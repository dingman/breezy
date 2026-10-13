"""MAKER S3 WP3: maker template builder and CLI for the A1 loss-floor reachability run.

Modes: ``--subset-benchmark``, ``--sweep``, ``--binding`` (needs ``--s2-artifact``,
``--s1-artifact``, ``--s5-cap-pin``; ``--inputs-only`` prints the derived inputs). Path
model and pins: ``..._templates``; inputs and their JSON schemas: ``..._inputs``; frozen
cell, verdict, early stop, horizon: ``..._verdict``; artifact: ``..._artifact``. Heavy runs
belong to WP4: run them under ``systemd-run`` with ``--out`` to scratch.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
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
)
from scripts.analysis.fq_loss_floor_mc_maker_stages import Runners, run_binding, run_sweep
from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    B_CAP,
    B_FLOOR,
    BINDING_REPLICATES,
    BORDERLINE_REPLICATES,
    BORDERLINE_SEED,
    DEFF_CEILING,
    FILL_ICC,
    FILL_ICC_SD,
    MAKER_SPEC,
    MAX_RUNGS,
    N_TEMPLATE_DATES,
    OUTER_REPLICATES,
    OUTER_RESAMPLES,
    SEED,
    STRESS_THETA,
    SWEEP_REPLICATES,
    MakerMix,
    MakerRefusal,
    build_maker_groups,
    design_effects,
    maker_be,
    maker_floor_config,
    station_day_icc,
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
    "FILL_ICC_SD",
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
    "design_effects",
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
    "station_day_icc",
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


def _runners() -> Runners:
    """Looked up at call time, so the module-level names stay the single patch points."""
    return Runners(
        plain=run_cell,
        final=run_cell_final,
        recheck=recheck_cell,
        horizon=horizon_sensitivity,
        apply_cap=apply_address_space_cap,
    )


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
            return run_binding(args, _runners())
        apply_address_space_cap(args.max_memory_gib)
        if args.subset_benchmark:
            return benchmark(run_cell)
        if args.out is None:
            print("--sweep requires --out", file=sys.stderr)
            return 2
        return run_sweep(args.out, _runners())
    except MakerRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
