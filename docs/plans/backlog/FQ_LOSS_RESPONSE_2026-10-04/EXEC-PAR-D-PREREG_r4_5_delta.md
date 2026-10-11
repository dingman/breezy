# D-PREREG r4.5 delta: BG-10 viability ruling (ICC)

- **Base:** r4 + r4.1–r4.4.
- **Inputs:**
  - BG-10 results on branch bg10 @ c9128746;
  - two independent reviews, a market/stats review and an architecture review, each run blind.
- **Status:** these rulings are binding and fold into the frozen text (§13). They are subject to the mandatory freeze-time three-lens review.

## Disclosure (must also appear in the freeze commit message)

1. **Coordinator deviation.** The coordinator's BG-10 brief allowed an ICC fallback of 0.1 "when data was thin". That deviates from G6 (ICC = max(0.1, pre-window ANOVA estimate)), and it was introduced after the spec converged. The deviation was caught at review and is recorded here as an error.
2. **Rulings were made after seeing the results.** O2 and O3 below were adopted after both the G6 verdict and the 0.1 verdict were visible. They are justified because the data cannot settle the question, as the interval below shows. They are not independent of the result, and this record does not claim otherwise.

## O1. Recorded pre-activation verdict: NOT VIABLE under G6

| Quantity | Value |
|---|---|
| V1 level | 0.424 (≥ 0.33: **pass**) |
| Pre-window ANOVA ICC | 0.4147, from n_amb = 7 over 12 days; day-bootstrap 5–95%: 0.065–0.77 |
| ICC used (G6) | **0.4147** |
| V3 at the 90% bound | fails, so the switch to the 95% bound is triggered |
| V3 at the 95% bound, ICC 0.4147 | **41% (> 20%: FAIL)** |
| Verdict | **NOT VIABLE under G6.** Re-evaluable only through the O2 live gate. |

- **The ICC 0.1 run** (V3 at 95% = 16.1%; V2 = 95.9% overall with no-halt, 99.6% bound-only) is a **labelled sensitivity run only**. It is not a result and never satisfies V1–V3.
- **No reruns.** BG-10 is not rerun with other seeds, resamples or estimators to move these numbers.

## O2. Viability moves to a promotion-time gate

This replaces the pre-activation use of V2/V3 in §5 and in §14 / §14.2.

**S1 activation (K = 2).**
- S1 at K = 2 may activate when **V1 passes** and every other §14 item holds.
- V2 and V3 are **not** pre-activation conditions. They protect against false promotion, and S1 is not a promotion.
- Every §5, §6, §7, §9 and §15 halt and stop rule stays armed at K = 2 unchanged. The §5 Clopper-Pearson and burst rules bound the AMBIGUOUS rate during S1, so the ICC question is not needed for S1 safety.

**Every promotion look (S1→S2 and later).**

1. Before the look, BG-10 is rerun in **promotion-time mode**. It uses the same pinned seeds, resample counts and simulation assumptions as the O1 run. Its data is pre-window plus every non-excluded K > 1 stage day so far.
2. The rerun computes ICC_v as follows:
   - **Minimum data met:** at least 30 AMBIGUOUS events, at least 15 non-excluded days, and at least 8 days with two or more events. Then ICC_v = max(0.1, the **80% upper one-sided day-bootstrap bound** of the ANOVA ICC).
   - **Otherwise:** ICC_v = max(**0.4147**, the ANOVA estimate).
3. V2 and V3 are recomputed at ICC_v. The 90%→95% switch is triggered by V3 only, exactly as in K10.
4. The look is **taken only if V1–V3 all pass**. If they do not:
   - there is no look and no promotion;
   - the stage holds at its K (L3), and the hold is reported;
   - M5 cleanup demotion applies after 30 held days.
5. The promotion Wilson-DEFF bound itself (§5, the ICC line) uses **ICC_v** in place of the live floored estimate. A live estimate taken from the tested sample is anti-conservative, and ICC_v is never lower than it.

The upper bootstrap bound and the 0.4147 floor are what make this gate fail closed: thin or unlucky live data can never loosen it.

## O3. A hard K = 2 ceiling until an O2 pass

- **BG-9 config guard.** BG-9 fails when configured K > 2 unless a committed promotion-time record (`docs/evidence/exec_par/exec_par_bg10_promo_<stage>_<date>.json`) exists, is sha-pinned in an amendment, and shows V1–V3 PASS.
- **BG-3 boot guard.** BG-3 mirrors this check at boot: configured K > 2 without such a record forces K = 1, with a CRITICAL alert.

## O4. Additional stop rule rejected

The architecture review proposed a per-day AMBIGUOUS ceiling. It is not added:
- the §5 burst guard (≥5 AMBIGUOUS within 60 min of arm time) and the Clopper-Pearson α=0.01 halt (> 0.18 at n ≥ 20) already bound the AMBIGUOUS rate at K = 2;
- each AMBIGUOUS intent also denies further entries until it resolves (the R-7 latch).

Adding the ceiling would mean a fourth threshold with no analysed operating characteristic.

## O5. BG scope changes

| Package | Change |
|---|---|
| **BG-10** | The results JSON reports the **G6 verdict as primary** (`verdict: NOT_VIABLE_G6`) and the ICC 0.1 run under `sensitivity`. The current text calls 0.1 "used", which is wrong. |
| **BG-10(f), new** | Promotion-time mode for O2: pinned seeds, the ICC_v rule, and the minimum-data check. It emits the O3 record. Stage: before the first promotion look; it is not required for S1 activation. |
| **BG-5** | Day-level AMBIGUOUS counts per stage day go into the stage report, so that BG-10(f) can consume them. The in-node evaluator **never** promotes on its own: a promotion verdict requires the O3 record. |
| **BG-9 / BG-3** | The O3 guards. |

## O6. §5 recorded table (TBD rows filled at freeze)

The freeze fills the §5 TBD rows from the O1 values and the BG-10 artefacts:
- `exec_par_bg10_results.json`: sha recorded at freeze, after the O5 relabel;
- `exec_parallel_dhat_v2_results.json` (1f25257b…), the §3 re-run, which passes at K = 6 with every seed ≤ 0.2912.
