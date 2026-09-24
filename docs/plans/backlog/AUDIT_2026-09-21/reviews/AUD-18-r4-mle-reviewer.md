# AUD-18 round-4 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 049d7307aaadc87ef044fe1f405601ed00b7643a2fe7ccbff66332a91b0bb210
Round: 4
Reviewer: mle-reviewer (independent, blind). §13 self-score text ignored per instruction.

## Round-3 MATERIAL defect (LD_OBF unreachable, presented as selectable) — verification: FIXED

`grep` for `LD_OBF`/`LD-OBF`/`group-sequential` confirms every live passage (§5, §6.1, §6.4 step 3, §12) now frames it as WITHDRAWN, with the arithmetic reason restated (`per_variant_alpha <= 0.05/4 = 0.0125 < 0.025`, correctly recomputed for the new `MAX_HYPOTHESES=4`). `look_policy` is now `Literal["SINGLE_LOOK"]` in the schema; one RED (§7 step 1) refuses any other value; `PINNED_LD_OBF_ALPHA`/`look_schedule_n` fields removed. Only remaining `LD_OBF` mentions are inside §13's historical rows 2-3, correctly kept as history. No residual offering found.

## Arithmetic and derivation — verified

`MAX_HYPOTHESES=4` = §6.3's three open classes (archive-table recalibration, NO-side, hours 10-11) + one reserve, CONFIRMED against the §6.3 table read this session. `MIN_PER_VARIANT_ALPHA = 0.05/4/4 = 0.003125` — arithmetic CONFIRMED. `roi_bound.py:100,130,173` (`MIN_NON_EXCLUDED_N`, `ROIBoundUnderpowered`, `compute_roi_bound`) CONFIRMED accurate. One-sidedness consistent throughout (`PROGRAMME_ALPHA`, `per_variant_alpha`, `MIN_PER_VARIANT_ALPHA` all stated one-sided; no one/two-sided mismatch). Zero-look records (`REJECTED`, `UNDERPOWERED_NOT_REGISTERED`) mechanically cannot acquire a `HypothesisLook` row — tested by name in §7 steps 1(vi) and 3's REDs — no free-look loophole found.

## New MATERIAL defect — power-check's variance input is unspecified, risking a peek

The MDE computation (§6.1, §7 step 8(v)) is described as computed "over station-day-clustered draws under the repo's own estimator conventions — `combine_station_day`/`score_combined`." Those two functions are **estimators that operate on realized `StratumRow` data**, not power-calculation primitives; a pre-data MDE needs a variance/noise **assumption** (e.g. this repo's own established conservative Bernoulli bound `q(1-q) <= 1/4`, the same principle behind `I_MAX = n_max/4` in `PREREG_v2`), not real outcome rows. The plan never states which variance input the ruling's peers are meant to use, nor explicitly prohibits sourcing it from a preliminary peek at the very hypothesis's own draws. `register_hypothesis` itself only compares a **caller-supplied** `mde_at_allocated_alpha` against `mde_plausibility_bound` — it does not compute or validate the MDE, so nothing in the code enforces a peek-free derivation; the entire guarantee rests on the ruling authors' unstated discretion. D13 tests only the refuse/bookkeeping behaviour once an MDE is supplied, never that it was derived without opening data. **Required change:** pin the variance/noise assumption the MDE formula must use (e.g. the same conservative Bernoulli bound already used for `I_MAX`, or an explicit historical-but-different-corpus source that is not this hypothesis's own confirmatory data), state it in §6.1 next to the MDE formula, and add a RED or a ruling-artefact-format check that the stated variance source is the pinned one, not an ad hoc figure.

## Other checks

- Length: §13 now states the file is 832 lines — CONFIRMED via `wc -l` (832). Factual this round, an improvement over round 3's off-by-one.
- `MAX_VARIANTS_PER_HYPOTHESIS=4` is a stated policy preference (fewer, sharper hypotheses), not a derived constant like `MAX_HYPOTHESES` — correctly distinguished in the text, no overclaiming.
- "What IS controlled" still says "at most `MAX_HYPOTHESES x k_variants`" (singular `k_variants`) rather than `MAX_HYPOTHESES x MAX_VARIANTS_PER_HYPOTHESIS` for the true worst-case bound — a trivial wording imprecision, not a numerical error (the actually-enforced per-registration sum is correct); not scored.

## Per-criterion scoring (round 4, whole plan, fresh)

- Fidelity to audit gap and completeness: 18/20 — LD_OBF cleanly withdrawn and honestly recorded; the power check closes a real, previously-flagged gap in principle; docked for the unspecified variance-input mechanism leaving the freeze-firewall promise partly unverified.
- Technical correctness and evidence grounding: 16/20 — all citations and arithmetic verified correct; the newly-added power-check mechanism's core input (the variance assumption) is unspecified, a genuine correctness gap in this round's main addition.
- Implementation specificity and feasibility: 11/15 — `SINGLE_LOOK`/allocation machinery is fully concrete and buildable; the MDE computation is left to the ruling authors without a pinned formula or variance source.
- Acceptance criteria and validation quality: 16/20 — D13 solidly tests refusal/bookkeeping; no criterion tests (or could test, since none is specified) that the MDE was derived from the pinned assumption rather than a peek.
- Autonomous operation, failure handling and recovery: 14/15 — unchanged strength from round 3.
- Portfolio objective alignment, scope and dependencies: 8/10 — constants now derived from §6.3 rather than asserted; length grew again (731→832) but is honestly and correctly reported this round.

**Total: 83/100**

## Blockers

- None requiring external/operator input. The power-check variance-input gap is author-fixable (a specification addition, not a ruling or unavailable evidence).
