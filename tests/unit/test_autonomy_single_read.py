"""ARCH-0 seam 2b: ``single_read`` openat-based read and write contract (AC 7).

Every test runs as a normal uid. The mode-bit refusal never depends on uid (V30).
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    open_root,
    read_once_at,
    replace_atomic,
    walk_dirs,
    write_once,
)

TEMP_NAME_RE = re.compile(r"\A\.tmp\.[0-9a-f]{16}\Z")


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    data_root = tmp_path / "root"
    data_root.mkdir(mode=0o700)
    yield data_root
    for directory in [data_root, *data_root.rglob("*")]:
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)


def _read(directory: Path, name: str, **kwargs: Any) -> bytes:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        return read_once_at(fd, name, max_bytes=kwargs.pop("max_bytes", 1024), **kwargs)
    finally:
        os.close(fd)


def _reason(exc_info: pytest.ExceptionInfo[SingleReadRefused]) -> SingleReadReason:
    return exc_info.value.reason


# ---------------------------------------------------------------- open_root / walk_dirs


def test_open_root_refuses_symlinked_root(tmp_path: Path, root: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(SingleReadRefused) as exc_info:
        open_root(link)
    assert _reason(exc_info) is SingleReadReason.SYMLINK


def test_walk_refuses_symlinked_intermediate_dir(tmp_path: Path, root: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "b").mkdir(parents=True)
    (root / "a").symlink_to(elsewhere)
    rootfd = open_root(root)
    try:
        with pytest.raises(SingleReadRefused) as exc_info:
            walk_dirs(rootfd, ("a", "b"), create=False)
    finally:
        os.close(rootfd)
    assert _reason(exc_info) is SingleReadReason.SYMLINK


def test_walk_returns_fd_for_nested_directory_and_creates_on_request(root: Path) -> None:
    rootfd = open_root(root)
    try:
        with pytest.raises(SingleReadRefused) as exc_info:
            walk_dirs(rootfd, ("x", "y"), create=False)
        assert _reason(exc_info) is SingleReadReason.NOT_FOUND
        fd = walk_dirs(rootfd, ("x", "y"), create=True)
        try:
            assert stat.S_ISDIR(os.fstat(fd).st_mode)
        finally:
            os.close(fd)
    finally:
        os.close(rootfd)
    assert stat.S_IMODE((root / "x" / "y").stat().st_mode) == 0o700


@pytest.mark.parametrize("component", ["", ".", "..", "a\x00b", "a/b"])
def test_walk_refuses_invalid_components(root: Path, component: str) -> None:
    rootfd = open_root(root)
    try:
        with pytest.raises(SingleReadRefused) as exc_info:
            walk_dirs(rootfd, ("ok", component), create=True)
    finally:
        os.close(rootfd)
    assert _reason(exc_info) is SingleReadReason.INVALID_NAME
    assert not (root / "ok").exists()


def test_walk_refuses_a_regular_file_component(root: Path) -> None:
    (root / "f").write_bytes(b"x")
    rootfd = open_root(root)
    try:
        with pytest.raises(SingleReadRefused) as exc_info:
            walk_dirs(rootfd, ("f",), create=False)
    finally:
        os.close(rootfd)
    assert _reason(exc_info) is SingleReadReason.NOT_DIRECTORY


# ---------------------------------------------------------------- read_once_at


def test_read_returns_bytes(root: Path) -> None:
    (root / "f").write_bytes(b"hello")
    (root / "f").chmod(0o600)
    assert _read(root, "f", policy=ReadPolicy.STRICT) == b"hello"


def test_read_refuses_fifo_without_blocking(root: Path) -> None:
    os.mkfifo(root / "pipe", 0o600)
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "pipe", policy=ReadPolicy.STRICT)
    assert _reason(exc_info) is SingleReadReason.NOT_REGULAR


def test_read_refuses_symlink(root: Path) -> None:
    (root / "target").write_bytes(b"x")
    (root / "link").symlink_to(root / "target")
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "link", policy=ReadPolicy.REPO)
    assert _reason(exc_info) is SingleReadReason.SYMLINK


def test_read_missing_is_not_found(root: Path) -> None:
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "absent", policy=ReadPolicy.STRICT)
    assert _reason(exc_info) is SingleReadReason.NOT_FOUND


@pytest.mark.parametrize("mode", [0o620, 0o602, 0o666])
def test_read_refuses_group_writable_under_strict(root: Path, mode: int) -> None:
    (root / "f").write_bytes(b"x")
    (root / "f").chmod(mode)
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "f", policy=ReadPolicy.STRICT)
    assert _reason(exc_info) is SingleReadReason.MODE_TOO_OPEN


def test_read_repo_policy_accepts_group_writable(root: Path) -> None:
    (root / "f").write_bytes(b"x")
    (root / "f").chmod(0o664)
    assert _read(root, "f", policy=ReadPolicy.REPO) == b"x"


def test_read_refuses_a_foreign_owner(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "f").write_bytes(b"x")
    other_uid = os.geteuid() + 1
    monkeypatch.setattr(os, "geteuid", lambda: other_uid)
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "f", policy=ReadPolicy.REPO)
    assert _reason(exc_info) is SingleReadReason.WRONG_OWNER


def test_read_size_cap(root: Path) -> None:
    (root / "f").write_bytes(b"x" * 11)
    with pytest.raises(SingleReadRefused) as exc_info:
        _read(root, "f", max_bytes=10, policy=ReadPolicy.REPO)
    assert _reason(exc_info) is SingleReadReason.OVERSIZE
    (root / "g").write_bytes(b"x" * 10)
    assert _read(root, "g", max_bytes=10, policy=ReadPolicy.REPO) == b"x" * 10


def test_read_uses_one_fd(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "f").write_bytes(b"data")
    dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    opened: list[int] = []
    fstat_fds: list[int] = []
    closed: list[int] = []
    real_open, real_fstat, real_close = os.open, os.fstat, os.close

    def spy_open(*args: Any, **kwargs: Any) -> int:
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def spy_fstat(fd: int) -> os.stat_result:
        fstat_fds.append(fd)
        return real_fstat(fd)

    def spy_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("path-based stat is a TOCTOU window")

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fstat", spy_fstat)
    monkeypatch.setattr(os, "close", spy_close)
    monkeypatch.setattr(os, "stat", forbidden)
    monkeypatch.setattr(os, "lstat", forbidden)
    try:
        assert read_once_at(dirfd, "f", max_bytes=100, policy=ReadPolicy.REPO) == b"data"
    finally:
        monkeypatch.undo()
        real_close(dirfd)
    assert len(opened) == 1
    assert set(fstat_fds) == {opened[0]}
    assert closed == opened


# ---------------------------------------------------------------- write_once


def _temps(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.startswith(".tmp."))


def test_write_once_new_file_is_written_with_exact_mode_by_stat(root: Path) -> None:
    previous = os.umask(0o077)
    try:
        outcome = write_once(root / "f.json", b"payload", root=root, mode=0o440)
    finally:
        os.umask(previous)
    assert outcome is WriteOutcome.WRITTEN
    assert (root / "f.json").read_bytes() == b"payload"
    assert stat.S_IMODE((root / "f.json").stat().st_mode) == 0o440
    assert os.listdir(root) == ["f.json"]


def test_write_once_final_mode_by_stat(root: Path) -> None:
    write_once(root / "a", b"1", root=root, mode=0o600)
    write_once(root / "b", b"1", root=root, mode=0o400)
    assert stat.S_IMODE((root / "a").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "b").stat().st_mode) == 0o400


def test_write_once_exists_equal_creates_no_temp(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = root / "d"
    sub.mkdir(mode=0o700)
    write_once(sub / "f", b"same", root=root, mode=0o400)
    sub.chmod(0o500)  # the post-seed chmod: a rerun must still succeed
    creations: list[int] = []
    real_open = os.open

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & os.O_CREAT:
            creations.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    outcome = write_once(sub / "f", b"same", root=root, mode=0o400)
    assert outcome is WriteOutcome.EXISTS_EQUAL
    assert creations == []
    assert os.listdir(sub) == ["f"]


def test_write_once_different_bytes_is_exists_different_and_untouched(root: Path) -> None:
    write_once(root / "f", b"old", root=root, mode=0o600)
    outcome = write_once(root / "f", b"new", root=root, mode=0o600)
    assert outcome is WriteOutcome.EXISTS_DIFFERENT
    assert (root / "f").read_bytes() == b"old"
    assert _temps(root) == []


def test_write_once_symlink_at_destination_with_equal_bytes_is_different(root: Path) -> None:
    (root / "target").write_bytes(b"same")
    (root / "f").symlink_to(root / "target")
    outcome = write_once(root / "f", b"same", root=root, mode=0o600)
    assert outcome is WriteOutcome.EXISTS_DIFFERENT
    assert (root / "f").is_symlink()
    assert _temps(root) == []


def test_write_once_new_file_in_owner_readonly_dir_refused(root: Path) -> None:
    sub = root / "d"
    sub.mkdir(mode=0o700)
    sub.chmod(0o500)
    with pytest.raises(SingleReadRefused) as exc_info:
        write_once(sub / "f", b"x", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.DIR_NOT_WRITABLE
    assert os.listdir(sub) == []


def test_dir_not_writable_check_precedes_any_temp_creation(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = root / "d"
    sub.mkdir(mode=0o700)
    sub.chmod(0o500)
    created: list[Any] = []
    real_open = os.open

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & os.O_CREAT:
            created.append(path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    with pytest.raises(SingleReadRefused):
        write_once(sub / "f", b"x", root=root, mode=0o600)
    assert created == []


def test_write_once_temp_name_shape_and_link_not_rename(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    links: list[tuple[str, str, bool]] = []
    real_link = os.link

    def spy_link(src: str, dst: str, **kwargs: Any) -> None:
        links.append((src, dst, kwargs["follow_symlinks"]))
        real_link(src, dst, **kwargs)

    def forbidden_rename(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("write_once has no rename fallback")

    monkeypatch.setattr(os, "link", spy_link)
    monkeypatch.setattr(os, "rename", forbidden_rename)
    monkeypatch.setattr(os, "replace", forbidden_rename)
    write_once(root / "f", b"x", root=root, mode=0o600)
    assert len(links) == 1
    src, dst, follow = links[0]
    assert TEMP_NAME_RE.match(src)
    assert dst == "f"
    assert follow is False
    assert os.listdir(root) == ["f"]


@pytest.mark.parametrize("code", [errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP, errno.EMLINK])
def test_write_once_link_unsupported_fails_closed(
    root: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    def failing_link(*args: Any, **kwargs: Any) -> None:
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(os, "link", failing_link)
    with pytest.raises(SingleReadRefused) as exc_info:
        write_once(root / "f", b"x", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.LINK_UNSUPPORTED
    assert os.listdir(root) == []


def test_write_once_eexist_race_recompares(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = os.link

    def racing_link(src: str, dst: str, **kwargs: Any) -> None:
        (root / dst).write_bytes(b"winner")
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    assert write_once(root / "f", b"winner", root=root, mode=0o600) is WriteOutcome.EXISTS_EQUAL
    (root / "f").unlink()
    assert write_once(root / "f", b"loser", root=root, mode=0o600) is WriteOutcome.EXISTS_DIFFERENT
    assert (root / "f").read_bytes() == b"winner"
    assert _temps(root) == []


def test_write_once_refuses_path_outside_root(tmp_path: Path, root: Path) -> None:
    with pytest.raises(SingleReadRefused) as exc_info:
        write_once(tmp_path / "escape", b"x", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.INVALID_NAME
    assert not (tmp_path / "escape").exists()


def test_write_once_refuses_symlinked_parent(tmp_path: Path, root: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "d").symlink_to(elsewhere)
    with pytest.raises(SingleReadRefused) as exc_info:
        write_once(root / "d" / "f", b"x", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.SYMLINK
    assert os.listdir(elsewhere) == []


# ---------------------------------------------------------------- replace_atomic


def test_replace_atomic_writes_temp_in_target_dir_fsyncs_and_replaces(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "f").write_bytes(b"old")
    events: list[str] = []
    real_replace, real_fsync = os.replace, os.fsync
    sources: list[str] = []

    def spy_replace(src: str, dst: str, **kwargs: Any) -> None:
        events.append("replace")
        sources.append(src)
        assert dst == "f"
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        real_replace(src, dst, **kwargs)

    def spy_fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "replace", spy_replace)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    replace_atomic(root / "f", b"new", root=root, mode=0o600)
    assert (root / "f").read_bytes() == b"new"
    assert stat.S_IMODE((root / "f").stat().st_mode) == 0o600
    assert len(sources) == 1 and TEMP_NAME_RE.match(sources[0])
    assert events[0] == "fsync" and "replace" in events
    assert events[events.index("replace") + 1 :].count("fsync") >= 1  # directory fsync
    assert os.listdir(root) == ["f"]


def test_replace_atomic_creates_missing_destination(root: Path) -> None:
    replace_atomic(root / "new", b"v", root=root, mode=0o600)
    assert (root / "new").read_bytes() == b"v"


def test_replace_atomic_failure_leaves_old_bytes_and_no_temp(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "f").write_bytes(b"old")

    def failing_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EIO, "boom")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(SingleReadRefused) as exc_info:
        replace_atomic(root / "f", b"new", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.IO
    assert (root / "f").read_bytes() == b"old"
    assert os.listdir(root) == ["f"]


def test_replace_atomic_in_owner_readonly_dir_refused(root: Path) -> None:
    sub = root / "d"
    sub.mkdir(mode=0o700)
    (sub / "f").write_bytes(b"old")
    sub.chmod(0o500)
    with pytest.raises(SingleReadRefused) as exc_info:
        replace_atomic(sub / "f", b"new", root=root, mode=0o600)
    assert _reason(exc_info) is SingleReadReason.DIR_NOT_WRITABLE
    assert (sub / "f").read_bytes() == b"old"
