"""Host probes for the parallel gate: shard sizing, CPU idle, and primary-tree detection.

Stdlib only; split from ``gate_shards.py``.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from pathlib import Path
from typing import Final

#: Peak resident set of one shard (shell + bwrap + pytest + spawned children),
#: measured in Phase 0 (docs/core/PARALLEL_GATE.md). A shard is budgeted at this.
PER_SHARD_GB: Final[float] = 1.5
#: Memory kept free for the host (live node, nightly studies) before sharding.
MEM_RESERVE_GB: Final[float] = 4.0
MAX_SHARDS: Final[int] = 10
DEFAULT_SHARDS: Final[int] = 10
#: Quiet-host sampling window for the serial tail, and the git probe timeout.
TAIL_IDLE_WINDOW_S: Final[float] = 3.0
GIT_TIMEOUT_S: Final[float] = 10.0


def choose_n(
    meminfo_text: str,
    requested: int | None,
    per_shard_gb: float,
    cpus: int | None = None,
) -> tuple[int, str]:
    match = re.search(r"^MemAvailable:\s+(\d+)\s*kB", meminfo_text, flags=re.MULTILINE)
    if match is None:
        raise ValueError("MemAvailable not found in meminfo")
    if requested is not None and requested < 1:
        raise ValueError(f"shard count must be at least 1, got {requested}")
    available_gb = int(match.group(1)) / 1048576
    memory_cap = math.floor((available_gb - MEM_RESERVE_GB) / per_shard_gb)
    cpu_cap = max(1, cpus if cpus is not None else (os.cpu_count() or 1))
    asked = requested if requested else DEFAULT_SHARDS
    wanted = min(asked, MAX_SHARDS)
    n = max(1, min(wanted, memory_cap, cpu_cap))
    if memory_cap < min(wanted, cpu_cap):
        reason = (
            f"memory-limited: {available_gb:.1f} GB available, {MEM_RESERVE_GB:g} GB reserved, "
            f"{per_shard_gb:g} GB per shard"
        )
    elif cpu_cap < wanted:
        reason = f"cpu-limited: {cpu_cap} cpus"
    elif requested:
        reason = f"requested {requested}"
    else:
        reason = f"default {DEFAULT_SHARDS} ({available_gb:.1f} GB available)"
    return n, reason


#: Fields of the aggregate ``cpu`` line of /proc/stat that count as time (guest is
#: already inside user), and the ones that count as idle.
_CPU_TIME_FIELDS: Final[int] = 8
_CPU_IDLE_FIELDS: Final[tuple[int, ...]] = (3, 4)


def _cpu_totals(proc_stat: str) -> tuple[int, int]:
    for line in proc_stat.splitlines():
        if line.startswith("cpu "):
            fields = [int(x) for x in line.split()[1 : 1 + _CPU_TIME_FIELDS]]
            if len(fields) < max(_CPU_IDLE_FIELDS) + 1:
                break
            return sum(fields), sum(fields[i] for i in _CPU_IDLE_FIELDS)
    raise ValueError("no aggregate cpu line in /proc/stat text")


def cpu_idle_percent(before: str, after: str) -> float:
    """Whole-host CPU idle percentage between two /proc/stat samples."""
    total_a, idle_a = _cpu_totals(before)
    total_b, idle_b = _cpu_totals(after)
    if total_b <= total_a:
        raise ValueError("/proc/stat did not advance between samples")
    return 100.0 * (idle_b - idle_a) / (total_b - total_a)


def _git_path(root: Path, flag: str) -> Path | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", flag],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        return None
    return (root / out).resolve()


def is_primary_tree(repo_root: Path) -> bool:
    """True only for the main working tree (git dir == common git dir); a linked
    worktree, a non-repository or a missing ``git`` is not primary."""
    git_dir = _git_path(repo_root, "--git-dir")
    common = _git_path(repo_root, "--git-common-dir")
    return git_dir is not None and common is not None and git_dir == common
