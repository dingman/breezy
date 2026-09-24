# AUD-07 review — round 6 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: 911f5b8bf978a3a7f4ee69c68bedb0148b45c80bc4f84352dd6365f1b4b3da3f
Round: 6 (delta review of the round-5 mle MATERIAL plus the round-5 pm MATERIAL)

## Chronology independently re-verified via read-only `git log`/`git show --stat`, all exact

- `ebe7c46` 2026-09-16T03:00:51Z — Rev 2 design doc. `bdcfd38` T03:06:57Z — PREREG v4 DRAFT created.
  `7c558a5` T03:24:56Z — pre-anchor edit. `84d9042` T03:36:32Z — "Appendix A.3 — exit-window study
  result (R-DEAD 0/5 fillable, R-THREAT 1/5...)" = the first commit reporting an outcome reading over
  this corpus. `537783a` T05:52:43Z — §5.4/§5b two-layer cover, touching BOTH files, POSTDATES the
  anchor. All five timestamps and titles CONFIRMED exact against `git show -s --format`.
- **Full commit history for both files independently pulled** (`git log --follow`): confirms `537783a`
  is the LAST commit touching either the DRAFT spec or the design doc — nothing postdates it, so
  nothing else was missed downstream.
- **One additional commit found between the anchor and `537783a`:** `d0bd8b2` (T03:46:32Z, "Appendix
  A.3 corrected — leg-correct study..."). Read in full: it corrects a settlement-inference sign bug in
  the SAME exit-window study reading (the MIA NO-leg pnl sign, `+0.91` → `−0.09`; R-DEAD/R-THREAT
  counts unchanged) and does **not** touch the DRAFT spec at all. This is a refinement of the same
  outcome event, not a new design-provenance source — it does not need its own row, and using the
  **earlier** `84d9042` timestamp as the anchor (rather than the corrected `03:46:32Z`) is the more
  conservative choice: the earliest point a human could have seen *any* R-DEAD/R-THREAT reading (even
  buggy) is what matters for no-peeking, and using the later, corrected timestamp would have let more
  provenance slip through as falsely "pre-anchor." The chosen anchor is right.

## Remedy judged honest, not an unfalsifiable attestation

The `PROVENANCE_POSTDATES_READOUT` remedy (re-derive from pre-anchor inputs and re-cite, OR an
explicit ruling artefact — with the flagged rows' cost bounded because `n` resets to 0 at registration
regardless) is falsifiable: both paths are independently checkable (a new citation is itself
date-tested against the same anchor; a ruling artefact either exists or doesn't), and the "acceptable
without re-deriving" cost is tied to an already-independently-verified structural fact (the `n`-reset
rule, confirmed in earlier rounds), not a new promise this item invents. The one row known to be
flagged today (`537783a`, §5b's AMBIGUOUS-exit cover) is named, not hidden, and a dedicated test drives
the check off that real row rather than an empty/synthetic fixture.

## PRECONDITION-2 (halt-state) citations independently re-verified, all exact

`FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"` at `trial_day_latch.py:291`;
`is_family_halted` def at `:1002`; `continuous_family_halt_key` def at
`trade_supervisor_core.py:158`, docstring confirms "Returns ... regardless of the argument" and the
cardinality-1 "GLOBAL-equivalent" language quoted verbatim; `submit_exit` def at
`exit_wiring.py:246`, `is_family_halted()` veto check at `:270`. The design is sound: a read-only
precondition check (§5 step (0), §7 step 7c) that blocks no step of this item (which sends nothing),
correctly routes a set halt to `BLOCKED_FAMILY_HALT_SET` rather than a false control failure, and
names the existing clear→act→re-set route by id rather than inventing a bypass.

## Regression sweep

AC numbering (`8`, `8b`, `8c`, `9` — no collision), the five new §7 step 7b RED tests correctly include
both the anti-regression test (fails a `corpus_first_fill_date` implementation) and the live-data test
(driven off the real `537783a` row) the coordinator asked about, and no existing citation or test was
weakened. No other regression found.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — both round-5 MATERIALs fully closed.
- Technical correctness and evidence grounding (20): **20** — chronology independently re-derived from
  git and confirmed exact, including verifying nothing else was missed; the anchor choice is not just
  correct but demonstrably the conservative one.
- Implementation specificity and feasibility (15): **15** — the provenance table's new schema
  (`doc:line`, introducing-commit timestamp, `ATTESTED`/`PROVENANCE_POSTDATES_READOUT` status) and the
  halt-state precondition are both concretely specified.
- Acceptance criteria and validation quality (20): **20** — AC #8b/#8c are objectively testable, with
  a test set that specifically targets the regression class this round fixes.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; PRECONDITION-2 makes
  the arming path's honesty more complete, not less.

**Total: 100/100**

## Remaining defects and required changes

None found this round.

## Blockers / preconditions (not deductions)

- **PRECONDITION-1:** corpus growth/arming decision depend on a future family trading.
- **PRECONDITION-2 (new):** the sender-global family halt, set for the entry family under RULING_A1,
  would also veto the exit family's positive control — named, not a blocker of this item's own fixes.
- **DEP-2/DEP-3:** registration and its boundary-conclusion sequencing, per RULING 3.
- Live-trading enablement of `pm_us_crh_exit_v4` remains operator-only (addendum A3).
