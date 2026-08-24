"""Unit tests for `breezy.persistence.filelock` -- the shared OS lock mechanics
extracted from `breezy.persistence.catalog._writer_lock`.

Scope: opening the lock descriptor, symlink refusal via `O_NOFOLLOW`, and
blocking/non-blocking `flock` acquisition and release. Catalog- and
state-store-specific translation is exercised in their own test modules.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from breezy.persistence.filelock import (
    FileLockContentionError,
    FileLockError,
    FileLockSymlinkError,
    acquire_flock,
    open_lock_fd,
    release_flock,
)


def test_open_lock_fd_creates_missing_parent_directories(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "dir" / "lock"

    fd = open_lock_fd(lock_path)
    try:
        assert lock_path.is_file()
    finally:
        os.close(fd)


def test_open_lock_fd_refuses_a_symlinked_lock_path(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("")
    lock_path = tmp_path / "lock"
    lock_path.symlink_to(target)

    with pytest.raises(FileLockSymlinkError):
        open_lock_fd(lock_path)


def test_open_lock_fd_refuses_a_dangling_symlinked_lock_path(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    lock_path.symlink_to(tmp_path / "does-not-exist")

    with pytest.raises(FileLockSymlinkError):
        open_lock_fd(lock_path)

    assert not (tmp_path / "does-not-exist").exists()


def test_open_lock_fd_refuses_a_dangling_symlinked_parent_directory(tmp_path: Path) -> None:
    """`mkdir(parents=True, exist_ok=True)` raises `EEXIST` (not `ELOOP`) on a
    dangling symlinked parent, so this surfaces as `FileLockError`, not
    `FileLockSymlinkError` -- verifying a *resolving* symlinked parent is
    each caller's job (e.g. catalog.py's separate `_require_real_directory`),
    not this module's, per the docstring.
    """
    dangling_dir = tmp_path / "dangling"
    dangling_dir.symlink_to(tmp_path / "does-not-exist")

    with pytest.raises(FileLockError):
        open_lock_fd(dangling_dir / "lock")


def test_open_lock_fd_wraps_other_os_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = tmp_path / "lock"

    def explode(*args: object, **kwargs: object) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "open", explode)

    with pytest.raises(FileLockError) as excinfo:
        open_lock_fd(lock_path)

    assert not isinstance(excinfo.value, FileLockSymlinkError)


def test_acquire_flock_non_blocking_raises_on_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    holder_fd = open_lock_fd(lock_path)
    acquire_flock(holder_fd, blocking=False)

    contender_fd = os.open(lock_path, os.O_RDWR)
    try:
        with pytest.raises(FileLockContentionError):
            acquire_flock(contender_fd, blocking=False)
    finally:
        os.close(contender_fd)
        release_flock(holder_fd)
        os.close(holder_fd)


def test_acquire_flock_blocking_waits_for_release_rather_than_raising(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    holder_fd = open_lock_fd(lock_path)
    acquire_flock(holder_fd, blocking=False)

    waiter_fd = os.open(lock_path, os.O_RDWR)
    acquired = threading.Event()

    def wait_for_lock() -> None:
        acquire_flock(waiter_fd, blocking=True)
        acquired.set()

    waiter = threading.Thread(target=wait_for_lock)
    waiter.start()
    try:
        # Give the waiter a real chance to (wrongly) acquire immediately.
        assert not acquired.wait(timeout=0.2)

        release_flock(holder_fd)
        assert acquired.wait(timeout=5), "blocking acquire never unblocked after release"
    finally:
        waiter.join(timeout=5)
        release_flock(waiter_fd)
        os.close(waiter_fd)
        os.close(holder_fd)


def test_release_flock_allows_a_subsequent_non_blocking_acquire(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    fd_a = open_lock_fd(lock_path)
    acquire_flock(fd_a, blocking=False)
    release_flock(fd_a)

    fd_b = os.open(lock_path, os.O_RDWR)
    try:
        acquire_flock(fd_b, blocking=False)  # must not raise
    finally:
        release_flock(fd_b)
        os.close(fd_b)
        os.close(fd_a)


def test_a_sigkilled_blocking_holder_does_not_wedge_a_waiter(tmp_path: Path) -> None:
    """The kernel releases `flock` unconditionally on process exit, including
    `SIGKILL` -- the whole reason `state_store.py` may safely use a BLOCKING
    acquisition for a lock held across the process lifetime.
    """
    lock_path = tmp_path / "lock"
    script = f"""
import os
import time
from pathlib import Path
from breezy.persistence.filelock import open_lock_fd, acquire_flock

fd = open_lock_fd(Path({str(lock_path)!r}))
acquire_flock(fd, blocking=True)
time.sleep(30)
os._exit(0)
"""
    proc_holder = _spawn(tmp_path, script)
    # Wait until the lock file exists and is actually locked by polling a
    # non-blocking contender from this process.
    deadline = time.monotonic() + 5
    lock_path.touch(exist_ok=True)
    while time.monotonic() < deadline:
        probe_fd = os.open(lock_path, os.O_RDWR)
        try:
            acquire_flock(probe_fd, blocking=False)
            release_flock(probe_fd)
            os.close(probe_fd)
        except FileLockContentionError:
            os.close(probe_fd)
            break
        time.sleep(0.02)
    else:
        proc_holder.kill()
        pytest.fail("holder subprocess never took the lock")

    proc_holder.kill()
    proc_holder.wait(timeout=5)

    waiter_fd = os.open(lock_path, os.O_RDWR)
    try:
        acquire_flock(waiter_fd, blocking=True)  # must not hang
    finally:
        release_flock(waiter_fd)
        os.close(waiter_fd)


def _spawn(tmp_path: Path, script: str) -> object:
    import subprocess
    import sys

    script_path = tmp_path / "_holder.py"
    script_path.write_text(script)
    return subprocess.Popen([sys.executable, str(script_path)])
