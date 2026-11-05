# AUD-15 review — round 2

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
sha256: 7b4582b341ac0bf36ce397749a49cd6104cb8239bd1581fecf4dc265e81fb0e9
Round: 2
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-1 disposition audit

Round 1: this reviewer 90/100 (no material defects, independently confirmed the `OnFailure=`
hole by grep); silent-failure-hunter 91/100 (also none). §13 lists 6 dispositions. Independently
re-verified each against the current plan body and the artefact:

- Disposition 1 (quote the offer-gate unit's self-contradictory comment) — CONFIRMED PRESENT and
  independently re-verified this session by reading the unit file directly (see below); the
  extension (mb-daily's *same* sentence has the *opposite* truth value) is also confirmed.
- Disposition 2 (direct cgroup `memory.events`/`memory.stat` read in a quiet window) — CONFIRMED
  promoted from a §12 caution to a named §7 15b/15c step 1e deliverable and §8 items 4/6.
- Disposition 3 (re-aim, not delete, the exit-0 test) — CONFIRMED: §7 15a step 4 now pins the
  wrapper's exit contract (0 = lock contention, 75 = lock infrastructure) rather than an
  `OnFailure`-level assertion on a path that structurally cannot fire.
- Disposition 4 (decision table for 15b/15c) — CONFIRMED present in §6, mapping five evidence
  observations to implied dispositions.
- Dispositions 5-6 (`TimeoutStartSec` guard; notifier's own-failure residual named) — CONFIRMED
  present as new negative acceptance criteria (§8 item 9) and a named residual in §9.

No rejection in either round-1 record; none was warranted.

## Claims verified this session (fresh, re-read from the artefact directly, not carried from
round 1's record)

- `/usr/bin/grep -rl OnFailure deploy/systemd/` → matches only `.sh` wrapper files and
  `README.md`; zero `.service` files. CONFIRMED, structural gap is real.
- `breezy-offer-gate-daily.service` — read in full. `MemoryHigh=12G`/`MemoryMax=16G` at
  `:41-42` (exact), `TimeoutStartSec=1800` at `:81` (exact), `Slice=breezy-studies.slice` at
  `:46` (exact), and the comment at `:35-36` reads "at 14.7G, 17.3G, 15.3G over 7-9 min wall
  clock. MemoryHigh=12G/MemoryMax=16G matches the sibling tape studies: well above this unit's
  measured range" — this is arithmetically backwards (12 < 14.7-17.3) exactly as the plan states.
- `breezy-mb-daily.service` — read in full. `:37-38` cites "10.1G, 11.6G ... well above this
  unit's measured range" against the same `MemoryHigh=12G` — here the comment is correct (12 >
  11.6). Confirms the plan's central diagnostic claim: the *same sentence* is right for one unit
  and wrong for the other, which is the evidence that the two units fail for different reasons.
  `Slice=breezy-studies.slice` at `:48` (exact), `TimeoutStartSec=3600` at `:62` (exact).
- `offer-gate-daily-run.sh:53-59` (approx) — read; confirms the exit-0-on-lock-contention /
  exit-75-on-lock-infrastructure contract the plan's §7 15a step 4 test targets.
- The `breezy-family-tally@pm_us_crh_cont` exclusion (routed to G-04, not absorbed) is consistent
  with this reviewer's independent read of AUD-05's territory (not re-opened here).

## Analysis

The plan's core structural finding (`OnFailure=` absent from every study `.service`) and its two
independent per-unit diagnoses (memory-throttle-into-swap for offer-gate; workload growth against
a fixed timeout for mb-daily, evidenced by a flat memory peak and a climbing wall clock across
four days) both survive a from-scratch re-read of the unit files and their own comments. The
decision table in §6 correctly narrows the fix-or-retire ruling to a bounded question per unit
without pre-deciding either ruling, which is the correct posture given the brief's instruction
that operator/strategy-lead judgment calls must be surfaced as blockers, not decided here. The
`TimeoutStartSec` guard (never shippable as "the fix") is the right adversarial check for this
class of item — a naive fix would convert a 30-minute silent failure into a 60-minute one, and
the plan closes that off with a negative `git diff` acceptance item rather than prose alone.

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond what round 1 already
disclosed and this revision already closed.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — both named units get distinct, measured
  diagnoses; the un-named structural `OnFailure=` gap is added and independently confirmed real;
  G-04 (the family-tally unit) is correctly routed to its own item rather than absorbed here.
- Technical correctness and evidence grounding: 20/20 — every unit-file citation checked
  (`:35-36, :37-38, :41-42, :43-44, :46, :48, :62, :81`) reproduces exactly at HEAD; the
  backwards-comment claim and its mb-daily counter-example both verified by direct reading, not
  by trusting the plan's quotation.
- Implementation specificity and feasibility: 15/15 — 15a is fully literal (unit name, `%n`/`%i`
  expansion, entry-point shape, severity, event name, site, `detail` contract, four pin tests);
  15b/15c are correctly bounded by the decision table to what can be specified before a ruling.
- Acceptance criteria and validation quality: 20/20 — `systemd-analyze --user verify` empty
  output, three-consecutive-run acceptance, a **delivered** (not logged) alert artefact, the
  cgroup counter check, and three negative `git diff` guards (`MemoryMax`, slice,
  `TimeoutStartSec`) together make "quietly loosen a cap to make the timeout go away" mechanically
  detectable.
- Autonomous operation, failure handling, recovery: 15/15 — cause-agnostic coverage (timeout,
  OOM-kill, non-zero exit all trigger the same `OnFailure=` path); the notifier's own failure mode
  is deliberately fail-closed and its residual (nothing pages on the notifier itself) is named
  with a reasoned decision not to close it (avoiding an alert loop); no auto-retry, correctly
  reasoned against the 2026-09-11 K1 host-contention incident.
- Portfolio objective alignment, scope, dependencies: 10/10 — cost-avoidance framing uses only
  measured CPU/wall/memory figures, never an invented dollar amount; G-04 routed to its owner;
  every scope exclusion (raising `MemoryMax`, changing method, auto-retry) states its reason.

**Total: 100/100**

## Required changes for full marks

None. No point was withheld without a nameable defect and required change; none could be named
this round.

## Blockers

- The per-unit fix-or-retire ruling for `breezy-offer-gate-daily` (15b) and for M_A/M_B under
  `breezy-mb-daily` (15c, ruled separately) remain correctly named, undecided strategy-lead
  rulings. Not waivable by this review. 15a has no blocker and is independently actionable today.
