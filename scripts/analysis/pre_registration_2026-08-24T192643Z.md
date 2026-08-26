# Settlement-Alignment Study Pre-Registration

Registered at: 2026-08-24T19:26:43Z

## Question

For each Breezy `polymarket_us` settlement city and climate day, when the
running maximum of intraday raw METAR instantaneous `T`-group observations
reached integer threshold `X`, did the final NWS CLI daily climate report for
the same station and same climate day report `tmax_f >= X`?

This is an offline settlement-alignment study only. It does not use market
data, prices, orders, fills, PnL, or simulate trades.

## Data Sources

Labels: IEM raw NWS text archive via AFOS product retrieval for `CLI{cli_location}`.
Products are parsed as raw CLI text with Breezy's existing parser/classifier.
Only final settlement-grade CLI products are eligible; if multiple finals exist
for the same station/day, the superseding latest final record is used.

Intraday observations: IEM ASOS archive via `/cgi-bin/request/asos.py`, using
raw `metar` text and `valid` UTC timestamps. Station identity is read from
Breezy's registry and mapped explicitly from ICAO to the IEM ASOS station id:
`KNYC -> NYC`, `KSFO -> SFO`, `KMIA -> MIA`, `KMDW -> MDW`, `KLAX -> LAX`.

Validation bridge: before historical labels are trusted, IEM final CLI labels
must agree with overlapping final Breezy `NwsClimateDay` records read from the
local catalog through `breezy.persistence.catalog`. If any overlapping final
record disagrees, the historical study halts and reports the discrepancy.

## Sites

The study includes all current `polymarket_us` registry pairs returned by
`breezy.registry.sites.default_registry()`: NYC, SFO, MIA, MDW, and LAX.
Station identity is never derived from nearby airports or city names.

## Climate-Day Rule

METAR observations are assigned to climate days only with
`breezy.normalize.climate_day.climate_day_for_instant(instant,
std_utc_offset_hours)`, where `std_utc_offset_hours` is read from
`breezy.registry.sites`. No `ZoneInfo`, DST-aware local clock, or UTC-date
assignment is allowed.

## Temperature Rule

Only raw METAR instantaneous `TsnTTTsnTdTdTd` remark groups are eligible for the
running maximum. API convenience temperature fields and METAR 6-hour `1xxxx` or
24-hour `4xxxx` summary groups are ignored.

The Celsius-to-Fahrenheit whole-degree rule is half-up rounding:

`whole_f = floor((celsius_tenths / 10) * 9 / 5 + 32 + 0.5)`

All hit and margin statistics use that rounded whole-degree value. The study
also counts rounding-sensitive evaluated cases: cases where changing from
unrounded Fahrenheit to rounded whole-degree Fahrenheit changes whether `X` was
reached.

## Hit Definition

One evaluated case is `(city, climate_day, X)` where:

1. A final CLI label exists for `(city, climate_day)` and `tmax_f` is
   non-sentinel.
2. At least one raw METAR instantaneous `T` group exists inside that Breezy
   climate day.
3. The rounded intraday METAR running maximum reaches `X`.
4. `X` is one of the four integer thresholds immediately below or equal to the
   rounded running maximum: margins `0F`, `1F`, `2F`, or `>=3F`.

The case is a hit when `final_cli_tmax_f >= X`. It is a miss when
`final_cli_tmax_f < X`.

## Clearance-Margin Buckets

Clearance margin is `rounded_metar_running_max_f - X` at the end of the climate
day. Buckets are:

- `0-1F`: margin `0`
- `1-2F`: margin `1`
- `2-3F`: margin `2`
- `3F+`: margin `>= 3`

Only these four thresholds are evaluated per eligible city/day so high-clearance
days do not overwhelm the sample with trivial low thresholds.

## Date Window

Historical study window: 2021-01-01 through 2025-12-31 inclusive.

Archive-validation overlap window: every final Breezy `NwsClimateDay` available
in the configured local catalog at analysis time.

## Minimum Sample Count

A per-city verdict requires at least 1,000 evaluated `(city, climate_day, X)`
cases. If a city has fewer than 1,000 cases after drops, its verdict is
`NO-GO: insufficient sample`.

## Break-Even And GO Threshold

Primary entry-price assumption: buy YES at 99 cents.

Reason: the user supplied break-even rates for both 97 cent and 99 cent entries;
the 99 cent entry is the stricter gate and best represents the late, crowded
"already observed" trade where little edge remains after public information is
available. Ignoring fees and slippage, the preregistered break-even hit rate is
`0.9906`.

GO threshold: for each city, the Wilson 95% lower confidence bound for the hit
rate must be strictly greater than `0.9906`, and the city must meet the minimum
sample count. Otherwise the city verdict is NO-GO.

The 97 cent break-even rate, `0.9760`, is reported as a secondary reference only
and cannot upgrade a city from NO-GO to GO under this preregistration.

## Drop Reasons

The study drops and counts:

- `missing_cli_final`: no final CLI product/record for the climate day.
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
of the named causes from available records, the cause remains `unexplained`.
