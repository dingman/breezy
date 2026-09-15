"""RED-first suite for `persistence/exit_gate.py` (INC-1).

Today NO family may exit (hold-to-settlement is the registered action,
PREREG v3): the registered-families frozenset is empty, and every family
manifest currently committed to the repo -- including drafts -- must gate
False. A manifest's own `exit_rule` field can never flip the gate alone;
only membership in the module's own frozenset, set here in code (never by
editing a JSON file), can.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.persistence.exit_gate import (
    _EXIT_RULE_REGISTERED_FAMILIES,
    family_declares_exit_rule,
)
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest

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


def test_the_registered_families_frozenset_is_final_and_empty() -> None:
    assert isinstance(_EXIT_RULE_REGISTERED_FAMILIES, frozenset)
    assert _EXIT_RULE_REGISTERED_FAMILIES == frozenset()


def test_every_committed_family_manifest_gates_false_and_carries_no_exit_rule() -> None:
    paths = _committed_manifest_paths()
    for path in paths:
        manifest = _load_any(path)
        assert manifest.exit_rule is None, f"{path}: unexpected exit_rule {manifest.exit_rule!r}"
        assert family_declares_exit_rule(manifest) is False, f"{path}: gate must be False today"


def test_a_manifest_with_exit_rule_not_in_the_frozenset_gates_false(tmp_path: Path) -> None:
    manifest = FamilyManifest(
        family_id="not_registered_family",
        venue="polymarket_us",
        trial_id_prefix="not_registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=tmp_path / "boundary.json",
        boundary_inputs_sha256="a" * 64,
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
        trial_id_prefix="registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=Path("deploy/families/does_not_matter.json"),
        boundary_inputs_sha256="a" * 64,
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
        trial_id_prefix="registered/trial/",
        d0_climate_day="2026-09-15",
        boundary_artefact_path=Path("deploy/families/does_not_matter.json"),
        boundary_inputs_sha256="a" * 64,
        stations=("SFO",),
        status="REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule="hold_to_settlement",
    )
    assert exit_gate_module.family_declares_exit_rule(manifest) is True
