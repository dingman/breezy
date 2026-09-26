"""FU-8b: a native ``LiveClock`` timer re-polls the two runtime-only alert
surfaces (``install_reconciliation_refusal_alert`` and
``install_stale_intent_alert``) whose handlers today fire only on a
``ComponentStateChanged``. A runtime latch appended between state changes
would otherwise stay unalerted until some unrelated component transitions.

``install_refusal_repoll_timer`` is the ONLY new function. It joins an
already-armed ``Clock`` (real ``TestClock`` here; a real ``LiveClock`` under
``tests/contract/test_refusal_repoll_live_clock_contract.py``) to the handler
closures ``install_reconciliation_refusal_alert``/``install_stale_intent_alert``
already return -- no synthetic ``ComponentStateChanged`` is ever published, and
no new dedupe set is created: both triggers share the SAME closures.

The loop hop (``loop.call_soon_threadsafe``) is faked here with an inline
loop that calls back immediately on the SAME thread -- the genuine
cross-thread hop is proven separately under a real asyncio loop and a real
``LiveClock`` in the contract test above.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock, MessageBus, TestClock
from nautilus_trader.model.identifiers import TraderId

from breezy.runtime.component_health_watch import (
    REFUSAL_REPOLL_INTERVAL,
    REFUSAL_REPOLL_TIMER_NAME,
    install_reconciliation_refusal_alert,
    install_refusal_repoll_timer,
    install_stale_intent_alert,
)
from breezy.runtime.health import AlertPayload

TRADER_ID = TraderId("BREEZY-REPOLL-001")

_NS_PER_S = 1_000_000_000


def _new_bus() -> MessageBus:
    return MessageBus(trader_id=TRADER_ID, clock=LiveClock())


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _InlineLoop:
    """Fakes the surface ``_on_timer`` reads: ``is_closed`` and
    ``call_soon_threadsafe``. Calls the callback INLINE, on the SAME thread,
    because these unit tests run on one thread; the genuine cross-thread hop
    is proven under a real asyncio loop in the contract test file.
    """

    def __init__(self, *, closed: bool = False) -> None:
        self._closed = closed
        self.scheduled: list[tuple[Callable[..., None], tuple[Any, ...]]] = []

    def is_closed(self) -> bool:
        return self._closed

    def call_soon_threadsafe(self, callback: Callable[..., None], *args: Any) -> None:
        self.scheduled.append((callback, args))
        callback(*args)


class _RaisingScheduleLoop:
    """``is_closed`` answers ``False``; ``call_soon_threadsafe`` always raises.

    Models both a generic scheduling failure (test 8) and the specific
    closed-loop race (test 10): ``is_closed()`` is read first and answers
    ``False``, and the loop closes in the gap before the schedule call lands.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, callback: Callable[..., None], *args: Any) -> None:
        del callback, args
        raise self._exc


def _fire(clock: TestClock) -> None:
    """Advance a `TestClock` by exactly one `REFUSAL_REPOLL_INTERVAL` and
    hand every returned `TimeEventHandler` its own `.handle()` call -- the
    same idiom `TestClock.advance_time` documents and
    `test_live_timer_thread_affinity.py::test_testclock_fires_inline_on_the_caller_thread`
    measures: a `TestClock` runs the callback INLINE, on the caller's thread.
    """
    target_ns = clock.timestamp_ns() + int(REFUSAL_REPOLL_INTERVAL.total_seconds() * _NS_PER_S)
    for handler in clock.advance_time(target_ns):
        handler.handle()


class TestArming:
    def test_the_timer_is_armed_on_the_given_clock_at_the_named_interval(self) -> None:
        clock = TestClock()
        t0 = clock.timestamp_ns()

        install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=())

        assert REFUSAL_REPOLL_TIMER_NAME in clock.timer_names
        assert clock.next_time_ns(REFUSAL_REPOLL_TIMER_NAME) == t0 + int(
            REFUSAL_REPOLL_INTERVAL.total_seconds() * _NS_PER_S
        )


class TestEachFire:
    def test_advancing_one_interval_repolls_every_handler_once_in_order(self) -> None:
        order: list[str] = []
        clock = TestClock()
        install_refusal_repoll_timer(
            clock,
            loop=_InlineLoop(),
            handlers=(
                lambda event: order.append("recon"),
                lambda event: order.append("stale"),
            ),
        )

        _fire(clock)

        assert order == ["recon", "stale"]

    def test_advancing_less_than_one_interval_polls_nothing(self) -> None:
        order: list[str] = []
        clock = TestClock()
        install_refusal_repoll_timer(
            clock, loop=_InlineLoop(), handlers=(lambda event: order.append("fired"),)
        )

        half_interval_ns = int(REFUSAL_REPOLL_INTERVAL.total_seconds() * _NS_PER_S) // 2
        handlers = clock.advance_time(clock.timestamp_ns() + half_interval_ns)
        for handler in handlers:
            handler.handle()

        assert order == []


class TestRuntimeLatchesAlertWithoutAStateChange:
    def test_a_runtime_reconciliation_latch_alerts_on_the_next_tick_without_a_state_change(
        self,
    ) -> None:
        """The behavioural RED: still fails if the join polls nothing."""
        sink = _RecordingSink()
        surface: list[dict[str, str]] = []
        clock = TestClock()
        handler = install_reconciliation_refusal_alert(
            _new_bus(), refusals=lambda: tuple(surface), sink=sink
        )
        install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=(handler,))

        surface.append(
            {
                "latch": "resolver_fill_not_booked",
                "subject": "",
                "detail": "RESOLVER_FILL_NOT_BOOKED",
            }
        )
        _fire(clock)
        assert len(sink.payloads) == 1
        assert sink.payloads[0].detail == "RESOLVER_FILL_NOT_BOOKED"

        _fire(clock)
        assert len(sink.payloads) == 1

    def test_a_stale_intent_appearing_mid_run_alerts_on_the_next_tick_without_a_state_change(
        self,
    ) -> None:
        sink = _RecordingSink()
        surface: list[dict[str, str]] = []
        clock = TestClock()
        handler = install_stale_intent_alert(
            _new_bus(), stale_alerts=lambda: tuple(surface), sink=sink
        )
        install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=(handler,))

        surface.append(
            {
                "intent_id": "intent-1",
                "venue_order_id": "vo-1",
                "age_minutes": "16",
                "last_failure_kind": "TIMEOUT",
            }
        )
        _fire(clock)
        assert len(sink.payloads) == 1
        assert sink.payloads[0].severity == "CRITICAL"

        _fire(clock)
        assert len(sink.payloads) == 1


class TestSharedDedupe:
    def test_timer_and_state_change_triggers_share_one_dedupe_in_either_order(self) -> None:
        sink = _RecordingSink()
        surface = [
            {"latch": "positions_read_failed", "subject": "", "detail": "POSITIONS_READ_FAILED"}
        ]
        msgbus = _new_bus()
        clock = TestClock()
        handler = install_reconciliation_refusal_alert(
            msgbus, refusals=lambda: tuple(surface), sink=sink
        )
        install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=(handler,))

        # First trigger: the timer.
        _fire(clock)
        assert len(sink.payloads) == 1

        # Second trigger: the SAME refusal, via the state-change path.
        handler(object())
        assert len(sink.payloads) == 1


class TestFailureContainment:
    def test_a_raising_handler_is_logged_and_neither_blocks_its_sibling_nor_later_ticks(
        self, caplog: Any
    ) -> None:
        fired: list[str] = []

        def _raiser(event: object) -> None:
            raise ValueError("boom")

        clock = TestClock()
        install_refusal_repoll_timer(
            clock,
            loop=_InlineLoop(),
            handlers=(_raiser, lambda event: fired.append("sibling")),
        )

        with caplog.at_level("ERROR"):
            _fire(clock)
        assert fired == ["sibling"]

        fired.clear()
        _fire(clock)
        assert fired == ["sibling"]

    def test_the_timer_callback_never_raises_when_call_soon_threadsafe_raises(
        self, caplog: Any
    ) -> None:
        clock = TestClock()
        install_refusal_repoll_timer(
            clock,
            loop=_RaisingScheduleLoop(RuntimeError("scheduling exploded")),
            handlers=(),
        )

        with caplog.at_level("ERROR"):
            _fire(clock)  # must not raise

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        assert "exception_type=RuntimeError" in errors[0].message
        assert "scheduling exploded" not in errors[0].message

    def test_a_closed_loop_schedules_nothing_and_logs_nothing(self, caplog: Any) -> None:
        clock = TestClock()
        loop = _InlineLoop(closed=True)
        install_refusal_repoll_timer(clock, loop=loop, handlers=(lambda event: None,))

        with caplog.at_level("ERROR"):
            _fire(clock)

        assert loop.scheduled == []
        assert caplog.records == []

    def test_a_loop_closing_between_is_closed_and_schedule_logs_at_most_one_error(
        self, caplog: Any
    ) -> None:
        clock = TestClock()
        install_refusal_repoll_timer(
            clock,
            loop=_RaisingScheduleLoop(RuntimeError("Event loop is closed")),
            handlers=(),
        )

        with caplog.at_level("ERROR"):
            _fire(clock)  # must not raise

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) <= 1


class TestCancel:
    def test_cancel_removes_the_timer_and_is_idempotent(self) -> None:
        clock = TestClock()
        cancel = install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=())

        assert REFUSAL_REPOLL_TIMER_NAME in clock.timer_names
        cancel()
        assert REFUSAL_REPOLL_TIMER_NAME not in clock.timer_names
        cancel()  # idempotent: must not raise


class TestArmingSignals:
    def test_a_duplicate_install_fails_loudly_at_install_not_in_a_callback(self) -> None:
        clock = TestClock()
        install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=())

        with pytest.raises(KeyError):
            install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=())

    def test_arming_writes_one_info_line_naming_the_timer_and_interval(
        self, caplog: Any
    ) -> None:
        clock = TestClock()
        with caplog.at_level("INFO"):
            install_refusal_repoll_timer(clock, loop=_InlineLoop(), handlers=())

        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_records) == 1
        assert REFUSAL_REPOLL_TIMER_NAME in info_records[0].message
        assert "interval_s=60" in info_records[0].message
