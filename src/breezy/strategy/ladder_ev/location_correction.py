"""Alias of :mod:`breezy.domain.location_correction` (AUT-6 WP5, M3).

The module moved unchanged to ``domain/``. Every module-level name is re-exported here by
identity, so existing importers of the strategy path keep the very same objects.
"""

from __future__ import annotations

from breezy.domain.location_correction import (
    CorrectionForm,
    correction_prediction_f,
    daylight_hours,
    emos_params_from_draw_entry,
)

__all__ = [
    "CorrectionForm",
    "correction_prediction_f",
    "daylight_hours",
    "emos_params_from_draw_entry",
]
