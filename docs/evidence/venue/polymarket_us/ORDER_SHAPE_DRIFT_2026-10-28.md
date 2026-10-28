# Polymarket.us `GET /v1/order/{id}` shape drift (2026-10-28) — `estimatedAmount`, `estimatedCommission`, `principal`

Observed by a read-only probe at 2026-10-28 ~21:10Z (the venue change itself landed between 20:10Z and 20:19Z, see timeline) on six of our own order reads (five 2026-10-28 rests, one 2026-10-27 expired rest) via the shipped read client. HTTP 200. The `Order` object gained three keys the pinned SDK snapshot (`polymarket_us_0.1.2`, `types/orders.py` `Order`) does not declare:

| Key | Observed JSON type on these reads | Populated type |
|---|---|---|
| `estimatedAmount` | null | UNKNOWN |
| `estimatedCommission` | null | UNKNOWN |
| `principal` | null | UNKNOWN |

No other key was added or removed. The body under the top-level `order` key is 27 nested keys: the previous 24 wire keys plus these three. This note records key names and types only.

Polls at 20:10:22Z and 20:10:52Z were readable, so the venue change landed between 20:10Z and 20:19Z. First poll failure 20:19:24Z was one `PrivateReadRefused`. From 20:19:28Z the 30 s resting poll (`_apply_resting_poll`) raised `ExecutionReportMappingError` because `parse_order_status_report` / `_known_order` refused the three names. 285 failures. The node latched `resting_query_unreadable` at 20:20:22Z.

```
ExecutionReportMappingError: order status report carries field(s) 'estimatedAmount', 'estimatedCommission', 'principal' that the SDK snapshot does not declare; the venue shape moved under a surface reconciliation reads money from, so it is refused rather than ignored
```

The guard behaved correctly: it refused undeclared names on a surface reconciliation reads money from, the same way the balances drift notes record `bonusHold` and the 2026-09-04 six (`docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-04.md`, `BALANCES_SHAPE_DRIFT_2026-09-19.md`).

## Disposition

DECLARED-BUT-UNREAD. The three names are in `_ORDER_DRIFT_ALLOWED_KEYS` and in the `WIRE_ORDER_KEYS` literal (`src/breezy/adapters/polymarket_us/exec/reports.py`), and they are absent from `_ORDER_KEYS`. `_ORDER_KEYS` stays the frozen SDK snapshot row, so `test_polymarket_us_exec_snapshot_drift.py` still checks set equality against that snapshot. None of the three is read into an `OrderStatusReport`. A further undeclared key is still refused.

Open question for the fee-drift watch: whether `estimatedCommission` should become a read field later. Not decided here. Its populated type is UNKNOWN, and this note records no values.

## Review conditions (python-reviewer APPROVE-WITH-FIXES, prediction-market-reviewer APPROVE-WITH-CONDITIONS, 2026-10-28)

Populated (non-null) values of the three keys are UNTESTED: no filled body has ever been observed for this family (0 fills). Every money/state reading stays on its named field (`quantity`, `cumQuantity`, `state`, `price`, `avgPx`, `commissionNotionalTotalCollected`; `commissionNotionalCollected` on the taker `Execution`); the residual exposure is a venue that moves realised commission or notional into the new fields and leaves the old ones stale (bounded at qty 1; `fee_reconciled` and the bps-drift latch catch the commission case). Posture ruled: declared-but-unread beats refuse-until-populated (a self-made deadlock for a 0-fill maker) and beats read-now (binds money to an unseen type).

**First-fill checklist (record value-free: types, nullness, sign; numeric comparisons only):**
1. Type and nullness of `estimatedAmount`, `estimatedCommission`, `principal` on the first PARTIALLY_FILLED/FILLED body (and on the taker `Execution.order` if that path fires).
2. `commissionNotionalTotalCollected` non-null and consistent with `cumQuantity × avgPx` economics — never a stale `"0"` while `estimatedCommission` is populated; compare sign/magnitude of `estimatedCommission` to it and to `0.0695·qty·px·(1−px)`.
3. `avgPx`/`cumQuantity` populated and consistent with `principal ≈ cumQuantity × avgPx` (NO-leg price translation applied); `price` is still the limit price, not a notional.
4. `commissionsBasisPoints` / `makerCommissionsBasisPoints` still `"0"` (bps-drift latch unlatched).
5. `fee_reconciled`, `venue_fee_raw`, `cumulative_fee` on the `DurableFillRecord` vs the venue's post-fill balance/commission figure.
6. `unknown_keys` empty (no further additive drift).

Fee-drift watch: `estimatedCommission` is NOT read; decide promotion to a watched field only after item 2 is recorded once.
