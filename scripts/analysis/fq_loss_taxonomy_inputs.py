"""TE-2 FQ v1 loss taxonomy: I/O wrappers over the reused modules.

WP0 stub. The clipping wrapper, the Phase A projection, the streaming and partition-union log
readers, the reflog pin resolver and the git port live here. Every public callable raises
``NotImplementedError``; nothing here imports ``breezy.adapters.polymarket_us.exec.*`` directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from breezy.analysis.labeling.decision_link import BridgeEvent, BridgeMatch, BridgeReport
from breezy.analysis.labeling.epoch import EpochReader
from breezy.analysis.labeling.settlement_source import SettlementSource
from breezy.domain.nws_climate_day import NwsClimateDay

__all__ = [
    "AttributionResult",
    "AuditReproduction",
    "Boot",
    "BootPin",
    "ClippingSettlementSource",
    "GitPort",
    "PartitionEvent",
    "PhaseAProjection",
    "S0ACounts",
    "SnapshotShaMismatch",
    "SubprocessGit",
    "UnclassifiedFillsStop",
    "alt_truth_summary",
    "attribute_fills",
    "iter_partition_events",
    "partition_union",
    "phase_b_refusals",
    "pin_label",
    "post_hoc_violations",
    "project_phase_a",
    "refreeze_status",
    "reproduce_audit",
    "resolve_pins",
    "s0a_counts",
    "stream_take_events",
    "truth_status",
]


class UnclassifiedFillsStop(Exception):
    """A fill did not attribute to exactly one Take: the plan STOPs (S0-C)."""


class SnapshotShaMismatch(Exception):
    """The reflog snapshot's sha256 differs from the value pinned in TE2_PINS.json."""


class GitPort(Protocol):
    def head_blob_sha256(self, path: str) -> str: ...
    def porcelain_clean(self, paths: Sequence[str]) -> bool: ...
    def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
    def blob_sha256(self, commit: str, path: str) -> str | None: ...
    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]: ...


class SubprocessGit:
    """The production ``GitPort``: read-only git subprocess calls in ``repo_root``."""

    def __init__(self, repo_root: Path) -> None:
        raise NotImplementedError

    def head_blob_sha256(self, path: str) -> str:
        raise NotImplementedError

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        raise NotImplementedError

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        raise NotImplementedError

    def blob_sha256(self, commit: str, path: str) -> str | None:
        raise NotImplementedError

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        raise NotImplementedError


class ClippingSettlementSource:
    """A ``SettlementSource`` that returns ``None`` for any climate day after ``last_day``."""

    def __init__(self, inner: SettlementSource, last_day: dt.date) -> None:
        raise NotImplementedError

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        raise NotImplementedError


@dataclass(frozen=True)
class PhaseAProjection:
    """A settlement record with ``tmax_f`` removed: what the outcome-blind Phase A may see."""

    station: str
    climate_day: dt.date
    is_final: bool
    is_superseded: bool
    correction_flag: bool
    revision_seq: int


def project_phase_a(record: NwsClimateDay) -> PhaseAProjection:
    raise NotImplementedError


def truth_status(projection: PhaseAProjection | None) -> Literal["SETTLED", "TRUTH_UNSETTLED"]:
    raise NotImplementedError


@dataclass(frozen=True)
class S0ACounts:
    n_fills: int
    n_instruments: int
    n_no_leg: int
    n_open_ended: int
    n_station_days: int
    n_clusters: int
    n_clusters_excluding_k1b: int
    n_k1b_fills: int
    n_k1b_station_days: int


def s0a_counts(
    db_path: Path,
    terminal_climate_day: dt.date,
    fq_window_start: dt.date = dt.date(2026, 10, 1),
) -> S0ACounts:
    raise NotImplementedError


@dataclass(frozen=True)
class AttributionResult:
    matches: tuple[BridgeMatch, ...]
    report: BridgeReport


def attribute_fills(
    fills: Sequence[object],
    log_files: Sequence[Path],
    *,
    data_root: Path,
    epoch_reader: EpochReader | None = None,
    family_id: str = "pm_us_crh_fq_v1",
    recalibration: str | None = None,
) -> AttributionResult:
    raise NotImplementedError


def stream_take_events(path: Path, *, chunk_size: int = 1 << 20) -> Iterator[BridgeEvent]:
    raise NotImplementedError


@dataclass(frozen=True)
class PartitionEvent:
    station: str
    climate_day: dt.date
    rung_id: str
    kind: str


def iter_partition_events(path: Path) -> Iterator[PartitionEvent]:
    raise NotImplementedError


def partition_union(
    events: Iterator[PartitionEvent],
) -> dict[tuple[str, dt.date], frozenset[str]]:
    raise NotImplementedError


@dataclass(frozen=True)
class Boot:
    number: int
    boot_time: dt.datetime
    logged_manifest_sha256: str
    logged_artefact_sha256: str


@dataclass(frozen=True)
class BootPin:
    boot_number: int
    commit: str | None
    near_boundary: bool
    state: Literal["PINNED", "UNTESTABLE"]
    reason: str | None


def resolve_pins(
    snapshot_path: Path,
    expected_snapshot_sha256: str,
    boots: Sequence[Boot],
    git: GitPort,
    *,
    manifest_path: str,
    artefact_path: str,
    widened_paths: Sequence[str],
    reproduces_under: Callable[[int, str], bool] | None = None,
) -> tuple[BootPin, ...]:
    raise NotImplementedError


def pin_label(widened_path_commits: Sequence[str]) -> Literal["STABLE", "INFERRED"]:
    raise NotImplementedError


def phase_b_refusals(
    pinned_blob_sha256: dict[str, str], predeclaration_commit: str, git: GitPort
) -> tuple[str, ...]:
    raise NotImplementedError


def refreeze_status(
    frozen: dict[str, str], head: dict[str, str], new_predeclaration_pins: dict[str, str] | None
) -> Literal["OK", "REFROZEN", "REFREEZE_REQUIRED"]:
    raise NotImplementedError


def post_hoc_violations(
    predeclaration_commit: str, artefact_commit: str, git: GitPort
) -> tuple[str, ...]:
    raise NotImplementedError


@dataclass(frozen=True)
class AuditReproduction:
    n_fills: int
    n_wins: int
    net_pnl: Decimal
    wins: tuple[tuple[str, int], ...]
    n_refused: int


def reproduce_audit(
    fills: Sequence[object],
    source: SettlementSource,
    *,
    now_ns: int,
    clip_after: dt.date = dt.date(2026, 10, 6),
) -> AuditReproduction:
    raise NotImplementedError


@dataclass(frozen=True)
class AltTruth:
    k3_status: Literal["TESTED", "UNTESTABLE"]
    k3_count: int | None
    k4_status: Literal["TESTED", "UNTESTABLE"]
    k4_count: int | None


def alt_truth_summary(
    metar_flips: dict[str, bool] | None, venue_mismatches: dict[str, bool] | None
) -> AltTruth:
    raise NotImplementedError
