# AUD-18 — Round 4 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 049d7307aaadc87ef044fe1f405601ed00b7643a2fe7ccbff66332a91b0bb210
Round: 4

## Round-3 MATERIAL (power unexamined; MAX_HYPOTHESES unjustified) — PARTIALLY fixed

**Genuinely fixed:** `MAX_HYPOTHESES=4` verified honest against §6.3's own table — exactly the three classes marked BLOCKED-not-CLOSED (archive-table recalibration, NO-side, hours 10-11) plus one reserve for the "genuinely different" maker/resting redesign §6.3 itself names; nothing else in §6.3 is registerable (forecast-taker CLOSED/TERMINAL, Kalshi out of scope). `MAX_VARIANTS_PER_HYPOTHESIS=4` and `MIN_PER_VARIANT_ALPHA=0.003125` correctly floor the allocation. LD_OBF withdrawal is correct and well-cited: `I_MAX=40.0` (`gs_boundary_artefact.py:78`), `ALPHA_ONE_SIDED=0.025` (`:82`), refusal logic (`:269-272`) all CONFIRMED verbatim; `per_variant_alpha <= 0.0125` under any admissible allocation genuinely never reaches 0.025.

**NOT fixed — MATERIAL: the power-check mechanism cites the wrong precedent and never specifies its own inputs.** `ROIBoundUnderpowered` (`roi_bound.py:100,130,173`) is CONFIRMED but is a POST-HOC sample-size floor (`n < MIN_NON_EXCLUDED_N=30` on already-collected rows) — it computes no effect size and compares no bound; it is functionally identical to (and redundant with) this plan's own existing `min_station_days` gate. It is not precedent for a PROSPECTIVE minimum-detectable-effect calculation made before any data exists, which is what §7 step 8(v) actually requires. The plan never states what feeds that prospective MDE: no assumed ask price, no explicit tie to the CURRENT fee schedule (θ=0.0695, not the stale 0.06 pin `venue-fee-theta-drift-2026-09-17`), and no slippage assumption. `combine_station_day`/`score_combined` (`current_rung_hold_v2.py:298,348`) DO compute a fee-net statistic (`BE_i = entry_ask + fee`) over realized rows, but a ruling cannot run them "over station-day-clustered draws" before any draws exist — the plan conflates "use this estimator's Var_H0 formula prospectively with assumed parameters" (a real, executable design) with "run the estimator over draws" (impossible pre-registration), and never resolves which is meant. Required change: state explicitly that the MDE is computed by plugging an ASSUMED per-take ask price (net of the current θ and a stated slippage assumption, not a raw hit-rate) into the same `Var_H0`/`BE_i` formula extrapolated to `min_station_days`, cite the correct precedent (there may be none — say so), and add a RED pinning that formula, not just the refusal branch.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 18/20 — LD_OBF cleanup and the honest "KILL more likely" framing (§9/§11) are strong; the power check's own mechanism is still not executable as specified.
- Technical correctness and evidence grounding: 15/20 — MATERIAL mis-citation: `ROIBoundUnderpowered` does not establish the claimed prospective-MDE discipline.
- Implementation specificity and feasibility: 12/15 — no formula or input convention (assumed ask/fee/slippage) for the pre-data MDE; an implementer cannot mechanically produce the number the ruling is required to state.
- Acceptance criteria and validation quality: 16/20 — D13 tests the refusal branch well but nothing pins the MDE computation itself or its fee/slippage-net unit convention.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected, unchanged from round 3, still solid.
- Portfolio alignment, scope and dependencies: 10/10 — unaffected, clean.

**Total: 86/100.**

## Blockers

None external. The power-check specification gap is an in-plan fix (state the MDE's input convention and formula, correct or drop the `ROIBoundUnderpowered` citation), not an operator/strategy ruling or unavailable evidence.
