# Polymarket.us `GET /v1/account/balances` shape drift (2026-09-04)

Observed at the first live launch of `breezy-trade` (2026-09-04 17:23:25 UTC, trader `BREEZY-L001`):
the exec client's `_connect` reconciliation refused the balances payload —

```
ExecutionReportMappingError(account balances response balances[0] carries field(s)
'availableToWithdraw', 'bonusReservation', 'depositReservation', 'displayedAvailableSoon',
'displayedBonus', 'displayedCash' that the SDK snapshot does not declare; the venue shape
moved under a surface reconciliation reads money from, so it is refused rather than ignored)
```

Re-probed with `scripts/venue/polymarket_us_private_shape_probe.py --endpoint /v1/account/balances`
at 17:25:41 UTC: HTTP 200, envelope parsed, each `balances[]` row carries the 12 declared keys
(`assetAvailable, assetNotional, balanceReservation, buyingPower, currency, currentBalance,
lastUpdated, marginRequirement, openOrders, pendingCredit, pendingWithdrawals, unsettledFunds`)
plus **6 unrecognized keys of JSON type number** (value-free artefact
`PRIVATE_v1_account_balances_20260904T172541Z.probe.json`, git-ignored). The 2026-09-02 probe of
the same endpoint (`PRIVATE_v1_account_balances_20260902T185916Z.probe.json`) recorded 0
unrecognized keys, so the venue added these fields between 2026-09-02 18:59 UTC and 2026-09-04
17:23 UTC. The SDK snapshot pinned in the repo (`polymarket_us_0.1.2`, `types/account.py`
`UserBalance`) predates them; no docs snapshot describes them.

Consequences: the fail-closed refusal worked as designed (no reconciliation on an unverified
money surface); the node stayed `RUNNING` with `ExecEngine.check_connected() == False` for 60 s
until stopped by hand — the exec client's `_connect` has no fail-fast path (the data client's was
added in `6fcadae`). Disposition: widen the declared set with the six names as declared-but-unread
(none is read for money), and give the exec `_connect` the same fatal-fault exit.
