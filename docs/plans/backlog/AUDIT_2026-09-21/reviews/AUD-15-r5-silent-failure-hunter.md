# AUD-15 — Round 5 review (silent-failure-hunter, FINAL, reconciled)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** 7b7efaf45dc297ba528b188f730a458a3eff994bdec4280aa20e904ab6cb9d76 (verified via `sha256sum`)
**Round:** 5 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification of the reported change against source

Re-checked the citations underpinning the new orchestration:

| Claim | Status |
|---|---|
| `TimeoutStartSec=1800` at `breezy-offer-gate-daily.service:81` | CONFIRMED, exact line |
| `TimeoutStartSec=3600` at `breezy-mb-daily.service:62` | CONFIRMED, exact line |
| `Slice=breezy-studies.slice` at `:46` (offer-gate) / `:48` (mb-daily) | CONFIRMED, exact lines |
| No-start rule `[16:35Z, 01:15Z)` at `deploy/systemd/README.md:939` | CONFIRMED, exact line and text |

§7 15b/15c step 1(e) now specifies, in full: the live read is a **one-off diagnostic performed by the implementer at implementation time**, never a permanent sampler/unit/`ExecStartPost=` (rejected against YAGNI, with the reason stated — a standing sampler would itself contend inside `breezy-studies.slice` during the runs it measures); the implementer **starts the unit directly** (`systemctl --user start <unit>.service`) rather than waiting on the timer, subject to binding host constraints (one heavy study at a time; never inside `[16:35Z, 01:15Z)`; never while the shared studies flock is held; therefore two units are measured in **two sequential, non-concurrent windows**); a **bounded polling loop** samples every **30 s** up to a **75-minute** hard cap, appending timestamped `memory.events`/`memory.stat` blocks to a scratch file; an empty `ControlGroup=` or a failing `cat` is recorded as `READ_FAILED` and **ends the loop**, never written as a zero; the reading used is the **last successful pre-teardown sample**; and the compared quantity is explicitly the **final cumulative `high` of the run plus that run's duration**, both units sampled at the **same 30 s cadence**, addressing `high`'s cumulative (non-gauge) semantics directly. §8 items 4 and 6 require the cadence, sample series/last-good-sample, run durations, and any `READ_FAILED` markers as acceptance artefacts, and explicitly reject a single undated snapshot or a control read taken by a different method/phase. §12's assumption line no longer leaves the quiet window to the executor.

This closes all three parts of the round-4 MATERIAL defect (orchestration/actor named; teardown-race handling specified in the safe direction; comparability of the two counters fixed by cadence and run-duration reporting) precisely as required, with no gap found on renewed reading. I specifically checked for a residual timing risk — could the manual-trigger loop's 30 s cadence itself drift or miss the true peak — and found the units' own `TimeoutStartSec` (1800 s / 3600 s) bounds each run well inside the 75-minute loop cap, so the loop is guaranteed to observe the unit's actual terminal state (either `Finished` or `failed`-by-timeout) before the cap is reached; no new defect found.

## Reconciliation of previously-withheld points (round 4: 88/100)

| Criterion | R4 | Reason given | Disposition |
|---|---|---|---|
| Fidelity | 19/20 | (no specific defect named beyond a general description) | **(b) AWARDED — 20/20.** No defect is named for this criterion in any round; both units get distinct, measured diagnoses, the un-named `OnFailure=` structural gap is added, G-04 is correctly routed to its own item. |
| Technical correctness | 17/20 | "the plan once shipped a truncated quote that reversed its own evidence's sign" (historical, already fixed in revision 3); "the mb-daily throttle contribution is still bounded by argument until the live counter is actually read" | **(b) AWARDED — 20/20.** The truncated-quote defect is a closed historical fact, not present in the current text (re-verified: both units' full three-peak comments are quoted, §7 15b/15c step 2). "Not yet read" is inherent to a plan review — no document can contain a live cgroup counter reading of code that has not been executed; this is the same class of non-defect already established for AUD-13's "tests not yet executed." |
| Implementation specificity | 13/15 | "the specificity of this exact step was scored 14 while a MATERIAL gap sat inside it... evidence about this plan's self-assessment" (meta/historical); "the loop itself is scaffolding the implementer still has to write" | **(b) AWARDED — 15/15.** The first reason is about the plan's own scoring history, not the current text. The second: the loop is specified in full — actor, trigger command, cadence, cap, sample format, teardown handling, comparison rule — to the same level of prose-plus-exact-API-citation rigor AUD-13's fixture specs were awarded full marks for; requiring literal shell script in a planning document is not a specificity bar this backlog applies elsewhere. |
| Acceptance | 18/20 | "three-consecutive-runs acceptance still lands days after merge, and every 15b/15c acceptance item remains downstream of two strategy-lead rulings" | **(b) AWARDED — 20/20.** Multi-day proof-of-fix cannot exist before the days elapse — structural, same class as AUD-13's post-merge live proof. Being downstream of the R-1/R-2-equivalent strategy-lead rulings here (the fix-or-retire rulings) is correctly recorded as a BLOCKER in §12, not a plan-text defect — the acceptance items themselves are fully specified conditional on the ruling. |
| Autonomous operation | 14/15 | "Unchanged, and not implicated by this round's defect" | **(b) AWARDED — 15/15.** No currently-active defect named; the notifier's own unpageable-failure residual is explicitly named with its reasoning (an alert-loop is worse than a missed alert) in §9, which is a correct, deliberate design stance, not a gap. |
| Portfolio | 10/10 | (full) | Unchanged — 10/10. |

## Per-criterion points (final)

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 15 |
| Acceptance criteria and validation quality | 20 | 20 |
| Autonomous operation, failure handling, recovery | 15 | 15 |
| Portfolio objective alignment, scope, dependencies | 10 | 10 |
| **Total** | **100** | **100** |

## Required changes

None. All three parts of the round-4 MATERIAL defect (orchestration actor, teardown-race handling, cross-unit comparability) are closed and verified against source this session.

## Blockers

**Unchanged, carried forward, not affected by this review's score:** the per-unit fix-or-retire rulings for `breezy-offer-gate-daily` and for M_A/M_B (ruled separately) remain strategy-lead BLOCKERs on 15b/15c — they gate the *remediation*, not the evidence-gathering method this round examined, and are not waivable by review. 15a (the `OnFailure=` alert path) carries no blocker.
