# Breezy Refactoring Plan, Rev 1 (plan only)

HEAD `60290e9d`, worktree `emdash-refactor-y4qj4`. This is a worktree of the live branch `feat/data-capture-and-risk`. NautilusTrader is pinned at 1.231.0 and is immutable.

**Inputs.** Eight read-only audits: S1a, S1b, S2, S3, S4a, S4b, S5a, S5b, all under `.../scratchpad/results/`.

**Verification this pass.** All eight audits reported codegraph unavailable. It worked for this pass. I used it, plus Read and Grep on Markdown, config and scripts, to re-check the facts the plan leans on. Facts re-checked this pass carry the tag **[V]**.

**Tags.**
- **CONFIRMED** and **HYPOTHESIS** carry the audit's meaning.
- **[V]** means I re-checked the fact against the source in this pass.

**Operator controls.** The two operator-reserved controls are named only, never valued: the **maximum daily budget** and the **maximum per position**.

---

## 1. Executive assessment

### 1.1 Headline

Breezy's complexity does **not** come from re-implementing NautilusTrader.

- The three Nautilus-boundary audits (S1a adapters, S1b runtime/app, S4a ingest/persistence/domain) found **zero subsystems that can be replaced by a native component while keeping their semantics**.
- The strategy audit (S2 §C) found that the strategy seam already uses the native surface: subscriptions, `order_factory`, `cancel_all_orders`, `close_all_positions`, `external_order_claims` and `Clock.set_timer`.

Breezy's complexity is **structural**:
- oversized modules and functions on the live path;
- five dead strategy families that are still wired into a production script;
- `scripts/` holding production-only logic;
- copy-pasted Actor and Strategy shells;
- one-implementation protocols and duplicated helpers;
- a 300k-LOC test suite with no fast tier.

On top of that sits a layer of **documentation and requirements drift**.

### 1.2 Why there is almost nothing to substitute (CONFIRMED unless tagged)

Each candidate below was examined, and native substitution would change behaviour, money semantics or recovery guarantees.

| Breezy component | Native candidate | Why substitution fails | Evidence |
|---|---|---|---|
| `SqliteStateStore` (`runtime/sqlite_store.py`) | `Cache` + `CacheDatabase` | Durable only with Redis. The kernel accepts only `database.type=="redis"`, and `get` is memory-only. Adopting it adds a service and an egress path the N2 firewall does not model. | S1b B4; S4a §B (`kernel.py:310-329`, `cache.pyx:1704-1708,2853`); pinned by `tests/contract/test_nautilus_cache_durability_contract.py` |
| `DailySpendLedger` (maximum daily budget, maximum per position) | `RiskEngineConfig.max_notional_per_order`, `Throttler` | Native is a per-order, whole-dollar `int` with no day key. It is inert while no `AccountState` is cached (`engine.pyx:684-689` returns `True`). | S1b B1 |
| `SubmitIntentLatch` | `max_order_submit_rate` | A rate limit is not a single-outstanding-create mutex. | S1b B2 |
| In-flight check off + AMBIGUOUS resolver | `_check_inflight_orders` | Polymarket.us has no client order id. A native "FAILED" verdict opens a path to a doubled position. | S1b B3 |
| `PolymarketUSFeeModel` | PyO3 `ProbabilityPriceFeeModel` | Right formula, wrong type: it fails `Condition.type(..., FeeModel)` at `engine.pyx:651`. Also lacks the dated θ schedule and the refusal. | S1a B5 |
| WebSocket reconnect supervisor | `WebSocketConfig.reconnect_*` | Headers are constructor-only, so a signed timestamp goes stale across a native retry. | S1a B2 (Rust behaviour is HYPOTHESIS) |
| PyNaCl signing | `nautilus_pyo3.ed25519_signature` | Byte equivalence was never executed (HYPOTHESIS). A mismatch is a full auth outage. | S1a B4 |
| `health.py` / alert ladder | `MessageBusConfig.heartbeat_interval_secs` | The field has no Python consumer, and the trade node runs `message_bus=None`. | S1b B5 |
| `logging_bridge.py` | `LoggingConfig` | No CRITICAL level, and records before `init_logging` are dropped. | S1b B6 |
| Catalog wrapper / feather reader | `ParquetDataCatalog`, `_read_feather_file` | Native silently skips on an equal range, has no flock or read-back, and `read_all()` uses about 48x the memory. | S4a §B, C1 |
| Actor timer bridge | `Actor.run_in_executor` | Returns a `TaskId`; the result is unreachable. | S4a C1 |
| `cache.orders_open` | `weather_common/inflight.py` | Native misses INITIALIZED and SUBMITTED orders. | S2 §C |

Three items remain native candidates, and **none is a refactor step**. Each needs evidence first and is listed in §3.4:
- WebSocket native reconnect, and only if `/v1/ws/markets` proves to be public. This is an unresolved probe (S1a F).
- `ed25519_signature` byte parity (S1a F, HYPOTHESIS).
- `StreamingFeatherWriter` for non-settlement observation streams (S4a finding 10, HYPOTHESIS; it loses the raw payload and the byte cap).

### 1.3 Ranked structural complexity drivers

| Rank | Driver | Size | Evidence |
|---|---|---|---|
| 1 | **Oversized live-path modules and functions** | `exec/client.py` 5,957 lines / 85 methods (`_resolve_ambiguous_intents` 605, `_submit_order` 503, `__init__` 261). `continuous_strategy.py` 3,434 (`_hunt_tick` 570, `_evaluate_no_side_shadow` 327). `trade_supervisor.py` 2,893 + `trade_supervisor_core.py` 1,850. `quote_tape_ingest_cli.py` 2,441. `nws_actor.py` 2,422. `app/trade.py:run` 476. 112 functions over 50 lines in strategy/settlement/analysis/app, and 56 in ingest/persistence. | S1a C; S1b C; S2 D; S4a D (all CONFIRMED, AST spans) |
| 2 | **`scripts/` holds production-only logic** | 21 PROD + 32 PROD-LIB files = 48,453 LOC run by 19 timers. These scripts are the only implementation of: the PREREG kill-clock (`score_live_trials.py` admission and residual, `family_tally_v2.py`, `structural_dead_stop.py`); the FQ calibration artefact chain; the `archive_table.py` generator; and the `gs_boundary` JSON. 13 scripts import underscore-private `breezy` symbols. | S4b A, D (CONFIRMED) |
| 3 | **Five dead strategy families, still wired** | Dead shells: `cli_settlement_print_lock` 1,831, `forecast_revision` 1,101, `calibration_mean_reversion` 936, `running_extreme_lock` 902, `forecast_mispricing` 867 (5,637 LOC). Tests-only root modules: `forecast_edge.py` 224, `resting_ladder.py` 392, `strike_ladder.py` 318 (934 LOC). None is reachable from `app/`. **[V]** `scripts/analysis/run_weather_strategy_backtests.py:244-266` imports all five at module scope. That file is PROD-LIB: `replay_sufficiency_census.py:94` imports `_capture_instruments_by_id` and `WEATHER_VENUE` from it on the `breezy-replay-daily` unit. | S2 A, F; S4b A; [V] |
| 4 | **Copy-pasted shells** | Strategy shell: about 200 identical lines × 2 extra copies (difflib 1.0 on 7 methods). **[V]** Actor timer bridge copied in 5 places; `nbm_forecast_actor.py:246-284` and `nbm_quantile_actor.py:340-378` differ only in log strings, and `nws_observation_actor.py:261-267` adds a fail-closed side effect (`_rebuild_trusted=False`). Halt-latch preamble duplicated (`trade.py:607-688` vs `:730-744`). Atomic temp+rename written 6 ways. Validators rewritten about 10 times. | S2 B1-B3; S4a C2; S4b C; [V] |
| 5 | **One-implementation protocols** | **[V]** `StateStore` is declared 4 times (`ingest/gate.py:287`, `product_index.py:220`, `gaps.py:185`, `runtime/submit_intent.py:43`), each docstring saying "structurally identical, declared here to avoid an import". Also 9 adapter protocols (several single-use), 9 runtime protocols (3 near-identical `Node` aliases), and `BulletinFetcher` ×2. | S1a C; S1b C; S4a D; [V] |
| 6 | **Duplicated helpers** | **[V]** `_ns_to_datetime` ×5, all in dead shells. `AllowShortNotPermittedError` ×3. Fee θ·p·(1−p) in 4 places (**not** safe to fold: type, rounding and validation differ). Book walk ×2 (behaviour differs). **[V]** The `gs_boundary` solver is duplicated, and the copies have already drifted (`gs_boundary_artefact.py:405` "Duplicated from", literal `xtol=1e-10` at `:491-492` vs the script's `BRENTQ_XTOL`). | S2 B4-B10; S4b C; [V] |
| 7 | **Test-suite weight with no fast tier** | 626 files / 300,560 LOC (2.63× src); 11,249 test functions; 34 files over 1,500 LOC. The `slow` marker covers 1 test and `replay` covers 0. Full gate is 22.7–25.4 min wall. 741 private-attribute assert lines; 4 `os.fork()` tests. | S3 A, C, D (MEASURED); gate timing cited by the operator, not re-measured |
| 8 | **Unwired ingest code** | NBS chain (`NbmForecastActor` 402, `nbm_forecast_parse` 276, `IemMosFallbackTransport` 235), the archive writer `archive_records.py` 95, and `archived_selection.py` 83: about 1,091 LOC with no src or scripts caller. | S4a C3 (static CONFIRMED; whether parked or dead is HYPOTHESIS) |

### 1.4 Documentation and requirements drift (CONFIRMED unless tagged)

**Programme state**
- `PROGRESS.md:86` says "S9 activation pending", but HEAD *is* S9.
- `PROGRESS.md:32` still names cont as the live-measurement family.

**Stale comments in src**
- **[V]** `app/trade.py:713-716` says the FQ branch is "unreachable" because the manifest is `DRAFT_NOT_REGISTERED`. The manifest is REGISTERED.
- **[V]** `exec/client.py:660` cites `weather_common/risk.py:139`; the flag is at `:224`.
- `websocket.py:61-63` cites the wrong `retry.py` lines.
- `operator_controls.py:267` names a non-existent `RiskLimits` type.
- `persistence/__init__.py:1-6` says "single submodule"; there are 22.
- `ingest/gaps.py:408-410` is stale.
- `signing.py` and `write_transport.py:6` docstrings are stale.

**Repository docs**
- The `nws-cli-settlement` skill line 176 recommends pyIEM, which was reversed.
- `AGENT_ARCHITECTURE.md:43,172` says `~=1.231`.
- `STRATEGY_QUICKSTART.md:383` describes the layer order wrongly.
- `deploy/systemd/README.md:9-10` names the wrong drop-in.
- R8 §(viii) contradicts L-26.
- The L-36 anchor (`submit_chain:818`) now sits at `:1200`.
- PROGRESS line cites for `operator_controls` are wrong.
- The ledger "in-memory BY DESIGN" text is half-true, because `seed_spent` re-seeds the ledger at boot.

Sources: S2 G1; S5a B-1..B-10; S5b B1-B15; S4a D.

**Audit contradiction, resolved.** S1a says `tests/unit/test_polymarket_us_exec_snapshot_drift.py` "was not found". S3 lists it as a drift pin. **[V]** The file exists, so S3 is right and S1a's claim is withdrawn.

---

## 2. Requirement-to-subsystem responsibility map

Status values:
- **CLEAR**: one owner, unambiguous.
- **EXTENDS**: Breezy layered on a native API.
- **UNCLEAR**: owner, pin or placement is in doubt.

IDs come from S5a (S-, P-, D-) and S5b (OPS-, ENG-, V-).

| Requirement | Owning Breezy subsystem | Nautilus-owned part | Pinning tests | Status |
|---|---|---|---|---|
| S-01/02/03/05, ENG-09/16: egress barriers N1–N3/N5, exact sets | `tests/conftest.py:82-380`; `scripts/ci/run_tests_no_egress.sh` | none; pyo3 `HttpClient` bypasses `socket` | `test_execution_egress_firewall_guard.py` | CLEAR |
| S-04: credentialed-session refusal | `conftest.py:383-408` | — | not located | UNCLEAR (no pin) |
| S-06, ENG-10: default deselection | `pyproject.toml:49` **[V]** | pytest | `test_probe_containment.py:585` (addopts literal) | CLEAR |
| S-07: B2 GET-only read signer; POST-only write signer | `adapters/polymarket_us/signing.py`, `write_transport.py` | `HttpClient` exposes every verb (the cage is the control) | `test_polymarket_us_signing.py:266-275`, `_write_transport.py`, `test_cage_rule_constants_are_pinned.py` | CLEAR |
| S-08/09/11: maximum daily budget, maximum per position, ledger seed, permit | `adapters/polymarket_us/operator_controls.py:264-427`, `safety.py` | `RiskEngine` max-notional (defence in depth, inert without `AccountState`) | `test_operator_reserved_controls.py`, `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_polymarket_us_permit_issuance.py`, `test_native_order_cap_wiring.py`, `test_risk_engine_ordering_enforcement.py` | EXTENDS. Placement is UNCLEAR: venue-neutral controls live in the adapter (V-07) |
| S-10: reserved-control census | the census test | — | `test_operator_control_assignment_scan.py` | CLEAR |
| S-12/23: `OrderSubmissionPermit`; one permit per process; A-1 ceiling | `runtime/order_enablement.py`; supervisor core `:122-128` | — | `test_runtime_order_guard_permit_expiry.py`, `test_trade_supervisor.py` | CLEAR (B-11 is open) |
| S-13: `BacktestOrderGuard` | `runtime/backtest_order_guard.py` | cash SELL `balance_impact` fails open (`cash.pyx:489-493`) | `test_runtime_backtest_order_guard.py:169-341`, `test_runtime_live_order_guard.py` | EXTENDS |
| S-14: `allow_short` never True | CRH, FQ and `ladder_ev` configs raise; `weather_common/risk.py:224` defaults it | `StrategyConfig` does not reject True | `tests/strategy/*/test_config.py`, `test_weather_common_risk.py:874` | EXTENDS. The pin is non-uniform: the dead shells only default it (S2 E) |
| S-15, P-05: qty≡1; R-10 | `current_rung_hold/config.py:264-266` | — | qty pin not located | UNCLEAR |
| S-16/18/19: submit chokepoint order; AMBIGUOUS; latch | `exec/client.py:_submit_order`, `submit_chain.py`, `runtime/submit_intent.py` | `generate_order_*`; throttler is a rate; in-flight check off | `test_polymarket_us_submit_order_chain.py`, `test_submit_intent_latch.py`, `test_current_rung_hold_pre_arm_race.py`, `test_current_rung_hold_ambiguous_resolver.py` (weak; S3 E) | EXTENDS |
| S-17, OPS-01/02/03/07/08/10: supervisor schedule, adopt, single instance | `runtime/trade_supervisor.py`, `trade_supervisor_core.py` | none (`TradingNode` is one process) | `test_trade_supervisor*.py` (4 files) | CLEAR |
| S-20: drift allowlists | `exec/reports.py:233-418` | report types | `test_polymarket_us_exec_reports.py`, `test_polymarket_us_exec_snapshot_drift.py` [V] | EXTENDS |
| S-21: per-family halt | `strategy/current_rung_hold/trial_day_latch.py`; literals duplicated in supervisor core (B-13) | — | `test_edge3_per_family_halt.py`, `test_set_family_halt_cli.py`, `test_trade_supervisor_cont_self_check.py` | UNCLEAR (literal duplicated across layers, pinned byte for byte) |
| S-22: fee θ drift halt | `adapters/.../fees.py` dated schedule; `strategy/.../fee_drift_probe.py` (venue HTTP from strategy, V-02); `app/trade.py:_build_fee_drift_probe` | Cython `FeeModel` slot | `test_fee_drift_probe.py`, `test_app_trade_fee_drift_probe_wiring.py`, `test_polymarket_us_fee_*.py` (S3 E names them; S5a "not located" is superseded) | UNCLEAR (layer placement) |
| S-24: NO first-order containment | `exec/no_side_keys.py` | — | `test_no_side_keys.py`, `test_no_side_first_order_pending_2026_09_14.py` | CLEAR |
| Account-presence halt | `runtime/account_presence_halt.py` | `RiskEngine.set_trading_state(HALTED)` | `tests/contract/test_account_presence_halt_contract.py` | EXTENDS |
| P-01..04, P-09: PREREG v3 statistic, LOSS_STOP, station-day variance, tally | `settlement/current_rung_hold_v2.py`, `persistence/gs_boundary_artefact.py`, plus **scripts** `family_tally_v2.py`, `score_live_trials.py`, `structural_dead_stop.py` | — | `test_family_tally_v2_look_loop_golden.py`, `test_current_rung_hold_v2_*.py`, `test_multi_position_validation_2026_09_14.py`, `test_gs_boundary_artefact.py` | UNCLEAR (split between src and scripts; solver duplicated [V]) |
| P-06: NO-side hunting | `continuous_strategy.py:1565,2443`, `ladder_ev/scoring.py:70` | — | `test_no_leg_depth10_bid_ladder_2026_09_14.py`, `*_no_side_2026_09_14.py` | CLEAR |
| P-07: rest_v5 shadow, byte-identical orders | `resting_decider.py`, `shadow_rest_store.py` | — | `test_resting_decider_wiring_byte_identical_orders.py` | CLEAR |
| P-08: evaluation trigger frozen (L-34) | first-snapshot latch, dedupe key `continuous_strategy.py:1935-1942` | — | not located | UNCLEAR (no pin) |
| P-10: FQ activation, single sending family | `deploy/families/pm_us_crh_fq_v1.json`, `app/trade.py:709-745`, `strategy/forecast_quantile_ladder` | — | `test_fq_s8_registration_artefacts.py`, `test_fq_caps_and_ambiguous_2026_10_01.py` | CLEAR (stop-rule gap is out of scope; see below) |
| P-11: exit seam unarmed | `persistence/exit_gate.py:55-66` | `Order.tags` | `test_persistence_exit_gate.py:80-139` | CLEAR |
| P-12: programme KILL horizon | none | — | none | UNCLEAR |
| P-13: PREREG only by ruling; sha pins | manifests, `CORPUS_SHA256`, `archive_table.py` (byte-frozen) | — | `test_prereg_v1_is_byte_unmodified.py`, `test_settlement_purity_guard.py` | CLEAR |
| D-01/02/14: settlement-grade, corrections, CLI parse | `normalize/classify.py`, `cli_parse.py`; `settlement/settlement_truth.py:30-44` (+ do-not-dedupe script copy) | — | `test_normalize_classify.py`, `test_normalize_correction_signal_agreement.py`, `test_normalize_cli_parse*.py` | CLEAR |
| D-03..07: `revision_seq`, selection, `is_superseded`, product index, dedupe | `ingest/nws_actor.py:1397-1465`, `domain/selection.py`, `persistence/catalog.py`, `ingest/product_index.py` | `ParquetDataCatalog` write/query (in-place write, silent equal-range skip, filename = ts range) | `test_domain_selection.py`, `test_ingest_product_index.py`, `test_catalog_write_interval_contract.py` | EXTENDS. D-05 is a CONFLICT (B-6) |
| D-08: LST climate day | `domain/climate_day.py:30-53` | — | `test_normalize_climate_day.py` | CLEAR |
| D-09/10: tape vs catalog layer; replay sufficiency | `persistence/feather_*`, `quote_tape_gaps.py`, `analysis/replay_sufficiency.py` | `StreamingConfig`, `convert_stream_to_data` | `test_quote_tape_*`, `test_replay_sufficiency*.py`, `tests/contract/test_quote_tape_ingest_native_pin.py` | EXTENDS |
| D-11/12: venue NO netting and echo | `exec/reports.py:1405-1452`, `leg_prices.py` | — | `test_polymarket_us_exec_positions.py`, `test_leg_prices_2026_09_14.py` | CLEAR |
| D-13: durable key grammar (`^`, never `~`) | `trial_day_latch.py`, `domain/instrument_leg.py` | `InstrumentId` str | real-writer fixtures (L-42) | CLEAR |
| OPS-04/06: `KillMode=process`, `RestartPreventExitStatus`, `TimeoutStopSec` | `deploy/systemd/breezy-trade-supervisor.service:141-168` | — | **none** [V: no `\bKillMode\b` under `tests/`] | UNCLEAR (unpinned) |
| OPS-05/20/21: memory caps | unit files; host drop-ins | — | `test_analysis_units_memory_capped.py`, `test_quote_tape_service_memory_ceiling.py` | UNCLEAR (host drop-ins override the repo) |
| OPS-09/15/16: restart window, `systemd-run`, hand relaunch | procedural only | — | none | UNCLEAR |
| OPS-11: four-part liveness | supervisor core, partial | — | none | UNCLEAR |
| OPS-17/18/19: alert egress, OnFailure | `runtime/health.py`, `check_alerts_cli.py`, `study_failure_notifier.py`, units | `Component.degrade` unused | `test_alert_egress.py`, `test_study_failure_alert.py`, `test_alerts_env_deploy.py` | CLEAR for timers; UNCLEAR for long-running units (OPS-19) |
| OPS-22/23/24: catalog pipeline, timer ticks, protected window | units + `runtime/quote_tape_*` | `StreamingConfig` | `test_deploy_timer_hours.py`, `test_analysis_units_serialized.py` | EXTENDS. OPS-24 is UNCLEAR (window derived from CRH, not FQ) |
| OPS-25/27/28: one sending family via unit env | unit + `settings.py` | — | `test_trade_supervisor_phase1_unit.py:49-94` | CLEAR |
| ENG-01/02/03: layers, exactly 4 `ignore_imports`, `.com` ban | `pyproject.toml:73-212` [V] | — | `test_test_safety_tooling_config.py:87` (set equality) [V] | CLEAR |
| ENG-04/05: exact pins | `pyproject.toml:11-26` | — | `test_test_safety_tooling_config.py:36-40` | CLEAR |
| ENG-06/07: mypy strict; exact ratchet ceilings | `test_mypy_ratchet.py:282-348` | — | itself | CLEAR (CF-12 W2 staged at `4b0b4f6`) |
| ENG-13/14/20: full gate after every merge; no installers in a worktree; gate rewrites `src` in place | procedural; `tests/support/host_python.py` | — | `test_archive_import_contract.py:49-56` rewrites `persistence/catalog.py` | UNCLEAR (procedural only) |
| V-01..V-11: Polymarket.us coupling outside `adapters/` | `strategy/current_rung_hold`, `runtime`, `app` | — | — | UNCLEAR. Kalshi is parked (V-12), so no action beyond "do not deepen" |

### 2.1 Ownership ambiguities the refactor must not resolve by accident

1. **Venue-neutral money controls live in the adapter (V-07).** `DailySpendLedger` and the permit are imported by `runtime/order_enablement.py` and `continuous_strategy.py`.
   - Moving them is a layer change on the live order path, and L-22 pins a single construction site.
   - **Retain the location in this plan.** Move only under a separate design that the peers review.
2. **Halt literals are duplicated between `trial_day_latch` (strategy) and supervisor core (runtime) (B-13)** and pinned byte for byte. Runtime cannot import strategy (`pyproject` layer rule). Leave as is.
3. **PREREG evaluation is split between src and scripts (P-01..P-09).** Step R2.2 consolidates ownership without changing semantics.
4. **The fee-drift probe does venue HTTP from the strategy layer (V-02).** Retain; any relocation is a design item.

### 2.2 Conflicts: blockers vs separately tracked findings

| # | Conflict | Evidence | Classification |
|---|---|---|---|
| C1 | Stale PROGRESS rows (`:32` cont live, `:86` S9 pending, wrong `operator_controls` cites) | S2 G1; S5a B-1; S5b B1 | **BLOCKER (before)**: fix in R0.2. Sub-agent briefs take PROGRESS as fact; stale rows propagate (memory "verify premises before briefing"). |
| C2 | PREREG v3 §7 scopes the maximum per position per station-day; code applies it per order; R-10 allows several positions | S5a B-3 | **Separately tracked** (ruling item, P-13). Blocker only for a step touching `operator_controls.authorize_order_cost`, and no step does. |
| C3 | `is_superseded` is vacuous for live records: always written False and ignored by selection, so a corrected-away FINAL passes `is_settlement_grade` | S5a B-6; S4a E | **Separately tracked** (settlement correctness). **DURING blocker** for R3.6 (domain boilerplate): characterization test CT-9 must pin current behaviour before that step. |
| C4 | `KillMode=process` (+ `RestartPreventExitStatus=2`, `TimeoutStopSec=120`) has no test | S5b OPS-04, C; [V] | **BLOCKER (before)** for every supervisor step: R0.4 adds the pin. |
| C5 | Host TEMPORARY memory drop-ins override the repo caps; past their removal date; README names the wrong file | S5b OPS-21, B4-B5 | **Separately tracked (ops)**. Blocker only for a step editing `breezy-nws-ingest` or `breezy-replay-daily` unit files; this plan edits neither. |
| C6 | Live hand-launched node (`breezy-trade-hand-151202`) runs an unversioned launcher in a scratchpad; no A-1 ceiling; R8 contradicts L-26 | S5b OPS-16, B2-B3 | **DURING constraint.** Supervisor and app steps must keep the `spawn_node()` env/argv contract and log-marker text byte-stable, because the hand launcher mirrors it. Ops ownership of hand launches is tracked separately. |
| C7 | Failed units: `breezy-replay-daily`, `breezy-fee-evidence-pull`, transient parity units | S4b E; S5b live context | **BLOCKER (before)** for R2.x steps that touch their scripts (S4b "before any move" 1). A refactor must not land on an already-red job without a baseline. |
| C8 | Gate tests rewrite `src` in place (ENG-20); units execute from the primary tree on the same branch | S5b ENG-15, ENG-20 | **Standing constraint.** Never run the gate in `/home/jon/breezy`. Merging to the branch is a deploy at the next spawn or timer. |
| C9 | Ledger described as "in-memory by design" but re-seeded from durable fills; AMBIGUOUS spend is lost on restart | S5a B-2 | Doc fix in R0.2; the behaviour gap is **separately tracked**. |
| C10 | Stale θ=0.06 hard-coded on the kill-clock path (`mb_current_rung_edge_study.py:195` → `family_tally_v2`, `live_family_tally`); venue θ is 0.0695 since 2026-09-17 | S4b risk 4, D | **Separately tracked, HIGH, reportable.** Changing it alters PREREG outputs (ruling, P-13). R2.2 must keep it byte-for-byte. |
| C11 | v3 §3 vs §10 one-sided vs two-sided α; "LD-OBF on Wilson" is inaccurate | S5a B-4 | Separately tracked (ruling text). |
| C12 | FQ `external_order_claims` not shown set (HYPOTHESIS); OMS type unverified | S2 C, G3-G4 | Separately tracked question for the trading-reliability peer. Not a refactor blocker. |
| C13 | NYC excluded from CRH `SUPPORTED_STATIONS` (4) vs 5-city surface | S5b B15 | Separately tracked. |

**OUT OF SCOPE, reportable [HIGH].** The live family `pm_us_crh_fq_v1` has **no registered statistical stop**. Its boundary is a not-applicable sentinel that refuses any group-sequential tally. The only stops are the maximum daily budget, the maximum per position, the fee-drift halt and the manual halt tool. Under L-38 this is a missing stop (S5a C, P-10). A refactor cannot and must not fix it; it needs a ruling.

---

## 3. Prioritized refactoring plan

### 3.1 Dispositions per subsystem

Only a disposition, its single reason, and the native extension point verified by the audit. "Behaviour change" lists what would change if the subsystem were altered beyond the disposition.

| Subsystem | Disposition | Requirement | Why | Verified Nautilus extension point | Behaviour difference / integration constraint | Simplest ownership boundary |
|---|---|---|---|---|---|---|
| Signers + GET/POST cages | **Retain** | S-07 | The cage is the control; merging collapses B2 | `HttpClient.get/post` injected (`pyi:5417-5452`) | Merging is the hazard | Breezy owns the signed client graph |
| WebSocket + 10-sub pool | **Retain** | market data; venue cap | No header-refresh API | `WebSocketClient.connect` (`pyi:5530-5558`) | Native reconnect only after the probe in §3.4 BC-11 | Breezy |
| Data client, provider, parsing, symbology | **Retain** | instruments, quotes | `.com` grammar differs; import banned | `LiveMarketDataClient`, `InstrumentProvider.load_all_async` | — | Breezy |
| Exec client + reports + `submit_chain` + refusals | **Retain; simplify internally (last, optional)** | S-16/18/19/20 | The 5,957-line class is the maintenance cost | five `generate_*` methods, `calculate_commission` (`live/execution_client.py:343-440`) | A split must move E0/N2/X3 exact sets in the same commit (L-12) | Breezy owns pre-POST policy and parsing |
| Fee model | **Retain** | S-22 | PyO3 type mismatch | Cython `FeeModel.get_commission` (`fee.pyx:33-168`) | Deleting the override books zero commission | Breezy |
| Permit, ledger, `OrderSubmissionPermit`, latch | **Retain** | S-08..S-12, S-19 | Native caps have no day dimension and are inert without an account | `LiveRiskEngineConfig` stays as defence in depth | Any merge alters money semantics | Breezy |
| SQLite state store | **Retain**; **consolidate the protocol only** | durable gate, latch, intent | Native needs Redis | none | Schema change is BC-2 | Breezy |
| Node config, settings, composition roots | **Retain**; **simplify** `app/trade.py:run` | P-10, OPS-28 | 476-line function, duplicated preamble | `TradingNodeConfig`, `Trader.add_actor` | Empty strategy and exec-algorithm literals and `inflight_check_interval_ms=0` stay explicit (S1b E) | Breezy maps settings; Nautilus runs the node |
| Supervisor | **Retain; simplify** (move pure decisions into core) | S-17, OPS-01..10 | Functions of 228/215/194 lines | none (systemd + subprocess) | Adopt semantics, `PASS_ADOPTED_LOG_UNKNOWN`, log markers | Breezy |
| Account-presence halt, `BacktestOrderGuard`, PIT guard | **Retain** | S-13, account halt | They close native fail-open gaps | `RiskEngine.set_trading_state` | — | Breezy |
| Quote-tape recorder | **Retain** | D-09 | Already native | `StreamingConfig` | — | Nautilus writes |
| Quote-tape ingest CLI | **Simplify** (split functions) | D-09/10 | 177/162/154/142-line functions | `ParquetDataCatalog.convert_stream_to_data` (`parquet.py:2604`) | Never "fix" idempotency by same-range rewrite | Nautilus converts; Breezy bounds memory and refuses truncation |
| Health, alerts, `logging_bridge` | **Retain** | OPS-17/18 | No native substitute | `MessageBus.subscribe(ComponentStateChanged)` only | L-16: timer callbacks record their own alert | Breezy |
| Domain `Data` types + `strict_arrow` | **Retain**; boilerplate simplification **deferred** (HYPOTHESIS) | D-01..D-07 | Each field is listed 4×, but generated code risks schema drift | `register_arrow(encoder, decoder)` (`serializer.py:89`) | Strict decode must still raise | Nautilus owns the hook; Breezy the fields |
| Catalog wrapper | **Retain; split** the filesystem probe (241 lines) out | D-04 | Unrelated code in one file | `ParquetDataCatalog.write_data/query` | The ENG-20 test rewrites `catalog.py` | Nautilus storage; Breezy invariants |
| Ingest actors | **Consolidate** the timer bridge | D-03..07, FQ feed | 5 copies | `Clock.set_timer(start_time=)` native; `run_in_executor` unusable | Observation actor's fail-closed hook must survive | Breezy |
| `StateStore` protocol ×4 | **Consolidate** | gate, index, gaps, intent | Same shape; docstrings admit it | none | None, if the leaf module imports no Nautilus | Breezy |
| Atomic writers ×6 | **Retain for now** (durability differs) | evidence stores | Consolidating changes durability | none | fsync/naming changes are BC-1 | Breezy |
| NBS chain, archive writer, `archived_selection` | **Remove or park** (approval BC-4) | none live | No src or scripts caller | — | Breaks 3 test files + import contract rows | — |
| `features/` | **Remove** (approval BC-5) | none | Empty; pinned by contract + 1 test | — | Edit to a contract row | — |
| CRH (`current_rung_hold`) | **Retain; split** `continuous_strategy.py` and `trial_day_latch.py` as pure moves only (late) | P-01..P-08 | 3,434 / 1,808 lines | `Strategy` lifecycle already native | L-34: any change to snapshot selection is class C | Breezy |
| FQ, `ladder_ev`, `weather_common`, `depth10`, `harness_probe`, `settlement/`, `analysis/` | **Retain** | P-10, D-01, P-01 | Live or library | — | Do not merge `margin`/`scoring.margin` or the fee functions (S2 B4-B7) | Breezy |
| Five dead shells + `forecast_edge`, `resting_ladder`, `strike_ladder` | **Remove** (approval BC-3), after R2.5 | none live (L-9; the 09-20 mapping is HYPOTHESIS) | 6,571 LOC; drags a non-uniform `allow_short` pin | — | `strike_ladder` hosts contract `test_multi_instrument_weather_strategy.py` | — |
| `scripts/` PROD + PROD-LIB | **Consolidate** pure prod logic into src; keep entry points stable | P-01..P-09, OPS-22 | Only implementation of the kill-clock and artefacts | — | Units reference paths; ruling-cited STUDY scripts are frozen | src owns logic; scripts are thin CLIs |
| `scripts/` STUDY | **Retain frozen**; archive retired ones (BC-6) | evidence citability | Rulings cite path and line | — | — | — |
| Replace-with-Nautilus | **None in this plan** | — | §1.2 | — | — | — |

### 3.2 Sequenced steps

**Global acceptance for every step**
- Full egress-blocked gate (`scripts/ci/run_tests_no_egress.sh`, no arguments) green on the refactor worktree. Run it with `PYTHONPATH=<wt>/src` and the primary-tree interpreter, never `uv`/`pip` (L-51).
- `lint-imports` green.
- `test_mypy_ratchet.py` green. Ceilings are exact, so any step that moves code carrying mypy errors re-baselines **in its own commit** (ENG-07).
- After merge to `feat/data-capture-and-risk`: the full gate again on the integration tree (L-43). Read `GATE_EXIT` before any push (memory).

**Live-path rule.** Steps marked **LIVE** touch code the trade node loads at its next 16:50Z spawn.
- Merge them only between 01:15Z and 14:00Z, so a revert plus a 25-minute gate fits before 16:40Z.
- Each needs an independent reviewer (`python-reviewer` + `code-reviewer`; plus `security-reviewer` for the exec or permit paths).
- Steps touching `trade_supervisor*` also need a supervisor restart inside 01:00–16:40Z (OPS-09). That is coordinator ops, never part of the step.

**Rollback default.** `git revert <sha>` on the integration branch, then the full gate. No on-disk state format changes in any R-step. The only state-format change in this plan is BC-2.

#### Phase 0: Safety net and drift (test-only or docs/comments-only; no src behaviour)

**R0.1: Fix stale comments in src**
- Requirement and evidence: §1.4; [V] `trade.py:713-716`, [V] `exec/client.py:660`; S1a F; S1b F; S4a D.
- Change: comment and docstring text only:
  - `app/trade.py:709-719`
  - `exec/client.py:659-660` → `risk.py:224`
  - `websocket.py:61-63` → `retry.py:195-197`
  - `operator_controls.py:267` (drop `RiskLimits`)
  - `persistence/__init__.py:1-6`
  - `ingest/gaps.py:408-410`
  - `signing.py` "add a method" text
  - `write_transport.py:6`
- Dependencies: none.
- Benefit: removes the false-premise sources that agents read as fact.
- Acceptance: full gate. Confirm no test scans comment text in these files first (L-54 grep, e.g. `test_cage_rule_constants_are_pinned.py` P1 scan). `archive_table.py` untouched.
- Rollback: revert.
- Effort S, risk L. **LIVE** (exec client and app files are reloaded at spawn even though only comments change).

**R0.2: Docs drift**
- Requirement and evidence: C1, C9; S5b B1-B12; S4a finding 9.
- Change:
  - `docs/core/PROGRESS.md:32,86` and the `operator_controls` cites, keeping the 250-line / 12 KB hook (ENG-12)
  - the `nws-cli-settlement` skill line 176
  - `AGENT_ARCHITECTURE.md:43,172`
  - `STRATEGY_QUICKSTART.md:383`
  - `deploy/systemd/README.md:9-10`
  - the L-36 anchor note
  - the ledger "in-memory" wording
  - the R8 §(viii) note pointing to L-26
- Dependencies: none.
- Acceptance: the PROGRESS size hook passes; nothing under `src` reads `docs/evidence` (`test_probe_containment.py:550`).
- Effort S, risk L. Not live.

**R0.3: Mark the 10 unmarked contract modules**
- Requirement and evidence: S3 B, F. [V] 27 of 39 files under `tests/contract` carry a mark.
- Change: add `pytestmark = pytest.mark.contract` to:
  - `test_nautilus_cache_durability_contract.py`
  - `test_current_rung_hold_wiring_contract.py`
  - `test_forecast_source_liveness_contract.py`
  - `test_ingest_backlog_drain.py`
  - `test_instrument_leg_layer_agreement_contract.py`
  - `test_mechanism_test_ineligibility.py`
  - `test_no_leg_settlement_sign_contract.py`
  - `test_no_side_scorer_tally_leg_contract.py`
  - `test_position_monitor_trial_id_join_contract.py`
  - `test_rung_hold_families_mutual_exclusion_contract.py`
- Dependencies: none.
- Benefit: `-m contract` selects the full Nautilus-bump pin set, including the cache-durability pin.
- Acceptance: full gate. Grep `tests/` for any count pin on `contract` marks first (L-54).
- Effort S, risk L. Not live.

**R0.4: Pin the supervisor unit directives**
- Requirement and evidence: OPS-04/06; C4; [V] no test names `KillMode`.
- Change: new unit test that parses `deploy/systemd/breezy-trade-supervisor.service` and asserts `KillMode=process`, `RestartPreventExitStatus=2`, `TimeoutStopSec=120`, `Restart=always`. It must also assert the absence of `MemoryHigh`/`MemoryMax` (OPS-05 is already pinned by `test_analysis_units_memory_capped.py:169`; extend rather than duplicate if that file is the natural host).
- Dependencies: none.
- Benefit: a sanctioned guard on the line the unit itself calls "THE MOST IMPORTANT LINE".
- Acceptance: test green on HEAD and red on a locally mutated copy (positive control, L-12 "what would refuse this").
- Effort S, risk L. Not live (test only).

**R0.5: Characterization tests for under-documented behaviour**
- Requirement and evidence: S3 F; S5a C; S5b C.
- Write each test against current behaviour, green on HEAD, using public entry points:
  - **CT-1, AMBIGUOUS.** Submit once through the public command port and get a with-id empty-executions body. Assert the intent stays OPEN and no second POST is made, without `_latch` or `_submit_order` (S3 F, C#1-2).
  - **CT-2, supervisor.** Adopt-not-double-spawn with a process double, no `os.fork()` (S3 F).
  - **CT-3, ledger.** Clock-rewind refusal; `seed_spent` keeps `max()`; prior-day pruning; release/true-up at most once (S5a C, S-09). Messages name the control, never a value.
  - **CT-4, ingest.** `nws_actor` `ts_init` nudge to `existing_max+1` (S4a §B; S5a C).
  - **CT-5, ingest.** `product_index` first-write-wins with a mismatch alarm (D-06). Extend only if existing tests lack it.
  - **CT-6, scoring.** `combine_station_day` same-rung fold and the `rung=None` exemption (S5a C).
  - **CT-7, strategy.** Continuous-strategy snapshot dedupe key `(ts_event, ask, size)` (P-08, `continuous_strategy.py:1935-1942`).
  - **CT-8, supervisor.** Constants and markers: boot retry 8 / 15 min, `PERMIT_ALERT_HEARTBEAT`, `PERMIT_DEFERRED_MAX`, `SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS`, and the log-marker strings parsed as an API (S5b C).
  - **CT-9, settlement.** `is_settlement_grade` returns True for a corrected-away FINAL in live records. This **documents** the B-6 vacuity and does not fix it.
  - **CT-10, egress.** Credentialed pytest refusal requires all three unlocks (S-04).
  - **CT-11, venue.** qty≡1 refusal on CRH config (S-15).
- Dependencies: none. Prerequisite for R1.2 (CT-4), R3.1 (CT-8), R3.2 (CT-2, CT-8), R3.4 (CT-7), R3.5 (CT-1), R3.6 (CT-9).
- Acceptance: every CT green on HEAD, plus a demonstrated red on one deliberate local mutation each (not committed).
- Note: tests read stores through the real writer (L-42).
- Effort M, risk L. Not live.

**R0.6: Tripwire on scripts' private `breezy` imports**
- Requirement and evidence: S4b risk 6 (13 scripts).
- Change: one unit test that AST-scans `scripts/**/*.py` for `from breezy... import _x` and asserts every such symbol still resolves. This turns a silent nightly-job break into a gate failure for every later src step.
- Dependencies: none.
- Effort S, risk L. Not live.

**R0.7: Introduce the `heavy` marker (configuration only)**
- Requirement and evidence: S3 F marker hole. [V] `pyproject.toml:56` defines `slow` as an env-gated skip (`BREEZY_RUN_SLOW`), so it cannot serve as a "runs in full gate, excluded from fast tier" marker. [V] Markers are pinned only by membership (`test_test_safety_tooling_config.py:44-46`).
- Change: add `"heavy: real-engine, fork, subprocess or large-fixture tests; runs in the full gate, excluded from the fast tier"` to `markers`. **Do not touch `addopts`** (pinned by `test_probe_containment.py:585`, L-54).
- Dependencies: none for the marker. Marking files waits for the Rev 2 durations table (§4.6).
- Effort S, risk L. Not live.

#### Phase 1: Low-risk mechanical consolidation (pure moves)

**R1.1: One `StateStore` protocol**
- Requirement and evidence: S4a C2, D; [V] four declarations.
- Change: create a stdlib-only leaf module in the lowest layer whose package `__init__` is import-free. The candidate is `breezy/persistence/state_store.py`; verify `persistence/__init__.py` imports nothing that reaches Nautilus, which is the docstrings' stated concern.
  - `ingest/gate.py`, `product_index.py`, `gaps.py` and `runtime/submit_intent.py` import it.
  - `gate.ClosableStateStore` keeps extending it.
- Dependencies: R0.*.
- Benefit: removes 3 duplicate declarations (about 30 LOC) and one stated "keep in sync" obligation.
- Acceptance: full gate; `lint-imports` (layer: persistence is below ingest and runtime). Run `codegraph_impact` on each `StateStore` before the edit; [V] the gaps variant has 9 callers, including `trial_day_latch`.
- Rollback: revert.
- Effort S, risk L. **LIVE** (`submit_intent` loads on the node).

**R1.2: Actor timer-bridge helper**
- Requirement and evidence: S4a C2 rank 4; [V] three bodies compared; L-16.
- Change: one helper in `breezy/ingest/` that owns `_submit`, `_settle`, `_on_poll_done`, `_record_task_death`, `inflight`, `poll_timer_armed`, `_arm_timer`, `_stagger_start_time` and `on_stop`.
  - Parameters: timer name, interval, a log label, and an `_on_task_death(exc)` hook. The hook keeps `nws_observation_actor`'s `_rebuild_trusted = False` ([V] `:264-266`).
  - Apply to `nbm_quantile_actor.py` and `nws_observation_actor.py`. Apply to `nws_actor.py:778` and `strategy/current_rung_hold/fee_drift_probe.py:356-370` only if their bodies match after diffing.
  - Skip `nbm_forecast_actor.py` if BC-4 is approved.
- Dependencies: R0.5 CT-4.
- Benefit: about 60 lines × 3–4 copies (about 180–240 LOC). One place implements the L-16 discipline.
- Acceptance:
  - `tests/contract/test_live_timer_thread_affinity.py`
  - `tests/unit/test_nbm_quantile_actor.py`, `test_nws_observation_actor*.py`, `test_ingest_nws_actor*.py`
  - `tests/unit/test_forecast_quantile_ladder_boot.py`
  - full gate
- Migration: CRITICAL log text changes. Grep `caplog` assertions and the supervisor/alert log-marker parsers (S5b D, "log marker text") for these strings first. If any parser matches, keep the strings exactly.
- Rollback: revert.
- Effort M, risk M. **LIVE**: `NbmQuantileActor` feeds the sending FQ family ([V] `app/trade.py` instantiates it).

**R1.3: Consolidate the three `Node` protocols**
- Requirement and evidence: S1b C, E.
- Change: one `Node` protocol in `runtime/` used by `cli.py:90`, `quote_tape_cli.py:123`, `trade_cli.py:253`.
- Benefit: small, but it removes divergent near-copies.
- Acceptance: full gate; mypy ratchet re-baseline if counts move.
- Effort S, risk L. **LIVE** (`trade_cli`).

**R1.4: Split the filesystem probe out of `persistence/catalog.py`**
- Requirement and evidence: S4a D (241 lines of unrelated mountinfo/NFS code at `:961-1202`).
- Change: move it to `persistence/filesystem_probe.py`; re-export the public names from `catalog.py`.
- Dependencies: **first read `tests/unit/test_archive_import_contract.py:49-56`**, which rewrites `catalog.py` in place (ENG-20). The move must not change what that test plants or restores.
- Also grep for `monkeypatch.setattr("breezy.persistence.catalog._…")` targets that the moved code reads. A re-export does not redirect an internal lookup.
- Acceptance: `test_persistence_catalog.py`, `tests/contract/test_persistence_partitioning.py`, `test_catalog_nws_records.py`, full gate.
- Effort S, risk L–M. Not on the order path; it is on the settlement ingest path.

**R1.5: Pay off `ignore_imports` row `ingest.nws_actor -> runtime.health`**
- Requirement and evidence: ENG-01; S4a D row 1 (`runtime/health.py` imports nothing from `breezy`; value types at `:154,243,351,706-746`).
- Change: move `GapSummary`, `HealthSnapshot`, `AlertPayload`, `AlertCondition(Key)` and `AlertState` to a module below ingest. Re-export from `runtime.health`. Replace `nws_actor`'s TYPE_CHECKING + `_health()` indirection (`:197`, `:331-355`) with a direct import.
- **Same commit:** remove the row from `pyproject.toml:105` and from the set in `test_test_safety_tooling_config.py:87`. This narrows a debt set and is a safety-reviewed edit under L-54.
- Dependencies: R0.*.
- Acceptance: `lint-imports`; full gate. Confirm these types are not persisted by qualified class name (HYPOTHESIS: `AlertState` is JSON).
- Benefit: 4 → 3 debt rows; removes a function-level import hack.
- Rollback: revert (config and test move together).
- Effort S–M, risk L. Not on the order path. NWS ingest is a long-running unit, so it takes effect at its next restart.

**R1.6: Pay off row `persistence.quote_tape_gaps -> adapters...tape_records` (HYPOTHESIS)**
- Requirement and evidence: ENG-01; S4a D row 2.
- Change: **do not move the `QuoteTapeGap` `Data` class**; catalog type identity is at stake. Instead relocate the consumer loader `persistence/quote_tape_gaps.py` up to a layer allowed to import adapters, if its importers permit.
- Dependencies: a `codegraph_impact` on `quote_tape_gaps` to list importers. If any importer sits at or below `persistence`, **drop this step** and record the row as permanent debt.
- Same-commit config and test edits as R1.5.
- Effort S–M, risk M. Off the order path.

#### Phase 2: Production logic out of `scripts/`

**Before all of Phase 2:** C7 is acknowledged. Capture a baseline output of each affected nightly job from a read-only copy of its inputs into a scratch directory. These are the golden outputs for the step.

**R2.1: Freeze the boundary-solver duplication with a parity pin; do not edit the script**
- Requirement and evidence: P-01; [V] `gs_boundary_artefact.py:405,491-492`; S4b C.
- Conflict, resolved: S4b says "merge into `gs_boundary_artefact`", but `crh_group_sequential_boundaries.py` is cited by a ruling and generates a sha-pinned artefact. Rulings cite scripts by path and line, so editing it breaks citations.
- Change: a unit test that loads both implementations (`spec_from_file_location`, the existing pattern) and asserts equal outputs on the registered parameters. Assert `BRENTQ_XTOL == 1e-10`, or document the difference if not equal.
- Benefit: drift becomes a gate failure.
- Effort S, risk L. **Question for review:** should the src copy instead become the source of truth, with the generator rerun under a ruling?

**R2.2: Move PREREG fill-admission core into src**
- Requirement and evidence: P-01..P-09; S4b D(3).
- Change: move `score_live_trials.py:_admit_fill`, `_admit_one_fill`, `compute_residual` and `read_filled_trials_state_db`, plus `fill_time_count.py`, into a `breezy.analysis` module. The live path is barred from importing analysis (ENG-03), which is correct for an offline scorer.
  - Scripts keep their paths and CLIs and import from src. Unit files are unchanged.
  - `mb_current_rung_edge_study.py`'s θ=0.06 stays **byte-for-byte** (C10).
- Dependencies: R0.6, C7 baseline.
- Benefit: the kill-clock gains a src owner, mypy strict coverage in src, and layer checks. It removes the script-private import `fill_time_count._open_readonly`.
- Acceptance:
  - `test_family_tally_v2_look_loop_golden.py`, `test_family_tally_v2_*.py`, `test_structural_dead_stop*.py`
  - output of `score_live_trials` and `family_tally_v2` on the frozen baseline is **byte-identical**
  - `lint-imports`; full gate; mypy ratchet re-baseline in its own commit (code moves from `scripts/analysis` into `src`)
- Rollback: revert; units are untouched.
- Effort L, risk M. Not on the order path. It is the KILL/SURVIVE path, so the trading-reliability peer must review.

**R2.3: Extract the instrument-discovery seam from `run_weather_strategy_backtests.py`**
- Requirement and evidence: D-10; [V] `run_weather_strategy_backtests.py:244-266,353,1325-1428`; [V] `replay_sufficiency_census.py:94-95`; codegraph shows `_select_capture_instruments` also called from `current_rung_hold_paper_replay.py` and `whole_tape_paper_replay.py`.
- Change: move `WEATHER_VENUE`, `_capture_instruments_by_id`, `_select_capture_instruments` and `TapeInstrument` into a new PROD-LIB module with no dead-strategy imports. Two placements:
  - preferred: `breezy.analysis.tape_instruments` (src, typed);
  - fallback: a new `scripts/analysis` module.

  `run_weather_strategy_backtests.py` re-imports them, so its path and behaviour are unchanged for ruling citations. The three PROD/PROD-LIB consumers import the new module.
- Dependencies: R0.6; C7 (`breezy-replay-daily` is currently failed). Prerequisite for BC-3.
- Benefit: decouples the nightly replay from five dead packages. Today a dead-family deletion would break a production timer.
- Acceptance: `tests/unit/test_census_column_scan.py`, `test_replay_sufficiency_census.py`, paper-replay tests, full gate. A census on the frozen baseline is byte-identical.
- Effort M, risk M. Not on the order path.

**R2.4: Promote private symbols that PROD/PROD-LIB scripts import (optional)**
- Requirement and evidence: S4b A private column.
- Change: public aliases for `_local_hour`, `_fee` (`decision.py:320`, keeping Decimal HALF_EVEN), `_round_cost_up_to_cent`, `_UNPINNED_SHA256`, `_fee_coefficient`. The private names stay, so ruling-cited STUDY scripts are untouched.
- Dependencies: R0.6.
- Effort S, risk L. `decision.py` is **LIVE**.
- Note: if peers judge R0.6 sufficient, drop this step (YAGNI).

#### Phase 3: Oversized-module decomposition (pure moves, highest scrutiny, late)

**R3.1: Decompose `app/trade.py:run` (476 lines)**
- Requirement and evidence: P-10, OPS-28; S1b C; S2 B3 (halt-latch preamble `:607-688` vs `:730-744`).
- Change: extract one builder per `composition_kind` and one shared halt-latch preamble helper. The preamble is parameterized by key prefix and latch type; the comments say "same shape". Same file or a sibling `app/` module.
- Must stay byte-stable: boot log lines, the permit line (OPS-13, L-30) and exit codes.
- Dependencies: R0.1, R0.5 CT-8.
- Benefit: −40 to −80 duplicate LOC; three readable builders.
- Acceptance:
  - `tests/contract/test_node_composition_contract.py`, `test_trade_node_lifecycle_contract.py`
  - `test_app_trade_*.py`, `test_fq_caps_and_ambiguous_2026_10_01.py`, `test_operator_caps_through_the_live_composition.py`
  - full gate; peer review
- Effort M, risk H. **LIVE** (boot path of the sending family).

**R3.2: Move supervisor decision logic into `trade_supervisor_core.py`**
- Requirement and evidence: S-17, OPS-01..10; S1b E.
- Change: split `_do_self_check` (228), `_do_midday_watch` (215) and `_run_forever` (194) into pure decision functions in core plus thin I/O shells.
- Must stay unchanged: halt literals (B-13), `spawn_node` env/argv (C6), log markers, `PASS_ADOPTED_LOG_UNKNOWN`.
- Dependencies: R0.4, R0.5 CT-2/CT-8.
- Acceptance: the 4 `test_trade_supervisor*.py` files, full gate.
- Deployment: requires a supervisor restart inside 01:00–16:40Z, `KillMode=process` intact. That is coordinator ops after merge, and the node stays up.
- Effort L, risk H. **LIVE** (supervisor).

**R3.3: Split `quote_tape_ingest_cli.py` long functions**
- Requirement and evidence: D-09/10; S1b B8, C.
- Change: split `_convert_one_tick_type_per_file` (177), `_ingest_instance_per_file` (162), `run_ingest` (154) and `run` (142) into helpers in the same module or a sibling. Keep the native mirror (`:809`) intact.
- Acceptance: `tests/contract/test_quote_tape_ingest_native_pin.py`, `test_catalog_write_interval_contract.py`, `test_quote_tape_*`, `test_extend_dedupe_filtered.py` (`memory`), full gate.
- Effort M, risk M. Not the order path; the catalog timer runs every 15 minutes, so the step goes live within 15 minutes of merge.

**R3.4: Split `continuous_strategy.py` (3,434 lines; class ~3,017; `_hunt_tick` 570) by moving code only**
- Requirement and evidence: P-01..P-08; S2 D, F.
- Change: move pure helpers and the NO-side shadow evaluator into sibling modules. **No reordering inside `_hunt_tick`** (L-34: changing which snapshot becomes the trial is class C).
- Dependencies: R0.5 CT-7.
- Acceptance: `test_current_rung_hold_study_replay_equivalence.py`, `test_continuous_rung_hold_*.py`, `test_current_rung_hold_paper_replay.py`, full gate. A paper replay on SFO 09-01 (the one clean tape, memory) is byte-identical.
- Effort L, risk H. Not the sending family today (unit sends FQ, `deploy/.../breezy-trade-supervisor.service:128`). `pm_us_crh_v4` is REGISTERED, so treat the step as **LIVE**.

**R3.5: Extract `_resolve_ambiguous_intents` (605 lines) from `exec/client.py` (OPTIONAL, last)**
- Requirement and evidence: S-16/18/19; S1a C, E.
- Change: move the resolver into a sibling `exec/` module.
- **Same commit:** widen the N2, X3 and E0-INERT exact sets by one reviewed row (L-12, L-14, L-46). `classify_create_order_outcome` stays byte-unchanged (L-36). `_submit_order` itself is **not** split; its call set must stay on the static allowlist.
- Dependencies: R0.5 CT-1; security-reviewer sign-off.
- Acceptance: `test_execution_egress_firewall_guard.py`, `test_polymarket_us_submit_order_chain.py`, `test_current_rung_hold_ambiguous_resolver.py`, `test_polymarket_us_exec_client.py`, full gate.
- Effort L, risk H. **LIVE (order path).** **Question for review:** does the value justify the risk while live n is small? The default is to defer.

**R3.6: `nws_actor.py` health extraction**
- Requirement and evidence: D-03..07; S4a F.
- Change: move `_alert_conditions` (188) and `_emit_health` (129) into an ingest sibling module. The bridge is already consolidated by R1.2.
- Dependencies: R1.2, R1.5, R0.5 CT-4/CT-9.
- Acceptance: `test_ingest_nws_actor*.py`, `tests/integration/test_ingest_crash_between_mark_and_persist.py`, `test_runtime_restart_resume.py`, full gate.
- Effort M, risk M. Off the order path; settlement ingest.

**Recommended order:** R0.1–R0.7 → R1.1 → R1.3 → R1.4 → R1.5 → R1.2 → R1.6 → R2.1 → R2.3 → R2.2 → R2.4 → R3.3 → R3.6 → R3.1 → R3.2 → R3.4 → (R3.5).
- Phases are independently mergeable.
- Phase 0 alone delivers the safety net.
- Phase 1 alone delivers the protocol, actor and layer-debt payoff.

### 3.3 Projected LOC effect (PROJECTED, not measured)

| Source | Removed or relocated |
|---|---|
| R1.1 + R1.2 + R1.3 | about 250–300 duplicate LOC removed |
| R3.1 | about 40–80 duplicate LOC removed |
| R2.2 + R2.3 | about 1,000–1,500 LOC relocated from scripts to src (not removed) |
| BC-3 | 6,571 src LOC + dependent tests (count unknown, HYPOTHESIS) |
| BC-4 | about 1,091 src LOC |

### 3.4 Proposed behaviour changes requiring approval (never inside an R-step)

| ID | Change | Why proposed | What changes | Evidence | Gate |
|---|---|---|---|---|---|
| BC-1 | Consolidate the 6 atomic writers into one helper with uniform `mkstemp` + file + dir fsync | Durability is inconsistent today | `nbp_derived_store.py:296,355` ([V] fixed `.tmp`, no fsync) and `scored_trial_store.py` become slower and safer; tmp naming changes | S4a C2 | Trading-reliability peer |
| BC-2 | Replace KV + manifest-over-KV (`gaps.py:636`, `product_index.py:347-409`) with scan-capable SQLite tables | Manifests fake a scan | On-disk live gate-state format; needs dual-read migration | S4a C2, F | Ruling-level; last |
| BC-3 | Remove the five dead shells + `forecast_edge`/`resting_ladder`/`strike_ladder` and their tests; then prune `weather_common` modules left with zero importers | 6,571 LOC; non-uniform `allow_short` pin; ~400 duplicated shell LOC disappear with them (no base-class extraction needed, S2 F) | Test-surface change. `strike_ladder` hosts contract `test_multi_instrument_weather_strategy.py`, which needs a replacement host (e.g. `harness_probe.py`) or an explicit retirement. Tag the pre-removal commit so ruling citations of `run_weather_strategy_backtests.py` stay reproducible | S2 A, F; [V] | Requires R2.3. Confirm the 09-20 mapping for three families (S2 G6). PROGRESS:41 binds settlement and PREREG edits |
| BC-4 | Remove or park the NBS chain + `archive_records.py` + `archived_selection.py` | No caller (about 1,091 LOC) | 3 test files; forbidden-contract rows in pyproject | S4a C3, G1-G2 | Owner confirms parked vs dead |
| BC-5 | Remove empty `features/` | Placeholder | Layer contract (`pyproject.toml:96` row "features \| settlement") + `test_test_safety_tooling_config.py:133` | S4a D | L-54 review |
| BC-6 | Archive (never delete) retired scripts: `live_family_tally.py`, `k1_kalshi_prior.py`, `aud07_m1c_*`, plan-only probes; delete candidates `iem_asos1min_backfill.py` and 109 untracked `.pyc` | Clarity | Ruling RULING_R5 says "stay in repo, unedited", which forbids deletion | S4b F | **Audit conflict, resolved:** S2's "no deletion ban" applies to strategy packages; S4b's ban applies to the scripts the rulings name. Both stand. |
| BC-7 | Remove the `ts_init` nudge (`nws_actor.py:1436-1437`) via a different partitioning key | A storage quirk mutates a provenance timestamp | Replay/catalog semantics | S4a §B, G7 | Ruling |
| BC-8 | Re-enable native in-flight, open-check or position-check; Redis `CacheConfig.database` | — | False FAILED without a client order id; changes the recovery domain | S1b B3-B4, flagged list | **Not recommended** |
| BC-9 | Any fold of the fee functions, book walks or `margin`/`scoring.margin` | Duplication | Rounding, partial-fill and `n_cell` gate semantics | S2 B4-B7 | **Not recommended** |
| BC-10 | Script θ constants → dated `taker_fee_coefficient_as_of` | Two sources of truth (C10) | PREREG kill-clock outputs | S4b D | Ruling |
| BC-11 | Native WebSocket reconnect; `ed25519_signature` swap; `StreamingFeatherWriter` for observations | Native-first | Auth outage risk; loses raw payload and byte cap | S1a F; S4a 10 | Each needs a probe or parity evidence first |
| BC-12 | Mark superseded records, or drop the vacuous leg of `is_settlement_grade` | B-6 | Settlement selection | S5a B-6 | Ruling |
| BC-13 | Replace 3 of the 4 `os.fork()` tests with a process double | Fork DeprecationWarning; burden | Test-only, but it reduces real-OS adopt coverage | S3 D, F | Test-engineering peer. Proceed only after CT-2 lands |

---

## 4. Testing strategy and measurable success criteria

### 4.1 Tiers organized by application-owned risk

All tiers run through `scripts/ci/run_tests_no_egress.sh [pytest args…]` ([V] usage line 19).
- An unsandboxed `pytest` aborts at barrier N2 before collection (S3 header; `conftest.py:359-380`).
- Exporting the attestation without the namespace is refused by N3.

**The `-m` override trap.** `addopts` already carries `-m 'not live and not venue_live and not real_money'` ([V] `pyproject.toml:49`). A CLI `-m` **replaces** it; it is not combined. Every tier expression must therefore restate all three exclusions. (Standard pytest behaviour; S3 marks it HYPOTHESIS, so it is verified in §4.5 item 2.)

| Tier | Owns which risk | Command (`$G` = `scripts/ci/run_tests_no_egress.sh`) | When |
|---|---|---|---|
| T1 fast unit | Custom decision logic: ledger, permit, latch, drift refusal, fee, PREREG statistic, normalize/settlement predicates | `$G -m "not live and not venue_live and not real_money and not contract and not heavy" tests/unit tests/strategy` (`heavy` after R0.7 + Rev 2 marks) | Every commit on a worktree |
| T2 contract | Nautilus-boundary pins (cache durability, catalog interval, risk ordering, expiry absence, timer affinity, streaming, settlement-price hazard, native cap wiring) | `$G -m "contract and not live and not venue_live and not real_money"` (complete after R0.3; until then also `$G tests/contract`) | Every step touching an adapter, runtime, ingest or persistence boundary; first on any Nautilus bump |
| T3 deterministic e2e | Composed behaviour across layers | `$G tests/integration tests/contract/test_account_presence_halt_contract.py tests/contract/test_exec_client_reconciliation_contract.py tests/contract/test_trade_node_lifecycle_contract.py tests/contract/test_node_composition_contract.py tests/contract/test_backtest_harness_stop_gate.py` | Every LIVE step |
| T4 full gate | Everything | `$G` (no args) | Every step before merge, and on the integration branch after every merge (L-43) |
| Static | Layering, typing | `lint-imports`; mypy ratchet (inside T4 via `test_mypy_ratchet.py`); ruff (CI only, ENG-08) | Every step |

**T3 composition (CONFIRMED by S3 B and S4a E docstrings).** Integration tests that qualify:
- `test_ingest_crash_between_mark_and_persist.py`
- `test_runtime_restart_resume.py`
- `test_runtime_lifecycle_smoke.py`

Plus the five real-engine contract hosts listed in the command.

`test_forecast_edge_backtest.py` and `test_resting_ladder_backtest.py` exercise dead strategies and leave with BC-3. No e2e test exists for the AMBIGUOUS path through the public port; CT-1 fills that gap.

### 4.2 Pins to keep, retain as-is (S3 B, E "Strong")

| Group | Pins |
|---|---|
| Egress firewall | N1/N2/N3 and the conftest abort |
| Signing | B2 non-GET raise (`test_polymarket_us_signing.py:266`) |
| Backtest guard | `BacktestOrderGuard` refusal table (`:169-341`) |
| Short selling | `allow_short=True` construction refusal (`tests/strategy/*/test_config.py:43`) |
| Caps | Native cap wiring + risk-engine ordering |
| Settlement | PRELIMINARY/FINAL classify; H0 closed form (`test_multi_position_validation_2026_09_14.py:302`); `test_prereg_v1_is_byte_unmodified.py` |
| Nautilus boundary | Catalog, cache, expiry, streaming, settlement-price and timer-affinity contract pins |
| Drift | `SchemaDriftError`; per-surface drift allowlists |

### 4.3 Tests to replace, consolidate or remove, and how protection is kept

**Rule.** The behavioural replacement lands first and is green. The private assertion is deleted in the **same commit**, never earlier. No safety, contract, settlement or NO-SEND test loses an assertion without an equal-or-stronger public one.

| S3 C # | Site | Replacement (public outcome) | Prerequisite |
|---|---|---|---|
| 1, 2 | `test_current_rung_hold_ambiguous_resolver.py:296,300` | CT-1 (one submit, OPEN intent, no second POST) | R0.5 |
| 3, 4 | `test_continuous_rung_hold_fill_wiring.py:579,2277` | Persisted trial row holds the decision ask; fill-row fee = cumulative fee / qty | — |
| 5 | `test_polymarket_us_exec_client.py:1081` | A later order is accepted once the refusal clears | — |
| 6, 7 | `test_polymarket_us_startup_evidence.py:480-481` | One position event; a repeat read emits nothing; emitted long set equals the read | — |
| 8 | `test_continuous_rung_hold_strategy.py:476` | Hunt tick submits nothing while the fee is unverified | — |
| 9, 10, 11 | `test_current_rung_hold_composition.py:282,800,1367` | Subscribed and ordered station set; exit decision checked on the order; node station set (not log text) | — |
| 12 | `test_app_trade_fee_drift_probe_wiring.py:142` | Delete only; the agree/no-halt test that follows already covers it | — |
| 13 | `test_archive_cache.py:151` | A second `get_or_fetch` does not call the fetch | — |
| 14 | `test_polymarket_us_submit_order_chain.py:1933` | Delete only (`:1930-1932` pin kind and fee) | — |
| 15 | `test_sl13c_d_plus_1_resolution.py:257` | Subscribes and submits nothing until resolution | — |

Other changes:
- **`os.fork()` ×4** (`test_trade_supervisor.py:2554,2735,2748,2762`): keep one real fork; replace three with the CT-2 process double (BC-13).
- **Duplicate fixtures:** move `store_path` (18 files), `interior_instrument` (12) and `tally_mod` (10) into `tests/support/`. Store fixtures write through the real writer (L-42).
  - `_operator_order_ceiling` (8 files) names an operator-reserved control. Move it only if the L-39 census (`test_operator_control_assignment_scan.py`) still passes. Otherwise leave it.
- **Large files:** split `test_trade_supervisor.py` (7,026) and `test_current_rung_hold_ambiguous_resolver.py` (6,989; 118 private asserts) along public-outcome lines **after** CT-1/CT-2, as moves only.

### 4.4 Measured baselines and projected targets

| Metric | MEASURED baseline (source) | PROJECTED target (labelled projection) |
|---|---|---|
| Full gate wall time | 22.7–25.4 min; ~20 min CPU; 1.8–2.3 GB peak (operator, six runs 2026-10-01; cited by S3, not re-measured) | ≤ baseline after Phases 0–3; −5–15% after BC-3 (HYPOTHESIS: depends on Rev 2 durations) |
| Fast tier (T1) | none exists (S3 F) | ≤ 5 min once `heavy` is applied |
| Green-log outcomes | 14,654–14,910 passes (lower bound); 11–12 skipped; 7 xfail; 3 xpass; 0 flakes on green logs (S3 D) | 0 new skips or xfails; the xpass set is reviewed (3 XPASS under strict markers is an existing anomaly to triage) |
| Test functions / LOC | 11,249 / 300,560 (S3 A) | No reduction target. Reductions come only from BC-3/BC-4 removals and §4.3 de-duplication |
| Private-attribute assert lines | 741 lines / 101 files (S3 C) | −15 worst sites (§4.3); no new private asserts in new tests |
| Unmarked contract modules | 10 (S3 B; [V] 27 of 39 marked) | 0 |
| `os.fork()` tests | 4 (S3 D) | 1 |
| Warning headers per gate | 181–205 (S3 D) | Fork DeprecationWarning gone after BC-13; others unchanged |
| `ignore_imports` debt rows | 4 ([V] `pyproject.toml:100-108`) | 3 after R1.5; 2 if R1.6 is feasible |
| Modules > 800 lines in src | ≥ 25 across S1b/S2/S4a lists | −3 (`app/trade.py`, `catalog.py`, `quote_tape_ingest_cli.py` under 800) after Phase 3; `exec/client.py` and `continuous_strategy.py` reduced, not under 800 |
| `scripts/` private `breezy` imports | 13 scripts (S4b) | Tripwired (R0.6); ≤ 5 after R2.4 if adopted |
| Collected item count | unknown; collection is blocked outside the namespace (S3 G1) | Recorded in Rev 2 |

### 4.5 Gate procedure for the refactor

1. **Worktree and interpreter.**
   - One gate at a time per tree; never in `/home/jon/breezy`, because gate tests rewrite `src` in place (ENG-20).
   - `PYTHONPATH=<wt>/src`; interpreter `/home/jon/breezy/.venv/bin/python` via `BREEZY_PYTHON`.
   - Under `systemd-run`, pass `-p LimitNOFILE=524288` and keep basetemp on `~/.cache` (memory).
2. **One-time check of the `-m` override.** Run `$G --collect-only -q -m "not live and not venue_live and not real_money and not contract"` and confirm no `live`-marked item is collected. Record the collected count for §4.4.
3. **Ratchet.** Re-baseline only in a dedicated commit with the before/after counts in the message. Rebase on CF-12 W2 (`4b0b4f6`) if it merges first.
4. **Tier selection.** LIVE steps run T1 → T2 → T3 → T4. Others run T1 → T4.

### 4.6 Slow-tail placeholder (to be filled in Rev 2 from the in-progress per-test durations run)

| Rank | Test node id | Duration (s) | Engine/fork/subprocess? | Proposed tier (`heavy`?) |
|---|---|---|---|---|
| 1–20 | *pending `--durations` run (transient unit `breezy-gate-refactor-dur`, S4b E)* | — | — | — |

Candidates to check (HYPOTHESIS, S3 D):
- the ten largest test files
- `test_backtest_harness_stop_gate.py`
- `test_multi_instrument_weather_strategy.py`
- `test_backtest_run_refusals.py`
- `test_trade_supervisor.py`

---

## 5. Peer review (placeholder)

This Rev 1 plan has not yet been reviewed. Four independent reviews follow. Their findings, required revisions and blockers will be appended here in Rev 2, together with the durations table in §4.6:
- **Nautilus architecture:** confirm the §1.2 non-substitution table and the extension points.
- **Trading reliability:** live-path steps R1.1, R1.2, R3.1, R3.2, R3.4 and R3.5; the merge-window rule; C10 and C12; the FQ missing-stop finding.
- **Test engineering:** the tiers, the `-m` trap, the `heavy` marker, §4.3 replacements, BC-13.
- **Maintainability:** step granularity, the R2.1 / R2.4 / R3.5 review questions, BC-3 sequencing.

Open questions already routed to review:
- R2.1: which boundary-solver copy is the source of truth.
- R2.4: keep or drop.
- R3.5: value versus order-path risk.
- BC-3: replacement host for the contract test that runs on `strike_ladder`.
- BC-4: is the NBS chain parked or dead.
- R1.6: is it feasible at all.