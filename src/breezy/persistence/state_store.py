"""`FileStateStore` -- the durable :class:`~breezy.ingest.gate.StateStore` that
backs the settlement gate's ``ua_trap_blocked`` latch and every other
cross-restart trading-safety fact.

Why not the native Nautilus ``Cache``
--------------------------------------
``Cache`` requires Redis, and mid-session Redis loss fails OPEN silently:
``Cache.add`` writes memory-first and fire-and-forgets the Redis write
(``cache/cache.pyx:1704-1708``), ``Cache.get`` never reads the database at all
(``cache.pyx:2853``), and a killed Redis makes ``add()`` return in ~5.4e-5s
with no exception. A safety gate whose durable half can silently stop being
durable is worse than no persistence at all -- it *looks* persisted. That
decision is settled elsewhere; this module is the replacement.

Locking is BLOCKING, not ``LOCK_NB``
-------------------------------------
The kernel releases an ``flock`` unconditionally on process exit, including
``SIGKILL`` -- there is no OS-level way for a hard-killed predecessor to hold
a lock forever. So a BLOCKING acquisition at startup can never wedge a
restart: the new process simply waits (at most) for the crashed one's file
descriptor table to be torn down, which happens synchronously as part of
process exit. ``LOCK_NB`` would be actively wrong here -- it would fail
startup against a predecessor's not-yet-released descriptor even though that
descriptor is guaranteed to be released within microseconds, turning an
ordinary restart race into a spurious hard failure. The lock is acquired
once, in :meth:`FileStateStore.__init__`, held for the process's lifetime,
and released in :meth:`FileStateStore.close`.

A second, in-process guard exists alongside ``flock`` for a hazard ``flock``
cannot cover: two :class:`FileStateStore` instances opened on the SAME path
in the SAME process would deadlock each other forever, because a blocking
``flock`` on one descriptor cannot be released by an unrelated blocking
acquisition on a second descriptor in the same process -- there is no
external actor left to release it. :data:`_OPEN_PATHS` fails this case fast,
as :class:`ConcurrentStateStoreError`, instead of hanging the process.

A ``threading.RLock`` guards every in-process access in addition to
``flock``. ``flock`` is cross-process; the ``RLock`` covers the one
documented in-process hazard this project has: ``Future.add_done_callback``
firing its callback on ``MainThread`` or a tokio worker thread, i.e. a
callback that touches the store from a thread other than the one that
constructed it. ``RLock`` (not a plain ``Lock``) so a callback that
re-enters the store from the same thread that already holds it does not
deadlock itself.

Durability sequence
--------------------
Every :meth:`~FileStateStore.set` rewrites the WHOLE map, in this order:

1. Serialize the whole map as JSON.
2. Write it to ``<path>.tmp`` in the SAME directory (so the final
   ``os.replace`` is same-filesystem and therefore atomic).
3. ``flush()`` the buffered write (hands it from Python's userspace buffer to
   the kernel).
4. ``os.fsync(fd)`` the temp file (hands it from the kernel's page cache to
   the storage device).
5. ``os.replace(tmp, path)`` (atomically publishes the new version).
6. ``os.fsync`` the CONTAINING DIRECTORY's file descriptor (on most POSIX
   filesystems, the rename itself is not guaranteed durable until the
   directory entry is synced too).

A whole-file rewrite is correct at this scale -- Breezy's durable state is a
handful of small per-site and global entries, on the order of ~600 KB/year of
churn. A log-structured store would trade this module's simplicity for a
compaction problem this data volume does not justify.

Per-value CRC32, not one whole-file checksum
----------------------------------------------
This is load-bearing, not decorative, and the reason is specific to how
:mod:`breezy.ingest.gate` uses this store. The gate deliberately treats a
corrupt SITE entry as blocking only that one site (``gate.py:558-585``), but
a corrupt GLOBAL entry (which holds ``ua_trap_blocked``) as an ALL-site halt
(``gate.py:601-625``) -- two different blast radii for two different failure
severities, by design. A single whole-file checksum collapses that
distinction: one flipped bit anywhere in the file would force treating EVERY
key, site and global alike, as equally corrupt, which is either a
false all-site halt (if the corrupt byte was actually confined to one site's
harmless field) or -- far worse -- a silent full read failure that gets
handled the same way regardless of which key it was, defeating the isolation
``gate.py`` depends on. A CRC32 computed and stored PER VALUE means a
corrupted byte inside one key's payload is detected and reported for that key
alone; every other key -- including the security-critical global entry --
remains readable exactly as if nothing had happened to its neighbour.

Corruption never decodes to a wrong value
--------------------------------------------
A key whose stored CRC32 does not match its decoded bytes raises
:class:`StateStoreCorruptError` from :meth:`~FileStateStore.get` for THAT KEY
-- it never falls through to returning the corrupted bytes, and it never
takes down every other key's read. A whole-file parse failure (the JSON
itself is not well-formed) is treated as corrupting every key, because there
is no per-key boundary left to isolate once the container format itself has
failed -- this is the one case per-value CRC32 cannot help with, since it
protects VALUES, not the JSON syntax connecting them.
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import os
import stat
import threading
import weakref
import zlib
from pathlib import Path
from typing import Any, Final, TypedDict

from breezy.persistence.catalog import (
    FilesystemProbe,
    WriterLockFilesystemError,
    assert_writer_lock_filesystem_supported,
    probe_filesystem,
)
from breezy.persistence.filelock import (
    FileLockError,
    FileLockSymlinkError,
    acquire_flock,
    open_lock_fd,
    release_flock,
)

__all__ = [
    "ConcurrentStateStoreError",
    "FileStateStore",
    "StateStoreCorruptError",
    "StateStoreError",
    "StateStoreLockError",
    "StateStorePathError",
    # Re-exported verbatim from `breezy.persistence.catalog`, not redefined --
    # `assert_state_store_durable` raises it directly (see its docstring), so
    # a caller catching it must be able to import the type from here too.
    "WriterLockFilesystemError",
    "assert_state_store_durable",
]

_LOCK_SUFFIX: Final[str] = ".lock"
_TMP_SUFFIX: Final[str] = ".tmp"

#: Key written by `assert_state_store_durable`'s canary round-trip. Namespaced
#: so it can never collide with a real `gate:`/`productidx:` key, and includes
#: the pid so two processes racing the same durability check leave separate
#: canaries rather than clobbering each other's in-flight probe.
_CANARY_KEY_PREFIX: Final[str] = "__breezy_state_store_durability_canary__"


class StateStoreError(RuntimeError):
    """Base class for every failure `FileStateStore` and `assert_state_store_durable` raise."""


class StateStoreCorruptError(StateStoreError):
    """Raised when a stored value fails its CRC32 check, or the container JSON
    itself cannot be parsed.

    Never raised in place of returning a wrong value -- `get()` either returns
    the bytes that were actually written, or raises this, never a silently
    decoded mismatch.
    """


class StateStoreLockError(StateStoreError):
    """Raised when the durable lock or the durability sequence itself fails:
    the lock could not be acquired or held, or a write could not be made
    durable (`ENOSPC`, a read-only mount, ...). Covers every environmental
    failure that is not a path-safety refusal.
    """


class ConcurrentStateStoreError(StateStoreLockError):
    """Raised when a second `FileStateStore` is constructed on the SAME path
    within the SAME process.

    This is not the cross-process case -- that is resolved by blocking on the
    `flock` itself, correctly, per the module docstring. Two instances in one
    process are different: a blocking `flock` taken on a second descriptor in
    the SAME process can never be released by anything, because there is no
    external actor left to release the first one. Left unguarded, that is not
    a slow path, it is a permanent hang. This is raised immediately, before
    the blocking acquisition is attempted, so the failure is loud instead of
    silent.
    """


class StateStorePathError(StateStoreError, ValueError):
    """Raised when `path`, or its companion lock file, is a symlink.

    A `ValueError` subclass so a caller validating configuration generically
    still catches it, matching `breezy.persistence.catalog.CatalogPathError`'s
    reasoning for the same choice.
    """


class _Record(TypedDict):
    """One key's on-disk representation: base64 payload plus its own CRC32."""

    data: str
    crc32: int


# path -> True, guarded by `_REGISTRY_LOCK`. Tracks every currently-open
# `FileStateStore` in THIS process by resolved path, so a second construction
# on the same path fails fast (`ConcurrentStateStoreError`) instead of
# deadlocking forever on its own blocking `flock` -- see the module docstring.
_OPEN_PATHS: Final[dict[Path, bool]] = {}
_REGISTRY_LOCK: Final[threading.Lock] = threading.Lock()


def _claim_path(path: Path) -> None:
    with _REGISTRY_LOCK:
        if path in _OPEN_PATHS:
            raise ConcurrentStateStoreError(
                f"a FileStateStore is already open on {path} in this process; a "
                "second blocking flock acquisition on the same path in the same "
                "process can never be released and would hang forever. Reuse "
                "the existing instance, or close() it first."
            )
        _OPEN_PATHS[path] = True


def _release_path(path: Path) -> None:
    with _REGISTRY_LOCK:
        _OPEN_PATHS.pop(path, None)


def _require_real_directory(directory: Path) -> None:
    """Refuse a state-store directory that is not a REAL directory, verified
    with `os.lstat` (which, unlike every path predicate used to derive
    `directory`, does NOT follow a symlink).

    Mirrors `breezy.persistence.catalog._require_real_directory` exactly --
    same hazard, same fix, same discipline -- but is deliberately duplicated
    here rather than imported: that function is a private name, and importing
    it would couple this module to catalog's internals through something not
    part of its public contract.

    `Path.mkdir(exist_ok=True)` catches `FileExistsError` and falls back to
    `self.is_dir()`, which DOES follow a symlink: a link planted at
    `directory` -- before `mkdir` ever runs, or in the window between `mkdir`
    returning and this check -- is reported as "already exists and is a
    directory", and every subsequent write lands in the link's target with no
    exception and no log. For `state_store.py` this is worse than for the
    catalog: a `FileStateStore` is opened once and written through for the
    whole process lifetime, so a once-at-startup check alone leaves the
    entire session exposed, and the value being redirected can be the
    `ua_trap_blocked` halt latch itself. That is why this is called BOTH at
    the end of `__init__` (after `mkdir`) AND at the top of every
    `_persist()`, inside the in-process lock that already guards every
    `get`/`set` -- narrowing the exposure from "once per process lifetime" to
    "immediately before each write".

    Raises
    ------
    StateStorePathError
        If `directory` cannot be `lstat`-ed, or exists but is not a real
        directory.
    """
    try:
        status = os.lstat(directory)
    except OSError as exc:
        raise StateStorePathError(
            f"the state-store directory {directory} could not be verified as "
            f"a real directory ({exc}); refusing to store durable "
            "trading-safety state through a path whose identity on disk is "
            "unknown"
        ) from exc

    if not stat.S_ISDIR(status.st_mode):
        raise StateStorePathError(
            f"state-store directory {directory} is not a real directory: "
            f"`lstat` (which does not follow links) reports "
            f"{stat.filemode(status.st_mode)}. A symlink here would silently "
            "redirect every write -- including the ua_trap_blocked halt "
            "latch -- to a directory of someone else's choosing, and "
            "`mkdir(exist_ok=True)` cannot detect it because its `is_dir()` "
            "fallback follows the link"
        )


class FileStateStore:
    """A durable, `flock`-and-`fsync`-backed :class:`~breezy.ingest.gate.StateStore`.

    Structurally satisfies the `StateStore` `Protocol` (`get`/`set`); see the
    module docstring for the locking, durability-sequence and per-value-CRC32
    design this class implements.

    Parameters
    ----------
    path : Path
        The JSON state file. Its parent directory is created if missing. Must
        not itself be a symlink.
    fsync : bool
        Default `True`. `False` skips the `os.fsync` calls in the durability
        sequence while keeping `flush()` and `os.replace()` -- exists ONLY so
        the durability sequence's individual steps can be exercised in tests;
        production code must never construct with `fsync=False`.

    Raises
    ------
    StateStorePathError
        If `path`, or its companion lock file (or a directory above either),
        is a symlink.
    ConcurrentStateStoreError
        If a `FileStateStore` is already open on this path in this process.
    StateStoreLockError
        If the lock cannot be acquired or held for any other reason, or the
        existing state file cannot be read for a reason other than
        corruption (e.g. permissions).
    StateStoreCorruptError
        If the existing state file exists but is not well-formed JSON.
    """

    def __init__(self, path: Path, *, fsync: bool = True) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_name(self._path.name + _LOCK_SUFFIX)
        self._fsync = fsync
        self._rlock = threading.RLock()
        self._closed = False

        self._require_not_a_symlink(self._path)

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StateStoreLockError(
                f"could not create the parent directory of {self._path}: {exc}"
            ) from exc

        # Re-verified on every `_persist()` too -- see `_require_real_directory`.
        _require_real_directory(self._path.parent)

        _claim_path(self._path)
        try:
            try:
                self._lock_fd = open_lock_fd(self._lock_path)
            except FileLockSymlinkError as exc:
                raise StateStorePathError(
                    f"refusing to follow a symlink at or above lock path "
                    f"{self._lock_path}; a lock taken on a link's target does "
                    f"not exclude another holder of {self._path}"
                ) from exc
            except FileLockError as exc:
                raise StateStoreLockError(
                    f"could not open lock file {self._lock_path}: {exc}"
                ) from exc

            try:
                try:
                    acquire_flock(self._lock_fd, blocking=True)
                except FileLockError as exc:
                    raise StateStoreLockError(
                        f"could not acquire the durable-state lock for {self._path}: {exc}"
                    ) from exc

                self._records, self._corrupt = self._load()
            except BaseException:
                os.close(self._lock_fd)
                raise
        except BaseException:
            _release_path(self._path)
            raise

        self._install_fork_guard()

    # -- construction helpers --------------------------------------------

    def _install_fork_guard(self) -> None:
        """Guard against a `fork()`ed child's `close()` releasing THIS
        process's `flock`.

        POSIX `flock` is associated with the OPEN FILE DESCRIPTION, not the
        process: a `fork()`ed child inherits a duplicate fd on the SAME
        lock, and an explicit `LOCK_UN` issued through ANY duplicate fd
        releases the lock for every holder immediately -- unlike a plain
        `close()`, which only releases it once every duplicate fd is closed.
        `close()` calls `release_flock` (`LOCK_UN`), so an unguarded child
        that inherits this store and calls `close()` on it -- e.g. a
        `multiprocessing` fork-start-method worker tearing itself down --
        would silently break this process's single-writer exclusivity, with
        no exception anywhere.

        `os.register_at_fork(after_in_child=...)` runs in the child
        immediately as part of `os.fork()` itself, before any of the
        child's own code executes, and marks `_closed = True` on the
        child's copy. Because `close()` early-returns once `_closed` is set,
        the child's `close()` becomes a no-op: it never reaches
        `release_flock` or `os.close` on the inherited fd, so the true
        holder (whichever process does NOT fork away) keeps its lock
        intact. The inherited fd is simply leaked in the child until that
        process exits, which is the correct trade -- an ordinary `close()`
        (including the kernel's implicit one at process exit) only releases
        the lock once every duplicate fd referring to the same open file
        description is closed, so as long as the true holder's own fd stays
        open, the child exiting does not disturb it.

        A `weakref` to `self` is captured, not `self` directly:
        `os.register_at_fork` hooks are never unregistered, so a strong
        reference here would keep every `FileStateStore` ever constructed
        alive for the remaining life of the process.
        """
        weak_self = weakref.ref(self)

        def _invalidate_in_child() -> None:
            inst = weak_self()
            if inst is not None:
                inst._closed = True

        os.register_at_fork(after_in_child=_invalidate_in_child)

    def _require_not_a_symlink(self, path: Path) -> None:
        if path.is_symlink():
            raise StateStorePathError(
                f"{path} is a symlink; refusing to store durable trading-safety "
                "state through a link, whose target is not this call's to decide"
            )

    def _load(self) -> tuple[dict[str, _Record], set[str]]:
        try:
            fd = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}, set()
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise StateStorePathError(
                    f"{self._path} is a symlink; refusing to read durable "
                    "trading-safety state through a link"
                ) from exc
            raise StateStoreLockError(f"could not open {self._path} for reading: {exc}") from exc

        with os.fdopen(fd, "rb") as handle:
            raw = handle.read()

        return self._parse(raw)

    def _parse(self, raw: bytes) -> tuple[dict[str, _Record], set[str]]:
        if not raw:
            return {}, set()

        try:
            parsed: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StateStoreCorruptError(
                f"state file {self._path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise StateStoreCorruptError(
                f"state file {self._path} does not contain a JSON object at its top level"
            )

        records: dict[str, _Record] = {}
        corrupt: set[str] = set()
        for key, entry in parsed.items():
            if not isinstance(key, str):
                continue
            verified = self._verify_entry(entry)
            if verified is None:
                corrupt.add(key)
            else:
                records[key] = verified
        return records, corrupt

    @staticmethod
    def _verify_entry(entry: Any) -> _Record | None:
        try:
            data_b64 = entry["data"]
            stored_crc = entry["crc32"]
            if not isinstance(data_b64, str) or not isinstance(stored_crc, int):
                return None
            value = base64.b64decode(data_b64, validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error):
            return None

        if zlib.crc32(value) != stored_crc:
            return None
        return {"data": data_b64, "crc32": stored_crc}

    # -- StateStore protocol ----------------------------------------------

    def get(self, key: str) -> bytes | None:
        with self._rlock:
            self._require_open()
            if key in self._corrupt:
                raise StateStoreCorruptError(
                    f"stored value for key {key!r} in {self._path} failed its "
                    "CRC32 check; refusing to decode it as though it were valid"
                )
            record = self._records.get(key)
            if record is None:
                return None
            return base64.b64decode(record["data"])

    def set(self, key: str, value: bytes) -> None:
        with self._rlock:
            self._require_open()
            record: _Record = {
                "data": base64.b64encode(value).decode("ascii"),
                "crc32": zlib.crc32(value),
            }
            new_records = dict(self._records)
            new_records[key] = record
            self._persist(new_records)
            self._records = new_records
            self._corrupt.discard(key)

    # -- durability ---------------------------------------------------------

    def _persist(self, records: dict[str, _Record]) -> None:
        payload = json.dumps(records, sort_keys=True).encode("utf-8")
        tmp_path = self._path.with_name(self._path.name + _TMP_SUFFIX)
        directory = self._path.parent

        # Re-verified on every write, not just once at `__init__`: this
        # store is opened once and written through for the whole process
        # lifetime (unlike the catalog's per-write writer lock), so a
        # once-at-startup check alone would leave the entire session exposed
        # to a directory swapped for a symlink after construction. `set()`
        # already holds `self._rlock` for the whole of this call, which is
        # this store's in-process critical section (the `flock` itself is
        # acquired once, at construction, and held for the process's
        # lifetime -- see the module docstring).
        _require_real_directory(directory)

        try:
            fd = os.open(
                tmp_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise StateStorePathError(
                    f"refusing to write through symlinked temp path {tmp_path}"
                ) from exc
            raise StateStoreLockError(
                f"could not open {tmp_path} for a durable write: {exc}"
            ) from exc

        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                if self._fsync:
                    os.fsync(handle.fileno())

            os.replace(tmp_path, self._path)

            if self._fsync:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except OSError as exc:
            raise StateStoreLockError(
                f"durable write to {self._path} failed ({exc}); the in-memory "
                "update was not committed"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    # -- lifecycle ------------------------------------------------------

    def close(self) -> None:
        """Release the lock and mark this instance closed. Idempotent."""
        with self._rlock:
            if self._closed:
                return
            try:
                release_flock(self._lock_fd)
            finally:
                os.close(self._lock_fd)
                self._closed = True
                _release_path(self._path)

    def is_lock_held(self) -> bool:
        """`True` from construction until `close()`. The lock is acquired once,
        at construction, and held for the whole of that span -- never
        re-acquired lazily mid-session.
        """
        with self._rlock:
            return not self._closed

    @property
    def path(self) -> Path:
        return self._path

    def _require_open(self) -> None:
        if self._closed:
            raise StateStoreError(f"{self._path} is closed; no further get/set is permitted")


def assert_state_store_durable(store: object) -> None:
    """Prove `store` provides Breezy's durable-state guarantee, or raise.

    A weak version of this check -- "is it a `FileStateStore`", "does the
    path exist", "is the directory writable" -- silently reopens the exact
    hole the old `Cache`-based assertion closed: all three of those pass on
    `tmpfs`, where the `flock`+`fsync` discipline being certified is
    meaningless (an in-memory filesystem has no persistence to lose). So this
    proves three things directly against the LIVE object, mirroring
    `breezy.persistence.catalog.assert_writer_lock_filesystem_supported`'s
    reasoning for the writer lock:

    (a) The backing filesystem genuinely supports the `flock`+`fsync`
        discipline -- reusing `probe_filesystem` /
        `assert_writer_lock_filesystem_supported`, which already solved
        exactly this problem for the catalog's writer lock.
    (b) The lock was acquired AT STARTUP (`FileStateStore.__init__` blocks
        until it holds it) and is still held now, not merely "will be
        acquired the first time someone happens to call `set()`".
    (c) A canary write, followed immediately by a read-back through the SAME
        instance, actually round-trips right now -- proving the durability
        sequence executes end to end, not just that its methods exist.

    Raises
    ------
    StateStoreError
        If `store` is not a `FileStateStore` backed by a real path.
    WriterLockFilesystemError
        If the backing filesystem cannot be trusted for `flock` (network
        filesystem, or undeterminable type).
    StateStoreLockError
        If the store's lock is not currently held.
    StateStoreCorruptError
        If the canary write does not round-trip.
    """
    path = getattr(store, "path", None)
    if not isinstance(store, FileStateStore) or not isinstance(path, Path):
        raise StateStoreError(
            f"{store!r} does not provide Breezy's durable-state guarantee "
            "(flock + fsync + per-value CRC32); an in-memory or otherwise "
            "non-durable StateStore must never back the settlement gate's "
            "ua_trap_blocked latch"
        )

    probe: FilesystemProbe = probe_filesystem(path)
    assert_writer_lock_filesystem_supported(probe)

    if not store.is_lock_held():
        raise StateStoreLockError(
            f"{store!r} does not currently hold its startup lock; the lock "
            "must be acquired once at construction and held for the process "
            "lifetime, never discovered mid-session"
        )

    canary_key = f"{_CANARY_KEY_PREFIX}{os.getpid()}"
    canary_value = os.urandom(16)
    store.set(canary_key, canary_value)
    round_tripped = store.get(canary_key)
    if round_tripped != canary_value:
        raise StateStoreCorruptError(
            f"canary write to {store!r} did not round-trip (got {round_tripped!r}); "
            "refusing to certify this store as durable"
        )
