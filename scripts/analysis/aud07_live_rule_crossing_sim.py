#!/usr/bin/env python3
"""AUD-07 amendment Stage M1c -- live-rule mixed-side crossing-rate harness.

`docs/plans/backlog/AUDIT_2026-09-21/AUD-07-AMENDMENT-2026-09-25.md` (Rev
2.1, APPROVED) SS4 "M1c: harness". Measures the realised one-sided efficacy
crossing rate of the LIVE PREREG v2 sequential rule
(`scripts/analysis/family_tally_v2.run_sequential_looks`) over mixed-side
q_max=1 station-days, replaying the loop VERBATIM -- including the terminal
stop at `I >= I_max` -- unlike both prior harnesses (AUD-06a's sweep and the
`test_multi_position_validation_2026_09_14.py` strict-xfail), which
interpolate the 16-row `reference_table` and never stop (L-40 amendment
(ii), `docs/core/LESSONS.md:1401`).

**Reuses, never re-implements:**
- `sample_station_day`/`ADMISSIBLE_K_SIDE_MIX`/`DISPERSION_GRID`/`CellSpec`
  (`aud06a_qty_envelope_sweep.py`), including its NO-`held` fix.
- `combine_station_day` (`breezy.settlement.current_rung_hold_v2`), the
  exact mutual-exclusivity variance.
- `run_sequential_looks` (`family_tally_v2.py`, AUD-07 Stage M1b
  extraction), imported by `importlib` module-spec loading -- the script
  carries no package `__init__` and this avoids the CLI's own `__main__`
  side effects (mirrors `test_family_tally_v2_look_loop_golden.py`).

**Streaming boundary (L-40 amendment (iii)):** `StreamingBoundary` is a
per-replicate, stateful reimplementation of
`BoundaryArtefact.boundary_for`'s own joint-density recursion. It imports
the artefact's OWN `_look_step`/`_one_sided_spend` primitives (never
re-deriving the spending function) and carries `(grid, dens, prev_t)`
forward across looks within one replicate, so a 20000-replicate Monte-Carlo
never pays `boundary_for`'s from-scratch-every-call cost. Proven equal to
`boundary_for` to 1e-12 at the full grid and to 1e-3 at a reduced grid
(`tests/unit/test_aud07_streaming_boundary.py`, tests 4a/4b) before this
module's Monte-Carlo numbers are cited anywhere.

**Neutral inputs (L-41):** `total_pnl = residual = Decimal(0)` for every
look, so `LOSS_STOP` can never fire and the tally's own `verdict` string is
architecturally unable to report `SURVIVE` (`look_verdict`/`terminal_look`
both gate `SURVIVE` on `total_pnl > 0`, which `0 > 0` never satisfies). The
efficacy-crossing count is therefore taken directly off each `LookRecord`'s
own `state.s >= b_eff` field -- the pure LD-OBF boundary-crossing event --
never off the `verdict` literal, which this neutral wiring intentionally
strips of the pnl/cell_dead business overlay (`cell_dead = False`,
`structural_fired = False`, `truncation = None` complete the neutral set).

**Grid (amendment SS4 M1c "Grid"):** the 16 mixed q_max=1 cells (8
dispersion classes x k in {2, 3}, `mixed` undefined at k=1), their 32
matched all_yes/all_no cells in the same (dispersion, k) strata, and the
one all_yes k=1 control -- 49 cells total, canonical order fixed so a
cell's index never moves (mirrors `aud06a_qty_envelope_sweep.ALL_CELLS`).

No network. No repo writes except `--out`.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import (
    ADMISSIBLE_K_SIDE_MIX,
    DISPERSION_GRID,
    CellSpec,
    DispersionSpec,
    InadmissibleSampleRetryExhausted,
    clopper_pearson_lower,
    clopper_pearson_upper,
    sample_station_day,
)

from breezy.persistence.gs_boundary_artefact import (
    ALPHA_ONE_SIDED,
    GRID_HALFWIDTH_SD,
    GRID_NPTS,
    I_MAX,
    BoundaryArtefact,
    SpendingSpec,
    _look_step,
    _one_sided_spend,
)
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    TruncationReason,
    combine_station_day,
)

__all__ = [
    "ALL_YES_K1_CONTROL",
    "LOOK_STEP",
    "M1C_GRID",
    "N_MAX",
    "REDUCED_NPTS",
    "SEED_BASE",
    "M1cCellResult",
    "StreamingBoundary",
    "clopper_pearson_lower",
    "clopper_pearson_upper",
    "m1c_grid",
    "run_cell",
    "run_sequential_looks",
    "seed_for_cell_index",
]


def _load_run_sequential_looks() -> Any:
    """Import `family_tally_v2.py` via its module spec (no package
    `__init__`), exactly as `test_family_tally_v2_look_loop_golden.py`
    does, and return its live `run_sequential_looks` -- the AUD-07 Stage
    M1b extraction this harness reuses verbatim. Module-spec loading (never
    a bare `import family_tally_v2`) avoids the script's own `__main__`
    side effects."""
    import importlib.util

    path = _SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2_aud07_m1c", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run_sequential_looks


run_sequential_looks: Any = _load_run_sequential_looks()

# --- Live schedule, pinned (never re-derived; matches
# `deploy/families/gs_boundary_pm_us_crh_v2.json`'s `n_max`/`look_step`,
# inputs_sha256 471fd8a7ea78...) -----------------------------------------
N_MAX: Final[int] = 160
LOOK_STEP: Final[int] = 10

#: MEASURED LIMIT (calibration, 2026-09-25, not re-derived at import time):
#: `StreamingBoundary`'s fixed-grid convolution converges cleanly for a
#: SINGLE look (`npts=601` reproduces `boundary_for` to <9e-4 across 40
#: random first-look histories over `t in [0.15, 1.0]`) but does NOT hold
#: 1e-3 across a MULTI-look chain even close to the full grid -- measured
#: 2-look-chain worst error at `npts=1301` was ~2.5e-3, and at `npts=1981`
#: (16-look chains) was ~4e-3. This is a property of the recursive
#: convolution's successive re-gridding (each look's density is rebuilt on
#: a fresh `np.linspace` grid via `_convolve_density`'s trapezoid integral
#: over the PRIOR grid), not a defect in this reimplementation -- test 4a
#: proves bit-identical output at matching `npts`. Consequently
#: `REDUCED_NPTS` is proven (test 4b) ONLY for single-look histories and is
#: NOT the default `npts` `run_cell` uses for its multi-look Monte-Carlo
#: replay (`run_cell` defaults to the full `GRID_NPTS`, below) -- it is
#: exposed for a future single-look-dominant use case, not today's bulk
#: sweep. See the amendment's own "Reduced-grid error" risk mitigation
#: (spot-check + full-grid re-run if it disagrees): the honest response to
#: this measurement IS to fall back to the full grid, not to relax the
#: test's own 1e-3 bound.
REDUCED_NPTS: Final[int] = 601

SEED_BASE: Final[int] = 20260925_000


# ---------------------------------------------------------------------------
# Streaming boundary (L-40 amendment (iii))
# ---------------------------------------------------------------------------
class StreamingBoundary:
    """A per-replicate streaming reimplementation of
    `BoundaryArtefact.boundary_for`'s own joint-density recursion.

    Carries `(grid, dens, prev_t)` forward across looks within ONE
    replicate's history -- `boundary_for` itself recomputes from `t=0` on
    every call, which a 20000-replicate x 16-look Monte-Carlo cannot
    afford. Imports the artefact's OWN `_look_step`/`_one_sided_spend`
    primitives (`breezy.persistence.gs_boundary_artefact`); never
    re-derives the spending function (L-40 amendment (iii), `docs/core/
    LESSONS.md:1403`).

    Non-terminal target: `spend(t) - spend(prev_t)` -- the identical
    subtraction `_iter_boundary_looks` performs. Terminal target: `alpha -
    spend(prev_t)`, via a `_look_step` call from the SAME prior `(grid,
    dens, prev_t)` state (never from a hypothetical intermediate
    non-terminal state). A tie (`t == prev_t`) is not special-cased here:
    it flows into `_look_step`'s own `dt == 0` branch, which returns the
    degenerate `(+inf, -inf)` pair unchanged.

    Every call must extend the previously committed `t_history` by EXACTLY
    one element -- checked explicitly, a wiring defect otherwise (a fresh
    instance is required per Monte-Carlo replicate; state is never shared
    across replicates).
    """

    def __init__(
        self,
        *,
        alpha: float = ALPHA_ONE_SIDED,
        npts: int = GRID_NPTS,
        halfwidth_sd: float = GRID_HALFWIDTH_SD,
    ) -> None:
        self.alpha = alpha
        self.npts = npts
        self.halfwidth_sd = halfwidth_sd
        self._grid: NDArray[np.float64] | None = None
        self._dens: NDArray[np.float64] | None = None
        self._prev_t = 0.0
        self._committed_looks = 0

    def __call__(
        self, t_history: Sequence[float], *, is_terminal: bool
    ) -> tuple[float, float]:
        t_history = tuple(t_history)
        if len(t_history) != self._committed_looks + 1:
            raise ValueError(
                "StreamingBoundary requires t_history to extend the previously "
                f"committed history by exactly one look: had "
                f"{self._committed_looks} committed look(s), got a t_history of "
                f"length {len(t_history)} (a wiring defect -- one fresh "
                "StreamingBoundary instance per Monte-Carlo replicate)"
            )
        t = t_history[-1]
        prev_t = self._prev_t
        if is_terminal:
            target = self.alpha - _one_sided_spend(prev_t, self.alpha)
        else:
            target = _one_sided_spend(t, self.alpha) - _one_sided_spend(prev_t, self.alpha)
        b_eff, b_fut, new_grid, new_dens, new_prev_t = _look_step(
            t, prev_t, self._grid, self._dens, target, self.npts, self.halfwidth_sd
        )
        self._grid, self._dens, self._prev_t = new_grid, new_dens, new_prev_t
        self._committed_looks += 1
        z_scale = math.sqrt(t)
        return b_eff / z_scale, b_fut / z_scale


def _synthetic_artefact(
    *, alpha: float, i_max: float, n_max: int, look_step: int
) -> BoundaryArtefact:
    """Byte-identical shape to `test_family_tally_v2_look_loop_golden.py`'s
    own `_synthetic_artefact` -- never file-loaded, so `run_sequential_looks`
    exercises the real schedule fields (`i_max`, `spending.n_max`,
    `spending.look_step`) without `load_boundary_artefact`'s reference-table
    replay. `boundary_for` itself is never called: `StreamingBoundary` is
    passed as the separate `boundary_fn` parameter."""
    return BoundaryArtefact(
        inputs_sha256="0" * 64,
        i_max=i_max,
        alpha_one_sided=alpha,
        spending=SpendingSpec(
            spending_id="aud07_m1c_synthetic",
            alpha_one_sided=alpha,
            n_max=n_max,
            look_step=look_step,
        ),
        reference_rows=(),
    )


# ---------------------------------------------------------------------------
# Grid (amendment SS4 M1c "Grid")
# ---------------------------------------------------------------------------
_MIXED_K_VALUES: Final[tuple[int, ...]] = tuple(
    k for k, side_mix in ADMISSIBLE_K_SIDE_MIX if side_mix == "mixed"
)


def _mixed_cells() -> tuple[CellSpec, ...]:
    """The 16 mixed q_max=1 cells: the 8 dispersion classes x the mixed-
    admissible k values (k=1 is undefined for `mixed`,
    `ADMISSIBLE_K_SIDE_MIX` already excludes it)."""
    return tuple(
        CellSpec(q_max=1, dispersion=dispersion, k=k, side_mix="mixed")
        for dispersion in DISPERSION_GRID
        for k in _MIXED_K_VALUES
    )


def _matched_same_side_cells(mixed_cells: Sequence[CellSpec]) -> tuple[CellSpec, ...]:
    """The matched all_yes/all_no q_max=1 cells in the SAME (dispersion, k)
    strata as `mixed_cells`."""
    cells: list[CellSpec] = []
    for mixed in mixed_cells:
        cells.append(CellSpec(q_max=1, dispersion=mixed.dispersion, k=mixed.k, side_mix="all_yes"))
        cells.append(CellSpec(q_max=1, dispersion=mixed.dispersion, k=mixed.k, side_mix="all_no"))
    return tuple(cells)


#: At `q_max=1` every dispersion class produces `qty=1` for a single leg
#: (`_qty_for_leg` caps at `q_max`), so the control is unambiguous
#: regardless of which dispersion label is used; `all_equal` is canonical.
ALL_YES_K1_CONTROL: Final[CellSpec] = CellSpec(
    q_max=1, dispersion=DispersionSpec("all_equal"), k=1, side_mix="all_yes"
)


def m1c_grid() -> tuple[CellSpec, ...]:
    """The full 49-cell M1c grid, canonical order fixed so a cell's index
    never moves (mirrors `aud06a_qty_envelope_sweep.enumerate_cells`)."""
    mixed = _mixed_cells()
    matched = _matched_same_side_cells(mixed)
    return (*mixed, *matched, ALL_YES_K1_CONTROL)


M1C_GRID: Final[tuple[CellSpec, ...]] = m1c_grid()
assert len(M1C_GRID) == 49, f"expected 49 M1c cells, got {len(M1C_GRID)}"


def seed_for_cell_index(cell_index: int) -> int:
    return SEED_BASE + cell_index


# ---------------------------------------------------------------------------
# One cell's Monte-Carlo, replaying the live rule
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class M1cCellResult:
    cell_index: int
    label: str
    side_mix: str
    k: int
    dispersion: str
    r: int | None
    seed: int
    n_reps: int
    npts: int
    crossing_count: int
    crossing_rate: float
    cp_upper: float
    cp_lower: float
    mean_s_terminal: float
    var_s_terminal: float
    mean_look_count: float
    loss_stop_count: int
    skipped: bool = False
    skip_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "cell_index": self.cell_index,
            "label": self.label,
            "side_mix": self.side_mix,
            "k": self.k,
            "dispersion": self.dispersion,
            "r": self.r,
            "seed": self.seed,
            "n_reps": self.n_reps,
            "npts": self.npts,
            "crossing_count": self.crossing_count,
            "crossing_rate": self.crossing_rate,
            "cp_upper": self.cp_upper,
            "cp_lower": self.cp_lower,
            "mean_s_terminal": self.mean_s_terminal,
            "var_s_terminal": self.var_s_terminal,
            "mean_look_count": self.mean_look_count,
            "loss_stop_count": self.loss_stop_count,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


def _feasibility_check(cell: CellSpec, *, seed: int) -> str | None:
    """One cheap admissibility probe before committing `n_reps` full
    replays (mirrors `aud06a_qty_envelope_sweep._feasibility_check`)."""
    probe_rng = random.Random(seed)
    try:
        for _ in range(5):
            sample_station_day(probe_rng, cell)
    except InadmissibleSampleRetryExhausted as exc:
        return str(exc)
    return None


def _skipped_result(
    cell: CellSpec, *, cell_index: int, seed: int, n_reps: int, npts: int, reason: str
) -> M1cCellResult:
    return M1cCellResult(
        cell_index=cell_index,
        label=cell.label,
        side_mix=cell.side_mix,
        k=cell.k,
        dispersion=cell.dispersion.label,
        r=cell.dispersion.r,
        seed=seed,
        n_reps=0,
        npts=npts,
        crossing_count=0,
        crossing_rate=float("nan"),
        cp_upper=float("nan"),
        cp_lower=float("nan"),
        mean_s_terminal=float("nan"),
        var_s_terminal=float("nan"),
        mean_look_count=float("nan"),
        loss_stop_count=0,
        skipped=True,
        skip_reason=reason,
    )


def run_cell(
    cell: CellSpec,
    *,
    cell_index: int,
    seed: int,
    n_reps: int,
    npts: int = GRID_NPTS,
    alpha: float = ALPHA_ONE_SIDED,
    i_max: float = I_MAX,
    n_max: int = N_MAX,
    look_step: int = LOOK_STEP,
) -> M1cCellResult:
    """One cell's Monte-Carlo, replaying the LIVE look loop verbatim
    (`run_sequential_looks` + a fresh `StreamingBoundary` per replicate).

    Neutral inputs throughout (L-41): `total_pnl = residual = Decimal(0)`,
    `cell_dead = structural_fired = False`, `truncation = None`. The
    crossing predicate is `state.s >= b_eff` at ANY recorded look (interim
    or terminal) -- read directly off each `LookRecord`, never off the
    tally's own `verdict` string, which this neutral wiring makes
    permanently unable to report `SURVIVE` (`total_pnl > 0` never holds at
    `total_pnl == 0`).
    """
    skip_reason = _feasibility_check(cell, seed=seed)
    if skip_reason is not None:
        return _skipped_result(
            cell, cell_index=cell_index, seed=seed, n_reps=n_reps, npts=npts, reason=skip_reason
        )

    artefact = _synthetic_artefact(alpha=alpha, i_max=i_max, n_max=n_max, look_step=look_step)
    rng = random.Random(seed)
    crossings = 0
    loss_stop_count = 0
    sum_s_terminal = 0.0
    sum_s2_terminal = 0.0
    sum_look_count = 0

    try:
        for _rep in range(n_reps):
            draws: list[CombinedDraw] = [
                combine_station_day(sample_station_day(rng, cell)) for _ in range(n_max)
            ]
            streaming = StreamingBoundary(alpha=alpha, npts=npts)
            looks, _verdict, decided = run_sequential_looks(
                draws,
                artefact=artefact,
                boundary_fn=streaming,
                total_pnl=Decimal(0),
                residual=Decimal(0),
                cell_dead=False,
                structural_fired=False,
                registered=True,
                truncation=None,
            )
            if not decided:
                raise AssertionError(
                    "the real n_max/look_step schedule always reaches a "
                    "terminal look (reached_n_max fires at look_n == n_max); "
                    "an undecided replicate is a driver defect"
                )
            if any(look.reason is TruncationReason.LOSS_STOP for look in looks):
                loss_stop_count += 1
            if any(look.state.s >= look.b_eff for look in looks):
                crossings += 1
            terminal_s = looks[-1].state.s
            sum_s_terminal += terminal_s
            sum_s2_terminal += terminal_s * terminal_s
            sum_look_count += len(looks)
    except InadmissibleSampleRetryExhausted as exc:
        return _skipped_result(
            cell, cell_index=cell_index, seed=seed, n_reps=n_reps, npts=npts, reason=str(exc)
        )

    mean_s_terminal = sum_s_terminal / n_reps
    var_s_terminal = sum_s2_terminal / n_reps - mean_s_terminal * mean_s_terminal
    crossing_rate = crossings / n_reps

    return M1cCellResult(
        cell_index=cell_index,
        label=cell.label,
        side_mix=cell.side_mix,
        k=cell.k,
        dispersion=cell.dispersion.label,
        r=cell.dispersion.r,
        seed=seed,
        n_reps=n_reps,
        npts=npts,
        crossing_count=crossings,
        crossing_rate=crossing_rate,
        cp_upper=clopper_pearson_upper(crossings, n_reps),
        cp_lower=clopper_pearson_lower(crossings, n_reps),
        mean_s_terminal=mean_s_terminal,
        var_s_terminal=var_s_terminal,
        mean_look_count=sum_look_count / n_reps,
        loss_stop_count=loss_stop_count,
    )


def run_chunk(
    from_idx: int, to_idx: int, *, out_path: Path, n_reps: int, npts: int = GRID_NPTS
) -> None:
    """Append one JSONL row per completed cell in `M1C_GRID[from_idx:to_idx]`
    (mirrors `aud06a_qty_envelope_sweep.run_chunk`'s chunked/resumable
    protocol -- per-cell seed, so chunk boundaries cannot change the
    result)."""
    with out_path.open("a", encoding="utf-8") as f:
        for cell_index in range(from_idx, to_idx):
            cell = M1C_GRID[cell_index]
            t0 = time.monotonic()
            result = run_cell(
                cell,
                cell_index=cell_index,
                seed=seed_for_cell_index(cell_index),
                n_reps=n_reps,
                npts=npts,
            )
            wall_s = time.monotonic() - t0
            row = result.to_json()
            row["wall_s"] = wall_s
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(
                f"[aud07-m1c] cell {cell_index} ({cell.label}): "
                f"crossing_rate={result.crossing_rate!r} cp_upper={result.cp_upper!r} "
                f"wall_s={wall_s:.2f}",
                file=sys.stderr,
                flush=True,
            )


def load_results(out_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with out_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _parse_cells_arg(value: str) -> tuple[int, int]:
    from_str, to_str = value.split(":")
    return int(from_str), int(to_str)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=_parse_cells_arg, required=True, help="FROM:TO, e.g. 0:49")
    parser.add_argument("--n-reps", type=int, required=True)
    parser.add_argument("--npts", type=int, default=GRID_NPTS)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from_idx, to_idx = args.cells
    args.out.parent.mkdir(parents=True, exist_ok=True)
    run_chunk(from_idx, to_idx, out_path=args.out, n_reps=args.n_reps, npts=args.npts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
