"""ARCH-0 seam B (WP-B2c, gate phase 2): the bus snapshot handoff across a real namespace.

The unsandboxed side (``write_bus_snapshot``, as ``ExecStartPre`` runs it) executes in the
test process with a stub ``popen`` so no real user bus is read; the sandboxed side runs a
child under real bubblewrap through ``tests.support.bwrap_harness`` (``--unshare-net``,
explicit environment). Assertions observe behaviour, not argv (E-7 rule 1).

This file is a member of ``BWRAP_HOST_TEST_FILES``; its test count is part of
``BWRAP_HOST_EXPECTED_TESTS`` (L-12).
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.bus_handoff import write_bus_snapshot
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, SandboxRoots
from tests.support.bwrap_harness import (
    CHILD_ROOTS_PRELUDE,
    make_roots,
    roots_json,
    run_in_row,
)

pytestmark = pytest.mark.bwrap_host

ROW = "breezy-autonomy-selftest"
UNIT = f"{ROW}.service"
INVOCATION = "0123456789abcdef0123456789abcdef"
STDOUT = b"Id=breezy-autonomy-selftest.service\nActiveState=active\n"


class _StubProc:
    """What ``Popen(...)`` returns for the unsandboxed writer: one canned systemctl answer."""

    pid = 4242
    returncode = 0

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.args = argv
        read_fd, write_fd = os.pipe()
        os.write(write_fd, STDOUT)
        os.close(write_fd)
        self.stdout = os.fdopen(read_fd, "rb")

    def wait(self, timeout: float | None = None) -> int:
        return 0


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    return make_roots(tmp_path)


def _unsandboxed_write(roots: SandboxRoots) -> int:
    return write_bus_snapshot(
        AUTONOMY_BWRAP_TABLE[ROW],
        roots=roots,
        environ={"INVOCATION_ID": INVOCATION},
        unit=UNIT,
        popen=_StubProc,
    )


def _in_row(roots: SandboxRoots, code: str) -> dict[str, Any]:
    argv = [sys.executable, "-c", CHILD_ROOTS_PRELUDE + textwrap.dedent(code), roots_json(roots)]
    result = run_in_row(ROW, argv, roots, env={"INVOCATION_ID": INVOCATION})
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}\n{result.stdout}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def test_in_row_systemctl_fails_and_snapshot_readable(roots: SandboxRoots) -> None:
    assert _unsandboxed_write(roots) == 0
    code = """
    import subprocess
    from breezy.runtime.autonomy_sandbox.bus_handoff import read_bus_snapshot
    from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
    row = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest"]
    try:
        done = subprocess.run(
            ["/usr/bin/systemctl", "--user", "show", "-p", "Id", "--", "breezy-x.service"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
            env={"PATH": "/usr/bin:/bin", "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"},
        )
        systemctl = "ok" if done.returncode == 0 else "failed"
    except OSError:
        systemctl = "failed"
    snapshot = read_bus_snapshot(row, environ=os.environ, roots=roots)
    snap_dir = os.path.join(str(roots.data_root), "cache", "autonomy_selftest", ".bus_snapshot")
    print(json.dumps({
        "systemctl": systemctl,
        "reads": {r.name: [r.rc, r.stdout] for r in snapshot.reads},
        "left": sorted(os.listdir(snap_dir)),
        "mode": oct(os.lstat(snap_dir).st_mode & 0o777),
    }))
    """
    report = _in_row(roots, code)
    assert report["systemctl"] == "failed"
    assert report["reads"] == {"self_show": [0, STDOUT.decode()]}
    assert report["left"] == []
    assert report["mode"] == "0o700"
    snap = roots.data_root / "cache" / "autonomy_selftest" / ".bus_snapshot"
    assert stat.S_IMODE(os.lstat(snap).st_mode) == 0o700 and list(snap.iterdir()) == []


def test_in_row_symlink_plant_then_unsandboxed_snapshot_refuses(roots: SandboxRoots) -> None:
    assert _unsandboxed_write(roots) == 0
    bind = roots.data_root / "cache" / "autonomy_selftest"
    registry = roots.data_root / "registry"
    code = """
    bind = os.path.join(str(roots.data_root), "cache", "autonomy_selftest")
    snap = os.path.join(bind, ".bus_snapshot")
    for name in os.listdir(snap):
        os.unlink(os.path.join(snap, name))
    os.rmdir(snap)
    os.symlink(os.path.join(str(roots.data_root), "registry"), snap)
    print(json.dumps({"planted": os.path.islink(snap)}))
    """
    assert _in_row(roots, code) == {"planted": True}
    assert os.path.islink(bind / ".bus_snapshot")
    before = sorted(os.listdir(registry))
    status = write_bus_snapshot(
        AUTONOMY_BWRAP_TABLE[ROW],
        roots=roots,
        environ={"INVOCATION_ID": "fedcba9876543210fedcba9876543210"},
        unit=UNIT,
        popen=_StubProc,
    )
    assert status == 78
    assert sorted(os.listdir(registry)) == before == []
