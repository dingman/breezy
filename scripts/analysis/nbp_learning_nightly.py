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
    DEFAULT_SPLITS,
    FIT_STATUS_OK,
    FitNotConvergedError,
    NbpCalibrationArtefact,
    StationDayResidual,
    artefact_from_json_dict,
    artefact_sha256,
    crps_numerical,
    write_artefact,
)
from breezy.analysis.nbp_comparator_models import m1_rung_probabilities
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
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
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
HOLDOUT_START: Final[dt.date] = DEFAULT_SPLITS.holdout_start

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

LABEL_STATUS_FINAL: Final[str] = "FINAL"
LABEL_STATUS_PROVISIONAL: Final[str] = "PROVISIONAL"

NBP_STALE_CYCLE_ALERT_EVENT: Final[str] = "nbp_nightly_stale_cycle"
NBP_STALE_FINAL_LABEL_ALERT_EVENT: Final[str] = "nbp_nightly_stale_final_label"
NBP_DRIFT_ALERT_EVENT: Final[str] = "nbp_nightly_drift"
NBP_CALIBRATION_DRIFT_ALERT_EVENT: Final[str] = "nbp_nightly_calibration_drift"
_ALERT_SEVERITY: Final[str] = "WARN"
_ALERT_SITE: Final[str] = "global"
_TEST_POSITIVE_CONTROL: Final[str] = "TEST_POSITIVE_CONTROL"

# NBP TXN cycles used by this family are 01Z, 13Z and 19Z; the longest normal
# gap is 12h (01Z->13Z). 18h gives one missed/pending cycle's worth of slack
# while still alerting before a whole cadence day disappears.
NBP_STALE_CYCLE_AFTER: Final[dt.timedelta] = dt.timedelta(hours=18)

# Final CLI rows usually publish after the climate day has ended, with
# overnight local lag. 72h tolerates weekend/backfill latency but alerts
# before the learning loop can silently run for several nights on old labels.
FINAL_LABEL_STALE_AFTER: Final[dt.timedelta] = dt.timedelta(hours=72)

DRIFT_MEAN_RESIDUAL_THRESHOLD_F: Final[float] = 2.5
# A >0.75 degF average CRPS regression is larger than routine tenth-degree
# numerical jitter and large enough to matter before it can dominate rung edge.
DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F: Final[float] = 0.75


class HoldoutAuthorizationError(RuntimeError):
    """Post-holdout final labels were requested without the explicit flag."""


class PositiveControl(str, Enum):
    STALE_CYCLE = "stale-cycle"
    STALE_LABEL = "stale-label"
    DRIFT = "drift"
    CALIBRATION_DRIFT = "calibration-drift"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class LearningRow:
    station: str
    climate_day: dt.date
    label_status: str
    cli_tmax_f: float
    m2_median_f: float
    p_m2: float
    p_m1: float
    outcome: bool
    percentiles: Percentiles | None = None
    nbm_version: str = "v5.0"

    @property
    def residual_f(self) -> float:
        return self.cli_tmax_f - self.m2_median_f


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    newest_cycle: dt.datetime | None
    newest_final_label_day: dt.date | None
    stale_cycle: bool
    stale_label: bool


@dataclass(frozen=True, slots=True)
class DriftResult:
    n: int
    mean_residual_f: float | None
    shift_f: float | None
    drifted: bool
    calibration_crps_delta: float | None
    calibration_drifted: bool


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


def _instant_from_ns(ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ns / _NS_PER_SECOND, tz=dt.UTC)


def final_pre_holdout_rows(rows: Sequence[LearningRow]) -> tuple[LearningRow, ...]:
    return tuple(
        row
        for row in rows
        if row.label_status == LABEL_STATUS_FINAL and row.climate_day < HOLDOUT_START
    )


def newest_final_label_day(rows: Sequence[LearningRow]) -> dt.date | None:
    return max(
        (
            row.climate_day
            for row in rows
            if row.label_status == LABEL_STATUS_FINAL
        ),
        default=None,
    )


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
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    newest_cycle = max((_instant_from_ns(row.cycle_runtime_ns) for row in nbp_rows), default=None)
    newest_label_day = (
        max(final_label_days, default=None)
        if final_label_days is not None
        else newest_final_label_day(label_rows)
    )

    stale_cycle = newest_cycle is None or now - newest_cycle > NBP_STALE_CYCLE_AFTER
    stale_label = (
        newest_label_day is None
        or now - _label_freshness_instant(newest_label_day) > FINAL_LABEL_STALE_AFTER
    )

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


def _label_freshness_instant(day: dt.date) -> dt.datetime:
    next_utc_midnight = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)
    return next_utc_midnight


def check_drift(
    *,
    rows: Sequence[LearningRow],
    sink: AlertSink,
    frozen_mean_residual_f: float = 0.0,
    frozen_artefact: NbpCalibrationArtefact | None = None,
    positive_control: bool = False,
    calibration_positive_control: bool = False,
) -> DriftResult:
    final_rows = final_pre_holdout_rows(rows)
    if not final_rows and not positive_control and not calibration_positive_control:
        return DriftResult(
            n=0,
            mean_residual_f=None,
            shift_f=None,
            drifted=False,
            calibration_crps_delta=None,
            calibration_drifted=False,
        )
    mean_residual = (
        frozen_mean_residual_f + DRIFT_MEAN_RESIDUAL_THRESHOLD_F + 0.1
        if positive_control
        else statistics.fmean(row.residual_f for row in final_rows)
        if final_rows
        else None
    )
    shift = None if mean_residual is None else mean_residual - frozen_mean_residual_f
    drifted = shift is not None and abs(shift) > DRIFT_MEAN_RESIDUAL_THRESHOLD_F
    calibration_crps_delta = _calibration_crps_delta(final_rows, frozen_artefact=frozen_artefact)
    if calibration_positive_control:
        calibration_crps_delta = DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F + 0.1
    calibration_drifted = (
        calibration_crps_delta is not None
        and calibration_crps_delta > DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F
    )
    if drifted:
        _send_alarm(
            sink,
            event=NBP_DRIFT_ALERT_EVENT,
            detail="mean_residual_shift",
            positive_control=positive_control,
        )
    if calibration_drifted:
        _send_alarm(
            sink,
            event=NBP_CALIBRATION_DRIFT_ALERT_EVENT,
            detail="calibration_crps_delta",
            positive_control=calibration_positive_control,
        )
    return DriftResult(
        n=len(final_rows),
        mean_residual_f=mean_residual,
        shift_f=shift,
        drifted=drifted,
        calibration_crps_delta=calibration_crps_delta,
        calibration_drifted=calibration_drifted,
    )


def _calibration_crps_delta(
    rows: Sequence[LearningRow],
    *,
    frozen_artefact: NbpCalibrationArtefact | None,
) -> float | None:
    if frozen_artefact is None:
        return None
    if frozen_artefact.fit_status != FIT_STATUS_OK:
        raise FitNotConvergedError(
            f"frozen artefact refused: fit_status={frozen_artefact.fit_status!r}, not {FIT_STATUS_OK!r}"
        )
    method = CdfMethod(frozen_artefact.cdf_method)
    deltas: list[float] = []
    for row in rows:
        if row.percentiles is None:
            continue
        params = frozen_artefact.emos_params_by_version.get(row.nbm_version)
        if params is None:
            continue
        a, gamma = params
        base_cdf = build_cdf(method, row.percentiles)
        frozen_cdf = apply_emos(
            base_cdf,
            row.percentiles,
            EmosParams(a=a, gamma=gamma, delta=frozen_artefact.delta),
        )
        frozen_crps = crps_numerical(frozen_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        raw_crps = crps_numerical(base_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        deltas.append(frozen_crps - raw_crps)
    if not deltas:
        return None
    return statistics.fmean(deltas)


def residual_by_month(
    rows: Sequence[LearningRow], *, tested_months: set[int] | None = None
) -> tuple[MonthResidualReport, ...]:
    tested = tested_months or set()
    grouped: dict[str, list[float]] = {}
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
        month_numbers[key] = residual.month

    reports = []
    for key in sorted(grouped):
        reports.append(
            MonthResidualReport(
                month=key,
                n=len(grouped[key]),
                median_residual_f=float(statistics.median(grouped[key])),
                status="TESTED" if month_numbers[key] in tested else "UNTESTED",
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


def _learning_rows_from_labels(rows: Sequence[Any]) -> tuple[LearningRow, ...]:
    result = []
    for row in final_rows_for_gate(rows):
        if row.tmax_f is None:
            continue
        result.append(
            LearningRow(
                station=row.station,
                climate_day=row.climate_day,
                label_status=LABEL_STATUS_FINAL,
                cli_tmax_f=float(row.tmax_f),
                m2_median_f=float(row.tmax_f),
                p_m2=0.5,
                p_m1=0.5,
                outcome=True,
                percentiles=None,
            )
        )
    return tuple(result)


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
    nbp_rows = _load_nbp_rows(Path(args.nbp_derived_root))
    learning_rows = _load_learning_rows_jsonl(Path(args.learning_rows_jsonl))
    final_label_days: tuple[dt.date, ...] | None = None
    if not learning_rows:
        settlement_truth_path = Path(args.settlement_truth)
        final_label_days = _load_final_label_days(settlement_truth_path)
        learning_rows = _learning_rows_from_labels(
            _load_settlement_truth_rows(settlement_truth_path)
        )

    check_freshness(
        nbp_rows=nbp_rows,
        label_rows=learning_rows,
        final_label_days=final_label_days,
        now=now,
        sink=sink,
        positive_control=positive_control,
    )
    frozen_artefact = (
        _load_candidate_artefact(Path(args.frozen_artefact_json))
        if args.frozen_artefact_json
        else None
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
