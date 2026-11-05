# GAP-1 SOURCE-RESOLUTION — plan r1

Status: r1 — for re-review by **architect** and **prediction-market-reviewer**. Written 2026-11-01. Nothing runs before both re-reviews pass, D1 is ruled and PREREG_GAP1 is frozen.

## Finding → resolution
| # | Sev | Resolution (evidence) |
|---|---|---|
| A-1 | HIGH | Accepted. S0 cites `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json` (`frozen_sha` 205fd542, stamp fb37ed30) and `docs/evidence/f13/c1_lag_evidence_2026-10-21.json` (sha 792ff2a8…, RULING_F13…:12, :38). Both files exist. No F13 pin is written, so nothing is re-frozen (PIN-R8b). S0 writes only `PREREG_GAP1`. |
| A-2 | HIGH | Accepted. Write-once was verified at `multisource_blend_skill.py:324-325` (`write_stage_a`). No `stage_a.json` exists under `~/.local/share/breezy`. J3 is F13's one Stage A/B look, and GAP-1 spends it. The F13 verdict (`outcomes` ACCEPT/NO_SKILL/…) and the GAP-1 ΔRES rule are both read from that single run. Neither is re-run or re-thresholded. Both go into K_cum (§5). |
| A-3 | HIGH | Accepted. **J1 is dropped.** The 09-30 result (`NBP_S2_VALIDATE_RESULT_2026-09-30.md:28-29`) is cited as a prior look. In-sample G2.3 FAILed (d_res 0.0038, :690). `G2.3_out_of_sample` is UNTESTED with n=0. Re-running a deterministic script on the same data is not a new look. §5 "Data" now uses the F13 fold rule, not the J1 split. |
| A-4 | HIGH | Accepted. Horizons are copied verbatim from the F13 `pins.anchors` (:89-93): **D-1 = 18:00Z** and **D0 = 10:00 LST**. D0_sensitivity (12:00 LST) is reported only. Standalone NBS-MOS at D0 is UNSCORABLE, because `ComparatorMatchedEvent` is D+1 only (`nbp_skill_study.py:1106-1110`). |
| P-1 | HIGH | Accepted, and it resolves A-7 (LOW). The G2.3 rule is adopted **verbatim**: CI lower > 0 AND point ≥ X = `G22_TARGET_DIFFERENCE_X` 0.0152 (`nbp_calibration.py:2239-2265`, `:314`). The only change is a multiplicity-adjusted α (P-4). r0's stricter "lower bound > X" is withdrawn. |
| P-2 | HIGH | Accepted. Every PASS cell gets a required report line: the ΔRES CI lower bound against the measured ask-minus-NBP gap 0.0228 (`P2_…:50-52`). Each PASS is labelled **"beats NBP"** or **"beats ask (indicative)"**. Only "beats ask" cells go to GAP-2/3 by default (§5). |
| P-3 | HIGH | Accepted, with a combined fix (the reviewers agree in substance). Every arm, including M0, is scored on **one** 3-rung ladder: `_forecast_centered_ladder(round(champion.percentiles.q50))`. This is the same centring J1 uses (`nbp_skill_study.py:1217-1218`), it is NBP-centred as P-3 asks, and it uses one centre rule as A-5 asks. UNC is reported per cell, and the reader refuses if UNC differs across arms. |
| P-4 | HIGH | Accepted. m = 6 cells (3 arms × 2 horizons). The rule is Bonferroni, which is Holm's first step and is conservative: the percentile CI at α = 0.05/6. The cells are nested and correlated, which is disclosed. Each cell counts separately in K_cum. |
| P-5 | HIGH | Accepted. The n ≥ 200 rule is replaced by `compute_n_min(sigma_d)` per cell (`nbp_calibration.py:330-347`), with sigma_d taken from the cell's own OOF paired Brier differences in the same run. If n < n_min, the cell is **UNDERPOWERED**, never KILL. `N_MIN_CEILING` 520 is the holdout ceiling: it is recorded and not applied. |
| A-5 / P-8 | MED | Accepted. The schema was verified: `arm_predictions.{mu, sigma, nu}` per arm (`multisource_blend_io.py:82-84`). The reader uses the Student-t with the row's `nu`. The centre rule is in D1 and in the PREREG. |
| A-6 | MED | Accepted. J2 measured 25m04s cold, 756 MB max RSS and a 4.8G cgroup peak, under MemoryMax=12G and RuntimeMaxSec=3000 (RULING_F13…:37-39). J2 now runs under those exact settings. J3 is unmeasured. |
| P-6 | MED | Accepted. A CRPS screen FAIL does not KILL any source. Without D1 no RES is tested, so GAP-1 cannot reach KILL. |
| P-7 | MED | Accepted. J1 is dropped. The only OOS rows are J3's fold-CV OOF rows. |
| A-8, A-9, P-9, P-10 | OK/LOW | No change needed. Two P-9 items are now resolved: the seed (`BOOTSTRAP_SEED` 20260929, `nbp_calibration.py:472`) and both F13 paths. |

## 1 Objective
Test whether LAMP, PFM, GFS-MOS or their blends have better resolution (Murphy RES) than calibrated NBP on rung binaries, scored out-of-fold on data before 2026-07-01. A winning trade needs probabilities that separate winners from losers better than the ask does. Measured so far: NBP RES 0.0059 against YES-ask RES 0.0287 (P2). If no source beats NBP, no forecast family downstream can win. GAP-1 is the first gate.

## 2 Preconditions and dependencies
- No dependency on GAP-2…6. GAP-2, 3 and 4 run only for a cell that PASSes here. GAP-5 and GAP-6 are independent.
- The F13 prereg is frozen. Its `frozen_sha` must be an ancestor of HEAD, which the runner enforces (`load_verified_prereg`, `:274-297`). Post-freeze follow-ups are merged (b20cb5ae, RULING_F13…:44-46).
- **D1 must be ruled, and if granted the S5 reader must be built and tested, before S3/S4 run.** Building it afterwards would mean designing an evaluator after seeing the look.
- Archive inventory as in r0. Raw NBM members are UNSCORABLE (none stored). `us-lamp-live` covers the tape only and is not used.

## 3 Scope
- **J2** `scripts/analysis/multisource_blend_features_build.py --prereg <F13_prereg_blend_v1.json> --nbp-root ~/.local/share/breezy/derived/nbp --us-source-root /mnt/storage/breezy/us_source_archive --mos-root ~/.local/share/breezy/archive --truth <settlement_truth.parquet> --start 2021-01-01 --end 2026-06-30 --out-features <run>/f.jsonl --out-lag-features <run>/fl.jsonl --report-json <run>/build.json --max-memory-gib 3.5`. The real `/mnt/storage` path is passed because the builder refuses a symlinked root.
- **J3** `scripts/analysis/multisource_blend_skill.py --prereg <same> --features <run>/f.jsonl --lag-features <run>/fl.jsonl --c1-evidence docs/evidence/f13/c1_lag_evidence_2026-10-21.json --out-dir <run>/j3 --max-memory-gib 3.5`. Outputs: `stage_a.json`, `result.json` and `oof_rows.jsonl`.
- **S5 reader (only with D1).** One read-only script, `scripts/analysis/gap1_oof_murphy.py`. It reuses the library functions `resolution_difference`, `cluster_bootstrap_draws`, `percentile_interval` and `compute_n_min`. It adds no model, fit, tape read or emission.
- **Cited, not re-run:** `NBP_S2_VALIDATE_RESULT_2026-09-30.md` (NBS-MOS prior look) and `P2_NBP_VS_ASK_MURPHY_2026-10-22.md`.
- **Not in scope:** J1/`nbp_skill_study` re-runs, any tape or catalog read, any refit on or after 07-01, the holdout, NYC, raw NBM, Kalshi, forward emission (GAP-2), the live and exec paths, and any edit to the F13 prereg or its pins.

## 4 Steps
Run one heavy job at a time, each under `systemd-run --user`, with a stall watch armed in the launch turn. Each run writes an immutable directory `~/.local/share/breezy/derived/gap1_source_resolution/<run_id>/`.

| # | Step | Inputs → output | Who | Time |
|---|---|---|---|---|
| S0 | Draft `docs/prereg/PREREG_GAP1_2026-11-01.json` (§5). It cites the F13 prereg and C1 evidence by sha and writes no F13 pins. Freeze it by commit sha. | → prereg | sub-agent drafts, coordinator freezes | 1 h |
| S1 | RED→GREEN tests (§6). Dry run of J2/J3/S5 on a fixture, which is not a look. | tests | tdd-guide | 1 h (+0.5 d for S5) |
| S2 | D1 ruled by the operator. If granted, S5 is built and reviewed here, before any look. | — | operator, tdd-guide, python-reviewer | 0.5 d |
| S3 | J2 with MemoryMax=12G, RuntimeMaxSec=3000, LimitNOFILE=524288 (the measured envelope) | archives → features + `build.json` | harness | ~25 min |
| S4 | J3, the **one look**: MemoryMax=12G with the internal `--max-memory-gib 3.5` guard. An OOM or timeout is recorded as "not run" and the cap may only be widened (L-12). | → `j3/` | harness | unmeasured |
| S5 | Reader over `j3/oof_rows.jsonl`, in the same look window | → `murphy.json` | harness | 0.5 h |
| S6 | Coordinator sidecar beside the machine-written outputs (L-75), plus a PROGRESS line | → `docs/evidence/GAP1_SOURCE_RESOLUTION_<date>.md` | coordinator | 0.5 h |

## 5 Pre-registered PASS / KILL (frozen at S0; one look = S4 + S5)
- **Cells (m = 6).** Arms M1 (+LAMP), M2 (+PFM) and M3 (+GFS MOS) from the F13 nested ladder (`fixed_by_plan.ladder`), each at horizons D-1 18:00Z and D0 10:00 LST.
  - Baseline: M0, the NBP champion.
  - At D0, ΔRES of M0prime against M0 is also reported, so that obs-so-far credit is not attributed to the new source.
- **Data.** OOF rows only, from 2021-01-01 to 2026-06-30. Folds follow F13 `fold_rule` (28-day blocks within each version and source-break segment, embargo 3 d). No tuning on test folds.
- **Events.** For each OOF row, the 3-rung ladder centred on `round(champion.percentiles.q50)` is used for every arm. Arm p comes from the Student-t (mu, sigma, nu). M0 p comes from the champion spec using `champion_cdf_method` NORMAL. UNC must be equal across arms in a cell, or the reader refuses.
- **Metric.** ΔRES = RES_arm − RES_M0, binned with `RELIABILITY_BUCKET_EDGES`. The CI is a cluster bootstrap with B=2000 and seed 20260929. Both station-day and climate-day clusters are computed and the wider CI is used.
- **PASS (cell).** All three must hold:
  1. G2.3 verbatim at α = 0.05/6: CI lower > 0 AND point ≥ 0.0152.
  2. REL_arm ≤ REL_M0 on the same events. This is a pinned rule: the arm must be no worse calibrated than the champion.
  3. Station-days ≥ `compute_n_min(sigma_d)`, with sigma_d measured from the cell's own paired Brier differences.
- **Required labels.** Every PASS cell reports its lower bound against 0.0228. If the lower bound is above 0.0228 the label is "beats ask (indicative)", otherwise "beats NBP". The P2 gap was measured on venue rungs, so the comparison is across event sets and is labelled indicative.
- **Cell outcomes.**
  - PASS.
  - FAIL: clause 1 or 2 fails with n ≥ n_min.
  - UNDERPOWERED: n < n_min. This never counts as KILL.
- **Overall outcomes.**
  - **PASS:** at least one PASS cell. "Beats ask" cells go to GAP-2/3. "Beats NBP"-only cells go to the operator as a programme decision.
  - **KILL:** D1 was granted, every cell is FAIL, and no cell is UNDERPOWERED. On KILL: PROGRESS records "forecast-edge programme STOPPED at GAP-1", and GAP-2, 3 and 4 do not start.
  - **UNRESOLVED:** D1 refused, or any cell UNDERPOWERED with no PASS. This goes to the operator and is never a silent KILL.
  - A CRPS screen result, pass or fail, never decides KILL.
- **F13's own verdict.** It is read from the same `result.json` and reported as-is: ACCEPT, REFUSED_M0PRIME_WORSE, HELD_LEAK_AUDIT or NO_SKILL. It does not override the GAP-1 verdict.
- **K_cum.** Add 6 cells, F13's primary comparison (1), and the 09-30 G2 validate look (1) if it is not already seeded.

## 6 Tests and gate route (RED first)
- **S1:**
  - `test_gap1_prereg_frozen_blob_matches` (`check_frozen_blob`, `prereg_precommit_check.py:340`)
  - `test_gap1_prereg_cites_f13_prereg_and_c1_evidence_by_sha`
  - `test_gap1_j3_out_dir_refuses_existing_stage_a`
- **S5:**
  - `test_oof_murphy_identity_brier_reconstructs_1e12`
  - `test_oof_murphy_self_delta_is_zero`
  - `test_oof_murphy_uses_student_t_nu`
  - `test_oof_murphy_common_ladder_equal_unc_across_arms`
  - `test_oof_murphy_bonferroni_alpha_is_0_05_over_6`
  - `test_oof_murphy_underpowered_not_kill`
  - `test_oof_murphy_refuses_header_digest_mismatch`
  - `test_oof_murphy_refuses_post_cutoff_rows`
  - `test_oof_murphy_no_network_no_catalog_import`
- **Gate:** `scripts/ci/run_tests_no_egress.sh` on the primary tree is the binding result. Read EXIT before any push. Basetemp goes inside the worktree. Briefs name the whole-tree guards: import pins, `lint-imports` run from the tree root, the citation map, the asdict scan, and `test_nbp_calibration_module_is_byte_unchanged`.

## 7 Pins, isolation, risks
- **Binding constraints:**
  - Nautilus Trader is immutable.
  - `allow_short` stays False.
  - No safety, settlement, contract, pin or NO-SEND test is weakened or deleted.
  - No operator cap is assigned.
  - Live enablement and the egress firewall are not touched.
  - Holdout ruling cl.1–cl.4 applies, and no confirmatory use is spent.
  - L-34: one look only, and a dry run is never a look.
  - L-12: widen only, never relax.
  - L-75: machine-written evidence is never hand-edited.
  - `iem_cli_fetch.fetch` is never called.
  - No credentials or order ids go into the repo.
  - F13 prereg bytes are unchanged.
- **Risks:**
  - The Bonferroni tail at B=2000 is thin (about 8 draws). L-12 allows B to be raised at S0, never lowered.
  - LAMP MDL gaps are MISSING and never imputed, so LAMP rows fall back to M0prime under the F13 nesting. Per-arm coverage is reported, which keeps any selection bias visible.
  - Horizon alignment: J2 keys rows by `climate_day` and anchors. A reviewer confirms the D-1 anchor maps to the D+1 target day.

## 8 Operator decisions
- **D1.** Grant a narrow exception to the 10-21 "existing harness only" ruling, under the Card D §6 precedent. It covers exactly one read-only file, `scripts/analysis/gap1_oof_murphy.py`, which:
  - reads `oof_rows.jsonl` (mu, sigma, nu per arm, plus the champion spec);
  - builds the common ladder centred on `round(champion q50)`;
  - computes the Murphy decomposition and ΔRES using the existing library functions.
  - It adds no model, fitting, tape access or emission.
  - If D1 is refused, GAP-1 can only reach UNRESOLVED, plus F13's own verdict.
- No size, cap or enablement decisions are involved.

## 9 Citations
- **Verified:**
  - `nbp_calibration.py:314, :317, :330-347, :472, :2239-2265`
  - `nbp_skill_study.py:1092-1102, :1106-1110, :1217-1218, :1601, :2109-2116`
  - `multisource_blend_skill.py:274-297, :324-325`
  - `multisource_blend_io.py:82-84`
  - F13 prereg `anchors`, `ladder`, `fold_rule`, `student_t_nu`, `champion_cdf_method`, `frozen_sha`
  - RULING_F13…:12, :37-40
  - 09-30 result lines 28-29, 690
- **Not verified:** see below.

---
Unverified citations:
1. The exact `arm_predictions` key names in `oof_rows.jsonl`, and whether M0 has its own entry or must be rebuilt from `champion`. S5's first RED test pins this.
2. Whether a `stage_a.json` exists outside `~/.local/share/breezy` (for example under `/mnt/storage`). Only that root was searched.
3. J3 runtime and peak memory are unmeasured. Only J2 has measurements.
4. Whether the 09-30 G2 validate look is already counted in the K_cum seed list.
5. That `resolution_difference` with `bin_by_edges(RELIABILITY_BUCKET_EDGES)` accepts generic (p, outcome) sequences without `MatchedEvent`. Only the call site at `nbp_calibration.py:2169-2173` was read.
