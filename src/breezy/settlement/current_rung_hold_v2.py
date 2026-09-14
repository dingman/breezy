"""PREREG v2 sequential score, strata, and verdict rules for `current_rung_hold`.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b (SS3,
ruling `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md`
statistic C) and `docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`
commits 4/5.

Pure module -- no I/O, no Nautilus, no `scripts/` import
(`tests/unit/test_settlement_purity_guard.py`). v1
(`scripts/analysis/mb_current_rung_edge_study.py`,
`scripts/analysis/live_family_tally.py`) is byte-unmodified and is never
imported here (`tests/unit/test_prereg_v1_is_byte_unmodified.py`); this
module is a SIBLING statistic, not a replacement wired into v1's live path.

Statistic (rev b Sec 3, ruling option C): under H0, `held_i | ask_i ~
Bern(BE_i)` with `BE_i` known per-row, so the numerator
`Sum(held_i - BE_i)` has independent increments -- unlike a re-estimated
plug-in `pi_k` (`x(1-x)` is concave, so `n*pi*(1-pi) >= Sum(BE_i*(1-BE_i))`,
ruling line 9). `score()` computes:

    I = Sum_i BE_i * (1 - BE_i)             # observed statistical information
    S = Sum_i (held_i - BE_i) / sqrt(I)     # per-row centred score

`information_fraction` reports `t = min(1, I / I_max)` where `I_max = 40`
(`n_max=160 * 1/4`, the Bernoulli variance bound) is supplied by the
caller -- never re-derived here (rev b Sec 3: "fixed before first fill").

`StratumV2.cell_dead` inlines the Wilson score interval from
`scripts/analysis/archive_correction_probe.py:352-363` (restated, not
imported, to avoid a `src/` -> `scripts/` edge) against `pi = mean(BE_i)`
per rev b Sec 5/6 (the concave-fee BE amendment), at the v1 fixed-rule
floor `n >= 60` (`mb_current_rung_edge_study.py:717-719`).

`look_verdict`/`terminal_look` implement rev b Sec 3/4's SURVIVE/KILL/
CONTINUE truth table, including the fail-closed interior band
(`b_fut < S < b_eff` at truncation is KILL, never CONTINUE -- CONTINUE is
illegal at a terminal look) and the unconditional `LOSS_STOP` KILL.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

__all__ = [
    "Z_95",
    "CombinedDraw",
    "ScoreState",
    "StationDayAdmissionRefusal",
    "StratumRow",
    "StratumV2",
    "TruncationReason",
    "break_even_row",
    "build_stratum_v2",
    "combine_station_day",
    "information_fraction",
    "look_verdict",
    "score",
    "score_combined",
    "terminal_look",
]

#: Two-sided 95% normal quantile. Value restated from
#: `scripts/analysis/archive_correction_probe.py:66`
#: (`Z_95: Final[float] = 1.959963984540054`), itself the terminal critical
#: value v1 froze (PREREG v2 rev b Sec 2). Never imported: this module must
#: stay `scripts/`-free (`test_settlement_purity_guard.py`, and the layer
#: contract `src/` never imports `scripts/`).
Z_95: Final[float] = 1.959963984540054


def break_even_row(entry_ask: Decimal, fee: Decimal) -> Decimal:
    """`BE_i = entry_ask_i + fee_i` -- rev b Sec 5's per-row break-even.

    Deliberately NOT `break_even(mean_ask)` (v1's registered analysis BE,
    `mb_current_rung_edge_study.py:179-181`): the venue fee is concave in
    ask, so that form overstates the true hurdle relative to `mean(BE_i)`
    by Jensen's inequality (rev b Sec 5).
    """
    return entry_ask + fee


@dataclass(frozen=True, slots=True, kw_only=True)
class StratumRow:
    """One filled Take's inputs to the v2 score/strata, adapter-shaped so
    this module never depends on `ScoredTrial`'s 17-column schema.

    `qty` (Increment A, plan S4a / operator ruling 2026-09-14, R3-2): a
    PARAMETER fixed at `Decimal(1)` by every real caller today -- never a
    literal average. It exists so :func:`combine_station_day`'s exact
    mutual-exclusivity variance (R3-3) is qty-weighted by construction,
    letting Increment B (S4b) wire real qty through additively, with no
    change to this dataclass or `combine_station_day`'s formula.
    """

    entry_ask: Decimal
    fee: Decimal
    held: bool
    station: str
    qty: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreState:
    """`S`, the observed information `I`, and the filled count `n` at a look."""

    s: float
    information: float
    n: int


def score(rows: list[StratumRow] | tuple[StratumRow, ...]) -> ScoreState:
    """`S = Sum(held_i - BE_i) / sqrt(I)`, `I = Sum BE_i(1 - BE_i)`.

    Raises `ValueError` if `I <= 0` -- undefined, never silently `0.0`
    (rev b Sec 3; the same "a rate over nothing is undefined" discipline
    `RealizedStratum`/`build_realized_stratum` already use for v1).
    """
    bes = [float(break_even_row(row.entry_ask, row.fee)) for row in rows]
    information = sum(be * (1.0 - be) for be in bes)
    if information <= 0:
        raise ValueError(
            "score() is undefined at I <= 0 (no rows, or every BE_i in "
            "{0.0, 1.0}); refusing to return a degenerate 0.0"
        )
    numerator = sum(
        (1.0 if row.held else 0.0) - be for row, be in zip(rows, bes, strict=True)
    )
    s = numerator / math.sqrt(information)
    return ScoreState(s=s, information=information, n=len(rows))


class StationDayAdmissionRefusal(ValueError):
    """Raised by :func:`combine_station_day` when a station-day's
    constituent break-evens sum above 1.

    Enforced AT DRAW CONSTRUCTION, never post-hoc (R3-3, plan S4a /
    operator ruling 2026-09-14): the whole station-day is refused before
    `I`/`S` are ever touched, rather than admitted with an out-of-range
    `Var_H0` term silently corrupting the pooled information sum.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class CombinedDraw:
    """One station-day's combined draw under the exact mutual-exclusivity
    statistic (R3-3, plan S4a / operator ruling 2026-09-14).

    For taken rungs `i=1..k` on one station-day (mutually exclusive by
    `RungBounds`/`_rung_index` construction, so `Cov(held_i, held_j) =
    -BE_i*BE_j` under H0):

        x        = Sum_i qty_i * (held_i - BE_i)
        variance = Sum_i qty_i^2 * BE_i*(1 - BE_i)
                   - 2 * Sum_{i<j} qty_i*qty_j*BE_i*BE_j

    Built only by :func:`combine_station_day`. At k=1, qty=1 this reduces
    to `held - BE` and `BE*(1 - BE)` -- byte-identical to one `StratumRow`'s
    own contribution inside :func:`score`.
    """

    x: float
    variance: float
    n_constituents: int


def combine_station_day(rows: Sequence[StratumRow] | tuple[StratumRow, ...]) -> CombinedDraw:
    """Build one station-day's :class:`CombinedDraw` from its constituent
    (mutually exclusive) rung fills (R3-3, plan S4a).

    Raises :class:`StationDayAdmissionRefusal` if `Sum_i BE_i > 1` for this
    station-day -- the admission gate fires here, at draw construction,
    before any `I`/`S` arithmetic ever sees the row. Raises `ValueError` for
    an empty ``rows`` -- a combined draw over nothing is undefined, matching
    :func:`score`'s own "no rows" refusal.
    """
    rows = tuple(rows)
    if not rows:
        raise ValueError("combine_station_day() is undefined for an empty station-day")
    bes = [float(break_even_row(row.entry_ask, row.fee)) for row in rows]
    qtys = [float(row.qty) for row in rows]
    if sum(bes) > 1.0:
        raise StationDayAdmissionRefusal(
            f"station {rows[0].station!r}: constituent break-evens sum to "
            f"{sum(bes)!r} > 1 -- refusing the whole station-day as "
            "malformed_input before scoring (R3-3 admission gate)"
        )
    x = sum(
        qty * ((1.0 if row.held else 0.0) - be)
        for row, be, qty in zip(rows, bes, qtys, strict=True)
    )
    variance = sum(qty * qty * be * (1.0 - be) for be, qty in zip(bes, qtys, strict=True))
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            variance -= 2.0 * qtys[i] * qtys[j] * bes[i] * bes[j]
    return CombinedDraw(x=x, variance=variance, n_constituents=len(rows))


def score_combined(draws: Sequence[CombinedDraw] | tuple[CombinedDraw, ...]) -> ScoreState:
    """`S`/`I`/`n` over station-day :class:`CombinedDraw`\\ s (R3-3, plan
    S4a): `I = Sum_sd Var_H0(X_sd)`, `S = Sum_sd X_sd / sqrt(I)`, `n` is the
    number of station-day DRAWS (the registered trial unit, M2), never the
    number of constituent fills.

    Raises `ValueError` at `I <= 0`, mirroring :func:`score`.
    """
    information = sum(draw.variance for draw in draws)
    if information <= 0:
        raise ValueError(
            "score_combined() is undefined at I <= 0 (no draws, or every "
            "draw's variance is 0); refusing to return a degenerate 0.0"
        )
    numerator = sum(draw.x for draw in draws)
    s = numerator / math.sqrt(information)
    return ScoreState(s=s, information=information, n=len(draws))


def information_fraction(information: float, *, i_max: float) -> float:
    """`t = min(1, I / I_max)` -- rev b Sec 3, `I_max` fixed by the caller."""
    return min(1.0, information / i_max)


def _wilson_interval(hit_count: int, sample_count: int, *, z: float = Z_95) -> tuple[float, float]:
    """Restated verbatim from `archive_correction_probe.py:352-363`
    (equivalence asserted in `tests/unit/test_current_rung_hold_v2_strata.py`
    against 200 random `(k, n)` pairs, imported there only, never here)."""
    if sample_count == 0:
        return (0.0, 0.0)
    phat = hit_count / sample_count
    denom = 1 + z * z / sample_count
    center = (phat + z * z / (2 * sample_count)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * sample_count)) / sample_count) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass(frozen=True, slots=True, kw_only=True)
class StratumV2:
    """One v2 stratum (pooled/station/ask-band), fixed-rule `cell_dead`
    against `pi = mean(BE_i)` (rev b Sec 5/6) -- no sequential monitoring
    here; only the pooled `ScoreState` is monitored sequentially."""

    label: str
    n: int
    k: int
    mean_ask: Decimal
    pi: Decimal
    wilson_lower: float
    wilson_upper: float

    @property
    def cell_dead(self) -> bool:
        """Wilson-95% UPPER below `mean(BE_i)`, at the v1 fixed floor `n >= 60`."""
        return self.n >= 60 and self.wilson_upper < float(self.pi)


def build_stratum_v2(
    label: str, rows: list[StratumRow] | tuple[StratumRow, ...]
) -> StratumV2 | None:
    """`None` for an empty stratum -- a rate over nothing is undefined."""
    rows = tuple(rows)
    if not rows:
        return None
    n = len(rows)
    k = sum(1 for row in rows if row.held)
    mean_ask = sum((row.entry_ask for row in rows), start=Decimal(0)) / n
    pi = sum((break_even_row(row.entry_ask, row.fee) for row in rows), start=Decimal(0)) / n
    wilson_lower, wilson_upper = _wilson_interval(k, n)
    return StratumV2(
        label=label,
        n=n,
        k=k,
        mean_ask=mean_ask,
        pi=pi,
        wilson_lower=wilson_lower,
        wilson_upper=wilson_upper,
    )


def look_verdict(
    state: ScoreState,
    *,
    b_eff: float,
    b_fut: float,
    total_pnl: Decimal,
    cell_dead: bool,
    structural_fired: bool,
) -> Literal["SURVIVE", "KILL", "CONTINUE"]:
    """Interim-look verdict (rev b Sec 3).

    SURVIVE <=> S >= b_eff AND total_pnl > 0 AND no cell_dead AND not structural_fired
    KILL    <=> S <= b_fut OR cell_dead OR structural_fired
    else CONTINUE.

    `+-inf` boundaries are valid inputs (a degenerate tied-information look,
    `docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Sec 7 tie guard):
    `S >= float("inf")` and `S <= float("-inf")` are both false for any
    finite `S`, so the look is CONTINUE-forced unless `cell_dead` or
    `structural_fired` independently fires KILL.
    """
    if state.s >= b_eff and total_pnl > 0 and not cell_dead and not structural_fired:
        return "SURVIVE"
    if state.s <= b_fut or cell_dead or structural_fired:
        return "KILL"
    return "CONTINUE"


@enum.unique
class TruncationReason(enum.StrEnum):
    """Rev b Sec 4's three truncation triggers."""

    D0_165 = "D0_165"
    LOSS_STOP = "LOSS_STOP"
    I_MAX = "I_MAX"


def terminal_look(
    state: ScoreState,
    *,
    reason: TruncationReason,
    b_eff: float,
    b_fut: float,
    total_pnl: Decimal,
    cell_dead: bool,
    structural_fired: bool = False,
) -> Literal["SURVIVE", "KILL"]:
    """Terminal verdict at truncation (rev b Sec 4). `CONTINUE` is illegal
    here by construction (the return type admits only SURVIVE/KILL).

    `LOSS_STOP` -> KILL unconditionally (SURVIVE needs `total_pnl > 0`,
    impossible at a loss stop; any efficacy remaining-alpha computation
    would be vacuous, rev b Sec 4). Structural-dead is a separate KILL
    authority and cannot be substituted by the clock.

    Otherwise, an inconclusive interior score (`b_fut < S < b_eff`) is
    fail-closed to KILL -- the family is stopping at the clock, not
    continuing (rev b Sec 4). `D0_165`/`I_MAX` admit SURVIVE only with
    `S >= b_eff AND total_pnl > 0 AND no cell_dead`; anything else is KILL.
    """
    if structural_fired:
        return "KILL"
    if reason is TruncationReason.LOSS_STOP:
        return "KILL"
    if b_fut < state.s < b_eff:
        return "KILL"
    if state.s >= b_eff and total_pnl > 0 and not cell_dead:
        return "SURVIVE"
    return "KILL"
