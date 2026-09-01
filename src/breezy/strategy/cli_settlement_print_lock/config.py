"""Configuration for
:class:`~breezy.strategy.cli_settlement_print_lock.strategy.CliSettlementPrintLockStrategy`.

Field set follows the design brief's plug-in contract
(``docs/strategies/breezy_strategy_cli_settlement_print_lock.md``, "Plug-in
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
* No ``max_daily_trading_budget`` / ``max_notional_per_position``. Those two
  are operator-reserved and stay UNSET here, exactly as in every other
  weather strategy. Sizing is bounded by the payout-dollar caps below.
"""

from __future__ import annotations

from typing import Final

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

from breezy.strategy.weather_common.risk import RiskLimits

__all__ = ["CliSettlementPrintLockConfig"]

#: The INHERITED risk defaults, read once so the two BL-19 fields below can
#: default to them by reference instead of by copied literal. See those
#: fields for why that matters.
_RISK_DEFAULTS: Final[RiskLimits] = RiskLimits()


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
    require_correction_flag_clear : bool
        Refuse a record whose ``correction_flag`` is set (CCA/CCB or
        correction text in the raw product). ``is_superseded`` is refused
        unconditionally and is NOT governed by this flag.
    use_tmax, use_tmin : bool
        Measure-class enables. See the module docstring.
    base_quantity, max_quantity, edge_qty_scale : float
        Position sizing: ``base_quantity + edge_qty_scale * edge``, clipped to
        ``max_quantity``, to the visible ask depth, and floored to a whole
        contract. Contract counts, not dollars -- the payout-dollar caps
        below and ``RiskManager.evaluate_order`` do the dollar clipping, and
        the two operator-reserved dollar controls stay unset.
    max_position_contracts, max_event_notional, max_location_notional,
    max_simultaneous_positions, max_equity_fraction, min_model_edge,
    max_bid_ask_spread, min_liquidity_contracts, min_hours_to_settlement,
    halt_hours_before_settlement, stale_quote_minutes, transaction_cost_prob,
    allow_short : see ``breezy.strategy.weather_common.risk.RiskLimits``.
    min_edge_after_costs : float
        The DECISION layer's own edge floor (the brief's pass-through
        intent). ``RiskManager`` independently enforces ``min_model_edge``.
    starting_equity : float
        Fallback equity for the equity-fraction risk check when the native
        account balance is unavailable.
    price_scale_override : float | None
        Overrides ``contract.price_scale`` (1.0 for [0, 1]-priced markets)
        when the venue prices in a different unit.

    """

    instrument_ids: tuple[InstrumentId, ...]
    #: REQUIRED -- no default. See the module docstring.
    stale_observation_hours: float | None

    # Print-lock semantics.
    min_stable_prob: float = 0.97
    require_correction_flag_clear: bool = True
    #: Measure-class ENABLES, not field selectors -- see the module docstring.
    use_tmax: bool = True
    use_tmin: bool = False

    # Signal sizing.
    base_quantity: float = 25.0
    max_quantity: float = 150.0
    edge_qty_scale: float = 400.0

    # Risk limits (breezy.strategy.weather_common.risk.RiskLimits).
    max_position_contracts: float = 250.0
    max_event_notional: float = 1_000.0
    max_location_notional: float = 2_000.0
    max_simultaneous_positions: int = 12
    max_equity_fraction: float = 0.08
    # --- BL-19 -----------------------------------------------------------
    # `min_model_edge` (0.04), `min_edge_after_costs` and
    # `transaction_cost_prob` (0.015) are KNOWN to be mis-set for
    # near-certain contracts: a bucket whose measured `p_stable` is 0.9994
    # can only clear a 4c edge floor at an ask <= ~0.944, which is a price a
    # settled-source contract has usually already left. The correct values
    # are a SEPARATE decision in flight (BL-19); this strategy deliberately
    # picks none. All three are plumbed as config that DEFAULTS to the
    # inherited `RiskLimits` value by reference (`_RISK_DEFAULTS`), never as
    # a copied literal, so when BL-19 lands it is a config/limits change at
    # the call site rather than an edit to this strategy.
    min_model_edge: float = _RISK_DEFAULTS.min_model_edge
    min_edge_after_costs: float = _RISK_DEFAULTS.min_model_edge
    transaction_cost_prob: float = _RISK_DEFAULTS.transaction_cost_prob
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
    starting_equity: float = 10_000.0

    price_scale_override: float | None = None
