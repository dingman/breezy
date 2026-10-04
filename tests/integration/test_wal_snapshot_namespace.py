"""ARCH-0 seam B (WP-B3, gate phase 2): the WAL snapshot helper across a real namespace.

The store is a scratch layout under ``tmp_path`` (``SandboxRoots.data_root``): a WAL-mode
SQLite file in ``state/`` (read-only inside the row, as in production) and the 0700 cache
bind ``cache/autonomy_selftest``. The helper runs in a child under real bubblewrap through
``tests.support.bwrap_harness`` (``--unshare-net``, explicit environment). Assertions
observe behaviour, not argv (E-7 rule 1, E-7a rule 3). No test touches the real store.

This file is a member of ``BWRAP_HOST_TEST_FILES``; its test count is part of
``BWRAP_HOST_EXPECTED_TESTS`` (L-12).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.table import SandboxRoots
from tests.support.bwrap_harness import (
    CHILD_ROOTS_PRELUDE,
    make_roots,
    roots_json,
    run_in_row,
)

pytestmark = pytest.mark.bwrap_host

ROW = "breezy-autonomy-selftest"
DB_NAME = "exec_polymarket_us.sqlite"
LOCK_NAME = DB_NAME + ".intent.lock"
ROWS = 6


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    made = make_roots(tmp_path)
    (made.data_root / "cache").chmod(0o700)
    (made.data_root / "state" / LOCK_NAME).write_bytes(b"")
    return made


def _db(roots: SandboxRoots) -> Path:
    return roots.data_root / "state" / DB_NAME


def _wal_db_with_sidecars(roots: SandboxRoots) -> sqlite3.Connection:
    conn = sqlite3.connect(_db(roots), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for index in range(ROWS):
        conn.execute("INSERT INTO t(v) VALUES (?)", (f"row{index}",))
    assert (_db(roots).parent / (DB_NAME + "-wal")).stat().st_size > 0
    return conn


def _wal_db_without_sidecars(roots: SandboxRoots) -> None:
    conn = _wal_db_with_sidecars(roots)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    names = sorted(os.listdir(_db(roots).parent))
    assert names == [DB_NAME, LOCK_NAME], names


def _in_row(roots: SandboxRoots, code: str) -> dict[str, Any]:
    argv = [sys.executable, "-c", CHILD_ROOTS_PRELUDE + textwrap.dedent(code), roots_json(roots)]
    result = run_in_row(ROW, argv, roots)
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}\n{result.stdout}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


SNAPSHOT_CHILD = """
from breezy.runtime.autonomy_sandbox.wal_snapshot import (
    WalSnapshot, connect_snapshot_readonly, exec_snapshot)
cache = roots.data_root / "cache" / "autonomy_selftest"
state = roots.data_root / "state"
before = sorted(os.listdir(state))
kwargs = json.loads(sys.argv[2])
with exec_snapshot(cache_dir=cache, data_root=roots.data_root, **kwargs) as snap:
    if isinstance(snap, WalSnapshot):
        conn = connect_snapshot_readonly(snap)
        values = [r[0] for r in conn.execute("SELECT v FROM t ORDER BY id")]
        conn.close()
        out = {"kind": "snapshot", "values": values, "advisory": snap.advisory,
               "took_flock": snap.took_flock, "snap_dir": snap.path.parent.name[:5]}
    else:
        out = {"kind": "failure", "reason": snap.reason.name}
print(json.dumps({**out, "state_unchanged": sorted(os.listdir(state)) == before,
                  "state_snap_dirs": [n for n in os.listdir(state) if n.startswith("snap.")],
                  "cache_left": os.listdir(cache)}))
"""


def _snapshot(roots: SandboxRoots, **kwargs: Any) -> dict[str, Any]:
    code = SNAPSHOT_CHILD.replace("sys.argv[2]", repr(json.dumps(kwargs)))
    return _in_row(roots, code)


def test_wal_snapshot_under_bwrap_sidecars_present(roots: SandboxRoots) -> None:
    conn = _wal_db_with_sidecars(roots)
    report = _snapshot(roots, take_flock=False, lock_path=None)
    conn.close()
    assert report["kind"] == "snapshot", report
    assert report["values"] == [f"row{i}" for i in range(ROWS)]
    assert report["advisory"] is True and report["snap_dir"] == "snap."
    assert report["state_unchanged"] is True and report["state_snap_dirs"] == []
    assert report["cache_left"] == []


def test_wal_snapshot_under_bwrap_sidecars_absent(roots: SandboxRoots) -> None:
    _wal_db_without_sidecars(roots)
    report = _snapshot(roots, take_flock=False, lock_path=None)
    assert report["kind"] == "snapshot", report
    assert report["values"] == [f"row{i}" for i in range(ROWS)]
    assert report["state_unchanged"] is True and report["state_snap_dirs"] == []
    assert sorted(os.listdir(_db(roots).parent)) == [DB_NAME, LOCK_NAME]
    assert report["cache_left"] == []


def test_mode_ro_in_place_fails_under_bwrap_without_sidecars(roots: SandboxRoots) -> None:
    """The premise of E-7a rule 3: an in-place ``mode=ro`` open of a WAL db cannot work here."""
    _wal_db_without_sidecars(roots)
    code = """
    import sqlite3
    path = os.path.join(str(roots.data_root), "state", "exec_polymarket_us.sqlite")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("SELECT count(*) FROM t").fetchone()
        outcome = "opened"
    except sqlite3.OperationalError as exc:
        outcome = f"failed: {exc}"
    print(json.dumps({"outcome": outcome}))
    """
    assert _in_row(roots, code)["outcome"].startswith("failed")


def test_take_flock_true_under_bwrap_readonly_lock(roots: SandboxRoots) -> None:
    conn = _wal_db_with_sidecars(roots)
    lock = roots.data_root / "state" / LOCK_NAME
    before = (lock.stat().st_ino, lock.stat().st_mtime_ns, lock.stat().st_size)
    report = _snapshot(roots, take_flock=True, release_deadline_ns=time.time_ns() + 60 * 10**9)
    conn.close()
    assert report["kind"] == "snapshot", report
    assert report["took_flock"] is True and report["advisory"] is False
    assert report["values"] == [f"row{i}" for i in range(ROWS)]
    assert (lock.stat().st_ino, lock.stat().st_mtime_ns, lock.stat().st_size) == before
    assert report["state_unchanged"] is True
