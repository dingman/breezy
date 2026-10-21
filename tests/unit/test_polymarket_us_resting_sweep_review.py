"""S4 WP4 (ARM maker-sharp B5 review G6, G7, G13, G16): the boot sweep's refusal paths.

The sweep is the cancel-on-stop enforcement and the only retirement route for a prior
process's rests. Whenever it cannot finish -- it does not run, a ledger id is still listed
after the per-id pass, the claim "unbound orders are never cancelled" stops being true, or
the whole sweep overruns -- it LATCHES ``resting_cancel_unconfirmed`` (new rests refused, the
never-arm gate refuses) instead of leaving only a log line.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.strategy.current_rung_hold.trial_day_latch import startup_evidence_refusal_reason
from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import CancelSender, _rig
from tests.unit.test_polymarket_us_resting_robustness import hand_bind
from tests.unit.test_polymarket_us_resting_submit import _id_n, _rest_command, _submit_rest
from tests.unit.test_polymarket_us_resting_sweep import (
    _EVIDENCE_KEY,
    _open_row,
    _second_process,
    _set_state_on,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_unverified,  # noqa: F401 -- used via usefixtures
)

_LATCH: Final[str] = submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON


def _latched(client: Any) -> bool:
    return _LATCH in [r.reason for r in client._trading_refusals]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_sweep_that_does_not_run_latches_and_the_gate_refuses_the_own_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G6: the rest could not be cancelled and the gate exempts own orders, so the
    refusal must be the latch (and the evidence must say so), not just a log line."""
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=None,
        payloads={OPEN_ORDERS_PATH: {"orders": [_open_row(command, 0)]}},
    )
    await second._connect()
    assert _latched(second)
    evidence = json.loads(second._store_get(_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [True]
    assert evidence["resting_cancel_unconfirmed"] is True
    assert startup_evidence_refusal_reason(evidence) == "resting_cancel_unconfirmed"
    assert not second.log_lines("error", "arm gate keeps refusing")
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env", "write_canonical_unverified")
async def test_a_sweep_with_the_canonical_string_unverified_latches_and_posts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same latch for an unverified canonical string (the ledger is bound by hand: a
    submit cannot run while the canonical string is unverified)."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    hand_bind(client, _rest_command(client), 0)
    await client._sweep_resting_orders_at_boot()
    assert _latched(client)
    assert client.log_lines("error", "sweep does not run")
    assert rig.sender.cancels == [] and rig.sender.cancel_alls == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_sweep_with_nothing_to_cancel_does_not_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=None
    )
    await second._connect()
    assert not _latched(second)
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("still_listed", [True, False])
async def test_a_ledger_id_still_listed_open_after_the_per_id_pass_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, still_listed: bool
) -> None:
    """G7: the per-id GET read the order terminal, but the unfiltered re-read still LISTS
    it -- the two disagree, so nothing may be certified: latch."""
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    payloads: dict[str, Any] = rig.client._private_read._payloads
    sender = CancelSender()
    listed = [_open_row(command, 0)] if still_listed else []
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=sender,
        payloads={
            submit_chain.order_by_id_path(_id_n(0)): payloads[
                submit_chain.order_by_id_path(_id_n(0))
            ],
            OPEN_ORDERS_PATH: {"orders": listed},
        },
    )
    sender.on_cancel = lambda oid: _set_state_on(second, 0, "ORDER_STATE_CANCELED")
    await second._connect()
    assert _latched(second) is still_listed
    if still_listed:
        assert second.log_lines("error", "boot_sweep_ledger_id_still_listed")
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_hung_sweep_is_bounded_latches_and_connect_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G16: the per-order bound does not bound the SWEEP (many ids, each with a venue
    round trip). An overall wall-clock deadline latches and lets ``_connect`` finish."""
    monkeypatch.setattr(submit_chain, "BOOT_SWEEP_DEADLINE_S", 0.2)
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    sender = CancelSender()
    sender.gate = asyncio.Event()  # never set: the first cancel POST hangs forever
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender
    )
    await asyncio.wait_for(second._connect(), 5.0)
    assert _latched(second)
    assert second.log_lines("error", "boot_sweep_reread_failed:TimeoutError")
    assert second._cancel_in_flight == frozenset(), "the hung loop released its guard"
    assert second._store_get(_EVIDENCE_KEY), "the evidence write still ran"
    assert second._swept_resting_intent_ids == frozenset()
    await second._disconnect()


_NEVER_CANCELLED_CLAIM: Final[str] = (
    "Unbound orders are NEVER cancelled only while SLUG_SCOPED_CANCEL_ALL_VERIFIED is False"
)


def test_the_unbound_never_cancelled_claim_is_scoped_to_the_slug_pin_being_false() -> None:
    """G13: "unbound orders are never cancelled" is a property of the pin being False. With
    the pin True the slug cancel-all removes an unbound order on a ledger slug (spec 9.18),
    so the sweep's docstring must say the claim is conditional."""
    doc = " ".join(
        (
            inspect.getdoc(client_module.PolymarketUSExecutionClient._sweep_resting_orders_at_boot)
            or ""
        ).split()
    )
    assert _NEVER_CANCELLED_CLAIM in doc


def test_flipping_the_slug_pin_requires_reconciling_the_never_cancelled_claim() -> None:
    """The reconciliation tripwire. Flipping ``SLUG_SCOPED_CANCEL_ALL_VERIFIED`` to ``True``
    must be done in the same reviewed change that (a) rewrites the sweep docstring, r4 5.4
    and spec 9.18 so no one still reads "unbound orders are never cancelled", and (b) edits
    this test. It fails loudly until then. (The pin-True behaviour itself -- a WARN naming
    each unbound order, then the slug cancel-all -- is pinned in
    ``test_polymarket_us_resting_sweep.py``.)"""
    assert submit_chain.SLUG_SCOPED_CANCEL_ALL_VERIFIED is False, (
        "the slug pin was flipped: reconcile the sweep docstring, r4 5.4 and spec 9.18 "
        "('unbound orders are never cancelled') before editing this test"
    )
