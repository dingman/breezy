"""ARCH-0 seam B (WP-B3): the WAL snapshot helper (plan r5 AC-3; E-8, E-8a, E-7e(b), E-7a rule 3).

Every test builds a store layout under ``tmp_path`` (a ``state/`` directory holding a
WAL-mode SQLite file and its intent lock, and a 0700 cache directory under a 0700
parent). **No test touches the real execution store**: the helper is only ever pointed at
these fixtures, and a dedicated test proves the source is opened read-only and never
written (``os.open`` spy, 0555 directory, 0444 files).

The seams the tests use are the helper's own injected ``clock_ns`` / ``sleep`` and the
module-level ``_copy_files`` / ``_recover`` / ``_fingerprint`` functions, so a change made
"between the copy and the re-fingerprint" is deterministic.
"""

from __future__ import annotations

import ast
import builtins
import datetime as dt
import errno
import fcntl
import inspect
import mmap
import os
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy import pins
from breezy.runtime.autonomy_sandbox import wal_snapshot as ws
from breezy.runtime.autonomy_sandbox.wal_snapshot import (
    EXEC_STORE_FILENAME,
    INTENT_LOCK_SUFFIX,
    QUIESCENCE_NS,
    SnapshotFailureReason,
    SnapshotReadFailure,
    WalSnapshot,
    connect_snapshot_readonly,
    exec_snapshot,
    exec_store_paths,
    wal_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REASON = SnapshotFailureReason
_REAL_OPEN = os.open
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_FIXED_TIME_NS = 1_700_000_000_000_000_000
_OLD_NS = _FIXED_TIME_NS - 3_600 * 1_000_000_000


@dataclass
class Store:
    root: Path
    state: Path
    cache: Path
    db: Path
    lock: Path

    def sidecar(self, suffix: str) -> Path:
        return self.db.with_name(self.db.name + suffix)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    data = tmp_path / "data"
    state, cache_parent = data / "state", data / "cache"
    cache = cache_parent / "snapcache"
    for directory in (data, state, cache_parent, cache):
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
    db = state / EXEC_STORE_FILENAME
    lock = state / (EXEC_STORE_FILENAME + INTENT_LOCK_SUFFIX)
    lock.write_bytes(b"")
    return Store(data, state, cache, db, lock)


def _writer(db: Path, rows: int = 5) -> sqlite3.Connection:
    """A WAL-mode writer that never checkpoints, so the ``-wal`` and ``-shm`` stay present."""
    conn = sqlite3.connect(db, isolation_level=None)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE IF NOT EXISTS t(id INTEGER PRIMARY KEY, v TEXT)")
    _insert(conn, rows)
    return conn


def _insert(conn: sqlite3.Connection, count: int, tag: str = "row") -> None:
    for index in range(count):
        conn.execute("INSERT INTO t(v) VALUES (?)", (f"{tag}{index}",))


def _values(snapshot: WalSnapshot) -> list[str]:
    conn = connect_snapshot_readonly(snapshot)
    try:
        return [row[0] for row in conn.execute("SELECT v FROM t ORDER BY id")]
    finally:
        conn.close()


def _take(store: Store, **kw: Any) -> Any:
    kw.setdefault("take_flock", False)
    kw.setdefault("lock_path", None)
    return wal_snapshot(store.db, cache_dir=store.cache, **kw)


def _result(store: Store, **kw: Any) -> tuple[Any, list[str]]:
    """The yielded value, and the (copy of the) rows when it is a snapshot."""
    with _take(store, **kw) as outcome:
        values = _values(outcome) if isinstance(outcome, WalSnapshot) else []
    return outcome, values


def _failure(store: Store, **kw: Any) -> SnapshotReadFailure:
    outcome, _ = _result(store, **kw)
    assert isinstance(outcome, SnapshotReadFailure), outcome
    return outcome


def _is_held(path: Path) -> bool:
    """Whether another open file description cannot take ``LOCK_EX|LOCK_NB`` on ``path``."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


@pytest.fixture
def open_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, int, int | None, int | None]]:
    """Every ``os.open`` as (path, flags, dir_fd, inode of dir_fd)."""
    calls: list[tuple[Any, int, int | None, int | None]] = []

    def spy(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        ino = os.fstat(dir_fd).st_ino if dir_fd is not None else None
        calls.append((path, flags, dir_fd, ino))
        return _REAL_OPEN(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", spy)
    return calls


def _after_copy(monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> list[int]:
    """Run ``action`` after every ``_copy_files`` call; return the call counter."""
    original = ws._copy_files
    count: list[int] = []

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        count.append(1)
        action()
        return result

    monkeypatch.setattr(ws, "_copy_files", wrapper)
    return count


def _rewrite_same_tick(path: Path, offset: int) -> None:
    """Flip one byte in place and restore size and mtime: only a content digest sees it."""
    st = path.stat()
    with path.open("r+b") as handle:
        handle.seek(offset)
        byte = handle.read(1)
        handle.seek(offset)
        handle.write(bytes([byte[0] ^ 0xFF]))
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert path.stat().st_size == st.st_size and path.stat().st_mtime_ns == st.st_mtime_ns


def _launch_ns() -> int:
    hour, minute = (int(part) for part in pins.SCHEDULE_LAUNCH_UTC.split(":"))
    launch = dt.datetime(2026, 10, 1, hour, minute, tzinfo=dt.UTC)
    return int(launch.timestamp()) * 10**9


#: 16:00 on the launch day: before the deadline floor (launch minus 120 s), so a valid
#: ``release_deadline_ns`` is in the future and the helper's own launch-day derivation matches.
_T0 = _launch_ns() - 50 * 60 * 10**9


def _locked() -> dict[str, Any]:
    """take_flock=True kwargs: a deadline derived from ``pins`` and a clock before it."""
    return {"release_deadline_ns": _launch_ns() - 120 * 10**9, "clock_ns": lambda: _T0}


def _age(store: Store) -> None:
    for path in (store.db, store.sidecar("-wal"), store.sidecar("-journal")):
        if path.exists():
            os.utime(path, ns=(_OLD_NS, _OLD_NS))


# --- the contract surface ----------------------------------------------------------


def test_failure_reason_set_is_exact() -> None:
    assert {reason.name for reason in REASON} == {
        "CACHE_DIR_MODE",
        "CACHE_BUSY",
        "LOCK_PATH_INVALID",
        "LOCK_FILE_MISSING",
        "LOCK_HELD",
        "LOCK_ERROR",
        "SOURCE_INVALID",
        "FINGERPRINT_UNSTABLE",
        "COPY_ERROR",
        "QUICK_CHECK",
        "DEADLINE",
    }


def test_exec_snapshot_kwargs_match_consumer_call_shape() -> None:
    wal = inspect.signature(wal_snapshot).parameters
    for name in ("cache_dir", "take_flock", "lock_path", "release_deadline_ns"):
        assert wal[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert next(iter(wal)) == "db_path"
    params = inspect.signature(exec_snapshot).parameters
    assert params["cache_dir"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["take_flock"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["lock_path"].default is None and params["data_root"].default is None
    assert next(iter(params)) == "cache_dir"


def test_exec_store_paths_match_node_and_supervisor() -> None:
    from breezy.runtime.trade_supervisor import intent_lock_path

    db, lock = exec_store_paths(Path("/x/breezy"))
    assert db == Path("/x/breezy/state") / EXEC_STORE_FILENAME
    assert lock == intent_lock_path(db)
    unit = (REPO_ROOT / "deploy/systemd/breezy-score-live-trials.service").read_text()
    match = re.search(r"^Environment=POLYMARKET_US_EXEC_STATE_DB=(\S+)$", unit, re.MULTILINE)
    assert match is not None and match.group(1).endswith(f"/state/{EXEC_STORE_FILENAME}")


def test_exec_store_paths_default_is_pwd_home_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    import pwd

    monkeypatch.setenv("HOME", "/nonexistent-home-not-pwd")
    db, _ = exec_store_paths()
    assert db == Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/share/breezy/state" / (
        EXEC_STORE_FILENAME
    )


def test_exec_snapshot_reads_the_store_under_data_root(store: Store) -> None:
    conn = _writer(store.db)
    with exec_snapshot(
        cache_dir=store.cache, take_flock=False, lock_path=None, data_root=store.root
    ) as snap:
        assert isinstance(snap, WalSnapshot)
        assert len(_values(snap)) == 5
    conn.close()


def test_exec_snapshot_derives_the_lock_beside_the_db_when_taking_the_flock(store: Store) -> None:
    conn = _writer(store.db)
    with exec_snapshot(
        cache_dir=store.cache,
        take_flock=True,
        data_root=store.root,
        **_locked(),
    ) as snap:
        assert isinstance(snap, WalSnapshot)
        assert snap.took_flock is True and snap.advisory is False
    conn.close()


def test_take_flock_true_call_sites_allowlisted() -> None:
    """Only the AUT-5 16:45 pass may take the flock; its allowlist starts empty."""
    allowlist: set[str] = set()
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.endswith("autonomy_sandbox/wal_snapshot.py") or rel in allowlist:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in {"wal_snapshot", "exec_snapshot"}:
                continue
            for kw in node.keywords:
                is_false = isinstance(kw.value, ast.Constant) and kw.value.value is False
                if kw.arg == "take_flock" and not is_false:
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_helper_holds_no_launch_time_literal() -> None:
    """The deadline is the caller's (from pins); the helper's code carries no 16:48/16:50 value."""
    tree = ast.parse(Path(ws.__file__).read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    clock_like = re.compile(r"\b\d{1,2}:\d{2}\b")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in docstrings:
            continue
        assert not (isinstance(node.value, str) and clock_like.search(node.value)), node.value
        assert node.value not in {1645, 1648, 1650}, node.value
    assert "pins.SCHEDULE_LAUNCH_UTC" in ast.unparse(tree)  # the launch instant comes from pins


# --- recovery and content ----------------------------------------------------------


def test_snapshot_includes_uncheckpointed_wal_rows_while_writer_connected(store: Store) -> None:
    conn = _writer(store.db, rows=7)
    assert store.sidecar("-wal").stat().st_size > 0 and store.sidecar("-shm").exists()
    outcome, values = _result(store)
    assert isinstance(outcome, WalSnapshot) and outcome.advisory is True
    assert values == [f"row{i}" for i in range(7)]
    conn.close()


_CHILD_WRITER = """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], isolation_level=None)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA wal_autocheckpoint=0")
conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
for i in range(4):
    conn.execute("INSERT INTO t(v) VALUES (?)", (f"committed{i}",))
conn.execute("BEGIN")
for i in range(300):
    conn.execute("INSERT INTO t(v) VALUES (?)", (f"uncommitted{i}" + "x" * 200,))
print("ready", flush=True)
import time
time.sleep(60)
"""


def test_recovers_stale_wal_after_sigkill(store: Store) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD_WRITER, str(store.db)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None and child.stdout.readline().strip() == "ready"
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    assert store.sidecar("-wal").exists()
    outcome, values = _result(store)
    assert isinstance(outcome, WalSnapshot)
    assert values == [f"committed{i}" for i in range(4)]


def test_copy_opens_mode_ro_without_sidecars(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store) as snap:
        assert isinstance(snap, WalSnapshot)
        assert sorted(p.name for p in snap.path.parent.iterdir()) == [EXEC_STORE_FILENAME]
        ro = connect_snapshot_readonly(snap)
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t(v) VALUES ('x')")
        ro.close()
    conn.close()


def test_never_copies_shm(store: Store, open_spy: list[Any]) -> None:
    conn = _writer(store.db)
    assert store.sidecar("-shm").exists()
    _result(store)
    names = [str(call[0]) for call in open_spy]
    assert not [name for name in names if name.endswith("-shm")], names
    conn.close()


def test_copy_order_db_wal_journal(store: Store, open_spy: list[Any]) -> None:
    conn = _writer(store.db)
    store.sidecar("-journal").write_bytes(b"\0" * 600)
    _result(store)
    created = [str(c[0]) for c in open_spy if c[1] & os.O_EXCL and c[1] & os.O_CREAT]
    assert created == [
        EXEC_STORE_FILENAME,
        EXEC_STORE_FILENAME + "-wal",
        EXEC_STORE_FILENAME + "-journal",
    ]
    conn.close()


def test_copies_are_dir_fd_relative(store: Store, open_spy: list[Any]) -> None:
    conn = _writer(store.db)
    store.sidecar("-journal").write_bytes(b"\0" * 600)
    with _take(store, take_flock=True, lock_path=store.lock, **_locked()) as snap:
        assert isinstance(snap, WalSnapshot)
    absolute = [str(c[0]) for c in open_spy if c[2] is None and str(c[0]) != "/"]
    assert absolute == [], absolute
    store_names = {EXEC_STORE_FILENAME + s for s in ("", "-wal", "-journal", INTENT_LOCK_SUFFIX)}
    assert store_names & {str(c[0]) for c in open_spy}
    conn.close()


# --- the live store is read-only ---------------------------------------------------


def test_source_is_never_opened_for_writing_or_changed(
    store: Store, open_spy: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    store.sidecar("-journal").write_bytes(b"\0" * 600)
    sources = [store.db, store.sidecar("-wal"), store.sidecar("-journal"), store.lock]
    for path in sources:
        path.chmod(0o444)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in sources}
    listing = sorted(os.listdir(store.state))
    source_ino = store.state.stat().st_ino
    connects: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(*args: Any, **kwargs: Any) -> Any:
        connects.append(str(args[0]))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spying_connect)
    builtin_opens: list[tuple[Any, str]] = []
    real_builtin_open = builtins.open

    def spying_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        builtin_opens.append((file, mode))
        return real_builtin_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spying_open)
    mmaps: list[tuple[Any, ...]] = []
    monkeypatch.setattr(mmap, "mmap", lambda *a, **k: mmaps.append(a))
    store.state.chmod(0o555)
    try:
        for flock in (False, True):
            with _take(
                store,
                take_flock=flock,
                lock_path=store.lock if flock else None,
                **_locked(),
            ) as snap:
                assert isinstance(snap, WalSnapshot)
    finally:
        store.state.chmod(0o700)
    writes = [c for c in open_spy if c[3] == source_ino and c[1] & _WRITE_FLAGS]
    assert writes == []
    assert all(c[3] != source_ino or c[1] & 3 == os.O_RDONLY for c in open_spy)
    assert not [path for path in connects if str(store.state) in path]
    assert [mode for _, mode in builtin_opens if mode != "rb"] == [], builtin_opens
    assert not [f for f, _ in builtin_opens if isinstance(f, str | Path) and "state" in str(f)]
    assert mmaps == []
    assert sorted(os.listdir(store.state)) == listing
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in sources} == before
    conn.close()


# --- the fingerprint ---------------------------------------------------------------


def test_fingerprint_change_retries_then_unstable(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    sleeps: list[float] = []

    def grow_db() -> None:
        store.db.write_bytes(store.db.read_bytes() + b"\0")

    count = _after_copy(monkeypatch, grow_db)
    failure = _failure(store, copy_attempts=3, sleep=sleeps.append)
    assert failure.reason is REASON.FINGERPRINT_UNSTABLE and failure.attempts == 3
    assert len(count) == 3
    assert os.listdir(store.cache) == []
    conn.close()


def test_change_after_the_first_copy_is_retried_and_the_new_row_is_seen(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    fired: list[int] = []

    def writer_commits_once() -> None:
        if not fired:
            fired.append(1)
            _insert(conn, 1, tag="late")

    _after_copy(monkeypatch, writer_commits_once)
    outcome, values = _result(store, sleep=lambda _s: None)
    assert isinstance(outcome, WalSnapshot) and outcome.attempts == 2
    assert values[-1] == "late0"
    conn.close()


@pytest.mark.parametrize(
    ("role", "where"),
    [
        pytest.param("db", lambda size: 24, id="db_change_counter_bytes_24_to_27"),
        pytest.param("db", lambda size: 2000, id="db_page1_body"),
        pytest.param("-wal", lambda size: 8, id="wal_header_salt"),
        pytest.param("-wal", lambda size: size - 100, id="wal_tail_digest"),
    ],
)
def test_same_tick_rewrite_detected_by_header_and_tail_digest(
    store: Store, monkeypatch: pytest.MonkeyPatch, role: str, where: Callable[[int], int]
) -> None:
    conn = _writer(store.db, rows=3)
    target = store.db if role == "db" else store.sidecar(role)
    assert target.stat().st_size > (4096 + 100 if role == "-wal" else 100)
    _after_copy(monkeypatch, lambda: _rewrite_same_tick(target, where(target.stat().st_size)))
    failure = _failure(store, copy_attempts=2, sleep=lambda _s: None)
    assert failure.reason is REASON.FINGERPRINT_UNSTABLE
    conn.close()


def test_quiescence_waits_out_recent_mtime(store: Store) -> None:
    conn = _writer(store.db)
    now = _FIXED_TIME_NS
    for path in (store.db, store.sidecar("-wal")):
        os.utime(path, ns=(now - 1_000_000, now - 1_000_000))
    sleeps: list[float] = []
    outcome, _ = _result(store, clock_ns=lambda: now, sleep=sleeps.append)
    assert isinstance(outcome, WalSnapshot)
    assert sleeps == [QUIESCENCE_NS / 1e9]
    conn.close()


def test_quiescence_does_not_wait_for_old_files(store: Store) -> None:
    conn = _writer(store.db)
    _age(store)
    sleeps: list[float] = []
    outcome, _ = _result(store, clock_ns=lambda: _FIXED_TIME_NS, sleep=sleeps.append)
    assert isinstance(outcome, WalSnapshot) and sleeps == []
    conn.close()


def test_racing_writer_never_silent_miss(store: Store) -> None:
    import threading

    conn = _writer(store.db, rows=3)
    stop = threading.Event()
    committed = [3]

    def loop() -> None:
        own = sqlite3.connect(store.db, isolation_level=None, timeout=5)
        own.execute("PRAGMA wal_autocheckpoint=0")
        while not stop.is_set():
            own.execute("INSERT INTO t(v) VALUES ('race')")
            committed[0] += 1
        own.close()

    thread = threading.Thread(target=loop)
    thread.start()
    try:
        for _ in range(15):
            floor = committed[0]
            outcome, values = _result(store, copy_attempts=4, sleep=lambda _s: None)
            if isinstance(outcome, WalSnapshot):
                assert len(values) >= floor, (len(values), floor)
            else:
                assert outcome.reason is REASON.FINGERPRINT_UNSTABLE
    finally:
        stop.set()
        thread.join()
    conn.close()


# --- the intent flock (take_flock) -------------------------------------------------


def test_take_flock_true_holds_flock_on_readonly_fd(
    store: Store, monkeypatch: pytest.MonkeyPatch, open_spy: list[Any]
) -> None:
    conn = _writer(store.db)
    held_during_copy: list[bool] = []
    _after_copy(monkeypatch, lambda: held_during_copy.append(_is_held(store.lock)))
    with _take(store, take_flock=True, lock_path=store.lock, **_locked()) as snap:
        assert isinstance(snap, WalSnapshot)
        assert snap.took_flock is True and snap.advisory is False
    assert held_during_copy == [True]
    lock_opens = [c for c in open_spy if str(c[0]) == store.lock.name]
    assert len(lock_opens) == 1
    flags = lock_opens[0][1]
    assert flags & 3 == os.O_RDONLY and flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
    assert not (flags & os.O_CREAT)
    assert _is_held(store.lock) is False
    conn.close()


def test_flock_is_held_at_every_fingerprint_through_the_last(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    held: list[bool] = []
    original = ws._fingerprint

    def spy(*args: Any, **kwargs: Any) -> Any:
        held.append(_is_held(store.lock))
        return original(*args, **kwargs)

    monkeypatch.setattr(ws, "_fingerprint", spy)
    with _take(store, take_flock=True, lock_path=store.lock, **_locked()) as snap:
        assert isinstance(snap, WalSnapshot) and snap.advisory is False
    assert held and all(held)
    conn.close()


def test_advisory_false_only_with_flock_through_last_fingerprint(store: Store) -> None:
    conn = _writer(store.db)
    plain, _ = _result(store)
    assert plain.advisory is True and plain.took_flock is False
    locked, _ = _result(store, take_flock=True, lock_path=store.lock, **_locked())
    assert locked.advisory is False and locked.took_flock is True
    refused = _failure(store, take_flock=True, lock_path=store.state / "other.lock", **_locked())
    assert refused.advisory is False
    store.cache.chmod(0o755)
    assert _failure(store).advisory is True
    store.cache.chmod(0o700)
    conn.close()


def test_flock_released_before_quick_check(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _writer(store.db)
    original = ws._recover
    seen: list[bool] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(_is_held(store.lock))
        return original(*args, **kwargs)

    monkeypatch.setattr(ws, "_recover", spy)
    outcome, _ = _result(store, take_flock=True, lock_path=store.lock, **_locked())
    assert isinstance(outcome, WalSnapshot) and seen == [False]
    conn.close()


def test_take_flock_true_requires_lock_path_beside_db(store: Store) -> None:
    other = store.root / "elsewhere.lock"
    other.write_bytes(b"")
    for bad in (other, None, store.state / "x.intent.lock"):
        failure = _failure(store, take_flock=True, lock_path=bad, **_locked())
        assert failure.reason is REASON.LOCK_PATH_INVALID, bad
    assert not (store.state / "x.intent.lock").exists()


def test_take_flock_true_requires_a_release_deadline(store: Store) -> None:
    _writer(store.db).close()
    with (
        pytest.raises(ValueError, match="release_deadline_ns"),
        _take(store, take_flock=True, lock_path=store.lock),
    ):
        pass


def test_take_flock_false_never_opens_lock_path(store: Store, open_spy: list[Any]) -> None:
    conn = _writer(store.db)
    for lock_path in (None, store.lock):
        outcome, _ = _result(store, lock_path=lock_path)
        assert isinstance(outcome, WalSnapshot)
    assert not [c for c in open_spy if str(c[0]).endswith(INTENT_LOCK_SUFFIX)]
    conn.close()


def test_lock_file_missing_fails_closed_and_is_not_created(store: Store) -> None:
    _writer(store.db).close()
    store.lock.unlink()
    failure = _failure(store, take_flock=True, lock_path=store.lock, **_locked())
    assert failure.reason is REASON.LOCK_FILE_MISSING
    assert not store.lock.exists() and os.listdir(store.cache) == []


def test_lock_that_is_a_symlink_or_directory_is_invalid(store: Store, tmp_path: Path) -> None:
    _writer(store.db).close()
    target = tmp_path / "victim.lock"
    target.write_bytes(b"")
    store.lock.unlink()
    store.lock.symlink_to(target)
    kw = {"take_flock": True, "lock_path": store.lock, **_locked()}
    assert _failure(store, **kw).reason is REASON.LOCK_PATH_INVALID
    store.lock.unlink()
    store.lock.mkdir()
    assert _failure(store, **kw).reason is REASON.LOCK_PATH_INVALID


def test_unreadable_lock_file_is_lock_error(store: Store) -> None:
    _writer(store.db).close()
    store.lock.chmod(0)
    failure = _failure(store, take_flock=True, lock_path=store.lock, **_locked())
    assert failure.reason is REASON.LOCK_ERROR


def test_lock_held_after_three_attempts_is_lock_held(store: Store) -> None:
    _writer(store.db).close()
    holder = os.open(store.lock, os.O_RDONLY)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sleeps: list[float] = []
    try:
        failure = _failure(
            store,
            take_flock=True,
            lock_path=store.lock,
            **_locked(),
            sleep=sleeps.append,
        )
    finally:
        os.close(holder)
    assert failure.reason is REASON.LOCK_HELD and failure.advisory is False
    assert sleeps == [5.0, 5.0]


def test_flock_error_other_than_contention_is_lock_error(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _writer(store.db).close()

    real_flock = fcntl.flock

    def boom(fd: int, op: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            real_flock(fd, op)  # the cache-dir flock is not the one under test
            return
        raise OSError(errno.ENOLCK, "no locks")

    monkeypatch.setattr(fcntl, "flock", boom)
    failure = _failure(store, take_flock=True, lock_path=store.lock, **_locked())
    assert failure.reason is REASON.LOCK_ERROR


def test_take_flock_true_hold_bounded_node_lock_fails_fast_not_blocks(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.runtime.submit_intent import SubmitIntentLockHeld, hold_submit_intent_process_lock

    conn = _writer(store.db)
    outcomes: list[tuple[str, float]] = []

    def node_boot_attempt() -> None:
        started = time.monotonic()
        try:
            with hold_submit_intent_process_lock(store.db):
                outcomes.append(("acquired", time.monotonic() - started))
        except SubmitIntentLockHeld:
            outcomes.append(("held", time.monotonic() - started))

    _after_copy(monkeypatch, node_boot_attempt)
    with _take(store, take_flock=True, lock_path=store.lock, **_locked()) as snap:
        assert isinstance(snap, WalSnapshot)
    assert [name for name, _ in outcomes] == ["held"] and outcomes[0][1] < 1.0
    node_boot_attempt()
    assert [name for name, _ in outcomes][-1] == "acquired"
    conn.close()


# --- the release deadline (from pins, never a literal) -----------------------------


def _deadline_before_launch() -> tuple[int, int]:
    """(release deadline, launch) in epoch ns, both derived from ``pins`` (E-8 step 6)."""
    hour, minute = (int(part) for part in pins.SCHEDULE_LAUNCH_UTC.split(":"))
    launch = dt.datetime(2026, 10, 1, hour, minute, tzinfo=dt.UTC)
    launch_ns = int(launch.timestamp()) * 10**9
    return launch_ns - 120 * 10**9, launch_ns


def test_releases_by_the_deadline_before_launch_and_reports_deadline(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    deadline, launch = _deadline_before_launch()
    assert deadline < launch
    now = [deadline - 5 * 10**9]
    _after_copy(monkeypatch, lambda: now.__setitem__(0, deadline + 10**9))
    failure = _failure(
        store,
        take_flock=True,
        lock_path=store.lock,
        release_deadline_ns=deadline,
        clock_ns=lambda: now[0],
        sleep=lambda _s: None,
    )
    assert failure.reason is REASON.DEADLINE and failure.advisory is False
    assert now[0] < launch
    assert _is_held(store.lock) is False and os.listdir(store.cache) == []
    conn.close()


def test_deadline_not_reached_succeeds(store: Store) -> None:
    conn = _writer(store.db)
    deadline, _ = _deadline_before_launch()
    outcome, _ = _result(
        store,
        take_flock=True,
        lock_path=store.lock,
        release_deadline_ns=deadline,
        clock_ns=lambda: deadline - 5 * 10**9,
        sleep=lambda _s: None,
    )
    assert isinstance(outcome, WalSnapshot)
    conn.close()


def test_deadline_already_past_never_copies(store: Store, open_spy: list[Any]) -> None:
    conn = _writer(store.db)
    failure = _failure(
        store,
        release_deadline_ns=_T0 - 1,
        clock_ns=lambda: _T0,
    )
    assert failure.reason is REASON.DEADLINE
    assert not [c for c in open_spy if c[1] & os.O_EXCL]
    conn.close()


# --- the cache directory -----------------------------------------------------------


def test_cache_dir_flock_contention_is_cache_busy(store: Store) -> None:
    conn = _writer(store.db)
    holder = os.open(store.cache, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        failure = _failure(store)
    finally:
        os.close(holder)
    assert failure.reason is REASON.CACHE_BUSY
    assert isinstance(_result(store)[0], WalSnapshot)
    conn.close()


def test_cache_dir_flock_is_released_on_exit(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store):
        assert _is_held(store.cache)
    assert not _is_held(store.cache)
    conn.close()


def test_cache_dir_wrong_mode_owner_or_symlink_is_cache_dir_mode(
    store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)
    store.cache.chmod(0o755)
    assert _failure(store).reason is REASON.CACHE_DIR_MODE
    store.cache.chmod(0o700)
    store.cache.parent.chmod(0o750)
    assert _failure(store).reason is REASON.CACHE_DIR_MODE
    store.cache.parent.chmod(0o700)
    assert isinstance(_result(store)[0], WalSnapshot)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    assert _failure(store).reason is REASON.CACHE_DIR_MODE
    monkeypatch.undo()
    link = store.cache.parent / "link"
    link.symlink_to(store.cache)
    outcome = wal_snapshot(store.db, cache_dir=link, take_flock=False, lock_path=None)
    with outcome as value:
        assert isinstance(value, SnapshotReadFailure) and value.reason is REASON.CACHE_DIR_MODE
    with wal_snapshot(
        store.db, cache_dir=store.cache.parent / "missing", take_flock=False, lock_path=None
    ) as value:
        assert isinstance(value, SnapshotReadFailure) and value.reason is REASON.CACHE_DIR_MODE
    conn.close()


def test_cache_dir_checked_by_fstat_not_path(store: Store, tmp_path: Path) -> None:
    """A symlinked cache path is refused even when its target would pass every mode check."""
    conn = _writer(store.db)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    swapped = store.root / "cache" / "swapped"
    swapped.symlink_to(elsewhere)
    with wal_snapshot(store.db, cache_dir=swapped, take_flock=False, lock_path=None) as value:
        assert isinstance(value, SnapshotReadFailure) and value.reason is REASON.CACHE_DIR_MODE
    assert os.listdir(elsewhere) == []
    conn.close()


def test_leftover_snap_dirs_swept_never_following_symlinks(store: Store, tmp_path: Path) -> None:
    conn = _writer(store.db)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    (store.cache / "snap.stale").mkdir()
    (store.cache / "snap.stale" / "inner").mkdir()
    (store.cache / "snap.stale" / "inner" / "file").write_text("x")
    (store.cache / "snap.evil").symlink_to(victim)
    (store.cache / "unrelated").write_text("mine")
    outcome, _ = _result(store)
    assert isinstance(outcome, WalSnapshot)
    assert sorted(os.listdir(store.cache)) == ["unrelated"]
    assert (victim / "keep.txt").read_text() == "keep"
    conn.close()


# --- failures ----------------------------------------------------------------------


def test_source_missing_symlink_or_directory_is_source_invalid(
    store: Store, tmp_path: Path
) -> None:
    assert _failure(store).reason is REASON.SOURCE_INVALID
    real = tmp_path / "real.sqlite"
    _writer(real).close()
    store.db.symlink_to(real)
    assert _failure(store).reason is REASON.SOURCE_INVALID
    store.db.unlink()
    store.db.mkdir()
    assert _failure(store).reason is REASON.SOURCE_INVALID
    assert os.listdir(store.cache) == []


def test_source_directory_that_is_a_symlink_is_source_invalid(store: Store, tmp_path: Path) -> None:
    real = tmp_path / "realstate"
    real.mkdir()
    _writer(real / EXEC_STORE_FILENAME).close()
    link = tmp_path / "linkstate"
    link.symlink_to(real)
    with wal_snapshot(
        link / EXEC_STORE_FILENAME, cache_dir=store.cache, take_flock=False, lock_path=None
    ) as value:
        assert isinstance(value, SnapshotReadFailure) and value.reason is REASON.SOURCE_INVALID


def test_quick_check_failure_is_read_failure(store: Store) -> None:
    conn = sqlite3.connect(store.db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for index in range(400):
        conn.execute("INSERT INTO t(v) VALUES (?)", (f"row{index}" + "y" * 100,))
    conn.close()
    with store.db.open("r+b") as handle:
        handle.seek(4096 * 2)
        handle.write(b"\xff" * 2048)
    failure = _failure(store)
    assert failure.reason is REASON.QUICK_CHECK
    assert os.listdir(store.cache) == []


def test_copy_error_is_a_read_failure_not_an_exception(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _writer(store.db)

    def enospc(fd: int, data: Any) -> int:
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(os, "write", enospc)
    failure = _failure(store)
    assert failure.reason is REASON.COPY_ERROR
    monkeypatch.undo()
    assert os.listdir(store.cache) == []
    conn.close()


def test_snapshot_dir_removed_on_every_outcome(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store) as snap:
        assert isinstance(snap, WalSnapshot) and snap.path.exists()
        path = snap.path
    assert not path.exists() and os.listdir(store.cache) == []
    with pytest.raises(RuntimeError, match="boom"), _take(store) as snap:
        raise RuntimeError("boom")
    assert os.listdir(store.cache) == []
    conn.close()


def test_snapshot_path_is_under_the_real_cache_dir_in_a_private_snap_dir(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store) as snap:
        assert isinstance(snap, WalSnapshot)
        assert snap.path.parent.parent == store.cache.resolve()
        assert snap.path.parent.name.startswith("snap.")
        assert (snap.path.parent.stat().st_mode & 0o777) == 0o700
        assert (snap.path.stat().st_mode & 0o777) == 0o600
    conn.close()


def test_snapshot_result_is_immutable_and_reports_fingerprints(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store) as snap:
        assert isinstance(snap, WalSnapshot)
        assert {fp.role for fp in snap.fingerprints} == {"db", "wal", "journal"}
        by_role = {fp.role: fp for fp in snap.fingerprints}
        assert by_role["db"].present and by_role["wal"].present and not by_role["journal"].present
        with pytest.raises(AttributeError):
            snap.advisory = False  # type: ignore[misc]
    conn.close()


# --- unicode and size --------------------------------------------------------------


def test_large_and_unicode_rows_survive_the_copy(store: Store) -> None:
    conn = _writer(store.db, rows=0)
    for index in range(2000):
        conn.execute("INSERT INTO t(v) VALUES (?)", (f"é\U0001f600'; DROP TABLE t;--{index}",))
    outcome, values = _result(store)
    assert isinstance(outcome, WalSnapshot) and len(values) == 2000
    assert values[1999].endswith("1999") and values[0].startswith("é\U0001f600")
    conn.close()


# --- housekeeping ------------------------------------------------------------------


def test_module_declares_no_shell_or_network_imports() -> None:
    tree = ast.parse(textwrap.dedent(Path(ws.__file__).read_text(encoding="utf-8")))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }
    assert not imported & {"subprocess", "socket", "shutil", "nautilus_trader"}
    internal = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("breezy")
    }
    assert internal <= {
        "breezy.runtime.autonomy_sandbox.binds",
        "breezy.persistence.autonomy",  # the lazy ``pins`` import for the deadline floor
    }


# --- B10 rulings (WP-B3 security review) ------------------------------------------


_HOLDERS: list[int] = []


def _scenario_deadline(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    now = [_T0]
    _after_copy(mp, lambda: now.__setitem__(0, _launch_ns()))
    return {"clock_ns": lambda: now[0], "release_deadline_ns": _launch_ns() - 120 * 10**9}


def _scenario_unstable(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:

    def grow() -> None:
        store.db.write_bytes(store.db.read_bytes() + b"\0")

    _after_copy(mp, grow)
    return {**_locked(), "sleep": lambda _s: None}


def _scenario_copy_error(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    def enospc(fd: int, data: Any) -> int:
        raise OSError(errno.ENOSPC, "no space")

    mp.setattr(os, "write", enospc)
    return _locked()


def _scenario_quick_check(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    store.db.unlink()
    for suffix in ("-wal", "-shm"):
        store.sidecar(suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(store.db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    for index in range(400):
        conn.execute("INSERT INTO t(v) VALUES (?)", (f"row{index}" + "y" * 100,))
    conn.close()
    with store.db.open("r+b") as handle:
        handle.seek(4096 * 2)
        handle.write(b"\xff" * 2048)
    return _locked()


def _scenario_source_invalid(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    for suffix in ("", "-wal", "-shm"):
        store.sidecar(suffix).unlink(missing_ok=True)
    return _locked()


def _scenario_cache_mode(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    store.cache.chmod(0o755)
    return _locked()


def _scenario_cache_busy(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    holder = os.open(store.cache, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _HOLDERS.append(holder)
    return _locked()


def _scenario_lock_path(store: Store, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    return {**_locked(), "lock_path": store.state / "other.lock"}


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        (_scenario_deadline, REASON.DEADLINE),
        (_scenario_unstable, REASON.FINGERPRINT_UNSTABLE),
        (_scenario_copy_error, REASON.COPY_ERROR),
        (_scenario_quick_check, REASON.QUICK_CHECK),
        (_scenario_source_invalid, REASON.SOURCE_INVALID),
        (_scenario_cache_mode, REASON.CACHE_DIR_MODE),
        (_scenario_cache_busy, REASON.CACHE_BUSY),
        (_scenario_lock_path, REASON.LOCK_PATH_INVALID),
    ],
    ids=lambda v: getattr(v, "__name__", None) or str(v),
)
def test_intent_flock_is_released_before_a_failure_is_yielded(
    store: Store, monkeypatch: pytest.MonkeyPatch, scenario: Any, reason: Any
) -> None:
    """B10-R1 (H-1): inside the ``with`` body the intent flock is already free, for every reason
    reachable with the lock file present (LOCK_HELD, LOCK_ERROR and LOCK_FILE_MISSING have no
    free lock to observe: another holder, an unreadable file, no file)."""
    conn = _writer(store.db)
    try:
        kwargs = {"take_flock": True, "lock_path": store.lock, **scenario(store, monkeypatch)}
        with _take(store, **kwargs) as outcome:
            assert isinstance(outcome, SnapshotReadFailure) and outcome.reason is reason, outcome
            assert outcome.advisory is False
            assert _is_held(store.lock) is False
    finally:
        while _HOLDERS:
            os.close(_HOLDERS.pop())
        conn.close()


def test_intent_flock_is_free_inside_the_with_body_after_success(store: Store) -> None:
    conn = _writer(store.db)
    with _take(store, take_flock=True, lock_path=store.lock, **_locked()) as snap:
        assert isinstance(snap, WalSnapshot)
        assert _is_held(store.lock) is False
    conn.close()


def test_copy_loop_checks_the_deadline_after_every_chunk(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B10-R2 (M-1): a deadline passing mid-copy aborts before the remaining chunks are read."""
    conn = _writer(store.db, rows=40)
    monkeypatch.setattr(ws, "_COPY_CHUNK", 1024)
    reads: list[int] = []
    real_read = os.read

    def counting_read(fd: int, n: int) -> bytes:
        reads.append(n)
        return real_read(fd, n)

    monkeypatch.setattr(os, "read", counting_read)
    deadline = _launch_ns() - 120 * 10**9
    clock = lambda: deadline + 1 if len(reads) >= 2 else _T0
    failure = _failure(
        store, take_flock=True, lock_path=store.lock, release_deadline_ns=deadline, clock_ns=clock
    )
    assert failure.reason is REASON.DEADLINE
    assert len(reads) <= 3, len(reads)
    assert _is_held(store.lock) is False
    conn.close()


def test_release_deadline_later_than_launch_minus_120s_is_refused(store: Store) -> None:
    """B10-R2 (L-2): the deadline is validated against the pins launch instant minus 120 s."""
    floor = _launch_ns() - 120 * 10**9
    for deadline in (floor + 1, _launch_ns(), _launch_ns() + 10**9):
        with (
            pytest.raises(ValueError, match="release_deadline_ns"),
            _take(store, release_deadline_ns=deadline, clock_ns=lambda: _T0),
        ):
            pass
    _writer(store.db).close()
    outcome, _ = _result(store, release_deadline_ns=floor, clock_ns=lambda: _T0)
    assert isinstance(outcome, WalSnapshot)


def test_release_deadline_floor_follows_the_pins_schedule(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _writer(store.db).close()
    deadline = _launch_ns() - 120 * 10**9  # valid under the real 16:50
    monkeypatch.setattr(pins, "SCHEDULE_LAUNCH_UTC", "16:30")
    with (
        pytest.raises(ValueError, match="release_deadline_ns"),
        _take(store, release_deadline_ns=deadline, clock_ns=lambda: _T0),
    ):
        pass


def test_recovery_connects_through_proc_self_fd(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B10-R4 (L-1): the read-write recovery connection is opened via the snap dir's fd."""
    conn = _writer(store.db)
    seen: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(*args: Any, **kwargs: Any) -> Any:
        seen.append(str(args[0]))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spying_connect)
    outcome, values = _result(store)
    assert isinstance(outcome, WalSnapshot) and len(values) == 5
    rw = [path for path in seen if not path.startswith("file:")]
    assert len(rw) == 1 and re.fullmatch(r"/proc/self/fd/\d+/" + EXEC_STORE_FILENAME, rw[0]), rw
    conn.close()
