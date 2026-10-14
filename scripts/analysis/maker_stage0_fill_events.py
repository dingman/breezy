"""MAKER-S2 WP4: event model, clock shift, clock-offset pre-pass and leakage asserts (pure).

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` WP4 (L148-172) and r4
delta (i)3. No I/O; the fill simulator (``maker_stage0_fill``) consumes these types. Prices are
integer cents so level equality is exact; sizes are contracts (driver applies the ``TradeUnit``).
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol

NS_PER_MIN: int = 60_000_000_000
NS_PER_HOUR: int = 60 * NS_PER_MIN
CENTS: int = 100  # YES price + NO price
S7_DELTA_BOUND_NS: int = 10 * NS_PER_MIN  # r4 delta (i)3: any delta > 10 min aborts the run

BUYER: str = "BUYER"  # YES-buyer aggressor (direction fixed by WP0); the only credited side
SELLER: str = "SELLER"
NO_AGGRESSOR: str = "NO_AGGRESSOR"  # never credited

Level = tuple[int, float]  # (price in cents, displayed size)


class Kind(enum.IntEnum):
    """Equal-ts priority (plan L150): cancels precede credits; same-ts frames follow prints."""

    GAP_START = 0
    CANCEL = 1
    PRINT = 2
    DEPTH = 3
    GAP_END = 4
    FORECAST_RELEASE = 5
    DECIDE = 6  # decisions run after every event of their timestamp (see ``_Pass.run``)


class LeakageError(RuntimeError):
    """A look-ahead or ordering invariant of plan L168-170 was violated."""


class DeltaBoundExceeded(RuntimeError):
    """S-7: a recorder clock offset above ten minutes voids the whole run before any scoring."""


@dataclass(frozen=True)
class DepthFrame:
    """One book frame; YES asks at ``a`` cents are NO bids at ``100 - a`` cents."""

    rung_id: str
    yes_bids: tuple[Level, ...]
    yes_asks: tuple[Level, ...]
    truncated: bool = False  # a same-ts_event DepthTruncation row exists
    instance_id: str = ""


@dataclass(frozen=True)
class Print:
    rung_id: str
    yes_price_cents: int
    size: float
    aggressor: str
    instance_id: str = ""


@dataclass(frozen=True)
class GapMark:
    rung_id: str | None  # None = the whole recorder


@dataclass(frozen=True)
class Cut:
    """A clock alert. ``resume`` False ends the process-live window for the rest of the day."""

    reason: str  # CANCEL_PROCESS | GTD_EXPIRY | CANCEL_HARD
    resume: bool


@dataclass(frozen=True)
class ForecastVector:
    """The vector in force; the event ts is ``available_at_ns`` (shifted +delta)."""

    available_at_ns: int
    p_yes_point: Mapping[str, float]
    p_yes_upper: Mapping[str, float]
    cycle_runtime_ns: int
    raw_sha256: str
    nbm_era: str


Payload = DepthFrame | Print | GapMark | Cut | ForecastVector


@dataclass(frozen=True, order=True)
class Event:
    """Totally ordered by ``(ts_ns, kind, seq)``; ``seq`` is the source row order."""

    ts_ns: int
    kind: Kind
    seq: int
    payload: Payload = field(compare=False)


def apply_clock_shift(events: Iterable[Event], delta_ns: int) -> tuple[Event, ...]:
    """Forecast releases +|delta|, cancels/process cuts -|delta| (plan L152; leak-safe)."""
    d = abs(delta_ns)
    shifted: list[Event] = []
    for ev in events:
        if ev.kind is Kind.FORECAST_RELEASE:
            ev = replace(ev, ts_ns=ev.ts_ns + d)
        elif ev.kind is Kind.CANCEL:
            ev = replace(ev, ts_ns=ev.ts_ns - d)
        shifted.append(ev)
    return tuple(sorted(shifted))


@dataclass(frozen=True)
class OffsetSample:
    """One ``VenueClockOffset`` observation of a recorder instance."""

    instance_id: str
    ts_ns: int
    offset_ns: int


def instance_day_deltas(
    samples: Sequence[OffsetSample], window_start_ns: int, window_end_ns: int
) -> dict[str, int]:
    """Per recorder instance: max |offset_ns| inside the process-live window (r4 delta (i)3)."""
    out: dict[str, int] = {}
    for s in samples:
        if window_start_ns <= s.ts_ns < window_end_ns:
            out[s.instance_id] = max(out.get(s.instance_id, 0), abs(s.offset_ns))
    return out


def station_day_delta_ns(
    samples: Sequence[OffsetSample], window_start_ns: int, window_end_ns: int
) -> int:
    """A station-day spanning two instances takes the max over both; 0 when no sample."""
    per_instance = instance_day_deltas(samples, window_start_ns, window_end_ns)
    return max(per_instance.values(), default=0)


def assert_delta_within_bound(deltas: Iterable[int]) -> int:
    """S-7 pre-pass: the driver calls it over every station-day before scoring. Returns the max."""
    worst = max((abs(d) for d in deltas), default=0)
    if worst > S7_DELTA_BOUND_NS:
        raise DeltaBoundExceeded(
            f"S-7: clock offset {worst} ns exceeds {S7_DELTA_BOUND_NS} ns; run void before scoring"
        )
    return worst


def assert_leak_free(
    *,
    available_at_ns: int,
    delta_ns: int,
    t0_ns: int,
    depth_ts_used_ns: int,
    filled_ns: int | None,
) -> None:
    """Plan L168-170: ``available_at + delta < t0 <= filled`` and ``depth_ts_used <= t0``."""
    if not available_at_ns + abs(delta_ns) < t0_ns:
        raise LeakageError("forecast vector not strictly before t0 after the clock shift")
    if depth_ts_used_ns > t0_ns:
        raise LeakageError("depth frame used is later than t0")
    if filled_ns is not None and not t0_ns < filled_ns:
        raise LeakageError("fill credited at or before t0")


# ---- selector interface and result records (consumed by ``maker_stage0_fill``) ----------------


@dataclass(frozen=True)
class Desired:
    rung_id: str
    bid_cents: int


@dataclass(frozen=True)
class Decision:
    """Selector output. ``desired`` is in rank order (first = the K1 rung)."""

    desired: tuple[Desired, ...] = ()
    drop_reason: str = "CANCEL_PMIN"  # end reason for live rungs no longer desired
    forecast_valid: bool = True  # drives ``forecast_valid_h``


@dataclass(frozen=True)
class DecisionContext:
    """What a selector may see at a decision instant (all strictly in the past or at ``now_ns``)."""

    now_ns: int
    vector: ForecastVector | None  # latest release whose shifted ts is strictly < now_ns
    books: Mapping[str, DepthFrame]
    live_bids: Mapping[str, int]
    held: frozenset[str]


class RungSelector(Protocol):
    def __call__(self, ctx: DecisionContext, /) -> Decision: ...


@dataclass(frozen=True)
class Episode:
    station: str
    climate_day: str
    rung_id: str
    t0_ns: int
    end_ns: int
    end_reason: str
    bid_cents: int
    a_gt: float
    a_eq: float
    refused_reason: str | None
    filled_ns_base: int | None
    filled_ns_stress: int | None
    gap_ns_subtracted: int
    p_yes_point_live: float | None
    p_yes_upper_live: float | None
    cycle_runtime_ns: int | None
    raw_sha256: str | None
    nbm_era: str | None
    available_at_ns: int | None
    depth_ts_used_ns: int | None
    unit_hypothesis: str

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["bid"] = self.bid_cents / CENTS
        return out


@dataclass(frozen=True)
class StationDaySummary:
    station: str
    climate_day: str
    unit_hypothesis: str
    bid_bearing: bool
    guard_refused_only: bool
    n_attempts: int
    n_episodes: int
    n_refused: int
    n_process_cuts: int
    n_gtd_cuts: int
    rung_trials_posted: int
    rung_trials_filled_base: int
    rung_trials_filled_stress: int
    filled_pairs_base: int
    filled_pairs_stress: int
    k1_rung_id: str | None
    k1_filled_base: int
    k1_filled_stress: int
    bid_median_fills_stress: float | None
    delta_ns: int
    process_live_h: float
    forecast_valid_h: float
    gap_h: float
    covered_live_h: float
    gap_share: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StationDayResult:
    episodes: tuple[Episode, ...]
    summary: StationDaySummary
