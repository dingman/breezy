"""R-6e: the two operator-reserved controls, exercised as mechanism.

The invariant that no repo file ASSIGNS either control is proven separately, by
``test_operator_control_assignment_scan.py``. This module proves the mechanism
those controls drive:

* a rolling **UTC calendar-day** USD-notional accumulator, and
* a per-position ceiling whose unit is **USD cost** (``price x quantity``),

both **failing closed** when the operator has not set them.

Every value here arrives through ``tests/unit/operator_control_env.py``, the one
whitelisted seam: it is scoped to a ``with`` block, restores the prior state,
and names no control of its own. A test DRIVING the mechanism is not the repo
assigning a value, and the scan can tell the two apart because every other
route -- a ``monkeypatch.setenv``, a fixture, an ``os.environ`` subscript --
fires.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

import pytest

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailyBudgetExhausted,
    DailySpendLedger,
    operator_max_daily_budget_usd,
    operator_max_position_cost_usd,
    order_cost_usd,
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from breezy.strategy.weather_common.risk import RiskLimits
from tests.unit.operator_control_env import operator_control_env, operator_control_unset

_NS: Final[int] = 1_000_000_000


def _ns(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Nanoseconds since epoch for a UTC wall-clock instant."""
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp()) * _NS


#: 2026-09-02T12:00:00Z -- an ordinary mid-day instant.
MIDDAY: Final[int] = _ns(2026, 9, 2, 12)


@contextmanager
def _budget(*, daily: str, position: str) -> Iterator[None]:
    """Both controls set for the duration of a ``with`` block, then restored."""
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, daily),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, position),
    ):
        yield


# ---------------------------------------------------------------------------
# Fail closed -- the default state of the whole mechanism
# ---------------------------------------------------------------------------


def test_every_order_is_refused_when_neither_control_is_set() -> None:
    ledger = DailySpendLedger()
    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
        pytest.raises(LiveTradingPermissionError),
    ):
        ledger.authorize_order_cost(price_usd=Decimal("0.10"), quantity=Decimal(1), now_ns=MIDDAY)


def test_an_order_is_refused_when_only_the_daily_budget_is_set() -> None:
    ledger = DailySpendLedger()
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00"),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
        pytest.raises(LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(price_usd=Decimal("0.10"), quantity=Decimal(1), now_ns=MIDDAY)
    assert MAX_POSITION_COST_USD_ENV_VAR in str(excinfo.value)


def test_an_order_is_refused_when_only_the_position_cap_is_set() -> None:
    ledger = DailySpendLedger()
    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "25.00"),
        pytest.raises(LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(price_usd=Decimal("0.10"), quantity=Decimal(1), now_ns=MIDDAY)
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in str(excinfo.value)


def test_a_blank_control_is_absence_not_zero() -> None:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "   "),
        pytest.raises(LiveTradingPermissionError) as excinfo,
    ):
        operator_max_daily_budget_usd()
    assert "no default" in str(excinfo.value)


@pytest.mark.parametrize("raw", ["0.00", "-5.00", "5.001", "1e3", "5,00", "five"])
def test_a_malformed_or_nonpositive_control_is_refused(raw: str) -> None:
    with (
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, raw),
        pytest.raises(LiveTradingPermissionError),
    ):
        operator_max_position_cost_usd()


def test_a_well_formed_control_reads_back_as_a_decimal() -> None:
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "250.00"):
        value = operator_max_daily_budget_usd()
    assert type(value) is Decimal
    assert value == Decimal("250.00")


# ---------------------------------------------------------------------------
# The unit: USD cost, not contracts
# ---------------------------------------------------------------------------


def test_order_cost_is_price_times_quantity() -> None:
    assert order_cost_usd(price_usd=Decimal("0.37"), quantity=Decimal(100)) == Decimal("37.00")


def test_order_cost_rounds_up_to_the_cent() -> None:
    """A fraction of a cent of premium consumes a whole cent of budget."""
    assert order_cost_usd(price_usd=Decimal("0.333"), quantity=Decimal(1)) == Decimal("0.34")


def test_the_same_contract_count_costs_differently_at_different_prices() -> None:
    """Why the unit is USD: contracts are not a loss ceiling.

    ``RiskLimits.max_position_contracts`` is a per-strategy sizing tunable in
    CONTRACTS and is a different control entirely -- R-6e neither reads nor
    changes it. At its shipped value the SAME position costs 19x more at $0.95
    than at $0.05, which is precisely why a max-loss ceiling cannot be
    expressed in contracts.
    """
    contracts = Decimal(RiskLimits().max_position_contracts)
    cheap = order_cost_usd(price_usd=Decimal("0.05"), quantity=contracts)
    dear = order_cost_usd(price_usd=Decimal("0.95"), quantity=contracts)
    assert cheap == Decimal("12.50")
    assert dear == Decimal("237.50")


@pytest.mark.parametrize("bad", [0.37, "0.37", 37, None])
def test_a_non_decimal_price_is_refused_by_type_never_by_value(bad: object) -> None:
    with pytest.raises(LiveTradingPermissionError) as excinfo:
        order_cost_usd(price_usd=bad, quantity=Decimal(1))  # type: ignore[arg-type]
    message = str(excinfo.value)
    assert "must be exactly Decimal" in message
    assert str(bad) not in message or (bad is None)


@pytest.mark.parametrize("bad", [Decimal(0), Decimal(-1)])
def test_a_nonpositive_quantity_is_refused(bad: Decimal) -> None:
    with pytest.raises(LiveTradingPermissionError):
        order_cost_usd(price_usd=Decimal("0.50"), quantity=bad)


def test_a_non_finite_amount_is_refused() -> None:
    with pytest.raises(LiveTradingPermissionError):
        order_cost_usd(price_usd=Decimal("NaN"), quantity=Decimal(1))


# ---------------------------------------------------------------------------
# The per-position ceiling
# ---------------------------------------------------------------------------


def test_a_cost_above_the_position_cap_is_refused() -> None:
    ledger = DailySpendLedger()
    with (
        _budget(daily="1000.00", position="25.00"),
        pytest.raises(LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(price_usd=Decimal("0.26"), quantity=Decimal(100), now_ns=MIDDAY)
    assert MAX_POSITION_COST_USD_ENV_VAR in str(excinfo.value)


def test_a_cost_exactly_at_the_position_cap_is_admitted() -> None:
    """The boundary is ``>``, so the operator's stated ceiling is spendable."""
    ledger = DailySpendLedger()
    with _budget(daily="1000.00", position="25.00"):
        recorded = ledger.authorize_order_cost(
            price_usd=Decimal("0.25"), quantity=Decimal(100), now_ns=MIDDAY
        )
    assert recorded.cost == Decimal("25.00")


def test_a_cost_below_the_position_cap_is_admitted() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="1000.00", position="25.00"):
        recorded = ledger.authorize_order_cost(
            price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=MIDDAY
        )
    assert recorded.cost == Decimal("10.00")


def test_a_refused_order_costs_no_budget() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="1000.00", position="25.00"):
        with pytest.raises(LiveTradingPermissionError):
            ledger.authorize_order_cost(
                price_usd=Decimal("0.99"), quantity=Decimal(100), now_ns=MIDDAY
            )
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal(0)


# ---------------------------------------------------------------------------
# The daily accumulator
# ---------------------------------------------------------------------------


def test_the_budget_accumulates_across_orders_within_one_day() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 1)
        )
        ledger.authorize_order_cost(
            price_usd=Decimal("0.30"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 9)
        )
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 2, 23)) == Decimal("70.00")


def test_the_accumulated_total_is_what_refuses_the_next_order() -> None:
    """Not the single order's size: the DAY's spend is the control."""
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.50"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 1)
        )
        ledger.authorize_order_cost(
            price_usd=Decimal("0.45"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 2)
        )
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.authorize_order_cost(
                price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 3)
            )
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 2, 3)) == Decimal("95.00")
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in str(excinfo.value)


def test_daily_budget_exhaustion_raises_the_typed_subclass() -> None:
    """Operator ruling 2026-09-14: the exec client marks a UTC day
    spend-exhausted by exception TYPE, not by re-parsing this (unchanged)
    message -- so the daily-budget branch specifically must raise
    ``DailyBudgetExhausted``, a ``LiveTradingPermissionError`` subclass.
    """
    ledger = DailySpendLedger()
    with (
        _budget(daily="100.00", position="200.00"),
        pytest.raises(DailyBudgetExhausted) as excinfo,
    ):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.50"), quantity=Decimal(300), now_ns=MIDDAY
        )
    assert isinstance(excinfo.value, LiveTradingPermissionError)
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in str(excinfo.value)


def test_a_cost_above_the_position_cap_raises_plain_not_the_daily_subclass() -> None:
    """The per-position ceiling is a distinct control; its refusal must
    never be mistaken for a day-budget exhaustion by the exec client's
    ``except DailyBudgetExhausted`` arm.
    """
    ledger = DailySpendLedger()
    with (
        _budget(daily="1000.00", position="25.00"),
        pytest.raises(LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(price_usd=Decimal("0.26"), quantity=Decimal(100), now_ns=MIDDAY)
    assert type(excinfo.value) is LiveTradingPermissionError
    assert not isinstance(excinfo.value, DailyBudgetExhausted)


def test_a_backwards_clock_denial_raises_plain_not_the_daily_subclass() -> None:
    """The clock-rewind branch shares the daily env-var name in its message
    but is NOT a budget exhaustion and must not mark the day.
    """
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        ledger.authorize_order_cost(price_usd=Decimal("0.10"), quantity=Decimal(1), now_ns=MIDDAY)
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.authorize_order_cost(
                price_usd=Decimal("0.10"), quantity=Decimal(1), now_ns=MIDDAY - _NS
            )
    assert type(excinfo.value) is LiveTradingPermissionError
    assert not isinstance(excinfo.value, DailyBudgetExhausted)


def test_spending_exactly_the_daily_budget_is_admitted() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(price_usd=Decimal("0.60"), quantity=Decimal(100), now_ns=MIDDAY)
        ledger.authorize_order_cost(price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("100.00")


def test_the_budget_resets_at_the_day_boundary() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(
            price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 23, 59)
        )
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 2, 23, 59)) == Decimal("100.00")

        # One minute later, and one UTC day later: the budget is whole again.
        recorded = ledger.authorize_order_cost(
            price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=_ns(2026, 9, 3, 0, 0)
        )
        assert recorded.cost == Decimal("100.00")
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 3, 0, 0)) == Decimal("100.00")


def test_a_previous_day_reports_zero_and_is_never_resurrected() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.50"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 12)
        )
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 1, 12)) == Decimal(0)
        assert ledger.spent_today_usd(now_ns=_ns(2026, 9, 2, 12)) == Decimal("50.00")


def test_a_backwards_clock_is_refused_rather_than_re_granting_budget() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(
            price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=_ns(2026, 9, 2, 12)
        )
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.authorize_order_cost(
                price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=_ns(2026, 9, 1, 12)
            )
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in str(excinfo.value)


def test_two_ledgers_do_not_share_a_budget() -> None:
    """Stated honestly in the module docstring; pinned here so it is not a surprise."""
    first, second = DailySpendLedger(), DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        first.authorize_order_cost(price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=MIDDAY)
        assert second.spent_today_usd(now_ns=MIDDAY) == Decimal(0)


def test_concurrent_authorizations_never_overspend_the_day() -> None:
    """A read-modify-write of the accumulator is the classic double-spend."""
    ledger = DailySpendLedger()
    granted: list[Decimal] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            booking = ledger.authorize_order_cost(
                price_usd=Decimal("1.00"), quantity=Decimal(10), now_ns=MIDDAY
            )
        except LiveTradingPermissionError:
            return
        with lock:
            granted.append(booking.cost)

    with _budget(daily="100.00", position="100.00"):
        threads = [threading.Thread(target=attempt) for _ in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sum(granted, Decimal(0)) <= Decimal("100.00")
        assert ledger.spent_today_usd(now_ns=MIDDAY) == sum(granted, Decimal(0))
    assert len(granted) == 10


# ---------------------------------------------------------------------------
# WHICH day -- UTC, and demonstrably not the per-site climate day
# ---------------------------------------------------------------------------


def test_the_day_is_the_utc_calendar_day() -> None:
    assert utc_day_for_ns(_ns(2026, 9, 2, 0, 0)) == date(2026, 9, 2)
    assert utc_day_for_ns(_ns(2026, 9, 2, 0, 0) - 1) == date(2026, 9, 1)
    assert utc_day_for_ns(_ns(2026, 9, 2, 23, 59)) == date(2026, 9, 2)


def test_the_boundary_is_utc_midnight_not_a_sites_standard_time_midnight() -> None:
    """The contrast that names the choice.

    2026-09-01T23:00Z and 2026-09-02T01:00Z fall in ONE New York climate day
    (local standard time UTC-5: 18:00 and 20:00 on 2026-09-01) and in TWO UTC
    days. The ledger rolls between them, which is what makes "today's spend"
    a single portfolio-wide number rather than one per site.
    """
    before = _ns(2026, 9, 1, 23)
    after = _ns(2026, 9, 2, 1)
    assert utc_day_for_ns(before) != utc_day_for_ns(after)

    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=before)
        assert ledger.spent_today_usd(now_ns=after) == Decimal(0)


def test_the_day_is_never_derived_from_a_float() -> None:
    with pytest.raises(LiveTradingPermissionError) as excinfo:
        utc_day_for_ns(1.787617213e18)  # type: ignore[arg-type]
    assert "never derived from a float" in str(excinfo.value)


@pytest.mark.parametrize("bad", [0, -1])
def test_a_nonpositive_clock_reading_is_refused(bad: int) -> None:
    with pytest.raises(LiveTradingPermissionError):
        utc_day_for_ns(bad)


def test_the_ledger_samples_no_wall_clock_of_its_own() -> None:
    """``now_ns`` is always the caller's INJECTED clock, as in ``safety``."""
    import inspect

    from breezy.adapters.polymarket_us import operator_controls

    source = inspect.getsource(operator_controls)
    for forbidden in ("time.time", "time.monotonic", "datetime.now", "datetime.utcnow"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# R-7-PRE-2 -- release and true-up primitives (library only)
# ---------------------------------------------------------------------------


def test_releasing_a_booking_vacates_the_budget_for_an_identical_later_grant() -> None:
    """Non-vacuity: without the release, the second grant is refused.

    A string of definitive rejects would otherwise burn the daily budget with
    $0 at risk. Releasing the first grant is what makes the identical second
    grant admissible.
    """
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        first = ledger.authorize_order_cost(
            price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=MIDDAY
        )
        with pytest.raises(LiveTradingPermissionError):
            ledger.authorize_order_cost(
                price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=MIDDAY
            )
        ledger.release_booking(first, now_ns=MIDDAY)
        second = ledger.authorize_order_cost(
            price_usd=Decimal("1.00"), quantity=Decimal(100), now_ns=MIDDAY
        )
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("100.00")
        assert second.booking_id != first.booking_id


def test_a_booking_can_be_released_at_most_once() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="100.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.release_booking(booking, now_ns=MIDDAY)
        with pytest.raises(LiveTradingPermissionError):
            ledger.release_booking(booking, now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal(0)


def test_a_previous_day_booking_cannot_be_released_against_today() -> None:
    """The day already rolled, the spend is gone -- raise, never silently no-op.

    Reuses the rollover clock fixture (``_ns``) so the UTC day boundary is the
    same one ``test_the_budget_resets_at_the_day_boundary`` exercises.
    """
    ledger = DailySpendLedger()
    grant_ns = _ns(2026, 9, 2, 12)
    next_day_ns = _ns(2026, 9, 3, 0, 0)
    with _budget(daily="100.00", position="100.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.50"), quantity=Decimal(100), now_ns=grant_ns
        )
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.release_booking(booking, now_ns=next_day_ns)
        assert "day already rolled" in str(excinfo.value)
        assert ledger.spent_today_usd(now_ns=grant_ns) == Decimal("50.00")
        assert ledger.spent_today_usd(now_ns=next_day_ns) == Decimal(0)


def test_release_never_takes_spent_below_zero() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        first = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        second = ledger.authorize_order_cost(
            price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.release_booking(first, now_ns=MIDDAY)
        ledger.release_booking(second, now_ns=MIDDAY)
        spent = ledger.spent_today_usd(now_ns=MIDDAY)
        assert spent == Decimal(0)
        assert spent >= Decimal(0)
        with pytest.raises(LiveTradingPermissionError):
            ledger.release_booking(first, now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal(0)


def test_true_up_to_a_smaller_cost_lowers_spent_today() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("40.00")
        ledger.true_up_booking(booking, filled_cost_usd=Decimal("25.00"), now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("25.00")


def test_true_up_above_the_booking_raises() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.true_up_booking(booking, filled_cost_usd=Decimal("40.01"), now_ns=MIDDAY)
        assert "accounting error" in str(excinfo.value)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("40.00")


def test_true_up_twice_raises() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.true_up_booking(booking, filled_cost_usd=Decimal("25.00"), now_ns=MIDDAY)
        with pytest.raises(LiveTradingPermissionError):
            ledger.true_up_booking(booking, filled_cost_usd=Decimal("10.00"), now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("25.00")


def test_true_up_after_release_raises() -> None:
    """Cross-operation: a released booking is closed; true-up must not reopen it."""
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.release_booking(booking, now_ns=MIDDAY)
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.true_up_booking(booking, filled_cost_usd=Decimal("10.00"), now_ns=MIDDAY)
        assert "already been released" in str(excinfo.value)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal(0)


def test_release_after_true_up_raises() -> None:
    """Cross-operation: a trued-up booking is closed; release must not reopen it."""
    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.true_up_booking(booking, filled_cost_usd=Decimal("25.00"), now_ns=MIDDAY)
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.release_booking(booking, now_ns=MIDDAY)
        assert "already been trued up" in str(excinfo.value)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("25.00")


def test_true_up_of_a_previous_day_booking_raises() -> None:
    ledger = DailySpendLedger()
    grant_ns = _ns(2026, 9, 2, 12)
    next_day_ns = _ns(2026, 9, 3, 0, 0)
    with _budget(daily="100.00", position="100.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.50"), quantity=Decimal(100), now_ns=grant_ns
        )
        with pytest.raises(LiveTradingPermissionError) as excinfo:
            ledger.true_up_booking(booking, filled_cost_usd=Decimal("10.00"), now_ns=next_day_ns)
        assert "day already rolled" in str(excinfo.value)
        assert ledger.spent_today_usd(now_ns=grant_ns) == Decimal("50.00")


def test_day_rollover_prunes_prior_day_bookings() -> None:
    """Rollover drops prior-day rows; the day-rule refusal is unchanged.

    Prior-day bookings are already unreleasable and untrue-up-able, so pruning
    them must not change the error a caller sees. After the first grant of the
    new day, none of the three containers still holds a prior-day id.
    """
    ledger = DailySpendLedger()
    grant_ns = _ns(2026, 9, 2, 12)
    next_day_ns = _ns(2026, 9, 3, 0, 0)
    with _budget(daily="100.00", position="100.00"):
        open_booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.20"), quantity=Decimal(100), now_ns=grant_ns
        )
        released = ledger.authorize_order_cost(
            price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=grant_ns
        )
        trued = ledger.authorize_order_cost(
            price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=grant_ns
        )
        ledger.release_booking(released, now_ns=grant_ns)
        ledger.true_up_booking(trued, filled_cost_usd=Decimal("5.00"), now_ns=grant_ns)
        prior_ids = {open_booking.booking_id, released.booking_id, trued.booking_id}

        with pytest.raises(LiveTradingPermissionError) as release_before:
            ledger.release_booking(open_booking, now_ns=next_day_ns)
        with pytest.raises(LiveTradingPermissionError) as true_up_before:
            ledger.true_up_booking(
                open_booking, filled_cost_usd=Decimal("1.00"), now_ns=next_day_ns
            )
        release_error = str(release_before.value)
        true_up_error = str(true_up_before.value)
        assert "day already rolled" in release_error
        assert "day already rolled" in true_up_error

        today = ledger.authorize_order_cost(
            price_usd=Decimal("0.30"), quantity=Decimal(100), now_ns=next_day_ns
        )

        with pytest.raises(LiveTradingPermissionError) as release_after:
            ledger.release_booking(open_booking, now_ns=next_day_ns)
        with pytest.raises(LiveTradingPermissionError) as true_up_after:
            ledger.true_up_booking(
                open_booking, filled_cost_usd=Decimal("1.00"), now_ns=next_day_ns
            )
        assert str(release_after.value) == release_error
        assert str(true_up_after.value) == true_up_error

        assert prior_ids.isdisjoint(ledger._bookings)
        assert prior_ids.isdisjoint(ledger._released_ids)
        assert prior_ids.isdisjoint(ledger._trued_up_ids)
        assert today.booking_id in ledger._bookings
        today_day = utc_day_for_ns(next_day_ns)
        assert all(booking.day == today_day for booking in ledger._bookings.values())


def test_true_up_and_authorize_share_the_rounding_helper() -> None:
    """Pin by identity: true-up rounds through the same helper the cap uses."""
    import inspect

    from breezy.adapters.polymarket_us import operator_controls as oc

    true_up = DailySpendLedger.true_up_booking  # AttributeError on HEAD
    helper = oc._round_cost_up_to_cent  # AttributeError until the helper is extracted
    assert inspect.getclosurevars(oc.order_cost_usd).globals["_round_cost_up_to_cent"] is helper
    assert inspect.getclosurevars(true_up).globals["_round_cost_up_to_cent"] is helper

    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="50.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.40"), quantity=Decimal(100), now_ns=MIDDAY
        )
        ledger.true_up_booking(booking, filled_cost_usd=Decimal("10.001"), now_ns=MIDDAY)
        assert ledger.spent_today_usd(now_ns=MIDDAY) == helper(Decimal("10.001"))
        assert helper(Decimal("10.001")) == Decimal("10.01")


def test_authorize_returns_a_frozen_booking_record() -> None:
    import dataclasses

    from breezy.adapters.polymarket_us.operator_controls import SpendBooking

    ledger = DailySpendLedger()
    with _budget(daily="100.00", position="25.00"):
        booking = ledger.authorize_order_cost(
            price_usd=Decimal("0.25"), quantity=Decimal(100), now_ns=MIDDAY
        )
    assert type(booking) is SpendBooking
    assert booking.cost == Decimal("25.00")
    assert booking.day == utc_day_for_ns(MIDDAY)
    assert type(booking.booking_id) is int
    assert booking.booking_id > 0
    assert dataclasses.is_dataclass(booking) and booking.__dataclass_params__.frozen


def test_module_docstring_states_the_fee_floor_precondition() -> None:
    from breezy.adapters.polymarket_us import operator_controls

    assert (
        "R-8 does not proceed until the venue's minimum taker fee is measured and "
        "`fees.py` models it; until then the per-position cost control "
        "(`operator_max_position_cost_usd()`) is cost-BEFORE-fee and the operator "
        "sizes accordingly."
    ) in (operator_controls.__doc__ or "")


# ---------------------------------------------------------------------------
# R-6e is mechanism only -- no production call site, no order path
# ---------------------------------------------------------------------------


def test_the_mechanism_has_no_production_call_site_yet() -> None:
    """Ships as a library, the shape R-4 and R-6d landed in.

    R-7's submit path (``factories.py``) is one consumer. CRH enablement
    step 8's sealed order-submission permit (``runtime/order_enablement.py``,
    A3) is a second: ``issue`` reads both operator caps present-and-positive
    through the same two accessor functions, before any ledger booking
    exists. WIDENED, not relaxed (L-12) -- a THIRD importer arriving here
    undeclared is still the accidental-wiring signal this test exists to
    catch. Third, declared 2026-09-07: the operator's value-free presence /
    file validator ``scripts/operator/print_operator_controls.py`` imports the
    inventory tuple to derive the control names at runtime; it reads, never
    assigns (layers A-D and ``find_environ_mutations`` still police it).
    Fourth, declared 2026-09-10 (operator ruling of that date):
    ``safety.issue_live_trading_permit`` reads the same two accessors to
    derive the three session ceilings when those env vars are absent. It
    never writes them.
    Fifth, declared 2026-09-14 (S0, plan rev 3 R3-1): ``exec/client.py``
    imports ``utc_day_for_ns`` to compute the UTC calendar day for its
    boot-time durable-fill spend seed. It reads no control value -- see
    ``test_the_seed_never_reads_an_operator_control_value``.
    Sixth, declared 2026-09-14 (operator ruling of that date, daily-budget
    day stop): ``strategy.current_rung_hold.continuous_strategy`` imports
    ``utc_day_for_ns`` to compute the UTC day for the strategy's own
    ``TrialDayLatch.is_day_budget_exhausted`` read -- it reads no control
    value either, only the day boundary the exec client's marker key already
    uses.
    Seventh, declared 2026-09-21 (AUD-04, portfolio ROI report): the OFFLINE,
    read-only `scripts/analysis/portfolio_roi_report.py` imports ONE pure
    symbol, `_round_cost_up_to_cent`, to quantise `cost + fee` per ledger fill
    into capital-deployed, so the report cannot round differently from the live
    cap arithmetic and the ledger true-up (AUD-04 §6 D4). It imports no money
    accessor, reads no operator value, constructs no ledger, and runs in a
    `Type=oneshot` outside the node -- the same pure-helper class as the exec
    client's and the strategy's `utc_day_for_ns` rows above. This scan is a
    SUBSTRING scan, so the module is also matched by that script's explanatory
    docstring citations; those are documentation, not calls.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    importers = sorted(
        path.relative_to(repo_root).as_posix()
        for root in ("src", "scripts")
        for path in (repo_root / root).rglob("*.py")
        if "__pycache__" not in path.parts
        and "operator_controls" in path.read_text(encoding="utf-8")
        and path.name != "operator_controls.py"
    )
    assert importers == [
        "scripts/analysis/portfolio_roi_report.py",
        "scripts/operator/print_operator_controls.py",
        "src/breezy/adapters/polymarket_us/exec/client.py",
        "src/breezy/adapters/polymarket_us/factories.py",
        "src/breezy/adapters/polymarket_us/safety.py",
        "src/breezy/runtime/order_enablement.py",
        "src/breezy/strategy/current_rung_hold/continuous_strategy.py",
    ]


# ---------------------------------------------------------------------------
# S0 (plan rev 3, R3-1) -- seed_spent: booking prior spend at boot
# ---------------------------------------------------------------------------


def test_seed_spent_books_the_figure_into_a_fresh_days_accumulator() -> None:
    """A never-yet-authorized ledger accepts a boot-time seed for today."""
    ledger = DailySpendLedger()
    today = utc_day_for_ns(MIDDAY)
    ledger.seed_spent(day=today, spent_usd=Decimal("3.00"), now_ns=MIDDAY)
    assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("3.00")


def test_seed_spent_is_a_no_op_the_second_time_in_one_process() -> None:
    """A second `_connect()` in the same process must not double-book."""
    ledger = DailySpendLedger()
    today = utc_day_for_ns(MIDDAY)
    ledger.seed_spent(day=today, spent_usd=Decimal("3.00"), now_ns=MIDDAY)
    ledger.seed_spent(day=today, spent_usd=Decimal("3.00"), now_ns=MIDDAY)
    assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("3.00")


def test_seed_spent_never_lowers_an_already_higher_in_memory_total() -> None:
    """A real order authorized between the walk and the seed call must never
    be clobbered back down by a smaller durable figure."""
    ledger = DailySpendLedger()
    today = utc_day_for_ns(MIDDAY)
    with _budget(daily="100.00", position="100.00"):
        ledger.authorize_order_cost(price_usd=Decimal("5.00"), quantity=Decimal(1), now_ns=MIDDAY)
    ledger.seed_spent(day=today, spent_usd=Decimal("3.00"), now_ns=MIDDAY)
    assert ledger.spent_today_usd(now_ns=MIDDAY) == Decimal("5.00")


def test_seed_spent_refuses_a_negative_or_non_decimal_figure() -> None:
    ledger = DailySpendLedger()
    today = utc_day_for_ns(MIDDAY)
    with pytest.raises(LiveTradingPermissionError):
        ledger.seed_spent(day=today, spent_usd=Decimal("-1.00"), now_ns=MIDDAY)
    with pytest.raises(LiveTradingPermissionError):
        ledger.seed_spent(day=today, spent_usd=3.0, now_ns=MIDDAY)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AUD-04 -- close the blanket-admission gap in the "Seventh, declared
# 2026-09-21" row above: admitting the FILE into the pin means the pin alone
# no longer notices WHICH symbol it imports. Pin the import surface itself.
# ---------------------------------------------------------------------------


def test_portfolio_roi_report_imports_only_the_cent_rounding_helper() -> None:
    """A future edit importing a cap ACCESSOR from this file must trip.

    The "Seventh" row above admits the whole file to the substring/import
    scans on the strength of ONE pure symbol, `_round_cost_up_to_cent`. That
    admission is blanket at the file level: it says nothing about which name
    is imported, so a later edit that also imports, say,
    `operator_max_daily_budget_usd` from the SAME module would satisfy both
    pins without tripping either. This test closes that gap directly: it
    parses the script with `ast` and asserts the exact set of names imported
    from `breezy.adapters.polymarket_us.operator_controls` is precisely
    `{"_round_cost_up_to_cent"}` -- no more, no fewer -- and that the module is
    never imported as a whole (no `import ...operator_controls` / aliasing
    form) or accessed via attribute off such an alias.

    Non-vacuity: the assertion is `==` against a non-empty set, so if the
    script ever stops importing the helper altogether, this test fails loudly
    instead of passing vacuously -- the correct response then is to REMOVE
    the "Seventh" pin rows above and in the readonly-guard pin, not to weaken
    this assertion.
    """
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "analysis" / "portfolio_roi_report.py"
    source = script_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script_path))

    module_name = "breezy.adapters.polymarket_us.operator_controls"
    imported_names: set[str] = set()
    whole_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    whole_module_aliases.add(alias.asname or alias.name)

    assert not whole_module_aliases, (
        "portfolio_roi_report.py must never `import "
        f"{module_name}` as a whole module; found alias(es) {whole_module_aliases}"
    )
    for alias_name in whole_module_aliases:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == alias_name
            ):
                raise AssertionError(
                    "portfolio_roi_report.py must never access "
                    f"`{alias_name}.{node.attr}` -- only the direct "
                    "`_round_cost_up_to_cent` import is admitted"
                )

    assert imported_names, (
        "portfolio_roi_report.py no longer imports anything from "
        f"{module_name} -- REMOVE the 'Seventh' pin row above and the "
        "matching AUD-04 row in test_polymarket_us_readonly_guard.py rather "
        "than leaving this assertion vacuous"
    )
    assert imported_names == {"_round_cost_up_to_cent"}
