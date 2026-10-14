"""MAKER-S2 WP6: run configuration, summary, preflight record and the refusal vocabulary."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_frozen import FrozenDateSet
from scripts.analysis.maker_stage0_model import ModelPin
from scripts.analysis.maker_stage0_nodelog import NodeLogScan

__all__ = [
    "MIN_FREE_BYTES",
    "RSS_ABORT_BYTES",
    "S5_MAX_SECONDS",
    "DiskLow",
    "MemoryAbort",
    "Pre",
    "RunConfig",
    "RunDirExists",
    "RunSummary",
    "SubsetRefused",
]

MIN_FREE_BYTES: Final[int] = 10 * 2**30  # E4
RSS_ABORT_BYTES: Final[int] = 4 * 2**30  # S-5
S5_MAX_SECONDS: Final[float] = 6 * 3600.0


class SubsetRefused(ValueError):
    """A subset flag or an inconsistent mode combination was given to a verdict run."""


class RunDirExists(ValueError):
    """The run directory (or its scratch root) already exists: no resume, no overwrite."""


class DiskLow(RuntimeError):
    """E4: less than 10 GiB free on the output volume."""


class MemoryAbort(RuntimeError):
    """S-5: resident memory exceeded 4 GiB mid-run; the run is void."""


@dataclass(frozen=True, kw_only=True)
class RunConfig:
    census_days: Path
    trade_unit: Path
    catalog_root: Path
    nbp_root: Path
    truth: Path
    truth_cross_check: Path
    node_log_dir: Path
    out_dir: Path
    repo_root: Path
    amendment: Path
    amendment_sha: str
    spec: Path
    ledger: Path
    work_root: Path
    addendum: Path | None = None
    addendum_sha: str | None = None
    stations: tuple[str, ...] | None = None
    days: tuple[dt.date, ...] | None = None
    bench: int | None = None
    tail_only: bool = False
    verify_first: bool = False
    parity: tuple[tuple[str, int], ...] | None = None
    tail_csv: Path | None = None
    as_of: dt.date | None = None
    argv: tuple[str, ...] = ()
    min_free_bytes: int = MIN_FREE_BYTES


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    label: str | None
    code_sha: str
    mode: str


@dataclass(frozen=True)
class Pre:
    """Everything preflight established before the ledger is touched."""

    frozen: FrozenDateSet
    census: dict[tuple[str, dt.date], CensusedDay]
    scans: list[NodeLogScan]
    scan_paths: list[Path]
    model: ModelPin
    code_sha: str
    free_start: int
    started: float = field(default_factory=time.monotonic)
