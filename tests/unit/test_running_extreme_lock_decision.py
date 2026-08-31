"""Unit tests for `breezy.strategy.running_extreme_lock.decision.evaluate_instrument`.

Pure-function tests -- no Nautilus `Strategy`, cache, clock, or engine anywhere
in scope, matching the convention set by
`tests/unit/test_forecast_mispricing_decision.py`.

v1 scope, pinned here (see the module docstring in `decision.py` for the full
rationale): `open_tail_only=True` is the ONLY path -- an interior bucket, or
any bucket that is not an open-ended upper (HIGH) tail, must always evaluate
to `None`, never a short.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
from breezy.strategy.running_extreme_lock.decision import (
    RunningExtremeObservation,
    evaluate_instrument,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import MarketQuote, SideIntent

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
NOW = dt.datetime(2026, 8, 28, 18, 0, tzinfo=dt.UTC)
INSTRUMENT_ID = "KNYC-GE80.SIM"

#: The measured table under test -- mirrors the values pinned in
#: `docs/evidence/observation_lock_falsification_2026-08-31.md` section 2.
MODEL_P_TABLE = {
    0: 0.996829,
    1: 0.998244,
    2: 0.998798,
    3: 0.999094,
    4: 0.999418,
    5: 0.999418,
}


def _facts(
    *,
    lower_f: int | None = 80,
    upper_f: int | None = None,
    measure: Measure = Measure.HIGH,
    climate_day: dt.date = CLIMATE_DAY,
    station: str = STATION,
) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=station,
        climate_day=climate_day,
        measure=measure,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _contract(**facts_kwargs: object) -> MispricingContract:
    return MispricingContract(
        instrument_id=INSTRUMENT_ID,
        facts=_facts(**facts_kwargs),  # type: ignore[arg-type]
        tick_size=0.01,
    )


def _quote(
    *,
    ask: float | None,
    bid: float | None = 0.10,
    ts_event: dt.datetime = NOW,
    ask_size: float = 100.0,
    ask_ladder: tuple[tuple[float, float], ...] | None = None,
) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=bid,
        ask=ask,
        bid_size=100.0,
        ask_size=ask_size,
        ts_event=ts_event,
        ask_ladder=ask_ladder,
    )


def _observation(
    *,
    tmax_f: int | None,
    tmin_f: int | None = None,
    station: str = STATION,
    climate_day: dt.date = CLIMATE_DAY,
    correction_flag: bool = False,
    is_superseded: bool = False,
    published_at: dt.datetime = NOW,
) -> RunningExtremeObservation:
    return RunningExtremeObservation(
        station=station,
        climate_day=climate_day,
        tmax_f=tmax_f,
        tmin_f=tmin_f,
        correction_flag=correction_flag,
        is_superseded=is_superseded,
        published_at=published_at,
    )


def _cfg(**overrides: object) -> RunningExtremeLockConfig:
    from nautilus_trader.model.identifiers import InstrumentId

    return RunningExtremeLockConfig(
        instrument_ids=(InstrumentId.from_str("KNYC-GE80.SIM"),),
        stale_observation_hours=12.665,
        **overrides,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# The core rule: margin-conditioned model_p, only once the tail is cleared
# ---------------------------------------------------------------------------


def test_tail_already_cleared_at_margin_zero_longs_yes_with_the_margin_zero_wilson_bound() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=80),  # exactly at the tail floor -> margin 0
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.model_probability == MODEL_P_TABLE[0]


def test_margin_three_uses_the_margin_three_wilson_bound() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=83),  # 80 + 3 -> margin 3
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None
    assert decision.model_probability == MODEL_P_TABLE[3]


def test_margin_zero_and_margin_three_produce_different_model_p() -> None:
    """Proves the conditioning is real, not decorative (C5)."""
    contract = _contract(lower_f=80, upper_f=None)
    at_margin_zero = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=80),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )
    at_margin_three = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=83),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert at_margin_zero is not None
    assert at_margin_three is not None
    assert at_margin_zero.model_probability != at_margin_three.model_probability
    assert at_margin_zero.model_probability < at_margin_three.model_probability


def test_margin_beyond_the_table_clamps_to_the_five_plus_bound() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=99),  # margin 19, far past the table's max key
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None
    assert decision.model_probability == MODEL_P_TABLE[5]


def test_running_value_below_the_tail_floor_is_not_yet_a_signal() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.10),
        observation=_observation(tmax_f=79),  # one degree short of the tail
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# C6 -- correction_flag / is_superseded gate
# ---------------------------------------------------------------------------


def test_correction_flag_set_refuses_the_signal() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, correction_flag=True),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_is_superseded_refuses_the_signal() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, is_superseded=True),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# applies_to filter
# ---------------------------------------------------------------------------


def test_a_record_for_a_different_station_is_ignored() -> None:
    contract = _contract(lower_f=80, upper_f=None, station=STATION)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, station="MIA"),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_a_record_for_a_different_climate_day_is_ignored() -> None:
    contract = _contract(lower_f=80, upper_f=None, climate_day=CLIMATE_DAY)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, climate_day=dt.date(2026, 8, 27)),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# Look-ahead guard
# ---------------------------------------------------------------------------


def test_a_record_timestamped_after_now_is_refused_as_look_ahead() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, published_at=NOW + dt.timedelta(minutes=1)),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_a_record_timestamped_exactly_at_now_is_accepted() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=85, published_at=NOW),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None


# ---------------------------------------------------------------------------
# v1 scope guards -- open tail only, never an interior short
# ---------------------------------------------------------------------------


def test_running_value_above_an_interior_buckets_upper_bound_is_dead_not_a_short() -> None:
    """The running max has already blown past this bucket's cap.

    v1 only trades an open-ended upper tail (`upper_f is None`); an interior
    bucket -- capped above -- is out of scope entirely, and must never come
    back as a short.
    """
    contract = _contract(lower_f=80, upper_f=82)  # interior bucket [80, 82]
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=90),  # blew past the cap
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_an_interior_bucket_still_containing_the_running_value_is_out_of_scope_in_v1() -> None:
    contract = _contract(lower_f=80, upper_f=82)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=81),  # inside the interior bucket
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_a_low_measure_bucket_is_out_of_scope_no_tmin_table_exists() -> None:
    contract = _contract(lower_f=None, upper_f=40, measure=Measure.LOW)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=None, tmin_f=35),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_a_missing_running_high_is_not_a_signal() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50),
        observation=_observation(tmax_f=None),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# Edge is computed against the ASK, never the mid
# ---------------------------------------------------------------------------


def test_edge_is_computed_against_the_ask_not_the_mid() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    # model_p at margin 0 is 0.996829. mid = (bid + ask)/2 = (0.10 + 0.50)/2 = 0.30,
    # which would produce a very different (and wrong) edge than the ask does.
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.50, bid=0.10),
        observation=_observation(tmax_f=80),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(transaction_cost_prob=0.0),
    )

    assert decision is not None
    assert decision.market_probability == 0.50
    assert decision.edge == MODEL_P_TABLE[0] - 0.50


def test_no_ask_available_is_not_a_signal() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=None),
        observation=_observation(tmax_f=85),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# Below minimum edge
# ---------------------------------------------------------------------------


def test_below_minimum_edge_is_refused() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    # model_p ~ 0.9968; an ask of 0.99 plus cost leaves near-zero edge.
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.99),
        observation=_observation(tmax_f=80),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(min_model_edge=0.5),
    )

    assert decision is None


# ---------------------------------------------------------------------------
# Never SHORT_YES
# ---------------------------------------------------------------------------


def test_never_emits_short_yes_across_a_spread_of_inputs() -> None:
    contract_open_tail = _contract(lower_f=80, upper_f=None)
    contract_interior = _contract(lower_f=80, upper_f=82)
    cases = [
        (contract_open_tail, _observation(tmax_f=80)),
        (contract_open_tail, _observation(tmax_f=90)),
        (contract_open_tail, _observation(tmax_f=None)),
        (contract_interior, _observation(tmax_f=81)),
        (contract_interior, _observation(tmax_f=90)),
    ]
    for contract, observation in cases:
        decision = evaluate_instrument(
            contract=contract,
            quote=_quote(ask=0.50),
            observation=observation,
            now=NOW,
            model_p_table=MODEL_P_TABLE,
            cfg=_cfg(),
        )
        assert decision is None or decision.intent is SideIntent.LONG_YES


# ---------------------------------------------------------------------------
# HIGH finding: sizing/edge must reflect the depth actually consumed, not the
# level-0 tick -- every fill here is a TAKER against the live ask.
# ---------------------------------------------------------------------------


def test_thin_book_where_level_zero_looks_profitable_but_vwap_over_required_size_refuses() -> (
    None
):
    """Regression test for the HIGH finding.

    Level 0 alone (0.50, size 5) looks very profitable at margin 0
    (model_p=0.996829), but the level-0-implied sizing formula wants far more
    than 5 contracts, and the REST of the ladder is priced at 0.99. The
    VWAP-priced edge over the size actually walked must fall below
    `min_model_edge` and refuse -- a level-0-only read would wrongly accept.
    """
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(
            ask=0.50,
            ask_size=5.0,
            ask_ladder=((0.50, 5.0), (0.99, 300.0)),
        ),
        observation=_observation(tmax_f=80),  # margin 0
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),  # default min_model_edge=0.04, transaction_cost_prob=0.015
    )

    assert decision is None


def test_quantity_is_clipped_to_cumulative_available_ask_depth_when_depth_is_binding() -> None:
    """The ladder offers only 60 contracts total at a good price (0.50).

    The level-0-implied sizing formula wants 150 (clipped to `max_quantity`),
    but only 60 contracts of real depth exist -- the final quantity must be
    clipped to that 60, not to `max_quantity`.
    """
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(
            ask=0.50,
            ask_size=60.0,
            ask_ladder=((0.50, 60.0),),
        ),
        observation=_observation(tmax_f=80),  # margin 0
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None
    assert decision.quantity == 60.0
    assert decision.market_probability == 0.50


def test_deep_book_with_ample_liquidity_reproduces_the_previous_level_zero_behavior() -> None:
    """No regression: with ample depth, VWAP == the level-0 ask price and
    quantity is clipped only by `max_quantity`, exactly as the pre-fix,
    level-0-only computation would have produced.
    """
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(
            ask=0.50,
            ask_size=40.0,
            ask_ladder=((0.50, 40.0), (0.50, 500.0)),
        ),
        observation=_observation(tmax_f=80),  # margin 0
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is not None
    assert decision.market_probability == 0.50
    assert decision.quantity == 150.0  # clipped by max_quantity, not depth
    expected_edge = MODEL_P_TABLE[0] - 0.50 - 0.015  # default transaction_cost_prob
    assert decision.edge == pytest.approx(expected_edge)


# ---------------------------------------------------------------------------
# MEDIUM finding: a degenerate implied ask must be refused independently of
# `RiskManager.quote_tradable`'s downstream crossed-book check.
# ---------------------------------------------------------------------------


def test_ask_price_of_zero_is_refused_as_degenerate() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=0.0),
        observation=_observation(tmax_f=80),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None


def test_ask_price_at_or_above_one_is_refused_as_degenerate() -> None:
    contract = _contract(lower_f=80, upper_f=None)
    decision = evaluate_instrument(
        contract=contract,
        quote=_quote(ask=1.0),
        observation=_observation(tmax_f=80),
        now=NOW,
        model_p_table=MODEL_P_TABLE,
        cfg=_cfg(),
    )

    assert decision is None
