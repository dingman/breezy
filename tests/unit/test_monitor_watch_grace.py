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


# --------------------------------------------------------------------------- oneshot services


def _oneshot(*, state: str = "activating", ended_s: float = -600, entered: str = "") -> str:
    """A running oneshot as systemd reports it: ``ActiveEnterTimestamp`` is EMPTY (the unit is
    activating until it exits and never enters ``active``); ``InactiveEnterTimestamp`` is the end
    of the previous run. Observed on ``breezy-autonomy-health.service`` at its own 08:21Z pass."""
    return show_block(
        SERVICE_A,
        ActiveState=state,
        ActiveEnterTimestamp=entered,
        InactiveEnterTimestamp=systemd_ts(ended_s),
    )


def test_a_running_oneshot_with_an_empty_active_enter_gets_the_grace(
    tmp_path: Path, deploy: Path
) -> None:
    """Root cause of the 08:21Z self-page: the timer was mid-trigger (next elapse empty until its
    service exits) and the service had no ``ActiveEnterTimestamp`` to compare."""
    result = _verdict(tmp_path, deploy, _gone(last_s=-1), _oneshot(ended_s=-600))
    assert result.outcome == "PASS", result.findings


def test_a_oneshot_that_ended_since_the_trigger_gets_no_grace(tmp_path: Path, deploy: Path) -> None:
    """It ran and finished after the last trigger, yet the timer still has no next elapse."""
    result = _verdict(tmp_path, deploy, _gone(last_s=-300), _oneshot(ended_s=-200))
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_an_idle_oneshot_gets_no_grace_even_before_its_trigger(
    tmp_path: Path, deploy: Path
) -> None:
    result = _verdict(tmp_path, deploy, _gone(last_s=-1), _oneshot(state="inactive"))
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_the_oneshot_grace_is_bounded_from_the_last_trigger(tmp_path: Path, deploy: Path) -> None:
    inside = _verdict(tmp_path, deploy, _gone(last_s=-3590), _oneshot(ended_s=-9000))
    outside = _verdict(tmp_path, deploy, _gone(last_s=-3610), _oneshot(ended_s=-9000))
    assert inside.outcome == "PASS"
    assert {f.kind for f in outside.findings} == {"timer_no_next_elapse"}


def test_equality_with_the_last_trigger_counts_as_after_it(tmp_path: Path, deploy: Path) -> None:
    """A running service that entered the same second as the trigger (or one second before)."""
    same = _verdict(tmp_path, deploy, _gone(last_s=-100), _service(entered_s=-100))
    one_before = _verdict(tmp_path, deploy, _gone(last_s=-100), _service(entered_s=-101))
    two_before = _verdict(tmp_path, deploy, _gone(last_s=-100), _service(entered_s=-102))
    assert same.outcome == one_before.outcome == "PASS"
    assert {f.kind for f in two_before.findings} == {"timer_no_next_elapse"}


def test_a_running_service_with_no_enter_time_and_no_activating_state_gets_no_grace(
    tmp_path: Path, deploy: Path
) -> None:
    result = _verdict(tmp_path, deploy, _gone(last_s=-1), _oneshot(state="active"))
    assert {f.kind for f in result.findings} == {"timer_no_next_elapse"}


def test_a_stale_trigger_is_still_unconditional_for_a_running_oneshot(
    tmp_path: Path, deploy: Path
) -> None:
    stale = _gone(last_s=-(86_400 + TIMER_GRACE_S + 60))
    result = _verdict(tmp_path, deploy, stale, _oneshot())
    # the grace window (1 h) is long over as well, so both are raised; stale is never forgiven
    assert {f.kind for f in result.findings} == {"timer_last_trigger_stale", "timer_no_next_elapse"}
