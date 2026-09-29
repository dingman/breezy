"""load_calibration_artefact -- sha-pinned json only, never live-refit (SL-12)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

_VALID_PAYLOAD: dict[str, Any] = {
    "cdf_method": "normal",
    "emos": {"a": 0.0, "gamma": 0.0, "delta": 1.0},
    "p_lower_haircut": 0.03,
    "p_upper_haircut": 0.03,
}


def _write(tmp_path: Path, payload: dict[str, Any]) -> tuple[str, str]:
    path = tmp_path / "artefact.json"
    raw = json.dumps(payload).encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_a_matching_sha_loads_the_artefact(tmp_path: Path) -> None:
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
        load_calibration_artefact,
    )
    from breezy.strategy.ladder_ev.quantile_density import CdfMethod

    path, sha = _write(tmp_path, _VALID_PAYLOAD)

    artefact = load_calibration_artefact(path, expected_sha256=sha)

    assert artefact.sha256 == sha
    assert artefact.cdf_method is CdfMethod.NORMAL
    assert artefact.emos.a == 0.0
    assert artefact.emos.gamma == 0.0
    assert artefact.emos.delta == 1.0
    assert artefact.p_lower_haircut == 0.03
    assert artefact.p_upper_haircut == 0.03


def test_a_mismatched_sha_is_refused(tmp_path: Path) -> None:
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
        CalibrationArtefactPinMismatchError,
        load_calibration_artefact,
    )

    path, _real_sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_calibration_artefact(path, expected_sha256="a" * 64)


def test_an_unpinned_all_zero_expected_sha_is_refused(tmp_path: Path) -> None:
    from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
        CalibrationArtefactPinMismatchError,
        load_calibration_artefact,
    )

    path, _sha = _write(tmp_path, _VALID_PAYLOAD)

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_calibration_artefact(path, expected_sha256="0" * 64)
