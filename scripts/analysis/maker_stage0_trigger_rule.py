"""MAKER-S2 second look (C2): the pure trigger rule (counts-only rows; no census/driver import).

E = first climate day whose cumulative ``n_eff_gov`` over COUNTED rows reaches the threshold; a row
counts when COVERED and listed by D-1 12:00Z.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.analysis.maker_stage0_inputs import InputRefused, n_eff_gov
from scripts.analysis.maker_stage0_rule import listed_in_time

TRIGGER_THRESHOLD: Final[float] = 34.0
_KEYS: Final[frozenset[str]] = frozenset({"station", "climate_day", "reason", "first_seen_ns"})


@dataclass(frozen=True, slots=True)
class TriggerRow:
    station: str
    climate_day: dt.date
    reason: str
    first_seen_ns: int | None


def counted(row: TriggerRow) -> bool:
    return row.reason == "COVERED" and listed_in_time(row.first_seen_ns, row.climate_day)


def _per_day(rows: Iterable[TriggerRow]) -> dict[dt.date, int]:
    per_day: dict[dt.date, int] = defaultdict(int)
    for row in filter(counted, rows):
        per_day[row.climate_day] += 1
    return dict(per_day)


def n_eff_proxy(rows: Iterable[TriggerRow]) -> float:
    return n_eff_gov(_per_day(rows))


def first_crossing(
    rows: Sequence[TriggerRow], threshold: float = TRIGGER_THRESHOLD
) -> dt.date | None:
    per_day = _per_day(rows)
    total = 0.0
    for day in sorted(per_day):
        total += n_eff_gov({day: per_day[day]})
        if total >= threshold:
            return day
    return None


def _row_of(record: object, number: int) -> TriggerRow:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise InputRefused(f"trigger row {number}: keys must be exactly {sorted(_KEYS)}")
    for key in ("station", "climate_day", "reason"):
        if not isinstance(record[key], str):  # NB3: rows are hash-pinned, so no coercion
            raise InputRefused(f"trigger row {number}: {key} must be a string")
    seen = record["first_seen_ns"]
    if seen is not None and type(seen) is not int:
        raise InputRefused(f"trigger row {number}: first_seen_ns must be an int or null")
    try:
        return TriggerRow(
            record["station"], dt.date.fromisoformat(record["climate_day"]), record["reason"], seen
        )
    except (ValueError, TypeError) as exc:
        raise InputRefused(f"trigger row {number}: malformed value ({type(exc).__name__})") from exc


def trigger_rows_from_records(records: Iterable[object]) -> list[TriggerRow]:
    """Strictly validate parsed records (the same checks ``read_trigger_rows`` applies)."""
    return [_row_of(record, number) for number, record in enumerate(records, start=1)]


def read_trigger_rows(path: Path) -> list[TriggerRow]:
    """A JSONL of exactly the four counts-only keys; any other key is refused."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError) as exc:
        raise InputRefused(f"trigger rows {path.name} unreadable ({type(exc).__name__})") from exc
    return trigger_rows_from_records(records)
