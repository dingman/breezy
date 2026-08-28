"""Unit tests for the preserved decision logic: `evaluate_instrument`.

These are pure-function tests -- no Nautilus `Strategy`, cache, clock, or
engine anywhere in scope -- which is the entire point of extracting
`evaluate_instrument` out of the operator's bundle
(``breezy.strategy.forecast_mispricing.decision``). Every branch pinned here
is the operator's original math: `edge_after_costs`, the separate entry/exit
edge thresholds, uncertainty-damped and horizon-scaled sizing, and the
optional short side.
"""

from __future__ import annotations

import datetime as dt

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.decision import evaluate_instrument
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import (
    ForecastSnapshot,
    MarketQuote,
    SideIntent,
    SignalDecision,
)
from breezy.strategy.weather_common.probability import WeatherProbabilityEngine
from breezy.strategy.weather_common.risk import RiskLimits, RiskManager

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)
INSTRUMENT_ID = "KORD-GE80.SIM"


def _facts(*, lower_f: int | None = 80, upper_f: int | None = None) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=STATION,
        climate_day=CLIMATE_DAY,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _contract(**facts_kwargs: object) -> MispricingContract:
    return MispricingContract(
        instrument_id=INSTRUMENT_ID,
        facts=_facts(**facts_kwargs),  # type: ignore[arg-type]
        tick_size=0.01,
    )


def _quote(*, bid: float | None, ask: float | None, ts_event: dt.datetime = NOW) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=bid,
        ask=ask,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=ts_event,
    )


def _forecast(
    *,
    expected_high_f: float,
    horizon_hours: float = 6.0,
    published_at: dt.datetime = NOW,
) -> ForecastSnapshot:
    return ForecastSnapshot(
        location_id=STATION,
        target_date=CLIMATE_DAY,
        published_at=published_at,
        expected_high_f=expected_high_f,
        horizon_hours=horizon_hours,
    )


def _cfg(**overrides: object) -> ForecastMispricingConfig:
    return ForecastMispricingConfig(
        instrument_ids=(InstrumentId.from_str("KORD-GE80.SIM"),),
        **overrides,  # type: ignore[arg-type]
    )


def _engine() -> WeatherProbabilityEngine:
    return WeatherProbabilityEngine()


def _risk(contract: MispricingContract, **limit_overrides: object) -> RiskManager:
    return RiskManager(RiskLimits(**limit_overrides), {contract.instrument_id: contract})  # type: ignore[arg-type]


def _evaluate(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    forecast: ForecastSnapshot,
    current_qty: float = 0.0,
    cfg: ForecastMispricingConfig | None = None,
) -> SignalDecision | None:
    return evaluate_instrument(
        contract=contract,
        quote=quote,
        forecast=forecast,
        now=NOW,
        current_qty=current_qty,
        engine=_engine(),
        risk=_risk(contract),
        cfg=cfg or _cfg(),
    )


# ---------------------------------------------------------------------------
# Stale forecast -> FLAT, unconditionally
# ---------------------------------------------------------------------------


def test_stale_forecast_returns_flat_regardless_of_edge() -> None:
    contract = _contract()
    quote = _quote(bid=0.10, ask=0.12)
    forecast = _forecast(
        expected_high_f=95.0,
        published_at=NOW - dt.timedelta(hours=9),  # cfg default stale_forecast_hours=8.0
    )

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast)

    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "stale_forecast"


# ---------------------------------------------------------------------------
# Untradable quotes -> None, never a fabricated signal
# ---------------------------------------------------------------------------


def test_missing_ask_returns_none() -> None:
    contract = _contract()
    quote = _quote(bid=0.40, ask=None)
    forecast = _forecast(expected_high_f=95.0)

    assert _evaluate(contract=contract, quote=quote, forecast=forecast) is None


def test_spread_wider_than_the_risk_limit_returns_none() -> None:
    contract = _contract()
    quote = _quote(bid=0.30, ask=0.60)  # spread 0.30 > default max_bid_ask_spread 0.06
    forecast = _forecast(expected_high_f=95.0)

    assert _evaluate(contract=contract, quote=quote, forecast=forecast) is None


# ---------------------------------------------------------------------------
# Entry: long and short
# ---------------------------------------------------------------------------


def test_enters_long_yes_when_model_probability_is_far_above_the_cheap_ask() -> None:
    contract = _contract(lower_f=80, upper_f=None)  # "at least 80F"
    quote = _quote(bid=0.28, ask=0.30)
    forecast = _forecast(expected_high_f=95.0)  # comfortably above threshold

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast)

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.model_probability > 0.9
    assert decision.edge >= _cfg().min_entry_edge
    assert 1.0 <= decision.quantity <= _cfg().max_quantity
    assert 0.0 < decision.conviction <= 1.0
    assert decision.reason == "forecast_mispricing"


def test_enters_short_yes_when_model_probability_is_far_below_the_rich_bid() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.70, ask=0.72)
    forecast = _forecast(expected_high_f=50.0)  # comfortably below threshold

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast)

    assert decision is not None
    assert decision.intent is SideIntent.SHORT_YES
    assert decision.model_probability < 0.1
    assert decision.edge >= _cfg().min_entry_edge


def test_short_side_is_refused_when_shorting_is_disabled() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.70, ask=0.72)
    forecast = _forecast(expected_high_f=50.0)

    decision = _evaluate(
        contract=contract, quote=quote, forecast=forecast, cfg=_cfg(allow_short=False),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# No signal when the market already prices the model view
# ---------------------------------------------------------------------------


def test_returns_none_when_edge_does_not_clear_the_entry_threshold() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.60, ask=0.62)
    forecast = _forecast(expected_high_f=80.0)  # right at the threshold

    assert _evaluate(contract=contract, quote=quote, forecast=forecast, current_qty=0.0) is None


# ---------------------------------------------------------------------------
# Exit: decaying edge flattens an existing position, on either side
# ---------------------------------------------------------------------------


def test_exits_an_existing_long_when_edge_decays_below_the_exit_threshold() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.60, ask=0.62)
    forecast = _forecast(expected_high_f=80.0)

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast, current_qty=10.0)

    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "mispricing_exit_long"


def test_exits_an_existing_short_when_edge_decays_below_the_exit_threshold() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.60, ask=0.62)
    forecast = _forecast(expected_high_f=80.0)

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast, current_qty=-10.0)

    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "mispricing_exit_short"


# ---------------------------------------------------------------------------
# Sizing: clipped to the configured ceiling, never runs away
# ---------------------------------------------------------------------------


def test_quantity_is_clipped_to_max_quantity_on_an_extreme_edge() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    quote = _quote(bid=0.01, ask=0.02)  # as cheap as it gets
    # A long horizon keeps `horizon_frac` at its ceiling (1.0) so the raw
    # sized quantity is large enough to actually hit `max_quantity`.
    forecast = _forecast(expected_high_f=110.0, horizon_hours=48.0)

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast)

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.quantity == pytest.approx(_cfg().max_quantity)


@pytest.mark.parametrize("measure_upper", [None, 90])
def test_range_and_above_buckets_both_route_through_bucket_probability(
    measure_upper: int | None,
) -> None:
    """A closed-range bucket (both bounds set) must not crash the routing branch."""
    contract = _contract(lower_f=80, upper_f=measure_upper)
    quote = _quote(bid=0.28, ask=0.30)
    forecast = _forecast(expected_high_f=85.0)

    decision = _evaluate(contract=contract, quote=quote, forecast=forecast)

    # Not asserting a specific side here -- only that the RANGE branch (both
    # bounds set) is reachable and produces a well-formed decision or a clean
    # "no signal", never an exception.
    assert decision is None or decision.model_probability is not None
