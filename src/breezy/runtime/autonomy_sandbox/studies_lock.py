"""The in-process studies-lock helper (AUT-1 WP5 stage 3, S3-R13, S3-R38).

A unit that holds ``breezy-studies.lock`` for its whole run takes it itself, rather than through
``flock -w`` in front of the wrapper, so the lock wait does not age the seam B bus snapshot taken
in ``ExecStartPre`` (S3-R14). Reusable by AUT-6's ``IN_PROCESS_STUDIES_LOCK_UNITS``.

The lock file is never created here: the unit's own ``touch`` pre line makes it, and the wrapper
re-binds that same inode into the sandbox (``run_mounts``). The helper opens it
``O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK`` (the last so a swapped-in FIFO cannot block
the open), checks the open file with ``fstat`` (a regular file, owned by the euid, ``st_nlink ==
1``) and polls ``flock(LOCK_EX | LOCK_NB)``. The returned fd is close-on-exec and is never passed
to a child process; the caller keeps it open for the run and closes it at the end. Error codes
carry no path. Stdlib only (the package contract).
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

__all__ = [
    "StudiesLockError",
    "StudiesLockMissing",
    "StudiesLockRefused",
    "StudiesLockTimeout",
    "acquire_studies_lock",
]

_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_LOCK_BUSY: Final = (errno.EWOULDBLOCK, errno.EAGAIN)


class StudiesLockError(Exception):
    """The studies lock could not be taken. ``code`` is the stderr reason and never a path."""

    code: str = "studies_lock"

    def __init__(self) -> None:
        super().__init__(self.code)


class StudiesLockMissing(StudiesLockError):
    """The lock file does not exist. It is never created here."""

    code = "studies_lock_missing"


class StudiesLockRefused(StudiesLockError):
    """The path is a symlink, not a regular file, not owned by the euid or has another link."""

    code = "studies_lock_refused"


class StudiesLockTimeout(StudiesLockError):
    """Another process held the lock for the whole wait."""

    code = "studies_lock_timeout"


def _open_checked(path: Path) -> int:
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise StudiesLockMissing from None
        raise StudiesLockRefused from None  # ELOOP (symlink), EACCES, ENXIO ...
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1:
            raise StudiesLockRefused
    except BaseException:
        os.close(fd)
        raise
    return fd


def acquire_studies_lock(
    path: Path,
    *,
    wait_s: float,
    poll_s: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Take ``LOCK_EX`` on ``path`` within ``wait_s`` seconds and return the held fd.

    Raises ``StudiesLockMissing`` (ENOENT, nothing created), ``StudiesLockRefused`` (symlink,
    non-regular, foreign owner, ``st_nlink != 1``) or ``StudiesLockTimeout``. The lock is tried
    once even when ``wait_s`` is 0. No fd outlives a failed attempt.
    """
    fd = _open_checked(path)
    deadline = monotonic() + wait_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError as exc:
                if exc.errno not in _LOCK_BUSY:
                    raise StudiesLockRefused from None
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise StudiesLockTimeout
            sleep(min(poll_s, remaining))
    except BaseException:
        os.close(fd)
        raise
