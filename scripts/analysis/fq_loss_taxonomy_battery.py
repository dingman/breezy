"""TE-2 WP1c: the Phase B test battery over station-event clusters or station-days (pure).

Plan section 2. Every test is exact and stdlib-only (see ``fq_loss_taxonomy_stats``); this module
only assembles the per-unit inputs, runs T-WIN (with its H0-K companion and leave-one-out), T-LOC,
T-SPREAD, T-ART and the Holm step, re-evaluates testability after ties, and builds the
``HypothesisOutcome`` objects the verdict consumes. No file, clock or settlement read happens here.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from scripts.analysis.fq_loss_taxonomy_stats import (
    ClusterOutcome,
    LeaveOneOut,
    PowerResult,
    Status,
    art_testability,
    cluster_probability,
    cluster_station_days,
    cluster_tail_indicator,
    format_p_value,
    h0k_cluster_probs,
    holm_decisions,
    holm_plan,
    min_attainable_p_sign,
    sign_test,
    spread_cluster_null,
    status_for_min_p,
    t_loc_cluster,
    t_loc_min_attainable_p,
    t_spread,
    t_spread_min_attainable_p,
    t_spread_power,
    t_win,
    t_win_leave_one_out,
    t_win_power,
    t_win_testability,
)
from scripts.analysis.fq_loss_taxonomy_verdict import HypothesisOutcome, reevaluate_after_ties

Level = Literal["cluster", "day"]


@dataclass(frozen=True)
class DayRecord:
    """One station-day, built from the Phase A table plus the settled outcome."""

    station: str
    climate_day: dt.date
    p_d: float
    won: bool
    ask_prob: float  # the H0-K / H1-K day probability (break-even of the ask, summed, capped)
    fill_qs: tuple[float, ...] | None  # per-fill T-SPREAD null; None when any pmf is missing
    tail_flags: tuple[bool, ...] | None  # per-fill tail miss; None when any pmf is missing
    pi: float | None  # T-LOC null of the day (earliest fill's pmf)
    corr_err: float | None  # tmax - corrected median (earliest fill's pmf)
    raw_err: float | None  # tmax - raw NBM median


@dataclass(frozen=True)
class BatteryResult:
    report: dict[str, Any]
    outcomes: Mapping[str, HypothesisOutcome]
    loo_rejects: bool
    after_ties: Mapping[str, Status]
    decisions: Mapping[str, bool]


@dataclass(frozen=True)
class _Unit:
    station: str
    p_c: float
    won: bool
    ask_days: tuple[float, ...]
    q_c: float | None
    tail: int | None
    pi_min: float | None
    pi_max: float | None
    corr_err: float | None
    raw_err: float | None


def _mean(values: Sequence[float | None]) -> float | None:
    if not values or any(v is None for v in values):
        return None
    return math.fsum(v for v in values if v is not None) / len(values)


def _flat_floats(parts: Sequence[tuple[float, ...] | None]) -> list[float] | None:
    return None if any(p is None for p in parts) else [x for p in parts if p for x in p]


def _flat_flags(parts: Sequence[tuple[bool, ...] | None]) -> list[bool] | None:
    return None if any(p is None for p in parts) else [x for p in parts if p for x in p]


def _unit(group: Sequence[DayRecord]) -> _Unit:
    qs = _flat_floats([d.fill_qs for d in group])
    flags = _flat_flags([d.tail_flags for d in group])
    pis = [d.pi for d in group]
    known = [p for p in pis if p is not None]
    complete = len(known) == len(pis)
    return _Unit(
        station=group[0].station,
        p_c=cluster_probability([d.p_d for d in group]),
        won=any(d.won for d in group),
        ask_days=tuple(d.ask_prob for d in group),
        q_c=None if qs is None else spread_cluster_null(qs),
        tail=None if flags is None else cluster_tail_indicator(flags),
        pi_min=min(known) if complete else None,
        pi_max=max(known) if complete else None,
        corr_err=_mean([d.corr_err for d in group]),
        raw_err=_mean([d.raw_err for d in group]),
    )


def _groups(days: Sequence[DayRecord], level: Level) -> list[list[DayRecord]]:
    ordered = sorted(days, key=lambda d: (d.station, d.climate_day))
    if level == "day":
        return [[d] for d in ordered]
    by_key = {(d.station, d.climate_day): d for d in ordered}
    return [
        [by_key[(c.station, day)] for day in c.climate_days]
        for c in cluster_station_days(list(by_key))
    ]


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _loo_report(loo: LeaveOneOut | None) -> dict[str, Any] | None:
    if loo is None:
        return None
    return {
        "dropped_station": loo.dropped_station, "w_obs": loo.w_obs, "n_clusters": loo.n_clusters,
        "p_value": loo.p_value, "p_display": format_p_value(loo.p_value), "rejects": loo.rejects,
    }  # fmt: skip


def _power_report(power: PowerResult) -> dict[str, Any]:
    return {
        "power": power.power, "w_star": power.w_star, "power_max_pc": power.power_max_pc,
        "power_independent": power.power_independent,
    }  # fmt: skip


def run_battery(
    days: Sequence[DayRecord], *, level: Level, alpha_primary: float, alpha_art: float
) -> BatteryResult:
    """Run every test at ``level`` ("cluster": station-events, "day": station-days)."""
    units = [_unit(g) for g in _groups(days, level)]
    p_cs = [u.p_c for u in units]
    w_obs = sum(1 for u in units if u.won)
    win = t_win(p_cs, w_obs, alpha=alpha_primary)
    win_status = t_win_testability(p_cs, alpha=alpha_primary)
    power = t_win_power(p_cs, [u.ask_days for u in units], alpha=alpha_primary)
    h0k = t_win(h0k_cluster_probs([u.ask_days for u in units]), w_obs, alpha=alpha_primary)
    loo = (
        t_win_leave_one_out(
            [ClusterOutcome(u.station, u.p_c, u.won) for u in units], alpha=alpha_primary
        )
        if len(units) >= 2
        else None
    )

    loc_pool = [
        (u, _sign(u.corr_err), u.pi_min, u.pi_max)
        for u in units
        if u.corr_err is not None and u.pi_min is not None and u.pi_max is not None
    ]
    loc_kept = [(s, lo, hi) for _u, s, lo, hi in loc_pool if s != 0]
    loc = t_loc_cluster(
        [s for s, _lo, _hi in loc_kept],
        [lo for _s, lo, _hi in loc_kept],
        [hi for _s, _lo, hi in loc_kept],
    )
    loc_min_pre = t_loc_min_attainable_p(
        [lo for _u, _s, lo, _hi in loc_pool], [hi for _u, _s, _lo, hi in loc_pool]
    )
    loc_min_post = t_loc_min_attainable_p(
        [lo for _s, lo, _hi in loc_kept], [hi for _s, _lo, hi in loc_kept]
    )

    spread_pool = [u for u in units if u.q_c is not None and u.tail is not None]
    qs = [u.q_c for u in spread_pool if u.q_c is not None]
    x_obs = sum(u.tail for u in spread_pool if u.tail is not None)
    spread_p = t_spread(qs, x_obs)
    spread_min = t_spread_min_attainable_p(qs)
    spread_power = t_spread_power(qs, alpha=alpha_primary)

    art_pool = [u for u in units if u.corr_err is not None and u.raw_err is not None]
    diffs = [
        abs(u.corr_err) - abs(u.raw_err)
        for u in art_pool
        if u.corr_err is not None and u.raw_err is not None
    ]
    art = sign_test(diffs, "greater")
    art_pre = status_for_min_p(min_attainable_p_sign(len(diffs), "greater"), alpha_art)
    art_post = status_for_min_p(min_attainable_p_sign(art.n_after_drops, "greater"), alpha_art)

    plan_pre = holm_plan({"T-LOC": loc_min_pre, "T-SPREAD": spread_min}, alpha=alpha_primary)
    plan_post = holm_plan({"T-LOC": loc_min_post, "T-SPREAD": spread_min}, alpha=alpha_primary)
    decisions = holm_decisions(
        {"T-LOC": loc.p_value, "T-SPREAD": spread_p}, plan_post, alpha=alpha_primary
    )
    pre: dict[str, Status] = {
        "T-WIN": win_status, "T-LOC": plan_pre.statuses["T-LOC"],
        "T-SPREAD": plan_pre.statuses["T-SPREAD"], "T-ART": art_pre,
    }  # fmt: skip
    post: dict[str, Status] = {
        "T-WIN": win_status, "T-LOC": plan_post.statuses["T-LOC"],
        "T-SPREAD": plan_post.statuses["T-SPREAD"], "T-ART": art_post,
    }  # fmt: skip
    ties = reevaluate_after_ties(pre, post)
    art_rejects = art.p_value <= alpha_art
    outcomes = {
        "T-WIN": HypothesisOutcome("T-WIN", win_status, win.rejects, win.p_value, power.power),
        "T-LOC": HypothesisOutcome("T-LOC", post["T-LOC"], decisions["T-LOC"], loc.p_value, None),
        "T-SPREAD": HypothesisOutcome(
            "T-SPREAD", post["T-SPREAD"], decisions["T-SPREAD"], spread_p, spread_power
        ),
        "T-ART": HypothesisOutcome("T-ART", art_post, art_rejects, art.p_value, None),
    }
    report: dict[str, Any] = {
        "level": level,
        "n_units": len(units),
        "T-WIN": {
            "n_units": len(units), "w_obs": w_obs, "p_value": win.p_value,
            "p_display": format_p_value(win.p_value), "rejects": win.rejects, "status": win_status,
            "min_attainable_p": t_win_p0(p_cs), "power": _power_report(power),
            "leave_one_out": _loo_report(loo),
            "h0k": {"p_value": h0k.p_value, "rejects": h0k.rejects},
        },
        "T-LOC": {
            "n_units": len(loc_pool), "n_after_drops": len(loc_kept),
            "n_dropped": len(loc_pool) - len(loc_kept), "p_value": loc.p_value,
            "p_display": format_p_value(loc.p_value), "p_at_pi_min": loc.p_at_pi_min,
            "p_at_pi_max": loc.p_at_pi_max, "rejects": decisions["T-LOC"],
            "status": post["T-LOC"], "min_attainable_p": loc_min_post, "indicative": True,
        },
        "T-SPREAD": {
            "n_units": len(spread_pool), "x_obs": x_obs, "p_value": spread_p,
            "p_display": format_p_value(spread_p), "rejects": decisions["T-SPREAD"],
            "status": post["T-SPREAD"], "min_attainable_p": spread_min, "power": spread_power,
            "n_dropped_no_pmf": len(units) - len(spread_pool),
        },
        "T-ART": {
            "n_units": len(art_pool), "n_after_drops": art.n_after_drops,
            "n_dropped": art.n_dropped, "n_positive": art.n_positive, "p_value": art.p_value,
            "p_display": format_p_value(art.p_value), "rejects": art_rejects, "status": art_post,
            "min_attainable_p": min_attainable_p_sign(art.n_after_drops, "greater"),
        },
        "testability": {
            "pre_ties": dict(pre), "after_ties": dict(post), "holm_k": plan_post.k,
            "holm_alpha_step1": plan_post.alpha_step1,
        },
        "tie_reevaluation": {
            "downgraded": list(ties.downgraded), "variance_eligible": dict(ties.variance_eligible)
        },
    }  # fmt: skip
    return BatteryResult(report, outcomes, bool(loo and loo.rejects), post, decisions)


def t_win_p0(p_cs: Sequence[float]) -> float:
    """The minimum attainable T-WIN p: P(W = 0) under H0-M."""
    return math.prod(1.0 - p for p in p_cs)


def s0i_statuses_from_phase_a(table: Mapping[str, Any], *, alpha_primary: float) -> dict[str, str]:
    """The outcome-blind S0-I testability list, from the Phase A table's cluster rows."""
    clusters = table["clusters"]
    p_cs = [c["P_c"] for c in clusters]
    pis = [(c["pi_min"], c["pi_max"]) for c in clusters if c["pi_min"] is not None]
    qs = [c["q_c"] for c in clusters if c["q_c"] is not None]
    plan = holm_plan(
        {
            "T-LOC": t_loc_min_attainable_p([lo for lo, _ in pis], [hi for _, hi in pis]),
            "T-SPREAD": t_spread_min_attainable_p(qs),
        },
        alpha=alpha_primary,
    )
    return {
        "T-WIN": t_win_testability(p_cs, alpha=alpha_primary),
        "T-LOC": plan.statuses["T-LOC"],
        "T-SPREAD": plan.statuses["T-SPREAD"],
        "T-ART": art_testability(len(clusters)),
    }
