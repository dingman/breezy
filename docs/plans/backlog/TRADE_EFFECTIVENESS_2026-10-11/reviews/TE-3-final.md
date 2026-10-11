# TE-3 convergence record — READY (2026-10-11)

**Final plan:** `TE-3_plan_r3_1.md`. This is r3 with a coordinator wording pass and no substantive change. The ruling text is Appendix A.

## Score trajectory

| Round | Domain (stats) | Python | Architecture / Gov | Codex |
|---|---|---|---|---|
| r1 | 84 RWC | 71 RWC | 82 RWC | 76 NOT-READY |
| r2 | 88 RWC | lapsed (WP-1 dropped, no code) | 84 RWC | 98 READY |
| r3 | **93 READY** | n/a | **93 READY** | r2 READY stands (r3 delta is wording + correction) |

r3.1 applies every MED/LOW finding from the r3 round:
- domain R3-1..R3-4
- governance G1..G5: Lane-E expiry scoped to δ 0.04; WA-3 P4′/W15 sizing reference; "pre-freeze"; "recorded by ruling"; WA-3 pending-issue note; the refusal-count wording; the 2027-06-01 cell.

No BLOCKER or HIGH finding is open.

## Outcome

TE-3 is planned as a **ruling, not a build**: `UNDERPOWERED_NOT_REGISTERED`, structurally infeasible on PM.us.
- The R4 ledger desk recompute needs n = 1486, or 1743 at programme FWER 0.025, against a 5-station ceiling of 490.
- The motivating anomaly is gone. Under the inclusive scoring the NO side was 1 win in 3 fills, net +0.65, P(≥1 | 0.12) = 0.32.
- WP-4 stays dormant, with its inherited requirements.

## Next actions

- **WP-2:** save the Appendix A ruling to `docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_2026-10-11.md`, after a final prediction-market-reviewer read of the exact text.
- **WP-3:** move PROGRESS to RULED, and record the lesson.

## Mid-loop correction

The band-semantics correction (`CORRECTION_2026-10-11_band_semantics.md`) was applied in r3.
