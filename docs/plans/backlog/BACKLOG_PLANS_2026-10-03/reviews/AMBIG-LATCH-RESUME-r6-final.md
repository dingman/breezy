# AMBIG-LATCH-RESUME r6: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| security-reviewer | 95 | 0 |
| trading-bot-architect | 95 | 0 |

Plan: `AMBIG-LATCH-RESUME_plan_r6.md`. Status: **READY**.

## Ruled changes, disclosed in the plan

- **Lesson L-36.** The no-id clause of its B10 item ("`clear_submit_intent` stays the only no-id path") is superseded by the automated no-id resolver.
  - The resolver is fail-closed. It reads complete data only, and it has the T41(vii) real-capture control.
  - L-36 is amended in the same merge.
  - Basis: operator policy says nothing but the two caps may go to the operator.
- **T25(iii)** is inverted into a positive resolver test.

## Binding build items

1. **Two-phase build (DH1).**
   - Phase A merges first: C0, the supervisor changes and the marker.
   - Then a supervisor restart in the 01:00–16:40Z window.
   - Then the check script. It must exit 0 before Phase B merges.
   - The node-side marker gate is the mechanical guard.
2. **Runbook text for the CRITICAL.** It names the expected halt of up to about 55 h for a lead-1 take made before 16:40Z on D−1. §7 states that the edge applies only to that case.
3. **PROGRESS follow-up.** Add a row: extend the manual sign table if `SELL_SHORT`, or any unobserved manual shape, ever appears.

## Accepted residuals

- **Lead-1 halt.** In the R-CONTRA residual case, a lead-1 take can stay halted for 49–55 h. It is fail-closed, paged CRITICAL, operator-free, and exits automatically.
- **No-id frequency.** No-id intents occur about 0.18 times a day: 1 of 24 historical intents.
- **Forward skew.** The 55 s forward skew is a symmetric choice, not a derived value.
