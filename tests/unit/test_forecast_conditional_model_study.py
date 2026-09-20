"""Leak guards and mechanics for `scripts/analysis/forecast_conditional_model_study.py` (WP-6).

No network, no real archive read: every fixture is a small synthetic in-memory
row through the real functions, matching
`test_forecast_txn_climate_day_cli_alignment.py`'s convention. `main()` and the
`load_*` real-I/O paths are exercised by hand to regenerate the artefact, never
by this suite.

The four leakage vectors WP-6 names each get a test here that FAILS if its
guard is removed (mutation-verified at authoring time):

* train-window leak  -> `fit_train_error_model` (reuses the shipped
  `fit_error_model(train_end_exclusive=...)`)
* forecast vintage   -> `assert_forecast_vintage`
* duplicate trials   -> `assert_unique_station_days`
* target-into-feature-> `assert_features_exclude_target`
* cadence mixing     -> `downsample_running_max` / `assert_single_cadence` (L-13)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def study() -> ModuleType:
    return _load_module("forecast_conditional_model_study")


def _row(study: ModuleType, day: dt.date, *, station: str = "KSFO", settled: int = 70):
    return study.CorpusRow(
        station=station,
        climate_day=day,
        settled_tmax_f=settled,
        forecast_txn_f_by_lead={17: float(settled) - 1.0, 23: float(settled) - 2.0},
        obs_max_f=float(settled),
        running_max_f_by_local_hour={10: float(settled) - 5.0},
        obs_cadence_seconds=study.OBS_CADENCE_SECONDS,
    )


# ---------------------------------------------------------------------------
# Vector 1 -- the train window may never reach into the holdout
# ---------------------------------------------------------------------------


def test_a_training_corpus_that_reaches_into_the_holdout_refuses_loudly(
    study: ModuleType,
) -> None:
    rows = [_row(study, dt.date(2024, 6, 1)), _row(study, dt.date(2025, 1, 1))]
    with pytest.raises(ValueError, match="lookahead bias"):
        study.fit_train_error_model(rows)


def test_a_clean_training_corpus_fits(study: ModuleType) -> None:
    rows = [_row(study, dt.date(2024, 6, 1) + dt.timedelta(days=i)) for i in range(60)]
    model = study.fit_train_error_model(rows)
    assert model.bias_by_key["*"] == pytest.approx(1.0)


def test_the_split_helper_never_lets_a_holdout_day_into_the_train_side(
    study: ModuleType,
) -> None:
    rows = [_row(study, dt.date(2024, 12, 31)), _row(study, dt.date(2025, 1, 1))]
    train, holdout = study.split_corpus(rows)
    assert [r.climate_day for r in train] == [dt.date(2024, 12, 31)]
    assert [r.climate_day for r in holdout] == [dt.date(2025, 1, 1)]
    with pytest.raises(study.LeakageError, match="train/holdout overlap"):
        study.assert_split_disjoint(train + holdout, holdout)


# ---------------------------------------------------------------------------
# Vector 2 -- forecast vintage: issued before the decision instant, always
# ---------------------------------------------------------------------------


def test_a_forecast_issued_after_the_decision_instant_is_refused(study: ModuleType) -> None:
    day = dt.date(2023, 7, 4)
    late = dt.datetime(2023, 7, 4, 13, tzinfo=dt.UTC)
    with pytest.raises(study.LeakageError, match="vintage"):
        study.assert_forecast_vintage(
            station="KSFO", climate_day=day, runtime_ns=int(late.timestamp()) * study.NS
        )


def test_a_forecast_issued_at_or_before_the_decision_instant_is_accepted(
    study: ModuleType,
) -> None:
    day = dt.date(2023, 7, 4)
    for hour in (1, 7, 12):
        at = dt.datetime(2023, 7, 4, hour, tzinfo=dt.UTC)
        study.assert_forecast_vintage(
            station="KSFO", climate_day=day, runtime_ns=int(at.timestamp()) * study.NS
        )


def test_the_shortest_archived_lead_clears_the_decision_instant(study: ModuleType) -> None:
    """The lead set is declared, not discovered: min lead must be vintage-legal."""
    assert min(study.LEAD_BINS_HOURS) == study.PRIMARY_LEAD_HOURS
    day = dt.date(2023, 7, 4)
    ftime = dt.datetime(2023, 7, 5, 0, tzinfo=dt.UTC)
    runtime = ftime - dt.timedelta(hours=study.PRIMARY_LEAD_HOURS)
    study.assert_forecast_vintage(
        station="KSFO", climate_day=day, runtime_ns=int(runtime.timestamp()) * study.NS
    )


# ---------------------------------------------------------------------------
# Vector 3 -- one trial unit is one station-day; duplicates inflate n
# ---------------------------------------------------------------------------


def test_a_duplicated_station_day_is_refused(study: ModuleType) -> None:
    day = dt.date(2023, 3, 3)
    rows = [_row(study, day), _row(study, day)]
    with pytest.raises(study.LeakageError, match="duplicate station-day"):
        study.assert_unique_station_days(rows)


def test_the_same_day_at_two_stations_is_not_a_duplicate(study: ModuleType) -> None:
    day = dt.date(2023, 3, 3)
    study.assert_unique_station_days(
        [_row(study, day, station="KSFO"), _row(study, day, station="KLAX")]
    )


# ---------------------------------------------------------------------------
# Vector 4 -- the CLI final is the TARGET and may never become a feature
# ---------------------------------------------------------------------------


def test_a_target_derived_name_may_not_appear_in_the_feature_set(study: ModuleType) -> None:
    with pytest.raises(study.LeakageError, match="target"):
        study.assert_features_exclude_target(("forecast_txn_f", "settled_tmax_f"))


def test_the_declared_feature_set_is_target_free(study: ModuleType) -> None:
    study.assert_features_exclude_target(study.DECLARED_FEATURE_NAMES)
    assert study.TARGET_NAME not in study.DECLARED_FEATURE_NAMES


# ---------------------------------------------------------------------------
# L-13 -- an extremum is not comparable across cadences
# ---------------------------------------------------------------------------


def test_a_running_max_is_taken_on_one_declared_cadence_only(study: ModuleType) -> None:
    base = dt.datetime(2023, 5, 1, 0, tzinfo=dt.UTC)
    samples = [(base + dt.timedelta(minutes=i), 60.0 + (i % 7)) for i in range(60)]
    kept = study.downsample_running_max(samples, cadence_seconds=300)
    assert [t.minute for t, _ in kept] == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]


def test_mixing_two_cadences_in_one_comparison_is_refused(study: ModuleType) -> None:
    with pytest.raises(study.LeakageError, match="cadence"):
        study.assert_single_cadence({60, 300})


def test_a_single_cadence_is_accepted(study: ModuleType) -> None:
    study.assert_single_cadence({study.OBS_CADENCE_SECONDS})


# ---------------------------------------------------------------------------
# Scoring mechanics
# ---------------------------------------------------------------------------


def test_the_brier_score_of_a_perfect_forecaster_is_zero(study: ModuleType) -> None:
    trials = (
        study.Trial("median", "KSFO", dt.date(2023, 1, 1), True, 1.0, 0.5),
        study.Trial("median", "KSFO", dt.date(2023, 1, 2), False, 0.0, 0.5),
    )
    assert study.brier(trials, "p_fc") == pytest.approx(0.0)
    assert study.brier(trials, "p_clim") == pytest.approx(0.25)


def test_reliability_buckets_report_absolute_deviation(study: ModuleType) -> None:
    trials = tuple(
        study.Trial("median", "KSFO", dt.date(2023, 1, 1) + dt.timedelta(days=i), i < 5, 0.55, 0.5)
        for i in range(10)
    )
    buckets = study.reliability(trials, "p_fc")
    hit = next(b for b in buckets if b.n)
    assert hit.observed == pytest.approx(0.5)
    assert hit.predicted == pytest.approx(0.55)
    assert hit.abs_deviation == pytest.approx(0.05)


def test_the_bootstrap_resamples_whole_clusters_not_single_trials(
    study: ModuleType,
) -> None:
    """Every trial on a resampled DATE moves together, so the CI is genuinely clustered."""
    day = dt.date(2023, 1, 1)
    trials = tuple(
        study.Trial(study.FAMILY_MEDIAN, station, day, True, 1.0, 0.0, 0.0, 0.5)
        for station in ("KSFO", "KLAX")
    )
    ci = study.bootstrap_brier_difference_ci(
        trials, against=study.MODEL_CLIMATOLOGY, cluster=study.CLUSTER_DATE,
        iterations=64, seed=1,
    )
    assert ci.low == pytest.approx(-1.0)
    assert ci.high == pytest.approx(-1.0)
    assert ci.n_clusters == 1
    assert ci.max_cluster_size == 2


def test_the_bootstrap_is_deterministic_for_a_fixed_seed(study: ModuleType) -> None:
    trials = tuple(
        study.Trial(
            study.FAMILY_MEDIAN,
            station,
            dt.date(2023, 1, 1) + dt.timedelta(days=i),
            i % 3 == 0,
            0.3,
            0.5,
            0.4,
            0.5,
        )
        for i in range(50)
        for station in ("KSFO", "KLAX")
    )
    kwargs = {
        "against": study.MODEL_PERSISTENCE,
        "cluster": study.CLUSTER_DATE,
        "iterations": 200,
        "seed": 7,
    }
    assert study.bootstrap_brier_difference_ci(
        trials, **kwargs
    ) == study.bootstrap_brier_difference_ci(trials, **kwargs)


def test_mae_and_rmse_are_reported_per_declared_lead(study: ModuleType) -> None:
    rows = [_row(study, dt.date(2023, 1, 1) + dt.timedelta(days=i)) for i in range(4)]
    by_lead = study.point_error_by_lead(rows)
    assert by_lead[17].mae == pytest.approx(1.0)
    assert by_lead[23].rmse == pytest.approx(2.0)
    assert by_lead[17].n == 4


# ---------------------------------------------------------------------------
# Thin data is an outcome, never a verdict
# ---------------------------------------------------------------------------


def test_thin_holdout_data_returns_the_insufficient_verdict_and_never_raises(
    study: ModuleType,
) -> None:
    train = [_row(study, dt.date(2023, 1, 1) + dt.timedelta(days=i)) for i in range(400)]
    holdout = [_row(study, dt.date(2025, 1, 1) + dt.timedelta(days=i)) for i in range(3)]
    result = study.evaluate(train, holdout)
    assert result.verdict == study.VERDICT_INSUFFICIENT_DATA
    assert result.brier_fc is None


def test_the_insufficient_verdict_exits_zero(study: ModuleType) -> None:
    assert study.exit_code_for(study.VERDICT_INSUFFICIENT_DATA) == 0


# ---------------------------------------------------------------------------
# The artefact is deterministic
# ---------------------------------------------------------------------------


_FIXTURE_STATIONS = ("KSFO", "KLAX", "KMIA", "KMDW")


def _corpus(study: ModuleType, start: dt.date, days: int) -> list:
    """Four stations x consecutive days: non-degenerate date clusters, and every
    day after the first has a predecessor for the persistence baseline."""
    return [
        _row(
            study,
            start + dt.timedelta(days=i),
            station=station,
            settled=60 + (i + s) % 25,
        )
        for i in range(days)
        for s, station in enumerate(_FIXTURE_STATIONS)
    ]


def test_the_same_corpus_renders_a_byte_identical_artefact(study: ModuleType) -> None:
    train = _corpus(study, dt.date(2022, 1, 1), 300)
    holdout = _corpus(study, dt.date(2025, 1, 1), 150)
    first = study.render_artefact(study.evaluate(train, holdout), input_digests={"a": "b"})
    second = study.render_artefact(study.evaluate(train, holdout), input_digests={"a": "b"})
    assert first == second
    assert "\"corpus_definition\"" in first


def test_the_artefact_records_the_declared_feature_set_and_the_cadence(
    study: ModuleType,
) -> None:
    train = _corpus(study, dt.date(2022, 1, 1), 300)
    holdout = _corpus(study, dt.date(2025, 1, 1), 150)
    text = study.render_artefact(study.evaluate(train, holdout), input_digests={})
    assert "obs_cadence_seconds" in text
    assert study.DECLARED_FEATURE_NAMES[0] in text


def test_the_artefact_carries_source_archive_digests_and_code_provenance(
    study: ModuleType,
) -> None:
    """Review defect 10: the artefact must be traceable to exact inputs AND code."""
    train = _corpus(study, dt.date(2022, 1, 1), 300)
    holdout = _corpus(study, dt.date(2025, 1, 1), 150)
    text = study.render_artefact(
        study.evaluate(train, holdout),
        input_digests={"corpus:pooled": "deadbeef"},
        source_digests={"archive:iem-mos:KSFO:0": "cafe"},
        provenance={"commit": "abc123", "worktree": "DIRTY"},
    )
    assert "source_archive_digests" in text
    assert "cafe" in text
    assert "abc123" in text
    assert "DIRTY" in text


def test_the_ladder_reports_every_model_and_a_skill_score(study: ModuleType) -> None:
    result = study.evaluate(
        _corpus(study, dt.date(2022, 1, 1), 300), _corpus(study, dt.date(2025, 1, 1), 150)
    )
    family = result.by_family[study.FAMILY_MEDIAN]
    assert set(family["brier_by_model"]) == set(study.MODEL_KEYS)
    assert set(family["brier_skill_score_vs_constant"]) == set(study.MODEL_KEYS)
    assert result.brier_persistence is not None
    assert result.brier_constant is not None


def test_the_rung_family_does_not_report_a_climatology_comparison(study: ModuleType) -> None:
    """Review defect 3: a baseline that loses to a constant is not a baseline."""
    result = study.evaluate(
        _corpus(study, dt.date(2022, 1, 1), 300), _corpus(study, dt.date(2025, 1, 1), 150)
    )
    rung = result.by_family[study.FAMILY_RUNG]
    assert "WITHDRAWN" in str(rung["climatology_comparison"])
    assert all(
        ci["against"] != study.MODEL_CLIMATOLOGY for ci in rung["brier_difference_intervals"]
    )


def test_the_calibration_leg_is_evaluated_not_merely_computed(study: ModuleType) -> None:
    """Review defect 6: the leg must produce an explicit PASS/FAIL."""
    result = study.evaluate(
        _corpus(study, dt.date(2022, 1, 1), 300), _corpus(study, dt.date(2025, 1, 1), 150)
    )
    leg = result.by_family[study.FAMILY_MEDIAN]["calibration_leg"][study.MODEL_FORECAST]
    assert leg["verdict"] in (study.LEG_PASS, study.LEG_FAIL)
    assert leg["epsilon"] == study.RELIABILITY_EPSILON
    assert leg["n_buckets_evaluated"] >= 1


def test_a_failing_bucket_is_reported_with_n_and_a_z_score(study: ModuleType) -> None:
    trials = tuple(
        study.Trial(
            study.FAMILY_MEDIAN,
            "KSFO",
            dt.date(2025, 1, 1) + dt.timedelta(days=i),
            i < 10,
            0.55,
            0.5,
            0.5,
            0.5,
        )
        for i in range(100)
    )
    leg = study.evaluate_calibration_leg(trials, study.MODEL_FORECAST)
    assert leg.verdict == study.LEG_FAIL
    assert leg.failing[0]["n"] == 100
    assert leg.failing[0]["z"] > 0


def test_uniform_underconfidence_is_flagged_with_its_live_consequence(
    study: ModuleType,
) -> None:
    """Review defect 3, forward-looking: too-wide sigma makes a live rule UNDER-fire."""
    trials = tuple(
        study.Trial(
            study.FAMILY_RUNG,
            "KSFO",
            dt.date(2025, 1, 1) + dt.timedelta(days=i),
            i % 10 < 6,
            0.25,
            0.5,
            0.5,
            0.5,
        )
        for i in range(100)
    )
    signal = study.underconfidence_signal(trials, study.MODEL_FORECAST)
    assert signal["all_buckets_underconfident"] is True
    assert signal["mean_signed_deviation_observed_minus_predicted"] > 0
    assert "UNDER-FIRES" in str(signal["live_consequence"])


# ---------------------------------------------------------------------------
# Review defect 5 -- the cached-corpus load path must re-assert vintage
# ---------------------------------------------------------------------------


def test_a_hand_mutated_corpus_json_is_vintage_checked_on_LOAD(study: ModuleType) -> None:
    """The load path, not just the build path, must refuse an illegal vintage.

    `build_corpus` calls `assert_forecast_vintage` per MOS row, but the run that
    produced every number in the artefact went through the cached-corpus JSON,
    where no forecast runtime survives. A stale or hand-edited corpus carrying a
    lead shorter than the declared set implies a run issued AFTER the decision
    instant, and must be refused there too.
    """
    day = dt.date(2023, 7, 4)
    good = study.CorpusRow(
        station="KSFO",
        climate_day=day,
        settled_tmax_f=70,
        forecast_txn_f_by_lead={17: 69.0},
        obs_max_f=70.0,
        running_max_f_by_local_hour={},
        obs_cadence_seconds=study.OBS_CADENCE_SECONDS,
    )
    study.assert_corpus_vintage([good])  # the shipped lead set is legal
    # lead 11 h => runtime 13:00Z on the climate day => AFTER the 12:00Z decision.
    mutated = study.CorpusRow(
        station="KSFO",
        climate_day=day,
        settled_tmax_f=70,
        forecast_txn_f_by_lead={11: 69.0},
        obs_max_f=70.0,
        running_max_f_by_local_hour={},
        obs_cadence_seconds=study.OBS_CADENCE_SECONDS,
    )
    with pytest.raises(study.LeakageError, match="vintage"):
        study.assert_corpus_vintage([mutated])


def test_the_cached_corpus_loader_re_asserts_vintage(study: ModuleType, tmp_path) -> None:
    import json

    path = tmp_path / "corpus.json"
    path.write_text(
        json.dumps(
            [
                {
                    "station": "KSFO",
                    "climate_day": "2023-07-04",
                    "settled_tmax_f": 70,
                    "forecast_txn_f_by_lead": {"11": 69.0},
                    "obs_max_f": 70.0,
                    "running_max_f_by_local_hour": {},
                    "obs_cadence_seconds": study.OBS_CADENCE_SECONDS,
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(study.LeakageError, match="vintage"):
        study.load_cached_corpus(path)


# ---------------------------------------------------------------------------
# Review defect 4 -- the CI's cluster label must describe the SHIPPED config
# ---------------------------------------------------------------------------


def test_station_day_clustering_is_degenerate_for_the_shipped_headline_family(
    study: ModuleType,
) -> None:
    """One trial per station-day in the headline family => station-day clusters are size 1.

    The old artefact key claimed `cluster_station_day` while the bootstrap it
    described was an IID trial bootstrap. Refusing a degenerate cluster key is
    what makes the label honest.
    """
    trials = tuple(
        study.Trial(
            study.FAMILY_MEDIAN,
            "KSFO",
            dt.date(2025, 1, 1) + dt.timedelta(days=i),
            i % 2 == 0,
            0.4,
            0.5,
        )
        for i in range(40)
    )
    with pytest.raises(study.LeakageError, match="degenerate"):
        study.assert_nondegenerate_clustering(trials, cluster=study.CLUSTER_STATION_DAY)


def test_date_clustering_is_non_degenerate_when_stations_share_a_date(
    study: ModuleType,
) -> None:
    trials = tuple(
        study.Trial(
            study.FAMILY_MEDIAN, station, dt.date(2025, 1, 1) + dt.timedelta(days=i), True, 0.4, 0.5
        )
        for i in range(40)
        for station in ("KSFO", "KLAX", "KMIA", "KMDW")
    )
    study.assert_nondegenerate_clustering(trials, cluster=study.CLUSTER_DATE)
    study.assert_nondegenerate_clustering(trials, cluster=study.CLUSTER_STATION)


def test_the_ci_reports_the_cluster_it_actually_used(study: ModuleType) -> None:
    trials = tuple(
        study.Trial(
            study.FAMILY_MEDIAN,
            station,
            dt.date(2025, 1, 1) + dt.timedelta(days=i),
            i % 3 == 0,
            0.4,
            0.5,
        )
        for i in range(40)
        for station in ("KSFO", "KLAX", "KMIA", "KMDW")
    )
    ci = study.bootstrap_brier_difference_ci(
        trials, against="p_clim", cluster=study.CLUSTER_DATE, iterations=128, seed=3
    )
    assert ci.cluster == study.CLUSTER_DATE
    assert ci.n_clusters == 40
    assert ci.max_cluster_size == 4
    assert ci.low <= ci.high
