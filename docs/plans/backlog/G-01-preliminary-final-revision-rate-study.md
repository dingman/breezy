# G-01 Preliminary/Final Tmax Revision-Rate Study

Date: 2026-08-26

## Objective

Measure how often an NWS CLI preliminary daily-maximum-temperature value is
revised by the later final CLI product for Breezy's live venue sites.

This addresses DOM-11 in `docs/plans/TRADING_ENABLEMENT_REVIEW.md`: after the
preliminary CLI product publishes, the stated `tmax` is no longer a lower bound.
The remaining truth risk for a post-preliminary trade is the probability that a
later final product changes that `tmax`.

## Scope

In scope:

- `polymarket_us:{NYC,SFO,MIA,MDW,LAX}` settlement sites from the registry.
- Existing `NwsClimateDay` records from the live Parquet catalog at
  `/home/jon/.local/share/breezy/catalog`.
- Per-site paired preliminary/final city-days.
- `tmax_f` only.
- A pre-registered PASS/FAIL/UNDERPOWERED verdict against the pre-registered
  threshold.

Out of scope:

- Runtime or adapter changes.
- Writes to the live Parquet catalog or SQLite state DB.
- Post-hoc threshold selection, guard-band sweeps, or exploratory threshold
  tuning.
- Settlement-alignment against METAR or venue settlement results.

## Read-Only Catalog Protocol

The live catalog is a production data source and may be written by the running
systemd collector. The study must:

1. Treat `/home/jon/.local/share/breezy/catalog` as read-only.
2. Open existing station catalog roots directly with `ParquetDataCatalog(path=...)`.
3. Avoid `open_station_catalog(...)` during analysis because it creates missing
   directories.
4. Never write, lock, compact, delete, or repair files under the catalog base.
5. Stop and report blocked if ordinary read access appears unsafe.

## Method

1. Write the pre-registration document before reading any catalog data.
2. Inspect the catalog readers and selection code:
   - `src/breezy/persistence/catalog.py`
   - `src/breezy/domain/selection.py`
   - `src/breezy/domain/nws_climate_day.py`
3. Implement `scripts/analysis/preliminary_final_revision_rate_study.py`.
4. For each site:
   - read all `NwsClimateDay` records from the existing station catalog root;
   - keep only records whose `station` equals the registry `cli_location`;
   - group by `climate_day`;
   - choose the latest preliminary before the first final arrival;
   - choose the latest final currently present;
   - include the day only when both chosen records have non-null `tmax_f`;
   - count a revision when preliminary `tmax_f != final tmax_f`.
5. Compute per-site revision rate and Wilson 95% lower/upper bounds.
   - Reuse `wilson_lower_bound` from the existing settlement-alignment study.
   - Compute the upper bound as `1 - wilson_lower_bound(non_revisions, n)`.
6. Write evidence to
   `docs/evidence/preliminary_final_revision_2026-08-26.md`.
7. Run focused lint/type checks for the added script.

## Expected Outcome

Continuous collection was re-established only on 2026-08-24 after catalog loss,
so the live-catalog sample is expected to be small. If any site has fewer than
the pre-registered sample floor, the primary verdict must be UNDERPOWERED, not
PASS.

Historical IEM archive data may be used in a later extension, but it must be
kept separate from live-captured catalog data and documented with exact
provenance. This first execution is live-catalog only unless explicitly run with
an archive mode added and documented separately.

## Deliverables

- `docs/plans/backlog/G-01-preliminary-final-revision-rate-study.md`
- `docs/evidence/preliminary_final_revision_prereg_2026-08-26.md`
- `scripts/analysis/preliminary_final_revision_rate_study.py`
- `docs/evidence/preliminary_final_revision_2026-08-26.md`

## Verification

Required evidence in the final report:

- command used to run the study;
- catalog path and station roots inspected;
- per-site paired sample size `N`;
- per-site tmax revision count, revision rate, and Wilson 95% bounds;
- primary verdict against the pre-registered threshold;
- limitations, especially underpowered live sample size if observed;
- exit codes for focused `uv run ruff check ...` and `uv run mypy ...` checks.
