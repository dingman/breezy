# Nautilus 1.231.0 — Backtesting, Data Replay, Determinism & Parity

<!-- Generated: 2026-08-22 | Repo HEAD: (no commits on master yet) | nautilus-trader 1.231.0 -->

- **Sources (authoritative, in this order):**
  1. Installed source — `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/` (v1.231.0, verified via `nautilus_trader.__version__`). **Ground truth.**
  2. Vendored docs — `/home/jon/breezy/docs/reference/nautilus/v1.231.0/` (git tag v1.231.0).
  3. `docs/reference/nautilus/upstream-latest/` — **2.x/develop. NOT truth for 1.231.0. Not cited here.**
- **Scope:** How historical data (built-in and custom) is loaded, ordered, and replayed by `BacktestEngine` / `BacktestNode`; what determinism is guaranteed; what backtest/live parity actually covers.
- **Empirical verification:** every "VERIFIED (run)" claim below was executed against the installed 1.231.0 package in this session.

> ⚠️ The vendored v1.231.0 docs **already contain 2.x-flavoured prose** in `concepts/backtesting/apis-and-runs.md`. Several of its code snippets do not run on 1.231.0. See [Docs vs code drift](#docs-vs-code-drift). Trust the installed source.

---

## Verified facts

### A. API levels

**1. Two API levels, and the documented purpose of each.**
`concepts/backtesting/index.md` and `getting_started/index.md:38-46`:

| API level | Entry point | Docs say it is FOR |
| --- | --- | --- |
| Low-level | `BacktestEngine` | Direct component access, library development; data already in memory or manually batched; loading from non-Parquet formats; rerunning the same loaded data with swapped components. |
| High-level | `BacktestNode` | Data in a `ParquetDataCatalog`; automatic chunked loading; one config object that describes AND identifies a run; a fresh engine per independent run. |

**Recommendation for reproducible production workflows: the high-level `BacktestNode` API.** `getting_started/index.md:43` labels it *"Production workflows, easier transition to live trading (recommended)"*, and adds *"The low-level API works with in-memory data but **has no live-trading path**"* (`getting_started/index.md:45-46`). `BacktestRunConfig` is content-hashed into a stable run identity — `config.id` is a SHA-256 over the serialized config (VERIFIED (run): `id = 48cdaf44…`), which is the reproducibility anchor.

**2. One node per process.** `getting_started/index.md:48-52`: running multiple `BacktestNode` or `TradingNode` instances *concurrently in the same process is not supported* (global singleton state). Sequential execution with disposal between runs is supported. `concepts/backtesting/apis-and-runs.md` shows the `for config in configs: node = BacktestNode([config]); …; node.dispose()` loop.

---

### B. `BacktestDataConfig` and custom data classes — Q2

**3. YES — `BacktestDataConfig` in 1.231.0 accepts a custom data class.** The field is **`data_cls`** (`backtest/config.py:241`), annotated `str` but accepting either form:

| Form | Accepted? | Evidence |
| --- | --- | --- |
| **Class object** (`data_cls=WeatherData`) | ✅ **YES — preferred** | `backtest/config.py:266-269` (`if isinstance(self.data_cls, str): return resolve_path(...) else: return self.data_cls`). VERIFIED (run). Also the documented shape: `concepts/data/index.md:1487-1494` and `getting_started/backtest_high_level.py:190` both pass the class object. |
| **Colon-separated path** (`"pkg.mod:ClassName"`) | ✅ YES | `common/config.py:78-82`: `resolve_path` does `path.rsplit(":", maxsplit=1)`. VERIFIED (run). |
| **Dotted path** (`"pkg.mod.ClassName"`) | ❌ **NO — BROKEN** | VERIFIED (run): `ValueError('not enough values to unpack (expected 2, got 1)')`. |

**4. `Data.fully_qualified_name()` returns a colon path and IS directly usable as `data_cls`.**
`core/data.pyx:54-66` → `return cls.__module__ + ':' + cls.__qualname__`.
VERIFIED (run): `QuoteTick.fully_qualified_name() == "nautilus_trader.model.data:QuoteTick"`.
Passing a **class object** also serializes to that exact colon string: VERIFIED (run) — `BacktestDataConfig(data_cls=WeatherData).json()` emits `"data_cls":"bzprobe:WeatherData"`. So class object and FQN string are round-trip equivalent; the class object is safer because it fails at import time rather than at query time.

**5. Failure mode of a dotted path is LATE, not at construction.** `data_cls` is a plain `str`-annotated msgspec field; msgspec Structs do not validate on `__init__`. The dotted string is accepted by the constructor and only explodes when `.data_type` is first read — inside `BacktestNode._run_oneshot` / `_run_streaming`, i.e. *mid-run*. VERIFIED (run).

**6. Exact field names (msgspec `frozen=True` — unknown kwargs are a hard `TypeError`).** `backtest/config.py:240-254`:

```
catalog_path: str                       # required
data_cls: str                           # required  (class object also accepted)
catalog_fs_protocol / _fs_storage_options / _fs_rust_storage_options
instrument_id: InstrumentId | None
start_time: str | int | None            # NOT "start"
end_time:   str | int | None            # NOT "end"
filter_expr: str | None
client_id: str | None                   # plain str, not ClientId
metadata: dict | Callable | None
bar_spec / instrument_ids / bar_types
optimize_file_loading: bool = False
```

VERIFIED (run): `BacktestDataConfig(..., data_type="QuoteTick")` → `TypeError: Unexpected keyword argument 'data_type'`; `start=`/`end=` → `TypeError: Unexpected keyword argument 'start'`.
`start` / `end` DO exist — on **`BacktestRunConfig`** (`backtest/config.py:446-447`), not on the data config.

---

### C. `client_id` for instrument-less custom data — Q3

**7. `client_id` is MANDATORY for any data class that is not a built-in Nautilus type.** Two distinct enforcement points with two DIFFERENT exception types:

| Path | Site | Raises |
| --- | --- | --- |
| High-level (`BacktestNode`) | `backtest/node.py:727-731` | `ValueError: Data type <class '…'> not setup for loading into 'BacktestEngine'` |
| Low-level (`BacktestEngine.add_data`) | `backtest/engine.pyx:889` → `core/correctness.pyx:141-148` | **`TypeError: 'client_id' argument was 'None'`** |

VERIFIED (run), both. `Condition.not_none` defaults to `ex_default=TypeError` (`core/correctness.pyx:145`), **not** `ValueError`.

**8. The gate is `is_nautilus_class`, not "has no instrument_id".** `core/inspect.py:21-33`: anything whose `__module__` is outside `nautilus_trader.model` / `nautilus_trader.common` (and `Signal*` types) is "custom" and therefore requires `client_id`. A user class that *does* carry an `instrument_id` field still requires `client_id`, because the `CustomData` wrapper (not the payload) is what `add_data` inspects (`backtest/engine.pyx:862-895`).

---

### D. Sort key — Q4

**9. `BacktestEngine.add_data` sorts by `ts_init`. Definitively.**

```
backtest/engine.pyx:903      self._data = sorted(self._data, key=lambda x: x.ts_init)
backtest/engine.pyx:1258     # sort_data() — identical key
backtest/engine.pyx:2461     # BacktestDataIterator._add_data — sorted(..., key=lambda data: data.ts_init)
backtest/engine.pyx:2610     heapq.heappush(self._heap, (ts_init, data_priority, data_index))   # k-way merge key
```

The replay clock is advanced from `ts_init` too (`backtest/engine.pyx:1663, 1685-1692, 1727`). `ts_event` is **never** consulted for ordering anywhere in the replay path.

VERIFIED (run): four `CustomData` items with `ts_event` strictly DESCENDING (900, 899, 898, 897) and `ts_init` ascending (100, 101, 102, 103), fed to `add_data` in reverse order, were delivered in `ts_init`-ascending order — i.e. `ts_event` descending.

**Docs agreement:** `concepts/data/index.md:485` (*"Data is ordered by `ts_init` using a stable sort"*), `:1470` (*"Backtests order the data stream by `ts_init`"*), and the `add_data` docstring itself (`backtest/engine.pyx:803`) all say `ts_init`. **No contradiction on the sort key in 1.231.0.** (The skill file's claim that this "contradicts the base-class docstring" is stale — see Corrections.)

**Consequence when `ts_event != ts_init`:** the strategy sees events in *observation* order, not in *occurrence* order. A weather observation with `ts_event = 12:00` but `ts_init = 14:30` (a late-arriving or corrected reading) replays at 14:30 and can legitimately arrive *after* an observation with a later `ts_event`. That is the intended anti-look-ahead behaviour, and it means **`ts_init` is the field Breezy must get right**; `ts_event` is metadata only.

---

### E. `ts_event` vs `ts_init` semantics — Q5

**10. Definitions** (`concepts/data/index.md:451-455`): `ts_event` = UNIX ns **when the event occurred**; `ts_init` = UNIX ns **when NautilusTrader initialized the object**. `:472-474`: *"`ts_init` means initialization time, not always receipt time."*

**11. Look-ahead prevention rule.** Backtest ordering is on `ts_init` (`:485`), which encodes *when the information became available to the system*. Setting `ts_init` to the true availability time is what keeps a backtest honest.

**12. Documented rule for revised/corrected data.** The docs state the general rule only for bars, and it generalizes:
`concepts/backtesting/bar-execution.md:12-27` — *"each bar's initialization timestamp (`ts_init`) must represent the **close** of the interval. This prevents the complete bar from becoming visible before it formed."* For bars stamped at the open, set `ts_init = ts_event + interval_ns`. And explicitly: *"For custom data, populate `ts_event` and `ts_init` before constructing objects, encoding Arrow record batches, writing a catalog, or calling `add_data()`."*
`:498` — *"clock skew means [`ts_init`] is not guaranteed to be ≥ `ts_event`."* Nothing enforces `ts_init >= ts_event`.
**Breezy rule:** for a revised/corrected observation, `ts_event` = the original observation time; `ts_init` = the timestamp at which the *revision* became available. Two records for the same `ts_event` with different `ts_init` are the correct representation of a correction; there is no in-place update path.

**13. `_query_pyarrow` time-filters on `ts_init`** (`persistence/catalog/parquet.py:2153, 2156`: `pds.field("ts_init") >= start`, `<= end`), and catalog filenames encode the **`ts_init`** range. VERIFIED (run): data with `ts_init` 10000–20004 produced `…/1970-01-01T00-00-00-000010000Z_1970-01-01T00-00-00-000020004Z.parquet`. So `BacktestDataConfig.start_time`/`end_time` window on `ts_init`, consistently with replay order.

---

### F. Interleaving of custom data with market data — Q6

**14. One global stream; ordering across data types IS guaranteed, keyed on `ts_init`.** `BacktestDataIterator` (`backtest/engine.pyx:2273-2300`) is a *"time-ordered multiplexer"* that yields *"in strict chronological order based on their `ts_init` timestamps"*, using a single-array fast path for one stream and a binary min-heap k-way merge for ≥2.

**15. Tie-break is fully deterministic:** the heap key is the 3-tuple `(ts_init, data_priority, data_index)` (`backtest/engine.pyx:2610`). `data_priority` is `±(counter)` — `append_data=True` → positive (lower priority, later); `append_data=False` → negative (higher priority, earlier); never zero (`:2445-2452`). Within a stream, `data_index` preserves insertion order, and `sorted()` is stable.

**16. All of `BacktestEngine.add_data` lands in ONE stream** named `"backtest_data"` (`backtest/engine.pyx:904, 1259`). Distinct streams only arise from `add_data_iterator()` and from live `SubscribeData` requests inside the run.

**17. Custom data bypasses the exchange and goes straight to the data engine.** The run loop's `isinstance` dispatch chain (`backtest/engine.pyx:1695-1722`) has no branch for `CustomData`, so it falls through to `self._data_engine.process(data)` (`:1724`). `concepts/custom_data.md:353-354` states the same for the Rust engine: *"treats `Data::Custom` as data-engine-delivered input rather than exchange-routed data."* The engine clock still advances to the custom datum's `ts_init` (`:1689-1692`), and venues are settled at that timestamp (`:1727`) — so **custom data does move the simulated clock and can trigger fills of resting orders via the settle phase**.

**18. Routing topic.** `data/engine.pyx:2845-2848` publishes the **inner payload** (`data.data`), not the `CustomData` wrapper, on a topic from `common/data_topics.pyx:189-211`:
- payload has `instrument_id` **and** the `DataType` has no metadata → `data.<TypeName>.<venue>.<symbol>`
- otherwise → `data.<DataType.topic>` where `DataType.topic` = `<TypeName>.k=v.k=v` (`model/data.pyx:2102-2104`).
Equality/hash of `DataType` use `(type, metadata)` only; `identifier` is excluded (`model/data.pyx:2106-2112`, `concepts/custom_data.md:132-141`). **Metadata is part of the routing key; identifier is not.**

---

### G. Backtest / live parity — Q7

**19. Explicitly SHARED** (`concepts/backtesting/index.md:3-6`): *"the same core system components used in live trading: built-in engines, the `Cache`, the MessageBus, `Portfolio`, Actors, Strategies, Execution Algorithms, and user-defined modules."* `concepts/architecture.md:240-244`: the `system` subpackage's `NautilusKernel` is the common core across Backtest / Sandbox / Live. `concepts/live.md:3-5`: *"deploys backtested strategies to live markets with no code changes."*

**20. Explicitly NOT shared / not guaranteed:**
- **Data source & clock.** `concepts/architecture.md:284-286`: in live mode the adapter pushes through an async unbounded MPSC channel; *"in backtests the engine feeds data directly."* Backtest uses a `TestClock` driven by `ts_init`; live uses a `LiveClock`.
- **Determinism.** `concepts/architecture.md:502-504`: the single-threaded kernel *"helps maintain backtest-live parity, **though live inputs and latency can still cause behavioral differences**."*
- **Reconciliation.** `concepts/reconciliation.md:17`: *"Only the `LiveExecutionEngine` performs reconciliation, since backtesting controls both sides."* Backtests never exercise `generate_*_report` paths.
- **The low-level API has no live path at all** (`getting_started/index.md:45-46`).
- **Venue microstructure.** `concepts/backtesting/data-and-venues.md`: fills come from a simulated matching engine over a book reconstructed from whatever granularity you supplied; *"even a recorded book cannot show how a simulated order would have changed the market."*
- **Background services are threaded in live** (`concepts/architecture.md:513-521`): network I/O, DataFusion/persistence, and adapter thread-pool executors run off-kernel and re-enter through the bus.

---

### H. Determinism — Q8

**21. What `concepts/dst.md` guarantees.** Under `(seed, binary hash, configuration hash)` on the same platform, bitwise-identical: async task scheduling order; timer firings (virtual monotonic + virtual wall-clock); `madsim::rand` output; `tokio::sync` channel delivery order (`dst.md:99-104`).

**22. Required conditions (all must hold, `dst.md:106-131`):** `simulation` Cargo feature **and** `RUSTFLAGS="--cfg madsim"` (one without the other *"silently falls back to real tokio and breaks determinism without an error"*); `biased;` on every DST-path `tokio::select!`; monotonic reads via `nautilus_common::live::dst::time` / `nautilus_network::dst::time`; wall-clock via `nautilus_core::time::duration_since_unix_epoch`; RNG via `madsim::rand`; `IndexMap`/`IndexSet` (or sort-at-use) for order-sensitive collections; no `LocalSet`; no `spawn_blocking`.

**23. What breaks determinism (`dst.md:398-446`):** unaliased dependencies reaching the OS directly (`libc`, `std::net`, `fastrand`, `OsRng`) *"escape the simulator without raising an error"*; transport I/O (`tokio-tungstenite`, `tokio-rustls`, `reqwest`, `redis`, `sqlx`) runs on real networking; logging runs on a real OS thread and is outside the contract; **adapter crates are out of scope entirely**; cross-platform reproducibility is **not** claimed.

**24. ⚠️ DST DOES NOT COVER PYTHON — this is the headline for Breezy.** `dst.md:361-379`: *"No Python interpreter starts during a DST run… the Python packages under `nautilus_trader/` are excluded from the contract as a policy."* And directly: *"A Python strategy that calls `time.time()`, issues arbitrary network requests, or relies on thread scheduling can vary its command stream between runs; the Rust core processes the varying stream deterministically, but **end-to-end replay from a Python entry point is not guaranteed**."*

**25. Async/executor usage in `dst.md`:** yes, extensively — `madsim` swaps `tokio::{time,task,runtime,signal}`; `spawn_blocking` and `LocalSet` are banned/cfg-gated because *"a blocking call escapes the deterministic scheduler"*; `select!` must be `biased;`. **None of this reaches the Python `Actor` executor.** In the installed 1.231.0, `Actor.queue_for_executor` / `run_in_executor` fall back to a *synchronous inline call* when no executor is registered (`common/actor.pyx:1030-1031`, `:1091-1092`) — which is the backtest default and preserves determinism. **Registering an `ActorExecutor` (`common/actor.pyx:734-757`) moves work off the kernel thread and forfeits deterministic replay.** Breezy should not register one in backtest.

**26. What IS deterministic in a 1.231.0 Python backtest, independent of DST:** the `ts_init` total order (fact 15); deterministic `TradeId`s — `T-{fnv1a(venue, raw_id, ts_init):016x}-{count:03d}`, *"the same replayed data produces the same `TradeId` every time"*, and *"`TradeId` is always deterministic and is not affected by the `use_random_ids` flag"* (`concepts/backtesting/execution-flow.md:107-127`); and `FillModel(random_seed=…)` (`backtest/config.py:474`). `use_random_ids` still randomizes `VenueOrderId` / `PositionId` — leave it off.

---

### I. Multiple configs of the same custom type — Q9

**27. YES, multiple `BacktestDataConfig` entries of the same custom class in one run are permitted and all load.** `BacktestNode._run_oneshot` (`backtest/node.py:640-670`) iterates `for config in data_configs:` with no de-duplication by `data_cls`. VERIFIED (run): two configs, same `data_cls=WeatherData`, distinct `client_id` and distinct `metadata`, both loaded and both replayed in one run.

**28. ⚠️ BUT metadata does NOT filter the catalog — it only TAGS the result.** `persistence/catalog/parquet.py:1732-1744`: `metadata` is read from `kwargs` *after* the query returns and used solely to build `DataType(data_cls, metadata=…)` around each row. File discovery (`get_file_list_from_data_cls` → `class_to_filename` → `<catalog>/data/custom_<snake_case>/**/*.parquet`, `parquet.py:2286-2310, 2465-2477`) is keyed on the **class name only**.
VERIFIED (run): `catalog.query(data_cls=WeatherData, metadata={"station":"KJFK"})` returned **all 10** rows including the KBOS ones, every one tagged `station=KJFK`.
VERIFIED (run, full node): two configs distinguished *only* by metadata caused **every physical row to be replayed twice** (10 rows → 20 deliveries), each on a different message-bus topic.

**29. The only real partition key is the catalog directory (`identifiers`).** `_make_path` (`parquet.py:2465-2477`) writes to `<catalog>/data/custom_<snake>/<urisafe_identifier>/…` when the payload carries an `instrument_id`. VERIFIED (run): a custom class with an `instrument_id` field produced `…/custom_weather_point/KJFK.WX/…` and `…/KBOS.WX/…`, and `query(identifiers=[jfk])` returned exactly 3 of 6 rows.

**30. ⚠️ …but setting `instrument_id` on a CUSTOM-data `BacktestDataConfig` silently yields ZERO rows unless a matching `Instrument` is also in the catalog.** `backtest/node.py:677-686`:
```python
instruments = catalog.instruments(instrument_ids=used_instrument_ids) if used_instrument_ids else None
if len(used_instrument_ids) > 0 and not instruments:
    return CatalogDataResult(data_cls=config.data_type, data=[])   # ← silent empty
```
The caller only logs a `warning` and `continue`s (`node.py:648-654`). VERIFIED (run): identical config, 6 rows on disk → `instrument_id` set, no `Instrument` written → **0 rows**; `instrument_id` unset → 6 rows.
Additionally `BacktestNode._validate_configs` (`node.py:192-197`) will raise `InvalidConfiguration` if the instrument's venue has no `BacktestVenueConfig`.

**31. Recommended partitioning for Breezy (in preference order):**
   1. **Separate catalog paths** per logical dataset (one `BacktestDataConfig` per `catalog_path`) — total isolation, no instrument plumbing.
   2. **Separate custom classes** (`WeatherObsKJFK`, `WeatherObsKBOS`) — different `class_to_filename`, different directories.
   3. `instrument_id` partitioning — works, but **requires writing a synthetic `Instrument` to the catalog and a matching `BacktestVenueConfig`** (fact 30).
   4. Metadata alone — **do not**: it duplicates, it does not filter (fact 28).
   Use `metadata` for *topic routing* (fact 18), never for *selection*.

---

## Documented patterns

### Pattern 1 — Custom data through `BacktestNode` + `ParquetDataCatalog` (high-level, recommended)

Verified end-to-end against 1.231.0 in this session.

```python
# ---- weather_data.py  (an IMPORTABLE module — data_cls resolution needs it) ----
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass

@customdataclass                      # NO arguments; see Trap T5 for frozen=True
class WeatherObs(Data):
    station: str = ""
    temp_c: float = 0.0
# @customdataclass auto-calls register_serializable_type + register_arrow
# (model/custom.py:160-161), so the type is Parquet-persistable immediately.
```

```python
# ---- write the catalog ----
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from weather_data import WeatherObs

catalog = ParquetDataCatalog("./catalog")
catalog.write_data([                      # NOT catalog.write(...) — no such method
    WeatherObs(ts_event=obs_time_ns, ts_init=available_time_ns,
               station="KJFK", temp_c=21.3),
    ...
])
# -> ./catalog/data/custom_weather_obs/<ts_init_lo>Z_<ts_init_hi>Z.parquet
```

```python
# ---- configure and run ----
from nautilus_trader.backtest.node import (
    BacktestNode, BacktestRunConfig, BacktestDataConfig,
    BacktestVenueConfig, BacktestEngineConfig,
)
from nautilus_trader.config import ImportableActorConfig
from weather_data import WeatherObs

data = BacktestDataConfig(
    catalog_path="./catalog",
    data_cls=WeatherObs,                      # class object (or "weather_data:WeatherObs")
    client_id="WEATHER",                      # MANDATORY for custom data (plain str)
    metadata={"station": "KJFK"},             # topic routing ONLY — does not filter
    start_time="2026-01-01T00:00:00Z",        # start_time / end_time — NOT start / end
    end_time="2026-02-01T00:00:00Z",
    # instrument_id=...  -> only if a matching Instrument is in the catalog (fact 30)
)

config = BacktestRunConfig(
    venues=[BacktestVenueConfig(
        name="SIM", oms_type="NETTING", account_type="CASH",
        book_type="L1_MBP", starting_balances=["1_000_000 USD"],
    )],
    data=[data],
    engine=BacktestEngineConfig(actors=[ImportableActorConfig(
        actor_path="my_pkg.actors:WeatherActor",
        config_path="my_pkg.actors:WeatherActorConfig",
        config={"component_id": "WEATHER-ACTOR"},
    )]),
    # chunk_size=...  -> DO NOT SET for Cython custom data (Trap T6)
    raise_exception=True,                     # else run failures are swallowed into a log line
)

node = BacktestNode([config])
node.build()
try:
    results = node.run()
finally:
    node.dispose()
```

```python
# ---- subscribing actor ----
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.model import DataType
from nautilus_trader.model.identifiers import ClientId
from weather_data import WeatherObs

class WeatherActorConfig(ActorConfig, frozen=True): ...

class WeatherActor(Actor):
    def on_start(self) -> None:
        # DataType metadata MUST match the BacktestDataConfig metadata exactly —
        # equality/hash and the msgbus topic derive from (type, metadata).
        self.subscribe_data(
            DataType(WeatherObs, metadata={"station": "KJFK"}),
            client_id=ClientId("WEATHER"),
        )

    def on_data(self, data) -> None:
        if isinstance(data, WeatherObs):      # on_data receives the INNER payload
            ...
```

### Pattern 2 — Low-level `BacktestEngine.add_data` equivalent

```python
from nautilus_trader.backtest.engine import BacktestEngine        # NOT nautilus_trader.backtest
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.model import DataType
from nautilus_trader.model.data import CustomData
from nautilus_trader.model.identifiers import ClientId, Venue
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money, Currency

engine = BacktestEngine(BacktestEngineConfig(trader_id="BREEZY-001"))
engine.add_venue(
    venue=Venue("SIM"), oms_type=OmsType.NETTING, account_type=AccountType.CASH,
    starting_balances=[Money(1_000_000, Currency.from_str("USD"))],
)
engine.add_actor(WeatherActor(WeatherActorConfig(component_id="WEATHER-ACTOR")))

data_type = DataType(WeatherObs, metadata={"station": "KJFK"})
wrapped = [CustomData(data_type=data_type, data=obs) for obs in observations]  # ← REQUIRED, Trap T1

engine.add_data(wrapped, client_id=ClientId("WEATHER"))   # signature: (data, client_id, validate, sort)
engine.run()
```

Bulk-load variant (avoids re-sorting the cumulative list on every call — Drift D3):

```python
engine.add_data(batch_1, client_id=ClientId("WEATHER"), sort=False)
engine.add_data(batch_2, client_id=ClientId("WEATHER"), sort=False)
engine.sort_data()          # MUST be called; sort=False leaves the engine not-ready
engine.run()
```

Manual streaming (the low-level answer to large datasets):

```python
engine.add_strategy(strategy)
for batch in batches:
    engine.add_data(batch, client_id=ClientId("WEATHER"))
    engine.run(streaming=True)
    engine.clear_data()
engine.end()                # flushes timers, fires on_stop, produces the final result
```

Parameter sweeps over the same data: `engine.reset()` retains data / instruments / venues / actors / strategies and clears orders, positions, balances, and counters (`concepts/backtesting/apis-and-runs.md`, "Repeated runs").

---

## Docs vs code drift

Ordered by blast radius. **In every case the installed source wins.**

**D1 — `concepts/backtesting/apis-and-runs.md` uses a package-root API that does not exist in 1.231.0.**
Doc: `from nautilus_trader.backtest import BacktestEngine` / `BacktestNode` / `BacktestDataConfig` / `BacktestVenueConfig` / `BacktestEngineConfig`.
Reality: `backtest/__init__.py` is a docstring only — no re-exports. VERIFIED (run): `ImportError: cannot import name 'BacktestEngine' from 'nautilus_trader.backtest'`.
Correct: `nautilus_trader.backtest.engine`, `.node`, `.config`, or `nautilus_trader.config`. Corroborated by `api_reference/backtest.md` (autodoc targets the submodules) and by both `getting_started/backtest_*.py` examples. **This page is 2.x prose that leaked into the v1.231.0 tag.**

**D2 — the same page's `BacktestDataConfig` example does not construct.**
Doc: `BacktestDataConfig(data_type="QuoteTick", catalog_path=..., instrument_id=...)`.
Reality: `data_type` is a read-only *property*; the field is `data_cls`. VERIFIED (run): `TypeError: Unexpected keyword argument 'data_type'`.

**D3 — "each `add_data()` call creates an independent stream" is FALSE.**
Doc (`apis-and-runs.md`, "Loading data"): *"Each `add_data()` call copies its input into an independent stream… Adding one batch per instrument does not repeatedly sort a cumulative list."*
Reality (`backtest/engine.pyx:900-904`): `self._data.extend(data)` then `sorted(self._data, key=…)` — a single cumulative list named `"backtest_data"`, re-sorted in full on **every** call. The engine's own `add_data` docstring (`:827-844`) contradicts the concept page and matches the code: *"For optimal performance when loading large datasets, consider using `sort=False` for all calls… then calling `sort_data()` once."* **Performance-relevant: N `add_data` calls are O(N · total · log total).**

**D4 — "The low-level API does not expose a generator-based `add_data_iterator()` method" is FALSE.**
`BacktestEngine.add_data_iterator(data_name, generator, client_id=None)` exists at `backtest/engine.pyx:922-950`.

**D5 — `add_data` docstring's exception type for missing `client_id` is wrong.**
Docstring (`backtest/engine.pyx:814-815`): *"ValueError — If `data` elements do not have an `instrument_id` and `client_id` is `None`."*
Reality: `Condition.not_none` raises **`TypeError`** (`core/correctness.pyx:141-148`, `ex_default=TypeError`). VERIFIED (run): `TypeError: 'client_id' argument was 'None'`.
(The high-level `BacktestNode` path *does* raise `ValueError`, from `node.py:729` — different site, different message.)

**D6 — `concepts/custom_data.md` catalog path layout does not match the Cython catalog.**
Doc (`:258-262`): *"`data/custom/<type_name>/<identifier...>`"*.
Reality for `nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog`: `data/custom_<snake_case_class_name>/<identifier>/…` (`persistence/funcs.py:36, 39-53` `CUSTOM_DATA_PREFIX = "custom_"`, `parquet.py:2465-2477`). VERIFIED (run): `data/custom_weather_data/…` and `data/custom_weather_point/KJFK.WX/…`.
The whole of `concepts/custom_data.md` describes the **PyO3/Rust** custom-data system (`DataRegistry`, `register_custom_data_class`, `@customdataclass_pyo3`), which it admits at `:376-384`: *"The Cython `@customdataclass` system is separate from this architecture."* **Breezy on the Cython stack must not read that page as normative.**

**D7 — DeFi `ts_init` tie-break is Rust-engine only.**
Doc (`concepts/data/index.md:486`): *"DeFi data (`DefiData`) breaks `ts_init` ties by on-chain position."* No such logic exists in `backtest/engine.pyx` (sort key is bare `x.ts_init`). Harmless for Breezy; flagged so the "stable sort" claim is read as *insertion-order-stable*, nothing more.

**D8 — `concepts/backtesting/index.md` and `apis-and-runs.md` describe "the current Rust backtest engine".**
In 1.231.0 the Python-facing `BacktestEngine` is Cython (`backtest/engine.pyx`). Behaviour statements sourced from `crates/backtest/**` are not automatically true of the Python path — D3, D4, D6, D7 are all instances of this.

---

## Traps

**T1 — Raw custom `Data` added to `BacktestEngine` is accepted, replayed, and SILENTLY NEVER DELIVERED.**
`add_data` accepts any `Data` subclass (`Condition.list_type(data, Data, …)`, `engine.pyx:853`), but `DataEngine._handle_data` (`data/engine.pyx:2540-2572`) dispatches custom payloads **only** via `isinstance(data, CustomData)`. A bare `WeatherObs` hits the `else` branch and logs `"Cannot handle data: unrecognized type"` — an INFO-level miss that is invisible under `bypass_logging`.
VERIFIED (run): `engine.add_data([WeatherObs(...)], client_id=ClientId("WX"))` → engine ran clean, actor received **zero** items.
**Always wrap: `CustomData(data_type=DataType(Cls, metadata), data=obj)`.** (`BacktestNode` does this for you — `parquet.py:1732-1744`.)

**T2 — `metadata` does not filter (fact 28). Two configs distinguished only by metadata duplicate every row.** VERIFIED (run): 10 rows → 20 deliveries.

**T3 — `instrument_id` on a custom-data config silently returns zero rows without a matching catalog `Instrument`** (fact 30). Failure is a `warning` log + `continue`, then an empty backtest that "succeeds".

**T4 — Dotted `data_cls` fails LATE, at first `.data_type` access, inside the run** (fact 5). Prefer the class object so a typo is an `ImportError` at module load.

**T5 — `@customdataclass(frozen=True)` is BROKEN.** The decorator forwards kwargs to `dataclass(cls, **kwargs)` (`model/custom.py:42`), then the injected `__init__` assigns `self._ts_event` / `self._ts_init` (`:51-52`), which a frozen dataclass forbids.
VERIFIED (run): `dataclasses.FrozenInstanceError: cannot assign to field '_ts_event'` at first instantiation. **Use bare `@customdataclass`.**

**T6 — `chunk_size` (streaming mode) is INCOMPATIBLE with Cython `@customdataclass` types.**
`BacktestNode._run_streaming` (`node.py:531-628`) routes everything through the Rust `DataBackendSession`, which requires the type in the Rust `DataRegistry`. Cython `@customdataclass` registers only the Python Arrow serializer, not the Rust one.
VERIFIED (run): `RuntimeError: custom data type 'WeatherData' is not registered with an Arrow schema containing ts_init`, raised from `parquet.py:1978` `session.add_custom_file(...)`.
**Leave `chunk_size=None` (one-shot) for Breezy weather data**, or move the type to `@customdataclass_pyo3` + `register_custom_data_class`.

**T7 — streaming mode also drops `client_id`.** Even where it works, `node.py:610-614` calls `engine.add_data(data=data, validate=False, sort=True)` with **no `client_id`**, so `_add_data_client_if_not_exists` is never invoked for that data and validation is off. Subscriptions bound to a `client_id` may go unserved.

**T8 — `sort=False` leaves the engine not-ready and `run()` hard-fails.** `engine.pyx:907` clears `self._sorted`; `engine.pyx:1540-1544` then raises `RuntimeError("Data has been added but not sorted, call 'engine.sort_data()' or use 'engine.add_data(..., sort=True)' before running")`. Note `reset()` only re-arms the iterator when `self._sorted` is already true (`engine.pyx:1243-1244`).

**T9 — look-ahead via `ts_init`.** `ts_init` is the *only* gate. A weather forecast issued at 06:00 that describes 18:00 conditions must carry `ts_init = 06:00` (issuance), never `ts_init = 18:00` (validity), or the backtest reads the future. Corollary from `bar-execution.md:12-27`: any *aggregated / interval* datum must have `ts_init` at the **close** of the interval it summarizes.

**T10 — no native next-bar-open fill** (`concepts/backtesting/bar-execution.md:113-119`): *"Using the current bar's open from its `on_bar` callback would introduce look-ahead."*

**T11 — venue `book_type` silently discards data.** `concepts/backtesting/data-and-venues.md`: at `L2_MBP`/`L3_MBO`, `QuoteTick` and `Bar` do **not** update the book (orders appear never to fill); at `L1_MBP` (default), `OrderBookDelta(s)` are ignored. The clock still advances and strategies still receive the data — so the symptom is "no fills", not "no data".

**T12 — `raise_exception` defaults to `False`** (`backtest/config.py:444`). A `BacktestNode` run that throws is caught by `log_backtest_exception` and degrades into a log line with a "successful" return. Set `raise_exception=True` in any automated/CI Breezy run.

**T13 — `Actor.subscribe_data` metadata must match the config metadata EXACTLY.** `DataType.__eq__` / `__hash__` use `(type, frozenset(metadata.items()))` (`model/data.pyx:2106-2112`); the topic string is built from the same. `{"station": "KJFK"}` and `{"station": "kjfk"}` are different topics. `identifier` is deliberately excluded from equality and routing (`concepts/custom_data.md:132-141`).

**T14 — determinism is not inherited from DST.** `dst.md:361-379` excludes Python entirely. Breezy's replay determinism rests on: (a) fixed `ts_init` ordering, (b) `FillModel(random_seed=…)`, (c) `use_random_ids=False`, (d) no `ActorExecutor` registered, (e) no wall-clock / `random` / network calls inside strategy or actor code. Enumerate these in a contract test; do not cite `dst.md` as coverage.

---

## Answer index

| Q | Answer | Where |
| --- | --- | --- |
| 1 | Low-level = direct control / in-memory / non-Parquet; high-level = catalog-backed, config-identified, fresh engine per run. **High-level `BacktestNode` recommended** for reproducible production; low-level has no live path. | Facts 1-2 |
| 2 | **YES.** `data_cls` accepts a **class object** (preferred) or a **colon** path `"module:Class"`. Dotted path **fails**. `fully_qualified_name()` returns the colon form and is directly usable. | Facts 3-6 |
| 3 | `client_id` **mandatory**. High-level → `ValueError` (`node.py:729`); low-level → **`TypeError`** (`engine.pyx:889` / `correctness.pyx:145`). | Facts 7-8, D5 |
| 4 | **`ts_init`.** `engine.pyx:903`, `:1258`, `:2461`, `:2610`. No doc contradiction in 1.231.0. | Fact 9 |
| 5 | `ts_event` = occurrence, `ts_init` = availability; ordering on `ts_init` is the anti-look-ahead mechanism; revisions get a NEW `ts_init` (interval data → `ts_init` at interval close). | Facts 10-13 |
| 6 | Single merged stream, **guaranteed** ordering by `ts_init`, ties `(ts_init, data_priority, data_index)`. Custom data bypasses the exchange but advances the clock and triggers venue settlement. | Facts 14-18 |
| 7 | Shared: kernel, engines, Cache, MessageBus, Portfolio, Actors, Strategies, ExecAlgos. Not shared: data ingress + clock, reconciliation (live only), live latency/timing, low-level API's live path, venue microstructure, off-kernel threads. | Facts 19-20 |
| 8 | Seed-reproducible Rust async scheduling/timers/RNG/channels under `simulation` + `--cfg madsim`; broken by unaliased deps, real transport, adapters, cross-platform. **Python is explicitly out of scope.** Async/executor: yes — `spawn_blocking`/`LocalSet` banned, `select!` must be `biased;`. | Facts 21-26 |
| 9 | **YES** they all load — but metadata does **not** filter, so metadata-only distinction duplicates every row N×. Partition by catalog path, class, or catalog identifier. | Facts 27-31, T2-T3 |
