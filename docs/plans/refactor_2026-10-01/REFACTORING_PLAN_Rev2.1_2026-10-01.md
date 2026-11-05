# Breezy Refactoring Plan, Rev 2.1 (plan only)

**Baseline.** HEAD `60290e9d` on the live branch `feat/data-capture-and-risk`, read through the worktree `emdash-refactor-y4qj4`. NautilusTrader is pinned at 1.231.0 and is not modified.

**Inputs.**
- Rev 1, built from eight read-only audits (S1a, S1b, S2, S3, S4a, S4b, S5a, S5b).
- Four peer reviews of Rev 1.
- The coordinator's 16 rulings (`briefs/P2_rev2_revision.md`).
- One measured gate run (`results/S6_measured_durations.md`).

**Tags.** CONFIRMED and HYPOTHESIS carry the audit meaning. MEASURED means observed in a run; PROJECTED means an estimate. **[V]** means the fact was re-checked against the source in this pass. **[R#]** cites a coordinator ruling.

**Operator controls.** The two operator-reserved controls appear by name only, never by value: the **maximum daily budget** and the **maximum per position**.

**Scope.** This is a plan. It makes no repository edits, runs no tests and touches no systemd unit.

---

## 1. Executive assessment

### 1.1 Headline

Breezy's complexity does **not** come from re-implementing NautilusTrader.

- Three audits checked the Nautilus boundary: S1a (adapters), S1b (runtime and app), S4a (ingest, persistence, domain). None found a subsystem that a native component could replace without changing behaviour.
- The independent Nautilus architecture review re-checked every row in §1.2 against the 1.231.0 sources. It confirmed the "replace with Nautilus: none" verdict and corrected four of the stated reasons.
- The strategy seam already uses the native surface: subscriptions, `order_factory`, `cancel_all_orders`, `close_all_positions`, `external_order_claims` and `Clock.set_timer` (S2 §C).

The complexity is **structural**:
- oversized modules and functions on the live path;
- five dead strategy families still imported by a production script;
- production-only logic living in `scripts/`;
- copy-pasted shells;
- a test suite with no fast tier, where 38.8% of wall time sits in two files and is incidental (MEASURED, S6).

### 1.2 Why there is almost nothing to substitute

Reviewer corrections applied: **[R12]**, Nautilus review (E) items 2, 3, 5, 6, 8.

| Breezy component | Native candidate | Why substitution fails | Evidence |
|---|---|---|---|
| `SqliteStateStore` | `Cache` + `CacheDatabase` | The kernel wires only Redis (`system/kernel.py:310-329`). `get` is memory-only (`cache.pyx:2853`). `PostgresCacheDatabase` and `CachePostgresAdapter` (`cache/adapter.py:58-66`) exist but the kernel never constructs them, and they are still network databases without read-through. No Postgres step is planned. | S1b B4; S4a §B; Nautilus review (A) row 1; pinned by `tests/contract/test_nautilus_cache_durability_contract.py` |
| `DailySpendLedger` (maximum daily budget, maximum per position) | `max_notional_per_order`, `Throttler` | The native cap is per order, `int`, has no day key, and is inert with no cached account (`risk/engine.pyx:684-689`). Margin accounts also return True (`:691-692`). | S1b B1; Nautilus review CONFIRM |
| `SubmitIntentLatch` | `max_order_submit_rate` | A rate limiter is not a mutex on one outstanding create. | S1b B2; CONFIRM |
| In-flight check off + AMBIGUOUS resolver | `_check_inflight_orders` | After retries, `_resolve_inflight_order` (`live/execution_engine.py:767-785`) turns SUBMITTED into `OrderRejected("UNKNOWN")`. That frees a second submit. The venue's lack of a client order id remains HYPOTHESIS, carried from S1b. | Nautilus review (A) |
| Fee model | PyO3 `ProbabilityPriceFeeModel` | Bases are `(object,)`, so it fails `Condition.type(..., FeeModel)` at `backtest/engine.pyx:651`. No dated θ, no refusal. The **live** hook is `ExecutionClient.calculate_commission` at `execution/client.pyx:165-194`; the base returns `None`, so reconciliation books zero unless overridden. | Nautilus review (E)3. Rev 1 cited `live/execution_client.py:343-440`; that cite is withdrawn |
| WebSocket reconnect supervisor | `WebSocketConfig.reconnect_*` | Headers are set only in the constructor (`pyi:5531-5544`). No setter exists. `post_reconnection` runs after connect. | CONFIRM; the Rust header-reuse question stays HYPOTHESIS |
| Breezy signer | `nautilus_pyo3.ed25519_signature` | The reviewer **executed** parity: a 32-byte seed gives identical base64 to PyNaCl. The primitive rejects the 64-byte expanded key that `signing.py:169-170` accepts. The signer stays in Breezy because of the GET/POST method cage, the 30 s skew window and the key shapes. | Nautilus review (A), (C)1 |
| `health.py` / alert ladder | `heartbeat_interval_secs` | The field is declared only; there is no reader. `Component.degrade` **is** used ([V] `exec/client.py:5950`; also `component_health_watch.py`), but it is a state transition, not an alert ladder. `MessageBus.subscribe(topic, handler)` is topic-based (`component.pyx:2678`). | Nautilus review (C)5; Rev 1's "degrade unused" withdrawn |
| `logging_bridge.py` | `LoggingConfig` | There is no CRITICAL level. The Cython `Logger` drops records before `init_logging` (`component.pyx:1450-1451`); that default path is the operative one. | CONFIRM |
| Catalog wrapper / feather reader | `ParquetDataCatalog` | An equal-range write prints and returns (`parquet.py:378-380`; also in convert, near `:2684`). No flock. `_read_feather_file` is `read_all()`. The ~48× memory factor is HYPOTHESIS (not re-measured). | CONFIRM |
| Actor timer bridge | `Actor.run_in_executor` | Returns a `TaskId`; the result is discarded. It also cannot run a coroutine on the loop that owns the store. | CONFIRM |
| `weather_common/inflight.py` | `orders_open` / `orders_inflight` | Neither covers INITIALIZED (`base.pyx:421-430`, `:444-449`). Taking their union double-counts PENDING_*. The `cache.pyx:5906` comment is stale. | Nautilus review (A) last row, (E)6 |

**Remaining native candidates.** None of these is an R-step; all sit in §3.4 BC-11.
- `ed25519_signature`: only the 32-byte form matches. Swapping would need a key-shape migration.
- `StreamingFeatherWriter` for observation streams: `include_types` takes Arrow types only, so the raw payload and the byte cap would be lost (HYPOTHESIS).
- The "public markets socket" premise is **struck**. [V] `websocket.py:1278-1280` records that the 2026-08-30 probe failed authentication: `/v1/ws/markets` requires auth.

### 1.3 Ranked structural complexity drivers

| Rank | Driver | Size | Evidence |
|---|---|---|---|
| 1 | Oversized live-path modules and functions | `exec/client.py` 5,957 (`_resolve_ambiguous_intents` 605, `_submit_order` 503); `continuous_strategy.py` 3,434 (`_hunt_tick` 570); `trade_supervisor.py` 2,893 + core 1,850; `quote_tape_ingest_cli.py` 2,441; `nws_actor.py` 2,422; `app/trade.py:run` 476. 112 functions over 50 lines in strategy/settlement/analysis/app, 56 in ingest/persistence. | S1a C; S1b C; S2 D; S4a D |
| 2 | Production logic in `scripts/` | 21 PROD + 32 PROD-LIB = 48,453 LOC. They are the only implementation of the PREREG kill-clock admission, the FQ calibration artefact chain, the `archive_table.py` generator and the `gs_boundary` JSON. 13 scripts import private `breezy` symbols. | S4b A, D |
| 3 | Five dead strategy families still imported in production | 5,637 LOC + 934 LOC in tests-only root modules. [V] `run_weather_strategy_backtests.py:244-266` imports all five at module scope. It is imported by `replay_sufficiency_census.py:94` **and by `current_rung_hold_paper_replay.py:69-77` (seven names) and `whole_tape_paper_replay.py:43-47`**. The paper replay is driven by `breezy-replay-daily`. `weather_strategy_backtest_lib.py:42` imports a dead shell inside a function. | S2 A; S4b A; maintainability review C; [V] |
| 4 | Copy-pasted shells | Strategy shell: ~200 identical lines × 2 extra copies. Actor timer bridge × 5, and the copies are **not** identical (the observation actor holds an inflight lock, fails closed via `_rebuild_trusted=False`, and `nws_actor` arms a second deadline timer; the fee probe has no `_settle`). [V, coordinator 2026-10-01: `_settle` runs on exactly one path per poll (`nws_observation_actor.py:226-267`); a Rev 1 reviewer claim of a double-settle was wrong and is struck]. Halt-latch preamble × 2. Atomic writers × 6. | S2 B; S4a C2; trading review B3; Nautilus review (D)1 |
| 5 | Duplicated helpers | `_ns_to_datetime` × 5 (dead shells only). [V] `gs_boundary` solver × 2, already drifted (`gs_boundary_artefact.py:405,491-492`). Fee θ·p·(1−p) × 4 (**not** foldable). | S2 B; S4b C |
| 6 | Test-suite weight with no fast tier | 300,560 LOC test; 14,954 collected items (MEASURED, test-eng review). Gate wall 25m03s, CPU 21m52s, peak 2.4 GB (MEASURED, S6). 583 s of 1,503 s sits in two files, and both costs are incidental. | S3 A; S6; test-eng review (A) |
| 7 | Unwired ingest code | NBS chain + archive writer + `archived_selection`: 1,091 LOC with no src or scripts caller. | S4a C3; maintainability C (CONFIRMED) |
| 8 | One-implementation protocols | `StateStore` × 4, 3 `Node` aliases, single-use adapter protocols. **Each one is deliberate:** they avoid Nautilus-importing package `__init__`s, or they are different surfaces. **Declined [R1][R2].** | maintainability review A; [V] `persistence/__init__.py:8` imports `catalog` |

### 1.4 Documentation and requirements drift (CONFIRMED unless tagged)

**Programme state**
- `PROGRESS.md:86` says "S9 pending"; HEAD *is* S9.
- `PROGRESS.md:32` names cont as the live-measurement family.

**Stale comments in src**
- [V] `app/trade.py:713-716` says the FQ branch is "unreachable", citing `DRAFT_NOT_REGISTERED`. The manifest is REGISTERED.
- [V] `exec/client.py:660` cites `risk.py:139`; the flag is at `:224`.
- `websocket.py:61-63` points at the wrong `retry.py` lines.
- `operator_controls.py:267` names a non-existent `RiskLimits` type.
- [V] `persistence/__init__.py:1-6` says "single submodule"; there are 22.
- `gaps.py:408-410` is stale.
- The `signing.py` and `write_transport.py:6` docstrings are stale.
- `cache.pyx:5906` is a stale Nautilus-side comment, noted only.

**Repository docs**
- The nws-cli-settlement skill line 176 still recommends pyIEM.
- `AGENT_ARCHITECTURE.md` says `~=1.231`.
- `STRATEGY_QUICKSTART.md:383` describes the layer order wrongly.
- `deploy/systemd/README.md:9-10` names the wrong drop-in.
- The L-36 anchor is stale.
- R8 §(viii) contradicts L-26.
- The ledger "in-memory BY DESIGN" wording is half-true, because `seed_spent` re-seeds the ledger at boot.

Sources: S2 G1; S5a B; S5b B.

**Withdrawn audit claim.** S1a said `test_polymarket_us_exec_snapshot_drift.py` was missing. [V] The file exists.

---

## 2. Requirement-to-subsystem responsibility map

Status values:
- **CLEAR**: one owner, unambiguous.
- **EXTENDS**: Breezy layered on a native API.
- **UNCLEAR**: owner, pin or placement is in doubt.

IDs come from S5a (S-, P-, D-) and S5b (OPS-, ENG-, V-).

| Requirement | Owning Breezy subsystem | Nautilus part | Pinning tests | Status |
|---|---|---|---|---|
| S-01/02/03/05, ENG-09/16: egress barriers N1–N3/N5, exact sets | `tests/conftest.py:82-380`; `scripts/ci/run_tests_no_egress.sh` | none (pyo3 `HttpClient` bypasses `socket`) | `test_execution_egress_firewall_guard.py` | CLEAR |
| S-04: credentialed-session refusal | `conftest.py:383-408` | — | `test_polymarket_us_credential_gate.py:59-181` (test-eng C; S5a "not located" was a search miss) | CLEAR |
| S-06, ENG-10: default deselection | `pyproject.toml:49` [V] | pytest | `test_probe_containment.py:585` | CLEAR |
| S-07: GET-only read signer, POST-only write signer | `signing.py`, `write_transport.py` | `HttpClient` exposes every verb | `test_polymarket_us_signing.py:266-275`, `_write_transport.py`, `test_cage_rule_constants_are_pinned.py` | CLEAR |
| S-08/09/11: maximum daily budget, maximum per position, ledger seed, permit | `adapters/polymarket_us/operator_controls.py:264-427`, `safety.py` | `RiskEngine` max-notional (defence in depth; inert without an account) | `test_operator_reserved_controls.py` (rewind `:292`, seed `:773-801`), `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_polymarket_us_permit_issuance.py`, `test_native_order_cap_wiring.py`, `test_risk_engine_ordering_enforcement.py` | EXTENDS. Placement is UNCLEAR (V-07) |
| S-10: reserved-control census | the census test | — | `test_operator_control_assignment_scan.py` | CLEAR |
| S-12/23: `OrderSubmissionPermit`; one permit per process; A-1 ceiling | `runtime/order_enablement.py`; core `:122-128` (env-var literal lazily imported by the node at `app/trade.py:145`) | — | `test_runtime_order_guard_permit_expiry.py`, `test_trade_supervisor.py:6244-6304` | CLEAR |
| S-13: `BacktestOrderGuard` | `runtime/backtest_order_guard.py` | cash SELL fails open | `test_runtime_backtest_order_guard.py`, `test_runtime_live_order_guard.py` | EXTENDS |
| S-14: `allow_short` never True | CRH, FQ, `ladder_ev` configs raise; `weather_common/risk.py:224` | `StrategyConfig` does not reject | `tests/strategy/*/test_config.py`, `test_weather_common_risk.py:874` | EXTENDS (non-uniform in dead shells) |
| S-15, P-05: qty≡1; R-10 | `current_rung_hold/config.py:263-266` | — | `test_current_rung_hold_config.py:70,75` | CLEAR |
| S-16/18/19: submit chokepoint, AMBIGUOUS, latch | `exec/client.py:_submit_order`, `submit_chain.py`, `runtime/submit_intent.py` | `generate_order_*`; throttler is a rate | `test_polymarket_us_submit_order_chain.py`, `test_submit_intent_latch.py`, `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_current_rung_hold_ambiguous_resolver.py` (white-box) | EXTENDS. No public-port test (CT-1) |
| S-17, OPS-01..10: supervisor | `runtime/trade_supervisor*.py` | none | 4 `test_trade_supervisor*.py` files | CLEAR |
| S-20: drift allowlists | `exec/reports.py:233-418` | report types | `test_polymarket_us_exec_reports.py`, `test_polymarket_us_exec_snapshot_drift.py` [V] | EXTENDS |
| S-21: per-family halt | `trial_day_latch.py`; literals duplicated in core (B-13) | — | `test_edge3_per_family_halt.py`, `test_set_family_halt_cli.py`, `test_trade_supervisor_cont_self_check.py`. **No FQ through-`run()` test** (trading review B2) | UNCLEAR (CT-12) |
| S-22: fee θ drift halt | `fees.py`, `fee_drift_probe.py` (venue HTTP in the strategy layer), `app/trade.py:_build_fee_drift_probe` (only `record_policy_halt` caller, `:462`) | Cython `FeeModel`; `calculate_commission` | `test_fee_drift_probe.py`, `test_app_trade_fee_drift_probe_wiring.py`, `test_polymarket_us_fee_*.py` | UNCLEAR (layer placement) |
| S-24: NO first-order containment | `exec/no_side_keys.py` | — | `test_no_side_keys.py` | CLEAR |
| Account-presence halt | `runtime/account_presence_halt.py` | `RiskEngine.set_trading_state` (`engine.pyx:228-257`) | `tests/contract/test_account_presence_halt_contract.py` | EXTENDS |
| P-01..04, P-09: PREREG statistic, LOSS_STOP, variance, tally | `settlement/current_rung_hold_v2.py`, `persistence/gs_boundary_artefact.py`, **scripts** `family_tally_v2.py`, `score_live_trials.py`, `structural_dead_stop.py` | — | look-loop golden; v2 verdict/score; `test_station_day_mixed_side_2026_09_14.py:421-466`; `test_gs_boundary_artefact.py` | UNCLEAR (split between src and scripts) |
| P-06: NO-side hunting | `continuous_strategy.py`, `ladder_ev/scoring.py:70` | — | NO-side tests | CLEAR |
| P-07: rest_v5 shadow | `resting_decider.py` | — | byte-identical orders test | CLEAR |
| P-08: frozen trigger (L-34) | snapshot dedupe key `continuous_strategy.py:1927-1942` | — | not found (gap, CT-7) | UNCLEAR |
| P-10: FQ activation, single sending family | `pm_us_crh_fq_v1.json`, `app/trade.py:709-745`, FQ package | — | `test_fq_s8_registration_artefacts.py`, `test_forecast_quantile_ladder_boot.py` | CLEAR (missing stop: out of scope) |
| P-11: exit seam unarmed | `persistence/exit_gate.py:55-66` | `Order.tags` | `test_persistence_exit_gate.py` | CLEAR |
| P-12: KILL horizon | none | — | none | UNCLEAR |
| P-13: PREREG only by ruling | sha pins, byte-frozen `archive_table.py` | — | `test_prereg_v1_is_byte_unmodified.py` | CLEAR |
| D-01/02/14: settlement-grade, corrections, CLI parse | `normalize/`, `settlement/settlement_truth.py` | — | `test_normalize_classify.py`, correction agreement, `cli_parse` tests | CLEAR |
| D-03..07: `revision_seq`, selection, `is_superseded`, product index | `nws_actor.py:1397-1465`, `domain/selection.py`, `catalog.py`, `product_index.py` | catalog in-place write, equal-range skip, filename = `ts_init` range | `test_domain_selection.py`, `test_ingest_product_index.py:126-629`, `test_catalog_write_interval_contract.py` | EXTENDS. D-05 conflict |
| D-08: LST climate day | `domain/climate_day.py` | — | `test_normalize_climate_day.py` | CLEAR |
| D-09/10: tape vs catalog; replay sufficiency | `persistence/feather_*`, `quote_tape_gaps.py`, `analysis/replay_sufficiency.py` | `StreamingConfig`, `convert_stream_to_data` | quote-tape contracts, `test_replay_sufficiency*.py` | EXTENDS |
| D-11/12: NO netting and echo | `exec/reports.py:1405-1452`, `leg_prices.py` | — | `test_polymarket_us_exec_positions.py`, `test_leg_prices_2026_09_14.py` | CLEAR |
| D-13: durable key grammar | `trial_day_latch.py`, `domain/instrument_leg.py` | `InstrumentId` str | real-writer fixtures | CLEAR |
| OPS-04/06: `KillMode=process` etc. | supervisor unit `:141-168` | — | none [V] | UNCLEAR (R0.A adds the pin) |
| OPS-05/20/21: memory caps | units + host drop-ins | — | `test_analysis_units_memory_capped.py` | UNCLEAR |
| OPS-09/15/16: restart window, `systemd-run`, hand relaunch | procedural | — | none | UNCLEAR |
| OPS-11: four-part liveness | supervisor core, partial | — | none | UNCLEAR |
| OPS-17/18/19: alerts | `runtime/health.py` (`AlertState` in-memory, loop-thread only), `check_alerts_cli.py`, notifier | `Component.degrade` used separately | `test_alert_egress.py`, `test_study_failure_alert.py` | CLEAR for timers; UNCLEAR for OPS-19 |
| OPS-22/23/24: catalog timers, ticks, protected window | units, `runtime/quote_tape_*` | `StreamingConfig` | `test_deploy_timer_hours.py`, `test_analysis_units_serialized.py` | EXTENDS. OPS-24 UNCLEAR |
| OPS-25/27/28: one sending family via unit env | unit + `settings.py` | — | `test_trade_supervisor_phase1_unit.py` | CLEAR |
| ENG-01/02/03: layers, exactly 4 `ignore_imports`, `.com` ban | `pyproject.toml:73-212` [V] | — | `test_test_safety_tooling_config.py:68-92` (set equality) | CLEAR |
| ENG-06/07: mypy ratchet | `test_mypy_ratchet.py:283-323` (CLEAN packages; [V] ceilings `scripts/analysis: 364`, `src/breezy/analysis: 13`) | — | itself | CLEAR |
| ENG-13/14/20: gate procedure; tests rewrite `catalog.py` in place | procedural; `test_archive_import_contract.py:46-56` | — | — | UNCLEAR |
| V-01..V-11: Polymarket.us coupling outside `adapters` | `strategy/current_rung_hold`, `runtime`, `app` | — | — | UNCLEAR. Kalshi parked; "do not deepen" |

### 2.1 Ownership ambiguities this plan must not resolve by accident

1. **Venue-neutral money controls live in the adapter (V-07).** L-22 pins a single construction site. Retain the location.
2. **Halt literals are duplicated across strategy and runtime (B-13)** and pinned byte for byte. Runtime cannot import strategy. Leave as is.
3. **PREREG admission is split between src and scripts.** R2.2 gives it a src owner without changing semantics.
4. **The fee-drift probe does venue HTTP from the strategy layer (V-02).** Retain. It is also the **only automated live halt** for FQ, so it is excluded from every refactor step [R3][R16].
5. **The `StateStore` protocol stays duplicated four times on purpose.** A single home would execute a Nautilus-importing package `__init__` on the order-gate import path [R1].

### 2.2 Conflicts: blockers vs separately tracked findings

| # | Conflict | Classification |
|---|---|---|
| C1 | Stale PROGRESS rows | **BLOCKER (before).** Fixed in R0.2. |
| C2 | PREREG v3 §7 scopes the maximum per position per station-day; code applies it per order | Separately tracked, needs a ruling. No step touches `authorize_order_cost`. |
| C3 | `is_superseded` is vacuous for live records | Separately tracked settlement finding. CT-9 is **detached** from R3.6 [R7] and kept only as a documenting test (optional, not gating). |
| C4 | `KillMode=process` and related directives are unpinned | **BLOCKER (before)** for any supervisor step. Fixed in R0.A. |
| C5 | Host TEMPORARY memory drop-ins | Separately tracked (ops). No step edits those units. |
| C6 | Unversioned hand-launch script mirrors `spawn_node()` | **DURING constraint.** CT-8 byte-pins `spawn_node` env/argv. Ops ownership is tracked separately. |
| C7 | Failed units (`replay-daily`, `fee-evidence-pull`, parity) | **BLOCKER (before)** for R2.x on their scripts: baseline first. |
| C8 | Gate tests rewrite `src`; units execute from the primary tree | **Standing constraint.** Never gate in `/home/jon/breezy`. A merge is a deploy (§3.0). |
| C9 | Ledger described as in-memory, but re-seeded; AMBIGUOUS spend is lost on restart | Doc fix in R0.2. The behaviour gap is separately tracked and is **not** fixed inside CT-1. |
| C10 | Stale θ on the kill-clock path. See the full restatement after this table. | **Separately tracked, HIGH, reportable.** Changing it is a ruling [R6]. |
| C11 | PREREG α wording | Separately tracked. |
| C12 | FQ claims and OMS | **Resolved (CONFIRMED by trading review C-4).** FQ sets no `external_order_claims` (`forecast_quantile_ladder/composition.py:233-241`); OMS is NETTING (`exec/client.py:1670`). FQ fills reconcile under EXTERNAL at the next boot. R3.1 must preserve this absence [R9]. |
| C13 | NYC excluded from CRH | Separately tracked. |

**C10, restated per trading review C-2 [R6].**
- `family_tally_v2` computes cost from real fill fees (`cost = t.fill_px + t.fee`, `:566`). It imports only `ASK_BANDS` and `classify_ask_band` from the study module (`:85`).
- The stale `FEE_THETA = 0.06` (`mb_current_rung_edge_study.py:195`) feeds `break_even`. That reaches `live_family_tally.py`, `structural_dead_stop.py`, `k1_*` and `band_decider_stage0b_screen.py`.
- A separate literal, `DRIFT_FEE_THETA = 0.06`, sits at `crh_group_sequential_boundaries.py:109`.
- Stale src defaults `current_rung_hold/config.py:233` (`Decimal("0.06")`), `ladder_ev/config.py:154` and `composition.py:476` are **do-not-touch**.
- FQ defaults to 0.0695 (`forecast_quantile_ladder/config.py:73`).

**OUT OF SCOPE, reportable [HIGH; R16; VERIFIED by the trading review].**
- `pm_us_crh_fq_v1` has **no registered statistical stop**. Its boundary artefact is `{"applicable": false}`, a sentinel that refuses any tally.
- LOSS_STOP and the group-sequential machinery are offline tally verdicts only.
- The sole `record_policy_halt` caller is the fee-drift DISAGREE path (`app/trade.py:462`). L-38 applies.
- Stops that do exist: the two caps at the exec chokepoint with qty 1; the 10 h permit TTL plus the A-1 ceiling; the fee-drift halt; the manual halt tool; OPEN/AMBIGUOUS deny; the `allow_short` floor.
- Severity is HIGH and accepted by the 2026-10-01 ruling (FQ plan R3).
- This plan proposes no stop rule. The missing stop **raises the stakes of R3.1**, because the per-family halt veto and the fee-drift halt are the only automated containment.

---

## 3. Prioritized refactoring plan

### 3.0 Live-path safety net and hold rule [R8][R9]

**A merge is a deploy.** Production units execute from `/home/jon/breezy` on the same branch.
- Node code goes live at the next 16:50Z spawn.
- Timer code goes live at its next tick.
- Long-running services (nws-ingest, quote-tape) pick code up at their next restart.
- **Lazy imports run inside already-running processes:** `app/trade.py:144-145,998`, `node_config.py:119,534,689,878,907`, `ingest/nws_actor.py:2218`, `ingest/routing.py:814`. A moved symbol with no re-export breaks a running process on first call, and on a timer thread that failure is silently discarded (L-16).
- **Rule:** every move keeps a re-export at the old path until the next spawn has proven out.

**Merge procedure (all R-steps).**
1. Run the pre-merge full gate on the **rebased tip** (agent worktrees start stale).
2. Merge fast-forward only. The post-merge gate on the integration tree is confirmatory (L-43).
3. Never land two refactor merges inside one gate cycle. Read `GATE_EXIT` before any push.
4. **Node-loaded steps:** before spawn, run a boot smoke on the integration tree. It drives the real FQ manifest through `app.trade.run` with a scratch store and catalog and `RecordingNode` (the pattern in `test_forecast_quantile_ladder_boot.py`). Also run `python -c "import breezy.runtime.trade_supervisor, breezy.app.trade"` from the production interpreter.
5. **Any `trade_supervisor*` change** (core is also node-imported, `app/trade.py:145`): a supervisor restart with an observed heartbeat by **14:00Z the same day**. `KillMode=process` keeps the node running.
6. **Timer-fed steps** (scripts/analysis, quote-tape ingest): merge by **10:00Z**, then run each affected consumer once against the frozen baseline before its first tick.
7. Rollback is `git revert` (fast-forward), the full gate, and the same smoke. No R-step changes an on-disk state format.

**Hold rule [R9].**
- **R3.1, R3.2 and R3.4 (and the conditional R1.2)** do not start until both of these are recorded:
  1. the FQ live proof (FQ_GO_LIVE_PLAN §5, items 1–12);
  2. one full trading day with reconciled fills and no AMBIGUOUS intent or halt.
- Phase 0, Phase 1 (R1.4, R1.5, R1.6) and Phase 2 may proceed now.
- R3.3 and R3.6 are not node-loaded. They are not held, but they are sequenced after Phase 2.

**Global acceptance for every step.**
- Full gate green: `scripts/ci/run_tests_no_egress.sh`, `PYTHONPATH=<wt>/src`, the primary-tree interpreter, no `uv`/`pip` (L-51).
- `lint-imports` green.
- mypy ratchet: ceiling counts change **in the same commit** as the code that moves them, with before/after in the message. A count that falls below its ceiling also fails (ENG-07). CLEAN packages cannot be relaxed.

### 3.1 Dispositions per subsystem

| Subsystem | Disposition | Requirement | Verified extension point | Integration constraint / behaviour risk | Boundary |
|---|---|---|---|---|---|
| Signers + GET/POST cages | **Retain** | S-07 | `HttpClient` verbs (`pyi:5416-5452`) | Merging cages collapses B2 | Breezy |
| WebSocket + pool | **Retain** | market data | `WebSocketClient.connect(post_reconnection=)` (`pyi:5547-5558`) | Socket requires auth (struck premise) | Breezy |
| Data client, provider, parsing, symbology | **Retain** | instruments | `LiveMarketDataClient` (`live/data_client.py:320`), `load_all_async` (`providers.py:76`) | — | Breezy |
| Exec client + reports + `submit_chain` | **Retain**; R3.5 deferred | S-16..20 | five `generate_*` (`live/execution_client.py:343,371,394,417,440`); `calculate_commission` (`execution/client.pyx:165-194`) | N2/E0 exact sets; callee strings are `self.`-shaped | Breezy owns pre-POST policy |
| Fee model | **Retain** | S-22 | `FeeModel.get_commission` (`fee.pyx:33-64`); backtest gate `engine.pyx:651` | Deleting the override books zero | Breezy |
| Permit, ledger, latch | **Retain** | S-08..12, S-19 | `LiveRiskEngineConfig` as defence in depth | Money semantics | Breezy |
| `SqliteStateStore` + 4 protocols | **Retain** (R1.1 declined) | durable state | none (Redis only) | BC-2 only | Breezy |
| `app/trade.py` composition root | **Simplify** (R3.1, held) | P-10 | `TradingNodeConfig`, `Trader.add_actor` | CT-12 first; FQ has no claims; NETTING | Breezy maps; Nautilus runs |
| Supervisor | **Simplify** (R3.2, held, two merges) | S-17, OPS | none | Restart by 14:00Z; four fork tests kept | Breezy |
| Guards and halts | **Retain** | S-13, account halt | `set_trading_state` | — | Breezy |
| Quote-tape ingest CLI | **Simplify** (R3.3; sibling move) | D-09/10 | `convert_stream_to_data` (`parquet.py:2604`) | Must not touch `ts_init`, the filename interval, the deadline clock, or "repair" the equal-range skip [R11] | Nautilus converts |
| Health, alerts, logging bridge | **Retain**; types move (R1.5) | OPS-17 | `MessageBus.subscribe(topic, handler)` | `AlertState.evaluate` stays on the loop thread | Breezy |
| Domain `Data` types | **Retain** (boilerplate generator deferred) | D-01..07 | `register_arrow`, keyed on the class object (`serializer.py:89-128`) | A second registration overwrites `_SCHEMAS`; renaming changes the catalog directory | Nautilus hook, Breezy fields |
| Catalog wrapper | **Retain; split** the probe (R1.4) | D-04 | `write_data/query` stay | `monkeypatch` targets; ENG-20 rewrite | Breezy invariants |
| Ingest actor bridge | **Conditional** (Appendix A, R1.2) | L-16 | `Clock.set_timer` | Copies differ | Breezy |
| `persistence/quote_tape_gaps.py` | **Move to `breezy.runtime`** (R1.6) | D-09 | catalog query | Imports Nautilus; no src importer below persistence | Breezy |
| NBS chain, archive writer | **Remove/park** (BC-4) | none | — | full pin list | — |
| `features/` | **Remove** (BC-5) | none | — | layers equality | — |
| CRH | **Retain; split by move** (R3.4, held) | P-01..08 | `Strategy` lifecycle | L-34; subscribe-marker class names | Breezy |
| FQ, `ladder_ev`, `weather_common`, `settlement`, `analysis` | **Retain** | P-10, D-01, P-01 | — | No fee, walk or margin folds (BC-9) | Breezy |
| Dead shells + tests-only strategies | **Remove** (BC-3), hard prerequisite R2.3 | none | — | Contract-test host; nightly import | — |
| `scripts/` PROD + PROD-LIB | **Consolidate** (R2.2, R2.3) | P-01..09 | — | Ruling citations; ratchet; timer cutoff | src logic, thin CLIs |
| `scripts/` STUDY | **Retain frozen** | evidence | — | `live_family_tally.py` unedited (RULING_R5:30) | — |

**Declined steps** (recorded with reason):
- **R1.1** (`StateStore` consolidation) [R1]. Both candidate homes run Nautilus-importing package `__init__`s ([V] `persistence/__init__.py:8` → `catalog`; `domain/__init__.py:16-53`). The exhaustive layer list forbids a new top-level package. Gain about 30 LOC.
- **R1.3** (`Node` protocols) [R2]. The three protocols are different surfaces (`cli.py:90-97`, `quote_tape_cli.py:123-132`, `trade_cli.py:253-289`), and `runtime` is a mypy CLEAN package.
- **R2.4** (public aliases) [R4]. R0.6 suffices. Limit of R0.6: it does not catch module-scope import of dead strategies.

### 3.2 Sequenced steps

#### Phase 0: safety net, speedups, drift (no src behaviour)

**R0.2: Docs and non-live comment drift**
- Requirement and evidence: C1, C9; §1.4.
- Change:
  - `PROGRESS.md:32,86` and the `operator_controls` cites, under the 250-line hook (ENG-12);
  - the nws-cli-settlement skill, `AGENT_ARCHITECTURE.md`, `STRATEGY_QUICKSTART.md:383`, `deploy/systemd/README.md:9-10`, the L-36 anchor, the ledger wording, the R8 §(viii) note pointing to L-26;
  - the comment in `ingest/gaps.py:408-410` (loaded only by nws-ingest, which picks it up at restart).
- Do not name reserved controls in prose (L-39).
- Acceptance: PROGRESS size hook; `test_probe_containment.py:550` (src never reads `docs/evidence`); full gate.
- Effort S, risk L. Not live.

**R0.1: Live-file comment fixes, folded [R7]**
- Comments in `app/trade.py:709-719` ride R3.1.
- `persistence/__init__.py:1-6` rides R1.4.
- `exec/client.py:660` rides R3.5 if it is ever done.
- `websocket.py:61-63`, `operator_controls.py:267`, `signing.py` and `write_transport.py:6` have **no planned edit**. They stay queued, attached to the next real edit of each file, and are recorded in PROGRESS as a comment backlog.
- No stand-alone live gate for comments.

**R0.A: One test/config commit (R0.3 + R0.4 + R0.6 + R0.7 + tier infra) [R7][R14]**
- Requirement and evidence: S3 B, F; OPS-04/06 (C4); S4b risk 6; test-eng (B), (F)6, (F)9.
- Change, as one commit and one gate:
  1. Add `pytestmark = pytest.mark.contract` to the 10 unmarked `tests/contract` modules (list in Rev 1 R0.3; confirmed by test-eng).
  2. A unit test that parses `deploy/systemd/breezy-trade-supervisor.service` and asserts `KillMode=process`, `RestartPreventExitStatus=2`, `TimeoutStopSec=120`, `Restart=always`, and no `MemoryHigh`/`MemoryMax`. Shown red on a mutated copy.
  3. The R0.6 tripwire: an AST scan of `scripts/**` for `from breezy… import _x`, asserting each private symbol still resolves.
  4. Register the `heavy` marker in `pyproject.toml` `markers` only. `addopts` is untouched (pinned at `test_probe_containment.py:585`); the markers list is pinned by membership only ([V] `test_test_safety_tooling_config.py:44-46`).
  5. A new `scripts/ci/run_tier.sh T1|T2|T3`. It holds `EXCL='not live and not venue_live and not real_money'` as **one** constant, delegates to `run_tests_no_egress.sh`, and adds no `-q`. A unit test asserts the script contains all three exclusions.
  6. A **heavy-allowlist meta-test**: `heavy` may appear only in files on an explicit allowlist. These may never be listed: the readonly guard, egress firewall, credential gate, cage rule, permit issuance, operator-control census, fee guard, probe containment, native-read-spies, strategy-module gate, and `test_mypy_ratchet.py`.
  7. A **tier-partition meta-check**: `--collect-only` counts satisfy |T1| + |contract| + |heavy ∖ (contract ∪ integration)| + |integration ∖ contract| + |live-class| = total collected (terms disjoint by construction). The nested collect-only subprocesses cost about 15–20 s inside T1 (PROJECTED), within the ≤10 min budget. 14,954 today (MEASURED).
- Dependencies: none. Before adding any `pyproject` row, grep for count pins (L-54).
- Benefit: complete `-m contract` selection (277 → ~326 PROJECTED); KillMode pinned; scripts' private-import breakage caught by the gate; tier infrastructure that cannot silently shrink coverage.
- Rollback: one revert.
- Effort M, risk L. Not live.

**R0.8: Test speedups with no pin loss [R7]**
- Requirement and evidence: test-eng (A), (F)1; S6 MEASURED.
- Change:
  - **(a)** In the four `test_current_rung_hold_exit_window_study.py` `main(...)` tests (test-eng cites lines 1219, 1252, 2170, 2192), inject `sleep=sleeps.append` and assert `sleeps == [5.0, 15.0, 45.0]`. This keeps the retry schedule pinned. Sibling tests already use the seam.
  - **(b)** In `test_aud07_m1c_census.py`, a module-scoped fixture runs `run_census_chunk(0, 49, …)` + `run_stress_chunk` **once through the real writer** (L-42). The three `refuses_*` tests copy the JSONL and derive their cases (truncate to 48; drop the stress row; 48 + one extra cell with sha "b"). Keep the genuine second pass in the chunk-vs-all-in-one test. Do **not** stub `run_census_cell`.
- Benefit: PROJECTED −255 s and −200 s, so the full gate goes from 1,503 s to about 1,040 s (**~17.3 min**) with no tiering.
- Acceptance: both files green; mutation-red check (change the retry schedule → (a) red; remove the coverage check → (b) red); full gate wall recorded.
- Effort S–M, risk L. Not live.

**R0.5: Characterization tests (pruned) [R7]**

Every CT names its entry point, goes through the real writer, and is shown red on one local mutation before commit.

| CT | Pins | Entry point | Red mutation | Gates |
|---|---|---|---|---|
| CT-1 | AMBIGUOUS through the public port. One submit gets a with-id empty-executions body. A second public submit is **refused**, the POST count stays 1, the intent stays OPEN, and the retirement reason literal is unchanged. The C9 spend loss is not "fixed". | the exec client's command path as driven by `test_fq_caps_and_ambiguous_2026_10_01.py`, never `_submit_order` directly | skip the latch arm | §4.3 sites 1–2; R3.5 |
| CT-2 | Adopt-not-double-spawn with a **real `subprocess.Popen` child** (not a double) | `trade_supervisor` boot shell | spawn regardless of the flock holder | R3.2 |
| CT-4 | `nws_actor` `ts_init` nudge to `existing_max+1` (`:1423-1437`) | the persist path with a real catalog | remove the `+1` | R3.6 |
| CT-7 | Continuous-strategy snapshot dedupe key `(ts_event, ask, size)` (`:1927-1942`) | strategy driven by `TestClock` quotes | drop `size` from the key | R3.4 |
| CT-8 | Supervisor contract surface: boot-retry 8 / 15 min constants; log-marker strings parsed as API (`core.py:91-190`); the permit-ceiling env-var literal (`core.py:128`, consumed at `app/trade.py:145`) and its injection into the child env; subscribe-marker class names (`core.py:161-166`); `spawn_node` env/argv **byte-pin**; an FQ halt clearing path (set → self-check FAIL → clear → PASS, L-48) | core + `spawn_node` | rename one marker | R3.1, R3.2, R3.4 |
| CT-12 | FQ manifest through the **real `app.trade.run`**. The halt row is written by the real writer (`record_policy_halt` / set-family-halt path). Halted twin: `submit_veto` refuses. Unhalted twin: permits. The manifest fee coefficient reaches the config. | `app.trade.run` + `RecordingNode` | mutated key prefix in the halt preamble | **R3.1 hard prerequisite** |
| CT-13 | A supervisor crash between spawn and state persist re-adopts and does not re-spawn | `_do_midday_watch` / boot-retry shells with failure injection | persist before spawn | R3.2 |

Dropped as already covered [R7] (citations from the test-eng review (C)):
- CT-3: `test_operator_reserved_controls.py:292,773-801`; `test_current_rung_hold_order_submission_wiring.py:379`.
- CT-5: `test_ingest_product_index.py:126,236-323,629`.
- CT-6: `test_station_day_mixed_side_2026_09_14.py:421-466`.
- CT-10: `test_polymarket_us_credential_gate.py:59-181`.
- CT-11: `test_current_rung_hold_config.py:70,75`.

CT-9 is a separately tracked settlement finding (C3), optional, and not gating.

Effort M–L, risk L. Not live.

**R0.9: Apply `heavy` marks**
- Requirement and evidence: §4.6 MEASURED.
- Change: mark only the files in §4.6 classified `heavy` **after** R0.8, and add them to the allowlist in the same commit.
- Acceptance: the partition meta-check holds; T1 passes under 3 fixed randomly seeds (logged).
- Effort S, risk L.

#### Phase 1: low-risk moves (may proceed now)

**R1.4: Split the filesystem probe out of `persistence/catalog.py`**
- Requirement and evidence: S4a D.
- Change: move `:961-1202` to `persistence/filesystem_probe.py`. Re-export from `catalog.py`, because `persistence/__init__.py:8-29` imports those names (e.g. `NETWORK_FILESYSTEM_TYPES`) from `catalog`. Carries the R0.1 docstring fix for `persistence/__init__.py`.
- Prerequisites:
  - Read `test_archive_import_contract.py:15,46-56`; its plant path onto `catalog.py` must stay valid (ENG-20).
  - Grep `monkeypatch.setattr("breezy.persistence.catalog._…")`. A re-export does **not** redirect an internal lookup [R11]. Retarget any such test to the new module in the same commit.
  - `write_data` and `query` stay in place.
- Benefit: `catalog.py` goes from 1,202 to about 961 lines (not under 800 [R15]).
- Acceptance: `test_persistence_catalog.py`, `test_persistence_partitioning.py`, `test_catalog_nws_records.py`, full gate.
- Effort S, risk L–M. Long-running ingest picks it up at restart.

**R1.5: Pay off `ingest.nws_actor -> runtime.health`**
- Requirement and evidence: ENG-01; S4a D.
- Change: move `GapSummary`, `HealthSnapshot`, `AlertPayload`, `AlertCondition(Key)` and `AlertState` below `ingest`. Re-export from `runtime.health`, which keeps class identity. Replace `nws_actor`'s TYPE_CHECKING + `_health()` indirection with a direct import.
  - **Same commit:** delete the `pyproject.toml:105` row **and** the matching string in the set at `test_test_safety_tooling_config.py:87-92`.
  - `AlertState` is **not persisted** (in-memory, one loop thread) [R11]. Add a pin that `AlertState.evaluate` runs on the loop thread.
- Destination: a leaf below `ingest`. **A `persistence` home inherits the Nautilus-importing `__init__`** (same objection as R1.1). Choose a layer whose package init is import-light (`registry` or `settlement`; CONFIRMED thin by the trading review B1), or keep the types where they are and drop the step if no layer-legal home is light.
- Benefit: debt rows 4 → 3.
- Rollback: one revert.
- Effort S–M, risk L–M. Not node-loaded.

**R1.6: Pay off `persistence.quote_tape_gaps -> adapters...tape_records` [R11]**
- Requirement and evidence: ENG-01; maintainability (A).
- Change: move `persistence/quote_tape_gaps.py` to **`breezy/runtime/quote_tape_gaps.py`**. The module imports Nautilus directly (`:15-19`), so `analysis` is illegal; `runtime > adapters` is legal and sits beside the quote-tape ingest owner. Its only callers are `scripts/analysis/structural_dead_stop.py` and tests (codegraph, maintainability (A)).
  - Update those imports in the same commit.
  - Remove `pyproject.toml:107` and the matching test-set string.
  - Leave no shim in `persistence`; a shim would keep the edge.
  - Do not move the `QuoteTapeGap` `Data` class (catalog directory is `__name__`; registry keyed on the class).
- Live status: timer-fed (`structural_dead_stop` runs in score-live-trials at 14:15Z), so the 10:00Z cutoff applies plus one consumer run.
- Benefit: debt rows 3 → 2.
- Effort S, risk M. Both packages are mypy CLEAN, so no ceiling change.

#### Phase 2: production logic out of `scripts/` (may proceed now; timer-fed LIVE)

**Before Phase 2:** C7 is acknowledged. Capture baselines.

"Byte-identical nightly output" is **redefined** [R15]: the **stripped semantic payload** produced on frozen inputs with a frozen `--as-of`, ignoring dated marker names, writer metadata and appended row order. The replay appends dated JSONL rows; the scorer writes `score_live_trials_ok_<date>` markers.

**R2.1: Boundary-solver parity pin**
- Requirement and evidence: P-01; [V] `gs_boundary_artefact.py:405,491-492`.
- Change: a test loads both implementations and asserts equal outputs on the registered parameters. It also asserts `BRENTQ_XTOL == 1e-10` or documents the difference. The ruling-cited script is not edited.
- Effort S, risk L. Source of truth is an open question (§5d).

**R2.3: Extract the tape-instrument seam into a new `scripts/analysis` module [R5]. HARD prerequisite for BC-3.**
- Requirement and evidence: D-10; [V] `run_weather_strategy_backtests.py:244-266,353,1325-1428`; `replay_sufficiency_census.py:94`; maintainability C.
- Target: a `scripts/analysis` module (e.g. `scripts/analysis/tape_instruments.py`). `breezy.analysis` is illegal because `TapeInstrument` carries Nautilus types (`:534-538`) and the analysis contract forbids direct Nautilus imports (`pyproject.toml:165-177`).
- Change: move **every** name imported by:
  - `current_rung_hold_paper_replay.py:69-77` (seven names);
  - `whole_tape_paper_replay.py:43-47` (`DEFAULT_WEATHER_CATALOG_ROOT`, `WEATHER_VENUE`, `TapeInstrument`);
  - `replay_sufficiency_census.py:94`.

  Repoint those three consumers. `run_weather_strategy_backtests.py` re-imports the moved names, so its path and ruling citations stay valid. Address `weather_strategy_backtest_lib.py:42` (function-scope import of `cli_settlement_print_lock`): move the calling function's dependency behind the BC-3 decision, or document it as the last remaining coupling.
- **Plain statement:** until paper replay no longer imports `run_weather_strategy_backtests.py`, BC-3 still breaks `breezy-replay-daily`.
- Acceptance:
  - `test_census_column_scan.py`, `test_replay_sufficiency_census.py`, the paper-replay tests;
  - an import-graph test asserting none of the three consumers transitively imports any of the five shell packages;
  - stripped-payload equality on the frozen baseline;
  - mypy `scripts/analysis` ceiling updated in the same commit;
  - 10:00Z cutoff.
- Effort M, risk M.

**R2.2: Move the PREREG fill-admission core into `breezy.analysis` [R6]**
- Requirement and evidence: P-01..09; S4b D(3); trading C-3; maintainability D.
- Change: move `_admit_fill`, `_admit_one_fill`, `compute_residual` (`:376,950,468`), `read_filled_trials_state_db` (`:557`) and `fill_time_count.py` (sqlite-only, HYPOTHESIS → verify at step time) into a `breezy.analysis` module.
  - **Must NOT move** the `catalog.instruments()` walk ([V] `score_live_trials.py:1213`), which is Nautilus-typed.
  - The original functions stay as **re-exporting shims at their current line positions**, so ruling citations keep resolving by symbol. Line positions cannot be literally preserved (moving `_admit_fill` and `read_filled_trials_state_db`, `score_live_trials.py:557-950`, shifts every later line; rulings cite e.g. `:611,675,689,707,861,1079,1788`), so a **citation map old → new is MANDATORY in the same commit**, plus a test that every symbol named in the map still resolves (trading-reliability confirmation N1).
  - mypy ceilings `scripts/analysis: 364` and `src/breezy/analysis: 13` ([V] `test_mypy_ratchet.py:314-315`) change **in the same commit**.
  - θ literals stay byte-for-byte (C10).
- New test: the reader still opens SQLite with `mode=ro` and cannot write ([V] `fill_time_count.py:94`).
- Timer-fed LIVE: consumers fire at 14:15Z (score-live-trials), 14:30Z (live-tally) and 17:20Z (family-tally@). Merge by **10:00Z**; run each consumer once against the frozen baseline before 14:15Z.
- Acceptance: look-loop golden; `test_family_tally_v2_*.py`; `test_structural_dead_stop*.py`; stripped-payload equality; `lint-imports` (the live path still never imports `breezy.analysis`).
- Rollback: one revert (ratchet change is inside the commit).
- Effort L, risk M. The trading-reliability reviewer reviews the step.

#### Phase 3: decomposition (R3.3/R3.6 after Phase 2; R3.1/R3.2/R3.4 under the hold rule)

**R3.3: Move the long `quote_tape_ingest_cli.py` functions to a sibling module**
- Requirement and evidence: S1b B8; Nautilus review (B), (E).
- Change: move `_convert_one_tick_type_per_file` (177), `_ingest_instance_per_file` (162), `run_ingest` (154) and `run` (142) to a sibling module, with re-exports. **Must not touch** `ts_init`, the filename interval, the monotonic-vs-wall clocks, or "repair" the equal-range skip [R11].
- Benefit: about 2,441 → ~1,806 lines [R15].
- Acceptance: `test_quote_tape_ingest_native_pin.py`, `test_catalog_write_interval_contract.py`, `test_quote_tape_*`, `test_quote_tape_ingest_bounded_rss.py`.
- Timer-fed (every 15 min): 10:00Z cutoff.
- Effort M, risk M.

**R3.6: `nws_actor.py` health extraction**
- Requirement and evidence: S4a F.
- Change: move `_alert_conditions` (188) and `_emit_health` (129) to an ingest sibling module. `AlertState.evaluate` stays on the loop thread. The **`ts_init` nudge does not move** [R11].
- Dependencies: R1.5; CT-4 (not CT-9 [R7]).
- Acceptance: `test_ingest_nws_actor*.py`, `test_ingest_crash_between_mark_and_persist.py`, `test_runtime_restart_resume.py`.
- Effort M, risk M. nws-ingest picks it up at restart.

**R3.1: Extract the halt-latch preamble and per-kind builders in `app/trade.py:run` (HELD)**
- Requirement and evidence: P-10; S2 B3; trading A, B2.
- Change: one shared halt-latch preamble helper, parameterized by key prefix and latch type, replacing `:607-688` and `:730-744`. Builders per `composition_kind`. Carries the R0.1 comment fix (`:709-719`).
- Must be preserved:
  - **no `external_order_claims` for FQ**, OMS NETTING (C12);
  - the manifest `required_fee_coefficient` propagation (no fall-through to the stale CRH 0.06 default);
  - byte-stable boot lines, permit line and exit codes.
- Dependencies: the hold rule; **CT-12 merged and shown red**; CT-8.
- Benefit: −40 to −80 duplicate LOC. The file stays about 1,020–1,060 lines; this is not a file split [R15].
- Acceptance:
  - `test_node_composition_contract.py`, `test_trade_node_lifecycle_contract.py`, `test_forecast_quantile_ladder_boot.py`, CT-12, `test_fq_caps_and_ambiguous_2026_10_01.py`;
  - the boot smoke (§3.0);
  - **SL-13p2 parity re-run** on the same one-day window (`docs/evidence/SL13P2_parity_pm_us_crh_fq_v1_2026-10-01.json`, 0 mismatches / 720,597) with identical decision keys.
- Effort M, risk H. **LIVE (sending-family boot).**

**R3.2: Supervisor decisions into core, in two merges (HELD)**
- Requirement and evidence: S1b E; trading A, B6-B10.
- **R3.2a:** core pure functions only, with the I/O shells untouched. Core is node-imported (`app/trade.py:145`), so it needs the boot smoke plus a supervisor restart and an observed heartbeat by 14:00Z.
- **R3.2b:** after one daily cycle, thin the shells (`_do_self_check` 228, `_do_midday_watch` 215, `_run_forever` 194), then restart again.
- Preserved: halt literals (B-13); `spawn_node` env/argv (CT-8); markers; `PASS_ADOPTED_LOG_UNKNOWN`; spawn-then-persist ordering (CT-13).
- **All four `os.fork()` tests stay** until R3.2b plus one daily cycle.
- Dependencies: R0.A (KillMode pin), CT-2, CT-8, CT-13; hold rule.
- Acceptance: the four supervisor test files; smoke; restart evidence.
- Effort L, risk H. **LIVE.**

**R3.4: Split `continuous_strategy.py` by moving code only (HELD)**
- Requirement and evidence: S2 D; trading A.
- Change: move pure helpers and the NO-side shadow evaluator to sibling modules. No reordering inside `_hunt_tick` (L-34). **No class renames.** Subscribe-marker class names are pinned in CT-8.
- The module is imported at module scope by `app/trade.py` for every boot, including FQ.
- Dependencies: CT-7, CT-8; hold rule.
- Acceptance: `test_current_rung_hold_study_replay_equivalence.py`, continuous tests, CRH SFO 09-01 replay identity (CRH only), boot smoke.
- Effort L, risk H. **LIVE (import path).**

**R3.5: Resolver extraction from `exec/client.py` (DEFERRED) [R10]**

If ever done:
- as a **mixin**, so the `self.`-shaped callee strings on `EXEC_RESOLVER_PERMITTED_CALLEES` stay valid;
- same-commit edits to the N2 equality list (`test_execution_egress_firewall_guard.py:738-772`) and `EXEC_ASYNC_LIFECYCLE_MODULES` (`:1788`);
- **there is no X3 file allowlist**; X3 is a vocabulary scan, and adding an exemption would relax L-12;
- a positive control that the resolver-by-name scan covers the new module;
- CT-1 first;
- security-reviewer sign-off.

**Recommended order:** R0.2 → R0.A → R0.8 → R0.5 (CT-1, CT-12 first) → R0.9 → R1.4 → R1.5 → R1.6 → R2.1 → R2.3 → R2.2 → R3.3 → R3.6 → [hold lifts] → R3.1 → R3.2a → R3.2b → R3.4. R3.5 stays deferred.

Every step is independently mergeable. Phase 0 alone delivers the safety net and the measured speedups.

#### Appendix A: R1.2 actor timer bridge (CONDITIONAL; not in the sequence) [R3]

Proceed only when **all** of these hold:
- **(a)** the FQ live proof is recorded;
- **(b)** per-actor characterization of current `inflight` and death semantics is merged, including the observation actor's inflight lock and the `_rebuild_trusted=False` fail-closed behaviour (the earlier "double-settle / negative inflight" claim is struck: `_settle` runs exactly once per poll, `nws_observation_actor.py:226-267` [V]);
- **(c)** the Nautilus constraints are met:
  - the timer callback only submits;
  - death handling goes through `call_soon_threadsafe`;
  - the observation actor's `_rebuild_trusted=False`, inflight lock, `nws_actor`'s second deadline timer and the CRITICAL strings are behaviour-identical;
  - an assertion that the callback mutates no store;
- **(d)** `fee_drift_probe` is excluded.

Acceptance is the real-actor test (`test_the_real_nbm_actor_feeds_the_composed_quantile_actor`) plus the SL-13p2 parity re-run. `test_live_timer_thread_affinity.py` pins Nautilus behaviour only and is not acceptance.

**If BC-4 removes `nbm_forecast_actor`, R1.2 is dropped outright**, because the remaining pair is the non-identical one.

### 3.3 Effect actually produced

| Step | Effect |
|---|---|
| R1.4 | relocates ~241 LOC |
| R1.5 / R1.6 | relocate small modules; debt rows 4 → 2 |
| R2.2 / R2.3 | relocate ~1,000–1,500 LOC from scripts to src or a new scripts module; shims add a few lines |
| R3.1 | removes ~40–80 duplicate LOC |
| R3.3 | relocates ~635 LOC |
| R3.6 | relocates ~317 LOC |

**Duplicate LOC removed by the committed sequence: ~40–80.** Every other committed step relocates code. Rev 1's 250–300 figure is withdrawn after the R1.1, R1.2 and R1.3 drops [R15].

Reductions come only from approvals: BC-3 (6,571 src LOC + dependent tests) and BC-4 (~1,091). The measured win is test time (§4.4).

### 3.4 Proposed behaviour changes requiring approval (never inside an R-step)

| ID | Change | Pins and conditions |
|---|---|---|
| BC-1 | Uniform atomic writer (mkstemp + file + dir fsync) | `nbp_derived_store.py:296,355` (fixed `.tmp`, no fsync) and `scored_trial_store` get slower and safer. Trading peer. |
| BC-2 | KV + manifest → scan-capable SQLite tables | On-disk live gate state; dual-read migration; last. |
| BC-3 | Remove the 5 dead shells + `forecast_edge`, `resting_ladder`, `strike_ladder` and their tests; then prune `weather_common` modules left with zero importers | **R2.3 is the hard prerequisite.** `strike_ladder` hosts contract `test_multi_instrument_weather_strategy.py`, which needs a host decision (§5d). Tag the pre-removal commit for citation reproducibility. Confirm the 09-20 mapping for three families. No tally math touched. |
| BC-4 | Remove or park the NBS chain + `archive_records.py` + `archived_selection.py` [R13] | Same commit: forbidden row `pyproject.toml:145` + `test_archive_import_contract.py:74`; `IEM_HOST_ALLOWED_MODULES` (`:84-86`); tests `test_nbm_forecast_actor.py`, `test_nbm_forecast_parse.py`, `test_iem_mos_fallback_transport.py`, `test_ingest_archive_records.py`, `test_domain_archived_selection.py`; the string in `test_nbp_shadow_parity_contract.py:51`. Drops Appendix A. |
| BC-5 | Remove empty `features/` [R13] | Layers equality (`test_test_safety_tooling_config.py:68-86`), forbidden `source_modules` (`pyproject.toml:158-161`, test `:124-136`), the layer row at `:96`. |
| BC-6 | Archive retired STUDY scripts [R13] | **`live_family_tally.py` may not be moved or edited** (RULING_R5:30). Remaining candidates: `k1_kalshi_prior.py`, `aud07_m1c_*`, plan-only probes. Delete candidates: `iem_asos1min_backfill.py`, 109 untracked `.pyc`. |
| BC-7 | Remove the `ts_init` nudge | Ruling (replay semantics). |
| BC-8 | Native in-flight / open / position checks; Redis or Postgres cache | Not recommended. |
| BC-9 | Fold fee functions, book walks or margins | Not recommended. |
| BC-10 | Script θ → dated schedule (C10) | Ruling. |
| BC-11 | `ed25519_signature` swap (needs key-shape migration); `StreamingFeatherWriter` for observations | Evidence first. The public-socket premise is struck. |
| BC-12 | Mark superseded records, or drop the vacuous leg | Ruling. |
| BC-13 | Fork tests → a **real `subprocess.Popen` zombie** shared by one module fixture; raise the `_wait_for_zombie` deadline above 1.0 s (e.g. 5 s) [R13] | Only after R3.2b + one daily cycle. Real `/proc` semantics kept; Rev 1's "process double" withdrawn. |

---

## 4. Testing strategy and measurable success criteria

### 4.1 Tiers by application-owned risk [R14]

Every tier runs through `scripts/ci/run_tests_no_egress.sh`, wrapped by `run_tier.sh` (R0.A). An unsandboxed `pytest` aborts at N2.

**The `-m` trap (MEASURED by the test-eng review).** A CLI `-m` **replaces** the `addopts` `-m`. `-m "not contract"` selected 14,677 = 14,672 + the 5 live-class items. Every tier therefore uses `EXCL` from the one script constant, pinned by a test. `addopts` is never edited.

| Tier | Owns which risk | Command (`$G` = egress wrapper; `EXCL` from `run_tier.sh`) | When |
|---|---|---|---|
| T1 fast | Custom decision logic plus **all guard and safety scans** (they never carry `heavy`) | `$G -m "$EXCL and not contract and not heavy" tests/unit tests/strategy` | Every worktree commit |
| T2 contract | Nautilus-boundary pins + the 7 unit-file contract tests | `$G -m "contract and $EXCL"` (no path) | Steps touching adapter/runtime/ingest/persistence boundaries; first on any Nautilus bump |
| T3 e2e | Composed behaviour | `$G -m "$EXCL" tests/integration tests/unit/test_forecast_quantile_ladder_boot.py` + the CT-12 file. Engine contract hosts run in T2, not repeated here. | Every LIVE step |
| T4 full | Everything, including `heavy` and `test_mypy_ratchet.py` | `$G` (no args, default `addopts`) | Before every merge; after every merge on the integration tree (L-43) |
| Static | Layering, types | `lint-imports`; mypy ratchet (inside T4); ruff (CI only) | Every step |

**Execution constraints.**
- **CI runs T4 only.** Tiers are a local developer loop and never replace the post-merge full gate. Bubblewrap on `ubuntu-latest` is HYPOTHESIS (AppArmor).
- `pytest-xdist` is not installed (MEASURED), and L-51 forbids installers. Sharding means N concurrent `$G` processes on **disjoint** path lists, with **`test_archive_import_contract.py` in a serial lane** because it rewrites `catalog.py` (ENG-20).
- **Randomization:** pytest-randomly is active. Validate T1 under 3 fixed `-p randomly --randomly-seed=N` runs, and always log the seed (it is hidden under `-q`; do not add a second `-q`).
- The partition meta-check and heavy allowlist from R0.A run in T1.

**T3 composition.** `test_ingest_crash_between_mark_and_persist.py`, `test_runtime_restart_resume.py`, `test_runtime_lifecycle_smoke.py`, the FQ boot test and CT-12. `test_forecast_edge_backtest.py` and `test_resting_ladder_backtest.py` leave with BC-3.

### 4.2 Pins to keep, retain as-is

| Group | Pins |
|---|---|
| Egress | N1/N2/N3 and the conftest abort |
| Signing | B2 non-GET raise |
| Guard | `BacktestOrderGuard` refusal table |
| Short selling | `allow_short=True` construction refusal |
| Caps | Native cap wiring; risk-engine ordering |
| Settlement | PRELIMINARY/FINAL classify; H0 closed form; `test_prereg_v1_is_byte_unmodified.py` |
| Nautilus boundary | Catalog, cache, expiry, streaming, settlement-price and timer-affinity contracts |
| Drift | `SchemaDriftError`; drift allowlists |
| Ratchet | `test_mypy_ratchet.py` (T4 and static tier, never `heavy`) |
| Strict xfails | `test_reconciliation_settlement_price_hazard.py:535`, `test_runtime_live_order_guard.py:321,346`, multi_position `:162`. Moving files between tiers must not hide them. |

### 4.3 Implementation-detail assertion sites: per-site verdicts [R14]

**Rule.** A replacement lands green and is shown **mutation-red** before the private assertion is removed in the same commit. Every site on a safety, NO-SEND or trading-refusal path needs a two-sided replacement.

| Site (S3 C #) | Location | Verdict |
|---|---|---|
| 1, 2 | `test_current_rung_hold_ambiguous_resolver.py:296,300` (`_drive_to_ambiguous` harness precondition) | **KEEP** until CT-1 asserts a refused second submit + POST count 1. Then keep the helper precondition; it makes ~118 downstream tests non-vacuous. |
| 3 | `test_continuous_rung_hold_fill_wiring.py:579` | **Proceed.** The public `record.ask` is already asserted. Keep one bounded-growth assertion or record its loss explicitly. |
| 4 | same file `:2277` (`_recorded_fee_for`) | **Proceed** only with an end-to-end `Decimal("0.01")` assertion through the real durable writer, shown red under a mutated division. |
| 5 | `test_polymarket_us_exec_client.py:1081` | **Two-sided:** a later order is refused while the refusal is set and accepted after it clears. |
| 6, 7 | `test_polymarket_us_startup_evidence.py:480-481` | **Proceed.** The replacement is stronger. |
| 8 | `test_continuous_rung_hold_strategy.py:476` (`_DIAG_FEE_UNVERIFIED`) | **KEEP.** It is the operator no-trade diagnosis and the S-22 guard. |
| 9 | `test_current_rung_hold_composition.py:282` | **KEEP** `orders_enabled is False`. Replace only the `stations` part. |
| 10 | same file `:800` | Replace only with a submit-through-strategy exit observation; otherwise keep. |
| 11 | same file `:1367` (log text) | Replace after CT-8 pins the marker string. |
| 12 | `test_app_trade_fee_drift_probe_wiring.py:142` | **KEEP** (the 09-17 θ incident pin; zero cost). |
| 13 | `test_archive_cache.py:151` | **Dropped from the list:** `_fetch_calls` is a test-double attribute, misclassified by S3. |
| 14 | `test_polymarket_us_submit_order_chain.py:1933` | **Proceed** in its own commit with a reviewer note (no consumer of `branch=exact` in src/scripts/deploy). |
| 15 | `tests/strategy/forecast_quantile_ladder/test_sl13c_d_plus_1_resolution.py:257` | **KEEP** (SL-13c D+1 pin on the sending family) until a mutation-red negative test exists (no subscription to today's ids). |

**Fork tests** (`test_trade_supervisor.py:2554,2735,2748,2762`) stay until BC-13 is approved.

**Fixtures** [R14]:
- Move `store_path` only (18 one-line copies) into `tests/unit/conftest.py`.
- **Do not consolidate `tally_mod`.** The 10 copies load different scripts and overwrite `sys.modules`.
- `interior_instrument`: low value, left as is.
- `_operator_order_ceiling`: left as is (L-39).

**Large-file splits** (`test_trade_supervisor.py`, the ambiguous-resolver file) happen only after the tier infrastructure exists and CT-1/CT-2 land, as moves, and never inside a LIVE-step commit.

### 4.4 Baselines (MEASURED) and targets (PROJECTED)

| Metric | MEASURED baseline | PROJECTED target |
|---|---|---|
| Full gate wall / CPU / peak | 25m03s / 21m52s / 2.4 GB, `GATE_EXIT=0` (S6). Earlier operator runs 22.7–25.4 min. | **~17.3 min after R0.8** (1,503 → ~1,040 s). R0.5 and R0.A add a small amount (unmeasured). |
| Top-80 duration share | 1,062 s of ~1,503 s (S6) | — |
| Two incidental files | 583 s = 38.8% of wall (test-eng (A)) | ~128 s after R0.8 |
| T1 serial | none exists | **≤ 10 min serial** (PROJECTED ~520–540 s); **≤ 3 min sharded** (3–4 disjoint shards + serial lane). The Rev 1 "≤ 5 min" is withdrawn. |
| Collected / default-selected | 14,954 / 14,949 (5 deselected) (MEASURED, test-eng) | Partition check equals the collected total, always |
| `-m contract` | 277 = 270 contract + 7 unit | ~326 after R0.A (PROJECTED) |
| `tests/contract` | 37 test modules / 319 items (39 tracked files incl. `__init__`, `conftest`) | 0 unmarked modules |
| Outcomes (green logs) | ~14.7–14.9k passed; 11–12 skipped; 7 xfailed; 3 xpassed (S3 D) | Strict-xfail count unchanged. The 3 XPASS are the known non-strict report-only studies (`test_no_side_ldobf_validation_2026_09_14.py:673,714`); document and leave. Skips include the archive-regeneration tests, which skip without the on-disk corpus (not a CI pin). |
| Private-attribute assert **sites** under review | 15 sites in S3 (one misclassified) | Up to 8 sites changed, each individually justified (§4.3). The 741-line count is not a target. |
| `os.fork()` tests | 4 | 4 until BC-13; then 0 forks, 3 `Popen` zombies + positive control |
| `ignore_imports` debt rows | 4 [V] | 3 (R1.5), 2 (R1.6) |
| Module sizes | `catalog.py` 1,202; `app/trade.py` 1,099; `quote_tape_ingest_cli.py` 2,441 | ~961; ~1,020–1,060; ~1,806. **No "under 800" claims** [R15]. |
| Scripts' private imports | 13 scripts | Tripwired (R0.A); R2.4 declined |

### 4.5 Gate procedure for the refactor

1. **Where and how.** One gate per tree; never in `/home/jon/breezy`. `BREEZY_PYTHON` = primary interpreter; `PYTHONPATH=<wt>/src`. Under `systemd-run`, pass `-p LimitNOFILE=524288` and keep basetemp on `~/.cache`.
2. **Merge and deploy.** §3.0 procedure: rebased-tip pre-merge gate, fast-forward only, one merge per gate cycle, smoke, cutoffs.
3. **Ratchet.** Count changes go in the same commit as the code move. Rebase on CF-12 W2 (`4b0b4f6`) if it merges first.
4. **Tiers per step.** LIVE: T1 → T2 → T3 → T4 → smoke. Timer-fed: T1 → T4 → consumer run. Others: T1 → T4.

### 4.6 Slow tail (MEASURED, S6; classification from the test-eng review (A))

| # | Test | s | Kind | Cost | Tier after R0.8 |
|---|---|---|---|---|---|
| 1 | `test_aud07_m1c_census.py::test_chunked_census_plus_derive_pin_equals_the_all_in_one_result` | 120.0 | pure-Python MC, two 49-cell passes | duplicated | heavy (keeps the genuine second pass) |
| 2–5 | `test_current_rung_hold_exit_window_study.py`: 4 `main(...)` tests | 4 × 65.0 | real 5 + 15 + 45 s back-off | **incidental** | fast (R0.8a) |
| 6–8 | `test_aud07_m1c_census.py::test_derive_pin_refuses_{missing_cells, missing_stress_row, mixed_code_shas}` | 64.1 / 62.5 / 59.3 | repeated 49-cell pass | **incidental** | fast or heavy after R0.8b (decide on re-measure) |
| 9 | `test_nbp_calibration.py::test_skew_normal_cdf_…` | 40.5 | scipy fit | intrinsic | heavy |
| 10–12 | `test_aud07_live_rule_crossing_sim.py` × 3 | 28.2 / 27.6 / 26.3 | MC | intrinsic | heavy |
| 13–14 | archive-table regeneration × 2 | 24.1 / 23.5 | real corpus; skips if absent | intrinsic, environment-dependent | heavy |
| 15 | `test_mypy_ratchet.py` (setup) | 21.1 | mypy subprocess | ratchet **pin** | T4 + static only; never `heavy`-parked out of T4 |
| 16 | `test_nbp_skill_study.py::test_default_stage_…` | 15.9 | full validate stage | intrinsic (HYPOTHESIS) | heavy |
| 17 | `test_quote_tape_ingest_bounded_rss.py` | 15.9 + 12.1 | child-process RSS (`memory`) | intrinsic | heavy (keeps `memory`) |
| 18–19 | `test_trade_node_lifecycle_contract.py`, `test_boot_halt_alert_contract.py` | 10.0 each | real `TradingNode` | intrinsic | contract (T2) + heavy |
| 20–21 | `test_gs_boundary_artefact.py`, `test_crh_group_sequential_boundaries.py` | 9.5 / 9.3 | numeric solver reference | intrinsic, PREREG pin | heavy |
| — | readonly guard 22.4, egress firewall 22.2, credential gate 13.1, operator scan 10.0, permit issuance 8.0, cage rule 3.9 | — | repo-wide AST or subprocess scans | **safety pins** | **T1, never heavy** (allowlist meta-test). A session-scoped `(path, mtime_ns, size)` parse cache could save ~40–50 s (HYPOTHESIS; optional). |
| — | `replay_daily_wrapper` 5.04 × 2, `instrument_cache_alert` 5.02 / 5.00, `operator_control_assignment_scan` 5.03 | — | likely real waits | ~25 s incidental (HYPOTHESIS) | open before marking; inject clocks where the wait is real |

---

## 5. Peer review: findings, revisions, unresolved blockers

### 5(a) Findings per reviewer

| Reviewer role | Model / agent | Verdict | Blockers | Majors | Minors |
|---|---|---|---|---|---|
| NautilusTrader architecture | Grok (independent model) | APPROVE-WITH-CHANGES | 0 | 4 | 4 |
| Maintainability / sequencing | Grok (independent model) | APPROVE-WITH-CHANGES | 5 | 5 | 1 |
| Trading reliability | Claude `trading-bot-architect` agent | APPROVE-WITH-CHANGES | 2 | 6 | 7 |
| Test engineering | Claude `pr-test-analyzer` agent | APPROVE-WITH-CHANGES | 0 | 6 | 5 |

### 5(b) Revisions applied (keyed to reviewer items)

**Nautilus architecture (E):**
- 1 → R1.2 moved to Appendix A with the constraints.
- 2 → §1.2 signing row; BC-11 narrowed.
- 3 → fee cite corrected to `execution/client.pyx:165-194` / `engine.pyx:651`.
- 4 → R1.5 (`AlertState` not persisted; `evaluate` on the loop thread) and R3.6 (nudge stays; CT-4, not CT-9).
- 5 → cache row (Postgres exists, unwired, no step).
- 6 → orders row (`orders_inflight`; `cache.pyx:5906` stale).
- 7 → public-socket premise struck ([V] `websocket.py:1278-1280`).
- 8 → `Component.degrade` used ([V] `exec/client.py:5950`).

**Maintainability (F):**
- 1 → R1.3 dropped.
- 2 → R1.1 dropped.
- 3 → R2.3 targets `scripts/analysis` and moves every imported name; it is the hard prerequisite.
- 4 → R2.2 keeps the catalog walk out of `breezy.analysis`; ratchet counts change in the same commit.
- 5 → BC-6 leaves `live_family_tally.py` untouched.
- 6 → R1.2 conditional; R2.4 dropped.
- 7 → R0.A merged commit; R0.5 split; CT-9 detached.
- 8 → R3.5 conditions.
- 9 → BC-4 and BC-5 pin lists.
- 10 → §4.4 deltas; byte-identity redefined.
- 11 → R0.1 folded; R1.6 destination named (`runtime`); R2.1 stays a pin.

**Trading reliability (E):**
- 1 → CT-12 is the R3.1 prerequisite.
- 2 → §3.0 safety net (smoke, import check, restart by 14:00Z).
- 3 → R1.1 dropped.
- 4 → Appendix A excludes `fee_drift_probe` and requires per-actor characterization.
- 5 → hold rule.
- 6 → CT-13; fork tests kept; R3.2 split into two merges; spawn byte-pin.
- 7 → R2.2 shims plus a mandatory citation map and symbol-resolution test; `mode=ro` test; 10:00Z cutoff and consumer run; C10 restated.
- 8 → rebased-tip, fast-forward-only, one merge per cycle.
- 9 → R3.5 mixin.
- 10 → CT-8 marker class names.
- 11 → R0.1 no stand-alone commit; L-54 grep; L-39.
- 12 → R2.4 dropped. R1.3 was dropped under the maintainability blocker instead of being bundled.
- 13 → CT order: CT-1 and CT-12 first.
- 14 → SL-13p2 parity re-run.
- 15 → C10 text and do-not-touch defaults.
- C-4 → C12 resolved.
- (D) → HIGH out-of-scope finding verified.

**Test engineering (F):**
- 1 → R0.8.
- 2 → §4.6 filled; T1 targets restated.
- 3 → §4.3 per-site verdicts.
- 4 → BC-13 uses a real `Popen` zombie.
- 5 → `tally_mod` not consolidated.
- 6 → partition meta-check, heavy allowlist, 3-seed validation.
- 7 → CTs pruned and specified.
- 8 → XPASS, contract counts and skip notes in §4.4.
- 9 → the `EXCL` constant plus its test; T3 redefined.
- 10 → CI scope.
- 11 → 5.0x s tests listed for inspection.

### 5(c) Reviewer disagreements and how they were resolved

| Disagreement | Positions | Resolution [ruling] |
|---|---|---|
| **R1.2 timer bridge** | Nautilus: keep with constraints. Maintainability: drop. Trading: major changes, exclude the fee probe. | **Conditional appendix**, gated on FQ proof, per-actor characterization, Nautilus constraints and fee-probe exclusion. Dropped outright if BC-4 removes `nbm_forecast_actor` [R3]. |
| **§4.3 sites 8, 12, 15** | S3 / Rev 1: replace. Test-eng: keep (operator diagnosis; 09-17 incident pin; SL-13c D+1 pin on the live family). | **Keep** all three. Site 15 is replaceable only after a mutation-red negative exists [R14]. |
| **BC-13 fork tests** | Rev 1: process double. Test-eng: real `Popen` zombie. Trading: keep forks through R3.2 plus one cycle. | **Real `Popen` zombie, only after R3.2b plus one daily cycle**; deadline raised [R13][R9]. |
| **R1.3 Node protocols** | Trading: OK as an off-node batch. Maintainability: blocker (the protocols differ; runtime is CLEAN). | **Dropped** [R2]. |
| **R0.1 comment edits** | Trading: own commit. Maintainability: fold into real edits. | **Fold** into the first commit that already edits each live file; non-live comments go with R0.2 [R7]. |
| **CT-2 mechanism** | Rev 1: process double. | **Real `Popen` child** [R7]. |

### 5(d) Unresolved blockers and open questions (need a ruling or an operator-level decision outside this plan)

1. **FQ has no registered statistical stop.** HIGH, accepted by the 2026-10-01 ruling (FQ plan R3), verified by the trading review, L-38 applies. Out of scope; reported. It raises the stakes of R3.1.
2. **PREREG v3 §7 cap scope** (per station-day vs per order) for the maximum per position: ruling (C2).
3. **`is_superseded` vacuity** for live records: settlement ruling (C3, BC-12).
4. **Stale θ = 0.06 on the kill-clock path** (`FEE_THETA`, `DRIFT_FEE_THETA`; C10): ruling. It also bounds R2.2, which must keep the literals byte-for-byte.
5. **Host TEMPORARY memory drop-ins** past their removal condition: ops decision (C5).
6. **Unversioned hand-launch script** in a scratchpad, with no A-1 ceiling: ops ownership (C6). CT-8 protects the contract it mirrors.
7. **Hold-lift date:** FQ d0 is 2026-10-02. The earliest lift is after the FQ live proof is recorded **and** one full trading day with reconciled fills and no AMBIGUOUS/halt. PROJECTED no earlier than 2026-10-03; to be recorded by the coordinator.
8. **R2.1 source of truth** for the boundary solver (script vs src): a P-13 ruling if src is to own it.
9. **BC-3 contract-test host:** `test_multi_instrument_weather_strategy.py` runs on `strike_ladder`. Re-host on `harness_probe.py`, or retire the test explicitly.
10. **BC-4: is the NBS chain parked or dead?** Owner decision. It also decides whether Appendix A survives.

Further question for peers (not a blocker): R1.5 is dropped unless a layer-legal, import-light home below `ingest` is shown by an import-graph test.

### 5(e) Independence statement

Two reviews (Nautilus architecture, maintainability) ran on an independent model (Grok). Two reviews (trading reliability, test engineering) ran on Claude specialist agents. Those agents are distinct from the plan author but belong to the same model family, so their independence is partial. None of the four is a human review. The plan author re-checked the new claims this revision relies on against the source ([V] tags). Reviewer measurements that were not re-run here are cited as reported:
- the collect-only counts;
- the `ed25519` parity run;
- the S6 durations, which the coordinator ran.
### 5(f) Confirmation pass on Rev 2 (2026-10-01) and the Rev 2.1 corrections

| Reviewer role | Verdict on Rev 2 | Items addressed | Residual |
|---|---|---|---|
| NautilusTrader architecture (Grok) | APPROVE-WITH-CHANGES | 8 / 8 | New: the "observation actor settles twice / inflight goes negative" claim was false. **Applied in Rev 2.1** (§1.3 rank 4, Appendix A(b)); coordinator verified `nws_observation_actor.py:226-267`: `_settle` runs exactly once per poll. |
| Maintainability / sequencing (Grok) | APPROVE-WITH-CHANGES | 10 / 11 (item 6 PARTIAL: R1.2 kept as a conditional appendix by coordinator ruling R3, see §5(c)) | New: line-stable shims are impossible for R2.2; the citation map must be the committed path. **Applied in Rev 2.1** (R2.2). Partition-sum double count. **Applied** (R0.A item 7, disjoint buckets). |
| Trading reliability (Claude agent) | APPROVE-WITH-CHANGES | 15 / 15 | N1: same citation-map point. **Applied.** N2/N3: R1.5 destinations (`registry`, `settlement`) and R1.6 destination (`runtime`) verified import-light / layer-legal. Note: this reviewer read lines 1–579 of Rev 2 only. |
| Test engineering (Claude agent) | APPROVE | 10 / 11 (item 11 PARTIAL: the five ~5 s waits remain a §4.6 follow-up, no R-step owns them) | Minor notes applied: disjoint partition formula; meta-check cost ~15–20 s PROJECTED; census tests stay `heavy` until re-measured after R0.8(b). |

No material objection remains open against the plan text. The ten items in §5(d) are outside the plan's authority (rulings, ops, owner decisions) and stay listed as unresolved blockers for those steps that depend on them.

**Document provenance.** Audits (S1a, S1b, S2, S3, S4a, S4b, S5a, S5b, S6) and the four Rev 1 reviews plus the four confirmation passes are archived beside this plan under `docs/plans/refactor_2026-10-01/evidence/` and `.../reviews/`. Codegraph was unavailable to the Grok audits (read-only sandbox) and was used by the Claude agents and the plan author.
