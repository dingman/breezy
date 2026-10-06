"""AUT-4 sequential-look core (G36 move, F7a WP1s): `run_sequential_looks`, `LookRecord`
and the per-replicate `StreamingBoundary`.

Every definition below is moved BYTE-IDENTICALLY from `scripts/analysis/family_tally_v2.py`
and `scripts/analysis/aud07_live_rule_crossing_sim.py` (base sha 8bdb5ef1); the scripts re-export
the names. `tests/unit/analysis/stats/test_moved_source_pinned.py` pins the moved source.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

import numpy as np
from numpy.typing import NDArray

from breezy.persistence.gs_boundary_artefact import (
    ALPHA_ONE_SIDED,
    GRID_HALFWIDTH_SD,
    GRID_NPTS,
    BoundaryArtefact,
    _look_step,
    _one_sided_spend,
)
from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    ScoreState,
    TruncationReason,
    information_fraction,
    look_verdict,
    score_combined,
    terminal_look,
)

#: v1 SS6:124-128, restated (never imported -- `mb_current_rung_edge_study`
#: has no module-level constant for this; it is inlined in prose there).
LOSS_STOP_PNL: Final[Decimal] = Decimal(-60)


@dataclass(frozen=True, slots=True, kw_only=True)
class LookRecord:
    """One completed look (interim or terminal) of the pooled sequential test."""

    look_n: int
    t: float
    state: ScoreState
    b_eff: float
    b_fut: float
    verdict: str
    terminal: bool
    reason: TruncationReason | None
    #: B7 (report string only, never a new `TruncationReason` member): True
    #: exactly for the natural "n == n_max reached with I < i_max" trigger
    #: (rev b SS3's third terminal trigger) -- `reason` itself stays
    #: `TruncationReason.I_MAX` either way; this only tells the renderer to
    #: print `terminal=n_max_reached` instead of `truncation=I_MAX` for
    #: this specific sub-case.
    n_max_reached_below_i_max: bool = False


class _BoundaryFn(Protocol):
    """The exact call shape `run_sequential_looks` needs off `boundary_fn`
    -- structurally satisfied by `BoundaryArtefact.boundary_for` (a bound
    method, `t_history: Sequence[float], *, is_terminal: bool = False`)
    without importing it as a nominal type. Every call site here passes
    `is_terminal` explicitly (never relies on a default), so it is
    declared required, matching actual usage exactly rather than merely
    matching `boundary_for`'s own (wider) signature."""

    def __call__(
        self, t_history: tuple[float, ...], *, is_terminal: bool
    ) -> tuple[float, float]: ...


def run_sequential_looks(
    combined_draws: Sequence[CombinedDraw],
    *,
    artefact: BoundaryArtefact,
    boundary_fn: _BoundaryFn,
    total_pnl: Decimal,
    residual: Decimal,
    cell_dead: bool,
    structural_fired: bool,
    registered: bool,
    truncation: TruncationReason | None,
) -> tuple[tuple[LookRecord, ...], str, bool]:
    """Replay the pooled sequential look loop (rev b Sec 3/4), including the
    off-grid truncation tail -- extracted verbatim from
    `build_family_tally_v2` (AUD-07 amendment Stage M1b, L-33
    characterisation: `tests/unit/test_family_tally_v2_look_loop_golden.py`
    pins this function's behaviour unchanged by the extraction).

    Returns `(looks, verdict, decided)`. `decided` is `True` exactly when a
    terminal or non-CONTINUE interim verdict was reached (main loop `break`,
    or the off-grid tail ran) -- the caller computes `bca_line` (via
    `_roi_bound_line_v2`, which needs `roi_rows`, a caller-only concern)
    only when `decided` is `True`, byte-identical to the pre-extraction
    `bca_line is None` cases (structural KILL with zero looks; a plain
    CONTINUE below `look_step` with no truncation).

    `boundary_fn` is a separate parameter from `artefact` (whose
    `i_max`/`spending.look_step`/`spending.n_max` are still read here) so a
    future streaming solver (plan §4 M1c) can pass its own `(t_history,
    is_terminal) -> (b_eff, b_fut)` callable without touching this loop --
    production always passes `artefact.boundary_for`.
    """
    n = len(combined_draws)
    look_step = artefact.spending.look_step
    n_max = artefact.spending.n_max

    looks: list[LookRecord] = []
    t_history: list[float] = []
    verdict = "CONTINUE"

    # Structural-dead is a separate KILL authority: never overwritten by a
    # later look_verdict/terminal_look assignment. Skip the look loop
    # entirely -- no look, no BCa line.
    if structural_fired and registered:
        return (), "KILL", False

    scheduled_ns = range(look_step, min(n, n_max) + 1, look_step)
    for look_n in scheduled_ns:
        state = score_combined(combined_draws[:look_n])
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)

        reached_loss_stop = (total_pnl + residual) <= LOSS_STOP_PNL
        reached_i_max = state.information >= artefact.i_max
        reached_n_max = (
            look_n >= n_max
        )  # B5: >= not == (see load_boundary_artefact's n_max%look_step==0 invariant)
        forced = truncation is not None and look_n == n
        is_terminal = reached_loss_stop or reached_i_max or reached_n_max or forced

        if is_terminal:
            reason = (
                TruncationReason.LOSS_STOP
                if reached_loss_stop
                else (truncation if forced and truncation is not None else TruncationReason.I_MAX)
            )
            n_max_reached_below_i_max = (
                reason is TruncationReason.I_MAX and reached_n_max and not reached_i_max
            )
            b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=True)
            verdict = terminal_look(
                state,
                reason=reason,
                b_eff=b_eff,
                b_fut=b_fut,
                total_pnl=total_pnl,
                cell_dead=cell_dead,
                structural_fired=structural_fired,
            )
            looks.append(
                LookRecord(
                    look_n=look_n,
                    t=t,
                    state=state,
                    b_eff=b_eff,
                    b_fut=b_fut,
                    verdict=verdict,
                    terminal=True,
                    reason=reason,
                    n_max_reached_below_i_max=n_max_reached_below_i_max,
                )
            )
            return tuple(looks), verdict, True

        b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=False)
        verdict = look_verdict(
            state,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=cell_dead,
            structural_fired=structural_fired,
        )
        looks.append(
            LookRecord(
                look_n=look_n,
                t=t,
                state=state,
                b_eff=b_eff,
                b_fut=b_fut,
                verdict=verdict,
                terminal=False,
                reason=None,
            )
        )
        if verdict != "CONTINUE":
            return tuple(looks), verdict, True

    already_terminal = bool(looks) and looks[-1].terminal
    if (
        not (structural_fired and registered)
        and truncation is not None
        and not already_terminal
        and combined_draws
    ):
        # An off-grid explicit truncation (n does not land on a look_step
        # boundary): treated as a look too, never a skipped None (rev b
        # SS4).
        state = score_combined(combined_draws)
        t = information_fraction(state.information, i_max=artefact.i_max)
        t_history.append(t)
        b_eff, b_fut = boundary_fn(tuple(t_history), is_terminal=True)
        verdict = terminal_look(
            state,
            reason=truncation,
            b_eff=b_eff,
            b_fut=b_fut,
            total_pnl=total_pnl,
            cell_dead=cell_dead,
            structural_fired=structural_fired,
        )
        looks.append(
            LookRecord(
                look_n=n,
                t=t,
                state=state,
                b_eff=b_eff,
                b_fut=b_fut,
                verdict=verdict,
                terminal=True,
                reason=truncation,
            )
        )
        return tuple(looks), verdict, True

    return tuple(looks), verdict, False


# fmt: off
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
# fmt: on
