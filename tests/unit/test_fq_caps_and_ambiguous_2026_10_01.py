"""FQ-S6 (plan §3 S6 test 5, test 6): the operator caps and the AMBIGUOUS-
intent resolver apply to an fq-labelled order exactly as they do to CRH's.

Both guards (`DailySpendLedger.authorize_order_cost`, the submit-intent
latch's WAIT refusal) live entirely in the shared, family-agnostic exec
client (D8) -- there is no fq-specific code path to wire. These tests prove
that reuse by actually driving an fq-``StrategyId``-tagged order through it,
never by inspection alone, reusing the established `_build_accept_fill_rig`
R-7 harness (`test_polymarket_us_exec_client.py`) rather than a second,
drifting one.

Per plan §8/invariants: no test here reads, assigns, or logs a real
operator-reserved cap VALUE outside the whitelisted
`operator_control_env`/`operator_control_unset` test seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderDenied
from nautilus_trader.model.identifiers import StrategyId
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit.operator_control_env import operator_control_env, operator_control_unset
from tests.unit.test_polymarket_us_exec_client import (
    TRADER_ID,
    _AcceptFillRig,
    _build_accept_fill_rig,
    _FakeOrderSender,
)
from tests.unit.test_polymarket_us_submit_order_chain import write_canonical_verified  # noqa: F401

FQ_STRATEGY_ID = StrategyId("FORECAST-QUANTILE-LADDER-LAX")
FQ_ORDER_PRICE = "0.63"


class _RaisingOrderSender(_FakeOrderSender):
    """A `_FakeOrderSender` whose `post_order` raises once armed -- the
    SAME AMBIGUOUS-triggering shape `test_polymarket_us_submit_order_chain
    .py`'s own `_FakeSender.error` already provides, redeclared as a real
    `_FakeOrderSender` subclass so it satisfies `_build_accept_fill_rig`'s
    concrete parameter type.
    """

    def __init__(self) -> None:
        super().__init__()
        self.error: BaseException | None = None

    async def post_order(
        self, base_url: str, *, headers: Mapping[str, str], body: bytes,
    ) -> VenueResponse:
        self.calls.append({"base_url": base_url, "headers": dict(headers), "body": body})
        if self.error is not None:
            raise self.error
        return self.response


def _fq_submit_order(rig: _AcceptFillRig, *, price: str = FQ_ORDER_PRICE) -> SubmitOrder:
    """The exact order shape ``ForecastQuantileLadderStrategy._maybe_submit``
    builds (LIMIT/IOC/BUY/qty 1), tagged with an fq ``StrategyId`` -- never
    the CRH one the shared rig's own ``limit_buy()`` hardcodes.
    """
    from nautilus_trader.common.factories import OrderFactory

    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=FQ_STRATEGY_ID, clock=rig.clock)
    order = factory.limit(
        instrument_id=rig.instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, rig.instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
    )
    return SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=FQ_STRATEGY_ID,
        order=order,
        command_id=UUID4(),
        ts_init=0,
    )


@pytest.mark.asyncio
async def test_fq_order_denied_when_per_position_cap_is_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        # Cost (0.63) exceeds this ceiling -- the per-position deny path.
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "0.10"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == [], "a per-position cap deny must never reach the venue"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert MAX_POSITION_COST_USD_ENV_VAR in denials[0].reason
    assert "0.63" not in denials[0].reason and "0.10" not in denials[0].reason
    assert rig.client._ledger is not None
    assert rig.client._ledger.spent_today_usd(now_ns=rig.clock.timestamp_ns()) == Decimal(0)


@pytest.mark.asyncio
async def test_fq_order_denied_when_daily_budget_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        # Cost (0.63) exceeds this ceiling -- the daily-budget deny path.
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "0.10"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == []
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert MAX_DAILY_BUDGET_USD_ENV_VAR in denials[0].reason


@pytest.mark.asyncio
async def test_fq_order_denied_when_neither_control_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        await rig.client._disconnect()

    assert sender.calls == [], "absence of either control must refuse, never default-permit"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1


@pytest.mark.asyncio
async def test_fq_order_resolved_ambiguous_then_the_next_take_is_latch_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_canonical_verified: None,  # noqa: F811
) -> None:
    """An fq-tagged order whose `post_order` raises classifies AMBIGUOUS
    (the shared resolver, D8): the client latches a trading refusal
    (``submit_chain.latched_refusal_reason``) and will not act on venue
    state it could not attribute -- so a SECOND fq take is refused on that
    SAME shared, family-agnostic latch, never special-cased for fq (plan §3
    S6 test 6). The first order itself gets no `OrderDenied` (it reaches the
    venue and only its RESPONSE is unattributable); only the second,
    latch-refused one does.
    """
    sender = _RaisingOrderSender()
    sender.error = ConnectionError("simulated transport failure")
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await rig.client._connect()
        await rig.client._submit_order(_fq_submit_order(rig))
        # The first intent is now AMBIGUOUS/latched -- a second fq take must
        # be refused on that SAME latch, never submit a second order.
        await rig.client._submit_order(_fq_submit_order(rig, price="0.64"))
        await rig.client._disconnect()

    assert len(sender.calls) == 1, "the second take must never reach the venue once latched"
    denials = [event for event in rig.order_events if isinstance(event, OrderDenied)]
    assert len(denials) == 1
    assert "AMBIGUOUS" in denials[0].reason
    assert denials[0].reason == submit_chain.latched_refusal_reason(
        "create-order outcome is AMBIGUOUS; latch stays open and the booking is held",
    )
# ---------------------------------------------------------------------------
# 2026-10-02 incident: the AMBIGUOUS refusal outlived its own retired intent.
#
# The automated resolver's terminal ZERO-FILL path retires the durable intent
# and trues the booking to zero, but the instrument-unscoped AMBIGUOUS entry
# `_refuse` appended at create time stayed in `_trading_refusals`, so every
# later `_submit_order` was denied for the rest of the session. These pins
# drive the REAL resolver pass (the rig lives in the resolver test module).
# ---------------------------------------------------------------------------

_AMBIGUOUS_REASON = submit_chain.AMBIGUOUS_REASON
_UNRELATED_REFUSAL = "unrelated latched refusal for the clear-scope pin"


async def _take(client: object, ordinal: int) -> SubmitOrder:
    """One more take on the resolver rig's own strategy and instrument.

    ``ordinal`` seeds the factory's client-order-id counter past the id the
    rig's own first take already used, so the cache never sees a duplicate.
    """
    from nautilus_trader.common.component import LiveClock
    from nautilus_trader.common.factories import OrderFactory

    from tests.unit.test_current_rung_hold_pre_arm_race import (
        STRATEGY_ID,
        _submit_command,
    )
    from tests.unit.test_current_rung_hold_pre_arm_race import (
        TRADER_ID as RACE_TRADER_ID,
    )

    factory = OrderFactory(trader_id=RACE_TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    factory.set_client_order_id_count(ordinal)
    command = _submit_command(client, factory, "")  # type: ignore[arg-type]
    client._cache.add_order(command.order, position_id=None)  # type: ignore[attr-defined]
    return command


def _denial_reasons(order_events: list[Any]) -> list[str]:
    return [event.reason for event in order_events if isinstance(event, OrderDenied)]


def _set_get_evidence(
    client: object,
    order_id: str,
    slug: str,
    *,
    state: str,
    cum: float,
    positions: dict[str, Any],
    eof: bool = True,
    avg_px: str | None = None,
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _order_get_body

    payloads = client._private_read._payloads  # type: ignore[attr-defined]
    payloads[f"/v1/order/{order_id}"] = _order_get_body(
        order_id,
        slug=slug,
        state=state,
        cum_quantity=cum,
        avg_px=avg_px,
    )
    payloads["/v1/portfolio/positions"] = {"positions": positions, "eof": eof}


@pytest.mark.asyncio
async def test_terminal_zero_fill_retirement_clears_ambiguous_refusal_and_a_take_reaches_sender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import (
        _arm_one_ambiguous_intent,
        _run_resolver_passes,
    )
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(tmp_path)
        sender = client._order_sender
        assert _AMBIGUOUS_REASON in client.trading_refusals
        await client._submit_order(await _take(client, 10))
        assert len(sender.calls) == 1, "a second take is latch-refused while the intent is open"
        assert len(_denial_reasons(order_events)) == 1

        _set_get_evidence(client, order_id, slug, state="ORDER_STATE_CANCELED", cum=0, positions={})
        await _run_resolver_passes(client, count=1)

        assert client._latch.current_open() is None
        assert _AMBIGUOUS_REASON not in client.trading_refusals
        await client._submit_order(await _take(client, 20))
        assert len(sender.calls) == 2, "a take after the clear must reach the sender"
        assert len(_denial_reasons(order_events)) == 1, "no further denial after the clear"
        await client._disconnect()


@pytest.mark.asyncio
async def test_terminal_zero_fill_retirement_keeps_an_unrelated_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import (
        _arm_one_ambiguous_intent,
        _run_resolver_passes,
    )
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, order_id, slug, _latch_cm, _events = await _arm_one_ambiguous_intent(tmp_path)
        client._refuse(_UNRELATED_REFUSAL)
        _set_get_evidence(client, order_id, slug, state="ORDER_STATE_CANCELED", cum=0, positions={})
        await _run_resolver_passes(client, count=1)

        assert client._latch.current_open() is None
        assert _UNRELATED_REFUSAL in client.trading_refusals
        await client._disconnect()


@pytest.mark.asyncio
async def test_an_incomplete_positions_read_neither_retires_nor_clears_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import (
        _arm_one_ambiguous_intent,
        _run_resolver_passes,
    )
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, order_id, slug, _latch_cm, _events = await _arm_one_ambiguous_intent(tmp_path)
        _set_get_evidence(
            client,
            order_id,
            slug,
            state="ORDER_STATE_CANCELED",
            cum=0,
            positions={},
            eof=False,
        )
        await _run_resolver_passes(client, count=2)

        assert client._latch.current_open() is not None
        assert _AMBIGUOUS_REASON in client.trading_refusals
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_non_terminal_get_neither_retires_nor_clears_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import (
        _arm_one_ambiguous_intent,
        _run_resolver_passes,
    )
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, order_id, slug, _latch_cm, _events = await _arm_one_ambiguous_intent(tmp_path)
        _set_get_evidence(client, order_id, slug, state="ORDER_STATE_NEW", cum=0, positions={})
        await _run_resolver_passes(client, count=2)

        assert client._latch.current_open() is not None
        assert _AMBIGUOUS_REASON in client.trading_refusals
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import (
        _arm_one_ambiguous_intent,
        _run_resolver_passes,
    )
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, order_id, slug, _latch_cm, _events = await _arm_one_ambiguous_intent(tmp_path)
        _set_get_evidence(
            client,
            order_id,
            slug,
            state="ORDER_STATE_FILLED",
            cum=1,
            positions={slug: {"netPosition": "1"}},
            avg_px="0.40",
        )
        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        assert _AMBIGUOUS_REASON in client.trading_refusals
        await client._disconnect()


async def _armed_zero_fill_rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, Any]:
    """The resolver rig with terminal zero-fill evidence already wired in.

    Returns ``(client, latch_cm)``; the caller MUST keep ``latch_cm``
    referenced (dropping it GCs the generator and releases the flock).
    """
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _arm_one_ambiguous_intent
    from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate

    enable_operator_gate(monkeypatch, order_count="3")
    client, order_id, slug, _latch_cm, _events = await _arm_one_ambiguous_intent(tmp_path)
    _set_get_evidence(client, order_id, slug, state="ORDER_STATE_CANCELED", cum=0, positions={})
    return client, _latch_cm


@pytest.mark.asyncio
async def test_a_permit_restore_raise_keeps_the_ambiguous_refusal_and_logs_the_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    capfd: pytest.CaptureFixture[str],
) -> None:
    from breezy.adapters.polymarket_us import safety
    from breezy.adapters.polymarket_us.exec import client as client_module
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _run_exactly_one_pass

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, _latch_cm = await _armed_zero_fill_rig(tmp_path, monkeypatch)

        def _raise(**_kwargs: Any) -> bool:
            raise safety.LiveTradingPermissionError("simulated restore failure")

        monkeypatch.setattr(client_module, "restore_live_trading_budget", _raise)
        await _run_exactly_one_pass(client)

        assert _AMBIGUOUS_REASON in client.trading_refusals
        assert client.resolver_error_count == 1
        captured = capfd.readouterr()
        assert "LiveTradingPermissionError" in captured.out + captured.err
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_ledger_true_up_raise_keeps_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _run_exactly_one_pass

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, _latch_cm = await _armed_zero_fill_rig(tmp_path, monkeypatch)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated true-up failure")

        monkeypatch.setattr(type(client._ledger), "true_up_booking", _raise)
        await _run_exactly_one_pass(client)

        assert _AMBIGUOUS_REASON in client.trading_refusals
        assert client.resolver_error_count == 1
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_corrupt_latch_read_after_retire_keeps_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from breezy.runtime.submit_intent import SubmitIntentCorrupt
    from tests.unit.test_current_rung_hold_ambiguous_resolver import _run_exactly_one_pass

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        client, _latch_cm = await _armed_zero_fill_rig(tmp_path, monkeypatch)
        real_retire = client._retire
        real_current_open = client._latch.current_open
        retired = {"done": False}

        def _retire_then_poison(*args: Any, **kwargs: Any) -> None:
            real_retire(*args, **kwargs)
            retired["done"] = True

        def _current_open() -> Any:
            if retired["done"]:
                raise SubmitIntentCorrupt()
            return real_current_open()

        monkeypatch.setattr(client, "_retire", _retire_then_poison)
        monkeypatch.setattr(client._latch, "current_open", _current_open)
        await _run_exactly_one_pass(client)

        assert retired["done"] is True
        assert _AMBIGUOUS_REASON in client.trading_refusals
        assert client.resolver_error_count == 1
        await client._disconnect()
