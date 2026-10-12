# S1 — Stage 0 preconditions (maker-window print census + TRADE_QUANTITY_UNIT)

| Field | Value |
|---|---|
| ID | S1 |
| Title | Stage 0 preconditions: maker-window print census, LAX/MDW/MIA/SFO, climate days 2026-09-18..2026-10-13; resolve `TRADE_QUANTITY_UNIT` |
| Revision | r2 (supersedes r1; disposition of both r1 reviews in §11) |
| Date | 2026-10-12 |
| Status | READY-FOR-REVIEW (planning only; nothing built, nothing run) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2, §3, §6.0, §6.1, §7.6, §9.3, §9.4 |

## 1. Goal state (acceptance test)

S1 is done when these exist on the branch:

1. **A committed censused-day list**, `~/.local/share/breezy/derived/maker/s1/censused_days.jsonl` (sha256 in the
   doc): one row per (station, climate_day), LAX/MDW/MIA/SFO, 2026-08-30..2026-10-13, closed `reason` alphabet (WP1),
   with coverage, BUYER prints per YES-price bucket, SELLER/NO_AGGRESSOR counts, `first_seen_ns`. **No Depth10 is read.**
2. **Numbers computed by the script, never by hand:** `N_cov` covered station-days, `D_cov` distinct covered climate
   dates, `n_eff_ub` (clustered upper bound on Stage 0 bid units, §2.1), and the fillability ceiling `C` = covered
   station-days with ≥ 1 BUYER print at p_yes ≥ 0.20 in the maker window ÷ `N_cov`.
3. **A unit verdict.** `TRADE_QUANTITY_UNIT` ∈ {`CONTRACTS`, `USD_NOTIONAL_YES`, `USD_NOTIONAL_TAKER`} from matching
   own create-path fills to unique recorded prints, or the explicit token `UNRESOLVED` with the surviving hypothesis set.
4. **The constant recorded** (`parsing.py:231`) only if item 3 resolved, with its pin test rewritten RED→GREEN.
5. **One evidence doc**, `docs/evidence/MAKER-S1_preconditions_<run-date>.md`, with items 1–4, the empirically checked
   YES→NO inversion (§5.3), the net SEARCH forfeiture tally, and the `census_provenance:` line.

## 2. Entry criteria and STOP conditions

**Entry (all required):**
- Worktree off `feat/data-capture-and-risk`, fast-forwarded first; every command carries `PYTHONPATH=<wt>/src`; no
  uv/pip/`uv run` from the worktree; never `git stash`.
- **≥ 10 GB free on `/`.** Measured 2026-10-12: **4.7 GB free (100 %)**. No gate or run starts until a coordinator frees
  space; S1 never deletes tape.
- Recorder active; `breezy-studies.lock` free. **WP0 committed** before any climate day > 2026-09-25 is read (WP1, WP2).

### 2.1 The floor, derived (replaces r1's bare "E ≥ 25")

The Stage 0 kill is "fill rate < 0.1" (spec §6.0); the floor keeps noise from firing it on a viable family.
- **Target:** false-kill probability ≤ 5 % when the true per-bid fill rate is 0.2 (2× the kill line; spec §9.15 plans
  on 0.3). Binomial: at n = 30, P(X ≤ 2 | p = 0.2) = 0.044. So **n_eff ≥ 30 bid units**.
- **Clustering:** the unit is the climate date (spec §6.2). A date carries m_d ≤ 2 × (covered station-days on d) bids
  (≤ 2 rungs per station-day, spec §3). Within-date correlation **ρ = 0.5 is ASSUMED, not measured**.
- **Formula:** `n_eff_ub = Σ_d m_d / (1 + (m_d − 1)·ρ)`. A full date (m = 8) contributes 1.78, so ≈ 17 fully covered
  dates are needed. The best case for 2026-09-18..10-13 (26 dates) is ≈ 46.
- **Upper bound:** how many rungs the rule bids needs the forecast (S2's job), so S1's floor is **necessary** only; S2
  re-checks on real bids.
- **Status: crude, exploratory** (Stage 0 is never promotion evidence); ρ and the 0.2 target are labelled assumptions.

### 2.2 STOP conditions

- **S-1 (UNDERPOWERED):** `n_eff_ub < 30` after the full run. S1 ends UNDERPOWERED. The evidence doc states the
  declaration extension Stage 0 would need (dates after 2026-10-13 at the measured n_eff per date, and their net
  forfeiture cost) and routes it to **Q1** (programme-level SEARCH ruling). The eligibility rule is never relaxed.
- **S-2 (unit):** verdict `UNRESOLVED`: §6.1 cannot run; the constant stays; the doc records the surviving hypothesis
  set (e.g. "USD, YES vs taker undecided") for the spec owner to rule on bracketing (Q5).
- **S-3 (premise break):** any own fill whose window holds no inversion-consistent print but ≥ 1 anti-candidate (a NO
  taker printing BUYER or at price = cost; a YES taker printing SELLER). §5.3 is then false. STOP and return to the spec.
- **S-4 (firewall refused):** WP0 not endorsed. Pass A alone is ≤ 8 dates × 4 stations = 32 station-days, so
  `n_eff_ub ≤ 14 < 30` by construction: **S1 ends UNDERPOWERED, routes to Q1.** No "wait": later days are post-freeze too.
- **S-5 (fillability ceiling):** a resting NO bid at b ≤ 0.80 fills only on a BUYER print at p_yes ≥ 1 − b ≥ 0.20 on its
  rung (§5.3), so the per-bid fill rate is at most about `C` (any-rung, so loose upward). **`C < 0.05` → STOP the family
  at v0.2 with no S2 build** (Stage 0's kill would fire by construction; the 0.05 margin covers bid-day selection).
  `0.05 ≤ C < 0.10` → flag `KILL-LIKELY` and proceed to S2. Payoff: S1 can retire S2–S5 for the cost of one census.

## 3. Simplest direct path

### 3.1 Path

(1) WP0: one dated SEARCH declaration (docs). (2) WP1: a ~250-line sidecar that, per CLEAN instance, natively converts
four **small** streams (`BinaryOption`, `QuoteTapeGap`, `VenueClockOffset`, `TradeTick`, ~2–8 MB each) into a scratch
catalog, counts deduped prints per station-day in the maker window, and deletes the scratch. One run. (3) WP2: match the
28 create-path own fills to unique prints. (4) WP3: flip one constant if resolved.

Why the AUD-09a census is not reused or parameterised (verified): its window is `[12:00, 17:00)` LST on D
(`replay_sufficiency.py:207-222`), disjoint from `[D−1 12:00Z, D 09:00 LST)`; `ReplaySufficiency` has no print counts
and 20 callers incl. `promotion_criteria`; its span-cache key has no window identity (`instance_span_cache.py:84-85`), so
a second window would poison `DEFAULT_INSTANCE_SPANS_PATH`; it converts QuoteTick + Depth10 per CLEAN instance
(`tape_instruments._convert_live_capture:121-148`), disk-heavy at 4.7 GB free; and the maker window crosses the 09:00Z
rotation, so it is a union of two instances, not one winning instance.

Why **no Depth10**: S1 asks "was the recorder alive" and "did fill-capable prints happen" — liveness and prints only.
Overnight books are quiet, so Depth10 spacing would misread quiet as outage. Queue/book conditions are S2's.

### 3.2 RA-13 B-3 and the SEARCH cost

- B-3 binds the corpus, not the statistic: any count on post-2026-09-25 tape spends those station-days' H-ARCHIVE-RECAL
  CONFIRM status (`RULING_RA-13_programme_kill_2026-09-27.md:89-92`); only an explicit SEARCH declaration with the cost
  in both plans licenses it (`EDGE-4_DISPOSITION_2026-09-27.md:19`). Carve-outs are named only (AUD-09a, replay-daily;
  `RA-13-FW_firewall_audit_2026-09-27.md:13-14`); the exit-window ruling (`RA-13-FW:21-29`) is the template; TE-3 read
  nothing after 09-25 (`RULING_TE-3_NO_CHEAP_LONGSHOT_2026-10-11.md:5,49`). A census does **not** lift B-3; WP0 does.
- **Pass B is required** (S-4 arithmetic): trade capture starts 2026-09-17 09:00Z, so the pre-freeze maker sample is
  climate days 09-18..09-25 only. Pass A and Pass B are therefore one run.
- **Net cost.** Gross scope 4 stations × 18 days (09-26..10-13) = 72 station-days. **14 are already SEARCH** because the
  nightly exit-window study read their Depth10 for FQ-live fill exits: LAX 10-02..10-06; MDW 10-02, 10-04, 10-05, 10-06;
  MIA 10-03, 10-05; SFO 10-03, 10-04, 10-06 (instrument ids in `derived/exit_window_study/2026-10-0*_nightly/
  exit_window_study.json`, read 2026-10-12; WP0 re-verifies and cites). **Net new forfeiture ≤ 58 station-days.** At the
  ~5/day EDGE-4 accrual this delays revival by ≈ 12 days, from ≈ 2026-11-24 to ≈ 2026-12-06, inside the 2027-01-25
  backstop. NYC is untouched.
- **Programme flag (not S1's decision, Q1):** an S5 shadow run on these four stations makes most future station-days
  SEARCH, leaving revival to NYC (~1/day), which cannot fire before the backstop.

## 4. Invariants (restated; S1 respects every one)

- Nautilus immutable (native types, `ParquetDataCatalog`, `default_convert` only); `allow_short` stays `False`; no value
  for max daily budget / max per position; live enablement, `BREEZY_ORDERS_ENABLED`, A1 halt untouched; no frozen
  PREREG.json edited, no pre-registered date moved; FQ-v2 NO-TRADE ruling in force; no safety/settlement/contract/NO-SEND
  test weakened (exact-set barriers widen by one reviewed row, L-12); Stage 0 output EXPLORATORY only.
- **S1 makes zero network calls**; exec sqlite opened `mode=ro`; the capture root is read-only (scratch catalogs live
  under `~/.cache/breezy/maker-s1-work/`, refused if inside the capture root, as `_convert_live_capture:129-135` does).
- Rewriting `test_the_print_size_unit_is_declared_unresolved` is not weakening a guard: the new pin is stricter.

## 5. Nautilus null-hypothesis check

### 5.1 Native capability per need

| Need | Native / existing capability | Evidence | Gap? |
|---|---|---|---|
| Print with direction | `TradeTick` + `AggressorSide` | built `parsing.py:993-1001`; `_TAKER_SIDES` `parsing.py:283-290` | none |
| Print identity across instances | `TradeTick.trade_id` = sha256 over venue-only fields (slug, tradeTime, price, qty, taker.side) | `parsing.py:940-948,981-991` | none; dedupe key |
| Raw feather → catalog | `default_convert(source, instance_id, cls, "live", target=work)` | `quote_tape_ingest_core.py:742-776`; used by `_convert_live_capture` | none |
| Gap records, collapsed + partitioned | `load_partitioned_quote_tape_gaps(catalog)` → `resolved_gaps_by_seq` | `quote_tape_gaps.py:86-106`; flat reads refused `:56-61,79-83` | none; reuse |
| Recorder liveness span | `VenueClockOffset` series, one record per 200 quote frames, flat per instance | `data.py:294,2059-2082` | none; reuse (span = first..last `ts_init`) |
| Instance classification | `scan_instance` / `classify_instance` | `feather_preflight.py:525`; `cli_basis_offer_gate_scan.py:391` | none; reuse |
| Rung identity | `read_weather_bucket_facts(instrument.info)` | `weather_bucket_facts.py:90-124` | none |
| Maker fill matching (S2) | `BacktestVenueConfig(trade_execution=True, queue_position=True)`; SELLER trade fills resting BUY | `docs/reference/nautilus/v1.231.0/concepts/backtesting/trade-execution.md:3,29-34,46,96` | none, but caps at `trade.size` in instrument units, so the unit verdict is S2's precondition |
| Venue quantity unit | none; a venue fact | — | **missing: WP2** |
| Maker-window print census | none; AUD-09a is afternoon-only | `replay_sufficiency.py:207-222` | **missing: WP1** |
| Post-freeze firewall | governance | §3.2 | **WP0 + refusal in WP1/WP2** |

### 5.2 Bound for S2

PM.us prints arrive on the YES instrument only (`parsing.py:936-938`); S2 derives NO-frame ticks via §5.3 (S1 verifies).

### 5.3 YES→NO inversion for a NO maker bid

- A resting **BUY NO at b** goes out as `ORDER_SIDE_SELL` / `ORDER_INTENT_BUY_SHORT` at wire price `1 − b`
  (`leg_prices.py:39-46,56-75`): a **YES ask at 1 − b**.
- Only a YES print with **aggressor BUYER at p_yes ≥ 1 − b** can fill it ≡ NO-frame **SELLER at ≤ b**, matching
  Nautilus's "SELLER trade fills resting BUY". YES SELLER prints are NO buyers taking: they compete, never fill.
- With 0.50 ≤ b ≤ 0.80, p_yes ∈ [0.20, 0.50) fills some bids and p_yes ≥ 0.50 any bid (hence WP1's buckets). A print far
  above a tail rung's ask means cheaper asks were swept: the §6.9 adverse-selection signature; S2 conditions on it.
- "NO seller closing" vs "YES buyer opening" is indistinguishable by design (parser ignores `intent`) and irrelevant.
- Taker-side check (WP2): our NO IOC buys must print **SELLER at 1 − cost**, YES buys **BUYER at cost**; else S-3.

## 6. Work packages

Every focused gate:
`PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/python -m pytest <tests> tests/unit/test_polymarket_us_fee_guard.py <exec-import-pin + NO-SEND firewall tests> --basetemp ~/.cache/breezy-pytest/s1-<wp>`; read the exit code
(not `-q`), then `rm -rf` the basetemp; `cd <wt> && lint-imports` must print "N kept, 0 broken". Format only own files.

### WP0 — SEARCH declaration (docs only; ~1 h)

- **Create** `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`: basis (§3.2); scope LAX/MDW/MIA/SFO ×
  climate days 2026-09-26..2026-10-13, NYC excluded; covers S1 and S2 Stage 0 reads only, never S5; the net cost
  table (72 gross, 14 already SEARCH with source, ≤ 58 net, date effect); the per-fill list WP2 will read.
- Record the same cost in the H-ARCHIVE-RECAL/AUD-18 record ("both plans"). Blind review by prediction-market-reviewer
  and architect → `reviews/S1-WP0-*.md`. **Done when** committed; its sha256 is the value WP1 pins.

### WP1 — maker-window print census (~5 h build, run ≤ 1 h projected)

**Create `src/breezy/analysis/maker_tape_census.py`** (pure, ~130 lines, no Nautilus import, no pyarrow; satisfies
"The offline analysis layer never DIRECTLY imports Nautilus", `pyproject.toml:163`). It operates on plain ints/strings.
- Constants (fixed before any run; changing one needs a plan revision): `PRE_FREEZE_END = date(2026, 9, 25)` (same
  name and value as `nbp_market_comparison.py:72`; scripts not refactored), `TRADE_CAPTURE_START_NS` =
  2026-09-17T09:00Z, `MAKER_STATIONS = frozenset({"LAX","MDW","MIA","SFO"})`, `SEARCH_DECLARED = ("LAX,MDW,MIA,SFO",
  date(2026,9,26), date(2026,10,13))`, `SEARCH_DECLARATION_SHA256` (WP0's), `COVERAGE_MIN = 0.90`,
  `LONGEST_HOLE_MAX_MIN = 60`, `RHO_ASSUMED = 0.5`, `N_EFF_FLOOR = 30`, `C_STOP = 0.05`, `C_FLAG = 0.10`,
  `PRICE_BUCKETS = ((0, 0.10), (0.10, 0.20), (0.20, 0.50), (0.50, 1.01))`.
- `maker_window_ns(*, climate_day, std_utc_offset_hours) -> tuple[int, int]` = `[D−1 12:00Z, D 09:00 LST)`, integer
  arithmetic.
- `require_firewall_clearance(station, day, declaration_sha256: str | None) -> Literal["PRE_FREEZE","SEARCH_DECLARED"]`
  raises `FirewallRefused` for a station outside `MAKER_STATIONS`, or a day > `PRE_FREEZE_END` that is outside
  `SEARCH_DECLARED` or whose supplied sha256 ≠ the pinned one. No markdown parsing.
- `covered_intervals(window, alive_spans, gaps) -> tuple[tuple[int,int], ...]`: union of instance alive spans clipped
  to the window, minus every gap interval of the station-day's instruments (an unresolved gap runs to `+∞`).
- `CensusedDay` (frozen): station, climate_day, firewall_class, reason, coverage_fraction, longest_hole_min,
  buyer_by_bucket (4 ints), prints_seller, prints_no_aggressor, rungs_with_qualifying_buyer, first_seen_ns,
  instances_clean, instances_corrupt. Explicit `to_dict`/`from_dict`, no `asdict`.
- `classify(...) -> CensusedDay`. Closed `reason`: `PRE_TRADE_CAPTURE` (window start < `TRADE_CAPTURE_START_NS`; emitted
  **without reading tape**, excluded from every denominator), `NO_CLEAN_INSTANCE`, `CORRUPT_ONLY`,
  `TRADE_PARSE_FAILURE`, `LOW_COVERAGE`, `LONG_HOLE`, `COVERED`.
- `summarise(rows) -> CensusSummary`: `N_cov`, `D_cov`, `n_eff_ub` (§2.1), `C`, which STOP (S-1/S-5) fires or the flag.
- `write_censused_days` / `read_censused_days`: sorted, byte-idempotent JSONL; refuses unknown keys and duplicate
  (station, day).

**Create `scripts/analysis/maker_tape_census.py`** (I/O layer, ~150 lines).
- Flags: `--from`, `--to`, `--stations`, `--search-declaration PATH` (sha256 checked against the pin), `--output`,
  `--catalog-root` (default `~/.local/share/breezy/catalog/quote_tape/polymarket_us`), `--work-root` (default
  `~/.cache/breezy/maker-s1-work`).
- Per instance: `scan_instance` + `classify_instance`; only CLEAN is read; LIVE/CORRUPT counted into rows.
- Per CLEAN instance: `default_convert` the four small classes into `<work-root>/<instance_id>`; `work.query` them;
  gaps via `load_partitioned_quote_tape_gaps(work)` per `GapPartitionKey`; alive span = first..last `VenueClockOffset`
  `ts_init`; cleanup via `replay_sufficiency_census._cleanup_work_catalog` in a `finally`.
- Any conversion/deserialise failure of `TradeTick` for an instance → every station-day it touches gets
  `TRADE_PARSE_FAILURE` (never a silent lower count).
- Prints are **deduplicated on `trade_id` across instances** (overlapping rotation instances see the same print).
  Bucketed on YES price; BUYER counted per bucket; per-rung qualifying BUYER counted via `read_weather_bucket_facts`.
- `first_seen_ns` = earliest `BinaryOption.ts_init` for (station, day) across instances; diagnostic, so a structural
  listing gap is not misread as a tape shortage; the evidence doc counts rows with `first_seen_ns` > window start.
- Emits `census_provenance:` (git sha, stations, range, declaration sha256, instance count) and one stderr progress line
  per instance (the stall watch keys on it).

**RED-first tests** (`tests/unit/test_maker_tape_census.py`):
`test_maker_window_spans_d_minus_1_noon_utc_to_d_0900_lst`, `test_post_freeze_day_refused_without_matching_declaration_sha`,
`test_post_freeze_day_outside_declared_range_refused`, `test_nyc_is_refused_even_with_declaration`,
`test_pre_trade_capture_rows_are_emitted_without_reading_tape`,
`test_unresolved_gap_contaminates_to_window_end`, `test_coverage_is_alive_span_minus_gaps_not_book_density`,
`test_a_print_seen_by_two_overlapping_instances_counts_once`, `test_seller_and_no_aggressor_prints_never_qualify`,
`test_buyer_print_below_020_never_qualifies`, `test_n_eff_ub_matches_hand_formula_for_mixed_dates`,
`test_c_below_005_fires_s5`, `test_censused_days_round_trip_refuses_extra_keys_and_duplicates`,
`test_write_is_byte_idempotent_regardless_of_input_order`; script-level (tmp raw-feather fixture written through the
streaming writer as in `test_gaps_and_offsets_survive_the_streaming_writer_and_the_catalog`):
`test_live_instance_is_counted_never_read`, `test_trade_tick_parse_failure_refuses_the_station_day`,
`test_work_catalog_is_removed_and_capture_root_untouched`.

**Run** (after review; not under this plan): (a) **subset benchmark**: one instance under `/usr/bin/time -v`, record
wall and peak RSS; (b) **one run**, `--from 2026-08-30 --to 2026-10-13`, only after WP0 is committed and **at/after
2026-10-14 10:00Z** (the 10-13 window ends inside the 10-13 boot instance, LIVE until the 09:00Z rotation), clear of the
15:20Z/15:50Z studies:
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

**Create `src/breezy/analysis/trade_quantity_unit.py`** (pure, ~80 lines).
- `UNIT_HYPOTHESES = ("CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER")`.
- `OwnFillMatch` (frozen): leg, fill_cost, fill_qty, candidate_count, anti_candidate_count, print_price_yes,
  print_size, summed: bool.
- `predicted_size(h, m)`: CONTRACTS → `fill_qty`; USD_NOTIONAL_YES → `print_price_yes × fill_qty`;
  USD_NOTIONAL_TAKER → `fill_cost`. Compared by exact Decimal equality at the print's own precision.
  NO fill at 0.12 predicts (1, 0.88, 0.12); a YES fill at c predicts (1, c, c), so YES matches separate CONTRACTS from
  USD but never the two USD hypotheses. Fractional contracts fall under CONTRACTS (no integer test).
- `classify_trade_quantity_unit(matches) -> tuple[str, frozenset[str], str]` (verdict, surviving set, reason). A match
  **counts** only if `candidate_count == 1` and not `summed`. Resolve iff counted n ≥ 2 **and** the set of hypotheses
  consistent with every counted match has **size 1**. A counted match consistent with no hypothesis → `UNRESOLVED`
  (contradiction reported). A `SUMMED` match (sum of same-side, same-price prints in the window, admissible only when
  no single print matches) is reported and may confirm, never count.
- `inversion_verdict(m) -> Literal["HOLDS","CONTRADICTED","NO_PRINT"]`: `CONTRADICTED` iff `candidate_count == 0` and
  `anti_candidate_count ≥ 1` (feeds S-3).

**Create `scripts/analysis/trade_quantity_unit_crosscheck.py`** (~110 lines).
- Reads `exec/polymarket_us/fill/*` from `~/.local/share/breezy/state/exec_polymarket_us.sqlite` (`mode=ro`); keeps a
  fill only if `tsEvent ≥ TRADE_CAPTURE_START_NS`, `tradeId` is a venue id (not `GET-…`, not null; **resolver
  `tsEvent` is discovery time and is never matched**), `feeReconciled` is True (else `cumulativeCost` may embed fee;
  refused), and the station is in `MAKER_STATIONS`. Each kept fill passes `require_firewall_clearance`.
- Prints every fill key, tsEvent, climate day, provenance, keep/refuse reason. Verified 2026-10-12 (read-only): **28 kept** (09-21 MIA NO 0.12, 09-21 SFO YES 0.35, 09-22 MDW NO 0.12, plus 25 YES fills 10-01..10-05 on climate days
  10-02..10-06, no NYC); 6 excluded (one null `tradeId`, one `GET-` resolver, four before trade capture).
- Clock: create-path `tsEvent` is the venue `Execution.transactTime` (`reports.py:1356-1360`), the same venue clock as
  the print's `tradeTime`, so the window is **±5 s** with no host-offset correction.
- Candidate selection uses **side + price + time only, never size** (else the test is circular): on
  `yes_instrument(instrumentId)` (`capture_audit_fill_support.py:183`), NO leg → SELLER at `1 − cost`, YES leg → BUYER
  at `cost`; anti-candidates are the opposite aggressor or the un-inverted price. Prints come from the WP1 conversion
  path (dedupe on `trade_id`), CLEAN instances only. Every candidate is listed; none is silently picked.
- Writes one JSON result and prints verdict, surviving set and per-fill inversion verdicts.

**RED-first tests** (`tests/unit/test_trade_quantity_unit.py`): `test_no_leg_fill_separates_all_three_hypotheses`,
`test_yes_only_matches_resolve_contracts_but_not_usd_split`, `test_two_candidates_make_a_match_not_count`,
`test_disagreeing_matches_are_unresolved`, `test_fewer_than_two_counted_matches_are_unresolved`,
`test_summed_match_never_counts`, `test_inversion_contradicted_needs_zero_candidates_and_an_anti_candidate`,
`test_resolver_and_unreconciled_fills_are_refused`, `test_post_freeze_fill_refused_without_declaration`,
`test_crosscheck_opens_exec_db_read_only`.

**Done when:** tests GREEN; verdict, surviving set and inversion result emitted by the script; S-2/S-3 evaluated.

### WP3 — record the unit (~1 h; only if WP2 resolved)

- **Modify `src/breezy/adapters/polymarket_us/parsing.py:225-231`**: `TRADE_QUANTITY_UNIT: str = "<verdict>"`; comment
  cites the evidence doc and matched fills; update the `parse_trade_tick` docstring line "**size is unit-unresolved**"
  (`:950`). No unit conversion in the parser: recorded tape stays byte-stable; conversion is S2's.
- **Modify `src/breezy/adapters/polymarket_us/data.py:1863-1866`**: the log text interpolates the constant instead of the
  literal "is UNRESOLVED". No other behaviour change.
- **Modify `tests/unit/test_polymarket_us_depth_parsing.py:431-438`**: write
  `test_the_print_size_unit_is_resolved_by_own_fill_crosscheck` first (RED against `"UNRESOLVED"`), asserting the value
  and that `docs/evidence/MAKER-S1_preconditions_*.md` names it; then flip the constant (GREEN); remove the old pin.
- Gate: focused, then **full** `scripts/ci/run_tests_no_egress.sh --basetemp ~/.cache/breezy-pytest/s1-full` (under
  `systemd-run -p LimitNOFILE=524288`); read EXIT before merge/push; `rm` the basetemp.
- **Activation:** next scheduled 09:00Z rotation/node spawn; no manual restart (it would cut a capture hole S2/S5 need).

### WP4 — evidence doc + PROGRESS row (~1 h)

- **Create** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`: `N_cov`, `D_cov`, `n_eff_ub` (with ρ labelled
  assumed), `C` by station and bucket table; rows by reason; `first_seen_ns` late-listing count; jsonl sha256 and row
  count; provenance line; unit verdict, surviving set and per-fill match table; inversion result; net forfeiture
  actually incurred (station-days read post-freeze minus the 14 already SEARCH); which STOP fired; the §6.1 erratum.
- One-line row in `docs/core/PROGRESS.md`. Commit at the milestone; push only after a green gate, EXIT read.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| Raw tape (81 instances) | `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live/<uuid>/` | present; `trade_tick/` in 27, `custom_quote_tape_gap/` in 52, flat `custom_venue_clock_offset_*.feather` (~2 MB) |
| Trade capture start | commit `4d6bb059` (2026-09-16); first journal evidence 2026-09-17 09:00Z | VERIFIED (journal, r1) |
| Durable fills | `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, table `state`, keys `exec/polymarket_us/fill/<venueOrderId>` | VERIFIED 2026-10-12: 34 rows, 28 kept (§6 WP2) |
| Already-SEARCH station-days | `~/.local/share/breezy/derived/exit_window_study/*_nightly/exit_window_study.json` | 14 found 2026-10-12; WP0 re-verifies |
| Native conversion of `QuoteTapeGap`/`VenueClockOffset` | `default_convert` | ingest markers `.converted-custom_quote_tape_gap` / `-custom_venue_clock_offset` exist on instances, so the path works; first script RED fixture re-proves it |
| `TradeTick` via `default_convert` into a scratch catalog | — | **UNVERIFIED** (no existing caller converts `trade_tick` to a target); fallback: deserialize the raw stream with `ArrowSerializer` as `_load_stream` does, keeping trade_id dedupe and loud failures |
| Alive span from `VenueClockOffset` | `data.py:2059-2082` | first..last sample under-states the span by ≤ 200 frames (conservative); a silent feed publishes none, so a zombie recorder ends its span |
| Disk | `/` | **4.7 GB free: entry blocker** |

## 8. Risks → invariant → guard

| Risk | Invariant | Guard |
|---|---|---|
| Post-freeze read without cover | RA-13 B-3 | `require_firewall_clearance` with sha pin + RED tests; run gated on committed WP0 |
| NYC read | B-3 scope | closed `MAKER_STATIONS` + test; WP2 station filter |
| Print double-count across rotation | honesty of `C`/n | dedupe on `trade_id` + RED test |
| Silent lost trade file lowers counts | honesty of S-5 | `TRADE_PARSE_FAILURE` refuses the station-day |
| Quiet overnight book read as outage | coverage honesty | liveness = alive span − gaps; no Depth10 |
| Scratch catalog written into the capture root, or left behind | capture is read-only evidence; disk | root-inside-capture refusal; `finally` cleanup; test |
| OOM/stall; basetemp fills `/` | one-heavy-job rule; host stability | studies slice, MemoryMax 4G, RuntimeMaxSec, flock, benchmark, Monitor; ≥ 10 GB entry, `~/.cache` basetemp, `rm` after EXIT |
| Test imports exec, trips the exec import pin | NO-SEND pins (L-12) | S1 tests never import `exec/`; pins in every focused gate |
| Unit flipped on a coincidental print | S2 correctness | uniqueness, size-blind selection, set-size-1, n ≥ 2, SUMMED never counts |
| Thresholds tuned after results; pin rewrite read as weakening | Stage 0 honesty; L-12 | constants in code before the run (change = plan revision); stricter pin + WP3 sign-off |

## 9. Effort and the evidence artifact

~**13 agent-hours** (WP0 1, WP1 5, WP2 2.5, WP3 1, WP4 1, reviews 2–3) + ≤ 1 h run, after 2026-10-14 10:00Z and the
disk gate. **Single evidence artifact:** `docs/evidence/MAKER-S1_preconditions_<run-date>.md`.

## 10. Open questions for peer review (≤ 5)

1. **Q1 — programme SEARCH scope.** S5 shadow here forfeits most future station-days, leaving EDGE-4 revival to NYC.
   Rule it now, before S2? S-1 and S-4 both route here.
2. **ρ = 0.5 and the 0.2 target** (§2.1): acceptable as a labelled crude floor?
3. **S-5 margin:** `C < 0.05` STOP / `< 0.10` flag, given `C` is any-rung and already loose upward?
4. **Coverage constants:** `COVERAGE_MIN 0.90`, `LONGEST_HOLE_MAX_MIN 60` over a 26–29 h liveness window.
5. **Partial verdict:** if WP2 leaves {USD_NOTIONAL_YES, USD_NOTIONAL_TAKER}, may S2 bracket them (they differ only on
   NO-leg prints)?

## 11. Review disposition

Conflicts. PM-1 wanted Depth10 conditions (non-empty YES-ask snapshots; "rung whose YES ask ≤ 0.10"); architect-1 and
the coordinator say no Depth10. **Followed the architect:** book/queue state is S2's simulator; the any-rung BUYER count
only errs toward continuing. PM-5 wanted "≥ 2 unique NO-leg matches", architect-4 "set of size 1, n ≥ 2". **Followed the
architect:** YES matches validly split CONTRACTS from USD, and set-size-1 forces NO-leg evidence whenever the answer is
USD; PM-5's uniqueness requirement is adopted in full.

| Review file | # | Disposition |
|---|---|---|
| S1-r1-architect | 1 MAJOR (Depth10 via column scan false) | ACCEPTED — §3.1, WP1: no Depth10 read at all |
| S1-r1-architect | 2 MAJOR (gap reader; coverage) | ACCEPTED — WP1: native convert + `load_partitioned_quote_tape_gaps`; coverage = alive span − gaps (§2/WP1) |
| S1-r1-architect | 3 MAJOR (`_load_stream` double-count, silent failure) | ACCEPTED — dedupe on `trade_id`; `TRADE_PARSE_FAILURE`; RED tests |
| S1-r1-architect | 4 MAJOR (F1 can't meet NO-leg rule; drop F2) | ACCEPTED — set-size-1 rule; F2 deleted; F1 folded into one 28-fill pass (verified YES-only, no NYC) |
| S1-r1-architect | 5 MAJOR (S-1/S-4 assume readable future tape) | ACCEPTED — §2.2 S-1 names the extension and routes to Q1; S-4 = UNDERPOWERED → Q1; Pass B required |
| S1-r1-architect | 6 MINOR (gross vs net cost) | ACCEPTED — §3.2: 14 already SEARCH, ≤ 58 net |
| S1-r1-architect | 7, 8 MINOR (pre-capture days; `PRE_FREEZE_END`) | ACCEPTED — `PRE_TRADE_CAPTURE` rows without reading; WP1 constant name |
| S1-r1-architect | 9, 10 MINOR (listing; fee-inclusive cost) | ACCEPTED — `first_seen_ns` + WP4 count; `feeReconciled` False refused (all 28 kept are True) |
| S1-r1-architect | 11, 12 MINOR (markdown parsing; NYC in F1) | ACCEPTED — sha256 pin, no parser; station filter, verified no NYC |
| S1-r1-architect | cited-vs-actual | FIXED — `feather_preflight.py:525`, `cli_basis_offer_gate_scan.py:391`, TE-3 `:5,49`, gap loader `quote_tape_gaps.py:86-106` |
| S1-r1-prediction-market-reviewer | 1 MAJOR (eligibility measures wrong flow) | ACCEPTED in part — BUYER at p_yes ≥ 0.20 by bucket, `C`, S-5. REBUTTED in part (Depth10 conditions) — see conflict note |
| S1-r1-prediction-market-reviewer | 2 MAJOR (25 is bare) | ACCEPTED — §2.1 derived `n_eff_ub ≥ 30`, clustered by climate date, assumptions labelled |
| S1-r1-prediction-market-reviewer | 3 MAJOR (pre-capture days pollute the rate) | ACCEPTED — `PRE_TRADE_CAPTURE`, excluded from denominators |
| S1-r1-prediction-market-reviewer | 4 MAJOR (resolver tsEvent) | ACCEPTED — provenance checked: all 28 kept are create-path (venue `tradeId`); resolver fills refused, not window-widened; create `tsEvent` = venue `transactTime` (`reports.py:1356-1360`) |
| S1-r1-prediction-market-reviewer | 5 MAJOR (coincident print) | ACCEPTED (uniqueness, size-blind selection); "≥ 2 NO-leg" REBUTTED — see conflict note |
| S1-r1-prediction-market-reviewer | 6, 7 MINOR (sums; inversion additions) | ACCEPTED — SUMMED never counts, fractional under CONTRACTS; §5.3 buckets + intent statement |
| S1-r1-prediction-market-reviewer | 8, 9 MINOR (coverage denominator; F1 NYC) | ACCEPTED — `covered_intervals` formula, no Depth10; verified no NYC |

## 12. Spec v0.3 inputs (not S1's to fix)

1. **§6.1 inversion erratum:** "YES print at price ≤ 1 − b with aggressor SELLER" is wrong-frame. Correct: YES print
   `p_yes ≥ 1 − b`, aggressor **BUYER** ≡ NO-frame SELLER at ≤ b.
2. **§6.0 start date:** prints exist only from 2026-09-17 09:00Z; Stage 0's effective first climate day is 09-18.
3. **§6.0 / §9.4:** "B-3 may bar reads until a census is run" is wrong; only a SEARCH declaration (WP0 scope) lifts it.
4. **Stage 0 denominator:** fill rate must be over all covered bid-bearing station-days, never over print-eligible days.
5. **§6.1 unit precondition:** the hypotheses are three (contracts, USD YES notional, USD taker notional), not two; and
   the spec should rule whether a USD-only partial verdict may be bracketed (Q5).
6. **§2 / §9.3 cite:** `parsing.py:225-232` → `:225-231`. 7. **S5 SEARCH scope** (Q1) belongs in the spec explicitly.
