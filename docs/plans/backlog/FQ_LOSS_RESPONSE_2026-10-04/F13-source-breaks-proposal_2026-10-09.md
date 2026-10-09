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

## Correction after the draft build (2026-10-09 evening; mle-reviewer, read-only)

**The claim "observed ⊆ proposed" was false.** The full `--draft-scratch` build (5 stations, 2021-01-01..2026-06-30, EXIT=0) also observed an NBP break on **2026-01-01**. That break is a **builder bug**, not an NBM change:
- `nbp_version_breaks` (`multisource_blend_inputs_report.py:69-76`) compares each row with the station's previous row, across gaps.
- KNYC has no 2025 rows (`obs_excluded_station_years`). Its v4.2 row on 2024-12-31 is therefore followed directly by a v4.3 row on 2026-01-01.
- A fix is in progress (TDD): breaks are counted only between consecutive climate days. **Re-run the draft build after the fix merges, before the freeze.**

**`mos_coverage_gap_days` = 15** is 5 stations × 2020-12-29..31. The MOS runtime lookback reaches 3 days before the window, but the archive starts on 2021-01-01. This is benign: it touches only the first rows of 2021. It is **accepted, not backfilled.** The 2026 H1 backfill is confirmed read.

**2022-08-11 (PFM LOT layout).** The builder detects only LAMP and NBP breaks, so this break is unobservable by design. Keep it, labelled a **manual known-break** with its ILZ104 provenance. Pinning it is conservative, because fold splitting only gets finer.

**Recommended list (unchanged):** `["2022-08-11","2023-01-18","2024-05-15","2024-05-16","2025-05-28","2026-03-29","2026-03-30","2026-03-31","2026-05-06"]`. Do not add 2026-01-01.

**Re-run after the fix (merge c34f1417, 2026-10-09).** The full `--draft-scratch` build ran with EXIT=0 in 182 s and finished with status complete. It observed:

- lamp: 2026-03-29, 2026-03-30, 2026-03-31
- nbp_versions: 2023-01-18, 2024-05-15, 2024-05-16, 2025-05-28, 2026-05-06
- mos_coverage_gap_days: 15 (benign; see above)

**Observed is now a subset of the recommended list.** The only proposed date the build does not observe is 2022-08-11, which is the manual PFM break. Open items 1 and 7 are closed. What remains for the freeze (on or after 10-21): the peer review of this list, then the freeze procedure.

**Peer review (trading-bot-architect, 2026-10-09): READY 90/100.**

The list is correct and complete under PIN-R7 (`F13-phaseA-pin-proposals_r3.md:47`).

**Guard behaviour.** `check_breaks_pinned` (`multisource_blend_pin_guards.py:116-127`) refuses only when a date is observed but not pinned (`observed - pinned`). A date that is pinned but not observed, such as 2022-08-11, is therefore accepted.

**Fold behaviour.** `build_folds` (`multisource_blend_folds.py:93-111`) moves the 1-day cluster segments (05-15/16 and 03-29..31) to `excluded`. It does not crash on them.

**Freeze-commit conditions:**
1. Record 2022-08-11 as a manual known-break, citing its ILZ104 provenance.
2. Re-run `--draft-scratch` at the freeze if any code or archive has changed since c34f1417. The run must give EXIT=0 and `observed ⊆ pinned`.
3. Holdout boundary: checked by the coordinator. `DEFAULT_SPLITS.holdout_start` is 2026-07-01 (`nbp_calibration.py:277`), the day after the build window ends on 2026-06-30. No pre-holdout days are left uncovered.
