"""Configuration for
:class:`~breezy.strategy.calibration_mean_reversion.strategy.CalibrationMeanReversionStrategy`.

Every signal knob is carried over from the bundle's
``CalibrationMeanReversionConfig`` / ``WeatherStrategyConfig`` sections. The
same four fields the first bundle's integration dropped are dropped here, for
the same reasons (see ``forecast_mispricing/config.py``):

* ``nws_client_id`` -- the weather client id is a shared CONSTANT
  (``breezy.runtime.backtest_feed.NWS_BACKTEST_CLIENT_ID``), not a per-strategy
  override. A mismatch there is a silently-dropped subscription, so it is not a
  legitimate customisation point.
* ``diagnostic_log`` -- logging is unconditional.
* ``flatten_on_stop`` -- that is the native ``StrategyConfig.manage_stop`` flag
  Nautilus already provides; a hand-rolled duplicate is a reimplementation.
* ``strategy_id`` -- the bundle defaulted it to the string
  ``"CALIBRATION-MR-001"``, but the native ``StrategyConfig.strategy_id`` is a
  ``StrategyId``, not a ``str``. Callers set it natively.
"""

from __future__ import annotations

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.config import StrategyConfig

__all__ = ["CalibrationMeanReversionConfig"]


class CalibrationMeanReversionConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`CalibrationMeanReversionStrategy`.

    Parameters
    ----------
    instrument_ids : tuple[InstrumentId, ...]
        Every weather-bucket market this strategy instance may trade. Each must
        be present in the cache at ``on_start`` and carry KNOWN weather bucket
        facts (``breezy.domain.weather_bucket_facts``).
    entry_z, exit_z : float
        Entry requires ``|z| >= entry_z`` where ``z`` is the market-vs-model
        probability gap in units of
        ``WeatherProbabilityEngine.expected_probability_se``. An open position
        exits once ``z`` reverts inside ``exit_z``. Two distinct thresholds,
        deliberately -- collapsing them would churn positions on noise.
    min_abs_prob_gap : float
        An absolute floor on ``|mid_p - calibrated_p|``, applied ALONGSIDE the
        z-score so a tiny gap divided by a tiny standard error cannot manufacture
        a large z.
    extra_market_noise : float
        Added to the modelled standard error, widening it. Represents book noise
        the Bernoulli/horizon terms do not capture.
    base_quantity, max_quantity, z_qty_scale : float
        Position sizing: ``base_quantity + z_qty_scale * (|z| - entry_z + 1)``,
        clipped to ``max_quantity``.
    min_horizon_hours : float
        Below this many hours to settlement the strategy will not open, and
        flattens anything already open. Sourced from
        ``ForecastSnapshot.horizon_hours`` -- see the strategy module docstring.
    recheck_minutes : float
        Throttle: a FLAT instrument is re-evaluated at most this often. An
        instrument holding a position is never throttled.
    require_stable_forecast, stable_forecast_minutes : bool, float
        When enabled, a forecast younger than ``stable_forecast_minutes`` is not
        traded -- this strategy is a mean-reversion play against a settled
        forecast, so it deliberately waits out the revision window that
        ``breezy.strategy.forecast_revision`` exists to trade.
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
    entry_z: float = 1.85
    exit_z: float = 0.60
    min_abs_prob_gap: float = 0.07
    extra_market_noise: float = 0.035
    base_quantity: float = 15.0
    max_quantity: float = 80.0
    z_qty_scale: float = 18.0
    min_horizon_hours: float = 6.0
    recheck_minutes: float = 20.0
    require_stable_forecast: bool = True
    stable_forecast_minutes: float = 25.0

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
