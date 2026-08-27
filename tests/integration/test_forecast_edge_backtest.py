"""A newcomer-style weather edge strategy through the real backtest harness."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.objects import Money

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.forecast_edge import (
    ForecastHighEdgeBuyer,
    ForecastHighEdgeBuyerConfig,
)
from tests.support.synthetic_binary_tape import SyntheticBinaryTape, synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine

STARTING_BALANCE_USD = 1_000
CLIP = 10
SETTLEMENT_PRICE = 1.0


def _config(tape: SyntheticBinaryTape) -> BreezyBacktestConfig:
    return BreezyBacktestConfig(
        instruments=(tape.instrument,),
        market_data=tape.all_data(),
        weather_data=as_backtest_data(
            [
                make_climate_day(
                    station="NYC",
                    tmax_f=84,
                    is_final=True,
                    retrieved_at_ns=tape.weather_ts_ns,
                ),
            ],
        ),
        settlement_prices={tape.instrument.id: tape.settlement_price},
        starting_balances=(Money(STARTING_BALANCE_USD, tape.instrument.quote_currency),),
    )


def _strategy(tape: SyntheticBinaryTape) -> ForecastHighEdgeBuyer:
    return ForecastHighEdgeBuyer(
        ForecastHighEdgeBuyerConfig(
            instrument_id=tape.instrument.id,
            station="NYC",
            yes_if_tmax_at_least_f=80,
            trade_quantity=Decimal(CLIP),
            edge_threshold=Decimal("0.10"),
            probability_when_yes=Decimal("0.70"),
            probability_when_no=Decimal("0.20"),
        ),
    )


def _run() -> tuple[BacktestEngine, ForecastHighEdgeBuyer, SyntheticBinaryTape]:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=SETTLEMENT_PRICE)
    strategy = _strategy(tape)
    engine = run_backtest(_config(tape), strategies=(strategy,))
    return engine, strategy, tape


def test_forecast_high_edge_buyer_trades_weather_edge_and_settles() -> None:
    engine, strategy, tape = _run()
    try:
        positions = engine.cache.positions()
        fills = [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled)
        ]
        commissions = sum((fill.commission.as_decimal() for fill in fills), Decimal(0))
        expected_pnl = Decimal(CLIP) * (
            Decimal(str(tape.settlement_price)) - tape.best_ask.as_decimal()
        ) - commissions

        assert strategy.weather == 1
        assert strategy.depths > 0
        assert strategy.traded_tmax_f == 84
        assert strategy.last_model_probability == Decimal("0.70")
        assert strategy.last_edge == Decimal("0.28")
        assert strategy.orders_submitted == 1
        assert strategy.own_fills == 1
        assert strategy.maker_fills == 0
        assert strategy.weather_stations == ("NYC",)
        assert len(positions) == 1
        assert positions[0].is_closed
        assert positions[0].avg_px_close == tape.settlement_price
        assert positions[0].realized_pnl is not None
        assert positions[0].realized_pnl.as_decimal() == expected_pnl
        assert positions[0].realized_pnl.as_decimal() > 0
    finally:
        engine.dispose()
