# AUD-05 review — round 2 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 171f40d32865d19ac19c3531e78eb5bc889149d41973601bce59478542f054f1
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 remedy verification

| # | R1 defect | Claimed fix (§13) | Verified in body |
|---|---|---|---|
| 1 (mle) | D-A under-cites the registered formula | §6 D-A quotes amendment §3 notation, `BE_i`, `q_i`, `Var_H0`, pair-sign cases, §4 gate | CONFIRMED text is now present in §6 (lines ~140-159) and matches `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §3 verbatim (sign convention, `BE_i` per leg, `q_i`, `Var_H0` formula, three pair cases, admission gate) — checked against the amendment file directly. **However, see new MATERIAL defect below: the cited formula is not the one `build_stratum_v2` computes.** |
| 2 (pm) | D-B causes not pre-ranked | §6 D-B / §7 step 0(b) name `no_leg_instrument_id`, `leg_of`, `sibling_instrument_id`, `LEG_NO` and make the composite-id comparison the first check | CONFIRMED present. `fill_time_count.py:139-159` re-read directly: `counted_trial_keys` is genuinely one key per `(family_prefix, station, climate_day)` (line ~139-146), and membership test is `trial.instrument_id in filled_instrument_ids` (built from `DurableFillRecord.instrument_id`) — both claims hold verbatim. |
| 3 (both) | Alert wiring left as a choice | New §6 D-F: `emit_alert(resolve_alert_sink(), AlertPayload(severity=..., event=..., site=..., detail=...))`, latched per family/day | CONFIRMED `emit_alert`, `resolve_alert_sink`, `AlertPayload` exist at `src/breezy/runtime/health.py:351,579,668`; `AlertPayload` is exactly the 4-field shape the plan calls (`severity`, `event`, `site`, `detail`) — CONFIRMED verbatim. |
| 4 (both) | D-A field location unpinned | §6 names stratum builder's `side`/`BE`/`held` carriers around `:380-430`, step 0(f) requires the dataclass field list | Present, but see the new defect below — the location is right, the target semantics are not. |
| 5 (mle) | Establish D-B root cause first | §7 step 3 conditions the test set on step 0's finding | CONFIRMED, present as written. |
| 6 (both) | AC #4 live half unschedulable | Split into fixture gate + OPEN observation | CONFIRMED, present. |
| 7 (both) | §11 ROI alignment score | Explicit chain + numeric baseline + falsifier added | CONFIRMED present; assessed again below on its own merits, not re-litigated as a round-1 dispute. |

## New verification this round (whole revised plan, source-checked)

**MATERIAL — D-A's RED-test oracle (`Var_H0` with the positive YES/NO cross term) is not a
statistic `build_stratum_v2` computes, and the plan does not reconcile this.**

File: AUD-05 §6 "D-A → make `build_stratum_v2` side-aware", §7 step 1.

I read both functions verbatim (`src/breezy/settlement/current_rung_hold_v2.py`):

- `build_stratum_v2` (def at :405, not :380 as the plan's location estimate has it — see MINOR
  below) computes exactly three things from a stratum's rows: `k = sum(held)`, `mean_ask =
  mean(entry_ask)`, `pi = mean(break_even_row(entry_ask, fee))`, and a Wilson interval on `k/n`.
  There is no variance term, no cross term, no `s_i`/`q_i` construction anywhere in this function
  or in `StratumV2` (fields: `label, n, k, mean_ask, pi, wilson_lower, wilson_upper` — no
  `variance` field exists). `cell_dead` compares `wilson_upper < pi` — a fixed-rule, non-sequential
  check, explicitly documented as such ("no sequential monitoring here").
- `combine_station_day` (def at :298, **not :192-227** — see MINOR below) is the function that
  actually computes `s_i`, `q_i = _cell_probability(be, side)`, `x`, and
  `variance -= 2.0 * qty_i * qty_j * signs[i] * signs[j] * qs[i] * qs[j]` (verbatim at :344) — this
  IS the amendment §3 formula, byte-for-byte, and it feeds the *sequential pooled* monitor via
  `score_combined`, a structurally separate path from `build_stratum_v2`/`StratumV2`/`cell_dead`.

The plan's §7 step 1 RED test `test_a_mixed_side_station_day_matches_the_registered_variance_formula`
is described as proving that **the D-A fix** (in `build_stratum_v2`) "implements the registered
statistic rather than a plausible one," asserting the cross term is positive for a YES/NO pair. But
that cross term belongs to `combine_station_day`, a function the plan's own §5 explicitly excludes
from any change ("No change to `combine_station_day`... it already implements the registered
mixed-side variance"). Two readings, both bad:

1. If the test calls `combine_station_day` (unchanged, already correct): it is not RED before the
   fix — it already passes today, since that function was never side-blind and is not touched by
   D-A. Billing it under "RED for D-A" is a genuine RED→GREEN methodology defect: a test that never
   fails cannot demonstrate the fix. It would be a legitimate *characterization* test of an
   unchanged function, but the plan presents it as proof of the changed one.
2. If the test is meant to exercise `build_stratum_v2` post-fix: then the fix is not the "narrow,
   field-level" change §6 describes (touching only `side`/`BE`/`held` carriers) — it requires adding
   an entirely new variance/covariance computation and a `variance` field to `StratumV2` that does
   not exist today, contradicting the plan's own scope statement and its "confined to three fields"
   framing, and reopening the question of whether `cell_dead`'s comparison of `wilson_upper` against
   a scalar `pi` (mean of raw `BE_i`, not reflected `q_i`) is even well-defined once NO rows are
   admitted — the amendment's §3 formula was never written for a fixed-rule Wilson-vs-mean-BE
   stratum test; it was written for the sequential pooled draw. **The amendment gives no oracle at
   all for what a side-aware `build_stratum_v2`/`pi`/`cell_dead` should compute** — e.g. whether
   `pi` should become `mean(q_i)` (the reflected probability) rather than `mean(BE_i)` for NO rows,
   which changes `cell_dead`'s truth value on any station/ask-band stratum containing a NO row.

This is a material design decision — "what does side-aware `pi` mean for the fixed-rule strata" —
left unresolved by both the amendment (which the plan correctly treats as the oracle, but which
does not speak to this function) and the plan itself. It is exactly the class of gap the brief asks
this review to catch: the plan is not executable as specified without the implementer inventing a
statistic that was never registered, and the plan's central claim ("registered statistic is
unchanged, proven by test") does not, as written, connect to the code path it claims to prove.

**MINOR — both line citations for the two functions central to D-A's grounding are stale.**
File: AUD-05 §3 D-A ("combine_station_day at ... :192-227"), §5, §7 step 0(f) ("current_rung_hold_v2.py:380-430").
Issue: `combine_station_day` is defined at line 298 in the current file, not 192-227 (192-227 is the
`StationDayAdmissionRefusal`/`CombinedDraw` docstring block, which *describes* the formula in prose
but is not the function). This citation is inherited verbatim from
`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` itself (also stale there, presumably drifted since
87278dd through later edits — `_MixedDayMissingRungKeyRefusal`/`_SameRungOppositeSidesRefusal` were
added after the amendment was written). `build_stratum_v2` is defined at :405, not the plan's
":380-430" estimate (405-437 is closer). Neither is a blocking defect on its own — the empty-diff
merge assertion and the dataclass-field-list evidence step (§7 step 0(f)) do not depend on line
accuracy — but a plan whose central risk-mitigation claim rests on "verify against the cited lines"
should have caught this when re-verifying the amendment's own citation, and it did not.
Fix: re-cite both functions at their current line numbers, and, more importantly, resolve the
MATERIAL defect above before the line numbers matter.

No other new defects found. D-D, D-E, D-F, the alert-sink call shape, and the D-B counting-unit
diagnosis all re-verify cleanly against source on this pass.

## Round-1 "portfolio objective alignment" (item 7) — assessed fresh, not re-litigated

§11 now states the explicit chain (AUD-05 → n grows → AUD-02 edge estimate → AUD-06b BLOCKER-B →
AUD-04), a numeric baseline (0 reports, n=0, ≥3 consecutive failures), a plausible-vs-demonstrated
split that concedes zero ROI contribution, an evaluation rule and a falsifier. This is genuinely
what was missing in round 1 (a stated path, not an asserted one) and I find no remaining defect in
this section on its own terms: it neither inflates nor buries the indirectness. The remaining
score shortfall is not a "still missing" item to fix — it reflects that the item is a real
dependency but not a money-moving one, which the plan itself says plainly. I do not withhold points
here beyond what that honest characterization already costs (see per-criterion table).

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **17** — covers G-04 fully and surfaces D-D/D-F beyond
  it. Docked 1 further than the author's 18 because the D-A remedy, as now specified, does not
  actually close the gap it claims to close (see MATERIAL defect) — "side-aware `build_stratum_v2`"
  is still underspecified at the semantic level, not just the field level.
- Technical correctness and evidence grounding (20): **13** — the amendment-citation work is
  excellent (verbatim quoting, correctly identifies `combine_station_day` as already-correct), but
  the plan's own RED-test oracle for the changed function is not grounded in a formula that function
  actually computes, and both central line citations are stale. This is the item's single
  highest-risk claim, and the round-2 pass does not survive re-verification.
- Implementation specificity and feasibility (15): **9** — seams named, alert wiring fully specified,
  D-B pre-narrowing concrete. But the D-A implementation target is unresolved at the level that
  matters (what should `pi`/`cell_dead` mean for a mixed-side stratum), which is a bigger gap than
  "the exact field names come from step 0" — it is a missing statistic definition, not a missing
  lookup.
- Acceptance criteria and validation quality (20): **14** — AC #4 and #9 are well-designed; guard
  preservation is proven by test. AC #5 ("the registered statistic is unchanged... the mixed-side
  closed-form test matches the amendment §3 formula") is not achievable as specified for the
  function actually being changed, per the MATERIAL defect.
- Autonomous operation, failure handling, recovery (15): **13** — D-F is fully specified and
  verified against real sink code; genuinely closes the round-1 gap. Docked 2 (not the author's 1)
  because nothing prevents orphan-unit re-accumulation, matching the author's own self-assessment.
- Portfolio objective alignment, scope, dependencies (10): **7** — §11's chain, baseline and
  falsifier are concrete and honest; this criterion improved genuinely from round 1 and I award
  above the author's 6 because the "epistemic, not money-moving" framing is exactly right and fully
  evidenced, not merely asserted.

**Total: 73/100**

## Required changes to reach 100

1. Resolve, with a stated statistic (not left to the implementer), what a side-aware
   `build_stratum_v2`/`pi`/`cell_dead` means for a stratum containing NO rows — either derive it
   from the amendment's principles (e.g. `pi := mean(q_i)`, reflected per side) and state that
   derivation as the oracle, or scope D-A down to "refuse NO rows into `build_stratum_v2`'s pooled
   stratum only, admit them elsewhere" if that is actually what "side-aware" is meant to mean here.
   As written, the plan asserts a formula for the wrong function.
2. Re-point `test_a_mixed_side_station_day_matches_the_registered_variance_formula` (or split it) so
   it is genuinely RED before the fix and GREEN after, against the function D-A actually changes.
3. Correct the two stale line citations (`combine_station_day` → :298, `build_stratum_v2` → :405) in
   §3, §5 and §7 step 0(f).

## Blockers

- **BLOCKER-1 (strategy-lead / PREREG authority):** the `trial_id_prefix` collision — genuine,
  correctly deferred, unchanged from round 1.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired — genuine, correctly deferred.
- **New, this round:** the D-A statistic definition for `build_stratum_v2` is not a strategy-lead
  ruling question (it is an implementation-correctness question this plan should answer), so it is
  not filed as a third BLOCKER — it is a required plan change (#1 above), not an operator decision.
