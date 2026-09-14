# Create-order execution drift -- 2026-09-13 MIA (closes R-6)

**Capture**: node log `breezy-trade-20260913T165011Z.log:533`, 2026-09-13T17:03:46.808Z,
live MIA BUY 1 @0.70 IOC, resolver store key
`exec/polymarket_us/resolver/428709da14e14a8ba2602332753d8534`.

## Sanitised key tree (names only, no values)

```
{'executions'[2]: {
  'aggressor', 'commissionNotionalCollected': {'currency','value'},
  'commissionSpreadPx': {'currency','value'},   # NEW
  'id', 'lastPx': {'currency','value'}, 'lastShares',
  'legPrices'[0],                               # NEW
  'order': { ...all already covered by _ORDER_KEYS | _ORDER_DRIFT_ALLOWED_KEYS
             and _MARKET_METADATA_KEYS | _MARKET_METADATA_DRIFT_ALLOWED_KEYS },
  'orderRejectReason', 'text',
  'traceId',                                    # NEW
  'tradeId', 'transactTime',
  'transactTradeDate',                          # NEW
  'type',
  'unsolicitedCancelReason'                     # NEW
}, 'id'}
```

## Refusal text (verbatim)

> fill report carries field(s) 'commissionSpreadPx', 'legPrices', 'traceId',
> 'transactTradeDate', 'unsolicitedCancelReason' that the SDK snapshot does
> not declare; the venue shape moved under a surface reconciliation reads
> money from, so it is refused rather than ignored

Outcome fell to `KIND_AMBIGUOUS` with `fill_parse_error` set; the resolver's
GET path filled the order 3s later as a residual (third real order, third
AMBIGUOUS on the create path).

## The five keys added (`_EXECUTION_DRIFT_ALLOWED_KEYS`)

`commissionSpreadPx`, `legPrices`, `traceId`, `transactTradeDate`,
`unsolicitedCancelReason` -- merged only at `parse_fill_report`'s `known=`
site, never into `_EXECUTION_KEYS` itself (keeps
`test_polymarket_us_exec_snapshot_drift.py`'s drift check meaningful).

## Cross-check against the OpenAPI snapshot

All five appear in
`docs_snapshots/api-reference_orders_create-order_2026-08-25.md:257-284`
(`Execution` schema): `legPrices` (array of `LegPrice`), `unsolicitedCancelReason`
(`UnsolicitedCxlReason`), `traceId` (string), `commissionSpreadPx` (`Amount`),
`transactTradeDate` (date-time string) -- verified 2026-09-14.

## UNVERIFIED (literal values)

* Live values for `commissionSpreadPx`, `traceId`, `transactTradeDate`,
  `unsolicitedCancelReason` were never captured (names-only sanitised tree by
  design -- SEC-H1). `legPrices` was observed empty (`[0]`) on this capture
  only; a non-empty `legPrices` on a multi-leg instrument is unobserved.
* No live value confirms the RED test's synthetic `fee_reconciled=False`
  reflects the real 09-13 order's own `_cumulative_fee_and_reconciliation`
  branch -- that fixture is coherent-synthetic, not a captured reconciliation
  outcome.

**Closes R-6.**
