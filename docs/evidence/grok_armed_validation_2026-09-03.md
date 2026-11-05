# Grok validation — is the bot armed to discover, evaluate, and trade? (2026-09-03)

Operator requirement: "The bot must be armed to self-discover the available markets and positions,
then evaluate using a backtested strategy, to trade on forecasted winning positions. Validate this."
Verbatim Grok output, read-only (`--permission-mode plan`, no shell, no subagents), tree `e4dfcad`.
Claude verification: `strategies=[]`/`catalogs=[]` (`node_config.py:218,229`), order/fill reports
return `[]` (`exec/client.py:885,899`), only `_SequenceForecastSource` implements `ForecastSource`
outside tests — all confirmed at the code.


---

### 1. Self-discover MARKETS — **ARMED**

**Exists**
- Live node (`breezy-trade`) registers the same read-only data factory as the recorder: `trade_cli.py:_run_node` → `PolymarketUSLiveDataClientFactory`; `node_config.py:build_trade_node_config` puts it in `data_clients`.
- On connect: `data.py:PolymarketUSDataClient._connect` → `instrument_provider.initialize()` → `provider.py:load_all_async` → `_discover_markets` → `_weather_market_payloads` (city tokens from `config.py:discovery_city_codes_from_registry` / `sites.toml`). Then `_reconcile_discovered_subscriptions(cycle="initial")`.
- Cadence: `_connect` starts `_update_instruments` forever; `_run_one_reload_cycle` does `initialize(reload=True)` then `subscription_changes_after_discovery`. New climate-day slugs subscribe without operator action.
- Empty listing **raises** `VenuePayloadError` (`load_all_async`: “zero configured-city weather markets… refusing to treat this as a quiet market”). Reload catches that and retries; existing WS subs stay (abort never reaches `_reconcile_discovered_subscriptions`). Proven 2026-09-02: venue listed **0** climate markets, HTTP 200, 14-byte body (`LISTING_GAP_INCIDENT_2026-09-02T0845Z.md`). Census 2026-09-03: five cities, Highest only, one open climate day, 30 markets; city filter is a no-op today.

**Missing (not required to call this armed)**
- `_last_successful_non_empty_discovery` is written, no reader found — not a keep-alive fallback.
- Trade node `catalogs=[]` (does not persist tape). Quotes still flow; `strategies=[]` so nothing trades on them.
- Cold start **on a gap day** fails the data-client connect until a non-empty cycle. UNVERIFIED: a `breezy-trade` process has actually reached RUNNING against the venue (wiring is in source; live discovery evidence is the recorder).

**Arming increments:** none that respect fail-closed. Do not paper over a 0-row listing.

---

### 2. Self-discover POSITIONS / orders / balances — **PARTIAL**

**Exists**
- Native mass-status seam overridden: `exec/client.py:generate_mass_status` never returns `None`; calls the three report generators.
- **Balances:** `_connect` → `_publish_account_state` → signed GET `ACCOUNT_BALANCES_PATH` (`/v1/account/balances`) → `generate_account_state`.
- **Positions:** `generate_position_status_reports` → GET `PORTFOLIO_POSITIONS_PATH`; `_map_position` maps LONG, refuses unmapped/non-long, drops EXPIRED (settled list) and FLAT. Unattributable → `_refuse` latch. Non-2xx → `PrivateReadRefused` + `classify_venue_refusal` (`factories.py:private_read`, R-6.5a).
- `eof is not True` → refuse rather than truncate (R-4P-1; no cursor follow).
- Account presence: `trade_cli.py` installs `install_account_presence_halt` → `RiskEngine.set_trading_state(HALTED)` if an order is formed with no cached account.
- Probe 2026-09-02 18:59Z: all four private paths HTTP 200 (`PRIVATE_v1_account_balances_*`, `…_portfolio_positions_*`, `…_orders_open_*`, `…_portfolio_activities_*`).

**Missing**
- `generate_order_status_reports` **always `[]`** (open-orders path not in `PRIVATE_READ_PATHS`; V2).
- `generate_fill_reports` **always `[]`** (activities deferred; no fills because no orders).
- `generate_order_status_report` returns `None`.
- Cursor pagination unfollowed.

**Arming increments (do not send):** after operator OQ-B (R-6.5P positive control), wire GET `/v1/orders/open` into `generate_order_status_reports`; later wire activities into fills; R-4P-2 cursor follow. Keep refuse-don’t-guess.

---

### 3. Evaluate with a BACKTESTED strategy — **ABSENT**

**Exists**
- Five packages under `src/breezy/strategy/` (`forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`, `running_extreme_lock`, `cli_settlement_print_lock`) plus `weather_common`. `ForecastSource` is a Protocol (`forecast_source.py`). The only non-test implementer is `_SequenceForecastSource` in `scripts/analysis/run_weather_strategy_backtests.py`.
- Live node: `build_trade_node_config` **`strategies=[]`, `exec_algorithms=[]`** (empty literals). Nothing evaluates live.

**What “backtested” means here**
- Prices are **forward-only** from ~2026-08-30 (`PROGRESS.md` standing verdicts). Forecast family backtests used **synthetic** snapshots. Forecast family **KILLED** (`grok_forecast_family_verdict_2026-09-02.md`): Breezy ingests **no** forecasts. Lock family **refuted on execution** (LESSONS **L-9**). K1 cheap-D-1 **DEAD** on Kalshi, n=0 here. M_B is a **descriptive join, not a Nautilus backtest**; `n_taken=1` of kill 60 / survive 150 (`mb_current_rung_edge_2026-09-02.md`, `grok_mb_kill_amendment_2026-09-02.md`). Standing: **no family has a proven edge**.

**Missing:** production `ForecastSource`; any strategy wired into the live node; any backtest on **real prices × real forecasts/observations** that survived.

**Arming increments:** do **not** wire a killed/refuted family. M_B must survive (n≥150, both lags) **before** BL-24 (`intraday_observation_ingest_2026-09-01.md`: `StationObservation` Data + catalog + `BacktestEngine` replay of `R(t)`). A real M_B backtest also needs that observation type; a forecast-family backtest needs a live ingest, not a synthetic source. `PROGRESS.md`: no new strategy / BL-24 / forecast ingest until M_B survives.

---

### 4. Trade on FORECASTED winning positions — **ABSENT**

**Exists (denial, not a send)**
- `_submit_order` always `generate_order_denied` (`_STANDING_ORDER_REFUSAL`: “reconciles and does nothing else, and no send path exists”).
- `signing.py` / `http.py`: `PERMITTED_METHODS == {"GET"}`.
- `assert_live_order_submission_permitted`: **zero `src/` callers** (re-export only; B6/B7 ban a caller). L-18: a function with no caller is not a control.
- `operator_max_daily_budget_usd` / `operator_max_position_cost_usd`: tests only; production importers = 0.
- `issue_live_trading_permit`: permanently unexported. No `write_transport.py` in `src/`.

**Missing:** any production forecast ingest; any POST; any `_submit_order` body that can dispatch.

**Remaining chain to one live order (do not execute here):** R-6.5P operator **positive control** (hand $0.01 BUY, probe must `PREFLIGHT_NOT_EMPTY`) → R-6.5b write transport (separate signer, B4 exemption) → R-7 `_submit_order` body that still **denies without a permit** → R-8 operator-present: mint permit, set `BREEZY_TRADING_ENABLED=1` and the two reserved caps **in the operator’s shell only**, fee floor measured. Plus a strategy that has actually survived. L-18: removing R-4 without a send path is worse (silent in-flight), not “enables sends.”

---

### Overall

The bot **is armed to self-discover weather markets** (live node, start + reload, fail-closed on a listing gap) **and to reconcile balances and long positions** (unattributable state refused; account-presence halt wired). It is **not armed to evaluate with a backtested strategy** (live `strategies=[]`; every forecast backtest was synthetic; lock family dead; M_B underpowered at n=1) **and not armed to trade forecasted winners** (no production `ForecastSource`, no send path, GET-only signer, standing R-4 denial). Discovery without a surviving strategy and without a send path is a recorder-class node that also reconciles.

### Ranked gaps

| # | Gap | Increment | Evidence it is armed |
|---|---|---|---|
| 1 | No surviving strategy | Wait for M_B n≥150 both lags; **then** BL-24 observation ingest + Nautilus backtest. Do not wire killed families. | M_B survive artefact + `BacktestEngine` run on real tape × real `R(t)` with fees |
| 2 | No production forecast | Build a real `ForecastSource` **only if** a forecast family is revived after ingest exists | Live `snapshot()` returning issuance-lead NWS/Open-Meteo, not settlement tmax |
| 3 | Orders/fills not reconciled | After OQ-B, GET open-orders; later activities→fills; cursor follow | Mass-status contains venue open orders/fills, not `[]` |
| 4 | No send path | R-6.5P → R-6.5b → R-7 (still denying) → R-8 operator gates | One `OrderDenied` that names **permit**, not `_STANDING_ORDER_REFUSAL`; still no send until R-8 |
| 5 | Caps/permit inert | Leave unread until R-7; operator assigns values, never the bot | Call sites exist; assignment scan still forbids values in repo |

**Engineering:** 3 (read-only recon), 4 (R-6.5b/R-7, still no send). **Data/time:** 1 (M_B clock ~09-22 / ~10-21), 2 (forecast archive + ingest). **Operator-only:** R-6.5P $0.01 BUY; R-8 `BREEZY_TRADING_ENABLED` + reserved caps in the shell; never assigned here.


---

## The brief Grok answered

# Validation brief — is the bot ARMED to self-discover markets and positions, evaluate with a backtested strategy, and trade forecasted winners?

Read-only, from files only: NO shell and NO subagents in this run (`run_terminal_command` and `spawn_subagent` are unavailable — do not attempt them). Repo root is the cwd (Breezy, Nautilus Trader 1.231.0, Polymarket.us daily-high weather markets). Under 170 lines.

## Invariants (binding — restate them; no recommendation may violate them)
Nautilus Trader is immutable. `allow_short` stays `False`. Never weaken/delete a safety, settlement, barrier or contract test. Never assign a value to an operator-reserved control (max daily budget the max-daily-budget control, max per position the max-per-position control). Never touch live-trading enablement (`BREEZY_TRADING_ENABLED`) or the NO-SEND execution-egress firewall. The bot has never sent a live order; this brief asks for none.

## The operator's requirement, verbatim
"The bot must be armed to self-discover the available markets and positions, then evaluate using a backtested strategy, to trade on forecasted winning positions. Validate this."

## Your task
Validate each capability against the CODE and the EVIDENCE, not against documentation claims. For each, give a verdict **ARMED / PARTIAL / ABSENT**, with `file:symbol` evidence, what exactly exists, what exactly is missing, and the smallest set of increments that would arm it — respecting the invariants. Then a one-paragraph overall verdict, and a ranked gap list an engineer can act on.

### Capability 1 — self-discover available MARKETS
Pointers: `src/breezy/adapters/polymarket_us/provider.py` (`PolymarketUSInstrumentProvider.load_all_async`, `_discover_markets`, `_weather_market_payloads`, city filter from `src/breezy/registry/sites.toml`), `src/breezy/adapters/polymarket_us/data.py` (`subscription_changes_after_discovery`, the reload cycle), `docs/plans/CF14_DISCOVERY_ISOLATION_2026-09-02.md`, `docs/evidence/venue_city_census_2026-09-03.md` (the venue lists exactly five cities, Highest only, one open climate day at a time), the recorder `src/breezy/runtime/quote_tape_cli.py` and the trading node `src/breezy/runtime/trade_cli.py` / `node_config.py`. Questions: does the LIVE TRADING node (not just the recorder) discover and subscribe automatically on start and on the reload cadence? Are new climate-day cohorts picked up without operator action? What happens on a venue listing gap (2026-09-02 had none listed)?

### Capability 2 — self-discover POSITIONS (and open orders, balances)
Pointers: `src/breezy/adapters/polymarket_us/exec/client.py` (`generate_position_status_reports`, `_map_position`, `generate_order_status_reports`, `generate_fill_reports`, the `_refuse` latch, R-6.5a's `PrivateReadRefused` classification), `exec/reports.py`, `factories.py` (`private_read` closure), `src/breezy/runtime/account_presence_halt.py`, `docs/plans/EXEC_SPINE_2026-09-01.md` and `EXEC_SPINE_R5_R6_2026-09-02.md` (R-3 reconciliation), `docs/evidence/venue/polymarket_us/PRIVATE_*` (all four private paths returned 200 on 2026-09-02). Questions: on node start, does Nautilus reconciliation populate the cache with the venue's positions and open orders through these methods? Is the account/balance presence enforced (`account_presence_halt`)? Are unattributable states refused rather than guessed? What is NOT reconciled (fills? orders?) and why.

### Capability 3 — evaluate using a BACKTESTED strategy
Pointers: `src/breezy/strategy/` (five packages: `forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`, `running_extreme_lock`, `cli_settlement_print_lock`; `weather_common/` risk, inflight, equity, models), `scripts/backtest/run_weather_strategy_backtests.py`, `scripts/analysis/weather_strategy_backtest_lib.py`, the backtest harness under `tests/integration/`, `docs/core/PROGRESS.md` "Standing verdicts", and the verdicts: `docs/evidence/grok_forecast_family_verdict_2026-09-02.md` (forecast family KILLED — every backtest was synthetic because Breezy ingests NO forecasts), `docs/core/LESSONS.md` L-9 (observation-lock family refuted on execution), `docs/evidence/k1_kalshi_prior_2026-09-02.md`, `docs/evidence/mb_current_rung_edge_2026-09-02.md` + `grok_mb_kill_amendment_2026-09-02.md` (the one open hypothesis, under measurement, n_taken=1 of 60/150). Questions: which strategy packages are wired into the live node config today, and with what verdict? Is ANY strategy in the tree backed by a backtest on real prices AND real forecasts/observations? What does "backtested" honestly mean here given prices are forward-only from 2026-08-30 and no forecast archive is ingested? What would a real backtest of the M_B cell require (BL-24 `docs/plans/intraday_observation_ingest_2026-09-01.md`)?

### Capability 4 — trade on FORECASTED winning positions
Pointers: forecast ingest — `ForecastSource` protocol and its implementations (find them; `weather_common/models.py`, any `ingest/` forecast client, `docs/evidence/open_meteo_previous_runs_probe_*`, IEM AFOS forecast PIL evidence in PROGRESS "Standing verdicts"); the write path — `exec/client.py:_submit_order` (R-4 standing refusal), `signing.py` `PERMITTED_METHODS == {"GET"}`, `docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md` Rev 6 (R-6.5a landed `4f76137`; R-6.5P probe landed `38f2426`, parked at the operator's positive control; R-6.5b, R-7, R-8 not started), `safety.py` (`assert_live_order_submission_permitted` zero callers by barrier), `operator_controls.py` (zero call sites), `docs/core/LESSONS.md` L-18. Questions: is there a production forecast source at all? Can the node place an order? What is the exact remaining chain to one live order, and what gates it (operator-only steps included)?

## Output
Per capability: verdict line, evidence bullets (file:symbol), missing bullets, smallest arming increments. Then: overall verdict (one paragraph, plain), a ranked gap list (each: gap → increment → what evidence would prove it armed), and a final line stating which gaps are engineering, which are data/time, and which are operator-only. Mark anything you cannot verify from files UNVERIFIED. Do not soften: if the honest answer is "the bot is armed for discovery and reconciliation, and NOT armed to evaluate or trade because no strategy has survived and no send path exists," say exactly that.
