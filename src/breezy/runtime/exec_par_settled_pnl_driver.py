"""EXEC-PAR BG-5c WP-D: the settled-P&L driver (R8, A3, A6, A7, N-A; inert until WP-E wires it).

One pass: build the ``EntryInput`` rows with ``entry_inputs_from`` (so ``ever_ambiguous`` comes from
the BG-1b marks), refresh the settlement truth on an executor, score every entry through the BG-1c
accumulator and persist the whole-day rows (``persist_settled_pnl``) plus, for each per-station
floor stub, a stub row that covers ONLY the entries armed at or after ``floor.ts`` (N-A), stored
where the snapshot builder reads it as ``floor_stub_pnl``.

**Truth (R8.1, A7).** Reads are blocking file reads (``exec_par_settled_truth``) run through
``loop.run_in_executor``, one fresh read-only handle each, single-flight per ``(station, day)``,
each bounded by ``read_timeout_s``. A timeout or a read fault is "no outcome": the day is pending,
then overdue past ``SETTLEMENT_DEADLINE_DAYS``, never zero. A read that outlives its timeout keeps
running and its result lands on the loop (``call_soon_threadsafe``, via the executor future), so a
late FINAL is cached for the next pass. Only final-grade outcomes are cached; every pass
re-validates a cached final, so a revised CLI value replaces it and a final the store no longer
shows is invalidated (the day falls back to pending, which the BG-1c monotonic guard then refuses to
persist: fail closed, never a silent pnl rise). A failed RE-validation keeps the cached final: it
was final and unrevised when last seen, and a fault is not evidence of a change.

**Sign (A6).** The held side is the instrument id's own leg (``held_outcome``). A durable entry
record is a BUY of the held leg's instrument at the held leg's price, so ``cumulative_cost`` is
already the held cost: no cost flip happens here. The accumulator scores ``qty * outcome(held) -
cost - fee`` exactly as ``fq_scorer`` (``analysis`` is never imported on this path).

**Cents.** Each fill's cost is quantised to the cent (banker's rounding, :func:`cent_cost`, the
same rule the spend audit compares under) BEFORE any summing.

**Failure contract.** A source read failure, an unattributable fill or a malformed input propagates
typed (the runner turns it into FAIL); nothing is written. A persist failure raises
:class:`SettledPnlPersistError` (cause chained, no amounts). Nothing here logs a currency value.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import dataclasses
import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Protocol

from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_durable_sources import DurableSources, entry_inputs_from
from breezy.runtime.exec_par_records import SettledPnlDay, StageReset
from breezy.runtime.exec_par_settled_pnl import (
    CENT,
    EntryInput,
    FillLike,
    persist_settled_pnl,
    settled_pnl_by_day,
)
from breezy.runtime.exec_par_settled_truth import (
    CacheEvent,
    FinalTruthCache,
    TruthReader,
    TruthRecord,
    held_outcome,
)

__all__ = [
    "TRUTH_READ_TIMEOUT_S",
    "DriverDisposed",
    "PassReport",
    "PnlStore",
    "SettledPnlDriver",
    "SettledPnlPersistError",
    "cent_cost",
]

#: Bound on one truth read before the day is scored pending (A7).
TRUTH_READ_TIMEOUT_S: Final[float] = 5.0
_MAX_WORKERS: Final[int] = 2
_THREAD_PREFIX: Final[str] = "exec_par_pnl_truth"

type _TruthKey = tuple[str, dt.date]


@dataclass(frozen=True, slots=True)
class _Outcome:
    """One executor read, posted back to the loop thread."""

    record: TruthRecord | None
    failed: bool


class DriverDisposed(RuntimeError):
    """The driver was disposed; its executor is shut down."""


class SettledPnlPersistError(RuntimeError):
    """A settled-P&L row could not be persisted (the runner maps this to FAIL)."""


class PnlStore(Protocol):
    """The slice of the submit-intent latch the driver writes and reads."""

    def read_stage_reset(self) -> StageReset | None: ...
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...
    def write_floor_stub_pnl_day(self, record: SettledPnlDay) -> None: ...


@dataclass(frozen=True, slots=True)
class PassReport:
    """What one pass did, in counts only (never amounts)."""

    days: int
    stub_days: int
    truth_timeouts: int
    truth_errors: int
    revisions: int
    invalidations: int


def cent_cost(value: Decimal) -> Decimal:
    """A fill cost at the venue's cent, banker's rounding (the spend audit's rule)."""
    return value.quantize(CENT, ROUND_HALF_EVEN)


class _CentFill:
    """A fill whose cost is quantised to the cent; everything else is the wrapped record's."""

    __slots__ = ("_inner", "cumulative_cost")

    def __init__(self, inner: FillLike) -> None:
        self._inner = inner
        self.cumulative_cost = cent_cost(inner.cumulative_cost)

    @property
    def instrument_id(self) -> str:
        return self._inner.instrument_id

    @property
    def order_side(self) -> str:
        return self._inner.order_side

    @property
    def cumulative_qty(self) -> Decimal:
        return self._inner.cumulative_qty

    @property
    def cumulative_fee(self) -> Decimal:
        return self._inner.cumulative_fee

    @property
    def fee_reconciled(self) -> bool:
        return self._inner.fee_reconciled

    @property
    def fee_coefficient_at_fill(self) -> Decimal | None:
        return self._inner.fee_coefficient_at_fill


def _quantised(entry: EntryInput) -> EntryInput:
    if entry.fill is None:
        return entry
    return dataclasses.replace(entry, fill=_CentFill(entry.fill))


class SettledPnlDriver:
    """Loop-thread driver; ``run_pass`` is awaited by the daily pass and by the seq trigger."""

    def __init__(
        self,
        *,
        reader: TruthReader,
        facts_of: Callable[[str], WeatherBucketFacts | None],
        sources_factory: Callable[[], DurableSources],
        days: Callable[[], Iterable[str]],
        unresolved_intent_ids: Callable[[], frozenset[str]],
        armed_cost_of: Callable[[str], Decimal | None],
        governed: DayConvention,
        store: PnlStore,
        today: Callable[[], str],
        read_timeout_s: float = TRUTH_READ_TIMEOUT_S,
    ) -> None:
        self._reader = reader
        self._facts_of = facts_of
        self._sources_factory = sources_factory
        self._days = days
        self._unresolved = unresolved_intent_ids
        self._armed_cost_of = armed_cost_of
        self._governed = governed
        self._store = store
        self._today = today
        self._timeout = read_timeout_s
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=_MAX_WORKERS, thread_name_prefix=_THREAD_PREFIX
        )
        self._cache = FinalTruthCache()
        self._inflight: dict[_TruthKey, asyncio.Future[None]] = {}
        self._disposed = False
        self._seq = 0
        self._last: tuple[tuple[SettledPnlDay, ...], tuple[SettledPnlDay, ...]] | None = None
        self._timeouts = 0
        self._errors = 0
        self._revisions = 0
        self._invalidations = 0

    # -- public ----------------------------------------------------------------------------

    def settled_pnl_seq(self) -> int:
        """Monotonic; moves only when a persisted row (whole-day or stub) changed."""
        return self._seq

    def dispose(self) -> None:
        """Idempotent. Pending reads are cancelled; a running one finishes and is discarded."""
        if self._disposed:
            return
        self._disposed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def run_pass(self) -> PassReport:
        if self._disposed:
            raise DriverDisposed("the settled-P&L driver is disposed")
        entries = tuple(
            _quantised(entry)
            for entry in entry_inputs_from(
                self._sources_factory(),
                tuple(self._days()),
                unresolved_intent_ids=self._unresolved(),
                armed_cost_of=self._armed_cost_of,
            )
        )
        facts = self._facts_for(entries)
        before = (self._timeouts, self._errors, self._revisions, self._invalidations)
        await self._refresh({self._key(f) for f in facts.values()})
        outcomes = self._outcomes(facts)
        today = self._today()
        rows = settled_pnl_by_day(entries, outcomes, self._governed.entry_day, today=today)
        stubs = self._stub_rows(entries, outcomes, today)
        self._persist(rows, stubs)
        after = (self._timeouts, self._errors, self._revisions, self._invalidations)
        t, e, r, i = (a - b for a, b in zip(after, before, strict=True))
        return PassReport(len(rows), len(stubs), t, e, r, i)

    # -- truth -----------------------------------------------------------------------------

    @staticmethod
    def _key(facts: WeatherBucketFacts) -> _TruthKey:
        return (facts.settlement_station, facts.climate_day)

    def _facts_for(self, entries: Iterable[EntryInput]) -> dict[str, WeatherBucketFacts]:
        found: dict[str, WeatherBucketFacts] = {}
        for entry in entries:
            if entry.fill is None or entry.fill.instrument_id in found:
                continue
            instrument_id = entry.fill.instrument_id
            try:
                facts = self._facts_of(instrument_id)
            except Exception:  # noqa: BLE001 - an unresolvable rung is "no outcome", never a zero
                facts = None
            if facts is not None:
                found[instrument_id] = facts
        return found

    def _outcomes(self, facts: Mapping[str, WeatherBucketFacts]) -> dict[str, bool | None]:
        outcomes: dict[str, bool | None] = {}
        for instrument_id, bucket in facts.items():
            held = held_outcome(instrument_id, bucket, self._cache.get(self._key(bucket)))
            if held is not None:
                outcomes[instrument_id] = held
        return outcomes

    async def _refresh(self, keys: Iterable[_TruthKey]) -> None:
        await asyncio.gather(*(self._fetch(key) for key in sorted(keys)))

    async def _fetch(self, key: _TruthKey) -> None:
        """Wait (bounded) for the single in-flight read of ``key``; never raises a read fault."""
        try:
            fut = self._inflight.get(key) or self._launch(key)
            await asyncio.wait_for(asyncio.shield(fut), self._timeout)
        except TimeoutError:
            self._timeouts += 1
        except RuntimeError:  # the executor was shut down under a pass: the day is pending
            self._errors += 1

    def _launch(self, key: _TruthKey) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        self._inflight[key] = done
        work = loop.run_in_executor(self._executor, self._read_and_post, loop, key, done)
        work.add_done_callback(lambda finished: self._on_work_done(key, done, finished))
        return done

    def _read_and_post(
        self, loop: asyncio.AbstractEventLoop, key: _TruthKey, done: asyncio.Future[None]
    ) -> None:
        """EXECUTOR thread: one read on its own handle, posted back to the loop (A7)."""
        outcome: _Outcome
        try:
            outcome = _Outcome(self._reader.read(key[0], key[1]), failed=False)
        except Exception:  # noqa: BLE001 - any read fault means "no outcome", counted on the loop
            outcome = _Outcome(None, failed=True)
        with contextlib.suppress(RuntimeError):  # the loop closed under us: nothing to post to
            loop.call_soon_threadsafe(self._land, key, done, outcome)

    def _land(self, key: _TruthKey, done: asyncio.Future[None], outcome: _Outcome) -> None:
        """LOOP thread: release the waiters, then fold a successful read into the cache."""
        if self._inflight.get(key) is done:
            del self._inflight[key]
        if not done.done():
            done.set_result(None)
        if self._disposed:
            return
        if outcome.failed:
            self._errors += 1
            return
        event = self._cache.land(key, outcome.record)
        if event is CacheEvent.REVISED:
            self._revisions += 1
        elif event is CacheEvent.INVALIDATED:
            self._invalidations += 1

    def _on_work_done(
        self, key: _TruthKey, done: asyncio.Future[None], work: asyncio.Future[None]
    ) -> None:
        """LOOP thread: a job cancelled by shutdown never posts, so release its waiters."""
        if not work.cancelled():
            work.exception()  # retrieved: _read_and_post catches everything itself
            return
        if self._inflight.get(key) is done:
            del self._inflight[key]
        if not done.done():
            done.set_result(None)

    # -- stub rows and persistence ---------------------------------------------------------

    def _stub_rows(
        self, entries: tuple[EntryInput, ...], outcomes: Mapping[str, bool | None], today: str
    ) -> dict[str, SettledPnlDay]:
        floor = self._store.read_stage_reset()
        if floor is None:
            return {}
        labels = self._governed.open_days_at(floor.ts)
        post = tuple(
            entry
            for entry in entries
            if entry.arm_ns >= floor.ts
            and self._governed.entry_day(entry.station, entry.arm_ns) in labels
        )
        return settled_pnl_by_day(post, outcomes, self._governed.entry_day, today=today)

    def _persist(
        self, rows: Mapping[str, SettledPnlDay], stubs: Mapping[str, SettledPnlDay]
    ) -> None:
        try:
            persist_settled_pnl(self._store, rows)
            for day in sorted(stubs):
                self._store.write_floor_stub_pnl_day(stubs[day])
        except Exception as exc:
            raise SettledPnlPersistError("settled-P&L persist failed") from exc
        state = (tuple(rows[d] for d in sorted(rows)), tuple(stubs[d] for d in sorted(stubs)))
        if state != self._last:
            self._last = state
            self._seq += 1
