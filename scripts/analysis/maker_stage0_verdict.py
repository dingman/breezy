"""MAKER-S2 WP5: rows, per-hypothesis analysis, the frozen verdict table and ``s3_inputs``.

Plan ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` 1.1 + WP5 and r4 delta
(a) V0, (e) denominator, (f) ``s3_inputs.json``, (g) CSV contract, (i)4/(i)6. Spec v0.3 6.0
(``docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md`` :211-230) and 6.9 (:290-304).

Pure. ``n_eff_gov`` / ``is_underpowered`` come from ``maker_stage0_inputs`` (never recomputed).
Section 6.9 and the expectancy use the BASE rule (``p_yes_point_live`` is the base pass's vector).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Final

from scripts.analysis import maker_stage0_stats as st
from scripts.analysis.maker_stage0_inputs import is_underpowered, n_eff_gov

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
OUTCOME_NO: Final[str] = "NO"
OUTCOME_VOID: Final[str] = "VOID"  # excluded from section 6.9; refund 0 in the expectancy
NO_FINAL: Final[str] = ""  # no CLI FINAL: excluded from section 6.9 and counted
_LOSSES: Final[frozenset[str]] = frozenset({"YES", "UNRESOLVED"})  # unresolved past D+14 = LOSS
_OUTCOMES: Final[frozenset[str]] = _LOSSES | {OUTCOME_NO, OUTCOME_VOID, NO_FINAL}
COVERAGE_LIVE_SHARE: Final[float] = 0.5  # (i)4: covered_live_h >= 0.5 * process_live_h
GAP_SHARE_LIMIT: Final[float] = 0.5
TARGET_POSITIONS: Final[int] = 200
MAX_RUNGS_HYPOTHESIS: Final[int] = 2


class NoBidBearingDays(ValueError):
    """S-4 (r4 (a)): n_sd = 0 is degenerate; no rate is computable."""


# --- rows -------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SdRow:
    """``station_days.csv`` (r4 (g)); replay fields are None where the day was not replayed.

    ``rung_trials_attempted`` (position-unit denominator) and ``n_no_book_wants`` (WP4 re-check M1:
    wanted rungs that never had a book) are appended after the contract columns.
    """

    station: str
    climate_day: str
    cluster_id: str
    unit_hypothesis: str
    census_reason: str | None = None
    covered_bidlive: bool = False
    covered: bool = False
    outage_excluded: bool = False
    node_log_absent: bool = False
    bid_bearing: bool | None = None
    guard_refused_only: bool | None = None
    n_depth_frames: int | None = None
    has_depth_frame: bool | None = None
    n_attempts: int | None = None
    n_episodes: int | None = None
    n_refused: int | None = None
    n_process_cuts: int | None = None
    n_gtd_cuts: int | None = None
    rung_trials_posted: int | None = None
    rung_trials_filled_base: int | None = None
    rung_trials_filled_stress: int | None = None
    process_live_h: float | None = None
    forecast_valid_h: float | None = None
    gap_h: float | None = None
    covered_live_h: float | None = None
    gap_share: float | None = None
    filled_pairs_base: int | None = None
    filled_pairs_stress: int | None = None
    k1_rung_id: str | None = None
    k1_filled_base: int | None = None
    k1_filled_stress: int | None = None
    bid_median_fills_stress: float | None = None
    nogo_driving: bool | None = None
    positions_filled_k2_base: int | None = None
    positions_filled_k2_stress: int | None = None
    positions_filled_k1_base: int | None = None
    positions_filled_k1_stress: int | None = None
    delta_ns: int | None = None
    truth_final: bool | None = None
    truth_tmax_f: int | None = None
    void: bool | None = None
    unresolved_d14: bool | None = None
    theta: float | None = None
    rung_trials_attempted: int | None = None
    n_no_book_wants: int | None = None

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


@dataclass(frozen=True, kw_only=True)
class PosRow:
    """``scored_episodes.csv`` row; ``truth_final`` is "", YES, NO, VOID or UNRESOLVED."""

    position_id: str
    rung_trial_id: str
    station: str
    climate_day: str
    unit_hypothesis: str
    bid: float
    filled_base: bool
    filled_stress: bool
    p_yes_point_live: float | None
    truth_final: str

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


def nz(value: float | None) -> float:
    return 0.0 if value is None else float(value)


def in_denominator(row: SdRow) -> bool:
    """Covered, not outage-excluded, bid-bearing (or with a never-booked want; WP4 M1)."""
    booked = bool(row.bid_bearing) or nz(row.n_no_book_wants) > 0
    return row.covered and not row.outage_excluded and booked


# --- section 6.9 over scored rows -------------------------------------------------------------


@dataclass(frozen=True)
class Section69(st.Screen):
    """The pooled screen plus the exclusions the report must count (r4 (i)6)."""

    excluded_no_final_filled: int
    excluded_no_final_unfilled: int
    excluded_no_final_days: int
    n_void_excluded: int


def section_69(rows: Sequence[PosRow]) -> Section69:
    kept: list[st.ScreenRow] = []
    no_final = {True: 0, False: 0}
    no_final_days: set[tuple[str, str]] = set()
    voids = 0
    for r in rows:
        if r.truth_final not in _OUTCOMES:
            raise ValueError(f"unknown settlement token {r.truth_final!r} on {r.position_id}")
        if r.truth_final == OUTCOME_VOID:
            voids += 1
        elif r.truth_final == NO_FINAL:
            no_final[r.filled_base] += 1
            no_final_days.add((r.station, r.climate_day))
        elif r.p_yes_point_live is None:
            raise ValueError(f"scored row {r.position_id} has no p_yes_point_live")
        else:
            loss = r.truth_final in _LOSSES
            kept.append(st.ScreenRow(r.p_yes_point_live, loss, r.filled_base, r.climate_day))
    screen = st.pooled_screen(kept)
    return Section69(
        **{f.name: getattr(screen, f.name) for f in fields(screen)},
        excluded_no_final_filled=no_final[True],
        excluded_no_final_unfilled=no_final[False],
        excluded_no_final_days=len(no_final_days),
        n_void_excluded=voids,
    )


# --- rates ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    k: int
    n: int
    point: float | None
    wilson: tuple[float, float] | None
    boot: st.BootInterval | None  # None = "not estimable" (< 5 climate-date clusters)


_Pick = Callable[[SdRow], float]
RATE_SPECS: Final[dict[str, tuple[_Pick, _Pick]]] = {
    "base_sd": (lambda r: float(nz(r.filled_pairs_base) >= 1), lambda r: 1.0),
    "stress_sd": (lambda r: float(nz(r.filled_pairs_stress) >= 1), lambda r: 1.0),
    "base_pos": (lambda r: nz(r.filled_pairs_base), lambda r: nz(r.rung_trials_attempted)),
    "stress_pos": (lambda r: nz(r.filled_pairs_stress), lambda r: nz(r.rung_trials_attempted)),
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


def _stricter(a: Rate, b: Rate) -> float:
    return min((x for x in (a.point, b.point) if x is not None), default=0.0)


# --- expectancy and bids ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Fill:
    climate_day: str
    win: float
    net: float
    p_no: float

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


@dataclass(frozen=True)
class Expectancy:
    """Base-rule fills: win rate beside mean model p_NO, and ``w - (b + theta b (1 - b))``."""

    n_fills: int
    n_excluded_no_final: int
    wins: int
    win_rate: float | None
    mean_p_no: float | None
    win_rate_boot: st.BootInterval | None
    win_rate_cp: tuple[float, float] | None
    net_mean: float | None
    net_upper_bound: float | None  # one-sided 95% (climate-date cluster bootstrap)


def _mean(fills: Sequence[_Fill], pick: Callable[[_Fill], float]) -> float:
    return math.fsum(pick(f) for f in fills) / len(fills) if fills else 0.0


def expectancy(fills: Sequence[PosRow], theta: Mapping[tuple[str, str], float]) -> Expectancy:
    scored: list[_Fill] = []
    for r in (r for r in fills if r.truth_final != NO_FINAL):
        if (r.station, r.climate_day) not in theta:
            raise ValueError(f"no theta for scored fill {r.position_id}")
        fee = theta[(r.station, r.climate_day)] * r.bid * (1.0 - r.bid)
        win = float(r.truth_final == OUTCOME_NO)
        scored.append(
            _Fill(r.climate_day, win, win - (r.bid + fee), 1.0 - (r.p_yes_point_live or 0))
        )
    n, wins = len(scored), round(sum(f.win for f in scored))

    def mean_of(pick: Callable[[_Fill], float]) -> Callable[[Sequence[_Fill]], float]:
        return lambda rows: _mean(rows, pick)

    return Expectancy(
        n, len(fills) - n, wins, wins / n if n else None,
        _mean(scored, lambda f: f.p_no) if n else None,
        st.cluster_interval(scored, mean_of(lambda f: f.win)), st.clopper_pearson(wins, n),
        _mean(scored, lambda f: f.net) if n else None,
        st.cluster_upper_bound(scored, mean_of(lambda f: f.net)),
    )  # fmt: skip


@dataclass(frozen=True)
class BidStats:
    b: float | None
    iqr: tuple[float, float] | None
    n_stressed_fills: int
    median_base: float | None


def bid_stats(rows: Sequence[PosRow]) -> BidStats:
    stressed = [r.bid for r in rows if r.filled_stress]
    base = [r.bid for r in rows if r.filled_base]
    return BidStats(
        st.lower_median(stressed), st.inverted_cdf_iqr(stressed), len(stressed),
        st.lower_median(base),
    )  # fmt: skip


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


def days_to_200(rows: Sequence[SdRow]) -> dict[str, float | None]:
    """200 / (positions per distinct covered climate date); None when nothing fills."""
    live = [r for r in rows if r.covered and not r.outage_excluded]
    dates = len({r.climate_day for r in live})
    out: dict[str, float | None] = {}
    for key in ("k2_base", "k2_stress", "k1_base", "k1_stress"):
        total = sum(nz(getattr(r, f"positions_filled_{key}")) for r in live)
        out[key] = TARGET_POSITIONS * dates / total if total > 0 else None
    return out


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
    expectancy: Expectancy
    two_fill_share: float | None
    bids: BidStats
    coverage: Coverage
    days_to_200: dict[str, float | None]

    @property
    def r_lo(self) -> float:
        return self.rates["stress_sd"].point or 0.0


def _by_day(pairs: Sequence[tuple[str, float]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for day, value in pairs:
        out[day].append(value)
    return dict(out)


def analyse_hypothesis(
    name: str, sd_rows: Sequence[SdRow], pos_rows: Sequence[PosRow]
) -> HypAnalysis:
    den = [r for r in sd_rows if in_denominator(r)]
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
        base_rate=_stricter(rates["base_sd"], rates["base_pos"]),
        stress_rate=_stricter(rates["stress_sd"], rates["stress_pos"]),
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


def analyse_all(sd_rows: Sequence[SdRow], pos_rows: Sequence[PosRow]) -> list[HypAnalysis]:
    names = sorted({r.unit_hypothesis for r in sd_rows})
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


def decide(analyses: Sequence[HypAnalysis]) -> Decision:
    """V0 on the minimum ``n_eff_gov``; else NO-GO > UNSCREENED > NOT-KILLED, ties to lower r_lo."""
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


def build_s3_inputs(
    decision: Decision, analyses: Sequence[HypAnalysis], *, code_sha: str
) -> dict[str, object]:
    """Every ``r_lo*`` key is the minimum over hypotheses; the rest come from the governing one."""
    gov = next(a for a in analyses if a.name == decision.governing)
    lcbs = {a.name: _lcb(a, "stress_sd") for a in analyses}
    # the SE comes from the hypothesis attaining the minimum LCB, never the smallest SD
    worst = min(analyses, key=lambda a: _lcb(a, "stress_sd") or 0.0).rates["stress_sd"].boot
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
        "r_lo_se_cluster_boot": None if worst is None or None in lcbs.values() else worst.se,
        "r_lo_k1": min(a.rates["stress_k1"].point or 0.0 for a in analyses),
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
