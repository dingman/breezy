"""MAKER-S2 WP6: raw capture records -> the WP4 event stream (pure; no I/O, no truth)."""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_events_build as eb
from scripts.analysis.maker_stage0_fill_events import (
    BUYER,
    NO_AGGRESSOR,
    SELLER,
    Cut,
    DepthFrame,
    Episode,
    ForecastVector,
    GapMark,
    Kind,
    Print,
    validate_events,
)
from scripts.analysis.maker_stage0_inputs import UnitHypothesis

D = Decimal
WINDOW = (0, 10**15)


def _frame(rung: str = "R", ts: int = 100, bid: str = "0.15", ask: str = "0.25") -> eb.RawFrame:
    return eb.RawFrame(rung, ts, ((D(bid), D("10")),), ((D(ask), D("10")),))


def _slice(instance: str = "i1", **kw: object) -> eb.InstanceSlice:
    base: dict[str, object] = {
        "frames": (), "prints": (), "gaps": (), "truncations": (),
    }  # fmt: skip
    base.update(kw)
    return eb.InstanceSlice(instance, **base)  # type: ignore[arg-type]


def _contracts(size: Decimal, price: Decimal, aggressor: str | None) -> Decimal:
    return size


def _build(*slices: eb.InstanceSlice, size_of=_contracts, window=WINDOW) -> eb.DataEvents:  # type: ignore[no-untyped-def]
    return eb.build_data_events(list(slices), size_of=size_of, window=window)


def test_events_are_totally_ordered_and_pass_wp4_validation() -> None:
    pr = eb.RawPrint("t1", "R", 100, D("0.25"), D("3"), "BUYER")
    built = _build(_slice(frames=(_frame(ts=100), _frame(ts=50)), prints=(pr,)))
    validate_events(built.events)
    kinds = [(e.ts_ns, e.kind) for e in built.events]
    assert kinds == [(50, Kind.DEPTH), (100, Kind.PRINT), (100, Kind.DEPTH)]  # print before frame
    assert built.n_depth_frames == 2 and built.rungs_with_books == frozenset({"R"})


def test_prices_become_integer_cents_and_pad_levels_are_dropped() -> None:
    frame = eb.RawFrame(
        "R", 1, ((D("0.150"), D("10")), (D("0.000"), D("0"))), ((D("0.250"), D("0")),)
    )
    out = _build(_slice(frames=(frame,))).events[0].payload
    assert isinstance(out, DepthFrame)
    assert out.yes_bids == ((15, 10),) and out.yes_asks == ()
    assert out.instance_id == "i1" and out.ts_ns == 1


def test_non_integer_cent_price_is_refused_loudly() -> None:
    with pytest.raises(eb.EventBuildError, match="cent"):
        _build(_slice(frames=(_frame(ask="0.2505"),)))


def test_unit_conversion_applies_to_print_and_depth_sizes_with_aggressor_aware_prices() -> None:
    calls: list[tuple[Decimal, Decimal, str | None]] = []

    def spy(size: Decimal, price: Decimal, aggressor: str | None) -> Decimal:
        calls.append((size, price, aggressor))
        return size / 2

    pr = eb.RawPrint("t1", "R", 100, D("0.25"), D("7"), "BUYER")
    built = _build(_slice(frames=(_frame(),), prints=(pr,)), size_of=spy)
    payloads = [e.payload for e in built.events]
    pri = next(p for p in payloads if isinstance(p, Print))
    dep = next(p for p in payloads if isinstance(p, DepthFrame))
    assert pri.size == 3  # 7/2 = 3.5 floors: fewer contracts credited (pessimistic for fills)
    assert dep.yes_asks == ((25, 5),) and dep.yes_bids == ((15, 5),)  # 10/2 = 5 exact
    assert (D("10"), D("0.25"), BUYER) in calls  # an ask level is lifted by a YES buyer
    assert (D("10"), D("0.15"), SELLER) in calls  # a bid level is hit by a YES seller


def test_fractional_depth_sizes_round_up_so_the_queue_is_never_understated() -> None:
    frame = eb.RawFrame("R", 1, ((D("0.15"), D("10")),), ((D("0.25"), D("10")),))
    hyp = UnitHypothesis("USD_NOTIONAL_YES")  # size / yes_price
    ask = _build(_slice(frames=(frame,)), size_of=hyp.to_contracts).events[0].payload
    assert isinstance(ask, DepthFrame)
    assert ask.yes_asks == ((25, 40),)  # 10 / 0.25
    assert ask.yes_bids == ((15, 67),)  # 10 / 0.15 = 66.67 -> 67


def test_no_aggressor_prints_are_never_emitted() -> None:
    pr = eb.RawPrint("t1", "R", 100, D("0.25"), D("3"), NO_AGGRESSOR)
    built = _build(_slice(prints=(pr,)))
    assert built.events == () and built.n_no_aggressor == 1


def test_truncation_rows_flag_the_side_with_more_than_ten_levels() -> None:
    trunc = eb.RawTruncation("R", 100, bid_levels_seen=12, ask_levels_seen=9)
    both = eb.RawTruncation("R", 200, bid_levels_seen=11, ask_levels_seen=14)
    built = _build(
        _slice(frames=(_frame(ts=100), _frame(ts=200), _frame(ts=300)), truncations=(trunc, both))
    )
    flags = [(e.payload.asks_truncated, e.payload.bids_truncated) for e in built.events]  # type: ignore[union-attr]
    assert flags == [(False, True), (True, True), (False, False)]


def test_a_trade_id_yields_one_print_and_a_copy_in_another_instances_segment_is_dropped() -> None:
    pr = eb.RawPrint("t1", "R", 15, D("0.25"), D("3"), "BUYER")  # inside a's segment [10, 20)
    twin = dataclasses.replace(pr, ts_ns=16)  # same trade_id re-delivered by the same instance
    a = _slice("a", frames=(_frame(ts=10),), prints=(pr, twin))
    b = _slice("b", frames=(_frame(ts=20),), prints=(dataclasses.replace(pr, ts_ns=25),))
    prints = [e.payload for e in _build(a, b).events if isinstance(e.payload, Print)]
    assert len(prints) == 1 and prints[0].instance_id == "a"


def test_later_instance_takes_over_at_its_first_event_and_clips_open_gaps() -> None:
    a = _slice(
        "a",
        frames=(_frame(ts=10), _frame(ts=60)),  # the 60 frame is after b took over: dropped
        gaps=(eb.RawGap("R", 30, None),),
    )
    b = _slice("b", frames=(_frame(ts=50),))
    built = _build(a, b)
    frames = [
        (e.ts_ns, e.payload.instance_id) for e in built.events if isinstance(e.payload, DepthFrame)
    ]
    assert frames == [(10, "a"), (50, "b")]
    gaps = [(e.ts_ns, e.kind) for e in built.events if isinstance(e.payload, GapMark)]
    assert gaps == [(30, Kind.GAP_START), (50, Kind.GAP_END)]  # a's open gap ends at hand-over


def test_last_instances_open_gap_runs_on() -> None:
    built = _build(_slice("a", frames=(_frame(ts=10),), gaps=(eb.RawGap("R", 30, None),)))
    gaps = [e.kind for e in built.events if isinstance(e.payload, GapMark)]
    assert gaps == [Kind.GAP_START]


def test_events_outside_the_window_are_dropped_but_the_last_book_before_it_is_kept() -> None:
    frames = (_frame(ts=5), _frame(ts=15), _frame(ts=25), _frame(ts=95))
    built = _build(_slice(frames=frames), window=(20, 90))
    assert [e.ts_ns for e in built.events] == [15, 25]
    assert built.n_depth_frames == 1  # only frames INSIDE the window count toward coverage


def test_clock_events_get_seq_after_the_data_events_and_merge_in_order() -> None:
    built = _build(_slice(frames=(_frame(ts=100),)))
    vec = ForecastVector(100, {"R": 0.01}, {"R": 0.02}, 7, "sha", "v5.0")
    clock = eb.clock_events(
        [eb.CutSpec(50, "CANCEL_PROCESS", True), eb.CutSpec(100, "GTD_EXPIRY", True)], [vec]
    )
    merged = eb.merge_events(built, clock)
    validate_events(merged)
    assert [(e.ts_ns, e.kind) for e in merged] == [
        (50, Kind.CANCEL),
        (100, Kind.CANCEL),
        (100, Kind.DEPTH),
        (100, Kind.FORECAST_RELEASE),
    ]
    assert isinstance(merged[0].payload, Cut)
    assert len({e.seq for e in merged}) == len(merged)


def _episode(end_ns: int) -> Episode:
    values: dict[str, object] = {f.name: None for f in dataclasses.fields(Episode)}
    values.update(
        station="SFO", climate_day="2026-09-29", rung_id="R", t0_ns=1, end_ns=end_ns,
        end_reason="X", bid_cents=75, a_gt=0, a_eq=0, gap_ns_subtracted=0, unit_hypothesis="H",
    )  # fmt: skip
    return Episode(**values)  # type: ignore[arg-type]


def test_episode_past_local_midnight_of_d_raises() -> None:
    day = dt.date(2026, 9, 29)
    midnight = int(dt.datetime(2026, 9, 29, 8, 0, tzinfo=dt.UTC).timestamp()) * 10**9  # SFO LST
    eb.assert_before_local_midnight(_episode(midnight), "SFO", day)  # ends AT midnight: allowed
    with pytest.raises(eb.LocalDayViolation, match="S-6"):
        eb.assert_before_local_midnight(_episode(midnight + 1), "SFO", day)


def test_events_module_has_no_truth_or_io_imports() -> None:
    tree = ast.parse(Path(eb.__file__).read_text())
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not [m for m in imported if "inputs" in m or "verify_first" in m or "truth" in m]


def test_replay_counts_wanted_rungs_that_never_had_a_book() -> None:
    from scripts.analysis.maker_stage0_adapter import WantTracker
    from scripts.analysis.maker_stage0_fill_events import Decision

    tracker = WantTracker(wanted_without_book={"A", "B"})
    data = _build(_slice(frames=(_frame("B", ts=10),)))
    day = dt.date(2026, 9, 29)
    got = eb.replay_station_day(
        data, (), selector=lambda _ctx: Decision(), tracker=tracker, station="SFO", day=day,
        unit_hypothesis="H", live_from_ns=0, delta_ns=0,
    )  # fmt: skip
    assert got.n_no_book_wants == 1  # B had a book, A never did
    assert got.n_events == 1 and got.result.summary.n_attempts == 0


def test_hand_over_is_at_the_later_instances_first_event_of_any_kind() -> None:
    quiet = _slice(
        "a",
        frames=(_frame(ts=100),),
        prints=(eb.RawPrint("t1", "R", 10, D("0.25"), D("3"), "BUYER"),),
    )  # its FIRST event is a print at 10; its first frame is only at 100
    busy = _slice("b", frames=(_frame(ts=50),))
    frames = [
        (e.ts_ns, e.payload.instance_id)
        for e in _build(quiet, busy).events
        if isinstance(e.payload, DepthFrame)
    ]
    assert frames == [(50, "b")]  # b took over at its start (50); a's frame at 100 is dropped


def test_a_gap_or_truncation_row_counts_as_an_instances_first_event() -> None:
    older = _slice("a", frames=(_frame(ts=100),), gaps=(eb.RawGap("R", 5, 8),))
    younger = _slice("b", frames=(_frame(ts=50),))
    frames = [e.payload.instance_id for e in _build(older, younger).events
              if isinstance(e.payload, DepthFrame)]  # fmt: skip
    assert frames == ["b"]
    assert "first depth frame" not in (eb.__doc__ or "")


def test_rounding_counters_report_floored_prints_and_ceil_raised_levels() -> None:
    def half(size: Decimal, price: Decimal, aggressor: str | None) -> Decimal:
        return size / 2

    frame = eb.RawFrame("R", 100, ((D("0.15"), D("3")),), ((D("0.25"), D("4")),))
    prints = (
        eb.RawPrint("t1", "R", 100, D("0.25"), D("1"), "BUYER"),  # 0.5 -> floors to 0
        eb.RawPrint("t2", "R", 100, D("0.25"), D("3"), "BUYER"),  # 1.5 -> 1
    )
    built = _build(_slice(frames=(frame,), prints=prints), size_of=half)
    assert built.n_levels == 2 and built.n_levels_ceil_raised == 1  # 1.5 -> 2 raised; 2 exact
    assert built.n_prints == 2 and built.n_prints_floored_zero == 1
