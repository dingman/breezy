"""RED-first suite for `persistence/exit_gate.py` (INC-1, extended INC-E1).

`_EXIT_RULE_REGISTERED_FAMILIES` now names exactly one family,
`pm_us_crh_exit_v4` (PREREG v4, `docs/plans/
POSITION_EXIT_EXECUTION_2026-09-16.md` §2). Membership alone still grants
nothing: every family manifest currently committed to the repo -- including
`pm_us_crh_exit_v4`'s own DRAFT manifest, which ships with no `exit_rule`
key at INC-E1 -- must gate False until its manifest actually declares
`exit_rule`, and `pm_us_crh_cont` (the live hold-to-settlement family) must
gate False even if its manifest were hypothetically edited to declare one,
because it is not, and must never become, a member of the frozenset.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.persistence.exit_gate import (
    _EXIT_RULE_REGISTERED_FAMILIES,
    family_declares_exit_rule,
)
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.strategy.current_rung_hold.trial_day_latch import CONTINUOUS_TRIAL_KEY_PREFIX

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"

# Committed family manifests, enumerated explicitly (mirrors
# `test_family_manifest.py::test_the_three_committed_family_manifests_load_with_allow_draft`)
# rather than a bare `*.json` glob: `deploy/families/` also holds
# `gs_boundary_*.json` boundary-artefact sidecars, which are NOT manifests
# and do not share the manifest schema.
_COMMITTED_MANIFEST_NAMES: tuple[str, ...] = (
    "pm_us_crh_v2.json",
    "pm_us_crh_cont.json",
    "kalshi_crh_v1.json",
    "pm_us_crh_exit_v4.json",
    # WP-THETA: the family registered at the 2026-09-17 taker basis
    # (0.0695). It declares no `exit_rule` either, so the gate stays closed
    # for it exactly as for every sibling above.
    "pm_us_crh_v4.json",
    # SL-13 (2026-09-29): the forecast_quantile_ladder family. Shadow-only,
    # status DRAFT_NOT_REGISTERED, `family_id` absent from
    # `_EXIT_RULE_REGISTERED_FAMILIES`, and the manifest declares neither
    # `exit_rule` nor `no_leg_exit` -- it satisfies both invariants below
    # exactly like every other committed manifest.
    "pm_us_crh_fq_v1.json",
)


def _committed_manifest_paths() -> tuple[Path, ...]:
    paths = tuple(_FAMILIES_DIR / name for name in _COMMITTED_MANIFEST_NAMES)
    for path in paths:
        assert path.is_file(), f"expected committed family manifest at {path}"
    # Cross-check: every JSON file in the directory that actually parses as a
    # family manifest (carries `trial_id_prefix`) must be one of the ones
    # enumerated above -- a new manifest landing without a matching test
    # update must fail loudly here, not slip past silently.
    for candidate in sorted(_FAMILIES_DIR.glob("*.json")):
        payload_text = candidate.read_text(encoding="utf-8")
        if '"trial_id_prefix"' in payload_text:
            assert candidate in paths, (
                f"{candidate} looks like a family manifest but is not enumerated "
                "in _COMMITTED_MANIFEST_NAMES"
            )
    return paths


def _load_any(path: Path) -> FamilyManifest:
    try:
        return load_family_manifest(path)
    except Exception:  # noqa: BLE001 -- draft/unpinned manifests retry with the flag
        return load_family_manifest(path, allow_draft=True)


def test_the_registered_families_frozenset_names_exactly_pm_us_crh_exit_v4() -> None:
    assert isinstance(_EXIT_RULE_REGISTERED_FAMILIES, frozenset)
    assert _EXIT_RULE_REGISTERED_FAMILIES == frozenset({"pm_us_crh_exit_v4"})


def test_every_committed_family_manifest_gates_false_and_carries_no_exit_rule() -> None:
    """True for every committed manifest today, `pm_us_crh_exit_v4`'s DRAFT
    manifest included: code-registration alone never suffices (module
    docstring) -- the manifest must ALSO declare `exit_rule`, which none do
    yet."""
    paths = _committed_manifest_paths()
    for path in paths:
        manifest = _load_any(path)
        assert manifest.exit_rule is None, f"{path}: unexpected exit_rule {manifest.exit_rule!r}"
        assert family_declares_exit_rule(manifest) is False, f"{path}: gate must be False today"


def test_pm_us_crh_exit_v4_gates_true_only_once_its_manifest_declares_exit_rule() -> None:
    """The registered family gates False while its manifest omits
    `exit_rule` (today's committed state) and True once a manifest for that
    SAME family_id declares one -- the second, independent half of the gate
    (module docstring)."""
    without_exit_rule = FamilyManifest(
        family_id="pm_us_crh_exit_v4",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold_exit_v4/trial/",
        d0_climate_day="2099-01-01",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="DRAFT_NOT_REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=None,
    )
    assert family_declares_exit_rule(without_exit_rule) is False

    with_exit_rule = FamilyManifest(
        family_id="pm_us_crh_exit_v4",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold_exit_v4/trial/",
        d0_climate_day="2099-01-01",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED",
        manifest_sha256="c" * 64,
        exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
    )
    assert family_declares_exit_rule(with_exit_rule) is True


def test_pm_us_crh_cont_can_never_gate_true_even_if_its_manifest_declared_exit_rule() -> None:
    """`pm_us_crh_cont` is not, and must never become, a member of
    `_EXIT_RULE_REGISTERED_FAMILIES` -- a change to the ACTION is a new
    family (PREREG v4, L-34), never an amendment of the live hold-to-
    settlement family. Simulates the hypothetical bad edit (a manifest JSON
    declaring `exit_rule` for `pm_us_crh_cont`) to prove code registration,
    not the manifest, is the deciding half."""
    hypothetically_amended = FamilyManifest(
        family_id="pm_us_crh_cont",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="continuous_rung_hold/trial/",
        d0_climate_day="2026-09-12",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("LAX", "MDW", "MIA", "SFO"),
        status="REGISTERED",
        manifest_sha256="d" * 64,
        exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
    )
    assert family_declares_exit_rule(hypothetically_amended) is False
    assert "pm_us_crh_cont" not in _EXIT_RULE_REGISTERED_FAMILIES


def test_a_manifest_with_exit_rule_not_in_the_frozenset_gates_false(tmp_path: Path) -> None:
    manifest = FamilyManifest(
        family_id="not_registered_family",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="not_registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=tmp_path / "boundary.json",
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule="hold_to_settlement",
    )
    assert family_declares_exit_rule(manifest) is False


def test_a_manifest_in_a_monkeypatched_frozenset_but_exit_rule_none_gates_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import breezy.persistence.exit_gate as exit_gate_module

    monkeypatch.setattr(
        exit_gate_module, "_EXIT_RULE_REGISTERED_FAMILIES", frozenset({"registered_family"})
    )
    manifest = FamilyManifest(
        family_id="registered_family",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=Path("deploy/families/does_not_matter.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=None,
    )
    assert exit_gate_module.family_declares_exit_rule(manifest) is False


def test_a_manifest_both_registered_and_declaring_exit_rule_gates_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import breezy.persistence.exit_gate as exit_gate_module

    monkeypatch.setattr(
        exit_gate_module, "_EXIT_RULE_REGISTERED_FAMILIES", frozenset({"registered_family"})
    )
    manifest = FamilyManifest(
        family_id="registered_family",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=Path("deploy/families/does_not_matter.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule="hold_to_settlement",
    )
    assert exit_gate_module.family_declares_exit_rule(manifest) is True


# ---------------------------------------------------------------------------
# FU-1d: the NO-leg exit-declaration gate (RULING_FU-1b_no_leg_marks_
# 2026-09-26.md item 2).
# ---------------------------------------------------------------------------


def test_every_committed_manifest_loads_unchanged_and_declares_no_no_leg_exit() -> None:
    """AC4: every committed manifest loads with NO change to its bytes or
    `manifest_sha256`, and none of them declares `no_leg_exit` today."""
    for path in _committed_manifest_paths():
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = _load_any(path)
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert before == after, f"{path}: bytes changed by loading"
        assert manifest.manifest_sha256 == before
        assert manifest.no_leg_exit is False


def test_family_declares_no_leg_exit_requires_the_exit_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`family_declares_no_leg_exit` can only ever ADD a restriction on top
    of `family_declares_exit_rule` -- never grant one independently."""
    import breezy.persistence.exit_gate as exit_gate_module

    monkeypatch.setattr(
        exit_gate_module, "_EXIT_RULE_REGISTERED_FAMILIES", frozenset({"registered_family"}),
    )

    def _manifest(*, family_id: str, exit_rule: str | None, no_leg_exit: bool) -> FamilyManifest:
        return FamilyManifest(
            family_id=family_id,
            venue="polymarket_us",
            taker_fee_coefficient=Decimal("0.06"),
            trial_id_prefix="registered/trial/",
            d0_climate_day="2026-09-15",
            boundary_artefact_path=Path("deploy/families/does_not_matter.json"),
            boundary_inputs_sha256="a" * 64,
            composition_kind="continuous_rung_hold",
            density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
            density_artefact_sha256=(
                "247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65"
            ),
            stations=("SFO",),
            status="REGISTERED",
            manifest_sha256="b" * 64,
            exit_rule=exit_rule,
            no_leg_exit=no_leg_exit,
        )

    # Registered + exit_rule + no_leg_exit=True -> True (both halves present).
    assert (
        exit_gate_module.family_declares_no_leg_exit(
            _manifest(family_id="registered_family", exit_rule="rule", no_leg_exit=True)
        )
        is True
    )
    # Registered + exit_rule but no_leg_exit=False -> False.
    assert (
        exit_gate_module.family_declares_no_leg_exit(
            _manifest(family_id="registered_family", exit_rule="rule", no_leg_exit=False)
        )
        is False
    )
    # no_leg_exit=True but the family is NOT code-registered -> False: the
    # family gate is not bypassable by the narrower one.
    assert (
        exit_gate_module.family_declares_no_leg_exit(
            _manifest(family_id="unregistered_family", exit_rule="rule", no_leg_exit=True)
        )
        is False
    )


def test_live_composition_still_resolves_pm_us_crh_cont_not_the_draft_exit_family() -> None:
    """`composition.py`'s live trial-key wiring (`CONTINUOUS_TRIAL_KEY_PREFIX`)
    still mints trial ids under `pm_us_crh_cont`'s own registered
    `trial_id_prefix` -- adding `pm_us_crh_exit_v4` to the gate's frozenset
    (INC-E1) selects no live family and rewires nothing; that requires its
    own manifest to flip to REGISTERED with a real `exit_rule` (INC-E4)."""
    cont = load_family_manifest(_FAMILIES_DIR / "pm_us_crh_cont.json")
    assert CONTINUOUS_TRIAL_KEY_PREFIX == cont.trial_id_prefix

    draft_v4 = load_family_manifest(
        _FAMILIES_DIR / "pm_us_crh_exit_v4.json", allow_draft=True
    )
    assert draft_v4.trial_id_prefix != CONTINUOUS_TRIAL_KEY_PREFIX
