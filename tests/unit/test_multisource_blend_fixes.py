"""RED-first tests for the F13 Phase A review-fix batch (library side).

Items: S1 (M0 pool + embargo + pooled sensitivity + fold exclusion), S2 (negative-control gate),
S3 (complete-case and ladder-level diagnostics), S4 (leak audit on Delta(M0-M3), two-sided M0'
difference), P2 (convergence check, smooth sigma floor), P3 (feature-boundary validation).
Synthetic fixtures only.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

import numpy as np
import pytest
from scipy.optimize import OptimizeResult, minimize

from breezy.analysis import multisource_blend as msb
from breezy.analysis.nbp_calibration import fit_calibration as real_fit_calibration
from breezy.strategy.ladder_ev.quantile_density import Percentiles
from tests.unit.test_multisource_blend import (
    _BOOT,
    _passing_inputs,
    _pct,
    _row,
    _settings,
    _summary,
    make_rows,
)

_START = dt.date(2025, 1, 1)  # a validate-split date
_FOLDS = "breezy.analysis.multisource_blend_folds"
_FIT = "breezy.analysis.multisource_blend_fit"


def _two_versions(days: int = 112) -> list[msb.FeatureRow]:
    first = make_rows(
        days=days, start=_START, version="v4.2", stations=("NYC",), horizons=("D-1",), seed=11
    )
    second = make_rows(
        days=days,
        start=_START + dt.timedelta(days=days),
        version="v4.3",
        stations=("NYC",),
        horizons=("D-1",),
        seed=12,
    )
    return [*first, *second]


def _segmented_plan(rows: Sequence[msb.FeatureRow]) -> msb.FoldPlan:
    return msb.build_folds(
        msb.days_by_version(rows),
        source_breaks=(_START + dt.timedelta(days=56),),
        block_days=14,
        min_train_days=14,
    )


class _CalibrationSpy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pools: list[list[tuple[str, dt.date]]] = []

        def _spy(all_rows: Sequence[Any], **kwargs: Any) -> Any:
            self.pools.append([(r.version, r.climate_day) for r in all_rows])
            return real_fit_calibration(all_rows, **kwargs)

        monkeypatch.setattr(f"{_FOLDS}.fit_calibration", _spy)


# ------------------------------------------------------------------ S1


def test_m0_pool_is_held_versions_train_days_plus_all_other_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _two_versions()
    plan = _segmented_plan(rows)
    spy = _CalibrationSpy(monkeypatch)
    msb.out_of_fold_scores(
        rows, plan, _settings(), levels=(0,), champion=True, m0_bootstrap_draws=_BOOT
    )
    by_version = msb.days_by_version(rows)
    assert len(plan.folds) >= 8
    assert len(spy.pools) == 2 * len(plan.folds)  # M0 pool, then the pooled sensitivity pool
    for index, fold in enumerate(plan.folds):
        m0_pool = spy.pools[2 * index]
        own = {d for v, d in m0_pool if v == fold.version}
        assert own == set(fold.train_days)  # not the other source segment's days
        assert not own & set(fold.held_days)
        for other in set(by_version) - {fold.version}:
            assert {d for v, d in m0_pool if v == other} == set(by_version[other])


def test_pooled_m0_is_reported_as_a_sensitivity_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _two_versions()
    plan = _segmented_plan(rows)
    spy = _CalibrationSpy(monkeypatch)
    scored = msb.out_of_fold_scores(
        rows, plan, _settings(), levels=(0,), champion=True, m0_bootstrap_draws=_BOOT
    )
    assert all("M0pooled" in s.crps and "M0" in s.crps for s in scored)
    index = 0
    fold = plan.folds[index]
    m0_pool, pooled = spy.pools[2 * index], spy.pools[2 * index + 1]
    assert set(m0_pool) < set(pooled)  # the sensitivity pool pads with the other segment's days
    in_segment_gap = {d for v, d in pooled if v == fold.version} - set(fold.held_days)
    assert in_segment_gap - set(fold.train_days)
    assert msb.mean_arm_crps(scored, "M0pooled") > 0.0


def test_embargo_keeps_days_near_the_held_block_out_of_m0_and_blend_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _two_versions()
    plan = _segmented_plan(rows)
    spy = _CalibrationSpy(monkeypatch)
    blend_train: list[list[dt.date]] = []

    def _blend_spy(train: Sequence[msb.FeatureRow], **kwargs: Any) -> Any:
        blend_train.append([r.climate_day for r in train])
        return msb.fit_blend(train, **kwargs)

    monkeypatch.setattr(f"{_FOLDS}.fit_blend", _blend_spy)
    embargo = 3
    msb.out_of_fold_scores(
        rows,
        plan,
        _settings(),
        levels=(0,),
        champion=True,
        m0_bootstrap_draws=_BOOT,
        embargo_days=embargo,
    )
    assert len(blend_train) == len(plan.folds)
    for index, fold in enumerate(plan.folds):
        held = fold.held_days
        near = {h + dt.timedelta(days=k) for h in held for k in range(-embargo, embargo + 1)} - set(
            held
        )
        assert near, "the fixture must have days to embargo"
        for pool in (spy.pools[2 * index], spy.pools[2 * index + 1]):
            assert not {d for _v, d in pool} & (near | set(held))
        assert not set(blend_train[index]) & (near | set(held))
        assert set(blend_train[index]) <= set(fold.train_days)


def test_zero_embargo_keeps_the_adjacent_training_days(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _two_versions()
    plan = _segmented_plan(rows)
    spy = _CalibrationSpy(monkeypatch)
    msb.out_of_fold_scores(
        rows, plan, _settings(), levels=(0,), champion=True, m0_bootstrap_draws=_BOOT
    )
    fold = plan.folds[1]  # an interior block has train days on both sides
    own = {d for v, d in spy.pools[2] if v == fold.version}
    assert min(fold.held_days) - dt.timedelta(days=1) in own


def test_negative_embargo_is_refused() -> None:
    rows = _two_versions()
    plan = _segmented_plan(rows)
    with pytest.raises(ValueError, match="embargo"):
        msb.out_of_fold_scores(
            rows, plan, _settings(), levels=(0,), champion=False, embargo_days=-1
        )


def test_fold_without_an_admissible_m0_pool_is_excluded_and_counted() -> None:
    # one version only: fit_calibration needs >= 2 versions, so no fold can score M0
    solo = make_rows(
        days=112, start=_START, version="v4.2", stations=("NYC",), horizons=("D-1",), seed=3
    )
    plan = _segmented_plan(solo)
    assert plan.folds
    eligible = msb.m0_eligible_plan(solo, plan, embargo_days=0)
    assert eligible.folds == ()
    reasons = [why for _v, _s, why in eligible.excluded]
    assert len(reasons) >= len(plan.folds)
    assert all("M0 pool" in why for why in reasons[-len(plan.folds) :])
    # a train-era-only pool has no validate/v5 row either
    train_only = [
        *make_rows(days=112, start=dt.date(2023, 1, 1), version="v4.1", stations=("NYC",)),
        *make_rows(days=112, start=dt.date(2023, 6, 1), version="v4.2", stations=("NYC",)),
    ]
    train_plan = msb.build_folds(
        msb.days_by_version(train_only), source_breaks=(), block_days=14, min_train_days=14
    )
    assert msb.m0_eligible_plan(train_only, train_plan, embargo_days=0).folds == ()
    rows = _two_versions()
    full = _segmented_plan(rows)
    kept = msb.m0_eligible_plan(rows, full, embargo_days=0)
    assert kept.folds == full.folds and kept.excluded == full.excluded


def test_scoring_an_ineligible_champion_fold_raises_never_pads() -> None:
    solo = make_rows(
        days=112, start=_START, version="v4.2", stations=("NYC",), horizons=("D-1",), seed=3
    )
    plan = _segmented_plan(solo)
    with pytest.raises(msb.InsufficientRowsError, match="M0 pool"):
        msb.out_of_fold_scores(
            solo, plan, _settings(), levels=(0,), champion=True, m0_bootstrap_draws=_BOOT
        )


# ------------------------------------------------------------------ S2 / S4


def _spread() -> float:
    return msb.fold_sd(_passing_inputs().m0_fold_crps)


def test_negative_control_with_positive_lower_bound_is_held_leak_audit() -> None:
    clean = msb.decide_acceptance(_passing_inputs(negative_control=_summary(0.01, -0.03)))
    assert clean.verdict is msb.Verdict.ACCEPT
    leaky = msb.decide_acceptance(_passing_inputs(negative_control=_summary(0.05, 0.01)))
    assert leaky.verdict is msb.Verdict.HELD_LEAK_AUDIT
    assert any("negative control" in reason for reason in leaky.reasons)
    boundary = msb.decide_acceptance(_passing_inputs(negative_control=_summary(0.0, 0.0)))
    assert boundary.verdict is msb.Verdict.ACCEPT  # the gate is LB > 0, strictly


def test_negative_control_summary_is_required() -> None:
    inputs = _passing_inputs()
    with pytest.raises(TypeError):
        msb.AcceptanceInputs(
            **{
                f.name: getattr(inputs, f.name)
                for f in dataclasses.fields(inputs)
                if f.name != "negative_control"
            }
        )


def test_leak_audit_also_checks_delta_m0_minus_m3() -> None:
    spread = _spread()
    verdict = msb.decide_acceptance(
        _passing_inputs(
            m0p_vs_m3=_summary(0.30, 0.20),
            m0_vs_m3=_summary(spread * 25.0, spread * 24.0),
            leak_audit_multiple=20.0,
        )
    )
    assert verdict.verdict is msb.Verdict.HELD_LEAK_AUDIT
    assert any("CRPS(M0) - CRPS(M3)" in reason for reason in verdict.reasons)


def test_report_carries_the_two_sided_m0_prime_difference() -> None:
    worse = msb.decide_acceptance(_passing_inputs(m0p_minus_m0=0.02))
    better = msb.decide_acceptance(_passing_inputs(m0p_minus_m0=-0.03))
    for decision, signed in ((worse, 0.02), (better, -0.03)):
        two_sided = decision.report["m0p_vs_m0_two_sided"]
        assert two_sided["difference"] == pytest.approx(signed)
        assert two_sided["abs_difference"] == pytest.approx(abs(signed))
    assert better.verdict is msb.Verdict.ACCEPT  # reported, never gating on the better side


# ------------------------------------------------------------------ S3


def _with_missing_mos(rows: Sequence[msb.FeatureRow], every: int) -> list[msb.FeatureRow]:
    return [
        dataclasses.replace(r, mos_mu_f=None, mos_available_at_ns=None) if i % every == 0 else r
        for i, r in enumerate(rows)
    ]


def test_complete_case_delta_and_level_counts_are_reported() -> None:
    rows = _with_missing_mos(
        make_rows(days=112, stations=("NYC", "LAX"), horizons=("D-1",), seed=9), every=3
    )
    plan = msb.build_folds(msb.days_by_version(rows), source_breaks=(), block_days=28)
    scored = msb.out_of_fold_scores(rows, plan, _settings(), levels=(0, 3), champion=False)
    counts = msb.level_counts(scored, "M3")
    assert sum(counts.values()) == len(scored)
    assert set(counts) <= {0, 1, 2, 3} and counts[3] > 0 and counts.get(2, 0) > 0
    complete = [s for s in scored if s.levels["M3"] == 3]
    manual = math.fsum(s.crps["M0prime"] - s.crps["M3"] for s in complete) / len(complete)
    out = msb.complete_case_delta(scored, "M0prime", "M3")
    assert out["n_rows"] == len(complete) == counts[3]
    assert out["mean"] == pytest.approx(manual)
    assert out["label"] == "diagnostic_only_never_gating"


def test_complete_case_delta_with_no_complete_rows_is_none() -> None:
    rows = _with_missing_mos(
        make_rows(days=60, stations=("NYC",), horizons=("D-1",), seed=2), every=1
    )
    plan = msb.build_folds(
        msb.days_by_version(rows), source_breaks=(), block_days=14, min_train_days=14
    )
    scored = msb.out_of_fold_scores(rows, plan, _settings(), levels=(0, 3), champion=False)
    out = msb.complete_case_delta(scored, "M0prime", "M3")
    assert out["n_rows"] == 0 and out["mean"] is None


def test_scored_row_json_round_trips_levels_and_fallbacks() -> None:
    pct = _pct(70.0, 2.5)
    row = msb.ScoredRow(
        station="NYC",
        climate_day=dt.date(2026, 5, 10),
        horizon="D-1",
        version="v5.0",
        fold_id=1,
        observed_f=70.0,
        crps={"M0prime": 1.0, "M3": 0.9},
        arm_predictions={"M3": msb.ArmPrediction(mu=70.0, sigma=2.0, nu=6.0)},
        champion=msb.ChampionSpec("NORMAL", pct, 0.0, 0.0, 0.0),
        levels={"M0prime": 0, "M3": 2},
        fell_back=("M3",),
    )
    assert msb.scored_row_from_json(msb.scored_row_to_json(row)) == row
    legacy = msb.scored_row_to_json(row)
    del legacy["levels"], legacy["fell_back"]
    assert msb.scored_row_from_json(legacy).levels == {}


# ------------------------------------------------------------------ P2


def test_smooth_sigma_floor_is_a_floor_and_nearly_identity_above_it() -> None:
    floor = 0.5
    assert msb.floored_sigma(-30.0, floor) >= floor
    assert msb.floored_sigma(-30.0, floor) == pytest.approx(floor, abs=1e-4)
    assert msb.floored_sigma(math.log(3.0), floor) == pytest.approx(3.0, rel=1e-3)
    grid = np.linspace(-3.0, 3.0, 61)
    values = [float(msb.floored_sigma(float(g), floor)) for g in grid]
    assert all(b > a for a, b in pairwise(values))  # strictly increasing


def test_smooth_sigma_floor_has_a_gradient_below_the_floor() -> None:
    floor = 0.5
    eta = math.log(0.9 * floor)  # exp(eta) is below the floor: a hard floor has zero slope here
    step = 1e-5
    slope = (
        float(msb.floored_sigma(eta + step, floor)) - float(msb.floored_sigma(eta - step, floor))
    ) / (2 * step)
    assert slope > 1e-3


def test_predict_row_uses_the_same_smooth_floor_as_the_fit() -> None:
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",), seed=4)
    fit = msb.fit_blend(rows, level=0, settings=_settings(sigma_floor_f=0.7))
    cell = fit.cells[(0, False)]
    row = rows[0]
    eta = cell.c + cell.d * math.log(row.percentiles.sd)
    assert msb.predict_row(fit, row)[1] == pytest.approx(
        float(msb.floored_sigma(eta, 0.7)), rel=1e-12
    )


def _fail_big_cells(monkeypatch: pytest.MonkeyPatch, *, fail_all: bool = False) -> None:

    def _fake(fun: Any, x0: Any, **kwargs: Any) -> OptimizeResult:
        result = minimize(fun, x0, **kwargs)
        if fail_all or len(x0) > 4:  # level-0 cell without obs has 4 parameters
            result.success = False
            result.message = "synthetic non-convergence"
        return result

    monkeypatch.setattr(f"{_FIT}.minimize", _fake)


def test_non_converged_cell_is_dropped_counted_and_falls_back_to_m0_prime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",), seed=4)
    _fail_big_cells(monkeypatch)
    fit = msb.fit_blend(rows, level=3, settings=_settings())
    assert fit.nonconverged == ((3, False),)
    assert (3, False) not in fit.cells and (0, False) in fit.cells
    _mu, sigma, level = msb.predict_row(fit, rows[0])
    assert level == 0 and math.isfinite(sigma)


def test_fallback_rows_are_recorded_on_the_scored_row(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = make_rows(days=112, stations=("NYC",), horizons=("D-1",), seed=4)
    plan = msb.build_folds(msb.days_by_version(rows), source_breaks=(), block_days=28)
    _fail_big_cells(monkeypatch)
    scored = msb.out_of_fold_scores(rows, plan, _settings(), levels=(0, 3), champion=False)
    assert scored and all(s.fell_back == ("M3",) and s.levels["M3"] == 0 for s in scored)
    # and with a healthy optimiser nothing falls back
    monkeypatch.undo()
    healthy = msb.out_of_fold_scores(rows, plan, _settings(), levels=(0, 3), champion=False)
    assert all(s.fell_back == () and s.levels["M3"] == 3 for s in healthy)


def test_non_converged_m0_prime_cell_cannot_fall_back_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",), seed=4)
    _fail_big_cells(monkeypatch, fail_all=True)
    with pytest.raises(msb.FitNotConvergedError):
        msb.fit_blend(rows, level=0, settings=_settings())


# ------------------------------------------------------------------ P3


def _assemble(percentiles: Percentiles, **overrides: Any) -> msb.FeatureRow:
    day = dt.date(2025, 3, 1)
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": day,
        "version": "v4.2",
        "horizon": "D-1",
        "anchor_ns": 1_740_000_000_000_000_000,
        "std_utc_offset_hours": -5.0,
        "percentiles": percentiles,
        "cli_tmax_f": 60.0,
    }
    kwargs.update(overrides)
    return msb.assemble_feature_row(**kwargs)


@pytest.mark.parametrize("bad_sd", [0.0, -1.0, float("nan"), float("inf")])
def test_assemble_feature_row_rejects_non_positive_or_non_finite_sd(bad_sd: float) -> None:
    pct = dataclasses.replace(_pct(60.0, 2.0), sd=bad_sd)
    with pytest.raises(msb.NonFiniteInputError):
        _assemble(pct)


@pytest.mark.parametrize("field", ["q10", "q25", "q50", "q75", "q90", "mean"])
def test_assemble_feature_row_rejects_non_finite_percentiles(field: str) -> None:
    pct = dataclasses.replace(_pct(60.0, 2.0), **{field: float("nan")})
    with pytest.raises(msb.NonFiniteInputError):
        _assemble(pct)


def test_validate_percentiles_is_the_one_boundary_check() -> None:
    msb.validate_percentiles(_pct(60.0, 2.0))
    with pytest.raises(msb.NonFiniteInputError):
        msb.validate_percentiles(dataclasses.replace(_pct(60.0, 2.0), sd=0.0))


def test_champion_spec_and_arm_prediction_refuse_degenerate_values() -> None:
    bad = dataclasses.replace(_pct(60.0, 2.0), sd=-2.0)
    with pytest.raises(msb.NonFiniteInputError):
        msb.ChampionSpec("NORMAL", bad, 0.0, 0.0, 0.0)
    for mu, sigma, nu in ((60.0, 0.0, 6.0), (60.0, float("nan"), 6.0), (60.0, 2.0, 0.0)):
        with pytest.raises(ValueError, match="sigma|nu|finite"):
            msb.ArmPrediction(mu, sigma, nu)
    with pytest.raises(msb.NonFiniteInputError):
        msb.ArmPrediction(float("inf"), 2.0, 6.0)


def test_feature_row_json_with_nan_sd_is_refused() -> None:
    row = _row(
        station="NYC",
        day=dt.date(2025, 3, 1),
        version="v4.2",
        horizon="D-1",
        y=60.0,
        nbp=60.0,
        sd=2.0,
        obs=None,
        lamp=None,
        pfm=None,
        mos=None,
    )
    data = msb.feature_row_to_json(row)
    data["percentiles"]["sd"] = float("nan")
    with pytest.raises(msb.NonFiniteInputError):
        msb.feature_row_from_json(data)
