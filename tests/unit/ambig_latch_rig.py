"""Shared rig for the AMBIG-LATCH-RESUME Phase B suites.

Not a test module: a helper, in the shape of ``polymarket_us_exec_shapes.py``.

**It never imports the ``exec`` package itself.** Barrier X1
(``test_execution_egress_firewall_guard.exec_importing_test_modules``) pins, by
set EQUALITY, every test module that does; a new importer is a deliberate
widening of that pin, which this item is not licensed to make. Every ``exec``
symbol the Phase B suites need is therefore reached through the existing,
already-pinned ``test_current_rung_hold_ambiguous_resolver`` module (which
re-exports what it imports) or through the client class's own module object.
The rig opens no socket: every sender and private read is a local double.

The one control this rig drives is the clock. ``Component._clock`` is a
read-only Cython attribute, so a test cannot assign a fake to a built client;
:class:`TimedClient` shadows it with a property that returns an offset clock,
which lets a test move the Python-visible "now" (the resolver's age gates, the
latch ages) forward without sleeping. Native Cython code keeps the real clock.

Operator caps: the rig reaches them only through
``tests/unit/operator_control_env`` (the single whitelisted seam, the same
``with`` pattern every sibling exec suite uses); no value is introduced here
beyond the placeholders those suites already use.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory

from breezy.adapters.polymarket_us.account_activity import PORTFOLIO_ACTIVITIES_PATH
from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit import test_current_rung_hold_ambiguous_resolver as _resolver_tests
from tests.unit import test_current_rung_hold_pre_arm_race as _race_tests
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import build_instrument
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    OPEN_ORDERS_PATH,
    PORTFOLIO_POSITIONS_PATH,
    RESOLVER_CONTEXT_KEY_PREFIX,
    AmbiguousResolverContext,
    PolymarketUSExecutionClient,
    RetirementReason,
    SubmitIntentState,
    _build_client_with_custom_loader,
    _run_resolver_passes,
    submit_chain,
)
from tests.unit.test_current_rung_hold_pre_arm_race import (
    STRATEGY_ID,
    TRADER_ID,
    _build_race_client,
    _SlowSender,
    _submit_command,
)
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,
)

__all__ = [
    "IOC",
    "OPEN_ORDERS_PATH",
    "PORTFOLIO_ACTIVITIES_PATH",
    "PORTFOLIO_POSITIONS_PATH",
    "RESOLVER_CONTEXT_KEY_PREFIX",
    "SEC_NS",
    "AmbiguousResolverContext",
    "PolymarketUSExecutionClient",
    "RaisingSender",
    "RetirementReason",
    "SubmitIntentState",
    "TimedClient",
    "arm_context",
    "boot_second_process",
    "build_client",
    "caps",
    "client_module",
    "gate_env",
    "make_command",
    "ns_to_rfc3339",
    "prior_process",
    "read_context",
    "reboot_client",
    "response_sender",
    "rig_slug",
    "run_passes",
    "submit_chain",
    "trade_row",
    "wire_payloads",
    "write_canonical_verified",
    "write_evidence",
]

#: The PolymarketUSExecutionClient's own module (``exec.client``), reached
#: through the class so this helper contains no ``exec`` import statement.
client_module: Final[Any] = sys.modules[PolymarketUSExecutionClient.__module__]

SEC_NS: Final[int] = 1_000_000_000
IOC: Final[str] = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


class _OffsetClock:
    """``timestamp_ns`` = the real clock + a test-controlled offset."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.offset_ns = 0

    def timestamp_ns(self) -> int:
        return int(self._inner.timestamp_ns()) + self.offset_ns

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _RecordingLog:
    """Delegates to the client's real logger and keeps ``(level, message)``."""

    def __init__(self, inner: Any, records: list[tuple[str, str]]) -> None:
        self._inner = inner
        self._records = records

    def _wrap(self, level: str) -> Any:
        real = getattr(self._inner, level)

        def _call(message: Any, *args: Any, **kwargs: Any) -> Any:
            self._records.append((level, str(message)))
            return real(message, *args, **kwargs)

        return _call

    def __getattr__(self, name: str) -> Any:
        if name in {"debug", "info", "warning", "error", "critical"}:
            return self._wrap(name)
        return getattr(self._inner, name)


class TimedClient(PolymarketUSExecutionClient):  # type: ignore[misc]
    """The real client with a Python-visible movable clock (see module doc).

    ``admitted`` (class attribute, set by :func:`build_client`) is forwarded as
    ``no_id_retire_admitted`` ONLY when a test sets it, so rigs that exercise
    nothing no-id never pass a keyword the client might not yet accept.
    """

    admitted: bool | None = None
    order_events: list[Any]
    latch_cm: Any

    def __init__(self, **kwargs: Any) -> None:
        if type(self).admitted is not None:
            kwargs["no_id_retire_admitted"] = type(self).admitted
        super().__init__(**kwargs)

    @property
    def _clock(self) -> Any:  # type: ignore[override]
        wrapped = self.__dict__.get("_offset_clock")
        if wrapped is None:
            base = PolymarketUSExecutionClient._clock.__get__(self)  # type: ignore[attr-defined]
            wrapped = _OffsetClock(base)
            self.__dict__["_offset_clock"] = wrapped
        return wrapped

    @property
    def _log(self) -> Any:  # type: ignore[override]
        wrapped = self.__dict__.get("_recording_log")
        if wrapped is None:
            base = PolymarketUSExecutionClient._log.__get__(self)  # type: ignore[attr-defined]
            wrapped = _RecordingLog(base, self.log_records)
            self.__dict__["_recording_log"] = wrapped
        return wrapped

    @property
    def log_records(self) -> list[tuple[str, str]]:
        return self.__dict__.setdefault("_log_records", [])

    def log_lines(self, level: str, contains: str = "") -> list[str]:
        return [m for lv, m in self.log_records if lv == level and contains in m]

    @property
    def offset_clock(self) -> _OffsetClock:
        clock = self._clock
        assert isinstance(clock, _OffsetClock)
        return clock

    def advance(self, seconds: float) -> None:
        self.offset_clock.offset_ns += int(seconds * SEC_NS)


# ---------------------------------------------------------------------------
# Environment / builders
# ---------------------------------------------------------------------------


@contextmanager
def caps() -> Iterator[None]:
    """The placeholder caps every sibling exec suite wraps its body in."""
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(
            MAX_POSITION_COST_USD_ENV_VAR,
            "10.00",
        ),
    ):
        yield


@pytest.fixture
def gate_env(
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,
) -> Iterator[None]:
    """Live gate on (2 order slots), canonical string verified, caps bound."""
    del write_canonical_verified
    enable_operator_gate(monkeypatch, order_count="2")
    with caps():
        yield


def wire_payloads(client: Any) -> dict[str, Any]:
    """The mutable payload map behind the client's ``_PrivateReadStub``; also
    makes sure the open-orders path answers (the stub raises ``KeyError`` for
    an unwired path)."""
    payloads: dict[str, Any] = client._private_read._payloads
    payloads.setdefault(OPEN_ORDERS_PATH, {"orders": []})
    return payloads


class RaisingSender:
    """``post_order`` raises the given exception after one loop turn."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.exc: BaseException = exc if exc is not None else VenueTransportError("boom (rig)")

    async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
        await asyncio.sleep(0)
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        raise self.exc


def response_sender(status: int, body: bytes) -> _SlowSender:
    sender = _SlowSender()
    sender.response = VenueResponse(status=status, headers={}, body=body)
    return sender


async def build_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sender: Any,
    admitted: bool | None = None,
    start: bool = False,
) -> tuple[TimedClient, list[Any], Any, Any]:
    """``_build_race_client`` with :class:`TimedClient` substituted for the
    client class (both builder modules reference it as a module global)."""
    TimedClient.admitted = admitted
    monkeypatch.setattr(_race_tests, "PolymarketUSExecutionClient", TimedClient)
    monkeypatch.setattr(_resolver_tests, "PolymarketUSExecutionClient", TimedClient)
    client, order_events, permit, latch_cm = await _build_race_client(tmp_path, sender=sender)
    wire_payloads(client)
    if start:
        client.start()
    assert isinstance(client, TimedClient)
    client.order_events = order_events
    return client, order_events, permit, latch_cm


async def reboot_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_latch_cm: Any,
    first_client: Any,
    admitted: bool | None = None,
    resolver_instrument_loader: Any = None,
) -> tuple[TimedClient, Any]:
    """Model a process restart: release the first process's flock and build a
    fresh client over the SAME durable store (not yet connected)."""
    await first_client._disconnect()
    first_latch_cm.__exit__(None, None, None)
    TimedClient.admitted = admitted
    monkeypatch.setattr(_resolver_tests, "PolymarketUSExecutionClient", TimedClient)
    client, latch_cm = await _build_client_with_custom_loader(
        tmp_path,
        store_path=tmp_path / "exec_state.db",
        resolver_instrument_loader=resolver_instrument_loader,
    )
    wire_payloads(client)
    assert isinstance(client, TimedClient)
    return client, latch_cm


#: ONE factory for the process: its counter is what de-dupes client order ids
#: when a single test submits two orders.
_FACTORY: Final[OrderFactory] = OrderFactory(
    trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock()
)


def make_command(client: Any, *, price: str = "0.40") -> Any:
    """A BUY 1 IOC ``SubmitOrder`` on the shared instrument, with its order
    added to the cache the way the real engine does before the client runs."""
    del price
    command = _submit_command(client, _FACTORY, "a")
    client._cache.add_order(command.order, position_id=None)
    return command


def rig_slug() -> str:
    return instrument_id_to_slug(build_instrument().id)


def read_context(client: Any, intent_id: str) -> Any:
    raw = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
    return None if raw is None else AmbiguousResolverContext.from_bytes(raw)


async def run_passes(client: Any, count: int = 1) -> None:
    await _run_resolver_passes(client, count)


# ---------------------------------------------------------------------------
# Activities rows
# ---------------------------------------------------------------------------


def ns_to_rfc3339(ns: int) -> str:
    """Nanosecond epoch -> ``YYYY-MM-DDTHH:MM:SS.fffffffffZ``."""
    from datetime import UTC, datetime

    seconds, frac = divmod(ns, SEC_NS)
    stamp = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp}.{frac:09d}Z"


def _order_obj(
    *,
    order_id: str,
    slug: str,
    outcome_side: str,
    action: str,
    price: str,
    quantity: Any,
    tif: str,
    manual: bool,
    intent: str,
    side: str,
) -> dict[str, Any]:
    return {
        "id": order_id,
        "marketSlug": slug,
        "side": side,
        "price": {"value": price, "currency": "USD"},
        "quantity": quantity,
        "tif": tif,
        "intent": intent,
        "outcomeSide": outcome_side,
        "action": action,
        "manualOrderIndicator": (
            "MANUAL_ORDER_INDICATOR_MANUAL" if manual else "MANUAL_ORDER_INDICATOR_AUTOMATIC"
        ),
        "createTime": "2026-01-01T00:00:00Z",
    }


def trade_row(
    *,
    ts_ns: int,
    order_id: str,
    slug: str,
    outcome_side: str = "OUTCOME_SIDE_YES",
    action: str = "ORDER_ACTION_BUY",
    price: str = "0.40",
    quantity: Any = 1,
    tif: str = IOC,
    manual: bool = False,
    passive_manual: bool = False,
    intent: str = "ORDER_INTENT_BUY_LONG",
    side: str = "ORDER_SIDE_BUY",
    qty_decimal: str | None = "1.0000",
    passive_id: str | None = None,
) -> dict[str, Any]:
    """One ``ACTIVITY_TYPE_TRADE`` row in the captured shape (aggressor and
    passive order objects under ``trade``)."""
    trade: dict[str, Any] = {
        "id": f"trade-{order_id}",
        "createTime": ns_to_rfc3339(ts_ns),
        "marketSlug": slug,
        "aggressor": _order_obj(
            order_id=order_id,
            slug=slug,
            outcome_side=outcome_side,
            action=action,
            price=price,
            quantity=quantity,
            tif=tif,
            manual=manual,
            intent=intent,
            side=side,
        ),
        "passive": _order_obj(
            order_id=passive_id or f"passive-{order_id}",
            slug=slug,
            outcome_side="OUTCOME_SIDE_NO",
            action="ORDER_ACTION_BUY",
            price=price,
            quantity=5,
            tif="TIME_IN_FORCE_GOOD_TILL_DATE",
            manual=passive_manual,
            intent="ORDER_INTENT_BUY_SHORT",
            side="ORDER_SIDE_SELL",
        ),
    }
    if qty_decimal is not None:
        trade["qtyDecimal"] = qty_decimal
    return {"type": "ACTIVITY_TYPE_TRADE", "trade": trade}


def zero(value: str = "0") -> Decimal:
    return Decimal(value)


# ---------------------------------------------------------------------------
# Hand-built OPEN intents (exact control of created_ns and the baseline)
# ---------------------------------------------------------------------------


def write_evidence(
    client: Any,
    net: str | None,
    *,
    ts_ns: int | None = None,
    eof: bool = True,
    refused: bool = False,
    slug: str | None = None,
) -> int:
    """Write the durable startup evidence the pre-POST baseline is taken from.
    ``net`` is the slug's signed ``netPosition`` string (``None`` = slug absent)."""
    stamp = client._clock.timestamp_ns() if ts_ns is None else ts_ns
    raw = {} if net is None else {(slug or rig_slug()): {"netPosition": net}}
    client._write_startup_position_evidence(
        now_ns=stamp, eof_complete=eof, position_read_refused=refused, raw_positions=raw
    )
    return stamp


def arm_context(
    client: Any,
    *,
    age_s: float,
    instrument: Any = None,
    venue_order_id: str = "",
    wire_slug: str | None = "__default__",
    wire_price: str | None = "0.40",
    wire_outcome_side: str | None = "OUTCOME_SIDE_YES",
    wire_action: str | None = "ORDER_ACTION_BUY",
    baseline_venue_net: str | None = None,
    baseline_durable_net: str | None = None,
    baseline_ts_ns: int | None = None,
    with_context: bool = True,
    notional: str = "0.40",
) -> tuple[str, int]:
    """Arm the singleton ``age_s`` seconds ago and (optionally) write a no-id
    resolver context for it. Returns ``(intent_id, created_ns)``."""
    inst = instrument if instrument is not None else build_instrument()
    created_ns = client._clock.timestamp_ns() - int(age_s * SEC_NS)
    armed = client._latch.arm("5" * 64, now_ns=created_ns)
    if with_context:
        slug = rig_slug() if wire_slug == "__default__" else wire_slug
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=venue_order_id,
            instrument_id=str(inst.id),
            client_order_id="O-HAND-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal(notional),
            booking_id=1,
            created_ns=created_ns,
            order_side="SELL" if wire_action == "ORDER_ACTION_SELL" else "BUY",
            **{
                k: v
                for k, v in {
                    "wire_market_slug": slug,
                    "wire_price": wire_price,
                    "wire_outcome_side": wire_outcome_side,
                    "wire_action": wire_action,
                    "baseline_venue_net": baseline_venue_net,
                    "baseline_durable_net": baseline_durable_net,
                    "baseline_ts_ns": baseline_ts_ns,
                }.items()
                if v is not None
            },
        )
        client._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{armed.intent_id}", context.to_bytes())
    return armed.intent_id, created_ns


async def prior_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_context: str | None,
    age_s: int,
    **context_kwargs: Any,
) -> tuple[Any, Any, str, int]:
    """ "Process 1": arms an intent ``age_s`` seconds ago and writes the given
    resolver context kind ("with_id", "no_id" or ``None``), left for a reboot."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    client, _ev, _permit, latch_cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}")
    )
    intent_id, created_ns = arm_context(
        client,
        age_s=age_s,
        venue_order_id="ord-amb-1" if with_context == "with_id" else "",
        with_context=with_context is not None,
        **(
            {
                "wire_slug": None,
                "wire_price": None,
                "wire_outcome_side": None,
                "wire_action": None,
            }
            if with_context == "with_id"
            else {}
        ),
        **context_kwargs,
    )
    return client, latch_cm, intent_id, created_ns


async def boot_second_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: Any,
    first_cm: Any,
    *,
    admitted: bool,
    in_provider: bool = True,
    instrument: Any = None,
) -> tuple[TimedClient, Any]:
    """Reboot over the first process's store; the shared instrument is in the
    cache and (``in_provider``) in the provider. A past-day shape (not in the
    provider) gets a second instrument so the provider is never empty."""
    client, cm = await reboot_client(
        tmp_path, monkeypatch, first_latch_cm=first_cm, first_client=first, admitted=admitted
    )
    inst = instrument if instrument is not None else build_instrument()
    client._cache.add_instrument(inst)
    if in_provider:
        client._instrument_provider.add(inst)
    else:
        from tests.unit.polymarket_us_exec_shapes import build_second_instrument

        other = build_second_instrument()
        client._cache.add_instrument(other)
        client._instrument_provider.add(other)
    return client, cm
