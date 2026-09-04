# current_rung_hold shadow-mode runtime wiring brief (2026-09-04) — DRAFT, under peer review

Authored by code-architect against `74cfa7c`. Blueprint build-order item 8 (runtime), shadow mode only: `orders_enabled` stays False and unreachable from env. Open conflict for reviewers: this brief makes the composition root the sole opener of the submit-intent lock, while `R7_BUILD_BRIEF_2026-09-04.md` converged D6 has the exec client's connect path run `reconcile_at_startup` — one ownership rule must win and bind both.

## Architecture: FLAG-OFF runtime wiring of `CurrentRungHoldStrategy` (shadow mode)

### Verified ground truth (all re-read at 74cfa7c)
- `open_submit_intent_latch` (`src/breezy/runtime/submit_intent.py:508-521`) has **zero production callers** — only `tests/unit/test_submit_intent_latch.py`. **R-7 has not landed; nothing holds the flock at runtime today.**
- `hold_submit_intent_process_lock` (`submit_intent.py:481-505`) is `flock(LOCK_EX|LOCK_NB)` on a fresh fd per call → a second opener **in the same process** also gets `EWOULDBLOCK` → `SubmitIntentLockHeld`. A double-open is loud, never silent.
- `SubmitIntentLatch.shared_state_binding()` (`:443-461`) → `(store, lock)`; `open_trial_day_latch(intent_latch)` (`trial_day_latch.py:242-252`) is the only `TrialDayLatch` constructor.
- `SqliteStateStore` is `check_same_thread=True` with `_check_thread()` (`runtime/sqlite_store.py:117-137`) — **the store must be built on the thread that will call it.**
- `Trader.add_strategy` (`.venv/.../nautilus_trader/trading/trader.py:375-420`): rejects RUNNING/DISPOSED, `RuntimeError` on duplicate `strategy.id` (`:400`) **and** on duplicate `order_id_tag` (`:416`); silently no-ops if the trader is already running (`:396`).
- `build_trade_node_config` pins `strategies=[]` at `node_config.py:696` — untouched by this design.

### Design decisions
- **D1 — registration mirrors Seam B exactly.** `node.trader.add_strategy(s)` for each station inside `_run_node`, in the same loop position as `add_actor` (`trade_cli.py:354-355`), **before** `node.build()`. `build_trade_node_config` unchanged; `strategies=[]` stays an empty literal, so every existing pin asserts a non-change.
- **D2 — one flag, AND-gated.** `BREEZY_CURRENT_RUNG_HOLD=1` in the `_parse_live_observations` idiom (`settings.py:275-276`). On **without** `BREEZY_LIVE_OBSERVATIONS=1` → `SettingsError` (exit 2 via `_CONFIG_ERRORS`), message naming both variables: the strategy prices against `StationObservation` (`strategy.py:228`), so no observation publisher means it would latch `observation_unavailable` on every station-day and burn the one trial. Fail closed, at load, not at `on_start`.
- **D3 — latch ownership: the composition root owns the ONE opener, for the process lifetime.** `run()` holds `contextlib.ExitStack`; it opens `SqliteStateStore(exec_client_config.state_store_path)` and `open_submit_intent_latch(store, Path(state_store_path))` **on the main thread, before `_run_node`**, and passes the live `SubmitIntentLatch` down. `trial_day_latch_factory = lambda: open_trial_day_latch(intent_latch)` — the shared binding, never a second store, never a second `open_submit_intent_latch`. **Binding rule for R-7:** the exec client must accept this already-opened latch by injection (its `state_store_opener` at `node_config.py:684` keeps its own read/write store, but must never open a *latch*); if R-7 opens its own, the flock fires and the process dies at `_connect` — that is the intended, loud outcome, not a design to permit. Ownership stated in the module docstring of the new composition file and in `R8_OPERATOR_RUNBOOK.md` row 0.6.
- **D4 — one strategy per supported station**, `stations=(station,)`, `strategy_id=f"CurrentRungHoldStrategy-{station}"`, explicit `order_id_tag=station` (both native `StrategyConfig` fields) — satisfies both uniqueness checks at `trader.py:400,416` rather than relying on the auto-tag branch.
- **D5 — `orders_enabled` stays `False`, unreachable from env.** The composition constructs `CurrentRungHoldConfig(...)` without the field; `config.py:237-241` refuses `True`. No settings field, no parser, no env name — the L-22 shape stays unforgeable.
- **D6 — instrument discovery lives in `runtime/`, not the strategy package** (avoids `breezy.strategy → breezy.adapters` import-contract risk under `lint-imports`; `runtime/` already imports the adapter).

### Instrument resolution (per station, today's climate day)
Source: the venue **instrument definitions in the quote-tape catalog**, read UNFILTERED and filtered in Python — `quote_tape_ingest_cli.py:286-300` documents that identifier-filtered `catalog.instruments(instrument_ids=[...])` silently omits every flat-written row. Pipeline: `ParquetDataCatalog(root).instruments()` → for each, `read_weather_bucket_facts(instrument.info)` (`domain/weather_bucket_facts.py:88`) giving `settlement_station`/`climate_day`/`measure`; when `weather_facts_status` is `UNKNOWN`, fall back to the slug grammar — `instrument_id_to_slug` (`symbology.py:212`) → `parse_weather_slug` (`:474`, `_WEATHER_SLUG_RE:125`) → `WeatherSlug.climate_date`/`measure`. Keep only `measure is Measure.HIGH`, `settlement_station ∈ SUPPORTED_STATIONS` (`config.py:76`), and `climate_day == ` the station's **local-standard** date from `default_registry().climate_day_window(venue, city)` — the same registry accessor `observation_composition.py:76` uses. Catalog root: reuse `QUOTE_TAPE_CATALOG_VAR` (`settings.py:63`), newly read by `load_trade_settings` **only when the flag is on**, required and non-blank in that case. **Refuse to start when a station resolves zero ids**: `NoTradableInstrumentsError` (a `SettingsError` subclass → exit 2) whose message carries the per-station counts and the climate day, e.g. `current_rung_hold: resolved 0 instruments for 2026-09-04 (LAX=0 MDW=7 MIA=5 SFO=6); refusing to start`.

### Refusal surface in journalctl
No new channel. Each strategy owns `self.refusals` (`strategy.py:189`, `RefusalCounter`). The composition retains the four counters; `run()` drives one `RefusalAlerter` sweep **at shutdown only** (no `LiveClock` timer — L-16, blueprint §1 "LiveClock timers NATIVE, DECLINED"), through `resolve_alert_sink` (logging sink by default). Operator sees, per station component id: `OUTSIDE_DECISION_WINDOW_REFUSALS`, `OBSERVATION_UNAVAILABLE_REFUSALS`, `OBSERVATION_AMBIGUOUS_REFUSALS`, `FEE_SCHEDULE_MISMATCH_REFUSALS`, `TRIAL_DAY_CONSUMED_REFUSALS`; plus the already-shipped per-event lines `CurrentRungHoldStrategy subscribed <id>` (`strategy.py:226`) and `TAKE recorded, no submit (orders_enabled=False): …` (`:341-345`) — that last line **is** the shadow-mode signal an operator greps for.

### Barriers — file:line, OLD → NEW
| Barrier | file:line | OLD → NEW |
|---|---|---|
| trade node config | `tests/unit/test_runtime_trade_node_config.py:225` | `config.strategies == []` — **UNCHANGED**, assert explicitly as a non-change |
| trade CLI | `tests/unit/test_trade_cli.py:311`, `:812` | `node.config.strategies == []` — **UNCHANGED** |
| node config fields | `tests/unit/test_runtime_node_config.py:377` | parametrize `["strategies","exec_algorithms"]` — **UNCHANGED** |
| strategy module gate | `tests/unit/test_strategy_module_gate.py:138-148` | globs `strategy/*.py` (top level only); no new top-level strategy module → **UNCHANGED**; `lint-imports` must stay green with the composition importing `current_rung_hold` |
| operator-control scan | `tests/unit/test_operator_control_assignment_scan.py:618` | `files_naming_a_control() == {DEFINITION_MODULE}` — **UNCHANGED**; no new file may name a reserved control |
| cage constants | `tests/unit/test_cage_rule_constants_are_pinned.py:864-873` | exemption count `== 3` — **UNCHANGED** |
| egress firewall | `tests/unit/test_execution_egress_firewall_guard.py` | **UNCHANGED** — no new order coroutine; `_maybe_submit` already exists and stays unreachable |
| `_run_node` shape | `tests/unit/test_trade_cli.py` (`actors=` call-shape assertions) | widen the injected-`Node` double to accept `add_strategy`; registration-order assertion `add_actor*` → `add_actor* + add_strategy*` **before** `build()` |

### RED tests (all fail today) — `tests/unit/test_trade_cli_current_rung_hold.py` unless noted
1. flag absent → `run()` registers **zero** strategies and `node.config.strategies == []`.
2. `BREEZY_CURRENT_RUNG_HOLD=1` **without** `BREEZY_LIVE_OBSERVATIONS=1` → exit **2**, stderr names both variables, `node_factory` never called.
3. Both flags on, catalog resolves zero ids for today's climate day → exit **2**, message carries the per-station counts and the date; no node built.
4. Both flags on, catalog populated → exactly one strategy per resolved station, each registered via `trader.add_strategy` **before** `build()` (ordering asserted against the recorded call log).
5. The trial-day latch is the **shared binding**: the `TrialDayLatch` handed to every station shares one `StateStore` **object identity** and one `_HeldSubmitIntentLock` with the composition's `SubmitIntentLatch`; `open_submit_intent_latch` is called **exactly once** per run (spy-counted), and a second `open_submit_intent_latch` over the same path inside the run raises `SubmitIntentLockHeld`.
6. `orders_enabled` cannot be set from env: no env value (`"1"`, `"true"`, `BREEZY_CURRENT_RUNG_HOLD_ORDERS_ENABLED=1`) produces a config with `orders_enabled True`; and `CurrentRungHoldConfig(orders_enabled=True)` still raises `OrdersEnabledNotPermittedError`.
7. Lifecycle: after `run()` returns (success **and** exception path), `lock.held is False` and the `.intent.lock` flock is re-acquirable by a fresh `hold_submit_intent_process_lock` — i.e. the `ExitStack` releases even when `_run_node` raises.
8. Two stations never share a component id: `strategy_id`/`order_id_tag` are distinct per station, and registering two same-station strategies on a real `Trader` raises `RuntimeError` (`trader.py:400`).
9. Tape recorder untouched: `tests/unit/test_quote_tape_recorder.py:303` still green, and the recorder's settings loader never reads `BREEZY_CURRENT_RUNG_HOLD` (assert on the parsed settings object).
10. `tests/unit/test_runtime_settings.py`: `BREEZY_CURRENT_RUNG_HOLD` absent/`"0"`/`"true"`/`"1"` → `False,False,False,True` (exact `== "1"` idiom).
11. `tests/contract/test_current_rung_hold_wiring_contract.py`: the composition's store is constructed on the **calling** thread and a cross-thread `TrialDayLatch.record` raises from `SqliteStateStore._check_thread` (`sqlite_store.py:128`) rather than corrupting.

### File plan
| File | Change | Size |
|---|---|---|
| `src/breezy/runtime/settings.py` | `CURRENT_RUNG_HOLD_VAR`, `_parse_current_rung_hold`, `_parse_trade_catalog_root`, fields `current_rung_hold: bool = False`, `catalog_root: Path | None`, cross-flag refusal in `load_trade_settings` | +45 |
| `src/breezy/runtime/current_rung_hold_composition.py` **(new)** | `strategy_component_id(station)`, `resolve_station_instrument_ids(catalog_root, today_by_station)`, `NoTradableInstrumentsError`, `build_current_rung_hold_strategies(...)`, `open_shared_trial_day_latch(...)` (contextmanager) | ~230 |
| `src/breezy/runtime/trade_cli.py` | `_run_node(..., strategies: Sequence[Strategy] = ())` + `add_strategy` loop before `build()`; `run()` gains the `ExitStack` composition and the shutdown refusal sweep | +70 |
| `tests/unit/test_trade_cli_current_rung_hold.py` **(new)** | RED 1-9 | ~380 |
| `tests/unit/test_current_rung_hold_composition.py` **(new)** | discovery/climate-day/slug-fallback units | ~260 |
| `tests/contract/test_current_rung_hold_wiring_contract.py` **(new)** | RED 11 + `add_strategy` native pins | ~150 |
| `docs/plans/R8_OPERATOR_RUNBOOK.md` | row 0.11 → PARTIAL (shadow wiring landed); new §"shadow mode" naming both flags and the journalctl strings | +25 |

### Build sequence
1. `settings.py` flag + catalog + cross-flag refusal (RED 10, 2). 2. Discovery + composition (RED 3, 4, 8). 3. `ExitStack` latch ownership in `run()` (RED 5, 7, 11). 4. `_run_node` registration (RED 1, 4). 5. Non-forgeability + isolation (RED 6, 9). 6. Barrier re-run + runbook.

### Least-confident decisions (odds it survives peer review as written)
- **0.55** — catalog as the discovery source. The live `PolymarketUSInstrumentProvider` (`provider.py:323-406`) already discovers today's weather markets and is what actually populates the cache `on_start` reads (`strategy.py:203`); the catalog can therefore hold ids the cache lacks, and the strategy then logs `no instrument … stopping`. A reviewer may prefer resolving from `data_client_config.market_slugs` + `parse_weather_slug`, or deferring resolution into `on_start` against the cache. **Mitigation:** RED 4 asserts the composition's ids and the cache lookup agree in the contract harness.
- **0.6** — reusing `QUOTE_TAPE_CATALOG_VAR` in the trading role. `settings.py:60-63` says it is read *only* by `load_quote_tape_settings`; that comment must be amended or a fifth var introduced.
- **0.6** — composition (not the exec client) as sole latch opener. It is right for shadow mode, but R-7's `_connect` is where `reconcile_at_startup` must run (R-7 brief D6), and injecting a main-thread-built `SqliteStateStore` into the exec engine's loop trips `check_same_thread` if that loop is not the main thread. **Alternative if it does not hold:** the composition opens only the **flock** via `hold_submit_intent_process_lock` and both latches are built on their own consuming threads from that one token.
- **0.65** — shutdown-only `RefusalAlerter` sweep. Honest under L-16, but a 12-hour run surfaces nothing until it stops; a reviewer may want the sweep on the existing health-snapshot path instead.
- **0.7** — refusing to start when *any* station resolves zero. Per-station degradation (start the stations that resolved, count the rest) is defensible given L-23 (~9% of station-days are never listed) and may be the better call.
