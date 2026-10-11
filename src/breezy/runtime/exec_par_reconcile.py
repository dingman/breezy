"""EXEC-PAR BG-1d: counter reconciliation and gappy-day marks (inert; unwired).

Spec D-PREREG 10a ("Gappy days", "Reconciliation", "Excluded days"), r4.1 K9
and r4.4 N3. Pure decision logic with every store read injected, so nothing
here touches Nautilus, the latch or the exec client.

* :func:`compute_gap_spans` / :func:`gappy_days` turn epoch rows and watcher
  heartbeats into gappy climate days. A recorded outage (``stop_ts`` to the
  next ``boot_ts``) is never a gap; a heartbeat lapse of more than 60 s while
  an epoch is open, and an unclean shutdown (no ``stop_ts``: last heartbeat to
  the next boot), are.
* :func:`reconcile_day` compares one day's BG-1b counters with the durable
  sources (fill index, slot table, ``DailySpendLedger`` registry) and decides
  UNCHANGED, REBUILT or DAY_EXCLUDED.
* :func:`run_reconcile_pass` is the effectful driver: ordering guard (mass
  status ingest must already have run), phase timestamps, the 300 s bound
  (returned as ``reconcile_stuck``; the halt wiring is BG-6), rebuild and
  exclusion writes.

The counter interface BG-1b must satisfy is :class:`CounterStorePort`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from itertools import pairwise
from typing import Final, Protocol

from breezy.runtime.exec_par_records import EpochRow, ExcludedDay

__all__ = [
    "HEARTBEAT_LAPSE_NS",
    "RECONCILE_BOUND_NS",
    "CounterStorePort",
    "DayCounts",
    "DayOutcome",
    "DayOutcomeKind",
    "DayVerdict",
    "DurableDaySources",
    "ExcludedDayWriter",
    "ExcludedEvent",
    "GapKind",
    "GapSpan",
    "PassResult",
    "PassStatus",
    "RebuildEvent",
    "RebuildRecord",
    "ReconcileOrderingError",
    "SlotDayCounts",
    "compute_gap_spans",
    "gappy_days",
    "reconcile_day",
    "run_reconcile_pass",
]

_NS: Final[int] = 1_000_000_000
#: Spec 10a (a): a watcher heartbeat gap strictly longer than this is a gap.
HEARTBEAT_LAPSE_NS: Final[int] = 60 * _NS
#: r4.3 / r4.4 N3: the reconcile phase bound; exceeding it is ``reconcile_stuck``.
RECONCILE_BOUND_NS: Final[int] = 300 * _NS
_HOUR_NS: Final[int] = 3_600 * _NS


# -- gappy marks -------------------------------------------------------------


class GapKind(Enum):
    HEARTBEAT_LAPSE = "heartbeat_lapse"
    UNCLEAN_SHUTDOWN = "unclean_shutdown"


@dataclass(frozen=True, slots=True)
class GapSpan:
    kind: GapKind
    start_ns: int
    end_ns: int


def _lapses(points: Sequence[int]) -> list[GapSpan]:
    return [
        GapSpan(GapKind.HEARTBEAT_LAPSE, a, b)
        for a, b in pairwise(points)
        if b - a > HEARTBEAT_LAPSE_NS
    ]


def compute_gap_spans(
    epochs: Iterable[EpochRow], heartbeats: Iterable[int], *, now_ns: int
) -> tuple[GapSpan, ...]:
    """Gap spans from epoch rows and heartbeat times (inputs are not mutated).

    Inside an epoch's up-window (``boot_ts`` to ``stop_ts``, or to ``now_ns``
    for the open epoch) any heartbeat spacing above 60 s is a lapse. An epoch
    with no ``stop_ts`` that is followed by a later boot was shut down
    uncleanly: its last heartbeat to that boot is a gap. The span from a
    ``stop_ts`` to the next ``boot_ts`` is a recorded outage and never a gap.
    """
    ordered = sorted(epochs, key=lambda e: e.boot_ts)
    beats = sorted(heartbeats)
    spans: list[GapSpan] = []
    for index, epoch in enumerate(ordered):
        next_boot = ordered[index + 1].boot_ts if index + 1 < len(ordered) else None
        unclean = epoch.stop_ts is None and next_boot is not None
        if epoch.stop_ts is not None:
            window_end = epoch.stop_ts
        else:
            window_end = next_boot if next_boot is not None else now_ns
        inside = [
            b
            for b in beats
            if epoch.boot_ts <= b and (b < window_end if unclean else b <= window_end)
        ]
        points = [epoch.boot_ts, *inside]
        if unclean and next_boot is not None:
            spans.extend(_lapses(points))
            spans.append(GapSpan(GapKind.UNCLEAN_SHUTDOWN, points[-1], next_boot))
        else:
            spans.extend(_lapses([*points, window_end]))
    return tuple(sorted(spans, key=lambda s: (s.start_ns, s.end_ns, s.kind.value)))


def _utc_day(ns: int) -> str:
    return datetime.fromtimestamp(ns // _NS, UTC).date().isoformat()


def gappy_days(
    spans: Iterable[GapSpan], *, day_of: Callable[[int], str] = _utc_day
) -> frozenset[str]:
    """Every climate day a gap span touches (``day_of`` maps ns to a day key)."""
    days: set[str] = set()
    for span in spans:
        cursor = span.start_ns
        while cursor < span.end_ns:
            days.add(day_of(cursor))
            cursor += _HOUR_NS
        days.add(day_of(span.end_ns))
        days.add(day_of(span.start_ns))
    return frozenset(days)


# -- the counter interface (BG-1b side) and the durable sources ---------------


@dataclass(frozen=True, slots=True)
class DayCounts:
    """The reconcilable subset of one climate day's counters."""

    posted_entries: int
    ambiguous: int
    fills: int
    spend_usd: Decimal


@dataclass(frozen=True, slots=True)
class SlotDayCounts:
    """What the slot table holds for a day."""

    posted_entries: int
    ambiguous: int


class CounterStorePort(Protocol):
    """What reconcile needs from BG-1b's counter store (single-writer side)."""

    def read_day_counts(self, day: str) -> DayCounts | None: ...
    def replace_day_counts(self, day: str, counts: DayCounts) -> None: ...
    def read_gappy_days(self) -> frozenset[str]: ...
    def clear_gappy_mark(self, day: str) -> None: ...
    def write_rebuild_record(self, record: RebuildRecord) -> None: ...
    def write_reconcile_phase(self, *, start_ns: int, ok_ns: int | None) -> None: ...


class DurableDaySources(Protocol):
    """Durable reads for a day; ``None`` means unreadable (never zero)."""

    def fill_count(self, day: str) -> int | None: ...
    def slot_counts(self, day: str) -> SlotDayCounts | None: ...
    def ledger_spend(self, day: str) -> Decimal | None: ...


class ExcludedDayWriter(Protocol):
    """The BG-1a ``add_excluded_day`` writer; ``False`` if already excluded."""

    def add_excluded_day(self, record: ExcludedDay) -> bool: ...


# -- per-day decision (pure) --------------------------------------------------


class DayOutcomeKind(Enum):
    UNCHANGED = "unchanged"
    REBUILT = "rebuilt"
    DAY_EXCLUDED = "day_excluded"


@dataclass(frozen=True, slots=True)
class DayVerdict:
    day: str
    kind: DayOutcomeKind
    mismatch_kinds: tuple[str, ...] = ()
    rebuilt: DayCounts | None = None
    reason: str | None = None


def _inconsistency(
    fills: int | None, slots: SlotDayCounts | None, spend: Decimal | None
) -> str | None:
    if fills is None:
        return "fills_unreadable"
    if slots is None:
        return "slots_unreadable"
    if spend is None:
        return "ledger_unreadable"
    if fills < 0 or slots.posted_entries < 0 or slots.ambiguous < 0:
        return "negative_count"
    if spend < 0:
        return "negative_spend"
    if slots.ambiguous > slots.posted_entries:
        return "ambiguous_exceeds_posted"
    if fills > slots.posted_entries:
        return "fills_exceed_posted"
    if spend > 0 and slots.posted_entries == 0:
        return "spend_without_entries"
    if fills > 0 and spend == 0:
        return "fills_without_spend"
    return None


def _mismatch_kinds(stored: DayCounts | None, durable: DayCounts) -> tuple[str, ...]:
    if stored is None:
        return ("missing",)
    pairs = (
        ("ambiguous", stored.ambiguous, durable.ambiguous),
        ("fills", stored.fills, durable.fills),
        ("posted_entries", stored.posted_entries, durable.posted_entries),
        ("spend", stored.spend_usd, durable.spend_usd),
    )
    return tuple(name for name, have, want in pairs if have != want)


def reconcile_day(
    day: str,
    *,
    stored: DayCounts | None,
    fills: int | None,
    slots: SlotDayCounts | None,
    spend: Decimal | None,
    gappy: bool,
) -> DayVerdict:
    """Decide one day. Unreadable or self-contradictory sources exclude it."""
    reason = _inconsistency(fills, slots, spend)
    if reason is not None:
        return DayVerdict(day, DayOutcomeKind.DAY_EXCLUDED, reason=reason)
    if fills is None or slots is None or spend is None:  # unreachable; narrows types
        return DayVerdict(day, DayOutcomeKind.DAY_EXCLUDED, reason="sources_unreadable")
    durable = DayCounts(slots.posted_entries, slots.ambiguous, fills, spend)
    kinds = _mismatch_kinds(stored, durable)
    if not kinds and not gappy:
        return DayVerdict(day, DayOutcomeKind.UNCHANGED)
    return DayVerdict(day, DayOutcomeKind.REBUILT, mismatch_kinds=kinds, rebuilt=durable)


# -- the pass -----------------------------------------------------------------


class ReconcileOrderingError(RuntimeError):
    """Reconcile was asked to run before the Nautilus mass-status ingest."""


class PassStatus(Enum):
    OK = "ok"
    RECONCILE_STUCK = "reconcile_stuck"


@dataclass(frozen=True, slots=True)
class RebuildRecord:
    """Durable note that a day's counters were rebuilt from the sources."""

    day: str
    ts_ns: int
    mismatch_kinds: tuple[str, ...]
    counts: DayCounts


@dataclass(frozen=True, slots=True)
class RebuildEvent:
    """Payload of the ``EXEC_PAR_COUNTER_REBUILT {day, mismatch_kinds}`` alert."""

    day: str
    mismatch_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExcludedEvent:
    """Payload of the ``day_excluded`` integrity outcome / ``EXEC_PAR_DAY_EXCLUDED``."""

    day: str
    cause: str


@dataclass(frozen=True, slots=True)
class DayOutcome:
    day: str
    kind: DayOutcomeKind
    mismatch_kinds: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PassResult:
    status: PassStatus
    outcomes: tuple[DayOutcome, ...]
    rebuild_events: tuple[RebuildEvent, ...]
    excluded_events: tuple[ExcludedEvent, ...]
    unprocessed_days: tuple[str, ...]
    reconcile_start_ns: int
    reconcile_ok_ns: int | None


def _require_ingested(probe: Callable[[], bool]) -> None:
    try:
        ready = probe()
    except Exception:  # noqa: BLE001 - any probe failure means not provably ingested
        raise ReconcileOrderingError("mass-status ingest probe failed") from None
    if ready is not True:
        raise ReconcileOrderingError("reconcile must run after the mass-status ingest")


def run_reconcile_pass(
    days: Iterable[str],
    *,
    mass_status_ingested: Callable[[], bool],
    counters: CounterStorePort,
    sources: DurableDaySources,
    excluded: ExcludedDayWriter,
    clock_ns: Callable[[], int],
) -> PassResult:
    """Reconcile ``days`` (deduplicated, ascending) once.

    Raises :class:`ReconcileOrderingError`, before any read or write, unless
    ``mass_status_ingested()`` is exactly ``True``. Past 300 s the pass stops
    and returns ``reconcile_stuck``; it never halts (BG-6 wires that).
    """
    _require_ingested(mass_status_ingested)
    ordered = tuple(sorted(set(days)))
    gappy = counters.read_gappy_days()
    start = clock_ns()
    counters.write_reconcile_phase(start_ns=start, ok_ns=None)

    outcomes: list[DayOutcome] = []
    rebuilds: list[RebuildEvent] = []
    exclusions: list[ExcludedEvent] = []
    for index, day in enumerate(ordered):
        now = clock_ns()
        if now - start > RECONCILE_BOUND_NS:
            return _result(
                PassStatus.RECONCILE_STUCK, outcomes, rebuilds, exclusions, ordered[index:], start
            )
        verdict = reconcile_day(
            day,
            stored=counters.read_day_counts(day),
            fills=sources.fill_count(day),
            slots=sources.slot_counts(day),
            spend=sources.ledger_spend(day),
            gappy=day in gappy,
        )
        outcomes.append(DayOutcome(day, verdict.kind, verdict.mismatch_kinds, verdict.reason))
        if verdict.kind is DayOutcomeKind.REBUILT and verdict.rebuilt is not None:
            record = RebuildRecord(day, now, verdict.mismatch_kinds, verdict.rebuilt)
            counters.replace_day_counts(day, verdict.rebuilt)
            counters.write_rebuild_record(record)
            counters.clear_gappy_mark(day)  # last: a crash before this re-reconciles
            rebuilds.append(RebuildEvent(day, verdict.mismatch_kinds))
        elif verdict.kind is DayOutcomeKind.DAY_EXCLUDED:
            cause = f"unreconcilable:{verdict.reason}"
            if excluded.add_excluded_day(ExcludedDay(day=day, cause=cause, ts=now)):
                exclusions.append(ExcludedEvent(day, cause))

    ok = clock_ns()
    if ok - start > RECONCILE_BOUND_NS:
        return _result(PassStatus.RECONCILE_STUCK, outcomes, rebuilds, exclusions, (), start)
    counters.write_reconcile_phase(start_ns=start, ok_ns=ok)
    return _result(PassStatus.OK, outcomes, rebuilds, exclusions, (), start, ok)


def _result(
    status: PassStatus,
    outcomes: list[DayOutcome],
    rebuilds: list[RebuildEvent],
    exclusions: list[ExcludedEvent],
    unprocessed: tuple[str, ...],
    start: int,
    ok: int | None = None,
) -> PassResult:
    return PassResult(
        status=status,
        outcomes=tuple(outcomes),
        rebuild_events=tuple(rebuilds),
        excluded_events=tuple(exclusions),
        unprocessed_days=unprocessed,
        reconcile_start_ns=start,
        reconcile_ok_ns=ok,
    )
