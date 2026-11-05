# Open-order TIME_IN_FORCE_DAY drift (2026-10-29)

Value-free note for EXEC-FOREIGN-POS S2. No ids, prices, or quantities.

## What the pinned sources say

The venue open-orders doc snapshot
`docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_get-open-orders_2026-10-13.md`
lists `- TIME_IN_FORCE_DAY` at line 181. Line 187 continues the description: that member expires
at the end of the trading day.

The pinned SDK row
`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py`
declares `TimeInForce` at lines 15-20 as GOOD_TILL_CANCEL, GOOD_TILL_DATE, IMMEDIATE_OR_CANCEL,
and FILL_OR_KILL. DAY is not in that literal.

`tests/unit/test_polymarket_us_exec_snapshot_drift.py`
`test_the_time_in_force_table_covers_exactly_the_snapshot_members` (lines 167-168) pins
`_TIME_IN_FORCE` to that SDK row, so the native map still omits DAY.

## 10-28 activities page 0

Of 98 trade-side Order objects, 21 carry DAY:

- 9 on non-weather markets, marked MANUAL, across 3 namespaces;
- 12 on weather markets, each the passive side of a Breezy IOC.

All 98 self-identify.

## Disposition (S2)

`parse_open_orders` enumerates DAY only on a row that both names its own market and sits outside
the weather namespace. The value is not mapped to a native time-in-force. `parse_order_status_report`
still refuses DAY, because `_TIME_IN_FORCE` is unchanged. A DAY row on a weather market, an unusable
slug, or a row that does not name itself still refuses the whole enumeration.

Inferred from activities-embedded orders and the venue doc. Live `GET /v1/orders/open` capture is
pending the pre-boot probe.
