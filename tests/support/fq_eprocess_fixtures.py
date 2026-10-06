"""Deterministic F7b take fixtures shared by the e-process, KILL and evaluator tests.

Pure data: no production import, so a scratch run of the F5 Monte-Carlo
(`scripts/analysis/fq_mc_eprocess.py`) can consume the very same rows that the tests feed to the
production code. `be` is the HAIRCUT break-even (`_break_even` in `fq_mc_livedata.py`: ask + one
tick + fee); `raw_ask` is the executable quote the live rule saw (F7B-R21): the Z comparator and
BSS-on-takes use `raw_ask`, BE and X use `be`.
"""

from __future__ import annotations

import datetime as dt
from typing import Final

BASE_DAY: Final = dt.date(2026, 3, 1)
BASE_TS_NS: Final = 1_772_323_200_000_000_000  # 2026-03-01T00:00:00Z
DAY_NS: Final = 86_400 * 1_000_000_000
SECOND_NS: Final = 1_000_000_000

#: (day_index, offset_seconds, station, rung_id, side, raw_ask, be, p_model, h, void)
Row = tuple[int, int, str, str, str, float, float, float, int | None, bool]

# `be` values are `_break_even(ask, LoopConfig())` repr()s from one scratch run.
_BE_015: Final = 0.1693408
_BE_020: Final = 0.22153005000000003
_BE_030: Final = 0.32486605
_BE_035: Final = 0.3760128
_BE_045: Final = 0.4772638
_BE_050: Final = 0.52736805

#: Rows are listed OUT of decision order on purpose.
FIXTURE_A: Final[tuple[Row, ...]] = (
    # day 0: a win and a loss
    (0, 200, "KSFO", "r2", "no", 0.35, _BE_035, 0.50, 0, False),
    (0, 100, "KNYC", "r1", "yes", 0.20, _BE_020, 0.35, 1, False),
    # day 1: one win
    (1, 50, "KNYC", "r3", "yes", 0.45, _BE_045, 0.60, 1, False),
    # day 2: three takes tied at one instant, then a void
    (2, 300, "KNYC", "r9", "yes", 0.30, _BE_030, 0.40, None, True),
    (2, 100, "KSFO", "r2", "yes", 0.50, _BE_050, 0.62, 0, False),
    (2, 100, "KNYC", "r2", "yes", 0.20, _BE_020, 0.35, 1, False),
    (2, 100, "KNYC", "r1", "no", 0.35, _BE_035, 0.50, 0, False),
    # day 3: covered, zero takes
    # day 4: both clipped wins/losses at the upside cap (be < 1/(1+x_max))
    (4, 100, "KSFO", "r1", "yes", 0.15, _BE_015, 0.30, 0, False),
    (4, 100, "KNYC", "r1", "yes", 0.15, _BE_015, 0.30, 1, False),
    # day 5: four takes, so takes are left uncounted at m_cap 2 and 3
    (5, 40, "KNYC", "r4", "yes", 0.35, _BE_035, 0.55, 1, False),
    (5, 10, "KNYC", "r1", "yes", 0.20, _BE_020, 0.35, 1, False),
    (5, 30, "KSFO", "r1", "no", 0.35, _BE_035, 0.55, 0, False),
    (5, 20, "KNYC", "r2", "yes", 0.45, _BE_045, 0.60, 1, False),
    # day 6: a void occupies the first slot, then a win
    (6, 20, "KNYC", "r2", "yes", 0.45, _BE_045, 0.60, 1, False),
    (6, 10, "KSFO", "r5", "yes", 0.30, _BE_030, 0.40, None, True),
    # day 7: one loss
    (7, 10, "KSFO", "r2", "yes", 0.50, _BE_050, 0.62, 0, False),
)
FIXTURE_A_DAYS: Final = 8
FIXTURE_A_COVERED: Final = tuple(range(FIXTURE_A_DAYS))


def fixture_b() -> tuple[Row, ...]:
    """A 40-day losing book: two takes a day, a win only in the first slot of every 8th day."""
    rows: list[Row] = []
    for d in range(40):
        win = 1 if d % 8 == 0 else 0
        rows.append((d, 10, "KNYC", "r1", "yes", 0.35, _BE_035, 0.45, win, False))
        rows.append((d, 20, "KSFO", "r2", "yes", 0.35, _BE_035, 0.45, 0, False))
    return tuple(rows)


FIXTURE_B_DAYS: Final = 40


def fixture_c() -> tuple[Row, ...]:
    """A 24-day winning book: two takes a day, the first wins 3 days in 4, the second every other
    day. The e-process crosses at alpha 0.05 (bar 20) well inside the window."""
    rows: list[Row] = []
    for d in range(24):
        rows.append(
            (d, 10, "KNYC", "r1", "yes", 0.35, _BE_035, 0.55, 0 if d % 4 == 3 else 1, False)
        )
        rows.append(
            (d, 20, "KSFO", "r2", "yes", 0.20, _BE_020, 0.35, 1 if d % 2 == 0 else 0, False)
        )
    return tuple(rows)


FIXTURE_C_DAYS: Final = 24


def fixture_d() -> tuple[Row, ...]:
    """A 60-day losing book WITH clipped days: the first slot is a longshot (be .169, X clipped from
    4.9 to x_max 4) that wins every 12th day, the second slot always loses. KILL fires."""
    rows: list[Row] = []
    for d in range(60):
        win = 1 if d % 12 == 0 else 0
        rows.append((d, 10, "KNYC", "r1", "yes", 0.15, _BE_015, 0.30, win, False))
        rows.append((d, 20, "KSFO", "r2", "yes", 0.35, _BE_035, 0.45, 0, False))
    return tuple(rows)


FIXTURE_D_DAYS: Final = 60


def ts_ns(day_index: int, offset_s: int) -> int:
    return BASE_TS_NS + day_index * DAY_NS + offset_s * SECOND_NS


def climate_day(day_index: int) -> dt.date:
    return BASE_DAY + dt.timedelta(days=day_index)
