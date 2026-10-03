"""ARCH-0 seam B (WP-B2b-2): the E-13 ER-1 contract tests, at AUT-4's paths.

E-13 ER-1: the shared wrapper passes ``--size`` before ``--tmpfs /tmp``. A row
that sets ``tmpfs_size_bytes`` gets that size; any other row gets the wrapper's
default cap; a malformed value fails closed before ``execv``.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.binds import OpenedBinds
from breezy.runtime.autonomy_sandbox.bwrap import build_bwrap_argv, main
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    DEFAULT_TMPFS_SIZE_BYTES,
    MAX_TMPFS_SIZE_BYTES,
    BwrapRow,
    SandboxRoots,
)

pytestmark = pytest.mark.contract

LEAF = "breezy-autonomy-selftest-notify.service"
SENTINEL_BWRAP = "/nonexistent/sentinel-bwrap"


def _row(**changes: Any) -> BwrapRow:
    return dataclasses.replace(AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"], **changes)


def _roots(tmp_path: Path) -> SandboxRoots:
    home = tmp_path / "home"
    (home / "data" / "cache" / "autonomy_selftest").mkdir(parents=True)
    run_user = tmp_path / "run" / "user"
    run_user.mkdir(parents=True)
    return SandboxRoots(home, home / "data", home / "repo", home / "py", os.getuid(), run_user)


@pytest.mark.parametrize(
    "size",
    ["2G", "", 0, -1, True, False, 1.5, [4096], MAX_TMPFS_SIZE_BYTES + 1],
    ids=["2G", "empty", "zero", "negative", "true", "false", "float", "type", "above-max"],
)
def test_wrapper_malformed_tmpfs_size_fails_closed(size: object, tmp_path: Path) -> None:
    row = _row(tmpfs_size_bytes=size)
    table: Mapping[str, BwrapRow] = MappingProxyType({row.name: row})
    cgroup = tmp_path / "cgroup"
    cgroup.write_text(f"0::/user.slice/{LEAF}\n")
    calls: list[tuple[str, list[str]]] = []

    status = main(
        [row.name, "/usr/bin/true"],
        roots=_roots(tmp_path),
        table=table,
        cgroup_path=cgroup,
        bwrap_path=SENTINEL_BWRAP,
        execv=lambda path, argv: calls.append((path, argv)),
        environ={"PATH": "/usr/bin:/bin"},
    )

    assert status != 0
    assert calls == [], "execv must never be reached with a malformed tmpfs size"


def test_wrapper_applies_default_tmpfs_size_to_rows_without_one() -> None:
    row = _row()
    assert row.tmpfs_size_bytes is None
    roots = SandboxRoots(
        Path("/home/u"),
        Path("/home/u/d"),
        Path("/home/u/r"),
        Path("/home/u/p"),
        1000,
        Path("/run/user/1000"),
    )
    argv = build_bwrap_argv(
        row,
        ("/usr/bin/true",),
        roots=roots,
        opened=OpenedBinds(binds=(), config_files=(), config_dirs=()),
        rebinds=(),
        environ={},
        cwd="/",
    )
    index = argv.index("--tmpfs", argv.index("--size"))
    assert argv[index - 2 : index + 2] == [
        "--size",
        str(DEFAULT_TMPFS_SIZE_BYTES),
        "--tmpfs",
        "/tmp",
    ]
    explicit = build_bwrap_argv(
        _row(tmpfs_size_bytes=2 * 1024**3),
        ("/usr/bin/true",),
        roots=roots,
        opened=OpenedBinds(binds=(), config_files=(), config_dirs=()),
        rebinds=(),
        environ={},
        cwd="/",
    )
    assert ["--size", str(2 * 1024**3), "--tmpfs", "/tmp"] == explicit[
        explicit.index("--size") : explicit.index("--size") + 4
    ]
