# AUD-18 round-7 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: bba51be19582c343291fbb549049ad2f7a285dc0156416458112ec755a3045e1
Round: 7
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.

## Round-6 MATERIAL defect (SUM's opposite-side covariance breaks `1/4`) — verification: FIXED at the root

The fix withdraws the SUM for this purpose and pins the station-day observation as the MEAN, `X_d = (1/m_d)·Σ(W_i − BE_i)`, bounded via Popoviciu rather than by modelling covariance structure. This is the mathematically correct way to close the class of failure I found in round 6 (it works for ANY dependence structure, sidestepping the sign-flip problem entirely) rather than a patch to the SUM's formula.

**Derivation independently re-verified, all three specific points requested:**
1. **Width-1 per term, both sides.** `W_i ∈ {0,1}` always; `BE_i = break_even_row(entry_ask_i, fee_i)` is a fixed per-leg constant computed identically regardless of side (confirmed: `break_even_row` at `current_rung_hold_v2.py:76-84` takes only `entry_ask`/`fee`, no side branch). So `W_i − BE_i ∈ {−BE_i, 1−BE_i}`, width exactly `1`, for a YES leg AND a NO leg alike (each using its own `BE_i`). CONFIRMED.
2. **Mean over different-width-1 intervals still spans ≤ 1.** If each `T_i ∈ [l_i, l_i+1]`, the Minkowski sum `ΣT_i` ranges over an interval of width `Σ1 = m`, so `X_d = (1/m)ΣT_i` ranges over width `m/m = 1`, regardless of the `l_i` being different (different `BE_i` per leg) and regardless of any dependence between the `T_i`. This holds unconditionally since Popoviciu only needs boundedness, not independence. CONFIRMED, matches the plan's claim exactly.
3. **`E[X_d]=0` is the correct one-sided null.** Under H0 (market/estimate exactly calibrated), `E[W_i] = BE_i` by definition of a break-even probability, so `E[W_i − BE_i] = 0` termwise and `E[X_d] = 0`. Testing for a positive mean (edge net of cost) is the correct one-sided direction, consistent with `per_variant_alpha` being one-sided throughout. CONFIRMED.

The worked mixed-side counterexample from round 6 (`q=[0.5,0.5]`, `qty=1`, opposite sides → SUM variance `1.0`) is correctly reused as the RED (vi-g) fixture proving the SUM fails and the MEAN doesn't. `combine_station_day`'s SUM is correctly kept, unchanged, for ROI accounting (`realized_draws.py`, `family_tally_v2.py`, settlement) — a real use-by-use distinction, not a blanket rename.

## New MATERIAL defect — `m_d = 0` (zero-take) station-days are not addressed, and this is a live case, not a hypothetical one

§6.1 defines `X_d` "for a station-day `d` carrying `m_d >= 1` takes" but nowhere states what happens to a station-day with `m_d = 0` — whether it is excluded from `n`/`min_station_days`, and by what mechanism. This is directly relevant, not an edge case: AUD-09's `replay_results.jsonl` schema (`docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`, confirmed this session) records `trials, fills` on every row including `outcome=COMPLETED` — a COMPLETED replay can legitimately have `fills=0` (the mechanical replay ran successfully but found no eligible take that day), which is this repo's OWN dominant historical pattern per G-01 ("0 pass cell legal... no order since 2026-09-15"). Meanwhile the reused primitive `combine_station_day` itself raises `ValueError` on an empty `rows` sequence ("a combined draw over nothing is undefined") — so if AUD-18's triage naively fed a `fills=0` COMPLETED row's (empty) leg set into `combine_station_day`, it would crash rather than silently mis-score, but the plan never states that this filtering happens, at what stage, or that such days are excluded from `n`/`min_station_days` counting (as opposed to, say, being counted toward `min_station_days` while never producing a draw, which would silently under-power the confirmatory test relative to what the ruling assumed). **Required change:** state explicitly, in §6.1 or §6.4 step 3, that a station-day with `fills=0` (no realized take) is excluded from the draw set AND from the `n`/`min_station_days` count the MDE was computed against, name the filter step, and add a RED asserting a `fills=0` COMPLETED row neither crashes the triage nor is silently counted toward `n`.

## Other checks

- No independence or side-mix assumption is smuggled in anywhere else in the diff; the use-by-use table (SUM vs MEAN) is accurate and complete for the citations given.
- Length: 1112 lines confirmed via `wc -l`; §13's claim is factual.

## Per-criterion scoring (round 7, whole plan, fresh)

- Fidelity to audit gap and completeness: 18/20 — the mixed-side fix is correct and elegant at the root; docked for the unaddressed, directly-grounded zero-take-day gap.
- Technical correctness and evidence grounding: 17/20 — the Popoviciu derivation and all three specifically-requested checks verified rigorously correct; docked for the unstated `m_d=0` handling, which is a real, schema-confirmed reachable case, not a hypothetical one.
- Implementation specificity and feasibility: 12/15 — `MEAN_EXCESS_PER_TAKE`, the refusal machinery and the worked fixtures are concrete; the zero-take filter step (where, and what happens to `n`) is unspecified.
- Acceptance criteria and validation quality: 17/20 — (vi-g)/(vi-h)/D13(vii) are precisely targeted and correct; no criterion covers the `fills=0` case.
- Autonomous operation, failure handling and recovery: 13/15 — otherwise solid, but an unhandled `fills=0` COMPLETED row could crash the triage run (`combine_station_day`'s own `ValueError` on empty input) rather than degrade gracefully, and nothing in §6.4's failure-case list names this.
- Portfolio objective alignment, scope and dependencies: 8/10 — length grew again (1004→1112) but accurately reported; scope remains tight.

**Total: 85/100**

## Blockers

- None requiring external/operator input. The `m_d=0` handling gap is author-fixable (a stated filter rule plus a test).
