# GAP-1 source-resolution kill screen — coordinator sidecar (S6)

Run: `gap1_j3_2026-11-02` (one pre-registered look, executed 2026-11-03).
PREREG: `docs/plans/backlog/GAPS_2026-11-01/gap1_source_resolution/PREREG_GAP1_2026-11-02.json`
(frozen_sha e648d181, stamp f86e3b76). Machine outputs (never hand-edited, L-75):
`/mnt/storage/breezy/derived/gap1_source_resolution/gap1_j3_2026-11-02/` (build.json, counts.json,
j3/{stage_a,result,prereg_record}.json, j3/oof_rows.jsonl, murphy.json). Committed copies:
`docs/evidence/gap1_source_resolution/counts_gap1_j3_2026-11-02.json` (94fbc55e, pre-J3) and
`docs/evidence/gap1_source_resolution/murphy_gap1_j3_2026-11-02.json` (sha256 74099a17…).

## Registered verdict (frozen rule, not reinterpreted)

**overall = PASS.** D1 granted (`d1.json`, prereg_frozen_sha e648d181). k_cum 1 → 8 (static PREREG copy).

| cell | class | n | n_min_adj | dRES | CI lower (gate) | label |
|---|---|---|---|---|---|---|
| M1:D0 | PASS | 7824 | 956 | 0.0439 | 0.0402 | beats ask (indicative) |
| M2:D0 | PASS | 7824 | 963 | 0.0492 | 0.0454 | beats ask (indicative) |
| M3:D0 | PASS | 7824 | 965 | 0.0491 | 0.0453 | beats ask (indicative) |
| M1/M2/M3:D-1 | FAIL | 7789 | 152 | 0.0012 | −0.00015 | — |

Guards at D0 all clear: REL_arm (≈4.4–4.6e-4) < REL_M0t (5.28e-4); dRES vs M0prime +0.029/+0.035/+0.035 (> 0, so not OBS_DRIVEN).
Both clusterings (station_day, climate_day) agree within 0.0004. Power met in all six cells.

## What the result does and does not say

- **D-1 is uninformative about LAMP.** LAMP missing on 7789/7789 D-1 rows at the 18:00Z anchor (same pattern as the
  10-21 draft: 9577/9582). M1–M3 collapse to M0prime there (dRES_M0prime = 0; `fell_back` reads 0 by construction,
  read `lamp_missing` instead). Prefix-present D-1 sensitivity n = 0. A D-1 FAIL does not falsify LAMP.
- **Only D0 bears on LAMP** (31/7979 missing-prefix). Of the D0 gain vs M0t, ≈0.0145 is the M0prime step
  (NBP + 10:00 LST METAR recalibration) and ≈0.029 is the LAMP step (M0prime → M1); PFM/MOS add ≤ 0.005.
- **"Beats ask (indicative)"** is RES(ask) − RES(NBP) = 0.0228 from `P2_NBP_VS_ASK_MURPHY_2026-10-22.md` (781 venue-rung
  events). It is a Brier-resolution screen on a champion-centred ladder, not a venue-rung, fee-net, executable edge.
  No dollar claim. No trading change. GAP-3 is the test against the market.
- **f13_verdict = HELD_LEAK_AUDIT (unresolved).** F13's shuffled-label negative control (M0prime vs M3, within-version
  shuffle) has one-sided lower bound 0.0116 > 0 ("the pipeline finds skill in noise"; shuffled mean 0.0365 vs real
  0.165). The PREREG says this never overrides GAP-1, so PASS stands as registered — but the audit is owed, not
  discharged (`multisource_blend_stats.py:230-234`). Candidate benign mechanism: M3's extra regressors under the soft
  sum-to-one penalty; undiagnosable from `oof_rows.jsonl` (shuffled rows not persisted).
- **KNYC absent by design (KNYC-DROP diagnosed 11-03, skew hypothesis REFUTED).** `f.jsonl` holds LAX/MDW/MIA/SFO
  only. NYC is "not in scope" per `plan_r1.md:37`, and `plan_r1.md:33` pins `--nbp-root …/derived/nbp`, a 4-station
  store (manifest 8945df4b, 0 KNYC rows in 6361 partitions); the 10-21 draft read the 5-station `derived/nbp5`
  (aa721c24). KNYC days therefore hit `select_nbp` with no candidates and are counted as `nbp_missing` (1642 at D0 =
  exactly the draft's 9621 → 7979 loss). Rows lost, not leaked; no timestamp rewrite involved. Gap: the plan never
  states that the NYC exclusion is why the row count fell, and the builder counts a zero-candidate station as
  `nbp_missing` instead of flagging it (candidate guard). NBP's availability pin remains `provisional: true` and
  outside `assert_row_leakage_free` (obs/pfm/mos/lamp only).
- Frozen source lags are p99 over 14–15 live days (Oct 2026) applied to 2021–2026 archives; observed maxima exceed
  pins (lav 110.6 vs 90 min; pfm 174 vs ≈99 min). The +60 min lag twin (lb 0.163 vs 0.150) shows the primary result is
  not timing-sensitive at 1 h.
- OOF integrity holds: 28-day climate_day blocks within NBM version and source-break segment, ±3-day embargo, champion
  refit excluding the held block. Holdout seal working (counters rose because the store grew; in-window loss is KNYC).

## Deviations and run notes (none change PREREG bytes)

- Run root relocated: the PREREG-pinned `~/.local/share/breezy/derived/gap1_source_resolution` is now a symlink to
  `/mnt/storage/breezy/derived/gap1_source_resolution` (mirrors `us_source_archive`). Needed because the J2 builder
  refuses writes under the live data root (`LIVE_DATA_ROOT` guard, a13e02d0, 2026-10-07) and the PREREG (2026-11-01)
  pinned a root inside it. Both scripts `.resolve()` so the reader still sees the frozen path.
- `--mos-root` = `~/.local/share/breezy/archive/iem-mos` (plan_r1:33 wrote `archive/`, which contains the
  settlement-alignment cache the builder requires to be disjoint).
- Thread env added to the systemd units (OMP/OPENBLAS/MKL/RAYON/POLARS = 4, ARROW_IO = 2): default 16-core pools
  could not create threads under the 3.5 GiB address-space cap (EAGAIN → std::system_error abort). Not an envelope cap.
- Three refused/aborted J2 launches (REFUSED path guard; EAGAIN; ArchiveCachePathError) computed nothing and wrote no
  features; the failed `build.json` (status error) was removed before the successful launch.
- J2: 35m01s wall, 3.2 G peak (cap 12 G / 3000 s). J3: 18m50s wall, 369.5 M peak (cap 12 G / 14400 s).
  S5 reader: 30m55s, 303.6 M. All under `systemd-run --user`, app.slice, LimitNOFILE=524288, stall watch armed.
- `murphy.json` git_sha 94fbc55e vs run_provenance code_sha 29d4836b: one docs-only commit between (counts.json),
  accepted by the reader; F13 prereg_record frozen_sha 205fd542 is the F13 prereg's own stamp (benign).
- Census (S3.5): every cell's ITT upper bound ≥ 7940 > floor 914, so the PREREG go/no-go did not fire; architect +
  prediction-market go/no-go was run anyway (GO-WITH-NOTE ×2) because D-1 is fallback-only.

## Disposition

PASS is recorded as registered. The conditional unlock of backlog #10 (GAP-2 → GAP-3 → GAP-4) is **held** behind two
follow-ups, neither of which re-looks at the primary data:
1. LEAK-NULL: outcome-blind, multi-seed shuffled-null of M3 vs M0prime (re-fit on permuted labels; needs a plan + peer
   loop; must not touch `gap1_j3_2026-11-02/j3`).
2. KNYC-DROP: CLOSED 11-03 — NYC out of scope by plan (`plan_r1.md:37`), 4-station store by plan (`:33`); disclosure
   is this paragraph. Residual candidate (small): builder guard that flags a configured station with zero NBP
   candidates instead of counting it as `nbp_missing`.
Reviews: go/no-go architect + prediction-market (GO-WITH-NOTE); post-read mle-reviewer (PASS_SUSPECT) +
prediction-market (mechanically correct, not decision-grade while HELD_LEAK_AUDIT stands).
