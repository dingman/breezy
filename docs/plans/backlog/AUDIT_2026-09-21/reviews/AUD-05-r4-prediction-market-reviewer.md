# AUD-05 — Round 4 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
sha256: 9aeef125f525e1a78b7b464db3c50035f19245642215fe6143738c54981963ca
Round: 4 (final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## The three settled claims from the brief — each independently re-verified against source

1. **`any_cell_dead` is gating, not reporting-only.** `family_tally_v2.py:655`:
   `any_cell_dead = any(s.cell_dead for s in (*station_strata, *ask_band_strata))`. It is passed as
   `cell_dead=any_cell_dead` into `terminal_look(...)` at `:728` and `:792`, and into
   `look_verdict(...)` at `:753` — CONFIRMED verbatim (all four line numbers read directly).
   `look_verdict` (`current_rung_hold_v2.py`, docstring and body) implements
   `KILL <=> S <= b_fut OR cell_dead OR structural_fired` — CONFIRMED verbatim in the body I read.
   Its return becomes `FamilyTallyV2.verdict`. **CONFIRMED: gating, not a report label.**
2. **`pooled` is reporting-only.** `pooled = build_stratum_v2("pooled", pooled_rows)` at `:645` is
   not a member of the `(*station_strata, *ask_band_strata)` tuple fed to `any_cell_dead` at `:655`
   — CONFIRMED by reading the exact tuple construction. It flows only to `FamilyTallyV2.pooled` and
   the renderer. **CONFIRMED inert to every registered KILL element.**
3. **The round-3 "pooled-only fix clears D-A" claim was refuted, and correctly so.** `_station_strata`
   (`:653`) and `_ask_band_strata` (`:654`) are both called on `non_excluded` — the SAME row set
   `pooled_rows` is built from at `:645`, immediately after — and both delegate to
   `build_stratum_v2`, which raises `ValueError` on any row whose `side != "yes"` (confirmed by
   reading `build_stratum_v2`'s body and its raise site directly). A pooled-only fix would leave the
   `ValueError` reachable at `:653`/`:654` with `pooled_rows` non-empty and any NO row present.
   **CONFIRMED: the tally would still not run.**

All three claims hold exactly as the reviser stated. The disposition that follows from them — D-A
ships against `pooled` only (provably inert), the two `cell_dead`-bearing strata become BLOCKER-3,
and a meantime "withhold, never fabricate" behaviour keeps the unit running — is the correct
response to the evidence, not an in-plan decision of a §7-frozen element.

## Derivation check: `E[held_i] = BE_i` on both sides

Re-derived independently from `StratumRow`'s docstring (`held` is the caller-supplied per-side truth:
`1{HIGH ∈ r_i}` for YES, `1{HIGH ∉ r_i}` for NO) and `_cell_probability` (`q_i = BE_i` for YES,
`q_i = 1 − BE_i` for NO, both read verbatim from source). For YES: `E[held_i] = P(HIGH ∈ r_i) = q_i =
BE_i`. For NO: `held_i = 1 − 1{HIGH ∈ r_i}`, so `E[held_i] = 1 − q_i = 1 − (1 − BE_i) = BE_i`.
**CONFIRMED correct** — this is not merely asserted, it follows from the fields' own stated
semantics, and it is the premise that makes admitting NO rows into `pooled` unpartitioned provably
inert to the statistic (`k` vs `pi = mean(BE_i)` is the correct null on both sides).

## Is a verdict ever computed WITHOUT the gating `cell_dead` term published as if registered?

No, by construction as specified: on a NO-bearing corpus, `station_strata = ()` and
`ask_band_strata = ()` are not computed, `any_cell_dead` is never fabricated as `False`, the look
loop is skipped via the same `scheduled_ns = range(0)` mechanism the existing structural-dead branch
already uses (verified present at `family_tally_v2.py:694-696`), and `verdict =
"PENDING_STRATA_RULING"` is published instead of any of the three registered outcomes. Two RED tests
(`test_a_no_bearing_corpus_withholds_the_cell_dead_strata_and_the_verdict`,
`test_a_no_bearing_corpus_never_reports_cell_dead_false`) hold this as a standing negative control on
the false-negative direction. On an all-YES corpus this branch never triggers and the existing
byte-identity floor still proves the registered path is untouched.

## Additional check performed (not in the brief, done for completeness)

Widening the verdict literal with a fourth value (`PENDING_STRATA_RULING`) risks breaking a
downstream reader that pattern-matches on a closed three-value union. Grepped the repo for
`FamilyTallyV2`/verdict consumers outside `family_tally_v2.py`/`current_rung_hold_v2.py`/tests: none
found (`live_family_tally.py`'s own `"SURVIVE"` string is a different, v1 module explicitly excluded
by this plan's §5). No defect found here; noted as a positive verification, not a deduction.

## Defects

None MATERIAL. The single MATERIAL defect from round 3 (side-partitioning a §7-frozen element
in-plan, with the "pooled-only already clears D-A" claim used to under-scope the fix) is fixed
exactly as this round's re-verification confirms: partitioning is withdrawn, the frozen strata are
deferred to BLOCKER-3 with a recommended (not decided) disposition, and the unit runs unattended
without ever publishing a fabricated verdict.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — G-04 fully covered (D-A/B/C/D/E/F); the §7-frozen
  element is now correctly surfaced as a named blocker with a source-derived recommendation instead
  of being decided in-plan.
- Technical correctness and evidence grounding (20): **20** — every load-bearing claim in this
  revision's central restructure (`cell_dead` gating, `pooled` inertness, the pooled-only-doesn't-
  clear refutation, the `E[held_i]=BE_i` derivation) independently re-verified against current
  source with exact line matches.
- Implementation specificity and feasibility (15): **15** — the code change is minimal and exactly
  located (drop the `:418-423` refusal; admit NO rows to `pooled` only; reuse the existing
  `scheduled_ns = range(0)` skip mechanism for withholding); the sentinel value and its alert are
  named.
- Acceptance criteria and validation quality (20): **20** — AC #11/#12 correctly test the withheld
  path and the false-negative negative control; the all-YES byte-identity floor (AC #5) remains
  untouched by the withholding branch, exactly as required.
- Autonomous operation, failure handling, recovery (15): **15** — D-F's latched CRITICAL alert on
  failure and the new WARN on a withheld verdict are both delivered, not silent; the orphan
  re-accumulation guard closes the WP-11b failure class.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's chain, numeric baseline
  and falsifier are concrete; no reviewer across three rounds has named a defect here.

**Total: 100/100**

## Required changes

None.

## Blockers (named separately, not scored as deductions — unresolvable by any reviewer or plan text)

- **BLOCKER-1** — strategy-lead/PREREG ruling on `pm_us_crh_v4`'s `trial_id_prefix` identity
  (identical to `pm_us_crh_cont`'s today).
- **BLOCKER-2** — strategy-lead ruling on whether `pm_us_crh_cont` is retired now that it carries a
  `terminal_climate_day`.
- **BLOCKER-3** (new this cluster, correctly filed rather than decided) — strategy-lead/PREREG
  ruling on whether NO-side rows may enter `station_strata`/`ask_band_strata` (the `cell_dead`-
  bearing, §7-frozen strata), with the recommended disposition ("admit unpartitioned, `pi =
  mean(BE_i)`") stated and derived but not adopted by this plan.
