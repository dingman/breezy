"""Pure gate arithmetic for the LAT-1 NBP revision-latency study (plan r3, amended r3.1).

No I/O, no Nautilus, no analysis or script imports. Book time is the row's ``ts_init``; the
as-of book at ``t`` is the last row with ``ts_init <= t`` and a row stamped after ``t`` is never
consulted. Quote AGE is never missingness: an unchanged quote under a live heartbeat is present.
Missing is decided only by a covering tape-gap record or a dead heartbeat (R3).
"""

from __future__ import annotations

import bisect
import datetime as dt
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

__all__ = [
    "HEARTBEAT_WINDOW_NS",
    "NS",
    "W_NS",
    "BookRow",
    "BookSeries",
    "ExitBid",
    "GapSpan",
    "MissingClass",
    "RevisionRefused",
    "SignedBands",
    "as_of_snapshot",
    "decision_instant",
    "first_bid_in_window",
    "is_missing",
    "mid",
    "revision",
    "signed_bands",
]

NS: Final[int] = 1_000_000_000
#: R3 heartbeat: some Depth10/QuoteTick row on the station's tape within the last 300 s.
HEARTBEAT_WINDOW_NS: Final[int] = 300 * NS
#: R6 exit window after ``t_exit``.
W_NS: Final[int] = 30 * 60 * NS
REASON_PRESENT: Final[str] = "present"
REASON_GAP: Final[str] = "quote_tape_gap"
REASON_HEARTBEAT: Final[str] = "heartbeat"


class RevisionRefused(ValueError):
    """The two releases cannot be differenced (leak guard 1)."""


class BookRow(NamedTuple):
    """Level-0 book at one tape instant. NaN marks an EMPTY side."""

    ts_init: int
    bid: float
    ask: float


@dataclass(frozen=True, slots=True)
class GapSpan:
    """A recorder outage. ``resolved=False`` covers every later instant (``ended_ns`` unused)."""

    started_ns: int
    ended_ns: int | None
    resolved: bool

    def covers(self, t_ns: int) -> bool:
        if t_ns < self.started_ns:
            return False
        if not self.resolved or self.ended_ns is None:
            return True
        return t_ns <= self.ended_ns


@dataclass(frozen=True, slots=True)
class MissingClass:
    missing: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ExitBid:
    """The exit bid. ``missing_exit`` means NO bid in ``[t_exit, t_exit + W]`` (bid is 0.0)."""

    bid: float
    ts_ns: int | None
    missing_exit: bool
    filled_inside_window: bool
    n_skipped_missing: int = 0


class SignedBands(NamedTuple):
    r_plus: str | None
    r_minus: str | None
    delta_plus: float | None
    delta_minus: float | None


class BookSeries:
    """Rows sorted by ``ts_init`` (stable) with O(log n) as-of lookup."""

    __slots__ = ("_keys", "_rows")

    def __init__(self, rows: Iterable[BookRow]) -> None:
        ordered = sorted(rows, key=lambda row: row.ts_init)
        self._rows: tuple[BookRow, ...] = tuple(ordered)
        self._keys: tuple[int, ...] = tuple(row.ts_init for row in ordered)

    @property
    def rows(self) -> tuple[BookRow, ...]:
        return self._rows

    def as_of(self, t_ns: int) -> BookRow | None:
        index = bisect.bisect_right(self._keys, t_ns)
        return self._rows[index - 1] if index else None

    def after_through(self, lo_ns: int, hi_ns: int) -> tuple[BookRow, ...]:
        """Rows with ``lo_ns < ts_init <= hi_ns``."""
        start = bisect.bisect_right(self._keys, lo_ns)
        stop = bisect.bisect_right(self._keys, hi_ns)
        return self._rows[start:stop]


def _series(rows: Iterable[BookRow] | BookSeries) -> BookSeries:
    return rows if isinstance(rows, BookSeries) else BookSeries(rows)


def revision(
    *,
    prev_p: Mapping[str, float],
    cur_p: Mapping[str, float],
    prev_climate_day: dt.date,
    cur_climate_day: dt.date,
    climate_day: dt.date,
    prev_available_at_ns: int,
    cur_available_at_ns: int,
) -> dict[str, float]:
    """``dP_r = P_cur(r) - P_prev(r)``; refuses releases that are not a same-day ordered pair."""
    if not prev_climate_day == cur_climate_day == climate_day:
        raise RevisionRefused(
            f"climate days differ: prev={prev_climate_day} cur={cur_climate_day} D={climate_day}"
        )
    if prev_available_at_ns >= cur_available_at_ns:
        raise RevisionRefused(
            f"prev available_at {prev_available_at_ns} is not before cur {cur_available_at_ns}"
        )
    absent = sorted(set(cur_p) - set(prev_p))
    if absent:
        raise RevisionRefused(f"rungs missing from the previous release: {absent}")
    return {rung: cur_p[rung] - prev_p[rung] for rung in cur_p}


def signed_bands(delta: Mapping[str, float]) -> SignedBands:
    """``r+`` = argmax dP (> 0), ``r-`` = argmin dP (< 0); ties break on the lower rung id."""
    r_plus: str | None = None
    delta_plus: float | None = None
    r_minus: str | None = None
    delta_minus: float | None = None
    for rung in sorted(delta):
        value = delta[rung]
        if value > 0 and (delta_plus is None or value > delta_plus):
            r_plus, delta_plus = rung, value
        if value < 0 and (delta_minus is None or value < delta_minus):
            r_minus, delta_minus = rung, value
    return SignedBands(r_plus, r_minus, delta_plus, delta_minus)


def decision_instant(available_at_ns: int, lag_ns: int) -> int:
    """``t_dec`` is STRICTLY after ``available_at + L``."""
    return available_at_ns + lag_ns + 1


def as_of_snapshot(rows: Iterable[BookRow] | BookSeries, t_ns: int) -> BookRow | None:
    """The last row with ``ts_init <= t`` (any input order); a later row is never returned."""
    return _series(rows).as_of(t_ns)


def mid(row: BookRow | None) -> float | None:
    """Both sides or nothing: an empty (NaN) side makes the mid missing."""
    if row is None or math.isnan(row.bid) or math.isnan(row.ask):
        return None
    return (row.bid + row.ask) / 2.0


def is_missing(gaps: Sequence[GapSpan], heartbeat_ts: Sequence[int], t_ns: int) -> MissingClass:
    """R3. A covering gap wins; else a dead heartbeat (ascending ``heartbeat_ts``) is missing."""
    if any(gap.covers(t_ns) for gap in gaps):
        return MissingClass(True, REASON_GAP)
    index = bisect.bisect_right(heartbeat_ts, t_ns)
    if index and heartbeat_ts[index - 1] >= t_ns - HEARTBEAT_WINDOW_NS:
        return MissingClass(False, REASON_PRESENT)
    return MissingClass(True, REASON_HEARTBEAT)


def first_bid_in_window(
    rows: Iterable[BookRow] | BookSeries,
    t_exit_ns: int,
    w_ns: int,
    *,
    missing_at: Callable[[int], bool] | None = None,
) -> ExitBid:
    """First instant in ``[t_exit, t_exit + W]`` with a bid: ``t_exit`` itself, then each later
    snapshot's ``ts_init``. A candidate instant that is missing by R3 (``missing_at``) is skipped,
    never carried forward. No bid anywhere in the window gives ``bid = 0`` flagged missing."""
    series = _series(rows)
    skipped = 0
    candidates: list[tuple[int, BookRow | None]] = [(t_exit_ns, series.as_of(t_exit_ns))]
    candidates += [(r.ts_init, r) for r in series.after_through(t_exit_ns, t_exit_ns + w_ns)]
    for instant, row in candidates:
        if row is None or math.isnan(row.bid):
            continue
        if missing_at is not None and missing_at(instant):
            skipped += 1
            continue
        return ExitBid(row.bid, instant, False, instant != t_exit_ns, skipped)
    return ExitBid(0.0, None, True, False, skipped)
