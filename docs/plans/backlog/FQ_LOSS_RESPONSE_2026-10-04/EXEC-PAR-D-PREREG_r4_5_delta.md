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
2. **ICC_v.** The rerun computes ICC_v as the maximum of the terms below. This applies in **every** branch, so ICC_v is never below 0.4147.

   | Term | When it applies |
   |---|---|
   | 0.4147 | Always |
   | the ANOVA estimate | When it is defined |
   | the **90% upper one-sided day-bootstrap bound** of the ANOVA ICC | When there are at least 40 AMBIGUOUS events and at least 12 days with two or more events |

   - **Undefined terms.** An undefined or NaN term (for example, no multi-event days) is omitted. The 0.4147 floor still applies.
   - **Lowering the floor.** Taking ICC_v below 0.4147 requires a new amendment, and that amendment needs both of:
     - at least 60 events;
     - a 95% upper bound below 0.4147.
3. **Same value everywhere.** The same ICC_v feeds V2, V3 and the DEFF in item 5. There is no separately floored live value. m̄ (K10) is not floored. V2 and V3 are recomputed at ICC_v, and the 90%→95% switch is triggered by V3 only, exactly as in K10.
4. **Outcome of a look.** A look is **taken only if V1–V3 all pass**. If they do not:
   - there is no look and no promotion;
   - the stage holds at its K (L3), and the hold is reported;
   - M5 cleanup demotion still applies. Its 30-day counter runs from the latest `stage_reset` (N4), and a failed look never resets it.
5. **Promotion bound.** The promotion Wilson-DEFF bound itself (§5, the ICC line) uses **ICC_v** in place of the live floored estimate. An ICC estimated live from the tested sample is anti-conservative.
6. **One run per look.** Each look gets exactly one BG-10(f) run.
   - If the run crashes or errors, it may be rerun **with identical inputs only**. The first complete output is the record.
   - The inputs are snapshotted when the run starts. The snapshot covers the counters and the `excluded_days` set, which is written only by the existing BG-1d/BG-5 rules and never edited by hand. The record carries the snapshot's sha.
7. **When BG-10(f) fails.** In each of the cases below, the look is not taken, the stage holds (L3), and a CRITICAL alert is raised:
   - an error with no complete output;
   - a timeout;
   - a missing record;
   - a stale record, meaning older than 24 h at the time of the look;
   - a record whose stage or date does not match the look.

This gate fails closed: no amount of live data, thin or plentiful, can lower ICC below the pre-window G6 value without a new amendment.

**S1 exposure before the first look.** This exposure is bounded by the §15 stops (−0.15 of the daily budget per day and −0.40 of it per stage), by the §5 Clopper-Pearson and burst halts, and by the R-7 AMBIGUOUS latch. The CP halt cannot fire before n = 20. The §15 stage stop is the binding bound on loss in clustered-failure scenarios. That residual risk is accepted.

**Relationship to K10.** K10's "nothing else may be tuned after the result is seen" applies to the O1 numbers, and they stand unchanged as NOT VIABLE. O2 and O3 are procedural amendments that are strictly more conservative than G6: they never pass a case that G6 would fail. The freeze-time three-lens review must explicitly confirm or reject this characterisation.

## O3. A hard K = 2 ceiling until an O2 pass

- **BG-9 config guard.** BG-9 fails when configured K > 2 unless a committed promotion-time record (`docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/promo/exec_par_bg10_promo_<stage>_<date>.json`, beside the amendments that pin it; never under `docs/evidence`, which `src` may not read — `test_no_module_under_src_reads_docs_evidence`) meets all of these:
  - it is sha-pinned in an amendment;
  - it shows V1–V3 PASS;
  - its stage is the stage being promoted from;
  - it is the latest record for that stage, so it is not superseded by a later failed look.
- **BG-3 boot guard.** BG-3 mirrors this check at boot. A configured K > 2 with a missing, invalid or non-matching record forces K = 1, with a CRITICAL alert.

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
