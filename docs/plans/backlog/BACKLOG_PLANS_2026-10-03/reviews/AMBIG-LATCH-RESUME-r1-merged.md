# AMBIG-LATCH-RESUME r1: merged review (coordinator)

Scores: trading-bot-architect 93 (1 HIGH), security-reviewer 92. Final score 92, so the plan goes to r2.

## Items

- **A1 [TBA HIGH]: hard precondition on relaunch.** Before relaunch, the activation must run the exact open-intent probe command against the live store. If an intent is OPEN, the activation defers to the next launch. Write out the deferral path step by step. Never relaunch while an intent is OPEN, because a boot with an unresolved intent refuses once.
- **A2 [both reviewers]: alert throttle now (coordinator ruling).** Build `renotify_after_ns` in this change; do not defer it. The re-armed alert re-notifies at most once per configured interval per episode. Name the constant and test both throttle and re-arm.
  - Also measure the takes per day and the IOC-miss rate from the live exec store, read-only, and record the expected alert volume.
- **A3 [TBA]: accept-fill path in scope (coordinator ruling).** `_resolve_accept_fill` must clear the AMBIGUOUS refusal the same way `_resolve_terminal_zero` does. That way the client resumes after **any** retired AMBIGUOUS, which is the goal state. Add RED→GREEN tests. The NO-SEND resolver callee allowlist must stay unwidened. If clearing on accept-fill needs a widening, stop and say so.
- **A4 [sec]: state the scope in §2.3.** The FSM/health RUNNING state never gates sending and is not proof the node can trade. Sending stays gated by refusals, the permit, the latch and the family halt. Add a test that resume leaves order admission unchanged while the permit is invalid or a halt is set.
- **A5 [both reviewers]: race tests.** Cover a refusal during RESUMING and a refusal arriving after resume. Both must re-degrade, and the alert must re-fire subject to the throttle.

## LOW
- Split T8 into a pure guard and a RED test.
- Cite the re-poll interval constant for the ≤60 s latency.
- Record the additions-only diff for the `_EXEC_CLIENT_SHA256` re-pin and the new sha in the PR.
