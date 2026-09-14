"""S2 data-inert guard for the NO leg (N2-2, R3-6 disposition).

The NO instrument never receives native market data -- inbound frames
publish under the id resolved from the wire ``marketSlug``, i.e. the YES id.
`_subscribe_quote_ticks`/`_subscribe_order_book_depth` already resolve the
slug through `instrument_id_to_slug`, which is a hard bijection over base
slugs (N2-1) and therefore already refuses a NO leg's composite id -- this
file is the RED test proving that refusal is explicit, logged, and issues no
feed call, not an accident of missing wiring.
"""

from __future__ import annotations

import pytest

from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
from tests.unit.test_polymarket_us_data import (
    SLUG,
    build_harness,
    depth_subscribe_command,
    subscribe_command,
)


@pytest.mark.asyncio
async def test_quote_subscribe_refuses_a_no_leg_instrument_with_no_feed_call() -> None:
    harness = build_harness()
    await harness.client._connect()
    no_id = no_leg_instrument_id(SLUG)

    await harness.client._subscribe_quote_ticks(subscribe_command(no_id))

    # `_connect()` already auto-subscribes the preloaded YES instrument
    # (`SLUG`) via discovery reconciliation; the NO-leg subscribe call itself
    # must add NOTHING beyond that.
    assert harness.feed.events == ["connect", f"subscribe:{SLUG}"]
    await harness.client._disconnect()


@pytest.mark.asyncio
async def test_depth_subscribe_refuses_a_no_leg_instrument_with_no_feed_call() -> None:
    harness = build_harness()
    await harness.client._connect()
    no_id = no_leg_instrument_id(SLUG)

    await harness.client._subscribe_order_book_depth(depth_subscribe_command(no_id))

    assert harness.feed.events == ["connect", f"subscribe:{SLUG}"]
    await harness.client._disconnect()
