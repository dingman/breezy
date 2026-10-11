**VERDICT: NOT-READY** · **SCORE: 76/100**

r2 fixes most of r1, and every remaining fix is a text change. One premise is wrong, which is a BLOCKER under the brief: P14 counts one out-of-scope fill when there are five. Separately, the test design makes the "attribution" step close to unreachable without saying so.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| B1 | BLOCKER | **P14 is wrong.** `terminal_climate_day` is an inclusive climate day, so 10-06 is not a D+1 alias. But FIVE fills land on climate day 10-06, not one: SFO `gte81lt82`, SFO `gte83lt84`, MDW `lt70`, MDW `gte70lt71`, LAX `lt92`. All five were taken on 10-05 between 16:51Z and 19:31Z, after the 16:40Z halt that was meant to stop exactly those takes. The manifest is correct; the halt failed. So K1b's consumer ("manifest bug row: terminal vs D+1 take date") is aimed at the wrong thing. | `family_barrier.py:41-44, 85-91`; `pm_us_crh_fq_v1.json:6`; `breezy-trade-20261005T165040Z.log:706, 807, 869, 896, 235691`; `HALT_POINT_2026-10-04.md:10, 60` | Make K1b cover 5 fills on 3 station-days. Route it to the existing failed-halt incident, with no new manifest row. Pre-declare a sensitivity run without the 10-06 days (7→6 clusters). Never route the 25 rows through `assert_family_only`, which would refuse the whole batch. |
| B2 | HIGH | **Some verdicts are fixed before any data is read; others can't be reached.** The station-event rule gives 7 clusters, not "about 12" (P6). LAX's cluster P_c is at least 0.992 (S0-1), so T-WIN's p is at most 0.008 < 0.02 whatever happens. VARIANCE and INCONCLUSIVE therefore can't occur (§0 calls INCONCLUSIVE "live"). Exact sign tests on 7 clusters have a smallest possible p of 1/128 = 0.0078. That means T-LOC (Holm step 1, α 0.01) and T-ART (α 0.01) reject only if all 7 agree; on 6 clusters (the B1 sensitivity) neither can reject. So MODEL_MISCALIBRATED_UNATTRIBUTED is close to guaranteed, and it would read as a tested result. | §2 α table; P6 | In S0-I (before the freeze), compute the smallest attainable p for each test from the observed cluster count. Report any test that can't reject as NOT-TESTABLE, never as "did not reject". Fix P6 and §0. |
| B3 | MED | The downgrade rule says the cluster-level decision wins, but T-SPREAD is only defined per station-day. | §2 | Define T-SPREAD's cluster-level form, or exempt it from the rule. |
| B4 | MED | **A5 is only partly fixed.** No commit sha appears in the 10-04 boot log, so "pin from the boot log" can't be done. Of the logs, only that one was checked. | `breezy-trade-20261004T165012Z.log` has no commit or sha line | Pre-declare a reflog/committer-time rule. If the deployed code can't be identified, the fill is UNTESTABLE, not K1a. Say whether UNTESTABLE counts against the 23/25 threshold. |
| B5 | MED | **S0-F checks a different store from the one truth is read from.** `NwsCliFinal` reads the catalog (`read_climate_day_including_corrections`); `coverage.json` describes the fq-truth CSV. The pre-freeze "never read `tmax_f`" is a rule, not code: `record()` returns the whole object. | `settlement_source.py:41-51` | Run the coverage check on the catalog itself. Pass Phase A a projection without `tmax_f`, and test that. |
| B6 | MED | **The F13 consumer can't take TE-2's output, so the 10-20 date has no customer.** The F13 freeze (≥10-21) only fills in `source_lags_ns`/`source_breaks`. The distribution and ladder are already fixed in the plan, and the scorer refuses rows on or after 07-01. The TAIL and LOC_ARTEFACT rows ("input to F13 blend design") have nowhere to enter. | `F13_prereg_blend_v1.json:4, 11-20` | Route them to a named row for a later F13 revision or a T2/T3 candidate, and make 10-20 a soft target. |
| B7 | LOW | **Reuse is mostly real, with two catches.** The "keyed second pass on `now_ns`" is left over from r1's P4 (now ruled wrong). The partition union does need its own reader, because `read_log_events` keeps Takes only, not Refuses. "Import `fill_source`, not `exec.client`" avoids nothing: `fill_source.py:21` and `decision_link.py:28` both import `exec.client`. | as cited | Drop the second pass. Confirm the import pin is a direct-import check only, or widen its row in the same commit (L-12). |
| B8 | LOW | 10-20 is realistic on I/O: 15 cycle items, at most 30 requests, and `read_log_events` keeps only bridge events in memory. The risk is serial reviews plus the 23–25 min gate. | `nbp_backfill.py:127, 142`; `decision_link.py:161-170` | Leave as is; the plan already states the slip. |

**r1 A1–A11:**
- Resolved: A1 (C4.1 cited correctly; F13 refuses rows on or after 07-01, so no holdout use), A3 (23 per-cycle `NBM_NBP_PUBLISHED` lines across 9 logs, e.g. the 01Z 10-03 cycle at 02:10:27Z, 4 s before the MIA take), A4, A7, A8, A10.
- Partly resolved: A2 (B5), A5 (B4), A6 and A9 (B2, B6).
- Wrongly resolved: A11 (B1).

**Premises checked:**
- P3: CONFIRMED. 25 `OrderFilled` lines on FQ instruments.
- P5: CONFIRMED (`decision_link.py:161, 202, 213-214, 250`).
- P6: cluster count WRONG (7, not about 12).
- P7: CONFIRMED (C4.1 items 1, 2, 4).
- P9/P11: CONFIRMED. The log line fires once per cycle (`nbm_quantile_actor.py:542-551`).
- P10: PARTLY WRONG. The truth source is the catalog, not the CSV.
- P14: WRONG. 5 fills on 3 station-days, caused by the failed 10-05 halt.
- `holm_correction` at `:1670`: CONFIRMED.
- `DEFAULT_SPLITS` at `:273`: CONFIRMED (the plan cites `:277`, inside the same block).