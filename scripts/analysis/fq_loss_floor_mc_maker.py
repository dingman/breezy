"""MAKER S3 WP3: maker template builder and CLI for the A1 loss-floor reachability run.

Modes: ``--subset-benchmark``, ``--sweep``, ``--binding`` (needs ``--s2-artifact``,
``--s1-artifact``, ``--s5-cap-pin``; ``--inputs-only`` prints the derived inputs). Path
model and pins: ``..._templates``; inputs and their JSON schemas: ``..._inputs``; frozen
cell, verdict, early stop, horizon: ``..._verdict``; artifact: ``..._artifact``. Heavy runs
belong to WP4: run them under ``systemd-run`` with ``--out`` to scratch.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO), str(_REPO / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.memory_cap import apply_address_space_cap
from scripts.analysis.fq_loss_floor_mc_engine import run_floor
from scripts.analysis.fq_loss_floor_mc_gate import DEFAULT_FREEZE
from scripts.analysis.fq_loss_floor_mc_maker_artifact import (
    assemble_artifact,
    cell_summary,
    window_label,
)
from scripts.analysis.fq_loss_floor_mc_maker_bench import benchmark
from scripts.analysis.fq_loss_floor_mc_maker_inputs import (
    binding_cells,
    listing_rate_4stn,
    load_s1,
    load_s2,
    load_s5_cap_pin,
    mix_for,
)
from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    B_CAP,
    B_FLOOR,
    BINDING_REPLICATES,
    BORDERLINE_REPLICATES,
    BORDERLINE_SEED,
    DEFF_CEILING,
    FILL_ICC,
    MAKER_SPEC,
    MAX_RUNGS,
    N_TEMPLATE_DATES,
    OUTER_REPLICATES,
    OUTER_RESAMPLES,
    SEED,
    STRESS_THETA,
    SWEEP_REPLICATES,
    THETA_TAKER,
    MakerMix,
    MakerRefusal,
    build_maker_groups,
    maker_be,
    maker_floor_config,
    sweep_mixes,
)
from scripts.analysis.fq_loss_floor_mc_maker_verdict import (
    evaluate_binding,
    horizon_sensitivity,
    needs_borderline_rerun,
    recheck_cell,
    select_frozen_cell,
    sweep_early_stop,
    verdict,
)

__all__ = [
    "BINDING_REPLICATES",
    "BORDERLINE_REPLICATES",
    "BORDERLINE_SEED",
    "B_CAP",
    "B_FLOOR",
    "DEFAULT_FREEZE",
    "DEFF_CEILING",
    "FILL_ICC",
    "MAKER_SPEC",
    "MAX_RUNGS",
    "N_TEMPLATE_DATES",
    "OUTER_REPLICATES",
    "OUTER_RESAMPLES",
    "SEED",
    "STRESS_THETA",
    "SWEEP_REPLICATES",
    "MakerMix",
    "MakerRefusal",
    "assemble_artifact",
    "binding_cells",
    "build_maker_groups",
    "evaluate_binding",
    "horizon_sensitivity",
    "listing_rate_4stn",
    "load_s1",
    "load_s2",
    "load_s5_cap_pin",
    "main",
    "maker_be",
    "maker_floor_config",
    "needs_borderline_rerun",
    "recheck_cell",
    "run_cell",
    "run_cell_final",
    "select_frozen_cell",
    "sweep_early_stop",
    "sweep_mixes",
    "verdict",
    "window_label",
]


def run_cell(
    mix: MakerMix,
    *,
    replicates: int,
    outer_resamples: int,
    outer_replicates: int,
    seed: int,
    n_dates: int = N_TEMPLATE_DATES,
) -> dict[str, Any]:
    """One maker cell through ``run_floor(spec=MAKER_SPEC)``."""
    groups = build_maker_groups(mix, n_dates=n_dates, seed=seed)
    config = maker_floor_config(groups, mix)
    doc = run_floor(
        groups,
        replicates=replicates,
        seed=seed,
        config=config,
        outer_resamples=outer_resamples,
        outer_replicates=outer_replicates,
        spec=MAKER_SPEC,
    )
    return cell_summary(doc, mix, config, replicates=replicates, seed=seed, n_dates=n_dates)


def run_cell_final(mix: MakerMix, **kwargs: Any) -> dict[str, Any]:
    """``run_cell`` plus the borderline rule: one final 50,000-replicate re-run, seed 20261013."""
    cell = run_cell(mix, **kwargs)
    if needs_borderline_rerun(cell):
        pinned = {**kwargs, "replicates": BORDERLINE_REPLICATES, "seed": BORDERLINE_SEED}
        return {**run_cell(mix, **pinned), "borderline_rerun": True}
    return {**cell, "borderline_rerun": False}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MAKER S3 A1 loss-floor reachability.")
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--subset-benchmark", "--sweep", "--binding"):
        mode.add_argument(flag, action="store_true")
    for flag in ("--s2-artifact", "--s1-artifact", "--s5-cap-pin", "--out"):
        parser.add_argument(flag, type=Path, default=None)
    parser.add_argument("--admitted-k", type=int, choices=(1, 2), default=None)
    parser.add_argument("--inputs-only", action="store_true")
    parser.add_argument("--max-memory-gib", type=float, default=8.0)
    return parser


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_REPO, text=True).strip()


def _write(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _pinned(
    mix: MakerMix, replicates: int, *, final: bool = True, outer: bool = True
) -> dict[str, Any]:
    run = run_cell_final if final else run_cell
    cell = run(
        mix,
        replicates=replicates,
        outer_resamples=OUTER_RESAMPLES if outer else 0,
        outer_replicates=OUTER_REPLICATES if outer else 0,
        seed=SEED,
    )
    print(
        f"cell k={mix.rungs} b={mix.bid} f={mix.fill_rate} theta={mix.theta} "
        f"floor_mode={cell['floor_mode']} c={cell['c']}",
        flush=True,
    )
    return cell


def _sweep(out: Path) -> int:
    cells = [_pinned(mix, SWEEP_REPLICATES, final=False, outer=False) for mix in sweep_mixes()]
    stop = sweep_early_stop(cells, lambda mix: _pinned(mix, BINDING_REPLICATES))
    doc = {"mode": "sweep", "seed": SEED, "replicates": SWEEP_REPLICATES, "cells": cells}
    _write(out, {**doc, **(stop or {})})
    print(f"early_stop={stop['early_stop'] if stop else None}", flush=True)
    return 0


def _frozen_horizon(
    evaluation: Mapping[str, Any], kill: Sequence[Mapping[str, Any]], pin: Any
) -> Any:
    frozen_cell = evaluation["frozen_cell"]
    if frozen_cell is None:
        return None
    base = next(c for c in kill if (c["k"], c["b"]) == (frozen_cell["k"], frozen_cell["b"]))
    frozen = {
        "c": evaluation["frozen_c"],
        "t_min": evaluation["frozen_t_min"],
        "alpha_star": evaluation["frozen_alpha_star"],
    }
    return horizon_sensitivity(
        base,
        frozen,
        l_cap=pin.l_cap,
        holdout_start=pin.holdout_start.isoformat(),
        cap_date=pin.cap_date.isoformat(),
    )


def _binding(args: argparse.Namespace) -> int:
    s2 = load_s2(args.s2_artifact)
    listing, s1_sha = load_s1(args.s1_artifact)
    pin = load_s5_cap_pin(args.s5_cap_pin)
    derived = {
        "s2_verdict": s2.verdict,
        "s2_sha256": s2.sha256,
        "r_lo": s2.f_kill,
        "f_pass": s2.f_pass,
        "listing_rate_4stn": listing.listing_rate,
        "unknown_share": listing.unknown_share,
        "s1_sha256": s1_sha,
        "realised_bid_median": s2.b_median,
        "L_cap": pin.l_cap,
        "s5_cap_pin_sha256": pin.sha256,
    }
    print("\n".join(f"{key}={value}" for key, value in derived.items()), flush=True)
    if args.inputs_only:
        return 0
    apply_address_space_cap(args.max_memory_gib)
    plan = binding_cells(s2, args.admitted_k)
    reps = BINDING_REPLICATES
    kill = [_pinned(mix_for(c, s2, f=c.f_kill, theta=THETA_TAKER), reps) for c in plan]
    low = [_pinned(mix_for(c, s2, f=c.f_pass, theta=THETA_TAKER), reps) for c in plan]
    evaluation = evaluate_binding(kill, low, b_median=s2.b_median, k_admitted=args.admitted_k)
    report = [_pinned(mix_for(c, s2, f=c.f_pass, theta=STRESS_THETA), reps) for c in plan]
    provenance = {
        **derived,
        "git_head": _git("rev-parse", "HEAD"),
        "script_git_sha": _git("hash-object", str(Path(__file__).resolve())),
    }
    artifact = assemble_artifact(
        evaluation,
        report_cells=report,
        horizon=_frozen_horizon(evaluation, kill, pin),
        provenance=provenance,
    )
    _write(args.out, artifact)
    print(f"verdict={artifact['verdict']}", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.binding:
            needed = {
                "--s2-artifact": args.s2_artifact,
                "--s1-artifact": args.s1_artifact,
                "--s5-cap-pin": args.s5_cap_pin,
            }
            if not args.inputs_only:
                needed["--out"] = args.out
            missing = [flag for flag, value in needed.items() if value is None]
            if missing:
                print(f"binding mode requires {', '.join(missing)}", file=sys.stderr)
                return 2
            return _binding(args)
        apply_address_space_cap(args.max_memory_gib)
        if args.subset_benchmark:
            return benchmark(run_cell)
        if args.out is None:
            print("--sweep requires --out", file=sys.stderr)
            return 2
        return _sweep(args.out)
    except MakerRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
