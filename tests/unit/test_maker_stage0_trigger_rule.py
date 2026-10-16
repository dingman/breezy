"""MAKER-S2 second look (C2, delta 2.6): the pure trigger rule."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_trigger_rule import (
    TRIGGER_THRESHOLD,
    TriggerRow,
    counted,
    first_crossing,
    n_eff_proxy,
    read_trigger_rows,
)

DAY = dt.date(2026, 10, 14)
_NS = 1_000_000_000


def _ns(day: dt.date, hour: int) -> int:
    moment = dt.datetime.combine(day, dt.time(hour), tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


def _row(station: str, day: dt.date, reason: str = "COVERED", ns: int | None = None) -> TriggerRow:
    early = _ns(day - dt.timedelta(days=1), 6) if ns is None else ns
    return TriggerRow(station, day, reason, early)


def test_trigger_threshold_is_pinned() -> None:
    assert TRIGGER_THRESHOLD == 34.0


def test_counted_requires_covered_and_listed_in_time() -> None:
    assert counted(_row("SFO", DAY))
    assert not counted(_row("SFO", DAY, reason="NO_TAPE"))
    late = _ns(DAY - dt.timedelta(days=1), 13)
    assert not counted(_row("SFO", DAY, ns=late))


def test_listed_in_time_boundary_exactly_d_minus_1_1200z_counts() -> None:
    edge = _ns(DAY - dt.timedelta(days=1), 12)
    assert counted(_row("SFO", DAY, ns=edge))
    assert not counted(_row("SFO", DAY, ns=edge + 1))


def test_first_crossing_is_first_day_not_check_day() -> None:
    days = [DAY + dt.timedelta(days=i) for i in range(5)]
    rows = [_row("SFO", days[0]), _row("SFO", days[1]), _row("MIA", days[1])]
    rows += [_row("SFO", days[2]), _row("SFO", days[3]), _row("SFO", days[4])]
    assert n_eff_proxy(rows) == pytest.approx(1 + 2 / 1.5 + 3)
    assert first_crossing(list(reversed(rows)), threshold=3.0) == days[2]
    assert first_crossing(rows, threshold=1000.0) is None
    assert first_crossing([], threshold=1.0) is None


def test_uncounted_rows_never_advance_the_crossing() -> None:
    rows = [_row("SFO", DAY, reason="NO_TAPE")]
    assert first_crossing(rows, threshold=0.5) is None


def test_read_trigger_rows_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    record = {
        "station": "SFO",
        "climate_day": "2026-10-14",
        "reason": "COVERED",
        "first_seen_ns": 5,
    }
    path.write_text(json.dumps(record) + "\n")
    assert read_trigger_rows(path) == [TriggerRow("SFO", DAY, "COVERED", 5)]


def test_read_trigger_rows_refuses_extra_fields(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    record = {"station": "SFO", "climate_day": "2026-10-14", "reason": "COVERED"}
    path.write_text(json.dumps({**record, "first_seen_ns": 5, "tmax_f": 70}) + "\n")
    with pytest.raises(InputRefused, match="keys"):
        read_trigger_rows(path)
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(InputRefused, match="keys"):
        read_trigger_rows(path)
