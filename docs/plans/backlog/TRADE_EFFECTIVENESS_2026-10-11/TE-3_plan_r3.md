# TE-3 plan r3: NO-side cheap-entry hypothesis (revision of r2; 2026-10-11; read-only planning; suggested path `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r3.md`)

This plan read no M1-v3 report or outcome. It read `ask_threshold` (0.90, inclusive) from `docs/evidence/m1v3/PREREG.json`, as permitted. It computes no outcome statistic on the tape. The only outcomes touched are the 3 live NO fills, scored through the bot's own band rule (§2).

## 0. Verdict
- **No motivating anomaly survives the corrected scoring.** The band-semantics correction (`reviews/CORRECTION_2026-10-11_band_semantics.md`) puts the NO side at 3 fills / 1 win / +0.65.
  - Only MDW 09-22 won. MIA 09-15 NO lost (tmax 93 is inside [92,93]).
  - P(≥ 1 win of 3 | p = 0.12) = 1 − 0.88³ = **0.318528**, which is unremarkable. The r2 statistic 0.039744 is **withdrawn**.
  - The ledger verdict below stands on its own and needs no anomaly.
- **Primary basis (R4, mechanical):** a `recompute_mde` desk recompute gives n = 1486 station-days for MDE ≤ 0.04. The bound is cited to the H-NO-SIDE ruling §3. No `register_hypothesis` call was made and no record was written. Intake would return `UNDERPOWERED_NOT_REGISTERED`, rationale "structurally infeasible on PM.us".
  - n_raw = 1485.16 → **1486** at α = 0.05/4. At the stricter programme α (0.025/4) n = **1743**.
  - PM.us has 5 stations, so the most any window can supply is 5 per day. For a 2026-10-12 start the window is 98 days (ceiling **490**). A 2026-10-26 start gives 84 days (ceiling **420**).
  - Ledger MDE at 490 is **0.0696** (0.0754 at α 0.025/4). At 420 it is **0.0752** (0.0815). Every figure exceeds 0.04.
  - The result holds at any rate, because the ceiling is physical (5 stations × days).
- **Corroboration only (Lane E, not structural), scoped to δ = 0.04:** a model-free forward test at α = 0.05 is infeasible at the central and low observed rates.
  - At δ = 0.04 the high rate admits one corner under the normal approximation: p0 = 0.07, n = 292, verdict 2027-01-20. The exact test misses the backstop by 1 day (2027-01-26).
  - Some cells at δ ≥ 0.05 are feasible (§3). Dismissing them rests on §4 prior grounds only.
  - r1's "structural, independent of the rate" claim stays withdrawn.
- **Deliverables:** one ruling (Appendix A), bookkeeping, and a dormant WP-4. There is **no new code** and no collector. WP-1 (the census tool) stays dropped.

## 1. How TE-3 differs from M1-v3, NO-1 and H-NO-SIDE
| | M1-v3 (frozen, read-once ≥ 12-07) | TE-3 |
|---|---|---|
| Entry | NO ask ≥ 0.90 (NO favourite), first Depth10 row in [12:00,13:00) UTC | NO ask in [0.06, 0.12] (YES bid 0.88–0.94), interior rung, 12–16 LST |
| Fair-odds prior | favourable side (D_12Z cell −1.4¢; R11 expects NO-EDGE) | adverse side (M1 YES 0.0–0.1 cells are reliable losers, −1.7 to −2.3¢). Carried from r1, not recomputed |

- The ask bands are disjoint, so a TE-3 entry can never be an M1-v3 take.
- **Never pool the two samples.** One station-day can hold an M1-v3 NO favourite on one rung and a TE-3 longshot on the current rung. The outcomes are dependent.
- **NO-1 / PREREG v3a** already registers the NO leg: take NO iff `1 − P_HOLD_UPPER > NO ask + fee`, current rung only. All 3 live NO fills came from that rule. It is dead in practice for three reasons:
  1. `cont` and `v4` are halted, and `fq_v1` is the sending family.
  2. The frozen `P_HOLD_UPPER` table is unsafe on the NO side (memory `archive-table-train-serve-skew`).
  3. **AUD-01a:** `no_side_calibration_gate_cleared` is `False` by default (`config.py:247`). The gate at `decision.py:484-485` refuses every NO candidate as `no_side_calibration_unsafe`.
- **H-NO-SIDE-2026-09** is already `UNDERPOWERED_NOT_REGISTERED` (MDE 0.0890 at the stated n). Its record covers the `no_side_hunting` class. TE-3 cites it and registers nothing new.
- **Erratum:** H-NO-SIDE quotes n ≈ 1487 for MDE ≤ 0.04. The recomputed figure is **1486** (n_raw 1485.162).

## 2. Verified premises
- **Fills** (`~/.local/share/breezy/state/exec_polymarket_us.sqlite`; truth `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`).
- **Scoring.** Re-verified 2026-10-11 through `breezy.analysis.labeling.instrument_facts.bucket_facts_from_instrument_id` (inclusive `[lower_f, upper_f]`, `WeatherBucketFacts.contains`). The band rule was not hand-rolled. NO wins iff `not contains(tmax)`.

| Fill | Instrument | Interval | CLI tmax | YES in band | Cost | Result |
|---|---|---|---|---|---|---|
| CGW8DJ23PVB2 | MIA 09-15 `gte92lt93^no` | [92,93] | 93 | True | 0.09, fee 0 | **NO loses, −0.09** |
| CNC3HJD66WP9 | MDW 09-22 `gte62lt63^no` | [62,63] | 64 | False | 0.12 + 0.01 | **NO wins, +0.87** |
| CMRS7Y99WWPE | MIA 09-21 `gte88lt89^no` | [88,89] | 88 | True | 0.12 + 0.01 | **NO loses, −0.13** |

  - Net = −0.09 + 0.87 − 0.13 = **+0.65**, matching the corrected audit (3 fills / 1 win).
  - The scorer's output for the three instrument ids was `92 93 / 93 / True`, `62 63 / 64 / False` and `88 89 / 88 / True`.
- The 3 NO fills are all the NO fills among the 34 (31 YES + 3 NO). Selection is by side, not by outcome. They are still SEARCH data and power nothing.
- r2's claim that the memory `hunt-window-opens-after-repricing` is wrong on the 09-15 rung is dropped. The CLI value 93 is simply inside [92,93].
- **Price semantics:** the `^no` price is `1 − best YES bid (size ≥ 1)` (`decision.py:455-496`; `market_calibration_scan.py:242`). An empty bid side returns None and is never synthesised.
- **Executable band:** `config.py:234-235` gives 0.05 < ask < 0.95 (strict). TE-3 fixes **[0.06, 0.12]** throughout.
- **Fee:** `decision.py:320-327`. Fee = `0.0695·a·(1−a)`, ROUND_HALF_EVEN to the cent: 0.00 at asks 0.06–0.07 and 0.01 at 0.08–0.12.
- **Break-even (net EV zero, slippage 0.01):** p0 = ask + fee + 0.01.

| Ask | 0.06 | 0.07 | 0.08 | 0.10 | 0.12 |
|---|---|---|---|---|---|
| p0 | 0.07 | 0.08 | 0.10 | 0.12 | 0.14 |

  - The band's p0 runs **0.07 to 0.14**.
- **Ledger constants** (`hypothesis_ledger.py`): `PROGRAMME_ALPHA` 0.05 (:177), `MAX_HYPOTHESES` 4 (:181), `POWER` 0.80 (:192), `VARIANCE_BOUND` 0.25 (:196).
  - Per-variant α = 0.05/4 = 0.0125, z-sum 3.083024. At programme FWER 0.025 (RA-13 :5, :87), α′ = 0.025/4 = 0.00625 and z-sum 3.339327.
  - `recompute_mde` (`:859-870`) is the only admitted derivation. An MDE above the bound yields `UNDERPOWERED_NOT_REGISTERED` (`:1125`). The bound 0.04 is cited to H-NO-SIDE §3.
- **Governance:**
  - Backstop 2027-01-25 (RA-13 §3). It is firm (B-5) and not extended by capture holes (L-38).
  - B-3: any count on tape after 2026-09-25 spends H-ARCHIVE-RECAL CONFIRM days.
  - B-2: no PM.us n, bound or α is reused for Kalshi.
  - Revival routes: R4, and FQ-v2 T1–T3 (R3V §3.2).
  - Prior art for the effect's sign: L-9 amendment (`LESSONS.md:492-505`).
- **Census provenance (outcome-free; row counts only; re-run 2026-10-11, identical output):**

| Item | Value |
|---|---|
| Files read | `offer_tape_2026-09-{16,17,19,20,21,22,23}.jsonl.gz`, all dated ≤ 2026-09-25 |
| Full days | 4 (09-16, 20, 21, 22; each over 400 KB) |
| Coverage holes | 09-17, 09-19, 09-23 (each under 7 KB); no file for 09-18 or after 09-23 |
| Filter | `side == "NO"`, ask in [0.06, 0.12], climate_day ≤ 2026-09-25 |
| Distinct rungs | **9** = **8 interior finite `gte…lt…` + 1 open-lower tail** (SFO 09-20 `lt65`, excluded from the rate) |
| Interior per climate day | 09-16: 3, 09-20: 1, 09-21: 2, 09-22: 2 |
| Station-days | The 8 interior rungs are 8 distinct station-days |
| Hours | hour_lst 12–16 |
| Reached `take` | **2** (MIA 09-21, MDW 09-22; the same 2 as the fills above) |
| Refused `observation_ambiguous` | 6 of the other interior rungs and the open tail (7 of 9 distinct rungs). MIA 09-21 shows both the refusal and the take |

  - It reads no `replay_sufficiency` row and no truth, so it is B-3 clean and outcome-free. The corrected scoring changes the fills' outcomes only, not one census row. The MIA 09-15 fill has no tape file and is not in the count.
  - The command is in Appendix B.

## 3. Arithmetic (every figure recomputed with `/home/jon/breezy/.venv/bin/python`; formulas in Appendix C)
**Fills statistic.** P(≥ 1 of 3 | 0.12) = binom.sf(0, 3, 0.12) = 1 − 0.88³ = **0.318528**. P(≥ 1 of 3 | 0.07) is not needed.

**Rate.**
- λ̂ = 8 interior rungs / 4 full days = **2.00 per day**.
- Exact Poisson (Garwood) 95%: lower = χ²₀.₀₂₅(16)/2/4 = 0.86346, upper = χ²₀.₉₇₅(18)/2/4 = 3.94080, i.e. **[0.863, 3.941]**.
- Sensitivity: with all 7 file-days as exposure, λ̂ = 8/7 = 1.143 [0.493, 2.252]. The 4-day denominator is the favourable one.
- The tape is the node's own, so the days are not a random sample.

**Available trials.** n_avail = λ·κ·T, κ = 0.8 (assumed coverage haircut), computed with the **unrounded** λ and floored to an integer. The floor is conservative.

| Case | λ | n_avail, T = 98 (unrounded) | n_avail, T = 84 |
|---|---|---|---|
| Low | 0.8635 | 67 (67.7) | 58 |
| Central | 2.00 | 156 (156.8) | 134 |
| High | 3.9408 | 308 (308.96) | 264 |
| Ceiling (5/day, κ = 1) | – | **490** | **420** |

- T = 98 means first_forward_day 2026-10-12 and last_forward_day 2027-01-17 (backstop minus an 8-day truth lag, the M1-v3 R7 precedent). T = 84 means a first day of 2026-10-26. Neither is a scheduled freeze.
- Same-day correlation across the 5 stations shrinks the effective n under a calendar-day cluster bootstrap. It strengthens the verdict and is not modelled.

**MDE, two non-comparable families (p0 = 0.12, power 0.80).**
- (a) Bernoulli MDE, α = 0.05: the smallest δ with exact-binomial power ≥ 0.80.

| n | Normal approx | Exact |
|---|---|---|
| 156 (central) | 0.069 | 0.077 |
| 308 (high) | 0.048 | 0.052 |
| 490 / 420 | 0.038 / 0.041 | 0.040 / 0.044 |

- (b) Ledger MDE = z-sum·0.5/√n (pinned sd 0.5):

| n | α = 0.0125 (z-sum 3.083024) | α′ = 0.00625 (z-sum 3.339327) |
|---|---|---|
| 156 | 0.1234 | 0.1337 |
| 308 | 0.0878 | 0.0951 |
| 420 | 0.0752 | 0.0815 |
| 490 | 0.0696 | 0.0754 |
| required for MDE ≤ 0.04 | n_raw 1485.162 → **1486** | n_raw 1742.360 → **1743** |

- (b) is about 2.4 times the Bernoulli sd at p = 0.12. Do not compare (a) and (b).

**Required n, exact one-sided binomial** (smallest n with power ≥ 0.80, p1 = p0 + δ, α = 0.05). Shown as normal/exact.

| p0 | δ = 0.04 | δ = 0.05 | δ = 0.06 | δ = 0.08 |
|---|---|---|---|---|
| 0.07 | 292/311 | 193/204 | 138/155 | 82/90 |
| 0.10 | 386/403 | 253/270 | 179/193 | 105/117 |
| 0.12 | 445/464 | 290/307 | 205/219 | 119/127 |
| 0.14 | 500/516 | 325/341 | 229/239 | 133/145 |

- At α = 0.0125, δ = 0.04: 436/476, 582/613, 672/705, 758/787 for p0 = 0.07, 0.10, 0.12, 0.14. These are unchanged from r2.

**Feasible cells (n_min ≤ n_avail, T = 98, α = 0.05).** Both the normal and the exact figure must fit unless noted.
- **Central (156):** p0 = 0.07 at δ = 0.06 (138/155) and δ = 0.08; p0 = 0.10, 0.12, 0.14 at δ = 0.08 only. At δ = 0.04 and 0.05 nothing fits.
- **High (308):**
  - δ = 0.04: p0 = 0.07, normal only (292); the exact figure 311 does not fit.
  - δ = 0.05: p0 = 0.07 (193/204), 0.10 (253/270), 0.12 (290/307). p0 = 0.14 does not fit (325/341).
  - δ = 0.06: p0 = 0.07, 0.10, 0.12, 0.14 all fit.
  - δ = 0.08: all four fit.
- Low (67): nothing fits.
- Dismissing the δ ≥ 0.05 cells rests on §4 prior grounds only.

**Verdict dates.** The date is the last forward day needed plus 8 days. The first forward day is 2026-10-12. The backstop is 2027-01-25.

| Required n | Low | Central | High |
|---|---|---|---|
| 311 (p0 0.07, δ 0.04, exact) | 2028-01-13 | 2027-05-02 | 2027-01-26 (1 day late) |
| 292 (same cell, normal) | 2027-12-16 | 2027-04-20 | **2027-01-20 (inside)** |
| 403 (p0 0.10, exact) | 2028-05-25 | 2027-06-28 | 2027-02-24 |
| 464 (p0 0.12, exact) | 2028-08-21 | 2027-08-05 | 2027-03-16 |
| 155 (p0 0.07, δ 0.06, exact) | not reachable | 2027-01-24 (inside) | inside |
| 1486 (ledger) | not reachable (over 5 years) | 2029-05-05 | 2028-02-03 |

- The ledger n at the 5/day physical maximum needs 298 days (1486/5 = 297.2, rounded up), against the 98-day window.

**Corroboration, stated honestly.**
- At **δ = 0.04** the Lane-E test is infeasible at the central and low rates for every p0. At the high rate it fits only at p0 = 0.07 under the normal approximation. The exact test is 1 day late.
- That corner needs every entry at ask 0.06 exactly and the 95% upper rate. The band-pooled p0 is mixed (0.07–0.14), so the corner is **not reachable** in practice.
- At δ ≥ 0.05 the feasible cells above exist. The ledger bound 0.04 is a ledger rule and does not apply to Lane E.
- A WINNER at any such cell nominates an admissibility filter, not a family.

## 4. Prior grounds for treating δ ≥ 0.05 as implausible (no ledger bound invoked)
- The fair-odds prior is adverse (§1). The market already prices this region as a lottery already lost (L-9 amendment).
- The band was chosen after seeing 3 fills and 9 tape rungs. That is SEARCH, and with the anomaly gone the fills carry no signal (1 of 3 at p ≈ 0.12, P = 0.3185). P(WINNER) is therefore close to α.
- Observation ambiguity refused 7 of 9 candidate rungs, so the bot's own rule would rarely fire. Real-money fillability is unmeasured.
- These are priors, not measurements. They are the only basis for excluding the feasible δ ≥ 0.05 cells, and the ruling says so.

## 5. Stage 0 STOP conditions (apply to the ruling work and to any dormant WP-4 build)
1. **STOP if** the M1-v3 PREREG blob differs from `adb1cd8b`/`6fbc4f6b` (`git log -- docs/evidence/m1v3/PREREG.json`, `check_frozen_blob`).
2. **STOP if** any artefact opens a path under `docs/evidence/m1v3/` other than PREREG.json for the band constant, or imports `no_longshot_pooled_test`.
3. **STOP if** any count touches a climate day after 2026-09-25 (RA-13 B-3). This applies to tape, `replay_sufficiency` and offer-tape inputs alike.
4. **STOP if** any tape statistic uses the 3 NO fills. They are premises only. The band rule for any scoring must go through `bucket_facts_from_instrument_id`, never a hand-rolled test.
5. **STOP if** a number in the ruling cannot be reproduced from Appendix C or B.

## 6. Work packages
Build route is unchanged: Grok → Codex → Claude tdd-guide; the coordinator runs `scripts/ci/run_tests_no_egress.sh`. No code is written for WP-2/WP-3.

**WP-1: DROPPED (YAGNI).** A fresh census cannot change a ledger verdict or the corroboration. Only the preliminary census (§2) is quoted, with its provenance.

**WP-2: the ruling (docs only).**
- File: `docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_<date>.md`, drafted in Appendix A.
- Verdict token: `UNDERPOWERED_NOT_REGISTERED`, rationale "structurally infeasible on PM.us". It cites H-NO-SIDE-2026-09.
- No `_UNDERPOWERED_REGISTRATIONS` entry is added.
- It goes through a prediction-market-reviewer pass before the coordinator saves it.

**WP-3: bookkeeping.**
- Update the TE-3 row in `docs/core/PROGRESS.md` to the ruling file, with the §3 numbers.
- Write `reviews/TE-3-final.md` (the convergence record).
- Record a lesson via the lessons skill, after deduping: **a hypothesis chosen from a handful of fills cannot be powered by them; a "structural" claim must survive its own sensitivity table; and an outcome re-score must go through the bot's own band function.**

**WP-4 (CONTINGENT, DORMANT).** It builds only if a re-open trigger fires and a new ruling says so. A WP-4 re-plan re-opens python F4–F10 and arch G7/G8 as review inputs.
- Shape: an offline Lane-E tool in the `no_longshot_pooled_test.py` pattern. It uses `check_frozen_blob` and a freeze-introduction check. It does not touch the CRH strategy shadow path.
- **Binding requirements it inherits:**
  1. **Every input refuses climate days after 2026-09-25** (arch G1, python F3): tape, `replay_sufficiency` rows and offer tape. The refusal sits at function level, not only the CLI, and clamps the UTC `hi_ns` too (the PT tail of climate day 09-25 reads UTC 09-26).
  2. **LST → UTC conversion** with `std_utc_offset_hours` (`sites.py:401`), **reusing `replay_sufficiency.decision_window_ns`** (`replay_sufficiency.py:207-222`) for the window. It must not re-derive it (L-1). It reads one tape per UTC day the window touches; a PT station's window runs 20Z to 01Z next day (python F1).
  3. **A standalone no-lookahead check on the LST climate-day end.** `assert_no_lookahead` and `Observation` cannot be used, because they need truth and a UTC day end (python F2).
  4. `_observe_row` and `_scan_day` are off limits (they take a `TruthRow`). `classify_directory`, `_index_directories`, `no_ask`, `_levels` and `_first_row` are reusable.
  5. Any outcome scoring uses `bucket_facts_from_instrument_id` with its inclusive interval. Fixtures include an upper-edge-inclusive case (e.g. MIA 09-15).
- Tests mirror M1-v3: forward-day filter from git, no verdict before the read date, read-once, lookahead gives INVALID, decision ts < outcome ts.
- Sanity guard: "ask ≤ 0.12 with hit rate > 0.35 is a bug signature" (memory `implausible-result-is-a-leak`).

## 7. Dormant PREREG skeleton (never frozen on PM.us)
- **Id / lane:** `H-NO-CHEAP-CURRENT-RUNG` / Lane E, outside the AUT-S K ledger, as M1-v3 is.
- **H1:** buying NO at the Depth10 ask on an interior rung, with NO ask in [0.06, 0.12] and YES bid ≥ 0.88, at the first qualifying row in 12–16 LST, has positive mean net EV per take. It is named "interior rung, YES bid ≥ 0.88" and does not claim "current rung", since there is no running-max input.
- **Net EV:** `hit − (ask + fee + 0.01)`, fee per §2.
- **Unit:** one trial per station-day; calendar-day cluster bootstrap with zero-take days kept.
- **Statistic:** K = 1, one-sided, α = 0.05. A ledger-registered variant would use α′ = 0.0125 (or 0.00625 at programme FWER 0.025).
- **Looks:** a single look, counts-only before the read date.
- **Floors:** n ≥ the §3 exact n for the realised p0, at least 40 days, at least 5 loss days.
- **KILL:** verdict date after 2027-01-25, or any floor unmet at the read date.
- **Pins:** SEARCH/CONFIRM split at the freeze commit. The three fills and all pre-09-26 tape are SEARCH.

## 8. Re-open triggers, each with its next action
| # | Trigger | Next action |
|---|---|---|
| 1 | PM.us lists enough daily-high stations that λ·κ·T ≥ 1486 (1743 at α′ 0.00625) inside a window ending before the backstop | Planner re-runs Appendix C with the new station count. 16 stations × 98 days = 1568 only at κ = 1 with every station-day qualifying, so this is nominal, not a plan. Lapses 2027-01-25 |
| 2 | **None needed: a desk action available now** | Propose a successor-ruling candidate class to the WA-3 class table (MAX_HYPOTHESES_K = 3 is full; the table changes only by successor ruling, L-12). Size it only via K-2a §5 (bound_K, n_K, shared α). Exclude the 5 shared cities from the holdout. Reuse no PM.us n, bound or α (B-2) |
| 3 | A ruling raises the plausibility bound, using outcome-free evidence | Re-run `recompute_mde`. The bound must reach **≈ 0.088 at the feasible n = 308** (≈ 0.095 at α′ 0.00625), and **≈ 0.123 at n = 156** (≈ 0.134). The 490 ceiling (0.0696 / 0.0754) needs κ = 1 with every station-day qualifying, so it is necessary but not sufficient. Lapses 2027-01-25 |
| 4 | FQ-v2 **T2 (new sender) or T3** fires and requests it. T1 (an M1-v3 CONFIRM) has no bearing, because TE-3 is never pooled with M1-v3 | Planner re-plans WP-4 under that T-ruling with the §6 inherited requirements. Lapses 2027-01-25 |

- **Lane-E feasibility expires** for any freeze after **2026-10-17** (the δ = 0.04 corner: 292/(3.9408·0.8) → 93 days; 2027-01-17 less 92 days). The δ = 0.06 central cell expires after 2026-10-13 (exact, 155) or 2026-10-23 (normal, 138).

## 9. Dependencies and risks
- The ruling needs only the files in §2. The M1-v3 read (≥ 12-07, read-once) is untouched and never awaited.
- **Risk: the census is 4 days.** The ledger verdict does not depend on it. The corroboration dates do, and the ruling quotes the full interval and the 8/7 sensitivity.
- **Risk: sides confused.** TE-3 is the NO longshot. The §1 table and the never-pool rule cover it.
- **Risk: anecdote pressure.** The ruling states the corrected fills (1 win of 3, +0.65, P(≥ 1 | 0.12) = 0.3185). The earlier "2 wins" framing came from a half-open band rule that the bot does not use.
- **Risk: firewall.** Declaring this infeasible touches no post-09-25 tape. A collector would spend CONFIRM days.
- **Risk: scope creep of the ruling.** Appendix A §8 states what it does not decide.

## 10. Non-goals
No live order, arming, halt, permit or operator cap. No M1-v3 file or PREREG change. No new family or `ContinuousRungHoldStrategy` shadow. No resting-bid design. No post-09-25 count. No Kalshi build. No outcome statistic on the tape corpus. No new code.

## 11. Goal-state map
| Goal item | Where met |
|---|---|
| Documented ruling (covered or infeasible) | WP-2 and Appendix A; the part covered by NO-1 / v3a is in §1 |
| Feasibility number | §3: 2.00 per day [0.863, 3.941], preliminary; the ledger ceiling 490 (or 420) against 1486 (1743) |
| Verdict date at the rate | §3 table: central 2027-08-05 (p0 = 0.12) or 2029-05-05 (ledger); every central δ = 0.04 case is past the backstop |
| INFEASIBLE with the number | R4: n 1486 against ceiling 490; MDE 0.0696 against bound 0.04 |
| Shadow measurement path | Not built, by the infeasibility rule. WP-4 and §7 hold the dormant design |
| Revival path with named actions | §8 |
| Arming and live sending | Out of scope |

## 12. Changes from r2
| ID | Finding | Disposition |
|---|---|---|
| Merge 0 | Band-semantics correction is binding | Done. Fills re-verified through `bucket_facts_from_instrument_id`: MIA 09-15 NO loses (−0.09), MDW 09-22 wins (+0.87), MIA 09-21 loses (−0.13); 3 fills / 1 win / +0.65. P(≥ 1 of 3 \| 0.12) = 0.318528. 0.039744 withdrawn. §0, §1 (erratum), §2, §4, §9 and Appendix A §1 rewritten. Appendix B re-run: output identical. Ruling says "no motivating anomaly survives the corrected scoring; the ledger verdict stands on its own" |
| Merge 1 (Domain S1/S2) | Lane-E corroboration scoped to δ = 0.04 | Done. §0, §3 "Feasible cells" and "Corroboration" list the feasible δ ≥ 0.05 cells (central p0 0.07 δ ≥ 0.06; several at high); §4 says dismissal rests on priors only |
| Merge 2 (Domain S3/S4/S5) | Corner text, flooring, unrounded λ | Done. Exact test is 1 day late (2027-01-26); the corner needs every entry at ask 0.06 and the 95% upper rate and is not reachable at a mixed p0 (§3, Appendix A §4). n_avail flooring stated; Appendix C uses unrounded λ |
| Merge 3 (Gov F1) | "What this does NOT decide" | Added as Appendix A §8 |
| Merge 4 (Gov F2) | Trigger 2 rewritten | Done. §8 row 2: desk action now; WA-3 successor class; K-2a §5 sizing; 5 shared cities excluded; B-2 |
| Merge 5 (Gov F3) | T-trigger and expiries | Done. §8 row 4 names T2/T3 (T1 irrelevant); Lane-E feasibility expires after 2026-10-17; triggers 1, 3, 4 lapse 2027-01-25 |
| Merge 6 (Gov F4) | Both α cases | Done. n 1486 and 1743; MDE 0.0696/0.0754 at 490, 0.0752/0.0815 at 420. §0, §3, §8 row 3, Appendix A §3 |
| Merge 7 (Gov F5) | Trigger 3 at feasible n | Done. ≈ 0.088 at 308, ≈ 0.123 at 156 (0.095 / 0.134 at α′) |
| Merge 8 (Gov F6) | Reuse `decision_window_ns` | Done. §6 WP-4 req. 2 |
| Merge 9 (Gov F7/F8/F9) | Wording, erratum, re-plan inputs | Done. "`recompute_mde` desk recompute; intake would return…" with the bound cited to H-NO-SIDE §3 (§0, Appendix A §3); erratum 1487 → 1486 (§1); WP-4 re-plan re-opens py F4–F10 and arch G7/G8 (§6) |
| Codex r2 | READY 98, no findings | No change. Appendix B and the Appendix C spot checks reproduce |
| Added | WP-4 req. 5, STOP 4, lesson text | Inclusive scoring via `bucket_facts_from_instrument_id`; hand-rolled band rules banned |

## Appendix A. Draft ruling text (`docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_<date>.md`)
```
# RULING TE-3: NO-side cheap-entry longshot (NO ask 0.06-0.12)
Verdict: UNDERPOWERED_NOT_REGISTERED (structurally infeasible on PM.us; a recompute_mde desk
recompute, intake would return this token). No PREREG is frozen. No tape outcome statistic was
computed. No tape after 2026-09-25 was read (RA-13 B-3). No M1-v3 outcome data was read.

1. Hypothesis. Buying NO at the Depth10 ask on an interior rung with NO ask in [0.06, 0.12] has
   positive net EV. It was prompted by 3 live NO fills, scored through the bot's inclusive band
   rule (bucket_facts_from_instrument_id): 1 win (MDW 09-22, +0.87), 2 losses (MIA 09-15 -0.09,
   MIA 09-21 -0.13), net +0.65. P(>=1 win of 3 | p=0.12) = 0.318528. No motivating anomaly
   survives the corrected scoring; the ledger verdict stands on its own. The fills are all the
   NO fills among 34 and are SEARCH data.
2. Delta. Disjoint from M1-v3 (NO ask >= 0.90). Samples are never pooled. The bot's NO rule
   (PREREG v3a, NO-1) is dead: cont/v4 halted, P_HOLD_UPPER unsafe on the NO side, AUD-01a
   no_side_calibration_gate_cleared=False. H-NO-SIDE-2026-09 already holds the no_side_hunting
   class as UNDERPOWERED_NOT_REGISTERED; this ruling cites that record and registers nothing new.
   Erratum: H-NO-SIDE quotes n ~1487; the recomputed figure is 1486.
3. Basis (R4, mechanical; MDE bound 0.04 per H-NO-SIDE section 3). Variance 0.25, power 0.80.
   - alpha 0.05/4 = 0.0125, z-sum 3.083024: n_raw 1485.16, n = 1486 station-days.
   - alpha 0.025/4 = 0.00625 (RA-13 programme FWER), z-sum 3.339327: n_raw 1742.36, n = 1743.
   PM.us has 5 stations: a 98-day window (2026-10-12..2027-01-17, backstop 2027-01-25 less an
   8-day truth lag) yields at most 490; 420 for a 2026-10-26 start. Ledger MDE at 490 = 0.0696
   (0.0754 at alpha 0.00625); at 420 = 0.0752 (0.0815). All exceed 0.04. The result holds at
   any rate.
4. Corroboration (Lane E, alpha 0.05, power 0.80, delta = 0.04 only). Preliminary census: 8
   interior rungs over 4 full tape days, lambda = 2.00/day, exact Poisson 95% [0.863, 3.941];
   the 9th rung is an open tail and excluded; 2 of the 8 reached take; 7 of 9 distinct rungs were
   refused observation_ambiguous. n_avail (kappa 0.8, T 98, floored) = 67 / 156 / 308
   (low/central/high). Required exact-binomial n at delta 0.04 is 311 to 516 over p0 0.07-0.14.
   The test is infeasible at the central and low rates. At the high rate it fits only at p0 =
   0.07 under the normal approximation (n 292, verdict 2027-01-20); the exact test (n 311)
   misses the 2027-01-25 backstop by 1 day (2027-01-26). That corner needs every entry at ask
   0.06 and the 95% upper rate, so a band-pooled test (mixed p0) cannot reach it. This is
   corroboration, not a structural claim. At delta >= 0.05 some cells fit (central: p0 0.07,
   delta >= 0.06; high: several); excluding them rests on priors only (adverse fair-odds prior;
   SEARCH-picked band; observation_ambiguous refusals), not on a measurement.
5. Caveats. Four days; coverage holes at 09-17, 09-19, 09-23 and none after 09-23; sensitivity
   8/7 = 1.14/day. Same-day cross-station correlation shrinks effective n further. Floored
   n_avail, unrounded lambda.
6. Re-open triggers and next actions: (1) PM.us station count lifts lambda*kappa*T to >= 1486
   (1743 at alpha 0.00625) before the backstop: re-run Appendix C; (2) desk action now: propose a
   successor-ruling candidate class to the WA-3 table, size via K-2a section 5 (bound_K, n_K,
   shared alpha), exclude the 5 shared cities, reuse no PM.us n/bound/alpha (B-2); (3) bound
   raised by an outcome-free ruling: re-run recompute_mde, needs ~0.088 at n=308 (0.095 at alpha
   0.00625) or ~0.123 at n=156 (0.134); 0.0696/0.0754 at the 490 ceiling is necessary, not
   sufficient; (4) FQ-v2 T2/T3 fires and requests it: re-plan WP-4 (T1 is irrelevant). Lane-E
   feasibility expires for any freeze after 2026-10-17. Triggers 1, 3, 4 lapse 2027-01-25.
7. Dormant WP-4 requirements: inputs refuse climate days after 2026-09-25; LST->UTC multi-day
   tape reusing replay_sufficiency.decision_window_ns; standalone no-lookahead check on the LST
   day end; scoring via bucket_facts_from_instrument_id. A re-plan re-opens python F4-F10 and
   arch G7/G8 as review inputs.
8. What this does NOT decide. It does not dispose of the NO-side class for RA-13 section
   6.6 / B-1. It does not kill the NO-side requirement. It does not fire R4. Arming, halts, caps,
   the NO-SEND firewall, Nautilus, allow_short and every PREREG are untouched.
```

## Appendix B. Census command (read-only; reads files dated ≤ 2026-09-25 only)
```
/home/jon/breezy/.venv/bin/python -I - <<'EOF'
import glob,gzip,json,re,collections
from decimal import Decimal as D
UNTIL="2026-09-25"; DIR="/home/jon/.local/share/breezy/catalog/quote_tape/decisions/"
seen={}
for f in sorted(glob.glob(DIR+"offer_tape_2026-09-*.jsonl.gz")):
    if re.search(r"(\d{4}-\d{2}-\d{2})",f.rsplit("/",1)[1]).group(1)>UNTIL: continue
    for ln in gzip.open(f,"rt"):
        r=json.loads(ln)
        if r.get("side")!="NO" or r["climate_day"]>UNTIL or r.get("ask") is None: continue
        if not D("0.06")<=D(r["ask"])<=D("0.12"): continue
        slug=r["instrument_id"].split("^")[0]
        shape="interior" if re.search(r"-gte\d+lt\d+f?$",slug) else "open"
        e=seen.setdefault(r["instrument_id"],{"shape":shape,"day":r["climate_day"],"taken":False})
        e["taken"]|=(r["decision"]=="take")
c=collections.Counter((e["shape"],e["taken"]) for e in seen.values())
print(len(seen),dict(c),sorted(collections.Counter(e["day"] for e in seen.values() if e["shape"]=="interior").items()))
EOF
```
- Output (re-run 2026-10-11, identical to r2): `9 {('interior', False): 6, ('open', False): 1, ('interior', True): 2} [('2026-09-16', 3), ('2026-09-20', 1), ('2026-09-21', 2), ('2026-09-22', 2)]`.
- File sha256 prefixes (first 16 hex): 16: `405fc4fbda1acb7f`, 17: `8fd14aa8c0be976c`, 19: `0ec7467d5ebb08ba`, 20: `21122f7c18963442`, 21: `f179550af6eee93d`, 22: `a6e1d7b752f7f961`, 23: `ea2870e9d8dd1d33`.
- The census is outcome-free, so the band-semantics correction does not change it.

**Fill re-scoring (premises only; never a tape statistic).** Run with `/home/jon/breezy/.venv/bin/python`:
```
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id as b
# truth: {(station, climate_day): tmax_f} from truth_cli_finals.csv, rows with non-empty tmax_f
f = b("tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US")   # lower_f 92, upper_f 93
no_wins = not f.contains(tmax)                                     # inclusive [lower_f, upper_f]
```
- Output: MIA 09-15 `92 93 / 93 / contains True → NO loses`; MDW 09-22 `62 63 / 64 / False → NO wins`; MIA 09-21 `88 89 / 88 / True → NO loses`.

## Appendix C. Formulas (all run with `/home/jon/breezy/.venv/bin/python`, scipy 1.18.1; unrounded λ)
```
Poisson(k,T): lo = chi2.ppf(0.025, 2k)/2/T ; hi = chi2.ppf(0.975, 2k+2)/2/T       # k=8,T=4 -> 0.86346, 3.94080
n_avail = floor(lambda * 0.8 * T) ; ceiling = 5 * T                                # T=98 or 84; 156.8->156, 308.96->308, 67.7->67
exact n_min(p0,d,a): smallest n with binom.sf(c-1, n, p0+d) >= 0.80,
    c = smallest integer with binom.sf(c-1, n, p0) <= a                           # a=0.05, 0.0125
normal n_min = ceil(((z(1-a)*sqrt(p0 q0) + z(0.80)*sqrt(p1 q1))/d)^2)
ledger: zsum(a) = z(1-a)+z(0.80), a = 0.0125 -> 3.083024 ; a = 0.00625 -> 3.339327
    n_raw = (zsum*0.5/0.04)^2 : 1485.162 -> 1486 ; 1742.360 -> 1743
    MDE(n) = zsum*0.5/sqrt(n)
      a=0.0125 : n=156 0.1234, 308 0.0878, 420 0.0752, 490 0.0696, 1486 0.039989
      a=0.00625: n=156 0.1337, 308 0.0951, 420 0.0815, 490 0.0754
Bernoulli MDE: bisection on d for the smallest d with exact power >= 0.80 (p0=0.12, a=0.05)
break-even p0 = ask + round_half_even(0.0695*ask*(1-ask), 0.01) + 0.01
verdict date = first_day + ceil(n_req/(lambda*0.8)) - 1 + 8 days ; first_day = 2026-10-12
freeze expiry: latest first_day = 2027-01-17 - (ceil(n_req/(lambda_high*0.8)) - 1) days
    n=292 -> 93 days -> 2026-10-17 ; n=311 -> 99 days (> 98, never feasible)
    n=155 central (lambda 2.00) -> 97 days -> 2026-10-13 ; n=138 -> 87 days -> 2026-10-23
P(>=1 of 3 | 0.12) = binom.sf(0, 3, 0.12) = 1 - 0.88^3 = 0.318528
```
The calculation script was in the session scratchpad and is not persisted. Appendix C is sufficient to re-run every figure.

## Relevant files
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r2.md`
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/reviews/TE-3-r2-merge.md`
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/reviews/CORRECTION_2026-10-11_band_semantics.md`
- `/home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`
- `/home/jon/breezy/docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md`
- `/home/jon/breezy/docs/evidence/RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md`
- `/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/instrument_facts.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/decision.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/config.py`
- `/home/jon/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`
- `/home/jon/.local/share/breezy/catalog/quote_tape/decisions/`