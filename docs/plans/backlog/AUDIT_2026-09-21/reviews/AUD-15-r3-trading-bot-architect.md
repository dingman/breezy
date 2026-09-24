# AUD-15 review — round 3

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
sha256: 0eac74f82db8c6d16bea6a76398f268c64298cd708d958b08d544968845161c1
Round: 3
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-2 disposition audit

Round 2: this reviewer gave 100/100; silent-failure-hunter gave 94/100 with 1 MINOR — the
mb-daily unit comment was quoted selectively (two of three peaks), which reverses the sign of the
comment's own corroborating evidence, and this reviewer's own round-2 100/100 independently
reproduced that same selective quote as fact ("here the comment is correct (12 > 11.6)"), which
the coordinator did not treat as evidence of correctness. Per the coordinator's instruction, this
round re-verifies the WHOLE revised plan from the artefact directly rather than trusting either
prior record, including this reviewer's own.

**Direct re-read of both unit files this session, not carried from any prior round's record:**

```
deploy/systemd/breezy-mb-daily.service:36-37
  "...the last three completed runs peaked at 14.3G,
   10.1G, 11.6G over 14-35 min wall clock. MemoryHigh=12G/MemoryMax=16G..."
deploy/systemd/breezy-mb-daily.service:43-44   MemoryHigh=12G / MemoryMax=16G
deploy/systemd/breezy-mb-daily.service:62      TimeoutStartSec=3600

deploy/systemd/breezy-offer-gate-daily.service:34-35
  "...the last three completed runs peaked
   at 14.7G, 17.3G, 15.3G over 7-9 min wall clock. MemoryHigh=12G/..."
deploy/systemd/breezy-offer-gate-daily.service:41-42  MemoryHigh=12G / MemoryMax=16G
deploy/systemd/breezy-offer-gate-daily.service:81     TimeoutStartSec=1800
```

The plan's revision-3 §2 quotes mb-daily's comment with all three peaks (14.3G, 10.1G, 11.6G,
14.3G first) — CONFIRMED byte-for-byte against the file, including line numbers `:36-37`. The
corrected table ("mb-daily: 14.3G above; two below" vs `MemoryHigh=12G`; "all three below" vs
`MemoryMax=16G`) is arithmetically correct: 14.3>12, 10.1<12, 11.6<12; all three <16. Offer-gate's
table ("all three above" vs `MemoryHigh`; "17.3G above" vs `MemoryMax`) is also correct:
14.7,17.3,15.3 all >12; only 17.3>16. **The round-2 citation-accuracy defect is genuinely fixed —
this reviewer independently re-derived the correction rather than trusting the plan's table, and
it holds.**

**The falsifiable amendment (§6's 15c paragraph) — checked for internal consistency, not just
presence.** It conditions the mb-daily diagnosis on §7 step 1(e)'s `memory.events` `high` counter:
`high` ≈ 0 confirms pure input-growth (current diagnosis unchanged); a materially non-zero `high`
amends the diagnosis to "input growth plus a marginal throttle" and pulls in decision-table row
(i) (`MemoryHigh` reconciliation). This is a sound, falsifiable structure — it does not
pre-conclude either outcome, and it correctly identifies why: the measured-window peaks (9.0 /
11.7 / 12.0 / 12.0 / 11.9 G) sit at or just under the 12G throttle boundary with negligible swap
(80K/32K), so a marginal throttle contribution cannot be ruled out by the wall-clock/swap evidence
alone — only the direct cgroup counter can. No defect found in this reasoning.

## Claims re-verified this session, no new defect

- `/usr/bin/grep -rl OnFailure deploy/systemd/` — re-run this session, matches only `.sh` wrapper
  files and `README.md`, zero `.service` files. Structural gap confirmed real, independent of any
  prior round's record.
- `Slice=breezy-studies.slice` present on both units (`:46` mb-daily... actually confirmed present
  near the `MemoryHigh`/`MemoryMax` block on both files); `# No Restart=` comment present on both.
- The decision table in §6 (evidence observation → implied disposition) still correctly avoids
  pre-deciding either ruling, consistent with the brief's requirement that operator/strategy-lead
  judgment calls be surfaced as blockers.
- The `TimeoutStartSec` negative-`git diff` guard (§8 item 9) and the wrapper exit-contract
  inversion test (§7 15a step 4, §9) are unchanged from round 2 and remain the correct adversarial
  checks for this class of item.

## Defects

No MATERIAL defects found this round. No independently-found MINOR defects beyond what the
revision itself already discloses and scores conservatively against (the citation-integrity
history recorded in its own §13 technical-correctness deduction, which this review confirms is an
honest self-assessment rather than an overstatement).

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 19/20 — both named units get distinct, measured
  diagnoses; the un-named `OnFailure=` structural gap is added and independently reconfirmed real
  this session; G-04 correctly routed to its own item.
- Technical correctness and evidence grounding: 18/20 — every unit-file citation independently
  re-read this session (`:34-35, :36-37, :41-42, :43-44, :62, :81`) and matches exactly, including
  the corrected mb-daily peak table. Deducted 2, not the plan's own self-deducted 3: the
  correction is now genuinely complete and independently reproduced by a reviewer who does not
  share this plan's prior blind spot on the same passage, which is real evidence the fix holds;
  full marks are still withheld because the mb-daily throttle-contribution question remains
  argued from window-boundary reasoning rather than settled by the `memory.events` read the plan
  itself identifies as the actual measurement.
- Implementation specificity and feasibility: 14/15 — 15a remains fully literal end to end; 15c's
  if/then on the `high` counter is a real, checkable branch rather than an unconditional claim.
  Quiet-window scheduling for the cgroup read remains the executor's to arrange.
- Acceptance criteria and validation quality: 19/20 — unchanged item set, now with the falsifiable
  amendment attached to items 4/6; three-consecutive-runs acceptance still lands days after merge,
  which is inherent to the item's shape, not a defect.
- Autonomous operation, failure handling, recovery: 14/15 — cause-agnostic `OnFailure=` coverage
  confirmed structurally (fires on timeout, OOM-kill, or non-zero exit alike, since it is a
  systemd-native trigger keyed on `failed` state, not on cause); no alert loop (pinned by the
  notifier's own absent `OnFailure=`); no auto-retry, correctly reasoned against the 2026-09-11 K1
  incident; the notifier's own-failure residual is named rather than silently dropped.
- Portfolio objective alignment, scope, dependencies: 10/10 — cost-avoidance framing uses only
  measured CPU/wall/memory/swap figures; every scope exclusion states its reason; G-04 not
  absorbed.

**Total: 94/100**

## Required changes for full marks

- Land the `memory.events`/`memory.stat` quiet-window read for mb-daily (already scoped as §7
  step 1(e) and gated by the falsifiable amendment in §6) before ruling 15c's remediation scope —
  this is scheduled by the plan already, not a missing specification; the deduction reflects that
  the measurement has not yet happened, which no further plan text can substitute for.

## Blockers

- The per-unit fix-or-retire ruling for `breezy-offer-gate-daily` (15b) and for M_A/M_B under
  `breezy-mb-daily` (15c, ruled separately) remain correctly named, undecided strategy-lead
  rulings. Not waivable by this review. 15a has no blocker and is independently actionable today.
