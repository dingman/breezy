# F13 `source_breaks` proposal (PIN-R7), 2026-10-09: PROPOSAL, not pinned

This proposal was derived read-only from archive and provenance files only, never from residuals or CRPS. It is pinned only at the C1 freeze (on or after about 2026-10-21), after peer review and after a `--draft-scratch` build confirms `source_breaks_observed`. Never edit `F13_prereg_blend_v1.json` outside the freeze procedure.

## Proposed list

`["2022-08-11","2023-01-18","2024-05-15","2024-05-16","2025-05-28","2026-03-29","2026-03-30","2026-03-31","2026-05-06"]`

| Date | Source | Evidence | Observed by the builder |
|---|---|---|---|
| 2022-08-11 | PFM layout, LOT (KMDW) | ILZ104: row order changed from UTC-over-CDT to CDT/UTC, and labels from MAX/MIN to Max/Min, at the 13:15Z entry (key `0808a737a022…`) | No |
| 2023-01-18 | NBM v4.0→v4.1 | First 4.1 header is cycle 2023-01-17 13Z (`nbp5/2023/01/nbp_20230117_13z.parquet`) | Yes |
| 2024-05-15 | NBM v4.1→v4.2 (KLAX, KSFO) | First 4.2 header is 05-14 19Z. The 05-15 01Z `last_modified` of 16:53Z falls between the EST/CST and PST anchors | Yes |
| 2024-05-16 | NBM v4.2 (all stations) | Same evidence | Yes |
| 2025-05-28 | NBM v4.2→v4.3 | First 4.3 header is 05-27 13Z | Yes |
| 2026-03-29 to 2026-03-31 | LAMP MDL↔LAV basis flips | 73 h MDL gap from 03-26 23:30Z to 03-30 00:30Z (`us-lamp-mdl/coverage.json`, `lampbf_monthly2.json` missing_runs) | Yes |
| 2026-05-06 | NBM v4.3→v5.0 | 5.0 header at 05-04 13Z; flip back to 4.3 at 05-05 01Z; 05-04 13Z `last_modified` is 05-05 18:08Z | Yes |

A read-only simulation of the builder over the full window gives observed ⊆ proposed. The only extra date is 2022-08-11 (PFM).

## Open items for the freeze review

1. **Draft build.** Confirm the observed set with `--draft-scratch` before freezing. A dropped station-day can only move an NBP break later; the guard refuses loudly if so.
2. **MOS model changes:** none considered. Every GFS MOS row is GFS, with the same header in every year.
3. **LAMP version changes:** none considered. The header is constant across 49,926 payloads.
4. **KLAX PFM zone change, CAZ041→CAZ366 on 2024-05-09.** Proposed: exclude it. It is not a layout change, and the parser never keys on zone.
5. **NBM dates come from provenance only.** Never take them from the code table `VERSION_BREAKS` (`nbp_lag_census.py:60`): its dates are cycle dates, and five cycles disagree with it.
6. **Same-day flips** (2024-05-15, 2026-03-30) are artefacts of availability or gaps. They create 1–2-day segments, which `build_folds` excludes.
7. **Coverage gap: there is no GFS MOS archive for 2026-01..06.** The GFS leg backfills complete years only (`_last_complete_year`). The builder counts the gap as `mos_coverage_gap_days`. Decide before the freeze whether to backfill 2026 H1 (a monthly leg) or accept the gap.

**Update to item 7 (2026-10-09 ~00:05Z):**
- Done: GFS MOS 2026-01-01..2026-07-01 (end exclusive) was fetched into the iem-mos cache via `iem_mos_backfill.py --start/--end`. That is 5 stations × 15,204 rows, rc 0. Report: `quarantine/run-reports-2026-10-08/gfs_mos_2026h1_1009.json`.
- Still to check: whether the builder reads partial-range keys. The `--draft-scratch` build's `mos_coverage_gap_days` will show it.
