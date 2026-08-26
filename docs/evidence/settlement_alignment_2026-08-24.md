# Settlement-Alignment Study Evidence

Generated at: 2026-08-24T19:35:35+00:00
Pre-registration: `scripts/analysis/pre_registration_2026-08-24T192643Z.md`
Command: `python scripts/analysis/settlement_alignment_study.py`
Catalog base: `None`
Cache dir: `scripts/analysis/cache/settlement_alignment`

## Registered Rules

- Historical window: 2021-01-01 through 2025-12-31
- Primary GO threshold: Wilson 95% lower bound > 0.9906
- Secondary 97c reference break-even: 0.9760
- Minimum per-city sample count: 1000
- C->F rounding: half-up whole Fahrenheit from raw METAR T-group Celsius tenths
- Margin buckets: 0-1F, 1-2F, 2-3F, 3F+

## Archive Validation Bridge

Status: **blocked: validation_unavailable**
Checked overlapping final records: 0
Mismatches: 0

- BREEZY_CATALOG_BASE/--catalog-base was not supplied

## Study Status

BLOCKED. Historical hit-rate analysis was not run because the archive-validation bridge did not pass.

## Per-City Statistics

Not computed.

## Per-Margin Bucket Statistics

Not computed.

## GO / NO-GO Verdicts

No city receives a GO verdict because the validation bridge did not pass.

## Drop Counts

- validation_unavailable: 1

## Disagreement Case Files

No disagreement cases were computed.

## Parse Issues

- pyiem version available to backfill extra: 1.27.0
