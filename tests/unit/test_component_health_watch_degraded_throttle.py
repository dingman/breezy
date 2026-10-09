"""AMBIG-LATCH-RESUME Phase B: the degraded alert re-arms on RUNNING and
throttles repeats (T17-T19), with AMBIGUOUS episodes exempt (F3) and the
episode counter that closes the clear-to-resume gap (F6).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` sections 2.3 and 2.3a. Everything here drives
``install_component_degraded_alert`` with real ``ComponentStateChanged`` events
on a real ``MessageBus`` and an explicit ``ts_event`` (the throttle's clock), so
no wall time is involved. The module names no venue.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.identifiers import ClientId, TraderId

from breezy.runtime import component_health_watch as watch
from breezy.runtime.health import AlertPayload

COMPONENT = "POLYMARKET_US"
OTHER = "SOMETHING_ELSE"
HOUR_NS = 60 * 60 * 1_000_000_000
AMBIGUOUS = "ambiguous (rig)"


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _World:
    def __init__(self, **kwargs: Any) -> None:
        self.trader_id = TraderId("BREEZY-THROTTLE-001")
        self.msgbus = MessageBus(trader_id=self.trader_id, clock=LiveClock())
        self.sink = _Sink()
        self.reasons: tuple[str, ...] = ()
        self.clears = 0
        kwargs.setdefault("reasons", lambda: self.reasons)
        self.handler = watch.install_component_degraded_alert(
            self.msgbus, component_id=COMPONENT, sink=self.sink, **kwargs
        )

    def publish(self, state: ComponentState, ts_ns: int, component: str = COMPONENT) -> None:
        self.msgbus.publish(
            topic=f"events.system.{component}",
            msg=ComponentStateChanged(
                trader_id=self.trader_id,
                component_id=ClientId(component),
                component_type="PolymarketUSExecutionClient",
                state=state,
                config={},
                event_id=UUID4(),
                ts_event=ts_ns,
                ts_init=ts_ns,
            ),
        )

    def episode(self, ts_ns: int, reasons: tuple[str, ...]) -> None:
        """RUNNING -> DEGRADED, as a re-armed refusal would publish it."""
        self.publish(ComponentState.RUNNING, ts_ns - 1)
        self.reasons = reasons
        self.publish(ComponentState.DEGRADED, ts_ns)


def _throttle_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if "throttled" in r.getMessage()]


# ---------------------------------------------------------------------------
# T17 / T18: the throttle and its window
# ---------------------------------------------------------------------------


def test_a_repeat_non_ambiguous_episode_inside_the_window_is_throttled_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    world = _World()
    world.episode(10, ("reason A",))
    assert len(world.sink.payloads) == 1
    world.episode(10 + 60 * 1_000_000_000, ("reason A",))
    assert len(world.sink.payloads) == 1, "same set inside the hour: suppressed"
    warnings = _throttle_warnings(caplog)
    assert len(warnings) == 1
    assert "component_degraded alert throttled" in warnings[0].getMessage()


def test_a_repeat_episode_after_the_window_re_alerts_and_the_boundary_is_inclusive() -> None:
    world = _World(renotify_after_ns=1000)
    world.episode(10, ("reason A",))
    world.episode(10 + 999, ("reason A",))
    assert len(world.sink.payloads) == 1, "one nanosecond short of the window: throttled"
    world.episode(10 + 1000 + 5, ("reason A",))
    assert len(world.sink.payloads) == 2
    # the boundary itself (elapsed == window) alerts: suppress iff elapsed < window
    world.episode(10 + 1005 + 1000, ("reason A",))
    assert len(world.sink.payloads) == 3


def test_the_default_window_is_one_hour() -> None:
    assert watch.DEGRADED_ALERT_RENOTIFY_AFTER_NS == HOUR_NS
    world = _World()
    world.episode(10, ("reason A",))
    world.episode(HOUR_NS + 9, ("reason A",))
    assert len(world.sink.payloads) == 1
    world.episode(2 * HOUR_NS + 10, ("reason A",))
    assert len(world.sink.payloads) == 2


# ---------------------------------------------------------------------------
# T19: bypasses, validation, ticks
# ---------------------------------------------------------------------------


def test_a_new_reason_bypasses_the_throttle_and_a_subset_does_not() -> None:
    world = _World()
    world.episode(10, ("reason A", "reason B"))
    world.episode(20, ("reason A",))
    assert len(world.sink.payloads) == 1, "a SUBSET of the last set is throttled"
    world.episode(30, ("reason C",))
    assert len(world.sink.payloads) == 2, "a new reason always alerts"


def test_a_backwards_clock_alerts() -> None:
    world = _World()
    world.episode(10_000, ("reason A",))
    world.episode(5_000, ("reason A",))
    assert len(world.sink.payloads) == 2


def test_a_failing_reader_is_a_new_reason_set() -> None:
    def _boom() -> tuple[str, ...]:
        raise RuntimeError("reader down")

    world = _World(reasons=_boom)
    world.episode(10, ())
    world.episode(20, ())
    assert len(world.sink.payloads) == 2, "REASONS_UNAVAILABLE is never throttled as a repeat"
    assert "unavailable" in world.sink.payloads[0].detail


def test_one_alert_per_episode_and_running_re_arms_for_the_same_component_only() -> None:
    world = _World(renotify_after_ns=1)
    world.reasons = ("reason A",)
    world.publish(ComponentState.DEGRADED, 10)
    world.publish(ComponentState.DEGRADED, 20)
    assert len(world.sink.payloads) == 1, "no re-alert inside one episode"
    world.publish(ComponentState.RUNNING, 25, component=OTHER)
    world.publish(ComponentState.DEGRADED, 30)
    assert len(world.sink.payloads) == 1, "another component's RUNNING does not re-arm"
    world.publish(ComponentState.RUNNING, 35)
    world.publish(ComponentState.DEGRADED, 40)
    assert len(world.sink.payloads) == 2


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_an_invalid_renotify_window_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="renotify_after_ns"):
        _World(renotify_after_ns=bad)


def test_a_tick_is_a_no_op_without_the_ambiguous_readers() -> None:
    world = _World()
    world.reasons = (AMBIGUOUS,)
    world.handler(object())
    assert world.sink.payloads == []
    world2 = _World(ambiguous_reason=AMBIGUOUS)
    world2.reasons = (AMBIGUOUS,)
    world2.handler(object())
    assert world2.sink.payloads == [], "one reader without the other is still a no-op"


# ---------------------------------------------------------------------------
# F3 / F6: AMBIGUOUS is never throttled and every episode is counted
# ---------------------------------------------------------------------------


def _ambiguous_world() -> _World:
    holder: list[_World] = []

    def _clears() -> int:
        return holder[0].clears

    world = _World(ambiguous_reason=AMBIGUOUS, ambiguous_clears=_clears)
    holder.append(world)
    return world


def test_ambiguous_episodes_inside_the_window_each_alert_with_no_throttle_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    world = _ambiguous_world()
    world.episode(10, (AMBIGUOUS,))
    world.clears += 1
    world.episode(20, (AMBIGUOUS,))
    assert len(world.sink.payloads) == 2
    assert _throttle_warnings(caplog) == []


def test_a_tick_emits_one_alert_per_owed_episode_exactly_once() -> None:
    world = _ambiguous_world()
    world.episode(10, (AMBIGUOUS,))
    assert len(world.sink.payloads) == 1
    # two more episodes were added and cleared (and one is present) between ticks
    world.clears += 2
    world.reasons = (AMBIGUOUS,)
    world.handler(object())
    assert len(world.sink.payloads) == 3
    world.handler(object())
    assert len(world.sink.payloads) == 3
    world.clears += 1
    world.reasons = ()
    world.handler(object())
    assert len(world.sink.payloads) == 3, "the clear of an already-alerted episode owes nothing"


def test_a_state_change_for_another_component_is_ignored_even_with_the_readers() -> None:
    world = _ambiguous_world()
    world.reasons = (AMBIGUOUS,)
    world.publish(ComponentState.DEGRADED, 10, component=OTHER)
    assert world.sink.payloads == []
