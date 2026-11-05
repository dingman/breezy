"""EXEC-PAR BG-5c WP-D: the settled-P&L driver (R8, A3, A6, A7, N-A; inert until WP-E wires it).

One pass: build the ``EntryInput`` rows with ``entry_inputs_from`` (so ``ever_ambiguous`` comes from
the BG-1b marks), refresh the settlement truth on an executor, score every entry through the BG-1c
accumulator and persist the whole-day rows plus, for each per-station floor stub, a stub row that
covers ONLY the entries armed at or after ``floor.ts`` (N-A), stored where the snapshot builder
reads it as ``floor_stub_pnl``.

**Truth (R8.1, A7).** Reads are blocking file reads (``exec_par_settled_truth``) run through
``loop.run_in_executor``, one fresh read-only handle each, single-flight per ``(station, day)``,
each bounded by ``read_timeout_s``. The worker posts its result back to the loop with
``call_soon_threadsafe``. A timeout or a read fault is "no outcome": the day is pending, then
overdue past ``SETTLEMENT_DEADLINE_DAYS``, never zero. A read that outlives its timeout keeps
running and its result lands on the loop, so a late FINAL is cached for the next pass. Only
final-grade outcomes are cached.

**Corrections.** The driver scores on the first FINAL it reads. The F2 dataset serves only
PROMOTED CLI revisions, so an upstream correction that has not been promoted changes nothing; once
promoted, the next re-validation sees a new token and the day is re-scored (below).

**Re-validation and staleness.** Every pass re-reads each cached final. A failed re-validation keeps
the cached final (it was final and unrevised when last seen, and a fault is not evidence of a
change), counts a per-key error streak, alerts once at 3 consecutive failed passes and reports the
streak. A cached final unrevalidated for more than 24 h is dropped back to pending: conservative,
it ages into overdue at full loss. That drop is a staleness drop, not a shrink FAIL.

**Persistence (never wedged silently).** Each day row and each stub row is persisted in its OWN
try block; one failure never blocks the others, and the trigger seq moves whenever any write lands.
A row that fails the BG-1c monotonic guard goes one of three ways:
* a PROMOTED CLI revision of its station-day (``REVISED`` this or an earlier unpersisted pass):
  an audit row ``settled_pnl_revision/<label>/<ts_ns>`` is written first, then the latch replaces
  the row (the only non-monotonic write it allows, and only under that audit row);
* a drop in ``settled_entries``, or an invalidated final, that is not a revision: FAIL
  ``settled_truth_shrank:<label>`` (the row is withheld);
* anything else: FAIL ``settled_pnl_regression:<label>``.
Each named FAIL also alerts once (de-duplicated until it clears). The pass raises after every row
has been tried: :class:`SettledPnlFail` for named failures, else :class:`SettledPnlPersistError`
(a stub row's reason carries a ``:stub`` suffix).

**Sign (A6).** The held side is the instrument id's own leg (``held_outcome``). A durable entry
record is a BUY of the held leg's instrument at the held leg's price, so ``cumulative_cost`` is
already the held cost: no cost flip happens here. The accumulator scores ``qty * outcome(held) -
cost - fee`` exactly as ``fq_scorer`` (``analysis`` is never imported on this path).

**Cents.** Each fill's cost is quantised to the cent (banker's rounding, :func:`cent_cost`, the
same rule the spend audit compares under) BEFORE any summing.

**Failure contract.** A source read failure, an unattributable fill or a malformed input propagates
typed (the runner turns it into FAIL); nothing is written. An entry whose rung facts cannot be
resolved is pending (counted as ``facts_missing``, only the exception TYPE is logged) and FAILs
``facts_missing`` once it is past the settlement deadline. Nothing here logs a currency value.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Protocol

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_durable_sources import DurableSources, entry_inputs_from
from breezy.runtime.exec_par_daemon_executor import DaemonExecutor
from breezy.runtime.exec_par_records import (
    SettledPnlBasis,
    SettledPnlDay,
    SettledPnlRevision,
    StageReset,
)
from breezy.runtime.exec_par_settled_pnl import (
    CENT,
    SETTLEMENT_DEADLINE_DAYS,
    EntryInput,
    FillLike,
    SettledPnlRegression,
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
    "STALE_FINAL_AFTER_S",
    "STREAK_ALERT_AT",
    "TRUTH_READ_TIMEOUT_S",
    "DriverDisposed",
    "PassReport",
    "PnlStore",
    "SettledPnlDriver",
    "SettledPnlFail",
    "SettledPnlPersistError",
    "cent_cost",
]

_LOG = logging.getLogger(__name__)

#: Bound on one truth read before the day is scored pending (A7).
TRUTH_READ_TIMEOUT_S: Final[float] = 5.0
#: A cached final not re-validated for longer than this drops back to pending.
STALE_FINAL_AFTER_S: Final[float] = 24 * 3600.0
#: Consecutive failed re-validation passes (per station-day) before the alert.
STREAK_ALERT_AT: Final[int] = 3
_MAX_WORKERS: Final[int] = 2
_THREAD_PREFIX: Final[str] = "exec_par_pnl_truth"
_CAUSE_REVISION: Final[str] = "cli_revision"
_NO_SHA: Final[str] = "unknown"

type _TruthKey = tuple[str, dt.date]


@dataclass(frozen=True, slots=True)
class _Outcome:
    """One executor read, posted back to the loop thread."""

    record: TruthRecord | None
    failed: bool


class DriverDisposed(RuntimeError):
    """The driver was disposed; its executor is shut down."""


class SettledPnlPersistError(RuntimeError):
    """Rows could not be persisted (the runner maps this to FAIL). ``reasons`` carry no amounts."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(";".join(reasons))
        self.reasons = reasons


class SettledPnlFail(SettledPnlPersistError):
    """At least one NAMED FAIL (regression, shrunk truth, missing facts): see ``reasons``."""


class PnlStore(Protocol):
    """The slice of the submit-intent latch the driver writes and reads."""

    def read_stage_reset(self) -> StageReset | None: ...
    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None: ...
    def read_floor_stub_pnl_day(self, day: str) -> SettledPnlDay | None: ...
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...
    def write_floor_stub_pnl_day(self, record: SettledPnlDay) -> None: ...
    def read_settled_pnl_basis(self, day: str, scope: str) -> SettledPnlBasis | None: ...
    def write_settled_pnl_basis(self, record: SettledPnlBasis) -> None: ...
    def write_settled_pnl_revision(self, record: SettledPnlRevision) -> None: ...
    def replace_settled_pnl_day_for_revision(self, record: SettledPnlDay, ts_ns: int) -> None: ...
    def replace_floor_stub_pnl_for_revision(self, record: SettledPnlDay, ts_ns: int) -> None: ...


@dataclass(frozen=True, slots=True)
class PassReport:
    """What one pass did, in counts only (never amounts)."""

    days: int
    stub_days: int
    truth_timeouts: int
    truth_errors: int
    revisions: int
    invalidations: int
    facts_missing: int = 0
    measure_unsupported: int = 0
    stale_dropped: int = 0
    truth_error_streak: int = 0


@dataclass(frozen=True, slots=True)
class _Failure:
    reason: str
    named: bool
    cause: BaseException | None = None
    #: the ROW landed even though the pass of this row failed (e.g. its basis write did not)
    landed: bool = False


def _new_executor() -> DaemonExecutor:
    """Daemon workers: a hung local read must never block interpreter exit."""
    return DaemonExecutor(_MAX_WORKERS, _THREAD_PREFIX)


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


@dataclass(slots=True)
class _Resolved:
    """Per-pass rung resolution: facts by instrument, plus what could not be resolved."""

    facts: dict[str, WeatherBucketFacts]
    missing: set[str]


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
        alert: Callable[[str], object],
        read_timeout_s: float = TRUTH_READ_TIMEOUT_S,
        clock_ns: Callable[[], int] = time.time_ns,
        monotonic: Callable[[], float] = time.monotonic,
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
        self._alert = alert
        self._timeout = read_timeout_s
        self._clock_ns = clock_ns
        self._monotonic = monotonic
        self._executor = _new_executor()
        self._cache = FinalTruthCache()
        self._inflight: dict[_TruthKey, asyncio.Future[None]] = {}
        self._disposed = False
        self._seq = 0
        self._written: dict[tuple[str, str], SettledPnlDay] = {}
        self._alerted: set[str] = set()
        self._ok_count: dict[_TruthKey, int] = {}
        self._last_ok: dict[_TruthKey, float] = {}
        self._streak: dict[_TruthKey, int] = {}
        self._revised: dict[_TruthKey, TruthRecord] = {}
        self._invalidated: set[_TruthKey] = set()
        self._revision_labels: dict[str, str] = {}
        self._basis: dict[str, dict[str, TruthRecord]] = {}
        self._basis_text: dict[tuple[str, str], str] = {}
        self._timeouts = 0
        self._errors = 0
        self._revisions = 0
        self._invalidations = 0

    # -- public ----------------------------------------------------------------------------

    def settled_pnl_seq(self) -> int:
        """Monotonic; moves whenever a persisted row (whole-day or stub) changed."""
        return self._seq

    def dispose(self) -> None:
        """Idempotent. Pending reads are cancelled, waiters are released, nothing posts back."""
        if self._disposed:
            return
        self._disposed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        for done in list(self._inflight.values()):
            if not done.done():
                done.set_result(None)
        self._inflight.clear()

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
        resolved = self._rung_facts(entries)
        keys = {self._key(f) for f in resolved.facts.values()}
        before = (self._timeouts, self._errors, self._revisions, self._invalidations)
        ok_before = {key: self._ok_count.get(key, 0) for key in keys}
        await self._refresh(keys)
        if self._disposed:
            raise DriverDisposed("the settled-P&L driver was disposed mid-pass")
        streak = self._update_streaks(keys, ok_before)
        stale = self._drop_stale(keys)
        labels_by_key = self._labels_by_key(entries, resolved)
        shrink_labels = self._consume_events(labels_by_key)
        self._basis = self._basis_by_label(labels_by_key)
        stale_labels = {label for key in stale for label in labels_by_key.get(key, ())}
        outcomes = self._outcomes(resolved.facts)
        today = self._today()
        rows = settled_pnl_by_day(entries, outcomes, self._governed.entry_day, today=today)
        stubs = self._stub_rows(entries, outcomes, today)
        failures = self._persist(rows, stubs, shrink_labels, stale_labels)
        missing_old = self._facts_failure(entries, resolved, today)
        if missing_old is not None:
            failures.append(missing_old)
        self._raise_for(failures, streak)
        after = (self._timeouts, self._errors, self._revisions, self._invalidations)
        t, e, r, i = (a - b for a, b in zip(after, before, strict=True))
        return PassReport(
            len(rows),
            len(stubs),
            t,
            e,
            r,
            i,
            facts_missing=self._count_entries(entries, resolved.missing),
            measure_unsupported=self._count_unsupported(entries, resolved.facts),
            stale_dropped=len(stale),
            truth_error_streak=max(streak.values(), default=0),
        )

    # -- rung facts ------------------------------------------------------------------------

    @staticmethod
    def _key(facts: WeatherBucketFacts) -> _TruthKey:
        return (facts.settlement_station, facts.climate_day)

    def _rung_facts(self, entries: Iterable[EntryInput]) -> _Resolved:
        resolved = _Resolved({}, set())
        for entry in entries:
            if entry.fill is None:
                continue
            instrument_id = entry.fill.instrument_id
            if instrument_id in resolved.facts or instrument_id in resolved.missing:
                continue
            try:
                facts = self._facts_of(instrument_id)
            except Exception as exc:  # noqa: BLE001 - "no outcome", never a zero
                _LOG.warning("settled-P&L rung facts unavailable (%s)", type(exc).__name__)
                facts = None
            if facts is None:
                resolved.missing.add(instrument_id)
            else:
                resolved.facts[instrument_id] = facts
        return resolved

    @staticmethod
    def _count_entries(entries: Iterable[EntryInput], instruments: set[str]) -> int:
        return sum(1 for e in entries if e.fill is not None and e.fill.instrument_id in instruments)

    @staticmethod
    def _count_unsupported(
        entries: Iterable[EntryInput], facts: Mapping[str, WeatherBucketFacts]
    ) -> int:
        return sum(
            1
            for e in entries
            if e.fill is not None
            and (found := facts.get(e.fill.instrument_id)) is not None
            and found.measure is not Measure.HIGH
        )

    def _facts_failure(
        self, entries: Iterable[EntryInput], resolved: _Resolved, today: str
    ) -> _Failure | None:
        """FAIL when an entry whose rung is unresolved is past the settlement deadline."""
        now = dt.date.fromisoformat(today)
        for entry in entries:
            if entry.fill is None or entry.fill.instrument_id not in resolved.missing:
                continue
            day = dt.date.fromisoformat(self._governed.entry_day(entry.station, entry.arm_ns))
            if (now - day).days >= SETTLEMENT_DEADLINE_DAYS:
                return _Failure("facts_missing", named=True)
        return None

    def _labels_by_key(
        self, entries: Iterable[EntryInput], resolved: _Resolved
    ) -> dict[_TruthKey, set[str]]:
        found: dict[_TruthKey, set[str]] = {}
        for entry in entries:
            if (
                entry.fill is None
                or (facts := resolved.facts.get(entry.fill.instrument_id)) is None
            ):
                continue
            label = self._governed.entry_day(entry.station, entry.arm_ns)
            found.setdefault(self._key(facts), set()).add(label)
        return found

    # -- truth -----------------------------------------------------------------------------

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

    def _launch(self, key: _TruthKey) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        self._inflight[key] = done
        try:
            work = loop.run_in_executor(self._executor, self._read_and_post, loop, key, done)
        except Exception as exc:  # noqa: BLE001 - e.g. an executor shut down under us: day pending
            _LOG.warning("settled-P&L truth read not scheduled (%s)", type(exc).__name__)
            self._errors += 1
            self._inflight.pop(key, None)
            done.set_result(None)
            return done
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
        if self._disposed:
            return  # never post into a disposed driver
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
        self._ok_count[key] = self._ok_count.get(key, 0) + 1
        self._last_ok[key] = self._monotonic()
        event = self._cache.land(key, outcome.record)
        if event is CacheEvent.REVISED and outcome.record is not None:
            self._revisions += 1
            self._revised[key] = outcome.record
        elif event is CacheEvent.INVALIDATED:
            self._invalidations += 1
            self._invalidated.add(key)

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

    def _update_streaks(
        self, keys: Iterable[_TruthKey], ok_before: Mapping[_TruthKey, int]
    ) -> dict[_TruthKey, int]:
        streaks: dict[_TruthKey, int] = {}
        for key in keys:
            failed = self._ok_count.get(key, 0) == ok_before[key]
            self._streak[key] = self._streak.get(key, 0) + 1 if failed else 0
            streaks[key] = self._streak[key]
        return streaks

    def _drop_stale(self, keys: Iterable[_TruthKey]) -> set[_TruthKey]:
        now = self._monotonic()
        dropped = {
            key
            for key in keys
            if self._cache.get(key) is not None
            and now - self._last_ok.get(key, now) > STALE_FINAL_AFTER_S
        }
        for key in dropped:
            self._cache.drop(key)
        return dropped

    def _basis_by_label(
        self, labels_by_key: Mapping[_TruthKey, set[str]]
    ) -> dict[str, dict[str, TruthRecord]]:
        """Per label, the cached FINAL each of its station-days is currently scored from."""
        basis: dict[str, dict[str, TruthRecord]] = {}
        for key, labels in labels_by_key.items():
            record = self._cache.get(key)
            if record is None:
                continue
            for label in labels:
                basis.setdefault(label, {})[f"{key[0]}@{key[1].isoformat()}"] = record
        return basis

    def _consume_events(self, labels_by_key: Mapping[_TruthKey, set[str]]) -> set[str]:
        """Map this pass's REVISED / INVALIDATED events onto labels. Revisions stay pending until
        their label persists; invalidations apply to this pass only."""
        for key, record in self._revised.items():
            for label in labels_by_key.get(key, ()):
                self._revision_labels[label] = record.product_sha256 or _NO_SHA
        self._revised.clear()
        shrink = {label for key in self._invalidated for label in labels_by_key.get(key, ())}
        self._invalidated.clear()
        return shrink

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
        self,
        rows: Mapping[str, SettledPnlDay],
        stubs: Mapping[str, SettledPnlDay],
        shrink_labels: set[str],
        stale_labels: set[str],
    ) -> list[_Failure]:
        """Try EVERY row in its own block; collect failures; bump the seq if anything landed."""
        failures: list[_Failure] = []
        failed_labels: set[str] = set()
        landed = False
        for kind, mapping in (("day", rows), ("stub", stubs)):
            for label in sorted(mapping):
                record = mapping[label]
                failure = self._write_one(
                    kind, record, label in shrink_labels, label in stale_labels
                )
                if failure is not None:
                    failures.append(failure)
                    failed_labels.add(label)
                    if not failure.landed:
                        continue
                if self._written.get((kind, label)) != record:
                    self._written[(kind, label)] = record
                    landed = True
        for label in set(rows) | set(stubs):
            if label not in failed_labels:
                self._revision_labels.pop(label, None)
        if landed:
            self._seq += 1
        return failures

    def _write_one(
        self, kind: str, record: SettledPnlDay, invalidated: bool, stale: bool
    ) -> _Failure | None:
        label = record.day
        suffix = "" if kind == "day" else ":stub"
        try:
            prior = self._prior(kind, label)
            if invalidated or (not stale and self._shrank(prior, record, label)):
                return _Failure(f"settled_truth_shrank:{label}{suffix}", named=True)
            self._write(kind, record)
        except SettledPnlRegression as exc:
            return self._accept_revision(kind, record, label, suffix, exc)
        except Exception as exc:  # noqa: BLE001 - isolated: one row never blocks the others
            return _Failure(f"settled_pnl_persist_failed:{label}{suffix}", named=False, cause=exc)
        return self._record_basis(kind, label, suffix)

    def _basis_now(self, label: str) -> dict[str, TruthRecord]:
        return self._basis.get(label, {})

    def _record_basis(self, kind: str, label: str, suffix: str) -> _Failure | None:
        """AFTER the row landed: remember which CLI products it was built from (durable)."""
        current = self._basis_now(label)
        text = ";".join(f"{k}={current[k].token}" for k in sorted(current))
        if not text or self._basis_text.get((kind, label)) == text:
            return None
        try:
            self._store.write_settled_pnl_basis(SettledPnlBasis(label, kind, text))
        except Exception as exc:  # noqa: BLE001 - the row is in; only its basis is missing
            return _Failure(
                f"settled_pnl_basis_write_failed:{label}{suffix}",
                named=False,
                cause=exc,
                landed=True,
            )
        self._basis_text[(kind, label)] = text
        return None

    def _durable_revision(self, kind: str, label: str) -> str | None:
        """The product digest of a station-day whose final differs from the one the persisted
        row was built from: a revision promoted while this process was down (or unseen)."""
        stored = self._store.read_settled_pnl_basis(label, kind)
        if stored is None:
            return None
        known = dict(item.split("=", 1) for item in stored.basis.split(";") if "=" in item)
        current = self._basis_now(label)
        for name in sorted(current):
            if name in known and known[name] != current[name].token:
                return current[name].product_sha256 or _NO_SHA
        return None

    def _shrank(self, prior: SettledPnlDay | None, record: SettledPnlDay, label: str) -> bool:
        if prior is None:
            return False
        return record.settled_entries < prior.settled_entries

    def _prior(self, kind: str, label: str) -> SettledPnlDay | None:
        if kind == "day":
            return self._store.read_settled_pnl_day(label)
        return self._store.read_floor_stub_pnl_day(label)

    def _write(self, kind: str, record: SettledPnlDay) -> None:
        if kind == "day":
            self._store.write_settled_pnl_day(record)
        else:
            self._store.write_floor_stub_pnl_day(record)

    def _accept_revision(
        self,
        kind: str,
        record: SettledPnlDay,
        label: str,
        suffix: str,
        guard: SettledPnlRegression,
    ) -> _Failure | None:
        """A guard failure: accept it only as a promoted CLI revision, under an audit row."""
        try:
            sha = self._revision_labels.get(label) or self._durable_revision(kind, label)
        except Exception as exc:  # noqa: BLE001 - an unreadable basis is a persist failure
            return _Failure(f"settled_pnl_persist_failed:{label}{suffix}", named=False, cause=exc)
        if sha is None:
            return _Failure(f"settled_pnl_regression:{label}{suffix}", named=True, cause=guard)
        if guard.kind != "pnl_rise":  # a revision changes P&L, never the entry count
            return _Failure(f"settled_truth_shrank:{label}{suffix}", named=True, cause=guard)
        try:
            prior = self._prior(kind, label)
            ts_ns = self._clock_ns()
            self._store.write_settled_pnl_revision(
                SettledPnlRevision(
                    day=label,
                    ts_ns=ts_ns,
                    scope=kind,
                    old_pnl=prior.pnl if prior is not None else "0",
                    new_pnl=record.pnl,
                    old_entries=prior.total_entries if prior is not None else 0,
                    new_entries=record.total_entries,
                    cause=_CAUSE_REVISION,
                    product_sha256=sha,
                )
            )
            if kind == "day":
                self._store.replace_settled_pnl_day_for_revision(record, ts_ns)
            else:
                self._store.replace_floor_stub_pnl_for_revision(record, ts_ns)
        except SettledPnlRegression as exc:  # the latch's own entry-shrink refusal
            return _Failure(f"settled_truth_shrank:{label}{suffix}", named=True, cause=exc)
        except Exception as exc:  # noqa: BLE001 - isolated like any other row failure
            return _Failure(f"settled_pnl_persist_failed:{label}{suffix}", named=False, cause=exc)
        return self._record_basis(kind, label, suffix)

    # -- alerts and the raise --------------------------------------------------------------

    def _raise_for(self, failures: list[_Failure], streak: Mapping[_TruthKey, int]) -> None:
        active = {f.reason for f in failures if f.named}
        for (station, day), count in streak.items():
            if count >= STREAK_ALERT_AT:
                active.add(f"truth_revalidation_failing:{station}:{day.isoformat()}")
        for reason in sorted(active - self._alerted):
            self._send(reason)
        self._alerted = active  # a reason that cleared re-arms its alert
        if failures:
            cause = next((f.cause for f in failures if f.cause is not None), None)
            error_type = (
                SettledPnlFail if any(f.named for f in failures) else SettledPnlPersistError
            )
            raise error_type(tuple(f.reason for f in failures)) from cause

    def _send(self, reason: str) -> None:
        try:
            self._alert(reason)
        except Exception as exc:  # noqa: BLE001 - an alert fault must not hide the FAIL itself
            _LOG.error("settled-P&L alert not delivered (%s)", type(exc).__name__)
