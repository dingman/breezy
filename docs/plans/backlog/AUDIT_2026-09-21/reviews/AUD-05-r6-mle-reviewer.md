# AUD-05 review — round 6 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: dfd10527ca5c0805ca9061e20d136eedaa182125045523465ac043f17078f5f6
Round: 6 (delta review of the round-5-named defect's fix)

## Fix verification: the `pooled_side_mix` carrier field

Round 5 found that D-A(ii)'s described mechanism ("`side_mix` computed at the call site from the row
sequence") was infeasible at the cited call sites, because `render_markdown_v2` only receives the
already-built `FamilyTallyV2` object, not the raw rows. This revision withdraws that wording and names
the actual data-flow: `FamilyTallyV2` gains one defaulted field, `pooled_side_mix: str = ""`, computed
once inside `build_family_tally_v2` from `pooled_rows` while they are still in scope, and read by the
renderer at the same two call sites.

**Every citation independently re-verified against source, all exact:**
- `build_family_tally_v2` def at `scripts/analysis/family_tally_v2.py:567` — CONFIRMED.
- `render_markdown_v2` def at `:1025`, signature `(tally: FamilyTallyV2, *, source_paths, as_of)`,
  containing both cited call sites — CONFIRMED.
- `pooled_rows = tuple(_stratum_row(t) for t in ordered)` at `:644` — CONFIRMED.
- `FamilyTallyV2`'s `return FamilyTallyV2(...)` statement spans `:809-826` (plan cites `:809-827`,
  within one line of exact) — CONFIRMED, and its existing defaulted, kw-only fields
  (`store_empty_no_sidecar: bool = False`, `n_residual_excluded: int = 0`,
  `residual_scored_contradictions: tuple[str, ...] = ()`) are exactly as cited at `:286-294` — this is
  the proven-safe extension pattern (three prior additive fields on this exact dataclass) the new field
  now follows a fourth time.
- `render_markdown_v2(tally, source_paths=(args.store_dir,), as_of=args.as_of)` called from `main()` at
  `:1325` (plan cites `:1312-1325`, the call falls inside that range) — CONFIRMED.
- `StratumRow.side` documented at `src/breezy/settlement/current_rung_hold_v2.py:99-110` — CONFIRMED,
  `side: Literal["yes","no"] = "yes"` with the exact semantics quoted (leg's own ask/fee, per-side
  `held` truth, no further inversion).
- `FamilyTallyV2` has exactly one caller (`build_family_tally_v2`, confirmed via dependency query) —
  supports the plan's claim that the dataclass is never serialised elsewhere, so the byte-identity
  guarantee genuinely lives on the rendered text, not on the dataclass shape.

**Dataclass mechanics check:** `FamilyTallyV2` is `@dataclass(frozen=True, slots=True, kw_only=True)`.
Appending one more defaulted field after the existing defaulted fields is valid dataclass field
ordering (defaults must trail non-defaults, which this satisfies), and `slots=True` is compatible with
declaring the new field directly in the class body — this is not a novel pattern, it is the same
mechanism already used three times in this class. No mechanical defect.

## Byte-identity claim (AC #5) — verified

The plan's claim that `FamilyTallyV2` is never serialised (so the new field cannot affect any
byte-identity fixture keyed on the dataclass) is supported: only one instantiation site exists
(`build_family_tally_v2`), and the only consumer is `render_markdown_v2`. The `""`/`()` defaults
reproduce today's rendered output exactly on an all-YES corpus (no annotation, no footnote), and every
existing `FamilyTallyV2(...)` construction (including any pinned test fixture) remains valid unchanged
since the new field is keyword-only with a default. No regression found.

## The new end-to-end test — verified sound

`test_the_side_mix_label_reaches_the_rendered_report_end_to_end` drives the real path (rows →
`build_family_tally_v2` → `render_markdown_v2` → asserted report text) rather than exercising
`_fmt_stratum_row` in isolation with `side_mix` pre-supplied, which is exactly what closes the round-5
gap (the three isolated formatter tests proved formatting, not that the renderer could ever produce the
argument). It additionally asserts `tally.pooled_side_mix` directly, which is a sound double-check: it
proves the *field* carries the label (not that the renderer independently reconstructs an
equivalent-looking string by some other means). The test is correctly RED today for the right reason —
`FamilyTallyV2` has no such field yet, so attribute access fails before `_fmt_stratum_row` is ever
reached — not merely RED on the formatter argument as the isolated tests already were.

## Regression sweep of the touched sections

Checked AC numbering (AC #13 remains unique, no renumbering collision with AC #10/#11/#12), the
`xfail` carrying BLOCKER-3 (unchanged, still correctly deferred, and the additive `strata_side_mix`
tuple gives it a stated destination once exercised), and §9's failure-case list (untouched by this
diff). No regression found in any section this revision touches or is adjacent to.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — unaffected; unchanged from round 5.
- Technical correctness and evidence grounding (20): **20** — unaffected; unchanged from round 5.
- Implementation specificity and feasibility (15): **15** — the round-5 defect is closed: the data-flow
  is now concretely named, grounded in an already-proven extension pattern on the exact dataclass, and
  independently re-verified against source. No remaining gap found.
- Acceptance criteria and validation quality (20): **20** — AC #13 now requires the end-to-end test,
  which is the correct, sufficient proof that the carrier field is actually wired; the round-5 gap (no
  test drove the real render path) is closed.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected.

**Total: 100/100**

## Remaining defects and required changes

None found this round. AC #1's three-consecutive-day clock and AC #4's live-half OPEN observation
(no NO-leg fill in the record yet) remain honestly-named, unavoidable temporal properties, not fixable
by plan text — already correctly not deducted from Acceptance criteria in this final assessment.

## Blockers

- **BLOCKER-1 (strategy-lead / PREREG authority):** `trial_id_prefix` collision — unchanged, genuine.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired — unchanged, genuine.
- **BLOCKER-3 (strategy-lead / PREREG authority):** whether NO-side rows enter the `cell_dead`-bearing
  `station_strata`/`ask_band_strata` at all — unchanged, genuine. The additive `strata_side_mix: tuple[str,
  ...] = ()` extension named in §6 D-A(ii) correctly gives the post-ruling labelling a stated home
  without exercising it before the ruling lands.
