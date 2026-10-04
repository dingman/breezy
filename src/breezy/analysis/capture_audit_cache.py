"""AUT-1 WP5 stage 2b, W3: the audit's per-log reducer cache and its directory (design S2-R6).

A log that ended (its ``TradingNode`` DISPOSED line was seen) is immutable, so its reducer outputs
are cached under ``AUDIT_CACHE_DIR``, keyed by ``(name, size, mtime_ns, head-sha)`` plus the codec
version. The cache is an optimisation, never evidence: an unreadable or undecodable entry is a miss
and the log is scanned again; a log still being written is never cached (its key moves with every
byte).

``write_scan_cache`` is the audit's only cache write; ``ensure_cache_dir`` creates the directory the
exec-store snapshot also uses. Entries are JSON through a closed registry of dataclasses (never
pickle), written ``0600`` by atomic replace.

Trust (S2-R29). The cache is UNAUTHENTICATED: it is trusted as same-uid data, like every other file
under the data root. Each entry embeds its own key and a read compares it, so an entry copied or
renamed under another key is a miss. The key also covers the reducer code (S2-R28): a sha256 over
the source bytes of the node-log reducer modules, so a changed reducer never reads an old result.
"""

import datetime as dt
import functools
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import LogMarkers, ReplayResult
from breezy.analysis.capture_audit_model import AUDIT_CACHE_DIR
from breezy.analysis.capture_audit_replay import BootDayReplay
from breezy.analysis.capture_node_log import NodeLogScan
from breezy.analysis.capture_node_log_decisions import (
    DecisionLine,
    OrderFilledLine,
    TakeInputs,
    WriterFailureLine,
)
from breezy.analysis.capture_node_log_io import UnparseableLine
from breezy.analysis.capture_node_log_markers import (
    CaptureEpochStartLine,
    CaptureRefusedLine,
    FqVectorCompleteLine,
    NbpCycleMissedLine,
    NbpPublishedLine,
    OrderDeniedLine,
    OrderSubmittedLine,
)
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadRefused,
    ensure_dir,
    open_root,
    read_once_at,
    replace_atomic,
    walk_dirs,
)

__all__ = [
    "CACHE_PREFIX",
    "CODEC_VERSION",
    "LogResult",
    "cache_dir_parts",
    "encode_result",
    "ensure_cache_dir",
    "log_key",
    "read_scan_cache",
    "reducer_source_hash",
    "write_scan_cache",
]

#: The cache entry format. Any change to a cached type or the codec bumps it, so an old entry is a
#: miss rather than a wrong answer.
CODEC_VERSION: Final[str] = "scan-cache/2"
CACHE_PREFIX: Final[str] = "scan_"
CACHE_FILE_MODE: Final[int] = 0o600
_HEAD_BYTES: Final[int] = 65_536
_MAX_FILE_BYTES: Final[int] = 64 * 1024 * 1024
_KEY_RE: Final[re.Pattern[str]] = re.compile(r"\A[0-9a-f]{64}\Z")

_CACHE_TYPES: Final[Mapping[str, type]] = MappingProxyType(
    {
        cls.__name__: cls
        for cls in (
            NodeLogScan,
            DecisionLine,
            TakeInputs,
            OrderFilledLine,
            WriterFailureLine,
            UnparseableLine,
            ReplayResult,
            BootDayReplay,
            LogMarkers,
            CaptureRefusedLine,
            OrderSubmittedLine,
            OrderDeniedLine,
            NbpPublishedLine,
            FqVectorCompleteLine,
            NbpCycleMissedLine,
            CaptureEpochStartLine,
        )
    }
)


def _enc(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return {"$b": value.hex()}
    if isinstance(value, dt.date):
        return {"$d": value.isoformat()}
    if isinstance(value, tuple | list):
        return {"$t": [_enc(v) for v in value]}
    if isinstance(value, frozenset):
        return {"$f": sorted((_enc(v) for v in value), key=repr)}
    if isinstance(value, Mapping):
        return {"$m": [[_enc(k), _enc(v)] for k, v in value.items()]}
    if is_dataclass(value) and not isinstance(value, type) and type(value).__name__ in _CACHE_TYPES:
        return {
            "$c": type(value).__name__,
            "f": {f.name: _enc(getattr(value, f.name)) for f in fields(value)},
        }
    raise TypeError(f"not cacheable: {type(value).__name__}")


def _dec(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "$b" in value:
        return bytes.fromhex(value["$b"])
    if "$d" in value:
        return dt.date.fromisoformat(value["$d"])
    if "$t" in value:
        return tuple(_dec(v) for v in value["$t"])
    if "$f" in value:
        return frozenset(_dec(v) for v in value["$f"])
    if "$m" in value:
        return {_dec(k): _dec(v) for k, v in value["$m"]}
    return _CACHE_TYPES[value["$c"]](**{k: _dec(v) for k, v in value["f"].items()})


@dataclass(frozen=True, slots=True)
class LogResult:
    """One log's reducer outputs: the scan summary and the per ``(instance_id, UTC day)`` replay
    and marker results (the sinks partition by the UTC day of each line)."""

    scan: NodeLogScan
    replay: Mapping[tuple[str, dt.date], ReplayResult]
    markers: Mapping[tuple[str, dt.date], LogMarkers]


def encode_result(result: LogResult, key: str) -> bytes:
    def keyed(items: Mapping[tuple[str, dt.date], Any]) -> list[Any]:
        return [[iid, day.isoformat(), _enc(value)] for (iid, day), value in items.items()]

    body = {
        "v": CODEC_VERSION,
        "key": key,
        "scan": _enc(result.scan),
        "replay": keyed(result.replay),
        "markers": keyed(result.markers),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _decode_result(raw: bytes, key: str) -> LogResult | None:
    """The cached result, or ``None`` for anything not exactly this codec's output for ``key`` (a
    miss)."""
    try:
        body = json.loads(raw)
        if body.get("v") != CODEC_VERSION or body.get("key") != key:
            return None
        scan = _dec(body["scan"])

        def keyed(items: list[Any]) -> dict[tuple[str, dt.date], Any]:
            return {(iid, dt.date.fromisoformat(day)): _dec(v) for iid, day, v in items}

        replay, markers = keyed(body["replay"]), keyed(body["markers"])
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError):
        return None
    ok = (
        isinstance(scan, NodeLogScan)
        and all(isinstance(v, ReplayResult) for v in replay.values())
        and all(isinstance(v, LogMarkers) for v in markers.values())
    )
    return LogResult(scan, replay, markers) if ok else None


_REDUCER_GLOBS: Final[tuple[str, ...]] = (
    "capture_node_log*.py",
    "capture_audit_replay.py",
    "capture_audit_log_markers.py",
    "capture_audit_cache.py",
)


def reducer_source_hash_of(source_dir: Path) -> str:
    """sha256 over the (name, bytes) of every reducer module in ``source_dir``, in name order."""
    names = sorted({p.name for pattern in _REDUCER_GLOBS for p in source_dir.glob(pattern)})
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256((source_dir / name).read_bytes()).digest())
    return digest.hexdigest()


@functools.cache
def reducer_source_hash() -> str:
    """The reducer modules' source hash, computed once per process (S2-R28)."""
    return reducer_source_hash_of(Path(__file__).resolve().parent)


def log_key(path: Path) -> str:
    """``sha256(codec | reducer-source | name | size | mtime_ns | sha256(first 64 KiB))``: a log
    that grew, was touched or was replaced, or a reducer that changed, is a different key."""
    stat, name = path.stat(), path.name
    with path.open("rb") as handle:
        head = hashlib.sha256(handle.read(_HEAD_BYTES)).hexdigest()
    text = (
        f"{CODEC_VERSION}|{reducer_source_hash()}|{name}|{stat.st_size}|{stat.st_mtime_ns}|{head}"
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_dir_parts() -> tuple[str, ...]:
    return tuple(AUDIT_CACHE_DIR.split("/"))


def ensure_cache_dir(data_root: Path) -> None:
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, cache_dir_parts()))
    finally:
        os.close(rootfd)


def write_scan_cache(data_root: Path, key: str, body: bytes) -> None:
    """Write one per-log reducer cache entry below ``AUDIT_CACHE_DIR`` (atomic replace)."""
    if _KEY_RE.fullmatch(key) is None:
        raise ValueError("cache key must be 64 lowercase hex characters")
    ensure_cache_dir(data_root)
    path = data_root.joinpath(*cache_dir_parts(), f"{CACHE_PREFIX}{key}.json")
    replace_atomic(path, body, root=data_root, mode=CACHE_FILE_MODE)


def read_scan_cache(data_root: Path, key: str) -> LogResult | None:
    """The cached result for ``key``, or ``None``: every refusal, unreadable or undecodable entry is
    a miss (S2-R30), because the cache is an optimisation, never evidence."""
    try:
        rootfd = open_root(data_root)
    except SingleReadRefused:
        return None
    try:
        dirfd = walk_dirs(rootfd, cache_dir_parts())
    except SingleReadRefused:
        return None
    finally:
        os.close(rootfd)
    try:
        raw = read_once_at(
            dirfd, f"{CACHE_PREFIX}{key}.json", max_bytes=_MAX_FILE_BYTES, policy=ReadPolicy.STRICT
        )
    except SingleReadRefused:
        return None
    finally:
        os.close(dirfd)
    return _decode_result(raw, key)
