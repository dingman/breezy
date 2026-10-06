"""AUT-4 evaluation statistics glue: ETA arithmetic and power-at-n reporting.

``mde_one_sided`` and ``power_one_sided`` are imported from ``sample_size`` and never redefined
(AUT-4 r11 K2, RC-1); they are re-exported so evaluators import every statistic from one place.
"""

from __future__ import annotations

import datetime as dt
import math

from breezy.persistence.autonomy.sample_size import (
    mde_one_sided,
    power_one_sided,
)

__all__ = ["eta_date", "eta_days", "mde_one_sided", "power_at_n", "power_one_sided"]


def eta_days(n_min: int, n: int, rate_per_day: float) -> int | None:
    """Whole days until ``n`` reaches ``n_min`` at ``rate_per_day``; 0 once reached.

    ``None`` when the rate is not positive and the target is not yet met: no honest ETA exists.
    """
    if n_min < 0 or n < 0:
        raise ValueError("n_min and n must be non-negative")
    if n >= n_min:
        return 0
    if rate_per_day <= 0.0 or not math.isfinite(rate_per_day):
        return None
    return math.ceil((n_min - n) / rate_per_day)


def eta_date(today: dt.date, n_min: int, n: int, rate_per_day: float) -> dt.date | None:
    """The calendar date of :func:`eta_days`, or ``None`` when there is no ETA."""
    days = eta_days(n_min, n, rate_per_day)
    return None if days is None else today + dt.timedelta(days=days)


def power_at_n(sigma: float, n: int, alpha: float, delta: float) -> float:
    """Power reported on a verdict at the achieved ``n`` (a thin call of ``power_one_sided``)."""
    return power_one_sided(sigma, n, alpha, delta)
