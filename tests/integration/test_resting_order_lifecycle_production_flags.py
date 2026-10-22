"""ARM post-B2: the resting-order lifecycle under ALL the production flags, with NO venue.

``test_resting_order_lifecycle`` proves the lifecycle on the per-id cancel path (its ``_rig``
default pins ``SLUG_SCOPED_CANCEL_ALL_VERIFIED`` False). Since c9fb69e6 the module values are
GTD ``True``, slug ``True`` and commission-sign ``False``; this scenario runs in exactly that
configuration (nothing but the test-speed timing constants is patched) and walks a venue that
REFUSES a cancel past its latch deadline:

refused per-order cancel -> alert -> latch -> ONE slug cancel-all on the ledger slug ->
the confirming GET -> settle ONCE -> permit restored for this process's id.

A real slug cancel-all removes EVERY open order on the slug, so the sibling rest on the same
slug is cancelled by it too (spec 9.18 / S-2); the client learns of that only by its next read,
which settles it ONCE as a venue-initiated terminal. The day's spend is asserted EXACTLY after
every step. Every sender and private read is a local double; the ``exec`` package is never
imported here (barrier X1).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.adapters.polymarket_us.errors import VenueTransportError
from tests.integration.test_resting_order_lifecycle import (
    UNIT,
    _assert_exact_spend,
    _Bench,
    _gated,
    _index,
    _names,
    _open_exposures,
    _RefusingSender,
    _remaining,
    _spent,
    _spy_settles,
)
from tests.unit.ambig_latch_rig import submit_chain, write_canonical_verified  # noqa: F401
from tests.unit.test_polymarket_us_resting_cancel import _rig
from tests.unit.test_polymarket_us_resting_submit import _id_n
from tests.unit.test_polymarket_us_resting_sweep import _set_state_on

_CANCELED: Final[str] = "ORDER_STATE_CANCELED"


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_refused_cancel_escalates_to_one_slug_cancel_all_and_settles_once_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def body() -> None:
        assert submit_chain.GTD_EXPIRY_VERIFIED is True
        assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is True
        assert submit_chain.MAKER_COMMISSION_SIGN_VERIFIED is False
        # `_rig(pin=True)` sets the slug flag to the module's own production value (True)
        rig = await _rig(tmp_path, monkeypatch, pin=True)
        bench = _Bench(rig)
        orders = [bench.order(), bench.order()]
        for order in orders:
            bench.submit(order)
        await bench.drain()
        assert [o.status.name for o in orders] == ["ACCEPTED", "ACCEPTED"]
        assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is True
        assert submit_chain.GTD_EXPIRY_VERIFIED is True
        client = rig.client
        first, second = orders
        sender = _RefusingSender()
        rig.sender = sender
        client._order_sender = sender
        settles = _spy_settles(monkeypatch, client)
        intent_0 = client._resting_bookings[_id_n(0)][0]
        intent_1 = client._resting_bookings[_id_n(1)][0]
        slug = client._resting_ledger()[0].slug
        start = _remaining(client)

        # step 0: two live rests
        assert _spent(client) == UNIT * 2
        _assert_exact_spend(client, "two rests")
        assert _open_exposures(client) == [_id_n(0), _id_n(1)] and _index(client) == [
            _id_n(0),
            _id_n(1),
        ]

        seen: dict[str, Any] = {}

        def attempts(attempt: int, order_id: str) -> None:
            if attempt == 2:
                # the order's expiry (30 min) + grace is the latch deadline: age past it
                client.advance(2_100)
            if attempt == 3:
                # step 2: the refusal latched and escalated; NOTHING has settled or moved yet
                seen["cancel_alls"] = [list(s) for s in sender.cancel_alls]
                seen["refusals"] = [r.reason for r in client._trading_refusals]
                seen["spent"] = _spent(client)
                seen["remaining"] = _remaining(client)
                seen["settles"] = list(settles)
                seen["events"] = Counter(rig.event_names())
                _assert_exact_spend(client, "after the escalation, before any confirmation")
                # the venue honours the cancel-all: EVERY open order on the slug is cancelled
                _set_state_on(client, 0, _CANCELED)
                _set_state_on(client, 1, _CANCELED)

        sender.attempt_hook = attempts
        sender.cancel_raises = VenueTransportError("refused (bench)")
        bench.strategy.cancel_order(first)
        sender.on_cancel_all = lambda slugs: seen.setdefault("sent", list(slugs))
        await bench.drain()

        # step 1-2: refused cancels, then the single escalation on the ledger slug
        assert seen["refusals"] == [submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON]
        assert seen["cancel_alls"] == [[slug]] and seen["sent"] == [slug]
        assert seen["settles"] == [] and seen["spent"] == UNIT * 2
        assert seen["remaining"] == start
        assert seen["events"]["OrderCanceled"] == 0
        # step 3: the confirming GET retired the row ONCE, restored this process's id
        assert settles == [intent_0]
        assert first.status.name == "CANCELED"
        assert client._budget_was_restored(_id_n(0))
        assert _remaining(client) == (start[0] + UNIT, start[1] + 1)
        assert _spent(client) == UNIT
        _assert_exact_spend(client, "after the confirmed cancel")
        assert _index(client) == [_id_n(1)] and _open_exposures(client) == [_id_n(1)]
        assert client._trading_refusals == [] and client.resting_cancel_alerts == ()
        assert sender.cancel_alls == [[slug]], "one cancel-all in total"
        assert _names(rig)["OrderCanceled"] == 1

        # step 4: the sibling the slug cancel-all removed is learned by the next read and
        # settles ONCE, as a venue-initiated terminal, restoring its (this-process) slot
        sender.cancel_raises = None
        sender.attempt_hook = None
        bench.strategy.query_order(second)
        await bench.drain()
        assert settles == [intent_0, intent_1]
        assert second.status.name == "CANCELED"
        assert _spent(client) == 0
        _assert_exact_spend(client, "after the sibling's venue-side cancel is read")
        assert _remaining(client) == (start[0] + UNIT * 2, start[1] + 2)
        assert _index(client) == [] and _open_exposures(client) == []

        # step 5: nothing repeats -- a second query and a second cancel of settled ids
        frozen = (list(settles), _remaining(client), len(sender.cancels), list(rig.event_names()))
        bench.strategy.query_order(first)
        bench.strategy.query_order(second)
        await bench.drain()
        assert await client._cancel_resting_order([_id_n(0), _id_n(1)]) == frozenset()
        assert (
            list(settles),
            _remaining(client),
            len(sender.cancels),
            list(rig.event_names()),
        ) == frozen
        assert sender.cancel_alls == [[slug]]
        assert _spent(client) == 0
        _assert_exact_spend(client, "after the repeats")
        assert client._cancel_in_flight == frozenset()
        bench.stop()

    await _gated(monkeypatch, body)
