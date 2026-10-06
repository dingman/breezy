"""Append-only revision store for the F13 US-source raw payloads (H4, R17, R28, R32).

``ArchiveCache`` is unmodified and is used here ONLY as the write API: the
change detector is this module, which compares the fetched sha256 against the
digests of every stored raw revision for ``(source, station, run_ts, base)``.

* A payload whose digest is already stored appends nothing.
* A new digest is written as ``<base>-r<N>`` with ``N = 1 + max`` (``-r0`` is
  the first-seen revision and stays the timing anchor), through
  ``ArchiveCache(fetch=<closure returning the already-fetched bytes>)
  .get_or_fetch`` on a key verified ``missing()``.
* Digest set, ``N`` and the write all run under the source's unit lock
  ``<root>/<source>/collector.lock`` -- never ``coverage.json.lock``, which the
  cache takes non-blocking for its own commit.
* UTF-8 and any caller-supplied parse validation run BEFORE the write, so a
  refused payload never leaves an orphan.
* An outlier (deviation from every other source above a prereg threshold) is
  quarantined to an append-only ledger instead of being promoted.
"""

from __future__ import annotations

import contextlib
import csv
import errno
import fcntl
import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest, count_rows
from breezy.persistence.us_source_request import (
    US_SOURCE_PRODUCTS,
    revision_product_pattern,
    revision_request,
)

__all__ = [
    "AppendOutcome",
    "RevisionPayloadRefusedError",
    "RevisionResult",
    "RevisionStoreBusyError",
    "RevisionStoreError",
    "RevisionStoreIntegrityError",
    "UsSourceRevisionStore",
]

LOCK_NAME: Final[str] = "collector.lock"
QUARANTINE_NAME: Final[str] = "quarantine.jsonl"
_SYMLINKED_LOCK_ERRNOS: Final[frozenset[int]] = frozenset({errno.ELOOP, errno.EMLINK})

_LEDGER_FIELDS: Final[dict[str, type]] = {
    "base_product": str,
    "run_ts_ns": int,
    "sha256": str,
    "station": str,
}

Validator = Callable[[bytes], None]
#: Smallest absolute deviation (deg F) from every OTHER source, or None when
#: there is nothing to compare against. Supplied by the caller; pure.
OutlierProbe = Callable[[bytes], float | None]


class _NanosecondClock(Protocol):
    def timestamp_ns(self) -> int: ...


class RevisionStoreError(Exception):
    """Base for every local refusal. Not a TransportError, CliParseError or CliSanityError."""


class RevisionPayloadRefusedError(RevisionStoreError):
    """The payload failed the pre-write checks. Nothing was written."""


class RevisionStoreBusyError(RevisionStoreError):
    """Another run holds the unit lock. Blocking is not offered; skip the cycle."""


class RevisionStoreIntegrityError(RevisionStoreError):
    """The on-disk state contradicts the store's invariants."""


class AppendOutcome(StrEnum):
    APPENDED = "appended"
    UNCHANGED = "unchanged"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class RevisionResult:
    outcome: AppendOutcome
    sha256: str
    revision: int | None
    request: ArchiveRequest | None


class UsSourceRevisionStore:
    def __init__(
        self,
        root: Path,
        clock: _NanosecondClock,
        *,
        validator: Validator | None = None,
        outlier_probe: OutlierProbe | None = None,
        outlier_threshold_f: float | None = None,
    ) -> None:
        if (outlier_probe is None) != (outlier_threshold_f is None):
            raise ValueError(
                "outlier_probe and outlier_threshold_f are given together or not at all"
            )
        if outlier_threshold_f is not None and not outlier_threshold_f > 0:
            raise ValueError("outlier_threshold_f must be > 0")
        self._root = Path(root)
        self._clock = clock
        self._validator = validator
        self._outlier_probe = outlier_probe
        self._outlier_threshold_f = outlier_threshold_f
        self._payload: bytes = b""
        self._cache = ArchiveCache(self._root, fetch=self._fetch_closure, clock=clock)
        self._held: dict[str, tuple[int, int]] = {}  # source -> (owner thread, depth)

    def _fetch_closure(self, _request: ArchiveRequest) -> bytes:
        return self._payload

    # -- unit lock ---------------------------------------------------------

    def lock_path(self, source: str) -> Path:
        return self._root / source / LOCK_NAME

    @contextlib.contextmanager
    def unit_lock(self, source: str) -> Iterator[None]:
        """Non-blocking exclusive flock on ``<root>/<source>/collector.lock``; re-entrant here."""
        if source not in US_SOURCE_PRODUCTS:
            raise ValueError(f"unknown US source {source!r}")
        me = threading.get_ident()
        held = self._held.get(source)
        if held is not None:
            owner, depth = held
            if owner != me:
                raise RevisionStoreBusyError(
                    f"{source} is locked by another thread of this store; one writer per unit"
                )
            self._held[source] = (owner, depth + 1)
            try:
                yield
            finally:
                self._held[source] = (owner, self._held[source][1] - 1)
            return
        path = self.lock_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
        except OSError as exc:
            if exc.errno in _SYMLINKED_LOCK_ERRNOS:
                raise RevisionStoreIntegrityError(f"refusing a symlinked lock at {path}") from exc
            raise RevisionStoreIntegrityError(
                f"could not open the unit lock {path}: {exc}"
            ) from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise RevisionStoreBusyError(f"another run holds {path}") from exc
        self._held[source] = (me, 1)
        try:
            yield
        finally:
            del self._held[source]
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # -- reads -------------------------------------------------------------

    def revisions(
        self, source: str, station: str, run_ts_ns: int, base_product: str
    ) -> tuple[tuple[int, str], ...]:
        """``(N, sha256)`` for raw-payload entries only, ascending by ``N`` (R32)."""
        pattern = revision_product_pattern(base_product)
        found: list[tuple[int, str]] = []
        for entry in self._cache.entries(source):
            if entry.station != station or entry.window_start != run_ts_ns:
                continue
            matched = pattern.fullmatch(entry.product)
            if matched is not None:
                found.append((int(matched.group(1)), entry.sha256))
        return tuple(sorted(found))

    def digests(
        self, source: str, station: str, run_ts_ns: int, base_product: str
    ) -> frozenset[str]:
        return frozenset(sha for _, sha in self.revisions(source, station, run_ts_ns, base_product))

    def anchor_revision(
        self, source: str, station: str, run_ts_ns: int, base_product: str
    ) -> int | None:
        """The first-seen revision (lowest ``N``), the timing anchor. None if nothing stored."""
        stored = self.revisions(source, station, run_ts_ns, base_product)
        return stored[0][0] if stored else None

    def quarantined_count(
        self, source: str, station: str, run_ts_ns: int, base_product: str
    ) -> int:
        return sum(
            1
            for row in self._read_quarantine(source)
            if row["station"] == station
            and row["run_ts_ns"] == run_ts_ns
            and row["base_product"] == base_product
        )

    # -- the append --------------------------------------------------------

    def append_if_new(
        self,
        *,
        source: str,
        station: str,
        run_ts_ns: int,
        model: str | None,
        payload: bytes,
    ) -> RevisionResult:
        base = US_SOURCE_PRODUCTS.get(source)
        if base is None:
            raise ValueError(f"unknown US source {source!r}")
        self._check_payload(payload)
        sha = hashlib.sha256(payload).hexdigest()
        with self.unit_lock(source):
            stored = self.revisions(source, station, run_ts_ns, base)
            if sha in {s for _, s in stored}:
                return RevisionResult(AppendOutcome.UNCHANGED, sha, None, None)
            if self._is_quarantined(source, station, run_ts_ns, base, sha):
                return RevisionResult(AppendOutcome.QUARANTINED, sha, None, None)
            deviation = self._deviation(payload)
            if deviation is not None:
                self._append_quarantine(source, station, run_ts_ns, base, sha, deviation)
                return RevisionResult(AppendOutcome.QUARANTINED, sha, None, None)
            number = stored[-1][0] + 1 if stored else 0
            request = revision_request(source, station, run_ts_ns, number, model=model)
            if not self._cache.missing(request):
                raise RevisionStoreIntegrityError(
                    f"key for {request.product} already exists but its digest is not in the set"
                )
            self._payload = payload
            try:
                self._cache.get_or_fetch(request)
            finally:
                self._payload = b""
            return RevisionResult(AppendOutcome.APPENDED, sha, number, request)

    # -- pre-write checks ----------------------------------------------------

    def _check_payload(self, payload: bytes) -> None:
        if not isinstance(payload, bytes) or not payload.strip():
            raise RevisionPayloadRefusedError("payload must be non-empty bytes")
        try:
            payload.decode("utf-8")
            count_rows(payload)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise RevisionPayloadRefusedError(f"payload is not valid UTF-8 or CSV: {exc}") from exc
        if self._validator is None:
            return
        try:
            self._validator(payload)
        except RevisionStoreError:
            raise
        except Exception as exc:
            raise RevisionPayloadRefusedError(
                f"caller validation refused the payload: {exc}"
            ) from exc

    def _deviation(self, payload: bytes) -> float | None:
        if self._outlier_probe is None or self._outlier_threshold_f is None:
            return None
        deviation = self._outlier_probe(payload)
        if deviation is not None and deviation > self._outlier_threshold_f:
            return deviation
        return None

    # -- quarantine ledger ---------------------------------------------------

    def _quarantine_path(self, source: str) -> Path:
        return self._root / source / QUARANTINE_NAME

    def _read_quarantine(self, source: str) -> list[dict[str, Any]]:
        path = self._quarantine_path(source)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RevisionStoreIntegrityError(f"{path}: corrupt quarantine line") from exc
            if not isinstance(row, dict) or any(
                not isinstance(row.get(name), kind) for name, kind in _LEDGER_FIELDS.items()
            ):
                raise RevisionStoreIntegrityError(
                    f"{path}: quarantine line is not an object with fields {sorted(_LEDGER_FIELDS)}"
                )
            rows.append(row)
        return rows

    def _is_quarantined(
        self, source: str, station: str, run_ts_ns: int, base: str, sha: str
    ) -> bool:
        return any(
            r["sha256"] == sha
            and r["station"] == station
            and r["run_ts_ns"] == run_ts_ns
            and r["base_product"] == base
            for r in self._read_quarantine(source)
        )

    def _append_quarantine(
        self,
        source: str,
        station: str,
        run_ts_ns: int,
        base: str,
        sha: str,
        deviation_f: float,
    ) -> None:
        row = {
            "base_product": base,
            "deviation_f": deviation_f,
            "quarantined_at_ns": self._clock.timestamp_ns(),
            "run_ts_ns": run_ts_ns,
            "sha256": sha,
            "station": station,
        }
        path = self._quarantine_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
