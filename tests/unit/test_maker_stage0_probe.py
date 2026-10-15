"""MAKER S2 WP0 -- the read-only Stage-0 probe.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (e), (g), (i)3.

The I/O fixtures are a SYNTHETIC capture written through the production streaming writer and
read back through the production ``default_convert`` path (L-42, L-55); the real catalog is
never touched.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import StreamingFeatherWriter

from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
)
from breezy.analysis.maker_tape_census import PrintRecord
from scripts.analysis import maker_stage0_probe as p
from tests.unit.test_quote_tape_recorder import make_instrument

_NS = 1_000_000_000
_DAY = dt.date(2026, 9, 22)  # after trade capture started (09-17 09:00Z), pre-freeze
_LEVELS = 10


def _ns(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).replace(tzinfo=dt.UTC).timestamp()) * _NS


def _slug(city: str, rung: str = "gte89lt90f", day: str = "2026-09-22") -> str:
    return f"tc-temp-{city}high-{day}-{rung}"


# --------------------------------------------------------------------------------------
# Pure core
# --------------------------------------------------------------------------------------

_RUNG = "R"


def _print(side: str, price: str, ts: int, trade_id: str = "t", rung: str = _RUNG) -> PrintRecord:
    return PrintRecord(trade_id, ts, Decimal(price), side, rung, Decimal(1))


def _frames(*pairs: tuple[int, str | None]) -> dict[str, list[p.Frame]]:
    return {_RUNG: [p.Frame(ts, None if mid is None else Decimal(mid)) for ts, mid in pairs]}


def test_buyer_print_at_or_above_prior_mid_agrees() -> None:
    frames = _frames((10, "0.40"))
    prints = [
        _print("BUYER", "0.40", 20, "a"),  # tie agrees
        _print("BUYER", "0.45", 21, "b"),
        _print("BUYER", "0.30", 22, "c"),  # below the mid: disagrees
        _print("SELLER", "0.35", 23, "d"),
        _print("SELLER", "0.40", 24, "e"),  # tie agrees
        _print("SELLER", "0.41", 25, "f"),  # above the mid: disagrees
    ]

    result = p.direction_result(prints, frames)

    assert (result.buyer.n_agree, result.buyer.n_disagree, result.buyer.n_undefined) == (2, 1, 0)
    assert (result.seller.n_agree, result.seller.n_disagree, result.seller.n_undefined) == (2, 1, 0)
    assert result.buyer.agreement == pytest.approx(2 / 3)


def test_mid_comes_from_the_last_frame_strictly_before_the_print() -> None:
    frames = _frames((10, "0.40"), (20, "0.60"))

    result = p.direction_result([_print("BUYER", "0.50", 20)], frames)

    assert (result.buyer.n_agree, result.buyer.n_disagree) == (1, 0)  # frame@20 is not before 20


def test_undefined_mid_is_counted_not_disagreeing() -> None:
    frames = _frames((10, None), (30, "0.40"))
    prints = [
        _print("BUYER", "0.01", 5, "early"),  # no frame yet
        _print("SELLER", "0.99", 20, "onesided"),  # last frame has no two-sided mid
        _print("BUYER", "0.50", 40, "ok"),
        _print("BUYER", "0.50", 41, "other-rung", rung="X"),  # rung with no frames at all
    ]

    result = p.direction_result(prints, frames)

    assert (result.buyer.n_undefined, result.buyer.n_disagree, result.buyer.n_agree) == (2, 0, 1)
    assert (result.seller.n_undefined, result.seller.n_disagree) == (1, 0)
    assert result.buyer.n_defined == 1 and result.buyer.agreement == 1.0
    assert result.seller.agreement is None


def _tally(agree: int, disagree: int) -> p.SideTally:
    return p.SideTally(n_agree=agree, n_disagree=disagree, n_undefined=3)


def _result(buyer: p.SideTally, seller: p.SideTally) -> p.DirectionResult:
    return p.classify_direction(buyer, seller)


def test_agreement_at_or_above_point_nine_with_n_fixes_the_mapping() -> None:
    result = _result(_tally(180, 20), _tally(190, 10))

    assert result.verdict == "FIXED"
    assert p.enforce_direction(result) is result


def test_inconclusive_agreement_raises_stop_s2() -> None:
    result = _result(_tally(120, 80), _tally(150, 50))

    assert result.verdict == "INCONCLUSIVE"
    with pytest.raises(p.StopS2, match="S-2") as caught:
        p.enforce_direction(result)
    assert caught.value.result is result


def test_inverted_agreement_raises_stop_s2() -> None:
    result = _result(_tally(10, 190), _tally(20, 180))

    assert result.verdict == "INVERTED"
    with pytest.raises(p.StopS2, match="INVERTED") as caught:
        p.enforce_direction(result)
    assert caught.value.result.verdict == "INVERTED"


def test_mixed_sides_and_thin_samples_are_never_fixed() -> None:
    mixed = _result(_tally(190, 10), _tally(10, 190))
    thin = _result(_tally(199, 0), _tally(200, 0))  # buyer n_defined 199 < 200

    assert mixed.verdict == "INCONCLUSIVE"
    assert thin.verdict == "INSUFFICIENT"
    for result in (mixed, thin):
        with pytest.raises(p.StopS2):
            p.enforce_direction(result)


def test_first_replayable_day_follows_first_print_instant() -> None:
    # D needs the feed from D-1 16:50Z; otherwise D+1.
    assert p.first_replayable_day(_ns("2026-09-22T04:00:00")) == dt.date(2026, 9, 23)
    assert p.first_replayable_day(_ns("2026-09-22T16:50:00")) == dt.date(2026, 9, 23)
    assert p.first_replayable_day(_ns("2026-09-22T16:50:01")) == dt.date(2026, 9, 24)
    assert p.first_replayable_day(_ns("2026-09-17T09:00:00")) == dt.date(2026, 9, 18)


def test_gap_free_frames_drops_frames_inside_a_gap_and_an_open_gap_runs_on() -> None:
    frames = [p.Frame(10, Decimal("0.4")), p.Frame(25, Decimal("0.9")), p.Frame(40, Decimal("0.6"))]

    resolved = p.gap_free_frames(frames, [p.Gap(20, 30)])
    still_open = p.gap_free_frames(frames, [p.Gap(20, None)])

    assert [f.ts_ns for f in resolved] == [10, 40]
    assert [f.ts_ns for f in still_open] == [10]


def _pr(trade_id: str, side: str, ts: int = 1, price: str = "0.5") -> PrintRecord:
    return PrintRecord(trade_id, ts, Decimal(price), side, _RUNG, Decimal(2))


def test_duplicate_trade_id_or_no_aggressor_fails_census_reassert() -> None:
    clean = p.count_census({"a": [_pr("1", "BUYER", 1), _pr("2", "SELLER", 2)]})
    assert p.reassert_census(clean) is clean

    no_agg = p.count_census({"a": [_pr("1", "NO_AGGRESSOR")]})
    dup = p.count_census({"a": [_pr("1", "BUYER", 1), _pr("1", "BUYER", 2)]})
    twin = p.count_census({"a": [_pr("1", "BUYER"), _pr("2", "SELLER")]})

    assert (no_agg.no_aggressor, dup.duplicate_trade_ids, twin.opposite_side_twins) == (1, 1, 1)
    for counts in (no_agg, dup, twin):
        with pytest.raises(p.CensusViolation):
            p.reassert_census(counts)


def test_the_same_print_seen_by_two_instances_is_not_a_duplicate() -> None:
    counts = p.count_census({"a": [_pr("1", "BUYER")], "b": [_pr("1", "BUYER")]})

    assert (counts.duplicate_trade_ids, counts.opposite_side_twins) == (0, 0)
    assert counts.cross_instance_overlap == 1


def test_delta_is_per_instance_day_and_max_over_instances() -> None:
    window = (100, 200)
    samples = {
        "inst-a": [(100, -5 * _NS), (150, 2 * _NS), (250, 99 * _NS)],  # 250 is outside the window
        "inst-b": [(120, -9 * _NS)],
        "inst-c": [(300, 77 * _NS)],  # alive only outside the window: no entry at all
    }

    per_instance = p.instance_day_deltas(samples, window)

    assert {i: d.delta_ns for i, d in per_instance.items()} == {
        "inst-a": 5 * _NS,
        "inst-b": 9 * _NS,
    }
    assert per_instance["inst-a"].samples == 2
    assert (per_instance["inst-a"].min_offset_ns, per_instance["inst-a"].max_offset_ns) == (
        -5 * _NS,
        2 * _NS,
    )
    assert p.station_day_delta(per_instance) == 9 * _NS
    assert p.station_day_delta({}) is None


# --------------------------------------------------------------------------------------
# I/O layer: a synthetic capture through the production writer
# --------------------------------------------------------------------------------------

_WRITE_TYPES = [
    BinaryOption,
    TradeTick,
    QuoteTapeGap,
    VenueClockOffset,
    OrderBookDepth10,
    DepthTruncation,
]


def _instrument(slug: str, ts_init: int) -> BinaryOption:
    base = make_instrument(slug)
    return BinaryOption.from_dict({**BinaryOption.to_dict(base), "ts_init": ts_init})


def _depth(instrument: BinaryOption, bid: str, ask: str, ts: int) -> OrderBookDepth10:
    def side(px: str, order_side: OrderSide) -> list[BookOrder]:
        levels = [(px, "10")] + [("0.000", "0")] * (_LEVELS - 1)  # padded at instrument precision
        return [
            BookOrder(order_side, Price.from_str(price), Quantity.from_str(size), i)
            for i, (price, size) in enumerate(levels)
        ]

    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=side(bid, OrderSide.BUY),
        asks=side(ask, OrderSide.SELL),
        bid_counts=[1] * _LEVELS,
        ask_counts=[1] * _LEVELS,
        flags=0,
        sequence=0,
        ts_event=ts,
        ts_init=ts,
    )


def _trade(
    instrument: BinaryOption, trade_id: str, price: str, side: AggressorSide, ts: int
) -> TradeTick:
    return TradeTick(
        instrument.id,
        Price.from_str(price),
        Quantity.from_str("3"),
        side,
        TradeId(trade_id),
        ts,
        ts,
    )


def _gap(
    instrument: BinaryOption,
    *,
    start: int,
    end: int,
    resolved: bool,
    instance: str = "inst-a",
    seq: int = 1,
) -> QuoteTapeGap:
    ts = end if resolved else start
    return QuoteTapeGap(instrument.id, seq, start, end, resolved, instance, ts, ts)


def _write_instance(
    capture: Path,
    instance_id: str,
    *,
    instruments: list[BinaryOption],
    records: list[Any],
    offsets: list[tuple[int, int]],
) -> None:
    cache = Cache(database=None, config=CacheConfig())
    for instrument in instruments:
        cache.add_instrument(instrument)
    writer = StreamingFeatherWriter(
        path=str(capture / "live" / instance_id),
        cache=cache,
        clock=TestClock(),
        include_types=_WRITE_TYPES,
    )
    for instrument in instruments:
        writer.write(instrument)
    for ts, offset_ns in offsets:
        writer.write(VenueClockOffset("ws-transact-time", offset_ns, 1, ts, ts))
    for record in sorted(records, key=lambda r: r.ts_init):
        writer.write(record)
    writer.close()


_IN_WINDOW_OFFSETS = (
    (_ns("2026-09-22T01:00:00"), -5 * _NS),  # inside the bid-live window [D-1 16:50Z, D 02:50Z)
    (_ns("2026-09-22T02:00:00"), 2 * _NS),
)
_OUT_OF_WINDOW_OFFSET = (_ns("2026-09-22T06:00:00"), 660 * _NS)  # 11 min, no bid can be live


def _capture(
    tmp_path: Path, *, offsets: list[tuple[int, int]] | None = None, instance: str = "inst-a"
) -> Path:
    """LAX 2 rungs (listed before D-1 12:00Z), SFO 1 rung (listed late), NYC noise."""
    capture = tmp_path / "capture"
    lax = _instrument(_slug("lax"), _ns("2026-09-21T11:00:00"))
    lax2 = _instrument(_slug("lax", "gte90lt91f"), _ns("2026-09-21T11:00:00"))
    sfo = _instrument(_slug("sfo"), _ns("2026-09-21T13:00:00"))
    nyc = _instrument(_slug("nyc"), _ns("2026-09-21T11:00:00"))
    t = _ns
    records: list[Any] = [
        _depth(lax, "0.490", "0.510", t("2026-09-20T05:00:00")),  # before the day bound
        _depth(lax, "0.390", "0.410", t("2026-09-22T05:00:00")),  # mid .40
        _gap(
            lax, start=t("2026-09-22T02:10:00"), end=t("2026-09-22T02:20:00"), resolved=True, seq=2
        ),
        _gap(lax, start=t("2026-09-22T05:10:00"), end=t("2026-09-22T05:10:00"), resolved=False),
        _gap(lax, start=t("2026-09-22T05:10:00"), end=t("2026-09-22T05:20:00"), resolved=True),
        _depth(lax, "0.890", "0.910", t("2026-09-22T05:15:00")),  # inside the gap
        _depth(lax, "0.590", "0.610", t("2026-09-22T05:30:00")),  # after it: mid .60
        DepthTruncation(lax.id, 12, 14, 6, t("2026-09-22T05:30:00"), t("2026-09-22T05:30:00")),
        _depth(nyc, "0.390", "0.410", t("2026-09-22T05:00:00")),
        _trade(nyc, "nyc", "0.500", AggressorSide.BUYER, t("2026-09-22T04:00:00")),
        _trade(lax, "in-gap", "0.450", AggressorSide.BUYER, t("2026-09-22T05:12:00")),
        _trade(lax, "after", "0.500", AggressorSide.BUYER, t("2026-09-22T05:40:00")),
    ]
    _write_instance(
        capture,
        instance,
        instruments=[lax, lax2, sfo, nyc],
        records=records,
        offsets=offsets if offsets is not None else [*_IN_WINDOW_OFFSETS, _OUT_OF_WINDOW_OFFSET],
    )
    return capture


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
    }


def test_open_gap_row_is_superseded_by_its_resolved_row(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    # 'in-gap' sees the 05:00 frame (.40; the 05:15 frame is inside the gap): 0.45 >= .40 agrees.
    # 'after' sees the 05:30 frame (.60): 0.50 < .60 disagrees. Were the open row not superseded,
    # the 05:30 frame would stay contaminated and 'after' would read .40 and agree.
    assert (report.direction.buyer.n_agree, report.direction.buyer.n_disagree) == (1, 1)


def test_probe_reports_coverage_census_clocks_and_ladder(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    report = p.probe(
        capture,
        {_DAY},
        ("LAX", "SFO"),
        work_root=tmp_path / "work",
        first_print_ns=_ns("2026-09-22T04:00:00"),
    )

    assert report.first_replayable_day == "2026-09-23"
    assert report.depth_frames == 3 and report.truncated_frames == 1  # NYC frame is out of scope
    assert report.to_dict()["truncated_frame_share"] == pytest.approx(1 / 3)
    by_key = {(c.station, c.climate_day): c for c in report.coverage}
    lax, sfo = by_key[("LAX", "2026-09-22")], by_key[("SFO", "2026-09-22")]
    # live/gap hours are on the process-live window [D-1 16:50Z, D 02:50Z): alive 01:00..02:50
    assert lax.live_hours == pytest.approx(110 / 60)
    assert lax.gap_overlap_hours == pytest.approx(10 / 60)  # the 02:10 gap, not the 05:10 one
    # the S1 maker-window hours are a separate labelled column (alive 01:00..06:00, two gaps)
    assert lax.maker_live_hours == pytest.approx(5.0)
    assert lax.maker_gap_overlap_hours == pytest.approx(20 / 60)
    assert (lax.listing_abstain, sfo.listing_abstain) == (False, True)  # SFO listed after 12:00Z
    assert lax.listing_ns == _ns("2026-09-21T11:00:00")
    assert lax.delta_ns == 5 * _NS
    assert report.census.no_aggressor == 0 and report.census.duplicate_trade_ids == 0
    assert report.ladder_parity["LAX"] == {"rungs_per_day": {"2": 1}, "uniform": True}
    assert [d.delta_ns for d in report.delta_instance_days] == [5 * _NS, 5 * _NS]
    assert report.delta_distribution["max"] == 5 * _NS


def test_first_print_instant_ignores_nyc_and_undeclared_days(tmp_path: Path) -> None:
    capture = _capture(tmp_path)  # the earliest print on the tape (04:00) is NYC
    work = tmp_path / "work"

    maker = p.first_print_instant(capture, {_DAY}, work_root=work)
    other_day = p.first_print_instant(capture, {dt.date(2026, 9, 23)}, work_root=work)
    nyc_only = p.first_print_instant(capture, {_DAY}, work_root=work, stations=("NYC",))

    assert maker == _ns("2026-09-22T05:12:00")
    assert other_day is None  # no print for an undeclared day: None is a STOP for the driver
    assert nyc_only is None  # the firewall: NYC is never a licensed station


def test_positive_control_is_reported_for_the_named_station(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work", control_station="LAX")
    other = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work", control_station="SFO")

    assert report.control is not None and report.control.buyer.n_defined == 2
    assert other.control is not None and other.control.buyer.n_defined == 0


def test_probe_report_to_dict_is_json_serialisable_and_pinned(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")
    payload = report.to_dict()

    assert json.loads(json.dumps(payload, sort_keys=True)) == payload
    assert tuple(sorted(payload)) == (
        "census",
        "clocks",
        "coverage",
        "days",
        "delta_distribution",
        "delta_instance_days",
        "depth_frames",
        "direction",
        "first_print_ns",
        "first_replayable_day",
        "ladder_parity",
        "positive_control",
        "skipped_instances",
        "stations",
        "truncated_frame_share",
        "truncated_frames",
    )
    assert tuple(sorted(payload["direction"])) == (
        "buyer",
        "mid_age_ns",
        "seller",
        "thresholds",
        "verdict",
    )
    assert payload["direction"]["thresholds"] == {
        "fix_min": 0.9,
        "invert_max": 0.1,
        "min_defined_per_side": 200,
    }
    assert payload["clocks"]["print_ts_event"].startswith("venue tradeTime")
    assert payload["days"] == ["2026-09-22"]


def test_probe_never_writes_under_catalog_root(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    before = _tree(capture)

    p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")
    p.first_print_instant(capture, {_DAY}, work_root=tmp_path / "work")

    assert _tree(capture) == before


def test_work_root_inside_the_catalog_is_refused(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    with pytest.raises(ValueError, match="inside the capture root"):
        p.probe(capture, {_DAY}, ("LAX",), work_root=capture / "scratch")


# --------------------------------------------------------------------------------------
# Review fixes (pmr H1/H2, py M1-M4, ties, mid age)
# --------------------------------------------------------------------------------------


def _delta_of(report: p.ProbeReport, station: str = "LAX") -> int | None:
    return {c.station: c.delta_ns for c in report.coverage}[station]


def test_offset_outside_the_bidlive_window_does_not_raise_delta(tmp_path: Path) -> None:
    capture = _capture(tmp_path)  # 11 min offset at 06:00Z, after the bid-live window closes

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert _delta_of(report) == 5 * _NS
    assert max(d.delta_ns for d in report.delta_instance_days) <= 600 * _NS


def test_offset_inside_the_bidlive_window_raises_delta(tmp_path: Path) -> None:
    offsets = [(_ns("2026-09-22T01:00:00"), -5 * _NS), (_ns("2026-09-22T02:30:00"), 660 * _NS)]
    capture = _capture(tmp_path, offsets=offsets)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert _delta_of(report) == 660 * _NS
    assert report.delta_distribution["max"] == 660 * _NS


def test_a_station_day_without_offset_samples_has_unknown_delta_never_zero(tmp_path: Path) -> None:
    offsets = [_OUT_OF_WINDOW_OFFSET]  # alive, but no sample inside the bid-live window
    capture = _capture(tmp_path, offsets=offsets)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert _delta_of(report) is None
    assert report.delta_distribution["n"] == 0 and report.delta_distribution["min"] is None
    assert report.delta_distribution["n_unknown"] == 1


def test_queries_for_depth_and_trades_are_bounded_to_the_day_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    seen: list[tuple[type, Any, Any]] = []
    original = ParquetDataCatalog.query

    def spy(self: Any, data_cls: type, *args: Any, **kwargs: Any) -> Any:
        seen.append((data_cls, kwargs.get("start"), kwargs.get("end")))
        return original(self, data_cls, *args, **kwargs)

    monkeypatch.setattr(ParquetDataCatalog, "query", spy)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    start, end = _ns("2026-09-21T12:00:00"), _ns("2026-09-23T11:00:00")  # D-1 12:00Z .. D+1 end
    bounded = {OrderBookDepth10, TradeTick}
    calls = [c for c in seen if c[0] in bounded]
    assert {c[0] for c in calls} == bounded
    trades = [c for c in calls if c[0] is TradeTick]
    assert all((c[1], c[2]) == (start, end) for c in trades)
    # S-5: depth is read in disjoint inclusive slices whose union is exactly the day window
    depth = sorted({(c[1], c[2]) for c in calls if c[0] is OrderBookDepth10})  # per rung, same
    assert depth[0][0] == start and depth[-1][1] == end
    assert all(nxt[0] == prev[1] + 1 for prev, nxt in itertools.pairwise(depth))
    assert report.depth_frames == 3  # the 09-20 frame is never loaded


def test_malformed_and_non_clean_instances_are_recorded_as_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    (capture / "live" / "bad-inst").mkdir()  # an instance directory with no feather files

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert set(report.skipped) == {"bad-inst"}
    assert report.skipped["bad-inst"].startswith("PreflightError")
    assert report.to_dict()["skipped_instances"] == dict(report.skipped)

    monkeypatch.setattr(p, "classify_instance", lambda *a, **k: "LIVE")
    live = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work2")
    assert live.skipped["inst-a"] == "verdict LIVE"
    assert live.depth_frames == 0


def test_work_dir_that_already_exists_is_refused_and_left_alone(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    stale = tmp_path / "work" / "inst-a"
    stale.mkdir(parents=True)
    (stale / "leftover").write_text("keep")

    with pytest.raises(FileExistsError):
        p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert (stale / "leftover").read_text() == "keep"


def test_catalog_inside_the_work_root_is_refused(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    with pytest.raises(ValueError, match="inside the work root"):
        p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path)


def test_symlinked_work_root_into_the_catalog_is_refused(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(capture / "live", target_is_directory=True)

    with pytest.raises(ValueError, match="inside the capture root"):
        p.probe(capture, {_DAY}, ("LAX",), work_root=link)


def test_work_root_is_left_empty_after_a_run(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    work = tmp_path / "work"

    p.probe(capture, {_DAY}, ("LAX",), work_root=work)
    p.first_print_instant(capture, {_DAY}, work_root=work)

    assert work.is_dir() and not any(work.iterdir())


def test_cross_instance_duplicate_keeps_the_first_sorted_instances_print(tmp_path: Path) -> None:
    capture = _capture(tmp_path)  # inst-a: 'after' BUYER @0.50 vs prior mid .60 -> disagrees
    lax = _instrument(_slug("lax"), _ns("2026-09-21T11:00:00"))
    _write_instance(
        capture,
        "inst-b",
        instruments=[lax],
        records=[_trade(lax, "after", "0.700", AggressorSide.BUYER, _ns("2026-09-22T05:40:00"))],
        offsets=[(_ns("2026-09-22T01:00:00"), 0)],
    )

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert report.census.cross_instance_overlap == 1
    assert (report.direction.buyer.n_agree, report.direction.buyer.n_disagree) == (1, 1)


def test_probe_is_deterministic(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    first = p.probe(capture, {_DAY}, ("LAX", "SFO"), work_root=tmp_path / "work")
    second = p.probe(capture, {_DAY}, ("LAX", "SFO"), work_root=tmp_path / "work")

    assert first.to_dict() == second.to_dict()


def test_mid_age_distribution_is_reported_for_the_mids_used(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    # 'in-gap' uses the 05:00 mid (12 min old); 'after' uses 05:30 (10 min old)
    assert report.direction.mid_age_ns == {
        "n": 2, "min": 600 * _NS, "p50": 600 * _NS, "p95": 720 * _NS, "max": 720 * _NS,
    }  # fmt: skip
    assert report.to_dict()["direction"]["mid_age_ns"] == report.direction.mid_age_ns


def test_clocks_document_the_gap_clock_against_the_frame_clock() -> None:
    assert "recorder" in p.CLOCKS["gap_started_ns_ended_ns"]
    assert "venue" in p.CLOCKS["depth_ts_event"]


# --- ties --------------------------------------------------------------------------------


def test_ties_agree_but_are_counted_and_a_tie_excluded_rate_is_reported() -> None:
    frames = _frames((10, "0.40"))
    prints = [
        _print("BUYER", "0.40", 20, "a"),  # tie
        _print("BUYER", "0.45", 21, "b"),
        _print("BUYER", "0.30", 22, "c"),
        _print("SELLER", "0.40", 23, "d"),  # tie
        _print("SELLER", "0.40", 24, "e"),  # tie
        _print("SELLER", "0.41", 25, "f"),
    ]

    result = p.direction_result(prints, frames)

    assert (result.buyer.n_agree, result.buyer.n_tie) == (2, 1)
    assert (result.seller.n_agree, result.seller.n_tie) == (2, 2)
    assert result.buyer.to_dict()["agreement_excl_ties"] == pytest.approx(1 / 2)
    assert result.seller.to_dict()["agreement_excl_ties"] == pytest.approx(0 / 2)
    assert result.seller.agreement == pytest.approx(2 / 3)  # the frozen statistic keeps ties


def test_tie_excluded_rate_is_none_when_every_defined_print_is_a_tie() -> None:
    tally = p.SideTally(n_agree=3, n_disagree=0, n_undefined=0, n_tie=3)

    assert tally.to_dict()["agreement_excl_ties"] is None


# --- pure rules moved to the core --------------------------------------------------------


def test_mid_of_is_none_for_a_one_sided_book_else_the_exact_midpoint() -> None:
    lax = _instrument(_slug("lax"), 0)
    two_sided = _depth(lax, "0.390", "0.410", 1)
    one_sided = _depth(lax, "0.390", "0.410", 1)
    one_sided = OrderBookDepth10(
        one_sided.instrument_id, one_sided.bids, [
            BookOrder(OrderSide.SELL, Price.from_str("0.000"), Quantity.from_str("0"), i)
            for i in range(_LEVELS)
        ], [1] * _LEVELS, [1] * _LEVELS, 0, 0, 1, 1,
    )  # fmt: skip

    assert p.mid_of(two_sided) == Decimal("0.400")
    assert p.mid_of(one_sided) is None


def test_listing_abstain_when_unlisted_or_listed_after_the_window_opens() -> None:
    opens = _ns("2026-09-21T12:00:00")

    assert p.listing_abstain(None, opens) is True
    assert p.listing_abstain(opens + 1, opens) is True
    assert p.listing_abstain(opens, opens) is False
    assert p.listing_abstain(opens - 1, opens) is False


def test_distribution_summarises_n_min_p50_p95_max() -> None:
    assert p.distribution([]) == {"n": 0, "min": None, "p50": None, "p95": None, "max": None}
    assert p.distribution(list(range(1, 101))) == {
        "n": 100, "min": 1, "p50": 50, "p95": 95, "max": 100,
    }  # fmt: skip


def test_ladder_parity_flags_a_station_whose_rung_count_varies_by_day() -> None:
    d1, d2 = dt.date(2026, 9, 22), dt.date(2026, 9, 23)
    rungs = {("LAX", d1): {"a", "b"}, ("LAX", d2): {"a"}, ("SFO", d1): {"a"}, ("SFO", d2): {"b"}}

    parity = p.ladder_parity(rungs, ("LAX", "SFO", "MIA"))

    assert parity["LAX"] == {"rungs_per_day": {"1": 1, "2": 1}, "uniform": False}
    assert parity["SFO"] == {"rungs_per_day": {"1": 2}, "uniform": True}
    assert parity["MIA"] == {"rungs_per_day": {}, "uniform": True}


def test_station_day_key_admits_only_yes_leg_maker_station_days_in_scope() -> None:
    def key(slug: str, days: set[dt.date], stations: set[str]) -> object:
        return p.station_day_key(_instrument(slug, 0).id, days, stations)

    days = {_DAY}
    assert key(_slug("lax"), days, {"LAX"}) == ("LAX", _DAY)
    assert key(_slug("nyc"), days, {"LAX", "NYC"}) is None  # firewall
    assert key(_slug("lax"), {dt.date(2026, 9, 23)}, {"LAX"}) is None  # undeclared day
    assert key(_slug("lax"), days, {"SFO"}) is None  # unrequested station


# --------------------------------------------------------------------------------------
# S-7 estimator: dense samples through the real writer path; n_backwards_ts_event
# --------------------------------------------------------------------------------------


def test_dense_offset_samples_report_the_despiked_delta_and_the_raw_one(tmp_path: Path) -> None:
    t = _ns("2026-09-22T01:00:00")
    dense = [(t, 165_000_000), (t + 45 * _NS, 789_800_000_000), (t + 90 * _NS, 193_000_000)]
    capture = _capture(tmp_path, offsets=dense)

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert _delta_of(report) == 10_193_000_000
    (row,) = [d for d in report.delta_instance_days if d.station == "LAX"]
    assert (row.delta_ns, row.raw_delta_ns) == (10_193_000_000, 789_800_000_000)
    assert (row.n_despiked, row.n_unconfirmable, row.samples) == (1, 2, 3)
    assert report.delta_distribution["max"] == 10_193_000_000
    assert report.delta_distribution["raw_max"] == 789_800_000_000
    assert report.delta_distribution["n_despiked"] == 1
    payload = report.to_dict()["delta_instance_days"][0]
    assert {"raw_delta_ns", "n_despiked", "n_unconfirmable"} <= set(payload)


def test_sparse_samples_keep_the_old_behaviour_and_report_nothing_despiked(tmp_path: Path) -> None:
    report = p.probe(_capture(tmp_path), {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert report.delta_distribution["raw_max"] == 5 * _NS
    assert report.delta_distribution["n_despiked"] == 0


def _depth_at(instrument: BinaryOption, event_ts: int, init_ts: int) -> OrderBookDepth10:
    base = _depth(instrument, "0.490", "0.510", init_ts)
    return OrderBookDepth10(
        base.instrument_id, base.bids, base.asks, base.bid_counts, base.ask_counts,
        base.flags, base.sequence, event_ts, init_ts,
    )  # fmt: skip


def test_backwards_ts_event_depth_frames_are_counted_per_rung_and_summed_per_station_day(
    tmp_path: Path,
) -> None:
    t = _ns
    lax = _instrument(_slug("lax"), t("2026-09-21T11:00:00"))
    lax2 = _instrument(_slug("lax", "gte90lt91f"), t("2026-09-21T11:00:00"))
    records: list[Any] = []
    for inst in (lax, lax2):
        records += [
            _depth_at(inst, t("2026-09-22T05:00:00"), t("2026-09-22T05:00:00")),
            _depth_at(inst, t("2026-09-22T05:30:00"), t("2026-09-22T05:30:00")),
            _depth_at(inst, t("2026-09-22T05:10:00"), t("2026-09-22T05:31:00")),  # stale: backwards
            _depth_at(inst, t("2026-09-22T05:10:00"), t("2026-09-22T05:32:00")),  # equal: not below
        ]
    capture = tmp_path / "capture"
    _write_instance(capture, "inst-a", instruments=[lax, lax2], records=records, offsets=[])

    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    (row,) = report.coverage
    assert report.depth_frames == 8
    assert row.n_backwards_ts_event == 2
    assert report.to_dict()["coverage"][0]["n_backwards_ts_event"] == 2


def test_a_monotone_depth_stream_has_zero_backwards_ts_event(tmp_path: Path) -> None:
    report = p.probe(_capture(tmp_path), {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert [c.n_backwards_ts_event for c in report.coverage] == [0]
