"""The C6 ``label`` seam's batch types (AUT-2 r7 WP6).

``Scorer.label(capture_day, exec_fills, settlements)`` has no clock and no prior-run argument, and a
registered plug-in object outlives a run. The label run therefore passes the per-run facts inside
the ``exec_fills`` argument as a :class:`ScoringBatch` and takes back a :class:`ScoredBatch` that
also carries the scorer's own counts. A plug-in builds its scorer from the batch on every call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from breezy.persistence.autonomy.label_store import LabelRow

__all__ = ["ScoredBatch", "ScoringBatch"]


@dataclass(frozen=True)
class ScoringBatch:
    """One kind's inputs for one run: the run clock, the rows already stored, the fill inputs."""

    now_ns: int
    prior: tuple[LabelRow, ...]
    inputs: tuple[Any, ...]


@dataclass(frozen=True)
class ScoredBatch:
    """One kind's rows (already stamped against ``prior``) and the scorer's own counts."""

    rows: tuple[LabelRow, ...]
    p_null_count: int = 0
    non_c1_post_epoch_count: int = 0
    legacy_sell_rows: int = 0

    @staticmethod
    def of(rows: Sequence[LabelRow]) -> ScoredBatch:
        return ScoredBatch(rows=tuple(rows))
