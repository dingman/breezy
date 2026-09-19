# FC-0a-4 Phase B — `(icao, runtime, ftime) -> climate_day` map freeze

Plan of record: `docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md`
WP-4; `docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md` §3.3/§4.2.
Phase A (already committed): `scripts/analysis/forecast_climate_day_map.py`.
Unblocked by the WP-1 IEM MOS reachability probe,
`docs/evidence/iem_mos_reachability_probe_20260919T133522Z/` (VERDICT: PASS,
four-station NBS 2021-01-01..2026-09-19).

## What Phase B adds

1. `scripts/analysis/forecast_txn_climate_day_cli_alignment.py` — per-station
   CLI-truth alignment script. Reads the real, already-archived NWS CLI
   final records from the on-disk settlement-alignment cache (the same
   cache `cli_basis_boundary_study.py` and its siblings already read;
   `pmr_climatology_study.load_cli_records` reused verbatim, not
   reimplemented) and runs two checks per station — see module docstring
   for the full design. Machine-generated output of the real run:
   `docs/evidence/forecast_txn_climate_day_cli_alignment_2026-09-19.md`.
2. Nine "observed"-provenance fixture rows appended to
   `tests/support/forecast_climate_day_fixtures.py` (one per existing
   Phase-A phenomenon, so the Phase-A `test_every_phenomenon_has_an_
   observed_row` xfail-until-Phase-B test now runs for real and passes),
   each grounded in a real NWS CLI FINAL date verified present in the
   archive: 2024-12-02/2024-12-03 (MIA/MDW/SFO/LAX bleed + the v5-format
   split pair), 2022-03-13 (DST spring-forward), 2022-11-06 (DST
   fall-back). Three of the nine are the ones the plan names explicitly:
   `mia_period_end_bleed`, `sfo_utc_cut_miss`/`lax_utc_cut_miss`,
   `dst_spring_forward`/`dst_fall_back`.
3. `tests/unit/test_forecast_climate_day_observed_fixtures.py` — the
   RED-first suite for those three named phenomena (see RED_EVIDENCE
   below), each proving the frozen map beats a naive "UTC calendar date of
   ftime" map on a real date, not a synthetic one.
4. `tests/unit/test_forecast_txn_climate_day_cli_alignment.py` — unit
   coverage for the alignment script's pure functions (window-bounds
   arithmetic, the day-label cross-check, the window-coverage check),
   synthetic in-memory `CliRecord` rows only, no real cache read, matching
   `test_cli_basis_boundary_study.py`'s established convention.
5. `FROZEN_TABLE_SHA256` frozen (was `None`) — see digest section below.

## Real-archive run (four stations, 2021-01-01..2025-12-31, `n`=1809-1826/station)

| station | offset | n days | day-label mismatches | window-coverage miss rate |
|---|---|---|---|---|
| KMIA | -5.0 | 1819 | **0** | 0.61% (11/1797) |
| KMDW | -6.0 | 1826 | **0** | 7.98% (145/1817) |
| KSFO | -8.0 | 1809 | **0** | 1.57% (28/1782) |
| KLAX | -8.0 | 1820 | **0** | 0.69% (12/1745) |

Full per-station miss examples in
`docs/evidence/forecast_txn_climate_day_cli_alignment_2026-09-19.md`
(script-generated, reproducible via
`.venv/bin/python scripts/analysis/forecast_txn_climate_day_cli_alignment.py`).

**Day-label cross-check (P2): 0 mismatches across 7,274 real archived
station-days, all four stations.** For every real NWS CLI FINAL day `D` on
record, the canonical daily-max TXN row targeting `D`
(`runtime=12Z(D)`, `ftime=06Z(D+1)`) maps back to exactly `D` through
`climate_day_for_txn`. This is exhaustive over the archive, not a sample.

**Window-coverage check (P1 corollary): MDW is an outlier.** The other
three stations show the true CLI-published maximum landing inside the 18h
TXN window on 98.4%-99.4% of days; MDW is lower at 92.0%. Inspecting the
MDW miss examples (`2021-01-22@00h`, `2021-02-05@00h`, ...) shows the
published max routinely falls in the first 0-1 local-standard hours of the
day — i.e. the tail of the *previous* day's warm air mass, a real winter
meteorological pattern at MDW, not a parsing or arithmetic defect (the
`CliMaxTime` "(LST)" claim on the CLI product itself is not independently
re-verified here; `pmr_climatology_study.parse_cli_max_time`'s own
docstring already flags that the printed "(LST)" label is carried through
unverified).

**v5-format boundary — measured, not guessed.** The WP-1 probe's 24 NBS
CSV headers (`docs/evidence/iem_mos_reachability_probe_20260919T133522Z/`)
were diffed programmatically: 3 distinct header variants exist across
2021-2026 (an early-years `swh` column present through 2023 at KMIA/KSFO
only, and `t06`/`wbg` columns added starting 2026 at all four stations),
but `runtime`, `ftime`, `model`, `station`, `txn`, and `xnd` are IDENTICAL
— same names, same relative order — across all three variants, spanning
the Dec-2024 `v5` boundary the fixtures docstring flagged as an "INFERRED
boundary date." **This refutes "silent v5 TXN semantic shift" as a
column-schema risk** for the fields this map depends on. It does NOT
confirm value-level semantics (no `txn` cell was ever observed populated
in the two sample rows per probe file — both sampled at short lead times,
01Z runtime / 06Z+09Z ftime — see P1 verdict below).

## P1 / P2 verdict

**P2 — CONFIRMED.** `climate_day = local_standard_date(valid_start_ns,
std_utc_offset_hours)` reproduces the real CLI archive's own day label with
**zero exceptions** over 7,274 real station-days across all four stations
(exhaustive, not sampled), on top of holding by construction: `valid_start`
is always `12:00 UTC` on the target day, and `12 + offset` (7, 6, 4, or 4
for MIA/MDW/SFO/LAX) is a daytime hour that can never cross a local-standard
date boundary regardless of DST (this module never reads DST). No station
needs a distinct P2 formula.

**P1 — PARTIALLY CONFIRMED, not fully verifiable from available evidence.**
The DAY-LABELING consequence of using the 18h/12Z-06Z window (i.e. that
`valid_start`'s date is the correct target day) holds regardless of the
window's exact length — any window anchored at `12Z(D)` staying within
`[D, D+1)` gives the same label — and that part is the CONFIRMED claim
above. The window's specific NUMERIC shape (18h, ending exactly at 06Z) is
still `INFERRED`: the WP-1 probe's two sample rows per NBS file never
showed `txn` populated (both were short-lead, 01Z-runtime, 06Z/09Z-ftime
samples — plausibly too short-range for the daily aggregate element to be
computed yet), so no real forecast TXN value has been observed to confirm
the 12Z-06Z window boundary directly. What IS available as corroborating
(not confirming) evidence: real CLI archive data shows this window would
have captured the true published daily maximum on 92.0%-99.4% of real days
per station (table above) — strong circumstantial support that 12Z-06Z is
a sensible daytime-max window, not obviously wrong, but not a
confirmation of the NBS element's own documented semantics. **Real NBS
forecast-row backfill with populated `txn` values (Stage 0b's WP-6 fit
corpus, `IEM NBS ⨝ CLI truth`) is the only path to fully confirm P1's
numeric claim, and is out of WP-4's Stage-0a "no ingest" scope by design.**

## Per-station disposition (GATE)

**No station needs a per-station map; none drops out.** The shared,
offset-parameterized formula (`climate_day_for_txn`, unchanged from Phase
A) reproduces every one of 7,274 real archived days across all four
stations with zero exceptions. MDW's materially higher window-coverage
miss rate (7.98% vs 0.6-1.6% at the other three) is a Stage-0b
FORECAST-ACCURACY signal (the 18h window sometimes undercounts MDW's true
daily max) worth carrying into WP-6/WP-8's per-station cheap-screen and
power-table work — it is not a day-labeling defect and does not trigger
the plan's per-station-map CONTINUATION clause.

## Digest freeze

`FROZEN_TABLE_SHA256` in `tests/support/forecast_climate_day_fixtures.py`:
was `None`; now
`170eead77c0bbe4b1b876f215813932d14c919ac109296820765bce88aca97ee`, computed
by `table_digest(FROZEN_FIXTURES)` over all 18 rows (9 Phase-A synthetic +
9 Phase-B observed) as the final step of this change, after every fixture
row was finalized. `test_fixture_table_digest_is_frozen` and
`test_every_phenomenon_has_an_observed_row`
(`tests/unit/test_forecast_txn_climate_day.py`) both flip from
`xfail(strict=True)` to real, passing assertions as a direct consequence.

## Leg-invariance (L-44)

`climate_day_for_txn` (`forecast_climate_day_map.py:71-73`) takes no side
or leg parameter and is asserted contract-free of one
(`test_mapping_signature_has_no_side_or_leg_parameter`,
`test_module_ast_has_no_side_leg_yes_or_no_identifier`). Phase B's new
observed rows and the alignment script are likewise side/leg-free by
construction (`ForecastDayFixture` carries no side/leg field;
`forecast_txn_climate_day_cli_alignment.py` never reads one).

## Nautilus null hypothesis

Nautilus Trader 1.231.0 provides no `(icao, runtime, ftime) -> climate_day`
mapping, no MOS/NBS forecast-element parsing, and no CLI-archive alignment
utility — this is a domain-specific weather-forecast semantics problem
with no Nautilus extension point, exactly as Phase A's docstring already
established for `climate_day_for_txn` itself. This module extends nothing
in Nautilus; it is pure Python reading a local file cache.
