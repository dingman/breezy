"""EXEC-PAR WP7 (r5 5.WP7): failure injection on the order path and across restarts.

* A simulated process death at every step between ``arm_slot`` and the end of the
  POST, then a restart over the SAME durable store: no slot may ever be POSTed
  twice (the slot table is the only thing standing between a crash and a
  duplicate order).
* A POST timeout leaves the slot open and the slug denied.
* A restart with three open slots re-books and resolves each of them.

Everything drives the REAL client, latch and ledger through ``exec_par_rig`` at
K > 1 via the client's slot-capacity parameters (``EXEC_PAR_MAX_CONCURRENT_
INTENTS`` is never touched). Only the venue sender is a double, so nothing here
can reach the network. A crash is a ``BaseException`` subclass: no
``except Exception`` handler on the order path runs, exactly as for a killed
process. Caps are bound only through the whitelisted ``caps`` seam.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.operator_controls import DailySpendLedger
from breezy.runtime.submit_intent import CURRENT_INTENT_KEY
from tests.unit.exec_par_rig import (
    ParRig,
    ScriptedSender,
    ambiguous_body,
    arm_open_intent,
    backdate,
    build_par_rig,
    caps,
    decimal_spent,
    ok,
    par_rig,
    reboot,
    run_passes,
    submit_chain,
    wire_order,
    wire_positions,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

WAIT = submit_chain.OPEN_INTENT_WAIT_REASON


class _Crash(BaseException):
    """A simulated process death (not an ``Exception``: no handler may swallow it)."""


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise _Crash


class _CrashRegisterLedger(DailySpendLedger):
    """The real ledger whose exposure registration kills the process."""

    def register_open_exposure(self, *args: Any, **kwargs: Any) -> None:
        raise _Crash


class _CrashSender:
    """Dies once at the POST: before any byte leaves, or after the bytes left.

    Not a ``ScriptedSender`` subclass: the B9 pin counts ``post_order`` call sites
    across the whole tree, so this double records and answers by itself.
    """

    def __init__(self, mode: str | None, *responses: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = list(responses)
        self._mode = mode

    async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
        mode, self._mode = self._mode, None
        if mode == "post_before_send":
            raise _Crash
        index = len(self.calls)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        if mode == "post_after_send":
            raise _Crash
        return self.responses[min(index, len(self.responses) - 1)]


#: Every step of ``_submit_order`` between the durable ``arm_slot`` and the end of
#: the POST (the reply having been received but not yet acted on included).
CRASH_POINTS = (
    "after_arm_slot",
    "register_open_exposure",
    "note_ambiguous_open",
    "after_note_ambiguous_open",
    "sign_headers",
    "post_before_send",
    "post_after_send",
    "after_reply_before_classify",
)
#: The points after which the wire bytes had left the process.
_BYTES_LEFT = frozenset({"post_after_send", "after_reply_before_classify"})


def _install_crash(rig: ParRig, point: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Arm a ONE-SHOT crash at ``point`` on a freshly built rig."""
    if point == "after_arm_slot":
        real_arm = rig.latch.arm_slot

        def arm_then_die(*args: Any, **kwargs: Any) -> Any:
            real_arm(*args, **kwargs)
            raise _Crash

        monkeypatch.setattr(rig.latch, "arm_slot", arm_then_die)
    elif point == "note_ambiguous_open":
        monkeypatch.setattr(rig.client, "_note_ambiguous_open", _boom)
    elif point == "after_note_ambiguous_open":
        real_note = rig.client._note_ambiguous_open

        def note_then_die(*args: Any, **kwargs: Any) -> Any:
            real_note(*args, **kwargs)
            raise _Crash

        monkeypatch.setattr(rig.client, "_note_ambiguous_open", note_then_die)
    elif point == "sign_headers":
        monkeypatch.setattr(rig.client._write_signer, "sign_headers", _boom)
    elif point == "after_reply_before_classify":
        real_classify = submit_chain.classify_create_order_outcome
        armed = {"live": True}

        def classify_once_then_live(*args: Any, **kwargs: Any) -> Any:
            if armed["live"]:
                armed["live"] = False
                raise _Crash
            return real_classify(*args, **kwargs)

        monkeypatch.setattr(submit_chain, "classify_create_order_outcome", classify_once_then_live)
    # register_open_exposure is a ledger subclass; post_* live in the sender.


@pytest.mark.asyncio
@pytest.mark.parametrize("point", CRASH_POINTS)
async def test_crash_at_every_line_arm_slot_to_post_no_double_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    point: str,
) -> None:
    sender = _CrashSender(
        point if point.startswith("post_") else None,
        ok(zero_fill_body(order_id="ord-1")),
        ok(zero_fill_body(order_id="ord-2")),
    )
    with caps():
        first = await build_par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=2,
            ledger=_CrashRegisterLedger() if point == "register_open_exposure" else None,
        )
        _install_crash(first, point, monkeypatch)
        with pytest.raises(_Crash):
            await first.client._submit_order(first.buy(first.instrument))
        posted_before_death = len(sender.calls)
        assert posted_before_death == (1 if point in _BYTES_LEFT else 0), point
        assert first.latch.open_slot_count() == 1, "the slot was durable before the death"

        second = await reboot(first, monkeypatch, sender=sender, max_slots=2)
        try:
            assert second.latch.open_slot_count() == 1, "the restart inherits the open slot"
            # The strategy re-hunts the same market after the restart.
            await second.client._submit_order(second.buy(second.instrument))

            assert len(second.denied_reasons()) == 1, "the retry on the open slug is denied"
            assert len(sender.calls) == posted_before_death, "no second POST for the slot"
            assert len(sender.calls) <= 1
            bodies = [call["body"] for call in sender.calls]
            assert len(set(bodies)) == len(bodies), "never the same wire body twice"
        finally:
            await second.close()


# ---------------------------------------------------------------------------
# POST timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("post timed out"), ConnectionResetError("reset")])
async def test_post_timeout_leaves_slot_and_slug_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    failure: Exception,
) -> None:
    sender = ScriptedSender(failure, ok(zero_fill_body(order_id="ord-other")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            slug_a, slug_b = rig.slug(0), rig.slug(1)
            await rig.client._submit_order(rig.buy(rig.instruments[0]))

            assert len(sender.calls) == 1
            (intent,) = rig.latch.open_submit_intents()
            assert intent.slug == slug_a, "the timed-out take still holds its slot"
            assert rig.client.trading_refusal_scopes == (slug_a,), "scoped, not global"
            assert rig.latch.admission_refusal(slug_a, False) == "slug_open"

            # Time passing does not free the slot: only the resolver may retire it.
            rig.client.advance(300)
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert len(sender.calls) == 1, "no re-POST on the ambiguous slug"
            expected = submit_chain.latched_refusal_reason(submit_chain.AMBIGUOUS_REASON)
            assert rig.denied_reasons() == [expected]
            assert rig.latch.is_open_intent(intent.intent_id)

            # The other slug is not collateral damage of the scoped refusal.
            rig.latch.write_breaker_heartbeat(
                hb_ns=rig.clock.timestamp_ns(), resolver_pass_ns=rig.clock.timestamp_ns()
            )
            assert rig.latch.admission_refusal(slug_b, False) is None
            await rig.client._submit_order(rig.buy(rig.instruments[1]))
            assert len(sender.calls) == 2


# ---------------------------------------------------------------------------
# Restart with three open slots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_with_three_open_slots_rebooks_and_resolves_each(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    names = ("ord-a", "ord-b", "ord-c")
    with caps():
        first = await build_par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=3, connect=False
        )
        ids = [
            arm_open_intent(first, index, venue_order_id=name, notional="0.40")
            for index, name in enumerate(names)
        ]
        raw = json.loads(first.latch._store.get(CURRENT_INTENT_KEY))
        assert raw["v"] == 2 and len(raw["slots"]) == 3

        sender = ScriptedSender()
        second = await reboot(first, monkeypatch, sender=sender, max_slots=3)
        try:
            # (1) every inherited slot is re-booked as uncharged AMBIGUOUS exposure
            assert all(second.ledger.has_open_exposure(i) for i in ids)
            assert second.ledger.uncharged_open_total() == Decimal("1.20")
            assert second.ledger.ambiguous_open_total() == Decimal("1.20")
            assert decimal_spent(second) == Decimal(0), "re-booking charges nothing"
            assert second.latch.max_slots() == 3

            # (2) the resolver retires each one on terminal-zero venue evidence
            for index, name in enumerate(names):
                wire_order(second, name, index, state="ORDER_STATE_CANCELED", cum_quantity=0)
            wire_positions(second, {})
            for intent_id in ids:
                backdate(second.client, intent_id)
            await run_passes(second.client, count=8)

            assert not any(second.latch.is_open_intent(i) for i in ids)
            assert not any(second.ledger.has_open_exposure(i) for i in ids)
            assert second.ledger.uncharged_open_total() == Decimal(0)
            assert sender.calls == [], "resolution reads the venue; it never POSTs"
            drained = json.loads(second.latch._store.get(CURRENT_INTENT_KEY))
            assert drained["v"] == 1 and drained["state"] == "RETIRED"
            # each retired slug is cooling off, so a late fill cannot be doubled up
            assert all(second.latch.admission_refusal(second.slug(i), False) for i in range(3))
        finally:
            await second.close()


@pytest.mark.asyncio
async def test_restart_after_with_id_ambiguous_take_rebooks_and_resolves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """A with-id AMBIGUOUS take, killed right after the POST reply, resolves after restart."""
    sender = ScriptedSender(ok(ambiguous_body("ord-1")))
    with caps():
        first = await build_par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2)
        await first.client._submit_order(first.buy(first.instrument))
        (intent_id,) = first.open_intent_ids()
        second = await reboot(first, monkeypatch, sender=ScriptedSender(), max_slots=2)
        try:
            assert second.ledger.has_open_exposure(intent_id)
            wire_order(second, "ord-1", 0, state="ORDER_STATE_CANCELED", cum_quantity=0)
            wire_positions(second, {})
            backdate(second.client, intent_id)
            await run_passes(second.client, count=4)
            assert not second.latch.is_open_intent(intent_id)
            assert not second.ledger.has_open_exposure(intent_id)
        finally:
            await second.close()
