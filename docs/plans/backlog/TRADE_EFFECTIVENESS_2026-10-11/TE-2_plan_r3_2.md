# TE-2 r3.2 (coordinator statistical-correction pass over r3.1: r3.1 domain C1–C4, arch R1–R2): Root-cause the FQ v1 loss result (2 wins in 25 fills, −2.17)

Status: r3.2 (coordinator pass over r3.1; see the closing changes table). r3.1 was a targeted revision of r3 under the binding `reviews/TE-2-r3-merge.md` (items 1–10). The coordinator saves it to `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3_1.md`. The architecture and domain reviewers then run a confirmation pass.

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

**Honest expectation, stated before any data is read (r3.1, restated for w_obs = 2 of 7):**
- The Oct FQ fills sit on 14 station-days in 7 station-event clusters (verified in P6). Only 6 clusters remain if the 10-06 station-days are excluded.
- Exact sign tests on 7 clusters have a smallest possible p of 1/128 = 0.0078. On 6 clusters it is 1/64 = 0.0156.
- Several secondary tests will therefore be reported NOT-TESTABLE or TESTABLE-CONDITIONAL (§2). That is a result, not "did not reject".
- T-WIN is the lower tail P(W ≤ 2) over 7 clusters. It rejects only if ΣP_c is well above 2. With the triage's mean p̂ of about 0.29 per fill and a near-certain LAX cluster, ΣP_c may sit only moderately above 2. **INCONCLUSIVE from non-rejection is the likelier outcome.** MODEL_MISCALIBRATED_UNATTRIBUTED is the next most likely. VARIANCE is reachable only with cluster power ≥ 0.8 and an unconditionally TESTABLE secondary, and then carries "weak" unless the secondaries' own power is known. This paragraph is an expectation, not a computed value.
- The LAX cluster has P_c ≥ 0.992 on a losing fill. The pre-declared leave-one-out T-WIN drops the largest-P_c cluster. When the dropped cluster is a **win** cluster, w_obs is recomputed on the remaining clusters (w_obs − 1). When it is a loss cluster, w_obs is unchanged and the cluster count falls to 6.
- The leave-one-out sits **outside the α budget**. It cannot reject for the plan. It can only block VARIANCE or add the "single-cluster-driven" label.
- The information gain of TE-2 is not the T-WIN verdict. It is the per-fill flags (K1a, K4, K1b), the descriptive table, and the attribution that can honestly be made.

## 1. Verified premises

Re-verified on 2026-10-11. CHANGED means the entry differs from r3.

- **P1. FQ is D+1 only and prices YES off `p_lower`.** `src/breezy/strategy/forecast_quantile_ladder/decision.py:216-218`, `:277-281` (`NotDPlus1`), `:331` (p̂ is the mean of per-draw rung probabilities), `:349` (`ev_net(p_lower, cost)`), `:353-355`. `decision.py` last changed in `749316c5` (10-01T01:54Z) and `3534c8ac` (10-01T02:09Z); both are ancestors of every pinned boot commit in P7.
- **P2. The Take line carries no ask, no forecast vector and no `client_order_id`** (`decision.py:200-212`). The fill's `cumulativeCost` proxies the ask. The decision-time ask is unauditable (audit "Gaps", `:35-36`). The report must say so.
- **P3. Logs live in `~/.local/share/breezy/logs/breezy-trade-202610*.log`.**
  - There are 9 boot logs for 10-01..10-05. Names (UTC): 10-01 `151202`, `160158`, `165011`; 10-02 `165039`, `200526`, `205521`; 10-03 `165045`; 10-04 `165012`; 10-05 `165040`.
  - Sizes run up to 1.43 GB (10-03). Streaming is required.
  - Codex counted 32 Takes, 32 OrderInitialized and 25 OrderFilled (89 bridge events). 7 Takes are IOC misses.
  - `NBM_NBP_PUBLISHED` lines exist in all 5 daily boot logs (Codex: `…20261001T151202Z.log:388`, `…1002T165039Z.log:706`, `…1003T165045Z.log:786`, `…1004T165012Z.log:691`, `…1005T165040Z.log:689`).
- **P4. The ladder partition is NOT recoverable from same-`now_ns` lines.**
  - Each rung is evaluated at its own `now_ns`, and the log is on-change (`strategy.py:585-625`).
  - The partition is the union of `rung_id`s per (station, climate_day) across all logs, plus `instrument_facts.bucket_facts_from_instrument_id` (`instrument_facts.py:72`).
  - `read_log_events` keeps only bridge events and drops Refuse lines. The partition union needs its own streaming reader that includes Refuse lines.
  - An incomplete union gives `PARTITION_INCOMPLETE`.
- **P5. The fill → Take join is a three-hop chain.**
  - fill → OrderFilled → OrderInitialized by client id, then init → Take by instrument and time window.
  - `decision_link.py`: `read_log_events` `:161`, `bridge_decision` `:202`, `bridge_report` `:250`.
  - The `BackfillRefused` raise is at `:213-214`. **The `BridgeUnmatched("no_trade_id")` return is at `:216` (CHANGED, was `:215`).** It fires when `fill.trade_id` is `None`.
  - `epoch_class` comes from `epoch.py:98` `fill_epoch_class(fill, reader)`. An absent epoch file with no OrderLink in C1 gives PRE_EPOCH (`epoch.py:7`, `:91`).
  - `recalibration` feeds only `artefact_p_raw` (`probability.py:77`, `raw_yes` at `decision_link.py:243`). TE-2 does not use `p_raw`. Pass the artefact's recalibration token, or `None`.
  - Codex verified: attribution 25 attributed / 0 ambiguous / 0 missing, and all 25 fills are PRE_EPOCH.
  - `fill_source.py:58` `read_durable_fills` opens `mode=ro` and returns a `FillRead` (`fields: fills, n_keys, n_undecodable`). `require_clean` is at `:49`.
- **P6. Counts from the fill store's instrument ids (outcome-free; re-run by S0-A).**
  - The store `~/.local/share/breezy/state/exec_polymarket_us.sqlite` was read read-only through `read_durable_fills`. Only instrument ids were used.
  - Oct FQ: 25 fills on 25 distinct instruments, all YES (no `^no`), 6 open-ended bands (`lt`/`gte`), `n_undecodable` 0.
  - **14 station-days.** LAX 10-02..10-06 (5), MDW 10-02, 10-04, 10-05, 10-06 (4), MIA 10-03, 10-05 (2), SFO 10-03, 10-04, 10-06 (3). Fills per station: LAX 8, MDW 8, MIA 4, SFO 5.
  - **7 station-event clusters.** LAX is one cluster. MDW has two (10-02; 10-04..06). MIA has two (10-03; 10-05; a 10-04 gap splits them). SFO has two (10-03..04; 10-06). With the 10-06 station-days excluded there are **6 clusters**.
  - MIA 10-03 and MIA 10-05 each hold 2 distinct rungs, so one loss sibling sits on each winning day.
  - Open-band semantics: `slug_closed_interval` (`symbology.py:483-500`) gives `lt B` → (None, B−1), `gte A` → (A, None), `gteAltB` → [A, B] inclusive.
- **P7. Deployed-commit pin, per boot by REFLOG (CHANGED; replaces r3's committer-time rule).**
  - **Identity source.** The boot logs carry `manifest_sha256=8e1217fd…` and `calibration_sha256=9c0b6d6e…` but no commit sha. The EPOCH ledger has no rows for 10-01..10-05 (`trade.py:1002-1012`, `:1150`). Each boot is therefore pinned to the commit the deployed branch (`feat/data-capture-and-risk`; HEAD reflog fallback) pointed to at boot time.
  - **Committed snapshot.** `docs/evidence/te2/REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt` holds the HEAD reflog (`.git/logs/HEAD`) and the branch reflog, identity columns stripped. Reflogs expire, so the resolver reads this file, never the live reflog. Its sha256 goes into `TE2_PINS.json`. The branch and HEAD reflogs agree for all nine boots.
  - **Committer time is never the selector.** Example: `4ac87414` has committer time 10-04T16:28:33Z but reached the branch through the 10-04T17:11:31Z fast-forward to `2be63d85`. The 10-04 boot (16:50:12Z) therefore does NOT carry it. Only the 10-05 boot does. (This corrects r3 P7.)
  - **`git log` over the widened path set.** The set is `src/breezy/strategy/forecast_quantile_ladder/` (includes `artefact_bounds.py` and `strategy.py`), `src/breezy/strategy/ladder_ev/` (whole package), `src/breezy/normalize/climate_day.py`, `src/breezy/ingest/nbm_quantile_actor.py`, and `deploy/families/`. The range is `1d7ea1016d7c..4ba7f10cd1f6`. It is NOT empty: 21 commits, so the label is `PIN=INFERRED`.
    - **Pre-boot-1 (15 commits).** These are the go-live set `5fc82050`, `dfa75525`, `7cbe6523`, `749316c5`, `416c2b53`, `9b14017c`, `3534c8ac`, `d8f19493`, `197d063d`, `60caaee3`, `59c4b1cd`, `10a5991a`, `ad76d2f2`, `fdff6855` and `60290e9d`. They are in-tree for every boot.
    - **`20aa5ea5` and `99067d4a`**, both 10-01 (15:30Z, 15:37Z), reached the branch by the 16:01:36Z fast-forward. `20aa5ea5` touched `forecast_quantile_ladder/strategy.py` and `current_rung_hold/composition.py` (outside the set; codex F1 correction) plus one test. `99067d4a` touched `strategy.py` only. Neither is on the `decision.evaluate` path.
    - **`f2e91fe4`** (`ladder_ev/__init__.py`), **`062dad8f`** (`capture_adapter.py`, `plugin.py`) and **`232d06bc`** (`capture_adapter.py`) are all in-tree from the 10-04 boot.
    - **`4ac87414`** (`normalize/climate_day.py`, `ladder_ev/forecast_state.py`, `ladder_ev/forecast_subscriber.py`) is in-tree from the 10-05 boot only.
    - After the last fill boot, so not in force for any fill: `cebaab49` (10-06T01:42:30Z, manifest adds `terminal_climate_day`; the HEAD manifest sha256 is `324c01f8…` and differs from the logged `8e1217fd…`) and the 10-06 `loss_stop_probe` commits. Corroboration therefore uses the blob AT the pinned commit, never HEAD.
  - **Per-boot pin table** (resolved from the snapshot; the script reproduces it and a mismatch is a STOP):

| # | Boot log (UTC) | Last reflog entry ≤ boot | Pinned commit | Widened-path state |
|---|---|---|---|---|
| 1 | 10-01 151202 | 10-01T13:39:52 | `60290e9ddd29` | baseline (go-live set) |
| 2 | 10-01 160158 | 10-01T16:01:36 (22 s before) | `99067d4a9e7a` | + `20aa5ea5`, `99067d4a` (strategy.py); NEAR-BOUNDARY |
| 3 | 10-01 165011 | 10-01T16:01:36 | `99067d4a9e7a` | same as 2 |
| 4 | 10-02 165039 | 10-02T16:00:52 | `7dfd1af114c1` | no widened-path change vs 3 |
| 5 | 10-02 200526 | 10-02T20:05:01 (25 s before) | `6e99a7ae2dbe` | none; NEAR-BOUNDARY |
| 6 | 10-02 205521 | 10-02T20:54:53 (28 s before) | `3eb4a1085dbf` | none; NEAR-BOUNDARY |
| 7 | 10-03 165045 | 10-03T15:01:45 | `f45f5a6558cd` | none (last src merge `4b8347a6`, 10-02T22:25:46) |
| 8 | 10-04 165012 | 10-04T16:28:31 | `c893e13e603e` | + `f2e91fe4`, `062dad8f`, `232d06bc`; NOT `4ac87414` |
| 9 | 10-05 165040 | 10-04T22:35:21 (no entry until 10-06T00:55:18) | `4ba7f10cd1f6` | + `4ac87414` (via fast-forward `2be63d85`) |

  - **Corroboration.** The manifest and artefact blob sha256 AT the pinned commit must equal the logged values. Verified today at `60290e9d`, `c893e13e` and `4ba7f10c`: manifest `8e1217fd…`, artefact `9c0b6d6e…`. The script checks all nine. The manifest at `ad76d2f2` was `f33a0f63…`, so `ad76d2f2` is not a pin.
  - **Tree-equivalence and near-boundary rule.** For each boot the resolver also records the `git rev-parse <commit>:<path>` tree shas of the widened set. Boots with identical tree shas are equivalent. For a NEAR-BOUNDARY boot (reflog entry < 120 s before boot) the resolver compares the widened-path tree shas of the pinned commit and its reflog predecessor. If they differ, the boot is UNTESTABLE unless p̂ reproduces under the pinned commit AND the predecessor. Boots 5 and 6 are expected to be equal. Boot 2 is expected to DIFFER (`strategy.py` changed between `60290e9d` and `99067d4a`), so boot 2 requires p̂ to reproduce under both commits or its fills are UNTESTABLE (r3.1 arch R1).
  - Residual risk, disclosed: the node imports the working tree at boot, so uncommitted edits cannot be excluded, and the reflog is the primary tree's. This is why the label is INFERRED. The near-boundary check looks only at reflog entries BEFORE each boot; an entry shortly after a boot (nearest: 21 min after boot 8) could be picked up by a lazy import, which is disclosed, not tested (r3.1 arch R2).
- **P8. The FQ artefact is a validate-stage candidate.** Manifest `pm_us_crh_fq_v1.json`, sha256 **`8e1217fd…`**. Artefact sha256 **`9c0b6d6e…23a5`**.
  - `NBP_S2_VALIDATE_RESULT_2026-09-30.md`: G2.0 (n=11604) and G2.1 (n=4335) are the calibration baseline. `month_10` mean residual is −0.20 °F, n=369, p=0.31 (`:264-269`). v5.0 parameters come from the 05-04..06-30 fit slice.
  - LOC_ARTEFACT is "v5.0 May–June parameter extrapolation to October". TE-2 on 7 clusters is weaker evidence than G2.1 and says so.
- **P9. Holdout.** C4.1 items 1, 2 and 4 of `RULING_holdout_freeze_and_forward_window_2026-10-03.md` freeze the holdout at [2026-07-01, 2026-10-02). Every FQ climate day is ≥ 10-02, so none is a holdout day. `nbp_calibration.py:273` `DEFAULT_SPLITS` still lacks the end date, so the script must never touch `open_holdout`. No new ruling is filed.
- **P10. The SL-13p parity harness refuses October days** (`nbp_shadow_parity_pure.py:98-132`, `PostFreezeTapeRefusedError`). Recompute with production `evaluate` plus injected inputs (S0-D).
- **P11. Which vector the strategy sees.** `nbm_quantile_actor.py:210-218` keeps the nearest-valid-start (D+1) window per station and variable. `available_at_ns = cycle_runtime_ns + measured_lag` (`:221-233`). Backfill availability comes from Last-Modified (`nbp_derived_store.py:142`). The node log is the visibility source. The NBP TXN window length is UNVERIFIED (`NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md:42-53`).
- **P12. Truth path.**
  - Truth is the **catalog** read through `NwsCliFinal` (`settlement_source.py:41-51`, via `persistence/catalog.py:637` `read_climate_day_including_corrections`), graded by `score_trial` (`trial_scorer.py:167`).
  - `NwsCliFinal.record` returns the whole `NwsClimateDay` (`domain/nws_climate_day.py:117`), including `tmax_f`. The protocol is `SettlementSource.record(station, climate_day)` (`settlement_source.py:37-38`). Plan: a clipping wrapper and a `tmax_f`-free projection for Phase A.
  - `fq-truth/truth_cli_finals.csv` and `coverage.json` describe a different store and are NOT the coverage check.
  - Catalog coverage of 10-02..10-06 for the four stations is NOT verified here; S0-F checks it through a projection. The loader hard-clips at `climate_day <= 2026-10-06`.
- **P13. Cycle and visibility source.** `poll_ledger.jsonl` starts at the 10-06 01Z cycle, so it covers no take cycle. The node logs carry `NBM_NBP_PUBLISHED cycle_ns=%d …` (`nbm_quantile_actor.py:546`, once per cycle). Its log timestamp is the visibility time. `derived/nbp` stops at 09-29 and `derived/nbp5` at month 06, so October vectors are re-fetched (S0-D).
- **P14. Route-back policy.** `RULING_FQ-v2-NO-TRADE_2026-10-08.md:44-50`: T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (a new US source, F13). The F13 freeze review is ≥ 10-21 (`PROGRESS.md:104`).
- **P15. Lessons (repo-local, headers verified in `docs/core/LESSONS.md`).** L-1 `:8`, L-2 `:67`, L-12 `:620`, L-18 `:871`, L-40 `:1384`, L-42 `:1421`, L-52 `:1610`, L-55 `:1666`.
- **P16. Out-of-scope fills.**
  - The manifest's `terminal_climate_day` is an inclusive CLIMATE day (`family_barrier.py:83-90`, `row.climate_day > terminal`; manifest HEAD `:6` is `2026-10-05`).
  - **FIVE fills** sit on climate day 10-06, on 3 station-days: LAX 1, MDW 2, SFO 2 (verified from instrument ids in P6).
  - The terminal day was added after the fact (`cebaab49`, 10-06T01:42Z). The manifest the node loaded had no such key, so the five fills were in scope for the deployed node.
  - They were taken on 10-05 between 16:51Z and 19:31Z, after the 16:40Z halt, which FAILED and was redone on 10-06 (`HALT_POINT_2026-10-04.md`, `HALT_POINT_2026-10-06.md`). Log lines as cited by architecture r2: `…20261005T165040Z.log:706, 807, 869, 896, 235691`. S0-B re-checks them.
  - Consequence: K1b is a bookkeeping flag on these five fills. The incident is already fixed (`0fe98eb4` plus the orders-off drop-in). No new manifest row is filed.

**Not verified; Stage 0 checks these:** that S3 still serves the 10-01..10-05 cycles; that a second truth source exists; that venue-resolved outcomes are readable; the catalog coverage for the four stations (P12); that the node ran from the primary tree whose HEAD reflog is snapshotted.

## 2. Statistical design (frozen before Phase B)

**Units.**
- The station-day is the exact unit. Its rungs are mutually exclusive (L-40), so W_d ∈ {0,1} and P_d = min(1, Σ p̂_i over the bought rungs).
- P_d sums p̂ taken at different cycles and assumes marginal calibration. The report states this.
- **Cluster (binding).** A cluster is a station-event: consecutive climate days at one station. W_c = 1 if any station-day in the cluster won. Observed cluster count: 7 (6 in the 10-06 sensitivity). Climate-day clusters are a descriptive sensitivity only.

**P_c under correlation.**
- Binding P_c = max over the cluster's P_d, clamped to P_c ≤ 1 − 1e-9. This is a valid lower bound on P(win in cluster) under any dependence, and a smaller P_c makes the lower-tail p-value larger, so it is conservative.
- The independent value 1 − Π(1 − P_d) is the optimistic bound, used in power (below).
- Any reported p-value below 1e-12 is printed "< 1e-12", never 0.

**α allocation (overall ≤ 0.05 by Bonferroni across three families):**

| Family | Tests | α |
|---|---|---|
| Primary | T-WIN | 0.02 |
| Secondary, Holm via `nbp_calibration.holm_correction` (`:1670`) | T-LOC, T-SPREAD | 0.02 |
| Artefact | T-ART | 0.01 |

The leave-one-out T-WIN and T-EDGE sit outside every family.

**Tests.** All are exact, standard-library and conditional on take where noted. The Poisson-binomial recursion is checked against brute force.

- **T-WIN (primary, one-sided lower tail, cluster level).**
  - H0-M: W_c ~ Bernoulli(P_c), independent across clusters. W = Σ W_c. The p-value is the exact P(W ≤ w_obs). With zero wins it reduces to Π(1 − P_c).
  - Companion H0-K uses ask-implied probability net of θ·p·(1−p) fees, with the SAME max-over-cluster rule and clamp.
  - **Leave-one-out** (outside the α budget): drop the cluster with the largest P_c (ties go to the alphabetically first station), recompute w_obs on the remaining clusters, and test again. It can only block VARIANCE or add the "single-cluster-driven" label (no leave-one-out rejection while the full test rejects).
  - The station-day-level result is a reported sensitivity.
- **T-LOC (Holm), one null (CHANGED).**
  - **Two-sided.** No outcome-blind direction exists: the heat-bust prior is outcome knowledge.
  - **Null.** For each station-day, π_d = P(tmax > median | tmax ≠ median), computed from the model's own discrete pmf of that day's EARLIEST fill (the declared choice). Raw-median companions use the raw NBM pmf.
  - **Collapse to clusters (r3.2: INDICATIVE, not validated conservative).** Cluster statistic S_c = sign of the cluster-mean signed error (tmax − corrected median). The p-value uses the larger of the two-sided exact p-values under the all-π^min and all-π^max vectors, but the bound P(S_c=+) ∈ [min π_d, max π_d] is NOT proven for a mean over days with unequal pmfs (r3.1 domain C2). T-LOC is therefore labelled **indicative**: it is reported, but it can never alone produce MODEL_LIMITATION, FIXABLE or a SOURCE sub-label (see §2 verdict rule 2).
  - Zero-error clusters (ties) are dropped and n after drops is reported.
  - Labelled "conditional on take" (adverse selection, `decision.py:349-355`).
  - Companions: the same test on the raw NBM median, and the unfilled-Take contrast (7 IOC-missed Takes, descriptive). T-LOC alone never yields FIXABLE.
- **T-SPREAD (Holm), cluster level (CHANGED to per-fill pmf).**
  - **Per fill:** PIT of tmax under the pmf of THAT fill's decision cycle. A fill is a tail miss if mid-PIT is outside [0.05, 0.95]; its null tail probability is q_f from the same pmf.
  - **Per day:** q_d = min(1, Σ q_f over the day's fills) (union upper bound). A day is a tail day if any of its fills is a tail miss.
  - **Per cluster (r3.2 corrected):** A_c = 1 if any fill in the cluster is a tail miss, with null q_c = **min(1, Σ q_f over the cluster's fills)**. This is the union (Boole) UPPER bound on P(A_c = 1) under any dependence, which is what makes an UPPER-tail test conservative. r3.1's max-q was a lower bound, which is anti-conservative here (r3.1 domain C1). The day-level q_d likewise becomes min(1, Σ q_f over the day's fills). T-SPREAD's min attainable p and H1-S power are recomputed with this q.
  - X = Σ A_c is Poisson-binomial over clusters. One-sided (too many tail misses), "conditional on take". The station-day version is a sensitivity subject to the downgrade rule.
  - **SPREAD versus LOCATION attribution is NOT identified.** A location bias also inflates the tail count. A tail rejection is never attributed to spread alone.
- **T-ART (own α).** Exact paired sign test on d = |corrected error| − |raw error| per cluster, H1: corrected is worse (one-sided, null 0.5). Ties are dropped and n after drops is reported. A rejection means "v5.0 May–June parameters extrapolate badly to October".
- **T-EDGE: exploratory, outside every family.** Exact P(X ≥ k) for the count of losing fills with `edge_dist_f == 1`, through the inclusive interval. Confirmatory weight is zero.

**S0-I. Testability and power gate (outcome-blind, runs BEFORE the freeze).**
- **Testability uses the cluster count only** (CHANGED; "tie-free" removed) together with the pmf-based nulls.
- For each test it enumerates the outcomes (≤ 2^7) and computes the minimum attainable p under the test's own null vector.
- **T-WIN:** min attainable p is P(W = 0) under H0-M. TESTABLE iff ≤ 0.02. **T-ART:** TESTABLE iff min p ≤ 0.01; otherwise NOT-TESTABLE.
- **Holm members (T-LOC, T-SPREAD), CHANGED.**
  1. A member with min attainable p > 0.02 is NOT-TESTABLE. NOT-TESTABLE members are dropped BEFORE Holm, so k shrinks.
  2. Let k be the count of remaining members. The step-1 threshold is 0.02/k.
  3. A member with min p ≤ 0.02/k is **TESTABLE**. A member with 0.02/k < min p ≤ 0.02 is **TESTABLE-CONDITIONAL**: it can reject only at a later Holm step, after another member rejects.
  4. Apply the identical rule in the 6-cluster sensitivity.
- **Testability uses the same null vectors as the test** (r3.2): T-LOC testability is the min attainable p under the max-of-two (π^min, π^max) rule; T-SPREAD under the union-bound q_c. Uniform-0.5 values below are reference only (r3.1 domain C3).
- Reference values (uniform null 0.5): on 7 clusters a one-sided sign test has min p 0.0078 (T-ART reaches 0.01 only on 7 of 7 same sign) and a two-sided T-LOC has min p 0.0156, which is TESTABLE-CONDITIONAL when k = 2. On 6 clusters T-ART (0.0156) is NOT-TESTABLE.
- A NOT-TESTABLE or CONDITIONAL test is reported as such, never as "did not reject".
- **Phase B re-evaluation after ties (pre-declared rule).** After ties are dropped, recompute testability on n' clusters with the same rule. A test that drops to a weaker status is reported as such and, if NOT-TESTABLE or CONDITIONAL, cannot feed the VARIANCE clause. Shrinking Holm k after ties is acceptable: a member that cannot reject never affects validity; the predeclaration says so (r3.1 domain C4).
- **Power (CHANGED).** Computed at station-day and cluster level. The reject region is {W ≤ w*}, where w* is the largest w with P_H0(W ≤ w) ≤ 0.02, under the alternative H1-K (ask-implied probability).
  - Cluster power is the **minimum over {max-P_c, independent-union P_c}**.
  - **T-SPREAD power is reported**, against H1-S: each q_c doubled and capped at 1, pre-declared. T-LOC and T-ART power are not computed; their minimum attainable p is the disclosed substitute.
- **VARIANCE requires cluster-level power ≥ 0.8.**

**Verdict, deterministic, evaluated in this precedence:**
1. **FIXABLE_DEFECT.** Any fill carries K4, OR any **material** K1a. K1a is material only if it flips the take/no-take decision or |Δp̂| > 0.01. A deterministic recompute is not a counterfactual P&L. K3, K2, K1b, UNTESTABLE and CYCLE_AMBIGUOUS never produce FIXABLE. The statistical label below is still reported alongside it.
2. **MODEL_LIMITATION.** No material K1a or K4, and at least one Holm- or T-ART-valid rejection among {T-SPREAD, T-ART}; a T-LOC rejection (indicative) is reported alongside but never qualifies alone. Sub-label: ARTEFACT (T-ART), SOURCE (T-SPREAD rejects and T-ART does not; T-LOC may be cited as indicative support), or both.
3. **MODEL_MISCALIBRATED_UNATTRIBUTED.** T-WIN rejects, no qualifying secondary (T-SPREAD, T-ART) rejects (an indicative T-LOC rejection is ignored for this clause and in rule 4, and is reported as a note), no material K1a or K4. Qualifiers: "single-cluster-driven" (leave-one-out does not reject) and "secondaries NOT-TESTABLE".
4. **VARIANCE.** T-WIN fails to reject, T-WIN is TESTABLE with cluster power ≥ 0.8, the leave-one-out does not reject, at least one secondary is **unconditionally TESTABLE after ties** (CONDITIONAL, NOT-TESTABLE and the indicative T-LOC do not count), and no qualifying TESTABLE secondary (T-SPREAD, T-ART) rejects. The label carries **"weak" unless every unconditionally TESTABLE secondary has computed power ≥ 0.8**. A leave-one-out rejection with a full-sample non-rejection blocks VARIANCE and routes to INCONCLUSIVE with that reason. The report lists which tests were NOT-TESTABLE or CONDITIONAL.
5. **INCONCLUSIVE.** Everything else, with the reason stated.

Mixed results are a ranked list with share of loss, never one label.

**Downgrade rule.** If the station-day-level decision differs from the cluster-level decision for any test, the verdict is the cluster-level one and the report states the range. A decision that flips under the 10-06 exclusion sensitivity (6 clusters) is reported as "scope-sensitive" with both results. The verdict stays on the full 25 fills.

**Mandatory footer, pinned by a test, printed with every verdict:**
- "diagnostic, post-hoc, n = N station-days in C clusters, non-confirmatory"
- "This verdict is NOT permission to re-arm. Re-open routes are T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (new US source, F13), per RULING_FQ-v2-NO-TRADE_2026-10-08."
- "VARIANCE does not imply positive EV."

**Forbidden.** Counterfactual P&L such as "would have won with the 19Z cycle" (L-18); cycle comparisons are descriptive only. Any hand arithmetic: all numbers come from the script. Any edge-distance or band-membership computed other than through `bucket_facts_from_instrument_id`. Selecting a boot's commit by committer time.

## 3. Taxonomy (frozen in `TE2_PREDECLARATION.json`)

**Per-fill descriptors, computed and not judged:**
- `p_hat`, `p_lower`, `ask_proxy` (fill cost).
- `edge_dist_f`: integer °F distance from `tmax` to the nearest edge of the bought **inclusive** interval [lower_f, upper_f] from `bucket_facts_from_instrument_id`. It is 0 inside the interval. For `lt B` the interval is (None, B−1]; for `gte A` it is [A, None); an open side is never the nearest edge. For a `^no` leg the YES interval is used and the leg is stated.
- Mid-PIT of `tmax` under the decision-cycle corrected model CDF, and the signed standardised error z.
- Raw vs corrected median error, and the correction in °F.
- Cycle age at decision, the newest visible cycle at `now_ns`, the PIN label, boot number, pinned commit and the boot log of the fill.
- Rungs bought on the same station-day, `PARTITION_INCOMPLETE`, and whether any fill on the station-day won.

**Primary class, per fill, first match wins, order pinned by a test:**

| Class | Rule |
|---|---|
| WIN | The fill's inclusive interval contains tmax. The loss taxonomy does not apply. |
| SIBLING_WON (K10) | A losing fill whose station-day contains a winning fill. It is checked BEFORE BOUNDARY, TAIL, BAND_SELECTION and BODY_MISS. This is the expected cost of stacked exclusive rungs. |
| BOUNDARY (K5) | Losing fill, `edge_dist_f == 1`, PIT in [0.05, 0.95] |
| TAIL (K6) | Losing fill, PIT outside [0.05, 0.95]. Mutually exclusive with BOUNDARY by definition. |
| BAND_SELECTION (K7) | Losing fill on a station-day with 2 or more bought rungs, all of which lost; tmax in the model's central 80% (PIT in [0.10, 0.90]); and not BOUNDARY. Needs a complete partition, otherwise UNTESTABLE for that station-day. |
| BODY_MISS (K9) | Residual losing fill: body miss with `edge_dist_f >= 2` and none of the above. **Renamed from "VARIANCE (K9)" to avoid colliding with the VARIANCE verdict.** |

- K7 is applied per fill using that fill's own `edge_dist_f`, so one station-day can yield a BOUNDARY fill and a BAND_SELECTION fill. Class counts are per fill, and a separate station-day-level K7 count is reported.
- The BOUNDARY-versus-BAND_SELECTION overlap is real ([0.10, 0.90] sits inside [0.05, 0.95]), which is why the order is pinned. BOUNDARY and TAIL cannot overlap, which a separate test pins.
- Classes are K5, K6, K7, K9, K10 and the flags are K1–K4. There is no K8.
- TAIL attribution: LOCATION (indicative only) if T-LOC rejects, SPREAD only if T-SPREAD rejects, otherwise unattributed; spread vs location is not identified.

**Orthogonal flags (multi-label, counted separately, never in the primary share):**

| Flag | Meaning |
|---|---|
| K1a INPUT_DEFECT | S0-D reproduction miss that survives root cause, or `available_at > now_ns`, or `vector.climate_day != instrument climate day`. Feeds FIXABLE only if material (§2). |
| K1b SCOPE | Fill on climate day 10-06, beyond the (post-hoc) `terminal_climate_day` 10-05. Five fills on 3 station-days (P16). Bookkeeping only. |
| K2 STALE_CYCLE | The cycle in use is not the newest visible at `now_ns`, or its age exceeds a maximum pinned in the declaration. Descriptive. |
| K3 TRUTH_BASIS | The outcome flips when ASOS/METAR max replaces CLI tmax. Descriptive only and never fixable: CLI is the settlement truth. |
| K4 VENUE_SEMANTICS | Venue-resolved outcome differs from the slug-parsed outcome (`lt`/`gteLlt H`, edge inclusivity), on a WIN or a loss. Uses the `reconcile.py` settlement leg. |
| LOC_ARTEFACT | The corrected median error is larger than the raw error. Fires about half the time by chance. Inference comes only from T-ART. |
| LOC_SOURCE | Raw NBM median error alone is beyond ±1 sd. |
| FLANK_CHEAP | Ask < 0.10, consistent with M1's reliable-loser cells. |
| CYCLE_AMBIGUOUS | Reconstruction cannot decide the cycle in use. |
| UNTESTABLE | The bulletin is unavailable or reissued, no deployed commit can be identified or corroborated (P7), or the alternative-truth/venue source is absent. Never counted as zero evidence. |

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
  - **Pin rule (CHANGED), per boot, by reflog.**
    1. Read `REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt` (its sha256 must equal the value in `TE2_PINS.json`). Never read the live reflog. Never select by committer time.
    2. Assign each of the 9 boots the last reflog entry with timestamp ≤ the boot-log time (branch reflog first, HEAD reflog fallback). Reproduce the P7 table; a mismatch is a STOP.
    3. Corroborate: the manifest and artefact blob sha256 AT the pinned commit must equal the logged `manifest_sha256` and `calibration_sha256`. A fill whose boot fails corroboration is UNTESTABLE.
    4. Apply the near-boundary tree-equivalence rule of P7.
    5. If no commit can be identified, the fill is UNTESTABLE.
    6. The script reproduces the `git log` check over the widened path set and prints its result, so the label is data. A non-empty log gives `PIN=INFERRED`; an empty log in a future run gives `PIN=STABLE`.
  - **STOP if fewer than 23 of 25 p̂ match the logged value to 1e-9, counting UNTESTABLE as a non-match.**
  - **Inputs (all named):** the manifest and `ArtefactBoundsProvider` (`artefact_bounds.py`) from the pinned commit; `load_live_calibration(<manifest path>, <artefact sha>)`; a fresh `QuantileLadderLatch`; `cfg`, `fee_coefficient`, `slippage_floor_prob`, `latitude_deg`, `std_utc_offset_hours` as in `decision.py:221-241`; conventions from `scripts/analysis/fq_evaluate_shim.py`. `breezy.app` is never imported.
  - **Vector.** Rebuild with `ForecastQuantileState.push` (`src/breezy/strategy/ladder_ev/forecast_state.py:245`; the file has a second `push` at `:88` for the TXN class) and `value_at` (`:310`), applying the actor's D+1 `_nearest_per_station_variable` filter. Use the pinned commit's `forecast_state.py`, `climate_day.py` and `nbm_quantile_actor.py` semantics (the 10-05 boot carries `4ac87414`; earlier boots do not).
  - **Cycle and visibility** come from the node log `NBM_NBP_PUBLISHED cycle_ns=` lines. The poll-ledger sha check is N/A for 10-01..10-05.
  - **Fetch.** One coordinator step, run outside 16:30–17:10Z (`launch_window_guard`, `capture_schedule.py:36-51`):
    `BREEZY_LIVE=1 BREEZY_USER_AGENT=<monitored> .venv/bin/python scripts/analysis/nbp_backfill.py --start 2026-10-01 --end 2026-10-05 --output-dir <scratch> --request-budget <2 × planned items> --apply --report-json <scratch>/report.json`
    - Run `--dry-run` first. `build_plan` is date-major over cycles 13, 19 and 1 (about 15 items, at most 30 requests).
    - The backfill writes a parsed derived store carrying `raw_sha256`. Only the per-cycle `raw_sha256` and the small reconstructed-vector table are committed. Tests never touch the network.
  - **Classes.** A miss caused by an unavailable or reissued bulletin is UNTESTABLE. A cycle-selection mismatch is CYCLE_AMBIGUOUS. Only a miss that survives root cause as a code or data difference is K1a, with the delta recorded and the materiality rule applied.
  - **Positive control.** A perturbed vector must produce a mismatch.
- **S0-E. Import and holdout guard.**
  - The AST pin is an allowlist of modules and names. It forbids `ast.Attribute` and string access to `open_holdout` or any holdout path, and any path under an M1-v3 directory. It mirrors `test_nbp_shadow_parity_contract.py`.
  - `lint-imports` does not cover `scripts/` (`pyproject.toml:61-67`). The AST pin plus `test_execution_egress_firewall_guard` (scans `scripts/`, `:133`) are the enforcement.
  - `fill_source.py:21` and `decision_link.py:28` both import `breezy.adapters.polymarket_us.exec.client` transitively. WP0 confirms the exec-import pin (x1 and the set-equality rows in `test_execution_egress_firewall_guard.py`) checks DIRECT imports only. If the new `scripts/analysis/` modules trip it, the row is WIDENED in the same commit (L-12), never relaxed. The script never imports `exec.*` directly.
- **S0-F. Truth quality, scoped.**
  - Truth is the catalog via `NwsCliFinal`. Confirm the catalog holds 10-02..10-06 for LAX, MDW, MIA and SFO, and run the coverage and `catalog_disagreement == false` check on the catalog, not the CSV.
  - Wrap the source in a **clipping wrapper that implements the `SettlementSource` protocol** (`record(station, climate_day)`), returning `None` or refusing for `climate_day > 2026-10-06`.
  - Phase A receives a **projection** of the record without `tmax_f` (status, final, superseded, correction). A test record whose `tmax_f` raises on access must pass Phase A.
  - A flagged or superseded settlement day is `TRUTH_UNSETTLED`, with its exclusion count stated.
- **S0-G. Alternative sources.** Look for a METAR/ASOS series (`us_source_archive/metar-routine`, `asos-cache`, `settlement_alignment_study` loaders) and a venue-resolved outcome per instrument. If absent, K3 and K4 are UNTESTABLE.
- **S0-H. Freeze.**
  - Phase A emits the per-fill outcome-blind table: p̂, ask proxy, cycle age, newest-visible flag, rung geometry, boot and pinned commit, PIN label, P_d, P_c, π_d (T-LOC null), q_f/q_d/q_c (T-SPREAD) and clusters.
  - `TE2_PREDECLARATION.json` holds the taxonomy, thresholds, tests, α allocation, sidedness, tie handling, the T-LOC null and collapse rule, the T-SPREAD per-fill rule, the S0-I results (minimum attainable p, TESTABLE / CONDITIONAL / NOT-TESTABLE lists, Holm k, power and H1-S), the Phase B tie re-evaluation rule, verdict rules, footer text, consumer map, the cycle-age maximum, the P_c rule and clamp, the leave-one-out and sensitivity rules, the reflog snapshot sha256, the per-boot pin table, and the Phase A table sha256. It does NOT store its own sha.
  - **Enforcement.** Phase B refuses unless all of these hold:
    - (a) the sha256 of the **HEAD blob** of the script and core module equals values in `TE2_PINS.json`, AND `git status --porcelain` on the pinned paths is clean;
    - (b) the predeclaration file is committed and its commit is an ancestor of HEAD (`git merge-base --is-ancestor`).
  - The "result artefact committed in a later commit than the predeclaration" check is a **post-hoc verifier test over the committed artefacts**, not a Phase B gate. There is no commit-message sha.
  - **Re-freeze rule.** A script bugfix after the freeze requires a new predeclaration commit and a disclosed re-freeze, with no Phase B result consumed in between.
  - Disclosed contamination: the audit and triage showed the headline direction (low win rate, LAX heat bust, MIA wins). The freeze constrains classification and thresholds, not the prior.

**Phase B (after the freeze):**
- Reproduce the corrected audit: 25 FQ fills, 2 wins, net −2.17 (cost + fee − payout, ±0.005); 34 fills / 4 wins / −2.63 total; Sep 9 / 2 / −0.46; wins MIA 10-03 `gte86lt87` (tmax 87) and MIA 10-05 `gte89lt90` (tmax 90). A mismatch is a STOP. Outcomes key on the INSTRUMENT climate day, not the order date.
- Join truth through the clipping wrapper, `NwsCliFinal` and `score_trial`. Re-evaluate testability on n' after ties (S0-I).

## 5. Work packages

All work is native-first. Reuse the cited modules, `score_trial`, `holm_correction` and `bucket_facts_from_instrument_id`.
- `combine_station_day` (`current_rung_hold_v2.py:296-330`) is **not used**: it takes `StratumRow`, builds break-even probabilities, and raises `StationDayAdmissionRefusal` when Σq > 1. P_d = min(1, Σ p̂) is the correct rule.
- Statistics use the standard library only.

**Layout (each file under 400 lines; 800 is a hard stop):**
- `scripts/analysis/fq_v1_loss_taxonomy.py`: CLI with Phase A and Phase B modes.
- `scripts/analysis/fq_loss_taxonomy_core.py`: pure, no I/O. Descriptors, classifier, Poisson-binomial, tests, verdict, footer.
- `scripts/analysis/fq_loss_taxonomy_inputs.py`: I/O wrappers over the reused modules, the clipping wrapper, the streaming reader, the Refuse-including partition-union reader and the reflog pin resolver.
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
| 7 | `t_win_leave_one_out_drops_max_P_c_cluster_recomputes_w_obs_when_a_win_cluster_drops_and_ties_go_to_first_station` |
| 8 | `h0_k_uses_max_over_cluster_and_clamp` |
| 9 | `edge_dist_inclusive_via_bucket_facts_upper_edge_inclusive_lt_gte_and_no_leg` (fixtures `gte86lt87` tmax 87 = inside, 88 = distance 1; `lt B`; `gte A`; `^no`; single-token `ltB`/`gteA`) |
| 10 | `pit_midpoint_for_integer_outcome_from_pmf` |
| 11 | `classifier_boundary_precedes_band_selection_on_overlap` |
| 12 | `boundary_and_tail_are_mutually_exclusive` |
| 13 | `win_class_then_sibling_won_precede_all_other_classes_and_taxonomy_applies_to_losers_only` (pins SIBLING_WON-first ordering; BODY_MISS is last) |
| 14 | `k7_per_fill_rule_when_edge_dist_differs_within_a_station_day` |
| 15 | `partition_incomplete_marks_k7_untestable` |
| 16 | `t_spread_null_is_per_fill_decision_cycle_pmf_not_binomial_0_10` |
| 17 | `t_spread_cluster_null_is_union_upper_bound_min_1_sum_q_and_any_fill_tail_miss_and_is_conservative_vs_bruteforce` |
| 18 | `sign_tests_drop_zeros_and_report_n_after_drops` |
| 19 | `min_attainable_p_marks_not_testable_never_did_not_reject` (7 clusters testable, 6 NOT-TESTABLE for T-ART) |
| 20 | `t_loc_is_two_sided_pmf_null_and_t_art_one_sided` |
| 21 | `t_loc_collapse_uses_min_max_pi_and_reports_the_larger_p` |
| 22 | `cluster_power_is_min_over_max_Pc_and_independent_union_and_reports_t_spread_power` |
| 23 | `verdict_variance_requires_power_0_8_unconditionally_testable_secondary_and_weak_label` |
| 24 | `verdict_miscalibrated_unattributed_branch_and_qualifiers` |
| 25 | `verdict_inconclusive_branch_states_reason_incl_loo_only_rejection` |
| 26 | `verdict_fixable_positive_path_for_k4_and_for_material_k1a` |
| 27 | `immaterial_k1a_below_0_01_without_decision_flip_is_not_fixable` |
| 28 | `t_loc_alone_k3_and_k1b_never_yield_fixable` |
| 29 | `model_limitation_sublabels_artefact_source_both_and_t_loc_alone_never_qualifies_model_limitation_or_source` |
| 30 | `downgrade_rule_cluster_level_wins_and_scope_sensitive_label` |
| 31 | `footer_is_present_and_names_t1_t2_t3_not_permission_to_rearm` |
| 32 | `holm_drops_not_testable_members_first_k_shrinks_step1_alpha_over_k_and_testable_conditional_status_incl_6_cluster_sensitivity` (T-EDGE excluded; also pins that S0-I testability uses each test's own null vectors: T-LOC max-of-two π, T-SPREAD union q_c) |
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
| 44 | `pin_resolver_reads_reflog_snapshot_file_not_live_reflog_and_never_committer_time` (fixtures: a **rebased commit whose committer time precedes its fast-forward reflog time** must NOT be pinned to the earlier boot; the 9-boot table; near-boundary tree-equivalence; blob sha at the commit, never HEAD; STABLE, INFERRED, UNTESTABLE; STOP below 23 counting UNTESTABLE) |
| 45 | `streaming_reader_is_a_lazy_generator_or_tracemalloc_bounded_and_keeps_a_take_split_across_a_prefilter_boundary` |
| 46 | `partition_union_reader_includes_refuse_lines` |
| 47 | `k1b_flags_five_fills_on_three_station_days_and_sensitivity_excludes_them` |
| 48 | `alt_truth_unavailable_marks_untestable_not_zero` |
| 49 | `reproduces_audit_25_fills_2_wins_minus_2_17` (Phase B; fixture written through the real writer path, `read_durable_fills` plus `require_clean`, L-42; includes the upper-edge-inclusive MIA 10-03 and 10-05 wins) |
| 50 | `testability_reevaluated_after_ties_and_downgraded_test_cannot_feed_variance` |
| 51 | `body_miss_class_name_replaces_k9_variance_and_never_collides_with_verdict_label` |

Per L-55, run the production default path once where a fake dependency is injected.

**WP1. Phase A (outcome-blind).**
- Implement the readers, the join, the partition union, the reflog pin resolver and the reconstruction. Run S0-A, B, C, D, F (projection only), G and I, and emit the Phase A table.
- Streaming is a line-wise prefilter on `'kind': 'Take'` plus the Refuse-including partition-union pass. There is no keyed second pass on `now_ns` (P4).
- The coordinator runs it under `systemd-run --user -p MemoryMax=4G -p LimitNOFILE=524288`, with `--basetemp` under `~/.cache` (not `/tmp`). One heavy job at a time.
- Interpreter: `/home/jon/breezy/.venv/bin/python`. No `uv`, no `pip`. In a worktree set `PYTHONPATH=<wt>/src`. No `git stash`.

**WP2. Freeze.**
- The coordinator commits `TE2_PINS.json` (HEAD-blob sha256 of the script and core module, plus the reflog snapshot sha256) and `TE2_PREDECLARATION.json`.
- The review checks that no Phase B quantity leaked in. Reviewers: prediction-market-reviewer (statistics, cluster rule, NOT-TESTABLE and Holm logic), python-reviewer (code), and an adversarial Codex review. The reviewer is not the TE-1 or script author.

**WP3. Phase B and classification.**
- Run the Phase B reproduction, the truth join, the alternative sources, the classification, the tests and the verdict. Write JSON and a generated `.md`.
- Add a TE-1 ledger cross-check block, or print "TE-1 cross-check pending". Do not build a second scorer.

**WP4. Findings, consumers and delivery.** See §7.

**Outputs (committed):**
- `docs/evidence/te2/TE2_PINS.json` and `docs/evidence/te2/TE2_PREDECLARATION.json`.
- `docs/evidence/te2/fq_v1_loss_taxonomy_<date>.json` and generated `.md`, recording the script, pin and snapshot shas.
- Per-cycle `raw_sha256` values and the small reconstructed-vector table.

## 6. Dependencies and gate

- **Hard.** The node logs and the durable fill store; the committed reflog snapshot; S3 serving of the 10-01..10-05 cycles (otherwise those fills are UNTESTABLE for S0-D, which can leave fewer than 23 matched and trigger the STOP); `nbp_backfill`; and the catalog holding the four stations' 10-02..10-06 CLI records.
- **Soft.** The TE-1 ledger (cross-check only), a second truth series and a venue-resolved outcome source.
- **Sequencing.** WP0 → WP1 → WP2 (hard stage boundary) → WP3 → WP4.
- **Routing.** Grok, then Codex, then Claude tdd-guide for implementation. The coordinator runs `scripts/ci/run_tests_no_egress.sh` and reads the exit code before any push. Briefs restate the invariants: Nautilus immutable, `allow_short=False`, NO-SEND firewall, no operator caps, no live enablement, format only your own files.
- **Focused gate must include:** the new AST-pin test and `test_execution_egress_firewall_guard`; the exec-import pin and the citation map; all `test_autonomy_*` tests; `lint-imports` from the repo root, which must print "N kept, 0 broken" (and it does not cover `scripts/`).

## 7. Consumers and delivery (each finding maps to exactly one)

The coordinator turns each into a row in `docs/core/PROGRESS.md`.

| Finding | Consumer |
|---|---|
| K1a (material) | Bug row against the named module. Blocks any FQ re-open (T2). |
| K1b | **Closed — no action, incident already fixed (`0fe98eb4` + orders-off drop-in; HALT_POINT_2026-10-06).** No new manifest row. Never `assert_family_only` on the batch. |
| K2 | Descriptive only. A feed-latency input to the F13 source review. |
| K3 | Descriptive only. If a route is wanted, the F13 US-source list. Never CF-2 or CF-7. |
| K4 | Venue-semantics row. Settlement alignment is fixed before any family trades this venue. |
| BOUNDARY (K5) | T2 input only. T-EDGE is exploratory. If it does not reject, close "no action: within model-expected near-misses". |
| SIBLING_WON (K10) | T2 take-rule input (rung stacking). |
| TAIL (K6) with LOC_SOURCE or SPREAD | A named PROGRESS row, "F13 r-next / T2-T3 candidate input". The F13 ≥ 10-21 freeze takes only `source_lags_ns` and `source_breaks`, so this cannot enter that freeze. The 25 fills are forward data under C4.1 and serve as a descriptive baseline, never a tuning set. |
| TAIL (K6) with LOC_ARTEFACT (T-ART) | The same PROGRESS row family, as a calibration note against `nbp_calibration`: v5.0 May–June extrapolation to October. |
| BAND_SELECTION (K7) | T2 take-rule input (minimum-ask filter, consistent with M1). |
| BODY_MISS (K9) / VARIANCE verdict | Closed "no action" with the test, p-value, power, the "weak" qualifier if present, and the T1–T3 footer. |
| MODEL_MISCALIBRATED_UNATTRIBUTED | F13 r-next / T3 input: the model is miscalibrated in a way these data cannot attribute. The next evidence is T1 (12-07) or a forward screen. |
| NOT-TESTABLE / TESTABLE-CONDITIONAL | Feeds INCONCLUSIVE route 1 below: the number of forward days the minimum-attainable-p calculation says is required. |
| INCONCLUSIVE | Two named routes: (1) a forward-only evidence plan sized by what the power calculation says is needed, handed to T2; (2) closed "no action" until T1 (12-07) if that number is infeasible. The report states which. |

**Delivery.**
- Soft target: the result artefact is committed by 2026-10-20. The F13 freeze review (≥ 10-21) does not depend on it (see the TAIL row).
- If the S3 or fetch STOPs slip it, the report states the slip explicitly and cites TE-2 as "pending".

## 8. Risks

1. **Overfit on a small sample.** Mitigated by the outcome-blind Phase A, the pinned freeze, exact tests, the conservative P_c and the α split.
2. **Selection bias.** T-LOC and T-SPREAD are conditional on take. Mitigated by labelling, the unfilled-Take contrast, and T-LOC alone never yielding FIXABLE.
3. **Cluster-count power.** With 7 (or 6) clusters, several tests cannot reach α, or reach it only at a later Holm step. Mitigated by S0-I status reporting before the freeze, post-tie re-evaluation, and the rule that non-testable never reads as "no effect".
4. **Single-cluster T-WIN.** Mitigated by the pre-declared leave-one-out (outside α) and the "single-cluster-driven" qualifier.
5. **Deployed-code identity.** The pin is inferred from a committed reflog snapshot; the working tree and a different checkout cannot be excluded. Mitigated by reflog-not-committer-time selection, blob-sha corroboration, near-boundary tree-equivalence, UNTESTABLE for unidentified fills, and the 23-of-25 STOP counting UNTESTABLE as a miss.
6. **Cycle retention or reissue.** Handled as UNTESTABLE or CYCLE_AMBIGUOUS, never silently skipped and never K1.
7. **Ask proxy.** The fill cost stands in for the decision-time ask (zero-slippage audit). State it in the report.
8. **Unverified TXN window.** Do not assert window alignment as a cause.
9. **Truth basis.** CLI is the settlement truth. The venue-side settlement was not cross-checked, so K4 may stay UNTESTABLE.
10. **Band-semantics regression.** Mitigated by routing every band through `bucket_facts_from_instrument_id` and by tests #9 and #49.
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

- [ ] All 25 fills carry a primary class (WIN, SIBLING_WON, BOUNDARY, TAIL, BAND_SELECTION or BODY_MISS) and flags, or an explicit UNTESTABLE, TRUTH_UNSETTLED or UNCLASSIFIED-STOP reason.
- [ ] One verdict with tests, p-values, TESTABLE / CONDITIONAL / NOT-TESTABLE list, power (station-day and cluster level, T-SPREAD included), the leave-one-out and the 10-06 sensitivity, and the mandatory footer. A ranked list when mixed.
- [ ] Every finding maps to one named consumer, including INCONCLUSIVE and NOT-TESTABLE, with a soft delivery date or a stated slip.
- [ ] The result reproduces from the committed script and the committed reflog snapshot. The post-hoc verifier test passes (artefact commit after the predeclaration, HEAD-blob pins, ancestor check).
- [ ] The full gate passes with a read exit code, and no re-arm took place.

**Key paths for the implementer:**
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/decision.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/artefact_bounds.py`
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/strategy.py`
- `/home/jon/breezy/src/breezy/strategy/ladder_ev/forecast_state.py`
- `/home/jon/breezy/src/breezy/normalize/climate_day.py`
- `/home/jon/breezy/src/breezy/ingest/nbm_quantile_actor.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/fill_source.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/decision_link.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/epoch.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/instrument_facts.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/settlement_source.py`
- `/home/jon/breezy/src/breezy/settlement/trial_scorer.py`
- `/home/jon/breezy/src/breezy/settlement/family_barrier.py`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/scripts/analysis/nbp_backfill.py`
- `/home/jon/breezy/scripts/analysis/fq_evaluate_shim.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/docs/evidence/te2/REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt`
- `/home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- `/home/jon/breezy/docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md`
- `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`
- `/home/jon/.local/share/breezy/logs/breezy-trade-202610*.log`

## Changes from r3

| Source item | Disposition in r3.1 |
|---|---|
| Merge 1 / arch C1 BLOCKER / python R3-3 (pin by reflog) | Adopted. P7 and S0-D pin each boot to the reflog entry at boot time, read from the committed snapshot (sha in `TE2_PINS.json`), never from committer time and never from the live reflog. The 9-boot table is resolved from the snapshot and verified here. `4ac87414` is corrected: committer time 16:28:33Z, but it arrived by the 17:11:31Z fast-forward to `2be63d85`, so only the 10-05 boot carries it. Blob-sha corroboration is unchanged and verified at `60290e9d`, `c893e13e` and `4ba7f10c` (manifest `8e1217fd…`, artefact `9c0b6d6e…`). Test #44 gains the rebased-commit fixture, the snapshot-file read and the 9-boot table. |
| Merge 1 / codex F1 | `20aa5ea5` touched-file list corrected: `strategy.py`, `current_rung_hold/composition.py` and one test. |
| My addition (near-boundary boots) | Boots 2, 5 and 6 sit 22, 25 and 28 s after a reflog entry. The resolver compares widened-path tree shas of the pinned commit and its reflog predecessor and marks the boot UNTESTABLE if they differ and p̂ does not reproduce under both. Expected equal. |
| Merge 2 / python R3-1 (widen path set) | Adopted. P7 re-run with `git log 1d7ea1016d7c..4ba7f10cd1f6` over `forecast_quantile_ladder/` (including `strategy.py`), `ladder_ev/` (whole package, so `f2e91fe4`), `normalize/climate_day.py`, `nbm_quantile_actor.py` and `deploy/families/`: 21 commits, NOT empty, PIN=INFERRED. Listed by boot. |
| Merge 3 / python R3-2, domain M3, arch C4 (Holm testability) | Adopted. A member is TESTABLE only if min p ≤ α/k. Otherwise TESTABLE-CONDITIONAL or NOT-TESTABLE. NOT-TESTABLE members are dropped before Holm, so k shrinks. The VARIANCE clause needs an unconditionally TESTABLE secondary. The rule is applied in the 6-cluster sensitivity and pinned in #32. |
| Merge 4 / domain M1 (ties) | S0-I uses the cluster count only ("tie-free" removed). Phase B re-evaluates testability on n' after ties with a pre-declared rule. A downgraded test cannot feed VARIANCE (new test #50). |
| Merge 5 / domain M2 (T-LOC null) | One pmf-based null π_d = P(tmax > median \| not tied), from the earliest fill's pmf. Cluster collapse by min and max π_d, reporting the larger p. Pinned in the predeclaration; test #21 updated. |
| Merge 6 / domain M4 (power) | Cluster power is the minimum over {max-P_c, independent-union P_c}. T-SPREAD power reported against H1-S. VARIANCE carries "weak" unless every unconditionally TESTABLE secondary has computed power ≥ 0.8. Test #22 and #23 updated. |
| Merge 7 / domain M5 (T-SPREAD per fill) | PIT and q use the pmf of each fill's decision cycle. q_d is the max over the day's fills. A_c = 1 if any fill in the cluster is a tail miss. Tests #16 and #17 updated. |
| Merge 8 / domain M6 (§0) | Expectation restated for w_obs = 2 of 7: INCONCLUSIVE from non-rejection is likelier. Leave-one-out recomputes w_obs when a win cluster drops, sits outside the α budget, and can only block VARIANCE or add "single-cluster-driven". Test #7 updated. |
| Merge 9 / domain M7 (naming and order) | Class K9 renamed BODY_MISS (new test #51). SIBLING_WON-first ordering is pinned in #13. Consumer row renamed. |
| Merge 10 / python R3-4, arch C3 | `BridgeUnmatched("no_trade_id")` cite corrected to `decision_link.py:216`. The K1b consumer is now "closed — no action, incident already fixed (`0fe98eb4` + orders-off drop-in; HALT_POINT_2026-10-06)". |
| Housekeeping | The r2→r3 changes table is dropped (it lives in the r3 file). "Not verified" now includes that the node ran from the primary tree whose HEAD reflog is snapshotted. `TE2_PINS.json` and the predeclaration carry the snapshot sha and the per-boot pin table. Risk 5 and the acceptance text are updated for the reflog. |

## Changes from r3.1 (coordinator pass r3.2)
| Source | Disposition |
|---|---|
| r3.1 domain C1 (HIGH) | T-SPREAD cluster and day null q = min(1, Σ q_f), the union upper bound, conservative for an upper-tail test. Test #17 renamed and checked against brute force. Min-p and H1-S power recomputed with it. |
| r3.1 domain C2 (HIGH) | T-LOC relabelled INDICATIVE. It can never alone produce MODEL_LIMITATION, FIXABLE or SOURCE, and does not count toward the VARIANCE TESTABLE-secondary clause. TAIL LOCATION attribution is indicative. |
| r3.1 domain C3 (MED) | Testability uses the same null vectors as each test. Uniform 0.5 values are reference only. |
| r3.1 domain C4 (LOW) | Predeclaration states that shrinking Holm k after ties does not affect validity. |
| r3.1 arch R1 (LOW) | Boot 2 expected to differ from its predecessor, so it needs p̂ reproduction under both commits. |
| r3.1 arch R2 (LOW) | Post-boot reflog entries disclosed as residual risk. |
| r3.1 arch R3 (LOW) | No change. S0-D re-prints the git log, and a mismatch is a STOP. |
| r3.2 confirm D1–D4 | Per-day q_d is the union bound (line 155 no longer contradicts). Rules 3 and 4 ignore an indicative T-LOC rejection and report it as a note. Tests #29 and #32 extended. Status header updated. |
