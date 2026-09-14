"""NO-side S5 submit-chain leg attribution (plan `NO_SIDE_S5_EXEC_2026-09-14.md`
sections 2 and 3). `_outcome_token`/`build_order_body`/`unmappable_order_reason`
key the order body's `outcomeSide` on `leg_of(instrument.id)`, never on the
free-text outcome string a venue could vary at any time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import StrategyId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair
from breezy.adapters.polymarket_us.symbology import leg_of

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT: Final[int] = 1_787_617_213_000_000_000
TRADER_ID: Final[TraderId] = TraderId("BREEZY-R7-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")


def _load_raw(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((RAW / name).read_text(encoding="utf-8"))
    return payload


@pytest.fixture
def legs() -> tuple[BinaryOption, BinaryOption]:
    payload = _load_raw("market_open_510636_by_slug.json")
    yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    assert leg_of(yes.id) == "yes"
    assert leg_of(no.id) == "no"
    return yes, no


def _limit_buy(instrument: BinaryOption, *, price: str = "0.37") -> Any:
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    return factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=TimeInForce.IOC,
    )


def test_x3_alone_without_leg_keyed_submit_chain_never_emits_no(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """E2-5 safety pin: with X3 narrowed (OUTCOME_SIDE_NO admitted) but
    `_outcome_token` NOT yet leg-keyed (this commit, before section 3 lands),
    a NO-leg order stays unmappable -- the barrier's removal alone can never
    emit a NO order body. `_outcome_token` today reads `instrument.outcome`
    casefold-equal to "yes"; the NO leg's outcome string never satisfies that,
    so it returns None and `build_order_body` refuses."""
    _yes, no = legs
    order = _limit_buy(no)
    assert submit_chain._outcome_token(no) is None
    reason = submit_chain.unmappable_order_reason(order, no)
    assert reason is not None
    assert "no YES outcome leg is derivable" in reason
    with pytest.raises(ValueError, match="no YES outcome leg is derivable"):
        submit_chain.build_order_body(order, no)
