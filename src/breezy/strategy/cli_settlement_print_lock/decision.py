"""The preserved trading decision: the FINAL CLI print has already named the
settlement value, and exactly one ladder bucket contains it.

Edge hypothesis (see
``docs/strategies/breezy_strategy_cli_settlement_print_lock.md``): Polymarket.us
weather contracts settle on the local WFO Daily Climate Report (CLI), not on a
weather app and not on the venue clock. Once the FINAL CLI for climate day D
has printed value ``V``, the bucket containing ``V`` can only settle NO if a
later correction moves the number across a bucket boundary before settlement.
This module is PURE -- no I/O, no clock, no order submission -- mirroring
``breezy.strategy.running_extreme_lock.decision.evaluate_instrument``.

WHY AN INTERIOR BUCKET IS SOUND HERE AND DEAD IN ``running_extreme_lock``
--------------------------------------------------------------------------
``running_extreme_lock`` ships ``open_tail_only=True`` because an interior
bucket requires EXACT EQUALITY between the value it holds now and the value at
settlement, and the pre-registered prelim->final revision study FAILS that on
3/5 sites (MDW 13.96%, NYC 11.79%, SFO 4.50% --
``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 3).
Those revisions are the PRELIMINARY becoming the FINAL. This strategy fires
only AFTER the final, so the revision the study measures has already happened.
On the same archive, measured from the FIRST FINAL to the last pre-settlement
value: ``p_stable`` = 99.989% (9105/9106 POOLED -- the shipped constant is the
per-station bound, see MODEL PROBABILITY below), and 98.66% (9041/9164) of
station-days leave a legal trading window above the configured
``min_hours_to_settlement`` (section 1). The two results do not conflict --
they measure two different products.

That makes the ``is_final`` gate LOAD-BEARING, not decorative: dropping it
turns this strategy into the measured-dead interior-after-preliminary path. It
is hard-coded here rather than exposed as config, for the reason spelled out
in ``config.py``.

MODEL PROBABILITY
-----------------
``model_probability`` is ``1 - p_revise_out_of_bucket``, supplied by the
caller as ``p_stable`` -- never computed here, exactly as
``running_extreme_lock`` takes its ``model_p_table`` as an input. The caller
(``strategy.py``) supplies a fixed, cited constant: the PER-STATION
Wilson-95%-LOWER bound -- one observed failure at n = 1821 station-days --
never the point estimate, and never the POOLED bound of the raw 9105/9106.
Pooling assumes the five stations are exchangeable, which G-01 refutes (see
``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` section 8 and the
``MEASURED_P_STABLE_WILSON_LOWER`` comment in ``strategy.py``). A caller that
supplies the pooled bound is over-confident by construction. See that module
for why the number is a constant and not a runtime query.

Unlike ``running_extreme_lock``'s margin-conditioned table, there is exactly
ONE published figure here -- no per-margin conditioning of the FINAL print's
stability has been measured. The distance from the printed value to the
nearest bucket boundary is therefore carried as CONVICTION and metadata only,
never smuggled into the probability: a print sitting on a boundary loses the
bucket to a 1F correction, while a print in the middle survives one, and that
is a real difference in exposure quality even though no measured probability
yet distinguishes them. Inventing a margin-conditioned table for the final
would be fabricating evidence.

EXECUTION
---------
Every fill is a TAKER against the live ask (the brief: "No post-only, no
maker-rebate dependence"), so the edge is ``model_p - ask_p - cost`` against
the ASK, never the midpoint, and the requested size never exceeds the visible
ask depth. Level-0 pricing with the size CLIPPED to level-0 depth is the v1
choice: it removes the only way top-of-book pricing can lie (sizing past the
level you priced against) without walking a ladder. ``running_extreme_lock``
does walk the ladder for its open-tail sizing; sharing that helper means
lifting it into ``weather_common``, which is a refactor of a shipped strategy
and is left as a named follow-up rather than a copy-paste here.

No price is ever emitted by this module -- the strategy submits a MARKET
order -- so the venue's 0.01 tick can never be violated by an unrepresentable
limit price such as 0.995.

BOOK SHAPE
----------
A long-only taker needs an ASK and nothing else. An asks-only book (the bid
side padded away by ``OrderBookDepth10``, rendered ``bid=None`` by
``breezy.strategy.depth10.market_quote_from_depth``) is TRADED, following
``running_extreme_lock`` and ``RiskManager.quote_tradable``'s explicit
one-sided-book branch. A book with no ASK is not tradable at all and returns
``None``.

RECORD-SHAPE GATES
------------------
``correction_flag`` is refused under ``require_correction_flag_clear``
(default ``True``); ``is_superseded`` is refused unconditionally -- a record
that has been replaced is not evidence about anything, regardless of config.
A record whose own ``published_at`` is in the future relative to the decision
clock has not happened yet and is refused as look-ahead.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from breezy.domain.weather_bucket_facts import Measure
from breezy.strategy.weather_common.models import SideIntent, SignalDecision, ensure_aware

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.domain.weather_bucket_facts import WeatherBucketFacts
    from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = ["CliPrintObservation", "evaluate_instrument"]

#: Degrees of clearance from the nearest FINITE bucket boundary at which
#: conviction reaches 1.0. Two degrees, because the printed value must move
#: strictly PAST a boundary to leave the bucket: at margin 0 a single 1F
#: correction loses the bucket, at margin 1 it takes two, and beyond that the
#: distinction stops carrying information at the resolution NWS publishes
#: (whole degrees F). Conviction only, never probability -- see the module
#: docstring.
CONVICTION_FULL_MARGIN_F: Final[int] = 2


@dataclass(frozen=True, slots=True)
class CliPrintObservation:
    """The station/climate-day CLI print, translated out of the raw
    ``breezy.domain.nws_climate_day.NwsClimateDay`` wire record.

    A translated snapshot, not the wire type itself -- the same shape choice
    ``RunningExtremeObservation`` and ``ForecastSnapshot`` make -- so this
    module's tests never need to construct a full 20-field ``NwsClimateDay``.
    ``published_at`` is the record's ISSUANCE instant (never a
    retrieval/ingest timestamp), matching ``SignalFreshness.age_hours``'s own
    contract.
    """

    station: str
    climate_day: dt.date
    #: The printed daily maximum. ``None`` when the product carries a sentinel.
    tmax_f: int | None
    #: The printed daily minimum. ``None`` when the product carries a sentinel.
    tmin_f: int | None
    #: ``True`` only for the settlement-grade final issuance. This strategy
    #: trades nothing else -- see the module docstring.
    is_final: bool
    correction_flag: bool
    is_superseded: bool
    published_at: dt.datetime


def _printed_value(observation: CliPrintObservation, measure: Measure) -> int | None:
    """The settlement datum for ``measure``, read from the field that measure names.

    Never config-selected: a HIGH bucket settles on the published MAXIMUM and
    a LOW bucket on the published MINIMUM. See ``config.py`` for why
    ``use_tmax``/``use_tmin`` are participation flags rather than selectors.
    """
    if measure is Measure.HIGH:
        return observation.tmax_f
    return observation.tmin_f


def _measure_enabled(measure: Measure, cfg: CliSettlementPrintLockConfig) -> bool:
    return cfg.use_tmax if measure is Measure.HIGH else cfg.use_tmin


def _boundary_margin_f(facts: WeatherBucketFacts, printed_f: int) -> int:
    """Degrees from ``printed_f`` to the NEAREST FINITE bound of its bucket.

    Only reached once ``facts.contains(printed_f)`` holds, so both distances
    are non-negative. An open side contributes no boundary at all (nothing
    can revise "out of" a bound that does not exist), and at least one bound
    is always finite -- ``read_weather_bucket_facts`` refuses a bucket with
    neither.
    """
    distances = [
        printed_f - facts.lower_f if facts.lower_f is not None else None,
        facts.upper_f - printed_f if facts.upper_f is not None else None,
    ]
    finite = [d for d in distances if d is not None]
    return min(finite) if finite else 0


def evaluate_instrument(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    observation: CliPrintObservation,
    now: dt.datetime,
    p_stable: float,
    cfg: CliSettlementPrintLockConfig,
) -> SignalDecision | None:
    """Return the desired position change, or ``None`` for "do nothing".

    Never returns a ``SHORT_YES`` intent under any input -- there is no branch
    in this function that constructs one.
    """
    facts = contract.facts
    if not facts.applies_to(observation.station, observation.climate_day):
        return None
    if ensure_aware(observation.published_at) > ensure_aware(now):
        # Look-ahead guard: a record whose own timestamp is still in the
        # future relative to the decision clock has not "happened" yet.
        return None
    if not observation.is_final:
        # LOAD-BEARING, not decorative -- see the module docstring. A
        # preliminary is the product G-01 measures as unstable.
        return None
    if observation.is_superseded:
        return None
    if observation.correction_flag and cfg.require_correction_flag_clear:
        return None

    if not _measure_enabled(facts.measure, cfg):
        return None
    printed_f = _printed_value(observation, facts.measure)
    if printed_f is None:
        return None
    if not facts.contains(printed_f):
        # Some OTHER rung of the ladder contains this print. Not a short --
        # this strategy is silent on every bucket but the one that won.
        return None

    model_p = p_stable
    if model_p < cfg.min_stable_prob:
        # The published falsification kill line, carried into the running
        # system: below it the edge is dead by the brief's own criterion.
        return None

    scale = (
        cfg.price_scale_override if cfg.price_scale_override is not None else contract.price_scale
    )
    ask_p = quote.implied_ask(scale)
    if ask_p is None:
        # No executable side for a long-only taker.
        return None
    # Degenerate-ask guard, independent of `RiskManager.quote_tradable`
    # downstream (this module is independently reusable, so its own guard
    # must hold on its own). `ask_p <= 0` would flow through the edge formula
    # as an apparent ~0.98 "free" edge that is really a missing price;
    # `ask_p >= 1.0` is paying at or above the maximum possible payout on a
    # 0/1 binary, which can never be a profitable LONG_YES.
    if ask_p <= 0.0 or ask_p >= 1.0:
        return None

    # Edge against the ASK actually paid, never the midpoint -- every fill is
    # a taker (module docstring, and the brief's non-negotiable look-ahead /
    # execution rules).
    edge = model_p - ask_p - cfg.transaction_cost_prob
    if edge < cfg.min_edge_after_costs:
        return None

    # Sizing: the largest WHOLE contract count this signal asks for, bounded
    # by the visible ask depth so the price above is the price the whole
    # order actually pays. Payout-dollar caps (`max_event_notional`,
    # `max_location_notional`, `max_position_contracts`,
    # `max_equity_fraction`, `max_simultaneous_positions`) and the two
    # operator-reserved dollar controls are applied downstream by
    # `RiskManager.evaluate_order`, which clips -- this module never reasons
    # in current market value.
    visible_depth = quote.ask_size or 0.0
    quantity = math.floor(
        min(cfg.max_quantity, cfg.base_quantity + cfg.edge_qty_scale * edge, visible_depth),
    )
    if quantity < 1:
        return None

    margin_f = _boundary_margin_f(facts, printed_f)
    return SignalDecision(
        instrument_id=contract.instrument_id,
        intent=SideIntent.LONG_YES,
        model_probability=model_p,
        market_probability=ask_p,
        edge=edge,
        conviction=min(1.0, margin_f / float(CONVICTION_FULL_MARGIN_F)),
        quantity=float(quantity),
        reason="cli_final_print_locks_bucket",
        metadata={
            "printed_f": printed_f,
            "measure": facts.measure.value,
            "bucket_lower_f": facts.lower_f,
            "bucket_upper_f": facts.upper_f,
            "boundary_margin_f": margin_f,
        },
    )
