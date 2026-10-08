# K-2a plan r2: Kalshi sibling family (desk-only; K-2b runs after programme KILL), 2026-10-08

**Status:** r2 is a complete replacement for r1.
- It applies every WA-1 round-1 review item plus the coordinator rulings.
- Reviewer tags: T = trading-bot-architect, M = prediction-market-reviewer, L = mle-reviewer, A = architect, S = security-reviewer.
- The planner wrote it read-only and the coordinator transcribed it.
- Next step: WA-1 round 2 (convergence).

**Authority:**
- `RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md` §3.3, which amends RA-13 §4 for K-2a.
- RA-13 §5 and §7 B-1..B-8 still bind.
- `PROGRAMME_PATH.md:7`: the stop gate is live-small [A8].
- L-3 (the plan must reach the goal state) [A8].

## 0. Scope and invariants

**K-2a (now) is desk-only: this plan, the WA-2..WA-4 documents, and peer review.**
- No network calls and no runtime change.
- No file is added or edited under `src/`, `scripts/`, `tests/` or `deploy/`.
- No K-2a deliverable adds, edits or enables any host, permit or egress row [S7]. The first egress-pin edit lands with WB-3 or WB-6.

**K-2b starts only on programme KILL** [A1, plus the coordinator ruling on A1 vs T1].
- After the KILL, node N-S (§8) decides start or defer within 7 days [T1].
- Any earlier start needs a new ruling amending RA-13 §4/§5 and R3V §3.3. This plan proposes none.

**Basis.** This re-plans `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` (Rev 3, written for CRH).
- K-2 carries the NBP forecast-quantile family (`RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md:55-56`).
- Rev 3's venue mechanics (S0-verified) and barrier work S1'–S4' carry over.
- Rev 3's tally, power and family sections are replaced.

**Invariants.**
- Nautilus is immutable, and `allow_short=False`.
- No safety, settlement, contract, import-lint or NO-SEND test is weakened. Exact sets widen only by one reviewed row.
- The two operator caps are never assigned.
- No K-2 code touches live enablement, permit minting, or `fq-v1-halt-orders-off.conf` [A7d].
- RULING_FQ-v2-NO-TRADE is in force.
- No existing PREREG.json is edited. The Kalshi PREREG is a new file (WB-7b) [T4].
- No Kalshi path reads PM.us tape dated after 2026-09-25.
- K-2a never displaces PM.us work (B-8).

**Allowed PM.us edits** are only the reviewed rows named in this plan:
- the S13 permit venue binding;
- the D6(i) and independence import contracts;
- the `hypothesis_ledger.py` sha256 pin;
- the egress-pin widenings.

Any other PM.us edit is stop-and-replan.

## 1. Goal state (acceptance test for all of K-2) [L-3]

- **Family:** a Kalshi family trades live under its own frozen PREREG (WB-7b), its own hypothesis ledger, its own α constants (§5), and its own nightly triage.
  - It is never pooled with PM.us.
  - Cross-venue rows are refused in both directions (`assert_family_only`, `src/breezy/settlement/family_barrier.py:52`).
- **Learning loop:** L runs nightly on admitted Kalshi stations under a deployed timer.
  - Done means the first scheduled success is seen [T4 / WB-5b].
  - Labels follow the Stage 0 ruling (§3, §4) [L5].
- **F6 veto [A2]:**
  - Every `forecast_quantile_ladder` manifest is wrapped in `FqComposedVeto` (`src/breezy/app/trade.py:763-809`). The loss-stop artefact is keyed on `catalog_root` (`:779`).
  - RULING_FQ-v2-NO-TRADE makes that veto permanent, so Kalshi going live is an FQ-v2 **T2** event.
  - KC-1 needs its own prereg loss floor that passes FQ-v2 §4.6 for its own mix (WB-7a), recorded by ruling. Opening this plan does not count [T3].
  - The PM.us F6 contract tests stay byte-unchanged.
- **Enablement:** a new A1-class ruling, plus the FQ-v2 T2 ruling, plus operator-only enablement (§10).
- **No bare stop:** every negative names its next node (§8: N-S, N-0..N-5).

## 2. Nautilus null hypothesis: real gaps [L-1, L-11]

| Need | Native in 1.231.0? | Disposition |
|---|---|---|
| Kalshi venue protocol (REST/WS, auth, symbology) | No (digest `prediction-markets-native-support.md` fact 28) | **Real gap.** Build `src/breezy/adapters/kalshi/`, scaffolded from `nautilus_trader/adapters/_template/{core,data,execution,providers}.py` [A8], via extension points only |
| Instrument | Cython `BinaryOption` | Reuse. Mirror PM.us YES plus local NO (`parse_binary_option_pair`, `polymarket_us/provider.py:526,643`) |
| Provider, data/exec clients, factories | `InstrumentProvider`, `LiveMarketDataClient`, `LiveExecutionClient`, `add_*_client_factory` | Subclass only; the PM.us tree is the template |
| Fees | `FeeModel` | `KalshiFeeModel(FeeModel)` is the **backtest/replay seam only**. Live fee truth comes from fill reconciliation, mirroring `taker_fee_at_fill` (`polymarket_us/fees.py:560-594`) [A8]. Rounding follows θ_K sourcing (§5); ceil_6dp is withdrawn [M8] |
| Book / quotes | `OrderBookDelta` / `QuoteTick` (Depth10) | Map Kalshi `orderbook_delta` to native types |
| Catalog | `ParquetDataCatalog` | Capture to the catalog. Composite ids use `^` or `:`, never `~` |
| Forecast data | custom `Data` (`ForecastPoint`) + Actor | Reuse unchanged |
| Reconciliation / cash account / NETTING | Yes | Reuse. Known gap: no live `InstrumentClose` consumer |
| Egress host | n/a | NO-SEND and the allowed-host sets each widen by one reviewed row, in WB-3/WB-6 only, never in K-2a [A8, S2, S7] |
| Per-venue permit, venue-scoped ledger, family barrier, `[sites.kalshi.*]`, TWC settlement truth | n/a (Breezy-owned) | **Real Breezy gaps.** Coverage widenings only (§0 list) |

**NO side and P1 [T5].** K-2b mirrors PM.us:
- a local NO `BinaryOption` and leg-price translation;
- the venue's net short-YES leg sign applied in reconciliation;
- PM.us's echo cross-check (side and intent) and its X3 close-intent discrimination, carried over.

Safeguards:
- The YES-leg SELL translation is keyed on the NO-leg instrument and cannot be reached from the strategy.
- A test proves that no opening SELL of the YES instrument is ever emitted.
- YES/NO cross-leg venue netting is documented and reconciled with the leg sign.

The wire claim "a NO buy is `side=ask` on the YES leg at 1−p" is inherited from Rev 3 and is **UNVERIFIED**. WB-6 verifies it against vendor docs before any write path is built.

## 3. Stage 0: per-station TWC-vs-CLI settlement reconciliation (frozen in WA-2, run in WB-1)

**Event universe [M1, coordinator ruling].**
- The unit is one station-day event (series × climate day).
- Only TWC-era events count, i.e. those whose `rules_primary` names The Weather Company.
- NWS-era events are tautological and serve only to date each series' switch to TWC.

**TWC side [M4].** Public, unauthenticated settled markets, fetched through the k1 layer `list_series_markets` (`scripts/analysis/k1_kalshi_prior.py:939-960`; host `API_BASE` at `:213`).
- **Status filter:** accept both `finalized` and `settled`. The k1 call at `:944` requests only `settled`, so the Stage 0 script passes its own parameters and k1 stays unchanged.
- **`expiration_value` parse [M2]:** a decimal string with a zero fraction becomes an int (seen: '100.00', '82.00', '88'). Any non-integer is REFUSED.
- **Strike semantics [M4]:**
  - `greater` with floor F means ≥F+1.
  - `less` with cap C means ≤C−1.
  - `between` is inclusive at both ends.
- **Ladder property test:** over the fixture ladders, every integer lands in exactly one market per event.
- **Legacy markets:** `strike_type=None` markets are parsed from the rules text, or excluded and listed.
- **Result-partition check [M4]:** it is circular on NWS-era events, so it is a parse sanity check only. A disagreement means REFUSE.
- **No other source:** no other historical TWC source is admissible (`weather.com/kalshi` returns 429; the TWC API is paid).

**CLI side.**
- IEM AFOS CLI finals with `is_final=True`.
- Latest revision via `latest_by_archived_climate_day` (`src/breezy/domain/archived_selection.py:46`), with BBB corrections applied.

**Station identity** comes from `rules_primary` only.
- Same-office collisions get a narrow `body_header_regex` plus a sibling-decoy test: KOKX EWR/NYC, KPHI PHL/TTN, KEWX AUS/SAT.
- Known traps: CLIHOU is Hobby; "TWIN CITIES MN"; "AUSTIN BERGSTROM".

**Projection firewall [S8, M8, P4].**
- A deny-by-default allowlist of response keys: {ticker, event_ticker, series_ticker, strike_type, floor_strike, cap_strike, status, result, expiration_value, close_time, expected_expiration_time, rules_primary}.
- Unknown keys and any price/volume/last-price key are dropped at parse time.
- The raw response is never written. The k1 cache write (`store_markets`, `k1_kalshi_prior.py:1508-1512`) is disabled, or receives projected records only.
- No candlesticks are fetched, and nothing is read from PM.us.
- No trading path reads Stage 0 outputs.
- Tests:
  - no price key appears in any Stage 0 artifact;
  - unknown and price keys are dropped;
  - an import-graph test enforces the no-trading-path rule.

**Metrics.**
1. **Admission [M1, M2, L5]:** exact `expiration_value == CLI extreme`, per TWC-era event. HIGH is primary; LOW is evaluated separately.
2. **Voids [M3]:** voided, disputed and amended events count as **disagreements**. They are also reported separately and never dropped.
3. **Diagnostics only [M2]:**
   - bucket agreement, restricted to the 2 buckets adjacent to the CLI value;
   - the signed `expiration_value` − CLI histogram;
   - strata: DST vs standard time, era, and CLI-correction days.

**Acceptance (frozen before any fetch) [M1, coordinator ruling].**
- **ADMITTED** iff the Wilson lower bound (z = 1.959963984540054) on exact agreement is > 0.99 at the actual n.
  - That needs n ≥ 381 with zero misses, because n/(n+z²) > 0.99 ⇔ n ≥ 381.
  - The r1 n≥90 floor is deleted.
- **EXCLUDED** iff the Wilson upper bound is < 0.99. Excluded stations are never down-weighted.
- **HELD** otherwise. HELD series are re-evaluated as events accrue (N-4).
- **Projected admission date:** for each series, the date n reaches 381 (from the TWC-era listing rate) is a §5 feasibility input. If every station's date falls past the horizon, that is recorded as N-0 evidence; the threshold is never changed.
- **Season stratum flag:** any season stratum with n ≥ 30 and Wilson upper < 0.99 is flagged for peer review.
- **TWC-labelled admission [M5]:** by peer ruling only. It requires a stable, deterministic offset model that predicts TWC from CLI-like inputs (there is no live TWC feed), validated on ≥381 TWC-era events. Otherwise the station is EXCLUDED.

**Output:** `docs/evidence/venue/kalshi/KALSHI_TWC_CLI_RECON_<date>.md`, containing:
- the ADMITTED, HELD and EXCLUDED sets;
- per-series TWC switch dates;
- projected admission dates.

Zero admitted stations, with none projectable within the horizon, leads to N-0.

## 4. Forecast carry-over and per-station recalibration (WB-5)

**Carried unchanged:**
- `nbm_quantile_actor.py` and `nbm_quantile_parse.py`
- `nbp_derived_store`
- L (SL-15)
- `ForecastPoint`
- the Rev 3 §3.2 leakage controls
- the `forecast_quantile_ladder` strategy

**Stations.**
- `nbp_backfill.py --stations` stamps the root station set (`scripts/analysis/nbp_backfill.py:161-189`). Re-derive from cached raw bulletins where possible.
- `_station_latitudes` (`scripts/analysis/nbp_skill_study.py:1332-1346`) iterates the PM registry via `VENUE`. Change it to take a Kalshi registry argument [L8].

**Model [L4]:** y = pooled(version) + a_s + γ_s·z.
- Station effects are fit on pre-v5.0 history only. The v5.0 slice fits version terms only.
- **N_s = 365** distinct pre-v5.0 climate days per station. This is fixed here, outcome-free, as one seasonal cycle, so that a_s does not alias season.
- A station below N_s gets a_s = γ_s = 0 (pooled) plus a flag.

**τ [L3].**
- Chosen by forward-chained, within-station, time-blocked CRPS with outcome-free folds.
- LOSO is a sensitivity check only. The PM.us `select_kappa_by_lovo_crps` (`src/breezy/analysis/nbp_calibration.py:1004`) is not the selector.
- Report τ=0 and τ=∞.

**Labels [L5].**
- Fit labels are fixed by the Stage 0 ruling and recorded in the Kalshi PREREG.
- Holdout gates are scored on TWC labels (`expiration_value`).

**Holdout [L1, adopted in full].**
- Window: [2026-07-01, F_H), with **F_H = min(2027-01-01, K-2b start date)**.
- **Shared stations:** stations in both venue sets (the 5 shared cities) are **excluded** from the Kalshi confirmatory holdout by default. The alternative (a window after the later venue's holdout open date, flagged non-independent) applies only if WA-2 declares it.
- **Marker file:** `holdout_marker_kalshi_<sha256 of sorted station set>.json`.
  - Written create-exclusive (O_EXCL).
  - A C-1 reopen appends and never overwrites.
  - A test proves it never equals the PM.us marker path.
- **PM.us opener:** `open_holdout` (`nbp_calibration.py:353-398`; it overwrites via `write_text` at `:385`, `:398`) stays byte-unchanged. Kalshi gets its own opener.

**S2' gate [L2, L7].**
- G2.0 runs on pooled-over-stations month strata (N=60, ≥15 dates) plus per-station aggregate residuals, never per station-month.
- PASS requires ≥75% of holdout station-days in tested strata; otherwise the result is INCONCLUSIVE.
- G2.0–G2.3 are evaluated **per station**, and only passing stations trade. Pooled results are descriptive.
- One Holm family covers stations × gates (`holm_correction`, `nbp_calibration.py:1670`).
- Climate-day cluster bootstrap, B=2,000.

**n_min [L6].**
- Use the A-3 formula (`compute_n_min`, `nbp_calibration.py:309`).
- X, the ceiling and σ_d all come from the Kalshi validation split, with out-of-fold station offsets and date-clustered σ_d.
- Counted in distinct climate dates.
- The artefact names its sources. 592 is not reused.

**Reproducibility [L8].** The artefact records:
- the station set;
- the raw-cache sha256;
- NBM_VERSION_BREAKS;
- the seed;
- the sites-registry sha.

**LOW** is a separate model and class (KC-2), because NBP TXN covers HIGH only.

## 5. Power and α: Kalshi derives its own numbers (B-2)

None of these PM.us values are reused: n≈1743, 0.04, 0.025/4, θ 0.0695, the 0.25 take rate, n_min 592, or ceil_6dp.

**Classes.**
- KC-1: NBP-HIGH D+1 taker, YES and NO legs, `MEAN_EXCESS_PER_TAKE`.
- KC-2: NBP-LOW. Enters only when a LOW model exists.
- KC-3: reserve maker. Enters only with a verified maker fee.

**Constants [A4, M6, coordinator ruling].**
- A separate constants module and a separate ledger, mirroring `hypothesis_ledger.py`: RE_ARM_GATING_PROGRAMME_ALPHA (`:158`, enforced at `:582`/`:1042`), PROGRAMME_ALPHA (`:177`), and MAX_HYPOTHESES / MIN_PER_VARIANT_ALPHA (`:181-186`).
- The Kalshi constants are PROGRAMME_ALPHA_K, RE_ARM_GATING_PROGRAMME_ALPHA_K, MAX_HYPOTHESES_K = 3 and MAX_VARIANTS_K.
- MIN_PER_VARIANT_ALPHA_K = PROGRAMME_ALPHA_K / MAX_HYPOTHESES_K / MAX_VARIANTS_K. It is asserted, never re-derived.

**α accounting.**
- **Default:** both constants draw on the **same programme totals as PM.us** (0.05 and 0.025), because the families are correlated (same model, same weather days, 5 shared cities).
- Kalshi plus PM.us look-taking allocations must stay within those totals. The WA-3 ruling states the accounting, and the PM.us ledger is read-only to it.
- A fresh budget needs a successor ruling with a stated cross-venue dependence discount.
- The Bonferroni-across-classes layer is deleted.

**θ_K [M8].**
- Taken from the series `fee_type`/`fee_multiplier` (`tests/fixtures/kalshi/series_KXHIGHNY.json:11-12`: quadratic, 1) plus the published schedule, with cent-rounding verified against vendor docs.
- No bound is quoted before θ_K is sourced.

**Comparator bound [M7, M8].**
- SEARCH corpus: top-of-book candlesticks for admitted series, **TWC-era days only**, strictly before **F_K = 2026-10-08** (declared here, frozen in WA-3).
- The candlestick fetch is a separate, later spend, logged in the Kalshi ledger.
- bound_K is the **lower limit** of a 95% climate-day cluster-bootstrap interval (B=2,000) on the SEARCH excess net of θ_K, never a point estimate.
- It is optimistic because the candlesticks carry no depth; shadow Depth10 corrects for that.
- The K-1 prior is SEARCH-spent and never used as confirmatory evidence.

**n and feasibility [M7].**
- n_K = ⌈((z(1−α_v,K) + z(0.8))·0.5 / bound_K)²⌉, counted in **climate-day clusters**.
- Accrual per day (clusters) = Σ admitted listing-persistence × take-rate_K. It is measured in shadow, diagnostic only, and fed by the §3 projected admission dates.
- Feasible only within a horizon of {120, 180} days. Otherwise a zero-look `UNDERPOWERED_NOT_REGISTERED` record is written, which leads to N-2.

**Effective n.**
- One observation per station-day cluster.
- HIGH and LOW are separate hypotheses inside the shared budget.
- The shared cities add zero independence; this is stated in the PREREG.

## 6. Parked branch `wip/kalshi-s4-registry` (58280b6 on d2faeab; 8 files, +618/−17)

WA-0 was done on 2026-10-08 via `git show`.

| Item | Verdict |
|---|---|
| `src/breezy/registry/sites.toml` (+233) | Values reusable: settlement clock (08:00 America/New_York, 7-day fallback, NWS-derived delay pair) and regex shape. Station coverage is wrong (shared cities only); re-enter after §3 admission |
| `deploy/systemd/breezy-kalshi-crh-tally.{service,timer}` | Stale (CRH is dead) |
| `runtime/settings.py`, `observation_composition.py` | Stale; refactor Rev 2.1 and AUT-* landed since, so re-derive. Kalshi config lives in `breezy.adapters.kalshi` or `breezy.registry`, never in `breezy.runtime` [A5] |
| `tests/unit/test_registry_sites.py` (+239) | Portable as Kalshi-site cases |
| `test_polymarket_us_series.py` / `test_runtime_settings.py` diffs | Stale; drop |
| **Disposition [T6, coordinator ruling]** | Fresh branch from main with a hand port, departing from RA-13 §4 "rebase". **WB-0 needs a ruling line amending RA-13 §4 (L-32).** The old branch is never deleted silently |

## 7. Work packages

### K-2a (desk-only, now; documents under `docs/` only)

| WP | Work | Depends | Acceptance |
|---|---|---|---|
| WA-0 | Branch inspection | — | DONE 2026-10-08 |
| WA-1 | Peer review to convergence (§11) | — | All SOUND or SOUND-WITH-CHANGES, with changes applied |
| WA-2 | Freeze Stage 0 (§3) plus §4's N_s, F_H and holdout station rule as a pre-registration doc, including the WB-1 hard request budget and body cap [S1] | WA-1 | Committed under `docs/plans/`; no fetch |
| WA-3 | Ruling draft: class table, α constants and cross-venue accounting (§5), F_K = 2026-10-08, corpus partition (SEARCH / confirmatory / sealed weather holdout), θ_K sourcing rule, KC-1 loss-floor rule (§1) | WA-1 | prediction-market-reviewer co-signs; no outcome-derived numbers |
| WA-4 | Ledger interface spec [A3] (below) | WA-3 | Architect confirms PM.us bytes and contracts unchanged |

**WA-4 detail [A3].**
- **What protects `hypothesis_ledger.py` today.** It has no byte-pin. Its guards are:
  - the two D6(i) contracts (`pyproject.toml:176-213`);
  - `tests/unit/test_hypothesis_ledger.py`;
  - the fixture `hypothesis_ledger_v1_2026-09-27.jsonl`;
  - R3-4 (`tests/unit/test_hypothesis_triage.py:1502`).
- **WA-4 specifies:**
  - (a) a sha256 pin test as a widening, landing as WB-4's first commit;
  - (b) the Kalshi ledger module added to both D6(i) contracts;
  - (c) the reuse-vs-duplication choice.
- **Why not plain reuse.** `register_hypothesis` (`:877`) reads module-level PROGRAMME_ALPHA (`:962-964`) and MAX_HYPOTHESES (`:1114-1118`). `may_gate_re_arm` reads them at `:1244`. Reuse would need a constants parameter, which edits the pinned file.
- **Chosen: partial duplication.**
  - A new `breezy.analysis.hypothesis_ledger_kalshi` imports the record schema and serialisation unchanged.
  - It re-implements registration and gating against the K constants.
  - A parity test runs the PM.us registration vectors through the Kalshi functions with the PM.us constants and expects identical outcomes.

### K-2b (gated: KILL, then N-S START)

Every WP is one commit, RED-first, gated by `scripts/ci/run_tests_no_egress.sh` plus `lint-imports` after every slice, with python-reviewer on each WP.

| WP | Work | Depends | Acceptance |
|---|---|---|---|
| WB-0 | Branch disposition | N-S START; RA-13 §4 ruling line [T6] | Old branch untouched |
| WB-1 | Stage 0 run [S1] (below) | WA-2 | Projection, parse-REFUSE, strike property, void-as-miss, sibling-decoy and DST-strata tests; §3 sets |
| WB-2 | Admission completeness: KDEN live recheck, KHOU density, `parse_metar_t_group` 4-digit fix (`src/breezy/ingest/iem_observations.py:47`; rev2 only), LOW-window cadence | WB-1 | v1 archive pin byte-identical |
| WB-3 | Barriers S1' (Rev 3:123-127), before any `adapters/kalshi/` file; first egress-pin edit allowed [S7] | WB-0 | Non-vacuity modules fail B4/B6/E2; C4 at all 6 sites |
| WB-4 | sha256 pin first [A3a]; then the Kalshi ledger (WA-4 design), triage, family manifest, `assert_family_only` in both directions | WA-3, WA-4 | Pin, PM.us ledger and tally green; cross-venue refused; parity green |
| WB-5 | Weather carry-over and Kalshi S2' (§4) | WB-1 | Per-station G2.0–G2.3 under Holm; holdout opened once (O_EXCL). Fail → N-1 |
| WB-5b | Deploy the nightly L timer for admitted stations [T4] | WB-5 | First scheduled success seen |
| WB-6 | Read path (below) | WB-3 | Rev 3 S4–S7 tests; WS subscription cap verified by coverage count on first boot (L-45) |
| WB-7 | SEARCH comparator (§5; fetch ledger-logged) and power check | WB-5, WB-4 | REGISTERED, or zero-look UNDERPOWERED → N-2 |
| WB-7a | KC-1 prereg loss floor passing FQ-v2 §4.6 for its own mix [A2] | WB-7 | prediction-market-reviewer sign-off |
| WB-7b | Freeze the Kalshi PREREG.json (new file; no PM.us PREREG edit); register hypotheses in the Kalshi ledger [T4] | WB-7a | Before any confirmatory use; frozen sha recorded |
| WB-8 | Kalshi shadow FQ instance (phase-0 permit refuses all orders); ≥14-day parity | WB-5b, WB-6 | Deny chain byte-unchanged; no shadow row in any tally; Kalshi `loss_stop_artefact_path` distinct from PM.us [A2]. Fail → N-5 |
| WB-9a | S12 key custody and trap tests; S13 venue-bound permits (below) | WB-7b, WB-8 | security-reviewer sign-off |
| WB-9b | S14 two-venue node and shared ledger (below) | WB-9a | architect and security-reviewer sign-off before merge [S9] |
| WB-9c | S15 live TWC reconciliation, OP-SEQ, reconcile-before-resubmit | WB-9b | Rev 3 S15 exits |
| WB-10 | Look → FQ-v2 T2 ruling [T3] + new A1-class ruling → operator enablement | WB-9c | Goal state (§1) |

**WB-1 detail (Stage 0 run) [S1].**
- A `scripts/` entry point launched deliberately via `systemd-run --user`, never run from `src/` or tests.
- Network goes only through the k1 layer: GET only, host allowlist exactly `api.elections.kalshi.com`, and the WA-2 request budget and body cap.
- Reuses the IEM CLI loader.
- Tests use a stub transport. The gate is `run_tests_no_egress.sh` with canary N3, plus a test that no `scripts/` module opens a socket at import.

**WB-6 detail (read path).**
- Components:
  - `[sites.kalshi.*]` and symbology;
  - a provider (YES plus local NO);
  - a GET-only transport with a pinned 429 backoff;
  - a data client writing to the catalog;
  - `KalshiFeeModel` (seam only) plus its own F1 guard [A8].
- Verify the NO wire semantics against vendor docs [T5].
- **Import-linter [A5]:**
  - a new `independence` contract between `polymarket_us` and `kalshi`;
  - no new `ignore_imports` row in the layers contract (`pyproject.toml:74-106`);
  - `lint-imports` reports N+1 kept.
- **Egress [S2]:**
  - read-path modules join the egress-pin sets in the same commit that creates them;
  - pre-existing rows are reused: C3/C5 `_VENUE_HOST_RE` (`tests/unit/test_polymarket_us_readonly_guard.py:232-234`), the SDK ban (`:181`), and the `adapters/kalshi/exec/` E0 prefix (`test_cage_rule_constants_are_pinned.py:220-224`);
  - the alerts egress pin is unchanged, and Kalshi never uses alert egress.
- `test_operator_control_assignment_scan.py` is extended to `adapters/kalshi/` [S6d].

**WB-9a detail (keys and permits).**
- **Key custody [S3]:**
  - The PEM lives at `~/.config/breezy/kalshi.env`, or a 0600 PEM referenced from it, outside the repo. Looser permissions are refused.
  - It is held in a redacted secure-string container like PolymarketUSCredentials. repr, str, pickle, deepcopy and exceptions all render REDACTED, and the key id is redacted too.
- **RED-first trap tests [S4]:**
  - (a) repr redaction;
  - (b) a malformed PEM is rejected without being echoed;
  - (c) no key material appears in tracebacks or logs;
  - (d) a loose-permission PEM is refused;
  - (e) PERMITTED_METHODS stays GET-only until WB-9b;
  - (f) the canonical string is checked against vendor docs plus a golden vector, behind a VERIFIED predicate that stays False until then;
  - (g) clock-skew errors do not leak.
- **Venue-bound permits [S5]:**
  - `OrderSubmissionPermit` (`src/breezy/runtime/order_enablement.py:155`, no venue field today) and the LiveTradingPermit issued at `polymarket_us/safety.py:673` gain a mandatory, immutable venue set at `issue()`.
  - Every submit path asserts `permit.venue == client.venue`.
  - Identity tests run in both directions, and a no-venue permit is refused.
  - The PM.us issuer stamps the PM.us venue, as a one-row reviewed widening.

**WB-9b detail (two-venue node and shared ledger).**
- **Two venues in one node [A7d].** The node runs one family today (`boot_family`, `trade.py:987-1028`), so this is a node, supervisor and manifest change.
  - The node stays ONE process [S6]; a separate process is forbidden.
  - The orders-off drop-in is process-wide. Arming Kalshi never edits `fq-v1-halt-orders-off.conf` or PM.us enablement; otherwise stop and replan.
- **Shared ledger [A6].**
  - The `app` composition root builds ONE `DailySpendLedger` (`src/breezy/adapters/polymarket_us/operator_controls.py:264`) and injects it into both exec clients. The Kalshi client depends on a local Protocol.
  - Kalshi cost is venue-neutral notional including fees.
  - `authorize_order_cost` (`:348`) is the sole gate.
- **Boot seed [A7a].** It sums durable fills from **both** venue stores before the first authorize (`seed_spent` is one-shot, `:307-316`).
- **Session ceilings [A7b].** These derive at permit mint (`safety.py:582-599`). The shared ledger is the binding dollar cap. The session order count is shared or split so the combined count never exceeds the single-venue derivation (tested).
- **Shared cities [A7c].** A cross-venue position on one station-day in the 5 shared cities is **refused** unless a peer ruling declares it distinct.
- **Tests [S6]:**
  - (a) the combined cap cannot be exceeded;
  - (b) a two-venue race does not double-spend;
  - (c) the seed is idempotent and counts Kalshi fills exactly once;
  - a restart after a Kalshi fill refuses at the daily budget [A7a];
  - the WB-8 shadow cannot reach any Kalshi write endpoint [S9].

## 8. Decision nodes (every terminal node is named)

Happy path: KILL → N-S START → WB-0..WB-10 → goal state.

- **N-S (KILL recorded) [T1].** Within 7 days the peer loop issues a start/defer ruling; the default is START. A DEFER names its next review date, and N-S is re-run then.
- **N-0 (no station admitted, or none projectable within the horizon).** Close K-2 with the evidence recorded. Next lever: a TWC-label ruling (M5 bar), or GEFS+EMOS via a new S0-class ruling.
- **N-1 (S2' fails) [T2].** Try the M1 fallback, then KC-2 LOW alone. Failing those, write the REJECTED record and apply N-3's intake rule.
- **N-2 (UNDERPOWERED) [T2].** Write the zero-look record. Re-derive at the next horizon step (120→180) or on a T3-class take-rate change. If neither applies, take KC-2/KC-3 intake and close at the horizon.
- **N-3 (look REJECTED).** L continues. A new estimand must come through Kalshi §6.3 intake.
- **N-4 (HELD) [T2, coordinator ruling].** Re-check monthly until n≥381 or the horizon. No admission by the horizon goes to N-0.
- **N-5 (WB-8 parity fail) [T2].** Run a root-cause WP (WB-8r). No WB-9 until a fresh ≥14-day re-run passes; the re-run returns to WB-8.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Short TWC-era histories (high): the 381 floor HOLDs most series initially (N-4) | Projected dates feed §5, so infeasibility surfaces early |
| Systematic TWC divergence (hourly max; DST boundary, especially for LOW) | §3 strata; M5-gated TWC label |
| Spatial and cross-venue correlation | Climate-day clusters; shared α totals; shared-city holdout exclusion |
| Calibration drift in new climates | Hierarchical offsets with the N_s gate |
| No depth in the comparator | Use the lower confidence limit; shadow Depth10 corrects |
| Two-venue node composition (highest): permit, ledger split, seed | Do WB-9a before WB-9b; identity tests; dual review |
| F6 permanence | Kalshi going live needs FQ-v2 T2 (WB-7a, WB-10) |
| Horizon arithmetic: a KILL on 2027-01-25 pushes K-2b well into 2027 | K-2a removes the design latency |
| Displacement | Any PM.us edit outside §0 is stop-and-replan |

## 10. Operator-only (nothing else)

1. Kalshi account, eligibility/KYC, funding and API key (S11).
2. The two caps. The repo never assigns them. One shared ledger means Kalshi never raises total spend.
3. Live enablement.

θ_K is sourced from public data, so it is no longer an operator item [M8]. Venue priority and the K-2b start are peer-loop decisions (B-8, N-S).

## 11. Reviewers and open questions

**Plan stage (WA-1 round 2):**
- trading-bot-architect
- prediction-market-reviewer
- mle-reviewer
- architect
- security-reviewer

**K-2b code stage:**
- python-reviewer on every WP;
- security-reviewer on WB-1, WB-3, WB-6, WB-9a and WB-9b;
- architect on WB-4 and WB-9b.

**Resolved questions:**
- **P1:** yes, with the T5 controls; the wire claim is verified in WB-6.
- **P2:** shared totals by default; a fresh budget needs a ruling.
- **P3:** fresh branch, plus an RA-13 §4 ruling line.
- **P4:** yes, with the M8/S8 projection, no raw writes, and a logged candlestick spend.
- **Optional [T7]:** a desk pre-screen of the committed enumeration docs, only under a successor ruling.

## Change log r1 → r2

| § | Changes |
|---|---|
| §0 | KILL-only start, then N-S [A1, T1]; desk-only host/permit/egress invariant [S7]; allowed PM.us edit list |
| §1 | F6/FQ-v2 T2 [A2, T3]; L timer done-criterion [T4]; nodes |
| §2 | `_template` scaffold, FeeModel as seam, egress row [A8]; P1 controls and UNVERIFIED wire claim [T5]; ceil_6dp withdrawn [M8] |
| §3 | M1–M5; S8 and M8 projection |
| §4 | L1–L8 |
| §5 | A4/M6 α; M7/M8 power and θ_K |
| §6 | T6 ruling line; A5 config placement |
| §7 | WA-4 rewritten [A3]; WB-5b and WB-7b [T4]; WB-7a [A2]; WB-1 egress [S1]; WB-6 imports and egress [A5, S2]; WB-9 split into 9a/9b/9c [S3–S6, S9, A6, A7] |
| §8 | N-S, N-4, N-5 added; N-1 and N-2 rewritten [T1, T2] |
| §10 | θ_K removed [M8] |
| §11 | P1–P4 resolved; T7 recorded |

## Applied with interpretation (for round 2)

1. **A3(a):** the pin is specified in WA-4 but lands as WB-4's first commit, because K-2a writes no tests.
2. **Citations corrected:**
   - `hypothesis_ledger.py:1244` is `may_gate_re_arm`, not `register_hypothesis`;
   - `open_holdout` is at `:353-398`;
   - session ceilings are at `safety.py:582-599`;
   - D6(i) spans `pyproject.toml:176-213`.
3. **S1 "operator-launched":** read as coordinator-launched via `systemd-run`. The operator reserves only the caps and enablement, and the security intent is kept.
4. **α debit mechanics** under the shared totals are left to the WA-3 ruling. The PM.us ledger cannot read Kalshi spend without a PM.us edit, so the plan relies on K-2b being KILL-gated.
5. **Values to confirm:**
   - N_s = 365 [L4];
   - F_H = min(2027-01-01, K-2b start) [L1];
   - F_K = 2026-10-08 [M7];
   - EXCLUDED defined as Wilson upper < 0.99.
6. **N-5 loop** is uncapped. T2 did not bound it, and adding a cap would be invention.
