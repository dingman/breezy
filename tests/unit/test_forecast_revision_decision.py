"""Unit tests for the preserved forecast-revision decision.

Pure-function tests: no Nautilus `Strategy`, cache, clock or portfolio in
scope. Every branch pinned here is the operator's original math from the
``forecast_revision.py`` section of the bundle -- the revision magnitude
screens (absolute degrees, absolute probability, and degrees-over-sigma), the
same-sign persistence filter, the "how much has the book already absorbed"
comparison, the reaction window, the per-publication cooldown, and the
catch-up exit.

The adaptation the port forces, and it is reported rather than hidden: the
bundle drove revisions from a PUSH event (``on_nws_forecast`` ->
``on_forecast_updated``) delivered on a wire-level ``NWSForecastUpdate``
custom data type that Breezy does not publish. Breezy's forecast seam is a
PULL (``ForecastSource.snapshot``), so revision history is accumulated by
``RevisionState.observe`` when a pulled snapshot carries a newer
``published_at``. The decision math below is unchanged.
"""

from __future__ import annotations

import datetime as dt

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.decision import RevisionState, evaluate_instrument
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
T0 = dt.datetime(2026, 8, 28, 6, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 8, 28, 8, 0, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 8, 28, 8, 30, tzinfo=dt.UTC)
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


def _snapshot(*, high_f: float, published_at: dt.datetime, horizon: float) -> ForecastSnapshot:
    return ForecastSnapshot(
        location_id=STATION,
        target_date=CLIMATE_DAY,
        published_at=published_at,
        expected_high_f=high_f,
        horizon_hours=horizon,
    )


def _state_with_upward_revision(*, baseline_mid: float = 0.30) -> RevisionState:
    """Two publications, +6F apart, with a market baseline captured at each."""
    state = RevisionState(history_len=12)
    contract = _contract()
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=78.0, published_at=T0, horizon=26.0),
        market_mid_p=baseline_mid,
    )
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=84.0, published_at=T1, horizon=24.0),
        market_mid_p=baseline_mid,
    )
    return state


def _evaluate(
    *,
    state: RevisionState,
    quote: MarketQuote,
    now: dt.datetime = NOW,
    current_qty: float = 0.0,
    cfg: ForecastRevisionConfig | None = None,
) -> SignalDecision | None:
    return evaluate_instrument(
        contract=_contract(),
        quote=quote,
        now=now,
        current_qty=current_qty,
        state=state,
        engine=WeatherProbabilityEngine(),
        cfg=cfg if cfg is not None else ForecastRevisionConfig(instrument_ids=()),
    )


# ----------------------------------------------------------------------
# History accumulation (the push -> pull adaptation)
# ----------------------------------------------------------------------
def test_a_single_publication_is_not_yet_a_revision() -> None:
    state = RevisionState(history_len=12)
    state.observe(
        contract=_contract(),
        forecast=_snapshot(high_f=78.0, published_at=T0, horizon=26.0),
        market_mid_p=0.30,
    )
    assert _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31)) is None


def test_re_observing_the_same_publication_does_not_grow_the_history() -> None:
    state = RevisionState(history_len=12)
    contract = _contract()
    snap = _snapshot(high_f=78.0, published_at=T0, horizon=26.0)
    state.observe(contract=contract, forecast=snap, market_mid_p=0.30)
    state.observe(contract=contract, forecast=snap, market_mid_p=0.31)
    assert len(state.history(contract)) == 1


def test_an_out_of_order_publication_is_ignored() -> None:
    state = RevisionState(history_len=12)
    contract = _contract()
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=84.0, published_at=T1, horizon=24.0),
        market_mid_p=0.30,
    )
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=78.0, published_at=T0, horizon=26.0),
        market_mid_p=0.30,
    )
    assert len(state.history(contract)) == 1
    assert state.history(contract)[-1].expected_high_f == 84.0


# ----------------------------------------------------------------------
# Entry
# ----------------------------------------------------------------------
def test_an_unabsorbed_upward_revision_buys_yes() -> None:
    state = _state_with_upward_revision()
    decision = _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31))
    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.reason == "forecast_revision_unabsorbed"
    assert _metric(decision, "dT") == 6.0
    assert _metric(decision, "dP_model") > 0


def test_a_revision_the_book_already_absorbed_is_not_traded() -> None:
    """Market has moved with the revision, so there is nothing left to take."""
    state = _state_with_upward_revision(baseline_mid=0.30)
    decision = _evaluate(state=state, quote=_quote(bid=0.94, ask=0.96))
    assert decision is None


def test_a_revision_below_every_magnitude_floor_is_not_traded() -> None:
    state = RevisionState(history_len=12)
    contract = _contract()
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=84.0, published_at=T0, horizon=26.0),
        market_mid_p=0.30,
    )
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=84.05, published_at=T1, horizon=24.0),
        market_mid_p=0.30,
    )
    assert _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31)) is None


def test_shorts_are_suppressed_when_disallowed() -> None:
    """A downward revision would short YES; with shorts off it must not."""
    state = RevisionState(history_len=12)
    contract = _contract()
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=90.0, published_at=T0, horizon=26.0),
        market_mid_p=0.80,
    )
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=72.0, published_at=T1, horizon=24.0),
        market_mid_p=0.80,
    )
    cfg = ForecastRevisionConfig(instrument_ids=(), allow_short=False)
    assert _evaluate(state=state, quote=_quote(bid=0.79, ask=0.81), cfg=cfg) is None


def test_entry_is_refused_when_edge_after_costs_is_below_the_minimum() -> None:
    state = _state_with_upward_revision()
    cfg = ForecastRevisionConfig(instrument_ids=(), min_model_edge=0.95)
    assert _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31), cfg=cfg) is None


def test_quantity_is_clipped_to_the_configured_maximum() -> None:
    state = _state_with_upward_revision()
    cfg = ForecastRevisionConfig(instrument_ids=(), max_quantity=25.0)
    decision = _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31), cfg=cfg)
    assert decision is not None
    assert decision.quantity == 25.0


# ----------------------------------------------------------------------
# Reaction window and cooldown
# ----------------------------------------------------------------------
def test_a_publication_is_traded_at_most_once() -> None:
    state = _state_with_upward_revision()
    quote = _quote(bid=0.29, ask=0.31)
    first = _evaluate(state=state, quote=quote)
    assert first is not None
    second = _evaluate(state=state, quote=quote)
    assert second is None or second.intent is SideIntent.FLAT


def test_a_revision_older_than_the_reaction_window_is_not_entered() -> None:
    state = _state_with_upward_revision()
    cfg = ForecastRevisionConfig(instrument_ids=(), reaction_window_minutes=10.0)
    late = T1 + dt.timedelta(minutes=30)
    decision = _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31), now=late, cfg=cfg)
    assert decision is None or decision.intent is SideIntent.FLAT


# ----------------------------------------------------------------------
# Catch-up exit
# ----------------------------------------------------------------------
def test_a_position_exits_once_the_market_catches_up() -> None:
    state = _state_with_upward_revision()
    quote = _quote(bid=0.29, ask=0.31)
    entry = _evaluate(state=state, quote=quote)
    assert entry is not None

    cfg = ForecastRevisionConfig(instrument_ids=(), reaction_window_minutes=10.0)
    late = T1 + dt.timedelta(minutes=30)
    decision = _evaluate(
        state=state,
        quote=_quote(bid=0.94, ask=0.96),
        now=late,
        current_qty=20.0,
        cfg=cfg,
    )
    assert decision is not None
    assert decision.intent is SideIntent.FLAT
    assert decision.reason == "revision_market_caught_up"


def test_no_catch_up_exit_without_a_position() -> None:
    state = _state_with_upward_revision()
    quote = _quote(bid=0.29, ask=0.31)
    assert _evaluate(state=state, quote=quote) is not None

    cfg = ForecastRevisionConfig(instrument_ids=(), reaction_window_minutes=10.0)
    late = T1 + dt.timedelta(minutes=30)
    assert (
        _evaluate(
            state=state,
            quote=_quote(bid=0.94, ask=0.96),
            now=late,
            current_qty=0.0,
            cfg=cfg,
        )
        is None
    )
