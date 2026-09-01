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
    CliPrintObservation,
    evaluate_instrument,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.freshness import SignalFreshness
from breezy.strategy.weather_common.models import MarketQuote, SideIntent
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


def _contract(instrument_id: str = INSTRUMENT_ID, **facts_kwargs: object) -> MispricingContract:
    return MispricingContract(
        instrument_id=instrument_id,
        facts=_facts(**facts_kwargs),  # type: ignore[arg-type]
        tick_size=0.01,
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
    return CliSettlementPrintLockConfig(
        instrument_ids=(InstrumentId.from_str("KNYC-80-84.SIM"),),
        stale_observation_hours=9.0,
        **overrides,  # type: ignore[arg-type]
    )


def _evaluate(
    *,
    contract: MispricingContract | None = None,
    quote: MarketQuote | None = None,
    observation: CliPrintObservation | None = None,
    now: dt.datetime = NOW,
    p_stable: float = P_STABLE,
    cfg: CliSettlementPrintLockConfig | None = None,
):
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


def test_a_corrected_record_is_refused_by_default() -> None:
    """A CCA/CCB correction sets `correction_flag`; default config refuses it."""
    assert _evaluate(observation=_observation(correction_flag=True)) is None


def test_a_corrected_record_is_tradable_when_the_config_does_not_require_a_clear_flag() -> None:
    decision = _evaluate(
        observation=_observation(correction_flag=True),
        cfg=_cfg(require_correction_flag_clear=False),
    )

    assert decision is not None


def test_a_superseded_record_is_refused_even_with_the_correction_gate_off() -> None:
    """Superseded is not configurable: the record has been replaced."""
    assert _evaluate(
        observation=_observation(is_superseded=True),
        cfg=_cfg(require_correction_flag_clear=False),
    ) is None


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
    cfg = _cfg()
    # mid 0.60 would give edge ~0.38; the ask is what we actually pay.
    decision = _evaluate(quote=_quote(ask=0.99, bid=0.21))

    assert decision is None
    tradable = _evaluate(quote=_quote(ask=0.90, bid=0.21))
    assert tradable is not None
    assert tradable.market_probability == pytest.approx(0.90)
    assert tradable.edge == pytest.approx(P_STABLE - 0.90 - cfg.transaction_cost_prob)


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
    cfg = _cfg()
    # edge == p_stable - ask - cost; pick an ask that lands just under the floor.
    ask = P_STABLE - cfg.transaction_cost_prob - cfg.min_edge_after_costs + 0.01

    assert _evaluate(quote=_quote(ask=round(ask, 2)), cfg=cfg) is None


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
