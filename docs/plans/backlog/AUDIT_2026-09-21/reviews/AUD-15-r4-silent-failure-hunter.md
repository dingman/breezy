# AUD-15 — Round 4 review (silent-failure-hunter, FINAL)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** d78db339b9809f5f71425f19b19dd422c2d1b6ebb1dad9db34a73721f99a50a8
**Round:** 4 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source this session

| Claim | Status |
|---|---|
| `OnFailure=` appears in no `.service` unit under `deploy/systemd/` | Not re-run this session (prior rounds' `/usr/bin/grep -rl OnFailure deploy/systemd/` result was independently confirmed twice already; no reason to doubt) |
| `emit_alert`/`AlertPayload`/`resolve_alert_sink` reuse (`health.py:351,579,668`) | CONFIRMED via codegraph this session (consistent with AUD-14 review's independent confirmation of the same sink) |
| `systemctl --user show <unit> -p ControlGroup` is empty post-exit for a `Type=oneshot`, `RemainAfterExit=no` unit, while `MemoryPeak`/`MemorySwapPeak` persist | Accepted as measured by the plan's own session-3/4 transcript (`ControlGroup=` empty, `MemoryPeak=12884615168` for mb-daily, `MemoryPeak=11061796864`/`MemorySwapPeak=92901376` for offer-gate) — internally consistent with cgroup-v2 lifecycle semantics (a `oneshot` unit's transient scope is torn down on exit; `MemoryPeak`/`MemorySwapPeak` are systemd-maintained resource-accounting properties that outlive the cgroup) |
| cgroup v2 `memory.events` counters (`low`/`high`/`max`/`oom`/`oom_kill`) are cumulative for the lifetime of the cgroup, not point-in-time gauges | Standard cgroup-v2 semantics (kernel documentation); the plan does not contradict this, but also never uses it |

## New MATERIAL defect this round — the brief's own attack point

**§7 15b/15c step 1(e) and §6's falsifier specify WHAT to read (`ControlGroup` then `memory.events`) and WHEN it is valid to read it (only while `ActiveState=active`), but not WHO/WHAT performs that read during an actual UNATTENDED run, nor how the read is protected from racing teardown.**

Both study units run on a systemd timer, unattended, for 30–60 minutes of wall clock (offer-gate: `TimeoutStartSec=1800`; mb-daily: `TimeoutStartSec=3600`, with real runs up to and past 60 minutes). §7 step 1(e) requires the `memory.events` read to be "captured while `ActiveState=active`, during a run in a quiet window" — but the plan specifies only the two static commands (`systemctl --user show <unit> -p ControlGroup --value` then `cat /sys/fs/cgroup<path>/memory.events`), never:

1. **The orchestration.** Is this a human/agent manually triggering `systemctl --user start <unit>` and then polling in a foreground/background loop for up to an hour, watching a clock? Is it a companion `ExecStartPost=`/wrapper-embedded step that snapshots `memory.events` to a file at intervals so no one has to be present? The plan names neither. Given both units are `Type=oneshot` launched by a `.timer` (not started interactively in the ordinary case), an executor who wants "the same method, same session" positive-control read for offer-gate (§6's binding precondition) must coordinate two separate ~30–60 minute unattended windows without dropping the live read — nothing in §7 says how.
2. **The race with teardown.** `ControlGroup=` is confirmed (by the plan's own measurement) to go empty the instant the unit leaves `active`. A read sequence of `show -p ControlGroup --value` followed by a separate `cat .../memory.events` has an unbounded window between the two commands in which the unit can finish; the second command then fails (`No such file or directory`) rather than returning a stale value — which is actually the *safe* failure (a hard error, not a false zero) — but the plan states no retry/handling for this, and does not say whether a `cat` failure here is recorded as "failed read, re-attempt" or silently drops that one sample.
3. **The monotonic-counter timing problem.** `memory.events`' `high` counter accumulates from cgroup creation; a *single* read taken early in a run under-reports relative to a read taken just before completion. §6/§7 specify no sampling cadence (single point-in-time snapshot vs. periodic polling through the run) and no requirement that the offer-gate positive-control read and the mb-daily diagnostic read be taken at a **comparable phase** of their respective runs. Because offer-gate times out at 30 min and mb-daily now runs past 60 min, a single arbitrarily-timed read on each is not a controlled comparison: it is possible for the control to read non-zero (confirming the instrument works) while the mb-daily read, taken earlier in its longer run, under-reports `high` for reasons unrelated to whether a genuine throttle exists later in that same run — and the plan's binding rule ("control non-zero + mb-daily ≈0 ⇒ input-growth diagnosis stands") would then accept a false negative it explicitly says it is designed to catch.

This is exactly the failure class round 3 closed for the *post-exit* read (a zero from a torn-down cgroup reported as a real zero) — round 4 closed that literal question ("who performs the read, is it racing teardown, when is a zero not a zero") is answered for the *static command*, but not for the *unattended, hour-long, live-read orchestration* the command has to run inside. A false "instrument validated, mb-daily ≈0" reading downstream would then feed directly into §6's decision table row "input growth only" and exclude row (i) (`MemoryHigh` reconciliation) exactly as the round-3 fix was designed to prevent for the *post-exit* case — this round's gap reopens the same risk one layer up, in the live-read's own timing.

**Required change:** specify the concrete unattended-safe orchestration for the live read — e.g., an explicit instruction that the executing session manually triggers each unit via `systemctl --user start <unit>` and runs a backgrounded polling loop (named interval, e.g. every 30–60s) for the unit's full active lifetime, writing each `memory.events` snapshot with a timestamp to a scratch file, so the LAST successful pre-teardown sample is used as the peak reading rather than a single arbitrarily-timed point; state explicitly what happens when a `cat` in that loop races teardown (treat as end-of-loop, not as a zero, and use the prior sample); and require the offer-gate control read and the mb-daily diagnostic read to be sampled on the same cadence so the comparison is over comparably-timed points in each run, not a single snapshot at an unstated moment in runs of very different length.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both units get distinct, measured diagnoses; the un-named `OnFailure=` structural gap is added; G-04 correctly routed to its own item. Unaffected by the new defect, which is about *how* the arbiter measurement is taken, not the diagnosis's substance. |
| Technical correctness and evidence grounding | 20 | 17 | Unit-file citations, the `ControlGroup=`/`MemoryPeak` split and the delegation/positive-control logic are all measured and accurate. Deducted 3 (carried, not re-litigated): the round-2 truncated-quote defect and the fact that the live counter has still never actually been read remain the reasons this criterion is not 20; this round's new defect (below) is scored under specificity/acceptance rather than double-counted here. |
| Implementation specificity and feasibility | 15 | 11 | **MATERIAL** — the live-read orchestration for an unattended, hour-long run is unspecified: no named actor, no polling cadence, no teardown-race handling, no comparable-timing requirement between the control read and the diagnostic read. This is the load-bearing mechanic for 15c's entire diagnosis and it is the one piece of §7 step 1(e) left to the executor's invention. |
| Acceptance criteria and validation quality | 20 | 17 | §8 item 4 requires "the resolved `ControlGroup` path quoted" and the control reading, but does not require the sampling cadence or the last-good-sample handling to be recorded, so an executor could satisfy item 4's letter with a single early, under-reporting snapshot on one or both units without the note reflecting the risk. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Unchanged: cause-agnostic `OnFailure=` coverage, no alert loop, no auto-retry (reasoned), wrapper masking pinned, notifier residual named. Not implicated by the 15b/15c evidence-gathering gap, which is build-time only. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: cost-avoidance on measured numbers only; every exclusion names its reason. |
| **Total** | **100** | **88** | |

## Required changes (summary)

1. Name the concrete actor/mechanism that performs the live `memory.events` read for an unattended, up-to-60-minute run (manual trigger + backgrounded polling loop, or an in-unit instrumentation step) — not merely the two static commands to run once conditions are met.
2. State the polling cadence and what happens when a sample races teardown (use the last successful pre-exit sample; do not record a `cat` failure as a zero).
3. Require the offer-gate positive-control read and the mb-daily diagnostic read to be sampled on directly comparable timing (e.g., same cadence, both carried through to their respective run's end) so the control validates the instrument at a phase of the run comparable to where the diagnostic read is trusted, not merely "somewhere during an active run."

## Blockers

None of the above requires an operator/strategy-lead ruling — this is a build-side measurement-methodology gap, fixable within the plan's own scope, on the evidence-gathering step only (15a's `OnFailure=` work is unaffected and has no defect this round). The existing BLOCKERs (fix-or-retire rulings for offer-gate and for M_A/M_B) are unchanged and are not created or resolved by this review.
