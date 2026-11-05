# AUT-6 r2: merged review (coordinator). silent-failure-hunter 86 (2 HIGH), trading-bot-architect 86 (1 HIGH). Final 86, NOT READY.

**Rebase on ARCH Rev 6** (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev6.md`). Rev 6 decides D-HALT by adding a
`DRILL_INJECT_HALT` drill detector. It never writes the exec store and never freezes anything, and one drill run gives the AUT-5 and
AUT-6 HALT proofs. Existing exec-store halts are declared gate-proven only. Rev 6 also makes AUT-6 the only SELF_HEAL and ALERT executor,
puts the dead-man in AUT-5, and archives demand files by rename (W16). Absorb all of this. C-12 (second demand writer) goes to the ARCH
Rev 7 or 8 decision; state your assumption.

## HIGH
- **G1 [sf N1]**: A persistently UNKNOWN health pass must not look healthy. The dead-man and the intraday reciprocal watch both FAIL when `passes_unknown_streak ≥ 3`, not only on age. Test it.
- **G2 [sf N2]**: On an unreadable or empty fold the producer writes a CRITICAL `fold_unreadable` and sets `heartbeat.fold_ok=false`; #26 then FAILs. Test it.
- **G3 [ops HIGH-1]: #15 `fill_better_than_ask`.**
  - Restrict it to taker IOC fills, exclude resting orders, and normalise the leg sign (the venue shows a NO buy as SELL/BUY_SHORT).
  - Compare against the book at the fill timestamp (`depth_ref`), not the decision-time ask.
  - Add `test_legit_ask_drop_and_resting_fill_do_not_trip_integrity`.
  - State the remaining false-positive risk and that the INTEGRITY floor clears through build-side incident handling.

## MEDIUM
- **G4 [ops M1]**: Rebase as above. Fix the demand clearing text (archived by rename, never unlinked).
- **G5 [sf N3]**: Commit the journal cursor and seen-file only after the classification and action rows are written. Dedupe on `USER_INVOCATION_ID`, and add a crash-between-steps test. Add fixtures for the `exit-code` and `signal` results.
- **G6 [sf N4, ops M4]: timer scan.**
  - Scan every key of `TIMER_MAX_INTERVAL_S`, keyed by template plus enumerated enabled instances (for example `breezy-family-tally@…`).
  - A timer that is not enabled, or has `LastTriggerUSec=0` after grace, is FAIL.
  - Use `NextElapseUSecMonotonic` for `OnUnitActiveSec` timers.
- **G7 [sf N5]**: Add `aut6.halted_too_long` (more than 24 h halted) with `metrics.halted_age_s`.
- **G8 [sf N6]**: For a CRITICAL, write the outbox entry at submit time and delete it on 2xx, so it survives a SIGKILL.
- **G9 [sf N7]**: Make #15 intraday, or state its latency. Reserve one demand-file slot for INTEGRITY.
- **G10 [sf N8]**: Add `alert_delivery_journal_unwritable` to #23's inputs.
- **G11 [ops M2]**: A daily producer lock timeout prints `PRODUCER_DAILY SKIPPED lock_timeout`, exits 0 and counts toward #27. Add a RED test.
- **G12 [ops M3]**: Size discovery-pull from its working set (RSS plus swap). If the working set is over 1 GB, redesign the job (chunk or stream) rather than raising the ceiling.

## LOW
- **G13 [sf N9]**: When the journal is unreadable, the canary retry gate sends. The `run-*` ownership rule includes the repo path.
- **G14 [ops LOW]**: State the veto arithmetic: about 17:45Z the next day, inside the trading window. Give idempotency evidence for each self-heal unit. For the `/proc` scan, set `ProcSubset=all` or fall back to UNKNOWN.
