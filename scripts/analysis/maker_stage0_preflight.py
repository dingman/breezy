"""MAKER-S2 WP6: everything that can be refused BEFORE the ledger claim (r3 WP6; review M2, M3).

A refusal costs nothing; a post-claim failure burns the one-shot ledger entry. So the mode and its
licences (``--bench`` sample size, ``--tail-only`` stations), the frozen set's census completeness,
the venue theta range, the existence and readability of every pinned input (truth cross-check
parquet, NBP manifest, spec, ``uv.lock``, the node-log directory), disk space, the truth CSV sha,
the model pin and the clean tree are all decided here, in that order.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_frozen import (
    FrozenDateSet,
    FrozenSetRefused,
    assert_in_frozen_set,
    load_amendment,
)
from scripts.analysis.maker_stage0_inputs import (
    MAKER_STATIONS,
    InputRefused,
    load_census_days,
    load_trade_unit,
    sha256_file,
)
from scripts.analysis.maker_stage0_model import load_model
from scripts.analysis.maker_stage0_modes import free_bytes
from scripts.analysis.maker_stage0_nodelog import NodeLogScan, scan_node_log
from scripts.analysis.maker_stage0_pins import assert_clean_tree, git_commit
from scripts.analysis.maker_stage0_run_types import (
    BENCH_COUNTS,
    DiskLow,
    Pre,
    RunConfig,
    SubsetRefused,
)
from scripts.analysis.maker_stage0_runio import theta_for_day

__all__ = ["check_theta", "mode_of", "preflight", "requested", "scan_logs"]

THETA_RANGE: Final[tuple[float, float]] = (0.0, 0.2)  # r4 (r)6: a coefficient outside is refused
Key = tuple[str, dt.date]


def mode_of(cfg: RunConfig) -> str:
    """The one mode ``cfg`` selects, with the licence checks that need no read."""
    flags = (
        ("bench", cfg.bench is not None),
        ("tail-only", cfg.tail_only),
        ("verify-first", cfg.verify_first),
    )
    chosen = [name for name, on in flags if on]
    if len(chosen) > 1:
        raise SubsetRefused(f"modes {chosen} are mutually exclusive")
    mode = chosen[0] if chosen else "verdict"
    if mode != "bench" and (cfg.stations is not None or cfg.days is not None):
        raise SubsetRefused(f"{mode} run refuses --stations/--days (only --bench accepts them)")
    if mode == "bench" and cfg.bench not in BENCH_COUNTS:
        raise SubsetRefused(f"--bench N must be one of {BENCH_COUNTS}, got {cfg.bench}")
    if mode == "tail-only":
        if not cfg.parity:
            raise InputRefused("--tail-only needs --parity STATION:0|1 for every station")
        outside = sorted({station for station, _ in cfg.parity} - set(MAKER_STATIONS))
        if outside:
            raise InputRefused(
                f"--parity stations {outside} are outside MAKER_STATIONS {MAKER_STATIONS}"
                " (NYC is never read)"
            )
    return mode


def requested(cfg: RunConfig, fs: FrozenDateSet) -> dict[Key, CensusedDay]:
    """The census rows of every requested (station, day); each one must exist exactly once."""
    stations, days = cfg.stations or fs.stations, cfg.days or fs.dates
    for station in stations:
        for day in days:
            assert_in_frozen_set(fs, station, day)
    census: dict[Key, CensusedDay] = {}
    for row in load_census_days(cfg.need("census_days")).rows:
        if row.station in stations and row.climate_day in days:
            key = (row.station, row.climate_day)
            if key in census:
                raise FrozenSetRefused(f"duplicate census row for {key[0]} {key[1]}")
            census[key] = row
    absent = [f"{s} {d}" for s in stations for d in days if (s, d) not in census]
    if absent:
        raise FrozenSetRefused(
            f"the census holds no row for {len(absent)} frozen station-days, e.g. {absent[:3]}"
        )
    return census


def check_theta(days: list[dt.date]) -> None:
    low, high = THETA_RANGE
    for day in days:
        theta = theta_for_day(day)
        if not low <= theta <= high:
            raise InputRefused(f"theta {theta} for {day} is outside [{low}, {high}]")


def scan_logs(directory: Path) -> tuple[list[NodeLogScan], list[Path]]:
    paths = sorted(directory.glob("*.log"))
    return [scan_node_log(p) for p in paths], paths


def _need_file(path: Path, what: str) -> None:
    if not path.is_file():
        raise InputRefused(f"{what} {path} is missing or not a file")


def _need_parquet(path: Path, what: str) -> None:
    _need_file(path, what)
    try:
        pq.read_metadata(path)
    except (OSError, ValueError) as exc:
        raise InputRefused(
            f"{what} {path} is not a readable parquet ({type(exc).__name__})"
        ) from exc


def _need_json(path: Path, what: str) -> None:
    _need_file(path, what)
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputRefused(f"{what} {path} is not readable JSON ({type(exc).__name__})") from exc


def require_inputs(cfg: RunConfig, mode: str) -> None:
    """Existence and readability of every pinned input the mode will touch (before the claim)."""
    logs = cfg.need("node_log_dir")
    if not logs.is_dir():
        raise InputRefused(
            f"--node-log-dir {logs} is not a directory: refusing (a missing directory would "
            "silently mark every day NODE_LOG_ABSENT and drop the outage exclusions)"
        )
    if mode == "bench":
        return
    _need_parquet(cfg.truth_cross_check, "truth cross-check parquet")
    _need_json(cfg.nbp_root / "_manifest.json", "NBP manifest")
    if mode == "verdict":
        _need_file(cfg.spec, "spec")
        _need_file(cfg.repo_root / "uv.lock", "uv.lock")


def preflight(cfg: RunConfig, mode: str) -> Pre:
    fs = load_amendment(cfg.amendment, cfg.amendment_sha)
    census = requested(cfg, fs)
    check_theta(sorted({d for _, d in census}))
    require_inputs(cfg, mode)
    free = free_bytes(cfg.out_dir.parent)
    if free < cfg.min_free_bytes:
        raise DiskLow(f"E4: {free} bytes free < {cfg.min_free_bytes}")
    if sha256_file(cfg.need("truth")) != fs.truth_csv_sha256:
        raise InputRefused("truth CSV sha256 differs from the frozen block's pinned sha")
    load_trade_unit(cfg.need("trade_unit"))
    model = load_model(cfg.repo_root)
    if mode != "bench":
        assert_clean_tree(cfg.repo_root)
    scans, paths = scan_logs(cfg.need("node_log_dir"))
    return Pre(fs, census, scans, paths, model, git_commit(cfg.repo_root), free)
