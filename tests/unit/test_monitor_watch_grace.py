"""X-15 (binding activation ruling): a bounded grace for a missing NextElapse (WP3 S6).

A missing next elapse is a finding unless the timer's service is activating or active and entered
after the last trigger, and then only for min(interval, 1 h). The stale and never-triggered checks
stay unconditional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.monitor_watch_timers import TIMER_GRACE_S, _check_block
from tests.support.monitor_watch_fixtures import TIMER_A, synth_deploy, timer_block
from tests.support.unit_health_daemon_fixtures import systemd_ts
from tests.support.unit_health_fixtures import NOW_NS, show_block
from tests.unit.test_monitor_watch import healthy, judge

SERVICE_A = "breezy-a.service"


@pytest.fixture
def deploy(tmp_path: Path) -> Path:
    return synth_deploy(tmp_path / "deploy")


def _service(*, active: str = "active", entered_s: float = -100) -> str:
    return show_block(SERVICE_A, ActiveState=active, ActiveEnterTimestamp=systemd_ts(entered_s))


def _verdict(tmp_path: Path, deploy: Path, timer: str, service: str | None) -> Any:
    blocks = [timer, *healthy(deploy)[1:]]
    if service is not None:
        blocks.append(service)
    return judge(tmp_path, deploy, blocks)


def _gone(**kw: Any) -> str:
    return timer_block(TIMER_A, next_s=-60, last_s=kw.pop("last_s", -3600), **kw)


@pytest.mark.parametrize("state", ["active", "activating"])
def test_a_running_service_newer_than_the_last_trigger_gets_the_grace(
    tmp_path: Path, deploy: Path, state: str
) -> None:
    result = _verdict(tmp_path, deploy, _gone(), _service(active=state, entered_s=-100))
    assert result.outcome == "PASS", result.findings


@pytest.mark.parametrize("state", ["inactive", "failed", "deactivating"])
def test_an_idle_service_gets_no_grace(tmp_path: Path, deploy: Path, state: str) -> None:
    result = _verdict(tmp_path, deploy, _gone(), _service(active=state))
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_a_missing_service_block_gets_no_grace(tmp_path: Path, deploy: Path) -> None:
    result = _verdict(tmp_path, deploy, _gone(), None)
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_a_service_entered_before_the_last_trigger_gets_no_grace(
    tmp_path: Path, deploy: Path
) -> None:
    result = _verdict(tmp_path, deploy, _gone(last_s=-600), _service(entered_s=-4000))
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_the_grace_ends_after_an_hour_for_a_daily_timer(tmp_path: Path, deploy: Path) -> None:
    inside = _verdict(tmp_path, deploy, _gone(last_s=-9000), _service(entered_s=-3590))
    outside = _verdict(tmp_path, deploy, _gone(last_s=-9000), _service(entered_s=-3610))
    assert inside.outcome == "PASS" and {f.kind for f in outside.findings} == {
        "timer_no_next_elapse"
    }


@pytest.mark.parametrize(("entered_s", "finding"), [(-500, False), (-700, True)])
def test_the_grace_is_the_interval_when_that_is_under_an_hour(
    entered_s: float, finding: bool
) -> None:
    block = dict(
        line.split("=", 1) for line in timer_block(TIMER_A, next_s=-60, last_s=-3000).splitlines()
    )
    service = dict(
        line.split("=", 1) for line in _service(entered_s=entered_s).splitlines() if "=" in line
    )
    found, _unreadable = _check_block(
        TIMER_A,
        block,
        interval_s=600,
        monotonic=False,
        now_ns=NOW_NS,
        today="2026-10-09",
        service=service,
    )
    assert {f.kind for f in found if f.kind == "timer_no_next_elapse"} == (
        {"timer_no_next_elapse"} if finding else set()
    )


def test_a_stale_last_trigger_is_unconditional(tmp_path: Path, deploy: Path) -> None:
    stale = _gone(last_s=-(86_400 + TIMER_GRACE_S + 60))
    result = _verdict(tmp_path, deploy, stale, _service(entered_s=-100))
    assert {f.kind for f in result.findings} == {"timer_last_trigger_stale"}


def test_never_triggered_is_unconditional(tmp_path: Path, deploy: Path) -> None:
    never = timer_block(TIMER_A, next_s=-60, last_s=None, entered_s=-(86_400 + TIMER_GRACE_S + 60))
    result = _verdict(tmp_path, deploy, never, _service(entered_s=-100))
    assert {f.kind for f in result.findings} == {"timer_never_triggered"}
