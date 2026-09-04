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

## Addendum 17:36–17:45 UTC — sub-cent precision

Second launch (17:36:17 UTC) after widening the declared set: `_connect` refused
`Field 'account balances response balances[0].currentBalance' carries more precision than the
instrument allows (precision 2); refusing to round a venue value` — and, with the new
`shutdown_system` request, the node exited on its own (exit non-zero via the exec-fault latch).

Value-free scale probe (one signed GET, digit counts only, `scratchpad/scale_probe/scale.py`):
`rows=1`; every money field is a JSON **number**, not a string; `currentBalance`, `buyingPower`,
`balanceReservation`, `bonusReservation`, `displayedBonus`, `displayedCash`, `availableToWithdraw`
carry **4 decimal places** (all positive); `depositReservation`, `displayedAvailableSoon` are positive
integers; `assetNotional`, `assetAvailable`, `pendingCredit`, `openOrders`, `unsettledFunds`,
`marginRequirement` are zero integers. A positive `bonusReservation`/`displayedBonus` alongside
4-dp balances is consistent with venue-side bonus accrual in sub-cent units; fees cannot produce it
(banker's-rounded to cents). Disposition (peer-reviewed): quantize `currentBalance`→total and
`buyingPower`→free to cents ROUND_DOWN for the Nautilus `AccountState` only, log a count once;
price precision guards stay strict; Breezy's sizing never reads these fields.
