# AMBIG-LATCH-RESUME r2: merged review (coordinator)

TBA scored 91 and security scored 91, each with one HIGH. The final score is 91, so the plan goes to r3.

**Verdict on the inverted pin:** both reviewers judge it LEGITIMATE. It is a ruled scope change, not a weakened safety test.

## HIGH items

**F1 [TBA HIGH]: no deadlock after STOP.** The supervisor launch path and the boot-retry path both refuse when the intent is OPEN (`trade_supervisor.py:1233-1255`, `:1594`). This is lesson L-39. Coordinator ruling:
- (a) If P1 finds an OPEN intent, never stop the node. Defer the relaunch.
- (b) Hold the intent lock from P1 through SIGTERM, if that is feasible without touching the node's own lock semantics. Otherwise show the remaining gap is bounded.
- (c) If an OPEN intent is still found after the stop (the race case), specify the exact autonomous clearing path with code evidence. The fallback is the existing hand-relaunch recipe, whose boot reconciles and lets the resolver retire. Verify the "boot with an unresolved intent refuses once" behaviour and handle it. Raise a named CRITICAL.
- Add a clearing-path row.
- Drop the claim that the supervisor "handles it at 16:50Z".

**F2 [sec HIGH]: disclose the second test edit.** `tests/unit/test_current_rung_hold_ambiguous_resolver.py:1308` will go RED.
- Change its assertion to `refusals_before` minus AMBIGUOUS. That keeps "no NEW refusal" and is stricter.
- Show the grep over every `trading_refusals` assertion that follows an accept-fill rig.
- Correct the hunk count and the PR claims.

## MEDIUM items

**F3 [sec]: AMBIGUOUS is never throttled (coordinator ruling).** Exempt `AMBIGUOUS_REASON` from the throttle. Every new AMBIGUOUS gets a CRITICAL. The measured volume is about 0.9/day. Other reasons stay throttled.

**F4 [TBA]: pin provenance.**
- Cite `87b3725b` verbatim.
- Require written security sign-off that the fill-confirmation predicate is as strong as the zero-fill one.

**F5 [TBA]: the P2 log-tail check.** Either make P1 authoritative and give P2 an exact regex, or drop P2.

**F6 [TBA]: second AMBIGUOUS before resume.** If a second AMBIGUOUS arrives inside the ≤60 s window before resume, the resume must be refused. Document this and add a test. Per F3, that AMBIGUOUS still alerts.

## LOW items
- State the period mismatch in the alert-volume inputs.
- Label T14(ii) as an isolation test.
- State that the cross-session early return is intended.
- Make the T4(iii) DEGRADING spy concrete.
