"""The shared WAL snapshot helper (plan r5 AC-3; erratum E-8 as amended by E-7e(b), E-8a).

A wrapped unit never opens a live WAL-mode database in place (under bwrap the in-place
``mode=ro`` open fails without sidecars, and ``immutable=1`` loses committed WAL rows). It
takes a **snapshot**: the database and its ``-wal`` (and ``-journal``) are copied, never
``-shm``, into a private ``snap.*`` directory of the caller's 0700 cache directory, the copy
is recovered and checked, and it is opened read-only.

**The live store is only ever read.** Every source open is ``O_RDONLY|O_NOFOLLOW`` relative to
a nofollow-walked directory fd; nothing is created, truncated, checkpointed or connected to
in the source directory. Only the cache copy is opened read-write (to recover it). The sole
lock taken on a live file is the E-8 intent flock, on the ``<db>.intent.lock`` file opened
``O_RDONLY`` (a ``flock`` needs no write access), and only when ``take_flock`` is true.

Steps (each pinned by a test in ``tests/unit/test_wal_snapshot.py``):

1. Walk the cache directory without following symlinks; ``fstat`` its fd and its parent
   (directory, the caller's euid, mode exactly 0700) or ``CACHE_DIR_MODE``; take
   ``flock(LOCK_EX|LOCK_NB)`` on an ``O_RDONLY|O_DIRECTORY`` fd of it (contention is
   ``CACHE_BUSY``); sweep ``snap.*`` leftovers without following symlinks.
2. ``take_flock=True`` only (the AUT-5 16:45 pass): ``lock_path`` must equal
   ``<db>.intent.lock``; open it ``O_RDONLY|O_CLOEXEC|O_NOFOLLOW`` (a missing file is
   ``LOCK_FILE_MISSING`` and is never created); ``flock(LOCK_EX|LOCK_NB)`` up to
   ``flock_attempts`` times, ``flock_retry_s`` apart, then ``LOCK_HELD``. A ``release_deadline_ns``
   is **required** here: the caller derives it from the schedule constants; this module holds no
   launch-time literal.
3. Fingerprint db, ``-wal``, ``-journal`` (present, inode, size, ``mtime_ns``, and sha256 of
   db bytes 0-99, ``-wal`` bytes 0-31 and its last 4096, ``-journal`` bytes 0-511). If any file
   was modified within ``QUIESCENCE_NS`` of the clock, wait that long and fingerprint again.
4. Copy db, ``-wal``, ``-journal`` in that order, fd-relative (``openat`` with ``O_EXCL``,
   0600) into ``snap.<token>`` (0700).
5. Re-fingerprint: a difference removes the copy and retries, up to ``copy_attempts``, then
   ``FINGERPRINT_UNSTABLE``. Check the deadline (``DEADLINE``), then release the intent flock.
6. Recover the copy read-write under the real cache path: ``PRAGMA quick_check`` must be
   ``ok`` (``QUICK_CHECK``), ``journal_mode=DELETE`` leaves a single file, no ``-wal``/``-shm``.
7. Yield ``WalSnapshot`` or ``SnapshotReadFailure``; an expected failure never raises.
   ``finally`` removes the snapshot directory and releases both flocks.

``advisory`` is false only when the intent flock was held from before the first fingerprint
through the last re-fingerprint. Stdlib only.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import io
import os
import pwd
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from breezy.runtime.autonomy_sandbox.binds import BindIntegrityError, walk_nofollow

EXEC_STORE_FILENAME: Final = "exec_polymarket_us.sqlite"
INTENT_LOCK_SUFFIX: Final = ".intent.lock"  # mirrors trade_supervisor.intent_lock_path
QUIESCENCE_NS: Final = 20_000_000
SNAP_PREFIX: Final = "snap."

_NS_PER_S: Final = 1_000_000_000
_SUFFIX: Final = {"db": "", "wal": "-wal", "journal": "-journal"}
_ROLES: Final = tuple(_SUFFIX)  # the copy order: db, -wal, -journal
_HEAD_BYTES: Final = {"db": 100, "wal": 32, "journal": 512}
_WAL_TAIL_BYTES: Final = 4096
_COPY_CHUNK: Final = 1 << 20
_PRIVATE_DIR_MODE: Final = 0o700
_PRIVATE_FILE_MODE: Final = 0o600
#: Read-only opens spell their flags inline (``os.O_RDONLY | ...``) so the AC6 scan sees
#: them as reads; only the cache copy's own creates are write sites.
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_CONTENDED: Final = frozenset({errno.EWOULDBLOCK, errno.EAGAIN})


class SnapshotFailureReason(StrEnum):
    """The exact set of expected failures (AC-3.8)."""

    CACHE_DIR_MODE = "cache_dir_mode"
    CACHE_BUSY = "cache_busy"
    LOCK_PATH_INVALID = "lock_path_invalid"
    LOCK_FILE_MISSING = "lock_file_missing"
    LOCK_HELD = "lock_held"
    LOCK_ERROR = "lock_error"
    SOURCE_INVALID = "source_invalid"
    FINGERPRINT_UNSTABLE = "fingerprint_unstable"
    COPY_ERROR = "copy_error"
    QUICK_CHECK = "quick_check"
    DEADLINE = "deadline"


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    role: str
    present: bool
    inode: int | None
    size: int | None
    mtime_ns: int | None
    head_sha256: str | None
    tail_sha256: str | None


@dataclass(frozen=True, slots=True)
class WalSnapshot:
    path: Path
    fingerprints: tuple[FileFingerprint, ...]
    took_flock: bool
    advisory: bool
    attempts: int
    taken_at_ns: int


@dataclass(frozen=True, slots=True)
class SnapshotReadFailure:
    reason: SnapshotFailureReason
    advisory: bool
    attempts: int


class _Fail(Exception):
    """An expected failure; ``wal_snapshot`` turns it into ``SnapshotReadFailure``."""

    def __init__(self, reason: SnapshotFailureReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class _Retry(Exception):
    """A source file changed under the copy: discard it and try again."""


@dataclass(frozen=True, slots=True)
class _Params:
    db_path: Path
    cache_dir: Path
    take_flock: bool
    lock_path: Path | None
    release_deadline_ns: int | None
    flock_attempts: int
    flock_retry_s: float
    copy_attempts: int
    clock_ns: Callable[[], int]
    sleep: Callable[[float], None]


class _Attempts:
    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0


class _Held:
    """An fd whose close releases its flock; ``release`` is idempotent."""

    __slots__ = ("fd",)

    def __init__(self, fd: int) -> None:
        self.fd = fd

    def release(self) -> None:
        fd, self.fd = self.fd, -1
        if fd >= 0:
            os.close(fd)


# --------------------------------------------------------------------------- paths


def _default_data_root() -> Path:
    """The passwd home's data root (never ``$HOME``: L-55)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "share" / "breezy"


def exec_store_paths(data_root: Path | None = None) -> tuple[Path, Path]:
    """``(db, intent lock)`` of the execution store under ``data_root`` (default: production)."""
    root = data_root if data_root is not None else _default_data_root()
    db = root / "state" / EXEC_STORE_FILENAME
    return db, db.with_name(db.name + INTENT_LOCK_SUFFIX)


# --------------------------------------------------------------------------- the source (read-only)


def _open_source(src_fd: int, name: str) -> int | None:
    """``name`` opened ``O_RDONLY|O_NOFOLLOW`` beside the store; ``None`` if it is absent."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=src_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise _Fail(SnapshotFailureReason.SOURCE_INVALID) from None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise _Fail(SnapshotFailureReason.SOURCE_INVALID)
    return fd


def _open_source_dir(stack: ExitStack, db_path: Path) -> int:
    try:
        walked = walk_nofollow(db_path.parent, kind="dir")
    except BindIntegrityError:
        raise _Fail(SnapshotFailureReason.SOURCE_INVALID) from None
    stack.callback(os.close, walked.fd)
    return walked.fd


def _digest(handle: io.FileIO, offset: int, length: int) -> str:
    handle.seek(offset)
    return hashlib.sha256(handle.read(length)).hexdigest()


def _fingerprint(src_fd: int, db_name: str, role: str) -> FileFingerprint:
    fd = _open_source(src_fd, db_name + _SUFFIX[role])
    if fd is None:
        if role == "db":
            raise _Fail(SnapshotFailureReason.SOURCE_INVALID)
        return FileFingerprint(role, False, None, None, None, None, None)
    try:
        st = os.fstat(fd)
        with open(fd, "rb", buffering=0, closefd=False) as handle:
            head = _digest(handle, 0, _HEAD_BYTES[role])
            tail = (
                _digest(handle, max(0, st.st_size - _WAL_TAIL_BYTES), _WAL_TAIL_BYTES)
                if role == "wal"
                else None
            )
    finally:
        os.close(fd)
    return FileFingerprint(role, True, st.st_ino, st.st_size, st.st_mtime_ns, head, tail)


def _fingerprints(src_fd: int, db_name: str) -> tuple[FileFingerprint, ...]:
    return tuple(_fingerprint(src_fd, db_name, role) for role in _ROLES)


def _is_recent(fingerprints: tuple[FileFingerprint, ...], params: _Params) -> bool:
    horizon = params.clock_ns() - QUIESCENCE_NS
    return any(fp.present and (fp.mtime_ns or 0) > horizon for fp in fingerprints)


# --------------------------------------------------------------------- the cache copy (read-write)


def _remove_tree(parent_fd: int, name: str) -> None:
    """Remove ``name`` under ``parent_fd``; a symlink is unlinked, never followed."""
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
    except FileNotFoundError:
        return
    except OSError:
        os.unlink(name, dir_fd=parent_fd)  # not a directory, or a symlink: drop the entry itself
        return
    try:
        for child in os.listdir(fd):
            _remove_tree(fd, child)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent_fd)


def _sweep(cache_fd: int) -> None:
    for name in os.listdir(cache_fd):
        if name.startswith(SNAP_PREFIX):
            _remove_tree(cache_fd, name)


def _check_private_dir(st: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(st.st_mode)
        or st.st_uid != os.geteuid()
        or stat.S_IMODE(st.st_mode) != _PRIVATE_DIR_MODE
    ):
        raise _Fail(SnapshotFailureReason.CACHE_DIR_MODE)


def _open_cache_dir(stack: ExitStack, cache_dir: Path) -> int:
    """Nofollow walk, ``fstat`` checks on the dir and its parent, then the cache flock."""
    try:
        parent = walk_nofollow(cache_dir.parent, kind="dir")
    except BindIntegrityError:
        raise _Fail(SnapshotFailureReason.CACHE_DIR_MODE) from None
    stack.callback(os.close, parent.fd)
    try:
        fd = os.open(
            cache_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent.fd,
        )
    except OSError:
        raise _Fail(SnapshotFailureReason.CACHE_DIR_MODE) from None
    stack.callback(os.close, fd)
    _check_private_dir(os.fstat(fd))
    _check_private_dir(parent.st)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        busy = exc.errno in _CONTENDED
        raise _Fail(
            SnapshotFailureReason.CACHE_BUSY if busy else SnapshotFailureReason.COPY_ERROR
        ) from None
    return fd


def _make_snap_dir(cache_fd: int) -> tuple[str, int]:
    name = SNAP_PREFIX + secrets.token_hex(8)
    os.mkdir(name, _PRIVATE_DIR_MODE, dir_fd=cache_fd)
    try:
        return name, os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=cache_fd
        )
    except OSError:
        os.rmdir(name, dir_fd=cache_fd)
        raise


def _create_copy(src: int, snap_fd: int, name: str, size: int) -> None:
    """Copy ``size`` bytes of ``src`` into a new 0600 file ``name`` (``O_EXCL``, fd-relative)."""
    dst = os.open(name, _CREATE_FLAGS, _PRIVATE_FILE_MODE, dir_fd=snap_fd)
    try:
        remaining = size
        while remaining > 0:
            chunk = os.read(src, min(_COPY_CHUNK, remaining))
            if not chunk:
                break  # the file shrank: the re-fingerprint will see it
            view = memoryview(chunk)
            while view:
                view = view[os.write(dst, view) :]
            remaining -= len(chunk)
    finally:
        os.close(dst)


def _copy_files(
    src_fd: int, snap_fd: int, db_name: str, fingerprints: tuple[FileFingerprint, ...]
) -> None:
    """Copy each present file, in fingerprint order (db, -wal, -journal); never ``-shm``."""
    for fp in fingerprints:
        if not fp.present:
            continue
        name = db_name + _SUFFIX[fp.role]
        src = _open_source(src_fd, name)
        if src is None:
            raise _Retry
        try:
            st = os.fstat(src)
            if st.st_ino != fp.inode:
                raise _Retry
            _create_copy(src, snap_fd, name, st.st_size)
        finally:
            os.close(src)


def _copy_attempt(
    stack: ExitStack,
    cache_fd: int,
    src_fd: int,
    db_name: str,
    first: tuple[FileFingerprint, ...],
) -> str | None:
    name, snap_fd = _make_snap_dir(cache_fd)
    stack.callback(_remove_tree, cache_fd, name)
    try:
        _copy_files(src_fd, snap_fd, db_name, first)
    except _Retry:
        _remove_tree(cache_fd, name)
        return None
    except OSError:
        raise _Fail(SnapshotFailureReason.COPY_ERROR) from None
    finally:
        os.close(snap_fd)
    return name


# --------------------------------------------------------------------------- the intent flock


def _check_deadline(params: _Params) -> None:
    deadline = params.release_deadline_ns
    if deadline is not None and params.clock_ns() >= deadline:
        raise _Fail(SnapshotFailureReason.DEADLINE)


def _acquire_intent_lock(stack: ExitStack, src_fd: int, db_name: str, params: _Params) -> _Held:
    name = db_name + INTENT_LOCK_SUFFIX
    if params.lock_path is None or Path(params.lock_path) != params.db_path.with_name(name):
        raise _Fail(SnapshotFailureReason.LOCK_PATH_INVALID)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=src_fd)
    except FileNotFoundError:
        raise _Fail(SnapshotFailureReason.LOCK_FILE_MISSING) from None
    except OSError as exc:
        symlink = exc.errno == errno.ELOOP
        raise _Fail(
            SnapshotFailureReason.LOCK_PATH_INVALID if symlink else SnapshotFailureReason.LOCK_ERROR
        ) from None
    held = _Held(fd)
    stack.callback(held.release)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise _Fail(SnapshotFailureReason.LOCK_PATH_INVALID)
    for attempt in range(1, params.flock_attempts + 1):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in _CONTENDED:
                raise _Fail(SnapshotFailureReason.LOCK_ERROR) from None
        else:
            return held
        if attempt < params.flock_attempts:
            params.sleep(params.flock_retry_s)
            _check_deadline(params)
    raise _Fail(SnapshotFailureReason.LOCK_HELD)


# --------------------------------------------------------------------------- the snapshot


def _stable_copy(
    stack: ExitStack,
    params: _Params,
    attempts: _Attempts,
    src_fd: int,
    cache_fd: int,
    db_name: str,
) -> tuple[str, tuple[FileFingerprint, ...]]:
    for attempt in range(1, params.copy_attempts + 1):
        attempts.count = attempt
        _check_deadline(params)
        first = _fingerprints(src_fd, db_name)
        if _is_recent(first, params):
            params.sleep(QUIESCENCE_NS / _NS_PER_S)
            _check_deadline(params)
            first = _fingerprints(src_fd, db_name)
        name = _copy_attempt(stack, cache_fd, src_fd, db_name, first)
        if name is None:
            continue
        if _fingerprints(src_fd, db_name) == first:
            return name, first
        _remove_tree(cache_fd, name)
    raise _Fail(SnapshotFailureReason.FINGERPRINT_UNSTABLE)


def _recover(cache_real: Path, snap_name: str, db_name: str) -> Path:
    """Open the copy read-write, check it, leave a single rollback-journal file."""
    path = cache_real / snap_name / db_name
    if not Path(os.path.realpath(path)).is_relative_to(cache_real):
        raise _Fail(SnapshotFailureReason.COPY_ERROR)
    try:
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise _Fail(SnapshotFailureReason.QUICK_CHECK)
            if conn.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
                raise _Fail(SnapshotFailureReason.QUICK_CHECK)
        finally:
            conn.close()
    except sqlite3.Error:
        raise _Fail(SnapshotFailureReason.QUICK_CHECK) from None
    if {db_name + "-wal", db_name + "-shm"} & set(os.listdir(path.parent)):
        raise _Fail(SnapshotFailureReason.COPY_ERROR)
    return path


def _run(stack: ExitStack, params: _Params, attempts: _Attempts) -> WalSnapshot:
    db_name = params.db_path.name
    src_fd = _open_source_dir(stack, params.db_path)
    cache_fd = _open_cache_dir(stack, params.cache_dir)
    _sweep(cache_fd)
    held = _acquire_intent_lock(stack, src_fd, db_name, params) if params.take_flock else None
    name, fingerprints = _stable_copy(stack, params, attempts, src_fd, cache_fd, db_name)
    _check_deadline(params)
    if held is not None:
        held.release()
    path = _recover(Path(os.path.realpath(params.cache_dir)), name, db_name)
    return WalSnapshot(
        path=path,
        fingerprints=fingerprints,
        took_flock=params.take_flock,
        advisory=not params.take_flock,
        attempts=attempts.count,
        taken_at_ns=params.clock_ns(),
    )


@contextmanager
def wal_snapshot(
    db_path: Path,
    *,
    cache_dir: Path,
    take_flock: bool,
    lock_path: Path | None,
    release_deadline_ns: int | None = None,
    flock_attempts: int = 3,
    flock_retry_s: float = 5.0,
    copy_attempts: int = 3,
    clock_ns: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[WalSnapshot | SnapshotReadFailure]:
    """Yield a recovered read-only-openable copy of ``db_path``, or why there is none."""
    if take_flock and release_deadline_ns is None:
        raise ValueError("take_flock=True requires release_deadline_ns")
    params = _Params(
        Path(db_path),
        Path(cache_dir),
        take_flock,
        None if lock_path is None else Path(lock_path),
        release_deadline_ns,
        flock_attempts,
        flock_retry_s,
        copy_attempts,
        clock_ns,
        sleep,
    )
    attempts = _Attempts()
    with ExitStack() as stack:
        outcome: WalSnapshot | SnapshotReadFailure
        try:
            outcome = _run(stack, params, attempts)
        except _Fail as fail:
            outcome = SnapshotReadFailure(fail.reason, not take_flock, attempts.count)
        except OSError:
            outcome = SnapshotReadFailure(
                SnapshotFailureReason.COPY_ERROR, not take_flock, attempts.count
            )
        yield outcome


@contextmanager
def exec_snapshot(
    *,
    cache_dir: Path,
    take_flock: bool,
    lock_path: Path | None = None,
    data_root: Path | None = None,
    **kwargs: Any,
) -> Iterator[WalSnapshot | SnapshotReadFailure]:
    """``wal_snapshot`` of the execution store (``take_flock=True`` derives the lock path)."""
    db, lock = exec_store_paths(data_root)
    chosen = lock_path if lock_path is not None else (lock if take_flock else None)
    with wal_snapshot(
        db,
        cache_dir=cache_dir,
        take_flock=take_flock,
        lock_path=chosen,
        **kwargs,
    ) as outcome:
        yield outcome


def connect_snapshot_readonly(snap: WalSnapshot) -> sqlite3.Connection:
    """The copy opened ``mode=ro`` with ``query_only=ON`` (it has no sidecars to need)."""
    conn = sqlite3.connect(f"file:{quote(str(snap.path))}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn
