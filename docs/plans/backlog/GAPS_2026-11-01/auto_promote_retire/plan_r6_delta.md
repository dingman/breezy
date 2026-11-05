# AUTO-PROMOTE-RETIRE plan r6: delta over r5 (portfolio financial basis from AUD-04 r2.3/r2.4)

Applies on top of:
- `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r1.md`
- `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r2_delta.md`
- `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r4_delta.md`
- `docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r5_delta.md`

`docs/plans/backlog/GAPS_2026-11-01/auto_promote_retire/plan_r3_delta.md` is SUPERSEDED ENTIRELY by r4 (`plan_r4_delta.md:19`) and is not applied.

Where they differ, this delta wins. Status: FINAL-ROUND DRAFT (round-2 items 1, 4, 5, 6 and 11 applied in place; round-3 AUD-04 Erratum r2.4-e1 applied in place to R6-2 and R6-5).

Trigger: `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_3.md` §2 item 4 (option b), as amended by `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-ROI-LEDGER-delta-2026-11-04_r2_4.md`. The accessor serves a per-family residual block. That restores the n_p partition and the residual P&L that r1 `:81-94` requires and r2.2 had dropped.

## R6-1 Portfolio financial basis
For family F, `e = read_roi_for_decision(path, now).for_family(F)`. A served `e` (`FamilyDecisionStats`) is the "complete current portfolio set" (r1 `:82`), covering every fill attributed to F through `settled_through`.
- `residual_loss = max(0, −residual_pnl)`. This is r1 `:83`'s unsigned loss magnitude; a positive residual is never credited.
- `total_pnl = net_pnl − residual_loss`. Both figures are net of fees, so nothing is subtracted again. `net_pnl` is over F's COMPLETE admissible rows.
- **n_p (B2):** `n_p = n_admissible + n_incomplete + n_residual`. All three terms are report-native (AUD-04 r2.4 §5), and accounting `fill_rows` are NOT used.
  - `fill_rows` supply only the accessor's partition check: `n_other_excluded = n_fills_attributed − n_p`, and a value below 0 is `FAMILY_PARTITION`.
  - This restates r1 `:81` with no erratum. Eligibility requires `n_other_excluded == 0` (R6-2), so r1's `n_p = n_a + n_residual + n_other_excluded` and this definition agree on every eligible pass.
- n_a, S (including the per-row win term), looks and boundaries stay on #7's own exact prefix (r1 `:79-80,84-85`), unchanged. #7 reads no `n_wins` from the view (AUD-04 r2.4 §3).
  - #7 requires `own_prefix_n_p ≤ n_p`. Otherwise that pass withholds entry and eligibility.

## R6-2 Asymmetric use of flagged inputs
**Eligibility** (permissive: PROMOTE-ELIGIBLE / ARM) reads ONLY a served `FamilyDecisionStats`, never a refusal's `restrictive` block. It requires ALL of:
- a served `e`;
- `n_residual_fee_unverified == 0`;
- `n_residual_settlement_disagree == 0`;
- `n_residual_pending == 0`;
- **(B1)** `n_other_excluded == 0`. The exception ("the bucket holds only fills with no P&L") is disproved structurally: C2 `UNATTRIBUTED` settled rows book `net` into F's bucket (`src/breezy/analysis/labeling/accounting.py:556-577`). AUD-04 S0 re-reads that path at the build HEAD, and the strict rule binds while it holds. The bucket is disclosed on every row either way. A served `e` with `n_other_excluded > 0` also WITHHOLDS ENTRY for F (e1). P&L in that bucket is outside `net_pnl`, so LOSS_STOP cannot see a loss there. This is no RETIRE and consumes no look;
- **(freshness, AUD-04 Erratum r2.4-e1)** `input_freshness_status == "OK"` OR `n_open_anchors_without_fill == 0`. A `None` count is treated as non-zero. The count is |{anchors whose `client_order_id` has no `DurableFillRecord`} ∪ {anchors with `arm_ns >` the newest fill's `ts_event`}| (AUD-04 r2.4 §1.4).
  - No durable terminal-close record exists, so a cancelled, expired or IOC-missed entry counts for good. Once any entry goes unfilled, the STALE branch never passes. That is accepted as fail-closed, and only OK freshness clears it.
  - A count of 0 means only that every anchored BUY entry has a fill record and none was armed after the newest one. It does NOT prove that no unseen fill exists: SELL exits are outside the count, and S0 bounds ingest gaps. The guard against unseen fills remains the exec reconciliation latch (`src/breezy/adapters/polymarket_us/exec/client.py:188-216`);
- `total_pnl > 0`.

**A STALE view is never new evidence.** On a view with `input_freshness_status != "OK"`, a pass:
- consumes no look;
- never advances n_a or n_p beyond its own prefix;
- records no new PROMOTE or ARM state unless the freshness rule above holds.

Freshness never affects LOSS_STOP, refusals or entry withholding.

**LOSS_STOP** (restrictive: r1 `:89`) is UNCHANGED in its threshold and cadence. It reads `total_pnl` on every pass, from:
- a served `e`; or
- a `FamilyDecisionRefusal` whose `restrictive` block is set (`FAMILY_FEE_UNVERIFIED`, `FAMILY_SETTLEMENT_DISAGREE`, `FAMILY_INCOMPLETE`, `FAMILY_PARTITION`; AUD-04 r2.4 §6.1). The same formula applies to the block's `net_pnl` and `residual_pnl`.

A refused family therefore never blinds LOSS_STOP.
- **`FAMILY_PARTITION` disclosure (e1).** A partition refusal means `n_p > n_fills_attributed`. So that block's `net_pnl` may double-count a row, in either sign. It is read RESTRICTIVELY only: it may cross LOSS_STOP, and it never feeds eligibility. F's entry is already withheld by the refusal, so an overstated gain cannot add exposure.
- LOSS_STOP is evaluated even when fees are unverified. Fee uncertainty cannot hide a settled loss, and stopping early is conservative.
- If the refusal is `FAMILY_SETTLEMENT_DISAGREE`, or `n_residual_settlement_disagree > 0`, the booked sign may be wrong. Entries for F are withheld (r1 `:90` "Gated inputs withhold entry"), and a crossing is recorded as pending, not as a RETIRE verdict, until the disagreement clears. No verdict is invented.

**Open positions (AUD-04 r2.4 §6.2).** An unsettled fill is not in `n_incomplete`, so it does not refuse F.
- If AUD-04 S0 finds otherwise, an open position refuses F for eligibility until it settles.
- LOSS_STOP still reads F's settled `net_pnl` and residual block from `restrictive`.

**Refusals:**
- A report-level refusal (no block) withholds entry and eligibility for every family. It never RETIREs and never consumes a look.
- A family-level refusal does the same for that family only, and LOSS_STOP still reads its block as above.
- `UNKNOWN` and `NOT_IN_REPORT` carry no block and never affect a registered family.

## R6-3 Units
- The v3 LOSS_STOP is −60 contract-units (r1 `:89`). `total_pnl` from the view is USD.
- The two are equal only for qty-1 registrations (`ScoredTrial.pnl` is per-contract; scored writers admit qty 1).
- A family whose PREREG admits qty > 1 (the #5 sizing path) must register a USD-basis LOSS_STOP, or enrolment is blocked (r1 `:89`, unchanged).

## R6-4 E-TE1-a
This item relies on AUD-04 r2.3/r2.4's reading:
- The residual block's money is `ResidualSettlement`-based, not an accounting sum.
- Accounting `fill_rows` supply only the partition count and the two CLI-disagree refusal counts.

The rules for this item:
- #7's decision module imports only `breezy.persistence.portfolio_roi_decision`.
- The TE-1 AST guard (`tests/support/te1_accounting_guard.py`) is NOT widened. Any `accounting` reference from #7 fails it.
- #7 appends its module to an import contract when that module is created (AUD-04 r2.2 §1 D3).

## R6-5 RED-first tests (add to r4 §6)
1. `test_residual_only_loss_crosses_loss_stop_with_unchanged_n_a`
2. `test_positive_residual_is_never_credited_to_eligibility`
3. `test_fee_unverified_residual_blocks_eligibility_but_not_loss_stop`
4. `test_residual_settlement_disagreement_withholds_entry_without_retire`
5. `test_report_refusal_withholds_entry_and_consumes_no_look`
6. `test_family_refusal_on_a_does_not_affect_b`
7. `test_partition_refusal_blocks_eligibility`
8. `test_stale_view_with_open_anchors_without_fill_blocks_eligibility_only` (param: count > 0 and `None`). LOSS_STOP still evaluates, and no look is consumed.
9. `test_stale_view_with_zero_open_anchors_without_fill_still_serves_eligibility`
10. `test_other_excluded_nonzero_blocks_eligibility_withholds_entry_and_is_disclosed` (e1: entry is withheld; no RETIRE; no look consumed)
11. `test_family_refusal_restrictive_block_feeds_loss_stop_never_eligibility` (param: fee, incomplete, partition; disagree records a pending crossing)
12. `test_n_p_is_admissible_plus_incomplete_plus_residual_without_fill_rows`

r6's former test 8 (`fees_total` not subtracted twice) is dropped: the field no longer exists (AUD-04 r2.4 §3), and AUD-04 AC 4 proves fees are counted once.

Fixtures come from AUD-04's production writer (L-24).

## R6-6 Invariants (restated)
- Nautilus Trader is immutable.
- `allow_short=False`.
- Leg sign only via `leg_of_symbol`.
- NO-SEND.
- Never assign, default or propose the operator day, position or month caps, and never name their env vars.
- Never weaken a safety, settlement, contract or pin test (the TE-1 guard is byte-unchanged).
- New tests are classified in `scripts/ci/gate_reviewed.json` and `scripts/ci/gate_durations.json`.
- `lint-imports` after every slice.
- No `dataclasses.asdict`.
