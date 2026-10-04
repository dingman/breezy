"""ARCH-0 seam 5b ruling A5b-R4: ``single_read.write_once_tmpfile`` (``O_TMPFILE`` + link publish).

The file is built as an unnamed inode, fsynced, linked into place by ``/proc/self/fd`` and the
directory is fsynced. No named temporary file is ever visible. Existing destinations map to the
same ``EXISTS_EQUAL`` / ``EXISTS_DIFFERENT`` outcomes as ``write_once``.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy import single_read
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    WriteOutcome,
    write_once,
    write_once_tmpfile,
)

DATA = b'{"a":1}'


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    data_root = tmp_path / "root"
    (data_root / "d").mkdir(parents=True, mode=0o700)
    yield data_root
    for directory in (data_root / "d", data_root):
        directory.chmod(0o700)


class OsProxy:
    """``single_read.os`` with chosen functions wrapped; everything else is the real ``os``."""

    def __init__(self, **wrappers: Callable[..., Any]) -> None:
        self._wrappers = wrappers

    def __getattr__(self, name: str) -> Any:
        real = getattr(os, name)
        wrapper = self._wrappers.get(name)
        if wrapper is None:
            return real
        return lambda *a, **k: wrapper(real, *a, **k)


def names(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "d").iterdir())


def test_written_with_mode_content_and_no_leftovers(root: Path) -> None:
    out = write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert out is WriteOutcome.WRITTEN
    path = root / "d" / "f.json"
    assert path.read_bytes() == DATA
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert names(root) == ["f.json"]


def test_no_named_temp_file_is_visible_at_any_step(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, list[str]] = {}

    def spy(step: str) -> Callable[..., Any]:
        def wrapper(real: Callable[..., Any], *a: Any, **k: Any) -> Any:
            seen.setdefault(step, names(root))  # listed from inside the write step
            return real(*a, **k)

        return wrapper

    monkeypatch.setattr(
        single_read, "os", OsProxy(write=spy("write"), fsync=spy("fsync"), link=spy("link"))
    )
    write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert seen["write"] == [] and seen["fsync"] == [] and seen["link"] == []
    assert names(root) == ["f.json"]


def test_fsync_order_is_file_then_link_then_directory(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def rec(step: str) -> Callable[..., Any]:
        def wrapper(real: Callable[..., Any], *a: Any, **k: Any) -> Any:
            events.append(step)
            return real(*a, **k)

        return wrapper

    monkeypatch.setattr(single_read, "os", OsProxy(fsync=rec("fsync"), link=rec("link")))
    write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert events == ["fsync", "link", "fsync"]


def test_existing_equal_is_exists_equal_and_untouched(root: Path) -> None:
    write_once(root / "d" / "f.json", DATA, root=root, mode=0o444)
    before = (root / "d" / "f.json").stat().st_ino
    assert write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444) is (
        WriteOutcome.EXISTS_EQUAL
    )
    assert (root / "d" / "f.json").stat().st_ino == before


def test_existing_different_and_symlink_are_exists_different(root: Path) -> None:
    write_once(root / "d" / "f.json", b"other", root=root, mode=0o444)
    with pytest.raises(SingleReadRefused) as caught:
        write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert caught.value.reason is SingleReadReason.EXISTS_DIFFERENT
    (root / "d" / "ln.json").symlink_to(root / "d" / "f.json")
    with pytest.raises(SingleReadRefused) as linked:
        write_once_tmpfile(root / "d" / "ln.json", b"other", root=root, mode=0o444)
    assert linked.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert (root / "d" / "f.json").read_bytes() == b"other"


@pytest.mark.parametrize(("winner", "expected"), [(DATA, "equal"), (b"x", "different")])
def test_lost_race_at_link_maps_like_write_once(
    root: Path, monkeypatch: pytest.MonkeyPatch, winner: bytes, expected: str
) -> None:
    fired: list[bool] = []

    def racing_link(real: Callable[..., Any], *a: Any, **k: Any) -> Any:
        if not fired:
            fired.append(True)
            write_once(root / "d" / "f.json", winner, root=root, mode=0o444)
        return real(*a, **k)

    monkeypatch.setattr(single_read, "os", OsProxy(link=racing_link))
    if expected == "equal":
        out = write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
        assert out is WriteOutcome.EXISTS_EQUAL
    else:
        with pytest.raises(SingleReadRefused) as caught:
            write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
        assert caught.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert names(root) == ["f.json"]


def test_unwritable_directory_is_refused(root: Path) -> None:
    (root / "d").chmod(0o500)
    with pytest.raises(SingleReadRefused) as caught:
        write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert caught.value.reason is SingleReadReason.DIR_NOT_WRITABLE


def test_invalid_mode_and_name_are_refused(root: Path) -> None:
    with pytest.raises(SingleReadRefused) as mode:
        write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o4444)
    assert mode.value.reason is SingleReadReason.INVALID_MODE
    with pytest.raises(SingleReadRefused) as outside:
        write_once_tmpfile(root.parent / "x.json", DATA, root=root, mode=0o444)
    assert outside.value.reason is SingleReadReason.INVALID_NAME


@pytest.mark.parametrize("err", [errno.EOPNOTSUPP, errno.EISDIR])
def test_o_tmpfile_unsupported_is_a_distinct_reason(
    root: Path, monkeypatch: pytest.MonkeyPatch, err: int
) -> None:
    def refusing_open(real: Callable[..., Any], path: Any, flags: int, *a: Any, **k: Any) -> Any:
        if flags & os.O_TMPFILE == os.O_TMPFILE:
            raise OSError(err, os.strerror(err))
        return real(path, flags, *a, **k)

    monkeypatch.setattr(single_read, "os", OsProxy(open=refusing_open))
    with pytest.raises(SingleReadRefused) as caught:
        write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert caught.value.reason is SingleReadReason.TMPFILE_UNSUPPORTED
    assert names(root) == []


def test_missing_proc_self_fd_is_unsupported(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_proc(real: Callable[..., Any], *a: Any, **k: Any) -> Any:
        raise FileNotFoundError(errno.ENOENT, "no /proc")

    monkeypatch.setattr(single_read, "os", OsProxy(link=no_proc))
    with pytest.raises(SingleReadRefused) as caught:
        write_once_tmpfile(root / "d" / "f.json", DATA, root=root, mode=0o444)
    assert caught.value.reason is SingleReadReason.TMPFILE_UNSUPPORTED
    assert names(root) == []


def test_this_host_supports_o_tmpfile_on_the_test_filesystem(root: Path) -> None:
    fd = os.open(root / "d", os.O_TMPFILE | os.O_WRONLY, 0o600)
    os.close(fd)
