# P2 plan r2 — NBP vs venue ask at D−1 09:00 LST (2026-10-22; supersedes r1 per reviews/P2_r1_pmr.md + reviews/P2_r1_grok.md)


**Goal:** one test of whether the FQ v1 forecast that actually traded has more resolution than the PM.us YES ask, or a positive realized taker P&L, at the D−1 instant it traded. The result is PASS, FAIL or INCONCLUSIVE, with the consequence of each fixed below.

## Inputs (checked on disk in r1; Grok confirmed the code paths)

- **Forecast:** `PNoStore` / `ladder_p_yes` in `/home/jon/breezy/src/breezy/strategy/no_ladder_maker/pno_store.py`.
  - It reads only the 13Z and 19Z cycles of D−1 and the 01Z cycle of D, first MAX column.
  - It uses `LiveCalibration.resolve` (with the day-length correction) and takes the mean over the bootstrap draws.
  - `VectorChain.at(t)` returns the newest vector with `available_at_ns ≤ t`, so there is no look-ahead.
- **Calibration:** `/home/jon/breezy/deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`. **Fit range 2021-01-01..2026-06-30** (`DEFAULT_SPLITS`).
- **Stations:** LAX, MDW, MIA, SFO.
- **Book:** Depth10 L0 per rung, read with `forecast_cheap_screen_wp7.read_rung_tape` from `/mnt/storage/breezy/catalog/quote_tape/polymarket_us`. Rungs come from `market_calibration_scan.classify_directory` (inclusive [A,B]).
- **Truth:** `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (finals through 2026-10-21).
- **Statistics:**
  - `murphy_decomposition` and `resolution_difference` from `src/breezy/analysis/brier_decomposition.py`, using 10 equal-width bins (`nbp_calibration.RELIABILITY_BUCKET_EDGES`).
  - `cluster_bootstrap_draws` and `percentile_interval` from `src/breezy/analysis/nbp_calibration.py`, seed 20260929, B=2000.
- **Entry rule:** the production `forecast_quantile_ladder.decision.evaluate`, called with `permit_covers=True`, the `LadderEvConfig` / `slippage_floor_prob` that `composition.build_forecast_quantile_ladder_strategies` passes for `pm_us_crh_fq_v1`, a fresh `QuantileLadderLatch` per station-day, YES evaluated before NO, and fee coefficient 0.0695. This is the same call `fq_loss_taxonomy_reconstruct._p_hat` makes.
- **Scored range:** climate days D from the first day the tape has a book at 09:00 LST on D−1 (expected about 2026-08-30/31) **through 2026-10-13**.
  - The end is set by the last NBP file, `nbp_20261012_19z`: its 13Z/19Z cycles on 10-12 feed D = 10-13.
  - Assert `min(D−1) > 2026-06-30`.
  - This spends days from the sealed S2 holdout (from 2026-07-01). The evidence file says so.

## Fixed definitions

- **Gating instant:** 09:00 LST on D−1, at the station's fixed standard-time offset (no DST). This passes the D+1 check in `evaluate`.
- **Book rule:** the first snapshot at or after the instant and within 10 minutes; otherwise the rung is dropped. The uncapped `first_liftable_at_or_after` is not used.
- **ASK set (primary):** each rung whose YES L0 ask is present in that snapshot. The market forecast is that ask.
- **MID set (report only):** both L0 sides present in the same snapshot, with bid > 0.01.
- **Report-only D0 line:** D_res(ask) at 09:00 LST on D. There is no P&L line for D0, because FQ v1 refuses D0 with `NotDPlus1`.
- **D_res** = RES(p_nbp) − RES(ask), on identical events.
- **Taker P&L:**
  - For each ASK-set rung where `evaluate` returns a YES `Take`: P&L = outcome − ask − fee, with fee = 0.0695·ask·(1−ask), qty 1, rounded half-even to the cent. **This is the primary P&L.**
  - NO takes are reported separately, priced only from a captured NO-instrument book under the same 10-minute rule. Otherwise they are counted as unpriced.
- **Confidence intervals:** for D_res(ask) and YES P&L, compute the 95% CI clustered by station-day and by climate-day, and use the **wider** of the two.
- **Minimum sample, per statistic:**
  - D_res: ≥ 30 climate-day clusters and ≥ 200 rung-events.
  - YES P&L: ≥ 30 climate-day clusters and ≥ 30 takes.
  - A statistic below its minimum is "not evaluable".

## Steps

1. **Add `/home/jon/breezy/scripts/analysis/p2_nbp_ask_murphy.py`.** This is the only new code; the existing pieces are wired together here and are not available as one entry point anywhere else. It:
   - loads the calibration with `load_live_calibration` and the sha pin;
   - wraps `nbp_derived_store.partition_path`/`read_partition` in a 5-line `PartitionSource` adapter;
   - streams one station-day at a time and builds the events;
   - computes RES, D_res, P&L and the CIs;
   - writes the evidence file.
2. **Built-in checks.** Any failure means STOP, with no verdict.
   - The script asserts the sha pin and min(day) > 2026-06-30.
   - **Identity:** `|brier − reconstructed_brier| ≤ 1e-12` for both systems.
   - **Null:** setting p = ask gives D_res = 0 exactly.
   - **Live parity:** at the logged decision time in `logs/breezy-trade-20261004T165012Z.log` L1571–1589, the script's p for LAX 2026-10-05 `lt97f` must reproduce the logged p_hat 0.992 within `S0D_TOLERANCE`.
3. **Smoke run:** SFO only, one week. Time it.
   - If extrapolating the smoke time puts the full run above about 30 minutes, run it under `systemd-run --user -p MemoryMax=8G -p RuntimeMaxSec=14400 -p LimitNOFILE=524288`.
   - Otherwise run it directly.
4. **Full run → `/home/jon/breezy/docs/evidence/P2_NBP_VS_ASK_MURPHY_<run-date>.md`.** It contains:
   - the scored range and fit range;
   - the census, with drops by reason and by station (no vector at the instant, no book within 10 minutes, no truth);
   - per set: n events, both cluster counts, both Briers, REL/RES/UNC for both systems, D_res with both CIs;
   - YES and NO takes, and P&L with both CIs;
   - the verdict.
   Commit the script and evidence by explicit path.

## PASS / FAIL / INCONCLUSIVE (fixed now; only evaluable statistics count)

| Outcome | Condition | What follows |
|---|---|---|
| **PASS** | wider-CI lower bound of D_res(ask) ≥ +0.005, **or** wider-CI lower bound of YES P&L > 0 | A forecast-taker plan may be written later. |
| **FAIL** | wider-CI upper bound of D_res(ask) < 0, **and** wider-CI upper bound of YES P&L < 0 | Recommendation to delete the PM.us forecast-taker path, as its own reviewed change (list below). |
| **INCONCLUSIVE** | anything else, including any statistic not evaluable | Keep the code. No further forecast-taker work. The backlog proceeds through P4. |

**Deletion recommendation on FAIL (src, deploy and tests only).** It needs a fresh impact check at the time. Pinned import sets get updated, never weakened.
- In `src/breezy/strategy/forecast_quantile_ladder/`: `decision.py`, `strategy.py`, `composition.py`, `plugin.py`, `capture_adapter.py`, `decision_funnel.py`, `latch.py`, `margin.py`, `loss_stop_probe.py`, `config.py`, `bounds.py`, `artefact_bounds.py`.
- **Keep** `calibration_artefact.py` (the maker's `pno_store.py` imports it) and `persistent_latch.py` (`analysis/labeling/attribution.py` imports it).
- The FQ wiring in `src/breezy/app/trade.py` (L114–129, L791, the `forecast_quantile_ladder` composition branch).
- `deploy/families/pm_us_crh_fq_v1.json`. Keep the artefact JSON, which the maker uses.
- The taker-only tests under `tests/strategy/forecast_quantile_ladder/`.

## Effort and wall-clock

- Cost $0, about 1.5 days: day 1 for the script, checks and smoke run; day 2 for the full run and evidence.
- No src changes, so the full gate is not required. Run `ruff check` on the script.

## Risks

1. **MIA's 13Z D−1 cycle may land after 09:00 LST.** For MIA, 09:00 LST is 14:00Z, which is exactly the 13Z cycle plus the 60-minute floor. Late MIA vectors drop those station-days, which costs power and can push the result to INCONCLUSIVE. Those days are dropped, not substituted, and the per-station census shows how many.
2. **YES takes may be too few** to reach 30 takes over 30 climate days. The P&L statistic then can't be evaluated, so FAIL becomes impossible and the result is INCONCLUSIVE. That outcome is honest.
3. **The NO leg may be largely unpriced on the tape.** NO results stay report-only.

## What we deliberately do not do

- No instant (b): no METAR, no running max, no conditioning.
- No gating on D0 or on the mid.
- No 5-bin sensitivity, full-partition subset or W−C report.
- No synthetic positive control, no |p−mid| vs 0.021, no fee-plus-half-spread table.
- No NBP re-derive after 2026-10-12, no refit, no NYC.
- No deletion inside P2.
---

## r2.1 coordinator amendments (adopting verbatim the required changes of `reviews/P2_r2_grok.md` [REQUEST-CHANGES, 3 items] and `reviews/P2_r2_pmr.md` [APPROVE-WITH-CHANGES]) — STATUS: READY

These override the r2 text wherever the two conflict.

1. **Gating instant = the real launch.**
   - Use the first Depth10 snapshot at or after **16:50Z on LST date D−1**, within 10 minutes, one snapshot, else drop the rung. The node launches at 16:50Z (`trade_supervisor_core.py:38`), the permit lasts 10 h (`safety.py:172`), and the LAX `lt97f` Take was at 16:51:03Z. This instant is still D+1.
   - 09:00 LST is dropped everywhere: it lands before the process exists at MDW and MIA.
   - The D0 report-only line is dropped too, so there is one instant only.
   - The MIA 13Z-cycle risk no longer applies.
   - At the gate only the 13Z cycle of D−1 is visible (`pno_store.py:144–147`). The scored range still ends at D = 2026-10-13.
2. **Fee by date.**
   - Use `taker_fee_coefficient_as_of` (`fees.py:93–122`): 0.06 before 2026-09-17T00:00Z, refused until 17:00Z that day, then 0.0695.
   - `evaluate` keeps its hurdle on the unrounded `venue_fee_prob` plus slippage (`decision.py:337–345`).
   - Only the cash P&L fee is θ·ask·(1−ask), rounded half-even to the cent (`fees.py:313–351, 597–605`).
   - Composition uses the default `LadderEvConfig()` (`trade.py:854–873`).
3. **Dropped:**
   - the live-parity STOP: the log is under `logs-archive/`, and `p_hat` 0.9924313174096698 cannot meet `S0D_TOLERANCE` 1e-9 as specified;
   - the `systemd-run` scaffolding (run it directly; add a cap only if the smoke run says it exceeds 30 min);
   - the deletion file list. A FAIL leads to its own reviewed change with its own impact check.
   - **Kept:** the sha pin, the identity check, the null check, and `min(day) > 2026-06-30`.
4. **FAIL is decided by P&L** (PMR HIGH). The ask carries roughly 29% overround, so D_res(ask) < 0 is expected even with taker edge.
   - **FAIL** = the wider-CI upper bound of YES taker P&L is below 0, with ≥ 30 takes and ≥ 30 climate-day clusters. D_res is reported as corroboration only.
   - **PASS** is unchanged: D_res(ask) LB ≥ +0.005 OR YES P&L LB > 0.
   - **INCONCLUSIVE** = everything else. It leaves any deletion to a separate operator decision; it is never a mandate.
5. **Note in the evidence** that P&L at qty 1 at the L0 ask ignores depth, so it is optimistic, which leans toward PASS.
