# Strategy Quickstart — Write a Breezy Trading Strategy

**Target reader:** An engineer with no prior Breezy experience who wants to write a Nautilus `Strategy` and backtest it.

**Status:** Active reference. Last updated 2026-08-27.

This guide takes you from zero to a working backtest in ~30 minutes. Follow it linearly; every step has been validated against the live codebase.

---

## 1. What you're building

A Breezy strategy is a subclass of Nautilus Trader's native `Strategy`, extended to consume weather data (`NwsClimateDay` records from NOAA). You write the trading logic, the backtest harness handles the simulation and feed mechanics. No Breezy wrapper, no lifecycle abstraction — just Nautilus' own extension point.

**You have two reference strategies:**

- **`src/breezy/strategy/harness_probe.py`** — Minimal. Counts what arrives, submits one market order, logs decisions. Copy this if you want the smallest possible working shape.
- **`src/breezy/strategy/forecast_edge.py`** — Ordinary. Subscribes to weather and L2 book, maps tmax to a model probability, buys when edge clears a threshold. Copy this if you're building a real trading model.

---

## 2. Copy and rename a reference strategy

```bash
cp src/breezy/strategy/forecast_edge.py src/breezy/strategy/my_strategy.py
```

Edit the file:
- Rename the config class: `ForecastHighEdgeBuyerConfig` → `MyStrategyConfig`
- Rename the strategy class: `ForecastHighEdgeBuyer` → `MyStrategy`
- Update docstrings and `__all__`

**No changes to `pyproject.toml` or any init file are required.** Strategies are loaded by direct import at the call site (see §5). If you find yourself editing `pyproject.toml` to register your strategy, that's a bug — report it.

---

## 3. Understand the four data streams

A strategy receives data through subscription callbacks:

### 3.1 Order Book Depth (Use this for bid-ask)

```python
def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
    best_ask = depth.asks[0].price if depth.asks else None
    # Now you know the current ask price for decision-making
```

**CRITICAL:** Ask state should come from `OrderBookDepth10`, not `QuoteTick`. Under L2 market profiles, the book depth drives execution, and a quote can arrive *after* a weather record — a strategy keying only on `on_quote_tick` may never trade. Subscribe to depth even if you only extract the best ask; you need the timestamp alignment.

```python
def on_start(self) -> None:
    instrument = self.cache.instrument(self.config.instrument_id)
    self.subscribe_order_book_depth(instrument.id)  # NOT optional
```

### 3.2 Quote Ticks (Optional: for data tracing)

```python
def on_quote_tick(self, tick: QuoteTick) -> None:
    # Useful for logging or light decision-making, but not for order submission
    self.log.info(f"Quote arrived: {tick.ask_price}")
```

### 3.3 Weather Records (Station-filtered, client-scoped)

```python
def on_data(self, data: Data) -> None:
    if type(data) is not NwsClimateDay:  # Type-exact, not isinstance
        return
    
    # CRITICAL: YOU MUST FILTER BY STATION
    # Weather is delivered to EVERY strategy in the run from EVERY city.
    # The subscription is CLIENT-scoped, not instrument-scoped.
    # Your instrument's city is never automatically correlated.
    if data.station != self.config.station:
        return  # Skip foreign records
    
    # Now act on this record
```

**Why is weather client-scoped?** One climate day settles many markets. The platform delivers all cities' records to all strategies with nothing marking which is foreign. A ladder that acts on the first record it sees will size a New York position off Chicago's temperature and log nothing. This is correct platform behaviour. You must filter.

### 3.4 Instrument Close (Settlement trigger)

```python
def on_instrument_close(self, update: InstrumentClose) -> None:
    # The harness uses this to settle positions at a known price.
    # You should not need to handle this; subscribe only if you need the callback.
```

---

## 4. Weather data: subscription and wrapping

### 4.1 In your strategy: subscribe by CLIENT ID

```python
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID

def on_start(self) -> None:
    # Use client_id, NOT instrument_id. See the reason in §3.3.
    self.subscribe_data(
        nws_climate_day_data_type(),
        client_id=NWS_BACKTEST_CLIENT_ID
    )
```

### 4.2 In your backtest harness: wrap weather data with `as_backtest_data()`

When you set up the backtest, weather records cannot go in the `market_data` list. They must be wrapped and passed as a separate `weather_data` parameter.

```python
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.persistence.catalog import read_climate_days

# Read raw weather records (unwrapped)
records = read_climate_days("path/to/catalog.db")

# Wrap them for the backtest
config = BreezyBacktestConfig(
    instruments=(my_instrument,),
    market_data=(quotes, depths, closes),
    weather_data=as_backtest_data(records),  # <-- Wrapped here
    settlement_prices={my_instrument.id: Price(1.0)},
    # ...
)
```

**Why the wrapper?** The `DataEngine` dispatches on type. A bare `NwsClimateDay` hits the terminal `else` case, logs "Cannot handle data", and drops silently. The `CustomData` envelope carries the record's `DataType` so the engine knows how to route it.

---

## 5. Configuration: reading fields and typing

Nautilus' compiled config base types all custom fields as `Any`. Under `strict = true` mypy, reading a config field requires a `cast()`.

```python
from typing import cast
from decimal import Decimal
from nautilus_trader.trading.config import StrategyConfig

class MyStrategyConfig(StrategyConfig, frozen=True):
    probability_if_hot: Decimal = Decimal("0.70")

class MyStrategy(Strategy):
    def _validate_probability(self) -> None:
        prob = cast("Decimal", self.config.probability_if_hot)
        if prob < 0 or prob > 1:
            raise ValueError(f"Invalid probability: {prob}")
```

**Import path (critical):** Always import `StrategyConfig` from `nautilus_trader.trading.config`, **NOT** from `nautilus_trader.trading.strategy`. The wrong import produces a confusing error: `Unexpected keyword argument "frozen" for "__init_subclass__" of "object"`.

---

## 6. Decimal literals: Ruff preference

Ruff rule FURB157 prefers `Decimal(0)` over `Decimal("0")`:

```python
_ZERO = Decimal(0)      # ✓ Preferred
_ONE = Decimal(1)       # ✓ Preferred
_ALMOST_ONE = Decimal("0.99")  # ✓ OK for non-integer values
```

---

## 7. Minimal end-to-end example

Here's a runnable example, tested against the real harness:

```python
from decimal import Decimal
from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID, as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest


class TempEagerConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    station: str
    buy_if_tmax_f: int = 80


class TempEager(Strategy):
    def __init__(self, config: TempEagerConfig) -> None:
        super().__init__(config)
        self.orders_submitted: int = 0
        self._last_ask: Price | None = None
        self._quantity: Quantity | None = None

    def on_start(self) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.stop()
            return
        self._quantity = instrument.make_qty(Decimal(10))
        self.subscribe_quote_ticks(instrument.id)
        self.subscribe_order_book_depth(instrument.id)
        self.subscribe_data(
            nws_climate_day_data_type(),
            client_id=NWS_BACKTEST_CLIENT_ID
        )

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        if depth.asks:
            self._last_ask = depth.asks[0].price

    def on_data(self, data) -> None:
        if type(data) is not NwsClimateDay:
            return
        if data.station != self.config.station:
            return
        # CRITICAL: Guard against None — missing highs are normal in real data
        if data.tmax_f is None:
            return
        if self.orders_submitted or self._last_ask is None:
            return
        # Optional: require final observations (preliminary readings arrive first)
        if not data.is_final:
            return
        if data.tmax_f >= self.config.buy_if_tmax_f:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=self._quantity,
            )
            self.orders_submitted += 1
            self.submit_order(order)


# To run a backtest with this strategy:
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

tape = synthetic_binary_tape()
strategy = TempEager(TempEagerConfig(
    instrument_id=tape.instrument.id,
    station="NYC",
))

config = BreezyBacktestConfig(
    instruments=(tape.instrument,),
    market_data=tape.all_data(),
    weather_data=as_backtest_data([
        make_climate_day(
            station="NYC",
            tmax_f=84,
            is_final=True,
            retrieved_at_ns=tape.weather_ts_ns,
        ),
    ]),
    settlement_prices={tape.instrument.id: 1.0},  # float, not Price
    starting_balances=(Money(1000, tape.instrument.quote_currency),),
)

engine = run_backtest(config, strategies=(strategy,))

# Verify the strategy actually traded
print(f"Strategy orders submitted: {strategy.orders_submitted}")
assert strategy.orders_submitted == 1, "Example strategy should have submitted one order"
```

**This example runs and submits an order.** Copy-paste into a file in your repo, import `make_climate_day` from `tests.unit.test_persistence_catalog`, and run it — it will complete successfully with the strategy trading once.

---

## 8. The four validation gates

Every gate is mandatory before committing. Run them in this order:

### 8.1 Pytest (unit and integration tests)

```bash
python -m pytest -q
```

Runs all tests except those marked `live`, `venue_live`, or `real_money`. Your strategy tests go in `tests/unit/` (fast, isolated) or `tests/integration/` (against the real harness).

**Type coverage note:** `tests/` is NOT wholesale typechecked (159 pre-existing strict errors across 38 files). Your integration test will not be typechecked. However, your strategy code in `src/breezy/strategy/` IS typechecked under strict mode — any type error in the strategy itself will fail `mypy`.

### 8.2 Ruff linter

```bash
python -m ruff check .
```

Checks linting rules. If violations appear and you want to auto-fix them, use `python -m ruff format .` — **note: this command rewrites files in place**. Check first, format second.

### 8.3 MyPy type checker (strict mode on src/breezy/strategy)

```bash
python -m mypy
```

Type-checks your strategy code under strict mode. If you read a config field, use `cast()` (see §5). If you use a type annotation, ensure it matches at runtime.

### 8.4 Import linter (architecture contract)

```bash
lint-imports
```

Enforces the layer contract defined in `pyproject.toml`. Your strategy is in the top layer and may import from `runtime`, `ingest`, `domain`, and `persistence`, but not vice versa. If you need something from a lower layer, the architecture contract blocks it — that's a signal to refactor.

---

## 9. Adding a strategy: what changes, what doesn't

**You MUST change:**
- Create `src/breezy/strategy/my_strategy.py` with your strategy class

**You MUST NOT change:**
- `pyproject.toml` — No registration, no module listing needed
- `src/breezy/strategy/__init__.py` — Deliberately empty; strategies are imported by direct name
- Config files in `docs/` or `scripts/` — Backtest configs live in your test file, not a shared location

**If you feel you must edit pyproject.toml or the __init__.py to add a strategy, that's a bug. Report it.**

---

## 10. Common traps

### Trap: Quote-only strategies never trade

A strategy that only subscribes to quotes and acts in `on_quote_tick` may never trade if weather arrives first. L2 execution keying happens on the book depth, not the quote.

**Fix:** Subscribe to `order_book_depth` and extract the best ask from `depth.asks[0]`.

### Trap: Foreign weather records arrive with no marker

A two-city run delivers both cities' weather to both strategies. A strategy that acts on the first record without checking `station` will trade off the wrong city.

**Fix:** Every `on_data` handler must check `if data.station != self.config.station: return`.

### Trap: Missing high temperature crashes the strategy

`NwsClimateDay.tmax_f` is `int | None` — a missing high is normal in real data, not exceptional. Comparing `None >= int` raises `TypeError` and stops the strategy.

**Fix:** Guard every read: `if data.tmax_f is None: return` before any arithmetic or comparison.

### Trap: Wrong StrategyConfig import

Importing `StrategyConfig` from `nautilus_trader.trading.strategy` instead of `.trading.config` produces: `Unexpected keyword argument "frozen"...`

**Fix:** Use `from nautilus_trader.trading.config import StrategyConfig`.

### Trap: Bare weather records reach the backtest harness

Calling `BacktestEngine.add_data(weather_records)` without wrapping silently drops them. The harness expects `weather_data=as_backtest_data(weather_records)`.

**Fix:** Always wrap: `weather_data=as_backtest_data(read_climate_days(...))`.

### Trap: Wrong settlement_prices type

`settlement_prices` accepts a dict with `float` values (e.g., `1.0`), not `Price` objects.

**Fix:** Use `settlement_prices={instrument_id: 1.0}` or `={instrument_id: 0.0}`, never `={instrument_id: Price(...)}`.

### Trap: Example imports not copied

The example in §7 lists all required imports at the top. If you copy only the class definitions and test code without the imports, you get `NameError` on `InstrumentId`, `OrderBookDepth10`, `Money`, and other types.

**Fix:** Copy the entire example's import block verbatim, or add them to your own imports before pasting the class code.

---

## 11. Next steps

1. **Copy a reference strategy** (forecast_edge for a real model, harness_probe for minimal).
2. **Write your trading logic** in `on_data` and `on_order_book_depth`.
3. **Test with synthetic data** (see `tests/support/synthetic_binary_tape.py`).
4. **Run the four gates** (pytest, ruff, mypy, lint-imports).
5. **Commit only `src/breezy/strategy/your_strategy.py`** and its test file — nothing else needs to change.

---

## 12. References

- **Strategy examples:** `src/breezy/strategy/harness_probe.py`, `src/breezy/strategy/forecast_edge.py`
- **Test shape:** `tests/integration/test_forecast_edge_backtest.py`
- **Backtest harness:** `src/breezy/runtime/backtest_harness.py` (BreezyBacktestConfig, run_backtest)
- **Weather wrapping:** `src/breezy/runtime/backtest_feed.py` (as_backtest_data, NWS_BACKTEST_CLIENT_ID)
- **Nautilus docs:** Built-in `on_quote_tick`, `on_order_book_depth`, `on_data`, `subscribe_data`, `order_factory.market`
- **Venue config:** `docs/specs/BACKTEST_VENUE_CONFIG.md` (settlement, fees, account types)

---

## Appendix: Why the harness raises `IDLE_STRATEGY`

If a strategy submits no orders at all, the harness raises `SilentRunError(SilentRunCondition.IDLE_STRATEGY)`. This catches:
- Weather subscriptions that matched no topic (e.g., wrong CLIENT ID)
- Instruments missing from the cache
- Decision conditions that were never true
- Bugs in station filtering

All of these are silent failures in Nautilus itself. The harness makes them loud. If your strategy genuinely should never trade, pass `allow_idle_strategies=True` to `run_backtest`.
