"""``ArtefactBoundsProvider`` -- SL-13: the real implementation of the seam
:mod:`bounds` names ("the seam a later calibration slice fills").

SL-13 S2: the per-version EMOS point/draws resolution the LIVE strategy uses
(sha pin, fit-status gate, per-version pooling, the shared location
correction) now lives ONE place, :mod:`calibration_artefact`
(``LiveCalibration.resolve``). ``ArtefactBoundsProvider`` is a thin,
stateless-except-``cdf_method`` adapter: ``decision.evaluate`` resolves the
era-specific draws via ``LiveCalibration.resolve`` and hands them to this
provider call-by-call, per the ``BoundsProvider`` Protocol (``bounds.py``).

``load_bounds_artefact_draws``/``BoundsArtefactDraws``/
``BoundsArtefactPinMismatchError`` (the OLD loader, which re-parsed the SAME
``NbpCalibrationArtefact`` JSON shape ``calibration_artefact.
load_live_calibration`` also parses) are REMOVED (FQ-S4b, plan §3 S4b): the
live composition path (``composition.py``) stopped calling them at S2, and
``scripts/analysis/nbp_shadow_parity.py``, their last caller, migrated onto
``calibration_artefact.load_live_calibration`` (ONE sha-pinned read, shared
by both the live and batch legs) in S4b.
"""

from __future__ import annotations

from collections.abc import Sequence

from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    rung_probability_interval,
)

__all__ = ["ArtefactBoundsProvider"]


class ArtefactBoundsProvider:
    """``bounds.BoundsProvider`` backed by sha-pinned, era-resolved bootstrap
    EMOS draws (plan §3 S2). ``p_hat`` is the MEAN of the per-draw rung
    probabilities -- see ``rung_probability_interval``'s own docstring for
    why that is deterministic and sums to 1, unlike a per-rung median.
    """

    def __init__(self, *, cdf_method: CdfMethod) -> None:
        self._cdf_method = cdf_method

    def __call__(
        self,
        *,
        percentiles: Percentiles,
        draws: Sequence[EmosParams],
        ladder: Sequence[Rung],
        rung_id: str,
    ) -> RungBounds:
        if not draws:
            raise ValueError("ArtefactBoundsProvider needs at least one draw")
        interval = rung_probability_interval(percentiles, self._cdf_method, draws, ladder)
        point, lower, upper = interval[rung_id]
        return RungBounds(p_hat=point, p_lower=lower, p_upper=upper)
