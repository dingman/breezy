"""MAKER-S2 S-5 bench screen: projected wall time and a leak-growth memory projection (pure).

Plan r3/r4: "Per-station-day RSS goes in the progress events; linear extrapolation to the set size
is a screen, not a proof; S-5 fires if the projection exceeds 4 GiB or 6 h."

Time: ``projected_total_s = mean(elapsed_s) * n_replayable_station_days`` (unchanged).

Memory. ``ru_maxrss`` is a ratchet, so its per-row delta is NOT a growth rate: the first rows
raise the high-water mark once (allocator warm-up, the heaviest day) and later rows add 0. The
old screen extrapolated the MEAN delta over the remaining rows and so read that one-off warm-up as
per-row growth (47.5 GB for a process whose end-of-row RSS was flat at ~2.1 GB). A leak is growth
of the RESIDENT set that persists from row to row, so the screen is

    projected_peak = max(peak_rss over rows) + slope * (n_replayable - n_rows)

where ``slope`` is the least-squares slope of the END-OF-ROW ``rss_bytes`` over the row index,
fitted on the rows after the ``WARMUP_ROWS`` first ones and floored at 0. The first two rows are
excluded because they are where the process builds its working set (allocator arenas, interned
levels, the first and heaviest day's slices); with fewer than two rows left no slope can be fitted
and the observed peak alone is projected (a screen that cannot see a leak says so, it does not
invent one). A process that grows >= S bytes per row after warm-up projects S * remaining on top
of its peak. The in-run ``RSS_ABORT_BYTES`` check on every pass still bounds the per-row peak.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from scripts.analysis.maker_stage0_run_types import RSS_ABORT_BYTES, S5_MAX_SECONDS

__all__ = ["WARMUP_ROWS", "BenchProjection", "project_bench"]

WARMUP_ROWS: Final[int] = 2
_MIN_FIT_ROWS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class BenchProjection:
    projected_total_s: float
    projected_peak_rss_bytes: int
    rss_slope_bytes_per_row: int
    s5_exceeded: bool


def _slope(ys: Sequence[float]) -> float:
    """Least-squares slope of ``ys`` over 0..n-1 (0.0 when fewer than two points)."""
    n = len(ys)
    if n < _MIN_FIT_ROWS:
        return 0.0
    mean_x, mean_y = (n - 1) / 2, sum(ys) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(ys))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den


def project_bench(rows: Sequence[Mapping[str, Any]], total: int) -> BenchProjection:
    """Project the full set (``total`` station-days) from the timed rows, in run order."""
    mean_s = sum(r["elapsed_s"] for r in rows) / max(1, len(rows))
    peak = max((r["peak_rss_bytes"] for r in rows), default=0)
    resident = [float(r["rss_bytes"]) for r in rows[WARMUP_ROWS:]]
    slope = max(0, int(_slope(resident)))
    projected = peak + slope * max(0, total - len(rows))
    exceeded = mean_s * total > S5_MAX_SECONDS or projected > RSS_ABORT_BYTES
    return BenchProjection(mean_s * total, projected, slope, exceeded)
