"""AUT-1 WP5 stage 3 (gate phase 2): the in-process studies lock across a real namespace.

The audit unit takes ``%t/breezy-studies.lock`` itself (``studies_lock.acquire_studies_lock``), so
the same inode that the wrapper re-binds into the sandbox must exclude the host both ways. The
child runs under real bubblewrap through ``tests.support.bwrap_harness`` in the shipped
``breezy-capture-audit`` row (``network="none"``, ``E7_STUDIES_LOCK``). The lock lives in a scratch
``run_user`` directory: the real host lock is never taken.

This file is a member of ``BWRAP_HOST_TEST_FILES``; its 2 tests are part of
``BWRAP_HOST_EXPECTED_TESTS`` (L-12).
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.run_mounts import STUDIES_LOCK_NAME
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, SandboxRoots
from tests.support.bwrap_harness import (
    CHILD_ROOTS_PRELUDE,
    make_roots,
    roots_json,
    run_in_row,
)

pytestmark = pytest.mark.bwrap_host

ROW = "breezy-capture-audit"
PRIVATE = 0o700

PROBE = """
import errno, fcntl
from breezy.runtime.autonomy_sandbox.studies_lock import (
    StudiesLockTimeout, acquire_studies_lock)
path = roots.run_user / "breezy-studies.lock"
out = {}
try:
    fd = acquire_studies_lock(path, wait_s=0.3, poll_s=0.05)
    out["helper"] = "acquired"
    out["cloexec"] = not os.get_inheritable(fd)
    os.close(fd)
except StudiesLockTimeout:
    out["helper"] = "timeout"
raw = os.open(path, os.O_RDONLY)
try:
    fcntl.flock(raw, fcntl.LOCK_EX | fcntl.LOCK_NB)
    out["raw"] = "acquired"
except BlockingIOError as exc:
    out["raw"] = "EWOULDBLOCK" if exc.errno == errno.EWOULDBLOCK else str(exc.errno)
print(json.dumps(out))
"""


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    made = make_roots(tmp_path)
    for rel in AUTONOMY_BWRAP_TABLE[ROW].binds:
        directory = made.data_root / rel
        directory.mkdir(parents=True, exist_ok=True)
        for part in [directory, *directory.parents]:
            if part == made.data_root.parent:
                break
            part.chmod(PRIVATE)
    return made


def _lock(roots: SandboxRoots) -> Path:
    lock = roots.run_user / STUDIES_LOCK_NAME
    lock.touch(mode=0o600)
    return lock


def _in_row(roots: SandboxRoots) -> dict[str, Any]:
    code = CHILD_ROOTS_PRELUDE + textwrap.dedent(PROBE)
    result = run_in_row(ROW, [sys.executable, "-c", code, roots_json(roots)], roots)
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}\n{result.stdout}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def test_studies_lock_in_row_alone_succeeds(roots: SandboxRoots) -> None:
    lock = _lock(roots)
    seen = _in_row(roots)
    assert seen["helper"] == "acquired" and seen["cloexec"] is True
    assert seen["raw"] == "acquired"  # the helper's fd was closed: the lock is free again
    assert os.stat(lock).st_nlink == 1


def test_studies_lock_in_row_held_by_host_ewouldblock(roots: SandboxRoots) -> None:
    lock = _lock(roots)
    held = os.open(lock, os.O_RDONLY)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        seen = _in_row(roots)
    finally:
        os.close(held)
    assert seen == {"helper": "timeout", "raw": "EWOULDBLOCK"}
