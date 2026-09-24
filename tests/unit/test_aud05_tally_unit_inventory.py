"""AUD-05 D-E standing guard: a family-tally timer must name a REGISTERED family.

The retired ``breezy-pm-crh-*-tally`` units are not in this git tree (they
live in the user systemd directory). This test guards the repo unit files.
Removing the installed copies is a post-merge deploy step, not a systemctl
call from this worktree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO / "deploy" / "systemd"
_FAMILIES = _REPO / "deploy" / "families"


def _registered_ids(families_dir: Path) -> set[str]:
    ids: set[str] = set()
    for path in families_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("status") == "REGISTERED":
            family_id = payload.get("family_id")
            if isinstance(family_id, str):
                ids.add(family_id)
    return ids


def _offending_units(unit_dir: Path, families_dir: Path) -> list[str]:
    registered = _registered_ids(families_dir)
    bad: list[str] = []
    for path in sorted(unit_dir.iterdir()):
        name = path.name
        if name.startswith("breezy-pm-crh-") and "tally" in name:
            bad.append(name)
            continue
        marker = "breezy-family-tally@"
        if marker not in name:
            continue
        instance = name.split("@", 1)[1]
        instance = instance.split(".", 1)[0]
        if not instance or instance.startswith("%"):
            continue
        if instance not in registered:
            bad.append(name)
    return bad


def test_no_installed_family_tally_timer_targets_an_unregistered_family() -> None:
    assert _offending_units(_SYSTEMD, _FAMILIES) == []


def test_an_unregistered_instance_and_an_orphan_name_fail_the_guard(tmp_path: Path) -> None:
    units = tmp_path / "units"
    families = tmp_path / "families"
    units.mkdir()
    families.mkdir()
    (families / "pm_us_crh_v4.json").write_text(
        json.dumps({"family_id": "pm_us_crh_v4", "status": "REGISTERED"}),
        encoding="utf-8",
    )
    (units / "breezy-family-tally@.timer").write_text("[Timer]\n", encoding="utf-8")
    (units / "breezy-family-tally@pm_us_crh_v4.timer").write_text("[Timer]\n", encoding="utf-8")
    (units / "breezy-family-tally@not_a_family.timer").write_text("[Timer]\n", encoding="utf-8")
    (units / "breezy-pm-crh-cont-tally.timer").write_text("[Timer]\n", encoding="utf-8")
    offending = _offending_units(units, families)
    assert "breezy-family-tally@pm_us_crh_v4.timer" not in offending
    assert "breezy-family-tally@.timer" not in offending
    assert "breezy-family-tally@not_a_family.timer" in offending
    assert "breezy-pm-crh-cont-tally.timer" in offending
    with pytest.raises(AssertionError):
        assert offending == []
