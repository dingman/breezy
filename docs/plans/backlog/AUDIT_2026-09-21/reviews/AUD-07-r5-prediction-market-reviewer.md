# AUD-07 — Round 5 (delta, post-ruling) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
sha256: d1d74b39caf8910d6be6473b28829489fd3ad239f2c998707bf1814d59599cc7
Round: 5 (delta, post-ruling)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Citations verified against source

- `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md` exists exactly as cited: `Status:
  DRAFT_NOT_REGISTERED (2026-09-16). D0 unpinned.` at `:3`, `d0_climate_day | UNPINNED` at `:20`,
  boundary re-run-and-pin instruction at `:116` ("Re-run `crh_group_sequential_boundaries.py` at
  registration and pin the resulting `inputs_sha256`") — CONFIRMED, so step 7b's framing ("the DRAFT
  already exists; what's missing is provenance") is accurate, not inflated.
- `exit_gate.py:55` `_EXIT_RULE_REGISTERED_FAMILIES` and the class-scoped 09-16 ruling text are
  consistent with what I verified in earlier rounds of this plan.
- `POSITION_EXIT_EXECUTION_2026-09-16.md:322-328` ("If the preview cannot distinguish reducing from
  opening, this step is NOT retired and step 3 stays blocked") is quoted and used correctly as the
  conservative guard on the positive control's sequencing.
- `OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118` ("operator residue is one command … No UI clicks,
  no hand-placed order… assigns none of" the reserved controls) supports the reclassification of the
  positive control as bot-automated rather than an operator gate.

## The cross-item fact the coordinator asked me to check: the shared family halt

Verified from source, not from the plan's own text (which never mentions it):

- `FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"` (`trial_day_latch.py:291`) — a single,
  **literal, non-family-parameterized** key. `is_family_halted()` reads it at `:1002-1015`.
- `submit_exit` (`src/breezy/strategy/current_rung_hold/exit_wiring.py`, def `:245`) checks
  `strategy._latch.is_family_halted()` at `:270` and refuses (returns without submitting) at
  `:271-275` — its own docstring states this explicitly: "Family-halt veto FIRST … an exit competes
  for the SAME durable halt an entry does, so a family halted for ANY reason … never submits another
  order of either kind."
- `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (ENDORSED) confirms this halt is
  **sender-global under the node's cardinality-1 design**: "halted is GLOBAL-equivalent to this
  node's only sender is halted… **no matter which literal family id currently occupies that slot**."

**Consequence, not stated anywhere in AUD-07:** once AUD-02b's set-halt CLI runs against
`pm_us_crh_v4` (which A1 requires), the SAME literal `FAMILY_HALT_KEY` is what `pm_us_crh_exit_v4`'s
own `submit_exit`/entry veto would read if and when it ever occupies the node's sender slot — the key
is not scoped to the family that set it. A halt left set against `pm_us_crh_v4` would silently block
`pm_us_crh_exit_v4` from sending **any** order, including the 1-lot positive control this plan's own
arming path depends on, unless the halt is explicitly cleared first via
`clear_family_halt_cli.py`. AUD-07's revision-5 "authorisation chain" (§5, addendum A3) states that
live-trading enablement is operator-only and that the 09-16 ruling is class-scoped, but never checks
or states this halt-state precondition — a gap that sits exactly in the section whose job is to name
everything the arming decision needs.

## Defects

1. **MATERIAL — the plan's authorisation-chain and dependency sections never address the shared,
   sender-global `FAMILY_HALT_KEY`.** If `pm_us_crh_v4`'s halt is set (per the A1 ruling, via
   AUD-02b) and never cleared before `pm_us_crh_exit_v4` is registered and takes the node's sender
   slot, the positive control this plan's whole arming path culminates in would be silently refused
   at the exec veto — indistinguishable, without this fact stated, from a bug in the positive control
   itself rather than an inherited safety state. This is precisely the kind of interaction AUD-07's
   own §5/§12 "what the arming decision requires" sections exist to enumerate, and it is missing.
   **Required change:** add to §5 (or §12, as a new DEP) an explicit statement that the shared
   `FAMILY_HALT_KEY` (`trial_day_latch.py:291`, read by `exit_wiring.py:270-275` for both entries and
   exits) must be verified CLEAR — or explicitly cleared via `clear_family_halt_cli.py` — before the
   1-lot positive control runs, since a halt set against `pm_us_crh_v4` under A1 is sender-global, not
   family-scoped, and would otherwise silently block `pm_us_crh_exit_v4` too. Add a RED test (or a
   step-0-style evidence check ahead of §4 step 3) asserting the halt state is read and reported
   before the positive control is attempted.

## Regression sweep

- The other four RULING 3 / addendum A3 consequences (PRECONDITION-1 reclassification, DEP-2/DEP-3
  downgrades, the authorisation-chain statement, the "no arming timeline" honesty) are each
  accurately applied and consistent with the ruling text, independently re-read above.
- `exit_gate.py`'s empty-diff invariant and "no registration, no positive control, no enablement" are
  correctly restated and unaffected by this finding.
- No operator-reserved value is read, restated, defaulted or assigned anywhere in this revision.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **17** — the ruling's reclassifications are applied
  faithfully and the DRAFT-spec provenance work is real, checkable work rather than restating the
  ruling. −3 for the missing halt-state precondition, which is squarely inside this plan's own
  "authorisation chain" charter.
- Technical correctness and evidence grounding (20): **17** — every cited line (the DRAFT spec, the
  ruling text, the bot-positive-control precedent) re-verified exact. −3 for the same gap: a
  verifiable, source-confirmed fact about the exact mechanism this plan's positive control depends on
  is absent.
- Implementation specificity and feasibility (15): **13** — step 7b's provenance table and dated
  attestation are concretely specified and mechanically checkable. −2: no step or test names the
  halt-clear precondition, so an implementer following this plan to the positive control could hit an
  unexplained refusal.
- Acceptance criteria and validation quality (20): **18** — AC #8b's dated-provenance check is
  objectively verifiable and the existing negative criteria (AC #9) are correctly widened. −2: no
  criterion requires the halt state to be checked/reported before the positive control.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this finding; the
  ladder-based detectors and registration package remain sound.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the reclassifications
  correctly narrow what blocks this item without overclaiming readiness for arming.

**Total: 90/100**

## Required changes to reach 100

1. State the shared `FAMILY_HALT_KEY` precondition explicitly in §5/§12 and add a test or evidence
   step that checks/reports its state before the positive control is attempted, as detailed above.

## Blockers

- **PRECONDITION-1** — corpus growth; unavailable evidence, gates the arming decision only.
- **DEP-2** — PREREG v4 registration + the (now bot-automated) positive control; sequencing, not
  operator-only except for live-trading enablement itself.
- **DEP-3** — AUD-06a's boundary conclusion; gates registration only.
- **New, named by this review, not yet a formal blocker id:** the shared family-halt clear state is a
  precondition of the positive control specifically; it is build-side and closable by the required
  change above, not an operator ruling.
