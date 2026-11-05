[PLAN] TE-2 r3: Root-cause the FQ v1 loss result (2 wins in 25 fills, −2.17)

Status: r3. It revises r2 under the binding `reviews/CORRECTION_2026-10-11_band_semantics.md` and `reviews/TE-2-r2-merge.md`. The coordinator saves it to `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3.md`.

The plan is read-only analysis. It produces one committed analysis script and its tests, plus evidence artefacts. It does not arm, halt, refit or edit strategy code. No M1-v3 outcome data is read.

## 0. What is already covered, the delta TE-2 owns, and the honest expectation

| Covered | Source |
|---|---|
| S0-1 LAX 10-05 `<97`, p̂ 0.992, ask 0.64: genuine, recomputed by the bot from the NBM 13Z cycle | `FQ-LOSS-RESPONSE_plan_r3.md:87`; `FQ_LOSS_TRIAGE_2026-10-04.md:30-32` |
| S0-2 MIA p̂ 0.6368 comes from NBM's tight spread | plan r3 `:88` |
| Triage on n=14: Brier 0.075 vs market 0.048, mean p̂ 0.287 vs mean ask 0.142, NBM spread about 2 °F, 2–3 exclusive rungs stacked per station-day | triage `:9-23` |
| Fee, side, sizing, fee-θ drift and latency race are ruled out | triage `:25-28` |
| The M1 scan found no model-free cell. Cheap YES (ask < 0.10) is a "reliable loser" filter input | `M1_MARKET_SCAN_2026-10-04.md` |
| Corrected audit: FQ **25 fills, 2 wins, −2.17**. Wins are MIA 10-03 `gte86lt87` (tmax 87) and MIA 10-05 `gte89lt90` (tmax 90). Total 34 / 4 / −2.63. Slippage 0 on 34/34 | `TRADE_EFFECTIVENESS_2026-10-11.md:12-24` (corrected, inclusive [A,B]) |

The earlier "0/25", "−4.17" and "five 1 °F losses" figures are withdrawn. They used a half-open band rule.

**The delta TE-2 owns:**
1. A per-fill classification of all 25 fills into one pre-declared taxonomy: 2 WIN fills and 23 loss fills.
2. Exact tests at station-event cluster level, with their minimum attainable p and their power.
3. A split into fixable defect, model limitation and variance.
4. A committed, reproducible script. The audit re-score was hand-run.
5. A consumer for every finding, including INCONCLUSIVE and NOT-TESTABLE.

**Honest expectation, stated before any data is read:**
- The Oct FQ fills sit on 14 station-days in 7 station-event clusters (verified in P6). Only 6 clusters remain if the 10-06 station-days are excluded.
- Cluster arithmetic is tight. Exact sign tests on 7 clusters have a smallest possible p of 1/128 = 0.0078. On 6 clusters it is 1/64 = 0.0156.
- Several secondary tests will therefore be reported NOT-TESTABLE. That is a result, not "did not reject".
- T-WIN is now the lower tail P(W ≤ 2), not the zero-win product. Two wins sit in two separate MIA clusters, which is the corrected audit's win list combined with the cluster structure. The script recomputes this in Phase B.
- T-WIN is likely driven by one cluster. LAX has p̂ ≥ 0.992 on a losing fill, so P_c(LAX) ≥ 0.992 and the LAX cluster is a near-certain Bernoulli term under H0-M. A pre-declared leave-one-out T-WIN (drop the largest-P_c cluster) is therefore part of the design.
- The information gain of TE-2 is not the T-WIN verdict. It is the per-fill flags (K1a, K4, K1b), the descriptive table, and the attribution that can honestly be made.
- INCONCLUSIVE and MODEL_MISCALIBRATED_UNATTRIBUTED are the likely verdicts. VARIANCE is reachable only with cluster power ≥ 0.8 and at least one testable secondary.

## 1. Verified premises

Re-verified on 2026-10-11. CHANGED means the entry differs from r2. NEW means it is added in r3.

- **P1. FQ is D+1 only and prices YES off `p_lower`.** `src/breezy/strategy/forecast_quantile_ladder/decision.py:216-218`, `:277-281` (`NotDPlus1`), `:331` (p̂ is the mean of per-draw rung probabilities), `:349` (`ev_net(p_lower, cost)`), `:353-355`. `git log` shows no change to `decision.py` after 10-01T02:09Z (`3534c8ac`) and `749316c5` (10-01T01:54Z), so these cites hold for every 10-01..10-05 boot.
- **P2. The Take line carries no ask, no forecast vector and no `client_order_id`** (`decision.py:200-212`). The fill's `cumulativeCost` proxies the ask. The decision-time ask is unauditable (audit "Gaps", `:35-36`). The report must say so.
- **P3. Logs live in `~/.local/share/breezy/logs/breezy-trade-202610*.log`.**
  - There are 9 boot logs for 10-01..10-05. Names (UTC): 10-01 `151202`, `160158`, `165011`; 10-02 `165039`, `200526`, `205521`; 10-03 `165045`; 10-04 `165012`; 10-05 `165040`.
  - Sizes run up to 1.43 GB (10-03). Streaming is required.
  - Codex counted 32 Takes, 32 OrderInitialized and 25 OrderFilled (89 bridge events). 7 Takes are IOC misses.
  - `NBM_NBP_PUBLISHED` lines exist in all 5 daily boot logs (Codex: `…20261001T151202Z.log:388`, `…1002T165039Z.log:706`, `…1003T165045Z.log:786`, `…1004T165012Z.log:691`, `…1005T165040Z.log:689`).
- **P4. The ladder partition is NOT recoverable from same-`now_ns` lines.**
  - Each rung is evaluated at its own `now_ns`, and the log is on-change (`strategy.py:585-625`).
  - The partition is the union of `rung_id`s per (station, climate_day) across all logs, plus `instrument_facts.bucket_facts_from_instrument_id` (`instrument_facts.py:72`).
  - **Reader (CHANGED).** `read_log_events` keeps only bridge events (Takes, inits, fills). It drops Refuse lines. The partition union needs its own streaming reader that includes Refuse lines.
  - An incomplete union gives `PARTITION_INCOMPLETE`.
- **P5. The fill → Take join is a three-hop chain** (CHANGED details).
  - fill → OrderFilled → OrderInitialized by client id, then init → Take by instrument and time window.
  - `decision_link.py`: `read_log_events` `:161`, `bridge_decision` `:202`, `bridge_report` `:250`.
  - The `BackfillRefused` raise is at `:213-214` (`:211` is the docstring).
  - Call inputs: `fill.trade_id` (`None` gives `BridgeUnmatched("no_trade_id")`, `:215`). `epoch_class` comes from `epoch.py:98` `fill_epoch_class(fill, reader)`. An absent epoch file with no OrderLink in C1 gives PRE_EPOCH (`epoch.py:7`, `:91`).
  - `recalibration` feeds only `artefact_p_raw` (`probability.py:77`, `raw_yes` at `decision_link.py:243`). TE-2 does not use `p_raw`. Pass the artefact's recalibration token, or `None`.
  - Codex verified: attribution 25 attributed / 0 ambiguous / 0 missing, and all 25 fills are PRE_EPOCH.
  - `fill_source.py:58` `read_durable_fills` opens `mode=ro` and returns a `FillRead` (`fields: fills, n_keys, n_undecodable`). `require_clean` is at `:49`.
- **P6. Counts from the fill store's instrument ids (NEW, outcome-free; re-run by S0-A).**
  - The store `~/.local/share/breezy/state/exec_polymarket_us.sqlite` was read read-only through `read_durable_fills`. Only instrument ids were used.
  - Oct FQ: 25 fills on 25 distinct instruments, all YES (no `^no`), 6 open-ended bands (`lt`/`gte`), `n_undecodable` 0.
  - **14 station-days.** LAX 10-02..10-06 (5), MDW 10-02, 10-04, 10-05, 10-06 (4), MIA 10-03, 10-05 (2), SFO 10-03, 10-04, 10-06 (3).
  - Fills per station: LAX 8, MDW 8, MIA 4, SFO 5.
  - **7 station-event clusters.** LAX is one cluster. MDW has two (10-02; 10-04..06). MIA has two (10-03; 10-05; a 10-04 gap splits them). SFO has two (10-03..04; 10-06).
  - With the 10-06 station-days excluded there are **6 clusters** (SFO 10-06 disappears).
  - MIA 10-03 and MIA 10-05 each hold 2 distinct rungs, so one loss sibling sits on each winning day.
  - Open-band semantics: `slug_closed_interval` (`symbology.py:483-500`) gives `lt B` → (None, B−1), `gte A` → (A, None), `gteAltB` → [A, B] inclusive.
- **P7. Deployed-commit pin (CHANGED; the merge item 1(a) check was run).**
  - The boot logs carry `manifest_sha256=8e1217fd…` and `calibration_sha256=9c0b6d6e…`. They carry no commit sha. The node's commit goes only to the EXEC-PAR epoch ledger (`trade.py:1002-1012`, `:1150`), which has no rows for 10-01..10-05.
  - **Result of `git log --since=2026-10-01T00:00Z --until=2026-10-07T00:00Z` over `src/breezy/strategy/forecast_quantile_ladder`, `src/breezy/strategy/ladder_ev/forecast_state.py` and `deploy/families/*fq_v1*`: the log is NOT empty.** The pin is not moot, so rule (b) applies, label **PIN=INFERRED**. (`ArtefactBoundsProvider` lives in `forecast_quantile_ladder/artefact_bounds.py`, already covered by the path.)
  - Commits in the window (committer time):
    - Before the first boot (10-01T15:12:02Z). These are the FQ go-live commits `dfa75525`..`60290e9d`, last at 10-01T13:39:52Z, all in-tree for every boot.
    - 10-01T15:30:41Z `20aa5ea5` and 10-01T15:37:53Z `99067d4a`: `strategy.py` only (D+1 resolution and subscribe). They lie between boot 1 and boot 2 on 10-01 and are not on the `decision.evaluate` path.
    - 10-04T16:28:33Z `4ac87414` (author date 15:37Z): `forecast_state.py` +4 lines, the constant `NBP_QUANTILE_MODEL`. It is before the 10-04 boot at 16:50:12Z, so boots from 10-04 carry it.
    - 10-04T10:07Z and 10:33Z `062dad8f` and `232d06bc`: `capture_adapter.py` and `plugin.py` (AUT-1 capture).
    - 10-06T01:42:30Z `cebaab49`: manifest adds `terminal_climate_day`. It is after the last fill boot (10-05T16:50:40Z), so it is not in force for any fill. The manifest blob at HEAD sha256 is `324c01f8…`, which differs from the logged `8e1217fd…`. Corroboration must therefore use the blob AT the chosen commit, never HEAD.
    - 10-06T09:23Z `88dbda40`, `670efce3`, `df8197e7`: `loss_stop_probe.py`, after all fills.
  - **Corroboration verified today.** The manifest blob at `60290e9d` has sha256 `8e1217fd…`, which equals the logged value (10-05 boot). The artefact `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` has sha256 `9c0b6d6e…23a5`, equal to the logged `calibration_sha256`. The manifest at `ad76d2f2` was `f33a0f63…`, so the ad76d2f2 commit is not the deployed one.
  - Residual risk, disclosed: the node imports the working tree at boot. Uncommitted edits cannot be excluded, which is why the label is INFERRED.
- **P8. The FQ artefact is a validate-stage candidate.** Manifest `pm_us_crh_fq_v1.json`, sha256 **`8e1217fd…`** (the deployed blob). Artefact sha256 **`9c0b6d6e…23a5`** (CHANGED labels).
  - `NBP_S2_VALIDATE_RESULT_2026-09-30.md`: G2.0 (n=11604) and G2.1 (n=4335) are the calibration baseline. `month_10` mean residual is −0.20 °F, n=369, p=0.31 (`:264-269`). v5.0 parameters come from the 05-04..06-30 fit slice.
  - LOC_ARTEFACT is "v5.0 May–June parameter extrapolation to October". TE-2 on 7 clusters is weaker evidence than G2.1 and says so.
- **P9. Holdout.** C4.1 items 1, 2 and 4 of `RULING_holdout_freeze_and_forward_window_2026-10-03.md` freeze the holdout at [2026-07-01, 2026-10-02). Every FQ climate day is ≥ 10-02, so none is a holdout day. `nbp_calibration.py:273` `DEFAULT_SPLITS` still lacks the end date, so the script must never touch `open_holdout`. No new ruling is filed.
- **P10. The SL-13p parity harness refuses October days** (`nbp_shadow_parity_pure.py:98-132`, `PostFreezeTapeRefusedError`). Recompute with production `evaluate` plus injected inputs (S0-D).
- **P11. Which vector the strategy sees.** `nbm_quantile_actor.py:210-218` keeps the nearest-valid-start (D+1) window per station and variable. `available_at_ns = cycle_runtime_ns + measured_lag` (`:221-233`). Backfill availability comes from Last-Modified (`nbp_derived_store.py:142`). The two clocks differ, so the node log is the visibility source. The NBP TXN window length is UNVERIFIED (`NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md:42-53`).
- **P12. Truth path (CHANGED).**
  - Truth is the **catalog** read through `NwsCliFinal` (`settlement_source.py:41-51`, via `persistence/catalog.py:637` `read_climate_day_including_corrections`), graded by `score_trial` (`trial_scorer.py:167`).
  - `NwsCliFinal.record` returns the whole `NwsClimateDay` (`domain/nws_climate_day.py:117`), including `tmax_f`.
  - The protocol is `SettlementSource.record(station, climate_day)` (`settlement_source.py:37-38`). Plan: a clipping wrapper (below) and a projection without `tmax_f` for Phase A.
  - `fq-truth/truth_cli_finals.csv` and `coverage.json` describe a different store, so they are NOT the coverage check. The SFO 2026-03-11 gap there is irrelevant.
  - The catalog holding 10-02..10-06 for LAX, MDW, MIA and SFO is NOT verified here; S0-F checks it through a projection.
  - The loader hard-clips at `climate_day <= 2026-10-06`.
- **P13. Cycle and visibility source.** `poll_ledger.jsonl` starts at the 10-06 01Z cycle, so it covers no take cycle. The node logs carry `NBM_NBP_PUBLISHED cycle_ns=%d …` (`nbm_quantile_actor.py:546`, once per cycle, `:542-551`). Its log timestamp is the visibility time. `derived/nbp` stops at 09-29 and `derived/nbp5` at month 06, so October vectors are re-fetched (S0-D).
- **P14. Route-back policy.** `RULING_FQ-v2-NO-TRADE_2026-10-08.md:44-50`: T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (a new US source, F13). The F13 freeze review is ≥ 10-21 (`PROGRESS.md:104`).
- **P15. Lessons (repo-local, headers verified in `docs/core/LESSONS.md`).** L-1 `:8`, L-2 `:67`, L-12 `:620`, L-18 `:871`, L-40 `:1384`, L-42 `:1421`, L-52 `:1610`, L-55 `:1666`.
- **P16. Out-of-scope fills (CHANGED, replaces r2's P14).**
  - The manifest's `terminal_climate_day` is an inclusive CLIMATE day (`family_barrier.py:83-90`, `row.climate_day > terminal`; manifest HEAD `:6` is `2026-10-05`).
  - **FIVE fills** sit on climate day 10-06, on 3 station-days: LAX 1, MDW 2, SFO 2 (verified from instrument ids in P6).
  - The terminal day was added after the fact (`cebaab49`, 10-06T01:42Z). The manifest the node loaded had no such key (the logged `8e1217fd…` blob lacks it). The five fills were therefore in scope for the deployed node.
  - They were taken on 10-05 between 16:51Z and 19:31Z, after the 16:40Z halt. That halt FAILED and was redone on 10-06 (see `HALT_POINT_2026-10-04.md` and `HALT_POINT_2026-10-06.md`). The log lines are as cited by architecture r2 (`…20261005T165040Z.log:706, 807, 869, 896, 235691`); S0-B re-checks them.
  - Consequence: K1b is a bookkeeping flag on these five fills. It routes to the existing failed-halt incident. It is not a manifest bug, and no new manifest row is filed.

**Not verified; Stage 0 checks these:** that S3 still serves the 10-01..10-05 cycles; that a second truth source exists; that venue-resolved outcomes are readable; the catalog coverage for the four stations (P12); the per-boot pin table.

## 2. Statistical design (frozen before Phase B)

**Units.**
- The station-day is the exact unit. Its rungs are mutually exclusive (L-40), so W_d ∈ {0,1} and P_d = min(1, Σ p̂_i over the bought rungs).
- P_d sums p̂ taken at different cycles and assumes marginal calibration. The report states this.
- **Cluster (binding).** A cluster is a station-event: consecutive climate days at one station. W_c = 1 if any station-day in the cluster won. Observed cluster count: 7 (6 in the 10-06 sensitivity).
- Climate-day clusters are a descriptive sensitivity only.

**P_c under correlation.**
- Binding P_c = max over the cluster's P_d, clamped to P_c ≤ 1 − 1e-9. This is a valid lower bound on P(win in cluster) under any dependence (P(∪A) ≥ max P(A)). A smaller P_c makes the lower-tail p-value larger, so it is conservative.
- The independent value 1 − Π(1 − P_d) is reported as the optimistic bound.
- Any reported p-value below 1e-12 is printed "< 1e-12" and never as 0.

**α allocation (overall ≤ 0.05 by Bonferroni across three families):**

| Family | Tests | α |
|---|---|---|
| Primary | T-WIN | 0.02 |
| Secondary, Holm via `nbp_calibration.holm_correction` (`:1670`) | T-LOC, T-SPREAD | 0.02 |
| Artefact | T-ART | 0.01 |

**Tests.** All are exact, standard-library and conditional on take where noted. The Poisson-binomial recursion is checked against brute force.

- **T-WIN (primary, one-sided lower tail, cluster level).**
  - H0-M: W_c ~ Bernoulli(P_c), independent across clusters. The statistic is W = Σ W_c. The p-value is the exact P(W ≤ w_obs). With zero wins it reduces to Π(1 − P_c).
  - Companion H0-K uses ask-implied probability net of θ·p·(1−p) fees, with the SAME max-over-cluster rule and clamp.
  - Pre-declared **leave-one-out T-WIN**: drop the cluster with the largest P_c (ties go to the alphabetically first station) and test the remaining clusters. The report labels the full result "single-cluster-driven" if the leave-one-out does not reject.
  - The station-day-level result is a reported sensitivity.
- **T-LOC (Holm).** Exact sign test on the cluster-mean signed (tmax − corrected median).
  - **Two-sided.** No outcome-blind direction exists: the heat-bust prior is outcome knowledge. This makes the smallest attainable p twice 1/2^n.
  - Ties (zero signed error) are dropped, and n after drops is reported. The null is 0.5 on the pmf's own mid-rank convention, declared in the predeclaration.
  - It is labelled "conditional on take" (adverse selection, `decision.py:349-355`).
  - Companions: the same test on the raw NBM median, and the unfilled-Take contrast (7 IOC-missed Takes, descriptive).
  - T-LOC alone never yields FIXABLE.
- **T-SPREAD (Holm), cluster level (binding).**
  - Per cluster, A_c = 1 if any station-day in the cluster has mid-PIT outside [0.05, 0.95]. The null probability is q_c = max over the cluster's station-days of P(tail) from the model's own discrete pmf. This is a Fréchet lower bound, so the upper-tail test is conservative.
  - X = Σ A_c is Poisson-binomial over clusters. The test is one-sided (too many tail misses) and labelled "conditional on take".
  - The station-day-level version (Poisson-binomial over days) is a reported sensitivity and is subject to the downgrade rule.
  - **SPREAD versus LOCATION attribution is NOT identified.** A location bias also inflates the tail count. The report states this and never attributes a tail rejection to spread alone.
- **T-ART (own α).** Exact paired sign test on d = |corrected error| − |raw error| per cluster, H1: corrected is worse (one-sided). Ties are dropped and n after drops is reported. A rejection means "v5.0 May–June parameters extrapolate badly to October".
- **T-EDGE: exploratory, outside every family.** It is the exact P(X ≥ k) for the count of losing fills with `edge_dist_f == 1`, computed through the inclusive interval. The count is seen only after the freeze, so confirmatory weight is zero. The earlier "five 1 °F" figure is withdrawn and not an input.

**S0-I. Testability and power gate (outcome-blind, runs BEFORE the freeze).**
- For every test it computes the minimum attainable p from the observed cluster count and tie-free n. The threshold is the most lenient one the test can face: 0.02 for T-WIN and each Holm member, 0.01 for T-ART.
- A test whose minimum attainable p exceeds that threshold is **NOT-TESTABLE**. It is reported as such, never as "did not reject", and the verdict rules treat it as non-informative.
- Reference values: with 7 clusters, a one-sided sign test has min p 0.0078 (T-ART reaches 0.01 only on 7 of 7 same sign); a two-sided T-LOC has min p 0.0156 (reaches 0.02 only on 7 of 7, and misses the Holm step-1 threshold 0.01). On 6 clusters, T-ART (0.0156) is NOT-TESTABLE.
- T-WIN min attainable p is P(W = 0) under H0-M.
- **Power** is computed at station-day and cluster level (conservative P_c). The reject region is {W ≤ w*}, where w* is the largest w with P_H0(W ≤ w) ≤ 0.02. The alternative is H1-K, the ask-implied probability.
- **VARIANCE requires cluster-level power ≥ 0.8.** Power for the secondaries is not computed. Their minimum attainable p is the disclosed substitute.

**Verdict, deterministic, evaluated in this precedence:**
1. **FIXABLE_DEFECT.** Any fill carries K4, OR any **material** K1a (below). K1a is material only if it flips the take/no-take decision or |Δp̂| > 0.01. A deterministic recompute is not a counterfactual P&L. K3, K2, K1b, UNTESTABLE and CYCLE_AMBIGUOUS never produce FIXABLE. The statistical label below is still reported alongside it.
2. **MODEL_LIMITATION.** No material K1a or K4, and at least one TESTABLE member of {T-LOC, T-SPREAD (Holm), T-ART} rejects. Sub-label: ARTEFACT (T-ART), SOURCE (T-LOC or T-SPREAD rejects and T-ART does not), or both.
3. **MODEL_MISCALIBRATED_UNATTRIBUTED.** T-WIN rejects, no secondary rejects, no material K1a or K4. Sub-qualifiers: "single-cluster-driven" (leave-one-out does not reject) and "secondaries NOT-TESTABLE".
4. **VARIANCE.** T-WIN (and its leave-one-out) fail to reject, T-WIN is TESTABLE with cluster power ≥ 0.8, at least one secondary is TESTABLE, and no TESTABLE secondary rejects. NOT-TESTABLE tests neither support nor block. The report lists which tests were NOT-TESTABLE. (The "at least one TESTABLE secondary" clause is an r3 addition, kept because VARIANCE otherwise rests on no secondary evidence.)
5. **INCONCLUSIVE.** Everything else, with the reason stated.

Mixed results are a ranked list with share of loss, never one label.

**Downgrade rule.** If the station-day-level decision differs from the cluster-level decision for any test, the verdict is the cluster-level one and the report states the range. A decision that flips under the 10-06 exclusion sensitivity (6 clusters) is reported as "scope-sensitive" with both results. The verdict stays on the full 25 fills.

**Mandatory footer, pinned by a test, printed with every verdict:**
- "diagnostic, post-hoc, n = N station-days in C clusters, non-confirmatory"
- "This verdict is NOT permission to re-arm. Re-open routes are T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (new US source, F13), per RULING_FQ-v2-NO-TRADE_2026-10-08."
- "VARIANCE does not imply positive EV."

**Forbidden.** Counterfactual P&L such as "would have won with the 19Z cycle" (L-18); cycle comparisons are descriptive only. Any hand arithmetic: all numbers come from the script. Any edge-distance or band-membership computed other than through `bucket_facts_from_instrument_id`.

## 3. Taxonomy (frozen in `TE2_PREDECLARATION.json`)

**Per-fill descriptors, computed and not judged:**
- `p_hat`, `p_lower`, `ask_proxy` (fill cost).
- `edge_dist_f`: integer °F distance from `tmax` to the nearest edge of the bought **inclusive** interval [lower_f, upper_f] from `bucket_facts_from_instrument_id`. It is 0 inside the interval. For `lt B` the interval is (None, B−1]; for `gte A` it is [A, None); an open side is never the nearest edge. For a `^no` leg the YES interval is used and the leg is stated.
- Mid-PIT of `tmax` under the corrected model CDF, and the signed standardised error z.
- Raw vs corrected median error, and the correction in °F.
- Cycle age at decision, the newest visible cycle at `now_ns`, the PIN label and the boot log of the fill.
- Rungs bought on the same station-day, `PARTITION_INCOMPLETE`, and whether any fill on the station-day won.

**Primary class, per fill, first match wins, order pinned by a test:**

| Class | Rule |
|---|---|
| WIN | The fill's inclusive interval contains tmax. The loss taxonomy does not apply. |
| SIBLING_WON (K10) | A losing fill whose station-day contains a winning fill. This is the expected cost of stacked exclusive rungs. |
| BOUNDARY (K5) | Losing fill, `edge_dist_f == 1`, PIT in [0.05, 0.95] |
| TAIL (K6) | Losing fill, PIT outside [0.05, 0.95]. Mutually exclusive with BOUNDARY by definition. |
| BAND_SELECTION (K7) | Losing fill on a station-day with 2 or more bought rungs, all of which lost; tmax in the model's central 80% (PIT in [0.10, 0.90]); and not BOUNDARY. Needs a complete partition, otherwise UNTESTABLE for that station-day. |
| VARIANCE (K9) | Residual losing fill: body miss with `edge_dist_f >= 2` and none of the above |

- K7 is applied per fill using that fill's own `edge_dist_f`. One station-day can therefore yield a BOUNDARY fill and a BAND_SELECTION fill. The class counts are per fill, and a separate station-day-level K7 count is reported.
- The BOUNDARY-versus-BAND_SELECTION overlap is real ([0.10, 0.90] sits inside [0.05, 0.95]), which is why the order is pinned. BOUNDARY and TAIL cannot overlap, which a separate test pins.
- Classes are K5, K6, K7, K9, K10 and the flags are K1–K4. There is no K8.
- TAIL attribution: LOCATION if T-LOC rejects, SPREAD only if T-SPREAD rejects, otherwise unattributed. Spread and location are not identified.

**Orthogonal flags (multi-label, counted separately, never in the primary share):**

| Flag | Meaning |
|---|---|
| K1a INPUT_DEFECT | S0-D reproduction miss that survives root cause, or `available_at > now_ns`, or `vector.climate_day != instrument climate day`. Feeds FIXABLE only if material (§2). |
| K1b SCOPE | Fill on climate day 10-06, beyond the (post-hoc) `terminal_climate_day` 10-05. Five fills on 3 station-days (P16). Bookkeeping only, routed to the failed-halt incident. |
| K2 STALE_CYCLE | The cycle in use is not the newest visible at `now_ns`, or its age exceeds a maximum pinned in the declaration. Descriptive. |
| K3 TRUTH_BASIS | The outcome flips when ASOS/METAR max replaces CLI tmax. Descriptive only and never fixable: CLI is the settlement truth. |
| K4 VENUE_SEMANTICS | Venue-resolved outcome differs from the slug-parsed outcome (`lt`/`gteLlt H`, edge inclusivity), on a WIN or a loss. Uses the `reconcile.py` settlement leg. |
| LOC_ARTEFACT | The corrected median error is larger than the raw error. This per-fill flag fires about half the time by chance. Inference comes only from T-ART. |
| LOC_SOURCE | Raw NBM median error alone is beyond ±1 sd. |
| FLANK_CHEAP | Ask < 0.10, consistent with M1's reliable-loser cells. |
| CYCLE_AMBIGUOUS | Reconstruction cannot decide the cycle in use. |
| UNTESTABLE | The bulletin is unavailable or reissued, no deployed commit can be identified (P7), or the alternative-truth/venue source is absent. It is never counted as zero evidence. |

## 4. Stage 0 gates

All read-only. Any STOP is reported verbatim and halts the plan with no partial verdict.

**Pre-freeze, outcome-blind (Phase A):**

- **S0-A. Count-only reproduction.**
  - Use `read_durable_fills` plus `FillRead.require_clean`.
  - FQ fills must be 25 on 25 distinct instruments, every `instrumentId` must parse and `n_undecodable == 0` (else `FillStoreCorruption`, STOP).
  - Record the epoch class through `fill_epoch_class`. If POST_EPOCH, `bridge_decision` raises `BackfillRefused`, so STOP and re-plan the join on the C1 attribution path.
  - Emit the station-day, cluster and K1b counts (14 / 7 / 5 fills on 3 station-days). A mismatch with P6 is a STOP.
  - No wins and no P&L are computed before the freeze.
- **S0-B. Scope.** Confirm P16: which fills have climate day > `terminal_climate_day`, and the log lines of their orders. They get K1b. The batch is never routed through `assert_family_only`, which would refuse the whole batch.
- **S0-C. Take attribution, 25/25 required.** Use `read_log_events` over the October logs, then `bridge_decision` for each fill, then `bridge_report`. A fill that does not attribute to exactly one Take is UNCLASSIFIED and STOPs the plan. The 7 unfilled Takes form a separate census with no P&L.
- **S0-D. Reproduction gate.**
  - **Pin rule (CHANGED), per boot.**
    - (a) is evaluated and fails: `git log` over 10-01..10-06 is not empty (P7). The label is `PIN=INFERRED`.
    - (b) For each of the 9 boots, take the last branch commit with committer time ≤ boot time. Corroborate it: the blob sha256 of the manifest and artefact AT THAT COMMIT must equal the logged `manifest_sha256` and `calibration_sha256`. A fill whose boot fails corroboration is UNTESTABLE.
    - (c) If no commit can be identified, the fill is UNTESTABLE.
    - The script reproduces the (a) `git log` check and prints its result, so the label is data, not an assertion. If the future log is empty the label is `PIN=STABLE`.
  - **STOP if fewer than 23 of 25 p̂ match the logged value to 1e-9, counting UNTESTABLE as a non-match.**
  - **Inputs (all named):** the manifest and `ArtefactBoundsProvider` (`artefact_bounds.py`) from the pinned commit; `load_live_calibration(<manifest path>, <artefact sha>)`; a fresh `QuantileLadderLatch`; `cfg`, `fee_coefficient`, `slippage_floor_prob`, `latitude_deg`, `std_utc_offset_hours` as in `decision.py:221-241`; conventions from `scripts/analysis/fq_evaluate_shim.py`. `breezy.app` is never imported.
  - **Vector.** Rebuild with `ForecastQuantileState.push` (`src/breezy/strategy/ladder_ev/forecast_state.py:245`; the file has a second `push` at `:88` for the TXN class) and `value_at` (`:310`), applying the actor's D+1 `_nearest_per_station_variable` filter.
  - **Cycle and visibility** come from the node log `NBM_NBP_PUBLISHED cycle_ns=` lines. The poll-ledger sha check is N/A for 10-01..10-05.
  - **Fetch.** One coordinator step, run outside 16:30–17:10Z (`launch_window_guard`, `capture_schedule.py:36-51`):
    `BREEZY_LIVE=1 BREEZY_USER_AGENT=<monitored> .venv/bin/python scripts/analysis/nbp_backfill.py --start 2026-10-01 --end 2026-10-05 --output-dir <scratch> --request-budget <2 × planned items> --apply --report-json <scratch>/report.json`
    - Run `--dry-run` first. `build_plan` is date-major over cycles 13, 19 and 1 (about 15 items, at most 30 requests).
    - The backfill writes a parsed derived store carrying `raw_sha256`. Only the per-cycle `raw_sha256` and the small reconstructed-vector table are committed. Tests never touch the network.
  - **Classes.** A miss caused by an unavailable or reissued bulletin is UNTESTABLE. A cycle-selection mismatch is CYCLE_AMBIGUOUS. Only a miss that survives root cause as a code or data difference is K1a, with the delta recorded and the materiality rule (|Δp̂| > 0.01 or a decision flip) applied.
  - **Positive control.** A perturbed vector must produce a mismatch.
- **S0-E. Import and holdout guard.**
  - The AST pin is an allowlist of modules and names. It forbids `ast.Attribute` and string access to `open_holdout` or any holdout path, and any path under an M1-v3 directory. It mirrors `test_nbp_shadow_parity_contract.py`.
  - `lint-imports` does not cover `scripts/` (`pyproject.toml:61-67`). The AST pin plus `test_execution_egress_firewall_guard` (scans `scripts/`, `:133`) are the enforcement.
  - **Import pin (CHANGED).** `fill_source.py:21` and `decision_link.py:28` both import `breezy.adapters.polymarket_us.exec.client` transitively. WP0 confirms the exec-import pin (x1 and the set-equality rows in `test_execution_egress_firewall_guard.py`) checks DIRECT imports only. If the new `scripts/analysis/` modules trip it, the row is WIDENED in the same commit (L-12), never relaxed. The script never imports `exec.*` directly.
- **S0-F. Truth quality, scoped (CHANGED).**
  - Truth is the catalog via `NwsCliFinal`. Confirm the catalog holds 10-02..10-06 for LAX, MDW, MIA and SFO, and run the coverage and `catalog_disagreement == false` check on the catalog, not the CSV.
  - Wrap the source in a **clipping wrapper that implements the `SettlementSource` protocol** (`record(station, climate_day)`), returning `None` or refusing for `climate_day > 2026-10-06`.
  - Phase A receives a **projection** of the record without `tmax_f` (status, final, superseded, correction). A test record whose `tmax_f` raises on access must pass Phase A.
  - A flagged or superseded settlement day is `TRUTH_UNSETTLED`, with its exclusion count stated.
- **S0-G. Alternative sources.** Look for a METAR/ASOS series (`us_source_archive/metar-routine`, `asos-cache`, `settlement_alignment_study` loaders) and a venue-resolved outcome per instrument. If absent, K3 and K4 are UNTESTABLE.
- **S0-H. Freeze.**
  - Phase A emits the per-fill outcome-blind table: p̂, ask proxy, cycle age, newest-visible flag, rung geometry, PIN label, P_d, P_c and clusters.
  - `TE2_PREDECLARATION.json` holds the taxonomy, thresholds, tests, α allocation, sidedness, tie handling, S0-I results (minimum attainable p, NOT-TESTABLE list, power), verdict rules, footer text, consumer map, the cycle-age maximum, the P_c rule and clamp, the leave-one-out and sensitivity rules, and the Phase A table sha256. It does NOT store its own sha.
  - **Enforcement (CHANGED).** Phase B refuses unless all of these hold:
    - (a) the sha256 of the **HEAD blob** of the script and core module equals values in `TE2_PINS.json`, AND `git status --porcelain` on the pinned paths is clean;
    - (b) the predeclaration file is committed and its commit is an ancestor of HEAD (`git merge-base --is-ancestor`).
  - The "result artefact committed in a later commit than the predeclaration" check is a **post-hoc verifier test over the committed artefacts**, not a Phase B gate (the artefact does not exist at that point). There is no commit-message sha.
  - **Re-freeze rule.** A script bugfix after the freeze requires a new predeclaration commit and a disclosed re-freeze, with no Phase B result consumed in between.
  - Disclosed contamination: the audit and triage showed the headline direction (low win rate, LAX heat bust, MIA wins). The freeze constrains classification and thresholds, not the prior.

**Phase B (after the freeze):**
- Reproduce the corrected audit: 25 FQ fills, 2 wins, net −2.17 (cost + fee − payout, ±0.005); 34 fills / 4 wins / −2.63 total; Sep 9 / 2 / −0.46; wins MIA 10-03 `gte86lt87` (tmax 87) and MIA 10-05 `gte89lt90` (tmax 90). A mismatch is a STOP. Outcomes key on the INSTRUMENT climate day, not the order date.
- Join truth through the clipping wrapper, `NwsCliFinal` and `score_trial`.

## 5. Work packages

All work is native-first. Reuse the cited modules, `score_trial`, `holm_correction` and `bucket_facts_from_instrument_id`.
- `combine_station_day` (`current_rung_hold_v2.py:296-330`) is **not used**. It takes `StratumRow` (entry_ask, fee, qty), builds break-even probabilities, and raises `StationDayAdmissionRefusal` when Σq > 1. It does not sum p̂. P_d = min(1, Σ p̂) is the correct rule.
- Statistics use the standard library only.

**Layout (each file under 400 lines; 800 is a hard stop):**
- `scripts/analysis/fq_v1_loss_taxonomy.py`: CLI with Phase A and Phase B modes.
- `scripts/analysis/fq_loss_taxonomy_core.py`: pure, no I/O. Descriptors, classifier, Poisson-binomial, tests, verdict, footer.
- `scripts/analysis/fq_loss_taxonomy_inputs.py`: I/O wrappers over the reused modules, the clipping wrapper, the streaming reader, the Refuse-including partition-union reader and the pin resolver.
- Tests in `tests/unit/test_fq_loss_taxonomy_core.py` and `…_inputs.py`.

**WP0. Stubs first, then RED tests (tdd-guide).** Stubs raise `NotImplementedError`. RED means an `AssertionError` or `NotImplementedError`, never `ImportError`.

| # | Test |
|---|---|
| 1 | `poisson_binomial_matches_bruteforce_enumeration` |
| 2 | `lower_tail_P_W_le_k_matches_bruteforce_and_k0_equals_product_of_complements` |
| 3 | `station_day_collapses_exclusive_rungs_and_clamps_P_d_at_1` |
| 4 | `cluster_collapse_station_event_gap_splits_and_fixture_gives_14_days_7_clusters_6_without_10_06` |
| 5 | `cluster_P_c_is_max_of_P_d_clamped_and_zero_p_prints_below_bound` |
| 6 | `t_win_positive_control_high_P_c_with_few_wins_rejects` |
| 7 | `t_win_leave_one_out_drops_max_P_c_cluster_and_ties_go_to_first_station` |
| 8 | `h0_k_uses_max_over_cluster_and_clamp` |
| 9 | `edge_dist_inclusive_via_bucket_facts_upper_edge_inclusive_lt_gte_and_no_leg` (fixtures `gte86lt87` tmax 87 = inside, 88 = distance 1; `lt B`; `gte A`; `^no`; single-token `ltB`/`gteA`) |
| 10 | `pit_midpoint_for_integer_outcome_from_pmf` |
| 11 | `classifier_boundary_precedes_band_selection_on_overlap` |
| 12 | `boundary_and_tail_are_mutually_exclusive` |
| 13 | `win_class_and_sibling_won_apply_taxonomy_to_losers_only` |
| 14 | `k7_per_fill_rule_when_edge_dist_differs_within_a_station_day` |
| 15 | `partition_incomplete_marks_k7_untestable` |
| 16 | `t_spread_null_is_per_station_day_pmf_not_binomial_0_10` |
| 17 | `t_spread_cluster_level_uses_max_per_day_tail_probability` |
| 18 | `sign_tests_drop_zeros_and_report_n_after_drops` |
| 19 | `min_attainable_p_marks_not_testable_never_did_not_reject` (7 clusters testable, 6 NOT-TESTABLE for T-ART) |
| 20 | `t_loc_is_two_sided_and_t_art_one_sided` |
| 21 | `t_loc_and_t_art_collapse_to_cluster_level` |
| 22 | `cluster_power_computed_at_both_levels_against_h1_k` |
| 23 | `verdict_variance_requires_cluster_power_0_8_and_a_testable_secondary` |
| 24 | `verdict_miscalibrated_unattributed_branch_and_qualifiers` |
| 25 | `verdict_inconclusive_branch_states_reason` |
| 26 | `verdict_fixable_positive_path_for_k4_and_for_material_k1a` |
| 27 | `immaterial_k1a_below_0_01_without_decision_flip_is_not_fixable` |
| 28 | `t_loc_alone_k3_and_k1b_never_yield_fixable` |
| 29 | `model_limitation_sublabels_artefact_source_both` |
| 30 | `downgrade_rule_cluster_level_wins_and_scope_sensitive_label` |
| 31 | `footer_is_present_and_names_t1_t2_t3_not_permission_to_rearm` |
| 32 | `holm_over_two_tests_only_t_edge_excluded` |
| 33 | `clipping_wrapper_implements_settlement_source_and_clips_after_2026_10_06` |
| 34 | `phase_a_projection_without_tmax_f_passes_when_tmax_f_raises` |
| 35 | `truth_unsettled_for_flagged_or_superseded_day` |
| 36 | `ast_pin_allowlist_forbids_open_holdout_attribute_and_string_access` |
| 37 | `phase_b_refuses_without_head_blob_pins_clean_path_and_ancestor_commit` |
| 38 | `refreeze_rule_requires_new_predeclaration_commit` |
| 39 | `post_hoc_verifier_checks_artefact_commit_is_after_predeclaration` |
| 40 | `s0a_count_only_runs_without_any_outcome` |
| 41 | `all_25_fills_attribute_or_stop_unclassified` (epoch class from `fill_epoch_class`) |
| 42 | `s0d_perturbed_vector_mismatches_and_is_classed_k1a` (positive control) |
| 43 | `unavailable_bulletin_is_untestable_and_cycle_mismatch_is_cycle_ambiguous` |
| 44 | `pin_rule_stable_inferred_untestable_and_stop_below_23_counting_untestable` (blob sha at the commit, never HEAD) |
| 45 | `streaming_reader_is_a_lazy_generator_or_tracemalloc_bounded_and_keeps_a_take_split_across_a_prefilter_boundary` |
| 46 | `partition_union_reader_includes_refuse_lines` |
| 47 | `k1b_flags_five_fills_on_three_station_days_and_sensitivity_excludes_them` |
| 48 | `alt_truth_unavailable_marks_untestable_not_zero` |
| 49 | `reproduces_audit_25_fills_2_wins_minus_2_17` (Phase B; fixture written through the real writer path, `read_durable_fills` plus `require_clean`, L-42; includes the upper-edge-inclusive MIA 10-03 and 10-05 wins) |

Per L-55, run the production default path once where a fake dependency is injected.

**WP1. Phase A (outcome-blind).**
- Implement the readers, the join, the partition union, the pin resolver and the reconstruction. Run S0-A, B, C, D, F (projection only), G and I, and emit the Phase A table.
- Streaming is a line-wise prefilter on `'kind': 'Take'` plus the Refuse-including partition-union pass. There is no keyed second pass on `now_ns` (P4).
- The coordinator runs it under `systemd-run --user -p MemoryMax=4G -p LimitNOFILE=524288`, with `--basetemp` under `~/.cache` (not `/tmp`). One heavy job at a time.
- Interpreter: `/home/jon/breezy/.venv/bin/python`. No `uv`, no `pip`. In a worktree set `PYTHONPATH=<wt>/src`. No `git stash`.

**WP2. Freeze.**
- The coordinator commits `TE2_PINS.json` (HEAD-blob sha256 of the script and core module) and `TE2_PREDECLARATION.json`.
- The review checks that no Phase B quantity leaked in. Reviewers: prediction-market-reviewer (statistics, cluster rule, NOT-TESTABLE logic), python-reviewer (code), and an adversarial Codex review. The reviewer is not the TE-1 or script author.

**WP3. Phase B and classification.**
- Run the Phase B reproduction, the truth join, the alternative sources, the classification, the tests and the verdict. Write JSON and a generated `.md`.
- Add a TE-1 ledger cross-check block, or print "TE-1 cross-check pending". Do not build a second scorer.

**WP4. Findings, consumers and delivery.** See §7.

**Outputs (committed):**
- `docs/evidence/te2/TE2_PINS.json` and `docs/evidence/te2/TE2_PREDECLARATION.json`.
- `docs/evidence/te2/fq_v1_loss_taxonomy_<date>.json` and generated `.md`, recording the script and pin shas.
- Per-cycle `raw_sha256` values and the small reconstructed-vector table.

## 6. Dependencies and gate

- **Hard.**
  - The node logs and the durable fill store.
  - S3 serving of the 10-01..10-05 cycles (otherwise those fills are UNTESTABLE for S0-D, which can leave fewer than 23 matched and trigger the STOP).
  - `nbp_backfill`, and the catalog holding the four stations' 10-02..10-06 CLI records.
- **Soft.** The TE-1 ledger (cross-check only), a second truth series and a venue-resolved outcome source.
- **Sequencing.** WP0 → WP1 → WP2 (hard stage boundary) → WP3 → WP4.
- **Routing.** Grok, then Codex, then Claude tdd-guide for implementation. The coordinator runs `scripts/ci/run_tests_no_egress.sh` and reads the exit code before any push. Briefs restate the invariants: Nautilus immutable, `allow_short=False`, NO-SEND firewall, no operator caps, no live enablement, format only your own files.
- **Focused gate must include:** the new AST-pin test and `test_execution_egress_firewall_guard`; the exec-import pin and the citation map; all `test_autonomy_*` tests; `lint-imports` from the repo root, which must print "N kept, 0 broken" (and it does not cover `scripts/`).

## 7. Consumers and delivery (each finding maps to exactly one)

The coordinator turns each into a row in `docs/core/PROGRESS.md`.

| Finding | Consumer |
|---|---|
| K1a (material) | Bug row against the named module. Blocks any FQ re-open (T2). |
| K1b | The existing failed-halt incident (`HALT_POINT_2026-10-04.md`, `HALT_POINT_2026-10-06.md`). No new manifest row. Never `assert_family_only` on the batch. |
| K2 | Descriptive only. A feed-latency input to the F13 source review. |
| K3 | Descriptive only. If a route is wanted, the F13 US-source list. Never CF-2 or CF-7. |
| K4 | Venue-semantics row. Settlement alignment is fixed before any family trades this venue. |
| BOUNDARY (K5) | T2 input only. T-EDGE is exploratory. If it does not reject, close "no action: within model-expected near-misses". |
| SIBLING_WON (K10) | T2 take-rule input (rung stacking). |
| TAIL (K6) with LOC_SOURCE or SPREAD | A named PROGRESS row, "F13 r-next / T2-T3 candidate input". The F13 ≥ 10-21 freeze takes only `source_lags_ns` and `source_breaks`, so this cannot enter that freeze. The 25 fills are forward data under C4.1 and serve as a descriptive baseline, never a tuning set. |
| TAIL (K6) with LOC_ARTEFACT (T-ART) | The same PROGRESS row family, as a calibration note against `nbp_calibration`: v5.0 May–June extrapolation to October. |
| BAND_SELECTION (K7) | T2 take-rule input (minimum-ask filter, consistent with M1). |
| VARIANCE (K9) / VARIANCE verdict | Closed "no action" with the test, p-value and power, plus the T1–T3 footer. |
| MODEL_MISCALIBRATED_UNATTRIBUTED | F13 r-next / T3 input: the model is miscalibrated in a way these data cannot attribute. The next evidence is T1 (12-07) or a forward screen. |
| NOT-TESTABLE | Feeds the INCONCLUSIVE route 1 below: the number of forward days the minimum-attainable-p calculation says is required. |
| INCONCLUSIVE | Two named routes: (1) a forward-only evidence plan sized by what the power calculation says is needed, handed to T2; (2) closed "no action" until T1 (12-07) if that number is infeasible. The report states which. |

**Delivery.**
- Soft target: the result artefact is committed by 2026-10-20. The F13 freeze review (≥ 10-21) does not depend on it (see the TAIL row).
- If the S3 or fetch STOPs slip it, the report states the slip explicitly and cites TE-2 as "pending".

## 8. Risks

1. **Overfit on a small sample.** Mitigated by the outcome-blind Phase A, the pinned freeze, exact tests, the conservative P_c and the α split.
2. **Selection bias.** T-LOC and T-SPREAD are conditional on take. Mitigated by labelling, the unfilled-Take contrast, and T-LOC alone never yielding FIXABLE.
3. **Cluster-count power.** With 7 (or 6) clusters, several tests cannot reach α. Mitigated by S0-I NOT-TESTABLE reporting before the freeze, and the rule that non-testable never reads as "no effect".
4. **Single-cluster T-WIN.** Mitigated by the pre-declared leave-one-out and the "single-cluster-driven" qualifier.
5. **Deployed-code identity.** The pin is inferred, and working-tree edits cannot be excluded. Mitigated by blob-sha corroboration at the chosen commit, UNTESTABLE for unidentified fills, and the 23-of-25 STOP counting UNTESTABLE as a miss.
6. **Cycle retention or reissue.** Handled as UNTESTABLE or CYCLE_AMBIGUOUS, never silently skipped and never K1.
7. **Ask proxy.** The fill cost stands in for the decision-time ask (zero-slippage audit). State it in the report.
8. **Unverified TXN window.** Do not assert window alignment as a cause.
9. **Truth basis.** CLI is the settlement truth. The venue-side settlement was not cross-checked, so K4 may stay UNTESTABLE.
10. **Band-semantics regression.** The earlier half-open rule produced the withdrawn figures. Mitigated by routing every band through `bucket_facts_from_instrument_id` and by test #9 and #49.
11. **Resources.** 1.4 GB logs, memory caps, scratch directory and `~/.cache` basetemp as in WP1.
12. **Verdict misuse.** The footer test (#31) prevents VARIANCE from reading as permission to re-arm.

## 9. Non-goals

- No re-arm, no un-halt, no `BREEZY_ORDERS_ENABLED` change, no permit work. `RULING_FQ-v2-NO-TRADE` stays in force.
- No edits to `src/breezy/strategy/**`, `nbp_calibration`, the artefact or any manifest. A defect found becomes its own bug row.
- No refit, no new model, no `open_holdout`, no marker write.
- No change to PREREG semantics, F13 pins or `F13_prereg_blend_v1.json`.
- No M1-v3 outcome data, and no truth row after 2026-10-06 held or printed.
- No second scorer and no TE-1 build. No NO-side analysis (TE-3; the FQ fills are all YES). No live network calls from tests.
- No new holdout ruling and no new manifest row.

## 10. Acceptance (the goal state)

- [ ] All 25 fills carry a primary class (WIN, SIBLING_WON, BOUNDARY, TAIL, BAND_SELECTION or VARIANCE) and flags, or an explicit UNTESTABLE, TRUTH_UNSETTLED or UNCLASSIFIED-STOP reason.
- [ ] One verdict with tests, p-values, NOT-TESTABLE list, power (station-day and cluster level), the leave-one-out and the 10-06 sensitivity, and the mandatory footer. A ranked list when mixed.
- [ ] Every finding maps to one named consumer, including INCONCLUSIVE and NOT-TESTABLE, with a soft delivery date or a stated slip.
- [ ] The result reproduces from the committed script. The post-hoc verifier test passes (artefact commit after the predeclaration, HEAD-blob pins, ancestor check).
- [ ] The full gate passes with a read exit code, and no re-arm took place.

**Key paths for the implementer:**
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/decision.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/artefact_bounds.py`
- `/home/jon/breezy/src/breezy/strategy/ladder_ev/forecast_state.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/fill_source.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/decision_link.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/epoch.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/instrument_facts.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/settlement_source.py`
- `/home/jon/breezy/src/breezy/settlement/trial_scorer.py`
- `/home/jon/breezy/src/breezy/settlement/family_barrier.py`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/src/breezy/ingest/nbm_quantile_actor.py`
- `/home/jon/breezy/scripts/analysis/nbp_backfill.py`
- `/home/jon/breezy/scripts/analysis/fq_evaluate_shim.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- `/home/jon/breezy/docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md`
- `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`
- `/home/jon/.local/share/breezy/logs/breezy-trade-202610*.log`

## Changes from r2

| Source item | Disposition in r3 |
|---|---|
| Band correction (merge item 0) | Adopted. FQ is 2 wins in 25 fills, −2.17. Every "0 wins" and "five 1 °F" premise is restated or withdrawn. T-WIN is the exact lower tail P(W ≤ w_obs). `edge_dist_f` uses the inclusive interval through `bucket_facts_from_instrument_id`. Fixtures cover upper-edge-inclusive, `^no` and single-token `ltB`/`gteA` (test #9, #49). Winning fills get class WIN, and the loss taxonomy applies to losers only. |
| New class SIBLING_WON (K10) | My addition. The corrected wins sit on MIA station-days that each hold 2 distinct rungs, so a loss sibling exists. Its loss is the expected cost of stacked exclusive rungs and is not a model fault. |
| Merge 1(a): the git-log check, RUN | Result reported in P7. `git log` over 10-01..10-06 on the FQ paths is NOT empty (`20aa5ea5`, `99067d4a`, `062dad8f`, `232d06bc`, `4ac87414`, `cebaab49`, and three 10-06 `loss_stop_probe` commits). The pin is not moot, so rule (b), PIN=INFERRED, applies. Only `4ac87414` (a constant) falls between fill boots on the decision path. |
| Merge 1(b)(c) pin rule | Adopted in S0-D. Per-boot committer-time rule; blob-sha corroboration at the chosen commit (verified: manifest at `60290e9d` = `8e1217fd…`, artefact = `9c0b6d6e…`; HEAD manifest differs after `cebaab49`); UNTESTABLE otherwise; STOP below 23 counting UNTESTABLE as a miss. Boot logs carry no commit sha (codex BLOCKER, python N1, arch B4). |
| Merge 2 / arch B1 (out-of-scope fills) | Adopted. Five fills on 3 station-days (verified from instrument ids). Routed to the existing failed-halt incident, with no new manifest row and no `assert_family_only`. 10-06 exclusion sensitivity added (6 clusters). New nuance: the deployed manifest lacked the terminal day (added by `cebaab49` after the fills), recorded in P16. |
| Merge 3 / domain R2-2, R2-3, R2-7 / arch B2 | Adopted. P6 fixes the cluster count to 7 (6 in the sensitivity), 14 station-days. S0-I runs before the freeze and computes the minimum attainable p. NOT-TESTABLE is distinct from "did not reject". Leave-one-out T-WIN added. §0 states the single-cluster driver and that the gain is the flags. Ties are dropped with n reported. T-LOC is declared two-sided. P_c is clamped at 1 − 1e-9 and p < 1e-12 is printed as a bound. |
| Merge 4 / domain R2-4 / arch B3 | Adopted. T-SPREAD is defined at cluster level with the maximum per-day tail probability. The downgrade rule applies to it. Spread-versus-location attribution is stated as not identified. |
| Merge 5 / domain R2-5 | Adopted. A K1a feeds FIXABLE only if it flips take/no-take or |Δp̂| > 0.01. |
| Merge 6 / domain R2-6 | Adopted. H0-K uses the same max-over-cluster rule and clamp. |
| Merge 7 / domain R2-1 | Adopted. Test #11 tests BOUNDARY against BAND_SELECTION. #12 adds BOUNDARY/TAIL mutual exclusion. K7 is defined per fill (#14). |
| Merge 8 / python N2 | Adopted. HEAD-blob sha256 plus a clean-path check; the ancestor check stays; result-commit order moves to a post-hoc verifier test (#39); the commit-message sha is dropped; a re-freeze rule is added (#38). |
| Merge 9 / python N4 / arch B5 | Adopted. Truth is the catalog via `NwsCliFinal`. Coverage is checked on the catalog. A clipping wrapper implements `SettlementSource`. Phase A gets a `tmax_f`-free projection, tested with a raising record (#33, #34). |
| Merge 10 / python N3, N6–N8 / arch B7 | Adopted. sha labels corrected (manifest `8e1217fd…`, artefact `9c0b6d6e…`). `combine_station_day` is dropped, with the reason. `BackfillRefused` is at `:213-214`, with `trade_id`, `recalibration` and `epoch_class` sources named. `forecast_state` has its full path. The keyed second pass is dropped. The partition-union reader includes Refuse lines (#46). The import pin is confirmed direct-only or widened in the same commit (L-12). |
| Merge 11 / arch B6 | Adopted. TAIL and LOC_ARTEFACT go to a named PROGRESS row, "F13 r-next / T2-T3 candidate input". The F13 ≥ 10-21 freeze takes only `source_lags_ns` and `source_breaks`. 10-20 is a soft target. |
| Merge 12 / python N5 | Adopted. RED is `AssertionError` or `NotImplementedError`. The #10 typo is fixed. #45 uses a lazy generator or tracemalloc. New tests cover the downgrade rule, FIXABLE positive path, MODEL_LIMITATION sub-labels, INCONCLUSIVE, cluster collapse, cluster power, PARTITION_INCOMPLETE and K7 UNTESTABLE, TRUTH_UNSETTLED, a T-WIN positive control, NOT-TESTABLE and leave-one-out. |
| Merge 13 | Adopted. Codex PASS facts are cited as premises in P3 and P5: 25/0/0 attribution, all PRE_EPOCH, 32 take / 32 init / 25 filled events, `NBM_NBP_PUBLISHED` in all 5 daily boot logs. |
| VARIANCE guard (my addition) | VARIANCE additionally requires at least one TESTABLE secondary, so it never rests on no secondary evidence (domain R2-7). |
| Premise re-verification | `decision_link.py:161, 202, 213-214, 250`; `fill_source.py:21, 49, 58`; `settlement_source.py:37, 41`; `family_barrier.py:83-90`; `symbology.py:483-500`; `instrument_facts.py:72`; `epoch.py:98`; `forecast_state.py:88, 245, 310`; `nbm_quantile_actor.py:546`; `nbp_calibration.py:273, 1670`; `trade.py:1002-1012, 1150`; LESSONS headers L-1, L-2, L-12, L-18, L-40, L-42, L-52, L-55. The `DEFAULT_SPLITS` cite is corrected from `:277` to `:273`. |
| Not re-verified here | The 10-05 log line numbers for the five K1b orders (architecture r2 cite; S0-B re-checks them), and the F13 prereg line cites. |