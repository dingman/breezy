**Verdict: APPROVE.** No CRITICAL or HIGH findings. Four MEDIUM/LOW items are non-blocking; fold them into the AUT-5a brief and the AC 31 text. I read the full r4 plan and my r3 review. I ran no probes.

**r3 findings 1–9**

| # | Status | Evidence |
|---|---|---|
| 1 HWM index/domain | RESOLVED | AC 16: `venue_seq ≥ 1`, `export_seq ≥ 0`, 64-hex `chain_head`. Compare `rows[venue_seq−1]`. An unknown reading type gives `hwm_unreadable`. All three tests are named. |
| 2 Schemas move and shared predicate | RESOLVED | `FamilyBytes` and `ResolvedFamily` moved out of `schemas`. V22 probes contract (c), including a planted control. AC 10.5 and AC 13 call `rows_admissible` from one home. |
| 3 StagePolicy ban | RESOLVED | AC 15(ii) bans every `replace`, `copy`, `__class__`, `type(x)(` and `object.__new__` call, and resolves aliases. `stage is STAGE` is asserted in `_append` and `_resolve`. |
| 4 Foreign introducers | RESOLVED | AC 13 and AC 14: `FoldInvalid` for any other introducing kind, and `root_lineage_mismatch`. |
| 5 Reset CLI | RESOLVED | Note 6e requires `--expect-head`, prints the standing DEMOTE/HALT rows, and runs the restrictiveness check. R14 words `hwm_absent` as a tripwire. |
| 6 DEMOTE latency | RESOLVED | R14 and note 8. |
| 7 Shadow role assertion | RESOLVED | AC 17.0 and AC 18. `ShadowPaths` is not a subclass of `AutonomyPaths`. |
| 8 Test hunk | RESOLVED | V29. |
| 9 DIR_NOT_WRITABLE | RESOLVED | AC 7 refuses on the mode bit. The test is in AC 28. |

**New findings**

**N1. MEDIUM. Note 6d, L1 cut-over: `flock -w 5` can acquire the lock and write after 16:44:55.**
- Failure scenario: the script reaches the lock at 16:44:54, waits up to 5 s and writes at about 16:44:59. That is inside the window the plan says it never writes in. It also overlaps the 16:45:00 E-8 snapshot, which holds the same flock.
- Failure scenario: the abort path deletes the key, and that delete is itself a write at or after 16:44:55. The plan words it as "never writes in [16:44:55, 16:50:00)", which contradicts it.
- The named test only checks that the slot ends by 16:44:55.
- Fix:
  - Compute a monotonic deadline once.
  - Use `flock -w min(5, deadline − now)`.
  - Re-check the clock after acquiring the lock and before the write.
  - Treat a write that completes after the deadline as an abort.
  - Carve out the key deletion explicitly. It may run only while the script holds the lock. If the lock was never acquired, there is no key to delete.
- Tests to add: lock acquired at 16:44:54 aborts; a write completing after the deadline aborts; abort leaves no key and no registry.
- A stale HWM left behind by a failed delete only causes `hwm_regressed` on the next cut-over. That is fail-closed, and the reset CLI clears it.

**N2. MEDIUM. Note 6b/6c: the boot HWM write is not specified as monotone, so a stale boot write can lower `venue_seq` or `export_seq`.**
- The node writes `ResolvedFamily.hwm`, computed at resolve time, under the intent flock. The plan does not say the watch actor's tick writes take that flock.
- Failure scenario: a tick writes a higher `venue_seq`/`export_seq` between the node's resolve and the node's boot write. The stale boot write then overwrites it with a lower HWM, which weakens the regression detector. The plan's "never lowered" covers only the actor's in-memory carry-forward.
- Within a single resolve, `export_seq` cannot be lowered: step 4 guarantees `hwm.export_seq ≤ newest_export_seq`. So `next_hwm` can only raise it.
- Fix: one `hwm.write_monotone(store, new)` helper.
  - It runs under the flock.
  - It re-reads the current HWM through `hwm_reading_from_bytes`.
  - It refuses or skips unless `new.venue_seq ≥ cur.venue_seq` and `new.export_seq ≥ cur.export_seq`, with the hash at the same `venue_seq` consistent.
  - Every writer uses it: node boot, ticks and the cut-over.
  - Only the reset CLI bypasses it.
- Add `test_hwm_write_never_lowers`.

**N3. LOW. AC 31: the append-only pin test is only as strong as its base ref.**
- A same-commit edit of the manifest and its pin row cannot bypass the test when the base already contains the row. The row would change, and that is refused.
- Two cases make it vacuous. The first is a commit pushed directly to a branch where `merge-base HEAD <ref>` is HEAD. The second is a shallow clone or a missing git. Both make the test pass or skip silently.
- This is acceptable, because the "reviewed commit" anchor is review, not the test. The runtime check is `row.manifest_sha256 == sha(deploy file)`, and a bypassed edit fails closed as `manifest_sha_mismatch`.
- Fix: name the base ref (the integration branch). Make the test fail, not skip, when the ref is unavailable. Note that the test is CI hygiene and not a security control.

**N4. LOW. Note 5: `_tick_once` applies `new_rows[:adm.admitted]` and then runs `validate`.**
- Fold applies the prefix, while `validate` and the HWM stay un-advanced. That is restrictive-correct.
- The plan does not say whether the next tick re-reads from the last verified seq. It must, so the refused row is re-evaluated and the prefix is not double-applied.
- Add a test that two consecutive refused ticks give an identical in-memory fold.

**ResolvedFamily carry-forward: no hole found.**
- `export_seq` is raised only by a verified export read. The check `export_seq > newest_export_seq` is not clearable by the engine.
- The one consumer-side forging path is a same-uid HWM write, which is the R14 residual, and N2 hardens it.
- `rows_admissible` is applied as a prefix and also refuses in the resolver, which is fail-closed.

**Invariants.**
- All hold. The plan has no `enabled` or permit field, and only `permit_absent` is accepted.
- The exec client is read by AST only.
- Operator-reserved controls are not named.
- No guard test is weakened.

Plan reviewed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r4.md`