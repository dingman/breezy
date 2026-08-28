"""H-1, continued: the two ordering facts that need a REAL running engine.

``tests/unit/test_backtest_harness_refusal_precedence.py`` pins every
precedence question answerable from a pure function call. Two questions
cannot be: whether a build-time guard preempts a runtime concern (the
strategy has to actually be handed to ``run_backtest`` to prove it never
ran), and which of the three ``SilentRunCondition`` values wins when all
three are true of the SAME run (that requires a live ``BacktestEngine`` to
produce a rejection, an open position and an idle strategy in one pass).

Status: both facts below were already true of the current implementation --
`run_backtest` calls `build_backtest_engine` before it ever calls
`engine.add_strategy`/`engine.run()` (structural, in the source), and the
three post-run refusals are three independent `if not allow_...: _refuse...()`
statements checked in a fixed textual order. These are new observations of
existing, correct behaviour -- not defects, and nothing here changes
production code.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Money

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    NotVenueMarketDataError,
    SilentRunCondition,
    SilentRunError,
    run_backtest,
)
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

CLIP = 10

#: Never added to `config.instruments`, so the strategy holding it resolves no
#: instrument in `on_start`, logs, and calls `self.stop()` -- never
#: subscribing to anything. Guaranteed idle, with no need to stage a third
#: real market.
_IDLE_INSTRUMENT_ID = InstrumentId(Symbol("synthetic-idle-market"), Venue("POLYMARKET_US"))


# ---------------------------------------------------------------------------
# Cross-phase: a build-time guard failure preempts every runtime concern
# ---------------------------------------------------------------------------


def test_a_build_time_screen_failure_preempts_every_runtime_concern() -> None:
    """`run_backtest` calls `build_backtest_engine` before `add_strategy`/`run()`.

    The config below fails `assert_market_data_is_venue_data` (a bare weather
    record sits in `market_data`) AND, independently, carries no settlement
    price at all -- a `SettlementInvariantError` waiting behind it -- AND
    hands a strategy that would happily submit an order if the engine ever
    ran. None of that matters: the strategy never starts.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=tape.instrument.id,
            trade_quantity=Decimal(CLIP),
        ),
    )
    config = BreezyBacktestConfig(
        instruments=(tape.instrument,),
        market_data=[*tape.all_data(), make_climate_day()],  # foreign record
        weather_data=as_backtest_data([make_climate_day(retrieved_at_ns=tape.weather_ts_ns)]),
        settlement_prices={},  # ALSO a SettlementInvariantError, never reached
        starting_balances=(Money(1_000, tape.instrument.quote_currency),),
    )

    with pytest.raises(NotVenueMarketDataError):
        run_backtest(config, strategies=(probe,))

    assert probe.orders_submitted == 0


# ---------------------------------------------------------------------------
# SilentRunCondition total order:
#   REJECTED_ORDERS > OPEN_POSITIONS > IDLE_STRATEGY
#
# Read directly off `run_backtest`'s three `if not allow_...:` statements, in
# the order they are written.
# ---------------------------------------------------------------------------


def _three_condition_config() -> tuple[BreezyBacktestConfig, tuple[BreezyHarnessProbe, ...]]:
    """One run in which all three `SilentRunCondition`s are true at once.

    * `rejected_tape`'s probe submits into a book that is not there yet
      (weather stamped before the first depth record) -- REJECTED_ORDERS.
    * `open_tape`'s probe fills normally, but `open_tape` never receives a
      close and is named in `instruments_without_close` -- its position is
      left open at the end of the run -- OPEN_POSITIONS.
    * `idle_probe` is configured against an instrument that is never added to
      `config.instruments`; it logs, stops, and never subscribes to
      anything -- IDLE_STRATEGY.
    """
    rejected_tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    open_tape = synthetic_binary_tape(size_precision=2, settlement_price=1.0)

    rejected_probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=rejected_tape.instrument.id,
            trade_quantity=Decimal(CLIP),
            station="REJECTED",
        ),
    )
    open_probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=open_tape.instrument.id,
            trade_quantity=Decimal(CLIP),
            station="OPEN",
        ),
    )
    idle_probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=_IDLE_INSTRUMENT_ID,
            trade_quantity=Decimal(CLIP),
            station="IDLE",
        ),
    )

    first_depth = rejected_tape.market_data[0]
    weather = as_backtest_data(
        [
            make_climate_day(station="REJECTED", retrieved_at_ns=first_depth.ts_init - 1),
            make_climate_day(station="OPEN", retrieved_at_ns=open_tape.weather_ts_ns),
        ],
    )

    config = BreezyBacktestConfig(
        instruments=(rejected_tape.instrument, open_tape.instrument),
        market_data=[*rejected_tape.all_data(), *open_tape.market_data],
        weather_data=weather,
        settlement_prices={rejected_tape.instrument.id: rejected_tape.settlement_price},
        starting_balances=(Money(1_000, rejected_tape.instrument.quote_currency),),
        instruments_without_close=frozenset({open_tape.instrument.id}),
    )
    return config, (rejected_probe, open_probe, idle_probe)


def test_rejected_orders_beats_open_positions_and_idle_strategy() -> None:
    """All three conditions are true; `REJECTED_ORDERS` is checked first."""
    config, strategies = _three_condition_config()

    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(config, strategies=strategies)

    assert excinfo.value.condition is SilentRunCondition.REJECTED_ORDERS


def test_open_positions_beats_idle_strategy_once_rejection_is_waived() -> None:
    """With `REJECTED_ORDERS` waived, `OPEN_POSITIONS` -- checked next -- wins."""
    config, strategies = _three_condition_config()

    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(config, strategies=strategies, allow_rejected_orders=True)

    assert excinfo.value.condition is SilentRunCondition.OPEN_POSITIONS


def test_idle_strategy_fires_last_once_the_other_two_are_waived() -> None:
    """With the first two waived, `IDLE_STRATEGY` -- checked last -- is what remains."""
    config, strategies = _three_condition_config()

    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            config,
            strategies=strategies,
            allow_rejected_orders=True,
            allow_open_positions=True,
        )

    assert excinfo.value.condition is SilentRunCondition.IDLE_STRATEGY


def test_waiving_all_three_finally_returns_the_engine() -> None:
    """Sanity check on the scenario itself: nothing else is wrong with it."""
    config, strategies = _three_condition_config()

    engine = run_backtest(
        config,
        strategies=strategies,
        allow_rejected_orders=True,
        allow_open_positions=True,
        allow_idle_strategies=True,
    )
    try:
        rejected_probe, open_probe, idle_probe = strategies
        assert rejected_probe.orders_submitted == 1
        assert open_probe.orders_submitted == 1
        assert idle_probe.orders_submitted == 0
    finally:
        engine.dispose()
