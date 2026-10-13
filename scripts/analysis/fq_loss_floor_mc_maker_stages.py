"""Stage runners for the maker S3 CLI: ``--sweep`` and ``--binding``.

Split from ``fq_loss_floor_mc_maker`` (300-line cap). The cell runners are injected (``Runners``)
so the CLI module stays the single place they are looked up and tests can substitute them.
Per-stage pins: sweep cells run at ``SWEEP_REPLICATES`` WITHOUT the outer SE; the early-stop
confirm cells and every binding/frozen-cell cell run at ``BINDING_REPLICATES`` WITH the outer
20 x 2000 (``run_final``: the borderline 50k re-run applies); report cells (theta 0.08 at f_pass)
and the horizon cell never trigger a re-run and never enter the verdict.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.analysis.fq_loss_floor_mc_maker_artifact import (
    assemble_artifact,
    early_stop_evaluation,
    freeze_blocked_cells,
)
from scripts.analysis.fq_loss_floor_mc_maker_inputs import (
    UNKNOWN_SHARE_BASIS,
    binding_cells,
    load_s1,
    load_s2,
    load_s5_cap_pin,
    mix_for,
)
from scripts.analysis.fq_loss_floor_mc_maker_templates import (
    BINDING_REPLICATES,
    OUTER_REPLICATES,
    OUTER_RESAMPLES,
    SEED,
    STRESS_THETA,
    SWEEP_REPLICATES,
    THETA_TAKER,
    MakerMix,
    design_effects,
    sweep_mixes,
)
from scripts.analysis.fq_loss_floor_mc_maker_verdict import evaluate_binding, sweep_early_stop

__all__ = ["Runners", "pinned_cell", "run_binding", "run_sweep", "write_json"]

_REPO = Path(__file__).resolve().parents[2]
_MAIN = Path(__file__).with_name("fq_loss_floor_mc_maker.py")

RunCell = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Runners:
    """The callables the stages drive; ``plain`` never re-runs borderline cells, ``final`` does."""

    plain: RunCell
    final: RunCell
    recheck: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]
    horizon: Callable[..., dict[str, Any]]
    apply_cap: Callable[[float], object]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_REPO, text=True).strip()


def write_json(path: Path, doc: Mapping[str, Any]) -> None:
    """Atomic write (tmp + rename) of the one ``--out`` file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _provenance(extra: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **extra,
        "git_head": _git("rev-parse", "HEAD"),
        "script_git_sha": _git("hash-object", str(_MAIN.resolve())),
        "git_tree_clean": _git("status", "--porcelain") == "",
    }


def pinned_cell(run: RunCell, mix: MakerMix, replicates: int, *, outer: bool) -> dict[str, Any]:
    """One cell at the pinned seed; ``outer`` adds the 20 x 2000 outer SE."""
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


def run_sweep(out: Path, runners: Runners) -> int:
    """30 context cells without the outer SE; all-veto triggers the six-cell confirm at 10k."""
    cells = [pinned_cell(runners.plain, m, SWEEP_REPLICATES, outer=False) for m in sweep_mixes()]
    confirmed: list[dict[str, Any]] = []

    def confirm(mix: MakerMix) -> dict[str, Any]:
        confirmed.append(pinned_cell(runners.final, mix, BINDING_REPLICATES, outer=True))
        return confirmed[-1]

    stop = sweep_early_stop(cells, confirm)
    blocked = freeze_blocked_cells(sweep_cells=cells, confirm_cells=confirmed)
    for entry in blocked:
        print(f"BUILDER-DEFECT freeze_blocked {entry}", flush=True)
    head = {"mode": "sweep", "seed": SEED, "replicates": SWEEP_REPLICATES}
    provenance = _provenance({})
    if stop:
        art = assemble_artifact(
            early_stop_evaluation(confirmed),
            early_stop=stop,
            sweep_cells=cells,
            provenance=provenance,
        )
        doc = {**head, **art, "confirm_cells": confirmed}
    else:
        doc = {
            **head,
            "verdict": None,
            "sweep_cells": cells,
            "confirm_cells": confirmed,
            "freeze_blocked_cells": blocked,
            "provenance": provenance,
        }
    write_json(out, doc)
    print(f"early_stop={stop['early_stop'] if stop else None}", flush=True)
    return 0


def _frozen_horizon(
    evaluation: Mapping[str, Any],
    kill: Sequence[Mapping[str, Any]],
    pin: Any,
    horizon: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    frozen_cell = evaluation["frozen_cell"]
    if frozen_cell is None:
        return None
    base = next(c for c in kill if (c["k"], c["b"]) == (frozen_cell["k"], frozen_cell["b"]))
    frozen = {
        "c": evaluation["frozen_c"],
        "t_min": evaluation["frozen_t_min"],
        "alpha_star": evaluation["frozen_alpha_star"],
    }
    return horizon(
        base,
        frozen,
        l_cap=pin.l_cap,
        holdout_start=pin.holdout_start.isoformat(),
        cap_date=pin.cap_date.isoformat(),
    )


def run_binding(args: argparse.Namespace, runners: Runners) -> int:
    """Inputs, 12 binding cells (+ frozen-c re-check), 6 report cells, horizon cell, artifact."""
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
        "unknown_share_all_rows": listing.unknown_share_all_rows,
        "unknown_share_basis": UNKNOWN_SHARE_BASIS,
        "s1_sha256": s1_sha,
        "s1_rows": listing.rows,
        "realised_bid_median": s2.b_median,
        "L_cap": pin.l_cap,
        "s5_cap_pin_sha256": pin.sha256,
        "fill_icc_s2_raw": s2.fill_icc_raw,
        **design_effects(s2.fill_icc),
    }
    print("\n".join(f"{key}={value}" for key, value in derived.items()), flush=True)
    if args.inputs_only:
        return 0
    runners.apply_cap(args.max_memory_gib)
    plan = binding_cells(s2, args.admitted_k)
    reps = BINDING_REPLICATES

    def at(cell_f: str, theta: float, run: RunCell) -> list[dict[str, Any]]:
        return [
            pinned_cell(run, mix_for(c, s2, f=getattr(c, cell_f), theta=theta), reps, outer=True)
            for c in plan
        ]

    kill = at("f_kill", THETA_TAKER, runners.final)
    low = at("f_pass", THETA_TAKER, runners.final)
    evaluation = evaluate_binding(
        kill, low, b_median=s2.b_median, k_admitted=args.admitted_k, recheck=runners.recheck
    )
    report = at("f_pass", STRESS_THETA, runners.plain)
    artifact = assemble_artifact(
        evaluation,
        report_cells=report,
        horizon=_frozen_horizon(evaluation, kill, pin, runners.horizon),
        provenance=_provenance({**derived, "s2_lines": dict(s2.lines)}),
    )
    write_json(args.out, artifact)
    print(f"verdict={artifact['verdict']}", flush=True)
    return 0
