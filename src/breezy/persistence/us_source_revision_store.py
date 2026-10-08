"""Append-only revision store for the F13 US-source raw payloads (H4, R17, R28, R32).

``ArchiveCache`` is unmodified and is used here ONLY as the write API: the
change detector is this module, which compares the fetched sha256 against the
digests of every stored raw revision for ``(source, station, run_ts, base)``.

* A payload whose digest is already stored appends nothing.
* A new digest is written as ``<base>-r<N>`` with ``N = 1 + max`` (``-r0`` is
  the first-seen revision and stays the timing anchor), through
  ``ArchiveCache(fetch=<closure returning the already-fetched bytes>)
  .get_or_fetch`` on a key verified ``missing()``. A run that appends many
  products opens :meth:`coverage_batch` (a subclass in this module — the
  ``archive_cache`` module stays byte-frozen) so ``coverage.json`` is not
  rewritten on every product; the per-product write is still ``get_or_fetch``.
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
import signal
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.persistence.archive_cache import (
    MANIFEST_VERSION,
    ArchiveCache,
    ArchiveRequest,
    CoverageEntry,
    _atomic_write,
    count_rows,
)
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
#: New payloads one coverage batch may commit before rewriting coverage.json.
#: One rewrite is O(entries); doing it on every product is O(n^2).
COVERAGE_FLUSH_EVERY: Final[int] = 200
#: Keys committed in a batch but not yet folded into coverage.json. Append-only,
#: so another process can see them before this one releases collector.lock.
_JOURNAL_NAME: Final[str] = "coverage.pending.jsonl"
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


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _manifest_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _arm_sigterm() -> Callable[[], None] | None:
    """Turn SIGTERM into SystemExit so a batch ``finally`` can flush.

    The default action kills the process before ``finally`` runs. Ignored
    SIGTERM stays ignored. Only the main thread can install a handler.
    """
    if threading.current_thread() is not threading.main_thread():
        return None
    previous = signal.getsignal(signal.SIGTERM)
    if previous == signal.SIG_IGN:
        return None

    def _handler(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _handler)

    def _restore() -> None:
        signal.signal(signal.SIGTERM, previous)

    return _restore


class _BatchedCoverageCache(ArchiveCache):
    """``ArchiveCache`` that can defer ``coverage.json`` rewrites.

    ``archive_cache.py`` is byte-frozen. Batching lives here and is used only by
    :class:`UsSourceRevisionStore`. Outside a batch every miss still rewrites the
    manifest immediately, via :meth:`ArchiveCache._commit_miss`.
    """

    def __init__(
        self,
        root: Path,
        fetch: Callable[[ArchiveRequest], bytes],
        clock: _NanosecondClock,
    ) -> None:
        super().__init__(root, fetch, clock)
        self._stamp: dict[str, tuple[int, int] | None] = {}
        self._journal_stamp: dict[str, tuple[int, int] | None] = {}
        self._dirty: dict[str, dict[str, CoverageEntry]] = {}
        self._batch_depth = 0

    @contextlib.contextmanager
    def coverage_batch(self) -> Iterator[None]:
        """Write each payload now; rewrite the manifest on a cadence and on the way out.

        Each new key is appended to ``coverage.pending.jsonl`` before the unit
        lock is released, so another process dedupes against it. The manifest is
        rewritten every ``COVERAGE_FLUSH_EVERY`` new keys, when this context
        exits, and when it is left by an exception or by SIGTERM (delivered as
        ``SystemExit`` so this ``finally`` runs). A flush drops any pending key
        whose file is missing or whose digest does not match, then removes the
        journal. A crash before that rewrite never leaves ``coverage.json``
        claiming bytes that are not on disk.
        """
        self._batch_depth += 1
        restore_sigterm = _arm_sigterm() if self._batch_depth == 1 else None
        try:
            yield
        finally:
            self._batch_depth -= 1
            try:
                if self._batch_depth == 0:
                    self.flush_coverage()
            finally:
                if restore_sigterm is not None:
                    restore_sigterm()

    def flush_coverage(self) -> None:
        """Fold pending journals into ``coverage.json``. No-op if nothing is pending."""
        for source in self._pending_sources():
            fd = self._acquire_lock(self._lock_path(source))
            try:
                self._flush_source(source)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _load_source(self, source: str) -> dict[str, CoverageEntry]:
        path = self._manifest_path(source)
        journal = self._journal_path(source)
        stamp = _manifest_stamp(path)
        journal_stamp = _manifest_stamp(journal)
        cached = self._loaded.get(source)
        # Outside a batch with no journal, the manifest file is truth on every
        # read. A journal (or an open batch) is ahead of that file.
        if (
            cached is not None
            and self._stamp.get(source) == stamp
            and self._journal_stamp.get(source) == journal_stamp
            and (self._batch_depth > 0 or journal_stamp is not None)
        ):
            return cached
        entries = self._read_manifest(path)
        for key, entry in self._read_journal(source).items():
            entries.setdefault(key, entry)
        self._loaded[source] = entries
        self._stamp[source] = stamp
        self._journal_stamp[source] = journal_stamp
        return entries

    def _commit_miss(self, request: ArchiveRequest, body: bytes) -> None:
        if self._batch_depth == 0:
            journal = self._journal_path(request.source)
            if journal.is_file() and not journal.is_symlink():
                fd = self._acquire_lock(self._lock_path(request.source))
                try:
                    self._flush_source(request.source)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
            super()._commit_miss(request, body)
            self._dirty.pop(request.source, None)
            self._stamp[request.source] = _manifest_stamp(self._manifest_path(request.source))
            self._journal_stamp[request.source] = _manifest_stamp(
                self._journal_path(request.source)
            )
            return
        fd = self._acquire_lock(self._lock_path(request.source))
        try:
            self._commit_batched(request, body)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _new_entry(self, request: ArchiveRequest, body: bytes) -> CoverageEntry:
        return CoverageEntry(
            cache_key=request.cache_key(),
            station=request.station,
            product=request.product,
            window_start=request.window_start,
            window_end=request.window_end,
            rows=count_rows(body),
            bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            fetched_at_ns=self._clock.timestamp_ns(),
            model=request.model,
            manifest_version=MANIFEST_VERSION,
        )

    def _journal_path(self, source: str) -> Path:
        return self._root / source / _JOURNAL_NAME

    def _pending_sources(self) -> list[str]:
        found = {source for source, dirty in self._dirty.items() if dirty}
        root = self._root
        if root.is_dir() and not root.is_symlink():
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir():
                    continue
                journal = child / _JOURNAL_NAME
                if journal.is_file() and not journal.is_symlink():
                    found.add(child.name)
        return sorted(found)

    def _read_journal(self, source: str) -> dict[str, CoverageEntry]:
        path = self._journal_path(source)
        if not path.is_file() or path.is_symlink():
            return {}
        found: dict[str, CoverageEntry] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            try:
                raw = json.loads(line)
                entry = CoverageEntry.from_dict(raw) if isinstance(raw, dict) else None
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if entry is not None and entry.cache_key:
                found[entry.cache_key] = entry
        return found

    def _append_journal_line(self, source: str, entry: CoverageEntry) -> None:
        """Durably record one key before the caller releases the unit lock."""
        path = self._journal_path(source)
        if path.is_symlink():
            raise RevisionStoreIntegrityError(f"refusing a symlinked coverage journal at {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        created = not path.exists()
        try:
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o644)
        except OSError as exc:
            if exc.errno in _SYMLINKED_LOCK_ERRNOS:
                raise RevisionStoreIntegrityError(
                    f"refusing a symlinked coverage journal at {path}"
                ) from exc
            raise
        line = (
            json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
        try:
            view = line
            while view:
                wrote = os.write(fd, view)
                if wrote <= 0:
                    raise OSError(f"short write to coverage journal {path}")
                view = view[wrote:]
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            _fsync_dir(path.parent)
        self._journal_stamp[source] = _manifest_stamp(path)

    def _unlink_journal(self, source: str) -> None:
        path = self._journal_path(source)
        if path.is_symlink():
            raise RevisionStoreIntegrityError(f"refusing a symlinked coverage journal at {path}")
        path.unlink(missing_ok=True)

    def _payload_matches(self, source: str, entry: CoverageEntry) -> bool:
        path = self._root / source / f"{entry.cache_key}.csv"
        if not path.is_file() or path.is_symlink():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == entry.sha256

    def _flush_source(self, source: str) -> None:
        """Publish pending keys whose files match. Caller holds the coverage lock.

        The on-disk manifest wins when it already has a key. A pending entry is
        dropped, not published, when the csv is missing or its digest differs.
        """
        pending = self._read_journal(source)
        pending.update(self._dirty.get(source) or {})
        path = self._manifest_path(source)
        base = self._read_manifest(path)
        published = dict(base)
        for key, entry in pending.items():
            if key in base:
                continue
            if self._payload_matches(source, entry):
                published[key] = entry
        if len(published) != len(base):
            _atomic_write(path, self._encode_manifest(published))
        self._unlink_journal(source)
        self._loaded[source] = published
        self._stamp[source] = _manifest_stamp(path)
        self._journal_stamp[source] = None
        self._dirty[source] = {}

    def _commit_batched(self, request: ArchiveRequest, body: bytes) -> None:
        """Payload and journal now, manifest later. Caller holds the coverage lock."""
        entries = self._load_source(request.source)
        existing = entries.get(request.cache_key())
        if existing is not None:
            self._require_matching_window(request, existing)
            return
        _atomic_write(self._payload_path(request), body)
        entry = self._new_entry(request, body)
        entries[request.cache_key()] = entry
        self._loaded[request.source] = entries
        dirty = self._dirty.setdefault(request.source, {})
        dirty[entry.cache_key] = entry
        self._append_journal_line(request.source, entry)
        if len(dirty) >= COVERAGE_FLUSH_EVERY:
            self._flush_source(request.source)


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
        self._cache = _BatchedCoverageCache(self._root, fetch=self._fetch_closure, clock=clock)
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

    @contextlib.contextmanager
    def coverage_batch(self) -> Iterator[None]:
        """Defer this store's ``coverage.json`` rewrite until the batch ends.

        Append, quarantine, refusal and dedupe semantics are unchanged. See
        :meth:`_BatchedCoverageCache.coverage_batch`.
        """
        with self._cache.coverage_batch():
            yield

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
