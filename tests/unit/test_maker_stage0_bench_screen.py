"""MAKER-S2 S-5 memory screen: a leak-growth projection that a flat process can pass.

The old screen extrapolated the MEAN per-row ``ru_maxrss`` delta over the remaining rows, but that
delta is a ratchet: the first rows raise the high-water mark once (allocator warm-up, the heaviest
day) and later rows add 0, so a flat process projected ~47 GB. The screen must see leaks only.
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
    rss: float, peak: float, delta: float, elapsed: float = 100.0, **over: Any
) -> dict[str, Any]:
    return {
        "elapsed_s": elapsed,
        "rss_bytes": int(rss * GB),
        "peak_rss_bytes": int(peak * GB),
        "rss_peak_delta_bytes": int(delta * GB),
        **over,
    }


def _flat_rows() -> list[dict[str, Any]]:
    """The 2026-10-14 bench: deltas 1.19/0.94/0/0 GB, end-of-row rss 1.45/1.94/2.13/2.10 GB."""
    return [
        _row(1.45, 1.90, 1.19),
        _row(1.94, 2.84, 0.94),
        _row(2.13, 2.84, 0.0),
        _row(2.10, 2.84, 0.0),
    ]


def test_a_flat_process_does_not_exceed_the_memory_screen() -> None:
    out = project_bench(_flat_rows(), TOTAL)
    assert out.projected_peak_rss_bytes <= RSS_ABORT_BYTES
    assert out.projected_peak_rss_bytes >= int(2.84 * GB)  # never below the observed high-water
    assert out.s5_exceeded is False


def test_a_genuine_leak_exceeds_the_memory_screen() -> None:
    rows = [_row(1.5 + 0.1 * i, 1.6 + 0.1 * i, 0.1) for i in range(4)]
    out = project_bench(rows, TOTAL)
    assert out.projected_peak_rss_bytes > RSS_ABORT_BYTES
    assert out.s5_exceeded is True


def test_a_leak_after_warm_up_is_seen_on_an_eight_row_bench() -> None:
    rows = [_row(1.4, 1.9, 1.2), _row(1.9, 2.8, 0.9)]
    rows += [_row(2.1 + 0.05 * i, 2.8 + 0.05 * i, 0.05) for i in range(6)]
    assert project_bench(rows, TOTAL).s5_exceeded is True


def test_noisy_flat_rows_after_warm_up_stay_under_the_screen() -> None:
    wobble = [2.10, 2.16, 2.08, 2.14, 2.09, 2.13]
    rows = [_row(1.4, 1.9, 1.2), _row(1.9, 2.8, 0.9)] + [_row(w, 2.8, 0.0) for w in wobble]
    assert project_bench(rows, TOTAL).s5_exceeded is False


def test_the_slope_is_floored_at_zero_for_a_shrinking_process() -> None:
    rows = [_row(1.4, 1.9, 1.2), _row(2.5, 3.0, 1.1), _row(2.4, 3.0, 0.0), _row(2.2, 3.0, 0.0)]
    out = project_bench(rows, TOTAL)
    assert out.rss_slope_bytes_per_row == 0
    assert out.projected_peak_rss_bytes == int(3.0 * GB)


def test_too_few_rows_to_fit_a_slope_project_the_observed_peak_only() -> None:
    out = project_bench([_row(1.4, 1.9, 1.2), _row(1.9, 2.8, 0.9)], TOTAL)
    assert out.rss_slope_bytes_per_row == 0
    assert out.projected_peak_rss_bytes == int(2.8 * GB)


def test_projected_total_time_is_the_mean_row_time_times_the_set_size() -> None:
    rows = [_row(1.4, 1.9, 1.2, elapsed=e) for e in (200.0, 300.0, 100.0, 400.0)]
    out = project_bench(rows, TOTAL)
    assert out.projected_total_s == 250.0 * TOTAL
    assert out.s5_exceeded == (250.0 * TOTAL > S5_MAX_SECONDS)  # time alone can fire S-5


def test_either_limit_fires_s5() -> None:
    slow = [_row(2.0, 2.0, 0.0, elapsed=400.0) for _ in range(4)]  # 400 s x 88 > 6 h
    assert project_bench(slow, TOTAL).s5_exceeded is True


def test_write_bench_records_the_new_projection_and_keeps_the_old_keys(tmp_path: Path) -> None:
    cfg = SimpleNamespace(out_dir=tmp_path)
    pre = SimpleNamespace(code_sha="abc")
    timings = [
        {**_row(r["rss_bytes"] / GB, r["peak_rss_bytes"] / GB, 0.0), "station": "SFO",
         "climate_day": f"2026-10-0{i + 1}"}
        for i, r in enumerate(_flat_rows())
    ]  # fmt: skip
    weights = {("SFO", dt.date(2026, 10, i + 1)): 10 for i in range(4)}
    weights.update({("SFO", dt.date(2027, 1, 1) + dt.timedelta(days=i)): 1 for i in range(84)})
    modes._write_bench(cfg, pre, timings, weights, ("primary",))  # type: ignore[arg-type]
    bench = json.loads((tmp_path / "bench.json").read_text())
    assert bench["n_replayable_station_days"] == TOTAL
    assert bench["projected_total_s"] == 100.0 * TOTAL
    assert bench["projected_peak_rss_bytes"] <= RSS_ABORT_BYTES
    assert bench["s5_exceeded"] is False
    assert "rss_slope_bytes_per_row" in bench


@pytest.mark.parametrize("rows", [[], [_row(1.0, 1.0, 0.0)]])
def test_degenerate_row_counts_do_not_raise(rows: list[dict[str, Any]]) -> None:
    out = project_bench(rows, TOTAL)
    assert out.rss_slope_bytes_per_row == 0
