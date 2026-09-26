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
import hashlib
import json
import math
import os
import random
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np
import scipy
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
    "AUDIT_TARGET",
    "COARSE_NPTS",
    "LOOK_STEP",
    "M1C_GRID",
    "N_DEPTHS",
    "N_MAX",
    "N_SUBSTREAMS_80K",
    "REDUCED_NPTS",
    "SEED_BASE",
    "SEED_CAL_BASE",
    "SEED_RERUN_BASE",
    "AuditPremiseViolation",
    "EpsPin",
    "EpsPinValidationError",
    "ForeignStageRowError",
    "M1cCellResult",
    "ResumeKeyConflictError",
    "StreamingBoundary",
    "clopper_pearson_lower",
    "clopper_pearson_upper",
    "load_eps_pin",
    "m1c_grid",
    "run_cell",
    "run_chunk",
    "run_sequential_looks",
    "seed_for",
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

#: Rev 2 M1c/M2 execution amendment (2026-09-25) constants -- §7.
COARSE_NPTS: Final[int] = REDUCED_NPTS
SEED_CAL_BASE: Final[int] = 20260925_900
SEED_RERUN_BASE: Final[int] = 20260925_500
N_SUBSTREAMS_80K: Final[int] = 4
AUDIT_TARGET: Final[int] = 400

#: EPS floor (amendment §1 "EPS and DT_MIN"): `EPS = max(0.02, 3 x census
#: max)`, never below this regardless of the census.
EPS_FLOOR: Final[float] = 0.02

#: AUD-07 M1c-eps_k (RULING PR-1, 2026-09-26): the per-depth `eps_k` table's
#: fixed length, `N_MAX / LOOK_STEP` -- one entry per scheduled interim
#: look ordinal. Terminal looks use the separate, authoritative
#: `eps_terminal`, never an entry of this table.
N_DEPTHS: Final[int] = N_MAX // LOOK_STEP


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


def seed_for(stage: str, cell_index: int, substream: int = 0) -> int:
    """The Rev 2 seed-base table (§3.1): the 20k, 80k and CAL seed ranges
    are pairwise disjoint by construction (test 27). CAL-a/CAL-b/CAL-c
    intentionally share ONE formula (`SEED_CAL_BASE + cell_index`): CAL-c is
    required to reuse CAL-a's exact seeds for the byte-equality check
    (amendment §5, "CAL-c: refined `run_cell` on the CAL-a cells and
    seeds")."""
    if stage == "20k":
        return SEED_BASE + cell_index
    if stage == "80k":
        return SEED_RERUN_BASE + 100 * substream + cell_index
    if stage in ("cal_a", "cal_b", "cal_c", "smoke"):
        return SEED_CAL_BASE + cell_index
    raise ValueError(f"unknown stage {stage!r}")


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
    # --- Rev 2 M1c/M2 execution amendment fields (§7), all defaulted so the
    # dataclass stays valid and every existing pure-mode call site/test is
    # byte-unchanged. ---
    stage: str | None = None
    code_sha: str | None = None
    substream: int | None = None
    boundary_mode: str = "pure"
    coarse_npts: int | None = None
    eps: float | None = None
    dt_min: float | None = None
    eps_pin_sha256: str | None = None
    audit_every: int | None = None
    refined_count: int = 0
    #: sorted pairs: frozen/slots-safe, no mutable default.
    refine_reasons: tuple[tuple[str, int], ...] = ()
    audit_reps: int = 0
    audit_max_abs_delta_b: float | None = None
    audit_disagreements: int = 0
    sum_s_terminal: float = 0.0
    sum_s2_terminal: float = 0.0
    sum_look_count: int = 0
    numpy_version: str | None = None
    scipy_version: str | None = None
    #: AUD-07 M1c-eps_k (RULING PR-1): the per-depth eps table the pin used
    #: for this run's refined-mode replicates, disclosure only -- `None` in
    #: `pure` mode (no pin at all). `to_json` OMITS this key entirely when
    #: `None` (architect code note) so every existing pure-mode row's exact
    #: key set stays byte-unchanged (test 17).
    eps_by_depth: tuple[float, ...] | None = None

    def to_json(self) -> dict[str, Any]:
        payload = {
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
            "stage": self.stage,
            "code_sha": self.code_sha,
            "substream": self.substream,
            "boundary_mode": self.boundary_mode,
            "coarse_npts": self.coarse_npts,
            "eps": self.eps,
            "dt_min": self.dt_min,
            "eps_pin_sha256": self.eps_pin_sha256,
            "audit_every": self.audit_every,
            "refined_count": self.refined_count,
            "refine_reasons": [list(pair) for pair in self.refine_reasons],
            "audit_reps": self.audit_reps,
            "audit_max_abs_delta_b": self.audit_max_abs_delta_b,
            "audit_disagreements": self.audit_disagreements,
            "sum_s_terminal": self.sum_s_terminal,
            "sum_s2_terminal": self.sum_s2_terminal,
            "sum_look_count": self.sum_look_count,
            "numpy_version": self.numpy_version,
            "scipy_version": self.scipy_version,
        }
        if self.eps_by_depth is not None:
            payload["eps_by_depth"] = list(self.eps_by_depth)
        return payload


# ---------------------------------------------------------------------------
# Rev 2 refine-on-proximity machinery (amendment §1, §2, §3.2)
# ---------------------------------------------------------------------------
class EpsPinValidationError(ValueError):
    """`load_eps_pin` refuses an EPS below the floor, below 3x the census
    max, or stamped with a foreign `code_sha` (amendment §5 "Pin")."""


class AuditPremiseViolation(RuntimeError):
    """Raised when an in-run audit finds a decision disagreement or an
    |delta b| >= EPS between the coarse and fine grids (amendment §2.1).
    The cell that raises this writes NO row and the caller must exit
    non-zero (test 22)."""

    def __init__(
        self, *, cell_index: int, rep_index: int, max_abs_delta_b: float, disagreement: bool
    ) -> None:
        self.cell_index = cell_index
        self.rep_index = rep_index
        self.max_abs_delta_b = max_abs_delta_b
        self.disagreement = disagreement
        super().__init__(
            f"cell {cell_index} rep {rep_index}: audit premise violation "
            f"(disagreement={disagreement}, max_abs_delta_b={max_abs_delta_b!r})"
        )


@dataclass(frozen=True, slots=True)
class EpsPin:
    """The data-file EPS/DT_MIN pin (amendment §1 "EPS and DT_MIN", §5
    "Pin") -- never a code constant, so CAL and the gated runs share one
    `code_sha` and one snapshot."""

    eps: float
    dt_min: float
    census_sha256: str
    census_max: float
    code_sha: str
    #: sha256 of the pin FILE's own canonical bytes, stamped on every row.
    sha256: str
    #: AUD-07 M1c-eps_k (RULING PR-1): the per-depth eps table (length
    #: `N_DEPTHS`, index 0 = depth 1) and the authoritative terminal eps.
    #: `None` only for an :class:`EpsPin` built directly (bypassing
    #: `load_eps_pin`) without a table -- `load_eps_pin` itself ALWAYS
    #: returns both populated, normalising a legacy scalar pin to a
    #: constant table (architect code note).
    eps_by_depth: tuple[float, ...] | None = None
    eps_terminal: float | None = None


def load_eps_pin(path: Path, *, code_sha: str) -> EpsPin:
    """Load and validate `eps_pin.json` (amendment §5 "Pin"): `EPS >=
    0.02`, `EPS >= 3 x census max`, and the pin's own `code_sha` must match
    the running code -- each violation is a refusal, never a silent clamp
    (test 28).

    AUD-07 M1c-eps_k (RULING PR-1, 2026-09-26): an optional per-depth
    `eps_by_depth` (length `N_DEPTHS`) plus an authoritative `eps_terminal`.
    A legacy pin (neither key present) is NORMALISED to a constant table --
    `eps_by_depth = (eps,) * N_DEPTHS`, `eps_terminal = eps` -- so every
    downstream consumer has ONE representation (architect code note). Each
    entry passes the SAME floor/3x-census validation as the scalar `eps`;
    the pin refuses a table of the wrong length and refuses a scalar `eps`
    that does not equal `max(eps_by_depth, eps_terminal)`."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    eps = float(payload["eps"])
    dt_min = float(payload["dt_min"])
    census_max = float(payload["census_max"])
    census_sha256 = str(payload["census_sha256"])
    pin_code_sha = str(payload["code_sha"])

    if pin_code_sha != code_sha:
        raise EpsPinValidationError(
            f"eps_pin code_sha {pin_code_sha!r} does not match the running "
            f"code_sha {code_sha!r} (foreign pin)"
        )

    eps_by_depth_raw = payload.get("eps_by_depth")
    if eps_by_depth_raw is None:
        # Legacy scalar pin: normalise to a constant per-depth table.
        eps_by_depth_list = [eps] * N_DEPTHS
        eps_terminal = eps
        census_max_by_depth = [census_max] * N_DEPTHS
        census_terminal_max = census_max
    else:
        eps_by_depth_list = [float(v) for v in eps_by_depth_raw]
        if len(eps_by_depth_list) != N_DEPTHS:
            raise EpsPinValidationError(
                f"eps_by_depth has {len(eps_by_depth_list)} entries, expected "
                f"{N_DEPTHS} (N_MAX/LOOK_STEP)"
            )
        if "eps_terminal" not in payload:
            raise EpsPinValidationError("eps_by_depth is present but eps_terminal is missing")
        eps_terminal = float(payload["eps_terminal"])
        census_max_by_depth_raw = payload.get("census_max_by_depth")
        if census_max_by_depth_raw is None:
            census_max_by_depth = [0.0] * N_DEPTHS
        else:
            census_max_by_depth = [float(v) for v in census_max_by_depth_raw]
            if len(census_max_by_depth) != N_DEPTHS:
                raise EpsPinValidationError(
                    f"census_max_by_depth has {len(census_max_by_depth)} entries, "
                    f"expected {N_DEPTHS} (N_MAX/LOOK_STEP)"
                )
        census_terminal_max = float(payload.get("census_terminal_max", 0.0))

    paired_depths = zip(eps_by_depth_list, census_max_by_depth)
    for depth, (eps_k_val, max_k) in enumerate(paired_depths, start=1):
        if eps_k_val < EPS_FLOOR:
            raise EpsPinValidationError(
                f"eps_by_depth[{depth}] {eps_k_val!r} is below the floor {EPS_FLOOR!r}"
            )
        if eps_k_val < 3.0 * max_k:
            raise EpsPinValidationError(
                f"eps_by_depth[{depth}] {eps_k_val!r} is below 3x its census max "
                f"{max_k!r} ({3.0 * max_k!r})"
            )
    if eps_terminal < EPS_FLOOR:
        raise EpsPinValidationError(
            f"eps_terminal {eps_terminal!r} is below the floor {EPS_FLOOR!r}"
        )
    if eps_terminal < 3.0 * census_terminal_max:
        raise EpsPinValidationError(
            f"eps_terminal {eps_terminal!r} is below 3x the terminal census max "
            f"{census_terminal_max!r} ({3.0 * census_terminal_max!r})"
        )

    expected_scalar_eps = max([*eps_by_depth_list, eps_terminal])
    if eps != expected_scalar_eps:
        raise EpsPinValidationError(
            f"scalar eps {eps!r} does not equal max(eps_by_depth, eps_terminal) "
            f"{expected_scalar_eps!r}"
        )
    if eps < EPS_FLOOR:
        raise EpsPinValidationError(f"eps {eps!r} is below the floor {EPS_FLOOR!r}")
    if eps < 3.0 * census_max:
        raise EpsPinValidationError(
            f"eps {eps!r} is below 3x the census max {census_max!r} "
            f"({3.0 * census_max!r})"
        )
    if dt_min <= 0.0:
        raise EpsPinValidationError(f"dt_min {dt_min!r} must be > 0")

    return EpsPin(
        eps=eps,
        dt_min=dt_min,
        census_sha256=census_sha256,
        census_max=census_max,
        code_sha=pin_code_sha,
        sha256=hashlib.sha256(raw).hexdigest(),
        eps_by_depth=tuple(eps_by_depth_list),
        eps_terminal=eps_terminal,
    )


def _resolve_audit_every(n_reps: int, audit_every: int | None) -> int:
    """Review item 6b: `audit_every = n_reps // AUDIT_TARGET` when omitted
    (never zero -- `max(1, ...)` so a small `n_reps` still audits every
    rep), matching amendment §1 ("50 at 20k and 200 at 80k"). An EXPLICIT
    `audit_every` that would yield fewer than `AUDIT_TARGET` audits is
    refused rather than silently under-auditing."""
    if audit_every is None:
        return max(1, n_reps // AUDIT_TARGET)
    n_audits = n_reps // audit_every
    if n_audits < AUDIT_TARGET:
        raise ValueError(
            f"--audit-every {audit_every} yields only {n_audits} audit(s) for "
            f"n_reps={n_reps}, below AUDIT_TARGET={AUDIT_TARGET}"
        )
    return audit_every


def _depth_table_as_mapping(table: tuple[float, ...] | None) -> dict[int, float] | None:
    """`pin.eps_by_depth` is a 0-indexed tuple (index 0 = depth 1); expose
    it to :func:`_eps_for_look` as the depth-keyed mapping it expects."""
    if table is None:
        return None
    return dict(enumerate(table, start=1))


def _eps_for_look(
    look: Any,
    *,
    eps: float,
    eps_by_depth: Mapping[int, float] | None,
    eps_terminal: float | None,
) -> float:
    """AUD-07 M1c-eps_k (RULING PR-1): the per-look eps -- `eps_terminal`
    for a look the SIM'S OWN stop rule marks `terminal` (never by ordinal
    position), else `eps_by_depth[depth]` for that look's ordinal depth
    (`look_n // LOOK_STEP`), falling back to the GLOBAL scalar `eps` (never
    the floor) when `eps_by_depth` is absent entirely or has no entry for
    that depth."""
    if eps_by_depth is None:
        return eps
    if look.terminal:
        return eps_terminal if eps_terminal is not None else eps
    depth = look.look_n // LOOK_STEP
    # A look at depth N_DEPTHS (look_n == N_MAX) is always terminal (the
    # `look.terminal` branch above), so `eps_by_depth[N_DEPTHS]` can never be
    # reached here by design -- the table still carries that entry only to
    # satisfy the fixed-length (N_DEPTHS) table-shape contract.
    return eps_by_depth.get(depth, eps)


def _needs_refine(
    looks: Sequence[Any],
    *,
    eps: float,
    dt_min: float,
    eps_by_depth: Mapping[int, float] | None = None,
    eps_terminal: float | None = None,
) -> str | None:
    """`None` only if ALL of eff/fut/dt/nonfinite hold over the reached
    coarse looks (amendment §2.1). Returns the FIRST failing category's
    short name otherwise.

    AUD-07 M1c-eps_k (RULING PR-1): `eps_by_depth`/`eps_terminal` are
    optional and default to `None`, in which case every look uses the
    single scalar `eps` -- byte-identical to the pre-eps_k behaviour (tests
    1-16, 4a/4b, the M1b golden). When present, the eff/fut checks use
    EACH look's own eps via :func:`_eps_for_look`. PR-2: `dt_min` stays one
    global scalar, unaffected by eps_k."""
    if not looks:
        return None

    confident_crossing = any(
        (look.state.s - look.b_eff)
        >= _eps_for_look(look, eps=eps, eps_by_depth=eps_by_depth, eps_terminal=eps_terminal)
        for look in looks
    )
    confident_non_crossing = all(
        (look.state.s - look.b_eff)
        <= -_eps_for_look(look, eps=eps, eps_by_depth=eps_by_depth, eps_terminal=eps_terminal)
        for look in looks
    )
    if not (confident_crossing or confident_non_crossing):
        return "eff"

    for look in looks:
        if look.b_fut == float("-inf"):
            continue  # tie pair: infinite margin, always passes.
        look_eps = _eps_for_look(
            look, eps=eps, eps_by_depth=eps_by_depth, eps_terminal=eps_terminal
        )
        if abs(look.state.s - look.b_fut) < look_eps:
            return "fut"

    prev_t = 0.0
    for look in looks:
        dt = look.t - prev_t
        prev_t = look.t
        if dt == 0.0:
            continue  # a tie: the degenerate (+inf, -inf) pair.
        if dt < dt_min:
            return "dt"

    for look in looks:
        is_tie_pair = look.b_eff == float("inf") and look.b_fut == float("-inf")
        if is_tie_pair:
            continue
        if not (math.isfinite(look.b_eff) and math.isfinite(look.b_fut)):
            return "nonfinite"

    return None


def _decisions(looks: Sequence[Any]) -> tuple[bool, int, int | None]:
    """`(crossing indicator, number of looks, futility-stop index)`
    (amendment §2.1 `decisions(looks)`)."""
    crossed = any(look.state.s >= look.b_eff for look in looks)
    futility_index = next(
        (i for i, look in enumerate(looks) if look.state.s <= look.b_fut), None
    )
    return (crossed, len(looks), futility_index)


def _max_abs_delta_b(looks_a: Sequence[Any], looks_b: Sequence[Any]) -> float:
    """Max absolute |delta b| over the two chains' matching looks. The
    exact `(+inf, -inf)` tie pair counts as zero delta when both sides
    agree; any other pairing where one side is non-finite and the other is
    not is reported as an infinite (maximal) delta."""
    max_delta = 0.0
    for look_a, look_b in zip(looks_a, looks_b, strict=False):
        for xa, xb in ((look_a.b_eff, look_b.b_eff), (look_a.b_fut, look_b.b_fut)):
            if xa == xb:
                continue
            if not (math.isfinite(xa) and math.isfinite(xb)):
                return float("inf")
            max_delta = max(max_delta, abs(xa - xb))
    return max_delta


def _audit_violates_eps(looks_a: Sequence[Any], looks_b: Sequence[Any], pin: EpsPin) -> bool:
    """AUD-07 M1c-eps_k (RULING PR-1): the audit abort is per-depth --
    each matching look pair is checked against THAT look's own eps
    (:func:`_eps_for_look`, keyed off `looks_a`'s `.terminal`/`.look_n`)
    rather than the single scalar `pin.eps`. With no `eps_by_depth` table
    this reduces exactly to the legacy `max_abs_delta_b >= pin.eps` check
    (test 18)."""
    eps_by_depth = _depth_table_as_mapping(pin.eps_by_depth)
    for look_a, look_b in zip(looks_a, looks_b, strict=False):
        threshold = _eps_for_look(
            look_a, eps=pin.eps, eps_by_depth=eps_by_depth, eps_terminal=pin.eps_terminal
        )
        for xa, xb in ((look_a.b_eff, look_b.b_eff), (look_a.b_fut, look_b.b_fut)):
            if xa == xb:
                continue
            if not (math.isfinite(xa) and math.isfinite(xb)):
                return True
            if abs(xa - xb) >= threshold:
                return True
    return False


def _run_replicate(
    draws: list[CombinedDraw],
    *,
    artefact: BoundaryArtefact,
    pin: EpsPin,
    coarse_npts: int,
    fine_npts: int,
    alpha: float,
    audit: bool,
    rep_index: int,
    cell_index: int,
) -> tuple[tuple[Any, ...], str | None, dict[str, Any]]:
    """One refined-mode replicate (amendment §2.1's pseudocode). Raises
    `AuditPremiseViolation` (never caught here) on an audited disagreement
    or |delta b| >= EPS -- the caller must let the cell abort with no row
    written (test 22)."""
    try:
        streaming_c = StreamingBoundary(alpha=alpha, npts=coarse_npts)
        looks_c, _verdict_c, _decided_c = run_sequential_looks(
            draws,
            artefact=artefact,
            boundary_fn=streaming_c,
            total_pnl=Decimal(0),
            residual=Decimal(0),
            cell_dead=False,
            structural_fired=False,
            registered=True,
            truncation=None,
        )
    except ValueError:
        reason: str | None = "solver"
        looks_c = ()
    else:
        reason = _needs_refine(
            looks_c,
            eps=pin.eps,
            dt_min=pin.dt_min,
            eps_by_depth=_depth_table_as_mapping(pin.eps_by_depth),
            eps_terminal=pin.eps_terminal,
        )

    audit_stats: dict[str, Any] = {
        "audited": False,
        "max_abs_delta_b": None,
        "disagreement": False,
    }

    if reason is not None or audit:
        streaming_f = StreamingBoundary(alpha=alpha, npts=fine_npts)
        looks_f, _verdict_f, _decided_f = run_sequential_looks(
            draws,
            artefact=artefact,
            boundary_fn=streaming_f,
            total_pnl=Decimal(0),
            residual=Decimal(0),
            cell_dead=False,
            structural_fired=False,
            registered=True,
            truncation=None,
        )
        if audit and reason is None:
            max_delta = _max_abs_delta_b(looks_c, looks_f)
            disagreement = _decisions(looks_c) != _decisions(looks_f)
            audit_stats = {
                "audited": True,
                "max_abs_delta_b": max_delta,
                "disagreement": disagreement,
            }
            if disagreement or _audit_violates_eps(looks_c, looks_f, pin):
                raise AuditPremiseViolation(
                    cell_index=cell_index,
                    rep_index=rep_index,
                    max_abs_delta_b=max_delta,
                    disagreement=disagreement,
                )
        looks = looks_f
        used_fine_grid = True
    else:
        looks = looks_c
        used_fine_grid = False

    # `needed_refine` (reason-triggered) is DISTINCT from `used_fine_grid`
    # (also true for an audit-only rep that never needed refining) -- the
    # cost-model refine fraction f (§2.4) counts only the former.
    return looks, reason, {
        "used_fine_grid": used_fine_grid,
        "needed_refine": reason is not None,
        **audit_stats,
    }


def _assert_snapshot_imports(root: Path) -> None:
    """Startup assertion (amendment §3.2): `breezy` and
    `aud06a_qty_envelope_sweep` must both resolve UNDER `root` -- catches an
    editable install in `.venv`, or a stray `PYTHONPATH`, pointing at a
    different tree than the pinned snapshot (test 26)."""
    root = root.resolve()

    import breezy

    breezy_path = Path(breezy.__file__).resolve()
    if root not in breezy_path.parents:
        raise AssertionError(
            f"breezy resolves to {breezy_path}, outside the snapshot root "
            f"{root} (editable install or stray PYTHONPATH?)"
        )

    import aud06a_qty_envelope_sweep

    sweep_path = Path(aud06a_qty_envelope_sweep.__file__).resolve()
    if root not in sweep_path.parents:
        raise AssertionError(
            f"aud06a_qty_envelope_sweep resolves to {sweep_path}, outside "
            f"the snapshot root {root}"
        )

    family_tally_v2_path = (_SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py").resolve()
    if root not in family_tally_v2_path.parents:
        raise AssertionError(
            f"the family_tally_v2 spec path {family_tally_v2_path} is "
            f"outside the snapshot root {root}"
        )


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
    boundary_mode: Literal["pure", "refined"] = "pure",
    eps_pin: EpsPin | None = None,
    coarse_npts: int = COARSE_NPTS,
    audit_every: int | None = None,
    stage: str | None = None,
    code_sha: str | None = None,
    substream: int | None = None,
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

    `boundary_mode="pure"` (the default) is byte-unchanged from the M1b
    behaviour: a single `StreamingBoundary(npts=npts)` chain per replicate.
    `boundary_mode="refined"` (Rev 2 amendment §1/§2) requires `eps_pin`: it
    runs the coarse chain at `coarse_npts`, refining onto a fresh
    `npts`-grid chain on proximity, forced guard, or in-run audit
    (`audit_every`). `npts` is then the DECISION grid recorded on the row.
    An `AuditPremiseViolation` propagates uncaught -- the cell aborts with
    no row written (test 22).
    """
    skip_reason = _feasibility_check(cell, seed=seed)
    if skip_reason is not None:
        return _skipped_result(
            cell, cell_index=cell_index, seed=seed, n_reps=n_reps, npts=npts, reason=skip_reason
        )

    if boundary_mode == "refined" and eps_pin is None:
        raise ValueError("boundary_mode='refined' requires an eps_pin")

    artefact = _synthetic_artefact(alpha=alpha, i_max=i_max, n_max=n_max, look_step=look_step)
    rng = random.Random(seed)
    crossings = 0
    loss_stop_count = 0
    sum_s_terminal = 0.0
    sum_s2_terminal = 0.0
    sum_look_count = 0
    refined_count = 0
    refine_reason_counts: dict[str, int] = {}
    audit_reps = 0
    audit_max_abs_delta_b: float | None = None
    audit_disagreements = 0
    audit_every_effective = (
        _resolve_audit_every(n_reps, audit_every) if boundary_mode == "refined" else None
    )

    try:
        for rep_index in range(n_reps):
            draws: list[CombinedDraw] = [
                combine_station_day(sample_station_day(rng, cell)) for _ in range(n_max)
            ]

            if boundary_mode == "refined":
                assert eps_pin is not None
                audit = audit_every_effective is not None and rep_index % audit_every_effective == 0
                looks, reason, stats = _run_replicate(
                    draws,
                    artefact=artefact,
                    pin=eps_pin,
                    coarse_npts=coarse_npts,
                    fine_npts=npts,
                    alpha=alpha,
                    audit=audit,
                    rep_index=rep_index,
                    cell_index=cell_index,
                )
                decided = True
                if stats["needed_refine"]:
                    refined_count += 1
                    refine_reason_counts[reason] = refine_reason_counts.get(reason, 0) + 1
                if stats["audited"]:
                    audit_reps += 1
                    delta = stats["max_abs_delta_b"]
                    if delta is not None and (
                        audit_max_abs_delta_b is None or delta > audit_max_abs_delta_b
                    ):
                        audit_max_abs_delta_b = delta
                    if stats["disagreement"]:
                        audit_disagreements += 1
            else:
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
        stage=stage,
        code_sha=code_sha,
        substream=substream,
        boundary_mode=boundary_mode,
        coarse_npts=coarse_npts if boundary_mode == "refined" else None,
        eps=eps_pin.eps if eps_pin is not None else None,
        dt_min=eps_pin.dt_min if eps_pin is not None else None,
        eps_pin_sha256=eps_pin.sha256 if eps_pin is not None else None,
        eps_by_depth=eps_pin.eps_by_depth if eps_pin is not None else None,
        audit_every=audit_every_effective,
        refined_count=refined_count,
        refine_reasons=tuple(sorted(refine_reason_counts.items())),
        audit_reps=audit_reps,
        audit_max_abs_delta_b=audit_max_abs_delta_b,
        audit_disagreements=audit_disagreements,
        sum_s_terminal=sum_s_terminal,
        sum_s2_terminal=sum_s2_terminal,
        sum_look_count=sum_look_count,
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
    )


class ForeignStageRowError(RuntimeError):
    """A row's own `stage` field does not match the `--stage`/`stage=`
    this `run_chunk` invocation was given (amendment §3.3, test 24)."""


class ResumeKeyConflictError(RuntimeError):
    """The same `(stage, cell_index, substream)` already has a row on disk
    with a DIFFERENT resume key (e.g. a different `code_sha`) -- refused
    rather than silently overwritten or duplicated (amendment §3.3, test
    23)."""


#: The resume key (amendment §3.3, step 3): an exact match on all of these
#: means the cell is done and is skipped; any other difference on the same
#: `(stage, cell_index, substream)` raises.
_RESUME_KEY_FIELDS: Final[tuple[str, ...]] = (
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


def _resume_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in _RESUME_KEY_FIELDS)


def _read_and_repair(out_path: Path) -> list[str]:
    """Read complete lines from `out_path`, repairing a killed write
    (amendment §3.3 step 1: non-empty, no trailing `\\n` -> truncate to the
    last complete line, or to empty). Returns the complete raw lines
    (without their trailing newline); a complete line that fails to parse
    is left for the caller to raise on (step 2)."""
    if not out_path.exists():
        return []
    raw = out_path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        last_nl = raw.rfind(b"\n")
        repaired = raw[: last_nl + 1] if last_nl >= 0 else b""
        out_path.write_bytes(repaired)
        print(
            f"[aud07-m1c] repaired a killed write in {out_path}: truncated to "
            "the last complete line",
            file=sys.stderr,
        )
        raw = repaired
    text = raw.decode("utf-8")
    return [line for line in text.split("\n") if line]


def _load_done_cells(out_path: Path, *, stage: str) -> dict[int, tuple[Any, ...]]:
    """`{cell_index: resume_key}` for rows already complete in `out_path`,
    after repairing a killed write. Raises `ForeignStageRowError` on a row
    whose `stage` differs from the expected stage; a malformed complete
    line raises via `json.loads` itself (amendment §3.3 step 2)."""
    done: dict[int, tuple[Any, ...]] = {}
    for line in _read_and_repair(out_path):
        row = json.loads(line)
        if row.get("stage") != stage:
            raise ForeignStageRowError(
                f"row stage {row.get('stage')!r} in {out_path} does not match "
                f"the expected stage {stage!r}"
            )
        done[row["cell_index"]] = _resume_key(row)
    return done


def run_chunk(
    from_idx: int,
    to_idx: int,
    *,
    out_path: Path,
    n_reps: int,
    npts: int = GRID_NPTS,
    stage: str = "20k",
    code_sha: str | None = None,
    boundary_mode: Literal["pure", "refined"] = "pure",
    eps_pin: EpsPin | None = None,
    coarse_npts: int = COARSE_NPTS,
    audit_every: int | None = None,
    substream: int | None = None,
) -> None:
    """Append one JSONL row per completed cell in `M1C_GRID[from_idx:to_idx]`
    (mirrors `aud06a_qty_envelope_sweep.run_chunk`'s chunked/resumable
    protocol -- per-cell seed, so chunk boundaries cannot change the
    result), stage-aware and idempotent (amendment §3.3).

    `--out`'s parent directory name must equal `stage` (amendment §3.3
    "The CLI takes `--stage` and refuses an `--out` whose parent directory
    name is not that stage", test 24) -- enforced by the CLI, not here, so
    a direct `run_chunk` call (as the tests use) stays a plain library
    call.
    """
    done = _load_done_cells(out_path, stage=stage)

    with out_path.open("a", encoding="utf-8") as f:
        for cell_index in range(from_idx, to_idx):
            cell = M1C_GRID[cell_index]
            seed = seed_for(stage, cell_index, substream or 0)
            this_key = (
                stage,
                cell_index,
                substream,
                seed,
                n_reps,
                boundary_mode,
                coarse_npts if boundary_mode == "refined" else None,
                eps_pin.sha256 if eps_pin is not None else None,
                code_sha,
                np.__version__,
                scipy.__version__,
            )
            existing_key = done.get(cell_index)
            if existing_key is not None:
                if existing_key == this_key:
                    continue  # exact match: already done, skip.
                raise ResumeKeyConflictError(
                    f"cell {cell_index} in {out_path} already has a row with a "
                    f"DIFFERENT resume key: existing={existing_key!r} "
                    f"new={this_key!r}"
                )

            t0 = time.monotonic()
            result = run_cell(
                cell,
                cell_index=cell_index,
                seed=seed,
                n_reps=n_reps,
                npts=npts,
                boundary_mode=boundary_mode,
                eps_pin=eps_pin,
                coarse_npts=coarse_npts,
                audit_every=audit_every,
                stage=stage,
                code_sha=code_sha,
                substream=substream,
            )
            wall_s = time.monotonic() - t0
            row = result.to_json()
            row["wall_s"] = wall_s
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())
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


class StageDirMismatchError(RuntimeError):
    """`--out`'s parent directory name is not `--stage` (amendment §3.3,
    test 24)."""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=_parse_cells_arg, required=True, help="FROM:TO, e.g. 0:49")
    parser.add_argument("--n-reps", type=int, required=True)
    parser.add_argument("--npts", type=int, default=GRID_NPTS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", default="20k")
    parser.add_argument("--code-sha", default=None)
    parser.add_argument("--eps-pin", type=Path, default=None)
    parser.add_argument("--substream", type=int, default=None)
    parser.add_argument(
        "--boundary-mode", choices=("pure", "refined"), default="pure"
    )
    parser.add_argument("--coarse-npts", type=int, default=COARSE_NPTS)
    parser.add_argument("--audit-every", type=int, default=None)
    return parser.parse_args(argv)


#: Stages that MUST run from the pinned code snapshot (amendment §3.2):
#: `smoke` is exempt (decided, review item 3) -- it is a cheap plumbing
#: check, run directly against the working tree during development, never
#: cited as evidence.
_SNAPSHOT_GATED_STAGES: Final[frozenset[str]] = frozenset({"cal_a", "cal_b", "cal_c", "20k", "80k"})


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from_idx, to_idx = args.cells
    if args.out.parent.name != args.stage:
        raise StageDirMismatchError(
            f"--out {args.out} has parent directory {args.out.parent.name!r}, "
            f"which does not match --stage {args.stage!r}"
        )
    if args.stage in _SNAPSHOT_GATED_STAGES:
        _assert_snapshot_imports(_REPO_ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    eps_pin = None
    if args.boundary_mode == "refined":
        if args.eps_pin is None:
            raise ValueError("--boundary-mode=refined requires --eps-pin")
        eps_pin = load_eps_pin(args.eps_pin, code_sha=args.code_sha)

    run_chunk(
        from_idx,
        to_idx,
        out_path=args.out,
        n_reps=args.n_reps,
        npts=args.npts,
        stage=args.stage,
        code_sha=args.code_sha,
        boundary_mode=args.boundary_mode,
        eps_pin=eps_pin,
        coarse_npts=args.coarse_npts,
        audit_every=args.audit_every,
        substream=args.substream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
