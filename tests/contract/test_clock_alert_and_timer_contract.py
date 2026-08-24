"""Contract tests pinning `Clock.set_time_alert`/`set_timer` naming and staggering.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run these FIRST on
any version bump: a failure means the platform moved, not that Breezy is wrong.

Breezy's ingest scheduling treats `Clock.next_time_ns(name)` as an armed-ness
predicate ("is a timer/alert with this name currently pending?") and relies on
`override=True` to safely re-arm a named alert without a `cancel_timer` dance
first. It also stacks several `set_timer` calls with a `start_time` offset to
stagger otherwise-identical polling intervals so they do not all fire in the
same tick. Both are pinned here against a `TestClock`, which fires
deterministically on `advance_time` -- no wall-clock sleep, no flakiness.

Scope: `common/component.pyx` `Clock.set_time_alert` (`:316`),
`Clock.set_time_alert_ns` (`TestClock` override `:675`), `Clock.next_time_ns`
(`TestClock` override `:760`), `Clock.cancel_timer` (`TestClock` override
`:764`), and `Clock.set_timer` staggering via `start_time`. No network access,
no live kernel, no disk.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from nautilus_trader.common.component import TestClock

pytestmark = pytest.mark.contract


def _clock() -> TestClock:
    return TestClock()


def _advance(clock: TestClock, to_time_ns: int) -> None:
    for handler in clock.advance_time(to_time_ns=to_time_ns):
        handler.handle()


# ---------------------------------------------------------------------------
# `set_time_alert` / `set_time_alert_ns` naming semantics
# ---------------------------------------------------------------------------


def test_duplicate_alert_name_without_override_raises_key_error() -> None:
    """`common/component.pyx:316` -- `set_time_alert` with an already-armed
    `name` and no `override` argument raises `KeyError`.

    `TestClock.set_time_alert_ns` (`:675`) enforces this via
    `Condition.not_in(name, self.timer_names, ...)`. If this ever becomes a
    silent no-op or a different exception type, Breezy's re-arm logic (which
    catches `KeyError` to detect "already armed, use override instead") would
    stop firing its fallback path.
    """
    clock = _clock()
    clock.set_time_alert_ns(name="A", alert_time_ns=1_000_000_000, callback=lambda evt: None)

    with pytest.raises(KeyError):
        clock.set_time_alert_ns(name="A", alert_time_ns=2_000_000_000, callback=lambda evt: None)


def test_duplicate_alert_name_with_override_replaces_it() -> None:
    """`common/component.pyx:316` -- `override=True` replaces an existing
    alert rather than raising. `next_time_ns` reflects the NEW time, proving
    the old alert was actually replaced and not merely tolerated alongside it.
    """
    clock = _clock()
    clock.set_time_alert_ns(name="B", alert_time_ns=1_000_000_000, callback=lambda evt: None)

    clock.set_time_alert(
        name="B",
        alert_time=clock.utc_now() + timedelta(seconds=5),
        callback=lambda evt: None,
        override=True,
    )

    # The replaced alert's time is ~5s out, not the original 1s -- distinguish
    # "replaced" from "silently ignored" by checking the new value landed.
    assert clock.next_time_ns("B") > 1_000_000_000


def test_allow_past_false_refuses_an_alert_time_already_in_the_past() -> None:
    """`common/component.pyx:316` `allow_past=False` raises rather than
    silently clamping a past `alert_time_ns` to "now" for immediate firing
    (which is the `allow_past=True` default's documented behaviour).

    `TestClock.set_time_alert_ns` (`:675`, validation at `:685`) raises
    `ValueError` -- NOT `KeyError` and NOT the framework's documented past-time
    warning-and-clamp path. If Breezy ever passes `allow_past=False` to guard
    against scheduling a stale alert, catching the wrong exception type here
    would let the bug through uncaught.
    """
    clock = _clock()
    _advance(clock, to_time_ns=10_000_000_000)  # clock must be past t=0 for "past" to mean anything

    with pytest.raises(ValueError, match="was in the past"):
        clock.set_time_alert_ns(
            name="C",
            alert_time_ns=1_000_000_000,  # 9s behind the current 10s
            callback=lambda evt: None,
            allow_past=False,
        )


def test_next_time_ns_returns_zero_for_an_unknown_or_unarmed_name() -> None:
    """`common/component.pyx:295`/`:760` -- `next_time_ns` for a name that was
    never armed (or was armed and has since fired/been cancelled) returns the
    integer `0`, not `None` and not an exception.

    Breezy uses `next_time_ns(name) > 0` as an armed-ness predicate. If a
    future version returned `None` instead, `None > 0` raises `TypeError` in
    Python 3 (loud); if it instead returned a sentinel like `-1` the same
    `> 0` check would still read as "unarmed" by luck rather than by contract.
    Pinning the literal `0` closes both gaps.
    """
    clock = _clock()

    assert clock.next_time_ns("never-armed") == 0


def test_cancel_timer_clears_next_time_ns_back_to_zero() -> None:
    """`common/component.pyx:764` -- `cancel_timer(name)` deletes the alert,
    and `next_time_ns(name)` reverts to `0` (unarmed) rather than retaining
    the cancelled time or raising.
    """
    clock = _clock()
    clock.set_time_alert_ns(name="D", alert_time_ns=1_000_000_000, callback=lambda evt: None)
    assert clock.next_time_ns("D") == 1_000_000_000

    clock.cancel_timer("D")

    assert clock.next_time_ns("D") == 0


# ---------------------------------------------------------------------------
# `set_timer` staggering via `start_time`
# ---------------------------------------------------------------------------


def test_set_timer_start_time_offsets_stagger_the_firing_order() -> None:
    """Three timers sharing one `interval` but given different `start_time`
    offsets fire in OFFSET order, not registration order.

    Registered A (offset 5s), B (offset 9s), C (offset 1s) -- in that order --
    but the FIRST event each timer fires lands at `start_time + interval`
    (10s interval, no `fire_immediately`): C at 11s, A at 15s, B at 19s. So a
    single `advance_time` sweep to 20s delivers them in offset order (C, A,
    B), not registration order (A, B, C). This is the mechanism Breezy relies
    on to desynchronise otherwise-identical per-city polling intervals so they
    do not all wake in the same tick. `event.ts_event` (not
    `clock.timestamp_ns()`, which reflects the clock's final position after
    the whole sweep) is what proves each event carries its own distinct fire
    time rather than all collapsing to the sweep's endpoint.
    """
    clock = _clock()
    fires: list[tuple[int, str]] = []

    def _make_callback(name: str):
        def _callback(event: object) -> None:
            fires.append((event.ts_event, name))  # type: ignore[attr-defined]

        return _callback

    interval = timedelta(seconds=10)
    now = clock.utc_now()
    clock.set_timer(name="A", interval=interval, start_time=now + timedelta(seconds=5), callback=_make_callback("A"))
    clock.set_timer(name="B", interval=interval, start_time=now + timedelta(seconds=9), callback=_make_callback("B"))
    clock.set_timer(name="C", interval=interval, start_time=now + timedelta(seconds=1), callback=_make_callback("C"))

    _advance(clock, to_time_ns=20_000_000_000)

    names_in_fire_order = [name for _, name in fires]
    assert names_in_fire_order == ["C", "A", "B"]
    assert [ts for ts, _ in fires] == [11_000_000_000, 15_000_000_000, 19_000_000_000]
