# CLI-Basis Candidate #2 — Archive-Side Adverse-Selection Proxy — Pre-Registration

Registered at: 2026-09-02T062000Z

**This document is written BEFORE the per-season outcome below has been
computed.** Only plumbing (that `pmr_climatology_study.season_for` classifies
every climate day in the archive window into one of four seasons with no
`KeyError`, and that the admissible-hour `SetupCase` population from
`cli_basis_hourly_profile_study` is non-empty per station) was checked first.

## Why this statistic

Task 2's concern, stated precisely: the archive gives an UNCONDITIONAL
`P(win | setup)` over every admissible-hour setup in five years of history.
Breezy would only ever TRADE the subset of setups the venue actually offers
at `<= $0.05` in size. If the venue offers cheaply precisely on the days it
is most confident the tail is dead — i.e., days whose TRUE basis-crossing
probability is already low for reasons visible to a counterparty — then the
unconditional archive rate does not describe the tradeable population, and
the edge could be illusory even though the archive PASSES. Order-book
history does not exist before 2026-09-01 (verified, hard constraint), so
`P(win | setup, offered <= 0.05)` cannot be measured directly today.

What CAN be measured from the archive alone: whether the admissible-hour
setup population is internally HOMOGENEOUS or whether it decomposes into
sub-populations with materially different basis-crossing rates along an axis
a counterparty could plausibly observe or infer WITHOUT the archive (season
is such an axis — a counterparty knows the calendar). If the setup
population's rate is stable across seasons, one plausible and CHEAP
selection channel is not available to a counterparty; if it varies sharply,
this is affirmative, archive-only evidence that a selection channel exists
in principle, though not proof the venue actually uses it (no prices exist
to confirm mechanism — see "Say plainly" below).

## Statistic (fixed in advance)

For each dense station `S` and each meteorological season
`season_for(climate_day) in {DJF, MAM, JJA, SON}` (reused verbatim, the
repo's only per-day season classifier), restricted to the SAME admissible
population the corrected headline already uses
(`cli_basis_hourly_profile_study.filter_cases_by_admissible_hours`, i.e.
local-standard hour `>= 17`, margins `{1, 2}` pooled):

    P(CLI_final_tmax_f(S, d) >= R_h(S, d) + m) | season_for(d) = season

Reported per `(station, season)` cell: `n`, `k`, rate, Wilson 95% bounds, and
the season's SHARE of that station's total admissible-hour setup count
(`n_season / n_station_total`) -- the share matters as much as the rate:
a season with a much lower rate that also holds a much LARGER share of all
setups is the dangerous case (a counterparty who can infer season gets to
selectively offer on the majority of the tradeable flow).

## Bar

No PASS/FAIL bar is registered for this diagnostic -- it does not gate a
GO/NO-GO by itself, it characterizes HETEROGENEITY. The finding is reported
as: **materially heterogeneous** if any season's Wilson 95% interval, at
`n >= 100`, excludes the pooled point estimate (0.1213) from
`cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md`; otherwise
**materially homogeneous**. This is descriptive, not a kill rule -- reported
as `MATERIALLY HETEROGENEOUS` / `MATERIALLY HOMOGENEOUS` / `UNDERPOWERED`
per cell (`n < 100`), never `PASS`/`FAIL`, so it is never mistaken for a
tradeability verdict.

## Power

Admissible only at `n >= 100` per `(station, season)` cell -- same floor as
every other cell in this study family, same reasoning (an underpowered
verdict describes the sample, not the world).

## What this test can and cannot establish, stated before it is run

- It CAN show whether season is a plausible, cheap selection axis available
  to a rational counterparty without any special access to Breezy's own
  data.
- It CANNOT show that the venue actually conditions its offers on season, or
  on anything else -- no price data exists before 2026-09-01 to confirm
  mechanism. A finding of heterogeneity here is evidence the RISK is live,
  not evidence the risk has already materialized in the one resolved LOSS.
- It CANNOT rule out a finer, non-seasonal selection channel (e.g. synoptic
  pattern, fog, marine layer) that this archive does not capture at all. A
  homogeneous finding narrows one channel; it does not clear the family of
  adverse selection in general.

## Null hypothesis — existing capability, checked before writing new code

- `pmr_climatology_study.season_for` -- NATIVE-EXISTS-AND-REUSED verbatim
  via import; the repo's only per-day season classifier
  (`_SEASON_BY_MONTH`, DJF/MAM/JJA/SON).
- `cli_basis_hourly_profile_study.filter_cases_by_admissible_hours` /
  `is_admissible_hour` -- NATIVE-EXISTS-AND-REUSED verbatim via import, so
  this test measures heterogeneity WITHIN the exact population the corrected
  headline already treats as one pool, rather than a different population.
- `cli_basis_setup_win_rate_study.build_setup_cases` / `SetupCase` /
  `DENSE_STATIONS` -- NATIVE-EXISTS-AND-REUSED verbatim via import.
- `k1_cheap_open_settlement.wilson_interval` -- NATIVE-EXISTS-AND-REUSED
  verbatim via import.
- A per-`(station, season)` aggregation of `SetupCase` -- does NOT exist
  upstream (every existing aggregator in this family groups by
  `(station, hour)`, never by season). GENUINE GAP, built as a small, new
  function in `scripts/analysis/cli_basis_adverse_selection_probe.py`,
  re-deriving nothing the pieces above already provide.
