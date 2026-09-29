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
import math
from pathlib import Path

import pytest

from breezy.analysis import nbp_calibration as calib
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
)

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
            "v5.0": ((0.4, 0.08), (0.5, 0.1), (0.6, 0.12)),
            "v4.3": ((-0.1, 0.0), (0.0, 0.0), (0.1, 0.0)),
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
    assert '"v5.0":[[0.4,0.08],[0.5,0.1],[0.6,0.12]]' in payload


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


def dataclasses_replace(instance: calib.MatchedEvent, **changes: object) -> calib.MatchedEvent:
    return dataclasses.replace(instance, **changes)  # type: ignore[arg-type]
