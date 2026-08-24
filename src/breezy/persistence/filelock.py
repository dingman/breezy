"""Shared OS mechanics for an advisory `flock`-based file lock.

This module owns exactly the TOCTOU-sensitive core that both
`breezy.persistence.catalog`'s per-write writer lock and
`breezy.persistence.state_store`'s process-lifetime durable-store lock need,
and nothing else. Both callers wrap these primitives in their OWN exception
taxonomy via ``raise ... from`` -- this module raises only the three types
below, never a catalog- or state-store-specific error, so it stays reusable
without either caller's public exception hierarchy leaking into the other's.

What is extracted
------------------
* Opening the lock file with ``O_NOFOLLOW`` so a pre-planted symlink at (or a
  parent of) the lock path fails the open rather than silently redirecting
  the lock onto an inode of someone else's choosing. This is checked by the
  kernel as part of the ``open`` syscall itself, so there is no
  check-then-open window to race, and it covers a *dangling* symlink too --
  ``O_CREAT`` on a dangling link would otherwise create and lock the
  attacker-chosen path.
* Taking (and releasing) the `flock` itself, blocking or non-blocking.

What is NOT extracted (deliberately -- everything else is path-shaped, not
mechanism-shaped, and belongs to each caller):
* Deriving the lock path from a catalog root or a state-store path.
* How long the lock is held (`catalog.py` takes it for one write call;
  `state_store.py` takes it once at construction and holds it for the
  process lifetime).
* Directory- or root-level symlink and identity re-verification.
* Translating a failure into a caller-specific exception message.

Blocking vs. non-blocking
--------------------------
Both modes are supported because the two callers have opposite requirements.
`catalog.py`'s writer lock is non-blocking (`LOCK_NB`): a second writer must
fail at the door with `ConcurrentWriterError` rather than serialise, because
the read-modify-write verification it protects is not safe to interleave.
`state_store.py`'s lock is BLOCKING: the kernel releases `flock`
unconditionally on process exit, including `SIGKILL`, so a hard-killed
predecessor can never wedge a blocking waiter -- while `LOCK_NB` would fail
startup outright against a predecessor's not-yet-released descriptor. Neither
caller's choice belongs in this module; both are passed in as `blocking`.
"""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
from typing import Final

__all__ = [
    "FileLockContentionError",
    "FileLockError",
    "FileLockSymlinkError",
    "acquire_flock",
    "open_lock_fd",
    "release_flock",
]

# `open(..., O_NOFOLLOW)` on a symlink is ELOOP on Linux and EMLINK on the BSDs.
# Both are treated as a path-safety failure rather than an environment failure;
# either way the open is refused, so the only cost of the (vanishingly
# unlikely) EMLINK-from-`mkdir` overlap is a less precise message on an
# already-loud abort.
_SYMLINKED_LOCK_ERRNOS: Final[frozenset[int]] = frozenset({errno.ELOOP, errno.EMLINK})


class FileLockError(OSError):
    """Base for every failure raised by this module's OS mechanics.

    A subclass of `OSError` so a caller that only wants "something about
    opening or taking this lock failed" can catch broadly, exactly as the
    pre-extraction code caught a raw `OSError`. Callers translate this (and
    its subclasses) into their own public exception hierarchy via
    ``raise ... from exc`` -- this type is never raised across a module
    boundary as the caller-visible error.
    """


class FileLockSymlinkError(FileLockError):
    """Raised when the lock path, or a directory above it, is a symlink.

    Covers both `O_NOFOLLOW` rejecting the lock path itself and `mkdir`
    failing on a symlinked parent -- both are the same hazard (a lock taken
    on a link's target does not exclude another holder on the real path), so
    they are not distinguished further here.
    """


class FileLockContentionError(FileLockError):
    """Raised by a non-blocking `acquire_flock` when the lock is already held.

    Never raised by a blocking acquisition -- there, contention is resolved
    by waiting, not by failing.
    """


def open_lock_fd(lock_path: Path, *, mode: int = 0o644) -> int:
    """Open (creating if needed) `lock_path` for exclusive advisory locking.

    Creates every missing parent directory first (`parents=True,
    exist_ok=True`), then opens with `O_CREAT | O_RDWR | O_NOFOLLOW`. The
    returned descriptor is UNLOCKED -- call `acquire_flock` next.

    `O_NOFOLLOW` guards `lock_path` ITSELF, including a dangling symlink
    there (`O_CREAT` on a dangling link would otherwise create and lock the
    attacker-chosen path). It does NOT guard a parent directory that already
    resolves to a real directory through a symlink -- `Path.mkdir`'s
    `exist_ok=True` falls back to `is_dir()`, which follows links, exactly
    the aliasing hazard `catalog.py`'s `_require_real_directory` exists to
    close separately with `os.lstat`. Verifying the directory identity above
    the lock path is deliberately each caller's job, not this module's: it is
    path-shaped (which component, checked against which registry), not
    mechanism-shaped.

    Raises
    ------
    FileLockSymlinkError
        If `lock_path` itself is a symlink (resolving or dangling).
    FileLockError
        For every other `OSError` encountered creating a parent directory or
        opening the file -- including a *dangling* symlinked parent
        (`mkdir` raises `EEXIST`, not `ELOOP`/`EMLINK`, so that case is not
        classified as `FileLockSymlinkError`) and environmental failures
        (`EROFS`, `ENOSPC`, `EACCES`, `EISDIR`, `ENOTDIR`, ...).
    """
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, mode)
    except OSError as exc:
        if exc.errno in _SYMLINKED_LOCK_ERRNOS:
            raise FileLockSymlinkError(
                exc.errno,
                f"refusing to follow a symlink at or above lock path {lock_path}",
            ) from exc
        raise FileLockError(
            exc.errno,
            f"could not open lock path {lock_path}: {exc}",
        ) from exc


def acquire_flock(fd: int, *, blocking: bool) -> None:
    """Take an exclusive `flock` on `fd`.

    `blocking=True` waits for the lock indefinitely -- correct for a lock
    held for a process's lifetime, since the kernel guarantees release on
    exit (including `SIGKILL`), so no waiter can be wedged by a dead holder.
    `blocking=False` (`LOCK_NB`) fails immediately with
    `FileLockContentionError` -- correct for a lock re-taken on every write,
    where a caller needs to know it lost the race rather than wait for a
    verification window it cannot safely interleave with.

    Raises
    ------
    FileLockContentionError
        Only when `blocking=False` and the lock is already held. Matches the
        pre-extraction behaviour exactly: any `OSError` from a non-blocking
        `flock` attempt is treated as contention, not narrowed to a specific
        errno, since a non-blocking `LOCK_EX` has no other realistic failure
        mode on the platforms this project targets.
    FileLockError
        For any `OSError` from a *blocking* `flock` call (there is no
        contention outcome to distinguish -- a blocking call that raises has
        failed for an environmental reason instead).
    """
    op = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fd, op)
    except OSError as exc:
        if not blocking:
            raise FileLockContentionError(exc.errno, str(exc)) from exc
        raise FileLockError(exc.errno, str(exc)) from exc


def release_flock(fd: int) -> None:
    """Release the `flock` held on `fd`. Does not close `fd`."""
    fcntl.flock(fd, fcntl.LOCK_UN)
