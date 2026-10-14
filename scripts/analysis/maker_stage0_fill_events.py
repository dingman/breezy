"""MAKER-S2 WP4: event model, clock shift, clock-offset pre-pass and leakage asserts (pure).

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` WP4 (L148-172) and r4
delta (i)3. No I/O; the fill simulator (``maker_stage0_fill``) consumes these types. Prices are
integer cents so level equality is exact; sizes are contracts (driver applies the ``TradeUnit``).
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import Any, Protocol

NS_PER_MIN: int = 60_000_000_000
NS_PER_HOUR: int = 60 * NS_PER_MIN
CENTS: int = 100  # YES price + NO price
S7_DELTA_BOUND_NS: int = 10 * NS_PER_MIN  # r4 delta (i)3: any delta > 10 min aborts the run

BUYER: str = "BUYER"  # YES-buyer aggressor (direction fixed by WP0); the only credited side
SELLER: str = "SELLER"
NO_AGGRESSOR: str = "NO_AGGRESSOR"  # never credited

# Selector drop-reason vocabulary (per-rung end reasons for a live rung no longer desired).
CANCEL_PMIN: str = "CANCEL_PMIN"
CANCEL_BFLOOR: str = "CANCEL_BFLOOR"
CANCEL_STALE: str = "CANCEL_STALE"  # forecast older than the staleness bound
CANCEL_DAYMISMATCH: str = "CANCEL_DAYMISMATCH"  # forecast is for a different climate day
CANCEL_HARD: str = "CANCEL_HARD"
NOT_YET_AVAILABLE: str = "NOT_YET_AVAILABLE"  # no forecast vector yet for this rung
DROP_REASONS: frozenset[str] = frozenset(
    {CANCEL_PMIN, CANCEL_BFLOOR, CANCEL_STALE, CANCEL_DAYMISMATCH, CANCEL_HARD, NOT_YET_AVAILABLE}
)


def _flat_fields(obj: Any) -> dict[str, Any]:
    """Shallow field-name -> value dict (all callers' fields are scalars)."""
    return {f.name: getattr(obj, f.name) for f in fields(obj)}


Level = tuple[int, int]  # (price in cents, displayed size in whole contracts)


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


class EventError(ValueError):
    """The event stream is malformed (order, duplicates, price or size domain)."""


class DeltaBoundExceeded(RuntimeError):
    """S-7: a recorder clock offset above ten minutes voids the whole run before any scoring."""


@dataclass(frozen=True, kw_only=True)
class DepthFrame:
    """One book frame; YES asks at ``a`` cents are NO bids at ``100 - a`` cents.

    ``ts_ns`` is the frame's own timestamp (leak asserts use it, never the decision time).
    ``asks_truncated`` / ``bids_truncated``: a same-``ts_event`` ``DepthTruncation`` row says that
    side holds levels beyond the displayed ones. Only the YES-ask side matters to the guard.
    """

    rung_id: str
    ts_ns: int
    yes_bids: tuple[Level, ...]
    yes_asks: tuple[Level, ...]
    asks_truncated: bool = False
    bids_truncated: bool = False
    instance_id: str = ""


@dataclass(frozen=True)
class Print:
    rung_id: str
    yes_price_cents: int
    size: int
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "p_yes_point", MappingProxyType(dict(self.p_yes_point)))
        object.__setattr__(self, "p_yes_upper", MappingProxyType(dict(self.p_yes_upper)))


@dataclass(frozen=True)
class DecideMark:
    """Synthetic decision instant (shifted release + 1 ns) made by ``apply_clock_shift``."""


Payload = DepthFrame | Print | GapMark | Cut | ForecastVector | DecideMark


@dataclass(frozen=True, order=True)
class Event:
    """Totally ordered by ``(ts_ns, kind, seq)``; ``seq`` is the source row order."""

    ts_ns: int
    kind: Kind
    seq: int
    payload: Payload = field(compare=False)


def _check_levels(levels: tuple[Level, ...], what: str) -> None:
    for price, size in levels:
        if not _is_int(price) or not 1 <= price <= CENTS - 1:
            raise EventError(f"{what}: price {price!r} is not an integer cent in 1..99")
        if not _is_int(size) or size < 0:
            raise EventError(f"{what}: size {size!r} is not a non-negative integer contract count")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_payload(payload: Payload) -> None:
    if isinstance(payload, DepthFrame):
        _check_levels(payload.yes_bids, "yes_bids")
        _check_levels(payload.yes_asks, "yes_asks")
    elif isinstance(payload, Print):
        _check_levels(((payload.yes_price_cents, payload.size),), "print")


def validate_events(events: Sequence[Event]) -> None:
    """Strictly increasing ``(ts_ns, kind, seq)`` and sane payload domains, else ``EventError``."""
    prev: tuple[int, int, int] | None = None
    for event in events:
        key = (event.ts_ns, int(event.kind), event.seq)
        if prev is not None and key == prev:
            raise EventError(f"duplicate event key {key}")
        if prev is not None and key < prev:
            raise EventError(f"events out of order: {key} follows {prev}")
        prev = key
        _check_payload(event.payload)


def apply_clock_shift(events: Iterable[Event], delta_ns: int) -> tuple[Event, ...]:
    """Validate, then shift forecast releases +|delta| and cancels/process cuts -|delta|.

    Every shifted release also yields a ``DECIDE`` event at shifted release + 1 ns so the new vector
    is in force for a decision before any later print (plan L152). The input must already be in
    canonical order (``EventError`` otherwise); only the post-shift reordering is sorted here.
    """
    source = tuple(events)
    validate_events(source)
    d = abs(delta_ns)
    shifted: list[Event] = []
    for ev in source:
        if ev.kind is Kind.FORECAST_RELEASE:
            ev = replace(ev, ts_ns=ev.ts_ns + d)
            shifted.append(replace(ev, ts_ns=ev.ts_ns + 1, kind=Kind.DECIDE, payload=DecideMark()))
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
    """Selector output. ``desired`` is in rank order (first = the K1 rung).

    A live rung absent from ``desired`` ends with ``dropped[rung]``, else ``drop_reason``; with
    neither the simulator raises. Defaults fail closed (``forecast_valid`` False, no reason).
    """

    desired: tuple[Desired, ...] = ()
    drop_reason: str | None = None
    forecast_valid: bool = False  # drives ``forecast_valid_h``
    dropped: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reasons = [*self.dropped.values(), *([self.drop_reason] if self.drop_reason else [])]
        for reason in reasons:
            if reason not in DROP_REASONS:
                raise ValueError(f"unknown drop reason {reason!r}; expected one of DROP_REASONS")
        object.__setattr__(self, "dropped", MappingProxyType(dict(self.dropped)))

    def reason_for(self, rung_id: str) -> str:
        reason = self.dropped.get(rung_id, self.drop_reason)
        if reason is None:
            raise ValueError(f"selector dropped live rung {rung_id} without a drop reason")
        return reason


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


@dataclass(frozen=True, kw_only=True)
class Episode:
    """One (rung, t0) row. Un-suffixed end/vector fields are the base pass's (the stress pass's
    for a stress-only row); the ``*_stress`` fields are the stress pass's own end and vector."""

    station: str
    climate_day: str
    rung_id: str
    t0_ns: int
    end_ns: int
    end_reason: str
    bid_cents: int
    a_gt: int
    a_eq: int
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
    end_ns_stress: int | None
    end_reason_stress: str | None
    p_yes_point_live_stress: float | None
    p_yes_upper_live_stress: float | None
    cycle_runtime_ns_stress: int | None
    raw_sha256_stress: str | None
    nbm_era_stress: str | None
    available_at_ns_stress: int | None

    def to_dict(self) -> dict[str, Any]:
        out = _flat_fields(self)
        out["bid"] = self.bid_cents / CENTS
        return out


@dataclass(frozen=True, kw_only=True)
class StationDaySummary:
    """``n_attempts``/``n_episodes``/``n_refused`` count the BASE pass; ``episodes`` also holds
    stress-only rows. ``rung_trials_attempted`` (refused or placed) is the position-unit
    denominator; ``rung_trials_posted`` counts placed rungs only."""

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
    rung_trials_attempted: int
    rung_trials_posted: int
    rung_trials_filled_base: int
    rung_trials_filled_stress: int
    rungs_ever_posted: int
    filled_pairs_base: int
    filled_pairs_stress: int
    k1_rung_id: str | None
    k1_filled_base: int
    k1_filled_stress: int
    bid_median_fills_stress: float | None
    delta_ns: int
    truncation_refused_share: float | None
    first_refusal_to_first_placement_s: float | None
    process_live_h: float
    forecast_valid_h: float
    gap_h: float
    covered_live_h: float
    gap_share: float | None

    def to_dict(self) -> dict[str, Any]:
        return _flat_fields(self)


@dataclass(frozen=True)
class StationDayResult:
    episodes: tuple[Episode, ...]
    summary: StationDaySummary
