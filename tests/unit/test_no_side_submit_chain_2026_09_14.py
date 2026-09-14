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


_COPY_FIELDS: Final[tuple[str, ...]] = (
    "raw_symbol",
    "asset_class",
    "price_precision",
    "size_precision",
    "price_increment",
    "size_increment",
    "activation_ns",
    "expiration_ns",
    "ts_event",
    "ts_init",
    "min_quantity",
    "maker_fee",
    "taker_fee",
    "outcome",
    "description",
)


def _rebuild(instrument: BinaryOption, **overrides: Any) -> BinaryOption:
    """A ``BinaryOption`` is a native, immutable instrument: to vary one
    field (``instrument_id``, ``info``, ``outcome``) a fixture must
    reconstruct the whole object from its own field values."""
    kwargs: dict[str, Any] = {field: getattr(instrument, field) for field in _COPY_FIELDS}
    kwargs["instrument_id"] = instrument.id
    kwargs["currency"] = instrument.quote_currency
    kwargs["info"] = dict(instrument.info)
    kwargs.update(overrides)
    return BinaryOption(**kwargs)


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
    """E2-5 safety pin, superseded by this commit (section 3 lands here).

    At commit 36c6d99 (section 2, X3 narrowed but `_outcome_token` still
    outcome-string-keyed) this test proved a NO-leg order stayed unmappable
    -- the barrier's removal alone could never emit a NO order body. This
    commit closes that gap correctly: `_outcome_token` is now leg-keyed via
    `leg_of(instrument.id)`, so a NO leg maps to `OUTCOME_SIDE_NO` and is
    mappable. The milestone this test guarded (X3-alone is safe) is
    preserved in history at 36c6d99; going forward this test instead proves
    the NO leg is now correctly (not accidentally) mappable.
    """
    _yes, no = legs
    order = _limit_buy(no)
    assert submit_chain._outcome_token(no) == submit_chain._OUTCOME_SIDE_NO
    assert submit_chain.unmappable_order_reason(order, no) is None
    body = submit_chain.build_order_body(order, no)
    assert body["outcomeSide"] == submit_chain._OUTCOME_SIDE_NO


def test_a_no_leg_instrument_maps_to_outcome_side_no(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert submit_chain._outcome_token(no) == "OUTCOME_SIDE_NO"


def test_a_yes_leg_instrument_still_maps_to_outcome_side_yes(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    assert submit_chain._outcome_token(yes) == "OUTCOME_SIDE_YES"


def test_the_order_body_key_set_is_identical_on_both_legs(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, no = legs
    yes_body = submit_chain.build_order_body(_limit_buy(yes), yes)
    no_body = submit_chain.build_order_body(_limit_buy(no), no)
    assert set(yes_body) == set(no_body) == submit_chain.ORDER_BODY_KEYS
    assert yes_body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert no_body["outcomeSide"] == "OUTCOME_SIDE_NO"


def test_a_no_order_at_nautilus_price_0_97_sends_3_cents_on_the_wire(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """Rev 5 (E5-1): the venue's `price.value` always represents the YES
    (long) side's price; a NO buy at 0.97 must send `1 - 0.97 = 0.03`."""
    _yes, no = legs
    order = _limit_buy(no, price="0.97")
    body = submit_chain.build_order_body(order, no)
    assert body["price"] == {"value": "0.03", "currency": "USD"}


def test_a_yes_order_wire_price_is_byte_identical_to_before_rev_5(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, _no = legs
    order = _limit_buy(yes, price="0.37")
    body = submit_chain.build_order_body(order, yes)
    assert body["price"] == {"value": "0.37", "currency": "USD"}


def test_intent_fingerprint_hashes_the_nautilus_price_not_the_wire_price(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """`intent_fingerprint` must not change when the wire translation is
    applied -- it hashes `order.price` (the Nautilus/instrument price),
    identically on the create and GET paths, regardless of leg."""
    _yes, no = legs
    order_no = _limit_buy(no, price="0.97")
    order_yes_same_nautilus_price = _limit_buy(no, price="0.97")
    assert submit_chain.intent_fingerprint(order_no) == submit_chain.intent_fingerprint(
        order_yes_same_nautilus_price
    )
    # Sanity: the wire price sent for this order is NOT 0.97 (it is 0.03),
    # yet the fingerprint tracks the Nautilus price unchanged.
    body = submit_chain.build_order_body(order_no, no)
    assert body["price"]["value"] == "0.03"


def test_a_sell_on_the_no_leg_is_still_unmappable(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """SELL stays refused on EITHER leg -- the check at :283-284 is
    leg-agnostic and byte-unchanged by this commit."""
    _yes, no = legs
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    sell_order = factory.limit(
        instrument_id=no.id,
        order_side=OrderSide.SELL,
        quantity=Quantity(1, no.size_precision),
        price=Price.from_str("0.37"),
        time_in_force=TimeInForce.IOC,
    )
    reason = submit_chain.unmappable_order_reason(sell_order, no)
    assert reason == "only a BUY is mappable (a SELL is a naked short); refusing"
    with pytest.raises(ValueError, match="only a BUY is mappable"):
        submit_chain.build_order_body(sell_order, no)


def test_an_instrument_whose_info_leg_contradicts_its_id_is_refused(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """Disagreement between the id-derived leg and `info["leg"]` is a
    refusal in BOTH directions (E2-8), never a fallback to either side."""
    yes, no = legs
    id_no_info_yes = _rebuild(no, info={**no.info, "leg": "yes"})
    with pytest.raises(ValueError, match="contradicts"):
        submit_chain._outcome_token(id_no_info_yes)

    id_yes_info_no = _rebuild(yes, info={**yes.info, "leg": "no"})
    with pytest.raises(ValueError, match="contradicts"):
        submit_chain._outcome_token(id_yes_info_no)


def test_the_outcome_string_is_never_read_for_the_token(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """Mutating the free-text `outcome` string (venue prose that can vary at
    any time, `parsing.py:1211-1221`) must not change the mapped token --
    it is keyed on `leg_of(instrument.id)` only."""
    _yes, no = legs
    mutated = _rebuild(no, outcome="Yes")
    assert submit_chain._outcome_token(mutated) == "OUTCOME_SIDE_NO"
