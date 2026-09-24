# AUD-14 review — round 1

Plan: AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
sha256: c38f23a9792a525dd3e6c0655de9cc03affee5b206ab2fea6901ca61cae91835
Round: 1
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Claims verified

- **Independently reproduced** the full 7-row journal-vs-commit table:
  `journalctl --user -u breezy-trade-supervisor.service --since 2026-09-10
  --until 2026-09-21` shows exactly the same 7 Stopping→Started cycles at the
  same UTC timestamps as §2, each a clean Stopped/Started pair with no
  `Main process exited` / `Failed` line. `git log --since/--until -- src/
  deploy/` reproduces the same nearest-commit SHAs and deltas, including the
  0-second exact match for `7938032` (restart #2) and the 46-second gap for
  `cd3f8e8` (restart #1, independently confirmed via `git show -s`). The
  claim "6 of 7 are unambiguously deploy-driven, the 7th is deploy-adjacent"
  is CONFIRMED, not agent-reported.
- Commit `1859498`'s causal chain (marker-name mismatch →
  `FAIL_NODE_NOT_READY` → orphaned defunct child → `FAIL_CHILD_EXITED`) is
  read directly from the commit's own message, consistent with the plan's
  narrative and its own correction of the "since 09-15" date claim against
  the journal's actual 09-12 first-FAIL timestamp.
- No `src`-side test evidence contradicts the plan's binding constraints:
  it touches no PREREG semantics, no cap, no enablement flag; `self_check`'s
  ladder is explicitly untouched with a negative `git diff` acceptance item.

## Analysis of the "is a deploy restart now a deploy-process question" point

The plan correctly treats this as settled by its own evidence: since 0 of 7
restarts were recovery-driven, G-13's implied "hands-off failure" is
reclassified as "human-driven deploys are undocumented," and the plan's scope
(§5) explicitly and correctly refuses to automate the deploy restart itself
("a change to live-trading enablement posture... NOT a build-side call"),
while still closing the *attribution* gap with a revision field. This is the
right scope boundary — it neither oversells the fix as "hands-off achieved"
nor silently expands into automating deploys. §11 states the "hands-off"
framing honestly (loss-avoidance, not automation).

The plan also states explicitly, correctly, that a future restart can still
NOT be told apart from a "deploy" vs "recovery" restart by the revision field
alone — the field records what is running, not why the restart happened. A
reader could ask for a second field naming the trigger (manual vs. crash),
but the supervisor genuinely cannot observe *why* systemd was asked to
restart it (it only observes that it was), so inventing such a field would
require attributing a cause the process cannot know — correctly excluded.

## Defects

No MATERIAL defects found. No MINOR defects found beyond what the author's
own §13 already discloses (the `ContinuousRungHoldStrategy subscribed` first-
appearance date is not independently re-verified by this review either — it
is not load-bearing for 14a/14b's acceptance and does not block).

## Per-criterion points

- Fidelity to the audit gap and completeness: 18/20 — matches author baseline;
  the motive-verification half is fully closed and reproduces exactly.
- Technical correctness and evidence grounding: 19/20 — every timestamp and
  commit correlation in §2 independently reproduced bit-for-bit this session.
- Implementation specificity and feasibility: 13/15 — field names, reducer
  shape, and `log_decision`'s value contract are all named; store key
  namespace left as prose.
- Acceptance criteria and validation quality: 18/20 — the seven-day historical
  replay test is a strong, concrete regression guard; the negative `git diff`
  requirement on `self_check` is well-designed.
- Autonomous operation, failure handling, recovery: 13/15 — store/revision/
  sink fallbacks all specified; deliberately adds no self-restart, correctly
  reasoned (a self-restarting supervisor under an unexamined fault is a
  named anti-pattern in this repo's own history).
- Portfolio objective alignment, scope, dependencies: 9/10 — ROI framing is
  loss-avoidance using only recorded, measured numbers (3-day fee halt,
  11-hour permit lapse, 7-day readiness FAIL).

**Total: 90/100**

## Required changes for full marks

- None material. Optional: state explicitly in §12 that the revision field
  records *what* is running, never *why* the restart occurred, to preempt a
  reader expecting the field to answer the motive question by itself.

## Blockers

None. The plan itself states no operator/strategy-lead ruling is required,
and independent verification confirms no cap, enablement flag, or PREREG
semantic is touched.
