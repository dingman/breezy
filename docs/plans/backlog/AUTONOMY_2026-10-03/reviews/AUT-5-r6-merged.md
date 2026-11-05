# AUT-5 r6 merged review (coordinator)

Scores: security 95 (READY), TBA 90 with one HIGH. The final score is 90, so the plan goes to r7.

Coordinator note: E-9 was adopted while r6 was being drafted, and I did not relay it to the planner. That is a coordinator miss, not a planner defect.

## HIGH
- **AD1 [TBA H1, M2, L2]: consume E-9.**
  - Wrap each `ExecStartPre` in `timeout -k 1 <n>`, or collapse the mkdirs into one bounded command.
  - Compute each unit's worst-case end as the sum of the per-command bounds plus `TimeoutStopSec`.
  - Restate every "Ends by" figure, including the bootstrap ≤16:41:xx, the pre-launch ≤16:49, the E-8 16:48:00 release, and the dwell margin. Keep the fixed points by shrinking `TimeoutStartSec` where needed.
  - Confirm that the drawdown and dead-man units each have exactly one command.
  - Add a test that sums the per-command bounds, and cite E-9.

## MEDIUM
- **AD2 [TBA M1]:** evaluate `halt_inert` before the label gate. An inert block always emits PASS/HALT_INERT plus the daily WARN, whatever the marker says.
- **AD3 [sec M1]:** add a test that no gate, health or attest path counts HALT_INERT as evidence of a working drawdown control. The L2 and drill transition rows record `drawdown_inert=true`.
- **AD4 [sec M2]:** while inert, add a code-ceiling backstop in the pins. If the computed statistic exceeds the ceiling, raise a delivered CRITICAL. This never demotes and keeps the policy unchanged; it is a signal only.

## LOW
- Map AUT-5's "≤48h00m from the C 16:50 LAUNCH" to AUT-7 K-20's "≤47h50m from C 17:00" in one line.
- Reword the "only `os.link` site" claim, and give `demand.archive` its own allowlist row.
- State the alert escalation cadence for a differing archive, and the build-side recovery expectation.
- State that AUT-6's reader de-dupes by file name between archive steps 2 and 4.
