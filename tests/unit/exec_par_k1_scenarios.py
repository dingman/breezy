"""K=1 behavioural scenarios for the EXEC-PAR WP4 differential replay.

Not a test module. ``run_k1_scenarios`` drives the shipped K=1 wiring through
the create path (zero-fill, accept-fill, reject, AMBIGUOUS with and without an
id) and the resolver (terminal-zero, accept-fill, no-id no-fill) on a fixed
clock with deterministic ids, and returns a normalised, JSON-able record of
everything observable: the ordered native events and denial reasons, the
durable write sequence, the latched refusals, the permit and the ledger.

``tests/unit/golden_exec_par_wp4_k1.json`` was captured from the code BEFORE
any WP4 change to ``exec/client.py``. The only normalisation that hides a
difference is dropping the context blob's ``wireQuantity`` key (enumerated
delta D6): everything else must be byte-identical (D1-D5 do not occur in these
scenarios, which is itself part of what the replay proves).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit.exec_par_rig import (
    OPEN_ORDERS_PATH,
    PORTFOLIO_ACTIVITIES_PATH,
    PORTFOLIO_POSITIONS_PATH,
    FakeOrderSender,
    ParRig,
    accept_fill_body,
    ambiguous_body,
    build_par_rig,
    caps,
    reject_body,
    zero_fill_body,
)
from tests.unit.polymarket_us_exec_shapes import build_instrument
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    _backdate_resolver_context,
    _order_get_body,
    _run_resolver_passes,
)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
#: Dropped on comparison only: enumerated delta D6 (the context blob gains it).
_D6_KEYS = frozenset({"wireQuantity"})


class _Names:
    """Maps each distinct 32-hex id to a stable first-seen alias."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self._bookings: dict[int, str] = {}

    def alias(self, value: str) -> str:
        if value not in self._seen:
            self._seen[value] = f"<ID{len(self._seen) + 1}>"
        return self._seen[value]

    def booking(self, value: int) -> str:
        """``SpendBooking`` ids come from a PROCESS-GLOBAL counter, so they depend
        on how many bookings earlier tests made: alias them by first sight."""
        if value not in self._bookings:
            self._bookings[value] = f"<BK{len(self._bookings) + 1}>"
        return self._bookings[value]


def _norm(value: Any, names: _Names) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _D6_KEYS:
                continue
            if key == "bookingId" and type(item) is int and item > 0:
                out[_norm_text(key, names)] = names.booking(item)
            else:
                out[_norm_text(key, names)] = _norm(item, names)
        return out
    if isinstance(value, list):
        return [_norm(v, names) for v in value]
    if isinstance(value, str):
        return _norm_text(value, names)
    return value


def _norm_text(text: str, names: _Names) -> str:
    if _HEX32.match(text):
        return names.alias(text)
    return re.sub(r"[0-9a-f]{32}", lambda m: names.alias(m.group(0)), text)


def _decode(raw: bytes, names: _Names) -> Any:
    try:
        return _norm(json.loads(raw), names)
    except ValueError:
        return raw.decode("utf-8", "replace")


async def snapshot(rig: ParRig) -> dict[str, Any]:
    """Record everything observable, then close the client and release the flock."""
    names = _Names()
    client = rig.client
    record = {
        "events": [[type(e).__name__, getattr(e, "reason", None)] for e in rig.order_events],
        "refusals": list(client.trading_refusals),
        "permit": [str(v) for v in rig.remaining_permit()],
        "spent": str(rig.ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns())),
        "sender_calls": len(rig.sender.calls),
        "resolver_errors": client.resolver_error_count,
        "bookings_held": sorted(_norm_text(k, names) for k in client._ambiguous_bookings),
        "writes": [[_norm_text(k, names), _decode(v, names)] for k, v in rig.writes],
    }
    await client._disconnect()
    rig.latch_cm.__exit__(None, None, None)
    return record


def _deterministic_ids() -> Any:
    ids = iter(uuid.UUID(int=i) for i in range(1, 400))
    return patch("breezy.runtime.submit_intent.uuid.uuid4", lambda: next(ids))


async def _rig(tmp: Path, mp: pytest.MonkeyPatch, sender: Any, **kw: Any) -> ParRig:
    tmp.mkdir(parents=True, exist_ok=True)
    return await build_par_rig(tmp, mp, sender=sender, record_writes=True, **kw)


def _sender(body: bytes, status: int = 200) -> FakeOrderSender:
    sender = FakeOrderSender()
    sender.response = VenueResponse(status=status, headers={}, body=body)
    return sender


class _RaisingSender(FakeOrderSender):
    async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        raise RuntimeError("transport down (scenario)")


def _slug() -> str:
    return instrument_id_to_slug(build_instrument().id)


async def zero_fill_create(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _sender(zero_fill_body(order_id="ord-z1")))
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def accept_fill_create(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _sender(accept_fill_body(_slug(), order_id="ord-f1")))
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def reject_create(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _sender(reject_body(), status=400))
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def ambiguous_then_wait(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _sender(ambiguous_body("ord-a1")))
    await rig.client._submit_order(rig.buy())
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def refusal_latched_denies(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _sender(zero_fill_body(order_id="ord-r1")))
    rig.client._refuse("scenario refusal")
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def _ambiguous_aged(tmp: Path, mp: pytest.MonkeyPatch, order_id: str) -> ParRig:
    rig = await _rig(tmp, mp, _sender(ambiguous_body(order_id)))
    await rig.client._submit_order(rig.buy())
    (intent_id,) = [i.intent_id for i in rig.latch.open_submit_intents()]
    _backdate_resolver_context(rig.client, intent_id)
    return rig


def _wire_get(rig: ParRig, order_id: str, **body: Any) -> None:
    payloads = rig.client._private_read._payloads
    payloads[f"/v1/order/{order_id}"] = _order_get_body(order_id, slug=_slug(), **body)


async def ambiguous_then_resolver_zero_fill(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _ambiguous_aged(tmp, mp, "ord-az1")
    _wire_get(rig, "ord-az1", state="ORDER_STATE_CANCELED", cum_quantity=0)
    payloads = rig.client._private_read._payloads
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}
    await _run_resolver_passes(rig.client, count=1)
    return await snapshot(rig)


async def ambiguous_then_resolver_accept_fill(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _ambiguous_aged(tmp, mp, "ord-af1")
    _wire_get(rig, "ord-af1", state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
    payloads = rig.client._private_read._payloads
    payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {_slug(): {"netPosition": "1"}},
        "eof": True,
    }
    await _run_resolver_passes(rig.client, count=1)
    return await snapshot(rig)


async def no_response_then_wait(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _RaisingSender())
    await rig.client._submit_order(rig.buy())
    await rig.client._submit_order(rig.buy())
    return await snapshot(rig)


async def no_response_then_no_id_no_fill(tmp: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    rig = await _rig(tmp, mp, _RaisingSender(), client_kwargs={"no_id_retire_admitted": True})
    await rig.client._submit_order(rig.buy())
    rig.client.set_now(rig.clock.timestamp_ns() + 400 * 1_000_000_000)
    payloads = rig.client._private_read._payloads
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}
    payloads[OPEN_ORDERS_PATH] = {"orders": []}
    payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
    await _run_resolver_passes(rig.client, count=1)
    return await snapshot(rig)


SCENARIOS: dict[str, Callable[[Path, pytest.MonkeyPatch], Any]] = {
    "zero_fill_create": zero_fill_create,
    "accept_fill_create": accept_fill_create,
    "reject_create": reject_create,
    "ambiguous_then_wait": ambiguous_then_wait,
    "refusal_latched_denies": refusal_latched_denies,
    "ambiguous_then_resolver_zero_fill": ambiguous_then_resolver_zero_fill,
    "ambiguous_then_resolver_accept_fill": ambiguous_then_resolver_accept_fill,
    "no_response_then_wait": no_response_then_wait,
    "no_response_then_no_id_no_fill": no_response_then_no_id_no_fill,
}


async def run_k1_scenarios(tmp_path: Path, mp: pytest.MonkeyPatch) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with caps(), _deterministic_ids():
        for name, scenario in SCENARIOS.items():
            results[name] = await scenario(tmp_path / name, mp)
    normalised: dict[str, Any] = json.loads(json.dumps(results, sort_keys=True, default=str))
    return normalised
