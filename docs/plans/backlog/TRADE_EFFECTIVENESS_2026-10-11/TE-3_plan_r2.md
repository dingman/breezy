# TE-3 plan r2: NO-side cheap-entry hypothesis (revision of r1; 2026-10-11; read-only planning; suggested path `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r2.md`)

This plan read no M1-v3 report or outcome. It read `ask_threshold` (0.90, inclusive) from `docs/evidence/m1v3/PREREG.json`, as permitted. It computes no outcome statistic.

## 0. Verdict
- **Primary basis (R4, mechanical):** the ledger intake returns `UNDERPOWERED_NOT_REGISTERED` for this hypothesis, rationale "structurally infeasible on PM.us".
  - The pinned ledger path needs n_raw 1485.16, i.e. **1486** station-days for MDE ≤ 0.04.
  - PM.us has 5 stations, so the most any window can supply is 5 per day.
  - For the earliest plausible freeze (2026-10-12) the window is 98 days and the ceiling is **490**. A 2026-10-26 freeze gives 84 days and a ceiling of **420**.
  - The ledger MDE at 490 is **0.0696** and at 420 is **0.0752**. Both exceed the 0.04 bound.
  - The result holds at any rate, because the ceiling is physical (5 stations × days).
- **Corroboration only (Lane E, not structural):** a model-free forward test at α = 0.05 is infeasible at the central and low observed rates.
  - It is knife-edge in one corner: lowest break-even, high-end rate, normal approximation. That corner is not claimed infeasible (§5).
  - r1's "structural, independent of the rate" claim is **withdrawn**.
- **Deliverables:** one ruling (Appendix A), bookkeeping, and a dormant WP-4. There is **no new code** and no collector. WP-1 (the census tool) is dropped.

## 1. How TE-3 differs from M1-v3, NO-1 and H-NO-SIDE
| | M1-v3 (frozen, read-once ≥ 12-07) | TE-3 |
|---|---|---|
| Entry | NO ask ≥ 0.90 (NO favourite), first Depth10 row in [12:00,13:00) UTC | NO ask in [0.06, 0.12] (YES bid 0.88–0.94), interior rung, 12–16 LST |
| Fair-odds prior | favourable side (D_12Z cell −1.4¢; R11 expects NO-EDGE) | adverse side (M1 YES 0.0–0.1 cells are reliable losers, −1.7 to −2.3¢). Carried from r1 and not recomputed in r2 |

- The ask bands are disjoint, so a TE-3 entry can never be an M1-v3 take.
- **Never pool the two samples.** One station-day can hold an M1-v3 NO favourite on one rung and a TE-3 longshot on the current rung. The two outcomes are dependent.
- **NO-1 / PREREG v3a** already registers the NO leg: take NO iff `1 − P_HOLD_UPPER > NO ask + fee`, current rung only.
  - All 3 live NO fills came from that rule.
  - It is dead in practice for three reasons:
    1. `cont` and `v4` are halted, and `fq_v1` is the sending family.
    2. The frozen `P_HOLD_UPPER` table is unsafe on the NO side (memory `archive-table-train-serve-skew`).
    3. **AUD-01a:** `no_side_calibration_gate_cleared` is `False` by default (`config.py:247`). The gate at `decision.py:484-485` refuses every NO candidate as `no_side_calibration_unsafe`.
- **H-NO-SIDE-2026-09** is already `UNDERPOWERED_NOT_REGISTERED` (MDE 0.0890 at the stated n). Its record covers the `no_side_hunting` class. TE-3 cites it and registers nothing new.

## 2. Verified premises
- **Fills** (`~/.local/share/breezy/state/exec_polymarket_us.sqlite`; truth `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`):

| Fill | Instrument | Cost | CLI tmax | Result |
|---|---|---|---|---|
| CGW8DJ23PVB2 | MIA 09-15 `gte92lt93^no` | 0.09, fee 0 | 93 | NO wins, +0.91 |
| CNC3HJD66WP9 | MDW 09-22 `gte62lt63^no` | 0.12 + 0.01 | 64 | +0.87 |
| CMRS7Y99WWPE | MIA 09-21 `gte88lt89^no` | 0.12 + 0.01 | 88 | NO loses |

  - Net +1.65, matching the audit. The memory `hunt-window-opens-after-repricing` is wrong on the 09-15 rung: the CLI file says 93.
  - The three fills are SEARCH data, picked by outcome from 34. Exact P(≥ 2 of 3 | p = 0.12) = 0.039744. With the selection, that is not evidence.
- **Price semantics:** the `^no` price is `1 − best YES bid (size ≥ 1)` (`decision.py:455-496`; `market_calibration_scan.py:242`). An empty bid side returns None and is never synthesised.
- **Executable band:** `config.py:234-235` gives 0.05 < ask < 0.95 (strict). TE-3 fixes **[0.06, 0.12]** throughout.
- **Fee:** `decision.py:320-327`. Fee = `0.0695·a·(1−a)`, ROUND_HALF_EVEN to the cent. It is 0.00 at asks 0.06–0.07 and 0.01 at 0.08–0.12.
- **Break-even (net EV zero, slippage s = 0.01):** p0 = ask + fee + 0.01.

| Ask | 0.06 | 0.07 | 0.08 | 0.10 | 0.12 |
|---|---|---|---|---|---|
| p0 | 0.07 | 0.08 | 0.10 | 0.12 | 0.14 |

  - The band's p0 therefore runs **0.07 to 0.14**. r1's single 0.12 corresponds to an ask of 0.10 only.
- **Ledger constants** (`hypothesis_ledger.py`):

| Constant | Value | Line |
|---|---|---|
| `PROGRAMME_ALPHA` | 0.05 | 177 |
| `MAX_HYPOTHESES` | 4 | 181 |
| `POWER` | 0.80 | 192 |
| `VARIANCE_BOUND` | 0.25 | 196 |

  - Per-variant α = 0.05/4 = 0.0125, so z-sum = 3.083024.
  - `recompute_mde` (`:859-870`) is the only admitted derivation. An MDE above the plausibility bound yields `UNDERPOWERED_NOT_REGISTERED` (`:1125`).
  - The H-NO-SIDE ruling §3 sets the bound at 0.04.
- **Governance:**
  - Backstop 2027-01-25 (RA-13 §3). It is firm (B-5) and not extended by capture holes (L-38).
  - B-3: any count on tape after 2026-09-25 spends H-ARCHIVE-RECAL CONFIRM days.
  - B-2: no PM.us n, bound or α is reused for Kalshi.
  - Revival routes: R4, and FQ-v2 T1–T3 (R3V §3.2).
  - Prior art for the effect's sign: L-9 amendment (`LESSONS.md:492-505`), the cheap side is mostly a lottery already lost.
- **Census provenance (outcome-free; row counts only):**

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
| Refused `observation_ambiguous` | 6 of the other interior rungs and the open tail (7 of 9 distinct rungs overall). MIA 09-21 shows both the refusal and the take |

  - It reads no `replay_sufficiency` row and no truth, so it is B-3 clean. The MIA 09-15 fill has no tape file and is not in the count.
  - The exact command is in Appendix B. Recomputing the corrected figure from the same files agreed with codex F1 (8 interior + 1 open; 2 taken).

## 3. Arithmetic (every figure recomputed with `/home/jon/breezy/.venv/bin/python`; formulas in Appendix C)
**Rate.**
- λ̂ = 8 interior rungs / 4 full days = **2.00 per day**.
- Exact Poisson (Garwood) 95% interval for k = 8, T = 4: lower = χ²₀.₀₂₅(16)/2 / 4, upper = χ²₀.₉₇₅(18)/2 / 4, i.e. **[0.863, 3.941]**.
- Sensitivity: if all 7 file-days were exposure (the holes counted as zero days), λ̂ = 8/7 = 1.143 [0.493, 2.252]. The 4-day denominator is therefore the favourable one.
- The tape is the node's own, so the days are not a random sample.

**Available trials.** n_avail = λ·κ·T, with κ = 0.8 as an assumption (coverage haircut: Depth10 gaps, never-listed station-days).

| Case | λ | n_avail, T = 98 | n_avail, T = 84 |
|---|---|---|---|
| Low | 0.863 | 67 | 58 |
| Central | 2.00 | 156 | 134 |
| High | 3.941 | 308 | 264 |
| Ceiling (5/day, κ = 1) | – | **490** | **420** |

- T = 98 means first_forward_day 2026-10-12 and last_forward_day 2027-01-17 (backstop minus an 8-day truth lag, the M1-v3 R7 precedent). T = 84 means a first day of 2026-10-26.
- Neither is a scheduled freeze. They are the earliest plausible and the r1 case.
- Same-day correlation across the 5 stations (a shared weather regime) shrinks the effective n under a calendar-day cluster bootstrap. This strengthens the verdict. It is not modelled.

**MDE, two non-comparable families (p0 = 0.12, α = 0.05, power 0.80).**
- (a) Bernoulli MDE: the smallest δ with exact-binomial power ≥ 0.80.

| n | Normal approx | Exact |
|---|---|---|
| 156 (central) | 0.069 | 0.077 |
| 308 (high) | 0.048 | 0.052 |

  - At the ceiling, n = 490 gives 0.038 (normal) and 0.040 (exact). For n = 420 the figures are 0.041 and 0.044.
- (b) Ledger MDE, pinned variance 0.25 (sd 0.5), α = 0.0125: 0.123 at n = 156, 0.088 at n = 308, **0.0696 at 490**, **0.0752 at 420**.
- (b) is about 2.4 times the Bernoulli sd at p = 0.12. Do not compare the two.

**Required n, exact one-sided binomial** (smallest n with power ≥ 0.80, p1 = p0 + δ, α = 0.05). The normal approximation is the lower figure, shown as normal/exact.

| p0 | δ = 0.04 | δ = 0.05 | δ = 0.06 | δ = 0.08 |
|---|---|---|---|---|
| 0.07 | 292/311 | 193/204 | 138/155 | 82/90 |
| 0.10 | 386/403 | 253/270 | 179/193 | 105/117 |
| 0.12 | 445/464 | 290/307 | 205/219 | 119/127 |
| 0.14 | 500/516 | 325/341 | 229/239 | 133/145 |

- At α = 0.0125, δ = 0.04: 436/476, 582/613, 672/705, 758/787 for p0 = 0.07, 0.10, 0.12, 0.14.
- The normal-approximation cells match r1 (445, 290, 205, 119, and so on) and domain's recompute. The exact figures are larger.

**Verdict dates.** The date is the last forward day needed, plus 8 days. The window is first_forward_day 2026-10-12. The backstop is 2027-01-25.

| Required n | Low | Central | High |
|---|---|---|---|
| 311 (p0 0.07, δ 0.04, exact) | 2028-01-13 | 2027-05-02 | 2027-01-26 (1 day late) |
| 292 (same cell, normal) | 2027-12-16 | 2027-04-20 | **2027-01-20 (inside)** |
| 403 (p0 0.10, exact) | 2028-05-25 | 2027-06-28 | 2027-02-24 |
| 464 (p0 0.12, exact) | 2028-08-21 | 2027-08-05 | 2027-03-16 |
| 1486 (ledger) | not reachable (over 5 years) | 2029-05-05 | 2028-02-03 |

- The ledger n at the 5/day physical maximum needs 298 days, against the 98-day window.

**Corroboration, stated honestly.**
- The Lane-E test is **infeasible** at the central and low rates for every p0 and every δ ≤ 0.06.
- At the high rate it is infeasible except in one corner (p0 = 0.07, δ = 0.04, normal approximation).
- The Lane-E test at δ = 0.08 is **not rejected by the 0.04 ledger bound**, which is a ledger rule and does not apply to Lane E. It is rejected on prior grounds only (§4).
  - Its n_min is 82–145, against central n_avail of 156 at T = 98.
  - Even if it were run, a WINNER there nominates an admissibility filter, not a family.

## 4. Prior grounds for treating δ ≥ 0.08 as implausible (no ledger bound invoked)
- The fair-odds prior is adverse (§1) and the market already prices this region as a lottery already lost (L-9 amendment).
- The band was chosen after seeing 3 outcome-selected fills and 9 tape rungs, which is SEARCH. P(WINNER) is therefore close to α.
- Venue refusals: observation ambiguity refused 7 of 9 candidates, so the bot's own rule would rarely have fired. Real-money fillability is unmeasured.

## 5. Stage 0 STOP conditions (apply to the ruling work and to any dormant WP-4 build)
1. **STOP if** the M1-v3 PREREG blob differs from `adb1cd8b`/`6fbc4f6b` (`git log -- docs/evidence/m1v3/PREREG.json`, `check_frozen_blob`).
2. **STOP if** any artefact opens a path under `docs/evidence/m1v3/` other than PREREG.json for the band constant, or imports `no_longshot_pooled_test`.
3. **STOP if** any count touches a climate day after 2026-09-25 (RA-13 B-3). This applies to tape, `replay_sufficiency` and offer-tape inputs alike.
4. **STOP if** any statistic uses the 3 NO fills. They are premises only.
5. **STOP if** a number in the ruling cannot be reproduced from Appendix C or B.

## 6. Work packages
Build route is unchanged: Grok → Codex → Claude tdd-guide; the coordinator runs `scripts/ci/run_tests_no_egress.sh`. No code is written for WP-2/WP-3.

**WP-1: DROPPED (YAGNI).** A fresh census cannot change a ledger verdict or the corroboration. Only the preliminary census (§2) is quoted, with its provenance.

**WP-2: the ruling (docs only).**
- File: `docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_<date>.md`, drafted in Appendix A.
- Verdict token: `UNDERPOWERED_NOT_REGISTERED`, with "structurally infeasible on PM.us" as the rationale. It cites the H-NO-SIDE-2026-09 record.
- No `_UNDERPOWERED_REGISTRATIONS` entry is added.
- It goes through a prediction-market-reviewer pass before the coordinator saves it.

**WP-3: bookkeeping.**
- Update the TE-3 row in `docs/core/PROGRESS.md` to the ruling file, with the §3 numbers.
- Write `reviews/TE-3-final.md` (the convergence record).
- Record a lesson via the lessons skill, after deduping against the "implausible result" entries: **a hypothesis chosen from outcome-selected fills cannot be powered by them, and a "structural" claim must survive its own sensitivity table**.

**WP-4 (CONTINGENT, DORMANT).** It builds only if a re-open trigger fires and a new ruling says so.
- Shape: an offline Lane-E tool in the `no_longshot_pooled_test.py` pattern. It uses `check_frozen_blob` and a freeze-introduction check. It does not touch the CRH strategy shadow path.
- **Binding requirements it inherits** (recorded here so the design is not lost):
  1. **Every input refuses climate days after 2026-09-25** (arch G1, python F3). That covers tape, `replay_sufficiency` rows and offer tape. The refusal sits at the function level, not only the CLI, and clamps the UTC `hi_ns` too (the PT tail of climate day 09-25 reads UTC 09-26).
  2. **LST → UTC conversion** with `std_utc_offset_hours` (`sites.py:401`), and one tape per UTC day the 12–16 LST window touches. A PT station's window runs 20Z to 01Z next day (python F1).
  3. **A standalone no-lookahead check on the LST climate-day end.** `assert_no_lookahead` and `Observation` cannot be used, because they need truth and a UTC day end (python F2).
  4. `_observe_row` and `_scan_day` are off limits (they take a `TruthRow`). `classify_directory`, `_index_directories`, `no_ask`, `_levels` and `_first_row` are reusable.
- Tests would mirror M1-v3: forward-day filter from git, no verdict before the read date, read-once, lookahead gives INVALID, decision ts < outcome ts.
- Sanity guard: "ask ≤ 0.12 with hit rate > 0.35 is a bug signature" (memory `implausible-result-is-a-leak`).

## 7. Dormant PREREG skeleton (never frozen on PM.us)
- **Id / lane:** `H-NO-CHEAP-CURRENT-RUNG` / Lane E, outside the AUT-S K ledger, as M1-v3 is.
- **H1:** buying NO at the Depth10 ask on an interior rung, with NO ask in [0.06, 0.12] and YES bid ≥ 0.88, at the first qualifying row in 12–16 LST, has positive mean net EV per take.
  - The rule is named "interior rung, YES bid ≥ 0.88". It does not claim "current rung", since there is no running-max input.
- **Net EV:** `hit − (ask + fee + 0.01)`, with fee per §2.
- **Unit:** one trial per station-day; calendar-day cluster bootstrap with zero-take days kept.
- **Statistic:** K = 1, one-sided, α = 0.05. A ledger-registered variant would use α′ = 0.0125.
- **Looks:** a single look, counts-only before the read date.
- **Floors:** n ≥ the §3 exact n for the realised p0, at least 40 days, at least 5 loss days.
- **KILL:** verdict date after 2027-01-25, or any floor unmet at the read date.
- **Pins:** SEARCH/CONFIRM split at the freeze commit. The three fills and all pre-09-26 tape are SEARCH.

## 8. Re-open triggers, each with its next action
| # | Trigger | Next action |
|---|---|---|
| 1 | PM.us lists enough daily-high stations that λ·κ·T ≥ 1486 inside a window ending before the backstop | Planner re-runs Appendix C with the new station count. Note 16 stations × 98 days = 1568 only with κ = 1 and every station-day qualifying, so this is nominal, not a plan |
| 2 | A K-2b Kalshi ledger exists | List TE-3 as a **desk-only candidate** in the K-2a plan hypothesis list (R3V:55-61). Size it with Kalshi's own station count and TWC settlement. Reuse no PM.us n, bound or α (B-2) |
| 3 | A ruling raises the plausibility bound, using outcome-free evidence | Re-run `recompute_mde`. The bound must reach at least **0.0696** at the 490 ceiling, and about 0.123 at the central n_avail of 156 |
| 4 | FQ-v2 T1–T3 fire and request it | Planner re-plans WP-4 under the T-trigger ruling with the §6 inherited requirements |

## 9. Dependencies and risks
- The ruling needs only the files in §2. The M1-v3 read (≥ 12-07, read-once) is untouched and never awaited.
- **Risk: the census is 4 days.** The ledger verdict does not depend on it. The corroboration dates do, and the ruling quotes the full interval and the 8/7 sensitivity.
- **Risk: sides confused.** TE-3 is the NO longshot. The §1 table and the never-pool rule cover it.
- **Risk: anecdote pressure.** The ruling quotes P = 0.039744 and the selection from 34 fills.
- **Risk: firewall.** Declaring this infeasible touches no post-09-25 tape. A collector would spend CONFIRM days.

## 10. Non-goals
No live order, arming, halt, permit or operator cap. No M1-v3 file or PREREG change. No new family or `ContinuousRungHoldStrategy` shadow. No resting-bid design. No post-09-25 count. No Kalshi build. No outcome statistic on the SEARCH corpus. No new code.

## 11. Goal-state map
| Goal item | Where met |
|---|---|
| Documented ruling (covered or infeasible) | WP-2 and Appendix A; the part covered by NO-1 / v3a is in §1 |
| Feasibility number | §3: 2.00 per day [0.863, 3.941], preliminary; the ledger ceiling 490 (or 420) against 1486 |
| Verdict date at the rate | §3 table: central 2027-08-05 (p0 = 0.12) or 2029-05-05 (ledger); every central case is past the backstop |
| INFEASIBLE with the number | R4: n 1486 against ceiling 490; MDE 0.0696 against bound 0.04 |
| Shadow measurement path | Not built, by the infeasibility rule. WP-4 and §7 hold the dormant design |
| Revival path with named actions | §8 |
| Arming and live sending | Out of scope |

## 12. Changes from r1
| ID | Finding | Disposition |
|---|---|---|
| Merge 1 | Primary basis is R4 ledger intake | Done. §0, Appendix A. Token `UNDERPOWERED_NOT_REGISTERED`; no `INFEASIBLE_NOT_REGISTERED`; n_raw 1485.16 → 1486 |
| Merge 2 | Lane E is corroboration only | Done. §0, §3 corroboration, §4. "Structural, independent of rate" withdrawn. n_min over p0 0.07–0.14, exact with the normal approximation as the lower figure. Ceilings 490/420. Two MDE families separated. δ = 0.08 rejected on prior grounds |
| Merge 3 | Census correction | Done. 8 interior over 4 days, λ̂ = 2.00 [0.863, 3.941]; open `lt65` excluded; band [0.06, 0.12] everywhere; dates fixed |
| Merge 4 | WP-1 dropped | Done. §6. Python F1–F10 lapse; F1/F2/F3 and arch G1 are inherited by WP-4 as binding requirements |
| Merge 5 | Re-open triggers name an action | Done. §8 |
| Merge 6 | Added premises | Done. AUD-01a (§1), same-day correlation (§3), never-pool note (§1) |
| Merge 7 | Deliverables | Done. §6; ruling text in Appendix A |
| Domain S1 | "Structural" claim false | Fixed. Withdrawn; replaced by the ledger path and the §3 sensitivity |
| Domain S2 | Ledger bound applied to Lane E | Fixed. δ = 0.08 rejected on prior grounds (§4) |
| Domain S3 | MDE families mixed | Fixed. §3 separates them |
| Domain S4 | Single p0 | Fixed. p0 range 0.07–0.14 (§2, §3) |
| Domain S5 | Band inconsistent | Fixed. [0.06, 0.12] throughout |
| Domain S6 | Dates off | Fixed. Recomputed on the new convention (§3) |
| Domain S7 | Same-day correlation | Added (§3) |
| Domain (disjointness) | Station-day can hold both samples | Added (§1) |
| Python F1 | LST → UTC, multi-day tape | Inherited by WP-4 (§6 req. 2) |
| Python F2 | `assert_no_lookahead` unusable | Inherited by WP-4 (§6 req. 3) |
| Python F3 | `--until` unenforceable | Folded into the arch G1 refusal inherited by WP-4 (§6 req. 1) |
| Python F4–F10 | RED tests, AST pin, imports, loader, window_complete, runtime, focused gate | Lapse with WP-1; no tool is built |
| Arch G1 | Post-09-25 inputs | Inherited by WP-4 (§6 req. 1); STOP 3 (§5) covers all inputs. The preliminary census reads none |
| Arch G2 | Primary basis is ledger intake | Done (§0) |
| Arch G3 | WP-1 is YAGNI | Done (WP-1 dropped) |
| Arch G4 | Reuse `decision_window_ns`; `ladder_ev` census | Moot with WP-1 dropped. Not recorded for WP-4, which is dormant |
| Arch G5 | Triggers need actions | Done (§8) |
| Arch G6 | AUD-01a gate | Added (§1) |
| Arch G7 | Private helpers pin test | Lapses with WP-1 |
| Arch G8 | Focused gate | Lapses with WP-1 (no code) |
| Arch G9 | Optional registration redundant | Dropped (WP-2) |
| Codex F1 | Census mislabelled | Fixed. 8 interior + 1 open (§2, §3) |
| Codex F2 | n off by one | Fixed. 1485.16 → 1486 |
| Codex "strongest argument" | The 420 ceiling depends on a 10-26 freeze | Handled. Ceiling 490 at 10-12 and 420 as a second case; Lane E is demoted to corroboration |

## Appendix A. Draft ruling text (`docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_<date>.md`)
```
# RULING TE-3: NO-side cheap-entry longshot (NO ask 0.06-0.12)
Verdict: UNDERPOWERED_NOT_REGISTERED (structurally infeasible on PM.us). No PREREG is frozen.
No outcome statistic was computed. No tape after 2026-09-25 was read (RA-13 B-3). No M1-v3
outcome data was read.

1. Hypothesis. Buying NO at the Depth10 ask on an interior rung with NO ask in [0.06, 0.12] has
   positive net EV. It came from 2 wins in 3 live NO fills (+1.65 net). The 3 fills were
   picked by outcome from 34; P(>=2 of 3 | p=0.12) = 0.039744. They are SEARCH data.
2. Delta. Disjoint from M1-v3 (NO ask >= 0.90). Samples are never pooled. The bot's NO rule
   (PREREG v3a, NO-1) is dead: cont/v4 halted, P_HOLD_UPPER unsafe on the NO side, AUD-01a
   no_side_calibration_gate_cleared=False. H-NO-SIDE-2026-09 already holds the
   no_side_hunting class as UNDERPOWERED_NOT_REGISTERED; this ruling cites that record and
   registers nothing new.
3. Basis (R4, mechanical). Ledger intake: alpha 0.05/4 = 0.0125, z-sum 3.083024, variance 0.25.
   For MDE <= 0.04 n_raw = 1485.16, so n = 1486 station-days. PM.us has 5 stations: a 98-day
   window (2026-10-12..2027-01-17, backstop 2027-01-25 less an 8-day truth lag) yields at most
   490, or 420 for a 2026-10-26 freeze. Ledger MDE at 490 = 0.0696; at 420 = 0.0752. Both exceed
   0.04. The result holds at any rate.
4. Corroboration (Lane E, alpha 0.05, power 0.80). Preliminary census: 8 interior rungs over 4
   full tape days, lambda = 2.00/day, exact Poisson 95% [0.863, 3.941]; 9th rung is an open-tail
   and excluded; 2 of the 8 reached take; 7 of 9 distinct rungs were refused observation_ambiguous.
   n_avail (kappa 0.8, T 98) = 67 / 156 / 308 (low/central/high). Required exact-binomial n
   (delta 0.04) is 311 to 516 over p0 0.07-0.14. The test is infeasible at the central and low
   rates; at the high rate it is infeasible except at p0 = 0.07 under the normal approximation
   (verdict 2027-01-20 versus a 2027-01-25 backstop). This is corroboration, not a structural
   claim. delta >= 0.08 is rejected on prior grounds (adverse fair-odds prior; SEARCH-picked band).
5. Caveats. Four days; coverage holes at 09-17, 09-19, 09-23 and none after 09-23; sensitivity 8/7 =
   1.14/day. Same-day cross-station correlation shrinks effective n further.
6. Re-open triggers and next actions: (1) PM.us station count lifts lambda*kappa*T to >= 1486
   before the backstop: re-run Appendix C; (2) K-2b Kalshi ledger: list as desk-only candidate
   in K-2a (R3V:55-61), no PM.us n/bound/alpha reused (B-2); (3) bound raised by an outcome-free
   ruling: re-run recompute_mde, needs >= 0.0696; (4) FQ-v2 T1-T3: re-plan under that ruling.
7. Dormant WP-4 requirements: inputs refuse climate days after 2026-09-25; LST->UTC multi-day
   tape; standalone no-lookahead check on the LST day end.
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
- Output on 2026-10-11: `9 {('interior', False): 6, ('open', False): 1, ('interior', True): 2} [('2026-09-16', 3), ('2026-09-20', 1), ('2026-09-21', 2), ('2026-09-22', 2)]`.
- File sha256 prefixes (first 16 hex): 16: `405fc4fbda1acb7f`, 17: `8fd14aa8c0be976c`, 19: `0ec7467d5ebb08ba`, 20: `21122f7c18963442`, 21: `f179550af6eee93d`, 22: `a6e1d7b752f7f961`, 23: `ea2870e9d8dd1d33`.

## Appendix C. Formulas (all run with `/home/jon/breezy/.venv/bin/python`, scipy 1.18.1)
```
Poisson(k,T): lo = chi2.ppf(0.025, 2k)/2/T ; hi = chi2.ppf(0.975, 2k+2)/2/T       # k=8,T=4
n_avail = lambda * 0.8 * T ; ceiling = 5 * T                                       # T=98 or 84
exact n_min(p0,d,a): smallest n with binom.sf(c-1, n, p0+d) >= 0.80,
    c = smallest integer with binom.sf(c-1, n, p0) <= a                           # a=0.05, 0.0125
normal n_min = ceil(((z(1-a)*sqrt(p0 q0) + z(0.80)*sqrt(p1 q1))/d)^2)
ledger: zsum = z(1-0.0125)+z(0.80) = 3.083024 ; n_raw = (zsum*0.5/0.04)^2 = 1485.162 ;
    MDE(n) = zsum*0.5/sqrt(n)    # n=420 -> 0.07522, n=490 -> 0.06964, n=1486 -> 0.039989
Bernoulli MDE: bisection on d for the smallest d with exact power >= 0.80 (p0=0.12, a=0.05)
break-even p0 = ask + round_half_even(0.0695*ask*(1-ask), 0.01) + 0.01
verdict date = first_day + ceil(n_req/(lambda*0.8)) - 1 + 8 days ; first_day = 2026-10-12
P(>=2 of 3 | 0.12) = binom.sf(1, 3, 0.12) = 0.039744
```
The calculation script was in the session scratchpad and is not persisted. Appendix C is sufficient to re-run every figure.

## Relevant files
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r1.md`
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/reviews/TE-3-r1-merge.md`
- `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`
- `/home/jon/breezy/docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md`
- `/home/jon/breezy/docs/evidence/RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md`
- `/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/decision.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/config.py`
- `/home/jon/.local/share/breezy/catalog/quote_tape/decisions/`