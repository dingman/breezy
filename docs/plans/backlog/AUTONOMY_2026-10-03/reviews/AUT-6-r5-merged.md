# AUT-6 r5: merged by the coordinator. silent-failure-hunter 95; trading-bot-architect 92 with 1 HIGH. Final score 92, so the plan goes to r6.

- **S1 [HIGH tba-1 + MEDIUM sfh, the F8 stall heal]: coordinator ruling (KISS).**
  - **Change:** remove every oneshot member from the SELF_HEAL allowlist. A failed or timed-out oneshot pull goes to #22, which alerts with delivery proof, and its next timer elapse retries it.
  - **What stays:** SELF_HEAL keeps only long-running `Type=simple`/`notify` services whose liveness is observable at any pass.
  - **Docs:** remove the 0.8×T stall rule and the ≥600 s floor wherever they existed only to justify oneshot heals. Update R-5.
  - **Tests:**
    - Add `test_selfheal_allowlist_has_no_oneshot_members`. It parses the unit files.
    - Add a real-slot test: for each remaining member, assert that a health pass exists at which a stall is detectable.
- **S2 [MEDIUM tba-2]:** judge the #23 canary for the 17:10:00Z slot at a pass ≥17:21Z, or require the retry record to exist. Add a test at the real 17:11 boundary.
- **S3 [MEDIUM tba-2b]:** #31 is WARN until 2026-10-16. After that it is CRITICAL.
  - **Live proof:** removing the ING-2-AMEND2 drop-in is a named prerequisite. The live proof's "#31 PASS" cannot be met until then.
  - **Upstream:** name ING-2 S3a, with its owner and date, as an upstream dependency.
- **S4 [LOW sfh]:** flag an `InvocationID` change that no selfheal record or rotate marker explains. This catches a crash hidden by an `NRestarts` reset.
- **S5 [LOW sfh]:** if the armed marker is still missing after 24 h of delivered canaries, #23 FAILs.
- **S6 [LOW tba]:** add the drill-probe exception to the §3.9 HUNG class. This becomes moot if S1 removes the drill probe from the allowlist.
- **S7 [LOW]:** re-derive the §10 self-scores honestly.
