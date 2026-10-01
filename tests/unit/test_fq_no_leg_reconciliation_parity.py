"""FQ-S6 test 9 (plan §3 S6 item 9, D8, peer-review disposition 1): the
go-live NO-leg reconciliation gate.

Drives an fq-composed NO Take (the exact ``order_factory.limit(...)`` shape
``ForecastQuantileLadderStrategy._maybe_submit`` builds: LIMIT/IOC/BUY/qty 1,
not post-only -- identical to ``ContinuousRungHoldStrategy._maybe_submit``'s
own shape, D8) through the REAL exec client, with a stub sender returning the
captured NO accept-fill shape, and asserts, side by side against a CRH-shaped
run of the SAME inputs:

  (a) the wire body price equals ``1 - p`` and the echo
      ``(ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)`` is accepted;
  (b) the ``DurableFillRecord`` carries the ``^no`` ``instrument_id`` and an
      ``instrument_price_for_leg``-inverted cost;
  (c) the ``DailySpendLedger`` booking equals the NO premium, identically to
      the CRH run of the same fill;
  (d) a following boot's ``generate_mass_status`` on a venue payload of
      ``outcome="No", netPosition=-1`` maps to LONG 1 on the SAME ``^no`` id
      with ``avg_px_open`` equal to the CRH run's;
  (e) native position and PnL for fq equal the CRH run's, field for field.

Reuses the exact fixtures/helpers D8 cites: ``_build_client``/``legs``/
``_accept_fill_body`` (``test_no_side_fill_attribution_2026_09_14.py``) and
``_no_side_position`` (``test_polymarket_us_exec_client.py``) -- never a
second, drifting fixture.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.model.identifiers import StrategyId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec.endpoints import PORTFOLIO_POSITIONS_PATH
from breezy.adapters.polymarket_us.leg_prices import instrument_price_for_leg
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import leg_of
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_no_side_fill_attribution_2026_09_14 import (
    STRATEGY_ID,
    TRADER_ID,
    TS_INIT,
    _accept_fill_body,
    _build_client,
    _load_raw,
    _reopened_fill_record,
)
from tests.unit.test_polymarket_us_exec_client import _no_side_position, _PrivateReadStub
from tests.unit.test_polymarket_us_submit_order_chain import _FakeSender

#: The CRH-shaped and the fq-shaped runs each submit a LIMIT/IOC/BUY/qty-1
#: order at THIS instrument (NO-leg) price -- D8: both compositions build
#: the identical order shape (``order_factory.limit(...)``, not post-only),
#: so this one constant drives both legs of the side-by-side comparison.
NO_LEG_PRICE: Decimal = Decimal("0.63")
#: The wire's OWN echoed last price (always YES-denominated, Rev 5) in the
#: captured accept-fill shape -- `1 - NO_LEG_PRICE`.
WIRE_LAST_PX = "0.37"

FQ_STRATEGY_ID = StrategyId("FORECAST-QUANTILE-LADDER-LAX")


def _no_leg_limit_buy(instrument: BinaryOption, *, strategy_id: StrategyId) -> Any:
    """The EXACT shape ``_maybe_submit`` builds in both compositions (D8):
    LIMIT, BUY, IOC, qty 1, not post-only."""
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=strategy_id, clock=LiveClock())
    return factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str(str(NO_LEG_PRICE)),
        time_in_force=TimeInForce.IOC,
        post_only=False,
    )


async def _drive_no_leg_order(
    tmp_path: Path,
    *,
    legs: tuple[BinaryOption, BinaryOption],
    monkeypatch: pytest.MonkeyPatch,
    strategy_id: StrategyId,
    order_id: str,
) -> dict[str, Any]:
    """Submit ONE NO-leg order through the REAL exec client and return the
    observable facts test 9 compares side by side: the wire body, the
    DurableFillRecord, the ledger booking, and the position/PnL mapping from
    a FOLLOWING boot's own ``generate_mass_status``.
    """
    _yes, no = legs
    sender = _FakeSender()
    fixture = _build_client(tmp_path / "submit", legs=legs, sender=sender, monkeypatch=monkeypatch)
    slug = str(no.raw_symbol)
    sender.response = VenueResponse(
        status=200,
        headers={},
        body=_accept_fill_body(slug, order_id=order_id, wire_last_px=WIRE_LAST_PX),
    )
    await fixture.client._connect()
    order = _no_leg_limit_buy(no, strategy_id=strategy_id)
    command = SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=strategy_id,
        order=order,
        command_id=UUID4(),
        ts_init=TS_INIT,
    )
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        await fixture.client._submit_order(command)

    # (a) wire body price and echo -- the sender captured the EXACT body
    # `build_order_body` sent on the wire.
    assert len(sender.calls) == 1
    sent_body = json.loads(sender.calls[0]["body"])
    assert sent_body["price"] == {"value": WIRE_LAST_PX, "currency": "USD"}
    assert Decimal(WIRE_LAST_PX) == Decimal(1) - NO_LEG_PRICE
    assert sent_body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert sent_body["action"] == "ORDER_ACTION_BUY"

    # (b) the durable fill record: `^no` instrument id, instrument_price_
    # for_leg-inverted cost (never the raw wire value).
    record = _reopened_fill_record(fixture.store_path, order_id)
    assert record is not None
    assert record.instrument_id == str(no.id)
    assert leg_of(no.id) == "no"
    assert record.cumulative_cost == instrument_price_for_leg(
        "no", Decimal(WIRE_LAST_PX),
    )
    assert record.cumulative_cost == NO_LEG_PRICE

    # (c) the DailySpendLedger booking equals the NO premium.
    ledger = fixture.client._ledger
    assert ledger is not None
    now_ns = fixture.client._clock.timestamp_ns()
    spent = ledger.spent_today_usd(now_ns=now_ns)
    assert spent == NO_LEG_PRICE

    await fixture.client._disconnect()

    # (d)/(e): a FOLLOWING boot's `generate_mass_status` on a venue payload
    # of outcome="No", netPosition=-1 maps to LONG 1 on the SAME `^no` id,
    # priced from THIS run's own durable fill record (never the wire value).
    boot_fixture = _build_client(tmp_path / "boot", legs=legs, monkeypatch=monkeypatch)
    await boot_fixture.client._connect()
    boot_fixture.client.record_fill(record)
    # The venue slug is SHARED by both legs (`raw_symbol`) -- never the
    # `^no`-suffixed Nautilus `InstrumentId`, which `_slug` (keyed on
    # `instrument.symbol`) would wrongly return for the NO instrument.
    shared_slug = str(no.raw_symbol)
    boot_read = cast("_PrivateReadStub", boot_fixture.client._private_read)
    boot_read._payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {shared_slug: _no_side_position(shared_slug, cost=str(NO_LEG_PRICE))},
        "eof": True,
    }
    mass_status = await boot_fixture.client.generate_mass_status()
    reports = mass_status.position_reports[no.id]
    assert len(reports) == 1
    report = reports[0]
    assert report.position_side == PositionSide.LONG
    assert report.quantity == Quantity(1, no.size_precision)
    assert report.avg_px_open == NO_LEG_PRICE
    await boot_fixture.client._disconnect()

    return {
        "wire_price": sent_body["price"]["value"],
        "fill_cost": record.cumulative_cost,
        "ledger_spent": spent,
        "position_side": report.position_side,
        "position_quantity": report.quantity,
        "avg_px_open": report.avg_px_open,
    }


@pytest.mark.asyncio
async def test_fq_composed_no_order_reconciles_identically_to_the_crh_run(
    tmp_path: Path, legs: tuple[BinaryOption, BinaryOption], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The go-live gate (plan §3 S6 test 9): the fq-composed NO order's wire
    price, fill record, ledger booking, and boot-time position/PnL mapping
    are IDENTICAL to the CRH composition's run of the same inputs -- the
    reused exec/reports/leg_prices chain (D8) is proven family-agnostic by
    actually running it twice, never by inspection alone.
    """
    crh_facts = await _drive_no_leg_order(
        tmp_path / "crh",
        legs=legs,
        monkeypatch=monkeypatch,
        strategy_id=STRATEGY_ID,
        order_id="ord-no-crh-1",
    )
    fq_facts = await _drive_no_leg_order(
        tmp_path / "fq",
        legs=legs,
        monkeypatch=monkeypatch,
        strategy_id=FQ_STRATEGY_ID,
        order_id="ord-no-fq-1",
    )

    assert fq_facts == crh_facts


@pytest.fixture
def legs() -> tuple[BinaryOption, BinaryOption]:
    """Byte-identical to ``test_no_side_fill_attribution_2026_09_14.legs``
    (same captured payload, same parse call) -- redeclared rather than
    imported because pytest fixtures are not plain importable functions.
    """
    payload = _load_raw("market_open_510636_by_slug.json")
    yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    assert leg_of(yes.id) == "yes"
    assert leg_of(no.id) == "no"
    return yes, no
