# WP-12.0 — L-1 null-hypothesis verdicts, verified against installed Nautilus 1.231.0

Date: 2026-09-19. Method: read the INSTALLED source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` (note: python3.13, not 3.12 —
the plan's path assumption was wrong; package/version match 1.231.0). Not read from
documentation, not from recalled API shape.

This record exists because the plan of record
(`docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md`, WP-12.0) requires these
four verdicts to be established BEFORE `forecast_catalog.py` is written. Three of the four
stand as written. One needs a correction, and the trap list needs two additions.

Founding law restated: Nautilus Trader is immutable. The null hypothesis is that Nautilus
already provides the capability. A verdict of GENUINELY ABSENT authorises a build; a false
"absent" is expensive, so each one below cites installed file:line.

---

## Verdict 1 — `(station, climate_day)` partitioning: NATIVE BUT INSUFFICIENT — **CONFIRMED**

`ParquetDataCatalog.write_data` dispatch, `persistence/catalog/parquet.py:320-336`
(`identifier_function`):

- `Instrument`      -> `(name, obj.id.value)`            (:329)
- has `bar_type`    -> `(name, str(obj.bar_type))`       (:331)
- has `instrument_id` -> `(name, obj.instrument_id.value)` (:333)
- else              -> `(name, None)`                    (:336)   <- custom Data with no identity

`_make_path` (`parquet.py:2465-2479`) confirms the flat fallback exactly:

    directory = f"{base_path}/data/{file_prefix}"
    if identifier is not None:
        directory += f"/{urisafe_identifier(identifier)}"

So a custom `Data` with no `instrument_id` / `bar_type` lands in ONE flat
`data/custom_<name>/` directory. Two weather stations are physically indistinguishable
at the file level.

`register_arrow` (`serialization/arrow/serializer.py:89-128`) contributes NOTHING to
partitioning — it registers schema/encoder/decoder only and carries no identifier concept.

**There is no third native option.** `BaseDataCatalog` (`persistence/catalog/base.py:76-86,
220-227`) threads a single opaque `identifier: str | None`; there is no `partition_keys`
and no Hive-style `pyarrow.dataset.write_dataset(partitioning=...)` anywhere in
`parquet.py` — writes are plain `pq.write_table(table, where=parquet_file, ...)` to one
computed path (`parquet.py:391-396`). `persistence/funcs.py:84-88` confirms the identifier
union is `InstrumentId | BarType | str`; no partition-tuple type exists.

**Chosen extension: ONE `ParquetDataCatalog` ROOT PER STATION.** It requires zero change to
the custom `Data` class and simply reconstructs `ParquetDataCatalog(path=...)`, which is how
the class is designed to be used (`parquet.py:143-178` — path is the sole catalog-identity
boundary). The alternative (populating `instrument_id`) demands an object with a `.value`
attribute (`obj.instrument_id.value`, :333) — i.e. a real `InstrumentId` — which would force
weather-station identity into the trading-instrument type system purely to gain one
directory level. Rejected on separation of concerns.

**Climate-day is a QUERY FILTER, confirmed.** Time is never a partition dimension in
`_make_path` / `identifier_function`; the only dispatch axes are class name and one
identifier string. Temporal partitioning is filename-range-based
(`_timestamps_to_filename`, `ts_init`), not a directory level. Day filtering must go
through `query()`'s `start`/`end`/`where` against `ts_event` / custom fields
(`parquet.py:1652-1657, 1675-1676`).

---

## Verdict 2 — live delivery of `ForecastPoint`: NATIVE AND SUFFICIENT — **CONFIRMED, with a correction**

`Actor.publish_data` (`common/actor.pyx:2813-2830`):
`self._msgbus.publish_c(topic=self._topic_cache.get_custom_data_topic(data_type), msg=data)`.

`Actor.subscribe_data` (`common/actor.pyx:1258-1313`) registers `self.handle_data` on
`get_custom_data_topic(data_type, instrument_id)` **unconditionally at :1289-1292**, before
the client_id/instrument_id check.

Topic matching (`common/data_topics.pyx:189-211`): with `instrument_id is None` the topic is
`data.{data_type.topic}` (:208), driven purely by `DataType` + metadata — matching
`publish_data`, which never passes an `instrument_id`. The actor-push channel therefore
works with no `InstrumentId` at all.

Repo precedent already in production:
- `src/breezy/ingest/nws_observation_actor.py:398`, `src/breezy/ingest/nws_actor.py:1465,1502`
  — `self.publish_data(...)`
- `src/breezy/strategy/forecast_edge.py:112` — `self.subscribe_data(nws_climate_day_data_type(),
  client_id=NWS_BACKTEST_CLIENT_ID)`, consuming `NwsClimateDay` in `on_data` (:129)

**CORRECTION to the plan.** `subscribe_data` logs
`error("client_id or instrument_id need to be specified")` and returns early
(`actor.pyx:1294-1297`) when BOTH are `None` — but the msgbus subscription was already made
one line earlier, so delivery still works and the failure is a spurious ERROR log rather
than a dead channel. The forecast actor MUST pass a `client_id`, mirroring the repo's own
precedent, or it will emit a misleading error on every boot.

**The "never `catalog.query` in a hot handler" rule is EVIDENCE-BACKED, not style.**
`ParquetDataCatalog.query` (`parquet.py:1648`) and everything beneath it (`_query_rust`,
`_query_pyarrow`, `backend_session`) are plain synchronous `def`s — no `async def`, no
`await`, no executor offload anywhere in `parquet.py`. A `catalog.query(...)` inside a
synchronous `on_data` / timer handler runs disk + DataFusion I/O directly on the calling
thread, which in live IS the asyncio event-loop thread, blocking all concurrent order and
data I/O for the duration. Nothing in the installed source guards or warns.

Hot path stays: **actor push -> in-memory `ForecastState`**. Catalog is durable archive and
backtest source only.

---

## Verdict 3 — champion/challenger registry + promotion engine: GENUINELY ABSENT — **CONFIRMED**

Case-insensitive search of the entire installed tree for champion / challenger / model
registry / promote / canary / ab-test returns zero hits outside Breezy's own code. Nothing
resembling a model-artefact registry or promotion engine exists in 1.231.0.

This is the one verdict with no installed counter-evidence at all. The out-of-process build
(WP-20, WP-26) is authorised. Reuse the `FamilyManifest` exact-set SHAPE, distinct schema.

---

## Verdict 4 — NBM client absent, native pieces present — **CONFIRMED; timer trap REFRAMED**

No `NBM` / `noaa.gov` / `weather.gov` reference anywhere in installed `nautilus_trader`.
Forecast HTTP client absence confirmed.

Framing correction worth keeping straight: `HttpTransport` is **Breezy's own** class
(`src/breezy/ingest/http.py:522`), already extended by `NwsObservationTransport` /
`ProbeTransport` / `PacedIemTransport`. The Nautilus-native pieces are Actor + Actor timers
(`Clock.set_time_alert` / `set_timer` family, `common/component.pyx:257-513, 884-984`).
Precedent for the whole shape: `src/breezy/ingest/nws_observation_actor.py:109`.

### The timer trap is real, but it is NOT the silent swallow the plan implies

- **Backtest:** `backend/engine.pyx:1822` invokes the user timer callback as bare
  `callback(event)` inside `_advance_time` with **no try/except**. The surrounding `run()`
  loop catches only `AccountError` (`engine.pyx:1742`). Any other exception propagates fully
  uncaught and crashes the entire run. That is LOUD, not silent — but it is still a real
  gap: every other `on_*` handler in `actor.pyx` (e.g. `handle_data`, :4714-4721) carries the
  standard `try / except Exception / log.exception / raise` wrapper. Timer callbacks get none.
- **Live:** `LiveClock.set_time_alert_ns` / `set_timer_ns` (`component.pyx:897-984`) wrap the
  callback via `create_pyo3_conversion_wrapper` (:1006-1010) — also no try/except in the
  visible Python/Cython layer. Actual invocation happens inside the compiled Rust core via
  PyO3 and is **NOT inspectable from installed Python source**.
  **UNVERIFIED:** whether the Rust/PyO3 boundary logs-and-swallows or propagates a raised
  Python exception. This gap is recorded as unknown and must NOT be filled with a guess.

**Consequence for the build:** the per-cycle forecast Actor MUST wrap its own timer-callback
body in try/except and log explicitly. The framework provides no safety net for timers the
way it does for data handlers, and the live-side failure behaviour is unknown.

---

## Traps on the custom-Data write/read path

### Trap 1 (named in the plan) — silent skip on existing range — CONFIRMED, and worse than stated

`_write_chunk`, `parquet.py:378-380`:

    if self.fs.exists(parquet_file):
        print(f"File {parquet_file} already exists, skipping write")
        return

It is not merely silent: it is a bare `print()`, not a logger call — invisible to any
log-capture or monitoring pipeline that watches the logging framework. A "replace"
implemented as a rewrite is a no-op that looks like it worked and leaves no log trace.

### Trap 2 (named in the plan) — `delete_data_range` no-ops for identifier-less custom types — CONFIRMED, with the mechanism

For `identifier is None` (`parquet.py:1420-1441`), the fan-out guard is
`if f"/data/{data_cls_name}/" in directory` (:1428) — which requires a **trailing slash
after** `data_cls_name`. A flat identifier-less custom-type leaf directory is exactly
`.../data/<data_cls_name>` with nothing after it, so the substring never matches, the loop
body never runs, and the call returns having deleted nothing — zero error, zero log, zero
return-value signal.

Therefore delete-then-rewrite is doubly dead. Corrections must be written as NEW RECORDS
WITH A LATER `ts_init`.

### Trap 3 (NEW — not in the plan) — metadata is not a query filter; identity diverges between channels

`query()` (`parquet.py:1732-1744`) re-wraps every returned row into
`CustomData(data_type=DataType(data_cls, metadata=metadata), data=d)` using whatever
`metadata` kwarg **the caller passes at query time** (or `None`). It does not filter on, or
verify against, the metadata a row was WRITTEN with.

But the msgbus layer (`get_custom_data_topic`, `data_topics.pyx:199-208`) DOES key delivery
off `DataType.metadata`. So for the same `DataType`, identity means one thing on the live
delivery channel and nothing at all on the storage/query channel. Anyone assuming metadata
acts as a queryable tag in the catalog will silently read back the wrong rows.

### Trap 4 (NEW — not in the plan, minor) — empty-write gap recording can silently vanish

`write_data`'s empty-list branch (`parquet.py:311-318`) calls `extend_file_name`, which
returns immediately unless `start`/`end` are **exactly adjacent** to an existing file's
boundary (`parquet.py:455-477`, `==` adjacency only). A deliberate "checked the venue this
cycle, no forecast published" empty write can therefore record no interval and raise no
error — later indistinguishable from "never queried at all".

---

## Net effect on the plan

Verdicts 1 and 3 stand exactly as written. Verdict 2 stands with the `client_id` correction.
Verdict 4 stands with the timer trap reframed (loud crash in backtest; UNVERIFIED across the
live Rust boundary) and the mitigation made mandatory. Traps 3 and 4 are new and belong in
the WP-12 design.
