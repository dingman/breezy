"""A forecast's error sigma is a function of its LEAD AT ISSUANCE, not the clock.

T-11. ``ForecastSnapshot.horizon_hours`` is the LIVE hours-remaining-to-settlement
(``forecast_source``'s contract, and what the settlement-halt and horizon-scaled
sizing gates legitimately want). ``ForecastErrorModel.sigma`` models something
else entirely: how wrong a forecast is, which is a property OF THE FORECAST --
its lead time when it was issued. A forecast's error distribution does not shrink
because the clock advanced toward a deadline it already knew about.

Feeding the live horizon to ``sigma`` therefore understates sigma by roughly the
ratio of the two horizons: a forecast issued 24h before settlement and read 3h
before settlement selects the 3-hour error bin (~1.4 degF) for a forecast that
actually carries the 24-hour error (~2.8 degF). Understated sigma pushes model
probability toward its bounds, which OVERSTATES edge -- worst exactly on the
near-certain buckets where sizing is largest, i.e. it corrupts measured
backtest ROI in the favourable direction.

These tests pin the argument (what ``sigma`` is called with), the consequence
(which sigma bin comes back), and the money (the edge that sigma produces), so
a future refactor that reintroduces the collapse is caught at the number and
not only at the call.
"""

from __future__ import annotations

import datetime as dt
from datetime import date

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.decision import (
    evaluate_instrument as evaluate_calibration,
)
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.decision import (
    evaluate_instrument as evaluate_mispricing,
)
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.decision import (
    RevisionState,
)
from breezy.strategy.forecast_revision.decision import (
    evaluate_instrument as evaluate_revision,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import ForecastSnapshot, MarketQuote, SignalDecision
from breezy.strategy.weather_common.probability import (
    ForecastErrorModel,
    WeatherProbabilityEngine,
    default_conus_summer_error_model,
)
from breezy.strategy.weather_common.risk import RiskLimits, RiskManager

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
INSTRUMENT_ID = "NYC-GE80.POLYMARKET_US"

#: The instrument's own native settlement deadline (`expiration_ns` in the
#: running system, `_deadlines[instrument_id]` at the strategy layer).
DEADLINE = dt.datetime(2026, 8, 29, 0, 0, tzinfo=dt.UTC)
#: Issued a full day out ...
PUBLISHED_AT = DEADLINE - dt.timedelta(hours=24)
#: ... and read three hours before settlement.
NOW = DEADLINE - dt.timedelta(hours=3)

LIVE_HORIZON_H = 3.0
ISSUANCE_LEAD_H = 24.0

#: `default_conus_summer_error_model` bins, which are what these two horizons
#: are worth in degrees F. The whole defect in one line: 1.4 vs 2.8.
SIGMA_AT_LIVE_HORIZON_F = 1.4
SIGMA_AT_ISSUANCE_LEAD_F = 2.8


class _RecordingErrorModel(ForecastErrorModel):
    """Every horizon `sigma` was called with, in order, and nothing else.

    Subclass rather than a spy on the instance: `ForecastErrorModel` is a
    `slots=True` dataclass, so an instance cannot carry a recording attribute.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.sigma_horizons: list[float] = []

    def sigma(self, location_id: str, target_date: date, horizon_hours: float) -> float:
        self.sigma_horizons.append(horizon_hours)
        return super().sigma(location_id, target_date, horizon_hours)


def _facts(*, lower_f: int | None = 80, upper_f: int | None = None) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=STATION,
        climate_day=CLIMATE_DAY,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _contract() -> MispricingContract:
    return MispricingContract(instrument_id=INSTRUMENT_ID, facts=_facts(), tick_size=0.01)


def _quote(*, bid: float, ask: float) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=bid,
        ask=ask,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW,
    )


def _forecast(*, expected_high_f: float = 83.0) -> ForecastSnapshot:
    """The T-24h publication, read at T-3h: `horizon_hours` is LIVE, per contract."""
    return ForecastSnapshot(
        location_id=STATION,
        target_date=CLIMATE_DAY,
        published_at=PUBLISHED_AT,
        expected_high_f=expected_high_f,
        horizon_hours=LIVE_HORIZON_H,
    )


def _mispricing_cfg(**overrides: object) -> ForecastMispricingConfig:
    # `stale_forecast_hours` is raised because a 21-hour-old forecast is stale
    # under the shipped 8h default and would return FLAT before sigma is ever
    # reached. That gate BOUNDS the defect in this strategy (to an 8h
    # lead-vs-live gap); it does not remove it, and it does not exist at all in
    # `calibration_mean_reversion.decision`, which is tested below at its own
    # defaults.
    params: dict[str, object] = {"stale_forecast_hours": 48.0}
    params.update(overrides)
    return ForecastMispricingConfig(
        instrument_ids=(InstrumentId.from_str("NYC-GE80.POLYMARKET_US"),),
        **params,  # type: ignore[arg-type]
    )


def _evaluate_mispricing(
    *,
    quote: MarketQuote,
    engine: WeatherProbabilityEngine,
    cfg: ForecastMispricingConfig | None = None,
) -> SignalDecision | None:
    contract = _contract()
    return evaluate_mispricing(
        contract=contract,
        quote=quote,
        forecast=_forecast(),
        now=NOW,
        current_qty=0.0,
        engine=engine,
        risk=RiskManager(RiskLimits(), {contract.instrument_id: contract}),
        cfg=cfg if cfg is not None else _mispricing_cfg(),
        settlement_deadline=DEADLINE,
    )


def _metric(decision: SignalDecision, key: str) -> float:
    value = decision.metadata[key]
    assert isinstance(value, int | float), f"{key} is {type(value).__name__}, not numeric"
    return float(value)


# ---------------------------------------------------------------------------
# RED-1 -- the ARGUMENT: what `sigma` is actually called with
# ---------------------------------------------------------------------------


def test_mispricing_sigma_is_called_with_the_issuance_lead_not_the_live_horizon() -> None:
    model = _RecordingErrorModel()
    engine = WeatherProbabilityEngine(model)

    decision = _evaluate_mispricing(quote=_quote(bid=0.78, ask=0.80), engine=engine)

    assert decision is not None
    assert model.sigma_horizons, "sigma was never called -- the test proved nothing"
    assert set(model.sigma_horizons) == {ISSUANCE_LEAD_H}, (
        f"sigma saw {sorted(set(model.sigma_horizons))}; a forecast issued 24h "
        f"before settlement carries 24h of error however late it is read"
    )
    assert LIVE_HORIZON_H not in model.sigma_horizons


def test_calibration_sigma_is_called_with_the_issuance_lead_not_the_live_horizon() -> None:
    model = _RecordingErrorModel()
    contract = _contract()

    evaluate_calibration(
        contract=contract,
        quote=_quote(bid=0.78, ask=0.80),
        forecast=_forecast(),
        now=NOW,
        current_qty=0.0,
        engine=WeatherProbabilityEngine(model),
        # `min_horizon_hours` is lowered because it is a LIVE-horizon gate and
        # the shipped 6.0 default flattens at T-3h before sigma is reached.
        # That gate is correct as it stands and is deliberately left alone --
        # see the module docstring on keeping the two meanings separate.
        cfg=CalibrationMeanReversionConfig(instrument_ids=(), min_horizon_hours=1.0),
        settlement_deadline=DEADLINE,
    )

    assert model.sigma_horizons, "sigma was never called -- the test proved nothing"
    assert set(model.sigma_horizons) == {ISSUANCE_LEAD_H}
    assert LIVE_HORIZON_H not in model.sigma_horizons


def test_revision_sigma_is_called_with_each_publications_own_issuance_lead() -> None:
    model = _RecordingErrorModel()
    contract = _contract()
    earlier_published_at = DEADLINE - dt.timedelta(hours=30)
    state = RevisionState(history_len=12)
    state.observe(
        contract=contract,
        forecast=ForecastSnapshot(
            location_id=STATION,
            target_date=CLIMATE_DAY,
            published_at=earlier_published_at,
            expected_high_f=77.0,
            # Live as of ITS OWN observation instant, which is not `NOW` --
            # exactly why a stored snapshot's issuance lead cannot be
            # recovered from `horizon_hours` after the fact.
            horizon_hours=9.0,
        ),
        market_mid_p=0.30,
    )
    state.observe(contract=contract, forecast=_forecast(), market_mid_p=0.30)

    evaluate_revision(
        contract=contract,
        quote=_quote(bid=0.30, ask=0.32),
        now=NOW,
        current_qty=0.0,
        state=state,
        engine=WeatherProbabilityEngine(model),
        cfg=ForecastRevisionConfig(instrument_ids=(), allow_short=True),
        settlement_deadline=DEADLINE,
    )

    assert model.sigma_horizons, "sigma was never called -- the test proved nothing"
    assert set(model.sigma_horizons) == {30.0, ISSUANCE_LEAD_H}, (
        "each publication carries its own lead: 30h for the older, 24h for the newer"
    )


# ---------------------------------------------------------------------------
# RED-2 -- the CONSEQUENCE: which sigma comes back
# ---------------------------------------------------------------------------


def test_sigma_reported_is_the_24_hour_bin_not_the_3_hour_bin() -> None:
    engine = WeatherProbabilityEngine(default_conus_summer_error_model())

    decision = _evaluate_mispricing(quote=_quote(bid=0.78, ask=0.80), engine=engine)

    assert decision is not None
    assert _metric(decision, "sigma_f") == pytest.approx(SIGMA_AT_ISSUANCE_LEAD_F)
    assert _metric(decision, "sigma_f") != pytest.approx(SIGMA_AT_LIVE_HORIZON_F)


def test_the_live_horizon_is_still_reported_live_and_still_drives_the_time_gates() -> None:
    """The fix must not repurpose `horizon_hours`; both meanings stay separate."""
    engine = WeatherProbabilityEngine(default_conus_summer_error_model())

    decision = _evaluate_mispricing(quote=_quote(bid=0.78, ask=0.80), engine=engine)

    assert decision is not None
    assert _metric(decision, "horizon_h") == pytest.approx(LIVE_HORIZON_H)


# ---------------------------------------------------------------------------
# RED-3 -- the MONEY: the edge that sigma produces
# ---------------------------------------------------------------------------

#: `prob_above(83.0, 80, sigma)` with the continuity correction, minus the ask
#: (0.80) and `transaction_cost_prob` (0.015).
#:
#: At sigma=1.4 the model probability saturates the `p_floor` clip at 0.99;
#: at the honest sigma=2.8 it is 0.89435. Same forecast, same book, same
#: instant -- the ONLY difference is which horizon reached `sigma`.
EDGE_AT_UNDERSTATED_SIGMA = 0.175
EDGE_AT_HONEST_SIGMA = 0.0793502263331446


def test_edge_is_not_overstated_by_an_understated_sigma() -> None:
    engine = WeatherProbabilityEngine(default_conus_summer_error_model())

    decision = _evaluate_mispricing(quote=_quote(bid=0.78, ask=0.80), engine=engine)

    assert decision is not None
    assert decision.edge == pytest.approx(EDGE_AT_HONEST_SIGMA)
    assert decision.edge < EDGE_AT_UNDERSTATED_SIGMA
    assert decision.model_probability == pytest.approx(0.8943502263331446)


def test_a_trade_that_only_the_understated_sigma_would_have_taken_is_refused() -> None:
    """The overstatement is not cosmetic: it changes whether a position opens.

    At an ask of 0.85 the honest edge (0.0294) is below `min_entry_edge`
    (0.06) while the understated one (0.125) is comfortably above it -- so the
    defect does not merely mis-report edge on trades already taken, it
    manufactures trades.
    """
    engine = WeatherProbabilityEngine(default_conus_summer_error_model())

    decision = _evaluate_mispricing(quote=_quote(bid=0.83, ask=0.85), engine=engine)

    assert decision is None
