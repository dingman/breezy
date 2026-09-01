"""Construction-time guards for `CliSettlementPrintLockStrategy`.

Same load-bearing property as
`tests/unit/test_running_extreme_lock_strategy_construction.py`: this is an
OBSERVATION-kind weather strategy, and `RiskLimits.stale_observation_hours`
defaults `None`, which REFUSES every order as `observation_limit_unset` -- a
counted refusal `RefusalAlerter._conditions` (hardcoded `SHORTS_DISABLED`
only) never alerts on. A strategy wired with no bound would silently refuse
everything in live, so construction must raise instead.

Also pinned here: the `OrderBookDepth10` padding seam. An absent book side is
ten `Price(0)`/`Quantity(0)` levels starting at index 0, so `depth.bids[0]` is
a fabricated 0.00. This strategy reads books ONLY through
`breezy.strategy.depth10.market_quote_from_depth`, which renders the absent
side as `None`; as a long-only taker it needs no bid at all and TRADES an
asks-only book (see `decision.py`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.parsing import FEE_COEFFICIENT_KEY
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.cli_settlement_print_lock.config import (
    MIN_EDGE_AFTER_COSTS_BL19,
    CliSettlementPrintLockConfig,
)
from breezy.strategy.cli_settlement_print_lock.strategy import (
    ABSOLUTE_SLIPPAGE_FLOOR_PROB,
    MEASURED_P_STABLE_WILSON_LOWER,
    MEASURED_STATIONS,
    CliSettlementPrintLockStrategy,
    EdgeFloorInversionError,
    FeeCoefficientMismatchError,
    MissingFeeCoefficientSourceError,
    MissingObservationBoundError,
    NegativeEdgeFloorError,
    NoTradableMeasureError,
    UnmeasuredStationError,
    UnpricedInstrumentError,
)
from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.weather_common.costs import UnknownFeeScheduleError

INSTRUMENT_ID = InstrumentId(Symbol("nyc-80-84"), Venue("POLYMARKET_US"))

#: [MEASURED] every captured weather market carries `feeCoefficient: 0.06`.
THETA = 0.06

#: "this test did not set the key at all", distinct from "the key is present
#: and holds `None`" -- the venue writes a literal `None` when it could not
#: parse a coefficient, and those two cases are treated differently.
_ABSENT: object = object()


class _Fees:
    """A `FeeCoefficientSource` that answers, or REFUSES -- never defaults."""

    def __init__(self, theta: float | None = THETA) -> None:
        self._theta = theta

    def fee_coefficient_for(self, instrument_id: str) -> float:
        if self._theta is None:
            raise UnknownFeeScheduleError(f"no fee schedule for {instrument_id}")
        return self._theta


def _config(**overrides: object) -> CliSettlementPrintLockConfig:
    fields: dict[str, object] = {
        "instrument_ids": (INSTRUMENT_ID,),
        "stale_observation_hours": 9.0,
        "slippage_prob": 0.01,
        **overrides,
    }
    return CliSettlementPrintLockConfig(**fields)  # type: ignore[arg-type]


def _strategy(
    config: CliSettlementPrintLockConfig | None = None,
    fees: object | None = None,
) -> CliSettlementPrintLockStrategy:
    return CliSettlementPrintLockStrategy(
        _config() if config is None else config,
        _Fees() if fees is None else fees,  # type: ignore[arg-type]
    )


def test_constructing_with_stale_observation_hours_none_raises() -> None:
    with pytest.raises(MissingObservationBoundError):
        _strategy(_config(stale_observation_hours=None))


def test_constructing_with_an_explicit_bound_succeeds() -> None:
    strategy = _strategy()

    assert strategy is not None


def test_omitting_stale_observation_hours_is_a_type_error() -> None:
    """No default exists anywhere in the call chain -- an explicit operator act."""
    with pytest.raises(TypeError):
        CliSettlementPrintLockConfig(instrument_ids=(INSTRUMENT_ID,))  # type: ignore[call-arg]


def test_omitting_slippage_prob_is_a_type_error() -> None:
    """The ONLY writable cost input, and it is REQUIRED -- no default anywhere.

    Plan s2.2: the fee is not configurable at all, so this is the one term an
    operator writes, and it is named for the single thing it actually is.
    """
    with pytest.raises(TypeError):
        CliSettlementPrintLockConfig(  # type: ignore[call-arg]
            instrument_ids=(INSTRUMENT_ID,),
            stale_observation_hours=9.0,
        )


def test_omitting_the_fee_coefficient_source_is_a_type_error() -> None:
    """REQUIRED and POSITIONAL -- the `ForecastSource` precedent, exactly."""
    with pytest.raises(TypeError):
        CliSettlementPrintLockStrategy(_config())  # type: ignore[call-arg]


def test_a_none_fee_coefficient_source_raises_rather_than_defaulting() -> None:
    """A caller pushing `None` through an `Optional`-typed site still fails loud."""
    with pytest.raises(MissingFeeCoefficientSourceError):
        CliSettlementPrintLockStrategy(_config(), None)  # type: ignore[arg-type]


def test_disabling_both_measures_raises_rather_than_shipping_a_silent_no_op() -> None:
    with pytest.raises(NoTradableMeasureError):
        _strategy(_config(use_tmax=False, use_tmin=False))


def test_allow_short_defaults_false() -> None:
    assert _config().allow_short is False


def test_no_field_on_this_config_denotes_a_TOTAL_cost() -> None:
    """STRUCTURAL, and strictly stronger than the plumbing equality it replaces.

    The old assertion pinned `cfg.transaction_cost_prob == limits.
    transaction_cost_prob`: an equality between two copies of a field NOTHING
    reads. `transaction_cost_prob` appears in `weather_common/risk.py` exactly
    once -- its own definition at line 116 -- and `edge_after_costs` takes
    `cost` by injection, so `RiskManager` never reads it.

    What replaces it is the thing that actually keeps the hazard closed: there
    must be NO field in which a total cost can be written. The unsafe edit
    (`transaction_cost_prob = 0.0006` + a 0.005 floor -> trades at ask 0.99,
    which BL-19 s8.2 computes as -0.003698) then has no target at all. This
    fails RED on any future re-add, including under a new name.
    """
    names = set(CliSettlementPrintLockConfig.__struct_fields__)

    assert not any("transaction_cost" in name for name in names)
    assert not any(name in {"cost_prob", "total_cost_prob", "cost"} for name in names)
    # The ONE writable cost input, named for the single term it actually is.
    assert "slippage_prob" in names
    assert not any("fee" in name for name in names), (
        "the fee is a VENUE FACT resolved per instrument, never a config field"
    )


def test_the_two_edge_floors_are_the_bl19_value_and_cannot_invert() -> None:
    """ONE floor, spelled twice, derived from ONE source -- not two knobs.

    `RiskManager.evaluate_order` re-applies `abs(edge) < min_model_edge`
    (`risk.py:421`) to the number the decision layer already cost-netted. If
    `min_model_edge` were left ABOVE `min_edge_after_costs`, the decision layer
    would emit signals the risk layer refuses 100% of the time as
    `edge_below_minimum` -- and `RefusalAlerter._conditions`
    (`weather_common/refusals.py:134-151`) builds only a `SHORTS_DISABLED`
    condition, so nothing would alert and the strategy would look like a market
    with no opportunities.
    """
    cfg = _config()

    assert cfg.min_edge_after_costs == pytest.approx(MIN_EDGE_AFTER_COSTS_BL19)
    assert cfg.min_model_edge == pytest.approx(MIN_EDGE_AFTER_COSTS_BL19)
    assert cfg.min_model_edge <= cfg.min_edge_after_costs


def test_an_inverted_pair_of_edge_floors_raises_at_construction() -> None:
    """The invariant is enforced, not merely defaulted correctly."""
    with pytest.raises(EdgeFloorInversionError):
        _strategy(_config(min_model_edge=0.04, min_edge_after_costs=0.005))


def test_equal_floors_are_accepted_because_the_bound_is_not_strict() -> None:
    assert _strategy(_config(min_model_edge=0.005, min_edge_after_costs=0.005)) is not None


def _wilson_lower_bound(hit: int, n: int, z: float = 1.959963984540054) -> float:
    """`scripts/analysis/settlement_alignment_study.py:wilson_lower_bound`, recomputed."""
    import math

    phat = hit / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    radius = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return (centre - radius) / denom


def test_measured_p_stable_is_the_per_station_wilson_lower_bound() -> None:
    """PER-STATION, 1 failure at n=1821 -- NOT the pooled 9105/9106.

    `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.1: the five
    CLI products come from five different WFOs with independent QC practice,
    and G-01 measured materially different prelim->final revision rates across
    them (MDW 13.96%, NYC 11.79%, SFO 4.50% vs LAX/MIA passing --
    `docs/evidence/observation_lock_falsification_2026-08-31.md` s3). The
    stations are therefore not exchangeable and the pooled bound overstates
    confidence.

    This pins the DERIVATION, not the digits: change the constant without
    changing the basis and this fails.
    """
    assert MEASURED_P_STABLE_WILSON_LOWER == pytest.approx(
        _wilson_lower_bound(1820, 1821), abs=1e-6,
    )
    assert MEASURED_P_STABLE_WILSON_LOWER < 1820 / 1821


def test_measured_p_stable_charges_the_single_failure_to_one_station() -> None:
    """The one observed failure is charged in full to a single denominator.

    A ZERO-failure bound at the same n=1821 would be 0.997895 -- strictly
    HIGHER. Pinning the lower of the two makes the construction deliberately
    conservative rather than optimistic, and stops a future edit from silently
    swapping in the zero-failure reading.
    """
    zero_failure_bound = _wilson_lower_bound(1821, 1821)

    assert zero_failure_bound == pytest.approx(0.997895, abs=1e-6)
    assert MEASURED_P_STABLE_WILSON_LOWER < zero_failure_bound


def test_measured_p_stable_is_not_the_pooled_five_station_bound() -> None:
    """Pooling was REJECTED; the pooled bound must never be the shipped value."""
    pooled = _wilson_lower_bound(9105, 9106)

    assert pooled == pytest.approx(0.999378, abs=1e-6)
    assert MEASURED_P_STABLE_WILSON_LOWER < pooled


# ---------------------------------------------------------------------------
# The Depth10 padding seam
# ---------------------------------------------------------------------------


def _side(side: OrderSide, price: str, size: int) -> list[BookOrder]:
    real = BookOrder(side, Price.from_str(price), Quantity.from_int(size), 0)
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    return [real] + [filler] * 9


def _empty_side(side: OrderSide) -> list[BookOrder]:
    return [BookOrder(side, Price(0, 2), Quantity(0, 0), 0)] * 10


def test_an_asks_only_depth10_renders_the_padded_bid_as_none_not_zero() -> None:
    depth = OrderBookDepth10(
        instrument_id=INSTRUMENT_ID,
        bids=_empty_side(OrderSide.BUY),
        asks=_side(OrderSide.SELL, "0.90", 500),
        bid_counts=[0] * 10,
        ask_counts=[1] + [0] * 9,
        flags=0,
        sequence=0,
        ts_event=0,
        ts_init=0,
    )

    quote = market_quote_from_depth(depth)

    assert quote is not None
    assert quote.bid is None
    assert quote.ask == pytest.approx(0.90)
    assert quote.mid is None


# ---------------------------------------------------------------------------
# `on_start`: the fee schedule and the tick floor are resolved LOUDLY, once
# ---------------------------------------------------------------------------
#
# Driven through a REAL registered `Strategy` (the pattern
# `tests/unit/test_strategy_harness_probe.py` established): `Actor.cache` is a
# read-only Cython attribute and cannot be replaced on an instance.


def _weather_instrument(
    *,
    price_increment: str = "0.01",
    station: str = "NYC",
    fee_coefficient: object = _ABSENT,
) -> BinaryOption:
    symbol = Symbol("nyc-80-84")
    increment = Price.from_str(price_increment)
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol, Venue("POLYMARKET_US")),
        raw_symbol=symbol,
        outcome="Yes",
        description="NYC daily high 80-84F",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=8 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
        info=_info(station, fee_coefficient),
    )


def _info(station: str, fee_coefficient: object) -> dict[str, object]:
    """`Instrument.info`, carrying the venue's own theta only when asked.

    ABSENT by default, because a hand-built instrument carries no venue
    authority and the cross-check in `on_start` has nothing to compare
    against. A REAL Polymarket.us instrument always carries the key
    (`parsing.py:1225` writes it unconditionally), which is what the
    mismatch tests below exercise.
    """
    info: dict[str, object] = {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: "2026-08-28",
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 84,
    }
    if fee_coefficient is not _ABSENT:
        info[FEE_COEFFICIENT_KEY] = fee_coefficient
    return info


def _register(
    strategy: CliSettlementPrintLockStrategy, instrument: BinaryOption,
) -> None:
    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )


def test_on_start_resolves_the_fee_coefficient_onto_the_contract() -> None:
    instrument = _weather_instrument()
    strategy = _strategy()
    _register(strategy, instrument)

    strategy.on_start()

    contract = strategy._contracts[str(instrument.id)]
    assert contract.fee_coefficient == pytest.approx(THETA)


def test_an_unpriced_instrument_raises_at_on_start_rather_than_trading_free() -> None:
    """A fee schedule is a STATIC property, so the refusal belongs at the gate.

    Deferring it to decision time converts a loud startup failure into a
    permanent, SILENT no-op the refusal counter cannot see (BL-19 s8.5 null
    class N1: a pre-signal `None` never reaches `evaluate_order` and is never
    counted). `fees.py:90-92` refuses rather than trading free; this is that
    rule, moved to the gate.
    """
    instrument = _weather_instrument()
    strategy = _strategy(fees=_Fees(theta=None))
    _register(strategy, instrument)

    with pytest.raises(UnpricedInstrumentError):
        strategy.on_start()


def test_slippage_below_the_absolute_floor_raises_at_construction() -> None:
    """The floor is now ABSOLUTE and is checked before any instrument exists.

    Plan s2.2's closure proof: to trade at 0.99 an operator must write
    `slippage_prob <= 0.001302`. That used to be closed by the 0.01 tick,
    which made the guard a property of the VENUE's price granularity rather
    than of execution -- see
    `test_a_finer_tick_does_not_loosen_the_slippage_floor`.
    """
    with pytest.raises(UnpricedInstrumentError):
        _strategy(_config(slippage_prob=0.001302))


def test_slippage_exactly_at_the_floor_is_accepted_because_it_is_not_strict() -> None:
    instrument = _weather_instrument()
    strategy = _strategy(_config(slippage_prob=ABSOLUTE_SLIPPAGE_FLOOR_PROB))
    _register(strategy, instrument)

    strategy.on_start()

    assert str(instrument.id) in strategy._contracts


def test_a_finer_tick_does_not_loosen_the_slippage_floor() -> None:
    """EXECUTED COUNTER-EXAMPLE, closed.

    With `tick_size=0.001` the old per-instrument floor admitted
    `slippage_prob=0.001`, and `worst_admissible_ask(...)` then returns 0.99
    at edge +0.005302 -- the exact trade BL-19 s8.2 computes as **-0.003698**
    and the whole cost contract exists to refuse. A taker's slippage is a
    function of BOOK DEPTH and LATENCY, not of the venue's price granularity:
    halving the tick does not halve the adverse move. The floor is therefore
    `max(ABSOLUTE_SLIPPAGE_FLOOR_PROB, tick)` (BL-19 s8.5).
    """
    with pytest.raises(UnpricedInstrumentError):
        _strategy(_config(slippage_prob=0.005))

    with pytest.raises(UnpricedInstrumentError):
        _strategy(_config(slippage_prob=0.001))


def test_a_coarser_tick_still_raises_the_floor_above_the_absolute_one() -> None:
    """The absolute floor is a FLOOR, not a replacement: `max`, not a constant."""
    instrument = _weather_instrument(price_increment="0.05")
    strategy = _strategy(_config(slippage_prob=0.01))
    _register(strategy, instrument)

    with pytest.raises(UnpricedInstrumentError):
        strategy.on_start()


def test_a_non_finite_slippage_is_refused_at_construction() -> None:
    """`nan < 0.01` is `False`, so a bare comparison lets `nan` through.

    It then raises inside `trade_cost_prob` from a DATA HANDLER, mid-session,
    which is exactly the loud-at-the-gate/silent-in-flight inversion every
    other guard in this module exists to prevent.
    """
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(UnpricedInstrumentError):
            _strategy(_config(slippage_prob=bad))


# ---------------------------------------------------------------------------
# The edge floors must be NON-NEGATIVE, not merely ordered
# ---------------------------------------------------------------------------


def test_negative_edge_floors_are_refused_even_though_they_are_ordered() -> None:
    """A two-line config edit, no error today, and negative expectation.

    `EdgeFloorInversionError` checks only the RELATIVE order, so
    `min_model_edge == min_edge_after_costs == -0.02` passes it. Then
    `decision.py:430` admits ask 0.99 at edge -0.003698, `risk.py:421`'s
    `abs(edge) < min_model_edge` can never fire against a negative threshold,
    and `worst_admissible_ask` clamps `a_max` to 1.0 -- a $25.00 anchor on a
    trade with negative expectation.
    """
    with pytest.raises(NegativeEdgeFloorError):
        _strategy(_config(min_model_edge=-0.02, min_edge_after_costs=-0.02))


def test_a_single_negative_floor_is_refused_on_either_side() -> None:
    with pytest.raises(NegativeEdgeFloorError):
        _strategy(_config(min_model_edge=-0.001, min_edge_after_costs=0.005))
    with pytest.raises(NegativeEdgeFloorError):
        _strategy(_config(min_model_edge=0.0, min_edge_after_costs=-0.005))


def test_a_zero_edge_floor_is_accepted_because_zero_is_not_negative() -> None:
    """Zero expectation is a defensible (if useless) floor; negative is not."""
    assert _strategy(_config(min_model_edge=0.0, min_edge_after_costs=0.0)) is not None


def test_non_finite_edge_floors_are_refused() -> None:
    """`nan > nan` is `False`, so the inversion check passes a `nan` pair."""
    with pytest.raises(NegativeEdgeFloorError):
        _strategy(_config(min_model_edge=float("nan"), min_edge_after_costs=0.005))
    with pytest.raises(NegativeEdgeFloorError):
        _strategy(_config(min_model_edge=0.005, min_edge_after_costs=float("nan")))


# ---------------------------------------------------------------------------
# The injected theta is cross-checked against the instrument in hand
# ---------------------------------------------------------------------------


def test_on_start_refuses_an_injected_theta_that_disagrees_with_the_market() -> None:
    """`FeeCoefficientSource.fee_coefficient_for` takes an OPAQUE string.

    Nothing in the Protocol obliges an implementation to return a value ABOUT
    the instrument it was asked for -- the shipped
    `PolymarketUSFeeCoefficients` holds its OWN copied mapping
    (`run_weather_strategy_backtests.py:438-442`), so a mis-keyed or drifted
    map answers with another market's theta and the whole cost model is
    silently priced off the wrong number. `on_start` already holds the
    instrument, whose `info[FEE_COEFFICIENT_KEY]` is the venue's own
    authority; comparing them is free.
    """
    instrument = _weather_instrument(fee_coefficient="0.06")
    strategy = _strategy(fees=_Fees(theta=0.02))
    _register(strategy, instrument)

    with pytest.raises(FeeCoefficientMismatchError):
        strategy.on_start()


def test_on_start_accepts_an_injected_theta_that_matches_the_market() -> None:
    instrument = _weather_instrument(fee_coefficient="0.06")
    strategy = _strategy()
    _register(strategy, instrument)

    strategy.on_start()

    assert strategy._contracts[str(instrument.id)].fee_coefficient == pytest.approx(THETA)


def test_an_instrument_carrying_no_coefficient_at_all_skips_the_cross_check() -> None:
    """FAIL-OPEN, deliberately and narrowly: absence is not disagreement.

    A real Polymarket.us instrument ALWAYS carries the key (`parsing.py:1225`
    writes it unconditionally, `None` included). An instrument with no key at
    all is hand-built or from a venue whose wiring does not publish one, and
    carries no authority to check against.
    """
    instrument = _weather_instrument()
    strategy = _strategy()
    _register(strategy, instrument)

    strategy.on_start()

    assert strategy._contracts[str(instrument.id)].fee_coefficient == pytest.approx(THETA)


def test_an_instrument_whose_own_coefficient_is_unusable_is_refused() -> None:
    """PRESENT-but-unusable is the venue saying "unknown", never "any value".

    `parsing.py:1225` writes a literal `None` when it could not parse a
    coefficient. An injected source that nonetheless answered with a number
    did not read THIS instrument.
    """
    for unusable in (None, True, "not-a-decimal", 1.5):
        instrument = _weather_instrument(fee_coefficient=unusable)
        strategy = _strategy()
        _register(strategy, instrument)

        with pytest.raises(UnpricedInstrumentError):
            strategy.on_start()


def test_the_venue_neutral_info_key_is_the_one_the_adapter_writes() -> None:
    """DRY across a layer boundary that forbids the import.

    `weather_common.costs` must not name a venue (its own module docstring),
    so the key is re-declared there rather than imported from
    `adapters.polymarket_us.parsing`. This test is the anti-drift pin the
    import would otherwise have provided.
    """
    from breezy.strategy.weather_common.costs import INSTRUMENT_INFO_FEE_COEFFICIENT_KEY

    assert INSTRUMENT_INFO_FEE_COEFFICIENT_KEY == FEE_COEFFICIENT_KEY


def test_an_unmeasured_station_is_refused_at_on_start_not_silently_at_decision() -> None:
    """A sixth city is a routine VENUE event. It must not reach the tape at all."""
    instrument = _weather_instrument(station="BOS")
    strategy = _strategy()
    _register(strategy, instrument)

    with pytest.raises(UnmeasuredStationError):
        strategy.on_start()


def test_the_strategy_reexports_the_allow_list_beside_the_measured_constant() -> None:
    """The bound and its SUPPORT are one measurement and are read together."""
    assert MEASURED_STATIONS == frozenset({"NYC", "MIA", "MDW", "LAX", "SFO"})
    assert len(MEASURED_STATIONS) == 5
