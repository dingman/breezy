"""RED-first tests for `breezy.analysis.multisource_blend` (F13 Phase A / A1).

Plan: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md, section
"Phase A1 / A", with the r3.1 / r3.2 amendments and ruling F13-R35 (LAMP remaining-hours
feature). Every fixture is synthetic: no archive, catalogue, network or sealed day is read.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import hashlib
import math
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from breezy.analysis import nbp_calibration as calib
from breezy.strategy.ladder_ev.quantile_density import Percentiles

REPO_ROOT = Path(__file__).resolve().parents[2]
_NS = 1_000_000_000
_HOUR_NS = 3600 * _NS
_OFFSET = -5.0  # NYC local standard time
_NBP_MODULE = REPO_ROOT / "src" / "breezy" / "analysis" / "nbp_calibration.py"
#: sha256 of src/breezy/analysis/nbp_calibration.py at the F13 Phase A start (HEAD 6d1eb4f3).
_NBP_MODULE_SHA256 = "e126e1b49217467cbef0c4c767a48e8ae8a317e4f7abd2ca733ed4cbed7033a0"


# ------------------------------------------------------------------ helpers


def _lst_midnight_ns(day: dt.date) -> int:
    """UTC instant of local-standard midnight starting ``day`` for UTC-5."""
    utc = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) + dt.timedelta(hours=-_OFFSET)
    return int(utc.timestamp()) * _NS


def _lst_ns(day: dt.date, hour: float) -> int:
    return _lst_midnight_ns(day) + int(hour * _HOUR_NS)


def _pct(q50: float, sd: float) -> Percentiles:
    return Percentiles(
        q10=q50 - 1.2816 * sd,
        q25=q50 - 0.6745 * sd,
        q50=q50,
        q75=q50 + 0.6745 * sd,
        q90=q50 + 1.2816 * sd,
        mean=q50,
        sd=sd,
    )


def _lamp_hours(
    day: dt.date, first_lst: float, n: int, temp: float = 70.0
) -> tuple[msb.LampHour, ...]:
    """``n`` hourly instants starting at LST hour ``first_lst`` of ``day`` (may exceed 24)."""
    return tuple(
        msb.LampHour(valid_ts_ns=_lst_ns(day, first_lst + i), tmp_f=temp) for i in range(n)
    )


def _lamp_feature(rem: float | None, *, anchor_ns: int) -> msb.LampFeature:
    if rem is None:
        return msb.MISSING_LAMP
    return msb.LampFeature(
        rem_max_f=rem,
        hours_covered=10,
        peak_covered=True,
        missing=False,
        run_available_at_ns=anchor_ns - _HOUR_NS,
        min_valid_ts_ns=anchor_ns + _HOUR_NS,
        strict_24h_max_f_diagnostic=None,
    )


def _row(
    *,
    station: str,
    day: dt.date,
    version: str,
    horizon: str,
    y: float,
    nbp: float,
    sd: float,
    obs: float | None,
    lamp: float | None,
    pfm: float | None,
    mos: float | None,
) -> msb.FeatureRow:
    anchor = _lst_ns(day, 9.0) if horizon == "D0" else _lst_ns(day - dt.timedelta(days=1), 15.0)
    return msb.FeatureRow(
        station=station,
        climate_day=day,
        version=version,
        horizon=horizon,
        anchor_ns=anchor,
        percentiles=_pct(nbp, sd),
        cli_tmax_f=y,
        obs_so_far_f=obs,
        obs_available_at_ns=None if obs is None else anchor - _HOUR_NS,
        lamp=_lamp_feature(lamp, anchor_ns=anchor),
        pfm_mu_f=pfm,
        pfm_available_at_ns=None if pfm is None else anchor - _HOUR_NS,
        mos_mu_f=mos,
        mos_available_at_ns=None if mos is None else anchor - _HOUR_NS,
    )


def make_rows(
    *,
    days: int,
    start: dt.date = dt.date(2023, 1, 1),
    version: str = "v4.1",
    stations: Sequence[str] = ("NYC", "LAX"),
    horizons: Sequence[str] = ("D-1", "D0"),
    seed: int = 7,
    informative: bool = True,
) -> list[msb.FeatureRow]:
    """Truth = climatology + shock. NBP is noisy; other sources are sharper if ``informative``."""
    rng = random.Random(seed)
    rows: list[msb.FeatureRow] = []
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        for station in stations:
            clim = 60.0 + 12.0 * math.sin(offset / 20.0) + (5.0 if station == "LAX" else 0.0)
            shock = rng.gauss(0.0, 4.0)
            y = clim + shock
            for horizon in horizons:
                nbp = y + rng.gauss(0.0, 2.5)
                if informative:
                    lamp = y + rng.gauss(0.0, 0.8)
                    pfm = y + rng.gauss(0.0, 1.5)
                    mos = y + rng.gauss(0.0, 1.5)
                else:
                    lamp = nbp + rng.gauss(0.0, 0.8)
                    pfm = nbp + rng.gauss(0.0, 1.5)
                    mos = nbp + rng.gauss(0.0, 1.5)
                obs = (y - abs(rng.gauss(0.0, 2.0))) if horizon == "D0" else None
                rows.append(
                    _row(
                        station=station,
                        day=day,
                        version=version,
                        horizon=horizon,
                        y=y,
                        nbp=nbp,
                        sd=2.5,
                        obs=obs,
                        lamp=lamp,
                        pfm=pfm,
                        mos=mos,
                    )
                )
    return rows


def two_version_rows(*, seed: int, days: int = 84) -> list[msb.FeatureRow]:
    """Two consecutive NBM versions on validate-split dates (the champion needs two)."""
    first = make_rows(
        days=days,
        start=dt.date(2025, 1, 1),
        version="v4.2",
        stations=("NYC", "LAX"),
        horizons=("D-1",),
        seed=seed,
    )
    second = make_rows(
        days=days,
        start=dt.date(2025, 1, 1) + dt.timedelta(days=days),
        version="v4.3",
        stations=("NYC", "LAX"),
        horizons=("D-1",),
        seed=seed + 1,
    )
    return [*first, *second]


def _settings(**overrides: object) -> msb.BlendSettings:
    base: dict[str, object] = {
        "nu": 6.0,
        "sigma_floor_f": 0.5,
        "weight_sum_lambda": 1.0,
        "min_cell_rows": 20,
    }
    base.update(overrides)
    return msb.BlendSettings(**base)  # type: ignore[arg-type]


_BOOT = 3  # tiny champion bootstrap: these tests check wiring, not the champion's statistics


# ------------------------------------------------------------------ module pins


def test_nbp_calibration_module_is_byte_unchanged() -> None:
    digest = hashlib.sha256(_NBP_MODULE.read_bytes()).hexdigest()
    assert digest == _NBP_MODULE_SHA256, (
        "src/breezy/analysis/nbp_calibration.py is the champion: it must stay byte-unchanged "
        "by F13 Phase A (plan: M0 = fit_calibration, untouched)"
    )


def test_open_holdout_is_never_called(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("open_holdout must never be called by Phase A")

    monkeypatch.setattr(calib, "open_holdout", _boom)
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",))
    plan = msb.build_folds(
        msb.days_by_version(rows), source_breaks=(), block_days=14, min_train_days=14
    )
    msb.out_of_fold_scores(
        rows, plan, _settings(), levels=(0, 1), champion=False, m0_bootstrap_draws=_BOOT
    )
    for rel in (
        "src/breezy/analysis/multisource_blend.py",
        "scripts/analysis/multisource_blend_skill.py",
        "scripts/analysis/blend_veto_descriptive.py",
    ):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        aliased = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert "open_holdout" not in names | attrs | aliased, rel


def test_no_row_on_or_after_2026_07_01_reaches_the_fit_or_score() -> None:
    assert msb.HOLDOUT_START == calib.DEFAULT_SPLITS.holdout_start == dt.date(2026, 7, 1)
    ok = make_rows(days=40, start=dt.date(2026, 5, 1), stations=("NYC",), horizons=("D-1",))
    bad = [*ok, *make_rows(days=1, start=dt.date(2026, 7, 1), stations=("NYC",), horizons=("D-1",))]
    last_ok = max(r.climate_day for r in ok)
    assert last_ok < dt.date(2026, 7, 1)
    with pytest.raises(msb.HoldoutLeakError):
        msb.fit_blend(bad, level=0, settings=_settings())
    fit = msb.fit_blend(ok, level=0, settings=_settings())
    with pytest.raises(msb.HoldoutLeakError):
        msb.score_rows(fit, bad)
    with pytest.raises(msb.HoldoutLeakError):
        msb.build_folds(msb.days_by_version(bad), source_breaks=())
    plan = msb.build_folds(
        msb.days_by_version(ok), source_breaks=(), block_days=14, min_train_days=14
    )
    with pytest.raises(msb.HoldoutLeakError):
        msb.out_of_fold_scores(bad, plan, _settings(), levels=(0,), champion=False)
    # the boundary day itself: 2026-06-30 is the last admissible climate day
    boundary = make_rows(days=1, start=dt.date(2026, 6, 30), stations=("NYC",), horizons=("D-1",))
    msb.assert_pre_holdout(boundary)


# ------------------------------------------------------------------ distribution


def test_blend_uses_crps_numerical_with_blend_mu_as_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = make_rows(days=40, stations=("NYC",), horizons=("D-1",))
    fit = msb.fit_blend(rows, level=3, settings=_settings())
    seen: list[float] = []
    real = calib.crps_numerical

    def _spy(cdf: Any, observed: float, *, center: float, **kwargs: Any) -> float:
        seen.append(center)
        return real(cdf, observed, center=center, **kwargs)

    monkeypatch.setattr("breezy.analysis.multisource_blend.crps_numerical", _spy)
    row = rows[0]
    value = msb.row_crps(fit, row)
    mu, _sigma, _level = msb.predict_row(fit, row)
    assert seen == [mu]
    assert value > 0.0


def test_blend_identical_sigma_treatment_across_primary_arms() -> None:
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",))
    settings = _settings()
    arms = {level: msb.fit_blend(rows, level=level, settings=settings) for level in (0, 3)}
    assert arms[0].settings == arms[3].settings
    row = rows[5]
    for fit in arms.values():
        for cell in fit.cells.values():
            assert cell.e is None
        _mu, sigma, level = msb.predict_row(fit, row)
        cell = fit.cells[(level, False)]
        expected = max(math.exp(cell.c + cell.d * math.log(row.percentiles.sd)), 0.5)
        assert sigma == pytest.approx(expected)


def test_blend_student_t_log_sigma_includes_source_disagreement_only_in_separate_step() -> None:
    rows = make_rows(days=80, stations=("NYC",), horizons=("D-1",))
    primary = msb.fit_blend(rows, level=3, settings=_settings())
    separate = msb.fit_blend(rows, level=3, settings=_settings(use_disagreement_sigma=True))
    assert all(cell.e is None for cell in primary.cells.values())
    deep = separate.cells[(3, False)]
    assert deep.e is not None
    # the primary arm's sigma never moves when only a source's value moves
    row = rows[3]
    moved = dataclasses.replace(row, pfm_mu_f=(row.pfm_mu_f or 0.0) + 6.0)
    assert msb.predict_row(primary, row)[1] == msb.predict_row(primary, moved)[1]
    # the separate step is exactly the documented formula
    sigma = msb.predict_row(separate, moved)[1]
    dis = msb.source_disagreement_f(moved, level=3)
    expected = max(
        math.exp(deep.c + deep.d * math.log(moved.percentiles.sd) + deep.e * math.log(dis)), 0.5
    )
    assert sigma == pytest.approx(expected)
    # level 0 has no sources to disagree: the step is a no-op there
    assert (
        msb.fit_blend(rows, level=0, settings=_settings(use_disagreement_sigma=True))
        .cells[(0, False)]
        .e
        is None
    )


def test_blend_sigma_floor_prevents_overconfidence() -> None:
    rng = random.Random(3)
    rows = []
    for offset in range(60):
        day = dt.date(2023, 1, 1) + dt.timedelta(days=offset)
        y = 60.0 + rng.gauss(0.0, 3.0)
        rows.append(
            _row(
                station="NYC",
                day=day,
                version="v4.1",
                horizon="D-1",
                y=y,
                nbp=y,
                sd=0.01,
                obs=None,
                lamp=None,
                pfm=None,
                mos=None,
            )
        )
    fit = msb.fit_blend(rows, level=0, settings=_settings(sigma_floor_f=0.7))
    sigmas = [msb.predict_row(fit, row)[1] for row in rows]
    assert min(sigmas) >= 0.7 - 1e-12
    assert min(sigmas) == pytest.approx(0.7)


def test_blend_weight_sum_shrinks_toward_one_not_hard_box() -> None:
    rng = random.Random(11)
    rows = []
    for offset in range(120):
        day = dt.date(2023, 1, 1) + dt.timedelta(days=offset)
        x = 55.0 + rng.gauss(0.0, 8.0)
        y = 1.25 * x - 17.0 + rng.gauss(0.0, 1.0)  # true weight sum 1.25
        rows.append(
            _row(
                station="NYC",
                day=day,
                version="v4.1",
                horizon="D-1",
                y=y,
                nbp=x,
                sd=1.0 + rng.random(),
                obs=None,
                lamp=None,
                pfm=None,
                mos=None,
            )
        )

    def total(lam: float) -> float:
        fit = msb.fit_blend(rows, level=0, settings=_settings(weight_sum_lambda=lam))
        return sum(fit.cells[(0, False)].w)

    free, shrunk, pinned = total(0.0), total(30.0), total(1.0e6)
    assert free == pytest.approx(1.25, abs=0.08)
    assert abs(pinned - 1.0) < abs(shrunk - 1.0) < abs(free - 1.0)
    assert abs(shrunk - 1.0) > 1e-3  # a shrinkage penalty, not a hard sum-to-one box
    assert abs(pinned - 1.0) < 0.02


def test_blend_nonfinite_input_refused_not_imputed() -> None:
    good = make_rows(days=1, stations=("NYC",), horizons=("D-1",))[0]
    for change in (
        {"pfm_mu_f": float("nan")},
        {"mos_mu_f": float("inf")},
        {"obs_so_far_f": float("-inf")},
        {"cli_tmax_f": float("nan")},
        {"percentiles": _pct(float("nan"), 2.0)},
        {"percentiles": _pct(60.0, 0.0)},
    ):
        with pytest.raises(msb.NonFiniteInputError):
            dataclasses.replace(good, **change)
    with pytest.raises(msb.NonFiniteInputError):
        dataclasses.replace(good, lamp=dataclasses.replace(good.lamp, rem_max_f=float("nan")))


# ------------------------------------------------------------------ R35 LAMP feature

_DAY = dt.date(2025, 7, 15)


def test_lamp_rem_max_excludes_hours_at_or_before_anchor() -> None:
    anchor = _lst_ns(_DAY, 14.0)
    # hours 13, 14 are hot decoys at or before the anchor; 15..18 are the real remainder
    hours = (
        msb.LampHour(_lst_ns(_DAY, 13.0), 99.0),
        msb.LampHour(_lst_ns(_DAY, 14.0), 98.0),
        *(msb.LampHour(_lst_ns(_DAY, 15.0 + i), 80.0 + i) for i in range(10)),
    )
    run = msb.LampRun(
        issued_ns=_lst_ns(_DAY, 12.5), available_at_ns=_lst_ns(_DAY, 13.5), hours=hours
    )
    feature = msb.lamp_remaining_feature(
        [run], anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert (
        feature.rem_max_f == 88.0
    )  # hours 15..23 are inside the LST day (hour 24 is not); never 99/98
    assert feature.min_valid_ts_ns is not None and feature.min_valid_ts_ns > anchor
    assert feature.hours_covered == 9  # 15..23 inside the LST day; hour 24 is the next day


def test_lamp_rem_run_available_at_before_anchor_asserted() -> None:
    anchor = _lst_ns(_DAY, 14.0)
    early = msb.LampRun(_lst_ns(_DAY, 8.5), _lst_ns(_DAY, 9.5), _lamp_hours(_DAY, 10.0, 25, 70.0))
    late = msb.LampRun(_lst_ns(_DAY, 13.5), _lst_ns(_DAY, 14.5), _lamp_hours(_DAY, 15.0, 25, 95.0))
    feature = msb.lamp_remaining_feature(
        [early, late], anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert (
        feature.run_available_at_ns == early.available_at_ns
    )  # the later run is not yet available
    assert feature.rem_max_f == 70.0
    with pytest.raises(msb.LeakageError):
        msb.assert_lamp_run_before_anchor(late, anchor)
    msb.assert_lamp_run_before_anchor(early, anchor)
    only_future = msb.lamp_remaining_feature(
        [late], anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert only_future.missing and only_future.rem_max_f is None


def test_lamp_peak_coverage_d0_complete_dm1_requires_ext() -> None:
    # D0 anchor 09:00 LST, run issued 08:30: 25 hourly columns cover LST 10:00 .. next day 10:00
    anchor_d0 = _lst_ns(_DAY, 9.0)
    d0_run = msb.LampRun(_lst_ns(_DAY, 7.5), _lst_ns(_DAY, 8.5), _lamp_hours(_DAY, 9.0, 25, 80.0))
    d0 = msb.lamp_remaining_feature(
        [d0_run], anchor_ns=anchor_d0, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert d0.peak_covered and not d0.missing

    # D-1 anchor 15:00 LST the day before: lavtxt reaches only ~13:30 of D; peak needs lavtxt_ext
    prev = _DAY - dt.timedelta(days=1)
    anchor_dm1 = _lst_ns(prev, 15.0)
    base_hours = _lamp_hours(prev, 13.0, 25, 80.0)  # 13:00 .. next day 13:00
    ext_hours = _lamp_hours(prev, 13.0 + 25, 13, 85.0)  # hours 26..38
    plain = msb.LampRun(_lst_ns(prev, 12.5), _lst_ns(prev, 13.5), base_hours)
    extended = msb.LampRun(_lst_ns(prev, 12.5), _lst_ns(prev, 13.5), (*base_hours, *ext_hours))
    without = msb.lamp_remaining_feature(
        [plain], anchor_ns=anchor_dm1, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    with_ext = msb.lamp_remaining_feature(
        [extended], anchor_ns=anchor_dm1, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert not without.peak_covered and without.missing
    assert with_ext.peak_covered and not with_ext.missing
    assert with_ext.hours_covered > without.hours_covered


def test_lamp_peak_uncovered_sets_missing_indicator_no_imputation() -> None:
    anchor = _lst_ns(_DAY, 9.0)
    gappy = [
        msb.LampHour(_lst_ns(_DAY, 10.0 + i), None if i == 5 else 75.0) for i in range(12)
    ]  # the 15:00 hour is absent
    run = msb.LampRun(_lst_ns(_DAY, 7.5), _lst_ns(_DAY, 8.5), tuple(gappy))
    feature = msb.lamp_remaining_feature(
        [run], anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert feature.missing and not feature.peak_covered
    assert feature.rem_max_f is None  # never filled from neighbouring hours
    assert feature.hours_covered == 11


def test_lamp_peak_window_not_covered_is_missing_not_imputed() -> None:
    anchor = _lst_ns(_DAY, 9.0)
    run = msb.LampRun(_lst_ns(_DAY, 7.5), _lst_ns(_DAY, 8.5), _lamp_hours(_DAY, 10.0, 4, 90.0))
    feature = msb.lamp_remaining_feature(
        [run], anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET
    )
    assert feature.missing and feature.rem_max_f is None
    assert msb.MISSING_LAMP.missing and msb.MISSING_LAMP.rem_max_f is None


def test_combined_feature_is_max_obs_so_far_and_lamp_rem() -> None:
    assert msb.combined_lamp_input(80.0, 78.0) == 80.0
    assert msb.combined_lamp_input(70.0, 78.0) == 78.0
    assert msb.combined_lamp_input(None, 78.0) == 78.0
    assert (
        msb.combined_lamp_input(80.0, None) is None
    )  # LAMP missing: the term drops, obs is not it


def test_dm1_anchor_obs_so_far_undefined_uses_lamp_only() -> None:
    prev = _DAY - dt.timedelta(days=1)
    anchor = _lst_ns(prev, 15.0)
    readings = [
        msb.ObsReading(ts_ns=_lst_ns(prev, 13.0), available_at_ns=_lst_ns(prev, 13.2), temp_f=88.0),
    ]
    assert (
        msb.obs_so_far(readings, anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET)
        is None
    )  # yesterday's readings are not today's max-so-far
    assert msb.combined_lamp_input(None, 77.0) == 77.0


def test_obs_so_far_never_sourced_from_lamp() -> None:
    anchor = _lst_ns(_DAY, 14.0)
    with pytest.raises(msb.LeakageError):
        msb.obs_so_far(
            [msb.ObsReading(_lst_ns(_DAY, 13.0), _lst_ns(_DAY, 13.1), 99.0, source="lamp")],
            anchor_ns=anchor,
            climate_day=_DAY,
            std_utc_offset_hours=_OFFSET,
        )
    readings = [
        msb.ObsReading(_lst_ns(_DAY, 11.0), _lst_ns(_DAY, 11.1), 84.0),
        msb.ObsReading(_lst_ns(_DAY, 13.0), _lst_ns(_DAY, 13.1), 86.0),
        msb.ObsReading(_lst_ns(_DAY, 13.9), _lst_ns(_DAY, 14.5), 99.0),  # arrives after the anchor
    ]
    assert (
        msb.obs_so_far(readings, anchor_ns=anchor, climate_day=_DAY, std_utc_offset_hours=_OFFSET)
        == 86.0
    )
    row = msb.assemble_feature_row(
        station="NYC",
        climate_day=_DAY,
        version="v5.0",
        horizon="D0",
        anchor_ns=anchor,
        std_utc_offset_hours=_OFFSET,
        percentiles=_pct(85.0, 2.0),
        cli_tmax_f=88.0,
        obs_readings=[],
        lamp_runs=[
            msb.LampRun(_lst_ns(_DAY, 12.5), _lst_ns(_DAY, 13.5), _lamp_hours(_DAY, 15.0, 10, 90.0))
        ],
    )
    assert row.obs_so_far_f is None  # LAMP is never promoted into the observed-so-far field
    assert row.lamp_input_f == row.lamp.rem_max_f


def test_missing_lamp_row_scores_as_m0prime() -> None:
    rows = make_rows(days=70, stations=("NYC",), horizons=("D-1",))
    settings = _settings()
    m0p = msb.fit_blend(rows, level=0, settings=settings)
    m1 = msb.fit_blend(rows, level=1, settings=settings)
    row = dataclasses.replace(rows[10], lamp=msb.MISSING_LAMP)
    assert msb.predict_row(m1, row) == msb.predict_row(m0p, row)[:2] + (0,)
    assert msb.row_crps(m1, row) == pytest.approx(msb.row_crps(m0p, row))
    # PFM present but LAMP absent: the nested ladder still falls back to M0'
    m3 = msb.fit_blend(rows, level=3, settings=settings)
    assert msb.predict_row(m3, row)[2] == 0


def test_lamp_missingness_reported_per_horizon() -> None:
    rows = make_rows(days=10, stations=("NYC",), horizons=("D-1", "D0"))
    degraded = [
        dataclasses.replace(r, lamp=msb.MISSING_LAMP)
        if (r.horizon == "D-1" and (i // 2) % 2 == 0)
        else r
        for i, r in enumerate(rows)
    ]
    report = msb.lamp_missingness_by_horizon(degraded)
    assert set(report) == {"D-1", "D0"}
    assert report["D0"].missing == 0
    assert report["D-1"].n == 10 and report["D-1"].missing == 5
    assert report["D-1"].share == pytest.approx(0.5)


def test_strict_24h_max_labelled_diagnostic() -> None:
    assert msb.STRICT_24H_LABEL == "diagnostic_only"
    full = msb.LampRun(
        _lst_ns(_DAY, 0.0) - _HOUR_NS, _lst_ns(_DAY, 0.0), _lamp_hours(_DAY, 0.0, 24, 77.0)
    )
    assert msb.strict_24h_max_diagnostic(full, _DAY, _OFFSET) == 77.0
    short = msb.LampRun(_lst_ns(_DAY, 8.5), _lst_ns(_DAY, 9.5), _lamp_hours(_DAY, 10.0, 25, 77.0))
    assert msb.strict_24h_max_diagnostic(short, _DAY, _OFFSET) is None
    # the blend never reads the diagnostic
    rows = make_rows(days=60, stations=("NYC",), horizons=("D-1",))
    fit = msb.fit_blend(rows, level=1, settings=_settings())
    row = rows[4]
    flagged = dataclasses.replace(
        row, lamp=dataclasses.replace(row.lamp, strict_24h_max_f_diagnostic=150.0)
    )
    assert msb.predict_row(fit, row) == msb.predict_row(fit, flagged)


# ------------------------------------------------------------------ leakage


def test_feature_rows_all_available_before_anchor() -> None:
    anchor = _lst_ns(_DAY, 14.0)
    row = msb.assemble_feature_row(
        station="NYC",
        climate_day=_DAY,
        version="v5.0",
        horizon="D0",
        anchor_ns=anchor,
        std_utc_offset_hours=_OFFSET,
        percentiles=_pct(85.0, 2.0),
        cli_tmax_f=88.0,
        obs_readings=[msb.ObsReading(_lst_ns(_DAY, 12.0), _lst_ns(_DAY, 12.1), 84.0)],
        lamp_runs=[
            msb.LampRun(_lst_ns(_DAY, 12.5), _lst_ns(_DAY, 13.5), _lamp_hours(_DAY, 15.0, 10, 90.0))
        ],
        pfm_vintages=[
            msb.SourceVintage(_lst_ns(_DAY, 8.0), 86.0),
            msb.SourceVintage(_lst_ns(_DAY, 15.0), 99.0),  # not yet available at the anchor
        ],
        mos_vintages=[
            msb.SourceVintage(_lst_ns(_DAY, 14.0), 97.0)
        ],  # available_at == anchor: excluded
    )
    assert row.pfm_mu_f == 86.0 and row.mos_mu_f is None
    msb.assert_row_leakage_free(row)
    avail = [
        t
        for t in (row.obs_available_at_ns, row.lamp.run_available_at_ns, row.pfm_available_at_ns)
        if t is not None
    ]
    assert max(avail) < row.anchor_ns
    assert row.lamp.min_valid_ts_ns is not None and row.lamp.min_valid_ts_ns > row.anchor_ns

    leaky = dataclasses.replace(row, pfm_available_at_ns=anchor)
    with pytest.raises(msb.LeakageError):
        msb.assert_row_leakage_free(leaky)
    with pytest.raises(msb.LeakageError):
        msb.fit_blend([leaky] * 40, level=0, settings=_settings())
    stale_hour = dataclasses.replace(
        row, lamp=dataclasses.replace(row.lamp, min_valid_ts_ns=anchor)
    )
    with pytest.raises(msb.LeakageError):
        msb.assert_row_leakage_free(stale_hour)


# ------------------------------------------------------------------ folds


def test_folds_blocked_within_version_and_never_straddle_source_break() -> None:
    v1 = make_rows(days=130, version="v4.1", stations=("NYC",), horizons=("D-1",))
    v2 = make_rows(
        days=130, start=dt.date(2023, 7, 1), version="v4.2", stations=("NYC",), horizons=("D-1",)
    )
    v3 = make_rows(
        days=40, start=dt.date(2024, 1, 1), version="v4.3", stations=("NYC",), horizons=("D-1",)
    )
    days = msb.days_by_version([*v1, *v2, *v3])
    breaks = (dt.date(2023, 3, 2),)  # inside v4.1, leaves 60 / 70 day segments
    plan = msb.build_folds(days, source_breaks=breaks)
    assert plan.folds
    for fold in plan.folds:
        every = set(fold.held_days) | set(fold.train_days)
        assert not set(fold.held_days) & set(fold.train_days)
        assert every <= set(days[fold.version])
        segments = {sum(1 for b in breaks if d >= b) for d in every}
        assert len(segments) == 1, "a fold must never straddle a source break"
        assert len(fold.held_days) >= 28 and len(fold.train_days) >= 28
    assert {f.version for f in plan.folds} == {"v4.1", "v4.2"}
    assert any(version == "v4.3" for version, _segment, _why in plan.excluded)
    assert sum(1 for f in plan.folds if f.version == "v4.1") >= 4  # two segments x >= 2 blocks
    held_v1 = [d for f in plan.folds if f.version == "v4.1" for d in f.held_days]
    assert len(held_v1) == len(set(held_v1))  # blocks partition the held days


def test_negative_control_shuffled_labels_gives_zero_delta() -> None:
    rows = make_rows(days=140, stations=("NYC", "LAX"), horizons=("D-1",), seed=21)
    plan = msb.build_folds(msb.days_by_version(rows), source_breaks=(), block_days=28)
    settings = _settings()

    def mean_delta(sample: list[msb.FeatureRow]) -> float:
        scored = msb.out_of_fold_scores(
            sample, plan, settings, levels=(0, 3), champion=False, m0_bootstrap_draws=_BOOT
        )
        return msb.mean_arm_difference(scored, "M0prime", "M3")

    real = mean_delta(rows)
    shuffled = mean_delta(msb.shuffle_labels(rows, seed=5))
    assert real > 0.3
    # the positive control has skill; the shuffled arm shows none (it can only lose to over-fitting)
    assert shuffled < 0.05 * real
    assert abs(shuffled) < 0.2 * real


# ------------------------------------------------------------------ champion link


def test_blend_m0_prime_matches_champion_crps_within_tolerance() -> None:
    rows = two_version_rows(seed=33)
    plan = msb.build_folds(msb.days_by_version(rows), source_breaks=(), block_days=28)
    scored = msb.out_of_fold_scores(
        rows, plan, _settings(), levels=(0,), champion=True, m0_bootstrap_draws=_BOOT
    )
    m0 = msb.mean_arm_crps(scored, "M0")
    m0p = msb.mean_arm_crps(scored, "M0prime")
    assert all(s.champion is not None and s.fold_id is not None for s in scored)
    status = msb.m0_prime_status(m0_crps=m0, m0_prime_crps=m0p, tolerance=0.15)
    assert status.within_tolerance, (m0, m0p)
    assert abs(m0p - m0) < 0.15


def test_accept_refused_when_m0_prime_worse_than_m0_beyond_tolerance() -> None:
    assert msb.m0_prime_status(m0_crps=1.00, m0_prime_crps=1.04, tolerance=0.05).within_tolerance
    worse = msb.m0_prime_status(m0_crps=1.00, m0_prime_crps=1.06, tolerance=0.05)
    assert not worse.within_tolerance and worse.worse_than_champion
    better = msb.m0_prime_status(m0_crps=1.00, m0_prime_crps=0.80, tolerance=0.05)
    assert better.within_tolerance  # only WORSE beyond the tolerance refuses
    verdict = msb.decide_acceptance(_passing_inputs(m0p_minus_m0=0.06, m0p_tolerance=0.05))
    assert verdict.verdict is msb.Verdict.REFUSED_M0PRIME_WORSE


# ------------------------------------------------------------------ acceptance


def _summary(mean: float, lb: float) -> msb.DeltaSummary:
    return msb.DeltaSummary(mean=mean, lb=lb, n_days=300)


def _passing_inputs(**overrides: object) -> msb.AcceptanceInputs:
    base: dict[str, object] = {
        "m0p_vs_m3": _summary(0.30, 0.20),
        "m0_vs_m3": _summary(0.31, 0.21),
        "fold_means_m0p_vs_m3": (0.3, 0.25, 0.35, 0.3, 0.28, 0.33, 0.31, 0.29),
        "m0_fold_crps": (1.00, 1.10, 0.90, 1.05, 0.95, 1.02, 0.98, 1.00),
        "floor_multiple": 1.0,
        "leak_audit_multiple": 20.0,
        "m0p_minus_m0": 0.0,
        "m0p_tolerance": 0.05,
        "station_deltas": {"NYC": 0.3, "LAX": 0.25},
        "station_tolerance": 0.05,
        "lag_rerun": _summary(0.25, 0.10),
        "lag_rows_lost": 12,
    }
    base.update(overrides)
    return msb.AcceptanceInputs(**base)  # type: ignore[arg-type]


def test_floor_is_prereg_multiple_of_m0_fold_sd_committed_before_m1_m3_scored() -> None:
    folds = (1.0, 1.2, 0.8, 1.0)
    sd = msb.fold_sd(folds)
    assert sd == pytest.approx(0.1633, abs=1e-3)
    assert msb.minimum_effect_floor(folds, 1.5) == pytest.approx(1.5 * sd)
    with pytest.raises(msb.PreregIncompleteError):
        msb.minimum_effect_floor(folds, None)
    with pytest.raises(msb.PreregIncompleteError):
        msb.minimum_effect_floor(folds, 0.0)
    with pytest.raises(msb.PreregIncompleteError):
        msb.decide_acceptance(_passing_inputs(floor_multiple=None))
    with pytest.raises(msb.InsufficientFoldsError):
        msb.minimum_effect_floor((1.0,), 1.0)  # one fold has no spread


def test_acceptance_requires_floor_and_one_sided_975_lb_gt_zero() -> None:
    assert msb.ALPHA_ONE_SIDED == 0.025
    draws = [float(i) for i in range(1, 1001)]
    assert msb.lower_bound_one_sided(draws) == pytest.approx(25.0, abs=1.0)
    floor = msb.minimum_effect_floor(_passing_inputs().m0_fold_crps, 1.0)
    assert 0.0 < floor < 0.2
    ok = msb.decide_acceptance(_passing_inputs())
    assert ok.verdict is msb.Verdict.ACCEPT
    below_floor = msb.decide_acceptance(_passing_inputs(m0p_vs_m3=_summary(0.30, floor * 0.5)))
    assert below_floor.verdict is msb.Verdict.NO_SKILL
    assert any("floor" in reason for reason in below_floor.reasons)
    at_floor = msb.decide_acceptance(_passing_inputs(m0p_vs_m3=_summary(0.30, floor)))
    assert at_floor.verdict is msb.Verdict.ACCEPT  # LB >= floor, the R25 inequality


def test_acceptance_also_requires_m0_minus_m3_lb_gt_zero_and_ge_floor() -> None:
    floor = msb.minimum_effect_floor(_passing_inputs().m0_fold_crps, 1.0)
    weak = msb.decide_acceptance(_passing_inputs(m0_vs_m3=_summary(0.31, floor * 0.5)))
    assert weak.verdict is msb.Verdict.NO_SKILL
    assert any("CRPS(M0) - CRPS(M3)" in reason for reason in weak.reasons)
    negative = msb.decide_acceptance(_passing_inputs(m0_vs_m3=_summary(0.05, -0.02)))
    assert negative.verdict is msb.Verdict.NO_SKILL


def test_acceptance_stops_when_ci_lower_bound_not_positive() -> None:
    for lb in (0.0, -0.01):
        verdict = msb.decide_acceptance(_passing_inputs(m0p_vs_m3=_summary(0.05, lb)))
        assert verdict.verdict is msb.Verdict.NO_SKILL
        assert any("lower bound" in reason for reason in verdict.reasons)


def test_fold_sign_rule_is_ceil_075_n_folds() -> None:
    expected = {1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 8: 6, 10: 8, 12: 9}
    for n, need in expected.items():
        assert msb.fold_sign_threshold(n) == need == math.ceil(0.75 * n)
    seven_of_ten = (0.2,) * 7 + (-0.1,) * 3
    eight_of_ten = (0.2,) * 8 + (-0.1,) * 2
    fail = msb.decide_acceptance(_passing_inputs(fold_means_m0p_vs_m3=seven_of_ten))
    passed = msb.decide_acceptance(_passing_inputs(fold_means_m0p_vs_m3=eight_of_ten))
    assert fail.verdict is msb.Verdict.NO_SKILL and any("folds" in r for r in fail.reasons)
    assert passed.verdict is msb.Verdict.ACCEPT


def test_delta_above_fold_spread_is_held_leak_audit() -> None:
    sd = msb.fold_sd(_passing_inputs().m0_fold_crps)
    suspicious = msb.decide_acceptance(
        _passing_inputs(m0p_vs_m3=_summary(sd * 25.0, sd * 24.0), leak_audit_multiple=20.0)
    )
    assert suspicious.verdict is msb.Verdict.HELD_LEAK_AUDIT


def test_no_station_degraded_beyond_tolerance() -> None:
    bad = msb.decide_acceptance(_passing_inputs(station_deltas={"NYC": 0.3, "LAX": -0.08}))
    assert bad.verdict is msb.Verdict.NO_SKILL and any("LAX" in r for r in bad.reasons)
    fine = msb.decide_acceptance(_passing_inputs(station_deltas={"NYC": 0.3, "LAX": -0.04}))
    assert fine.verdict is msb.Verdict.ACCEPT


def test_lag_sensitivity_rerun_plus_60_min_reported_and_sign_must_hold() -> None:
    assert msb.LAG_SHIFT_NS == 3600 * _NS
    held = msb.decide_acceptance(_passing_inputs())
    assert held.verdict is msb.Verdict.ACCEPT
    assert held.report["lag_rerun"]["rows_lost"] == 12
    flipped = msb.decide_acceptance(_passing_inputs(lag_rerun=_summary(0.01, -0.05)))
    assert flipped.verdict is msb.Verdict.NO_SKILL and any("lag" in r for r in flipped.reasons)
    missing = msb.decide_acceptance(_passing_inputs(lag_rerun=None))
    assert missing.verdict is msb.Verdict.NO_SKILL

    anchor = _lst_ns(_DAY, 14.0)
    base_kwargs: dict[str, object] = {
        "station": "NYC",
        "climate_day": _DAY,
        "version": "v5.0",
        "horizon": "D0",
        "anchor_ns": anchor,
        "std_utc_offset_hours": _OFFSET,
        "percentiles": _pct(85.0, 2.0),
        "cli_tmax_f": 88.0,
        "pfm_vintages": [
            msb.SourceVintage(anchor - 30 * 60 * _NS, 86.0)
        ],  # 30 min before the anchor
    }
    base = msb.assemble_feature_row(**base_kwargs)  # type: ignore[arg-type]
    shifted = msb.assemble_feature_row(**base_kwargs, extra_lag_ns=msb.LAG_SHIFT_NS)  # type: ignore[arg-type]
    assert base.pfm_mu_f == 86.0 and shifted.pfm_mu_f is None
    lost = msb.lag_rows_lost([base], [shifted])
    assert lost == {"lamp": 0, "pfm": 1, "mos": 0}


def test_crps_by_horizon_pit_coverage_and_log_score_are_reported() -> None:
    rows = make_rows(days=84, stations=("NYC",), horizons=("D-1", "D0"), seed=41)
    plan = msb.build_folds(msb.days_by_version(rows), source_breaks=(), block_days=28)
    settings = _settings()
    scored = msb.out_of_fold_scores(
        rows, plan, settings, levels=(0, 3), champion=False, m0_bootstrap_draws=_BOOT
    )
    report = msb.diagnostics(scored, arm="M3", nu=settings.nu, rung_edges=(50, 55, 60, 65, 70, 75))
    assert set(report["crps_by_horizon"]) == {"D-1", "D0"}
    assert len(report["pit_histogram"]) == 10 and sum(report["pit_histogram"]) == len(
        [s for s in scored if s.arm_predictions.get("M3")]
    )
    assert 0.0 <= report["coverage_80"] <= 1.0 and 0.0 <= report["coverage_95"] <= 1.0
    assert report["coverage_95"] >= report["coverage_80"]
    assert math.isfinite(report["mean_rung_log_score"]) and report["mean_rung_log_score"] <= 0.0
    assert report["rmse_descriptive"] > 0.0
    assert report["rmse_label"] == "descriptive_only"


# ------------------------------------------------------------------ statistics + C1 gate


def test_stationary_bootstrap_is_seeded_and_block_correlated() -> None:
    values = [0.5] * 60
    draws = msb.stationary_bootstrap_means(values, mean_block=7.0, n_boot=200, seed=1)
    assert len(draws) == 200 and draws == sorted(draws)
    assert all(d == pytest.approx(0.5) for d in draws)
    noisy = [(-1.0) ** i * 1.0 + 0.3 for i in range(80)]
    a = msb.stationary_bootstrap_means(noisy, mean_block=7.0, n_boot=300, seed=9)
    b = msb.stationary_bootstrap_means(noisy, mean_block=7.0, n_boot=300, seed=9)
    assert a == b
    summary = msb.delta_summary(
        [(dt.date(2023, 1, 1) + dt.timedelta(days=i), 0.3 + 0.01 * (i % 3)) for i in range(120)],
        n_boot=200,
        seed=2,
        mean_block=7.0,
    )
    assert summary.lb < summary.mean and summary.lb > 0.2 and summary.n_days == 120


def test_phase_a_refuses_to_score_until_c1_has_14_days_of_measured_lags() -> None:
    ok = {"lamp": 14, "pfm": 20, "mos": 30}
    msb.require_c1_measured_lags(ok, required=("lamp", "pfm", "mos"), min_days=14)
    with pytest.raises(msb.C1LagEvidenceError):
        msb.require_c1_measured_lags(
            {**ok, "lamp": 13}, required=("lamp", "pfm", "mos"), min_days=14
        )
    with pytest.raises(msb.C1LagEvidenceError):
        msb.require_c1_measured_lags({"lamp": 30}, required=("lamp", "pfm"), min_days=14)
    with pytest.raises(msb.C1LagEvidenceError):
        msb.require_c1_measured_lags(
            ok, required=("lamp",), min_days=14, uncensored={"lamp": 3}, min_uncensored=10
        )
    msb.require_c1_measured_lags(
        ok, required=("lamp",), min_days=14, uncensored={"lamp": 12}, min_uncensored=10
    )


def test_feature_row_json_round_trips() -> None:
    row = make_rows(days=1, stations=("NYC",), horizons=("D0",))[0]
    assert msb.feature_row_from_json(msb.feature_row_to_json(row)) == row
