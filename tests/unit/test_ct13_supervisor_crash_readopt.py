"""CT-13: a crash between spawn and state return re-adopts and does not re-spawn.

Entry point: ``_do_midday_watch``. With the zero-instrument latch set, no
permit, and no tracked pid, that shell dispatches to ``_do_boot_retry``.
The ordinary midday relaunch path does not adopt before spawn; this test
does not pin that path.

The crash is ``log_decision("boot_retry_launched")`` raising after
``spawn_node`` and ``_retain_spawned_child`` return, and before the shell
returns the updated scheduler state. ``DaySchedulerState`` is in memory
only. The caller keeps the pre-call state, so the attempt increment from
the crashed call is discarded. The second call must adopt the real child
that already holds the intent flock.

Discovery is bound to that child. A host-global ``pgrep`` would see the
live ``breezy-trade`` and must not adopt or signal it. The flock match is
``resolve_lock_holder_pid`` (``/proc/locks``).
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.trade_supervisor import (
    _SPAWNED_CHILDREN,
    _SUPERVISOR_SPAWNED,
    SupervisorPorts,
    _do_midday_watch,
    count_lock_holders,
    intent_lock_is_free,
    intent_lock_path,
    log_decision,
    probe_open_intent,
    process_is_alive,
    resolve_lock_holder_pid,
    spawn_node,
)
from breezy.runtime.trade_supervisor_core import AlertDetail
from tests.unit.test_trade_supervisor import (
    _boot_retry_ready_state,
    _RecordingAlertSink,
    _utc,
)

_WAIT_S: Final[float] = 5.0
_POLL_S: Final[float] = 0.05
_CRASH: Final[str] = "ct13 injected crash after spawn, before persist"


@pytest.fixture(autouse=True)
def _clear_retained_children() -> Iterator[None]:
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()
    yield
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()


def _write_script(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _reap(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_WAIT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=_WAIT_S)


def _holder_pid(lock_path: Path) -> int | None:
    return resolve_lock_holder_pid(lock_path)


def _holder_count(lock_path: Path) -> int:
    return count_lock_holders(lock_path)


def _wait_until_holder(proc: subprocess.Popen[bytes], ready: Path, lock_path: Path) -> None:
    deadline = time.monotonic() + _WAIT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"boot-retry child exited early rc={proc.returncode}")
        if ready.is_file() and resolve_lock_holder_pid(lock_path) == proc.pid:
            return
        time.sleep(_POLL_S)
    raise AssertionError("spawned child never became the /proc/locks holder")


def test_crash_between_spawn_and_persist_readopts_on_next_boot_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "state" / "store.sqlite3"
    lock_path = intent_lock_path(store_path)
    ready = tmp_path / "retry.ready"
    node_bin = tmp_path / "retry-node"
    _write_script(
        node_bin,
        "import fcntl, os, time\n"
        f"fd = os.open({str(lock_path)!r}, os.O_CREAT | os.O_RDWR, 0o644)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        f"open({str(ready)!r}, 'w', encoding='utf-8').close()\n"
        "time.sleep(60)\n",
    )
    spawned: list[subprocess.Popen[bytes]] = []
    fired = {"n": 0}

    def _spawn_and_record(
        *,
        node_bin: Path,
        repo_root: Path,
        env: Mapping[str, str],
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        proc = spawn_node(
            node_bin=node_bin, repo_root=repo_root, env=env, log_path=log_path
        )
        spawned.append(proc)
        return proc

    def _crash_after_launch(event: str, **fields: int | str) -> None:
        log_decision(event, **fields)
        if event == "boot_retry_launched" and fired["n"] == 0:
            fired["n"] = 1
            raise RuntimeError(_CRASH)

    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.log_decision", _crash_after_launch
    )
    sink = _RecordingAlertSink()

    def _find_node() -> int | None:
        if not spawned:
            return None
        return spawned[0].pid

    ports = SupervisorPorts(
        find_node_pid=_find_node,
        resolve_intent_lock_holder=_holder_pid,
        intent_lock_free=intent_lock_is_free,
        count_intent_lock_holders=_holder_count,
        terminate_after_recheck=lambda *_a, **_k: None,
        process_alive=process_is_alive,
        probe_open_intent_state=probe_open_intent,
        spawn=_spawn_and_record,
        read_log_new=lambda _path: "",
        alert_sink=sink,
    )
    state = _boot_retry_ready_state(_utc(17, 0))
    now = _utc(17, 10)
    log_dir = tmp_path / "logs"
    try:
        with pytest.raises(RuntimeError, match=_CRASH):
            _do_midday_watch(
                ports=ports,
                state=state,
                now=now,
                tracked_pid=None,
                node_log=None,
                store_path=store_path,
                repo_root=tmp_path,
                node_bin=node_bin,
                log_dir=log_dir,
            )
        assert state.boot_retry_attempts == 0
        assert len(spawned) == 1
        _wait_until_holder(spawned[0], ready, lock_path)
        new_pid, _new_log, new_state = _do_midday_watch(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=None,
            node_log=None,
            store_path=store_path,
            repo_root=tmp_path,
            node_bin=node_bin,
            log_dir=log_dir,
        )
        assert new_pid == spawned[0].pid
        assert len(spawned) == 1
        assert new_state.boot_retry_attempts == 1
        first_alerts = [
            payload.detail
            for payload in sink.payloads
            if payload.detail == AlertDetail.BOOT_RETRY_FIRST_ATTEMPT.value
        ]
        assert first_alerts == [
            AlertDetail.BOOT_RETRY_FIRST_ATTEMPT.value,
            AlertDetail.BOOT_RETRY_FIRST_ATTEMPT.value,
        ]
    finally:
        for proc in spawned:
            _reap(proc)
        _SPAWNED_CHILDREN.clear()
        _SUPERVISOR_SPAWNED.clear()
