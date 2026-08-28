"""The preserved trading decision: model probability vs executable bid/ask.

This is ``ForecastMispricingStrategy.evaluate_instrument`` from the operator's
bundle, extracted verbatim in its arithmetic and branching, as a pure function
of its inputs instead of a method on the Nautilus ``Strategy`` subclass. That
change is the whole point of the extraction: every branch below --
``edge_after_costs``, the separate entry/exit edge thresholds, the
uncertainty-damped and horizon-scaled sizing, and the optional short side --
is exactly the operator's intent, and is now unit-testable with no Nautilus
object, no cache, and no clock in scope.

Two adaptations from the bundle, both forced by the surrounding plumbing
change and neither touching the math itself:

1. ``forecast.horizon_hours`` replaces ``self.hours_to_settlement(contract, now)``
   for the horizon-scaled-sizing term. See
   ``breezy.strategy.weather_common.forecast_source`` for why: the bundle had
   a fabricated settlement clock to compute that independently; Breezy does
   not, so the one horizon the injected forecast source is required to keep
   live (see that module's docstring) now serves both purposes.
2. ``model_p`` comes from ``engine.bucket_probability(contract.facts, ...)``
   rather than ``engine.contract_probability(contract, ...)`` -- a rename
   forced by ``breezy.strategy.weather_common.bucket_contract.MispricingContract``
   wrapping real venue facts instead of the bundle's own ``TemperatureContract``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from breezy.strategy.weather_common.models import SideIntent, SignalDecision
from breezy.strategy.weather_common.risk import edge_after_costs

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import ForecastSnapshot, MarketQuote
    from breezy.strategy.weather_common.probability import WeatherProbabilityEngine
    from breezy.strategy.weather_common.risk import RiskManager

__all__ = ["evaluate_instrument"]


def evaluate_instrument(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    forecast: ForecastSnapshot,
    now: datetime,
    current_qty: float,
    engine: WeatherProbabilityEngine,
    risk: RiskManager,
    cfg: ForecastMispricingConfig,
) -> SignalDecision | None:
    """Return the desired position change, or ``None`` for "do nothing"."""
    if forecast.is_stale(now, cfg.stale_forecast_hours):
        return SignalDecision(
            instrument_id=contract.instrument_id,
            intent=SideIntent.FLAT,
            model_probability=0.0,
            market_probability=0.0,
            edge=0.0,
            conviction=0.0,
            quantity=0.0,
            reason="stale_forecast",
        )
    age_min = (now - quote.ts_event).total_seconds() / 60.0
    ok, _why = risk.quote_tradable(quote, contract.price_scale, age_min)
    if not ok:
        return None

    model_p = engine.bucket_probability(
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
    if bid_p is None or ask_p is None:
        return None

    long_edge = edge_after_costs(
        model_p=model_p,
        bid_p=bid_p,
        ask_p=ask_p,
        intent_long_yes=True,
        cost=cfg.transaction_cost_prob,
    )
    short_edge = edge_after_costs(
        model_p=model_p,
        bid_p=bid_p,
        ask_p=ask_p,
        intent_long_yes=False,
        cost=cfg.transaction_cost_prob,
    )
    assert long_edge is not None and short_edge is not None

    if current_qty > 1e-9 and long_edge < cfg.exit_edge:
        return SignalDecision(
            contract.instrument_id,
            SideIntent.FLAT,
            model_p,
            ask_p,
            long_edge,
            0.0,
            0.0,
            "mispricing_exit_long",
            {"bid": bid_p, "ask": ask_p},
        )
    if current_qty < -1e-9 and short_edge < cfg.exit_edge:
        return SignalDecision(
            contract.instrument_id,
            SideIntent.FLAT,
            model_p,
            bid_p,
            short_edge,
            0.0,
            0.0,
            "mispricing_exit_short",
            {"bid": bid_p, "ask": ask_p},
        )

    intent = SideIntent.FLAT
    edge = 0.0
    mkt = mid_p or ask_p
    if long_edge >= cfg.min_entry_edge and long_edge >= short_edge:
        intent = SideIntent.LONG_YES
        edge = long_edge
        mkt = ask_p
    elif short_edge >= cfg.min_entry_edge and cfg.allow_short:
        intent = SideIntent.SHORT_YES
        edge = short_edge
        mkt = bid_p
    else:
        return None

    _, sigma = engine.mu_sigma(
        forecast.expected_high_f,
        forecast.horizon_hours,
        contract.facts.settlement_station,
        contract.facts.climate_day,
    )
    hours_left = max(forecast.horizon_hours, 0.5)
    horizon_frac = min(1.0, hours_left / 48.0)
    horizon_frac = max(horizon_frac, cfg.horizon_size_floor)
    damp = 1.0 / (1.0 + sigma / max(cfg.uncertainty_dampen, 0.1))
    qty = cfg.base_quantity + cfg.edge_qty_scale * edge
    qty *= damp * horizon_frac
    qty = min(max(qty, 1.0), cfg.max_quantity)
    conviction = min(1.0, edge / max(cfg.min_entry_edge, 1e-6) * damp)

    return SignalDecision(
        instrument_id=contract.instrument_id,
        intent=intent,
        model_probability=model_p,
        market_probability=mkt,
        edge=edge,
        conviction=conviction,
        quantity=qty,
        reason="forecast_mispricing",
        metadata={
            "sigma_f": sigma,
            "nws_high": forecast.expected_high_f,
            "horizon_h": forecast.horizon_hours,
            "long_edge": long_edge,
            "short_edge": short_edge,
        },
    )
