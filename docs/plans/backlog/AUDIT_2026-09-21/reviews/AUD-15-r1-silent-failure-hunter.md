# AUD-15 review (round 1)

**Plan file sha256:** 57c79d4025f47c68c9f9a3fbeefca3531c1f85eb6b9360a0c6da0029becb415d
**Round:** 1
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified

- `grep -rl OnFailure deploy/systemd/` — CONFIRMED: matches only `.sh` wrapper scripts and
  `README.md`, zero `.service` files. The structural hole is real as stated.
- `MemoryHigh=12G`/`MemoryMax=16G` on both units — CONFIRMED by reading the unit files directly.
  Notably, `breezy-offer-gate-daily.service`'s own header comment is internally
  self-contradictory: it cites pre-cap peaks of "14.7G, 17.3G, 15.3G" and then claims
  `MemoryHigh=12G` is "well above this unit's measured range" — 12G is *below* 14.7-17.3G, not
  above. This independently corroborates the plan's diagnosis ("the cap was set below this
  unit's own recorded working set") — the shipped comment's own arithmetic is wrong, which is
  stronger evidence for the plan's claim than the plan itself states.
- `offer-gate-daily-run.sh:53-59` — CONFIRMED the exit-code contract exactly as described: exit 0
  on lock contention (healthy skip, must not alert), exit 75 on lock-infrastructure failure
  (genuine defect, should alert), matching the plan's §9 failure-case requirement precisely. This
  is good pre-existing design that the plan correctly preserves rather than reinvents.
- `OnFailure=` is a systemd-native, cause-agnostic trigger (fires on any `failed` unit state
  regardless of timeout/OOM/non-zero exit) — the plan's design of one template notifier correctly
  covers "timeout, OOM-kill, and exit-code alike" without needing to special-case each; this
  directly answers the brief's challenge question.
- "What alerts when the alert unit itself fails" — directly answered in §9: the notifier carries
  no `OnFailure=` on itself, by design, to avoid an alert loop, and a test pins that. This is a
  reasoned, explicit boundary, not a silent gap.
- Retirement path explicitly names the `breezy-pm-crh-{cont,v2}-tally` orphan anti-pattern
  (G-04) and requires `systemctl --user list-timers` to show the timer fully gone, not merely
  inactive — directly answers the "dangling timer/orphan unit" challenge.

## Defects

No MATERIAL defect found against the silent-failure lens. The diagnosis is independently
corroborated (and, on the offer-gate unit, the plan's diagnosis is stronger than it claims — the
shipped comment's own logic is backwards). The alert-coverage design (cause-agnostic
`OnFailure=`, no self-alerting loop, orphan-unit prevention) is sound and specifically targets
the three failure classes (timeout/OOM/exit-code) and the two meta-failure risks (alerter fails;
retirement leaves an orphan) this review was asked to probe.

**MINOR** — 15a's dedicated tests for "exit 0 must not alert" are somewhat over-specified: a
unit exiting 0 never enters systemd's `failed` state, so `OnFailure=` structurally cannot fire
regardless of test coverage. Harmless (belt-and-suspenders), not a defect.

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 18 |
| Technical correctness and evidence grounding | 20 | 19 |
| Implementation specificity and feasibility | 15 | 13 |
| Acceptance criteria and validation quality | 20 | 18 |
| Autonomous operation, failure handling and recovery | 15 | 14 |
| Portfolio objective alignment, scope and dependencies | 10 | 9 |
| **Total** | **100** | **91** |

## Required changes to reach 100

1. In the evidence doc, cite the offer-gate unit's own self-contradictory comment ("well above"
   when 12G is in fact below 14.7-17.3G) as corroborating evidence — strengthens the record with
   near-zero cost.
2. Re-measure the 12.2G peak in a quiet window (already required by §12) before touching any
   limit — carry through as written.

## Blockers

Per-unit fix-or-retire rulings for offer-gate and for M_A/M_B (separately) are correctly named
as strategy-lead BLOCKERs the plan does not decide — genuine, not a scoring gap.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-15-r1-silent-failure-hunter.md
