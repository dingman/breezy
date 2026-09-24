# AUD-19 — round 3 — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 445efcad5d40e1d33b8a2766a3789d185d5a33108080d7e9982db83d3dba87d9
Reviewer: silent-failure-hunter (blind, independent)

## Round-2 findings — verified fixed
1. **"AUD-09 is CLOSED" (MATERIAL)** — FIXED. All 5 sites (§4, §5, §6 E-header, §9, §13's round-2
   entry) now say AUD-09's document is not edited, without the false CLOSED claim, and state it is
   "a planning document, not built code: its section and line anchors can move." New **step 22-pre**
   (§7) is a mandatory re-verification of every cited AUD-09 section (§6b.2 items 1/3, §6b.3, §7 step
   8, §8 B16/B17/B18) against the then-current AUD-09 doc **and** the built `replay_daily_runner.py`,
   refusing on any field/key/test-name discrepancy; sections are now the primary anchor, `:line`s
   secondary. New **A16**. Directly closes the citation-drift risk I raised.
2. **argv_sha256 single implementation (MINOR)** — FIXED. New `scripts/analysis/argv_digest.py`,
   stdlib-only, `argv_sha256(argv) -> str`, imported by driver and runner via the sibling-import
   convention — verified at `current_rung_hold_paper_replay.py:45` (`sys.path.insert`) and `:47`
   (`from archive_correction_probe import wilson_interval`, the same pattern). Order/change-
   sensitivity test (step 18) and a driver↔runner round-trip test (step 22, `test_the_runner_and_
   driver_agree_on_argv_sha256`). A15. No import-linter contract over `scripts/` — reconfirmed
   (`pyproject.toml:71-92`, `containers = ["breezy"]` only).

## Architect's finding — verified
- E2 now names the AUD-09 §7 step 8 sub-assertion it supersedes explicitly. Verified against source:
  AUD-09 `:799-801` reads verbatim "`engine_params_source="DRIVER_DEFAULTS"`, and `params_match=False`
  for today's manifest (B16)" — matches the plan's citation exactly. The supersession is justified
  (E1 makes `--family-manifest` unconditional in the deployed runner, so the DRIVER_DEFAULTS path
  the old assertion pinned can no longer occur) and the retained negative — refused/missing/
  mismatched manifest or sidecar → `BLOCKED`, never `DRIVER_DEFAULTS` — is stated and tested (E3,
  step 22's `test_a_missing_or_mismatched_sidecar_yields_a_BLOCKED_row`). This is a value-pin update
  tied to a stated behavioural cause, not a weakened safety/contract assertion: every other AUD-09
  step-8 assertion (target selection, crash recovery, H0, stall escalation, `validity`) is stated
  untouched.

## Sweep for new defects
None found. `argv_sha256`'s definition is now pinned to "the arguments after the script path, in the
order passed" (raw `sys.argv[1:]`, not a re-sorted/canonicalized form), closing the driver/runner
representation-drift risk from round 2. Step 22-pre's refusal condition and A16's evidence are both
concrete and checkable. No new silent-fallback, no new untested consumer.

## Per-criterion (cap)
Fidelity 19/20 · Technical correctness 19/20 · Implementation specificity 14/15 ·
Acceptance criteria 19/20 · Autonomous operation/failure handling 14/15 · Portfolio alignment 9/10.
**Total: 94/100.**

## Blockers
None. No MATERIAL defect remains from this reviewer's lens.

## Scoring reconciliation (post-report)

Re-examined each withheld point against the current plan text; named a concrete defect or restored
the point, per instruction.

- **Fidelity 19→20/20.** Withheld point cited "G-06/G-07 read via the ruling's quotations, not
  end-to-end in the audit" — that is a note about verification method, not a defect in the plan's
  text or coverage of the gap. No concrete defect found. **Restored: 20/20.**
- **Technical correctness 19→20/20.** Withheld point cited `pm_us_crh_v4.json:13`'s θ as "relied on
  from the ruling, not re-read." Re-read directly: `taker_fee_coefficient: "0.0695"` is present on
  disk (verified this round), matching every citation in the plan. No refuted claim found anywhere
  in the plan. **Restored: 20/20.**
- **Implementation specificity 14→15/15.** Withheld point cited 19c's line numbers being uncitable
  against a not-yet-built module. This is inherent (the module doesn't exist) and is exactly what
  step 22-pre exists to mitigate (section-primary citation + mandatory re-verification before code).
  A genuinely inapplicable criterion, not a defect. **Restored: 15/15.**
- **Acceptance criteria 19/20 — KEPT, defect renamed and sharpened.** New concrete defect found on
  re-sweep: **§6 E3** maps *every* non-zero driver exit to `record_blocked(...)` ("day stays
  queued"), with no exception. AUD-09 §9 (`:893-895`, verified) is explicit that specific driver
  exceptions — `NoDecisionWindowCoverageError`, `EntryAskFromLatchMissingError`,
  `ImpossibleFillPriceError` — must produce `outcome="FAILED"` (**the day leaves the queue**), not
  `BLOCKED`; only `ASOS_CACHE_EMPTY`-class refusals and argument/manifest refusals stay queued. As
  written, E3 would route a genuine engine crash (e.g. `ImpossibleFillPriceError`, which AUD-09
  explicitly says "must never be swallowed") into the same permanently-requeued `BLOCKED` bucket as
  a config refusal — reproducing exactly the permanent-silent-stall shape memory N3 and AUD-09's own
  crash-recovery design (`:650-657`) were built to eliminate. **Required change:** §6 E3 must
  distinguish "argument/manifest/sidecar refusal, pre-engine" (→ `BLOCKED`, day stays queued) from
  "driver raised one of AUD-09's named FAILED-class exceptions" (→ `FAILED`, day leaves queue, per
  AUD-09's existing exception-type dispatch), and step 22 needs a RED test asserting a driver crash
  from this set is never misclassified as `BLOCKED`. A14 must be extended to cover it. **19/20.**
- **Autonomous operation/failure handling 14→14/15 — KEPT, same defect.** Identical root cause: E3's
  blanket non-zero-exit → BLOCKED mapping is a genuine failure-handling gap, not a deliberate,
  justified design choice (unlike the exit-code-vocabulary point I previously (and vaguely) cited,
  which is inapplicable — AUD-09 already dispatches on exception type, not exit code, so no new
  vocabulary is needed; 19c only has to route into AUD-09's existing dispatch correctly, and
  currently does not). **14/15.**
- **Portfolio alignment 9→10/10.** Withheld point cited "large scope, 19c reaches into a sibling
  item's module" as a weakness. The plan already justifies this concretely: ownership is assigned by
  ruling Q1 item 7 (unowned gap), 19c is blocked on AUD-09b's runner existing, AUD-09's document is
  never edited, and dependencies are stated by id throughout §4/§12. No further concrete defect
  distinct from what the plan already discloses and justifies. **Restored: 10/10.**

**Reconciled total: 20 + 20 + 15 + 19 + 14 + 10 = 98/100.**
