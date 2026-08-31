"""The preserved trading decision: calibrated probability vs market midpoint.

This is ``CalibrationMeanReversionStrategy.evaluate_instrument`` from the
operator's bundle, extracted verbatim in its arithmetic and branching, as a
pure function of its inputs instead of a method on the Nautilus ``Strategy``
subclass. Every branch below -- the z-score against
``expected_probability_se``, the separate entry/exit z thresholds, the absolute
probability-gap floor, the executable-gap-after-costs screen, the short
permission check and the z-scaled sizing -- is exactly the operator's intent,
and is now unit-testable with no Nautilus object, cache or clock in scope.

Three adaptations from the bundle, all forced by the surrounding plumbing
change and none of them touching the math:

1. ``hours_left`` comes from ``forecast.horizon_hours`` rather than from
   ``self.hours_to_settlement(contract, now)``. The bundle computed that from a
   FABRICATED per-contract settlement clock (a hardcoded ``time(23, 59)`` in a
   hardcoded ``"America/Chicago"``, wrong for four of the venue's five cities).
   Breezy has no wall-clock settlement source at the strategy layer -- see
   ``breezy.strategy.weather_common.forecast_source`` for the contract that
   replaces it, and ``bucket_contract`` for why the clock was removed.
2. ``cal_p`` comes from ``engine.bucket_probability(contract.facts, ...)``
   rather than ``engine.contract_probability(contract, ...)`` -- a rename forced
   by ``MispricingContract`` wrapping real venue facts instead of the bundle's
   hand-rolled ``TemperatureContract``.
3. ``current_qty`` is passed in, from the native
   ``Portfolio.net_position``, rather than read from a strategy-owned
   ``portfolio_view`` ledger the bundle mutated by hand. The native portfolio
   cannot drift from what Nautilus believes is true.

The recheck throttle is exposed separately as :func:`should_throttle` rather
than folded into :func:`evaluate_instrument`. It is scheduling, not decision
math, and the caller must know whether it fired in order to decide whether to
stamp ``last_eval`` -- which is exactly the ordering the bundle had inline.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from breezy.strategy.weather_common.models import SideIntent, SignalDecision
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.calibration_mean_reversion.config import (
        CalibrationMeanReversionConfig,
    )
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import ForecastSnapshot, MarketQuote
    from breezy.strategy.weather_common.probability import WeatherProbabilityEngine

__all__ = ["evaluate_instrument", "should_throttle"]


def should_throttle(
    *,
    last_eval: datetime | None,
    now: datetime,
    current_qty: float,
    cfg: CalibrationMeanReversionConfig,
) -> bool:
    """Whether this instrument was evaluated too recently to look again.

    An instrument HOLDING a position is never throttled: the exit branch must
    stay responsive even when entries are being rate-limited.
    """
    if last_eval is None:
        return False
    if abs(current_qty) >= 1e-9:
        return False
    elapsed_min = (now - last_eval).total_seconds() / 60.0
    return elapsed_min < cfg.recheck_minutes


def evaluate_instrument(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    forecast: ForecastSnapshot,
    now: datetime,
    current_qty: float,
    engine: WeatherProbabilityEngine,
    cfg: CalibrationMeanReversionConfig,
    refusals: RefusalCounter | None = None,
) -> SignalDecision | None:
    """Return the desired position change, or ``None`` for "do nothing"."""
    hours_left = forecast.horizon_hours
    if hours_left < cfg.min_horizon_hours:
        if abs(current_qty) > 1e-9:
            return SignalDecision(
                contract.instrument_id,
                SideIntent.FLAT,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                "calibration_horizon_flatten",
            )
        return None

    if cfg.require_stable_forecast:
        age_min = (now - forecast.published_at).total_seconds() / 60.0
        if age_min < cfg.stable_forecast_minutes:
            return None

    cal_p = engine.bucket_probability(
        contract.facts, forecast.expected_high_f, forecast.horizon_hours,
    )
    scale = (
        cfg.price_scale_override if cfg.price_scale_override is not None else contract.price_scale
    )
    bid_p, ask_p, mid_p = (
        quote.implied_bid(scale),
        quote.implied_ask(scale),
        quote.implied_mid(scale),
    )
    if mid_p is None or bid_p is None or ask_p is None:
        return None

    se = engine.expected_probability_se(
        cal_p, forecast.horizon_hours, extra_market_noise=cfg.extra_market_noise,
    )
    z_mid = (mid_p - cal_p) / se
    gap = mid_p - cal_p

    if current_qty > 1e-9 and z_mid > -cfg.exit_z:
        # Long YES was opened because the market was too cheap (z negative).
        return SignalDecision(
            contract.instrument_id,
            SideIntent.FLAT,
            cal_p,
            mid_p,
            abs(gap),
            0.0,
            0.0,
            "calibration_z_exit_long",
            {"z": z_mid, "se": se},
        )
    if current_qty < -1e-9 and z_mid < cfg.exit_z:
        return SignalDecision(
            contract.instrument_id,
            SideIntent.FLAT,
            cal_p,
            mid_p,
            abs(gap),
            0.0,
            0.0,
            "calibration_z_exit_short",
            {"z": z_mid, "se": se},
        )

    if abs(gap) < cfg.min_abs_prob_gap or abs(z_mid) < cfg.entry_z:
        return None

    # Market too high vs calibrated P -> short YES. Market too low -> long YES.
    if z_mid >= cfg.entry_z:
        intent = SideIntent.SHORT_YES
        executable_gap = bid_p - cal_p - cfg.transaction_cost_prob
        mkt = bid_p
    else:
        intent = SideIntent.LONG_YES
        executable_gap = cal_p - ask_p - cfg.transaction_cost_prob
        mkt = ask_p
    if intent is SideIntent.SHORT_YES and not cfg.allow_short:
        # Counted, not merely suppressed: this strategy was SHORT_YES-only in
        # the tested window, so this branch can silence it entirely.
        if refusals is not None:
            refusals.record(SHORTS_DISABLED)
        return None
    if executable_gap < cfg.min_model_edge:
        return None

    qty = min(
        cfg.max_quantity,
        cfg.base_quantity + cfg.z_qty_scale * (abs(z_mid) - cfg.entry_z + 1.0),
    )
    return SignalDecision(
        instrument_id=contract.instrument_id,
        intent=intent,
        model_probability=cal_p,
        market_probability=mkt,
        edge=executable_gap,
        conviction=min(1.0, abs(z_mid) / cfg.entry_z),
        quantity=qty,
        reason="calibration_z_entry",
        metadata={
            "z": z_mid,
            "se": se,
            "cal_p": cal_p,
            "mid_p": mid_p,
            "nws_high": forecast.expected_high_f,
            "horizon_h": forecast.horizon_hours,
        },
    )
