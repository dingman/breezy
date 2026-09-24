# AUD-18 — Round 3 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 63388d3de452d87e24f776f52ae30d6f4a98e9d50928940f08d5f63e45445801
Round: 3

## Round-2 minors re-verified against source — both GENUINELY FIXED

- §13's ENDORSED/PROPOSED inconsistency: fixed, round-2 log row now says "peer-ENDORSED (Revision 3, no required change)" and matches §12.
- §6.4b `OnCalendar`: now `*-*-* 01:20:00 UTC`. Enumerated the 11 timers myself against `deploy/systemd/*.timer` — matches the plan's list exactly (k1-daily 01:35, offer-gate 02:05, quote-tape-rotate 09:00, mb-daily 13:30, score-live-trials 14:15, live-tally 14:30, position-monitor-report 15:00, exit-window-study 15:20, family-tally@ 17:20, quote-tape-ingest 00/06/12/18:15, ingest-frequent `*:0/15`). Protected no-start window `[16:35Z,01:15Z)` confirmed verbatim (`README.md:938-939`). AUD-09's replay slot confirmed `15:50:00 UTC` (`AUD-09...md:664-673`, DECIDED N4). 01:20Z is free, outside the window, 15 min clear of 01:35, and — since 15:50Z to 01:20Z next day is the very next tick after the protected window closes with nothing else scheduled between — `After=breezy-replay-daily.service` correctly orders it behind the SAME day's replay run (not a stale one), and the plan honestly states `After=` is belt-and-braces on top of calendar spacing, not the real ordering mechanism. Accurate.

## New material finding (this round, this reviewer's lens)

**MATERIAL — no power analysis; the tightened alpha budget's feasibility is unexamined.** The Bonferroni fix (§6.1) correctly controls FWER but `per_variant_alpha = PROGRAMME_ALPHA(0.05) / MAX_HYPOTHESES(8) / k_variants` — e.g. ≈0.00052 one-sided for a WP7-shaped `k_variants=12` hypothesis — is never checked against achievable power at PM.us station-day accrual rates. This repo's own history (`RULING §7`'s three retractions, the WP-7 hunt's underpowered-negative correction, all at the LOOSER `alpha=0.05`) is evidence that detecting a real edge at PM.us sample sizes is already hard at 0.05; nothing in the plan shows the ~2-4x larger required-n at `alpha≈0.0005` is attainable within `min_station_days`/the PARKED horizon, and `MAX_HYPOTHESES=8` itself is asserted with no derivation. If power is hopeless, the programme's own honest-refusal ethos (stated repeatedly, e.g. §6.3's closing paragraph) requires saying so — it does not. Required change: (a) justify `MAX_HYPOTHESES` or replace it with a value derived from §6.3's actual class count; (b) add a power/minimum-detectable-effect check to §7 step 8's peer ruling (alongside n/stopping-rule/alpha-share/KILL-criterion) so a hypothesis is not registered into an allocation it cannot plausibly clear; (c) state explicitly in §6.6/§11 that, given this correction's cost, programme KILL is the more likely honest outcome, not merely a possible one.

No other new defects found; D12's arithmetic tests are sound and the FWER fix itself is correctly verified against `gs_boundary_artefact.py:78,82,269-272` and `PREREG_WP7_MULTIPLICITY_RULE §1.ii`.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 17/20 — the loop still doesn't honestly triage the new alpha budget's feasibility, which is exactly the "honest refusal" the audit gap requires.
- Technical correctness and evidence grounding: 16/20 — FWER-control fix verified correct, but a level-only correction with unexamined power is an incomplete statistical design for a program whose deliverable is a CI that excludes zero.
- Implementation specificity and feasibility: 14/15 — `MAX_HYPOTHESES=8` is an unjustified magic constant.
- Acceptance criteria and validation quality: 17/20 — D12 tests allocation arithmetic well; no criterion requires a power check before intake.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected; timer/lock design re-verified accurate.
- Portfolio alignment, scope and dependencies: 10/10 — unaffected; clean.

**Total: 89/100.**

## Blockers

None external. The power-analysis gap is a plan defect to fix in-place (add a check to the existing §7 step 8 peer-ruling step), not an operator/strategy ruling or unavailable evidence.
