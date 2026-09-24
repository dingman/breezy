# AUD-15 round-4 review — trading-bot-architect

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
SHA256: d78db339b9809f5f71425f19b19dd422c2d1b6ebb1dad9db34a73721f99a50a8
Round: 4 (FINAL)
Reviewer: trading-bot-architect

## Claims verified against source (this session, live host read)

| Claim | Verdict |
|---|---|
| `systemctl --user show breezy-mb-daily.service -p Type -p RemainAfterExit -p ActiveState -p ControlGroup -p MemoryPeak -p MemorySwapPeak` → `Type=oneshot`, `RemainAfterExit=no`, `ActiveState=failed`, **`ControlGroup=` empty**, `MemoryPeak=12884615168`, `MemorySwapPeak=0` | CONFIRMED — ran the exact command this session; output matches the plan's quoted transcript byte-for-byte |
| Same for `breezy-offer-gate-daily.service`: `ControlGroup=` empty, `MemoryPeak=11061796864`, `MemorySwapPeak=92901376` | CONFIRMED, matches exactly |
| `/usr/bin/grep -rl OnFailure deploy/systemd/` matches only wrapper `.sh`/`README.md`, no `.service` | Not re-run this session (round 1/2/3 already independently confirmed it); the wrapper `offer-gate-daily-run.sh` header quoted in §6/§9 (`OnFailure=` fires on a healthy skip comment, `unset POSIXLY_CORRECT`, `exit 75` on lock infrastructure) matches the file read directly this session |
| `deploy/systemd/AlertDetail`/`health.py` sink reuse — no new claim beyond prior rounds | consistent |

This is the plan's own central, falsifiable arbiter claim — that `ControlGroup=` is empty post-exit and `memory.events` is therefore unreadable except while the unit is `active` — and it is the exact claim the round-4 brief asked me to re-verify. It is TRUE, measured directly on this host, not merely re-quoted from the plan.

## Defects

None MATERIAL. I did not find a defect in the positive-control design (offer-gate's `high` counter predicted non-zero before the read, and a ≈0 control result is defined as a measurement defect rather than "mb-daily is fine") — this is the correct shape for an instrument whose zero-reading capability has not yet been demonstrated, and it closes exactly the failure class recorded in this repo's own memory index ("positive control is the bot's job").

One thing I checked and found sound rather than defective: the decision table's row mapping ("consumer exists, family live, unit still overruns after limit reconciliation → retire candidate, not a budget candidate") correctly refuses to let `TimeoutStartSec` be raised as a disguised fix, and §8 item 9's negative `git diff` on `TimeoutStartSec` makes that mechanically checked rather than merely stated.

**MINOR — residual, self-disclosed and unclosed, not newly found:** the quiet-window scheduling for the live cgroup read (catching offer-gate mid-run for its own positive control) remains an execution-time coordination task with no stated mechanism (e.g., how the executor knows a run is "quiet" versus contending with the live node). This is unchanged from round 3's disposition and was already deducted for; I am not deducting for it a second time as a new finding, only noting it survives.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both units get distinct, measured diagnoses; the un-named `OnFailure=` structural gap is added and independently confirmed by grep in prior rounds; G-04 correctly routed to its own item rather than absorbed. |
| Technical correctness and evidence grounding | 20 | 18 | The plan's own central arbiter claim (`ControlGroup=` empties post-exit, `MemoryPeak`/`MemorySwapPeak` persist) is verified TRUE by direct command this session, not merely re-read from the plan text — this is the strongest evidence grounding this plan has carried across four rounds. Deducted 2, carried from the plan's own honest self-assessment: the truncated-quote citation defect from round 2 is fixed but is on record as having happened, and the mb-daily throttle contribution is still bounded by argument (the falsifiable `memory.events` condition) rather than by an executed measurement. |
| Implementation specificity and feasibility | 15 | 14 | 15a is fully literal (unit name, `%n`/`%i`, entry point, severity, event, site, detail contract). The arbiter read for 15b/15c is now literal to the command and path, with the positive control's pass/fail consequence stated. Deducted 1: quiet-window scheduling for the live read remains unspecified, as noted above. |
| Acceptance criteria and validation quality | 20 | 19 | Nine items: `systemd-analyze` empty, a delivered (not logged) alert artefact, the cgroup counter check with the resolved `ControlGroup` path and the pre-read prediction, decision-table attribution, three negative `git diff` guards. Three-consecutive-runs acceptance necessarily lands after merge, which is inherent to the remediation, not a specification gap. |
| Autonomous operation, failure handling and recovery | 15 | 14 | Cause-agnostic `OnFailure=` coverage across timeout/OOM/non-zero-exit; no alert loop (the notifier's own failure is named with its residual rather than hidden); no auto-retry, correctly reasoned against the 2026-09-11 K1 host-contention incident; the wrapper-exit-contract inversion test closes the correct risk (a wrapper masking a genuine failure as exit 0), not the vacuous one round 1 first proposed. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost-avoidance framed on measured numbers only (CPU/wall/swap tables, not invented dollars); every exclusion (raising `MemoryMax`, method changes, the protected window) names its reason; G-04 deconflicted. |
| **Total** | **100** | **94** | |

## Required changes

None MATERIAL. The one open item (quiet-window read scheduling) is carried, not new, and does not block acceptance of 15a; it is a precondition of 15b/15c's evidence-pack step that the executing session must resolve operationally (e.g., by scheduling the read against the unit's own timer-fired window), not a design gap requiring more plan text.

## Blockers

The per-unit fix-or-retire rulings for `breezy-offer-gate-daily` and for M_A/M_B (separately) remain strategy-lead BLOCKERs on 15b/15c, as the plan itself states and does not attempt to pre-empt. 15a carries no blocker and is independently actionable today.
