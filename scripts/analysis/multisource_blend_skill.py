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
4. C1 has measured the source lags for >= 14 days (``--c1-evidence``), and every pinned
   ``source_lags_ns`` value is at least that source's C1 observed p99 (PIN-R6).

Freeze guards (PIN-R8): a prereg whose git history holds more than one commit with a non-UNFROZEN
``frozen_sha`` is refused as re-frozen; a sidecar stamped ``scoring: false`` (a builder
``--draft-scratch`` build) is refused. Every builder pin is a required pin (PIN-R9). The sidecars'
observed source breaks must all be pinned in ``source_breaks`` (PIN-R7). Amendments are made only in
a NEW file (``..._v2.json``) with an amendment record, frozen once on its own; both results are
reported. A prereg is never edited after its freeze.

It then scores in two stages. Stage A fits only M0 (the champion, ``fit_calibration``) and M0';
the minimum-effect floor (multiple x the M0 fold-to-fold CRPS SD) is written to ``stage_a.json``
BEFORE M1-M3 are scored. Stage B scores M1-M3, the +60 min lag rerun and the shuffled-label
negative control. The prereg digest is re-checked just before the result is written. The
out-of-fold rows are written with a header line carrying the prereg digest, which the descriptive
veto (``blend_veto_descriptive.py``) re-verifies.

Inputs are pre-assembled feature rows (JSONL of ``multisource_blend.feature_row_to_json``), built by
``assemble_feature_row``; a second file carries the same rows assembled with every source lag +60
min. Both files need the builder's sidecar, and the pair is cross-checked (anchor variant, anchors,
lags, routine minutes, prereg digest, lag shifts, row counts). The lag arm is compared with the
primary on the keys both hold (paired difference); a lost fraction above any of the pinned
``lag_arm_max_lost_fraction`` caps (overall, per horizon, per station) refuses the run. Rows on or
after 2026-07-01 are refused. The script never calls ``open_holdout``, opens no network
connection and writes only under ``--out-dir``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeGuard

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis import multisource_blend as msb
from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.analysis.multisource_blend_features import LAG_SHIFT_NS
from breezy.strategy.ladder_ev.quantile_density import CdfMethod
from scripts.analysis.multisource_blend_inputs_anchors import (
    check_row_anchors,
    check_sidecar_anchors_match_prereg,
)
from scripts.analysis.multisource_blend_inputs_pins import BuildRefusal, load_pins
from scripts.analysis.multisource_blend_lag_arm import (
    LagKeys,
    check_lag_caps,
    common_scored,
    lag_loss_report,
    paired_day_values,
    parse_lag_caps,
    split_lag_keys,
)
from scripts.analysis.multisource_blend_pin_guards import (
    check_breaks_pinned,
    check_not_refrozen,
    check_pinned_lags_cover_c1,
)
from scripts.analysis.multisource_blend_refusal import Refusal
from scripts.analysis.multisource_blend_sidecar import (
    ANCHOR_VARIANTS,
    PRIMARY_VARIANT,
    SIDECAR_SCHEMA,
    SIDECAR_SUFFIX,
    check_rows_not_excluded,
    check_sidecar,
    check_sidecar_lags_match_prereg,
    check_sidecar_pair,
    check_sidecar_row_count,
)
from scripts.analysis.prereg_precommit_check import check_frozen_blob

__all__ = [
    "LAG_SHIFT_NS",
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
    "check_row_anchors",
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
    "lag_arm_max_lost_fraction",
    # PIN-R9: every pin the builder reads is required, so a null refuses by name
    "anchors",
    "source_lags_ns",
    "obs_source",
    "obs_cadence_seconds",
    "obs_routine_minute_by_station",
    "obs_min_coverage_per_station_year",
    "obs_max_pin_minute_excluded_share",
)
RECORD_NAME: Final[str] = "prereg_record.json"
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
    try:
        parse_lag_caps(pins.get("lag_arm_max_lost_fraction"))
    except ValueError as exc:
        problems.append(str(exc))
    return problems


def _check_builder_pins(design: Mapping[str, Any]) -> list[str]:
    """The builder's own validation of the anchors, lags, obs and coverage pins (PIN-R9)."""
    try:
        load_pins(design)
    except BuildRefusal as exc:
        return [str(exc)]
    return []


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
    problems += _check_builder_pins(design)
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
    check_not_refrozen(path)
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


def _load_rows(path: Path, *, extra_lag_ns: int = 0) -> list[msb.FeatureRow]:
    """Load a feature file; ``extra_lag_ns`` is the lag twin's shift for the leak check (FB-R2)."""
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        rows = [msb.feature_row_from_json(json.loads(ln)) for ln in lines]
    except (OSError, ValueError, KeyError, TypeError, msb.NonFiniteInputError) as exc:
        raise Refusal(f"cannot load feature rows from {path}: {type(exc).__name__}: {exc}") from exc
    try:
        msb.assert_pre_holdout(rows)
        for row in rows:
            msb.assert_row_leakage_free(row, extra_lag_ns=extra_lag_ns)
    except (msb.HoldoutLeakError, msb.LeakageError) as exc:
        raise Refusal(str(exc)) from exc
    if not rows:
        raise Refusal(f"{path} holds no feature rows")
    return rows


def _check_sidecar(
    path: Path, design: Mapping[str, Any], *, role: str, variant: str = PRIMARY_VARIANT
) -> dict[str, Any]:
    """FB-R10/FB-R14: the builder's sidecar must exist, match the file and bind it to the prereg."""
    return check_sidecar(
        path, role=role, prereg_digest=content_digest(design), expected_variant=variant
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
            required=msb.C1_LAG_SOURCES,
            min_days=int(design["fixed_by_plan"]["c1_min_measured_days"]),
            uncensored=uncensored,
            min_uncensored=int(design["pins"]["min_uncensored_lag_samples"]),
        )
    except msb.C1LagEvidenceError as exc:
        raise Refusal(str(exc)) from exc
    check_pinned_lags_cover_c1(design["pins"]["source_lags_ns"], evidence.get("lag_samples_ns"))


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
    lag_keys: LagKeys

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


def _check_variant(anchor_variant: str) -> None:
    if anchor_variant not in ANCHOR_VARIANTS:
        raise Refusal(f"anchor_variant must be one of {ANCHOR_VARIANTS}, was {anchor_variant!r}")


def _check_lag_loss(keys: LagKeys, pins: Mapping[str, Any]) -> None:
    """PIN-R5: refuse on any exceeded cap; the measured loss never loosens one."""
    check_lag_caps(keys, parse_lag_caps(pins["lag_arm_max_lost_fraction"]))


def prepare_run(
    *,
    prereg: Path,
    features: Path,
    lag_features: Path,
    c1_evidence: Path,
    out_dir: Path,
    anchor_variant: str = PRIMARY_VARIANT,
) -> RunContext:
    """The freeze checks, the inputs and the fold plan; nothing is fitted here."""
    _check_variant(anchor_variant)
    design = load_verified_prereg(prereg)
    pins, fixed = design["pins"], design["fixed_by_plan"]
    record_prereg(out_dir, design)
    if (out_dir / STAGE_A_NAME).exists():
        raise Refusal(
            f"{out_dir / STAGE_A_NAME} already exists: the floor commitment is write-once; "
            "use a fresh --out-dir"
        )
    _check_c1(c1_evidence, design)
    meta = _check_sidecar(features, design, role="primary", variant=anchor_variant)
    lag_meta = _check_sidecar(lag_features, design, role="lag", variant=anchor_variant)
    check_sidecar_pair(meta, lag_meta)
    check_breaks_pinned(meta, pins["source_breaks"], features)
    check_breaks_pinned(lag_meta, pins["source_breaks"], lag_features)
    check_sidecar_anchors_match_prereg(meta, design, features)
    check_sidecar_anchors_match_prereg(lag_meta, design, lag_features)
    check_sidecar_lags_match_prereg(meta, design, features)
    check_sidecar_lags_match_prereg(lag_meta, design, lag_features)
    rows = _load_rows(features)
    lag_loaded = _load_rows(lag_features, extra_lag_ns=LAG_SHIFT_NS)
    check_row_anchors(rows, meta, features)
    check_rows_not_excluded(rows, meta, features)
    check_rows_not_excluded(lag_loaded, lag_meta, lag_features)
    check_row_anchors(lag_loaded, lag_meta, lag_features)
    check_sidecar_row_count(meta, features, len(rows))
    check_sidecar_row_count(lag_meta, lag_features, len(lag_loaded))
    keys = split_lag_keys(rows, lag_loaded)
    _check_lag_loss(keys, pins)
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
    return RunContext(design, out_dir, rows, lag_loaded, _settings(pins), plan, embargo, keys)


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


def _common_scored_or_refuse(
    b: StageB,
) -> tuple[list[msb.ScoredRow], list[msb.ScoredRow]]:
    primary, lag = common_scored(b.scored, b.lag_scored)
    if not primary:
        raise Refusal("the primary and lag arms scored no key in common; no paired comparison")
    return primary, lag


def _lag_section(
    ctx: RunContext,
    b: StageB,
    lag_delta: msb.DeltaSummary,
    primary_common: Sequence[msb.ScoredRow],
    lag_common: Sequence[msb.ScoredRow],
    rows_lost: Mapping[str, int],
) -> dict[str, Any]:
    """The lag arm: BOTH arms on the common keys, their paired difference, what was lost."""
    keys = ctx.lag_keys
    paired = msb.delta_summary(
        paired_day_values(primary_common, lag_common, "M0prime", "M3"),
        n_boot=int(ctx.pins["bootstrap_n"]),
        seed=int(ctx.pins["bootstrap_seed"]),
        mean_block=float(ctx.fixed["mean_block_days"]),
    )
    return {
        **_summary_json(lag_delta),
        "rows_lost": rows_lost,
        "keys_lost_by_horizon": _lost_counts_by_horizon(keys),
        "n_keys_common": len(keys.common),
        "n_keys_base": len(keys.base),
        "primary_on_common": _summary_json(_delta(primary_common, "M0prime", "M3", ctx)),
        "paired_difference": _summary_json(paired),
        "paired_difference_definition": "primary minus lag, day-block bootstrap",
        **lag_loss_report(ctx.rows, ctx.lag_rows, keys, b.scored),
    }


def _lost_counts_by_horizon(keys: LagKeys) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _station, _day, horizon in sorted(keys.lost):
        counts[horizon] = counts.get(horizon, 0) + 1
    return counts


def assemble_result(ctx: RunContext, a: StageA, b: StageB) -> dict[str, Any]:
    """The acceptance decision and every reported figure, from the two scored stages."""
    primary_common, lag_common = _common_scored_or_refuse(b)
    deltas = {
        "m0p_m3": _delta(b.scored, "M0prime", "M3", ctx),
        "m0_m3": _delta(b.scored, "M0", "M3", ctx),
        "lag": _delta(lag_common, "M0prime", "M3", ctx),
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
        "lag_rerun": _lag_section(ctx, b, deltas["lag"], primary_common, lag_common, lost),
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
    anchor_variant: str = PRIMARY_VARIANT,
) -> dict[str, Any]:
    ctx = prepare_run(
        prereg=prereg,
        features=features,
        lag_features=lag_features,
        c1_evidence=c1_evidence,
        out_dir=out_dir,
        anchor_variant=anchor_variant,
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
    parser.add_argument(
        "--anchor-variant",
        choices=ANCHOR_VARIANTS,
        default=PRIMARY_VARIANT,
        help="the feature-file pair to score; the 12 LST sensitivity is never the default",
    )
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
            anchor_variant=args.anchor_variant,
        )
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
