# AUD-05 — Round 6 (delta) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
sha256: dfd10527ca5c0805ca9061e20d136eedaa182125045523465ac043f17078f5f6
Round: 6 (delta, final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## What changed (per the supplied diff, verified against current source, not taken on trust)

Revision 5's mechanism ("`side_mix` computed at the call site from the row sequence the stratum was
built from") is withdrawn and replaced with a named carrier field. I re-verified every citation in
the new text directly against `scripts/analysis/family_tally_v2.py`:

- `render_markdown_v2` is defined at `:1025` with signature
  `(tally: FamilyTallyV2, *, source_paths, as_of)` — CONFIRMED exact — and its only argument is the
  already-built `FamilyTallyV2`; it has no access to raw rows.
- `FamilyTallyV2` (`class` at `:261`, fields through `:294`) carries `family_id`, `manifest_sha256`,
  `boundary_inputs_sha256`, `status`, `n_scored`, `n_excluded`, `pooled`, `station_strata`,
  `ask_band_strata`, `looks`, `verdict`, `total_pnl`, `bca_line`, `structural_dead`, then the
  defaulted fields `store_empty_no_sidecar`, `n_residual_excluded`, `residual_scored_contradictions`
  — CONFIRMED: **no rows, no side counts.** Revision 5's mechanism genuinely could not have worked.
- `pooled_rows` is a local of `build_family_tally_v2` (def `:567`), assigned at `:644` — CONFIRMED
  exact — and the `FamilyTallyV2(...)` return is at `:809-827` — CONFIRMED (return statement at
  `:809`, closing paren at `:827`), i.e. the rows are still in scope at construction time, which is
  exactly where the plan now places the new field's computation.
- `main()` builds the tally then calls `render_markdown_v2(tally, source_paths=(args.store_dir,),
  as_of=args.as_of)` at `:1324`, inside the cited `:1312-1325` range — CONFIRMED — the sole handoff
  from build to render is the `FamilyTallyV2` object. This is the fact that makes revision 5's
  mechanism impossible and this revision's fix necessary.
- `_fmt_stratum_row` (`:830-835`) still has no `side_mix` parameter today — CONFIRMED, so the new
  end-to-end test (`test_the_side_mix_label_reaches_the_rendered_report_end_to_end`) is genuinely RED
  on the missing `FamilyTallyV2.pooled_side_mix` carrier, not merely on the formatter argument, as
  the plan claims.
- The two call sites `_fmt_stratum_row(tally.pooled)` and the `(*tally.station_strata,
  *tally.ask_band_strata)` loop are at `:1075`/`:1077` — CONFIRMED exact, matching the new text's
  citations for where `tally.pooled_side_mix`/`strata_side_mix` would be threaded in.

## Regression sweep

- **No other `FamilyTallyV2(...)` construction breaks.** Grepped the full tree: the only two
  constructors are `family_tally_v2.py:809` (production) and `tests/unit/test_family_tally_v2.py:
  1872` (a test helper). The test helper already omits other defaulted fields
  (`n_residual_excluded`, `residual_scored_contradictions`) via the same kw-only-with-defaults
  mechanism, confirming a third defaulted field is safe to add without touching either call site.
- **`FamilyTallyV2` is never serialised.** No `asdict`/JSON dump of the dataclass found anywhere in
  `family_tally_v2.py`; its only consumer is the renderer. The plan's claim that AC #5's byte-identity
  guarantee "lives on the rendered report text, not the dataclass shape" is therefore accurate, and
  adding a defaulted field cannot itself perturb that guarantee.
- **No statistic is touched.** `StratumV2` (`current_rung_hold_v2.py:386-402`) gains no field;
  `build_stratum_v2` is unchanged; `cell_dead` (`family_tally_v2.py:655`) and the `look_verdict`/
  `terminal_look` call sites (`:728`/`:753`/`:792`) read nothing new — re-confirmed against the same
  lines verified in my prior rounds' review of this plan, unchanged by this diff.
- **Test restructuring is a genuine strengthening, not a coverage loss.** The two "isolated formatter"
  tests now call `_fmt_stratum_row(stratum, side_mix="…")` directly, which correctly isolates a
  formatting bug from a plumbing bug; the new end-to-end test is the one that would have caught
  revision 5's actual defect (an unimplementable data-flow) that the isolated tests alone could not.
  No test coverage is removed by the diff, only added and re-labelled.
- **The post-BLOCKER-3 `strata_side_mix` extension is correctly scoped as future, additive work**,
  not shipped now — it is not gated by anything this revision builds, and its positional-indexing
  detail (one entry per element of the combined `(*station_strata, *ask_band_strata)` rendering
  sequence) is consistent with the existing rendering loop's own iteration order. Not scored, since
  it ships only once BLOCKER-3 is ruled and is explicitly named as such.

No new defect found. The plumbing gap the round-5 mle record identified (a real, verified,
unimplementable mechanism) is closed with a concrete, source-grounded, minimal, backward-compatible
fix, and I found no regression it introduces.

## Defects

None MATERIAL, none MINOR.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — unaffected by this diff; G-04 remains fully
  covered and the disclosure mechanism now actually reaches the report.
- Technical correctness and evidence grounding (20): **20** — every citation in the new text
  independently re-verified exact against current source, including the two-function data-flow
  (`build_family_tally_v2` → `FamilyTallyV2` → `render_markdown_v2`) that makes the fix necessary and
  correct.
- Implementation specificity and feasibility (15): **15** — the carrier field, its computation point,
  its default, its threading through the renderer's two call sites, and the additive post-BLOCKER-3
  extension are all concretely named with exact line citations, closing the round-5 gap in full.
- Acceptance criteria and validation quality (20): **20** — AC #13 now requires the end-to-end test
  green, which is the only evidence that the carrier is actually wired rather than merely specified;
  the isolated formatter tests and the all-YES no-annotation guard remain intact.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this diff.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected by this diff.

**Total: 100/100**

## Required changes

None.

## Blockers (named separately, not scored as deductions)

- **BLOCKER-1** — strategy-lead/PREREG ruling on `pm_us_crh_v4`'s `trial_id_prefix` identity.
- **BLOCKER-2** — strategy-lead ruling on whether `pm_us_crh_cont` is retired.
- **BLOCKER-3** — strategy-lead/PREREG ruling on whether NO-side rows may enter
  `station_strata`/`ask_band_strata`; the additive `strata_side_mix` extension named this round is
  the mechanism that will carry the label once this ruling lands, not a substitute for it.
