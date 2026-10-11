"""EXEC-PAR BG-1b: AMBIGUOUS ingestion from the ledger's ever-ambiguous marks.

The mark set is acknowledged only after the durable ``ambiguous/<intent_id>`` row
is written, so a with-id entry that resolves between two 5 s ticks is still counted.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.operator_controls import DailySpendLedger
from breezy.runtime.breaker_watcher import BreakerWatcherActor
from breezy.runtime.exec_par_counter_ingest import (
    CounterAttributionError,
    CounterWriteError,
    ExecParCounterIngest,
)
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentLatch,
    open_submit_intent_latch,
)

SEC = 1_000_000_000
ARM = 1_700_000_000 * SEC + 123
DAY = "2026-10-11"
FP = "a" * 64
SLUG = "aec-nyc-high-2026-10-11-t70"
UNATTRIBUTED = "unattributed"


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_set = False

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        if self.fail_set:
            raise OSError("down")
        self.data[key] = value


@contextmanager
def _latch(tmp_path: Path, store: _Store) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(
        store, tmp_path / "s.db", max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: ARM
    ) as latch:
        yield latch


def _ingest(latch: SubmitIntentLatch) -> ExecParCounterIngest:
    return ExecParCounterIngest(
        store=latch,
        climate_day_of=lambda slug, ns: DAY,
        theta_of=lambda ts: Decimal("0.0695"),
    )


def _ambiguous(ledger: DailySpendLedger, intent_id: str) -> None:
    ledger.register_open_exposure(
        intent_id,
        Decimal("4.00"),
        booking=None,
        seeded_partial_usd=Decimal(0),
        side="BUY",
        now_ns=ARM,
    )
    ledger.mark_ambiguous(intent_id)


class _FixedMarks:
    """A mark source with caller-chosen sources (the ledger itself only says 'unknown')."""

    def __init__(self, marks: Iterable[tuple[str, str]]) -> None:
        self.marks = set(marks)
        self.acked: list[tuple[str, str]] = []

    def ambiguous_marks_pending(self) -> frozenset[tuple[str, str]]:
        return frozenset(self.marks)

    def ack_ambiguous_marks(self, marks: Iterable[tuple[str, str]]) -> None:
        for mark in marks:
            self.acked.append(mark)
            self.marks.discard(mark)


# -- the latch intent reader ------------------------------------------------


def test_read_intent_finds_open_slots_then_history_then_none(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        assert latch.read_intent(slot.intent_id) == slot
        latch.retire(slot.intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=ARM + SEC)
        retired = latch.read_intent(slot.intent_id)
        assert retired is not None and retired.created_ns == ARM
        assert latch.read_intent("0" * 32) is None
        with pytest.raises(ValueError):
            latch.read_intent("not-hex")


# -- attribution -------------------------------------------------------------


def test_with_id_ambiguous_attributed_from_the_open_slot(tmp_path: Path) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        ledger = DailySpendLedger()
        _ambiguous(ledger, slot.intent_id)
        assert _ingest(latch).ingest_ambiguous_marks(ledger, now_ns=ARM + 5 * SEC) == 1
        (row,) = latch.read_ambiguous(DAY)
        assert (row.intent_id, row.arm_ns, row.attribution) == (slot.intent_id, ARM, "slot")
        assert ledger.ambiguous_marks_pending() == frozenset()  # acknowledged


def test_resolved_inside_one_tick_is_still_counted_from_history(tmp_path: Path) -> None:
    """The finding-4 case: abandoned and retired before the watcher ever looked."""
    with _latch(tmp_path, _Store()) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        ledger = DailySpendLedger()
        _ambiguous(ledger, slot.intent_id)
        ledger.abandon_open_exposure(slot.intent_id)
        latch.retire(
            slot.intent_id, RetirementReason.STATUS_REPORT_ACCEPT_FILL_TERMINAL, now_ns=ARM + SEC
        )
        assert _ingest(latch).ingest_ambiguous_marks(ledger, now_ns=ARM + 5 * SEC) == 1
        (row,) = latch.read_ambiguous(DAY)
        assert (row.arm_ns, row.attribution) == (ARM, "history")


def test_no_id_ambiguous_counts_like_any_other_slot(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        marks = _FixedMarks({(slot.intent_id, "unknown")})
        assert _ingest(latch).ingest_ambiguous_marks(marks, now_ns=ARM + SEC) == 1
        assert [r.intent_id for r in latch.read_ambiguous(DAY)] == [slot.intent_id]


def test_no_slot_and_no_history_is_counted_as_unattributed_never_dropped(
    tmp_path: Path,
) -> None:
    with _latch(tmp_path, _Store()) as latch:
        marks = _FixedMarks({("b" * 32, "unknown")})
        now = ARM + 9 * SEC
        assert _ingest(latch).ingest_ambiguous_marks(marks, now_ns=now) == 1
        (row,) = latch.read_ambiguous(UNATTRIBUTED)
        assert (row.attribution, row.day, row.arm_ns) == (UNATTRIBUTED, UNATTRIBUTED, now)
        assert marks.marks == set()


def test_boot_source_is_stored_verbatim(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        _ingest(latch).ingest_ambiguous_marks(
            _FixedMarks({(slot.intent_id, "boot")}), now_ns=ARM + SEC
        )
        (row,) = latch.read_ambiguous(DAY)
        assert row.source == "boot"


# -- idempotence, restart, acknowledge ------------------------------------


def test_idempotent_across_ticks_and_the_set_shrinks_after_acknowledge(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        ledger = DailySpendLedger()
        ingest = _ingest(latch)
        _ambiguous(ledger, slot.intent_id)
        assert ingest.ingest_ambiguous_marks(ledger, now_ns=ARM + SEC) == 1
        assert ingest.ingest_ambiguous_marks(ledger, now_ns=ARM + 2 * SEC) == 0  # nothing pending
        ledger.mark_ambiguous(slot.intent_id)  # a repeat mark of a counted entry
        assert ingest.ingest_ambiguous_marks(ledger, now_ns=ARM + 3 * SEC) == 0  # not twice
        assert len(latch.read_ambiguous(DAY)) == 1
        assert ledger.ambiguous_marks_pending() == frozenset()


def test_restart_re_mark_of_an_already_counted_intent_is_not_counted_twice(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        first = DailySpendLedger()
        _ambiguous(first, slot.intent_id)
        _ingest(latch).ingest_ambiguous_marks(first, now_ns=ARM + SEC)
    with _latch(tmp_path, store) as latch:  # new process: the slot persists, H6 re-marks it
        reboot = DailySpendLedger()
        _ambiguous(reboot, slot.intent_id)
        assert _ingest(latch).ingest_ambiguous_marks(reboot, now_ns=ARM + 600 * SEC) == 0
        (row,) = latch.read_ambiguous(DAY)
        assert (row.arm_ns, row.attribution) == (ARM, "slot")
        assert reboot.ambiguous_marks_pending() == frozenset()


def test_restart_attributes_a_never_counted_boot_mark_from_the_persisted_slot(
    tmp_path: Path,
) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
    with _latch(tmp_path, store) as latch:
        marks = _FixedMarks({(slot.intent_id, "boot")})
        assert _ingest(latch).ingest_ambiguous_marks(marks, now_ns=ARM + 900 * SEC) == 1
        (row,) = latch.read_ambiguous(DAY)
        assert (row.arm_ns, row.source) == (ARM, "boot")


def test_write_failure_does_not_acknowledge_and_the_next_tick_retries(tmp_path: Path) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        ledger = DailySpendLedger()
        _ambiguous(ledger, slot.intent_id)
        ingest = _ingest(latch)
        store.fail_set = True
        with pytest.raises(CounterWriteError):
            ingest.ingest_ambiguous_marks(ledger, now_ns=ARM + SEC)
        assert ledger.ambiguous_marks_pending() == frozenset({(slot.intent_id, "unknown")})
        assert latch.read_ambiguous(DAY) == ()
        store.fail_set = False
        assert ingest.ingest_ambiguous_marks(ledger, now_ns=ARM + 6 * SEC) == 1
        assert ledger.ambiguous_marks_pending() == frozenset()


def test_one_failing_mark_does_not_lose_the_ones_already_written(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        good = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        no_slug = latch.arm_slot("b" * 64, slug="other-slug", is_exit=False, now_ns=ARM)
        failing = ExecParCounterIngest(
            store=latch,
            climate_day_of=lambda slug, ns: (
                (_ for _ in ()).throw(KeyError(slug)) if slug == "other-slug" else DAY
            ),
            theta_of=lambda ts: Decimal("0.0695"),
        )
        marks = _FixedMarks({(good.intent_id, "unknown"), (no_slug.intent_id, "unknown")})
        with pytest.raises(CounterAttributionError):
            failing.ingest_ambiguous_marks(marks, now_ns=ARM + SEC)
        assert [r.intent_id for r in latch.read_ambiguous(DAY)] == [good.intent_id]
        assert marks.marks == {(no_slug.intent_id, "unknown")}  # retried, never lost


# -- the watcher ---------------------------------------------------------------


class _Sink:
    def emit(self, payload: object) -> None:  # pragma: no cover
        raise AssertionError("no alert expected")


class _HbLatch:
    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...


class _Client:
    contradiction_events_total = 0
    duplicate_suspect_total = 0
    ambiguous_notional_breaker_tripped = False
    resolver_last_pass_ns = 0
    open_intent_ages: tuple[tuple[str, str, int], ...] = ()
    held_position_slugs: tuple[str, ...] = ()
    unreadable_slot_keys: tuple[str, ...] = ()
    k_forced_to_1_reason = None
    stuck_refusals_after_settle_failure_total = 0
    no_fill_retire_refusals_total = 0


def _watcher(ingest: ExecParCounterIngest, marks: DailySpendLedger) -> BreakerWatcherActor:
    clock = TestClock()
    clock.set_time(ARM + 5 * SEC)
    actor = BreakerWatcherActor(
        latch=_HbLatch(), alert_sink=_Sink(), counters=ingest, ambiguous_marks=marks
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.bind_client(lambda: _Client())
    return actor


@pytest.mark.asyncio
async def test_watcher_tick_ingests_marks_and_surfaces_failures_as_faults(tmp_path: Path) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        slot = latch.arm_slot(FP, slug=SLUG, is_exit=False, now_ns=ARM)
        ledger = DailySpendLedger()
        _ambiguous(ledger, slot.intent_id)
        ledger.abandon_open_exposure(slot.intent_id)  # resolved before the first tick
        actor = _watcher(_ingest(latch), ledger)
        store.fail_set = True
        assert await actor.tick() is True  # a counter fault never withholds the heartbeat (BG-6)
        assert actor.ingest_fault_count == 1
        assert isinstance(actor.last_ingest_fault, CounterWriteError)
        assert ledger.ambiguous_marks_pending() != frozenset()
        store.fail_set = False
        assert await actor.tick() is True
        assert actor.ingest_fault_count == 1
        assert [r.intent_id for r in latch.read_ambiguous(DAY)] == [slot.intent_id]
        assert ledger.ambiguous_marks_pending() == frozenset()


@pytest.mark.asyncio
async def test_watcher_without_a_mark_source_ingests_nothing(tmp_path: Path) -> None:
    with _latch(tmp_path, _Store()) as latch:
        actor = BreakerWatcherActor(latch=_HbLatch(), alert_sink=_Sink(), counters=_ingest(latch))
        clock = TestClock()
        actor.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=TestComponentStubs.msgbus(),
            cache=TestComponentStubs.cache(),
            clock=clock,
        )
        actor.bind_client(lambda: _Client())
        assert await actor.tick() is True
        assert actor.ingest_fault_count == 0


# -- the resolution-floor constants the design leans on ------------------------


def test_the_no_id_floor_and_poll_interval_are_pinned_to_the_client_constants() -> None:
    """Reads the pinned client's source text (no import) so a change to the floors surfaces."""
    text = Path("src/breezy/adapters/polymarket_us/exec/client.py").read_text(encoding="utf-8")
    assert "_RESOLVER_POLL_INTERVAL_SECS: Final[float] = 5.0" in text
    assert "_RESOLVER_ZERO_FILL_MIN_AGE_NS: Final[int] = 120 * 1_000_000_000" in text
    assert "_RESOLVER_NO_ID_MIN_AGE_NS: Final[int] = 300 * 1_000_000_000" in text
    # the accept-fill leg has no age gate: a with-id entry can resolve within one watcher tick,
    # which is why the ledger keeps an ever-ambiguous set instead of being polled for state.
