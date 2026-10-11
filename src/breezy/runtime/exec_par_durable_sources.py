"""EXEC-PAR BG-5c WP-B: the durable day sources of the K>1 stage evaluator (inert; unwired).

Supplies the BG-1d ``DurableDaySources`` port (:class:`DurableSources`), the spend audit against
the Nautilus cache (:class:`SpendAuditor`) and ``counters_expected`` from the BG-2 epochs. Every
store, slot, cache and clock dependency is INJECTED, so this module imports no network or
Nautilus code and opens nothing itself; WP-E supplies the real ports at configured K>1 only.

**Entry fills (R1, item 1).** Each non-exit slot (open or retired) joins to its fill by the exact
SP-3r key the client wrote, ``fill_by_fingerprint/<UTC day of created_ns>:<fingerprint>`` ->
venue order id -> ``fill/<id>`` (read-only ``get``; ``exec/client.py`` is never imported). The
slot's own ``is_exit`` flag, never a ``wire*`` field, tells entry from exit; the entry's day is
``entry_day(station_of(slug), created_ns)``. A fill that cannot be placed (no station) is
unattributable and FAILS the days it could belong to; it is never dropped.

**Two spend metrics (R3 as amended).** ``ledger_spend`` (the BG-1d reconcile check) is Σ armed
notional over the day's durable entry anchors, the same definition as the counter store's
``spend_usd``, so a partially filled day reconciles clean. ``filled_spend`` is Σ over entry orders
of the ``cumulative_cost`` of the order's TERMINAL record (max ``cumulative_qty``; the client
rewrites one cumulative record per venue order, so partial fills are never summed); only it is
audited against the Nautilus cache.

**AMBIGUOUS (R2).** Counted only from the BG-1b ever-ambiguous mark rows, attributed by each
mark's stored ``arm_ns`` and station.

**Failure contract.** Every ``*_reading`` returns a :class:`SourceReading`: an empty result is
``ok=True`` with a real zero; a raise becomes a typed :class:`SourceFailure`; a failure is never a
zero. The ``DurableDaySources`` methods map a failure to ``None`` (BG-1d excludes the day) except
``entry_fill_count``, which re-raises ``UnattributableFill`` as that port requires. Failures are
also kept on :attr:`DurableSources.failures` (reasons only, never amounts).

**Audit (A2).** The cache audit is FULL only when
``day_start >= boot_ts - reconciliation_lookback``. Otherwise, or when the cache is
unavailable, the day is ``UNAUDITED``: that DEFERS the look (it is
not a failed look and never counts toward demotion), and past ``SETTLEMENT_DEADLINE_DAYS`` it
excludes the day. A full-coverage mismatch of filled spend is ``spend_audit_mismatch``: it also
DEFERS the look and raises an alert (``SpendAudit.alerts``), and never excludes the day; exclusion
stays the BG-1d path for counter-vs-durable mismatches only.

Use a FRESH :class:`DurableSources` per reconcile pass: the slot/fill join is read once and cached.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Final, Protocol

from breezy.domain.exec_intent import (
    FILL_BY_DAY_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    FILL_KEY_PREFIX,
    utc_day_for_ns,
)
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_reconcile import (
    FillRecord,
    SlotDayCounts,
    UnattributableFill,
    entry_fills_by_day,
)
from breezy.runtime.exec_par_records import AmbiguousRow, EpochRow, OrderAnchor
from breezy.runtime.exec_par_settled_pnl import (
    CENT,
    SETTLEMENT_DEADLINE_DAYS,
    EntryInput,
    FillLike,
)

__all__ = [
    "HISTORY_KEY_PREFIX",
    "UNATTRIBUTED",
    "AmbiguousRowsPort",
    "AnchorRowsPort",
    "AuditStatus",
    "CacheFill",
    "CacheFillPort",
    "DurableSources",
    "FillStoreReader",
    "IntentSource",
    "OffsetDayConvention",
    "SlotView",
    "SourceFailure",
    "SourceReadError",
    "SourceReading",
    "SpendAudit",
    "SpendAuditMonitor",
    "SpendAuditor",
    "StoreIntentSource",
    "counters_expected_from",
    "day_bounds_from_offsets",
    "earliest_day_start_ns",
    "entry_inputs_from",
    "terminal_fill",
]

#: Restated (a test pins it equal to ``submit_intent.history_key("")``): retired-slot rows.
HISTORY_KEY_PREFIX: Final[str] = "exec/polymarket_us/intent/history/"
#: Restated from ``exec_par_counter_ingest.UNATTRIBUTED`` (a test pins equality) so this module
#: never loads the ingest layer's Nautilus imports.
UNATTRIBUTED: Final[str] = "unattributed"
_LOG = logging.getLogger(__name__)
_ENTRY_SIDE: Final[str] = "BUY"
_HOUR_NS: Final[int] = 3_600 * 1_000_000_000
_DAY_NS: Final[int] = 24 * _HOUR_NS
_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

REASON_READ_ERROR: Final[str] = "read_error"
REASON_CORRUPT: Final[str] = "corrupt"
REASON_UNATTRIBUTABLE: Final[str] = "unattributable"
REASON_AUDIT_MISMATCH: Final[str] = "spend_audit_mismatch"


# -- ports ---------------------------------------------------------------------------


class SlotView(Protocol):
    """The read-only slot fields the join uses (``SubmitIntent`` satisfies this)."""

    @property
    def intent_id(self) -> str: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def created_ns(self) -> int: ...
    @property
    def slug(self) -> str | None: ...
    @property
    def is_exit(self) -> bool: ...


class IntentSource(Protocol):
    """Every slot, open or retired. May raise (a read failure) or return duplicates."""

    def all_intents(self) -> Iterable[SlotView]: ...


class FillStoreReader(Protocol):
    """Read-only ``get`` over the exec store (never ``set``)."""

    def get(self, key: str) -> bytes | None: ...


class FillRecordLike(FillLike, Protocol):
    @property
    def venue_order_id(self) -> str: ...
    @property
    def client_order_id(self) -> str: ...
    @property
    def order_side(self) -> str: ...
    @property
    def cumulative_qty(self) -> Decimal: ...
    @property
    def cumulative_cost(self) -> Decimal: ...


class AmbiguousRowsPort(Protocol):
    """The latch's day-scoped ever-ambiguous mark rows (BG-1b ``read_ambiguous``)."""

    def read_ambiguous(self, day: str) -> tuple[AmbiguousRow, ...]: ...


class AnchorRowsPort(Protocol):
    """The latch's day-scoped posted-entry anchors (BG-1b ``read_order_anchors``)."""

    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]: ...


@dataclass(frozen=True, slots=True)
class CacheFill:
    """One entry/exit order's cost as the Nautilus cache's own fill events say (WP-E adapts it)."""

    client_order_id: str
    slug: str
    arm_ns: int
    order_side: str
    cost: Decimal = field(repr=False)


class CacheFillPort(Protocol):
    """Independent source: ``None`` or a raise means the cache cannot be read right now."""

    def order_fills(self) -> Iterable[CacheFill] | None: ...


# -- typed readings ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceFailure:
    """Why a source could not answer (no amounts, no messages)."""

    source: str
    reason: str
    exc_type: str | None = None


class SourceReadError(Exception):
    """A durable read failed twice within the pass (``name`` says which source).

    Not an exclusion: the runner maps it to FAIL ``stage_eval_fail:source_read:<name>`` (an
    integrity halt, retried on the next pass). ``None`` / ``day_excluded`` stays reserved for a
    genuine counter-vs-durable mismatch. The message carries the name only, never a value.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"durable source read failed: {name}")
        self.name = name


@dataclass(frozen=True, slots=True)
class SourceReading[T]:
    """An answer or a failure; ``ok`` with an empty/zero value is a REAL empty result."""

    ok: bool
    value: T | None
    failure: SourceFailure | None

    @classmethod
    def success(cls, value: T) -> SourceReading[T]:
        return cls(True, value, None)

    @classmethod
    def failed(cls, source: str, reason: str) -> SourceReading[T]:
        return cls(False, None, SourceFailure(source, reason))


class _Corrupt(Exception):
    """A durable row is missing where an index promised it, or is malformed."""


# -- the terminal fill -----------------------------------------------------------------


def terminal_fill[R: FillRecordLike](records: Sequence[R]) -> R:
    """The record with the max ``cumulative_qty`` (cumulative totals: never summed).

    Two records at the same max quantity must agree on cost, else the terminal one is ambiguous
    and ``ValueError`` is raised. An empty sequence raises.
    """
    if not records:
        raise ValueError("no fill record")
    best = max(records, key=lambda r: r.cumulative_qty)
    if any(
        r.cumulative_qty == best.cumulative_qty and r.cumulative_cost != best.cumulative_cost
        for r in records
    ):
        raise ValueError("ambiguous terminal fill")
    return best


# -- the slot/fill join (read once) ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Entry:
    intent_id: str
    arm_ns: int
    station: str | None
    day: str | None
    fill: FillRecordLike | None


@dataclass(slots=True)
class _Joined:
    entries: list[_Entry] = field(default_factory=list)
    reachable: set[str] = field(default_factory=set)
    posted: dict[str, int] = field(default_factory=dict)
    fills: dict[str, int] = field(default_factory=dict)
    spend: dict[str, Decimal] = field(default_factory=dict)
    posted_poison: set[str] = field(default_factory=set)
    fill_poison: set[str] = field(default_factory=set)
    all_posted_poisoned: bool = False
    all_fills_poisoned: bool = False


class _Join:
    def __init__(
        self,
        intents: IntentSource,
        store: FillStoreReader,
        decode_fill: Callable[[bytes], FillRecordLike],
        governed: DayConvention,
        station_of: Callable[[str], str | None],
    ) -> None:
        self._intents = intents
        self._store = store
        self._decode = decode_fill
        self._governed = governed
        self._station_of = station_of

    def build(self) -> _Joined:
        joined = _Joined()
        records: list[FillRecord] = []
        seen: set[str] = set()
        for intent in self._intents.all_intents():
            if intent.intent_id in seen:
                continue
            seen.add(intent.intent_id)
            vid = self._vid_of(intent)
            if vid is not None:
                joined.reachable.add(vid)
            if intent.is_exit:
                continue
            fill = None if vid is None else self._record_of(vid)
            if fill is not None:
                _check_amounts(fill)
            filled = fill is not None and fill.cumulative_qty > 0
            station = self._station(intent.slug)
            day = self._day(station, intent.created_ns)
            joined.entries.append(_Entry(intent.intent_id, intent.created_ns, station, day, fill))
            if station is None or day is None:
                self._poison(joined, intent.created_ns, filled)
                continue
            joined.posted[day] = joined.posted.get(day, 0) + 1
            if fill is None or not filled:
                continue
            if fill.order_side != _ENTRY_SIDE:
                joined.all_fills_poisoned = True
                continue
            records.append(
                FillRecord(fill.venue_order_id, fill.order_side, intent.created_ns, station, False)
            )
            joined.spend[day] = joined.spend.get(day, Decimal(0)) + fill.cumulative_cost
        if not joined.all_fills_poisoned:
            joined.fills = entry_fills_by_day(records, entry_day=self._governed.entry_day)
        return joined

    def _station(self, slug: str | None) -> str | None:
        if not slug:
            return None
        try:
            return self._station_of(slug)
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return None

    def _day(self, station: str | None, created_ns: int) -> str | None:
        if station is None:
            return None
        try:
            return self._governed.entry_day(station, created_ns)
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return None

    def _poison(self, joined: _Joined, created_ns: int, filled: bool) -> None:
        try:
            days = set(self._governed.open_days_at(created_ns))
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            joined.all_posted_poisoned = True
            joined.all_fills_poisoned = joined.all_fills_poisoned or filled
            return
        joined.posted_poison |= days
        if filled:
            joined.fill_poison |= days

    def _vid_of(self, intent: SlotView) -> str | None:
        try:
            day = utc_day_for_ns(intent.created_ns).isoformat()
        except ValueError:
            raise _Corrupt from None
        raw_id = self._store.get(f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{intent.fingerprint}")
        return None if raw_id is None else raw_id.decode("utf-8", "replace")

    def _record_of(self, vid: str) -> FillRecordLike:
        raw = self._store.get(f"{FILL_KEY_PREFIX}{vid}")
        if raw is None:
            raise _Corrupt
        try:
            return terminal_fill([self._decode(raw)])
        except Exception as exc:
            raise _Corrupt from exc

    def orphan_check(self, day: str, reachable: set[str]) -> None:
        """Raise :class:`_Corrupt` for an entry-side fill row no slot fingerprint reaches.

        Looks at the ``fill_by_day`` UTC indexes the day can touch (its label +-1 day). An
        unreachable SELL (an operator exit with no slot) is not an entry and is ignored.
        """
        centre = dt.date.fromisoformat(day)
        for offset in (-1, 0, 1):
            utc_day = (centre + dt.timedelta(days=offset)).isoformat()
            raw_index = self._store.get(f"{FILL_BY_DAY_KEY_PREFIX}{utc_day}")
            if raw_index is None:
                continue
            try:
                listed = json.loads(raw_index.decode("utf-8"))
            except ValueError:
                raise _Corrupt from None
            if not isinstance(listed, list):
                raise _Corrupt
            for vid in listed:
                if not isinstance(vid, str):
                    raise _Corrupt
                if vid in reachable:
                    continue
                fill = self._record_of(vid)
                if fill.order_side == _ENTRY_SIDE and fill.cumulative_qty > 0:
                    raise _Corrupt


def _check_amounts(fill: FillRecordLike) -> None:
    for value in (fill.cumulative_qty, fill.cumulative_cost):
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise _Corrupt


# -- the spend audit --------------------------------------------------------------------


class AuditStatus(Enum):
    FULL_MATCH = "full_match"
    MISMATCH = "mismatch"
    UNAUDITED = "unaudited"
    DURABLE_UNREADABLE = "durable_unreadable"


@dataclass(frozen=True, slots=True)
class SpendAudit:
    """One day's audit. ``reason`` is a label only; the amounts are kept out of ``repr``."""

    day: str
    status: AuditStatus
    reason: str | None = None
    durable: Decimal | None = field(default=None, repr=False)
    cache: Decimal | None = field(default=None, repr=False)

    @property
    def defers_look(self) -> bool:
        """``spend_unaudited`` or ``spend_audit_mismatch``: no look is taken; NOT a failed look."""
        return self.status in (AuditStatus.UNAUDITED, AuditStatus.MISMATCH)

    @property
    def blocks_pass(self) -> bool:
        """Only a full-coverage match lets the day pass; every other status blocks it."""
        return self.status is not AuditStatus.FULL_MATCH

    @property
    def alerts(self) -> bool:
        """A full-coverage mismatch raises an alert; it never excludes the day."""
        return self.status is AuditStatus.MISMATCH

    def excludes_day(self, today: str) -> bool:
        """An unaudited OR mismatched day at least ``SETTLEMENT_DEADLINE_DAYS`` old becomes
        ``day_excluded`` (§10a); before that it defers (a mismatch with an alert)."""
        if self.status not in (AuditStatus.UNAUDITED, AuditStatus.MISMATCH):
            return False
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(self.day)).days
        return age >= SETTLEMENT_DEADLINE_DAYS


class OffsetDayConvention(DayConvention, Protocol):
    """A day convention that also exposes each governed station's standard UTC offset (hours)."""

    @property
    def std_offsets(self) -> Mapping[str, float]: ...


def earliest_day_start_ns(day: str, governed: OffsetDayConvention) -> int:
    """The earliest instant any governed station's ``day`` can start (min over stations).

    The A2 coverage rule needs the earliest start: the day is only fully audited if the cache
    reaches back to the first station that rolled onto it.
    """
    return day_bounds_from_offsets(governed.std_offsets)(day)[0]


class SpendAuditMonitor:
    """Alerts once per (day, status) transition into a MISMATCH, never on every pass.

    Long-lived (one per node, shared by the per-pass :class:`DurableSources`). ``alert_sink`` is
    REQUIRED, so an audit consumer cannot be built unwired. A sink that returns ``False`` or raises
    leaves the transition undelivered, so the next observation retries it.
    """

    def __init__(self, *, alert_sink: Callable[[SpendAudit], bool]) -> None:
        self._sink = alert_sink
        self._seen: dict[str, AuditStatus] = {}

    def observe(self, audit: SpendAudit) -> None:
        previous = self._seen.get(audit.day)
        if audit.status is previous:
            return
        if audit.alerts:
            try:
                delivered = self._sink(audit)
            except Exception as exc:  # noqa: BLE001 - an alert failure must not break the pass
                _LOG.error("spend audit alert not delivered: %s", type(exc).__name__)
                return
            if not delivered:
                return
        self._seen[audit.day] = audit.status


class SpendAuditor:
    """Compares durable spend with the cache's entry-fill costs under the A2 coverage rule."""

    def __init__(
        self,
        *,
        cache: CacheFillPort | None,
        governed: OffsetDayConvention,
        station_of: Callable[[str], str | None],
        boot_ts_ns: int,
        lookback_ns: int,
    ) -> None:
        self._cache = cache
        self._governed = governed
        self._station_of = station_of
        self._boot = boot_ts_ns
        self._lookback = lookback_ns

    def audit(self, day: str, durable: Decimal) -> SpendAudit:
        if earliest_day_start_ns(day, self._governed) < self._boot - self._lookback:
            return SpendAudit(day, AuditStatus.UNAUDITED, "partial_coverage")
        if self._cache is None:
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_unavailable")
        try:
            fills = self._cache.order_fills()
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_error")
        if fills is None:
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_unavailable")
        try:
            cache_total, unattributable = self._cache_total(day, fills)
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_error")
        if unattributable:
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_unattributable")
        if cache_total.quantize(CENT, ROUND_HALF_EVEN) == durable.quantize(CENT, ROUND_HALF_EVEN):
            return SpendAudit(day, AuditStatus.FULL_MATCH, None, durable, cache_total)
        return SpendAudit(day, AuditStatus.MISMATCH, REASON_AUDIT_MISMATCH, durable, cache_total)

    def _cache_total(self, day: str, fills: Iterable[CacheFill]) -> tuple[Decimal, bool]:
        total = Decimal(0)
        for fill in fills:
            if fill.order_side != _ENTRY_SIDE:
                continue
            station = self._station_of(fill.slug)
            if station is None:
                if day in self._governed.open_days_at(fill.arm_ns):
                    return total, True
                continue
            if self._governed.entry_day(station, fill.arm_ns) != day:
                continue
            if not fill.cost.is_finite() or fill.cost < 0:
                return total, True
            total += fill.cost
        return total, False


# -- DurableDaySources ---------------------------------------------------------------------


class DurableSources:
    """The BG-1d ``DurableDaySources`` over the slot table, durable fills and mark rows.

    A read failure is retried ONCE within the pass; a second failure raises
    :class:`SourceReadError` (a FAIL, never an exclusion). ``None`` / ``UnattributableFill`` are
    reserved for data that is genuinely unplaceable.
    """

    def __init__(
        self,
        *,
        intents: IntentSource,
        store: FillStoreReader,
        decode_fill: Callable[[bytes], FillRecordLike],
        governed: DayConvention,
        station_of: Callable[[str], str | None],
        ambiguous: AmbiguousRowsPort,
        anchors: AnchorRowsPort,
        monitor: SpendAuditMonitor,
        auditor: SpendAuditor | None = None,
    ) -> None:
        self._join = _Join(intents, store, decode_fill, governed, station_of)
        self._governed = governed
        self._ambiguous = ambiguous
        self._anchors = anchors
        self._monitor = monitor
        self._auditor = auditor
        self._built: _Joined | None = None
        self._build_failure: tuple[str, str | None] | None = None
        self._orphan_ok: set[str] = set()
        self._failures: list[SourceFailure] = []

    @property
    def failures(self) -> tuple[SourceFailure, ...]:
        return tuple(self._failures)

    # typed readings -----------------------------------------------------------------------

    def fills_reading(self, day: str) -> SourceReading[int]:
        joined = self._joined()
        if isinstance(joined, SourceFailure):
            return self._fail("fills", joined.reason, joined.exc_type)
        if joined.all_fills_poisoned or day in joined.fill_poison:
            return self._fail("fills", REASON_UNATTRIBUTABLE)
        orphan = self._orphan_failure(day, joined)
        if orphan is not None:
            return self._fail("fills", orphan.reason, orphan.exc_type)
        return SourceReading.success(joined.fills.get(day, 0))

    def filled_spend_reading(self, day: str) -> SourceReading[Decimal]:
        joined = self._joined()
        if isinstance(joined, SourceFailure):
            return self._fail("spend", joined.reason, joined.exc_type)
        if joined.all_fills_poisoned or day in joined.fill_poison:
            return self._fail("spend", REASON_UNATTRIBUTABLE)
        orphan = self._orphan_failure(day, joined)
        if orphan is not None:
            return self._fail("spend", orphan.reason, orphan.exc_type)
        return SourceReading.success(joined.spend.get(day, Decimal(0)))

    def slots_reading(self, day: str) -> SourceReading[SlotDayCounts]:
        joined = self._joined()
        if isinstance(joined, SourceFailure):
            return self._fail("slots", joined.reason, joined.exc_type)
        if joined.all_posted_poisoned or day in joined.posted_poison:
            return self._fail("slots", REASON_UNATTRIBUTABLE)
        try:
            marks = self._retry_once(lambda: self._marks(day))
        except _Unattributable:
            return self._fail("slots", REASON_UNATTRIBUTABLE)
        except Exception as exc:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return self._fail("slots", REASON_READ_ERROR, type(exc).__name__)
        return SourceReading.success(SlotDayCounts(joined.posted.get(day, 0), marks))

    def unattributed_ambiguous_reading(self) -> SourceReading[int]:
        """Marks BG-1b could not place on a day (kept apart; never folded into a day)."""
        try:
            rows = self._retry_once(lambda: self._ambiguous.read_ambiguous(UNATTRIBUTED))
        except Exception as exc:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return self._fail("unattributed_ambiguous", REASON_READ_ERROR, type(exc).__name__)
        return SourceReading.success(len(rows))

    def marked_intent_ids(self, days: Iterable[str]) -> frozenset[str]:
        """Intent ids with an ever-ambiguous mark on ``days`` (and the unattributed bucket)."""
        ids: set[str] = set()
        try:
            for day in (*sorted(set(days)), UNATTRIBUTED):
                ids |= self._mark_ids(day)
        except Exception as exc:
            self._fail("marks", REASON_READ_ERROR, type(exc).__name__)
            raise SourceReadError("marks") from exc
        return frozenset(ids)

    def _mark_ids(self, day: str) -> set[str]:
        def read() -> set[str]:
            return {row.intent_id for row in self._ambiguous.read_ambiguous(day)}

        return self._retry_once(read)

    def audit_spend(self, day: str) -> SpendAudit:
        reading = self.filled_spend_reading(day)
        if not reading.ok or reading.value is None:
            audit = SpendAudit(day, AuditStatus.DURABLE_UNREADABLE)
        elif self._auditor is None:
            audit = SpendAudit(day, AuditStatus.UNAUDITED, "cache_unavailable")
        else:
            audit = self._auditor.audit(day, reading.value)
        self._monitor.observe(audit)
        return audit

    # DurableDaySources ---------------------------------------------------------------------

    def entry_fill_count(self, day: str) -> int | None:
        reading = self.fills_reading(day)
        failure = reading.failure
        if failure is not None:
            if failure.reason == REASON_UNATTRIBUTABLE:
                raise UnattributableFill("fill record is not attributable")
            raise SourceReadError("fills")
        return reading.value

    def slot_counts(self, day: str) -> SlotDayCounts | None:
        reading = self.slots_reading(day)
        failure = reading.failure
        if failure is not None and failure.reason != REASON_UNATTRIBUTABLE:
            raise SourceReadError("slots")
        return reading.value

    def ledger_spend(self, day: str) -> Decimal | None:
        """Σ armed notional of the day's durable entry anchors: the SAME definition as the counter
        store's ``spend_usd`` (BG-1d compares like with like, so a partial fill never mismatches).
        The separate filled-spend metric (:meth:`filled_spend_reading`) is what the cache audits.
        A read failure is retried once, then raises :class:`SourceReadError`."""
        try:
            return self._retry_once(lambda: self._armed_spend(day))
        except Exception as exc:
            self._fail("armed_spend", REASON_READ_ERROR, type(exc).__name__)
            raise SourceReadError("armed_spend") from exc

    def joined_entries(self) -> tuple[_Entry, ...]:
        joined = self._joined()
        if isinstance(joined, SourceFailure):
            self._fail("entries", joined.reason, joined.exc_type)
            if joined.reason == REASON_UNATTRIBUTABLE:
                raise UnattributableFill("fill record is not attributable")
            raise SourceReadError("entries")
        if joined.all_fills_poisoned:
            raise UnattributableFill("fill record is not attributable")
        return tuple(joined.entries)

    # internals -------------------------------------------------------------------------------

    def _armed_spend(self, day: str) -> Decimal:
        total = Decimal(0)
        for anchor in self._anchors.read_order_anchors(day):
            notional = Decimal(anchor.notional)
            if anchor.day != day or not notional.is_finite() or notional < 0:
                raise _Corrupt
            total += notional
        return total

    @staticmethod
    def _retry_once[T](read: Callable[[], T]) -> T:
        try:
            return read()
        except _Unattributable:
            raise
        except Exception:  # noqa: BLE001 - one retry within the pass, then the caller raises
            return read()

    def _joined(self) -> _Joined | SourceFailure:
        if self._built is not None:
            return self._built
        if self._build_failure is None:
            for _attempt in range(2):
                try:
                    self._built = self._join.build()
                    return self._built
                except UnattributableFill as exc:
                    self._build_failure = (REASON_UNATTRIBUTABLE, type(exc).__name__)
                    break
                except _Corrupt as exc:
                    self._build_failure = (REASON_CORRUPT, type(exc).__name__)
                except Exception as exc:  # noqa: BLE001 - mapped to a typed failure
                    self._build_failure = (REASON_READ_ERROR, type(exc).__name__)
        reason, exc_type = self._build_failure or (REASON_READ_ERROR, None)
        return SourceFailure("join", reason, exc_type)

    def _orphan_failure(self, day: str, joined: _Joined) -> SourceFailure | None:
        if day in self._orphan_ok:
            return None
        try:
            self._retry_once(lambda: self._join.orphan_check(day, joined.reachable))
        except _Corrupt as exc:
            return SourceFailure("orphan", REASON_CORRUPT, type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - mapped to a typed failure
            return SourceFailure("orphan", REASON_READ_ERROR, type(exc).__name__)
        self._orphan_ok.add(day)
        return None

    def _marks(self, day: str) -> int:
        rows = self._ambiguous.read_ambiguous(day)
        for row in rows:
            if row.station == UNATTRIBUTED:
                raise _Unattributable
            try:
                placed = self._governed.entry_day(row.station, row.arm_ns)
            except Exception as exc:
                raise _Unattributable from exc
            if placed != day:
                raise _Unattributable
        return len(rows)

    def _fail[T](self, source: str, reason: str, exc_type: str | None = None) -> SourceReading[T]:
        failure = SourceFailure(source, reason, exc_type)
        self._failures.append(failure)
        _LOG.error(
            "exec_par durable source failure: source=%s reason=%s exc=%s",
            source,
            reason,
            exc_type or "-",
        )
        return SourceReading(False, None, failure)


class _Unattributable(Exception):
    """A mark cannot be placed on the day it is stored under."""


# -- slot source over the store -------------------------------------------------------------


class _KeyedStore(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def keys_with_prefix(self, prefix: str) -> list[str]: ...


class StoreIntentSource:
    """Open slots plus every retired ``intent/history/<id>`` row, deduplicated by intent id.

    ``decode`` is ``SubmitIntent.from_bytes``; a row that does not decode raises (never skipped).
    """

    def __init__(
        self,
        *,
        open_intents: Callable[[], Iterable[SlotView]],
        store: _KeyedStore,
        decode: Callable[[bytes], SlotView],
    ) -> None:
        self._open = open_intents
        self._store = store
        self._decode = decode

    def all_intents(self) -> Iterable[SlotView]:
        found: dict[str, SlotView] = {i.intent_id: i for i in self._open()}
        for key in self._store.keys_with_prefix(HISTORY_KEY_PREFIX):
            raw = self._store.get(key)
            if raw is None:
                raise _Corrupt
            record = self._decode(raw)
            found.setdefault(record.intent_id, record)
        return tuple(found.values())


# -- day bounds and counters_expected ---------------------------------------------------------


def day_bounds_from_offsets(
    std_offsets: Mapping[str, float],
) -> Callable[[str], tuple[int, int]]:
    """``day -> (earliest start, latest end)`` ns over the governed stations' standard time.

    A label is open for the earliest-rolling station first and closes with the latest-rolling one,
    so the union is the span in which any entry of that label can exist.
    """
    offsets = tuple(std_offsets.values())
    if not offsets:
        raise ValueError("no governed stations")

    def bounds(day: str) -> tuple[int, int]:
        midnight = dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC)
        base = int((midnight - _EPOCH).total_seconds()) * 1_000_000_000
        starts = [base - int(offset * _HOUR_NS) for offset in offsets]
        return min(starts), max(starts) + _DAY_NS

    return bounds


def counters_expected_from(
    epochs: Callable[[], Sequence[EpochRow]],
    *,
    now_ns: Callable[[], int],
    day_bounds_ns: Callable[[str], tuple[int, int]],
) -> Callable[[str], bool]:
    """``counters_expected(day)``: a BG-2 epoch with ``effective_k > 1`` overlaps ``day``.

    An epoch runs from ``boot_ts`` to its ``stop_ts``; without one, to the next boot (an unclean
    shutdown) or, for the latest, to now. Epochs are read on every call (a read failure raises
    loudly; BG-5b maps it to FAIL).
    """

    def expected(day: str) -> bool:
        start, end = day_bounds_ns(day)
        ordered = sorted(epochs(), key=lambda e: e.boot_ts)
        now = now_ns()
        for index, epoch in enumerate(ordered):
            if epoch.effective_k <= 1:
                continue
            if epoch.stop_ts is not None:
                window_end = epoch.stop_ts
            elif index + 1 < len(ordered):
                window_end = ordered[index + 1].boot_ts
            else:
                window_end = now
            if epoch.boot_ts < end and window_end > start:
                return True
        return False

    return expected


def entry_inputs_from(
    sources: DurableSources,
    days: Iterable[str],
    *,
    unresolved_intent_ids: frozenset[str],
    armed_cost_of: Callable[[str], Decimal | None],
) -> tuple[EntryInput, ...]:
    """BG-1c ``EntryInput`` rows for the entries on ``days`` (entries only, exits never).

    ``ever_ambiguous`` is true iff a BG-1b mark row exists for the intent id. An entry is an input
    when it has a confirmed fill or is an unresolved AMBIGUOUS one; the latter with no fill needs
    its armed notional from ``armed_cost_of`` (missing raises :class:`SourceReadError`). An input
    that cannot be placed on a station raises ``UnattributableFill``. ``unresolved_intent_ids``
    comes from venue-evidenced resolution, never from the mark.
    """
    wanted = frozenset(days)
    marked = sources.marked_intent_ids(wanted)
    inputs: list[EntryInput] = []
    for entry in sources.joined_entries():
        filled = entry.fill is not None and entry.fill.cumulative_qty > 0
        unresolved = entry.intent_id in unresolved_intent_ids
        if not (filled or unresolved):
            continue
        if entry.station is None or entry.day is None:
            raise UnattributableFill("fill record is not attributable")
        if entry.day not in wanted:
            continue
        fill = entry.fill if filled else None
        cost: Decimal | None = None
        if fill is None:
            cost = armed_cost_of(entry.intent_id)
            if cost is None:
                raise SourceReadError("armed_cost")
        inputs.append(
            EntryInput(
                arm_ns=entry.arm_ns,
                station=entry.station,
                fill=fill,
                ever_ambiguous=entry.intent_id in marked,
                ambiguous_unresolved=unresolved,
                ambiguous_cost=cost,
            )
        )
    return tuple(inputs)
