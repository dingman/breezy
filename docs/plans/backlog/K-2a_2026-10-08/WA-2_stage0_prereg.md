# WA-2: K-2a Stage 0 pre-registration (TWC-vs-CLI settlement reconciliation), DRAFT for review

**Frozen at:** git `<SHA of the commit that freezes this file after review>`, 2026-10-08. The draft was written before any fetch and without looking at outcomes. Author: planner, transcribed by the coordinator. Status: DRAFT until the WA-2 review converges.

**Source.** `K-2a_kalshi_plan_r2.md`, read with its precedence rule: the Convergence amendments B1–B4/N1–N5 and the r2.1 delta R1–R6 govern.

**Executed by.** WB-1, which is K-2b work (programme KILL, then N-S START). Nothing in this document authorises a fetch now.

**What would change this document.** Only a named peer-loop ruling that amends a numbered section, appended as a dated delta.
- A WB-1 finding never edits this document. Examples: an API parameter is rejected, a body exceeds its cap, a field changes shape. In those cases WB-1 stops, records the finding, and waits for a ruling.
- These are never tuned against observed outcomes: z, 0.99, N_s, F_H, the holdout window, and 2027-12-31.

## Draft decisions flagged for review
1. The body cap and request budget live in a Stage 0 subclass of k1 `KalshiHttp`. k1 `get_json` (`scripts/analysis/k1_kalshi_prior.py:896-937`) reads the whole body with no cap or counter, and k1 must stay byte-unchanged.
2. Whether `status=finalized` works as a list filter is unverified. A 400 on that pass is recorded as `FILTER_UNSUPPORTED`. The `status` value in each response is what binds.
3. Kalshi-side failures count as misses: refusals, voids, disputes, amendments, and events stuck unsettled. A missing CLI final is "not comparable": it is excluded from n and listed.
4. The holdout seal (§8.6) is added: outputs for climate days ≥ F_K carry aggregate counts only.
5. 19 of the 24 CLI stations are not in the sites registry. Stage 0 passes its own fixed station set and never edits the registry.
6. k1 `list_series_markets` keeps the first copy of a duplicate (`setdefault`), which would hide amendments. Stage 0 detects conflicting duplicates itself.

## 1. Invariants (binding on WB-1)
- Nautilus is immutable. `allow_short=False`. RULING_FQ-v2-NO-TRADE is in force. No PREREG.json is edited. The operator caps are never assigned.
- No safety, settlement, contract, import-lint or NO-SEND test is weakened.
- WB-1 adds no egress-pin, host or permit row; the first such row arrives with WB-3/WB-6. A pin test failure means stop and replan.
- `scripts/analysis/k1_kalshi_prior.py` stays byte-unchanged.
- No trading path imports Stage 0 or reads its outputs. Stage 0 reads no PM.us tape and fetches no candlesticks.

## 2. Event universe (frozen)
**Unit.** One station-day event = one series × one climate day.
- The climate day comes from `event_ticker`, matched against `^<SERIES>-(\d{2})([A-Z]{3})(\d{2})$`.
- It must equal the date in `rules_primary`; otherwise REFUSE(DATE).

**Series universe.** Exactly the 48 series that had open events on 2026-09-04 (enumeration doc): 24 CLI stations × HIGH/LOW.

| CLI | HIGH | LOW |
|---|---|---|
| ATL | KXHIGHTATL | KXLOWTATL |
| AUS | KXHIGHAUS | KXLOWTAUS |
| BOS | KXHIGHTBOS | KXLOWTBOS |
| MDW | KXHIGHCHI | KXLOWTCHI |
| DFW | KXHIGHTDAL | KXLOWTDAL |
| DEN | KXHIGHDEN | KXLOWTDEN |
| HOU | KXHIGHTHOU | KXLOWTHOU |
| LAS | KXHIGHTLV | KXLOWTLV |
| LAX | KXHIGHLAX | KXLOWTLAX |
| SDF | KXHIGHTSDF | KXLOWTSDF |
| MIA | KXHIGHMIA | KXLOWTMIA |
| MSP | KXHIGHTMIN | KXLOWTMIN |
| MSY | KXHIGHTNOLA | KXLOWTNOLA |
| NYC | KXHIGHNY | KXLOWTNYC |
| EWR | KXHIGHTEWR | KXLOWTEWR |
| OKC | KXHIGHTOKC | KXLOWTOKC |
| PHL | KXHIGHPHIL | KXLOWTPHIL |
| PHX | KXHIGHTPHX | KXLOWTPHX |
| SAT | KXHIGHTSATX | KXLOWTSATX |
| SAN | KXHIGHTSAN | KXLOWTSAN |
| SFO | KXHIGHTSFO | KXLOWTSFO |
| SEA | KXHIGHTSEA | KXLOWTSEA |
| TTN | KXHIGHTTTN | KXLOWTTTN |
| DCA | KXHIGHTDC | KXLOWTDC |

**Out of universe** (listed, never fetched):
- international series;
- dormant US duplicates: KXLOWNY, KXLOWNYC, KXLOWCHI, KXHIGHHOU, KXHIGHOU, KXHIGHUS;
- non-KX legacy series: HIGHNY, HIGHCHI, HIGHMIA, HIGHAUS;
- hourly, custom and multi-city series.

Adding a series needs a ruling.

**Run cutoff.** Climate days ≤ run_date − 8 days. The lower bound is the full listed history.

**Classification [N1].** Per market, from `rules_primary` only, literal and case-sensitive:

| Class | Rule |
|---|---|
| `TWC` | contains "The Weather Company" and not "National Weather Service" |
| `NWS` | the reverse |
| `BOTH` | contains both |
| `UNNAMED` | contains neither |

- An event's class is the common class of its markets. Markets that disagree make the event `MIXED`.
- Only `TWC` events enter n. `NWS` events only date the switch. UNNAMED, BOTH and MIXED events are excluded and listed.
- `settlement_sources` is never read to date or classify anything.
- Per series, record the last NWS climate day and the first TWC climate day. An NWS event after a TWC event is flagged `NON_MONOTONE_SWITCH`.

## 3. Field allowlist (deny-by-default projection)
- **Kept:** {ticker, event_ticker, series_ticker, strike_type, floor_strike, cap_strike, status, result, expiration_value, close_time, expected_expiration_time, rules_primary}.
- **Dropped at parse:** every other key, before any storage or logging.
- **Never written:** raw responses. k1 `store_markets` and `CandleCache` are never called.
- Projected records live in memory only. Their sorted-JSON sha256 is recorded.

## 4. Parse rules
- **`expiration_value`.**
  - Must match `^-?\d+(\.0+)?$`, then is converted to int. Examples: "100.00"→100, "82.00"→82, "88"→88. Negatives are legal.
  - Anything else → REFUSE(EXPIRATION_VALUE), e.g. "", "82.5", "1e2", whitespace, null, or a non-string.
  - All markets in one event must agree; otherwise REFUSE(EV_CONFLICT).
- **Strikes.**
  - `greater` with floor F → {x ≥ F+1}.
  - `less` with cap C → {x ≤ C−1}.
  - `between` (F, C) → {F ≤ x ≤ C}.
  - Anything else, or a missing strike → REFUSE(STRIKE).
- **Legacy markets** (`strike_type` null): parse `strictly greater than (\d+)°F` → {x ≥ k+1}. Otherwise EXCLUDED_LEGACY. Either way they are UNNAMED, so never in n.
- **Ladder checks.**
  - Overlap → REFUSE(LADDER_OVERLAP).
  - Gap → `SKIPPED_GAP`, listed, not a refusal.
- **Result partition** (sanity only).
  - On a gap-free TWC event, exactly one market resolves `result=="yes"`, and its interval contains `expiration_value`.
  - Otherwise REFUSE(PARTITION).
- **Status.**
  - Accepted statuses: `finalized`, `settled`.
  - An event that is closed but not in an accepted status → PENDING (excluded, listed).
  - Past `expected_expiration_time` + 8 days and still not accepted → STUCK.

## 5. Misses [M3]
**Counted in n as misses, and tabulated by reason:**
- every REFUSE(*) on a TWC event;
- STUCK;
- VOID: `result` ∉ {"yes","no"} on a settled market;
- AMENDED: a ticker seen more than once with a differing `expiration_value`, `result` or `status` (detected by Stage 0; k1's first-wins is not relied on);
- DISPUTED: any detectable dispute or "last fair price" resolution.

**Not comparable (excluded, listed):** no final CLI, or a null `tmax_f`/`tmin_f`.

## 6. Station identity
- **TWC side.** `rules_primary` must contain exactly one `\(CLI([A-Z]{3})\)`, equal to the §2 code; otherwise REFUSE(STATION). Titles are never used (known drift: KXHIGHTSDF titled "SATX", KXLOWTMIN "Minnesota").
- **CLI side.** IEM AFOS `CLI<code>` with `is_final=True`, latest revision via `latest_by_archived_climate_day` (`src/breezy/domain/archived_selection.py:46`), BBB corrections applied. HIGH uses `tmax_f`; LOW uses `tmin_f`.
- **Header guard.** A narrow `body_header_regex` per station, built from committed CLI fixtures:
  - HOU needs "HOBBY";
  - MSP needs "TWIN CITIES";
  - AUS needs "BERGSTROM", not Camp Mabry.
- **Sibling decoys, refused both ways:** OKX EWR↔NYC, PHI PHL↔TTN, EWX AUS↔SAT.

## 7. WB-1 transport, budget and body cap [S1]
### 7.1 Kalshi
**Transport.** A subclass of k1 `KalshiHttp`. It reuses `API_BASE`, the 401/403 raise, and backoff 0.25 s → cap 8.0 s. It overrides `get_json` only to add:
- a budget counter;
- a capped read (`read(cap+1)`);
- a GET-only assertion;
- a host assertion (`api.elections.kalshi.com` exactly);
- a guarantee that no auth header is ever sent.

Pacing: `min_interval_s=0.25` (≤4 rps), `max_retries=6`.

**Listing passes per series**, `limit=1000`, following the cursor until it is empty:
1. `historical/markets?series_ticker=T`
2. `markets?series_ticker=T&status=settled`
3. `markets?series_ticker=T&status=finalized` (a 400 → `FILTER_UNSUPPORTED`, which still counts as an attempt)

**Sizing.**
- Ladders run from ≥2023-01-01 (k1 `ERA_BOUNDARY`): ≤1,376 days × 6 markets ≈ 8,256 markets.
- That is ≤14 pages per series, so 48 series ≈ 672 nominal requests. The 09-04 enumeration needed 103.

**Hard limits.**

| Limit | Value | When exceeded |
|---|---|---|
| Run attempts (retries included) | **1,500** | the run aborts on attempt 1,501 |
| Per-series attempts | 30 | the series becomes `INCOMPLETE` |
| Body per response | **8 MiB (8,388,608 B)** | `BODY_CAP` for that series, never parsed |
| Cumulative body | 1.5 GiB | run abort |

Body sizing: a full raw market is ≈2.9 KB (`tests/fixtures/kalshi/market_KXHIGHLAX_2026-09-04.json`), so a 1,000-market page is ≈2.9 MB.

**Run abort.** Any of: run budget exceeded, cumulative cap exceeded, or an unexpected 4xx. The run then writes `status=ABORTED_<reason>` and no verdicts. A partial run never ADMITS.

### 7.2 IEM CLI
- Reuse the `IemCliTransport`, `fetch_cli_text` and `require_afos_cli_url` primitives (`scripts/archive/iem_cli_fetch.py`): `RequestBudget`, `IemPacer`, `MAX_BODY_BYTES`=32 MiB, `AFOS_LIMIT`=9,999.
- The station set is the fixed set of 24 codes; the registry is not edited.
- Budget: 24 × 3 = **72** attempts.
- Window start: the minimum first-TWC climate day.

### 7.3 Launch
- A `scripts/` entry point via `systemd-run --user`, launched by the coordinator.
- `RuntimeMaxSec=3600`, `MemoryMax=2G`, and a progress line every 50 attempts.
- Interpreter: `/home/jon/breezy/.venv/bin/python`.

## 8. Admission metric and verdicts (per series; HIGH and LOW separate)
1. **Metric.** Exact `expiration_value == CLI extreme`. s = n − m, where m = misses.
2. **Wilson interval.** z = **1.959963984540054**.
   - L/U = (p̂ + z²/2n ∓ z·√(p̂(1−p̂)/n + z²/4n²)) / (1 + z²/n)
   - **ADMITTED** iff L > 0.99. With m = 0 this means n ≥ 381; with one miss, roughly n ≈ 560.
   - **EXCLUDED** iff U < 0.99.
   - **HELD** otherwise.
   - INCOMPLETE, or n = 0, gets no verdict.
3. **Projected admission [N2]** (HELD series only).
   - n* = the least n′ ≥ n with L(n′ − m, n′) > 0.99, assuming no further misses (optimistic).
   - r = TWC events in n ÷ days in [first TWC day, cutoff].
   - Projected date = cutoff + ⌈(n* − n)/r⌉ days.
   - If r is undefined, or there are fewer than 2 TWC days → `UNPROJECTABLE`. A date > **2027-12-31** → `BEYOND_CAP`.
4. **Programme.**
   - Zero ADMITTED, and none projectable by 2027-12-31 → record N-0 evidence.
   - While any series is HELD, K-2 stays open as monitoring (B1). N-4 re-checks monthly until each series is ADMITTED or EXCLUDED, or reaches its projected date + 60 days (cap 2027-12-31), and then goes to N-0.
   - The threshold never changes.
5. **Season flag.** A DJF/MAM/JJA/SON stratum with n ≥ 30 and U < 0.99 is flagged `SEASON_FLAG` for peer review. It never changes the verdict.
   - A TWC-labelled admission requires a ruling (M5); otherwise the station is EXCLUDED.
6. **Holdout seal.** For climate days ≥ F_K (2026-10-08), outputs carry aggregate counts only. No per-event values or differences are published.

## 9. Diagnostics (never gating)
- Bucket agreement over the CLI bucket ± 1 adjacent bucket.
- A signed-difference histogram, for days < F_K only.
- Strata:
  - DST vs standard (PHX is always standard);
  - endpoint era;
  - CLI-correction day (BBB/revision > 0);
  - season.

## 10. Forecast and holdout constants
- **N_s = 365** pre-v5.0 climate days per station. Below that: pooled, plus a flag.
- **F_H** = min(2027-01-01, K-2b start).
- **F_K** = 2026-10-08. WA-3 freezes it; this document only reads it.
- **Confirmatory holdout** = [max(2026-07-01, F_K), F_H) = [2026-10-08, F_H). SEARCH ∩ holdout = ∅.
- **Holdout stations** = ADMITTED stations at the time WB-5 opens the holdout, minus the 5 shared stations (CLINYC, CLIMIA, CLIMDW, CLILAX, CLISFO; HIGH and LOW). The non-independent alternative is not declared.
- **Marker** `holdout_marker_kalshi_<sha256(sorted station set)>.json`, created with O_EXCL.

## 11. Output schema
**Files.** `docs/evidence/venue/kalshi/KALSHI_TWC_CLI_RECON_<date>.md`, plus a deterministic `.json` sidecar (sorted keys).

**Header fields.**
- `wa2_sha256`, `git_sha`, `run_utc`, `cutoff_day`, `status`
- `kalshi_attempts`/1500, `kalshi_bytes`, `iem_attempts`/72
- `filter_unsupported`, `projected_records_sha256`
- `universe` (48), `out_of_universe`

**Per-series fields.**
- Identity: `series`, `cli_code`, `kind`, `shared_station`
- Classification: `class_counts`, `last_nws_day`, `first_twc_day`, `non_monotone_switch`
- Counts: `n`, `misses{...}`, `not_comparable`, `pending`, `skipped_gap`
- Result: `wilson_lo`, `wilson_hi` (6 dp), `verdict`, `projected_admission`, `rate_per_day`
- Diagnostics: `season_flags`, `diagnostics{bucket, histogram(<F_K), strata}`

**Other blocks.**
- A refusal ledger, for days < F_K only.
- A `programme` block: {admitted, held, excluded, n0_evidence}.

**Forbidden keys.** Anything matching `(price|bid|ask|volume|liquidity|open_interest|_dollars|_fp)`.

## 12. WB-1 acceptance tests
All RED-first, using a stub transport, with no network.

**Projection and artifacts**
1. `test_stage0_projection_allowlist_exact` (fixture `market_KXHIGHLAX_2026-09-04.json`).
2. `test_stage0_no_price_key_in_any_artifact`.
3. `test_stage0_never_writes_raw_or_k1_cache`: `store_markets` and `CandleCache.store` raise; a filesystem spy confirms the write paths.

**Parsing and classification**

4. `test_expiration_value_parse`:
   - accepts "100.00", "82.00", "88", "-5.00";
   - refuses "", "82.5", "1e2", " 82", None, and the float 82.0.
5. `test_strike_semantics_and_ladder_partition_property`:
   - on KXHIGHNY-26JUL02, every integer in −60..140 lands in exactly one market;
   - property checks on synthetic ladders;
   - KXHIGHNY-26SEP01 and KXHIGHLAX-26SEP05 → `SKIPPED_GAP`;
   - a synthetic overlap → REFUSE.
6. `test_result_partition_refuse_counts_as_miss`.
7. `test_event_classification_n1`:
   - 26JUL02 → NWS, 26SEP01 → TWC, legacy → UNNAMED;
   - synthetic BOTH and MIXED cases;
   - `settlement_sources` is never read.
8. `test_void_disputed_amended_stuck_are_misses`, including a historical-vs-live conflicting duplicate.
9. `test_cli_missing_is_not_comparable_not_miss` and `test_cli_latest_final_with_bbb_selected`.

**Verdicts**

10. `test_wilson_verdicts`: z is exact; (380,0) → HELD; (381,0) → ADMITTED; (100,5) → EXCLUDED.
11. `test_projected_admission_date_miss_aware`: brute force over m ∈ {0,1,2}; UNPROJECTABLE and BEYOND_CAP cases.

**Station identity**

12. `test_station_identity_from_rules_primary_only`.
13. `test_cli_header_sibling_decoys`: EWR↔NYC, PHL↔TTN and AUS↔SAT both ways; the HOBBY, TWIN CITIES and BERGSTROM guards.

**Strata, transport and limits**

14. `test_dst_strata`: PHX always STANDARD; NYC on 2026-03-08 and 2026-11-01.
15. `test_request_budget_and_caps`:
    - attempt 1501 → ABORTED;
    - series attempt 31 → INCOMPLETE;
    - an 8 MiB + 1 body → BODY_CAP, unparsed;
    - the 1.5 GiB cumulative cap;
    - IEM budget 72.
16. `test_transport_get_only_single_host_no_auth`.

**Seal, determinism and isolation**

17. `test_holdout_seal_no_per_event_values_on_or_after_fk`.
18. `test_stage0_output_deterministic`.
19. `test_no_trading_path_imports_stage0` plus `test_stage0_scripts_open_no_socket_at_import`. Gate: `scripts/ci/run_tests_no_egress.sh` with canary N3; `lint-imports` reports N kept, 0 broken.

---
## Review amendments (BINDING): architect review, 2026-10-08

The review result was CHANGES. All nine edits are adopted. Where these edits conflict with the body above, the edits govern.

- **E1 (transport).**
  - The subclass replaces `get_json` entirely and never calls `super().get_json()`, because k1 `:915` reads the response uncapped.
  - The attempt counter sits inside the retry loop.
  - The host is also asserted on `response.geturl()`, and redirects are refused.
  - Stage 0 does **not** call `list_series_markets`: its params are hard-coded at `:942-945` and duplicates are first-wins at `:956`. Stage 0 reuses only `API_BASE`, the throttle constants, and the 401/403 raise.
- **E2 (unfiltered status pass).**
  - Pass 3 becomes an **unfiltered** `markets?series_ticker=T`, and binding status comes from each response.
  - Without this, PENDING and STUCK would be unobservable and would silently leave n.
  - FILTER_UNSUPPORTED is removed. Any 4xx other than a 404 on pass 1 → ABORTED.
- **E3 (AMENDED).** AMENDED fires only when `expiration_value` or `result` differs. A `settled`→`finalized` status change is lifecycle, not a miss.
- **E4 (refusal reasons by side).**
  - Kalshi side, counted as a miss: EXPIRATION_VALUE, EV_CONFLICT, STRIKE, LADDER_OVERLAP, PARTITION, DATE, STATION.
  - CLI side, counted as not comparable: header-guard failure, sibling-decoy hit, no final, null tmax/tmin.
  - If not-comparable exceeds 5% of a series' TWC events, set `NOT_COMPARABLE_FLAG` for peer review. The verdict is unchanged.
- **E5.** The holdout seal is confirmed, with no edit. Note that F_H is 2027-01-01 in practice.
- **E6 (stations and timezones).**
  - Add an explicit table mapping the 24 CLI codes to IANA timezones, used for DST strata and the climate day.
  - Calling k1 `station_for_series`, `offset_hours_for_series` or `SERIES_TO_CLI_LOCATION` is forbidden. They cover only the 5 PM.us stations.
- **E7 (cumulative cap).** The cumulative body cap is **2.5 GiB**. Derivation: the worst-case N-4 re-run on 2027-12-31 is about 1,826 days × 6 × 2.9 KB × 48 ≈ 1.5 GB of historical pages, plus overlap. The other limits stand.
- **E8 (`rules_primary`).**
  - Historical records with no `rules_primary` are counted as `rules_primary_missing` and listed per series.
  - The `\(CLI([A-Z]{3})\)` regex is pinned by a fixture test against the current `rules_primary` of all 48 series.
- **E9 (added tests).**
  - Cross-host redirect refused.
  - The subclass never reaches an uncapped read.
  - The counter counts retries.
  - PENDING and STUCK are reached via the unfiltered pass.
  - `settled`→`finalized` is not AMENDED.
  - The E4 Kalshi/CLI partition.
  - REFUSE(DATE).
  - EV_CONFLICT.
  - NON_MONOTONE_SWITCH.
  - An ABORTED or partial run writes no verdict and never ADMITs.
  - SEASON_FLAG never changes a verdict.
  - No dropped keys appear in log lines.

**Status after amendments:** CONVERGED. The frozen-at SHA is the commit that adds this section.
