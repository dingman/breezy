# AUD-14 round-5 delta review — trading-bot-architect

Plan: AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
SHA256: c7646c8da5fe70b6f5eaf4b09bdfa4735c578c2442274c5cd752abf46e5e5db3
Round: 5 (delta on Revision 5, FINAL)
Reviewer: trading-bot-architect

## Scope of this round

Coordinator-scoped delta: verify the fix for the MINOR both reviewers named in round 4 (the
`SelfCheckEscalationState` operand fed to the reducer on `CORRUPT`/`UNAVAILABLE` was
unspecified), and reconcile my round-4 deductions that named no concrete defect+required-change,
per the same rule applied to AUD-13.

## Verification performed this session

- `sha256sum` matches the coordinator-supplied hash exactly.
- Read §6's new "The state operand on a fault load, and what is written back" block (`:310-344`)
  in full, plus the three write-back tests it drives in §7 step 4 (`:474-489`).
- **Confirmed the fix is complete and correct, not merely asserted.** `_load_self_check_escalation`
  now returns the same `SelfCheckEscalationState()` default on `CORRUPT` and `UNAVAILABLE` as on
  `ABSENT` — the ambiguity I flagged in round 4 is closed by naming the shared operand rather than
  leaving it to be inferred. Beyond what I asked for, the plan also specifies **what gets written
  back**, reasoned through three sequences against an explicit no-under-alert rule:
  - FAIL→FAIL persists `1` (the reducer's output), not the pre-reducer `0` — because persisting
    `0` would make the *next* FAIL a first FAIL (WARN) where a CRITICAL is owed, which the plan
    correctly identifies and rejects by name as the exact under-alert this item exists to prevent.
  - FAIL→PASS persists `1` then `0` — the PASS legitimately resets the streak.
  - PASS→FAIL persists `0` — the one legitimate rebase, because a PASS is a directly-observed
    result that retires whatever streak the unreadable bytes may have held; a zero written on the
    strength of an unreadable key (the seven-day shape this item exists to kill) is distinguished
    from a zero written on the strength of an *observed* PASS.
  - The rejected alternative (skip the write, leave corrupt bytes) is named and correctly refuted:
    it escalates identically on the first case but never self-heals, so the corrupt WARN repeats
    daily until a human clears the key.
  Each sequence has a dedicated read-back assertion in §7 step 4
  (`test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero` for
  case 1 plus a chained second poll, a named PASS-under-corrupt case for case 2, and the closing
  clause of `test_a_corrupt_stored_value_alerts_where_an_absent_key_is_silent` for case 3), so the
  design is falsifiable, not merely narrated.
- Re-confirmed `_do_self_check`'s signature/return annotation (`:1198-1207`... — this round's edit
  states these are unchanged, consistent with what I independently verified from source in round
  4) and the existing alert block (`:1297-1303`) remain untouched by this edit, which is correct:
  the fix is additive to the load-helper's own contract, not a change to the call site.

I find no gap in the fix and no new defect it introduces. The reasoning is sound: the write-back
rule is derived from an explicit invariant (never under-alert on the next poll) rather than
asserted by convention, and both branches of that invariant (the escalate-again case and the
self-heal-after-PASS case) are tested.

## Reconciliation of round-4 deductions (coordinator-requested)

Round 4 scored 94/100, withholding points on five of six criteria. Re-applying the rule — every
withheld point needs a named defect AND a required change; a shortfall no plan change could fix
(real implementation cost, an inherent property of a not-yet-executed plan, or a reasoned,
correctly-scoped exclusion) is a note, not a deduction — against my own round-4 text:

- **Fidelity (19→20).** My round-4 reason was "G-13's 'hands-off' headline remains observable
  rather than fixed... and the self-check-never-runs case is still only halved." Both are
  **deliberate, reasoned scope exclusions the plan itself names with an owner** — automating the
  deploy restart is explicitly out of scope because it is a live-trading-enablement-adjacent
  posture change, not a build-side call (§5); the dead-man's-switch residual is named with its
  owner (`AMENDMENT B-4`) rather than silently dropped (§5, §9). No plan text within AUD-14's own
  scope could close either without scope creep the plan is right to refuse. Reconciled: criterion
  met as far as this item's stated scope applies. **Note, not a deduction:** both residuals are
  real and are carried forward to their named owners, not resolved here.
- **Technical correctness (18→20).** One point was the clarification gap now fixed above. The
  other was "the mechanism has never been executed" — real, but not fixable by any plan text; a
  plan document cannot contain an executed transcript before implementation begins. Reconciled.
- **Implementation specificity (14→15).** My round-4 reason was "the decode helper's exact
  placement... [remains] the implementer's." This is a trivial, non-load-bearing mechanical
  choice (which function goes where inside an existing module) with no design consequence — real
  implementation latitude, not a specificity gap, and no different from the placement discretion
  every other reviewed item in this backlog leaves to its implementer. Reconciled.
- **Acceptance (19→20).** My round-4 text already stated the reason directly: "Item 5 still lands
  after merge, which is inherent to the item's subject, not a specification gap" — I had already
  concluded this was not a defect and should not have deducted for it. Reconciled.
- **Autonomous operation (14→15).** Same defect as fidelity's: the never-ran case is a named,
  owned exclusion, not an unaddressed gap. Reconciled.
- **Portfolio (10/10).** Unchanged — no deduction was made here.

## Defects

None remaining, MATERIAL or MINOR. The one MINOR named jointly in round 4 is verified fixed
against the plan text, with the fix's own internal reasoning independently checked (the three
write-back sequences against the stated no-under-alert invariant) rather than accepted on the
plan's word.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Motive half (14a) and escalation half (14b) both fully closed within this item's own stated scope; the two named residuals (deploy-restart automation, dead-man's-switch) are deliberate exclusions with owners, not gaps. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation re-verified from source; the round-4 clarification gap is closed and its fix independently checked for internal consistency. |
| Implementation specificity and feasibility | 15 | 15 | Literal store key, JSON shape, enum members, reducer signature, the read-decide-write bracket ordering, and now the exact write-back value for every reachable fault/result combination. |
| Acceptance criteria and validation quality | 20 | 20 | Eleven items including the six-symbol negative `git diff`, the three-way fault distinguishability, the unchanged-signature diff, and now three explicit write-back read-back assertions. |
| Autonomous operation, failure handling and recovery | 15 | 15 | Four distinct, named, tested fault paths with exactly one permitted silent case (`ABSENT`); the over-alerting consequence of a sustained outage is bounded to daily cadence (verified in round 4) and now self-heals correctly on the next observed PASS. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Loss-avoidance framing on recorded numbers only; every exclusion names its owning work package. |
| **Total** | **100** | **100** | |

## Required changes

None.

## Blockers

None. No operator or strategy-lead ruling is required for either 14a or 14b.
