"""Focused tests for the named directory-fsync helper."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


def test_fsync_directory_opens_o_rdonly_fsyncs_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.persistence.archive_cache import fsync_directory

    opened: list[int] = []
    fsynced: list[int] = []
    closed: list[int] = []
    real_open = os.open
    real_fsync = os.fsync
    real_close = os.close

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if os.path.realpath(path) == os.path.realpath(tmp_path):
            opened.append(flags)
            fsynced.clear()
            closed.clear()
        return fd

    def spy_fsync(fd: int) -> None:
        fsynced.append(fd)
        real_fsync(fd)

    def spy_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(os, "close", spy_close)

    fsync_directory(tmp_path)

    assert opened, "fsync_directory must open the directory"
    assert all((flags & os.O_ACCMODE) == os.O_RDONLY for flags in opened)
    assert fsynced, "fsync_directory must fsync the opened fd"
    assert closed, "fsync_directory must close the opened fd"


def test_fsync_directory_raises_when_the_directory_is_missing(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import fsync_directory

    with pytest.raises(OSError):
        fsync_directory(tmp_path / "missing")


def test_fsync_directory_raises_when_the_path_is_a_file(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import fsync_directory

    target = tmp_path / "not-a-dir"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        fsync_directory(target)
