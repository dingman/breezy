# AUD-19 round 3 review — trading-bot-architect

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: 445efcad5d40e1d33b8a2766a3789d185d5a33108080d7e9982db83d3dba87d9
Round: 3

## Round-2 MATERIAL: verified fixed
§6 E2 confirmed against source at `AUD-09-scheduled-per-station-replay.md:799-801` (the plan's cited
line, not my round-2 `:798-800` — off-by-one on my side, now corrected): the exact assertion
`engine_params_source="DRIVER_DEFAULTS"`, `params_match=False` "for today's manifest" is there. E2
names it, states the supersession reason (E1's unconditional flag), gives the replacement
(`FAMILY_MANIFEST`/`True` + retained BLOCKED negative), and lists untouched assertions. Correctly
framed as a value-pin supersession, not a weakened test. FIXED.

## Sweep of other round-3 edits
- "AUD-09 is CLOSED" removed from all 5 sites, replaced by mandatory **step 22-pre** re-verification
  (section-primary, line-secondary, refuse-on-discrepancy) — sound risk control for a plan-document
  dependency with a not-yet-built module; A16 evidence is appropriately a recorded note, not a test.
- `scripts/analysis/argv_digest.py`: citations verified — `current_rung_hold_paper_replay.py:45`
  (`sys.path.insert`) and `:47` (`from archive_correction_probe import wilson_interval`) both exact
  match; file correctly does not exist yet (plan-stage). Single-implementation constraint (A15,
  order/change-sensitivity + driver↔runner round-trip test) closes a real duplicate-hash-drift risk.
  No import-linter concern: confirmed no `breezy` import, `scripts/` ungoverned.

## Scoring reconciliation (coordinator-requested)
Re-examined every withheld point against current plan text; named a defect or restored the point.

- **Fidelity 19→20/20, RESTORED.** Prior note ("G-06/G-07 read via the ruling's quotations, not the
  audit itself") re-checked against `docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:59-63` directly
  this round: both entries are 3-4 line summaries; the plan's citations already capture their full
  substantive content. No additional gap found — restored, no defect nameable.
- **Correctness: 20/20, unchanged.** No new refuted claim found this round.
- **Specificity 14→15/15, RESTORED.** Prior note (can't cite runner line numbers pre-build) is a
  **dependency**, not a defect: 19c is explicitly gated on AUD-09b's runner existing (§4, §1), and
  step 22-pre exists precisely to re-verify anchors once it does. Nothing in the plan's control.
- **Acceptance criteria: 19/20, 1 point withheld, NAMED.** §8 **A16**'s evidence is "the
  re-verification note appended to §13, dated, naming each section checked" — a manually-authored
  note, not a machine-checkable artifact, unlike every other criterion in the table (RED→GREEN output,
  `git diff --stat`, grep counts). Nothing forces step 22-pre to actually run before 19c's code is
  written, or catches a note that was back-filled after the fact. **Required change:** A16's evidence
  should be (or additionally require) an automated pre-flight check — e.g. a script/test in 19c's
  own test file that fails CI unless a step-22-pre marker/commit exists, or that itself re-imports
  and asserts against AUD-09's cited anchors programmatically — not a prose note alone.
- **Autonomous ops: 13/15, 2 points withheld, NAMED (carried from round 1, still true).** §9 and §6
  C4/E3 give every refusal as a raise-and-exit with a message, but define no exit-code vocabulary
  across 19a/19b/19c. A scheduler (AUD-09's runner, and later callers) can distinguish a refusal from
  a crash only by parsing stderr text, which is fragile automation practice and contradicts the
  plan's own "loud, unambiguous" framing for autonomous operation. **Required change:** define at
  least two distinct exit codes (e.g., a validation/refusal code for `FamilyManifestArgumentError`
  and friends vs. an unhandled-exception code), documented once in §6 and asserted by one test per
  increment.
- **Portfolio alignment: 7→9/10, 1 point withheld, NAMED (2 restored).** Two prior sub-reasons
  re-examined: (a) "three increments, seven files is large scope" and "19c reaches into a sibling
  item's module" — coordinator correctly flags these as inherent to the ruling's own ownership
  assignment (Q4 item 1, Q1 item 7) and the sequencing is a stated **dependency** (§4: "blocked
  additionally on AUD-09b's runner existing... a sequencing dependency... not a scope claim"), not a
  design defect — **restored, no defect nameable**. (b) One concrete, still-present defect: **§4's
  "Priority: P2" bullet** reads "nothing live depends on either increment; but two scheduled items
  are inert without 19b, and both increments are small" — stale from when the item had two
  increments; it now has three (19a/19b/19c, §1) and the wording ("either", "both") no longer
  matches the item's own structure. **Required change:** update §4's first bullet to "any increment"
  /"all three increments" (or equivalent), consistent with §1's three-increment structure.

## Per-criterion points (final)
- Fidelity to audit gap and completeness: 20/20
- Technical correctness and evidence grounding: 20/20
- Implementation specificity and feasibility: 15/15
- Acceptance criteria and validation quality: 19/20
- Autonomous operation, failure handling and recovery: 13/15
- Portfolio objective alignment, scope and dependencies: 9/10

**Total: 96/100**

## Blockers
None.
