#!/usr/bin/env python3
"""AUD-07 M1c/M2 Rev 2 execution amendment -- CAL-b census (amendment §5).

Three chunkable, resumable modes (2026-09-25 fix: the original all-in-one
invocation ran all 49 cells x 400 reps SERIALLY in one process -- about
15h wall time, fitting no schedule segment (plan §4.4 budgets CAL-b at
about 15.4 WORKER-h split across P=8 workers and segments C and A), and a
`RuntimeMaxSec` kill lost the whole run. The all-in-one CLI is REMOVED
(nothing depended on it -- CAL had not yet run); its three steps are now
separately chunkable and idempotently resumable, reusing
`aud07_live_rule_crossing_sim`'s own resume-key/killed-write machinery and
`aud07_m1c_merge`'s own dedupe/stage-mismatch machinery verbatim, never
forked):

- `--stage cal_b --cells i:j --reps-per-cell N --out <path>`: per-cell mode.
  One row per cell (per-depth `|delta b|` stats, min dt, min t_1), stamped
  with the SAME resume-key fields `run_chunk` uses (`stage`, `cell_index`,
  `substream`, `seed`, `n_reps`, `boundary_mode`, `coarse_npts`,
  `eps_pin_sha256`, `code_sha`, `numpy_version`, `scipy_version`) so
  `_load_done_cells`/`_resume_key`/`_read_and_repair` apply unmodified.
- `--stress-only --out <path>`: the synthetic low-t/low-dt stress set
  (amendment §5 "Stress set") -- a cheap, single-row MEASUREMENT (no eps
  dependency: it records raw per-`(t1, dt)` `|delta b|`; the eps-dependent
  "is this dt safe" derivation happens in `derive_eps_pin`, once the real
  eps is known, avoiding measure-before-you-know-eps circularity).
- `--derive-pin --in <cal_b dir> --out-census <path> --out-pin <path>`:
  aggregates every `*.jsonl` under `--in` (via
  `aud07_m1c_merge.load_stage_rows`/`dedupe_rows`), requires EXACTLY the
  49 cells (0..48) plus exactly one stress row, a single `code_sha`, and
  no conflicts -- raising `MergeStageError`/`MergeConflictError`/
  `MergeCoverageError` otherwise. Derives EPS/DT_MIN exactly as before.

The snapshot import assertion (amendment §3.2) applies to every mode that
runs real computation (per-cell, stress-only); `--derive-pin` is pure
post-processing of already-written files and is exempt, matching
`aud07_live_rule_crossing_sim.py`'s own `smoke`-stage exemption pattern.

Explicitly NOT invoked by the test suite at production scale (the
amendment's own instruction: "Do NOT run CAL, the sweep or any heavy job.
Execution is the coordinator's job."). Exercised here only at tiny
`--reps-per-cell` counts, and by the coordinator, later, for real.

No network. No repo writes except `--out`/`--out-census`/`--out-pin`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import scipy

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
    ResumeKeyConflictError,
    StreamingBoundary,
    _assert_snapshot_imports,
    _load_done_cells,
    seed_for,
)
from aud07_m1c_merge import MergeCoverageError, MergeStageError, dedupe_rows, load_stage_rows

from breezy.persistence.gs_boundary_artefact import ALPHA_ONE_SIDED, GRID_NPTS, I_MAX
from breezy.settlement.current_rung_hold_v2 import (
    combine_station_day,
    information_fraction,
    score_combined,
)

__all__ = [
    "STRESS_CELL_INDEX",
    "CensusCellStats",
    "derive_eps_pin",
    "run_census_cell",
    "run_census_chunk",
    "run_derive_pin",
    "run_stress_chunk",
    "run_stress_set",
]

DEFAULT_REPS_PER_CELL: Final[int] = 400
CAL_B_STAGE: Final[str] = "cal_b"

#: The stress row's identity in the shared resume-key scheme -- a cell
#: index no real cell can ever have.
STRESS_CELL_INDEX: Final[int] = -1

#: Stress-set grid sizes (amendment §5 "Stress set"): t_1 in
#: [0.5 x min observed, 0.15], dt on a log grid down to 1e-4.
_STRESS_T1_POINTS: Final[int] = 6
_STRESS_DT_POINTS: Final[int] = 8
_STRESS_DT_MIN: Final[float] = 1e-4
_STRESS_DT_MAX: Final[float] = 0.05


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
    seed = seed if seed is not None else seed_for(CAL_B_STAGE, cell_index)
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


def _resume_row_shell(
    *, stage: str, cell_index: int, seed: int, n_reps: int | None, code_sha: str, boundary_mode: str
) -> dict[str, Any]:
    """The shared resume-key fields, stamped on every cal_b row (cell or
    stress) so `aud07_live_rule_crossing_sim`'s own
    `_load_done_cells`/`_resume_key`/`_read_and_repair` apply UNMODIFIED --
    never forked."""
    return {
        "stage": stage,
        "cell_index": cell_index,
        "substream": None,
        "seed": seed,
        "n_reps": n_reps,
        "boundary_mode": boundary_mode,
        "coarse_npts": COARSE_NPTS,
        "eps_pin_sha256": None,
        "code_sha": code_sha,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
    }


def run_census_chunk(
    from_idx: int,
    to_idx: int,
    *,
    out_path: Path,
    reps_per_cell: int,
    code_sha: str,
    stage: str = CAL_B_STAGE,
) -> None:
    """Append one JSONL row per completed cell in `M1C_GRID[from_idx:to_idx]`,
    idempotent and resumable via the SAME resume-key scheme `run_chunk`
    uses (amendment §3.3) -- reused, not forked."""
    done = _load_done_cells(out_path, stage=stage)

    with out_path.open("a", encoding="utf-8") as f:
        for cell_index in range(from_idx, to_idx):
            seed = seed_for(stage, cell_index)
            shell = _resume_row_shell(
                stage=stage,
                cell_index=cell_index,
                seed=seed,
                n_reps=reps_per_cell,
                code_sha=code_sha,
                boundary_mode="census",
            )
            this_key = tuple(shell[field] for field in _RESUME_KEY_ORDER)
            existing_key = done.get(cell_index)
            if existing_key is not None:
                if existing_key == this_key:
                    continue
                raise ResumeKeyConflictError(
                    f"cell {cell_index} in {out_path} already has a row with a "
                    f"DIFFERENT resume key: existing={existing_key!r} new={this_key!r}"
                )

            stats = run_census_cell(cell_index, n_reps=reps_per_cell, seed=seed)
            row = {**shell, **stats.to_json()}
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())


#: Mirrors `aud07_live_rule_crossing_sim._RESUME_KEY_FIELDS` exactly (same
#: field NAMES, same order) -- imported values, not re-derived, so a
#: resume key built here is directly comparable to one `_load_done_cells`
#: extracts from disk.
_RESUME_KEY_ORDER: Final[tuple[str, ...]] = (
    "stage",
    "cell_index",
    "substream",
    "seed",
    "n_reps",
    "boundary_mode",
    "coarse_npts",
    "eps_pin_sha256",
    "code_sha",
    "numpy_version",
    "scipy_version",
)


def _lin_grid(lo: float, hi: float, n: int) -> list[float]:
    if n <= 1:
        return [lo]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _log_grid(lo: float, hi: float, n: int) -> list[float]:
    if lo <= 0 or hi <= 0:
        raise ValueError(f"_log_grid requires lo, hi > 0: lo={lo!r} hi={hi!r}")
    if n <= 1:
        return [lo]
    log_lo, log_hi = math.log10(lo), math.log10(hi)
    return [10 ** (log_lo + (log_hi - log_lo) * i / (n - 1)) for i in range(n)]


def run_stress_set(*, min_observed_t1: float) -> dict[str, Any]:
    """Synthetic low-t/low-dt stress set (amendment §5 "Stress set"):
    `t_1` in `[0.5 x min_observed_t1, 0.15]`, `dt` on a log grid down to
    `1e-4`. Needs NO real station-day draws: the coarse/fine boundary
    comparison depends only on the synthetic `t_history` fed to
    `StreamingBoundary`, never on `S` -- cheap, unlike the CAL-b census's
    real Monte-Carlo replicates.

    A pure MEASUREMENT: records the per-`(t1, dt)` max `|delta b|` only.
    Which dt is "safe" depends on eps, not yet known when this runs
    standalone (`--stress-only` has no census dependency) -- that
    derivation happens in `derive_eps_pin`, once eps is known."""
    t1_lo = 0.5 * min_observed_t1
    t1_grid = _lin_grid(min(t1_lo, 0.15), 0.15, _STRESS_T1_POINTS)
    dt_grid = _log_grid(_STRESS_DT_MIN, _STRESS_DT_MAX, _STRESS_DT_POINTS)

    results: list[dict[str, float]] = []

    for t1 in t1_grid:
        for dt in dt_grid:
            t2 = t1 + dt
            if t2 > 1.0:
                continue
            coarse = StreamingBoundary(alpha=ALPHA_ONE_SIDED, npts=COARSE_NPTS)
            fine = StreamingBoundary(alpha=ALPHA_ONE_SIDED, npts=GRID_NPTS)
            max_delta = 0.0
            t_history: list[float] = []
            for i, t in enumerate((t1, t2)):
                t_history.append(t)
                is_terminal = i == 1
                b_eff_c, b_fut_c = coarse(tuple(t_history), is_terminal=is_terminal)
                b_eff_f, b_fut_f = fine(tuple(t_history), is_terminal=is_terminal)
                for xc, xf in ((b_eff_c, b_eff_f), (b_fut_c, b_fut_f)):
                    if xc == xf:
                        continue
                    if math.isfinite(xc) and math.isfinite(xf):
                        max_delta = max(max_delta, abs(xc - xf))
            results.append({"t1": t1, "dt": dt, "max_abs_delta_b": max_delta})

    return {"results": results}


def _min_observed_t1_from_dir(in_dir: Path | None, *, stage: str = CAL_B_STAGE) -> float:
    """The realised minimum `t_1` across whatever cal_b cell rows are
    already on disk under `in_dir` -- falls back to the amendment's own
    conservative upper bound (0.15) if none are available yet (a
    stand-alone `--stress-only` run needs no prior census)."""
    if in_dir is None or not in_dir.exists():
        return 0.15
    t1s: list[float] = []
    for path in sorted(in_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("stage") != stage or row.get("cell_index", STRESS_CELL_INDEX) < 0:
                continue
            min_t1 = row.get("min_t1")
            if isinstance(min_t1, (int, float)) and min_t1 > 0:
                t1s.append(float(min_t1))
    return min(t1s) if t1s else 0.15


def run_stress_chunk(
    *, out_path: Path, code_sha: str, in_dir: Path | None = None, stage: str = CAL_B_STAGE
) -> None:
    """Idempotent single-row stress-set run, using the SAME resume-key
    scheme as `run_census_chunk` (`STRESS_CELL_INDEX` stands in for the
    per-cell `cell_index`)."""
    done = _load_done_cells(out_path, stage=stage)
    seed = seed_for(stage, STRESS_CELL_INDEX)
    shell = _resume_row_shell(
        stage=stage,
        cell_index=STRESS_CELL_INDEX,
        seed=seed,
        n_reps=None,
        code_sha=code_sha,
        boundary_mode="stress",
    )
    this_key = tuple(shell[field] for field in _RESUME_KEY_ORDER)
    existing_key = done.get(STRESS_CELL_INDEX)
    if existing_key is not None:
        if existing_key == this_key:
            return
        raise ResumeKeyConflictError(
            f"the stress row in {out_path} already has a DIFFERENT resume "
            f"key: existing={existing_key!r} new={this_key!r}"
        )

    min_observed_t1 = _min_observed_t1_from_dir(in_dir, stage=stage)
    stress = run_stress_set(min_observed_t1=min_observed_t1)
    row = {**shell, "min_observed_t1": min_observed_t1, "results": stress["results"]}
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def derive_eps_pin(
    cell_stats: list[CensusCellStats],
    *,
    code_sha: str,
    census_json_path: Path,
    stress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`EPS = max(0.02, 3 x census max)`. `DT_MIN` = the realised minimum
    dt across cells, further lowered (never raised) by the stress set's
    raw `results`, filtered by THIS eps at derivation time (amendment §5:
    "The stress set can only lower DT_MIN, and only where it shows
    Δb ≤ EPS/3")."""
    census_max = max((s.max_abs_delta_b for s in cell_stats), default=0.0)
    dt_min = min((s.min_dt for s in cell_stats if s.min_dt > 0), default=0.0)
    eps = max(EPS_FLOOR, 3.0 * census_max)

    if stress is not None:
        safe_dts = [
            row["dt"] for row in stress.get("results", []) if row["max_abs_delta_b"] <= eps / 3.0
        ]
        if safe_dts:
            stress_dt = min(safe_dts)
            dt_min = min(dt_min, stress_dt) if dt_min > 0 else stress_dt

    census_sha256 = hashlib.sha256(census_json_path.read_bytes()).hexdigest()
    return {
        "eps": eps,
        "dt_min": dt_min,
        "census_max": census_max,
        "census_sha256": census_sha256,
        "code_sha": code_sha,
    }


def _collect_cal_b_rows(
    in_dir: Path, *, stage: str = CAL_B_STAGE
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate every `*.jsonl` under `in_dir` (via
    `aud07_m1c_merge.load_stage_rows`/`dedupe_rows` -- reused verbatim,
    never forked): requires EXACTLY the 49 cells (0..48) plus exactly one
    stress row, and a single `code_sha`."""
    paths = sorted(in_dir.glob("*.jsonl"))
    if not paths:
        raise MergeCoverageError(f"no .jsonl files found under {in_dir}")

    rows = load_stage_rows(paths, stage=stage)  # raises MergeStageError on a foreign-stage row.
    rows = dedupe_rows(rows)  # raises MergeConflictError on a conflicting duplicate.

    shas = {row.get("code_sha") for row in rows}
    if len(shas) > 1:
        raise MergeStageError(
            f"multiple distinct code_sha values under {in_dir}: {sorted(map(repr, shas))}"
        )

    cell_rows = [row for row in rows if row["cell_index"] >= 0]
    stress_rows = [row for row in rows if row["cell_index"] < 0]

    expected_cells = set(range(len(M1C_GRID)))
    got_cells = {row["cell_index"] for row in cell_rows}
    missing = expected_cells - got_cells
    if missing:
        raise MergeCoverageError(f"cal_b census missing cell(s): {sorted(missing)}")
    extra = got_cells - expected_cells
    if extra:
        raise MergeCoverageError(f"cal_b census has unexpected cell(s): {sorted(extra)}")
    if len(stress_rows) != 1:
        raise MergeCoverageError(
            f"cal_b census requires exactly 1 stress row, found {len(stress_rows)} under {in_dir}"
        )

    return cell_rows, stress_rows[0]


def run_derive_pin(*, in_dir: Path, out_census: Path, out_pin: Path) -> dict[str, Any]:
    """`--derive-pin`: pure post-processing, no new computation -- exempt
    from the snapshot-import assertion (like `main()`'s own `smoke`
    exemption)."""
    cell_rows, stress_row = _collect_cal_b_rows(in_dir)
    code_sha = cell_rows[0]["code_sha"]
    stats = [
        CensusCellStats(
            cell_index=row["cell_index"],
            n_reps=row["n_reps"],
            max_abs_delta_b=row["max_abs_delta_b"],
            p999_abs_delta_b=row["p999_abs_delta_b"],
            min_dt=row["min_dt"],
            min_t1=row["min_t1"],
        )
        for row in sorted(cell_rows, key=lambda r: r["cell_index"])
    ]
    stress = {"results": stress_row["results"]}

    out_census.parent.mkdir(parents=True, exist_ok=True)
    out_census.write_text(
        json.dumps({"cells": [s.to_json() for s in stats], "stress": stress}, indent=2) + "\n",
        encoding="utf-8",
    )
    pin = derive_eps_pin(stats, code_sha=code_sha, census_json_path=out_census, stress=stress)
    out_pin.parent.mkdir(parents=True, exist_ok=True)
    out_pin.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    return pin


def _parse_cells_arg(value: str) -> tuple[int, int]:
    from_str, to_str = value.split(":")
    return int(from_str), int(to_str)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cells", type=_parse_cells_arg, help="FROM:TO -- per-cell census mode")
    mode.add_argument("--stress-only", action="store_true")
    mode.add_argument("--derive-pin", action="store_true")

    parser.add_argument("--stage", default=CAL_B_STAGE)
    parser.add_argument("--code-sha")
    parser.add_argument("--reps-per-cell", type=int, default=DEFAULT_REPS_PER_CELL)
    parser.add_argument("--out", type=Path, help="per-cell / stress-only mode")
    parser.add_argument(
        "--in", dest="in_dir", type=Path, help="stress-only (optional) / derive-pin"
    )
    parser.add_argument("--out-census", type=Path)
    parser.add_argument("--out-pin", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.derive_pin:
        if args.in_dir is None or args.out_census is None or args.out_pin is None:
            raise ValueError("--derive-pin requires --in, --out-census and --out-pin")
        pin = run_derive_pin(in_dir=args.in_dir, out_census=args.out_census, out_pin=args.out_pin)
        print(f"[aud07-m1c-census] EPS={pin['eps']!r} DT_MIN={pin['dt_min']!r}", file=sys.stderr)
        return 0

    if args.code_sha is None or args.out is None:
        raise ValueError("--code-sha and --out are required")
    _assert_snapshot_imports(_REPO_ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.stress_only:
        run_stress_chunk(
            out_path=args.out, code_sha=args.code_sha, in_dir=args.in_dir, stage=args.stage
        )
        return 0

    from_idx, to_idx = args.cells
    run_census_chunk(
        from_idx, to_idx,
        out_path=args.out, reps_per_cell=args.reps_per_cell,
        code_sha=args.code_sha, stage=args.stage,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
