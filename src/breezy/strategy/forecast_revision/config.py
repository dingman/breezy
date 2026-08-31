"""Configuration for
:class:`~breezy.strategy.forecast_revision.strategy.ForecastRevisionStrategy`.

Every signal knob is carried over from the bundle's ``ForecastRevisionConfig``
/ ``WeatherStrategyConfig`` sections. The same four fields the first bundle's
integration dropped are dropped here for the same reasons -- ``nws_client_id``
(the weather client id is a shared constant, and a mismatch is a silently
dropped subscription rather than a customisation), ``diagnostic_log`` (logging
is unconditional), ``flatten_on_stop`` (that is the native
``StrategyConfig.manage_stop``), and ``strategy_id`` (the bundle defaulted it
to a ``str``; the native field is a ``StrategyId``).
"""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

__all__ = ["ForecastRevisionConfig"]


class ForecastRevisionConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`ForecastRevisionStrategy`.

    Parameters
    ----------
    instrument_ids : tuple[InstrumentId, ...]
        Every weather-bucket market this strategy instance may trade. Each must
        be present in the cache at ``on_start`` and carry KNOWN weather bucket
        facts (``breezy.domain.weather_bucket_facts``).
    min_temp_revision_f, min_prob_revision : float
        Magnitude floors on the revision, in degrees F and in model
        probability. A revision must clear at least one of them.
    min_revision_over_sigma : float
        A third floor, on ``|dT| / sigma_previous`` -- the revision measured in
        units of the model's own forecast uncertainty, so a 2F move at a
        24-hour horizon is not treated like a 2F move at a 6-hour one.
    min_unabsorbed_prob : float
        The tradable quantity: model probability revision MINUS the market's own
        move since the revision was published. Below this there is nothing left
        to take.
    min_caught_up_fraction : float
        Fraction of the model revision the book must have absorbed (in the same
        direction) before an entry is abandoned and an open position exits.
    persistence_updates, persistence_same_sign : int, bool
        When enabled, require the last ``persistence_updates`` revisions to
        share a sign, so a single oscillating update is not chased.
    reaction_window_minutes : float
        How long after a publication an entry may still be opened. Past it, the
        only action available is the catch-up exit.
    cooldown_minutes : float
        Minimum spacing between trades on one instrument.
    base_quantity, max_quantity, revision_qty_scale : float
        Position sizing: ``base_quantity + revision_qty_scale * |unabsorbed|``,
        clipped to ``max_quantity``.
    exit_when_market_catches_up : bool
        Whether to flatten once the book has absorbed the revision.
    history_len : int
        How many publications to retain per station/climate-day.
    max_position_contracts, max_event_notional, max_location_notional,
    max_simultaneous_positions, max_equity_fraction, min_model_edge,
    max_bid_ask_spread, min_liquidity_contracts, min_hours_to_settlement,
    halt_hours_before_settlement, stale_forecast_hours, stale_quote_minutes,
    transaction_cost_prob, allow_short : see
        ``breezy.strategy.weather_common.risk.RiskLimits``.
    starting_equity : float
        Fallback equity for the equity-fraction risk check when the native
        account balance is unavailable.
    error_distribution, student_t_df, sigma_floor_f, sigma_per_sqrt_hour_f,
    p_floor : see ``breezy.strategy.weather_common.probability.ForecastErrorModel``.
    use_limit_orders, limit_inside_ticks, flatten_on_observation,
    price_scale_override : see ``forecast_mispricing.config``.

    """

    instrument_ids: tuple[InstrumentId, ...]

    # Signal thresholds and sizing.
    min_temp_revision_f: float = 1.5
    min_prob_revision: float = 0.05
    min_revision_over_sigma: float = 0.60
    min_unabsorbed_prob: float = 0.03
    min_caught_up_fraction: float = 0.55
    persistence_updates: int = 2
    persistence_same_sign: bool = True
    reaction_window_minutes: float = 90.0
    cooldown_minutes: float = 45.0
    base_quantity: float = 20.0
    max_quantity: float = 120.0
    revision_qty_scale: float = 500.0
    exit_when_market_catches_up: bool = True
    history_len: int = 12

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
    stale_forecast_hours: float = 8.0
    stale_quote_minutes: float = 15.0
    transaction_cost_prob: float = 0.015
    #: FALSE. See ``breezy.strategy.weather_common.risk.RiskLimits.allow_short``:
    #: this is the only naked-short control in the system (Nautilus denies no
    #: naked short of its own), and ``True`` is reachable only by writing it at
    #: a call site -- an explicit operator act, never a default.
    allow_short: bool = False
    starting_equity: float = 10_000.0

    # Probability model (breezy.strategy.weather_common.probability.ForecastErrorModel).
    error_distribution: str = "gaussian"
    student_t_df: float = 7.0
    sigma_floor_f: float = 1.1
    sigma_per_sqrt_hour_f: float = 0.55
    p_floor: float = 0.01

    # Execution.
    use_limit_orders: bool = True
    limit_inside_ticks: int = 0
    flatten_on_observation: bool = False
    price_scale_override: float | None = None
