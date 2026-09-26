"""RED-first suite for `persistence/family_manifest.py` (6f)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence import family_manifest as family_manifest_module
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestValidationError,
    UnpinnedBoundaryArtefactError,
    UnpinnedDensityArtefactError,
    UnregisteredFamilyManifestError,
    load_family_manifest,
)

#: WP-11b L-12 widen: real (non-zero) sha of the committed sentinel density
#: artefact -- `deploy/families/artefacts/not_applicable_density.json` --
#: shared by every non-forecast family manifest.
_SENTINEL_DENSITY_SHA = "247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65"

_VALID: dict[str, Any] = {
    "family_id": "pm_us_crh_v2",
    "venue": "polymarket_us",
    "trial_id_prefix": "current_rung_hold/trial/",
    "d0_climate_day": "2026-09-10",
    "taker_fee_coefficient": "0.06",
    "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v2.json",
    "boundary_inputs_sha256": "a" * 64,
    "composition_kind": "current_rung_hold",
    "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
    "density_artefact_sha256": _SENTINEL_DENSITY_SHA,
    "stations": ["LAX", "MDW", "MIA", "SFO"],
    "status": "REGISTERED",
}


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload))
    return path


def test_a_well_formed_registered_manifest_loads(tmp_path: Path) -> None:
    manifest: FamilyManifest = load_family_manifest(_write(tmp_path, _VALID))
    assert manifest.family_id == "pm_us_crh_v2"
    assert manifest.venue == "polymarket_us"
    assert manifest.trial_id_prefix == "current_rung_hold/trial/"
    assert manifest.d0_climate_day == "2026-09-10"
    assert manifest.boundary_artefact_path == Path(
        "deploy/families/gs_boundary_pm_us_crh_v2.json"
    )
    assert manifest.stations == ("LAX", "MDW", "MIA", "SFO")
    assert manifest.status == "REGISTERED"


def test_manifest_sha256_echoes_the_raw_file_bytes(tmp_path: Path) -> None:
    import hashlib

    path = _write(tmp_path, _VALID)
    manifest = load_family_manifest(path)
    assert manifest.manifest_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_bad_d0_climate_day_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, d0_climate_day="not-a-date")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_a_nonexistent_month_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, d0_climate_day="2026-13-40")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_an_unknown_key_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, extra_field="surprise")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_a_missing_required_key_is_refused(tmp_path: Path) -> None:
    payload = {k: v for k, v in _VALID.items() if k != "stations"}
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_empty_stations_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, stations=[])
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_a_malformed_sha_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, boundary_inputs_sha256="not-hex")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_a_wrong_typed_field_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, family_id=123)
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_invalid_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(path)


def test_a_bad_status_value_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, status="WHATEVER")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_draft_status_is_refused_without_allow_draft(tmp_path: Path) -> None:
    payload = dict(_VALID, status="DRAFT_NOT_REGISTERED")
    with pytest.raises(UnregisteredFamilyManifestError):
        load_family_manifest(_write(tmp_path, payload))


def test_draft_status_loads_with_allow_draft(tmp_path: Path) -> None:
    payload = dict(_VALID, status="DRAFT_NOT_REGISTERED")
    manifest = load_family_manifest(_write(tmp_path, payload), allow_draft=True)
    assert manifest.status == "DRAFT_NOT_REGISTERED"


def test_unpinned_sha_is_refused_without_allow_draft(tmp_path: Path) -> None:
    payload = dict(_VALID, boundary_inputs_sha256="0" * 64, status="DRAFT_NOT_REGISTERED")
    with pytest.raises((UnpinnedBoundaryArtefactError, UnregisteredFamilyManifestError)):
        load_family_manifest(_write(tmp_path, payload))


def test_unpinned_sha_specifically_refused_even_when_draft_is_allowed_is_still_flagged(
    tmp_path: Path,
) -> None:
    payload = dict(
        _VALID,
        boundary_inputs_sha256="0" * 64,
        status="REGISTERED",
    )
    with pytest.raises(UnpinnedBoundaryArtefactError):
        load_family_manifest(_write(tmp_path, payload))


def test_unpinned_sha_loads_with_allow_draft(tmp_path: Path) -> None:
    payload = dict(_VALID, boundary_inputs_sha256="0" * 64, status="DRAFT_NOT_REGISTERED")
    manifest = load_family_manifest(_write(tmp_path, payload), allow_draft=True)
    assert manifest.boundary_inputs_sha256 == "0" * 64


def test_the_three_committed_family_manifests_load_with_allow_draft() -> None:
    """Extended from two to three at `pm_us_crh_cont`'s registration
    (2026-09-11): a third committed family manifest now exists alongside
    `pm_us_crh_v2` and `kalshi_crh_v1`."""
    repo_root = Path(__file__).resolve().parents[2]
    pm = load_family_manifest(
        repo_root / "deploy/families/pm_us_crh_v2.json", allow_draft=True
    )
    kalshi = load_family_manifest(
        repo_root / "deploy/families/kalshi_crh_v1.json", allow_draft=True
    )
    cont = load_family_manifest(
        repo_root / "deploy/families/pm_us_crh_cont.json", allow_draft=True
    )
    assert pm.family_id == "pm_us_crh_v2"
    assert pm.venue == "polymarket_us"
    assert kalshi.family_id == "kalshi_crh_v1"
    assert kalshi.venue == "kalshi"
    assert kalshi.trial_id_prefix == "kalshi:current_rung_hold/trial/"
    assert cont.family_id == "pm_us_crh_cont"
    assert cont.venue == "polymarket_us"
    assert cont.trial_id_prefix == "continuous_rung_hold/trial/"
    assert pm.stations and kalshi.stations and cont.stations


def test_the_registered_cont_manifest_loads_without_allow_draft() -> None:
    """PREREG v3 registration (2026-09-11): `pm_us_crh_cont` flips to
    REGISTERED with D0 = 2026-09-12 (first UTC day strictly after the
    registration commit) and reuses v2's boundary artefact verbatim -- the
    manifest loads with NO `allow_draft` at all, and its
    `boundary_inputs_sha256` equals the reused artefact's own
    `inputs_sha256` exactly. Stations are v2's four, excluding NYC."""
    repo_root = Path(__file__).resolve().parents[2]
    artefact_payload = json.loads(
        (repo_root / "deploy/families/gs_boundary_pm_us_crh_v2.json").read_text()
    )
    cont = load_family_manifest(repo_root / "deploy/families/pm_us_crh_cont.json")
    assert cont.status == "REGISTERED"
    assert cont.d0_climate_day == "2026-09-12"
    assert cont.boundary_inputs_sha256 == artefact_payload["inputs_sha256"]
    assert cont.trial_id_prefix == "continuous_rung_hold/trial/"
    assert cont.stations == ("LAX", "MDW", "MIA", "SFO")


def test_exit_rule_absent_defaults_to_none(tmp_path: Path) -> None:
    manifest = load_family_manifest(_write(tmp_path, _VALID))
    assert manifest.exit_rule is None


def test_exit_rule_present_and_non_empty_is_accepted(tmp_path: Path) -> None:
    payload = dict(_VALID, exit_rule="hold_to_settlement")
    manifest = load_family_manifest(_write(tmp_path, payload))
    assert manifest.exit_rule == "hold_to_settlement"


def test_a_genuinely_unknown_key_is_still_refused_alongside_exit_rule(
    tmp_path: Path,
) -> None:
    payload = dict(_VALID, exit_rule="hold_to_settlement", extra_field="surprise")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_an_empty_string_exit_rule_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, exit_rule="")
    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(_write(tmp_path, payload))


def test_no_leg_exit_absent_defaults_to_false(tmp_path: Path) -> None:
    manifest = load_family_manifest(_write(tmp_path, _VALID))
    assert manifest.no_leg_exit is False


def test_no_leg_exit_true_is_accepted_when_exit_rule_present(tmp_path: Path) -> None:
    payload = dict(_VALID, exit_rule="hold_to_settlement", no_leg_exit=True)
    manifest = load_family_manifest(_write(tmp_path, payload))
    assert manifest.no_leg_exit is True


def test_no_leg_exit_true_without_exit_rule_is_refused(tmp_path: Path) -> None:
    payload = dict(_VALID, no_leg_exit=True)
    with pytest.raises(FamilyManifestValidationError, match="incoherent"):
        load_family_manifest(_write(tmp_path, payload))


@pytest.mark.parametrize("bad_value", [False, 1, "true", "True", 1.0])
def test_no_leg_exit_accepts_only_literal_true(tmp_path: Path, bad_value: object) -> None:
    payload = dict(_VALID, exit_rule="hold_to_settlement", no_leg_exit=bad_value)
    with pytest.raises(FamilyManifestValidationError, match="no_leg_exit"):
        load_family_manifest(_write(tmp_path, payload))


def test_dump_omits_no_leg_exit_when_false_and_round_trips_true(tmp_path: Path) -> None:
    from breezy.persistence.family_manifest import dump_family_manifest, write_family_manifest

    without = load_family_manifest(_write(tmp_path, _VALID))
    assert without.no_leg_exit is False
    assert "no_leg_exit" not in dump_family_manifest(without)

    draft = dict(_VALID, status="DRAFT_NOT_REGISTERED", exit_rule="hold_to_settlement")
    draft["no_leg_exit"] = True
    skeleton = load_family_manifest(_write(tmp_path, draft), allow_draft=True)
    assert skeleton.no_leg_exit is True
    assert dump_family_manifest(skeleton)["no_leg_exit"] is True

    once = write_family_manifest(tmp_path / "no_leg_exit_once.json", skeleton)
    pinned = replace(
        skeleton, manifest_sha256=hashlib.sha256(once.read_bytes()).hexdigest(),
    )
    reloaded = load_family_manifest(once, allow_draft=True)
    assert reloaded == pinned


def test_a_manifest_round_trips_through_the_serialiser(tmp_path: Path) -> None:
    """AUD-10b step 8: load(write(m), allow_draft=True) == m.

    `manifest_sha256` is the hash of the file bytes, not a JSON field, so
    the object under test is the one whose sha is the hash of what the
    serialiser itself writes.
    """
    from breezy.persistence.family_manifest import write_family_manifest

    draft = dict(_VALID, status="DRAFT_NOT_REGISTERED", exit_rule="hold_to_settlement")
    draft["terminal_climate_day"] = "2026-09-30"
    skeleton = load_family_manifest(_write(tmp_path, draft), allow_draft=True)
    once = write_family_manifest(tmp_path / "once.json", skeleton)
    pinned = replace(
        skeleton,
        manifest_sha256=hashlib.sha256(once.read_bytes()).hexdigest(),
    )
    twice = write_family_manifest(tmp_path / "twice.json", pinned)
    assert load_family_manifest(twice, allow_draft=True) == pinned
    assert twice.read_bytes() == once.read_bytes()


def test_a_required_key_absent_from_the_serialiser_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future `_REQUIRED_KEYS` member with no serialiser mapping raises,
    naming the key -- the serialiser is built from the key sets."""
    from breezy.persistence.family_manifest import dump_family_manifest

    skeleton = load_family_manifest(
        _write(tmp_path, dict(_VALID, status="DRAFT_NOT_REGISTERED")),
        allow_draft=True,
    )
    monkeypatch.setattr(
        family_manifest_module,
        "_REQUIRED_KEYS",
        family_manifest_module._REQUIRED_KEYS | frozenset({"brand_new_required_key"}),
    )
    with pytest.raises(FamilyManifestValidationError, match="brand_new_required_key"):
        dump_family_manifest(skeleton)
