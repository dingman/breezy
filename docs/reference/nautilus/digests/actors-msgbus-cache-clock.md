# Digest: Actors, MessageBus, Cache, Clock/Timers, Component Lifecycle

<!-- Generated: 2026-08-22 | Repo HEAD: (no commits on master at generation time) -->

- **Source (docs)**: `/home/jon/breezy/docs/reference/nautilus/v1.231.0/` (vendored official docs, git tag `v1.231.0`)
- **Source (ground truth)**: installed `nautilus-trader 1.231.0` at
  `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/`
- **Date**: 2026-08-22
- **Scope**: One-page authority on how a Breezy component ingests non-venue data, publishes it as custom
  data, schedules work on the clock, persists state, and moves through the component lifecycle — Cython
  (`nautilus_trader.*`) API only, verified against the installed binary.

> **Convention in this file.** `path:line` citations without a prefix are the **installed source**
> (rooted at `.venv/lib/python3.13/site-packages/nautilus_trader/`). Doc citations are prefixed
> `docs:` and rooted at `docs/reference/nautilus/v1.231.0/`.
> Where docs and installed source disagree, **installed source wins** and the conflict is recorded in
> "Docs vs code drift".
> Claims tagged **[EMPIRICAL]** were executed against the installed 1.231.0 binary, not merely read.

---

## Verified facts

### A. Actor as an external-data ingestion point

**1. An `Actor` is a documented, sanctioned publisher of custom data — including data it sources
itself rather than receiving from a venue.**
`docs:concepts/data/index.md:1470-1478` states it directly, contrasting adapter-sourced and
actor-sourced paths:

> "An adapter can construct this type and send it to the `DataEngine` for subscribers. An actor or
> strategy can publish it directly:"
> ```python
> self.publish_data(
>     DataType(MyDataPoint, metadata={"some_optional_category": 1}),
>     MyDataPoint(...),
> )
> ```

`docs:concepts/message_bus.md:148-163` names this the "Actor-based publish/subscribe data" messaging
style and scopes it to "**Exchange of structured trading data** like market data, indicators, custom
metrics", with "**Proper event ordering** via built-in timestamps (`ts_event`, `ts_init`) crucial for
backtest accuracy".
`docs:concepts/actors.md:6-12` lists an Actor's key capabilities as including "Data subscription and
requests (market data, **custom data**)" and "Event handling and **publishing**".

**2. There is an in-tree precedent shipped inside the package: `InterestRateProvider(Actor)`.**
`persistence/loaders.py:190-259`. It is the canonical shape for "poll an external source, publish
custom data, reschedule yourself". Verbatim structure:

- `on_start()` → calls `update_interest_rate()` (`loaders.py:218-219`).
- Lazily loads an external file on first call (`loaders.py:223-224`) — external I/O performed inline
  on the actor thread, no executor.
- Timestamps from the **clock**, or from the firing alert: `utc_now_ns = alert.ts_init if alert is not
  None else self.clock.timestamp_ns()` (`loaders.py:227`). This is what keeps it correct in backtest.
- Writes to the cache (`self.cache.add_yield_curve(...)`, `loaders.py:241`).
- Publishes custom data with an explicit `DataType` + metadata (`loaders.py:244-247`).
- **Self-reschedules** with `set_time_alert(..., override=True)` (`loaders.py:251-256`).
- `on_stop()` → `self.clock.cancel_timers()` (`loaders.py:258-259`).

There is **no doc page** for `InterestRateProvider`; it is undocumented but shipped. Treat it as
precedent, not as API contract.

---

### B. Publishing and subscribing to custom data

**3. Exact 1.231.0 signatures (Cython).**

```python
# actor.pyx:2813
cpdef void publish_data(self, DataType data_type, Data data)

# actor.pyx:1258
cpdef void subscribe_data(
    self,
    DataType data_type,
    ClientId client_id = None,
    InstrumentId instrument_id = None,
    bint update_catalog = False,
    dict[str, object] params = None,
)

# actor.pyx:2116
cpdef void unsubscribe_data(...)          # mirrors subscribe_data

# actor.pyx:2832 / 2868
cpdef void publish_signal(self, str name, value, uint64_t ts_event = 0)
cpdef void subscribe_signal(self, str name = "")
```

Handler on the receiving side is the fixed-name `on_data(self, data)` (`actor.pyx:589`); signals go to
`on_signal(self, signal)` (`actor.pyx:605`); request responses go to `on_historical_data(self, data)`
(`actor.pyx:625`).

**4. `data_type` must be a `DataType` INSTANCE, never a bare class. [EMPIRICAL]**
`publish_data` and `subscribe_data` are Cython-typed on `DataType`. Passing the class raises:

```
TypeError: Argument 'data_type' has incorrect type
           (expected nautilus_trader.model.data.DataType, got type)
```

Verified by execution against installed 1.231.0. See "Docs vs code drift" #D1 — `docs:concepts/message_bus.md`
shows the bare-class form and is wrong for this version.

**5. `publish_data` type-checks the payload against the `DataType`.**
`actor.pyx:2827`: `Condition.type(data, data_type.type, "data", "data.type")`. Publishing a payload
whose class differs from `data_type.type` raises. Both `publish_data` and `subscribe_data` also assert
`self.trader_id is not None` — i.e. the actor must have been registered with a trader
(`actor.pyx:2828`, `actor.pyx:1287`).

**6. Topic derivation from `DataType` — exact rule.**
`DataType.__init__` (`model/data.pyx:2094-2107`) computes `.topic` eagerly:

```python
self.topic = self.type.__name__ + '.' + '.'.join([
    f'{k}={v if v is not None else "*"}' for k, v in self.metadata.items()
]) if self.metadata else self.type.__name__ + "*"
```

`TopicCache.get_custom_data_topic` (`common/data_topics.pyx:189-211`) then prefixes it:

| Case | Published / subscribed topic |
|---|---|
| No metadata, no `instrument_id` | `data.WeatherData*` (**literal trailing `*`**) |
| `metadata={"station": "KJFK"}` | `data.WeatherData.station=KJFK` |
| `metadata={"station": None}` | `data.WeatherData.station=*` (explicit wildcard slot) |
| No metadata **but** `instrument_id` supplied | `data.WeatherData.{venue}.{symbol}` (`data_topics.pyx:202`) |
| `request_data(...)` (historical) | same string, prefixed `historical.` (`data_topics.pyx:200,208`) |

`identifier=` does **not** affect the topic or `DataType` equality — it is catalog-path only
(`docs:concepts/custom_data.md:143-150`; confirmed [EMPIRICAL]: `DataType(W, meta, identifier="KJFK") ==
DataType(W, meta)` → `True`, same `.topic`).

**7. Matching is glob on the SUBSCRIPTION pattern against the PUBLISHED topic string.**
`MessageBus.publish_c` → `_resolve_subscriptions` → `is_matching(topic, existing_sub.topic)`
(`common/component.pyx:2860-2891`), an FFI call to the Rust `is_matching_ffi`. Verified end-to-end
with four live actors [EMPIRICAL]:

| Publisher `DataType` | no-meta sub | `{"station":"KJFK"}` sub | `{"station":None}` sub |
|---|---|---|---|
| `{"station":"KJFK"}` | **receives** | **receives** | **receives** |
| no metadata | **receives** | *drops* | *drops* |

So: a metadata-less subscription is the widest net; a metadata-bearing subscription **never** sees a
metadata-less publication. See Traps T1–T3.

**8. The `on_data` payload is the inner object, not a `CustomData` wrapper.**
Actor-published data is the raw object (`actor.pyx:2830`: `self._msgbus.publish_c(topic=..., msg=data)`).
DataEngine-delivered custom data is unwrapped before publish:
`data/engine.pyx:2845-2848` — `self._msgbus.publish_c(topic=topic, msg=data.data)`. Both paths give
`on_data` the plain `Data` subclass, so a single `isinstance` check works for either origin.
`docs:concepts/data/index.md:1508-1512` correctly instructs type-checking in `on_data` "because the
handler receives all custom data".

**9. `subscribe_data` with neither `client_id` nor `instrument_id` still subscribes on the bus, then
logs an ERROR and returns before sending the engine command. [EMPIRICAL]**
`actor.pyx:1289-1297`: the `self._msgbus.subscribe(...)` call happens **first**, then the guard:

```python
if client_id is None and instrument_id is None:
    self.log.error("`Actor.subscribe_data`: `client_id` or `instrument_id` need to be specified")
    return
```

Consequence: pure actor→actor pub/sub works (bus routing is live) but emits a red ERROR line every
start. For intra-process-only custom data, pass a dummy `ClientId` to silence it, or subscribe via
`self.msgbus.subscribe(topic=..., handler=...)` directly (`docs:concepts/actors.md:311-331` documents
that direct pattern for order events, and `docs:concepts/actors.md:385-388` notes "Direct message bus
subscriptions do not send data engine commands").

**10. Signal values are restricted to `int | float | str` — nothing else. [EMPIRICAL]**
`actor.pyx:2851`: `Condition.is_in(type(value), (int, float, str), ...)`. `True` and `b"y"` both raise
`KeyError`. Signal topic is `data.Signal{Name.title()}*` (`data_topics.pyx:239`); the signal **name is
not recoverable in the handler** — match on `signal.value`
(`docs:concepts/message_bus.md:234-235`).

---

### C. Clock: `set_timer` vs `set_time_alert`

**11. Signatures (both on the `Clock` base, `common/component.pyx`).**

```python
# component.pyx:316 — ONE-SHOT
cpdef void set_time_alert(
    self, str name, datetime alert_time,
    callback: Callable[[TimeEvent], None] = None,
    bint override = False,       # if True, cancels an existing same-name timer first
    bint allow_past = True,      # False -> ValueError if alert_time < now
)

# component.pyx:419 — RECURRING
cpdef void set_timer(
    self, str name, timedelta interval,
    datetime start_time = None,  # None -> now
    datetime stop_time = None,   # None -> repeats indefinitely
    callback: Callable[[TimeEvent], None] | None = None,
    bint allow_past = True,
    bint fire_immediately = False,  # True -> fire at start_time, then every interval
)
```
`*_ns` variants take `uint64_t` epoch-nanoseconds (`component.pyx:373`, `component.pyx:485`).

**12. Semantics.** `set_time_alert` fires **once**; `set_timer` fires **every `interval`** until
`stop_time` or `cancel_timer(name)`. Names must be unique per clock —
`Condition.not_in(name, self.timer_names, ...)` (`component.pyx:686`, `component.pyx:715`) raises on a
duplicate. `set_time_alert(override=True)` is the sanctioned way to re-arm a same-named one-shot
(`component.pyx:364-365`: `if override and self.next_time_ns(name) > 0: self.cancel_timer(name)`).
Without `override=True`, re-arming the same name raises.

**13. Callback routing.** A `callback` receives the `TimeEvent` directly. If `callback is None`, the
event goes to the clock's **default handler**, which `Actor.register_base` wires to
`self.handle_event` → `on_event` (`actor.pyx:722`: `clock.register_default_handler(self.handle_event)`;
`docs:concepts/actors.md:133-134`).

**14. Backtest vs live — determinism.**
- **Backtest** uses `TestClock` (`component.pyx:623`). Each component gets **its own clock instance**
  (`trading/trader.py:342-343`: `clock = self._clock.__class__(); register_component_clock(...)`).
  `BacktestEngine` advances all component clocks from the **data stream's `ts_init`**
  (`backtest/engine.pyx:1689-1692` → `_advance_time(data.ts_init)`; `engine.pyx:1765-1800`), and drains
  timers via a time-ordered accumulator, **re-checking for newly scheduled timers after each callback**
  so chained self-rescheduling alerts stay monotonic (comment at `engine.pyx:1766-1771`). When the data
  stream is exhausted the loop calls `_process_next_timer()` (`engine.pyx:1678`) so timers still fire.
  Net: timers are **fully deterministic** in backtest and fire on simulated time, never wall-clock.
- **Live** uses `LiveClock` (`component.pyx:839`), backed by Rust timers; callbacks are wrapped by
  `create_pyo3_conversion_wrapper` (`component.pyx:1004-1008`) before crossing the FFI boundary.
- `Trader._start()` calls `actor.clock.set_time(now_ns)` on every component clock **before**
  `actor.start()` when `environment == BACKTEST` (`trading/trader.py:252-259`), so `self.clock.utc_now()`
  inside `on_start` is already simulated time.

**15. Timers are auto-cancelled on stop and on dispose.**
`Actor._stop()` (`actor.pyx:1211-1226`) runs `on_stop()` **then** `self._clock.cancel_timers()` and
logs each cancellation, **then** cancels all executor tasks. `Actor._dispose()` (`actor.pyx:1241-1249`)
calls `Component._dispose` (cancels timers), `on_dispose()`, then
`cancel_default_handler()` + `cancel_callbacks()` to break the actor↔clock reference cycle that
Python's GC cannot trace. So the `docs:concepts/actors.md:120-122` advice to cancel timers in
`on_stop()` is defensive, not required.

---

### D. Executor

**16. Documented purpose.** `register_executor(loop, executor)` (`actor.pyx:734`) attaches an
`ActorExecutor` (`common/executor.py:60`) — "an executor for `Actor` and `Strategy` classes … queues
and executes tasks within a given event loop and is tailored for single-threaded applications"
(`executor.py:61-70`). Two submit APIs:
- `run_in_executor(func, args=None, kwargs=None) -> TaskId` (`actor.pyx:1047`) — schedule.
- `queue_for_executor(func, args=None, kwargs=None) -> TaskId` (`actor.pyx:991`) — **sequential** queue.
Companion introspection/cancellation: `queued_task_ids`, `active_task_ids`, `has_queued_tasks`,
`has_active_tasks`, `has_any_tasks`, `cancel_task`, `cancel_all_tasks` (`actor.pyx:1104-1206`).

**17. With NO executor registered, both methods execute `func` SYNCHRONOUSLY, inline, and return a
fresh `TaskId`. [EMPIRICAL]**
`actor.pyx:1091-1096` (identical shape at `actor.pyx:1030-1035`):

```python
if self._executor is None:
    func(*args, **kwargs)
    task_id = TaskId.create()
else:
    task_id = self._executor.run_in_executor(func, *args, **kwargs)
```

Docstring (`actor.pyx:1072-1077`): *"For backtesting the `func` is immediately executed, as there's no
need for a `Future` object that can be awaited."* Verified: submit-then-append produced
`['task', 'after']`, `queued_task_ids() == []`, `has_any_tasks() == False`.

**18. An executor is registered ONLY on the live/async start path — never in backtest.**
`system/kernel.py:1020` calls `self._register_executor()` inside `start_async()`; the synchronous
`start()` (`kernel.py:989-1001`) does **not**. `_register_executor` (`kernel.py:1254-1262`) loops over
actors, strategies and exec algorithms, handing each a shared
`concurrent.futures.ThreadPoolExecutor` created at `kernel.py:279-280`. **Therefore backtests remain
deterministic even if Breezy code calls `run_in_executor` unconditionally** — the call degenerates to
a direct invocation.

**19. Thread-safety caveat.** `executor.py:81-85`: "This executor is not fully thread-safe. Only
`queue_for_executor` can be safely called from other threads. All other methods (`cancel_task`,
`get_future`, `reset`, etc.) must be invoked from the same thread in which the executor was created."

---

### E. State persistence — what actually survives a restart

**20. `on_save` / `on_load` contract.**
```python
cpdef dict[str, bytes] on_save(self)              # actor.pyx:208 — returns {} by default
cpdef void on_load(self, dict[str, bytes] state)  # actor.pyx:226 — no-op by default
```
Both are `bytes`-valued: **you serialize yourself** (the docs' cache examples use `pickle`,
`docs:concepts/cache.md` "Cache vs. strategy variables"). Framework entry points are
`Actor.save()` (`actor.pyx:876-911`) and `Actor.load(state)` (`actor.pyx:913-946`); both **catch, log,
and re-raise** exceptions — `save()` re-raises deliberately, "Otherwise invalid state information
could be saved" (`actor.pyx:911`). `save()` refuses and returns `None` if the actor was never
registered with a trader (`actor.pyx:892-896`).

**21. Persistence requires BOTH a kernel flag AND a cache database. This is the load-bearing fact.**
- Write: `NautilusKernel.stop()` / `stop_async()` → `if self.save_state: self._trader.save()`
  (`kernel.py:1053-1054`, `kernel.py:1091-1092`) → `Cache.update_actor(actor)`
  (`trading/trader.py:822`) → `cache/cache.pyx:2742-2757`, which does
  `if self._database is not None: self._database.update_actor(actor)` → `cache/database.pyx:1105`
  calls `actor.save()`.
- Read: `NautilusKernel.__init__` → `if self._load_state: self._trader.load()`
  (`kernel.py:538-539`) → `Cache.load_actor(actor)` (`cache/cache.pyx:1530-1552`), which does
  `if self._database is not None: state = self._database.load_actor(actor.id)`.

**With `CacheConfig.database = None` (the default, and the default in backtests), `on_save` is never
called and `on_load` never receives anything — silently.** The only trace is an INFO line
`"No previous state found for <id>"` (`cache.pyx:1551`). A backing store must be configured via
`CacheConfig.database` (`cache/config.py:63`) — Redis or Postgres
(`docs:concepts/cache.md:134-143`).

**22. Generic `Cache.add` / `Cache.get` — signatures and reach. [EMPIRICAL]**
```python
cpdef void  add(self, str key, bytes value)   # cache/cache.pyx:1686
cpdef bytes get(self, str key)                # cache/cache.pyx:2834 -> bytes or None
```
`value` is strictly `bytes`; passing `str` raises `TypeError`. `add` writes the in-memory
`self._general` dict **and** forwards to the database when one exists
(`cache.pyx:1704-1708`). On startup `Cache.cache_general()` (`cache.pyx:279-303`) repopulates
`_general` from `self._database.load()`, or sets `{}` when there is no database.
`docs:concepts/cache.md` documents exactly this shape:
```python
self.cache.add(key="my_key", value=b"some binary data")
stored_data = self.cache.get("my_key")  # Returns bytes or None
```
and warns: *"The `Cache` is not designed to be a full database replacement."*

**23. Survives / does not survive a restart:**

| Item | Survives restart? |
|---|---|
| `on_save` dict, keyed per `actor_id` | **Only** with `save_state=True` + `load_state=True` + `CacheConfig.database` set |
| `Cache.add(key, bytes)` general entries | **Only** with `CacheConfig.database` set (`cache.pyx:1707`) |
| Plain Python attributes on the Actor | **Never** |
| Registered timers / alerts | **Never** — cancelled in `_stop()`/`_dispose()` (`actor.pyx:1216`) |
| Message-bus subscriptions | **Never** — re-subscribe in `on_start()` |
| In-flight `run_in_executor` tasks | **Never** — `cancel_all_tasks()` in `_stop()` (`actor.pyx:1224-1226`) |
| Custom data written via catalog / `update_catalog=True` | Yes (Parquet on disk, separate mechanism) |

**24. Actor IDs must be stable across restarts for state to reload.** `Cache.load_actor` keys on
`actor.id` (`cache.pyx:1544`). `ActorConfig.component_id` (or `actor_id`) is what fixes it — "The base
config may include an `actor_id`; if supplied, the actor registers with that ID. If omitted, the system
derives a runtime actor ID" (`docs:concepts/actors.md:48-50`). A derived ID that changes between runs
orphans the saved state.

---

### F. Lifecycle ordering

**25. State machine** (`docs:concepts/actors.md:66-97`, `docs:concepts/architecture.md:380-403`):
`PRE_INITIALIZED --register()--> READY --start()--> STARTING --on_start()--> RUNNING`, then
`stop()→STOPPING→on_stop()→STOPPED`, `resume()→RUNNING`, `degrade()`, `fault()`,
`dispose()→DISPOSED`. Handler table: `on_start`, `on_stop`, `on_resume`, `on_reset`, `on_degrade`,
`on_fault`, `on_dispose` (`docs:concepts/actors.md:89-97`).

**26. Guaranteed to have happened BEFORE `on_start()` runs:**
1. `__init__(config)` — but at this point `self.msgbus`, `self.cache`, `self.clock`, `self.trader_id`,
   `self.portfolio` are all still `None` (`actor.pyx:183-189`). **Do not touch them in `__init__`.**
2. `register_base(portfolio, msgbus, cache, clock)` — via `Trader.add_actor`
   (`trading/trader.py:342-352`). This assigns a **dedicated clock instance per component**, registers
   `self.handle_event` as that clock's default handler, assigns `trader_id`, `msgbus`, `cache`,
   `portfolio`, `log`, and builds `self.greeks` (`actor.pyx:689-730`).
3. `on_load(state)` — if `load_state=True`, this runs during **`NautilusKernel.__init__`**
   (`kernel.py:538-539`), i.e. long before `start()`. **`on_load` precedes `on_start`.**
4. Engines started, data/exec clients connected, emulator started, portfolio initialized — all before
   `Trader.start()` (`kernel.py:997-1001`). In `start_async` additionally: executor registered,
   engines awaited connected, execution reconciliation awaited (`kernel.py:1020-1039`).
5. In BACKTEST only: `actor.clock.set_time(now_ns)` (`trading/trader.py:256-257`).

Not guaranteed before `on_start`: any market data having arrived, instruments being in the cache
(request them in `on_start` and handle in `on_instrument` / `on_historical_data`).

**27. Order within stop/reset/dispose (`actor.pyx:1211-1249`):**
- `_stop()`: `on_stop()` → `clock.cancel_timers()` (`actor.pyx:1216`, each cancellation logged) → `executor.cancel_all_tasks()` (`actor.pyx:1226`).
- `_reset()`: `on_reset()` → clears `_requests`, `_pending_requests`, and all registered indicators.
  Message-bus subscriptions are **not** cleared by reset.
- `_dispose()`: `Component._dispose(self)` (cancels timers) → `on_dispose()` →
  `clock.cancel_default_handler()` + `clock.cancel_callbacks()`.

**28. `on_start` / `on_stop` / `on_resume` / `on_reset` log a WARNING when not overridden**
(`actor.pyx:255-259`, `276-280`, `295-299`, `313-317`). `on_save`, `on_load`, `on_dispose`,
`on_degrade`, `on_fault` are silent no-ops. A stray "handler was called when not overridden" warning in
Breezy logs means a lifecycle hook is missing, not that something failed.

**29. Every data handler is gated on `RUNNING` and silently drops otherwise.**
`actor.pyx:4698-4721`: `handle_data` (definition at `actor.pyx:4698`) calls `on_data` **only** `if self._fsm.state ==
ComponentState.RUNNING`. Same gate on `handle_signal` (definition `actor.pyx:4723`, gate `actor.pyx:4741`). Confirmed [EMPIRICAL]: after
`actor.stop()`, the message-bus subscription remains registered and the message is still delivered to
`handle_data`, but `on_data` is never invoked — no log, no warning. See Trap T5.

---

### G. Logging

**30. Inside a component: use `self.log`.** Assigned in `register_base` (`actor.pyx:730`) and listed in
`docs:concepts/actors.md:140-146` as one of the five system-access properties
(`self.cache`, `self.portfolio`, `self.clock`, `self.log`, `self.msgbus`).

**31. `Logger` API (`common/component.pyx:1396-1424`).** Constructor is `Logger(name: str)`; the name
appears in each log line. Level methods are
`debug/info/warning/error(message: str, color: LogColor = LogColor.NORMAL)` and
`exception(message, ex)`. `LogColor` comes from `nautilus_trader.common.enums`
(`LogColor.GREEN/RED/BLUE/NORMAL`). Nautilus's own code uses `color=LogColor.BLUE` for state
save/load lines (`actor.pyx:903`).

**32. There are NO structured key/value fields for Python callers.** The Python surface is
message-string only; structure comes from the **file** format, not the call site — set
`LoggingConfig(log_file_format="json")` to emit `.jsonl`
(`docs:concepts/logging.md`, "File logging"). Interpolate context into the message string
(f-strings) as Nautilus does.

**33. Standalone use outside a kernel** (`docs:concepts/logging.md`, "Using a logger directly"):
```python
from nautilus_trader.common.component import init_logging, Logger
log_guard = init_logging()
logger = Logger("MyLogger")
```
Only one logging subsystem per process; up to 255 concurrent `LogGuard`s; the logging thread stays
alive until all guards drop. Running multiple sequential backtest engines in one process **requires**
holding a `LogGuard` from the first engine (`engine.get_log_guard()`), otherwise later engines emit
`Error sending log event: ...`.

**34. Per-component level filtering.** `LoggingConfig(log_component_levels={"Portfolio": "INFO"})` —
exact match on component ID. Env alternative: `NAUTILUS_LOG="stdout=Info;fileout=Debug;RiskEngine=Error;is_colored"`.
`log_components_only=True` with an **empty** `log_component_levels` emits **nothing at all** — the docs
flag this explicitly as a warning.

---

### H. `Actor.request_data`

**35. Full 1.231.0 signature (`actor.pyx:2893-2906`):**
```python
cpdef UUID4 request_data(
    self,
    DataType data_type,
    ClientId client_id,                 # POSITIONAL AND REQUIRED (Condition.not_none)
    InstrumentId instrument_id = None,
    datetime start = None,              # TypeError if None (see below)
    datetime end = None,                # None -> now
    int limit = 0,
    callback: Callable[[UUID4], None] | None = None,
    bint update_catalog = False,        # <-- the flag; a bool, not an enum
    bint join_request = False,
    UUID4 request_id = None,
    dict[str, object] params = None,
)  # returns the request UUID4
```

**36. YES — `update_catalog` exists, and it is a plain `bint`, not an enum.**
Documented as "`update_catalog : bool, default False` — Whether to update a catalog with the received
data" (`actor.pyx:2934-2935`). It is **not** a direct argument to the data client: it is folded into
the request `params` map — `used_params["update_catalog"] = update_catalog` (`actor.pyx:2970`) — and
travels on the `RequestData` message to the resolving client/catalog layer. It therefore applies on the
**request/response (historical) path only**. The same `bint update_catalog` parameter appears on 20+
Actor methods including all `subscribe_*` and every `request_*` (grep: `update_catalog` at
`actor.pyx:1263, 1319, 1368, 1489, 1637, 1692, 1877, 2902, 3008, 3117, 3227, 3324, 3504, 3616, 3723,
3830, 3941, …`). On `subscribe_*` the docstring adds: *"Only useful when downloading data during a
backtest"* (`actor.pyx:1279-1281`).

**37. Response routing and cleanup.** `request_data` subscribes `handle_historical_data` to
`historical.data.<DataType.topic>` (`actor.pyx:2992-2995`), records the request in `self._requests`
and the user callback in `self._pending_requests`, then sends the command. On response,
`_handle_data_response` (`actor.pyx:4796-4804`) pops the request and **unsubscribes the historical
topic**, then fires the user `callback(request_id)`. Data lands in `on_historical_data`, **not**
`on_data` (`docs:concepts/actors.md:191`, `actor.pyx:625`).

**38. `start` is effectively mandatory.** Docstring: *"start : datetime — The start datetime (UTC) of
request time range. **Cannot be `None`**"*, and `Raises: TypeError If start is None`
(`actor.pyx:2921-2924, 2947-2952`). Additional `ValueError`s if `start > now`, `end > now`, or
`start > end` — enforced by `self._validate_datetime_range(start, end)` (`actor.pyx:2966`).

---

## Documented patterns

### Pattern 1 — Actor polls an external source on a timer and publishes custom data

Shape derived from `persistence/loaders.py:190-259` (in-tree precedent) plus
`docs:concepts/actors.md:99-134` and `docs:concepts/data/index.md:1470-1478`.

```python
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TimeEvent
from nautilus_trader.config import ActorConfig
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.data import DataType
from nautilus_trader.model.identifiers import ClientId
from datetime import timedelta


@customdataclass
class WeatherObservation(Data):
    station: str
    temp_c: float


class WeatherPollerConfig(ActorConfig):
    # component_id pins the actor ID -> required for on_save/on_load to reattach (fact 24)
    component_id: str = "WEATHER-POLLER"
    station: str = "KJFK"
    poll_interval_secs: int = 300


class WeatherPoller(Actor):
    def __init__(self, config: WeatherPollerConfig) -> None:
        super().__init__(config)
        # msgbus/cache/clock are still None here (fact 26) - only plain state.
        self._last_ts_event: int = 0

    def on_start(self) -> None:
        self._poll(None)                       # prime immediately, like InterestRateProvider
        self.clock.set_timer(
            name="weather-poll",
            interval=timedelta(seconds=self.config.poll_interval_secs),
            callback=self._poll,               # explicit callback -> bypasses on_event
        )

    def _poll(self, event: TimeEvent | None) -> None:
        # Clock-derived time, never wall clock -> correct under TestClock (fact 14).
        now_ns = event.ts_init if event is not None else self.clock.timestamp_ns()

        # Blocking I/O. With no executor registered (backtest) this runs inline and
        # stays deterministic; in live, self.run_in_executor(...) offloads it (facts 17-18).
        temp_c = self._fetch(self.config.station)

        obs = WeatherObservation(
            station=self.config.station,
            temp_c=temp_c,
            ts_event=now_ns,
            ts_init=now_ns,
        )
        # Metadata is what makes the topic addressable per-station (fact 6).
        self.publish_data(
            DataType(WeatherObservation, metadata={"station": self.config.station}),
            obs,
        )
        self._last_ts_event = now_ns

    def on_stop(self) -> None:
        self.clock.cancel_timer("weather-poll")   # belt-and-braces; _stop() also does it (fact 15)

    def _fetch(self, station: str) -> float:
        ...
```

### Pattern 2 — Another component subscribes

```python
class WeatherConsumer(Actor):
    def on_start(self) -> None:
        self.subscribe_data(
            data_type=DataType(WeatherObservation, metadata={"station": "KJFK"}),
            client_id=ClientId("WEATHER"),   # required, else red ERROR log (fact 9)
        )

    # Widest net (also receives every metadata variant AND any class whose name
    # starts with "WeatherObservation" - see Trap T2):
    #   self.subscribe_data(DataType(WeatherObservation), client_id=ClientId("WEATHER"))
    #
    # Per-key wildcard - matches any station, but ONLY metadata-bearing publications:
    #   self.subscribe_data(DataType(WeatherObservation, metadata={"station": None}), ...)

    def on_data(self, data: Data) -> None:
        if isinstance(data, WeatherObservation):   # always type-check (fact 8)
            ...

    def on_stop(self) -> None:
        self.unsubscribe_data(
            data_type=DataType(WeatherObservation, metadata={"station": "KJFK"}),
            client_id=ClientId("WEATHER"),
        )
```

For a purely intra-process channel with no data-engine involvement, the documented alternative is the
raw bus (`docs:concepts/actors.md:311-331`):

```python
def on_start(self) -> None:
    self.msgbus.subscribe(topic="data.WeatherObservation.station=KJFK", handler=self._on_obs)

def on_stop(self) -> None:
    self.msgbus.unsubscribe(topic="data.WeatherObservation.station=KJFK", handler=self._on_obs)
```

### Pattern 3 — Saving and restoring state

```python
import msgspec


class StatefulActor(Actor):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._seen: dict[str, int] = {}

    # Values MUST be bytes; you own serialization (fact 20).
    def on_save(self) -> dict[str, bytes]:
        return {"seen": msgspec.json.encode(self._seen)}

    # Runs during kernel construction, BEFORE on_start (fact 26.3).
    def on_load(self, state: dict[str, bytes]) -> None:
        raw = state.get("seen")
        if raw is not None:
            self._seen = msgspec.json.decode(raw)

    # Cross-component shared scratch (fact 22) - also DB-backed only.
    def _share(self) -> None:
        self.cache.add("breezy:last_poll_ns", str(self.clock.timestamp_ns()).encode())

    def _read_share(self) -> int | None:
        raw = self.cache.get("breezy:last_poll_ns")   # bytes | None
        return int(raw) if raw is not None else None
```

Wiring required for any of the above to actually persist (fact 21):

```python
from nautilus_trader.config import CacheConfig, DatabaseConfig, TradingNodeConfig

TradingNodeConfig(
    trader_id="BREEZY-001",
    cache=CacheConfig(database=DatabaseConfig()),  # None (default) => NOTHING persists
    save_state=True,                               # writes on kernel stop
    load_state=True,                               # reads during kernel __init__
    ...
)
```

---

## Docs vs code drift

Installed 1.231.0 source is authoritative for every row.

| # | Doc claim | Installed 1.231.0 reality |
|---|---|---|
| **D1** | `docs:concepts/message_bus.md:198,201` — `self.publish_data(GreeksData, data)` and `self.subscribe_data(GreeksData)` (bare **class**). | **Raises `TypeError`.** Both params are Cython-typed `DataType` (`actor.pyx:2813, 1258`). Must be `DataType(GreeksData)`. `docs:concepts/data/index.md:1477,1500` shows the **correct** form — prefer that page. [EMPIRICAL] |
| **D2** | `docs:concepts/actors.md:233` — `request_bars(..., update_catalog_mode=None,  # UpdateCatalogMode \| None)`. | No `UpdateCatalogMode` symbol and no `update_catalog_mode` parameter exist anywhere in the installed package (grep across `*.py`/`*.pyx`/`*.pyi` → 0 hits). The real parameter is `bint update_catalog = False` (`actor.pyx:3830`). This example line is imported from a later (2.x) API. |
| **D3** | `docs:concepts/message_bus.md:19-30` — replayed/requested data publishes on `data.pipeline.<kind>...`, e.g. `data.pipeline.book.deltas.XCME.ESZ24`. | No `data.pipeline` string exists in the installed Cython source. The historical/replay prefix is `historical.` prepended to the normal topic (`common/data_topics.pyx:64,103,112,121,130,200,208`), e.g. `historical.data.WeatherData.station=KJFK`. The `data.pipeline` root is a 2.x/Rust-runtime concept. |
| **D4** | `docs:concepts/data/index.md` (signals) — "one `str`, `float`, `int`, `bool`, or `bytes` value". | Only `int`, `float`, `str`. `bool` and `bytes` raise `KeyError` from `Condition.is_in(type(value), (int, float, str), ...)` (`actor.pyx:2851`). Note `docs:concepts/message_bus.md:234` states the correct trio — the two doc pages contradict each other. [EMPIRICAL] |
| **D5** | `docs:concepts/actors.md:55-64` — a `Rust implementation` info box describing `DataActor` / `DataActorNative` / `DataActorConfig`. | Those are the Rust/2.x actor surface. The Python/Cython class Breezy extends is `nautilus_trader.common.actor.Actor`. `nautilus_pyo3.DataActor` **does exist** in the installed 1.231.0 build, so the presence of the name is not by itself proof a doc is 2.x — see D6. |
| **D6** | The project's own version heuristic ("`register_custom_data_class` + `DataType("Name", ...)` ⇒ 2.x; `Actor` + `@customdataclass` + `DataType(SomeClass, …)` ⇒ 1.231.0"). | **Unreliable — both surfaces ship in 1.231.0.** Verified [EMPIRICAL]: `nautilus_pyo3.DataType("MarketTickPython", {"exchange": "NASDAQ"})` constructs fine, `nautilus_pyo3.register_custom_data_class` and `nautilus_pyo3.DataActor` all exist, and `nautilus_trader.model.custom` exports **both** `customdataclass` and `customdataclass_pyo3`. `docs:concepts/custom_data.md:375-383` states this outright: *"The Cython `@customdataclass` system is separate from this architecture. This document describes the PyO3 custom-data system."* The reliable discriminator is the **import path**, not the symbol name: `nautilus_trader.model.data.DataType` (Cython, class-first) vs `nautilus_trader.core.nautilus_pyo3.model.DataType` (PyO3, string-first). Breezy's Actor/msgbus/cache path is entirely Cython. |
| **D7** | `docs:concepts/actors.md:120-122` — "Cancel timers to prevent resource leaks across stop/resume cycles". | Accurate as advice but **not** required: `Actor._stop()` calls `self._clock.cancel_timers()` unconditionally after `on_stop()` (`actor.pyx:1216`). Note the corollary: a timer set inside `on_stop()` is cancelled immediately afterwards. |
| **D8** | `docs:concepts/actors.md:99-134` and `docs:concepts/cache.md` never mention that `subscribe_data` **requires** `client_id` or `instrument_id`. | It does, and violating it logs `[ERROR] ... 'client_id' or 'instrument_id' need to be specified` on every start while still leaving a working bus subscription (`actor.pyx:1289-1297`). Undocumented; the code even carries a `# TODO` acknowledging the gap. |
| **D9** | No doc page covers `InterestRateProvider`. | It ships at `persistence/loaders.py:190`. Undocumented in-tree precedent — usable as a shape reference, not as a stability guarantee. |

---

## Traps (silent wrong results)

**T1 — A metadata-bearing subscriber never sees a metadata-less publication. [EMPIRICAL]**
Publishing `DataType(WeatherData)` produces the literal topic `data.WeatherData*`. A subscriber on
`DataType(WeatherData, metadata={"station": "KJFK"})` has pattern `data.WeatherData.station=KJFK`,
which does not match. **No error, no warning, zero messages.** Rule: the publisher's metadata must be a
superset shape of the subscriber's, never the reverse. Pick one metadata schema per custom type and use
it on *every* publish.

**T2 — Class-name PREFIX collision on metadata-less subscriptions. [EMPIRICAL]**
Pattern `data.WeatherData*` matches topic `data.WeatherDataHourly*`. A `DataType(WeatherData)`
subscriber **receives `WeatherDataHourly` objects in `on_data`**. Confirmed by execution. Two
mitigations, use both: (a) always `isinstance`-check in `on_data`
(`docs:concepts/data/index.md:1508-1512`); (b) never name a Breezy custom data class as a prefix of
another (`WeatherObservation` / `WeatherObservationHourly` collide — use `HourlyWeatherObservation`).

**T3 — Metadata dict key ORDER changes the topic, while `DataType` equality ignores it. [EMPIRICAL]**
`DataType(W, {"a":1,"b":2}) == DataType(W, {"b":2,"a":1})` → `True`, and their hashes are equal
(`__eq__`/`__hash__` use `frozenset(metadata.items())`, `model/data.pyx:2106-2107,2112`). But `.topic`
is built by iterating `metadata.items()` in **insertion order** (`model/data.pyx:2102-2104`), giving
`WeatherData.a=1.b=2` vs `WeatherData.b=2.a=1` — which do **not** glob-match. Verified: a subscriber
built with reversed key order received **0** of the publisher's messages while comparing equal to the
publisher's `DataType`. Any equality-based unit test will pass while production delivers nothing.
Mitigation: build every `DataType` for a given type through **one shared factory function** so key
order is fixed in a single place.

**T4 — DataEngine-delivered custom data re-routes when the payload has an `instrument_id` attribute.**
`DataEngine._handle_custom_data` does `getattr(data.data, "instrument_id", None)` and, when metadata is
absent, routes to `data.<Type>.<venue>.<symbol>` instead of `data.<Type>*`
(`data/engine.pyx:2846-2847`; `common/data_topics.pyx:195-203`). Note the asymmetry: `Actor.publish_data` calls `get_custom_data_topic(data_type)` with **no** `instrument_id` (`actor.pyx:2830`), so the venue/symbol topic form is reachable only via the DataEngine path. Adding an `instrument_id` field to a
Breezy custom data class silently re-routes engine-delivered instances away from existing metadata-less
subscribers.

**T5 — Data is silently discarded whenever the actor is not `RUNNING`. [EMPIRICAL]**
`handle_data` / `handle_signal` check `self._fsm.state == ComponentState.RUNNING` and return with no
log otherwise (`actor.pyx:4716`, `actor.pyx:4741`). Verified: a STOPPED actor stays subscribed on the
bus and is still invoked, but `on_data` never fires. Anything published during `STARTING` (i.e. from
inside another component's `on_start`, before this actor reaches `RUNNING`) is lost. Do not treat
`on_start` ordering across actors as a delivery guarantee — prime state from the cache or a
`request_data(...)` instead.

**T6 — `on_save` / `on_load` are silent no-ops without a cache database.**
With `CacheConfig.database=None` (default), `Cache.update_actor` / `Cache.load_actor` skip the database
branch entirely (`cache/cache.pyx:2755-2757`, `cache/cache.pyx:1543-1544`). `on_save` is **never
called**. The only signal is one INFO line, `"No previous state found for <id>"`. State-persistence
tests must assert against a configured backing store, or they assert nothing.

**T7 — Changing the actor ID orphans saved state.**
State is keyed by `actor.id` (`cache.pyx:1544`). Omitting `component_id`/`actor_id` from the config
means a runtime-derived ID (`docs:concepts/actors.md:48-50`); a rename or a derived-ID change loads
`{}` and logs only INFO. Pin `component_id` in every Breezy `ActorConfig`.

**T8 — Duplicate timer name raises; `set_time_alert` without `override=True` cannot be re-armed.**
`Condition.not_in(name, self.timer_names, ...)` (`component.pyx:686,715`). A self-rescheduling one-shot
**must** pass `override=True` (as `InterestRateProvider` does, `loaders.py:255`) or it raises `KeyError`
on the second arming.

**T9 — Backtest data ordering is by `ts_init`, not `ts_event`.**
`docs:concepts/data/index.md:1466-1468`: *"Backtests order the data stream by `ts_init`."* Confirmed by
`backtest/engine.pyx:1685-1692`, which advances clocks off `data.ts_init`. Weather observations that
carry an observation time in `ts_event` and an ingestion time in `ts_init` will replay on the
**ingestion** timeline. If `ts_init` reflects a real-world fetch time later than the observation, the
backtest will legitimately show the data arriving late — that is correct look-ahead protection, but it
must be set deliberately, not accidentally.

**T10 — `run_in_executor` gives no isolation in backtest.**
With no executor registered, `func` runs inline and any exception it raises propagates into the caller's
stack frame instead of landing in a `Future` (`actor.pyx:1091-1093`). Code that relies on
"exceptions are swallowed by the future" behaves differently between live and backtest. Handle
exceptions inside `func`.

**T11 — `save()` re-raises.** `Actor.save()` catches, logs, and **re-raises** any `on_save` exception
by design (`actor.pyx:908-911`). A bug in `on_save` therefore aborts kernel shutdown. Keep `on_save`
allocation-free and total.

**T12 — Executor thread-safety.** Only `queue_for_executor` may be called from a non-kernel thread
(`executor.py:81-85`). Calling `cancel_task` / `has_active_tasks` from a websocket or polling thread is
undefined behavior.

---

## Open questions (docs do not answer)

1. **Backpressure / drop policy for a live `Actor` timer whose callback outruns its interval** —
   whether `LiveClock` coalesces missed ticks or queues them. Not stated in `docs:concepts/actors.md`
   or `docs:concepts/architecture.md`; the behavior lives in Rust (`live_clock_set_timer`), not
   inspectable from the installed Python surface.
2. **Whether `update_catalog=True` on `subscribe_*` is honored by an arbitrary custom data client**, or
   only by the built-in catalog-backed clients. It is passed opaquely via `params`
   (`actor.pyx:1300`) and no doc specifies the client-side contract.
3. **`join_request=True` semantics** on `request_data` — the docstring says "If a request should be
   joined and sorted with another one by using request_join" (`actor.pyx:2937-2938`); no concept doc
   explains how requests are grouped or how `_handle_join_response` (`actor.pyx:4806`) terminates.
4. **Whether `on_reset` is invoked between backtest runs in the `BacktestNode` (config-driven) path**,
   or only via explicit `engine.reset()`. `docs:concepts/actors.md:94` claims "called between backtest
   runs"; the call site was not traced in this pass.
5. **Ordering guarantees among multiple actors subscribed to the same topic.** Subscriptions are sorted
   by `Subscription` priority (`common/component.pyx:2739`), but the documented advice is not to touch
   priority ("Only assign a higher priority to the subscription if you are certain of what you're
   doing", `component.pyx:2706-2713`). Default-priority relative ordering across actors is unspecified.
6. **Maximum practical size for `Cache.add` values.** Docs warn only that the cache "is not designed to
   be a full database replacement" (`docs:concepts/cache.md`) — no numeric guidance.
