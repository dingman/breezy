"""Append-only AFOS CLI revision store (FQ loss response F2).

Split out of ``iem_cli_fetch.py`` to keep that module small; this is the ONLY module
that writes the AFOS CLI cache (``afos-cli/<LOC>/``), and ``iem_cli_fetch.py`` is its
only caller. See that module's docstring for the revision, promotion and exit-code
contract. Reads no environment variable; no network.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "AFOS_CACHE_SUBDIR",
    "CHANGES_LOG_NAME",
    "REJECTED_LOG_NAME",
    "CacheLockedError",
    "PromoteRefused",
    "Promotion",
    "Revision",
    "RevisionStore",
    "SkippedRevision",
    "atomic_write",
    "run_promote_command",
    "sha256_hex",
]

# Same numbers as iem_cli_fetch EXIT_OK / EXIT_REFUSED / EXIT_ABORTED.
_PROMOTE_EXIT_OK: Final[int] = 0
_PROMOTE_EXIT_REFUSED: Final[int] = 2
_PROMOTE_EXIT_ABORTED: Final[int] = 3
_MARKER_ID_RE: Final[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}\.\d{3,}")
_SHA_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{8,64}")
_CONFIRM_RE: Final[re.Pattern[str]] = re.compile(r"(\d{4}-\d{2}-\d{2})=(-?\d+)\Z")

AFOS_CACHE_SUBDIR: Final[str] = "afos-cli"
LOCK_NAME: Final[str] = ".lock"
REJECTED_LOG_NAME: Final[str] = "rejected.jsonl"
CHANGES_LOG_NAME: Final[str] = "changes.jsonl"
REVISION_SCHEMA: Final[str] = "afos_cli_revision/v1"
_BODY_SHA_PREFIX_LEN: Final[int] = 12
_STATION_RE: Final[re.Pattern[str]] = re.compile(r"[A-Z]{3}")
logger = logging.getLogger("breezy.truth_fetch")


class CacheLockedError(RuntimeError):
    """Another writer holds the cache lock."""


@dataclass(frozen=True, slots=True)
class Revision:
    station: str
    fetch_date: dt.date
    url: str
    body_path: Path
    body_sha256: str
    label_days: tuple[dt.date, ...]
    catalog_check: Mapping[str, Any]
    promoted: bool = True


@dataclass(frozen=True, slots=True)
class SkippedRevision:
    station: str
    marker: str
    reason: str


class PromoteRefused(ValueError):
    """A promotion guard failed. Nothing was written."""


@dataclass(frozen=True, slots=True)
class Promotion:
    station: str
    marker: str
    body_sha256: str
    promoted_at: str


class _InvalidRevisionError(Exception):
    """A marker that cannot be trusted; the reason is logged and reported."""


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _parse_confirms(pairs: Sequence[str]) -> dict[str, int]:
    if not pairs:
        raise PromoteRefused("at least one --confirm DAY=VALUE is required")
    confirmed: dict[str, int] = {}
    for raw in pairs:
        if not isinstance(raw, str):
            raise PromoteRefused(f"confirm must be DAY=VALUE: {raw!r}")
        match = _CONFIRM_RE.fullmatch(raw.strip())
        if match is None:
            raise PromoteRefused(f"confirm must be DAY=VALUE: {raw!r}")
        day = match.group(1)
        try:
            dt.date.fromisoformat(day)
        except ValueError as exc:
            raise PromoteRefused(f"confirm must be DAY=VALUE: {raw!r}") from exc
        if day in confirmed:
            raise PromoteRefused(f"duplicate confirm for {day}")
        confirmed[day] = int(match.group(2))
    return confirmed


def _utc_stamp(moment: dt.datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PromoteRefused("promoted_at must be timezone-aware UTC")
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha_prefix_matches(marker: Path, prefix: str) -> bool:
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(meta, dict):
        return False
    digest = meta.get("body_sha256")
    return isinstance(digest, str) and digest.lower().startswith(prefix)


def _resolve_marker(directory: Path, revision: str) -> Path:
    if not directory.is_dir():
        raise PromoteRefused("no revisions for station")
    token = revision.strip()
    if token != Path(token).name or token.startswith("."):
        raise PromoteRefused("revision id must be a marker name or sha256 prefix")
    stem = token.removesuffix(".json")
    if _MARKER_ID_RE.fullmatch(stem):
        path = directory / f"{stem}.json"
        if not path.is_file():
            raise PromoteRefused(f"marker not found: {stem}.json")
        return path
    lowered = token.lower()
    if not _SHA_PREFIX_RE.fullmatch(lowered):
        raise PromoteRefused(f"revision not found: {revision}")
    matches = [
        marker
        for marker in sorted(directory.glob("*.json"))
        if _sha_prefix_matches(marker, lowered)
    ]
    if len(matches) != 1:
        raise PromoteRefused(f"sha256 prefix {revision} matched {len(matches)} markers")
    return matches[0]


def _load_marker_meta(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromoteRefused(f"marker unreadable: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PromoteRefused("marker is not an object")
    meta: dict[str, Any] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise PromoteRefused("marker keys must be strings")
        meta[key] = value
    return meta


def _require_promotable(meta: Mapping[str, Any], station: str) -> None:
    if meta.get("schema") != REVISION_SCHEMA or meta.get("station") != station:
        raise PromoteRefused("schema or station mismatch")
    if meta.get("promoted") is not False:
        raise PromoteRefused("already promoted")


def _require_body_sha(directory: Path, meta: Mapping[str, Any]) -> None:
    body_file = meta.get("body_file")
    bare = isinstance(body_file, str) and bool(body_file) and Path(body_file).name == body_file
    expected = meta.get("body_sha256")
    if not bare or not isinstance(expected, str) or not isinstance(body_file, str):
        raise PromoteRefused("body sha256 mismatch")
    try:
        actual = sha256_hex((directory / body_file).read_bytes())
    except OSError as exc:
        raise PromoteRefused(f"body sha256 mismatch: {exc}") from exc
    if actual != expected:
        raise PromoteRefused("body sha256 mismatch")


def _require_catalog(check: Any, allow_no_catalog: bool) -> None:
    if not isinstance(check, dict):
        raise PromoteRefused("catalog check missing")
    if check.get("disagreement") is True:
        raise PromoteRefused("catalog disagreement")
    status = check.get("status")
    if status == "unavailable":
        if not allow_no_catalog:
            raise PromoteRefused("catalog unavailable; pass --allow-no-catalog")
        return
    if status != "compared" or check.get("disagreement") is not False:
        raise PromoteRefused("catalog check not clean")


def _recorded_new_values(meta: Mapping[str, Any]) -> dict[str, int]:
    raw = meta.get("value_change_unconfirmed")
    if not isinstance(raw, list) or not raw:
        raise PromoteRefused("no unconfirmed value changes recorded")
    recorded: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise PromoteRefused("value_change_unconfirmed entry is not an object")
        day = item.get("climate_day")
        value = item.get("new_tmax_f")
        if not isinstance(day, str) or day in recorded:
            raise PromoteRefused("value_change_unconfirmed entry is malformed")
        if not isinstance(value, int) or isinstance(value, bool):
            raise PromoteRefused("value_change_unconfirmed entry is malformed")
        recorded[day] = value
    return recorded


def _require_exact_confirms(recorded: Mapping[str, int], confirmed: Mapping[str, int]) -> None:
    missing = sorted(set(recorded) - set(confirmed))
    extra = sorted(set(confirmed) - set(recorded))
    wrong = sorted(day for day in set(recorded) & set(confirmed) if recorded[day] != confirmed[day])
    if not missing and not extra and not wrong:
        return
    parts: list[str] = []
    if missing:
        parts.append(f"missing={missing}")
    if extra:
        parts.append(f"extra={extra}")
    if wrong:
        parts.append(f"wrong={wrong}")
    raise PromoteRefused("confirms do not match value_change_unconfirmed: " + " ".join(parts))


def _confirmed_pairs(confirmed: Mapping[str, int]) -> list[dict[str, Any]]:
    return [{"climate_day": day, "new_tmax_f": confirmed[day]} for day in sorted(confirmed)]


def _copy_change(change: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "climate_day": change["climate_day"],
        "old_tmax_f": change["old_tmax_f"],
        "new_tmax_f": change["new_tmax_f"],
        "old_correction_flag": change["old_correction_flag"],
        "new_correction_flag": change["new_correction_flag"],
    }


def _copy_catalog(check: Mapping[str, Any]) -> dict[str, Any]:
    raw = check["disagreements"]
    if not isinstance(raw, list):
        raise PromoteRefused("catalog disagreements is not a list")
    disagreements: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PromoteRefused("catalog disagreement entry is not an object")
        disagreements.append(
            {
                "climate_day": item["climate_day"],
                "cli_tmax_f": item["cli_tmax_f"],
                "catalog_tmax_f": item["catalog_tmax_f"],
            }
        )
    return {
        "status": check["status"],
        "compared_days": check["compared_days"],
        "disagreement": check["disagreement"],
        "disagreements": disagreements,
    }


def _promoted_marker(
    meta: Mapping[str, Any],
    *,
    stamp: str,
    confirmed: Mapping[str, int],
    reviewer_note: str,
) -> dict[str, Any]:
    changes = meta["value_change_unconfirmed"]
    label_days = meta["label_days"]
    catalog = meta["catalog_check"]
    if not isinstance(changes, list) or not isinstance(label_days, list):
        raise PromoteRefused("marker lists are malformed")
    if not isinstance(catalog, dict):
        raise PromoteRefused("catalog check missing")
    copied = [_copy_change(change) for change in changes if isinstance(change, dict)]
    if len(copied) != len(changes):
        raise PromoteRefused("value_change_unconfirmed entry is not an object")
    return {
        "schema": meta["schema"],
        "station": meta["station"],
        "fetch_date": meta["fetch_date"],
        "url": meta["url"],
        "body_file": meta["body_file"],
        "body_sha256": meta["body_sha256"],
        "body_bytes": meta["body_bytes"],
        "label_days": list(label_days),
        "catalog_check": _copy_catalog(catalog),
        "promoted": True,
        "value_change_unconfirmed": copied,
        "promotion": {
            "promoted_at": stamp,
            "confirmed": _confirmed_pairs(confirmed),
            "reviewer_note": reviewer_note,
        },
    }


def _promotion_log(
    meta: Mapping[str, Any],
    marker_name: str,
    stamp: str,
    confirmed: Mapping[str, int],
    reviewer_note: str,
) -> dict[str, Any]:
    return {
        "event": "promoted",
        "marker": marker_name,
        "fetch_date": meta["fetch_date"],
        "body_sha256": meta["body_sha256"],
        "promoted_at": stamp,
        "confirmed": _confirmed_pairs(confirmed),
        "reviewer_note": reviewer_note,
    }


class RevisionStore:
    def __init__(self, cache_dir: Path) -> None:
        self._root = cache_dir / AFOS_CACHE_SUBDIR

    @property
    def root(self) -> Path:
        return self._root

    def station_dir(self, station: str) -> Path:
        if not _STATION_RE.fullmatch(station):
            raise ValueError(f"station must match [A-Z]{{3}}: {station!r}")
        return self._root / station

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / LOCK_NAME).open("a") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CacheLockedError("another AFOS CLI cache writer holds the lock") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def latest_valid(self, station: str) -> Revision | None:
        """The newest promoted revision whose marker parses and whose body matches its sha."""
        return self.latest_valid_report(station)[0]

    def latest_valid_report(
        self, station: str
    ) -> tuple[Revision | None, tuple[SkippedRevision, ...]]:
        """``latest_valid`` plus every newer corrupt marker skipped on the way (also logged)."""
        directory = self.station_dir(station)
        skipped: list[SkippedRevision] = []
        if not directory.is_dir():
            return None, ()
        for marker in sorted(directory.glob("*.json"), reverse=True):
            try:
                revision = self._load(station, directory, marker)
            except _InvalidRevisionError as exc:
                logger.warning("skipped revision %s/%s: %s", station, marker.name, exc)
                skipped.append(SkippedRevision(station, marker.name, str(exc)))
                continue
            if revision.promoted:
                return revision, tuple(skipped)
        return None, tuple(skipped)

    def _load(self, station: str, directory: Path, marker: Path) -> Revision:
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta["schema"] != REVISION_SCHEMA or meta["station"] != station:
                raise _InvalidRevisionError("schema or station mismatch")
            body_file = str(meta["body_file"])
            if body_file != Path(body_file).name:
                raise _InvalidRevisionError("body_file is not a bare file name")
            body_path = directory / body_file
            if sha256_hex(body_path.read_bytes()) != meta["body_sha256"]:
                raise _InvalidRevisionError("body sha256 mismatch")
            return Revision(
                station=station,
                fetch_date=dt.date.fromisoformat(meta["fetch_date"]),
                url=str(meta["url"]),
                body_path=body_path,
                body_sha256=str(meta["body_sha256"]),
                label_days=tuple(dt.date.fromisoformat(day) for day in meta["label_days"]),
                catalog_check=dict(meta["catalog_check"]),
                promoted=bool(meta.get("promoted", True)),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _InvalidRevisionError(f"{type(exc).__name__}: {exc}") from exc

    def commit(
        self,
        *,
        station: str,
        fetch_date: dt.date,
        url: str,
        body: bytes,
        label_days: Sequence[dt.date],
        catalog_check: Mapping[str, Any],
        value_changes: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Append a revision (body then marker); never unlinks. Caller holds ``locked()``."""
        directory = self.station_dir(station)
        directory.mkdir(parents=True, exist_ok=True)
        digest = sha256_hex(body)
        seq = len(list(directory.glob(f"{fetch_date.isoformat()}.*.json")))
        stem = f"{fetch_date.isoformat()}.{seq:03d}"
        body_name = f"{stem}.{digest[:_BODY_SHA_PREFIX_LEN]}.txt"
        atomic_write(directory / body_name, body)
        meta = {
            "schema": REVISION_SCHEMA,
            "station": station,
            "fetch_date": fetch_date.isoformat(),
            "url": url,
            "body_file": body_name,
            "body_sha256": digest,
            "body_bytes": len(body),
            "label_days": [day.isoformat() for day in sorted(label_days)],
            "catalog_check": dict(catalog_check),
            "promoted": not value_changes,
            "value_change_unconfirmed": [dict(change) for change in value_changes],
        }
        atomic_write(directory / f"{stem}.json", (json.dumps(meta, sort_keys=True) + "\n").encode())
        for change in value_changes:
            _append_jsonl(
                directory / CHANGES_LOG_NAME,
                {"fetch_date": fetch_date.isoformat(), "body_sha256": digest, **change},
            )
        return digest

    def log_rejection(
        self, *, station: str, fetch_date: dt.date, reason: str, body: bytes, detail: str
    ) -> None:
        directory = self.station_dir(station)
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "fetch_date": fetch_date.isoformat(),
            "reason": reason,
            "body_sha256": sha256_hex(body),
            "body_bytes": len(body),
            "detail": detail,
        }
        _append_jsonl(directory / REJECTED_LOG_NAME, record)

    def promote(
        self,
        *,
        station: str,
        revision_id: str,
        confirms: Sequence[str],
        reviewer_note: str,
        allow_no_catalog: bool,
        promoted_at: dt.datetime,
    ) -> Promotion:
        """Rewrite one unpromoted marker in place. Holds the cache lock; never touches a body."""
        if not isinstance(reviewer_note, str) or not reviewer_note.strip():
            raise PromoteRefused("reviewer note is required")
        confirmed = _parse_confirms(confirms)
        stamp = _utc_stamp(promoted_at)
        with self.locked():
            return self._promote_locked(
                station=station,
                revision_id=revision_id,
                confirmed=confirmed,
                reviewer_note=reviewer_note,
                allow_no_catalog=allow_no_catalog,
                stamp=stamp,
            )

    def _promote_locked(
        self,
        *,
        station: str,
        revision_id: str,
        confirmed: Mapping[str, int],
        reviewer_note: str,
        allow_no_catalog: bool,
        stamp: str,
    ) -> Promotion:
        directory = self.station_dir(station)
        marker = _resolve_marker(directory, revision_id)
        meta = _load_marker_meta(marker)
        _require_promotable(meta, station)
        _require_body_sha(directory, meta)
        _require_catalog(meta.get("catalog_check"), allow_no_catalog)
        _require_exact_confirms(_recorded_new_values(meta), confirmed)
        try:
            updated = _promoted_marker(
                meta, stamp=stamp, confirmed=confirmed, reviewer_note=reviewer_note
            )
            log_line = _promotion_log(meta, marker.name, stamp, confirmed, reviewer_note)
        except KeyError as exc:
            raise PromoteRefused(f"marker missing {exc}") from exc
        atomic_write(marker, (json.dumps(updated, sort_keys=True) + "\n").encode())
        _append_jsonl(directory / CHANGES_LOG_NAME, log_line)
        return Promotion(
            station=station,
            marker=marker.name,
            body_sha256=str(meta["body_sha256"]),
            promoted_at=stamp,
        )


def run_promote_command(args: argparse.Namespace, *, now: dt.datetime) -> int:
    """Promote one revision. Exit codes match ``iem_cli_fetch`` (0 ok, 2 refused, 3 lock)."""
    from settlement_alignment_cache import (  # type: ignore[import-not-found]
        SettlementAlignmentCacheError,
        require_settlement_alignment_cache_dir,
    )

    try:
        promoted = RevisionStore(require_settlement_alignment_cache_dir(args.cache_dir)).promote(
            station=str(args.station),
            revision_id=str(args.revision),
            confirms=tuple(args.confirm),
            reviewer_note=str(args.reviewer_note),
            allow_no_catalog=bool(args.allow_no_catalog),
            promoted_at=now,
        )
    except CacheLockedError as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return _PROMOTE_EXIT_ABORTED
    except (PromoteRefused, SettlementAlignmentCacheError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return _PROMOTE_EXIT_REFUSED
    print(f"promoted {promoted.station} {promoted.marker}")
    return _PROMOTE_EXIT_OK
