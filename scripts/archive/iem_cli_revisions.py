"""Append-only AFOS CLI revision store (FQ loss response F2).

Split out of ``iem_cli_fetch.py`` to keep that module small; this is the ONLY module
that writes the AFOS CLI cache (``afos-cli/<LOC>/``), and ``iem_cli_fetch.py`` is its
only caller. See that module's docstring for the revision, promotion and exit-code
contract. Reads no environment variable; no network.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "AFOS_CACHE_SUBDIR",
    "CHANGES_LOG_NAME",
    "REJECTED_LOG_NAME",
    "CacheLockedError",
    "Revision",
    "RevisionStore",
    "SkippedRevision",
    "atomic_write",
    "sha256_hex",
]

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
