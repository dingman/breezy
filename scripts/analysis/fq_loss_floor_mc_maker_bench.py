"""``--subset-benchmark`` for the maker S3 floor: time one cell, print the full-run projection."""

from __future__ import annotations

import resource
import time
from collections.abc import Callable, Mapping
from typing import Any

from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    BINDING_REPLICATES,
    OUTER_REPLICATES,
    OUTER_RESAMPLES,
    SEED,
    SWEEP_REPLICATES,
    sweep_mixes,
)
from scripts.analysis.fq_loss_floor_mc_maker_verdict import recheck_cell

__all__ = ["benchmark"]

_SMALL, _LARGE, _OUTER = 100, 200, (2, 100)
_RECHECK_SIMS_PER_CELL = 7  # 4 binding rows + 3 G3 deltas
_RECHECK_CELLS = 12  # 6 binding cells x {f_kill, f_pass}; report cells are not re-checked
_FALLBACK = {
    "c": 1.0,
    "t_min": 5,
    "alpha_star": 0.10,
}  # a veto cell has no solved stop; timing only


def _rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def benchmark(
    run_cell: Callable[..., dict[str, Any]],
    recheck: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]] = recheck_cell,
) -> int:
    """Time f=0.5, b=0.80, k=2 at two replicate sizes plus one outer-SE increment."""
    mix = sweep_mixes()[-1]

    cells: list[dict[str, Any]] = []

    def timed(reps: int, resamples: int, outer_reps: int) -> float:
        start = time.monotonic()
        cell = run_cell(
            mix,
            replicates=reps,
            outer_resamples=resamples,
            outer_replicates=outer_reps,
            seed=SEED,
        )
        seconds = time.monotonic() - start
        cells.append(cell)
        print(
            f"benchmark_point replicates={reps} outer={resamples}x{outer_reps} "
            f"seconds={seconds:.2f} rss_mib={_rss_mib():.0f}",
            flush=True,
        )
        return seconds

    t_small, t_large = timed(_SMALL, 0, 0), timed(_LARGE, 0, 0)
    per_rep = max(0.0, (t_large - t_small) / (_LARGE - _SMALL))
    base = max(0.0, t_small - per_rep * _SMALL)
    outer_unit = max(0.0, (timed(_SMALL, *_OUTER) - t_small) / (_OUTER[0] * _OUTER[1]))
    outer = outer_unit * OUTER_RESAMPLES * OUTER_REPLICATES
    probe = cells[0]
    frozen = {key: probe.get(key) or default for key, default in _FALLBACK.items()}
    start = time.monotonic()
    recheck(probe, frozen)
    t_recheck = time.monotonic() - start
    print(f"benchmark_point recheck replicates={_SMALL} seconds={t_recheck:.2f}", flush=True)
    # linear in replicates (an upper bound: the date-template build is a fixed cost)
    recheck_cell_s = t_recheck * BINDING_REPLICATES / _SMALL
    sweep = base + per_rep * SWEEP_REPLICATES  # the sweep runs without the outer SE
    binding = base + per_rep * BINDING_REPLICATES + outer
    lines = [
        "subset_benchmark=1",
        "official_evidence_written=0",
        f"seconds_per_replicate={per_rep:.5f}",
        f"outer_seconds_per_resample_replicate={outer_unit:.6f}",
        f"projected_cell_seconds_sweep={sweep:.0f}",
        f"projected_cell_seconds_binding={binding:.0f}",
        f"projected_sweep_seconds_30_cells={30 * sweep:.0f}",
        f"projected_binding_seconds_18_cells={18 * binding:.0f}",
        f"recheck_seconds_at_{_SMALL}_replicates={t_recheck:.2f}",
        f"projected_recheck_seconds_per_cell_binding={recheck_cell_s:.0f}",
        (f"projected_recheck_seconds_{_RECHECK_CELLS}_cells={_RECHECK_CELLS * recheck_cell_s:.0f}"),
        f"projected_recheck_sims={_RECHECK_CELLS * _RECHECK_SIMS_PER_CELL}",
        f"measured_rss_mib={_rss_mib():.0f}",
    ]
    print("\n".join(lines), flush=True)
    return 0
