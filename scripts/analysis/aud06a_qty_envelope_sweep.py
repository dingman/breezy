"""AUD-06a — R-11 qty envelope sweep driver.

Amendment C to `docs/plans/MULTI_POSITION_PER_STATION_2026-09-14.md` (item
(ii) of the validation slice, R3-3 disposition). Re-validates the LD-OBF
boundary artefact's realised one-sided crossing rate as a function of the
qty distribution, over the dimensionless sweep grid pinned in Amendment C's
own text, and reports the realised information-accrual trajectory against
the artefact's assumed schedule (the recorded xfail mechanism,
`tests/unit/test_multi_position_validation_2026_09_14.py:163-179`).

This module REUSES the registered formulas verbatim -- `StratumRow`,
`combine_station_day`, `score_combined` (`breezy.settlement.current_rung_hold_v2`)
-- and never re-implements the H0 variance. The artefact's own
`reference_table` is read the same way
`tests/unit/test_multi_position_validation_2026_09_14.py` already does
(`_artefact_payload` + linear interpolation), not the `persistence`-layer
loader, which would pull `settlement` under `persistence` for a module that
lives outside both layers (`scripts/analysis`).

No operator-reserved value is read, restated, defaulted or inferred
anywhere in this module -- the qty axis is a dimensionless `q_max`/`R` grid,
never a dollar figure (AUD-06a §5, §12 named risk).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

import numpy as np
from scipy import stats

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    StratumRow,
    combine_station_day,
)

_ARTEFACT_PATH = _REPO_ROOT / "deploy" / "families" / "gs_boundary_pm_us_crh_v2.json"

# ---------------------------------------------------------------------------
# Methodology, pinned (Amendment C "Methodology, pinned")
# ---------------------------------------------------------------------------
N_REPS: int = 20000
REPRODUCTION_SEED: int = 20260914
SWEEP_SEED_BASE: int = 20260921_000
VAR_S_TOLERANCE: tuple[float, float] = (0.95, 1.05)
CP_CONFIDENCE: float = 0.95  # one-sided 95% upper bound (Clopper-Pearson exact)

# Mechanism-verdict thresholds -- REASONED BUILD-SIDE DEFAULTS, fixed before
# the sweep ran, NOT inherited from any registered study (Amendment C
# "Threshold provenance", R3 fix). Contrast: N_REPS, CP_CONFIDENCE and
# VAR_S_TOLERANCE ARE anchored to
# `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6.
MIN_CONTRIBUTING_CELLS: int = 24
RHO_THRESHOLD: float = 0.70
PERMUTATION_P_THRESHOLD: float = 0.01
PERMUTATION_COUNT: int = 10000
CONTROL_MAX_ABS_DELTA_T: float = 0.01
CONTROL_MAX_CP_UPPER: float = 0.025

# Sweep axes (Amendment C "Sweep axes")
Q_MAX_GRID: tuple[int, ...] = (1, 2, 3, 4, 5)
CAP_SHAPED_R_GRID: tuple[int, ...] = (2, 3, 5, 8, 13, 21)
K_GRID: tuple[int, ...] = (1, 2, 3)
SideMix = Literal["all_yes", "all_no", "mixed"]
SIDE_MIX_GRID: tuple[SideMix, ...] = ("all_yes", "all_no", "mixed")

#: Read-only observed ask sample -- the 9 durable PM.us fills' `cost = px`
#: column, `docs/evidence/AUD13A_RECONCILIATION_EVIDENCE_2026-09-24.md` §1.
#: This is the ONLY observed live/tape ask data read for this item (no
#: operator-reserved value; asks are the venue's own posted price, already
#: public per-fill). Used as both the `BE`-prior draw and the `cap-shaped`
#: dispersion's `ask_i` draw (Amendment C: "one source, not two").
OBSERVED_ASKS: tuple[float, ...] = (0.22, 0.70, 0.11, 0.09, 0.24, 0.44, 0.12, 0.35, 0.12)


def observed_ask_support(asks: tuple[float, ...] = OBSERVED_ASKS) -> dict[str, float]:
    """`min`/`p25`/`median`/`p75`/`max`/`iqr` of the observed ask sample --
    the `BE`-prior support the staleness trigger (Amendment C) records."""
    arr = np.asarray(asks, dtype=float)
    p25, median, p75 = np.percentile(arr, [25, 50, 75])
    return {
        "n": float(arr.size),
        "min": float(arr.min()),
        "p25": float(p25),
        "median": float(median),
        "p75": float(p75),
        "max": float(arr.max()),
        "iqr": float(p75 - p25),
    }


def envelope_is_stale(live_asks: tuple[float, ...], *, recorded_support: dict[str, float]) -> bool:
    """Fail-closed staleness predicate (Amendment C "Output: the validated
    envelope AND its expiry condition"). STALE when either:
    (1) the live median ask falls outside the recorded `[p25, p75]`; or
    (2) the live IQR exceeds the recorded IQR by >50% or falls below it by >33%.
    An empty `live_asks` is STALE (no evidence the envelope still applies).
    """
    if not live_asks:
        return True
    arr = np.asarray(live_asks, dtype=float)
    live_p25, live_median, live_p75 = np.percentile(arr, [25, 50, 75])
    live_iqr = live_p75 - live_p25
    recorded_iqr = recorded_support["iqr"]
    if not (recorded_support["p25"] <= live_median <= recorded_support["p75"]):
        return True
    if recorded_iqr <= 0:
        return live_iqr > 0
    if live_iqr > recorded_iqr * 1.5:
        return True
    return live_iqr < recorded_iqr * (1 - 0.33)


# ---------------------------------------------------------------------------
# Artefact loading (byte-identical to the existing test module's approach)
# ---------------------------------------------------------------------------
def artefact_payload() -> dict:
    return json.loads(_ARTEFACT_PATH.read_text(encoding="utf-8"))


def interp(t: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation with flat extrapolation, restated dependency-free
    (verbatim copy of `test_multi_position_validation_2026_09_14._interp`)."""
    if t <= xs[0]:
        return ys[0]
    if t >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            return y0 + (t - x0) / (x1 - x0) * (y1 - y0)
    return ys[-1]


# ---------------------------------------------------------------------------
# Cell specification and canonical ordering
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DispersionSpec:
    label: str
    r: int | None = None


DISPERSION_GRID: tuple[DispersionSpec, ...] = (
    DispersionSpec("all_equal"),
    DispersionSpec("two_point"),
    *(DispersionSpec("cap_shaped", r=r) for r in CAP_SHAPED_R_GRID),
)

#: The 8 ADMISSIBLE (k, side_mix) pairs -- `mixed` is undefined at k=1 and
#: is SKIPPED, never silently sampled as all-YES (Amendment C compute-budget
#: subsection).
ADMISSIBLE_K_SIDE_MIX: tuple[tuple[int, SideMix], ...] = tuple(
    (k, side_mix)
    for k in K_GRID
    for side_mix in SIDE_MIX_GRID
    if not (k == 1 and side_mix == "mixed")
)


@dataclass(frozen=True, slots=True)
class CellSpec:
    q_max: int
    dispersion: DispersionSpec
    k: int
    side_mix: SideMix

    @property
    def label(self) -> str:
        if self.dispersion.r is None:
            disp = self.dispersion.label
        else:
            disp = f"{self.dispersion.label}:R={self.dispersion.r}"
        return f"q_max={self.q_max},dispersion={disp},k={self.k},side_mix={self.side_mix}"


def enumerate_cells() -> tuple[CellSpec, ...]:
    """Canonical cell ordering (Amendment C compute-budget subsection):
    lexicographic on `(q_max, dispersion, R_or_none, k, side_mix)`, fixed
    and recorded so a cell's index never moves. 5 x 8 x 8 = 320 cells."""
    cells = []
    for q_max in Q_MAX_GRID:
        for dispersion in DISPERSION_GRID:
            for k, side_mix in ADMISSIBLE_K_SIDE_MIX:
                cells.append(CellSpec(q_max=q_max, dispersion=dispersion, k=k, side_mix=side_mix))
    return tuple(cells)


ALL_CELLS: tuple[CellSpec, ...] = enumerate_cells()
assert len(ALL_CELLS) == 320, f"expected 320 cells, got {len(ALL_CELLS)}"


class InadmissibleSampleRetryExhausted(RuntimeError):
    """Raised if admissible-draw rejection sampling cannot find a valid
    station-day within the retry budget -- a driver defect, never a reason
    to relax the admission gate."""


_MAX_SAMPLE_ATTEMPTS = 2000


def _qty_for_leg(
    dispersion: DispersionSpec, *, q_max: int, leg_index: int, k: int, ask: float
) -> int:
    if dispersion.label == "all_equal":
        return q_max
    if dispersion.label == "two_point":
        half = k // 2
        return q_max if leg_index < (k - half) else 1
    if dispersion.label == "cap_shaped":
        assert dispersion.r is not None
        return min(max(1, math.floor(dispersion.r / ask)), q_max)
    raise ValueError(f"unknown dispersion class {dispersion.label!r}")


def _sides_for_mix(side_mix: SideMix, k: int) -> list[Literal["yes", "no"]]:
    if side_mix == "all_yes":
        return ["yes"] * k
    if side_mix == "all_no":
        return ["no"] * k
    if side_mix == "mixed":
        no_count = max(1, k // 2)
        yes_count = k - no_count
        yes_count = max(1, yes_count)
        no_count = k - yes_count
        return ["yes"] * yes_count + ["no"] * no_count
    raise ValueError(f"unknown side_mix {side_mix!r}")


def sample_station_day(rng: random.Random, cell: CellSpec) -> tuple[StratumRow, ...]:
    """One admissible station-day draw for `cell`, `BE`/`ask` drawn from the
    observed ask distribution (bootstrap resample), respecting the two live
    admission gates by REJECTION SAMPLING (never post-hoc clamping) --
    Amendment C, "the station-day admission gate is enforced at draw
    construction, never post-hoc"."""
    k = cell.k
    sides = _sides_for_mix(cell.side_mix, k)
    for _attempt in range(_MAX_SAMPLE_ATTEMPTS):
        asks = [rng.choice(OBSERVED_ASKS) for _ in range(k)]
        qtys = [
            _qty_for_leg(cell.dispersion, q_max=cell.q_max, leg_index=i, k=k, ask=asks[i])
            for i in range(k)
        ]
        qs = [ask if side == "yes" else (1.0 - ask) for ask, side in zip(asks, sides, strict=True)]
        if sum(qs) > 1.0:
            continue
        u = rng.random()
        cumulative = 0.0
        holder: int | None = None
        for i, q in enumerate(qs):
            cumulative += q
            if u < cumulative:
                holder = i
                break
        rows = tuple(
            StratumRow(
                entry_ask=Decimal(str(round(asks[i], 9))),
                fee=Decimal(0),
                # `held` is the per-side truth (StratumRow docstring):
                # `1{HIGH in r_i}` for YES (i.e. `holder == i`), `1{HIGH
                # NOT in r_i}` for NO (`holder != i`, including the "no
                # rung holds" case `holder is None`) -- NOT the same
                # `i == holder` test for both sides (a real bug caught by
                # `test_the_simulated_null_reproduces_the_registered_h0_variance_exactly`
                # and re-verified by `test_a_be_prior...`-adjacent checks:
                # using `i == holder` for a NO row biases E[held] away
                # from `q_i`, an L-41-class null drift).
                held=(i == holder) if sides[i] == "yes" else (i != holder),
                station="MIA",
                qty=Decimal(qtys[i]),
                side=sides[i],
                rung=f"r{i}",
            )
            for i in range(k)
        )
        return rows
    raise InadmissibleSampleRetryExhausted(
        f"could not construct an admissible station-day for {cell.label} in "
        f"{_MAX_SAMPLE_ATTEMPTS} attempts"
    )


# ---------------------------------------------------------------------------
# One cell's Monte-Carlo (O(1) memory: only scalar accumulators + a
# length-16 per-look history survive a replication -- no per-rep record is
# retained after the rep closes)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CellResult:
    cell_index: int
    label: str
    q_max: int
    dispersion: str
    r: int | None
    k: int
    side_mix: str
    seed: int
    n_reps: int
    crossing_count: int
    crossing_rate: float
    cp_upper: float
    cp_lower: float
    look_ns: tuple[int, ...]
    delta_t: tuple[float, ...]
    var_s: tuple[float, ...]
    max_abs_delta_t: float
    skipped: bool = False
    skip_reason: str | None = None

    def to_json(self) -> dict:
        return {
            "cell_index": self.cell_index,
            "label": self.label,
            "q_max": self.q_max,
            "dispersion": self.dispersion,
            "r": self.r,
            "k": self.k,
            "side_mix": self.side_mix,
            "seed": self.seed,
            "n_reps": self.n_reps,
            "crossing_count": self.crossing_count,
            "crossing_rate": self.crossing_rate,
            "cp_upper": self.cp_upper,
            "cp_lower": self.cp_lower,
            "look_ns": list(self.look_ns),
            "delta_t": list(self.delta_t),
            "var_s": list(self.var_s),
            "max_abs_delta_t": self.max_abs_delta_t,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


def _feasibility_check(cell: CellSpec, *, seed: int) -> str | None:
    """One cheap admissibility probe before committing 20000 reps. Returns
    a skip reason if the (dispersion, k, side_mix) combination cannot
    produce an admissible station-day from the observed ask distribution at
    all -- e.g. `all_no` at k=3 where `1-ask` typically sums well above 1
    for this repo's typically-cheap observed asks -- never a bug in the
    sampler's rejection loop, a genuine structural admissibility fact about
    this ask regime, reported rather than forced. This is a FAST PATH only:
    a combination can be admissible-but-rare (an occasional lucky draw
    exists), in which case this probe may pass and `run_cell`'s own
    try/except around the full replication loop is the authoritative
    catch."""
    probe_rng = random.Random(seed)
    try:
        for _ in range(5):
            sample_station_day(probe_rng, cell)
    except InadmissibleSampleRetryExhausted as exc:
        return str(exc)
    return None


def _skipped_cell_result(cell: CellSpec, *, cell_index: int, seed: int, reason: str) -> CellResult:
    n_looks = 16
    return CellResult(
        cell_index=cell_index,
        label=cell.label,
        q_max=cell.q_max,
        dispersion=cell.dispersion.label,
        r=cell.dispersion.r,
        k=cell.k,
        side_mix=cell.side_mix,
        seed=seed,
        n_reps=0,
        crossing_count=0,
        crossing_rate=float("nan"),
        cp_upper=float("nan"),
        cp_lower=float("nan"),
        look_ns=tuple(range(10, 10 * n_looks + 1, 10)),
        delta_t=(float("nan"),) * n_looks,
        var_s=(float("nan"),) * n_looks,
        max_abs_delta_t=float("nan"),
        skipped=True,
        skip_reason=reason,
    )


def clopper_pearson_upper(successes: int, n: int, *, confidence: float = CP_CONFIDENCE) -> float:
    """One-sided exact Clopper-Pearson upper bound at `confidence`."""
    if successes >= n:
        return 1.0
    return float(stats.beta.ppf(confidence, successes + 1, n - successes))


def clopper_pearson_lower(successes: int, n: int, *, confidence: float = CP_CONFIDENCE) -> float:
    """One-sided exact Clopper-Pearson lower bound at `confidence`."""
    if successes <= 0:
        return 0.0
    return float(stats.beta.ppf(1.0 - confidence, successes, n - successes + 1))


def run_cell(cell: CellSpec, *, cell_index: int, seed: int, n_reps: int = N_REPS) -> CellResult:
    skip_reason = _feasibility_check(cell, seed=seed)
    if skip_reason is not None:
        return _skipped_cell_result(cell, cell_index=cell_index, seed=seed, reason=skip_reason)
    payload = artefact_payload()
    i_max = payload["i_max"]
    n_max = payload["n_max"]
    look_step = payload["look_step"]
    table = payload["reference_table"]
    table_t = [row["t_k"] for row in table]
    table_b_eff = [row["b_eff"] for row in table]
    table_b_fut = [row["b_fut"] for row in table]
    look_ns = tuple(range(look_step, n_max + 1, look_step))
    n_looks = len(look_ns)

    rng = random.Random(seed)
    sum_i = [0.0] * n_looks
    sum_s = [0.0] * n_looks
    sum_s2 = [0.0] * n_looks
    crossings = 0

    try:
        for _rep in range(n_reps):
            cum_x = 0.0
            cum_var = 0.0
            stopped = False
            crossed = False
            draw_idx = 0
            for look_i, n_k in enumerate(look_ns):
                for _d in range(draw_idx, n_k):
                    draw: CombinedDraw = combine_station_day(sample_station_day(rng, cell))
                    cum_x += draw.x
                    cum_var += draw.variance
                draw_idx = n_k
                i_k = cum_var
                t_realised = min(1.0, i_k / i_max) if i_max > 0 else 0.0
                s_k = cum_x / math.sqrt(i_k) if i_k > 0 else 0.0
                sum_i[look_i] += i_k
                sum_s[look_i] += s_k
                sum_s2[look_i] += s_k * s_k
                if not stopped:
                    b_eff = interp(t_realised, table_t, table_b_eff)
                    b_fut = interp(t_realised, table_t, table_b_fut)
                    if s_k >= b_eff:
                        crossed = True
                        stopped = True
                    elif s_k <= b_fut:
                        stopped = True
            if crossed:
                crossings += 1
    except InadmissibleSampleRetryExhausted as exc:
        # A cell that turns out to be near-infeasible only deep into its
        # replications (rare-but-not-impossible admissible draws exhausted
        # the retry budget) is reported exactly like an up-front infeasible
        # cell -- never a partially-completed row.
        return _skipped_cell_result(cell, cell_index=cell_index, seed=seed, reason=str(exc))

    delta_t = []
    var_s = []
    for look_i, n_k in enumerate(look_ns):
        mean_i = sum_i[look_i] / n_reps
        t_realised = min(1.0, mean_i / i_max) if i_max > 0 else 0.0
        t_assumed = n_k / n_max
        delta_t.append(t_realised - t_assumed)
        mean_s = sum_s[look_i] / n_reps
        var_s.append(sum_s2[look_i] / n_reps - mean_s * mean_s)

    crossing_rate = crossings / n_reps
    cp_upper = clopper_pearson_upper(crossings, n_reps)
    cp_lower = clopper_pearson_lower(crossings, n_reps)
    max_abs_delta_t = max(abs(d) for d in delta_t)

    return CellResult(
        cell_index=cell_index,
        label=cell.label,
        q_max=cell.q_max,
        dispersion=cell.dispersion.label,
        r=cell.dispersion.r,
        k=cell.k,
        side_mix=cell.side_mix,
        seed=seed,
        n_reps=n_reps,
        crossing_count=crossings,
        crossing_rate=crossing_rate,
        cp_upper=cp_upper,
        cp_lower=cp_lower,
        look_ns=look_ns,
        delta_t=tuple(delta_t),
        var_s=tuple(var_s),
        max_abs_delta_t=max_abs_delta_t,
    )


def seed_for_cell_index(cell_index: int) -> int:
    return SWEEP_SEED_BASE + cell_index


# ---------------------------------------------------------------------------
# Mechanism verdict (Amendment C "confirmation criterion, machine-checkable")
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MechanismVerdict:
    verdict: Literal["CONFIRMED", "REFUTED", "INDETERMINATE"]
    rho: float | None
    p_value: float | None
    n_cells: int
    reason: str


def _permutation_p_value(
    x: np.ndarray,
    y: np.ndarray,
    observed_rho: float,
    *,
    n_perm: int,
    rng: np.random.Generator,
) -> float:
    count = 0
    y_perm = y.copy()
    for _ in range(n_perm):
        rng.shuffle(y_perm)
        rho, _ = stats.spearmanr(x, y_perm)
        if rho >= observed_rho:
            count += 1
    return (count + 1) / (n_perm + 1)


def compute_mechanism_verdict(
    cell_results: list[CellResult],
    *,
    seed: int = SWEEP_SEED_BASE,
    n_permutations: int = PERMUTATION_COUNT,
) -> MechanismVerdict:
    cell_results = [c for c in cell_results if not c.skipped]
    n_cells = len(cell_results)
    if n_cells < MIN_CONTRIBUTING_CELLS:
        return MechanismVerdict(
            verdict="INDETERMINATE",
            rho=None,
            p_value=None,
            n_cells=n_cells,
            reason=f"only {n_cells} contributing cells, minimum is {MIN_CONTRIBUTING_CELLS}",
        )

    control_cells = [
        c for c in cell_results if c.q_max == 1 and c.k == 1 and c.side_mix == "all_yes"
    ]
    control_ok = bool(control_cells) and all(
        c.max_abs_delta_t <= CONTROL_MAX_ABS_DELTA_T and c.cp_upper <= CONTROL_MAX_CP_UPPER
        for c in control_cells
    )

    x = np.array([c.max_abs_delta_t for c in cell_results])
    y = np.array([c.crossing_rate for c in cell_results])
    rho, _ = stats.spearmanr(x, y)
    rng = np.random.default_rng(seed)
    p_value = _permutation_p_value(x, y, rho, n_perm=n_permutations, rng=rng)

    monotonic_ok = rho >= RHO_THRESHOLD and p_value < PERMUTATION_P_THRESHOLD

    if control_ok:
        control_cp_upper = max(c.cp_upper for c in control_cells)
        for c in cell_results:
            if c.max_abs_delta_t <= CONTROL_MAX_ABS_DELTA_T and c.cp_lower > control_cp_upper:
                return MechanismVerdict(
                    verdict="REFUTED",
                    rho=float(rho),
                    p_value=float(p_value),
                    n_cells=n_cells,
                    reason=(
                        f"cell {c.label} shows no departure (max|dt|={c.max_abs_delta_t:.4f}) "
                        f"but over-crosses (CP lower {c.cp_lower:.4f} > control CP upper "
                        f"{control_cp_upper:.4f})"
                    ),
                )

    if monotonic_ok and control_ok:
        return MechanismVerdict(
            verdict="CONFIRMED",
            rho=float(rho),
            p_value=float(p_value),
            n_cells=n_cells,
            reason=(
                f"rho={rho:.4f} >= {RHO_THRESHOLD}, p={p_value:.5f} < {PERMUTATION_P_THRESHOLD}, "
                "control anchor holds"
            ),
        )

    return MechanismVerdict(
        verdict="INDETERMINATE",
        rho=float(rho),
        p_value=float(p_value),
        n_cells=n_cells,
        reason=(
            f"neither CONFIRMED nor REFUTED: rho={rho:.4f}, p={p_value:.5f}, "
            f"control_ok={control_ok}"
        ),
    )


# ---------------------------------------------------------------------------
# Amendment C2 (post-hoc, made AFTER seeing the first 33 cells --
# prediction-market-reviewer ruling): the ABSOLUTE control anchor
# (`max_k|Δt_k| <= 0.01`) implicitly assumes a `BE~0.5` prior. The observed,
# realistically-cheap ask prior (median 0.22, p75 0.35) makes even the
# `qty=1` control depart from the artefact's assumed `n_k/n_max` schedule
# for reasons structural to the BE prior, not to qty. Condition (3) is
# therefore made BASELINE-RELATIVE: each cell's departure is measured
# against its OWN `q_max=1` cell in the same `(k, side_mix, dispersion, R)`
# stratum, differencing out the qty-independent structural component and
# isolating the qty-induced INCREMENT. Reported under BOTH anchors --
# never only the favourable one.
# ---------------------------------------------------------------------------

#: Reuses the original anchor's numeric value, RE-JUSTIFIED for the
#: baseline-DIFFERENCED quantity (Amendment C2): a `q_max=1` cell is paired
#: with itself and so has baseline-relative departure exactly 0 by
#: construction -- unlike the absolute anchor, this tolerance is
#: satisfiable, and 0.01 remains a meaningful near-zero threshold relative
#: to the observed q_max=2 baseline-relative departures (typically
#: 0.2-0.9, i.e. 20-90x this tolerance -- see the RULING artefact).
BASELINE_RELATIVE_TOLERANCE: Final[float] = 0.01


def stratum_key(cell: CellResult) -> tuple[int, str, str, int | None]:
    """`(k, side_mix, dispersion, R)` -- the stratum a cell is paired within."""
    return (cell.k, cell.side_mix, cell.dispersion, cell.r)


def baseline_relative_max_delta_t(cell: CellResult, baseline: CellResult) -> float:
    """`max_k |Δt_k(cell) - Δt_k(baseline)|` -- the qty-induced INCREMENT
    over the same-stratum `q_max=1` baseline's own departure."""
    return max(abs(a - b) for a, b in zip(cell.delta_t, baseline.delta_t, strict=True))


def _q1_baselines_by_stratum(cell_results: list[CellResult]) -> dict[tuple, CellResult]:
    return {
        stratum_key(c): c
        for c in cell_results
        if c.q_max == 1 and not c.skipped
    }


def compute_mechanism_verdict_c2(
    cell_results: list[CellResult],
    *,
    seed: int = SWEEP_SEED_BASE,
    n_permutations: int = PERMUTATION_COUNT,
    tolerance: float = BASELINE_RELATIVE_TOLERANCE,
) -> MechanismVerdict:
    """Amendment C2's baseline-relative mechanism verdict. Condition (2)
    (monotonicity) is re-run against the baseline-relative departure instead
    of the raw (BE-prior-confounded) `max_abs_delta_t`. Condition (3) (the
    control anchor) becomes: every PAIRABLE `q_max=1` baseline cell has
    (trivially, by construction) 0 departure from itself, AND its own
    CP-upper stays <= alpha -- the qty-independent structural departure
    found by the domain review no longer defeats the anchor."""
    non_skipped = [c for c in cell_results if not c.skipped]
    baselines = _q1_baselines_by_stratum(non_skipped)

    pairable: list[tuple[CellResult, float]] = []
    for c in non_skipped:
        baseline = baselines.get(stratum_key(c))
        if baseline is None:
            continue
        pairable.append((c, baseline_relative_max_delta_t(c, baseline)))

    n_cells = len(pairable)
    if n_cells < MIN_CONTRIBUTING_CELLS:
        return MechanismVerdict(
            verdict="INDETERMINATE",
            rho=None,
            p_value=None,
            n_cells=n_cells,
            reason=f"only {n_cells} pairable cells, minimum is {MIN_CONTRIBUTING_CELLS}",
        )

    q1_cells = [c for c in baselines.values()]
    control_ok = bool(q1_cells) and all(c.cp_upper <= CONTROL_MAX_CP_UPPER for c in q1_cells)

    x = np.array([rel_dt for _c, rel_dt in pairable])
    y = np.array([c.crossing_rate for c, _rel_dt in pairable])
    rho, _ = stats.spearmanr(x, y)
    rng = np.random.default_rng(seed)
    p_value = _permutation_p_value(x, y, rho, n_perm=n_permutations, rng=rng)
    monotonic_ok = rho >= RHO_THRESHOLD and p_value < PERMUTATION_P_THRESHOLD

    if control_ok:
        control_cp_upper = max(c.cp_upper for c in q1_cells)
        for c, rel_dt in pairable:
            if rel_dt <= tolerance and c.cp_lower > control_cp_upper:
                return MechanismVerdict(
                    verdict="REFUTED",
                    rho=float(rho),
                    p_value=float(p_value),
                    n_cells=n_cells,
                    reason=(
                        f"cell {c.label} shows no baseline-relative departure "
                        f"(rel_dt={rel_dt:.4f}) but over-crosses (CP lower "
                        f"{c.cp_lower:.4f} > q_max=1 CP upper {control_cp_upper:.4f})"
                    ),
                )

    if monotonic_ok and control_ok:
        return MechanismVerdict(
            verdict="CONFIRMED",
            rho=float(rho),
            p_value=float(p_value),
            n_cells=n_cells,
            reason=(
                f"[Amendment C2, baseline-relative] rho={rho:.4f} >= {RHO_THRESHOLD}, "
                f"p={p_value:.5f} < {PERMUTATION_P_THRESHOLD}, control anchor holds "
                f"({len(q1_cells)} q_max=1 baseline cells, all CP-upper <= "
                f"{CONTROL_MAX_CP_UPPER})"
            ),
        )

    return MechanismVerdict(
        verdict="INDETERMINATE",
        rho=float(rho),
        p_value=float(p_value),
        n_cells=n_cells,
        reason=(
            f"[Amendment C2] neither CONFIRMED nor REFUTED: rho={rho:.4f}, "
            f"p={p_value:.5f}, control_ok={control_ok}"
        ),
    )


@dataclass(frozen=True, slots=True)
class PairedTrendRow:
    stratum: tuple[int, str, str, int | None]
    q1_crossing_rate: float
    q1_cp_upper: float
    by_q_max: dict[int, float]  # q_max -> crossing_rate, for q_max > 1 in this stratum
    fold_increase: dict[int, float]  # q_max -> crossing_rate / q1_crossing_rate


def paired_trend_table(cell_results: list[CellResult]) -> list[PairedTrendRow]:
    """Stratum-controlled paired trend (Amendment C2 point 3): for each
    `(k, side_mix, dispersion, R)` stratum, the crossing rate at `q_max=1`
    versus every `q_max>1` cell run in the SAME stratum, and the fold
    increase -- confirms or refutes the reviewer's observation ("q_max 1->2
    raised crossing 4-6x... in every sampled stratum") on the full grid."""
    non_skipped = [c for c in cell_results if not c.skipped]
    baselines = _q1_baselines_by_stratum(non_skipped)
    rows: dict[tuple, PairedTrendRow] = {}
    for c in non_skipped:
        if c.q_max == 1:
            continue
        # stratum key without q_max, but WITH k/side_mix/dispersion/r
        key = stratum_key(c)
        baseline = baselines.get(key)
        if baseline is None:
            continue
        row = rows.get(key)
        if row is None:
            row = PairedTrendRow(
                stratum=key,
                q1_crossing_rate=baseline.crossing_rate,
                q1_cp_upper=baseline.cp_upper,
                by_q_max={},
                fold_increase={},
            )
            rows[key] = row
        row.by_q_max[c.q_max] = c.crossing_rate
        row.fold_increase[c.q_max] = (
            c.crossing_rate / baseline.crossing_rate if baseline.crossing_rate > 0 else float("inf")
        )
    return list(rows.values())


# ---------------------------------------------------------------------------
# Envelope selection
# ---------------------------------------------------------------------------
def q_max_validated(cell_results: list[CellResult], *, alpha: float) -> dict[str, int]:
    """Largest `q_max` per `side_mix` whose every swept cell (all dispersion
    x k combinations at that side_mix) has CP-upper <= alpha. `q_max=1`
    (no qty above 1 validates) is a legitimate result for a `side_mix`."""
    by_side: dict[str, dict[int, list[CellResult]]] = {}
    for c in cell_results:
        if c.skipped:
            continue
        by_side.setdefault(c.side_mix, {}).setdefault(c.q_max, []).append(c)

    envelope: dict[str, int] = {}
    for side_mix, by_q in by_side.items():
        validated = 1
        for q_max in sorted(by_q):
            cells_at_q = by_q[q_max]
            if all(c.cp_upper <= alpha for c in cells_at_q):
                validated = q_max
            else:
                break
        envelope[side_mix] = validated
    return envelope


# ---------------------------------------------------------------------------
# Chunked, resumable CLI
# ---------------------------------------------------------------------------
def run_chunk(from_idx: int, to_idx: int, *, out_path: Path, n_reps: int = N_REPS) -> None:
    completed: set[int] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                completed.add(json.loads(line)["cell_index"])
    with out_path.open("a", encoding="utf-8") as fh:
        for cell_index in range(from_idx, to_idx):
            if cell_index in completed:
                continue
            cell = ALL_CELLS[cell_index]
            seed = seed_for_cell_index(cell_index)
            result = run_cell(cell, cell_index=cell_index, seed=seed, n_reps=n_reps)
            fh.write(json.dumps(result.to_json()) + "\n")
            fh.flush()


def load_results(out_path: Path) -> list[CellResult]:
    results = []
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        results.append(
            CellResult(
                cell_index=row["cell_index"],
                label=row["label"],
                q_max=row["q_max"],
                dispersion=row["dispersion"],
                r=row["r"],
                k=row["k"],
                side_mix=row["side_mix"],
                seed=row["seed"],
                n_reps=row["n_reps"],
                crossing_count=row["crossing_count"],
                crossing_rate=row["crossing_rate"],
                cp_upper=row["cp_upper"],
                cp_lower=row["cp_lower"],
                look_ns=tuple(row["look_ns"]),
                delta_t=tuple(row["delta_t"]),
                var_s=tuple(row["var_s"]),
                max_abs_delta_t=row["max_abs_delta_t"],
                skipped=row.get("skipped", False),
                skip_reason=row.get("skip_reason"),
            )
        )
    return sorted(results, key=lambda r: r.cell_index)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", required=True, help="FROM:TO over the canonical cell ordering")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--n-reps", type=int, default=N_REPS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from_str, to_str = args.cells.split(":")
    run_chunk(int(from_str), int(to_str), out_path=args.out, n_reps=args.n_reps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
