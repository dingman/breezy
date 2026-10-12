# S1 — Stage 0 preconditions (maker-window print census + TRADE_QUANTITY_UNIT)

| Field | Value |
|---|---|
| ID | S1 |
| Title | Stage 0 preconditions: maker-window print census, LAX/MDW/MIA/SFO, climate days 2026-09-18..2026-10-13; resolve or bracket `TRADE_QUANTITY_UNIT` |
| Revision | r3 (conformance revision of r2 to spec v0.3; r2 verdict `reviews/S1-r2-final.md` READY-WITH-NOTES, all MINORs applied, §11) |
| Date | 2026-10-12 |
| Status | READY (planning only; nothing built, nothing run) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` **v0.3**, §3, §4, §6.0, §6.1, §9.3, §9.4, §9.16 |

## 1. Goal state (acceptance test)

S1 is done when these exist on the branch:

1. **A committed censused-day list**, `~/.local/share/breezy/derived/maker/s1/censused_days.jsonl` (sha256 in the
   doc): one row per (station, climate_day), LAX/MDW/MIA/SFO, 2026-08-30..2026-10-13, closed `reason` alphabet (WP1),
   with coverage, BUYER prints per YES-price bucket, SELLER/NO_AGGRESSOR counts, `first_seen_ns`. **No Depth10 is read.**
2. **Numbers computed by the script, never by hand:** `N_cov` covered station-days, `D_cov` distinct covered climate
   dates, `n_eff_ub` (clustered upper bound on Stage 0 station-day units, §2.1), and the fillability ceiling `C` =
   covered station-days with ≥ 1 YES BUYER print at p_yes ≥ 0.20 in the maker window ÷ `N_cov`.
3. **A unit verdict.** `TRADE_QUANTITY_UNIT` ∈ {`CONTRACTS`, `USD_NOTIONAL_YES`, `USD_NOTIONAL_TAKER`} from matching
   own create-path fills to unique recorded prints; or `BRACKETED_USD` (surviving set exactly {`USD_NOTIONAL_YES`,
   `USD_NOTIONAL_TAKER`}, which spec §6.0/§6.1/§9.3 accept: Stage 0 runs under both, the conservative one governs); or
   `UNRESOLVED` with the surviving set.
4. **The constant recorded** (`parsing.py:231`) only on a single-hypothesis verdict, pin test rewritten RED→GREEN.
5. **One evidence doc**, `docs/evidence/MAKER-S1_preconditions_<run-date>.md`, with items 1–4, the empirically checked
   YES→NO inversion (§5.2), the net SEARCH forfeiture tally, and the `census_provenance:` line.

## 2. Entry criteria and STOP conditions

**Entry (all required):**
- Worktree off `feat/data-capture-and-risk`, ff'd first; `PYTHONPATH=<wt>/src` always; no uv/pip/`uv run`; no stash.
- **≥ 10 GB free on `/`** (4.7 GB on 2026-10-12): no gate or run until a coordinator frees space; S1 never deletes tape.
- Recorder active; `breezy-studies.lock` free. **WP0 committed** before any climate day > 2026-09-25 is read (WP1, WP2).

### 2.1 The floor, derived

Spec §6.0 verdicts: **NO-GO** (base fill rate < 0.10 point estimate, or §6.9 FAIL), **NOT-KILLED** (base and stressed
≥ 0.10, §6.9 PASS), **NOT-KILLED-UNSCREENED** (§6.9 under its 10-expected-loss minimum); denominator = all covered
bid-bearing station-days. The floor keeps noise from firing NO-GO on a viable family.
- **Target:** false NO-GO probability ≤ 5 % when the true fill rate is 0.2 (2× the line; spec §9.15 plans on 0.3).
  Binomial: at n = 30, P(X ≤ 2 | p = 0.2) = 0.044 (X ≤ 2 ⇔ rate < 0.10). So **n_eff ≥ 30 station-day units**.
- **Unit = station-day, cluster = climate date** (spec §6.2). Spec §3 makes MAX_RUNGS = 2 conditional (fallback 1) and
  says gates use the stricter of position and station-day units; the station-day unit is the stricter and is
  identical under MAX_RUNGS 1 or 2, so S1 needs no rung assumption. A date carries m_d ≤ 4 units.
- **Formula:** `n_eff_ub = Σ_d m_d / (1 + (m_d − 1)·ρ)`, within-date **ρ = 0.5 ASSUMED, not measured**. A full date
  (m = 4) contributes 1.6, so ≈ 19 fully covered dates are needed; the best case for 09-18..10-13 (26 dates) is ≈ 41.6.
- **Necessary only, crude, exploratory:** bid-bearing days need the forecast (S2 re-checks on real bids).
- **§6.9 power line (reported, not gated by S1):** at p_YES ≤ 0.06 per bid, 10 expected losses need ≥ 167 fills, above
  any pre-freeze + declared sample, so Stage 0 can likely emit only NO-GO or NOT-KILLED-UNSCREENED (never PASS, §7 g9).

### 2.2 STOP conditions

- **S-1 (UNDERPOWERED):** `n_eff_ub < 30` after the full run. S1 ends UNDERPOWERED. The evidence doc states the
  declaration extension Stage 0 would need (dates after 2026-10-13 at the measured n_eff per date, and their net
  forfeiture cost) and routes it to **Q1** (programme SEARCH ruling). The eligibility rule is never relaxed.
- **S-2 (unit):** only verdict `UNRESOLVED` stops (CONTRACTS not excluded, a contradiction, fewer than 2 counted
  matches, or a surviving set other than the two USD hypotheses). §6.1 cannot run; the constant stays. **`BRACKETED_USD`
  is not a stop:** S2 proceeds under both USD hypotheses (spec §6.0), the constant stays unflipped.
- **S-3 (premise break):** an own fill with no inversion-consistent print but ≥ 1 anti-candidate (§5.2 false): STOP.
- **S-4 (firewall refused):** WP0 not endorsed. Pass A alone (≤ 8 dates × 4 stations) gives `n_eff_ub ≤ 12.8 < 30`:
  **UNDERPOWERED, routes to Q1.** No "wait": later days are post-freeze too.
- **S-5 (fillability ceiling):** a resting NO bid at b ∈ [B_FLOOR 0.70, B_CAP 0.80] fills only on a YES BUYER print at
  p_yes ≥ 1 − b ≥ 0.20 on its rung (§5.2, spec §6.1), and only after the queue ahead is consumed, so the per-station-day
  fill rate is at most about `C` (any-rung, queue-blind, interruption-blind: loose upward). **`C < 0.05` → STOP the
  family at v0.3 with no S2 build**, reported as a Stage 0 **NO-GO pre-screen** (base fill rate < 0.10 is implied; the
  0.05 margin covers bid-bearing-day selection). `0.05 ≤ C < 0.10` → flag `KILL-LIKELY` and proceed to S2. Payoff: S1
  can retire S2–S5 for the cost of one census.

## 3. Simplest direct path

### 3.1 Path

(1) WP0: one dated SEARCH declaration (docs). (2) WP1: a ~250-line sidecar that, per CLEAN instance, natively converts
four **small** streams (`BinaryOption`, `QuoteTapeGap`, `VenueClockOffset`, `TradeTick`, ~2–8 MB each) into a scratch
catalog, filters prints to the four stations and declared days, counts deduped prints per station-day in the maker
window, and deletes the scratch. One run. (3) WP2: match the 28 create-path own fills to unique prints. (4) WP3: flip
one constant if a single hypothesis survives.

**Maker window (spec §3).** `[D−1 12:00Z, min(D 01:00Z + STALE_H + NBP_LAG_UB, D 09:00 LST))`:
- Vectors for climate day D come from the D−1 13Z, D−1 19Z and D 01Z cycles (`ForecastQuantileVector.climate_day` = the
  cycle's LST date + 1, `forecast_state.py:191-201`; standard offsets are negative). The D 01Z vector is the last; with
  `age = now − available_at` and STALE_H = 8, bids for D stop at its `available_at` + 8 h.
- `NBP_LAG_UB = 2 h`: above the measured 01Z p95 lag of 98.4 min (`docs/evidence/NBP_LAG_CENSUS_2026-09-29.md`, per-cycle
  table; floor 60 min, `forecast_point.py:165-169`). End ≈ D 11:00Z. **09:00 LST (14Z MIA, 15Z MDW, 17Z LAX/SFO) is
  the backstop** and never binds at this lag. A slower 01Z publication extends the true window; a missing 01Z vector
  shortens it. Both are per-day schedule facts S2 simulates (spec §6.0 process schedule); S1 does not read forecasts.
- Start D−1 12:00Z is the listing line (spec §3) and precedes the first D−1 13Z vector (≈ 14Z): loose upward for S-5.
  The window crosses the 09:00Z rotation, so it is a union of two instances.

AUD-09a is not reused (verified r2): afternoon-only window (`replay_sufficiency.py:207-222`), no print counts, 20
callers, window-blind span cache (`instance_span_cache.py:84-85`), QuoteTick + Depth10 conversion (disk-heavy).
**No Depth10**: S1 asks only "was the recorder alive" and "did fill-capable prints happen"; quiet overnight books would
read as outage. Q₀, trade-through, episodes, marketability and the 2×(size ahead + 1) stress (spec §6.1) are S2's.

### 3.2 RA-13 B-3 and the SEARCH cost

- B-3 binds the corpus: any count on post-2026-09-25 tape spends those station-days' H-ARCHIVE-RECAL CONFIRM status
  (`RULING_RA-13_programme_kill_2026-09-27.md:89-92`); only a SEARCH declaration with the cost in both plans licenses it
  (`EDGE-4_DISPOSITION_2026-09-27.md:19`; template `RA-13-FW_firewall_audit_2026-09-27.md:21-29`). A census does
  **not** lift B-3; WP0 does (spec §6.0).
- **Pass B is required** (S-4 arithmetic): trade capture starts 2026-09-17 09:00Z, so the pre-freeze maker sample is
  climate days 09-18..09-25 only (spec §6.0 first replayable day 09-18). Pass A and Pass B are one run.
- **Net cost.** Gross scope 4 stations × 18 days (09-26..10-13) = 72 station-days. **14 are already SEARCH** (nightly
  exit-window study read their Depth10): LAX 10-02..10-06; MDW 10-02, 10-04, 10-05, 10-06; MIA 10-03, 10-05; SFO 10-03,
  10-04, 10-06 (`derived/exit_window_study/2026-10-0*_nightly/exit_window_study.json`, read 2026-10-12; WP0 re-verifies
  and cites). **Net new forfeiture ≤ 58 station-days**: at ~5/day EDGE-4 accrual, revival moves ≈ 12 days, from
  ≈ 2026-11-24 to ≈ 2026-12-06, inside the 2027-01-25 backstop. NYC is untouched.
- **Q1 flag:** an S5 shadow run here makes most future station-days SEARCH, leaving revival to NYC (~1/day).

## 4. Invariants (restated; S1 respects every one)

- Nautilus immutable (native types, `ParquetDataCatalog`, `default_convert` only); `allow_short` stays `False`; no value
  for max daily budget / max per position; live enablement, `BREEZY_ORDERS_ENABLED`, A1 halt untouched; no frozen
  PREREG.json edited, no pre-registered date moved; FQ-v2 NO-TRADE ruling in force (this programme is its T2 route); no
  safety/settlement/contract/NO-SEND test weakened (exact-set barriers widen by one reviewed row, L-12); Stage 0 output
  EXPLORATORY only; S1 emits no Stage 0 verdict other than the S-5 NO-GO pre-screen and never the word GO.
- **S1 makes zero network calls**; exec sqlite opened `mode=ro`; the capture root is read-only (scratch catalogs live
  under `~/.cache/breezy/maker-s1-work/`, refused if inside the capture root, as `_convert_live_capture:129-135` does).
- S1 reads no forecast store (NBP holdout untouched; window end is a constant, §3.1). Rewriting
  `test_the_print_size_unit_is_declared_unresolved` is not weakening a guard: the new pin is stricter.

## 5. Nautilus null-hypothesis check

### 5.1 Native capability per need

| Need | Native / existing capability | Evidence | Gap? |
|---|---|---|---|
| Print, direction, identity | `TradeTick` + `AggressorSide`; `trade_id` = sha256 of venue-only fields | `parsing.py:283-290,940-948,981-1001` | none; dedupe key |
| Raw feather → catalog | `default_convert(source, instance_id, cls, "live", target=work)` | `quote_tape_ingest_core.py:742-776` | none (TradeTick UNVERIFIED, §7) |
| Gap records, collapsed + partitioned | `load_partitioned_quote_tape_gaps(catalog)` | `quote_tape_gaps.py:86-106`; flat reads refused `:56-61,79-83` | none; reuse |
| Recorder liveness span | `VenueClockOffset`, one per 200 quote frames | `data.py:294,2059-2082` | none (span = first..last `ts_init`) |
| Instance classification | `scan_instance` / `classify_instance` | `feather_preflight.py:525`; `cli_basis_offer_gate_scan.py:391` | none; reuse |
| Rung / station / day identity | `read_weather_bucket_facts(instrument.info)` | `weather_bucket_facts.py:90-124` | none |
| Maker fill matching (S2) | `BacktestVenueConfig(trade_execution=True, queue_position=True)` | `docs/reference/nautilus/v1.231.0/concepts/backtesting/trade-execution.md:3,29-34,46,96` | caps at `trade.size` in instrument units: the unit verdict is S2's precondition |
| Unit; maker-window census; post-freeze firewall | none (venue fact; AUD-09a afternoon-only; governance) | — | **missing: WP2, WP1, WP0** |

PM.us prints arrive on the YES instrument only (`parsing.py:936-938`); S2 derives NO-frame ticks via §5.2.

### 5.2 YES→NO inversion for a NO maker bid (spec §6.1)

- A resting **BUY NO at b** goes out as `ORDER_SIDE_SELL` / `ORDER_INTENT_BUY_SHORT` at wire price `1 − b`
  (`leg_prices.py:39-46,56-75`): a **YES ask at 1 − b**.
- Only a YES print with **aggressor BUYER at p_yes ≥ 1 − b** can fill it ≡ NO-frame **SELLER at ≤ b**, matching
  Nautilus's "SELLER trade fills resting BUY". YES SELLER prints are NO buyers taking: they compete, never fill.
- With b ∈ [0.70, 0.80] (B_FLOOR..B_CAP): p_yes < 0.20 (NO price > 0.80) consumes better-priced NO bids only — a Q₀
  reducer in S2, never a fill; p_yes ∈ [0.20, 0.30) fills bids b ≥ 1 − p_yes; p_yes ≥ 0.30 can fill any bid. Hence
  WP1's buckets. A print far above a tail rung's ask means cheaper asks were swept: the §6.9 adverse-selection signature.
- Taker-side check (WP2): our NO IOC buys must print **SELLER at 1 − cost**, YES buys **BUYER at cost**; else S-3.

## 6. Work packages

Every focused gate:
`PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m pytest <tests> tests/unit/test_polymarket_us_fee_guard.py <exec-import-pin + NO-SEND firewall tests> --basetemp ~/.cache/breezy-pytest/s1-<wp>`; read the exit code
(not `-q`), then `rm -rf` the basetemp; `cd <wt> && lint-imports` must print "N kept, 0 broken". Format only own files.

### WP0 — SEARCH declaration (docs only; ~1 h)

- **Create** `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`: basis (§3.2); scope LAX/MDW/MIA/SFO ×
  climate days 2026-09-26..2026-10-13, NYC excluded; covers S1 and S2 Stage 0 reads only, never S5; the net cost
  table (72 gross, 14 already SEARCH with source, ≤ 58 net, date effect); the per-fill list WP2 will read.
- Same cost in the H-ARCHIVE-RECAL/AUD-18 record. Blind review (prediction-market-reviewer, architect) →
  `reviews/S1-WP0-*.md`. **Done when** committed; its sha256 is the value WP1 pins.

### WP1 — maker-window print census (~5 h build, run ≤ 1 h projected)

**First RED fixture (before anything else is built):** `test_trade_tick_default_convert_round_trips_into_scratch_catalog`
(script-level, tmp raw-feather written through the streaming writer). If it cannot go GREEN without touching Nautilus,
switch to the named fallback (§7) before building on it.

**Create `src/breezy/analysis/maker_tape_census.py`** (pure, ~140 lines, no Nautilus import, no pyarrow; satisfies
"The offline analysis layer never DIRECTLY imports Nautilus", `pyproject.toml:163`). Plain ints/strings only.
- Constants (fixed before any run; changing one needs a plan revision): `PRE_FREEZE_END = date(2026, 9, 25)` (same
  name and value as `nbp_market_comparison.py:72`), `TRADE_CAPTURE_START_NS` = 2026-09-17T09:00Z,
  `MAKER_STATIONS = frozenset({"LAX","MDW","MIA","SFO"})`, `SEARCH_DECLARED = ("LAX,MDW,MIA,SFO", date(2026,9,26),
  date(2026,10,13))`, `SEARCH_DECLARATION_SHA256` (WP0's), `STALE_H = 8`, `LAST_CYCLE_UTC_HOUR = 1`,
  `NBP_LAG_UB_H = 2`, `CANCEL_LST_HOUR = 9`, `COVERAGE_MIN = 0.90`, `LONGEST_HOLE_MAX_MIN = 60`, `RHO_ASSUMED = 0.5`,
  `N_EFF_FLOOR = 30`, `C_STOP = 0.05`, `C_FLAG = 0.10`,
  `PRICE_BUCKETS = ((0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.01))`.
- `maker_window_ns(*, climate_day, std_utc_offset_hours) -> tuple[int, int]` = `[D−1 12:00Z, min(D 01:00Z + STALE_H +
  NBP_LAG_UB_H, D CANCEL_LST))`, integer arithmetic; returns which bound bound (`STALE_DERIVED` / `CANCEL_LST`).
- `require_firewall_clearance(station, day, declaration_sha256: str | None) -> Literal["PRE_FREEZE","SEARCH_DECLARED"]`
  raises `FirewallRefused` for a station outside `MAKER_STATIONS`, or a day > `PRE_FREEZE_END` that is outside
  `SEARCH_DECLARED` or whose supplied sha256 ≠ the pinned one. No markdown parsing.
- `admit_print(station, climate_day, requested_days) -> bool`: True only for `MAKER_STATIONS` × requested, cleared days.
  Applied **before any bucketing, count or log**; a rejected print (NYC, D+1 or out-of-range slug) is discarded
  unrecorded (no row, no counter, no value logged).
- `covered_intervals(window, alive_spans, gaps) -> tuple[tuple[int,int], ...]`: union of instance alive spans clipped
  to the window, minus every gap interval of the station-day's instruments (an unresolved gap runs to `+∞`).
- `CensusedDay` (frozen): station, climate_day, firewall_class, reason, coverage_fraction, longest_hole_min,
  `tail_span_only` (bool: the day failed coverage only because the last `VenueClockOffset` precedes window end),
  buyer_by_bucket (4 ints), prints_seller, prints_no_aggressor, rungs_with_qualifying_buyer, first_seen_ns,
  instances_clean, instances_corrupt. Explicit `to_dict`/`from_dict`, no `asdict`.
- `classify(...) -> CensusedDay`. Closed `reason`: `PRE_TRADE_CAPTURE` (window start < `TRADE_CAPTURE_START_NS`; emitted
  **without reading tape**, excluded from every denominator), `NO_CLEAN_INSTANCE`, `CORRUPT_ONLY`,
  `TRADE_PARSE_FAILURE`, `LOW_COVERAGE`, `LONG_HOLE`, `COVERED`.
- `summarise(rows) -> CensusSummary`: `N_cov`, `D_cov`, `n_eff_ub` (§2.1, station-day units), `C`, report-only `C_030`
  (p_yes ≥ 0.30), `tail_span_only` count, and which STOP (S-1/S-5) fires or the flag.
- `write_censused_days` / `read_censused_days`: sorted, byte-idempotent JSONL; refuses unknown keys, duplicates.

**Create `scripts/analysis/maker_tape_census.py`** (I/O layer, ~150 lines).
- Flags: `--from`, `--to`, `--stations`, `--search-declaration PATH` (sha256 checked against the pin), `--output`,
  `--catalog-root` (default `~/.local/share/breezy/catalog/quote_tape/polymarket_us`), `--work-root` (default
  `~/.cache/breezy/maker-s1-work`).
- Per instance: `scan_instance` + `classify_instance`; LIVE/CORRUPT counted, only CLEAN read: `default_convert` the four small classes into `<work-root>/<instance_id>`; `work.query` them;
  gaps via `load_partitioned_quote_tape_gaps(work)` per `GapPartitionKey`; alive span = first..last `VenueClockOffset`
  `ts_init`; cleanup via `replay_sufficiency_census._cleanup_work_catalog` in a `finally`.
- Prints pass `admit_print` first (instances hold all five ladders and D+1 slugs; conversion necessarily touches NYC
  bytes, counting never does), then are **deduplicated on `trade_id` across instances**, bucketed on YES price; BUYER
  counted per bucket; per-rung qualifying BUYER counted via `read_weather_bucket_facts`.
- Any conversion/deserialise failure of `TradeTick` for an instance → every admitted station-day it touches gets
  `TRADE_PARSE_FAILURE` (never a silent lower count).
- `first_seen_ns` = earliest `BinaryOption.ts_init` per (station, day): listing-gap diagnostic.
- Emits `census_provenance:` (git sha, stations, range, declaration sha256, instances, window constants) and one stderr
  progress line per instance (the stall watch keys on it).

**RED-first tests** (`tests/unit/test_maker_tape_census.py`):
`test_maker_window_spans_d_minus_1_noon_utc_to_stale_derived_end`, `test_cancel_lst_backstop_binds_when_earlier`,
`test_post_freeze_day_refused_without_matching_declaration_sha`, `test_post_freeze_day_outside_declared_range_refused`,
`test_nyc_is_refused_even_with_declaration`, `test_nyc_prints_never_reach_a_count`,
`test_out_of_range_day_prints_never_reach_a_count`, `test_pre_trade_capture_rows_are_emitted_without_reading_tape`,
`test_unresolved_gap_contaminates_to_window_end`, `test_coverage_is_alive_span_minus_gaps_not_book_density`,
`test_tail_span_only_failure_is_flagged`, `test_a_print_seen_by_two_overlapping_instances_counts_once`,
`test_seller_and_no_aggressor_prints_never_qualify`, `test_buyer_print_below_020_never_qualifies`,
`test_n_eff_ub_matches_hand_formula_for_mixed_dates`, `test_c_below_005_fires_s5`,
`test_censused_days_round_trip_refuses_extra_keys_and_duplicates`,
`test_write_is_byte_idempotent_regardless_of_input_order`; script-level (tmp raw-feather fixture written through the
streaming writer as in `test_gaps_and_offsets_survive_the_streaming_writer_and_the_catalog`): the first-RED fixture
above, `test_live_instance_is_counted_never_read`, `test_trade_tick_parse_failure_refuses_the_station_day`,
`test_work_catalog_is_removed_and_capture_root_untouched`.

**Run** (after review; not under this plan): (a) **subset benchmark**: one instance under `/usr/bin/time -v`, record
wall and peak RSS; (b) **one run**, `--from 2026-08-30 --to 2026-10-13`, only after WP0 is committed and **at/after
2026-10-14 10:00Z** (the 10-13 window ends ≈ 10-13 11:00Z inside the instance that is LIVE until the 10-14 09:00Z
rotation), clear of the 15:20Z/15:50Z studies:
```
systemd-run --user --unit=breezy-maker-s1-census --slice=breezy-studies.slice \
  -p MemoryHigh=3G -p MemoryMax=4G -p RuntimeMaxSec=<3 × benchmark × instances, min 1800> \
  -p LimitNOFILE=524288 -p WorkingDirectory=<wt> -E PYTHONPATH=<wt>/src --collect \
  /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
  /home/jon/breezy/.venv/bin/python scripts/analysis/maker_tape_census.py --from 2026-08-30 --to 2026-10-13 \
  --stations LAX,MDW,MIA,SFO --search-declaration docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md \
  --output ~/.local/share/breezy/derived/maker/s1/censused_days.jsonl
```
Arm a Monitor in the launch turn; stop the unit on a 15-min progress stall; wait on ActiveState ∉ {active, activating}.
**Done when:** tests GREEN; lint-imports clean; python-reviewer clean (blind); run exit 0 with provenance quoted;
`N_cov`, `D_cov`, `n_eff_ub`, `C` and any STOP emitted by the script.

### WP2 — `TRADE_QUANTITY_UNIT` evidence (~2.5 h build, minutes to run)

**Create `src/breezy/analysis/trade_quantity_unit.py`** (pure, ~90 lines).
- `UNIT_HYPOTHESES = ("CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER")`; `USD_BRACKET = frozenset(
  {"USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER"})`.
- `OwnFillMatch` (frozen): leg, fill_cost, fill_qty, candidate_count, anti_candidate_count, print_price_yes,
  print_size, summed: bool.
- `predicted_size(h, m)`: CONTRACTS → `fill_qty`; USD_NOTIONAL_YES → `print_price_yes × fill_qty`;
  USD_NOTIONAL_TAKER → `fill_cost`. Exact Decimal equality at the print's own precision. A NO fill at 0.12 predicts
  (1, 0.88, 0.12); a YES fill at c predicts (1, c, c), so YES matches separate CONTRACTS from USD but never the two USD
  hypotheses. Fractional contracts fall under CONTRACTS (no integer test).
- `classify_trade_quantity_unit(matches) -> tuple[str, frozenset[str], str]` (verdict, surviving set, reason). A match
  **counts** only if `candidate_count == 1` and not `summed`. With counted n ≥ 2: surviving set of size 1 → that
  hypothesis; surviving set == `USD_BRACKET` → `BRACKETED_USD`; anything else → `UNRESOLVED`. A counted match
  consistent with no hypothesis → `UNRESOLVED` (contradiction reported).
- **SUMMED path.** `DurableFillRecord` is CUMULATIVE per venue order (`client.py:933-957`: `cumulative_qty`,
  `cumulative_cost`; `ts_event`/`trade_id` reflect the last update). Any record whose match needs more than one print
  (no single unique candidate equals a prediction, but a same-side, same-price sum in the window does), or whose
  window holds > 1 candidate, is routed to `summed=True`: reported, may confirm, **never counts**. Earlier clips of a
  multi-clip order can sit outside the ±5 s window anchored on the last clip, which is why it never counts.
- `inversion_verdict(m) -> Literal["HOLDS","CONTRADICTED","NO_PRINT"]`: `CONTRADICTED` iff `candidate_count == 0` and
  `anti_candidate_count ≥ 1` (feeds S-3).

**Create `scripts/analysis/trade_quantity_unit_crosscheck.py`** (~110 lines).
- Reads `exec/polymarket_us/fill/*` from `~/.local/share/breezy/state/exec_polymarket_us.sqlite` (`mode=ro`); keeps a
  fill only if `tsEvent ≥ TRADE_CAPTURE_START_NS`, `tradeId` is a venue id (not `GET-…`, not null; **resolver
  `tsEvent` is discovery time and is never matched**), `feeReconciled` is True (else `cumulativeCost` may embed fee;
  refused), and the station is in `MAKER_STATIONS`. Each kept fill passes `require_firewall_clearance`.
- Prints every fill key, tsEvent, climate day, provenance, keep/refuse reason. Verified 2026-10-12 (read-only): **28
  kept** (MIA NO 0.12 09-21, SFO YES 0.35 09-21, MDW NO 0.12 09-22, 25 YES on climate days 10-02..10-06, no NYC); 6
  excluded (one null `tradeId`, one `GET-` resolver, four pre-capture).
- Clock: create-path `tsEvent` = venue `Execution.transactTime` (`reports.py:1356-1360`), the print's clock: **±5 s**.
- Candidate selection uses **side + price + time only, never size** (else circular): on `yes_instrument(instrumentId)`
  (`capture_audit_fill_support.py:183`), NO leg → SELLER at `1 − cost`, YES leg → BUYER at `cost`; anti-candidates are
  the opposite aggressor or the un-inverted price. Prints come from the WP1 conversion path (`admit_print`, dedupe on
  `trade_id`), CLEAN instances only. Every candidate is listed; none is silently picked.

**RED-first tests** (`tests/unit/test_trade_quantity_unit.py`): `test_no_leg_fill_separates_all_three_hypotheses`,
`test_yes_only_matches_resolve_contracts_but_not_usd_split`, `test_usd_pair_surviving_is_bracketed_not_unresolved`,
`test_contracts_not_excluded_is_unresolved`, `test_two_candidates_make_a_match_not_count`,
`test_disagreeing_matches_are_unresolved`, `test_fewer_than_two_counted_matches_are_unresolved`,
`test_summed_match_never_counts`, `test_cumulative_multi_print_order_routes_to_summed`,
`test_inversion_contradicted_needs_zero_candidates_and_an_anti_candidate`,
`test_resolver_and_unreconciled_fills_are_refused`, `test_post_freeze_fill_refused_without_declaration`,
`test_crosscheck_opens_exec_db_read_only`. **Done when:** tests GREEN; one JSON result with verdict, surviving set, per-fill inversion; S-2/S-3 evaluated.

### WP3 — record the unit (~1 h; only on a single-hypothesis verdict; `BRACKETED_USD` skips WP3)

- **Modify `src/breezy/adapters/polymarket_us/parsing.py:225-231`**: `TRADE_QUANTITY_UNIT: str = "<verdict>"`; comment
  cites the evidence doc and matched fills; update the `parse_trade_tick` docstring line "**size is unit-unresolved**"
  (`:950`). No unit conversion in the parser: recorded tape stays byte-stable; conversion is S2's.
- **Modify `src/breezy/adapters/polymarket_us/data.py:1863-1866`**: log text interpolates the constant; nothing else.
- **Modify `tests/unit/test_polymarket_us_depth_parsing.py:431-438`**: write
  `test_the_print_size_unit_is_resolved_by_own_fill_crosscheck` first (RED against `"UNRESOLVED"`), asserting the value
  and that `docs/evidence/MAKER-S1_preconditions_*.md` names it; then flip the constant (GREEN); remove the old pin.
- Gate: focused, then **full** `scripts/ci/run_tests_no_egress.sh --basetemp ~/.cache/breezy-pytest/s1-full`
  (LimitNOFILE=524288); EXIT before merge; `rm`. Activation: next scheduled 09:00Z rotation, never a manual restart.

### WP4 — evidence doc + PROGRESS row (~1 h)

- **Create** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`: `N_cov`, `D_cov`, `n_eff_ub` (ρ labelled assumed),
  `C` and `C_030` by station and bucket table; rows by reason; count of days failed on tail span only;
  `first_seen_ns` late-listing count; window constants and which bound bound; jsonl sha256 and row count; provenance
  line; unit verdict, surviving set and per-fill match table (SUMMED rows marked); inversion result; net forfeiture
  actually incurred (station-days read post-freeze minus the 14 already SEARCH); which STOP fired or `KILL-LIKELY`; the
  §6.9 power line (§2.1). The words GO / NOT-KILLED never appear as S1 outcomes.
- One-line `docs/core/PROGRESS.md` row; commit at the milestone; push only after a green gate, EXIT read.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| Raw tape (81 instances) | `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live/<uuid>/` | present; `trade_tick/` in 27, `custom_quote_tape_gap/` in 52, flat `custom_venue_clock_offset_*.feather` (~2 MB) |
| Trade capture start | commit `4d6bb059` (2026-09-16); first journal evidence 2026-09-17 09:00Z | VERIFIED (journal, r1) |
| Durable fills | `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, `exec/polymarket_us/fill/<venueOrderId>` | VERIFIED 2026-10-12: 34 rows, 28 kept |
| Already-SEARCH station-days | `~/.local/share/breezy/derived/exit_window_study/*_nightly/exit_window_study.json` | 14 found 2026-10-12; WP0 re-verifies |
| NBP lag bound | `docs/evidence/NBP_LAG_CENSUS_2026-09-29.md` (01Z p95 98.4 min, max 804 min) | VERIFIED 2026-10-12; constant, no forecast read |
| Native conversion of `QuoteTapeGap`/`VenueClockOffset` | `default_convert` | ingest markers exist on instances; first script fixture re-proves it |
| `TradeTick` via `default_convert` into a scratch catalog | — | **UNVERIFIED** (no existing caller); proven by WP1's first RED fixture before the sidecar is built; fallback: deserialize the raw stream with `ArrowSerializer` as `_load_stream` does, keeping `admit_print`, trade_id dedupe and loud failures |
| Alive span from `VenueClockOffset` | `data.py:2059-2082` | first..last sample under-states the span by ≤ 200 frames (conservative; quiet overnight feeds may drop days on tail span, counted in WP4) |
| Disk | `/` | **4.7 GB free: entry blocker** |

## 8. Risks → invariant → guard

| Risk | Invariant | Guard |
|---|---|---|
| Post-freeze read without cover | RA-13 B-3 | `require_firewall_clearance` with sha pin + RED tests; run gated on committed WP0 |
| NYC / undeclared-day print counted | B-3 scope | `admit_print` before any count + `test_nyc_prints_never_reach_a_count`; WP2 station filter |
| Print double-count; silent lost trade file | honesty of `C`/n, S-5 | `trade_id` dedupe; `TRADE_PARSE_FAILURE`; RED tests |
| Quiet overnight book read as outage | coverage honesty | liveness = alive span − gaps; no Depth10; tail-span-only count reported |
| Window end mis-set vs STALE_H | S-5 / S-1 honesty | constants from spec §3 + lag census; backstop test; S2 simulates the true schedule |
| Scratch in capture root / left behind; OOM, stall, basetemp fills `/` | capture read-only; one heavy job | root refusal + `finally` cleanup; studies slice, MemoryMax 4G, RuntimeMaxSec, flock, benchmark, Monitor; `~/.cache` basetemp, `rm` after EXIT |
| Test imports exec, trips the exec import pin | NO-SEND pins (L-12) | S1 tests never import `exec/`; pins in every focused gate |
| Unit flipped on a coincidental or cumulative print | S2 correctness | uniqueness, size-blind selection, set-size-1, n ≥ 2, SUMMED never counts; bracket never flips |
| Thresholds tuned after results; pin rewrite read as weakening | Stage 0 honesty; L-12 | constants in code before the run (change = plan revision); stricter pin + WP3 sign-off |

## 9. Effort and the evidence artifact

~**13.5 agent-hours** (WP0 1, WP1 5.5, WP2 2.5, WP3 1, WP4 1, reviews 2–3) + ≤ 1 h run, after 2026-10-14 10:00Z and
the disk gate. **Single evidence artifact:** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`.

## 10. Open questions for peer review (≤ 5)

1. **Q1 — programme SEARCH scope.** S5 shadow here forfeits most future station-days, leaving EDGE-4 revival to NYC.
   Rule it before S2? S-1 and S-4 both route here.
2. **ρ = 0.5 and the 0.2 target** (§2.1): acceptable as a labelled crude floor?
3. **S-5 margin:** `C < 0.05` STOP / `< 0.10` flag, given `C` is any-rung, queue-blind and already loose upward?
4. **Coverage constants:** `COVERAGE_MIN 0.90`, `LONGEST_HOLE_MAX_MIN 60` over the ≈ 23 h maker window.
5. **`NBP_LAG_UB_H = 2`** (01Z p95 98.4 min): adequate for a census window, given S2 owns the per-day schedule?

## 11. Review disposition

r1 dispositions are in r2 §11, verified by `reviews/S1-r2-final.md`; they carry into r3 unchanged. r2 §12 (spec
inputs) is absorbed into spec v0.3 and closed; only S5 SEARCH scope remains, as Q1.

### r3 conformance table

| Verdict item / spec v0.3 point | Plan § changed |
|---|---|
| Final #1, #3: header v0.3; Q5 and §12 absorbed (MINOR) | header (r3, READY, spec v0.3); §10 Q5 replaced; §12 deleted, closure in §11 |
| Final #2 unresolved unit → bracket, two USD hypotheses do not stop (MINOR) | §1 items 3–4; §2.2 S-2; WP2 `USD_BRACKET`, test `..bracketed_not_unresolved`; WP3 skip |
| Final #4 maker window ends at STALE_H-derived time, 09:00 LST backstop (MINOR) | §3.1 window derivation; WP1 `maker_window_ns`, constants, tests `..stale_derived_end`, `..backstop_binds..`; §7 lag-bound row |
| Residual: filter prints to four stations × declared days before counting (MINOR) | WP1 `admit_print`, script bullet, tests `test_nyc_prints_never_reach_a_count`, `..out_of_range_day..`; §8 row |
| Residual: cumulative fill records → SUMMED (MINOR) | WP2 SUMMED path (`client.py:933-957`), test `..multi_print_order_routes_to_summed` |
| Residuals: tail-span-only failures reported; TradeTick `default_convert` proven first (MINOR) | WP1 `tail_span_only` + test, first RED fixture; WP4; §7 |
| Spec §3 B_FLOOR 0.70 (dead "0.50 ≤ b") | §5.2 bid range and buckets; WP1 `PRICE_BUCKETS`; §2.2 S-5 |
| Spec §3 MAX_RUNGS 2 conditional, fallback 1 | §2.1 station-day unit (stricter, rung-independent); n_eff arithmetic 1.6/date, 41.6 best, S-4 ≤ 12.8 |
| Spec §6.0 verdict table, denominator, never GO; process schedule | §2.1, §2.2 S-5 (NO-GO pre-screen), §4, WP4 wording; §3.1 schedule owned by S2 |
| Spec §6.1 trade-through/Q₀/episodes/2×; §6.9 10-loss minimum, UNSCREENED ≠ PASS | §3.1 (S2's), §5.2 buckets (p_yes < 0.20 = Q₀ reducer); §2.1 power line, WP4 |
| Spec §4, §6.2, §6.3, §6.5–§6.7, §7.3 | not S1's scope; no S1 statement contradicts them (no LD-OBF, 60/40, or GO text remains) |
