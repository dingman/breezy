"""Live calibration consumer -- the REAL ``NbpCalibrationArtefact`` schema
(SL-13 S2, plan §2 D2, §3 S2, findings F1-F4).

``load_live_calibration`` is now the ONE loader the live strategy uses. It
reads the sha-pinned artefact JSON ``breezy.analysis.nbp_calibration.
NbpCalibrationArtefact.to_json_dict`` writes -- ``schema_version`` 1, keys
``emos_params_by_version``/``emos_draws_by_version`` (never the old flat
``{"emos": {...}}`` shape) -- and resolves per-(NBM version era, station
latitude, climate day) ``EmosParams``, both the point estimate and every
bootstrap draw for THAT version only (finding F3: draws are never pooled
across versions). The shared, pure location correction
(``breezy.strategy.ladder_ev.location_correction``) is applied identically to
the point and to every draw's own ``a`` (plan D2) -- this module performs NO
correction math of its own, only orchestration.

There is no live refitting (plan §2.2): ``load_live_calibration`` refuses the
unpinned all-zero sha, any sha mismatch, ``fit_status != "OK"``, any
``converged_by_version`` entry that is ``False``, ``recalibration != "none"``,
a ``correction_form`` outside ``{"none", "linear_lst_day_length"}`` (finding
F4: the LST-day-length form this registered artefact actually carries), a
linear form missing its coefficients, and a version with zero draws (finding
F2: including the real 3-element ``[a, gamma, delta]`` bootstrap-draw shape,
handled via ``location_correction.emos_params_from_draw_entry`` rather than
crashing on an uncaught ``ValueError``). Any other malformed/missing field in
an otherwise-parseable payload also fails CLOSED with the same typed error,
never an uncaught exception (plan §3 S2 item 8).

``CalibrationArtefact``/``load_calibration_artefact`` (the old flat,
single-``EmosParams`` shape) are UNCHANGED and kept alongside: SL-13's own
live composition path (``composition.py``/``decision.py``/``strategy.py``)
no longer uses them after this slice, but ``scripts/analysis/
nbp_shadow_parity.py``/``nbp_shadow_parity_pure.py`` (S4, not yet migrated --
plan §4: "S4b needs S2") still construct and pass them. Removing them here
would break that out-of-scope script ahead of its own slice; S4b is the
slice that migrates it onto ``LiveCalibration``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from breezy.strategy.ladder_ev.location_correction import (
    CorrectionForm,
    correction_prediction_f,
    daylight_hours,
    emos_params_from_draw_entry,
)
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams

__all__ = [
    "CalibrationArtefact",
    "CalibrationArtefactPinMismatchError",
    "CalibrationArtefactUnknownVersionError",
    "LiveCalibration",
    "ResolvedCalibration",
    "load_calibration_artefact",
    "load_live_calibration",
]

_UNPINNED_SHA256: Final[str] = "0" * 64
_FIT_STATUS_OK: Final[str] = "OK"
_FIT_STATUS_UNKNOWN: Final[str] = "UNKNOWN"
_SUPPORTED_RECALIBRATION: Final[str] = "none"
_SUPPORTED_CORRECTION_FORMS: Final[frozenset[str]] = frozenset(
    {CorrectionForm.NONE.value, CorrectionForm.LINEAR_DAYLENGTH.value},
)


class CalibrationArtefactPinMismatchError(ValueError):
    """Raised when the sha pin is unset/mismatched, or when the parsed
    artefact fails any fail-closed schema check: a non-``"OK"`` fit status, a
    non-converged version, an unsupported ``recalibration``/
    ``correction_form``, a linear form missing its coefficients, zero draws
    for a version, or any other malformed/missing field."""


class CalibrationArtefactUnknownVersionError(KeyError):
    """Raised by :meth:`LiveCalibration.resolve` when ``era`` names an NBM
    version the artefact carries no parameters/draws for. The caller
    (``decision.evaluate``) turns this into ``Refuse("calibration_version_
    unavailable")`` -- never an uncaught exception on the live tick path."""


@dataclass(frozen=True, slots=True)
class CalibrationArtefact:
    """A fitted, sha-pinned M2 recalibration -- never fitted here (plan §2.2).

    Legacy flat shape (ONE ``EmosParams``, no per-version resolution, no
    bootstrap draws). See the module docstring: kept only for
    ``scripts/analysis/nbp_shadow_parity*.py`` (S4) until its own migration
    slice (S4b).
    """

    sha256: str
    cdf_method: CdfMethod
    emos: EmosParams


def load_calibration_artefact(path: str, *, expected_sha256: str) -> CalibrationArtefact:
    """Read, hash-verify and parse the legacy flat artefact at ``path``.

    Raises
    ------
    CalibrationArtefactPinMismatchError
        If ``expected_sha256`` is the unpinned all-zero placeholder, or if
        the file's own sha256 disagrees with it.
    """
    if expected_sha256 == _UNPINNED_SHA256:
        raise CalibrationArtefactPinMismatchError(
            "expected_sha256 is the unpinned all-zero placeholder; there is "
            "no live refitting (plan §2.2, SL-12) -- a real manifest pin is required",
        )
    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} hashes to {actual_sha256!r}, "
            f"expected the manifest-pinned {expected_sha256!r}",
        )
    payload: dict[str, Any] = json.loads(raw)
    emos_payload = payload["emos"]
    return CalibrationArtefact(
        sha256=actual_sha256,
        cdf_method=CdfMethod(payload["cdf_method"]),
        emos=EmosParams(
            a=float(emos_payload["a"]),
            gamma=float(emos_payload["gamma"]),
            delta=float(emos_payload["delta"]),
        ),
    )


@dataclass(frozen=True, slots=True)
class ResolvedCalibration:
    """One ``(era, latitude_deg, climate_day)`` resolution (plan D2):
    the location-corrected point estimate, every corrected bootstrap draw
    for THAT version only, and the correction amount itself (observability).

    **``point`` is never read by the live trading path.** Ruling A-6 (plan
    §12): "all statistical uncertainty is carried by the bootstrap
    ``p_lower``/``p_upper``" -- :func:`decision.evaluate` forwards only
    ``draws`` into the injected ``BoundsProvider``; ``p_hat`` itself is the
    MEAN of the per-draw rung probabilities (``ArtefactBoundsProvider`` ->
    ``quantile_density.rung_probability_interval``), never this field.
    ``point`` is kept, computed, and exposed anyway (FQ-S2 statistics
    review, disposition: keep + document) because it is the ONE
    location-corrected value a cross-module parity check can compare
    against the analysis path's own point-CDF (``scripts/analysis/
    nbp_skill_study.calibrated_m2_rung_probabilities``) without
    re-deriving it by hand -- see ``tests/unit/
    test_fq_live_analysis_point_cdf_parity.py``, which pins live/analysis
    point-CDF rung probabilities equal to within 1e-12.
    """

    cdf_method: CdfMethod
    point: EmosParams
    draws: tuple[EmosParams, ...]
    correction_f: float


@dataclass(frozen=True, slots=True)
class LiveCalibration:
    """Sha-pinned, per-version EMOS parameters plus the shared location
    correction (plan D2) -- the ONE live calibration consumer.

    Construct via :func:`load_live_calibration`, never by hand in production
    code (tests may construct directly).
    """

    sha256: str
    cdf_method: CdfMethod
    correction_form: CorrectionForm
    linear_coefficients: tuple[float, float] | None
    month_offsets: Mapping[int, float]
    point_by_version: Mapping[str, EmosParams]
    draws_by_version: Mapping[str, tuple[EmosParams, ...]]

    def resolve(
        self, era: str, *, latitude_deg: float, climate_day: date,
    ) -> ResolvedCalibration:
        """Resolve ``era`` (``f"v{model_version}"``, "header wins" -- plan D2)
        to its location-corrected point estimate and bootstrap draws.

        Raises :class:`CalibrationArtefactUnknownVersionError` when ``era``
        is not a version this artefact carries parameters for -- NEVER
        silently falls back to a different version or pools across versions
        (finding F3).
        """
        point = self.point_by_version.get(era)
        draws = self.draws_by_version.get(era)
        if point is None or not draws:
            raise CalibrationArtefactUnknownVersionError(
                f"{era!r} is not a version this calibration artefact carries "
                f"parameters for ({sorted(self.point_by_version)!r})",
            )
        day_length_hours = daylight_hours(latitude_deg, climate_day)
        correction_f = correction_prediction_f(
            self.correction_form,
            month=climate_day.month,
            day_length_hours=day_length_hours,
            month_offsets=self.month_offsets,
            linear_coefficients=self.linear_coefficients,
        )
        corrected_point = EmosParams(
            a=point.a + correction_f, gamma=point.gamma, delta=point.delta,
        )
        corrected_draws = tuple(
            EmosParams(a=draw.a + correction_f, gamma=draw.gamma, delta=draw.delta)
            for draw in draws
        )
        return ResolvedCalibration(
            cdf_method=self.cdf_method,
            point=corrected_point,
            draws=corrected_draws,
            correction_f=correction_f,
        )


def _parse_payload(payload: Mapping[str, Any]) -> LiveCalibration:
    """Parses the already sha/fit-status/recalibration/correction-form
    checked ``payload`` into a :class:`LiveCalibration`.

    Every remaining field access is wrapped by the caller in a single
    ``try/except`` over ``(KeyError, ValueError, TypeError)`` (plan §3 S2
    item 8: a malformed artefact must fail CLOSED, never raise uncaught --
    this is what turns ``emos_params_from_draw_entry``'s plain ``ValueError``
    on a malformed draw entry, or a missing JSON key, into the SAME typed
    :class:`CalibrationArtefactPinMismatchError` every other schema
    violation here raises).
    """
    delta = float(payload["delta"])
    cdf_method = CdfMethod(payload["cdf_method"])
    correction_form = CorrectionForm(payload.get("correction_form", CorrectionForm.NONE.value))
    linear_coefficients_raw = payload.get("correction_linear_coefficients")
    if correction_form is CorrectionForm.LINEAR_DAYLENGTH:
        if linear_coefficients_raw is None:
            raise CalibrationArtefactPinMismatchError(
                "correction_form='linear_lst_day_length' needs "
                "correction_linear_coefficients, none were supplied",
            )
        linear_coefficients: tuple[float, float] | None = (
            float(linear_coefficients_raw[0]),
            float(linear_coefficients_raw[1]),
        )
    else:
        linear_coefficients = None
    month_offsets = {
        int(month): float(offset)
        for month, offset in payload.get("correction_month_offsets", {}).items()
    }
    emos_params_by_version = payload["emos_params_by_version"]
    emos_draws_by_version = payload["emos_draws_by_version"]
    if not emos_params_by_version or not emos_draws_by_version:
        raise CalibrationArtefactPinMismatchError(
            "artefact carries no per-version EMOS parameters or draws",
        )
    point_by_version: dict[str, EmosParams] = {}
    for version, (a, gamma) in emos_params_by_version.items():
        point_by_version[version] = EmosParams(a=float(a), gamma=float(gamma), delta=delta)
    draws_by_version: dict[str, tuple[EmosParams, ...]] = {}
    for version, entries in emos_draws_by_version.items():
        if not entries:
            raise CalibrationArtefactPinMismatchError(
                f"version {version!r} carries zero bootstrap draws",
            )
        draws_by_version[version] = tuple(
            emos_params_from_draw_entry(entry, fallback_delta=delta) for entry in entries
        )
    return LiveCalibration(
        sha256="",  # overwritten by the caller, which already knows actual_sha256
        cdf_method=cdf_method,
        correction_form=correction_form,
        linear_coefficients=linear_coefficients,
        month_offsets=month_offsets,
        point_by_version=point_by_version,
        draws_by_version=draws_by_version,
    )


def load_live_calibration(path: str, *, expected_sha256: str) -> LiveCalibration:
    """Read, hash-verify and parse the REAL ``NbpCalibrationArtefact`` JSON
    shape at ``path`` into the ONE live calibration consumer (plan §3 S2).

    Raises :class:`CalibrationArtefactPinMismatchError` for every fail-closed
    condition listed in the module docstring. Never raises an uncaught
    ``ValueError``/``KeyError``/``TypeError`` for a malformed-but-parseable
    payload -- every such failure is wrapped into the one typed error.
    """
    if expected_sha256 == _UNPINNED_SHA256:
        raise CalibrationArtefactPinMismatchError(
            "expected_sha256 is the unpinned all-zero placeholder; there is "
            "no live refitting (plan §2.2) -- a real manifest pin is required",
        )
    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} hashes to {actual_sha256!r}, "
            f"expected the manifest-pinned {expected_sha256!r}",
        )
    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} is not valid JSON: {exc}",
        ) from exc

    fit_status = str(payload.get("fit_status", _FIT_STATUS_UNKNOWN))
    if fit_status != _FIT_STATUS_OK:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} carries fit_status={fit_status!r}, "
            f"not {_FIT_STATUS_OK!r} -- refusing to trade off a calibration fit "
            "that did not converge, or never asserted convergence at all",
        )
    not_converged = sorted(
        version
        for version, converged in payload.get("converged_by_version", {}).items()
        if not converged
    )
    if not_converged:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} has non-converged versions "
            f"{not_converged!r} in converged_by_version",
        )
    recalibration = str(payload.get("recalibration", _SUPPORTED_RECALIBRATION))
    if recalibration != _SUPPORTED_RECALIBRATION:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} carries recalibration={recalibration!r}; "
            "the live path currently supports only 'none' and refuses "
            "unsupported probability transforms closed",
        )
    correction_form_str = str(payload.get("correction_form", CorrectionForm.NONE.value))
    if correction_form_str not in _SUPPORTED_CORRECTION_FORMS:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} carries correction_form="
            f"{correction_form_str!r}; the live path currently supports only "
            f"{sorted(_SUPPORTED_CORRECTION_FORMS)!r} and refuses unsupported "
            "location transforms closed",
        )

    try:
        live_calibration = _parse_payload(payload)
    except (KeyError, ValueError, TypeError) as exc:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} is malformed: {type(exc).__name__}: {exc}",
        ) from exc
    return LiveCalibration(
        sha256=actual_sha256,
        cdf_method=live_calibration.cdf_method,
        correction_form=live_calibration.correction_form,
        linear_coefficients=live_calibration.linear_coefficients,
        month_offsets=live_calibration.month_offsets,
        point_by_version=live_calibration.point_by_version,
        draws_by_version=live_calibration.draws_by_version,
    )
