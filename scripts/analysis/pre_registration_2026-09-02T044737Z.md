# CLI-Basis Boundary Upper-Tail — Pre-Registration

Registered at: 2026-09-02T04:47:37Z

**This document is written BEFORE any outcome statistic in this study has been
computed.** Plumbing (registry loading, ASOS/CLI archive cache-hit checks, and
one station's CLI-final load) was smoke-tested to confirm the archive is
readable offline with zero network access, per L-1 (validate the null
hypothesis that the needed capability already exists before building
anything new) — no per-cell hit rate, Wilson bound, or PASS/FAIL verdict was
computed or viewed before this file was written.

## Question

Late in the day, a public ASOS running maximum for station `S` says the day's
observed high has "just missed" a venue rung by less than a whole degree. Does
the **official settlement instrument** — the NWS CLI final print — land at or
above the next whole degree often enough that a cheap `>= X` open-upper-tail
buy is executable positive EV against a counterparty anchored on the wrong
(ASOS) instrument?

This is an offline settlement-alignment / climatology study only. It reads no
market data, prices, orders, fills, or PnL, and simulates no trades. It places
no orders and opens no venue connection.

## Statistic (fixed in advance)

For each station `S` in {LAX, MDW, MIA, NYC, SFO} and each local-standard hour
`h` in `17..23`:

    P(CLI_final_tmax_f(S, d) >= R_h(S, d) + 1)

over every station-day `d` in the archive where local-standard hour `h` is
**complete** (has at least one observation, so `R_h` is well-defined and not a
carried-forward gap) and a non-sentinel CLI final exists for `(S, d)`.

`R_h(S, d)` is the ASOS/METAR running-maximum temperature (whole °F, rounded
half-up) for station `S` on climate day `d`, as of the end of local-standard
hour `h`. This is `pmr_climatology_study.build_running_max_days`'s
`running_max_f[h]`, reused verbatim (see "Null hypothesis" below) — a single
forward pass over ascending instants, so no observation after hour `h` can
influence `R_h`, with the accumulator carried across empty hours and reset at
local-standard midnight.

"Local hour" uses each station's **fixed standard-time UTC offset**
(`breezy.registry.sites.ClimateDayWindow.std_utc_offset_hours`, read via
`climate_day_window(venue, city)`), never a DST-following wall clock and never
`ZoneInfo`. This is the same climate-day boundary
`breezy.normalize.climate_day.climate_day_for_instant` uses, and it is
deliberately NOT the venue's settlement-deadline clock
(`SettlementDeadline.settlement_timezone`, which DOES follow DST) — the two
clocks are structurally kept apart in `breezy/registry/sites.py` and this
study must not blur them back together. Because the offset is fixed
year-round, an hour bucket never "moves" across a DST transition; what DOES
move is the wall-clock hour a DST-observing human would call "5pm", which is
irrelevant here since the analysis is standard-time throughout.

In words: given the public tape says the day is still a full degree short of
`R_h + 1` at hour `h`, how often does the official CLI print come in at or
above that next degree anyway?

## Bar (break-even, derived — not copied)

Ask assumption: buy the `>= X` tail at **5 cents** (a "dead tail" ask, per the
mechanism this study tests).

Venue fee: `PolymarketUSFeeModel` charges `theta * C * p * (1 - p)` per fill
(`src/breezy/adapters/polymarket_us/fees.py`, `get_commission`). `theta` is
read per-market from `instrument.info["fee_coefficient"]`
(`_fee_coefficient`) and is NOT a single repo-wide constant — the module's own
docstring gives **theta = 0.06** as the worked example
(`fees.py`, "... contracts at theta = 0.06"). This study uses theta = 0.06 as
the representative coefficient, matching the worked example; a market with a
materially different theta shifts the bar (see "What would make this wrong").

At p = 0.05 (the entry price): fee = `0.06 * 0.05 * 0.95` = `0.00285`.

Tick buffer: one 0.01 tick.

    break-even = ask + fee + tick buffer
               = 0.05 + 0.00285 + 0.01
               = 0.06285

This reproduces the bar given in the task brief (0.06285) from theta = 0.06;
no adjustment is needed.

**PASS bar: a cell (S, h) PASSES only if its Wilson 95% LOWER bound on the
statistic above is >= 0.06285.**

## Power

A cell is **ADMISSIBLE** only if n >= 100 station-days (the count of
station-days entering that cell after drops). A cell below n = 100 is reported
as **UNDERPOWERED**, never as FAIL — an underpowered verdict describes the
sample, not the world (operator standing lesson,
`MEMORY.md: check-what-data-a-blocker-used.md`, citing G-01's own
"UNDERPOWERED, no PASS claim is valid" language in
`docs/evidence/observation_lock_falsification_2026-08-31.md`). n is reported
for every one of the 35 cells regardless of verdict.

## Multiplicity

5 stations x 7 hours (17..23) = 35 cells, tested simultaneously. Handling,
fixed before any cell is inspected:

1. The primary PASS bar (Wilson lower >= 0.06285) is itself conservative
   (a one-sided 95% bound on a small-fee break-even), and is applied
   per-cell without correction as the headline criterion.
2. As a secondary, explicitly more conservative check, this study ALSO
   reports how many cells would still clear a Bonferroni-adjusted 95%/35
   interval, i.e. a two-sided (1 - 0.05/35) = 99.857% Wilson bound
   (z = 2.9848). A cell that clears bar (1) but not bar (2) is flagged, not
   silently dropped.
3. Neither adjustment changes the GO/NO-GO rule below by itself; the
   Bonferroni count is reported as corroborating evidence for how robust a
   GO is to the multiplicity of cells tested.

## Verdict rule (fixed in advance)

- **GO** — at least one ADMISSIBLE (S, h) cell PASSES the primary bar (Wilson
  lower >= 0.06285), AND that cell also clears the Bonferroni-adjusted bound
  in the secondary check (so the GO is not solely an artifact of testing 35
  cells at nominal 95%). Proceed to the live offer-gate scan for that
  cell/station/hour combination.
- **NO-GO** — every ADMISSIBLE cell FAILS the primary bar. The family is dead;
  write it up and stop. (An UNDERPOWERED cell does not count as a FAIL for
  this purpose — see Power.)
- **INCONCLUSIVE** — no cell is ADMISSIBLE (n < 100 everywhere), or the only
  cells that pass the primary bar fail the Bonferroni corroboration (a
  plausible-looking GO that does not survive the conservative check). Report
  as inconclusive, not as GO, and name which cells drove the ambiguity.

## Null hypothesis — existing capability, checked before writing new code

- `scripts/analysis/pmr_climatology_study.py:build_running_max_days`
  (`~line 351` in the FDCR-branch copy ported into this worktree, see below) —
  **NATIVE-EXISTS-AND-REUSED.** Confirmed by reading it: one forward pass over
  ascending `MetarTemperature` rows per climate day, producing
  `running_max_f: tuple[int | None, ...]` indexed by local-standard hour, with
  gap-hours carried forward and the accumulator reset at each climate-day
  boundary. This is exactly `R_h(S, d)`. Reused via import, not
  reimplemented, from a verbatim copy of the function.
- CLI-final and archive loading —
  **NATIVE-EXISTS-AND-REUSED**, `scripts/analysis/pmr_climatology_study.py`'s
  `load_cli_records`/`CliRecord`/`iter_cached_cli_products` (AFOS zip cache,
  finals only) and `scripts/analysis/settlement_alignment_study.py`'s
  `SiteSpec`/`load_sites`/`asos_url`/`afos_url`/`parse_asos_rows`/
  `metar_temperatures`. `settlement_truth_dataset.py` was also read; it uses a
  different, heavier archive layout (digest-verified window zips plus
  `breezy.domain.weather_bucket_facts`, which this worktree's checkout does
  not carry) built for per-day settlement-truth rows with provenance, and is
  a genuine alternative loader but not the smaller fold this study needs —
  the `pmr_climatology_study`/`settlement_alignment_study` pair is the
  narrower, already-proven-working fit and is what this study ports.
- ASOS archive location —
  **NATIVE-EXISTS-AND-REUSED**, not a separate 5-minute-file archive: the "IEM
  ASOS" series `pmr_climatology_study`/`settlement_alignment_study` already
  consume (`asos_url` -> `/cgi-bin/request/asos.py`, `data=metar`) is cached,
  keyed by URL hash, under
  `~/.local/share/breezy/archive/settlement-alignment-cache/` (confirmed
  present and readable with **zero cache misses** for all 5 stations' full
  2021-01-01..2025-12-31 window, and for NYC's CLI-final AFOS zip, in a smoke
  check run before any outcome statistic). `docs/core/RUNBOOK_NWS_COLLECTION.md`
  does not separately document a raw 5-minute-file ASOS archive; the archive
  this repo actually built and validated is this cache, and it is the one
  `pmr_climatology_2026-09-01.md`'s own basis table was generated from.
- Wilson interval — **GENUINE GAP for THIS study's test suite**: existing
  Wilson implementations exist twice in the repo
  (`archive_correction_probe.wilson_interval`,
  `settlement_alignment_study.wilson_lower_bound`), so the FORMULA is reused,
  but this study's own RED-then-GREEN unit tests are written fresh against a
  small local wrapper because the pre-registered bar needs a two-sided
  Bonferroni-adjusted bound (a different `z`) as well as the standard
  one-sided lower bound, which neither existing helper parameterizes.

## Worktree note

This worktree's checked-out commit predates the `feat/data-capture-and-risk`
work that added `scripts/analysis/`, `docs/core/LESSONS.md`, and
`src/breezy/adapters/polymarket_us/`. The five files above were ported
verbatim (git `show <ref>:<path>`, no edits) from `feat/data-capture-and-risk`
into this worktree's `scripts/analysis/` (an explicitly allowed path) because
they are the existing fold this task requires reusing; they import
successfully against this worktree's own `src/breezy` (`normalize`, `domain`,
`persistence`, `registry`) with zero modification, and a smoke check
confirmed all 5 stations' ASOS cache files and NYC's CLI-final AFOS cache are
present with no network access required. `fees.py` and `docs/core/LESSONS.md`
were read via `git show feat/data-capture-and-risk:<path>` (not written to
this worktree, since they sit under paths this task does not permit touching).
