"""ARM post-B2: a 404 on ``GET /v1/order/{id}`` is UNREADABLE, never "the order is gone".

The venue answers 404 for an order-by-id read it cannot (yet) serve -- the B2 live run saw it
right after a create. The client has no way to tell that from an order that never existed, and
a false terminal on a venue with no client-order-id is the first step to a doubled position. So
every order-by-id reader must treat the refusal as one failed read: no retire, no budget
restore, and no ``OrderCanceled`` / ``OrderRejected`` / NO_FILL. These six are RED-capable
characterizations of that behaviour on the six readers (confirm, cancel confirm, with-id
resolver, ``_query_order`` poll, boot sweep); each injects ``PrivateReadRefused(status=404)`` on
the order-by-id path only.

No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig`` and the sibling
suites. No venue contact: every sender and private read is a local double.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    run_passes,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import (
    CancelSender,
    _remaining,
    _set_state,
)
from tests.unit.test_polymarket_us_resting_cancel import _rig as _cancel_rig
from tests.unit.test_polymarket_us_resting_query import _query
from tests.unit.test_polymarket_us_resting_submit import (
    VENUE_ID,
    _held_rest,
    _id_n,
    _rest_command,
    _submit_rest,
    _venue_order,
)
from tests.unit.test_polymarket_us_resting_submit import _rig as _submit_rig
from tests.unit.test_polymarket_us_resting_sweep import _second_process, _set_state_on

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
#: Events a false terminal would emit; a 404 must produce none of them.
_FALSE_TERMINAL_EVENTS: Final[frozenset[str]] = frozenset(
    {"OrderCanceled", "OrderRejected", "OrderExpired", "OrderFilled", "OrderDenied"}
)


class Inject404:
    """Wrap a client's ``_private_read``: order-by-id GETs raise ``PrivateReadRefused(404)``.

    Scoped to ``ids`` (or every order id when ``None``) while ``active``; every other path, and
    the same path once ``active`` is cleared, passes through to the wrapped read.
    """

    def __init__(
        self,
        client: Any,
        ids: frozenset[str] | None = None,
        first: int | None = None,
        stall_s: float = 0.0,
        on_hit: Callable[[int], None] | None = None,
    ) -> None:
        self.inner = client._private_read
        self._payloads = self.inner._payloads  # the rig's scripted payloads stay reachable
        self.ids = ids
        self.first = first  # 404 only the first N matching reads, then pass through
        self.stall_s = stall_s  # block the loop on the first 404 (a starved host, a GC pause)
        self.on_hit = on_hit  # called with the hit count after each injected 404
        self.active = True
        self.hits: list[str] = []
        client._private_read = self

    def _matches(self, path: str) -> bool:
        if self.ids is None:
            return path.startswith("/v1/order/")
        return path in {submit_chain.order_by_id_path(i) for i in self.ids}

    async def __call__(self, path: str, *args: Any, **kwargs: Any) -> Any:
        if (
            self.active
            and self._matches(path)
            and (self.first is None or len(self.hits) < self.first)
        ):
            self.hits.append(path)
            if self.stall_s and len(self.hits) == 1:
                time.sleep(self.stall_s)  # noqa: ASYNC251 - a deliberate whole-loop stall
            if self.on_hit is not None:
                self.on_hit(len(self.hits))
            raise client_module.PrivateReadRefused(status=404, path=path, body=b"")
        return await self.inner(path, *args, **kwargs)


def _false_terminals(events: list[Any]) -> list[str]:
    return [n for n in (type(e).__name__ for e in events) if n in _FALSE_TERMINAL_EVENTS]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_confirm_404_then_200_returns_NEW(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two 404s inside the deadline, then the clean NEW: the confirm keeps polling past the
    404s and binds. (A confirm that held on the first unreadable read would not.)"""
    rig = await _submit_rig(tmp_path, monkeypatch)
    client = rig.client
    command = _rest_command(client)
    rig.set_get(_venue_order(command))
    # The rig's 20 ms deadline would expire after one attempt on a starved host; this test ends
    # on the third read, so the production 5 s deadline loses nothing and cannot flake.
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_DEADLINE_NS", 5_000_000_000)
    gate = Inject404(client, first=2)  # two 404s, then the venue "catches up"
    real_confirm = client._confirm_resting_order
    verdicts: list[str] = []

    async def spy(*args: Any, **kwargs: Any) -> str:
        verdict: str = await real_confirm(*args, **kwargs)
        verdicts.append(verdict)
        return verdict

    client._confirm_resting_order = spy
    await client._submit_order(command)
    assert len(gate.hits) == 2, "the confirm saw exactly two 404s before the 200"
    assert verdicts == [submit_chain.RESTING_CONFIRM_NEW]
    assert rig.event_names().count("OrderAccepted") == 1
    assert _false_terminals(rig.events) == []
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == [VENUE_ID]
    assert client._latch.open_slot_count() == 0
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("stall_s", [0.0, 0.1], ids=["no_stall", "first_read_stalls"])
async def test_resting_confirm_404_to_deadline_holds_and_intent_stays_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stall_s: float
) -> None:
    rig = await _submit_rig(tmp_path, monkeypatch)
    client = rig.client
    command = _rest_command(client)
    rig.set_get(_venue_order(command))  # the order IS there; only the read 404s
    # The confirm's deadline is read from the client's Python-visible clock. Give it the real
    # 5 s deadline (the rig's 20 ms one is only wall-clock luck: a stall before the second read
    # expires it after ONE attempt) and move the clock past it right after the second 404, so
    # "retried to the deadline" no longer depends on how fast the host is.
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_DEADLINE_NS", 5_000_000_000)

    def expire_after_second_404(hit_count: int) -> None:
        if hit_count == 2:
            client.advance(submit_chain.RESTING_CONFIRM_DEADLINE_S + 1)

    gate = Inject404(client, stall_s=stall_s, on_hit=expire_after_second_404)
    budget_before = _remaining(rig)
    await client._submit_order(command)
    intent = rig.intent()
    assert len(gate.hits) >= 2, "the confirm retried to the deadline"
    assert intent is not None and intent.state.name == "OPEN"
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    assert client._latch.open_slot_count() == 1
    assert intent.intent_id in client._ambiguous_bookings
    assert client._ledger.has_open_exposure(intent.intent_id)
    assert client._store_get(_INDEX_KEY) is None, "nothing bound"
    assert "OrderAccepted" not in rig.event_names()
    assert _false_terminals(rig.events) == []
    assert _remaining(rig) != budget_before, "the booking is HELD, not restored"
    held = _remaining(rig)
    await run_passes(client, 1)  # the resolver also reads 404 -> still held
    assert _remaining(rig) == held
    assert rig.intent() is not None and rig.intent().state.name == "OPEN"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_confirm_404_is_unreadable_not_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _cancel_rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    budget_before = _remaining(rig)
    gate = Inject404(client)
    # the venue DID cancel it; the read 404s, so the client must not conclude anything
    _set_state(rig, 0, "ORDER_STATE_CANCELED")
    verdict = await client._confirm_cancel_terminal(_id_n(0), target.slug)
    assert verdict == submit_chain.CANCEL_READ_UNREADABLE
    pending = await client._cancel_resting_order([_id_n(0)], max_passes=1)
    assert pending == frozenset({_id_n(0)}), "still unconfirmed"
    assert _false_terminals(rig.events) == []
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)], "the row is kept"
    assert client._ledger.has_open_exposure(client._resting_bookings[_id_n(0)][0])
    assert _remaining(rig) == budget_before, "no budget restored"
    assert len(gate.hits) >= 2
    # non-vacuity: the same read, readable, IS terminal
    gate.active = False
    assert await client._confirm_cancel_terminal(_id_n(0), target.slug) == (
        submit_chain.CANCEL_READ_CANCELED
    )
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_with_id_get_404_stays_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    budget_before = _remaining(rig)
    gate = Inject404(client)
    # even a venue that now shows a terminal CANCELED must not be believed through a 404
    rig.set_get(_venue_order(command, state="ORDER_STATE_CANCELED", leavesQuantity=0))
    await run_passes(client, 3)
    assert gate.hits, "the resolver did read the order"
    intent = rig.intent()
    assert intent is not None and intent.intent_id == intent_id and intent.state.name == "OPEN"
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    assert client._latch.open_slot_count() == 1
    assert _false_terminals(rig.events) == []
    assert "OrderAccepted" not in rig.event_names()
    assert _remaining(rig) == budget_before, "no budget restored"
    assert client._ledger.has_open_exposure(intent_id)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_order_404_is_one_strike_not_retire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _cancel_rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    budget_before = _remaining(rig)
    gate = Inject404(client)
    _set_state(rig, 0, "ORDER_STATE_CANCELED")  # a 404 must not let this be believed
    await client._query_order(_query(rig, command))
    assert len(gate.hits) == 1
    assert client._resting_poll_failures == {_id_n(0): 1}, "exactly one strike"
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON not in [
        r.reason for r in client._trading_refusals
    ]
    assert _false_terminals(rig.events) == []
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)], "not retired"
    assert client._ledger.has_open_exposure(intent_id)
    assert _remaining(rig) == budget_before
    # the next readable poll clears the strike and (it IS canceled) retires normally
    gate.active = False
    await client._query_order(_query(rig, command))
    assert client._resting_poll_failures == {}
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_404_per_id_latches_not_certifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two ledger ids; the venue cancels both but the read of id 0 404s. Id 1 confirms and
    retires; id 0 is latched ``resting_cancel_unconfirmed`` and stays in the ledger."""
    rig = await _cancel_rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    src: dict[str, Any] = rig.client._private_read._payloads
    payloads = {
        submit_chain.order_by_id_path(_id_n(n)): src[submit_chain.order_by_id_path(_id_n(n))]
        for n in (0, 1)
    }
    sender = CancelSender()
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender, payloads=payloads
    )
    gate = Inject404(second, frozenset({_id_n(0)}))

    def both_canceled(_oid: str) -> None:
        _set_state_on(second, 0, "ORDER_STATE_CANCELED")
        _set_state_on(second, 1, "ORDER_STATE_CANCELED")

    sender.on_cancel = both_canceled
    await second._connect()
    assert gate.hits, "id 0 was read and 404'd"
    assert sorted(c["order_id"] for c in sender.cancels) == [_id_n(0), _id_n(1)]
    reasons = [r.reason for r in second._trading_refusals]
    assert submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON in reasons, "latched, not certified"
    assert json.loads(second._store_get(_INDEX_KEY)) == [_id_n(0)], "only id 1 retired"
    assert second._swept_resting_intent_ids == frozenset()
    assert second.log_lines("warning", "confirm GET failed")
    await second._disconnect()
