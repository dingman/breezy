---
name: nautilus-trader-patterns
description: Nautilus Trader 1.231.0 native extension points — the Cython Python surface, custom Data types, ParquetDataCatalog, backtest replay, adapter base classes, and the verified traps that silently produce wrong results. Stops reinvention of what Nautilus already provides, and stops reliance on docs that describe a different API surface.
---

# Nautilus Trader Patterns — 1.231.0

> **Every claim below was verified on 2026-08-22 by executing against the installed
> `nautilus-trader 1.231.0` in `.venv/`, or by reading `file:line` in that install.**
> The previous revision of this file carried twelve claims that were wrong; they are
> corrected here and listed in "Corrected claims" at the bottom so nobody reintroduces them.

## Prime Directive: Nautilus Trader is IMMUTABLE

Start from the null hypothesis: **assume Nautilus already provides the functionality until proven otherwise.**
Never modify, patch, fork, bypass, or reimplement its foundation. Extend only through intended native mechanisms.

Before building any new infrastructure: investigate the extension point, determine whether native
capability satisfies it, reuse or extend, and build new only on concrete evidence that it does not exist.

---

## FIRST: know which API surface you are reading about

1.231.0 ships **three parallel surfaces**. Most of the official documentation describes the two
Breezy does *not* use. This is the single largest source of wasted effort in this project.

| Surface | Custom data | Actor | `DataType` first arg | Ours? |
|---|---|---|---|---|
| **Cython Python** | `@customdataclass`, `register_arrow` | `Actor` | **class object** | **YES** |
| PyO3 Python | `customdataclass_pyo3`, `nautilus_pyo3.register_custom_data_class` | — | **string** | no |
| Rust | — | `DataActor`, `DataActorCore` | — | no |

Verified in the install:

```
from nautilus_trader.model.custom import register_custom_data_class  → ImportError
from nautilus_trader.common.actor  import DataActor                  → ImportError
DataType("GreeksData", {})  → TypeError: expected type, got str
DataType(GreeksData,   {})  → OK
nautilus_pyo3.register_custom_data_class                             → exists
```

So `register_custom_data_class`, `DataActor`, and string-first `DataType` are **not** signs of a
newer version — they are present in 1.231.0, on surfaces we don't use. `concepts/custom_data.md`
is entirely about the PyO3 stack and says so at `:375-383`. `concepts/actors.md:61` reads
*"Rust authors implement `DataActor`"*. `register_arrow` appears in **one** file of the 206-page tag tree.

**The website is also a different major version.** `nautilustrader.io/docs/` serves 2.x/develop;
there is no version-pinned URL for 1.231.0 (all 404). Reliable tell: `customdataclass` occurs
**zero** times in the 2.x corpus. Vendored authoritative docs: `docs/reference/nautilus/v1.231.0/`.

---

## What Nautilus Provides FREE (do not rebuild)

### Adapter scaffolding

- **`LiveDataClient`** (`live/data_client.py`) — non-market/custom data feeds. `venue=None` allowed (`:92-93`).
- **`LiveMarketDataClient`** — market data. Requires an `instrument_provider` and hard-validates it (`:361`), so it is structurally unusable for instrument-less data.
- **`LiveExecutionClient`** (`live/execution_client.py`).

`LiveDataClient` has exactly **five** coroutines: `_connect`/`_disconnect` **required**;
`_subscribe`/`_unsubscribe`/`_request` **optional**, each taking a message object
(`SubscribeData`/`UnsubscribeData`/`RequestData`). The ~40 typed `_subscribe_*`/`_request_*`
variants belong to `LiveMarketDataClient` only.

**Do not override an optional method just to raise `NotImplementedError`.** The base already does,
and every call is swallowed into `self._log.exception(...)` by `_on_task_completed`
(`live/data_client.py:197-222`) — it never reaches the engine, node, or strategy.

### Factory & TradingNode wiring

```python
@staticmethod
def create(loop, name, config, msgbus, cache, clock) -> LiveDataClient:
    return CustomDataClient(config, msgbus, cache, clock)

# Registration takes a NAME and the factory CLASS — not a bound method:
node.add_data_client_factory("WEATHER", WeatherLiveDataClientFactory)
node.add_exec_client_factory("POLYMARKET_US", PolymarketUSExecClientFactory)
```

`add_data_client_factory(name: str, factory: type[LiveDataClientFactory]) -> None` (`live/node.py:230`).
`name` must match the key in the `data_clients` config dict.

### Custom Data types

**PRIMARY PATTERN (recommended)**: hand-written `Data` subclass + exactly ONE `register_arrow`.
This is documented at `concepts/data/index.md:1531-1670` with in-tree proof in `adapters/betfair/data_types.py`
(six patterns at `:738-805`), `adapters/databento/`, `adapters/binance/`, and `common/signal.py`.
Use this whenever the type needs **nullable fields, `date`/`Enum` fields, or a decoder that raises on drift**.

```python
# Route B — hand-written. Full control, no hidden injection, schema resilience.
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import register_arrow

class WeatherObs(Data):
    def __init__(self, station: str, temp_f: float, ts_event: int, ts_init: int):
        self.station = station
        self.temp_f = temp_f
        self._ts_event = ts_event
        self._ts_init = ts_init
    
    @property
    def ts_event(self) -> int:
        return self._ts_event
    
    @property
    def ts_init(self) -> int:
        return self._ts_init
    
    def to_dict(self) -> dict:
        return {"station": self.station, "temp_f": self.temp_f}
    
    @classmethod
    def from_dict(cls, values: dict) -> WeatherObs:
        return cls(values["station"], float(values["temp_f"]), values["ts_event"], values["ts_init"])
    
    @classmethod
    def schema(cls):
        return pa.schema([
            pa.field("station", pa.string(), nullable=False),
            pa.field("temp_f", pa.float64(), nullable=False),  # nullable is explicit and safe
            pa.field("ts_event", pa.int64()),
            pa.field("ts_init", pa.int64()),
        ])

register_arrow(WeatherObs, WeatherObs.schema(), encoder, decoder)  # once, at module scope
```

**SECONDARY ROUTE**: the convenience decorator. Injects `__init__`, `__repr__`, `to_dict`, `from_dict`,
`register_serializable_type` and `register_arrow`. Use only when all fields are among the 8 supported types
and you don't need drift detection.

```python
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.core.data import Data

@customdataclass
class WeatherObs(Data):
    station: str
    temp_f: float
```

**Route A supports exactly 8 annotations** (`model/custom.py:245-254`):
`InstrumentId, str, bool, float, int, bytes, ndarray, dict`.
Anything else — **including `float | None`** — raises `TypeError` at class-definition time.

**Never pass `frozen=True`.** Kwargs forward to `dataclass(cls, **kwargs)` (`model/custom.py:42`),
then the injected `__init__` assigns `self._ts_event` (`:51`). The class *defines* fine and then
raises `FrozenInstanceError: cannot assign to field '_ts_event'` on first construction. Verified.

If you hand-write `__init__`, `to_dict`, `from_dict`, or `_schema`, the decorator skips injecting
that member (`not in cls.__dict__` guards at `:88,105,157`).

`register_arrow` **silently overwrites** on a second call for the same class;
`register_serializable_type` raises `KeyError` and keys on `cls.__name__`, not the class object
(`serialization/base.pyx:335-336`). **Never call `register_arrow` twice for the same class** — the second call
wins in the global registry but leaves the class's own `cls._schema` unchanged, producing a permanent silent
divergence between what `to_arrow` uses and what the catalog writes.

### ParquetDataCatalog

```python
catalog = ParquetDataCatalog("./data")
catalog.write_data([obs1, obs2])                                  # a LIST of Data objects
results = catalog.query(data_cls=WeatherObs, start=..., end=...)  # returns CustomData wrappers
obs = [r.data for r in results]                                   # unwrap
```

There is no `catalog.write(...)` and no `catalog.read(...)`. `write_data` is `parquet.py:255`,
`query` is `:1648`. `query` returns `CustomData` wrappers for custom classes (`:1732-1744`) while
`on_data()` delivers unwrapped objects — two different shapes from the same class.

**Partitioning is attribute-driven, not automatic** (`parquet.py:320-336`): `Instrument` → `bar_type`
→ `instrument_id` → else flat. A custom type with no `instrument_id` writes flat to
`data/custom_<snake_name>/`.

### BacktestDataConfig with custom data

```python
BacktestDataConfig(
    catalog_path="./data",
    data_cls=WeatherObs,              # class object, or "pkg.mod:WeatherObs" — NEVER dotted
    client_id="WEATHER",              # plain str, required when instrument_id is None
    start_time=...,                   # NOT `start`
    end_time=...,                     # NOT `end`
)
```

Custom data interleaves with market data automatically **on this path**.

---

## What you MUST build

### Re-subscription (not reconnection)

The **engine** does nothing: `LiveDataEngine.connect()` calls `client.connect()` once, with no
reconnect loop and no resubscribe orchestration (grep for `reconnect|resubscribe` in `live/*.py`
and `data/engine.pyx` → zero hits).

But the **transport** reconnects natively. `nautilus_pyo3.WebSocketConfig`
(`core/nautilus_pyo3.pyi:5530-5558`) ships `reconnect_timeout_ms`, `reconnect_delay_initial_ms`,
`reconnect_delay_max_ms`, `reconnect_backoff_factor`, `reconnect_jitter_ms`,
`reconnect_max_attempts`, `idle_timeout_ms`, `heartbeat`, plus
`WebSocketClient.connect(post_reconnection=...)` and `is_reconnecting()`.

So: **only re-subscription replay is yours**, wired through `post_reconnection`. Do not hand-roll an
idle watchdog — that is `idle_timeout_ms`. For a **polling HTTP** client none of this applies: there
is no socket. Use a self-rescheduling `create_task` loop plus `RetryManager`.

`RetryManager` (`live/retry.py`) is public-shaped but absent from the API reference. It returns
`None` on failure rather than raising, retries only the `exc_types` you name, has jitter hardcoded
on with a **floor** (`randint(delay_initial_ms, delay)`), and `max_retries=0` disables it entirely.

### Reconciliation report methods (execution clients)

All four are **`async`** and take a single command object (`live/execution_client.py:343,371,394,417`):

```python
async def generate_order_status_report(self, command: GenerateOrderStatusReport) -> OrderStatusReport | None
async def generate_order_status_reports(self, command: GenerateOrderStatusReports) -> list[OrderStatusReport]
async def generate_fill_reports(self, command: GenerateFillReports) -> list[FillReport]
async def generate_position_status_reports(self, command: GeneratePositionStatusReports) -> list[PositionStatusReport]
```

A fifth exists: `async def generate_mass_status(self, lookback_mins: int | None = None)` (`:440`).
There is no `OrderId` type in Nautilus.

---

## VERIFIED TRAPS — each silently produces a wrong result

### 1. The catalog silently discards a same-range rewrite

`parquet.py:378-380`. If the computed filename already exists, the write is skipped with a bare
`print` to stdout — no exception, no logger. Executed:

```
write#1        : [70.0, 71.0]
File .../..._000001000Z_..._000002000Z.parquet already exists, skipping write
after rewrite  : [70.0, 71.0]        # the corrected 99.0/98.0 were discarded
```

A **partially overlapping** range instead raises `ValueError` (non-disjoint intervals), and a
disjoint range writes normally. The asymmetry is the hazard: loud on overlap, silent on exact
re-write. **Never express a correction as a rewrite of the same `ts_init` range.** Model corrections
as new records with a later `ts_init` — the documented rule for bars (`bar-execution.md:12-27`),
which is the only revision guidance the docs give.

### 2. `delete_data_range` silently no-ops for identifier-less custom types

`parquet.py:1386-1406` — the `identifier=None` branch matches on the substring `"/data/<name>/"`
with a trailing slash, which a flat custom-data directory never contains. Executed: returned
normally, deleted nothing, rows still queryable. So "delete then re-write" is not an escape hatch
from trap 1.

### 3. Raw `Data` passed to `add_data` is replayed and never delivered

`DataEngine._handle_data` dispatches only on `isinstance(data, CustomData)` (`data/engine.pyx:2570`);
a bare payload falls through to the error branch. Wrap it: `CustomData(DataType(Cls, metadata), obj)`.
`BacktestNode` wraps for you (`parquet.py:1732-1744`); `BacktestEngine.add_data` does not.

### 4. Metadata mismatch silently delivers zero messages

`DataType.topic` (`model/data.pyx:2102-2104`) builds the routing topic from metadata. A
metadata-bearing subscriber never receives a metadata-less publication. Worse: metadata **key order**
changes the topic (insertion-order iteration) while `DataType.__eq__`/`__hash__` use a `frozenset`
and compare **equal** — so equality-based unit tests pass while production delivers nothing.
**Use one shared `DataType` factory per type.** The same metadata must also go into
`BacktestDataConfig(metadata=...)` or backtest topics won't match live ones.

### 5. Prefix collision in topic matching

A `DataType(WeatherObs)` subscriber uses pattern `data.WeatherObs*` and **will receive
`WeatherObsHourly` objects**. Never name a custom class as a prefix of another, and always
`isinstance`-check in `on_data`.

### 6. `metadata` does not filter the catalog

It only tags the returned `DataType`. Two `BacktestDataConfig`s differing only by metadata replay
**every row twice**. The real partition key is the catalog directory.

### 7. `instrument_id` on a custom-data config silently yields zero rows

Unless a matching `Instrument` is in the catalog (`node.py:685-686` short-circuits; the caller only
logs a `warning`). Verified: 6 rows on disk → 0 loaded.

### 8. Data published before `RUNNING` is dropped

`handle_data`/`handle_signal` invoke `on_data`/`on_signal` only when state is `RUNNING`
(`actor.pyx:4716,4741`) — otherwise silently discarded while the bus subscription stays live.

### 9. `on_save`/`on_load` never fire without a cache database

They require **all three** of `save_state=True`, `load_state=True`, and `CacheConfig.database` set.
With the default `database=None`, `Cache.update_actor` skips the DB branch and `on_save` is never
called (`cache.pyx:2755-2757`, `:1543-1544`). Nothing else survives a restart: attributes, timers,
subscriptions, and in-flight tasks are all lost. `on_load` runs during `NautilusKernel.__init__`
(`kernel.py:538-539`), *before* `on_start`.

### 10. `chunk_size` streaming is incompatible with Cython custom data

`RuntimeError: custom data type 'X' is not registered with an Arrow schema containing ts_init`
(`parquet.py:1978`). Run one-shot (`chunk_size=None`) or move to `@customdataclass_pyo3`.

### 11. `HttpClient` hides response headers by default

`header_keys` is a *response*-header allow-list. Default → `response.headers == {}`. You cannot read
`Retry-After`, `X-RateLimit-*` or `ETag` unless named at construction. Its constructor is exactly
`(default_headers, header_keys, keyed_quotas, default_quota, timeout_secs, proxy_url)`
(`core/nautilus_pyo3.pyi:5417-5425`) — **no** redirect control, **no** TLS/CA pinning, **no** response
size cap, timeouts in whole seconds only, and quotas keyed per caller-supplied key rather than per host.

### 12. `.pyi` stubs are incomplete

`OrderFillVoided` and `ProbabilityPriceFeeModel` are absent from `core/nautilus_pyo3.pyi` but present
at runtime. Grepping the stub to prove a symbol doesn't exist yields false negatives — use
`dir(nautilus_pyo3)`.

### 13. `BacktestNode` swallows failures

`raise_exception` defaults to `False`, so a failed run becomes a log line. Also `sort=False` without
a later `sort_data()` → `RuntimeError` at `run()`.

### 14. `AccountType.BETTING` uses decimal-odds math

`accounting/accounts/betting.pyx:91` — `stake = quantity * (price - 1)`, which goes negative below
p=1. For 0–1 prediction-market prices use `AccountType.CASH` + `OmsType.NETTING`, as the bundled
Polymarket adapter does (`adapters/polymarket/execution.py:173-175`).

### 15. `from __future__ import annotations` breaks `@customdataclass`

PEP 563 stringifies all annotations at parse time. The decorator's injected `__init__` reads `cls.__annotations__`
and calls `getattr(self, ...)` on the string values — `AttributeError`. Never add `from __future__ import annotations`
to a module defining a `@customdataclass` type. Hand-written subclasses are safe.

### 16. No inheritance between custom record classes

A subclass receives the parent's injected `__init__` via `type.__new__`, which assigns `self._ts_event` but
omits parent fields (`AttributeError: no attribute '_ts_init'` on construction). The generated Arrow schema
also skips parent fields. Shared provenance must be a mixin interface (`Protocol`) or a separate data holder,
not a base class.

### 17. `NewType` and PEP-695 type aliases do not work on decorated classes

```python
DegreesFahrenheit = NewType('DegreesFahrenheit', float)
@customdataclass
class WeatherObs(Data):
    temp: DegreesFahrenheit  # TypeError at class-definition time
```
The decorator's type inspection fails. Use bare `float` and document the semantics in the `to_dict`/`from_dict` methods
of a hand-written subclass instead.

### 18. Schema drift is silent and non-deterministic

`ParquetDataCatalog` uses pyarrow's auto-schema-inference: it reads the first fragment, infers the schema,
and reuses it for all subsequent fragments in that partition. Whichever fragment sorts first in the directory
wins permanently. If a later file has different types or nullability, it is coerced silently: **new-schema-last**
overwrites new data with default values; **new-schema-first** injects `None` into fields with dataclass defaults.
Schema divergence is permanent and non-deterministic.

**Mitigation**: hand-written `Data` with an explicit decoder that **raises on missing columns**. The decoder is
invoked on read (`from_arrow`), providing the only reliable detection point. The `@customdataclass` injected
decoder calls `from_dict(...)` and passes missing keys through as defaults — no detection.

### 19. `catalog.custom_data(...)` returns `CustomData` wrapper objects, not raw instances

```python
results = catalog.custom_data(data_cls=WeatherObs, start=..., end=...)
# returns: [CustomData(DataType(...), raw_obj1), CustomData(DataType(...), raw_obj2), ...]
obs = [r.data for r in results]  # unwrap to get raw objects
```
Direct catalog reads return wrapped objects. `BacktestNode` unwraps automatically when delivering to `on_data`.

### 20. Metadata key order changes the topic string, but `DataType.__eq__` and `__hash__` ignore order

```python
DataType(Foo, {"a": 1, "b": 2}) == DataType(Foo, {"b": 2, "a": 1})  # True (frozenset)
DataType(Foo, {"a": 1, "b": 2}).topic()  # "data.Foo?a=1&b=2"
DataType(Foo, {"b": 2, "a": 1}).topic()  # "data.Foo?b=2&a=1"
```
Equality-based tests pass; production delivery fails silently because topic strings don't match.
**Use one shared `DataType` factory per type**, inserting it into both live subscribers and `BacktestDataConfig.metadata=...`.

### 21. Custom data without `instrument_id` requires one catalog root per station

`parquet.py:320-336` partitions by `bar_type` → `instrument_id` → flat. A custom type with no `instrument_id`
writes flat to `data/custom_<snake_name>/`, with no per-instrument subdirectories. A single catalog cannot separate
data for two stations into the same custom-type partition — they merge into one flat directory and become
indistinguishable on read. **Create one `ParquetDataCatalog(station_A_path)` per station**, or add an
`instrument_id` field to the custom type and populate it per-station (less flexible but workable).

---

## What Actually Works in 1.231.0 (the 2.x docs deny some of this)

- **Custom `Data` round-trips through `ParquetDataCatalog`** — verified with `date32` and nullable `int64` fields intact.
- **`BacktestNode` streams registered custom data end-to-end** — the online 2.x documentation claims custom data ingestion is unavailable in backtest; that applies to 2.x, not 1.231.0. Tested.
- **`Clock.set_timer` and `Clock.set_time_alert` are identical on `TestClock` and `LiveClock`** — both subclass the base clock where the methods are defined once. Polling cadence is replayable, making them safe for backtests.
- **`Actor.run_in_executor` stays deterministic when no `ActorExecutor` is registered** — `run_in_executor` executes **inline** and returns a fresh `TaskId`. `_register_executor()` is called only in `kernel.start_async()`, so backtests remain deterministic even if you call `run_in_executor` unconditionally. Tested.
- **`BacktestEngine.add_data` interleaves custom data with market data automatically** — no separate handling needed for mixed types.

---

## Replay ordering and determinism

**`ts_init` is the sort key, everywhere.** `backtest/engine.pyx:903` (`sorted(..., key=lambda x: x.ts_init)`),
`:1258`, `:2461`, and the k-way merge heap key `(ts_init, data_priority, data_index)` at `:2610`. The
replay clock advances off `ts_init` too (`:1663`, `:1685-1692`). **`ts_event` is never read in the
replay path.** This is documented, not a contradiction — `engine.pyx:803`,
`concepts/data/index.md:485` and `:1470` all say `ts_init`.

`ts_init` must represent **availability**. `ts_init >= ts_event` is not enforced
(`concepts/data/index.md:498`). Ordering across data types is guaranteed via the single merged
stream with the deterministic tie-break above.

Determinism levers that actually exist for a Python backtest: `ts_init` order, deterministic
`TradeId`, `FillModel(random_seed=)`, `use_random_ids=False`, and **registering no `ActorExecutor`**.
With no executor, `run_in_executor` executes **inline** and returns a fresh `TaskId`
(`actor.pyx:1091-1096`); `_register_executor()` is called only in `kernel.start_async()`
(`kernel.py:1020`). So backtests stay deterministic even if you call `run_in_executor`
unconditionally. Note `dst.md:361-379` explicitly excludes Python: *"end-to-end replay from a Python
entry point is not guaranteed."*

`add_data(data, client_id=None, validate=True, sort=True)` — **there is no `venue` parameter.**
Omitting `client_id` for instrument-less data raises **`TypeError`** (`engine.pyx:889` →
`correctness.pyx:145`), not `ValueError`; the docstring at `:814-815` says `ValueError` and is wrong.
The `BacktestNode` path does raise `ValueError` (`node.py:729`).

---

## Actor vs LiveDataClient for external ingestion

Both are sanctioned and the docs give **no criterion** — `concepts/data/index.md:1470-1478` blesses
both in one sentence. Decide on these facts:

- **In-tree precedent for Actor-as-ingest exists**: `InterestRateProvider(Actor)`
  (`persistence/loaders.py:190-259`) polls an external source, publishes
  `DataType(YieldCurveData, metadata={...})`, and self-reschedules with `set_time_alert(override=True)`.
- **Only a registered `DataClient` can serve a data request.** With a catalog registered and
  `update_catalog=False`, the engine answers `request_data` **from the catalog with no client at all**
  (`data/engine.pyx:2005-2009`); `update_catalog=True` routes to the client and therefore *requires* one.
- `LiveDataClient` brings connection lifecycle, `is_connected`, and the config/factory/secrets wiring.
- An `Actor` has no connection lifecycle and its handlers must not block.

Rule of thumb: **fetching → `LiveDataClient`; deriving and deciding → `Actor`.**

`Actor.publish_data(DataType, Data)` (`actor.pyx:2813`);
`subscribe_data(DataType, client_id=None, instrument_id=None, update_catalog=False, params=None)`
(`actor.pyx:1258`) — `data_type` must be a `DataType` **instance**; a bare class raises `TypeError`.
Calling `subscribe_data` with neither `client_id` nor `instrument_id` subscribes on the bus first,
then logs a red `[ERROR]` and returns (`actor.pyx:1289-1297`).

---

## Config & secrets convention

```python
class WeatherDataClientConfig(LiveDataClientConfig, frozen=True):   # class keyword, not @msgspec.frozen
    api_token: str | None = None
```

Base is `msgspec.Struct, kw_only=True, frozen=True, forbid_unknown_fields=True` (`live/config.py:222`).

**Resolve secrets in the factory or a credentials module, never in the config.** Mandated at
`developer_guide/adapters.md:263-266` (*"Do not spread environment lookup through request methods or
Python wrappers"*), and every in-tree call site obeys it (`databento/factories.py:59`,
`polymarket/common/credentials.py:22-38`). No in-tree config uses `__post_init__` for this.
`get_env_key` raises **`RuntimeError`**, not `KeyError` (`adapters/env.py:20-21`).

---

## Reference adapters

**1.231.0 ships TWO Polymarket adapters.** The legacy Cython one at
`nautilus_trader.adapters.polymarket` **does not import** — `providers.py:21` needs
`py_clob_client_v2`, which is not installed. A complete Rust/PyO3 V2 adapter ships at
`nautilus_trader.core.nautilus_pyo3.polymarket` (12 exported symbols including
`PolymarketUpDownEventSlugConfig`), and that is what `integrations/polymarket.md` documents. Use the
legacy one for *shape* only, and know that field names quoted from the docs describe the other adapter.

**Both target Polymarket.COM (crypto CLOB), not Polymarket.us (fiat DCM).** Auth, custody and
instrument-id schemes are load-bearing and incompatible: `.COM` uses a Polygon wallet key, ERC-1155
token ids, EIP-712 signing (delegated to the external `py_clob_client_v2` — the signing layer is not
in the tree to copy); `.us` uses Ed25519 request signing, an off-chain account, and slug-based
markets. The bundled `common/symbol.py:20-41` splits on `-` and indexes `[0]`/`[1]`, which a slug
scheme breaks outright.

**Kalshi: not present in any form.** Zero symbols in `nautilus_pyo3`, zero mentions across all 206
vendored doc pages.

**Betfair is the in-tree exemplar for hand-written custom `Data`** — seven types, six with explicit
`register_serializable_type` + `register_arrow` (`adapters/betfair/data_types.py`).

**Natively provided for prediction markets:** `BinaryOption` (correct for 0–1 prices — notional is
`qty × p`, multiplier 1, never inverse), `pUSD` as a first-class currency,
`nautilus_pyo3.ProbabilityPriceFeeModel` (`fee = qty·rate·p·(1−p)`, taker-only), the
probability↔odds bridge (`probability_to_bet`, `Bet`, `BetPosition`, `calc_bets_pnl`), and
`InstrumentClose(CONTRACT_EXPIRED)` which **backtest** settles (`backtest/engine.pyx:5939`) but
**live does not** — nothing in `execution/engine.pyx` or `portfolio/portfolio.pyx` consumes it.
Caution: `probability_to_bet` maps BUY→BACK while `betting.pyx:318` maps BUY→LAY — opposite conventions.

---

## Searching the installed source

Bash `grep -rn` against `.venv/lib/python3.13/site-packages/nautilus_trader/` **works**. The
gitignore-skipping behavior belongs to ripgrep and the harness `Grep` tool, not to GNU `grep`. Note
the codegraph symbol-search hook also routes symbol-shaped patterns — that is the real constraint,
not gitignore. `.pyx` files are not indexed by codegraph; read them directly.

---

## Version discipline

Pin `nautilus-trader~=1.231`. Every trap above is version-sensitive and should be guarded by a
contract test so a version bump fails RED rather than silently. On a bump: run contract tests first,
expect RED, re-verify against the new tag's docs — do not carry these claims forward unchecked.

---

## Corrected claims (do not reintroduce)

Twenty-three claims in previous revisions were verified wrong:

| Was | Actually |
|---|---|
| `@customdataclass(frozen=True)` | `FrozenInstanceError` on first construction |
| `catalog.write(data_type=, df=)` / `catalog.read(...)` | `write_data([...])` / `query(data_cls=...)`; never a DataFrame |
| "Any `@customdataclass` type is a first-class citizen" / "No catalog-side special-casing" | Custom types are second-class on read/delete — see traps 1, 2, 6 |
| "Partitions per-identifier automatically" | Only with `instrument_id`/`bar_type`; else flat |
| `data_cls="pkg.mod.Class"` dotted | Class object or `"pkg.mod:Class"`; dotted raises mid-run |
| `start=` / `end=` on `BacktestDataConfig` | `start_time=` / `end_time=` |
| `client_id=ClientId("WEATHER")` in the config | plain `str` |
| `add_data(data, venue=Venue(...))` | no `venue` parameter exists |
| `add_data` without client_id raises `ValueError` | raises `TypeError` (low-level path) |
| "Sorted by ts_init — contradicts base-class docstring" | Sort key right; no contradiction, it is documented |
| `add_data_client_factory(Factory.create)` | `(name: str, factory: type[...])` |
| Four sync reconciliation methods taking `OrderId`/`Venue` | Four `async` methods taking command objects, plus a fifth |
| `_subscribe_bars(self, bar_type)` with an `assert` | `_subscribe_bars(self, command: SubscribeBars)`; check is `PyCondition` in the sync `subscribe_bars` |
| "Raise `NotImplementedError` for unimplemented optional methods" | Don't override them at all |
| "Reconnection: Nautilus provides nothing" | Transport reconnect is native; only re-subscription is yours |
| "`grep` silently skips `.venv`" | Bash `grep` works; ripgrep/`Grep` tool respect gitignore |
| `@customdataclass` is the primary recommended pattern | Hand-written `Data` subclass + one `register_arrow` is primary; use decorator only for simple types |
| "It's safe to call `register_arrow` twice" | Second call silently diverges `_SCHEMAS` from `cls._schema`; never call twice |
| `from __future__ import annotations` is safe | Breaks `@customdataclass` outright; use on hand-written subclasses only |
| "You can inherit from a custom record class" | Subclass gets parent's injected `__init__` but loses parent fields; no inheritance |
| `NewType` / PEP-695 aliases work on decorated fields | `TypeError` at class-definition time; use bare types with semantic documentation |
| "Schema drift is obvious or prevented" | Silent and non-deterministic (first fragment wins); only hand-written decoders raise on missing columns |
| "`catalog.custom_data()` returns raw instances" | Returns `CustomData` wrappers; unwrap with `.data` |
| "Create one catalog for all stations" | Custom types without `instrument_id` write flat; need one catalog root per station |

## Quick checklist

**Before writing a custom type:**
- [ ] Use hand-written `Data` subclass + one `register_arrow` (primary pattern) if any field is nullable, `date`, `Enum`, or needs drift detection
- [ ] Use `@customdataclass` only if all 8 supported types and no nullable fields — never add `frozen=True`
- [ ] No `from __future__ import annotations` in the module
- [ ] No inheritance from other custom record classes
- [ ] No `NewType` or PEP-695 type aliases on decorated fields

**For catalog operations:**
- [ ] Custom type without `instrument_id` → one catalog root per station (trap 21)
- [ ] Corrections are new records with a later `ts_init` — never same-range rewrites (trap 1)
- [ ] Wrap raw data: `CustomData(DataType(Cls, meta), obj)` before `add_data` (trap 3)
- [ ] Unwrap catalog reads: `results = catalog.custom_data(...); obs = [r.data for r in results]` (trap 19)
- [ ] Never call `register_arrow` twice for the same class (trap 18)

**For topic routing:**
- [ ] One shared `DataType` factory per type; same metadata in live and `BacktestDataConfig` (traps 4, 20)
- [ ] Custom class name is not a prefix of another; `isinstance`-check in `on_data` (trap 5)
- [ ] Metadata key order matters for topic strings even though equality ignores it

**For configuration:**
- [ ] Confirmed which API surface (Cython / PyO3 / Rust) the doc describes — 1.231.0 ships three parallel surfaces
- [ ] `data_cls` is a class object or `"pkg.mod:Class"` colon path; never dotted (trap in Corrected Claims)
- [ ] `BacktestDataConfig`: `start_time` / `end_time`, `client_id` is a plain `str` and required for custom data
- [ ] `add_data(data, client_id=...)` — no `venue` parameter exists
- [ ] Secrets via `get_env_key` in the factory, never in the config

**For backtests:**
- [ ] `on_save`/`on_load` require **all three**: `save_state=True`, `load_state=True`, and `CacheConfig.database` set (trap 9)
- [ ] Data published before `RUNNING` is silently dropped (trap 8)
- [ ] `chunk_size` streaming raises `RuntimeError` for Cython custom data (trap 10)
- [ ] `run_in_executor` is deterministic in backtests (no executor registered) — safe to use unconditionally

**Contract tests guard:**
- [ ] Every trap above, especially version-sensitive ones (pin `nautilus-trader~=1.231`)
- [ ] Round-trip: custom data → parquet → catalog → backtest → on_data
- [ ] Schema drift: inject wrong type on second write, verify decoder raises on read
