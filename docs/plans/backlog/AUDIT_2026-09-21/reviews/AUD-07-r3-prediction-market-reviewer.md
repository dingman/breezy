# AUD-07 — Round 3 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
SHA256: 360d213f313643451d06addbf89055d4b5f5c5f140974cfef946450f04735dbe
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)

## Round-2 defect disposition verification

All round-2 findings are genuinely closed in the plan body:

- Re-alert ladder for `EXIT_CORPUS_FROZEN`/`EXIT_PNL_RECONCILIATION_MISMATCH` (adopted by reference
  from AUD-04 §6 D8): CONFIRMED — the table (weekly `WARN` at 3≤streak≤13, daily `CRITICAL` at
  streak≥14) and latch-file schema match AUD-04's ladder field-for-field, so the two controls cannot
  drift apart as designed.
- "Overlapping positions" defined as the inner join on `trial_id`, with the "must match to the cent
  today" argument: CONFIRMED. `exit_gate.py:55` re-verified —
  `_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]] = frozenset({"pm_us_crh_exit_v4"})` — and
  the manifest's `DRAFT_NOT_REGISTERED` status is unchanged by this item, so "hold" and "actual" are
  indeed definitionally identical for every row today; the exact-match requirement is sound.
- Independent second read of the ledger count (`DurableFillRecord` under `FILL_KEY_PREFIX`):
  CONFIRMED — `client.py:641` (class) and `:384` (`FILL_KEY_PREFIX: Final[str] =
  f"{STATE_KEY_NAMESPACE}fill/"`) both verified exact.

No round-2 disposition is misrepresented.

## Fresh review of the full revision (new defects, round-3 lens)

I independently re-verified the C1–C3 findings and the wrapper/composition path-derivation claim,
since they are the load-bearing diagnosis this item is built on:

- C1: `_DEFAULT_MONITORED_FAMILY_ID: Final[str] = "pm_us_crh_cont"` confirmed at
  `position_monitor_nightly_report.py:119`; `position-monitor-report-run.sh`'s `ARGS` block
  (verified lines ~102-106) indeed never passes `--family-manifest` — confirmed by reading the
  wrapper script directly, matching the plan's claim exactly.
- C2/C3: `SUMMARIES_DIR="$MONITOR_ROOT/summaries"` with `MONITOR_ROOT="$(dirname
  "$CATALOG_ROOT")/monitor"` in the wrapper, and `monitor_root = catalog_root.parent /
  _MONITOR_CATALOG_DIRNAME` / `summaries_dir = monitor_root / _MONITOR_SUMMARIES_DIRNAME` in
  `composition.py:563,663` — both confirmed to derive the identical path, supporting the plan's
  "paths agree by construction" claim and correctly narrowing step 0 to a live/never-flushed
  question rather than a path-mismatch bug.

No MATERIAL defect found. The B2 negative-median closing check (per-row `delta_i` classification,
gate-reading consequence stated as "AFTER rows do not count toward R-THREAT"), the standing
AUD-04↔AUD-07 reconciliation (now symmetric with AUD-04's mirror obligation, verified the join-key
definitions are byte-identical between the two plans), and the L-22 unforgeable-split guard on the
registration package (manifest half moves, code half — `exit_gate.py` diff empty — does not) are all
sound on this round's re-read.

One MINOR, not previously raised: §6 "A — complete the registration package" instructs setting
`taker_fee_coefficient` "to the coefficient in force at registration" for the `pm_us_crh_exit_v4`
manifest, but registration is explicitly out of scope for this item (`status` stays
`DRAFT_NOT_REGISTERED`). "The coefficient in force at registration" is therefore a value that cannot
be known at the time this item's own step 7 runs (registration is a future, separate, operator-gated
event) — the plan should either pin the coefficient to today's live value (`0.0695`, matching the
live family, stated as provisional and to be re-verified at actual registration time) or explicitly
mark this manifest field as `TBD_AT_REGISTRATION` rather than writing a value now that a future actor
might mistake for already-current. This is a documentation-precision gap in an otherwise inert
(non-arming) manifest edit, not a money-moving defect — the manifest stays `DRAFT_NOT_REGISTERED` and
`exit_gate.py`'s code half is unchanged either way, so nothing can fire on this value while it is
wrong.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **17** — extends EXIT-1 rather than duplicating it, and
  surfaces four defects (B, B2, C, D) the source audit did not name, each independently verified
  against source this round. −3, matching round 2's mark: G-12's literal ask (an armed or
  advancing-toward-armed seam) is answered by explaining why arming stays out of reach rather than by
  narrowing the distance to it — an honest but real completeness gap relative to the gap's literal
  text.
- Technical correctness and evidence grounding (20): **18** — every load-bearing citation
  (`exit_gate.py:55`, the wrapper's missing `--family-manifest`, the matching path-derivation,
  `client.py:641`/`:384`) re-verified independently against current source this round with no drift
  found. −2 because finding B (the study's drift between Rev 2 and the current nightly artefact)
  remains three competing hypotheses until step 6 runs — correctly deferred, but it is the item's
  central reconciliation and is still open at plan time.
- Implementation specificity and feasibility (15): **12** — sourcing path, default literal, missing
  wrapper argument, the two position universes, the ladder schema and the per-row anomaly
  classification are all named with file:line, each independently confirmed accurate. −3 for the
  C2/C3 branch-on-step-0 asymmetry (one branch is specified at a coarser grain), and for the minor
  `taker_fee_coefficient` provisional-value gap noted above.
- Acceptance criteria and validation quality (20): **17** — AC#2's independent-second-read
  requirement, AC#3's ladder tests, and AC#6's exact-match cent-level reconciliation are all
  concrete and machine-checkable. −3 because AC#6 cannot be exercised until AUD-04 ships (a real,
  named cross-plan dependency, not softened), and AC#1/#3 need multi-night acceptance windows.
- Autonomous operation, failure handling, recovery (15): **13** — the re-alert ladder closes the
  round-2 MATERIAL gap in full, sharing an identical specification with AUD-04 so the two controls
  cannot drift apart; restart-surviving latch and one-way escalation both verified in the shared
  spec. −2 because every rung still depends on the nightly timer firing at all, a limitation the
  plan states honestly but does not close.
- Portfolio objective alignment, scope and dependencies (10): **10** — §11 states the measured
  structural ceiling (Rev 2 §0's near-zero recovery), a field-level path into AUD-04 with a standing
  cross-check, a numeric baseline and a falsifier, and flatly concedes this item changes ROI not at
  all today. Per the brief's rule, round 2's disposition #5 (no named defect) is resolved: I find no
  separate defect in §11 itself, so full marks are awarded, matching the round-2 pm score.

**Total: 87/100**

## Required changes to reach 100

1. Resolve finding B (the step-0/current-nightly-artefact drift) with the reconciled table and
   stated provenance, as already planned for step 6 — this is a plan-execution gap, not a plan-text
   gap, but it caps the achievable score until closed.
2. Mark `pm_us_crh_exit_v4.json`'s `taker_fee_coefficient` as provisional/`TBD_AT_REGISTRATION` (or
   explicitly pin it to today's live `0.0695` with a stated re-verification requirement at actual
   registration time), so a future reader cannot mistake a pre-registration placeholder for a
   registered value.
3. State explicitly in §7 step 0 which of C2/C3's two branches is expected to be specified at finer
   grain, or add the missing detail to the path-defect branch so both branches are specified at
   parity.

## Blockers

BLOCKER-1 (corpus growth, depends on trading resuming), BLOCKER-2 (operator + PREREG v4
registration and the 1-lot positive control — operator-only, no reviewer may resolve) and BLOCKER-3
(inherits AUD-06a's boundary conclusions) remain open, exactly as the plan's own §12 states. None of
the findings in this review require a new blocker.
