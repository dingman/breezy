"""``BoundsProvider`` -- the seam a later calibration slice fills.

Plan A-6 (docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md §12): "all
statistical uncertainty is carried by the bootstrap ``p_lower``/``p_upper``
(A-4 draws)." :mod:`artefact_bounds` supplies a real bootstrap-draw interval
through :func:`breezy.strategy.ladder_ev.quantile_density.
rung_probability_interval`; THIS module ships only the Protocol those draws
satisfy, and :mod:`decision` consumes it by injection -- it never computes a
bound itself, and there is no inline haircut arithmetic anywhere in this
package.

SL-13 S2: the Protocol takes the vector's own ``percentiles`` and the
calibration's ERA-RESOLVED ``draws`` directly (plan §3 S2) -- never a ``cdf``
callable and never a ``percentiles_fn`` closure. ``decision.evaluate`` already
holds the visible ``ForecastQuantileVector`` and has just resolved its
per-version calibration via ``calibration_artefact.LiveCalibration.resolve``
by the time it calls a ``BoundsProvider``, so there is no second read seam to
plumb through composition.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, Protocol, runtime_checkable

from breezy.strategy.ladder_ev.quantile_density import EmosParams, Percentiles, Rung

__all__ = ["BoundsProvider", "RungBounds"]


class RungBounds(NamedTuple):
    """``p_hat`` plus its lower/upper bound, for ONE rung at ONE snapshot."""

    p_hat: float
    p_lower: float
    p_upper: float


@runtime_checkable
class BoundsProvider(Protocol):
    """Supplies :class:`RungBounds` for one rung, given the visible
    percentiles and the resolved, era-specific bootstrap draws.

    ``ladder`` is the full rung partition (needed by any implementation
    built on ``quantile_density.rung_probabilities``, which asserts
    completeness).
    """

    def __call__(
        self,
        *,
        percentiles: Percentiles,
        draws: Sequence[EmosParams],
        ladder: Sequence[Rung],
        rung_id: str,
    ) -> RungBounds: ...
