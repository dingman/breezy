"""EXEC-PAR BG-5c WP-C (R1): the governed-days module and the atomic day-attribution migration.

Every attribution path must agree with ``GovernedDays.entry_day`` (per-station STANDARD time,
never the DST wall clock). The property test pins ingest, reconcile, snapshot labels and the
settled-P&L accumulator to it over boundary instants.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.registry.sites import default_registry
from breezy.runtime.exec_par_counter_ingest import ExecParCounterIngest
from breezy.runtime.exec_par_governed_days import (
    GovernedDays,
    GovernedDaysError,
    UnknownStationError,
    governed_days_for,
)
from breezy.runtime.exec_par_reconcile import (
    FillRecord,
    GapKind,
    GapSpan,
    entry_fills_by_day,
    gappy_days,
)
from breezy.runtime.exec_par_records import EpochRow, OrderAnchor, StageReset
from breezy.runtime.exec_par_settled_pnl import EntryInput, settled_pnl_by_day
from breezy.runtime.exec_par_stage_snapshot import stage_day_labels
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

NS = 1_000_000_000
HOUR = 3_600 * NS
VENUE = "polymarket_us"


def ns_utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    stamp = dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * NS


def real_days() -> GovernedDays:
    registry = default_registry()
    return governed_days_for(
        SUPPORTED_STATIONS,
        lambda s: registry.climate_day_window(VENUE, s).std_utc_offset_hours,
    )


def two_station_days() -> GovernedDays:
    return governed_days_for(("EAST", "WEST"), {"EAST": -5.0, "WEST": -8.0}.__getitem__)


# -- the module ------------------------------------------------------------------------------


def test_entry_day_uses_standard_time_midnight_not_the_dst_wall_clock() -> None:
    days = two_station_days()
    # WEST is UTC-8 in standard time all year: midnight is 08:00Z, even in July (PDT = 07:00Z).
    assert days.entry_day("WEST", ns_utc(2026, 7, 1, 7, 59) + 59 * NS) == "2026-06-30"
    assert days.entry_day("WEST", ns_utc(2026, 7, 1, 8, 0)) == "2026-07-01"
    assert days.entry_day("WEST", ns_utc(2026, 7, 1, 8, 0) - 1) == "2026-06-30"
    # EAST is UTC-5: midnight is 05:00Z.
    assert days.entry_day("EAST", ns_utc(2026, 7, 1, 5, 0)) == "2026-07-01"
    assert days.entry_day("EAST", ns_utc(2026, 7, 1, 5, 0) - 1) == "2026-06-30"


@pytest.mark.parametrize("month_day", [(3, 8), (3, 9), (11, 1), (11, 2), (1, 15), (7, 15)])
def test_entry_day_is_stable_across_dst_transition_dates(month_day: tuple[int, int]) -> None:
    month, day = month_day
    days = two_station_days()
    midnight = ns_utc(2026, month, day, 8, 0)  # WEST standard-time midnight
    assert days.entry_day("WEST", midnight) == f"2026-{month:02d}-{day:02d}"
    assert days.entry_day("WEST", midnight - 1) != days.entry_day("WEST", midnight)


def test_open_days_cover_every_governed_station_and_today_is_the_earliest() -> None:
    days = two_station_days()
    instant = ns_utc(2026, 10, 11, 6, 0)  # EAST 01:00 on the 11th, WEST 22:00 on the 10th
    assert days.open_days_at(instant) == frozenset({"2026-10-10", "2026-10-11"})
    assert days.today(instant) == "2026-10-10"
    later = ns_utc(2026, 10, 11, 12, 0)
    assert days.open_days_at(later) == frozenset({"2026-10-11"})
    assert days.today(later) == "2026-10-11"


def test_open_days_follow_the_injected_station_set_never_a_hardcoded_one() -> None:
    only_east = governed_days_for(("EAST",), {"EAST": -5.0}.__getitem__)
    instant = ns_utc(2026, 10, 11, 6, 0)
    assert only_east.open_days_at(instant) == frozenset({"2026-10-11"})
    assert only_east.stations == ("EAST",)


def test_unknown_station_raises_a_typed_error() -> None:
    with pytest.raises(UnknownStationError):
        two_station_days().entry_day("NOWHERE", ns_utc(2026, 10, 11))


@pytest.mark.parametrize("arm", [0, -1, True, 1.5, None, "1"])
def test_arm_ns_must_be_a_positive_int(arm: Any) -> None:
    with pytest.raises(GovernedDaysError):
        two_station_days().entry_day("EAST", arm)
    with pytest.raises(GovernedDaysError):
        two_station_days().open_days_at(arm)


def test_construction_rejects_an_empty_station_set_and_a_bad_offset() -> None:
    with pytest.raises(GovernedDaysError):
        governed_days_for((), {"X": -5.0}.__getitem__)
    with pytest.raises(GovernedDaysError):
        governed_days_for(("X",), {"X": float("nan")}.__getitem__)
    with pytest.raises(GovernedDaysError):
        governed_days_for(("X",), {"X": 99.0}.__getitem__)
    with pytest.raises(GovernedDaysError):
        governed_days_for(("X", "X"), {"X": -5.0}.__getitem__)


# -- the property: every migrated site agrees with entry_day --------------------------------------


def boundary_instants(days: GovernedDays) -> list[tuple[str, int]]:
    """Per station: standard-time midnight (+-1 ns, +-1 h) on DST and non-DST dates."""
    registry = default_registry()
    points: list[tuple[str, int]] = []
    for station in days.stations:
        offset = registry.climate_day_window(VENUE, station).std_utc_offset_hours
        for month, day in ((3, 8), (3, 9), (7, 1), (11, 1), (11, 2), (12, 31)):
            midnight_utc = ns_utc(2026, month, day) - int(offset * HOUR)
            for delta in (-HOUR, -1, 0, 1, HOUR):
                points.append((station, midnight_utc + delta))
    return points


class _Writer:
    """Minimal ``CounterWriterPort`` that keeps the anchors."""

    boot_ns = 1

    def __init__(self) -> None:
        self.anchors: dict[str, OrderAnchor] = {}

    def write_order_anchor(self, record: OrderAnchor) -> bool:
        created = record.client_order_id not in self.anchors
        self.anchors[record.client_order_id] = record
        return created

    def add_window_order(self, day: str, window_start_ns: int, notional: Decimal, coid: str) -> Any:
        return None


class _Fill:
    instrument_id = "A"
    order_side = "BUY"
    cumulative_qty = Decimal(10)
    cumulative_cost = Decimal(4)
    cumulative_fee = Decimal("0.17")
    fee_reconciled = True
    fee_coefficient_at_fill = Decimal("0.0695")


def test_every_migrated_site_agrees_with_entry_day_on_boundary_instants() -> None:
    days = real_days()
    assert set(days.stations) == set(SUPPORTED_STATIONS)
    points = boundary_instants(days)
    assert len(points) >= 100
    for index, (station, ns) in enumerate(points):
        expected = days.entry_day(station, ns)

        # ingest: the stored anchor's day and station
        writer = _Writer()
        ingest = ExecParCounterIngest(store=writer, entry_day=days.entry_day)  # type: ignore[arg-type]
        ingest.record_posted(
            client_order_id=f"O-{index}",
            slug=station,
            decision_ask=Decimal("0.4"),
            qty=Decimal(10),
            arm_ns=ns,
        )
        anchor = writer.anchors[f"O-{index}"]
        assert (anchor.day, anchor.station) == (expected, station)

        # reconcile: entry fill attribution and the gap-span day set
        record = FillRecord(order_id="o", side="BUY", arm_ns=ns, station=station)
        assert entry_fills_by_day([record], entry_day=days.entry_day) == {expected: 1}
        span = GapSpan(GapKind.HEARTBEAT_LAPSE, ns, ns + 2 * HOUR)
        assert expected in gappy_days([span], open_days_at=days.open_days_at)

        # settled P&L: the arm-day key
        rows = settled_pnl_by_day(
            [EntryInput(arm_ns=ns, station=station, fill=_Fill())],
            {"A": True},
            days.entry_day,
            today=expected,
        )
        assert set(rows) == {expected}

        # snapshot labels: floor and first-K>1 boot are instant-only (open_days_at)
        floor = StageReset(ts=ns, cause="k_change", halt_ts=None)
        epochs = (EpochRow("sha", 2, None, ns),)
        through = max(days.open_days_at(ns))
        labels = stage_day_labels(floor, epochs, days, days.today(ns), through)
        assert labels[0] == min(days.entry_day(s, ns) for s in days.stations)
        assert labels[0] == days.today(ns)
        assert labels[-1] == through


def test_mixed_offset_night_gap_span_marks_every_open_day_it_overlaps() -> None:
    days = two_station_days()
    span = GapSpan(
        GapKind.UNCLEAN_SHUTDOWN, ns_utc(2026, 10, 11, 4, 30), ns_utc(2026, 10, 11, 9, 0)
    )
    # EAST rolls to the 11th at 05:00Z; WEST rolls at 08:00Z: three labels are open in the span.
    assert gappy_days([span], open_days_at=days.open_days_at) == frozenset(
        {"2026-10-10", "2026-10-11"}
    )


# -- the grep test --------------------------------------------------------------------------------


FORBIDDEN = (r"\bday_of_ns\b", r"\btoday_of\b", r"Callable\[\[int\], str\]")


def test_the_forbidden_station_less_day_patterns_actually_match_offenders() -> None:
    samples = ("day_of_ns: int", "ports.today_of(now)", "f: Callable[[int], str]")
    for pattern, sample in zip(FORBIDDEN, samples, strict=True):
        assert re.search(pattern, sample)


def test_no_station_less_day_function_remains_in_the_exec_par_runtime_modules() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "breezy" / "runtime"
    offenders = [
        (path.name, pattern)
        for path in sorted(root.glob("exec_par_*.py"))
        for pattern in FORBIDDEN
        if re.search(pattern, path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
