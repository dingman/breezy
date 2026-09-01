# NautilusTrader 1.231.0 — Native Support for Binary-Outcome / Prediction Markets

<!-- Generated: 2026-08-22 | Commit: (no commits on HEAD — repo has no revisions yet) | Sources: docs/reference/nautilus/v1.231.0/ (vendored official docs) + .venv/.../nautilus_trader/ (installed 1.231.0) -->

- **Source of truth (docs):** `/home/jon/breezy/docs/reference/nautilus/v1.231.0/`
- **Source of truth (code):** `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/` (`__version__ == "1.231.0"`, dist-info `Version: 1.231.0`)
- **Date:** 2026-08-22
- **Scope:** Inventory of what nautilus-trader 1.231.0 already provides for 0–1-priced binary-outcome prediction markets. This is an inventory, **not** a design for Breezy's adapter.

> Paths below are relative to the installed package root
> `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/`
> or the vendored docs root `/home/jon/breezy/docs/reference/nautilus/v1.231.0/`.

---

## 0. The single most important structural fact

**1.231.0 ships TWO complete Polymarket adapters in the same wheel.** Every other finding depends on knowing which one a given doc page describes.

| | Legacy Python/Cython adapter | V2 Rust adapter (PyO3) |
|---|---|---|
| Import path | `nautilus_trader.adapters.polymarket` | `nautilus_trader.core.nautilus_pyo3.polymarket` |
| Files | `adapters/polymarket/{config,data,execution,factories,loaders,providers,fee_model,order_fill_tracker}.py` + `common/ http/ websocket/ schemas/ scripts/` | compiled into the `nautilus_pyo3` extension |
| Instrument type used | Cython `BinaryOption` (`model/instruments/binary_option.pyx`) | PyO3 `BinaryOption` |
| Importable out of the box? | **NO** — `adapters/polymarket/providers.py:21` does `from py_clob_client_v2.client import ClobClient`; that package is not installed, so `import nautilus_trader.adapters.polymarket` raises `ModuleNotFoundError`. It needs the venue extra. | **YES** — `nautilus_pyo3.polymarket` imports with no extra deps |
| Documented by | `api_reference/adapters/polymarket.md` (autodoc of `nautilus_trader.adapters.polymarket.*`) | `integrations/polymarket.md` ("This page documents the V2 integration … implemented in Rust and exposed to Python through PyO3", lines 9–11) |

Verified: `nautilus_pyo3.polymarket` exposes `PolymarketDataClientConfig`, `PolymarketExecClientConfig`, `PolymarketDataClientFactory`, `PolymarketExecutionClientFactory`, `PolymarketInstrumentProviderConfig`, `PolymarketDataLoader`, `PolymarketRtdsCryptoPrice`, `PolymarketRtdsEquityPrice`, `PolymarketUpDownEventSlugConfig`, `SignatureType`, `POLYMARKET`, `POLYMARKET_VENUE`, `POLYMARKET_CLIENT_ID`, `polymarket_trade_id`, `polymarket_trade_sort_key`.

Verified: `nautilus_pyo3.polymarket.PolymarketDataClientConfig` carries **exactly** the field names in `integrations/polymarket.md:987–1009` — `ws_max_subscriptions`, `resolve_poll_enabled`, `resolve_poll_interval_secs`, `resolve_poll_grace_secs`, `resolve_poll_max_wait_secs`, `auto_load_missing_instruments`, `auto_load_debounce_ms`, `auto_load_max_retries`, `auto_load_retry_delay_initial_secs`, `auto_load_retry_delay_max_secs`, `subscribe_new_markets`, `drop_quotes_missing_side`, `new_market_fetch_max_concurrency`, `transport_backend`, `base_url_{http,ws,gamma,data_api,rtds}`, `http_timeout_secs`, `ws_timeout_secs`, `update_instruments_interval_mins`, `instrument_config`, `has_proxy_url`.

The legacy Python config uses **different names for the same concepts** — e.g. `ws_max_subscriptions_per_connection` (`adapters/polymarket/config.py:119`, `:207`) vs the documented `ws_max_subscriptions`. **Do not copy field names from `integrations/polymarket.md` into legacy-Python-shaped code.**

---

## Verified facts

### Instrument model

1. **Two native instrument types cover this domain.** `concepts/instruments/index.md:30–31`:
   `BinaryOption` — "Binary instrument that settles to 0 or 1" (adapters: Hyperliquid, OKX, Polymarket); `BettingInstrument` — "Sports or gaming market selection" (adapter: Betfair). A third, `TokenizedAsset`, is a crypto-spot token wrapper (`concepts/instruments/tokenized_asset.md:215` — instrument class `Spot`) and is **irrelevant** to binary outcomes.

2. **`InstrumentClass` enum** (`core/rust/model.pxd`): `SPORTS_BETTING = 11`, `BINARY_OPTION = 12`. `BinaryOption` hard-sets `InstrumentClass.BINARY_OPTION` (`model/instruments/binary_option.pyx:131`); `BettingInstrument` hard-sets `InstrumentClass.SPORTS_BETTING` (`model/instruments/betting.pyx:117`).

3. **Cython `BinaryOption` constructor — exact signature** (`model/instruments/binary_option.pyx:102–124`):
   ```
   BinaryOption(
       InstrumentId instrument_id, Symbol raw_symbol, AssetClass asset_class,
       Currency currency, int price_precision, int size_precision,
       Price price_increment, Quantity size_increment,
       uint64_t activation_ns, uint64_t expiration_ns,
       uint64_t ts_event, uint64_t ts_init,
       Quantity max_quantity=None, Quantity min_quantity=None,
       maker_fee: Decimal|None=None, taker_fee: Decimal|None=None,
       str outcome=None, str description=None, str tick_scheme_name=None, dict info=None,
   )
   ```
   Extra readonly attributes are only `outcome`, `description`, `activation_ns`, `expiration_ns` (`binary_option.pxd:22–30`), plus `activation_utc` / `expiration_utc` `pd.Timestamp` properties (`binary_option.pyx:161–185`).

4. **The Cython constructor hard-codes six fields the docs list as configurable** (`binary_option.pyx:133–147`): `is_inverse=False`, `multiplier=Quantity.from_int_c(1)`, `lot_size=Quantity.from_int_c(1)`, `max_notional=None`, `min_notional=None`, `max_price=None`, `min_price=None`, `margin_init=Decimal(0)`, `margin_maint=Decimal(0)`. Verified at runtime: `BinaryOption(..., min_price=Price.from_str("0.001"))` raises `TypeError: __init__() got an unexpected keyword argument 'min_price'`.
   The field table in `concepts/instruments/binary_option.md:11–38` (which lists `max_notional`, `min_notional`, `max_price`, `min_price`, `margin_init`, `margin_maint`, `tick_scheme`) describes the **Rust/PyO3 builder**, not the Cython class. Verified: PyO3 `BinaryOption(..., min_price=…, max_price=…, tick_scheme="FIXED_PRECISION_3", margin_init=0, min_quantity=…)` constructs successfully and round-trips those values. Note the kwarg is `tick_scheme` on PyO3 but `tick_scheme_name` on Cython.

5. **0–1 probability prices are represented as ordinary `Price` values with venue-set precision.** There is no probability type, no 0–1 clamp, and no dedicated probability tick scheme in the core model. `concepts/instruments/binary_option.md:46–47`: "Many venues quote binary outcomes between zero and one, but **the venue defines** the allowed price range and tick size." The instrument is never inverse and uses multiplier and lot size of one (`:45`).
   Consequence, verified at runtime on PyO3 `BinaryOption`: `notional_value(Quantity("10"), Price("0.600")) == 6.00000000 USDC`. **Shares × probability = collateral, natively and correctly**, with no adapter arithmetic.

6. **Tick schemes: registry exists; nothing binary-specific is pre-registered.** `model/tick_scheme/base.pyx:138–155` gives `TICK_SCHEMES`, `register_tick_scheme()`, `get_tick_scheme()`, `list_tick_schemes()`. `model/tick_scheme/__init__.py:28–30` registers only `TOPIX100`, `FOREX_3DECIMAL`, `FOREX_5DECIMAL`; `implementations/fixed.pyx:153–162` additionally auto-registers `FIXED_PRECISION_{0..FIXED_PRECISION}`. The only tiered scheme for a betting venue is adapter-registered: `adapters/betfair/common.py:94–115` builds `BETFAIR_TICK_SCHEME` from `BETFAIR_PRICE_TIERS` and calls `register_tick_scheme(BETFAIR_TICK_SCHEME)` at import time. **An adapter registering its own tick scheme at module import is the sanctioned native pattern.**

7. **Polymarket's real instrument construction** (`adapters/polymarket/common/parsing.py:208–257`): `instrument_id = f"{condition_id}-{token_id}.POLYMARKET"` (`common/symbol.py:20–21`); `raw_symbol` = the token id alone; `asset_class=AssetClass.ALTERNATIVE`; `currency=pUSD`; `price_increment = Price.from_str(market_info["minimum_tick_size"])` with `price_precision = price_increment.precision`; **`size_increment` hard-coded to `Quantity.from_str("0.000001")`** (6 dp, comment at `:222–224`: "trades are reported with 6-decimal collateral increments"); `activation_ns = 0` with the comment `# TBD?`; `expiration_ns` from `end_date_iso`, falling back to **now + 10 years** when the field is missing (`:227–231`); `min_quantity=None` and `max_quantity=None` deliberately — comment at `:218–221`: "the instrument model can only carry one `min_quantity`, so leave it unset and let the venue reject out-of-bounds orders. The raw `orderMinSize` remains accessible via `instrument.info`"; the entire raw Gamma/CLOB market dict is stashed in `info=market_info`.
   Contrast: `integrations/polymarket.md:446–447` claims "The published `BinaryOption` advertises `min_price` and `max_price` equal to `tick_size` and `1 - tick_size`". That is **V2/Rust-only** — the Cython class cannot carry those fields at all (fact 4), and the legacy parser sets neither.

8. **Legacy adapter price bounds live in module constants, not on the instrument** (`adapters/polymarket/common/constants.py:29–32`): `POLYMARKET_MAX_PRICE = 0.999`, `POLYMARKET_MIN_PRICE = 0.001`, `POLYMARKET_MAX_PRECISION_TAKER = 2`, `POLYMARKET_MAX_PRECISION_MAKER = 5`.

9. **Tick size changes are handled by republishing the instrument.** `adapters/polymarket/common/parsing.py:260–287` (`update_instrument`) constructs a whole new `BinaryOption` with the new `price_increment`/`price_precision`. `integrations/polymarket.md:454–466` documents the V2 five-step book-epoch transition around this: publish updated instrument → drop local book → mark awaiting snapshot → drop `price_change` deltas → reseed from snapshot.

### Settlement / resolution / expiry

10. **There is no "market resolved to YES/NO" *event*. There is a native *data type*: `InstrumentClose`.** `concepts/data/instrument_close.md:12` — fields include `close_type: InstrumentCloseType`, values `END_OF_SESSION` or `CONTRACT_EXPIRED` (`core/rust/model.pxd`, `cpdef enum InstrumentCloseType: END_OF_SESSION = 1, CONTRACT_EXPIRED = 2`). It is a `Data` subclass (`model/data.pyx:4198`), not an `Event`. Actors/strategies receive it via `subscribe_instrument_close()` → `on_instrument_close()` (`concepts/actors.md:188`, `concepts/strategies.md:118,131`).

11. **The V2 Polymarket data client synthesises resolution into `InstrumentClose`.** `integrations/polymarket.md:744–764`: it tracks exposure at `condition_id` level, watches open binary-option instruments, waits `resolve_poll_grace_secs` after expiry then polls Gamma every `resolve_poll_interval_secs` up to `resolve_poll_max_wait_secs`; strict winner inference requires a closed binary market with exactly two token IDs, two outcomes and a binary `outcomePrices`, else falls back to CLOB `GET /markets/{condition_id}` `tokens[].winner`. On apply it emits **one `InstrumentStatus` close and one `InstrumentClose` per tracked leg — winner leg closes at `1`, loser leg at `0`, `close_type = InstrumentCloseType.ContractExpired`** (`:761–764`).
    Explicitly scoped out at `:763–764` and `:800–801`: "This event **closes Nautilus exposure and does not redeem tokens or claim funds** on-chain … Redemption is a separate account or execution workflow."

12. **`InstrumentClose` cannot be subscribed generically on Polymarket.** `integrations/polymarket.md:1269,1278–1283`: TC-D61 (instrument close) and TC-D60 (instrument status) are **Unsupported / Skip** — "resolution close events belong to open-position tracking and must remain active until exposure closes. A generic unsubscribe cannot stop that source." Calling them directly returns an explicit error; the resolution events still flow.

13. **`activation_ns` / `expiration_ns` exist on the instrument but nothing in the live engines acts on them.** Grep across the package: `expiration_ns` is consumed only by `data/engine.pyx:1433–1641` (continuous-futures series roll), `backtest/data_client.pyx:476–584` (spread leg min-expiry), and adapters/serialization. **No live execution or portfolio code path settles, closes, or values a position at `expiration_ns`.**

14. **Backtest DOES have built-in expiry settlement — and `BINARY_OPTION` is deliberately excluded from the timestamp-triggered path.** `model/instruments/base.pyx:67–72`:
    ```
    ENGINE_EXPIRING_INSTRUMENT_CLASSES = {FUTURE, FUTURES_SPREAD, OPTION, OPTION_SPREAD}
    ```
    `BINARY_OPTION` and `SPORTS_BETTING` are **not** members, so `_instrument_has_expiration` is `False` for a `BinaryOption` (`backtest/engine.pyx:4030`).
    **However** the gate at `backtest/engine.pyx:5939` is:
    ```
    if (self._instrument_has_expiration and timestamp_ns >= self.instrument.expiration_ns) or self._instrument_close is not None:
    ```
    and `_instrument_close` is set by `process_instrument_close()` when `close.close_type == InstrumentCloseType.CONTRACT_EXPIRED` (`backtest/engine.pyx:4846–4847`), which the backtest engine dispatches for any `InstrumentClose` in the data stream (`backtest/engine.pyx:1717–1719`, `:3597–3622`).
    So: **feeding an `InstrumentClose(CONTRACT_EXPIRED)` into a backtest natively cancels all open orders and closes all open positions for that instrument** (`engine.pyx:5941–5979`). Because a `BinaryOption` is neither `OptionContract` nor `CryptoOption`, it takes the generic branch: a `reduce_only` `MarketOrder` tagged `EXPIRATION_{venue}_CLOSE` per open position, filled at `settlement_prices[instrument_id]` when that venue option is configured, otherwise at the prevailing book (`engine.pyx:5964–5978`). `settlement_prices: dict[InstrumentId, float] | None = None` is a real `BacktestVenueConfig` field (`backtest/config.py:179`, docstring `:135`).
    **This is the native YES=1.0 / NO=0.0 settlement mechanism for backtests.** No equivalent exists in live trading.

15. **Polymarket has a resolution-aware order status.** `adapters/polymarket/common/parsing.py:202–203` maps `PolymarketOrderStatus.CANCELED_MARKET_RESOLVED` → `OrderStatus.CANCELED`.

### `integrations/polymarket.md` — supported vs explicitly NOT supported

16. **Products.** Binary options only. `:51` — "NautilusTrader represents Polymarket outcome tokens as `BinaryOption` instruments." Collateral is **pUSD** (`:53`, `:83–93`): an ERC-20 on Polygon backed by USDC, proxy `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`.

17. **Data feeds supported** (`:201–202`): live `L2_MBP` order book deltas, quotes, trades. Instrument definitions published by "bootstrap, configured refreshes, new-market discovery, and tick-size changes." Plus RTDS custom data (`:684–711`): `PolymarketRtdsCryptoPrice` (`crypto_prices` topic) and `PolymarketRtdsEquityPrice` (`equity_prices`), subscribed via generic `DataType(..., metadata={"symbol": ...})` with a required non-empty `symbol`.

18. **Order types.** Supported: `MARKET`, `LIMIT` (`:217–225`). **NOT supported** (each marked "*Not supported by Polymarket*"): `STOP_MARKET`, `STOP_LIMIT`, `MARKET_IF_TOUCHED`, `LIMIT_IF_TOUCHED`, `TRAILING_STOP_MARKET`.

19. **Quantity semantics — a genuine footgun** (`:227–241`): LIMIT and market SELL use base units (conditional tokens); **market BUY interprets `quantity` as quote notional in pUSD**. "a market buy order submitted with a base-denominated quantity will execute far more size than intended." Market BUYs must set `quote_quantity=True`; the execution client **denies** base-denominated market buys.

20. **Time in force** (`:262–293`): `GTC`→`GTC` (LIMIT only), `GTD`→`GTD` (LIMIT only), `FOK`→`FOK`, `IOC`→**`FAK`**. `MARKET` orders accept only `IOC`/`FOK`. Any marketable order must be worth ≥ **1 pUSD** notional; resting GTC/GTD limits are bounded only by the **5-share minimum**. GTD expiry should be set ≥ 3 minutes out (venue applies a ~1-minute buffer) and **venue expiry is reported as `OrderCanceled`, not `OrderExpired`**.

21. **Execution instructions** (`:257–260`): `post_only` supported for `GTC`/`GTD` limits only; **`reduce_only` not supported**.

22. **Explicitly NOT supported, consolidated:** order modification (cancel only) `:299`; bracket/OCO `:300,:401–402`; iceberg `:301`; batch modify `:308`; order lists / linked contingency semantics `:400`; conditional orders `:403`; position mode, leverage, margin mode `:382–385` ("No leverage available", "No margin trading"); `OrderBookDepth10` (TC-D12) `:1267,1274–1275`; generic instrument-status and instrument-close subscription (TC-D60/61) `:1268–1269`; reduce-only `:966`. Also `:972–975`: **position reports omit balances below 0.01 shares**, and a sub-minimum residual cannot be exited through the 5-share minimum order size.

23. **Batch operations supported** (`:303–341`): batch submit via `POST /orders`, max **15** orders/request (`BATCH_ORDER_LIMIT`), LIMIT only. **Retry EXISTS but is disabled by default** — batch submit runs inside `retry_manager.run("submit_orders_batch", …)` (`adapters/polymarket/execution.py:1557-1567`) with `max_retries` defaulting to `None` → `0` (`config.py:208`, `execution.py:223`). There is still no idempotency key, so a non-zero `max_retries` can double a position. *(Corrected 2026-09-01: "no retry" was an author interpolation — the cited source `:303-341` says nothing about retry. The mechanism is present and off, not absent.)*; batch cancel via `DELETE /orders`, max **1,000** IDs, chunked further by the signer's cancellation burst.

24. **Precision hierarchy is tick-size-derived** (`:429–450`): tick `0.1`→1 price dp / 2 size dp / 3 amount dp; `0.01`→2/2/4; `0.001`→3/2/5; `0.0025`→4/2/6; `0.0001`→4/2/6. Market order types (`FAK`/`FOK`) cap the direct maker amount at **2 decimal places**. Limit prices outside `tick_size … 1 - tick_size` are rejected before signing.

### Adapter module structure a new venue adapter is expected to follow

25. **The developer guide documents a RUST crate layout.** `developer_guide/adapters.md:29–71`:
    ```
    crates/adapters/<adapter>/
    ├── src/common/       # credentials, enums, models, parsing, symbols, URLs
    ├── src/http/         # client.rs error.rs models.rs parse.rs query.rs
    ├── src/websocket/    # client.rs handler.rs messages.rs parse.rs [subscription.rs] [dispatch.rs]
    ├── src/config.rs  data.rs  execution.rs  factories.rs
    ├── src/python/       # PyO3 projection
    ├── src/signing/      # when auth/tx signing is a subsystem
    └── src/lib.rs
    ```
    with Python surfaces outside the crate at `python/nautilus_trader/adapters/<adapter>/` (`:79–85`). Only `Cargo.toml` and `src/lib.rs` are universal (`:73`). It also defines a 10-phase implementation sequence (`:125–243`) and the six-component lifecycle contract `start / connect / disconnect / stop / reset / dispose` (`:342–353`).
    **This is not the path for a pure-Python adapter.**

26. **The Python-adapter contract is `concepts/adapters.md` + `adapters/_template/`.** `concepts/adapters.md:38–45` gives the five components: `HttpClient` (REST), `WebSocketClient` (streaming), `InstrumentProvider` (parses venue responses into `Instrument` objects), `DataClient` (subscriptions/requests), `ExecutionClient` (submit/modify/cancel). The in-tree skeleton is `adapters/_template/{__init__,core,data,execution,providers}.py` — `core.py:20` = one `Venue` constant; `providers.py:30` `TemplateInstrumentProvider(InstrumentProvider)`; `data.py` enumerates every `Subscribe*`/`Unsubscribe*`/`Request*` command the client may override.
    The bundled **legacy Polymarket** adapter is the fullest in-tree Python example of that shape: `__init__.py` (re-exports) → `common/{constants,credentials,symbol,enums,parsing,conversion,cache,deltas,gamma_markets,retry,sanitization,types}.py` → `http/{client-conversion,errors}.py` → `websocket/{client,types}.py` → `schemas/{book,order,trade,user}.py` → `providers.py` → `config.py` → `data.py` / `execution.py` → `factories.py`, plus `loaders.py`, `fee_model.py`, `order_fill_tracker.py`, `scripts/`.

27. **Betfair shows the same Python shape with extras:** `adapters/betfair/{client,common,config,constants,data,data_types,execution,factories,providers,sockets}.py` + `parsing/` + a compiled `orderbook.pyx`.

### Kalshi

28. **No Kalshi support and no roadmap mention in 1.231.0. Plainly: NO.**
    - `grep -rn "Kalshi\|kalshi\|KALSHI"` over the entire vendored `v1.231.0/` doc tree → **0 hits**.
    - `integrations/index.md:8–27` lists every supported integration; Kalshi is absent. Only `Polymarket | POLYMARKET | Prediction Market (DEX) | stable` covers this venue class.
    - Case-insensitive grep for `kalshi` across all installed `.py`/`.pyx`/`.pyi` → **0 files**.
    - `[x for x in dir(nautilus_pyo3) if 'kalshi' in x.lower()]` → `[]`.

### Betfair — what transfers to a prediction market

29. **`BettingInstrument` is odds-shaped, not probability-shaped.** `concepts/instruments/betting_instrument.md:56–59`: asset class `Alternative`, instrument class `SportsBetting`, one instrument per selection/runner, tick scheme for valid odds steps, **"Margin defaults to one because staking a bet typically reserves the full stake"** (`model/instruments/betting.pyx:132–133`: `margin_init or Decimal(1)`, `margin_maint or Decimal(1)`).

30. **`BettingInstrument.notional_value` ignores price entirely** (`model/instruments/betting.pyx:276–290`): `notional = quantity * multiplier`, i.e. stake-denominated. `BinaryOption` uses the base implementation (`quantity * price`). These are **different economics** — do not swap one for the other.

31. **`BettingAccount` math is decimal-odds math and is WRONG for 0–1 prices.** `accounting/accounts/betting.pyx:91–99`:
    ```
    cpdef stake(Quantity quantity, Price price):  return quantity * (price - 1)
    cpdef liability(quantity, price, side): SELL -> quantity ; BUY -> stake(quantity, price)
    ```
    At a probability price of `0.60`, `stake()` returns a **negative** number. `AccountType.BETTING` presumes odds ≥ 1.01. Correspondingly, the Polymarket execution client uses **`AccountType.CASH`**, not `BETTING` (`adapters/polymarket/execution.py:175`, with `oms_type=OmsType.NETTING` at `:173`, `base_currency=pUSD` at `:176`).

32. **There IS a native probability↔odds bridge.** `nautilus_pyo3` exports `probability_to_bet`, `inverse_probability_to_bet`, `Bet`, `BetPosition`, `BetSide`, `calc_bets_pnl`, `betting_account_from_account_events`, `ProbabilisticFillModel`. Verified at runtime:
    ```
    probability_to_bet(Decimal("0.60"), Decimal("10"), OrderSide.BUY)
      -> Bet(Back @ 1.666… x 5.999…)
         exposure 10.0 ; liability 6.0 ; outcome_win_payoff 4.0 ; outcome_lose_payoff -6.0
    ```
    `Bet` exposes `stake/price/side/exposure()/liability()/profit()/outcome_win_payoff()/outcome_lose_payoff()/hedging_bet()/hedging_stake()/from_stake()/from_liability()`; `BetPosition` exposes `add_bet()/exposure/realized_pnl/unrealized_pnl()/total_pnl()/flattening_bet()/as_bet()/price/side/reset()`. Docstring: "For a BUY side, this creates a BACK bet; for SELL, a LAY bet." `model/instruments/betting.pyx:318–322` (`order_side_to_bet_side`) confirms the Nautilus convention: **BUY → LAY, SELL → BACK** for Betfair order sides — note this is the *opposite* mapping from `probability_to_bet`; do not assume one from the other.

33. **Betfair is the in-tree exemplar of hand-written custom `Data` types.** `adapters/betfair/data_types.py`: `BSPOrderBookDelta(OrderBookDelta)` `:49`; `BetfairTicker(Data)` `:151`; `BetfairStartingPrice(Data)` `:260`; `BetfairRaceRunnerData(Data)` `:333`; `BetfairRaceProgress(Data)` `:456`; `BetfairOrderVoided(Data)` `:587`; `BetfairSequenceCompleted(Data)` `:727–728` — **the only one using `@customdataclass`**; the rest hand-write `__init__`/`to_dict`/`from_dict` and then explicitly call `register_serializable_type(...)` + `register_arrow(...)` per type (`:732–800+`). Imports at `:25`, `:34`, `:35`.
    `integrations/betfair.md:336–341`: custom data "is delivered automatically when subscribed to markets — no explicit subscription is required"; strategies register a handler with `self.subscribe_data(DataType(BetfairTicker), client_id=BETFAIR_CLIENT_ID)` (`:404–411`).
    **Directly transferable to Breezy:** a weather/NWS observation type, a market-metadata type, or a resolution-source type follows exactly this pattern.

34. **Betfair's tiered tick scheme is the template for a non-uniform prediction-market grid** (`integrations/betfair.md:216–230`, `adapters/betfair/common.py:94–115`): ten `(low, high, increment)` tiers from `(1.01, 2, 0.01)` to `(100, 1010, 10)`, wrapped in `TieredTickScheme` and registered globally at import. `BETFAIR_FLOAT_TO_PRICE`, `MAX_BET_PRICE`, `MIN_BET_PRICE` are derived from `.ticks` (`common.py:112–114`).

### Accounting for a 0–1-priced binary instrument

35. **Three account types** (`concepts/accounting.md:15–21`): `Cash` (locks notional for every position a pending order would open), `Margin` (initial + maintenance), `Betting` ("Stake required by the venue; no leverage"). `concepts/accounting.md:50–54` on betting accounts: "the engine locks only the stake required by the venue; leverage and margin do not apply."

36. **A `BinaryOption` on a `CashAccount` behaves correctly for BUY and conservatively for SELL.** `accounting/accounts/cash.pyx:357–420`: BUY locks `instrument.notional_value(qty, price)` in `quote_currency` = `qty × p` pUSD — exactly right. For SELL, `base_currency = instrument.get_base_currency() or instrument.quote_currency`; `BinaryOption` inherits the base `get_base_currency()` returning `None` (`model/instruments/base.pyx`, ~line 493), so `base_currency` falls back to pUSD and the lock is `quantity` (line 405) — i.e. **N shares locks N pUSD**, the maximum payout / naked-sell liability, not the sale proceeds. Conservative and safe, but over-locks a covered sell.

37. **PnL is the ordinary linear formula; no binary special case.** `concepts/positions.md:252–257`: `realized_pnl = (exit_price − entry_price) × closed_quantity × multiplier`. With `multiplier = 1` (fact 3/5), a YES bought at 0.35 and resolved at 1.00 yields `0.65 × qty` pUSD. **The engine does not know the resolution price — a fill at 1.0 or 0.0 must be produced by settlement (fact 14 in backtest; nothing in live).**

38. **Cost currency = quote currency** for `BinaryOption` (`model/instruments/base.pyx` `get_cost_currency()`: base for inverse, quote otherwise; `BinaryOption.is_inverse` is hard-`False`). `concepts/accounting.md:88` restates this. `concepts/positions.md:296` adds: PnL "is calculated in the instrument's cost currency."

39. **Margin is a non-issue and must stay that way.** Cython `BinaryOption` hard-sets `margin_init=Decimal(0)`, `margin_maint=Decimal(0)` (`binary_option.pyx:146–147`). `integrations/polymarket.md:384–385`: "No leverage available", "No margin trading."

40. **`pUSD` is a first-class native currency in 1.231.0.** `nautilus_trader.model.currencies.pUSD` — code `pUSD`, precision **6**, `currency_type` crypto. It is also whitelisted as USD-equivalent for accounting: `model/instruments/base.pyx:74–90` `USD_EQUIVALENT_CURRENCY_CODES` includes `"pUSD"` (line 83) alongside `BUSD`, `FDUSD`, `TUSD`, `USD`, etc. (`USDC` precision is 8, for contrast.)

### Fees

41. **Polymarket's fee formula is documented and native to both adapters.** `integrations/polymarket.md:506–516`:
    ```
    platform fee = shares * rate * (price * (1 - price)) ^ exponent
    ```
    Current public schedule uses exponent `1`, i.e. Polymarket's `C * feeRate * p * (1 - p)`. Fees **peak at p = 0.50**, decay toward the extremes, and **apply only to taker fills**.
    Published taker `feeRate` by category (`:518–530`) — **Weather: 0.05 taker, 0 maker, 25% maker rebate**. (Crypto 0.07/20%; Sports 0.05/15%; Finance, Politics, Mentions, Tech 0.04/25%; Economics, Culture, Other 0.05/25%; Geopolitics 0.)
    `:532–533`: every adapter-signed order carries a hard-coded Nautilus builder code whose builder fee rate is **fixed at zero and not configurable**. `:535`: `FillReport.commission` is in pUSD, rounded to 5 dp.

42. **The fee model IS expressible in native config — via a `FeeModel`, and there are two implementations.**
    - **V2/Rust:** `integrations/polymarket.md:542–555` documents `ProbabilityPriceFeeModel`, passed to `BacktestVenueConfig.fee_model`. It "reads maker and taker rates from the binary option instrument and applies the same probability-price curve" and **"does not support other fee exponents or future maker-rebate distributions."** Verified present: `nautilus_pyo3.ProbabilityPriceFeeModel` instantiates. **The documented Python import path `from nautilus_trader.execution import ProbabilityPriceFeeModel` (`:548`) FAILS on the 1.231.0 wheel** — `ImportError: cannot import name 'ProbabilityPriceFeeModel' from 'nautilus_trader.execution'`. Reach it as `nautilus_trader.core.nautilus_pyo3.ProbabilityPriceFeeModel`.
    - **Legacy Python:** `adapters/polymarket/fee_model.py:230` `PolymarketFeeModelConfig(FeeModelConfig)` and `:245` `PolymarketFeeModel(FeeModel)` — docstring `:251` `fee = qty * fee_rate * p * (1 - p)`, "`fee_rate` is taken from `instrument.taker_fee` and `p` is the fill price in [0, 1]. Maker fees remain zero." Plus `maker_rebates_enabled`, `infer_maker_rebate_rate()` `:132`, `calculate_maker_rebate()` `:180`.
    - Cython-side generic fee models available: `nautilus_trader.backtest.models.{FeeModel, FixedFeeModel, MakerTakerFeeModel, PerContractFeeModel}`. PyO3 adds `CappedOptionFeeModel`, `TieredNotionalOptionFeeModel`, `ProbabilityPriceFeeModel`.
    - Per-instrument `maker_fee`/`taker_fee` decimals are carried natively on `BinaryOption` (`binary_option.pyx:118–119, 148–149`) and populated by `extract_fee_rates(market_info)` (`adapters/polymarket/common/parsing.py:233`).
    - **Betfair fees:** `integrations/betfair.md` documents no commission schedule; `BettingInstrument` defaults `maker_fee`/`taker_fee` to `0` (`concepts/instruments/betting_instrument.md:44–45`). Betfair market commission is not modeled natively.

---

## Native capability inventory

| Capability | Native in 1.231.0? | Where | What Breezy must still supply |
|---|---|---|---|
| Binary-outcome instrument type | **Yes** | `BinaryOption` — `model/instruments/binary_option.pyx:42`; PyO3 `nautilus_pyo3.BinaryOption` | Choose Cython vs PyO3 deliberately; they have **different constructors** (fact 4). Populate `info` with anything the class can't carry (`min_price`, `orderMinSize`, slug, resolution source). |
| 0–1 price representation | **Yes** (as plain `Price`) | `concepts/instruments/binary_option.md:46–47` | Venue-supplied bounds and tick grid; no native clamp to [0,1]. |
| `qty × probability = collateral` | **Yes** | base `Instrument.notional_value` (`instruments/base.pyx:798`); verified `10 @ 0.600 → 6.00` | Nothing. |
| Tick scheme registry + tiered schemes | **Yes** | `model/tick_scheme/base.pyx:138–155`; `TieredTickScheme` | Register a Polymarket.US scheme at adapter import (Betfair pattern, `adapters/betfair/common.py:115`) — no binary-market scheme is pre-registered. |
| Dynamic tick-size change | Pattern only | `adapters/polymarket/common/parsing.py:260–287`; `integrations/polymarket.md:454–466` | Re-publish instrument + drop/reseed book yourself if Polymarket.US changes ticks. |
| Resolution / settlement data type | **Yes** (`InstrumentClose`) | `model/data.pyx:4198`; `concepts/data/instrument_close.md` | The **producer**: poll/subscribe the venue's resolution source, infer the winner, emit `InstrumentClose(price=1|0, CONTRACT_EXPIRED)` per leg. |
| Backtest settlement of binary positions at 1/0 | **Yes** | `backtest/engine.pyx:4846–4847, 5939–5979`; `settlement_prices` in `backtest/config.py:179` | Feed `InstrumentClose(CONTRACT_EXPIRED)` into the data stream and set `settlement_prices`. `BINARY_OPTION` is **not** in `ENGINE_EXPIRING_INSTRUMENT_CLASSES`, so timestamp alone will not settle it. |
| **Live** settlement of binary positions | **NO** | nothing consumes `InstrumentClose` in `execution/engine.pyx` or `portfolio/portfolio.pyx` | Everything: the live position must be closed by real venue fills, or reconciled flat from venue position reports. |
| Redemption / claiming winnings | **NO** | explicitly out of scope, `integrations/polymarket.md:763–764, 800–801` | Entire workflow, if Polymarket.US requires one. |
| `activation_ns` / `expiration_ns` fields | **Yes** | `binary_option.pxd:27–30` | Populate them; nothing in the live engines reads them. |
| Cash accounting for 0–1 prices | **Yes** | `accounting/accounts/cash.pyx:357–420`; `AccountType.CASH` used by Polymarket (`adapters/polymarket/execution.py:175`) | Nothing for BUY. Be aware SELL over-locks (`qty` pUSD, fact 36). **Do not use `AccountType.BETTING`** (fact 31). |
| Linear PnL with multiplier 1 | **Yes** | `concepts/positions.md:252–257` | Nothing. |
| Margin | N/A by design | `binary_option.pyx:146–147` (`margin_init=margin_maint=0`) | Nothing — keep it zero. |
| `pUSD` currency | **Yes** | `model/currencies.pUSD` (precision 6); USD-equivalent at `instruments/base.pyx:83` | Decide whether Polymarket.US settles in `USD` (native) or something else; register via `Currency.register` only if genuinely new. |
| Probability-price fee model | **Yes ×2** | `nautilus_pyo3.ProbabilityPriceFeeModel`; `adapters/polymarket/fee_model.py:245` | Polymarket.US's actual schedule (rate/exponent/rebate) — the native models assume exponent 1. Note the documented `nautilus_trader.execution` import path is broken (fact 42). |
| Per-instrument maker/taker fee fields | **Yes** | `binary_option.pyx:118–119` | Parse the venue's fee schedule into them. |
| Probability ↔ decimal-odds conversion | **Yes** | `nautilus_pyo3.{probability_to_bet, inverse_probability_to_bet, Bet, BetPosition, calc_bets_pnl}` | Nothing, if you need odds-space math. |
| Custom `Data` types (weather, resolution metadata) | **Yes** | `model/custom.py` `@customdataclass`; exemplars in `adapters/betfair/data_types.py` | Define the types; register `register_serializable_type` + `register_arrow` if hand-writing `__init__`. |
| Adapter base classes + lifecycle | **Yes** | `live/data_client.py`, `live/execution_client.py`, `adapters/_template/` | Venue protocol only. |
| WebSocket auto-reconnect with backoff | **Yes** | `nautilus_pyo3.WebSocketConfig` (`core/nautilus_pyo3.pyi:5530–5546`): `reconnect_timeout_ms=10_000`, `reconnect_delay_initial_ms=2_000`, `reconnect_delay_max_ms=30_000`, `reconnect_backoff_factor=1.5`, `reconnect_jitter_ms=100`, `reconnect_max_attempts`, `idle_timeout_ms`, `heartbeat`, `heartbeat_msg` | **Re-subscription replay** after `post_reconnection` fires (`nautilus_pyo3.pyi:5555`) — see `adapters/polymarket/websocket/client.py:375–420` for the in-tree recipe. |
| Reconciliation orchestration | **Yes** | `LiveExecutionEngine` + `live/reconciliation.py` | The four `generate_*` report coroutines (`live/execution_client.py:343–424`) — **note they take command objects, not raw IDs**. |
| Order-book epoch / snapshot management | Partly | `manage_book` in data client configs | Epoch reset on tick change (fact 9). |
| Kalshi | **NO** | zero hits in docs or source | Everything. |

---

## Polymarket.COM (bundled) vs Polymarket.US (Breezy's target)

Based only on what is verifiable in the 1.231.0 source and vendored docs. Polymarket.US specifics below are asserted by the project brief, not by Nautilus docs — Nautilus documents nothing about Polymarket.US.

### Reusable as-is (venue-agnostic, no Polymarket.COM coupling)

| Asset | Evidence |
|---|---|
| `BinaryOption` as the instrument type | `concepts/instruments/binary_option.md:3–7` — "It can model prediction markets, binary options, **or venue-specific yes/no contracts**." Nothing in it is chain-aware. |
| `AccountType.CASH` + `OmsType.NETTING` choice | `adapters/polymarket/execution.py:173–175` — an economics decision about 0–1 binaries, not a Polygon decision. |
| Probability-price fee curve `f = qty·rate·p(1−p)` | `adapters/polymarket/fee_model.py:251`; `nautilus_pyo3.ProbabilityPriceFeeModel`. Rates differ per venue; the **curve shape** is generic to binary markets. |
| Instrument-republish-on-tick-change | `common/parsing.py:260–287` — pure model manipulation. |
| Resolution → `InstrumentClose(1|0, CONTRACT_EXPIRED)` per leg | `integrations/polymarket.md:761–764`. The *watchlist → grace → poll → strict-winner-inference → emit* algorithm is venue-agnostic; only the polling endpoint is not. |
| `DUST_SNAP_THRESHOLD` fill-normalisation concept | `integrations/polymarket.md:614–646`. Any venue with fixed-point wire amounts and a minimum order size has this problem. |
| WebSocket reconnect + `handler_reconnect` wiring | `adapters/polymarket/websocket/client.py:375–420`. |
| Module layout `common/ → http/ → websocket/ → schemas/ → providers → config → data/execution → factories` | The shape referenced by the project's skill; nothing venue-specific about it. |
| Auto-load-missing-instruments + debounce/coalesce/backoff pattern | `integrations/polymarket.md:713–742`. Any venue with thousands of short-lived markets needs it. |
| `cache.purge_instrument` housekeeping recipe | `integrations/polymarket.md:803–832`. Core cache API, not adapter code. |

### Load-bearing and incompatible

| Coupling | Evidence in 1.231.0 |
|---|---|
| **EIP-712 / Polygon wallet signing** | `signature_type: int = 0` (EOA) with modes 1 Magic-proxy, 2 Gnosis-Safe-proxy, 3 ERC-1271 deposit wallet (`adapters/polymarket/config.py:107–108, 196–197`; `integrations/polymarket.md:103–114`). Signing itself is delegated to the external `py_clob_client_v2` package (`adapters/polymarket/providers.py:21`) — **that whole dependency disappears for a fiat DCM**. |
| **`private_key` / `funder` credential model** | `common/credentials.py:33,37`; `POLYMARKET_PK`, `POLYMARKET_FUNDER`. There is no signer/funder split on an off-chain fiat account. |
| **On-chain allowances** | `integrations/polymarket.md:124–152`; `adapters/polymarket/scripts/set_allowances.py`. Meaningless off-chain. |
| **pUSD collateral + Polygon proxy contract** | `integrations/polymarket.md:83–93`; `currency=pUSD` at `common/parsing.py:243,273`. A fiat DCM settles in USD. |
| **`condition_id`-`token_id` instrument ID scheme** | `common/symbol.py:20–41` — `InstrumentId` is `f"{condition_id}-{token_id}.POLYMARKET"` and `get_polymarket_condition_id` / `get_polymarket_token_id` **parse by splitting on `-` and indexing `[0]`/`[1]`**. A slug-based venue breaks this outright, and `raw_symbol` is the bare ERC-1155 token id. |
| **Gamma / CLOB / Data-API endpoint triple** | `base_url_gamma`, `base_url_data_api`, `base_url_http`, `base_url_rtds` (`integrations/polymarket.md:990–992`); Gamma keyset filter vocabulary `:1080–1107`. Entirely Polymarket.COM's API surface. |
| **Per-signer CLOB tier rate limiting** | `integrations/polymarket.md:875–919`. Tiers keyed on 30-day maker wallet volume via `Poly-RateLimit-Tier` headers. |
| **`market_resolved` / UMA resolution semantics** | `integrations/polymarket.md:752–759` (`outcomePrices`, `tokens[].winner`, `uma_resolution_status`). |
| **Trade lifecycle `MATCHED → MINED → CONFIRMED / RETRYING / FAILED`** | `integrations/polymarket.md:476–492`. These are blockchain finality states. A fiat DCM fill is final at match; the `OrderFillVoided`-on-`FAILED` path has no analogue. |
| **`quote_quantity=True` market-BUY semantics** | `integrations/polymarket.md:227–241`. A CLOB-specific quirk, not a universal prediction-market rule — must be re-verified against Polymarket.US, never assumed. |
| **1 pUSD marketable minimum / 5-share resting minimum** | `integrations/polymarket.md:282–287`. Venue-specific numbers. |

---

## Traps

1. **`integrations/polymarket.md` and `api_reference/adapters/polymarket.md` describe DIFFERENT adapters that both ship in 1.231.0.** Field names, import paths, and behaviors diverge. Always ask which one before quoting a fact. (§0)
2. **Three documented import paths in `integrations/polymarket.md` do not resolve in the 1.231.0 wheel** as written: `from nautilus_trader.execution import ProbabilityPriceFeeModel` (`:548`), `from nautilus_trader.adapters.polymarket import PolymarketRtdsCryptoPrice` (`:691`), and `from nautilus_trader.adapters.polymarket import PolymarketInstrumentProviderConfig` (`:1131`). All three resolve under `nautilus_trader.core.nautilus_pyo3`. `nautilus_trader.adapters.polymarket.__init__` exports a **different, legacy** set (`__init__.py:46–64`).
3. **`import nautilus_trader.adapters.polymarket` raises `ModuleNotFoundError: No module named 'py_clob_client_v2'`** on a bare 1.231.0 install. Reading its source is fine; importing it is not.
4. **The `BinaryOption` field table in `concepts/instruments/binary_option.md` is the Rust builder, not the Cython constructor.** Six documented fields are hard-coded and un-passable in Cython; `tick_scheme` is named `tick_scheme_name`.
5. **`BINARY_OPTION` is deliberately absent from `ENGINE_EXPIRING_INSTRUMENT_CLASSES`.** A backtest will NOT settle a binary position when the clock passes `expiration_ns`. It settles only on an injected `InstrumentClose(CONTRACT_EXPIRED)`.
6. **`InstrumentClose` is `Data`, not an `Event`, and no live engine consumes it.** Emitting it in live trading publishes an observation; it does not flatten a position, credit pUSD, or generate a fill.
7. **`AccountType.BETTING` is a trap for 0–1 prices.** `stake() = quantity * (price - 1)` goes negative below 1.0. Use `CASH`.
8. **`BettingInstrument.notional_value` ignores price** (stake-denominated); `BinaryOption.notional_value` uses price. Swapping instrument types silently changes account locking and PnL.
9. **`probability_to_bet` maps BUY→BACK; `order_side_to_bet_side` maps BUY→LAY.** Two native helpers, opposite conventions. Read the one you're calling.
10. **A `CashAccount` SELL of a `BinaryOption` locks `quantity` pUSD, not `quantity × price`** — because `get_base_currency()` is `None` and falls back to the quote currency. Expect over-locking on covered sells.
11. **Polymarket market BUY uses quote notional; market SELL uses base.** If Polymarket.US differs, a copied assumption silently multiplies order size by ~1/p.
12. **Venue-expired GTD orders arrive as `OrderCanceled`, not `OrderExpired`** (`integrations/polymarket.md:289–293`). Strategy state machines keyed on `OrderExpired` will hang.
13. **`min_quantity` cannot express both a share minimum and a notional minimum.** The legacy parser leaves it `None` on purpose (`common/parsing.py:218–221`) and lets the venue reject. Setting it will mask one of the two constraints.
14. **`expiration_ns` silently defaults to now + 10 years when `end_date_iso` is missing** (`common/parsing.py:230–231`). Any Breezy logic keying resolution polling off `expiration_ns` must treat that sentinel explicitly.
15. **The developer-guide adapter layout is a Rust crate layout.** Following `developer_guide/adapters.md:29–71` literally for a Python adapter produces a directory structure that does not apply.
16. **Position reports omit sub-0.01-share balances** (`integrations/polymarket.md:972–975`); an absent report is not proof of flat.
17. **`nautilus_trader.core.nautilus_pyo3.pyi` is an incomplete stub.** `OrderFillVoided` and `ProbabilityPriceFeeModel` are absent from the `.pyi` but present at runtime. Grepping the stub to prove a symbol does not exist gives false negatives — use `dir(nautilus_pyo3)`.

---

## Answers to the eight questions, at a glance

| # | Question | Answer |
|---|---|---|
| 1 | Native binary instrument type(s)? | `BinaryOption` (primary) and `BettingInstrument` (odds-shaped, wrong economics). Constructor: facts 3–4. Precision from venue tick size; multiplier and lot size fixed at 1; never inverse. Tick scheme via optional registered-name lookup; **no binary scheme pre-registered**. 0–1 prices are plain `Price` objects; `qty × p` = collateral natively. |
| 2 | Settlement / resolution / expiry? | **No native "resolved to YES/NO" event.** `activation_ns`/`expiration_ns` fields exist but no live engine reads them. `InstrumentClose(close_type=CONTRACT_EXPIRED)` is the native carrier; the V2 Polymarket data client synthesises it at 1/0 per leg. In **backtest** it settles positions (facts 14). In **live**, open positions do nothing at expiry. |
| 3 | What `integrations/polymarket.md` documents as supported / not | Facts 16–24. Supported: BinaryOption products, MARKET+LIMIT, GTC/GTD/FOK/IOC→FAK, post_only, L2_MBP/quotes/trades, RTDS custom data, batch submit (15) and batch cancel (1000), position/order/fill queries. **Not**: all stop/trigger/trailing types, reduce_only, order modification, bracket/OCO/iceberg/order-lists/conditional, batch modify, leverage/margin/position-mode, `OrderBookDepth10`, generic instrument-status/close subscription. |
| 4 | Documented adapter module structure | Two answers: the **Rust crate** layout in `developer_guide/adapters.md:29–71` (`common/ http/ websocket/ config.rs data.rs execution.rs factories.rs python/ signing/ lib.rs`) and the **Python** five-component contract in `concepts/adapters.md:38–45` realised by `adapters/_template/` and, most fully, by the legacy Polymarket and Betfair packages. Facts 25–27. |
| 5 | Kalshi support or roadmap in 1.231.0? | **No.** Zero hits across the entire vendored doc tree, zero in installed source, zero in `dir(nautilus_pyo3)`, absent from `integrations/index.md`. Fact 28. |
| 6 | What Betfair demonstrates that transfers | Per-selection instrumentation, tiered tick scheme registered at adapter import, seven hand-written custom `Data` types with explicit `register_serializable_type`/`register_arrow`, auto-delivered custom data on market subscription, and the native probability↔odds bridge (`probability_to_bet` / `Bet` / `BetPosition`). Facts 29–34. |
| 7 | Native PnL and margin for a 0–1 binary | PnL: ordinary linear `(exit − entry) × qty × 1` in the quote (cost) currency — no binary special case. Margin: zero by construction; use `AccountType.CASH`, never `BETTING`. Author must supply: the settlement fills at 1.0/0.0 (nothing produces them in live), and awareness that SELL over-locks. Facts 35–40. |
| 8 | Fees, and native config expressibility | Yes, documented and yes, expressible. Curve `qty·rate·p(1−p)`, taker-only, peaks at p=0.5; **Weather category taker rate 0.05 with 25% maker rebate**. Native `FeeModel` implementations: `nautilus_pyo3.ProbabilityPriceFeeModel` (exponent 1 only) and legacy `PolymarketFeeModel` + `PolymarketFeeModelConfig`. Per-instrument `maker_fee`/`taker_fee` decimals on `BinaryOption`. Wired via `BacktestVenueConfig.fee_model`. Betfair commission is **not** modeled. Facts 41–42. |
