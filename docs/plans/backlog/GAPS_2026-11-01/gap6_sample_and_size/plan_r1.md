# GAP-6 SAMPLE-AND-SIZE — plan r1 (2026-11-01)
Status: r1 — for re-review by **architect** + **prediction-market-reviewer**. Written read-only; the coordinator lands it. r0 → r1: S0 history read comes first, the capture depends on it, the census is shorter and stratified, and governance runs through B-8.

## Finding → resolution
| # | Sev | Resolution |
|---|---|---|
| A-1 | HIGH | Transport is `KalshiHttp` at `k1_kalshi_prior.py:867-937`, used unchanged (Card E does the same, `card_e_cli_vs_twc.py:1911-1915`), behind a new wrapper `HostPinnedKalshi` (§3). The wrapper (a) asserts `base_url == API_BASE` (`:213`) and a path allowlist; (b) passes `min_interval_s=0.25` (Card E `:79`; the default 0.12 is about 8 rps) and an explicit `max_retries=3`, so the backoff is 0.25→1 s inside the `:256-257` ladder; (c) treats an exhausted 429/5xx as that market missing, and aborts the sweep as INCOMPLETE after 5 such misses in a row. r0's "never a retry loop" is replaced by this bounded policy. |
| A-2 | HIGH | Split D-2. `capture` is a collector like F13-C1 and needs no exception. `s0` and `census` are new evaluator logic, so D-2 asks for an exception covering only the §4 definitions and §5 rules, with no other metric. |
| A-3 | HIGH | Operator D-1 is deleted. S1 becomes a **successor ruling via the B-8 peer loop** (K-2a r1 `:5, :9, :194`) that names only the S0 GETs and the GET-only depth capture. It fixes F_K before any fetch (`:117`). α_K is untouched: S0 is SEARCH and the census measures supply, so neither spends edge FWER (`:113`). Card E is cited as a mechanical precedent only, never as authority. |
| P-1 | HIGH | The 74%/26% PM.us comparison is dropped. Eligibility now needs persistence (≥ 2 consecutive complete sweeps) and depth ≥ D_gate. D_gate = max(1, q) if the operator records q before S1; otherwise D_gate = 1, which is the qty-1 proving stance. A cap-tied depth is declined because the caps are not on disk and the plan may not infer a value. The depth grid {1, 10, 100} is reported. The gate is frozen on n_req over the K-2a horizon (§5). |
| P-2 | HIGH | Every read is stratified into pre-, intra- and post-observation hours (§4). Only **pre-observation** cells gate. Post-observation cells are labelled "resolved-outcome supply" and are descriptive only. |
| P-3 | HIGH | New **S0**: a historical settled-market read of tail NO win rate against price + fee. The truth is the venue's own `result`, so no CLI fetch is needed. Capture S3 runs **only if S0 ≠ KILL**. The census window drops to a 3-day pilot (not a look) plus 14 days (one look). |
| A-4 | MED | Accepted. The projection is lossless for `OrderBookDepth10`: 10 levels per side as verbatim Decimal strings, receive `ts_ns`, and `series_ticker`/`event_ticker`/`ticker` identity. Phase 2 converts this data and never re-captures. |
| A-5 | MED | Accepted. Both egress scans (`test_polymarket_us_readonly_guard.py` and `test_execution_egress_firewall_guard.py`) and the cage pin test are named as guards in §6. A new test asserts no `/orders` literal and no write verb. |
| A-6 | MED | Accepted. Each sweep writes its own create-exclusive file `<root>/<date>/<sweepT>.jsonl`, and a create-exclusive `MANIFEST.sha256` seals the day. The root is chosen in §3. Coordinator notes go to a sidecar (L-75). |
| A-7 | LOW | No change. The branch disposition matches K-2a `:141`. |
| P-4 | MED | Accepted. The denominator is **listed** station-side-days. Unlisted days are a separate VENUE-NEVER-LISTED count, never availability 0. |
| P-5 | MED | Accepted. Decimal throughout, with edge tests at bid 0.0300 / 0.0100 / 0.0099 / 0.0350. |
| P-6 | MED | Accepted. The hurdle is reported as a function of q ∈ {1, 5, 10, 100} (illustrative grid, never a proposal) under H1 ceil-6dp, H2 ceil-cent and H3 ceil-cent with rounding rebate. |
| P-7 | MED | Accepted. The size table is labelled illustrative, with N_elig taken from no measurement. The tail row's edge is stated as ≈ 0 or negative. |
| P-8 | LOW | Accepted. Citations corrected. The reviewers conflict on the KalshiHttp span. Verified: the class is at `:867`, `__init__` at `:880` and `get_json` ends at `:937`, so the cite is `:867-937`. |

## 1 Objective
- The single objective (realised win rate > price + fee, proven) is n-limited. PM.us has 5 stations, HIGH only: MDE 19.8¢ at 26 d, and D_c 55 d for 10¢ at R=3.
- Kalshi's 24 cities × HIGH/LOW (48 series) is the only station-day multiplier.
- The first question is the objective itself: on settled Kalshi history, does a pre-observation 0.97–0.99 NO buy win more often than price + fee (**S0**)?
- Only if it plausibly does: is persistent, executable tail supply large enough to reach n within the horizon (**census**)?
- The size arithmetic is written for the operator's q decision. q is never assigned here.

## 2 Preconditions and dependencies
- Independent of GAPs 1–5. Reads no forecast, no PM.us tape and no exec code.
- Facts in hand, not re-measured:
  - Kalshi `expiration_value` equals NWS CLI on 5185/5186 station-side-days (Card E).
  - A YES bid at X is a NO ask at 1 − X, with `count_fp` levels (S0 §6.1–6.2).
  - Nautilus 1.231.0 has no Kalshi adapter (`prediction-markets-native-support.md:144, :307`). A script respects the null hypothesis, because a native client needs instruments and a provider, which is WB-6.
  - `wip/kalshi-s4-registry` = `58280b6`; disposition is a fresh branch plus hand port, K-2b only.
- **Governance (S1):** a B-8 peer-loop successor ruling scoped to the S0 GETs and the depth capture. It sets F_K = the ruling date. Kalshi climate days < 2026-07-01 are SEARCH (S0). [07-01, F_K) stays unread. Days ≥ F_K are forward (S3).
- The ruling states α_K is unspent, and that shared-city history stays SEARCH-only (`:120`).
- **10-21 (D-2):** the operator exception covers `s0` and `census` only.

## 3 Scope
- **New:** `scripts/analysis/kalshi_depth_census.py` with three subcommands. `k1_kalshi_prior.py` stays byte-unchanged.
  - `s0`: settled-market listing via `list_series_markets` (`:939`), then one hourly-candlestick range call per market from D-1 open to D end. Reuses the k1 schema-tolerant `_candle_decimal` (`:551`) and the `HISTORICAL_CUTOFF` endpoint split (`:248, :962-975`). The 5 shared series are read cache-first from `~/.local/share/breezy/kalshi`.
  - `capture`: hourly sweeps. `GET /events?series_ticker=&status=open&with_nested_markets=true`, then `GET /markets/{ticker}/orderbook` per market.
  - `census`: the one-look count.
- `HostPinnedKalshi` wrapper (A-1). Allowlisted paths: `events`, `markets`, `historical/markets`, `markets/{t}/orderbook`, `{historical/,series/{s}/}markets/{t}/candlesticks`, `series/{s}/fee_changes`.
- **Storage:** `/mnt/storage/breezy/kalshi_depth/<UTC-date>/<sweepT>.jsonl`, deny-by-default projection, plus the day `MANIFEST.sha256`.
  - The root sits beside the quote tape. The free-space refusal (< 10 GB) is `statvfs` of **that** filesystem.
  - S0 outputs go to `~/.local/share/breezy/derived/kalshi_s0/<run>.json`, immutable per run.
- **NOT in scope:**
  - `src/breezy/adapters/kalshi/`, egress pins, permits, ledgers or NO-SEND;
  - auth, accounts or orders;
  - forecasts;
  - bands outside [0.97, 0.99] (GAP-1/3);
  - PM.us paths;
  - rebasing the parked branch;
  - the r0 S4 CLI backfill. It is dropped because S0 uses the venue `result`, and the backfill is deferred to K-2a WB-1.

## 4 Steps
| # | Step | Inputs → outputs | Runs | Est. |
|---|---|---|---|---|
| S1 | Successor ruling (B-8) + frozen PREREG (§5) for S0 and the census | → `…/gap6_sample_and_size/prereg_r1.md` + sha256; ruling under `docs/evidence/` | coordinator; architect + PM-reviewer co-sign | 0.5 d |
| S2 | Build `s0`/`capture`/`census` + wrapper, RED-first (§6) | S1 → script + tests | Grok → Codex → Claude tdd-guide; Claude runs the gate | 1.5 d |
| S3 | **S0 one look** on settled history, climate days [2025-07-01, 2026-07-01) | → `docs/evidence/kalshi_depth/S0_<date>.{md,json}` (L-75) | bot script, `systemd-run --user`, MemoryMax=2G, `-p LimitNOFILE=524288`, stall watch | ~8 h fetch + 1 h |
| S4 | If S0 ≠ KILL: 3-day capture pilot. Coverage and mechanics only, **not a look** | → sweep files + manifests | as S3 | 3 cal. d |
| S5 | 14-day capture, then ONE census look | → `CENSUS_<date>.{md,json}` (L-75) | as S3 | 14 cal. d + 1 h |
| S6 | θ verification (r0 method). Hurdle reported under H1/H2/H3 × q grid | → `docs/evidence/venue/kalshi/FEE_THETA_<date>.md` | sub-agent + operator PDF (D-3) | 0.5 d |

**Frozen definitions:**
- **NO ask** = 1 − YES bid, level by level, in Decimal.
- **Tail band** = [0.97, 0.99] inclusive.
- **Reference hours (local standard time).** Hours not listed are "intra" and reported only.

| Side | Pre | Post |
|---|---|---|
| HIGH | D-1 open-hour; D 10:00 | D 17:00 |
| LOW | D-1 open-hour; D-1 18:00 | D 10:00 |

- **S0 observation:** one per (rung, reference hour). NO ask = 1 − candle `yes_bid.close` (genuine: 0 < p < 1). excess = 1{NO wins per venue `result`} − NO ask.
  - Look-ahead is asserted: ref < settlement, and pre-observation ref < observation window start.
  - Void, cancelled and unfinalized markets are excluded, reusing Card E `_row_exclusion` semantics.
- **Census eligible station-side-day:** a pre-observation sweep where some rung's tail NO ask has cumulative size ≥ D_gate, present at ≥ 2 consecutive complete sweeps.
  - The census reports per station × side × stratum × hour: rung count, depth grid, best NO ask, and strike_type mix.
  - Shared cities are reported separately and add zero independent n.

## 5 Pre-registered PASS/KILL (frozen at S1; one look each, L-34; dry run on fixtures is never a look)
- **S0 cells:** {HIGH, LOW} × {pre, post}. Only the 2 pre cells gate.
  - Statistic: mean excess **fee-free (θ=0)**, with a day-block bootstrap (2000 resamples, frozen seed).
  - Minimum per cell: n ≥ 30 and ≥ 5 days. Otherwise INCONCLUSIVE.
- **S0 KILL:** both pre cells have mean excess ≤ 0 before any fee. Any fee only lowers this further, so the tail is dead whatever θ turns out to be. Capture is never launched.
- **S0 CONTINUE:** any pre cell has mean excess > 0, or is INCONCLUSIVE.
  - This is SEARCH only (FQ-R14): never a nomination, never a trade rule.
  - The 4 cells are recorded as S0's multiplicity count for any later registration.
- **Capture:**
  - Sweep complete = ≥ 95% of listed markets parsed.
  - Day covered = ≥ 20 of 24 sweeps complete.
  - ACCEPTED = ≥ 10 of 14 days covered. Otherwise INCONCLUSIVE, no look spent; re-arm once, then go to N-0.
- **Census gate (HIGH, new stations, pre stratum).**
  - S = mean eligible listed station-days per covered day.
  - n_req = ⌈((1.96 + 0.84) · σ / δ)²⌉, with σ = √(0.98·0.02) = 0.14 and δ = 0.02. This uses one-sided α = 0.025 with no multiplicity split, the **most lenient** case, so n_req = 385.
  - H = 120 d (K-2a `:125`).
- **KILL:** S × H < 385. Even the most optimistic tail edge cannot be sampled in the horizon.
- **PASS:** S × H ≥ 385. This means "supply clears the lenient bound", **not** "edge exists". It hands to K-2a WB-6/WB-7.
- LOW and post-observation results are reported, never pooled.

## 6 Tests (RED first) and gate
- `test_projection_drops_every_non_book_key`
- `test_projection_is_lossless_for_depth10_ten_levels_per_side`
- `test_no_ask_is_one_minus_yes_bid_levelwise_decimal`
- `test_tail_band_edges_bid_0300_0100_inclusive_0099_0350_excluded`
- `test_depth_below_d_gate_and_single_sweep_are_not_eligible`
- `test_pre_post_stratum_assignment_per_side`
- `test_unlisted_station_day_is_counted_separately_never_zero`
- `test_sweep_and_day_coverage_rules`
- `test_sweep_file_create_exclusive_and_day_manifest_sealed`
- `test_wrapper_asserts_api_base_and_path_allowlist`
- `test_wrapper_max_retries_explicit_and_exhausted_429_marks_missing`
- `test_five_consecutive_exhaustions_abort_sweep_incomplete`
- `test_script_has_no_orders_literal_and_no_write_verb`
- `test_s0_lookahead_raises_and_void_rows_excluded`
- `test_s0_reads_both_candle_schemas`
- `test_no_socket_opened_at_import`
- `test_never_imports_iem_cli_fetch_fetch`
- `test_census_and_s0_refuse_second_look`

Notes:
- Stub transport only. Fixtures are the S0 orderbook/market fixtures plus one historical and one live candle.
- **Whole-tree guards to name in briefs:**
  - `test_polymarket_us_readonly_guard.py`: `EGRESS_SCAN_ROOTS :153`, `_VENUE_HOST_RE :235`, `_VENUE_NAME_RE :249`. These mark the script venue-touching, so the write-verb rules apply.
  - `test_execution_egress_firewall_guard.py`: `EGRESS_SCAN_ROOTS :133`.
  - `test_cage_rule_constants_are_pinned.py`.
  - import gates, the asdict scan, the operator-control assignment scan.
- **Gate:** `scripts/ci/run_tests_no_egress.sh` on the primary tree, then `lint-imports` from the tree root.
  - Read EXIT before push. Basetemp inside the worktree, removed after EXIT is read.

## 7 Pins, isolation, risks
- **Binding:** Nautilus immutable; `allow_short=False`; no safety/settlement/contract/pin/NO-SEND test weakened; both caps never assigned; live enablement and the egress firewall untouched; unauthenticated GETs only (a 401/403 raises, `:917-922`); no credentials printed; no order ids; `iem_cli_fetch.fetch` never called; L-12; L-75 with notes in sidecars.
- **Holdout:** S0 reads only climate days < 07-01 and no forecast, so cl.1–cl.4 are not engaged. [07-01, F_K) is unread. Capture is ≥ F_K forward.
- **Risks:**
  - Candles carry no size, so S0 is a price-only upper bound; depth comes from the census.
  - Displayed size ≠ fillable size (cancel race), so census availability is also an upper bound.
  - Short listing histories for new series: n is reported per station.
  - The undocumented rate tier is mitigated by the A-1 policy at ≤ 4 rps. About 576 markets/sweep takes ~144 s.
  - A 97–99% break-even means one loss erases 30–50 wins. That is why δ = 0.02 is the most optimistic value.
  - Identity comes from `series_ticker`, never ticker parsing.

## Size math — ILLUSTRATIVE ONLY (N_elig = 57/month is back-derived, from no measurement; no q proposed)
- **Monthly $ = N_elig × edge × q.** Kalshi N_elig = Σ listed-days × census availability × take rate. The take rate is unmeasured.

| edge | $/month | q for $10 | q for $65 |
|---|---|---|---|
| 5¢ | 2.85·q | ≥ 3.51 | ≥ 22.8 |
| 10¢ | 5.70·q | ≥ 1.75 | ≥ 11.4 |
| 15¢ | 8.55·q | ≥ 1.17 | ≥ 7.6 |

- **Tail cell:** edge ≤ 1 − ask ≤ 3¢ gross and is **likely ≈ 0 or negative** after the fee. None of the rows above apply to it.
- **Where the caps bind:**
  - `BREEZY_MAX_POSITION_COST_USD` (`operator_controls.py:150`; check `:541-547`): q ≤ cap/price.
  - `BREEZY_MAX_DAILY_BUDGET_USD` (`:145`; `:540, :561-566`).
  - One shared ledger (WB-9) means Kalshi never raises total spend.

## 8 Operator decisions
- **D-2:** the 10-21 exception for `s0` + `census`, limited to the §4 definitions and §5 rules. `capture` needs none.
- **D-3:** θ source: the fee-schedule PDF (browser) or a first fill.
- **D-4:** size q. This is an OPERATOR DECISION and no value appears here. If q is recorded before S1, D_gate = max(1, q).
- **Removed:** r0 D-1. The Kalshi start is a B-8 peer-loop ruling (K-2a `:194`), not an operator decision.

## 9 Citations
- **Verified this revision:**
  - `k1_kalshi_prior.py`: `:213, :248, :256-257, :551, :867-937, :939, :962-975`
  - `card_e_cli_vs_twc.py`: `:79, :463-473, :1911-1915`
  - K-2a r1: `:5, :9, :113, :117, :120, :125, :128, :141, :194`
  - `test_polymarket_us_readonly_guard.py`: `:153, :235, :249`
  - `test_execution_egress_firewall_guard.py`: `:133`
- **Not verified:** see the five lines below the plan.

---
Still-unverified citations:
1. Candle payloads carry a `yes_bid` OHLC, and the K1 cache under `~/.local/share/breezy/kalshi` keeps the raw candle with `yes_bid`. k1's docstring `:56` mentions only `yes_ask`. If `yes_bid` is absent, S0 cannot be computed: its gate cells are INCONCLUSIVE and S0 falls through to CONTINUE.
2. The `/mnt/storage/breezy/…` root path, and the S0 fetch volume (~105k markets, ~8 h at 4 rps). Both are estimates.
3. The candlestick range-call limits (one call covering D-1 open to D end), the `series/{s}/fee_changes` path and whether it needs auth, and the ~576 markets/sweep figure.
4. The new-series listing start dates within [2025-07-01, 2026-07-01). Some series may contribute little or no S0 history.
5. Line numbers `prediction-markets-native-support.md:144, :307` and `operator_controls.py:145, :150, :540-566` are taken from the reviewers and were not re-opened here.
