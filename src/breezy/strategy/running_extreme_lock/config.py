"""Configuration for
:class:`~breezy.strategy.running_extreme_lock.strategy.RunningExtremeLockStrategy`.

Field set follows the shape of
:class:`breezy.strategy.forecast_mispricing.config.ForecastMispricingConfig`
(the sizing knobs and the ``breezy.strategy.weather_common.risk.RiskLimits``
pass-through), with the changes this strategy's design brief and its binding
peer review require:

* No ``stale_forecast_hours`` -- this strategy has no forecast (Breezy ingests
  none). ``stale_observation_hours`` replaces it, and unlike every other
  numeric limit here it has **no default**: it is a required field, so every
  construction site must supply an explicit value. This is not an oversight --
  see ``strategy.py``'s module docstring and
  :class:`~breezy.strategy.running_extreme_lock.strategy.MissingObservationBoundError`
  for why a silently-defaulted bound is the exact failure mode this strategy
  must not ship. The empirically-derived candidate is 12.665h -- max-over-sites
  P99 issuance gap (MIA, 12.3167h) plus live steady-state receipt P99
  (0.3488h) -- see ``docs/evidence/observation_lock_falsification_2026-08-31.md``
  section 4. It is documented here, not defaulted here: the threshold is an
  explicit operator act, the same posture ``allow_short`` already takes.
* No ``min_p_hold`` / ``min_p_stay`` / ``min_hours_remaining_interior``. The
  design brief's flat ``min_p_hold = 0.96`` gates a margin-conditional hazard
  while firing at margin ~= 0 -- the worst-conditioned cell (peer-review
  finding C5). Instead ``model_probability`` is looked up from a measured,
  margin-conditioned Wilson-95%-lower-bound table (see ``decision.py`` and
  ``strategy.py``), and the tradable edge floor is the same
  ``min_model_edge`` every other weather strategy already uses. ``min_p_stay``
  and ``min_hours_remaining_interior`` govern the interior-bucket path, which
  v1 does not implement (see ``open_tail_only`` below).
* No ``require_same_climate_day`` / ``require_not_final_ok``. Both were
  decorative in the brief: ``WeatherBucketFacts.applies_to`` already enforces
  same-station/same-climate-day unconditionally (there is no correct "off"
  state), and this strategy never gates on ``is_final`` at all -- a
  preliminary and a final are equally tradable once the tail is cleared and
  neither ``correction_flag`` nor ``is_superseded`` is set (C6). A config flag
  that cannot change behaviour is dead surface, not a knob.
* No ``use_limit_orders`` / ``limit_inside_ticks``. The design brief is
  explicit: "Taker against live ask only. No post-only. No maker rebate."  A
  market order against the ask already IS a taker fill; there is no
  maker-side mode to select.
"""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

__all__ = ["RunningExtremeLockConfig"]


class RunningExtremeLockConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`RunningExtremeLockStrategy`.

    Parameters
    ----------
    instrument_ids : tuple[InstrumentId, ...]
        Every weather-bucket market this strategy instance may trade. Each
        must be present in the cache at ``on_start`` and carry KNOWN weather
        bucket facts (``breezy.domain.weather_bucket_facts``). Only
        HIGH-measure, open-ended-upper-tail instruments (``upper_f is None``)
        are actually traded; any other configured instrument is logged and
        skipped -- see ``strategy.py``.
    stale_observation_hours : float | None
        REQUIRED, no default. See the module docstring.
    open_tail_only : bool
        Must be ``True`` in v1 -- constructing with ``False`` raises
        ``NotImplementedError``. The pre-registered symmetric-revision study
        (``docs/evidence/observation_lock_falsification_2026-08-31.md``
        section 3) FAILS the interior-bucket path on 3/5 sites (MDW 13.96%,
        NYC 11.79%, SFO 4.50%); the open tail survives on the same data
        (pooled downward rate 0.21%). Kept as an explicit field, not silently
        removed, so the brief's plug-in contract stays legible and a future
        increment that adds the interior path has a named switch to flip.
    base_quantity, max_quantity, edge_qty_scale : float
        Position sizing: ``base_quantity + edge_qty_scale * edge``, clipped to
        ``max_quantity``. Contract counts, not dollars -- sizing is clipped by
        the existing payout-dollar caps below, and the two operator-reserved
        dollar controls (max daily trading budget; max notional per position)
        stay unset here, exactly as in every other weather strategy.
    max_position_contracts, max_event_notional, max_location_notional,
    max_simultaneous_positions, max_equity_fraction, min_model_edge,
    max_bid_ask_spread, min_liquidity_contracts, min_hours_to_settlement,
    halt_hours_before_settlement, stale_quote_minutes, transaction_cost_prob,
    allow_short : see ``breezy.strategy.weather_common.risk.RiskLimits``.
    starting_equity : float
        Fallback equity used for the equity-fraction risk check when the
        native account balance is unavailable.
    price_scale_override : float | None
        Overrides ``contract.price_scale`` (1.0 for [0, 1]-priced markets)
        when the venue prices in a different unit.

    """

    instrument_ids: tuple[InstrumentId, ...]
    #: REQUIRED -- no default. See the module docstring.
    stale_observation_hours: float | None

    #: v1 ships the open upper tail only. See the field docstring above.
    open_tail_only: bool = True

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
    min_model_edge: float = 0.04
    max_bid_ask_spread: float = 0.06
    min_liquidity_contracts: float = 25.0
    min_hours_to_settlement: float = 2.0
    halt_hours_before_settlement: float = 1.0
    stale_quote_minutes: float = 15.0
    transaction_cost_prob: float = 0.015
    #: FALSE, and it must stay False. LONG_YES only -- this strategy never
    #: constructs a SHORT_YES intent (see ``decision.py``), and this is the
    #: only naked-short control in the system regardless
    #: (``breezy.strategy.weather_common.risk.RiskLimits.allow_short``).
    allow_short: bool = False
    starting_equity: float = 10_000.0

    price_scale_override: float | None = None
