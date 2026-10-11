"""EXEC-PAR BG-8: a healthy supervisor probe leaves rate-limited positive evidence."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import trade_supervisor as ts
from breezy.runtime.breaker_supervisor_watch import (
    PROBE_INTERVAL_NS,
    BreakerProbe,
    BreakerWatchState,
)
from breezy.runtime.trade_supervisor import SupervisorPorts

SEC = 1_000_000_000
NOW = 1_700_000_000 * SEC
HOUR = 3600 * SEC
EVENT = "breaker_probe_ok"


def _forbidden(*_a: object, **_kw: object) -> Any:
    raise AssertionError("never spawns")


def _ports(probe: BreakerProbe, k: int = 1) -> SupervisorPorts:
    class _Sink:
        def emit(self, _p: object) -> None: ...

    return SupervisorPorts(
        find_node_pid=lambda: None,
        resolve_intent_lock_holder=lambda _p: None,
        intent_lock_free=lambda _p: True,
        count_intent_lock_holders=lambda _p: 0,
        terminate_after_recheck=_forbidden,
        process_alive=lambda _pid: False,
        probe_open_intent_state=lambda *a, **kw: False,
        spawn=_forbidden,
        read_log_new=lambda _p: "",
        alert_sink=_Sink(),
        probe_breaker_record=lambda _p: probe,
        configured_exec_par_k=lambda: k,
    )


def _tick(ports: SupervisorPorts, watch: BreakerWatchState, now_ns: int) -> None:
    ts._dispatch_breaker_watch(
        ports=ports,
        watch=watch,
        now=dt.datetime.fromtimestamp(now_ns / SEC, tz=dt.UTC),
        tracked_pid=None,
        store_path=Path("/nowhere"),
    )


def _ok_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(EVENT)]


def test_first_probe_logs_once_with_booleans_and_states_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    _tick(_ports(BreakerProbe.absent()), BreakerWatchState(), NOW)
    assert _ok_lines(caplog) == [
        "breaker_probe_ok k_configured=1 halted=False slots_readable=True anchor=none"
    ]


def test_second_probe_within_the_hour_does_not_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ports, watch = _ports(BreakerProbe.absent()), BreakerWatchState()
    for i in range(6):  # six probes, 10 min apart: still inside the hour
        _tick(ports, watch, NOW + i * PROBE_INTERVAL_NS)
    assert len(_ok_lines(caplog)) == 1


def test_a_probe_after_an_hour_logs_again(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ports, watch = _ports(BreakerProbe.absent()), BreakerWatchState()
    _tick(ports, watch, NOW)
    _tick(ports, watch, NOW + HOUR)
    assert len(_ok_lines(caplog)) == 2


def test_unreadable_probe_does_not_log_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    bad = replace(BreakerProbe.absent(), readable=False)
    _tick(_ports(bad), BreakerWatchState(), NOW)
    assert _ok_lines(caplog) == []


def test_states_reflect_halt_slots_and_anchor(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    probe = replace(BreakerProbe.absent(), halted=True, unreadable_slots=1, k_anchor_ns=5)
    _tick(_ports(probe, k=2), BreakerWatchState(), NOW)
    assert _ok_lines(caplog) == [
        "breaker_probe_ok k_configured=2 halted=True slots_readable=False anchor=k_gt_1"
    ]
    caplog.clear()
    unreadable = replace(BreakerProbe.absent(), anchor_readable=False)
    _tick(_ports(unreadable), BreakerWatchState(), NOW)
    assert "anchor=unreadable" in _ok_lines(caplog)[0]
