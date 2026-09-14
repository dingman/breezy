# Ruling: multi-position per station (operator ruling 2026-09-14)

**Ruling:** the one-trial-per-station-day construction bound is removed. A
station may hold as many open positions as it has current rungs, bounded
only by the two operator caps (the per-position cap and the daily budget) —
never by a synthetic one-per-day limit. Increment A ships qty fixed at 1;
Increment B (separate review gate) carries real qty through sizing/scorer.
**PREREG v3 struck/replaced:** §13 line 210 (one position per station-day)
→ *one open position per instrument-day; a station-day may carry as many
positions as it has current rungs, bounded only by the two operator caps.*
§16 line 276 (`q != 1` exclusion) → *qty carried; `qty<=0` stays a loud
`malformed_input` refusal; only `0<qty<1 lot` stays `partial_fill`; a
thin-book fill is accepted at its filled qty.* §12 test 6 → re-scoped to
duplicate fill on the same **instrument**-day.
**Statistic (R3-3, supersedes Rev1/2 §2):** for station-day `sd`, rungs
`i=1..k` mutually exclusive (`Cov(held_i,held_j)=-BE_i·BE_j` under H0):
`X_sd=Σqty_i(held_i-BE_i)`; `Var_H0(X_sd)=Σqty_i²BE_i(1-BE_i) -
2·Σ_{i<j}qty_i·qty_j·BE_i·BE_j`; `I=Σ_sd Var_H0`; `S=ΣX_sd/√I`;
`Var_H0(S)=1` exactly. k=1,qty=1 → byte-identical to `score()`. At qty≡1,
`Var_H0` collapses to `S_sd(1-S_sd)` (`S_sd=ΣBE_i`) — same ≤1/4 ceiling
`i_max=n_max/4` already assumes. **Admission gate** (at draw construction,
never post-hoc): `Σ BE_i ≤ 1` per station-day, else `malformed_input`.
**Increment A scope:** qty fixed at `Decimal(1)` for every real caller;
multi-rung station-days combine to one draw (`combine_station_day`); the
tally scores one combined draw per station-day (`_combined_draws_for_looks`).
**Validation results (replaces S5), all in `tests/unit/`:**
- Closed-form reductions (k=1 Bernoulli, qty² scaling, non-negativity over
  an admissible grid) — GREEN, `test_current_rung_hold_v2_score.py`.
- H0 Monte-Carlo (seed 20260914, 2000 reps, k∈{1,2,3}, mixed qty∈{1,2,3}):
  `Var(S_terminal)`=**1.0003** (target [0.85,1.15]) — GREEN. One-sided
  efficacy-crossing rate=**~5.9%** (0.0592@5000reps, 0.058@2000reps) vs
  target ≤alpha+0.01=0.035 — **FAILS**; a qty≡1 control (same method)
  measures ~1.1–1.3%, in tolerance. Mixed qty (up to 9× a single Bernoulli
  variance term) saturates `I` faster than the schedule assumes; the
  realised-t interpolation under-covers. Committed `xfail(strict=True,...)`
  with the measured rate (`test_multi_position_validation_2026_09_14.py`).
  Per R3-3 this does NOT block Increment A (qty≡1); artefact NOT re-solved.
- `inputs_sha256` recomputed from the artefact's own inputs matches the pin
  `471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c` — GREEN.
- Static `I_max` bound: grid search over admissible BE tuples (Σ≤1, k≤4,
  qty=1) gives max `Var_H0`=0.25=`i_max/n_max` exactly — a multi-rung
  station-day structurally cannot exceed `i_max` at qty≡1 — GREEN, no new
  tally refusal needed.
- Tally identity floor (math-review addendum): a realistic multi-station
  fixture and the REGISTERED v2 manifest both give S/I/n/verdict/rendered
  text identical between the combined-draw path and a `score()`-only
  reference — GREEN, `test_family_tally_v2.py`.
**Increment B:** carries real qty through sizing/scorer/store. Before
Increment B relies on this artefact at qty>1, the H0 crossing-rate check
must be re-run at the real qty distribution and pass; re-solve only then.
**Open operator-only budget questions:** (1) with qty derived from the
per-position cap, one order can spend the whole cap instead of a small
fraction — is the current value still the intended per-order spend? (2) the
daily budget is reachable in one afternoon across multiple stations × N
rungs — confirm it is still the intended daily ceiling.
**Hard invariants:** Nautilus immutable (extension-only); `allow_short`
stays `False`; no safety/settlement/contract test weakened or deleted; no
operator-reserved control assigned or named by env-var name here;
live-trading enablement and the NO-SEND egress firewall untouched; the
boundary artefact, `i_max`, `n_max`, `alpha`, `look_step` unchanged —
re-validated, never re-derived.