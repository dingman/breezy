# AUD-15 round-5 delta review — trading-bot-architect

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
SHA256: 7b7efaf45dc297ba528b188f730a458a3eff994bdec4280aa20e904ab6cb9d76
Round: 5 (delta on Revision 5, FINAL)
Reviewer: trading-bot-architect

## Scope of this round

Coordinator-scoped delta: verify the fix for silent-failure-hunter's round-4 MATERIAL defect
(§7 15b/15c step 1(e) specified *what* to read and *when* it was valid but never *who* performs
the live, hour-long, unattended `memory.events` read, how teardown races are handled, or whether
the control and diagnostic reads are timing-comparable), and reconcile my own round-4 deductions
that named no concrete defect+required-change.

## Verification performed this session

- `sha256sum` matches the coordinator-supplied hash exactly.
- Read the new §7 15b/15c step 1(e) orchestration block (`:349-386`) in full and checked each of
  the hunter's three sub-points against it:
  1. **Who/how.** The plan now names the actor explicitly: "the implementing session,
     interactively, one unit at a time," starting the unit itself
     (`systemctl --user start <unit>.service`) rather than waiting for the timer, with a stated
     rationale for why this is a one-off diagnostic rather than a new permanent sampler (YAGNI —
     a standing instrumentation step for a question asked once would itself add a second process
     inside `breezy-studies.slice` during the runs it measures). Host constraints (16:35Z
     protected window, shared studies flock, one heavy study at a time ⇒ two sequential windows,
     never concurrent) are carried into the step as binding, and it is explicitly flagged as an
     execution-time action the planning text does not itself perform.
  2. **Teardown race.** A bounded 30 s polling loop, capped at 75 minutes, appends timestamped
     `memory.events`/`memory.stat` blocks to a scratch file. An empty `ControlGroup=` or a failing
     `cat` is recorded as `READ_FAILED` with its timestamp and **ends the loop** — never written
     as `high 0` — and the reading used is the **last successful pre-teardown sample**. A loop
     that produces no successful sample is defined as "measured nothing" and is re-run, never
     reported as zero. This directly answers the hunter's "is a `cat` failure a dropped sample or
     a zero" question in the direction the defect required.
  3. **Comparable timing.** The compared quantity is fixed as "the final cumulative `high` of the
     run (the last good sample) plus that run's duration and the sample's offset from start,"
     with both units sampled at the identical 30 s cadence and both carried to their own run's
     end — closing the cumulative-counter/unequal-run-length problem the hunter raised (offer-gate
     30 min vs. mb-daily 60+ min) by making the comparison "final value at end of run," not an
     arbitrarily-timed snapshot.
- Cross-checked the specific figures the fix cites against the artefact: `TimeoutStartSec=1800`
  confirmed at `breezy-offer-gate-daily.service:81`; `TimeoutStartSec=3600` confirmed at
  `breezy-mb-daily.service:62`; the `[16:35Z, 01:15Z)` no-start rule confirmed at
  `deploy/systemd/README.md:939`. All three match the plan's citations exactly.
- Read §6's positive-control paragraph as amended (`:289-294`) and §8 item 4 as amended (`:420-425`)
  — both now require the cadence, the timestamped sample series (or last good sample with
  timestamp/offset), each run's duration, and any `READ_FAILED` markers as acceptance, and item 4
  explicitly states that a single undated snapshot or a control read at a different phase of its
  run does not satisfy the item.

I find the fix technically complete against all three parts of the hunter's defect and internally
consistent with the rest of the plan (the `ControlGroup=`-empties-on-exit and
`MemoryPeak`/`MemorySwapPeak`-survive-exit split I verified directly against this host in round 4
is unchanged and still correct). No new defect surfaces from this orchestration spec — in
particular, the explicit rejection of a standing sampler is reasoned (YAGNI, host contention with
the very measurement it would take) rather than merely asserted, and the "re-run, never reported
as zero" rule closes the one path by which a false negative could still slip through.

## Reconciliation of round-4 deductions (coordinator-requested)

Round 4 scored 94/100. Re-checking each deduction against the rule — every withheld point needs a
named defect AND a required change; real implementation cost, an inherent not-yet-executed
property, or a correctly-scoped exclusion is a note, not a deduction:

- **Fidelity (19→20).** My round-4 cell named no concrete defect for the withheld point — it
  listed only positives. Reconciled; no note required beyond the standing, correctly-handled fact
  that the fix-or-retire questions are routed to strategy-lead BLOCKERs rather than decided here,
  which is the brief's own required behaviour, not a gap.
- **Technical correctness (18→20).** My round-4 reason cited "the truncated-quote citation defect
  from round 2 is fixed but is on record as having happened" (a historical fact, not a live
  defect requiring a current fix) and "the mb-daily throttle contribution is still bounded by
  argument rather than an executed measurement" — this is exactly the now-fixed MATERIAL defect
  (the live-read orchestration specifying how that measurement is actually taken); with the fix
  verified, this deduction no longer applies, and the historical-record point named no required
  change. Reconciled.
- **Implementation specificity (14→15).** My round-4 reason was "quiet-window scheduling for the
  live read remains unspecified" — this **was** the hunter's material defect and is now closed by
  the orchestration block verified above. Reconciled.
- **Acceptance (19→20).** My round-4 cell already stated the reason directly: "Three-consecutive-
  runs acceptance necessarily lands after merge, which is inherent to the remediation, not a
  specification gap" — already self-identified as not a defect. Reconciled.
- **Autonomous operation (14→15).** My round-4 cell listed only positives (cause-agnostic
  coverage, no alert loop, no auto-retry, wrapper-masking pinned) with no defect named for the
  withheld point. Reconciled.
- **Portfolio (10/10).** Unchanged.

## Defects

None remaining, MATERIAL or MINOR. The round-4 MATERIAL defect (live-read orchestration for an
unattended run) is verified closed on all three named sub-points, with figures cross-checked
against the unit files and the README this session.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Both units get distinct, measured diagnoses; the un-named `OnFailure=` structural gap is added; G-04 correctly routed to its own item; the fix-or-retire rulings are correctly surfaced as BLOCKERs rather than decided. |
| Technical correctness and evidence grounding | 20 | 20 | The plan's central arbiter claim (`ControlGroup=` empties post-exit, `MemoryPeak`/`MemorySwapPeak` persist) was verified live on this host in round 4 and is unchanged; the live-read orchestration that turns the throttle diagnosis from argument into measurement is now fully specified and consistent with it. |
| Implementation specificity and feasibility | 15 | 15 | The arbiter read is now literal end to end: actor, trigger, cadence, hard cap, scratch-file format, teardown-race handling, last-good-sample rule, and the exact compared quantity. |
| Acceptance criteria and validation quality | 20 | 20 | Nine items; item 4 now rejects an undated or non-comparable snapshot explicitly and requires the sample series and any `READ_FAILED` markers as acceptance artefacts. |
| Autonomous operation, failure handling and recovery | 15 | 15 | Cause-agnostic `OnFailure=` coverage across timeout/OOM/non-zero-exit; no alert loop; no auto-retry (reasoned against the 2026-09-11 K1 incident); the wrapper-exit-contract inversion test closes the correct (non-vacuous) risk. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost-avoidance framed on measured numbers only; every exclusion names its reason. |
| **Total** | **100** | **100** | |

## Required changes

None.

## Blockers

The per-unit fix-or-retire rulings for `breezy-offer-gate-daily` and for M_A/M_B (separately)
remain strategy-lead BLOCKERs on 15b/15c, as the plan itself states and does not attempt to
pre-empt. 15a carries no blocker and is independently actionable.
