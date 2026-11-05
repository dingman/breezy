# Polymarket.us `GET /v1/account/balances` shape drift (2026-09-19) — `bonusHold`

Both live-node launches on 2026-09-18 (`~/.local/share/breezy/logs/breezy-trade-20260918T165005Z.log`,
`~/.local/share/breezy/logs/breezy-trade-20260918T165120Z.log`) shut down within ~60 s of start with
the exec client's `_connect` reconciliation refusing the balances payload —

```
FATAL execution-client fault in POLYMARKET_US: _connect failed before the client reached a
connected state (ExecutionReportMappingError: account balances response balances[0] carries
field(s) 'bonusHold' that the SDK snapshot does not declare; the venue shape moved under a
surface reconciliation reads money from, so it is refused rather than ignored); no order can
ever be evaluated against a client that never connected
```

Consequences: no node on 2026-09-18 or 2026-09-19 (discovered 2026-09-19), no offer-tape
decisions for either day, no trading. The guard behaved correctly — it refused an undeclared
field on a surface reconciliation reads money from, exactly as it did for the six fields
captured on 2026-09-04 (`docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-04.md`).

Both 2026-09-18 launch logs were grepped for `"does not declare"`; every occurrence names
exactly one field, `'bonusHold'`. No other undeclared field appears in either log.

## Disposition

`bonusHold` is the seventh field observed on this endpoint beyond the pinned SDK snapshot
(`polymarket_us_0.1.2`, `types/account.py` `UserBalance`), following the same pattern as the
six fields from 2026-09-04 (`availableToWithdraw`, `bonusReservation`, `depositReservation`,
`displayedAvailableSoon`, `displayedBonus`, `displayedCash`). Widened into
`_USER_BALANCE_DRIFT_ALLOWED_KEYS` (`src/breezy/adapters/polymarket_us/exec/reports.py`) as
DECLARED-BUT-UNREAD: accepted so reconciliation does not refuse an otherwise-healthy connect
over a name it has never needed, but **not** merged into `_USER_BALANCE_KEYS` itself — that set
stays exactly what the SDK snapshot declares, so the drift check in
`test_polymarket_us_exec_snapshot_drift.py` stays meaningful. `bonusHold` is not read for money
by `_parse_account_balance`; it feeds no `total`, `free`, or `locked` figure.

The strict refusal remains strict: a field beyond these seven is still unknown and still
refused (`test_an_eighth_unknown_field_still_refuses_even_alongside_the_seven`,
`tests/unit/test_polymarket_us_exec_endpoints.py`).
