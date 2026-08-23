"""WI-10 + WI-12 wiring: the gap ledger and the health/alert emission,
attached at the TOP of `NwsIngestActor.poll_once`.

Why the attachment point is the whole test subject
---------------------------------------------------
`docs/plans/PHASE_CD_COLLECTION_DURABILITY_DESIGN.md` §3 "Attachment point"
puts `reconcile` beside `check_staleness()` and BEFORE the `network_allowed()`
early return, because that is the only line reached on every timer fire. The
304 branch, the no-new-products branch and the network-disallowed branch all
return early -- and those are precisely the polls a gap ledger exists to
observe. Three tests here pin exactly that, and they assert against the
DURABLE ledger rather than against a call spy, so they prove the whole chain
(clock -> catalog read -> reconcile -> store) rather than that one function
name was reached.

Failure isolation
-----------------
`gaps.reconcile` deliberately does NOT swallow -- it raises
`TamperedGapLedgerError` on a corrupted ledger -- so containment belongs at
the call site. Losing reconciliation for one cycle is recoverable; losing the
poll is not. Two tests assert the poll survives, and that the gate does not
acquire a block it did not earn.

Zero network I/O and no wall clock
-----------------------------------
`respx` intercepts `httpx` at the transport layer and `tests/conftest.py`
blocks real sockets as a second, independent mechanism. Every instant comes
from `FakeClock`, whose origin is derived from the NYC fixture's own
`meta.json`; no `date.today()` and no `time.time_ns()` is ever read, so this
file carries no date time-bomb.

Seams reused rather than reinvented: `process_cycle` / `start_and_settle` /
the `settings` fixture / `ThreadRecordingStore` from
`tests/integration/test_runtime_restart_resume.py`, and `FakeClock` /
`mock_discovery` / `mock_product` / the fixture constants from
`tests/unit/test_ingest_nws_actor.py`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from breezy.ingest import gaps
from breezy.ingest.gaps import GapState, TamperedGapLedgerError
from breezy.ingest.gate import GateReason, GateState
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.runtime.health import (
    POST_SETTLEMENT_REVISION,
    AlertPayload,
)
from tests.integration.test_runtime_restart_resume import (
    ThreadRecordingStore,
    process_cycle,
    settings,  # noqa: F401 -- re-exported pytest fixture
    start_and_settle,
)
from tests.unit.test_ingest_nws_actor import (
    CITY,
    DISCOVERY_URL,
    NYC_FINAL,
    VENUE,
    FakeClock,
    mock_discovery,
    mock_product,
)

# The fixture instant is 2026-08-22T06:31Z == 01:31 EST, so the local-STANDARD
# date is 2026-08-22 and the most recent COMPLETED climate day is 2026-08-21.
# Derived here from the same `FakeClock` default the rest of the suite uses --
# never restated as a literal, and never read from the wall clock.
STD_OFFSET_HOURS = -5.0
NEWEST_COMPLETED = gaps.most_recent_completed_climate_day(FakeClock().now, STD_OFFSET_HOURS)
# 2026-08-21's review extension (11:00 ET on 2026-08-22) has NOT elapsed at the
# fixture instant, so the newest EXPECTED day is the one before it.
NEWEST_EXPECTED = NEWEST_COMPLETED - dt.timedelta(days=1)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeObserved:
    """Structurally satisfies `gaps.ObservedRecord`.

    Used only where the test needs to drive the ledger through a REVISION,
    which would otherwise require three real catalog writes to set up. The
    reconciliation-attachment tests deliberately use the real catalog read.
    """

    station: str
    climate_day: dt.date
    ts_init: int
    is_final: bool = True
    revision_seq: int = 1
    correction_flag: bool = False
    is_superseded: bool = False


class RecordingSink:
    """An `AlertSink` that records every payload it is handed."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class ExplodingSink:
    """An `AlertSink` whose `emit` always raises.

    `health.emit_alert` contains this internally; these tests assert the
    containment END-TO-END through the wired poll path, which is the property
    an operator actually depends on.
    """

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, payload: AlertPayload) -> None:
        self.calls += 1
        raise RuntimeError("sink is down")


def mock_not_modified(mock: respx.MockRouter) -> Any:
    return mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))


def ledger_days(store: Any, state: GapState | None = None) -> set[dt.date]:
    entries = gaps.site_entries(store, VENUE, CITY)
    return {e.climate_day for e in entries if state is None or e.state is state}


# ---------------------------------------------------------------------------
# 1. Reconciliation runs on every early-return path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_runs_on_the_304_path(settings: Any) -> None:  # noqa: F811
    """A 304 is a SUCCESSFUL poll that writes no record. If reconciliation
    were attached after the terminal publish it would never run on a site
    that is simply up to date -- i.e. never, in the steady state.
    """
    clock = FakeClock()
    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        assert gaps.site_entries(runtime.store, VENUE, CITY) == (), (
            "positive control: the ledger must start empty"
        )

        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()

        assert NEWEST_EXPECTED in ledger_days(runtime.store, GapState.OPEN)


@pytest.mark.asyncio
async def test_reconciliation_runs_on_the_no_new_products_path(
    settings: Any,  # noqa: F811
) -> None:
    """The routine steady state: the discovery list carries products the
    integrity index already knows, so `poll_once` returns at the `pending`
    guard without ever reaching the publish stage.
    """
    clock = FakeClock()
    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()  # ingests it
            await actor.poll_once()  # nothing new

        assert NEWEST_EXPECTED in ledger_days(runtime.store, GapState.OPEN)


@pytest.mark.asyncio
async def test_reconciliation_runs_on_the_network_disallowed_path(
    settings: Any,  # noqa: F811
) -> None:
    """The UA-trap latch halts network I/O for every site. It must NOT halt
    the ledger: a trap that lasts days is exactly when knowing which climate
    days were missed matters most.
    """
    clock = FakeClock()
    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        runtime.shared.gate.record_forbidden_403(
            VENUE, CITY, detail="test", cross_site_burst_detected=True
        )
        assert not actor.network_allowed(), "precondition: the poll must be network-blocked"

        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json={}))
            await actor.poll_once()
            assert not route.called, "the network-disallowed path must issue no request"

        assert NEWEST_EXPECTED in ledger_days(runtime.store, GapState.OPEN)


# ---------------------------------------------------------------------------
# 2. Failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_raising_reconcile_is_logged_and_does_not_fail_the_poll(
    settings: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`reconcile` raises on a tampered ledger by design. Containment is the
    ATTACHMENT point's job, and the gate must not acquire a block the poll
    itself did not earn -- a ledger defect is not a settlement-data defect.
    """
    clock = FakeClock()

    def boom(**_: Any) -> None:
        raise TamperedGapLedgerError(gap_id="x", detail="deliberate")

    monkeypatch.setattr(gaps, "reconcile", boom)

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        with caplog.at_level(logging.ERROR), respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert actor.published, "the poll must still complete and publish"  # type: ignore[attr-defined]
        status = runtime.shared.gate.status(VENUE, CITY)
        assert status.state is not GateState.BLOCKED
        assert GateReason.STATE_STORE_TAMPERED not in runtime.shared.gate.blocking_causes(
            VENUE, CITY
        )
        assert any("gap reconciliation" in r.message.lower() for r in caplog.records), (
            "the swallowed failure must still be logged"
        )


@pytest.mark.asyncio
async def test_a_raising_alert_sink_does_not_break_collection(
    settings: Any,  # noqa: F811
) -> None:
    """`health.emit_alert` contains sink failures internally; this asserts the
    same end-to-end through the wired poll, which is the guarantee that
    actually matters. A monitoring channel outage must never stop ingestion.
    """
    clock = FakeClock()
    sink = ExplodingSink()

    with process_cycle(settings, clock) as (runtime, actor):
        actor.alert_sink = sink
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert sink.calls > 0, "positive control: the sink must actually have been called"
        assert actor.published, "collection must be unaffected by a dead sink"  # type: ignore[attr-defined]
        assert gaps.site_entries(runtime.store, VENUE, CITY) != ()


# ---------------------------------------------------------------------------
# 3. Revision -> PostSettlementRevision alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_revision_event_surfaces_as_a_post_settlement_revision_alert(
    settings: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrected CLI landing after a day was already collected is the
    money-losing case the ledger exists to notice. Driven through three
    cycles: open -> resolve -> revise.
    """
    clock = FakeClock()
    sink = RecordingSink()
    observed: list[FakeObserved] = []
    reads: list[int] = []

    def fake_read_climate_days(_catalog: Any) -> list[FakeObserved]:
        reads.append(len(observed))
        return list(observed)

    with process_cycle(settings, clock) as (_runtime, actor):
        # Patch the namespace `reconcile_and_report` ACTUALLY resolves from --
        # the defining module's `__globals__` -- not `sys.modules`.
        #
        # This is not a stylistic preference. `tests/unit/test_runtime_node_config.py
        # ::test_building_the_node_config_does_not_import_the_actor_module`
        # evicts `breezy.ingest.nws_actor` from `sys.modules` and never restores
        # it, so a later import creates a SECOND module object with a SECOND
        # `__dict__`. `breezy.runtime.composition` still holds the class from
        # the FIRST one, and that class's methods read the FIRST dict. A
        # `monkeypatch.setattr("breezy.ingest.nws_actor.read_climate_days", ...)`
        # then patches the module nobody is executing: the poll reads the real
        # catalog, the ledger never resolves, no revision is detected, and this
        # test fails as a bare `assert 0 == 1` roughly one run in three under
        # random ordering. Patching `__globals__` is immune to module identity
        # by construction, because it targets the exact dict the bytecode reads.
        monkeypatch.setitem(
            type(actor).reconcile_and_report.__globals__,
            "read_climate_days",
            fake_read_climate_days,
        )
        actor.alert_sink = sink
        await start_and_settle(actor)

        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)

            await actor.poll_once()  # cycle 1: NEWEST_EXPECTED opens

            observed.append(
                FakeObserved(
                    station="NYC", climate_day=NEWEST_EXPECTED, ts_init=clock.now, revision_seq=1
                )
            )
            await actor.poll_once()  # cycle 2: resolves
            assert not [p for p in sink.payloads if p.event == POST_SETTLEMENT_REVISION]

            observed[:] = [
                FakeObserved(
                    station="NYC",
                    climate_day=NEWEST_EXPECTED,
                    ts_init=clock.now,
                    revision_seq=2,
                    correction_flag=True,
                )
            ]
            await actor.poll_once()  # cycle 3: revision

        # Seam guard, and it is load-bearing: if the injection ever silently
        # misses again, THIS fails with a precise cause instead of the
        # downstream `assert 0 == 1` that says nothing about why.
        assert reads, "the catalog-read seam was never exercised -- injection missed"
        assert reads[-1] == 1, f"cycle 3 must observe exactly one record, saw {reads[-1]}"

        revisions = [p for p in sink.payloads if p.event == POST_SETTLEMENT_REVISION]
        assert len(revisions) == 1
        assert revisions[0].site == f"{VENUE}/{CITY}"
        assert NEWEST_EXPECTED.isoformat() in revisions[0].detail


# ---------------------------------------------------------------------------
# 4. The snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_snapshot_is_written_once_per_cycle_and_reflects_gate_state(
    settings: Any,  # noqa: F811
    tmp_path: Path,
) -> None:
    """One snapshot per poll cycle, carrying the gate state as of the instant
    it was taken.

    The emission is at the TOP of the cycle, so cycle 1's snapshot legitimately
    shows the PRE-poll state (a fresh site is `BLOCKED/never_polled` until its
    first success) and cycle 2's shows the result of cycle 1. That ordering is
    asserted rather than worked around: `snapshot_at_ns` is what makes the
    artifact interpretable, and a reader who assumes post-poll state would
    misread every fresh deployment.

    Also a redaction regression: no absolute state-db or catalog path may
    appear anywhere in the serialised artifact.
    """
    clock = FakeClock()
    target = tmp_path / "health" / "breezy-health.json"
    target.parent.mkdir(parents=True)

    with process_cycle(settings, clock) as (runtime, actor):
        actor.health_snapshot_path = target
        await start_and_settle(actor)
        assert not target.exists(), "positive control: nothing written before the first cycle"

        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        first = json.loads(target.read_text())
        assert first["snapshot_at_ns"] == clock.now
        assert [s["venue"] for s in first["sites"]] == [VENUE]
        # Taken at the TOP of cycle 1, i.e. before this poll's own success.
        assert first["sites"][0]["gate_state"] == GateState.BLOCKED.value
        assert first["sites"][0]["gate_reason"] == GateReason.NEVER_POLLED.value
        assert first["sites"][0]["last_successful_poll_ns"] is None

        raw = target.read_text()
        assert str(settings.state_db_path) not in raw
        assert str(settings.catalog_base) not in raw

        # Cycle 2 REWRITES it, now carrying cycle 1's success.
        clock.advance(60 * 1_000_000_000)
        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()

        second = json.loads(target.read_text())
        assert second["snapshot_at_ns"] == clock.now
        assert second["sites"][0]["gate_state"] == GateState.OPEN.value
        assert second["sites"][0]["last_successful_poll_ns"] is not None
        assert second["sites"][0]["cursor"], "the resume cursor must be rendered"

        # Cycle 3 tracks a gate state that changed between cycles.
        clock.advance(60 * 1_000_000_000)
        runtime.shared.gate.record_parser_failure(VENUE, CITY, detail="deliberate")
        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()

        third = json.loads(target.read_text())
        assert third["snapshot_at_ns"] == clock.now
        assert third["sites"][0]["gate_state"] == GateState.BLOCKED.value
        assert oct(target.stat().st_mode & 0o777) == oct(0o600)


@pytest.mark.asyncio
async def test_a_never_polled_site_raises_no_site_blocked_alert_at_boot(
    settings: Any,  # noqa: F811
) -> None:
    """A cold site is `BLOCKED/never_polled` with `at_ns == 0`, so measuring
    "blocked for >= N intervals" from `GateStatus.at_ns` reads the whole Unix
    epoch as downtime and pages CRITICAL on every fresh deployment.

    Boot state is not a fault at the instant of boot. Duration is therefore
    measured from when this process first OBSERVED the block, which also fixes
    a second defect the same arithmetic had: `at_ns` is the LAST TRANSITION
    instant, and `check_staleness` re-records one every cycle, so a
    permanently blocked site would have reset its own timer forever and never
    alerted at all.

    The negative control is the second half: a block that PERSISTS across
    cycles does alert once it ages past the threshold, so this is a corrected
    measurement rather than a silenced condition.
    """
    clock = FakeClock()
    sink = RecordingSink()

    with process_cycle(settings, clock) as (runtime, actor):
        actor.alert_sink = sink
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()

        snapshot = actor.last_health_snapshot
        assert snapshot is not None
        # Positive control: the condition really WAS evaluated against a
        # never-polled, BLOCKED site -- so "no alert" is not vacuous.
        assert snapshot.sites[0].gate_state == GateState.BLOCKED.value
        assert snapshot.sites[0].gate_reason == GateReason.NEVER_POLLED.value
        assert [p for p in sink.payloads if p.event == "site_blocked"] == []

        # Negative control: a block that PERSISTS across cycles (the UA-trap
        # latch also stops the poll that would otherwise clear it) does fire
        # once it has been observed for longer than the threshold.
        runtime.shared.gate.record_forbidden_403(
            VENUE, CITY, detail="test", cross_site_burst_detected=True
        )
        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()  # first OBSERVATION of the block
        assert [p for p in sink.payloads if p.event == "site_blocked"] == [], (
            "a freshly observed block must not alert before the threshold"
        )

        clock.advance(int(settings.poll_interval_seconds) * 5 * 1_000_000_000)
        with respx.mock(assert_all_called=False) as mock:
            mock_not_modified(mock)
            await actor.poll_once()

        assert [p for p in sink.payloads if p.event == "site_blocked"], (
            "the detector must fire for a block that persisted past the threshold"
        )


# ---------------------------------------------------------------------------
# 5. Thread confinement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_gap_ledger_store_touch_ever_leaves_the_loop_thread(
    settings: Any,  # noqa: F811
) -> None:
    """`reconcile` WRITES to the thread-confined `SqliteStateStore`, so it must
    run ON the loop thread -- only the catalog read may go through
    `_run_off_loop`. Getting this backwards crashes only in the real process.

    Three assertions, and the third is what makes the first two mean anything:

    * every recorded `gaps:` touch is on the loop thread;
    * `gaps:` keys really were touched (positive control -- otherwise "no
      off-thread touch" is satisfied by touching nothing);
    * the detector DEMONSTRABLY catches a breach, shown by driving one
      deliberately through the same `_run_off_loop` seam.
    """
    clock = FakeClock()
    touches: list[tuple[str, str, int]] = []

    def factory(path: Path) -> ThreadRecordingStore:
        return ThreadRecordingStore(path, touches)

    loop_thread = threading.get_ident()

    with process_cycle(settings, clock, store_factory=factory) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        gap_touches = [t for t in touches if t[1].startswith(gaps.GAP_KEY_PREFIX)]
        assert gap_touches, "positive control: the ledger must have been written"
        off_thread = [t for t in gap_touches if t[2] != loop_thread]
        assert off_thread == [], f"the gap ledger was touched off the loop thread: {off_thread}"

        # Negative control: the same store, through the same `_run_off_loop`
        # seam the poll uses for the catalog read, is both RECORDED off-thread
        # and REJECTED by the store itself.
        mark = len(touches)
        with pytest.raises(RuntimeError, match="different thread"):
            await actor._run_off_loop(lambda: runtime.store.get(gaps.GAP_KEY_PREFIX + "probe"))
        assert touches[mark:], "the negative control recorded nothing"
        assert all(t[2] != loop_thread for t in touches[mark:])


# ---------------------------------------------------------------------------
# 6. The climate-day derivation exists exactly once
# ---------------------------------------------------------------------------


def test_the_actor_has_no_private_climate_day_derivation() -> None:
    """`gaps.most_recent_completed_climate_day` was extracted byte-for-byte
    from the actor's own private copy. Two copies of the fixed-standard-offset
    -vs-DST arithmetic is exactly the divergence that silently fabricates or
    hides gaps, so the private one must be gone rather than merely equivalent.
    """
    assert not hasattr(NwsIngestActor, "_most_recent_completed_climate_day")
