# Settlement Bucket Gate Pre-Registration

Registered at: 2026-08-25T00:00:00Z

## Question

For each Breezy `polymarket_us` settlement city and climate day, does the
METAR-derived daily maximum temperature fall in the same venue temperature bucket
as the final official NWS CLI daily maximum temperature?

This is an offline settlement-alignment gate only. It does not use market prices,
orders, fills, PnL, credentials, or live Polymarket calls.

## Venue Bucket Grammar

The venue bucket grammar is derived only from captured JSON already stored under
`docs/evidence/venue/polymarket_us/raw/`.

Captured high-temperature market slugs and titles use:

- Lower tail: `ltNf`, displayed as `N-1 or below`.
- Interior bucket: `gteNltN+1f`, displayed as `N to N+1`.
- Upper tail: `gteNf`, displayed as `N or above`.

Because settlement is the NWS CLI daily maximum, an integer Fahrenheit value, the
registered settlement bucket interpretation is:

- Lower tail: values `< N`.
- Interior bucket: integer values `N` and `N+1`.
- Upper tail: values `>= N`.

The captured ladders have two-degree interior buckets and two-degree spacing.
They are not a fixed absolute integer lattice in the captures: the lower anchor
varies by event/day, so historical bucket boundaries are not observed.

## Historical Reconstruction Assumption

The 2021-01-01 through 2025-12-31 historical venue ladders are not observed.
The primary evaluation therefore reconstructs an infinite two-degree Fahrenheit
bucket lattice and evaluates sensitivity to lattice phase across the full
two-degree period.

For phase offset `p`, the bucket id for a value `x` is:

`floor((x - p) / 2.0)`

Both CLI and METAR values use the same `p`. Agreement means the two bucket ids
are identical.

The reported phase sweep is `p = 0.0, 0.1, ..., 1.9`. No phase may be selected
or emphasized based on post-hoc agreement. The total gate passes only if every
reported phase passes.

## Data Sources

Labels: historical IEM AFOS raw NWS text archive cache for `CLI{cli_location}`,
parsed through the existing loading and parsing functions in
`scripts/analysis/settlement_alignment_study.py`. Only final CLI products are
eligible; if multiple final records exist for a station/day, the latest final is
used.

Intraday observations: historical IEM ASOS archive cache using raw `metar` text
and UTC `valid` timestamps, loaded through the existing
`settlement_alignment_study.py` paths. Only raw METAR instantaneous
`TsnTTTsnTdTdTd` groups are eligible.

Catalog validation: before historical labels are trusted, overlapping final
Breezy `NwsClimateDay` records read from the configured local catalog must agree
with the IEM CLI archive labels. Any mismatch halts the gate.

## Sites

The study includes all current `polymarket_us` registry pairs returned by
`breezy.registry.sites.default_registry()`: NYC, SFO, MIA, MDW, and LAX.
Station identity is read from the registry and is never inferred from city name.

## Climate-Day Rule

METAR observations are assigned to climate days only with
`breezy.normalize.climate_day.climate_day_for_instant(instant,
std_utc_offset_hours)`, where `std_utc_offset_hours` comes from Breezy's site
registry. No UTC-date assignment and no DST-aware civil calendar assignment is
allowed.

## Temperature Rule

METAR daily maximum is the maximum half-up whole Fahrenheit temperature derived
from raw instantaneous `T` groups:

`whole_f = floor((celsius_tenths / 10) * 9 / 5 + 32 + 0.5)`

CLI daily maximum is the final CLI `tmax_f` integer.

## Case Definition

One evaluated case is `(city, climate_day, phase)` where:

1. A final CLI label exists for `(city, climate_day)` and `tmax_f` is
   non-sentinel.
2. At least one raw METAR instantaneous `T` group exists inside that Breezy
   climate day.
3. The phase is one of the preregistered sweep offsets.

The case is a bucket agreement when `bucket(cli_tmax_f, phase)` equals
`bucket(metar_rounded_max_f, phase)`. It is a miss otherwise. If the METAR bucket
id is less than the CLI bucket id, the miss direction is `METAR below CLI`; if it
is greater, the miss direction is `METAR above CLI`.

## Ties And Edges

Bucket edges are lower-inclusive and upper-exclusive under the formula above.
An exact edge value belongs to the bucket that starts at that edge. This is
applied identically to CLI and METAR values. There is no tolerance band and no
post-hoc edge adjustment.

Distance to the nearest real ladder edge is computed from the CLI value and the
same phase offset:

`min((cli_tmax_f - p) mod 2.0, 2.0 - ((cli_tmax_f - p) mod 2.0))`

## Date Window

Historical study window: 2021-01-01 through 2025-12-31 inclusive.

## Minimum Sample Count

A per-city verdict requires at least 1,000 evaluated city-days for every phase.
The total verdict requires at least 5,000 evaluated city-days for every phase.

If a city or total has fewer eligible city-days, its verdict is `FAIL:
insufficient sample`.

## Pass Threshold

The registered pass threshold is a Wilson 95% lower confidence bound strictly
greater than `0.9900` for the bucket-agreement rate.

Per-city pass: every phase must meet the per-city minimum sample count and have
Wilson 95% lower bound `> 0.9900`.

Total pass: every phase must meet the total minimum sample count and have Wilson
95% lower bound `> 0.9900`.

Phase 2 passes only if all five per-city verdicts and the total verdict pass at
every preregistered phase. If any phase fails, Phase 2 fails.

## Drop Reasons

The study drops and counts:

- `missing_cli_final`: no final CLI product/record for the climate day.
- `cli_sentinel`: final CLI tmax has a sentinel value.
- `missing_metar_t_group`: no instantaneous raw METAR `T` group in the climate
  day.
- `archive_parse_error`: CLI or METAR archive record could not be parsed under
  the existing registered rules.
- `validation_unavailable`: no overlapping Breezy catalog finals were available.
- `validation_mismatch`: IEM CLI archive disagreed with overlapping Breezy final.

## Reporting

The evidence report will include, for each city and total, bucket-agreement rate,
Wilson 95% lower bound, eligible city-day count, verdict, and miss direction
counts for every phase. It will also report agreement by CLI distance to the
nearest reconstructed bucket edge.
