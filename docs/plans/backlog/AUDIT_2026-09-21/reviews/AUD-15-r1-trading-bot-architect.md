# AUD-15 review — round 1

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
sha256: 57c79d4025f47c68c9f9a3fbeefca3531c1f85eb6b9360a0c6da0029becb415d
Round: 1
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Claims verified

- "`OnFailure=` appears in no `.service` unit" — CONFIRMED:
  `/usr/bin/grep -rl OnFailure deploy/systemd/` matches only `.sh` wrapper
  scripts and `README.md`; zero `.service` files match. The structural gap
  the plan builds 15a around is real.
- Unit files for both named studies exist as described
  (`breezy-mb-daily.service`/`.timer`, `breezy-offer-gate-daily.service`/
  `.timer`), each with a matching `-run.sh` wrapper — consistent with the
  plan's per-unit remediation design (15b/15c).
- The plan's scope correctly refuses to raise `MemoryMax` or touch
  `Slice=breezy-studies.slice`, citing the 2026-09-11 K1 host-contention
  incident as the reason the caps exist — this is a real, binding constraint
  this plan does not invent.
- 15a's mechanism reuse (existing `breezy.runtime.health` sink,
  `AlertPayload`/`emit_alert`/`resolve_alert_sink`, already wired by
  `f97c26f`) matches AUD-14's independently-verified claim that the alert
  delivery path was fixed 09-20 — consistent cross-plan.

## Analysis

The plan correctly separates two different failure mechanisms for the two
units (memory-throttle-into-swap for offer-gate vs. workload growth against a
fixed timeout for mb-daily) rather than proposing one shared fix, and commits
to evidence-then-ruling rather than pre-deciding fix-or-retire — appropriate
given both units measure families whose live status is contested per
PROGRESS.md's standing verdicts. The explicit refusal to pre-decide (§6:
"to be chosen on the evidence 15b collects, not pre-decided here") is the
correct posture for an item that must not invent a financial or research
verdict. The negative acceptance criteria (no `MemoryMax` increase, `git diff`
proof) make "quietly loosen the cap to make the timeout go away" mechanically
detectable, which is the right guard for this class of item.

The wrapper-script exit-code handling (flock exit 0, lock-infra exit 75 must
not fire `OnFailure=`) is a real edge case the plan explicitly tests for,
correctly distinguishing "healthy skip" from "unit failure" — this is the
kind of failure-injection discipline the item needs and the plan states it
as a named test rather than an assumption.

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond what
the author's own §13 already discloses (the memory-throttle mechanism is
inferred from `MemoryHigh` semantics + swap peaks rather than a direct
`memory.events` cgroup read, and the plan itself requires a quiet-window
re-measurement before any limit change — an appropriately conservative
gate on its own claim).

## Per-criterion points

- Fidelity to the audit gap and completeness: 18/20 — matches author baseline;
  both named units covered, the un-named structural `OnFailure=` gap
  correctly added and independently confirmed real.
- Technical correctness and evidence grounding: 19/20 — the one claim spot-
  checked (grep for `OnFailure`) reproduces exactly; the CPU/wall/memory
  figures were not independently re-run this session (would require
  triggering or waiting on scheduled units, out of this review's read-only
  bound) but the plan's own quiet-window re-measure requirement already
  covers that residual risk.
- Implementation specificity and feasibility: 12/15 — 15a is fully specified;
  15b/15c are deliberately evidence-then-ruling, matching the brief's
  instruction, at the cost of single-pass executability.
- Acceptance criteria and validation quality: 18/20 — `systemd-analyze verify`
  empty output, three-consecutive-run acceptance, delivered (not logged)
  alert artefact, and the `MemoryMax`/slice negative-diff requirement are all
  concrete and falsifiable.
- Autonomous operation, failure handling, recovery: 14/15 — notifier
  self-failure, healthy-skip (flock/lock-infra), and sink-unreachable are all
  named test cases; deliberately refuses an alerting loop.
- Portfolio objective alignment, scope, dependencies: 9/10 — cost-avoidance
  framing uses only measured numbers; G-04 (family-tally unit) correctly
  routed elsewhere rather than absorbed.

**Total: 90/100**

## Required changes for full marks

- None material. At execution time, re-confirm the memory-throttle diagnosis
  with a direct cgroup `memory.events`/`memory.stat` read in a quiet window
  before touching `MemoryHigh`, as the plan itself already requires — this is
  a note for the implementing session, not a defect in the plan.

## Blockers

- Fix-or-retire ruling for `breezy-offer-gate-daily` (15b) and for M_A/M_B
  under `breezy-mb-daily` (15c) — both are named strategy-lead rulings the
  plan correctly refuses to pre-empt, and 15b/15c cannot complete without
  them. 15a has no blocker and is independently actionable.
