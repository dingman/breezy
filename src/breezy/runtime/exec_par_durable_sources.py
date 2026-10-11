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

**Spend (R3).** Σ over entry orders of the ``cumulative_cost`` of the order's TERMINAL record (max
``cumulative_qty``): the client rewrites one cumulative record per venue order, so partial fills
are never summed.

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
excludes the day. A full-coverage mismatch is routed to the BG-1d exclusion path
(``ledger_spend`` returns ``None``).

Use a FRESH :class:`DurableSources` per reconcile pass: the slot/fill join is read once and cached.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Final, Protocol

from breezy.domain.exec_intent import (
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
from breezy.runtime.exec_par_records import AmbiguousRow, EpochRow
from breezy.runtime.exec_par_settled_pnl import SETTLEMENT_DEADLINE_DAYS

__all__ = [
    "HISTORY_KEY_PREFIX",
    "UNATTRIBUTED",
    "AmbiguousRowsPort",
    "AuditStatus",
    "CacheFill",
    "CacheFillPort",
    "DurableSources",
    "FillStoreReader",
    "IntentSource",
    "SlotView",
    "SourceFailure",
    "SourceReading",
    "SpendAudit",
    "SpendAuditor",
    "StoreIntentSource",
    "counters_expected_from",
    "day_bounds_from_offsets",
    "terminal_fill",
]

#: Restated (a test pins it equal to ``submit_intent.history_key("")``): retired-slot rows.
HISTORY_KEY_PREFIX: Final[str] = "exec/polymarket_us/intent/history/"
#: Restated from ``exec_par_counter_ingest.UNATTRIBUTED`` (a test pins equality) so this module
#: never loads the ingest layer's Nautilus imports.
UNATTRIBUTED: Final[str] = "unattributed"
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


class FillRecordLike(Protocol):
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


@dataclass(slots=True)
class _Joined:
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
            if intent.is_exit:
                continue
            fill = self._fill_of(intent)
            if fill is not None:
                _check_amounts(fill)
            filled = fill is not None and fill.cumulative_qty > 0
            station = self._station(intent.slug)
            day = self._day(station, intent.created_ns)
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

    def _fill_of(self, intent: SlotView) -> FillRecordLike | None:
        try:
            day = utc_day_for_ns(intent.created_ns).isoformat()
        except ValueError:
            raise _Corrupt from None
        raw_id = self._store.get(f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{intent.fingerprint}")
        if raw_id is None:
            return None
        raw = self._store.get(f"{FILL_KEY_PREFIX}{raw_id.decode('utf-8', 'replace')}")
        if raw is None:
            raise _Corrupt
        try:
            return terminal_fill([self._decode(raw)])
        except Exception as exc:
            raise _Corrupt from exc


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
        """``spend_unaudited``: no look is taken; it is NOT a failed look (A2)."""
        return self.status is AuditStatus.UNAUDITED

    def excludes_day(self, today: str) -> bool:
        """An unaudited day at least ``SETTLEMENT_DEADLINE_DAYS`` old becomes ``day_excluded``."""
        if self.status is not AuditStatus.UNAUDITED:
            return False
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(self.day)).days
        return age >= SETTLEMENT_DEADLINE_DAYS


class SpendAuditor:
    """Compares durable spend with the cache's entry-fill costs under the A2 coverage rule."""

    def __init__(
        self,
        *,
        cache: CacheFillPort | None,
        governed: DayConvention,
        station_of: Callable[[str], str | None],
        boot_ts_ns: int,
        lookback_ns: int,
        day_start_ns: Callable[[str], int],
    ) -> None:
        self._cache = cache
        self._governed = governed
        self._station_of = station_of
        self._boot = boot_ts_ns
        self._lookback = lookback_ns
        self._day_start = day_start_ns

    def audit(self, day: str, durable: Decimal) -> SpendAudit:
        if self._day_start(day) < self._boot - self._lookback:
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
        status = AuditStatus.FULL_MATCH if cache_total == durable else AuditStatus.MISMATCH
        return SpendAudit(day, status, None, durable, cache_total)

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
    """The BG-1d ``DurableDaySources`` over the slot table, durable fills and mark rows."""

    def __init__(
        self,
        *,
        intents: IntentSource,
        store: FillStoreReader,
        decode_fill: Callable[[bytes], FillRecordLike],
        governed: DayConvention,
        station_of: Callable[[str], str | None],
        ambiguous: AmbiguousRowsPort,
        auditor: SpendAuditor | None = None,
    ) -> None:
        self._join = _Join(intents, store, decode_fill, governed, station_of)
        self._governed = governed
        self._ambiguous = ambiguous
        self._auditor = auditor
        self._built: _Joined | None = None
        self._build_failure: str | None = None
        self._failures: list[SourceFailure] = []

    @property
    def failures(self) -> tuple[SourceFailure, ...]:
        return tuple(self._failures)

    # typed readings -----------------------------------------------------------------------

    def fills_reading(self, day: str) -> SourceReading[int]:
        joined = self._joined()
        if isinstance(joined, str):
            return self._fail("fills", joined)
        if joined.all_fills_poisoned or day in joined.fill_poison:
            return self._fail("fills", REASON_UNATTRIBUTABLE)
        return SourceReading.success(joined.fills.get(day, 0))

    def spend_reading(self, day: str) -> SourceReading[Decimal]:
        joined = self._joined()
        if isinstance(joined, str):
            return self._fail("spend", joined)
        if joined.all_fills_poisoned or day in joined.fill_poison:
            return self._fail("spend", REASON_UNATTRIBUTABLE)
        return SourceReading.success(joined.spend.get(day, Decimal(0)))

    def slots_reading(self, day: str) -> SourceReading[SlotDayCounts]:
        joined = self._joined()
        if isinstance(joined, str):
            return self._fail("slots", joined)
        if joined.all_posted_poisoned or day in joined.posted_poison:
            return self._fail("slots", REASON_UNATTRIBUTABLE)
        try:
            marks = self._marks(day)
        except _Unattributable:
            return self._fail("slots", REASON_UNATTRIBUTABLE)
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return self._fail("slots", REASON_READ_ERROR)
        return SourceReading.success(SlotDayCounts(joined.posted.get(day, 0), marks))

    def unattributed_ambiguous_reading(self) -> SourceReading[int]:
        """Marks BG-1b could not place on a day (kept apart; never folded into a day)."""
        try:
            return SourceReading.success(len(self._ambiguous.read_ambiguous(UNATTRIBUTED)))
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            return self._fail("unattributed_ambiguous", REASON_READ_ERROR)

    def audit_spend(self, day: str) -> SpendAudit:
        reading = self.spend_reading(day)
        if not reading.ok or reading.value is None:
            return SpendAudit(day, AuditStatus.DURABLE_UNREADABLE)
        if self._auditor is None:
            return SpendAudit(day, AuditStatus.UNAUDITED, "cache_unavailable")
        return self._auditor.audit(day, reading.value)

    # DurableDaySources ---------------------------------------------------------------------

    def entry_fill_count(self, day: str) -> int | None:
        reading = self.fills_reading(day)
        if reading.failure is not None and reading.failure.reason == REASON_UNATTRIBUTABLE:
            raise UnattributableFill("fill record is not attributable")
        return reading.value

    def slot_counts(self, day: str) -> SlotDayCounts | None:
        return self.slots_reading(day).value

    def ledger_spend(self, day: str) -> Decimal | None:
        reading = self.spend_reading(day)
        if not reading.ok or reading.value is None:
            return None
        if (
            self._auditor is not None
            and self._auditor.audit(day, reading.value).status is AuditStatus.MISMATCH
        ):
            self._failures.append(SourceFailure("spend", REASON_AUDIT_MISMATCH))
            return None
        return reading.value

    # internals -------------------------------------------------------------------------------

    def _joined(self) -> _Joined | str:
        if self._built is not None:
            return self._built
        if self._build_failure is not None:
            return self._build_failure
        try:
            self._built = self._join.build()
        except UnattributableFill:
            self._build_failure = REASON_UNATTRIBUTABLE
        except _Corrupt:
            self._build_failure = REASON_CORRUPT
        except Exception:  # noqa: BLE001 - mapped to a typed failure, never a zero
            self._build_failure = REASON_READ_ERROR
        return self._built if self._built is not None else str(self._build_failure)

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

    def _fail[T](self, source: str, reason: str) -> SourceReading[T]:
        reading: SourceReading[T] = SourceReading.failed(source, reason)
        if reading.failure is not None:
            self._failures.append(reading.failure)
        return reading


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
