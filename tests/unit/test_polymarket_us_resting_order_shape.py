"""S4 WP1 (ARM maker-sharp B3): the pure resting-order shape, body and echo.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 2 WP1 and section 9; ``S4_..._plan_r3.md`` WP1; ARM plan r2 delta D2.

Everything here is pure: no client, no sender, no network. A GTD BUY of the
NO leg on a daily-HIGH market is the only resting shape; the IOC and exit
shapes stay byte-identical (the source-hash pin in
``test_ambig_no_id_firewall_delta.py`` already freezes ``build_order_body``,
``build_exit_order_body`` and ``classify_create_order_outcome``).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderStatus, TimeInForce
from nautilus_trader.model.identifiers import AccountId, StrategyId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.exec import endpoints, submit_chain
from breezy.adapters.polymarket_us.exec.reports import parse_order_status_report
from breezy.adapters.polymarket_us.parsing import parse_binary_option_pair

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT: Final[int] = 1_787_617_213_000_000_000
NS_PER_S: Final[int] = 1_000_000_000
# 2026-08-25T00:20:13Z.
NOW_NS: Final[int] = TS_INIT
DAY_END_NS: Final[int] = ((NOW_NS // (86_400 * NS_PER_S)) + 1) * 86_400 * NS_PER_S
EXPIRE_NS: Final[int] = NOW_NS + 3_600 * NS_PER_S + 123_456_789
PERMIT_NS: Final[int] = NOW_NS + 10 * 3_600 * NS_PER_S
TRADER_ID: Final[TraderId] = TraderId("BREEZY-R7-001")
STRATEGY_ID: Final[StrategyId] = StrategyId("WEATHER-001")
ACCOUNT_ID: Final[AccountId] = AccountId("POLYMARKET_US-001")
VENUE_ORDER_ID: Final[str] = "ABCDEF123456"
CAP: Final[Decimal] = submit_chain.RESTING_PRICE_CAP

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


@pytest.fixture
def legs() -> tuple[BinaryOption, BinaryOption]:
    payload = json.loads((RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"))
    yes, no = parse_binary_option_pair(payload, ts_init=TS_INIT)
    assert no is not None
    return yes, no


def _with_slug(instrument: BinaryOption, slug: str) -> BinaryOption:
    """Same leg, different ``raw_symbol`` (the id keeps the fixture's slug)."""
    kwargs: dict[str, Any] = {f: getattr(instrument, f) for f in _COPY_FIELDS}
    kwargs["instrument_id"] = instrument.id
    kwargs["currency"] = instrument.quote_currency
    kwargs["info"] = dict(instrument.info)
    kwargs["raw_symbol"] = type(instrument.raw_symbol)(slug)
    return BinaryOption(**kwargs)


def _order(
    instrument: BinaryOption,
    *,
    price: str = "0.40",
    side: OrderSide = OrderSide.BUY,
    quantity: int = 1,
    tif: TimeInForce = TimeInForce.GTD,
    expire_ns: int | None = EXPIRE_NS,
    post_only: bool = False,
) -> Any:
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    expire = None
    if tif is TimeInForce.GTD and expire_ns is not None:
        expire = pd.Timestamp(expire_ns, unit="ns", tz="UTC")
    return factory.limit(
        instrument_id=instrument.id,
        order_side=side,
        quantity=Quantity(quantity, instrument.size_precision),
        price=Price.from_str(price),
        time_in_force=tif,
        expire_time=expire,
        post_only=post_only,
    )


def _reason(order: Any, instrument: Any, **overrides: Any) -> str | None:
    kwargs: dict[str, Any] = {
        "permit_expires_at_ns": PERMIT_NS,
        "now_ns": NOW_NS,
        "gtd_expiry_verified": True,
    }
    kwargs.update(overrides)
    reason: str | None = submit_chain.unmappable_resting_order_reason(order, instrument, **kwargs)
    return reason


# --------------------------------------------------------------------------
# format_good_till_time
# --------------------------------------------------------------------------


def test_good_till_time_is_rfc3339_utc_whole_seconds_floored() -> None:
    # 2026-08-25T01:20:13Z plus 123456789 ns
    assert submit_chain.format_good_till_time(EXPIRE_NS) == "2026-08-25T01:20:13Z"


def test_good_till_time_never_later_than_expire_time() -> None:
    for extra in (0, 1, 999_999_999):
        expire = NOW_NS + 7_200 * NS_PER_S + extra
        text = submit_chain.format_good_till_time(expire)
        floored = pd.Timestamp(text).value
        assert floored <= expire
        assert expire - floored < NS_PER_S


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1787620000000000000", None])
def test_good_till_time_refuses_non_positive_or_non_int(bad: object) -> None:
    with pytest.raises(ValueError):
        submit_chain.format_good_till_time(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# daily-HIGH slug admission (own ASCII fullmatch, independent of symbology)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "tc-temp-nychigh-2026-08-25-lt79f",
        "tc-temp-mdwhigh-2026-10-22-gte70lt72f",
        "tc-temp-sfohigh-2026-10-22-gte70f",
    ],
)
def test_daily_high_slug_is_admitted(slug: str) -> None:
    assert submit_chain.is_daily_high_slug(slug) is True


@pytest.mark.parametrize(
    "slug",
    [
        "tc-temp-mdwlow-2026-10-22-lt50f",  # LOW measure
        "tc-temp-nychigh-2026-08-25-lt79f\n",  # trailing newline ($ would accept it)
        "\ntc-temp-nychigh-2026-08-25-lt79f",
        "tc-temp-nychigh-2026-08-25-lt79f ",
        "tc-temp-nychigh-2026-08-25-lt79",  # no unit
        "tc-temp-nychigh-2026-13-25-lt79f",  # impossible month
        "tc-temp-nychigh-2026-02-30-lt79f",  # impossible day
        "tc-temp-nychigh-2026-08-25-gte70lt72gt73f",  # three bound tokens
        "tc-temp-nychigh-２０２６-08-25-lt79f",  # fullwidth digits
        "tc-temp-phlhigh-2026-08-25-lt79f-x",
        "tc-temp-nychigh-2026-08-25-lt79f^no",  # composite instrument symbol
        "nba-lal-bos-2026-08-25",
        "",
        "TC-TEMP-NYCHIGH-2026-08-25-LT79F",
    ],
)
def test_non_daily_high_slug_is_refused(slug: str) -> None:
    assert submit_chain.is_daily_high_slug(slug) is False


@pytest.mark.parametrize("bad", [None, 7, b"tc-temp-nychigh-2026-08-25-lt79f", ["x"]])
def test_slug_admission_refuses_non_strings(bad: object) -> None:
    assert submit_chain.is_daily_high_slug(bad) is False


# --------------------------------------------------------------------------
# unmappable_resting_order_reason: the third shape
# --------------------------------------------------------------------------


def test_ioc_shape_still_refuses_gtc_byte_identically(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    """[CHAR] the IOC shape refuses a GTD order exactly as before."""
    _yes, no = legs
    reason = submit_chain.unmappable_order_reason(_order(no), no)
    assert reason == "only an IOC order is mappable; refusing"


def test_resting_shape_admits_gtd_buy_no_qty1_at_the_cap(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert _reason(_order(no, price=format(CAP, ".2f")), no) is None


def test_resting_price_cap_is_the_sharp_v1_b_cap() -> None:
    """P16: re-valued 0.80 -> 0.89 by ``RULING_MAKER_sharp_v1_live_small_2026-10-21``.

    The equality to the family's ``B_CAP`` (``MakerRuleParams.b_cap``, the ported
    Stage 0 rule) lands with that port; until then this literal is the assertion.
    """
    assert Decimal("0.89") == CAP


def test_resting_shape_admits_089_and_refuses_090(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert _reason(_order(no, price="0.89"), no) is None
    assert _reason(_order(no, price="0.90"), no) is not None


def test_resting_shape_admits_gtd_buy_no_qty1_at_a_low_price(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert _reason(_order(no, price="0.01"), no) is None


def test_resting_shape_refuses_gtc(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    reason = _reason(_order(no, tif=TimeInForce.GTC, expire_ns=None), no)
    assert reason is not None and "GTD" in reason


def test_resting_shape_refuses_ioc(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    assert _reason(_order(no, tif=TimeInForce.IOC, expire_ns=None), no) is not None


def test_resting_shape_refuses_expire_after_permit_expiry(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    permit = NOW_NS + 1_800 * NS_PER_S  # inside the UTC day, before EXPIRE_NS
    assert _reason(_order(no, expire_ns=EXPIRE_NS), no, permit_expires_at_ns=permit) is not None


def test_resting_shape_admits_expire_exactly_at_the_permit_bound(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    permit = NOW_NS + 1_800 * NS_PER_S  # inside the UTC day
    assert _reason(_order(no, expire_ns=permit), no, permit_expires_at_ns=permit) is None
    assert _reason(_order(no, expire_ns=permit + 1), no, permit_expires_at_ns=permit) is not None


def test_resting_shape_refuses_expire_after_utc_day_end(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    permit = DAY_END_NS + 5 * 3_600 * NS_PER_S
    assert _reason(_order(no, expire_ns=DAY_END_NS), no, permit_expires_at_ns=permit) is None
    over = _order(no, expire_ns=DAY_END_NS + 1)
    assert _reason(over, no, permit_expires_at_ns=permit) is not None


@pytest.mark.parametrize("delta_ns", [0, -1, -NS_PER_S])
def test_resting_shape_refuses_expire_not_after_now(
    legs: tuple[BinaryOption, BinaryOption], delta_ns: int
) -> None:
    _yes, no = legs
    assert _reason(_order(no, expire_ns=NOW_NS + delta_ns), no) is not None


def test_resting_shape_refuses_while_gtd_unverified(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert _reason(_order(no), no, gtd_expiry_verified=False) is not None


def test_gtd_expiry_verified_constant_is_false_until_the_positive_control_flips_it() -> None:
    assert submit_chain.GTD_EXPIRY_VERIFIED is False


def test_resting_shape_refuses_price_above_cap(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    above = format(CAP + Decimal("0.01"), ".2f")
    assert _reason(_order(no, price=above), no) is not None


def test_resting_shape_refuses_the_yes_leg(legs: tuple[BinaryOption, BinaryOption]) -> None:
    yes, _no = legs
    assert _reason(_order(yes), yes) is not None


def test_resting_shape_refuses_sell(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    assert _reason(_order(no, side=OrderSide.SELL), no) is not None


def test_resting_shape_refuses_post_only(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    assert _reason(_order(no, post_only=True), no) is not None


def test_resting_shape_refuses_quantity_other_than_one(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    assert _reason(_order(no, quantity=2), no) is not None


def test_resting_shape_refuses_a_non_instrument(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    assert _reason(_order(no), None) is not None
    assert _reason(_order(no), object()) is not None


@pytest.mark.parametrize(
    "slug",
    [
        "tc-temp-mdwlow-2026-08-25-lt50f",
        "tc-temp-nychigh-2026-08-25-lt79f\n",
        "nba-lal-bos-2026-08-25",
    ],
)
def test_resting_shape_refuses_non_daily_weather_slug(
    legs: tuple[BinaryOption, BinaryOption], slug: str
) -> None:
    _yes, no = legs
    odd = _with_slug(no, slug)
    reason = _reason(_order(odd), odd)
    assert reason is not None and "daily" in reason


# --------------------------------------------------------------------------
# build_resting_order_body and encode_order_body (P13)
# --------------------------------------------------------------------------


def test_resting_body_key_set_is_the_nine_key_async_set(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    body = submit_chain.build_resting_order_body(_order(no), no)
    assert set(body) == submit_chain.RESTING_ORDER_BODY_KEYS
    assert len(submit_chain.RESTING_ORDER_BODY_KEYS) == 9
    assert submit_chain.RESTING_ORDER_BODY_KEYS == {
        "marketSlug",
        "type",
        "price",
        "quantity",
        "tif",
        "outcomeSide",
        "action",
        "manualOrderIndicator",
        "goodTillTime",
    }


def test_resting_body_omits_synchronous_execution_and_max_block_time(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    body = submit_chain.build_resting_order_body(_order(no), no)
    assert "synchronousExecution" not in body
    assert "maxBlockTime" not in body
    assert submit_chain.RESTING_ORDER_BODY_KEYS == (
        submit_chain.ORDER_BODY_KEYS - {"synchronousExecution", "maxBlockTime"}
    ) | {"goodTillTime"}


def test_resting_body_values_for_a_no_leg_gtd_buy(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    body = submit_chain.build_resting_order_body(_order(no, price="0.40"), no)
    assert body["marketSlug"] == str(no.raw_symbol)
    assert body["tif"] == "TIME_IN_FORCE_GOOD_TILL_DATE"
    assert body["goodTillTime"] == submit_chain.format_good_till_time(EXPIRE_NS)
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert body["action"] == "ORDER_ACTION_BUY"
    assert body["type"] == "ORDER_TYPE_LIMIT"
    assert body["quantity"] == 1
    # the venue prices the YES side: the NO leg at 0.40 is 0.60 on the wire
    assert body["price"] == {"value": "0.60", "currency": "USD"}


def test_resting_body_builder_refuses_what_the_shape_refuses(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    yes, no = legs
    with pytest.raises(ValueError):
        submit_chain.build_resting_order_body(_order(yes), yes)
    with pytest.raises(ValueError):
        submit_chain.build_resting_order_body(_order(no, tif=TimeInForce.GTC, expire_ns=None), no)
    odd = _with_slug(no, "tc-temp-mdwlow-2026-08-25-lt50f")
    with pytest.raises(ValueError):
        submit_chain.build_resting_order_body(_order(odd), odd)


def test_encode_accepts_the_resting_nine_key_body(
    legs: tuple[BinaryOption, BinaryOption],
) -> None:
    _yes, no = legs
    body = submit_chain.build_resting_order_body(_order(no), no)
    encoded = submit_chain.encode_order_body(body)
    assert json.loads(encoded) == body


def test_ioc_body_key_set_unchanged(legs: tuple[BinaryOption, BinaryOption]) -> None:
    """[CHAR] the IOC key set is still exactly the ten keys."""
    assert submit_chain.ORDER_BODY_KEYS == {
        "marketSlug",
        "type",
        "price",
        "quantity",
        "tif",
        "outcomeSide",
        "action",
        "manualOrderIndicator",
        "synchronousExecution",
        "maxBlockTime",
    }


def test_encode_refuses_a_mixed_key_set(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    body = dict(submit_chain.build_resting_order_body(_order(no), no))
    mixed_ioc_plus_gtt = {**body, "synchronousExecution": True, "maxBlockTime": "5"}
    with pytest.raises(ValueError):
        submit_chain.encode_order_body(mixed_ioc_plus_gtt)
    only_one_sync = {**body, "synchronousExecution": True}
    with pytest.raises(ValueError):
        submit_chain.encode_order_body(only_one_sync)
    short = {k: v for k, v in body.items() if k != "goodTillTime"}
    with pytest.raises(ValueError):
        submit_chain.encode_order_body(short)
    with pytest.raises(ValueError):
        submit_chain.encode_order_body({**body, "participateDontInitiate": True})


def test_encode_still_accepts_the_ioc_body(legs: tuple[BinaryOption, BinaryOption]) -> None:
    _yes, no = legs
    ioc = _order(no, tif=TimeInForce.IOC, expire_ns=None)
    body = submit_chain.build_order_body(ioc, no)
    assert json.loads(submit_chain.encode_order_body(body)) == body


# --------------------------------------------------------------------------
# resting_echo_matches
# --------------------------------------------------------------------------


def _venue_order(body: dict[str, Any], *, state: str = "ORDER_STATE_NEW") -> dict[str, Any]:
    """What ``GET /v1/order/{id}`` returns for the rest we posted."""
    return {
        "id": VENUE_ORDER_ID,
        "marketSlug": body["marketSlug"],
        "side": "ORDER_SIDE_SELL",
        "intent": "ORDER_INTENT_BUY_SHORT",
        "type": body["type"],
        "tif": body["tif"],
        "state": state,
        "price": body["price"],
        "quantity": body["quantity"],
        "cumQuantity": 0,
        "leavesQuantity": body["quantity"],
        "createTime": "2026-08-25T00:00:14.120237895Z",
        "goodTillTime": body["goodTillTime"],
    }


def _report_and_order(
    instrument: BinaryOption, body: dict[str, Any], **order_overrides: Any
) -> tuple[Any, dict[str, Any]]:
    order = {**_venue_order(body), **order_overrides}
    report = parse_order_status_report(
        order,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=UUID4(),
        ts_init=TS_INIT,
    )
    return report, order


@pytest.fixture
def posted(legs: tuple[BinaryOption, BinaryOption]) -> tuple[BinaryOption, dict[str, Any]]:
    _yes, no = legs
    return no, dict(submit_chain.build_resting_order_body(_order(no, price="0.40"), no))


def test_resting_echo_matches_the_order_we_posted(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body)
    assert report.order_status is OrderStatus.ACCEPTED
    assert submit_chain.resting_echo_matches(report, body, order) is True


def test_resting_echo_matches_price_mismatch_is_false(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body, price={"value": "0.61", "currency": "USD"})
    assert submit_chain.resting_echo_matches(report, body, order) is False


def test_resting_echo_matches_quantity_mismatch_is_false(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body, quantity=2, leavesQuantity=2)
    assert submit_chain.resting_echo_matches(report, body, order) is False


def test_resting_echo_matches_tif_gtd_mismatch_is_false(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body, tif="TIME_IN_FORCE_GOOD_TILL_CANCEL")
    assert submit_chain.resting_echo_matches(report, body, order) is False


def test_resting_echo_matches_slug_mismatch_is_false(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body)
    other = {**order, "marketSlug": "tc-temp-nychigh-2026-08-25-lt80f"}
    assert submit_chain.resting_echo_matches(report, body, other) is False
    body_other = {**body, "marketSlug": "tc-temp-nychigh-2026-08-25-lt80f"}
    assert submit_chain.resting_echo_matches(report, body_other, order) is False


def test_resting_echo_matches_side_mismatch_is_false(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body)
    assert (
        submit_chain.resting_echo_matches(report, {**body, "action": "ORDER_ACTION_SELL"}, order)
        is False
    )


def test_resting_echo_no_leg_compares_via_the_leg_mapping(
    legs: tuple[BinaryOption, BinaryOption], posted: tuple[BinaryOption, dict[str, Any]]
) -> None:
    """The NO leg sells the YES side on the wire: a raw ``side`` comparison would
    call this a mismatch, and a YES-leg report must not match a NO-leg body."""
    yes, _no = legs
    no, body = posted
    report, order = _report_and_order(no, body)
    assert order["side"] == "ORDER_SIDE_SELL"  # the wire is NOT a raw BUY
    assert submit_chain.resting_echo_matches(report, body, order) is True
    yes_order = {
        **order,
        "side": "ORDER_SIDE_BUY",
        "intent": "ORDER_INTENT_BUY_LONG",
        "price": {"value": "0.40", "currency": "USD"},
    }
    yes_report = parse_order_status_report(
        yes_order,
        instrument=yes,
        account_id=ACCOUNT_ID,
        report_id=UUID4(),
        ts_init=TS_INIT,
    )
    assert submit_chain.resting_echo_matches(yes_report, body, yes_order) is False


def test_resting_echo_good_till_time_within_one_second_only(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    base = pd.Timestamp(body["goodTillTime"]).value

    def echo(delta_ns: int) -> bool:
        stamp = pd.Timestamp(base + delta_ns, unit="ns", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")
        report, order = _report_and_order(no, body, goodTillTime=f"{stamp}000Z")
        return submit_chain.resting_echo_matches(report, body, order)

    assert echo(0) is True
    assert echo(NS_PER_S) is True
    assert echo(-NS_PER_S) is True
    assert echo(NS_PER_S + 1_000) is False
    assert echo(-NS_PER_S - 1_000) is False


@pytest.mark.parametrize("bad", [None, "", "not-a-time", 12345, "2026-08-25T01:00:13+00:00"])
def test_resting_echo_unreadable_good_till_time_is_false(
    posted: tuple[BinaryOption, dict[str, Any]], bad: object
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body)
    assert submit_chain.resting_echo_matches(report, body, {**order, "goodTillTime": bad}) is False


def test_resting_echo_never_raises_on_a_malformed_echo(
    posted: tuple[BinaryOption, dict[str, Any]],
) -> None:
    no, body = posted
    report, order = _report_and_order(no, body)
    assert submit_chain.resting_echo_matches(report, {}, order) is False
    assert submit_chain.resting_echo_matches(report, body, {}) is False
    assert submit_chain.resting_echo_matches(None, body, order) is False


# --------------------------------------------------------------------------
# valid_venue_order_id is the ONE allowlist (endpoints), re-exported
# --------------------------------------------------------------------------


def test_valid_venue_order_id_is_the_endpoints_allowlist() -> None:
    assert submit_chain.valid_venue_order_id is endpoints.valid_venue_order_id


@pytest.mark.parametrize(
    ("order_id", "expected"),
    [
        (VENUE_ORDER_ID, True),
        ("ABCDEF123456\n", False),
        ("abcdef123456", False),
        ("ABCDEF12345", False),
        ("ＡＢＣＤＥＦ１２３４５６", False),
        ("", False),
        (None, False),
    ],
)
def test_valid_venue_order_id_allowlist(order_id: object, expected: bool) -> None:
    assert submit_chain.valid_venue_order_id(order_id) is expected
