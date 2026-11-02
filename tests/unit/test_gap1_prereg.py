"""GAP-1 T1/T2: the existing freeze and its cited evidence are binding."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.analysis.multisource_blend_pin_guards import check_not_refrozen
from scripts.analysis.prereg_precommit_check import check_frozen_blob

ROOT = Path(__file__).resolve().parents[2]
PREREG = (
    ROOT / "docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/PREREG_GAP1_2026-11-02.json"
)


def test_t1_frozen_blob_not_refrozen_and_ancestor() -> None:
    design = json.loads(PREREG.read_text())
    assert design["frozen_sha"] == "e648d1812b88369b1db04fb468e1aadf1405cfea"
    assert check_frozen_blob(PREREG, design) == []
    check_not_refrozen(PREREG)
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", design["frozen_sha"], "HEAD"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )
    design["nu"] = 6
    assert [d.code for d in check_frozen_blob(PREREG, design)] == ["FROZEN_BLOB_DIFFERS"]


def test_t2_citations_and_required_rules() -> None:
    p = json.loads(PREREG.read_text())
    f13 = json.loads((ROOT / p["f13_prereg"]["path"]).read_text())
    canonical = json.dumps(
        {k: v for k, v in f13.items() if k != "frozen_sha"}, sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == p["f13_prereg"]["content_sha256"]
    assert f13["frozen_sha"] == p["f13_prereg"]["frozen_sha"]
    assert (
        hashlib.sha256((ROOT / p["c1_evidence"]["path"]).read_bytes()).hexdigest()
        == p["c1_evidence"]["sha256"]
    )
    assert p["successor"]["only_dir"].endswith(p["run_id"] + "-s2/j3")
    assert p["k_cum"] == {
        "before": 1,
        "added": "6 cells + 1 F13 primary; +1 per burned primary",
        "after": 8,
    }
    assert set(p) >= {
        "baselines",
        "cells",
        "census_rule",
        "ci",
        "constants",
        "envelopes",
        "estimand",
        "events",
        "inclusion",
        "ladder",
        "nu",
        "oof_header_expect",
        "overall",
        "power",
        "precedence",
        "root",
        "run_id",
        "successor",
        "test_plan",
    }
    assert p["test_plan"]["T8b"].startswith("scipy.stats.t(df=5")
    assert p["census_rule"]["prior_floor"] == p["power"]["prior_floor"] == 914
    assert p["envelopes"]["J2"]["MemoryMax"] == p["envelopes"]["J3"]["MemoryMax"] == "12G"
