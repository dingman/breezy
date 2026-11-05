"""F13 Phase A feature build: the LAMP readers (MDL archive and IEM LAV gap-fill).

Read-only over ``us_source_archive`` (``us-lamp-mdl`` / ``us-lav-iem``): the first-seen ``-r0``
revision only (the timing anchor), through an ``ArchiveCache`` that can never fetch.

FB-R8 rules enforced here:

* a run's ``available_at`` is its NOMINAL run time plus the pinned lag of its source
  (``source_lags_ns``). The availability manifest is read only for its ``holdout_sealed`` tag; its
  ``available_at_ns`` is a download-basis figure and is never used;
* a run the manifest seals, or whose run date is on or after the holdout start, is never read;
* the MDL -> LAV basis break is observed per climate day (:func:`basis_breaks`) for the report;
* a station block that is absent, or a run that does not parse, is counted and excluded, never
  repaired or imputed.

Runs are indexed from the cache manifest (cheap) and parsed on demand with a small LRU, so the
whole archive is never resident.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.multisource_blend_features import LampHour, LampRun
from breezy.ingest.lamp_parse import LampParseError, iter_lamp_blocks
from breezy.persistence.archive_cache import ArchiveCache, ArchiveCacheError
from breezy.persistence.us_source_request import (
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    US_SOURCE_PRODUCTS,
    revision_product_pattern,
    revision_request,
)
from scripts.archive.lamp_archive_runs import MANIFEST_NAME, LavPayloadError

__all__ = [
    "LampArchive",
    "LampRunChoice",
    "LavPayloadError",
    "basis_breaks",
    "lav_csv_to_lamp_run",
    "mdl_payload_to_lamp_run",
]

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3_600 * _NS
#: An HH30 run forecasts 38 h ahead; an older run cannot reach the climate day's afternoon.
_RUN_WINDOW_NS: Final[int] = 48 * _HOUR_NS
_CANDIDATES: Final[int] = 8
_KEEP_PARSED: Final[int] = 6
_LRU_SIZE: Final[int] = 64
_LAV_MODEL: Final[str] = "LAV"
_BASIS_BY_SOURCE: Final[Mapping[str, str]] = {US_LAMP_MDL_SOURCE: "mdl", US_LAV_IEM_SOURCE: "lav"}


@dataclass(frozen=True, slots=True)
class LampRunChoice:
    """The latest eligible runs of ONE basis (``mdl`` preferred, else ``lav``), oldest first."""

    runs: tuple[LampRun, ...]
    basis: str | None


@dataclass(frozen=True, slots=True)
class _Entry:
    source: str
    station: str
    run_ns: int
    sha256: str
    revision: int
    model: str | None


def _hours(blocks_hours: Sequence[tuple[dt.datetime, int | None]]) -> tuple[LampHour, ...]:
    return tuple(
        LampHour(valid_ts_ns=int(when.timestamp()) * _NS, tmp_f=None if tmp is None else float(tmp))
        for when, tmp in blocks_hours
    )


def mdl_payload_to_lamp_run(
    payload: bytes, *, station: str, run_ns: int, available_at_ns: int
) -> LampRun | None:
    """The ``station`` block of one stored MDL run, or ``None`` when the run lacks it.

    Raises :class:`~breezy.ingest.lamp_parse.LampParseError` on a payload that does not parse.
    """
    for block in iter_lamp_blocks(payload.decode("utf-8").splitlines()):
        if block.station == station:
            return LampRun(
                issued_ns=run_ns,
                available_at_ns=available_at_ns,
                hours=_hours(list(zip(block.valid_times, block.tmp_f, strict=True))),
            )
    return None


def lav_csv_to_lamp_run(payload: bytes, *, station: str, available_at_ns: int) -> LampRun:
    """One IEM ``mos.py?model=LAV`` CSV payload (one run, one station) as a :class:`LampRun`.

    Columns are read by NAME (``runtime``, ``ftime``, ``model``, ``tmp``, ``station``), never by
    position. An empty ``tmp`` is a missing hour (``None``). A row of another model or station,
    several runtimes in one payload, or a repeated ``ftime`` refuses the payload.
    """
    reader = csv.DictReader(io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", newline=""))
    fields = reader.fieldnames or []
    missing = [c for c in ("runtime", "ftime", "model", "tmp", "station") if c not in fields]
    if missing:
        raise LavPayloadError(f"LAV payload has no column(s) {missing}")
    runtimes: set[str] = set()
    hours: dict[int, float | None] = {}
    for row in reader:
        if row["model"].strip() != _LAV_MODEL:
            raise LavPayloadError(f"LAV payload row has model {row['model']!r}, not LAV")
        if row["station"].strip() != station:
            raise LavPayloadError(f"LAV payload row is station {row['station']!r}, not {station!r}")
        runtimes.add(row["runtime"].strip())
        try:
            ftime = dt.datetime.strptime(row["ftime"].strip(), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=dt.UTC
            )
            tmp = row["tmp"].strip()
            value = float(tmp) if tmp else None
        except ValueError as exc:
            raise LavPayloadError(f"LAV payload row is unparseable: {exc}") from exc
        key = int(ftime.timestamp()) * _NS
        if key in hours:
            raise LavPayloadError(f"LAV payload repeats ftime {row['ftime']!r}")
        hours[key] = value
    if len(runtimes) != 1:
        raise LavPayloadError(f"LAV payload must hold exactly one run, found {sorted(runtimes)}")
    runtime = dt.datetime.strptime(runtimes.pop(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
    return LampRun(
        issued_ns=int(runtime.timestamp()) * _NS,
        available_at_ns=available_at_ns,
        hours=tuple(LampHour(ts, hours[ts]) for ts in sorted(hours)),
    )


def basis_breaks(bases: Mapping[dt.date, str | None]) -> list[dt.date]:
    """The first climate day on which the LAMP basis differs from the previous known basis."""
    breaks: list[dt.date] = []
    previous: str | None = None
    for day in sorted(bases):
        basis = bases[day]
        if basis is None:
            continue
        if previous is not None and basis != previous:
            breaks.append(day)
        previous = basis
    return breaks


def _read_manifest_tags(root: Path, source: str) -> dict[tuple[str, int, str], bool]:
    """``(station, run_ts_ns, sha256) -> holdout_sealed``; a torn trailing line is skipped."""
    path = root / source / MANIFEST_NAME
    if not path.exists():
        return {}
    tags: dict[tuple[str, int, str], bool] = {}
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
            tags[(row["station"], int(row["run_ts_ns"]), row["sha256"])] = bool(
                row["holdout_sealed"]
            )
        except (ValueError, KeyError, TypeError):
            if index != len(lines) - 1:
                raise
    return tags


class LampArchive:
    """Selects, for one station and anchor, the latest eligible LAMP runs of the preferred basis."""

    def __init__(
        self,
        cache: ArchiveCache,
        manifest_root: Path,
        *,
        lag_ns_by_source: Mapping[str, int],
        holdout_start: dt.date,
        counts: Counter[str],
    ) -> None:
        self._cache = cache
        self._manifest_root = manifest_root
        self._lags = {
            US_LAMP_MDL_SOURCE: int(lag_ns_by_source["lamp-mdl"]),
            US_LAV_IEM_SOURCE: int(lag_ns_by_source["lav-iem"]),
        }
        self._holdout_start = holdout_start
        self._counts = counts
        self._index: dict[str, dict[str, list[_Entry]]] = {}
        self._parsed: OrderedDict[tuple[str, str, int], LampRun | None] = OrderedDict()

    # -- index ----------------------------------------------------------------------

    def _entries(self, source: str, station: str) -> list[_Entry]:
        if source not in self._index:
            self._index[source] = self._build_index(source)
        key = "ALL" if source == US_LAMP_MDL_SOURCE else station
        return self._index[source].get(key, [])

    def _build_index(self, source: str) -> dict[str, list[_Entry]]:
        pattern = revision_product_pattern(US_SOURCE_PRODUCTS[source])
        first: dict[tuple[str, int], _Entry] = {}
        for entry in self._cache.entries(source):
            matched = pattern.fullmatch(entry.product)
            if matched is None:
                continue
            revision = int(matched.group(1))
            key = (entry.station, entry.window_start)
            held = first.get(key)
            if held is None or revision < held.revision:
                first[key] = _Entry(
                    source, entry.station, entry.window_start, entry.sha256, revision, entry.model
                )
        tags = _read_manifest_tags(self._manifest_root, source)
        by_station: dict[str, list[_Entry]] = {}
        for item in sorted(first.values(), key=lambda e: e.run_ns):
            sealed = tags.get((item.station, item.run_ns, item.sha256))
            run_date = dt.datetime.fromtimestamp(item.run_ns // _NS, tz=dt.UTC).date()
            if sealed is None:
                self._counts["lamp_no_manifest_row"] += 1
            if sealed or run_date >= self._holdout_start:
                self._counts["lamp_holdout_sealed_skipped"] += 1
                continue
            by_station.setdefault(item.station, []).append(item)
        return by_station

    # -- selection ------------------------------------------------------------------

    def runs_for(self, station: str, *, anchor_ns: int) -> LampRunChoice:
        """Latest runs of the MDL basis (else LAV) available strictly before the anchor.

        Up to ``_KEEP_PARSED`` runs come back, so a +60 min lag twin can still find the latest run
        under its own, later, availability rule (``assemble_feature_row`` picks within them).
        """
        for source in (US_LAMP_MDL_SOURCE, US_LAV_IEM_SOURCE):
            runs = self._eligible(source, station, anchor_ns)
            if runs:
                return LampRunChoice(tuple(runs), _BASIS_BY_SOURCE[source])
        return LampRunChoice((), None)

    def _eligible(self, source: str, station: str, anchor_ns: int) -> list[LampRun]:
        lag = self._lags[source]
        candidates = [
            e
            for e in self._entries(source, station)
            if anchor_ns - _RUN_WINDOW_NS <= e.run_ns and e.run_ns + lag < anchor_ns
        ]
        parsed: list[LampRun] = []
        for entry in reversed(candidates[-_CANDIDATES:]):
            run = self._parse(entry, station)
            if run is not None:
                parsed.append(run)
            if len(parsed) == _KEEP_PARSED:
                break
        return list(reversed(parsed))

    def _parse(self, entry: _Entry, station: str) -> LampRun | None:
        key = (entry.source, station, entry.run_ns)
        if key in self._parsed:
            self._parsed.move_to_end(key)
            return self._parsed[key]
        run = self._load(entry, station)
        self._parsed[key] = run
        if len(self._parsed) > _LRU_SIZE:
            self._parsed.popitem(last=False)
        return run

    def _load(self, entry: _Entry, station: str) -> LampRun | None:
        available = entry.run_ns + self._lags[entry.source]
        request = revision_request(
            entry.source, entry.station, entry.run_ns, entry.revision, model=entry.model
        )
        try:
            payload = self._cache.read(request)
            if entry.source == US_LAMP_MDL_SOURCE:
                run = mdl_payload_to_lamp_run(
                    payload, station=station, run_ns=entry.run_ns, available_at_ns=available
                )
                if run is None:
                    self._counts["lamp_station_block_missing"] += 1
                return run
            return lav_csv_to_lamp_run(payload, station=station, available_at_ns=available)
        except (LampParseError, LavPayloadError, ArchiveCacheError, UnicodeDecodeError):
            self._counts["lamp_run_unreadable"] += 1
            return None
