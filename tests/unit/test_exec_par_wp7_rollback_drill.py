"""EXEC-PAR WP7 (r5 5.WP7 + section 7 rollback notes): supervisor rollback, the
rollback drill and breaker re-detection after a crash.

* A supervisor rolled back MID-RUN stops advertising slot schema 2; the latch then
  refuses every 1 -> 2 transition and leaves the stored table byte-identical.
* The rollback drill: drain to <= 1 open, reset the breaker record (node down,
  held positions acknowledged, through the REAL operator CLI), verify
  ``halted: null`` BEFORE any code is reverted, then run K = 1 over the same
  store. Old code ignores the breaker record, so a stale ``halted`` would sit
  there silently and bite on a later roll-forward; the drill therefore asserts
  the reset happened first.
* A crash between the watcher's detection and its latch write loses nothing:
  the trigger is re-derived from durable slot state after the restart.

The REAL client, latch, ledger, supervisor-marker module, watcher actor and
operator CLI run; only the venue sender and the alert sink are doubles. Caps go
through the whitelisted ``caps`` seam. No unit file, permit or order switch is
touched.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime import clear_submit_intent_cli as cli
from breezy.runtime.breaker_watcher import STUCK_AGE_NS, BreakerWatcherActor
from breezy.runtime.exec_state_db_path import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentAdmissionDenied,
    decode_slot_table,
)
from breezy.runtime.submit_intent_slots import BreakerRecord, parse_breaker
from breezy.runtime.supervisor_decode_marker import (
    discard_supervisor_decode_marker,
    supervisor_admits_slot_schema,
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)
from tests.unit.exec_par_rig import (
    BASE_NS,
    SEC_NS,
    ParRig,
    ScriptedSender,
    ambiguous_body,
    arm_open_intent,
    backdate,
    build_par_rig,
    caps,
    ok,
    par_rig,
    run_passes,
    submit_chain,
    wire_order,
    wire_positions,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

WAIT = submit_chain.OPEN_INTENT_WAIT_REASON
SUPERVISOR_PID = 4242


# ---------------------------------------------------------------------------
# supervisor rolled back mid-run
# ---------------------------------------------------------------------------


class _Supervisor:
    """A stand-in for the running supervisor's ``/proc`` identity and marker file."""

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.start_ticks: dict[int, int] = {SUPERVISOR_PID: 777}

    def ticks(self, pid: int) -> int | None:
        return self.start_ticks.get(pid)

    def advertise_v2(self) -> None:
        write_supervisor_decode_marker(
            self.store_path, revision="wp5a", pid=SUPERVISOR_PID, process_start_ticks=self.ticks
        )

    def predicate(self) -> bool:
        return supervisor_admits_slot_schema(self.store_path, process_start_ticks=self.ticks)

    def roll_back(self, mode: str) -> None:
        """The supervisor restarts as OLD code: ``mode`` is how that shows on disk."""
        if mode == "marker_without_slot_schema":
            supervisor_decode_marker_path(self.store_path).write_text(
                json.dumps(
                    {
                        "v": 1,
                        "pid": SUPERVISOR_PID,
                        "start_ticks": self.start_ticks[SUPERVISOR_PID],
                        "revision": "pre-wp5a",
                        "retirement_reasons": [],
                    }
                )
            )
        elif mode == "marker_discarded":
            discard_supervisor_decode_marker(self.store_path)
        elif mode == "supervisor_pid_replaced":
            self.start_ticks[SUPERVISOR_PID] += 1  # same pid, a different incarnation
        elif mode == "marker_garbled":
            supervisor_decode_marker_path(self.store_path).write_text("{not json")
        else:  # pragma: no cover - a typo in the parametrisation
            raise AssertionError(mode)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "marker_without_slot_schema",
        "marker_discarded",
        "supervisor_pid_replaced",
        "marker_garbled",
    ],
)
async def test_supervisor_rolled_back_mid_run_blocks_v2_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    mode: str,
) -> None:
    store_path = tmp_path / "exec_state.db"
    supervisor = _Supervisor(store_path)
    supervisor.advertise_v2()
    sender = ScriptedSender(
        ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")), ok(zero_fill_body())
    )
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=3,
            v2_predicate=supervisor.predicate,
            store_path=store_path,
        ) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            await rig.client._submit_order(rig.buy(rig.instruments[1]))
            assert len(sender.calls) == 2, "a v2-capable supervisor admits the second slot"
            table_before = rig.latch._store.get(CURRENT_INTENT_KEY)
            assert decode_slot_table(table_before).version == 2

            supervisor.roll_back(mode)
            third = rig.slug(2)
            assert rig.latch.admission_refusal(third, False) == "v2_predicate"
            assert rig.latch.admission_refusal(third, True) == "v2_predicate", "exits write v2 too"
            await rig.client._submit_order(rig.buy(rig.instruments[2]))

            assert rig.denied_reasons() == [WAIT]
            assert len(sender.calls) == 2, "no order is POSTed behind a refused v2 write"
            assert rig.latch._store.get(CURRENT_INTENT_KEY) == table_before, "table untouched"

            # Control: the same order is admitted once the supervisor advertises v2 again.
            supervisor.start_ticks[SUPERVISOR_PID] = 777
            supervisor.advertise_v2()
            assert rig.latch.admission_refusal(third, False) is None
            await rig.client._submit_order(rig.buy(rig.instruments[2]))
            assert len(sender.calls) == 3


@pytest.mark.asyncio
async def test_rolled_back_supervisor_refuses_the_one_to_two_transition_in_arm_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """One slot at v1, supervisor rolled back, a SECOND ``arm_slot``: refused by the arbiter.

    ``arm_slot`` is called directly so the ``admission_refusal`` pre-check cannot
    be what refuses it: only the arbiter-side predicate inside ``arm_slot`` stands
    between a rolled-back supervisor and a v2 table it cannot decode.
    """
    store_path = tmp_path / "exec_state.db"
    supervisor = _Supervisor(store_path)
    supervisor.advertise_v2()
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=ScriptedSender(),
            max_slots=2,
            v2_predicate=supervisor.predicate,
            store_path=store_path,
        ) as rig:
            arm_open_intent(rig, 0, venue_order_id="ord-a")
            before = rig.latch._store.get(CURRENT_INTENT_KEY)
            assert decode_slot_table(before).version == 1

            supervisor.roll_back("marker_without_slot_schema")
            with pytest.raises(SubmitIntentAdmissionDenied) as denied:
                rig.latch.arm_slot(
                    "a" * 64, slug=rig.slug(1), is_exit=False, now_ns=rig.clock.timestamp_ns()
                )

            assert denied.value.reason == "v2_predicate"
            after = rig.latch._store.get(CURRENT_INTENT_KEY)
            assert after == before, "the persisted bytes are unchanged"
            assert decode_slot_table(after).version == 1, "still a v1 table"


# ---------------------------------------------------------------------------
# the rollback drill
# ---------------------------------------------------------------------------


class _CliRun:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err


def _cli(store_path: Path, *argv: str) -> _CliRun:
    """The REAL operator tool; it takes the node's flock, so it refuses while the node is up."""
    out, err = io.StringIO(), io.StringIO()
    env = {EXEC_STATE_DB_ENV_VAR: str(store_path), cli.OPERATOR_ACK_ENV_VAR: "1"}
    code = cli.main(list(argv), env=env, stdout=out, stderr=err, clock_ns=lambda: BASE_NS)
    return _CliRun(code, out.getvalue(), err.getvalue())


def _breaker(store_path: Path) -> BreakerRecord | None:
    with SqliteStateStore(store_path) as store:
        raw = store.get(BREAKER_KEY)
    return None if raw is None else parse_breaker(raw)


def _table_bytes(store_path: Path) -> bytes | None:
    with SqliteStateStore(store_path) as store:
        return store.get(CURRENT_INTENT_KEY)


async def _trip_and_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store_path: Path
) -> ParRig:
    """A K = 2 node with two open slots and a latched breaker, drained to zero open.

    The drain runs with the node UP and the halt latched: the halt is entries-only,
    so the resolver keeps working, and draining must not clear the halt.
    """
    first = await build_par_rig(
        tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2, store_path=store_path
    )
    ids = [
        arm_open_intent(first, 0, venue_order_id="ord-a", registered=True),
        arm_open_intent(first, 1, venue_order_id="ord-b", registered=True),
    ]
    first.latch.write_breaker_halt("contradiction", ts_ns=first.clock.timestamp_ns())
    assert first.latch.admission_refusal(first.slug(2), False) == "breaker_halted"

    for index, name in enumerate(("ord-a", "ord-b")):
        wire_order(first, name, index, state="ORDER_STATE_CANCELED", cum_quantity=0)
    wire_positions(first, {})
    for intent_id in ids:
        backdate(first.client, intent_id)
    await run_passes(first.client, count=6)

    assert not any(first.latch.is_open_intent(i) for i in ids), "drained"
    record = first.latch.read_breaker_record()
    assert record is not None and record.is_halted, "draining never clears the halt"
    return first


@pytest.mark.asyncio
async def test_drain_then_reset_then_rollback_drill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Drain, reset (real CLI, node down), verify ``halted: null``, THEN run K = 1.

    The stand-in for the "old reader" is the CURRENT code at K = 1 plus
    ``SubmitIntent.from_bytes`` on the stored bytes; no historical build is run.
    """
    store_path = tmp_path / "exec_state.db"
    sender = ScriptedSender(ok(zero_fill_body(order_id="ord-k1")))
    with caps():
        node = await _trip_and_drain(tmp_path, monkeypatch, store_path)

        # --- the drained table is v1 bytes: what an older reader can decode ----------
        drained = decode_slot_table(node.latch._store.get(CURRENT_INTENT_KEY))
        assert drained.version == 1 and drained.open == ()

        # --- reset needs the node DOWN ... -------------------------------------------
        up = _cli(store_path, "--yes", "--reset-entry-halt", "--ack-held-positions-reviewed")
        assert up.code == cli.EXIT_REFUSED and "holds the lock" in up.err
        await node.close()

        # ... and the operator's acknowledgement that held positions were reviewed
        unacked = _cli(store_path, "--yes", "--reset-entry-halt")
        assert unacked.code == cli.EXIT_REFUSED
        halted = _breaker(store_path)
        assert halted is not None and halted.is_halted, "still halted before the reset"

        done = _cli(store_path, "--yes", "--reset-entry-halt", "--ack-held-positions-reviewed")
        assert done.code == cli.EXIT_OK, done.err

        # --- the gate: the breaker record is reset BEFORE any code is reverted --------
        before_rollback = _breaker(store_path)
        assert before_rollback is not None
        assert before_rollback.halted_reason is None and before_rollback.halted_ts_ns is None
        raw_table = _table_bytes(store_path)
        assert raw_table is not None
        # old-code stand-in 1: the K = 1 reader decodes the table as one plain record
        assert SubmitIntent.from_bytes(raw_table).state.value == "RETIRED"

        # --- rollback: K = 1 over the same store, old-code behaviour -------------------
        old = await build_par_rig(
            tmp_path, monkeypatch, sender=sender, max_slots=1, store_path=store_path
        )
        try:
            assert old.latch.max_slots() == 1
            await old.client._submit_order(old.buy(old.instruments[0]))
            assert len(sender.calls) == 1, "K = 1 trades normally after the drill"
            assert old.latch.open_slot_count() == 0
        finally:
            await old.close()

        # --- a later roll-forward finds no stale halt ------------------------------------
        again = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2, store_path=store_path
        )
        try:
            again.latch.write_breaker_heartbeat(
                hb_ns=again.clock.timestamp_ns(), resolver_pass_ns=again.clock.timestamp_ns()
            )
            assert again.latch.admission_refusal(again.slug(2), False) is None
        finally:
            await again.close()


@pytest.mark.asyncio
async def test_drain_to_exactly_one_open_slot_rewrites_the_table_as_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Drain to <= 1 open (here exactly 1): v1 bytes whose record is still OPEN.

    The "old reader" stand-in is the current code at K = 1 and
    ``SubmitIntent.from_bytes``.
    """
    store_path = tmp_path / "exec_state.db"
    with caps():
        node = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2, store_path=store_path
        )
        ids = [
            arm_open_intent(node, 0, venue_order_id="ord-a", registered=True),
            arm_open_intent(node, 1, venue_order_id="ord-b", registered=True),
        ]
        assert decode_slot_table(node.latch._store.get(CURRENT_INTENT_KEY)).version == 2
        wire_order(node, "ord-a", 0, state="ORDER_STATE_CANCELED", cum_quantity=0)
        wire_order(node, "ord-b", 1, state="ORDER_STATE_NEW", cum_quantity=0)
        wire_positions(node, {})
        for intent_id in ids:
            backdate(node.client, intent_id)
        await run_passes(node.client, count=6)

        assert not node.latch.is_open_intent(ids[0])
        assert node.latch.is_open_intent(ids[1])
        raw = node.latch._store.get(CURRENT_INTENT_KEY)
        assert raw is not None
        assert decode_slot_table(raw).version == 1, "rewritten as v1 once <= 1 is open"
        record = SubmitIntent.from_bytes(raw)
        assert record.state.value == "OPEN" and record.intent_id == ids[1]
        await node.close()

        old = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=1, store_path=store_path
        )
        try:
            assert old.latch.admission_refusal(old.slug(2), False) == "slot_open"
        finally:
            await old.close()


@pytest.mark.asyncio
async def test_rollback_without_the_reset_leaves_a_stale_halt_that_bites_on_roll_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The hazard the drill exists for: old code ignores the record, so skipping the
    reset is invisible until K > 1 returns and refuses entries on a halt nobody saw."""
    store_path = tmp_path / "exec_state.db"
    sender = ScriptedSender(ok(zero_fill_body(order_id="ord-k1")))
    with caps():
        node = await _trip_and_drain(tmp_path, monkeypatch, store_path)
        await node.close()

        old = await build_par_rig(
            tmp_path, monkeypatch, sender=sender, max_slots=1, store_path=store_path
        )
        try:
            await old.client._submit_order(old.buy(old.instruments[0]))
            assert len(sender.calls) == 1, "K = 1 ignores the breaker record: silently inert"
        finally:
            await old.close()

        halted = _breaker(store_path)
        assert halted is not None and halted.is_halted, "the stale halt persisted undetected"
        again = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2, store_path=store_path
        )
        try:
            assert again.latch.admission_refusal(again.slug(2), False) == "breaker_halted"
        finally:
            await again.close()


# ---------------------------------------------------------------------------
# crash after detection, before the latch write
# ---------------------------------------------------------------------------


class _Crash(BaseException):
    """A simulated process death (not an ``Exception``: the tick cannot contain it)."""


class _CrashOnHaltLatch:
    """The latch port whose halt write never happens: the process dies first."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.heartbeats = 0

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        raise _Crash

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        self.heartbeats += 1
        self._inner.write_breaker_heartbeat(hb_ns=hb_ns, resolver_pass_ns=resolver_pass_ns)


class _Sink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)

    def events(self, name: str) -> list[AlertPayload]:
        return [p for p in self.emitted if p.event == name]


def _watcher(latch: Any, client: Any, sink: _Sink) -> BreakerWatcherActor:
    clock = TestClock()
    clock.set_time(BASE_NS)
    actor = BreakerWatcherActor(latch=latch, alert_sink=sink)
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.bind_client(lambda: client)
    return actor


def _two_stuck_slots(rig: ParRig) -> None:
    age_s = STUCK_AGE_NS // SEC_NS + 100
    for index in (0, 1):
        arm_open_intent(rig, index, venue_order_id=f"ord-{index}", age_s=float(age_s))


@pytest.mark.asyncio
async def test_crash_after_detection_before_latch_redetects_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    store_path = tmp_path / "exec_state.db"
    with caps():
        first = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=3, store_path=store_path
        )
        _two_stuck_slots(first)
        sink = _Sink()
        doomed = _watcher(_CrashOnHaltLatch(first.latch), first.client, sink)

        with pytest.raises(_Crash):
            await doomed.tick()  # detects stuck_slots; dies before the latch write

        assert first.latch.read_breaker_record() is None, "nothing was persisted"
        assert sink.events("EXEC_PAR_BREAKER_TRIPPED") == []
        assert first.latch.admission_refusal(first.slug(2), False) is None, "the gap is real"
        await first.close()

        second = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=3, store_path=store_path
        )
        try:
            assert second.latch.open_slot_count() == 2, "the stuck slots are durable"
            sink2 = _Sink()
            watcher = _watcher(second.latch, second.client, sink2)

            assert await watcher.tick() is True

            record = second.latch.read_breaker_record()
            assert record is not None and record.halted_reason == "stuck_slots"
            assert record.hb_ns == BASE_NS, "the heartbeat follows the persisted halt"
            assert second.latch.admission_refusal(second.slug(2), False) == "breaker_halted"
            assert len(sink2.events("EXEC_PAR_BREAKER_TRIPPED")) == 1
        finally:
            await second.close()
