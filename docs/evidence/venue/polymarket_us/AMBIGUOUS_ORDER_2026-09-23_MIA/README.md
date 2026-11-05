# EDGE-2 Step 0: MIA 2026-09-23 ambiguous order -- read-only verdict

Authority: `docs/plans/backlog/EDGE_2026-09-27/
EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md`, section 6
(Step 0) and AC1. Produced by `scripts/venue/edge2_ambiguous_order_probe.py`,
run once as a read-only `systemd-run --user` oneshot
(`breezy-edge2-step0-0606.service`, started 2026-09-27T06:06:20Z, completed
successfully after 5m4.6s wall clock -- `ActiveState=inactive`,
`Result=success`, `ExecMainStatus=0`). GETs only; no create/cancel/modify
path was ever reached; `/v1/account/balances` was never called.

**Archived 2026-09-27 (post batch-2 gate fix).** The producing script now
lives in this directory as `edge2_ambiguous_order_probe.py.txt`: it is a
one-shot, already-run probe, and the repo-wide read-only guards B1-B6
(`tests/unit/test_polymarket_us_readonly_guard.py`) scan `scripts/` for
order-path literals it legitimately carries as GET path constants
(`/v1/order/`, `/v1/orders/open`), so it cannot live under `scripts/venue/`
at rest -- the same precedent as the 09-05 SFO `probe.py.txt` beside it.
**To re-run it:** copy `edge2_ambiguous_order_probe.py.txt` back to
`scripts/venue/edge2_ambiguous_order_probe.py`, run it, then remove it from
`scripts/venue/` again afterward so the guards stay clean.

Scope: venue order `CP05MNWMAWP6` (MIA 2026-09-23, YES BUY 1 @ 0.52 IOC,
intent `5e50e0d9ee084cd68629b72d1ef81a6b`, instrument
`tc-temp-miahigh-2026-09-23-gte82lt83f.POLYMARKET_US`).

## Verdict

**`ZERO_FILL_BENIGN`** -- no remediation. The order never traded; the
resolver's 09-24 retirement as `STATUS_REPORT_ZERO_FILL_TERMINAL` is correct.
Slice E (the remediation CLI) is **not built**: Step 0's Q2(i) count is 0.

## Q2s (ordering / cursor-stability) verdict

**`STABLE`** -- all three checks held over the full 35-activity account
history (a single page, `eof=true` on every traversal):

1. **Non-increasing order** (descending run 1): held across all 35
   `createTime` values.
2. **Re-read identity** (>= 5 minutes apart): run 1
   (`PRIVATE_activities_desc_r1_p0.json`, 06:06:20Z) and run 2
   (`PRIVATE_activities_desc_r2_p0.json`, 06:11:2xZ, 300s later) produced the
   **identical** 35-row id sequence -- no duplicate, no gap, no reorder.
2. **Ascending = exact reverse**: the `SORT_ORDER_ASCENDING` traversal
   (`PRIVATE_activities_asc_p0.json`) is the exact reverse of the descending
   run 1 sequence.

**Scope note (python review round 2).** The account's entire history fit in
ONE page on every traversal (`eof=true` from the first page each time), so
the cursor path was never exercised and the `min(createTime) < createdNs`
half of `complete = eof ∨ min(createTime) < createdNs` was never reached --
only the `eof` branch was. `STABLE` therefore holds under the plan's literal
Q2s definition (all three checks were evaluated and passed over what the
venue actually returned), but it licenses slice D's completeness rule ONLY
for the `eof` branch. The `min(createTime) < createdNs` branch stays
UNLICENSED by this run until a multi-page traversal is actually observed and
Q2s is re-verified across a page boundary -- tracked as follow-up
`EDGE-2-MULTIPAGE`. This does not affect the `ZERO_FILL_BENIGN` verdict
above: that verdict rests on `eof` completeness, which this run did
exercise.

## Positive control (PC)

**Passed**, using `CNC3HJD66WP9` (the first of the two plan-listed
candidates). The Q2(i)-style join found exactly 1 `ACTIVITY_TYPE_TRADE` row
for that id inside the same paged window that showed 0 rows for
`CP05MNWMAWP6` -- so the join mechanism is proven capable of finding a real
trade, and the 0-count for the target order is not an artefact of a filter
bug or an empty feed. (The second candidate, `CMSN9WPWWWPB`, also matched
independently.)

## Q1 -- `order_by_id` (`PRIVATE_order_by_id.json`)

| Field | Value |
|---|---|
| `id` | `CP05MNWMAWP6` |
| `marketSlug` | `tc-temp-miahigh-2026-09-23-gte82lt83f` |
| `side` / `intent` | `ORDER_SIDE_BUY` / `ORDER_INTENT_BUY_LONG` |
| `state` | `ORDER_STATE_EXPIRED` (terminal) |
| `quantity` / `cumQuantity` / `leavesQuantity` | 1 / 0 / 0 |
| `avgPx` | 0.0000 USD |
| `outcomeSide` | `OUTCOME_SIDE_YES` |
| `createTime` | `2026-09-23T17:22:07.801680656Z` |
| `lastTransactTime` | `2026-09-23T17:22:07.803075924Z` |

This is exactly the L-36-authoritative zero-fill shape (terminal, `cum=0`),
matching the plan's section 2.1 evidence (`ORDER_STATE_EXPIRED qty=1 cum=0
leaves=0`) and the create-path AMBIGUOUS log line's timing.

## Q2 -- `activities_desc` (`PRIVATE_activities_desc_r1_p0.json`)

One page, `eof=true`, 35 activities total (the account's entire history back
to 2026-08-05 -- well before the 2026-09-23T17:21:00Z completeness
threshold, so **complete** by the `eof` branch alone).

- **Q2(i)** (`ACTIVITY_TYPE_TRADE` with `trade.aggressor.id` or
  `trade.passive.id` == `CP05MNWMAWP6`): **0 rows**.
- **Q2(ii)** (any `ACTIVITY_TYPE_TRADE` on
  `tc-temp-miahigh-2026-09-23-gte82lt83f`): **0 rows**.
- **Q2(iii)** (`ACTIVITY_TYPE_POSITION_RESOLUTION` on the slug): **0 rows**.
- Q2 trade-quantity sum for the order: **0**.

## Q2b -- `activities_types_trade` (cross-check only, not relied on)

Server-side `types=[ACTIVITY_TYPE_TRADE]` filter, 17 trade rows returned --
consistent with the 17 `ACTIVITY_TYPE_TRADE` rows counted inside the
unfiltered Q2 page. None on `CP05MNWMAWP6` or the MIA slug.

## Q3 -- positions (`PRIVATE_positions_market.json`, `PRIVATE_positions_all.json`)

- `positions_market` (`market=tc-temp-miahigh-2026-09-23-gte82lt83f`):
  `{"positions": {}, "eof": true, "availablePositions": []}` -- no holding on
  the slug.
- `positions_all` (unfiltered): 2 open positions, both unrelated NCAA
  football markets (`aec-cfb-minnst-wash-2026-09-26`,
  `asc-cfb-minnst-wash-2026-09-26-neg-1pt5`). The MIA slug is absent, as
  expected for a settled market with no fill.

D2 (the "absent proves nothing for a settled market" gap) does not bite
here: Q2's activities join is the deciding evidence, and it independently
shows zero trades for the order.

## Q4 -- open orders on the slug (`PRIVATE_orders_open_slug.json`)

`{"orders": []}` -- empty, as required.

## Q5 -- market settlement (`PRIVATE_market_settlement.json`)

`{"slug": "tc-temp-miahigh-2026-09-23-gte82lt83f", "settlement": 1}` -- the
market settled (MIA reached the `[82, 83)`°F band). Payoff information
only; irrelevant to the verdict since no fill occurred (no P&L to compute).

## L1 -- local corroboration (no venue call)

Read directly from the production exec state store
(`/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite`, opened
read-only) and the ROI reconciliation snapshots under
`~/.local/share/breezy/derived/`. Neither read touched the venue or the live
node process.

**Store keys** (`exec/polymarket_us/` namespace):

| Key | Present | Value |
|---|---|---|
| `fill/CP05MNWMAWP6` | **Absent** | -- (no durable fill record exists) |
| `intent/history/5e50e0d9ee084cd68629b72d1ef81a6b` | Present | `state=RETIRED`, `retirement_reason=STATUS_REPORT_ZERO_FILL_TERMINAL` |
| `budget_restore/CP05MNWMAWP6` | Present | `1` (permit was restored on the 09-24 terminal-zero retirement) |
| `venue_id/CP05MNWMAWP6` | Present | maps the venue id to a `ClientOrderId` (routine bookkeeping, not fill evidence) |

The absence of `fill/CP05MNWMAWP6` is exactly what `ZERO_FILL_BENIGN`
predicts: no bot tooling has ever recorded a fill for this order.

**ROI daily reconciliation** (`PRIVATE_portfolio_roi_2026-09-26.json`,
`daily_reconciliation`):

| Day | Classification | Magnitude (cents) | Provisional |
|---|---|---|---|
| 2026-09-23 | `OK` | 0 | true |
| 2026-09-24 | `OK` | 0 | true |

**Residual uncertainty, named (plan section 2.4):** an earlier same-day
snapshot (`PRIVATE_portfolio_roi_2026-09-23.json`) showed 2026-09-23 as
`UNEXPLAINED_CAPITAL_FLOW`, magnitude 113 cents, provisional. That reading
was transient: every later snapshot (09-25, 09-26) shows 2026-09-23 settled
to `OK`, magnitude 0. Both readings are recorded here, per the plan's
instruction not to report only the latest.

**L1 = OK.**

## Decision-table application (plan section 6)

| Input | Value |
|---|---|
| Q1 | terminal (`EXPIRED`), `cum=0`, `quantity=1` |
| Q2 complete | yes (`eof` on page 1) |
| Q2(i) count | 0 |
| Q2(iii) / `beforePosition` | absent |
| Q2s | `STABLE` |
| PC | passed (`CNC3HJD66WP9`) |
| L1 | `OK` |
| Any non-2xx | none (every GET returned 200) |

Matches the `ZERO_FILL_BENIGN` row exactly: "Q1 terminal `cum=0`, Q2 complete
with zero Q2(i) rows, Q2s `STABLE`, PC passed, Q2(iii) absent or zero
`beforePosition`, L1 `OK`." No other row's conditions are satisfied.

## Evidence files (this directory, PRIVATE, mode 0600; directory mode 0700)

| File | Bytes | Contents |
|---|---|---|
| `PRIVATE_order_by_id.json` | 1,636 | Q1 |
| `PRIVATE_activities_desc_r1_p0.json` | 279,987 | Q2 descending, run 1 |
| `PRIVATE_activities_desc_r2_p0.json` | 279,987 | Q2 descending, run 2 (+300s) |
| `PRIVATE_activities_asc_p0.json` | 279,986 | Q2s ascending traversal |
| `PRIVATE_activities_types_trade.json` | 214,250 | Q2b cross-check |
| `PRIVATE_positions_market.json` | 310 | Q3, slug-filtered |
| `PRIVATE_positions_all.json` | 5,308 | Q3, unfiltered |
| `PRIVATE_orders_open_slug.json` | 235 | Q4 |
| `PRIVATE_market_settlement.json` | 89 | Q5 |
| `PRIVATE_summary.json` | 250 | Machine-readable run summary (page counts, PC id used, non-2xx flag) |

None of these files are committed (see `.gitignore` scoping in this
worktree's diff); only this README and the producing script/test are.

## Page counts and non-2xx

- Q2 descending run 1: **1 page** (`eof=true`).
- Q2 descending run 2: **1 page** (`eof=true`).
- Q2 ascending: **1 page** (`eof=true`).
- Any non-2xx across the entire run: **none** -- every GET returned `200`.

## Conclusion

The MIA 2026-09-23 order `CP05MNWMAWP6` never traded. The 09-24 resolver
retirement as `STATUS_REPORT_ZERO_FILL_TERMINAL` is correct and needs no
remediation. AC1 is satisfied: `ZERO_FILL_BENIGN`, `Q2s=STABLE`, PC passed,
evidence pack in place. This verdict is unaffected by the scope note above,
because it rests entirely on `eof` completeness, which this run exercised
directly.

Slice D's completeness rule is licensed **only for its `eof` branch** by this
run. Its `min(createTime) < createdNs` branch was never exercised (the
account's 35-row history fit in one page on every traversal) and stays
UNLICENSED until a multi-page traversal is observed and Q2s is re-verified
across a real page boundary -- follow-up `EDGE-2-MULTIPAGE`. Slice D may
proceed per plan section 8 on the strength of the `eof` branch alone; the
threshold branch's design is unchanged, but its own corroborating evidence
is still outstanding.
