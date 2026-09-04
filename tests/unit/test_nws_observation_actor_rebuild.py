"""A8 restart rebuild and the Seam B exit criterion for `NwsObservationActor`.

Harness and fixture facts: ``tests/unit/nws_observation_harness.py``
(fixture fetched 2026-09-04T02:34:57Z; local-standard midnight
2026-09-03T06:00:00Z). Every payload below is the recording with rows
REMOVED -- never a row added or a value changed (L-17).
"""

from __future__ import annotations

import logging

import pytest

from breezy.domain.temperature import round_half_up_f
from breezy.ingest.nws_observation_rebuild import (
    MAX_OBSERVATION_LIMIT,
    observation_fetch_limit,
)
from breezy.strategy.weather_common.refusals import (
    OBSERVATION_AMBIGUOUS,
    OBSERVATION_UNAVAILABLE,
    observation_refusal,
)
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator
from tests.unit.nws_observation_harness import (
    BOUND_NS,
    FETCH_INSTANT_NS,
    FIXTURE_ROWS,
    FIXTURE_TEXT,
    INTERVAL_S,
    MDW_STD_OFFSET_HOURS,
    MIDNIGHT_NS,
    NS,
    build,
    expected_rebuild_rows,
    payload_text,
    row_ns,
    rows_observed_at_or_before,
)


@pytest.mark.asyncio
async def test_a_rebuild_with_a_gap_over_the_bound_publishes_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rows REMOVED from the recording (never added): a one-hour hole mid-day."""
    hole_start = MIDNIGHT_NS + 3 * 3_600 * NS
    hole_end = hole_start + 3_600 * NS
    holed = [row for row in FIXTURE_ROWS if not (hole_start <= row_ns(row) < hole_end)]
    assert len(holed) < len(FIXTURE_ROWS)
    harness = build(texts=(payload_text(holed),))
    caplog.set_level(logging.CRITICAL, logger="breezy.ingest.nws_observation_actor")

    harness.actor.start()
    await harness.drain()

    assert harness.published == []
    assert harness.actor.rebuild_trusted is False
    assert harness.actor.counters["rebuild_untrusted"] == 1
    assert any(r.levelno == logging.CRITICAL and "untrusted" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_a_rebuild_covering_local_standard_midnight_publishes_every_row() -> None:
    harness = build()

    harness.actor.start()
    await harness.drain()

    expected = expected_rebuild_rows()
    got = [(r.observed_at_ns, r.temp_c_tenths) for r in harness.published]
    assert got == expected
    assert got == sorted(got)  # ascending, so the accumulator's day-reset sees midnight first
    assert min(o for o, _ in got) >= MIDNIGHT_NS
    assert harness.actor.rebuild_trusted is True
    assert harness.actor.counters["rebuild_untrusted"] == 0
    # The first attempt used the brief's bounded limit, not the ceiling.
    elapsed_s = (FETCH_INSTANT_NS - MIDNIGHT_NS) // NS
    assert harness.calls == [("KMDW", observation_fetch_limit(elapsed_s), FETCH_INSTANT_NS)]


@pytest.mark.asyncio
async def test_a_rebuild_that_does_not_reach_midnight_escalates_to_the_api_ceiling() -> None:
    """A short response whose oldest row is after midnight+bound: withhold, then ask for 500."""
    newest_twenty = sorted(FIXTURE_ROWS, key=row_ns)[-20:]
    assert row_ns(newest_twenty[0]) > MIDNIGHT_NS + BOUND_NS
    harness = build(texts=(payload_text(newest_twenty), FIXTURE_TEXT))

    harness.actor.start()
    await harness.drain()

    assert harness.published == []
    assert harness.actor.rebuild_trusted is False
    assert harness.calls[0][1] < MAX_OBSERVATION_LIMIT

    await harness.fire_due_timers(FETCH_INSTANT_NS + INTERVAL_S * NS)

    assert harness.calls[1][1] == MAX_OBSERVATION_LIMIT
    assert harness.actor.rebuild_trusted is True
    assert len(harness.published) == len(expected_rebuild_rows())


@pytest.mark.asyncio
async def test_a_steady_poll_publishes_only_rows_not_already_published() -> None:
    newest = max(FIXTURE_ROWS, key=row_ns)
    without_newest = [row for row in FIXTURE_ROWS if row is not newest]
    harness = build(texts=(payload_text(without_newest), FIXTURE_TEXT, FIXTURE_TEXT))

    harness.actor.start()
    await harness.drain()
    after_rebuild = len(harness.published)
    assert after_rebuild == len(expected_rebuild_rows()) - 1

    await harness.fire_due_timers(FETCH_INSTANT_NS + INTERVAL_S * NS)
    assert len(harness.published) == after_rebuild + 1
    assert harness.published[-1].observed_at_ns == row_ns(newest)
    assert harness.published[-1].received_at_ns == FETCH_INSTANT_NS + INTERVAL_S * NS

    await harness.fire_due_timers(FETCH_INSTANT_NS + 2 * INTERVAL_S * NS)
    assert len(harness.published) == after_rebuild + 1  # nothing new, nothing re-published
    # The steady poll asked for a bounded window, not the whole day again.
    assert harness.calls[1][1] == observation_fetch_limit(INTERVAL_S)


# ---------------------------------------------------------------------------
# Exit criterion: the live predicate against the recorded fixture
# ---------------------------------------------------------------------------

#: Closed rung bounds in the venue's `WeatherBucketFacts` convention
#: (`lower_f`, `upper_f`, both inclusive), 2 F wide like the observed ladders.
_RUNGS: tuple[tuple[int | None, int | None], ...] = (
    (None, 59),
    *((low, low + 1) for low in range(60, 100, 2)),
    (100, None),
)
_SAMPLE_STEP_S = 1_800


@pytest.mark.asyncio
async def test_the_live_predicate_holds_against_the_recorded_fixture() -> None:
    """R(t) tracks the fixture at every sampled instant; refusals are exact, never synthesised.

    The feed is replayed forward: at each poll instant `t` the fake API
    answers with exactly the recorded rows observed at or before `t`
    (removal only, never addition), so `received_at_ns` is the real poll
    instant and the accumulator's receipt gate is exercised. Samples are
    every 30 min; the six 5-min timer fires in between land on one clock
    instant and all but the first are skipped by the spacing rule.
    """
    start_ns = MIDNIGHT_NS + 2 * 3_600 * NS
    harness = build(
        texts=lambda now: payload_text(rows_observed_at_or_before(now)), now_ns=start_ns
    )
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=MDW_STD_OFFSET_HOURS)
    fixture_instants = {row_ns(row) for row in FIXTURE_ROWS}
    received_max_c_tenths: int | None = None

    harness.actor.start()
    await harness.drain()
    verdicts: list[str | None] = []
    seen = 0
    now_ns = start_ns
    previous_lower: int | None = None
    while now_ns <= FETCH_INSTANT_NS:
        for record in harness.published[seen:]:
            accumulator.push(
                record.observed_at_ns,
                record.temp_c_tenths,
                record.precision_c_tenths,
                record.is_metar,
                record.received_at_ns,
            )
            if received_max_c_tenths is None or record.temp_c_tenths > received_max_c_tenths:
                received_max_c_tenths = record.temp_c_tenths
        seen = len(harness.published)

        running_max = accumulator.value_at(now_ns)
        assert running_max is not None
        assert received_max_c_tenths is not None
        # Never synthesised: the maximising row is a real recorded instant...
        assert running_max.source_observed_at_ns in fixture_instants
        # ...and the interval brackets the true max of what was received.
        max_f = round_half_up_f(received_max_c_tenths)
        assert running_max.lower_f <= max_f <= running_max.upper_f
        if previous_lower is not None:
            assert running_max.lower_f >= previous_lower  # a later row never lowers R
        previous_lower = running_max.lower_f

        verdicts.append(
            observation_refusal(
                running_max,
                staleness_ns=accumulator.staleness_ns(now_ns),
                staleness_bound_ns=BOUND_NS,
                rung_bounds=_RUNGS,
            )
        )
        now_ns += _SAMPLE_STEP_S * NS
        await harness.fire_due_timers(now_ns)

    assert OBSERVATION_UNAVAILABLE not in verdicts  # the feed never went stale
    assert OBSERVATION_AMBIGUOUS in verdicts  # an integer-C-only max straddled two rungs

    # A fabricated MISSING interval (rows withheld, never invented): staleness
    # over the bound refuses `observation_unavailable`.
    stale_now_ns = FETCH_INSTANT_NS + BOUND_NS + NS
    stale_max = accumulator.value_at(stale_now_ns)
    assert (
        observation_refusal(
            stale_max,
            staleness_ns=accumulator.staleness_ns(stale_now_ns),
            staleness_bound_ns=BOUND_NS,
            rung_bounds=_RUNGS,
        )
        == OBSERVATION_UNAVAILABLE
    )
