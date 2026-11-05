"""Read-only, snapshot-memoized view of an archive cache.

``ArchiveCache`` re-parses a source's whole ``coverage.json`` on every read, which
is right for a writer that must see its own and other processes' commits but
costs ~0.5 s per read on a 100k-entry manifest. Offline readers (the feature
builder) never write, so they take each source's manifest once and keep it.

``archive_cache.py`` is byte-frozen; this subclass only overrides the read-side
manifest load and refuses every write path. The snapshot is taken lazily at the
first access of a source and is NOT refreshed: commits made by a concurrent
writer after that first access are invisible to this instance.
"""

from __future__ import annotations

from pathlib import Path

from breezy.persistence.archive_cache import (
    ArchiveCache,
    ArchiveCacheError,
    ArchiveRequest,
    CoverageEntry,
)

__all__ = ["ReadOnlyArchiveCache", "ReadOnlyCacheWriteError"]


class ReadOnlyCacheWriteError(ArchiveCacheError, RuntimeError):
    """Raised when a write path is invoked on a read-only cache."""


class _NoClock:
    def timestamp_ns(self) -> int:
        return 0


def _refuse_fetch(_request: ArchiveRequest) -> bytes:
    raise ReadOnlyCacheWriteError("a read-only archive cache never fetches")


class ReadOnlyArchiveCache(ArchiveCache):
    """``ArchiveCache`` that reads each source manifest once and refuses writes."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, fetch=_refuse_fetch, clock=_NoClock())
        self._snapshots: dict[str, dict[str, CoverageEntry]] = {}

    def _load_source(self, source: str) -> dict[str, CoverageEntry]:
        snapshot = self._snapshots.get(source)
        if snapshot is None:
            snapshot = super()._load_source(source)
            self._snapshots[source] = snapshot
        return snapshot

    def get_or_fetch(self, request: ArchiveRequest) -> bytes:
        raise ReadOnlyCacheWriteError("get_or_fetch is a write path; use read()")

    def _commit_miss(self, request: ArchiveRequest, body: bytes) -> None:
        raise ReadOnlyCacheWriteError("a read-only archive cache never commits")

    def _acquire_lock(self, lock_path: Path) -> int:
        raise ReadOnlyCacheWriteError("a read-only archive cache never takes the coverage lock")
