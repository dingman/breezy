"""CT-2: the boot shell adopts a real flock-holding child and does not spawn.

Entry point: ``breezy.runtime.trade_supervisor._do_launch`` (the 16:50Z boot
shell). The child is a real ``subprocess.Popen``, not a ``FakePopen``. It
holds the intent flock itself. Discovery is bound to that child's pid because
a host-global ``pgrep`` would see the live ``breezy-trade`` on this machine
and must not adopt or signal it. The flock match is the real ``/proc/locks``
resolver (``resolve_lock_holder_pid``).
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.trade_supervisor import (
    _SPAWNED_CHILDREN,
    _SUPERVISOR_SPAWNED,
    SupervisorPorts,
    _do_launch,
    count_lock_holders,
    intent_lock_is_free,
    intent_lock_path,
    process_is_alive,
    resolve_lock_holder_pid,
    spawn_node,
)
from breezy.runtime.trade_supervisor_core import (
    AlertDetail,
    initial_scheduler_state,
)
from tests.unit.test_trade_supervisor import (
    _DAY,
    _RecordingAlertSink,
    _utc,
)

_WAIT_S: Final[float] = 5.0
_POLL_S: Final[float] = 0.05


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


def _wait_until_holder(
    proc: subprocess.Popen[bytes],
    ready: Path,
    lock_path: Path,
    stderr_path: Path,
) -> None:
    deadline = time.monotonic() + _WAIT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            detail = ""
            if stderr_path.is_file():
                detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-500:]
            raise AssertionError(
                f"flock child exited early rc={proc.returncode} stderr={detail!r}"
            )
        if ready.is_file() and resolve_lock_holder_pid(lock_path) == proc.pid:
            return
        time.sleep(_POLL_S)
    raise AssertionError("real child never became the /proc/locks holder")


def test_boot_shell_adopts_real_flock_holder_and_does_not_spawn(tmp_path: Path) -> None:
    """``_do_launch`` adopts the pid that holds the intent flock.

    A second node (``node_bin``) touches ``marker`` only if spawn runs.
    """
    store_path = tmp_path / "state" / "store.sqlite3"
    lock_path = intent_lock_path(store_path)
    # os.open(O_CREAT) does not create missing parents; the holder exits 1
    # before it can flock if ``state/`` is absent.
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    ready = tmp_path / "holder.ready"
    marker = tmp_path / "second-node.spawned"
    log_dir = tmp_path / "logs"
    holder_bin = tmp_path / "hold-flock"
    node_bin = tmp_path / "node-bin"
    stderr_path = tmp_path / "holder.stderr"
    _write_script(
        holder_bin,
        "import fcntl, os, time\n"
        f"fd = os.open({str(lock_path)!r}, os.O_CREAT | os.O_RDWR, 0o644)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        f"open({str(ready)!r}, 'w', encoding='utf-8').close()\n"
        "time.sleep(60)\n",
    )
    _write_script(
        node_bin,
        "import time\n"
        f"open({str(marker)!r}, 'w', encoding='utf-8').close()\n"
        "time.sleep(30)\n",
    )
    stderr_fh = stderr_path.open("wb")
    try:
        holder = subprocess.Popen(
            [str(holder_bin)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh,
        )
    finally:
        stderr_fh.close()
    spawned: list[subprocess.Popen[bytes]] = []

    def _spawn_and_record(
        *,
        node_bin: Path,
        repo_root: Path,
        env: object,
        log_path: Path,
    ) -> subprocess.Popen[bytes]:
        del env
        proc = spawn_node(
            node_bin=node_bin,
            repo_root=repo_root,
            env={"CT02": "synthetic"},
            log_path=log_path,
        )
        spawned.append(proc)
        return proc

    sink = _RecordingAlertSink()
    ports = SupervisorPorts(
        find_node_pid=lambda: holder.pid,
        resolve_intent_lock_holder=_holder_pid,
        intent_lock_free=intent_lock_is_free,
        count_intent_lock_holders=_holder_count,
        terminate_after_recheck=_noop_terminate,
        process_alive=process_is_alive,
        probe_open_intent_state=lambda *_a, **_k: False,
        spawn=_spawn_and_record,
        read_log_new=lambda _path: "",
        alert_sink=sink,
        find_adopted_log=lambda _log_dir, _pid: None,
    )
    try:
        _wait_until_holder(holder, ready, lock_path, stderr_path)
        assert intent_lock_is_free(lock_path) is False
        pid, _log_path, _state, done = _do_launch(
            ports=ports,
            state=initial_scheduler_state(_DAY),
            now=_utc(16, 50),
            store_path=store_path,
            repo_root=tmp_path,
            node_bin=node_bin,
            log_dir=log_dir,
        )
        assert done is True
        assert pid == holder.pid
        assert spawned == []
        assert not marker.exists()
        assert all(
            payload.detail != AlertDetail.LAUNCH_BLOCKED_LOCK_HELD.value
            for payload in sink.payloads
        )
    finally:
        for proc in spawned:
            _reap(proc)
        _reap(holder)
        _SPAWNED_CHILDREN.clear()
        _SUPERVISOR_SPAWNED.clear()


def _holder_pid(lock_path: Path) -> int | None:
    return resolve_lock_holder_pid(lock_path)


def _holder_count(lock_path: Path) -> int:
    return count_lock_holders(lock_path)


def _noop_terminate(*_args: object, **_kwargs: object) -> None:
    return None
