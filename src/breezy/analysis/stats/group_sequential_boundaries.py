"""Group-sequential (Lan-DeMets O'Brien-Fleming) boundary solver (G36 move, F7a WP1s).

Moved BYTE-IDENTICALLY from `scripts/analysis/crh_group_sequential_boundaries.py` (base sha
8bdb5ef1): the joint-density recursion, `boundary_for`, `LookRow` and `build_reference_table`.
The CLI, provenance and simulation code stay in the script, which re-exports every moved name.
See the script module docstring for the spending-function derivation.
"""

# mypy: disable-error-code="no-any-return"
# (`_convolve_density` returns an untyped `np.trapezoid`; the source is moved byte-identically,
# so the finding is silenced for this module rather than edited away.)
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.optimize import brentq
from scipy.stats import norm

DEFAULT_ALPHA: Final[float] = 0.025


GRID_NPTS: Final[int] = 2001


GRID_HALFWIDTH_SD: Final[float] = 9.0


BRENTQ_XTOL: Final[float] = 1e-10


def one_sided_z_half(alpha: float) -> float:
    """z_half = Phi^-1(1-alpha); equals Z_ALPHA_ONE_SIDED at alpha=0.025."""
    return float(norm.ppf(1.0 - alpha))


def one_sided_spend(t: float, alpha: float) -> float:
    """One-sided Lan-DeMets O'Brien-Fleming-type cumulative spend at info
    fraction `t` (see module docstring for the source formula and the
    two-sided->one-sided halving)."""
    if t <= 0.0:
        return 0.0
    t = min(t, 1.0)
    z_half = one_sided_z_half(alpha)
    return 1.0 - float(norm.cdf(z_half / np.sqrt(t)))


def i_max_for(n_max: int) -> float:
    """Pinned information ceiling: n_max/4, the Bernoulli variance bound
    BE*(1-BE) <= 1/4 achieved only at BE=0.5 -- not an empirical estimate."""
    return n_max / 4.0


def _convolve_density(
    grid_prev: np.ndarray, dens_prev: np.ndarray, grid_new: np.ndarray, dt: float
) -> np.ndarray:
    diffs = grid_new[:, None] - grid_prev[None, :]
    kernel = norm.pdf(diffs, 0.0, np.sqrt(dt))
    return np.trapezoid(kernel * dens_prev[None, :], grid_prev, axis=1)


def _tail_probs(
    grid: np.ndarray, dens: np.ndarray
) -> tuple[float, Callable[[float], float], Callable[[float], float]]:
    cum = cumulative_trapezoid(dens, grid, initial=0.0)
    total = float(cum[-1])

    def upper(b: float) -> float:
        return total - float(np.interp(b, grid, cum, left=0.0, right=total))

    def lower(b: float) -> float:
        return float(np.interp(b, grid, cum, left=0.0, right=total))

    return total, upper, lower


def _look_step(
    t: float,
    prev_t: float,
    grid: np.ndarray | None,
    dens: np.ndarray | None,
    target: float,
    npts: int,
    halfwidth_sd: float,
) -> tuple[float, float, np.ndarray | None, np.ndarray | None, float]:
    """Advance the joint-density recursion by one look.

    Returns Brownian-scale `(b_eff, b_fut)`, the truncated `(grid, dens)` to
    carry forward, and `t` as the next `prev_t`. A tie (`dt == 0`) yields a
    degenerate CONTINUE-forced boundary and leaves the density unchanged.
    """
    dt = t - prev_t
    if dt < 0.0:
        raise ValueError("t_history must be non-decreasing (a strict decrease is a wiring defect)")
    if dt == 0.0:
        return float("inf"), float("-inf"), grid, dens, t

    hw = max(6.0, halfwidth_sd * np.sqrt(t))
    newgrid = np.linspace(-hw, hw, npts)
    if grid is None or dens is None:
        newdens = norm.pdf(newgrid, 0.0, np.sqrt(t))
    else:
        newdens = _convolve_density(grid, dens, newgrid, dt)

    _total, upper, lower = _tail_probs(newgrid, newdens)

    def cross_eff(
        b: float, upper: Callable[[float], float] = upper, target: float = target
    ) -> float:
        return upper(b) - target

    def cross_fut(
        b: float, lower: Callable[[float], float] = lower, target: float = target
    ) -> float:
        return lower(b) - target

    b_eff = brentq(cross_eff, newgrid[0], newgrid[-1], xtol=BRENTQ_XTOL)
    b_fut = brentq(cross_fut, newgrid[0], newgrid[-1], xtol=BRENTQ_XTOL)
    mask = (newgrid > b_fut) & (newgrid < b_eff)
    return b_eff, b_fut, newgrid, newdens * mask, t


def _iter_boundary_looks(
    t_history: Sequence[float],
    alpha: float,
    *,
    is_terminal: bool,
    npts: int = GRID_NPTS,
    halfwidth_sd: float = GRID_HALFWIDTH_SD,
) -> Iterator[tuple[float, float]]:
    """Yield Z-scale `(b_eff, b_fut)` at each look, carrying density forward.

    `is_terminal=True` retargets only the LAST look to remaining alpha.
    Arbitrary live `t_history` still starts from t=0 on every call; equal-t
    table builders consume this generator once instead of restarting.
    """
    if not t_history:
        raise ValueError("t_history must be non-empty")
    target_cum = [one_sided_spend(t, alpha) for t in t_history]
    incr = np.diff(np.concatenate(([0.0], target_cum)))

    grid: np.ndarray | None = None
    dens: np.ndarray | None = None
    prev_t = 0.0
    n_looks = len(t_history)
    for idx, t in enumerate(t_history):
        is_last = idx == n_looks - 1
        if is_terminal and is_last:
            prev_natural_cum = target_cum[idx - 1] if idx > 0 else 0.0
            target = alpha - prev_natural_cum
        else:
            target = incr[idx]
        b_eff, b_fut, grid, dens, prev_t = _look_step(
            t, prev_t, grid, dens, target, npts, halfwidth_sd
        )
        z_scale = np.sqrt(t)
        yield b_eff / z_scale, b_fut / z_scale


def boundary_for(
    t_history: Sequence[float],
    alpha: float = DEFAULT_ALPHA,
    *,
    is_terminal: bool = False,
    npts: int = GRID_NPTS,
    halfwidth_sd: float = GRID_HALFWIDTH_SD,
) -> tuple[float, float]:
    """The current-look (b_eff, b_fut) on the Z-scale, given the full history
    of realized information fractions up to and including the current look
    (`t_history[-1]`). Recomputes the joint-density recursion from t=0 over
    the given (possibly unequally spaced) history -- correct for arbitrary
    grids, at the cost of recomputing prior looks on every call. `is_terminal`
    retargets the LAST look's solve to spend exactly the remaining alpha
    (`alpha - alpha_spent(previous looks)`) instead of the natural
    spending-function increment (see module docstring); the boundary is
    still root-found, never forced to a fixed value. A tie in `t_history`
    (`t_k == t_{k-1}`) is a valid zero-increment look with a degenerate
    CONTINUE-forced boundary; only a strict decrease raises.
    """
    result: tuple[float, float] | None = None
    for result in _iter_boundary_looks(
        t_history, alpha, is_terminal=is_terminal, npts=npts, halfwidth_sd=halfwidth_sd
    ):
        pass
    if result is None:
        raise ValueError("t_history must be non-empty")
    return result


@dataclass(frozen=True, slots=True)
class LookRow:
    look_k: int
    n_k: int
    t_k: float
    b_eff: float
    b_fut: float
    alpha_spent_eff: float
    alpha_spent_fut: float

    def to_dict(self) -> dict[str, float | int]:
        # Explicit per-field construction: `dataclasses.asdict` is banned
        # under src/ and scripts/ by the closed allowlist in
        # `tests/unit/test_polymarket_us_credential_serialization.py`.
        return {
            "look_k": self.look_k,
            "n_k": self.n_k,
            "t_k": self.t_k,
            "b_eff": self.b_eff,
            "b_fut": self.b_fut,
            "alpha_spent_eff": self.alpha_spent_eff,
            "alpha_spent_fut": self.alpha_spent_fut,
        }


def build_reference_table(
    alpha: float, n_max: int, look_step: int, i_max: float, *, truncate_at: int | None = None
) -> list[LookRow]:
    """Regression-fixture table: one forward walk of the joint-density
    recursion over the canonical equally spaced t_k = n_k/n_max grid
    (n_k = look_step, 2*look_step, ...). Equivalent to `boundary_for` on
    each growing prefix (with `is_terminal` only on the last look) but
    carrying `(grid, dens, prev_t)` from look k to look k+1. The LAST row
    in the (possibly truncated) table is always the terminal look: it spends
    exactly the remaining alpha at its t_k, whether that is the natural end
    of the 16-look schedule or an early stop via `truncate_at` (binding
    ruling, `ca94177`) -- `alpha_spent_eff` and `alpha_spent_fut` equal
    `alpha` there by construction, not merely by approximation."""
    if n_max % look_step != 0:
        raise ValueError("n_max must be a multiple of look_step")
    n_ks = list(range(look_step, n_max + 1, look_step))
    if truncate_at is not None:
        if truncate_at not in n_ks:
            raise ValueError("truncate_at must be a scheduled look")
        n_ks = [n for n in n_ks if n <= truncate_at]
    ts = [n / n_max for n in n_ks]

    rows: list[LookRow] = []
    cum_eff = 0.0
    cum_fut = 0.0
    prev_cum_target = 0.0
    walked = _iter_boundary_looks(tuple(ts), alpha, is_terminal=True)
    for idx, ((n_k, t), (b_eff, b_fut)) in enumerate(
        zip(zip(n_ks, ts, strict=True), walked, strict=True)
    ):
        is_terminal = idx == len(n_ks) - 1
        if is_terminal:
            # Solved to spend exactly the remaining alpha (see boundary_for
            # / module docstring): cumulative equals `alpha` by construction,
            # not by recomputing the achieved crossing probability.
            cum_eff = alpha
            cum_fut = alpha
        else:
            target_cum_here = one_sided_spend(t, alpha)
            incr_target = target_cum_here - prev_cum_target
            prev_cum_target = target_cum_here
            cum_eff += incr_target
            cum_fut += incr_target
        rows.append(
            LookRow(
                look_k=idx + 1,
                n_k=n_k,
                t_k=t,
                b_eff=b_eff,
                b_fut=b_fut,
                alpha_spent_eff=cum_eff,
                alpha_spent_fut=cum_fut,
            )
        )
    return rows
