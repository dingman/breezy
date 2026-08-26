# Settlement Bucket Guard-Band Follow-Up Pre-Registration

Registered at: 2026-08-26T00:00:00Z

## Status

This is **not** the original settlement bucket gate pre-registration. It is an
explicitly **post-hoc, exploratory follow-up** to the failed pre-registered
bucket-alignment gate in
`docs/evidence/settlement_bucket_gate_2026-08-25.md`.

The guard-band idea was motivated by already-seen data in
`docs/evidence/settlement_alignment_diagnosis_2026-08-25.md`, where a
threshold-distance cut selected after seeing the failure made the raw threshold
gate pass. Therefore this analysis can generate a hypothesis, but it cannot
license trading without out-of-sample confirmation.

## Question

If city-days whose unrounded METAR-derived daily maximum is close to a
reconstructed 2 F venue bucket edge are excluded, does same-bucket agreement
between final CLI `tmax_f` and rounded METAR daily maximum pass the original
bucket gate across all cities and all lattice phases?

## Guard-Band Rule

For each `(city, climate_day, phase)` bucket case, compute the distance from the
unrounded METAR-derived daily maximum to the nearest reconstructed 2 F bucket
edge under the same phase offset:

`min((metar_unrounded_max_f - p) mod 2.0, 2.0 - ((metar_unrounded_max_f - p) mod 2.0))`

For positive guard bands, retain only cases with distance strictly greater than
the guard band. A guard band of `0.0 F` is the no-guard baseline and retains all
eligible bucket cases from the original gate.

## Sweep

The guard-band sweep is:

- `0.0 F`
- `0.25 F`
- `0.5 F`
- `0.75 F`
- `1.0 F`

The lattice phase sweep remains the original pre-registered bucket-gate sweep:
`0.0, 0.1, ..., 1.9`.

No guard band or phase may be selected or emphasized because it passes. The
report must show the whole sweep.

## Data, Bucket, And Sample Rules

This follow-up reuses the existing offline loading, parsing, validation, bucket
and Wilson-confidence functions from `scripts/analysis/settlement_bucket_gate.py`
and `scripts/analysis/settlement_alignment_study.py`.

It uses the same historical window, sites, cache-only IEM archive inputs,
catalog-validation bridge, reconstructed bucket formula, minimum samples and
pass threshold as `docs/evidence/settlement_bucket_gate_prereg_2026-08-25.md`:

- Historical window: 2021-01-01 through 2025-12-31 inclusive.
- Cities: NYC, SFO, MIA, MDW and LAX from the Breezy `polymarket_us` registry.
- Cache-only archives; no Polymarket calls, credentials, prices or orders.
- Bucket id: `floor((value_f - phase) / 2.0)`.
- Agreement: final CLI `tmax_f` bucket equals rounded METAR daily maximum
  bucket.
- Pass threshold: Wilson 95% lower confidence bound strictly greater than
  `0.9900`.
- Minimum sample: at least 1,000 retained city-day bucket cases per city and
  5,000 retained city-day bucket cases total at every phase.
- The gate for a guard band passes only if every city and the total pass at
  every phase.

## Retention Cost

Retention is a primary result, not a secondary diagnostic. For every
`(guard_band, phase, city)` cell and for totals, the report must include:

- retained bucket cases
- retained fraction versus the original eligible bucket cases
- retained city-day fraction
- agreement rate
- Wilson 95% lower bound
- miss direction split: METAR bucket below CLI versus METAR bucket above CLI

The headline per guard band must state whether it passes and the worst-phase
retention cost as:

`passes/fails at guard X, retaining Y% of city-days and Z% of threshold cases`

Because this follow-up excludes whole city-days for the bucket gate, threshold
case retention is computed as the fraction of the four diagnostic threshold
cases per retained city-day that would remain addressable. It is therefore
reported explicitly even when numerically equal to city-day retention.

## Falsification

This exploratory hypothesis is falsified for this archive window if no tested
guard band satisfies all of these conditions:

1. every city and total passes the Wilson threshold at every phase;
2. every city and total satisfies the original minimum-sample rules at every
   phase;
3. the retained city-day and threshold-case fractions are large enough to avoid
   the REQ-SETTLE-03a/R6a failure mode where `BOUNDARY_UNRESOLVED` silently
   consumes the addressable market.

The third condition is intentionally not converted into a pass/fail constant in
this exploratory document. The report must show the retention cost plainly so a
future trading-design decision cannot hide behind a green alignment statistic.

## Out-Of-Sample Requirement

Before any guard-band result can be relied on for trading, it must be confirmed
out of sample against venue-observed historical or future bucket ladders and
settlement outcomes. This archive does **not** observe the venue's real
2021-2025 bucket ladders; it reconstructs an infinite 2 F lattice and sweeps
phase offsets. A passing reconstructed-lattice result would not determine the
real venue boundary operator, real ladder anchors, or real settlement behavior.
