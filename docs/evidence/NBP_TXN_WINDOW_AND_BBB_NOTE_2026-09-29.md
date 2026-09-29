# SL-2 evidence note: NBP TXN window, column/LST-day mapping, and BBB indicator

**Slug:** `forecast_nbp_txn_window_bbb` · **Date:** 2026-09-29 · **Author:** TDD implementer (blind sub-agent, SL-2)
**Scope:** plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §3.2 items 1/3/8, §7 row SL-2 (and the BBB
branch of row SL-4). Produced alongside `src/breezy/ingest/nbm_quantile_parse.py` and
`tests/unit/test_nbm_quantile_parse.py`.

**Fixtures used as evidence (real captures, provenance headers in each file):**
`tests/fixtures/nbm/nbptx_t13z_excerpt.txt` (cycle 2026-09-28 13Z), `..._t19z_excerpt.txt` (2026-09-28 19Z),
`..._t01z_excerpt.txt` (2026-09-29 01Z) — all NBM v5.0 — and `..._v4era_t13z_excerpt.txt` (2024-06-01 13Z, NBM
v4.2), each holding the file preamble plus the KLAX/KMDW/KMIA/KSFO station blocks, byte-identical to the raw
AWS capture. Raw files (~34-35 MB each) were fetched from
`https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.<YYYYMMDD>/<HH>/text/blend_nbptx.t<HH>z` and are not
committed (only the excerpts are); their sha256 digests are recorded in each excerpt's provenance header.

---

## (a) TXN maximum-temperature valid window — PRIMARY SOURCE

**Source:** https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0 (NOAA/MDL "NBM Text Card", v5.0), fetched and
scraped 2026-09-29 (HTTP 200). Two distinct passages are relevant, and they do **not** fully agree in scope:

**Passage 1 — the NBP section's own key ("Begin Key" under "NBP"):**

> `TXNMN = QMD Mean minimum/maximum temperature, F. Minimum is listed at 12z, and Maximum is listed at 00z.`

(identically worded, mutatis mutandis, for `TXNSD`, `TXNP1`, `TXNP2`, `TXNP5`, `TXNP7`, `TXNP9`). This is
**VERIFIED, directly, for NBP**: it fixes which grid COLUMN (00Z vs 12Z) carries the daily MAX vs MIN. It does
**not** state a window length.

**Passage 2 — the NBS and NBE sections' own key (each states, identically):**

> `TXN = 18-hour maximum and minimum temperatures, degrees F.`
> `Min is between 00Z-18Z and reported at 12Z (except Guam)`
> `Max is between 12z(current day)-06Z(next day) and reported at 00z(following day) (except Guam)`

This gives an explicit 18-hour window for the MAX: **12Z on the "current day" through 06Z on the day after**,
with the value **labelled/reported at 00Z of that following day** — i.e. the grid column's own timestamp (00Z)
sits a few hours **before** the window's true close (06Z), not at it. That mismatch is the primary source's own
wording, not a parsing artifact.

**Verdict for NBP specifically: UNKNOWN (not independently verified), with a strong but unconfirmed inference.**
The NBP section never restates the "18-hour... 12Z-06Z" window text; it only fixes the 00Z/12Z column split
(Passage 1). `TXNMN`/`TXNP*` (NBP) and `TXN` (NBS/NBE) are computed by the same MDL "QMD" (quantile-mapped
distribution) machinery over what is, by every naming and column-convention signal available, the same
underlying physical daily-max quantity — but the card's authors chose not to duplicate the window-length
sentence under NBP's own key, and no other primary source was found that does. Per L-17 ("a confidently wrong
forecast is worse than no forecast"), this parser does **not** assert the 18-hour window for NBP: it stores only
the 00Z grid instant (`valid_start_ns == valid_end_ns`, mirroring `nbm_forecast_parse.py`'s identical choice for
the identical reason — see that module's own docstring, "period LENGTH is still UNVERIFIED"). The 18-hour figure
is recorded here as a documented, cross-product inference for G2.0/S2 to test against CLI empirically (plan
§3.2 item 8: "If it cannot be verified from a primary source, S2 treats it as unknown and relies on G2.0"),
never as a value baked into `NbpQuantilePoint`.

A secondary corroboration for the parser's own value-clamping behaviour (not the window question): the card
states "Large values: any value which would be printed as >998 will be printed as 998" and "Large negative
values: Any element with a displayed value < -98 will be displayed as -98", and separately, under NBP's own
"Missing Data" note: "For all Elements, a value of -99 indicates missing data." `-99` is already one of
`breezy.domain.forecast_point.FORECAST_VALUE_SENTINELS` (`(-99.0, 999.0)`); this parser reuses
`forecast_value_or_none` unchanged rather than re-declaring a second sentinel rule.

---

## (b) BBB-style correction indicator — PINNED ABSENT

**Checked every fixture header line** (4 stations × 4 files = 16 station-header lines: `KLAX`/`KMDW`/`KMIA`/`KSFO`
across the 13Z, 19Z, 01Z v5.0 captures and the v4.2-era capture) via `nbm_quantile_parse.bbb_correction_token`,
which parses the station-header line with the same regex used to extract station/version/cycle, then checks
for any non-whitespace token trailing `... UTC` on that line. **Result: absent on all 16.**
`test_bbb_correction_token_is_absent_on_every_real_fixture` (parametrized over all four fixture files) pins
this; `test_bbb_correction_token_is_parsed_when_present` proves the function is not a stub (it correctly reads
a synthetic header with a trailing `CCA` token).

**Why it is absent, structurally:** a WMO-style `BBB` correction/retransmission indicator (e.g. `CCA`, `RRA`,
`AAB`, `CCB`) is a token stamped by the NWS telecommunications gateway onto a WMO abbreviated header line
(`TTAAII CCCC DDHHMM [BBB]`) when a bulletin is a correction or retransmission of an already-transmitted
product. The `blend_nbptx.tHHz` files served flat from `noaa-nbm-grib2-pds` on AWS S3 (and mirrored on NOMADS)
carry **no WMO abbreviated-header line at all** — every file examined opens with a bare `1` line, a blank line,
then the first station's `<station> NBM V<version> NBP GUIDANCE ...` header directly. This is a different
distribution channel from the AFOS/NWWS text-product feed `archived_climate_day.py`'s own `wmo_bbb_token` field
was built for (CLI reports), which DOES carry that header. A grep of all four raw ~34 MB files for
`BBB|CCA|RRA|AAB|CCB| COR |RTD` found only coincidental substring matches inside OTHER stations' own
identifiers (`KBBB`, `KCCA`, `LRRA4`, `RRAC1`, `RRAC2`) — never a correction token, and never on any of our four
target stations.

**Consequence for SL-4 (R3-08 dedupe ordering):** per the plan's own branching rule, since BBB is verified
**absent** here, SL-4's retransmission-dedupe ordering must degrade **explicitly** to
`max(LastModified, raw_sha256)`, logged once per run — the `(a) BBB verified present` branch does not apply.

---

## (c) Column-to-LST-climate-day mapping, per cycle, worked examples

**Mechanism (reused, not reimplemented):** `nbm_quantile_parse.max_column_lst_climate_day` is a thin wrapper
over `breezy.ingest.gaps.local_standard_date` — "the ONE copy of this derivation" per that function's own
docstring — applied to a `NbpQuantilePoint`'s `valid_end_ns` (the 00Z grid instant itself, never a fabricated
window end; see part (a) above for why the window end is never used for this conversion). This is the same
family of function `scripts/analysis/forecast_climate_day_map.climate_day_for_txn` already uses for the NBS
product (that module lives in the `analysis` layer and cannot be imported from `ingest`; this module reuses the
same underlying `ingest.gaps.local_standard_date` primitive directly instead of duplicating its arithmetic).

Registered standard-time offsets (`src/breezy/registry/sites.toml`, never DST-following):
KLAX −8.0, KMDW −6.0, KMIA −5.0, KSFO −8.0.

**Why the REPORTED (00Z) instant, not a longer assumed window, must be used for the LST-day conversion:**
converting the true window's close (06Z next UTC day, per the NBS/NBE 18-hour text) instead of the reported 00Z
instant gives a DIFFERENT local calendar day at MIA's −5 offset than converting the 00Z instant does (00Z
converts to the local evening of the window's own "current day"; 06Z at −5 offset has already rolled into the
local morning of the FOLLOWING day). Only the 00Z-instant conversion agrees, at every one of this bot's four
station offsets, with the column mapping verified in part (a) ("Maximum is listed at 00z") and with
`climate_day_for_txn`'s own established convention for the sibling NBS product. This was caught empirically
while building this note (see the module's own docstring) and is the reason `NbpQuantilePoint.valid_end_ns` —
not a synthesized window end — is what `max_column_lst_climate_day` converts.

### Worked example 1 — 13Z cycle (KLAX, `nbptx_t13z_excerpt.txt`)

- Cycle: `2026-09-28 13:00 UTC`. Cycle's own LST day (`local_standard_date(cycle_ns, -8.0)`):
  `13:00 − 8h = 05:00` on **2026-09-28** (no rollback) → `D = 2026-09-28`.
- First available MAX column in the grid: `FHR=35` (the first day-group, `FHR=23`, carries only the 12Z/MIN
  value — NBP's own stated forecast-hour floor, "Hours 24-228*", excludes the earlier `FHR=11` slot that would
  have been that day's MAX). Valid instant = `13:00 + 35h = 2026-09-30 00:00 UTC`.
- `max_column_lst_climate_day` on that instant, offset −8.0: `00:00 − 8h = 16:00` on **2026-09-29**.
- Result: **2026-09-29 = D+1.** Confirmed by `test_first_max_column_targets_dplus1_in_lst_every_cycle` against
  all 4 stations, all three real v5.0-cycle fixtures.

### Worked example 2 — 19Z cycle (KLAX, `nbptx_t19z_excerpt.txt`)

- Cycle: `2026-09-28 19:00 UTC` → LST day: `19:00 − 8h = 11:00` on 2026-09-28 (no rollback) → `D = 2026-09-28`.
- First available MAX column: `FHR=29` (first group `FHR=17` is MIN-only, symmetric to the 13Z case). Valid
  instant = `19:00 + 29h = 2026-09-30 00:00 UTC`. LST day of that instant (offset −8.0): 2026-09-29 = **D+1**.

### Worked example 3 — 01Z cycle (KLAX, `nbptx_t01z_excerpt.txt`)

- Cycle, as printed in the header: `2026-09-29 01:00 UTC`. Cycle's own LST day:
  `01:00 − 8h = 17:00` **on 2026-09-28** (rolls back a day) → `D = 2026-09-28`. This is the case worth stating
  explicitly: the cycle's UTC calendar date (`2026-09-29`) and its LST calendar date (`2026-09-28`) DIFFER for a
  01Z cycle, for every station this bot trades (offsets −4 to −8 all roll back across a 01Z boundary).
  `test_01z_cycles_own_lst_day_is_the_utc_date_minus_one` pins exactly this fact.
- First available MAX column: `FHR=23` — this cycle's grid is shaped differently (its very first day-group
  already carries BOTH the MAX and MIN sub-values, `"00 12"`, because 01Z is early enough in the UTC day that
  the day-D MAX window's 00Z instant is already ≥ NBP's ~24h forecast-hour floor). Valid instant =
  `01:00 + 23h = 2026-09-30 00:00 UTC`. LST day of that instant (offset −8.0): 2026-09-29.
- Result: **2026-09-29 = D+1** (relative to `D = 2026-09-28`, the cycle's own LST day) — the SAME relationship
  as the 13Z/19Z cases, even though the grid's own shape (whether group 0 is MIN-only or MAX+MIN) differs.

### General rule this parser relies on (never hard-coded per station; always computed)

For every cycle and every station, `min(lst_climate_day over all MAX columns) == local_standard_date(cycle_runtime_ns, offset) + 1 day`,
regardless of which UTC hour the cycle runs at or how the day-group grid happens to be shaped at its edges. The
plan's own grouping of "12/13Z, 19Z, 00/01Z targeting D+1" (§2.3) is therefore correct as stated, where `D` is
read as the cycle's **own LST day**, not its printed UTC calendar date — the two differ specifically for the
00/01Z cycles, at every station this bot trades.

---

## Summary of what is pinned vs. still open

| Item | Status |
|---|---|
| NBP 00Z=MAX / 12Z=MIN column split | VERIFIED (primary source, NBP's own key) |
| NBP MAX window length (12Z-06Z, 18h) | **UNKNOWN for NBP** — verified only for the sibling NBS/NBE products; not asserted in `NbpQuantilePoint`; G2.0 is the empirical backstop per the plan |
| BBB correction indicator | VERIFIED ABSENT on all 16 real station-header lines examined; parser can parse one if a future capture ever carries it |
| Cycle → D+1 LST column mapping (13Z/19Z/01Z) | VERIFIED against real fixtures, all 4 stations, general rule stated above |
| `-99` missing-data sentinel | VERIFIED (primary source, NBP's own "Missing Data" note); reuses the existing `FORECAST_VALUE_SENTINELS` rule unchanged |
