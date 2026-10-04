"""AUT-1 WP4, FQ side: what `nbp_feed_freshness` reads from `missed_cycles(now)`.

FQ's NODE_LOCAL detector (plan r12 §3.7.2) maps the actor's `missed_cycles`
count to its outcome: exactly 1 alerts only, 2 or more vetoes `feed_stale`,
and a newer complete cycle clears. The detector class itself
(`capture_adapter.py`) is WP2/WP7 and does not exist yet, so these tests pin
the count it reads, through the actor's public API only, against the real
fixture bulletin. The detector-level veto cases wait for that module.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.ingest.nbm_quantile_actor import (
    DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS,
    NbmQuantileActor,
    NbmQuantileActorConfig,
)
from breezy.ingest.nbm_quantile_transport import NbmQuantileFetchResult

NS = 1_000_000_000
HOUR_NS = 3_600 * NS
DEADLINE_NS = DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS * NS
CYCLE_13Z = int(dt.datetime(2026, 9, 28, 13, tzinfo=dt.UTC).timestamp()) * NS
CYCLE_19Z = CYCLE_13Z + 6 * HOUR_NS
CYCLE_01Z = CYCLE_13Z + 12 * HOUR_NS
FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "nbm" / "nbptx_t13z_excerpt.txt"
).read_text(encoding="utf-8")


def _rfc2822(instant_ns: int) -> str:
    instant = dt.datetime.fromtimestamp(instant_ns / NS, tz=dt.UTC)
    return instant.strftime("%a, %d %b %Y %H:%M:%S GMT")


class _Feed:
    """A scripted transport: `text` for the bulletin, answered at the clock's time."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self.clock = clock
        self.text = FIXTURE

    async def fetch_nbp_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int
    ) -> NbmQuantileFetchResult:
        cycle_ns = (
            int(
                dt.datetime(
                    cycle_date.year, cycle_date.month, cycle_date.day, cycle_hour, tzinfo=dt.UTC
                ).timestamp()
            )
            * NS
        )
        return NbmQuantileFetchResult(
            text=self.text,
            source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
            last_modified=_rfc2822(cycle_ns + 65 * 60 * NS),
            fetched_at_ns=self.clock(),
            raw_sha256="0" * 64,
            raw_bytes=len(self.text),
        )


async def _drain(actor: NbmQuantileActor) -> None:
    import asyncio

    for _ in range(5_000):
        if actor.inflight == 0:
            return
        await asyncio.sleep(0)
    raise AssertionError("actor still has work in flight")


def _actor(feed_holder: list[_Feed], clock: TestClock) -> NbmQuantileActor:
    def factory(clock_fn: Callable[[], int]) -> _Feed:
        feed = _Feed(clock_fn)
        feed_holder.append(feed)
        return feed

    actor = NbmQuantileActor(
        NbmQuantileActorConfig(station_icaos=("KLAX", "KMDW", "KMIA", "KSFO")),
        transport_factory=factory,
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    return actor


async def _started_with_13z_complete() -> tuple[NbmQuantileActor, TestClock, list[_Feed]]:
    clock = TestClock()
    clock.set_time(CYCLE_13Z + 65 * 60 * NS + 60 * NS)
    feeds: list[_Feed] = []
    actor = _actor(feeds, clock)
    actor.start()
    await _drain(actor)
    return actor, clock, feeds


@pytest.mark.asyncio
async def test_one_missed_cycle_is_exactly_one_alert_only_count() -> None:
    actor, _, _ = await _started_with_13z_complete()

    assert actor.missed_cycles(CYCLE_19Z + DEADLINE_NS - 1) == 0
    assert actor.missed_cycles(CYCLE_19Z + DEADLINE_NS) == 1
    assert actor.missed_cycles(CYCLE_01Z + DEADLINE_NS - 1) == 1


@pytest.mark.asyncio
async def test_two_missed_cycles_reach_the_veto_threshold() -> None:
    actor, _, _ = await _started_with_13z_complete()

    assert actor.missed_cycles(CYCLE_01Z + DEADLINE_NS) == 2
    assert actor.missed_cycles(CYCLE_01Z + DEADLINE_NS) >= 2


@pytest.mark.asyncio
async def test_bulletin_drift_counts_as_missed_cycle() -> None:
    clock = TestClock()
    clock.set_time(CYCLE_13Z + 65 * 60 * NS + 60 * NS)

    def factory(clock_fn: Callable[[], int]) -> _Feed:
        feed = _Feed(clock_fn)
        feed.text = "not an NBP bulletin at all\n"
        return feed

    actor = NbmQuantileActor(
        NbmQuantileActorConfig(station_icaos=("KLAX",)), transport_factory=factory
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.start()
    await _drain(actor)

    assert actor.counters["bulletin_drift"] == 1
    assert actor.missed_cycles(CYCLE_13Z + DEADLINE_NS - 1) == 0
    assert actor.missed_cycles(CYCLE_13Z + DEADLINE_NS) == 1, "the drifted cycle never completed"


@pytest.mark.asyncio
async def test_missed_count_clears_on_newer_complete_cycle() -> None:
    actor, clock, _ = await _started_with_13z_complete()
    now = CYCLE_01Z + DEADLINE_NS
    assert actor.missed_cycles(now) == 2

    clock.set_time(CYCLE_01Z + 65 * 60 * NS + 60 * NS)
    actor.on_cycle_timer(event=object())
    await _drain(actor)

    assert actor.missed_cycles(now) == 0
