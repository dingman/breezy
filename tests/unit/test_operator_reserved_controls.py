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
    assert recorded == Decimal("25.00")


def test_a_cost_below_the_position_cap_is_admitted() -> None:
    ledger = DailySpendLedger()
    with _budget(daily="1000.00", position="25.00"):
        recorded = ledger.authorize_order_cost(
            price_usd=Decimal("0.10"), quantity=Decimal(100), now_ns=MIDDAY
        )
    assert recorded == Decimal("10.00")


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
        assert recorded == Decimal("100.00")
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
            cost = ledger.authorize_order_cost(
                price_usd=Decimal("1.00"), quantity=Decimal(10), now_ns=MIDDAY
            )
        except LiveTradingPermissionError:
            return
        with lock:
            granted.append(cost)

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
# R-6e is mechanism only -- no production call site, no order path
# ---------------------------------------------------------------------------


def test_the_mechanism_has_no_production_call_site_yet() -> None:
    """Ships as a library, the shape R-4 and R-6d landed in.

    The consumer is R-7's submit path. Pre-wiring it into ``exec/client.py``
    would put an order-path change inside a policy increment, and R-4's
    standing refusal keeps that path closed regardless. When R-7 lands, this
    test is the one that must be updated deliberately -- an accidental early
    wiring fails it.
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
    assert importers == []
