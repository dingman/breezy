"""Pure seed estimators and frozen R0--R4 rules for LEAK-NULL (r2 + delta)."""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from scipy.special import stdtrit

import breezy.analysis.multisource_blend as msb

Refusal = msb.PreregIncompleteError
_NULLS: Final = ("N1_within_version", "N2_penalty_off", "N3_scrambled_sources")


@dataclass(frozen=True, slots=True)
class Thresholds:
    lb_gt: float = 0.0
    leak_mean_min: float = 0.005
    fluke_count_max: int = 2
    benign_n2_ratio_max: float = 0.25
    benign_n3_ratio_min: float = 0.5
    invariant_tol: float = 1e-9
    max_failed_seeds: int = 2
    min_moved_fraction: float = 0.5
    k: int = 20
    pc_k: int = 5
    t_crit_k20: float = 2.093
    t_crit_pc5: float = 2.776
    plant_noise_sd_f: float = 1.0


THRESHOLDS: Final = Thresholds()


@dataclass(frozen=True, slots=True)
class SeedSummary:
    seed: int
    null_id: str
    mean: float | None
    lb: float | None
    n_days: int
    by_horizon: Mapping[str, msb.DeltaSummary]
    by_m3_level: Mapping[int, msb.DeltaSummary]
    day_values: tuple[tuple[dt.date, float], ...]
    failed: str | None = None


def seed_summary(
    scored: Sequence[msb.ScoredRow],
    *,
    seed: int,
    null_id: str,
    n_boot: int,
    boot_seed: int,
    mean_block: float,
) -> SeedSummary:
    def summarize(rows: Sequence[msb.ScoredRow]) -> msb.DeltaSummary:
        return msb.delta_summary(
            msb.delta_by_day(rows, "M0prime", "M3"),
            n_boot=n_boot,
            seed=boot_seed,
            mean_block=mean_block,
        )

    total = summarize(scored)
    return SeedSummary(
        seed,
        null_id,
        total.mean,
        total.lb,
        total.n_days,
        {
            h: summarize([r for r in scored if r.horizon == h])
            for h in sorted({r.horizon for r in scored})
        },
        {
            level: summarize([r for r in scored if r.levels["M3"] == level])
            for level in sorted({r.levels["M3"] for r in scored})
        },
        tuple(msb.delta_by_day(scored, "M0prime", "M3")),
    )


@dataclass(frozen=True, slots=True)
class Bound:
    m: float
    sd: float
    n: int
    t: float
    l: float
    note: str | None = None


def across_seed_bound(summaries: Sequence[SeedSummary]) -> Bound:
    completed = [s for s in summaries if s.failed is None]
    if not completed:
        raise Refusal("across_seed_bound needs at least one completed seed")
    values: list[float] = []
    for summary in completed:
        if summary.mean is None or not math.isfinite(summary.mean):
            raise Refusal("completed seed mean must be finite")
        values.append(summary.mean)
    n, m = len(values), statistics.mean(values)
    if n == 1:
        return Bound(m, 0.0, 1, 0.0, m, "n=1: sd=0 and L=M; no replication bound")
    t = {20: THRESHOLDS.t_crit_k20, 5: THRESHOLDS.t_crit_pc5}.get(n)
    if t is None:
        t = float(stdtrit(n - 1, 1 - msb.ALPHA_ONE_SIDED))
    sd = statistics.stdev(values)
    return Bound(m, sd, n, t, m - t * sd / math.sqrt(n))


def pc_flagged(
    pc: Sequence[SeedSummary],
    th: Thresholds,
    *,
    plant_mask_rate: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """The caller measures the pass-through fraction over all planted-present rows."""
    if plant_mask_rate is not None and not 0 <= plant_mask_rate <= 1:
        raise Refusal("plant_mask_rate must be a fraction")
    completed = [s for s in pc if s.failed is None]
    bound = across_seed_bound(completed) if completed else None
    valid = len(pc) == len(completed) == th.pc_k and len({s.seed for s in pc}) == th.pc_k
    flagged = valid and bound is not None and bound.l > th.lb_gt and bound.m >= th.leak_mean_min
    return flagged, {
        "L_PC": bound.l if bound else None,
        "M_PC": bound.m if bound else None,
        "per_seed_means": [s.mean for s in pc],
        "plant_mask_rate": plant_mask_rate,
        "n_completed": len(completed),
        "flagged": flagged,
    }


def f13_bias_adjusted(record: Mapping[str, Any], m_n1: float) -> dict[str, Any]:
    adj_lb = float(record["m0p_vs_m3_lb"]) - m_n1
    floor = record["floor"]
    floor_ok = floor is None or adj_lb >= float(floor)
    return {
        "adj_lb": adj_lb,
        "floor": floor,
        "floor_check": "unavailable" if floor is None else "pass" if floor_ok else "fail",
        "pass": math.isfinite(adj_lb) and adj_lb > 0.0 and floor_ok,
    }


class LeakNullVerdict(StrEnum):
    INVALID = "INVALID"
    LEAK_CONFIRMED = "LEAK_CONFIRMED"
    HELD_INCONCLUSIVE = "HELD_INCONCLUSIVE"
    DISCHARGED_FLUKE = "DISCHARGED_FLUKE"
    DISCHARGED_BENIGN_DOF = "DISCHARGED_BENIGN_DOF"
    DISCHARGED_PENALTY_MEDIATED = "DISCHARGED_PENALTY_MEDIATED"
    HELD = "HELD"


def _invalid_reasons(
    by_null: Mapping[str, tuple[SeedSummary, ...]],
    pc: Sequence[SeedSummary],
    invariant_defects: Sequence[str],
    th: Thresholds,
) -> tuple[str, ...]:
    reasons = list(invariant_defects)
    if set(by_null) != set(_NULLS):
        reasons.append("missing or unexpected null IDs")
    for null_id in _NULLS:
        seeds = by_null.get(null_id, ())
        completed = [s for s in seeds if s.failed is None]
        if not th.k - th.max_failed_seeds <= len(completed) <= th.k:
            reasons.append(f"{null_id}: {len(completed)} completed seeds; need at least 18")
        if len(seeds) > th.k or len({s.seed for s in seeds}) != len(seeds):
            reasons.append(f"{null_id}: excess or duplicate seed records")
        if any(s.null_id != null_id for s in seeds):
            reasons.append(f"{null_id}: mismatched seed null_id")
        if any(
            s.mean is None or s.lb is None or not math.isfinite(s.mean) or not math.isfinite(s.lb)
            for s in completed
        ):
            reasons.append(f"{null_id}: nonfinite or missing completed statistics")
    if not pc_flagged(pc, th)[0]:
        reasons.append("positive control not flagged or a PC seed failed")
    return tuple(reasons)


def _verdict(
    by_null: Mapping[str, tuple[SeedSummary, ...]],
    f13_record: Mapping[str, Any],
    th: Thresholds,
) -> tuple[LeakNullVerdict, tuple[str, ...]]:
    n1, n2, n3 = (across_seed_bound(by_null[key]) for key in _NULLS)
    positives = sum(
        s.failed is None and s.lb is not None and s.lb > th.lb_gt for s in by_null[_NULLS[0]]
    )
    if n2.l > th.lb_gt:
        if n2.m >= th.leak_mean_min:
            return LeakNullVerdict.LEAK_CONFIRMED, ("R1: N2 bound and mean clear the leak gates",)
        return LeakNullVerdict.HELD_INCONCLUSIVE, ("R1: positive N2 bound below mean floor",)
    if n1.n == th.k and n1.l <= th.lb_gt and positives <= th.fluke_count_max:
        return LeakNullVerdict.DISCHARGED_FLUKE, ("R2: all 20 N1 completed; at most two positives",)
    if n1.l > th.lb_gt and n2.l <= th.lb_gt:
        if (
            n2.m <= th.benign_n2_ratio_max * n1.m
            and n3.l > th.lb_gt
            and n3.m >= th.benign_n3_ratio_min * n1.m
        ):
            return LeakNullVerdict.DISCHARGED_BENIGN_DOF, ("R3: benign degrees-of-freedom pattern",)
        bias = f13_bias_adjusted(f13_record, n1.m)
        if n2.m <= 0 and bias["pass"] and bias["floor_check"] != "unavailable":
            return LeakNullVerdict.DISCHARGED_PENALTY_MEDIATED, (
                "R4: penalty-mediated; F13 bias check passes",
            )
    return LeakNullVerdict.HELD, ("no frozen discharge or confirmation rule applies",)


def decide(
    by_null: Mapping[str, tuple[SeedSummary, ...]],
    pc: Sequence[SeedSummary],
    invariant_defects: Sequence[str],
    f13_record: Mapping[str, Any],
    th: Thresholds,
) -> tuple[LeakNullVerdict, tuple[str, ...]]:
    reasons = _invalid_reasons(by_null, pc, invariant_defects, th)
    if reasons:
        return LeakNullVerdict.INVALID, reasons
    return _verdict(by_null, f13_record, th)
