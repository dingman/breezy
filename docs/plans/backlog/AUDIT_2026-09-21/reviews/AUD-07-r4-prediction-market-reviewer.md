# AUD-07 — Round 4 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
sha256: 980762dcee265c8e5973a61b1afe734d77cac84fa045b8cb6cdb2d7f36190acf
Round: 4 (final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claim verified against source: `taker_fee_coefficient` read from the manifest at run time

- `load_family_manifest` validates `taker_fee_coefficient` against `_TAKER_FEE_COEFFICIENT_RE` (a
  leading `0.` plus 1-6 decimal digits) then `0 < θ < 1`, at `src/breezy/persistence/
  family_manifest.py` — CONFIRMED verbatim. The key is in `_REQUIRED_KEYS`/`_STRING_FIELDS` and the
  allowed-key set is closed — CONFIRMED, so round 3's two rejected remedies
  (`"TBD_AT_REGISTRATION"`; an extra provenance key) would indeed make the manifest unloadable or be
  refused.
- `src/breezy/app/trade.py:239` and `:285` both pass `required_fee_coefficient=
  manifest.taker_fee_coefficient` — CONFIRMED verbatim at both sites. The plan states no coefficient
  value anywhere in its own text; the consumer genuinely reads it from the manifest at run time.
- The adopted remedy (a provisional decimal read at write time from the live fee source the node
  itself asserts against) is the only option of the three considered that is both loadable and not a
  stale re-pin of the kind that produced the 09-17 fee drift. **CONFIRMED sound.**

## Reconciliation (per coordinator instruction)

Re-examined every remaining deduction from my initial round-4 pass against the brief's rule: a
deduction stands only if tied to a named defect AND a text-level required change; a shortfall no
change to *this plan's own text* could fix (an execution-only measurement, another item's scope, an
operator/strategy-lead ruling) is a note/blocker, not a deduction. I re-read §3, §6, §7 and §12 in
full for a genuine remaining defect before reconciling each point — not merely reflexively awarding
them.

1. **Fidelity −2 ("G-12's literal ask ... answered by explaining why arming stays out of reach
   rather than narrowing the distance to it") — RECONCILED, AWARDED BACK.** Checked §3 required (v)
   and §6 finding A: the registration package is fully specified as *completed* work — real artefacts
   minted, `inputs_sha256` pinned, `composition_kind` corrected, the `exit_rule` key added — with
   `status` and `d0_climate_day` deliberately left as placeholders because "registration is the
   arming decision's act, not this item's." There is no further buildable step this item's own text
   is leaving undone; the remaining distance to arming is BLOCKER-2 (operator + PREREG v4
   registration), which is operator-only by the repo's own binding contract. The deduction held this
   item to a bar (narrowing distance to an operator-gated act) beyond both G-12's verdict statement
   and this item's own stated charter ("This plan does not arm anything"). Falls under the brief's
   carve-out (a ruling). Not a deduction.

2. **Technical correctness −1 (Finding B, three hypotheses pending step 6) — RECONCILED, AWARDED
   BACK.** §12 already names this explicitly: "Unresolved until step 6: the cause of the study drift
   (finding B). Three candidates are named; the measurement decides." §6 B2 gives a concrete,
   already-specified closing check (per-row `delta_i` classification, two RED tests through the real
   writer path, a stated gate-reading consequence) — the *test* exists in text; only running it can
   answer which hypothesis holds. Falls under the brief's carve-out (execution-only evidence). Not a
   deduction.

3. **Implementation specificity −2 (C2/C3 branch asymmetry "declared not removed"; ladder sequenced
   against a module AUD-04 has not shipped) — RECONCILED, AWARDED BACK, both sub-reasons.**
   Re-read §7 step 0: branch (a) is deliberately specified at finer grain because it is the
   evidence-favoured branch (the two path derivations, node-side and wrapper-side, agree by
   construction); branch (b) is deliberately specified only to "name the divergent path and
   permission bits, then re-scope" because, in the plan's own words, "a path/permission defect cannot
   be designed against before it is found." Designing branch (b) to parity before step 0 runs would
   mean guessing at an unknown defect's shape — not achievable by this plan's text. The AUD-04 module
   dependency is explicitly another item's scope (the ladder is imported, not re-implemented, with a
   ship-order contingency already specified in §6 body for AUD-07 landing first — verified present,
   not only in §13). Both sub-reasons are carve-outs (execution-gated design; cross-plan scope). Not a
   deduction.

4. **Acceptance criteria −3 (AC #6 needs AUD-04 to ship; AC #1/#3 need multi-night windows) —
   RECONCILED, AWARDED BACK.** Both are named, real cross-plan/execution-time dependencies, not
   softened criteria — AC #6's join-key definition and cent-exactness rule are fully specified now
   (identical on both sides of the AUD-04/AUD-07 reconciliation, verified in AUD-04's own AC #4);
   what remains is AUD-04 shipping and time passing, neither of which this plan's text can supply.
   Carve-out (cross-plan scope; execution-time evidence). Not a deduction.

5. **Autonomous operation −2 ("every rung still depends on the nightly timer firing") — RECONCILED,
   AWARDED BACK, and flagged as an internal scoring inconsistency.** This is a structural property of
   any scheduled unit (no text change removes a timer's need to fire), named honestly in §9/§12. The
   identical property in AUD-04 (same re-alert ladder, same "the plan states this honestly" framing)
   was scored 15/15 ("Fully met") in that item's round-3 pm review — re-verified by reading that
   record directly. Scoring the same inherent, honestly-disclosed property differently across two
   sibling items in the same cluster is inconsistent; reconciled to match. Not a deduction.

I looked specifically for a genuine remaining defect distinct from the five reconciled above — e.g. a
second co-emission/enforcement gap analogous to what stood in AUD-06b — and found none: the fee-
coefficient write path has no cap-adjacent value to leak, the ladder import is acyclic and verified
in the plan body, and the registration package's `status`/`d0_climate_day` placeholders are correctly
never assigned a value that would let anything fire on them.

## Defects

None MATERIAL, none MINOR remaining after reconciliation.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — extends EXIT-1 rather than duplicating it, surfaces
  four defects the source audit did not name, and completes a registration package honest about what
  it is not (an arming decision). The distance-to-arming property is BLOCKER-2-gated, not a text
  defect.
- Technical correctness and evidence grounding (20): **20** — every load-bearing citation
  re-verified this round (`family_manifest.py`'s closed schema, `trade.py:239`/`:285`'s run-time
  read); Finding B is honestly named as execution-gated in §12 with its closing check already
  specified in §6.
- Implementation specificity and feasibility (15): **15** — the ladder is one imported module with a
  specified ship-order contingency; the fee-coefficient write path, its source and its two RED tests
  are named; the C2/C3 branch asymmetry is a deliberate, reasoned, evidence-favoured disposition, not
  an unspecified gap.
- Acceptance criteria and validation quality (20): **20** — AC #2's independent second read, AC #3's
  ladder tests and AC #6's cent-exact join (identically defined on both sides of the AUD-04/AUD-07
  reconciliation) are concrete and machine-checkable; their unexercisability today is a named
  cross-plan/time dependency, not a softened criterion.
- Autonomous operation, failure handling, recovery (15): **15** — the ladder is restart-surviving,
  one-way-escalating, and single-sourced from AUD-04 so the two mirrored controls cannot drift;
  scored consistently with the identical property in AUD-04's own review.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 states the measured
  structural ceiling, a field-level path into AUD-04 with a standing cross-check, a numeric baseline
  and a falsifier, and flatly concedes this item changes ROI not at all today.

**Total: 100/100**

## Required changes to reach 100

None.

## Blockers / notes (not scored as deductions)

- **BLOCKER-1** — corpus growth, depends on trading resuming (G-01).
- **BLOCKER-2** — operator + PREREG v4 registration and the 1-lot positive control; operator-only, no
  reviewer may resolve. This is the actual gate on "arming or narrowing the distance to it."
- **BLOCKER-3** — inherits AUD-06a's boundary conclusions.
- **Note:** Finding B's root cause (three named hypotheses) and the C3 monitor-flush-vs-path-defect
  cause are both resolvable only by running §7 step 0/step 6 against real data, not by any further
  revision of this plan's text.
- **Note:** the ladder's dependency on AUD-04 shipping `alert_ladder.py` first (or the specified
  inline-plus-cross-test fallback if this item ships first) is a sequencing fact, not a defect in
  either plan.
