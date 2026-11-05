# AUD-19 — round 4 — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 6e1dfec7b3303156b7636cbc3cfcc096e792336da6a5655f50c306d69e543cf7
Reviewer: silent-failure-hunter (blind, independent)

## Round-3 finding — verified fixed
§6 E3's blanket "any non-zero driver exit → BLOCKED, day stays queued" is replaced by an exit-code
dispatch table. Verified against source: `EntryAskFromLatchMissingError` at
`scripts/analysis/current_rung_hold_paper_replay.py:180`, `NoDecisionWindowCoverageError` at `:195`,
`ImpossibleFillPriceError` at `src/breezy/runtime/paper_replay.py:131` — all exact. New C7 exit codes
follow the repo's real convention: `EXIT_OK=0`/`EXIT_REFUSED=2`/`EXIT_NOTHING_TO_CLEAR=3` at
`clear_family_halt_cli.py:46-48`, `EXIT_OK=0`/`EXIT_REFUSED=2`/`EXIT_NOTHING_OPEN=3` at
`clear_submit_intent_cli.py:28-30`, `EXIT_OK/EXIT_NOT_CONFIGURED/EXIT_DELIVERY_FAILED` (`Final[int]`)
at `check_alerts_cli.py:51-53` — all confirmed. RED tests added (step 22: refusal-exit-code test,
FAILED-class-never-BLOCKED test, message-blanking test); A14/A17 extended.

## D6 attacked, per instruction
D6 (§12) and E3's last table row govern an exit code outside `{0, 1, 2, 3}` — e.g. a driver killed by
`SIGKILL`/OOM (returncode 137 or -9 under `subprocess.run`), a segfault, or any crash that never
reaches Python's own uncaught-exception handler. The plan states this is "treated as `FAILED`-class
(day leaves the queue, exit non-zero)".

**This is a silent-failure hole, not a resolved case.** Three problems, none covered by any RED test
or acceptance criterion in this round's diff:
1. **No row-write is specified.** AUD-09's queue mechanism removes a day only by the *presence* of a
   terminal row (`COMPLETED`/`RECOVERED`/`FAILED`) for its key — confirmed by §6b.3's crash-recovery
   design (`:650-657`) and the target-selection description (`:543`). D6 says the outcome is "treated
   as FAILED-class" but never states that the runner actually calls `append_replay_result` for this
   branch, with what `outcome`/reason value, or that doing so is what makes "day leaves the queue"
   true rather than merely asserted in prose.
2. **No RED test exercises it.** Step 22's list (refusal-exit-code test, FAILED-class-exception test,
   message-blanking test, anchor test, wrapper-set test, argv_sha256 round-trip) contains nothing for
   a returncode outside `{0,1,2,3}`. A14/A17 do not mention it either.
3. **The three named exceptions collapse to code `1`, and A17 pins the runner to classify on
   `returncode` alone, never message text — so a signal-killed subprocess (no Python exception, no
   stderr traceback in the same shape) is exit-code-indistinguishable from "some future fourth named
   exception" unless the runner explicitly buckets "any code not in `{0,1,2,3}`" as its own case,
   which D6 asserts but never specifies where that bucket's identity is recorded for diagnosis.**

If (1) is not actually implemented — e.g. the runner logs and returns without appending a row — the
day is neither provably left nor provably kept, which is exactly the ambiguous state the round-3 fix
(E3's dispatch table) was built to eliminate for the refusal/crash split. An unspecified, untested
path in the same mechanism is the same hole reopened one level down.

**Required change:** state explicitly in §6 E3/D6 that the "any other exit code" branch calls
`append_replay_result` with `outcome="FAILED"` and a named reason distinguishing it from the three
known exceptions (e.g. a value such as `"UNCLASSIFIED_DRIVER_EXIT_<code>"`, or whatever field AUD-09's
own FAILED-row shape actually carries once step 22-pre resolves D6's flagged absence against AUD-09).
Add a RED test — e.g. `test_an_unclassified_exit_code_still_appends_a_FAILED_row_and_leaves_the_queue`
— that simulates a signal-killed subprocess (returncode `-9`/`137`) and asserts both the row and the
queue-removal effect, not just a non-zero process exit. Extend A14 (or add A18) to require this
evidence.

## Sweep
No other new defect found. The §4 priority-wording MINOR (stale "both/either increments") is fixed
correctly. C7's claim that no pre-existing failure path's exit code changes is consistent with the
three named exceptions all propagating uncaught (Python default `1`), unaffected by C7's two new
codes being reachable only through the new, previously-absent `--family-manifest` flag path.

## Per-criterion (cap)
Fidelity 20/20 · Technical correctness 20/20 · Implementation specificity 14/15 (D6's unclassified-
exit branch unspecified) · Acceptance criteria 18/20 (same branch untested — the primary MATERIAL) ·
Autonomous operation/failure handling 14/15 (same branch's "fail-closed and loud" claim unproven) ·
Portfolio alignment 10/10.
**Total: 96/100.**

## Blockers
None operator/evidence-side. D6's gap is a plan-authoring completion, resolvable without a ruling.
