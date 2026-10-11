"""EXEC-PAR BG-5c WP-D: settlement truth for the settled-P&L driver (R8.1, A6).

**Truth source.** The F2 truth dataset the live truth timers write,
``derived/fq-truth/truth_cli_finals.csv`` (schema ``fq_truth_cli/v1``, one row per station and
climate day, built from the latest PROMOTED NWS CLI revision and replaced atomically). It is a CSV
file, not SQLite, so there is no ``mode=ro`` URI: the read-only mode is ``open(path, "r")``, one
fresh handle per read, nothing in this module can write. A row exists only for a parsed CLI final;
a sentinel reading (``tmax_flag`` set, no ``tmax_f``) is a row that is NOT final-grade. The durable
store is preferred to the Nautilus catalog, which holds preliminaries and corrections too.

**Finality.** A record is final-grade iff it has a real ``tmax_f`` and no sentinel flag. Anything
else (no row, a sentinel, a read fault) is NO outcome: the caller scores the entry pending, then
overdue, and never as a zero. A revised value changes :attr:`TruthRecord.token`, which replaces or
invalidates the cached outcome (:class:`FinalTruthCache`).

**Held side (A6).** The held side comes from the instrument id's own leg suffix (``^no``), never
from an order side or a stored leg sign. ``held = contains`` for the YES leg and ``not contains``
for the NO leg: the one and only flip. The durable fill record already carries the HELD leg's cost
(a BUY of the ``^no`` instrument at the NO price), so no cost flip belongs here.

Pure apart from the reader's file read; imports no network code and never touches ``docs/``.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Hashable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Protocol

from breezy.domain.instrument_leg import leg_of_symbol, symbol_of_instrument_id
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts

__all__ = [
    "CacheEvent",
    "F2CsvTruthReader",
    "FinalTruthCache",
    "TruthReadError",
    "TruthReader",
    "TruthRecord",
    "held_outcome",
]

#: The columns this reader needs from ``fq_truth_cli/v1``; any other column is ignored.
REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"station", "climate_day", "tmax_f", "tmax_flag", "correction_flag", "product_sha256"}
)


class TruthReadError(RuntimeError):
    """The truth store could not be read or is malformed (the day stays pending, never zero)."""


@dataclass(frozen=True, slots=True)
class TruthRecord:
    """One station-day's CLI answer. ``token`` changes whenever the published value is revised."""

    station: str
    climate_day: dt.date
    tmax_f: int | None
    tmax_flag: str
    correction: bool
    token: str
    #: The CLI product's own digest: names WHICH revision a record came from (audit rows).
    product_sha256: str = ""

    @property
    def is_final_grade(self) -> bool:
        return self.tmax_f is not None and self.tmax_flag == ""


class TruthReader(Protocol):
    """A BLOCKING read of one station-day: runs on an executor thread, opens its own handle."""

    def read(self, station: str, climate_day: dt.date) -> TruthRecord | None: ...


def _parse_flag(raw: str) -> bool:
    if raw not in ("True", "False"):
        raise TruthReadError("correction_flag is not True/False")
    return raw == "True"


def _parse_row(row: dict[str, str]) -> TruthRecord:
    try:
        station = row["station"]
        day = dt.date.fromisoformat(row["climate_day"])
        raw_tmax = row["tmax_f"]
        tmax = int(raw_tmax) if raw_tmax != "" else None
        flag = row["tmax_flag"] or ""
        correction = _parse_flag(row["correction_flag"])
        sha = row["product_sha256"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TruthReadError("truth row is malformed") from exc
    return TruthRecord(
        station=station,
        climate_day=day,
        tmax_f=tmax,
        tmax_flag=flag,
        correction=correction,
        token=f"{sha}:{tmax}:{flag}:{int(correction)}",
        product_sha256=sha,
    )


class F2CsvTruthReader:
    """Reads the F2 finals CSV read-only; every ``read`` opens (and closes) its own handle."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self, station: str, climate_day: dt.date) -> TruthRecord | None:
        found: TruthRecord | None = None
        try:
            with self._path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if not REQUIRED_COLUMNS <= set(reader.fieldnames or ()):
                    raise TruthReadError("truth header lacks a required column")
                for raw in reader:
                    if raw.get("station") != station or raw.get("climate_day") != (
                        climate_day.isoformat()
                    ):
                        continue
                    record = _parse_row(raw)
                    if found is not None and found != record:
                        raise TruthReadError("conflicting truth rows for the station-day")
                    found = record
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise TruthReadError("truth store is unreadable") from exc
        return found


def held_outcome(
    instrument_id: str, facts: WeatherBucketFacts, record: TruthRecord | None
) -> bool | None:
    """Did the HELD side of ``instrument_id`` win? ``None`` when the answer is not yet knowable.

    ``None`` covers no record, a non-final record, a record for another station-day and a measure
    this tmax-only store cannot grade (LOW). It is never False.
    """
    if record is None or not record.is_final_grade or record.tmax_f is None:
        return None
    if facts.measure is not Measure.HIGH:
        return None
    if record.station != facts.settlement_station or record.climate_day != facts.climate_day:
        return None
    contains = facts.contains(record.tmax_f)
    return (
        contains if leg_of_symbol(symbol_of_instrument_id(instrument_id)) == "yes" else not contains
    )


class CacheEvent(Enum):
    STORED = "stored"
    UNCHANGED = "unchanged"
    REVISED = "revised"
    INVALIDATED = "invalidated"
    IGNORED = "ignored"


class FinalTruthCache:
    """Final-grade records only, keyed by station-day. Loop-thread use only (no locking)."""

    def __init__(self) -> None:
        self._finals: dict[Hashable, TruthRecord] = {}

    def get(self, key: Hashable) -> TruthRecord | None:
        return self._finals.get(key)

    def drop(self, key: Hashable) -> bool:
        """Forget a cached final (staleness); ``True`` when there was one."""
        return self._finals.pop(key, None) is not None

    def land(self, key: Hashable, record: TruthRecord | None) -> CacheEvent:
        """Fold one SUCCESSFUL read in. A non-final answer invalidates a cached final."""
        cached = self._finals.get(key)
        if record is None or not record.is_final_grade:
            if cached is None:
                return CacheEvent.IGNORED
            del self._finals[key]
            return CacheEvent.INVALIDATED
        self._finals[key] = record
        if cached is None:
            return CacheEvent.STORED
        return CacheEvent.UNCHANGED if cached == record else CacheEvent.REVISED
