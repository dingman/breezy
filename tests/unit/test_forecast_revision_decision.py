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

import pytest

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
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
T0 = dt.datetime(2026, 8, 28, 6, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 8, 28, 8, 0, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 8, 28, 8, 30, tzinfo=dt.UTC)
INSTRUMENT_ID = "NYC-GE80.POLYMARKET_US"
#: The instrument's native settlement deadline (`expiration_ns`). Chosen to be
#: CONSISTENT with the fixture's own live horizons -- `T0 + 26h == T1 + 24h ==
#: DEADLINE` -- so each publication's lead at issuance equals the
#: `horizon_hours` these tests already gave it, and every sigma below is the
#: same number it always was. What changed (T-11) is that the error model now
#: reads the lead rather than the live horizon; where the two coincide, as
#: here, nothing moves.
DEADLINE = dt.datetime(2026, 8, 29, 8, 0, tzinfo=dt.UTC)


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
    refusals: RefusalCounter | None = None,
) -> SignalDecision | None:
    return evaluate_instrument(
        contract=_contract(),
        quote=quote,
        now=now,
        current_qty=current_qty,
        state=state,
        engine=WeatherProbabilityEngine(),
        cfg=cfg if cfg is not None else ForecastRevisionConfig(instrument_ids=()),
        settlement_deadline=DEADLINE,
        refusals=refusals,
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

    # ... and the DEFAULT config, with no override at all, does the same --
    # counting the refusal so "no trades" stays distinguishable from "no
    # opportunities".
    refusals = RefusalCounter()
    assert _evaluate(state=state, quote=_quote(bid=0.79, ask=0.81), refusals=refusals) is None
    assert refusals.count(SHORTS_DISABLED) == 1


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


# ----------------------------------------------------------------------
# Bucket-ladder siblings: the per-instrument baseline is NOT the shared history
# ----------------------------------------------------------------------
SIBLING_INSTRUMENT_ID = "NYC-75TO80.POLYMARKET_US"


def _sibling_contract() -> MispricingContract:
    """A second ladder bucket settling off the SAME station and climate day.

    Breezy's venue sells bucket ladders, so `(settlement_station, climate_day)`
    -- the key `RevisionState` files forecast history under -- is shared by
    several tradable instruments. Their market prices are not.
    """
    return MispricingContract(
        instrument_id=SIBLING_INSTRUMENT_ID,
        facts=WeatherBucketFacts(
            settlement_station=STATION,
            climate_day=CLIMATE_DAY,
            measure=Measure.HIGH,
            lower_f=75,
            upper_f=80,
        ),
        tick_size=0.01,
    )


def _observe_ladder(state: RevisionState) -> None:
    """Tick both ladder siblings at both publications, primary contract first.

    This is the live sequencing: each instrument learns of the revision from
    its OWN quote tick, and whichever ticks first advances the shared history.
    """
    primary, sibling = _contract(), _sibling_contract()
    for published, primary_mid, sibling_mid in (
        (T0, 0.30, 0.50),
        (T1, 0.30, 0.52),
    ):
        high_f = 78.0 if published is T0 else 84.0
        horizon = 26.0 if published is T0 else 24.0
        snap = _snapshot(high_f=high_f, published_at=published, horizon=horizon)
        state.observe(contract=primary, forecast=snap, market_mid_p=primary_mid)
        state.observe(contract=sibling, forecast=snap, market_mid_p=sibling_mid)


def test_every_ladder_sibling_records_its_own_market_baseline() -> None:
    """The shared-history advance must not gate the per-instrument baseline.

    The sibling's `observe` call always loses the race to advance the shared
    `(station, climate_day)` bucket, so if baseline recording is gated behind
    that advance the sibling never gets one at all.
    """
    state = RevisionState(history_len=12)
    _observe_ladder(state)

    move = state.market_move_since(
        instrument_id=SIBLING_INSTRUMENT_ID,
        published_at=T1,
        quote=MarketQuote(
            instrument_id=SIBLING_INSTRUMENT_ID,
            bid=0.59,
            ask=0.61,
            bid_size=100.0,
            ask_size=100.0,
            ts_event=NOW,
        ),
        price_scale=1.0,
    )
    assert move is not None, "sibling has no market baseline at the publication"
    assert move == pytest.approx(0.60 - 0.52)


def test_a_ladder_sibling_nets_out_its_own_market_move() -> None:
    """`unabsorbed` for the sibling must subtract ITS move, not default to 0.0.

    With no baseline, `market_move_since` returns None, `market_dp` defaults to
    0.0 and `unabsorbed` collapses to the FULL model revision -- as though the
    book had absorbed nothing -- which systematically inflates `edge`.
    """
    state = RevisionState(history_len=12)
    _observe_ladder(state)

    sibling_quote = MarketQuote(
        instrument_id=SIBLING_INSTRUMENT_ID,
        bid=0.59,
        ask=0.61,
        bid_size=100.0,
        ask_size=100.0,
        ts_event=NOW,
    )
    decision = evaluate_instrument(
        contract=_sibling_contract(),
        quote=sibling_quote,
        now=NOW,
        current_qty=0.0,
        state=state,
        engine=WeatherProbabilityEngine(),
        # The sibling's unabsorbed move is DOWNWARD here, i.e. a SHORT_YES,
        # so this arithmetic test needs shorting explicitly enabled now that
        # it is off by default. What is under test is `unabsorbed`, not the
        # permission.
        cfg=ForecastRevisionConfig(instrument_ids=(), allow_short=True),
        settlement_deadline=DEADLINE,
    )
    assert decision is not None
    market_dp = _metric(decision, "dP_market")
    d_p = _metric(decision, "dP_model")
    assert market_dp == pytest.approx(0.60 - 0.52)
    assert market_dp != 0.0
    assert _metric(decision, "unabsorbed") == pytest.approx(d_p - market_dp)
    # The defect's signature: with no baseline, `market_dp` defaults to 0.0 and
    # `unabsorbed` is EXACTLY the full model revision. It must not be.
    assert _metric(decision, "unabsorbed") != pytest.approx(d_p)
    # This ladder bucket (75-80F) prices DOWN on a +6F revision, so its `d_p` is
    # negative while its market moved up: an opposite-sign move, which widens
    # `|unabsorbed|` rather than shrinking it. Absorption is signed, not absolute.
    assert d_p < 0
    assert _metric(decision, "absorbed_frac") < 0


# ----------------------------------------------------------------------
# Pinned characteristic of the pull seam: revisions between polls MERGE
# ----------------------------------------------------------------------
def test_a_publication_missed_between_polls_is_merged_not_scored() -> None:
    """`ForecastSource.snapshot` returns the CURRENT forecast, not a queue.

    A genuine NWS revision that lands and is superseded between two polls is
    permanently invisible: history holds only the later one, so `evaluate_instrument`
    scores ONE merged delta across what were two separate revision events. This
    test PINS that as a known characteristic of the pull seam -- it is not
    equivalence with the bundle's push path, and the correction belongs to the
    `ForecastSource` implementation (plan increment I-6), not here.
    """
    t_missed = T0 + dt.timedelta(minutes=45)
    state = RevisionState(history_len=12)
    contract = _contract()

    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=78.0, published_at=T0, horizon=26.0),
        market_mid_p=0.30,
    )
    # The 81.0F publication at `t_missed` is never polled -- it is superseded
    # by the 84.0F publication before the next `snapshot()` call.
    state.observe(
        contract=contract,
        forecast=_snapshot(high_f=84.0, published_at=T1, horizon=24.0),
        market_mid_p=0.30,
    )

    hist = state.history(contract)
    assert [s.expected_high_f for s in hist] == [78.0, 84.0]
    assert all(s.published_at != t_missed for s in hist)

    decision = _evaluate(state=state, quote=_quote(bid=0.29, ask=0.31))
    assert decision is not None
    # ONE merged +6.0F delta, not a +3.0F then a +3.0F scored separately.
    assert _metric(decision, "dT") == 6.0


# ----------------------------------------------------------------------
# Defensive None gate on the implied prices
# ----------------------------------------------------------------------
def test_a_one_sided_quote_yields_no_decision() -> None:
    """Align with `calibration_mean_reversion.decision`'s explicit None check.

    The falsy-`or` defect on `mkt` is preserved deliberately (operator ruling
    pending); what is corrected here is the MISSING `is None` gate before it,
    so a quote with no bid cannot reach the `mkt` expression at all.
    """
    state = _state_with_upward_revision()
    one_sided = MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=None,
        ask=0.31,
        bid_size=None,
        ask_size=100.0,
        ts_event=NOW,
    )
    assert _evaluate(state=state, quote=one_sided) is None


def test_a_one_sided_quote_does_not_count_as_shorts_disabled() -> None:
    """A downward revision on an asks-only book is no market, not a gag.

    BL-20 stores bid=None on a one-sided depth snapshot. If the None-side
    gate runs AFTER the SHORT_YES branch, every such tick is counted as
    shorts_disabled even though no executable short price exists.
    """
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
    refusals = RefusalCounter()
    one_sided = MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=None,
        ask=0.81,
        bid_size=None,
        ask_size=100.0,
        ts_event=NOW,
    )

    assert _evaluate(state=state, quote=one_sided, refusals=refusals) is None
    assert refusals.count(SHORTS_DISABLED) == 0
