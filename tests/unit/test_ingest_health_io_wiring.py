"""R1.5b C2: the NWS ingest actor receives its health I/O by injection.

``breezy.ingest`` sits below ``breezy.runtime`` in the layered contract, so the
actor can no longer import ``runtime.health`` (the old call-time ``_health()``
hop and its ``ignore_imports`` debt row are gone). Composition injects the
``runtime.health`` module as ``health_io``. The danger is a silent wiring
bug -- "alerts reach nobody" -- so every pin below is checked against a real
mutation, and the live boot refuses a miswired actor.
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import logging
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.ingest import gaps
from breezy.ingest.gate import GateReason, GateState, GateStatus
from breezy.ingest.nws_actor import LEDGER_DETAIL_MAX_CHARS, NwsIngestActor, _scrub_failure_detail
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.registry.health_model import (
    MAX_ALERT_DETAIL_CHARS,
    AlertPayload,
    AlertSink,
    GapSummary,
    HealthSnapshot,
)
from breezy.runtime import health
from breezy.runtime.composition import BreezyIngestRuntime, build_ingest_actors, ingest_runtime
from breezy.runtime.settings import BreezyRuntimeSettings

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
NWS_ACTOR_PATH: Final[Path] = REPO_ROOT / "src" / "breezy" / "ingest" / "nws_actor.py"
SITES: Final[tuple[tuple[str, str], ...]] = (("polymarket_us", "NYC"), ("polymarket_us", "SFO"))
ACTOR_LOGGER: Final[str] = "breezy.ingest.nws_actor"
ABSOLUTE_PATH_RE: Final[re.Pattern[str]] = re.compile(r"(^|[\s(=])/\S")


def _local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


class RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class RecordingHealthIO:
    """Delegates to the real ``runtime.health`` module and records the calls."""

    def __init__(self) -> None:
        self.emitted: list[tuple[AlertSink, AlertPayload]] = []

    def emit_alert(self, sink: AlertSink, payload: AlertPayload) -> None:
        self.emitted.append((sink, payload))
        health.emit_alert(sink, payload)

    def write_snapshot_atomic(self, path: Path, snapshot: HealthSnapshot) -> None:
        health.write_snapshot_atomic(path, snapshot)

    def resolve_alert_sink(self, env: Any = None) -> AlertSink:
        return health.resolve_alert_sink(env)

    def new_alert_state(self) -> Any:
        return health.new_alert_state()


class SnapshotRaisingHealthIO(RecordingHealthIO):
    def write_snapshot_atomic(self, path: Path, snapshot: HealthSnapshot) -> None:
        raise OSError("disk exploded")


def _settings(tmp_path: Path, *, snapshot_dir: Path | None) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=SITES,
        catalog_base=tmp_path / "catalog",
        state_db_path=tmp_path / "state" / "breezy.sqlite3",
        poll_interval_seconds=300,
        parse_timeout_ms=250,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
        health_snapshot_dir=snapshot_dir,
    )


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def runtime(tmp_path: Path, sink: RecordingSink) -> Iterator[BreezyIngestRuntime]:
    settings = _settings(tmp_path, snapshot_dir=tmp_path / "health")
    with ingest_runtime(settings, probe=_local_probe, alert_sink_factory=lambda: sink) as rt:
        yield rt


def _shutdown(actors: Sequence[NwsIngestActor]) -> None:
    for actor in actors:
        actor.shutdown_executor()


def _register(actor: NwsIngestActor) -> None:
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestClock(),
    )


# --------------------------------------------------------------------------
# Composition wiring
# --------------------------------------------------------------------------


def test_composition_wires_the_health_io_and_the_composed_sink(
    runtime: BreezyIngestRuntime, sink: RecordingSink
) -> None:
    actors = build_ingest_actors(runtime)
    try:
        assert len(actors) == len(SITES)
        for actor in actors:
            assert actor.health_io is health
            assert actor.alert_sink is sink
            assert actor.health_snapshot_path is not None
    finally:
        _shutdown(actors)


def test_composition_wires_health_io_even_without_a_snapshot_dir(
    tmp_path: Path, sink: RecordingSink
) -> None:
    """The snapshot directory is optional in production (unset -> no file), so
    it must never be part of the boot guard -- but ``health_io`` is always set."""
    settings = _settings(tmp_path, snapshot_dir=None)
    with ingest_runtime(settings, probe=_local_probe, alert_sink_factory=lambda: sink) as rt:
        actors = build_ingest_actors(rt)
        try:
            for actor in actors:
                assert actor.health_io is health
                assert actor.alert_sink is sink
                assert actor.health_snapshot_path is None
        finally:
            _shutdown(actors)


# --------------------------------------------------------------------------
# Fail-closed boot guard
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["health_io", "alert_sink"])
async def test_live_on_start_refuses_a_miswired_actor(
    runtime: BreezyIngestRuntime, missing: str
) -> None:
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        setattr(actor, missing, None)
        with pytest.raises(RuntimeError, match=missing):
            actor.on_start()
        assert actor._loop is not None
    finally:
        _shutdown(actors)


@pytest.mark.asyncio
async def test_live_on_start_accepts_a_fully_wired_actor_without_a_snapshot_path(
    runtime: BreezyIngestRuntime,
) -> None:
    """Today's production configuration (snapshot dir optional) must boot."""
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor.health_snapshot_path = None
        actor.on_start()  # must not raise
        actor.on_stop()
        await asyncio.sleep(0)
    finally:
        _shutdown(actors)


def test_backtest_on_start_does_not_require_health_io(runtime: BreezyIngestRuntime) -> None:
    """No running loop = backtest: no polling armed, so nothing to wire."""
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor.health_io = None
        actor.alert_sink = None
        actor.on_start()  # must not raise
        assert actor._loop is None
    finally:
        _shutdown(actors)


@pytest.mark.asyncio
async def test_an_unwired_health_io_names_the_missing_wiring_at_poll_time(
    runtime: BreezyIngestRuntime,
) -> None:
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor.health_io = None
        with pytest.raises(RuntimeError, match="health_io"):
            await actor._emit_health(1, entries=(), revisions=())
    finally:
        _shutdown(actors)


# --------------------------------------------------------------------------
# Real dispatch path and failure observability
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_forced_alert_reaches_the_sink_through_health_io(
    runtime: BreezyIngestRuntime, sink: RecordingSink
) -> None:
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        recorder = RecordingHealthIO()
        actor.health_io = recorder
        actor._ledger_failure_detail = "TamperedGapLedgerError"

        await actor._emit_health(1, entries=(), revisions=())

        assert [payload.event for _, payload in recorder.emitted] == ["ledger_unavailable"]
        assert recorder.emitted[0][0] is sink
        assert [payload.event for payload in sink.payloads] == ["ledger_unavailable"]
        assert sink.payloads[0].severity == "CRITICAL"
        assert sink.payloads[0].site == "polymarket_us/NYC"
    finally:
        _shutdown(actors)


@pytest.mark.asyncio
async def test_a_failing_snapshot_write_is_logged_not_silent(
    runtime: BreezyIngestRuntime, caplog: pytest.LogCaptureFixture
) -> None:
    """Pins today's behaviour: ``reconcile_and_report`` swallows a health I/O
    failure but logs it at ERROR under the actor's logger. If this ever goes
    quiet, alerts and snapshots fail with nobody told."""
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        _register(actor)
        actor.health_io = SnapshotRaisingHealthIO()

        with caplog.at_level(logging.ERROR, logger=ACTOR_LOGGER):
            await actor.reconcile_and_report()  # must not raise

        records = [
            r
            for r in caplog.records
            if r.name == ACTOR_LOGGER and "health emission failed" in r.getMessage()
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert records[0].exc_info is not None
        assert "polymarket_us/NYC" in records[0].getMessage()
    finally:
        _shutdown(actors)


def test_new_alert_state_is_a_fresh_cold_start_tracker_each_call() -> None:
    first = health.new_alert_state()
    second = health.new_alert_state()
    assert isinstance(first, health.AlertState)
    assert first is not second


def test_alert_detail_templates_are_bounded_and_path_free(
    runtime: BreezyIngestRuntime,
) -> None:
    actors = build_ingest_actors(runtime)
    try:
        actor = actors[0]
        ledger_exc = TamperedLedgerError(
            "row at /home/jon/state/breezy.sqlite3 for jon@example.com " + "x" * 300
        )
        actor._ledger_failure_detail = _scrub_failure_detail(ledger_exc)
        actor._unreadable_field_streak = 10_000
        status = GateStatus(
            venue="polymarket_us",
            city="NYC",
            state=GateState.BLOCKED,
            reason=GateReason.UA_TRAP_403,
            detail="x",
            at_ns=1,
            last_successful_poll_ns=1,
        )
        causes = [
            GateReason.UA_TRAP_403,
            GateReason.STATE_STORE_TAMPERED,
            GateReason.FINAL_CLI_OVERDUE,
        ]
        summaries = [GapSummary("2026-09-01", "ACKNOWLEDGED_LOST", "critical", 123456)]
        revisions = [
            gaps.RevisionEvent(
                venue="polymarket_us",
                city="NYC",
                climate_day=dt.date(2026, 9, 1),
                previous_revision_seq=123456,
                new_revision_seq=123457,
                correction_flag=True,
                is_superseded=True,
            )
        ]
        conditions = actor._alert_conditions(
            10**18,
            site_label="polymarket_us/NYC",
            status=status,
            causes=causes,
            ua_latched=True,
            entries=(),
            summaries=summaries,
            revisions=revisions,
        )

        events = {condition.event for condition in conditions}
        assert events == {
            "ua_trap_latched",
            "site_blocked",
            "final_overdue",
            "poll_stale",
            "ledger_unavailable",
            "chronic_unreadable_product",
            "gap_retention_warning",
            "post_settlement_revision",
        }
        assert (
            len(actor._ledger_failure_detail)
            <= len(ledger_exc.__class__.__name__) + 2 + LEDGER_DETAIL_MAX_CHARS + 3
        )
        for condition in conditions:
            payload = AlertPayload(
                severity=condition.severity,
                event=condition.event,
                site=condition.key.site,
                detail=condition.detail,
            )
            assert (
                len(condition.detail) <= MAX_ALERT_DETAIL_CHARS
                or condition.event == "ledger_unavailable"
            ), condition.event
            assert len(payload.detail) <= MAX_ALERT_DETAIL_CHARS
            assert not ABSOLUTE_PATH_RE.search(condition.detail), condition.detail
            assert "@" not in condition.detail, condition.detail
    finally:
        _shutdown(actors)


class TamperedLedgerError(Exception):
    """Stand-in with the same shape of class name the ledger raises."""


# --------------------------------------------------------------------------
# Layering
# --------------------------------------------------------------------------


def test_nws_actor_has_no_runtime_import_anywhere() -> None:
    tree = ast.parse(NWS_ACTOR_PATH.read_text(encoding="utf-8"))
    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("breezy.runtime"):
            offending.append(f"line {node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.ImportFrom) and node.module == "breezy":
            offending.extend(
                f"line {node.lineno}: from breezy import {alias.name}"
                for alias in node.names
                if alias.name == "runtime"
            )
        elif isinstance(node, ast.Import):
            offending.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.startswith("breezy.runtime")
            )
    assert offending == []
