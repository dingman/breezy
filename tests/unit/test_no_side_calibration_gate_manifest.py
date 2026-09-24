"""AUD-01a: the NO-side calibration flag is not a family-manifest field.

Two pins, both against the real schema and the real loader. Neither needs
production code: the key is absent from the closed key sets, and
``load_family_manifest`` already refuses an unknown key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from breezy.persistence import family_manifest
from breezy.persistence.family_manifest import (
    FamilyManifestValidationError,
    load_family_manifest,
)

_FLAG = "no_side_calibration_gate_cleared"
_V4 = Path("deploy/families/pm_us_crh_v4.json")


def test_calibration_gate_flag_is_not_a_manifest_schema_key() -> None:
    assert _FLAG not in (family_manifest._REQUIRED_KEYS | family_manifest._OPTIONAL_KEYS)


def test_injected_calibration_gate_flag_is_refused_as_an_unknown_key(
    tmp_path: Path,
) -> None:
    payload = json.loads(_V4.read_text(encoding="utf-8"))
    assert _FLAG not in payload
    payload[_FLAG] = True
    path = tmp_path / "pm_us_crh_v4.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FamilyManifestValidationError, match=r"unknown key\(s\)"):
        load_family_manifest(path)
