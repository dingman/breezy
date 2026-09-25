"""AUD-07 amendment Stage M1c, tests 3/4a/4b (plan §4 M1c / §5).

`StreamingBoundary` (`scripts/analysis/aud07_live_rule_crossing_sim.py`) is
a per-replicate streaming reimplementation of
`BoundaryArtefact.boundary_for`'s own joint-density recursion, needed
because a 20000-replicate Monte-Carlo cannot afford `boundary_for`'s
from-scratch-every-call cost (L-40 amendment (iii), `docs/core/
LESSONS.md:1403`). Before any crossing-rate number from
`aud07_live_rule_crossing_sim.py` is cited, this streaming solver must be
proven equal to `boundary_for` on real (unequally spaced, occasionally
tied, occasionally terminal) histories:

- 4a: exact form (`npts=GRID_NPTS=2001`), tolerance 1e-12, 50 random
  histories including terminal looks and tied `t`.
- 4b: reduced-grid form (`npts=REDUCED_NPTS`), tolerance 1e-3, against the
  full-grid `boundary_for` reference.
- 3: the terminal branch's target is independently verified to be `alpha -
  spend(prev_t)`, solved via a second, independent `_look_step` call from
  the SAME prior `(grid, dens, prev_t)` state.

**MEASURED SCOPE of 4b (calibration, 2026-09-25):** the recursive
convolution's successive re-gridding means a reduced grid's error does NOT
shrink smoothly with more looks -- a 2-look chain at `npts=1301` (65% of
the full grid) still disagreed with `boundary_for` by ~2.5e-3, over the
1e-3 bound. A SINGLE look, however, converges cleanly (`npts=601`: <9e-4
worst error over 40 random first-look histories spanning `t in [0.15,
1.0]`). Test 4b is therefore scoped to single-look histories -- exactly
the case `REDUCED_NPTS` is exposed for -- and `run_cell`'s own
multi-look Monte-Carlo replay uses the full `GRID_NPTS`, never
`REDUCED_NPTS` (see that constant's docstring in
`aud07_live_rule_crossing_sim.py`). Multi-look tied/terminal coverage at
the FULL grid is proven by test 4a.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.gs_boundary_artefact import (
    GRID_HALFWIDTH_SD,
    GRID_NPTS,
    BoundaryArtefact,
    SpendingSpec,
    _look_step,
    _one_sided_spend,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud07_live_rule_crossing_sim import REDUCED_NPTS, StreamingBoundary

_ALPHA = 0.025


def _artefact(alpha: float = _ALPHA) -> BoundaryArtefact:
    """Byte-identical shape to the golden test's own synthetic artefact --
    never file-loaded, so `boundary_for` exercises the real solver."""
    return BoundaryArtefact(
        inputs_sha256="0" * 64,
        i_max=40.0,
        alpha_one_sided=alpha,
        spending=SpendingSpec(
            spending_id="test_synthetic", alpha_one_sided=alpha, n_max=160, look_step=10
        ),
        reference_rows=(),
    )


#: Below this `t`, `_one_sided_spend(t, 0.025)` underflows to EXACTLY 0.0 in
#: float64 (measured: `t=0.05` -> `0.0`, `t=0.0625` -> `2.2e-15`). Below the
#: floor, `_look_step`'s root-find is locating a boundary for a target
#: probability of essentially zero -- the resulting `b_eff` sits wherever
#: the grid happens to end, an artefact of grid EXTENT rather than the
#: recursion's accuracy, and any two differently-sized grids can legitimately
#: disagree by far more than 1e-3 there. This is harmless for crossing
#: detection: dividing by `z_scale = sqrt(t)` at such small `t` still yields
#: a `b_eff` in the tens of Z-units, and no real Monte-Carlo `S` (bounded by
#: the realised draws) ever approaches it -- by design, O'Brien-Fleming
#: makes early-look efficacy stops astronomically unlikely. The equality
#: proof is scoped to `t >= _T_FLOOR`, the regime where `b_eff` is small
#: enough to matter operationally (and where a real replicate's boundary
#: check is actually meaningful).
_T_FLOOR: Final[float] = 0.15


def _random_t_history(rng: random.Random, n_looks: int, *, allow_tie: bool) -> tuple[float, ...]:
    """A monotone-non-decreasing history of information fractions, with an
    occasional tie (`dt == 0`, a degenerate look) when `allow_tie`. Starts
    at `_T_FLOOR` (see its docstring) -- the operationally meaningful
    range, not the deep-tail underflow zone below it."""
    ts: list[float] = []
    t = _T_FLOOR + rng.uniform(0.0, 0.05)
    for i in range(n_looks):
        if i > 0:
            if allow_tie and rng.random() < 0.2:
                ts.append(t)
                continue
            t = min(1.0, t + rng.uniform(0.01, 0.2))
        ts.append(t)
    return tuple(ts)


def _assert_pairs_close(
    got: tuple[float, float], expected: tuple[float, float], *, abs_tol: float
) -> None:
    for g, e in zip(got, expected, strict=True):
        assert math.isclose(g, e, rel_tol=0.0, abs_tol=abs_tol) or (
            math.isinf(g) and math.isinf(e) and (g > 0) == (e > 0)
        ), f"got {g!r}, expected {e!r} (abs_tol={abs_tol!r})"


@pytest.mark.parametrize("seed", range(50))
def test_streaming_boundary_at_npts_2001_equals_boundary_for_to_1e_12(seed: int) -> None:
    rng = random.Random(seed)
    artefact = _artefact()
    n_looks = rng.randint(1, 6)
    t_history = _random_t_history(rng, n_looks, allow_tie=True)
    terminal_last = rng.random() < 0.5

    streaming = StreamingBoundary(alpha=_ALPHA, npts=GRID_NPTS, halfwidth_sd=GRID_HALFWIDTH_SD)
    for i in range(n_looks):
        is_terminal = terminal_last and i == n_looks - 1
        prefix = t_history[: i + 1]
        expected = artefact.boundary_for(prefix, is_terminal=is_terminal)
        got = streaming(prefix, is_terminal=is_terminal)
        _assert_pairs_close(got, expected, abs_tol=1e-12)


@pytest.mark.parametrize("seed", range(50))
def test_reduced_npts_streaming_boundary_is_within_1e_3_of_boundary_for(seed: int) -> None:
    """Scoped to a SINGLE look (see the module docstring's "MEASURED SCOPE"
    note): a fresh `StreamingBoundary`'s first call, both non-terminal and
    terminal, over `t in [_T_FLOOR, 1.0]` (the operationally meaningful
    range -- see `_T_FLOOR`'s docstring for the deep-tail underflow floor)."""
    rng = random.Random(seed + 10_000)  # distinct stream from test 4a
    artefact = _artefact()
    t = _T_FLOOR + rng.uniform(0.0, 0.85)
    is_terminal = rng.random() < 0.5

    streaming = StreamingBoundary(alpha=_ALPHA, npts=REDUCED_NPTS, halfwidth_sd=GRID_HALFWIDTH_SD)
    expected = artefact.boundary_for((t,), is_terminal=is_terminal)  # full-grid reference
    got = streaming((t,), is_terminal=is_terminal)
    _assert_pairs_close(got, expected, abs_tol=1e-3)


def test_the_sim_terminal_look_spends_exactly_the_remaining_alpha() -> None:
    """The terminal branch's `_look_step` target is `alpha -
    spend(prev_t)`, solved from the SAME prior `(grid, dens, prev_t)` state
    the non-terminal branch would have used -- verified by an independent
    second `_look_step` call built from that exact prior state, never by
    re-deriving the formula inline."""
    alpha = _ALPHA
    npts = GRID_NPTS
    halfwidth_sd = GRID_HALFWIDTH_SD
    t1, t2 = 0.2, 0.55

    streaming = StreamingBoundary(alpha=alpha, npts=npts, halfwidth_sd=halfwidth_sd)
    streaming((t1,), is_terminal=False)

    grid_before = streaming._grid
    dens_before = streaming._dens
    prev_t_before = streaming._prev_t
    assert prev_t_before == t1

    got_b_eff, got_b_fut = streaming((t1, t2), is_terminal=True)

    expected_target = alpha - _one_sided_spend(prev_t_before, alpha)
    exp_b_eff, exp_b_fut, _grid, _dens, _prev_t = _look_step(
        t2, prev_t_before, grid_before, dens_before, expected_target, npts, halfwidth_sd
    )
    z_scale = math.sqrt(t2)
    assert math.isclose(got_b_eff, exp_b_eff / z_scale, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(got_b_fut, exp_b_fut / z_scale, rel_tol=0.0, abs_tol=1e-12)

    # Cross-check: the SAME terminal look computed by `boundary_for` over
    # the identical full history reproduces the streaming result too.
    reference = _artefact(alpha).boundary_for((t1, t2), is_terminal=True)
    assert math.isclose(got_b_eff, reference[0], rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(got_b_fut, reference[1], rel_tol=0.0, abs_tol=1e-9)


def test_streaming_boundary_raises_if_the_history_does_not_extend_by_exactly_one() -> None:
    streaming = StreamingBoundary(alpha=_ALPHA, npts=101)
    streaming((0.3,), is_terminal=False)
    with pytest.raises(ValueError, match="extend the previously committed history"):
        streaming((0.3, 0.5, 0.7), is_terminal=False)
    with pytest.raises(ValueError, match="extend the previously committed history"):
        streaming((0.3,), is_terminal=False)
