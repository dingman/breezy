"""Increment A validation slice (plan MULTI_POSITION_PER_STATION_2026-09-14,
Rev 3 disposition R3-3): S5 is replaced by this slice --

(ii) a seeded, deterministic Monte-Carlo under H0 asserting the combined
     statistic's unit variance and the LD-OBF boundary's realised one-sided
     crossing rate;
(iii) static guards: the boundary artefact's `inputs_sha256` self-check, and
     the analytic proof that the multi-rung combine never raises the
     per-station-day information ceiling above the artefact's `i_max` pin.

The Monte-Carlo interpolates `b_eff`/`b_fut` from the artefact's own 16-row
`reference_table` at the realised information fraction, exactly the
"practical stand-in for a fresh `boundary_for` call, not tractable at this
replicate count" pattern `crh_group_sequential_boundaries.simulate_drift`
already uses -- a genuine per-replicate `boundary_for` re-solve (a fresh
O(2001^2) joint-density recursion per look) is not tractable at 2000+
replications x 16 looks within this repo's compute budget (`docs/plans
/MULTI_POSITION_PER_STATION_2026-09-14.md` "Heavy compute" constraint), and
this module's own artefact JSON records the identical simulate_drift
methodology as its own `simulation_drift` fixture.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    StratumRow,
    combine_station_day,
    score_combined,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import aud06a_qty_envelope_sweep as sweep
import crh_group_sequential_boundaries as gs

_ARTEFACT_PATH = _REPO_ROOT / "deploy" / "families" / "gs_boundary_pm_us_crh_v2.json"


def _artefact_payload() -> dict:
    return json.loads(_ARTEFACT_PATH.read_text(encoding="utf-8"))


def _interp(t: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation with flat extrapolation past the table's ends --
    `np.interp`'s own default behaviour, restated dependency-free."""
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


def _sample_station_day(rng: random.Random) -> tuple[StratumRow, ...]:
    """One H0 station-day draw: k in {1,2,3} mutually exclusive rungs,
    `Sum BE_i = S ~ Uniform(0,1)` split among the k rungs (a random
    k-dimensional simplex point, admissible by construction), mixed
    qty in {1,2,3}, and `held` drawn from the true mutually-exclusive
    categorical (rung i holds w.p. BE_i, none holds w.p. `1-S`) -- exactly
    the H0 this module's `Var_H0` derivation assumes."""
    k = rng.randint(1, 3)
    total_be = rng.random()
    weights = [-math.log(rng.random()) for _ in range(k)]
    weight_sum = sum(weights)
    bes = [total_be * w / weight_sum for w in weights]
    qtys = [rng.randint(1, 3) for _ in range(k)]
    u = rng.random()
    cumulative = 0.0
    holder: int | None = None
    for i, be in enumerate(bes):
        cumulative += be
        if u < cumulative:
            holder = i
            break
    return tuple(
        StratumRow(
            entry_ask=Decimal(str(round(be, 9))),
            fee=Decimal(0),
            held=(i == holder),
            station="MIA",
            qty=Decimal(qtys[i]),
        )
        for i, be in enumerate(bes)
    )


def _run_h0_monte_carlo(*, seed: int, n_reps: int) -> tuple[list[float], int]:
    """Returns (terminal S per replication, count of replications whose
    FIRST boundary crossing -- across the `look_step`-spaced schedule up to
    `n_max` -- is the efficacy boundary). A replication that crosses
    futility first is marked "stopped" and not re-checked (real sequential-
    test semantics), so a replication is counted as a crossing only if
    efficacy is the FIRST boundary it reaches."""
    payload = _artefact_payload()
    i_max = payload["i_max"]
    n_max = payload["n_max"]
    look_step = payload["look_step"]
    table = payload["reference_table"]
    table_t = [row["t_k"] for row in table]
    table_b_eff = [row["b_eff"] for row in table]
    table_b_fut = [row["b_fut"] for row in table]
    look_ns = set(range(look_step, n_max + 1, look_step))

    rng = random.Random(seed)
    terminal_s: list[float] = []
    efficacy_crossings = 0
    for _rep in range(n_reps):
        draws = []
        stopped = False
        crossed_efficacy = False
        for draw_idx in range(1, n_max + 1):
            draws.append(combine_station_day(_sample_station_day(rng)))
            if draw_idx in look_ns and not stopped:
                state = score_combined(tuple(draws))
                t = min(1.0, state.information / i_max)
                b_eff = _interp(t, table_t, table_b_eff)
                b_fut = _interp(t, table_t, table_b_fut)
                if state.s >= b_eff:
                    crossed_efficacy = True
                    stopped = True
                elif state.s <= b_fut:
                    stopped = True
        terminal_s.append(score_combined(tuple(draws)).s)
        if crossed_efficacy:
            efficacy_crossings += 1
    return terminal_s, efficacy_crossings


def test_under_h0_the_combined_statistic_has_unit_variance() -> None:
    """`Var_H0(S) = 1` exactly by construction (station-days independent,
    `I = Sum_sd Var_H0(X_sd)` is the true population variance). Seed
    20260914, 2000 replications, k in {1,2,3}, qty in {1,2,3} -- sample
    Var(S_terminal) observed at ~1.00 (measured), asserted within
    [0.85, 1.15] of 1 (Monte-Carlo slack)."""
    terminal_s, _ = _run_h0_monte_carlo(seed=20260914, n_reps=2000)

    mean_s = sum(terminal_s) / len(terminal_s)
    sample_variance = sum((s - mean_s) ** 2 for s in terminal_s) / (len(terminal_s) - 1)

    assert 0.85 <= sample_variance <= 1.15, (
        f"observed sample Var(S_terminal)={sample_variance!r} outside [0.85, 1.15]"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "measured: observed one-sided efficacy-crossing rate ~0.059 at seed "
        "20260914 / 5000 reps (0.0592) and seed 20260914 / 2000 reps (0.058), "
        "both > alpha(0.025) + 0.01 slack = 0.035, under k in {1,2,3} MIXED "
        "qty in {1,2,3}. A qty=1-only control (same methodology, same seed "
        "family) measures ~0.011-0.013 -- within tolerance -- so the "
        "inflation is a genuine mixed-qty effect (higher qty pushes a "
        "station-day's variance up to 9x a single Bernoulli term, so I "
        "saturates far faster than the artefact's n_k/n_max=0.25-per-draw "
        "schedule assumes, and the realised-t boundary interpolation "
        "undershoots at that faster accrual), not a simulation artefact. "
        "Increment A ships at qty=1 only (R3-2), where this statistic is "
        "correctly calibrated; Increment B (qty>1) needs the boundary "
        "re-validated (plan Rev3 S3 'Increment B: re-run (ii) with qty>1') "
        "before it can rely on this artefact. Per R3-3 disposition, this "
        "does NOT block Increment A and the artefact is NOT re-solved here. "
        "AUD-06a (2026-09-25, docs/evidence/RULING_r11_qty_envelope_2026-09-25.md): "
        "re-validation at a dimensionless qty-envelope sweep (Amendment C, "
        "MULTI_POSITION_PER_STATION_2026-09-14.md) reproduced both figures, "
        "found the recorded mechanism's monotonicity STRONGLY supported "
        "(Spearman rho=0.83, p=0.0001 across 29 cells) but returned an "
        "INDETERMINATE mechanism verdict because the qty=1 control anchor "
        "itself departs from the artefact's assumed schedule under a "
        "realistic (non-uniform, cheap) BE prior -- a confound unrelated to "
        "qty. No envelope was published; this xfail is unchanged and stays "
        "strict pending a completed grid or a reconsidered control-anchor "
        "tolerance."
    ),
)
def test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha() -> None:
    """Realised one-sided efficacy-boundary crossing rate under H0, k in
    {1,2,3} MIXED qty in {1,2,3}, seed 20260914, 2000 replications, against
    the artefact's own `alpha=0.025` + 0.01 Monte-Carlo slack. Boundaries
    are the artefact's own solved values, read via `reference_table`
    interpolation at the realised information fraction -- never a fresh
    per-replicate `boundary_for` re-solve (not tractable at this replicate
    count) and never a re-derived boundary (R3-3: "a re-solve is required
    only if (ii) fails", which it does -- see the xfail reason)."""
    payload = _artefact_payload()
    alpha = payload["alpha"]
    _terminal_s, efficacy_crossings = _run_h0_monte_carlo(seed=20260914, n_reps=2000)
    n_reps = 2000

    observed_rate = efficacy_crossings / n_reps
    assert observed_rate <= alpha + 0.01, (
        f"observed one-sided efficacy-crossing rate {observed_rate!r} exceeds "
        f"alpha+slack {alpha + 0.01!r}"
    )


def test_the_boundary_inputs_sha256_is_unchanged() -> None:
    """Recompute `inputs_sha256` from the artefact's own recorded inputs the
    same way `crh_group_sequential_boundaries.py` (the generator) and
    `gs_boundary_artefact.py` (the loader) both do, and compare to the
    PREREG v3 SS16-pinned value (`docs/specs/PREREG_v3...` SS16,
    `471fd8a7...150e0c`). R3-3's combined-draw statistic changes neither
    alpha, the spending function, n_max, i_max, nor look_step -- this
    artefact is RE-VALIDATED, never re-solved (plan SS2)."""
    payload = _artefact_payload()
    recomputed_manifest = gs.inputs_manifest(
        payload["alpha"],
        payload["spending_id"],
        payload["n_max"],
        payload["i_max"],
        payload["look_step"],
    )
    recomputed_sha = gs.sha256_of_inputs(recomputed_manifest)

    pinned = "471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c"
    assert recomputed_sha == payload["inputs_sha256"] == pinned


def test_observed_information_cannot_exceed_i_max_within_n_max() -> None:
    """Static guard (R3-3): at qty=1, `Var_H0(X_sd) = S*(1-S)` where
    `S = Sum BE_i` -- the covariance-subtracted cross terms collapse
    `Sum BE_i**2 + 2*Sum_{i<j} BE_i*BE_j` into `S**2` exactly, so a
    multi-rung (k<=4) station-day's variance ceiling is IDENTICAL to the
    single-Bernoulli ceiling `BE*(1-BE) <= 1/4` (max at S=0.5) the
    artefact's `i_max = n_max/4` pin already assumes. A grid search over
    admissible BE tuples (Sum BE_i <= 1, k<=4, step 0.1) confirms no
    combination exceeds 0.25; the tally therefore needs no new refusal for
    an over-ceiling multi-rung station-day -- it structurally cannot occur
    at qty=1."""
    payload = _artefact_payload()
    i_max = payload["i_max"]
    n_max = payload["n_max"]

    be_values = [i / 10 for i in range(11)]
    max_variance = 0.0
    for k in range(1, 5):
        for combo in itertools.product(be_values, repeat=k):
            if sum(combo) > 1.0 + 1e-9:
                continue
            rows = tuple(
                StratumRow(entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA")
                for be in combo
            )
            draw = combine_station_day(rows)
            max_variance = max(max_variance, draw.variance)

    assert max_variance <= 0.25 + 1e-9
    assert i_max == pytest.approx(0.25 * n_max)


# ---------------------------------------------------------------------------
# AUD-06a — R-11 qty envelope sweep (Amendment C to
# MULTI_POSITION_PER_STATION_2026-09-14.md, replacing validation-slice item
# (ii)). See scripts/analysis/aud06a_qty_envelope_sweep.py.
# ---------------------------------------------------------------------------


def test_the_crossing_rate_is_reported_per_qty_envelope() -> None:
    """`run_cell` reports a `CellResult` carrying `q_max` and its realised
    one-sided crossing rate, so the sweep table is a function of the qty
    envelope rather than one point estimate."""
    cell_small = sweep.CellSpec(
        q_max=1, dispersion=sweep.DispersionSpec("all_equal"), k=1, side_mix="all_yes"
    )
    cell_large = sweep.CellSpec(
        q_max=3, dispersion=sweep.DispersionSpec("all_equal"), k=2, side_mix="mixed"
    )
    result_small = sweep.run_cell(cell_small, cell_index=0, seed=1, n_reps=500)
    result_large = sweep.run_cell(cell_large, cell_index=1, seed=2, n_reps=500)
    assert result_small.q_max == 1
    assert result_large.q_max == 3
    assert 0.0 <= result_small.crossing_rate <= 1.0
    assert 0.0 <= result_large.crossing_rate <= 1.0


def test_the_simulated_null_reproduces_the_registered_h0_variance_exactly() -> None:
    """Closed-form check of `Var_H0(X_sd)` against §6/Amendment §3 at k=1
    qty=1, and at k=2 mixed qty including a YES/NO pair whose cross term is
    POSITIVE (the L-41 guard: a mis-specified null must be caught here)."""
    # k=1, qty=1: Var = BE(1-BE)
    be = 0.3
    row = StratumRow(entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA")
    draw = combine_station_day((row,))
    assert draw.variance == pytest.approx(be * (1 - be))

    # k=2 mixed qty, YES/NO pair: cross term is POSITIVE (s_i*s_j = -1)
    be_yes, be_no = 0.2, 0.3
    qty_yes, qty_no = 2.0, 3.0
    row_yes = StratumRow(
        entry_ask=Decimal(str(be_yes)), fee=Decimal(0), held=False, station="MIA",
        qty=Decimal(str(qty_yes)), side="yes", rung="r0",
    )
    row_no = StratumRow(
        entry_ask=Decimal(str(be_no)), fee=Decimal(0), held=False, station="MIA",
        qty=Decimal(str(qty_no)), side="no", rung="r1",
    )
    draw_mixed = combine_station_day((row_yes, row_no))
    q_yes = be_yes
    q_no = 1.0 - be_no
    expected_variance = (
        qty_yes**2 * q_yes * (1 - q_yes)
        + qty_no**2 * q_no * (1 - q_no)
        - 2.0 * qty_yes * qty_no * (1.0) * (-1.0) * q_yes * q_no
    )
    assert draw_mixed.variance == pytest.approx(expected_variance)
    # The cross term itself (before the "-2*..." sign) is POSITIVE:
    cross_term = -2.0 * qty_yes * qty_no * (1.0) * (-1.0) * q_yes * q_no
    assert cross_term > 0


def test_an_inadmissible_station_day_is_refused_at_draw_construction() -> None:
    """A station-day whose cell probabilities sum above 1 is refused by
    `combine_station_day` itself -- the sampler's rejection loop exists so
    such a draw never reaches `score_combined`."""
    rows = tuple(
        StratumRow(entry_ask=Decimal("0.6"), fee=Decimal(0), held=False, station="MIA")
        for _ in range(2)
    )
    from breezy.settlement.current_rung_hold_v2 import StationDayAdmissionRefusal

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day(rows)


def test_the_realised_information_trajectory_is_reported_per_look() -> None:
    """Each `CellResult` reports `delta_t`/`var_s` at every look
    `n_k in {10,...,160}` -- the mechanism instrument (Amendment C)."""
    cell = sweep.CellSpec(
        q_max=2, dispersion=sweep.DispersionSpec("two_point"), k=2, side_mix="all_yes"
    )
    result = sweep.run_cell(cell, cell_index=0, seed=42, n_reps=300)
    assert result.look_ns == tuple(range(10, 161, 10))
    assert len(result.delta_t) == len(result.look_ns)
    assert len(result.var_s) == len(result.look_ns)
    assert result.max_abs_delta_t == max(abs(d) for d in result.delta_t)


def test_the_envelope_records_the_be_prior_support_and_its_staleness_predicate() -> None:
    """The artefact records the `BE`-prior's sampled support (min/p25/median
    /p75/max/IQR) and ships a staleness predicate function."""
    support = sweep.observed_ask_support()
    for key in ("n", "min", "p25", "median", "p75", "max", "iqr"):
        assert key in support
    assert support["min"] <= support["p25"] <= support["median"] <= support["p75"] <= support["max"]
    assert callable(sweep.envelope_is_stale)


def test_a_be_prior_outside_the_recorded_support_marks_the_envelope_stale() -> None:
    """Both staleness conditions fire: live median outside `[p25,p75]`, and
    live IQR drifted more than the recorded thresholds."""
    support = sweep.observed_ask_support()
    # Condition 1: live median far outside [p25, p75]
    assert sweep.envelope_is_stale((0.99, 0.99, 0.99, 0.99), recorded_support=support)
    # Condition 2: live IQR blown out relative to the recorded IQR
    wide_asks = tuple(i / 100 for i in range(1, 100))
    assert sweep.envelope_is_stale(wide_asks, recorded_support=support)
    # Not stale: the observed sample itself, replayed as "live"
    assert not sweep.envelope_is_stale(sweep.OBSERVED_ASKS, recorded_support=support)


def test_the_sampler_sets_side_and_the_mixed_cell_contains_both_legs() -> None:
    """The sampler sets `side` explicitly (never defaulting every row to
    `"yes"`), and a `mixed` cell's draw contains at least one YES and one
    NO leg."""
    rng = random.Random(7)
    cell = sweep.CellSpec(
        q_max=2, dispersion=sweep.DispersionSpec("all_equal"), k=2, side_mix="mixed"
    )
    rows = sweep.sample_station_day(rng, cell)
    sides = {row.side for row in rows}
    assert sides == {"yes", "no"}


def test_a_mixed_side_pair_raises_station_day_variance_relative_to_an_all_yes_pair() -> None:
    """At equal `q`/`qty`, a YES/NO pair has HIGHER station-day variance
    than a YES/YES pair (`combine_station_day:344`'s sign argument)."""
    be = 0.3
    qty = Decimal(2)
    row_yes_a = StratumRow(
        entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA",
        qty=qty, side="yes", rung="r0",
    )
    row_yes_b = StratumRow(
        entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA",
        qty=qty, side="yes", rung="r1",
    )
    row_no_b = StratumRow(
        entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA",
        qty=qty, side="no", rung="r1",
    )
    variance_all_yes = combine_station_day((row_yes_a, row_yes_b)).variance
    variance_mixed = combine_station_day((row_yes_a, row_no_b)).variance
    assert variance_mixed > variance_all_yes


def test_the_no_side_sampler_produces_unbiased_held_under_h0() -> None:
    """A k=1 `all_no` cell's `held` rate must match `E[held_i] = BE_i` under
    H0 (`build_stratum_v2` docstring: "under H0 E[held_i] = BE_i on both YES
    and NO") -- `held` is the PER-SIDE truth (`StratumRow` docstring), not
    the same `i == holder` test for both sides (that instead gives
    `E[held_i] = q_i = 1 - BE_i`, biased). Checked via a single fixed ask
    (never bootstrapped) so the true `BE_i` is known exactly, over 20000
    draws at `q_max=1` (dispersion is inert at q_max=1)."""
    cell = sweep.CellSpec(
        q_max=1, dispersion=sweep.DispersionSpec("all_equal"), k=1, side_mix="all_no"
    )
    rng = random.Random(2026)
    fixed_ask = 0.3  # BE_i = ask = 0.3; E[held_i] = BE_i for a NO leg too
    n_draws = 20000
    original_asks = sweep.OBSERVED_ASKS
    sweep.OBSERVED_ASKS = (fixed_ask,)
    try:
        rows_sample = [sweep.sample_station_day(rng, cell) for _ in range(n_draws)]
    finally:
        sweep.OBSERVED_ASKS = original_asks
    assert all(rows[0].side == "no" for rows in rows_sample)
    held_count = sum(1 for rows in rows_sample if rows[0].held)
    empirical_rate = held_count / n_draws
    expected_rate = fixed_ask
    assert empirical_rate == pytest.approx(expected_rate, abs=0.02), (
        f"empirical held-rate {empirical_rate!r} != expected BE_i={expected_rate!r} "
        "-- the NO-side sampler is biased"
    )


def test_the_mixed_cell_never_samples_an_inadmissible_station_day() -> None:
    """1000 sampled `mixed` station-days at k=2 and k=3 never raise a
    `StationDayAdmissionRefusal` when re-fed through `combine_station_day` --
    the sampler's rejection loop keeps its own output admissible."""
    from breezy.settlement.current_rung_hold_v2 import StationDayAdmissionRefusal

    rng = random.Random(99)
    for k in (2, 3):
        cell = sweep.CellSpec(
            q_max=3, dispersion=sweep.DispersionSpec("cap_shaped", r=5), k=k, side_mix="mixed"
        )
        for _ in range(1000):
            rows = sweep.sample_station_day(rng, cell)
            try:
                combine_station_day(rows)
            except StationDayAdmissionRefusal:
                pytest.fail("sampler produced an inadmissible mixed station-day")


def test_the_cap_shaped_dispersion_reads_no_operator_reserved_value() -> None:
    """The `R` grid is a literal dimensionless sequence; the sweep module's
    source contains no cap read, no currency figure and no cap-derived
    quotient."""
    source = Path(sweep.__file__).read_text(encoding="utf-8")
    forbidden = (
        "operator_controls", "per_position", "daily_budget", "PERMIT_BUDGETS", "os.environ",
    )
    for token in forbidden:
        assert token not in source, f"sweep module reads or references {token!r}"
    assert sweep.CAP_SHAPED_R_GRID == (2, 3, 5, 8, 13, 21)


def test_the_sweep_retains_no_per_replication_state() -> None:
    """`run_cell` holds no growing container across reps -- only scalar
    accumulators and a length-`n_max/look_step` per-look history survive a
    replication (the `replay_driver_memory_grows_unbounded` failure mode)."""
    import inspect

    source = inspect.getsource(sweep.run_cell)
    rep_loop_start = source.index("for _rep in range(n_reps):")
    rep_loop_end = source.index("\n    delta_t = []")
    rep_loop_body = source[rep_loop_start:rep_loop_end]
    assert ".append(" not in rep_loop_body, (
        "run_cell's per-replication loop retains state via .append(...) -- "
        "only fixed-size scalar accumulators (sum_i/sum_s/sum_s2, length "
        "n_max/look_step) may survive a replication"
    )


def test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run(tmp_path: Path) -> None:
    """Cells `0:6` in two chunks (`0:3` then `3:6`) assemble to a table
    byte-identical to a single `0:6` run -- chunk boundaries cannot change
    the result because the seed is per-cell."""
    chunked_path = tmp_path / "chunked.jsonl"
    sweep.run_chunk(0, 3, out_path=chunked_path, n_reps=50)
    sweep.run_chunk(3, 6, out_path=chunked_path, n_reps=50)

    single_path = tmp_path / "single.jsonl"
    sweep.run_chunk(0, 6, out_path=single_path, n_reps=50)

    chunked_results = [r.to_json() for r in sweep.load_results(chunked_path)]
    single_results = [r.to_json() for r in sweep.load_results(single_path)]
    assert chunked_results == single_results


def test_a_mixed_side_cell_at_k_equals_one_is_skipped_not_sampled_as_all_yes() -> None:
    """`(k=1, mixed)` is undefined and absent from the canonical cell grid
    entirely -- never silently degraded to `all_yes`."""
    assert (1, "mixed") not in sweep.ADMISSIBLE_K_SIDE_MIX
    for cell in sweep.ALL_CELLS:
        assert not (cell.k == 1 and cell.side_mix == "mixed")
    assert len(sweep.ALL_CELLS) == 320


def test_the_mechanism_verdict_is_computed_not_eyeballed() -> None:
    """The driver emits `CONFIRMED`/`REFUTED`/`INDETERMINATE` with `rho`,
    its permutation p-value and the contributing cell count; the same table
    always yields the same verdict."""
    too_few = [
        sweep.CellResult(
            cell_index=i, label=f"c{i}", q_max=1, dispersion="all_equal", r=None, k=1,
            side_mix="all_yes", seed=i, n_reps=100, crossing_count=2, crossing_rate=0.02,
            cp_upper=0.05, cp_lower=0.001, look_ns=(10, 20), delta_t=(0.0, 0.0), var_s=(1.0, 1.0),
            max_abs_delta_t=0.0,
        )
        for i in range(5)
    ]
    verdict_few = sweep.compute_mechanism_verdict(too_few)
    assert verdict_few.verdict == "INDETERMINATE"
    assert verdict_few.n_cells == 5

    synthetic = []
    for i in range(30):
        max_dt = i * 0.01
        rate = min(0.5, 0.01 + max_dt * 2.0)
        side_mix = "all_yes"
        synthetic.append(
            sweep.CellResult(
                cell_index=i, label=f"c{i}", q_max=(i % 5) + 1, dispersion="all_equal", r=None,
                k=1 if i == 0 else 2, side_mix=side_mix, seed=i, n_reps=20000,
                crossing_count=int(rate * 20000), crossing_rate=rate,
                cp_upper=min(1.0, rate + 0.005), cp_lower=max(0.0, rate - 0.005),
                look_ns=(10, 20), delta_t=(max_dt, max_dt), var_s=(1.0, 1.0),
                max_abs_delta_t=max_dt,
            )
        )
    verdict_1 = sweep.compute_mechanism_verdict(synthetic)
    verdict_2 = sweep.compute_mechanism_verdict(synthetic)
    assert verdict_1.verdict == verdict_2.verdict
    assert verdict_1.rho == verdict_2.rho
    assert verdict_1.p_value == verdict_2.p_value
    assert verdict_1.verdict in ("CONFIRMED", "REFUTED", "INDETERMINATE")
