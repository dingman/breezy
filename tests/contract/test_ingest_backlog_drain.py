"""WI-11 -- does a multi-day backlog of missed NWS CLI products drain inside
the ~7-day api.weather.gov retention window?

Governing spec: `docs/plans/NWS_COLLECTION_RUNTIME_PLAN.md` lines 269-282.

Three of the four candidate defeats the plan names are ALREADY DISPROVEN
against current code and are deliberately NOT re-tested here:

1. There is no `max_products_per_poll` cap -- `grep -rn max_products_per_poll
   src/` returns zero hits, and `NwsIngestActor.poll_once` iterates every
   pending entry with no batch-size limit. `test_single_poll_is_uncapped_and_
   drains_oldest_first` below is the anti-regression pin: it proves the
   CURRENT no-cap, oldest-first property so a future cap cannot be
   reintroduced silently.
2. The BLOCKED gate does not disable polling -- `network_allowed()` gates
   only on the global UA-trap latch and a self-set backoff window, never on
   `GateState`. `tests/unit/test_ingest_nws_actor.py::
   test_every_blocked_state_still_polls` already pins this; not duplicated
   here.
3. `ts_init` ordering within one poll's batch is enforced by
   `catalog._require_non_decreasing` and satisfied by construction (`poll_once`
   sorts pending entries by `issuance_time_ns` before fetching, and
   `_persist_batch` sorts the write batch by `record_cursor`, whose leading
   key is `ts_init`).

The mechanism that is genuinely UNTESTED, and the reason this module exists:
`ts_init` is fetch time (`retrieved_at_ns`), not issuance time. Two SEPARATE
polls that land on the same clock tick (plausible during a fast backlog
drain, and unavoidable in a test that does not sleep) produce two batches
whose `ts_init` ranges can be EXACTLY equal. `write_records` silently
discards an exact-range rewrite (`persistence/catalog.py` module docstring,
"Corrections" section) and routes the resulting `WriteOutcome.skipped` to
`record_write_integrity_violation` -- CRIT, hard-block, and the second
product is lost. `test_same_clock_tick_batches_do_not_silently_collide`
below is the test that finds this.

No test in this module performs real network I/O: `respx` intercepts
`httpx` at the transport layer (as in `tests/unit/test_ingest_nws_actor.py`),
and `tests/conftest.py` blocks real sockets outright as a second mechanism.
No test hard-codes a real calendar date relative to "today" -- every backlog
date is computed relative to a fixed, in-module reference date, never
`datetime.now()`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from itertools import pairwise
from typing import Any

import httpx
import pytest
import respx

from breezy.ingest.gate import GateReason, GateState

# Re-used, not re-invented (task constraint): the `actor`/`shared`/`clock`/
# `store`/`store_pair`/`registry` fixtures are picked up automatically from
# `tests/contract/conftest.py`, which re-exports them from the unit suite.
# Only the plain helpers/constants/types are imported directly here.
# `NwsIngestActor`/`SharedIngestState` come from their OWN modules, not the
# unit suite: the unit suite itself only re-imports them, and mypy's strict
# `implicit_reexport` rule (correctly) refuses a second-hand re-export.
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_days,
    read_raw_products,
)
from tests.unit.test_ingest_nws_actor import (
    BASE_URL,
    CITY,
    DISCOVERY_URL,
    SECOND,
    VENUE,
    FakeClock,
    discovery_payload,
)

# ---------------------------------------------------------------------------
# Synthetic backlog products
# ---------------------------------------------------------------------------
#
# The fixture library (`tests/fixtures/nws/`) covers exactly one NYC climate
# day (2026-08-21, final + preliminary). A multi-day backlog needs many
# distinct days, so this module builds minimal synthetic FINAL CLI bodies
# in the same shape `tests/unit/test_normalize_cli_parse_pattern.py::_body`
# already proves is sufficient to satisfy the structural allowlist, the
# headline/temperature parser and the physical-sanity bounds.

# A fixed reference date, never `datetime.now()` -- backlog days are always
# expressed as an offset from this constant so the suite cannot flip red on
# a future calendar day.
_REFERENCE_TODAY = dt.date(2026, 8, 22)


def backlog_day(days_before_reference: int) -> dt.date:
    """One climate day, `days_before_reference` days before `_REFERENCE_TODAY`."""
    return _REFERENCE_TODAY - dt.timedelta(days=days_before_reference)


def synthetic_uuid(label: str) -> str:
    """A deterministic, canonical UUID for one synthetic backlog product."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"breezy-backlog-{label}"))


def nyc_final_text(summary_date: dt.date) -> str:
    """A minimal, valid NYC FINAL CLI body for `summary_date`.

    Shape proven sufficient by `test_normalize_cli_parse_pattern.py::_body`:
    WMO transmission header, `CLINYC` AWIPS PIL, the headline regex
    `parse_cli_product` searches for, and a TEMPERATURE (F) / YESTERDAY
    block with values inside the physical-sanity bounds. No "VALID TODAY AS
    OF" line, so `classify_issuance` reads every one of these as FINAL.
    """
    month_name = summary_date.strftime("%B").upper()
    return (
        "\n000\nCDUS41 KOKX 010101\nCLINYC\n\n"
        f"...THE CENTRAL PARK NY CLIMATE SUMMARY FOR {month_name} "
        f"{summary_date.day} {summary_date.year}...\n"
        "TEMPERATURE (F)\n YESTERDAY\n  MAXIMUM 79\n  MINIMUM 63\n  AVERAGE 71\n\n"
        "PRECIPITATION (IN)\n"
    )


def synthetic_issuance(summary_date: dt.date) -> dt.datetime:
    """The FINAL's issuance instant: the morning after the climate day, as
    every real NYC FINAL fixture in this suite is stamped (06:26 UTC)."""
    return dt.datetime(
        summary_date.year, summary_date.month, summary_date.day, tzinfo=dt.UTC
    ) + dt.timedelta(days=1, hours=6, minutes=26)


def synthetic_entry(summary_date: dt.date, *, label: str | None = None) -> dict[str, Any]:
    return {
        "id": synthetic_uuid(label or summary_date.isoformat()),
        "productCode": "CLI",
        "issuingOffice": "KOKX",
        "wmoCollectiveId": "CDUS41",
        "issuanceTime": synthetic_issuance(summary_date).isoformat(),
    }


def synthetic_product_payload(summary_date: dt.date, *, label: str | None = None) -> dict[str, Any]:
    entry = synthetic_entry(summary_date, label=label)
    entry["productText"] = nyc_final_text(summary_date)
    return entry


def synthetic_product_url(summary_date: dt.date, *, label: str | None = None) -> str:
    return f"{BASE_URL}/products/{synthetic_uuid(label or summary_date.isoformat())}"


def mock_synthetic_discovery(mock: respx.MockRouter, *days: dt.date, **kwargs: Any) -> Any:
    payload = discovery_payload(*(synthetic_entry(d) for d in days))
    return mock.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=payload, **kwargs)
    )


def mock_synthetic_product(mock: respx.MockRouter, summary_date: dt.date) -> Any:
    return mock.get(synthetic_product_url(summary_date)).mock(
        return_value=httpx.Response(200, json=synthetic_product_payload(summary_date))
    )


def persisted_uuids(tmp_path: Any) -> set[str]:
    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    return {r.product_uuid for r in read_raw_products(catalog)}


# ---------------------------------------------------------------------------
# 1. A 48-hour backlog fully drains, and the persisted set matches the offer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_48_hour_backlog_fully_drains_across_successive_polls(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock, tmp_path: Any
) -> None:
    """Two climate days, ~48 hours apart, missed by an outage. Discovery
    keeps listing both (as the real ~7-day retention window would) across
    three successive polls; the persisted product-uuid set must equal the
    set the discovery list ever offered, with nothing left behind."""
    day_a = backlog_day(2)
    day_b = backlog_day(1)
    offered = {synthetic_uuid(day_a.isoformat()), synthetic_uuid(day_b.isoformat())}

    actor.on_start()
    for _ in range(3):
        with respx.mock(assert_all_called=False) as mock:
            mock_synthetic_discovery(mock, day_a, day_b)
            mock_synthetic_product(mock, day_a)
            mock_synthetic_product(mock, day_b)
            await actor.poll_once()
        clock.advance(300 * SECOND)

    assert persisted_uuids(tmp_path) == offered
    assert GateReason.WRITE_INTEGRITY_VIOLATION not in shared.gate.blocking_causes(VENUE, CITY)


# ---------------------------------------------------------------------------
# 2. A single poll is uncapped and drains oldest-issuance-first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_poll_is_uncapped_and_drains_oldest_first(
    actor: NwsIngestActor, tmp_path: Any
) -> None:
    """Anti-regression pin, replacing the stale `max_products_per_poll`
    premise: 10 backlogged products (> the plan's former cap of 8), offered
    in a REVERSED (newest-first) discovery list, must all fetch and persist
    in ONE poll, and the product-fetch HTTP requests must go out in
    oldest-issuance-first order regardless of discovery-list order."""
    days = [backlog_day(n) for n in range(10, 0, -1)]  # 10 distinct days
    offered = {synthetic_uuid(d.isoformat()) for d in days}

    with respx.mock(assert_all_called=False) as mock:
        # Deliberately newest-first in the wire payload.
        mock_synthetic_discovery(mock, *reversed(days))
        for day in days:
            mock_synthetic_product(mock, day)
        actor.on_start()
        await actor.poll_once()

        product_calls = [
            call for call in mock.calls if str(call.request.url) != DISCOVERY_URL
        ]

    assert persisted_uuids(tmp_path) == offered

    fetched_order = [str(call.request.url) for call in product_calls]
    expected_order = [synthetic_product_url(d) for d in days]  # `days` is oldest-first
    assert fetched_order == expected_order


# ---------------------------------------------------------------------------
# 3. A 7-day, >8-product backlog shrinks monotonically to zero
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_day_backlog_shrinks_monotonically_to_zero(
    actor: NwsIngestActor, clock: FakeClock, tmp_path: Any
) -> None:
    """9 products (> 8) spanning a week-old backlog. The outstanding count
    (offered minus persisted) must never increase poll over poll, and must
    reach exactly zero with nothing left unfetched."""
    days = [backlog_day(n) for n in range(9, 0, -1)]
    offered = {synthetic_uuid(d.isoformat()) for d in days}

    outstanding: list[int] = [len(offered - persisted_uuids(tmp_path))]
    actor.on_start()
    for _ in range(3):
        with respx.mock(assert_all_called=False) as mock:
            mock_synthetic_discovery(mock, *days)
            for day in days:
                mock_synthetic_product(mock, day)
            await actor.poll_once()
        clock.advance(300 * SECOND)
        outstanding.append(len(offered - persisted_uuids(tmp_path)))

    assert outstanding[0] == len(days)
    assert all(later <= earlier for earlier, later in pairwise(outstanding))
    assert outstanding[-1] == 0
    assert persisted_uuids(tmp_path) == offered


# ---------------------------------------------------------------------------
# 4. THE finding: same-clock-tick batches across separate polls must not
#    silently collide.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_clock_tick_batches_do_not_silently_collide(
    actor: NwsIngestActor, shared: SharedIngestState, tmp_path: Any
) -> None:
    """Two DIFFERENT products (different climate days), each fetched in its
    own poll, with the clock NOT advanced between polls -- a fast backlog
    drain, or two polls close enough together that the injected nanosecond
    clock genuinely reads the same instant twice. `ts_init` is fetch time,
    so both single-product batches share an identical `retrieved_at_ns`, and
    therefore an identical `ts_init` range for the whole batch.

    `write_records` treats a batch whose `ts_init` range EXACTLY matches an
    already-written file as a same-range rewrite and discards it SILENTLY
    (`persistence/catalog.py` module docstring, "Corrections"), which routes
    to `record_write_integrity_violation` -- CRIT, hard-block. The second
    poll's product would be durably lost with no exception anywhere in the
    call stack.

    This is the untested mechanism WI-11 exists to find. Every product from
    both polls must be durably persisted, `WriteOutcome.skipped` must never
    apply to fresh (never-before-seen) content, and the gate must never
    enter WRITE_INTEGRITY_VIOLATION for this station.
    """
    day_a = backlog_day(2)
    day_b = backlog_day(1)

    with respx.mock(assert_all_called=False) as mock:
        mock_synthetic_discovery(mock, day_a)
        mock_synthetic_product(mock, day_a)
        actor.on_start()
        await actor.poll_once()

    # Deliberately NOT advancing the clock: the collision only exists when
    # two separate polls land on the same instant.
    with respx.mock(assert_all_called=False) as mock:
        mock_synthetic_discovery(mock, day_b)
        mock_synthetic_product(mock, day_b)
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    raws = read_raw_products(catalog)
    days_persisted = read_climate_days(catalog)

    assert {r.product_uuid for r in raws} == {
        synthetic_uuid(day_a.isoformat()),
        synthetic_uuid(day_b.isoformat()),
    }
    assert {d.climate_day for d in days_persisted} == {day_a, day_b}
    assert (
        GateReason.WRITE_INTEGRITY_VIOLATION
        not in shared.gate.blocking_causes(VENUE, CITY)
    )
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# 5. A product that ages out of discovery before ever being seen is never
#    phantom-fetched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aged_out_product_is_never_fetched(
    actor: NwsIngestActor, shared: SharedIngestState, tmp_path: Any
) -> None:
    """A product that fell out of the ~7-day discovery retention window
    before this actor ever polled must never be requested -- there is no
    identifier space to "remember" it by, and the poll must still complete
    cleanly for the products discovery DOES offer."""
    day_a = backlog_day(2)
    day_b = backlog_day(1)
    day_aged_out = backlog_day(30)  # never appears in any discovery response

    with respx.mock(assert_all_called=False) as mock:
        mock_synthetic_discovery(mock, day_a, day_b)  # day_aged_out never offered
        mock_synthetic_product(mock, day_a)
        mock_synthetic_product(mock, day_b)
        aged_out_route = mock_synthetic_product(mock, day_aged_out)
        actor.on_start()
        await actor.poll_once()

    assert aged_out_route.call_count == 0
    assert persisted_uuids(tmp_path) == {
        synthetic_uuid(day_a.isoformat()),
        synthetic_uuid(day_b.isoformat()),
    }
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# 6. A 304 mid-backlog fetches nothing and does not mark the backlog drained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_304_during_open_backlog_fetches_nothing_and_leaves_backlog_open(
    actor: NwsIngestActor, shared: SharedIngestState, tmp_path: Any
) -> None:
    """One product ingested; a second, still-outstanding product's poll
    lands on a 304 (a still-valid conditional-GET ETag). The 304 must be a
    terminal no-op -- it must not fetch the outstanding product, and it must
    not cause that product to be treated as drained."""
    day_a = backlog_day(2)
    day_b = backlog_day(1)  # never actually offered by any 200 response below

    with respx.mock(assert_all_called=False) as mock:
        mock_synthetic_discovery(mock, day_a, headers={"ETag": '"v1"'})
        mock_synthetic_product(mock, day_a)
        actor.on_start()
        await actor.poll_once()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        never_fetched = mock_synthetic_product(mock, day_b)
        await actor.poll_once()

    assert never_fetched.call_count == 0
    assert persisted_uuids(tmp_path) == {synthetic_uuid(day_a.isoformat())}
    assert synthetic_uuid(day_b.isoformat()) not in persisted_uuids(tmp_path)
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN
