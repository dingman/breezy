"""Durable on-disk IEM archive cache. Manifest is truth; writes are atomic.

No HTTP client, no hostname, no URL: ``fetch`` is an injected callable that
returns a body or raises. Coverage is the manifest, never the directory.
"""

from __future__ import annotations

import csv
import datetime as dt
import errno
import fcntl
import hashlib
import io
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.persistence.archive_catalog import assert_archive_base_disjoint
from breezy.persistence.archive_layout import BACKED_UP_ARCHIVE_DATASET_DIR

__all__ = [
    "IEM_ASOS_1MIN_SOURCE",
    "MANIFEST_VERSION",
    "ArchiveCache",
    "ArchiveCacheConcurrentWriterError",
    "ArchiveCacheDigestError",
    "ArchiveCacheError",
    "ArchiveCacheManifestError",
    "ArchiveCacheMissingPayloadError",
    "ArchiveCachePathError",
    "ArchiveRequest",
    "CoverageEntry",
    "assert_cache_root_disjoint_from_backup",
    "cache_key",
    "canonical_request_bytes",
    "count_rows",
    "fsync_directory",
    "iem_asos_1min_request",
]

MANIFEST_VERSION: Final[int] = 1
IEM_ASOS_1MIN_SOURCE: Final[str] = "iem-asos-1min"
_IEM_ASOS_1MIN_PRODUCT: Final[str] = "asos-1min"
_MANIFEST_NAME: Final[str] = "coverage.json"
_LOCK_NAME: Final[str] = "coverage.json.lock"
_SOURCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9-]+\Z")
_STATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z0-9]+\Z")
_SYMLINKED_LOCK_ERRNOS: Final[frozenset[int]] = frozenset({errno.ELOOP, errno.EMLINK})


class _NanosecondClock(Protocol):
    def timestamp_ns(self) -> int: ...


class ArchiveCacheError(Exception):
    """Base for every archive-cache refusal."""


class ArchiveCachePathError(ArchiveCacheError, ValueError):
    """Raised when a cache path is not safe to write through."""


class ArchiveCacheConcurrentWriterError(ArchiveCacheError, RuntimeError):
    """Raised when another process holds the coverage lock. Blocking is not offered."""


class ArchiveCacheDigestError(ArchiveCacheError):
    """Raised when a payload's sha256 does not match the manifest entry."""


class ArchiveCacheManifestError(ArchiveCacheError):
    """Raised when the coverage manifest is malformed, unknown-version, or corrupt."""


class ArchiveCacheMissingPayloadError(ArchiveCacheError):
    """Raised when a manifest entry has no payload file."""


@dataclass(frozen=True, slots=True)
class ArchiveRequest:
    """Identity of one archive window. The cache key hashes every field."""

    source: str
    station: str
    product: str
    window_start: int
    window_end: int
    model: str | None

    def __post_init__(self) -> None:
        if not _SOURCE_PATTERN.fullmatch(self.source):
            raise ValueError(f"source must match [a-z0-9-], was {self.source!r}")
        if not _STATION_PATTERN.fullmatch(self.station):
            raise ValueError(f"station must match [A-Z0-9], was {self.station!r}")
        if not self.product or not isinstance(self.product, str) or not self.product.strip():
            raise ValueError("product must be a non-empty string")
        if isinstance(self.window_start, bool) or not isinstance(self.window_start, int):
            raise TypeError("window_start must be an int of UNIX nanoseconds")
        if isinstance(self.window_end, bool) or not isinstance(self.window_end, int):
            raise TypeError("window_end must be an int of UNIX nanoseconds")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be greater than window_start")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise ValueError("model must be None or a non-empty string")

    def cache_key(self) -> str:
        return cache_key(self)


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    """One manifested payload. ``from_dict`` is explicit: missing keys raise."""

    cache_key: str
    station: str
    product: str
    window_start: int
    window_end: int
    rows: int
    bytes: int
    sha256: str
    fetched_at_ns: int
    model: str | None
    manifest_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "station": self.station,
            "product": self.product,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "rows": self.rows,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "fetched_at_ns": self.fetched_at_ns,
            "model": self.model,
            "manifest_version": self.manifest_version,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> CoverageEntry:
        return cls(**{name: values[name] for name in cls.__dataclass_fields__})


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_request_bytes(request: ArchiveRequest) -> bytes:
    return _canonical_json(
        {
            "model": request.model,
            "product": request.product,
            "source": request.source,
            "station": request.station,
            "window_end": request.window_end,
            "window_start": request.window_start,
        }
    )


def cache_key(request: ArchiveRequest) -> str:
    return hashlib.sha256(canonical_request_bytes(request)).hexdigest()


def count_rows(csv_bytes: bytes) -> int:
    """Count CSV data rows by dropping empties and the header; never invent rows."""
    if not csv_bytes.strip():
        return 0
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8")))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return 0
    if not _STATION_PATTERN.fullmatch(rows[0][0].strip()):
        rows = rows[1:]
    return len(rows)


def iem_asos_1min_request(station: str, year: int) -> ArchiveRequest:
    if isinstance(year, bool) or not isinstance(year, int):
        raise TypeError("year must be an int")
    start = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
    end = dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC)
    return ArchiveRequest(
        source=IEM_ASOS_1MIN_SOURCE,
        station=station,
        product=_IEM_ASOS_1MIN_PRODUCT,
        window_start=int(start.timestamp()) * 1_000_000_000,
        window_end=int(end.timestamp()) * 1_000_000_000,
        model=None,
    )


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def assert_cache_root_disjoint_from_backup(root: Path) -> None:
    try:
        assert_archive_base_disjoint(
            archive_base=root,
            settlement_base=BACKED_UP_ARCHIVE_DATASET_DIR,
        )
    except ValueError as exc:
        raise ArchiveCachePathError(str(exc)) from exc


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fsync_directory(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class ArchiveCache:
    """Hit/miss archive cache. Construction does no I/O besides path checks."""

    def __init__(
        self,
        root: Path,
        fetch: Callable[[ArchiveRequest], bytes],
        clock: _NanosecondClock,
    ) -> None:
        self._root = Path(root)
        self._fetch = fetch
        self._clock = clock
        self._loaded: dict[str, dict[str, CoverageEntry]] = {}
        assert_cache_root_disjoint_from_backup(self._root)
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise ArchiveCachePathError(
                f"refusing to use a symlinked or non-directory cache root {self._root}"
            )

    def covered(self) -> frozenset[str]:
        return frozenset().union(*self._loaded.values()) if self._loaded else frozenset()

    def missing(self, request: ArchiveRequest) -> bool:
        return request.cache_key() not in self._load_source(request.source)

    def read(self, request: ArchiveRequest) -> bytes:
        entry = self._entry_for(request)
        if entry is None:
            raise ArchiveCacheMissingPayloadError(
                f"no manifest entry for {request.cache_key()}"
            )
        self._require_matching_window(request, entry)
        return self._read_payload(request, entry)

    def get_or_fetch(self, request: ArchiveRequest) -> bytes:
        entry = self._entry_for(request)
        if entry is not None:
            self._require_matching_window(request, entry)
            return self._read_payload(request, entry)
        body = self._fetch(request)
        self._commit_miss(request, body)
        return body

    def _payload_path(self, request: ArchiveRequest) -> Path:
        return self._root / request.source / f"{request.cache_key()}.csv"

    def _manifest_path(self, source: str) -> Path:
        return self._root / source / _MANIFEST_NAME

    def _lock_path(self, source: str) -> Path:
        return self._root / source / _LOCK_NAME

    def _load_source(self, source: str) -> dict[str, CoverageEntry]:
        entries = self._read_manifest(self._manifest_path(source))
        self._loaded[source] = entries
        return entries

    def _entry_for(self, request: ArchiveRequest) -> CoverageEntry | None:
        return self._load_source(request.source).get(request.cache_key())

    def _require_matching_window(self, request: ArchiveRequest, entry: CoverageEntry) -> None:
        if entry.window_start != request.window_start or entry.window_end != request.window_end:
            raise ArchiveCacheManifestError(
                f"manifest window for {entry.cache_key} does not match the request; "
                "refusing to treat a matched key as a hit"
            )

    def _read_payload(self, request: ArchiveRequest, entry: CoverageEntry) -> bytes:
        path = self._payload_path(request)
        if not path.is_file() or path.is_symlink():
            raise ArchiveCacheMissingPayloadError(
                f"manifest entry {entry.cache_key} has no payload at {path}"
            )
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != entry.sha256:
            raise ArchiveCacheDigestError(
                f"payload digest mismatch for {entry.cache_key}: "
                f"manifest {entry.sha256}, disk {digest}"
            )
        return body

    def _read_manifest(self, path: Path) -> dict[str, CoverageEntry]:
        if not path.exists():
            return {}
        try:
            payload: Any = json.loads(path.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveCacheManifestError(f"{path}: not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ArchiveCacheManifestError(f"{path}: manifest must be a JSON object")
        version = payload.get("manifest_version")
        if version != MANIFEST_VERSION:
            raise ArchiveCacheManifestError(
                f"{path}: unknown manifest_version {version!r}; refusing to migrate"
            )
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, dict):
            raise ArchiveCacheManifestError(f"{path}: entries must be a JSON object")
        entries: dict[str, CoverageEntry] = {}
        for key, value in raw_entries.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ArchiveCacheManifestError(f"{path}: entries must map strings to objects")
            try:
                entry = CoverageEntry.from_dict(value)
            except KeyError as exc:
                raise ArchiveCacheManifestError(f"{path}: entry {key} missing {exc}") from exc
            if entry.cache_key != key:
                raise ArchiveCacheManifestError(
                    f"{path}: entry key {key} does not match cache_key {entry.cache_key}"
                )
            if entry.manifest_version != MANIFEST_VERSION:
                raise ArchiveCacheManifestError(
                    f"{path}: unknown per-entry manifest_version {entry.manifest_version}"
                )
            entries[key] = entry
        return entries

    def _encode_manifest(self, entries: dict[str, CoverageEntry]) -> bytes:
        return _canonical_json(
            {
                "entries": {key: entry.to_dict() for key, entry in entries.items()},
                "manifest_version": MANIFEST_VERSION,
            }
        )

    def _acquire_lock(self, lock_path: Path) -> int:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
        except OSError as exc:
            if exc.errno in _SYMLINKED_LOCK_ERRNOS:
                raise ArchiveCachePathError(
                    f"refusing to follow a symlink at or above the lock path {lock_path}"
                ) from exc
            raise ArchiveCachePathError(
                f"could not open the coverage lock {lock_path}: {exc}"
            ) from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise ArchiveCacheConcurrentWriterError(
                f"another process holds the coverage lock {lock_path}; "
                "blocking is deliberately not offered"
            ) from exc
        return fd

    def _commit_miss(self, request: ArchiveRequest, body: bytes) -> None:
        fd = self._acquire_lock(self._lock_path(request.source))
        try:
            entries = self._read_manifest(self._manifest_path(request.source))
            existing = entries.get(request.cache_key())
            if existing is not None:
                self._loaded[request.source] = entries
                self._require_matching_window(request, existing)
                return
            _atomic_write(self._payload_path(request), body)
            entry = CoverageEntry(
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
            entries[request.cache_key()] = entry
            _atomic_write(self._manifest_path(request.source), self._encode_manifest(entries))
            self._loaded[request.source] = entries
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
