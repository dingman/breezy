# Forward GAP-1 D0 edge screen -- STEP 1 feasibility (2026-11-05, read-only)
SCREEN -- not confirmatory; upper bound (zero slippage); forward sample is small. Nothing was run; repo untouched.

## Windows
- Tape (Depth10, HIGH, LAX/MDW/MIA/SFO): climate days 2026-08-30..2026-11-05 (265 station-days, prior screen).
- FINAL truth (`derived/settlement-truth/settlement_truth.csv`, written 2026-09-29): last FINAL day 2026-09-28, all 5 stations.
- Sealed holdout (`DEFAULT_SPLITS`, RULING_holdout_freeze_and_forward_window_2026-10-03 cl.1): [2026-07-01, 2026-10-02); forward = >= 2026-10-02.
- => Tape ∩ FINAL truth = 2026-08-30..2026-09-28 = 30 days x 4 stations = 120 station-days, ALL inside the sealed holdout.
- => Admissible forward window (>= 10-02) ∩ FINAL truth = 0 station-days.

## Per-source coverage for climate days 2026-08-30..2026-09-28 (W) and forward 2026-10-02..2026-11-05 (F), 4 stations
| source (arm need) | store | covered range | W days/stn | F days/stn |
|---|---|---|---|---|
| NBP q50/sd (all arms) | `derived/nbp` v5.0, 01/13/19z | 2026-08-01..2026-10-26 | 30/30 | 25/35 |
| obs_so_far (M0prime..M3 obs cells) | `us_source_archive/metar-routine` (FB-R15: ONLY source) | 2026-01-01..2026-06-30 | 0/30 | 0/35 |
| LAMP (M1+) | `us-lamp-mdl` lamp-mdl-r0 | 2021-01-01..2026-09-30 (720 runs 08-28..10-02) | 30/30 | 0/35 (us-lamp-live 10-06+ is a different product, "not used" per plan_r1) |
| PFM (M2+) | `us-pfm-afos` pfm-r0 | 2021-01-01..2026-11-05 | 30/30 | 35/35 |
| GFS MOS (M3) | `archive/iem-mos` mos-gfs | 2021-01-01..2026-06-30 (NBS to 11-02 exists; M3 pins GFS, model mix refused) | 0/30 | 0/35 |
| FINAL truth | settlement_truth.csv | ..2026-09-28 | 30/30 | 0/35 |
Live NWS observations catalog (`catalog/quote_tape/observations`) starts 2026-09-17, mixes 5-min/METAR, not the pinned routine-METAR store -> not admissible without a pin change (train/serve skew).

## (c) Frozen-fit mechanics
No persisted BlendFit parameters exist; `oof_rows.jsonl` holds per-row OOF predictions from per-fold refits. The path would be
`fit_blend(rows<07-01, level, BlendSettings(nu=5, sigma_floor_f=0.75, weight_sum_lambda=1.0, min_cell_rows=60))` then `predict_row(fit, row)`.
`predict_row` itself does not assert the holdout, but `fit_blend`/`score_rows`/`out_of_fold_scores` refuse rows >= 2026-07-01 (`_assert_admissible`),
and the J2 builder "never opens the holdout", so tape-day rows would have to be hand-assembled via `assemble_feature_row` outside the builder.
A single full-pre-holdout fit is also not the registered champion (which is per-fold), so "frozen GAP-1 champion" would be a new fit.

## Decision: STOP after feasibility (no STEP 2)
1. Admissible forward station-days with FINAL truth = 0 (< 20). The only scorable window (120 station-days) is the sealed holdout; scoring p vs outcome there
   spends the single confirmatory look that cl.1 reserves and that GAP-2/GAP-3 plans refuse outright ("so no confirmatory use is spent"). Not my call to burn.
2. Even inside the holdout, M3 is unscorable (GFS MOS ends 06-30 -> M2 fallback at best) and obs_so_far is absent on every day (obs-absent cells were fitted
   mostly on D-1 rows), so the result would not be the GAP-1 D0 champion anyway.
Unblock paths (not executed): refresh FINAL truth past 10-02 (CLI alignment cache exists to 11-04) + extend routine-METAR/LAMP-MDL/GFS-MOS stores into the
forward window, then score >= 10-02 only (GAP-2/GAP-3 design); or an explicit ARCH ruling to spend the holdout look on this screen.
