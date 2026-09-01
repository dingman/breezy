"""Unit tests for `breezy.strategy.cli_settlement_print_lock.decision.evaluate_instrument`.

Pure-function tests, following the convention set by
`tests/unit/test_running_extreme_lock_decision.py` and
`tests/unit/test_forecast_mispricing_decision.py`: no Nautilus `Strategy`,
cache, clock, or engine in scope.

THE PROPERTY UNDER TEST, in one line: on the FINAL CLI print for a
station/climate-day, exactly ONE bucket of the ladder contains the printed
value, and that bucket -- usually an INTERIOR one -- is the only thing this
strategy ever buys.

Why an interior bucket here is not a contradiction of G-01
------------------------------------------------------------
G-01 / `docs/evidence/observation_lock_falsification_2026-08-31.md` section 3
kills the interior path AFTER THE PRELIMINARY: an interior bucket needs exact
equality, and the prelim->final revision rate FAILS on 3/5 sites (MDW 13.96%,
NYC 11.79%, SFO 4.50%). This strategy fires only AFTER THE FINAL, where that
revision has already happened -- measured `p_stable` (first final -> last
pre-settlement) 99.989% (9105/9106 pooled), section 1 of the same document.
The `is_final` gate is therefore load-bearing, not decorative, and is pinned
by `test_a_preliminary_print_is_never_traded`.

Those same cross-station differences are why the SHIPPED `p_stable` below is
NOT the pooled bound: see `P_STABLE` and
`docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.1.
"""

from __future__ import annotations

import datetime as dt

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.decision import (
    MEASURED_STATIONS,
    CliPrintObservation,
    cost_basis_anchor,
    evaluate_instrument,
    worst_admissible_ask,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.freshness import SignalFreshness
from breezy.strategy.weather_common.models import MarketQuote, SideIntent, SignalDecision
from breezy.strategy.weather_common.risk import (
    PortfolioSnapshot,
    RiskLimits,
    RiskManager,
)

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)
#: The decision clock. The CLI for climate day 2026-08-28 prints on the
#: morning of D+1 and the venue settles at 08:00 ET that same morning.
NOW = dt.datetime(2026, 8, 29, 9, 0, tzinfo=dt.UTC)
INSTRUMENT_ID = "KNYC-80-84.SIM"

#: The measured stability of the FINAL print, as the PER-STATION
#: Wilson-95%-LOWER bound: 1 failure at n=1821 -- mirrors
#: `strategy.MEASURED_P_STABLE_WILSON_LOWER`. Basis and the rejection of the
#: pooled 9105/9106 five-station bound (0.999378):
#: `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` section 8.1,
#: over counts from
#: `docs/evidence/observation_lock_falsification_2026-08-31.md` section 1.
#: The derivation itself is pinned by
#: `test_measured_p_stable_is_the_per_station_wilson_lower_bound`
#: in `test_cli_settlement_print_lock_strategy_construction.py`.
P_STABLE = 0.996896

#: [MEASURED] 20/20 captured weather markets carry `feeCoefficient: 0.06`.
THETA = 0.06
#: UNMEASURED placeholder, floored at one tick -- BL-19 s8.6 / s2.8 falsifier 1.
SLIPPAGE = 0.01


def _facts(
    *,
    lower_f: int | None = 80,
    upper_f: int | None = 84,
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


def _contract(
    instrument_id: str = INSTRUMENT_ID,
    fee_coefficient: float | None = THETA,
    **facts_kwargs: object,
) -> MispricingContract:
    return MispricingContract(
        instrument_id=instrument_id,
        facts=_facts(**facts_kwargs),  # type: ignore[arg-type]
        tick_size=0.01,
        fee_coefficient=fee_coefficient,
    )


def _quote(
    *,
    ask: float | None = 0.90,
    bid: float | None = 0.88,
    ts_event: dt.datetime = NOW,
    ask_size: float = 500.0,
    mid: float | None = None,
) -> MarketQuote:
    return MarketQuote(
        instrument_id=INSTRUMENT_ID,
        bid=bid,
        ask=ask,
        bid_size=500.0 if bid is not None else None,
        ask_size=ask_size if ask is not None else None,
        ts_event=ts_event,
        mid=mid,
    )


def _observation(
    *,
    tmax_f: int | None = 82,
    tmin_f: int | None = 64,
    station: str = STATION,
    climate_day: dt.date = CLIMATE_DAY,
    is_final: bool = True,
    correction_flag: bool = False,
    is_superseded: bool = False,
    published_at: dt.datetime | None = None,
) -> CliPrintObservation:
    return CliPrintObservation(
        station=station,
        climate_day=climate_day,
        tmax_f=tmax_f,
        tmin_f=tmin_f,
        is_final=is_final,
        correction_flag=correction_flag,
        is_superseded=is_superseded,
        published_at=NOW - dt.timedelta(hours=2) if published_at is None else published_at,
    )


def _cfg(**overrides: object) -> CliSettlementPrintLockConfig:
    fields: dict[str, object] = {
        "instrument_ids": (InstrumentId.from_str("KNYC-80-84.SIM"),),
        "stale_observation_hours": 9.0,
        "slippage_prob": SLIPPAGE,
        **overrides,
    }
    return CliSettlementPrintLockConfig(**fields)  # type: ignore[arg-type]


def _evaluate(
    *,
    contract: MispricingContract | None = None,
    quote: MarketQuote | None = None,
    observation: CliPrintObservation | None = None,
    now: dt.datetime = NOW,
    p_stable: float = P_STABLE,
    cfg: CliSettlementPrintLockConfig | None = None,
) -> SignalDecision | None:
    return evaluate_instrument(
        contract=_contract() if contract is None else contract,
        quote=_quote() if quote is None else quote,
        observation=_observation() if observation is None else observation,
        now=now,
        p_stable=p_stable,
        cfg=_cfg() if cfg is None else cfg,
    )


# ---------------------------------------------------------------------------
# The core rule: buy the ONE bucket that contains the printed value
# ---------------------------------------------------------------------------


def test_printed_value_inside_an_interior_bucket_longs_yes() -> None:
    """The lead case: 82F printed, bucket [80, 84] -- an INTERIOR bucket."""
    decision = _evaluate(
        contract=_contract(lower_f=80, upper_f=84),
        observation=_observation(tmax_f=82),
    )

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES
    assert decision.model_probability == pytest.approx(P_STABLE)
    assert decision.metadata["printed_f"] == 82


def test_printed_value_inside_the_open_upper_tail_longs_yes() -> None:
    decision = _evaluate(
        contract=_contract(lower_f=90, upper_f=None),
        observation=_observation(tmax_f=97),
    )

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES


def test_printed_value_inside_the_open_lower_tail_longs_yes() -> None:
    decision = _evaluate(
        contract=_contract(lower_f=None, upper_f=74),
        observation=_observation(tmax_f=61),
    )

    assert decision is not None
    assert decision.intent is SideIntent.LONG_YES


def test_printed_value_on_the_lower_boundary_is_inside_the_bucket() -> None:
    """`WeatherBucketFacts.contains` is closed at both finite ends."""
    decision = _evaluate(
        contract=_contract(lower_f=80, upper_f=84),
        observation=_observation(tmax_f=80),
    )

    assert decision is not None
    assert decision.metadata["boundary_margin_f"] == 0


def test_printed_value_on_the_upper_boundary_is_inside_the_bucket() -> None:
    decision = _evaluate(
        contract=_contract(lower_f=80, upper_f=84),
        observation=_observation(tmax_f=84),
    )

    assert decision is not None
    assert decision.metadata["boundary_margin_f"] == 0


def test_printed_value_outside_this_bucket_is_not_traded() -> None:
    assert _evaluate(
        contract=_contract(lower_f=80, upper_f=84),
        observation=_observation(tmax_f=85),
    ) is None


def test_exactly_one_bucket_of_a_tiling_ladder_is_selected() -> None:
    """The exclusive-bucket property, on the real ladder shape.

    A venue ladder tiles the line with closed, non-overlapping intervals
    (`docs/.../weather_bucket_facts` -- 114/114 captured groups tile). The
    printed value must select exactly one rung, for EVERY printed value the
    ladder covers.
    """
    ladder = [
        _contract(instrument_id="rung-le-79", lower_f=None, upper_f=79),
        _contract(instrument_id="rung-80-84", lower_f=80, upper_f=84),
        _contract(instrument_id="rung-85-89", lower_f=85, upper_f=89),
        _contract(instrument_id="rung-ge-90", lower_f=90, upper_f=None),
    ]

    for printed in range(60, 101):
        selected = [
            contract.instrument_id
            for contract in ladder
            if _evaluate(contract=contract, observation=_observation(tmax_f=printed)) is not None
        ]
        assert len(selected) == 1, f"printed={printed} selected {selected}"


def test_an_adjacent_rung_does_not_also_contain_a_boundary_value() -> None:
    assert _evaluate(
        contract=_contract(instrument_id="rung-le-79", lower_f=None, upper_f=79),
        observation=_observation(tmax_f=80),
    ) is None


# ---------------------------------------------------------------------------
# Record-shape gates
# ---------------------------------------------------------------------------


def test_a_preliminary_print_is_never_traded() -> None:
    """G-01: the interior path is dead AFTER THE PRELIMINARY. Only finals fire."""
    assert _evaluate(observation=_observation(is_final=False)) is None


def test_a_corrected_record_is_always_refused() -> None:
    """A CCA/CCB correction sets `correction_flag`. Refusal is UNCONDITIONAL."""
    assert _evaluate(observation=_observation(correction_flag=True)) is None


def test_the_correction_gate_cannot_be_turned_off_because_there_is_no_knob() -> None:
    """A corrected record is OUTSIDE the `p_stable` denominator entirely.

    `p_stable` is measured first-final -> last-pre-settlement, so a CORRECTION
    **is** the failure event being counted -- 1 in 1821 station-days. Trading
    one is not "the same edge with a caveat", it is the complement of the
    measurement. That is the identical argument `config.py` already makes for
    `require_final_print`: a flag whose only alternative setting trades a
    measured-dead path is not a knob. So the field is GONE, and this test pins
    its absence rather than pinning an off-setting as legitimate.
    """
    assert not hasattr(CliSettlementPrintLockConfig, "require_correction_flag_clear")
    assert "require_correction_flag_clear" not in set(
        CliSettlementPrintLockConfig.__struct_fields__,
    )
    with pytest.raises(TypeError):
        _cfg(require_correction_flag_clear=False)


def test_a_superseded_record_is_refused_unconditionally_too() -> None:
    """Superseded is not configurable either: the record has been replaced."""
    assert _evaluate(observation=_observation(is_superseded=True)) is None


def test_a_record_for_another_station_is_ignored() -> None:
    assert _evaluate(observation=_observation(station="MIA")) is None


def test_a_record_for_another_climate_day_is_ignored() -> None:
    assert _evaluate(observation=_observation(climate_day=dt.date(2026, 8, 27))) is None


def test_a_record_with_no_printed_extreme_is_ignored() -> None:
    assert _evaluate(observation=_observation(tmax_f=None)) is None


def test_a_future_dated_record_is_refused_as_look_ahead() -> None:
    assert _evaluate(
        observation=_observation(published_at=NOW + dt.timedelta(minutes=1)),
    ) is None


def test_a_record_published_exactly_now_is_tradable() -> None:
    assert _evaluate(observation=_observation(published_at=NOW)) is not None


# ---------------------------------------------------------------------------
# Staleness is the RISK layer's gate, not the decision layer's
# ---------------------------------------------------------------------------


def test_an_old_print_still_produces_a_decision_because_age_is_not_a_decision_gate() -> None:
    """A 6h-old final print is the NORMAL case for this strategy.

    The print lands ~05:00-13:00Z and the position is held to settlement, so
    the decision layer must not treat age as a defect. Liveness is owned by
    `RiskLimits.stale_observation_hours` -- pinned in the companion test
    below, which is the same bound's other side.
    """
    decision = _evaluate(
        observation=_observation(published_at=NOW - dt.timedelta(hours=6)),
    )

    assert decision is not None


def test_a_stale_print_is_refused_by_the_risk_layer_not_by_the_decision() -> None:
    contract = _contract()
    limits = RiskLimits(stale_observation_hours=9.0)
    risk = RiskManager(limits, {contract.instrument_id: contract})

    verdict = risk.evaluate_order(
        contract=contract,
        signed_qty_delta=10.0,
        hours_to_settlement=3.0,
        signal_age=SignalFreshness.observation(9.5),
        edge=0.08,
        portfolio=PortfolioSnapshot(),
        quote=_quote(),
        quote_age_minutes=1.0,
    )

    assert verdict.allowed is False
    assert verdict.reason == "stale_observation"


# ---------------------------------------------------------------------------
# Book shape: long-only taker needs an ask and nothing else
# ---------------------------------------------------------------------------


def test_an_asks_only_book_is_traded_because_a_long_only_taker_needs_no_bid() -> None:
    """`OrderBookDepth10` pads the absent bid side; `market_quote_from_depth`
    renders that as `bid=None`, never 0.00. A BUY takes the ask."""
    decision = _evaluate(quote=_quote(bid=None))

    assert decision is not None
    assert decision.market_probability == pytest.approx(0.90)


def test_a_book_with_no_asks_at_all_is_not_traded() -> None:
    assert _evaluate(quote=_quote(ask=None, bid=0.88)) is None


def test_a_degenerate_zero_ask_is_not_free_money() -> None:
    assert _evaluate(quote=_quote(ask=0.0, bid=None)) is None


def test_an_ask_at_or_above_full_payout_is_never_traded() -> None:
    assert _evaluate(quote=_quote(ask=1.0, bid=0.99)) is None


def test_edge_is_priced_against_the_ask_never_the_midpoint() -> None:
    """A wide book whose MID would clear the floor but whose ASK does not."""
    # mid 0.60 would give edge ~0.38; the ask is what we actually pay.
    decision = _evaluate(quote=_quote(ask=0.99, bid=0.21))

    assert decision is None
    tradable = _evaluate(quote=_quote(ask=0.90, bid=0.21))
    assert tradable is not None
    assert tradable.market_probability == pytest.approx(0.90)
    # BL-19 s8.2's cost model, not a scalar: fee(0.90) = 0.06*0.90*0.10 = 0.0054,
    # plus the 0.01 slippage placeholder.
    assert tradable.edge == pytest.approx(P_STABLE - 0.90 - 0.0154, abs=1e-9)


# ---------------------------------------------------------------------------
# Measure selection, probability floor, edge floor, sizing
# ---------------------------------------------------------------------------


def test_a_low_measure_bucket_is_not_traded_by_default() -> None:
    assert _evaluate(
        contract=_contract(measure=Measure.LOW, lower_f=60, upper_f=64),
        observation=_observation(tmax_f=82, tmin_f=62),
    ) is None


def test_a_low_measure_bucket_reads_tmin_when_enabled() -> None:
    decision = _evaluate(
        contract=_contract(measure=Measure.LOW, lower_f=60, upper_f=64),
        observation=_observation(tmax_f=82, tmin_f=62),
        cfg=_cfg(use_tmin=True),
    )

    assert decision is not None
    assert decision.metadata["printed_f"] == 62
    assert decision.metadata["measure"] == "low"


def test_a_high_measure_bucket_is_skipped_when_tmax_is_disabled() -> None:
    assert _evaluate(cfg=_cfg(use_tmax=False, use_tmin=True)) is None


def test_a_p_stable_below_the_configured_floor_is_not_traded() -> None:
    assert _evaluate(p_stable=0.95, cfg=_cfg(min_stable_prob=0.97)) is None


def test_an_ask_too_expensive_for_the_edge_floor_is_not_traded() -> None:
    """BL-19 s8.2 exactly: 0.98 is admitted, 0.99 is refused."""
    assert _evaluate(quote=_quote(ask=0.98, bid=None)) is not None
    assert _evaluate(quote=_quote(ask=0.99, bid=None)) is None


def test_the_edge_at_the_two_decidable_ticks_is_the_bl19_derivation() -> None:
    admitted = _evaluate(quote=_quote(ask=0.98, bid=None))

    assert admitted is not None
    # BL-19 s8.2: +0.005720 at 0.98, -0.003698 at 0.99.
    assert admitted.edge == pytest.approx(0.005720, abs=1e-6)
    assert P_STABLE - 0.99 - (THETA * 0.99 * 0.01 + SLIPPAGE) == pytest.approx(
        -0.003698, abs=1e-6,
    )


def test_quantity_is_a_whole_number_of_contracts() -> None:
    decision = _evaluate()

    assert decision is not None
    assert decision.quantity == int(decision.quantity)
    assert decision.quantity >= 1.0


def test_quantity_never_exceeds_the_visible_ask_depth() -> None:
    decision = _evaluate(quote=_quote(ask_size=7.0))

    assert decision is not None
    assert decision.quantity == 7.0


def test_no_visible_ask_depth_is_not_a_trade() -> None:
    assert _evaluate(quote=_quote(ask_size=0.0)) is None


def test_the_decision_never_constructs_a_short_intent() -> None:
    """Swept over every input shape above -- LONG_YES or nothing, never SHORT."""
    for printed in range(55, 106):
        for ask in (0.05, 0.5, 0.9, 0.94, 0.99):
            decision = _evaluate(
                observation=_observation(tmax_f=printed),
                quote=_quote(ask=ask, bid=None),
            )
            if decision is not None:
                assert decision.intent is SideIntent.LONG_YES


# ---------------------------------------------------------------------------
# ITEM 3 -- the measured-station allow-list, fail closed
# ---------------------------------------------------------------------------


def test_the_allow_list_is_exactly_the_five_measured_stations() -> None:
    """`MEASURED_P_STABLE_WILSON_LOWER` was measured on these five and no others.

    `docs/evidence/observation_lock_falsification_2026-08-31.md` s1:
    2020-12..2026-08, KNYC/KMIA/KMDW/KLAX/KSFO. The vocabulary here is the
    registry's `cli_location` (`src/breezy/registry/sites.toml`), which is what
    `parsing._weather_info` writes into `SETTLEMENT_STATION_KEY` and therefore
    what `WeatherBucketFacts.settlement_station` carries -- NOT the ICAO form.
    """
    assert MEASURED_STATIONS == frozenset({"NYC", "MIA", "MDW", "LAX", "SFO"})
    assert isinstance(MEASURED_STATIONS, frozenset)


def test_a_station_outside_the_measured_set_is_refused() -> None:
    """A sixth city is a routine VENUE event, not a code change. Fail closed.

    The commit's own argument for the per-station bound is that the five WFOs
    are NOT exchangeable (measured prelim->final revision rates 4.50%-13.96%).
    That argument refutes extrapolation to an UNMEASURED sixth office far more
    strongly than it refutes pooling across the five.
    """
    assert _evaluate(
        contract=_contract(station="BOS"),
        observation=_observation(station="BOS"),
    ) is None


def test_every_measured_station_is_tradable() -> None:
    """The allow-list must not accidentally brick a station that WAS measured."""
    for station in sorted(MEASURED_STATIONS):
        decision = _evaluate(
            contract=_contract(station=station),
            observation=_observation(station=station),
        )
        assert decision is not None, station


def test_the_allow_list_is_not_configurable() -> None:
    """Hard-coded exactly as `is_final` is -- see `config.py`'s no-knob argument."""
    assert not any(
        "station" in name for name in CliSettlementPrintLockConfig.__struct_fields__
    )


# ---------------------------------------------------------------------------
# ITEM 2 -- the decision call site: fee by injection, never by config
# ---------------------------------------------------------------------------


def test_an_unresolved_fee_coefficient_is_a_no_trade_never_a_free_trade() -> None:
    """The independent-reuse guard, same posture as the degenerate-ask guard.

    Unreachable through `strategy.py`, which raises `UnpricedInstrumentError`
    at `on_start`. `adapters.polymarket_us.fees`: "a market whose coefficient
    we could not parse raises rather than trading free."
    """
    assert _evaluate(contract=_contract(fee_coefficient=None)) is None


def test_the_decision_publishes_the_cost_terms_separately_for_bl19_s8_5() -> None:
    """`edge at slippage in {0.000, 0.010}` must be reconstructible OFFLINE.

    With `market_probability` (the ask), `model_probability`, `fee_prob` and
    `slippage_prob` on the record, a corrected slippage figure re-derives the
    threshold from the same tape -- no re-capture. That is the entire reason
    the two cost terms are kept separate and named.
    """
    decision = _evaluate(quote=_quote(ask=0.90, bid=None))

    assert decision is not None
    assert decision.metadata["fee_coefficient"] == pytest.approx(THETA)
    assert decision.metadata["fee_prob"] == pytest.approx(0.0054, abs=1e-9)
    assert decision.metadata["slippage_prob"] == pytest.approx(SLIPPAGE)

    fee_prob = decision.metadata["fee_prob"]
    slippage = decision.metadata["slippage_prob"]
    assert isinstance(fee_prob, float)
    assert isinstance(slippage, float)
    edge_at_zero_slippage = decision.edge + slippage
    assert edge_at_zero_slippage == pytest.approx(
        decision.model_probability - decision.market_probability - fee_prob, abs=1e-12,
    )


def test_no_total_cost_scalar_can_be_written_at_the_decision_layer() -> None:
    """The unsafe edit -- `transaction_cost_prob = 0.0006` -> trades at 0.99 --
    has no target: the field does not exist. Structural, not a value check."""
    names = set(CliSettlementPrintLockConfig.__struct_fields__)

    assert not any("transaction_cost" in name for name in names)
    assert "slippage_prob" in names


# ---------------------------------------------------------------------------
# ITEM 1 -- constant-dollar-cost-basis sizing
# ---------------------------------------------------------------------------


def test_the_worst_admissible_ask_is_the_exact_root_floored_to_the_tick() -> None:
    """Plan s1.5 step 1: 0.06 a^2 - 1.06 a + 0.981896 = 0 -> a = 0.98076408.

    Pinned so a future edit cannot drift the anchor silently.
    """
    exact = worst_admissible_ask(
        model_p=P_STABLE,
        fee_coefficient=THETA,
        slippage_prob=SLIPPAGE,
        min_edge_after_costs=0.005,
        tick_size=None,
    )
    on_grid = worst_admissible_ask(
        model_p=P_STABLE,
        fee_coefficient=THETA,
        slippage_prob=SLIPPAGE,
        min_edge_after_costs=0.005,
        tick_size=0.01,
    )

    # The plan prints 0.98076408; the exact root is 0.98076404395..., and the
    # difference is the plan's own intermediate rounding of sqrt to 8dp
    # (0.94230831). Pinned to 1e-7 -- the digits the derivation actually
    # determines -- with `test_..._solves_the_gate_equation_it_claims_to`
    # pinning the root EXACTLY against the equation rather than against a
    # transcribed decimal.
    assert exact == pytest.approx(0.98076408, abs=1e-7)
    assert on_grid == pytest.approx(0.98, abs=1e-12)


def test_the_worst_admissible_ask_solves_the_gate_equation_it_claims_to() -> None:
    """Not merely the digits: the root must satisfy `edge(a) == min_edge`."""
    a = worst_admissible_ask(
        model_p=P_STABLE,
        fee_coefficient=THETA,
        slippage_prob=SLIPPAGE,
        min_edge_after_costs=0.005,
        tick_size=None,
    )
    edge = P_STABLE - a - (THETA * a * (1.0 - a) + SLIPPAGE)

    assert edge == pytest.approx(0.005, abs=1e-12)


def test_the_cost_basis_anchor_is_the_base_clip_at_the_worst_admissible_ask() -> None:
    """Plan s1.5 step 2: A = 25 * (0.98 + fee(0.98)) = 25 * 0.981176 = $24.5294.

    NOT a new risk budget and NOT a config field -- it is the cost basis the
    shipped `base_quantity` already commits at the tightest admissible entry.
    A dollar-denominated per-decision knob is one rename away from an
    operator-reserved control, so it stays derived, in code.
    """
    anchor = cost_basis_anchor(base_quantity=25.0, worst_ask=0.98, fee_coefficient=THETA)

    assert anchor == pytest.approx(24.5294, abs=1e-4)


def test_the_anchor_is_not_a_config_field() -> None:
    names = set(CliSettlementPrintLockConfig.__struct_fields__)

    assert not any("cost_basis" in name or "notional_per_decision" in name for name in names)
    assert "edge_qty_scale" not in names


@pytest.mark.parametrize(
    ("ask", "expected_qty"),
    [
        (0.98, 25.0),
        (0.97, 25.0),
        (0.95, 25.0),
        (0.90, 27.0),
        (0.80, 30.0),
        (0.65, 36.0),
        (0.50, 47.0),
        (0.21, 111.0),
        (0.02, 150.0),
    ],
)
def test_sizing_pins_the_plan_s1_5_table(ask: float, expected_qty: float) -> None:
    """Every row of the design's ask -> quantity table, as a regression pin."""
    decision = _evaluate(quote=_quote(ask=ask, bid=None, ask_size=5000.0))

    assert decision is not None
    assert decision.quantity == expected_qty


def test_cost_basis_is_constant_across_the_whole_admitted_price_range() -> None:
    """THE invariant. Dollars at risk per decision, not contracts, are flat.

    A systematic mapping fault can no longer escalate its own capital
    consumption by producing a larger apparent edge. Floor() loses at most one
    contract's premium, so the basis sits in `(A - premium, A]` wherever
    neither `max_quantity` nor the visible depth binds.
    """
    anchor = cost_basis_anchor(base_quantity=25.0, worst_ask=0.98, fee_coefficient=THETA)

    for i in range(16, 99):  # ask 0.16 .. 0.98; below 0.16 the 150 cap binds
        ask = i / 100.0
        decision = _evaluate(quote=_quote(ask=ask, bid=None, ask_size=5000.0))
        if decision is None:
            continue
        premium = ask + THETA * ask * (1.0 - ask)
        basis = decision.quantity * premium
        assert basis <= anchor + 1e-9, ask
        assert basis > anchor - premium - 1e-9, ask


def test_capital_at_risk_no_longer_peaks_in_the_middle_of_the_band() -> None:
    """The shipped defect, stated in dollars: $26.49 at 0.98 vs ~$101 at 0.66.

    Under the replacement, the 0.66 basis must not exceed the 0.98 basis.
    """
    tight = _evaluate(quote=_quote(ask=0.98, bid=None, ask_size=5000.0))
    wide = _evaluate(quote=_quote(ask=0.66, bid=None, ask_size=5000.0))

    assert tight is not None
    assert wide is not None
    tight_basis = tight.quantity * (0.98 + THETA * 0.98 * 0.02)
    wide_basis = wide.quantity * (0.66 + THETA * 0.66 * 0.34)

    assert wide_basis <= tight_basis + 1e-9
    # The OLD rule committed 3.8x more here. Pin the ratio is now ~1.0.
    assert wide_basis / tight_basis > 0.9


def test_quantity_is_not_strictly_increasing_in_edge() -> None:
    """The regression guard for the replaced affine-in-edge term.

    The old rule was `base + 400 * edge`: STRICTLY increasing in edge at every
    point below the cap. The replacement is flat over 0.98 -> 0.95, so a
    re-introduction of edge-proportional sizing fails here.
    """
    sizes = [
        _evaluate(quote=_quote(ask=ask, bid=None, ask_size=5000.0))
        for ask in (0.98, 0.97, 0.96, 0.95)
    ]

    assert all(decision is not None for decision in sizes)
    quantities = [decision.quantity for decision in sizes if decision is not None]
    assert quantities == [25.0, 25.0, 25.0, 25.0]


def test_sizing_never_exceeds_the_cap_the_depth_or_goes_negative() -> None:
    for i in range(1, 100):
        ask = i / 100.0
        decision = _evaluate(quote=_quote(ask=ask, bid=None, ask_size=40.0))
        if decision is None:
            continue
        assert 1.0 <= decision.quantity <= 40.0
        assert decision.quantity == int(decision.quantity)


def test_nothing_admitted_before_the_change_is_refused_by_the_new_sizer() -> None:
    """Only SIZE changes. Every ask the edge gate admits still trades.

    Deep enough book that depth never binds; the sizer must never floor to 0.
    """
    for i in range(1, 99):
        ask = i / 100.0
        edge = P_STABLE - ask - (THETA * ask * (1.0 - ask) + SLIPPAGE)
        decision = _evaluate(quote=_quote(ask=ask, bid=None, ask_size=5000.0))
        if edge >= 0.005:
            assert decision is not None, ask
        else:
            assert decision is None, ask


# ---------------------------------------------------------------------------
# ITEM 6 -- `conviction` is structurally 0.0 on every interior bucket
# ---------------------------------------------------------------------------


def test_conviction_is_identically_zero_on_a_real_venue_interior_bucket() -> None:
    """The captured ladder's interiors are TWO-DEGREE CLOSED intervals.

    Slug `gte56lt57f` decodes to `[56, 57]` (`symbology.assert_bounds_cross_checked`
    -- "'lt' means '<= N' inside a range"), so `_boundary_margin_f` is
    `min(printed - lower, upper - printed)` over a pair that always contains a
    zero. There is no "middle" for an interior print to sit in.
    """
    for lower, upper in ((56, 57), (80, 81), (72, 73)):
        for printed in (lower, upper):
            decision = _evaluate(
                contract=_contract(lower_f=lower, upper_f=upper),
                observation=_observation(tmax_f=printed),
            )
            assert decision is not None, (lower, upper, printed)
            assert decision.conviction == 0.0
            assert decision.metadata["boundary_margin_f"] == 0


def test_conviction_is_only_ever_nonzero_in_an_open_tail() -> None:
    """`CONVICTION_FULL_MARGIN_F = 2` is reachable ONLY where a bound is absent."""
    tail = _evaluate(
        contract=_contract(lower_f=None, upper_f=74),
        observation=_observation(tmax_f=61),
    )

    assert tail is not None
    assert tail.conviction == 1.0


def test_sizing_does_not_consume_conviction() -> None:
    """Sizing UP on boundary margin would FABRICATE evidence.

    No measured margin-keyed table exists for the FINAL print (BL-19 s8.1(1)),
    so a margin-conditioned size is a number with no denominator behind it.
    An open tail (conviction 1.0) and an interior (conviction 0.0) at the SAME
    ask must therefore size identically.
    """
    interior = _evaluate(
        contract=_contract(lower_f=80, upper_f=81),
        observation=_observation(tmax_f=80),
        quote=_quote(ask=0.90, bid=None, ask_size=5000.0),
    )
    tail = _evaluate(
        contract=_contract(lower_f=None, upper_f=74),
        observation=_observation(tmax_f=61),
        quote=_quote(ask=0.90, bid=None, ask_size=5000.0),
    )

    assert interior is not None
    assert tail is not None
    assert interior.conviction == 0.0
    assert tail.conviction == 1.0
    assert interior.quantity == tail.quantity
