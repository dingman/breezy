"""M4 and L8: the discovery reload loop must be structurally unkillable.

M4 is a fail-SHUT regression and the opposite failure mode from the rest of
this adapter's hardening. ``derive_reload_delay_secs`` raising on an empty
boundary set is the FIRST statement inside ``_update_instruments``' loop,
before any ``await asyncio.sleep``, and the loop catches only
``asyncio.CancelledError``. A cold start inside a fully-settled window --
every discovered market carrying a ``resolved_reason``, so ``load_all_async``
SUCCEEDS while ``get_all()`` stays empty -- therefore kills the reload task on
its first iteration, permanently, because that loop is the only thing that
would ever discover the next day's ladder.

Falling back to the floor cadence with a loud warning is the ONE sanctioned
fallback-on-failure in this adapter, precisely because the alternative is
going quietly and irrecoverably blind.

L8 is the mirror-image concern on the same discovery path: a hostile RESPONSE
must not control loop termination.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock

from breezy.adapters.polymarket_us.data import (
    DISCOVERY_RELOAD_FLOOR_SECS,
    derive_reload_delay_secs,
)
from breezy.adapters.polymarket_us.errors import PolymarketUSError, VenuePayloadError
from breezy.adapters.polymarket_us.provider import MAX_DISCOVERY_PAGES
from tests.unit.test_polymarket_us_data import (
    SLUG,
    build_harness,
    make_config,
    make_instrument,
)
from tests.unit.test_polymarket_us_provider import (
    OPEN_SLUG,
    build_provider,
    raw_bytes,
)

# ---------------------------------------------------------------------------
# M4 -- "no boundaries yet" is a retry, not a fatal invariant
# ---------------------------------------------------------------------------


def test_an_empty_boundary_set_yields_the_floor_rather_than_raising() -> None:
    outcome = derive_reload_delay_secs(now_ns=0, boundaries_ns=())

    assert outcome.seconds == DISCOVERY_RELOAD_FLOOR_SECS
    assert outcome.clamped == "floor"
    assert outcome.boundary_ns is None


def test_the_empty_boundary_floor_is_reported_as_clamped_so_the_caller_can_warn() -> None:
    """Silent is the failure mode being fixed; the caller logs on ``clamped``."""
    assert derive_reload_delay_secs(now_ns=1, boundaries_ns=()).clamped is not None


@pytest.mark.asyncio
async def test_a_cold_start_with_no_known_instruments_still_schedules_a_reload() -> None:
    """The all-settled cold start: ``get_all()`` empty, so no boundary exists."""
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[],
    )

    delay = harness.client._next_reload_delay_secs()

    assert delay == DISCOVERY_RELOAD_FLOOR_SECS


@pytest.mark.asyncio
async def test_the_reload_loop_survives_an_error_from_the_delay_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: nothing but cancellation may end this loop.

    The floor fallback in ``derive_reload_delay_secs`` removes the known
    raise. This asserts the loop is STRUCTURALLY incapable of exiting on a
    ``PolymarketUSError``, so a future derivation that raises for a new reason
    cannot silently blind the bot either.
    """
    from breezy.adapters.polymarket_us import data as data_module

    # Collapse the retry floor so the loop's real timing is not under test.
    monkeypatch.setattr(data_module, "DISCOVERY_RELOAD_FLOOR_SECS", 0.0)

    now_ns = LiveClock().timestamp_ns()
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[
            make_instrument(
                SLUG,
                activation_ns=now_ns,
                expiration_ns=now_ns + 3 * 3600 * 1_000_000_000,
            )
        ],
    )
    calls: list[int] = []

    def exploding_delay() -> float:
        calls.append(1)
        if len(calls) <= 2:
            raise PolymarketUSError("synthetic derivation failure")
        return 3600.0

    monkeypatch.setattr(harness.client, "_next_reload_delay_secs", exploding_delay)

    task = asyncio.get_event_loop().create_task(harness.client._update_instruments())
    try:
        for _ in range(500):
            await asyncio.sleep(0)
            if len(calls) >= 3:
                break
        assert len(calls) >= 3, f"loop exited after {len(calls)} derivation attempt(s)"
        assert not task.done(), "the reload loop exited on a non-cancellation error"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_reload_loop_survives_a_failed_reload_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A venue outage or a malformed discovery payload is a failed CYCLE only.

    ``initialize(reload=True)`` raises ``VenuePayloadError`` on a zero-market
    discovery cycle, which is a routine venue condition. It must never end the
    only loop that would recover from it on the next pass.
    """
    from breezy.adapters.polymarket_us import data as data_module

    monkeypatch.setattr(data_module, "DISCOVERY_RELOAD_FLOOR_SECS", 0.0)
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[],
    )
    cycles: list[int] = []

    async def failing_cycle() -> None:
        cycles.append(1)
        raise VenuePayloadError("synthetic discovery failure")

    monkeypatch.setattr(harness.client, "_run_one_reload_cycle", failing_cycle)

    task = asyncio.get_event_loop().create_task(harness.client._update_instruments())
    try:
        for _ in range(500):
            await asyncio.sleep(0)
            if len(cycles) >= 3:
                break
        assert len(cycles) >= 3, f"loop exited after {len(cycles)} cycle(s)"
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_reload_loop_still_stops_on_cancellation() -> None:
    """Unkillable must not mean unstoppable -- shutdown still has to work.

    The loop handles ``asyncio.CancelledError`` and returns, so the task
    completes rather than ending in the cancelled state; what matters for
    shutdown is that it STOPS promptly and does not swallow the request.
    """
    harness = build_harness(
        config=make_config(instrument_reload_interval_mins=None),
        instruments=[],
    )
    task = asyncio.get_event_loop().create_task(harness.client._update_instruments())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.done()


# ---------------------------------------------------------------------------
# L8 -- a hostile response must not control loop termination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_pagination_is_capped_rather_than_unbounded() -> None:
    """A host that always returns a full page must fail loudly, not hang."""
    provider, transport, _ = build_provider(market_slugs=(OPEN_SLUG,))
    body = json.loads(raw_bytes("market_open_510636_by_slug.json"))["market"]
    limit = provider._discovery.limit

    async def always_full_page(url: str, *, headers: Any, quota_key: str) -> Any:
        from breezy.adapters.polymarket_us.transport import VenueResponse

        # Distinct, GRAMMAR-VALID slugs: the cap must fire on page count, not
        # be masked by a slug-validation error on the first page.
        page = [
            dict(body, slug=f"tc-temp-nychigh-2026-08-25-lt{index + 1}f")
            for index in range(limit)
        ]
        return VenueResponse(
            status=200, headers={}, body=json.dumps({"markets": page}).encode("utf-8")
        )

    transport.get = always_full_page  # type: ignore[method-assign]

    with pytest.raises(VenuePayloadError, match="page"):
        await provider.load_all_async()


def test_the_discovery_page_cap_is_a_named_constant() -> None:
    assert isinstance(MAX_DISCOVERY_PAGES, int)
    assert MAX_DISCOVERY_PAGES > 0
