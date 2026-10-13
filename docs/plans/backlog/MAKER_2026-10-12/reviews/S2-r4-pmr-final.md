# S2 r4 final verification (delta rev 2 + amendment DRAFT rev 2): prediction-market-reviewer, 2026-10-13
Verdict: **READY-WITH-EDITS.** No CRITICAL/HIGH open. Six text edits (E-A..E-F), none a redesign. Build of WP0-WP4 on fixtures may start now (no edit touches their logic); E-A..E-F must land before the amendment goes FINAL (E5) and before WP5/WP6 merge.
Read: delta rev 2, amendment rev 2, round-2 review, holdout ruling clauses 1-3, AUT-4 r10 :570-578, `fq_loss_floor_mc_maker_templates.py:70-110,138-148`, S3 r4 delta :31-48,140-166, r3 L27-67,185-203.

## 1. Disposition
| Id | Status | Evidence |
|---|---|---|
| H-1 ICC unit | RESOLVED | (f) `fill_icc_rung_trial`: ANOVA on stressed 0/1 position indicators (station-day x rung, <=8/date), clusters = dates, [0,1], null never 0.5; `fill_icc_station_day` report-only; (n)3 S3 floors at 0.5/7. Matches the per-rung-trial unit, m=8 (templates :79-85,144). k=1 gap: N-3 |
| H-2 reads beyond licence | RESOLVED, one wording conflict | amendment §1 items 1-5 exhaustive; delta (b) "every read is one of items 1-5"; verify-first fixed to 2026-06-30; tail licensed by name. Conflict: N-1 |
| H-3 holdout/AUT-4 | RESOLVED, one nit | amendment §2: 10-01 sealed and excluded; disclosure cites clause 2 + AUT-4 :574; "NBP S2" disambiguated. Nit: N-5 |
| M-1 estimator | RESOLVED (coordinator ruling applied consistently) | (a): V0 on imported RHO_ASSUMED/N_EFF_FLOOR, n_sd fixed pre-fill; fitted ICC report-only, explicit MSB/MSW/m0, undefined at n_sd = n0, banner. No residual max(rho_hat,0.5/7); (l) row marks it superseded |
| M-2 `k` alias | RESOLVED | (f) "No `k` key", test asserts absent, (n)2. k=1 carry-over incomplete: N-3 |
| M-3 r_lo across hypotheses | PARTLY | prefix rule "every key prefixed r_lo is the minimum" breaks for `r_lo_by_hypothesis` (a dict) and `r_lo_se_cluster_boot` (min of SDs is least conservative). N-2 |
| M-4 re-run contradiction | RESOLVED, one gap | (c) + amendment §3 exception list and addendum. Gap: N-4 |
| M-5 bracket order | RESOLVED | (a) V0 first on min n_eff_gov, then NO-GO > NKU > NK, ties to lower r_lo; test named |
| M-6 frozen-set rule | RESOLVED | (b) + amendment §1 rule, parsed block, fail-closed list, `test_frozen_set_equals_rule...`; no-E5 bound 8 x 4/2.5 = 12.8 verified |
| M-7 S3 allowlist | RESOLVED | (n)1 exact strings, test renamed, no claim until merged |
| L-1..L-4 | RESOLVED | (f): IQR inverted_cdf in $; lower median idx floor((n-1)/2); n_stressed_fills, realised_bid_median_base; lcb = 2.5th pct "not one-sided" |
| L-5 | RESOLVED | (a) "Under V0": threshold comparisons, test named |
| L-6 | RESOLVED | (i)3 S-7 pre-pass before scoring, void for non-result cause |
| L-7 | RESOLVED | Verified block, (e), (k): select_rungs is a WP3 deliverable |

## 2. New findings
**N-1 [MED] "exactly one scoring pass" vs report-only passes (amendment §1 item 1; delta (d), (i)1, (g)).** The overlay "second pass", +60 min stress and poll-lag stress each re-replay NBP + tape on the frozen set and write sidecars; read literally they are extra passes outside item 1.
E-A: amendment §1 after "There is one scoring pass.": "The report-only overlay and the +60 min and poll-lag stress variants are computed inside that same verdict invocation (one ledger entry), read the same data as item 1, write only the named sidecars, and set no label." Delta (d), (i)1: "computed inside the verdict invocation".
**N-2 [MED] `r_lo*` prefix rule (delta (f) :144, :152-156).** E-B: replace with "`r_lo`, `r_lo_station_day`, `r_lo_position`, `r_lo_k1`, `r_lo_lcb_cluster_boot` are each the minimum over unit hypotheses. `r_lo_by_hypothesis` is the per-hypothesis map. `r_lo_se_cluster_boot` is the SD of the draws of the hypothesis attaining the minimum `r_lo_lcb_cluster_boot`." Emit `r_lo_lcb_by_hypothesis`; test asserts lcb == its min.
**N-3 [MED] k=1 carry-over incomplete ((f), (n)4).** S3 (r4 delta :31-45) freezes a cell at the admitted k and checks f_kill and f_pass per cell; (n)4 maps only the k=2 pair. No k=1 lcb or k=1 ICC exists, so a k=1 selection leaves S3 without f_pass and ICC.
E-C: add to (f) `r_lo_k1_lcb_cluster_boot` (2.5th pct, K1 station-day bootstrap, min over hypotheses) and `fill_icc_rung_trial_k1` (same ANOVA on K1 stressed position indicators, <=4/date, null when undefined). Extend (n)4: "for k=1, f_kill = r_lo_k1, f_pass = r_lo_k1_lcb_cluster_boot, ICC = fill_icc_rung_trial_k1; S3 maps units per its own contract". Extend the key test. S3 brief note: a measured rung-trial ICC > 3/7 maps to >= 1 and trips MakerRefusal (templates :144); S3 must define that outcome (refuse the binding run, say so), not clip.
**N-4 [MED] Ledger re-run not mechanically non-forkable (delta (c) :91-94; amendment §3).** The driver checks only the addendum sha; a completed run that printed a verdict could be re-run on a "crash" claim.
E-D: delta (c) and amendment §3: "The driver refuses an addendum unless the named run_id directory is `.void`-renamed and contains none of scored_episodes.csv, s3_inputs.json, verdict.*; a run that wrote any of them has produced a result and is never void." Test `test_ledger_refuses_addendum_for_run_with_result_files`. The same addendum form may name a substitute verify-first day <= 2026-06-30 (by date, before step 5).
**N-5 [LOW] AUT-4 anchor (amendment §2 :42).** AUT-4 r10 :574 says "proposed 2026-10-02". E-E: "anchored (proposed) at 2026-10-02 by AUT-4 r10 :574; clause 2 makes days >= 2026-10-02 forward data". Substance is right against clauses 1-3 (10-01 sealed; clause 3 window ends 10-01 exclusive; 10-02..10-13 forward).
**N-6 [LOW] Truth cross-check parquet.** (g) pins one; item 1 says "CLI truth" only. E-F: name "the pinned truth CSV and its cross-check parquet, same days" in item 1.

## 3. Amendment verdict
Every plan read maps to items 1-5 (verdict pass; bench; verify-first 2026-06-30; WP0 control + step-2 print timestamps; tail-only 07-01..09-17), subject to E-A and E-F. 10-01 excluded consistently: delta (b) rule and driver refusal, (j) 17/25 count, amendment §1 rule + block + fail-closed list, §2, §3. Forfeiture 72 and ceiling 25 dates reconcile (8 + 17). Holdout/AUT-4 disclosure correct apart from N-5. Ledger non-forkable once E-D lands.
**COMPLIANT with RA-13 B-3 after E-A, E-D, E-E, E-F**; fill the block and go FINAL only after those; S2 pins the FINAL sha.

## 4. (o) rulings
1. ACCEPT. Fails closed at step 5; any substitute day via dated addendum (E-D) before step 5, never chosen after alignment output.
2. ACCEPT. Do not edit S1 after its frozen run to add an alias. If lint blocks the private import, use a scoped noqa or restate the one-line formula in the test over the same dict, still importing RHO_ASSUMED; the equality test must exist either way.
3. ACCEPT for k=2 (report prints the hypothesis each ICC came from); k=1 handled by N-3.
4. ACCEPT the mechanism, make it discoverable: append to the RA-13-FW ledger line (amendment §4) "; AUT-4 forward windows: 2026-10-02..10-13 MAKER-S2 NBP-vs-outcome statistics disclosed as descriptive contamination". No AUT-4 plan edit required.

## 5. Contradictions with r3 text in force
None beyond N-1..N-4. r3 L44 TAIL-MISCALIBRATED annotation (step 9) is consistent with "never the label"; r3 L175 "min over unit" agrees with (f) after E-B.
