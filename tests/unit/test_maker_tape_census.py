"""MAKER S1 WP1 -- the maker-window print census (pure core + sidecar script).

Plan: docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md, WP1.

The script-level fixtures are written through the production streaming writer
(``StreamingFeatherWriter``) and read back through the production
``default_convert`` path with no injected seam (L-42, L-55).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.model.identifiers import TradeId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import StreamingFeatherWriter

from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap, VenueClockOffset
from breezy.analysis import maker_tape_census as mtc
from breezy.analysis.maker_tape_census import (
    AliveSpan,
    CensusedDay,
    FirewallRefused,
    GapInterval,
    PrintRecord,
    admit_print,
    classify,
    covered_intervals,
    maker_window_ns,
    read_censused_days,
    require_firewall_clearance,
    summarise,
    tally_prints,
    write_censused_days,
)
from tests.unit.test_quote_tape_recorder import make_instrument

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import maker_tape_census as census_script  # type: ignore[import-not-found]

_NS = 1_000_000_000
_HOUR = 3600 * _NS
_DECLARATION = REPO_ROOT / "docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md"


def _ns(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).replace(tzinfo=dt.UTC).timestamp()) * _NS


def _slug(city: str, day: str, rung: str = "gte89lt90f") -> str:
    return f"tc-temp-{city}high-{day}-{rung}"


_DAY = dt.date(2026, 9, 22)  # pre-freeze, after trade capture started (09-17 09:00Z)
_LAX_WINDOW = maker_window_ns(climate_day=_DAY, std_utc_offset_hours=-8)


# --------------------------------------------------------------------------------------
# Pure core
# --------------------------------------------------------------------------------------


def test_maker_window_spans_d_minus_1_noon_utc_to_stale_derived_end() -> None:
    window = maker_window_ns(climate_day=dt.date(2026, 9, 22), std_utc_offset_hours=-8)

    assert window.start_ns == _ns("2026-09-21T12:00:00")
    assert window.end_ns == _ns("2026-09-22T11:00:00")  # D 01:00Z + STALE_H 8 + NBP_LAG_UB 2
    assert window.binding == "STALE_DERIVED"


def test_cancel_lst_backstop_binds_when_earlier() -> None:
    # A station east of the date line cannot occur in the registry; the backstop is the
    # arithmetic guard, so exercise it with an offset that puts 09:00 LST before 11:00Z.
    window = maker_window_ns(climate_day=dt.date(2026, 9, 22), std_utc_offset_hours=5)

    assert window.end_ns == _ns("2026-09-22T04:00:00")
    assert window.binding == "CANCEL_LST"


def test_post_freeze_day_refused_without_matching_declaration_sha() -> None:
    post_freeze = dt.date(2026, 10, 2)

    with pytest.raises(FirewallRefused):
        require_firewall_clearance("LAX", post_freeze, None)
    with pytest.raises(FirewallRefused):
        require_firewall_clearance("LAX", post_freeze, "0" * 64)
    assert (
        require_firewall_clearance("LAX", post_freeze, mtc.SEARCH_DECLARATION_SHA256)
        == "SEARCH_DECLARED"
    )
    assert require_firewall_clearance("LAX", dt.date(2026, 9, 25), None) == "PRE_FREEZE"


def test_pinned_declaration_sha_matches_the_committed_declaration_file() -> None:
    digest = hashlib.sha256(_DECLARATION.read_bytes()).hexdigest()

    assert digest == mtc.SEARCH_DECLARATION_SHA256
    assert digest == "38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6"


def test_post_freeze_day_outside_declared_range_refused() -> None:
    sha = mtc.SEARCH_DECLARATION_SHA256

    with pytest.raises(FirewallRefused):
        require_firewall_clearance("LAX", dt.date(2026, 10, 14), sha)
    with pytest.raises(FirewallRefused):
        require_firewall_clearance("LAX", dt.date(2026, 9, 26) - dt.timedelta(days=0), None)
    assert require_firewall_clearance("MIA", dt.date(2026, 10, 13), sha) == "SEARCH_DECLARED"


def test_nyc_is_refused_even_with_declaration() -> None:
    with pytest.raises(FirewallRefused):
        require_firewall_clearance("NYC", dt.date(2026, 9, 22), mtc.SEARCH_DECLARATION_SHA256)
    with pytest.raises(FirewallRefused):
        require_firewall_clearance("NYC", dt.date(2026, 10, 2), mtc.SEARCH_DECLARATION_SHA256)


def test_nyc_prints_never_reach_a_count() -> None:
    requested = frozenset({_DAY})

    assert admit_print("NYC", _DAY, requested) is False
    assert admit_print("LAX", _DAY, requested) is True
    # A requested-stations narrowing is honoured too.
    assert admit_print("MIA", _DAY, requested, frozenset({"LAX"})) is False


def test_out_of_range_day_prints_never_reach_a_count() -> None:
    requested = frozenset({_DAY})

    assert admit_print("LAX", _DAY + dt.timedelta(days=1), requested) is False
    assert admit_print("LAX", _DAY - dt.timedelta(days=1), requested) is False


def test_pre_trade_capture_rows_are_emitted_without_reading_tape() -> None:
    day = dt.date(2026, 9, 17)  # window starts 09-16 12:00Z, before capture start
    window = maker_window_ns(climate_day=day, std_utc_offset_hours=-8)

    row = classify(
        station="LAX",
        climate_day=day,
        firewall_class="PRE_FREEZE",
        window=window,
        clean_instances=7,
        trade_parse_failed=True,
        spans=(),
        prints=(),
        first_seen_ns=None,
    )

    assert row.reason == "PRE_TRADE_CAPTURE"
    assert row.instances_clean == 0
    assert row.buyer_by_bucket == (0, 0, 0, 0)
    assert summarise([row]).n_cov == 0
    assert maker_window_ns(climate_day=dt.date(2026, 9, 18), std_utc_offset_hours=-8).start_ns >= (
        mtc.TRADE_CAPTURE_START_NS
    )


def test_unresolved_gap_contaminates_to_window_end() -> None:
    start, end = _LAX_WINDOW.start_ns, _LAX_WINDOW.end_ns
    gap_at = start + 10 * _HOUR
    span = AliveSpan(start, end, (GapInterval(gap_at, None),))

    covered = covered_intervals((start, end), (span,))

    assert covered == ((start, gap_at),)


def test_coverage_is_alive_span_minus_gaps_not_book_density() -> None:
    start, end = _LAX_WINDOW.start_ns, _LAX_WINDOW.end_ns
    gap = GapInterval(start + 5 * _HOUR, start + 5 * _HOUR + 30 * 60 * _NS)
    span = AliveSpan(start, end, (gap,))

    row = classify(
        station="LAX",
        climate_day=_DAY,
        firewall_class="PRE_FREEZE",
        window=_LAX_WINDOW,
        clean_instances=1,
        trade_parse_failed=False,
        spans=(span,),
        prints=(),  # zero prints at all: a quiet book is still a covered day
        first_seen_ns=None,
    )

    assert row.reason == "COVERED"
    assert row.longest_hole_min == 30
    assert row.coverage_fraction == pytest.approx(1 - 0.5 / 23)
    assert row.tail_span_only is False


def test_tail_span_only_failure_is_flagged() -> None:
    start = _LAX_WINDOW.start_ns

    def run(alive_minutes: int) -> CensusedDay:
        return classify(
            station="LAX",
            climate_day=_DAY,
            firewall_class="PRE_FREEZE",
            window=_LAX_WINDOW,
            clean_instances=1,
            trade_parse_failed=False,
            spans=(AliveSpan(start, start + alive_minutes * 60 * _NS, ()),),
            prints=(),
            first_seen_ns=None,
        )

    low_tail = run(20 * 60)  # 3 h tail hole: fraction 0.87, passes if the tail is counted
    long_tail = run(21 * 60 + 30)  # 90 min tail hole: fraction 0.93, hole over 60 min
    gone = classify(
        station="LAX",
        climate_day=_DAY,
        firewall_class="PRE_FREEZE",
        window=_LAX_WINDOW,
        clean_instances=1,
        trade_parse_failed=False,
        spans=(
            AliveSpan(
                start,
                start + 20 * _HOUR,
                (GapInterval(start + 2 * _HOUR, start + 5 * _HOUR),),  # an interior outage too
            ),
        ),
        prints=(),
        first_seen_ns=None,
    )

    assert (low_tail.reason, low_tail.tail_span_only) == ("LOW_COVERAGE", True)
    assert (long_tail.reason, long_tail.tail_span_only) == ("LONG_HOLE", True)
    assert (gone.reason, gone.tail_span_only) == ("LOW_COVERAGE", False)
    assert summarise([low_tail, long_tail, gone]).tail_span_only == 2


def _print(
    trade_id: str, price: str, aggressor: str, *, rung: str = "r1", ts: int = 0
) -> PrintRecord:
    return PrintRecord(
        trade_id=trade_id,
        ts_event_ns=_LAX_WINDOW.start_ns + 1 + ts,
        price_yes=Decimal(price),
        aggressor=aggressor,
        rung=rung,
    )


def test_a_print_seen_by_two_overlapping_instances_counts_once() -> None:
    same = _print("t1", "0.25", "BUYER")

    tally = tally_prints((same, same, _print("t2", "0.25", "BUYER", ts=5)), *_window_pair())

    assert tally.buyer_by_bucket == (0, 0, 2, 0)


def _window_pair() -> tuple[int, int]:
    return _LAX_WINDOW.start_ns, _LAX_WINDOW.end_ns


def test_seller_and_no_aggressor_prints_never_qualify() -> None:
    prints = (
        _print("a", "0.40", "SELLER"),
        _print("b", "0.40", "NO_AGGRESSOR", ts=1),
        _print("c", "0.40", "SELLER", ts=2),
    )

    tally = tally_prints(prints, *_window_pair())

    assert tally.buyer_by_bucket == (0, 0, 0, 0)
    assert (tally.prints_seller, tally.prints_no_aggressor) == (2, 1)
    assert tally.rungs_with_qualifying_buyer == 0


def test_buyer_print_below_020_never_qualifies() -> None:
    prints = (
        _print("a", "0.05", "BUYER"),
        _print("b", "0.19", "BUYER", ts=1),
        _print("c", "0.20", "BUYER", ts=2, rung="r2"),
        _print("d", "0.30", "BUYER", ts=3, rung="r3"),
        _print("e", "0.99", "BUYER", ts=4, rung="r3"),
    )

    tally = tally_prints(prints, *_window_pair())

    assert tally.buyer_by_bucket == (1, 1, 1, 2)
    assert tally.rungs_with_qualifying_buyer == 2  # r2, r3 -- r1 only ever printed below 0.20
    row = _covered_row(prints)
    assert row.reason == "COVERED"
    assert row.buyer_by_bucket == (1, 1, 1, 2)


def _covered_row(
    prints: tuple[PrintRecord, ...], *, station: str = "LAX", day: dt.date = _DAY
) -> CensusedDay:
    start, end = _LAX_WINDOW.start_ns, _LAX_WINDOW.end_ns
    return classify(
        station=station,
        climate_day=day,
        firewall_class="PRE_FREEZE",
        window=_LAX_WINDOW,
        clean_instances=1,
        trade_parse_failed=False,
        spans=(AliveSpan(start, end, ()),),
        prints=prints,
        first_seen_ns=None,
    )


def _summary_rows(per_date: dict[dt.date, tuple[int, int]]) -> list[CensusedDay]:
    """per_date: date -> (covered units, how many of them carry a qualifying buyer)."""
    stations = ("LAX", "MDW", "MIA", "SFO")
    rows: list[CensusedDay] = []
    for day, (covered, with_buyer) in per_date.items():
        for index in range(covered):
            prints = (_print(f"{day}-{index}", "0.25", "BUYER"),) if index < with_buyer else ()
            rows.append(_covered_row(prints, station=stations[index], day=day))
    return rows


def test_n_eff_ub_matches_hand_formula_for_mixed_dates() -> None:
    # m=4 -> 4/(1+3*.5)=1.6 ; m=2 -> 2/(1+.5)=1.3333 ; m=1 -> 1.0
    rows = _summary_rows(
        {dt.date(2026, 9, 18): (4, 0), dt.date(2026, 9, 19): (2, 0), dt.date(2026, 9, 20): (1, 0)}
    )

    summary = summarise(rows)

    assert summary.n_cov == 7
    assert summary.d_cov == 3
    assert summary.n_eff_ub == pytest.approx(1.6 + 4 / 3 + 1.0)
    assert mtc.RHO_ASSUMED == 0.5
    assert "S-1" in summary.stops  # nowhere near 30


def test_c_below_005_fires_s5() -> None:
    # 10 dates x 4 covered units = 40 station-days; vary how many carry a qualifying buyer.
    def with_buyers(count: int) -> Any:
        days = {dt.date(2026, 9, 18) + dt.timedelta(days=i): (4, 0) for i in range(10)}
        days[dt.date(2026, 9, 18)] = (4, count)
        return summarise(_summary_rows(days))

    below = with_buyers(1)  # C = 0.025
    on_line = with_buyers(2)  # C = 0.05: not below the stop line, but KILL-LIKELY
    inside = with_buyers(3)  # C = 0.075
    clear = with_buyers(4)  # C = 0.10

    assert below.n_cov == 40
    assert below.c == pytest.approx(0.025)
    assert "S-5" in below.stops and below.flag is None
    assert "S-5" not in on_line.stops and on_line.flag == "KILL-LIKELY"
    assert "S-5" not in inside.stops and inside.flag == "KILL-LIKELY"
    assert "S-5" not in clear.stops and clear.flag is None


def test_zero_covered_days_is_underpowered_with_no_fillability_ratio() -> None:
    summary = summarise([])

    assert summary.n_cov == 0
    assert summary.c is None
    assert summary.stops == ("S-1",)
    assert summary.s5_unscreened


def test_censused_days_round_trip_refuses_extra_keys_and_duplicates(tmp_path: Path) -> None:
    row = _covered_row((_print("a", "0.25", "BUYER"),))
    path = tmp_path / "days.jsonl"

    write_censused_days(path, [row])

    assert read_censused_days(path) == [row]
    record = json.loads(path.read_text())
    record["surprise"] = 1
    extra = tmp_path / "extra.jsonl"
    extra.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="keys"):
        read_censused_days(extra)
    dup = tmp_path / "dup.jsonl"
    dup.write_text(path.read_text() * 2)
    with pytest.raises(ValueError, match="duplicate"):
        read_censused_days(dup)
    with pytest.raises(ValueError, match="duplicate"):
        write_censused_days(tmp_path / "w.jsonl", [row, row])
    bad_reason = json.loads(path.read_text())
    bad_reason["reason"] = "VIBES"
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(bad_reason) + "\n")
    with pytest.raises(ValueError, match="reason"):
        read_censused_days(bad)


def test_write_is_byte_idempotent_regardless_of_input_order(tmp_path: Path) -> None:
    rows = [
        _covered_row((), station="MIA", day=_DAY),
        _covered_row((_print("a", "0.25", "BUYER"),), station="LAX", day=_DAY),
        _covered_row((), station="LAX", day=_DAY + dt.timedelta(days=1)),
    ]
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"

    write_censused_days(first, rows)
    write_censused_days(second, list(reversed(rows)))
    write_censused_days(first, read_censused_days(first))

    assert first.read_bytes() == second.read_bytes()
    assert [(r.station, r.climate_day) for r in read_censused_days(first)] == [
        ("LAX", _DAY),
        ("LAX", _DAY + dt.timedelta(days=1)),
        ("MIA", _DAY),
    ]


# --------------------------------------------------------------------------------------
# Script level: raw feather written through the production streaming writer
# --------------------------------------------------------------------------------------

_WRITE_TYPES = [BinaryOption, TradeTick, QuoteTapeGap, VenueClockOffset]


def _instrument(slug: str, ts_init: int) -> BinaryOption:
    base = make_instrument(slug)
    return BinaryOption.from_dict({**BinaryOption.to_dict(base), "ts_init": ts_init})


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


def _write_instance(
    capture: Path,
    instance_id: str,
    *,
    instruments: list[BinaryOption],
    trades: list[TradeTick],
    alive: tuple[int, int],
    gaps: tuple[QuoteTapeGap, ...] = (),
) -> Path:
    cache = Cache(database=None, config=CacheConfig())
    for instrument in instruments:
        cache.add_instrument(instrument)
    directory = capture / "live" / instance_id
    writer = StreamingFeatherWriter(
        path=str(directory), cache=cache, clock=TestClock(), include_types=_WRITE_TYPES
    )
    for instrument in instruments:
        writer.write(instrument)
    for ts in alive:
        writer.write(
            VenueClockOffset(
                source="ws-transact-time", offset_ns=0, samples=1, ts_event=ts, ts_init=ts
            )
        )
    for gap in gaps:
        writer.write(gap)
    for trade in sorted(trades, key=lambda t: t.ts_init):
        writer.write(trade)
    writer.close()
    return directory


def _file_tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file() or path.is_dir()
    }


def _two_instance_capture(capture: Path) -> None:
    """A: rotation-straddling pair of instances; one print seen by both; NYC + D+1 noise."""
    lax = _instrument(_slug("lax", "2026-09-22"), _ns("2026-09-21T12:30:00"))
    lax_next = _instrument(_slug("lax", "2026-09-23"), _ns("2026-09-22T05:00:00"))
    nyc = _instrument(_slug("nyc", "2026-09-22"), _ns("2026-09-21T12:00:00"))
    both = [lax, lax_next, nyc]
    shared = _trade(lax, "shared", "0.350", AggressorSide.BUYER, _ns("2026-09-22T09:00:00"))
    _write_instance(
        capture,
        "inst-a",
        instruments=both,
        trades=[
            _trade(lax, "early", "0.250", AggressorSide.BUYER, _ns("2026-09-22T05:00:00")),
            _trade(lax, "sell", "0.400", AggressorSide.SELLER, _ns("2026-09-22T05:01:00")),
            _trade(nyc, "nyc-buy", "0.500", AggressorSide.BUYER, _ns("2026-09-22T05:02:00")),
            _trade(lax_next, "next-day", "0.500", AggressorSide.BUYER, _ns("2026-09-22T05:03:00")),
            shared,
        ],
        alive=(_ns("2026-09-21T12:00:00"), _ns("2026-09-22T09:00:10")),
    )
    _write_instance(
        capture,
        "inst-b",
        instruments=[lax],
        trades=[shared],
        alive=(_ns("2026-09-22T08:59:50"), _ns("2026-09-22T11:30:00")),
    )


def _run(capture: Path, tmp_path: Path, **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "catalog_root": capture,
        "work_root": tmp_path / "work",
        "stations": ("LAX",),
        "day_from": _DAY,
        "day_to": _DAY,
        "declaration_sha256": None,
    }
    options.update(overrides)
    return census_script.run_census(**options)


def test_trade_tick_default_convert_round_trips_into_scratch_catalog(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    lax = _instrument(_slug("lax", "2026-09-22"), _ns("2026-09-21T12:30:00"))
    sent = _trade(lax, "abc123", "0.250", AggressorSide.BUYER, _ns("2026-09-22T05:00:00"))
    _write_instance(
        capture,
        "inst-a",
        instruments=[lax],
        trades=[sent],
        alive=(_ns("2026-09-21T12:00:00"), _ns("2026-09-22T09:00:00")),
    )
    work = ParquetDataCatalog(str(tmp_path / "work" / "inst-a"))

    census_script.convert_instance(ParquetDataCatalog(str(capture)), "inst-a", work)

    landed = work.query(data_cls=TradeTick)
    assert [(t.trade_id.value, t.aggressor_side, str(t.price)) for t in landed] == [
        ("abc123", AggressorSide.BUYER, "0.250")
    ]
    assert len(work.query(data_cls=BinaryOption)) >= 1
    assert len(work.query(data_cls=VenueClockOffset)) == 2


def test_end_to_end_row_for_a_covered_day_with_production_defaults(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    _two_instance_capture(capture)

    result = _run(capture, tmp_path)

    (row,) = result.rows
    assert (row.station, row.climate_day, row.reason) == ("LAX", _DAY, "COVERED")
    assert row.firewall_class == "PRE_FREEZE"
    assert row.instances_clean == 2
    assert row.buyer_by_bucket == (0, 0, 1, 1)  # 'shared' counted once across both instances
    assert row.prints_seller == 1
    assert row.rungs_with_qualifying_buyer == 1
    assert row.first_seen_ns == _ns("2026-09-21T12:30:00")
    assert row.coverage_fraction == pytest.approx(1.0)
    assert result.summary.n_cov == 1
    assert "S-1" in result.summary.stops  # one covered day is far below the floor


def test_main_writes_output_prints_provenance_and_the_stop_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = tmp_path / "capture"
    _two_instance_capture(capture)
    output = tmp_path / "out" / "censused_days.jsonl"

    code = census_script.main(
        [
            "--from", "2026-09-22",
            "--to", "2026-09-22",
            "--stations", "LAX",
            "--catalog-root", str(capture),
            "--work-root", str(tmp_path / "work"),
            "--output", str(output),
        ]
    )  # fmt: skip

    captured = capsys.readouterr()
    assert code == 4  # S-5 UNSCREENED: 1 covered station-day < 10
    assert [r.reason for r in read_censused_days(output)] == ["COVERED"]
    assert "STOP S-5 UNSCREENED (covered_days=1 < 10)" in captured.out
    assert "NO-GO" not in captured.out and "KILL-LIKELY" not in captured.out
    assert "INFO bidlive:" in captured.out
    assert "census_provenance:" in captured.out
    assert "STOP S-1 UNDERPOWERED" in captured.out
    assert "inst-a" in captured.err  # one progress line per instance (the stall watch keys on it)


def test_nyc_prints_never_reach_a_count_in_the_script(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    _two_instance_capture(capture)

    result = _run(capture, tmp_path, stations=("LAX", "MIA"))

    assert sorted(r.station for r in result.rows) == ["LAX", "MIA"]
    lax = next(r for r in result.rows if r.station == "LAX")
    assert sum(lax.buyer_by_bucket) == 2  # NYC 0.50 buyer and the D+1 0.50 buyer are absent
    assert next(r for r in result.rows if r.station == "MIA").reason == "NEVER_LISTED"
    with pytest.raises(FirewallRefused):
        _run(capture, tmp_path, stations=("NYC",))


def test_live_instance_is_counted_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    lax = _instrument(_slug("lax", "2026-09-22"), _ns("2026-09-21T12:30:00"))
    directory = _write_instance(
        capture,
        "inst-live",
        instruments=[lax],
        trades=[_trade(lax, "t", "0.250", AggressorSide.BUYER, _ns("2026-09-22T05:00:00"))],
        alive=(_ns("2026-09-21T12:00:00"), _ns("2026-09-22T09:00:00")),
    )
    victim = next(directory.rglob("trade_tick/**/*.feather"))
    with victim.open("r+b") as handle:  # cut mid-message: a writer still open
        handle.truncate(victim.stat().st_size - 16)
    converted: list[str] = []
    real = census_script.default_convert

    def spy(catalog: Any, instance_id: str, *args: Any, **kwargs: Any) -> str:
        converted.append(instance_id)
        return real(catalog, instance_id, *args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(census_script, "default_convert", spy)

    result = _run(capture, tmp_path)

    assert converted == []
    assert result.instance_counts["LIVE"] == 1
    assert [r.reason for r in result.rows] == ["AMBIGUOUS_NO_CLEAN_INSTANCE"]
    assert result.rows[0].instances_live_unread == 1
    assert result.rows[0].buyer_by_bucket == (0, 0, 0, 0)


def test_trade_tick_parse_failure_refuses_the_station_day(tmp_path: Path) -> None:
    import pyarrow as pa

    capture = tmp_path / "capture"
    _two_instance_capture(capture)
    victim = next((capture / "live" / "inst-a").rglob("trade_tick/**/*.feather"))
    table = pa.table({"not_a_trade_column": [1]}).replace_schema_metadata({"class": "TradeTick"})
    with victim.open("wb") as handle:
        stream = pa.ipc.new_stream(handle, table.schema)
        stream.write_table(table)
        stream.close()

    result = _run(capture, tmp_path)

    (row,) = result.rows
    assert row.reason == "TRADE_PARSE_FAILURE"
    assert row.buyer_by_bucket == (0, 0, 0, 0)  # never a silent lower count
    assert summarise(result.rows).n_cov == 0


def test_work_catalog_is_removed_and_capture_root_untouched(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    _two_instance_capture(capture)
    before = _file_tree(capture)
    work_root = tmp_path / "work"

    _run(capture, tmp_path, work_root=work_root)

    assert _file_tree(capture) == before  # no marker, no catalog, no mtime moved
    assert not work_root.exists() or list(work_root.iterdir()) == []
    with pytest.raises(ValueError, match="capture root"):
        _run(capture, tmp_path, work_root=capture / "scratch")


def test_script_refuses_post_freeze_days_with_a_mismatched_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = tmp_path / "capture"
    _two_instance_capture(capture)
    forged = tmp_path / "declaration.md"
    forged.write_text("not the declaration\n")
    argv = [
        "--from", "2026-10-02",
        "--to", "2026-10-02",
        "--stations", "LAX",
        "--catalog-root", str(capture),
        "--work-root", str(tmp_path / "work"),
        "--output", str(tmp_path / "out.jsonl"),
    ]  # fmt: skip

    refused = census_script.main([*argv, "--search-declaration", str(forged)])
    missing = census_script.main(argv)
    cleared = census_script.main([*argv, "--search-declaration", str(_DECLARATION)])

    assert (refused, missing) == (2, 2)
    assert "FirewallRefused" in capsys.readouterr().err
    assert cleared == 4  # cleared and read; nothing covered, so S-5 is UNSCREENED
    assert [r.reason for r in read_censused_days(tmp_path / "out.jsonl")] == ["NEVER_LISTED"]


# --------------------------------------------------------------------------------------
# Review round: bid-live columns, scope filtering, reasons, S-5 guard, exit codes
# --------------------------------------------------------------------------------------


def test_bidlive_window_constants_are_the_spec_permit_window() -> None:
    assert mtc.BIDLIVE_START_HHMM_UTC == (16, 50)
    assert mtc.BIDLIVE_END_HHMM_UTC == (2, 50)

    start, end = mtc.bidlive_window_ns(climate_day=_DAY, window=_LAX_WINDOW)

    assert start == _ns("2026-09-21T16:50:00")
    assert end == _ns("2026-09-22T02:50:00")
    assert _LAX_WINDOW.start_ns < start and end < _LAX_WINDOW.end_ns  # a strict sub-window


def test_print_in_plan_window_outside_bidlive_counts_in_n_but_not_n_bidlive() -> None:
    inside = PrintRecord("in", _ns("2026-09-21T20:00:00"), Decimal("0.25"), "BUYER", "r1")
    plan_only = PrintRecord("out", _ns("2026-09-22T06:00:00"), Decimal("0.35"), "BUYER", "r1")

    row = _covered_row((inside, plan_only))

    assert (row.n_prints, row.n_prints_bidlive) == (2, 1)
    assert row.buyer_by_bucket == (0, 0, 1, 1)
    assert row.buyer_by_bucket_bidlive == (0, 0, 1, 0)
    assert row.covered_bidlive is True


def test_bidlive_covered_flag_survives_a_plan_window_failure() -> None:
    start = _ns("2026-09-21T16:00:00")
    spans = (AliveSpan(start, _ns("2026-09-22T03:00:00"), ()),)  # bid-live fully alive, plan 43%

    row = classify(
        station="LAX",
        climate_day=_DAY,
        firewall_class="PRE_FREEZE",
        window=_LAX_WINDOW,
        clean_instances=1,
        trade_parse_failed=False,
        spans=spans,
        prints=(PrintRecord("a", _ns("2026-09-21T20:00:00"), Decimal("0.25"), "BUYER", "r"),),
        first_seen_ns=None,
    )

    assert row.reason == "LOW_COVERAGE"
    assert row.n_prints == 0  # the plan-window basis is unchanged
    assert row.covered_bidlive is True and row.n_prints_bidlive == 1
    summary = summarise([row])
    assert (summary.n_cov, summary.n_cov_bidlive, summary.c_bidlive) == (0, 1, 1.0)


def test_summary_carries_bidlive_fields_alongside_the_plan_figures() -> None:
    def day_row(station: str, day: dt.date, ts: str) -> CensusedDay:
        prints = (PrintRecord(f"{station}{day}", _ns(ts), Decimal("0.25"), "BUYER", "r"),)
        return _covered_row(prints, station=station, day=day)

    # Same window anchor for both days is not needed: only the print's own clock matters.
    rows = [
        day_row("LAX", _DAY, "2026-09-21T20:00:00"),  # inside bid-live
        day_row("MIA", _DAY, "2026-09-22T06:00:00"),  # plan window only
    ]

    summary = summarise(rows)

    assert (summary.n_cov, summary.d_cov, summary.c) == (2, 1, 1.0)
    assert (summary.n_cov_bidlive, summary.d_cov_bidlive) == (2, 1)
    assert summary.c_bidlive == pytest.approx(0.5)
    assert summary.n_eff_ub_bidlive == pytest.approx(2 / 1.5)
    assert summary.stops == ("S-1",)  # bid-live figures never add or remove a STOP


def test_s5_is_unscreened_below_ten_covered_station_days_and_evaluated_at_ten() -> None:
    def quiet(count: int) -> Any:
        stations = ("LAX", "MDW", "MIA", "SFO")
        rows = [
            _covered_row((), station=stations[i % 4], day=_DAY + dt.timedelta(days=i // 4))
            for i in range(count)
        ]
        return summarise(rows)

    nine = quiet(9)
    ten = quiet(10)

    assert nine.c == 0.0 and nine.s5_unscreened is True
    assert "S-5" not in nine.stops and nine.flag is None
    assert ten.s5_unscreened is False and "S-5" in ten.stops


def test_nyc_only_capture_contributes_nothing_and_is_only_counted(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    nyc = _instrument(_slug("nyc", "2026-09-22"), _ns("2026-09-21T12:00:00"))
    gap = QuoteTapeGap(
        instrument_id=nyc.id,
        gap_seq=1,
        started_ns=_ns("2026-09-22T01:00:00"),
        ended_ns=_ns("2026-09-22T02:00:00"),
        resolved=True,
        recorder_instance_id="11111111-1111-1111-1111-111111111111",
        ts_event=_ns("2026-09-22T01:00:00"),
        ts_init=_ns("2026-09-22T02:00:00"),
    )
    _write_instance(
        capture,
        "inst-nyc",
        instruments=[nyc],
        trades=[_trade(nyc, "n", "0.500", AggressorSide.BUYER, _ns("2026-09-22T05:00:00"))],
        alive=(_ns("2026-09-21T12:00:00"), _ns("2026-09-22T09:00:00")),
        gaps=(gap,),
    )

    result = _run(capture, tmp_path)

    (row,) = result.rows
    assert (row.reason, row.first_seen_ns, row.instances_clean) == ("NEVER_LISTED", None, 0)
    assert result.rows_discarded_out_of_scope >= 3  # instrument + gap + print, values dropped

    work = ParquetDataCatalog(str(tmp_path / "direct"))
    census_script.convert_instance(ParquetDataCatalog(str(capture)), "inst-nyc", work)
    scope = census_script._Scope(frozenset({_DAY}), frozenset({"LAX"}))
    assert census_script._gaps_by_station_day(work, scope) == {}
    assert census_script._first_seen_by_station_day(work, scope) == {}
    assert scope.discarded >= 2


def test_corrupt_instance_is_ambiguous_not_never_listed_and_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    lax = _instrument(_slug("lax", "2026-09-22"), _ns("2026-09-21T12:30:00"))
    directory = _write_instance(
        capture,
        "inst-corrupt",
        instruments=[lax],
        trades=[_trade(lax, "t", "0.250", AggressorSide.BUYER, _ns("2026-09-22T05:00:00"))],
        alive=(_ns("2026-09-21T12:00:00"), _ns("2026-09-22T09:00:00")),
    )
    victim = next(directory.rglob("trade_tick/**/*.feather"))
    with victim.open("r+b") as handle:
        handle.truncate(victim.stat().st_size - 16)
    stale = time.time() - 30 * 86400
    os.utime(victim, (stale, stale))
    converted: list[str] = []

    def refuse_to_convert(catalog: Any, instance_id: str, *args: Any, **kwargs: Any) -> str:
        converted.append(instance_id)
        return "converted"

    monkeypatch.setattr(census_script, "default_convert", refuse_to_convert)

    result = _run(capture, tmp_path, stations=("LAX", "MIA"))

    assert converted == []
    assert result.instance_counts["CORRUPT"] == 1
    by_station = {r.station: r for r in result.rows}
    assert by_station["LAX"].reason == "AMBIGUOUS_NO_CLEAN_INSTANCE"
    assert by_station["LAX"].instances_corrupt_unread == 1
    assert by_station["MIA"].reason == "NEVER_LISTED"
    assert summarise(result.rows).n_cov == 0  # neither reason is in any denominator


def test_io_failure_exits_3_with_its_own_prefix_not_the_refusal_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = census_script.main(
        [
            "--from", "2026-09-22",
            "--to", "2026-09-22",
            "--stations", "LAX",
            "--catalog-root", str(tmp_path / "capture"),
            "--work-root", str(tmp_path / "work"),
            "--output", str(tmp_path / "out.jsonl"),
            "--search-declaration", str(tmp_path / "missing.md"),
        ]
    )  # fmt: skip

    err = capsys.readouterr().err
    assert code == 3
    assert "IO_FAILED" in err and "REFUSED" not in err
