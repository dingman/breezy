"""Pure location-correction math shared by analysis and the live ladder.

No I/O. ``breezy.analysis`` delegates here (it may import ``strategy``);
nothing in the live path imports ``breezy.analysis``. The daylight-hours
body is the formula previously inlined in
``scripts/analysis/nbp_skill_study._daylight_hours``.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from enum import Enum

from breezy.domain.quantile_density import EmosParams

__all__ = [
    "CorrectionForm",
    "correction_prediction_f",
    "daylight_hours",
    "emos_params_from_draw_entry",
]


class CorrectionForm(Enum):
    """The closed set of G2.0 correction forms (plan S4.1, R3-07). No other
    form may be introduced after S0."""

    NONE = "none"
    MONTH_OFFSET = "month_offset"
    LINEAR_DAYLENGTH = "linear_lst_day_length"


def daylight_hours(latitude_deg: float, day: dt.date) -> float:
    """Approximate astronomical daylight hours at ``latitude_deg`` on ``day``."""
    latitude = math.radians(latitude_deg)
    year_days = 366 if day.replace(month=12, day=31).timetuple().tm_yday == 366 else 365
    declination = math.radians(
        23.44 * math.sin((2.0 * math.pi / year_days) * (day.timetuple().tm_yday - 80))
    )
    cos_hour_angle = -math.tan(latitude) * math.tan(declination)
    cos_hour_angle = min(1.0, max(-1.0, cos_hour_angle))
    hour_angle = math.acos(cos_hour_angle)
    return (24.0 / math.pi) * hour_angle


def correction_prediction_f(
    form: CorrectionForm,
    *,
    month: int,
    day_length_hours: float,
    month_offsets: Mapping[int, float] | None = None,
    linear_coefficients: tuple[float, float] | None = None,
) -> float:
    """Additive correction applied to EMOS location ``a``.

    ``NONE`` is 0. ``MONTH_OFFSET`` is that month's offset and raises
    ``ValueError`` when the month is absent. ``LINEAR_DAYLENGTH`` is
    ``slope * day_length_hours + intercept``.
    """
    if form is CorrectionForm.NONE:
        return 0.0
    if form is CorrectionForm.MONTH_OFFSET:
        if month_offsets is None or month not in month_offsets:
            raise ValueError(f"CorrectionForm.MONTH_OFFSET needs an offset for month {month}")
        return month_offsets[month]
    if form is CorrectionForm.LINEAR_DAYLENGTH:
        if linear_coefficients is None:
            raise ValueError("CorrectionForm.LINEAR_DAYLENGTH needs (slope, intercept)")
        slope, intercept = linear_coefficients
        return slope * day_length_hours + intercept
    raise ValueError(f"unhandled CorrectionForm {form!r}")  # pragma: no cover


def emos_params_from_draw_entry(entry: Sequence[float], *, fallback_delta: float) -> EmosParams:
    """Parse one ``emos_draws_by_version`` JSON entry into :class:`EmosParams`
    (SL-8b review item 3).

    Accepts BOTH shapes: a 3-element ``[a, gamma, delta]`` entry (the
    current schema -- each draw carries its OWN resampled delta) and a
    2-element ``[a, gamma]`` entry (the pre-SL-8b schema, whose draws all
    shared the artefact's single top-level ``delta``) -- ``fallback_delta``
    (the artefact's own ``delta`` field) supplies the missing third value
    for the old shape, so an artefact written before this schema change
    still parses. Any other length is refused.
    """
    if len(entry) == 3:
        a, gamma, delta = entry
        return EmosParams(a=float(a), gamma=float(gamma), delta=float(delta))
    if len(entry) == 2:
        a, gamma = entry
        return EmosParams(a=float(a), gamma=float(gamma), delta=float(fallback_delta))
    raise ValueError(f"a draw entry must have 2 or 3 elements, got {len(entry)}: {entry!r}")
