# K-2a plan r1: Kalshi sibling family (desk-only re-plan; K-2b executes it) — 2026-10-08

**Status:** r1. The planner authored it read-only, with no API calls and no rebase. It is awaiting WA-1 peer review.

**Authority:** `docs/evidence/RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md` §3.3, which amends RULING_RA-13 §4 for K-2a. RA-13 §5 and §7 B-1..B-8 still bind.

## 0. Scope
- **K-2a (now, desk-only):** this plan, the frozen Stage 0 design, governance drafts, and peer review. No network, no runtime change, no change under `src/`.
- **K-2b (on programme KILL, or a successor ruling that names the stage):** every fetch, script and build, the branch disposition, shadow, and live.
- **Basis:** this re-plans `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` (Rev 3, written for `current_rung_hold`).
  - K-2 carries the **NBP forecast-quantile family** instead (`RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md:55-56`).
  - Carried over from Rev 3: the venue mechanics (S0-verified) and the barrier work (S1', S2', S3', S4').
  - Replaced from Rev 3: tally, power, and family.
- **Invariants:**
  - Nautilus is immutable, and `allow_short=False`.
  - No safety, settlement, contract, import-lint or NO-SEND test is weakened.
  - The two operator caps are never assigned.
  - Live enablement, the permit and the orders-off drop-in are untouched.
  - No PREREG.json is edited.
  - No PM.us tape after 2026-09-25 is read by any Kalshi path.
  - K-2a never displaces PM.us work (B-8).

## 1. Goal state (acceptance test for all of K-2)
- A Kalshi family trades live under its own frozen PREREG, hypothesis ledger, α budget and nightly triage.
- It is never pooled with PM.us. Cross-venue rows are refused in both directions.
- The NBP learning loop L runs nightly on the Kalshi stations. Labels are TWC settlement where it differs from CLI (§3).
- It is enabled by a new A1-class ruling plus operator-only enablement.
- There is no bare stop: every negative names its next node (§8).

## 2. Nautilus null hypothesis: real gaps
| Need | Native in 1.231.0? | Disposition |
|---|---|---|
| Kalshi venue protocol (REST/WS, auth, symbology) | No (digest `prediction-markets-native-support.md` fact 28) | **Real gap.** Build `src/breezy/adapters/kalshi/` via extension points only |
| Instrument | Cython `BinaryOption` | Reuse. Mirror PM.us YES plus a local NO (`provider.py:526,643`) |
| Provider, data, exec clients and factories | `InstrumentProvider`, `LiveMarketDataClient`, `LiveExecutionClient`, `add_*_client_factory` | Subclass only. The PM.us tree is the template |
| Fees | `FeeModel` | `KalshiFeeModel(FeeModel)`, ceil_6dp, per-order accumulator |
| Book and quotes | `OrderBookDelta` / `QuoteTick` (Depth10) | Map Kalshi `orderbook_delta` to native types |
| Catalog | `ParquetDataCatalog` | Capture to the catalog. Composite ids use `^`/`:`, never `~` |
| Forecast data | custom `Data` (`ForecastPoint`) plus Actor | Reuse unchanged |
| Reconciliation, cash account, NETTING | Yes | Reuse. Known gap: no live `InstrumentClose` consumer |
| Per-venue permit, venue-scoped ledger, family barrier, `[sites.kalshi.*]`, TWC settlement truth | n/a (Breezy-owned) | **Real Breezy gaps.** Coverage widenings only; PM.us bytes stay pinned |

**Rev 3 correction (F5).** "BUY-YES only" predates the 09-14 NO-side requirement.
- On Kalshi, a NO buy is `side="ask"` on the YES leg at 1−p.
- K-2b mirrors PM.us: a local NO `BinaryOption`, leg-price translation, and the venue's net short-YES leg sign applied in reconciliation.
- Peer question P1 asks whether this is compatible with `allow_short=False`.

## 3. Stage 0: per-station TWC-vs-CLI settlement reconciliation
The design is frozen in K-2a and executed in K-2b. Kalshi settles on The Weather Company, and the CLI code only names the station, so PM.us divergence does not transfer.

**TWC side.** Kalshi's public unauthenticated settled markets: `GET /historical/markets?series_ticker=` and `GET /markets?series_ticker=&status=settled`, using the `k1_kalshi_prior.py:940-977` fetch layer.
- Use `result` and `expiration_value`. That `expiration_value` is TWC's settled °F reading is INFERRED. It is verified by consistency with the `result` partition, and any disagreement means refuse.
- No other admissible historical TWC source exists: `weather.com/kalshi` returns 429, and the TWC API is paid.

**CLI side.** IEM AFOS CLI finals: `is_final=True`, latest revision via `latest_by_archived_climate_day`, with BBB corrections applied.

**Station identity** comes from `rules_primary` only.
- Same-office collisions each need a narrow `body_header_regex` and a sibling-decoy test: KOKX EWR/NYC, KPHI PHL/TTN, KEWX AUS/SAT.
- Known traps: CLIHOU is Hobby; "TWIN CITIES MN"; "AUSTIN BERGSTROM".

**Firewall.**
- Ingest projects only these fields: {ticker, event_ticker, series_ticker, strike_type, floor/cap_strike, status, result, expiration_value, close/expected_expiration_time}. All price, volume and last-price fields are dropped at parse time, and a test enforces it.
- No candlesticks are fetched.
- There are zero PM.us reads.

**Metrics** (per station × series; HIGH primary, LOW separate):
1. Bucket agreement (admission metric), via `WeatherBucketFacts.contains` (`domain/weather_bucket_facts.py:64`). Tails are exclusive; `between` is inclusive at both ends.
2. Value agreement: signed histogram of `expiration_value` − CLI (diagnostic).
3. Strata: DST vs standard, era (2023-01-01), and CLI-correction days.
4. Voids and disputed/amended events raise. They are never counted as agreement.

**Acceptance** (frozen before any fetch):
- n ≥ 90 settled events in the 2023+ exhaustive-bucket era; otherwise HELD, with the listing start recorded.
- Wilson lower bound (z = 1.959963984540054) on bucket agreement > 0.99 means ADMITTED; otherwise EXCLUDED, never down-weighted.
- Any season stratum with n ≥ 30 whose Wilson upper bound is < 0.99 is flagged for peer review.
- Systematic, mechanism-explained divergence may be admitted with TWC-labelled training only via a peer ruling.

**Output:** `docs/evidence/venue/kalshi/KALSHI_TWC_CLI_RECON_<date>.md` plus the admitted set. Zero admitted stations leads to N-0.

## 4. Forecast model carry-over and per-station recalibration
**Carried unchanged:**
- `nbm_quantile_actor.py` and `nbm_quantile_parse.py`
- `nbp_derived_store`
- L (SL-15)
- `ForecastPoint`
- the Rev 3 §3.2 leakage controls
- the `forecast_quantile_ladder` strategy

**Gaps to close:**
- **Stations.** `nbp_backfill.py --stations` already stamps the root station set (`:161-189`). Re-derive from cached raw bulletins where possible. Make venue-hard-coded keys venue-parameterised (`nbp_skill_study._station_latitudes`, `:1340-1345`).
- **Labels.** Extend the CLI-final parquet to the admitted stations, or use `expiration_value` where §3 rules TWC-labelled.
- **Recalibration.** S2 fit κ = ∞ on the PM stations. K-2b adds per-station hierarchical location/scale offsets (a_s, γ_s), shrunk to the pooled fit, with τ chosen by leave-one-station-out CRPS. Fits use train and validate only.
- **Kalshi S2' gate:**
  - G2.0 per station.
  - G2.1–G2.3 on the Kalshi station set's own sealed v5.0 holdout (2026-07-01 onward), opened once and guarded by a marker.
  - n_min recomputed with the A-3 formula on Kalshi-station σ_d (592 is not reused).
  - Climate-day cluster bootstrap, B = 2,000.
- **LOW.** NBP TXN covers HIGH only, so LOW is a separate model and class (KC-2) and is never assumed to transfer.

## 5. Power: Kalshi derives its own numbers (B-2)
None of these PM.us values are reused: n ≈ 1743, 0.04, 0.025/4, θ 0.0695, the 0.25 take rate, and n_min 592. K-2a freezes the derivation procedure and the candidate structure; K-2b (WB-7) fills in the values.

**Candidate class table:**
- KC-1: NBP-HIGH D+1 taker, YES and NO legs, `MEAN_EXCESS_PER_TAKE`.
- KC-2: NBP-LOW D+1 taker. Enters only when a LOW model exists.
- KC-3: reserve maker/resting. Enters only when a verified maker fee exists.

**Constants.**
- MAX_HYPOTHESES_K = 3.
- MAX_VARIANTS_K and MIN_PER_VARIANT_ALPHA_K = α_K / MAX_H_K / MAX_V_K are asserted, never re-derived.
- They live in a separate constants module and a separate ledger, mirroring `hypothesis_ledger.py:181-186`.

**α_K (P2).** Proposed: a fresh 0.025 FWER for the Kalshi programme if K-2b starts on the PM.us KILL. A start before the KILL under a successor ruling must split one 0.025 between the venues.

**Comparator bound.**
- Derived only from a Kalshi SEARCH corpus: historical top-of-book candlesticks for the admitted series, strictly before a freeze date F_K.
- F_K is declared in K-2a and fixed by the K-2b start ruling before any fetch.
- The method is a model-vs-market resolution comparison plus a plausible excess per take net of θ_K.
- The bound is optimistic because there is no depth data; shadow Depth10 corrects it.
- The shared-city Kalshi history (the K-1 prior) is SEARCH-spent and never confirmatory.

**n and feasibility.**
- n_K = ⌈((z(1−α_v,K) + z(0.8)) · 0.5 / bound_K)²⌉.
- Accrual per day = Σ admitted listing-persistence × take-rate_K, both measured in shadow (diagnostic only).
- Feasible only within a horizon ∈ {120, 180} days. Otherwise a zero-look `UNDERPOWERED_NOT_REGISTERED` record goes to the Kalshi ledger, leading to N-2.

**Effective n.**
- One observation per station-day. HIGH and LOW are separate hypotheses, with Bonferroni across classes.
- The five shared cities add zero independence relative to PM.us. That is moot because nothing is pooled, but it is stated in the PREREG.

## 6. Parked branch `wip/kalshi-s4-registry` (58280b6 on d2faeab; 8 files, +618/−17)
WA-0 was done by the coordinator on 2026-10-08 via `git show`.

| Item | Verdict |
|---|---|
| `src/breezy/registry/sites.toml` (+233) | Partly reusable for its values: the settlement clock (08:00 America/New_York, 7-day fallback, NWS-derived delay pair) and the regex shape. Station coverage is wrong (shared cities only), so re-enter it after §3 admission |
| `deploy/systemd/breezy-kalshi-crh-tally.{service,timer}` | Stale: CRH family, which is dead |
| `src/breezy/runtime/settings.py` (+36/−), `observation_composition.py` (+29/−) | Stale and presumed conflicting; refactor Rev 2.1 and AUT-* landed since. Re-derive |
| `tests/unit/test_registry_sites.py` (+239) | Portable. The registry-contract assertions are venue-scoped accessors, the settlement clock is venue-not-site, standard-time climate-day offset, no IANA tz exposure, and Open-Meteo coordinates not reachable via settlement. Port them as Kalshi-site cases |
| `tests/unit/test_polymarket_us_series.py` (+10/−) and `test_runtime_settings.py` (+16/−) | Stale. Small diffs tied to the stale settings and composition changes; drop them |
| Disposition (P3) | Default: a fresh branch from main, with a hand port of the registry values and `test_registry_sites` cases, rather than a rebase. K-2b only. The old branch is never deleted silently |

## 7. Work packages

**K-2a (desk-only, now)**

| WP | Work | Depends on | Acceptance |
|---|---|---|---|
| WA-0 | Branch inspection (§6) | — | DONE 2026-10-08 |
| WA-1 | Peer review to convergence (§11) | — | All reviewers return SOUND or SOUND-WITH-CHANGES, with changes applied |
| WA-2 | Freeze the Stage 0 spec (§3) as a pre-registration document | WA-1 | Doc committed under `docs/plans/`; no fetch |
| WA-3 | Kalshi §6.3 class table, the α_K/MAX_H_K rule, the F_K declaration rule, and the corpus partition (SEARCH / confirmatory / sealed weather holdout), drafted as a ruling | WA-1 | prediction-market-reviewer co-signs; no outcome-derived numbers |
| WA-4 | Interface spec for the venue-scoped ledger: separate jsonl and constants module; PM.us `hypothesis_ledger.py` byte-pin kept | WA-3 | Architect confirms PM.us bytes are unchanged |

**K-2b (KILL-gated).** Each WP is one commit, RED-first, gated by `scripts/ci/run_tests_no_egress.sh` with `lint-imports` after every slice.

| WP | Work | Depends on | Acceptance |
|---|---|---|---|
| WB-0 | Branch disposition | KILL or ruling | Old branch untouched |
| WB-1 | Stage 0 execution: a read-only script reusing the `k1_kalshi_prior` fetch and the IEM CLI loader | WA-2 | Tests: field projection, `expiration_value`/`result` consistency raise, void raise, sibling decoys, DST strata. Output: ADMITTED/HELD/EXCLUDED set |
| WB-2 | Admission completeness: KDEN live recheck, KHOU density, `parse_metar_t_group` 4-digit fix (rev2 only), LOW-window cadence | WB-1 | v1 archive pin byte-identical |
| WB-3 | Barriers S1' (Rev 3:123-127), landed before any `adapters/kalshi/` file | WB-0 | Non-vacuity modules fail B4/B6/E2; C4 at all 6 sites |
| WB-4 | Kalshi ledger, triage, family manifest, `assert_family_only` in both directions | WA-3, WA-4 | PM.us ledger and tally byte-pins green; cross-venue rows refused |
| WB-5 | Weather carry-over (§4) and Kalshi S2' | WB-1 | G2.0–G2.3 pass; holdout opened once. Fail → N-1 |
| WB-6 | Read path: `[sites.kalshi.*]`, symbology, provider (YES plus local NO), GET-only transport with pinned 429 backoff, data client to the catalog, `KalshiFeeModel` plus its own F1 guard | WB-3 | Rev 3 S4–S7 tests; WS subscription cap verified on first boot (L-45) |
| WB-7 | SEARCH comparator and power check on pre-F_K candlesticks | WB-5, WB-4 | REGISTERED, or zero-look UNDERPOWERED → N-2 |
| WB-8 | Kalshi shadow FQ instance (phase-0 permit refuses all orders); ≥14-day parity | WB-5, WB-6 | Deny chain byte-unchanged; no shadow row enters a tally |
| WB-9 | Write path: S11 (operator), S12 RSA-PSS, S13 per-venue permits, S14 exec client in the same process with one shared `DailySpendLedger`, OP-SEQ, reconcile-before-resubmit, S15 live TWC reconciliation | WB-7 REGISTERED, WB-8 | Rev 3 S12–S15 exits |
| WB-10 | Look, then a new A1-class ruling, then operator enablement | WB-9 | Goal state (§1) |

## 8. Decision nodes
- **N-0 (no station admitted):** close K-2 with the evidence recorded. Next lever: a TWC-labelled admission ruling, or GEFS+EMOS via a new S0-class ruling.
- **N-1 (S2' fails):** try the M1 fallback, then KC-2 LOW alone if a LOW model exists, then close.
- **N-2 (UNDERPOWERED):** write the zero-look record, take KC-2/KC-3 intake, and close at the horizon.
- **N-3 (look REJECTED):** L continues; a new estimand must come through Kalshi §6.3 intake.

## 9. Risks
- **Systematic TWC divergence**, from an hourly-max source or the DST day boundary (especially for LOW). Mitigated by the §3 strata and the ruling-gated TWC-label path.
- **Short listing histories:** some series will be HELD for lack of settled events.
- **Spatial correlation:** handled by the cluster bootstrap and a conservative accrual estimate.
- **Calibration drift in new climates:** handled by hierarchical per-station offsets.
- **No depth in the comparator:** corrected by shadow Depth10.
- **Horizon arithmetic:** if the KILL fires 2027-01-25, K-2b runs well into 2027. K-2a's value is removing design latency.
- **Operator lead time:** θ_K, KYC, and eligibility.
- **Permit inheritance and ledger split (highest severity):** S13 lands before S14, with an identity test.
- **Displacement risk:** any step that edits the PM.us path is stop-and-replan.

## 10. Operator-only (nothing else)
1. Kalshi account, eligibility/KYC, funding, and API key (S11).
2. θ_K source: the fee-schedule PDF, or acceptance of first-fill derivation.
3. The two caps, never assigned by the repo. One shared ledger means Kalshi never raises total spend.
4. Live enablement.

Venue priority and the K-2b start are peer-loop decisions (B-8).

## 11. Peer reviewers (WA-1; blind, adversarial)
- **Plan-stage reviewers:**
  - trading-bot-architect (domain and goal-state reachability)
  - prediction-market-reviewer (settlement, §3 metrics, §5 classes, α_K, comparators)
  - mle-reviewer (recalibration, S2' holdout, cluster bootstrap, n_min)
  - architect (governance against RA-13/R3V, Nautilus map, ledger scoping)
  - security-reviewer (new egress host, RSA-PSS, per-venue permits)
- **K-2b code stage:**
  - python-reviewer for every WP
  - security-reviewer for WB-3, WB-6 and WB-9

**Open questions:**
- **P1:** Is the local NO-instrument pair compatible with `allow_short=False` on Kalshi, given the venue nets NO as negative YES?
- **P2:** Is α_K a fresh 0.025, or a split of the existing budget?
- **P3:** Fresh branch, or rebase?
- **P4:** Does Stage 0's price-dropping projection leave the new-station price history unspent?
