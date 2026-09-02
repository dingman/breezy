"""T-4 -- account equity is either OBSERVED, or it is ``None``.

``_equity()`` returned a ``float`` no matter what it had actually seen: the
venue balance when one was in the cache, and otherwise
``config.starting_equity`` -- a fabricated ``10_000.0`` that the risk policy
then sized the equity-fraction cap against, as though somebody had counted
the money. ``float`` cannot express "unobserved"; ``None`` can.

Covers the shared reader
(:func:`breezy.strategy.weather_common.equity.observed_equity`), the
reduce-only refusal note that makes the resulting state visible in an
operator's journal, and the five strategies that delegate to both.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy
from breezy.strategy.cli_settlement_print_lock.strategy import CliSettlementPrintLockStrategy
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.running_extreme_lock.strategy import RunningExtremeLockStrategy
from breezy.strategy.weather_common.equity import (
    REDUCE_ONLY_STATE,
    observed_equity,
    reduce_only_refusal_note,
)
from breezy.strategy.weather_common.risk import EQUITY_NONPOSITIVE, EQUITY_UNOBSERVED

#: The constant `_equity()` used to fabricate. Stated here ONLY so the
#: assertions below fail loudly against the old behaviour rather than
#: silently against some other float.
FABRICATED_EQUITY: Final[float] = 10_000.0

#: Typed `Any` at the parameter, not `type`: these tests call the unbound
#: `_portfolio_snapshot` against a hand-built `self`, which is deliberately
#: not an instance of any of them.
STRATEGY_CLASSES: Final[tuple[type, ...]] = (
    ForecastMispricingStrategy,
    CalibrationMeanReversionStrategy,
    ForecastRevisionStrategy,
    RunningExtremeLockStrategy,
    CliSettlementPrintLockStrategy,
)


# ---------------------------------------------------------------------------
# Doubles. `observed_equity` touches exactly four things: `cache.instrument`,
# `portfolio.account`, `instrument.quote_currency` and
# `account.balance_total(...).as_double()`.
# ---------------------------------------------------------------------------


class _Venue:
    def __init__(self, name: str) -> None:
        self.name = name


class _NtId:
    """Stand-in for an `InstrumentId`: the reader only reads `.venue`."""

    def __init__(self, venue: _Venue) -> None:
        self.venue = venue


class _Instrument:
    def __init__(self, currency: str = "USDC") -> None:
        self.quote_currency = currency


class _Money:
    def __init__(self, amount: float) -> None:
        self._amount = amount

    def as_double(self) -> float:
        return self._amount


class _Account:
    """`balance_total` returns `Money | None` -- NEVER zero for "unknown".

    `nautilus_trader.accounting.accounts.base.Account.balance_total` returns
    `None` when it holds no balance for that currency; a zero would be a
    REPORTED zero balance, which is a different fact.
    """

    def __init__(self, balance: float | None) -> None:
        self._balance = balance

    def balance_total(self, currency: str) -> _Money | None:
        del currency
        return None if self._balance is None else _Money(self._balance)


class _Cache:
    def __init__(self, instrument: _Instrument | None) -> None:
        self._instrument = instrument

    def instrument(self, nt_id: Any) -> _Instrument | None:
        del nt_id
        return self._instrument

    def orders(self, instrument_id: Any = None) -> list[Any]:
        del instrument_id
        return []


class _Portfolio:
    def __init__(self, account: _Account | None) -> None:
        self._account = account

    def account(self, venue: Any) -> _Account | None:
        del venue
        return self._account

    def net_position(self, nt_id: Any) -> float:
        del nt_id
        return 0.0


class _Config:
    """Carries the field T-4 deletes, so nothing here fails for want of it."""

    starting_equity = FABRICATED_EQUITY


class _StrategySelf:
    """The attributes `_portfolio_snapshot` reads, and nothing else.

    The five `_portfolio_snapshot` bodies are byte-identical Python methods
    on Python subclasses of the compiled `Strategy`, so calling one unbound
    against this object exercises the REAL production body without standing
    up a registered node.
    """

    def __init__(self, *, account: _Account | None, instrument: _Instrument | None) -> None:
        self.cache = _Cache(instrument)
        self.portfolio = _Portfolio(account)
        self._nt_ids = {"A": _NtId(_Venue("POLYMARKET_US"))}
        self._risk = None
        self._config = _Config()

    def _equity(self) -> float:
        """POISONED, so the tests below fail on the DEFECT and not on a gap
        in this double.

        `_portfolio_snapshot` used to call a private per-strategy `_equity()`
        that fell back to `config.starting_equity`. Five byte-identical
        copies of it, each able to drift. Reaching this method at all means
        the snapshot is still sourcing equity from somewhere other than the
        one shared observer -- which is the thing T-4 removes, so it is
        asserted here rather than quietly answered.
        """
        raise AssertionError(
            "_portfolio_snapshot consulted a private per-strategy _equity() fallback "
            f"(it would have fabricated {FABRICATED_EQUITY}); it must read "
            "weather_common.equity.observed_equity, which answers None when nothing "
            "was observed",
        )


# ---------------------------------------------------------------------------
# RED-1 / RED-2 -- the shared reader
# ---------------------------------------------------------------------------


def test_an_observed_balance_is_returned_as_a_float() -> None:
    """The non-defect path, pinned first so every `None` below is meaningful."""
    equity = observed_equity(
        _Cache(_Instrument()),
        _Portfolio(_Account(1_234.5)),
        {"A": _NtId(_Venue("POLYMARKET_US"))},
    )

    assert equity == pytest.approx(1_234.5)


def test_no_account_on_the_venue_is_unobserved_not_a_constant() -> None:
    """RED-1: `portfolio.account(venue)` is `None` before the account event lands."""
    equity = observed_equity(
        _Cache(_Instrument()),
        _Portfolio(None),
        {"A": _NtId(_Venue("POLYMARKET_US"))},
    )

    assert equity is None


def test_an_account_with_no_balance_in_that_currency_is_unobserved() -> None:
    """RED-2: `balance_total` returns `None`, never zero, for "no such balance"."""
    equity = observed_equity(
        _Cache(_Instrument()),
        _Portfolio(_Account(None)),
        {"A": _NtId(_Venue("POLYMARKET_US"))},
    )

    assert equity is None


def test_an_instrument_missing_from_the_cache_is_unobserved() -> None:
    """No instrument means no quote currency to ask the account about."""
    equity = observed_equity(
        _Cache(None),
        _Portfolio(_Account(1_234.5)),
        {"A": _NtId(_Venue("POLYMARKET_US"))},
    )

    assert equity is None


def test_a_reported_zero_balance_is_observed_and_stays_zero() -> None:
    """Zero is a MEASUREMENT, distinct from `None`.

    The risk policy refuses a new buy on either, but for different reasons
    (`equity_nonpositive` vs `equity_unobserved`), so the reader must not
    collapse them.
    """
    equity = observed_equity(
        _Cache(_Instrument()),
        _Portfolio(_Account(0.0)),
        {"A": _NtId(_Venue("POLYMARKET_US"))},
    )

    assert equity == 0.0


def test_no_instruments_at_all_is_unobserved() -> None:
    assert observed_equity(_Cache(_Instrument()), _Portfolio(_Account(5.0)), {}) is None


# ---------------------------------------------------------------------------
# RED-1 / RED-2 at the five strategies -- what the snapshot actually carries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES, ids=lambda c: c.__name__)
def test_a_strategy_with_no_account_reports_unobserved_equity(strategy_cls: Any) -> None:
    """RED-1, at every strategy: the snapshot must not carry a fabrication."""
    snapshot = strategy_cls._portfolio_snapshot(
        _StrategySelf(account=None, instrument=_Instrument()),
    )

    assert snapshot.equity is None


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES, ids=lambda c: c.__name__)
def test_a_strategy_with_no_balance_reports_unobserved_equity(strategy_cls: Any) -> None:
    """RED-2, at every strategy."""
    snapshot = strategy_cls._portfolio_snapshot(
        _StrategySelf(account=_Account(None), instrument=_Instrument()),
    )

    assert snapshot.equity is None


@pytest.mark.parametrize("strategy_cls", STRATEGY_CLASSES, ids=lambda c: c.__name__)
def test_a_strategy_reports_the_observed_balance_when_there_is_one(strategy_cls: Any) -> None:
    """The control: these tests are not passing because nothing is wired."""
    snapshot = strategy_cls._portfolio_snapshot(
        _StrategySelf(account=_Account(1_200.0), instrument=_Instrument()),
    )

    assert snapshot.equity == pytest.approx(1_200.0)


# ---------------------------------------------------------------------------
# RED-9 -- reduce-only entered SILENTLY is indistinguishable from a bot that
# saw no opportunity. The refusal names the state and carries the tick clock
# it was decided on; without it the plan's own falsifier ("do these refusals
# cluster anywhere but start-up?") cannot be run against a journal.
# ---------------------------------------------------------------------------


def test_the_unobserved_refusal_note_carries_the_tick_timestamp() -> None:
    note = reduce_only_refusal_note(EQUITY_UNOBSERVED, tick_ts_ns=1_700_000_000_123_456_789)

    assert "1700000000123456789" in note


def test_the_unobserved_refusal_note_names_the_reduce_only_state() -> None:
    note = reduce_only_refusal_note(EQUITY_UNOBSERVED, tick_ts_ns=0)

    assert REDUCE_ONLY_STATE in note
    assert REDUCE_ONLY_STATE == "reduce-only"


def test_the_nonpositive_refusal_note_names_the_same_state() -> None:
    """Both equity refusals enter the same state, so both must say so."""
    note = reduce_only_refusal_note(EQUITY_NONPOSITIVE, tick_ts_ns=42)

    assert REDUCE_ONLY_STATE in note
    assert "42" in note


@pytest.mark.parametrize("reason", ["max_position", "stale_quote", "equity_fraction", "ok"])
def test_an_unrelated_refusal_gets_no_reduce_only_note(reason: str) -> None:
    """NOT unconditional decoration: `equity_fraction` is a clip against an
    OBSERVED balance and enters no reduce-only state, so a note on it would
    be a false operator signal.
    """
    assert reduce_only_refusal_note(reason, tick_ts_ns=42) == ""
