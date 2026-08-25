# Polymarket.us Build Plan

Status: consolidated amended plan, 2026-08-25.

Supersedes for implementation sequencing:
`docs/plans/POLYMARKET_US_CONNECTOR_DECISION.md`.

This plan preserves the decision that the shipped NautilusTrader `.com`
Polymarket adapter cannot be repointed to Polymarket.us. It folds in the
adversarial review in `docs/plans/POLYMARKET_US_CONNECTOR_REVIEW.md` and the
four reconciled specialist reviews supplied on 2026-08-25.

## Binding Constraints

- NautilusTrader 1.231.0 is immutable. Do not modify, patch, fork, bypass, or
  reimplement Nautilus. Extend through native adapter/provider/execution
  mechanisms only.
- Operator decision: use the Polymarket.us retail API, not institutional DMA.
- Operator decision: `manualOrderIndicator` has no default. Every submit path
  must receive it explicitly.
- Operator decision: real-money enablement is an operator-only ceiling.
- No authenticated calls, no POSTs, and no order placement before the relevant
  phase gates below pass.
- SDK decision: use `AsyncPolymarketUS` only for REST. A test must fail if the
  adapter package imports sync `PolymarketUS`.

## Evidence Standard

- DIRECT EVIDENCE means a local source file, local evidence artifact, SDK source
  file, Nautilus source/stub, or live unauthenticated GET result observed before
  this plan.
- INFERENCE means a design consequence drawn from direct evidence. Inferences
  remain open to falsification by a named test, fixture, or venue/operator
  answer.
- UNKNOWN means the plan must fail closed until the named oracle answers it.

## Transport Decision

Decision: B-for-REST / native-for-WebSocket.

- REST: use official SDK `AsyncPolymarketUS` behind a Breezy-owned protocol.
  DIRECT EVIDENCE: SDK 0.1.2 exports `AsyncPolymarketUS` on `httpx.AsyncClient`.
  DIRECT EVIDENCE: neither sync nor async SDK constructor accepts an injected
  transport/session, so tests may need a contained private `_http` seam or a
  Breezy transport fallback if contract tests require lower-level control.
- WebSocket: use native `nautilus_trader.core.nautilus_pyo3.WebSocketClient`
  with `WebSocketConfig`. Borrow only the SDK's `create_auth_headers` and
  subscribe/unsubscribe envelope as schema reference. DIRECT EVIDENCE:
  SDK websocket `_message_loop` returns on `ConnectionClosed`; it has no
  reconnect, no backoff, no resubscribe, no heartbeat monitor, and auth headers
  are computed once at connect. DIRECT EVIDENCE: Nautilus `WebSocketConfig`
  has heartbeat, reconnect delay/backoff/jitter, idle timeout, and
  `WebSocketClient.connect(..., post_reconnection=...)`.
- Rate limiting: use native Nautilus `HttpClient` quotas where the adapter owns
  direct HTTP. REST paths retained in the SDK must be wrapped by Breezy-owned
  throttles because the SDK does not accept an injected Nautilus client.

## Phase Table

| Phase | Venue access / credentials | Deliverables | Tests and markers | Falsifiable exit gate |
|---|---|---|---|---|
| 0. Safety and dependency fuses | NO venue access. NO credentials. | `.gitignore` secret-file hardening; no-secret `NautilusConfig` rule; runtime credentials use `SecureString`; pytest Polymarket credential fail-fast; pyo3 network-client constructor block plus documented OS namespace gap; live-trading permit chokepoint; optional `polymarket-us==0.1.2` extra; sync SDK import ban. | `tests/unit/`, default marker set. Dependency pin is run with `--extra polymarket-us`. | `tests/unit/test_polymarket_us_phase0_safety.py` passes; an inner pytest process with `POLYMARKET_US_SECRET_KEY` exits nonzero before collection and does not print the value; `SecureString` inside any `NautilusConfig` raises on `config.json()` and `tokenize_config`; adapter AST scan finds no sync `PolymarketUS` import; `tests/unit/test_polymarket_us_dependency_pin.py` passes in an env installed with `breezy[polymarket-us]`. |
| 1. Read-only venue truth probes | Unauthenticated GET only. NO credentials. NO POST. | Append-only evidence captures for `/v1/series`, weather events, market-by-slug, book, and settlement endpoints; classify book as L2 or BBO; determine whether book levels carry venue timestamps; determine whether `settlementPx` is live mark or frozen final payout; downgrade `.us` fee schedule from `[VERIFIED]` to `[UNKNOWN]` until observed or documented. | `tests/contract/` with `contract`; fixture refresh commands remain outside default pytest; any live probe script must be unauthenticated and GET-only. | Request log oracle contains exactly `GET` methods and zero auth headers for all captures; evidence directory contains dated content plus digest sidecars for all five cities and both high/low series; book classification fixture asserts one of `{L2, BBO}` from observed payload shape; `settlementPx` fixture either proves final-only by unchanged value after close and settlement endpoint agreement or records `UNKNOWN` and blocks later settlement use. |
| 2. Settlement alignment and EV proof | No credentials. May use unauthenticated settlement GETs and local NWS catalog. | Complete settlement-alignment study; EV model that combines bucket probabilities, settlement-error adjustment, tick/quantity rounding, depth/slippage, and fee/commission assumptions; fail-closed fee source policy. | `tests/unit/` for EV math; `tests/contract/` with `contract` for settlement fixtures; no `live`, `venue_live`, or `real_money` tests in the exit gate. | Settlement oracle evaluates at least 100 resolved city-days total, at least 15 per city, across the five Breezy cities; unexplained settlement mismatch count is 0; missing-overlap cases are counted separately and cannot pass; EV fixture set includes positive, zero, and negative edge cases and fails closed when fee source, depth, or settlement alignment is unknown. |
| 3. Instrument provider | NO venue access and NO credentials for default tests. Fixture-only. | `PolymarketUSInstrumentProvider` maps each bucket/outcome to native `BinaryOption`; `InstrumentId` uses a reserved separator such as `~`, never hyphen parsing; any slug containing `.` is rejected; `BinaryOption.outcome` stores side; `BinaryOption.info` carries numeric market id, event slug/id, side ids, city, climate date, high/low, strike bounds, and `city_day_cluster_id`. | `tests/unit/` default; `tests/contract/` with `contract` for Nautilus `BinaryOption` behavior. | Property/fixture tests accept real weather bucket slugs, reject dotted slugs and malformed IDs, prove symbol round-trip invertibility, prove no imports from `nautilus_trader.adapters.polymarket.common.symbol`, and prove all bucket instruments for a city/day share the same `city_day_cluster_id`. |
| 4. Read-only market data client | NO credentials for loopback/default tests. `venue_live` only if public websocket access or operator-approved non-order credentials exist. | Native `LiveMarketDataClient`; REST snapshots via `AsyncPolymarketUS`; websocket via Nautilus `WebSocketClient`; Decimal/`Price.from_str` conversions only; duplicate-safe snapshot/delta handling; reconnect `post_reconnection` resubscribe. | `tests/unit/` default; `tests/contract/` with `contract`; optional `tests/live/venue/` or `tests/contract/` with `venue_live` gated by `BREEZY_VENUE_LIVE=1`. | Loopback websocket fixture forces disconnect; client reconnects through Nautilus `post_reconnection` and resubscribes exactly once per market slug; precision fixtures prove no `float()` use for prices/amounts; casing fixture pins observed camelCase/snake_case contract; no authenticated endpoint or POST appears in default test request logs. |
| 5. Strategy, sizing, and risk | NO credentials. NO venue access for default tests. | Strategy consumes NWS catalog/gate state plus venue market data; forecast-to-bucket distribution; bankroll sizing; edge threshold; kill switch; per-order USD cap; city/day correlated exposure cap using `city_day_cluster_id`; stale-ingest and stale-book refusal. | `tests/unit/` default; `tests/replay/` with `replay`; backtest tests remain credential-free. | Strategy fixture refuses to trade for each named cause: stale NWS gate, unresolved settlement alignment, unknown fees, unknown depth, insufficient edge, over USD cap, over cluster exposure cap, kill switch active, and absent `manualOrderIndicator`; positive fixture produces only an execution-intent object, not a venue order. |
| 6. Node wiring | NO credentials. NO venue access. | Register Polymarket.us data and later execution client factories before `TradingNode.build()`; replace `data_clients={}` / `exec_clients={}` hardcoding with config driven wiring; preserve ingest-only node mode. | `tests/unit/` default for config; `tests/contract/` with `contract` for Nautilus node composition order. | Recording node factory proves `add_data_client_factory` and, when enabled, `add_exec_client_factory` are called before `build()`; ingest-only settings still produce no venue client registrations; config serialization contains no secrets. |
| 7. Authenticated preview, list, cancel, and native reconciliation reports | Credentials required. `venue_live` only. No create-order path. POST preview only if venue/operator confirms it cannot create or modify an order. | Authenticated REST wrapper using `AsyncPolymarketUS`; redacted auth failures; durable order journal for preview/list/cancel; cancel remains available under halt mode; implement `LiveExecutionClient.generate_order_status_reports`, `generate_fill_reports`, `generate_position_status_reports`, and `generate_mass_status`; parse live fill commissions into `OrderFilled.commission`. No live `FeeModel` use. | `tests/unit/` default with loopback signed-request capture; `tests/contract/` with `contract`; `venue_live` requires `BREEZY_VENUE_LIVE=1` and credential env vars outside normal pytest. | Loopback oracle verifies `X-PM-*` headers and `/v1/` paths while redacting secret material; journal records local submit id/body hash/status for every preview/cancel/list action; execution client subclass is instantiable because all four `generate_*` methods exist; fill fixture with commission payload emits `OrderFilled.commission`; no code path can dispatch `POST /v1/orders` create. |
| 8. Backtest fee model and replay parity | NO credentials. NO venue access for default tests. | Backtest-only `FeeModel` after fee schedule is verified; replay parity between recorded venue tape, strategy, risk, and simulated fills. | `tests/unit/` default; `tests/replay/` with `replay`. | Fee model tests cite the verified .us fee oracle and fail if fee schedule is `UNKNOWN`; replay fixtures match expected net PnL after fees/rounding for at least one win, loss, maker, and taker fill; plan explicitly states this model has no live execution consumer. |
| 9. Real-money create-order probe | Credentials and explicit operator approval required. `real_money` only. | Create-order path behind one call-time chokepoint requiring valid credentials, explicit `LiveTradingPermit`, explicit `manualOrderIndicator`, USD cap, market slug allowlist, cluster exposure cap, kill switch check, NTP/skew check, and durable journal. | `tests/unit/` default for chokepoint; `tests/contract/` with loopback; `real_money` gated by `BREEZY_REAL_MONEY=1` plus written operator approval artifact. | Before dispatch, the journal records order name, market slug, side/outcome, USD cap, `manualOrderIndicator`, timestamp, request body hash, and permit id; one approved production POST is allowed only when all gates are true; post-trade reconciliation via native reports reaches 100% agreement for order/fill/position, or the market group latches `SUBMIT_AMBIGUOUS` and halts. |

## Open Questions That Block Later Phases

| Question | Blocks | Required oracle |
|---|---|---|
| Is `marketSlug` immutable for a market's lifetime? | Instrument identity and journal recovery. | Venue documentation, support answer, or longitudinal read-only fixture showing unchanged slug for the same numeric market id through close/settlement. |
| Does Polymarket.us support trade-only, non-withdrawal, IP-restricted retail API keys? | Credential risk model and deployment runbook. | Operator portal evidence or venue support answer. |
| Does `/v1/markets/{slug}/book` return true L2 depth or only BBO? | EV, slippage, market-data model. | Read-only book fixture with multiple levels per side or official venue answer. |
| Do book levels carry venue timestamps? | Staleness checks and replay ordering. | Read-only payload fixture or official venue answer. |
| Is `settlementPx` a live mark or the frozen final payout? | Settlement and PnL accounting. | Closed-market longitudinal fixture comparing book endpoint and settlement endpoint after finalization. |
| What is the verified Polymarket.us retail fee/commission schedule? | EV and backtest fee model. | Official fee page/evidence capture or observed fill/accounting payload. Current local evidence is `[UNKNOWN]`; `.com` values must not be carried across. |
| Is there a client-supplied idempotency key or equivalent for create-order? | Duplicate-submit safety. | SDK source, official docs, or signed loopback/live response schema. |
| Are public/market websockets credential-free, and is message casing camelCase or snake_case in production? | Market data client contract. | Loopback fixtures plus optional `venue_live` websocket observation or official SDK/docs reconciliation. |
| What is acceptable host clock skew/NTP health for signing? | Authenticated REST and create-order. | Local NTP health check and venue signature-window docs. Risk is epoch-millisecond clock skew, not timezone. |

## Live Commission and Reconciliation Rule

DIRECT EVIDENCE: Nautilus `FeeModel` lives under `nautilus_trader.backtest` and
the shipped Polymarket fee model states it is for backtests. Therefore live
execution must not rely on a `FeeModel`. Live commissions arrive in fill
payloads and must be parsed into `OrderFilled.commission`.

DIRECT EVIDENCE: Nautilus live reconciliation is native
(`nautilus_trader/live/reconciliation.py`, driven by `LiveExecutionEngine`).
The adapter obligation is to implement the four `LiveExecutionClient` report
methods: `generate_order_status_reports`, `generate_fill_reports`,
`generate_position_status_reports`, and `generate_mass_status`. Breezy must not
hand-roll a reconciliation loop.

## Safety Notes

- Ordinary `pytest` must fail fast on Polymarket credential environment
  variables. This prevents a credentialed host from running default tests.
- Python socket blocking is not a complete OS-level egress proof for Rust/pyo3
  clients. Default tests also replace exposed `nautilus_pyo3.HttpClient` and
  `WebSocketClient` constructors, but the residual process-level gap is closed
  only by running tests inside a network namespace:
  `unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1 .venv/bin/python -m pytest`.
- Secret material must never be a `NautilusConfig` field because Nautilus can
  serialize config JSON and hash it via `tokenize_config`. Config may carry only
  references such as environment variable names. Runtime credential material
  uses `SecureString`.
