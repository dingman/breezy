# F13 US weather source survey: 2026-10-06

Research agent output (web and documentation, read-only), recorded verbatim below. **Not verified by the coordinator.** In particular, the arXiv 2609.23969 skill figures are as reported by the agent and must be re-checked against the paper before any decision rests on them.

## Coordinator reading
- **No allowed US source is independent of NBM,** because NBM blends GFS/GEFS/HRRR/RAP/NAM/MOS. Any extra skill comes from different post-processing (LAMP, which uses observations; the human PFM/NDFD forecast) or from raw output we bias-correct per station ourselves (HRRR).
- **The reported blend of public products roughly matches the market, not beats it.** A static blend is therefore not, on its own, an edge.
- **The timing hypothesis is worth testing:** the market may lag new-run releases.
- **Effect on the F13 plan:** its acceptance must measure edge against the market's ask, not just RMSE against NBM.

---

I rank **LAMP, HRRR and the NWS forecaster's own point forecast (PFM text) as the top three** to add to NBM. No allowed US source is fully independent of NBM, because NBM already blends GFS, GEFS, HRRR, RAP, NAM and MOS. The extra skill has to come from different post-processing (LAMP's use of observations, the human forecaster) or from raw model output you bias-correct per station yourself (HRRR). Everything below is from documentation and searches; I downloaded nothing and edited no files.

**Main skill evidence:** arXiv 2609.23969 (Kalshi markets vs public forecasts, 7 cities including NYC, MDW, MIA and LAX). At the day-before market open, next-day max RMSE was:

| Source | RMSE (°F) |
|---|---|
| Market | 2.44 |
| NBM | 2.70 |
| LAMP | 2.83 |
| NDFD (human) | 2.83 |
| GFS MOS | 3.17 |
| ECMWF | 3.31 |
| HRRR (raw) | 3.32 |

An out-of-sample regression blend of the public products reached 2.45 at the open, 2.25 vs NBM's 2.45 in the evening, and 1.90 vs 2.12 at the final NBM run. That is about 9–10% better than NBM, roughly matching the market. The blend included ECMWF, which you can't use, and the paper doesn't publish its weights. It also notes IEM keeps only LAMP's 00/06/12/18Z runs, so its LAMP inputs were 2–4 h stale.

| # | Source | Independent of NBM? | Archive depth and access | available_at | Effort | Value |
|---|---|---|---|---|---|---|
| 1 | LAMP (LAV) | Medium. Statistical, uses latest obs plus GFS MOS and HRRR | MDL `lamp.mdl.nws.noaa.gov/lamp/Data/archives/lmp_lavtxt.YYYY.tar`: hourly runs 2006–2025, ~3.8 GB/yr. 2026 not there yet. IEM `mos.py?model=LAV` from 2020-07, 00/06/12/18Z only, hourly `tmp`, no max/min column | Yes. Runs every hour, out about HH:30 | Medium. Daily max must come from hourly temps, and the 25 h text may not reach the D+1 afternoon | High |
| 2 | HRRR (v4 since Dec 2020) | High. Raw model, ~3 km | AWS `s3://noaa-hrrr-bdp-pds/hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfFF.grib2` with `.idx`; Google `high-resolution-rapid-refresh`; 2014 onward | Rebuild as run time + fixed delay (~1–2 h, my estimate). 48 h runs at 00/06/12/18Z cover D+1 | Medium-high. The 2 m TMP field is ~1.5 MB per hour and can't be cut to 5 points, so ~35 MB per run, ~100 MB per day | Medium-high once bias-corrected per station. Raw RMSE is the worst of the group |
| 3 | NWS forecaster forecast as PFM text (Point Forecast Matrices; has a Max/Min row) | Low-medium. Human, starts from NBM | IEM AFOS `cgi-bin/afos/retrieve.py?pil=PFM{OKX,LOT,MFL,LOX,MTR}&sdate=&edate=&fmt=text`, about 2000 onward, a few KB per issue | Yes, exact: the WMO header time (e.g. `FOUS51 KOKX 012020`). Issued about 3:30–4:20 PM local plus ~4 AM and updates | Low. Parse text; same IEM client as the MOS code | Medium. Ties NBM on its own but adds human judgement |
| 4 | NDFD gridded forecast (human) | Same as #3 | AWS `s3://noaa-ndfd-pds/wmo/<elem>/YYYY/MM/DD/` from 2020-04-16; MB-scale grids issued up to every 30 min | From file and WMO time | Medium (GRIB2 decode, nearest grid point) | Duplicates #3. Use PFM instead |
| 5 | GFS MOS (MAV short-range; MEX extended) | Low-medium. Already an NBM input | IEM `mos.py?model=GFS` from 2003, `MEX` from 2020-07. **Already wired in the repo** | Yes. 00Z ready ~04:15Z, 12Z ~16:15Z; 18Z probably ~22:15Z (my estimate) | Low | Low-medium. 3.17 RMSE, still usable in a blend |
| 6 | NAM MOS (MET) | Low-medium | IEM `model=NAM` from 2008 | Yes | Low | **Terminated 2026-11-03** (NWS notice SCN 26-47). Backtest only, no live use |
| 7 | GEFS (v12 since 2020-09) | Low. Heavily weighted in NBM | AWS `noaa-gefs-pds` from 2017; 6-hourly 2 m max temp. The reforecast covers only 2000–2019, so it is for calibration, not a 2021+ backtest | Rebuild as run + ~5–6 h (my estimate) | High (31 members, GRIB) | Low, but gives a spread signal |
| 8 | RAP | Low. HRRR's parent model | AWS `noaa-rap-pds` and NCEI; 51 h runs at 03/09/15/21Z | Rebuild as run + delay | Medium | Low |
| 9 | NBS / NBE / NBH text | None (NBM itself) | IEM NBS from 2018, NBE from 2020 | Yes | Already in repo | Only useful as a deterministic-vs-probabilistic cross-check |
| 10 | RRFS | High | AWS `noaa-rrfs-pds` holds prototype output only. **Operational from today (2026-10-06)** | n/a | n/a | **Its archive cannot support a pre-2026-07-01 backtest.** Collect live from now |
| 11 | WPC / CPC | n/a | n/a | n/a | n/a | Not useful. WPC max-temp grids start at day 3, CPC at 6–10 days |

**Top 3:**
1. **LAMP.** Second-best US product in the paper and conditioned on observations, so its errors differ from NBM's. Pull from the MDL hourly tars rather than IEM's 4-run archive so the decision-time runs are fresh. Download 2026 live, since its yearly tar isn't posted yet.
2. **NWS PFM text.** Tiny, exact issue times back to 2021, and it covers the KNYC Central Park point (`NYZ072`). Low effort and adds the forecaster's judgement.
3. **HRRR (12Z/18Z runs).** The most structurally independent dynamical source. It needs per-station bias correction learned only from settled CLI days, and it is the largest download.

GFS MOS is a cheap fourth because the code already exists.

**Backtest flags:**
- RRFS has no usable history.
- NAM MOS stops on 2026-11-03.
- The MDL LAMP tars end at 2025.
- IEM marks a new NBS/NBE cycle from 2026-05-05, so check for a version break.

**Repo code to reuse (read only, nothing edited):**
- `/home/jon/breezy/scripts/venue/iem_mos_probe_transport.py`
  - `:58` the station set is closed to KLAX/KMDW/KMIA/KSFO, so KNYC must be added.
  - `:60` the model set is NBS and GFS only; add LAV, MEX, NAM.
  - `:296-320` the MOS URL builder and its validation.
- `/home/jon/breezy/src/breezy/persistence/archive_cache.py`
  - `:55` `IEM_MOS_SOURCE`.
  - `:59` the model-to-product map (`IEM_MOS_MODEL_PRODUCTS`), which needs `mos-lav` and similar entries.
  - `:211` `iem_mos_request` and `:239` `iem_mos_window_request`.
  - `:335` the `ArchiveCache` class.
- `/home/jon/breezy/scripts/archive/iem_mos_backfill.py`: plan builders `:459-507`, `validate_payload` `:560`, closed-day guard `:622` (keyed to the 18Z NBS run, `:224`).
- `/home/jon/breezy/src/breezy/ingest/nbm_quantile_transport.py:97-103,316-324` is a working S3-then-NOMADS pattern to copy for HRRR and NDFD.

Sources: [arXiv 2609.23969](https://arxiv.org/html/2609.23969), [IEM MOS archive](https://mesonet.agron.iastate.edu/mos/), [MDL LAMP archives](https://lamp.mdl.nws.noaa.gov/lamp/Data/archives/), [LAMP v2.7 notice](https://www.weather.gov/media/notification/pdf_2025/scn25-62_lampglmp_v2.7.pdf), [NAM MOS retirement SCN 26-47](https://www.weather.gov/media/notification/pdf_2026/SCN26-47_Updated_Retire_NAM_SREF_HREF_HiresW_NAM_MOS.aab.pdf), [RRFS implementation SCN 26-48](https://www.weather.gov/media/notification/pdf_2026/scn26-48_RRFS_and_REFS_Implementation.pdf), [NDFD on AWS](https://registry.opendata.aws/noaa-ndfd/), [GFS MOS timing](https://vlab.noaa.gov/web/mdl/short-range-gfs-mos).