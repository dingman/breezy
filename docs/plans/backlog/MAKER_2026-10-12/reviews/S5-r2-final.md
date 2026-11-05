# S5 r2 final — prediction-market-reviewer (verification) — 2026-10-12
Verdict: NOT-READY — every r1 BLOCKER/MAJOR is present in the r2 body, but r2 still contradicts spec v0.3 on the loss stop (§4), forecast age (STALE_H), the §6.9 form and the "GO" gate, and it does not implement the conditional MAX_RUNGS fallback.

## Disposition check
| r1 review | # | r2 claims | verified? |
|---|---|---|---|
| architect | 1-13 + mismatches | all ACCEPTED | YES. Present in the body: mismatch abstain, `available_at` age, `<=` (WP1), coverage `c` (WP0.3, §8), BOOT/STOP + cancel-on-stop (WP2), `set_time_alert` (WP2), no `evaluate_order` (§3), WP6 health check, S4 moved to G8, package-wide AST ban, halt via `decide`. Cites re-checked: sha 47d1b94c exists; `check_freeze_introduction` :423, `_refuse_overwrite` :780, `_preflight_inputs` :875, `boundary_for` :163, `HALTABLE_COMPOSITION_KINDS` :20, `KINDS_WITH_EXIT_PATH` :30 |
| pm-reviewer | 1 BLOCKER | calendar dates, revisions 0 | YES. WP5 `holdout_start_date`, `calendar_cap_date`, `revision_budget: 0`; test `test_split_is_calendar_dates_not_fraction` |
| pm-reviewer | 2 | feasibility rule + day-60 power stop | YES in E1, S-5, WP5, §8. Table arithmetic re-computed and correct. Prose "E1 needs r_lo ≳ 0.2" is wrong (see R6) |
| pm-reviewer | 3 | pooled non-inferiority, 10-loss minimum | YES present, but the form conflicts with spec v0.3 (C4) |
| pm-reviewer | 4 | causal replay with fill state | YES (§3.2, WP3.2, `filled` in `decide`) |
| pm-reviewer | 5 | G3 method, no Holm, E5 | YES (WP4, WP5, WP0.2) |
| pm-reviewer | 6 | log vector + θ, per-stress re-decide | YES (`SHADOW_FORECAST`, WP3.7) |
| pm-reviewer | 7 | deff-inflated stop, `b_fut`, ordered looks | YES present, but the whole stop is now superseded by spec §4 (C1). The "(d) KEPT because spec §4 declares it binding" rebuttal is now false |
| pm-reviewer | 8-13 | unresolved = LOSS, 7-day blocks, units, age, G4/G6 values | YES (WP3.4, WP4, WP5, G7 = 0.90) |
No item was REBUTTED, so there was no rebuttal evidence to check except pm #7d, which fails against v0.3.

## Spec v0.3 contradictions (plan line -> spec section)
- C1 [MAJOR] §3.4, WP5 "Sequential stop", `maker_sequential_tally.py`, S-3, G-lists, §10 input 11, disposition #7d -> spec §4 "One loss stop": the stop is the A1 loss floor on the station-day clock, and "LD-OBF on Wilson every 10 positions is dropped (two stops would need two reachability proofs)". The plan keeps a second, Wilson/LD-OBF-style `S_k` stop with `boundary_for` at alpha_stop 0.025 and looks every 10 positions. S3 certifies only the A1 object, so this stop is unproven for reachability. Fix: delete the tally and `boundary_for` use; WP5 freezes the S3-certified A1 floor (station-day clock, design-effect 1.5, looks by settlement time) and E2 carries its parameters; S-3 becomes "A1 floor fires".
- C2 [MAJOR] `MAX_FORECAST_AGE_H`, WP1 ("> 6 h"), WP2 ("available_at + 6 h"), WP0.3 ("age <= 6 h"), tests `...plus_6h`, WP3.2 clamp -> spec §3 `STALE_H = 8`. The plan header says "working v0.3" yet uses 6 h. Fix: STALE_H = 8 everywhere (rename the constant); recompute the WP0.3 coverage table and `c`. The scorer clamp and S2 must also use 8.
- C3 [MAJOR] E1 "S2 GO" -> spec §6.0: Stage 0 never emits GO; the verdicts are NO-GO / NOT-KILLED / NOT-KILLED-UNSCREENED. Fix: E1 = NOT-KILLED (state whether NOT-KILLED-UNSCREENED suffices; the plan's §6.9 gate would need a fresh holdout screen anyway, so it may). Also make the E1 base-fill >= 0.10 and stressed >= 0.10 conditions explicit.
- C4 [MAJOR] WP5 "Adverse selection" row, WP4 G9, WP3.5 -> spec §6.9: the test is per pooled p_NO stratum (0.94-0.96, 0.96-0.98, >0.98). FAIL if the filled loss rate exceeds 1.5 x model p_YES (margin `as_margin`) by an exact tail test at alpha 0.05, or exceeds the unfilled rate by the same test. A verdict needs >= 10 expected losses, else UNSCREENED (not PASS). A FAIL is terminal. The plan uses a pooled additive bootstrap bound ("<= as_margin"), has only PASS / INCONCLUSIVE (no FAIL, no terminal), calls strata "report-only", and leaves `as_margin` as open Q2 (the spec fixes 1.5x). Fix: adopt the spec's exact-test, multiplicative form, with the PASS / FAIL / UNSCREENED vocabulary. G9 = PASS only. A FAIL ends the family. Delete open Q2.
- C5 [MAJOR] S-2, WP0.4, §10 input 1 -> spec §3 MAX_RUNGS: 2 is conditional on a reviewed per-family exclusive-conflict admission verified by a test before freeze. If refused, MAX_RUNGS = 1 and the clock doubles. The plan treats a refusal as "do not freeze" and gives no MAX_RUNGS = 1 branch. Fix: S-2 becomes "set MAX_RUNGS = 1 and recompute §8 (positions/day halve; station-day/day = 3.64 x r)"; WP0.4 states the admission test.
- C6 [MINOR] WP2 `order_factory.limit(..., GTC, 1)` -> spec §3 GTD with expire_time = min(S.day CANCEL_LST, permit.expires_at, end of booking UTC day). Log the would-be GTD order and the expiry so the replay clamp matches.
- C7 [MINOR] WP5 `maker_prereg_check` "holdout_start_date > last Stage 0 truth date + 2 days" -> spec §6.2 "one-calendar-day purge". The plan's rule is stricter; state it as a deliberate superset or align.
- C8 [MINOR] WP3 has no taker-fill bucket -> spec §3/§6.8 "filled as TAKER counted separately, reported". Add the scorer count (a crossed ask in the replay) and the report field.
- C9 [MINOR] G5 / WP3.7 `loso_<STN>` not stated as report-only; spec §6.7 lists by-station leave-one-out as report-only. State it.
- C10 [MINOR] G8 -> spec §7.8 names S4's venue positive controls (resting GTD accepted, cancel scoped); G8 lists "S4 merged sha + gate EXIT" only. Add the positive-control evidence. Also §10 "spec v0.3 inputs" is now stale (spec has absorbed 2-13); replace with a conformance table.
Matches v0.3: zero revisions, calendar split, 300/200 outcome-blind target, 7-day-block primary with climate-date reported, G3 one-sided at alpha_family, unresolved past D+14 = LOSS, void = refund - fee, baselines report-only (min n 30), gated stresses, leakage `<=`, cancel-on-stop, S4 at gate 8.

## Residual items
- R1 MAJOR C1. R2 MAJOR C2. R3 MAJOR C3. R4 MAJOR C4. R5 MAJOR C5.
- R6 MINOR: §8 "E1 needs r_lo ≳ 0.2" is wrong at c = 1. The cap is 2027-11-30, giving 358 binding days, so about r >= 0.115 (positions bind). Fix the sentence or tie it to `c` after the STALE_H 8 recompute.
- R7 MINOR: C6-C10 above.
- No new BLOCKERs.

## Invariants
- Nautilus immutable / native clock + order factory only: PASS
- allow_short False, no sells in `decide`: PASS
- No operator caps assigned; BREEZY_ORDERS_ENABLED untouched; no `live_orders_ruling`: PASS
- NO-SEND / L-12 widened rows only; package-wide AST submit/cancel ban: PASS
- Frozen PREREG never edited / dates not moved (fork only): PASS
- Stage 0 exploratory only: PASS (but E1 wording "GO" must change, C3)
- NO-TRADE ruling stays in force; advisory PROPOSAL, arms nothing: PASS
- Single stop object per spec §4: FAIL (C1)
- Simplest path: PASS apart from the extra tally script (C1), which is also the one removable machinery item
