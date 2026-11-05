# GAP-1 SOURCE-RESOLUTION — plan r0

Status: r0, written 2026-11-01. Peer review pending: **architect** and **prediction-market-reviewer**. Nothing runs before both reviews and the PREREG freeze.

## 1 Objective
Find out whether any archived forecast source has better resolution (Murphy RES) on rung binaries than NBP. Only fold-CV on data before 2026-07-01 counts. For any trade to win more often than price + fee, the model's probabilities have to separate winners from losers better than the ask does. Measured so far: NBP RES 0.0059 against YES-ask RES 0.0287 (P2). If no source beats NBP by a CI-separated margin, nothing downstream can make a winning family. GAP-1 is the first gate in the programme.

## 2 Preconditions and dependencies
- **No dependency on GAP-2…6.** GAP-1 is selection on archive data only and reads no tape. GAP-2 (forward emitter), GAP-3 (forecast-edge bins) and GAP-4 (family) only run for a source that PASSES here.
- **Correction to the shared premise.** Only `us-lamp-live` starts on 10-06. LAMP and PFM also have archive copies that go back before 07-01 (inventory below). So LAMP, PFM and LAV can be scored on archive data.
- **F13 lag freeze.** `docs/evidence/RULING_F13_source_lags_freeze_2026-10-21.md` covers the ≥ 14-day C1 lag requirement in `multisource_blend_skill.py` (refusal 4).

Inventory (listed by file count, contents not opened):

| Source | Store | Files | Span / cadence | Before 07-01? |
|---|---|---|---|---|
| NBS MOS (NBM station text) + GFS MOS | `~/.local/share/breezy/archive/iem-mos` (`mos_nbs_backfill.json`: 19 station-years) | 19+ | 2021→, 4×/day | **yes** |
| NBP percentiles | `~/.local/share/breezy/derived/nbp` (P2 fit 2021-01-01..2026-06-30) | n/c | 2021→, per cycle | **yes** |
| LAMP (MDL archive) | `/mnt/storage/breezy/us_source_archive/us-lamp-mdl` | 49,928 | yearly tars 2006–2025 plus monthly 2026 Jan–Sep; hourly; real gaps (e.g. 2026-03-26..30) | **yes** |
| LAV (IEM) | `us-lav-iem` | 5,639 | 2020/21→, gap-fill and cross-check only | **yes** |
| PFM (NWS point forecast) | `us-pfm-afos` | 101,498 | backfill ≥ 2021, 5 points (A0-R2) | **yes** |
| LAMP live (C1) | `us-lamp-live` | 1,887 | 2026-10-06→, hourly | **no** (tape window only) |
| Raw NBM members | none | 0 | — | **no** (NBP holds percentiles only). Out of scope, recorded as UNSCORABLE |

## 3 Scope
In scope. All runs use the existing harness with the exact flags below:
- **J1** `scripts/analysis/nbp_skill_study.py --stage validate --comparator-models --run-gates --out <run>/j1.json`. Default roots. Never `--stage holdout`, never `--coordinator-authorized`. Output: M0/M1/M2 (NBS-MOS family vs calibrated NBP) Brier, REL, RES and G2.0–G2.3, with d_res CIs.
- **J2** `scripts/analysis/multisource_blend_features_build.py --prereg <P> --nbp-root ~/.local/share/breezy/derived/nbp --us-source-root /mnt/storage/breezy/us_source_archive --mos-root ~/.local/share/breezy/archive --truth <settlement_truth.parquet> --start 2021-01-01 --end 2026-06-30 --out-features <run>/f.jsonl --out-lag-features <run>/fl.jsonl --report-json <run>/build.json --max-memory-gib 3.5`.
- **J3** `scripts/analysis/multisource_blend_skill.py --prereg <P> --features <run>/f.jsonl --lag-features <run>/fl.jsonl --c1-evidence <C1 lag evidence> --out-dir <run>/j3 --max-memory-gib 3.5`. Output: fold-CV CRPS for M0 (NBP champion), M0′, M1 (+LAMP), M2 (+PFM) and M3 (+GFS MOS), plus `oof_rows.jsonl`.
- **Cited, not re-run:** `scripts/analysis/p2_nbp_ask_murphy.py`, through `docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`.

**Harness gap (stated plainly).** J1 reports RES, but only for the MOS/NBP family. J3 reports CRPS only. No existing script produces rung-level RES or REL for LAMP, PFM or the blends. CRPS can only screen those sources. It cannot test resolution. See §8 decision D1.

Not in scope: any tape or catalog read, any refit after 07-01, the holdout, NYC (it is not in `_JOIN_STATIONS`), raw NBM, Kalshi, forward emission (GAP-2), and any change to the live or exec path.

## 4 Steps
Run one heavy job at a time. Each job runs as `systemd-run --user -p MemoryMax=4G -p LimitNOFILE=524288` with `--basetemp=<worktree>/.pytest-tmp`. A stall watch is armed for every job. Each run writes an immutable output directory: `~/.local/share/breezy/derived/gap1_source_resolution/<run_id>/`.

| # | Step | Inputs → output | Who | Time |
|---|---|---|---|---|
| S0 | Write `PREREG_GAP1_2026-11-01.json` (§5) and the F13 blend prereg pins. Freeze by commit sha. | → `docs/prereg/…` | sub-agent drafts, coordinator freezes | 1 h |
| S1 | Dry run of J1/J3 against a fixture. Not a look. | tests → GREEN | tdd-guide | 1 h |
| S2 | J1 | MOS/NBP archive → `j1.json` + generated note | harness under systemd-run | 1–2 h (ASOS 1-min parse; unmeasured) |
| S3 | J2 | archives → feature JSONL + sidecars | harness | 1–3 h |
| S4 | J3 | J2 output → `j3/result.json`, `oof_rows.jsonl` | harness | 0.5–1.5 h |
| S5 | Only if D1 is granted: Murphy reader over `oof_rows.jsonl`, which maps (mu, sigma) to rung p on the J1 ladder | J3 OOF → `murphy.json` | tdd-guide, then reviewer | build 0.5 d, run 0.5 h |
| S6 | Verdict note, machine-written (L-75). Coordinator sidecar. PROGRESS line. | → `docs/evidence/GAP1_SOURCE_RESOLUTION_<date>.md` | harness + coordinator | 0.5 h |

**Memory risk.** Earlier nightly studies used 10–24 GB, so J1 under 4 GiB may be OOM-killed. An OOM kill is recorded as "not run", never as a result. The cap can only be raised to a measured need (L-12), one job at a time.

## 5 Pre-registered PASS / KILL
These are frozen in S0 before S2 starts. There is one look.
- **Unit.** One cell = source s ∈ {NBS-MOS, GFS-MOS, LAMP, PFM, blend M1–M3} × horizon h ∈ {H1: D−1 issue at or before 16:50Z (the P2 gate instant); H0: D-morning issue at or before 15:00Z}. The baseline is NBP at the same issue instant.
- **Data.** Fit and score only on climate days from 2021-01-01 to 2026-06-30. Fold-CV uses the existing fold construction (leave-one-block-out), with no tuning on test folds. Nothing from the tape window is read for selection.
- **Metric.**
  - ΔRES = RES_s − RES_NBP on the forecast-centred 3-rung ladder (`_forecast_centered_ladder`).
  - CI: cluster bootstrap with B=2000 and seed 20260929. Station-day and climate-day clusters are both computed and the wider CI is used, as in P2.
- **PASS (cell).** All four must hold:
  1. Lower bound of ΔRES > X = 0.0152. This is the frozen G2.3 margin, reused and not re-derived.
  2. Holm-adjusted across all GAP-1 cells, and the cells are added to the K_cum ledger.
  3. Out-of-fold reliability passes the 09-30 gate set: G2.1 reliability buckets, G2.0 and G2.0a, with the definitions as they are in `nbp_skill_study.py` today.
  4. Evaluable: n ≥ 200 events and ≥ 30 climate-day clusters.
- **CRPS screen (LAMP/PFM/blends without D1).** M_k must beat M0 by the blend prereg's frozen floor (`stage_a.json`). The screen is necessary but never sufficient. A screen-only pass is reported as **UNRESOLVED**, never as PASS.
- **Overall PASS.** At least one cell passes. Only those cells go on to GAP-2/3.
  - Disclosure: the measured ask-vs-NBP gap is 0.0228, which is larger than X. A PASS therefore shows the source is better than NBP. It does not show the source is better than the market. That test is GAP-3's single forward look.
- **KILL.** No cell passes, and every source's resolution has been tested (D1 granted, or MOS-only if D1 is refused and LAMP/PFM fail the screen).
  - On KILL: write the evidence note and the PROGRESS entry "forecast-edge programme STOPPED at GAP-1". GAP-2, 3 and 4 do not start. GAP-5 and GAP-6 stay independent.
- **UNRESOLVED.** D1 is refused and a screen passed. This goes to the operator. It is not a silent KILL.

## 6 Tests and gate route
Write each test RED first.
- **S1:**
  - `test_gap1_prereg_frozen_blob_matches` (via `prereg_precommit_check.check_frozen_blob`)
  - `test_gap1_runs_refuse_rows_on_or_after_2026_07_01`
  - `test_gap1_j1_never_opens_holdout`
- **S5 (only if D1):**
  - `test_oof_murphy_identity_brier_reconstructs_1e12`
  - `test_oof_murphy_self_delta_is_zero`
  - `test_oof_murphy_refuses_header_digest_mismatch`
  - `test_oof_murphy_refuses_post_cutoff_rows`
  - `test_oof_murphy_no_network_no_catalog_import`
- **Gate:** `scripts/ci/run_tests_no_egress.sh` on the primary tree is the binding result. Read EXIT before any push. Briefs must name the whole-tree guards: import pins, `lint-imports` from the tree root, the citation map and the asdict scan.

## 7 Pins, isolation, risks
- The binding constraints all hold:
  - Nautilus is immutable.
  - `allow_short` stays False.
  - No safety, settlement, contract, pin or NO-SEND test is weakened or deleted.
  - No operator caps are assigned.
  - Live enablement and the egress firewall are not touched.
  - Holdout ruling cl.1–cl.4 applies: no confirmatory use is spent here.
  - L-34: one look only.
  - L-12: thresholds can only be widened, never relaxed.
  - L-75: machine-written evidence is never hand-edited.
  - `iem_cli_fetch.fetch` is never called.
  - No credentials or order ids go into the repo.
- **Risks:**
  - The CRPS-to-RES proxy can mislead. Mitigation: a screen-only result is UNRESOLVED, never PASS.
  - The LAMP MDL gaps (MISSING, never imputed) can bias toward days where LAMP is present. Mitigation: report the per-source coverage census.
  - The NBP "first MAX column is D+1" convention can misalign horizons. Mitigation: J1 already keys on `target_climate_day`. Reviewers should check that J2 does the same.

## 8 Operator decisions
- **D1.** Grant a narrow exception to the 10-21 "existing harness only" ruling. It would cover one read-only reader that turns existing `oof_rows.jsonl` (mu, sigma) into rung p and the Murphy decomposition. It adds no model, fitting, tape access or emission.
  - This is a smaller exception than GAP-2's and follows the Card D §6 precedent.
  - Without it, LAMP, PFM and the blends can only reach UNRESOLVED.
- **No size, cap or enablement decisions** are involved.

## 9 Citations not verified
See the list below.

---
Unverified citations:
1. G2.0 and G2.1 gate definitions were not read. The plan relies on `NBP_S2_VALIDATE_RESULT_2026-09-30.md` and the 09-30 ruling text.
2. The J1/J2/J3 run times and peak memory are estimates, not measurements.
3. The `us-pfm-afos` and `us-lav-iem` spans come from F13 A0 (A0-R2/R4/R6) and the PFM spot-check, not from reading `coverage.json`, which is too large to read.
4. Whether J3 `oof_rows.jsonl` carries (mu, sigma) per row, which S5 needs, was not confirmed.
5. The C1 lag-evidence path for `--c1-evidence` and the F13 blend prereg path were not located. S0 must name both.
