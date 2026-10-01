"""SL-15 tests for the NBP nightly learning loop.

All fixtures are synthetic. The tests never read the real NBP derived store,
the real settlement-truth parquet, or any post-holdout labels.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import math
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.analysis import nbp_calibration as calib
from breezy.persistence.nbp_derived_store import DerivedNbpRow
from breezy.runtime.health import AlertPayload

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_learning_nightly.py"
)
_spec = importlib.util.spec_from_file_location("nbp_learning_nightly", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
nbp_learning_nightly = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nbp_learning_nightly
_spec.loader.exec_module(nbp_learning_nightly)
nbp_learning_nightly = cast(Any, nbp_learning_nightly)


class _FakeAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


_NS = 1_000_000_000


def _ns(instant: dt.datetime) -> int:
    return int(instant.timestamp()) * _NS


def _cycle_row(cycle: dt.datetime) -> DerivedNbpRow:
    cycle_ns = _ns(cycle)
    return DerivedNbpRow(
        station="KLAX",
        variable="TXN_Q50",
        cycle_runtime_ns=cycle_ns,
        valid_start_ns=cycle_ns,
        valid_end_ns=cycle_ns,
        value_f=70.0,
        absence_reason=None,
        header_model_version="5.0",
        nbm_version_era="v5.0",
        version_break_mismatch=False,
        available_at_ns=cycle_ns,
        last_modified=None,
        source_host="test",
        raw_sha256="0" * 64,
        fetched_at_ns=cycle_ns,
    )


def _row(
    day: dt.date,
    *,
    status: str = nbp_learning_nightly.LABEL_STATUS_FINAL,
    residual_f: float = 0.25,
    p_m2: float = 0.70,
    p_m1: float = 0.55,
    outcome: bool = True,
) -> Any:
    return nbp_learning_nightly.LearningRow(
        station="LAX",
        climate_day=day,
        label_status=status,
        cli_tmax_f=72.0,
        m2_median_f=72.0 - residual_f,
        p_m2=p_m2,
        p_m1=p_m1,
        outcome=outcome,
    )


def _percentile_row(day: dt.date, *, residual_f: float = 0.0) -> Any:
    return nbp_learning_nightly.LearningRow(
        station="LAX",
        climate_day=day,
        label_status=nbp_learning_nightly.LABEL_STATUS_FINAL,
        cli_tmax_f=72.0 + residual_f,
        m2_median_f=72.0,
        p_m2=0.70,
        p_m1=0.55,
        outcome=True,
        percentiles=nbp_learning_nightly.Percentiles(
            q10=68.0,
            q25=70.0,
            q50=72.0,
            q75=74.0,
            q90=76.0,
            mean=72.0,
            sd=2.0,
        ),
        nbm_version="v5.0",
    )


def _artefact(*, fit_status: str = calib.FIT_STATUS_OK) -> calib.NbpCalibrationArtefact:
    return calib.NbpCalibrationArtefact(
        schema_version=calib.ARTEFACT_SCHEMA_VERSION,
        cdf_method="normal",
        recalibration="hierarchical_emos",
        correction_form="location_scale",
        delta=0.0,
        kappa=0.0,
        emos_params_by_version={"v5.0": (0.0, 1.0)},
        emos_draws_by_version={"v5.0": ((0.0, 1.0, 0.0),)},
        n_min=60,
        sigma_d=0.1,
        rung_probability_bounds={"mid": (0.5, 0.4, 0.6)},
        fit_status=fit_status,
    )


def test_heartbeat_fires_on_stale_cycle_positive_control() -> None:
    sink = _FakeAlertSink()
    now = dt.datetime(2026, 6, 5, 12, tzinfo=dt.UTC)

    result = nbp_learning_nightly.check_freshness(
        nbp_rows=(_cycle_row(now - dt.timedelta(hours=1)),),
        label_rows=(_row(dt.date(2026, 6, 4)),),
        now=now,
        sink=sink,
        positive_control=nbp_learning_nightly.PositiveControl.STALE_CYCLE,
    )

    assert result.stale_cycle
    assert [payload.event for payload in sink.payloads] == [
        "TEST_POSITIVE_CONTROL_nbp_nightly_stale_cycle"
    ]
    assert sink.payloads[0].detail == (
        "TEST_POSITIVE_CONTROL target_alarm=nbp_nightly_stale_cycle "
        "detail=newest_nbp_cycle_stale"
    )


def test_heartbeat_fires_on_stale_label_positive_control() -> None:
    sink = _FakeAlertSink()
    now = dt.datetime(2026, 6, 5, 12, tzinfo=dt.UTC)

    result = nbp_learning_nightly.check_freshness(
        nbp_rows=(_cycle_row(now - dt.timedelta(hours=1)),),
        label_rows=(_row(dt.date(2026, 6, 4)),),
        now=now,
        sink=sink,
        positive_control=nbp_learning_nightly.PositiveControl.STALE_LABEL,
    )

    assert result.stale_label
    assert [payload.event for payload in sink.payloads] == [
        "TEST_POSITIVE_CONTROL_nbp_nightly_stale_final_label"
    ]
    assert sink.payloads[0].detail == (
        "TEST_POSITIVE_CONTROL target_alarm=nbp_nightly_stale_final_label "
        "detail=newest_final_cli_label_stale"
    )


def test_fresh_state_gives_no_alert() -> None:
    sink = _FakeAlertSink()
    now = dt.datetime(2026, 6, 5, 12, tzinfo=dt.UTC)

    result = nbp_learning_nightly.check_freshness(
        nbp_rows=(_cycle_row(now - dt.timedelta(hours=1)),),
        label_rows=(_row(dt.date(2026, 6, 4)),),
        now=now,
        sink=sink,
    )

    assert not result.stale_cycle
    assert not result.stale_label
    assert sink.payloads == []


def test_post_holdout_final_label_date_counts_as_fresh_without_metric_access() -> None:
    sink = _FakeAlertSink()
    now = dt.datetime(2026, 7, 3, 12, tzinfo=dt.UTC)

    result = nbp_learning_nightly.check_freshness(
        nbp_rows=(_cycle_row(now - dt.timedelta(hours=1)),),
        label_rows=(_row(dt.date(2026, 7, 2)),),
        now=now,
        sink=sink,
    )

    assert result.newest_final_label_day == dt.date(2026, 7, 2)
    assert not result.stale_label
    assert sink.payloads == []


def test_newest_final_label_day_returns_only_date_and_never_tmax() -> None:
    class FinalDateOnly:
        label_status = nbp_learning_nightly.LABEL_STATUS_FINAL
        climate_day = dt.date(2026, 7, 2)

        @property
        def cli_tmax_f(self) -> float:
            raise AssertionError("freshness must not read final label temperatures")

    newest = nbp_learning_nightly.newest_final_label_day((FinalDateOnly(),))

    assert newest == dt.date(2026, 7, 2)
    assert not hasattr(newest, "tmax_f")


def test_drift_fires_on_positive_control() -> None:
    sink = _FakeAlertSink()

    result = nbp_learning_nightly.check_drift(
        rows=(_row(dt.date(2026, 6, 1)),),
        sink=sink,
        positive_control=True,
    )

    assert result.drifted
    assert [payload.event for payload in sink.payloads] == [
        "TEST_POSITIVE_CONTROL_nbp_nightly_drift"
    ]
    assert sink.payloads[0].detail == (
        "TEST_POSITIVE_CONTROL target_alarm=nbp_nightly_drift detail=mean_residual_shift"
    )


def test_calibration_drift_has_own_positive_control() -> None:
    sink = _FakeAlertSink()

    result = nbp_learning_nightly.check_drift(
        rows=(_percentile_row(dt.date(2026, 6, 1)),),
        sink=sink,
        frozen_artefact=_artefact(),
        calibration_positive_control=True,
    )

    assert result.calibration_drifted
    assert result.calibration_crps_delta is not None
    assert [payload.event for payload in sink.payloads] == [
        "TEST_POSITIVE_CONTROL_nbp_nightly_calibration_drift"
    ]
    assert sink.payloads[0].detail == (
        "TEST_POSITIVE_CONTROL target_alarm=nbp_nightly_calibration_drift "
        "detail=calibration_crps_delta"
    )


def test_provisional_labels_are_excluded_from_gates_and_metrics() -> None:
    rows = (
        _row(dt.date(2026, 6, 1), status=nbp_learning_nightly.LABEL_STATUS_PROVISIONAL),
        _row(dt.date(2026, 6, 2), status=nbp_learning_nightly.LABEL_STATUS_FINAL),
    )

    selected = nbp_learning_nightly.final_pre_holdout_rows(rows)
    metrics = nbp_learning_nightly.rolling_metrics(rows)

    assert [row.climate_day for row in selected] == [dt.date(2026, 6, 2)]
    assert metrics.n == 1


def test_residual_by_month_report_includes_untested_months() -> None:
    rows = (
        _row(dt.date(2026, 1, 1), residual_f=1.0),
        _row(dt.date(2026, 2, 1), residual_f=2.0),
        _row(dt.date(2026, 2, 2), residual_f=4.0),
    )

    report = nbp_learning_nightly.residual_by_month(rows, tested_months={1})

    assert [(item.month, item.status, item.median_residual_f) for item in report] == [
        ("2026-01", "TESTED", 1.0),
        ("2026-02", "UNTESTED", 3.0),
    ]


def test_candidate_artefact_never_writes_manifest_and_refuses_non_converged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", fake_home.as_posix())
    candidate_root = fake_home / ".local/share/breezy/derived/nbp_calibration/candidates"
    manifest_path = tmp_path / "nbp_calibration" / "manifest.json"

    written = nbp_learning_nightly.write_candidate_artefact(
        _artefact(), candidate_root=candidate_root, manifest_path=manifest_path
    )

    assert written.parent == candidate_root
    assert written.name.endswith(".json")
    assert not manifest_path.exists()
    assert not (candidate_root / "manifest.json").exists()
    with pytest.raises(calib.FitNotConvergedError):
        nbp_learning_nightly.write_candidate_artefact(
            _artefact(fit_status=calib.FIT_STATUS_NOT_CONVERGED),
            candidate_root=candidate_root,
            manifest_path=manifest_path,
        )


def test_candidate_root_refuses_paths_outside_candidate_base(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="candidate root must be under"):
        nbp_learning_nightly.write_candidate_artefact(
            _artefact(), candidate_root=tmp_path / "elsewhere"
        )


def test_candidate_root_refuses_repo_and_deploy_family_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    with pytest.raises(ValueError, match="candidate root must not be inside the repo"):
        nbp_learning_nightly.write_candidate_artefact(
            _artefact(), candidate_root=repo_root / ".local/share/breezy/derived/nbp_calibration/candidates"
        )
    with pytest.raises(ValueError, match="candidate root must not be inside the repo"):
        nbp_learning_nightly.write_candidate_artefact(
            _artefact(), candidate_root=repo_root / "deploy" / "families" / "nbp_calibration" / "candidates"
        )


def test_holdout_path_is_off_by_default_and_refuses_without_flag() -> None:
    rows = (_row(dt.date(2026, 7, 1)),)

    assert nbp_learning_nightly.final_pre_holdout_rows(rows) == ()
    with pytest.raises(nbp_learning_nightly.HoldoutAuthorizationError):
        nbp_learning_nightly.final_rows_for_report(
            rows, include_holdout=True, holdout_authorized=False
        )


def test_alerts_go_through_the_sender() -> None:
    sink = _FakeAlertSink()

    nbp_learning_nightly.send_alert(
        sink,
        event=nbp_learning_nightly.NBP_DRIFT_ALERT_EVENT,
        detail="positive_control",
    )

    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == nbp_learning_nightly.NBP_DRIFT_ALERT_EVENT


def _std_normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _mid_rung_probability(*, mu: float, sigma: float, center_f: int) -> float:
    """P(tmax in [center, center+1]) under N(mu, sigma), with the 0.5°F continuity correction."""
    upper = _std_normal_cdf((center_f + 1.5 - mu) / sigma)
    lower = _std_normal_cdf((center_f - 0.5 - mu) / sigma)
    return upper - lower


def _scoring_artefact() -> calib.NbpCalibrationArtefact:
    return calib.NbpCalibrationArtefact(
        schema_version=calib.ARTEFACT_SCHEMA_VERSION,
        cdf_method="normal",
        recalibration="none",
        correction_form="none",
        delta=1.0,
        kappa=0.0,
        emos_params_by_version={"v5.0": (1.5, 0.0)},
        emos_draws_by_version={"v5.0": ((1.5, 0.0, 1.0),)},
        n_min=60,
        sigma_d=0.1,
        rung_probability_bounds={"mid": (0.3, 0.2, 0.4)},
        fit_status=calib.FIT_STATUS_OK,
    )


def test_known_non_half_probabilities_match_hand_computed_brier_and_reliability() -> None:
    """Identity-scale EMOS with a=1.5 must not collapse to the 0.5 placeholder."""
    percentiles = nbp_learning_nightly.Percentiles(
        q10=68.0, q25=70.0, q50=72.0, q75=74.0, q90=76.0, mean=72.0, sd=2.0
    )
    artefact = _scoring_artefact()
    rows = tuple(
        nbp_learning_nightly.score_learning_row(
            station="LAX",
            climate_day=dt.date(2026, 6, day),
            cli_tmax_f=cli,
            percentiles=percentiles,
            version="v5.0",
            txn_mean_f=70.0,
            xnd_sd_f=2.0,
            artefact=artefact,
            day_length_hours=12.0,
        )
        for day, cli in ((1, 72.0), (2, 80.0))
    )

    center_f = 72
    p_m2 = _mid_rung_probability(mu=72.0 + 1.5, sigma=2.0, center_f=center_f)
    p_m1 = _mid_rung_probability(mu=70.0, sigma=2.0, center_f=center_f)
    assert p_m2 != pytest.approx(0.5)
    assert p_m1 != pytest.approx(0.5)
    assert [row.p_m2 for row in rows] == pytest.approx([p_m2, p_m2])
    assert [row.p_m1 for row in rows] == pytest.approx([p_m1, p_m1])
    assert [row.outcome for row in rows] == [True, False]
    assert rows[0].residual_f == pytest.approx(72.0 - (72.0 + 1.5))

    metrics = nbp_learning_nightly.rolling_metrics(rows)
    brier_m2 = ((p_m2 - 1.0) ** 2 + (p_m2 - 0.0) ** 2) / 2.0
    brier_m1 = ((p_m1 - 1.0) ** 2 + (p_m1 - 0.0) ** 2) / 2.0
    reliability = (p_m2 - 0.5) ** 2
    assert metrics.n == 2
    assert metrics.brier_m2 == pytest.approx(brier_m2)
    assert metrics.brier_m1 == pytest.approx(brier_m1)
    assert metrics.reliability == pytest.approx(reliability)
    assert metrics.bss_vs_m1 == pytest.approx(1.0 - brier_m2 / brier_m1)


def test_month_at_or_above_plan_n_is_tested_without_an_explicit_month_flag() -> None:
    rows = tuple(
        _row(dt.date(2026, 3, day), residual_f=1.25)
        for day in range(1, 16)
        for _copy in range(4)
    )

    report = nbp_learning_nightly.residual_by_month(rows)

    assert len(rows) == 60
    assert [(item.month, item.n, item.status) for item in report] == [
        ("2026-03", 60, "TESTED")
    ]

    short_dates = tuple(
        _row(dt.date(2026, 4, day), residual_f=1.0)
        for day in range(1, 15)
        for _copy in range(5)
    )
    short = nbp_learning_nightly.residual_by_month(short_dates)
    assert short[0].n == 70
    assert short[0].status == "UNTESTED"


def test_missing_calibration_artefact_fails_loudly_and_skips_placeholder_metrics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="breezy.runtime.health")

    code = nbp_learning_nightly.main(
        [
            "--nbp-derived-root",
            (tmp_path / "nbp").as_posix(),
            "--settlement-truth",
            (tmp_path / "missing.parquet").as_posix(),
            "--learning-rows-jsonl",
            (tmp_path / "missing.jsonl").as_posix(),
        ],
        env={},
    )

    captured = capsys.readouterr()
    assert code != 0
    assert "NBP_ROLLING_METRICS" not in captured.out
    assert "NBP_RESIDUAL_MONTH" not in captured.out
    assert "nbp_nightly_missing_calibration_artefact" in caplog.text
