"""Persistent `_emit_health` failure must reach an operator (2026-10-02).

`reconcile_and_report` swallows every non-Timeout failure from
`_emit_health`. Swallowed once is containment; swallowed every poll is the
"detector without delivery" failure class (docs/core/LESSONS.md), so N
consecutive failures escalate through the alert sink DIRECTLY -- never through
`health_io`, which is the thing that is failing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest import nws_actor as nws_actor_module
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.registry.health_model import HEALTH_EMISSION_FAILING, AlertPayload
from breezy.registry.sites import default_registry
from tests.unit.test_ingest_nws_actor import (
    ALL_SITES,
    CITY,
    VENUE,
    FakeClock,
    _local_probe,
    build_actor,
    durable_store_pair,
)

ACTOR_LOGGER = "breezy.ingest.nws_actor"
MARKER = "NWS_HEALTH_EMISSION_FAILING"
SITE_LABEL = f"{VENUE}/{CITY}"
THRESHOLD = nws_actor_module.HEALTH_EMISSION_FAILURE_ESCALATION_THRESHOLD


class RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class RaisingSink:
    def emit(self, payload: AlertPayload) -> None:
        raise OSError("sink down")


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
    instance.alert_sink = RecordingSink()
    try:
        yield instance
    finally:
        instance.shutdown_executor()


def _set_emission(actor: NwsIngestActor, *, failing: bool) -> None:
    async def _emit(*_args: Any, **_kwargs: Any) -> None:
        if failing:
            raise AttributeError("broken health_io")

    actor._emit_health = _emit  # type: ignore[method-assign]


def _sink(actor: NwsIngestActor) -> RecordingSink:
    sink = actor.alert_sink
    assert isinstance(sink, RecordingSink)
    return sink


def _marker_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if MARKER in r.getMessage()]


@pytest.mark.asyncio
async def test_below_threshold_failures_do_not_escalate(
    actor: NwsIngestActor, caplog: pytest.LogCaptureFixture
) -> None:
    _set_emission(actor, failing=True)
    with caplog.at_level(logging.INFO, logger=ACTOR_LOGGER):
        for _ in range(THRESHOLD - 1):
            await actor.reconcile_and_report()
    assert _sink(actor).payloads == []
    assert _marker_records(caplog) == []


@pytest.mark.asyncio
async def test_threshold_failures_escalate_exactly_once(
    actor: NwsIngestActor, caplog: pytest.LogCaptureFixture
) -> None:
    _set_emission(actor, failing=True)
    with caplog.at_level(logging.INFO, logger=ACTOR_LOGGER):
        for _ in range(THRESHOLD):
            await actor.reconcile_and_report()
    payloads = _sink(actor).payloads
    assert len(payloads) == 1
    assert payloads[0].event == HEALTH_EMISSION_FAILING
    assert payloads[0].severity == "CRITICAL"
    assert payloads[0].site == SITE_LABEL
    records = _marker_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.CRITICAL


@pytest.mark.asyncio
async def test_continued_failure_inside_renotify_window_does_not_duplicate(
    actor: NwsIngestActor,
) -> None:
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD * 3):
        await actor.reconcile_and_report()
    assert len(_sink(actor).payloads) == 1


@pytest.mark.asyncio
async def test_failure_past_renotify_interval_re_escalates_once(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    clock = shared.clock
    assert isinstance(clock, FakeClock)
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD):
        await actor.reconcile_and_report()
    clock.advance(nws_actor_module.HEALTH_EMISSION_RENOTIFY_AFTER_NS + 1)
    await actor.reconcile_and_report()
    await actor.reconcile_and_report()
    assert len(_sink(actor).payloads) == 2


@pytest.mark.asyncio
async def test_success_resets_counter_and_logs_recovery_once(
    actor: NwsIngestActor, caplog: pytest.LogCaptureFixture
) -> None:
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD - 1):
        await actor.reconcile_and_report()
    _set_emission(actor, failing=False)
    with caplog.at_level(logging.INFO, logger=ACTOR_LOGGER):
        await actor.reconcile_and_report()
        await actor.reconcile_and_report()
    # Counter reset: THRESHOLD-1 more failures still do not escalate.
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD - 1):
        await actor.reconcile_and_report()
    assert _sink(actor).payloads == []
    assert not [r for r in caplog.records if "recovered" in r.getMessage()]


@pytest.mark.asyncio
async def test_recovery_after_escalation_is_logged_once_and_rearms(
    actor: NwsIngestActor, caplog: pytest.LogCaptureFixture
) -> None:
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD):
        await actor.reconcile_and_report()
    _set_emission(actor, failing=False)
    with caplog.at_level(logging.INFO, logger=ACTOR_LOGGER):
        await actor.reconcile_and_report()
        await actor.reconcile_and_report()
    recovered = [r for r in caplog.records if MARKER in r.getMessage() and "recovered" in r.getMessage()]
    assert len(recovered) == 1
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD):
        await actor.reconcile_and_report()
    assert len(_sink(actor).payloads) == 2


@pytest.mark.asyncio
async def test_a_raising_sink_never_escapes_reconcile_and_report(
    actor: NwsIngestActor, caplog: pytest.LogCaptureFixture
) -> None:
    actor.alert_sink = RaisingSink()
    _set_emission(actor, failing=True)
    with caplog.at_level(logging.INFO, logger=ACTOR_LOGGER):
        for _ in range(THRESHOLD + 1):
            await actor.reconcile_and_report()  # must not raise
    assert any(
        MARKER in r.getMessage() and r.levelno == logging.CRITICAL for r in caplog.records
    )


@pytest.mark.asyncio
async def test_escalation_does_not_go_through_health_io(actor: NwsIngestActor) -> None:
    class ExplodingHealthIO:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"escalation touched health_io.{name}")

    actor.health_io = ExplodingHealthIO()
    _set_emission(actor, failing=True)
    for _ in range(THRESHOLD):
        await actor.reconcile_and_report()
    assert len(_sink(actor).payloads) == 1
