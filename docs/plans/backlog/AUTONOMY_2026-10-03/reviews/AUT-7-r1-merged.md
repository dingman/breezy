# AUT-7 r1: merged review (coordinator). security-reviewer 83, architect 81. Final 81, NOT READY.

**Contradiction resolved.** On the INTEGRITY escalation, security #7 asked to scope it and architect #3 asked to delete it. The coordinator
rules for **deletion**:
- A failed or cancelled rollback leaves F HALTED.
- The engine retries daily, sends CRITICAL through `deliver_with_proof`, and journals a counter.
- Rollback failures never cause a venue INTEGRITY freeze.
- The corrupt-target case (R2) halts only the target lineage's rollback eligibility.

This satisfies both reviewers: no operator dependency, and no venue-wide freeze from one bad target.

## HIGH
- **K1 [sec1]: position handoff on every swap.** Add the invariant: the incoming family's exit seam owns positions held under the outgoing family id, OR the §4.4 check at 16:45 requires "no open positions, or the incoming family owns them". Add a gate-drill test with a position open across each swap (rollback, DRILL_PROMOTE, and the closing ROLLBACK).
- **K2 [sec2]: rollback target eligibility.** The target must have:
  - a fresh ATTEST
  - `is_fee_verified`
  - a current `live_orders_ruling`
  - an age cap
  - no pending cause on the target

  Add these to target eligibility and `readiness()`, with a RED test for each.
- **K3 [sec3; ARCH W12]: drill fills stay in risk.** Drill fills count in every risk detector, in the drawdown limit, in reconciliation and in real P&L, with tests. The drill start gate refuses when drawdown headroom is low.
- **K4 [sec4, arch7]: post-verify and load-time crash.**
  - Post-LAUNCH verify runs at 17:05, keyed to the node's boot-time resolved sha. Declare the AUT-5a boot-line format as a consumed interface; today's line is `fq_live_orders … calibration_sha256=` at `app/trade.py:753-761`.
  - Add an R7: a node crash at load after the resolver passed (TOCTOU, `Path.read_bytes` follows symlinks) writes HALT plus an alert instead of crash-looping.
- **K5 [arch1]: drill retry.**
  - A retry reuses the CHALLENGER r0001 and writes only a new DRILL_PROMOTE+SUPERSEDE pair.
  - `d0_climate_day` equals the root's value, so it is dropped from the changed-key list.
  - Add `test_drill_retry_reuses_admitted_child_and_charges_no_second_admit`.
- **K6 [arch2]: binding intent check on RESUME.** Write RESUME (drill and production) only in the 16:45 pre-launch pass, where `probe_open_intent` is binding. Add a RESUME row to the §3.4 table.

## MEDIUM
- **K7 [sec5]: drill marker and cause.**
  - The marker's `episode_id`, `child_id` and `clause_sha256` must match the chain-derived drill state, the current CHAMPION and the ts SLO window. Otherwise ERROR.
  - A DEMOTE of a drill child carries `cause_code`, and RESUME is allowed only when the cause is `DRILL_INJECT`.
  - A genuine drift DEMOTE on r0001 follows the real-fault path, with no auto-RESUME. Remove the trigger-rule-3 exemption.
- **K8 [sec6]: damping.**
  - Add `ROLLBACK_MIN_DWELL_H`, and define the precedence of RESUME versus ROLLBACK.
  - Add a ping-pong test.
  - A budget-exhausted HALT does not consume the rollback budget.
- **K9 [arch3, sec7]**: Apply the deletion ruling above. The resume rule for engine `cause_code` HALTs is stated, and RESUME of F stays available.
- **K10 [sec8]**: The drill start gate adds fee-verified, permit unexpired, and no OPEN or AMBIGUOUS intent.
- **K11 [sec9]: journals.** The rollback and readiness journals get `prev_sha256` and `chain_head` links, with the journal sha recorded in the chain export or an ATTEST row. Readiness filenames are unique, never overwritten by date.
- **K12 [arch4]**: Cadence is measured from the last COMPLETED episode, and a failed episode is limited only by the 30-day budget. Recompute P90 with its margin to 2027-01-25.
- **K13 [arch5]**: State the statistical cost as about 2 sessions of drill fills (≈10) plus about 1 vetoed session.
- **K14 [arch6]**: The drill ROLLBACK goes through `plan_rollback` in the 16:45 pass, with write and ACTIVATE together. State plainly that the trigger path is gate-proven only when `promote_enabled=false`.

## LOW
- **K15 [sec10]**: Specify the `r<NNNN>` allocator.
- **K16 [arch8]**: The immutability check runs UPDATE on a read-write copy and asserts the trigger's ABORT.
- **K17 [arch9]**: "Empty or unrelated" becomes "empty, or allowed commits listed by sha".
- **K18 [arch10]**: Emit the drill bundle from the D+4 daily engine pass; no new unit.

## ARCH deltas
- ARCH Rev 5: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev5.md`. W2 adds a separate DRILL cause class, W3 makes fq_v1 rollback-eligible, and W5 clears `registry_halted` on a CHAMPION fold.
- ARCH Rev 6 is in progress and will resolve your C-1, C-3, C-4, C-5 and C-6 (planner feedback P7-*). Write your r2 against Rev 5 and state your assumption for each of those.
