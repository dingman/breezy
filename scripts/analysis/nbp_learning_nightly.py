"""SL-15 nightly NBP learning loop and freshness heartbeat.

Weather-only analysis. This script reads local derived stores, emits alerts
through the shared ``alerts.env`` sink, and writes candidate calibration
artefacts only under the candidate directory. It never mutates a family
manifest and never opens post-holdout labels unless the coordinator flag is
passed explicitly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from settlement_truth_dataset import (  # type: ignore[import-not-found]
    final_rows_for_gate,
)

from breezy.analysis.brier_decomposition import bin_by_value, murphy_decomposition
from breezy.analysis.nbp_calibration import (
    FIT_STATUS_OK,
    G20_MONTH_MIN_DATES,
    G20_MONTH_N,
    FitNotConvergedError,
    NbpCalibrationArtefact,
    ProbabilityRecalibrationForm,
    ProbabilityRecalibrationSelection,
    StationDayResidual,
    apply_probability_recalibration,
    artefact_from_json_dict,
    artefact_sha256,
    parse_correction_form,
    write_artefact,
)
from breezy.analysis.nbp_comparator_models import m1_rung_probabilities
from breezy.analysis.nbp_drift import (
    DRIFT_MEAN_RESIDUAL_THRESHOLD_F,
    FINAL_LABEL_STALE_AFTER,
    HOLDOUT_START,
    LABEL_STATUS_FINAL,
    LABEL_STATUS_PROVISIONAL,
    NBP_STALE_CYCLE_AFTER,
    DriftResult,
    FreshnessResult,
    LearningRow,
    compute_freshness,
    drift_flags,
    final_pre_holdout_rows,
    instant_from_ns,
    newest_final_label_day,
)
from breezy.persistence.nbp_derived_store import (
    DerivedNbpRow,
    load_manifest,
    read_partition,
)
from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)
from breezy.strategy.ladder_ev.location_correction import correction_prediction_f
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probabilities,
)

__all__ = [
    "DEFAULT_CANDIDATE_ROOT",
    "DEFAULT_LABEL_PATH",
    "DEFAULT_LEARNING_ROWS_JSONL",
    "DEFAULT_NBP_DERIVED_ROOT",
    "DRIFT_MEAN_RESIDUAL_THRESHOLD_F",
    "FINAL_LABEL_STALE_AFTER",
    "HOLDOUT_START",
    "LABEL_STATUS_FINAL",
    "LABEL_STATUS_PROVISIONAL",
    "NBP_DRIFT_ALERT_EVENT",
    "NBP_STALE_CYCLE_AFTER",
    "NBP_STALE_CYCLE_ALERT_EVENT",
    "NBP_STALE_FINAL_LABEL_ALERT_EVENT",
    "NBP_CALIBRATION_DRIFT_ALERT_EVENT",
    "FreshnessResult",
    "HoldoutAuthorizationError",
    "LearningRow",
    "MonthResidualReport",
    "PositiveControl",
    "RollingMetrics",
    "check_drift",
    "check_freshness",
    "final_pre_holdout_rows",
    "final_rows_for_report",
    "main",
    "newest_final_label_day",
    "residual_by_month",
    "rolling_metrics",
    "send_alert",
    "write_candidate_artefact",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000

DEFAULT_NBP_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_LABEL_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_LEARNING_ROWS_JSONL: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/nbp_learning/learning_rows.jsonl"
)
DEFAULT_CANDIDATE_ROOT: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/nbp_calibration/candidates"
)
DEFAULT_ARCHIVE_ROOT: Final[Path] = Path.home() / ".local/share/breezy/archive"

NBP_STALE_CYCLE_ALERT_EVENT: Final[str] = "nbp_nightly_stale_cycle"
NBP_STALE_FINAL_LABEL_ALERT_EVENT: Final[str] = "nbp_nightly_stale_final_label"
NBP_DRIFT_ALERT_EVENT: Final[str] = "nbp_nightly_drift"
NBP_CALIBRATION_DRIFT_ALERT_EVENT: Final[str] = "nbp_nightly_calibration_drift"
NBP_MISSING_CALIBRATION_ARTEFACT_EVENT: Final[str] = "nbp_nightly_missing_calibration_artefact"
NBP_SCORING_FAILED_EVENT: Final[str] = "nbp_nightly_scoring_failed"
_ALERT_SEVERITY: Final[str] = "WARN"
_ALERT_SITE: Final[str] = "global"
_TEST_POSITIVE_CONTROL: Final[str] = "TEST_POSITIVE_CONTROL"


class HoldoutAuthorizationError(RuntimeError):
    """Post-holdout final labels were requested without the explicit flag."""


class PositiveControl(str, Enum):
    STALE_CYCLE = "stale-cycle"
    STALE_LABEL = "stale-label"
    DRIFT = "drift"
    CALIBRATION_DRIFT = "calibration-drift"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class MonthResidualReport:
    month: str
    n: int
    median_residual_f: float
    status: str


@dataclass(frozen=True, slots=True)
class RollingMetrics:
    n: int
    reliability: float | None
    brier_m2: float | None
    brier_m1: float | None
    bss_vs_m1: float | None


def send_alert(sink: AlertSink, *, event: str, detail: str) -> None:
    emit_alert(
        sink,
        AlertPayload(
            severity=_ALERT_SEVERITY,
            event=event,
            site=_ALERT_SITE,
            detail=detail,
        ),
    )


def _send_alarm(
    sink: AlertSink,
    *,
    event: str,
    detail: str,
    positive_control: bool = False,
) -> None:
    if positive_control:
        send_alert(
            sink,
            event=f"{_TEST_POSITIVE_CONTROL}_{event}",
            detail=f"{_TEST_POSITIVE_CONTROL} target_alarm={event} detail={detail}",
        )
        return
    send_alert(sink, event=event, detail=detail)


def final_rows_for_report(
    rows: Sequence[LearningRow],
    *,
    include_holdout: bool = False,
    holdout_authorized: bool = False,
) -> tuple[LearningRow, ...]:
    if include_holdout and not holdout_authorized:
        raise HoldoutAuthorizationError(
            "--include-holdout requires --coordinator-authorized; the holdout is sealed"
        )
    if include_holdout:
        return tuple(row for row in rows if row.label_status == LABEL_STATUS_FINAL)
    return final_pre_holdout_rows(rows)


def check_freshness(
    *,
    nbp_rows: Sequence[DerivedNbpRow],
    label_rows: Sequence[LearningRow],
    final_label_days: Sequence[dt.date] | None = None,
    now: dt.datetime,
    sink: AlertSink,
    positive_control: PositiveControl | None = None,
) -> FreshnessResult:
    newest_cycle = max((instant_from_ns(row.cycle_runtime_ns) for row in nbp_rows), default=None)
    newest_label_day = (
        max(final_label_days, default=None)
        if final_label_days is not None
        else newest_final_label_day(label_rows)
    )
    measured = compute_freshness(
        newest_cycle=newest_cycle, newest_label_day=newest_label_day, now=now
    )
    stale_cycle = measured.stale_cycle
    stale_label = measured.stale_label

    if positive_control in (PositiveControl.STALE_CYCLE, PositiveControl.ALL):
        stale_cycle = True
    if positive_control in (PositiveControl.STALE_LABEL, PositiveControl.ALL):
        stale_label = True

    if stale_cycle:
        _send_alarm(
            sink,
            event=NBP_STALE_CYCLE_ALERT_EVENT,
            detail="newest_nbp_cycle_stale",
            positive_control=positive_control in (PositiveControl.STALE_CYCLE, PositiveControl.ALL),
        )
    if stale_label:
        _send_alarm(
            sink,
            event=NBP_STALE_FINAL_LABEL_ALERT_EVENT,
            detail="newest_final_cli_label_stale",
            positive_control=positive_control in (PositiveControl.STALE_LABEL, PositiveControl.ALL),
        )
    return FreshnessResult(
        newest_cycle=newest_cycle,
        newest_final_label_day=newest_label_day,
        stale_cycle=stale_cycle,
        stale_label=stale_label,
    )


def check_drift(
    *,
    rows: Sequence[LearningRow],
    sink: AlertSink,
    frozen_mean_residual_f: float = 0.0,
    frozen_artefact: NbpCalibrationArtefact | None = None,
    positive_control: bool = False,
    calibration_positive_control: bool = False,
) -> DriftResult:
    result = drift_flags(
        rows=rows,
        frozen_mean_residual_f=frozen_mean_residual_f,
        frozen_artefact=frozen_artefact,
        positive_control=positive_control,
        calibration_positive_control=calibration_positive_control,
    )
    if result.drifted:
        _send_alarm(
            sink,
            event=NBP_DRIFT_ALERT_EVENT,
            detail="mean_residual_shift",
            positive_control=positive_control,
        )
    if result.calibration_drifted:
        _send_alarm(
            sink,
            event=NBP_CALIBRATION_DRIFT_ALERT_EVENT,
            detail="calibration_crps_delta",
            positive_control=calibration_positive_control,
        )
    return result


def _forecast_centered_ladder(center_f: int) -> tuple[Rung, ...]:
    """Same 3-rung partition as ``nbp_skill_study._forecast_centered_ladder``.

    Centered on the forecast Q50, never on the settled outcome.
    """
    return (
        Rung("lt", None, center_f - 1),
        Rung("mid", center_f, center_f + 1),
        Rung("gte", center_f + 2, None),
    )


def _location_correction_f(
    artefact: NbpCalibrationArtefact, *, month: int, day_length_hours: float
) -> float:
    offsets = {
        int(key): float(value) for key, value in artefact.correction_month_offsets.items()
    }
    return correction_prediction_f(
        parse_correction_form(artefact.correction_form),
        month=month,
        day_length_hours=day_length_hours,
        month_offsets=offsets,
        linear_coefficients=artefact.correction_linear_coefficients,
    )


def _recalibrated_probabilities(
    artefact: NbpCalibrationArtefact, probabilities: dict[str, float]
) -> dict[str, float]:
    selection = ProbabilityRecalibrationSelection(
        form=ProbabilityRecalibrationForm(artefact.recalibration),
        affine=artefact.recalibration_affine,
        isotonic_points=artefact.recalibration_isotonic_points,
    )
    return apply_probability_recalibration(selection, probabilities)


def frozen_m2_mid_probability(
    *,
    percentiles: Percentiles,
    version: str,
    artefact: NbpCalibrationArtefact,
    day_length_hours: float,
    climate_day: dt.date,
) -> tuple[float, float]:
    """Calibrated mid-rung probability and M2 median from a frozen artefact.

    Reuses EMOS (``apply_emos`` / ``build_cdf`` / ``rung_probabilities``) and
    the closed location correction (``correction_prediction_f``). The median
    is ``q50 + a + correction``, the post-correction location S2's residual
    uses. Returns ``(p_mid, median_f)``.
    """
    params = artefact.emos_params_by_version.get(version)
    if params is None:
        raise KeyError(f"frozen artefact has no EMOS params for NBM version {version!r}")
    location_f, gamma = params
    correction_f = _location_correction_f(
        artefact, month=climate_day.month, day_length_hours=day_length_hours
    )
    adjusted = EmosParams(
        a=location_f + correction_f, gamma=gamma, delta=artefact.delta
    )
    center_f = round(percentiles.q50)
    cdf = apply_emos(
        build_cdf(CdfMethod(artefact.cdf_method), percentiles),
        percentiles,
        adjusted,
    )
    probabilities = _recalibrated_probabilities(
        artefact, rung_probabilities(cdf, _forecast_centered_ladder(center_f))
    )
    return probabilities["mid"], percentiles.q50 + location_f + correction_f


def score_learning_row(
    *,
    station: str,
    climate_day: dt.date,
    cli_tmax_f: float,
    percentiles: Percentiles,
    version: str,
    txn_mean_f: float,
    xnd_sd_f: float,
    artefact: NbpCalibrationArtefact,
    day_length_hours: float,
) -> LearningRow:
    """One pre-holdout station-day scored with frozen M2 and NBS TXN+XND M1."""
    if climate_day >= HOLDOUT_START:
        raise HoldoutAuthorizationError(
            f"refusing to score holdout climate day {climate_day.isoformat()}"
        )
    p_m2, median_f = frozen_m2_mid_probability(
        percentiles=percentiles,
        version=version,
        artefact=artefact,
        day_length_hours=day_length_hours,
        climate_day=climate_day,
    )
    center_f = round(percentiles.q50)
    p_m1 = m1_rung_probabilities(
        txn_mean_f=txn_mean_f,
        xnd_sd_f=xnd_sd_f,
        rungs=_forecast_centered_ladder(center_f),
    )["mid"]
    return LearningRow(
        station=station,
        climate_day=climate_day,
        label_status=LABEL_STATUS_FINAL,
        cli_tmax_f=cli_tmax_f,
        m2_median_f=median_f,
        p_m2=p_m2,
        p_m1=p_m1,
        outcome=int(cli_tmax_f) in (center_f, center_f + 1),
        percentiles=percentiles,
        nbm_version=version,
    )


def scored_rows_from_artefact(
    *,
    artefact: NbpCalibrationArtefact,
    nbp_derived_root: Path,
    settlement_truth: Path,
    archive_root: Path,
) -> tuple[LearningRow, ...]:
    """Pre-holdout D+1 events scored with the frozen artefact and real M1.

    The join is the S2 comparator join (explicit D+1 window, final CLI only,
    holdout dropped before lookup). M1 is that join's NBS TXN+XND probability.
    M2 replaces the join's uncalibrated placeholder with ``frozen_m2_mid_probability``.
    """
    if artefact.fit_status != FIT_STATUS_OK:
        raise FitNotConvergedError(
            f"frozen artefact refused: fit_status={artefact.fit_status!r}, not {FIT_STATUS_OK!r}"
        )
    import nbp_skill_study as study  # type: ignore[import-not-found]

    registry = study.station_registry()
    settlement_rows = study.read_settlement_truth_rows(
        settlement_truth, climate_day_before=HOLDOUT_START
    )
    settlement_by_station_day = study._settlement_lookup(
        settlement_rows, holdout_start=HOLDOUT_START
    )
    windows: list[Any] = []
    for _path, partition in study.iter_nbp_derived_rows(nbp_derived_root):
        if partition is None:
            continue
        windows.extend(study.complete_percentile_windows(partition))
    mos_by_cycle = study.mos_txn_xnd_by_cycle(archive_root=archive_root, registry=registry)
    frozen_0b = study.load_frozen_0b_error_model(_REPO_ROOT / study.FROZEN_0B_ARTEFACT_RELPATH)
    events, _report = study.build_comparator_matched_events(
        windows,
        settlement_by_station_day,
        mos_by_cycle,
        {},
        frozen_0b,
        registry=registry,
    )
    scored: list[LearningRow] = []
    for event in events:
        climate_day = event.climate_day
        if not isinstance(climate_day, dt.date) or climate_day >= HOLDOUT_START:
            continue
        percentiles = event.percentiles
        if not isinstance(percentiles, Percentiles):
            raise TypeError("comparator event is missing NBP percentiles")
        station = str(event.station)
        version = str(event.version)
        p_m2, median_f = frozen_m2_mid_probability(
            percentiles=percentiles,
            version=version,
            artefact=artefact,
            day_length_hours=float(study._daylight_hours(station, climate_day)),
            climate_day=climate_day,
        )
        scored.append(
            LearningRow(
                station=station,
                climate_day=climate_day,
                label_status=LABEL_STATUS_FINAL,
                cli_tmax_f=float(event.cli_tmax_f),
                m2_median_f=median_f,
                p_m2=p_m2,
                p_m1=float(event.p_m1),
                outcome=bool(event.outcome),
                percentiles=percentiles,
                nbm_version=version,
            )
        )
    return tuple(scored)


def residual_by_month(
    rows: Sequence[LearningRow], *, tested_months: set[int] | None = None
) -> tuple[MonthResidualReport, ...]:
    tested = tested_months or set()
    grouped: dict[str, list[float]] = {}
    dates: dict[str, set[dt.date]] = {}
    month_numbers: dict[str, int] = {}
    residuals = tuple(
        StationDayResidual(
            station=row.station,
            climate_day=row.climate_day,
            residual_f=row.residual_f,
            day_length_hours=24.0,
        )
        for row in final_pre_holdout_rows(rows)
    )
    for residual in residuals:
        key = f"{residual.climate_day.year:04d}-{residual.climate_day.month:02d}"
        grouped.setdefault(key, []).append(residual.residual_f)
        dates.setdefault(key, set()).add(residual.climate_day)
        month_numbers[key] = residual.month

    reports = []
    for key in sorted(grouped):
        n = len(grouped[key])
        meets_plan_n = n >= G20_MONTH_N and len(dates[key]) >= G20_MONTH_MIN_DATES
        status = "TESTED" if month_numbers[key] in tested or meets_plan_n else "UNTESTED"
        reports.append(
            MonthResidualReport(
                month=key,
                n=n,
                median_residual_f=float(statistics.median(grouped[key])),
                status=status,
            )
        )
    return tuple(reports)


def rolling_metrics(rows: Sequence[LearningRow]) -> RollingMetrics:
    final_rows = final_pre_holdout_rows(rows)
    if not final_rows:
        return RollingMetrics(n=0, reliability=None, brier_m2=None, brier_m1=None, bss_vs_m1=None)
    probs_m2 = [row.p_m2 for row in final_rows]
    probs_m1 = [row.p_m1 for row in final_rows]
    outcomes = [row.outcome for row in final_rows]
    decomposition = murphy_decomposition(probs_m2, outcomes, bin_by_value)
    brier_m1 = statistics.fmean(
        (p - float(o)) ** 2 for p, o in zip(probs_m1, outcomes, strict=True)
    )
    bss = None if brier_m1 == 0.0 else 1.0 - decomposition.brier / brier_m1
    return RollingMetrics(
        n=len(final_rows),
        reliability=decomposition.reliability,
        brier_m2=decomposition.brier,
        brier_m1=brier_m1,
        bss_vs_m1=bss,
    )


def write_candidate_artefact(
    artefact: NbpCalibrationArtefact,
    *,
    candidate_root: Path = DEFAULT_CANDIDATE_ROOT,
    manifest_path: Path | None = None,
) -> Path:
    if artefact.fit_status != FIT_STATUS_OK:
        raise FitNotConvergedError(
            f"candidate artefact refused: fit_status={artefact.fit_status!r}, not {FIT_STATUS_OK!r}"
        )
    digest = artefact_sha256(artefact)
    resolved_candidate_root = _resolve_candidate_root(candidate_root)
    resolved_candidate_root.mkdir(parents=True, exist_ok=True)
    path = resolved_candidate_root / f"nbp_calibration_candidate_{digest}.json"
    if manifest_path is not None and path == manifest_path.expanduser().resolve():
        raise ValueError("candidate artefact path must not be the family manifest path")
    write_artefact(path, artefact)
    return path


def _resolve_candidate_root(candidate_root: Path) -> Path:
    resolved = candidate_root.expanduser().resolve()
    repo_root = _REPO_ROOT.resolve()
    if resolved.is_relative_to(repo_root):
        raise ValueError("candidate root must not be inside the repo")
    deploy_families = (repo_root / "deploy" / "families").resolve()
    if resolved.is_relative_to(deploy_families):
        raise ValueError("candidate root must not be inside deploy/families")
    allowed_root = (
        Path.home() / ".local/share/breezy/derived/nbp_calibration/candidates"
    ).resolve()
    if resolved != allowed_root and not resolved.is_relative_to(allowed_root):
        raise ValueError(f"candidate root must be under {allowed_root}")
    return resolved


def _load_nbp_rows(root: Path) -> tuple[DerivedNbpRow, ...]:
    rows: list[DerivedNbpRow] = []
    for entry in load_manifest(root).values():
        path = Path(entry.parquet_path)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            rows.extend(read_partition(path))
    return tuple(rows)


def _load_settlement_truth_rows(path: Path) -> tuple[Any, ...]:
    if not path.exists():
        return ()
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    table = pq.read_table(path, filters=pc.field("climate_day") < HOLDOUT_START)
    module = sys.modules[final_rows_for_gate.__module__]
    row_type: Any = module.__dict__["SettlementTruthRow"]
    return tuple(row_type(**record) for record in table.to_pylist())


def _load_final_label_days(path: Path) -> tuple[dt.date, ...]:
    if not path.exists():
        return ()
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["climate_day", "status"])
    days: list[dt.date] = []
    for record in table.to_pylist():
        if record["status"] != LABEL_STATUS_FINAL:
            continue
        value = record["climate_day"]
        days.append(value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)))
    return tuple(days)


def _load_learning_rows_jsonl(path: Path) -> tuple[LearningRow, ...]:
    if not path.exists():
        return ()
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"{path}:{line_number}: expected a JSON object")
        rows.append(_learning_row_from_payload(payload, source=f"{path}:{line_number}"))
    return tuple(rows)


def _learning_row_from_payload(payload: Mapping[str, Any], *, source: str) -> LearningRow:
    try:
        percentiles = _percentiles_from_payload(payload)
        return LearningRow(
            station=str(payload["station"]),
            climate_day=dt.date.fromisoformat(str(payload["climate_day"])),
            label_status=str(payload["label_status"]),
            cli_tmax_f=float(payload["cli_tmax_f"]),
            m2_median_f=_m2_median_from_payload(payload, percentiles=percentiles),
            p_m2=float(payload["p_m2"]),
            p_m1=_m1_probability_from_payload(payload),
            outcome=bool(payload["outcome"]),
            percentiles=percentiles,
            nbm_version=str(payload.get("nbm_version", payload.get("header_model_version", "v5.0"))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source}: malformed learning row: {exc}") from exc


def _m2_median_from_payload(
    payload: Mapping[str, Any], *, percentiles: Percentiles | None
) -> float:
    if "m2_median_f" in payload:
        return float(payload["m2_median_f"])
    if percentiles is not None:
        return percentiles.q50
    raise KeyError("m2_median_f")


def _percentiles_from_payload(payload: Mapping[str, Any]) -> Percentiles | None:
    keys = ("q10", "q25", "q50", "q75", "q90", "mean", "sd")
    if not all(key in payload for key in keys):
        return None
    return Percentiles(
        q10=float(payload["q10"]),
        q25=float(payload["q25"]),
        q50=float(payload["q50"]),
        q75=float(payload["q75"]),
        q90=float(payload["q90"]),
        mean=float(payload["mean"]),
        sd=float(payload["sd"]),
    )


def _m1_probability_from_payload(payload: Mapping[str, Any]) -> float:
    if "p_m1" in payload:
        return float(payload["p_m1"])
    rung = Rung(
        str(payload.get("rung_id", "event")),
        _optional_int(payload.get("rung_lower_f")),
        _optional_int(payload.get("rung_upper_f")),
    )
    probabilities = m1_rung_probabilities(
        txn_mean_f=float(payload["m1_txn_mean_f"]),
        xnd_sd_f=float(payload["m1_xnd_sd_f"]),
        rungs=(rung,),
    )
    return probabilities[rung.rung_id]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _load_candidate_artefact(path: Path) -> NbpCalibrationArtefact:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: artefact JSON must be an object")
    return artefact_from_json_dict(payload)


def _parse_positive_control(value: str | None) -> PositiveControl | None:
    if value is None:
        return None
    return PositiveControl(value)


def _parse_months(values: Sequence[str]) -> set[int]:
    months: set[int] = set()
    for value in values:
        month = int(value)
        if not 1 <= month <= 12:
            raise ValueError(f"month must be in 1..12, got {value!r}")
        months.add(month)
    return months


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nbp-derived-root", default=DEFAULT_NBP_DERIVED_ROOT.as_posix())
    parser.add_argument("--settlement-truth", default=DEFAULT_LABEL_PATH.as_posix())
    parser.add_argument("--learning-rows-jsonl", default=DEFAULT_LEARNING_ROWS_JSONL.as_posix())
    parser.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT.as_posix())
    parser.add_argument(
        "--calibration-artefact",
        help=(
            "Frozen NBP calibration artefact JSON. Required. "
            "Metrics are refused when it is omitted."
        ),
    )
    parser.add_argument("--candidate-artefact-json")
    parser.add_argument("--frozen-artefact-json")
    parser.add_argument("--candidate-root", default=DEFAULT_CANDIDATE_ROOT.as_posix())
    parser.add_argument("--manifest-path")
    parser.add_argument("--tested-month", action="append", default=[])
    parser.add_argument(
        "--include-holdout",
        action="store_true",
        help="report on post-holdout final rows; requires --coordinator-authorized",
    )
    parser.add_argument("--coordinator-authorized", action="store_true")
    parser.add_argument(
        "--positive-control",
        choices=[item.value for item in PositiveControl],
        help="inject stale heartbeat and/or drift alarms through the configured sender",
    )
    return parser


def _print_monthly_report(report: Sequence[MonthResidualReport]) -> None:
    for item in report:
        print(
            "NBP_RESIDUAL_MONTH "
            f"month={item.month} n={item.n} median_residual_f={item.median_residual_f:.3f} "
            f"status={item.status}"
        )


def _print_metrics(metrics: RollingMetrics) -> None:
    print(
        "NBP_ROLLING_METRICS "
        f"n={metrics.n} reliability={_fmt(metrics.reliability)} "
        f"brier_m2={_fmt(metrics.brier_m2)} brier_m1={_fmt(metrics.brier_m1)} "
        f"bss_vs_m1={_fmt(metrics.bss_vs_m1)}"
    )


def _fmt(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "NA"
    return f"{value:.6f}"


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    source_env: Mapping[str, str] = os.environ if env is None else env
    log_alert_egress_status(source_env, component="nbp_learning_nightly")
    sink = resolve_alert_sink(source_env)
    now = dt.datetime.now(dt.UTC)

    positive_control = _parse_positive_control(args.positive_control)
    if not args.calibration_artefact:
        send_alert(
            sink,
            event=NBP_MISSING_CALIBRATION_ARTEFACT_EVENT,
            detail="refusing placeholder metrics; pass --calibration-artefact",
        )
        return 1
    artefact_path = Path(args.calibration_artefact)
    if not artefact_path.is_file():
        send_alert(
            sink,
            event=NBP_MISSING_CALIBRATION_ARTEFACT_EVENT,
            detail=f"calibration artefact not found: {artefact_path}",
        )
        return 1
    try:
        artefact = _load_candidate_artefact(artefact_path)
    except (OSError, TypeError, KeyError, ValueError) as exc:
        send_alert(
            sink,
            event=NBP_MISSING_CALIBRATION_ARTEFACT_EVENT,
            detail=f"calibration artefact refused: {exc}",
        )
        return 1
    if artefact.fit_status != FIT_STATUS_OK:
        send_alert(
            sink,
            event=NBP_MISSING_CALIBRATION_ARTEFACT_EVENT,
            detail=(
                f"calibration artefact fit_status={artefact.fit_status!r}, "
                f"not {FIT_STATUS_OK!r}"
            ),
        )
        return 1

    nbp_rows = _load_nbp_rows(Path(args.nbp_derived_root))
    settlement_truth_path = Path(args.settlement_truth)
    final_label_days = _load_final_label_days(settlement_truth_path)
    check_freshness(
        nbp_rows=nbp_rows,
        label_rows=(),
        final_label_days=final_label_days,
        now=now,
        sink=sink,
        positive_control=positive_control,
    )
    try:
        learning_rows = scored_rows_from_artefact(
            artefact=artefact,
            nbp_derived_root=Path(args.nbp_derived_root),
            settlement_truth=settlement_truth_path,
            archive_root=Path(args.archive_root),
        )
    except (OSError, TypeError, KeyError, ValueError, FitNotConvergedError) as exc:
        send_alert(sink, event=NBP_SCORING_FAILED_EVENT, detail=str(exc))
        print(f"NBP_SCORING_FAILED {exc}", file=sys.stderr)
        return 1
    if not learning_rows:
        send_alert(
            sink,
            event=NBP_SCORING_FAILED_EVENT,
            detail="no pre-holdout rows scored from the frozen artefact",
        )
        return 1
    frozen_artefact = (
        _load_candidate_artefact(Path(args.frozen_artefact_json))
        if args.frozen_artefact_json
        else artefact
    )
    check_drift(
        rows=learning_rows,
        sink=sink,
        frozen_artefact=frozen_artefact,
        positive_control=positive_control in (PositiveControl.DRIFT, PositiveControl.ALL),
        calibration_positive_control=positive_control
        in (PositiveControl.CALIBRATION_DRIFT, PositiveControl.ALL),
    )
    report_rows = final_rows_for_report(
        learning_rows,
        include_holdout=bool(args.include_holdout),
        holdout_authorized=bool(args.coordinator_authorized),
    )
    _print_monthly_report(
        residual_by_month(report_rows, tested_months=_parse_months(args.tested_month))
    )
    _print_metrics(rolling_metrics(report_rows))

    if args.candidate_artefact_json:
        manifest_path = Path(args.manifest_path) if args.manifest_path else None
        candidate_path = write_candidate_artefact(
            _load_candidate_artefact(Path(args.candidate_artefact_json)),
            candidate_root=Path(args.candidate_root),
            manifest_path=manifest_path,
        )
        print(f"NBP_CANDIDATE_ARTEFACT path={candidate_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
