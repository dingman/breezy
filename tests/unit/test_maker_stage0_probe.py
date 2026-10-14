"""MAKER S2 WP0 -- the read-only Stage-0 probe.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (e), (g), (i)3.

The I/O fixtures are a SYNTHETIC capture written through the production streaming writer and
read back through the production ``default_convert`` path (L-42, L-55); the real catalog is
never touched.
"""

from __future__ import annotations

import datetime as dt
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
    instrument: BinaryOption, *, start: int, end: int, resolved: bool, instance: str = "inst-a"
) -> QuoteTapeGap:
    ts = end if resolved else start
    return QuoteTapeGap(instrument.id, 1, start, end, resolved, instance, ts, ts)


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


def _capture(tmp_path: Path) -> Path:
    """LAX 2 rungs (listed before D-1 12:00Z), SFO 1 rung (listed late), NYC noise."""
    capture = tmp_path / "capture"
    lax = _instrument(_slug("lax"), _ns("2026-09-21T11:00:00"))
    lax2 = _instrument(_slug("lax", "gte90lt91f"), _ns("2026-09-21T11:00:00"))
    sfo = _instrument(_slug("sfo"), _ns("2026-09-21T13:00:00"))
    nyc = _instrument(_slug("nyc"), _ns("2026-09-21T11:00:00"))
    t = _ns
    records: list[Any] = [
        _depth(lax, "0.390", "0.410", t("2026-09-22T05:00:00")),  # mid .40
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
        "inst-a",
        instruments=[lax, lax2, sfo, nyc],
        records=records,
        offsets=[(t("2026-09-22T05:00:00"), -5 * _NS), (t("2026-09-22T06:00:00"), 2 * _NS)],
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
    assert lax.live_hours == pytest.approx(1.0)
    assert lax.gap_overlap_hours == pytest.approx(10 / 60)
    assert (lax.listing_abstain, sfo.listing_abstain) == (False, True)  # SFO listed after 12:00Z
    assert lax.listing_ns == _ns("2026-09-21T11:00:00")
    assert lax.delta_ns == 5 * _NS
    assert report.census.no_aggressor == 0 and report.census.duplicate_trade_ids == 0
    assert report.ladder_parity["LAX"] == {"rungs_per_day": {"2": 1}, "uniform": True}
    assert [d.delta_ns for d in report.delta_instance_days] == [5 * _NS, 5 * _NS]
    assert report.delta_distribution["max"] == 5 * _NS


def test_first_print_instant_reads_timestamps_only_across_all_stations(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    assert p.first_print_instant(capture, work_root=tmp_path / "work") == _ns("2026-09-22T04:00:00")


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
        "stations",
        "truncated_frame_share",
        "truncated_frames",
    )
    assert tuple(sorted(payload["direction"])) == (
        "buyer",
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
    p.first_print_instant(capture, work_root=tmp_path / "work")

    assert _tree(capture) == before


def test_work_root_inside_the_catalog_is_refused(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    with pytest.raises(ValueError, match="inside the capture root"):
        p.probe(capture, {_DAY}, ("LAX",), work_root=capture / "scratch")
