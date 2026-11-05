# FU-3: attribution of the 09-13 and 09-14 UNEXPLAINED_CAPITAL_FLOW rows (2026-09-26)

The source is the `PRIVATE_portfolio_roi_2026-09-25` report, windows ending 09-13 and 09-14. This note gives only the two flow amounts already quoted in PROGRESS; it contains no account balances.

## Evidence
- **E1:** a read-only recompute of `reconcile_daily` over the exec ledger, the scored-trial store and the node-log `AccountState` snapshots.
- **E2:** one read-only venue `GET /v1/portfolio/activities`, via the official SDK, 1 request, returning 32 activities.

| Window ending | Unexplained | Cause | Status |
|---|---|---|---|
| 09-13 | +$40.00 | External inflows, with 0 fills and 0 scored trials in the window. Venue: REFERRAL_BONUS $25 (`CFDEAYSG000Q`, 09-13 16:06:23Z), TRANSFER $5 (`CF317GQG000Q`, 09-13 05:57:25Z), and ACCOUNT_DEPOSIT $10 (`CFDE78TG000Q`, created 09-13 16:06:14Z, updated 09-17). | **VERIFIED external flow.** No code defect. |
| 09-14 | +$0.99 | Settlement payout of a RESIDUAL fill. Order `CFJ485874TMM` (MIA 09-13, gte91lt92 YES, qty 1, 0.70 + 0.01 fee) was excluded as `fee_unverified`, so it has no ScoredTrial row. The venue recorded POSITION_RESOLUTION on 09-14 at 13:44:34Z, inside the window. The balance change of +0.29 equals the 1.00 payout minus the 0.71 cost. The report counts the 0.70 cost as deployed capital but never counts the payout. | **VERIFIED. A code gap (H1)**: `reconcile_daily`/`proceeds_by_day` iterate scored trials only, never the residual sidecar. See backlog row FU-3b. |

## Notes
- H2 (a payout misdated through `scored_at_ns`) is refuted: there are 0 scored trials in either window.
- H3 (the balance counting open positions as well as cash) is not needed: `free == total` at every boundary snapshot.
- Venue schema facts:
  - A POSITION_RESOLUTION carries no cash amount. Its `realized` after-value read $0.00 here, so settlement cash must be taken from the balance arithmetic or from the market result, not from this field.
  - The ACCOUNT_DEPOSIT `updateTime` can trail its `createTime` by days.
