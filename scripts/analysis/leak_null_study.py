"""Outcome-blind LEAK-NULL driver (r2 plus delta); never runs F13 stages.

Only null-label summaries are persisted. Torn or incompatible checkpoints refuse
resume; existing artifacts are never replaced. A copied design routes context
output to f13_context, or directly to the disposable probe directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import breezy.analysis.leak_null as ln
import breezy.analysis.leak_null_decide as dec
import breezy.analysis.multisource_blend as msb
from breezy.analysis.memory_cap import apply_address_space_cap
from scripts.analysis import leak_null_guards as g
from scripts.analysis import multisource_blend_skill as skill

if g.FROZEN_THRESHOLDS != g.record(dec.THRESHOLDS):
    raise RuntimeError("FROZEN_THRESHOLDS drifted from leak_null_decide.THRESHOLDS")

RESULT_KEYS = frozenset(
    (
        "prereg_sha256",
        "code_sha",
        "verdict",
        "reasons",
        "by_null",
        "positive_control",
        "invariant_defects",
        "f13_bias_adjusted",
        "limitations",
    )
)
LIMITATIONS = (
    "Nulls cannot detect a label-carrying feature or establish NBP availability.",
    "Temporal or embargo leaks beyond the independent fold checks remain outside scope.",
    "A common-mode own-day leak through M0prime cancels in the delta.",
    "Across-seed bounds share fixed features; N2 removes the penalty on both arms.",
    (
        "Non-score-affecting helpers outside the code pin: multisource_blend_pin_guards, "
        "multisource_blend_sidecar, multisource_blend_lag_arm, multisource_blend_inputs_*, "
        "prereg_precommit_check, memory_cap."
    ),
)


def _prepare_context(design: g.LeakNullDesign) -> skill.RunContext:
    paths = {}
    for role, spec in design.inputs.items():
        path = Path(spec["path"]).expanduser()
        paths[role] = path if path.is_absolute() else ROOT / path
    return skill.prepare_run(
        prereg=paths["f13_prereg"],
        features=paths["features"],
        lag_features=paths["lag_features"],
        c1_evidence=paths["c1_evidence"],
        out_dir=design.out_root,
    )


def _score(
    ctx: skill.RunContext, labels: ln.NullLabels, settings: msb.BlendSettings
) -> list[msb.ScoredRow]:
    if not isinstance(labels, ln.NullLabels) or labels.moved_fraction < 0.5:
        raise g.Refusal("scoring requires NullLabels with moved_fraction >= 0.5")
    return msb.out_of_fold_scores(
        labels.rows,
        ctx.plan,
        settings,
        levels=(0, 3),
        champion=False,
        embargo_days=ctx.embargo_days,
    )


def _json_value(value: Mapping[str, Any]) -> dict[str, Any]:
    record = json.loads(json.dumps(value, default=_date, allow_nan=False))
    if not isinstance(record, dict):
        raise TypeError("artifact must be a JSON object")
    return record


def _thresholds(design: g.LeakNullDesign) -> dec.Thresholds:
    values: dict[str, Any] = dict(design.thresholds)
    return dec.Thresholds(**values)


def _date(value: Any) -> str:
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)}")


def _write_once(path: Path, record: Mapping[str, Any]) -> None:
    payload = json.dumps(record, sort_keys=True, indent=2, default=_date, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        raise g.Refusal(f"cannot write exclusive artifact {path}: {exc}") from exc


def _summary(raw: Mapping[str, Any]) -> dec.SeedSummary:
    return dec.SeedSummary(
        seed=raw["seed"],
        null_id=raw["null_id"],
        mean=raw["mean"],
        lb=raw["lb"],
        n_days=raw["n_days"],
        by_horizon={h: msb.DeltaSummary(**v) for h, v in raw["by_horizon"].items()},
        by_m3_level={int(k): msb.DeltaSummary(**v) for k, v in raw["by_m3_level"].items()},
        day_values=tuple((dt.date.fromisoformat(d), v) for d, v in raw["day_values"]),
        failed=raw["failed"],
    )


def _pins(design: g.LeakNullDesign, seed: int) -> dict[str, Any]:
    return {"prereg_sha256": design.prereg_sha256, "code_sha": design.code_sha, "seed": seed}


def _check_record_shape(record: Mapping[str, Any], *, pc: bool) -> None:
    common = {"prereg_sha256", "code_sha", "seed", "defects"}
    fields = (
        {"summary", "plant_passed", "plant_present"}
        if pc
        else {
            "summaries",
            "moved_fraction",
            "invariants",
        }
    )
    if set(record) != common | fields:
        raise ValueError("checkpoint fields differ")
    if pc:
        if any(type(record[k]) is not int for k in ("plant_passed", "plant_present")):
            raise ValueError("plant counts must be integers")
        if not 0 <= record["plant_passed"] <= record["plant_present"]:
            raise ValueError("invalid plant counts")
        return
    invariants = record["invariants"]
    if not isinstance(invariants, dict) or set(invariants) != {
        "level0_max_abs",
        "m0prime_max_abs",
        "prefix_preserved",
        "scored_fold_defects",
    }:
        raise ValueError("incomplete invariants")
    if not 0.5 <= record["moved_fraction"] <= 1 or type(invariants["prefix_preserved"]) is not bool:
        raise ValueError("invalid permutation invariants")
    if any(set(invariants[k]) != set(ln.NullId) for k in ("level0_max_abs", "scored_fold_defects")):
        raise ValueError("missing per-null invariants")


def _read_record(path: Path, design: g.LeakNullDesign, seed: int, *, pc: bool) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ValueError("symlink checkpoint")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or any(
            record.get(k) != v for k, v in _pins(design, seed).items()
        ):
            raise ValueError("checkpoint provenance differs")
        _check_record_shape(record, pc=pc)
        records = {ln.NullId.N2: record["summary"]} if pc else record["summaries"]
        if set(records) != ({ln.NullId.N2} if pc else set(ln.NullId)):
            raise ValueError("checkpoint null IDs differ")
        for null_id, raw in records.items():
            summary = _summary(raw)
            if summary.seed != seed or summary.null_id != null_id:
                raise ValueError("checkpoint seed or null ID differs")
            if _json_value(g.record(summary)) != raw:
                raise ValueError("checkpoint summary fields differ")
            if summary.failed is None and (
                summary.mean is None
                or summary.lb is None
                or not math.isfinite(summary.mean)
                or not math.isfinite(summary.lb)
                or summary.n_days != len(summary.day_values)
                or summary.n_days <= 0
            ):
                raise ValueError("incomplete seed summary")
        if not isinstance(record["defects"], list) or any(
            not isinstance(d, str) for d in record["defects"]
        ):
            raise ValueError("invalid invariant defects")
        return _json_value(record)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise g.Refusal(f"torn or incompatible checkpoint {path}: {exc}") from exc


def _checkpoint(
    ctx: skill.RunContext,
    design: g.LeakNullDesign,
    seed: int,
    *,
    pc: bool,
    compute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    path = ctx.out_dir / "seeds" / f"{'pc' if pc else 'seed'}_{seed}.json"
    if path.exists() or path.is_symlink():
        return _read_record(path, design, seed, pc=pc)
    start = time.perf_counter()
    record = compute()
    _write_once(path, record)
    with (ctx.out_dir / "timing.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"seed": seed, "pc": pc, "wall_s": time.perf_counter() - start}) + "\n"
        )
    return record


def _evaluate(
    ctx: skill.RunContext,
    labels: ln.NullLabels,
    settings: msb.BlendSettings,
    seed: int,
    null_id: ln.NullId,
) -> tuple[dec.SeedSummary, list[msb.ScoredRow]]:
    try:
        scored = _score(ctx, labels, settings)
    except msb.FitNotConvergedError as exc:
        return dec.SeedSummary(seed, null_id, None, None, 0, {}, {}, (), str(exc)), []
    return dec.seed_summary(
        scored,
        seed=seed,
        null_id=null_id,
        n_boot=int(ctx.pins["bootstrap_n"]),
        boot_seed=ln.subseed(seed, f"boot:{null_id}"),
        mean_block=float(ctx.fixed["mean_block_days"]),
    ), scored


def _score_defects(
    scored: Sequence[msb.ScoredRow], ctx: skill.RunContext, tol: float
) -> tuple[list[str], float | None, list[str]]:
    """Return (all defects, finite level-0 max or None, fold-disjointness defects)."""
    fold_defects = list(ln.scored_fold_defects(scored, ctx.plan))
    defects = list(fold_defects)
    maximum = ln.level0_max_abs(scored)
    if maximum > tol:
        defects.append("level0_max_abs exceeds invariant tolerance")
    return defects, maximum if math.isfinite(maximum) else None, fold_defects


def run_seed(ctx: skill.RunContext, design: g.LeakNullDesign, seed: int) -> dict[str, Any]:
    labels = ln.null_label_rows(ctx.rows, seed)
    scrambled = ln.scramble_sources(labels, seed)
    summaries, scores, maxima, fold_defects = {}, {}, {}, {}
    defects: list[str] = []
    tol = float(design.thresholds["invariant_tol"])
    for null_id in ln.NullId:
        summary, scored = _evaluate(
            ctx,
            scrambled if null_id == ln.NullId.N3 else labels,
            ln.null_settings(ctx.settings, null_id),
            seed,
            null_id,
        )
        summaries[null_id] = g.record(summary)
        bad, maxima[null_id], fold_defects[null_id] = _score_defects(scored, ctx, tol)
        defects.extend(f"{null_id}: {d}" for d in bad)
        if null_id == ln.NullId.N2:
            del scored  # only N1 and N3 rows feed the M0prime comparison
        else:
            scores[null_id] = scored
    prefix = ln.prefix_preserved(labels.rows, scrambled.rows)
    if not prefix:
        defects.append("scramble changed prefix_level")
    comparison = None
    if summaries[ln.NullId.N1]["failed"] is None and summaries[ln.NullId.N3]["failed"] is None:
        maximum = ln.m0prime_max_abs(scores[ln.NullId.N3], scores[ln.NullId.N1])
        comparison = maximum if math.isfinite(maximum) else None
        if maximum > tol:
            defects.append("N3 M0prime differs from N1")
    return _json_value(
        {
            **_pins(design, seed),
            "summaries": summaries,
            "defects": defects,
            "moved_fraction": labels.moved_fraction,
            "invariants": {
                "level0_max_abs": maxima,
                "m0prime_max_abs": comparison,
                "prefix_preserved": prefix,
                "scored_fold_defects": fold_defects,
            },
        }
    )


def _pc_seed(ctx: skill.RunContext, design: g.LeakNullDesign, seed: int) -> dict[str, Any]:
    labels = ln.null_label_rows(ctx.rows, seed)
    planted = ln.plant_leak(
        labels, seed=seed, noise_sd_f=float(design.thresholds["plant_noise_sd_f"])
    )
    summary, scored = _evaluate(
        ctx, planted, ln.null_settings(ctx.settings, ln.NullId.N2), seed, ln.NullId.N2
    )
    defects, _, _ = _score_defects(scored, ctx, float(design.thresholds["invariant_tol"]))
    if not ln.prefix_preserved(labels.rows, planted.rows):
        defects.append("plant changed prefix_level")
    present = [r for r in planted.rows if not r.lamp.missing]
    passed = sum(
        r.lamp.rem_max_f is not None
        and (r.obs_so_far_f is None or r.lamp.rem_max_f > r.obs_so_far_f)
        for r in present
    )
    return _json_value(
        {
            **_pins(design, seed),
            "summary": g.record(summary),
            "defects": defects,
            "plant_present": len(present),
            "plant_passed": passed,
        }
    )


def run_pc(ctx: skill.RunContext, design: g.LeakNullDesign) -> list[dec.SeedSummary]:
    return [
        _summary(
            _checkpoint(ctx, design, seed, pc=True, compute=partial(_pc_seed, ctx, design, seed))[
                "summary"
            ]
        )
        for seed in design.pc_seeds
    ]


def _pc_records(ctx: skill.RunContext, design: g.LeakNullDesign) -> tuple[float | None, list[str]]:
    records = [
        _read_record(ctx.out_dir / "seeds" / f"pc_{s}.json", design, s, pc=True)
        for s in design.pc_seeds
    ]
    present = sum(r["plant_present"] for r in records)
    rate = sum(r["plant_passed"] for r in records) / present if present else None
    return rate, [f"PC: {d}" for r in records for d in r["defects"]]


def assemble_result(
    design: g.LeakNullDesign,
    by_null: Mapping[str, tuple[dec.SeedSummary, ...]],
    pc: Sequence[dec.SeedSummary],
    defects: Sequence[str],
    *,
    plant_mask_rate: float | None = None,
) -> dict[str, Any]:
    th = _thresholds(design)
    verdict, reasons = dec.decide(by_null, pc, defects, design.f13_record, th)
    bounds = {}
    for null_id, summaries in by_null.items():
        complete = [s for s in summaries if s.failed is None]
        bounds[null_id] = {
            "bound": g.record(dec.across_seed_bound(complete)) if complete else None,
            "seeds": [g.record(s) for s in summaries],
        }
    n1 = [s for s in by_null.get(ln.NullId.N1, ()) if s.failed is None]
    bias = (
        dec.f13_bias_adjusted(design.f13_record, dec.across_seed_bound(n1).m)
        if n1
        else {
            "adj_lb": None,
            "floor": design.f13_record["floor"],
            "floor_check": "unavailable" if design.f13_record["floor"] is None else "not_evaluated",
            "pass": False,
        }
    )
    fields = {
        "prereg_sha256": design.prereg_sha256,
        "code_sha": design.code_sha,
        "verdict": verdict,
        "reasons": reasons,
        "by_null": bounds,
        "positive_control": dec.pc_flagged(pc, th, plant_mask_rate=plant_mask_rate)[1],
        "invariant_defects": list(defects),
        "f13_bias_adjusted": bias,
        "limitations": LIMITATIONS,
    }
    return _json_value({key: fields[key] for key in RESULT_KEYS})


def run_study(ctx: skill.RunContext, design: g.LeakNullDesign, out: Path) -> dict[str, Any]:
    if design.frozen_sha == skill.UNFROZEN:
        raise g.Refusal("UNFROZEN is allowed only in the timing probe")
    g.assert_unchanged(out, design.prereg_path, design, ROOT)
    ctx = replace(ctx, out_dir=out)
    (out / "seeds").mkdir(parents=True, exist_ok=True)
    defects = list(ln.fold_disjointness_defects(ctx.rows, ctx.plan, ctx.embargo_days))
    by_null: dict[str, tuple[dec.SeedSummary, ...]] = {n: () for n in ln.NullId}
    pc: list[dec.SeedSummary] = []
    rate = None
    if not defects:
        pc = run_pc(ctx, design)
        rate, pc_defects = _pc_records(ctx, design)
        defects.extend(pc_defects)
        flagged, _ = dec.pc_flagged(pc, _thresholds(design), plant_mask_rate=rate)
        if flagged and not defects:
            for seed in design.seeds:
                record = _checkpoint(
                    ctx, design, seed, pc=False, compute=partial(run_seed, ctx, design, seed)
                )
                defects.extend(record["defects"])
                for null_id in ln.NullId:
                    by_null[null_id] += (_summary(record["summaries"][null_id]),)
    result = assemble_result(design, by_null, pc, defects, plant_mask_rate=rate)
    g.assert_unchanged(out, design.prereg_path, design, ROOT)
    _write_once(out / "leak_null_result.json", result)
    return result


def run_probe(design: g.LeakNullDesign, probe_parent: Path) -> str:
    parent = g.guard_probe_parent(probe_parent, design.out_root)
    tmp = Path(tempfile.mkdtemp(dir=parent))
    try:
        ctx = _prepare_context(replace(design, out_root=tmp))
        count = len(ctx.plan.folds)
        if not count:
            raise g.Refusal("timing probe needs at least one fold")
        fold = max(ctx.plan.folds, key=lambda f: len(f.train_days))
        ctx = replace(ctx, plan=replace(ctx.plan, folds=(fold,)))
        labels = ln.null_label_rows(ctx.rows, design.probe_seed)
        scrambled = ln.scramble_sources(labels, design.probe_seed)
        durations = []
        for null_id in ln.NullId:
            start = time.perf_counter()
            _score(
                ctx,
                scrambled if null_id == ln.NullId.N3 else labels,
                ln.null_settings(ctx.settings, null_id),
            )
            durations.append(time.perf_counter() - start)
        a, b, c = durations
        line = (
            f"folds={count} n1_s={a} n2_s={b} n3_s={c} "
            f"projected_seed_s={(a + b + c) * count} projected_pc_s={5 * b * count}"
        )
        print(line)
        return line
    finally:
        shutil.rmtree(tmp)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--max-memory-gib", type=float, default=3.5)
    parser.add_argument("--timing-probe", action="store_true")
    parser.add_argument("--probe-parent", type=Path)
    args = parser.parse_args(argv)
    try:
        design = g.load_leak_prereg(args.prereg, allow_unfrozen=args.timing_probe)
        out = g.guard_out_dir(args.out_dir or design.out_root, design.out_root)
        shas = g.verify_inputs(design)
        for note in g.check_code_pin(ROOT, design.code_sha, design.pinned_blobs) or ():
            print(f"LEAK-NULL note: {note}", file=sys.stderr)
        if args.timing_probe:
            if args.probe_parent is None:
                raise g.Refusal("--timing-probe requires --probe-parent")
            g.guard_probe_parent(args.probe_parent, design.out_root)
            apply_address_space_cap(args.max_memory_gib)
            run_probe(design, args.probe_parent)
        else:
            g.record_provenance(out, design, shas)
            apply_address_space_cap(args.max_memory_gib)
            ctx = _prepare_context(replace(design, out_root=out / "f13_context"))
            run_study(ctx, design, out)
        return 0
    except (g.Refusal, ln.Refusal) as exc:
        print(f"LEAK-NULL refusal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
