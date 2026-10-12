"""Synthetic Phase B tree for the TE-2 WP1c tests: a committed predeclaration, pins and family.

Starts from the Phase A world (``te2_cli_fixtures.build_world``) and its Phase A table, copies the
world's tmp git repo, commits stub family modules plus ``TE2_PREDECLARATION.json`` in one commit,
and writes a pins file whose HEAD blobs cover the family. Offline; nothing real is read.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.analysis import fq_v1_loss_taxonomy as cli
from scripts.analysis.fq_loss_taxonomy_battery import s0i_statuses_from_phase_a
from scripts.analysis.fq_loss_taxonomy_predecl import (
    SRC_DEPENDENCIES,
    default_consumer_map,
    thresholds_block,
)
from tests.support.te2_cli_fixtures import World, utc_ns
from tests.support.te2_fixtures import git_cmd

FAMILY = (
    "scripts/analysis/fq_loss_taxonomy_core.py",
    "scripts/analysis/fq_loss_taxonomy_stats.py",
    "scripts/analysis/fq_v1_loss_taxonomy.py",
)
PRE_REL = "docs/evidence/te2/TE2_PREDECLARATION.json"
PINS_REL = "docs/evidence/te2/TE2_PINS.json"
#: Where the (patched) running-module locator believes the code runs from: the frozen tmp tree.
RUNNING_ROOT: list[Path] = []
NOW_NS = utc_ns(dt.date(2026, 10, 12), 10.0)
RESULT_NAME = "fq_v1_loss_taxonomy_2026-10-12"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def faithful_locate(rel: str) -> Path | None:
    """A stand-in for ``locate_running``: the stub tree IS the code that runs (set by build)."""
    return RUNNING_ROOT[-1] / rel if RUNNING_ROOT else None


@dataclass(frozen=True)
class BPaths:
    repo: Path
    table: Path
    predeclaration: Path
    pins: Path
    pre_commit: str
    out: Path
    world: World

    def argv(self, *, extra: list[str] | None = None) -> list[str]:
        return [
            "phase-b", "--fills-db", str(self.world.fills_db), "--output-dir", str(self.out),
            "--repo-root", str(self.repo), "--catalog-root", str(self.out / "catalog"),
            "--pins-json", str(self.pins), "--now-ns", str(NOW_NS),
            "--predeclaration", str(self.predeclaration), "--phase-a-table", str(self.table),
            "--archive-root", str(self.world.archive_root), *(extra or []),
        ]  # fmt: skip

    @property
    def result_json(self) -> Path:
        return self.out / f"{RESULT_NAME}.json"

    @property
    def result_md(self) -> Path:
        return self.out / f"{RESULT_NAME}.md"


def build_phase_b(
    tmp: Path,
    world: World,
    table: Path,
    *,
    thresholds_patch: Mapping[str, Any] | None = None,
) -> BPaths:
    """Copy the world repo, commit family + predeclaration, write pins. Returns the paths."""
    repo = tmp / "repo"
    shutil.copytree(world.repo_root, repo)
    for index, rel in enumerate((*FAMILY, *SRC_DEPENDENCIES)):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(f"# frozen stub {index}\nX = {index}\n")
    table_payload = json.loads(table.read_text())
    thresholds = {**thresholds_block(), **(thresholds_patch or {})}
    predeclaration = {
        "phase_a_table_sha256": sha256_path(table),
        "thresholds": thresholds,
        "consumer_map": default_consumer_map(),
        "s0i_statuses": s0i_statuses_from_phase_a(
            table_payload, alpha_primary=float(thresholds["alpha_primary"])
        ),
        "terminal_climate_day": cli.TERMINAL_CLIMATE_DAY.isoformat(),
    }
    pre_path = repo / PRE_REL
    pre_path.parent.mkdir(parents=True, exist_ok=True)
    pre_path.write_text(json.dumps(predeclaration, indent=2, sort_keys=True) + "\n")
    git_cmd(repo, "add", PRE_REL, *FAMILY, *SRC_DEPENDENCIES)
    git_cmd(repo, "commit", "-q", "-m", "freeze: predeclaration + family")
    pre_commit = git_cmd(repo, "rev-parse", "HEAD")
    pins = repo / PINS_REL
    pins.write_text(
        json.dumps(
            {
                "head_blob_sha256": {rel: sha256_path(repo / rel) for rel in FAMILY},
                "src_dependency_sha256": {rel: sha256_path(repo / rel) for rel in SRC_DEPENDENCIES},
                "predeclaration_commit": pre_commit,
                "reflog_snapshot_sha256": world.snapshot_sha256,
            }
        )
    )
    git_cmd(repo, "add", PINS_REL)
    git_cmd(repo, "commit", "-q", "-m", "freeze: pins")
    RUNNING_ROOT.append(repo)
    return BPaths(repo, table, pre_path, pins, pre_commit, tmp / "out", world)


def rewrite_pins(b: BPaths, mutate: Any) -> None:
    """Edit the pins file and COMMIT it: only the edited content (not dirtiness) is under test."""
    payload = json.loads(b.pins.read_text())
    mutate(payload)
    b.pins.write_text(json.dumps(payload))
    git_cmd(b.repo, "add", PINS_REL)
    git_cmd(b.repo, "commit", "-q", "-m", "freeze: pins edit")
