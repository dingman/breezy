"""F13-C1 S4: normalised-row builders and the normalised-CSV writer.

A normalised CSV is stored through ``ArchiveCache`` under ``<base>-norm-r<N>`` (one per raw
revision, so revisions never collide and the revision digest set never sees it). Every row
carries the observed-availability columns of its revision, so a downstream reader needs no
second source for ``available_at`` (A0 table, lag freeze).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.ingest.lamp_parse import LampBlock
from breezy.ingest.pfm_parse import PfmPoint
from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest
from breezy.persistence.us_source_request import normalised_request

__all__ = ["NormWriter", "lamp_csv", "pfm_csv", "write_normalised"]

_AVAILABILITY_COLUMNS: Final[tuple[str, ...]] = (
    "available_ts_ns",
    "basis",
    "miss_ts_ns",
    "clamped_to_miss",
    "first_seen_ns",
    "fetched_at_ns",
    "ntp_offset_ns",
    "late",
)
LAMP_COLUMNS: Final[tuple[str, ...]] = (
    "station",
    "issued_at_utc",
    "valid_time_utc",
    "tmp_f",
    *_AVAILABILITY_COLUMNS,
)
PFM_COLUMNS: Final[tuple[str, ...]] = (
    "station",
    "wfo",
    "issued_at_utc",
    "forecast_date",
    "max_f",
    *_AVAILABILITY_COLUMNS,
)
_STAMP: Final[str] = "%Y-%m-%dT%H:%MZ"


class _NanosecondClock(Protocol):
    def timestamp_ns(self) -> int: ...


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _availability(seen: Mapping[str, Any]) -> list[str]:
    return [_cell(seen.get(name)) for name in _AVAILABILITY_COLUMNS]


def _csv(header: Iterable[str], rows: Iterable[Iterable[str]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(list(header))
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def lamp_csv(blocks: Iterable[LampBlock], seen: Mapping[str, Any]) -> bytes:
    """One row per (station, valid time); a missing marker is an empty ``tmp_f``."""
    tail = _availability(seen)
    rows = (
        [
            block.station,
            block.issued_at.strftime(_STAMP),
            valid.strftime(_STAMP),
            _cell(value),
            *tail,
        ]
        for block in blocks
        for valid, value in zip(block.valid_times, block.tmp_f, strict=True)
    )
    return _csv(LAMP_COLUMNS, rows)


def pfm_csv(point: PfmPoint, seen: Mapping[str, Any]) -> bytes:
    """One row per forecast local date of the station's point."""
    tail = _availability(seen)
    rows = (
        [
            point.station,
            point.wfo,
            point.issued_at.strftime(_STAMP),
            day.isoformat(),
            str(maximum),
            *tail,
        ]
        for day, maximum in point.max_by_day
    )
    return _csv(PFM_COLUMNS, rows)


class NormWriter:
    """``ArchiveCache`` as a write API for normalised CSVs (and a reader for repairs)."""

    def __init__(self, root: Path, clock: _NanosecondClock) -> None:
        self._payload = b""
        self._cache = ArchiveCache(Path(root), fetch=self._closure, clock=clock)

    def _closure(self, _request: ArchiveRequest) -> bytes:
        return self._payload

    def missing(self, raw: ArchiveRequest) -> bool:
        return self._cache.missing(normalised_request(raw))

    def read_raw(self, raw: ArchiveRequest) -> bytes:
        return self._cache.read(raw)

    def write(self, raw: ArchiveRequest, data: bytes) -> None:
        self._payload = data
        try:
            self._cache.get_or_fetch(normalised_request(raw))
        finally:
            self._payload = b""


def write_normalised(writer: NormWriter, raw: ArchiveRequest, data: bytes) -> bool:
    """Write ``data`` as the normalised CSV of ``raw`` unless it already exists."""
    if not writer.missing(raw):
        return False
    writer.write(raw, data)
    return True
