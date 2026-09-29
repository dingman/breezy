"""``BoundsProvider`` -- the seam a later calibration slice fills.

Plan A-6 (docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md §12): "all
statistical uncertainty is carried by the bootstrap ``p_lower``/``p_upper``
(A-4 draws)." A later calibration slice supplies real bootstrap-draw
intervals through a pure function ``rung_probability_interval(...)`` in the
strategy layer; THIS module ships only the Protocol those draws satisfy, and
:mod:`decision` consumes it by injection -- it never computes a bound
itself, and there is no inline haircut arithmetic anywhere in this package.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple, Protocol, runtime_checkable

from breezy.strategy.ladder_ev.quantile_density import Rung

__all__ = ["BoundsProvider", "RungBounds"]


class RungBounds(NamedTuple):
    """``p_hat`` plus its lower/upper bound, for ONE rung at ONE snapshot."""

    p_hat: float
    p_lower: float
    p_upper: float


@runtime_checkable
class BoundsProvider(Protocol):
    """Supplies :class:`RungBounds` for one rung, given its assembled CDF.

    ``cdf`` is already the EMOS-recalibrated CDF (:func:`decision.evaluate`
    builds it from the quantile vector and the artefact's ``cdf_method``/
    ``emos`` before calling this). ``ladder`` is the full rung partition
    (needed by any implementation built on
    ``quantile_density.rung_probabilities``, which asserts completeness).
    """

    def __call__(
        self,
        *,
        cdf: Callable[[float], float],
        ladder: Sequence[Rung],
        rung_id: str,
    ) -> RungBounds: ...
