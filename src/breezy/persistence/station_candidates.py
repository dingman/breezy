"""AUD-08b: the unregistered-city sighting sidecar and the station-candidate register.

ADVISORY ONLY. Nothing in this module -- and nothing that reads its
artefacts -- can make a city tradeable. A candidate record queues a human
act (a strategy-lead ruling plus the ``sites.toml`` re-verification gate,
AUD-08 §6c); it is never a subscription set, never an allow-list, and never
an input to any strategy.

Two artefacts, one schema family:

* the **sighting sidecar** -- ``sightings/sightings-<UTC day>.jsonl``, one
  :class:`UnregisteredCitySighting` per line, appended by the recorder
  process ONLY (the provider's attached :class:`SightingSink`; the single
  writer is enforced by construction in ``adapters/polymarket_us/factories``,
  not by a lock -- a lock would make two writers *work*, which is the
  defect). The file's day is the sighting's OWN ``observed_ts_ns`` in UTC,
  resolved per append, so a long-running recorder rotates correctly and no
  line can land in a file whose day differs from the day it claims.
* the **register** -- ``station_candidates.jsonl``, one
  :class:`StationCandidate` per ``(venue, city_token)``, rewritten
  atomically by the nightly emitter
  (``scripts/analysis/station_candidate_register.py``) and read by the
  AUD-09a census (hand-off H1).

Venue-neutral by placement: every record carries ``venue``, so a second
venue adapter reuses this module without importing a sibling adapter. It
imports nothing from Breezy at all.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol, get_args

__all__ = [
    "LAST_FOLDED_DAY_PATH",
    "SIGHTINGS_DIR",
    "SIGHTING_SCHEMA_VERSION",
    "STALE_AFTER_DAYS",
    "STATION_CANDIDATES_DIR",
    "STATION_CANDIDATES_PATH",
    "STATION_CANDIDATES_SCHEMA_VERSION",
    "WATERMARK_SCHEMA_VERSION",
    "FileSightingSink",
    "Origin",
    "SightingRead",
    "SightingSidecarCorruptError",
    "SightingSink",
    "StationCandidate",
    "StationCandidateRegisterCorruptError",
    "Sufficiency",
    "UnknownSightingSchemaError",
    "UnknownStationCandidateSchemaError",
    "UnregisteredCitySighting",
    "append_sighting",
    "compact_station_candidates",
    "merge_sightings",
    "read_last_folded_day",
    "read_sightings",
    "read_sightings_file",
    "read_station_candidates",
    "sighting_day",
    "sighting_file_days",
    "sighting_path",
    "stale_record_count",
    "write_last_folded_day",
    "write_station_candidates",
]

_LOG = logging.getLogger(__name__)

SIGHTING_SCHEMA_VERSION: Final[int] = 1
STATION_CANDIDATES_SCHEMA_VERSION: Final[int] = 1
WATERMARK_SCHEMA_VERSION: Final[int] = 1

#: A register record whose ``last_seen_day`` is older than this is compacted,
#: never deleted (AUD-08 §6b.2 retention, A15).
STALE_AFTER_DAYS: Final[int] = 180

STATION_CANDIDATES_DIR: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "derived" / "station_candidates"
)
SIGHTINGS_DIR: Final[Path] = STATION_CANDIDATES_DIR / "sightings"
STATION_CANDIDATES_PATH: Final[Path] = STATION_CANDIDATES_DIR / "station_candidates.jsonl"
LAST_FOLDED_DAY_PATH: Final[Path] = STATION_CANDIDATES_DIR / "last_folded_day.json"

_SIGHTING_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^sightings-(\d{4}-\d{2}-\d{2})\.jsonl$")

Origin = Literal["SIGHTING", "REGISTRY_SEED"]
Sufficiency = Literal[
    "NO_SETTLEMENT_TRUTH",
    "REGISTRY_ONLY_NO_CAPTURE",
    "CAPTURED_INSUFFICIENT",
    "CAPTURE_SUFFICIENT",
]
_ORIGINS: Final[frozenset[str]] = frozenset(get_args(Origin))
_SUFFICIENCIES: Final[frozenset[str]] = frozenset(get_args(Sufficiency))


class UnknownSightingSchemaError(ValueError):
    """A sidecar line carries a ``schema_version`` this reader does not know."""


class SightingSidecarCorruptError(ValueError):
    """A NON-final sidecar line is malformed: two writers interleaved."""


class UnknownStationCandidateSchemaError(ValueError):
    """A register line carries a ``schema_version`` this reader does not know."""


class StationCandidateRegisterCorruptError(ValueError):
    """A register line is malformed or the register repeats a key."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UnregisteredCitySighting:
    """One unregistered venue city on a discovery payload.

    ``city_token`` is the venue's lowercase slug token. ``observed_ts_ns`` is
    0 until the provider stamps it from its clock; an unstamped sighting is
    never appended (its day would be unknowable).
    """

    schema_version: int
    venue: str
    city_token: str
    slug: str
    climate_date: str
    observed_ts_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StationCandidate:
    """One ``(venue, city_token)`` row of the register.

    Two day domains, deliberately (AUD-09a H1 readers: do not compare them):

    * ``first_seen_day`` is the UTC day the register FIRST recorded the city
      -- the FOLD day -- and never moves. It is the durable once-per-candidate
      alert key (A16).
    * ``last_seen_day`` is the latest UTC day the venue was OBSERVED listing
      it (a seed: the latest fold that still found it in the settlement
      registry); monotone non-decreasing.

    Because the nightly fold runs the day after the observation, a NEW
    sighting-origin record normally has ``first_seen_day`` one day AFTER
    ``last_seen_day``. That is expected, not corruption.

    ``distinct_slugs`` / ``distinct_climate_days`` are a LOWER BOUND: each
    fold computes the distinct count over the retained sidecar window
    (35 days) and merges by ``max``, so a city listed for longer than the
    window under-counts rather than double-counts. Always 0 for a
    ``REGISTRY_SEED`` row, which never counts slugs.
    """

    schema_version: int
    venue: str
    city_token: str
    origin: Origin
    first_seen_day: str
    last_seen_day: str
    distinct_slugs: int
    distinct_climate_days: int
    sufficiency: Sufficiency

    @property
    def key(self) -> tuple[str, str]:
        return (self.venue, self.city_token)


class SightingSink(Protocol):
    """The one capability the provider needs to persist a sighting.

    Mirrors ``runtime/health.AlertSink``'s one-method shape. Attached to the
    recorder's provider only, after construction.
    """

    def append(self, sighting: UnregisteredCitySighting) -> None: ...


@dataclass(frozen=True, slots=True)
class FileSightingSink:
    """The file-backed :class:`SightingSink`. Construction performs no I/O."""

    directory: Path

    def append(self, sighting: UnregisteredCitySighting) -> None:
        append_sighting(self.directory, sighting)


@dataclass(frozen=True, slots=True)
class SightingRead:
    sightings: tuple[UnregisteredCitySighting, ...]
    partial_lines_skipped: int


# ---------------------------------------------------------------------------
# The sighting sidecar
# ---------------------------------------------------------------------------


def sighting_day(sighting: UnregisteredCitySighting) -> str:
    """The UTC day of the sighting's own ``observed_ts_ns`` -- never the wall clock."""
    if sighting.observed_ts_ns <= 0:
        raise ValueError(
            f"sighting for {sighting.venue}/{sighting.city_token} has observed_ts_ns="
            f"{sighting.observed_ts_ns}; an unstamped sighting has no day and is never written"
        )
    seconds, nanos = divmod(sighting.observed_ts_ns, 1_000_000_000)
    del nanos
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).date().isoformat()


def sighting_path(directory: Path, day: str) -> Path:
    return directory / f"sightings-{day}.jsonl"


def append_sighting(directory: Path, sighting: UnregisteredCitySighting) -> Path:
    """Append ONE line to the file named for the sighting's own UTC day.

    The path is resolved on every call (round-4 a1): one ``write()`` of one
    ``json.dumps(...) + "\\n"`` on an ``O_APPEND`` handle, flushed and closed
    before return.
    """
    path = sighting_path(directory, sighting_day(sighting))
    line = json.dumps(asdict(sighting), sort_keys=True) + "\n"
    directory.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
    return path


def sighting_file_days(directory: Path) -> tuple[str, ...]:
    """Days with a sidecar file, ascending. Non-sidecar names are ignored."""
    if not directory.is_dir():
        return ()
    days = []
    for entry in directory.iterdir():
        match = _SIGHTING_FILE_RE.match(entry.name)
        if match is not None and entry.is_file():
            days.append(match.group(1))
    return tuple(sorted(days))


def _sighting_from_record(record: Any, *, path: Path, line_number: int) -> UnregisteredCitySighting:
    if not isinstance(record, dict):
        raise SightingSidecarCorruptError(f"{path}: line {line_number} is not a JSON object")
    version = record.get("schema_version")
    if version != SIGHTING_SCHEMA_VERSION:
        raise UnknownSightingSchemaError(
            f"{path}: line {line_number} has schema_version {version!r}; "
            f"this reader knows only {SIGHTING_SCHEMA_VERSION}"
        )
    expected = {
        "schema_version": int,
        "venue": str,
        "city_token": str,
        "slug": str,
        "climate_date": str,
        "observed_ts_ns": int,
    }
    if set(record) != set(expected) or not all(
        isinstance(record[name], kind) and not isinstance(record[name], bool)
        for name, kind in expected.items()
    ):
        raise SightingSidecarCorruptError(
            f"{path}: line {line_number} does not carry exactly the sighting fields"
        )
    if record["observed_ts_ns"] <= 0:
        raise SightingSidecarCorruptError(f"{path}: line {line_number} has no observed_ts_ns stamp")
    return UnregisteredCitySighting(**record)


def read_sightings_file(path: Path) -> SightingRead:
    """Read one sidecar file, streaming, de-duplicated.

    A trailing partial line (the LAST line, with no ``\n``) is a recorder
    killed mid-write: skipped with a WARN and counted. Any other malformed
    line is interleaving -- the two-writer defect -- and refuses.

    Identical sightings (same ``venue``, ``city_token``, ``slug`` and UTC day)
    are kept once, first occurrence wins: the recorder's empty-listing retry
    loop can re-append the same sighting many times a day, and memory must be
    bounded by distinct markets, not by retries.
    """
    sightings: dict[tuple[str, str, str, str], UnregisteredCitySighting] = {}
    partial = 0
    with open(path, encoding="utf-8") as handle:
        pending: tuple[int, str] | None = None
        for index, line in enumerate(handle, start=1):
            if pending is not None:
                _accept_sighting_line(sightings, *pending, path=path)
            pending = (index, line)
        if pending is not None:
            index, line = pending
            if line.endswith("\n"):
                _accept_sighting_line(sightings, index, line, path=path)
            else:
                partial = 1
                _LOG.warning(
                    "%s: skipping a trailing partial line (%d bytes) -- a recorder "
                    "killed mid-write",
                    path,
                    len(line),
                )
    return SightingRead(sightings=tuple(sightings.values()), partial_lines_skipped=partial)


def _accept_sighting_line(
    sightings: dict[tuple[str, str, str, str], UnregisteredCitySighting],
    index: int,
    line: str,
    *,
    path: Path,
) -> None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SightingSidecarCorruptError(
            f"{path}: line {index} is not valid JSON and is not the final line; "
            "two writers interleaved"
        ) from exc
    sighting = _sighting_from_record(record, path=path, line_number=index)
    key = (sighting.venue, sighting.city_token, sighting.slug, sighting_day(sighting))
    sightings.setdefault(key, sighting)


def read_sightings(path: Path) -> tuple[UnregisteredCitySighting, ...]:
    return read_sightings_file(path).sightings


# ---------------------------------------------------------------------------
# The fold (pure: no I/O, no sufficiency computation)
# ---------------------------------------------------------------------------


def _required_sufficiency(
    key: tuple[str, str], sufficiency_by_city: Mapping[tuple[str, str], Sufficiency]
) -> Sufficiency:
    try:
        return sufficiency_by_city[key]
    except KeyError as exc:
        raise ValueError(
            f"sufficiency_by_city carries no value for {key}; the fold never computes one"
        ) from exc


def merge_sightings(
    existing: Sequence[StationCandidate],
    sightings: Sequence[UnregisteredCitySighting],
    *,
    seed_cities: Sequence[tuple[str, str]],
    today: str,
    sufficiency_by_city: Mapping[tuple[str, str], Sufficiency],
) -> tuple[StationCandidate, ...]:
    """Fold sightings and registry seeds into the register. Idempotent.

    ``sightings`` is every RETAINED sidecar sighting (not only the newest
    day), so ``distinct_*`` are exact over the retention window and
    re-folding the same input is a no-op. Merge rules (AUD-08 §6b.2):
    ``first_seen_day`` and ``origin`` never change once set;
    ``last_seen_day`` and ``distinct_*`` never decrease; a city absent from
    this fold keeps its record; output ordered by ``(venue, city_token)``.
    """
    by_key: dict[tuple[str, str], StationCandidate] = {}
    for record in existing:
        if record.key in by_key:
            raise StationCandidateRegisterCorruptError(f"register repeats key {record.key}")
        by_key[record.key] = record

    for key in dict.fromkeys(seed_cities):
        sufficiency = _required_sufficiency(key, sufficiency_by_city)
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = StationCandidate(
                schema_version=STATION_CANDIDATES_SCHEMA_VERSION,
                venue=key[0],
                city_token=key[1],
                origin="REGISTRY_SEED",
                first_seen_day=today,
                last_seen_day=today,
                distinct_slugs=0,
                distinct_climate_days=0,
                sufficiency=sufficiency,
            )
        elif prior.origin == "REGISTRY_SEED":
            by_key[key] = replace(
                prior,
                last_seen_day=max(prior.last_seen_day, today),
                sufficiency=sufficiency,
            )

    grouped: dict[tuple[str, str], list[UnregisteredCitySighting]] = {}
    for sighting in sightings:
        grouped.setdefault((sighting.venue, sighting.city_token), []).append(sighting)

    for key, group in grouped.items():
        last_seen = max(sighting_day(s) for s in group)
        slugs = len({s.slug for s in group})
        climate_days = len({s.climate_date for s in group})
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = StationCandidate(
                schema_version=STATION_CANDIDATES_SCHEMA_VERSION,
                venue=key[0],
                city_token=key[1],
                origin="SIGHTING",
                first_seen_day=today,
                last_seen_day=last_seen,
                distinct_slugs=slugs,
                distinct_climate_days=climate_days,
                sufficiency=_required_sufficiency(key, sufficiency_by_city),
            )
            continue
        if prior.origin == "REGISTRY_SEED":
            # A seed is not a sighting and never counts slugs (§6b.3); its
            # sufficiency is the seed path's. Only last_seen_day moves.
            by_key[key] = replace(prior, last_seen_day=max(prior.last_seen_day, last_seen))
            continue
        updated = replace(
            prior,
            last_seen_day=max(prior.last_seen_day, last_seen),
            distinct_slugs=max(prior.distinct_slugs, slugs),
            distinct_climate_days=max(prior.distinct_climate_days, climate_days),
        )
        if key in sufficiency_by_city:
            updated = replace(updated, sufficiency=sufficiency_by_city[key])
        by_key[key] = updated

    return tuple(by_key[key] for key in sorted(by_key))


def compact_station_candidates(
    candidates: Sequence[StationCandidate],
    *,
    today: str,
    sufficiency_by_city: Mapping[tuple[str, str], Sufficiency],
) -> tuple[StationCandidate, ...]:
    """A15: a record unseen for over 180 days is compacted, never deleted.

    Counts and ``last_seen_day`` are frozen; ``sufficiency`` is recomputed
    from the supplied mapping when it carries the key. Idempotent.
    """
    horizon = (dt.date.fromisoformat(today) - dt.timedelta(days=STALE_AFTER_DAYS)).isoformat()
    compacted = []
    for record in candidates:
        if record.last_seen_day < horizon and record.key in sufficiency_by_city:
            record = replace(record, sufficiency=sufficiency_by_city[record.key])
        compacted.append(record)
    return tuple(compacted)


def stale_record_count(candidates: Sequence[StationCandidate], *, today: str) -> int:
    horizon = (dt.date.fromisoformat(today) - dt.timedelta(days=STALE_AFTER_DAYS)).isoformat()
    return sum(1 for record in candidates if record.last_seen_day < horizon)


# ---------------------------------------------------------------------------
# Register writer / reader, watermark
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_station_candidates(path: Path, candidates: Sequence[StationCandidate]) -> None:
    """One line per candidate, stable key order, atomic temp + ``os.replace``."""
    text = "".join(json.dumps(asdict(record), sort_keys=True) + "\n" for record in candidates)
    _atomic_write_text(path, text)


def _candidate_from_record(record: Any, *, path: Path, line_number: int) -> StationCandidate:
    if not isinstance(record, dict):
        raise StationCandidateRegisterCorruptError(
            f"{path}: line {line_number} is not a JSON object"
        )
    version = record.get("schema_version")
    if version != STATION_CANDIDATES_SCHEMA_VERSION:
        raise UnknownStationCandidateSchemaError(
            f"{path}: line {line_number} has schema_version {version!r}; "
            f"this reader knows only {STATION_CANDIDATES_SCHEMA_VERSION}"
        )
    expected = {
        "schema_version": int,
        "venue": str,
        "city_token": str,
        "origin": str,
        "first_seen_day": str,
        "last_seen_day": str,
        "distinct_slugs": int,
        "distinct_climate_days": int,
        "sufficiency": str,
    }
    if (
        set(record) != set(expected)
        or not all(
            isinstance(record[name], kind) and not isinstance(record[name], bool)
            for name, kind in expected.items()
        )
        or record["origin"] not in _ORIGINS
        or record["sufficiency"] not in _SUFFICIENCIES
    ):
        raise StationCandidateRegisterCorruptError(
            f"{path}: line {line_number} is not a valid station-candidate record"
        )
    return StationCandidate(**record)


def read_station_candidates(path: Path) -> tuple[StationCandidate, ...]:
    """Read the register. Absent file = empty register. Never guesses a version."""
    if not path.exists():
        return ()
    records = []
    seen: set[tuple[str, str]] = set()
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StationCandidateRegisterCorruptError(
                f"{path}: line {index} is not valid JSON"
            ) from exc
        record = _candidate_from_record(raw, path=path, line_number=index)
        if record.key in seen:
            raise StationCandidateRegisterCorruptError(f"{path}: line {index} repeats {record.key}")
        seen.add(record.key)
        records.append(record)
    return tuple(records)


def read_last_folded_day(path: Path) -> str | None:
    """The watermark. Absent, unreadable or unknown-version reads as ``None``.

    ``None`` means "fold every unpruned sidecar file" -- safe because the fold
    is idempotent (AUD-08 §6b.4).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != WATERMARK_SCHEMA_VERSION:
        return None
    day = raw.get("last_folded_day")
    if not isinstance(day, str):
        return None
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return None
    return day


def write_last_folded_day(path: Path, day: str) -> None:
    dt.date.fromisoformat(day)
    payload = {"last_folded_day": day, "schema_version": WATERMARK_SCHEMA_VERSION}
    _atomic_write_text(path, json.dumps(payload, sort_keys=True) + "\n")
