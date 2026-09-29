"""``ArtefactBoundsProvider`` -- SL-13: the real implementation of the seam
:mod:`bounds` names ("the seam a later calibration slice fills").

Reads the family manifest's sha-pinned ``density_artefact_path`` in the
richer bootstrap-draw JSON shape ``breezy.analysis.nbp_calibration.
NbpCalibrationArtefact.to_json_dict()`` writes (via ``write_artefact``) --
NOT ``calibration_artefact.CalibrationArtefact``'s flat point-estimate shape
(which carries only ONE ``EmosParams`` and cannot answer
``rung_probability_interval``'s ``draws`` argument). Same hash-pin
discipline as ``calibration_artefact.load_calibration_artefact``: refuses
the all-zero placeholder and any byte mismatch, unconditionally -- there is
no live refitting (plan §2.2).

``rung_probability_interval`` needs the snapshot's raw ``Percentiles``,
which ``decision.evaluate`` never forwards to an injected ``BoundsProvider``
(only the already-built, point-calibrated ``cdf`` callable -- see
``decision.py``, committed at SL-12 and unmodified here). This class closes
that gap the only way the existing ``BoundsProvider`` Protocol allows: it is
constructed with a ``percentiles_fn`` callable that independently reads the
SAME ``ForecastQuantileVector`` the strategy's own ``evaluate_snapshot`` call
just read off ``ForecastQuantileStateActor`` (the composition root wires
both from the ONE actor instance -- never two independent state sources, see
``app/trade.py``'s ``forecast_quantile_ladder`` branch). A ``None`` read
(forecast unavailable) raises :class:`BoundsNotReadyError` rather than
silently degrading to a point estimate -- ``decision.evaluate`` already
refuses to reach a ``bounds_provider`` call at all when ``vector is None``
(its own ``Refuse("forecast_unavailable")`` branch runs first), so this is
unreachable in the composed strategy; it exists only as defence in depth
against a ``percentiles_fn`` that reads a different snapshot or races.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
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
    "BoundsArtefactPinMismatchError",
    "BoundsNotReadyError",
    "load_bounds_artefact_draws",
]

_UNPINNED_SHA256: Final[str] = "0" * 64

#: Mirrors `breezy.analysis.nbp_calibration.FIT_STATUS_OK`/
#: `FIT_STATUS_UNKNOWN` by VALUE only -- `breezy.strategy` (the live trading
#: path) may never import `breezy.analysis` (pyproject.toml, "The live
#: trading path never imports the offline analysis layer"), so this is a
#: deliberate, contract-required duplication of the two string constants,
#: not a second source of truth for the convergence RULE itself (SL-8b2: a
#: non-OK `fit_status` must fail this loader closed exactly like a bad sha
#: pin).
_FIT_STATUS_OK: Final[str] = "OK"
_FIT_STATUS_UNKNOWN: Final[str] = "UNKNOWN"


class BoundsArtefactPinMismatchError(ValueError):
    """Raised when ``expected_sha256`` is the unpinned all-zero placeholder,
    when the artefact file's own sha256 disagrees with it, when the parsed
    artefact carries zero bootstrap draws, or when the artefact's own
    ``fit_status`` is not ``"OK"`` (SL-8b2 -- missing entirely counts as
    ``"UNKNOWN"``, not OK)."""


class BoundsNotReadyError(RuntimeError):
    """``percentiles_fn()`` returned ``None`` at call time -- see the module docstring."""


@dataclass(frozen=True, slots=True)
class BoundsArtefactDraws:
    """Every reconstructed per-version bootstrap ``EmosParams`` draw, pooled."""

    cdf_method: CdfMethod
    draws: tuple[EmosParams, ...]


def load_bounds_artefact_draws(path: str, *, expected_sha256: str) -> BoundsArtefactDraws:
    """Read, hash-verify and reconstruct every bootstrap ``EmosParams`` draw
    from an ``NbpCalibrationArtefact``-shaped JSON file
    (``breezy.analysis.nbp_calibration.write_artefact``).

    Each version's ``(a, gamma)`` draws are paired with the artefact's own
    top-level ``delta`` (shared across every version and draw, mirroring
    ``NbpCalibrationArtefact.emos_draws_by_version``'s own convention) and
    pooled into ONE flat ``draws`` tuple -- ``rung_probability_interval``
    takes a single ``Sequence[EmosParams]``, not one per version.

    Raises :class:`BoundsArtefactPinMismatchError` (SL-8b2) if the
    artefact's own ``fit_status`` is not ``"OK"`` -- a missing ``fit_status``
    key counts as ``"UNKNOWN"``, not OK, exactly like
    ``breezy.analysis.nbp_calibration.artefact_from_json_dict``'s own
    parser. The live strategy must never trade off bootstrap draws from a
    fit that did not converge, or never asserted convergence at all.
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
            f"not {_FIT_STATUS_OK!r} (SL-8b2) -- refusing to trade off a "
            "calibration fit that did not converge, or never asserted "
            "convergence at all",
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
    """``bounds.BoundsProvider`` backed by sha-pinned bootstrap EMOS draws.

    Satisfies the ``BoundsProvider`` Protocol structurally (``__call__(*,
    cdf, ladder, rung_id)``); ``cdf`` itself is unused -- see the module
    docstring for why the real interval needs ``percentiles_fn()`` instead.
    """

    def __init__(
        self,
        *,
        cdf_method: CdfMethod,
        draws: Sequence[EmosParams],
        percentiles_fn: Callable[[], Percentiles | None],
    ) -> None:
        if not draws:
            raise ValueError("ArtefactBoundsProvider needs at least one draw")
        self._cdf_method = cdf_method
        self._draws = tuple(draws)
        self._percentiles_fn = percentiles_fn

    def __call__(
        self,
        *,
        cdf: Callable[[float], float],
        ladder: Sequence[Rung],
        rung_id: str,
    ) -> RungBounds:
        del cdf  # unused -- see module docstring
        percentiles = self._percentiles_fn()
        if percentiles is None:
            raise BoundsNotReadyError(
                "ArtefactBoundsProvider: percentiles_fn() returned None; "
                "decision.evaluate should never reach a bounds_provider call "
                "with vector is None (see its own Refuse('forecast_unavailable') "
                "branch) -- this is defence in depth, not a reachable path",
            )
        interval = rung_probability_interval(percentiles, self._cdf_method, self._draws, ladder)
        point, lower, upper = interval[rung_id]
        return RungBounds(p_hat=point, p_lower=lower, p_upper=upper)
