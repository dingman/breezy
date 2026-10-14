"""MAKER-S2 WP5: per-hypothesis analysis, the frozen verdict table and ``s3_inputs``.

Plan ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` WP5 + r4 delta (a) V0,
(e), (f), (g), (i)4/(i)6; spec v0.3 6.0 (:211-230) and 6.9 (:290-304). Pure. ``n_eff_gov`` /
``is_underpowered`` come from ``maker_stage0_inputs``. Rows: ``maker_stage0_rows``; 6.9:
``maker_stage0_scored`` (both re-exported). 6.9 and the expectancy use the BASE rule.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from scripts.analysis import maker_stage0_stats as st
from scripts.analysis.maker_stage0_inputs import is_underpowered, n_eff_gov
from scripts.analysis.maker_stage0_rows import PosRow, SdRow, in_denominator, nz
from scripts.analysis.maker_stage0_scored import (
    NO_FINAL,
    OUTCOME_NO,
    OUTCOME_VOID,
    BidStats,
    Expectancy,
    Section69,
    VerdictRefused,
    bid_stats,
    days_to_200,
    expectancy,
    section_69,
)

# own public API plus the re-exports that keep the pre-split import paths alive
__all__ = [
    "FILL_FLOOR", "NOT_KILLED", "NOT_KILLED_UNSCREENED", "NO_FINAL", "NO_GO_ADVERSE",
    "NO_GO_FILL", "NO_GO_STRESS", "OUTCOME_NO", "OUTCOME_VOID", "UNDERPOWERED", "BidStats",
    "Coverage", "Decision", "Expectancy", "HypAnalysis", "NoBidBearingDays", "PosRow", "Rate",
    "SdRow", "Section69", "VerdictRefused", "analyse_all", "analyse_hypothesis", "bid_stats",
    "build_s3_inputs", "comparisons", "coverage_sensitivity", "days_to_200", "decide",
    "expectancy", "in_denominator", "nz", "section_69", "verdict_label",
]  # fmt: skip

UNDERPOWERED: Final[str] = "UNDERPOWERED-WAIT"
NO_GO_FILL: Final[str] = "NO-GO (fill)"
NO_GO_ADVERSE: Final[str] = "NO-GO (adverse selection)"
NO_GO_STRESS: Final[str] = "NO-GO (stress)"
NOT_KILLED_UNSCREENED: Final[str] = "NOT-KILLED-UNSCREENED"
NOT_KILLED: Final[str] = "NOT-KILLED"
FILL_FLOOR: Final[float] = 0.10  # spec :221-222
_ROW_LABELS: Final[dict[str, str]] = {
    "V1": NO_GO_FILL,
    "V2": NO_GO_ADVERSE,
    "V3": NO_GO_STRESS,
    "V4": NOT_KILLED_UNSCREENED,
}
COVERAGE_LIVE_SHARE: Final[float] = 0.5  # (i)4: covered_live_h >= 0.5 * process_live_h
GAP_SHARE_LIMIT: Final[float] = 0.5
MAX_RUNGS_HYPOTHESIS: Final[int] = 2


class NoBidBearingDays(ValueError):
    """S-4 (r4 (a)): n_sd = 0 is degenerate; no rate is computable."""


# --- rates ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    k: int
    n: int
    point: float | None
    wilson: tuple[float, float] | None
    boot: st.BootInterval | None  # None = "not estimable" (< 5 climate-date clusters)


_Pick = Callable[[SdRow], float]


def position_trials(r: SdRow) -> float:
    """Position-unit denominator: attempted rungs plus wanted rungs that never had a book."""
    return nz(r.rung_trials_attempted) + nz(r.n_no_book_wants)


RATE_SPECS: Final[dict[str, tuple[_Pick, _Pick]]] = {
    "base_sd": (lambda r: float(nz(r.filled_pairs_base) >= 1), lambda r: 1.0),
    "stress_sd": (lambda r: float(nz(r.filled_pairs_stress) >= 1), lambda r: 1.0),
    "base_pos": (lambda r: nz(r.filled_pairs_base), position_trials),
    "stress_pos": (lambda r: nz(r.filled_pairs_stress), position_trials),
    "base_k1": (lambda r: nz(r.k1_filled_base), lambda r: 1.0),
    "stress_k1": (lambda r: nz(r.k1_filled_stress), lambda r: 1.0),
}


def _rate(rows: Sequence[SdRow], num: _Pick, size: _Pick) -> Rate:
    k, n = round(sum(num(r) for r in rows)), round(sum(size(r) for r in rows))

    def ratio(drawn: Sequence[SdRow]) -> float:
        total = sum(size(r) for r in drawn)
        return sum(num(r) for r in drawn) / total if total else 0.0

    boot = st.cluster_interval(rows, ratio)
    return Rate(k, n, k / n if n else None, st.wilson_interval(k, n), boot)


def _stricter(day_unit: Rate, position_unit: Rate, *, n_den: int) -> float:
    """The lower of the two units; an empty unit on a non-empty denominator is a refusal."""
    if n_den == 0:
        return 0.0
    points: list[float] = []
    for label, unit in (("station-day", day_unit), ("position", position_unit)):
        if unit.point is None:
            raise VerdictRefused(f"{label} unit has n=0 on {n_den} denominator station-days")
        points.append(unit.point)
    return min(points)


# --- coverage sensitivity, days to 200 --------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    """(i)4, report-only: rates on days with ``covered_live_h >= 0.5 * process_live_h``."""

    n_all: int
    n_sd: int
    base_sd: float | None
    stress_sd: float | None
    base_pos: float | None
    stress_pos: float | None
    nogo_driving: int
    nogo_gap_gt_half: int


def coverage_sensitivity(den: Sequence[SdRow]) -> Coverage:
    kept = [r for r in den if nz(r.covered_live_h) >= COVERAGE_LIVE_SHARE * nz(r.process_live_h)]
    pt = {name: _rate(kept, *RATE_SPECS[name]).point for name in RATE_SPECS}
    nogo = [r for r in den if r.nogo_driving]
    gappy = sum(1 for r in nogo if r.gap_share is not None and r.gap_share > GAP_SHARE_LIMIT)
    return Coverage(
        len(den), len(kept), pt["base_sd"], pt["stress_sd"], pt["base_pos"], pt["stress_pos"],
        len(nogo), gappy,
    )  # fmt: skip


# --- per-hypothesis analysis ------------------------------------------------------------------


@dataclass(frozen=True)
class HypAnalysis:
    name: str
    n_sd: int
    n0: int
    n_eff_gov: float
    covered_days: int
    n_never_booked_days: int
    rates: dict[str, Rate]
    base_rate: float  # the stricter of the two units
    stress_rate: float
    icc_station_day: st.IccFit
    icc_rung_trial: st.IccFit
    icc_rung_trial_k1: st.IccFit
    fitted_icc_disagrees: bool
    s69: Section69
    s69_stress: Section69  # report-only: the same screen over STRESSED fills; never a label
    expectancy: Expectancy
    two_fill_share: float | None
    bids: BidStats
    coverage: Coverage
    days_to_200: dict[str, float | None]

    @property
    def r_lo(self) -> float:
        point = self.rates["stress_sd"].point
        return 0.0 if point is None else point


def _by_day(pairs: Sequence[tuple[str, float]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for day, value in pairs:
        out[day].append(value)
    return dict(out)


def _require_denominator_columns(name: str, den: Sequence[SdRow]) -> None:
    """A blank denominator cell on a denominator row would silently shrink the position unit."""
    for r in den:
        for col in ("rung_trials_attempted", "n_no_book_wants"):
            if getattr(r, col) is None:
                raise VerdictRefused(f"{name}: {r.station} {r.climate_day} has no {col}")


def analyse_hypothesis(
    name: str, sd_rows: Sequence[SdRow], pos_rows: Sequence[PosRow]
) -> HypAnalysis:
    den = [r for r in sd_rows if in_denominator(r)]
    _require_denominator_columns(name, den)
    keys = {(r.station, r.climate_day) for r in den}
    pos = [p for p in pos_rows if (p.station, p.climate_day) in keys]
    per_date = _by_day([(r.climate_day, 1.0) for r in den])
    eff = n_eff_gov({dt.date.fromisoformat(d): len(v) for d, v in per_date.items()})
    rates = {k: _rate(den, *spec) for k, spec in RATE_SPECS.items()}
    fit = st.anova_icc(_by_day([(r.climate_day, RATE_SPECS["base_sd"][0](r)) for r in den]))
    stress_days = [r for r in den if nz(r.filled_pairs_stress) >= 1]
    theta = {(r.station, r.climate_day): r.theta for r in den if r.theta is not None}
    return HypAnalysis(
        name=name,
        n_sd=len(den),
        n0=len(per_date),
        n_eff_gov=eff,
        covered_days=sum(1 for r in sd_rows if r.covered and not r.outage_excluded),
        n_never_booked_days=sum(1 for r in den if not r.bid_bearing),
        rates=rates,
        base_rate=_stricter(rates["base_sd"], rates["base_pos"], n_den=len(den)),
        stress_rate=_stricter(rates["stress_sd"], rates["stress_pos"], n_den=len(den)),
        icc_station_day=fit,
        icc_rung_trial=st.anova_icc(
            _by_day([(p.climate_day, float(p.filled_stress)) for p in pos])
        ),
        icc_rung_trial_k1=st.anova_icc(
            _by_day([(r.climate_day, nz(r.k1_filled_stress)) for r in den])
        ),
        fitted_icc_disagrees=fit.n_eff_hat is not None
        and is_underpowered(fit.n_eff_hat) != is_underpowered(eff),
        s69=section_69(pos),
        s69_stress=section_69(pos, stressed=True),
        expectancy=expectancy([p for p in pos if p.filled_base], theta),
        two_fill_share=(
            sum(1 for r in stress_days if nz(r.filled_pairs_stress) >= 2) / len(stress_days)
            if stress_days
            else None
        ),
        bids=bid_stats(pos),
        coverage=coverage_sensitivity(den),
        days_to_200=days_to_200(sd_rows),
    )


def _check_hypotheses(found: Sequence[str], expected: Sequence[str], what: str) -> list[str]:
    """The set comes from the WP1 unit loader; a missing or extra hypothesis is a refusal."""
    names = sorted(expected)
    if not names or len(set(names)) != len(names):
        raise VerdictRefused(f"expected hypothesis set must be non-empty and unique: {names}")
    absent, extra = sorted(set(names) - set(found)), sorted(set(found) - set(names))
    if absent or extra:
        raise VerdictRefused(f"{what}: hypotheses without rows {absent}, unexpected {extra}")
    return names


def analyse_all(
    sd_rows: Sequence[SdRow], pos_rows: Sequence[PosRow], hypotheses: Sequence[str]
) -> list[HypAnalysis]:
    """One analysis per hypothesis in ``hypotheses`` (from the unit loader), sorted by name."""
    names = _check_hypotheses([r.unit_hypothesis for r in sd_rows], hypotheses, "station-days")
    return [
        analyse_hypothesis(
            n,
            [r for r in sd_rows if r.unit_hypothesis == n],
            [p for p in pos_rows if p.unit_hypothesis == n],
        )
        for n in names
    ]


# --- the frozen table -------------------------------------------------------------------------


def verdict_label(base: float, stress: float, state: str) -> tuple[str, tuple[str, ...]]:
    """First matching row V1..V4 sets the label (else V5); every failing row is returned."""
    hits = (
        base < FILL_FLOOR,
        state == st.STATE_FAIL,
        stress < FILL_FLOOR,
        state == st.STATE_UNSCREENED,
    )
    failing = tuple(row for row, hit in zip(_ROW_LABELS, hits, strict=True) if hit)
    return (_ROW_LABELS[failing[0]] if failing else NOT_KILLED), failing


def comparisons(base: float, stress: float, state: str) -> tuple[str, ...]:
    """V1-V5 as threshold comparisons (descriptive; never a NO-GO string; r4 (a))."""
    rel = {True: "<", False: ">="}
    return (
        f"V1: base {base:.4f} {rel[base < FILL_FLOOR]} {FILL_FLOOR:.2f}",
        f"V2: section 6.9 state {state} (trigger FAIL)",
        f"V3: stressed {stress:.4f} {rel[stress < FILL_FLOOR]} {FILL_FLOOR:.2f}",
        f"V4: section 6.9 state {state} (trigger UNSCREENED)",
        f"V5: base and stressed >= {FILL_FLOOR:.2f} and state PASS",
    )


@dataclass(frozen=True)
class Decision:
    label: str
    governing: str
    failing: tuple[str, ...]
    per_hypothesis: dict[str, str]
    comparisons: tuple[str, ...]


def _rank(label: str) -> int:
    if label.startswith("NO-GO"):
        return 0
    return 1 if label == NOT_KILLED_UNSCREENED else 2


def decide(analyses: Sequence[HypAnalysis], hypotheses: Sequence[str]) -> Decision:
    """V0 on the minimum ``n_eff_gov``; else NO-GO > UNSCREENED > NOT-KILLED, ties to lower r_lo."""
    _check_hypotheses([a.name for a in analyses], hypotheses, "analyses")
    if not analyses or any(a.n_sd == 0 for a in analyses):
        raise NoBidBearingDays("no covered bid-bearing station-day: no verdict is computable")
    weakest = min(analyses, key=lambda a: (a.n_eff_gov, a.r_lo))
    if is_underpowered(weakest.n_eff_gov):
        notes = comparisons(weakest.base_rate, weakest.stress_rate, weakest.s69.state)
        return Decision(
            UNDERPOWERED, weakest.name, (), {a.name: UNDERPOWERED for a in analyses}, notes
        )
    scored = {a.name: verdict_label(a.base_rate, a.stress_rate, a.s69.state) for a in analyses}
    gov = min(analyses, key=lambda a: (_rank(scored[a.name][0]), a.r_lo))
    label, failing = scored[gov.name]
    per_hyp = {name: lab for name, (lab, _) in scored.items()}
    notes = comparisons(gov.base_rate, gov.stress_rate, gov.s69.state)
    return Decision(label, gov.name, failing, per_hyp, notes)


# --- s3_inputs.json (r4 (f)) ------------------------------------------------------------------


def _lcb(a: HypAnalysis, key: str) -> float | None:
    boot = a.rates[key].boot
    return None if boot is None else boot.low


def _min_or_none(values: Sequence[float | None]) -> float | None:
    """The minimum over hypotheses; None if any is not estimable (never optimistic)."""
    defined = [v for v in values if v is not None]
    return min(defined) if len(defined) == len(values) and defined else None


def _point(rate: Rate) -> float:
    return 0.0 if rate.point is None else rate.point


def _worst_boot(analyses: Sequence[HypAnalysis]) -> st.BootInterval | None:
    """The stressed-day bootstrap of the min-LCB hypothesis; None if any is not estimable."""
    boots = [a.rates["stress_sd"].boot for a in analyses]
    defined = [b for b in boots if b is not None]
    return min(defined, key=lambda b: b.low) if defined and len(defined) == len(boots) else None


def build_s3_inputs(
    decision: Decision, analyses: Sequence[HypAnalysis], *, code_sha: str
) -> dict[str, object]:
    """Every ``r_lo*`` key is the minimum over hypotheses; the rest come from the governing one.

    ``r_lo_position``, ``r_lo_lcb_cluster_boot``, ``r_lo_k1_lcb_cluster_boot`` and
    ``r_lo_se_cluster_boot`` are null when ANY hypothesis is not estimable (< 5 climate dates):
    S3 must treat null as REFUSE, never as 0 and never as f_pass = f_kill.
    """
    gov = next(a for a in analyses if a.name == decision.governing)
    lcbs = {a.name: _lcb(a, "stress_sd") for a in analyses}
    # the SE comes from the hypothesis attaining the minimum LCB, never the smallest SD
    worst = _worst_boot(analyses)
    r_by = {a.name: a.r_lo for a in analyses}
    base_boot, bids = gov.rates["base_sd"].boot, gov.bids
    return {
        "verdict": decision.label,
        "r_lo": min(r_by.values()),
        "r_lo_station_day": min(r_by.values()),
        "r_lo_position": _min_or_none([a.rates["stress_pos"].point for a in analyses]),
        "r_lo_by_hypothesis": r_by,
        "r_lo_lcb_cluster_boot": _min_or_none(list(lcbs.values())),
        "r_lo_lcb_by_hypothesis": lcbs,
        "r_lo_se_cluster_boot": None if worst is None else worst.se,
        "r_lo_k1": min(_point(a.rates["stress_k1"]) for a in analyses),
        "base_k1": gov.rates["base_k1"].point,
        "r_lo_k1_lcb_cluster_boot": _min_or_none([_lcb(a, "stress_k1") for a in analyses]),
        "fill_icc_rung_trial_k1": gov.icc_rung_trial_k1.rho,
        "base_station_day_rate": gov.rates["base_sd"].point,
        "base_station_day_rate_ci_cluster_boot": (
            None if base_boot is None else [base_boot.low, base_boot.high]
        ),
        "two_fill_share": gov.two_fill_share,
        "bid_bearing_share_of_covered_listed": gov.n_sd / gov.covered_days or None,
        "fill_icc_rung_trial": gov.icc_rung_trial.rho,
        "fill_icc_station_day": gov.icc_station_day.rho,
        "n0_climate_dates": gov.n0,
        "n_eff_gov": gov.n_eff_gov,
        "b": bids.b,
        "realised_bid_iqr": None if bids.iqr is None else list(bids.iqr),
        "n_stressed_fills": bids.n_stressed_fills,
        "realised_bid_median_base": bids.median_base,
        "max_rungs_hypothesis": MAX_RUNGS_HYPOTHESIS,
        "unit_hypothesis": decision.governing,
        "code_sha": code_sha,
    }
