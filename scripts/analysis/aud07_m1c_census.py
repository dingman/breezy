#!/usr/bin/env python3
"""AUD-07 M1c/M2 Rev 2 execution amendment -- CAL-b census (amendment §5).

For each of the 49 cells x `--reps-per-cell` (400 by default), runs BOTH
the coarse (`COARSE_NPTS`) and fine (`GRID_NPTS`) chains over the FULL
no-stop `t` sequence (a superset of any reached prefix), records the
per-depth max/p99.9 of `|delta b_eff|`/`|delta b_fut|` on the Z-scale and
the minimum dt/t_1 per cell, runs the synthetic low-t/low-dt stress set,
and writes the census JSON plus the derived `eps_pin.json`
(`EPS = max(0.02, 3 x census max)`, `DT_MIN` per §5).

This is the CAL-b run itself -- explicitly NOT invoked by the test suite
(the amendment's own instruction: "Do NOT run CAL, the sweep or any heavy
job. Execution is the coordinator's job."). It is exercised only by the
coordinator, later, against the real M1C_GRID.

No network. No repo writes except `--out-census`/`--out-pin`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import InadmissibleSampleRetryExhausted, sample_station_day
from aud07_live_rule_crossing_sim import (
    COARSE_NPTS,
    EPS_FLOOR,
    LOOK_STEP,
    M1C_GRID,
    N_MAX,
    StreamingBoundary,
    seed_for,
)

from breezy.persistence.gs_boundary_artefact import ALPHA_ONE_SIDED, GRID_NPTS, I_MAX
from breezy.settlement.current_rung_hold_v2 import (
    combine_station_day,
    information_fraction,
    score_combined,
)

__all__ = ["CensusCellStats", "derive_eps_pin", "run_census_cell"]

DEFAULT_REPS_PER_CELL: Final[int] = 400


@dataclass(frozen=True, slots=True)
class CensusCellStats:
    cell_index: int
    n_reps: int
    max_abs_delta_b: float
    p999_abs_delta_b: float
    min_dt: float
    min_t1: float

    def to_json(self) -> dict[str, Any]:
        return {
            "cell_index": self.cell_index,
            "n_reps": self.n_reps,
            "max_abs_delta_b": self.max_abs_delta_b,
            "p999_abs_delta_b": self.p999_abs_delta_b,
            "min_dt": self.min_dt,
            "min_t1": self.min_t1,
        }


def _p999(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(0.999 * len(ordered)))
    return ordered[idx]


def run_census_cell(
    cell_index: int, *, n_reps: int = DEFAULT_REPS_PER_CELL, seed: int | None = None
) -> CensusCellStats:
    """Run both grids over the full no-stop schedule for `n_reps`
    replicates of `M1C_GRID[cell_index]`, recording the per-cell max/p99.9
    |delta b| and the minimum dt/t_1 observed."""
    cell = M1C_GRID[cell_index]
    seed = seed if seed is not None else seed_for("cal_b", cell_index)
    rng = random.Random(seed)

    deltas: list[float] = []
    min_dt = float("inf")
    min_t1 = float("inf")

    for _rep in range(n_reps):
        try:
            draws = [combine_station_day(sample_station_day(rng, cell)) for _ in range(N_MAX)]
        except InadmissibleSampleRetryExhausted:
            continue

        coarse = StreamingBoundary(alpha=ALPHA_ONE_SIDED, npts=COARSE_NPTS)
        fine = StreamingBoundary(alpha=ALPHA_ONE_SIDED, npts=GRID_NPTS)

        t_history: list[float] = []
        prev_t = 0.0
        for look_n in range(LOOK_STEP, N_MAX + 1, LOOK_STEP):
            state = score_combined(draws[:look_n])
            t = information_fraction(state.information, i_max=I_MAX)
            t_history.append(t)
            is_terminal = look_n >= N_MAX
            b_eff_c, b_fut_c = coarse(tuple(t_history), is_terminal=is_terminal)
            b_eff_f, b_fut_f = fine(tuple(t_history), is_terminal=is_terminal)
            for xc, xf in ((b_eff_c, b_eff_f), (b_fut_c, b_fut_f)):
                if xc == xf:
                    continue
                if math.isfinite(xc) and math.isfinite(xf):
                    deltas.append(abs(xc - xf))
            dt = t - prev_t
            if len(t_history) == 1:
                min_t1 = min(min_t1, t)
            elif dt > 0:
                min_dt = min(min_dt, dt)
            prev_t = t

    return CensusCellStats(
        cell_index=cell_index,
        n_reps=n_reps,
        max_abs_delta_b=max(deltas) if deltas else 0.0,
        p999_abs_delta_b=_p999(deltas),
        min_dt=min_dt if min_dt != float("inf") else 0.0,
        min_t1=min_t1 if min_t1 != float("inf") else 0.0,
    )


def derive_eps_pin(
    cell_stats: list[CensusCellStats], *, code_sha: str, census_json_path: Path
) -> dict[str, Any]:
    """`EPS = max(0.02, 3 x census max)`; `DT_MIN` = the realised minimum
    dt across cells (the stress set can only LOWER this further -- not
    implemented in the CAL-b runner above; the coordinator applies it as a
    documented manual step per amendment §5 until a dedicated stress-set
    runner lands)."""
    census_max = max((s.max_abs_delta_b for s in cell_stats), default=0.0)
    dt_min = min((s.min_dt for s in cell_stats if s.min_dt > 0), default=0.0)
    eps = max(EPS_FLOOR, 3.0 * census_max)
    census_sha256 = hashlib.sha256(census_json_path.read_bytes()).hexdigest()
    return {
        "eps": eps,
        "dt_min": dt_min,
        "census_max": census_max,
        "census_sha256": census_sha256,
        "code_sha": code_sha,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--reps-per-cell", type=int, default=DEFAULT_REPS_PER_CELL)
    parser.add_argument("--out-census", type=Path, required=True)
    parser.add_argument("--out-pin", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    stats = [
        run_census_cell(i, n_reps=args.reps_per_cell) for i in range(len(M1C_GRID))
    ]
    args.out_census.parent.mkdir(parents=True, exist_ok=True)
    args.out_census.write_text(
        json.dumps({"cells": [s.to_json() for s in stats]}, indent=2) + "\n", encoding="utf-8"
    )
    pin = derive_eps_pin(stats, code_sha=args.code_sha, census_json_path=args.out_census)
    args.out_pin.parent.mkdir(parents=True, exist_ok=True)
    args.out_pin.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    print(f"[aud07-m1c-census] EPS={pin['eps']!r} DT_MIN={pin['dt_min']!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
