"""CT-14: a restarted supervisor re-derives readiness for a REAL adopted node.

SUP-RESTART-ANYTIME. A real ``subprocess.Popen`` child takes the intent flock
(``/proc/locks``) and writes a node-stamped log in the real ANSI-wrapped
Nautilus format. The supervisor side uses the real ``resolve_lock_holder_pid``,
``process_is_alive``, ``find_adopted_node_log`` and ``IncrementalLogReader``;
only ``find_node_pid`` is injected (a host-global ``pgrep`` would see the live
production node) and ``spawn`` is a recorder that must never be called.

The child stamps its lines with ``wall clock + offset`` so the fake supervisor
clock (set to a chosen UTC instant of trading day ``_DAY``) lines up with them.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.trade_supervisor import (
    _SPAWNED_CHILDREN,
    _SUPERVISOR_SPAWNED,
    IncrementalLogReader,
    SupervisorPorts,
    _do_permit_watch,
    _run_forever,
    count_lock_holders,
    find_adopted_node_log,
    intent_lock_is_free,
    intent_lock_path,
    process_is_alive,
    resolve_lock_holder_pid,
)
from breezy.runtime.trade_supervisor_core import (
    AlertDetail,
    DaySchedulerState,
    initial_scheduler_state,
)
from tests.unit.test_ct02_supervisor_adopt_real_child import (
    _reap,
    _wait_until_holder,
    _write_script,
)
from tests.unit.test_trade_supervisor import (
    _DAY,
    _FAR_FUTURE_EXPIRES_AT_NS,
    FakeClock,
    FakeSpawner,
    _RecordingAlertSink,
    _utc,
    ra_boot_text,
)

_WAIT_S: Final[float] = 5.0
_NODE_STAMP: Final[str] = "20260904T165100Z"
_RA_EVENT: Final[str] = "TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED"


@pytest.fixture(autouse=True)
def _clear_retained_children() -> Iterator[None]:
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()
    yield
    _SPAWNED_CHILDREN.clear()
    _SUPERVISOR_SPAWNED.clear()


_CHILD_BODY: Final[str] = """\
import datetime, fcntl, os, time
lock_fd = os.open({lock!r}, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
log = open({log!r}, 'a', buffering=1) if {write_log!r} else None
if log is not None:
    log.write({boot!r})
open({ready!r}, 'w').close()
while True:
    if log is not None and {shadow!r}:
        at = datetime.datetime.fromtimestamp(time.time() + {offset!r}, datetime.timezone.utc)
        log.write(
            '\\x1b[1m%s.%06d000Z\\x1b[0m [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: '
            'SHADOW_DECISION {{}}\\n' % (at.strftime('%Y-%m-%dT%H:%M:%S'), at.microsecond)
        )
        log.flush()
    time.sleep(0.2)
"""


@dataclass
class _Rig:
    store_path: Path
    lock_path: Path
    log_dir: Path
    log_path: Path
    ready: Path
    proc: subprocess.Popen[bytes]
    stderr_path: Path
    offset_s: float
    sink: _RecordingAlertSink
    spawner: FakeSpawner
    reader: IncrementalLogReader
    terminated: list[int]

    def fake_now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(time.time() + self.offset_s, dt.UTC)

    def ports(self, **overrides: object) -> SupervisorPorts:
        base: dict[str, object] = {
            "find_node_pid": lambda: self.proc.pid,
            "resolve_intent_lock_holder": resolve_lock_holder_pid,
            "intent_lock_free": intent_lock_is_free,
            "count_intent_lock_holders": count_lock_holders,
            "terminate_after_recheck": lambda pid, **_kw: self.terminated.append(pid),
            "process_alive": process_is_alive,
            "probe_open_intent_state": lambda *_a, **_k: False,
            "spawn": self.spawner,
            "read_log_new": self.reader.read_new,
            "read_log_from_start": self.reader.read_from_start_and_mark_consumed,
            "alert_sink": self.sink,
            "find_adopted_log": find_adopted_node_log,
        }
        base.update(overrides)
        return SupervisorPorts(**base)  # type: ignore[arg-type]


def _start_rig(
    tmp_path: Path,
    *,
    fake_at: dt.datetime,
    write_log: bool = True,
    shadow: bool = True,
    boot: str | None = None,
    stamp: str = _NODE_STAMP,
) -> _Rig:
    store_path = tmp_path / "state" / "store.sqlite3"
    lock_path = intent_lock_path(store_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"breezy-trade-{stamp}.log"
    ready = tmp_path / "child.ready"
    stderr_path = tmp_path / "child.stderr"
    offset = fake_at.timestamp() - time.time()
    body = _CHILD_BODY.format(
        lock=str(lock_path),
        log=str(log_path),
        write_log=write_log,
        boot=boot if boot is not None else ra_boot_text(_FAR_FUTURE_EXPIRES_AT_NS),
        ready=str(ready),
        shadow=shadow,
        offset=offset,
    )
    child_bin = tmp_path / "node-child"
    _write_script(child_bin, body)
    with stderr_path.open("wb") as stderr_fh:
        proc = subprocess.Popen(
            [str(child_bin)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_fh,
        )
    _wait_until_holder(proc, ready, lock_path, stderr_path)
    time.sleep(0.5)  # a few SHADOW_DECISION lines
    return _Rig(
        store_path=store_path,
        lock_path=lock_path,
        log_dir=log_dir,
        log_path=log_path,
        ready=ready,
        proc=proc,
        stderr_path=stderr_path,
        offset_s=offset,
        sink=_RecordingAlertSink(),
        spawner=FakeSpawner(),
        reader=IncrementalLogReader(),
        terminated=[],
    )


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        _reap(proc)


def _run(rig: _Rig, start: dt.datetime, iterations: int, caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock(start)

    def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)

    with caplog.at_level(logging.INFO):
        _run_forever(
            store_path=rig.store_path,
            repo_root=rig.store_path.parent,
            node_bin=rig.store_path.parent / "node_bin",
            log_dir=rig.log_dir,
            clock=clock,
            sleep=fake_sleep,
            ports=rig.ports(),
            max_iterations=iterations,
        )


def _poll(
    rig: _Rig,
    *,
    start: dt.datetime,
    polls: int,
    state: DaySchedulerState | None = None,
    tracked_pid: int | None = None,
    node_log: Path | None = None,
    ports: SupervisorPorts | None = None,
) -> tuple[DaySchedulerState, int | None, Path | None]:
    state = state if state is not None else initial_scheduler_state(_DAY)
    active = ports if ports is not None else rig.ports()
    for k in range(polls):
        tracked_pid, node_log, state = _do_permit_watch(
            ports=active,
            state=state,
            now=start + dt.timedelta(seconds=60 * k),
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=rig.store_path,
            log_dir=rig.log_dir,
            handler_read_log=False,
        )
    return state, tracked_pid, node_log


def _messages(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [m for m in caplog.messages if m.startswith(prefix)]


def _aligned(rig: _Rig, day_at: dt.datetime) -> dt.datetime:
    """The fake clock reading that matches the child's stamps, on ``day_at``'s date."""
    now = rig.fake_now()
    return day_at.replace(
        hour=now.hour, minute=now.minute, second=now.second, microsecond=now.microsecond
    )


def test_real_flock_holder_with_fresh_liveness_line_is_marked_after_restart(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, children: list[subprocess.Popen[bytes]]
) -> None:
    """T17"""
    rig = _start_rig(tmp_path, fake_at=_utc(20, 0))
    children.append(rig.proc)
    pid_before = rig.proc.pid
    _run(rig, rig.fake_now(), 3, caplog)
    assert _messages(caplog, f"restart_adopted_ready_node pid={pid_before} ")
    assert rig.spawner.calls == []
    assert rig.terminated == []
    assert rig.proc.pid == pid_before
    assert resolve_lock_holder_pid(rig.lock_path) == pid_before


@pytest.mark.parametrize("restart_at", [_utc(16, 50), _utc(16, 55)], ids=["1650", "1655"])
def test_real_flock_restart_at_1650_and_1655_adopts_without_spawn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    children: list[subprocess.Popen[bytes]],
    restart_at: dt.datetime,
) -> None:
    """T14b (S6): a restart inside the launch window adopts, never spawns."""
    rig = _start_rig(tmp_path, fake_at=restart_at)
    children.append(rig.proc)
    pid_before = rig.proc.pid
    _run(rig, rig.fake_now(), 12, caplog)
    assert _messages(caplog, f"launch_adopted_live_node pid={pid_before}")
    assert rig.spawner.calls == []
    assert rig.terminated == []
    assert rig.proc.pid == pid_before
    assert resolve_lock_holder_pid(rig.lock_path) == pid_before
    if restart_at == _utc(16, 55):
        assert _messages(caplog, f"node_ready pid={pid_before}")  # RELAUNCH_CHECK latched readiness


def test_real_live_pid_not_holding_flock_is_never_marked(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, children: list[subprocess.Popen[bytes]]
) -> None:
    """T18, mirroring ct02: a live pid that is not the flock holder never marks."""
    rig = _start_rig(tmp_path, fake_at=_utc(20, 0))
    children.append(rig.proc)
    bystander = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    children.append(bystander)
    start = rig.fake_now()
    # (a) adoption: discovery returns the bystander, the flock is held by the child.
    with caplog.at_level(logging.INFO):
        state, tracked, _log = _poll(
            rig, start=start, polls=3, ports=rig.ports(find_node_pid=lambda: bystander.pid)
        )
    assert tracked is None
    assert state.readiness_observed is False
    assert not _messages(caplog, "restart_adopted_ready_node")
    # (b) the bystander is already tracked and the child's log is bound: the
    # step's own fresh probe sees the child, not the tracked pid.
    state, tracked, _log = _poll(
        rig,
        start=start,
        polls=13,
        tracked_pid=bystander.pid,
        node_log=rig.log_path,
    )
    assert state.readiness_observed is False
    assert state.ready_adoption_deferral_polls == 13
    assert [p.severity for p in rig.sink.payloads if p.event == _RA_EVENT] == ["WARN", "CRITICAL"]
    assert rig.spawner.calls == []


def _touch_before_child_start(path: Path, rig: _Rig) -> None:
    long_ago = time.time() - 3600
    os.utime(path, (long_ago, long_ago))


def test_pid_to_log_binding_selects_only_this_childs_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, children: list[subprocess.Popen[bytes]]
) -> None:
    """T18b (SL1): the real guarantee behind check 9."""
    rig = _start_rig(tmp_path, fake_at=_utc(20, 0))
    children.append(rig.proc)
    pid = rig.proc.pid
    start = rig.fake_now()

    # (a) a D-1-stamped log with fresh-looking lines whose mtime predates the child.
    stale_log = rig.log_dir / "breezy-trade-20260903T165100Z.log"
    stale_log.write_text(
        ra_boot_text(_FAR_FUTURE_EXPIRES_AT_NS)
        + "\x1b[1m2026-09-04T20:00:00.000000000Z\x1b[0m [INFO] X: SHADOW_DECISION {}\n"
    )
    _touch_before_child_start(stale_log, rig)
    assert find_adopted_node_log(rig.log_dir, pid) == rig.log_path
    with caplog.at_level(logging.INFO):
        state, tracked, node_log = _poll(rig, start=start, polls=2)
    assert tracked == pid and node_log == rig.log_path
    assert state.readiness_observed is True
    assert state.first_boot_permit_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS

    # (c) the supervisor's own logs, newer than the node log, are never returned.
    for name in (
        "breezy-trade-supervisor.log",
        "breezy-trade-supervisor-stdout-20260904T170000Z.log",
        "breezy-trade-supervisor.launch-20260904T170000Z.log",
    ):
        (rig.log_dir / name).write_text("supervisor noise\n")
        newer = time.time() + 30
        os.utime(rig.log_dir / name, (newer, newer))
    assert find_adopted_node_log(rig.log_dir, pid) == rig.log_path

    # (d) /proc/<pid> unreadable: a reaped child has no binding.
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(timeout=_WAIT_S)
    assert find_adopted_node_log(rig.log_dir, gone.pid) is None


def test_pid_to_log_binding_with_only_a_pre_start_log_is_log_unknown(
    tmp_path: Path, children: list[subprocess.Popen[bytes]]
) -> None:
    """T18b (b): only the pre-start log exists -> None -> LOG_UNKNOWN, counted, no mark."""
    rig = _start_rig(tmp_path, fake_at=_utc(20, 0), write_log=False, shadow=False)
    children.append(rig.proc)
    pre_start = rig.log_dir / "breezy-trade-20260904T165100Z.log"
    pre_start.write_text(ra_boot_text(_FAR_FUTURE_EXPIRES_AT_NS))
    _touch_before_child_start(pre_start, rig)
    assert find_adopted_node_log(rig.log_dir, rig.proc.pid) is None
    start = rig.fake_now()
    latched = initial_scheduler_state(_DAY)
    latched = replace(
        latched,
        permit_issued_seen_expires_at_ns=_FAR_FUTURE_EXPIRES_AT_NS,
        first_boot_permit_expires_at_ns=_FAR_FUTURE_EXPIRES_AT_NS,
        strategy_subscribed_seen=True,
        liveness_line_last_ns=int(start.timestamp()) * 1_000_000_000,
    )
    state, _tracked, _log = _poll(
        rig, start=start, polls=13, state=latched, tracked_pid=rig.proc.pid, node_log=None
    )
    assert state.readiness_observed is False
    assert state.ready_adoption_deferral_polls == 13


def test_sibling_stamped_log_written_after_start_pages_and_never_marks(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, children: list[subprocess.Popen[bytes]]
) -> None:
    """T18b (e, r4 item 3): a refused duplicate's newer node-stamped log wins
    the binding (current behaviour, pinned); the result is a counted, paged
    wrong-log deferral and never a false mark."""
    rig = _start_rig(tmp_path, fake_at=_utc(20, 0))
    children.append(rig.proc)
    sibling = rig.log_dir / "breezy-trade-20260904T170000Z.log"
    sibling.write_text("breezy-trade: SubmitIntentLockHeld: intent lock is held\n")
    newer = time.time() + 30
    os.utime(sibling, (newer, newer))
    assert find_adopted_node_log(rig.log_dir, rig.proc.pid) == sibling
    start = rig.fake_now()
    state, tracked, node_log = _poll(rig, start=start, polls=12)
    assert tracked == rig.proc.pid and node_log == sibling
    assert state.readiness_observed is False
    assert state.ready_adoption_deferral_polls == 12
    step_alerts = [p for p in rig.sink.payloads if p.event == _RA_EVENT]
    assert [p.severity for p in step_alerts] == ["WARN", "CRITICAL"]
    assert [p.detail for p in step_alerts] == [
        AlertDetail.READY_ADOPTION_DEFERRED.value,
        AlertDetail.READY_ADOPTION_UNPROVEN.value,
    ]
    assert rig.spawner.calls == []
