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
``BoundsArtefactPinMismatchError`` (the OLD loader, which re-parses the SAME
``NbpCalibrationArtefact`` JSON shape ``calibration_artefact.
load_live_calibration`` now also parses) are UNCHANGED and kept alongside:
the live composition path (``composition.py``) no longer calls them after
this slice, but ``scripts/analysis/nbp_shadow_parity.py`` (S4, not yet
migrated -- plan §4: "S4b needs S2") still does. Removing them here would
break that out-of-scope script ahead of its own slice; S4b is the slice that
migrates it onto ``LiveCalibration``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    rung_probability_interval,
)

__all__ = [
    "ArtefactBoundsProvider",
    "BoundsArtefactDraws",
    "BoundsArtefactPinMismatchError",
    "load_bounds_artefact_draws",
]

_UNPINNED_SHA256: Final[str] = "0" * 64
_FIT_STATUS_OK: Final[str] = "OK"
_FIT_STATUS_UNKNOWN: Final[str] = "UNKNOWN"
_SUPPORTED_RECALIBRATION: Final[str] = "none"
_SUPPORTED_CORRECTION_FORM: Final[str] = "none"


class BoundsArtefactPinMismatchError(ValueError):
    """Raised when ``expected_sha256`` is the unpinned all-zero placeholder,
    when the artefact file's own sha256 disagrees with it, when the parsed
    artefact carries zero bootstrap draws, or when the artefact's own
    ``fit_status`` is not ``"OK"``.

    Legacy loader's own error type -- see the module docstring: kept only
    for ``scripts/analysis/nbp_shadow_parity.py`` (S4) until its own
    migration slice (S4b)."""


@dataclass(frozen=True, slots=True)
class BoundsArtefactDraws:
    """Every reconstructed bootstrap ``EmosParams`` draw, pooled ACROSS every
    NBM version (finding F3 -- superseded by ``LiveCalibration.resolve``'s
    per-version resolution; see the module docstring)."""

    cdf_method: CdfMethod
    draws: tuple[EmosParams, ...]


def load_bounds_artefact_draws(path: str, *, expected_sha256: str) -> BoundsArtefactDraws:
    """Legacy loader: read, hash-verify and reconstruct every bootstrap
    ``EmosParams`` draw, POOLED across every NBM version (finding F3).

    See the module docstring: kept only for ``scripts/analysis/
    nbp_shadow_parity.py`` (S4) pending its own migration (S4b) onto
    ``calibration_artefact.load_live_calibration``, which performs the SAME
    sha-pin/fit-status checks per version, never pooled.
    """
    if expected_sha256 == _UNPINNED_SHA256:
        raise BoundsArtefactPinMismatchError(
            "expected_sha256 is the unpinned all-zero placeholder; there is "
            "no live refitting (plan §2.2) -- a real manifest pin is required",
        )
    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise BoundsArtefactPinMismatchError(
            f"bounds artefact at {path!r} hashes to {actual_sha256!r}, "
            f"expected the manifest-pinned {expected_sha256!r}",
        )
    payload: dict[str, Any] = json.loads(raw)
    fit_status = str(payload.get("fit_status", _FIT_STATUS_UNKNOWN))
    if fit_status != _FIT_STATUS_OK:
        raise BoundsArtefactPinMismatchError(
            f"bounds artefact at {path!r} carries fit_status={fit_status!r}, "
            f"not {_FIT_STATUS_OK!r} -- refusing to trade off a calibration "
            "fit that did not converge, or never asserted convergence at all",
        )
    recalibration = str(payload.get("recalibration", _SUPPORTED_RECALIBRATION))
    if recalibration != _SUPPORTED_RECALIBRATION:
        raise BoundsArtefactPinMismatchError(
            f"bounds artefact at {path!r} carries recalibration={recalibration!r}; "
            "the live bounds path currently supports only 'none' and refuses "
            "unsupported probability transforms closed",
        )
    correction_form = str(payload.get("correction_form", _SUPPORTED_CORRECTION_FORM))
    if correction_form != _SUPPORTED_CORRECTION_FORM:
        raise BoundsArtefactPinMismatchError(
            f"bounds artefact at {path!r} carries correction_form={correction_form!r}; "
            "the live bounds path currently supports only 'none' and refuses "
            "unsupported location transforms closed",
        )
    delta = float(payload["delta"])
    cdf_method = CdfMethod(payload["cdf_method"])
    draws: list[EmosParams] = []
    for version_draws in payload["emos_draws_by_version"].values():
        for a, gamma in version_draws:
            draws.append(EmosParams(a=float(a), gamma=float(gamma), delta=delta))
    if not draws:
        raise BoundsArtefactPinMismatchError(
            f"bounds artefact at {path!r} carries zero emos_draws_by_version entries",
        )
    return BoundsArtefactDraws(cdf_method=cdf_method, draws=tuple(draws))


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
