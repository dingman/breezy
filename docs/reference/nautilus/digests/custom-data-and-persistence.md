# Custom Data + Persistence + Serialization — NautilusTrader 1.231.0

<!-- Sources: docs/reference/nautilus/v1.231.0/ (git tag v1.231.0 docs tree) + installed source at
     .venv/lib/python3.13/site-packages/nautilus_trader/ (NAUTILUS_VERSION == 1.231.0, verified at runtime).
     Generated: 2026-08-22 | Repo commit: none (working tree has no HEAD yet) -->

**Scope:** how to define, register, serialize, persist, query, delete and consolidate a custom
`Data` type in nautilus-trader 1.231.0, and every place the shipped behaviour diverges from the
shipped documentation.

**Doc-path convention below:** `v1.231.0/…` = `/home/jon/breezy/docs/reference/nautilus/v1.231.0/…`
**Source-path convention below:** bare `module/file.py:NNN` =
`/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/module/file.py:NNN`

---

## 0. The two stacks (read this before anything else)

1.231.0 ships **two parallel custom-data systems**. Confusing them is the single largest source of
wrong conclusions on this project.

| | Cython stack | PyO3 / Rust stack |
|---|---|---|
| Base class | `nautilus_trader.core.data.Data` | plain Python class (no base) |
| Decorator | `@customdataclass` | `@customdataclass_pyo3()` |
| Registration | automatic inside the decorator (`register_serializable_type` + `register_arrow`) | explicit `register_custom_data_class(MyClass)` |
| `DataType` | `nautilus_trader.model.data.DataType(SomeClass, metadata)` — **class first** | `nautilus_trader.core.nautilus_pyo3.model.DataType("Name", metadata, identifier)` — **string first** |
| Catalog | `nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog` | `nautilus_trader.core.nautilus_pyo3.ParquetDataCatalog` |
| Write / read | `catalog.write_data([...])` / `catalog.query(data_cls=Cls, …)` | `catalog.write_custom_data([...])` / `catalog.query("Name", …)` |
| Actor base | `nautilus_trader.common.actor.Actor` | `nautilus_pyo3.DataActor` |
| On-disk path | `data/custom_<snake_case_name>/[<identifier>]/…` | `data/custom/<type_name>/<identifier…>/…` |

Both stacks exist **in 1.231.0**. `register_custom_data_class`, `DataActor`, and the string-first
`DataType` are **not** 2.x-only markers — they are the PyO3 half of 1.231.0 (verified at runtime:
`nautilus_pyo3.NAUTILUS_VERSION == "1.231.0"`, `hasattr(nautilus_pyo3, "register_custom_data_class")
is True`, `hasattr(nautilus_pyo3, "DataActor") is True`). The tag's own
`v1.231.0/concepts/custom_data.md` is written entirely about the PyO3 stack and says so explicitly
at `v1.231.0/concepts/custom_data.md:375-383` ("The Cython `@customdataclass` system is separate
from this architecture").

**Breezy uses the Cython stack** (`from nautilus_trader.core.data import Data`,
`nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog`, `BacktestDataConfig`,
`BacktestEngine`). Everything below is Cython-stack unless labelled PyO3.

---

## 1. Verified facts

### Defining a custom `Data` type

1. **Two authoring routes are documented as first-class, not one.**
   (a) A hand-written `Data` subclass with explicit `register_serializable_type(...)` +
   `register_arrow(...)`, documented at `v1.231.0/concepts/data/index.md:1531-1670` (the
   `GreeksData` walk-through: `__init__`, `ts_event`/`ts_init` properties, `to_dict`/`from_dict`,
   `to_bytes`/`from_bytes`, `to_catalog`/`from_catalog`, `schema()`, then
   `register_serializable_type(...)` at :1625 and `register_arrow(...)` at :1663).
   (b) The `@customdataclass` decorator, documented at `v1.231.0/concepts/data/index.md:1672-1695`
   as generating exactly those methods. `@customdataclass` is therefore a **convenience over (a)**,
   not the only sanctioned route.
   In-tree proof of (a): `adapters/betfair/data_types.py:151` (`class BetfairTicker(Data)`) with
   `register_serializable_type` at `:732` and `register_arrow` at `:738`.
   In-tree proof of (b): `model/greeks_data.py:28-38` (`@customdataclass class GreeksData(Data)`).

2. **`Data` is a Cython `cdef class` with two abstract properties and no state.**
   `core/data.pyx:20` (`cdef class Data`), `:29-39` `ts_event`, `:41-51` `ts_init` — both raise
   `NotImplementedError`. `v1.231.0/concepts/data/index.md:1414-1416`: "`Data` holds no state, so a
   subclass does not need to call `super().__init__()`." Store both timestamps in backing fields and
   expose properties (`v1.231.0/concepts/data/index.md:1466-1467`).

3. **`Data.fully_qualified_name()` uses a COLON separator, not a dot.**
   `core/data.pyx:67`: `return cls.__module__ + ':' + cls.__qualname__`. Verified:
   `WX.fully_qualified_name() == "__main__:WX"`.

4. **`@customdataclass` injects only what the class does not already define.** Each of `__init__`,
   `__repr__`, `ts_event`, `ts_init`, `to_dict`, `from_dict`, `to_bytes`, `from_bytes`, `to_arrow`,
   `from_arrow`, `_schema` is guarded by `if "<name>" not in cls.__dict__`
   (`model/custom.py:36-39, 72, 80, 88, 105, 124, 131, 139, 149, 157`). The injected `__init__` has
   signature `__init__(self, ts_event: int = 0, ts_init: int = 0, *args2, **kwargs2)`
   (`model/custom.py:48`) — **timestamps come first positionally**, remaining fields go to the
   dataclass-generated `fields_init`.

5. **Registration inside `@customdataclass` is unconditional and happens at decoration time**, i.e.
   at import: `register_serializable_type(cls, cls.to_dict, cls.from_dict)` then
   `register_arrow(cls, cls._schema, cls.to_arrow, cls.from_arrow)` (`model/custom.py:160-161`).

### Field types

6. **`@customdataclass` supports exactly 8 annotation names for the auto-generated Arrow schema**
   (`model/custom.py:245-254`): `InstrumentId`→`pa.string()`, `str`→`pa.string()`,
   `bool`→`pa.bool_()`, `float`→`pa.float64()`, `int`→`pa.int64()`, `bytes`→`pa.binary()`,
   `ndarray`→`pa.binary()`, `dict`→`pa.string()` (JSON-encoded with `sort_keys=True`,
   `model/custom.py:309-311`).

7. **Anything else raises `TypeError` at class-definition time** (`model/custom.py:260-265`).
   Verified: `datetime`, `list[float]`, and **`float | None`** all raise
   `TypeError: Unsupported custom data field type for '<Cls>.<attr>': … Supported types are:
   InstrumentId, str, bool, float, int, bytes, ndarray, dict`. Optional/union annotations are NOT
   supported — a nullable column must be annotated with the bare type.

8. **Documented escape hatch: define `_schema` and/or `to_dict`/`from_dict` in the class body.**
   Because of the `not in cls.__dict__` guards (fact 4), an unannotated `_schema = pa.schema(...)`
   class attribute suppresses `_arrow_schema_for_class` entirely and the `TypeError` never fires.
   The docs state this at `v1.231.0/concepts/data/index.md:1674-1675` ("Override a generated method
   only when the defaults do not fit the type"). Verified end-to-end with a `datetime` field
   round-tripping through Arrow via a hand-written `_schema` + `to_dict` + `from_dict`.

### Registration contracts

9. **`register_arrow(data_cls, schema, encoder=None, decoder=None, batch_encoder=None) -> None`**
   — `serialization/arrow/serializer.py:89-128`. It writes into four module-level dicts
   (`_ARROW_ENCODERS`, `_ARROW_BATCH_ENCODERS`, `_ARROW_DECODERS`, `_SCHEMAS`, declared at
   `:75-78`). **Calling it twice for the same class silently OVERWRITES** — there is no guard.
   Verified.

10. **`schema` is effectively REQUIRED despite the `pa.Schema | None` annotation.**
    `serialization/arrow/serializer.py:116` runs `PyCondition.type(schema, pa.Schema, "schema")`
    (not `type_or_none`), so `schema=None` raises `TypeError`. The `:104-105` docstring saying
    "schema : pa.Schema or None" is wrong.

11. **`register_serializable_type(cls, to_dict, from_dict)` RAISES `KeyError` on a second call for
    the same class NAME** — `serialization/base.pyx:304-340`, guard at `:335-336`
    (`Condition.not_in(cls.__name__, _OBJECT_TO_DICT_MAP, …)`). Verified:
    `KeyError: "'cls.__name__' W already contained in '_OBJECT_TO_DICT_MAP' collection"`.
    The key is `cls.__name__`, **not** the class object — so two distinct classes that share a bare
    name collide, and re-importing a module under a second path (or re-running a notebook cell)
    fails. Since `@customdataclass` calls it (fact 5), **applying `@customdataclass` to a
    same-named class twice in one process is a hard error.**

12. **Registration also makes the type externally publishable on the message bus** —
    `serialization/base.pyx:312-314` and `:340` (`_EXTERNAL_PUBLISHABLE_TYPES.add(cls)`); exclude via
    `MessageBusConfig.types_filter`.

### Catalog (Cython `ParquetDataCatalog`)

13. **API surface for custom data** (all on `persistence/catalog/parquet.py`):
    - write: `write_data(data, start=None, end=None, data_cls=None, identifier=None, **kwargs)` `:255`
      (`skip_disjoint_check=True` via kwargs, `:309`)
    - read: `query(data_cls, identifiers=None, start=None, end=None, where=None, files=None, **kwargs)` `:1648`;
      convenience `custom_data(cls, instrument_ids=None, as_nautilus=False, metadata=None, **kwargs)`
      on the base class, `persistence/catalog/base.py:202`
    - intervals: `get_intervals(data_cls, identifier=None)` `:2388`,
      `query_first_timestamp` `:2314`, `query_last_timestamp` `:2329`,
      `get_missing_intervals_for_request` `:2344`
    - delete: `delete_data_range(data_cls, identifier=None, start=None, end=None)` `:1383`;
      `delete_catalog_range(start=None, end=None)` `:1299`
    - consolidate: `consolidate_data(data_cls, identifier=None, start, end, ensure_contiguous_files=True, deduplicate=False)` `:656`;
      `consolidate_catalog(...)` `:601`;
      `consolidate_data_by_period(data_cls, identifier=None, period=pd.Timedelta(days=1), start, end, ensure_contiguous_files=True)` `:891`;
      `consolidate_catalog_by_period(...)` `:827`
    - rename: `reset_all_file_names()` `:484`, `reset_data_file_names(data_cls, identifier=None)` `:513`
    - listing: `list_data_types()` `:2483`, `list_generic_data_types()` (`base.py:249`, strips the
      `custom_` prefix)
    - streaming: `convert_stream_to_data(instance_id, data_cls, ...)` `:2604`
    Documented at `v1.231.0/concepts/data/index.md:781-798` (write), `:826-849` (read),
    `:1147-1267` (reset / consolidate / delete), `:1269-1304` (Feather streaming).

14. **On-disk layout for a custom type is `<catalog>/data/custom_<snake_case_class_name>/…`.**
    `persistence/funcs.py:36` (`CUSTOM_DATA_PREFIX = "custom_"`), `:39-53` `class_to_filename`,
    `persistence/catalog/parquet.py:2465-2478` `_make_path`. Verified: a `WeatherData` class lands at
    `data/custom_weather_data/`. The `data/custom/<type_name>/<identifier…>` layout described at
    `v1.231.0/concepts/custom_data.md:260-262` is the **PyO3** catalog's layout, not this one.

15. **Per-identifier partitioning is NOT automatic — it is attribute-driven.**
    `parquet.py:320-336` (`identifier_function`): `Instrument` → `obj.id.value`; else `bar_type`
    attribute → `str(obj.bar_type)`; else `instrument_id` attribute → `obj.instrument_id.value`;
    **else `(name, None)` → no subdirectory at all**. A custom type without `instrument_id` or
    `bar_type` writes every row into one flat directory. Verified.

16. **File naming is `{start_iso}_{end_iso}.parquet` with `:` and `.` replaced by `-`**
    (`parquet.py:2942-2952` `_timestamps_to_filename`), start/end defaulting to
    `data[0].ts_init` / `data[-1].ts_init` (`parquet.py:373-374`).
    Documented at `v1.231.0/concepts/data/index.md:800-819`.

17. **A write whose computed filename already exists is a SILENT NO-OP.**
    `parquet.py:378-380`:
    ```python
    if self.fs.exists(parquet_file):
        print(f"File {parquet_file} already exists, skipping write")
        return
    ```
    A bare `print` to stdout — no exception, no logger, no return value. Verified: re-writing the
    same 3 timestamps with different values left the original values on disk. Same pattern in the
    Feather→Parquet conversion path at `parquet.py:2684`. **This is not documented anywhere in
    `v1.231.0/`.**

18. **A write that OVERLAPS an existing interval (without producing an identical filename) raises
    `ValueError`.** `parquet.py:382-388`, guard `_are_intervals_disjoint` (`:2997`). Suppress with
    `skip_disjoint_check=True`. Documented at `v1.231.0/concepts/data/index.md:821-824`.
    Verified: writing `(2,4)` over an existing `(1,3)` raised
    `ValueError: Writing file … with interval (2, 4) would create non-disjoint intervals.`

19. **Interval bookkeeping reads FILENAMES ONLY, never file contents.**
    `parquet.py:2419` docstring: "This method only examines the filenames and does not inspect the
    actual content of the files"; implementation `_get_directory_intervals` `:2451-2463` +
    `_parse_filename_timestamps` `:2969`. Consequence: `write_data(..., start=, end=)` overrides
    write a filename that may not match the payload, and every later disjoint/consolidate/delete
    decision trusts that filename.

20. **Data must be non-decreasing in `ts_init` at write time or `ValueError`.**
    `parquet.py:398-413` `_objects_to_table`, message at `:408`. It also enforces
    `PyCondition.list_type(data, data_cls, "data")` — a mixed-type list is rejected.

21. **`query()` on a non-Nautilus class returns `CustomData` WRAPPERS, not your objects.**
    `parquet.py:1732-1744`: if `not is_nautilus_class(data_cls)` the results are re-wrapped as
    `CustomData(data_type=DataType(data_cls, metadata=metadata), data=d)`. Verified —
    `type(catalog.query(data_cls=WeatherData)[0]).__name__ == "CustomData"`; the payload is `.data`.
    `is_nautilus_class` is at `core/inspect.py:21-31`.

22. **Custom types always take the PyArrow backend, never the Rust backend.**
    `parquet.py:1698-1730`: the Rust path is reachable only for the eight built-ins listed at
    `:1701-1708` or `_is_rust_custom_data(data_cls)` (`:2086`, i.e. registered via
    `register_rust_custom_serializer`, `serialization/arrow/serializer.py:414`). Documented at
    `v1.231.0/concepts/data/index.md:1109-1117`. Practical effect: use `filter_expr=` (PyArrow
    expression) for custom data; `where=` (DataFusion SQL) is ignored on this path
    (`v1.231.0/concepts/data/index.md:1141-1145`).

23. **`filename_to_class` resolves a directory name back to a class by scanning `_ARROW_ENCODERS`**
    (`persistence/funcs.py:56-81`). Any catalog-wide operation that walks directories
    (`delete_catalog_range` → `_extract_data_cls_and_identifier_from_path` `:1357-1381`,
    `consolidate_catalog`) therefore **requires your module to be imported in that process**;
    otherwise `data_cls is None` and the directory is skipped without a message
    (`parquet.py:1332-1340`, guard at `:1336`).

24. **Deletes split partially-overlapping files rather than truncating them**
    (`parquet.py:1383-1408` docstring, `_prepare_delete_operations` `:1510`,
    `v1.231.0/concepts/data/index.md:1264-1267`); "Delete operations cannot be undone" and "Empty
    directories are not automatically removed after deletion" (`parquet.py:1341`).

25. **Consolidation is metadata-strict.** `_validate_table_metadata` (`parquet.py:780-817`) raises
    `ValueError` if any two files being combined differ in schema-metadata keys or values.
    `deduplicate=True` (`consolidate_data` `:663`, `consolidate_catalog` `:606`) dedupes via
    `table.group_by(all_columns).aggregate([])` (`parquet.py:819-825`) — a group-by, so **row order
    is not preserved**.

### Timestamps

26. **`ts_init` orders replay; `ts_event` does not.**
    `v1.231.0/concepts/data/index.md:485-488`: "Data is ordered by `ts_init` using a stable sort …
    This ordering gives backtests deterministic replay." Restated for custom data at
    `v1.231.0/concepts/data/index.md:1470-1472` ("Backtests order the data stream by `ts_init`").
    Corroborated in code: `ArrowSerializer.rust_defined_to_record_batch` sorts by `ts_init`
    (`serialization/arrow/serializer.py:148`), `_objects_to_table` validates `ts_init` monotonicity
    (`parquet.py:401-413`), `_query_pyarrow` filters `start`/`end` on the `ts_init` column
    (`parquet.py:2153,2156`), and file names are cut from `ts_init` (`parquet.py:373-374`).
    Semantics: `ts_event` = when the event occurred; `ts_init` = when Nautilus initialized the
    object (`v1.231.0/concepts/data/index.md:451-454`); for a custom event, `ts_event` is
    "Time defined by the custom event" (`:471`). `ts_init >= ts_event` is **not guaranteed** —
    clock skew is called out at `:498-499`.

### Configuration / string identity

27. **`BacktestDataConfig.data_cls` is typed `str` and resolved with a COLON split.**
    `backtest/config.py:241` (`data_cls: str`), `:256-269` (`data_type` property →
    `resolve_path(self.data_cls)`), `common/config.py:78-82`
    (`module, cls_str = path.rsplit(":", maxsplit=1)`). A dotted path raises
    `ValueError: not enough values to unpack (expected 2, got 1)` — verified.
    The correct string is exactly `Data.fully_qualified_name()`, i.e. `"pkg.module:ClassName"`
    (`test_kit/stubs/config.py:137` does exactly this).

28. **Passing the class object itself also works** and is what the docs show
    (`v1.231.0/concepts/data/index.md:1489-1494`): msgspec does not validate on construction, and
    the encoding hook at `common/config.py:149-151` converts any `type` carrying
    `fully_qualified_name` to that colon string when the config is serialized. Verified: a config
    built with `data_cls=WX` encodes to `"data_cls":"__main__:WX"`.

29. **Cython `DataType` takes the CLASS first.** `DataType(SomeClass, metadata=None)`. Verified:
    `DataType("WX", metadata={})` raises
    `TypeError: Argument 'type' has incorrect type (expected type, got str)`.
    The topic is derived from class name + metadata (`DataType(WX, {"station":"KJFK"}).topic ==
    "WX.station=KJFK"`). Docs: `v1.231.0/concepts/data/index.md:1477-1483` (publish),
    `:1499-1505` (subscribe, with `client_id`).

30. **`DataType` metadata is a routing/topic concern and is NOT persisted by the Cython catalog.**
    `_make_path` (`parquet.py:2465`) uses only `class_to_filename(data_cls)` + identifier; metadata
    never reaches the path or the Parquet schema. On read it is re-attached from the `metadata=`
    kwarg you pass to `query()` (`parquet.py:1733-1744`). (The PyO3 catalog *does* persist metadata
    into schema metadata — `v1.231.0/concepts/custom_data.md:253-258` — which is a stack
    difference, not a version difference.)

### Schema evolution

31. **There is NO supported migration story for a custom Python type.** The only migration tooling
    documented (`v1.231.0/concepts/data/index.md:1306-1407`) is the Rust `nautilus_persistence`
    `to_json` / `to_parquet` binaries, and they auto-detect data type **from the filename** and
    handle only `OrderBookDelta`, `QuoteTick`, `TradeTick`, `Bar`
    (`v1.231.0/concepts/data/index.md:1327-1332`). Custom types are out of scope. The stated
    "best practices" (`:1402-1407`) are back-up-and-verify advice, not a mechanism.

32. **Adding a field to a persisted custom type silently corrupts reads.** `_query_pyarrow`
    (`parquet.py:2140-2145`) builds `pds.dataset(file_list, filesystem=self.fs, schema=schema)`
    with `schema = None` for every class except `Equity`. The in-code comment at
    `parquet.py:2134-2139` states the failure explicitly: pyarrow "infers the schema from the first
    fragment only", so fragments written before a field existed **mask that field on newer
    fragments**. Nautilus special-cased exactly one class (`Equity`) to work around this
    (`parquet.py:2142-2143`); custom classes get no such treatment.
    Corollary: consolidating across a schema change raises `ValueError` from
    `_validate_table_metadata` (fact 25) rather than merging.
    **Practical migration for Breezy: read old → transform in Python → write to a NEW class name /
    new directory → delete the old directory. There is no in-place path.**

---

## 2. Documented patterns

### A. `@customdataclass` — the default for Breezy
`v1.231.0/concepts/data/index.md:1676-1695`, in-tree `model/greeks_data.py:28-38`.

```python
from nautilus_trader.core.data import Data
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.custom import customdataclass


@customdataclass                       # NO frozen=True — see Traps T1
class WeatherObservation(Data):
    instrument_id: InstrumentId = InstrumentId.from_str("KJFK.NWS")  # drives partitioning
    temperature_c: float = 0.0
    station: str = ""

obs = WeatherObservation(
    ts_event=1_700_000_000_000_000_000,   # positional slot 1
    ts_init=1_700_000_000_000_000_000,    # positional slot 2
    instrument_id=InstrumentId.from_str("KJFK.NWS"),
    temperature_c=21.5,
    station="KJFK",
)
```
Decoration performs both registrations (`model/custom.py:160-161`). Import the module exactly once,
in one place, before any catalog or backtest use.

### B. Hand-written `Data` subclass + explicit `register_arrow`
`v1.231.0/concepts/data/index.md:1531-1670`; in-tree `adapters/betfair/data_types.py:151-260, 732-743`.
Use this when a field type is outside the eight supported annotations, when you need
`pa.dictionary()` / nullable / non-default Arrow types, or when the Arrow schema needs
`metadata={"type": "..."}`.

```python
import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow
from nautilus_trader.serialization.arrow.serializer import make_dict_serializer
from nautilus_trader.serialization.arrow.serializer import make_dict_deserializer
from nautilus_trader.serialization.base import register_serializable_type


class WeatherObservation(Data):
    def __init__(self, instrument_id, ts_event, ts_init, temperature_c=None): ...
    @property
    def ts_event(self) -> int: return self._ts_event
    @property
    def ts_init(self) -> int: return self._ts_init
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, values: dict): ...
    @classmethod
    def schema(cls) -> pa.Schema:
        return pa.schema(
            {"instrument_id": pa.string(), "ts_event": pa.uint64(),
             "ts_init": pa.uint64(), "temperature_c": pa.float64()},
            metadata={"type": "WeatherObservation"},
        )


register_serializable_type(WeatherObservation, WeatherObservation.to_dict, WeatherObservation.from_dict)
register_arrow(
    data_cls=WeatherObservation,
    schema=WeatherObservation.schema(),
    encoder=make_dict_serializer(schema=WeatherObservation.schema()),
    decoder=make_dict_deserializer(WeatherObservation),
)
```

### C. Partial escape hatch — keep `@customdataclass`, override the schema
Relies on the `not in cls.__dict__` guards (`model/custom.py:88, 105, 157`). Verified working with a
`datetime` field.

```python
@customdataclass
class Forecast(Data):
    issued_at: datetime = None            # would normally raise TypeError
    temperature_c: float = 0.0

    _schema = pa.schema({                 # UNANNOTATED — suppresses _arrow_schema_for_class
        "issued_at": pa.string(), "temperature_c": pa.float64(),
        "type": pa.string(), "ts_event": pa.int64(), "ts_init": pa.int64(),
    })

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict): ...
```

### D. Publish / subscribe / receive
`v1.231.0/concepts/data/index.md:1477-1515, 1620-1639`.

```python
self.publish_data(DataType(WeatherObservation, metadata={"region": "NE"}), obs)
self.subscribe_data(
    data_type=DataType(WeatherObservation, metadata={"region": "NE"}),
    client_id=ClientId("BREEZY_WX"),
)

def on_data(self, data: Data) -> None:
    if isinstance(data, WeatherObservation):   # on_data receives ALL custom data
        ...
```

### E. Catalog write / query
`v1.231.0/concepts/data/index.md:781-798, 826-849, 1658-1670`.

```python
catalog = ParquetDataCatalog(CATALOG_PATH)
observations.sort(key=lambda x: x.ts_init)          # required, fact 20
catalog.write_data(observations)

wrapped = catalog.query(data_cls=WeatherObservation, start="2026-01-01", end="2026-02-01")
observations = [w.data for w in wrapped]            # query returns CustomData, fact 21
```

### F. Backtest config
`v1.231.0/concepts/data/index.md:942-953`, corrected per fact 27.

```python
BacktestDataConfig(
    catalog_path=str(catalog.path),
    data_cls=WeatherObservation.fully_qualified_name(),   # "breezy.weather:WeatherObservation"
    client_id="BREEZY_WX",
    metadata={"region": "NE"},
    start_time="2026-01-01",
    end_time="2026-02-01",
)
```

### G. Feather streaming from a backtest, then conversion
`v1.231.0/concepts/data/index.md:1269-1304`.

```python
streaming = StreamingConfig(catalog_path=catalog.path, include_types=[WeatherObservation], flush_interval_ms=1000)
engine_config = BacktestEngineConfig(streaming=streaming)
...
catalog.convert_stream_to_data(results[0].instance_id, WeatherObservation)
```

---

## 3. Docs vs code drift (1.231.0 docs vs 1.231.0 installed source)

| # | Doc claim | Installed source | Trust |
|---|---|---|---|
| D1 | `v1.231.0/concepts/data/index.md:947`: `data_cls="my_package.data.NewsEventData"` — **dotted** path | `common/config.py:79` splits on `":"`; a dotted path raises `ValueError: not enough values to unpack` (verified) | **Code.** Use `"my_package.data:NewsEventData"`. The doc example is broken as written. |
| D2 | `serialization/arrow/serializer.py:91,104-105` — `schema: pa.Schema \| None`, "schema : pa.Schema or None" | `:116` `PyCondition.type(schema, pa.Schema, "schema")` rejects `None` | **Code.** Schema is mandatory. |
| D3 | `v1.231.0/concepts/custom_data.md:260-262` — custom data path is `data/custom/<type_name>/<identifier…>` | Cython catalog writes `data/custom_<snake_name>/[<identifier>]` (`persistence/funcs.py:36,48-52`; `parquet.py:2469-2476`) — verified `data/custom_weather_data/` | **Both, different objects.** The doc describes the PyO3 catalog; the Cython catalog is separate. Not a contradiction once the two stacks are separated (§0). |
| D4 | `v1.231.0/concepts/data/index.md:821-824` documents the overlapping-write `ValueError` | `parquet.py:378-380` additionally short-circuits an **exact filename match** with a `print` and `return` | **Code — and the docs are silently incomplete.** Fact 17 / Trap T4. |
| D5 | `v1.231.0/concepts/data/index.md:1249-1262` shows `delete_data_range(data_cls=..., identifier=...)` as the general delete | `parquet.py:1386-1406` with `identifier=None` matches on the substring `f"/data/{data_cls_name}/"`, which never matches a flat (no-identifier) custom-data directory — verified total no-op | **Code.** Trap T5. |
| D6 | `v1.231.0/concepts/data/index.md:1409-1412` presents custom data as flowing through "backtesting and live systems, … message bus, … cache or catalog" without qualification | Custom classes are excluded from the Rust query backend (`parquet.py:1698-1711`), get no schema enforcement on read (`parquet.py:2140-2143`), and come back wrapped in `CustomData` (`parquet.py:1732-1744`) | **Code.** The claim is true directionally, but "first-class" over-sells it. |
| D7 | `v1.231.0/concepts/custom_data.md` (whole file) reads as *the* custom-data document | `:375-383` scopes itself to PyO3 only; the Cython story lives in `concepts/data/index.md:1409-1757` | **Both.** Read `concepts/data/index.md` for Breezy; `custom_data.md` is PyO3 architecture. |
| D8 | Project file `docs/reference/nautilus/README.md` "version trap" table lists `register_custom_data_class`, `DataActor`, `DataType("Name", …)` as 2.x-only tells | All three exist in installed 1.231.0 (verified at runtime) and `register_custom_data_class` appears in the v1.231.0 tag docs at `concepts/data/index.md:1707,1719` and `concepts/custom_data.md:32,167,179,205` | **Code.** Those symbols discriminate **PyO3 vs Cython**, not 2.x vs 1.231.0. The README's heuristic will produce false "this doc is 2.x" rejections. |

---

## 4. Traps — silently wrong results

**T1 — `@customdataclass(frozen=True)` produces a class you cannot instantiate.**
The decorator applies `dataclass(cls, frozen=True)` (`model/custom.py:42`) and then installs an
`__init__` that does `self._ts_event = ts_event` (`model/custom.py:51-52`). Verified:
`dataclasses.FrozenInstanceError: cannot assign to field '_ts_event'` on first construction. Fails
loudly at construction, silently at import — a module that only *defines* the class imports fine.

**T2 — a field literally named `type` loses its value on every round-trip.**
Generated `to_dict` overwrites it with the class name (`model/custom.py:97`,
`result["type"] = str(cls.__name__)`) and generated `from_dict` pops it (`model/custom.py:110`).
Verified: `type="ACTUAL_VALUE"` → `to_dict()["type"] == "Coll2"` → `from_dict` reconstructs with the
dataclass **default**. No error. `data_type` is also popped (`model/custom.py:111`). Never name a
field `type`, `data_type`, `ts_event`, or `ts_init`.

**T3 — `ndarray` is in the supported-type table but is broken in the generated serializer.**
`model/custom.py:252` maps `ndarray` → `pa.binary()`, but `_serialize_field_value`
(`model/custom.py:305-312`) only special-cases `dict`; the raw `np.ndarray` reaches pyarrow.
Verified: `pyarrow.lib.ArrowTypeError: Expected bytes, got a 'numpy.ndarray' object` at
`to_arrow()`/write time — i.e. it fails at persistence, not at class definition. Hand-write
`to_dict`/`from_dict` to `.tobytes()` / `np.frombuffer` (pattern C).

**T4 — re-writing an already-covered exact interval silently keeps the OLD data.**
`parquet.py:378-380`. Verified end-to-end. A corrected/re-fetched weather observation set spanning
the same `ts_init` range as an earlier write is **discarded**, and the only signal is a line on
stdout. Backfill/repair loops will appear to succeed while changing nothing.
*Mitigation:* `delete_data_range(...)` for the range first (subject to T5), or check
`get_intervals(data_cls, identifier)` before writing.

**T5 — `delete_data_range(data_cls=X)` and `delete_catalog_range()` are complete no-ops for a
custom type with no `instrument_id`/`bar_type`.**
`parquet.py:1386-1406`: the `identifier is None` branch requires the substring
`f"/data/{data_cls_name}/"` — a **trailing slash** — which a flat leaf directory
`…/data/custom_flat_data` never contains. `delete_catalog_range` routes through the same branch
(`parquet.py:1332-1340`) and is equally inert. Verified: rows untouched, no exception, no message.
The same call on an `instrument_id`-bearing type deleted correctly.
*Mitigation:* give every persisted Breezy custom type an `instrument_id` field (which also restores
per-identifier partitioning, fact 15), or pass `identifier=` explicitly, or delete files with `fs`.

**T6 — `register_serializable_type` collides on bare class NAME.**
`serialization/base.pyx:335-336`. Two `WeatherData` classes in different modules, or one module
imported twice under different paths (`breezy.weather` and `src.breezy.weather`), raise
`KeyError` at import. Conversely `register_arrow` overwrites silently
(`serialization/arrow/serializer.py:121-128`), so a name collision can leave the Arrow registry
pointing at one class and the msgspec registry at the other.

**T7 — an unimported custom class makes catalog-wide operations skip its data.**
`filename_to_class` scans `_ARROW_ENCODERS` (`persistence/funcs.py:73-75`); an unregistered class
returns `None`, and `delete_catalog_range` skips that directory under
`if data_cls is not None` (`parquet.py:1336`). No warning.

**T8 — adding a field to a persisted custom type silently drops it on read.**
`parquet.py:2140-2143` passes `schema=None` (`schema = None` at `:2140`, overridden only for `Equity` at `:2142-2143`) to `pds.dataset` for every class except `Equity`;
pyarrow infers from the first fragment only (in-code comment `parquet.py:2134-2139`). Old files
therefore mask the new column across the whole dataset. See fact 32 for the only viable migration.

**T9 — interval bookkeeping trusts filenames, not contents.**
`parquet.py:2419`. `write_data(..., start=, end=)` lets you name a file with a range that does not
match its rows; `consolidate_*`, `delete_*`, `query_last_timestamp`, and the disjoint check all then
reason off that lie. Never pass `start`/`end` overrides unless you are reconstructing a known range.

**T10 — `query()` returns `CustomData`, so `isinstance(result[0], WeatherObservation)` is False.**
`parquet.py:1732-1744`. Unwrap `.data`. Note this differs from `on_data()`, which delivers the
**unwrapped** object. Same code shape, two different result types.

**T11 — `deduplicate=True` reorders rows.**
`_deduplicate_table` (`parquet.py:819-825`) is a `group_by(...).aggregate([])`. Combined with the
`ts_init` monotonicity requirement at write time (fact 20), a deduplicated file can come back out of
order; the file is not re-sorted before `pq.write_table` (`parquet.py:769-774`).

**T12 — `float | None` / `Optional[float]` is a hard `TypeError`, not a nullable column.**
`model/custom.py:279-292` resolves the annotation name and finds no mapping. Annotate the bare type
and let the Arrow field be nullable by default.

---

## 5. Answers to the seven questions

1. **Both routes are officially documented.** A hand-written `Data` subclass with explicit
   `register_serializable_type` + `register_arrow` is presented as a full first-class pattern
   (`v1.231.0/concepts/data/index.md:1531-1670`) and used in-tree by the Betfair adapter
   (`adapters/betfair/data_types.py:151, 732, 738`); `@customdataclass` is documented as a
   generator of those same methods (`:1672-1695`). `@customdataclass` is **not** the only sanctioned
   route.
2. **8 field types** — `InstrumentId, str, bool, float, int, bytes, ndarray, dict`
   (`model/custom.py:245-254`). Anything else, including any union/Optional, raises `TypeError` at
   class-definition time (`:260-265`). Escape hatch: define `_schema` and/or
   `to_dict`/`from_dict` in the class body (`model/custom.py:88, 105, 157`), documented at
   `v1.231.0/concepts/data/index.md:1674-1675`. Caveat: `ndarray` is mapped but its generated
   serializer is broken (Trap T3).
3. **`register_arrow(data_cls, schema, encoder=None, decoder=None, batch_encoder=None)`**
   (`serialization/arrow/serializer.py:89`) — call once at import, after the class is defined;
   `schema` is de-facto required (`:116`); a second call **silently overwrites**.
   **`register_serializable_type(cls, to_dict, from_dict)`** (`serialization/base.pyx:304`) — a
   second call for the same `cls.__name__` raises **`KeyError`** (`:335-336`).
4. **API surface: fact 13.** Rules: overlapping intervals raise `ValueError` unless
   `skip_disjoint_check=True` (fact 18, documented `v1.231.0/concepts/data/index.md:821-824`);
   intervals come from filenames only (fact 19); **a write whose exact filename already exists is a
   silent no-op with a bare `print`** (`parquet.py:378-380`, fact 17 / Trap T4) — undocumented;
   delete splits partially-overlapping files (fact 24) but is a **no-op for identifier-less custom
   types** (Trap T5); consolidation aborts on metadata mismatch (fact 25).
5. **No supported migration story for custom types.** The only documented tooling
   (`v1.231.0/concepts/data/index.md:1306-1407`) is Rust `to_json`/`to_parquet`, filename-gated to
   four built-in types. Worse, adding a field silently drops it on read (Trap T8). Migration must be
   read → transform → write-under-a-new-class-name → delete-old.
6. **`ts_init` orders replay** (`v1.231.0/concepts/data/index.md:485-488` and `:1470-1472`, stable
   sort; DeFi data additionally tie-breaks on chain position). `ts_event` is the venue/event time and
   does not order anything. `ts_init >= ts_event` is not guaranteed (`:498-499`).
7. **`Data.fully_qualified_name()` returns `module:QualName` with a COLON**
   (`core/data.pyx:67`), and that exact string is what `BacktestDataConfig.data_cls` /
   `resolve_path` expect (`backtest/config.py:266-267`, `common/config.py:79`). Passing the class
   object works too and is encoded to that same colon form
   (`common/config.py:149-151`). Dotted paths raise `ValueError`.

---

## 6. What the docs do not answer

- Whether the exact-filename skip (fact 17) is intended behaviour or a bug; nothing in `v1.231.0/`
  mentions it, and there is no flag to force an overwrite.
- Any supported way to change a persisted custom type's Arrow schema in place.
- Whether `identifier=` on `write_data`/`delete_data_range` may be a value other than an
  instrument-ID/bar-type string for a custom type (nothing forbids it; nothing documents it).
- The relationship between `DataType.metadata` and catalog storage for the **Cython** catalog
  (empirically: none — fact 30 — but this is never stated).
- Any documented thread-safety or multi-writer story: `parquet.py:131-135` says only "The data
  catalog is not threadsafe."
