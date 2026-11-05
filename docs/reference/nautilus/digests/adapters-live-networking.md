# Nautilus 1.231.0 — Adapters / Live Trading / Networking Digest

<!-- Generated: 2026-08-22 | Commit: (none — repo has no commits yet) | nautilus-trader 1.231.0 -->

- **Doc source (authoritative for prose):** `/home/jon/breezy/docs/reference/nautilus/v1.231.0/`
- **Code source (authoritative on disagreement):** `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/` (`METADATA: Version: 1.231.0`)
- **Scope:** what the official 1.231.0 docs + installed source actually sanction for building a non-venue live data client, wiring it into `TradingNode`, and making outbound HTTP calls.

All `file.py:NN` citations below are relative to the installed package root
`/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/`.
All `docs/...` citations are relative to `/home/jon/breezy/docs/reference/nautilus/v1.231.0/`.

---

## Verified facts

### Q1 — `LiveDataClient` vs `Actor` for non-venue HTTP data

1. **The docs do not contain a decision rule.** Exhaustive grep across `concepts/`, `how_to/`,
   `developer_guide/` for `custom data client`, `non-market`, `use an actor`, `instead of a data
   client` returns **zero hits**. There is no doc sentence that says "use an Actor when X, use a
   LiveDataClient when Y". Marked **unanswerable from the prose docs.**

2. **The docs explicitly sanction BOTH, in one sentence, with no criterion.**
   `docs/concepts/data/index.md:1473-1474`:
   > "An adapter can construct this type and send it to the `DataEngine` for subscribers. An actor
   > or strategy can publish it directly:"
   followed by the `self.publish_data(DataType(MyDataPoint, metadata=...), MyDataPoint(...))`
   example. That is the entirety of the official guidance.

3. **The only stated criterion in the whole 1.231.0 distribution is a docstring, not prose.**
   `adapters/_template/data.py:67`, class `TemplateLiveDataClient`:
   > "A live data client generally handles **non-market or custom data feeds and requests**."

   and `adapters/_template/data.py:114`, class `TemplateLiveMarketDataClient`:
   > "A live market data client generally handles **market data feeds and requests**."

   This is the sanctioned split: `LiveDataClient` = non-market/custom feeds (weather observations
   qualify); `LiveMarketDataClient` = market data (requires an `InstrumentProvider`, see fact 5).

4. **Structural gate — `LiveMarketDataClient` is disqualified for instrument-less data.**
   `live/data_client.py:349-362`: `LiveMarketDataClient.__init__` takes a **required**
   `instrument_provider: InstrumentProvider` positional and hard-validates it:
   `PyCondition.type(instrument_provider, InstrumentProvider, "instrument_provider")`
   (`live/data_client.py:361`). Weather data has no instruments. `LiveDataClient.__init__`
   (`live/data_client.py:109-125`) has **no** `instrument_provider` parameter.

5. **`client_id` routing works for instrument-less custom data.**
   `docs/concepts/data/index.md:1506`:
   > "`client_id` routes the subscription to a specific client."
   with `self.subscribe_data(data_type=DataType(MyDataPoint, metadata=...), client_id=ClientId("MY_ADAPTER"))`.
   This is the mechanism by which a `LiveDataClient` with no venue receives subscriptions.

6. **`Actor` is documented as a data *consumer* + publisher, never as an ingestion transport.**
   `docs/concepts/actors.md:3` — "An `Actor` receives data, handles events, and manages state."
   Its documented capability list (`actors.md:7-13`) is subscription/request, event handling,
   timers, cache/portfolio access, logging. Nothing about owning a connection lifecycle. There is
   no `on_connect`/`on_disconnect` and no `is_connected` on `Actor`; the lifecycle state machine
   (`actors.md:70-96`) is component-level, not transport-level.

7. **Blocking I/O in actor handlers is explicitly warned against.**
   `docs/how_to/configure_live_trading.md:29-34`:
   > "User code on the event loop thread (strategy callbacks, actor handlers, `on_event` methods)
   > must return quickly. ... Blocking operations like model inference, heavy calculations, or
   > **synchronous I/O** cause missed fills, stale data, and delayed order submissions. Offload
   > long-running work to an executor or a separate thread/process."
   An Actor doing polled HTTP must therefore use the clock timer + an awaited/offloaded fetch;
   it gets no framework help with that. `LiveDataClient` gives it `create_task()` for free
   (`live/data_client.py:150-196`).

### Q2 — Required vs optional coroutines on `LiveDataClient` (1.231.0)

8. **Authoritative table, `adapters/_template/data.py:69-79` (verbatim from the docstring):**

   | Method         | Requirement |
   | -------------- | ----------- |
   | `_connect`     | required    |
   | `_disconnect`  | required    |
   | `_subscribe`   | optional    |
   | `_unsubscribe` | optional    |
   | `_request`     | optional    |

   That is the **complete** `LiveDataClient` surface — five coroutines, no more.
   (`LiveMarketDataClient` has ~40; see `adapters/_template/data.py:107-160`.)

9. **Exact 1.231.0 signatures** (`live/data_client.py:282-305`):
   ```python
   async def _connect(self) -> None: ...
   async def _disconnect(self) -> None: ...
   async def _subscribe(self, command: SubscribeData) -> None: ...
   async def _unsubscribe(self, command: UnsubscribeBars) -> None: ...   # NOTE: annotation bug, see Traps
   async def _request(self, request: RequestData) -> None: ...
   ```
   All five take a **message object**, not loose primitives. The base implementations raise
   `NotImplementedError("implement the `_<name>` coroutine")`.

10. **Documented behavior for an unimplemented optional method — it does NOT raise to the caller
    and does NOT stop the node.** The public entry points wrap the coroutine in a task:
    `subscribe()` → `create_task(self._subscribe(command), ...)` (`live/data_client.py:252-259`);
    `unsubscribe()` → `live/data_client.py:261-270`; `request()` → `live/data_client.py:272-280`.
    The `NotImplementedError` surfaces in the task-done callback `_on_task_completed`
    (`live/data_client.py:197-222`) and is **logged only**:
    ```python
    if e:
        self._log.exception(f"Error on '{task.get_name()}'", e)
    ```
    Net effect: an unimplemented optional coroutine is a silent (log-level) failure.

11. **Corollary — `_connect` failure leaves the client permanently unconnected, silently.**
    `connect()` (`live/data_client.py:224-234`) passes
    `actions=lambda: self._set_connected(True)`. `_on_task_completed` only invokes `actions` on
    the no-exception branch (`live/data_client.py:211-222`). So a raising `_connect` never flips
    `is_connected`. `DataEngine.check_connected()` (`data/engine.pyx:325-339`) then returns False
    forever; `TradingNode` times out after `timeout_connection` (default 60.0s,
    `docs/how_to/configure_live_trading.md:72`).

### Q3 — Factory + `TradingNode` wiring

12. **`LiveDataClientFactory.create` exact 1.231.0 signature** (`live/factories.py:31-40`),
    verbatim:
    ```python
    class LiveDataClientFactory:
        @staticmethod
        def create(
            loop: asyncio.AbstractEventLoop,
            name: str,
            config: LiveDataClientConfig,
            msgbus: MessageBus,
            cache: Cache,
            clock: LiveClock,
        ) -> LiveDataClient:
    ```
    Base raises `NotImplementedError("method `create` must be implemented in the subclass")`
    (`live/factories.py:63-65`). Note the docstring's `config : dict[str, object]`
    (`live/factories.py:47`) contradicts the annotation — the annotation is correct.

13. **Registration takes `(name, factory_class)` — two arguments, and the CLASS not the method.**
    `live/node.py:230`:
    ```python
    def add_data_client_factory(self, name: str, factory: type[LiveDataClientFactory]) -> None:
    ```
    Docstring: "factory : type[LiveDataClientFactory] — The factory class to add." Raises
    `KeyError` if `name` already added (`live/node.py:245-246`).
    Doc examples confirm the shape, e.g. `docs/integrations/databento.md:990`:
    `node.add_data_client_factory(DATABENTO, DatabentoLiveDataClientFactory)`.

14. **`name` must match the `data_clients` dict key.** `live/config.py:312`:
    `data_clients: dict[str, Any] = {}` on `TradingNodeConfig` (`live/config.py:284`).
    `docs/how_to/configure_live_trading.md:56-63` shows `data_clients={"BINANCE": BinanceDataClientConfig()}`
    paired with `add_data_client_factory("BINANCE", ...)`. The key becomes the `ClientId`.

15. **Reference implementation of a real factory:** `adapters/polymarket/factories.py:132-192`
    (`PolymarketLiveDataClientFactory.create`) — builds the HTTP client and provider inside
    `create`, then passes `loop=`, `msgbus=`, `cache=`, `clock=`, `config=`, `name=` to the client.

### Q4 — Reconnection / re-subscription responsibilities (precise)

16. **The engine does nothing.** `LiveDataEngine` (`live/data_engine.py`) has `connect()`
    (`live/data_engine.py:126`) and `disconnect()` (`live/data_engine.py:144`) which each iterate
    clients **once**. There is no reconnect loop, no watchdog, no re-issue of `SubscribeData`.
    Grep for `reconnect|resubscribe` across `live/*.py` + `data/engine.pyx` yields **zero** hits.
    The engine's only connection awareness is the two read-only polls
    `check_connected()` / `check_disconnected()` (`data/engine.pyx:325-356`), which merely read
    `client.is_connected`.

17. **`is_connected` is adapter-driven only.** `data/client.pyx:124`
    `cpdef void _set_connected(self, bint value=True)` — docstring: "Setter for Python
    implementations to change the readonly property." Nothing in the framework flips it except the
    client's own `connect()`/`disconnect()` paths (`live/data_client.py:231, 245, 539, 553`).

18. **The framework DOES provide automatic *socket* reconnection — but only for
    `nautilus_pyo3.WebSocketClient`, not for HTTP.** `core/nautilus_pyo3.pyi:5530-5545`:
    ```python
    class WebSocketConfig:
        def __init__(
            self,
            url: str,
            headers: list[tuple[str, str]],
            heartbeat: int | None = None,
            heartbeat_msg: str | None = None,
            reconnect_timeout_ms: int | None = 10_000,
            reconnect_delay_initial_ms: int | None = 2_000,
            reconnect_delay_max_ms: int | None = 30_000,
            reconnect_backoff_factor: float | None = 1.5,
            reconnect_jitter_ms: int | None = 100,
            reconnect_max_attempts: int | None = None,
            idle_timeout_ms: int | None = None,
            proxy_url: str | None = None,
        ) -> None: ...
    ```
    and `core/nautilus_pyo3.pyi:5547-5558`:
    ```python
    class WebSocketClient:
        @classmethod
        def connect(cls, loop_, config: WebSocketConfig, handler,
                    ping_handler=None, post_reconnection: Callable[..., None] | None = None,
                    keyed_quotas=[], default_quota=None) -> Awaitable[WebSocketClient]: ...
    ```
    So: backoff, jitter, max-attempts, and idle-timeout detection are **provided**; the adapter
    supplies the `post_reconnection` callback body.

19. **Re-subscription semantics are 100% adapter-authored.** `docs/developer_guide/adapters.md:757-763`:
    > "Reconnection must restore protocol state, not only the socket: Recreate or replace command
    > paths before reporting the client active. Reauthenticate private sessions. **Restore
    > subscription intent** and required instrument context. Reset sequence, snapshot, or gap
    > state when the venue requires a fresh bootstrap."

    and `docs/developer_guide/adapters.md:729-735` (the reconnect ordering):
    > "1. Invalidate connection and authentication state. 2. Re-establish the transport.
    > 3. Authenticate when required. 4. **Replay active and pending subscribe intent.**
    > 5. Confirm subscriptions from explicit acknowledgements or authoritative data.
    > 6. Notify downstream consumers when they must reset protocol state."
    > "Do not replay pending unsubscriptions."

20. **Both reconnect strategies are explicitly legitimate.** `docs/developer_guide/adapters.md:634-636`:
    > "Some adapters use stream mode and perform reconnection in the adapter. Others use the
    > network client's handler mode and automatic reconnection. **Both are legitimate.**"

21. **Bottom line for a polling HTTP client (Breezy's case):** none of §18-20 applies. There is no
    persistent socket, so there is nothing to reconnect. The correct 1.231.0 mechanism is a
    self-rescheduling poll task created via `self.create_task(...)`
    (`live/data_client.py:150-196`) wrapped in a `RetryManager` (Q5) — exactly the shape of
    `PolymarketDataClient._update_instruments` (`adapters/polymarket/data.py:189-192`). No
    watchdog, no `handler_reconnect`, no idle-timeout channel logic is required.

### Q5 — `live/retry.py` `RetryManager`

22. **Purpose (docstring, `live/retry.py:65-66`):** "Provides retry state management for an HTTP
    request. This class is generic over `T`, where `T` is the return type of the function passed
    to the `run` method."

23. **Configuration surface** — `RetryManager.__init__` (`live/retry.py:90-101`), all
    constructor-only (no config class, no env var):

    | Param | Type | Meaning |
    |---|---|---|
    | `max_retries` | `int` | Max retries before failure. Falsy (`0`) disables retry entirely (`live/retry.py:170`). |
    | `delay_initial_ms` | `int` | First-attempt delay; also the **lower bound of the jitter window**. |
    | `delay_max_ms` | `int` | Ceiling for exponential growth. |
    | `backoff_factor` | `int` | Exponential factor. |
    | `logger` | `Logger` | Required. |
    | `exc_types` | `tuple[type[BaseException], ...]` | **Only these are retried**; anything else propagates out of `run`. |
    | `retry_check` | `Callable[[BaseException], bool] \| None` | Return `False` → do not retry. |
    | `error_logger` | `Callable[[str, BaseException \| None], None] \| None` | Overrides `logger.error`. |

24. **Backoff + jitter algorithm** (`live/retry.py:24-61`, module-level `get_exponential_backoff`,
    defaults `delay_initial_ms=500, delay_max_ms=2_000, backoff_factor=2, jitter=True`):
    ```python
    delay = min(delay_max_ms, delay_initial_ms * backoff_factor ** (num_attempts - 1))
    if jitter:
        return randint(delay_initial_ms, delay)
    return delay
    ```
    `RetryManager.run` always calls it with `jitter=True` (`live/retry.py:176-182`) — jitter is
    **not** configurable from `RetryManager`. Cites AWS "exponential backoff and jitter"
    (`live/retry.py:47-48`).

25. **Failure is non-raising.** `run()` returns `T | None` — `None` on retry exhaustion, on
    `retry_check` veto, and on cancellation (`live/retry.py:163-190`). Callers must check
    `manager.result` / `manager.message` / `manager.last_exception`. `asyncio.CancelledError` is
    swallowed into `_cancel()` and returns `None` (`live/retry.py:188-190`).

26. **`RetryManagerPool`** (`live/retry.py:227`) — an async-locked reuse pool;
    `acquire()` (`live/retry.py:296`) pops and `clear()`s a manager, `release()`
    (`live/retry.py:317`) returns it, `shutdown()` (`live/retry.py:281`) cancels all active
    managers. State is cleared on **acquire**, not release, deliberately: "state is cleared on
    acquisition to avoid potential race conditions" (`live/retry.py:334-335`).

27. **Public/sanctioned? — Mixed, lean "sanctioned but undocumented".**
    - `live/retry.py` is **not** exported in `api_reference/live.md` (that file autodocs only
      `data_client`, `data_engine`, `execution_client`, `execution_engine`, `risk_engine`, `node`,
      `node_builder` — `docs/api_reference/live.md:1-61`). No `retry` entry.
    - No leading underscore on the module or the class; both have full public numpydoc docstrings
      with a `Parameters` section — the package's convention for public API.
    - The equivalent Rust type **is** explicitly sanctioned in prose,
      `docs/developer_guide/adapters.md:590-592`:
      > "Use the shared [`RetryManager`](../../crates/network/src/retry.rs) when its cancellation
      > and backoff model fits. An adapter-specific classifier remains responsible for venue codes
      > and operation semantics."
    - **Verdict:** usable and intended for adapter authors, but carries no API-stability guarantee
      from the docs. Wrap it behind one Breezy-owned call site so a signature change is a
      one-file fix.

### Q6 — `nautilus_pyo3.HttpClient`

28. **Class docstring (verbatim, from `inspect.getdoc`):**
    > "An HTTP client that supports rate limiting and timeouts.
    > Built on `reqwest` for async I/O. Allows per-endpoint and default quotas through a rate
    > limiter.
    > This struct is designed to handle HTTP requests efficiently, providing support for rate
    > limiting, timeouts, and custom headers. The client is built on top of `reqwest` and can be
    > used for both synchronous and asynchronous HTTP requests."

29. **Constructor — verbatim from `core/nautilus_pyo3.pyi:5416-5425`**
    (runtime `__text_signature__` agrees: `(default_headers=Ellipsis, header_keys=Ellipsis,
    keyed_quotas=Ellipsis, default_quota=None, timeout_secs=None, proxy_url=None)`):
    ```python
    class HttpClient:
        def __init__(
            self,
            default_headers: dict[str, str] | None = None,
            header_keys: list[str] | None = None,
            keyed_quotas: list[tuple[str, Quota]] | None = None,
            default_quota: Quota | None = None,
            timeout_secs: int | None = None,
            proxy_url: str | None = None,
        ) -> None: ...
    ```

30. **Request methods — verbatim from `core/nautilus_pyo3.pyi:5426-5469`** (runtime
    `__text_signature__` agrees exactly):
    ```python
    async def request(self, method: HttpMethod, url: str, params: dict[str, Any] | None = None,
                      headers: dict[str, str] | None = None, body: bytes | None = None,
                      keys: list[str] | None = None, timeout_secs: int | None = None) -> HttpResponse: ...
    async def get(self, url: str, params=None, headers=None, keys=None, timeout_secs=None) -> HttpResponse: ...
    async def post(self, url: str, params=None, headers=None, body=None, keys=None, timeout_secs=None) -> HttpResponse: ...
    async def patch(self, url: str, params=None, headers=None, body=None, keys=None, timeout_secs=None) -> HttpResponse: ...
    async def delete(self, url: str, params=None, headers=None, keys=None, timeout_secs=None) -> HttpResponse: ...
    ```
    `HttpMethod` (`core/nautilus_pyo3.pyi:5471-5476`): `GET POST PUT DELETE PATCH`.
    `request.__doc__` adds: "If requesting `/foo/bar`, pass rate-limit keys `["foo/bar", "foo"]`."

31. **`HttpResponse`** exposes exactly three attributes: `status` (`int`), `body` (`bytes`),
    `headers` (`dict[str, str]`). Verified by live probe against `https://api.weather.gov/`:
    `status=200 (int)`, `body=<bytes> len 9495`, `headers=<dict>`.

32. **`header_keys` is a response-header ALLOW-LIST, not a request-header setting.** Empirically
    verified: `HttpClient()` → `r.headers == {}` on a 200 response;
    `HttpClient(header_keys=["content-type","server"])` → `r.headers ==
    {'content-type': 'text/html; charset=UTF-8', 'server': 'nginx/1.28.3'}`. **Any response header
    you do not name at construction is unreadable.** (This is not stated in any doc.)

33. **Module-level blocking helpers** (`nautilus_trader.core.nautilus_pyo3.network`):
    `http_get(url, params=None, headers=None, timeout_secs=None)`,
    `http_post(url, params=None, headers=None, body=None, timeout_secs=None)`,
    `http_patch(...)`, `http_delete(...)`,
    `http_download(url, filepath, params=None, headers=None, timeout_secs=None)`.
    All docstring: "Creates an `HttpClient` internally and **blocks** on the async operation using
    a dedicated runtime." `http_download` "Uses `reqwest::blocking::Client` to stream the response
    directly to disk, avoiding loading large files into memory." **These are blocking — do not
    call them from the event loop** (see fact 7).

34. **`Quota`** (`nautilus_pyo3`): constructors `rate_per_second(max_burst)`,
    `rate_per_minute(max_burst)`, `rate_per_hour(max_burst)`; each "Returns a `PyErr` if the max
    burst capacity is 0". Docstring documents burst semantics at length.

35. **Error types exported:** `HttpError`, `HttpTimeoutError`, `HttpClientBuildError`,
    `HttpInvalidProxyError` (all `Exception` subclasses; none carry structured docstrings).

### Q7 — Third-party HTTP libraries

36. **The docs say nothing. At all.** Grep for `httpx`, `aiohttp`, `urllib`, `requests library`
    across the entire `docs/reference/nautilus/v1.231.0/` tree returns **zero hits**. There is no
    mandate, no prohibition, no preference statement.

37. **`HttpClient` is presented as a *typical component*, never as mandatory.**
    `docs/concepts/adapters.md:5` — "An adapter **typically** comprises these components", with
    the table at `adapters.md:41` listing `HttpClient` → "REST API communication."
    The one prescriptive HTTP sentence in the developer guide is about **rate limiting**, not
    transport choice — `docs/developer_guide/adapters.md:597-599`:
    > "The shared [`HttpClient`](../../crates/network/src/http/client.rs) supports one or more
    > rate limiters. Scope limiter state to the venue quota, not to a convenient Rust object"
    — and that whole section is scoped to **Rust crate** adapters (`crates/adapters/<adapter>/`),
    not Python extensions.

38. **The only binding constraints the docs actually impose on outbound calls are transport-agnostic:**
    - Do not block the event loop — `docs/how_to/configure_live_trading.md:29-34` (fact 7).
    - Respect venue backoff / rate-limit signals; retry only classified transient failures on
      idempotent operations — `docs/developer_guide/adapters.md:584-589`.
    - Never log credentials — `docs/developer_guide/adapters.md:265-266` ("Never include credentials,
      signed payloads, or secret material in `Debug`, errors, or logs") and
      `docs/integrations/index.md:58-62` (TRACE logs may contain auth data).

### Q8 — Config & secrets convention

39. **Config base class:** `LiveDataClientConfig` (`live/config.py:222`):
    ```python
    class LiveDataClientConfig(NautilusConfig, frozen=True):
        handle_revised_bars: bool = False
        instrument_provider: InstrumentProviderConfig = InstrumentProviderConfig()
        routing: RoutingConfig = RoutingConfig()
    ```
    `NautilusConfig` (`common/config.py:241`) is
    `msgspec.Struct, kw_only=True, frozen=True, forbid_unknown_fields=True`.
    **`forbid_unknown_fields=True`** — a typo'd config key is a hard decode error, not a silent
    default. **`kw_only=True`** — all subclass fields must be passed by keyword.

40. **Subclassing convention (real adapters):**
    `class PolymarketDataClientConfig(LiveDataClientConfig, frozen=True)`
    (`adapters/polymarket/config.py:27`). The `frozen=True` is repeated as a **class keyword
    argument**, not a decorator.

41. **Env-key sourcing lives at the credential/factory boundary, NOT in the config object.**
    `adapters/env.py:19-23`:
    ```python
    def get_env_key(key: str) -> str:
        if key not in os.environ:
            raise RuntimeError(f"Environment variable '{key}' not set")
        else:
            return os.environ[key]
    ```
    plus `get_env_key_or(key, default)` (`adapters/env.py:26-30`).
    Every in-tree call site is a factory or a dedicated credentials module — never a config
    `__post_init__`:
    - `adapters/databento/factories.py:59` → `key=key or get_env_key("DATABENTO_API_KEY")`
    - `adapters/polymarket/common/credentials.py:22,26,30,34,38`
    - `adapters/binance/common/credentials.py:96,125`

42. **The docs mandate exactly this boundary.** `docs/developer_guide/adapters.md:263-266`:
    > "Resolve credentials at a credential, factory, or client construction boundary. Environment
    > fallback may be part of that boundary, and a presence check may inspect the environment.
    > **Do not spread environment lookup through request methods or Python wrappers.** Never
    > include credentials, signed payloads, or secret material in `Debug`, errors, or logs."

43. **Config field convention for a secret:** declare `str | None = None` with a docstring line
    "If ``None`` then will source the `X_ENV_NAME` environment variable"
    (`adapters/polymarket/config.py:37-55` uses this exact phrasing for `private_key`, `funder`,
    `api_key`, `api_secret`, `passphrase`), and resolve it in `Factory.create`.

---

## Documented patterns

Minimal 1.231.0-correct shape for a non-venue, poll-driven custom data client.

### Custom data type

```python
from nautilus_trader.core import Data
from nautilus_trader.model.custom import customdataclass


@customdataclass
class WeatherObservation(Data):
    station_id: str = ""
    temperature_c: float = 0.0
```
Do **not** hand-write `__init__` or `__repr__`: `model/custom.py:36-40` only injects them when
`cls.__init__ is object.__init__` / `cls.__repr__ is object.__repr__`. The injected
`__init__(self, ts_event=0, ts_init=0, *args2, **kwargs2)` (`model/custom.py:47-53`) delegates the
field args to the dataclass init it saved as `cls.fields_init`.

### Config

```python
from nautilus_trader.config import LiveDataClientConfig


class WeatherDataClientConfig(LiveDataClientConfig, frozen=True):
    stations: tuple[str, ...] = ()
    poll_interval_secs: float = 300.0
    base_url: str = "https://api.weather.gov"
    api_key: str | None = None  # If None, sourced from BREEZY_WEATHER_API_KEY in the factory
```

### Client

```python
import asyncio

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.data.messages import RequestData, SubscribeData, UnsubscribeData
from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.model import ClientId, DataType


class WeatherDataClient(LiveDataClient):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        config: WeatherDataClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=None,              # non-venue data source
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._poll_task: asyncio.Task | None = None

    # --- required ---
    async def _connect(self) -> None:
        self._poll_task = self.create_task(self._run_poll_loop(), log_msg="weather_poll")

    async def _disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    # --- optional ---
    async def _subscribe(self, command: SubscribeData) -> None:
        ...  # record intent from command.data_type

    async def _unsubscribe(self, command: UnsubscribeData) -> None:
        ...

    async def _request(self, request: RequestData) -> None:
        ...  # fetch history, then self._handle_data_response(...)

    async def _run_poll_loop(self) -> None:
        while True:
            ...  # await fetch; self._handle_data(WeatherObservation(...))
            await asyncio.sleep(self._config.poll_interval_secs)
```
`venue=None` is explicitly supported: `live/data_client.py:92-93` — "venue : Venue or ``None`` —
The client venue. If multi-venue then can be ``None``."

### Factory

```python
from nautilus_trader.adapters.env import get_env_key
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.model import ClientId


class WeatherLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: WeatherDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> WeatherDataClient:
        api_key = config.api_key or get_env_key("BREEZY_WEATHER_API_KEY")  # credential boundary
        return WeatherDataClient(
            loop=loop,
            client_id=ClientId(name),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
```

### Node wiring

```python
config = TradingNodeConfig(
    trader_id="BREEZY-001",
    data_clients={"WEATHER": WeatherDataClientConfig(stations=("KJFK",))},
)
node = TradingNode(config=config)
node.add_data_client_factory("WEATHER", WeatherLiveDataClientFactory)  # (name, CLASS)
node.build()
```

### Consumer side (actor/strategy)

```python
self.subscribe_data(
    data_type=DataType(WeatherObservation, metadata={"station_id": "KJFK"}),
    client_id=ClientId("WEATHER"),
)

def on_data(self, data: Data) -> None:
    if isinstance(data, WeatherObservation):
        ...
```

### Retry wrapper

> **NEVER APPLY THIS TO ORDER SUBMISSION ON A VENUE WITH NO CLIENT-SUPPLIED ORDER ID.**
> `RetryManagerPool` re-invokes the wrapped call on a classified-transient failure with **no
> idempotency key**, so an ambiguous timeout resubmits and **doubles the position**. The recipe
> below uses `max_retries=3` because it is a DATA-fetch example; copying it onto a submit path
> is a money-losing bug.
>
> Nautilus' own shipped Polymarket adapter agrees, and it is worth reading as the reference:
> it wraps batch submit at `adapters/polymarket/execution.py:1557-1567`, but defaults
> `max_retries: PositiveInt | None = None` (`adapters/polymarket/config.py:208`) and resolves it
> `config.max_retries or 0` (`execution.py:223`) — **retry is OFF by default on submit, and that
> is deliberate.** Its `_is_unknown_submit_result` / `_handle_unknown_batch_submit_result`
> (`:1571-1577`) exist precisely because the outcome is ambiguous rather than retryable.
>
> Rule: `max_retries=0` for submit. Retry only cancels and reads. In Breezy this is enforced by
> barrier **B8** (see `docs/plans/EXEC_SPINE_2026-09-01.md`), which bans `RetryManager`,
> `RetryManagerPool` and `retry_*` kwargs on the submit path by name.

```python
from nautilus_trader.live.retry import RetryManagerPool

self._retry_pool: RetryManagerPool = RetryManagerPool(
    pool_size=4,
    max_retries=3,
    delay_initial_ms=1_000,
    delay_max_ms=30_000,
    backoff_factor=2,
    logger=self._log,
    exc_types=(TimeoutError, OSError),   # ONLY these are retried
    retry_check=lambda e: True,
)

mgr = await self._retry_pool.acquire()
try:
    payload = await mgr.run("fetch_obs", [station_id], self._fetch, station_id)
    if payload is None:          # exhausted / vetoed / canceled — NOT an exception
        self._log.warning(f"weather fetch failed: {mgr.message}")
finally:
    await self._retry_pool.release(mgr)
```
Call `self._retry_pool.shutdown()` from `_disconnect` (`live/retry.py:281-291`).

---

## HttpClient capability matrix

| # | Control | Supported? | Evidence |
|---|---------|-----------|----------|
| a | **Redirect following / max redirects** | **NO (not controllable). Redirects ARE followed silently.** | No `redirect`/`max_redirects` parameter in the constructor (`core/nautilus_pyo3.pyi:5417-5425`) or in any request method (`:5426-5469`). Empirically: `HttpClient().get("https://httpbin.org/redirect/3")` → `status=200, len=280` (3 hops followed, final body returned). The string `redirect_policy` appears in the compiled `.so` (reqwest `ClientBuilder` internals), confirming reqwest's default policy is in force and is simply not projected to Python. reqwest default = follow up to 10 hops. **No way to disable, cap, or inspect the redirect chain.** |
| b | **TLS verification / pinned CA bundle** | **NO.** | No `verify`, `ca_bundle`, `root_cert`, `danger_accept_invalid_certs`, `identity`, or `tls_*` parameter anywhere in the constructor or request methods. The `.so` contains rustls strings including `"disabling rustls hostname verification only allowed with tls_certs_only()"`, i.e. the knob exists in Rust but is **not** exposed through PyO3. Verification is always on, against the compiled-in default trust store. **A pinned CA bundle is impossible via `HttpClient`.** |
| c | **Maximum response body size cap** | **NO.** | No `max_body_size` / `max_bytes` / `content_length_limit` parameter. `HttpResponse.body` is fully-materialized `bytes` (verified: `type(r.body) == bytes`, `len == 9495`) — the whole body is read into memory before Python sees it. There is no streaming/chunked response API on `HttpClient`. The only streaming path in the module is `http_download(url, filepath, ...)`, which streams **to disk** and is **blocking**, and also has no size cap parameter. **An unbounded/hostile response can OOM the process.** |
| d | **Per-host rate quotas** | **PARTIAL — per-KEY, not per-host.** | `keyed_quotas: list[tuple[str, Quota]]` and `default_quota: Quota \| None` on the constructor (`core/nautilus_pyo3.pyi:5421-5422`); `keys: list[str] \| None` on every request method (`:5433,5441,5450,5459,5467`). Keys are **caller-supplied arbitrary strings**, not derived from the URL host — `request.__doc__`: "If requesting `/foo/bar`, pass rate-limit keys `["foo/bar", "foo"]`." `Quota` supports `rate_per_second/minute/hour(max_burst)`. Per-host limiting works only if you pass the host as a key on every call. `default_quota` applies to all requests. Docs: `docs/developer_guide/adapters.md:597-606` ("Acquire all required quota before sending a request. Keep pagination and retry loops inside the same policy."). |
| e | **Request timeout** | **YES — two levels.** | Client-wide default: `timeout_secs: int \| None = None` on the constructor (`core/nautilus_pyo3.pyi:5423`). Per-request override: `timeout_secs: int \| None = None` on `request/get/post/patch/delete` (`:5434,5442,5451,5460,5468`). **Integer seconds only — sub-second timeouts are not expressible.** Violations surface as `HttpTimeoutError`. |
| — | *(bonus)* HTTP proxy | **YES.** | `proxy_url: str \| None = None` on the constructor (`core/nautilus_pyo3.pyi:5424`); `HttpInvalidProxyError` on a bad value. |
| — | *(bonus)* Response header access | **ALLOW-LIST ONLY.** | `header_keys: list[str] \| None` (`core/nautilus_pyo3.pyi:5420`). Verified: default → `r.headers == {}`; with `header_keys=["content-type","server"]` → both present. Undocumented anywhere in the docs tree. |

**Net:** `HttpClient` gives you timeout + rate limiting + proxy. It gives you **zero** transport
hardening controls (a, b, c) — the three that matter most when fetching from third-party public
infrastructure you do not operate.

---

## Docs vs code drift

1. **The vendored `v1.231.0` docs tree is Rust-first and describes surfaces that do not exist in
   the installed Python 1.231.0 package.** `docs/developer_guide/adapters.md` is written entirely
   against `crates/adapters/<adapter>/`, `#[async_trait(?Send)]` traits, `CacheView`, `DataEvent`,
   `bon::Builder`, the PyO3 registry, and `make py-stubs-v2`. It contains **no Python
   `LiveDataClient` guidance whatsoever** — grep for `LiveDataClient` in `concepts/`,
   `developer_guide/`, `how_to/`, `api_reference/` returns **zero hits**; the term only appears in
   `integrations/*.md` prose. Treat that developer guide as *principles* (evidence classes,
   reconnect ordering, retry policy, credential boundaries) and `adapters/_template/` +
   `adapters/polymarket/` as the *Python contract*.

2. **`docs/concepts/live.md` documents Rust `LiveNode`, not `TradingNode`.** `concepts/live.md:15-17`
   ("Rust `LiveNode::run()` prepares cached and venue state...") and the `metrics_snapshot()` /
   `LiveNodeConfig(shutdown_on_error=True)` sections. `grep -rn "class LiveNode"` across the
   installed package → **no match**. There is no Python `LiveNode` in 1.231.0. Python live trading
   is `nautilus_trader.live.node.TradingNode`. Ignore `concepts/live.md`'s Rust examples entirely.

3. **`docs/how_to/configure_live_trading.md` mixes Python and Rust in one page.** Its "Cache
   database configuration" and "MessageBus configuration" sections are Rust
   (`LiveNodeConfig`, `RedisCacheConfig`, `node.set_cache_database(...)`) and are inapplicable to
   `TradingNode`. The page itself flags this: "The Python v2 `LiveNode` does not yet expose direct
   cache-backing injection." The `TradingNodeConfig` / reconciliation / strategy-config tables on
   that page **are** accurate for Python (cross-checked against `live/config.py:81-201`).

4. **`docs/api_reference/live.md` and `docs/api_reference/config.md` carry no content.** Both are
   bare Sphinx `automodule` stubs. They cannot answer any signature question offline. Notably,
   `api_reference/live.md` does **not** list `nautilus_trader.live.retry` — the module is
   undocumented in the API reference despite being public-shaped.

5. **`LiveDataClientFactory.create` docstring contradicts its own annotation.**
   `live/factories.py:47` says `config : dict[str, object]`; the signature at
   `live/factories.py:35` says `config: LiveDataClientConfig`. The annotation is correct — real
   factories receive the typed config object (`adapters/polymarket/factories.py:137`).

6. **`LiveExecClientFactory` error message has a typo:** `"method `create' must be implemented"`
   — backtick/apostrophe mismatch (`live/factories.py:104`). Cosmetic; noted so nobody greps for
   the wrong string.

7. **`LiveDataClient._unsubscribe` has a wrong type annotation in 1.231.0:**
   `live/data_client.py:297` — `async def _unsubscribe(self, command: UnsubscribeBars) -> None`.
   The caller `unsubscribe()` (`live/data_client.py:261`) is typed `command: UnsubscribeData` and
   passes an `UnsubscribeData`. The template (`adapters/_template/data.py:97`) correctly uses
   `UnsubscribeData`. **Follow the template, not the base class annotation** — a strict mypy setup
   will fight you here.

8. **The brief's "2.x tells" are wrong for 1.231.0 — both are present in 1.231.0.**
   `DataActor` exists at `core/nautilus_pyo3.pyi:199`; `register_custom_data_class` is referenced
   at `model/custom.py:178-179,217` and documented at `docs/concepts/data/index.md:1707-1719`.
   Neither is a reliable version discriminator. A **reliable** 1.231.0 Python tell is the presence
   of `nautilus_trader/live/node.py::TradingNode` and the **absence** of a Python `LiveNode`.

9. **`docs/integrations/index.md` lists integrations whose adapter packages are not installed:**
   the table names `Coinbase`, `Blockchain`, `Derive`, `Lighter`; `adapters/` contains
   `architect_ax betfair binance bitmex bybit databento deribit dydx hyperliquid
   interactive_brokers interactive_brokers_pyo3 kraken okx polymarket sandbox tardis` and
   `_template`. Links like `integrations/coinbase.md` / `lighter.md` are also absent from the
   vendored tree. Do not plan against those.

---

## Traps

1. **Subscription bookkeeping is recorded BEFORE the coroutine runs.** `subscribe()` calls
   `self._add_subscription(command.data_type)` and *then* `create_task(self._subscribe(...))`
   (`live/data_client.py:252-259`). If `_subscribe` raises (including the base
   `NotImplementedError`), the client still reports the subscription in
   `subscribed_custom_data()`. **`is_subscribed` is intent, never confirmation.** Same pattern on
   all ~15 `LiveMarketDataClient.subscribe_*` methods (e.g. `live/data_client.py:658-666`).

2. **Every async failure in a live data client is log-only.** `_on_task_completed`
   (`live/data_client.py:197-222`) catches everything and calls `self._log.exception(...)`. Nothing
   propagates to the engine, node, or strategy. A weather feed that silently dies produces
   *nothing but a log line*. Breezy must add its own staleness watchdog (e.g. a clock timer that
   asserts "last observation newer than N minutes") — the framework will not tell you.

3. **`_connect` that raises → `is_connected` stays `False` forever → node startup times out at
   `timeout_connection` (60s default).** `connect()` passes `_set_connected(True)` as `actions`,
   which only runs on the success branch (`live/data_client.py:224-234` + `:211-222`).

4. **`disconnect()` bypasses `create_task`.** `live/data_client.py:236-250` uses
   `self._loop.create_task(_disconnect_with_cleanup())` directly — **no done-callback, no error
   logging**. An exception in `_disconnect` becomes a bare "Task exception was never retrieved"
   asyncio warning. Wrap your own `_disconnect` body in try/except.

5. **`RetryManager.run()` returns `None` on failure — it does not raise.** Checking only the
   return value conflates "success with a `None` payload" and "retry exhausted". Always consult
   `manager.result` (`live/retry.py:161,168-173`).

6. **`RetryManager` only retries exceptions in `exc_types`.** Anything else propagates out of
   `run()` (`live/retry.py:167`). `HttpTimeoutError` and `HttpError` are distinct classes — list
   both, or nothing will retry.

7. **`RetryManager` jitter has a floor, not a spread around zero.**
   `randint(delay_initial_ms, delay)` (`live/retry.py:59`) — the minimum wait is always
   `delay_initial_ms`. Setting `delay_initial_ms=5_000` means *every* retry waits ≥5s. Jitter
   cannot be disabled from `RetryManager` (hardcoded `jitter=True` at `live/retry.py:181`).

8. **`max_retries=0` disables retry entirely** — `not self.max_retries` short-circuits
   (`live/retry.py:170`). It does not mean "unlimited".

9. **`HttpClient` response headers are invisible unless allow-listed.** Fact 32. If you need
   `Retry-After`, `X-RateLimit-Remaining`, `Last-Modified`, or `ETag` (all standard on
   `api.weather.gov`), you must name them in `header_keys` at construction — otherwise
   `r.headers` is `{}` and you will silently ignore the venue's own backoff signals, contradicting
   `docs/developer_guide/adapters.md:586` ("Respect venue backoff and rate-limit signals").

10. **`HttpClient` timeouts are integer seconds.** No sub-second timeout is expressible
    (`timeout_secs: int | None`).

11. **`http_get` / `http_post` / `http_download` are BLOCKING.** Their docstrings say they create
    a client and "block on the async operation using a dedicated runtime". Calling one from a
    strategy/actor/data-client coroutine stalls the entire event loop — the exact failure
    `docs/how_to/configure_live_trading.md:29-34` warns about.

12. **`HttpClient` follows redirects silently with no cap you control and no way to see the final
    URL.** `HttpResponse` has no `url` attribute. A redirected fetch to an attacker-controlled or
    mis-configured host is indistinguishable from a direct one.

13. **`HttpClient` has no response-size cap and materializes the full body.** A malformed or
    hostile upstream can OOM the trading process. Any third-party fetch must be size-bounded by
    the caller — which `HttpClient` cannot do.

14. **`NautilusConfig` sets `forbid_unknown_fields=True`** (`common/config.py:241`). A renamed or
    misspelled config key is a **decode error at node build**, not a silently-defaulted field.
    Good for safety; will bite on config refactors.

15. **`NautilusConfig` is `kw_only=True` and `frozen=True`.** No positional construction, no
    mutation. Do not attempt `object.__setattr__` tricks in `__post_init__` to inject secrets —
    resolve them in the factory instead (fact 42).

16. **`LiveMarketDataClient.subscribe_bars` hard-validates external aggregation** via
    `PyCondition.is_true(command.bar_type.is_externally_aggregated(), "aggregation_source is not EXTERNAL")`
    (`live/data_client.py:654-657`) — in the **public** `subscribe_bars`, before the task is
    created. Irrelevant to `LiveDataClient` (no bar methods), listed because the skill file cites
    it incorrectly.

17. **`get_env_key` raises `RuntimeError`, not `KeyError`** (`adapters/env.py:20-21`) — with the
    variable name in the message. Catch `RuntimeError` if you want a friendlier startup error.

18. **One `TradingNode` per process.** `docs/how_to/configure_live_trading.md:21-23`:
    "Running multiple `TradingNode` instances concurrently in the same process is not supported
    due to global singleton state." Relevant if Breezy ever wants Polymarket + Kalshi in parallel:
    that is two processes, or one node with two clients.

19. **`add_data_client_factory` raises `KeyError` on a duplicate name** (`live/node.py:245-246`).

20. **Backtests order the stream by `ts_init`, not `ts_event`** —
    `docs/concepts/data/index.md:1470` (":::info Backtests order the data stream by `ts_init`."):
    weather observations whose `ts_event` (observation time) differs materially from `ts_init`
    (fetch time) will replay in *fetch* order. Set `ts_init` deliberately.
