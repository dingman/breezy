"""F13 Phase A runner: scores the multi-source blend against the NBP champion, offline.

Plan: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md, "Phase A1 / A"
(r3.1, r3.2, R25, R35). The statistics live in ``breezy.analysis.multisource_blend``; this script is
the I/O and the freeze discipline around them.

It REFUSES to score unless every one of these holds, in this order, before any model is fitted:

1. the prereg's ``frozen_sha`` is a 40-hex commit that is an ancestor of HEAD (never ``UNFROZEN``)
   and the prereg file equals the blob committed there
   (``prereg_precommit_check.check_frozen_blob``);
2. no pin is null (floor multiple, tolerances, nu, ...): the coordinator pins them before any M1-M3
   scoring;
3. the prereg's frozen sha and content digest are RECORDED in ``<out>/prereg_record.json``; a run
   directory recorded under a different prereg is refused ("changed since");
4. C1 has measured the source lags for >= 14 days (``--c1-evidence``).

It then scores in two stages. Stage A fits only M0 (the champion, ``fit_calibration``) and M0';
the minimum-effect floor (multiple x the M0 fold-to-fold CRPS SD) is written to ``stage_a.json``
BEFORE M1-M3 are scored. Stage B scores M1-M3, the +60 min lag rerun and the shuffled-label
negative control. The prereg digest is re-checked just before the result is written.

Inputs are pre-assembled feature rows (JSONL of ``multisource_blend.feature_row_to_json``), built by
``assemble_feature_row``; a second file carries the same rows assembled with every source lag +60
min. Rows on or after 2026-07-01 are refused. The script never calls ``open_holdout``, opens no
network connection and writes only under ``--out-dir``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis import multisource_blend as msb
from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.strategy.ladder_ev.quantile_density import CdfMethod
from scripts.analysis.prereg_precommit_check import check_frozen_blob

__all__ = ["REQUIRED_PINS", "UNFROZEN", "Refusal", "main", "run"]

UNFROZEN: Final[str] = "UNFROZEN"
DEFAULT_MAX_MEMORY_GIB: Final[float] = 8.0
REQUIRED_PINS: Final[tuple[str, ...]] = (
    "floor_multiple",
    "m0_prime_tolerance_crps_f",
    "station_tolerance_crps_f",
    "leak_audit_spread_multiple",
    "student_t_nu",
    "sigma_floor_f",
    "weight_sum_lambda",
    "min_cell_rows",
    "bootstrap_n",
    "bootstrap_seed",
    "champion_cdf_method",
    "m0_bootstrap_draws",
    "source_breaks",
    "rung_edges_f",
    "min_uncensored_lag_samples",
)
RECORD_NAME: Final[str] = "prereg_record.json"


class Refusal(Exception):
    """The run is refused; nothing was scored (or nothing further is scored)."""


# ------------------------------------------------------------------ the freeze


def _canonical(design: Mapping[str, Any]) -> str:
    body = {k: v for k, v in design.items() if k != "frozen_sha"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(design: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(design).encode("utf-8")).hexdigest()


def load_verified_prereg(path: Path) -> Mapping[str, Any]:
    """The frozen, complete prereg, or a :class:`Refusal`."""
    try:
        design = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"cannot read the prereg {path}: {exc}") from exc
    if not isinstance(design, Mapping):
        raise Refusal(f"{path}: the prereg must be a JSON object")
    if design.get("frozen_sha") == UNFROZEN:
        raise Refusal(
            "frozen_sha is UNFROZEN: the draft prereg has not been frozen; nothing is scored"
        )
    defects = check_frozen_blob(path, design)
    if defects:
        raise Refusal("; ".join(f"[{d.code}] {d.message}" for d in defects))
    pins = design.get("pins")
    if not isinstance(pins, Mapping):
        raise Refusal("the prereg has no `pins` object")
    unpinned = [name for name in REQUIRED_PINS if pins.get(name) is None]
    if unpinned:
        raise Refusal(f"pin(s) still null, the coordinator pins them before scoring: {unpinned}")
    return design


def record_prereg(out_dir: Path, design: Mapping[str, Any]) -> None:
    """Record the frozen sha + content digest; refuse a directory recorded under another prereg."""
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {"frozen_sha": design["frozen_sha"], "content_sha256": _digest(design)}
    path = out_dir / RECORD_NAME
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous != record:
            raise Refusal(
                f"the prereg changed since this run directory was recorded ({previous} -> {record})"
            )
        return
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def _assert_prereg_unchanged(prereg: Path, design: Mapping[str, Any]) -> None:
    again = load_verified_prereg(prereg)
    if _digest(again) != _digest(design) or again["frozen_sha"] != design["frozen_sha"]:
        raise Refusal("the prereg changed while the run was scoring; the result is not written")


# ------------------------------------------------------------------ inputs


def _load_rows(path: Path) -> list[msb.FeatureRow]:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        rows = [msb.feature_row_from_json(json.loads(ln)) for ln in lines]
    except (OSError, ValueError, KeyError, TypeError, msb.NonFiniteInputError) as exc:
        raise Refusal(f"cannot load feature rows from {path}: {type(exc).__name__}: {exc}") from exc
    try:
        msb.assert_pre_holdout(rows)
        for row in rows:
            msb.assert_row_leakage_free(row)
    except (msb.HoldoutLeakError, msb.LeakageError) as exc:
        raise Refusal(str(exc)) from exc
    if not rows:
        raise Refusal(f"{path} holds no feature rows")
    return rows


def _check_c1(path: Path, design: Mapping[str, Any]) -> None:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        measured = {k: int(v) for k, v in evidence["measured_days"].items()}
        uncensored = {k: int(v) for k, v in evidence.get("uncensored", {}).items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Refusal(f"cannot read the C1 lag evidence {path}: {exc}") from exc
    try:
        msb.require_c1_measured_lags(
            measured,
            required=msb.LEVEL_SOURCES,
            min_days=int(design["fixed_by_plan"]["c1_min_measured_days"]),
            uncensored=uncensored,
            min_uncensored=int(design["pins"]["min_uncensored_lag_samples"]),
        )
    except msb.C1LagEvidenceError as exc:
        raise Refusal(str(exc)) from exc


def _settings(pins: Mapping[str, Any]) -> msb.BlendSettings:
    return msb.BlendSettings(
        nu=float(pins["student_t_nu"]),
        sigma_floor_f=float(pins["sigma_floor_f"]),
        weight_sum_lambda=float(pins["weight_sum_lambda"]),
        min_cell_rows=int(pins["min_cell_rows"]),
    )


# ------------------------------------------------------------------ scoring


def _summary_json(summary: msb.DeltaSummary) -> dict[str, Any]:
    return {"mean": summary.mean, "lb": summary.lb, "n_days": summary.n_days}


def _delta(
    scored: Sequence[msb.ScoredRow],
    first: str,
    second: str,
    pins: Mapping[str, Any],
    fixed: Mapping[str, Any],
) -> msb.DeltaSummary:
    return msb.delta_summary(
        msb.delta_by_day(scored, first, second),
        n_boot=int(pins["bootstrap_n"]),
        seed=int(pins["bootstrap_seed"]),
        mean_block=float(fixed["mean_block_days"]),
    )


def _score(
    rows: Sequence[msb.FeatureRow], plan: msb.FoldPlan, settings: msb.BlendSettings, **kwargs: Any
) -> list[msb.ScoredRow]:
    return msb.out_of_fold_scores(rows, plan, settings, **kwargs)


def run(
    *,
    prereg: Path,
    features: Path,
    lag_features: Path,
    c1_evidence: Path,
    out_dir: Path,
) -> dict[str, Any]:
    design = load_verified_prereg(prereg)
    pins, fixed = design["pins"], design["fixed_by_plan"]
    record_prereg(out_dir, design)
    _check_c1(c1_evidence, design)
    rows, lag_rows = _load_rows(features), _load_rows(lag_features)
    keys = {(r.station, r.climate_day, r.horizon) for r in rows}
    if keys != {(r.station, r.climate_day, r.horizon) for r in lag_rows}:
        raise Refusal("the +60 min lag feature file does not cover the same station-days")

    settings = _settings(pins)
    breaks = [dt.date.fromisoformat(d) for d in pins["source_breaks"]]
    plan = msb.build_folds(
        msb.days_by_version(rows),
        source_breaks=breaks,
        block_days=int(fixed["block_days"]),
        min_train_days=int(fixed["min_train_days"]),
        min_blocks=int(fixed["min_blocks"]),
    )
    if not plan.folds:
        raise Refusal(f"no version/segment qualifies for folds: {plan.excluded}")
    champion_kwargs: dict[str, Any] = {
        "m0_bootstrap_draws": int(pins["m0_bootstrap_draws"]),
        "champion_method": CdfMethod[str(pins["champion_cdf_method"])],
    }

    # Stage A: the champion and M0' only. The floor is committed before M1-M3 are scored.
    stage_a = _score(rows, plan, settings, levels=(0,), champion=True, **champion_kwargs)
    m0_fold = msb.fold_mean_crps(stage_a, "M0")
    floor = msb.minimum_effect_floor(list(m0_fold.values()), float(pins["floor_multiple"]))
    (out_dir / "stage_a.json").write_text(
        json.dumps(
            {
                "floor": floor,
                "floor_multiple": float(pins["floor_multiple"]),
                "m0_fold_sd": msb.fold_sd(list(m0_fold.values())),
                "m0_fold_crps": {str(k): v for k, v in m0_fold.items()},
                "prereg_frozen_sha": design["frozen_sha"],
                "m1_m3_scored": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    # Stage B: M1-M3, the lag rerun and the negative control.
    stage_b = _score(rows, plan, settings, levels=(1, 2, 3), champion=False)
    scored = msb.merge_scored(stage_a, stage_b)
    lag_scored = _score(lag_rows, plan, settings, levels=(0, 3), champion=False)
    shuffled = _score(
        msb.shuffle_labels(rows, seed=int(pins["bootstrap_seed"])),
        plan,
        settings,
        levels=(0, 3),
        champion=False,
    )

    m0p_m3 = _delta(scored, "M0prime", "M3", pins, fixed)
    m0_m3 = _delta(scored, "M0", "M3", pins, fixed)
    lag = _delta(lag_scored, "M0prime", "M3", pins, fixed)
    fold_means = msb.per_fold_delta(scored, "M0prime", "M3")
    stations = msb.per_station_delta(scored, "M0prime", "M3")
    status = msb.m0_prime_status(
        m0_crps=msb.mean_arm_crps(scored, "M0"),
        m0_prime_crps=msb.mean_arm_crps(scored, "M0prime"),
        tolerance=float(pins["m0_prime_tolerance_crps_f"]),
    )
    decision = msb.decide_acceptance(
        msb.AcceptanceInputs(
            m0p_vs_m3=m0p_m3,
            m0_vs_m3=m0_m3,
            fold_means_m0p_vs_m3=list(fold_means.values()),
            m0_fold_crps=list(m0_fold.values()),
            floor_multiple=float(pins["floor_multiple"]),
            leak_audit_multiple=float(pins["leak_audit_spread_multiple"]),
            m0p_minus_m0=status.difference,
            m0p_tolerance=float(pins["m0_prime_tolerance_crps_f"]),
            station_deltas=stations,
            station_tolerance=float(pins["station_tolerance_crps_f"]),
            lag_rerun=lag,
            lag_rows_lost=msb.lag_rows_lost(rows, lag_rows),
        )
    )
    edges = [int(e) for e in pins["rung_edges_f"]]
    result: dict[str, Any] = {
        "prereg_frozen_sha": design["frozen_sha"],
        "verdict": decision.verdict.value,
        "reasons": list(decision.reasons),
        "report": decision.report,
        "primary_comparison": "M3 vs M0prime",
        "floor": floor,
        "rows_scored": len(scored),
        "rows_input": len(rows),
        "folds": len(plan.folds),
        "folds_excluded": [list(item) for item in plan.excluded],
        "delta_m0p_m3": _summary_json(m0p_m3),
        "delta_m0_m3": _summary_json(m0_m3),
        "fold_means_m0p_m3": {str(k): v for k, v in fold_means.items()},
        "station_deltas": stations,
        "lag_rerun": {**_summary_json(lag), "rows_lost": msb.lag_rows_lost(rows, lag_rows)},
        "m0_prime_status": {
            "within_tolerance": status.within_tolerance,
            "difference": status.difference,
        },
        "ladder_mean_crps": {
            arm: msb.mean_arm_crps(scored, arm)
            for arm in ("M0", *msb.ARM_NAMES)
            if arm in scored[0].crps
        },
        "negative_control": {
            "abs_delta": abs(msb.mean_arm_difference(shuffled, "M0prime", "M3")),
            "mean_delta": msb.mean_arm_difference(shuffled, "M0prime", "M3"),
        },
        "diagnostics": {
            arm: msb.diagnostics(scored, arm=arm, nu=settings.nu, rung_edges=edges)
            for arm in ("M0prime", "M3")
        },
        "lamp_missingness": {
            h: {"n": m.n, "missing": m.missing, "share": m.share}
            for h, m in msb.lamp_missingness_by_horizon(rows).items()
        },
        "rmse_label": "descriptive_only",
    }
    _assert_prereg_unchanged(prereg, design)
    (out_dir / "oof_rows.jsonl").write_text(
        "\n".join(json.dumps(msb.scored_row_to_json(s)) for s in scored), encoding="utf-8"
    )
    (out_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--lag-features", type=Path, required=True)
    parser.add_argument("--c1-evidence", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-memory-gib", type=float, default=DEFAULT_MAX_MEMORY_GIB)
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    apply_address_space_cap(args.max_memory_gib)
    try:
        run(
            prereg=args.prereg,
            features=args.features,
            lag_features=args.lag_features,
            c1_evidence=args.c1_evidence,
            out_dir=args.out_dir,
        )
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
