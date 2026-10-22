# P2 plan r1 — NBP vs venue mid, paired Murphy resolution (2026-10-22; author planner)


**Goal:** find out whether the live FQ v1 NBP probability carries more information (resolution) than the Polymarket.us mid. Score it at 09:00 LST and at a METAR-driven instant. A FAIL names the PM.us forecast-taker code to delete; nothing is deleted in this plan.

## Inputs (all checked on disk 2026-10-22)

- **Forecast engine:** `PNoStore` + `ladder_p_yes` in `/home/jon/breezy/src/breezy/strategy/no_ladder_maker/pno_store.py`. This is the live-equivalent FQ probability:
  - It reads only the cycles that can feed day D: 13Z and 19Z of D-1 and 01Z of D, first MAX column.
  - It uses `LiveCalibration.resolve`, which includes the day-length location correction.
  - p is the mean over the bootstrap draws, through `rung_probability_interval`.
  - `VectorChain.at(t)` returns the newest vector with `available_at_ns ≤ t`, so there is no look-ahead.
  - **Do not use** `scripts/analysis/nbp_market_comparison.py:probabilities_from_nbp_rows`. It skips the location correction, groups by UTC valid date, refuses tape after 2026-09-25, and queries the whole Depth10 catalog (~400 GB).
- **Calibration:** `/home/jon/breezy/deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`.
  - sha `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e` (the artefact that traded live).
  - `recalibration=none`, correction `linear_lst_day_length`, `cdf_method=normal`.
  - **Fit range: 2021-01-01 .. 2026-06-30.** That is train 2021–2024, validate 2025-01-01..2026-05-03 and the v5 slice 2026-05-04..06-30 (`DEFAULT_SPLITS`; `NBP_S2_VALIDATE_RESULT_2026-09-30.md`).
- **Stations:** LAX, MDW, MIA, SFO. These are the FQ v1 manifest stations, and `pno_store.site()` refuses NYC.
- **Scored range:** climate days from the first depth-tape day (about 2026-08-30) **through 2026-10-12**, inclusive.
  - The end is fixed because the NBP derived store `~/.local/share/breezy/derived/nbp/YYYY/MM/nbp_YYYYMMDD_{01,13,19}z.parquet` ends at 2026-10-12.
  - That is more than 60 days after the fit end, so the two ranges cannot overlap. The script hard-asserts `min(day) > 2026-06-30`.
- **Venue mid:** Depth10 L0 bid and ask, read per rung with `forecast_cheap_screen_wp7.read_rung_tape`. This is the WP-7b reader, re-proven in the AUD-02 run.
  - Tape root `/mnt/storage/breezy/catalog/quote_tape/polymarket_us`, passed explicitly.
  - Rungs come from `market_calibration_scan.classify_directory`, which gives inclusive [A,B] bounds.
- **Truth:** `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (finals through 2026-10-21). Outcome = `lo ≤ tmax_f ≤ hi`.
- **METAR:** `read_routine_metar` in `scripts/archive/metar_routine_store.py`, store at `/mnt/storage/breezy/us_source_archive/metar-routine/K*/2026.csv`. Only rows with `tmpf_source == "tgroup"` are used (tenths °C). They go into `RunningExtremeAccumulator` with `is_metar=True` and a fixed receipt time of observation time + 10 min.
- **Statistics, reused unchanged:**
  - `murphy_decomposition` and `resolution_difference` from `src/breezy/analysis/brier_decomposition.py`.
  - `cluster_bootstrap_draws`, `percentile_interval` and `RELIABILITY_BUCKET_EDGES` (10 equal-width bins) from `src/breezy/analysis/nbp_calibration.py`, with seed 20260929 and B=2000.
  - Clusters are (station, climate_day).
- **Why the 09-20 table did not close:** it printed the classic REL−RES+UNC with coarse bins. The extended identity `BS = REL − RES + UNC + W − C` closes exactly; for example 0.13200 vs 0.13090 on the ask/forecast row is the omitted W−C. Both REL−RES+UNC and the W−C residual will be reported.

## Instants (fixed before any outcome is read)

- **(a) 09:00 LST on D.**
  - The book snapshot is the first Depth10 snapshot at or after the instant, within 10 min (the WP-7b rule). The mid exists only if L0 bid and ask are both in that same snapshot.
  - p is the **unconditioned** NBP rung probability, which is what the taker computes.
- **(b) The first minute at or after 09:00 LST where a tenths-°C METAR moves the running max `R` into a different rung than it was in at 09:00.**
  - Why not the literal wording: with METAR-only history every METAR "pins" `R`, so the literal reading would just give the first METAR of the day.
  - Station-days with no crossing contribute no (b) events; their count is reported.
  - p is NBP **conditioned on T ≥ R**: dead rungs are set to 0 and each live rung gets `mass(rung ∩ T≥R) / mass(T≥R)`, using the mean-over-draws masses.
  - Only live rungs (R's rung and above) are scored.
- **Event set at both instants:** every rung whose snapshot is two-sided, with the forecast and the market scored on identical events. A station-day counts as a cluster if it has at least one event. The WP-7b full-partition subset is reported but does not gate.

## Steps

1. **Pre-flight (read-only).**
   - Record the first and last tape climate day, the last NBP derived cycle, the last METAR row date and the last truth date.
   - The scored range is the intersection of those coverages, clipped to [tape start, 2026-10-12]. Print it in the evidence.
2. **Add `/home/jon/breezy/scripts/analysis/p2_nbp_mid_murphy.py`** (the only new code). It:
   - verifies the artefact sha with `load_live_calibration`;
   - wraps `nbp_derived_store.partition_path`/`read_partition` in a 5-line `PartitionSource` adapter;
   - streams one station-day at a time, freeing each tape after use (as WP-7b `collect` does);
   - builds the events for (a) and (b);
   - computes Murphy components, D_res and its CI per instant;
   - writes the evidence file and prints one heartbeat line per station-day for the stall watch.
3. **In-script controls.** Any failure means STOP and no verdict.
   - **Identity:** `|brier − reconstructed_brier| ≤ 1e-12` for every system and instant.
   - **Null:** setting p_fc = mid gives D_res = 0 and CI = [0, 0].
   - **Positive:** setting p_fc = 0.8·outcome + 0.1 on the real (a) events gives a CI lower bound ≥ +0.005.
   - **Live parity:** LAX 2026-10-05 rung `lt97f` at the logged decision time (`logs/breezy-trade-20261004T165012Z.log` L1571–1589) must reproduce the logged p_hat 0.992 within the `S0D_TOLERANCE` used by `fq_loss_taxonomy_reconstruct`.
4. **Smoke run:** SFO 2026-09-01 only. Check the census and both instants by hand.
5. **Full run**, one heavy job, with a Monitor on the heartbeat log's mtime (stall after 20 min):
   `systemd-run --user -p MemoryMax=8G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288 …`
6. **Evidence:** `/home/jon/breezy/docs/evidence/P2_NBP_VS_MID_MURPHY_<run-date>.md`, written by the script. It contains:
   - the census, with refusals by reason;
   - the scored range and fit range;
   - per instant: n events, clusters, Brier for both systems, REL/RES/UNC/W/C/residual for both, and D_res with its CI;
   - for (b): mean |p − mid| against the 0.021 hurdle, plus the measured mean fee + half-spread;
   - the verdict line.
   Commit the script and the evidence by explicit path.

## PASS / FAIL / STOP (numeric)

- **Per instant:** pass if `D = RES_fc − RES_mkt` on 10 equal-width bins has a station-day-clustered 95% CI lower bound **≥ +0.005** with **≥ 30 clusters**.
- **PASS:** either instant passes. This leans toward keeping the code, which is the safe direction for a deletion decision.
- **FAIL:** (a) has ≥ 30 clusters and does not pass, and (b) does not pass (or has < 30 clusters).
- **STOP (no verdict, delete nothing):**
  - (a) has < 30 clusters;
  - any control fails;
  - artefact sha mismatch;
  - a scored day ≤ 2026-06-30;
  - a vector with `available_at_ns` later than the instant.
- **Not gating (report only):** the (b) mean |p − mid| against 0.021, the 5-bin sensitivity, and the full-partition subset.
- **On FAIL, these would be deleted.** Each item needs a fresh impact check at the time, and pinned import sets must be updated, never weakened.
  - In `src/breezy/strategy/forecast_quantile_ladder/`: `decision.py`, `strategy.py`, `composition.py`, `plugin.py`, `capture_adapter.py`, `decision_funnel.py`, `latch.py`, `margin.py`, `loss_stop_probe.py`, `config.py`, `bounds.py`, `artefact_bounds.py`.
  - The FQ wiring in `src/breezy/app/trade.py` (imports at L114–129, `fq_bridge` at L791, the `forecast_quantile_ladder` composition branch).
  - `deploy/families/pm_us_crh_fq_v1.json`.
  - The taker-only tests in `tests/strategy/forecast_quantile_ladder/`.
  - The scripts `scripts/analysis/fq_*.py`, `nbp_shadow_parity*.py` and `nbp_market_comparison.py`.
  - **Keep** `calibration_artefact.py` (imported by `no_ladder_maker/pno_store.py`), `persistent_latch.py` (imported by `analysis/labeling/attribution.py`) and the calibration artefact JSON, because the maker uses them.

## Effort and wall-clock

- Cost $0.
- Day 1: write the script, run the controls and the smoke run.
- Day 2: full run (about 1–4 h, limited by the slow storage disk read speed), then the evidence and review.
- No src changes, so the full gate is not required. Run `ruff check` on the script.

## Risks

1. **The run spends part of the sealed S2 holdout** (days ≥ 2026-07-01). The 2026-09-30 ruling kept it sealed; the 2026-10-22 backlog adoption is what authorizes using it here. Any later S2 verdict must exclude 2026-08-30..10-12.
2. **The (b) running max comes only from routine METARs**, so it is a lower bound on what the market can see from 5-minute data. That biases against the forecast. Also, CLI truth below R is possible; those cases are counted and kept.
3. **Mid coverage could still be thin.** WP-7b got 24 full-partition mid days out of 84. Per-rung inclusion should help, but if (a) has < 30 clusters the result is STOP, not FAIL.

## What we deliberately do not do

- No new module, timer, harness, PREREG or ruling.
- No NBP re-derive after 2026-10-12 and no METAR fetch.
- No refit or recalibration of NBP.
- No NYC.
- No D+1 instant. FQ v1 traded D+1, but this audit uses the specified D0 instants, which give the forecast its strongest (newest) cycle.
- No ask-based gate.
- No deletion in this item.