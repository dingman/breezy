# Settlement-Alignment Study Pre-Registration

Registered at: 2026-08-24T19:24:58Z

## Question

For each Breezy settlement city and climate day, when the intraday METAR
instantaneous temperature running maximum has reached an integer threshold `X`,
how often does the final NWS CLI daily climate report for the same station and
climate day report `tmax_f >= X`?

This is an offline settlement-alignment study only. It will not read market
data, prices, orders, fills, PnL, or simulate trades.

## Data Sources

Labels: IEM raw NWS text archive via `/cgi-bin/afos/retrieve.py`, PIL
`CLI{cli_location}`, parsed as verbatim CLI text with Breezy's existing
`breezy.normalize.cli_parse.parse_cli_product` and final/preliminary
classification from `breezy.normalize.classify.classify_issuance`.

Intraday observations: IEM ASOS archive via `/cgi-bin/request/asos.py`, using
`data=metar`, routine and special reports, UTC timestamps, and explicit station
IDs mapped from Breezy registry ICAO to IEM ASOS IDs.

Validation bridge: before historical analysis is trusted, IEM final CLI labels
must match overlapping final Breezy `NwsClimateDay` records read from the
operator-supplied Breezy catalog with `breezy.persistence.catalog`. Any mismatch
halts the study unless it is a sentinel/drop reason shared by both sources.

## Sites

Study sites are the current `polymarket_us` registry pairs from
`breezy.registry.sites.default_registry()`: NYC, SFO, MIA, MDW, and LAX. Station
identity is read from the registry; no station is derived from another station.
IEM ASOS station IDs are mapped explicitly as `KNYC -> NYC`, `KSFO -> SFO`,
`KMIA -> MIA`, `KMDW -> MDW`, `KLAX -> LAX`.

## Climate-Day Rule

METAR observations are assigned to climate days only with
`breezy.normalize.climate_day.climate_day_for_instant(instant,
std_utc_offset_hours)`, where `std_utc_offset_hours` is read from
`breezy.registry.sites`. No `ZoneInfo`, DST-aware local clock, or UTC-date
assignment is allowed.

## Temperature Rule

Only raw METAR instantaneous `TsnTTTsnTdTdTd` remark groups are eligible. The
study ignores METAR API convenience temperature fields and ignores 6-hour
`1xxxx` and 24-hour `4xxxx` summary groups.

The Celsius-to-Fahrenheit whole-degree rule is:

`whole_f = floor((celsius_tenths / 10) * 9 / 5 + 32 + 0.5)`

All study hits and margins use that rounded whole-degree value. The study will
also count outcomes sensitive to rounding by recomputing the crossing predicate
with the unrounded Fahrenheit running maximum.

## Hit Definition

One evaluated case is `(city, climate_day, X)` where:

1. The final settlement-grade CLI label for `(city, climate_day)` exists and has
   non-sentinel `tmax_f`.
2. At least one raw METAR instantaneous `T` group exists inside that climate day.
3. The rounded intraday METAR running maximum reaches `X`.
4. `X` is one of the four integer thresholds immediately below or equal to the
   rounded running maximum: margins `0F`, `1F`, `2F`, or `>=3F`.

The case is a hit when `final_cli_tmax_f >= X`. It is a miss when
`final_cli_tmax_f < X`.

## Clearance-Margin Buckets

Clearance margin is `rounded_metar_running_max_f - X` at the end of the climate
day.

Buckets are:

- `0-1F`: margin `0`
- `1-2F`: margin `1`
- `2-3F`: margin `2`
- `3F+`: margin `>= 3`

Only the four thresholds above are evaluated per eligible city/day so that
high-clearance days do not overwhelm the sample with trivial low thresholds.

## Date Window

Historical study window: 2025-06-01 through 2025-08-31 inclusive.

Archive-validation overlap window: every final Breezy `NwsClimateDay` available
in the configured local catalog at analysis time.

## Minimum Sample Count

A per-city verdict requires at least 80 evaluated `(city, climate_day, X)` cases.
If a city has fewer than 80 cases after drops, its verdict is `NO-GO:
insufficient sample`.

## Break-Even And GO Threshold

Entry-price assumption: buy YES at 90 cents.

Reason: the strategy under consideration is a late intraday confirmation trade
after a METAR running maximum already reaches a threshold, so a high entry price
is the conservative use case to test. Ignoring fees and slippage, break-even hit
rate is `0.90`.

GO threshold: for each city, the Wilson 95% lower confidence bound for the hit
rate must be strictly greater than `0.90`, and the city must meet the minimum
sample count. Otherwise the city verdict is NO-GO.

## Drop Reasons

The study drops and counts:

- `missing_cli_final`: no final CLI product/record.
- `cli_sentinel`: final CLI tmax has sentinel `M`, `T`, `MS`, or `MB`.
- `missing_metar_t_group`: no instantaneous raw METAR `T` group in the climate day.
- `archive_parse_error`: CLI or METAR archive record could not be parsed under
  the registered rules.
- `validation_unavailable`: no overlapping Breezy catalog finals were available.
- `validation_mismatch`: IEM CLI archive disagreed with overlapping Breezy final.

## Disagreement Classification

Every miss is written as a case-file row with source citations and classified as
one of: `C->F rounding`, `post-hoc correction`, `day-boundary`,
`station mismatch`, `sentinel`, or `unexplained`. If the script cannot prove one
of the named causes from the records it has, the cause remains `unexplained`.
