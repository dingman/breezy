"""MAKER-S2 shared fixture generator: S1 ``censused_days.jsonl`` rows + unit-verdict JSON.

Every row is built FROM :class:`CensusedDay` (never hand-typed JSON): the default for each field
is looked up by the dataclass's own field set, so an S1 schema change (a field added, removed or
renamed) raises ``AssertionError`` here and fails every MAKER-S2 test that uses the fixture
(plan r4 delta (k), MLE E-4). Rows reach disk only through S1's ``write_censused_days``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from breezy.analysis.maker_tape_census import CensusedDay, write_censused_days
from breezy.analysis.trade_quantity_unit import UNIT_HYPOTHESES, USD_BRACKET

#: The unit-verdict set MAKER-S2 must handle (plan r4 (k)).
UNIT_VERDICT_SET: Final[tuple[str, ...]] = ("CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER")
BRACKETED: Final[str] = "BRACKETED_USD"
UNRESOLVED: Final[str] = "UNRESOLVED"
FIXTURE_STATIONS: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")
FIXTURE_FIRST_DAY: Final[dt.date] = dt.date(2026, 9, 18)

_DEFAULTS: Final[Mapping[str, object]] = {
    "station": "SFO",
    "climate_day": FIXTURE_FIRST_DAY,
    "firewall_class": "PRE_FREEZE",
    "reason": "COVERED",
    "coverage_fraction": 1.0,
    "longest_hole_min": 0,
    "tail_span_only": False,
    "buyer_by_bucket": (0, 0, 2, 3),
    "prints_seller": 4,
    "prints_no_aggressor": 0,
    "rungs_with_qualifying_buyer": 2,
    "first_seen_ns": 1_789_000_000_000_000_000,
    "instances_clean": 1,
    "instances_corrupt_unread": 0,
    "instances_live_unread": 0,
    "n_prints": 9,
    "covered_bidlive": True,
    "buyer_by_bucket_bidlive": (0, 0, 1, 2),
    "n_prints_bidlive": 7,
}


def _assert_schema_in_step() -> None:
    names = {field.name for field in dataclasses.fields(CensusedDay)}
    if names != set(_DEFAULTS):
        raise AssertionError(
            "CensusedDay schema drifted from the MAKER-S2 fixture: "
            f"{sorted(names ^ set(_DEFAULTS))}"
        )


def census_row(
    station: str = "SFO", climate_day: dt.date = FIXTURE_FIRST_DAY, **overrides: Any
) -> CensusedDay:
    """One ``CensusedDay`` (COVERED and bid-live by default); ``overrides`` replace any field."""
    _assert_schema_in_step()
    values = {**_DEFAULTS, "station": station, "climate_day": climate_day, **overrides}
    row = CensusedDay(**values)
    if set(row.to_dict()) != set(_DEFAULTS):
        raise AssertionError("CensusedDay.to_dict keys differ from its fields")
    return row


def census_grid(
    stations: Sequence[str] = FIXTURE_STATIONS,
    first_day: dt.date = FIXTURE_FIRST_DAY,
    n_days: int = 8,
    *,
    overrides: Mapping[tuple[str, dt.date], Mapping[str, Any]] | None = None,
) -> list[CensusedDay]:
    """``stations x n_days`` consecutive COVERED rows; ``overrides`` keyed by (station, day)."""
    changes = overrides or {}
    return [
        census_row(
            station, first_day + dt.timedelta(days=offset), **changes.get((station, day), {})
        )
        for offset in range(n_days)
        for station in stations
        for day in [first_day + dt.timedelta(days=offset)]
    ]


def write_census_fixture(path: Path, rows: Iterable[CensusedDay]) -> Path:
    """Write through S1's production writer (sorted, byte-idempotent JSONL)."""
    write_censused_days(path, rows)
    return path


def unit_verdict_json(verdict: str) -> dict[str, object]:
    """A crosscheck-shaped result (``trade_quantity_unit_crosscheck.main``) for ``verdict``."""
    if UNIT_VERDICT_SET != UNIT_HYPOTHESES:
        raise AssertionError("S1 unit hypotheses drifted from the MAKER-S2 fixture")
    if verdict in UNIT_HYPOTHESES:
        surviving = [verdict]
    elif verdict == BRACKETED:
        surviving = sorted(USD_BRACKET)
    elif verdict == UNRESOLVED:
        surviving = []
    else:
        raise ValueError(f"unknown unit verdict {verdict!r}")
    return {
        "verdict": verdict,
        "surviving": surviving,
        "reason": f"fixture {verdict}",
        "n_counted": 0 if verdict == UNRESOLVED else 3,
        "s2_stop": verdict == UNRESOLVED,
        "s3_stop": False,
        "pinned_set_equal": True,
        "duplicate_prints": 0,
        "fills": [],
        "refused": [],
    }


def write_unit_fixture(path: Path, verdict: str) -> Path:
    path.write_text(json.dumps(unit_verdict_json(verdict), indent=2, sort_keys=True) + "\n")
    return path
