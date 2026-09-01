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

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.strategy import (
    MEASURED_P_STABLE_WILSON_LOWER,
    CliSettlementPrintLockStrategy,
    MissingObservationBoundError,
    NoTradableMeasureError,
)
from breezy.strategy.depth10 import market_quote_from_depth

INSTRUMENT_ID = InstrumentId(Symbol("nyc-80-84"), Venue("POLYMARKET_US"))


def _config(**overrides: object) -> CliSettlementPrintLockConfig:
    fields: dict[str, object] = {
        "instrument_ids": (INSTRUMENT_ID,),
        "stale_observation_hours": 9.0,
        **overrides,
    }
    return CliSettlementPrintLockConfig(**fields)  # type: ignore[arg-type]


def test_constructing_with_stale_observation_hours_none_raises() -> None:
    with pytest.raises(MissingObservationBoundError):
        CliSettlementPrintLockStrategy(_config(stale_observation_hours=None))


def test_constructing_with_an_explicit_bound_succeeds() -> None:
    strategy = CliSettlementPrintLockStrategy(_config())

    assert strategy is not None


def test_omitting_stale_observation_hours_is_a_type_error() -> None:
    """No default exists anywhere in the call chain -- an explicit operator act."""
    with pytest.raises(TypeError):
        CliSettlementPrintLockConfig(instrument_ids=(INSTRUMENT_ID,))  # type: ignore[call-arg]


def test_disabling_both_measures_raises_rather_than_shipping_a_silent_no_op() -> None:
    with pytest.raises(NoTradableMeasureError):
        CliSettlementPrintLockStrategy(_config(use_tmax=False, use_tmin=False))


def test_allow_short_defaults_false() -> None:
    assert _config().allow_short is False


def test_edge_and_cost_floors_default_to_the_inherited_risk_limits() -> None:
    """BL-19 is pending: these must be config, not literals, so the decision
    lands as a config change rather than a rewrite."""
    from breezy.strategy.weather_common.risk import RiskLimits

    limits = RiskLimits()
    cfg = _config()

    assert cfg.min_model_edge == limits.min_model_edge
    assert cfg.min_edge_after_costs == limits.min_model_edge
    assert cfg.transaction_cost_prob == limits.transaction_cost_prob


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
