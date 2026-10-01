I'll gather read-only evidence on the runtime seam against Nautilus 1.231.0, starting with the project skill and the installed extension points, and I won't change any files.The runtime tree is present, but `safety.py` and `operator_controls.py` are not in that listing. I'll locate them and map each module against the Nautilus 1.231.0 extension points.## Runtime seam vs Nautilus 1.231.0

Verified `nautilus_trader.__version__ == 1.231.0` from `/home/jon/breezy/.venv`. Seam size: `src/breezy/runtime/` + `src/breezy/app/` = **42 modules, 21,139 lines**. Codegraph `codegraph_explore` failed twice (`attempt to write a readonly database`); citations are direct reads of this worktree and the installed package. No tests were run. No files were changed.

`safety.py` and `operator_controls.py` are **not** under `runtime/`. They live at `src/breezy/adapters/polymarket_us/safety.py` (1,046 lines) and `operator_controls.py` (523). Runtime reaches them by deferred or direct import (`node_config.py:689`, `order_enablement.py:49-53`). **CONFIRMED.**

Nautilus owns the process shell inside one node. Breezy owns everything whose semantics Nautilus cannot express: two operator caps, a day boundary, a permit, a one-intent latch, a host-lifetime supervisor, and refusals that the framework's own checks fail open.

## (A) Ownership table

Legend: **CLEAR** = Nautilus owns it and Breezy only configures it, or Breezy owns it because Nautilus has no equivalent. **EXTENDS** = native object plus a Breezy condition Nautilus does not apply. **UNCLEAR** = name overlap, substitution not proven.

| Module (lines) | Mark | Nautilus already owns | Breezy must hand-author |
|---|---|---|---|
| `node_config.py` (973) | EXTENDS | `TradingNodeConfig` (`live/config.py:284-313`), `LiveExecEngineConfig` (`:81-201`), `LiveRiskEngineConfig`→`RiskEngineConfig` (`risk/config.py:21-45`), `CacheConfig` (`cache/config.py:23-74`), `LoggingConfig` (`common/config.py:617`), `StreamingConfig` (`persistence/config.py:28-73`), `ParquetDataCatalog` | Three role configs. Trade node: `strategies=[]`, `exec_algorithms=[]`, `message_bus=None`, `cache.database=None`, `inflight_check_interval_ms=0` (`node_config.py:958-971`). Notional map + `"5/00:00:01"` (`:642-706`). |
| `trade_cli.py` (795), `cli.py` (199), `quote_tape_cli.py` (287), `composition.py` (496), `app/trade.py` (1,099) | EXTENDS | `TradingNode` build/run; `Trader.add_actor` (`trading/trader.py:312` via `live/node.py:139`); `Actor` lifecycle. `ActorFactory.create` cannot build `NwsIngestActor` (needs a live object) (`node_config.py:127-134`) | Composition roots, factory registration, permit mint, fee-drift actor wiring (`app/trade.py:339-463`). |
| `trade_supervisor.py` (2,893) + `trade_supervisor_core.py` (1,850) | CLEAR (Breezy) | Nothing. `TradingNode` is one process, not a day supervisor | `spawn_node` `start_new_session=True` (`trade_supervisor.py:839-867`); 16:40/17:05/mid-day decisions; adopt (`self_check`, `trade_supervisor_core.py:622-689`). |
| `settings.py` (902) | CLEAR (Breezy) | `NautilusConfig` is msgspec, frozen, no env (`common/config.py:241`) | Pre-kernel env mapping. Module imports no Nautilus (`settings.py:7-9`). |
| `safety.py` + `operator_controls.py` (adapters) | CLEAR (Breezy) | No day budget, no position-cost cap, no permit. `RiskEngineConfig` fields are `bypass`, two rates, `max_notional_per_order: dict[str,int]`, `debug` (`risk/config.py:41-45`). No class `RiskLimits` anywhere in the install | `DailySpendLedger.authorize_order_cost` (`operator_controls.py:348-427`). `issue_live_trading_permit`, `PERMIT_TTL_NS` = 10 h (`safety.py:172`). Session ceilings derived at mint (`safety.py:582-625`). |
| `order_enablement.py` (234) | EXTENDS | None | Second minted permit that checks the live permit plus both caps (`:176-234`). |
| `submit_intent.py` (596) | CLEAR (Breezy) | Submit throttler is a rate, not a mutex (`risk/engine.pyx:142-152`) | One OPEN intent, flock, durable history (`:316-596`). `RetirementReason` includes AMBIGUOUS resolutions (`:73-93`). |
| `sqlite_store.py` (193), `exec_state_db_path.py` (218) | CLEAR (Breezy) | `Cache.add` writes Redis only if `_database is not None` (`cache/cache.pyx:1704-1708`); `get` is memory-only (`:2853`). Kernel accepts only `database.type == "redis"` (`system/kernel.py:310-329`); adapter constructs `RedisCacheDatabase` (`cache/database.pyx:162-166`) | SQLite `StateStore`, WAL, commit-before-return. |
| `account_presence_halt.py` (214) | EXTENDS | `RiskEngine.set_trading_state` / `TradingState.HALTED` denies in `_execution_gateway` (`risk/engine.pyx:1133-1143`). Missing account returns **allowed** (`:684-689`) | The condition: `OrderInitialized` with no cached account → `set_trading_state(HALTED)`, never self-clears (`account_presence_halt.py:144-174`). |
| `backtest_order_guard.py` (615) | CLEAR (Breezy) | Cash SELL `balance_impact` is **+notional** (`accounting/accounts/cash.pyx:489-493`); free-balance check is `(free + impact) < 0` (`risk/engine.pyx:949`); reduce-only exemption (`:979-982`) does not catch a naked sell | Post-only and naked-short refusal at `OrderInitialized`. |
| `backtest_harness.py` (1,058), `backtest_feed.py` (172), `paper_replay.py` (446), `point_in_time_guard.py` (80) | EXTENDS | `BacktestEngine` / `add_venue` / `add_data` / `run`. `BinaryOption` is not in `ENGINE_EXPIRING_INSTRUMENT_CLASSES` (`model/instruments/base.pyx:67-72`). `check_instrument_expiration` (`backtest/engine.pyx:5934`) | Settlement invariants, `CustomData` wrap, look-ahead on `ts_init`. No `BacktestNode` / `BacktestDataConfig` in this seam (those live under ingest/persistence). |
| `quote_tape_*.py` (ingest CLI 2,441) | EXTENDS | `StreamingConfig` on the recorder (`node_config.py:606-614`). `ParquetDataCatalog.convert_stream_to_data` (`parquet.py:2604`); same-name skip is a bare `print` | Bounded feather read, truncation refusal, idempotency around the silent skip. |
| `health.py` (830), `alert_ladder.py` (237), `component_health_watch.py` (702), `study_failure_notifier.py` (290), `check_alerts_cli.py` (175) | CLEAR (Breezy) | `Component.degrade()` publishes `ComponentStateChanged` (`common/component.pyx:2098-2127`). `MessageBusConfig.heartbeat_interval_secs` (`common/config.py:463-480`) has **no** `.py`/`.pyx` consumer except the field itself | Webhook/log alerts, streak ladder, stale-AMBIGUOUS CRITICAL (`component_health_watch.py:126-137`). Trade node sets `message_bus=None`, so the bus heartbeat cannot run. |
| `logging_bridge.py` (164) | EXTENDS | `LoggingConfig` + `Logger` (`component.pyx:1425-1530`). No CRITICAL level. Pre-`init_logging` calls no-op (`:1450`) | Stdlib `breezy.*` → `Logger`. L-27: this logger is process-global. |
| `stop_intent_marker.py`, `bootstrap_witness.py`, `structural_pin_guard.py`, `exit_control_precondition.py`, `ingest_deadline.py`, `ingest_deferral_streak.py`, `build_sha.py`, CLIs | CLEAR (Breezy) | No equivalents found | Ops markers, family-halt precondition, ingest deadlines. |

`LiveExecEngineConfig` defaults that the trade node does **not** override, so they stay on: `reconciliation=True` (`live/config.py:177`). Explicitly off: in-flight (`interval_ms=0` skips the loop, `live/execution_engine.py:383-387` and `:574-575`). Left at default `None`, so also off: `open_check_interval_secs`, `position_check_interval_secs` (`live/config.py:188,195`). **CONFIRMED.**

`ExecAlgorithm` is unused on purpose: empty literal because it has its own `submit_order` (`node_config.py:793-797`). **CONFIRMED.**

Fee-schedule drift is not a runtime module. `app/trade.py:339-463` constructs `FeeDriftProbeActor` and calls `record_policy_halt` with reason `fee_schedule_drift`. Venue execution-snapshot drift lives under `adapters/polymarket_us/exec/`, outside this seam. **CONFIRMED.**

## (B) Duplication candidates

Ranked by lines you could delete times confidence that behaviour would survive. The top of the list is "do not substitute."

| Rank | Breezy | Nautilus | Behavioural difference | Substitution risk | Save |
|---|---|---|---|---|---|
| 1 | `DailySpendLedger` (`operator_controls.py:264-427`), ~260 lines of logic | `RiskEngine._check_orders_risk_for_account` notional (`risk/engine.pyx:674-679`, deny `:912-917`) and `Throttler` (`:142-152`) | Ledger is UTC-day USD, `Decimal`, price×qty rounded **up** to the cent, both caps read before either applies, clock rewind refused. `max_notional_per_order` is **per order, per instrument id, `int` dollars**, and is **inert when no account is cached** (`:684-689` returns `True`). No day key. `Portfolio` has no position-cost cap (no `max_position` in `portfolio.pyx`). | **Does not preserve semantics.** A notional cap cannot stand in for a daily budget or a per-position cost. | 0. **CONFIRMED** |
| 2 | `SubmitIntentLatch` (596) | `max_order_submit_rate` `"5/00:00:01"` already set (`node_config.py:642-706`) | Latch is one OPEN intent per process, durable across the store. Throttler drops the 6th command inside one second and still allows many in flight. Docstring says the native rate cannot bind behind the latch. | Replacing the latch with the throttler removes the double-send mutex. | 0. **CONFIRMED** |
| 3 | In-flight pin `interval_ms=0` plus AMBIGUOUS resolver (resolver body is `exec/client.py`, not this seam) | `_check_inflight_orders` queries by `client_order_id`, then `_resolve_inflight_order` as **failed** after retries (`live/execution_engine.py:701-760`) | Polymarket.us has no client-order id. A false FAILED is a path to a doubled position (`node_config.py:820-845`). Startup `reconciliation=True` remains. | Turning in-flight back on is a behaviour change, not a simplification. | 0. **CONFIRMED** |
| 4 | `SqliteStateStore` (193) | `Cache` + `CacheDatabase` | Durable only with Redis. This deploy sets `database=None` (`node_config.py:962`; `kernel.py:310-311`). `on_save`/`on_load` need that database (skill trap 9; not re-executed here). | Adding Redis to delete 193 lines changes the recovery domain. | 0. **CONFIRMED** |
| 5 | `health.py` + watches (~1,500) | `MessageBusConfig.heartbeat_interval_secs` | Field is unused in the Python/Cython tree. Trade node passes `message_bus=None`. Breezy alerts are webhook/journal CRITICAL with dedupe, not a bus ping. | No drop-in. | 0. **CONFIRMED** field has no Python consumer; **HYPOTHESIS** that Rust would emit one if Redis were configured. |
| 6 | `logging_bridge.py` (164) | `LoggingConfig` | Two loggers. Bridge maps CRITICAL→`Logger.error`. Records before `init_logging` are discarded (`component.pyx:1450`). | Removing the bridge hides `logger.critical` from the node log. | 0. **CONFIRMED** |
| 7 | `backtest_harness.py` settlement block | `BacktestEngine.check_instrument_expiration` | `BinaryOption` never takes the time-expiry path (`base.pyx:67-72`). Unset `settlement_prices` falls through to the book (`engine.pyx:5934` area; harness docstring). | Switching the harness to `BacktestNode` does not delete the guards. | Low. **CONFIRMED** class set; book-fill path **HYPOTHESIS** beyond the docstring's cite (line 5934 is the expiration entry, not the price branch). |
| 8 | Quote-tape ingest mirror `_convert_stream_natively` (`quote_tape_ingest_cli.py:809`, functions of 177 and 162 lines) | `ParquetDataCatalog.convert_stream_to_data` (`parquet.py:2604`) | Mirror exists to avoid `read_all()` RSS, then still calls native `_convert_feather_table_to_parquet`. Same-name skip stays a bare `print`. | Deleting the mirror reintroduces the memory failure the module exists to avoid. | **HYPOTHESIS** tens of lines of bookkeeping, not the 2,441. |
| 9 | `health.py:422` SSL context | `breezy.ingest.http._build_ssl_context` | Comment says deliberate duplicate so `health` does not import `HttpTransport`. | Real, tiny, layer-driven. | ~15 lines. **CONFIRMED** comment. |

Already-correct native use, not duplication: `build_trade_risk_engine_config` (`node_config.py:645-707`) fills `max_notional_per_order` from `operator_max_order_notional_whole_usd()` (integer floor). Markets discovered after boot are **not** in the map (`:664-672`). The Decimal chokepoint stays `authorize_live_order_submission`. **CONFIRMED.**

## (C) Abstraction and coupling

**Parallel config, not a wrapper stack.** `settings.py` (902, no Nautilus) parses env into `BreezyRuntimeSettings` / `BreezyTradeSettings` / `PolymarketUSQuoteTapeSettings`. `node_config.py` maps those onto msgspec `TradingNodeConfig`. Secrets-in-factory is the Nautilus rule; this split matches it. Collapsing them would put env reads inside frozen kernel config. **CONFIRMED.**

**Import-linter** (`pyproject.toml`, 7 contracts). Layers: `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > …`. `ignore_imports` rows that name this seam (upward, not cycles):

- `breezy.adapters.polymarket_us.config -> breezy.runtime.settings`
- `breezy.adapters.polymarket_us.factories -> breezy.runtime.settings`
- `breezy.ingest.nws_actor -> breezy.runtime.health`

Historical cycle: `composition` → `node_config` → adapter config → `runtime.settings`, while `runtime/__init__.py` eagerly imported `composition`. `__init__` is now import-free; the `TYPE_CHECKING` guard remains (`node_config.py:105-122`). **CONFIRMED.**

**Nine one-implementation Protocols** in runtime: `StateStore` (`submit_intent.py:43`, duplicates `gate.StateStore` on purpose), `AlertSink`, `SettingsLike`, `ClockLike`, `SupportsNautilusLog`, and three `Node` protocols (`cli.py:90`, `quote_tape_cli.py:123`, `trade_cli.py:253`). **CONFIRMED.**

**Five `TradingNode` composition sites:** `app/trade.py`, `trade_cli.py`, `cli.py`, `quote_tape_cli.py`, `composition.py`. Three builders in `node_config`: ingest, quote tape, trade. **CONFIRMED** by import scan.

**Modules > 800 lines:** `trade_supervisor.py` 2,893; `quote_tape_ingest_cli.py` 2,441; `trade_supervisor_core.py` 1,850; `app/trade.py` 1,099; `backtest_harness.py` 1,058; `node_config.py` 973; `settings.py` 902; `health.py` 830.

**Functions > 50 lines that dominate maintenance** (span, not body): `app/trade.py:run` 476; `_build_fee_drift_probe` 145; `main` 136. `trade_supervisor.py`: `_do_self_check` 228, `_do_midday_watch` 215, `_run_forever` 194, `_do_launch` 93. `quote_tape_ingest_cli.py`: `_convert_one_tick_type_per_file` 177, `_ingest_instance_per_file` 162, `run_ingest` 154, `run` 142. `node_config.py:build_trade_node_config` 221 (much of that is the pin comment). `component_health_watch.py:install_refusal_repoll_timer` 136. `backtest_harness.py:build_backtest_engine` 133. **CONFIRMED** via AST end-line spans.

Layer count on the live order path: settings → permit mint (`safety`) → `OrderSubmissionPermit` → `SubmitIntentLatch` → exec client (adapter) → `RiskEngine` → venue. That is four Breezy gates before the native engine. They are not interchangeable. **CONFIRMED** from the call shape; the exec-client body was not fully read.

## (D) State and recovery invariants

| Invariant | Where | Pinning tests (names only; not executed) |
|---|---|---|
| Two operator caps, no default, absence refuses. `authorize_order_cost` reads both before applying either (`operator_controls.py:382-392`) | `operator_controls.py`, `operator.env` (gitignored; not opened) | `tests/unit/test_operator_reserved_controls.py`, `test_operator_caps_through_the_live_composition.py`, `test_operator_control_assignment_scan.py`, `test_fq_caps_and_ambiguous_2026_10_01.py` |
| Ledger is **in-memory**. Restart forgets spend unless `seed_spent` runs once (`operator_controls.py:271-334`). Second `_connect` must not double-book | same | `test_operator_reserved_controls.py` (`seed_spent`) |
| Permit TTL 10 h (`safety.py:172`). Mid-day relaunch clamps to the first boot's expiry via `BREEZY_PERMIT_EXPIRY_CEILING_NS` (`trade_supervisor_core.py:122-128`). That is **A-1**, a ceiling, not a halt flag | `safety.py`, `app/trade.py` mint, supervisor | `test_polymarket_us_permit_issuance.py` (`test_the_permit_ttl_is_pinned_to_ten_hours`), `test_runtime_order_guard_permit_expiry.py`, `test_app_trade_main_permit_logging.py`, `test_trade_supervisor.py` |
| One OPEN submit intent. Corrupt singleton fails closed. AMBIGUOUS retirement is a distinct reason, not "accepted" (`submit_intent.py:73-93`) | latch + SQLite | `test_submit_intent_latch.py`, `test_clear_submit_intent_cli.py`, `test_current_rung_hold_ambiguous_resolver.py`, `test_polymarket_us_exec_client.py` (`STARTUP_FILL`) |
| Boot with an unresolved AMBIGUOUS intent stays unresolved until a bounded GET; stale age pages CRITICAL `open_intent_stale` (`component_health_watch.py:126-137`). Resolver implementation is the exec client, not runtime | runtime wires loader (`node_config.py:710-750`) and the alert | `test_component_health_watch_stale_intent_alert.py`, `test_no_side_boot_reconcile_2026_09_14.py`, `tests/contract/test_reconciliation_durable_reports_contract.py` |
| Account-presence halt: missing account → `TradingState.HALTED`, no resume API (`account_presence_halt.py:74-79,171`) | risk engine state | `tests/contract/test_account_presence_halt_contract.py`, `tests/contract/test_risk_engine_ordering_enforcement.py` (fail-open pin; cited, not opened) |
| Continuous family halt is a SQLite flag the supervisor refuses to adopt through (`trade_supervisor_core.py:687-688`) | `SqliteStateStore` | `test_trade_supervisor_cont_self_check.py`, `test_edge3_per_family_halt.py`, `test_aud07_exit_control_halt_precondition.py` |
| Nautilus cache does not survive restart here (`database=None`) | `node_config.py:847-850,962` | `tests/contract/test_nautilus_cache_durability_contract.py` (cited by `sqlite_store.py:7`) |
| Supervisor death must not SIGTERM the node. `KillMode=process` (`deploy/systemd/breezy-trade-supervisor.service:151-168`). Child is a new session (`trade_supervisor.py:863`) but **stays in the unit cgroup** | systemd unit in-repo; live unit not touched | No test file contains the string `KillMode`. Adoption behaviour: `test_trade_supervisor.py`, `test_trade_supervisor_core.py` (`PASS_ADOPTED_LOG_UNKNOWN` at `trade_supervisor_core.py:640-675`) |
| Adopt without a readable log is `PASS_ADOPTED_LOG_UNKNOWN`, not a silent `PASS` (`:674-675`). Shadow mode (alive, subscribed, no valid permit) is `FAIL_SHADOW_MODE_NO_PERMIT` (`:678-681`) | core | `test_trade_supervisor_core.py` |
| L-16: a raise inside a `LiveClock` timer callback is discarded (Rust dispatch; Python wrapper at `common/component.pyx:1006-1010` has no `try`). `component_health_watch.py` timers must record their own alert, not rely on the raise | installed clock + lesson `docs/core/LESSONS.md:772-811` | Lesson records a direct repro on 1.231.0. **CONFIRMED** as a lesson plus the wrapper; the Rust swallow site is not in the Python tree. |
| L-26: a node launched inside the coordinator cgroup dies with the session. Launch is `systemd-run --user` or this supervisor, not `nohup` from the agent | `docs/core/LESSONS.md:1121-1150` | Runbook/lesson, not a unit test. **CONFIRMED** text. |
| L-27: supervisor `main()` opens a HOME log; tests must redirect `Path.home()` | `docs/core/LESSONS.md:1160-1178` | Lesson names the pollution incident. **CONFIRMED** text. |
| In-flight check stays off | `node_config.py:970` | `tests/unit/test_runtime_trade_node_config.py`, `tests/contract/test_trade_node_lifecycle_contract.py`, `test_native_order_cap_wiring.py` |
| Catalog same-range rewrite skips with a `print` (skill trap 1). Ingest must not "correct" by rewriting the same `ts_init` range | `parquet.py` as cited by `quote_tape_ingest_cli.py:1-40` | `tests/contract/test_quote_tape_ingest_native_pin.py`, `test_catalog_write_interval_contract.py` |

**Flagged behaviour changes (do not fold into a refactor):** re-enabling `inflight_check`; pointing `CacheConfig.database` at Redis; replacing `Decimal` day spend with `max_notional_per_order`; treating `PASS_ADOPTED_LOG_UNKNOWN` as `PASS`; letting account-presence halt clear itself; minting a fresh 10 h permit on mid-day relaunch; switching supervisor stop to cgroup kill.

## (E) Dispositions

| Subsystem | Disposition | Why | Extension point | Migration risk |
|---|---|---|---|---|
| `TradingNode` / three `node_config` builders | **Retain** | Kernel already builds engines (`node_config.py:772-776`). Breezy only maps settings and states the empty strategy/exec-algorithm cage | `TradingNodeConfig`, factories | Low if the empty literals and `inflight_check_interval_ms=0` stay explicit |
| `settings.py` | **Retain** | Pre-Nautilus env boundary. Not a second kernel config | None; do not push env into `NautilusConfig` | Medium if merged into msgspec structs (testability, forbid-unknown) |
| Permit + `DailySpendLedger` + `OrderSubmissionPermit` | **Retain** both caps; **simplify** only the double permit object if a design can keep the layer direction | Day budget and per-position cost do not exist on `RiskEngine`. Session ceilings are derived at mint, not stored as operator knobs | `RiskEngine` is defense in depth for whole-USD per order only | High. Any merge that drops `Decimal` cents or the day roll changes money |
| `SubmitIntentLatch` + SQLite | **Retain** | Rate limit ≠ one outstanding create. Boot AMBIGUOUS handling depends on the durable singleton | None on `Cache` without Redis | High |
| Supervisor + `KillMode=process` | **Retain**; **simplify** by moving more pure decisions into `trade_supervisor_core` (the split already exists) | Host lifetime is not `TradingNode` | `subprocess` + systemd, outside Nautilus | High around adopt/`PASS_ADOPTED_LOG_UNKNOWN` |
| Account-presence halt | **Retain** | Only way to make the framework's fail-open dominant | `RiskEngine.set_trading_state` | High if removed before the `account is None → True` path changes upstream |
| Native notional + submit rate | **Retain** as configured | Already the extension, not a fork | `LiveRiskEngineConfig` | Medium: integer floor vs `Decimal`; slugs unknown at boot are uncovered |
| In-flight / open-check / position-check | **Retain off** for in-flight and the two `None` intervals. **Do not** "turn on reconciliation" — startup reconciliation is already on | False FAILED without a client order id | `LiveExecEngineConfig` | High if someone "fixes" 0 toward the 5,000 ms docstring |
| Backtest harness + order guard + PIT guard | **Retain** guards; harness stays a composition root over `BacktestEngine` | Settlement and naked shorts are silent in 1.231.0 | `BacktestEngine.add_data` (must wrap `CustomData`; skill trap 3) | Medium |
| Quote-tape recorder | **Retain** `StreamingConfig` | Native streaming | `StreamingConfig` | Low |
| Quote-tape ingest | **Simplify** structure, **do not replace** with a raw `write_data` loop | Native convert exists; the module is the trap-handler (silent skip, RSS, live file) | `ParquetDataCatalog.convert_stream_to_data` | High if idempotency is "fixed" by same-range rewrite |
| Health / alerts / ladder | **Retain** | Bus heartbeat is not a substitute | `MessageBus.subscribe` for `ComponentStateChanged` only | Medium (L-16: timer callbacks must write their own record) |
| `logging_bridge` | **Retain** | Gap is real | `Logger` public methods | Low; do not attach to the root logger (L-27) |
| Nine Protocols, three `Node` aliases | **Consolidate** the three `Node` protocols only | One-implementation aliases | — | Low |
| `health` SSL copy | **Consolidate** only if the layer rule allows a tiny shared helper that does not import `HttpTransport` | Stated duplicate | — | Low |
| Fee-drift wiring in `app/trade.py` | **Retain** the actor; the 476-line `run` is the maintenance target, not a Nautilus gap | Probe is strategy-layer | `Actor` | Medium |
| NO-SEND / egress firewall | **Retain**, but it is mostly **not this seam** | CI firewall is `tests/unit/test_execution_egress_firewall_guard.py`. Runtime's cage is `strategies=[]` / `exec_algorithms=[]` plus "exec/ must not import `health`" (`component_health_watch.py` docstring) | — | High if the empty cage becomes a default |

No proposed behaviour change is recommended. The simplest ownership boundary: **Nautilus owns one running node (engines, bus, clock, catalog, backtest engine). Breezy owns money caps, the permit, the intent latch, the SQLite state file, the supervisor, and every refusal the framework fails open.**

## (F) Open questions

- **CONFIRMED gap:** `MessageBusConfig.heartbeat_interval_secs` has no consumer in the installed `.py`/`.pyx` tree. Whether the Rust Redis backing reads it was not verified. Irrelevant while `message_bus=None`.
- **CONFIRMED:** `DailySpendLedger`'s docstring names `RiskLimits` (`operator_controls.py:267`). That type is **absent** in 1.231.0. The conclusion (no day dimension) is still true of `RiskEngineConfig`'s actual fields. The name is stale.
- **HYPOTHESIS:** exact book price used when `settlement_prices` is missing. Harness claims `fill_market_order` (`backtest_harness.py:27-29`). `engine.pyx:5934` is the expiration entry; the fall-through line was not read.
- **Not in this seam, so not dispositioned:** AMBIGUOUS GET resolver, exec-report stores, and snapshot-drift refusals (`adapters/polymarket_us/exec/client.py`). Runtime only threads the latch, the catalog instrument loader, and the stale alert.
- **A-1 vs halt:** A-1 is the mid-day permit ceiling (`trade_supervisor_core.py:122-128,658-666`). The halt flags a refactor must preserve are `TradingState.HALTED` (account presence) and the continuous family-halt SQLite key. They are different mechanisms.
- **KillMode** is pinned by the unit file comment, not by a test that contains the string `KillMode`.
- Codegraph was unavailable. A few supervisor branches inside `_do_self_check` / `_do_midday_watch` (200-line functions) were not read line by line; the pure decision function `self_check` was.
