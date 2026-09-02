"""Configuration for
:class:`~breezy.strategy.forecast_mispricing.strategy.ForecastMispricingStrategy`.

Every knob is carried over from the bundle's ``ForecastMispricingConfig`` /
``WeatherStrategyConfig`` sections, with the settlement-clock fields
(``nws_client_id`` override, ``diagnostic_log`` toggle, and the
``flatten_on_stop`` custom flag) dropped -- see the strategy module docstring
for why: the weather client id is a shared constant rather than a per-strategy
override (a mismatch there is a silently-dropped subscription, not a
legitimate customisation point), logging is unconditional, and stop-time
flattening is the native ``StrategyConfig.manage_stop`` flag Nautilus already
provides rather than a hand-rolled duplicate of it.
"""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

__all__ = ["ForecastMispricingConfig"]


class ForecastMispricingConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`ForecastMispricingStrategy`.

    Parameters
    ----------
    instrument_ids : tuple[InstrumentId, ...]
        Every weather-bucket market this strategy instance may trade. Each
        must be present in the cache at ``on_start`` and carry KNOWN weather
        bucket facts (``breezy.domain.weather_bucket_facts``).
    min_entry_edge, exit_edge : float
        Entry requires ``edge_after_costs >= min_entry_edge``; an existing
        position exits once its edge decays below ``exit_edge``. Two distinct
        thresholds, deliberately -- collapsing them to one would either enter
        on marginal edge or exit good positions on noise.
    base_quantity, max_quantity, edge_qty_scale : float
        Position sizing: ``base_quantity + edge_qty_scale * edge``, damped
        below and clipped to ``max_quantity``.
    uncertainty_dampen : float
        Sizing divisor: size is scaled by ``1 / (1 + sigma / uncertainty_dampen)``.
    horizon_size_floor : float
        Sizing is never scaled down below this fraction purely for horizon
        (see ``forecast.horizon_hours`` in the strategy module docstring for
        what "horizon" means here).
    max_position_contracts, max_event_notional, max_location_notional,
    max_simultaneous_positions, max_equity_fraction, min_model_edge,
    max_bid_ask_spread, min_liquidity_contracts, min_hours_to_settlement,
    halt_hours_before_settlement, stale_forecast_hours, stale_quote_minutes,
    transaction_cost_prob, allow_short : see ``breezy.strategy.weather_common.risk.RiskLimits``.
    error_distribution, student_t_df, sigma_floor_f, sigma_per_sqrt_hour_f,
    p_floor : see ``breezy.strategy.weather_common.probability.ForecastErrorModel``.
    use_limit_orders : bool
        IOC limit orders (stepped ``limit_inside_ticks`` inside the spread)
        when True; market orders when False.
    limit_inside_ticks : int
        How many ``tick_size`` increments to step inside the touch price.
    flatten_on_observation : bool
        Flatten a bucket's position the moment its FINAL climate-day record
        arrives, even before any engine-side settlement.
    price_scale_override : float | None
        Overrides ``contract.price_scale`` (1.0 for [0, 1]-priced markets)
        when the venue prices in a different unit.

    """

    instrument_ids: tuple[InstrumentId, ...]

    # Signal thresholds and sizing.
    min_entry_edge: float = 0.06
    exit_edge: float = 0.015
    base_quantity: float = 25.0
    max_quantity: float = 150.0
    edge_qty_scale: float = 400.0
    uncertainty_dampen: float = 3.0
    horizon_size_floor: float = 0.35

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
