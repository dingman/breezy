# S3 r3+r4-delta and window ruling r2: final round-2 verification (prediction-market-reviewer, 2026-10-13)

Inputs: ruling DRAFT r2, S3 r4 delta, S5 r4 delta, round-1 PMR file, FQ engine at HEAD (`fq_loss_floor_mc_engine.py` `_criticals`, `fq_loss_floor_mc_solve.py` `crossing_rate`).

## 1. Round-1 blocking items
| Item | Status | Resolving line |
|---|---|---|
| Unit error (ticking station-days vs 110 climate dates) | RESOLVED | Ruling :13-14, :22-25, O-1 :43-44, O-6 :86-90; S3 delta (b) :43-55; S5 delta (b) :21. 24+30+31+25 = 110 and ~64 from 2026-11-23 both check out. |
| Optional horizon cell = forking path | RESOLVED, with a code caveat (N-1) | Ruling O-2 :53-60; delta (c) :59-70 (mandatory, pinned, report-only, second extra horizon refused). |
| Which cell's c is frozen | PARTIAL | Rule is now pinned (ruling O-4 :69-72; delta (a) :25-30) and every cell is re-evaluated. Gap: re-evaluation omits the per-cell H0 crossing rate (N-2). |
| S5 :221 freezes the wrong pair | RESOLVED | Ruling O-3; S5 delta (a) :13-18 (`c_deff`, full float, test pinned to artifact key). |
| WP0 mutation evidence | RESOLVED | Delta (e) :88-91 (MUTATION_RED_EVIDENCE, hash stability); WP1 CHARACTERISATION class :93-95. I did not re-run WP0. |

## 2. New design choices
- Frozen-cell rule (b = median realised fill-bid; both k bracket if the ruling is absent; larger c wins): SOUND-WITH-CAVEATS.
  - The ruling justifies larger c as "conservative: fewer false stops". For a loss stop, larger c is LESS protective. The protection side is only held by G1/G3 re-evaluation, so the justification wording must change (N-3).
  - Larger c monotone in b is not guaranteed; "larger of the two bracketing cells" is a heuristic, acceptable only because everything is re-checked.
  - Unstated: b outside [0.70, 0.80] (refuse or UNREACHABLE?) and the "nearest" tie at a midpoint (treated as bracket: fine, say so).
- Verdict change (own sqrt_boundary solve AND pass at frozen c): SOUND-WITH-CAVEATS. Tri-state is well-defined. It couples the family verdict to cells at b values S2 did not realise (robustness, deliberately strict); disclose, since a larger frozen c can fail G1 on an unrealised cell and yield UNREACHABLE.
- horizon_sensitivity on the frozen cell via crossing_rate: SOUND IN INTENT, BROKEN AS WRITTEN (N-1).
- Early stop: SOUND-WITH-CAVEATS.
  - 30 cells = 5 f x 3 b x 2 k, six f=0.5 cells: arithmetic fine. Asymmetric confirm (all six must veto again at 10k) is the right direction. Reopen condition (S2 2x point > 0.50) is consistent.
  - Defect: the trigger counts `freeze_blocked` (S6 failed / refused template = build failure, not evidence) as a veto, so an infrastructure failure can terminally kill the family (N-4).
  - "f=0.5 above every fill rate in S5 section 8" and "beta=1, p2=0.5 most optimistic" were not verified by me (UNVERIFIED).
- S5 cap pin compared by length not date: SOUND. Slip shifts both dates 1:1. Remedy "pre-freeze S3 re-run" must be limited to a changed pin, never result-driven (N-5).
- a1_tail_false_stop and discounted day-60 power: SOUND. Discounting by the H0-row rate is conservative for power under a true edge but optimistic relative to the S4/S5-bind rows; label which row is used.
- Numbers re-checked: fee overstatement 0.0172/0.0154/0.0131; S4 exit floor 0.1 x 0.5 x (0.02+fee) ~ 0.0017/leg ~ 0.004 sigma/tick; ticks 110 x 0.69..3.64 = 76..400. All correct.

## 3. Issues (domain math / mechanics)
- N-1 [HIGH, must fix before WP3 code, not a plan rewrite] `_criticals(sim, n_days, t_min)` uses `cuts[min(n_days, len(cuts)) - 1]`. Calling it with n_days = L_cap > the simulated length silently clamps to the simulated length, so the "false-stop rate at the cap" would equal the 110-date rate and the disclosure would be understated (Failure: PREREG claims a mild tail rate; real run halts ~15-40% of null runs, per PMR iid check). Fix: horizon_sensitivity must RE-SIMULATE the frozen cell with horizon = freeze + L_cap - 1 (same seeds), and add test asserting len(cuts) >= L_cap and that the rate at L_cap >= rate at 110 on a seeded case. Delta (c) text "crossing_rate on criticals over n_days = L_cap" must say this.
- N-2 [MEDIUM] Re-evaluation at frozen c checks G1 and G3 only. A c solved on a fewer-tick cell has H0 crossing rate > alpha_star on a more-ticks cell (the original N1 mechanism), and G3 >= 2.5*alpha_star uses the frozen alpha, not the cell's actual H0 rate. Add per-cell `frozen_c_h0_rate` (and S4/S5-bind rates) with a pass test against alpha_floor + 3 SE, or record and disclose it.
- N-3 [MEDIUM] Reword O-4 rationale: larger c lowers false stops AND protection; protection is enforced by the re-evaluation.
- N-4 [MEDIUM] Early stop must require every f=0.5 confirm cell to be `unreachable_veto` (or at least one such with the rest freeze_blocked from a stated non-infrastructure cause); freeze_blocked from s6_failed/refused templates should route to a fix, not terminal UNREACHABLE. Same for STOP 3 mapping.
- N-5 [LOW] State that a pre-freeze horizon_sensitivity re-run is permitted only when the S5 cap pin changes, same seeds, still report-only.
- N-6 [LOW] Disclose that frozen c is solved at f_kill tick counts; actual ticks above the point estimate raise the false-stop rate in the same way the tail does.
- Known fact accepted: real FQ CLI g3_floor/M-yes and all-NO g1_unreachable are both consistent with section 3.1.

## 4. Scores for r3 + delta (1-10)
correctness 8 | architecture fit 8 | test coverage 8 | risk mitigation 8 | scope minimality 8 | feasibility 7
(N-1 pending; S2, S1 `listing_rate_4stn`, S5 cap pin not yet produced.)

## 5. Ruling verdict
SOUND-WITH-CAVEATS. Option A stands. Cleared for FINAL once N-3 wording is amended; N-1/N-2/N-4 are plan/code amendments to the S3 delta, not ruling changes.

Overall: HIGH for the plan once N-1 is written into delta (c) (one-sentence fix plus a test). Remaining blocking: N-1 only.
