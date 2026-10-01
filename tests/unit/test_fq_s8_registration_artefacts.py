"""FQ-S8 RED suite -- registration artefacts (plan
`FQ_GO_LIVE_PLAN_2026-10-01.md` D5, S8): the committed byte-copy of the
selected calibration candidate, the sentinel boundary artefact, and the
REGISTERED `pm_us_crh_fq_v1.json` manifest carrying `live_orders_ruling`.

Scope note (parallel-build): S2 (the live calibration consumer rewrite that
reads the real `NbpCalibrationArtefact` JSON shape) is NOT in this
worktree's base. These tests therefore pin BYTES and SHAS and drive the
S5 manifest/gate contracts only -- they never ask the OLD
`calibration_artefact.load_calibration_artefact` to parse the real
artefact's body (it still expects a flat ``emos`` key the real artefact
does not have, plan finding F1, and would raise a bare ``KeyError``). The
one place this suite DOES call that loader is the tamper test, where the
sha check raises before any parsing is attempted.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence.family_manifest import load_family_manifest
from breezy.persistence.gs_boundary_artefact import (
    BoundaryArtefactError,
    load_boundary_artefact,
)
from breezy.persistence.live_orders_gate import live_orders_authorized
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactPinMismatchError,
    load_calibration_artefact,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "deploy" / "families" / "pm_us_crh_fq_v1.json"
_CALIBRATION_ARTEFACT_PATH = (
    _REPO_ROOT
    / "deploy"
    / "families"
    / "artefacts"
    / "nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
)
_BOUNDARY_SENTINEL_PATH = (
    _REPO_ROOT / "deploy" / "families" / "artefacts" / "not_applicable_boundary.json"
)
_PINNED_CALIBRATION_SHA256 = (
    "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
)
_RULING_ID = "RULING_operator_fq_live_real_orders_2026-10-01"


# ---------------------------------------------------------------------------
# The committed byte copy -- exact sha, byte-for-byte identical to source
# ---------------------------------------------------------------------------


def test_calibration_artefact_byte_copy_matches_the_pinned_sha256() -> None:
    assert _CALIBRATION_ARTEFACT_PATH.exists()
    actual = hashlib.sha256(_CALIBRATION_ARTEFACT_PATH.read_bytes()).hexdigest()
    assert actual == _PINNED_CALIBRATION_SHA256


def test_calibration_artefact_byte_copy_is_byte_identical_to_the_source_artefact() -> None:
    """Never re-serialized -- the copy's raw bytes equal the original
    candidate's raw bytes, not merely an equivalent JSON re-dump."""
    source = Path(
        "~/.local/share/breezy/derived/nbp_calibration/nbp_validate_candidate_2026-09-30.json"
    ).expanduser()
    if not source.exists():  # pragma: no cover - operator-machine-only fixture
        pytest.skip("source candidate artefact not present on this machine")
    assert _CALIBRATION_ARTEFACT_PATH.read_bytes() == source.read_bytes()


# ---------------------------------------------------------------------------
# The manifest loads REGISTERED, with every D5 field, without allow_draft
# ---------------------------------------------------------------------------


def test_the_registered_manifest_loads_without_allow_draft() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)

    assert manifest.status == "REGISTERED"
    assert manifest.family_id == "pm_us_crh_fq_v1"
    assert manifest.composition_kind == "forecast_quantile_ladder"
    assert manifest.venue == "polymarket_us"
    assert manifest.stations == ("LAX", "MDW", "MIA", "SFO")
    assert manifest.taker_fee_coefficient == Decimal("0.0695")
    assert manifest.live_orders_ruling == _RULING_ID
    assert manifest.exit_rule is None


def test_the_manifest_density_sha_pin_matches_the_committed_artefact_bytes() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)
    assert manifest.density_artefact_path == Path(
        "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
    )
    actual = hashlib.sha256((_REPO_ROOT / manifest.density_artefact_path).read_bytes()).hexdigest()
    assert actual == manifest.density_artefact_sha256 == _PINNED_CALIBRATION_SHA256


def test_the_manifest_boundary_sha_pin_matches_the_committed_sentinel_bytes() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)
    assert manifest.boundary_artefact_path == Path(
        "deploy/families/artefacts/not_applicable_boundary.json"
    )
    actual = hashlib.sha256(
        (_REPO_ROOT / manifest.boundary_artefact_path).read_bytes()
    ).hexdigest()
    assert actual == manifest.boundary_inputs_sha256


# ---------------------------------------------------------------------------
# The S5 gate authorises against the real, committed ruling
# ---------------------------------------------------------------------------


def test_live_orders_gate_authorises_the_committed_manifest_and_ruling() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)

    decision = live_orders_authorized(manifest, _REPO_ROOT, permit_present=True)

    assert decision.enabled is True
    assert decision.reason == "ok"


def test_live_orders_gate_stays_shadow_with_no_permit() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)

    decision = live_orders_authorized(manifest, _REPO_ROOT, permit_present=False)

    assert decision.enabled is False
    assert decision.reason == "permit_absent"


# ---------------------------------------------------------------------------
# A tampered artefact byte refuses -- sha check fires before any parsing
# (never routed through the still-broken, pre-S2 emos parser)
# ---------------------------------------------------------------------------


def test_a_tampered_calibration_artefact_byte_refuses_the_sha_pin(tmp_path: Path) -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(_CALIBRATION_ARTEFACT_PATH.read_bytes() + b"\n")

    with pytest.raises(CalibrationArtefactPinMismatchError):
        load_calibration_artefact(str(tampered), expected_sha256=manifest.density_artefact_sha256)


def test_the_untampered_byte_copy_passes_its_own_sha_check(tmp_path: Path) -> None:
    """Control for the tamper test above: the SAME loader call, same pin,
    unmodified bytes, raises nothing at the sha-check stage. (It is not
    asserted to return successfully here -- the old loader's `payload["emos"]`
    parse still fails on the real artefact's actual schema, plan finding F1,
    fixed by S2, not this slice.)"""
    manifest = load_family_manifest(_MANIFEST_PATH)
    try:
        load_calibration_artefact(
            str(_CALIBRATION_ARTEFACT_PATH), expected_sha256=manifest.density_artefact_sha256
        )
    except CalibrationArtefactPinMismatchError:
        pytest.fail("the untampered, correctly-pinned byte copy must pass its own sha check")
    except KeyError as exc:
        assert str(exc) == "'emos'", (
            "expected the KNOWN, pre-S2 F1 failure mode (missing flat 'emos' key) "
            f"past a clean sha check -- got a different KeyError: {exc!r}"
        )


# ---------------------------------------------------------------------------
# The boundary sentinel refuses any family_tally_v2-style load (D4)
# ---------------------------------------------------------------------------


def test_family_tally_v2_boundary_load_on_the_sentinel_refuses() -> None:
    manifest = load_family_manifest(_MANIFEST_PATH)

    with pytest.raises(BoundaryArtefactError):
        load_boundary_artefact(
            _REPO_ROOT / manifest.boundary_artefact_path,
            expected_sha256=manifest.boundary_inputs_sha256,
        )
