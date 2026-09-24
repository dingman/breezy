# AUD-05 review — round 5 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 30c9341d411008e64fc4a0eed6247200babddb021c1fe1c151b0218e865ca949
Round: 5 (delta review of the round-4-named defect's fix)

## Fix verification: D-A(ii), the mean_ask side-mix label

§6 gains D-A(ii): `_fmt_stratum_row` gains a keyword-only `side_mix: str` argument, computed at the
call site from the row sequence the stratum was built from, rendering `""` / `" (NO-only)"` /
`" (mixed-side: Y<n>/N<n>)"` inside the `mean ask` cell, plus one price-domain footnote emitted exactly
once when any annotation is present. `STRATUM_TABLE_HEADER`/`STRATUM_TABLE_DIVIDER`/`StratumV2` are
deliberately unchanged, preserving AC #5's byte-identity floor.

**Citations independently re-verified against source, all exact:**
- `STRATUM_TABLE_HEADER`/`STRATUM_TABLE_DIVIDER` at `scripts/analysis/family_tally_v2.py:182-185` —
  CONFIRMED.
- `_fmt_stratum_row` at `:830-835` — CONFIRMED, currently takes only `stratum: StratumV2`.
- Render call sites: `add(_fmt_stratum_row(tally.pooled))` at `:1075`,
  `add(_fmt_stratum_row(stratum))` (inside the loop over `station_strata`/`ask_band_strata`) at `:1077`
  — CONFIRMED exact.
- `StratumV2` (`current_rung_hold_v2.py:386-402`) carries no side field — CONFIRMED unchanged.

## A genuine new defect found on this pass: the described mechanism is not implementable at the cited
call sites as stated

The plan's own text says `side_mix` is "computed at the call site from the **same row sequence the
stratum was built from**." I read the actual render path: `render_markdown_v2(tally: FamilyTallyV2, *,
source_paths, as_of)` (`:1025`) is the function containing both cited call sites (`:1075`, `:1077`). Its
only input is the already-**built** `FamilyTallyV2` object — I independently re-read `FamilyTallyV2`'s
field list (`:263-294`, confirmed earlier in this review batch): it carries `pooled: StratumV2 | None`,
`station_strata`, `ask_band_strata`, `looks`, `verdict`, etc. — **no raw rows, and no side-count
fields.** The row sequences (`pooled_rows`, `non_excluded`) exist only as local variables inside
`build_family_tally_v2`, a **different function** than the one containing the cited call sites. So
`render_markdown_v2`'s call site, as cited, has no access to "the row sequence the stratum was built
from" — the mechanism described cannot be implemented at `:1075`/`:1077` without first threading the
side-count data through some new channel from `build_family_tally_v2` to `render_markdown_v2`, which
the plan does not name (it explicitly says `StratumV2` is unchanged, but says nothing about whether
`FamilyTallyV2` gains a field, or whether `render_markdown_v2`'s signature changes to accept the raw
rows).

This is not a statistical or safety defect — the label's *content* and *semantics* are correct and
well-specified — but it is a concrete implementation-feasibility gap: an implementer following the plan
literally hits a wall at the exact call site the plan cites, and must make an unstated structural
decision (add a field to `FamilyTallyV2`? pass rows separately? compute the label string earlier and
carry it as a plain string field?) that changes the shape of a dataclass the plan does not currently
propose changing. This is exactly the class of "material design decision left to the implementer" this
review's brief tests for.

**The tests as specified do not catch this gap either.** I re-read the four new tests' descriptions:
`test_a_mixed_side_pooled_row_renders_the_side_mix_label_on_mean_ask` and its siblings assert
`_fmt_stratum_row(stratum, side_mix=...)`'s **output string** — i.e., they exercise the formatter
function directly with `side_mix` **pre-supplied as an argument**, which proves the formatting is
correct but does not exercise whether `render_markdown_v2` can actually **produce** that argument from
what it has in scope. None of the four tests calls `render_markdown_v2(tally)` end-to-end and asserts
the label appears in its output, so the plumbing gap is untested as well as unspecified.

## Fresh review — no other new defect found

The three-literal rendering rule, the footnote text, and the `xfail` carrying BLOCKER-3's post-ruling
exercise were all independently re-checked and are sound and correctly scoped.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — unaffected; the disclosure's content and scope
  are correct.
- Technical correctness and evidence grounding (20): **20** — the labelling semantics (what the three
  literals mean, when the footnote fires) are correct and independently re-derived; the gap found is
  about implementation plumbing, not the underlying statistics or disclosure content.
- Implementation specificity and feasibility (15): **14** — 1 point withheld for the row-data threading
  gap: the plan's stated mechanism ("computed at the call site from the row sequence") is not achievable
  at the cited call sites, and no alternative data-flow is specified.
- Acceptance criteria and validation quality (20): **19** — 1 point withheld because none of the four
  new tests exercises the actual `render_markdown_v2(tally) → output` pipeline end-to-end; they test
  `_fmt_stratum_row` in isolation with `side_mix` pre-supplied, which does not prove the plumbing works.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected.

**Total: 98/100**

## Remaining defect and required change

1. **MINOR.** D-A(ii)'s described mechanism ("`side_mix` computed at the call site from the row
   sequence the stratum was built from") is infeasible at the cited call sites
   (`family_tally_v2.py:1075`/`:1077`, inside `render_markdown_v2`), which only receive the already-built
   `FamilyTallyV2` object, not the raw rows — those exist only inside the separate `build_family_tally_v2`
   function. **Required change:** name the actual data-flow explicitly — e.g., add `pooled_side_mix: str`
   (and, once BLOCKER-3 lands, per-stratum equivalents) as a new field on `FamilyTallyV2`, computed once
   inside `build_family_tally_v2` from `pooled_rows` before they go out of scope, and threaded through to
   `render_markdown_v2` — and add a test exercising `render_markdown_v2(tally)` end-to-end (not just
   `_fmt_stratum_row` in isolation) to prove the label actually reaches the rendered output.

## Blockers

- **BLOCKER-1 (strategy-lead / PREREG authority):** `trial_id_prefix` collision — unchanged, genuine.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired — unchanged, genuine.
- **BLOCKER-3 (strategy-lead / PREREG authority):** whether NO-side rows enter the `cell_dead`-bearing
  `station_strata`/`ask_band_strata` at all — unchanged, genuine; the `xfail` naming it is correctly
  carried forward and would also need the plumbing fix above once it is exercised.
