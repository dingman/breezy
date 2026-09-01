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
never smuggled into the probability, and never consumed by sizing.

``conviction`` IS STRUCTURALLY 0.0 ON EVERY INTERIOR BUCKET. SAY SO.
--------------------------------------------------------------------
The venue's ladder interiors are TWO-DEGREE CLOSED intervals: slug
``gte56lt57f`` decodes to ``[56, 57]``, because
``adapters.polymarket_us.symbology.assert_bounds_cross_checked`` reads ``lt``
as ``<= N`` *inside a range* (standalone it is ``<= N-1``). Every printed
value inside such a bucket is therefore ON one of its two bounds, so
``_boundary_margin_f`` -- ``min(printed - lower, upper - printed)`` -- is
identically **0** for every interior print, and ``CONVICTION_FULL_MARGIN_F``
is reachable ONLY in the open tails, where one bound is absent. There is no
"middle" for an interior print to sit in. The field is retained (it is a
required :class:`SignalDecision` field, and it is genuinely informative in the
tails) but it is a CONSTANT ZERO on the buckets this strategy exists to buy,
and nothing downstream may read it as a corroborating variable.

Sizing deliberately does NOT consume it. Sizing UP on boundary margin would
fabricate evidence: no measured margin-keyed table exists for the FINAL print
(BL-19 s8.1(1)), and the omission is currently CONSERVATIVE -- conditioning on
margin could only RAISE ``model_p``. Sizing DOWN at margin 0 is defensible but
would be a second undermined knob for a hazard constant-cost-basis sizing
already bounds, so it is a named follow-up, not this change.

WHICH STATIONS THIS IS MEASURED ON (:data:`MEASURED_STATIONS`)
---------------------------------------------------------------
``p_stable`` was measured on FIVE stations and no others. The whole argument
for shipping the PER-STATION bound rather than the pooled one is that those
five WFOs are **not exchangeable** -- measured preliminary->final revision
rates span 4.50% to 13.96%. That argument refutes extrapolation to an
UNMEASURED sixth office far more strongly than it refutes pooling across the
five, so a contract whose ``settlement_station`` is outside the measured set
is REFUSED here, hard-coded exactly as the ``is_final`` gate is. A new city
listing is a routine venue event, not a code change; fail closed.

COST, AND WHY THERE IS NO TOTAL-COST SCALAR
--------------------------------------------
The edge is netted against ``fee(ask) + slippage_prob``, computed by
``weather_common.costs``, never against a single configurable constant. The
venue fee is ``theta * p * (1 - p)`` with ``theta`` a VENUE FACT riding on
``contract.fee_coefficient``, resolved once per instrument at ``on_start``;
``slippage_prob`` is the only writable term and is floored at one tick. A
``None`` coefficient is a NO-TRADE, never a free trade. See
``docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`` s2.

SIZING: CONSTANT DOLLAR COST BASIS, NEVER AFFINE IN EDGE
---------------------------------------------------------
The replaced rule was ``base_quantity + edge_qty_scale * edge``, which is
strictly increasing in edge and therefore strictly increasing in how much the
book DISAGREES with us -- committing $26.49 at ask 0.98 and ~$101 at ask 0.66,
3.8x more money on the least-corroborated signal. For a long-only binary the
loss when wrong is the premium paid, so the exposure question is cost basis,
not contract count. The rule here holds that basis flat across the whole
admitted band: a systematic mapping or resolution-timing fault can no longer
escalate its own capital consumption by producing a larger apparent edge.
Nothing the edge gate admits is refused by this -- only the size changes.

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
``correction_flag`` and ``is_superseded`` are BOTH refused unconditionally,
with no config field for either. A corrected record sits outside the
``p_stable`` denominator entirely -- the measurement is first-final -> last
pre-settlement, so a correction IS the failure event being counted -- and a
superseded record has been replaced and is not evidence about anything. A
record whose own ``published_at`` is in the future relative to the decision
clock has not happened yet and is refused as look-ahead.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from breezy.domain.weather_bucket_facts import Measure
from breezy.strategy.weather_common.costs import (
    NoExecutableDepthError,
    depth_aware_trade_cost_prob,
    trade_cost_prob,
    venue_fee_prob,
)
from breezy.strategy.weather_common.ladder import ask_levels, levels_within_price
from breezy.strategy.weather_common.models import SideIntent, SignalDecision, ensure_aware

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.domain.weather_bucket_facts import WeatherBucketFacts
    from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = [
    "MEASURED_STATIONS",
    "CliPrintObservation",
    "cost_basis_anchor",
    "evaluate_instrument",
    "worst_admissible_ask",
]

#: The stations ``p_stable`` was actually measured on, in the vocabulary
#: ``WeatherBucketFacts.settlement_station`` carries -- the registry's
#: ``cli_location`` (``src/breezy/registry/sites.toml``), which
#: ``adapters.polymarket_us.parsing._weather_info`` writes into
#: ``SETTLEMENT_STATION_KEY``. NOT the ICAO form the evidence documents quote
#: (KNYC/KMIA/KMDW/KLAX/KSFO), which never reaches a contract.
#:
#: HARD-CODED, exactly as the ``is_final`` gate is, and for the same reason: a
#: flag that could turn it off would be a switch whose only alternative
#: setting trades an UNMEASURED station on a bound measured somewhere else.
#: See the module docstring's "WHICH STATIONS" section.
MEASURED_STATIONS: Final[frozenset[str]] = frozenset({"NYC", "MIA", "MDW", "LAX", "SFO"})

#: Degrees of clearance from the nearest FINITE bucket boundary at which
#: conviction reaches 1.0. Two degrees, because the printed value must move
#: strictly PAST a boundary to leave the bucket: at margin 0 a single 1F
#: correction loses the bucket, at margin 1 it takes two, and beyond that the
#: distinction stops carrying information at the resolution NWS publishes
#: (whole degrees F). Conviction only, never probability, and never sizing.
#:
#: REACHABLE ONLY IN THE OPEN TAILS. The venue's ladder interiors are
#: two-degree CLOSED intervals (``gte56lt57f`` -> ``[56, 57]``), so every
#: interior print sits ON a bound and its margin is 0. This threshold
#: therefore describes a case that exists only where one bound is absent --
#: see the module docstring's conviction section.
CONVICTION_FULL_MARGIN_F: Final[int] = 2

#: Guards the tick-grid floor against binary representation error: 0.98 / 0.01
#: is 97.99999999999999 in IEEE-754, which would floor to 0.97 and quietly
#: refuse the strategy's best entry.
_TICK_EPSILON: Final[float] = 1e-9


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

    IDENTICALLY 0 FOR EVERY INTERIOR PRINT on the venue's real ladder, whose
    interiors are two-degree closed intervals: with ``upper == lower + 1``,
    ``min(printed - lower, upper - printed)`` takes the minimum of a pair that
    always contains a zero. The function is not wrong and is not dead -- it is
    genuinely informative in the OPEN TAILS -- but any reader treating its
    output as a per-bucket quality signal on an interior is reading a
    constant. See the module docstring.
    """
    distances = [
        printed_f - facts.lower_f if facts.lower_f is not None else None,
        facts.upper_f - printed_f if facts.upper_f is not None else None,
    ]
    finite = [d for d in distances if d is not None]
    return min(finite) if finite else 0


def worst_admissible_ask(
    *,
    model_p: float,
    fee_coefficient: float,
    slippage_prob: float,
    min_edge_after_costs: float,
    tick_size: float | None,
) -> float:
    """The HIGHEST ask the edge gate admits, solved exactly, then put on the grid.

    Solves ``model_p - a - theta*a*(1 - a) - slippage_prob = min_edge_after_costs``
    for ``a``, i.e. the quadratic ``theta*a^2 - (1 + theta)*a + K = 0`` with
    ``K = model_p - slippage_prob - min_edge_after_costs``, taking the smaller
    root (the one in ``[0, 1]``). At the shipped constants -- ``model_p``
    0.996896, ``theta`` 0.06, slippage 0.01, floor 0.005 -- that is
    ``0.06 a^2 - 1.06 a + 0.981896 = 0`` -> **a = 0.98076408**, and 0.98 once
    floored to a 0.01 tick.

    ``tick_size=None`` returns the exact root, which is what the arithmetic
    pin in the tests asserts. Every caller in the running system passes the
    instrument's OWN increment: a finer tick moves the answer off 0.98 and the
    anchor with it, which is the design self-correcting rather than a table
    going stale.

    The discriminant is never negative: ``(1 + theta)^2 - 4*theta*K`` with
    ``K <= 1`` is at least ``(1 - theta)^2``.
    """
    remainder = model_p - slippage_prob - min_edge_after_costs
    if fee_coefficient <= 0.0:
        # Degenerate (and REAL -- a venue may publish theta = 0): the equation
        # is linear, and the quadratic formula would divide by zero.
        root = remainder
    else:
        b = 1.0 + fee_coefficient
        root = (b - math.sqrt(b * b - 4.0 * fee_coefficient * remainder)) / (
            2.0 * fee_coefficient
        )
    root = min(max(root, 0.0), 1.0)
    if tick_size is None or tick_size <= 0.0:
        return root
    return math.floor(root / tick_size + _TICK_EPSILON) * tick_size


def cost_basis_anchor(
    *,
    base_quantity: float,
    worst_ask: float,
    fee_coefficient: float,
) -> float:
    """``A = base_quantity * (a_max + fee(a_max))`` -- dollars, per decision.

    NOT a new risk budget and deliberately NOT a config field: it is the cost
    basis the shipped ``base_quantity`` ALREADY commits at the strategy's
    tightest admissible entry, read back off values the config already holds.
    Exposing it would create a dollar-denominated per-decision knob one rename
    away from "maximum notional per position", which is operator-reserved. It
    stays derived, in code, at the one call site
    (``docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md`` s1.7).

    At the shipped constants: ``25 * (0.98 + 0.001176)`` = **$24.5294**.
    """
    return base_quantity * (
        worst_ask + venue_fee_prob(executable_price=worst_ask, fee_coefficient=fee_coefficient)
    )


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
    if observation.correction_flag:
        # UNCONDITIONAL, and hard-coded exactly as `is_final` is. A CCA/CCB
        # correction is not "the same edge with a caveat": `p_stable` is
        # measured first-final -> last-pre-settlement, so a correction IS the
        # failure event the denominator counts. See `config.py` for the
        # identical no-knob argument applied to `require_final_print`.
        return None
    if facts.settlement_station not in MEASURED_STATIONS:
        # `p_stable` was measured on five stations whose own revision rates
        # span 4.50%-13.96%, i.e. demonstrably NOT exchangeable. A sixth
        # office has no bound at all. Fail closed -- module docstring.
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

    fee_coefficient = contract.fee_coefficient
    if fee_coefficient is None:
        # An unresolved fee schedule is a NO-TRADE, never a free trade
        # (`adapters.polymarket_us.fees`: "a market whose coefficient we could
        # not parse raises rather than trading free"). Unreachable through
        # `strategy.py`, which raises `UnpricedInstrumentError` at `on_start`
        # -- this is the independent-reuse guard, same posture as the
        # degenerate-ask guard above.
        return None

    # PRE-SCREEN at the BEST possible price -- level 0. Cheap, and it can only
    # over-admit: the depth-aware repricing below is monotone worse, so
    # anything this refuses the true price would refuse too.
    level0_fee_prob = venue_fee_prob(executable_price=ask_p, fee_coefficient=fee_coefficient)
    level0_cost = trade_cost_prob(
        executable_price=ask_p,
        fee_coefficient=fee_coefficient,
        slippage_prob=cfg.slippage_prob,
    )
    if model_p - ask_p - level0_cost < cfg.min_edge_after_costs:
        return None

    # Sizing: CONSTANT DOLLAR COST BASIS. The largest WHOLE contract count
    # whose PREMIUM (`ask + fee(ask)` -- the entire downside of a long-only
    # binary) stays within the anchor `A`, bounded by `max_quantity` and by
    # the depth the book actually offers. Never affine in `edge`: see the
    # module docstring.
    #
    # Payout-dollar caps (`max_event_notional`, `max_location_notional`,
    # `max_position_contracts`, `max_equity_fraction`,
    # `max_simultaneous_positions`) and the two operator-reserved dollar
    # controls are applied downstream by `RiskManager.evaluate_order`, which
    # clips -- this module never reasons in current market value.
    anchor = cost_basis_anchor(
        base_quantity=cfg.base_quantity,
        worst_ask=worst_admissible_ask(
            model_p=model_p,
            fee_coefficient=fee_coefficient,
            slippage_prob=cfg.slippage_prob,
            min_edge_after_costs=cfg.min_edge_after_costs,
            tick_size=contract.tick_size,
        ),
        fee_coefficient=fee_coefficient,
    )
    # THE RUNGS THIS STRATEGY CAN ACTUALLY LIFT. The execution seam submits a
    # MARKETABLE IOC LIMIT at `ask + slippage_prob` (`strategy.py`'s
    # `_marketable_limit_price`, and the "EXECUTION SEAM" section of that
    # module's docstring): no fill can occur above that price. Rungs above it
    # are not liquidity available to this strategy, so sizing or pricing
    # against them would model a fill it structurally cannot get. The bound is
    # computed WITHOUT the execution layer's round-UP-to-a-tick, so it is
    # never looser than the limit actually emitted.
    #
    # At the shipped configuration (`slippage_prob` = 0.01 = one tick) this
    # admits at most one rung past the top of book, and any such rung concedes
    # at most one tick -- so the effective slippage equals the floor and the
    # arithmetic below reduces to what it was before. That equality is the
    # POINT: it is now structural rather than a coincidence between two
    # modules. Raise `slippage_prob` and the strategy becomes willing to lift
    # deeper rungs, and the edge is repriced at their true VWAP instead of
    # still being computed off the level-0 tick (BL-25 D1).
    reachable = levels_within_price(
        ask_levels(quote),
        (quote.ask or 0.0) + cfg.slippage_prob / scale,
    )
    reachable_depth = sum(size for price, size in reachable if size > 0.0 and price > 0.0)
    candidate = math.floor(
        min(cfg.max_quantity, anchor / (ask_p + level0_fee_prob), reachable_depth),
    )
    if candidate < 1:
        return None

    # --- DEPTH-AWARE REPRICING (BL-25 D1) ---------------------------------
    # Size and price are mutually dependent: a bigger size walks deeper into
    # the ask ladder, worsening the VWAP, which shrinks the edge. Resolved as
    # SIZE-FIRST-THEN-REPRICE, exactly as `running_extreme_lock.decision`
    # resolves it and for the same reason -- an iterative largest-size search
    # would converge (edge is monotonically non-increasing in size) but is
    # unwarranted for a v1 rule whose inputs are themselves coarse.
    #
    # `candidate` was sized at the level-0 premium, which is the SMALLEST
    # possible premium and therefore the LARGEST size the anchor could ever
    # buy. Repricing it at the true VWAP can only make the premium bigger, and
    # the anchor is re-applied at that true premium downstream by
    # `strategy._clip_to_cost_basis_anchor`, which reads
    # `decision.market_probability + metadata["fee_prob"]` -- both of which are
    # the VWAP-based figures set below. So the dollar budget is enforced at the
    # honest price, not at the level-0 estimate, without a second walk here.
    #
    # With no `ask_ladder` on the quote this reduces EXACTLY to the previous
    # level-0 arithmetic (`weather_common.ladder.ask_levels` synthesises a
    # one-level ladder from top-of-book), so a ladderless quote is unaffected.
    try:
        cost_detail = depth_aware_trade_cost_prob(
            ask_levels=reachable,
            quantity=float(candidate),
            price_scale=scale,
            fee_coefficient=fee_coefficient,
            slippage_floor_prob=cfg.slippage_prob,
        )
    except NoExecutableDepthError:
        # No real depth is a no-trade, never a level-0-priced trade.
        return None
    vwap_ask_p = cost_detail.executable_price
    if vwap_ask_p <= 0.0 or vwap_ask_p >= 1.0:
        # Defensive: a degenerate deeper level (bad venue data) must not
        # produce a degenerate VWAP once the top-of-book guard has passed.
        return None
    fee_prob = cost_detail.fee_prob
    cost = cost_detail.total_prob
    quantity = math.floor(cost_detail.fillable_quantity)
    if quantity < 1:
        return None

    # Edge vs the VWAP-priced ask actually consumed, never the level-0 tick.
    edge = model_p - vwap_ask_p - cost
    if edge < cfg.min_edge_after_costs:
        return None

    # STRUCTURALLY 0 on every interior bucket -- the venue's ladder interiors
    # are two-degree CLOSED intervals, so every interior print sits ON a bound.
    # Non-zero only in the open tails. Reported, never consumed by sizing; see
    # the module docstring's conviction section for why sizing up on it would
    # fabricate evidence.
    margin_f = _boundary_margin_f(facts, printed_f)
    return SignalDecision(
        instrument_id=contract.instrument_id,
        intent=SideIntent.LONG_YES,
        model_probability=model_p,
        market_probability=vwap_ask_p,
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
            # LOAD-BEARING, not decoration. With `market_probability` (the
            # ask) and `model_probability` already on the record, these three
            # make BL-19 s8.5's "computed edge at slippage_prob in {0.000,
            # 0.010}" reconstructible OFFLINE from any recorded decision --
            # so a measured slippage figure re-derives the threshold without
            # re-running the capture. That is the whole point of keeping the
            # two cost terms separate and named.
            "fee_coefficient": fee_coefficient,
            "fee_prob": fee_prob,
            # The EFFECTIVE execution term actually charged --
            # `max(cfg.slippage_prob, VWAP - level-0 ask)`. The configured
            # floor is carried beside it as `slippage_floor_prob` so s8.5's
            # "computed edge at slippage_prob in {0.000, 0.010}" stays
            # re-derivable offline and the two are never confused.
            "slippage_prob": cost_detail.slippage_prob,
            "slippage_floor_prob": cfg.slippage_prob,
            "level0_ask_prob": ask_p,
            "vwap_ask_prob": vwap_ask_p,
            # RAW venue units, unlike every price above. The execution layer
            # prices its marketable IOC limit off this and only this: a limit
            # at the VWAP would stop halfway up the ladder the edge was
            # computed over, turning a priced order into a partial fill at an
            # unmodelled average.
            "worst_ask_raw": cost_detail.worst_price / scale,
            "depth_exhausted": int(cost_detail.depth_exhausted),
            # `A`, carried on the decision because it is the number the
            # EXECUTION layer needs to hold the POSITION -- not merely this
            # decision -- inside the design budget. `quantity` above is a
            # TARGET LEVEL, and a target level alone cannot bound a position
            # that is topped up on every depth tick as the ask falls (see
            # `strategy._maybe_submit`). Re-deriving it there would duplicate
            # this module's arithmetic at a second site.
            "cost_basis_anchor": anchor,
        },
    )
