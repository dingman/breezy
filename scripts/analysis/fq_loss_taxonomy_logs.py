"""TE-2 loss taxonomy: log readers, take attribution and the S0-A count gate (I/O). WP0 stub."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.labeling.decision_link import BridgeEvent, BridgeMatch, BridgeReport
from breezy.analysis.labeling.epoch import EpochReader
from breezy.analysis.labeling.fill_source import FillRead

CHUNK_BYTES: Final = 1 << 20


class UnclassifiedFillsStop(Exception):
    """A fill did not attribute to exactly one Take: the plan STOPs (S0-C)."""


class S0AStop(Exception):
    """An S0-A count differs from the verified P6 counts."""


class UnparseableInstrumentStop(S0AStop):
    """A durable fill's instrument id does not parse as a weather slug."""


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


def s0a_gate(counts: S0ACounts) -> None:
    """Raise ``S0AStop`` unless the counts equal P6: 25/25/0/6 and 14 days, 7 clusters, 5 K1b."""
    raise NotImplementedError


@dataclass(frozen=True)
class AttributionResult:
    matches: tuple[BridgeMatch, ...]
    report: BridgeReport


def attribute_fills(
    fills: FillRead,
    log_files: Sequence[Path],
    *,
    data_root: Path,
    epoch_reader: EpochReader | None = None,
    family_id: str = "pm_us_crh_fq_v1",
    recalibration: str | None = None,
) -> AttributionResult:
    raise NotImplementedError


def stream_take_events(path: Path, *, chunk_size: int = CHUNK_BYTES) -> Iterator[BridgeEvent]:
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
