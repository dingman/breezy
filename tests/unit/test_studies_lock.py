"""AUT-1 WP5 stage 3 (S3-R13, S3-R38): the in-process studies-lock helper.

Every case locks a scratch file under ``tmp_path``. A unit test never takes the real host studies
lock (``%t/breezy-studies.lock``): the helper takes its path as an argument and no test names it.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from breezy.runtime.autonomy_sandbox import studies_lock
from breezy.runtime.autonomy_sandbox.studies_lock import (
    StudiesLockError,
    StudiesLockMissing,
    StudiesLockRefused,
    StudiesLockTimeout,
    acquire_studies_lock,
)


class Clock:
    """A fake monotonic clock whose ``sleep`` advances it; ``on_sleep`` runs after each sleep."""

    def __init__(self, on_sleep: Callable[[int], None] | None = None) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


def _lock_file(tmp_path: Path) -> Path:
    path = tmp_path / "breezy-test.lock"
    path.touch(mode=0o600)
    return path


def _acquire(path: Path, clock: Clock, *, wait_s: float = 600, poll_s: float = 0.5) -> int:
    return acquire_studies_lock(
        path, wait_s=wait_s, poll_s=poll_s, monotonic=clock.monotonic, sleep=clock.sleep
    )


@contextmanager
def _held(path: Path) -> Iterator[int]:
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield fd
    finally:
        os.close(fd)


def _open_fds() -> set[int]:
    return {int(name) for name in os.listdir("/proc/self/fd")}


def test_lock_acquired_alone_returns_a_held_exclusive_fd(tmp_path: Path) -> None:
    path = _lock_file(tmp_path)
    fd = _acquire(path, Clock())
    try:
        other = os.open(path, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError) as blocked:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert blocked.value.errno == errno.EWOULDBLOCK
        finally:
            os.close(other)
    finally:
        os.close(fd)


def test_lock_fd_is_cloexec_and_read_only(tmp_path: Path) -> None:
    """S3-R38: the fd is never passed to a child process."""
    fd = _acquire(_lock_file(tmp_path), Clock())
    try:
        assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        assert os.get_inheritable(fd) is False
        assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    finally:
        os.close(fd)


def test_lock_never_creates(tmp_path: Path) -> None:
    """MUTATION M-CREAT: ``O_CREAT`` would make the missing file and succeed."""
    path = tmp_path / "absent.lock"
    with pytest.raises(StudiesLockMissing):
        _acquire(path, Clock())
    assert not path.exists() and list(tmp_path.iterdir()) == []


def test_missing_lock_does_not_wait(tmp_path: Path) -> None:
    clock = Clock()
    with pytest.raises(StudiesLockMissing):
        _acquire(tmp_path / "absent.lock", clock)
    assert clock.sleeps == []


def test_lock_refuses_symlink(tmp_path: Path) -> None:
    """MUTATION M-FOLLOW: dropping ``O_NOFOLLOW`` would follow the link and lock its target."""
    target = _lock_file(tmp_path)
    link = tmp_path / "link.lock"
    link.symlink_to(target)
    before = _open_fds()
    with pytest.raises(StudiesLockRefused):
        _acquire(link, Clock())
    assert _open_fds() == before


def test_lock_refuses_nlink_not_one(tmp_path: Path) -> None:
    """MUTATION (S3-R38): dropping the ``st_nlink == 1`` check."""
    path = _lock_file(tmp_path)
    os.link(path, tmp_path / "second-name.lock")
    before = _open_fds()
    with pytest.raises(StudiesLockRefused):
        _acquire(path, Clock())
    assert _open_fds() == before


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_lock_refuses_a_non_regular_file(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "odd.lock"
    if kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(StudiesLockRefused):
        _acquire(path, Clock(), wait_s=0)


def test_lock_refuses_a_file_owned_by_someone_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _lock_file(tmp_path)
    someone_else = os.geteuid() + 1
    monkeypatch.setattr(
        "breezy.runtime.autonomy_sandbox.studies_lock.os.geteuid", lambda: someone_else
    )
    with pytest.raises(StudiesLockRefused):
        _acquire(path, Clock())


def test_lock_times_out_after_wait(tmp_path: Path) -> None:
    path = _lock_file(tmp_path)
    clock = Clock()
    before = _open_fds()
    with _held(path), pytest.raises(StudiesLockTimeout):
        _acquire(path, clock, wait_s=600, poll_s=0.5)
    assert 600 <= clock.now - 1000.0 <= 600.5
    assert all(0 < step <= 0.5 for step in clock.sleeps)
    assert _open_fds() == before  # the failed attempt leaked no fd


def test_lock_wait_zero_tries_exactly_once(tmp_path: Path) -> None:
    path = _lock_file(tmp_path)
    clock = Clock()
    with _held(path), pytest.raises(StudiesLockTimeout):
        _acquire(path, clock, wait_s=0)
    assert clock.sleeps == []
    fd = _acquire(path, clock, wait_s=0)
    os.close(fd)


def test_lock_is_taken_when_the_holder_releases_during_the_wait(tmp_path: Path) -> None:
    path = _lock_file(tmp_path)
    holder = os.open(path, os.O_RDONLY)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(count: int) -> None:
        if count == 3:
            os.close(holder)

    clock = Clock(release)
    fd = _acquire(path, clock, wait_s=600)
    os.close(fd)
    assert len(clock.sleeps) == 3


def test_a_lock_error_is_one_family_and_the_codes_are_pathless(tmp_path: Path) -> None:
    for exc_type in (StudiesLockMissing, StudiesLockRefused, StudiesLockTimeout):
        assert issubclass(exc_type, StudiesLockError)
    with pytest.raises(StudiesLockMissing) as caught:
        _acquire(tmp_path / "absent.lock", Clock())
    assert str(tmp_path) not in str(caught.value) and "/" not in caught.value.code


def test_lock_file_is_left_untouched(tmp_path: Path) -> None:
    path = _lock_file(tmp_path)
    before = os.stat(path)
    fd = _acquire(path, Clock())
    os.close(fd)
    after = os.stat(path)
    assert (after.st_ino, after.st_size, stat.S_IMODE(after.st_mode)) == (
        before.st_ino,
        before.st_size,
        stat.S_IMODE(before.st_mode),
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_studies_lock_sys_modules_closure() -> None:
    """S3-R37: importing the helper pulls in no adapter and no HTTP client."""
    code = (
        "import sys\n"
        "import breezy.runtime.autonomy_sandbox.studies_lock\n"
        "bad = sorted(m for m in sys.modules if m.startswith('breezy.adapters')"
        " or m.split('.')[0] in ('httpx', 'requests', 'aiohttp', 'urllib3', 'nautilus_trader'))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(studies_lock.__file__).parents[3])}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
