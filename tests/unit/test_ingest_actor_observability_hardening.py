"""Hardening regressions for `NwsIngestActor`'s observability path.

Four defects, all of the same shape: an observability mechanism that fails
QUIETLY and therefore reports a healthy site while the thing it exists to
detect is broken.

1. **Alert state raced across worker threads.** `AlertState` is documented
   (`runtime/health.py`) as "deliberately not thread-safe ... exactly one
   poll loop is expected to own an instance", and `evaluate` is a
   read-modify-write over `self._active`. `on_poll_timer` submits a poll on
   EVERY fire with no exclusion, so an overrunning cycle N overlaps cycle
   N+1 and two dispatches interleave across the executor. The transitions
   lost are exactly the persistent-silent ones (`UA_TRAP_LATCHED`,
   `SITE_BLOCKED`) -- lost until the 24h re-notify.
2. **A swallowed `gaps.reconcile` failure reported a clean site forever.**
   The `except Exception: logger.exception(...)` branch left `entries=()`,
   so the snapshot published `open_gaps: []` and no condition fired: a
   `TamperedGapLedgerError` raised every cycle while the dashboard stayed
   green and revision detection -- the only defence against a superseded
   final -- was dead and invisible.
3. **The poll stagger delayed the settlement-deadline timer.**
   `check_final_deadline` performs no network I/O, so it gains nothing from
   UA-trap spreading and only inherits the delay: at site index 4 (240s of
   a 300s interval) cold-start deadline checking slipped 300s -> 540s.
4. **The off-loop snapshot write had no ceiling.** `write_snapshot_atomic`
   does `fsync`/`mkdir`/`chmod`, uninterruptible on a stalled mount. An
   unbounded `run_in_executor` parks the worker forever, `poll_once` never
   completes, its future never resolves, `_record_task_death` never fires
   and the settlement gate stays OPEN over stale data.

No network I/O and no wall-clock races: every test here pins a STRUCTURAL
property (mutual exclusion, which condition objects are constructed, which
`start_time` a timer was armed with, which call is bounded).
"""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest import nws_actor as nws_actor_module
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.registry.sites import default_registry
from breezy.runtime import health as health_module
from tests.unit.test_ingest_nws_actor import (
    ALL_SITES,
    CITY,
    VENUE,
    FakeClock,
    _local_probe,
    build_actor,
    durable_store_pair,
)

SECOND_NS = 1_000_000_000
SITE_LABEL = f"{VENUE}/{CITY}"


@pytest.fixture
def shared(tmp_path: Path) -> Iterator[SharedIngestState]:
    store, opener = durable_store_pair()
    state = SharedIngestState(
        registry=default_registry(),
        sites=ALL_SITES,
        catalog_base=tmp_path / "nws",
        store=store,
        clock=FakeClock(),
        store_opener=opener,
        probe=_local_probe,
        check_proxy_env=False,
    )
    try:
        yield state
    finally:
        state.dispose()


@pytest.fixture
def actor(shared: SharedIngestState) -> Iterator[NwsIngestActor]:
    instance = build_actor(shared)
    try:
        yield instance
    finally:
        instance.shutdown_executor()


class RecordingSink:
    """An `AlertSink` that keeps every payload `emit_alert` hands it."""

    def __init__(self) -> None:
        self.payloads: list[Any] = []

    def emit(self, payload: Any) -> None:
        self.payloads.append(payload)


class ConditionRecorder:
    """An `AlertState` stand-in that captures the conditions of every cycle.

    Mirrors the real class's SHAPE, not just the method the wiring happens to
    call today: `evaluate` is the state-mutating half and `dispatch` is
    `evaluate` plus the blocking fan-out. A stub that defined only `dispatch`
    is what previously blocked confining the mutation to the loop thread.
    """

    def __init__(self) -> None:
        self.cycles: list[tuple[Any, ...]] = []

    def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
        self.cycles.append(tuple(conditions))
        return ()

    def dispatch(self, sink: Any, conditions: Sequence[Any], *, now_ns: int) -> int:
        return len(self.evaluate(conditions, now_ns=now_ns))


def _conditions_of_kind(cycle: Sequence[Any], kind: str) -> list[Any]:
    return [c for c in cycle if c.key.kind == kind]


def _stub_reconcile(monkeypatch: pytest.MonkeyPatch, actor: NwsIngestActor) -> None:
    """Neutralise the ledger + catalog so a test can isolate one branch.

    Patched through `reconcile_and_report.__globals__` -- the exact dict the
    bytecode reads -- because `tests/unit/test_runtime_node_config.py` evicts
    `breezy.ingest.nws_actor` from `sys.modules`, so a later import can create
    a SECOND module object whose `__dict__` nobody is executing.
    """
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])
    gaps_module = globals_["gaps"]
    monkeypatch.setattr(
        gaps_module,
        "reconcile",
        lambda **_kwargs: type("_Result", (), {"revisions": ()})(),
    )
    monkeypatch.setattr(gaps_module, "site_entries", lambda *_a, **_k: ())


# ---------------------------------------------------------------------------
# Finding 1 -- overlapping poll cycles must not race `AlertState`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_poll_cycle_is_refused_while_one_is_in_flight(
    actor: NwsIngestActor,
) -> None:
    """`on_poll_timer` fires unconditionally, so an overrunning cycle must be
    excluded by `poll_once` itself -- not left to overlap and interleave two
    `AlertState.evaluate` read-modify-writes across the executor."""
    entered = 0
    release = asyncio.Event()

    async def slow_reconcile() -> None:
        # Only the FIRST cycle parks. A refused overlap must be observable as
        # a counter that did not move -- never as a deadlock, which would say
        # nothing about exclusion and would hang the suite instead of failing.
        nonlocal entered
        entered += 1
        if entered == 1:
            await release.wait()

    actor.reconcile_and_report = slow_reconcile  # type: ignore[method-assign]
    actor.network_allowed = lambda: False  # type: ignore[method-assign]

    first = asyncio.create_task(actor.poll_once())
    await asyncio.sleep(0)
    assert entered == 1, "the first cycle never entered"

    await actor.poll_once()  # the overlapping fire: must be refused, not queued
    assert entered == 1, "an overlapping cycle ran and can interleave AlertState"

    release.set()
    await first
    assert entered == 1

    # The guard releases: the NEXT tick still polls.
    await actor.poll_once()
    assert entered == 2, "the in-flight guard never cleared -- polling is dead"


@pytest.mark.asyncio
async def test_alert_dispatch_only_ever_runs_under_the_in_flight_guard(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural property, asserted rather than raced: the alert-state
    mutation is reached only from inside the mutual-exclusion window, so two
    dispatches cannot be in flight at once."""
    _stub_reconcile(monkeypatch, actor)
    observed: list[bool] = []

    class Probe(ConditionRecorder):
        def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
            observed.append(actor.poll_in_flight)
            return super().evaluate(conditions, now_ns=now_ns)

    actor._alert_state = Probe()  # type: ignore[assignment]
    actor.network_allowed = lambda: False  # type: ignore[method-assign]

    await actor.poll_once()

    assert observed == [True], (
        "alert dispatch ran outside the in-flight guard -- two cycles can "
        "interleave AlertState.evaluate"
    )


# ---------------------------------------------------------------------------
# Finding 2 -- a swallowed reconcile failure must page, not go quiet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_swallowed_reconcile_failure_raises_a_critical_ledger_alert(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `TamperedGapLedgerError` leaves `entries=()`, i.e. a snapshot that
    reports zero open gaps for a site whose ledger is unreadable. The failure
    must reach the operator as CRITICAL instead."""
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("tampered gap ledger")

    monkeypatch.setattr(globals_["gaps"], "reconcile", _boom)

    sink = RecordingSink()
    actor.alert_sink = sink
    recorder = ConditionRecorder()
    actor._alert_state = recorder  # type: ignore[assignment]

    await actor.reconcile_and_report()

    assert recorder.cycles, "no alert cycle was evaluated at all"
    ledger = _conditions_of_kind(recorder.cycles[-1], nws_actor_module.LEDGER_UNAVAILABLE)
    assert len(ledger) == 1, (
        "the swallowed reconcile failure raised no LEDGER_UNAVAILABLE condition -- "
        "the site reports zero open gaps while revision detection is dead"
    )
    condition = ledger[0]
    assert condition.active is True
    assert condition.severity == "CRITICAL"
    assert condition.key.site == SITE_LABEL
    assert "RuntimeError" in condition.detail


@pytest.mark.asyncio
async def test_the_ledger_alert_reaches_the_sink_and_clears_on_recovery(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the REAL `AlertState`: the condition fires once on
    the false->true transition, and is still evaluated (as inactive) once the
    ledger recovers, so it can fire again on the next failure."""
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])
    gaps_module = globals_["gaps"]

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("tampered gap ledger")

    monkeypatch.setattr(gaps_module, "reconcile", _boom)

    sink = RecordingSink()
    actor.alert_sink = sink

    await actor.reconcile_and_report()

    fired = [p for p in sink.payloads if p.event == nws_actor_module.LEDGER_UNAVAILABLE]
    assert len(fired) == 1, "the CRITICAL ledger alert never reached the sink"
    assert fired[0].severity == "CRITICAL"
    assert fired[0].site == SITE_LABEL

    # Recovery: the condition must be passed as inactive, not simply dropped,
    # or `AlertState` would never see the true->false edge and the NEXT
    # failure would be a true->true no-op muted for 24h.
    monkeypatch.setattr(
        gaps_module,
        "reconcile",
        lambda **_kwargs: type("_Result", (), {"revisions": ()})(),
    )
    monkeypatch.setattr(gaps_module, "site_entries", lambda *_a, **_k: ())
    recorder = ConditionRecorder()
    actor._alert_state = recorder  # type: ignore[assignment]

    await actor.reconcile_and_report()

    ledger = _conditions_of_kind(recorder.cycles[-1], nws_actor_module.LEDGER_UNAVAILABLE)
    assert len(ledger) == 1, "the ledger condition vanished instead of clearing"
    assert ledger[0].active is False


# ---------------------------------------------------------------------------
# Finding 3 -- stagger the network timer only
# ---------------------------------------------------------------------------


def test_the_settlement_deadline_timer_is_not_staggered(
    shared: SharedIngestState,
) -> None:
    """`check_final_deadline` makes no HTTP request, so it gains nothing from
    UA-trap spreading and must not inherit the delay: at 240s of stagger the
    cold-start deadline check would otherwise slip 300s -> 540s, roughly eight
    minutes of overdue->page latency before an 08:00 ET settlement deadline."""
    instance = build_actor(
        shared,
        poll_interval_seconds=300,
        final_deadline_check_interval_seconds=300,
        stagger_offset_seconds=240,
    )
    try:
        instance._arm_timers()
        clock = instance.clock

        assert clock.next_time_ns(instance._poll_timer_name) == (240 + 300) * SECOND_NS
        assert clock.next_time_ns(instance._deadline_timer_name) == 300 * SECOND_NS, (
            "the deadline timer inherited the poll stagger -- cold-start "
            "deadline checking slips by the full offset"
        )
    finally:
        instance.shutdown_executor()


# ---------------------------------------------------------------------------
# Finding 4 -- unbounded off-loop I/O is a fail-open in supervision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stalled_snapshot_write_surfaces_as_task_death(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unbounded `run_in_executor` over `fsync` parks the worker forever:
    `poll_once` never completes, its future never resolves, `_on_poll_done`
    never runs, and the gate stays OPEN over stale data. The stall must
    surface as an exception on the poll task instead."""
    _stub_reconcile(monkeypatch, actor)
    actor.health_snapshot_path = tmp_path / "health.json"
    actor.observability_io_timeout_s = 0.05
    actor.network_allowed = lambda: False  # type: ignore[method-assign]

    released = threading.Event()

    def _stalled(path: Path, snapshot: Any) -> None:
        released.wait(30)

    monkeypatch.setattr(health_module, "write_snapshot_atomic", _stalled)

    try:
        with pytest.raises(TimeoutError):
            await actor.poll_once()
    finally:
        released.set()


@pytest.mark.asyncio
async def test_a_stalled_alert_dispatch_surfaces_as_task_death(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same ceiling, same reason, for the other off-loop call in the cycle."""
    _stub_reconcile(monkeypatch, actor)
    actor.observability_io_timeout_s = 0.05
    actor.network_allowed = lambda: False  # type: ignore[method-assign]

    released = threading.Event()

    class StalledTracker:
        """Decides one payload; the STALL lives in the sink below, which is
        where a black-holed webhook actually parks a worker."""

        def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
            return (
                health_module.AlertPayload(
                    severity="CRITICAL", event="test", site=SITE_LABEL, detail="d"
                ),
            )

    class StalledSink:
        def emit(self, payload: Any) -> None:
            released.wait(30)

    actor._alert_state = StalledTracker()  # type: ignore[assignment]
    actor.alert_sink = StalledSink()

    try:
        with pytest.raises(TimeoutError):
            await actor.poll_once()
    finally:
        released.set()


@pytest.mark.asyncio
async def test_an_ordinary_observability_failure_is_still_swallowed(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new timeout escape hatch must not widen into "every observability
    failure kills the poll": only a STALL (a permanently parked worker) is a
    supervision event."""
    _stub_reconcile(monkeypatch, actor)

    class RaisingTracker:
        def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
            raise ValueError("sink exploded")

    actor._alert_state = RaisingTracker()  # type: ignore[assignment]
    actor.network_allowed = lambda: False  # type: ignore[method-assign]

    await actor.poll_once()  # must not raise


# ---------------------------------------------------------------------------
# Finding 2b -- the FILE-based monitor must also see the dead ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_snapshot_file_marks_the_ledger_unavailable(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CRITICAL alert is not enough on its own: `BREEZY_ALERT_WEBHOOK_URL`
    is UNSET by default, so `resolve_alert_sink` returns a logging sink and
    the alert reaches nothing an operator polls. The runbook points operators
    at `health-<venue>.<city>.json`, so the FILE must carry the marker --
    otherwise `open_gaps: []` on a dead ledger is indistinguishable from a
    genuinely healthy site.
    """
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("tampered gap ledger")

    monkeypatch.setattr(globals_["gaps"], "reconcile", _boom)
    actor.alert_sink = RecordingSink()
    path = tmp_path / "health-venue.city.json"
    actor.health_snapshot_path = path

    await actor.reconcile_and_report()

    decoded = json.loads(path.read_text())
    site = decoded["sites"][0]
    assert site["ledger_unavailable"] is not None, (
        "the snapshot FILE reports a healthy ledger while reconciliation is "
        "failing every cycle -- open_gaps: [] is indistinguishable from health"
    )
    assert "RuntimeError" in site["ledger_unavailable"]
    assert site["open_gaps"] == []


@pytest.mark.asyncio
async def test_a_healthy_ledger_leaves_the_snapshot_marker_null(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL. A working ledger must never set the marker, or the
    field is noise and an operator learns to ignore it.
    """
    _stub_reconcile(monkeypatch, actor)
    actor.alert_sink = RecordingSink()
    path = tmp_path / "health-venue.city.json"
    actor.health_snapshot_path = path

    await actor.reconcile_and_report()

    decoded = json.loads(path.read_text())
    assert decoded["sites"][0]["ledger_unavailable"] is None


@pytest.mark.asyncio
async def test_the_ledger_marker_recovers_to_null_on_the_next_good_cycle(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A latched-forever marker would be as useless as no marker at all."""
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])
    gaps_module = globals_["gaps"]

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError("tampered gap ledger")

    monkeypatch.setattr(gaps_module, "reconcile", _boom)
    actor.alert_sink = RecordingSink()
    path = tmp_path / "health-venue.city.json"
    actor.health_snapshot_path = path

    await actor.reconcile_and_report()
    assert json.loads(path.read_text())["sites"][0]["ledger_unavailable"] is not None

    _stub_reconcile(monkeypatch, actor)
    await actor.reconcile_and_report()

    assert json.loads(path.read_text())["sites"][0]["ledger_unavailable"] is None


@pytest.mark.asyncio
async def test_the_ledger_marker_cannot_carry_pii_or_paths_out_of_the_exception(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The detail originates in an EXCEPTION MESSAGE, which is attacker- and
    environment-influenced: pyarrow/sqlite failures interpolate absolute
    catalog and state-db paths, and an HTTP-layer failure can interpolate the
    User-Agent contact (`+mailto:<address>`). `health.py`'s redaction
    guarantee is "no field slot exists to hold it" -- a free-text field
    punches a hole through that, so the value must be scrubbed BEFORE it is
    stored, covering the webhook payload as well as the disk artifact.
    """
    globals_ = type(actor).reconcile_and_report.__globals__
    monkeypatch.setitem(globals_, "read_climate_days", lambda _catalog: [])

    def _boom(**_kwargs: Any) -> Any:
        raise RuntimeError(
            "failed opening /home/operator/breezy/state/breezy.sqlite3 for "
            "breezy-weather-ingest/0.1 (+mailto:breezy-data@gmail.com)\n"
            "CLIMATE REPORT NATIONAL WEATHER SERVICE NEW YORK NY MAXIMUM 91"
        )

    monkeypatch.setattr(globals_["gaps"], "reconcile", _boom)
    sink = RecordingSink()
    actor.alert_sink = sink
    path = tmp_path / "health-venue.city.json"
    actor.health_snapshot_path = path

    await actor.reconcile_and_report()

    file_text = path.read_text()
    payload_text = " ".join(str(p.detail) for p in sink.payloads)
    for leak in (
        "breezy-data@gmail.com",
        "mailto:",
        "/home/operator",
        "breezy.sqlite3",
        "NATIONAL WEATHER SERVICE",
    ):
        assert leak not in file_text, f"{leak!r} reached the snapshot artifact"
        assert leak not in payload_text, f"{leak!r} reached the alert payload"

    # ... while still naming the failure well enough to diagnose it.
    marker = json.loads(file_text)["sites"][0]["ledger_unavailable"]
    assert marker is not None
    assert marker.startswith("RuntimeError")


# ---------------------------------------------------------------------------
# Finding 1b -- AlertState's mutation must be CONFINED to the loop thread,
# not merely excluded from concurrency by the in-flight guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_alert_state_mutation_runs_on_the_event_loop_thread(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AlertState` documents itself as "deliberately not thread-safe ...
    exactly one poll loop is expected to own an instance", and `evaluate` is a
    read-modify-write over two dicts. Running the whole `dispatch` on an
    executor worker made that documented ownership false: it was safe only
    because no OTHER path dispatches alerts today, i.e. thread-safety by
    exclusion rather than by confinement. The next caller added anywhere makes
    it a silent data race over exactly the transitions that must never be lost
    (`UA_TRAP_LATCHED`, `SITE_BLOCKED`).

    Only the BLOCKING half -- `emit_alert` -> `WebhookAlertSink.emit` -> a
    synchronous `httpx` POST -- has any reason to leave the loop.
    """
    _stub_reconcile(monkeypatch, actor)
    loop_thread = threading.get_ident()
    mutated_on: list[int] = []
    emitted_on: list[int] = []

    class ThreadProbe:
        def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
            mutated_on.append(threading.get_ident())
            return (
                health_module.AlertPayload(
                    severity="CRITICAL", event="test", site=SITE_LABEL, detail="d"
                ),
            )

        def dispatch(self, sink: Any, conditions: Sequence[Any], *, now_ns: int) -> int:
            # Present so this test cannot pass merely because the stub lost a
            # method: if the wiring still runs the whole dispatch off-loop, it
            # is recorded here and the assertion below fails on the thread id.
            mutated_on.append(threading.get_ident())
            return len(self.evaluate(conditions, now_ns=now_ns))

    class ThreadRecordingSink:
        def emit(self, payload: Any) -> None:
            emitted_on.append(threading.get_ident())

    actor._alert_state = ThreadProbe()  # type: ignore[assignment]
    actor.alert_sink = ThreadRecordingSink()

    await actor.reconcile_and_report()

    assert mutated_on, "the alert state was never evaluated at all"
    assert set(mutated_on) == {loop_thread}, (
        "AlertState's read-modify-write ran on an executor worker -- the class "
        "documents itself as owned by exactly one poll loop"
    )
    assert emitted_on, "the decided payload never reached the sink"
    assert loop_thread not in emitted_on, (
        "the blocking sink fan-out was pulled back onto the event loop thread"
    )


@pytest.mark.asyncio
async def test_a_sink_failure_after_the_split_still_never_changes_the_count(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AlertState.dispatch` returns what it DECIDED to emit, never what the
    sink managed to deliver -- "a sink's own delivery failure must never
    change what this method returns or retry/duplicate an already-decided
    emission". Splitting evaluate/emit must preserve that exactly.
    """
    _stub_reconcile(monkeypatch, actor)

    payloads = tuple(
        health_module.AlertPayload(
            severity="CRITICAL", event=f"e{i}", site=SITE_LABEL, detail="d"
        )
        for i in range(3)
    )

    class Tracker:
        def evaluate(self, conditions: Sequence[Any], *, now_ns: int) -> tuple[Any, ...]:
            return payloads

    class ExplodingSink:
        def emit(self, payload: Any) -> None:
            raise ssl.SSLError("certificate verify failed")

    actor._alert_state = Tracker()  # type: ignore[assignment]
    actor.alert_sink = ExplodingSink()

    await actor.reconcile_and_report()  # must not raise

    snapshot = actor.last_health_snapshot
    assert snapshot is not None
    assert snapshot.alerts_emitted_this_cycle == 3, (
        "a failing sink changed the decided-emission count"
    )
