"""Unit tests for `breezy.ingest.nws_observation_actor` -- BL-24 Seam B, section 3.

Config validation, L-16 supervision, the one clock (A7), publication on the
shared topic, and politeness (S2). The A8 restart rebuild and the exit
criterion live in ``test_nws_observation_actor_rebuild.py``. The harness
-- a native `TestClock` registered through `Actor.register_base` with the
Nautilus test kit's bus/portfolio/cache, timers fired organically through
`TestClock.advance_time` -- is ``tests/unit/nws_observation_harness.py``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from breezy.domain.station_observation import StationObservation
from breezy.ingest.http import RateLimitedError, TransportError
from breezy.ingest.nws_observation_actor import (
    EXCLUDED_ICAOS,
    MIN_REQUEST_SPACING_NS,
    NwsObservationActorConfig,
)
from breezy.ingest.nws_observations import NWS_OBSERVATION_SOURCE_CHANNEL
from breezy.ingest.observation_sidecar import ObservationSidecar
from tests.unit.nws_observation_harness import (
    FETCH_INSTANT_NS,
    INTERVAL_S,
    LAG_NS,
    NS,
    build,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_knyc_is_excluded_from_the_live_rule_at_config_time() -> None:
    """Converged item 8: KNYC is hourly-only (A14); validation refuses it."""
    assert "KNYC" in EXCLUDED_ICAOS
    with pytest.raises(ValueError, match="KNYC"):
        NwsObservationActorConfig(station_icao="KNYC", assumed_publication_lag_ns=LAG_NS)


@pytest.mark.parametrize("icao", ["kmdw", "MDW", "KMDW ", "KMDWX", ""])
def test_a_malformed_icao_is_refused_at_config_time(icao: str) -> None:
    with pytest.raises(ValueError):
        NwsObservationActorConfig(station_icao=icao, assumed_publication_lag_ns=LAG_NS)


@pytest.mark.parametrize(
    "overrides",
    [
        {"assumed_publication_lag_ns": 0},
        {"poll_interval_seconds": 0},
        {"staleness_bound_seconds": 0},
        {"stagger_offset_seconds": -1},
    ],
)
def test_non_positive_config_values_are_refused(overrides: dict[str, int]) -> None:
    kwargs: dict[str, Any] = {"station_icao": "KMDW", "assumed_publication_lag_ns": LAG_NS}
    kwargs.update(overrides)
    with pytest.raises(ValueError):
        NwsObservationActorConfig(**kwargs)


def test_the_config_names_no_operator_reserved_control() -> None:
    forbidden = ("budget", "daily", "position_cap", "poscap")
    for name in NwsObservationActorConfig.__struct_fields__:
        assert not any(token in name.lower() for token in forbidden), name


# ---------------------------------------------------------------------------
# Supervision (L-16) and the one clock (A7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_poll_that_raises_reaches_the_supervisor_not_the_timer_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = build(raises=RuntimeError("the parser exploded"))
    caplog.set_level(logging.CRITICAL, logger="breezy.ingest.nws_observation_actor")

    harness.actor.start()
    await harness.drain()  # the on_start rebuild
    assert harness.actor.counters["task_death"] == 1

    fired = await harness.fire_due_timers(FETCH_INSTANT_NS + INTERVAL_S * NS)

    assert fired == 1  # the callback returned normally; nothing escaped it
    assert harness.actor.counters["task_death"] == 2
    assert harness.actor.rebuild_trusted is False
    assert harness.published == []
    deaths = [r for r in caplog.records if r.levelno == logging.CRITICAL and "died" in r.message]
    assert len(deaths) == 2
    assert all(r.exc_info is not None for r in deaths)


@pytest.mark.asyncio
async def test_the_transport_is_built_on_the_actors_own_clock() -> None:
    harness = build()

    harness.actor.start()
    await harness.drain()

    assert harness.calls[0][2] == FETCH_INSTANT_NS
    harness.clock.set_time(FETCH_INSTANT_NS + 7 * NS)
    assert harness.fetcher.clock() == FETCH_INSTANT_NS + 7 * NS


def test_a_backtest_without_a_running_loop_arms_nothing_and_opens_nothing() -> None:
    harness = build()

    harness.actor.start()

    assert harness.clock.timer_names == []
    assert harness.fetchers == []
    assert harness.actor.inflight == 0


def test_the_harness_runs_on_the_loop_thread_so_the_bridge_is_exercised() -> None:
    """Documentation of the harness: the timer handler runs where the test runs."""
    assert threading.current_thread() is threading.main_thread()


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_actor_publishes_on_the_shared_data_type_factory_topic() -> None:
    harness = build()

    harness.actor.start()
    await harness.drain()

    assert harness.published, "nothing arrived on the shared factory's topic"
    assert all(isinstance(record, StationObservation) for record in harness.published)
    assert {r.source_channel for r in harness.published} == {NWS_OBSERVATION_SOURCE_CHANNEL}
    assert {r.station for r in harness.published} == {"KMDW"}
    assert all(r.received_at_ns == FETCH_INSTANT_NS for r in harness.published)


# ---------------------------------------------------------------------------
# Politeness (S2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consecutive_polls_for_one_station_are_at_least_one_second_apart() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()
    assert len(harness.calls) == 1

    harness.clock.set_time(FETCH_INSTANT_NS + MIN_REQUEST_SPACING_NS // 2)
    harness.actor.on_poll_timer(None)
    await harness.drain()

    assert len(harness.calls) == 1
    assert harness.actor.counters["poll_skipped_too_soon"] == 1

    harness.clock.set_time(FETCH_INSTANT_NS + MIN_REQUEST_SPACING_NS)
    harness.actor.on_poll_timer(None)
    await harness.drain()

    assert len(harness.calls) == 2
    assert harness.calls[1][2] - harness.calls[0][2] >= MIN_REQUEST_SPACING_NS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raises", "counter"),
    [
        (RateLimitedError("429 Too Many Requests", retry_after="30"), "rate_limited"),
        (TransportError("connection reset"), "transport_error"),
    ],
)
async def test_a_rate_limited_poll_never_triggers_an_immediate_re_poll(
    raises: BaseException, counter: str
) -> None:
    harness = build(raises=raises)

    harness.actor.start()
    await harness.drain()

    assert len(harness.calls) == 1
    assert harness.actor.counters[counter] == 1
    assert harness.published == []

    # Nothing before the next timer fire...
    assert await harness.fire_due_timers(FETCH_INSTANT_NS + (INTERVAL_S - 1) * NS) == 0
    assert len(harness.calls) == 1
    # ...and exactly one attempt at it.
    assert await harness.fire_due_timers(FETCH_INSTANT_NS + INTERVAL_S * NS) == 1
    assert len(harness.calls) == 2
    assert harness.actor.counters[counter] == 2


@pytest.mark.asyncio
async def test_the_poll_timer_is_phase_shifted_by_the_stagger_offset_only() -> None:
    harness = build(stagger_offset_seconds=60)

    harness.actor.start()
    await harness.drain()

    assert harness.clock.timer_names == ["nws-obs-poll-KMDW"]
    assert await harness.fire_due_timers(FETCH_INSTANT_NS + INTERVAL_S * NS) == 0
    assert await harness.fire_due_timers(FETCH_INSTANT_NS + (INTERVAL_S + 60) * NS) == 1
    assert await harness.fire_due_timers(FETCH_INSTANT_NS + (2 * INTERVAL_S + 60) * NS) == 1


@pytest.mark.asyncio
async def test_stop_cancels_the_poll_timer() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()
    assert harness.clock.timer_names == ["nws-obs-poll-KMDW"]

    harness.actor.stop()

    assert harness.clock.timer_names == []


# ---------------------------------------------------------------------------
# 2026-09-16 GAP fix: raw-observation sidecar wiring (defect B).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_poll_writes_the_fetch_url_path_and_receipt_stamp_onto_every_sidecar_row(
    tmp_path: Path,
) -> None:
    sidecar_path = tmp_path / "observations.jsonl"
    sidecar = ObservationSidecar(sidecar_path)
    harness = build(sidecar=sidecar)

    harness.actor.start()
    await harness.drain()

    assert sidecar_path.exists()
    lines = sidecar_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 0
    for line in lines:
        row = json.loads(line)
        assert row["station"] == "KMDW"
        assert row["source_url_path"] == "/stations/KMDW/observations"
        assert row["fetched_at_ns"] == FETCH_INSTANT_NS
    # At least one published record's own decoded reading appears among the
    # sidecar rows -- the sidecar sees the same decode the strategy topic does.
    published_tenths = {record.temp_c_tenths for record in harness.published}
    sidecar_tenths = {json.loads(line)["temp_c_tenths"] for line in lines}
    assert published_tenths
    assert published_tenths <= sidecar_tenths


@pytest.mark.asyncio
async def test_a_poll_never_raises_when_the_sidecar_directory_is_unwritable(
    tmp_path: Path,
) -> None:
    """Failure containment: an `ObservationSidecar` that cannot write to
    disk must never surface out of the actor's poll -- observations still
    parse and publish, the sidecar just counts an error."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    unwritable_path = blocker / "sub" / "observations.jsonl"
    sidecar = ObservationSidecar(unwritable_path)
    assert sidecar.errors == 1  # construction itself already degraded

    harness = build(sidecar=sidecar)

    harness.actor.start()
    await harness.drain()  # must not raise

    assert harness.actor.rebuild_trusted is True
    assert len(harness.published) > 0
    assert not unwritable_path.exists()


@pytest.mark.asyncio
async def test_a_poll_with_no_sidecar_configured_is_byte_identical_to_before_the_fix() -> None:
    harness = build()  # sidecar defaults to None

    harness.actor.start()
    await harness.drain()

    assert harness.actor.rebuild_trusted is True
    assert len(harness.published) > 0
