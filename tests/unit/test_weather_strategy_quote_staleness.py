"""Strategy handoff tests for quote-age risk screening."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import cast

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.strategy import (
    CalibrationMeanReversionStrategy,
)
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import (
    ForecastSnapshot,
    MarketQuote,
    SideIntent,
    SignalDecision,
)
from breezy.strategy.weather_common.risk import PortfolioSnapshot, RiskLimits, RiskManager

NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)
CLIMATE_DAY = dt.date(2026, 8, 28)
INSTRUMENT_ID = "NYC-GE80.POLYMARKET_US"

MaybeSubmit = Callable[
    [
        object,
        MispricingContract,
        MarketQuote,
        SignalDecision,
        ForecastSnapshot,
        dt.datetime,
        float,
    ],
    None,
]

STRATEGY_MAYBE_SUBMIT: tuple[tuple[str, MaybeSubmit], ...] = (
    (
        "forecast_mispricing",
        cast(MaybeSubmit, ForecastMispricingStrategy._maybe_submit),
    ),
    (
        "calibration_mean_reversion",
        cast(MaybeSubmit, CalibrationMeanReversionStrategy._maybe_submit),
    ),
    (
        "forecast_revision",
        cast(MaybeSubmit, ForecastRevisionStrategy._maybe_submit),
    ),
)


class _NoWorkingOrdersCache:
    """No order of ANY status -- the shape every `_maybe_submit` gate must see through.

    `orders` was added alongside `orders_open` when the strategies' in-flight
    gate moved onto `breezy.strategy.weather_common.inflight.working_orders`
    (T-1): that helper reads `cache.orders(...)` and filters on
    `not order.is_closed`, because `orders_open` excludes INITIALIZED and
    SUBMITTED. Both methods are kept -- this double stands in for a real
    `Cache`, and a strategy that still asked the narrower question would
    otherwise fail here for the wrong reason (an `AttributeError`) instead of
    on its own behaviour.
    """

    def orders(self, *, instrument_id: object) -> list[object]:
        del instrument_id
        return []

    def orders_open(self, *, instrument_id: object) -> list[object]:
        del instrument_id
        return []


class _Log:
    def info(self, message: str) -> None:
        pass


class _StrategyHarness:
    def __init__(self, contract: MispricingContract) -> None:
        self.cache = _NoWorkingOrdersCache()
        self.log = _Log()
        self._nt_ids = {contract.instrument_id: object()}
        self._risk = RiskManager(
            RiskLimits(stale_quote_minutes=15.0),
            {contract.instrument_id: contract},
        )
        self.submitted: list[tuple[str, float]] = []
        self.reported_refusals = 0

    def _portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(equity=10_000.0)

    def _report_refusals(self) -> None:
        self.reported_refusals += 1

    def _submit_delta(
        self,
        contract: MispricingContract,
        quote: MarketQuote,
        signed_delta: float,
        decision: SignalDecision,
    ) -> None:
        self.submitted.append((contract.instrument_id, signed_delta))


def _contract() -> MispricingContract:
    return MispricingContract(
        instrument_id=INSTRUMENT_ID,
        facts=WeatherBucketFacts(
            settlement_station="NYC",
            climate_day=CLIMATE_DAY,
            measure=Measure.HIGH,
            lower_f=80,
            upper_f=None,
        ),
        tick_size=0.01,
    )


def _quote(*, age: dt.timedelta) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=0.28,
        ask=0.30,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW - age,
    )


def _forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        location_id="NYC",
        target_date=CLIMATE_DAY,
        published_at=NOW - dt.timedelta(hours=1),
        expected_high_f=95.0,
        horizon_hours=24.0,
    )


def _decision() -> SignalDecision:
    return SignalDecision(
        instrument_id=INSTRUMENT_ID,
        intent=SideIntent.LONG_YES,
        model_probability=0.95,
        market_probability=0.30,
        edge=0.20,
        conviction=1.0,
        quantity=10.0,
        reason="test_long_yes",
    )


@pytest.mark.parametrize(("strategy_name", "maybe_submit"), STRATEGY_MAYBE_SUBMIT)
def test_strategy_refuses_stale_quote_but_accepts_quote_inside_limit(
    strategy_name: str,
    maybe_submit: MaybeSubmit,
) -> None:
    contract = _contract()
    stale = _StrategyHarness(contract)
    fresh = _StrategyHarness(contract)

    maybe_submit(
        stale,
        contract,
        _quote(age=dt.timedelta(minutes=15, seconds=1)),
        _decision(),
        _forecast(),
        NOW,
        0.0,
    )
    maybe_submit(
        fresh,
        contract,
        _quote(age=dt.timedelta(minutes=14, seconds=59)),
        _decision(),
        _forecast(),
        NOW,
        0.0,
    )

    assert stale.submitted == [], f"{strategy_name} submitted with a stale quote"
    assert fresh.submitted == [(INSTRUMENT_ID, 10.0)]
