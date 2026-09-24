# AUD-15 review (round 2)

**Plan file sha256:** 7b4582b341ac0bf36ce397749a49cd6104cb8239bd1581fecf4dc265e81fb0e9
**Round:** 2
**Reviewer:** silent-failure-hunter (independent, blind)

## Round-1 disposition verification

Round 1 (both records) found no material defect. §13's disposition table shows the offer-gate
comment quote, the cgroup `memory.events`/`memory.stat` re-measurement requirement, the
exit-0-must-not-alert test re-aim, and the pre-specified fix-or-retire decision table all
ACCEPTED and incorporated. I re-verified the load-bearing artefacts independently this session
(not merely re-reading §13's claims):

- `/usr/bin/grep -rl OnFailure deploy/systemd/` — CONFIRMED (re-run): matches only `.sh`
  wrappers and `README.md`, zero `.service` files.
- `deploy/systemd/breezy-offer-gate-daily.service:30-42` — CONFIRMED verbatim: `MemoryHigh=12G`,
  `MemoryMax=16G`, and the comment "the last three completed runs peaked at 14.7G, 17.3G,
  15.3G… MemoryHigh=12G/MemoryMax=16G… well above this unit's measured range" — 12G is indeed
  below all three cited peaks; the comment's arithmetic is backwards, exactly as the plan states.
- `offer-gate-daily-run.sh:53-59`, `TimeoutStartSec=1800`/`:3600` on the two units — both
  confirmed at the cited line numbers.

## Defects

**MINOR — the mb-daily comment contrast ("opposite truth value") is itself imprecise, and the
plan's own quote is selectively partial.** §2 states: *"`breezy-mb-daily.service:37-38` cites
peaks of '10.1G, 11.6G' against the same `MemoryHigh=12G` — for *that* unit the comment's 'well
above' is correct… Same cap, same sentence, opposite truth value."* I read
`breezy-mb-daily.service:35-38` directly: the actual comment cites **three** peaks, not two —
*"the last three completed runs peaked at **14.3G**, 10.1G, 11.6G."* The plan's quote drops the
first value. **14.3G is itself above the 12G `MemoryHigh`**, the same directional error the plan
correctly identifies on the offer-gate unit. So the comment's "well above this unit's measured
range" is not cleanly *correct* for mb-daily either — it is correct for two of the three cited
runs and wrong for the third. The "opposite truth value" framing overstates the contrast between
the two units' header comments. This does not undermine the plan's actual diagnosis of mb-daily
(workload growth against a fixed time budget, independently supported by the measured wall-clock
table in §2 showing 39m→44m→>60m→>60m at flat memory with negligible swap — 80K, 32K — which is
the real evidence for "not a throttle problem") — but the specific corroborating-comment claim is
a citation accuracy defect of exactly the kind the brief asks to check ("a citation that does not
say what the plan claims is a defect"). **Fix:** quote all three cited peaks (14.3G, 10.1G,
11.6G) and state precisely that the comment is correct for 2 of 3, not "opposite truth value" —
or drop the framing and rely on the (stronger, already-present) swap-negligible wall-clock
evidence alone.

No MATERIAL defect found. The `OnFailure=` design (cause-agnostic coverage of timeout/OOM/exit
code via one template notifier, `%n`/`%i` expansion, no self-`OnFailure=` to avoid an alert
loop, the wrapper-exit-contract inversion test replacing the vacuous exit-0 test, and the named,
bounded residual for the notifier's own failure) is sound and directly answers every question
this review was asked to probe. The retirement path explicitly requires the timer fully gone
(`systemctl --user list-timers`), not merely inactive, avoiding the `breezy-pm-crh-{cont,v2}-tally`
orphan anti-pattern by name.

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 19 |
| Technical correctness and evidence grounding | 20 | 18 |
| Implementation specificity and feasibility | 15 | 14 |
| Acceptance criteria and validation quality | 20 | 19 |
| Autonomous operation, failure handling and recovery | 15 | 14 |
| Portfolio objective alignment, scope and dependencies | 10 | 10 |
| **Total** | **100** | **94** |

## Required changes to reach 100

1. Correct §2's mb-daily comment quote to include the dropped 14.3G peak and restate the
   two-unit contrast accurately (2-of-3 correct, not "opposite truth value").

## Blockers

Per-unit fix-or-retire rulings for offer-gate and for M_A/M_B (separately) remain genuine
strategy-lead BLOCKERs on 15b/15c, correctly named and not waivable by review. 15a has none.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-15-r2-silent-failure-hunter.md
