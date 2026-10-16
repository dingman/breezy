"""MAKER-S2 WP6: run configuration, summary, preflight record and the refusal vocabulary."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_inputs import InputRefused
from scripts.analysis.maker_stage0_model import ModelPin
from scripts.analysis.maker_stage0_nodelog import NodeLogScan

if TYPE_CHECKING:  # annotation only: the frozen-set module names the truth table type
    from scripts.analysis.maker_stage0_frozen import FrozenDateSet

__all__ = [
    "BENCH_COUNTS",
    "MIN_FREE_BYTES",
    "RSS_ABORT_BYTES",
    "S5_MAX_SECONDS",
    "DiskLow",
    "MemoryAbort",
    "Pre",
    "RunConfig",
    "RunDirExists",
    "RunSummary",
    "RunVoided",
    "SubsetRefused",
]

MIN_FREE_BYTES: Final[int] = 10 * 2**30  # E4
RSS_ABORT_BYTES: Final[int] = 4 * 2**30  # S-5
S5_MAX_SECONDS: Final[float] = 6 * 3600.0
BENCH_COUNTS: Final[tuple[int, ...]] = (4, 8)  # the licence allows these two sample sizes only


class SubsetRefused(ValueError):
    """A subset flag or an inconsistent mode combination was given to a verdict run."""


class RunDirExists(ValueError):
    """The run directory (or its scratch root) already exists: no resume, no overwrite."""


class DiskLow(RuntimeError):
    """E4: less than 10 GiB free on the output volume."""


class MemoryAbort(RuntimeError):
    """S-5: resident memory exceeded 4 GiB mid-run; the run is void."""


class RunVoided(RuntimeError):
    """A failure AFTER the ledger claim: the run directory is voided (CLI exit 3).

    ``cause`` is the original failure; ``void_failure`` is set when renaming the run directory
    ALSO failed, so the message never loses the real cause.
    """

    def __init__(self, cause: BaseException, *, void_failure: BaseException | None = None) -> None:
        detail = f"{type(cause).__name__}: {cause}"
        if void_failure is not None:
            detail += (
                f" [voiding the run directory ALSO failed: "
                f"{type(void_failure).__name__}: {void_failure}]"
            )
        super().__init__(detail)
        self.cause = cause
        self.void_failure = void_failure


@dataclass(frozen=True, kw_only=True)
class RunConfig:
    catalog_root: Path
    nbp_root: Path
    truth_cross_check: Path
    out_dir: Path
    repo_root: Path
    amendment: Path
    amendment_sha: str
    spec: Path
    ledger: Path
    work_root: Path
    census_days: Path | None = None  # absent only for --verify-first
    trade_unit: Path | None = None
    truth: Path | None = None
    node_log_dir: Path | None = None
    addendum: Path | None = None
    addendum_sha: str | None = None
    stations: tuple[str, ...] | None = None
    days: tuple[dt.date, ...] | None = None
    bench: int | None = None
    tail_only: bool = False
    verify_first: bool = False
    parity: tuple[tuple[str, int], ...] | None = None
    tail_csv: Path | None = None
    argv: tuple[str, ...] = ()
    min_free_bytes: int = MIN_FREE_BYTES
    block_first_day: str | None = None  # ISO day of a v2 block; None for v1 (six-key entry)
    isolate: bool = True  # S-5: one child process per station-day; False only for in-process tests

    def need(self, name: str) -> Path:
        """A path that the chosen mode requires; absence is a typed refusal, never a sentinel."""
        value: Path | None = getattr(self, name)
        if value is None:
            raise InputRefused(f"--{name.replace('_', '-')} is required for this run")
        return value


@dataclass(frozen=True)
class RunSummary:
    run_dir: Path
    label: str | None
    code_sha: str
    mode: str
    first_replayable_observed: str | None = None


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
