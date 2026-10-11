"""EXEC-PAR BG-2: the watcher writes the K-forced amendment on first observation.

The exec client is byte-pinned, so the bucket guard's ``force_k1`` is observed from
outside through ``ExecClientView.k_forced_to_1_reason``. Only the K>1 breaker watcher
does so; the K=1 alert-only watcher must stay write-free.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.breaker_watcher import (
    BreakerWatcherActor,
    ExecRefusalAlertActor,
    build_exec_watcher,
)
from breezy.runtime.exec_par_epochs import K_FORCED_NOTE_PREFIX
from breezy.runtime.exec_par_records import Amendment
from breezy.runtime.health import AlertPayload

SEC = 1_000_000_000
NOW = 1_700_000_000 * SEC


class _Sink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)


@dataclass
class _Client:
    k_forced_to_1_reason: str | None = None
    contradiction_events_total: int = 0
    duplicate_suspect_total: int = 0
    ambiguous_notional_breaker_tripped: bool = False
    resolver_last_pass_ns: int = NOW
    open_intent_ages: tuple[tuple[str, str, int], ...] = ()
    held_position_slugs: tuple[str, ...] = ()
    unreadable_slot_keys: tuple[str, ...] = ()
    stuck_refusals_after_settle_failure_total: int = 0
    no_fill_retire_refusals_total: int = 0


class _Latch:
    """Breaker port plus the amendment writer."""

    def __init__(self, *, fail_amendments: int = 0) -> None:
        self.amendments: list[Amendment] = []
        self.heartbeats: list[int] = []
        self.fail_amendments = fail_amendments

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        self.heartbeats.append(hb_ns)

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        raise AssertionError("no halt expected")

    def write_amendment(self, record: Amendment) -> None:
        if self.fail_amendments > 0:
            self.fail_amendments -= 1
            raise OSError("store down")
        self.amendments.append(record)


def _register(actor: Actor) -> None:
    clock = TestClock()
    clock.set_time(NOW)
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )


def _watcher(
    client: _Client, latch: _Latch, *, commit_sha: str | None = "abc123"
) -> ExecRefusalAlertActor:
    actor = build_exec_watcher(2, latch=latch, alert_sink=_Sink(), commit_sha=commit_sha)
    _register(actor)
    assert isinstance(actor, BreakerWatcherActor)
    actor.bind_client(lambda: client)
    return actor


@pytest.mark.asyncio
async def test_forced_reason_writes_one_amendment_with_the_commit_sha() -> None:
    latch = _Latch()
    actor = _watcher(_Client(k_forced_to_1_reason="bucket_label_above_frozen"), latch)

    assert await actor.tick() is True

    assert latch.amendments == [
        Amendment(NOW, "abc123", K_FORCED_NOTE_PREFIX + "bucket_label_above_frozen")
    ]


@pytest.mark.asyncio
async def test_later_ticks_do_not_rewrite_the_amendment() -> None:
    latch = _Latch()
    actor = _watcher(_Client(k_forced_to_1_reason="r"), latch)

    for _ in range(3):
        await actor.tick()

    assert len(latch.amendments) == 1


@pytest.mark.asyncio
async def test_no_forced_reason_writes_no_amendment() -> None:
    latch = _Latch()
    actor = _watcher(_Client(), latch)

    await actor.tick()

    assert latch.amendments == []


@pytest.mark.asyncio
async def test_a_failed_amendment_write_is_retried_and_withholds_the_heartbeat() -> None:
    latch = _Latch(fail_amendments=1)
    actor = _watcher(_Client(k_forced_to_1_reason="r"), latch)

    assert await actor.tick() is False
    assert latch.heartbeats == []
    assert await actor.tick() is True

    assert len(latch.amendments) == 1


@pytest.mark.asyncio
async def test_k1_watcher_never_writes_an_amendment() -> None:
    latch = _Latch()
    actor = build_exec_watcher(1, latch=latch, alert_sink=_Sink(), commit_sha="abc123")
    _register(actor)
    actor.bind_client(lambda: _Client(k_forced_to_1_reason="r"))

    assert await actor.tick() is True

    assert latch.amendments == []
    assert not isinstance(actor, BreakerWatcherActor)


@pytest.mark.asyncio
async def test_without_a_commit_sha_the_k_gt_1_watcher_writes_no_amendment() -> None:
    latch = _Latch()
    actor = _watcher(_Client(k_forced_to_1_reason="r"), latch, commit_sha=None)

    assert await actor.tick() is True

    assert latch.amendments == []
