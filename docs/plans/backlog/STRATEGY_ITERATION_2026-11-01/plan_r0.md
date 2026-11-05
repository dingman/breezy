# STRATEGY-ITERATION: adjust, re-backtest, stop on a pre-registered winner or a KILL (plan r0, 2026-11-01)

Status: r0 DRAFT for blind peer review (architect + prediction-market-reviewer). Planner text landed verbatim by the coordinator (planner has no Write tool); unverified citations listed in §9. HEAD 9f9c861b. Operator pause (PROGRESS 11-01 19:55Z): nothing in Step B is built until the operator directs.
Binding: Nautilus immutable; `allow_short=False`; caps are operator-only and never set here; the existing harness only (10-21 ruling: one flag on an existing script is the precedent); never weaken a safety, settlement, contract, NO-SEND or leakage test; thresholds never move after data is read (PROGRESS backlog rule, L-34); evidence is machine-written (L-75).

## 1. Objective, stated correctly
- "Winning effectiveness over 70%" cannot be the criterion. Buying at ask `a` breaks even at a win rate of `a + fee(a) + margin`. A 70% win rate at a = 0.80 loses money, and a 40% win rate at a = 0.30 makes money.
- **Criterion (per cell = source Ã horizon Ã side Ã ask band):** the one-sided Wilson lower bound on the realised win rate, at Î± = 0.05/K, must exceed `a_hi + fee(a_hi) + m`.
  - `a_hi` is the upper edge of the band. The executable ask is the lowest Depth10 level with size â¥ 1 (L-35).
  - `fee = round_half_even(0.0695Â·aÂ·(1âa), 0.01)`, the taker Î¸ (`EVIDENCED_FEE_THETA`).
  - `m` is a slippage/model margin, frozen at registration, with a floor of 0.02.
  - The secondary statistic is the mean excess `hit â (ask + fee)` per take, with a day-block bootstrap LB > m. Both must PASS.
- **Literal 70% floor (operator option):** additionally require LB â¥ 0.70. This floor only binds when break-even is below 0.70, i.e. a_hi â¤ ~0.63â0.65 depending on m. Above that, the cost criterion already demands more than 70%. If the operator wants the floor, the bands at or below 0.63 must clear 0.70 rather than break-even. That lowers power in exactly the bands M1 found to be reliable losers (cheap YES).

## 2. Data roles: the iteration loop, split by role
| Role | Forecast side (archive vs outcome) | Strategy side (forecast vs executable ask) |
|---|---|---|
| TRAIN/EXPLORE | climate days < 07-01 (CLI truth 2021â, IEM MOS/NBP, LAMP backfill). Fit, calibrate, search sources, horizons and blends, and rerun freely. | Tape days [10-02, T_freeze), about 30 days so far. Search side Ã band Ã margin Ã calibration map freely. |
| VALIDATE | Day-block CV inside < 07-01: `nbp_skill_study --stage validate`, `multisource_blend_skill` folds | Not separable. 30 days cannot be split again without losing all power. The SPA/RC p over the whole cumulative explore family (Â§3) stands in. |
| SEALED (ONE look) | [07-01, 10-02), opened once via `open_holdout` (HoldoutSingleLookError on a second open; only a co-signed C-1 deviation reopens it) | **None exists retrospectively.** Tape [08-30, 10-02) is inside the holdout and was touched by WP-7b, AUD-02, M1 and P2. Under cl.3 it is descriptive only and never used for selection or confirmation. |
| CONFIRM | the one holdout look above | [T_freeze, T_freeze + D_c): unseen forward tape, after the PREREG sha is committed (cl.2) |
| FORWARD live-small | â | after CONFIRM PASS plus operator enablement |
- **Correction to the brief:** cl.1 grants ONE confirmatory use of the holdout in total, not one per candidate. All registered candidates are scored in that single opening, with Bonferroni over R.
- **Asymmetry:** the forecast side has about 5.5 years Ã 5 stations (about 10k station-days). The strategy side has about 30 usable tape days Ã 5 stations, plus about 33 descriptive-only days.
  - A forecast PASS says nothing about the ask. P2 measured D_res(NBP â ask) = â0.023, so the ask already carries about 4.8Ã the resolution.
  - Only CONFIRM on forward tape can nominate a strategy (FQ-R14, the M1 docstring).
- **Leak rule:** any explore cell with mean excess > +15Â¢ or a win rate more than 20 pts above its ask is audited before it is logged as a candidate. The audit checks `available_at_ns` against the gate instant, the truth publication time and the window scoping ("an implausible result is a leak", the +0.55/take precedent).

## 3. Multiple-comparison accounting and stopping rule
- Every run gets a run id in `docs/evidence/STRATEGY_ITERATION/variant_ledger.jsonl`, written by the script wrapper and never by hand.
  - Fields: run id, git sha, flags, input sha256, K cells tested, best-cell stats, SPA p.
  - **K_cum** is the sum of K over all runs, including discarded ones.
- Explore gate (a candidate may be registered when):
  - the cumulative-family SPA p â¤ 0.10, from the scan's own reality-check/SPA over a joint day resample across all cells ever tested; and
  - the cell's Bonferroni-at-K_cum Wilson LB clears the Â§1 bar on explore days; and
  - the cell passes the leak audit.
- Registered candidates are capped at R â¤ 3. CONFIRM tests each at Î± = 0.05/R, one-sided.
- **Budget (KILL on exhaustion, never "keep tuning"):**
  - N = 240 cells: 5 sources Ã 3 horizons Ã 2 sides Ã 4 bands = 120, run twice (margin or calibration-map variant).
  - D = 28 calendar days of explore work from the Step B merge.
  - If either budget is exhausted with no registrable cell, the programme is KILLED. A KILL is recorded in `docs/evidence/`. Reopening needs new data (more station-days or a new venue), never a new grid on the same days.
- Each CONFIRM block gets one look (L-34). A FAIL removes that candidate permanently, and its cells stay counted in K_cum.

## 4. Order of work and harness route (bot and harness compute everything; nothing is hand-computed)
**A. Score sources against outcome (archive) and against the ask.**
- Commands:
  - `nbp_skill_study.py --stage validate --run-gates --comparator-models --out <scratch>`
  - `multisource_blend_features_build.py --prereg F13_prereg_blend_v1.json --nbp-root --us-source-root --mos-root --truth --start 2021-01-01 --end 2026-06-30 --out-features --out-lag-features --report-json`
  - `multisource_blend_skill.py --prereg --features --lag-features --out-dir`
  - `p2_nbp_ask_murphy.py` (NBP vs ask only; it has `--smoke` and no other flags, so it is a re-read of P2, not a new look)
- Output: `docs/evidence/STRATEGY_ITERATION/A_source_scores.md`, giving REL/RES/Brier per source Ã horizon with fold CIs.
- Time: 2â3 days, one heavy job at a time under systemd-run with MemoryMax=4G.
- KILL: no source beats NBP's validate resolution by a CI-separated margin AND NBP itself is the P2 FAIL â no forecast input can beat the ask. Stop before B.

**B. ONE flag: `market_calibration_scan.py --forecast-p PATH`** (parquet keyed station, climate_day, rung, window â p_yes, plus source and horizon tags).
- With the flag set:
  - cells become window Ã side Ã forecast-edge bin (p_side â ask in {<0, 0â5, 5â10, 10â20, >20}Â¢) Ã ask band;
  - station-days absent from the file leave both the horizon numerator and the denominator;
  - every other definition is byte-unchanged.
- Without the flag, output stays byte-identical to `m1/market_calibration_scan_v2.json`.
- This is the single sanctioned harness change. A second flag (e.g. a date slice) or any new evaluator is a **BLOCKER** that needs an operator exception (Card D precedent).
- Build: tdd-guide, RED first, then python-reviewer and prediction-market-reviewer, then the full no-egress gate, then read EXIT before push.
- Time: 3â5 days. KILL: none; a FAIL at review is an amendment.
- Open: whether the Step A scripts emit per-rung p files is UNVERIFIED. If they don't, producing them is evaluator logic, i.e. BLOCKER-H.

**C. Explore on [10-02, T_freeze).**
- Run B once per source Ã horizon p file and log each run in the ledger (Â§3).
- Output: `docs/evidence/STRATEGY_ITERATION/C_explore_<run>.{json,md}`, written by the writer.
- Time: â¤ D = 28 days. KILL: per Â§3.

**D. Register, then make one look.**
- Freeze `PREREG_strategy_<id>.md` with:
  - cell definition, m, Î±/R, D_c, n_min, the PASS/KILL table, and the sha of every input;
  - `prereg_precommit_check.py` clean;
  - commit and push before T_freeze.
- Size D_c from the cell's explore SE:
  - D_c â 26 Ã (19.8/Î)Â² Ã (z_{Î±/R} + 0.84)Â² / 4.03Â² days;
  - for Î = 10Â¢ at R â¤ 3, that is â 75â95 days.
- If the candidate uses a refitted forecast model, its forecast-side confirmation is the single holdout opening. Check the `open_holdout` marker first. If n_min (592 for the G2.2 route) is above the holdout's â 465 station-days, the forecast leg is INFEASIBLE, and that is recorded rather than worked around.
- Run B, with the frozen p file, on [T_freeze, T_freeze + D_c).
- Output: `D_confirm_<id>.md`.
- KILL: LB â¤ bar, or fewer than the frozen n fills by the end of D_c (STOP-underpowered, not PASS).

**E. Forward live-small, qty 1.**
- Needs operator enablement; caps unchanged.
- Uses the sequential design of the PREREG v2 ruling: LD-OBF on Wilson, Î± = 0.025, a look every 10 fills.
- An opportunity monitor is pre-registered beside it (L-64).
- **HARM stop:** at any look, the upper bound of the win rate falls below break-even, or the 2nd loss happens before n = 10 â disarm.
- A NO side is executed only through the merged S5 path (SELL/BUY_SHORT); `allow_short` is never changed.

## 5. What "adjusting the strategy" may and may not vary
- **May:** source (NBP, LAMP, PFM, MOS, blends), horizon/window, side, ask band, margin m, calibration map (fit < 07-01 only).
- **May not:**
  - the truth (NWS CLI finals);
  - the fee Î¸, or its rounding;
  - the holdout dates (cl.1, cl.4 is an ARCH change);
  - the executable-ask definition;
  - any PASS/KILL threshold, D_c or n after freeze;
  - the leakage guards (`_assert_no_holdout_rows`, `FIRST_FORWARD_DAY`): widen, never relax (L-12);
  - the caps and `allow_short`.

## 6. Expected outcome, time to decision, operator decisions
- Prior chance that a cell reaches CONFIRM PASS: NBP-based â 1â5%; unscored sources (LAMP/PFM/blends) â 3â12%.
- The record behind this prior:
  - M1 null (SPA p 0.416, MDE 19.8Â¢);
  - P2 FAIL;
  - taker falsified live (34 fills / 4 wins);
  - maker LB 0.839 below break-even;
  - Card A KILL, Card E KILL.
- Time to decision:
  - Explore decision about 4 weeks after B merges.
  - CONFIRM decision â 2â3 months of forward tape for a rough read, and 75â95 days to confirm a 10Â¢ edge, i.e. about mid-Feb to early Mar 2027.
- Even a PASS at qty 1 is worth â $0 to tens of $/month on PM.us (AUDIT 10-22).
- Operator decides:
  - (1) size q for P5;
  - (2) whether to capture Kalshi in parallel: 24 cities vs 5, which multiplies station-days and divides D_c roughly by the station ratio, but needs its own capture build and tmax truth per station;
  - (3) whether the literal 70% floor applies;
  - (4) authorization to build Step B under the 11-01 pause.

## 7. Risks
- 30 explore days are underpowered, so the likely outcome is a budget-exhaustion KILL. That is the honest result, not a defect.
- The NO ask in the scan is `1 â YES bid`, which P2 did not use, and it is unverified under SELL/BUY_SHORT. NO cells are therefore screening-only until a NO-instrument book is captured.
- Fixed UTC windows are not local-time equivalent (M1 caveat). A new window is a new scan and counts in K_cum.

## 8. Peer review
Peer review is required before anything is built: **architect** (data-role split, the single-look correction, the one-flag scope, BLOCKER boundaries) and **prediction-market-reviewer** (criterion, Wilson/fee arithmetic, SPA accounting, D_c sizing, HARM stop).

## 9. Cited but not verified by the author
- The priors (1–5% NBP, 3–12% unscored sources) are the reviewers' judgement from the 11-01 session, not a document.
- `open_holdout` is at `nbp_calibration.py:351-394`; whether the single-look marker file already exists was not checked.
- LAMP/PFM history before 07-01, and whether `multisource_blend_skill.py` writes per-rung p files (Step B depends on both) — UNVERIFIED.
- n_min 592 vs ≈ 465 holdout station-days is from the 09-30 ruling memory, not re-measured.
- The D_c formula is the planner's derivation from M1's MDE 19.8¢ over 26 days; the prediction-market-reviewer must check it.
