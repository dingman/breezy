# AUD-02 round-4 review — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 8790e1921b8c649892fb0e4fc809ed98ecd36c84b9f904f88698c761c90469cd
Round: 4 · Reviewer: prediction-market-reviewer (blind, independent)

## Claims verified against source (codegraph, not trusted from ruling/plan text)
- FAMILY_HALT_KEY / TrialDayLatch.is_family_halted / _HALT_CLEARED_MARKER
  (trial_day_latch.py:291,301,1002-1015) — CONFIRMED, fail-closed as claimed.
- family_halt_submit_veto wired via composition.py:195-228 → app/trade.py:260
  — CONFIRMED, synchronous, pre-permit-spend.
- continuous_family_halt_key/CONTINUOUS_FAMILY_HALT_KEY byte-identical pin
  (trade_supervisor_core.py:139,158-174) — CONFIRMED.
- Only writers today: record_duplicate_fill (:861-915), record_ambiguous_exit
  (:968-1000); only CLI is clear_family_halt_cli.py (no set sibling) —
  CONFIRMED by codegraph blast-radius (no set_family_halt_cli exists).
- Halt persists across relaunch/respawn: TrialDayLatch reopens the SAME
  durable SqliteStateStore fresh on every boot (app/trade.py, midday
  relaunch, supervisor respawn all construct a new exec client per process)
  — CONFIRMED.

## MATERIAL defects (not disclosed or addressed in the plan)
1. **The same halt also vetoes the exit seam, silently.**
   `exit_wiring.submit_exit` (exit_wiring.py:246,270-275) checks
   `strategy._latch.is_family_halted()` FIRST and refuses to submit any
   closing order once halted — "a family halted for ANY reason ... never
   submits another order of either kind" (composition.py docstring,
   confirmed). AUD-02b's §6.5/§9 describe the effect as "refuse every
   submit" but never name that this also disables the operator-mandated
   risk-reducing exit path (MEMORY: "Operator ruling: sell identified
   losers 2026-09-16," exit seam merged c96c7f4). If `pm_us_crh_v4` holds
   any open position at halt time, or the exit seam is later armed, setting
   AUD-02b's halt leaves that position with NO automated exit — a
   trading-safety consequence the plan should verify (open-position count
   at halt time) and explicitly accept or reject, not leave undiscovered.
   Required change: add an explicit check/acceptance criterion for open
   positions at halt time, and state whether blocking their exit is
   accepted risk.
2. **Self-check reads the same key and FAILs/alerts on halt — undisclosed.**
   `continuous_family_check` (trade_supervisor_core.py:359-375) computes
   `family_not_halted = not family_halted`; `_do_self_check`
   (trade_supervisor.py:1198-1304) alerts WARN
   `TRADE_SUPERVISOR_SELF_CHECK_FAIL` whenever the result is not a PASS.
   Existing tests (`test_family_halted_fails_named`,
   `test_family_halted_fails_that_check_only`) confirm a halted family
   already fails this check today for the automatic writers. AUD-02b's set
   CLI writes the SAME key/shape, so setting the halt will make the node's
   own self-check FAIL and alert WARN repeatedly (each self-check tick)
   for as long as the halt stands — by design, since clearing is
   deliberate. The plan's §7 step (7) correctly names the supervisor
   self-check as a reader of the key, but the plan never states or tests
   the CONSEQUENCE: an ongoing FAIL/alert stream that could be mistaken for
   a live incident, or (if ever suppressed to reduce noise) could mask a
   genuine self-check failure. Required change: name this explicitly in
   §9 (autonomous operation) and either add it as an expected/asserted
   behaviour in the RED test set, or state it is accepted alert noise.

## Rubric (20/20/15/20/15/10 = 100)
- Fidelity to audit gap & completeness: 17/20 — closes A1 decisional gap and
  scopes AUD-02b correctly to G-02/ruling, but does not trace the halt's
  effect on the related exit-seam control.
- Technical correctness & evidence grounding: 15/20 — citations accurate,
  but the stated consequence of the halt ("refuse every submit," "keep
  running healthy") is materially incomplete per defects 1-2 above.
- Implementation specificity & feasibility: 14/15 — CLI design concretely
  mirrors the existing clear CLI with file:line precision.
- Acceptance criteria & validation quality: 15/20 — 7 RED tests are
  objective, but omit an open-position check and the self-check FAIL/alert
  interaction named above.
- Autonomous operation, failure handling & recovery: 10/15 — the two
  undisclosed interactions (defects 1-2) are exactly the class of failure
  this criterion covers.
- Portfolio alignment, scope, dependencies: 9/10 — AUD-01a/AUD-03/AUD-18
  dependencies correctly stated and non-circular; minor: doesn't cross-
  reference the sell-identified-losers exit-seam item it interacts with.

**Total: 80/100.**

No HUNT-1/live-enablement/operator-cap violations found. Rollback
(breezy-clear-family-halt) is real and unchanged. Priors' rounds' fixes
(A1-ruling citation, AUD-03 ownership, AUD-18 linkage) verified present and
correctly reasoned this round.

## Blockers
None operator/evidence-unavailable; both required changes above are
plan-text/design fixes the implementer can make without new rulings.
