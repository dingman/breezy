"""EXEC-PAR WP5b: the breaker watcher Actor and its alert / digest telemetry.

Never imports the ``exec`` package (barrier X1 pins its importers by set
equality): the exec client is a local double exposing exactly the properties
the real client exposes (``contradiction_events_total``,
``ambiguous_notional_breaker_tripped``, ``resolver_last_pass_ns``,
``open_intent_ages``, ``held_position_slugs``, ``unreadable_slot_keys``,
``k_forced_to_1_reason``, ``stuck_refusals_after_settle_failure_total``,
``duplicate_suspect_total``) plus the coordinator-added
``no_fill_retire_refusals_total``.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime import breaker_watcher
from breezy.runtime.breaker_watcher import (
    NO_CLIENT_ERROR_TICKS,
    REALERT_INTERVAL_NS,
    STUCK_AGE_NS,
    WATCHER_INTERVAL_SECONDS,
    BreakerWatcherActor,
    ExecClientView,
    ExecRefusalAlertActor,
    build_exec_watcher,
)
from breezy.runtime.exec_par_telemetry import ExecParDigest
from breezy.runtime.health import AlertPayload
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    RetirementReason,
    SubmitIntentLatch,
    open_submit_intent_latch,
)

SEC = 1_000_000_000
NOW = 1_700_000_000 * SEC


class _MemStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.sets: list[str] = []

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.sets.append(key)
        self.data[key] = value


class _Sink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)

    def events(self, name: str) -> list[AlertPayload]:
        return [p for p in self.emitted if p.event == name]


@dataclass
class _Client:
    """A double exposing the exec client's watcher-facing properties."""

    contradiction_events_total: int = 0
    duplicate_suspect_total: int = 0
    ambiguous_notional_breaker_tripped: bool = False
    pass_ns: int = NOW
    ages: tuple[tuple[str, str, int], ...] = ()
    held_position_slugs: tuple[str, ...] = ()
    unreadable_slot_keys: tuple[str, ...] = ()
    k_forced_to_1_reason: str | None = None
    stuck_refusals_after_settle_failure_total: int = 0
    no_fill_retire_refusals_total: int = 0
    ages_raise: bool = False
    read_loops: list[asyncio.AbstractEventLoop] = field(default_factory=list)

    @property
    def open_intent_ages(self) -> tuple[tuple[str, str, int], ...]:
        if self.ages_raise:
            raise RuntimeError("evaluation blew up")
        return self.ages

    @property
    def resolver_last_pass_ns(self) -> int:
        self.read_loops.append(asyncio.get_running_loop())
        return self.pass_ns


class _RecordingLatch:
    def __init__(self, *, fail_halt: bool = False) -> None:
        self.heartbeats: list[tuple[int, int]] = []
        self.halts: list[tuple[str, int]] = []
        self.fail_halt = fail_halt

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        self.heartbeats.append((hb_ns, resolver_pass_ns))

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        if self.fail_halt:
            raise OSError("store down")
        self.halts.append((reason, ts_ns))


def _register(actor: Actor, clock: TestClock) -> None:
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )


def _watcher(
    client: _Client,
    latch: _RecordingLatch | None = None,
    sink: _Sink | None = None,
    *,
    clock: TestClock | None = None,
    digest: ExecParDigest | None = None,
) -> tuple[BreakerWatcherActor, _RecordingLatch, _Sink, TestClock]:
    the_latch = latch if latch is not None else _RecordingLatch()
    the_sink = sink if sink is not None else _Sink()
    the_clock = clock if clock is not None else TestClock()
    the_clock.set_time(NOW)
    actor = BreakerWatcherActor(latch=the_latch, alert_sink=the_sink, digest=digest)
    _register(actor, the_clock)
    actor.bind_client(lambda: client)
    return actor, the_latch, the_sink, the_clock


# ---------------------------------------------------------------------------
# Registration: K=1 has no breaker writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_not_registered_at_k1_and_no_breaker_writes() -> None:
    latch = _RecordingLatch()
    sink = _Sink()
    at_k1 = build_exec_watcher(1, latch=latch, alert_sink=sink)
    at_k2 = build_exec_watcher(2, latch=latch, alert_sink=sink)
    assert not isinstance(at_k1, BreakerWatcherActor)
    assert isinstance(at_k1, ExecRefusalAlertActor)
    assert isinstance(at_k2, BreakerWatcherActor)

    _register(at_k1, TestClock())
    client = _Client(
        contradiction_events_total=3,
        ambiguous_notional_breaker_tripped=True,
        ages=(("a", "S-A", 9_999 * SEC), ("b", "S-B", 9_999 * SEC)),
    )
    at_k1.bind_client(lambda: client)
    assert await at_k1.tick() is True
    assert latch.heartbeats == []
    assert latch.halts == []


async def _drive_timer_scenario() -> tuple[_Client, _RecordingLatch, asyncio.AbstractEventLoop]:
    client = _Client()
    actor, latch, _, clock = _watcher(client)
    actor.on_start()
    assert actor.timer_armed
    for event in clock.advance_time(NOW + 5 * SEC):
        event.handle()
    for _ in range(300):
        if actor.inflight == 0 and len(latch.heartbeats) >= 2:
            break
        await asyncio.sleep(0.01)
    actor.on_stop()
    return client, latch, asyncio.get_running_loop()


def test_watcher_is_an_actor_timer_task_on_the_node_loop() -> None:
    assert issubclass(BreakerWatcherActor, Actor)
    assert WATCHER_INTERVAL_SECONDS == 5
    client, latch, loop = asyncio.run(_drive_timer_scenario())
    assert client.read_loops, "the evaluation never ran"
    assert all(seen is loop for seen in client.read_loops)
    assert len(latch.heartbeats) >= 2


def test_watcher_latency_at_most_one_poll() -> None:
    _, latch, _ = asyncio.run(_drive_timer_scenario())
    # on_start evaluates once at once; one 5 s timer fire adds exactly one more
    assert len(latch.heartbeats) == 2
    actor = BreakerWatcherActor(latch=_RecordingLatch(), alert_sink=_Sink())
    assert actor.interval_seconds <= 5


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_trips_at_two_stuck() -> None:
    stuck = STUCK_AGE_NS + SEC
    one = _Client(ages=(("a", "S-A", stuck), ("b", "S-B", STUCK_AGE_NS - SEC)))
    actor, latch, sink, _ = _watcher(one)
    assert await actor.tick() is True
    assert latch.halts == []

    two = _Client(ages=(("a", "S-A", stuck), ("b", "S-B", stuck)))
    actor2, latch2, sink2, _ = _watcher(two)
    assert await actor2.tick() is True
    assert [reason for reason, _ in latch2.halts] == ["stuck_slots"]
    assert sink2.events("EXEC_PAR_BREAKER_TRIPPED")
    assert sink.events("EXEC_PAR_BREAKER_TRIPPED") == []


@pytest.mark.asyncio
async def test_breaker_notional_trigger_via_ledger_fires_below_f_adm() -> None:
    client = _Client(ambiguous_notional_breaker_tripped=True)
    actor, latch, _, _ = _watcher(client)
    await actor.tick()
    assert [reason for reason, _ in latch.halts] == ["ambiguous_notional"]


@pytest.mark.asyncio
async def test_contradiction_latches_halt_sticky_until_operator_reset(tmp_path: Path) -> None:
    store = _MemStore()
    clock = TestClock()
    clock.set_time(NOW)
    with open_submit_intent_latch(
        store,
        tmp_path / "s.db",
        max_slots=2,
        v2_predicate=lambda: True,
        clock_ns=clock.timestamp_ns,
    ) as latch:
        client = _Client()
        sink = _Sink()
        actor = BreakerWatcherActor(latch=latch, alert_sink=sink)
        _register(actor, clock)
        actor.bind_client(lambda: client)
        await actor.tick()
        assert latch.admission_refusal("S-A", False) is None

        client.contradiction_events_total = 1  # observed ...
        await actor.tick()
        assert latch.admission_refusal("S-A", False) == "breaker_halted"
        client.contradiction_events_total = 1  # ... and then retired: counter is monotonic
        await actor.tick()
        assert latch.admission_refusal("S-A", False) == "breaker_halted"
        record = latch.read_breaker_record()
        assert record is not None and record.halted_reason == "contradiction"
        # only the operator reset (node down) clears it
        assert latch.reset_breaker_halt() is True
        assert latch.admission_refusal("S-A", False) is None


@pytest.mark.asyncio
async def test_duplicate_suspect_trips() -> None:
    client = _Client(duplicate_suspect_total=1)
    actor, latch, _, _ = _watcher(client)
    await actor.tick()
    assert [reason for reason, _ in latch.halts] == ["duplicate_suspect"]


@pytest.mark.asyncio
async def test_halt_write_failure_withholds_the_heartbeat_and_retries_next_tick() -> None:
    client = _Client(contradiction_events_total=1)
    latch = _RecordingLatch(fail_halt=True)
    actor, _, _, _ = _watcher(client, latch)
    assert await actor.tick() is False
    assert latch.heartbeats == []
    latch.fail_halt = False
    assert await actor.tick() is True  # the unrecorded event is still pending
    assert [reason for reason, _ in latch.halts] == ["contradiction"]


# ---------------------------------------------------------------------------
# Heartbeat discipline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_not_written_when_poll_evaluation_raises() -> None:
    client = _Client(ages_raise=True)
    actor, latch, _, _ = _watcher(client)
    assert await actor.tick() is False
    assert latch.heartbeats == []
    ok = _Client(pass_ns=NOW - 7 * SEC)
    actor_ok, latch_ok, _, _ = _watcher(ok)
    assert await actor_ok.tick() is True
    assert latch_ok.heartbeats == [(NOW, NOW - 7 * SEC)]


@pytest.mark.asyncio
async def test_unbound_client_writes_no_heartbeat() -> None:
    latch = _RecordingLatch()
    actor = BreakerWatcherActor(latch=latch, alert_sink=_Sink())
    _register(actor, TestClock())
    assert await actor.tick() is False
    assert latch.heartbeats == []


def test_heartbeat_write_does_not_block_arm_slot(tmp_path: Path) -> None:
    store = _MemStore()
    clock_value = [NOW]
    with open_submit_intent_latch(
        store,
        tmp_path / "s.db",
        max_slots=2,
        v2_predicate=lambda: True,
        clock_ns=lambda: clock_value[0],
    ) as latch:
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW)
        stop = threading.Event()

        def beat() -> None:
            while not stop.is_set():
                latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW)

        thread = threading.Thread(target=beat)
        thread.start()
        try:
            started = time.monotonic()
            intent = latch.arm_slot("ab" * 32, slug="S-A", is_exit=False, now_ns=NOW)
            elapsed = time.monotonic() - started
        finally:
            stop.set()
            thread.join()
        assert intent.slug == "S-A"
        assert elapsed < 1.0
        assert BREAKER_KEY in store.sets


# ---------------------------------------------------------------------------
# Dead watcher / dead resolver (latch side of the admission gate)
# ---------------------------------------------------------------------------


@contextmanager
def _latch(store: _MemStore, tmp_path: Path, now: list[int]) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(
        store, tmp_path / "s.db", max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: now[0]
    ) as latch:
        yield latch


def test_dead_watcher_denies_entries_while_exits_stay_allowed(tmp_path: Path) -> None:
    now = [NOW]
    with _latch(_MemStore(), tmp_path, now) as latch:
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW)
        now[0] = NOW + 61 * SEC
        assert latch.admission_refusal("S-A", False) == "breaker_heartbeat_stale"
        assert latch.admission_refusal("S-A", True) is None


def test_dead_resolver_task_denies_entries_via_resolver_pass_age(tmp_path: Path) -> None:
    now = [NOW]
    with _latch(_MemStore(), tmp_path, now) as latch:
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW - 601 * SEC)
        assert latch.admission_refusal("S-A", False) == "breaker_resolver_stale"


def test_backoff_cap_resolver_pass_age_does_not_false_trip(tmp_path: Path) -> None:
    now = [NOW]
    with _latch(_MemStore(), tmp_path, now) as latch:
        # a venue-wide 5xx backoff sits at the 300 s cap: the loop is alive
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW - 300 * SEC)
        assert latch.admission_refusal("S-A", False) is None


def test_halt_allows_exits_and_resolver_still_retires(tmp_path: Path) -> None:
    now = [NOW]
    with _latch(_MemStore(), tmp_path, now) as latch:
        latch.write_breaker_heartbeat(hb_ns=NOW, resolver_pass_ns=NOW)
        latch.write_breaker_halt("stuck_slots", ts_ns=NOW)
        assert latch.admission_refusal("S-A", False) == "breaker_halted"
        assert latch.admission_refusal("S-A", True) is None
        intent = latch.arm_slot("cd" * 32, slug="S-X", is_exit=True, now_ns=NOW)
        retired = latch.retire(
            intent.intent_id, RetirementReason.RESOLVER_NO_ID_NO_FILL, now_ns=NOW
        )
        assert retired.retirement_reason is RetirementReason.RESOLVER_NO_ID_NO_FILL


def test_breaker_does_not_use_family_halt_or_veto_signature() -> None:
    source = inspect.getsource(breaker_watcher)
    for banned in ("family_halt", "submit_veto", "set_family_halted", "record_policy_halt"):
        assert banned not in source
    assert "operator_controls" not in source


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_unreadable_slot_alerts_once() -> None:
    client = _Client(unreadable_slot_keys=("slot-x",))
    actor, _, sink, _ = _watcher(client)
    await actor.tick()
    await actor.tick()
    assert len(sink.events("EXEC_PAR_UNREADABLE_SLOT")) == 1
    client.unreadable_slot_keys = ("slot-x", "slot-y")
    await actor.tick()
    assert len(sink.events("EXEC_PAR_UNREADABLE_SLOT")) == 2


@pytest.mark.asyncio
async def test_trip_alert_names_the_held_positions_once() -> None:
    client = _Client(contradiction_events_total=1, held_position_slugs=("S-H1", "S-H2"))
    actor, _, sink, _ = _watcher(client)
    await actor.tick()
    await actor.tick()
    (alert,) = sink.events("EXEC_PAR_BREAKER_TRIPPED")
    assert alert.severity == "CRITICAL"
    assert "S-H1" in alert.detail and "S-H2" in alert.detail


@pytest.mark.asyncio
async def test_stuck_slot_on_a_held_slug_alerts_once_per_intent() -> None:
    stuck = STUCK_AGE_NS + SEC
    client = _Client(
        ages=(("a", "S-HELD", stuck), ("b", "S-FLAT", 1 * SEC)),
        held_position_slugs=("S-HELD",),
    )
    actor, _, sink, _ = _watcher(client)
    await actor.tick()
    await actor.tick()
    (alert,) = sink.events("EXEC_PAR_STUCK_SLOT_ON_HELD_SLUG")
    assert "S-HELD" in alert.detail


@pytest.mark.asyncio
async def test_k_forced_to_1_alerts_once_per_reason() -> None:
    client = _Client(k_forced_to_1_reason="the live cap/budget bucket is above the frozen bucket")
    actor, _, sink, _ = _watcher(client)
    await actor.tick()
    await actor.tick()
    assert len(sink.events("EXEC_PAR_K_FORCED_TO_1")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("max_slots", [1, 2])
async def test_refusal_counters_alert_on_value_change_at_every_k(max_slots: int) -> None:
    sink = _Sink()
    latch = _RecordingLatch()
    actor = build_exec_watcher(max_slots, latch=latch, alert_sink=sink)
    _register(actor, TestClock())
    client = _Client()
    actor.bind_client(lambda: client)

    await actor.tick()
    assert sink.events("EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE") == []
    assert sink.events("EXEC_PAR_NO_FILL_RETIRE_REFUSAL") == []

    client.stuck_refusals_after_settle_failure_total = 1
    client.no_fill_retire_refusals_total = 2
    await actor.tick()
    await actor.tick()  # unchanged: deduped
    assert len(sink.events("EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE")) == 1
    assert len(sink.events("EXEC_PAR_NO_FILL_RETIRE_REFUSAL")) == 1

    client.stuck_refusals_after_settle_failure_total = 2
    await actor.tick()
    assert len(sink.events("EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE")) == 2
    assert len(sink.events("EXEC_PAR_NO_FILL_RETIRE_REFUSAL")) == 1


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def test_digest_reports_cross_day_settles_and_denial_reasons() -> None:
    digest = ExecParDigest(station_of=lambda slug: slug.split("-")[0])
    digest.record_denial("open_intent_wait")
    digest.record_denial("open_intent_wait")
    digest.record_denial("breaker_halted")
    digest.record_submitted("NYC-1", Decimal("0.40"), NOW)
    digest.record_submitted("NYC-2", Decimal("0.35"), NOW + SEC)
    digest.set_cross_day_settles_total(3)
    snap = digest.snapshot(NOW + 2 * SEC)
    assert snap.cross_day_settles_total == 3
    assert snap.heartbeat_stale_denials == 0
    shares = dict(snap.dropped_share_by_reason)
    assert shares["open_intent_wait"] == "0.4000"  # 2 of (3 denied + 2 submitted)
    assert shares["breaker_halted"] == "0.2000"
    assert dict(snap.exposure_by_station_day)[f"NYC@{NOW // (86_400 * SEC)}"] == "0.75"
    next_window = digest.snapshot(NOW + 5 * SEC + 1)
    assert next_window.window_orders == 2
    assert next_window.peak_window_orders == 2
    line = next_window.render()
    assert "event=exec_par_digest" in line and "cross_day_settles_total=3" in line


@pytest.mark.asyncio
async def test_watcher_counts_entries_denied_during_a_heartbeat_gap() -> None:
    digest = ExecParDigest()
    client = _Client()
    actor, _, _, clock = _watcher(client, digest=digest)
    await actor.tick()
    digest.record_denial("open_intent_wait")  # a denial lands while the loop is wedged
    clock.set_time(NOW + 61 * SEC)  # the gap since the last heartbeat exceeded 60 s
    await actor.tick()
    assert digest.snapshot(NOW + 62 * SEC).heartbeat_stale_denials == 1


# ---------------------------------------------------------------------------
# R1: the counters are read through a typed view, checked against the REAL class
# ---------------------------------------------------------------------------

_CLIENT_SOURCE = Path(__file__).resolve().parents[2] / (
    "src/breezy/adapters/polymarket_us/exec/client.py"
)


def test_real_exec_client_exposes_every_watcher_view_property() -> None:
    """AST of the real class (importing ``exec`` is barred by barrier X1)."""
    tree = ast.parse(_CLIENT_SOURCE.read_text(encoding="utf-8"))
    (cls,) = [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "PolymarketUSExecutionClient"
    ]
    properties = {
        fn.name
        for fn in cls.body
        if isinstance(fn, ast.FunctionDef)
        and any(isinstance(d, ast.Name) and d.id == "property" for d in fn.decorator_list)
    }
    view = set(ExecClientView.__protocol_attrs__)  # type: ignore[attr-defined]
    assert {
        "no_fill_retire_refusals_total",
        "stuck_refusals_after_settle_failure_total",
    } <= view
    assert view <= properties, sorted(view - properties)


# ---------------------------------------------------------------------------
# R2: delivery that can be lost is retried and periodically repeated
# ---------------------------------------------------------------------------


class _FlakySink(_Sink):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.attempts = 0

    def emit(self, payload: AlertPayload) -> None:
        self.attempts += 1
        if self.failures > 0:
            self.failures -= 1
            raise OSError("sink down")
        super().emit(payload)


@pytest.mark.asyncio
async def test_a_failed_alert_send_is_not_marked_sent_and_is_retried_next_tick() -> None:
    sink = _FlakySink(failures=1)
    client = _Client(stuck_refusals_after_settle_failure_total=1)
    actor, _, _, _ = _watcher(client, sink=sink)
    assert await actor.tick() is True  # a lost alert never withholds the heartbeat
    assert sink.emitted == []
    await actor.tick()
    assert len(sink.events("EXEC_PAR_STUCK_REFUSAL_AFTER_SETTLE_FAILURE")) == 1
    await actor.tick()
    assert len(sink.emitted) == 1  # now deduped


@pytest.mark.asyncio
async def test_every_alert_kind_is_realerted_hourly_while_its_condition_holds() -> None:
    stuck = STUCK_AGE_NS + SEC
    client = _Client(
        stuck_refusals_after_settle_failure_total=1,
        no_fill_retire_refusals_total=1,
        k_forced_to_1_reason="bucket",
        unreadable_slot_keys=("slot-x",),
        contradiction_events_total=1,
        ages=(("a", "S-H", stuck),),
        held_position_slugs=("S-H",),
    )
    actor, _, sink, clock = _watcher(client)
    await actor.tick()
    first = len(sink.emitted)
    assert first == 6
    clock.set_time(NOW + REALERT_INTERVAL_NS - SEC)
    await actor.tick()
    assert len(sink.emitted) == first  # inside the hour: deduped
    clock.set_time(NOW + REALERT_INTERVAL_NS)
    await actor.tick()
    assert len(sink.emitted) == 2 * first  # the hour is up: every condition again


@pytest.mark.asyncio
async def test_an_ended_episode_alerts_afresh_when_it_returns() -> None:
    client = _Client(k_forced_to_1_reason="bucket")
    actor, _, sink, _ = _watcher(client)
    await actor.tick()
    client.k_forced_to_1_reason = None
    await actor.tick()
    client.k_forced_to_1_reason = "bucket"
    await actor.tick()
    assert len(sink.events("EXEC_PAR_K_FORCED_TO_1")) == 2


# ---------------------------------------------------------------------------
# R3: the halt is persisted before anything that can fail
# ---------------------------------------------------------------------------


class _HeldRaises(_Client):
    @property
    def held_position_slugs(self) -> tuple[str, ...]:
        raise RuntimeError("positions evidence blew up")

    @held_position_slugs.setter
    def held_position_slugs(self, value: tuple[str, ...]) -> None:
        pass


@pytest.mark.asyncio
async def test_held_position_slugs_raising_still_writes_the_halt_and_alerts_unknown() -> None:
    client = _HeldRaises(contradiction_events_total=1)
    actor, latch, sink, _ = _watcher(client)
    assert await actor.tick() is True
    assert [reason for reason, _ in latch.halts] == ["contradiction"]
    (alert,) = sink.events("EXEC_PAR_BREAKER_TRIPPED")
    assert "held_positions=unknown" in alert.detail


@pytest.mark.asyncio
async def test_the_halt_is_written_before_any_alert_is_sent() -> None:
    order: list[str] = []

    class _OrderLatch(_RecordingLatch):
        def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
            order.append("halt")
            super().write_breaker_halt(reason, ts_ns=ts_ns)

    class _OrderSink(_Sink):
        def emit(self, payload: AlertPayload) -> None:
            order.append(payload.event)
            super().emit(payload)

    client = _Client(contradiction_events_total=1, k_forced_to_1_reason="bucket")
    actor, _, _, _ = _watcher(client, _OrderLatch(), _OrderSink())
    await actor.tick()
    assert order[0] == "halt" and len(order) > 1


@pytest.mark.asyncio
async def test_a_raising_alert_sink_never_withholds_the_heartbeat_or_the_halt() -> None:
    class _Dead(_Sink):
        def emit(self, payload: AlertPayload) -> None:
            raise OSError("down")

    client = _Client(contradiction_events_total=1, unreadable_slot_keys=("k",))
    actor, latch, _, _ = _watcher(client, sink=_Dead())
    assert await actor.tick() is True
    assert latch.halts and latch.heartbeats


@pytest.mark.asyncio
async def test_a_raising_client_getter_or_clock_is_contained_by_tick() -> None:
    actor = BreakerWatcherActor(latch=_RecordingLatch(), alert_sink=_Sink())
    _register(actor, TestClock())

    def boom() -> ExecClientView | None:
        raise RuntimeError("engine registry blew up")

    actor.bind_client(boom)
    assert await actor.tick() is False


# ---------------------------------------------------------------------------
# R4: a getter that keeps returning None is loud
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_client_getter_returning_none_logs_error_after_five_ticks_then_hourly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = TestClock()
    clock.set_time(NOW)
    actor = BreakerWatcherActor(latch=_RecordingLatch(), alert_sink=_Sink())
    _register(actor, clock)
    actor.bind_client(lambda: None)

    def errors() -> int:
        return len([r for r in caplog.records if r.levelno == logging.ERROR])

    with caplog.at_level(logging.ERROR, logger="breezy.runtime.breaker_watcher"):
        for _ in range(NO_CLIENT_ERROR_TICKS - 1):
            await actor.tick()
        assert errors() == 0
        await actor.tick()
        assert errors() == 1
        await actor.tick()
        assert errors() == 1  # not every tick
        clock.set_time(NOW + REALERT_INTERVAL_NS)
        await actor.tick()
        assert errors() == 2  # hourly after that
