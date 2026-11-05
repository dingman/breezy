# AUT-7 r2: merged review (coordinator). security-reviewer 86 (2 HIGH), architect 77 (4 HIGH). Final 77, NOT READY.
Main cause: r2 was written against ARCH Rev 5. **Rebase on Rev 6**
(`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev6.md`) and on
`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ROLLBACK-FAILURE-decision.md` (binding).

## HIGH
- **T1 [arch H1]: the drill includes HALT (Rev 6 §5.3, P6-4).** The sequence is DEMOTE → RESUME → HALT (via `DRILL_INJECT_HALT`) → ROLLBACK, with the child DISPLACED HALTED→CHALLENGER.
  - Add `detector` to the marker schema, with a time window per step.
  - Add HALT to the drill budget, the §6 bundle, the delivery events, `test_gate_drill_full_episode` and `test_drill_halt_never_freezes_or_writes_exec_store`.
- **T2 [arch H2]: pre-launch write split (Rev 6).**
  - At 15:30, after the advisory intent check, write MINT, DRILL_ADMIT and the DRILL_PROMOTE pair.
  - At 16:45, run G-1..G-10, then write ACTIVATE or SWAP_CANCEL. The 16:45 pass also writes ROLLBACK together with its ACTIVATE.
  - Restate the K5 retry in terms of this split.
- **T3 [arch H3, sec N2]**: Adopt the ROLLBACK-FAILURE decision: `rollback_failed` in a non-freezing class, and a target byte mismatch makes the target ineligible without freezing. Drop the plan's own `cause_code` values and `MAX_ENGINE_HALT_RESUMES_PER_VENUE_7D` [arch L1]. Update C-3, C-8 and C-9.
- **T4 [arch H4]**: The drill budget must not strand a retry. Either the closing drill ROLLBACK is restorative and never refused by the budget, or G-2 requires D′ ≥ (newest charged drill row) + 27 d. Recompute P90 and its margin to 2027-01-25.
- **T5 [sec N1]: a genuine fault on the drill child.** When any non-`DRILL_INJECT*` cause is on the child:
  - Never ROLLBACK to a target with the same `artefact_sha256`.
  - Leave r0001 HALTED and write RETIRE or an abandoned-episode close.
  - Apply E9 and the production budget.
  - Add `test_genuine_fault_on_drill_child_never_restores_identical_artefact`.

  State what sends next. If no other eligible family exists, the venue has no sender until an eligible champion exists. That is fail-safe, and an alert is raised.

## MEDIUM
- **T6 [arch M1, sec N4]: dwell.** Measure it in launch-dates (≥1 LAUNCH since the last effect), or delete `ROLLBACK_MIN_DWELL_H` and rely on the Z3 ceilings. State how the drill's closing and abort ROLLBACKs are treated. Define `ATTEST_MARGIN_H` against W1 (the 1.04 h constant).
- **T7 [sec N3]**: `verify_journal_chain` compares against the newest export's heads. A mismatch or a missing tail blocks rollback and sends a CRITICAL. Test it.
- **T8 [sec K4]**: Keep WP3 activation gated on the AUT-5a signals (`registry_boot_load_failed`, supervisor non-relaunch, bytes passed to composition). List them as named consumed interfaces.
