"""F13 Phase A runner: scores the multi-source blend against the NBP champion, offline.

Plan: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r3.md, "Phase A1 / A"
(r3.1, r3.2, R25, R35). The statistics live in ``breezy.analysis.multisource_blend``; this script is
the I/O and the freeze discipline around them.

It REFUSES to score unless every one of these holds, in this order, before any model is fitted:

1. the prereg's ``frozen_sha`` is a 40-hex commit that is an ancestor of HEAD (never ``UNFROZEN``)
   and the prereg file equals the blob committed there
   (``prereg_precommit_check.check_frozen_blob``);
2. no pin is null (floor multiple, tolerances, nu, embargo, ...): the coordinator pins them before
   any M1-M3 scoring; every pin and every ``fixed_by_plan`` value the run reads has the right type;
3. the prereg's frozen sha and content digest are RECORDED in ``<out>/prereg_record.json``; a run
   directory recorded under a different prereg is refused ("changed since"); a run directory that
   already holds ``stage_a.json`` is refused (the floor commitment is write-once);
4. C1 has measured the source lags for >= 14 days (``--c1-evidence``).

It then scores in two stages. Stage A fits only M0 (the champion, ``fit_calibration``) and M0';
the minimum-effect floor (multiple x the M0 fold-to-fold CRPS SD) is written to ``stage_a.json``
BEFORE M1-M3 are scored. Stage B scores M1-M3, the +60 min lag rerun and the shuffled-label
negative control. The prereg digest is re-checked just before the result is written. The
out-of-fold rows are written with a header line carrying the prereg digest, which the descriptive
veto (``blend_veto_descriptive.py``) re-verifies.

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
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, TypeGuard

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis import multisource_blend as msb
from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.strategy.ladder_ev.quantile_density import CdfMethod
from scripts.analysis.prereg_precommit_check import check_frozen_blob

__all__ = [
    "OOF_HEADER_KEY",
    "RECORD_NAME",
    "REQUIRED_PINS",
    "SIDECAR_SCHEMA",
    "SIDECAR_SUFFIX",
    "UNFROZEN",
    "Refusal",
    "RunContext",
    "StageA",
    "StageB",
    "assemble_result",
    "content_digest",
    "load_verified_prereg",
    "main",
    "prepare_run",
    "run",
    "run_stage_a",
    "run_stage_b",
    "write_stage_a",
]

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
    "embargo_days",
)
RECORD_NAME: Final[str] = "prereg_record.json"
#: FB-R10: ``<features>.manifest.json`` written by ``multisource_blend_features_build.py``. The
#: runner checks it whenever it is present; the feature files themselves stay header-free.
SIDECAR_SUFFIX: Final[str] = ".manifest.json"
SIDECAR_SCHEMA: Final[str] = "f13_features_manifest_v1"
#: FB-R6: the embargo must reach past the 1-day autocorrelation of a daily-max series.
MIN_EMBARGO_DAYS: Final[int] = 2
STAGE_A_NAME: Final[str] = "stage_a.json"
#: First line of ``oof_rows.jsonl``: ``{"header": {frozen_sha, content_sha256}}``.
OOF_HEADER_KEY: Final[str] = "header"
ARMS_WITH_LEVELS: Final[tuple[str, ...]] = ("M0prime", "M1", "M2", "M3")

# (key, minimum). ``int`` pins must be integers; ``number`` pins any finite real.
_FIXED_INTS: Final[tuple[tuple[str, int], ...]] = (
    ("block_days", 1),
    ("min_train_days", 1),
    ("min_blocks", 1),
    ("c1_min_measured_days", 1),
)
_FIXED_NUMBERS: Final[tuple[tuple[str, float], ...]] = (("mean_block_days", 1.0),)
_PIN_INTS: Final[tuple[tuple[str, int], ...]] = (
    ("min_cell_rows", 5),
    ("bootstrap_n", 1),
    ("bootstrap_seed", -(2**63)),
    ("m0_bootstrap_draws", 1),
    ("min_uncensored_lag_samples", 0),
    ("embargo_days", MIN_EMBARGO_DAYS),
)
_PIN_NUMBERS: Final[tuple[tuple[str, float], ...]] = (
    ("floor_multiple", 1e-12),
    ("m0_prime_tolerance_crps_f", 0.0),
    ("station_tolerance_crps_f", 0.0),
    ("leak_audit_spread_multiple", 1e-12),
    ("student_t_nu", 1e-12),
    ("sigma_floor_f", 1e-12),
    ("weight_sum_lambda", 0.0),
)


class Refusal(Exception):
    """The run is refused; nothing was scored (or nothing further is scored)."""


# ------------------------------------------------------------------ the freeze


def _canonical(design: Mapping[str, Any]) -> str:
    body = {k: v for k, v in design.items() if k != "frozen_sha"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_digest(design: Mapping[str, Any]) -> str:
    """SHA-256 of the prereg without its ``frozen_sha`` stamp."""
    return hashlib.sha256(_canonical(design).encode("utf-8")).hexdigest()


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _check_scalars(
    section: str,
    values: Mapping[str, Any],
    ints: Sequence[tuple[str, int]],
    numbers: Sequence[tuple[str, float]],
) -> list[str]:
    problems: list[str] = []
    for key, minimum in ints:
        value = values.get(key)
        if not _is_int(value) or value < minimum:
            problems.append(f"{section}.{key} must be an integer >= {minimum}, was {value!r}")
    for key, lowest in numbers:
        value = values.get(key)
        if not _is_number(value) or value < lowest:
            problems.append(f"{section}.{key} must be a finite number >= {lowest}, was {value!r}")
    return problems


def _check_collections(pins: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    if pins.get("champion_cdf_method") not in {m.name for m in CdfMethod}:
        problems.append(
            f"pins.champion_cdf_method must be one of {[m.name for m in CdfMethod]}, "
            f"was {pins.get('champion_cdf_method')!r}"
        )
    breaks = pins.get("source_breaks")
    try:
        if not isinstance(breaks, list):
            raise TypeError
        [dt.date.fromisoformat(item) for item in breaks]
    except (TypeError, ValueError):
        problems.append(f"pins.source_breaks must be a list of ISO dates, was {breaks!r}")
    edges = pins.get("rung_edges_f")
    if not isinstance(edges, list) or not edges or not all(_is_int(e) for e in edges):
        problems.append(f"pins.rung_edges_f must be a non-empty list of integers, was {edges!r}")
    return problems


def _check_values(design: Mapping[str, Any]) -> None:
    """Every value the run reads is present and well typed: a Refusal, never a traceback (P6)."""
    fixed, pins = design.get("fixed_by_plan"), design.get("pins")
    if not isinstance(fixed, Mapping):
        raise Refusal("the prereg has no `fixed_by_plan` object")
    if not isinstance(pins, Mapping):
        raise Refusal("the prereg has no `pins` object")
    problems = _check_scalars("fixed_by_plan", fixed, _FIXED_INTS, _FIXED_NUMBERS)
    problems += _check_scalars("pins", pins, _PIN_INTS, _PIN_NUMBERS)
    problems += _check_collections(pins)
    if problems:
        raise Refusal("; ".join(problems))


def load_verified_prereg(path: Path) -> Mapping[str, Any]:
    """The frozen, complete, well-typed prereg, or a :class:`Refusal`."""
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
    _check_values(design)
    return design


def record_prereg(out_dir: Path, design: Mapping[str, Any]) -> None:
    """Record the frozen sha + content digest; refuse a directory recorded under another prereg."""
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {"frozen_sha": design["frozen_sha"], "content_sha256": content_digest(design)}
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
    if (
        content_digest(again) != content_digest(design)
        or again["frozen_sha"] != design["frozen_sha"]
    ):
        raise Refusal("the prereg changed while the run was scoring; the result is not written")


def write_stage_a(out_dir: Path, payload: Mapping[str, Any]) -> None:
    """Write ``stage_a.json`` exclusively: the floor commitment is never overwritten (P7)."""
    path = out_dir / STAGE_A_NAME
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True))
    except FileExistsError as exc:
        raise Refusal(
            f"{path} already exists: the floor commitment is write-once; use a fresh --out-dir"
        ) from exc


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


def _check_sidecar(path: Path, design: Mapping[str, Any], *, role: str) -> None:
    """FB-R10: a feature file with a sidecar must match it (sha256 and prereg digest) or be refused.

    No sidecar means no check (hand-assembled inputs). A sidecar that exists but cannot be read,
    names another role or schema, or disagrees with the file or the prereg is a Refusal.
    """
    sidecar = Path(str(path) + SIDECAR_SUFFIX)
    if not sidecar.exists():
        return
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        schema, kind = meta["schema"], meta["role"]
        recorded_sha, recorded_digest = meta["features_sha256"], meta["prereg_content_sha256"]
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refusal(f"cannot read the sidecar {sidecar}: {type(exc).__name__}: {exc}") from exc
    if schema != SIDECAR_SCHEMA:
        raise Refusal(f"{sidecar}: schema {schema!r} is not {SIDECAR_SCHEMA!r}")
    if kind != role:
        raise Refusal(f"{sidecar}: role {kind!r} but {path} is loaded as the {role!r} file")
    if recorded_sha != actual_sha:
        raise Refusal(
            f"{path}: sha256 {actual_sha} does not match the sidecar's {recorded_sha}; the "
            "feature file changed since the builder wrote it"
        )
    if recorded_digest != content_digest(design):
        raise Refusal(
            f"{sidecar}: built under prereg digest {recorded_digest}, but this run's prereg "
            f"digest is {content_digest(design)}"
        )


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


# ------------------------------------------------------------------ the run, in stages


@dataclass(frozen=True, slots=True)
class RunContext:
    """Everything a stage needs, built once by :func:`prepare_run` before any model is fitted."""

    design: Mapping[str, Any]
    out_dir: Path
    rows: Sequence[msb.FeatureRow]
    lag_rows: Sequence[msb.FeatureRow]
    settings: msb.BlendSettings
    plan: msb.FoldPlan
    embargo_days: int
    lag_key_report: Mapping[str, Any] = field(default_factory=dict)

    @property
    def pins(self) -> Mapping[str, Any]:
        return self.design["pins"]  # type: ignore[no-any-return]

    @property
    def fixed(self) -> Mapping[str, Any]:
        return self.design["fixed_by_plan"]  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class StageA:
    scored: list[msb.ScoredRow]
    m0_fold_crps: dict[int, float]
    floor: float


@dataclass(frozen=True, slots=True)
class StageB:
    scored: list[msb.ScoredRow]  # stage A and B merged
    lag_scored: list[msb.ScoredRow]
    shuffled: list[msb.ScoredRow]


def _key(row: msb.FeatureRow) -> tuple[str, dt.date, str]:
    return (row.station, row.climate_day, row.horizon)


def _lag_key_intersection(
    rows: Sequence[msb.FeatureRow], lag_rows: Sequence[msb.FeatureRow]
) -> tuple[list[msb.FeatureRow], dict[str, Any]]:
    """FB-R2: the lag arm is scored on the keys both files hold; what was lost is reported.

    The +60 min shift can legitimately remove a row (a source no longer available before the
    anchor, an NBP cycle that drops out). Such a key is lost from the lag arm, counted per horizon,
    never a refusal; a lag row whose key the base file lacks is dropped and counted. Only a lag
    file with NO key in common is refused.
    """
    base_keys = {_key(r) for r in rows}
    lag_keys = {_key(r) for r in lag_rows}
    common = base_keys & lag_keys
    if not common:
        raise Refusal("the +60 min lag feature file has no station-day in common with the base")
    lost: dict[str, int] = {}
    for _station, _day, horizon in sorted(base_keys - lag_keys):
        lost[horizon] = lost.get(horizon, 0) + 1
    kept = [r for r in lag_rows if _key(r) in common]
    return kept, {
        "keys_lost_by_horizon": lost,
        "keys_extra_in_lag_dropped": len(lag_rows) - len(kept),
        "n_keys_common": len(common),
        "n_keys_base": len(base_keys),
    }


def prepare_run(
    *, prereg: Path, features: Path, lag_features: Path, c1_evidence: Path, out_dir: Path
) -> RunContext:
    """The freeze checks, the inputs and the fold plan; nothing is fitted here."""
    design = load_verified_prereg(prereg)
    pins, fixed = design["pins"], design["fixed_by_plan"]
    record_prereg(out_dir, design)
    if (out_dir / STAGE_A_NAME).exists():
        raise Refusal(
            f"{out_dir / STAGE_A_NAME} already exists: the floor commitment is write-once; "
            "use a fresh --out-dir"
        )
    _check_c1(c1_evidence, design)
    _check_sidecar(features, design, role="primary")
    _check_sidecar(lag_features, design, role="lag")
    rows, lag_loaded = _load_rows(features), _load_rows(lag_features)
    lag_rows, lag_key_report = _lag_key_intersection(rows, lag_loaded)
    embargo = int(pins["embargo_days"])
    plan = msb.build_folds(
        msb.days_by_version(rows),
        source_breaks=[dt.date.fromisoformat(d) for d in pins["source_breaks"]],
        block_days=int(fixed["block_days"]),
        min_train_days=int(fixed["min_train_days"]),
        min_blocks=int(fixed["min_blocks"]),
    )
    plan = msb.m0_eligible_plan(rows, plan, embargo_days=embargo)
    if not plan.folds:
        raise Refusal(f"no version/segment qualifies for folds (incl. M0 pool): {plan.excluded}")
    return RunContext(
        design, out_dir, rows, lag_rows, _settings(pins), plan, embargo, lag_key_report
    )


def _score(ctx: RunContext, rows: Sequence[msb.FeatureRow], **kwargs: Any) -> list[msb.ScoredRow]:
    return msb.out_of_fold_scores(
        rows, ctx.plan, ctx.settings, embargo_days=ctx.embargo_days, **kwargs
    )


def run_stage_a(ctx: RunContext) -> StageA:
    """The champion and M0' only; the floor is committed (write-once) before M1-M3 are scored."""
    pins = ctx.pins
    scored = _score(
        ctx,
        ctx.rows,
        levels=(0,),
        champion=True,
        m0_bootstrap_draws=int(pins["m0_bootstrap_draws"]),
        champion_method=CdfMethod[str(pins["champion_cdf_method"])],
    )
    m0_fold = msb.fold_mean_crps(scored, "M0")
    floor = msb.minimum_effect_floor(list(m0_fold.values()), float(pins["floor_multiple"]))
    write_stage_a(
        ctx.out_dir,
        {
            "floor": floor,
            "floor_multiple": float(pins["floor_multiple"]),
            "m0_fold_sd": msb.fold_sd(list(m0_fold.values())),
            "m0_fold_crps": {str(k): v for k, v in m0_fold.items()},
            "embargo_days": ctx.embargo_days,
            "prereg_frozen_sha": ctx.design["frozen_sha"],
            "m1_m3_scored": False,
        },
    )
    return StageA(scored, m0_fold, floor)


def run_stage_b(ctx: RunContext, stage_a: StageA) -> StageB:
    """M1-M3, the +60 min lag rerun and the shuffled-label negative control."""
    stage_b = _score(ctx, ctx.rows, levels=(1, 2, 3), champion=False)
    shuffled_rows = msb.shuffle_labels(ctx.rows, seed=int(ctx.pins["bootstrap_seed"]))
    return StageB(
        scored=msb.merge_scored(stage_a.scored, stage_b),
        lag_scored=_score(ctx, ctx.lag_rows, levels=(0, 3), champion=False),
        shuffled=_score(ctx, shuffled_rows, levels=(0, 3), champion=False),
    )


# ------------------------------------------------------------------ assembly


def _summary_json(summary: msb.DeltaSummary) -> dict[str, Any]:
    return {"mean": summary.mean, "lb": summary.lb, "n_days": summary.n_days}


def _delta(
    scored: Sequence[msb.ScoredRow], first: str, second: str, ctx: RunContext
) -> msb.DeltaSummary:
    return msb.delta_summary(
        msb.delta_by_day(scored, first, second),
        n_boot=int(ctx.pins["bootstrap_n"]),
        seed=int(ctx.pins["bootstrap_seed"]),
        mean_block=float(ctx.fixed["mean_block_days"]),
    )


def _decide(
    ctx: RunContext, a: StageA, b: StageB, deltas: Mapping[str, msb.DeltaSummary]
) -> tuple[msb.AcceptanceDecision, msb.M0PrimeStatus, dict[str, float]]:
    pins = ctx.pins
    stations = msb.per_station_delta(b.scored, "M0prime", "M3")
    status = msb.m0_prime_status(
        m0_crps=msb.mean_arm_crps(b.scored, "M0"),
        m0_prime_crps=msb.mean_arm_crps(b.scored, "M0prime"),
        tolerance=float(pins["m0_prime_tolerance_crps_f"]),
    )
    decision = msb.decide_acceptance(
        msb.AcceptanceInputs(
            m0p_vs_m3=deltas["m0p_m3"],
            m0_vs_m3=deltas["m0_m3"],
            fold_means_m0p_vs_m3=list(msb.per_fold_delta(b.scored, "M0prime", "M3").values()),
            m0_fold_crps=list(a.m0_fold_crps.values()),
            floor_multiple=float(pins["floor_multiple"]),
            leak_audit_multiple=float(pins["leak_audit_spread_multiple"]),
            m0p_minus_m0=status.difference,
            m0p_tolerance=float(pins["m0_prime_tolerance_crps_f"]),
            station_deltas=stations,
            station_tolerance=float(pins["station_tolerance_crps_f"]),
            lag_rerun=deltas["lag"],
            lag_rows_lost=msb.lag_rows_lost(ctx.rows, ctx.lag_rows),
            negative_control=deltas["negative_control"],
        )
    )
    return decision, status, stations


def _sensitivity_sections(scored: Sequence[msb.ScoredRow]) -> dict[str, Any]:
    """S1 / S3: reported, never gating."""
    m0, pooled = msb.mean_arm_crps(scored, "M0"), msb.mean_arm_crps(scored, "M0pooled")
    return {
        "pooled_m0_sensitivity": {
            "label": "sensitivity_only_never_gating",
            "mean_crps": pooled,
            "difference_vs_m0": pooled - m0,
        },
        "complete_case": msb.complete_case_delta(scored, "M0prime", "M3"),
        "level_counts": {arm: msb.level_counts(scored, arm) for arm in ARMS_WITH_LEVELS},
        "fit_fallbacks": {
            arm: sum(1 for s in scored if arm in s.fell_back) for arm in ARMS_WITH_LEVELS
        },
    }


def assemble_result(ctx: RunContext, a: StageA, b: StageB) -> dict[str, Any]:
    """The acceptance decision and every reported figure, from the two scored stages."""
    deltas = {
        "m0p_m3": _delta(b.scored, "M0prime", "M3", ctx),
        "m0_m3": _delta(b.scored, "M0", "M3", ctx),
        "lag": _delta(b.lag_scored, "M0prime", "M3", ctx),
        "negative_control": _delta(b.shuffled, "M0prime", "M3", ctx),
    }
    decision, status, stations = _decide(ctx, a, b, deltas)
    edges = [int(e) for e in ctx.pins["rung_edges_f"]]
    lost = msb.lag_rows_lost(ctx.rows, ctx.lag_rows)
    return {
        "prereg_frozen_sha": ctx.design["frozen_sha"],
        "verdict": decision.verdict.value,
        "reasons": list(decision.reasons),
        "report": decision.report,
        "primary_comparison": "M3 vs M0prime",
        "floor": a.floor,
        "embargo_days": ctx.embargo_days,
        "rows_scored": len(b.scored),
        "rows_input": len(ctx.rows),
        "folds": len(ctx.plan.folds),
        "folds_excluded": [list(item) for item in ctx.plan.excluded],
        "delta_m0p_m3": _summary_json(deltas["m0p_m3"]),
        "delta_m0_m3": _summary_json(deltas["m0_m3"]),
        "fold_means_m0p_m3": {
            str(k): v for k, v in msb.per_fold_delta(b.scored, "M0prime", "M3").items()
        },
        "station_deltas": stations,
        "lag_rerun": {**_summary_json(deltas["lag"]), "rows_lost": lost, **ctx.lag_key_report},
        "m0_prime_status": {
            "within_tolerance": status.within_tolerance,
            "difference": status.difference,
        },
        "ladder_mean_crps": {
            arm: msb.mean_arm_crps(b.scored, arm)
            for arm in ("M0", "M0pooled", *msb.ARM_NAMES)
            if arm in b.scored[0].crps
        },
        # S2: M0' vs M3 on shuffled labels; a positive lower bound already holds the verdict
        "negative_control": {
            **_summary_json(deltas["negative_control"]),
            "gate": "lb > 0 -> HELD_LEAK_AUDIT",
        },
        **_sensitivity_sections(b.scored),
        "diagnostics": {
            arm: msb.diagnostics(b.scored, arm=arm, nu=ctx.settings.nu, rung_edges=edges)
            for arm in ("M0prime", "M3")
        },
        "lamp_missingness": {
            h: {"n": m.n, "missing": m.missing, "share": m.share}
            for h, m in msb.lamp_missingness_by_horizon(ctx.rows).items()
        },
        "rmse_label": "descriptive_only",
    }


def _write_outputs(
    ctx: RunContext, prereg: Path, scored: Sequence[msb.ScoredRow], result: Mapping[str, Any]
) -> None:
    _assert_prereg_unchanged(prereg, ctx.design)
    header = {
        OOF_HEADER_KEY: {
            "frozen_sha": ctx.design["frozen_sha"],
            "content_sha256": content_digest(ctx.design),
            "schema": "f13_oof_rows_v1",
        }
    }
    lines = [json.dumps(header), *(json.dumps(msb.scored_row_to_json(s)) for s in scored)]
    (ctx.out_dir / "oof_rows.jsonl").write_text("\n".join(lines), encoding="utf-8")
    (ctx.out_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )


def run(
    *,
    prereg: Path,
    features: Path,
    lag_features: Path,
    c1_evidence: Path,
    out_dir: Path,
) -> dict[str, Any]:
    ctx = prepare_run(
        prereg=prereg,
        features=features,
        lag_features=lag_features,
        c1_evidence=c1_evidence,
        out_dir=out_dir,
    )
    stage_a = run_stage_a(ctx)
    stage_b = run_stage_b(ctx, stage_a)
    result = assemble_result(ctx, stage_a, stage_b)
    _write_outputs(ctx, prereg, stage_b.scored, result)
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
