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

from datetime import UTC, date, datetime, time, timedelta
from typing import Final

from breezy.strategy.ladder_ev.config import LadderEvConfig

__all__ = ["forecast_margin", "hours_to_settlement"]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_HOUR: Final[int] = 3_600 * _NS_PER_SECOND


def forecast_margin(h_hours: float, cfg: LadderEvConfig) -> float:
    """The horizon-aware policy buffer for a forecast-mode take (A-6)."""
    m0 = cfg.margin_m0
    m24 = cfg.margin_m24
    h0 = float(cfg.margin_h0_hours)
    span = 24.0 - h0
    t = min(1.0, max(0.0, (h_hours - h0) / span))
    return m0 + (m24 - m0) * t


def hours_to_settlement(
    *,
    now_ns: int,
    climate_day: date,
    std_utc_offset_hours: float,
) -> float:
    """Hours from ``now_ns`` to LST midnight ending ``climate_day``.

    The daily high is fully determined at that midnight, which is local
    midnight starting ``climate_day + 1``. The venue listing's
    ``expiration_ns`` is not this instant. The pure parity path keeps its own
    copy of this formula (``nbp_shadow_parity_pure.hours_to_settlement``) and
    must not call this function.
    """
    settlement_ns = _local_midnight_utc_ns(
        climate_day + timedelta(days=1),
        std_utc_offset_hours,
    )
    return (settlement_ns - now_ns) / _NS_PER_HOUR


def _local_midnight_utc_ns(local_date: date, std_utc_offset_hours: float) -> int:
    naive_midnight = datetime.combine(local_date, time(0, 0), tzinfo=UTC)
    utc_instant = naive_midnight - timedelta(hours=std_utc_offset_hours)
    return int(utc_instant.timestamp()) * _NS_PER_SECOND
