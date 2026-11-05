This is a read-only ownership audit of the Polymarket.us adapter. I'll verify Breezy against the installed Nautilus 1.231.0 source and the project skill, and I won't change any files.The seam is 34 modules and about 25k lines. Next I’ll map each class onto Nautilus base types and the safety invariants the skill flags.The Polymarket.us adapter is a real venue extension, not a second Nautilus. Of the 25,134 lines in `src/breezy/adapters/` (34 modules, HEAD `60290e9d`), the framework already owns client lifecycle, the order-event state machine, reconciliation orchestration, `BinaryOption`, the Cython `FeeModel` slot, `HttpClient` / `WebSocketClient`, and `RetryManager`. What it does not own is Ed25519 request signing, the GET/POST cages, NO-leg complement pricing, the dated fee schedule, drift refusals, or the SQLite fill store. Substituting the PyO3 probability fee model or the `.com` adapter is not equivalent. Codegraph was unavailable (read-only database); every line below was read directly. No tests were run.

## (A) Ownership table

Nautilus paths are under `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/`. Tags: **CLEAR** = Nautilus owns it and Breezy only calls it; **EXTENDS** = sanctioned subclass or venue behavior Nautilus does not have; **UNCLEAR** = overlap not fully proven.

| Module (LOC) | Nautilus owns | Breezy owns | Tag |
|---|---|---|---|
| `exec/client.py` (5957) | `LiveExecutionClient` (`live/execution_client.py:66`); sync `submit_order` → async `_submit_order` (`:277`, `:608`); `generate_order_denied` / `generate_order_submitted` (`execution/client.pyx:370`, `:411`); `calculate_commission` hook (`:165`); engine calls the five `generate_*` methods (`live/execution_client.py:343–440`) and books `Money(0)` if the hook returns `None` (`live/reconciliation.py:506–508`); risk engine allows orders while `account_for_venue` is `None` (`risk/engine.pyx:682–689`); Redis-only cache (`system/kernel.py:312`, `cache/cache.pyx:1366–1368`) | `AccountType.CASH` + `OmsType.NETTING` (`exec/client.py:1670–1671`); GET `private_read`; SQLite fill/venue-id store; ambiguous-intent resolver; permit/ledger denies before POST (`:5337–5340`); `calculate_commission` → `polymarket_us_fee` (`:5118–5175`) | EXTENDS |
| `exec/submit_chain.py` (1509) | Order events, not the pre-POST policy | Pure authorize/encode/classify helpers so `_submit_order` stays on the egress allowlist | EXTENDS |
| `exec/reports.py` (1798) | `OrderStatusReport` / `FillReport` / `PositionStatusReport` types | Venue JSON → reports, plus drift allow-sets | EXTENDS |
| `exec/refusals.py` (323), `endpoints.py` (182), `no_side_keys.py` (82), `exec/__init__.py` (27) | Nothing for `.us` private REST | Status classification, paths, NO-side store keys | EXTENDS |
| `exec_fault.py` (91), `feed_fault.py` (116) | Task failure logging via `_on_task_completed` | Named fatal-fault records; no socket | EXTENDS |
| `data.py` (2370) | `LiveMarketDataClient` (`live/data_client.py:320`); msgbus, cache, `LiveClock` (`data.py:732–734`); `create_task` (`data.py:1113`) | Quote/trade parse, discovery reload, tape-gap and silent-subscription watchdog. No `set_timer`, no `RetryManager` | EXTENDS |
| `websocket.py` (1669) | `WebSocketConfig` / `WebSocketClient.connect` (`core/nautilus_pyo3.pyi:5530–5558`); heartbeat and `idle_timeout_ms`; `RetryManager` (`live/retry.py:65`, used at `websocket.py:1033`) | Fresh-header reconnect when a signer is present (`reconnect_max_attempts=0`, `websocket.py:793–816`); 10-subscription pool | EXTENDS |
| `http.py` (290), `transport.py` (494), `write_transport.py` (197) | `HttpClient.get/post` (`pyi:5417–5452`); quotas; no redirect/TLS/size cap | GET-only and POST-only closures (B1/B3); status taxonomy; one query string signed and sent | EXTENDS |
| `signing.py` (286) | `ed25519_signature(private_key: bytes, data: str) -> str` (`pyi:519`), used by Binance (`adapters/binance/http/client.py:172`). No PM.us canonical string | PyNaCl `SigningKey`; `PERMITTED_METHODS={"GET"}` (`signing.py:84`, refuse at `:260–265`); 30s skew | EXTENDS |
| `fees.py` (605) | Cython `FeeModel` / `MakerTakerFeeModel` / `FixedFeeModel` / `PerContractFeeModel` (`backtest/models/fee.pyx:33–168`); `Condition.type(..., FeeModel)` (`backtest/engine.pyx:643–651`). PyO3 `ProbabilityPriceFeeModel` exists at runtime and is **not** a Cython `FeeModel` | `theta * C * p * (1-p)` from `instrument.info`, dated schedule, maker-rebate refusal | EXTENDS |
| `provider.py` (748), `parsing.py` (1539) | `InstrumentProvider.load_all_async` (`common/providers.py:76`); `BinaryOption` | Weather discovery and payload → `BinaryOption` | EXTENDS |
| `symbology.py` (640), `leg_prices.py` (206), `series.py` (352) | `.com` parser splits on `-` (`adapters/polymarket/common/symbol.py:20–35`). Forbidden import (`pyproject.toml:123`) | Slug ids, YES/NO instruments, wire price `1-p` for NO (`leg_prices.py:56–74`) | EXTENDS |
| `factories.py` (871), `config.py` (694) | `LiveDataClientFactory` / `LiveExecClientFactory` (`live/factories.py:27`, `:69`); `Live*ClientConfig` | Shared `lru_cache` signer/HTTP/provider; exec config embeds the data config (`config.py:547–558`); secrets are names, not values | EXTENDS |
| `credentials.py` (186), `env.py` (287), `secure.py` (97), `redaction.py` (92) | `SecureString.get_redacted` leaks 4+4 chars (`common/secure.py:100–102`, `__str__` `:133`, `__repr__` `:139`). `get_env_key` exists; this seam does not use it (`env.py:14`) | Mode/uid file read; `RedactedSecureString` (`secure.py:64–88`) | EXTENDS |
| `safety.py` (1046), `operator_controls.py` (523) | Risk engine, but only after an `AccountState` exists | HMAC permit, TTL, spend-down, daily USD ledger | EXTENDS |
| `tape_records.py` (637), `account_activity.py` (635) | `Data` + Arrow registration (hand-written custom data is the sanctioned pattern) | Gap/clock/settlement/depth records; activity taxonomy | EXTENDS |
| `errors.py` (369), `__init__.py` (215), `adapters/__init__.py` (1) | — | Venue errors; package exports. Permit issuer is deliberately not exported | EXTENDS |

`allow_short` is **not** assigned in this seam. `LONG_ONLY_SIDE = "BUY"` (`exec/client.py:661`) assumes it. The flag is `RiskLimits.allow_short: bool = False` at `src/breezy/strategy/weather_common/risk.py:224`. The comment at `exec/client.py:659` cites `risk.py:139`, which is a reason-string (`"p_hold_undefined"`), not the flag. **CONFIRMED** stale citation.

## (B) Duplication candidates

Ranked by lines you could actually delete, times confidence they are the same behavior. "Same name" was not treated as equivalence.

| Rank | Breezy | Nautilus | Equivalent? | Saved LOC × conf | Risk if substituted |
|---|---|---|---|---|---|
| 1 | `Ed25519WriteRequestSigner` (`write_transport.py:80–144`) | Sibling `Ed25519RequestSigner` (`signing.py:185–283`), not Nautilus | **No.** Read set is `{GET}` and has two canonical variants. Write set is `{POST}` (`write_transport.py:54`) and always `build_canonical_path_without_query` (`:127`). | ~65 × high that it is a clone, medium that a merge is safe | One signer object that accepts both verbs collapses barrier B2. |
| 2 | Auth reconnect supervisor (`websocket.py:903–1058`, `_build_config` `:793–807`) | `WebSocketConfig.reconnect_*` (`pyi:5537–5542`); `post_reconnection` fires only after connect (`pyi:5555`) | **No while a signer is attached.** Headers are constructor-only; there is no Python method to refresh them. Native reconnect is disabled (`reconnect_max_attempts=0`). Unauthenticated path already uses native reconnect (`:815`). | ~0 if the markets socket must be signed; a few hundred only if it is public | A dead `X-PM-Timestamp` (30s window, `signing.py:86–89`) fails every native retry the same way. Rust reuse of the original header list was **not** read. **HYPOTHESIS** on the Rust loop; **CONFIRMED** there is no refresh API. |
| 3 | `RetryManager` plus `_next_backoff_delay_ms` (`websocket.py:1005`, `:1033`) | `get_exponential_backoff` (`live/retry.py:24–60`); `RetryManager.run` returns `None` on `CancelledError` (`:195–197`, not `:187–189` as `websocket.py:61–63` says) | **Partial.** The helper is reused. The second counter is for drops after native reconnect is turned off. Jitter floor `randint(delay_initial_ms, delay)` (`retry.py:60`) matches the skill. | ~0 as a deletion | Removing the supervisor re-enables stale signed headers. |
| 4 | PyNaCl `SigningKey.sign` + base64 (`signing.py:57`, `:277–278`) | `nautilus_pyo3.ed25519_signature` (`pyi:519`) | **Not shown.** Primitive only: no method allow-list, no canonical path, no skew check. Return encoding was not executed. Binance passes an already-built string (`binance/http/client.py:172`). | ~40 × low | A byte-format mismatch fails every signed request. |
| 5 | `polymarket_us_fee` (`fees.py:313`) and `PolymarketUSFeeModel.get_commission` (`:266`) | PyO3 `ProbabilityPriceFeeModel`: `qty * fee_rate * p * (1-p)` from the instrument's maker/taker rate (runtime docstring). Cython fee models have no such class (`fee.pyx:33–168`) | **Formula shape only.** Breezy reads `instrument.info` theta, refuses an unknown schedule, keeps a dated 0.06 / ambiguous / 0.0695 schedule (`fees.py:84–122`), and prices makers at the taker coefficient plus a refusal (`exec/client.py:5148–5165`). Passing the PyO3 object into `BacktestEngine.add_venue` hits `Condition.type` (`engine.pyx:651`). | **0** | Backtest `TypeError`, or silent `MakerTakerFeeModel` flat `taker_fee` if `fee_model` is omitted (`engine.pyx:643–644`). |
| — | SQLite fill store (`exec/client.py:63–103`) | Cache + Redis restores orders and `avg_px_open` from `OrderFilled` (`cache.pyx:393` area claimed by the module; index rebuild **CONFIRMED** at `:1366–1368`; Redis-only **CONFIRMED** at `kernel.py:312`) | **Rejected on purpose**, not a missing API | Negative: adopting Redis | New process dependency and an egress path the N2 firewall does not model. |
| — | Slug symbology | `.com` `condition_id-token_id` split (`symbol.py:20–35`) | **No.** Different venue. Import is forbidden (`pyproject.toml:123`). | 0 | Wrong instrument ids. |
| — | `RedactedSecureString` | `SecureString` | **Not a reimplementation.** Subclass closes a real 4+4 leak (`secure.py:100–102`). | 0 | Reverting prints key fragments. |

Order-state transitions are not reimplemented. `_deny` calls `generate_order_denied` (`exec/client.py:5186–5195`); `_generate_submitted` calls `generate_order_submitted` (`:5220–5227`). **CONFIRMED**.

## (C) Abstraction and coupling

Nine `Protocol`s. Several have a single production use:

| Protocol | Site | Mentions in `src/` | Note |
|---|---|---|---|
| `QuoteTickParser` | `data.py:524` | 5 / 1 file | One parser, injected from `factories.py` |
| `SupportsTimestampNs` | `safety.py:200` | 4 / 1 file | Clock already has `timestamp_ns` |
| `_ReadableStore` | `exec/no_side_keys.py:46` | 2 / 1 file | |
| `SilentSubscription` | `data.py:452` | 12 / 2 files | |
| `SupportsVenueLog` | `http.py:111` | 7 / 2 files | |
| `PolymarketUSReadTransport` | `transport.py:168` | 9 / 4 files | The GET cage's type |
| `PrivateRead` | `exec/client.py:779` | 27 / 5 files | Not runtime-checkable; the real GET is the closure at `factories.py:801–844` |
| `MarketsFeed` | `data.py:470` | 17 / 4 files | Single socket and pool both satisfy it |
| `ExitAuthorizationLike` | `exec/submit_chain.py:390` | 6 / 2 files | Avoids a strategy import |

`PolymarketUSExecutionClient` has 85 methods. Three dominate: `__init__` 261 lines (`:1600`), `_resolve_ambiguous_intents` 605 (`:2377`), `_submit_order` 503 (`:5327`). `submit_chain.py` (1,509) exists so that coroutine's call set stays on the static allowlist. That split is load-bearing, not casual layering.

Config is not a second copy of Nautilus config. `PolymarketUSExecClientConfig` embeds `PolymarketUSDataClientConfig` (`config.py:546–558`). It does carry callables (`state_store_opener`, `submit_veto`, `resolver_instrument_loader`, `submit_intent_latch: object`) so `adapters` does not import `runtime`. That is the layer inversion showing up as fields.

Import-linter debt that names this seam (`pyproject.toml:100–107`), three rows:

- `breezy.adapters.polymarket_us.config -> breezy.runtime.settings`
- `breezy.adapters.polymarket_us.factories -> breezy.runtime.settings`
- `breezy.persistence.quote_tape_gaps -> breezy.adapters.polymarket_us.tape_records` (downward layer violation)

Also a hard ban on `nautilus_trader.adapters.polymarket` (`pyproject.toml:111–123`). `adapters` is forbidden from `breezy.analysis` (`:156–163`).

Two verb cages (`NautilusHttpTransport` GET, `PolymarketUSWriteTransport` POST) are parallel by design: each closes over `client.get` or `client.post` and stores no client attribute (`transport.py:450` area; `write_transport.py:147–158`). Merging them would put both verbs on one object.

## (D) Invariants and the tests that pin them

No test was executed. Paths were confirmed by search.

| Invariant | Where it lives | What it actually does | Pinning tests |
|---|---|---|---|
| Egress firewall (the "NO-SEND" name in code is `E0-NOSEND`) | AST guard plus runtime denies | **Not a runtime off switch.** `WRITE_CANONICAL_STRING_VERIFIED` is `True` (`write_transport.py:46–52`). Factory sets `order_sender = write` when that flag is true (`factories.py:799`). `_submit_order` still denies if the sender is `None` or the flag is not `True` (`exec/client.py:5337–5340`), and before that if refusals are latched or no account is cached. POST body lives only in `write_transport.py`. | `tests/unit/test_execution_egress_firewall_guard.py` (N1–N5; docstring measures that patching `socket` does not stop `nautilus_pyo3.HttpClient`), `tests/unit/test_polymarket_us_readonly_guard.py`, `tests/unit/test_polymarket_us_submit_order_chain.py`, `tests/unit/test_polymarket_us_exec_client.py`, `tests/unit/test_cage_rule_constants_are_pinned.py` |
| B2 GET-only signer | `signing.py:84`, `:260–265` | Read signer refuses anything but `GET` before the key is used. Independent of B1 (`http.py:68–69`, dispatch assert) and B3 (GET closure, no stored client). | `tests/unit/test_polymarket_us_signing.py`, `test_polymarket_us_http.py`, `test_polymarket_us_write_transport.py` (write sibling is POST-only) |
| Write signer cannot sign GET | `write_transport.py:54`, `:119–124` | Separate type, separate method set | `test_polymarket_us_write_transport.py`, `test_polymarket_us_write_signing_probe.py` |
| Drift refusals | `exec/reports.py:233` balance, `:291` order, `:333` execution (`commissionSpreadPx`, `legPrices`, `traceId`, `transactTradeDate`, `unsolicitedCancelReason`), `:376` position, `:418` market metadata | Unknown keys still refuse. Allow-sets are declared-but-unread so the snapshot test does not go vacuous. | `tests/unit/test_polymarket_us_exec_reports.py`; execution set also named from `test_polymarket_us_submit_order_chain.py`. A `test_polymarket_us_exec_snapshot_drift.py` is cited in comments and was **not** found. |
| Permit / caps in this seam | `safety.py` HMAC permit (TTL, spend-down, order count; issuer takes no ceiling argument, `:53–56`); `operator_controls.py` daily USD ledger | Pre-send. Distinct from Nautilus `RiskEngine`, which becomes live only once this client publishes `AccountState` (`exec/client.py:8–15`). | `tests/unit/test_polymarket_us_permit_issuance.py`, `test_polymarket_us_phase0_safety.py`, `test_order_submission_permit_issuance.py`, `test_operator_caps_through_the_live_composition.py`, `tests/contract/test_risk_engine_ordering_enforcement.py` |
| Long-only | Seam: `LONG_ONLY_SIDE` (`exec/client.py:661`); open side on reports assumed BUY (`exec/reports.py:779` comment). Flag: `risk.py:224` | SELL is a close, not a short (`exec/client.py:663–668`). NO buys are still buys of the NO instrument; the venue echoes them as `ORDER_SIDE_SELL` / `ORDER_INTENT_BUY_SHORT` (`leg_prices.py:39–46`). | `tests/unit/test_weather_common_risk.py`, `test_no_side_s5c_flip_2026_09_14.py`, `test_leg_prices_2026_09_14.py`, `test_polymarket_us_exec_client.py` |
| No `AccountType.BETTING` | `exec/client.py:1666–1671` | Betting stake math is `stake = quantity * (price - 1)` and is the wrong model for a 0–1 price. | `test_execution_egress_firewall_guard.py` (only file under `tests/` that names `AccountType.BETTING`) |
| Fee must be wired and must not raise on the reconcile path | `fees.py:19–28`; `calculate_commission` swallows into a refusal and returns `None` (`exec/client.py:5132–5181`) | A raise aborts startup while a position is open. `None` lets Nautilus book zero, so the refusal freezes trading. | `tests/unit/test_polymarket_us_fee_model.py`, `test_polymarket_us_fee_guard.py`, `test_polymarket_us_fee_schedule_pin.py` |
| Credential render | `secure.py:72–88` | No key fragment in `str`/`repr`/`format` | `tests/unit/test_polymarket_us_credential_serialization.py`, `test_polymarket_us_secret_exposure.py` |

## (E) Dispositions

| Subsystem | Disposition | Requirement | Why this shape | Extension point | Migration risk |
|---|---|---|---|---|---|
| GET cage + read signer + write cage + write signer | **Retain** | Venue auth and the no-accidental-POST property | Nautilus `HttpClient` exposes every verb (`pyi:5426–5469`). The cages are the control. | `HttpClient` injected, never constructed inside the write module | Merging cages or signers is the hazard, not keeping them |
| WebSocket + pool | **Retain** | Markets stream, fresh signatures, 10-sub cap | Native reconnect cannot refresh headers through any public API. Pool is a measured venue limit (`websocket.py:67–76`) | `WebSocketClient.connect` + `post_reconnection` for the public case | Deleting the supervisor is safe only after a live probe shows the socket is public (`websocket.py:29–33`, still unresolved) |
| Data client, provider, parsing, symbology, series | **Retain** | Weather `BinaryOption`s and quotes | `.com` slug/token scheme does not parse these markets | `LiveMarketDataClient`, `InstrumentProvider.load_all_async` | Low if left alone |
| Tape records | **Retain** | Gap, clock-offset, settlement, depth-truncation history | Hand-written `Data` is the sanctioned custom-data path | `Data` + one Arrow registration | Don't fold into quote ticks; they are different facts |
| Fee model | **Retain** | `theta * C * p * (1-p)` on the Cython backtest and on reconciliation | PyO3 model is the right formula and the wrong type | Cython `FeeModel.get_commission` | Replacing with `ProbabilityPriceFeeModel` fails `engine.pyx:651`. Deleting the override books zero commission |
| Exec client + reports + submit chain + refusals | **Retain, simplify internally** | Map `.us` orders/fills/positions and refuse on drift or ambiguity | Engine reconciliation is real and is already called. It does not know this venue's JSON, the ambiguous-POST resolver, or the position-lag latch | The five `generate_*` coroutines and `calculate_commission` | Splitting the 5,957-line class is safe only if the E0 allowlist and the drift sets move with the code. Do not "thin" it down to empty `generate_*` |
| SQLite store vs Redis cache | **Retain the refusal** | Restart-stable venue-order-id and fill index without Redis | Nautilus persistence exists and was declined (`exec/client.py:63–81`) | `Cache` if Redis is ever accepted | Adopting Redis changes ops and the firewall's egress picture |
| Permits and daily ledger | **Retain** | Operator ceiling the strategy cannot raise, enforced before POST | Risk engine is off until `AccountState`, and it has no HMAC permit | None. This is application policy | Removing it leaves only Nautilus risk checks, which no-op with no account |
| `RedactedSecureString` | **Retain** | Secrets must not render | Base class is doing what its docstring says and still leaks 4+4 | Subclass of `SecureString` | Reverting reopens the leak |
| Factories / config | **Simplify only the two `ignore_imports`** | One shared HTTP quota bucket and one venue config | Embedding `venue: PolymarketUSDataClientConfig` is already the right boundary | `Live*ClientFactory.create` | Don't split venue facts back into a second exec config |
| `.com` PyO3 adapter (`nautilus_pyo3.polymarket`, 12 symbols including `PolymarketExecutionClientFactory`) | **Do not adopt** | — | Crypto CLOB, wallet key, not Ed25519 `.us` | — | Forbidden Python package is `nautilus_trader.adapters.polymarket`; the PyO3 module is a separate surface and is also the wrong venue |
| Single-use protocols (`QuoteTickParser`, `SupportsTimestampNs`, `_ReadableStore`) | **Simplify** | Test injection | One implementation each | — | Low, if call sites are updated in the same change |
| `ed25519_signature` | **Do not swap yet** | — | Encoding and key layout unverified | The primitive | Auth outage |

Simplest ownership boundary: Nautilus owns the node, engines, cache, clock, bus, order events, and report application. Breezy owns one signed HTTP client graph, one markets socket, instrument discovery, report parsing with an explicit unknown-key refusal, and a pre-POST policy (permit, ledger, long-only, canonical-string flag) that runs before `generate_order_submitted`.

## (F) Open questions

- **CONFIRMED gap:** whether `/v1/ws/markets` requires auth. `websocket.py:29–33` says the SDK signs it and a public result would delete the custom reconnect. Not re-probed here.
- **HYPOTHESIS:** the Rust client resends the original `WebSocketConfig.headers` on every native reconnect. No Rust sources were read. The Python API has no counterexample.
- **HYPOTHESIS:** `ed25519_signature` returns the same base64 bytes as PyNaCl over the same canonical string. Not executed.
- **UNCLEAR:** once `AccountState` exists, which notional is enforced twice (HMAC permit vs `RiskEngine` max-notional). Both are live; they were not compared field by field.
- **CONFIRMED doc drift inside the seam:** `RetryManager` cancel is `live/retry.py:195–197`, while `websocket.py:61–63` cites `:187–189`. `allow_short` is `strategy/weather_common/risk.py:224`, while `exec/client.py:659` cites `:139`.
- The comment-cited test `test_polymarket_us_exec_snapshot_drift.py` was not in `tests/`. The drift sets are pinned from `test_polymarket_us_exec_reports.py` instead.
- Codegraph could not be queried. `.pyx` behavior cited above was read from the installed sources, not from `docs/reference/nautilus/`.
