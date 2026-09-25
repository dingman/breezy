"""AUD-07 amendment Stage M1c, tests 2/5/6/8 and the harness positive
control (test 7) (plan §4 M1c / §5).

`scripts/analysis/aud07_live_rule_crossing_sim.py` replays the LIVE PREREG
v2 sequential rule (`run_sequential_looks`, AUD-07 Stage M1b) verbatim,
including its terminal stop at `I >= I_max` -- the divergence L-40's
2026-09-25 amendment names as the reason neither prior harness (AUD-06a's
sweep, the strict-xfail Monte-Carlo) is evidence about the live rule.
"""

from __future__ import annotations

import math
import random
import sys
from decimal import Decimal
from pathlib import Path

from breezy.settlement.current_rung_hold_v2 import StratumRow, TruncationReason, combine_station_day

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import CellSpec, sample_station_day
from aud07_live_rule_crossing_sim import (
    ALL_YES_K1_CONTROL,
    LOOK_STEP,
    M1C_GRID,
    N_MAX,
    StreamingBoundary,
    _synthetic_artefact,
    run_cell,
    run_sequential_looks,
)

_ALPHA = 0.025

#: One representative mixed cell from the M1c grid, used by the tests that
#: need a concrete (dispersion, k) combination rather than the whole grid.
_ONE_MIXED_CELL: CellSpec = next(c for c in M1C_GRID if c.side_mix == "mixed" and c.k == 2)


def test_the_m1c_grid_has_49_cells_16_mixed_32_matched_and_one_control() -> None:
    assert len(M1C_GRID) == 49
    mixed = [c for c in M1C_GRID if c.side_mix == "mixed"]
    all_yes = [c for c in M1C_GRID if c.side_mix == "all_yes"]
    all_no = [c for c in M1C_GRID if c.side_mix == "all_no"]
    assert len(mixed) == 16
    assert all(c.q_max == 1 for c in mixed)
    assert all(c.k in (2, 3) for c in mixed)
    # 16 matched all_yes (one per mixed cell's (dispersion, k) stratum) plus
    # the one k=1 control.
    assert len(all_yes) == 17
    assert len(all_no) == 16
    assert ALL_YES_K1_CONTROL in M1C_GRID
    assert ALL_YES_K1_CONTROL.k == 1


def test_the_sim_stops_at_the_first_look_where_information_reaches_i_max() -> None:
    """Replaying via `run_sequential_looks` stops at the FIRST scheduled
    look where `I >= I_max`, terminal, reason `I_MAX` -- unlike the AUD-06a
    sweep's own hand-rolled loop (`aud06a_qty_envelope_sweep.run_cell`),
    which keeps drawing and re-testing at `b_eff(1)` for all 16 scheduled
    looks regardless (the exact divergence L-40's amendment (ii) names)."""
    cell = ALL_YES_K1_CONTROL
    rng_probe = random.Random(2026_09_25)
    draws = [combine_station_day(sample_station_day(rng_probe, cell)) for _ in range(N_MAX)]

    # i_max tiny enough that even one draw's information exceeds it.
    artefact = _synthetic_artefact(alpha=_ALPHA, i_max=1e-6, n_max=N_MAX, look_step=LOOK_STEP)
    streaming = StreamingBoundary(alpha=_ALPHA, npts=101)

    looks, verdict, decided = run_sequential_looks(
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

    assert decided is True
    assert len(looks) == 1, "a naive never-stopping loop would produce 16 looks here"
    assert looks[0].terminal is True
    assert looks[0].reason is TruncationReason.I_MAX
    assert looks[0].look_n == LOOK_STEP
    assert verdict in ("SURVIVE", "KILL")


def test_a_mixed_side_qty1_station_day_can_carry_variance_above_one_quarter() -> None:
    """L-40 amendment (i): the qty=1 ceiling `S(1-S) <= 1/4` is same-side
    only. A mixed YES+NO day at equal asks (`q_y = q_n = 0.5`) reaches the
    mixed-day maximum `Var_H0 = 1.0` -- four times the same-side ceiling."""
    yes_row = StratumRow(
        entry_ask=Decimal("0.50"), fee=Decimal(0), held=True, station="MIA", side="yes", rung="R1"
    )
    no_row = StratumRow(
        entry_ask=Decimal("0.50"), fee=Decimal(0), held=False, station="MIA", side="no", rung="R2"
    )

    draw = combine_station_day((yes_row, no_row))

    assert math.isclose(draw.variance, 1.0, rel_tol=0.0, abs_tol=1e-12)


def test_the_sim_null_has_mean_s_near_zero_and_unit_var_s_on_mixed_days() -> None:
    """L-41: the sampler quotes exactly at the true cell probability (no
    separate noise term), so the neutral-input harness reproduces the
    registered H0 exactly -- `mean(S_terminal) ~= 0`, `Var(S_terminal) ~=
    1` on a mixed-side cell. Reduced reps/`npts` for test-suite speed; the
    registered [0.95, 1.05] band applies at the full 20000-rep run."""
    result = run_cell(
        _ONE_MIXED_CELL,
        cell_index=0,
        seed=20260925_900001,
        n_reps=4000,
        npts=101,
    )

    assert not result.skipped
    se_mean = 1.0 / math.sqrt(result.n_reps)  # Var(S) ~= 1
    assert abs(result.mean_s_terminal) < 6.0 * se_mean
    assert 0.8 <= result.var_s_terminal <= 1.2
    assert result.loss_stop_count == 0


def test_the_all_yes_qty1_control_passes_the_m2_gate_under_the_live_rule() -> None:
    """Harness positive control (test 7): the all_yes k=1 q_max=1 cell is
    the SAME-side case L-40's pre-amendment text already validated
    (`docs/core/LESSONS.md:1391`) -- it must be calibrated (CP-upper well
    under the registered efficacy level) under the live-rule replay too.
    This cell runs the FULL 16-look schedule every replicate (its
    information never reaches `i_max` early), so `npts=101` (not
    `REDUCED_NPTS=601`, proven only for single-look histories -- see
    `test_aud07_streaming_boundary.py`) keeps this unit test fast; the
    registered 20000-rep, full-grid measurement is a separate harness run
    (M1c "Grid"/"Reps"), not this unit test."""
    result = run_cell(
        ALL_YES_K1_CONTROL,
        cell_index=48,
        seed=20260925_900002,
        n_reps=3000,
        npts=101,
    )

    assert not result.skipped
    # Generous test-suite bound (3000 reps at npts=101, not the registered
    # 20000 at the full grid): the M2 V-gate threshold is alpha + delta =
    # 0.0283 at the registered rep count; here we only need the mechanism
    # to be clearly under control.
    assert result.cp_upper < 0.06


def test_the_sim_counts_only_efficacy_crossings_and_loss_stop_never_fires() -> None:
    """Neutral inputs (`total_pnl = residual = Decimal(0)`) make `verdict`
    permanently unable to report `SURVIVE` (both `look_verdict` and
    `terminal_look` gate `SURVIVE` on `total_pnl > 0`) -- so the crossing
    predicate MUST be `state.s >= b_eff` read directly off each
    `LookRecord`, never `verdict == "SURVIVE"`. This test constructs a
    station-day sequence engineered to cross `b_eff` at an INTERIM look and
    confirms the tally's own verdict never says SURVIVE there, while the
    raw-field predicate still fires."""
    # A large, favourable all-YES run: high `held` rate at a low ask drives
    # `S` well above any early `b_eff`.
    rows = tuple(
        StratumRow(entry_ask=Decimal("0.05"), fee=Decimal(0), held=True, station="MIA")
        for _ in range(LOOK_STEP)
    )
    draws = [combine_station_day((row,)) for row in rows] + [
        combine_station_day(
            (StratumRow(entry_ask=Decimal("0.05"), fee=Decimal(0), held=True, station="MIA"),)
        )
        for _ in range(N_MAX - LOOK_STEP)
    ]

    artefact = _synthetic_artefact(alpha=_ALPHA, i_max=40.0, n_max=N_MAX, look_step=LOOK_STEP)
    streaming = StreamingBoundary(alpha=_ALPHA, npts=101)

    looks, verdict, decided = run_sequential_looks(
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

    assert decided is True
    assert verdict != "SURVIVE"  # neutral total_pnl=0 makes SURVIVE unreachable
    assert not any(look.reason is TruncationReason.LOSS_STOP for look in looks)
    crossed = any(look.state.s >= look.b_eff for look in looks)
    assert crossed, "the engineered favourable run must cross b_eff at some look"
