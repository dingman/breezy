"""Alias of :mod:`breezy.domain.quantile_density` (AUT-6 WP5, M3).

The module moved unchanged to ``domain/`` so the AUT-6 analysis closure can import it without the
venue adapters. Every module-level name is re-exported here by identity, so existing importers of
the strategy path keep the very same objects.
"""

from __future__ import annotations

from breezy.domain.quantile_density import (
    _MIN_SD,
    _PERCENTILE_PROBS,
    _SQRT2,
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    _assert_complete_partition,
    _dedup_knots,
    _FitFallbackAwareCdf,
    _logger,
    _normal_cdf_fn,
    _pchip_normal_tails_cdf,
    _skew_normal_cdf,
    _tail_sort_key,
    apply_emos,
    build_cdf,
    rung_probabilities,
    rung_probability_interval,
)

__all__ = [
    "_MIN_SD",
    "_PERCENTILE_PROBS",
    "_SQRT2",
    "CdfMethod",
    "EmosParams",
    "Percentiles",
    "Rung",
    "_FitFallbackAwareCdf",
    "_assert_complete_partition",
    "_dedup_knots",
    "_logger",
    "_normal_cdf_fn",
    "_pchip_normal_tails_cdf",
    "_skew_normal_cdf",
    "_tail_sort_key",
    "apply_emos",
    "build_cdf",
    "rung_probabilities",
    "rung_probability_interval",
]
