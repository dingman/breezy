# SIZE-UNDER-CAPS plan r5: delta over r4 (capital source amendment, driven by AUD-04 r2.3/r2.4)

Applies on top of:
- `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r1.md`
- `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r3_delta.md`
- `docs/plans/backlog/GAPS_2026-11-01/size_under_caps/plan_r4_delta.md`

Where they differ, this delta wins. Status: FINAL-ROUND DRAFT (round-2 items 1 and 7 applied in place).

Trigger: AUD-04 removes `available_capital` from `RoiDecisionView`, because #4 owns no capital. See `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_3.md`, as amended by `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_4.md`. Without this amendment, r3 §4 (`plan_r3_delta.md:46`, `ledger_B = view.available_capital`) and r1 Stage 2 (`plan_r1.md:76-77`) make #5 size at zero by construction (L-3).

## R5-1 Spendable capital: native Nautilus (L-1, NATIVE EXISTS)
The source is `Account.balance_free(USD)` (`nautilus_trader/accounting/accounts/base.pyx:262`) and `Account.balance_total(USD)` (`:226`), read from the native cache for the PM.us venue account. It never comes from a report scalar.

Where the value comes from:
- The PM.us exec client publishes the native `AccountState` with `free = buyingPower` and `total = currentBalance` (`src/breezy/adapters/polymarket_us/exec/reports.py:1015`, ROUND_DOWN, never overstated).
- It publishes at connect (`src/breezy/adapters/polymarket_us/exec/client.py:2739`) and on every native `QueryAccount` (`_query_account` `:5639` → `_publish_account_state` `:5648`).
- Strategies request a refresh with native `Strategy.query_account` (`nautilus_trader/trading/strategy.pyx:1492`).

The account carries `calculate_account_state=False` (`client.py:208`; `nautilus_trader/portfolio/portfolio.pyx:502`), so fills NEVER update it. The figure is a venue snapshot, and every rule below follows from that.

- **buyingPower is an upper bound, not a bankroll.** It is the most the venue will accept, and it may include credit, bonus or other non-cash capacity (UNVERIFIED). So the spendable base is `B_cap = min(balance_free, balance_total)`. A figure above `currentBalance` is never trusted.
  - The parser already refuses `free > total` rather than clamping it (`reports.py:1023-1024`). The `min` is defence in depth at the sizing site, and a test pins it.
- **Venue evidence (S0, read-only, NO new live calls).** S0 records what `buyingPower` includes (credit, margin, working orders) from existing logged account payloads only:
  - `docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-04.md`
  - `docs/evidence/venue/polymarket_us/BALANCES_SHAPE_DRIFT_2026-09-19.md`
  - the two `PRIVATE_v1_account_balances_*.probe.json` captures (counts and field names only)
  - the node's logged balance lines

  Undecidable evidence keeps every conservative rule below.
- **Timestamp.** `AccountState.ts_event` is the receipt time. `_publish_account_state` takes `self._clock.timestamp_ns()` right after `_private_read` returns (`client.py:5655-5661`), with no await between them. It is never a later local publish clock. Freshness compares `ts_event`, never `ts_init`.
- **Freshness.** Size only against an `AccountState` whose `ts_event` is at or after the newest fill or reservation the exec client booked on that account. Otherwise issue `query_account` and size zero (typed refusal `BALANCE_STALE`) until a newer state arrives.
  - A frozen, bot-derived `policy.max_balance_age` also bounds `now − ts_event`. S0 sets it; it is not an operator control.
  - **Blind spot.** This comparison cannot see a venue fill the client never booked. That gap is bounded by the exec client's reconciliation latch: a reconcile mismatch latches a node-global, never-self-clearing refusal, and native cash is non-authoritative while latched (`client.py:188-216`). A latched refusal is a sizing refusal (below). See AUD-04 r2.4 §1.2 and §1.6.
- **H_B.** `H_B = B_cap − working/in-flight reservations` held under `self._lock`.
  - Reservations are subtracted even though `buyingPower` may already net resting orders (UNVERIFIED). Subtracting twice only shrinks `q`, and r3's "never twice" applies to overstated headroom.
  - S0 may remove the extra subtraction only with logged venue evidence that `buyingPower` excludes open orders.
- **Refusals (each is zero with a typed refusal).** Any of these blocks sizing:
  - no venue account in the cache;
  - `balance_free` or `balance_total` is `None` or not in USD;
  - any reconciliation refusal is latched (`client.py:200-216`);
  - `resting_cancel_unconfirmed` is latched (R4-3).
- **Shared account and caps.** The account is shared with manual trading (ruling 10-29). `buyingPower` is account-wide, so manual activity can lower it or raise it.
  - The bot never attributes the balance to itself.
  - The three operator caps (day, position, month) remain the binding spend bounds. Their values are never assigned, defaulted or proposed here, and their env vars are never named.

## R5-2 Open exposure: the exec client (R4-3), not the report
R4-3 (`plan_r4_delta.md:12`) DOES hold committed cost: `{(instrument_id, leg): Σ cumulative_cost}`, with no day filter, restart-safe, booked by `seed_position_committed(...)` under `self._lock`. `H_position` reads only that ledger plus live reservations.

Supersede `plan_r1.md:76` ("realised P&L, open cost basis and available capital come ONLY from `read_roi_for_decision`"):
- Open cost basis comes from R4-3.
- Spendable capital comes from R5-1.
- Realised P&L is NOT a sizing input. Losses are already in the venue balance, and gains never restore capacity beyond the caps, so r1's "losses shrink, gains never replenish gross spend" holds.
- `B_eff = min(operator_D2_bankroll, ledger_B)` stays deleted (r2 removed D2).

## R5-3 What #5 still takes from the accessor: a per-family data-quality precondition only
Before sizing family F, the composition calls `read_roi_for_decision(path, now)`. Sizing proceeds only if both of these hold:
- the result is a `RoiDecisionView`;
- `view.for_family(F)` is a served `FamilyDecisionStats`.

Otherwise the size is zero, and the refusal carries the accessor's reason. That includes every `FamilyDecisionRefusal`, whether or not it carries a `restrictive` block.

- #5 reads NO money field from the view or a refusal: `net_pnl`, `residual_pnl` or the `restrictive` block (AUD-04 r2.4 §6.1: restrictive use is #7 LOSS_STOP only). `fees_total` no longer exists (r2.4 §3).
- #5 reads none of the freshness disclosures (`input_freshness_status`, `n_orders_since_newest_fill`). Capital freshness is R5-1's `BALANCE_STALE`.
- An open position does not refuse F: it is not in `n_incomplete` (AUD-04 r2.4 §6.2). If that S0 check FAILs, the zero-size consequence is recorded as a #5 blocker, never silent.
- The age bound is the accessor's `MAX_DECISION_REPORT_AGE` and is never restated here. This replaces r3 `:47-48`'s "[0,24 h]" and balance `observed_at` clauses.

## R5-4 Tests (RED-first; add to r3 §6/r4)
1. `test_balance_free_or_total_none_or_non_usd_sizes_zero`
2. `test_spendable_base_is_min_of_balance_free_and_balance_total`
3. `test_account_state_older_than_newest_booked_fill_sizes_zero_and_queries_account`. It compares `ts_event`; a fixture with a later `ts_init` but an older `ts_event` sizes zero.
4. `test_account_state_older_than_policy_max_age_sizes_zero`
5. `test_latched_reconciliation_refusal_sizes_zero_before_reading_balance`
6. `test_reservations_are_subtracted_from_spendable_base_once`
7. `test_open_cost_comes_from_position_committed_ledger_not_the_report`
8. `test_accessor_report_refusal_or_any_family_refusal_sizes_zero` (param: with and without a `restrictive` block)
9. `test_sizing_path_never_reads_a_view_money_field`: an AST/call-path check over the composition module for `net_pnl`, `residual_pnl` and `restrictive`, with a planted positive control.

Every report fixture is written by the production writer (L-24). The full gate is `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/size-under-caps`; read the EXIT code.

## R5-5 Invariants (restated)
- Nautilus Trader is immutable: `balance_free`, `balance_total` and `query_account` are used as shipped.
- `allow_short=False`.
- Leg sign only via `leg_of_symbol`.
- NO-SEND: `query_account` uses the existing authenticated exec path, S0 makes no new live call, and the sizing core stays pure.
- Never assign, default or propose the operator day, position or month caps, and never name their env vars.
- Never weaken a safety, settlement, contract or pin test.
- New tests are classified in `scripts/ci/gate_reviewed.json` and `scripts/ci/gate_durations.json`.
- `lint-imports` after every slice.
- No `dataclasses.asdict`.
