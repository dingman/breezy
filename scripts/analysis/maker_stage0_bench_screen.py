"""MAKER-S2 S-5 bench screen: projected wall time and a repeat-day leak projection (pure).

Plan r3/r4: "Per-station-day RSS goes in the progress events; linear extrapolation to the set size
is a screen, not a proof; S-5 fires if the projection exceeds 4 GiB or 6 h."

Rows are in run order. The bench replays its heaviest station-day a SECOND time as the final row
(``repeat_of_first: true``); that row is excluded from every time figure.

Time. The bench rows are the HEAVIEST station-days by catalog bytes, so extrapolating by count
(``mean(elapsed_s) * n``, kept as ``projected_total_s_by_count``) charges every remaining day at a
heavy-day cost. ``projected_total_s`` is ``max(proportional, affine)``: proportional is ``(sum
elapsed_s / sum bench bytes) * sum bytes of all replayable station-days`` (optimistic for fixed
per-day costs); affine fits ``elapsed = a + b * bytes`` by least squares over >= 4 rows and
projects ``a * n_days + b * total_bytes``. It is used only when the fit is non-degenerate
(``a >= 0`` and ``b >= 0``). Degenerate weights fall back to the by-count figure.

Memory. ``ru_maxrss`` is a ratchet, so its per-row delta is not a growth rate (the old mean-delta
screen projected 47.5 GB for a flat ~2.1 GB process), and the slope of end-of-row RSS over run
order is confounded by the heaviest day landing early. A leak is growth that persists when the
SAME work is repeated, so the leak rate is

    max(0, rss_end(repeat row) - rss_end(first replay of that day)) / rows between them

and ``projected_peak = max(peak_rss over all rows) + leak_rate * remaining station-days``. A bench
without a repeat row projects the observed peak only. The least-squares slope of end-of-row RSS
over the rows after ``DIAGNOSTIC_WARMUP_ROWS`` is reported (``rss_slope_bytes_per_row``) but does
not decide S-5. The in-run ``RSS_ABORT_BYTES`` check on every pass bounds the per-row peak.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from scripts.analysis.maker_stage0_run_types import RSS_ABORT_BYTES, S5_MAX_SECONDS

__all__ = ["DIAGNOSTIC_WARMUP_ROWS", "MIN_AFFINE_ROWS", "BenchProjection", "project_bench"]

DIAGNOSTIC_WARMUP_ROWS: Final[int] = 2
MIN_AFFINE_ROWS: Final[int] = 4
_MIN_FIT_ROWS: Final[int] = 2


@dataclass(frozen=True, slots=True)
class BenchProjection:
    projected_total_s: float
    projected_total_s_by_count: float
    by_count_exceeds_cap: bool
    projected_peak_rss_bytes: int
    leak_rate_bytes_per_row: int
    rss_slope_bytes_per_row: int
    n_fit_rows: int  # rows behind the diagnostic slope (0 when none was fitted)
    n_time_fit_rows: int  # rows behind the affine time fit (0 when proportional is used)
    s5_exceeded: bool


def _ols(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """(intercept, slope) of the least-squares line, or None when x has no spread."""
    n = len(xs)
    if n < _MIN_FIT_ROWS:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    den = sum((x - mean_x) ** 2 for x in xs)
    if den <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / den
    return mean_y - slope * mean_x, slope


def _is_repeat(row: Mapping[str, Any]) -> bool:
    return bool(row.get("repeat_of_first", False))


def _proportional(timed: Sequence[Mapping[str, Any]], total_weight: int, fallback: float) -> float:
    weights = [r.get("catalog_bytes", 0) for r in timed]
    if not timed or min(weights) <= 0 or total_weight <= 0:
        return fallback
    return float(sum(r["elapsed_s"] for r in timed) / sum(weights) * total_weight)


def _affine(timed: Sequence[Mapping[str, Any]], total: int, total_weight: int) -> tuple[float, int]:
    """(projected seconds, rows fitted); (0.0, 0) when the fit is unavailable or degenerate."""
    if len(timed) < MIN_AFFINE_ROWS or total_weight <= 0:
        return 0.0, 0
    fit = _ols([float(r.get("catalog_bytes", 0)) for r in timed], [r["elapsed_s"] for r in timed])
    if fit is None or fit[0] < 0 or fit[1] < 0:
        return 0.0, 0
    return fit[0] * total + fit[1] * total_weight, len(timed)


def _leak_rate(rows: Sequence[Mapping[str, Any]]) -> int:
    for index, row in enumerate(rows):
        if not _is_repeat(row):
            continue
        for first_index, first in enumerate(rows[:index]):
            same = (first["station"], first["climate_day"]) == (row["station"], row["climate_day"])
            if same and not _is_repeat(first):
                growth = row["rss_bytes"] - first["rss_bytes"]
                return max(0, int(growth / (index - first_index)))
    return 0


def project_bench(
    rows: Sequence[Mapping[str, Any]], total: int, total_weight: int = 0
) -> BenchProjection:
    """Project the full set (``total`` station-days, ``total_weight`` bytes) from the bench rows."""
    timed = [r for r in rows if not _is_repeat(r)]
    by_count = sum(r["elapsed_s"] for r in timed) / max(1, len(timed)) * total
    proportional = _proportional(timed, total_weight, by_count)
    affine, n_time_fit = _affine(timed, total, total_weight)
    seconds = max(proportional, affine)
    leak = _leak_rate(rows)
    peak = max((r["peak_rss_bytes"] for r in rows), default=0)
    projected = peak + leak * max(0, total - len(timed))
    resident = [float(r["rss_bytes"]) for r in timed[DIAGNOSTIC_WARMUP_ROWS:]]
    fit = _ols(list(range(len(resident))), resident)
    slope = 0 if fit is None else max(0, int(fit[1]))
    exceeded = seconds > S5_MAX_SECONDS or projected > RSS_ABORT_BYTES
    return BenchProjection(
        seconds, by_count, by_count > S5_MAX_SECONDS, projected, leak, slope,
        len(resident) if fit is not None else 0, n_time_fit, exceeded,
    )  # fmt: skip
