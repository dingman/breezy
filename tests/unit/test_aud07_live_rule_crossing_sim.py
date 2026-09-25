"""AUD-07 amendment Stage M1c, tests 2/5/6/8 and the harness positive
control (test 7) (plan §4 M1c / §5).

`scripts/analysis/aud07_live_rule_crossing_sim.py` replays the LIVE PREREG
v2 sequential rule (`run_sequential_looks`, AUD-07 Stage M1b) verbatim,
including its terminal stop at `I >= I_max` -- the divergence L-40's
2026-09-25 amendment names as the reason neither prior harness (AUD-06a's
sweep, the strict-xfail Monte-Carlo) is evidence about the live rule.
"""

from __future__ import annotations

import json
import math
import random
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from breezy.persistence.gs_boundary_artefact import I_MAX
from breezy.settlement.current_rung_hold_v2 import StratumRow, TruncationReason, combine_station_day

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import aud07_live_rule_crossing_sim as sim_mod
from aud06a_qty_envelope_sweep import CellSpec, sample_station_day
from aud07_live_rule_crossing_sim import (
    ALL_YES_K1_CONTROL,
    LOOK_STEP,
    M1C_GRID,
    N_MAX,
    SEED_BASE,
    SEED_CAL_BASE,
    SEED_RERUN_BASE,
    EpsPin,
    EpsPinValidationError,
    StreamingBoundary,
    _decisions,
    _max_abs_delta_b,
    _needs_refine,
    _run_replicate,
    _synthetic_artefact,
    load_eps_pin,
    run_cell,
    run_sequential_looks,
    seed_for,
)

_ALPHA = 0.025


def _look(*, t: float, s: float, b_eff: float, b_fut: float) -> SimpleNamespace:
    """A minimal stand-in for a `LookRecord`: `_needs_refine`/`_decisions`/
    `_max_abs_delta_b` only read `.t`, `.state.s`, `.b_eff`, `.b_fut`."""
    return SimpleNamespace(t=t, b_eff=b_eff, b_fut=b_fut, state=SimpleNamespace(s=s))


#: Gate-fast eps pin (§8 preamble: "gate-fast tests use a cheap grid pair:
#: coarse=151, fine=401"), `dt_min` pinned tiny so the dt guard never
#: confounds the eff/fut/nonfinite-focused tests.
_FAST_PIN = EpsPin(
    eps=0.03,
    dt_min=1e-6,
    census_sha256="0" * 64,
    census_max=0.0,
    code_sha="test-sha",
    sha256="0" * 64,
)

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


# ---------------------------------------------------------------------------
# Rev 2 M1c/M2 execution amendment, tests 17-21, 27, 28 (§8)
# ---------------------------------------------------------------------------

_METADATA_KEYS = {
    "boundary_mode",
    "coarse_npts",
    "eps",
    "dt_min",
    "eps_pin_sha256",
    "audit_every",
    "refined_count",
    "refine_reasons",
    "audit_reps",
    "audit_max_abs_delta_b",
    "audit_disagreements",
    "numpy_version",
    "scipy_version",
    "stage",
    "code_sha",
    "substream",
}


def test_refined_run_equals_the_fine_grid_run_field_for_field_and_exercises_both_paths() -> None:
    """Test 17. One mixed and one 16-look cell, ~200 reps: the refined
    result must equal a pure fine-grid run field for field (excluding
    metadata) AND `0 < refined_count < n_reps` -- exercising both the
    refine and the no-refine path (`_FAST_PIN.eps=0.03` is calibrated, by
    direct measurement, to split at the gate-fast coarse=151/fine=401
    pair)."""
    control_index = M1C_GRID.index(ALL_YES_K1_CONTROL)
    mixed_index = M1C_GRID.index(_ONE_MIXED_CELL)
    cells_and_indices = ((_ONE_MIXED_CELL, mixed_index), (ALL_YES_K1_CONTROL, control_index))
    for cell, cell_index in cells_and_indices:
        seed = 20260925_910000 + cell_index
        n_reps = 200

        refined = run_cell(
            cell,
            cell_index=cell_index,
            seed=seed,
            n_reps=n_reps,
            npts=401,
            boundary_mode="refined",
            eps_pin=_FAST_PIN,
            coarse_npts=151,
        )
        pure_fine = run_cell(
            cell, cell_index=cell_index, seed=seed, n_reps=n_reps, npts=401, boundary_mode="pure"
        )

        assert not refined.skipped and not pure_fine.skipped
        refined_json = refined.to_json()
        pure_json = pure_fine.to_json()
        for key in pure_json:
            if key in _METADATA_KEYS:
                continue
            assert refined_json[key] == pure_json[key], (
                f"{cell.label}: field {key!r} differs: "
                f"refined={refined_json[key]!r} pure={pure_json[key]!r}"
            )
        assert 0 < refined.refined_count < n_reps, (
            f"{cell.label}: expected a mix of refine/no-refine reps, got "
            f"refined_count={refined.refined_count} of {n_reps}"
        )


def test_refinement_has_teeth() -> None:
    """Test 18. A stub coarse boundary carries a systematic offset `d`
    relative to the fine grid. `EPS > d` -> the coarse and fine decisions
    agree (the audit sees no violation). `EPS < d` (with the eff/fut check
    itself failing to flag a refine -- the exact "premise silently holds
    when it should not" scenario the in-run audit exists to catch) -> the
    audit machinery (`_decisions`/`_max_abs_delta_b`, verbatim what
    `_run_replicate` uses) DOES detect a disagreement."""
    eps_wide = 0.05
    fine_look = _look(t=1.0, s=1.5, b_eff=1.0, b_fut=-100.0)

    # EPS(0.05) > d(0.01): the coarse decision still agrees with fine.
    d_small = 0.01
    coarse_look_small = _look(t=1.0, s=1.5, b_eff=1.0 + d_small, b_fut=-100.0)
    assert _needs_refine((coarse_look_small,), eps=eps_wide, dt_min=1e-6) is None
    assert _decisions((coarse_look_small,)) == _decisions((fine_look,))
    assert _max_abs_delta_b((coarse_look_small,), (fine_look,)) < eps_wide

    # EPS(0.05) < d(0.6): the coarse decision FLIPS (0.9 <-> 1.5 relative
    # to 1.6), yet the coarse-only eff/fut check still reports "no refine
    # needed" here (its margin-of-a-single-look heuristic is fooled) --
    # demonstrating exactly why the audit, not the heuristic alone, is the
    # backstop.
    d_large = 0.6
    coarse_look_large = _look(t=1.0, s=1.5, b_eff=1.0 + d_large, b_fut=-100.0)
    assert _needs_refine((coarse_look_large,), eps=eps_wide, dt_min=1e-6) is None
    disagreement = _decisions((coarse_look_large,)) != _decisions((fine_look,))
    max_delta = _max_abs_delta_b((coarse_look_large,), (fine_look,))
    assert disagreement or max_delta >= eps_wide, (
        "the audit must catch the violation the coarse-only heuristic missed"
    )


def test_refine_rules_eff_until_confident_crossing_fut_every_look() -> None:
    """Test 19, on hand-built `LookRecord`-shaped objects."""
    eps, dt_min = 0.02, 1e-3

    # eff: look 1 is ambiguous (margin -0.01, inside +-eps), but look 2
    # confidently crosses (margin +0.05 >= eps) -- the "any" rule means eff
    # nearness stops mattering once a confident crossing exists.
    eff_looks = (
        _look(t=0.3, s=0.90, b_eff=0.91, b_fut=-100.0),
        _look(t=1.0, s=1.05, b_eff=1.00, b_fut=-100.0),
    )
    assert _needs_refine(eff_looks, eps=eps, dt_min=dt_min) is None

    # fut: eff is trivially confident-non-crossing at every look (b_eff is
    # huge), but look 1's fut margin is ambiguous (0.005 < eps) -- unlike
    # eff, fut nearness is checked at EVERY reached look.
    fut_looks = (
        _look(t=0.3, s=-0.900, b_eff=100.0, b_fut=-0.895),
        _look(t=1.0, s=-0.950, b_eff=100.0, b_fut=-50.0),
    )
    assert _needs_refine(fut_looks, eps=eps, dt_min=dt_min) == "fut"


def test_small_dt_nonfinite_and_solver_error_force_the_fine_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 20: each of the three coarse-grid guards forces a refine
    independently of the eff/fut proximity check."""
    eps, dt_min = 0.02, 1e-3

    # (a) dt < DT_MIN, everything else safely confident.
    small_dt_looks = (_look(t=0.0005, s=10.0, b_eff=1.0, b_fut=-100.0),)
    assert _needs_refine(small_dt_looks, eps=eps, dt_min=dt_min) == "dt"

    # (b) a non-finite b that is NOT the exact (+inf, -inf) tie pair.
    nonfinite_looks = (_look(t=1.0, s=1.0, b_eff=math.inf, b_fut=5.0),)
    assert _needs_refine(nonfinite_looks, eps=eps, dt_min=dt_min) == "nonfinite"

    # The exact tie pair passes every guard cleanly.
    tie_looks = (_look(t=1.0, s=0.0, b_eff=math.inf, b_fut=-math.inf),)
    assert _needs_refine(tie_looks, eps=eps, dt_min=dt_min) is None

    # (c) a solver error at the coarse grid forces the fine grid, handled
    # by `_run_replicate` itself (never by `_needs_refine`).
    cell = _ONE_MIXED_CELL
    artefact = _synthetic_artefact(alpha=_ALPHA, i_max=I_MAX, n_max=N_MAX, look_step=LOOK_STEP)
    rng = random.Random(20260925_930001)
    draws = [combine_station_day(sample_station_day(rng, cell)) for _ in range(N_MAX)]

    real_run_sequential_looks = sim_mod.run_sequential_looks

    def _stub(draws_arg, *, artefact, boundary_fn, **kwargs):
        if getattr(boundary_fn, "npts", None) == 151:
            raise ValueError("synthetic solver failure at the coarse grid")
        return real_run_sequential_looks(
            draws_arg, artefact=artefact, boundary_fn=boundary_fn, **kwargs
        )

    monkeypatch.setattr(sim_mod, "run_sequential_looks", _stub)

    looks, reason, stats = sim_mod._run_replicate(
        draws,
        artefact=artefact,
        pin=_FAST_PIN,
        coarse_npts=151,
        fine_npts=401,
        alpha=_ALPHA,
        audit=False,
        rep_index=0,
        cell_index=0,
    )
    assert reason == "solver"
    assert stats["refined"] is True
    assert len(looks) > 0


def test_refined_mode_consumes_the_rng_identically_to_pure_mode() -> None:
    """Test 21: `_run_replicate` reads no randomness of its own -- the
    post-cell `rng.getstate()` must be identical whether or not refinement
    ran, given the SAME draws consumed per replicate."""
    cell = _ONE_MIXED_CELL
    seed = 20260925_940001
    n_reps = 5

    rng_pure = random.Random(seed)
    for _ in range(n_reps):
        [combine_station_day(sample_station_day(rng_pure, cell)) for _ in range(N_MAX)]
    state_pure = rng_pure.getstate()

    rng_refined = random.Random(seed)
    artefact = _synthetic_artefact(alpha=_ALPHA, i_max=I_MAX, n_max=N_MAX, look_step=LOOK_STEP)
    for rep_index in range(n_reps):
        draws = [combine_station_day(sample_station_day(rng_refined, cell)) for _ in range(N_MAX)]
        _run_replicate(
            draws,
            artefact=artefact,
            pin=_FAST_PIN,
            coarse_npts=151,
            fine_npts=401,
            alpha=_ALPHA,
            audit=False,
            rep_index=rep_index,
            cell_index=0,
        )
    state_refined = rng_refined.getstate()

    assert state_pure == state_refined


def test_seed_bases_are_pairwise_disjoint_across_20k_80k_substreams_and_cal() -> None:
    """Test 27 (amendment §3.1)."""
    seeds_20k = {seed_for("20k", i) for i in range(49)}
    seeds_80k = {seed_for("80k", i, j) for i in range(49) for j in range(4)}
    seeds_cal = {seed_for("cal_a", i) for i in range(49)} | {
        seed_for("cal_b", i) for i in range(49)
    }

    assert seeds_20k.isdisjoint(seeds_80k)
    assert seeds_20k.isdisjoint(seeds_cal)
    assert seeds_80k.isdisjoint(seeds_cal)
    assert min(seeds_20k) == SEED_BASE
    assert min(seeds_80k) == SEED_RERUN_BASE
    assert min(seeds_cal) == SEED_CAL_BASE

    with pytest.raises(ValueError):
        seed_for("bogus-stage", 0)


def test_eps_pin_validation_rejects_eps_below_floor_or_below_3x_census_max_or_foreign_sha(
    tmp_path: Path,
) -> None:
    """Test 28."""
    code_sha = "abc123"

    def _write_pin(**overrides: object) -> Path:
        payload = {
            "eps": 0.03,
            "dt_min": 1e-3,
            "census_max": 0.005,
            "census_sha256": "d" * 64,
            "code_sha": code_sha,
        }
        payload.update(overrides)
        path = tmp_path / f"eps_pin_{len(overrides)}_{overrides!r}.json".replace("/", "_")
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    ok_path = _write_pin()
    pin = load_eps_pin(ok_path, code_sha=code_sha)
    assert pin.eps == 0.03
    assert pin.sha256

    below_floor = _write_pin(eps=0.01, census_max=0.001)
    with pytest.raises(EpsPinValidationError, match="floor"):
        load_eps_pin(below_floor, code_sha=code_sha)

    below_3x_census = _write_pin(eps=0.02, census_max=0.01)  # 3x0.01=0.03 > 0.02
    with pytest.raises(EpsPinValidationError, match="3x"):
        load_eps_pin(below_3x_census, code_sha=code_sha)

    foreign_sha = _write_pin(code_sha="someone-elses-sha")
    with pytest.raises(EpsPinValidationError, match="code_sha"):
        load_eps_pin(foreign_sha, code_sha=code_sha)
