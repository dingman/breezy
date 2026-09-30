"""RED-first tests for `breezy.analysis.nbp_calibration` (SL-8; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S7 row SL-8; ruling
`docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` S12; SL-8 review
2026-09-29 items 1, 2, 3, 4, 5).

All synthetic. Never touches the real v5.0 holdout (2026-07-01 onward) or
any real archive/parquet data -- every row here is hand-constructed.

Fitting calls (:func:`~breezy.analysis.nbp_calibration.fit_version_unshrunk`
and everything built on it) now run a real Nelder-Mead minimum-CRPS descent,
so row counts and bootstrap-draw counts are kept SMALL throughout to keep
this file fast -- the review's own gate gives no free pass on determinism or
correctness, only on population size.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import time
from pathlib import Path

import pytest
from scipy.optimize import minimize

from breezy.analysis import nbp_calibration as calib
from breezy.analysis import nbp_comparator_models as comparator
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def test_split_order_violation_raises() -> None:
    with pytest.raises(calib.SplitOrderError):
        calib.Splits(
            train=calib.SplitBounds("train", dt.date(2021, 1, 1), dt.date(2024, 12, 31)),
            # Overlaps train: validate starts ON train's own end date.
            validate=calib.SplitBounds("validate", dt.date(2024, 12, 31), dt.date(2026, 5, 3)),
            v5_fit_slice=calib.SplitBounds("v5_fit_slice", dt.date(2026, 5, 4), dt.date(2026, 6, 30)),
            holdout_start=dt.date(2026, 7, 1),
        )


def test_v5_fit_slice_overlapping_the_holdout_start_raises() -> None:
    with pytest.raises(calib.SplitOrderError):
        calib.Splits(
            train=calib.SplitBounds("train", dt.date(2021, 1, 1), dt.date(2024, 12, 31)),
            validate=calib.SplitBounds("validate", dt.date(2025, 1, 1), dt.date(2026, 5, 3)),
            v5_fit_slice=calib.SplitBounds("v5_fit_slice", dt.date(2026, 5, 4), dt.date(2026, 7, 1)),
            holdout_start=dt.date(2026, 7, 1),
        )


def test_default_splits_construct_without_error_and_classify_dates() -> None:
    splits = calib.DEFAULT_SPLITS
    assert splits.split_for_date(dt.date(2023, 6, 1)) == "train"
    assert splits.split_for_date(dt.date(2025, 6, 1)) == "validate"
    assert splits.split_for_date(dt.date(2026, 5, 15)) == "v5_fit_slice"
    assert splits.split_for_date(dt.date(2026, 9, 29)) == "holdout"


def test_a_date_before_every_split_raises() -> None:
    with pytest.raises(calib.SplitOrderError):
        calib.DEFAULT_SPLITS.split_for_date(dt.date(2020, 1, 1))


# ---------------------------------------------------------------------------
# n_min (ruling S12 A-3)
# ---------------------------------------------------------------------------


def test_n_min_matches_the_pinned_formula() -> None:
    sigma_d = 0.11
    result = calib.compute_n_min(sigma_d)
    expected_raw = (
        (calib.Z_ALPHA_TWO_SIDED_095 + calib.Z_POWER_080) * sigma_d / calib.G22_TARGET_DIFFERENCE_X
    ) ** 2
    assert result.n_min == math.ceil(expected_raw)
    # Matches the plan's own illustrative arithmetic (S4.1): ~412.
    assert result.n_min == pytest.approx(412, abs=2)
    assert result.feasible
    assert result.status == "OK"


def test_n_min_above_the_520_ceiling_is_infeasible() -> None:
    result = calib.compute_n_min(0.5)
    assert result.n_min > calib.N_MIN_CEILING
    assert not result.feasible
    assert result.status == calib.PMUS_INFEASIBLE_ROUTE_NODE4


def test_n_min_refuses_nonpositive_sigma_d() -> None:
    with pytest.raises(ValueError, match="sigma_d"):
        calib.compute_n_min(0.0)


# ---------------------------------------------------------------------------
# The holdout single-look marker
# ---------------------------------------------------------------------------


def test_open_holdout_refuses_below_n_min_and_writes_no_marker(tmp_path: Path) -> None:
    marker = tmp_path / "holdout.marker.json"
    with pytest.raises(calib.HoldoutInsufficientNError):
        calib.open_holdout(
            marker, today=dt.date(2026, 10, 1), final_station_day_count=100, n_min=412
        )
    assert not marker.exists()


def test_open_holdout_first_open_writes_the_marker() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "holdout.marker.json"
        record = calib.open_holdout(
            marker, today=dt.date(2026, 10, 17), final_station_day_count=420, n_min=412
        )
        assert marker.exists()
        assert record["final_station_day_count"] == 420


def test_open_holdout_second_open_without_c1_raises() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "holdout.marker.json"
        calib.open_holdout(marker, today=dt.date(2026, 10, 17), final_station_day_count=420, n_min=412)
        with pytest.raises(calib.HoldoutSingleLookError):
            calib.open_holdout(
                marker, today=dt.date(2026, 10, 18), final_station_day_count=421, n_min=412
            )


def test_open_holdout_reopens_with_a_c1_deviation() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "holdout.marker.json"
        calib.open_holdout(marker, today=dt.date(2026, 10, 17), final_station_day_count=420, n_min=412)
        deviation = calib.C1Deviation(
            declared_at=dt.date(2026, 11, 1), reason="G2.1 fails on holdout only", co_signed_by="mle-reviewer"
        )
        record = calib.open_holdout(
            marker,
            today=dt.date(2026, 11, 1),
            final_station_day_count=421,
            n_min=412,
            c1_deviation=deviation,
        )
        c1_deviation_record = record["c1_deviation"]
        assert isinstance(c1_deviation_record, dict)
        assert c1_deviation_record["co_signed_by"] == "mle-reviewer"


# ---------------------------------------------------------------------------
# CRPS (review item 2: shape-agnostic, numerical)
# ---------------------------------------------------------------------------


def test_crps_normal_at_the_observed_mean_matches_the_closed_form() -> None:
    # CRPS(N(0,1), 0) = 2*phi(0) - 1/sqrt(pi), a well-known closed value.
    value = calib.crps_normal(mu=0.0, sigma=1.0, observed=0.0)
    expected = 2.0 * (1.0 / math.sqrt(2.0 * math.pi)) - 1.0 / math.sqrt(math.pi)
    assert value == pytest.approx(expected, abs=1e-12)


def test_crps_normal_refuses_nonpositive_sigma() -> None:
    with pytest.raises(ValueError):
        calib.crps_normal(mu=0.0, sigma=0.0, observed=1.0)


def test_crps_numerical_matches_the_normal_closed_form_within_1e_4() -> None:
    mu, sigma, observed = 90.0, 3.0, 92.5
    normal_cdf = build_cdf(CdfMethod.NORMAL, Percentiles(mu - 4, mu - 2, mu, mu + 2, mu + 4, mu, sigma))
    numerical = calib.crps_numerical(normal_cdf, observed, center=mu)
    closed_form = calib.crps_normal(mu, sigma, observed)
    assert numerical == pytest.approx(closed_form, abs=1e-4)


def test_crps_numerical_refuses_nonpositive_half_width_or_step() -> None:
    cdf = build_cdf(CdfMethod.NORMAL, Percentiles(88, 89, 90, 91, 92, 90, 1.0))
    with pytest.raises(ValueError):
        calib.crps_numerical(cdf, 90.0, center=90.0, half_width=0.0)
    with pytest.raises(ValueError):
        calib.crps_numerical(cdf, 90.0, center=90.0, step=0.0)


# ---------------------------------------------------------------------------
# Fitting (review item 1: minimum-CRPS, not moment matching)
# ---------------------------------------------------------------------------


def _percentiles(q50: float, sd: float = 3.0) -> Percentiles:
    return Percentiles(q10=q50 - 4, q25=q50 - 2, q50=q50, q75=q50 + 2, q90=q50 + 4, mean=q50, sd=sd)


def _version_row(
    version: str, split: str, day: dt.date, station: str, q50: float, sd: float, cli: float
) -> calib.VersionRow:
    return calib.VersionRow(
        version=version,
        split=split,
        station=station,
        climate_day=day,
        percentiles=_percentiles(q50, sd),
        cli_tmax_f=cli,
    )


def test_fit_version_unshrunk_refuses_mixed_versions() -> None:
    rows = [
        _version_row("v4.3", "validate", dt.date(2025, 6, 1), "KMIA", 90.0, 2.0, 92.0),
        _version_row("v4.2", "validate", dt.date(2025, 6, 2), "KMIA", 90.0, 2.0, 92.0),
    ]
    with pytest.raises(ValueError, match="one version"):
        calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)


def _total_crps(rows: list[calib.VersionRow], *, method: CdfMethod, delta: float, a: float, gamma: float) -> float:
    """Reconstructs `fit_version_unshrunk`'s own objective from PUBLIC
    building blocks only (never reaches into the private closure) -- the
    grid check the review asks for."""
    total = 0.0
    for row in rows:
        calibrated_cdf = apply_emos(
            build_cdf(method, row.percentiles), row.percentiles, EmosParams(a=a, gamma=gamma, delta=delta)
        )
        total += calib.crps_numerical(calibrated_cdf, row.cli_tmax_f, center=row.percentiles.q50)
    return total


def _moment_matching_start(rows: list[calib.VersionRow], *, delta: float) -> tuple[float, float]:
    import statistics

    a0 = statistics.fmean(row.cli_tmax_f - row.percentiles.q50 for row in rows)
    ratios = [
        ((row.cli_tmax_f - (row.percentiles.q50 + a0)) ** 2) / (row.percentiles.sd ** (2.0 * delta))
        for row in rows
    ]
    gamma0 = 0.5 * math.log(max(statistics.fmean(ratios), 1e-12))
    return a0, gamma0


def _old_reference_fit_version_unshrunk(
    rows: list[calib.VersionRow], *, method: CdfMethod, delta: float
) -> tuple[float, float]:
    """Test-only copy of the pre-SL-8e optimiser/objective."""
    a0, gamma0 = _moment_matching_start(rows, delta=delta)
    base_cdfs = [build_cdf(method, row.percentiles) for row in rows]

    def total_crps(params: tuple[float, float]) -> float:
        a, gamma = params
        total = 0.0
        for row, base_cdf in zip(rows, base_cdfs, strict=True):
            calibrated_cdf = apply_emos(
                base_cdf, row.percentiles, EmosParams(a=a, gamma=gamma, delta=delta)
            )
            total += calib.crps_numerical(
                calibrated_cdf, row.cli_tmax_f, center=row.percentiles.q50
            )
        return total

    result = minimize(
        total_crps,
        x0=(a0, gamma0),
        method="Nelder-Mead",
        options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": calib.DEFAULT_VERSION_FIT_MAX_ITERATIONS},
    )
    assert result.success
    return float(result.x[0]), float(result.x[1])


def _seeded_normal_rows(
    *,
    n: int,
    version: str = "v4.3",
    split: str = "validate",
    start_day: dt.date = dt.date(2025, 1, 1),
) -> list[calib.VersionRow]:
    rows: list[calib.VersionRow] = []
    for i in range(n):
        q50 = 62.0 + 23.0 * math.sin(i / 47.0) + 4.0 * math.cos(i / 19.0)
        sd = 1.8 + (i % 11) * 0.37
        bias = 1.35
        residual = bias + math.sin(i * 1.7) * sd * 0.55 + math.cos(i / 13.0) * 0.8
        day = start_day + dt.timedelta(days=i)
        rows.append(_version_row(version, split, day, f"K{i % 17:03d}", q50, sd, q50 + residual))
    return rows


def test_fit_version_unshrunk_minimum_crps_differs_from_moment_matching_on_skewed_residuals() -> None:
    # Mostly-zero residuals with two large positive outliers -- a skewed
    # empirical residual distribution against a normal EMOS shape.
    q50 = 90.0
    rows = [
        _version_row("v4.3", "validate", dt.date(2025, 6, 1), "KMIA", q50, 3.0, q50),
        _version_row("v4.3", "validate", dt.date(2025, 6, 2), "KMIA", q50, 3.0, q50),
        _version_row("v4.3", "validate", dt.date(2025, 6, 3), "KMIA", q50, 3.0, q50),
        _version_row("v4.3", "validate", dt.date(2025, 6, 4), "KMIA", q50, 3.0, q50 + 18.0),
        _version_row("v4.3", "validate", dt.date(2025, 6, 5), "KMIA", q50, 3.0, q50 + 20.0),
    ]
    delta = 1.0
    a0, gamma0 = _moment_matching_start(rows, delta=delta)

    estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=delta)

    # The minimum-CRPS fit and the moment-matching start differ.
    assert (estimate.a, estimate.gamma) != pytest.approx((a0, gamma0), abs=1e-6)

    # Grid check: the returned (a, gamma) locally minimises total CRPS --
    # every neighbour on a small grid around it scores no better.
    at_fit = _total_crps(rows, method=CdfMethod.NORMAL, delta=delta, a=estimate.a, gamma=estimate.gamma)
    for da in (-0.5, 0.0, 0.5):
        for dg in (-0.2, 0.0, 0.2):
            if da == 0.0 and dg == 0.0:
                continue
            neighbour = _total_crps(
                rows, method=CdfMethod.NORMAL, delta=delta, a=estimate.a + da, gamma=estimate.gamma + dg
            )
            assert at_fit <= neighbour + 1e-6, (da, dg, at_fit, neighbour)


def test_fast_normal_fit_matches_old_reference_objective_on_seeded_rows() -> None:
    rows = _seeded_normal_rows(n=36)
    expected_a, expected_gamma = _old_reference_fit_version_unshrunk(
        rows, method=CdfMethod.NORMAL, delta=0.95
    )

    estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=0.95)

    assert estimate.converged is True
    assert estimate.a == pytest.approx(expected_a, abs=2e-3)
    assert estimate.gamma == pytest.approx(expected_gamma, abs=2e-3)


def test_v43_like_normal_fit_converges_at_realistic_scale() -> None:
    rows = _seeded_normal_rows(n=4_086, version="v4.3")

    estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)

    assert estimate.converged is True
    assert estimate.n == 4_086
    assert math.isfinite(estimate.a)
    assert math.isfinite(estimate.gamma)


def test_normal_fit_four_thousand_rows_stays_under_runtime_budget() -> None:
    rows = _seeded_normal_rows(n=4_000, version="v4.3")
    budget_seconds = 5.0

    started = time.perf_counter()
    estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
    elapsed = time.perf_counter() - started

    assert estimate.converged is True
    assert elapsed < budget_seconds


def test_fast_normal_fit_still_flags_forced_non_convergence() -> None:
    rows = _seeded_normal_rows(n=200, version="v4.3")

    estimate = calib.fit_version_unshrunk(
        rows, method=CdfMethod.NORMAL, delta=1.0, max_iterations=1
    )

    assert estimate.converged is False


def test_fit_shared_delta_is_deterministic_and_within_its_bracket() -> None:
    rows_by_version = {
        "v4.3": [
            _version_row("v4.3", "train", dt.date(2023, 1, day), "KMIA", 90.0, 3.0, 90.0 + 0.5 * day)
            for day in range(1, 4)
        ],
        "v4.2": [
            _version_row("v4.2", "train", dt.date(2023, 1, day), "KMIA", 88.0, 2.0, 88.0 + 0.3 * day)
            for day in range(1, 4)
        ],
    }
    first = calib.fit_shared_delta(rows_by_version, method=CdfMethod.NORMAL, bracket=(0.2, 2.0))
    second = calib.fit_shared_delta(rows_by_version, method=CdfMethod.NORMAL, bracket=(0.2, 2.0))
    assert first == second
    assert 0.2 <= first <= 2.0


def test_fit_shared_delta_refuses_empty_input() -> None:
    with pytest.raises(ValueError):
        calib.fit_shared_delta({}, method=CdfMethod.NORMAL)


# ---------------------------------------------------------------------------
# Shrinkage
# ---------------------------------------------------------------------------


def test_shrink_toward_lovo_pooled_mean_kappa_zero_is_unshrunk() -> None:
    target = calib.VersionEstimate(version="v5.0", a=3.0, gamma=0.5, n=50)
    others = [calib.VersionEstimate(version="v4.3", a=0.0, gamma=0.0, n=200)]
    shrunk = calib.shrink_toward_lovo_pooled_mean(target, others, kappa=0.0)
    assert shrunk.a == pytest.approx(3.0)
    assert shrunk.gamma == pytest.approx(0.5)


def test_shrink_toward_lovo_pooled_mean_kappa_infinite_is_full_pooling() -> None:
    target = calib.VersionEstimate(version="v5.0", a=3.0, gamma=0.5, n=50)
    others = [
        calib.VersionEstimate(version="v4.3", a=0.0, gamma=0.0, n=100),
        calib.VersionEstimate(version="v4.2", a=2.0, gamma=0.2, n=100),
    ]
    shrunk = calib.shrink_toward_lovo_pooled_mean(target, others, kappa=math.inf)
    assert shrunk.a == pytest.approx(1.0)  # (0*100 + 2*100)/200
    assert shrunk.gamma == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# LOVO kappa selection (review items 2 + 4)
# ---------------------------------------------------------------------------

#: Small grid so Nelder-Mead-backed fitting stays fast in tests.
_SMALL_KAPPA_GRID: tuple[float, ...] = (0.0, 60.0, math.inf)


def _synthetic_rows_by_version(n_per_version: int = 3, split: str = "validate") -> dict[str, list[calib.VersionRow]]:
    rows_by_version: dict[str, list[calib.VersionRow]] = {}
    for version, offset in (("v4.3", 1.0), ("v5.0", 2.0)):
        version_rows = []
        for i in range(n_per_version):
            day = dt.date(2025, 1, 1) + dt.timedelta(days=i)
            version_rows.append(_version_row(version, split, day, "KMIA", 90.0 + offset, 2.0, 92.0 + offset))
        rows_by_version[version] = version_rows
    return rows_by_version


def test_select_kappa_by_lovo_crps_reports_the_full_curve() -> None:
    rows_by_version = _synthetic_rows_by_version()
    selection = calib.select_kappa_by_lovo_crps(
        rows_by_version, method=CdfMethod.NORMAL, delta=1.0, grid=_SMALL_KAPPA_GRID
    )
    assert selection.chosen_kappa in _SMALL_KAPPA_GRID
    assert {score.kappa for score in selection.curve} <= set(_SMALL_KAPPA_GRID)
    assert len(selection.curve) >= 1


def test_select_kappa_by_lovo_crps_refuses_a_holdout_tagged_row() -> None:
    rows_by_version = _synthetic_rows_by_version()
    rows_by_version["v5.0"].append(_version_row("v5.0", "holdout", dt.date(2026, 7, 5), "KMIA", 90.0, 2.0, 92.0))
    with pytest.raises(calib.PrimaryHoldoutLeakError):
        calib.select_kappa_by_lovo_crps(rows_by_version, method=CdfMethod.NORMAL, delta=1.0, grid=_SMALL_KAPPA_GRID)


def test_skew_normal_cdf_gives_a_different_kappa_curve_than_normal() -> None:
    # Asymmetric percentiles -- NORMAL ignores the shape (mean/sd only);
    # SKEW_NORMAL fits through it, so the two methods' CDFs genuinely differ.
    # cli targets VARY across rows (never identical) so no (a, gamma) can
    # drive CRPS to a degenerate near-zero for every scored row at once --
    # otherwise both methods trivially converge to the same ~0 score.
    skewed = Percentiles(q10=85.0, q25=87.0, q50=90.0, q75=91.0, q90=92.0, mean=89.0, sd=3.0)
    rows_by_version = {
        "v4.3": [
            calib.VersionRow(
                "v4.3", "validate", "KMIA", dt.date(2025, 1, 1) + dt.timedelta(days=i), skewed, cli
            )
            for i, cli in enumerate((91.0, 89.0, 92.0, 87.5))
        ],
        "v5.0": [
            calib.VersionRow(
                "v5.0", "validate", "KMIA", dt.date(2025, 1, 1) + dt.timedelta(days=i), skewed, cli
            )
            for i, cli in enumerate((89.5, 91.5, 88.0, 93.0))
        ],
    }
    normal_selection = calib.select_kappa_by_lovo_crps(
        rows_by_version, method=CdfMethod.NORMAL, delta=1.0, grid=(0.0,)
    )
    skew_selection = calib.select_kappa_by_lovo_crps(
        rows_by_version, method=CdfMethod.SKEW_NORMAL, delta=1.0, grid=(0.0,)
    )
    assert normal_selection.curve[0].mean_crps != pytest.approx(skew_selection.curve[0].mean_crps, rel=1e-6)


def test_poisoned_holdout_leaves_kappa_and_every_parameter_byte_identical() -> None:
    rows_by_version = _synthetic_rows_by_version()
    all_rows_clean: list[calib.VersionRow] = []
    for version_rows in rows_by_version.values():
        all_rows_clean.extend(version_rows)
    holdout_rows = [
        _version_row("v5.0", "holdout", dt.date(2026, 7, 1) + dt.timedelta(days=i), "KMIA", 90.0, 2.0, 92.0)
        for i in range(2)
    ]
    all_rows_with_clean_holdout = [*all_rows_clean, *holdout_rows]

    poisoned_holdout_rows = [
        _version_row("v5.0", "holdout", dt.date(2026, 7, 1) + dt.timedelta(days=i), "KMIA", -999.0, 50.0, 999.0)
        for i in range(2)
    ]
    all_rows_with_poisoned_holdout = [*all_rows_clean, *poisoned_holdout_rows]

    clean_result = calib.fit_hierarchical_emos(
        all_rows_with_clean_holdout, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2
    )
    poisoned_result = calib.fit_hierarchical_emos(
        all_rows_with_poisoned_holdout, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2
    )

    assert clean_result.kappa_selection.chosen_kappa == poisoned_result.kappa_selection.chosen_kappa
    assert clean_result.kappa_selection.curve == poisoned_result.kappa_selection.curve
    for version in clean_result.shrunk_by_version:
        clean_estimate = clean_result.shrunk_by_version[version]
        poisoned_estimate = poisoned_result.shrunk_by_version[version]
        assert clean_estimate.a == poisoned_estimate.a
        assert clean_estimate.gamma == poisoned_estimate.gamma


def test_fit_hierarchical_emos_refuses_when_no_fit_rows_present() -> None:
    holdout_only = [
        _version_row("v5.0", "holdout", dt.date(2026, 7, 1), "KMIA", 90.0, 2.0, 92.0),
    ]
    with pytest.raises(ValueError, match="validate/v5_fit_slice"):
        calib.fit_hierarchical_emos(holdout_only, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2)


# ---------------------------------------------------------------------------
# Train-era versions (review item 4)
# ---------------------------------------------------------------------------


def test_train_era_versions_appear_in_the_artefact_and_shape_the_pool() -> None:
    validate_rows = _synthetic_rows_by_version()
    train_rows = [
        _version_row("v3.2", "train", dt.date(2021, 1, day), "KMIA", 88.0, 2.0, 88.0)
        for day in range(1, 4)
    ] + [
        _version_row("v4.0", "train", dt.date(2022, 1, day), "KMIA", 89.0, 2.0, 89.0)
        for day in range(1, 4)
    ]
    all_rows = [*validate_rows["v4.3"], *validate_rows["v5.0"], *train_rows]

    result = calib.fit_hierarchical_emos(all_rows, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2)

    assert "v3.2" in result.shrunk_by_version
    assert "v4.0" in result.shrunk_by_version
    # Train-era versions are unshrunk (their own fit, byte for byte).
    from_train_pool = {"v3.2", "v4.0"}
    assert from_train_pool <= result.shrunk_by_version.keys()
    assert "v3.2" in result.draws_by_version
    assert "v4.0" in result.draws_by_version


def test_kappa_scoring_never_reads_train_rows_as_scored_halves() -> None:
    validate_rows = _synthetic_rows_by_version()
    train_rows_clean = [
        _version_row("v3.2", "train", dt.date(2021, 1, day), "KMIA", 88.0, 2.0, 88.0) for day in range(1, 4)
    ]
    train_rows_poisoned = [
        _version_row("v3.2", "train", dt.date(2021, 1, day), "KMIA", -500.0, 90.0, 500.0) for day in range(1, 4)
    ]
    all_rows_clean = [*validate_rows["v4.3"], *validate_rows["v5.0"], *train_rows_clean]
    all_rows_poisoned = [*validate_rows["v4.3"], *validate_rows["v5.0"], *train_rows_poisoned]

    clean_result = calib.fit_hierarchical_emos(all_rows_clean, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2)
    poisoned_result = calib.fit_hierarchical_emos(
        all_rows_poisoned, method=CdfMethod.NORMAL, delta=1.0, bootstrap_draws=2
    )

    # The kappa-selection CURVE (scored only on validate rows) is unaffected
    # by wildly different train-era values -- train rows are never a scored
    # half.
    assert clean_result.kappa_selection.curve == poisoned_result.kappa_selection.curve
    assert clean_result.kappa_selection.chosen_kappa == poisoned_result.kappa_selection.chosen_kappa


# ---------------------------------------------------------------------------
# Bootstrap parameter draws (review item 3)
# ---------------------------------------------------------------------------


def test_bootstrap_emos_draws_produces_the_requested_count_per_version() -> None:
    rows_by_version = _synthetic_rows_by_version()
    shrunk_by_version = {
        version: calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
        for version, rows in rows_by_version.items()
    }
    draws = calib.bootstrap_emos_draws(
        rows_by_version, shrunk_by_version, method=CdfMethod.NORMAL, delta=1.0, draws=4
    )
    for version_draws in draws.values():
        assert len(version_draws.draws) == 4


def test_bootstrap_emos_draws_with_resample_delta_false_pins_every_draws_delta() -> None:
    # The pre-SL-8b fixed-delta convention, still reachable via
    # resample_delta=False (SL-8b review item 3's own interval-width
    # comparison needs both modes on the same input).
    rows_by_version = _synthetic_rows_by_version()
    shrunk_by_version = {
        version: calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
        for version, rows in rows_by_version.items()
    }
    draws = calib.bootstrap_emos_draws(
        rows_by_version,
        shrunk_by_version,
        method=CdfMethod.NORMAL,
        delta=1.0,
        draws=4,
        resample_delta=False,
    )
    for version_draws in draws.values():
        for draw in version_draws.draws:
            assert draw.delta == pytest.approx(1.0)


def test_bootstrap_emos_draws_is_deterministic_under_a_fixed_seed() -> None:
    rows_by_version = _synthetic_rows_by_version()
    shrunk_by_version = {
        version: calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
        for version, rows in rows_by_version.items()
    }
    first = calib.bootstrap_emos_draws(
        rows_by_version, shrunk_by_version, method=CdfMethod.NORMAL, delta=1.0, draws=3, seed=42
    )
    second = calib.bootstrap_emos_draws(
        rows_by_version, shrunk_by_version, method=CdfMethod.NORMAL, delta=1.0, draws=3, seed=42
    )
    for version in first:
        assert first[version].draws == second[version].draws


def test_bootstrap_emos_draws_repeats_the_point_for_a_version_with_no_own_rows() -> None:
    shrunk_by_version = {"v3.2": calib.VersionEstimate(version="v3.2", a=1.0, gamma=0.0, n=10)}
    draws = calib.bootstrap_emos_draws({}, shrunk_by_version, method=CdfMethod.NORMAL, delta=1.0, draws=3)
    assert draws["v3.2"].draws == (draws["v3.2"].point,) * 3


def test_bootstrap_emos_draws_pools_delta_across_versions_jointly() -> None:
    """SL-8b review item 3: each bootstrap draw's shared delta comes from a
    POOLED cluster resample spanning every version's rows, refit ONCE and
    shared by every version in that draw -- never a per-version-alone
    refit (the SL-8b-original bug this closes).

    Version A's own rows (residual spread nearly flat across sd, 1.0 vs
    5.0) alone identify a LOW delta; version B's own rows (residual spread
    growing sharply with sd) alone identify a visibly HIGHER delta --
    hand-verified below via `fit_shared_delta` on each version alone. If
    the bootstrap still refit delta per-version-alone, draw A's delta would
    track A's own ~0.25 and draw B's would track B's own ~2.0, and the two
    would differ. Pooled, both versions in the SAME draw must carry the
    IDENTICAL shared delta.
    """
    rows_a = [
        _version_row("A", "validate", dt.date(2025, 1, 1), "KMIA", 90.0, 1.0, 90.2),
        _version_row("A", "validate", dt.date(2025, 1, 2), "KMIA", 90.0, 1.0, 89.8),
        _version_row("A", "validate", dt.date(2025, 1, 3), "KMIA", 90.0, 5.0, 90.3),
        _version_row("A", "validate", dt.date(2025, 1, 4), "KMIA", 90.0, 5.0, 89.7),
    ]
    rows_b = [
        _version_row("B", "validate", dt.date(2025, 1, 1), "KMIA", 90.0, 1.0, 90.1),
        _version_row("B", "validate", dt.date(2025, 1, 2), "KMIA", 90.0, 1.0, 89.9),
        _version_row("B", "validate", dt.date(2025, 1, 3), "KMIA", 90.0, 5.0, 92.5),
        _version_row("B", "validate", dt.date(2025, 1, 4), "KMIA", 90.0, 5.0, 87.5),
    ]
    rows_by_version = {"A": rows_a, "B": rows_b}

    delta_a_alone = calib.fit_shared_delta({"A": rows_a}, method=CdfMethod.NORMAL)
    delta_b_alone = calib.fit_shared_delta({"B": rows_b}, method=CdfMethod.NORMAL)
    assert abs(delta_a_alone - delta_b_alone) > 1.0  # visibly different single-version fits

    shrunk_by_version = {
        version: calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
        for version, rows in rows_by_version.items()
    }
    draws = calib.bootstrap_emos_draws(
        rows_by_version, shrunk_by_version, method=CdfMethod.NORMAL, delta=1.0, draws=3, seed=7
    )
    for i in range(3):
        delta_a_draw = draws["A"].draws[i].delta
        delta_b_draw = draws["B"].draws[i].delta
        # Pooled: both versions share the IDENTICAL per-draw delta.
        assert delta_a_draw == pytest.approx(delta_b_draw)
        # And it is pulled away from A's own flat-alone value by B's
        # pooled-in data -- never simply A's own single-version fit.
        assert delta_a_draw != pytest.approx(delta_a_alone, abs=0.3)


# ---------------------------------------------------------------------------
# G2.0 correction form (closed set)
# ---------------------------------------------------------------------------


def test_parse_correction_form_outside_the_closed_set_raises() -> None:
    with pytest.raises(calib.InvalidCorrectionFormError):
        calib.parse_correction_form("quadratic_in_day_length")


def test_parse_correction_form_accepts_every_member_of_the_closed_set() -> None:
    for member in calib.CorrectionForm:
        assert calib.parse_correction_form(member.value) is member


def test_apply_correction_form_none_is_identity() -> None:
    result = calib.apply_correction_form(
        calib.CorrectionForm.NONE, residual_f=1.5, month=6, day_length_hours=14.0
    )
    assert result == pytest.approx(1.5)


def test_apply_correction_form_month_offset_subtracts_the_offset() -> None:
    result = calib.apply_correction_form(
        calib.CorrectionForm.MONTH_OFFSET,
        residual_f=2.0,
        month=6,
        day_length_hours=14.0,
        month_offsets={6: 0.5},
    )
    assert result == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Holm correction
# ---------------------------------------------------------------------------


def test_holm_correction_matches_a_hand_worked_example() -> None:
    # Classic step-down example: alpha=0.05, k=4.
    p_values = {"a": 0.005, "b": 0.01, "c": 0.03, "d": 0.04}
    result = calib.holm_correction(p_values, alpha=0.05)
    assert result["a"]["rejected"] is True  # 0.005 <= 0.05/4 = 0.0125
    assert result["b"]["rejected"] is True  # 0.01  <= 0.05/3 = 0.01667
    assert result["c"]["rejected"] is False  # 0.03  >  0.05/2 = 0.025 -> stop
    assert result["d"]["rejected"] is False  # step-down already stopped


def test_holm_correction_refuses_an_empty_set() -> None:
    with pytest.raises(ValueError):
        calib.holm_correction({})


# ---------------------------------------------------------------------------
# G2.0 / G2.0a (+ review item 5: bootstrap_degenerate)
# ---------------------------------------------------------------------------


def _residual(station: str, day: dt.date, residual_f: float, day_length: float = 12.0) -> calib.StationDayResidual:
    return calib.StationDayResidual(
        station=station, climate_day=day, residual_f=residual_f, day_length_hours=day_length
    )


def test_g20_months_below_n_are_untested_never_tested() -> None:
    # 10 rows across 5 distinct January dates -- below both N=60 and 15 dates.
    rows = [
        _residual("KMIA", dt.date(2025, 1, (day % 5) + 1), 0.1 * (day % 3 - 1))
        for day in range(10)
    ]
    result = calib.evaluate_g20(rows, tercile_edges=(10.0, 14.0))
    month_group = next(group for group in result.groups if group.key == "month_01")
    assert month_group.status == "UNTESTED"
    assert month_group.p_value is None
    assert month_group.holm_rejected is None
    assert month_group.bootstrap_degenerate is None
    # No group was ever tested -> vacuously flat.
    assert result.flat is True


def test_g20_tested_group_reports_bootstrap_degenerate_false_when_var_is_present() -> None:
    # 60+ rows across >=15 dates with varying residuals -- a real, non-degenerate
    # bootstrap.
    rows = [
        _residual(f"K{i % 4}", dt.date(2025, 6, 1) + dt.timedelta(days=i % 20), 0.1 * ((i % 7) - 3))
        for i in range(70)
    ]
    result = calib.evaluate_g20(rows, tercile_edges=(10.0, 14.0))
    month_group = next(group for group in result.groups if group.key == "month_06")
    assert month_group.status == "TESTED"
    assert month_group.bootstrap_degenerate is False


def test_g20a_untested_below_n_and_flat_when_empty() -> None:
    rows = [_residual("KMIA", dt.date(2025, 6, day), 0.05) for day in range(1, 6)]
    result = calib.evaluate_g20a(rows, stratum_of_station={"KMIA": "KMIA"})
    assert result.groups[0].status == "UNTESTED"
    assert result.groups[0].bootstrap_degenerate is None
    assert result.flat is True


def test_g20a_ignores_stations_outside_the_stratum_map() -> None:
    rows = [_residual("KDEN", dt.date(2025, 6, day), 0.05) for day in range(1, 6)]
    result = calib.evaluate_g20a(rows, stratum_of_station={"KMIA": "KMIA"})
    assert result.groups == ()
    assert result.flat is True


# ---------------------------------------------------------------------------
# SL-8b2: no S2 gate may report PASS or FAIL on a non-converged fit.
# ---------------------------------------------------------------------------


def test_g20_refuses_on_a_non_converged_fit_status() -> None:
    rows = [_residual("KMIA", dt.date(2025, 1, 1), 0.05)]
    with pytest.raises(calib.FitNotConvergedError):
        calib.evaluate_g20(
            rows, tercile_edges=(10.0, 14.0), fit_status=calib.FIT_STATUS_NOT_CONVERGED
        )


def test_g20a_refuses_on_an_unknown_fit_status() -> None:
    rows = [_residual("KMIA", dt.date(2025, 1, 1), 0.05)]
    with pytest.raises(calib.FitNotConvergedError):
        calib.evaluate_g20a(
            rows, stratum_of_station={"KMIA": "KMIA"}, fit_status=calib.FIT_STATUS_UNKNOWN
        )


# ---------------------------------------------------------------------------
# G2.1 (+ review item 5)
# ---------------------------------------------------------------------------


def _rung_event(station: str, day: dt.date, p_model: float, outcome: bool) -> calib.RungEvent:
    return calib.RungEvent(station=station, climate_day=day, rung_id="r", p_model=p_model, outcome=outcome)


def test_g21_rejects_a_starkly_miscalibrated_bucket_and_flags_it_degenerate() -> None:
    # 40 events, all forecast p=0.1, but outcome is True every time -- an
    # enormous, unmistakable miscalibration no bootstrap noise could hide,
    # AND a zero-variance bootstrap (every drawn outcome is True).
    events = [
        _rung_event(f"K{i % 4}", dt.date(2025, 1, 1) + dt.timedelta(days=i), 0.1, True) for i in range(40)
    ]
    result = calib.evaluate_g21(events, iterations=200)
    assert not result.passed
    assert any(bucket.holm_rejected for bucket in result.buckets)
    assert all(bucket.bootstrap_degenerate for bucket in result.buckets)


def test_g21_with_no_populated_bucket_trivially_passes() -> None:
    events = [_rung_event("KMIA", dt.date(2025, 1, 1), 0.5, True)]
    result = calib.evaluate_g21(events)
    assert result.buckets == ()
    assert result.passed is True


def test_g21_refuses_on_a_non_converged_fit_status() -> None:
    events = [_rung_event("KMIA", dt.date(2025, 1, 1), 0.5, True)]
    with pytest.raises(calib.FitNotConvergedError):
        calib.evaluate_g21(events, fit_status=calib.FIT_STATUS_NOT_CONVERGED)


# ---------------------------------------------------------------------------
# G2.2 / G2.3
# ---------------------------------------------------------------------------


def _matched_events(n: int) -> list[calib.MatchedEvent]:
    events = []
    for i in range(n):
        outcome = i % 2 == 0
        events.append(
            calib.MatchedEvent(
                station=f"K{i % 4}",
                climate_day=dt.date(2025, 1, 1) + dt.timedelta(days=i),
                p_m2=0.9 if outcome else 0.1,
                p_m1=0.5,
                p_m0=0.5,
                outcome=outcome,
            )
        )
    return events


def test_g22_passes_when_m2_clearly_resolves_better_than_m1() -> None:
    events = _matched_events(40)
    result = calib.evaluate_g22(events, iterations=200)
    assert result.passed
    assert result.d_res_ci[0] > 0.0


def test_g23_passes_when_m2_clearly_beats_m0_by_more_than_the_floor() -> None:
    events = _matched_events(40)
    result = calib.evaluate_g23(events, iterations=200)
    assert result.passed
    assert result.d_res_ci[0] > 0.0
    assert result.d_res_point >= calib.G22_TARGET_DIFFERENCE_X


def test_g23_fails_when_m2_and_m0_are_identical() -> None:
    events = [
        calib.MatchedEvent(
            station=f"K{i % 4}",
            climate_day=dt.date(2025, 1, 1) + dt.timedelta(days=i),
            p_m2=0.5,
            p_m1=0.5,
            p_m0=0.5,
            outcome=i % 2 == 0,
        )
        for i in range(20)
    ]
    result = calib.evaluate_g23(events, iterations=200)
    assert not result.passed
    assert result.d_res_point == pytest.approx(0.0, abs=1e-9)


def test_g22_refuses_on_a_non_converged_fit_status() -> None:
    events = _matched_events(10)
    with pytest.raises(calib.FitNotConvergedError):
        calib.evaluate_g22(events, iterations=200, fit_status=calib.FIT_STATUS_NOT_CONVERGED)


def test_g23_refuses_on_a_non_converged_fit_status() -> None:
    events = _matched_events(10)
    with pytest.raises(calib.FitNotConvergedError):
        calib.evaluate_g23(events, iterations=200, fit_status=calib.FIT_STATUS_NOT_CONVERGED)


# ---------------------------------------------------------------------------
# C-1
# ---------------------------------------------------------------------------


def test_c1_reevaluate_refuses_a_row_inside_the_primary_holdout_window() -> None:
    deviation = calib.C1Deviation(
        declared_at=dt.date(2026, 11, 1), reason="G2.1 holdout-only failure", co_signed_by="mle-reviewer"
    )
    primary_window = (dt.date(2026, 7, 1), dt.date(2026, 10, 31))
    events = _matched_events(10)  # dates start 2025-01-01 -- outside the window, except one row we poison.
    tainted_events = [*events[:-1], dataclasses_replace(events[-1], climate_day=dt.date(2026, 8, 15))]
    with pytest.raises(calib.PrimaryHoldoutLeakError):
        calib.reevaluate_c1(
            deviation=deviation,
            primary_holdout_window=primary_window,
            g20_rows=[],
            g20a_rows=[],
            g20a_stratum_of_station={},
            g21_events=[],
            g22_events=[],
            g23_events=tainted_events,
            tercile_edges=(10.0, 14.0),
        )


def test_c1_reevaluate_runs_the_full_gate_set_when_clean() -> None:
    deviation = calib.C1Deviation(
        declared_at=dt.date(2026, 11, 1), reason="G2.1 holdout-only failure", co_signed_by="mle-reviewer"
    )
    primary_window = (dt.date(2026, 7, 1), dt.date(2026, 10, 31))
    events = _matched_events(10)  # all in 2025, outside the primary window.
    result = calib.reevaluate_c1(
        deviation=deviation,
        primary_holdout_window=primary_window,
        g20_rows=[],
        g20a_rows=[],
        g20a_stratum_of_station={},
        g21_events=[],
        g22_events=events,
        g23_events=events,
        tercile_edges=(10.0, 14.0),
    )
    assert result.deviation is deviation
    assert result.g20.groups == ()
    assert isinstance(result.g22.passed, bool)
    assert isinstance(result.g23.passed, bool)


def test_c1_reevaluate_refuses_on_a_non_converged_fit_status() -> None:
    """SL-8b2: none of the four C-1 gates may report a result computed from
    a fit that did not converge -- refuses BEFORE returning a
    ``C1Reevaluation`` a caller might otherwise trust."""
    deviation = calib.C1Deviation(
        declared_at=dt.date(2026, 11, 1), reason="G2.1 holdout-only failure", co_signed_by="mle-reviewer"
    )
    primary_window = (dt.date(2026, 7, 1), dt.date(2026, 10, 31))
    events = _matched_events(10)  # all in 2025, outside the primary window.
    with pytest.raises(calib.FitNotConvergedError):
        calib.reevaluate_c1(
            deviation=deviation,
            primary_holdout_window=primary_window,
            g20_rows=[],
            g20a_rows=[],
            g20a_stratum_of_station={},
            g21_events=[],
            g22_events=events,
            g23_events=events,
            tercile_edges=(10.0, 14.0),
            fit_status=calib.FIT_STATUS_NOT_CONVERGED,
        )


# ---------------------------------------------------------------------------
# The artefact (review item 3: draws replace the degenerate (p, p) bound)
# ---------------------------------------------------------------------------


def _fixed_artefact() -> calib.NbpCalibrationArtefact:
    percentiles = Percentiles(q10=86.0, q25=88.0, q50=90.0, q75=92.0, q90=94.0, mean=90.0, sd=3.0)
    rungs = (
        Rung("lt_88", None, 87),
        Rung("88_91", 88, 91),
        Rung("gt_91", 92, None),
    )
    draws = (
        EmosParams(a=0.3, gamma=0.05, delta=1.0),
        EmosParams(a=0.5, gamma=0.1, delta=1.0),
        EmosParams(a=0.7, gamma=0.15, delta=1.0),
    )
    bounds = calib.rung_bounds_from_calibration(percentiles, CdfMethod.NORMAL, draws, rungs)
    return calib.NbpCalibrationArtefact(
        schema_version=calib.ARTEFACT_SCHEMA_VERSION,
        cdf_method=CdfMethod.NORMAL.value,
        recalibration="none",
        correction_form=calib.CorrectionForm.NONE.value,
        delta=1.0,
        kappa=120.0,
        emos_params_by_version={"v5.0": (0.5, 0.1), "v4.3": (0.0, 0.0)},
        emos_draws_by_version={
            "v5.0": ((0.4, 0.08, 1.0), (0.5, 0.1, 1.0), (0.6, 0.12, 1.0)),
            "v4.3": ((-0.1, 0.0, 1.0), (0.0, 0.0, 1.0), (0.1, 0.0, 1.0)),
        },
        n_min=412,
        sigma_d=0.11,
        rung_probability_bounds=bounds,
    )


def test_artefact_rung_bounds_are_point_lower_upper_triples() -> None:
    artefact = _fixed_artefact()
    for point, lower, upper in artefact.rung_probability_bounds.values():
        assert lower <= point <= upper


def test_artefact_sha_is_stable_under_a_fixed_seed() -> None:
    first = calib.artefact_sha256(_fixed_artefact())
    second = calib.artefact_sha256(_fixed_artefact())
    assert first == second
    assert len(first) == 64


def test_artefact_json_carries_emos_draws_by_version() -> None:
    payload = calib.artefact_json(_fixed_artefact())
    assert '"emos_draws_by_version"' in payload
    assert '"v5.0":[[0.4,0.08,1.0],[0.5,0.1,1.0],[0.6,0.12,1.0]]' in payload


def test_artefact_json_round_trips_kappa_infinity_as_a_string() -> None:
    artefact = calib.NbpCalibrationArtefact(
        schema_version=1,
        cdf_method="normal",
        recalibration="none",
        correction_form="none",
        delta=1.0,
        kappa=math.inf,
        emos_params_by_version={},
        emos_draws_by_version={},
        n_min=412,
        sigma_d=0.11,
        rung_probability_bounds={},
    )
    payload = calib.artefact_json(artefact)
    assert '"kappa":"inf"' in payload


def test_write_artefact_writes_json_and_sha256_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "nbp_calibration.json"
    digest = calib.write_artefact(path, _fixed_artefact())
    assert path.exists()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    assert sidecar.exists()
    assert sidecar.read_text().strip() == digest
    assert digest == calib.artefact_sha256(_fixed_artefact())


def test_write_artefact_refuses_a_non_ok_fit_status(tmp_path: Path) -> None:
    """SL-8b2: `write_artefact` is the ONE path live code sees calibration
    through (module docstring) -- it must refuse a non-converged fit rather
    than write it where the live strategy could load it."""
    artefact = dataclasses.replace(_fixed_artefact(), fit_status=calib.FIT_STATUS_NOT_CONVERGED)
    path = tmp_path / "nbp_calibration.json"

    with pytest.raises(calib.FitNotConvergedError):
        calib.write_artefact(path, artefact)

    assert not path.exists()


def test_write_artefact_refuses_an_unknown_fit_status(tmp_path: Path) -> None:
    artefact = dataclasses.replace(_fixed_artefact(), fit_status=calib.FIT_STATUS_UNKNOWN)
    path = tmp_path / "nbp_calibration.json"

    with pytest.raises(calib.FitNotConvergedError):
        calib.write_artefact(path, artefact)

    assert not path.exists()


def dataclasses_replace(instance: calib.MatchedEvent, **changes: object) -> calib.MatchedEvent:
    return dataclasses.replace(instance, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SL-8b review item 1: pipeline glue -- fit_calibration wires
# fit_shared_delta's output into fit_hierarchical_emos in one entry point.
# ---------------------------------------------------------------------------


def _calibration_fixture_rows() -> list[calib.VersionRow]:
    rows: list[calib.VersionRow] = []
    for version, offset in (("v4.3", 1.0), ("v5.0", 2.0)):
        for i in range(3):
            day = dt.date(2021, 1, 1) + dt.timedelta(days=i)
            rows.append(_version_row(version, "train", day, "KMIA", 90.0 + offset, 2.0, 90.0 + offset + 0.3 * i))
        for i in range(3):
            day = dt.date(2025, 1, 1) + dt.timedelta(days=i)
            rows.append(_version_row(version, "validate", day, "KMIA", 90.0 + offset, 2.0, 92.0 + offset))
    return rows


def test_fit_calibration_delta_matches_fit_shared_delta_on_the_same_train_rows() -> None:
    rows = _calibration_fixture_rows()
    train_by_version: dict[str, list[calib.VersionRow]] = {}
    for row in rows:
        if row.split == "train":
            train_by_version.setdefault(row.version, []).append(row)
    expected_delta = calib.fit_shared_delta(train_by_version, method=CdfMethod.NORMAL)

    result = calib.fit_calibration(rows, method=CdfMethod.NORMAL, bootstrap_draws=2)

    assert result.delta == pytest.approx(expected_delta)
    # The SAME delta is what fit_hierarchical_emos actually fit the
    # per-version (a_v, gamma_v) against -- the whole point of "one entry
    # point" (review item 1).
    assert result.hierarchical.delta == pytest.approx(expected_delta)


def test_fit_calibration_falls_back_to_validate_rows_when_no_train_rows_present() -> None:
    rows_by_version = _synthetic_rows_by_version(n_per_version=4, split="validate")
    all_rows = [row for rows in rows_by_version.values() for row in rows]
    expected_delta = calib.fit_shared_delta(rows_by_version, method=CdfMethod.NORMAL)

    result = calib.fit_calibration(all_rows, method=CdfMethod.NORMAL, bootstrap_draws=2)

    assert result.delta == pytest.approx(expected_delta)
    assert result.hierarchical.delta == pytest.approx(expected_delta)


def test_fit_calibration_refuses_when_no_eligible_rows_present() -> None:
    holdout_only = [
        _version_row("v5.0", "holdout", dt.date(2026, 7, 1), "KMIA", 90.0, 2.0, 92.0),
    ]
    with pytest.raises(ValueError, match="fit_calibration needs"):
        calib.fit_calibration(holdout_only, method=CdfMethod.NORMAL)


# ---------------------------------------------------------------------------
# SL-8b review item 2: convergence flags carried into the artefact + parsed
# back, and a gate-blocking fit_status -- fit_calibration is the path a
# writable artefact actually comes from.
# ---------------------------------------------------------------------------


def test_artefact_from_calibration_fit_carries_real_convergence_diagnostics() -> None:
    rows = _calibration_fixture_rows()
    fit = calib.fit_calibration(rows, method=CdfMethod.NORMAL, bootstrap_draws=2)

    artefact = calib.artefact_from_calibration_fit(
        fit,
        cdf_method=CdfMethod.NORMAL,
        recalibration="emos",
        correction_form=calib.CorrectionForm.NONE,
        n_min=412,
        sigma_d=0.11,
        rung_probability_bounds={},
    )

    assert artefact.delta_converged == fit.delta_converged
    assert artefact.delta_nfev == fit.delta_nfev
    assert artefact.converged_by_version == {
        version: estimate.converged for version, estimate in fit.hierarchical.shrunk_by_version.items()
    }
    assert artefact.nfev_by_version == {
        version: estimate.nfev for version, estimate in fit.hierarchical.shrunk_by_version.items()
    }
    # This fixture's tiny, well-behaved fit converges cleanly.
    assert fit.delta_converged is True
    assert all(estimate.converged for estimate in fit.hierarchical.shrunk_by_version.values())
    assert artefact.fit_status == calib.FIT_STATUS_OK


def test_artefact_from_calibration_fit_blocks_on_a_forced_non_convergent_delta_fit() -> None:
    # delta_max_iterations=1 forces the bounded scalar minimiser to stop
    # before converging (fit_shared_delta_with_diagnostics's own documented
    # deterministic-non-convergence knob) -- never a flaky/random failure.
    rows = _calibration_fixture_rows()
    fit = calib.fit_calibration(rows, method=CdfMethod.NORMAL, bootstrap_draws=2, delta_max_iterations=1)
    assert fit.delta_converged is False

    artefact = calib.artefact_from_calibration_fit(
        fit,
        cdf_method=CdfMethod.NORMAL,
        recalibration="emos",
        correction_form=calib.CorrectionForm.NONE,
        n_min=412,
        sigma_d=0.11,
        rung_probability_bounds={},
    )

    assert artefact.delta_converged is False
    # A gate-blocking flag, not only the WARNING fit_shared_delta_with_
    # diagnostics already logs.
    assert artefact.fit_status == calib.FIT_STATUS_NOT_CONVERGED


def test_artefact_from_json_dict_round_trips_the_new_convergence_fields() -> None:
    artefact = calib.NbpCalibrationArtefact(
        schema_version=calib.ARTEFACT_SCHEMA_VERSION,
        cdf_method="normal",
        recalibration="none",
        correction_form="none",
        delta=1.0,
        kappa=120.0,
        emos_params_by_version={"v5.0": (0.5, 0.1)},
        emos_draws_by_version={"v5.0": ((0.4, 0.08, 1.0), (0.6, 0.12, 1.0))},
        n_min=412,
        sigma_d=0.11,
        rung_probability_bounds={},
        delta_converged=False,
        delta_nfev=2,
        converged_by_version={"v5.0": False},
        nfev_by_version={"v5.0": 59},
        fit_status=calib.FIT_STATUS_NOT_CONVERGED,
    )
    payload = json.loads(calib.artefact_json(artefact))

    parsed = calib.artefact_from_json_dict(payload)

    assert parsed.delta_converged is False
    assert parsed.delta_nfev == 2
    assert parsed.converged_by_version == {"v5.0": False}
    assert parsed.nfev_by_version == {"v5.0": 59}
    assert parsed.fit_status == calib.FIT_STATUS_NOT_CONVERGED
    assert parsed.emos_params_by_version == {"v5.0": (0.5, 0.1)}


def test_artefact_from_json_dict_defaults_informational_fields_for_a_pre_schema_payload() -> None:
    """An artefact written BEFORE this schema change carries none of the
    new keys -- the parser must default the four purely INFORMATIONAL
    fields exactly like the dataclass itself ("assume converged"), never
    raise KeyError. ``fit_status`` itself is NOT given that treatment (SL-8b2
    review, next test) -- it is the gate-blocking field."""
    payload = {
        "schema_version": 1,
        "cdf_method": "normal",
        "recalibration": "none",
        "correction_form": "none",
        "delta": 1.0,
        "kappa": "inf",
        "emos_params_by_version": {"v5.0": [0.5, 0.1]},
        "emos_draws_by_version": {"v5.0": [[0.4, 0.08], [0.6, 0.12]]},  # pre-review-item-3 2-tuple shape
        "n_min": 412,
        "sigma_d": 0.11,
        "rung_probability_bounds": {},
    }

    parsed = calib.artefact_from_json_dict(payload)

    assert parsed.delta_converged is True
    assert parsed.delta_nfev == 0
    assert parsed.converged_by_version == {}
    assert parsed.nfev_by_version == {}
    assert parsed.kappa == math.inf
    # The pre-review-item-3 2-element draw entries still parse, delta
    # falling back to the artefact's own top-level delta.
    assert parsed.emos_draws_by_version["v5.0"] == ((0.4, 0.08, 1.0), (0.6, 0.12, 1.0))


def test_artefact_from_json_dict_missing_fit_status_parses_unknown_not_ok() -> None:
    """SL-8b2 review: `fit_status` is the single GATE-BLOCKING field --
    unlike the informational convergence fields above, a payload missing it
    parses to UNKNOWN, never falls back to OK ("assume converged"). There
    are no production artefacts predating this schema to stay compatible
    with (the fix-first review's own finding)."""
    payload = {
        "schema_version": 1,
        "cdf_method": "normal",
        "recalibration": "none",
        "correction_form": "none",
        "delta": 1.0,
        "kappa": 1.0,
        "emos_params_by_version": {"v5.0": [0.5, 0.1]},
        "emos_draws_by_version": {"v5.0": [[0.4, 0.08, 1.0]]},
        "n_min": 412,
        "sigma_d": 0.11,
        "rung_probability_bounds": {},
    }

    parsed = calib.artefact_from_json_dict(payload)

    assert parsed.fit_status == calib.FIT_STATUS_UNKNOWN
    assert parsed.fit_status != calib.FIT_STATUS_OK


# ---------------------------------------------------------------------------
# SL-8b review item 2: convergence is inspected, logged, and flagged --
# never silently accepted.
# ---------------------------------------------------------------------------


def test_fit_version_unshrunk_flags_nonconvergence_when_forced(caplog: pytest.LogCaptureFixture) -> None:
    rows = [
        _version_row("v4.3", "validate", dt.date(2025, 6, 1), "KMIA", 90.0, 3.0, 90.0),
        _version_row("v4.3", "validate", dt.date(2025, 6, 2), "KMIA", 90.0, 3.0, 92.0),
        _version_row("v4.3", "validate", dt.date(2025, 6, 3), "KMIA", 90.0, 3.0, 88.0),
    ]
    with caplog.at_level("WARNING", logger="breezy.analysis.nbp_calibration"):
        estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0, max_iterations=1)

    assert estimate.converged is False
    assert estimate.nfev >= 1
    assert any("did not converge" in record.message for record in caplog.records)


def test_fit_version_unshrunk_converges_under_the_default_iteration_ceiling() -> None:
    rows = [
        _version_row("v4.3", "validate", dt.date(2025, 6, 1), "KMIA", 90.0, 3.0, 90.0),
        _version_row("v4.3", "validate", dt.date(2025, 6, 2), "KMIA", 90.0, 3.0, 92.0),
        _version_row("v4.3", "validate", dt.date(2025, 6, 3), "KMIA", 90.0, 3.0, 88.0),
    ]
    estimate = calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=1.0)
    assert estimate.converged is True
    assert estimate.nfev > 0


def test_fit_shared_delta_with_diagnostics_flags_nonconvergence_when_forced(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows_by_version = _synthetic_rows_by_version(n_per_version=3, split="train")
    with caplog.at_level("WARNING", logger="breezy.analysis.nbp_calibration"):
        diagnostics = calib.fit_shared_delta_with_diagnostics(
            rows_by_version, method=CdfMethod.NORMAL, bracket=(0.2, 2.0), max_iterations=1
        )

    assert diagnostics.converged is False
    assert diagnostics.nfev >= 1
    assert any("did not converge" in record.message for record in caplog.records)


def test_fit_shared_delta_with_diagnostics_converges_under_default_settings() -> None:
    rows_by_version = _synthetic_rows_by_version(n_per_version=3, split="train")
    diagnostics = calib.fit_shared_delta_with_diagnostics(
        rows_by_version, method=CdfMethod.NORMAL, bracket=(0.2, 2.0)
    )
    assert diagnostics.converged is True
    assert diagnostics.delta == pytest.approx(
        calib.fit_shared_delta(rows_by_version, method=CdfMethod.NORMAL, bracket=(0.2, 2.0))
    )


def test_shrink_toward_lovo_pooled_mean_carries_the_targets_convergence_through() -> None:
    target = calib.VersionEstimate(version="v5.0", a=3.0, gamma=0.5, n=50, converged=False, nfev=1)
    others = [calib.VersionEstimate(version="v4.3", a=0.0, gamma=0.0, n=200)]
    shrunk = calib.shrink_toward_lovo_pooled_mean(target, others, kappa=0.0)
    assert shrunk.converged is False
    assert shrunk.nfev == 1


# ---------------------------------------------------------------------------
# SL-8b review item 3: delta is resampled inside the bootstrap -- each draw
# carries its OWN refit delta, and the resulting interval never narrows
# relative to the old fixed-delta convention.
# ---------------------------------------------------------------------------


def _skewed_bootstrap_rows() -> list[calib.VersionRow]:
    # A deliberately non-trivial residual pattern across station-days, so
    # different cluster resamples fit genuinely different deltas.
    clis = (90.0, 91.5, 88.0, 93.0, 89.0, 94.0, 87.5, 90.5)
    return [
        _version_row("v5.0", "validate", dt.date(2025, 1, 1) + dt.timedelta(days=i), "KMIA", 90.0, 3.0, cli)
        for i, cli in enumerate(clis)
    ]


def test_bootstrap_draws_now_carry_a_per_draw_delta_that_is_not_all_identical() -> None:
    rows = _skewed_bootstrap_rows()
    shared_delta = 1.0
    shrunk_by_version = {
        "v5.0": calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=shared_delta),
    }
    draws = calib.bootstrap_emos_draws(
        {"v5.0": rows},
        shrunk_by_version,
        method=CdfMethod.NORMAL,
        delta=shared_delta,
        draws=8,
        resample_delta=True,
    )
    deltas = {draw.delta for draw in draws["v5.0"].draws}
    # At least one resampled draw disagrees with the shared point delta --
    # resampling is actually happening, not silently collapsing back to it.
    assert deltas != {shared_delta}


def test_resampled_delta_interval_never_narrows_relative_to_fixed_delta() -> None:
    rows = _skewed_bootstrap_rows()
    shared_delta = 1.0
    shrunk_by_version = {
        "v5.0": calib.fit_version_unshrunk(rows, method=CdfMethod.NORMAL, delta=shared_delta),
    }
    percentiles = _percentiles(90.0, sd=3.0)
    rungs = (Rung("lt_90", None, 89), Rung("90_93", 90, 93), Rung("gt_93", 94, None))

    fixed_draws = calib.bootstrap_emos_draws(
        {"v5.0": rows},
        shrunk_by_version,
        method=CdfMethod.NORMAL,
        delta=shared_delta,
        draws=12,
        resample_delta=False,
    )["v5.0"].draws
    resampled_draws = calib.bootstrap_emos_draws(
        {"v5.0": rows},
        shrunk_by_version,
        method=CdfMethod.NORMAL,
        delta=shared_delta,
        draws=12,
        resample_delta=True,
    )["v5.0"].draws

    fixed_bounds = calib.rung_bounds_from_calibration(percentiles, CdfMethod.NORMAL, fixed_draws, rungs)
    resampled_bounds = calib.rung_bounds_from_calibration(
        percentiles, CdfMethod.NORMAL, resampled_draws, rungs
    )
    # A per-rung comparison, not an exact one: independent re-fits (each
    # draw's own fit_shared_delta bracket search) carry ordinary
    # float/optimizer noise on the order of 1e-5 relative, which is not
    # "narrower" in any meaningful sense -- the total width across every
    # rung is the robust statistic review item 3 actually cares about.
    fixed_total_width = sum(upper - lower for _, lower, upper in fixed_bounds.values())
    resampled_total_width = sum(upper - lower for _, lower, upper in resampled_bounds.values())
    assert resampled_total_width >= fixed_total_width - 1e-3, (fixed_total_width, resampled_total_width)


def test_emos_params_from_draw_entry_prefers_its_own_delta() -> None:
    params = calib.emos_params_from_draw_entry([0.3, 0.1, 1.4], fallback_delta=1.0)
    assert params == EmosParams(a=0.3, gamma=0.1, delta=1.4)


def test_emos_params_from_draw_entry_falls_back_to_the_artefact_delta_for_the_old_2_element_shape() -> None:
    params = calib.emos_params_from_draw_entry([0.3, 0.1], fallback_delta=1.4)
    assert params == EmosParams(a=0.3, gamma=0.1, delta=1.4)


def test_emos_params_from_draw_entry_refuses_an_unexpected_length() -> None:
    with pytest.raises(ValueError, match="2 or 3 elements"):
        calib.emos_params_from_draw_entry([0.3], fallback_delta=1.0)


# ---------------------------------------------------------------------------
# SL-8b review item 4: p_point consistency -- the probability a G2.2/G2.3
# scorer uses for one event equals the artefact's p_point for the same
# inputs, because both are the mean over the same draws.
# ---------------------------------------------------------------------------


def test_p_point_equals_the_manual_mean_over_draws_a_scorer_would_compute() -> None:
    percentiles = _percentiles(90.0, sd=3.0)
    rungs = (Rung("lt_90", None, 89), Rung("90_93", 90, 93), Rung("gt_93", 94, None))
    draws = (
        EmosParams(a=0.2, gamma=0.05, delta=1.0),
        EmosParams(a=0.4, gamma=0.10, delta=1.1),
        EmosParams(a=-0.1, gamma=-0.05, delta=0.9),
        EmosParams(a=0.6, gamma=0.15, delta=1.2),
    )

    bounds = calib.rung_bounds_from_calibration(percentiles, CdfMethod.NORMAL, draws, rungs)

    # Reconstruct what a G2.2/G2.3 scorer would compute for ONE event's
    # p_m2 from PUBLIC building blocks only: the base CDF, apply_emos under
    # each draw, and rung_probabilities -- never reaching into
    # rung_bounds_from_calibration's own internals.
    base_cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    from breezy.strategy.ladder_ev.quantile_density import rung_probabilities

    for rung_id in ("lt_90", "90_93", "gt_93"):
        per_draw = [
            rung_probabilities(apply_emos(base_cdf, percentiles, draw), rungs)[rung_id] for draw in draws
        ]
        manual_p_point = sum(per_draw) / len(per_draw)
        artefact_p_point = bounds[rung_id][0]
        assert manual_p_point == pytest.approx(artefact_p_point, abs=1e-12)


# ---------------------------------------------------------------------------
# SL-8c: M0 (closed model, frozen 0b) + M1 comparators + G2.0a near-midnight
# feature (plan S2.2, S3.2 item 7, S4.1 G2.0a).
# ---------------------------------------------------------------------------

# The relpath is declared in `scripts/analysis/nbp_skill_study.py`, the
# caller allowed to name `docs/evidence/` (src/ is not -- see
# `tests/unit/test_probe_containment.py::test_no_module_under_src_reads_docs_evidence`).
# `load_frozen_0b_error_model` itself only ever takes an explicit path.
_FROZEN_0B_PATH = _REPO_ROOT / "docs/evidence/FC_0b_FROZEN_ERROR_MODEL_2026-09-19.json"


def test_frozen_0b_artefact_is_committed_at_the_declared_path() -> None:
    assert _FROZEN_0B_PATH.is_file()


def test_load_frozen_0b_error_model_is_byte_equal_to_the_committed_json() -> None:
    """The loader must reproduce the committed JSON's tables exactly -- never
    refit, never round, never drop a key."""
    raw = json.loads(_FROZEN_0B_PATH.read_text(encoding="utf-8"))

    model = comparator.load_frozen_0b_error_model(_FROZEN_0B_PATH)

    assert model.bias_by_key == raw["bias_by_key"]
    assert model.sigma_by_key == raw["sigma_by_key"]
    assert model.sample_size_by_key == raw["sample_size_by_key"]
    assert model.distribution == raw["distribution"]
    assert model.min_samples_for_local == raw["min_samples_for_local"]
    assert model.continuity_correction_f == raw["continuity_correction_f"]
    # The frozen fit's own declared TRAIN n (WP-6, n=5808) is the "*" catch-all
    # sample count -- pinning both together catches a corrupted or truncated
    # artefact, not just a malformed one.
    assert model.sample_size_by_key["*"] == comparator.M0_FROZEN_TRAIN_STATION_DAYS


def test_load_frozen_0b_error_model_raises_on_a_missing_required_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad_frozen_0b.json"
    bad.write_text(json.dumps({"bias_by_key": {}, "distribution": "gaussian"}))
    with pytest.raises(comparator.Frozen0bArtefactError):
        comparator.load_frozen_0b_error_model(bad)


def test_load_frozen_0b_error_model_raises_on_unparseable_json(tmp_path: Path) -> None:
    bad = tmp_path / "not_json.json"
    bad.write_text("not json at all")
    with pytest.raises(comparator.Frozen0bArtefactError):
        comparator.load_frozen_0b_error_model(bad)


def test_m0_reproduces_a_known_value_from_the_committed_frozen_09_20_corpus() -> None:
    """Positive control (plan task 1): the frozen artefact's own KMIA/August
    bias+sigma, applied by hand, must match `m0_rung_probabilities` exactly."""
    model = comparator.load_frozen_0b_error_model(_FROZEN_0B_PATH)
    txn_f = 90.0
    station = "KMIA"
    climate_day = dt.date(2023, 8, 15)
    horizon_hours = comparator.M0_PRIMARY_LEAD_HOURS

    # Hand-computed from the committed artefact's KMIA|8|24 bucket (bias
    # 0.20161290322580644, sigma 1.268632441529883 -- read directly off
    # docs/evidence/FC_0b_FROZEN_ERROR_MODEL_2026-09-19.json).
    bias = model.bias_by_key["KMIA|8|24"]
    sigma = model.sigma_by_key["KMIA|8|24"]
    assert model.bias(station, climate_day, horizon_hours) == pytest.approx(bias)
    assert model.sigma(station, climate_day, horizon_hours) == pytest.approx(sigma)

    mu = txn_f + bias
    expected = {
        "lt90": 0.5 * (1.0 + math.erf((89.5 - mu) / (sigma * math.sqrt(2.0)))),
        "90_91": (
            0.5 * (1.0 + math.erf((91.5 - mu) / (sigma * math.sqrt(2.0))))
            - 0.5 * (1.0 + math.erf((89.5 - mu) / (sigma * math.sqrt(2.0))))
        ),
    }
    expected["gt91"] = 1.0 - expected["lt90"] - expected["90_91"]

    rungs = (Rung("lt90", None, 89), Rung("90_91", 90, 91), Rung("gt91", 92, None))
    probabilities = comparator.m0_rung_probabilities(
        txn_f=txn_f,
        station=station,
        climate_day=climate_day,
        horizon_hours=horizon_hours,
        error_model=model,
        rungs=rungs,
    )

    assert probabilities["lt90"] == pytest.approx(expected["lt90"], abs=1e-12)
    assert probabilities["90_91"] == pytest.approx(expected["90_91"], abs=1e-12)
    assert probabilities["gt91"] == pytest.approx(expected["gt91"], abs=1e-12)
    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-9)


def test_m0_never_mutates_the_frozen_model_across_repeated_calls() -> None:
    """Calling m0 twice must not mutate the shared `ForecastErrorModel`."""
    model = comparator.load_frozen_0b_error_model(_FROZEN_0B_PATH)
    before_bias = dict(model.bias_by_key)
    before_sigma = dict(model.sigma_by_key)
    rungs = (Rung("lt90", None, 89), Rung("gte90", 90, None))

    comparator.m0_rung_probabilities(
        txn_f=88.0,
        station="KSFO",
        climate_day=dt.date(2022, 3, 1),
        horizon_hours=comparator.M0_PRIMARY_LEAD_HOURS,
        error_model=model,
        rungs=rungs,
    )

    assert model.bias_by_key == before_bias
    assert model.sigma_by_key == before_sigma


def test_m1_rung_partition_sums_to_1() -> None:
    rungs = (
        Rung("lt80", None, 79),
        Rung("80_81", 80, 81),
        Rung("82_83", 82, 83),
        Rung("gte84", 84, None),
    )
    probabilities = comparator.m1_rung_probabilities(txn_mean_f=81.5, xnd_sd_f=2.4, rungs=rungs)
    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= p <= 1.0 for p in probabilities.values())


def test_m1_uses_no_bias_correction_unlike_m0() -> None:
    """M1 is the zero-plumbing baseline (plan S2.2): the mean IS the TXN
    mean, with no bias term applied on top."""
    rungs = (Rung("lt90", None, 89), Rung("gte90", 90, None))
    probabilities = comparator.m1_rung_probabilities(txn_mean_f=90.0, xnd_sd_f=2.0, rungs=rungs)
    # At the mean exactly, the continuity-adjusted split around 89.5 puts
    # slightly more than half the mass above 90 -- a fixed, hand-verifiable
    # value independent of any bias/sigma fit.
    expected_below = 0.5 * (1.0 + math.erf((89.5 - 90.0) / (2.0 * math.sqrt(2.0))))
    assert probabilities["lt90"] == pytest.approx(expected_below, abs=1e-12)


def test_m1_refuses_a_non_positive_sd() -> None:
    rungs = (Rung("lt90", None, 89), Rung("gte90", 90, None))
    with pytest.raises(ValueError):
        comparator.m1_rung_probabilities(txn_mean_f=90.0, xnd_sd_f=0.0, rungs=rungs)


# ---------------------------------------------------------------------------
# G2.0a: near-midnight LST instant (plan S4.1; hand-computed for KMIA
# UTC-5 and KLAX UTC-8).
# ---------------------------------------------------------------------------


def test_near_midnight_flag_hand_computed_for_kmia_utc_minus_5() -> None:
    # 04:30Z -> LST 23:30 (previous LST day) -- 30 min before midnight: near.
    day, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 4, 30, tzinfo=dt.UTC), std_utc_offset_hours=-5.0
    )
    assert day == dt.date(2025, 6, 1)
    assert seconds == 23 * 3600 + 30 * 60
    assert comparator.is_near_lst_midnight(seconds) is True

    # 06:30Z -> LST 01:30 -- 90 min after midnight: near.
    _, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 6, 30, tzinfo=dt.UTC), std_utc_offset_hours=-5.0
    )
    assert seconds == 1 * 3600 + 30 * 60
    assert comparator.is_near_lst_midnight(seconds) is True

    # 12:00Z -> LST 07:00 -- 7h after midnight: not near.
    _, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 12, 0, tzinfo=dt.UTC), std_utc_offset_hours=-5.0
    )
    assert seconds == 7 * 3600
    assert comparator.is_near_lst_midnight(seconds) is False


def test_near_midnight_flag_hand_computed_for_klax_utc_minus_8() -> None:
    # 07:30Z -> LST 23:30 (previous LST day): near.
    day, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 7, 30, tzinfo=dt.UTC), std_utc_offset_hours=-8.0
    )
    assert day == dt.date(2025, 6, 1)
    assert seconds == 23 * 3600 + 30 * 60
    assert comparator.is_near_lst_midnight(seconds) is True

    # 09:30Z -> LST 01:30: near.
    _, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 9, 30, tzinfo=dt.UTC), std_utc_offset_hours=-8.0
    )
    assert seconds == 1 * 3600 + 30 * 60
    assert comparator.is_near_lst_midnight(seconds) is True

    # 15:00Z -> LST 07:00: not near.
    _, seconds = comparator.lst_clock_time(
        dt.datetime(2025, 6, 2, 15, 0, tzinfo=dt.UTC), std_utc_offset_hours=-8.0
    )
    assert seconds == 7 * 3600
    assert comparator.is_near_lst_midnight(seconds) is False


def test_is_near_lst_midnight_refuses_an_out_of_range_value() -> None:
    with pytest.raises(ValueError):
        comparator.is_near_lst_midnight(86_400)
    with pytest.raises(ValueError):
        comparator.is_near_lst_midnight(-1)


def test_daily_max_instant_from_samples_breaks_ties_to_the_first_occurrence() -> None:
    # Two samples share the max value; the earlier LST instant wins.
    samples = [(3600, 90.0), (7200, 90.0), (1800, 88.0)]
    instant = comparator.daily_max_instant_from_samples(
        samples, station="KMIA", climate_day=dt.date(2025, 6, 1)
    )
    assert instant is not None
    assert instant.lst_seconds_from_midnight == 3600
    assert instant.value_f == pytest.approx(90.0)


def test_daily_max_instant_from_samples_is_missing_not_imputed_for_a_gap() -> None:
    instant = comparator.daily_max_instant_from_samples(
        [], station="KMIA", climate_day=dt.date(2025, 6, 1)
    )
    assert instant is None


# ---------------------------------------------------------------------------
# target_climate_day: D+1 keyed on the cycle's OWN publish instant, never on
# "the nearest window" (coordinator directive, 2026-09-29).
# ---------------------------------------------------------------------------

_NS: int = 10**9


def _ns(instant: dt.datetime) -> int:
    return int(instant.timestamp()) * _NS


def test_target_climate_day_pins_d_plus_1_for_a_01z_cycle_at_kmia() -> None:
    # KMIA, UTC-5 (EST, standard -- never DST-aware). 01:00Z on 2025-06-02 is
    # 20:00 local standard on 2025-06-01 -- local_standard_date == 2025-06-01
    # -- so the D+1 target climate day is 2025-06-02.
    cycle_publish_ns = _ns(dt.datetime(2025, 6, 2, 1, 0, tzinfo=dt.UTC))
    assert comparator.target_climate_day(cycle_publish_ns, -5.0) == dt.date(2025, 6, 2)


def test_target_climate_day_pins_d_plus_1_for_a_13z_cycle_at_klax() -> None:
    # KLAX, UTC-8 (PST, standard). 13:00Z on 2025-06-02 is 05:00 local
    # standard on 2025-06-02 -- local_standard_date == 2025-06-02 -- so the
    # D+1 target climate day is 2025-06-03.
    cycle_publish_ns = _ns(dt.datetime(2025, 6, 2, 13, 0, tzinfo=dt.UTC))
    assert comparator.target_climate_day(cycle_publish_ns, -8.0) == dt.date(2025, 6, 3)
