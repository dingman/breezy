"""Configuration for
:class:`~breezy.strategy.cli_settlement_print_lock.strategy.CliSettlementPrintLockStrategy`.

Field set follows the design brief's plug-in contract
(``docs/strategies/archive/breezy_strategy_cli_settlement_print_lock.md``, "Plug-in
contract (implement exactly)") and the sizing/risk pass-through shape shared
by every other weather strategy
(:class:`breezy.strategy.weather_common.risk.RiskLimits`).

Deviations from the brief's SUGGESTED field list, each deliberate:

* ``stale_observation_hours`` is REQUIRED and has **no default**, exactly as
  in :class:`breezy.strategy.running_extreme_lock.config.RunningExtremeLockConfig`.
  This is the second observation-kind strategy, and ``RiskLimits.
  stale_observation_hours`` defaults ``None``, which REFUSES every
  observation-kind order as ``observation_limit_unset`` -- a counted refusal
  ``RefusalAlerter._conditions`` never alerts on. The bound is an explicit
  act at every construction site; see ``strategy.py``'s module docstring and
  :class:`~breezy.strategy.cli_settlement_print_lock.strategy.MissingObservationBoundError`.
  The derived value for THIS strategy is 9.0h and is **not** the sibling's
  12.665h -- that number was derived for the preliminary->final ISSUANCE gap,
  a different cadence. The derivation lives at the one construction site,
  ``scripts/analysis/run_weather_strategy_backtests.py``.
* ``max_quote_age_minutes`` from the brief is spelled ``stale_quote_minutes``
  here -- the name ``RiskLimits`` already uses for the identical bound, which
  is where this field is forwarded. Same semantics, one vocabulary.
* ``use_tmax`` / ``use_tmin`` are ENABLES for a MEASURE CLASS, never a
  selector for which field to read. The brief's own gloss ("only if the
  instrument is a min bucket") is a statement about the instrument, and the
  instrument already carries that fact as
  ``WeatherBucketFacts.measure``. Letting config choose the field would let a
  HIGH bucket be priced off ``tmin_f`` -- a wrong-settlement-value footgun
  with no legitimate use. ``decision.py`` therefore reads the field the
  bucket's own ``measure`` names, and these flags only decide whether this
  instance participates in that measure class at all. ``use_tmin`` defaults
  ``False`` because the falsification evidence
  (``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 1)
  measured ``p_stable`` on the settlement extreme for the HIGH ladder; no
  separate low-measure figure has been published.
* No ``require_final_print`` flag. Firing only on the FINAL print is the
  entire premise of the strategy, not a knob: the interior-bucket path is
  measured DEAD after a preliminary (G-01 / section 3 of the same document,
  MDW 13.96% / NYC 11.79% / SFO 4.50% revision rates) and sound only after
  the final, where the revision has already happened. A flag that could turn
  that gate off would be a switch whose only setting is "trade the measured-
  dead path". The gate is hard-coded in ``decision.py`` and pinned by
  ``test_a_preliminary_print_is_never_traded``.
* No ``require_correction_flag_clear`` flag either, and for the IDENTICAL
  reason. ``p_stable`` is measured first-final -> last-pre-settlement, so a
  CORRECTION *is* the failure event being counted -- the 1 in 1821 that the
  Wilson bound charges. A corrected record therefore sits OUTSIDE the
  denominator entirely; trading one is not "the same edge with a caveat", it
  is the complement of the measurement. The refusal is hard-coded in
  ``decision.py`` and pinned by
  ``test_the_correction_gate_cannot_be_turned_off_because_there_is_no_knob``.
* No station field, allow-list or override. ``MEASURED_P_STABLE_WILSON_LOWER``
  was measured on KNYC/KMIA/KMDW/KLAX/KSFO only, and the argument for using
  the PER-STATION bound rather than the pooled one is that those five WFOs are
  NOT exchangeable (revision rates 4.50%-13.96%). That argument refutes
  extrapolation to an UNMEASURED sixth office far more strongly than it
  refutes pooling across the five. A new city listing is a routine venue
  event, not a code change, so the allow-list is hard-coded
  (``decision.MEASURED_STATIONS``) and fails closed.
* No total-cost scalar. ``transaction_cost_prob`` is DELETED, because the
  dangerous configuration is a one-line edit of exactly that field: setting
  it to the fee alone (0.0006) with a 0.005 floor admits ask 0.99, which
  ``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s8.2 computes as
  **-0.003698** after one tick of slippage. The fee is a VENUE FACT resolved
  per instrument by injection and is not configurable at all; ``slippage_prob``
  is the only writable cost input, is REQUIRED, and is floored at the
  instrument's own tick in ``strategy.on_start``. See
  ``docs/plans/archive/print_lock_adverse_selection_and_cost_2026-09-01.md`` s2.
* No ``edge_qty_scale``. Sizing no longer depends on edge at all -- see
  ``base_quantity`` below and the same plan's s1. The field is DELETED rather
  than zeroed, because a zeroed knob is a knob that re-enables the defect.
* No ``max_daily_trading_budget`` / ``max_notional_per_position``. Those two
  are operator-reserved and stay UNSET here, exactly as in every other
  weather strategy. Sizing is bounded by the payout-dollar caps below.
"""

from __future__ import annotations

from typing import Final

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

__all__ = ["MIN_EDGE_AFTER_COSTS_BL19", "CliSettlementPrintLockConfig"]

#: BL-19 s8.6's edge floor for this strategy, in probability units.
#:
#: ONE number, referenced twice, because ``min_model_edge`` and
#: ``min_edge_after_costs`` are two spellings of ONE concept and must not
#: drift apart. Derivation
#: (``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s8.2, at
#: ``model_p`` = 0.996896 and ``theta`` = 0.06 with one tick of slippage):
#: ask 0.98 clears at edge **+0.005720**, ask 0.99 fails at **-0.003698**. So
#: 0.005 is the value that admits exactly the two ticks the evidence says are
#: tradable, with a 6.1x cushion over the 0.3104% Wilson-implied failure rate.
#:
#: WHY ONE CONSTANT AND NOT TWO DEFAULTS. ``RiskManager.evaluate_order``
#: re-applies ``abs(edge) < min_model_edge`` (``risk.py:421``) to the number
#: the decision layer has ALREADY cost-netted. Setting one per BL-19 and
#: leaving the other at the inherited 0.04 would make the decision layer emit
#: signals the risk layer refuses 100% of the time as ``edge_below_minimum``
#: -- and ``RefusalAlerter._conditions`` builds only a ``SHORTS_DISABLED``
#: condition, so nothing would alert and the strategy would look like a market
#: with no opportunities. ``CliSettlementPrintLockStrategy.__init__``
#: additionally REFUSES any pair with ``min_model_edge >
#: min_edge_after_costs``, so the invariant survives an override too.
MIN_EDGE_AFTER_COSTS_BL19: Final[float] = 0.005


class CliSettlementPrintLockConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`CliSettlementPrintLockStrategy`.

    Parameters
    ----------
    instrument_ids : tuple[InstrumentId, ...]
        Every weather-bucket market this strategy instance may trade. Each
        must be present in the cache at ``on_start`` and carry KNOWN weather
        bucket facts (``breezy.domain.weather_bucket_facts``). Unlike
        ``running_extreme_lock``, INTERIOR buckets are in scope -- they are
        the usual case here.
    stale_observation_hours : float | None
        REQUIRED, no default. See the module docstring.
    min_stable_prob : float
        Floor on the measured ``p_stable`` this strategy will act on. The
        brief's falsification threshold (``dead if p_stable < 0.97``) carried
        into the running system, so a future table revision that fell below
        the published kill line would stop the strategy instead of quietly
        trading a dead edge.
    slippage_prob : float
        REQUIRED, no default. The execution half of the taker cost, in
        probability units -- queue risk and quote-age drift, NOT the venue
        fee, which is resolved per instrument from the market's own ``theta``.
        UNMEASURED: 0.01 is a placeholder whose measurement obligation is
        named in ``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md``
        s8.5. Validated ``>= instrument.price_increment`` at ``on_start``,
        which is where the per-instrument tick is known.
    use_tmax, use_tmin : bool
        Measure-class enables. See the module docstring.
    base_quantity, max_quantity : float
        Position sizing, CONSTANT-COST-BASIS: the clip is
        ``floor(min(max_quantity, A / (ask + fee(ask)), visible_depth))``
        where ``A = base_quantity * (a_max + fee(a_max))`` and ``a_max`` is the
        worst ask the edge gate admits. ``base_quantity`` is therefore the
        clip at the TIGHTEST admissible entry and ``A`` is the dollars that
        clip already commits -- a DERIVED quantity, never a field, because a
        dollar-denominated per-decision knob is one rename away from an
        operator-reserved control. Size still rises as the contract gets
        cheaper; what no longer rises is the money at risk. See
        ``docs/plans/archive/print_lock_adverse_selection_and_cost_2026-09-01.md`` s1.
        The payout-dollar caps below and ``RiskManager.evaluate_order`` do the
        remaining dollar clipping, and the two operator-reserved dollar
        controls stay unset.
    max_position_contracts, max_event_notional, max_location_notional,
    max_simultaneous_positions, max_equity_fraction, min_model_edge,
    max_bid_ask_spread, min_liquidity_contracts, min_hours_to_settlement,
    halt_hours_before_settlement, stale_quote_minutes,
    allow_short : see ``breezy.strategy.weather_common.risk.RiskLimits``.
    min_edge_after_costs : float
        The DECISION layer's own edge floor. ``RiskManager`` independently
        re-applies ``min_model_edge`` to the same cost-netted number, so the
        two must satisfy ``min_model_edge <= min_edge_after_costs`` -- both
        default to :data:`MIN_EDGE_AFTER_COSTS_BL19` and the strategy refuses
        an inverted pair at construction.
    price_scale_override : float | None
        Overrides ``contract.price_scale`` (1.0 for [0, 1]-priced markets)
        when the venue prices in a different unit.

    """

    instrument_ids: tuple[InstrumentId, ...]
    #: REQUIRED -- no default. See the module docstring.
    stale_observation_hours: float | None
    #: REQUIRED -- no default. The ONLY writable cost input; the venue fee is
    #: NOT configurable. Floored at the instrument's own tick in ``on_start``.
    slippage_prob: float

    # Print-lock semantics.
    min_stable_prob: float = 0.97
    #: Measure-class ENABLES, not field selectors -- see the module docstring.
    use_tmax: bool = True
    use_tmin: bool = False

    # Signal sizing -- CONSTANT COST BASIS, never affine in edge.
    base_quantity: float = 25.0
    max_quantity: float = 150.0

    # Risk limits (breezy.strategy.weather_common.risk.RiskLimits).
    max_position_contracts: float = 250.0
    max_event_notional: float = 1_000.0
    max_location_notional: float = 2_000.0
    max_simultaneous_positions: int = 12
    max_equity_fraction: float = 0.08
    # --- BL-19, LANDED ---------------------------------------------------
    # The inherited `RiskLimits` values (min_model_edge 0.04,
    # transaction_cost_prob 0.015) are mis-set for near-certain contracts:
    # together they demand ask <= 0.9419 on a bucket the model calls 99.69%
    # certain, i.e. ask <= 0.94 on the grid -- a price a settled-source
    # contract has already left. BL-19 s8.6 replaces them. Both floors now
    # reference ONE constant so they cannot drift apart, and the total-cost
    # scalar is GONE rather than retuned (see the module docstring).
    min_model_edge: float = MIN_EDGE_AFTER_COSTS_BL19
    min_edge_after_costs: float = MIN_EDGE_AFTER_COSTS_BL19
    # ---------------------------------------------------------------------
    max_bid_ask_spread: float = 0.06
    min_liquidity_contracts: float = 25.0
    min_hours_to_settlement: float = 2.0
    halt_hours_before_settlement: float = 1.0
    #: The brief's ``max_quote_age_minutes``; named for the ``RiskLimits``
    #: field it is forwarded to.
    stale_quote_minutes: float = 15.0
    #: FALSE, and it must stay False. LONG_YES only -- ``decision.py``
    #: contains no branch that constructs a ``SHORT_YES`` intent, and this is
    #: the only naked-short control in the system regardless
    #: (``breezy.strategy.weather_common.risk.RiskLimits.allow_short``).
    allow_short: bool = False

    price_scale_override: float | None = None
