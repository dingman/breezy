"""MAKER-S2 WP5 statistics over scored rows / station-days: 6.9, expectancy, bid stats, days to 200.

Split out of ``maker_stage0_verdict`` (plan ceiling 400 lines; re-exported there). Pure.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Final

from scripts.analysis import maker_stage0_stats as st
from scripts.analysis.maker_stage0_rows import PosRow, SdRow, nz

OUTCOME_NO: Final[str] = "NO"
OUTCOME_VOID: Final[str] = "VOID"  # excluded from section 6.9; refund 0 in the expectancy
NO_FINAL: Final[str] = ""  # no CLI FINAL: excluded from section 6.9 and counted
_LOSSES: Final[frozenset[str]] = frozenset({"YES", "UNRESOLVED"})  # unresolved past D+14 = LOSS
TARGET_POSITIONS: Final[int] = 200
_OUTCOMES: Final[frozenset[str]] = _LOSSES | {OUTCOME_NO, OUTCOME_VOID, NO_FINAL}


class VerdictRefused(ValueError):
    """An input the verdict must not paper over (missing denominator, hypothesis or p)."""


@dataclass(frozen=True)
class Section69(st.Screen):
    """The pooled screen plus the exclusions the report must count (r4 (i)6)."""

    excluded_no_final_filled: int
    excluded_no_final_unfilled: int
    excluded_no_final_days: int
    n_void_excluded: int


def section_69(rows: Sequence[PosRow], *, stressed: bool = False) -> Section69:
    """Pooled 6.9 over the BASE fills (the label); ``stressed=True`` is the report-only block."""

    def filled(r: PosRow) -> bool:
        return r.filled_stress if stressed else r.filled_base

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
            no_final[filled(r)] += 1
            no_final_days.add((r.station, r.climate_day))
        elif r.p_yes_point_live is None:
            raise VerdictRefused(f"scored row {r.position_id} has no p_yes_point_live")
        else:
            loss = r.truth_final in _LOSSES
            kept.append(st.ScreenRow(r.p_yes_point_live, loss, filled(r), r.climate_day))
    screen = st.pooled_screen(kept)
    return Section69(
        **{f.name: getattr(screen, f.name) for f in fields(screen)},
        excluded_no_final_filled=no_final[True],
        excluded_no_final_unfilled=no_final[False],
        excluded_no_final_days=len(no_final_days),
        n_void_excluded=voids,
    )


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


def days_to_200(rows: Sequence[SdRow]) -> dict[str, float | None]:
    """200 / (positions per distinct covered climate date); None when nothing fills."""
    live = [r for r in rows if r.covered and not r.outage_excluded]
    dates = len({r.climate_day for r in live})
    out: dict[str, float | None] = {}
    for key in ("k2_base", "k2_stress", "k1_base", "k1_stress"):
        total = sum(nz(getattr(r, f"positions_filled_{key}")) for r in live)
        out[key] = TARGET_POSITIONS * dates / total if total > 0 else None
    return out


# --- expectancy -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fill:
    climate_day: str
    win: float
    net: float
    p_no: float  # model p_NO; unused (0.0) for a VOID
    void: bool = False

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


@dataclass(frozen=True)
class Expectancy:
    """Base-rule fills: win rate beside mean model p_NO, and ``w - (b + theta b (1 - b))``.

    VOIDs never enter the win rate or ``mean_p_no`` (``n_void`` reports them); the net still
    charges them (w = 0, fee paid, refund assumed 0; spec 6.5). ``n_fills`` includes voids.
    """

    n_fills: int
    n_excluded_no_final: int
    wins: int
    win_rate: float | None
    mean_p_no: float | None
    win_rate_boot: st.BootInterval | None
    win_rate_cp: tuple[float, float] | None
    net_mean: float | None
    net_upper_bound: float | None  # one-sided 95% (climate-date cluster bootstrap)
    n_void: int = 0


def _mean(fills: Sequence[_Fill], pick: Callable[[_Fill], float]) -> float:
    return math.fsum(pick(f) for f in fills) / len(fills) if fills else 0.0


def _scored_fill(r: PosRow, theta: Mapping[tuple[str, str], float]) -> _Fill:
    if (r.station, r.climate_day) not in theta:
        raise VerdictRefused(f"no theta for scored fill {r.position_id}")
    fee = theta[(r.station, r.climate_day)] * r.bid * (1.0 - r.bid)
    win = float(r.truth_final == OUTCOME_NO)
    if r.truth_final == OUTCOME_VOID:
        return _Fill(r.climate_day, 0.0, -(r.bid + fee), 0.0, void=True)
    if r.p_yes_point_live is None:
        raise VerdictRefused(f"scored fill {r.position_id} has no p_yes_point_live")
    return _Fill(r.climate_day, win, win - (r.bid + fee), 1.0 - r.p_yes_point_live)


def expectancy(fills: Sequence[PosRow], theta: Mapping[tuple[str, str], float]) -> Expectancy:
    scored = [_scored_fill(r, theta) for r in fills if r.truth_final != NO_FINAL]
    settled = [f for f in scored if not f.void]
    wins = round(sum(f.win for f in settled))

    def mean_of(pick: Callable[[_Fill], float]) -> Callable[[Sequence[_Fill]], float]:
        return lambda rows: _mean(rows, pick)

    return Expectancy(
        len(scored), len(fills) - len(scored), wins, wins / len(settled) if settled else None,
        _mean(settled, lambda f: f.p_no) if settled else None,
        st.cluster_interval(settled, mean_of(lambda f: f.win)),
        st.clopper_pearson(wins, len(settled)),
        _mean(scored, lambda f: f.net) if scored else None,
        st.cluster_upper_bound(scored, mean_of(lambda f: f.net)),
        len(scored) - len(settled),
    )  # fmt: skip
