"""Pure MOS NBS CSV row parsing + TXN occupancy stats (FC-0a TXN occupancy measurement).

No I/O, no network, no clock. Given a MOS CSV body already fetched by a
sanctioned transport (``scripts/venue/iem_mos_txn_occupancy_probe.py`` ->
``iem_mos_probe_transport.IemMosProbeTransport``), extract the
``(station, runtime, ftime, txn, xnd)`` columns needed to measure how often
``txn`` -- the MOS max/min temperature element the whole forecast family
depends on -- is actually populated, broken down by ``ftime``/``runtime`` UTC
hour, and to characterise the ``xnd`` companion field that is documented (IEM
MOS CSV grammar) to disambiguate MAX from MIN.

This module never reads the live IEM host, never writes a catalog entry, and
never names the host itself -- it only transforms a CSV string a caller
already fetched.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections import Counter
from dataclasses import dataclass
from typing import Final

__all__ = [
    "MosTxnRow",
    "OccupancyBucket",
    "ftime_hour",
    "occupancy_by_ftime_hour",
    "occupancy_by_runtime_hour",
    "parse_mos_txn_rows",
    "runtime_hour",
    "xnd_value_counts_for_nonempty_txn",
]

#: Runtime/ftime timestamp shapes actually observed in IEM MOS CSV exports
#: (``iem_mos_reachability_probe.py``'s ``_RUNTIME_FORMATS`` superset, kept
#: independent so this module has no import-time coupling to that script).
_INSTANT_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%MZ",
    "%Y-%m-%d",
)

_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset({"station", "runtime", "ftime", "txn", "xnd"})


@dataclass(frozen=True, slots=True)
class MosTxnRow:
    """One MOS CSV data row, narrowed to the five columns this measurement needs."""

    station: str
    runtime: str
    ftime: str
    txn: str
    xnd: str

    @property
    def txn_present(self) -> bool:
        return self.txn != ""


def _parse_instant(value: str) -> dt.datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in _INSTANT_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    return None


def ftime_hour(row: MosTxnRow) -> int | None:
    """The UTC hour-of-day of ``row.ftime``, or ``None`` if unparseable."""
    instant = _parse_instant(row.ftime)
    return None if instant is None else instant.hour


def runtime_hour(row: MosTxnRow) -> int | None:
    """The UTC hour-of-day of ``row.runtime``, or ``None`` if unparseable."""
    instant = _parse_instant(row.runtime)
    return None if instant is None else instant.hour


def parse_mos_txn_rows(text: str) -> tuple[MosTxnRow, ...]:
    """Parse a MOS CSV body into rows carrying only station/runtime/ftime/txn/xnd.

    Returns an empty tuple for an empty, HTML-error, or headerless body -- the
    same defensive shape as
    ``iem_mos_reachability_probe.parse_mos_csv_census``. A row missing any of
    the five required columns is skipped, never guessed at.
    """
    stripped = text.lstrip()
    if not stripped or stripped.startswith("<") or stripped.upper().startswith("ERROR"):
        return ()
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not _REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        return ()
    rows: list[MosTxnRow] = []
    for raw in reader:
        if any(raw.get(column) is None for column in _REQUIRED_COLUMNS):
            continue
        rows.append(
            MosTxnRow(
                station=(raw["station"] or "").strip(),
                runtime=(raw["runtime"] or "").strip(),
                ftime=(raw["ftime"] or "").strip(),
                txn=(raw["txn"] or "").strip(),
                xnd=(raw["xnd"] or "").strip(),
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class OccupancyBucket:
    """How many of ``total`` rows in one hour bucket carried a non-empty ``txn``."""

    total: int
    non_empty: int

    @property
    def occupancy_rate(self) -> float:
        return 0.0 if self.total == 0 else self.non_empty / self.total


def _occupancy_by_hour(
    rows: tuple[MosTxnRow, ...], hour_of: object
) -> dict[int, OccupancyBucket]:
    totals: Counter[int] = Counter()
    non_empty: Counter[int] = Counter()
    for row in rows:
        hour = hour_of(row)  # type: ignore[operator]
        if hour is None:
            continue
        totals[hour] += 1
        if row.txn_present:
            non_empty[hour] += 1
    return {
        hour: OccupancyBucket(total=totals[hour], non_empty=non_empty.get(hour, 0))
        for hour in sorted(totals)
    }


def occupancy_by_ftime_hour(rows: tuple[MosTxnRow, ...]) -> dict[int, OccupancyBucket]:
    """``txn`` occupancy grouped by the UTC hour-of-day of ``ftime`` (the projection)."""
    return _occupancy_by_hour(rows, ftime_hour)


def occupancy_by_runtime_hour(rows: tuple[MosTxnRow, ...]) -> dict[int, OccupancyBucket]:
    """``txn`` occupancy grouped by the UTC hour-of-day of ``runtime`` (the cycle)."""
    return _occupancy_by_hour(rows, runtime_hour)


def xnd_value_counts_for_nonempty_txn(rows: tuple[MosTxnRow, ...]) -> Counter[str]:
    """Distribution of the ``xnd`` companion value, restricted to rows where ``txn`` is populated.

    ``xnd`` is the documented MAX/MIN disambiguator for the combined ``txn``
    element; this is the raw evidence a caller cross-tabulates against
    ``ftime_hour`` to determine what each value actually means -- never
    assumed from the column name alone.
    """
    counts: Counter[str] = Counter()
    for row in rows:
        if row.txn_present:
            counts[row.xnd] += 1
    return counts
