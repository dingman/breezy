# AUD-06a — Round 4 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md
sha256: b6073c0602f07c08176ee54287a13422a76b1f63d71a6795c2e3b503cc2c601c
Round: 4 (final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claims verified against source/plan text

- **320-cell grid.** Plan text (§6 compute-budget subsection) states `5 q_max × 8 dispersion
  sub-cells × 8 ADMISSIBLE (k, side_mix) pairs = 320 cells`, with `mixed` explicitly excluded at
  `k=1` (undefined, not silently sampled as all-YES). CONFIRMED present in the plan body.
- **Calibration step instead of an invented wall-time number.** Step 4a: a single-cell timed
  calibration at the reference cell (`q_max=3`, `two-point`, `k=2`, `mixed`) publishing `τ_cell` and
  peak RSS, projecting `320 × τ_cell`, with a 6-wall-hour gate that triggers chunking and never
  reduces the registered 20000-rep count — CONFIRMED present in the plan body at the cited lines
  (`τ_cell`, "6-wall-hour", chunked/resumable `--cells FROM:TO`, per-cell seeding
  `20260921_000 + cell_index`).
- **Threshold provenance stated explicitly.** The `ρ ≥ 0.70` / permutation `p < 0.01` thresholds are
  labelled "reasoned build-side defaults ... NOT inherited" in the plan body (§6, not only §13),
  contrasted against the three quantities anchored to the amendment's own figures.

Both of round 3's required changes are genuinely implemented in the plan body, not merely asserted in
§13.

## Reconciliation (per coordinator instruction)

Re-examined every remaining deduction from my initial round-4 pass against the brief's rule: a
deduction stands only if tied to a named defect AND a text-level required change; a shortfall no
change to *this plan's own text* could fix (an execution-only measurement, another item's scope, an
operator/strategy-lead ruling) is a note/blocker, not a deduction.

1. **`max_equity_fraction` (G-11) — KEPT as a MINOR, text-fixable defect.** AUD-06a's own §2
   ("Source finding and class") explicitly imports this element of G-11 into its own source-finding
   text ("`weather_common/equity.py`'s `max_equity_fraction` is unused by the live family"), which
   creates an expectation that the plan states its disposition. §5 ("Scope and explicit exclusions")
   only excludes "sizing code" generically ("`order_quantity` stays 1 ... That is AUD-06b") and never
   names `max_equity_fraction` specifically or cites AUD-06b's actual disposition of it (verified:
   AUD-06b §12 carries a DECISION — not adopted this increment, with a named re-evaluation trigger
   tied to AUD-04's balance-semantics finding). A reader checking G-11 element-by-element against
   this plan has to infer the mapping rather than read it. **This is genuinely fixable by a one-clause
   text addition and is kept as a deduction**, unlike the items below.
   **Required change:** add one sentence to §5 naming `max_equity_fraction` specifically as excluded
   from this item, and cross-referencing AUD-06b §12's DECISION (with its re-evaluation trigger) as
   the disposition of that specific G-11 element — so the mapping is explicit rather than inferred
   from the generic sizing exclusion.

2. **"The mechanism remains a hypothesis until step 4 runs" — RECONCILED, AWARDED BACK (was −1 in
   Technical correctness).** This is a measurement only the sweep's execution can settle; §6/§7 name
   the exact test (Spearman `ρ`, permutation `p`, a machine-checkable three-outcome verdict incl.
   `INDETERMINATE`) that will settle it once run. No further plan text narrows this. Falls under the
   brief's carve-out ("steps that can only be evidenced after execution"). Not a deduction.

3. **"Cannot itself enforce that AUD-06b evaluates the staleness predicate every cycle" — RECONCILED,
   AWARDED BACK (was −1 in Autonomous operation).** This item ships a fail-closed
   `envelope_is_stale(...)` predicate; whether the CONSUMER calls it every cycle is AUD-06b's scope
   and is independently verified there (`test_sizing_refuses_when_the_envelope_is_stale`, checked in
   my AUD-06b review). Duplicating an enforcement requirement here would create a second
   specification of the same rule — the failure mode this backlog penalises elsewhere. Falls under
   the brief's carve-out ("another item's scope"). Not a deduction.

4. **"AC #9's budget figures are produced by the run itself rather than checkable beforehand" — was
   already reconciled to full marks in my initial pass; re-confirmed here.** Inherent to any
   measured-budget criterion; not a text-fixable gap.

## Defects

- **MINOR** (kept): §5 does not explicitly name `max_equity_fraction` as an excluded, cross-referenced
  element of G-11. Required change stated above.

No MATERIAL defect found.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **19** — R-11/G-11's `Var(S)` blocker fully addressed
  against the codebase's own recorded mechanism, over the station-day shapes (including `side_mix`)
  the envelope will actually be applied to, with the grid enumerated rather than estimated. −1 for
  the kept MINOR defect above (the `max_equity_fraction` scope-mapping gap).
- Technical correctness and evidence grounding (20): **20** — every formula, line reference and sign
  argument re-verified; the `(k=1, mixed)` exclusion is a genuine admissibility fix, not a cost trim;
  reps/CI/tolerance remain anchored to the amendment's own registered figures. The "hypothesis until
  step 4 runs" property is execution-gated, not a text defect (reconciled above) — full marks.
- Implementation specificity and feasibility (15): **15** — reps, CI, seeds, tolerance, all three
  dispersion classes, the `side_mix` axis, the verdict statistic, cell ordering, chunk interface,
  JSONL resume protocol and the memory contract are all pinned; the wall-time projection is scheduled
  by a calibration step rather than guessed.
- Acceptance criteria and validation quality (20): **20** — reproduce-first gate, a computed
  three-outcome verdict that also stops the item, an honest empty-envelope branch, a `side_mix`-aware
  publication rule, a measured-budget criterion (AC #9) and a threshold-provenance criterion (AC #10).
- Autonomous operation, failure handling, recovery (15): **15** — correctly forbids a standing timer;
  the staleness predicate is fail-closed at its one real consumer and ships tested; the run is
  resumable so a host kill costs at most one cell. The cross-item enforcement question is AUD-06b's
  scope (reconciled above) — full marks.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's enabling chain, numeric
  baseline, explicit decline of any ROI claim and falsifier are concrete; no operator-reserved value
  enters the analysis anywhere in this revision.

**Total: 99/100**

## Required changes to reach 100

1. Add one sentence to §5 naming `max_equity_fraction` specifically as an excluded G-11 element,
   cross-referenced to AUD-06b §12's DECISION and re-evaluation trigger as its disposition.

## Blockers / notes (not scored as deductions)

- **Note:** the `Var(S)` mechanism itself is a hypothesis until step 4's sweep actually runs — the
  plan already states this honestly (§6, §9); no ruling or plan-text change can resolve it, only
  execution.
- **Note:** enforcement that AUD-06b evaluates the staleness predicate on every sizing cycle is
  AUD-06b's scope, independently verified in that item's own test suite.

No operator or strategy-lead ruling is required for this item's own scope.
