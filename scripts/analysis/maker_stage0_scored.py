"""MAKER-S2 WP5 statistics over scored rows / station-days: section 6.9, bid stats, days to 200.

Split out of ``maker_stage0_verdict`` (plan ceiling 400 lines; re-exported there). Pure.
"""

from __future__ import annotations

from collections.abc import Sequence
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
