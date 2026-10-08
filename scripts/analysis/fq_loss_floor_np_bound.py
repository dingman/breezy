"""Neyman–Pearson upper bound on G3 power (FQ-R8-2 Stage 0).

Read-only. Imports the floor MC's thinning, day cuts and likelihood. Does not
retype them. ``--subset-benchmark`` prints a full-run projection and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO), str(_REPO / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.memory_cap import apply_address_space_cap
from scripts.analysis.fq_loss_floor_mc import (
    _git,
    _load_pins,
    _project,
    _rss,
    _sha,
    _world,
)
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay
from scripts.analysis.fq_loss_floor_mc_engine import (
    MIXES,
    _partition,
    _seed,
    prepare_mix_groups,
)
from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    HORIZON,
    FloorConfig,
    epoch_grid,
    inclusive_days,
    keep_probability,
    rate_gate,
    t_low_count,
)
from scripts.analysis.fq_loss_floor_mc_report import ticking_share
from scripts.analysis.fq_loss_floor_mc_rows import (
    StationDay,
    exit_probability,
)
from scripts.analysis.fq_loss_floor_mc_sim import Simulation, simulate_family
from scripts.analysis.fq_loss_floor_np_stat import (
    ALPHA_NOMINAL,
    DELTA_H1,
    E_PROJ,
    POWER_SE_FORMULA,
    TIES_EXACT,
    InformationReport,
    bound_min_with_se,
    conditional_variance_table,
    count_summary,
    d1_decision,
    d1_point_decision,
    identity_at_recorded_carries,
    identity_evidence,
    information_identity,
    json_float,
    log_lr_totals,
    mean_conditional_information,
    np_power_report,
    realised_tick_counts,
    sqrt_boundary_rate,
)
from scripts.analysis.fq_mc_livedata import UnreachableTakeRate

__all__ = ["build_parser", "default_out", "main"]

_A1 = _REPO / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_A1.json"
_EVIDENCE = _REPO / "docs/evidence/f5/fq_loss_floor_mc_seed20261008.json"
_STAT = Path(__file__).resolve().parent / "fq_loss_floor_np_stat.py"
_BENCH = (8, 32)
_TIES = (
    f"{TIES_EXACT}. "
    "c is the smallest H0 value with P0(L > c) ≤ α. "
    "γ = (α·n0 − #{L0 > c}) / #{L0 == c}, clipped to [0, 1]. "
    "Power = P1(L > c) + γ·P1(L == c). A +inf ratio always rejects."
)
_MIXSET = ("M-pool", "M-yes", "M-no")


@dataclass(frozen=True, slots=True)
class _Prepared:
    config: FloorConfig
    pooled: dict[str, list[list[PreparedDay]]]
    cleaned: tuple[tuple[StationDay, ...], ...]
    p_gate: float
    gate_rate: float
    tick_share: float
    identity: InformationReport
    n_long: int


def default_out(seed: int) -> Path:
    return _REPO / "docs" / "evidence" / "f5" / f"fq_loss_floor_np_bound_seed{seed}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Neyman–Pearson upper bound on G3 power.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--replicates", type=int, default=10_000)
    parser.add_argument("--subset-benchmark", action="store_true")
    parser.add_argument("--max-memory-gib", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=None)
    data = Path.home() / ".local/share/breezy/kalshi"
    parser.add_argument("--candles", type=Path, default=data / "candles.jsonl")
    parser.add_argument("--markets-dir", type=Path, default=data)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_sha(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{path} is not a JSON object")
    sha = document.get("frozen_sha")
    if not isinstance(sha, str) or not sha or sha == "UNFROZEN":
        raise RuntimeError(f"{path} has no frozen_sha")
    return sha


def _diagnostics(path: Path) -> tuple[float, int]:
    document = json.loads(path.read_text(encoding="utf-8"))
    diagnostics = document["outcome"]["diagnostics"]
    return float(diagnostics["c"]), int(diagnostics["t_min"])


def _prepare(args: argparse.Namespace) -> _Prepared:
    if MIXES != _MIXSET:
        raise RuntimeError(f"MIXSET drift: {MIXES}")
    if DEFAULT_FREEZE != date(2026, 10, 8):
        raise RuntimeError(f"A1 freeze date drifted: {DEFAULT_FREEZE}")
    config, _cal, gate_groups, _refused = _world(args)
    cleaned, _rejected = _partition(gate_groups)
    pooled = {mix: prepare_mix_groups(cleaned, mix, s6=False) for mix in MIXES}
    for mix, groups in pooled.items():
        if not any(groups):
            raise RuntimeError(f"{mix} has no prepared station-days")
    gate_rate = rate_gate(config.lambda_pool, config.take_rate_lower)
    p_gate = keep_probability(gate_rate, r_sd=config.r_sd, lambda_sd=config.lambda_sd)
    preps = [prep for groups in pooled.values() for group in groups for prep in group]
    identity = information_identity(preps)
    return _Prepared(
        config=config,
        pooled=pooled,
        cleaned=cleaned,
        p_gate=p_gate,
        gate_rate=gate_rate,
        tick_share=ticking_share(cleaned),
        identity=identity,
        n_long=inclusive_days(DEFAULT_FREEZE, HORIZON),
    )


def _simulate(
    groups: Sequence[Sequence[PreparedDay]],
    *,
    replicates: int,
    n_days: int,
    p_keep: float,
    seed: int,
    row: str,
    delta: float | None,
    config: FloorConfig,
) -> Simulation:
    return simulate_family(
        groups,
        replicates=replicates,
        n_days=n_days,
        p_keep=p_keep,
        seed=seed,
        row=row,
        delta=delta,
        netting=True,
        p_exit=exit_probability(config.pool_exit_fraction),
        half_spread=config.half_spread,
        theta=config.theta,
        record_draws=True,
    )


def _family(prepared: _Prepared, mix: str, *, replicates: int, seed: int, row: str) -> Simulation:
    delta = None if row == "H0" else DELTA_H1
    return _simulate(
        prepared.pooled[mix],
        replicates=replicates,
        n_days=prepared.n_long,
        p_keep=prepared.p_gate,
        seed=_seed(seed, f"np-{row}|{mix}"),
        row=row,
        delta=delta,
        config=prepared.config,
    )


def _score_row(
    h0: Simulation,
    h1: Simulation,
    *,
    epoch: date,
    mix: str,
    n_days: int,
    t_low: int,
    t_k: int,
    c_binding: float,
    t_min: int,
    variances: Mapping[int, float] | None,
) -> dict[str, Any]:
    h0_lr = log_lr_totals(h0.draws, h0.cuts, n_days=n_days, t_k=t_k, delta=DELTA_H1)
    h1_lr = log_lr_totals(h1.draws, h1.cuts, n_days=n_days, t_k=t_k, delta=DELTA_H1)
    alpha_eff = sqrt_boundary_rate(
        h0.paths, h0.cuts, n_days=n_days, t_k=t_k, c=c_binding, t_min=t_min
    )
    nominal = np_power_report(h0_lr, h1_lr, ALPHA_NOMINAL)
    effective = np_power_report(h0_lr, h1_lr, alpha_eff)
    row: dict[str, Any] = {
        "epoch": epoch.isoformat(),
        "mix": mix,
        "n_days": n_days,
        "t_low": t_low,
        "t_K": t_k,
        "N_e": count_summary(realised_tick_counts(h0.cuts, n_days)),
        "alpha_eff": alpha_eff,
        "crit_alpha010": json_float(nominal.c),
        "crit_alpha_eff": json_float(effective.c),
        "gamma_alpha010": nominal.gamma,
        "gamma_alpha_eff": effective.gamma,
        "h0_tail_alpha010": nominal.h0_tail,
        "h0_tail_alpha_eff": effective.h0_tail,
        "np_bound_alpha010": nominal.power,
        "np_bound_alpha010_se": nominal.se,
        "np_bound_alpha_eff": effective.power,
        "np_bound_alpha_eff_se": effective.se,
        "ties_conservative": TIES_EXACT,
    }
    if variances is not None:
        row["I_t"] = mean_conditional_information(
            h0.draws, h0.cuts, n_days=n_days, t_k=t_k, variances=variances
        )
    return row


def _run(args: argparse.Namespace) -> dict[str, Any]:
    prepared = _prepare(args)
    c_binding, t_min = _diagnostics(_EVIDENCE)
    amendment, _parent = _load_pins()
    h0 = {
        mix: _family(prepared, mix, replicates=args.replicates, seed=args.seed, row="H0")
        for mix in MIXES
    }
    h1 = {
        mix: _family(prepared, mix, replicates=args.replicates, seed=args.seed, row="H1")
        for mix in MIXES
    }
    carried = identity_at_recorded_carries(
        tuple(path for family in (h0, h1) for mix in MIXES for path in family[mix].draws)
    )
    evidence = identity_evidence(prepared.identity, carried)
    variances = None
    if not evidence["information_identity_holds"]:
        preps = [prep for groups in prepared.pooled.values() for group in groups for prep in group]
        variances = conditional_variance_table(preps)
    rows: list[dict[str, Any]] = []
    config = prepared.config
    for epoch in epoch_grid(DEFAULT_FREEZE):
        n_days = inclusive_days(epoch, HORIZON)
        t_low = t_low_count(
            n_days, config.lambda_sd, prepared.p_gate, tick_share=prepared.tick_share
        )
        t_k = math.floor(0.8 * t_low)
        for mix in MIXES:
            rows.append(
                _score_row(
                    h0[mix],
                    h1[mix],
                    epoch=epoch,
                    mix=mix,
                    n_days=n_days,
                    t_low=t_low,
                    t_k=t_k,
                    c_binding=c_binding,
                    t_min=t_min,
                    variances=variances,
                )
            )
    bound_min, bound_se = bound_min_with_se(rows)
    cutoff, decision = d1_decision(bound_min, e_proj=E_PROJ, se=bound_se)
    point = d1_point_decision(bound_min, e_proj=E_PROJ)[1]
    document: dict[str, Any] = {
        "seed": args.seed,
        "replicates": args.replicates,
        "git_head": _git(["rev-parse", "HEAD"]),
        "script_blob_sha": _git(["hash-object", str(Path(__file__).resolve())]),
        "stat_blob_sha": _git(["hash-object", str(_STAT)]),
        "a0_sha": _sha(amendment),
        "a1_frozen_sha": _frozen_sha(_A1),
        "evidence_sha256": _sha256(_EVIDENCE),
        "MIXSET": list(MIXES),
        "e_proj": E_PROJ,
        "c_binding": c_binding,
        "t_min_binding": t_min,
        "rate_gate": prepared.gate_rate,
        "p_gate": prepared.p_gate,
        "ties_note": _TIES,
        "power_se_formula": POWER_SE_FORMULA,
        **evidence,
        "rows": rows,
        "bound_min": bound_min,
        "bound_min_se": bound_se,
        "np_reach_cutoff_e": cutoff,
        "d1": decision,
        "d1_point": point,
    }
    return document


def _benchmark(args: argparse.Namespace) -> int:
    started = time.monotonic()
    load_started = time.monotonic()
    prepared = _prepare(args)
    load_seconds = time.monotonic() - load_started
    timings: list[tuple[int, float]] = []
    rss_points: list[int] = []
    families = len(MIXES) * 2
    for size in _BENCH:
        tick = time.monotonic()
        for mix in MIXES:
            _family(prepared, mix, replicates=size, seed=args.seed, row="H0")
            _family(prepared, mix, replicates=size, seed=args.seed, row="H1")
        timings.append((size, time.monotonic() - tick))
        rss_points.append(_rss())
        print(
            f"benchmark_point replicates={size} families={families} "
            f"seconds={timings[-1][1]:.3f} rss_mib={rss_points[-1] / 1024**2:.1f}",
            flush=True,
        )
    (n_small, t_small), (n_large, t_large) = timings
    projected_sim = _project(t_small, n_small, t_large, n_large, args.replicates)
    rss_small, rss_large = rss_points
    rss_growth = rss_large - rss_small
    rss_slope = rss_growth / (n_large - n_small)
    projected_rss = (
        rss_large if rss_slope <= 0.0 else rss_small + rss_slope * (args.replicates - n_small)
    )
    projected = load_seconds + projected_sim
    print(
        "\n".join(
            [
                "subset_benchmark=1",
                "official_evidence_written=0",
                f"families={families}",
                f"load_seconds={load_seconds:.3f}",
                f"horizon_days={prepared.n_long}",
                f"p_gate={prepared.p_gate:.6f}",
                f"rate_gate={prepared.gate_rate:.6f}",
                f"information_identity_holds={int(prepared.identity['information_identity_holds'])}",
                f"full_replicates={args.replicates}",
                f"projected_full_seconds={projected:.1f}",
                f"projected_full_minutes={projected / 60:.2f}",
                f"rss_growth_mib={rss_growth / 1024**2:.1f}",
                f"measured_rss_mib={rss_large / 1024**2:.1f}",
                f"projected_rss_mib={projected_rss / 1024**2:.1f}",
                f"wall_seconds={time.monotonic() - started:.3f}",
            ]
        ),
        flush=True,
    )
    return 0


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    apply_address_space_cap(args.max_memory_gib)
    try:
        if args.subset_benchmark:
            return _benchmark(args)
        document = _run(args)
    except UnreachableTakeRate as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _write(args.out or default_out(args.seed), document)
    print(f"d1={document['d1']} e_proj={document['e_proj']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
