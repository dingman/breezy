"""F6 loss-stop floor Monte Carlo (r3 §4.5–§4.6).

``--subset-benchmark`` times one family and prints a full-run projection.
It does not write evidence. The coordinator launches the seeded run.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO), str(_REPO / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.memory_cap import apply_address_space_cap
from scripts.analysis.fq_kill_power_report import mc_pool_days
from scripts.analysis.fq_loss_floor_mc_engine import (
    MIXES,
    PATH_FAMILIES,
    prepare_mix_groups,
    run_floor,
)
from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    HORIZON,
    FloorConfig,
    inclusive_days,
    keep_probability,
    rate_cal,
)
from scripts.analysis.fq_loss_floor_mc_rates import plan_floor_rates
from scripts.analysis.fq_loss_floor_mc_rows import (
    Leg,
    StationDay,
    estimate_rho,
    exit_probability,
    make_leg,
    make_station_day,
    partition_station_days,
    rho_bind,
    rung_temperature,
)
from scripts.analysis.fq_loss_floor_mc_sim import simulate_family
from scripts.analysis.fq_mc_livedata import (
    DayTemplate,
    LoadStats,
    PoolDay,
    PoolRung,
    TakeRecord,
    UnreachableTakeRate,
    group_days,
    load_pool,
)
from scripts.analysis.prereg_amendment_check import load_verified_amendment
from scripts.analysis.prereg_precommit_check import load_design

__all__ = ["build_parser", "default_out", "exit_code", "main"]

_AMENDMENT_ID = "F5_prereg_v2_A0_kill"
_A0 = _REPO / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_A0.json"
_DATA = Path.home() / ".local/share/breezy/kalshi"
_BENCH = (8, 32)


def default_out(seed: int) -> Path:
    return _REPO / "docs" / "evidence" / "f5" / f"fq_loss_floor_mc_seed{seed}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="F6 loss-stop floor Monte Carlo.")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--replicates", type=int, default=10_000)
    parser.add_argument("--outer-resamples", type=int, default=20)
    parser.add_argument("--outer-replicates", type=int, default=2000)
    parser.add_argument("--subset-benchmark", action="store_true")
    parser.add_argument("--max-memory-gib", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--alpha", type=float, default=None)
    parser.add_argument("--candles", type=Path, default=_DATA / "candles.jsonl")
    parser.add_argument("--markets-dir", type=Path, default=_DATA)
    return parser


def _git(args: Sequence[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=_REPO, text=True).strip()


def _number(doc: Mapping[str, Any], key: str) -> float:
    value = doc[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number, got {value!r}")
    return float(value)


def _sha(doc: Mapping[str, Any], key: str = "frozen_sha") -> str:
    value = doc[key]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} must be a non-empty string")
    return value


def _load_pins() -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    amendment = load_verified_amendment(_A0, _AMENDMENT_ID)
    amends = amendment.get("amends")
    if not isinstance(amends, Mapping):
        raise TypeError("A0 amends is missing")
    parent_rel = amends.get("path")
    if not isinstance(parent_rel, str):
        raise TypeError("A0 amends.path is missing")
    parent = load_design(_REPO / parent_rel)
    if _sha(parent) != _sha(amends):
        raise RuntimeError("parent frozen_sha does not match A0 amends.frozen_sha")
    return amendment, parent


def _half_spread(days: Sequence[PoolDay]) -> float | None:
    spreads = [
        (rung.yes_ask - rung.yes_bid) / 2.0
        for day in days
        for _station, rungs in day.stations
        for rung in rungs
        if rung.yes_bid is not None and rung.yes_ask > rung.yes_bid
    ]
    if not spreads:
        return None
    spreads.sort()
    return spreads[len(spreads) // 2]


def _pit(rungs: Sequence[PoolRung]) -> float | None:
    ordered = sorted(rungs, key=lambda rung: rung_temperature(rung.rung_id))
    winners = [rung for rung in ordered if rung.result is True]
    if len(winners) != 1:
        return None
    winner = winners[0]
    cdf = 0.0
    for rung in ordered:
        mass = min(1.0, max(0.0, rung.yes_ask))
        if rung.rung_id == winner.rung_id:
            return min(1.0, max(0.0, cdf + 0.5 * mass))
        cdf += mass
    return None


def _rho_hat(days: Sequence[PoolDay]) -> float | None:
    pits: list[list[float]] = []
    for day in days:
        station_pits = [pit for _station, rungs in day.stations if (pit := _pit(rungs)) is not None]
        if len(station_pits) >= 2:
            pits.append(station_pits)
    return estimate_rho(pits)


def _groups(templates: Sequence[DayTemplate]) -> tuple[tuple[StationDay, ...], ...]:
    groups: list[tuple[StationDay, ...]] = []
    for template in templates:
        by_station: dict[str, list[Leg]] = {}
        for take in template.takes:
            by_station.setdefault(take.station, []).append(_leg(take))
        groups.append(
            tuple(make_station_day(station, legs) for station, legs in sorted(by_station.items()))
        )
    return tuple(groups)


def _leg(take: TakeRecord) -> Leg:
    return make_leg(take.rung_id, take.side, take.be, price=take.ask, half_spread=take.half_spread)


def exit_code(document: Mapping[str, Any]) -> int:
    """1 when a non-spec outcome blocked the freeze. A spec veto still exits 0."""
    outcome = document.get("outcome")
    if isinstance(outcome, dict) and outcome.get("freeze_blocked"):
        return 1
    return 0


def _world(
    args: argparse.Namespace,
) -> tuple[
    FloorConfig, tuple[tuple[StationDay, ...], ...], tuple[tuple[StationDay, ...], ...], int
]:
    _amendment, parent = _load_pins()
    if not args.candles.is_file():
        raise FileNotFoundError(f"candles file not found: {args.candles}")
    stats = LoadStats()
    rows = load_pool(args.candles, markets_dir=args.markets_dir, stats=stats)
    days = group_days(rows)
    if not days:
        raise RuntimeError("the pre-holdout pool has no climate days")
    rng = np.random.default_rng(args.seed)
    chosen = rng.choice(len(days), size=min(mc_pool_days(), len(days)), replace=False)
    sampled = [days[int(index)] for index in sorted(int(i) for i in np.asarray(chosen).tolist())]
    target = _number(parent, "take_rate_lower")
    planned = plan_floor_rates(sampled, take_rate_lower=target, seed=args.seed)
    cal_groups = _groups(planned.cal_templates)
    gate_groups = _groups(planned.gate_templates)
    config = FloorConfig(
        take_rate_lower=target,
        theta=_number(parent, "theta"),
        lambda_pool=planned.lambda_pool,
        r_sd=planned.r_sd_gate,
        lambda_sd=planned.lambda_sd_gate,
        half_spread=_half_spread(sampled),
        pool_exit_fraction=0.0,
        rho_hat=_rho_hat(sampled),
        freeze=DEFAULT_FREEZE,
        horizon=HORIZON,
        achieved_rate_cal=planned.achieved_rate_cal,
        achieved_rate_gate=planned.achieved_rate_gate,
        r_sd_cal=planned.r_sd_cal,
        lambda_sd_cal=planned.lambda_sd_cal,
    )
    refused = len(refused_of(cal_groups)) + len(refused_of(gate_groups))
    return config, cal_groups, gate_groups, refused


def refused_of(groups: Sequence[Sequence[StationDay]]) -> tuple[object, ...]:
    refused: list[object] = []
    for group in groups:
        for day in group:
            _admitted, rejected = partition_station_days((day,))
            refused.extend(rejected)
    return tuple(refused)


def _project(t_small: float, n_small: int, t_large: float, n_large: int, n_full: int) -> float:
    if n_large == n_small:
        return t_large * (n_full / n_large)
    slope = (t_large - t_small) / (n_large - n_small)
    if slope <= 0.0:
        return t_large * (n_full / n_large)
    return t_small - slope * n_small + slope * n_full


def _rss() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _timed_cells() -> tuple[tuple[str, str, str, bool], ...]:
    """Binding cells, plus one mix of S1, S2 and S6. The last flag selects the S6 filter."""
    binding = tuple(
        (row, mix, mode, False)
        for row, mode in (("H0", "none"), ("S4", "none"), ("S5", "bind"))
        for mix in MIXES
    )
    sample = (
        ("S1", "M-pool", "none", False),
        ("S2", "M-pool", "none", False),
        ("S6", "M-pool", "none", True),
    )
    return binding + sample


def _benchmark(args: argparse.Namespace) -> int:
    """Time every binding cell and a sample of S rows at two replicate sizes."""
    started = time.monotonic()
    load_started = time.monotonic()
    config, groups, _gate_groups, refused_count = _world(args)
    groups = tuple(partition_station_days(group)[0] for group in groups)
    load_seconds = time.monotonic() - load_started
    n_days = inclusive_days(config.freeze, config.horizon)
    r_sd = config.r_sd if config.r_sd_cal is None else config.r_sd_cal
    lambda_sd = config.lambda_sd if config.lambda_sd_cal is None else config.lambda_sd_cal
    p_keep = keep_probability(
        rate_cal(config.lambda_pool, config.take_rate_lower), r_sd=r_sd, lambda_sd=lambda_sd
    )
    cells = _timed_cells()
    timings: list[tuple[int, float]] = []
    rss_points: list[int] = []
    for size in _BENCH:
        tick = time.monotonic()
        for row, mix, mode, s6 in cells:
            prepared = prepare_mix_groups(groups, mix, s6=s6)
            if not prepared:
                continue
            simulate_family(
                prepared,
                replicates=size,
                n_days=n_days,
                p_keep=p_keep,
                seed=args.seed,
                row=row,
                rho=rho_bind(config.rho_hat) if mode == "bind" else None,
                netting=row != "S6",
                p_exit=exit_probability(config.pool_exit_fraction) if row == "S4" else 0.0,
                half_spread=config.half_spread,
                theta=config.theta,
            )
        timings.append((size, time.monotonic() - tick))
        rss_points.append(_rss())
        print(
            f"benchmark_point replicates={size} cells={len(cells)} seconds={timings[-1][1]:.3f} "
            f"rss_mib={rss_points[-1] / 1024**2:.1f}",
            flush=True,
        )
    (n_small, t_small), (n_large, t_large) = timings
    n_timed = len(cells)
    projected_sim = (
        _project(t_small / n_timed, n_small, t_large / n_timed, n_large, args.replicates)
        * PATH_FAMILIES
    )
    rss_small, rss_large = rss_points
    # Families run one after another, so RSS is not multiplied by PATH_FAMILIES.
    # Project the per-replicate slope only when the high-water mark actually grew.
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
                f"refused_count={refused_count}",
                f"timed_cells={n_timed}",
                f"load_seconds={load_seconds:.3f}",
                f"horizon_days={n_days}",
                f"path_families={PATH_FAMILIES}",
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
        amendment, parent = _load_pins()
        config, groups, gate_groups, _refused = _world(args)
        document = run_floor(
            groups,
            replicates=args.replicates,
            seed=args.seed,
            config=config,
            alphas=None if args.alpha is None else (args.alpha,),
            script_git_sha=_git(["hash-object", str(Path(__file__).resolve())]),
            parent_sha=_sha(parent),
            a0_sha=_sha(amendment),
            git_head=_git(["rev-parse", "HEAD"]),
            gate_groups=gate_groups,
            outer_resamples=args.outer_resamples,
            outer_replicates=args.outer_replicates,
        )
    except UnreachableTakeRate as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _write(args.out or default_out(args.seed), document)
    outcome = document["outcome"]
    mode = outcome.get("floor_mode") if isinstance(outcome, dict) else None
    print(f"floor_mode={mode}", flush=True)
    code = exit_code(document)
    if code and isinstance(outcome, dict):
        blocked = outcome.get("freeze_blocked")
        reason = blocked.get("reason") if isinstance(blocked, dict) else "blocked"
        print(f"freeze_blocked={reason}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
