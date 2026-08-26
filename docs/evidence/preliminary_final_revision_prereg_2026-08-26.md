# Preliminary/Final Tmax Revision-Rate Study Pre-Registration

Date: 2026-08-26

This document was written before reading or analyzing the live catalog for this
study.

## Hypothesis

For Breezy's five live Polymarket US daily-maximum-temperature settlement sites,
the NWS CLI preliminary product's `tmax` value is rarely revised by the later
final CLI product.

Operationally, the post-preliminary trade window is acceptable only if each site
has enough paired observations and the Wilson 95% upper confidence bound for the
preliminary-to-final `tmax` revision rate is at or below 5%.

## Population

Primary population:

- live-captured `NwsClimateDay` records in the Parquet catalog rooted at
  `/home/jon/.local/share/breezy/catalog`;
- venue `polymarket_us`;
- cities `NYC`, `SFO`, `MIA`, `MDW`, and `LAX`;
- records whose `station` equals the registry `cli_location` for that city.

The unit of analysis is one paired site and `climate_day`.

## Inclusion Rules

Include a site-day only when all of the following are true:

1. At least one preliminary `NwsClimateDay` record exists for the site-day.
2. At least one final `NwsClimateDay` record exists for the same site-day.
3. The selected preliminary has `tmax_f` present, not a sentinel.
4. The selected final has `tmax_f` present, not a sentinel.
5. The selected preliminary arrived before the first final record for that
   site-day.

Selection rule:

- Preliminary value: latest non-final record by `(ts_init, revision_seq)` before
  the first final arrival for the site-day.
- Final value: latest final record by `(ts_init, revision_seq)` currently present
  in the catalog for the site-day.

## Exclusion Rules

Exclude a site-day when any of the following is true:

- missing station catalog root;
- no preliminary record;
- no final record;
- preliminary `tmax_f` is null/sentinel;
- final `tmax_f` is null/sentinel;
- preliminary is not earlier than the first final;
- record station does not match the registry `cli_location`.

Excluded rows are counted by reason and reported.

## Statistic

For each site:

- `N`: included paired site-days;
- `revisions`: count of included pairs where preliminary `tmax_f != final tmax_f`;
- `revision_rate = revisions / N`;
- Wilson 95% lower bound for the revision rate;
- Wilson 95% upper bound for the revision rate.

The Wilson lower bound must reuse the helper already present in
`scripts/analysis/settlement_alignment_study.py`. The upper bound is computed as:

`1 - wilson_lower_bound(non_revisions, N)`

where `non_revisions = N - revisions`.

## Sample-Size Floor

Minimum powered sample size: `N >= 90` paired site-days per site.

Justification: with zero observed revisions, a Wilson 95% upper bound falls below
5% at about 90 observations. A smaller sample cannot pass the 5% risk threshold
even if no revisions are observed, so reporting PASS below this floor would
overclaim what the data can support.

## PASS/FAIL/UNDERPOWERED Threshold

Per-site verdict:

- `UNDERPOWERED`: `N < 90`.
- `PASS`: `N >= 90` and Wilson 95% upper bound for `revision_rate <= 0.050000`.
- `FAIL`: `N >= 90` and Wilson 95% upper bound for `revision_rate > 0.050000`.

Primary study verdict:

- `PASS`: every site is per-site PASS.
- `FAIL`: every site is powered and at least one site is per-site FAIL.
- `UNDERPOWERED`: at least one site is per-site UNDERPOWERED.

The 5% threshold is intentionally conservative because `tmax` revision is an
upper bound on wrong-truth risk for a post-preliminary trade. A lower realized
trade error rate may be possible when market thresholds are far from the
revision magnitude, but that is not part of this pre-registered study.

## Archive Data Rule

The primary run is live-catalog only. If IEM archive data is used in a later run,
it must be reported separately from live-captured data, with exact URL/date-range
provenance and no mixing into the primary live-catalog verdict.
