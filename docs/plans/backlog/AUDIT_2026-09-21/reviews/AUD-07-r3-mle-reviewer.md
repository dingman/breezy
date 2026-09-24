# AUD-07 review — round 3 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: 360d213f313643451d06addbf89055d4b5f5c5f140974cfef946450f04735dbe
Round: 3

## Round-2 remedy verification

- **Re-alert ladder (round-2 MATERIAL):** CONFIRMED adopted by reference from AUD-04 §6 D8, with the
  same WARN-weekly/CRITICAL-daily structure, restart-surviving latch, and clear-then-full-re-arm.
  Tests cover the day-N-repeat case (`test_a_thirty_night_freeze_re_alerts_weekly_then_escalates_to_daily_critical`)
  and clear-then-refire (`test_a_new_position_clears_the_streak_emits_one_info_and_fully_re_arms`),
  matching this review round's explicit ask.
- **`exit_gate.py:55`** — independently re-read: `_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]]
  = frozenset({"pm_us_crh_exit_v4"})` — CONFIRMED byte-identical to the plan's citation.
- **`DurableFillRecord`/`FILL_KEY_PREFIX`** (`client.py:641`, `:384`) — independently re-grepped,
  CONFIRMED.
- **"Overlapping positions" = inner join on `trial_id`**, defined identically in AUD-04 §8 AC#4 and
  here (§6, §8 AC#6) — CONFIRMED textually identical in both plans (cross-checked both files).

## New finding this round — same shared-ladder duplication risk as AUD-04, self-conceded but unfixed

**MINOR** (joint with AUD-04's review record; see that record for the full argument).

File: AUD-07 §6 D, §12 ("the ladder's period-key computation is shared with AUD-04 — if the two
implementations diverge, nothing in either plan detects it").

This plan's own revision-3 self-score names the exact gap this review's brief asks about: the ladder
is adopted "by reference and without variation" from AUD-04, but nothing enforces that the two
period-key computations (ISO-week and UTC-day boundary arithmetic, streak state transitions) stay
identical once both are independently coded in two different modules with two different latch files.
The self-conceding text is honest, but it is recorded as an accepted residual weakness rather than
addressed with a required change — and this review round's brief specifically calls the shared ladder
out for scrutiny, so I am elevating it from "noted" to "required."

Fix: same as recommended on AUD-04's record — extract the shared period-key/streak logic into one
function both plans import (or add a documented cross-equivalence test), so "adopted by reference" is
enforced mechanically rather than by two authors reading the same paragraph independently.

## Verification of the two brief-specified ladder questions for this cluster, as applied to AUD-07

- **Is a first repeat after 7 days fast enough given the record is already frozen?** The live record's
  own baseline (§11: `n_positions_new_since_previous_run` unreported for 4+ consecutive nights as of
  authoring) means the streak is already past the `<3` silent zone and into the weekly-WARN band. A
  weekly cadence for a non-urgent, currently-expected "no new positions" state (trading paused since
  09-15, corpus growth blocked in fact on BLOCKER-1) is proportionate — this is a diagnostic-legibility
  control, not a safety-critical page, and escalating to daily only after two full weeks of zero
  progress is a reasonable balance against the WP-R1 false-page discipline this same backlog was
  opened to protect (`PROGRESS.md:103-128`). I find no defect in the cadence itself.
- **Do tests cover day-N-repeat and clear-then-refire?** Yes, both are present and both are structured
  to fail against the prior round's single-shot latch (confirmed by reading the test names and their
  stated purpose in §7 step 3) — this satisfies the brief's explicit ask.

## Other checks

`test_the_reports_stated_ledger_count_matches_an_independent_second_read_of_the_ledger` genuinely
derives the ledger count a second, structurally different way (a direct read-only `DurableFillRecord`
scan under `FILL_KEY_PREFIX`) rather than re-parsing the same summaries store twice under a different
name — this closes the round-2 "two independently-wrong reads that agree" concern for real, and I
independently confirm the two data sources (`read_monitor_summaries` vs `read_filled_trials_state_db`
vs the ledger scan) are genuinely three distinct code paths reading three distinct stores.

The B2 negative-delta closing check (`delta_i = threatened_confirmed_ts_i − last_executable_exit_ts_i`,
classified and individually explained before the reconciled table may publish) is methodologically
sound: it does not paper over the anomaly with a summary statistic, and it correctly ties the
per-row classification to the gate's own subject matter (R-THREAT firing before the exit side
empties) rather than treating the median as authoritative.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **17** — matches round 2/3 self-score; extends EXIT-1
  honestly, explains why arming stays out of reach rather than narrowing the distance to it.
- Technical correctness and evidence grounding (20): **17** — every load-bearing citation this round
  independently re-verified (`exit_gate.py:55`, `client.py:641/384`) and holds exactly.
- Implementation specificity and feasibility (15): **11** — docked 1 below round 2's 12 (matching
  the author's own revision-3 score) for the shared-ladder duplication risk, elevated this round from
  a noted weakness to a required fix per the brief's explicit focus on this control.
- Acceptance criteria and validation quality (20): **16** — matches round 2/3 self-score; AC#2's
  independent-second-read requirement is a genuine strengthening, AC#6's cent-exact join is well
  specified but cannot be exercised until AUD-04 ships (named, not a new defect).
- Autonomous operation, failure handling, recovery (15): **12** — matches round 2/3 self-score; the
  ladder closes the round-2 MATERIAL gap; every rung still depends on the timer firing, named
  honestly.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's measured ceiling, field-level
  path, numeric baseline and falsifier were independently re-assessed; no fixable defect found (round
  2: mle 7/10 citing only the criterion's structure, pm 10/10). Awarded in full per this round's
  instruction absent a named defect.

**Total: 83/100**

## Required changes to reach 100

1. Extract the shared re-alert ladder's period-key/streak logic into one function consumed by both
   AUD-04 and AUD-07 (or add a cross-implementation equivalence test) — see AUD-04's r3 record for
   the full argument; this is the same defect viewed from AUD-07's side of the mirror.

## Blockers

- **BLOCKER-1 (dependency in fact):** corpus cannot grow until trading resumes — unchanged, genuine,
  does not block this item's own fixes.
- **BLOCKER-2 (operator + PREREG):** arming requires registration and the 1-lot positive control —
  unchanged, genuine, operator-only.
- **BLOCKER-3 (strategy lead):** AUD-06a's boundary conclusions flow into v4's registration package —
  unchanged, genuine, correctly flagged rather than resolved.
