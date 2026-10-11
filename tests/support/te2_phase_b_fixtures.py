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
from scripts.analysis.fq_loss_taxonomy_predecl import default_consumer_map, thresholds_block
from tests.support.te2_cli_fixtures import World, utc_ns
from tests.support.te2_fixtures import git_cmd

FAMILY = (
    "scripts/analysis/fq_loss_taxonomy_core.py",
    "scripts/analysis/fq_loss_taxonomy_stats.py",
    "scripts/analysis/fq_v1_loss_taxonomy.py",
)
PRE_REL = "docs/evidence/te2/TE2_PREDECLARATION.json"
NOW_NS = utc_ns(dt.date(2026, 10, 12), 10.0)
RESULT_NAME = "fq_v1_loss_taxonomy_2026-10-12"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    for index, rel in enumerate(FAMILY):
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
    git_cmd(repo, "add", PRE_REL, *FAMILY)
    git_cmd(repo, "commit", "-q", "-m", "freeze: predeclaration + family")
    pre_commit = git_cmd(repo, "rev-parse", "HEAD")
    pins = tmp / "TE2_PINS.json"
    pins.write_text(
        json.dumps(
            {
                "head_blob_sha256": {rel: sha256_path(repo / rel) for rel in FAMILY},
                "predeclaration_commit": pre_commit,
                "reflog_snapshot_sha256": world.snapshot_sha256,
            }
        )
    )
    return BPaths(repo, table, pre_path, pins, pre_commit, tmp / "out", world)
