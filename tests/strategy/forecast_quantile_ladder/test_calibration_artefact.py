"""``load_live_calibration``/``LiveCalibration`` -- the REAL
``NbpCalibrationArtefact`` schema, per-version resolution, shared location
correction (SL-13 S2, plan §3 S2, findings F1-F4).

``_VALID_PAYLOAD`` mirrors the REAL registered artefact's own shape
(``~/.local/share/breezy/derived/nbp_calibration/
nbp_validate_candidate_2026-09-30.json``, sha ``9c0b6d6e...923a5e``):
``schema_version`` 1, per-version ``emos_params_by_version``/
``emos_draws_by_version`` (3-element ``[a, gamma, delta]`` bootstrap draws),
``correction_form="linear_lst_day_length"`` with real coefficients.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactPinMismatchError,
    CalibrationArtefactUnknownVersionError,
    LiveCalibration,
    ResolvedCalibration,
    load_live_calibration,
)
from breezy.strategy.ladder_ev.location_correction import CorrectionForm, daylight_hours
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams

_VALID_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "cdf_method": "normal",
    "recalibration": "none",
    "correction_form": "linear_lst_day_length",
    "correction_linear_coefficients": [-0.39835, 4.28148],
    "correction_month_offsets": {},
    "delta": 0.786448728097906,
    "kappa": "inf",
    "emos_params_by_version": {
        "v4.1": [0.29046801995079374, 0.2306389050479541],
        "v5.0": [0.6031095921945016, 0.24584481041901185],
    },
    "emos_draws_by_version": {
        "v4.1": [
            [0.29046801995079374, 0.2306389050479541, 0.786448728097906],
            [0.30, 0.231, 0.79],
        ],
        "v5.0": [
            [0.6031095921945016, 0.24584481041901185, 0.786448728097906],
            [0.61, 0.246, 0.80],
        ],
    },
    "n_min": 592,
    "sigma_d": 0.13195862875714462,
    "rung_probability_bounds": {},
    "converged_by_version": {"v4.1": True, "v5.0": True},
    "fit_status": "OK",
}

_KMIA_LAT = 25.7617
_DAY = date(2026, 10, 1)


def _write(tmp_path: Path, payload: dict[str, Any]) -> tuple[str, str]:
    path = tmp_path / "nbp_calibration_candidate.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# RED 1: accepts the real artefact's own schema (currently a KeyError 'emos')
# ---------------------------------------------------------------------------


def test_live_loader_accepts_the_committed_registered_artefact(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)

    calibration = load_live_calibration(path, expected_sha256=sha)

    assert isinstance(calibration, LiveCalibration)
    assert calibration.sha256 == sha
    assert calibration.cdf_method is CdfMethod.NORMAL
    assert calibration.correction_form is CorrectionForm.LINEAR_DAYLENGTH


# ---------------------------------------------------------------------------
# RED 2: 3-element bootstrap draws keep their own delta
# ---------------------------------------------------------------------------


def test_three_element_draws_keep_their_own_delta(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    calibration = load_live_calibration(path, expected_sha256=sha)

    draws = calibration.draws_by_version["v5.0"]

    assert {d.delta for d in draws} == {0.786448728097906, 0.80}
    assert draws[1].a == pytest.approx(0.61)
    assert draws[1].gamma == pytest.approx(0.246)


def test_two_element_draws_fall_back_to_the_top_level_delta(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD)
    payload["emos_draws_by_version"] = dict(payload["emos_draws_by_version"])
    payload["emos_draws_by_version"]["v5.0"] = [[0.6, 0.25]]
    path, sha = _write(tmp_path, payload)

    calibration = load_live_calibration(path, expected_sha256=sha)

    draws = calibration.draws_by_version["v5.0"]
    assert draws[0].delta == payload["delta"]


# ---------------------------------------------------------------------------
# RED 3: draws are never pooled across versions
# ---------------------------------------------------------------------------


def test_draws_are_never_pooled_across_versions(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    calibration = load_live_calibration(path, expected_sha256=sha)

    v41_draws = calibration.draws_by_version["v4.1"]
    v50_draws = calibration.draws_by_version["v5.0"]

    assert len(v41_draws) == 2
    assert len(v50_draws) == 2
    assert {d.a for d in v41_draws}.isdisjoint({d.a for d in v50_draws})


# ---------------------------------------------------------------------------
# RED 4: an unknown model version refuses closed, typed
# ---------------------------------------------------------------------------


def test_unknown_model_version_refuses_closed(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    calibration = load_live_calibration(path, expected_sha256=sha)

    with pytest.raises(CalibrationArtefactUnknownVersionError):
        calibration.resolve("v3.2", latitude_deg=_KMIA_LAT, climate_day=_DAY)


# ---------------------------------------------------------------------------
# RED 5: a month_offset form is refused live (closed set is {none, linear})
# ---------------------------------------------------------------------------


def test_month_offset_form_is_refused_live(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, correction_form="month_offset")
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="correction_form"):
        load_live_calibration(path, expected_sha256=sha)


# ---------------------------------------------------------------------------
# RED 6: not-converged / bad-recalibration / missing-coefficient refusals
# ---------------------------------------------------------------------------


def test_a_non_ok_fit_status_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, fit_status="FIT_NOT_CONVERGED")
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="fit_status"):
        load_live_calibration(path, expected_sha256=sha)


def test_a_missing_fit_status_key_is_refused_as_unknown(tmp_path: Path) -> None:
    payload = {key: value for key, value in _VALID_PAYLOAD.items() if key != "fit_status"}
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="fit_status"):
        load_live_calibration(path, expected_sha256=sha)


def test_a_non_converged_version_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, converged_by_version={"v4.1": True, "v5.0": False})
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="v5.0"):
        load_live_calibration(path, expected_sha256=sha)


def test_unsupported_probability_recalibration_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, recalibration="affine")
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="recalibration"):
        load_live_calibration(path, expected_sha256=sha)


def test_linear_form_missing_coefficients_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, correction_linear_coefficients=None)
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="correction_linear_coefficients"):
        load_live_calibration(path, expected_sha256=sha)


def test_a_version_with_zero_draws_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD)
    payload["emos_draws_by_version"] = dict(payload["emos_draws_by_version"])
    payload["emos_draws_by_version"]["v5.0"] = []
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError, match="zero"):
        load_live_calibration(path, expected_sha256=sha)


# ---------------------------------------------------------------------------
# Sha pin discipline (unchanged invariant)
# ---------------------------------------------------------------------------


def test_a_mismatched_sha_is_refused(tmp_path: Path) -> None:
    path, _real_sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_live_calibration(path, expected_sha256="a" * 64)


def test_an_unpinned_all_zero_expected_sha_is_refused(tmp_path: Path) -> None:
    path, _sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_live_calibration(path, expected_sha256="0" * 64)


# ---------------------------------------------------------------------------
# RED 8: a malformed artefact gives a typed refusal, never an uncaught crash
# ---------------------------------------------------------------------------


def test_a_malformed_draw_entry_refuses_closed_never_crashes(tmp_path: Path) -> None:
    """A draw entry with the wrong element count would otherwise raise a
    plain, uncaught ``ValueError`` from ``emos_params_from_draw_entry``."""
    payload = dict(_VALID_PAYLOAD)
    payload["emos_draws_by_version"] = dict(payload["emos_draws_by_version"])
    payload["emos_draws_by_version"]["v5.0"] = [[0.1]]
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_live_calibration(path, expected_sha256=sha)


def test_a_missing_schema_key_refuses_closed_never_crashes(tmp_path: Path) -> None:
    payload = {
        key: value for key, value in _VALID_PAYLOAD.items() if key != "emos_params_by_version"
    }
    path, sha = _write(tmp_path, payload)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_live_calibration(path, expected_sha256=sha)


def test_invalid_json_refuses_closed_never_crashes(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    raw = b"{not valid json"
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_live_calibration(str(path), expected_sha256=sha)


# ---------------------------------------------------------------------------
# resolve(): correction applied identically to the point and every draw
# ---------------------------------------------------------------------------


def test_resolve_applies_the_same_correction_to_point_and_every_draw(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    calibration = load_live_calibration(path, expected_sha256=sha)

    resolved = calibration.resolve("v5.0", latitude_deg=_KMIA_LAT, climate_day=_DAY)

    day_length_hours = daylight_hours(_KMIA_LAT, _DAY)
    slope, intercept = _VALID_PAYLOAD["correction_linear_coefficients"]
    expected_c = slope * day_length_hours + intercept
    assert resolved.correction_f == pytest.approx(expected_c)

    raw_point_a, raw_point_gamma = _VALID_PAYLOAD["emos_params_by_version"]["v5.0"]
    raw_point = EmosParams(a=raw_point_a, gamma=raw_point_gamma, delta=_VALID_PAYLOAD["delta"])
    assert resolved.point.a == pytest.approx(raw_point.a + expected_c)
    assert resolved.point.gamma == pytest.approx(raw_point.gamma)
    assert resolved.point.delta == pytest.approx(raw_point.delta)

    raw_draws = [
        EmosParams(a, gamma, delta)
        for a, gamma, delta in _VALID_PAYLOAD["emos_draws_by_version"]["v5.0"]
    ]
    for resolved_draw, raw_draw in zip(resolved.draws, raw_draws):
        assert resolved_draw.a == pytest.approx(raw_draw.a + expected_c)
        assert resolved_draw.gamma == pytest.approx(raw_draw.gamma)
        assert resolved_draw.delta == pytest.approx(raw_draw.delta)


def test_live_and_resolved_calibration_name_no_haircut_field() -> None:
    """Bounds are a bootstrap percentile interval. No field may reintroduce a haircut."""
    for cls in (LiveCalibration, ResolvedCalibration):
        named = [item.name for item in fields(cls) if "haircut" in item.name]
        assert named == []
