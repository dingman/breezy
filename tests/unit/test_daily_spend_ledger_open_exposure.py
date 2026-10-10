"""EXEC-PAR WP3 -- the daily-spend ledger's open-exposure API (inert).

Nothing in the exec client calls these methods yet. The properties are
BUY-only (exits are never registered, see ``test_register_open_exposure_refuses_sell``)
and round BOTH sides cent-up identically.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from breezy.adapters.polymarket_us import operator_controls
from breezy.adapters.polymarket_us.operator_controls import (
    COST_BUDGET_BUCKET_ABOVE_SENTINEL,
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailyBudgetExhausted,
    DailySpendLedger,
    OpenExposureBoundExceeded,
    SpendBooking,
)
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from tests.unit.operator_control_env import operator_control_env, operator_control_unset

_NS: Final[int] = 1_000_000_000


def _ns(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp()) * _NS


D1_MIDDAY: Final[int] = _ns(2026, 9, 2, 12)
D1_LATE: Final[int] = _ns(2026, 9, 2, 23, 59, 59)
D2_EARLY: Final[int] = _ns(2026, 9, 3, 0, 0, 1)
D2_MIDDAY: Final[int] = _ns(2026, 9, 3, 12)
D2_LATE: Final[int] = _ns(2026, 9, 3, 23, 0)
ZERO: Final = Decimal(0)


@contextmanager
def _budget(*, daily: str = "1000.00", position: str = "1000.00") -> Iterator[None]:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
    ):
        yield


def _auth(ledger: DailySpendLedger, cost: str, now_ns: int) -> SpendBooking:
    return ledger.authorize_order_cost(price_usd=Decimal(cost), quantity=Decimal(1), now_ns=now_ns)


def _register(
    ledger: DailySpendLedger,
    key: str,
    notional: str | None,
    *,
    booking: SpendBooking | None = None,
    partial: str = "0",
    now_ns: int = D1_MIDDAY,
    side: str = "BUY",
) -> None:
    ledger.register_open_exposure(
        key,
        None if notional is None else Decimal(notional),
        booking=booking,
        seeded_partial_usd=Decimal(partial),
        side=side,
        now_ns=now_ns,
    )


def _settle(
    ledger: DailySpendLedger,
    key: str,
    *,
    booking: SpendBooking | None = None,
    realized: str | None = None,
    fill_ts_ns: int | None = None,
    now_ns: int = D1_MIDDAY,
) -> bool:
    return ledger.settle(
        key,
        booking=booking,
        realized_usd=None if realized is None else Decimal(realized),
        fill_ts_ns=fill_ts_ns,
        now_ns=now_ns,
    )


# ---------------------------------------------------------------------------
# settle: same-day live bookings delegate to the existing bodies
# ---------------------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(
    cost_cents=st.integers(min_value=1, max_value=50_000),
    realized_milli_cents=st.integers(min_value=0, max_value=1_000_000),
    release=st.booleans(),
)
def test_settle_same_day_equals_true_up_and_release(
    cost_cents: int, realized_milli_cents: int, release: bool
) -> None:
    cost = Decimal(cost_cents) / 100
    realized = min(Decimal(realized_milli_cents) / 100_000, cost)
    with _budget():
        direct, via_settle = DailySpendLedger(), DailySpendLedger()
        b1 = _auth(direct, str(cost), D1_MIDDAY)
        b2 = _auth(via_settle, str(cost), D1_MIDDAY)
        _register(via_settle, "k", str(cost), booking=b2)
        if release:
            direct.release_booking(b1, now_ns=D1_MIDDAY)
            assert _settle(via_settle, "k", booking=b2, now_ns=D1_MIDDAY) is True
        else:
            direct.true_up_booking(b1, filled_cost_usd=realized, now_ns=D1_MIDDAY)
            assert (
                _settle(via_settle, "k", booking=b2, realized=str(realized), now_ns=D1_MIDDAY)
                is True
            )
        assert via_settle.spent_today_usd(now_ns=D1_MIDDAY) == direct.spent_today_usd(
            now_ns=D1_MIDDAY
        )
        assert not via_settle.has_open_exposure("k")


def test_settle_same_day_unknown_or_double_booking_still_raises() -> None:
    with _budget():
        ledger = DailySpendLedger()
        trued = _auth(ledger, "5.00", D1_MIDDAY)
        released = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "t", "5.00", booking=trued)
        _register(ledger, "r", "5.00", booking=released)
        ledger.true_up_booking(trued, filled_cost_usd=Decimal("1.00"), now_ns=D1_MIDDAY)
        ledger.release_booking(released, now_ns=D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="trued up"):
            _settle(ledger, "t", booking=trued, realized="1.00")
        with pytest.raises(LiveTradingPermissionError, match="released"):
            _settle(ledger, "r", booking=released)
        foreign = _auth(DailySpendLedger(), "5.00", D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="not known"):
            _register(ledger, "f", "5.00", booking=foreign)
        # the failed settles left both entries registered
        assert ledger.has_open_exposure("t") and ledger.has_open_exposure("r")


def test_settle_unregistered_key_with_no_booking_is_noop_false() -> None:
    with _budget():
        ledger = DailySpendLedger()
        _auth(ledger, "5.00", D1_MIDDAY)
        assert _settle(ledger, "nope", realized="1.00", fill_ts_ns=D1_MIDDAY) is False
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY) == Decimal("5.00")
        assert ledger.cross_day_settles_total == 0


def test_settle_unregistered_key_carrying_a_booking_raises() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="unregistered"):
            _settle(ledger, "nope", booking=booking, realized="1.00")
        ledger.release_booking(booking, now_ns=D1_MIDDAY)  # booking still intact


def test_settle_is_atomic_on_raise() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=booking)
        ledger.mark_ambiguous("k")
        with pytest.raises(LiveTradingPermissionError, match="more than authorized"):
            _settle(ledger, "k", booking=booking, realized="5.01")
        with pytest.raises(LiveTradingPermissionError, match="does not match"):
            _settle(ledger, "k", booking=None, realized="1.00")
        with pytest.raises(LiveTradingPermissionError, match="exactly Decimal"):
            ledger.settle(
                "k",
                booking=booking,
                realized_usd=1.0,  # type: ignore[arg-type]
                fill_ts_ns=None,
                now_ns=D1_MIDDAY,
            )
        assert ledger.has_open_exposure("k")
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY) == Decimal("5.00")
        assert ledger.ambiguous_open_total() == Decimal("5.00")
        assert _settle(ledger, "k", booking=booking, realized="2.00") is True
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY) == Decimal("2.00")


def test_public_true_up_and_release_wrappers_unchanged() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="exactly SpendBooking"):
            ledger.release_booking("x", now_ns=D1_MIDDAY)  # type: ignore[arg-type]
        with pytest.raises(LiveTradingPermissionError, match="exactly Decimal"):
            ledger.true_up_booking(booking, filled_cost_usd=1.0, now_ns=D1_MIDDAY)  # type: ignore[arg-type]
        with pytest.raises(LiveTradingPermissionError, match="must not be negative"):
            ledger.true_up_booking(booking, filled_cost_usd=Decimal(-1), now_ns=D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="more than authorized"):
            ledger.true_up_booking(booking, filled_cost_usd=Decimal("5.001"), now_ns=D1_MIDDAY)
        assert ledger.true_up_booking(
            booking, filled_cost_usd=Decimal("1.001"), now_ns=D1_MIDDAY
        ) == Decimal("1.01")
        with pytest.raises(LiveTradingPermissionError, match="trued up"):
            ledger.true_up_booking(booking, filled_cost_usd=Decimal(1), now_ns=D1_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="clock moved backwards"):
            ledger.release_booking(booking, now_ns=D1_MIDDAY - 1)
        # the public wrappers delegate to the locked bodies
        assert hasattr(ledger, "_true_up_locked") and hasattr(ledger, "_release_locked")


def test_prior_day_booking_still_not_releasable_via_public_methods() -> None:
    with _budget():
        ledger = DailySpendLedger()
        old = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=old)
        _auth(ledger, "1.00", D2_MIDDAY)  # rolls the day
        with pytest.raises(LiveTradingPermissionError, match="previous UTC day"):
            ledger.release_booking(old, now_ns=D2_MIDDAY)
        with pytest.raises(LiveTradingPermissionError, match="previous UTC day"):
            ledger.true_up_booking(old, filled_cost_usd=Decimal(1), now_ns=D2_MIDDAY)
        # ... but the registry settles it
        assert _settle(ledger, "k", booking=old, realized="2.00", fill_ts_ns=D2_MIDDAY)


# ---------------------------------------------------------------------------
# concurrency, midnight and clocks
# ---------------------------------------------------------------------------


def test_concurrent_authorize_during_post_await_does_not_break_true_up() -> None:
    with _budget():
        ledger = DailySpendLedger()
        first = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "a", "5.00", booking=first)
        _auth(ledger, "3.00", D1_MIDDAY + 10 * _NS)  # another task, fresher clock
        assert _settle(ledger, "a", booking=first, realized="2.00", now_ns=D1_MIDDAY) is True
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY + 10 * _NS) == Decimal("5.00")


def test_concurrent_authorize_during_post_await_crossing_midnight_settles_via_registry() -> None:
    with _budget():
        ledger = DailySpendLedger()
        first = _auth(ledger, "5.00", D1_LATE)
        _register(ledger, "a", "5.00", booking=first, now_ns=D1_LATE)
        _auth(ledger, "3.00", D2_EARLY)  # rolls the day while "a" is awaiting its POST
        assert ledger.uncharged_open_total() == Decimal("5.00")
        # the stale task settles with its pre-midnight clock; the fill landed after midnight
        assert (
            _settle(
                ledger, "a", booking=first, realized="2.00", fill_ts_ns=D2_EARLY, now_ns=D1_LATE
            )
            is True
        )
        assert ledger.spent_today_usd(now_ns=D2_EARLY) == Decimal("5.00")
        assert ledger.uncharged_open_total() == ZERO
        assert ledger.cross_day_settles_total == 1


def test_settle_tolerates_stale_now_ns_never_raises_clock_backwards() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY + 100 * _NS)
        _register(ledger, "k", "5.00", booking=booking, now_ns=D1_MIDDAY + 100 * _NS)
        assert _settle(ledger, "k", booking=booking, realized="1.00", now_ns=1) is True
        assert _settle(ledger, "k", now_ns=1) is False
        with pytest.raises(LiveTradingPermissionError, match="exactly int"):
            ledger.settle("k", booking=None, realized_usd=None, fill_ts_ns=None, now_ns=1.5)  # type: ignore[arg-type]


def test_settle_over_cost_same_day_still_raises() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=booking)
        with pytest.raises(LiveTradingPermissionError, match="more than authorized"):
            _settle(ledger, "k", booking=booking, realized="5.02", fill_ts_ns=D1_MIDDAY)
        assert ledger.has_open_exposure("k")


# ---------------------------------------------------------------------------
# day roll
# ---------------------------------------------------------------------------


def test_open_exposure_survives_day_roll_as_uncharged() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=booking)
        assert ledger.uncharged_open_total() == ZERO  # charged: it is inside spent
        _auth(ledger, "1.00", D2_MIDDAY)
        assert ledger.has_open_exposure("k")
        assert ledger.uncharged_open_total() == Decimal("5.00")
        assert ledger.spent_today_usd(now_ns=D2_MIDDAY) == Decimal("1.00")


def test_settle_after_roll_before_next_authorize() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=booking)
        assert _settle(
            ledger, "k", booking=booking, realized="2.00", fill_ts_ns=D2_MIDDAY, now_ns=D2_MIDDAY
        )
        assert ledger.spent_today_usd(now_ns=D2_MIDDAY) == Decimal("2.00")
        # the settle's roll is not undone by a stale authorize
        with pytest.raises(LiveTradingPermissionError, match="clock moved backwards"):
            _auth(ledger, "1.00", D1_MIDDAY)
        assert ledger.spent_today_usd(now_ns=D2_MIDDAY) == Decimal("2.00")


@pytest.mark.parametrize(
    ("fill_ts", "partial", "realized", "added"),
    [
        (D2_MIDDAY, "0", "4.00", "4.00"),
        (D2_MIDDAY, "1.50", "4.00", "2.50"),
        (D2_MIDDAY, "4.00", "4.00", "0.00"),
        (D2_MIDDAY, "5.00", "4.00", "0.00"),
        (D1_MIDDAY, "0", "4.00", "0.00"),
        (None, "0", "4.00", "0.00"),
    ],
)
def test_settle_uncharged_adds_realized_minus_partial_iff_ts_event_day_is_today(
    fill_ts: int | None, partial: str, realized: str, added: str
) -> None:
    with _budget():
        ledger = DailySpendLedger()
        _register(ledger, "k", "9.00", partial=partial, now_ns=D2_MIDDAY)
        assert _settle(ledger, "k", realized=realized, fill_ts_ns=fill_ts, now_ns=D2_MIDDAY)
        assert ledger.spent_today_usd(now_ns=D2_MIDDAY) == Decimal(added)


def test_settle_uncharged_without_realized_adds_nothing() -> None:
    with _budget():
        ledger = DailySpendLedger()
        _register(ledger, "k", "9.00", now_ns=D2_MIDDAY)
        assert _settle(ledger, "k", fill_ts_ns=D2_MIDDAY, now_ns=D2_MIDDAY)
        assert ledger.spent_today_usd(now_ns=D2_MIDDAY) == ZERO


def test_cross_day_settles_counter() -> None:
    with _budget():
        ledger = DailySpendLedger()
        same = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "same", "5.00", booking=same)
        _settle(ledger, "same", booking=same, realized="1.00")
        assert ledger.cross_day_settles_total == 0
        old = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "old", "5.00", booking=old)
        _register(ledger, "unc", "5.00", now_ns=D2_MIDDAY)
        _settle(ledger, "old", booking=old, realized="1.00", fill_ts_ns=D2_MIDDAY, now_ns=D2_MIDDAY)
        _settle(ledger, "unc", realized="1.00", fill_ts_ns=D2_MIDDAY, now_ns=D2_MIDDAY)
        assert ledger.cross_day_settles_total == 2
        _settle(ledger, "missing", now_ns=D2_MIDDAY)
        assert ledger.cross_day_settles_total == 2


# ---------------------------------------------------------------------------
# exactly-once properties (BUY only, cent-up both sides)
# ---------------------------------------------------------------------------


_ORDER = st.tuples(
    st.integers(min_value=1, max_value=2_000),  # authorized cost, cents
    st.integers(min_value=0, max_value=2_000),  # realized cents (clamped to cost)
    st.booleans(),  # authorized on D1 (else D2)
    st.booleans(),  # fill ts on D2 (else D1; forced D2 if authorized on D2)
    st.booleans(),  # settle with a stale (D1) clock
)


@settings(max_examples=80, deadline=None)
@given(orders=st.lists(_ORDER, min_size=0, max_size=8), data=st.data())
def test_in_process_spend_equals_seed_after_restart(
    orders: list[tuple[int, int, bool, bool, bool]], data: st.DataObject
) -> None:
    """In-process spend at quiescence equals the seed over the same BUY fills."""
    ordered = sorted(orders, key=lambda o: not o[2])  # D1 authorizations first
    has_d2_auth = any(not o[2] for o in ordered)
    with _budget(daily="1000000.00", position="1000000.00"):
        live = DailySpendLedger()
        bookings = []
        seed_total = ZERO
        for index, (cost_c, real_c, on_d1, fill_d2, _stale) in enumerate(ordered):
            auth_ns = D1_MIDDAY if on_d1 else D2_MIDDAY
            booking = _auth(live, str(Decimal(cost_c) / 100), auth_ns)
            _register(
                live, f"k{index}", str(Decimal(cost_c) / 100), booking=booking, now_ns=auth_ns
            )
            bookings.append(booking)
            realized = Decimal(min(real_c, cost_c)) / 100
            if fill_d2 or not on_d1:
                seed_total += realized
        for index in data.draw(st.permutations(range(len(ordered)))):
            cost_c, real_c, on_d1, fill_d2, stale = ordered[index]
            realized = Decimal(min(real_c, cost_c)) / 100
            fill_ts = D2_MIDDAY if (fill_d2 or not on_d1) else D1_MIDDAY
            assert _settle(
                live,
                f"k{index}",
                booking=bookings[index],
                realized=str(realized),
                fill_ts_ns=fill_ts,
                # a fill stamped D2 cannot be settled by a clock that never saw D2
                now_ns=D1_MIDDAY if stale and (has_d2_auth or fill_ts == D1_MIDDAY) else D2_LATE,
            )
        restarted = DailySpendLedger()
        restarted.seed_spent(
            day=datetime(2026, 9, 3, tzinfo=UTC).date(), spent_usd=seed_total, now_ns=D2_LATE
        )
        assert live.spent_today_usd(now_ns=D2_LATE) == restarted.spent_today_usd(now_ns=D2_LATE)
        assert live.uncharged_open_total() == ZERO
        assert not any(live.has_open_exposure(f"k{i}") for i in range(len(ordered)))


@settings(max_examples=80, deadline=None)
@given(
    rows=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=1_000),  # seeded partial, cents
            st.integers(min_value=0, max_value=1_000),  # extra to the final, cents
        ),
        min_size=1,
        max_size=8,
    ),
    data=st.data(),
)
def test_exactly_once_over_all_interleavings_incl_partials_and_concurrent_tasks(
    rows: list[tuple[int, int]], data: st.DataObject
) -> None:
    """Boot-registered uncharged entries: partials net out, nothing dropped early."""
    with _budget(daily="1000000.00", position="1000000.00"):
        ledger = DailySpendLedger()
        partials = [Decimal(p) / 100 for p, _ in rows]
        finals = [Decimal(p + extra) / 100 for p, extra in rows]
        ledger.seed_spent(
            day=datetime(2026, 9, 3, tzinfo=UTC).date(),
            spent_usd=sum(partials, ZERO),
            now_ns=D2_MIDDAY,
        )
        for i, (partial, final) in enumerate(zip(partials, finals, strict=True)):
            _register(ledger, f"k{i}", str(final - partial), partial=str(partial), now_ns=D2_MIDDAY)
        remaining = sum((f - p for p, f in zip(partials, finals, strict=True)), ZERO)
        assert ledger.uncharged_open_total() == remaining
        for i in data.draw(st.permutations(range(len(rows)))):
            stale = data.draw(st.booleans())
            _settle(
                ledger,
                f"k{i}",
                realized=str(finals[i]),
                fill_ts_ns=D2_MIDDAY,
                now_ns=D1_MIDDAY if stale else D2_LATE,
            )
            remaining -= finals[i] - partials[i]
            assert ledger.uncharged_open_total() == remaining
        assert ledger.spent_today_usd(now_ns=D2_LATE) == sum(finals, ZERO)


# ---------------------------------------------------------------------------
# registry bookkeeping
# ---------------------------------------------------------------------------


def test_unknown_notional_is_per_key() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "u1", None)
    _register(ledger, "u2", None)
    _register(ledger, "known", "3.00")
    assert ledger.unknown_key_count() == 2
    assert ledger.uncharged_open_total() == Decimal("3.00")
    with _budget():
        _settle(ledger, "u1", fill_ts_ns=D1_MIDDAY)
    assert ledger.unknown_key_count() == 1
    assert ledger.abandon_open_exposure("u2") is True
    assert ledger.unknown_key_count() == 0
    with pytest.raises(LiveTradingPermissionError, match="already registered"):
        _register(ledger, "known", "1.00")


def test_abandon_never_raises_and_adds_no_spend() -> None:
    with _budget():
        ledger = DailySpendLedger()
        booking = _auth(ledger, "5.00", D1_MIDDAY)
        _register(ledger, "k", "5.00", booking=booking)
        _register(ledger, "u", None)
        assert ledger.abandon_open_exposure("k") is True
        assert ledger.abandon_open_exposure("k") is False
        assert ledger.abandon_open_exposure("never") is False
        assert ledger.abandon_open_exposure(None) is False  # type: ignore[arg-type]
        assert ledger.abandon_open_exposure("u") is True
        assert ledger.unknown_key_count() == 0
        # a charged booking stays charged (conservative)
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY) == Decimal("5.00")
        assert ledger.uncharged_open_total() == ZERO


def test_register_open_exposure_refuses_sell() -> None:
    ledger = DailySpendLedger()
    with pytest.raises(LiveTradingPermissionError, match="exits"):
        _register(ledger, "exit", "5.00", side="SELL")
    assert not ledger.has_open_exposure("exit")
    assert ledger.uncharged_open_total() == ZERO


def test_mark_ambiguous_unregistered_is_noop() -> None:
    ledger = DailySpendLedger()
    ledger.mark_ambiguous("exit-key")
    assert ledger.ambiguous_open_total() == ZERO
    assert not ledger.has_open_exposure("exit-key")


# ---------------------------------------------------------------------------
# admission invariants and the read-only pre-check
# ---------------------------------------------------------------------------


def test_uncharged_overrun_raises_non_day_stop_type() -> None:
    with _budget(daily="100.00", position="100.00"):
        ledger = DailySpendLedger()
        _auth(ledger, "40.00", D1_MIDDAY)
        _register(ledger, "k", "50.00")
        with pytest.raises(OpenExposureBoundExceeded) as info:
            _auth(ledger, "20.00", D1_MIDDAY)
        assert isinstance(info.value, LiveTradingPermissionError)
        assert not isinstance(info.value, DailyBudgetExhausted)
        _auth(ledger, "10.00", D1_MIDDAY)  # exactly at the bound is admitted


def test_ambiguous_bound_counts_only_marked_ambiguous() -> None:
    with _budget(daily="100.00", position="100.00"):
        ledger = DailySpendLedger(f_adm=Decimal("0.50"))
        _register(ledger, "k", "40.00")
        _auth(ledger, "20.00", D1_MIDDAY)  # 40 uncharged, none marked ambiguous
        ledger.mark_ambiguous("k")
        with pytest.raises(OpenExposureBoundExceeded):
            _auth(ledger, "20.00", D1_MIDDAY)  # 40 + 20 > 50
        _auth(ledger, "10.00", D1_MIDDAY)  # 40 + 10 == 50


def test_defaults_leave_authorize_unbounded_by_ambiguous_exposure() -> None:
    with _budget(daily="100.00", position="100.00"):
        ledger = DailySpendLedger()
        _register(ledger, "k", "40.00")
        ledger.mark_ambiguous("k")
        _auth(ledger, "50.00", D1_MIDDAY)
        assert ledger.breaker_fraction_exceeded() is False


def test_precheck_is_read_only_view_roll() -> None:
    with _budget(daily="100.00", position="100.00"):
        ledger = DailySpendLedger()
        booking = _auth(ledger, "90.00", D1_MIDDAY)
        _register(ledger, "k", "90.00", booking=booking)
        # on D2 the 90 is uncharged exposure and spent is rolled to 0 on the view
        assert ledger.exposure_admission_refusal(Decimal("20.00"), Decimal(1), D2_MIDDAY)
        assert ledger.exposure_admission_refusal(Decimal("10.00"), Decimal(1), D2_MIDDAY) is None
        # nothing was rolled or mutated
        assert ledger.spent_today_usd(now_ns=D1_MIDDAY) == Decimal("90.00")
        assert ledger.uncharged_open_total() == ZERO
        ledger.release_booking(booking, now_ns=D1_MIDDAY)  # still live on D1


def test_precheck_uses_inlock_cost_function_boundary_to_the_cent() -> None:
    price, qty = Decimal("0.3331"), Decimal(3)  # 0.9993 -> cent-up 1.00
    for daily, admitted in (("11.00", True), ("10.99", False)):
        with _budget(daily=daily, position="5.00"):
            ledger = DailySpendLedger()
            _register(ledger, "k", "10.00")
            refusal = ledger.exposure_admission_refusal(price, qty, D1_MIDDAY)
            assert (refusal is None) is admitted
            if admitted:
                ledger.authorize_order_cost(price_usd=price, quantity=qty, now_ns=D1_MIDDAY)
            else:
                with pytest.raises(OpenExposureBoundExceeded):
                    ledger.authorize_order_cost(price_usd=price, quantity=qty, now_ns=D1_MIDDAY)


def test_precheck_defers_to_inlock_day_stop_when_uncharged_positive_and_budget_exhausted() -> None:
    with _budget(daily="100.00", position="100.00"):
        ledger = DailySpendLedger()
        _auth(ledger, "95.00", D1_MIDDAY)
        _register(ledger, "k", "10.00")
        assert ledger.exposure_admission_refusal(Decimal("10.00"), Decimal(1), D1_MIDDAY) is None
        with pytest.raises(DailyBudgetExhausted):
            _auth(ledger, "10.00", D1_MIDDAY)


def test_precheck_reads_budget_only_when_totals_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[int] = []

    def counting_reader() -> Decimal:
        reads.append(1)
        return Decimal("100.00")

    monkeypatch.setattr(operator_controls, "operator_max_daily_budget_usd", counting_reader)
    ledger = DailySpendLedger()
    assert ledger.exposure_admission_refusal(Decimal(1), Decimal(1), D1_MIDDAY) is None
    assert reads == []
    _register(ledger, "u", None)
    assert ledger.exposure_admission_refusal(Decimal(1), Decimal(1), D1_MIDDAY)
    assert reads == []  # unknown notional denies without reading the budget
    ledger.abandon_open_exposure("u")
    _register(ledger, "k", "5.00")
    assert ledger.exposure_admission_refusal(Decimal(1), Decimal(1), D1_MIDDAY) is None
    assert reads == [1]
    assert ledger.breaker_fraction_exceeded() is False  # not ambiguous, f off


def test_precheck_budget_unset_or_clock_rewind_is_deny_no_marker() -> None:
    ledger = DailySpendLedger()
    _register(ledger, "k", "5.00")
    with operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR):
        reason = ledger.exposure_admission_refusal(Decimal(1), Decimal(1), D1_MIDDAY)
    assert isinstance(reason, str) and reason
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in reason
    with _budget():
        later = DailySpendLedger()
        _auth(later, "1.00", D1_MIDDAY)
        rewind = later.exposure_admission_refusal(Decimal(1), Decimal(1), D1_MIDDAY - 1)
        assert isinstance(rewind, str) and "backwards" in rewind
        bad = later.exposure_admission_refusal(Decimal(1), Decimal(1), 0)
        assert isinstance(bad, str)


# ---------------------------------------------------------------------------
# breaker and bucket
# ---------------------------------------------------------------------------


def test_breaker_fraction_exceeded_false_without_reading_when_no_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> Decimal:
        raise AssertionError("budget must not be read")

    monkeypatch.setattr(operator_controls, "operator_max_daily_budget_usd", forbidden)
    ledger = DailySpendLedger(f_breaker=Decimal("0.25"))
    _register(ledger, "k", "50.00")  # open but not AMBIGUOUS
    assert ledger.breaker_fraction_exceeded() is False
    assert ledger.breaker_fraction_exceeded(Decimal("0.01")) is False


def test_breaker_fraction_exceeded_true_on_any_raise() -> None:
    ledger = DailySpendLedger(f_breaker=Decimal("0.25"))
    _register(ledger, "k", "10.00")
    ledger.mark_ambiguous("k")
    with operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR):
        assert ledger.breaker_fraction_exceeded() is True
    with _budget(daily="100.00"):
        assert ledger.breaker_fraction_exceeded() is False  # 10 <= 25
        assert ledger.breaker_fraction_exceeded(Decimal("0.05")) is True  # 10 > 5
        assert ledger.breaker_fraction_exceeded(1.5) is True  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cap", "label"),
    [
        ("2.00", "≤0.02"),
        ("2.01", "0.05"),
        ("5.00", "0.05"),
        ("7.77", "0.10"),
        ("25.00", "0.25"),
        ("50.00", "0.50"),
    ],
)
def test_cost_budget_bucket_returns_label_only(cap: str, label: str) -> None:
    with _budget(daily="100.00", position=cap):
        got = DailySpendLedger().cost_budget_bucket()
    assert got == label
    assert cap not in got and "100" not in got


def test_bucket_label_above_0_50_is_sentinel() -> None:
    with _budget(daily="100.00", position="50.01"):
        assert (
            DailySpendLedger().cost_budget_bucket() == COST_BUDGET_BUCKET_ABOVE_SENTINEL == ">0.50"
        )
    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        pytest.raises(LiveTradingPermissionError),
    ):
        DailySpendLedger().cost_budget_bucket()


# ---------------------------------------------------------------------------
# operator caps stay read-only
# ---------------------------------------------------------------------------


def test_operator_caps_never_assigned() -> None:
    """AST: the ledger module writes no environment and re-literals no cap."""
    tree = ast.parse(inspect.getsource(operator_controls))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and "environ" in ast.unparse(node.value)
        ):
            pytest.fail("environment write in operator_controls")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"setenv", "putenv", "setdefault", "unsetenv"}
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if "budget" not in ast.unparse(target) and "position_cap" not in ast.unparse(
                    target
                ):
                    continue
                # a cap-named binding may only hold what an existing reader returned
                assert isinstance(value, ast.Call)
                assert isinstance(value.func, ast.Name)
                assert value.func.id.startswith("operator_max_")
    controls = {
        c.value
        for c in ast.walk(tree)
        if isinstance(c, ast.Constant)
        and isinstance(c.value, str)
        and c.value.startswith("BREEZY_MAX")
    }
    assert controls == {MAX_DAILY_BUDGET_USD_ENV_VAR, MAX_POSITION_COST_USD_ENV_VAR}
