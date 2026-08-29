"""Unit tests for the preserved calibration mean-reversion decision.

Pure-function tests: no Nautilus `Strategy`, cache, clock or portfolio in
scope. Every branch pinned here is the operator's original math from the
``calibration_mean_reversion.py`` section of the bundle -- the z-score against
``expected_probability_se``, the separate entry/exit z thresholds, the
absolute-probability-gap floor, the executable-gap-after-costs screen and the
z-scaled sizing.

The one adaptation, and it is the point of the port: ``hours_left`` comes from
``forecast.horizon_hours`` rather than from the bundle's fabricated
``settlement_datetime_utc()`` clock. See
``tests/unit/test_weather_strategy_settlement_clock.py``.
"""

from __future__ import annotations

import datetime as dt

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.decision import (
    evaluate_instrument,
    should_throttle,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import (
    ForecastSnapshot,
    MarketQuote,
    SideIntent,
    SignalDecision,
)
from breezy.strategy.weather_common.probability import WeatherProbabilityEngine

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
NOW = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC)
INSTRUMENT_ID = "NYC-GE80.POLYMARKET_US"


def _metric(decision: SignalDecision, key: str) -> float:
    """Read a numeric `SignalDecision.metadata` entry with its type proven.

    `metadata` is a `Mapping[str, float | str | int | None]`, so comparing an
    entry directly against a number is unsound -- the string and None arms make
    `>` a type error. Asserting the arm here keeps the assertions below honest
    instead of silencing the checker at the comparison.
    """
    value = decision.metadata[key]
    assert isinstance(value, int | float), f"{key} is {type(value).__name__}, not numeric"
    return float(value)


def _contract() -> MispricingContract:
    return MispricingContract(
        instrument_id=INSTRUMENT_ID,
        facts=WeatherBucketFacts(
            settlement_station=STATION,
            climate_day=CLIMATE_DAY,
            measure=Measure.HIGH,
            lower_f=80,
            upper_f=None,
        ),
        tick_size=0.01,
    )


def _quote(*, bid: float, ask: float) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=bid,
        ask=ask,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW,
    )


def _forecast(
    *,
    expected_high_f: float = 85.0,
    horizon_hours: float = 24.0,
    published_at: dt.datetime = NOW - dt.timedelta(hours=1),
) -> ForecastSnapshot:
    return ForecastSnapshot(
        location_id=STATION,
        target_date=CLIMATE_DAY,
        published_at=published_at,
        expected_high_f=expected_high_f,
        horizon_hours=horizon_hours,
    )


def _evaluate(
    *,
    quote: MarketQuote,
    forecast: ForecastSnapshot | None = None,
    current_qty: float = 0.0,
    cfg: CalibrationMeanReversionConfig | None = None,
) -> SignalDecision | None:
    return evaluate_instrument(
        contract=_contract(),
        quote=quote,
        forecast=forecast if forecast is not None else _forecast(),
        now=NOW,
        current_qty=current_qty,
        engine=WeatherProbabilityEngine(),
        cfg=cfg if cfg is not None else CalibrationMeanReversionConfig(instrument_ids=()),
    )


# ----------------------------------------------------------------------
# Throttle
# ----------------------------------------------------------------------
def test_throttle_suppresses_a_flat_instrument_inside_the_recheck_window() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), recheck_minutes=20.0)
    last = NOW - dt.timedelta(minutes=5)
    assert should_throttle(last_eval=last, now=NOW, current_qty=0.0, cfg=cfg) is True


def test_throttle_never_suppresses_an_instrument_holding_a_position() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), recheck_minutes=20.0)
    last = NOW - dt.timedelta(minutes=5)
    assert should_throttle(last_eval=last, now=NOW, current_qty=10.0, cfg=cfg) is False


def test_throttle_expires_after_the_recheck_window() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), recheck_minutes=20.0)
    last = NOW - dt.timedelta(minutes=25)
    assert should_throttle(last_eval=last, now=NOW, current_qty=0.0, cfg=cfg) is False


def test_throttle_is_absent_on_first_evaluation() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=())
    assert should_throttle(last_eval=None, now=NOW, current_qty=0.0, cfg=cfg) is False


# ----------------------------------------------------------------------
# Horizon: comes from the forecast, never from a wall clock
# ----------------------------------------------------------------------
def test_short_horizon_flattens_an_open_position() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), min_horizon_hours=6.0)
    decision = _evaluate(
        quote=_quote(bid=0.40, ask=0.42),
        forecast=_forecast(horizon_hours=1.0),
        current_qty=10.0,
        cfg=cfg,
    )
    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "calibration_horizon_flatten"


def test_short_horizon_with_no_position_does_nothing() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), min_horizon_hours=6.0)
    assert (
        _evaluate(
            quote=_quote(bid=0.40, ask=0.42),
            forecast=_forecast(horizon_hours=1.0),
            current_qty=0.0,
            cfg=cfg,
        )
        is None
    )


# ----------------------------------------------------------------------
# Stable-forecast gate
# ----------------------------------------------------------------------
def test_a_forecast_younger_than_the_stability_window_is_not_traded() -> None:
    cfg = CalibrationMeanReversionConfig(
        instrument_ids=(),
        require_stable_forecast=True,
        stable_forecast_minutes=25.0,
    )
    forecast = _forecast(published_at=NOW - dt.timedelta(minutes=5))
    assert _evaluate(quote=_quote(bid=0.40, ask=0.42), forecast=forecast, cfg=cfg) is None


# ----------------------------------------------------------------------
# Entry
# ----------------------------------------------------------------------
def test_market_far_above_the_calibrated_probability_shorts_yes() -> None:
    """Forecast 70F against a >=80F bucket: model p is tiny, market is rich."""
    decision = _evaluate(
        quote=_quote(bid=0.90, ask=0.92),
        forecast=_forecast(expected_high_f=70.0),
    )
    assert decision is not None
    assert decision.intent is SideIntent.SHORT_YES
    assert decision.reason == "calibration_z_entry"
    assert decision.market_probability == 0.90
    assert _metric(decision, "z") > 0


def test_market_far_below_the_calibrated_probability_buys_yes() -> None:
    decision = _evaluate(
        quote=_quote(bid=0.04, ask=0.06),
        forecast=_forecast(expected_high_f=95.0),
    )
    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.market_probability == 0.06
    assert _metric(decision, "z") < 0


#: A forecast high of 79.5F against a ">= 80F" bucket sits exactly on the
#: model's continuity-corrected threshold, so `cal_p` is 0.50 and a 0.49/0.51
#: book is fairly priced: z is 0.0 and the probability gap is 0.0.
FAIR_HIGH_F = 79.5


def test_a_fairly_priced_market_produces_no_decision() -> None:
    assert (
        _evaluate(
            quote=_quote(bid=0.49, ask=0.51),
            forecast=_forecast(expected_high_f=FAIR_HIGH_F),
        )
        is None
    )


def test_shorts_are_suppressed_when_disallowed() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), allow_short=False)
    assert (
        _evaluate(
            quote=_quote(bid=0.90, ask=0.92),
            forecast=_forecast(expected_high_f=70.0),
            cfg=cfg,
        )
        is None
    )


def test_entry_is_refused_when_the_executable_gap_is_below_the_minimum_edge() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), min_model_edge=0.95)
    assert (
        _evaluate(
            quote=_quote(bid=0.90, ask=0.92),
            forecast=_forecast(expected_high_f=70.0),
            cfg=cfg,
        )
        is None
    )


def test_quantity_is_clipped_to_the_configured_maximum() -> None:
    cfg = CalibrationMeanReversionConfig(instrument_ids=(), max_quantity=30.0)
    decision = _evaluate(
        quote=_quote(bid=0.95, ask=0.97),
        forecast=_forecast(expected_high_f=60.0),
        cfg=cfg,
    )
    assert decision is not None
    assert decision.quantity == 30.0


# ----------------------------------------------------------------------
# Exit
# ----------------------------------------------------------------------
def test_a_long_exits_once_the_z_score_reverts() -> None:
    decision = _evaluate(
        quote=_quote(bid=0.49, ask=0.51),
        forecast=_forecast(expected_high_f=FAIR_HIGH_F),
        current_qty=10.0,
    )
    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "calibration_z_exit_long"


def test_a_short_exits_once_the_z_score_reverts() -> None:
    decision = _evaluate(
        quote=_quote(bid=0.49, ask=0.51),
        forecast=_forecast(expected_high_f=FAIR_HIGH_F),
        current_qty=-10.0,
    )
    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "calibration_z_exit_short"


def test_a_missing_side_of_the_book_produces_no_decision() -> None:
    quote = MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=None,
        ask=0.42,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW,
    )
    assert _evaluate(quote=quote) is None
