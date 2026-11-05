"""MAKER-S2 WP6: raw capture records -> WP4 events, and the station-day replay (no truth, no I/O).

Plan r3 WP6 flow step (1) + r4 delta (e)(i)3. The simulator import closure ends here: this module
may not (transitively) import the truth loader, the verify-first reader or the report.

``build_data_events`` turns one hypothesis' view of the raw records (depth frames, prints, gaps,
truncation rows, per recorder instance) into a totally ordered stream with seq 0..N-1;
``clock_events`` adds the cuts and forecast releases of one variant with seq N.. so the two merge
without re-sequencing the data. Conventions (all conservative for the fill rate):

* a later recorder instance takes over at its START, its first in-window event of ANY kind (depth
  frame, print, gap or truncation row): the earlier instance's later events are dropped and its
  open gaps end at the hand-over (the sim's "current instance" is single);
* one print per ``trade_id`` (first instance wins), ``NO_AGGRESSOR`` prints are never emitted;
* print sizes floor to whole contracts (fewer credited), depth sizes ceil (a longer queue); the
  number of prints floored to zero and of depth levels raised by the ceil are counted per build;
* a depth level is a YES level; a bid level is converted for a SELLER taker, an ask for a BUYER;
* per rung, the last frame before the window is kept as the opening book.
"""

from __future__ import annotations

import datetime as dt
import heapq
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from scripts.analysis.maker_stage0_adapter import MAX_RUNGS_PASSED, WantTracker
from scripts.analysis.maker_stage0_fill import simulate_station_day
from scripts.analysis.maker_stage0_fill_events import (
    BUYER,
    CENTS,
    NO_AGGRESSOR,
    SELLER,
    Cut,
    DepthFrame,
    Episode,
    Event,
    ForecastVector,
    GapMark,
    Kind,
    Level,
    Print,
    RungSelector,
    StationDayResult,
)
from scripts.analysis.maker_stage0_pno_store import site

__all__ = [
    "BuiltEvents",
    "CutSpec",
    "DataEvents",
    "EventBuildError",
    "InstanceSlice",
    "LocalDayViolation",
    "RawFrame",
    "RawGap",
    "RawPrint",
    "RawTruncation",
    "ReplayResult",
    "assert_before_local_midnight",
    "build_data_events",
    "clock_events",
    "merge_events",
    "replay_station_day",
    "simulate_station_day",
]

DEPTH_LEVELS: Final[int] = 10  # OrderBookDepth10 carries exactly ten levels per side
_NS_PER_HOUR: Final[int] = 3_600 * 10**9
_END_OF_TIME: Final[int] = 2**62
_CENT: Final[Decimal] = Decimal(CENTS)

SizeConverter = Callable[[Decimal, Decimal, str | None], Decimal]
BuiltEvents = tuple[Event, ...]


class EventBuildError(ValueError):
    """A capture record cannot be expressed as a WP4 event (non-cent price, bad side)."""


class LocalDayViolation(RuntimeError):
    """S-6: an episode extends past local midnight starting D (the window premise is wrong)."""


@dataclass(frozen=True, slots=True)
class RawFrame:
    rung: str
    ts_ns: int
    bids: tuple[tuple[Decimal, Decimal], ...]  # (YES price, size); pad levels have size 0
    asks: tuple[tuple[Decimal, Decimal], ...]


@dataclass(frozen=True, slots=True)
class RawPrint:
    trade_id: str
    rung: str
    ts_ns: int
    price: Decimal
    size: Decimal
    aggressor: str


@dataclass(frozen=True, slots=True)
class RawGap:
    rung: str
    start_ns: int
    end_ns: int | None  # None = unresolved: runs on


@dataclass(frozen=True, slots=True)
class RawTruncation:
    rung: str
    ts_ns: int
    bid_levels_seen: int
    ask_levels_seen: int


@dataclass(frozen=True, slots=True)
class InstanceSlice:
    instance_id: str
    frames: Sequence[RawFrame] = ()
    prints: Sequence[RawPrint] = ()
    gaps: Sequence[RawGap] = ()
    truncations: Sequence[RawTruncation] = ()


@dataclass(frozen=True, slots=True)
class CutSpec:
    ts_ns: int
    reason: str
    resume: bool


@dataclass(frozen=True, slots=True)
class DataEvents:
    events: BuiltEvents
    n_depth_frames: int  # frames INSIDE the window (coverage), not the opening books
    rungs_with_books: frozenset[str]
    n_no_aggressor: int = 0
    n_levels: int = 0  # depth levels emitted (D4 denominator)
    n_levels_ceil_raised: int = 0  # levels whose size the ceil raised (a longer queue)
    n_prints: int = 0  # prints emitted
    n_prints_floored_zero: int = 0  # prints that the floor credited as zero contracts

    @property
    def n_events(self) -> int:
        return len(self.events)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    result: StationDayResult
    n_no_book_wants: int
    n_events: int


# --- data events --------------------------------------------------------------------------------


def _cents(price: Decimal) -> int:
    scaled = price * _CENT
    cents = int(scaled)
    if scaled != cents:
        raise EventBuildError(f"price {price} is not a whole cent")
    return cents


@dataclass
class _Tally:
    """Rounding counts of one ``build_data_events`` call (D4 disclosure)."""

    levels: int = 0
    levels_raised: int = 0
    prints: int = 0
    prints_floored_zero: int = 0


def _levels(
    raw: Iterable[tuple[Decimal, Decimal]], size_of: SizeConverter, taker: str, tally: _Tally
) -> tuple[Level, ...]:
    out: list[Level] = []
    for price, size in raw:
        if size <= 0 or not 0 < price < 1:
            continue  # size-0 pad levels, or a price outside the open unit interval
        exact = size_of(size, price, taker)
        contracts = math.ceil(exact)
        tally.levels += 1
        tally.levels_raised += contracts != exact
        out.append((_cents(price), contracts))
    return tuple(out)


def _first_ts(sl: InstanceSlice) -> int:
    """The instance's START: its first in-window event of any kind."""
    stamps = [
        *(f.ts_ns for f in sl.frames),
        *(p.ts_ns for p in sl.prints),
        *(g.start_ns for g in sl.gaps),
        *(t.ts_ns for t in sl.truncations),
    ]
    return min(stamps) if stamps else _END_OF_TIME


def _segments(slices: Sequence[InstanceSlice]) -> list[tuple[InstanceSlice, int, int]]:
    """(slice, start, end): a later instance's start (first event) ends the earlier segment."""
    ordered = sorted(slices, key=lambda s: (_first_ts(s), s.instance_id))
    firsts = [_first_ts(s) for s in ordered]
    return [
        (s, firsts[i], firsts[i + 1] if i + 1 < len(ordered) else _END_OF_TIME)
        for i, s in enumerate(ordered)
    ]


def _flags(sl: InstanceSlice) -> dict[tuple[str, int], tuple[bool, bool]]:
    return {
        (t.rung, t.ts_ns): (t.ask_levels_seen > DEPTH_LEVELS, t.bid_levels_seen > DEPTH_LEVELS)
        for t in sl.truncations
    }


def _frame_events(
    sl: InstanceSlice, lo: int, hi: int, window: tuple[int, int], size_of: SizeConverter,
    tally: _Tally,
) -> tuple[list[tuple[int, Kind, Event]], int]:  # fmt: skip
    flags, kept, inside = _flags(sl), {}, 0
    rows: list[tuple[int, Kind, Event]] = []
    for frame in sorted(sl.frames, key=lambda f: f.ts_ns):
        if not lo <= frame.ts_ns < hi or frame.ts_ns >= window[1]:
            continue
        if frame.ts_ns < window[0]:
            kept[frame.rung] = frame  # only the last pre-window book per rung survives
            continue
        rows.append(_depth_row(frame, sl.instance_id, flags, size_of, tally))
        inside += 1
    rows.extend(_depth_row(f, sl.instance_id, flags, size_of, tally) for f in kept.values())
    return rows, inside


def _depth_row(
    frame: RawFrame,
    instance: str,
    flags: dict[tuple[str, int], tuple[bool, bool]],
    size_of: SizeConverter,
    tally: _Tally,
) -> tuple[int, Kind, Event]:
    asks_t, bids_t = flags.get((frame.rung, frame.ts_ns), (False, False))
    payload = DepthFrame(
        rung_id=frame.rung, ts_ns=frame.ts_ns,
        yes_bids=_levels(frame.bids, size_of, SELLER, tally),
        yes_asks=_levels(frame.asks, size_of, BUYER, tally),
        asks_truncated=asks_t, bids_truncated=bids_t, instance_id=instance,
    )  # fmt: skip
    return frame.ts_ns, Kind.DEPTH, Event(frame.ts_ns, Kind.DEPTH, 0, payload)


def _print_events(
    sl: InstanceSlice, lo: int, hi: int, window: tuple[int, int], size_of: SizeConverter,
    seen: set[str], tally: _Tally,
) -> tuple[list[tuple[int, Kind, Event]], int]:  # fmt: skip
    rows: list[tuple[int, Kind, Event]] = []
    dropped = 0
    for pr in sorted(sl.prints, key=lambda p: p.ts_ns):
        if not lo <= pr.ts_ns < hi or not window[0] <= pr.ts_ns < window[1]:
            continue
        if pr.aggressor == NO_AGGRESSOR:
            dropped += 1
            continue
        if pr.trade_id in seen:
            continue
        seen.add(pr.trade_id)
        exact = size_of(pr.size, pr.price, pr.aggressor)
        size = math.floor(exact)
        tally.prints += 1
        tally.prints_floored_zero += size == 0 and exact > 0
        payload = Print(pr.rung, _cents(pr.price), size, pr.aggressor, sl.instance_id)
        rows.append((pr.ts_ns, Kind.PRINT, Event(pr.ts_ns, Kind.PRINT, 0, payload)))
    return rows, dropped


def _gap_events(
    sl: InstanceSlice, lo: int, hi: int, window: tuple[int, int]
) -> list[tuple[int, Kind, Event]]:
    """GAP_START/GAP_END rows clipped to the instance's segment; the last open gap runs on."""
    rows: list[tuple[int, Kind, Event]] = []
    for gap in sl.gaps:
        start = max(gap.start_ns, lo)
        if gap.end_ns is None:
            end = None if hi == _END_OF_TIME else hi
        else:
            end = min(gap.end_ns, hi)
        if start >= window[1] or (end is not None and end <= window[0]):
            continue
        mark = GapMark(gap.rung)
        rows.append((start, Kind.GAP_START, Event(start, Kind.GAP_START, 0, mark)))
        if end is not None:
            rows.append((end, Kind.GAP_END, Event(end, Kind.GAP_END, 0, mark)))
    return rows


def build_data_events(
    slices: Sequence[InstanceSlice], *, size_of: SizeConverter, window: tuple[int, int]
) -> DataEvents:
    """One hypothesis' totally ordered data events (frames, prints, gaps) inside ``window``."""
    rows: list[tuple[int, Kind, Event]] = []
    seen: set[str] = set()
    tally = _Tally()
    inside = no_aggressor = 0
    for sl, lo, hi in _segments(slices):
        frames, n = _frame_events(sl, lo, hi, window, size_of, tally)
        prints, skipped = _print_events(sl, lo, hi, window, size_of, seen, tally)
        rows += [*frames, *prints, *_gap_events(sl, lo, hi, window)]
        inside, no_aggressor = inside + n, no_aggressor + skipped
    rows.sort(key=lambda r: (r[0], r[1]))  # stable: source order breaks ties
    events = tuple(
        Event(ts, kind, seq, event.payload) for seq, (ts, kind, event) in enumerate(rows)
    )
    books = frozenset(e.payload.rung_id for e in events if isinstance(e.payload, DepthFrame))
    return DataEvents(
        events, inside, books, no_aggressor,
        tally.levels, tally.levels_raised, tally.prints, tally.prints_floored_zero,
    )  # fmt: skip


# --- clock events -------------------------------------------------------------------------------


def clock_events(
    cuts: Iterable[CutSpec], releases: Iterable[ForecastVector], *, first_seq: int = 1 << 40
) -> BuiltEvents:
    """Cuts (``CANCEL``) and forecast releases, sequenced after every data event."""
    rows: list[tuple[int, Kind, object]] = [
        (c.ts_ns, Kind.CANCEL, Cut(c.reason, c.resume)) for c in cuts
    ]
    rows += [(v.available_at_ns, Kind.FORECAST_RELEASE, v) for v in releases]
    rows.sort(key=lambda r: (r[0], r[1]))
    return tuple(
        Event(ts, kind, first_seq + i, payload)  # type: ignore[arg-type]
        for i, (ts, kind, payload) in enumerate(rows)
    )


def merge_events(data: DataEvents, clock: BuiltEvents) -> BuiltEvents:
    """Merge two individually sorted streams into the canonical total order."""
    return tuple(heapq.merge(data.events, clock))


# --- replay -------------------------------------------------------------------------------------


def _local_midnight_ns(station: str, day: dt.date) -> int:
    """00:00 local STANDARD time starting ``day`` as UTC ns (offset is east-positive)."""
    utc = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
    return int(utc.timestamp()) * 10**9 - int(site(station).offset_hours * _NS_PER_HOUR)


def assert_before_local_midnight(episode: Episode, station: str, day: dt.date) -> None:
    """S-6: no episode may extend past the local midnight that starts climate day D."""
    limit = _local_midnight_ns(station, day)
    if episode.end_ns > limit:
        raise LocalDayViolation(
            f"S-6: {station} {day} episode {episode.rung_id} ends {episode.end_ns} after local "
            f"midnight {limit}; the observation-cancel premise is wrong"
        )


def replay_station_day(
    data: DataEvents,
    clock: BuiltEvents,
    *,
    selector: RungSelector,
    tracker: WantTracker,
    station: str,
    day: dt.date,
    unit_hypothesis: str,
    live_from_ns: int,
    delta_ns: int,
) -> ReplayResult:
    """Run WP4 over the merged stream (the S-6 assertion runs per episode in the driver)."""
    events = merge_events(data, clock)
    result = simulate_station_day(
        events,
        selector,
        station=station,
        climate_day=day.isoformat(),
        unit_hypothesis=unit_hypothesis,
        live_from_ns=live_from_ns,
        delta_ns=delta_ns,
        max_rungs=MAX_RUNGS_PASSED,
    )
    never_booked = tracker.wanted_without_book - data.rungs_with_books
    return ReplayResult(result, len(never_booked), len(events))
