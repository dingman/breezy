# AUD-19 round 2 review — trading-bot-architect

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 20d471ca04e3c16c1c6287e3c7f22b8ed4b8442a8a4d9b945df6431b1db4b452
Round: 2

## Round-1 MATERIAL: verified fixed
The "no code change on AUD-09's side" claim is withdrawn (§9); new **AUD-19c** wires
`scripts/analysis/replay_daily_runner.py` (AUD-09's own module) to pass `--family-manifest` and
source `engine_params_source`/`engine_required_fee_coefficient`/`params_match` from the sidecar.
Cited AUD-09 sections verified against source: `:486-490` (armed-manifest resolution, matches E1),
`:498-509` (the three fields, matches E2 exactly), `:546` (`record_blocked`, matches E3), `:698-702`
(row schema — confirmed no `exit_rule` field, matches D5), `:852,854` (B16/B18, matches E2/E4). Field
names, order and types all line up; no restatement of AUD-09's content, cited by section number only;
AUD-09's document is not diffed. FIXED.

## New defect found this round
- **MATERIAL** — AUD-09's own step-8 RED test (`:798-800`) pins `engine_params_source="DRIVER_DEFAULTS"`,
  `params_match=False` "for today's manifest" as an assertion inside `tests/unit/test_replay_daily_runner.py`
  — the exact file 19c step 22 "extends — never replaced, never weakened." But 19c's E1 makes the
  runner's driver vector **unconditionally** carry `--family-manifest <armed manifest>` — there is no
  longer a flag-absent path in the deployed runner once 19c lands, so that pinned sub-assertion
  describes a state the post-19c code can no longer produce. The plan does not state that step 22
  supersedes/edits that specific existing assertion (a planned supersession, not a weakened test) —
  it only adds new tests alongside it, leaving ambiguous whether an implementer edits, deletes, or is
  blocked by a now-permanently-failing pinned assertion. **Required change:** 19c (§6 E2 or §7 step 22)
  must explicitly name AUD-09's `:798-800` sub-assertion, state it is superseded (with the reason: E1
  makes the flag unconditional), and specify the replacement assertion — while leaving the rest of
  that RED test (target selection, crash recovery, BLOCKED handling, stall escalation) untouched.

## Sweep of other round-2 edits
- C6 pre-run clear / `argv_sha256` / atomic write (A9/A10, steps 17-19): sound, closes a real
  staleness hazard, no defect found.
- `unscoped` id tested against every live selector and family-scoped read (A11, step 20): consistent
  with D1, no defect found.
- `whole_tape_paper_replay.py` call-site test (A12, step 21) and its addition to A8's file allow-list:
  consistent, no defect found.
- C2's `:1118` branch fix (test resolved `strategy_name`, not `args.strategy`): correct bug fix,
  matches C4's `strategy_arg is None` design, no defect found.
- Sequencing (19a→19b→19c, 19c blocked on AUD-09b's runner existing): consistent, not a scope claim
  over AUD-09.

## Per-criterion points
- Fidelity to audit gap and completeness: 19/20 (now reaches the full goal state across all three consumers)
- Technical correctness and evidence grounding: 18/20 (-2: the stale-pin contradiction above was not caught this round by the plan itself)
- Implementation specificity and feasibility: 13/15 (19c necessarily can't cite exact line numbers in a not-yet-built module; otherwise fully specified)
- Acceptance criteria and validation quality: 16/20 (A13/A14 close the sidecar-consumption gap; -4 for the unresolved test-supersession gap above, which is exactly a validation-quality defect)
- Autonomous operation, failure handling and recovery: 13/15 (staleness now structurally impossible; still no exit-code vocabulary, deliberate)
- Portfolio objective alignment, scope and dependencies: 7/10 (three increments, seven files, 19c reaches into a sibling item's module — larger scope than round 1, though justified)

**Total: 86/100**

## Blockers
None requiring operator/strategy ruling. The new defect is a plan-text gap (name the superseded
assertion), resolvable without new evidence or access.
