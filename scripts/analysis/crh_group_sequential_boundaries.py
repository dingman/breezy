#!/usr/bin/env python3
"""Group-sequential efficacy/futility boundaries for PREREG v2 current_rung_hold.

Spec: `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` SS7 (script
contract), amended by the strategy lead's ratification
(`docs/evidence/grok_prereg_v2_ratification_2026-09-04.md` SS Final ruling
(1)(a)-(c)) and superseded on the INTERIM STATISTIC by the later binding
ruling `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md`: the live
interim statistic is the per-row centred score

    S_k = sum_i(held_i - BE_i) / sqrt(sum_i BE_i*(1-BE_i))

with information I_k = sum_i BE_i*(1-BE_i), information fraction
t_k = min(1, I_k / I_max), and I_max PINNED to n_max/4 (the Bernoulli
variance bound BE*(1-BE) <= 1/4, not an empirical estimate). Looks still fire
every `--look-step` filled Takes; the boundary is evaluated at the REALIZED
t_k via `boundary_for`, a Lan-DeMets recursion that accepts an ARBITRARY
(non-equally-spaced) history of information fractions -- not just the fixed
n_k/n_max grid. The 16-row `reference_table` in the JSON output is a
REGRESSION FIXTURE only: `boundary_for` evaluated at the canonical equally
spaced t_k = k/K grid, used to pin determinism and as the interpolation
source for simulation (SS "Simulation" below); it is not itself the live
per-look mechanism.

Spending function (Lan & DeMets 1983, the O'Brien-Fleming-type
alpha-spending approximation; see also Jennison & Turnbull 2000 SS7.2):

    alpha*(t) = 2 - 2*Phi(z_{alpha/2} / sqrt(t))          (combined two-sided)

Two one-sided tests, each at level `alpha` (0.025 default), split this
combined function exactly in half by symmetry:

    one_sided_spend(t) = alpha*(t) / 2 = 1 - Phi(z_half / sqrt(t))
    z_half = Phi^-1(1 - alpha)

so `one_sided_spend(1) == alpha` exactly, and `z_half == 1.959963984540054`
(v1's Wilson z, `mb_current_rung_edge_study.py:352`) when alpha=0.025.

Boundary recursion (Armitage-McPherson-Rowe / Jennison-Turnbull): the joint
density of the standardized Brownian-motion representation of the score
process is propagated on a numerical grid; at every look (non-terminal AND
terminal) the efficacy/futility boundaries are root-found so the incremental
crossing probability (integrated over the density restricted to the
still-alive region -- BINDING futility) matches a target spending increment.
At a non-terminal look that target is the natural Lan-DeMets spending-function
increment `one_sided_spend(t_k) - one_sided_spend(t_{k-1})`. At the TERMINAL
look -- t >= 1 (schedule/information budget exhausted) OR an early stop via
`truncate_at`, i.e. the last look that will actually be evaluated -- the
target is instead EXACTLY the remaining alpha, `alpha - alpha_spent(previous
looks)` (binding coordinator clarification, PREREG v2 SS4, committed
`ca94177`, superseding an earlier rejected draft that forced the terminal
boundary to `z_half` and only reached cumulative alpha 0.0312). Spending the
remainder rather than forcing the boundary keeps `alpha_spent_eff` /
`alpha_spent_fut` at the terminal look equal to `alpha` (0.025) to floating
point precision by construction, for ANY terminal look including a truncated
one. The resulting terminal boundary equals `z_half` exactly only in the
single-look limit (K=1, where the terminal look is also the first look, so
the "remaining alpha" is all of it and the density is still the unconditional
N(0, t)); for K=16 equal looks it lands slightly above `z_half` (measured; see
tests). This is a numerical solve, not an approximation to a "final analysis
uses the nominal fixed-sample test" convention -- there is no such special
case in this recursion.

Tie guard (spec "Tie guard (convergence edit)"): `I_k` is a sum of
non-negative terms, so `t` can never decrease across a real history. A tie
(`t_k == t_{k-1}`, zero new information) is accepted as a valid look with a
zero spending increment and a degenerate CONTINUE-forced boundary (`+inf` /
`-inf` on the Z-scale before the final look's rescale -- nothing can cross);
only a strict decrease raises, since that can only be a wiring defect.

No network. No repo writes except `--out`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
from numpy.random import Generator, default_rng

from breezy.analysis.stats.group_sequential_boundaries import (  # noqa: F401
    BRENTQ_XTOL,
    DEFAULT_ALPHA,
    GRID_HALFWIDTH_SD,
    GRID_NPTS,
    LookRow,
    _convolve_density,
    _iter_boundary_looks,
    _look_step,
    _tail_probs,
    boundary_for,
    build_reference_table,
    i_max_for,
    one_sided_spend,
    one_sided_z_half,
)

# --- Frozen constants -------------------------------------------------------

Z_ALPHA_ONE_SIDED: Final[float] = 1.959963984540054  # z_{0.975}; v1's Wilson z.


DEFAULT_N_MAX: Final[int] = 160
DEFAULT_LOOK_STEP: Final[int] = 10
SPENDING_FUNCTION_ID: Final[str] = "lan_demets_obrien_fleming_1983_symmetric_two_one_sided"

# Numerical-grid resolution for the recursive integration. Not a free
# parameter of the design (does not enter the sha256 input manifest) --
# it is a numerical-accuracy knob only.


# Fixture for the drifting-ask simulation (SS "Simulation").
DRIFT_ASK_LOW: Final[float] = 0.20
DRIFT_ASK_HIGH: Final[float] = 0.60
DRIFT_FEE_THETA: Final[float] = 0.06  # mb_current_rung_edge_study.py FEE_THETA


# --- Recursive joint-density boundary solver (arbitrary t grid) -------------


# --- Provenance --------------------------------------------------------------


def inputs_manifest(
    alpha: float, spending_id: str, n_max: int, i_max: float, look_step: int
) -> dict:
    return {
        "alpha": alpha,
        "spending_function_id": spending_id,
        "n_max": n_max,
        "i_max": i_max,
        "look_step": look_step,
    }


def sha256_of_inputs(manifest: dict) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def solver_fingerprint() -> str:
    """Diagnostic sha256 over the numerical-grid constants (`GRID_NPTS`,
    `GRID_HALFWIDTH_SD`, `BRENTQ_XTOL`) and the spending function id. This is
    NOT the registered inputs pin (`inputs_sha256`, which correctly excludes
    these per the spec -- SS7 pins design inputs only, not numerical-accuracy
    knobs) and is never used for admission. It exists so a silent change to a
    grid constant -- which moves `b_eff`/`b_fut` by a small but real amount
    even though `inputs_sha256` stays byte-identical -- is at least visible
    in the artefact; read module globals at call time so it tracks whatever
    values were actually in effect when the table was built."""
    blob = json.dumps(
        {
            "grid_npts": GRID_NPTS,
            "grid_halfwidth_sd": GRID_HALFWIDTH_SD,
            "brentq_xtol": BRENTQ_XTOL,
            "spending_function_id": SPENDING_FUNCTION_ID,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_output(
    alpha: float, n_max: int, look_step: int, *, truncate_at: int | None = None
) -> dict:
    i_max = i_max_for(n_max)
    manifest = inputs_manifest(alpha, SPENDING_FUNCTION_ID, n_max, i_max, look_step)
    sha = sha256_of_inputs(manifest)
    rows = build_reference_table(alpha, n_max, look_step, i_max, truncate_at=truncate_at)
    return {
        "alpha": alpha,
        "spending_id": SPENDING_FUNCTION_ID,
        "n_max": n_max,
        "i_max": i_max,
        "look_step": look_step,
        "inputs_sha256": sha,
        "solver_fingerprint": solver_fingerprint(),
        "usage": (
            "regression_fixture_only; live boundaries via boundary_for(t_history) "
            "at realized t_k = min(1, I_k/I_max)"
        ),
        "reference_table": [r.to_dict() for r in rows],
    }


# --- Simulation --------------------------------------------------------------


def simulate_fixed_pi(
    reference_table: list[LookRow], pi: float, delta: float, *, n_reps: int, seed: int
) -> dict:
    """Fixed-pi Bernoulli-fills simulation (informational; the design's live
    statistic is the drifting-ask score S_k below, not this fixed-pi form).
    Deterministic t_k = n_k/n_max matches the reference table's own grid
    exactly, so no interpolation is needed here."""
    rng = default_rng(seed)
    n_ks = np.array([r.n_k for r in reference_table])
    b_eff = np.array([r.b_eff for r in reference_table])
    b_fut = np.array([r.b_fut for r in reference_table])

    def run(p: float) -> dict:
        fills = rng.random((n_reps, n_ks[-1])) < p
        cum_hold = np.cumsum(fills, axis=1)
        k_at_look = cum_hold[:, n_ks - 1]
        phat = k_at_look / n_ks[None, :]
        z = (phat - pi) / np.sqrt(pi * (1 - pi) / n_ks[None, :])

        stop_look = np.zeros(n_reps, dtype=int)
        verdict = np.array(["none"] * n_reps, dtype=object)
        alive = np.ones(n_reps, dtype=bool)
        for j in range(len(n_ks)):
            eff_cross = alive & (z[:, j] >= b_eff[j])
            fut_cross = alive & (z[:, j] <= b_fut[j])
            stop_look[eff_cross] = j + 1
            verdict[eff_cross] = "efficacy"
            stop_look[fut_cross] = j + 1
            verdict[fut_cross] = "futility"
            alive = alive & ~eff_cross & ~fut_cross
        stop_look[alive] = len(n_ks)
        verdict[alive] = "underpowered"
        asn = float(np.mean(n_ks[stop_look - 1]))
        return {
            "asn": asn,
            "p_efficacy": float(np.mean(verdict == "efficacy")),
            "p_futility": float(np.mean(verdict == "futility")),
            "p_underpowered": float(np.mean(verdict == "underpowered")),
        }

    return {"leak_p_eq_pi": run(pi), "edge_p_eq_pi_plus_delta": run(pi + delta)}


def _drift_replicate_asks(rng: Generator, n: int) -> np.ndarray:
    return rng.uniform(DRIFT_ASK_LOW, DRIFT_ASK_HIGH, size=n)


def _break_even(ask: np.ndarray) -> np.ndarray:
    return ask + DRIFT_FEE_THETA * ask * (1.0 - ask)


def simulate_drift(
    reference_table: list[LookRow],
    alpha: float,
    n_max: int,
    i_max: float,
    delta: float,
    *,
    n_reps: int,
    seed: int,
) -> dict:
    """Drifting-ask DGP: per replicate, draw asks ~ U(0.20,0.60), BE_i = ask_i
    + 0.06*ask_i*(1-ask_i), held_i ~ Bernoulli(BE_i + shift). At each look
    n_k, evaluate BOTH:
      - S_k (the ADOPTED, valid statistic): centred score, info fraction
        t_k = min(1, I_k/I_max), boundary interpolated from `reference_table`
        at the realized t_k (a practical stand-in for a fresh `boundary_for`
        call per replicate/look, which is not tractable at this replicate
        count -- `boundary_for` itself is unit-tested against the equal-t
        grid it approximates).
      - Z_k (the REJECTED plug-in form): (phat_k - mean(BE_i)) / sqrt(mean(BE_i)
        *(1-mean(BE_i))/n_k), same interpolated boundary, reported for
        contrast only.
    """
    rng = default_rng(seed)
    n_ks = np.array([r.n_k for r in reference_table])
    table_t = np.array([r.t_k for r in reference_table])
    table_beff = np.array([r.b_eff for r in reference_table])
    table_bfut = np.array([r.b_fut for r in reference_table])

    def interp_boundary(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # No terminal override: `reference_table`'s last row (t_k == 1.0)
        # already holds the solved (never forced) terminal boundary, and
        # `np.interp` flat-extrapolates to that value for t >= 1.0.
        beff = np.interp(t, table_t, table_beff)
        bfut = np.interp(t, table_t, table_bfut)
        return beff, bfut

    def run(shift: float) -> dict:
        n = n_ks[-1]
        asks = rng.uniform(DRIFT_ASK_LOW, DRIFT_ASK_HIGH, size=(n_reps, n))
        be = _break_even(asks)
        p_hold = np.clip(be + shift, 0.0, 1.0)
        held = rng.random((n_reps, n)) < p_hold

        cum_be_var = np.cumsum(be * (1 - be), axis=1)
        cum_resid = np.cumsum(held - be, axis=1)
        cum_be = np.cumsum(be, axis=1)
        cum_held = np.cumsum(held, axis=1)

        idx = n_ks - 1
        I_k = cum_be_var[:, idx]
        t_k = np.minimum(1.0, I_k / i_max)
        S_k = cum_resid[:, idx] / np.sqrt(cum_be_var[:, idx])
        mean_be_k = cum_be[:, idx] / n_ks[None, :]
        phat_k = cum_held[:, idx] / n_ks[None, :]
        Z_k = (phat_k - mean_be_k) / np.sqrt(mean_be_k * (1 - mean_be_k) / n_ks[None, :])

        def crossings(stat: np.ndarray, t: np.ndarray) -> dict:
            beff, bfut = interp_boundary(t)
            stop_look = np.zeros(n_reps, dtype=int)
            verdict = np.array(["none"] * n_reps, dtype=object)
            alive = np.ones(n_reps, dtype=bool)
            for j in range(len(n_ks)):
                eff_cross = alive & (stat[:, j] >= beff[:, j])
                fut_cross = alive & (stat[:, j] <= bfut[:, j])
                stop_look[eff_cross] = j + 1
                verdict[eff_cross] = "efficacy"
                stop_look[fut_cross] = j + 1
                verdict[fut_cross] = "futility"
                alive = alive & ~eff_cross & ~fut_cross
            stop_look[alive] = len(n_ks)
            verdict[alive] = "underpowered"
            asn = float(np.mean(n_ks[stop_look - 1]))
            return {
                "asn": asn,
                "p_efficacy": float(np.mean(verdict == "efficacy")),
                "p_futility": float(np.mean(verdict == "futility")),
                "p_underpowered": float(np.mean(verdict == "underpowered")),
            }

        return {
            "score_S_k_valid": crossings(S_k, t_k),
            "plugin_Z_k_rejected": crossings(Z_k, n_ks[None, :] / float(n_max) * np.ones_like(t_k)),
        }

    return {"type_i_delta_0": run(0.0), "power_delta": run(delta)}


# --- CLI ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    p.add_argument("--n-max", type=int, default=DEFAULT_N_MAX)
    p.add_argument("--look-step", type=int, default=DEFAULT_LOOK_STEP)
    p.add_argument("--pi", type=float, required=True)
    p.add_argument("--delta", type=float, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--truncate-at", type=int, default=None)
    p.add_argument("--sim-reps", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=20260904)
    p.add_argument("--pi-drift", action="store_true", help="also run the drifting-ask simulation")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output = build_output(args.alpha, args.n_max, args.look_step, truncate_at=args.truncate_at)
    rows = [LookRow(**r) for r in output["reference_table"]]

    fixed_pi_sim = simulate_fixed_pi(
        rows, args.pi, args.delta, n_reps=args.sim_reps, seed=args.seed
    )
    output["simulation_fixed_pi"] = fixed_pi_sim

    drift_sim = simulate_drift(
        rows,
        args.alpha,
        args.n_max,
        output["i_max"],
        args.delta,
        n_reps=args.sim_reps,
        seed=args.seed,
    )
    output["simulation_drift"] = drift_sim

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
