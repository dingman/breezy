"""EXEC-PAR WP7 (r5 5.WP7, D-PREREG cool-off): per-slug serialisation.

* A slug that just retired an entry is cooling off (120 s from the retire,
  entries only, exits exempt), so a LATE fill of the retired order cannot be
  doubled up by an immediate re-arm on the same slug.
* An exit and an entry on the same slug never run concurrently, in either order:
  each waits for the other's slot to retire, and both orders are then sent.

The REAL client, latch and ledger run at K = 2 through ``exec_par_rig``; only the
venue sender is a double. The rig clock is injected, absolute and frozen unless a
test moves it, so no assertion depends on wall time.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.submit_intent_slots import DEFAULT_COOLOFF_NS
from tests.unit.exec_par_rig import (
    ARMED_EXIT_MANIFEST,
    BASE_NS,
    SEC_NS,
    GatedSender,
    ParRig,
    ScriptedSender,
    accept_fill_body,
    build_par_rig,
    caps,
    exit_fill_body,
    ok,
    par_rig,
    reboot,
    submit_chain,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

WAIT = submit_chain.OPEN_INTENT_WAIT_REASON
COOLOFF = "cooloff"


def _at(rig: ParRig, now_ns: int) -> None:
    """Move the rig clock and publish a FRESH breaker heartbeat there.

    Without the heartbeat a K > 1 entry is denied as ``breaker_heartbeat_stale``
    (60 s), which would mask the cool-off this module is about.
    """
    rig.client.set_now(now_ns)
    rig.latch.write_breaker_heartbeat(hb_ns=now_ns, resolver_pass_ns=now_ns)


async def _submit_expecting_wait(rig: ParRig, command: Any) -> None:
    """Submit ``command`` and require it to be DENIED at once (a WAIT).

    An order that is wrongly admitted parks on the gated sender; without the bound
    that would hang the suite instead of failing it.
    """
    task = asyncio.create_task(rig.client._submit_order(command))
    done, _pending = await asyncio.wait({task}, timeout=2.0)
    if not done:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise AssertionError("an order on a slug with an open slot was admitted (POST in flight)")
    await task


def _actions(sender: Any) -> list[tuple[str, str]]:
    """``(action, marketSlug)`` for every POSTed wire body, in order."""
    bodies = [json.loads(call["body"]) for call in sender.calls]
    return [(str(body["action"]), str(body["marketSlug"])) for body in bodies]


# ---------------------------------------------------------------------------
# cool-off after a retire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["zero_fill", "accept_fill"])
async def test_late_fill_after_zero_fill_or_fill_retire_then_rearm_same_slug_denied_by_cooloff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    outcome: str,
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()), ok(zero_fill_body(order_id="ord-late")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            slug, other = rig.slug(0), rig.slug(1)
            if outcome == "accept_fill":
                sender.responses[0] = ok(accept_fill_body(slug, order_id="ord-first"))
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert rig.latch.open_slot_count() == 0, "the order retired (zero fill or fill)"
            assert len(sender.calls) == 1
            until_ns = BASE_NS + DEFAULT_COOLOFF_NS

            # The venue can still report a late fill of the retired order for a while;
            # an immediate re-arm on the same slug is denied by the cool-off.
            _at(rig, BASE_NS + 1 * SEC_NS)
            assert rig.latch.admission_refusal(slug, False) == COOLOFF
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert rig.denied_reasons() == [WAIT]
            assert len(sender.calls) == 1, "no second POST during the cool-off"

            # Entries only: an exit on the cooling slug and an entry on another slug pass.
            assert rig.latch.admission_refusal(slug, True) is None
            assert rig.latch.admission_refusal(other, False) is None

            # The window is exactly 120 s from the retire: still denied one ns before ...
            _at(rig, until_ns - 1)
            assert rig.latch.admission_refusal(slug, False) == COOLOFF
            # ... and admitted at the boundary.
            _at(rig, until_ns)
            assert rig.latch.admission_refusal(slug, False) is None
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert len(sender.calls) == 2


@pytest.mark.asyncio
async def test_cooloff_survives_a_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The cool-off is durable: a restart inside the window does not reopen the slug."""
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        first = await build_par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2)
        slug = first.slug(0)
        await first.client._submit_order(first.buy(first.instruments[0]))
        assert first.latch.open_slot_count() == 0

        second = await reboot(first, monkeypatch, sender=sender, max_slots=2)
        try:
            _at(second, BASE_NS + 5 * SEC_NS)
            assert second.latch.admission_refusal(slug, False) == COOLOFF
            await second.client._submit_order(second.buy(second.instruments[0]))
            assert len(sender.calls) == 1
            assert second.denied_reasons() == [WAIT]
        finally:
            await second.close()


# ---------------------------------------------------------------------------
# exit and entry on one slug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_and_entry_same_slug_serialised_both_orders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    # Placeholders: the real wire bodies need the rig's slugs and are assigned below.
    sender = GatedSender(
        ok(zero_fill_body(order_id="ord-entry-0")),
        ok(zero_fill_body()),
        ok(zero_fill_body()),
        ok(zero_fill_body(order_id="ord-entry-1")),
    )
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=sender, max_slots=2, exit_manifest=ARMED_EXIT_MANIFEST
        ) as rig:
            slug0, slug1 = rig.slug(0), rig.slug(1)
            sender.responses[1] = ok(
                exit_fill_body(
                    slug0,
                    order_id="ord-exit-0",
                    side="ORDER_SIDE_SELL",
                    intent="ORDER_INTENT_SELL_LONG",
                )
            )
            sender.responses[2] = ok(
                exit_fill_body(
                    slug1,
                    order_id="ord-exit-1",
                    side="ORDER_SIDE_SELL",
                    intent="ORDER_INTENT_SELL_LONG",
                )
            )

            # --- entry first, exit second, same slug ---------------------------------
            entry = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            await _submit_expecting_wait(
                rig, rig.exit_sell(rig.instruments[0], client_order_id_value="O-EXIT-A1")
            )
            assert rig.denied_reasons() == [WAIT], "the exit waits behind the open entry"
            assert len(sender.calls) == 1
            assert rig.latch.open_slot_count() == 1
            sender.release(0)
            await entry

            exit_a = asyncio.create_task(
                rig.client._submit_order(
                    rig.exit_sell(rig.instruments[0], client_order_id_value="O-EXIT-A2")
                )
            )
            await sender.wait_started(1)  # exits are exempt from the entry cool-off
            assert rig.latch.open_slot_count() == 1
            sender.release(1)
            await exit_a
            assert rig.latch.open_slot_count() == 0

            # --- exit first, entry second, same slug ---------------------------------
            exit_b = asyncio.create_task(
                rig.client._submit_order(
                    rig.exit_sell(rig.instruments[1], client_order_id_value="O-EXIT-B1")
                )
            )
            await sender.wait_started(2)
            await _submit_expecting_wait(rig, rig.buy(rig.instruments[1]))
            assert rig.denied_reasons() == [WAIT, WAIT], "the entry waits behind the open exit"
            assert len(sender.calls) == 3
            assert rig.latch.open_slot_count() == 1
            sender.release(2)
            await exit_b

            entry_b = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[1])))
            await sender.wait_started(3)  # an exit's retire starts no entry cool-off
            sender.release(3)
            await entry_b

            assert rig.latch.open_slot_count() == 0
            assert _actions(sender) == [
                ("ORDER_ACTION_BUY", slug0),
                ("ORDER_ACTION_SELL", slug0),
                ("ORDER_ACTION_SELL", slug1),
                ("ORDER_ACTION_BUY", slug1),
            ], "both orders sent on each slug, one at a time, in arrival order"
