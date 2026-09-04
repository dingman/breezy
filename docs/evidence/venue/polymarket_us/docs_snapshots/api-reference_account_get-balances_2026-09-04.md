> Source: https://docs.polymarket.us/api-reference/account/get-account-balances.md,
> https://docs.polymarket.us/api-reference/oapi-schemas/account-schema.json,
> https://docs.polymarket.us/api-reference/sdks/python/account.md, https://docs.polymarket.us/changelog.md
> Fetched 2026-09-04 ~17:50 UTC via a read-only research agent (summary, not a verbatim page capture).

# Get Account Balances (`GET /v1/account/balances`) — documentation check after the 2026-09-04 shape drift

Documented `UserBalance` properties (all four surfaces agree; identical to the pinned SDK snapshot
`sdk_snapshot/polymarket_us_0.1.2/types/account.py` `UserBalance`): `assetAvailable`,
`assetNotional`, `balanceReservation`, `buyingPower`, `currency`, `currentBalance`, `lastUpdated`,
`marginRequirement`, `openOrders`, `pendingCredit`, `pendingWithdrawals`, `unsettledFunds`.

The two properties Breezy's reconciliation reads (`exec/reports.py`): 
- `currentBalance` (number, decimal): "Current fiat currency balance, not including security values"
- `buyingPower` (number, decimal): "Unencumbered capital available for trading, factoring in all security valuations and open orders"

Both descriptions are unchanged from the 2026-08-25 snapshot era.

## Not documented as of 2026-09-04T17:50Z

`availableToWithdraw`, `bonusReservation`, `depositReservation`, `displayedAvailableSoon`,
`displayedBonus`, `displayedCash` — observed live on every `balances[]` row since at least
2026-09-04 17:23 UTC (`BALANCES_SHAPE_DRIFT_2026-09-04.md`), absent from the endpoint page, the
OpenAPI account schema, the Python SDK page, and the changelog (v0.0.77 2026-08-10 … v0.0.82
2026-09-01, no balance-schema entry). Their meaning is unpublished; Breezy declares them as
known-but-UNREAD and maps none of them. Open risk the docs cannot close: whether the reservation
fields are already deducted from `buyingPower`; only a controlled observation (a non-zero
reservation alongside `buyingPower`) can settle it.
