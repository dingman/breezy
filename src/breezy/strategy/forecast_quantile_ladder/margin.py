"""Forecast-mode margin -- ruling A-6 (docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md §12).

``margin(h) = m0 + (m24 - m0) * clamp((h - h0) / (24 - h0), 0, 1)``, with
``m0 = 0.02``, ``m24 = 0.06`` and ``h0 = 6 h`` taken from the EXISTING,
committed ``LadderEvConfig`` defaults (``margin_m0``/``margin_m24``/
``margin_h0_hours``, pre-dating any NBP data) -- adopting them is therefore
outcome-free.

**Archive-cell gate dropped for this family (A-6).** ``p_hat`` comes from a
calibrated CDF, not a cell frequency, and all statistical uncertainty is
carried by the bootstrap ``p_lower``/``p_upper`` bounds (see ``bounds.py``),
so this function takes NO ``n_cell``/``n_min_cell`` -- unlike
``breezy.strategy.ladder_ev.scoring.margin``, which this module deliberately
does not call and does not modify.
"""

from __future__ import annotations

from breezy.strategy.ladder_ev.config import LadderEvConfig

__all__ = ["forecast_margin"]


def forecast_margin(h_hours: float, cfg: LadderEvConfig) -> float:
    """The horizon-aware policy buffer for a forecast-mode take (A-6)."""
    m0 = cfg.margin_m0
    m24 = cfg.margin_m24
    h0 = float(cfg.margin_h0_hours)
    span = 24.0 - h0
    t = min(1.0, max(0.0, (h_hours - h0) / span))
    return m0 + (m24 - m0) * t
