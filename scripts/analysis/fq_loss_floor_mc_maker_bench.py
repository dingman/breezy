"""``--subset-benchmark`` for the maker S3 floor: time one cell, print the full-run projection."""

from __future__ import annotations

import resource
import time
from collections.abc import Callable
from typing import Any

from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    BINDING_REPLICATES,
    OUTER_REPLICATES,
    OUTER_RESAMPLES,
    SEED,
    SWEEP_REPLICATES,
    sweep_mixes,
)

__all__ = ["benchmark"]

_SMALL, _LARGE, _OUTER = 100, 200, (2, 100)


def _rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def benchmark(run_cell: Callable[..., dict[str, Any]]) -> int:
    """Time f=0.5, b=0.80, k=2 at two replicate sizes plus one outer-SE increment."""
    mix = sweep_mixes()[-1]

    def timed(reps: int, resamples: int, outer_reps: int) -> float:
        start = time.monotonic()
        run_cell(
            mix,
            replicates=reps,
            outer_resamples=resamples,
            outer_replicates=outer_reps,
            seed=SEED,
        )
        seconds = time.monotonic() - start
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
        f"measured_rss_mib={_rss_mib():.0f}",
    ]
    print("\n".join(lines), flush=True)
    return 0
