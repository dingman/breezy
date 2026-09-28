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

import pytest

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
            _trade_activity(
                aggressor_id="SYN-ORDER-1", passive_id="SYN-OTHER-9", qty_decimal="1",
            ),
            _trade_activity(
                aggressor_id="SYN-OTHER-9", passive_id="SYN-ORDER-1", qty_decimal="0.5",
            ),
            _trade_activity(aggressor_id="SYN-OTHER", passive_id="SYN-OTHER-2"),
        ]
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    refs = scan.refs
    assert len(refs) == 2
    assert refs[0].is_aggressor is True
    assert refs[0].qty == Decimal(1)
    assert refs[1].is_aggressor is False
    assert refs[1].qty == Decimal("0.5")
    assert scan.uninterpretable_rows == 0


def test_trade_rows_for_order_ignores_marketslug_match_without_id_match() -> None:
    """L-17: the venue's `marketSlug` filter is NOT a trade filter for a
    specific order id -- a same-slug trade naming a DIFFERENT order must
    never be counted. The passive leg is given a realistic foreign id (F3:
    every captured row carries both legs) so this stays an ordinary foreign
    trade, never an uninterpretable row under the both-legs-required rule."""
    page = {
        "activities": [
            _trade_activity(
                aggressor_id="SYN-OTHER-ORDER",
                passive_id="SYN-OTHER-PASSIVE",
                market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f",
            ),
        ]
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert scan.refs == ()
    assert scan.uninterpretable_rows == 0


def test_trade_rows_for_order_ignores_non_trade_activities() -> None:
    page = {
        "activities": [
            _activity("ACTIVITY_TYPE_ACCOUNT_DEPOSIT", _balance_change()),
            {"type": "ACTIVITY_TYPE_POSITION_RESOLUTION", "positionResolution": {}},
        ]
    }
    assert aa.trade_rows_for_order(page, "SYN-ORDER-1") == aa.TradeRowScan((), 0)


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
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(scan.refs) == 1
    assert scan.refs[0].qty == Decimal(0)
    assert scan.refs[0].create_ts_ns == 0
    assert scan.uninterpretable_rows == 0


def test_trade_rows_for_order_returns_empty_for_non_list_activities() -> None:
    assert aa.trade_rows_for_order({"activities": "not-a-list"}, "SYN-ORDER-1") == aa.TradeRowScan(
        refs=(), uninterpretable_rows=1,
    )
    assert aa.trade_rows_for_order({}, "SYN-ORDER-1") == aa.TradeRowScan(
        refs=(), uninterpretable_rows=1,
    )


# ---------------------------------------------------------------------------
# TRADE-ROW-DRIFT (plan r1/r2, 2026-09-27): an unreadable TRADE row must
# never silently count as "not ours" -- it must be counted in
# ``uninterpretable_rows`` instead, never simply dropped as `()`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build_activities", "case_name"),
    [
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": "SYN-OTHER-ORDER"},
                        # M3/M14: passive renamed -- the leg this order could
                        # be resting on is unreadable.
                        "passiveOrder": {"id": "SYN-OTHER-PASSIVE"},
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "passive_renamed",
        ),
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    # M9: `trade` itself renamed away.
                    "tradeInfo": {
                        "aggressor": {"id": "SYN-OTHER-ORDER"},
                        "passive": {"id": "SYN-OTHER-PASSIVE"},
                    },
                },
            ],
            "trade_renamed",
        ),
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        # M11: leg id is an int, not a string.
                        "aggressor": {"id": 12345},
                        "passive": {"id": "SYN-OTHER-PASSIVE"},
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "aggressor_id_is_int",
        ),
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        # M10: leg id is an empty string.
                        "aggressor": {"id": ""},
                        "passive": {"id": "SYN-OTHER-PASSIVE"},
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "aggressor_id_is_empty_string",
        ),
        (
            # M9: the list element itself is not an object.
            lambda: ["x"],
            "element_not_an_object",
        ),
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": "SYN-OTHER-ORDER"},
                        # M14: passive also drifted, both legs bad at once.
                        "passive": {"id": 999},
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "both_legs_bad",
        ),
        (
            lambda: [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": ""},
                        "passive": {"id": ""},
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "both_legs_empty_string",
        ),
    ],
)
def test_trade_rows_for_order_flags_one_uninterpretable_row_per_drift(
    build_activities: Any, case_name: str,
) -> None:
    """T1 (r1) + M14 (r2): each drift shape gives `uninterpretable_rows == 1`
    with EMPTY refs -- today (RED, pre-fix) every one of these silently
    returns `()`, i.e. "not ours", which is exactly the false-zero-fill risk
    this plan closes. M16: the malformed row must never leak into `refs`."""
    page = {"activities": build_activities()}
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert scan.refs == (), case_name
    assert scan.uninterpretable_rows == 1, case_name


@pytest.mark.parametrize(
    ("activity_type", "has_trade_key", "expected_uninterpretable"),
    [
        (None, False, 1),  # T2: type missing.
        ("ACTIVITY_TYPE_BRAND_NEW", True, 1),  # T2: unknown type WITH a trade key.
        ("ACTIVITY_TYPE_BRAND_NEW", False, 0),  # T2: unknown type, no trade key (routine, L-37).
    ],
)
def test_trade_rows_for_order_type_drift_classification(
    activity_type: str | None, has_trade_key: bool, expected_uninterpretable: int,
) -> None:
    """T2 (r1, T-3 simplified rule): an unknown/missing `type` is flagged
    ONLY when the row also carries a `trade` key, or the type itself is
    missing -- a brand-new activity type with no `trade` key is routine
    drift (L-37) and must never stall every read."""
    activity: dict[str, Any] = {}
    if activity_type is not None:
        activity["type"] = activity_type
    if has_trade_key:
        activity["trade"] = {"aggressor": {"id": "SYN-OTHER"}, "passive": {"id": "SYN-OTHER-2"}}
    page = {"activities": [activity]}
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert scan.refs == ()
    assert scan.uninterpretable_rows == expected_uninterpretable


def test_trade_rows_for_order_matched_row_with_malformed_other_leg_is_not_flagged() -> None:
    """T3 (r1; kills M4): a matching aggressor plus a malformed (renamed)
    passive leg still counts as ONE match, and must NOT also be counted as
    uninterpretable -- flagging a row we ALREADY have positive evidence for
    would needlessly block a genuine retirement."""
    page = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "aggressor": {"id": "SYN-ORDER-1"},
                    "passiveOrder": {"id": "irrelevant"},
                    "qtyDecimal": "1",
                    "createTime": "2026-09-23T17:22:07.900000000Z",
                },
            },
        ],
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(scan.refs) == 1
    assert scan.uninterpretable_rows == 0


def test_trade_rows_for_order_self_trade_matches_once_as_aggressor() -> None:
    """Domain review item 1 (r2 T-4): our id on BOTH legs (a self-trade)
    gives exactly one ref, `is_aggressor=True` -- pins the CURRENT semantics
    (`aggressor` is checked first), never two refs for one row."""
    page = {
        "activities": [
            _trade_activity(aggressor_id="SYN-ORDER-1", passive_id="SYN-ORDER-1"),
        ]
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(scan.refs) == 1
    assert scan.refs[0].is_aggressor is True
    assert scan.uninterpretable_rows == 0


# ---------------------------------------------------------------------------
# r2 T-2: the id cross-check against `aggressorExecution.order.id` /
# `passiveExecution.order.id` (R3's "the id keeps its name but its meaning
# drifted" residual risk).
# ---------------------------------------------------------------------------


def test_trade_rows_for_order_flags_id_drift_between_leg_and_execution_block() -> None:
    """r2 T-2 (kills M17): `aggressor.id` and `aggressorExecution.order.id`
    are both non-empty strings but DISAGREE -- uninterpretable, never
    silently ignored as an ordinary foreign trade."""
    page = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "aggressor": {"id": "SYN-OTHER-ORDER"},
                    "aggressorExecution": {"order": {"id": "SYN-DRIFTED-EXEC-ID"}},
                    "passive": {"id": "SYN-OTHER-PASSIVE"},
                    "qtyDecimal": "1",
                    "createTime": "2026-09-23T17:22:07.900000000Z",
                },
            },
        ],
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert scan.refs == ()
    assert scan.uninterpretable_rows == 1


def test_trade_rows_for_order_execution_block_absence_is_fine() -> None:
    """r2 T-2: "absence is fine" -- an ordinary foreign trade with NO
    execution block at all must never be flagged uninterpretable just
    because the (optional) cross-check has nothing to compare."""
    page = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "aggressor": {"id": "SYN-OTHER-ORDER"},
                    "passive": {"id": "SYN-OTHER-PASSIVE"},
                    "qtyDecimal": "1",
                    "createTime": "2026-09-23T17:22:07.900000000Z",
                },
            },
        ],
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert scan.refs == ()
    assert scan.uninterpretable_rows == 0


def test_trade_rows_for_order_matches_via_execution_block_id_alone() -> None:
    """r2 T-2: "ours" matches EITHER location -- our id at
    `aggressorExecution.order.id` alone (even though the leg's own `id`
    disagrees) is still a match, never a false negative."""
    page = {
        "activities": [
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "aggressor": {"id": "SOME-OTHER-ID"},
                    "aggressorExecution": {"order": {"id": "SYN-ORDER-1"}},
                    "passive": {"id": "SYN-OTHER-PASSIVE"},
                    "qtyDecimal": "1",
                    "createTime": "2026-09-23T17:22:07.900000000Z",
                },
            },
        ],
    }
    scan = aa.trade_rows_for_order(page, "SYN-ORDER-1")
    assert len(scan.refs) == 1
    assert scan.uninterpretable_rows == 0


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
