# AUD-07 — Round 2 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
SHA256: 1feb9c09e1615753cfb083d84ba74f5cd9d43ac12cc85160d6ec57c96090bf24
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)

## Round-1 defect disposition verification

- Negative-median timing anomaly, no concrete closing check (my MINOR, mle independently flagged
  the same): CONFIRMED fixed and strengthened beyond what I asked for. §6 B2 defines a per-row
  `delta_i` classification into `THREATENED_BEFORE/AFTER_EXIT_SIDE_EMPTIED`, forbids publishing the
  reconciled table while any negative-delta row is unexplained, adds two RED tests through the real
  writer path (both orderings), and states the gate-reading consequence (`AFTER` rows do not count
  toward R-THREAT's "≥3 firing" gate even if that lowers the qualifying count).
- No standing AUD-04↔AUD-07 reconciliation (my MINOR): CONFIRMED fixed on both sides — §6 adds a
  standing (not one-shot) reconciliation read through AUD-04's `schema_version` reader, with a
  latched `EXIT_PNL_RECONCILIATION_MISMATCH`; AUD-04's own §8 AC#4 independently carries the mirror
  obligation, which I verified is present in AUD-04's current revision this round.
- Position-sourcing bug not located (both reviewers): CONFIRMED located with file:line — C1 (default
  literal `_DEFAULT_MONITORED_FAMILY_ID`), C2 (two different position universes:
  `read_monitor_summaries` vs `read_filled_trials_state_db`), C3 (the `monitor/` directory does not
  exist on disk). Independently re-verified this round: `ls ~/.local/share/breezy/catalog/monitor`
  exits nonzero (no such directory) against the live host, confirming C3's on-disk claim directly
  rather than trusting the plan's assertion of it.

## Fresh review of the full revision (new defects)

**MINOR — the standing AUD-04↔AUD-07 reconciliation compares `sum_hold_pnl` (this study) against
AUD-04's `realised_pnl_after_fees_total` without stating whether the two are computed over an
identical row set, and the two artefacts have different natural scopes (this study is per-position
over its fixed N=5 corpus; AUD-04 is account-wide and family-agnostic).**
File: AUD-07 §6 "standing P&L reconciliation", §8 AC#6.
Issue: the reconciliation is stated as "over the overlapping positions," which is the right idea,
but "overlapping" is not defined precisely enough to implement unambiguously — is it matched by
`trial_id`, by `(instrument_id, fill_ts)`, or by station-day? Given this study's `sum_hold_pnl` is a
HOLD-strategy counterfactual (the live family never sells) while AUD-04's realised P&L is over
actual settled fills, the two numbers should coincide only where "hold" and "actual" are the same
outcome — which, since the family never exits, should in fact be every row today. That equivalence
is not stated as the reason the reconciliation should currently match exactly; without it, an
implementer might treat a partial-N mismatch as expected slack rather than an alarm.
Fix: state explicitly in §6 that, until any exit ever fires, "hold" and "actual" are definitionally
identical, so the reconciliation should match to the cent for every row today, not just on average —
and that any exercised exit (post-arming, out of this item's scope) changes this to a genuine
matched-subset comparison.

**MINOR — C2/C3's fix branches on step 0's finding, and the "monitor legitimately never flushes"
branch's remediation (state the universe explicitly, reconcile against the ledger count) is not
accompanied by a test asserting the *ledger* count itself is read correctly, only that it is stated.**
File: AUD-07 §6 C2/C3, §7 step 1.
Issue: `test_the_report_states_its_position_universe_and_the_ledger_count_over_the_same_period`
asserts the report *states* a ledger count, but the acceptance criteria as written (AC#2:
"reconcilable... either equal, or differing with the difference and its universe named") do not
require the stated ledger count to be independently checked against the same source AUD-04 reads
(`DurableFillRecord` under `FILL_KEY_PREFIX`). Two independently-wrong ledger reads that happen to
agree with each other would pass this criterion.
Fix: add one test asserting the position-monitor report's stated ledger count matches a count
derived independently through AUD-04's reader (once AUD-04 ships) or through the same
`fill_time_count.py` read-only idiom this backlog already uses elsewhere.

No MATERIAL defect. The arming-exclusion discipline is airtight (byte-unchanged `exit_gate.py`,
manifest `status` stays `DRAFT_NOT_REGISTERED`, the §4 gates untouched, the "gate passed → arm"
gravity explicitly resisted in §9), which is the property that matters most given this item sits one
step from a real order path. Every artefact figure I spot-checked (the 0-vs-5 disagreement, the
`exit_gate.py:55` frozenset, the C1 default literal, the C3 on-disk absence) is confirmed accurate
against live source, not merely against the plan's own prose.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **18** — extends EXIT-1 rather than duplicating it, surfaces
  four defects (B, B2, C, D) the source audit did not name, keeps arming strictly excluded as G-12
  requires. −2 because G-12's literal ask (an armed or advancing-toward-armed seam) is addressed by
  explaining why arming stays out of reach rather than by narrowing the distance to it — an honest
  and correct choice, but still short of the gap's literal content.
- Technical correctness and evidence grounding (20): **18** — every cited figure and file:line
  independently re-verified this round, including a live on-disk check of C3. −2 because the drift
  cause (finding B) remains three competing hypotheses at plan time, which is appropriate discipline
  but leaves the item's central reconciliation open until step 6 runs.
- Implementation specificity and feasibility (15): **13** — the sourcing path, the default literal,
  the wrapper's missing argument, the two position universes, the latch schema and the per-row
  anomaly classification are all named with file:line. −2 for the "overlapping positions" definition
  gap and the ledger-count independent-check gap above.
- Acceptance criteria and validation quality (20): **18** — measurable, with a negative criterion (no
  order placed, no family registered, no gate opened), a standing cross-artefact reconciliation, and
  an anomaly that must be closed rather than merely observed. −2 for the two specification gaps
  above, both of which bear on whether the reconciliation criterion is actually falsifiable as
  written.
- Autonomous operation, failure handling, recovery (15): **14** — two genuine autonomy fixes (a job
  that cannot progress now says so via `EXIT_CORPUS_FROZEN`; a report that cannot see its corpus
  states its universe rather than printing a bare zero), each with a fully specified latch and
  false-page discipline matching AUD-04's mirrored mechanism. −1 because, as the plan itself
  concedes, both alerts depend on the nightly timers continuing to fire at all — a stopped timer is
  still detected only by systemd state, not by either new signal.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 states the measured ceiling
  honestly (a near-zero structural recovery on the one clean corpus), the field-level evaluation path
  with a standing cross-check, and a three-row table whose last row flatly states "this item changes
  ROI not at all today." §4/§12 correctly narrow BLOCKER-1 to corpus growth only, leaving every
  in-scope fix executable today. No operator ruling is required to reach full marks on this
  criterion; the arming decision itself (BLOCKER-2, operator-only) is named below rather than scored
  down.

**Total: 91/100**

## Required changes to reach 100

1. Define "overlapping positions" precisely for the standing AUD-04↔AUD-07 reconciliation (by
   `trial_id`, instrument, or station-day), and state that until any exit fires, hold-P&L and
   actual-P&L are definitionally identical, so the reconciliation should match to the cent today.
2. Add a test asserting the position-monitor report's stated ledger count is independently verified
   against a second read of the same durable fill ledger, not merely stated.

## Blockers

BLOCKER-1 (corpus cannot grow until trading resumes, G-01) blocks corpus growth only — verified
correct in §4/§12, every in-scope fix here is executable at the current N=5. BLOCKER-2 (PREREG v4
registration plus the operator-only 1-lot positive control) is genuinely outside any reviewer's
authority to resolve and is correctly left untouched by this plan. BLOCKER-3 (AUD-06a's boundary
conclusions flow into v4's registration package) is a named dependency, not a blocker this item owns.
None of these three is a scoring deduction under this round's guidance.
