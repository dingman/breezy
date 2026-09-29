"""``ArtefactBoundsProvider``/``load_bounds_artefact_draws`` (SL-13) --
the real ``BoundsProvider`` implementation ``bounds.py`` names as a seam.

Same sha-pin discipline as ``test_calibration_artefact.py`` (SL-12), applied
to the richer ``NbpCalibrationArtefact``-shaped JSON
(``breezy.analysis.nbp_calibration.write_artefact``): ``delta`` +
``emos_draws_by_version``, never the flat ``{"emos": {...}}`` shape.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.strategy.forecast_quantile_ladder.artefact_bounds import (
    ArtefactBoundsProvider,
    BoundsArtefactPinMismatchError,
    BoundsNotReadyError,
    load_bounds_artefact_draws,
)
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, Percentiles, Rung

_LADDER = (
    Rung("lt", None, 79),
    Rung("i0", 80, 81),
    Rung("gte", 82, None),
)

_VALID_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "cdf_method": "normal",
    "recalibration": "emos",
    "correction_form": "additive",
    "delta": 1.0,
    "kappa": 1.0,
    "emos_params_by_version": {"v1": [0.0, 0.0]},
    "emos_draws_by_version": {
        "v1": [[0.0, 0.0], [0.1, 0.05], [-0.1, -0.02]],
    },
    "n_min": 30,
    "sigma_d": 1.0,
    "rung_probability_bounds": {},
    "fit_status": "OK",
}


def _write(tmp_path: Path, payload: dict[str, Any]) -> tuple[str, str]:
    path = tmp_path / "bounds_artefact.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_a_matching_sha_reconstructs_every_pooled_draw(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)

    result = load_bounds_artefact_draws(path, expected_sha256=sha)

    assert result.cdf_method is CdfMethod.NORMAL
    assert len(result.draws) == 3
    assert {(d.a, d.gamma, d.delta) for d in result.draws} == {
        (0.0, 0.0, 1.0),
        (0.1, 0.05, 1.0),
        (-0.1, -0.02, 1.0),
    }


def test_a_mismatched_sha_is_refused(tmp_path: Path) -> None:
    path, _real_sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(BoundsArtefactPinMismatchError):
        load_bounds_artefact_draws(path, expected_sha256="a" * 64)


def test_an_unpinned_all_zero_expected_sha_is_refused(tmp_path: Path) -> None:
    path, _sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(BoundsArtefactPinMismatchError):
        load_bounds_artefact_draws(path, expected_sha256="0" * 64)


def test_zero_draws_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID_PAYLOAD, emos_draws_by_version={"v1": []})
    path, sha = _write(tmp_path, payload)

    with pytest.raises(BoundsArtefactPinMismatchError):
        load_bounds_artefact_draws(path, expected_sha256=sha)


def test_a_non_converged_fit_status_is_refused(tmp_path: Path) -> None:
    """SL-8b2: a `NbpCalibrationArtefact` whose fit never converged must
    fail this loader closed, exactly like a bad sha pin -- never silently
    hand the live strategy bootstrap draws from an unconverged fit."""
    payload = dict(_VALID_PAYLOAD, fit_status="FIT_NOT_CONVERGED")
    path, sha = _write(tmp_path, payload)

    with pytest.raises(BoundsArtefactPinMismatchError):
        load_bounds_artefact_draws(path, expected_sha256=sha)


def test_a_missing_fit_status_key_is_refused_as_unknown(tmp_path: Path) -> None:
    """SL-8b2: an artefact that never asserted convergence at all (no
    `fit_status` key) must fail closed as UNKNOWN, never fall back to
    "assume converged" -- there is no production artefact predating this
    schema to stay compatible with."""
    payload = {key: value for key, value in _VALID_PAYLOAD.items() if key != "fit_status"}
    path, sha = _write(tmp_path, payload)

    with pytest.raises(BoundsArtefactPinMismatchError):
        load_bounds_artefact_draws(path, expected_sha256=sha)


def test_provider_returns_rung_bounds_from_percentiles(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    draws = load_bounds_artefact_draws(path, expected_sha256=sha)
    percentiles = Percentiles(q10=76, q25=78, q50=80, q75=82, q90=84, mean=80, sd=3)
    provider = ArtefactBoundsProvider(
        cdf_method=draws.cdf_method, draws=draws.draws, percentiles_fn=lambda: percentiles,
    )

    bounds = provider(cdf=lambda x: 0.5, ladder=_LADDER, rung_id="i0")

    assert 0.0 <= bounds.p_lower <= bounds.p_hat <= bounds.p_upper <= 1.0


def test_provider_raises_when_percentiles_fn_returns_none(tmp_path: Path) -> None:
    path, sha = _write(tmp_path, _VALID_PAYLOAD)
    draws = load_bounds_artefact_draws(path, expected_sha256=sha)
    provider = ArtefactBoundsProvider(
        cdf_method=draws.cdf_method, draws=draws.draws, percentiles_fn=lambda: None,
    )

    with pytest.raises(BoundsNotReadyError):
        provider(cdf=lambda x: 0.5, ladder=_LADDER, rung_id="i0")


def test_provider_construction_refuses_zero_draws() -> None:
    with pytest.raises(ValueError, match="at least one draw"):
        ArtefactBoundsProvider(
            cdf_method=CdfMethod.NORMAL, draws=(), percentiles_fn=lambda: None,
        )
