"""RED-first unit tests for ``breezy.adapters.polymarket_us.account_activity``
(FU-13b stage 1).

Fixtures are shaped like the captured payload
(``docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/
activities_p0.json``) but every id and amount below is SYNTHETIC -- none of
them are copied from a real capture.
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any

from breezy.adapters.polymarket_us import account_activity as aa
from breezy.persistence.external_capital_flows import ExternalCapitalFlow


def _amount(value: str, currency: str = "USD") -> dict[str, str]:
    return {"value": value, "currency": currency}


def _balance_change(
    *,
    transaction_id: str = "SYN-TX-0001",
    status: str = "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
    value: str = "25",
    currency: str = "USD",
    create_time: str = "2026-09-13T04:00:00.000000000Z",
    update_time: str | None = "2026-09-13T04:00:01.000000000Z",
    failure_reason: str = "",
    failure_code: str = "",
    failure_action: Any = None,
    include_top_level: bool = True,
) -> dict[str, Any]:
    nested_entry = {
        "transactionId": transaction_id,
        "status": status,
        "amount": _amount(value, currency),
        "createTime": create_time,
        "updateTime": update_time,
        "failureReason": failure_reason,
        "failureCode": failure_code,
        "failureAction": failure_action,
    }
    record: dict[str, Any] = {"transactions": [dict(nested_entry)]}
    if include_top_level:
        record.update(
            {
                "transactionId": transaction_id,
                "status": status,
                "amount": _amount(value, currency),
                "createTime": create_time,
                "updateTime": update_time,
                "failureReason": failure_reason,
                "failureCode": failure_code,
                "failureAction": failure_action,
            }
        )
    return record


def _activity(activity_type: str, balance_change: dict[str, Any] | None) -> dict[str, Any]:
    activity: dict[str, Any] = {"type": activity_type}
    if balance_change is not None:
        activity["accountBalanceChange"] = balance_change
    return activity


def test_referral_deposit_transfer_parse_with_signs() -> None:
    page = {
        "activities": [
            _activity(
                "ACTIVITY_TYPE_REFERRAL_BONUS",
                _balance_change(transaction_id="SYN-REF-1", value="20"),
            ),
            _activity(
                "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
                _balance_change(transaction_id="SYN-DEP-1", value="10"),
            ),
            _activity(
                "ACTIVITY_TYPE_TRANSFER",
                _balance_change(transaction_id="SYN-XFER-1", value="5"),
            ),
        ]
    }
    flows = aa.parse_external_flows(page)
    assert [f.kind for f in flows] == ["REFERRAL_BONUS", "ACCOUNT_DEPOSIT", "TRANSFER"]
    assert [f.signed_amount for f in flows] == [Decimal(20), Decimal(10), Decimal(5)]
    assert [f.sign_basis for f in flows] == ["type_table", "type_table", "literal"]
    assert all(f.parse_status == aa.PARSE_STATUS_OK for f in flows)
    assert all(f.failed is False for f in flows)


def test_withdrawal_is_negative_and_flagged_unobserved() -> None:
    page = {
        "activities": [
            _activity(
                "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
                _balance_change(transaction_id="SYN-WD-1", value="15"),
            )
        ]
    }
    (flow,) = aa.parse_external_flows(page)
    assert flow.kind == "ACCOUNT_WITHDRAWAL"
    assert flow.signed_amount == Decimal(-15)
    assert flow.sign_basis == "type_table_unobserved"


def test_nested_single_transaction_fallback() -> None:
    balance_change = _balance_change(
        transaction_id="SYN-NEST-1", value="30", include_top_level=False
    )
    page = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", balance_change)]}
    (flow,) = aa.parse_external_flows(page)
    assert flow.parse_status == aa.PARSE_STATUS_OK
    assert flow.kind == "ACCOUNT_DEPOSIT"
    assert flow.signed_amount == Decimal(30)
    assert flow.transaction_id_sha256 == hashlib.sha256(b"SYN-NEST-1").hexdigest()


def test_two_nested_without_toplevel_is_unparseable() -> None:
    balance_change = {
        "transactions": [
            {
                "transactionId": "SYN-A",
                "status": "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
                "amount": _amount("1"),
                "createTime": "2026-09-13T04:00:00.000000000Z",
            },
            {
                "transactionId": "SYN-B",
                "status": "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
                "amount": _amount("2"),
                "createTime": "2026-09-13T05:00:00.000000000Z",
            },
        ]
    }
    page = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", balance_change)]}
    (flow,) = aa.parse_external_flows(page)
    assert flow.parse_status == aa.PARSE_STATUS_UNPARSEABLE
    assert flow.signed_amount is None
    assert flow.create_ts_ns is None
    assert flow.kind == "ACCOUNT_DEPOSIT"


def test_unknown_status_and_non_usd_are_marked() -> None:
    balance_change = _balance_change(
        transaction_id="SYN-EUR-1",
        status="ACCOUNT_BALANCE_CHANGE_STATUS_FAILED",
        value="9",
        currency="EUR",
    )
    page = {"activities": [_activity("ACTIVITY_TYPE_TRANSFER", balance_change)]}
    (flow,) = aa.parse_external_flows(page)
    assert flow.parse_status == aa.PARSE_STATUS_OK
    assert flow.status not in aa.KNOWN_STATUSES
    assert flow.currency != "USD"
    assert flow.signed_amount == Decimal(9)


def test_unknown_activity_type_kept_as_unrecognised_without_amount() -> None:
    balance_change = _balance_change(transaction_id="SYN-NEWTYPE-1", value="77")
    page = {"activities": [_activity("ACTIVITY_TYPE_SOMETHING_NEW", balance_change)]}
    (flow,) = aa.parse_external_flows(page)
    assert flow.kind == aa.UNRECOGNISED_KIND
    assert flow.signed_amount is None
    assert flow.currency is None
    assert flow.status is None
    assert flow.create_ts_ns is not None
    assert flow.transaction_id_sha256 == hashlib.sha256(b"SYN-NEWTYPE-1").hexdigest()


def test_failure_fields_mark_flow_failed() -> None:
    top_level_failed = _balance_change(
        transaction_id="SYN-FAIL-TOP", value="4", failure_reason="REVERSED"
    )
    page_top = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", top_level_failed)]}
    (flow_top,) = aa.parse_external_flows(page_top)
    assert flow_top.failed is True

    nested_failed = _balance_change(transaction_id="SYN-FAIL-NEST", value="6")
    nested_failed["failureReason"] = ""
    nested_failed["transactions"][0]["failureReason"] = "REVERSED"
    page_nested = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", nested_failed)]}
    (flow_nested,) = aa.parse_external_flows(page_nested)
    assert flow_nested.failed is True


def test_trade_and_resolution_rows_ignored() -> None:
    page = {
        "activities": [
            {"type": "ACTIVITY_TYPE_TRADE", "trade": {"id": "SYN-TRADE-1"}},
            {"type": "ACTIVITY_TYPE_POSITION_RESOLUTION", "positionResolution": {}},
        ]
    }
    assert aa.parse_external_flows(page) == []


def test_raw_transaction_id_never_in_output() -> None:
    balance_change = _balance_change(transaction_id="SENTINEL-RAW-ID", value="8")
    page = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", balance_change)]}
    (flow,) = aa.parse_external_flows(page)
    assert isinstance(flow, ExternalCapitalFlow)
    assert "SENTINEL-RAW-ID" not in repr(flow)
    assert flow.transaction_id_sha256 == hashlib.sha256(b"SENTINEL-RAW-ID").hexdigest()


def test_unparseable_diagnostic_has_no_payload(caplog: Any) -> None:
    balance_change = {
        "transactions": [
            {
                "transactionId": "SENTINELID",
                "status": "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
                "amount": _amount("123.45"),
                "createTime": "2026-09-13T04:00:00.000000000Z",
            },
            {
                "transactionId": "SENTINELID2",
                "status": "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
                "amount": _amount("123.45"),
                "createTime": "2026-09-13T05:00:00.000000000Z",
            },
        ]
    }
    page = {"activities": [_activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", balance_change)]}
    with caplog.at_level(logging.WARNING):
        (flow,) = aa.parse_external_flows(page)
    assert flow.parse_status == aa.PARSE_STATUS_UNPARSEABLE
    log_text = caplog.text
    assert "123.45" not in log_text
    assert "SENTINELID" not in log_text
    assert "SENTINELID2" not in log_text


# ---------------------------------------------------------------------------
# EDGE-2 slice D (AC4(c)): the resolver's trade-activity join.
#
# Fixtures below are shaped like the captured trade-row shape (``docs/
# evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/
# activities_p0.json``: ``trade.aggressor.id`` / ``trade.passive.id`` /
# ``qtyDecimal`` / ``createTime``) but every id and amount is SYNTHETIC.
# ---------------------------------------------------------------------------


def _trade_activity(
    *,
    aggressor_id: str | None = None,
    passive_id: str | None = None,
    qty_decimal: str | None = "1",
    create_time: str | None = "2026-09-23T17:22:07.900000000Z",
    market_slug: str = "tc-temp-miahigh-2026-09-23-gte82lt83f",
) -> dict[str, Any]:
    trade: dict[str, Any] = {"marketSlug": market_slug}
    if aggressor_id is not None:
        trade["aggressor"] = {"id": aggressor_id}
    if passive_id is not None:
        trade["passive"] = {"id": passive_id}
    if qty_decimal is not None:
        trade["qtyDecimal"] = qty_decimal
    if create_time is not None:
        trade["createTime"] = create_time
    return {"type": "ACTIVITY_TYPE_TRADE", "trade": trade}


def test_trade_rows_for_order_joins_aggressor_and_passive_ids() -> None:
    page = {
        "activities": [
            _trade_activity(aggressor_id="SYN-ORDER-1", qty_decimal="1"),
            _trade_activity(passive_id="SYN-ORDER-1", qty_decimal="0.5"),
            _trade_activity(aggressor_id="SYN-OTHER", passive_id="SYN-OTHER-2"),
        ]
    }
    refs = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(refs) == 2
    assert refs[0].is_aggressor is True
    assert refs[0].qty == Decimal(1)
    assert refs[1].is_aggressor is False
    assert refs[1].qty == Decimal("0.5")


def test_trade_rows_for_order_ignores_marketslug_match_without_id_match() -> None:
    """L-17: the venue's `marketSlug` filter is NOT a trade filter for a
    specific order id -- a same-slug trade naming a DIFFERENT order must
    never be counted."""
    page = {
        "activities": [
            _trade_activity(
                aggressor_id="SYN-OTHER-ORDER",
                market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f",
            ),
        ]
    }
    assert aa.trade_rows_for_order(page, "SYN-ORDER-1") == ()


def test_trade_rows_for_order_ignores_non_trade_activities() -> None:
    page = {
        "activities": [
            _activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", _balance_change()),
            {"type": "ACTIVITY_TYPE_POSITION_RESOLUTION", "positionResolution": {}},
        ]
    }
    assert aa.trade_rows_for_order(page, "SYN-ORDER-1") == ()


def test_trade_rows_for_order_degrades_never_drops_a_malformed_match() -> None:
    """A genuine match (id equality) is NEVER dropped for a malformed
    ``qtyDecimal``/``createTime`` -- losing a real trade row silently is
    exactly the false-zero-fill risk AC4(c) exists to close."""
    page = {
        "activities": [
            _trade_activity(
                aggressor_id="SYN-ORDER-1", qty_decimal="not-a-number", create_time="garbage",
            ),
        ]
    }
    refs = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(refs) == 1
    assert refs[0].qty == Decimal(0)
    assert refs[0].create_ts_ns == 0


def test_trade_rows_for_order_returns_empty_for_non_list_activities() -> None:
    assert aa.trade_rows_for_order({"activities": "not-a-list"}, "SYN-ORDER-1") == ()
    assert aa.trade_rows_for_order({}, "SYN-ORDER-1") == ()


def test_page_min_create_ts_ns_handles_missing_and_malformed_times() -> None:
    page = {
        "activities": [
            _trade_activity(
                aggressor_id="SYN-1",
                create_time="2026-09-23T17:22:07.900000000Z",
            ),
            _trade_activity(aggressor_id="SYN-2", create_time="not-a-timestamp"),
            _activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", _balance_change(
                create_time="2026-09-20T00:00:00.000000000Z",
            )),
            {"type": "ACTIVITY_TYPE_WEIRD"},
        ]
    }
    result = aa.page_min_create_ts_ns(page)
    assert result is not None
    # 2026-09-20 predates 2026-09-23, so the balance-change row's timestamp
    # is the minimum; the malformed trade row and the untimestamped weird
    # row are both excluded rather than corrupting the minimum.
    expected = aa._parse_rfc3339_ns("2026-09-20T00:00:00.000000000Z")
    assert result == expected


def test_page_min_create_ts_ns_returns_none_with_no_parseable_timestamp() -> None:
    page = {"activities": [{"type": "ACTIVITY_TYPE_WEIRD"}]}
    assert aa.page_min_create_ts_ns(page) is None
    assert aa.page_min_create_ts_ns({"activities": "not-a-list"}) is None
