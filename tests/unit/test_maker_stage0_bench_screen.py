"""MAKER-S2 S-5 bench screen: repeat-day leak test, by-weight and affine time projections.

The old memory screen extrapolated the MEAN per-row ``ru_maxrss`` delta (a ratchet: warm-up read as
per-row growth, 47.5 GB for a flat process); a slope over run order is confounded by the heaviest
day landing early. The bench now replays its heaviest day again as the last row and the leak rate is
the end-of-row RSS growth across the repeat.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis.maker_stage0_bench_screen import project_bench
from scripts.analysis.maker_stage0_run_types import RSS_ABORT_BYTES, S5_MAX_SECONDS

GB = 10**9
TOTAL = 88


def _row(
    rss: float,
    peak: float,
    *,
    elapsed: float = 100.0,
    weight: int = 10,
    day: str = "2026-10-01",
    repeat: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "station": "SFO",
        "climate_day": day,
        "elapsed_s": elapsed,
        "rss_bytes": int(rss * GB),
        "peak_rss_bytes": int(peak * GB),
        "rss_peak_delta_bytes": 0,
        "catalog_bytes": weight,
    }
    if repeat:
        row["repeat_of_first"] = True
    return row


def _bench(first_rss: float, repeat_rss: float) -> list[dict[str, Any]]:
    """Today's flat shape: the heaviest day is row 2, replayed again as the last row."""
    return [
        _row(1.45, 1.90, day="2026-10-03"),
        _row(first_rss, 2.84, day="2026-10-04"),
        _row(2.13, 2.84, day="2026-10-09"),
        _row(2.10, 2.84, day="2026-10-11"),
        _row(repeat_rss, 2.84, day="2026-10-04", repeat=True),
    ]


def test_a_flat_process_does_not_exceed_the_memory_screen() -> None:
    out = project_bench(_bench(1.94, 1.97), TOTAL)  # +30 MB over 3 rows: allocator noise
    assert out.leak_rate_bytes_per_row == int(0.03 * GB) // 3
    assert int(2.84 * GB) <= out.projected_peak_rss_bytes <= RSS_ABORT_BYTES
    assert out.s5_exceeded is False


def test_a_repeat_row_that_shrinks_gives_a_zero_leak_rate() -> None:
    out = project_bench(_bench(1.94, 1.80), TOTAL)
    assert out.leak_rate_bytes_per_row == 0
    assert out.projected_peak_rss_bytes == int(2.84 * GB)


def test_a_genuine_leak_exceeds_the_memory_screen_over_88_rows() -> None:
    out = project_bench(_bench(1.94, 3.94), TOTAL)  # the repeat row is 2 GB higher
    assert out.leak_rate_bytes_per_row == int(2 * GB) // 3
    assert out.projected_peak_rss_bytes > RSS_ABORT_BYTES
    assert out.s5_exceeded is True


def test_without_a_repeat_row_only_the_observed_peak_is_projected() -> None:
    out = project_bench(_bench(1.94, 9.0)[:4], TOTAL)
    assert out.leak_rate_bytes_per_row == 0
    assert out.projected_peak_rss_bytes == int(2.84 * GB)


def test_the_slope_stays_a_diagnostic_and_never_decides_s5() -> None:
    rows = [_row(1.4 + 0.5 * i, 1.9 + 0.5 * i, day=f"2026-10-0{i + 1}") for i in range(4)]
    out = project_bench(rows, TOTAL)
    assert out.rss_slope_bytes_per_row > 0 and out.n_fit_rows == 2
    assert out.projected_peak_rss_bytes == int(3.4 * GB)  # no repeat row: no leak rate
    assert out.s5_exceeded is False


def test_the_repeat_row_never_counts_in_the_time_figures() -> None:
    rows = _bench(1.94, 1.94)
    rows[-1]["elapsed_s"] = 99_999.0
    out = project_bench(rows, TOTAL)
    assert out.projected_total_s_by_count == 100.0 * TOTAL
    assert out.projected_total_s == pytest.approx(400.0 / 40 * 10 * TOTAL)


def test_equal_weights_give_the_by_count_projection() -> None:
    rows = [_row(2.0, 2.0, day=f"2026-10-0{i + 1}") for i in range(3)]
    out = project_bench(rows, TOTAL, 10 * TOTAL)
    assert out.projected_total_s == pytest.approx(out.projected_total_s_by_count)


def test_heaviest_rows_at_four_times_the_mean_weight_project_a_quarter() -> None:
    rows = [_row(2.0, 2.0, weight=40, day=f"2026-10-0{i + 1}") for i in range(3)]
    out = project_bench(rows, TOTAL, 10 * TOTAL)
    assert out.projected_total_s == pytest.approx(out.projected_total_s_by_count / 4)


@pytest.mark.parametrize("weights, total_weight", [([10, 0, 10], 880), ([10] * 3, 0), ([], 880)])
def test_degenerate_weights_fall_back_to_the_by_count_projection(
    weights: list[int], total_weight: int
) -> None:
    rows = [_row(2.0, 2.0, weight=w, day=f"2026-10-0{i + 1}") for i, w in enumerate(weights)]
    out = project_bench(rows, TOTAL, total_weight)
    assert out.projected_total_s == out.projected_total_s_by_count


def _affine_rows(a: float, b: float, weights: list[int]) -> list[dict[str, Any]]:
    return [
        _row(2.0, 2.0, weight=w, elapsed=a + b * w, day=f"2026-10-0{i + 1}")
        for i, w in enumerate(weights)
    ]


def test_a_fixed_per_day_cost_raises_the_projection_above_proportional() -> None:
    rows = _affine_rows(100.0, 1.0, [100, 200, 300, 400])  # 200 / 400 / 500 / ... seconds
    total_weight = 100 * TOTAL
    out = project_bench(rows, TOTAL, total_weight)
    proportional = (200 + 300 + 400 + 500) / 1000 * total_weight
    assert out.n_time_fit_rows == 4
    assert out.projected_total_s == pytest.approx(100.0 * TOTAL + 1.0 * total_weight)
    assert out.projected_total_s > proportional


def test_the_proportional_figure_wins_when_it_is_larger_than_the_fit() -> None:
    rows = [
        _row(2.0, 2.0, weight=w, elapsed=e, day=f"2026-10-0{i + 1}")
        for i, (w, e) in enumerate([(100, 300.0), (200, 310.0), (300, 320.0), (400, 330.0)])
    ]
    total_weight = 400 * TOTAL  # the set is far heavier per day than the bench
    out = project_bench(rows, TOTAL, total_weight)
    proportional = 1260.0 / 1000 * total_weight
    affine = 290.0 * TOTAL + 0.1 * total_weight
    assert proportional > affine
    assert out.projected_total_s == pytest.approx(proportional)


@pytest.mark.parametrize(
    "a, b", [(-50.0, 3.0), (200.0, -0.5)], ids=["negative intercept", "negative slope"]
)
def test_a_degenerate_fit_uses_the_proportional_figure(a: float, b: float) -> None:
    rows = _affine_rows(a, b, [100, 200, 300, 400])
    total_weight = 100 * TOTAL
    out = project_bench(rows, TOTAL, total_weight)
    elapsed = sum(r["elapsed_s"] for r in rows)
    assert out.n_time_fit_rows == 0
    assert out.projected_total_s == pytest.approx(elapsed / 1000 * total_weight)


def test_fewer_than_four_rows_use_the_proportional_figure() -> None:
    rows = _affine_rows(100.0, 1.0, [100, 200, 300])
    out = project_bench(rows, TOTAL, 100 * TOTAL)
    assert out.n_time_fit_rows == 0


def test_by_count_exceeds_cap_is_reported_and_s5_uses_the_larger_time() -> None:
    rows = [_row(2.0, 2.0, weight=40, elapsed=400.0, day=f"2026-10-0{i + 1}") for i in range(3)]
    out = project_bench(rows, TOTAL, 10 * TOTAL)  # by count 35,200 s; by weight 8,800 s
    assert out.by_count_exceeds_cap is True and out.s5_exceeded is False
    assert project_bench(rows, TOTAL).s5_exceeded is True  # no total weight: by-count fallback
    slow = [_row(2.0, 2.0, elapsed=S5_MAX_SECONDS, day=f"2026-10-0{i + 1}") for i in range(3)]
    assert project_bench(slow, TOTAL, 10 * TOTAL).s5_exceeded is True


def test_write_bench_records_both_projections_and_the_leak_fields(tmp_path: Path) -> None:
    cfg = SimpleNamespace(out_dir=tmp_path)
    pre = SimpleNamespace(code_sha="abc")
    rows = _bench(1.94, 1.97)
    timings = [
        {k: v for k, v in r.items() if k != "catalog_bytes"} | {"station": "SFO"} for r in rows
    ]
    weights = {("SFO", dt.date(2026, 10, d)): 10 for d in (3, 4, 9, 11)}
    weights.update({("SFO", dt.date(2027, 1, 1) + dt.timedelta(days=i)): 10 for i in range(84)})
    modes._write_bench(cfg, pre, timings, weights, ("primary",))  # type: ignore[arg-type]
    bench = json.loads((tmp_path / "bench.json").read_text())
    assert bench["n_replayable_station_days"] == TOTAL
    assert bench["projected_total_s_by_count"] == 100.0 * TOTAL
    assert bench["projected_total_s"] == pytest.approx(100.0 * TOTAL)
    assert bench["by_count_exceeds_cap"] is False and bench["s5_exceeded"] is False
    assert bench["leak_rate_bytes_per_row"] > 0
    assert {"rss_slope_bytes_per_row", "n_fit_rows", "n_time_fit_rows"} <= set(bench)
    assert [r.get("repeat_of_first", False) for r in bench["station_days"]] == [False] * 4 + [True]


@pytest.mark.parametrize("rows", [[], [_row(1.0, 1.0)]])
def test_degenerate_row_counts_do_not_raise(rows: list[dict[str, Any]]) -> None:
    out = project_bench(rows, TOTAL)
    assert out.leak_rate_bytes_per_row == 0
