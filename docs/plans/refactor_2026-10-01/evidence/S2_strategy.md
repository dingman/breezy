This is a read-only inventory of the strategy seam. I will verify package wiring, rulings, and Nautilus capabilities from the repo and the installed library, then report only what those sources support.HEAD is `60290e9d`. Next I will pin family status from the programme docs and see which packages the composition root and supervisor actually load.## Maintainability evidence — strategy seam

HEAD `60290e9ddd297a2a08d9da7d626f8c557b9d31f5`. Read-only. NautilusTrader **1.231.0** (`trading/strategy.pyx`, `common/actor.pyx`). Codegraph explore failed (`readonly database`); evidence is from source, AST, and diffs. LOC is `wc -l` on `*.py`.

## (A) Family inventory

Strategy tree: **93 files, 31,075 LOC**. Settlement **10 / 3,041**. Analysis **9 / 7,287**. App **2 / 1,105** (`trade.py` 1,099).

Live composition is `app/trade.py` `run` (`:590`, `:607`, `:709`): three `composition_kind`s. Unit file `deploy/systemd/breezy-trade-supervisor.service:128` sets `BREEZY_SENDING_FAMILY_ID=pm_us_crh_fq_v1`. Running systemd was not inspected.

| Package | LOC | What | Wired | Status | Share vs copy |
|---|---:|---|---|---|---|
| `current_rung_hold` | 15,281 | v2 rung-hold + continuous hunter, monitor, halt CLIs | `trade.py` kinds `current_rung_hold`, `continuous_rung_hold` | **CONFIRMED** `pm_us_crh_v2` REGISTERED (`deploy/families/pm_us_crh_v2.json`); `pm_us_crh_cont` REGISTERED, `d0=2026-09-12`, `terminal_climate_day=2026-09-19`; `pm_us_crh_v4` REGISTERED continuous; `pm_us_crh_exit_v4` DRAFT. PROGRESS:32 still calls cont the live-measurement family (PREREG v3). Tally barrier closes days **after** terminal (`family_barrier.py:85-90`). Not the unit’s sending id. | Uses `weather_common` only for halt, refusals, running-max. Fee and book-walk are local copies. |
| `forecast_quantile_ladder` | 2,530 | D+1 quantile taker | `trade.py:709` kind `forecast_quantile_ladder` | **CONFIRMED** `pm_us_crh_fq_v1.json` status REGISTERED, `d0_climate_day=2026-10-02`, `live_orders_ruling=…2026-10-01`. Unit sends this id. PROGRESS:86 still says S9 activation pending — stale vs manifest. `trade.py:709-719` still says the branch is unreachable because the manifest stays `DRAFT_NOT_REGISTERED` — false against the JSON. | Reuses `ladder_ev` + `weather_common.costs`. Not the SharedExposure shell. |
| `ladder_ev` | 2,494 | Stage-1 pure EV/density/forecast archive. Docstring: no Strategy (`ladder_ev/__init__.py:1`) | Not a composition kind. Imported by FQ and `analysis/nbp_*` | **CONFIRMED** library, live for NBP. PROGRESS:82 stage 2 PARKED. | Shared into FQ. Margin formula reimplemented, not called (`margin.py:12-14`). |
| `weather_common` | 3,845 | Risk, equity, quotes, probability, ladder walk, running max | Library | **CONFIRMED** live via CRH/FQ slices; bulk used by the dead shell below. | The shared layer. |
| `cli_settlement_print_lock` | 1,831 | Buy the bucket the FINAL CLI already settled | Not in `app/` | **CONFIRMED DEAD** L-9 (`docs/core/LESSONS.md:449-472`): 0 asks / 3332 rows. Falsification doc §1 stability gates PASS (`observation_lock_falsification_2026-08-31.md:15-23`) — economic offer still absent. | SharedExposure shell. |
| `forecast_revision` | 1,101 | Trade unabsorbed forecast revisions | Not in `app/` | **HYPOTHESIS** inside the 09-20 point-forecast close. No class name in that ruling. | Near-copy of calibration shell. |
| `calibration_mean_reversion` | 936 | Calibrated-p vs midpoint | Not in `app/` | **HYPOTHESIS** this is K1. PROGRESS:30 “K1 DEAD at ask ≥2c”; package name matches; ruling text read does not name the class. | Near-copy of revision shell. |
| `running_extreme_lock` | 902 | Buy the already-cleared open tail. `open_tail_only=False` refused (`strategy.py:199-205`) | Not in `app/` | **CONFIRMED DEAD** L-9 table; G-01 interior buckets dead (PROGRESS:29). | Same shell, lower body overlap. |
| `forecast_mispricing` | 867 | Model-p vs bid/ask | Not in `app/` | **HYPOTHESIS** same 09-20 close as revision. PROGRESS:30 names `pm_us_crh_fc_v1` CLOSED (`RULING_forecast_edge_programme_closes_2026-09-20.md`). | Same shell. |
| `_root` | 1,288 | See below | Mixed | — | — |
| `depth10.py` (85) | | Depth10 pad-safe quotes | Live importers include CRH, FQ, weather shells | **CONFIRMED retain** | Shared. |
| `harness_probe.py` (251) | | Backtest harness proof | `runtime/backtest_harness.py` | **CONFIRMED** test/harness only, not a family. | — |
| `forecast_edge.py` (224) | | Simple observation edge buyer | `tests/integration/test_forecast_edge_backtest.py` only (src hit is a comment) | **CONFIRMED** tests-only. | — |
| `resting_ladder.py` (392) | | Resting limit ladder | `tests/integration/test_resting_ladder_backtest.py` only | **CONFIRMED** tests-only. | Uses native NT portfolio/cache. |
| `strike_ladder.py` (318) | | Multi-instrument strike ladder | `tests/contract/test_multi_instrument_weather_strategy.py` only | **CONFIRMED** tests-only. | — |
| `settlement/` | 3,041 | Grade predicate, PREREG v2 score, tally barrier, ROI bound, exit guard | Not a strategy. Scorers/scripts | **CONFIRMED retain**. v2 statistic is sibling of v1, not a replacement (`current_rung_hold_v2.py:9-13`). | — |
| `analysis/` | 7,287 | Hypothesis ledger, NBP calibration, replay census, Brier | Offline. `nbp_calibration.py` imports `ladder_ev` | **CONFIRMED** NBP S2 machinery, not a sending strategy. PROGRESS:30 S2 still runs at n_min. | — |
| `app/trade.py` | 1,099 | Composition root | The live boot | **CONFIRMED** three kinds only. | Halt-latch preamble copied between cont and FQ. |

`kalshi_crh_v1.json` is `DRAFT_NOT_REGISTERED` / `current_rung_hold`. No Kalshi strategy package in this seam.

Weather shell import of `weather_common` (SharedExposure, risk, equity, inflight, refusals): calibration, mispricing, revision, lock, cli. **CONFIRMED** they share that library and still copy the Strategy class. CRH/FQ do not use that shell.

Reachable from `scripts/` but not `app/`: the five shell packages, via `scripts/analysis/run_weather_strategy_backtests.py`. Lock also via `weather_strategy_backtest_lib.py`.

## (B) Cross-family duplication

Ranked by duplicated LOC × confidence. “Identical” means `difflib` ratio 1.0 on the method.

| Rank | What | Copies | Diff | LOC | Tag |
|---|---|---|---|---:|---|
| 1 | Strategy shell: `__init__`, `on_start`, `_evaluate_and_act`, `_flatten`, `_maybe_submit`, `_portfolio_snapshot`, `_report_refusals`, `_risk_limits`, `_submit_delta`, `on_quote_tick` | `calibration_mean_reversion/strategy.py` vs `forecast_revision/strategy.py` file ratio **0.847** (545 vs 534). Identical: `_flatten` 35 (`cal` ~L490 area), `_maybe_submit` 72, `_portfolio_snapshot` 14, `_report_refusals` 15, `_risk_limits` 18, `_submit_delta` 38, `on_quote_tick` 13. `__init__` 0.909, `on_start` 0.974. Mispricing file ratio 0.870 vs calibration, 0.843 vs revision. | Decisions are **not** copies (calibration vs revision decision ratio **0.145**). | ~200 lines identical × 2 extra files ≈ **400** | **CONFIRMED** |
| 2 | Same shell, weaker | `running_extreme_lock/strategy.py` (462) vs `cli_settlement_print_lock/strategy.py` (1,001) ratio **0.380**. Method-name Jaccard vs mispricing 0.83 and 0.59. | Lock/cli decisions differ (247 and 141 line `evaluate_instrument`s). | Shell overlap ~150–250, not line-identical | **CONFIRMED** structure, **HYPOTHESIS** exact line savings |
| 3 | Halt-latch boot preamble | `trade.py:607-688` (continuous) vs `:730-744` (FQ). Comments say same shape, different key prefix and latch type. | Permit object is shared (`phase1_sending_permit`, `composition.py:257`). | ~40–80 | **CONFIRMED** |
| 4 | Fee `θ·p·(1−p)` | `weather_common/costs.py:155-183` `venue_fee_prob` (float, raises outside [0,1]). `current_rung_hold/decision.py:320-327` `_fee` (Decimal, ROUND_HALF_EVEN to the cent). `monitor_evidence.py:213-222` `exit_fee` calls `_fee` then × qty. Adapter `polymarket_us_fee` is a third implementation outside this seam. | Type, rounding, and validation differ. Comment at `decision.py:330-334` forbids a second study copy. | ~40 near-dup | **CONFIRMED** not safe to fold |
| 5 | Book walk | `weather_common/ladder.py:135` `walk_ask_ladder` (float levels, None if no depth, partial fill kept). `monitor_evidence.py:162-198` `walk_exit_vwap` (Decimal depth, YES bids / NO `1-ask`, **no partial**). | Different failure and NO rule. | ~40–70 | **CONFIRMED** near-dup, merge would change behaviour |
| 6 | Settlement clock | `forecast_quantile_ladder/margin.py:40-64` and `scripts/analysis/nbp_shadow_parity_pure.py:201-216`. Same `_local_midnight_utc_ns`. Margin docstring says the parity path **must not call** this function. | Intentional split. | ~24 × 2 | **CONFIRMED** |
| 7 | Horizon margin | `ladder_ev/scoring.py:90-96` returns None when `n_cell < n_min_cell`. `forecast_quantile_ladder/margin.py:30-37` same line, **no** `n_cell` (ruling A-6, docstring `:12-14` says it must not call `scoring.margin`). | Dropping the cell gate is a behaviour change. | ~7 | **CONFIRMED** |
| 8 | `AllowShortNotPermittedError` | `current_rung_hold/config.py:109`, `forecast_quantile_ladder/config.py:33`, `ladder_ev/config.py:41`. Weather configs default `allow_short=False` and do **not** raise (`forecast_revision/config.py:109`). | CRH comment `:116-119` records that difference on purpose (L-22). | ~15 × 3 | **CONFIRMED** |
| 9 | `_ns_to_datetime` | Five identical 2-line copies: mispricing `:518`, calibration `:544`, revision `:533`, lock `:461`, cli `:1000`. | Trivial. | 10 | **CONFIRMED** |
| 10 | `strategy_component_id` | `current_rung_hold/composition.py:192`, `forecast_quantile_ladder/composition.py:78` | 3 lines. File ratio of the two compositions is **0.060**. | 6 | **CONFIRMED** |

`evaluate_instrument` is five different economics under one name (mispricing `:61` 165 lines, calibration `:86` 160, revision `:210` 175, lock `:163` 141, cli `:341` 247). Consolidating them is a behaviour change. **CONFIRMED**

## (C) Nautilus substitution candidates

Installed `Strategy` (`strategy.pyx:109-184`) already supplies `on_start/stop/resume/reset`, `order_factory`, `cache`, `portfolio`, `submit_order`, `cancel_all_orders` (`:1215`), `close_all_positions` (`:1418`), `external_order_claims` (`:165`, `:191`), OMS type (`:117-123`). `Actor` supplies `subscribe_*` (`actor.pyx:1258+`), indicator registration (`:791`), and `_resume` → `on_resume` (`:1228-1229`). `_stop` cancels all timers (`:1211-1216`).

| Candidate | What Breezy does | Behavioural difference | Tag |
|---|---|---|---|
| Subscriptions, order factory, portfolio net position | Weather shell and CRH already call `subscribe_quote_ticks` / `subscribe_order_book_depth` / `order_factory.limit` / `portfolio.net_position` (e.g. calibration `strategy.py:215-216`, `:328`, `:457`). | No substitution left. Replacing call sites with a wrapper adds indirection. | **CONFIRMED** already native |
| `cache.orders_open` instead of `working_orders` | `weather_common/inflight.py:74-79` uses `cache.orders` and drops `is_closed`. | Docstring: `orders_open` **misses INITIALIZED and SUBMITTED**. That miss is why the helper exists. | **CONFIRMED** do not replace |
| `close_all_positions` / `cancel_all_orders` | Weather `_flatten` already calls both (calibration `:522-523`, mispricing `:496-497`, revision `:511-512`). | PROGRESS:80 T-9: per-family PREREG exit, no blind flatten. NT `on_market_exit` is a different policy. | **CONFIRMED** already used; do not point live CRH at market-exit |
| `external_order_claims` | CRH builder sets them (`composition.py:428-502`, `:715`) and refuses overlap (`:453-457`). | This **is** the native claim list. FQ path was not shown setting it in the lines read. | **CONFIRMED** for CRH; **HYPOTHESIS** FQ claims unset |
| `Clock.set_timer` | Fee-drift probe uses it (`fee_drift_probe.py:345`, citing `component.pyx:419`). | Native. `_stop` then cancels every timer. | **CONFIRMED** |
| Indicators | `register_indicator_for_quote_ticks` updates on quotes. | Breezy “probability” is a forecast-error model (`weather_common/probability.py`), not a quote indicator. Registering it would change the update rule. | **CONFIRMED** not equivalent |
| `Portfolio` PnL vs `observed_equity` / `RiskManager` | `equity.py:80`, `risk.py` `evaluate_order` (~`:572`, 171 lines). | Pre-trade edge, freshness, and short refusal. Portfolio has no model probability. | **CONFIRMED** different job |
| `on_resume` | No `def on_resume` under `strategy/`. Default warns (`strategy.pyx:238-244`). | Resume does not call `on_start` (`actor.pyx:1228-1229`). A stopped-then-resumed strategy would not resubscribe. Live node was not shown to resume. | **HYPOTHESIS** hazard, not a refactor target |
| `StrategyConfig` validation | NT checks `config` type (`strategy.pyx:144`) and msgspec-encodes fields (CRH config `:127-131`). | `allow_short` is a Breezy field. NT will not reject `True`. Families that only default it can be constructed `True` (`tests/unit/test_forecast_sigma_uses_issuance_lead.py` builds `ForecastRevisionConfig(..., allow_short=True)`). | **CONFIRMED** |
| OMS `HEDGING` vs `NETTING` | Unset → `UNSPECIFIED` → venue default (`strategy.pyx:155-164`). | Multi-rung “one position per instrument” may or may not match venue OMS. Not verified. | **HYPOTHESIS** |
| `ExecAlgorithm` | No subclass in this seam. | Taker decision is not an exec algo. | **CONFIRMED** absent; not a substitute |

## (D) Abstraction and dead code

| Finding | Evidence | Tag |
|---|---|---|
| One production `BoundsProvider` | Protocol `forecast_quantile_ladder/bounds.py:40`. Real impl `ArtefactBoundsProvider` (`artefact_bounds.py:38`). Tests and parity scripts also name it. | **CONFIRMED** seam is filled |
| `SupportsExpiresAtNs` | `forecast_quantile_ladder/strategy.py:94`. Comment `:517` says the cast is type-only. | **CONFIRMED** |
| `_DeadVerdict`, `_PartitionCell` | Mentioned only in `promotion_criteria.py:78` and `density_table.py:142`. | **CONFIRMED** single-file |
| `ForecastSource`, `FeeCoefficientSource`, `FamilyIdentity`, `SupportsQuantileLatch` | Multiple src users (forecast source: strategies + backtest script). | **CONFIRMED** not one-impl |
| No factory-of-factories | `default_registry` is `registry/sites.py:500`, called from `trade.py:745`. One site table. | **CONFIRMED** |
| Oversized modules (>800) | `continuous_strategy.py` **3434** (class `ContinuousRungHoldStrategy` starts `:418`, ~3017 lines), `trial_day_latch.py` **1808**, `nbp_calibration.py` **2665**, `hypothesis_ledger.py` **1398**, `trade.py` **1099**, `replay_sufficiency.py` **1040**, `cli…/strategy.py` **1001**, `composition.py` **909**, `forecast_quantile_ladder/strategy.py` **841**. `risk.py` 764. | **CONFIRMED** |
| Functions >50 lines | **112** in the four trees; **50** over 80. Worst: `_hunt_tick` `continuous_strategy.py:1872` **570** lines; `_evaluate_no_side_shadow` `:2443` **327**; `trade.run` `:486` **476**; `register_hypothesis` `hypothesis_ledger.py:877` **341**. | **CONFIRMED** |
| Public top-level funcs with no other src/scripts file | 21 names, length ≥12. Spot-check: every one occurs ≥2 times in its own file (internal calls). `build_eligible_inputs_no_side` and `exit_rule_from_tags` have **zero** test files but are used in-module. | **CONFIRMED** not dead. **HYPOTHESIS** dead methods inside the 3017-line class were not enumerated. |
| Tests-only strategies | `BreezyRestingLadder`, `BreezyStrikeLadder`, `ForecastHighEdgeBuyer`. | **CONFIRMED** |
| Nesting depth | Not measured. | **HYPOTHESIS** `_hunt_tick` is the place to look |

## (E) Invariants and pinning tests

| Invariant | Where fixed | Pinning tests seen | Tag |
|---|---|---|---|
| Never `allow_short=True` on the live rule | PROGRESS:39. Unforgeable on CRH (`config.py:109-119`), FQ (`config.py:33`), ladder_ev (`config.py:41`). Weather shell **defaults** False only (`forecast_revision/config.py:109`). | `tests/strategy/forecast_quantile_ladder/test_config.py`, `tests/strategy/ladder_ev/test_config.py`, `tests/unit/test_weather_common_risk.py`. Revision test **constructs True**. | **CONFIRMED** the pin is not uniform |
| Do not weaken `BacktestOrderGuard` | PROGRESS:39. Class `runtime/backtest_order_guard.py:168`. Inflight docstring `:94` says the guard sums working SELLs because a signed scalar cannot. | `tests/contract/test_reconciliation_settlement_price_hazard.py:125` builds a real guard. | **CONFIRMED** |
| Settlement-grade = FINAL, not superseded, `tmax_f` present | `settlement/settlement_truth.py:30-44`. Docstring `:11-12`: do not delete the script copy or let them diverge. | `tests/unit/test_cli_basis_offer_gate_settlement.py` (named in that docstring). | **CONFIRMED** |
| H0 variance, mutual exclusion | `combine_station_day` `current_rung_hold_v2.py:296-343`: `Var = Σ qty² q(1−q) − 2 Σ_{i<j} qty_i qty_j sign_i sign_j q_i q_j`. `score_combined` `:346-362` uses `I = Σ Var`. L-40 (`LESSONS.md:1382-1402`): qty≡1 same-side collapses to `S(1−S)≤1/4`; mixed YES+NO max is **1.0**, not 1/4. L-41 (`:1405-1417`): null is `BE_i` = true cell probability, no quote noise. | `tests/unit/test_multi_position_validation_2026_09_14.py` (named by L-41), `tests/unit/test_family_tally_v2_look_loop_golden.py` (L-40 amendment), `tests/unit/test_current_rung_hold_v2_strata.py` (Wilson restatement, `:370-373`). | **CONFIRMED** |
| NO-side hunting is required | PROGRESS:31 supersedes BL-6 (NO-1, 09-14). Hunt bodies: `continuous_strategy.py:1565` `_hunt_no_only`, `:2443` `_evaluate_no_side_shadow`. NO EV: `ladder_ev/scoring.py:70` `ev_net_no` (buys NO long; `intent_long_yes=False` is short-YES and returns None). | `tests/unit/test_no_leg_depth10_bid_ladder_2026_09_14.py`. L-41 names `tests/unit/test_no_side_ldobf_validation_2026_09_14.py`. | **CONFIRMED** requirement; the NO-1 ruling file was not opened |
| PREREG changes only by `docs/evidence/` ruling | PROGRESS:41-42. v1 scripts stay byte-unmodified (`current_rung_hold_v2.py:9-13`). | `tests/unit/test_prereg_v1_is_byte_unmodified.py`, `tests/unit/test_settlement_purity_guard.py` (named there). | **CONFIRMED** |
| Cont tally window | `pm_us_crh_cont.json` `terminal_climate_day=2026-09-19`. Barrier refuses later climate days (`family_barrier.py:85-90`). | `tests/unit/test_family_barrier.py`, `tests/unit/test_aud05_family_barrier_pin.py`. | **CONFIRMED** for scoring. Whether the strategy stops sending was **not** traced. |

## (F) Dispositions

No deletion ban for strategy **packages** was found. L-9 bans **designing** another lock, not deleting source. Explicit “do not delete” applies to the two `is_settlement_grade` copies and to byte-identical v1 scripts. Removing a package still fails its tests until those move. That is a test-surface change, not a live-trading change, and it still wants a ruling because PROGRESS:41 binds settlement and PREREG edits.

| Unit | Disposition | Why | Behaviour change? |
|---|---|---|---|
| `current_rung_hold` | **retain**, then split `continuous_strategy.py` / `trial_day_latch.py` only as moves | Live and registered families. v2, cont, v4 share it. | Split: no, if pure move. Deleting cont because terminal day passed: **yes**, and not verified safe. |
| `forecast_quantile_ladder` + `app` FQ branch | **retain** | Sending family in the unit file. Fix the stale DRAFT comment (`trade.py:709-719`) only as a comment. | Comment fix: no. |
| `ladder_ev` | **retain** as library | FQ and NBP import it. Stage 2 parked. Do not merge `scoring.margin` into `forecast_margin`. | Merge: **yes** (drops `n_cell` or couples parity). |
| `weather_common` | **retain** | CRH uses halt, refusals, `RunningExtremeAccumulator`. FQ uses costs. Dead shells use the rest. | Deleting the package with the shells: **yes**. |
| `cli_settlement_print_lock`, `running_extreme_lock` | **remove candidate** | L-9 names both. Not in `app/`. Tests + `run_weather_strategy_backtests.py`. Keep `weather_common/running_extreme.py` (CRH). | Deletion: no live path. Suite change. |
| `forecast_mispricing`, `forecast_revision`, `calibration_mean_reversion`, `forecast_edge.py` | **remove candidate** | Not in `app/`. 09-20 closes the point-forecast programme; class-level mapping is **HYPOTHESIS** except `forecast_edge` tests-only. | Same. Do not “simplify” by merging decisions. |
| `resting_ladder.py`, `strike_ladder.py` | **remove candidate** | Tests-only. `resting_ladder` is the one module that already uses NT timer + portfolio the way the docs describe (`resting_ladder.py:8-30`, `:161-225`). | Suite only. |
| `harness_probe.py`, `depth10.py` | **retain** | Harness and live quote reads. | — |
| `settlement/` | **retain** | PREREG v2, grade predicate, family barrier. Do not dedupe grade predicate. | Any formula edit: **yes**, ruling required. |
| `analysis/` | **retain** | NBP S2, hypothesis ledger, replay census. Split `nbp_calibration.py` only if a later plan says so. | — |
| Shell-class dedup (rank 1) | **simplify only after** the dead families are removed or one module remains | Extracting a base class across dead + live code is speculative. Live CRH/FQ do not use this shell. | Extract that changes flatten/submit: **yes**. |
| Replace working-order or equity logic with Portfolio/Cache helpers | **do not** | §C differences. | **yes** |

## (G) Open questions

1. **PROGRESS vs disk.** PROGRESS:32 and :86 were not updated for FQ `d0=2026-10-02`, unit sending id `pm_us_crh_fq_v1`, or cont `terminal_climate_day`. Which file is the operator’s current intent was not ruled in the lines read.
2. **Cont still trading?** Barrier closes the **tally** after 2026-09-19. The strategy’s own stop was not read. Unit file does not send cont.
3. **FQ `external_order_claims`.** Set for CRH. Not shown on the FQ build path in the lines read.
4. **OMS type** for multi-rung NETTING vs HEDGING against this venue. Not checked in the adapter.
5. **`on_resume`** is unoverridden. Whether this node ever resumes a strategy was not checked.
6. **K1 ↔ `CalibrationMeanReversionStrategy`** and **fc_v1 ↔ mispricing/revision** are name-level only.
7. **Dead methods** inside `ContinuousRungHoldStrategy` were not listed one by one.
8. **NO-1 ruling path** was not opened; the requirement text used is PROGRESS:31.
9. **Codegraph** was down this pass, so call-graph “zero callers” is textual, not the index.
