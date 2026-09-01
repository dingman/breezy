# Forecast ingestion — implementation plan

**Status:** REVISION 2. Rewritten after adversarial peer review (one BLOCK, three
APPROVE-WITH-CHANGES) and coordinator reconciliation. Not executed.
**Scope:** ingest weather FORECASTS into Breezy, staged NWS-first then Open-Meteo,
terminating at the existing `ForecastSource` consumer contract.

**Read §0 first.** Written without network access; external NWS API claims are marked
`[UNVERIFIED]` and gated behind Increment 0. Every claim about *this repository* — and,
in revision 2, every claim about the installed `nautilus_trader` package — carries a
`file:line` citation and was read directly. Every citation carried over from revision 1
was re-verified; four had drifted and are corrected (§0.3).

---

## Revision 2 — what changed and why

| # | Change | Finding that forced it |
|---|---|---|
| D1 | **Null-hypothesis miss corrected.** The as-of bound is pushed down to Nautilus' native `end=` filter. `domain/forecast_selection.py` is DELETED from the design. §1.3 item 4 is downgraded to a thin typed wrapper. R-3/R-4 re-rated. | Architecture BLOCK: `ParquetDataCatalog` already implements `ts_init <= end` at row level and prunes whole files; the §4.4 refusal copied a rationale that exists only because `select_climate_day` ranks `is_final` FIRST. The forecast rule has no `is_final` analogue. |
| D2 | **Split by SIGNAL, not by object.** A two-member capability object (`ua_trap_latched()`, `report_forbidden_403(...)`) replaces both "must not touch `SettlementGate`" and "inject the whole gate". Protocol declared outside `gate.py`. §7's spy-gate test becomes an attribute-reachability proof. Verdict recorded on the one-gate alternative (§4.3.4). | Architecture + security converged: "must not CLEAR" was over-generalised to "must not TOUCH", muting the poller most likely to latch the shared trap; and "read-only" as drafted was a naming convention, since import-linter blocks importing a module, not injecting an object. |
| D3 | **Per-instance body cap, from stage 1.** The forecast path gets its OWN `HttpTransport` instance for NWS as well as Open-Meteo. Any `max_body_bytes` parameter on `_fetch()` is explicitly prohibited. `DEFAULT_ACCEPT` handling stated honestly as a possible change to the hardened module (§4.2.3). | Two reviewers: `max_body_bytes` is already a per-instance constructor parameter (`http.py:536`), so the "per-call cap" was a lever threaded through the shared `_fetch` and reachable from settlement calls. |
| D4 | **One deployment shape, picked: ONE PROCESS.** A new `ForecastIngestState` container shares the SAME `StateStore` object and the SAME `SettlementGate` object in the settlement process. The separate `breezy-forecast` entry point is DROPPED, with the reason the `breezy-quote-tape` precedent does not transfer (§4.3.5). | §4.3's shared `SqliteStateStore` and I-5's separate process were mutually exclusive (`sqlite_store.py:122`, `:129-136`), and under a separate process the latch veto silently evaporated. §4.2's "costs nothing new" ignored `_claim_process_slot` (`shared_state.py:353`, `:614-624`). |
| D5 | **Zero-debt claim kept but now EARNED and TESTED.** The forecast Actor DOES emit health and alerts, through a primitive-typed sink Protocol declared in `breezy.ingest`, adapted onto `runtime.health` by the composition root — so no `breezy.ingest.forecast_actor -> breezy.runtime.health` edge is created (§4.9). | `pyproject.toml:78` already carries the settlement Actor's equivalent edge as layers debt; parity would have added a second entry the plan claimed not to add. |
| D6 | **`/forecast/hourly` is the design; periodised `/forecast` is a documented degraded fallback.** `predicted_high_f` is DERIVED as the max over hourly temperatures in the local-standard climate-day window. | Domain reviewer overturned OQ-3's lean: the "record verbatim, never compute" precedent is about `tavg_f` and its stated reason is that deriving it would invent a SETTLEMENT number (`nws_climate_day.py:126-131`). `predicted_high_f` is explicitly not one (§4.8). |
| D7 | **`lead_time_ns` added to the record**, with ONE canonical helper (`domain/forecast_window.py`) both the builder and any calibration script must call. | Missing field: forecast skill is horizon-dependent, so calibration cannot stratify without it — and two independent derivations is exactly the two-clock confusion `sites.py:15-16` is structured to prevent. |
| D8 | **ONE BATCH, ONE WRITE, mandated with a named test and a forecast-side integrity alarm.** | `nws_actor.py:889-898` records this as an observed real failure. One forecast poll yields many periods sharing one `retrieved_at_ns`; per-row writes would silently discard all but one row on every poll — and, with no gate participation, with no alarm. |
| D9 | **The flagship property test respecified** so it cannot pass vacuously: contesting rows straddling the bound, safety AND completeness, explicit `@example`s at the boundary. Every critical test in §7 now names the mutation it must catch. | The drafted assertion `result is None or result.ts_init <= bound` is satisfied by a reader that always returns `None`, and random int64 draws never land `ts_init == bound`, so the `<=` → `<` mutant survives. |
| D10 | **I-1 and I-3 are developed TOGETHER against I-0's payloads, behind a throwaway end-to-end spike, BEFORE the schema freezes and BEFORE I-4 deploys.** The `schema_version` decode policy is stated: **the field set is FINAL at I-1; no additive migration exists.** | Three-way convergence, and revision 2 found the stronger form: `make_strict_decoder` raises `SchemaDriftError` on any missing OR unexpected column (`strict_arrow.py:150-158`), and only one `register_arrow` per class is permitted, so a version-keyed shim is not merely undesigned — it is unreachable (§4.1.4). |
| D11 | **NWS office pattern tightened to `\A[A-Z]{3}\Z`**, with `\Z` (never `$`) and a comment saying why. | The registry stores 4-letter K-prefixed AWIPS ids (`sites.toml:121, 157, 195, 240, 279`); the gridpoints path segment is the 3-letter WFO id. `{3,4}` silently ACCEPTS the wrong identifier from the adjacent `SettlementSite.issuing_office` field. |
| D12 | **I-0's captured payloads are EVIDENCE ONLY** and structurally non-ingestible (§6, I-0). | A later "backfill" of committed payloads under a plausible `retrieved_at_ns` is exactly the backdating this design exists to prevent. |
| D13 | `issued_at_ns` renamed **`issuance_time_ns`**. | Existing precedent field name (`nws_climate_day.py:154, 188, 210, 276, 314, 342`). |
| D14 | Four drifted citations corrected; all others re-verified (§0.3). | Multiple reviewers. |
| D15 | **Forecast overdue watchdog + alert sink added to I-4**, not deferred. | Settlement has `FINAL_CLI_OVERDUE` (`gate.py:136`), staleness thresholds and an `AlertState` sink (`health.py:584`); the forecast side had none, so a multi-day outage would surface only as a silent stand-down at `decision.py:57`. |
| D16 | **Tracked risk R-11 with an owner**, gating live use at I-6/I-7. Not fixed here. | `strategy.py:242-243` returns early on a `None` forecast and nothing flattens an already-open position when the forecast later disappears. Pre-existing, but this plan makes forecast unavailability routine. |
| D17 | **Post-change aggregate request rate stated as a NUMBER** (§4.3.6), and the `/points` question resolved so that either I-0 answer yields the same steady-state count. | "A list of mitigations" is not a rate. |
| D18 | **`target_day` derivation named as a builder responsibility** with `ClimateDayWindow.std_utc_offset_hours` as its stated input, via the D7 canonical helper. | §4.1 never said who computes the join key the strategy queries on. |
| OQ-1 | Resolved as BOTH (b) and (c), with the docstring's operative claim preserved and the sigma hazard recorded (§4.10). | The `forecast_source.py:49-51` claim is literally false — `SettlementDeadline` exists — but its operative point survives. |
| — | NB-2/4/5/8/9/10, retention, station/grid binding, and two-writers-one-root addressed in §4.1.5, §4.9.2, §4.10.3, §6 (I-0), §9. | |

Revision 2 also records **three findings the review did not raise**, each verified: the
residual per-tick read cost that D1 does NOT dissolve (§4.4.3), the file-pruning
mechanism D1 mis-cited and what that implies for D8 (§4.4.2), and a pre-existing
fail-open in the settlement UA-trap veto that the forecast capability must not copy
(§4.3.3, R-12).

---

## 0. Evidence status, stated up front

| Class | Method | Status |
|---|---|---|
| Repo behaviour | Direct read of source | VERIFIED, cited `file:line` |
| Installed `nautilus_trader` 1.231.0 behaviour | Direct read of the package in `.venv/`, plus one executed round-trip check | VERIFIED, cited `file:line` |
| Prior repo findings | Direct read of committed evidence docs | VERIFIED as *what the repo asserts*, cited |
| NWS forecast API shape, cadence, payload size, archive availability | Live read-only HTTP | **NOT VERIFIED — no network tool available** |

### 0.1 The archive claim — what I actually found

The brief asked to verify, not repeat, "the NWS API serves current forecasts, not an archive."

**Verified (repo side):** Breezy holds no forecast history, and the repo has already
pre-registered that as binding.

- `docs/evidence/decision_time_clearance_prereg_2026-08-27.md:163-187` — direct
  verification: no forecast package, no forecast client (`grep -rn "forecast" src/breezy
  --include=*.py` returned four hits, "none of them code"), and the live catalog at
  `~/.local/share/breezy/catalog/polymarket_us/<CITY>/data/` contains only
  `custom_nws_climate_day/` and `custom_nws_raw_product/`, earliest
  `2026-08-24T19:50:55Z`, total 888 KB. "There is no observation stream and no forecast
  stream in it."
- `:189-194` pre-declares, bindingly: *"A forecast-based decision-time estimator — NWS
  gridpoint, NBM, Open-Meteo, or any other — cannot be backtested at all in this
  repository... it must first accumulate a forecast archive of its own and pre-register
  separately."*
- `docs/plans/TRADING_ENABLEMENT_PLAN.md:117` (REQ-DATA-09) sizes the gap independently:
  ">=2,000 settled pairs; ~13 months at live rate".

**Could NOT verify (API side):** whether `api.weather.gov` exposes any historical
forecast retrieval. Note that `/products/{id}` demonstrably serves *archived text
products* by id — that is the entire basis of existing CLI ingestion
(`ingest/http.py:587-603`) — so "the NWS API has no archive" is false as a blanket
statement. The claim needing test is narrower: **is there a retrievable archive of past
*gridpoint forecast* issuances, keyed by issuance time?** No evidence either way;
Increment 0 measures it.

**Stated plainly regardless of how that probe lands:**

> This feature does **not** make the three forecast-driven strategies backtestable over
> history. It starts a forward-collection clock from the day it deploys. Any claim of
> historical backtestability is a separate, evidenced deliverable that must survive the
> pre-registration at `decision_time_clearance_prereg_2026-08-27.md:189-194`. A forecast
> archive found in Increment 0 would be a *bonus* backfill increment, ranked last (I-8),
> never a load-bearing assumption.

### 0.2 What revision 2 verified in the installed package

Revision 1 asserted, without checking, that the catalog could not express the as-of
bound. That was wrong. The following were read directly in
`.venv/lib/python3.13/site-packages/nautilus_trader/`:

- `persistence/catalog/base.py:202-218` — `custom_data(cls=...)` forwards `**kwargs`
  (including `start`/`end`) straight to `query`.
- `persistence/catalog/parquet.py:1648-1730` — `query` routes non-Rust custom classes to
  `_query_pyarrow`.
- `parquet.py:2150-2156` — `_query_pyarrow` appends `pds.field("ts_init") <=
  used_end.value` to the dataset filter. **Inclusive**, matching `ts_init <= bound`.
- `parquet.py:2103-2109` — the datafusion/Rust variant builds the same bound as SQL
  `ts_init <= {end_ts}`.
- `parquet.py:2272-2277` calling `_query_intersects_filename` (`:2954-2967`) and
  `_parse_filename_timestamps` (`:2969-2983`) — whole FILES are pruned before any read,
  from the ISO timestamps in each fragment's FILENAME.
- Executed check (not inferred): `time_object_to_dt(1724529055123456789).value ==
  1724529055123456789`, so a plain `int` passed as `end=` is interpreted as UNIX
  nanoseconds with no lossy conversion.

Breezy's own `persistence/catalog.py:923-930` already accepts and forwards `start=`/`end=`
into `custom_data` (`:930`).

**One asymmetry worth pinning:** the pyarrow path guards with `used_end is not None`
(`:2155`) while the datafusion path guards with a truthiness test `if end:` (`:2107`), so
`end=0` is honoured by one backend and dropped by the other. A bound of 0 is degenerate,
but it is one `@example` away from being proven irrelevant — see §7.

### 0.3 Citation drift corrected in revision 2

| Revision 1 said | Correct | Note |
|---|---|---|
| `nws_actor.py:797-808` | `nws_actor.py:793-797` | "every per-site block ... clears *only* on a successful poll" |
| `sites.py:20-28` | `sites.py:15-16` (block `:15-28`) | "two genuinely different clocks in this system and they must never be confused" |
| `nws_climate_day.py:129-131` for whole-degree `tmax_f` | `nws_climate_day.py:123-125` | `:126-131` is `tavg_f` — the distinction is load-bearing for D6 |
| `pyproject.toml:27` for `hypothesis` | `pyproject.toml:28` | `:27` is `pytest-randomly` |

Also corrected inside this plan's own revision-2 reasoning: the coordinator's D1 cited
file-level pruning as `_min_max_from_parquet_metadata` (`parquet.py:556`). That function
is used by `_reset_file_names` (`:554-568`), a maintenance rename path, **not** the query
path. Query-time pruning is filename-derived (`:2272-2277`, `:2954-2983`). The conclusion
is unchanged; the mechanism matters for §4.4.2 and D8.

---

## 1. Null hypothesis: what already exists and is reused verbatim

Per `CLAUDE.md`, test this first. Breezy already has roughly 85% of it — more than
revision 1 credited, because the as-of bound is native.

### 1.1 REUSED AS-IS — no change proposed

| Component | Evidence | Why it already fits |
|---|---|---|
| Hardened transport core | `ingest/http.py:756-836` `_fetch` | HTTPS+allowlist before socket (`:605-625`), no redirects (`:630`), TLS>=1.2 (`:516`), streamed body cap (`:919-936`), strict UTF-8, sha256 over raw bytes before decode (`:810`), receipt instant stamped adjacent to the digest from an injected clock (`:829-833`). All as necessary for a forecast as for a CLI product. |
| `FetchResult` | `ingest/http.py:430-494` | Carries `retrieved_at_ns` unconditionally, no default (`:471`, `:473-486`) — precisely the point-in-time anchor a forecast record needs. |
| Proxy/TLS env guard | `ingest/http.py:250-269` | Applies unchanged. |
| URL redaction | `ingest/http.py:284-300` | Needed *more* by Open-Meteo, which uses query strings. |
| Nautilus timer + cross-thread bridge | `ingest/nws_actor.py:722-756` | The measured finding (timer callback runs on a Rust `_DummyThread` with no running loop, so `run_coroutine_threadsafe` is the only primitive — `:29-30`, `:723-734`) is a property of Nautilus, not of CLI products. |
| Timer stagger via native `start_time=` | `ingest/nws_actor.py:672-700`; pure offset function `runtime/composition.py:171-199` | Forecast polling must join the same anti-burst discipline against the same host. |
| Backtest no-network guarantee | `ingest/nws_actor.py:594-613` | `get_running_loop()` raises in backtest -> no timer armed -> "no network I/O by construction rather than by discipline". Inherited free. |
| Per-station catalog + writer lock + read-back verification | `persistence/catalog.py:391-419`, `:422-508` | Append semantics, `WriteOutcome.skipped` as integrity event (`:308-338`), non-decreasing `ts_init` per batch. |
| **The as-of BOUND ITSELF** | `nautilus_trader/persistence/catalog/parquet.py:2150-2156`, `:2103-2109`; forwarded by `persistence/catalog.py:923-930` | **Native.** Row-level `ts_init <= end` plus file-level pruning. See §0.2. Revision 1 missed this. |
| The as-of read *convention* | `persistence/catalog.py:552-617` | Required keyword, no default, runtime `TypeError` on non-`int` (`:603-610`), rationale at `:566-573`: *"an optional bound makes correctness depend on every future caller remembering to pass one, and the failure is silent"*. The CONVENTION is reused; the hand-rolled filtering is not. |
| Hand-written `Data` subclass pattern | `domain/nws_climate_day.py:1-80` | Explicit `ts_event`/`ts_init`, `to_dict`/`from_dict` by direct subscript (`:288-293`), explicit `schema()`, exactly ONE module-scope `register_arrow` (`:383-389`), `@customdataclass` refused (`:10-14`). |
| Strict Arrow encode/decode | `domain/strict_arrow.py:85-122`, `:125-172` | `SchemaDriftError` on any missing/unexpected column or type drift (`:150-166`). Reused verbatim — and it is what makes §4.1.4's schema-freeze conclusion binding. |
| `ts_init = retrieved_at_ns`, non-constructor | `domain/nws_climate_day.py:231-233`, decode check `:294-298` | Replay order equals real arrival order. |
| Shared `DataType` factory discipline | `ingest/nws_actor.py:380-388` | Trap 4/20: `DataType.topic` builds from metadata by INSERTION ORDER while `__eq__`/`__hash__` compare a `frozenset`. One `lru_cache`d factory per type is the only defence. |
| Backtest feed envelope | `runtime/backtest_feed.py:105-113`, `:116-124` | Type-EXACT `_DATA_TYPE_FACTORIES` with `UnfeedableRecordError`; `:116-120` warns a class whose name merely *starts with* another's leaks into its subscription. |
| Enrichment coordinate scaffolding | `registry/sites.py:176-189`, `:298-310`, `:407-418` | `EnrichmentCoordinates`; `settlement_eligible` validated *exactly* `False` (`:298-301`); reachable only via `enrichment_coordinates()`; structurally absent from `SettlementSite` (`:95-115`). Present for all five cities (`sites.toml:139-142, 175-178, 217-220, 258-261, 301-304`). |
| Alert sink shape | `runtime/health.py:376-386` (`AlertSink` is a `Protocol`), `:495-511` `resolve_alert_sink` | Reused via an adapter, never imported from `ingest` — §4.9. |
| Consumer contract | `strategy/weather_common/forecast_source.py:83-98`, `models.py:87-106` | Unchanged by this plan. |
| Disjoint-base convention, already written down | `persistence/catalog.py:347-348` | *"Root of the NWS data island... **Enrichment data lives under a disjoint base and never shares a root with settlement data.**"* Already committed; the structural hook for §4.7. |

### 1.2 The scaffolding that exists and is currently dead

`SiteRegistry.enrichment_coordinates()` (`registry/sites.py:407-418`) is called by **no
production code** — the only non-test references in `src/` are its own definition and
accessor. `sites.toml:78-83` states its purpose verbatim: *"ENRICHMENT-ONLY coordinate
data for forecast lookups... namespaced so that no settlement code path can reach it
through the settlement accessor."*

Pre-built for exactly this feature. **This plan's job is to call it, not to build a
coordinate source.** Any increment introducing a second home for lat/lon is a defect.

### 1.3 GENUINELY ABSENT — and only these

1. **A forecast record type.** `NwsClimateDay` models a settlement-grade observation;
   reusing it puts a forecast on the settlement topic. Non-starter.
2. **A URL builder for forecast endpoints.** `HttpTransport` exposes exactly two public
   fetch methods (`http.py:643-698`, `:700-754`), both taking *typed identifiers, never
   URLs* (`:14-22`), with hardcoded paths (`:585`, `:603`). No third path shape, no
   query-string builder anywhere in the module.
3. **A poll loop that is not settlement-gated.** `NwsIngestActor` holds the full
   `SettlementGate` and calls its mutators (§4.3).
4. **A typed forecast reader.** ~~An as-of reader.~~ **DOWNGRADED (D1).** The as-of bound
   is native (§0.2). What is absent is a *thin typed wrapper*: a function that names the
   `(station, target_day, source)` key, forwards the bound to the native `end=` filter,
   keeps the required-keyword/`TypeError` convention from `catalog.py:566-573, 603-610`,
   and applies a `(ts_init, revision_seq)` tie-break. That is roughly fifteen lines, not
   a selection module.
5. **A `ForecastSource` implementation.** Zero implementers in `src/`.
6. **A shared-host signalling seam between two pollers.** Revision 1 did not list this;
   D2 makes it explicit. Today the only cross-poller signal is the `SettlementGate`
   object itself, which is all-or-nothing (§4.3).

Six items. Everything else is reuse.

---

## 2. Problem statement

### 2.1 Three strategies price off a forecast and cannot be evaluated

- `strategy/forecast_mispricing/strategy.py:100-104` — `forecast_source` is a required
  positional argument (`:103`), raises `MissingForecastSourceError` on `None` (`:106-111`), and
  `snapshot(station=..., climate_day=..., now=...)` is called at `:237-241` on every
  quote/depth update. With no implementer, the strategy cannot be constructed at all.
- `strategy/forecast_revision_strategy.py:109-127`, `:1483` — operator bundle,
  push-shaped (`on_forecast_updated(current, previous)`), own local `ForecastSnapshot`,
  expects `NWSForecastUpdate` custom data (`:12`). Nothing publishes it.
- `strategy/calibration_mean_reversion_strategy.py:109`, `:1483`, `:1744` — same shape.

### 2.2 The seam is deliberately empty, and the docstring says why

`strategy/weather_common/forecast_source.py:5-20`: *"Breezy ingests NO forecast data...
The one and only wrong answer is to fabricate it from the settled observation — feeding
`NwsClimateDay.tmax_f` in as `expected_high_f`... gives the strategy perfect foresight of
its own settlement outcome."*

`:34-42` sanctions the correct degraded answer: `snapshot()` returning `None` means "no
forecast available", and the strategy **skips evaluation entirely** — "never trade, never
flatten-for-lack-of-forecast". §4.6 leans on this hard: it is why no cross-source fallback
chain is needed. §4.11 / R-11 records what that sanction does **not** cover.

### 2.3 The dominating requirement: point-in-time integrity

| Requirement | Mechanism | Precedent |
|---|---|---|
| Append, never update | New record per retrieval; a later forecast for the same target day is a new row | `nws_climate_day.py:65-70` — "A correction is a **new record with a strictly later** `ts_init`, never a rewrite: `ParquetDataCatalog._write_chunk` silently skips a write whose computed filename already exists" |
| Carry both times | `issuance_time_ns` **and** `retrieved_at_ns`, separate fields | `nws_climate_day.py:154`; `http.py:471` |
| `ts_init = retrieved_at_ns`, not a constructor parameter | Replay order == real arrival order | `nws_climate_day.py:20-26`, `:231-233`; decode check `:294-298` |
| Reader cannot answer with anything retrieved after `T` | Required, defaulted-nowhere `as_of_ts_init`, forwarded to the NATIVE `end=` filter | Convention: `catalog.py:566-573`, `:603-610`. Mechanism: `parquet.py:2155-2156` |

---

## 3. Options considered

**O-1. Extend `NwsIngestActor` / `NwsClimateDay` with forecast fields — REJECTED.** Puts
a prediction on the settlement record's Arrow schema and message-bus topic.
`NwsClimateDay` is read by `read_climate_day_as_of_settlement` (`catalog.py:552`) and
selected by `select_climate_day` (`domain/selection.py:140`) — it *is* the settlement
datum. Contaminating it violates the `settlement_eligible = false` wall
(`sites.py:298-301`).

**O-2. A new top-level `breezy/forecast/` package — REJECTED.** `pyproject.toml:72` sets
`exhaustive = true`, so a new top-level package **fails `lint-imports` immediately** until
inserted into `layers` (`:59-71`). That insertion is a real architectural decision with no
benefit — every piece has an obvious home in an existing package.

**O-3. A second, independent transport MODULE — REJECTED.** Duplicating `ingest/http.py`
is exactly the drift the module warns about; every control is individually load-bearing
(`:11-30`). A second transport **INSTANCE** is a different thing and is ACCEPTED from
stage 1 (§4.2, D3).

**O-4. A hand-rolled as-of selection module (`domain/forecast_selection.py`) —
REJECTED in revision 2 (D1).** It would be a second implementation of a bound Nautilus
already implements exactly (§0.2), for a rule that — unlike `select_climate_day` — has no
`is_final` term to protect.

**O-5. Reuse `HttpTransport` with new typed fetch methods on a SEPARATE INSTANCE; new
record type; a forecast Actor holding a two-member shared-host capability rather than the
gate; disjoint catalog base; native-bounded typed reader; explicit single-source
`ForecastSource` — RECOMMENDED.** This is §4.

---

## 4. Design

### 4.1 The record type — `breezy/domain/weather_forecast.py`

New hand-written `Data` subclass `WeatherForecastDay`, following `nws_climate_day.py`
exactly: explicit `ts_event`/`ts_init` properties, `to_dict`/`from_dict` by direct
subscript, explicit `schema()`, **exactly one** module-scope `register_arrow`, no
`@customdataclass`. The reasons at `nws_climate_day.py:10-19` apply unchanged and should
be *restated* in the new module's docstring, not cross-referenced away.

#### 4.1.1 Fields

| Field | Type | Note |
|---|---|---|
| `station` | `str` | Registry CLI location code, from `settlement_site(...).cli_location`. Used ONLY as the join key the strategy passes (`strategy.py:238` passes `contract.facts.settlement_station`). Never implies the forecast measures that sensor — §4.8. |
| `target_day` | `date` | Named `target_day`, deliberately **not** `climate_day`, so no reader confuses a forecast row with an observation row by field name. **Derived by the builder** — §4.1.3. |
| `predicted_high_f` | `float` | Deliberately `float`, unlike `NwsClimateDay.tmax_f: int\|None` (`:123-125`, whole degrees) — a forecast is not a whole-degree observation, and sharing the type invites sharing the semantics. **Derived** as the max over hourly values in the climate-day window — §4.8, D6. |
| `predicted_low_f` | `float \| None` | Optional; min over the same window. |
| `source` | `str` | `"nws_gridpoint_hourly"` or `"open_meteo"`. Non-null, no default. §4.6. |
| `source_endpoint` | `str` | Path shape fetched, for provenance. Distinguishes the D6 fallback (`/forecast`) from the design (`/forecast/hourly`) in the data itself. |
| `issuance_time_ns` | `int` | Upstream's own issuance/update time. **D13** — matches `nws_climate_day.py:154, 188, 210`. |
| `retrieved_at_ns` | `int` | From `FetchResult.retrieved_at_ns` (`http.py:471`). Becomes `ts_init`. |
| `derivation_window_start_ns`, `derivation_window_end_ns` | `int` | **Load-bearing** — the ACTUAL half-open window the max was taken over, as computed, not as intended. §4.8. |
| `derivation_input_count` | `int` | How many hourly values fell in the window. A count that is not the expected 24 is the loudest possible signal that the window/payload disagreed. |
| `lead_time_ns` | `int` | **D7.** `derivation_window_start_ns - issuance_time_ns`. Signed: negative for a nowcast issued during the target day, which is legitimate and must not be rejected. Computed by the ONE helper in §4.1.3. |
| `grid_id`, `grid_x`, `grid_y` | `str`, `int`, `int` (nullable for Open-Meteo) | So a grid reassignment is visible in the data (R-6). |
| `raw_sha256` | `str` | Digest of exact response bytes (`http.py:810`). |
| `parser_version`, `derivation_version`, `registry_version` | `str` | Mirrors `nws_climate_day.py:212-213`, plus a SEPARATE `derivation_version` because D6 makes Breezy the deriver of `predicted_high_f`. Parsing and deriving change for different reasons and must be independently auditable. |
| `revision_seq` | `int` | Monotonic per `(station, target_day, source)`, from 1. |
| `schema_version` | `int` | Stored, and — unlike `NwsClimateDay` — its decode policy is stated (§4.1.4). |
| `ts_event` | `int` | `= issuance_time_ns`. A forecast's semantic instant is its issuance. |

Constructor invariants (the constructor is also the catalog decode path, so per
`nws_climate_day.py:51-56` these must be *field* invariants only, never classification
guards):

- `issuance_time_ns <= retrieved_at_ns` — direct analogue of the check `NwsRawProduct`
  already performs (`nws_climate_day.py:42-45`).
- `derivation_window_start_ns < derivation_window_end_ns`.
- `derivation_input_count >= 1`.
- `revision_seq >= 1` (mirrors `:218-222`).
- `predicted_low_f is None or predicted_low_f <= predicted_high_f`.
- **No** check that `target_day` is in the future, and **no** check that `lead_time_ns`
  is positive — both are classification questions, and belong in the builder (§4.1.3),
  same reasoning as `:51-56`.

#### 4.1.2 Topic-prefix hazard

`backtest_feed.py:116-120` records that `is_matching_py("data.NwsClimateDayExtra*",
"data.NwsClimateDay*")` is **True**. `WeatherForecastDay` shares no prefix with either
existing record. A future `WeatherForecastDayHourly` **would** leak into
`WeatherForecastDay*` — this must be a named test, not a note (§7).

#### 4.1.3 `target_day` and `lead_time_ns` have exactly ONE deriver (D7, D18)

New pure module `breezy/domain/forecast_window.py`, importing nothing but `datetime`:

```
climate_day_bounds_ns(target_day: date, *, std_utc_offset_hours: float) -> tuple[int, int]
    # [local-standard midnight, next local-standard midnight), half-open, never DST-aware
target_day_for(instant_ns: int, *, std_utc_offset_hours: float) -> date
lead_time_ns(*, target_day: date, std_utc_offset_hours: float, issuance_time_ns: int) -> int
```

- The single stated input is `ClimateDayWindow.std_utc_offset_hours`
  (`registry/sites.py:146`), reached through `SiteRegistry.climate_day_window()`
  (`:381`). **Never** `SettlementDeadline.settlement_timezone` (`:150-174`), which is the
  DST-following venue clock. This is the exact pair `sites.py:15-16` says "must never be
  confused", and the two types exist as two types so that a caller cannot reach for the
  wrong one by autocomplete.
- **`breezy.ingest.forecast_records.build_forecast_day` is the builder and the only
  production caller**, exactly as `build_climate_day` (`ingest/records.py:225`) is for the
  observation record. It computes `target_day`, the derivation window, and
  `lead_time_ns` from these helpers, never inline.
- Any future calibration script under `scripts/analysis/` (already strict-typed,
  `pyproject.toml:176`) **must** import the same helpers. Pinned by a test that
  recomputes `lead_time_ns` from the stored `target_day` + `issuance_time_ns` + registry
  offset and asserts equality — so a second, divergent derivation fails CI rather than
  silently biasing a horizon-stratified calibration.

#### 4.1.4 `schema_version` decode policy: the field set is FINAL at I-1 (D10)

Revision 2 checked what a version-keyed decode shim would require, and it is not
available:

- `make_strict_decoder` raises `SchemaDriftError` if the on-disk fragment's column set
  differs from the registered schema in EITHER direction —
  `strict_arrow.py:150-158` (missing/unexpected) and `:160-166` (type drift) — and only
  then calls `from_dict` (`:168`). So a fragment written before a field was added is
  rejected at the ARROW layer, before `from_dict` ever sees `schema_version`.
- The decoder is bound to the class by a single `register_arrow` call, and a second call
  is explicitly forbidden: it *"wins in the serializer's `_SCHEMAS` registry while leaving
  `cls._schema` untouched, which permanently diverges what `to_arrow` uses from what the
  catalog writes"* (`nws_climate_day.py:16-19`).

**Therefore:** adding, removing or retyping a field after deployment makes every
already-written fragment permanently undecodable, class-wide. `schema_version` is stored
for forensics and for a future *rewrite-everything* migration; it is **not** a
compatibility mechanism, and the module docstring must say so in those words.

Consequence, which is the whole of D10: **the field set is irreversible the moment I-4
writes its first row.** So I-1 does not freeze on inspection — it freezes on evidence.
See §6.

#### 4.1.5 Where `ForecastSnapshot` lives (NB-4)

§8 non-goal 3 freezes `ForecastSnapshot`'s location in `breezy.strategy.weather_common.models`
(`models.py:87-106`). That freeze, and nothing else, is what forces §4.9's implementation
into `breezy.strategy` — `strategy` is the TOP layer (`pyproject.toml:59-64`) so nothing
below it may import the return type. Stated honestly, that has a cost: the top layer
acquires `pyarrow` and filesystem access as transitive dependencies of every strategy unit
test that imports the package.

**Evaluated, and declined for this plan:** `ForecastSnapshot` is a pure dataclass with one
method (`is_stale`, `models.py:108-112`) and no upward dependency, so moving it to
`breezy.domain` is mechanically trivial and would let `CatalogForecastSource` live in
`persistence` or `runtime`. It is declined because (a) it edits a file three strategies
import, for a benefit that is test-ergonomics only, and (b) `models.py` also holds
`MarketQuote` and `SignalDecision`, so moving one type splits a cohesive module. Recorded
as a follow-up, not silently absorbed: if strategy unit-test import cost becomes real,
move the dataclass down and relocate the source with it.

### 4.2 Transport — one more INSTANCE, never a second copy of the hardening

#### 4.2.1 Its own instance, from stage 1 (D3)

The forecast path constructs its **own `HttpTransport`** — for NWS in stage 1, not only
for Open-Meteo in stage 2. `max_body_bytes` is already a per-instance constructor
parameter (`http.py:536`, stored `:566`, enforced `:930-933`), as are `allowed_hosts`
(`:533`) and `base_url` (`:535`). So the forecast instance carries its own cap, chosen
from I-0's measured p99, and the settlement instance keeps 128 KiB
(`DEFAULT_MAX_BODY_BYTES`, `:78`) untouched.

> **PROHIBITED, explicitly:** any `max_body_bytes` parameter on `_fetch()` (`:756-836`) or
> on any public fetch method. `_fetch` is the shared hardened path used by
> `fetch_discovery_list` (`:643`) and `fetch_product` (`:700`) — the settlement calls. A
> per-call cap lever there is reachable from settlement code by construction, whatever
> the naming says. A test asserts `_fetch`'s signature carries no body-cap parameter, and
> asserts the settlement transport instance's cap is exactly 128 KiB.

#### 4.2.2 Stage 1 (NWS) — two new typed fetch methods on the transport CLASS

Built like the existing two: typed identifiers in, transport builds the path,
shape-checked by `_validated_path_identifier` (`http.py:366-401`) before any socket. They
are methods on the class and therefore *available* to the settlement instance; what
separates the paths is the INSTANCE, its allowlist, its cap, and §4.7's B-2/B-3 contracts.

- `fetch_grid_reference(lat, lon)` -> `/points/{lat},{lon}`. Coordinates come from
  `EnrichmentCoordinates` (`sites.py:176-189`) — validated TOML floats, never network
  data. Still range-check (`-90<=lat<=90`, `-180<=lon<=180`) and format to fixed
  precision in the transport: a `float` reaching a path segment via `str()` is a
  formatting-dependent path, the class of thing this module refuses (`http.py:14-22`).
- `fetch_gridpoint_hourly(office, grid_x, grid_y)` -> `/gridpoints/{office}/{x},{y}/forecast/hourly`.
  `office` is **network-derived** (parsed from the `/points` response) — exactly the
  `product_id` situation (`http.py:371-374`) — so an anchored pattern with the same
  refuse-don't-sanitise treatment.

> **The office pattern is `\A[A-Z]{3}\Z`, not `\A[A-Z]{3,4}\Z` (D11).** The gridpoints
> path segment is the three-letter WFO id (`OKX`, `MTR`, `MFL`, `LOT`, `LOX`); the
> registry's `SettlementSite.issuing_office` is the four-letter K-prefixed AWIPS id
> (`sites.toml:121, 157, 195, 240, 279` — `KOKX`, `KMTR`, `KMFL`, `KLOT`, `KLOX`).
> Accepting both does not "tolerate a variant" — it silently ACCEPTS the wrong
> identifier from the adjacent field, producing a 404 at best and a wrong grid cell at
> worst. This is the same confusion `_cli_location_url`'s error message already names:
> *"not the AWIPS PIL (`CLINYC`), not the issuing office, and not a URL"*
> (`http.py:580-582`).
>
> `\Z` and never `$`: under `.match()`, `$` also matches immediately before a trailing
> newline, so `"OKX\n"` would pass. `_validated_path_identifier` uses `pattern.match`
> (`:400`), so this is live, not theoretical. Carry that sentence as a code comment.
>
> `[UNVERIFIED]` — I-0 confirms the segment is three letters for all five sites. If any
> site's WFO is not three letters, widen the pattern with the measured evidence and add
> a test that the registry's four-letter value is still REFUSED.

`grid_x`/`grid_y` are `int`, bounds-checked non-negative.

Both are **unconditional GETs taking no cache validators**, deliberately, in the way
`fetch_product` documents (`http.py:700-730`). A gridpoint forecast *is* mutable, so a 304
would be truthful — but routing a 304 as a successful poll while writing no record is the
silent-staleness shape the CLI path went to great lengths to close. At stage 1 the
conservative default (always fetch, always write, let §4.5's dedupe policy collapse
repeats) is correct. Revisit only with measured volume evidence.

#### 4.2.3 The `Accept` header — an honest exception (D3)

`DEFAULT_ACCEPT = "application/ld+json"` (`http.py:81`) is baked into `_build_client`
(`:627-641`, header set at `:638`) and is **not** a constructor parameter. Revision 1
claimed a second instance "costs nothing new"; for the header, that is false.

- **Stage 1 (NWS).** `api.weather.gov` serves GeoJSON-LD across its API, so the existing
  header is expected to work unchanged. `[UNVERIFIED — I-0 must record the response
  `Content-Type` for `/points` and `/forecast/hourly`.]` If it works, no change.
- **Stage 2 (Open-Meteo).** Plain JSON. Most origins ignore an unknown `Accept`; a 406 is
  possible. `[UNVERIFIED — I-7 measures.]`
- **If a change is needed:** add `accept: str = DEFAULT_ACCEPT` as a **constructor**
  parameter, read in `_build_client`. That is a change to the hardened module, and this
  plan says so rather than pretending otherwise. It is acceptable in that exact shape
  because it is per-instance, adds no per-call lever, and cannot vary within a
  transport's lifetime. Pinned by a test asserting the settlement instance's request
  headers are byte-identical to today's. **Not** acceptable: a per-call `accept`
  parameter, or widening the client-level header set from caller input — the rule
  `_conditional_headers` states (`http.py:409-412`, *"A caller passes values, never
  keys"*) applies with equal force.

#### 4.2.4 Stage 2 (Open-Meteo) — the security-boundary change

`api.open-meteo.com` is a **new host**, and it is query-string driven, which
`HttpTransport` cannot express at all today.

> **Do NOT widen `DEFAULT_ALLOWED_HOSTS`.** `ingest/shared_state.py:98-99` documents it as
> *"The only host this process may fetch settlement data from."* Adding
> `api.open-meteo.com` there grants the *settlement* transport — the object that fetches
> `/products/{id}`, the settlement datum — the ability to reach a third-party host.
> Strictly larger than the feature needs.
>
> Instead: the forecast instance is reconstructed (or a third instance added) with
> `allowed_hosts=FORECAST_OPEN_METEO_HOSTS` and
> `base_url="https://api.open-meteo.com"`. The grant is exactly: *the Open-Meteo forecast
> transport instance may reach `api.open-meteo.com` over HTTPS on port 443, with no
> credentials, no redirects, and no ability to reach `/products/{id}`; and the settlement
> transport's allowlist is unchanged at `{"api.weather.gov"}`.*

For **stage 1**, `api.weather.gov` is already the sole allowlisted host
(`shared_state.py:99`) and both proposed paths are on it — **no allowlist change is
required for stage 1 at all.** `[UNVERIFIED]` only in that Increment 0 confirms the
endpoints live on that host and do not 3xx elsewhere (`http.py:855-861` treats any
non-304 3xx as an integrity alarm, so a cross-host redirect fails closed and loudly — a
useful probe signal).

Query-string support for Open-Meteo must be built the way headers were: the transport
builds the query from **typed, named parameters**, never a caller-supplied mapping —
mirroring `_conditional_headers` (`http.py:403-421`). `redact_url` (`:284-300`) already
redacts query VALUES, so log safety is inherited.

### 4.3 The Actor — `breezy/ingest/forecast_actor.py`

New `WeatherForecastActor(Actor)`, one per `(venue, city)`, reusing timer/bridge/stagger/
executor patterns from `nws_actor.py:594-756`.

#### 4.3.1 The hazard, restated precisely

`SettlementGate.record_successful_poll` (`gate.py:911-952`) clears **twenty** per-site
fields in one `replace(...)` (`:924-947`), including `parser_failure`,
`sanity_violation`, `transient_blocked`, `task_dead`, `write_integrity_violation`,
`stale_blocked` and `abuse_403_degraded`. `nws_actor.py:793-797` states the same thing
from the caller's side: *"every per-site block ... clears **only** on a successful
poll"*. A forecast poll calling it would **launder away a settlement block earned by a
bad CLI product.** That hazard is real and revision 2 does not weaken it.

#### 4.3.2 But "must not CLEAR" is not "must not TOUCH" (D2)

Revision 1 generalised the hazard into a blanket prohibition, which made the forecast
poller — the one most likely to latch the shared UA trap (R-1) — the only poller
structurally unable to REPORT it, leaving settlement to discover the trap by burning its
own requests into it. And "read-only by discipline" was not structural: import-linter
blocks importing a MODULE, not injecting an OBJECT, so nothing stopped the full gate from
being passed in later.

**Resolution: split by SIGNAL.** A capability object with exactly two members:

```
# breezy/ingest/network_veto.py   -- imports NOTHING from breezy.ingest.gate
class SharedHostVeto(Protocol):
    def ua_trap_latched(self) -> bool: ...
    def report_forbidden_403(self, *, detail: str) -> None: ...
```

- **The Protocol is declared OUTSIDE `gate.py`**, and that is not cosmetic: revision 2
  verified empirically that `grimp` records an import made inside `if TYPE_CHECKING:`
  as a real graph edge (`grimp.build_graph(...).direct_import_exists(...)` returned
  `True` for a `TYPE_CHECKING`-only import). So a Protocol *defined in* `gate.py` would
  put `forecast_actor -> gate` in the graph even under `TYPE_CHECKING`, defeating B-2.
- **`ua_trap_latched()` returns a plain `bool`, never a `GateReason`.** See §4.3.3 for
  the concrete defect that choice avoids.
- **The concrete adapter lives in a third module, `breezy/ingest/gate_veto.py`**, which
  imports `gate` and holds the `SettlementGate` in a `__slots__`-private `_gate`. It is
  constructed by the composition root and injected. B-2 forbids
  `breezy.ingest.forecast_actor -> breezy.ingest.gate` **and** `-> breezy.ingest.gate_veto`.
- **No clearing mutator is reachable as an attribute.** `report_forbidden_403` forwards
  to `SettlementGate.record_forbidden_403` (`gate.py:964-...`), which has no clearing
  branch — it can only latch the global trap (`:1053-1059`) or degrade the acting site.
  Nothing else on the gate is exposed.
- **`report_forbidden_403` reports under the SAME `(venue, city)` key as settlement**,
  not a forecast namespace. See §4.3.4 for why that is the correct key and why a
  forecast-namespaced key would be actively harmful.
- **Only 403 is reported.** Timeouts, oversize bodies, parse failures and 5xx on a
  forecast endpoint are the forecast's own business and never reach the gate — that
  preserves revision 1's true half: *a forecast outage must never block settlement.* A
  403 is different in kind: NWS's trap is scoped to the User-Agent and the host, both of
  which are shared, so a forecast 403 is genuinely evidence about settlement's access.

§7's Actor test changes accordingly, from "calls no `record_*`" to an
**attribute-reachability proof**: enumerate every public attribute of the injected object
and assert the set is exactly `{"ua_trap_latched", "report_forbidden_403"}`, and that no
attribute (public or dunder-reachable through `__dict__`) is a `SettlementGate`. That is a
claim about the object's SHAPE, which a future edit cannot satisfy by accident.

#### 4.3.3 A pre-existing fail-open the forecast veto must NOT copy

`NwsIngestActor.network_allowed` decides the settlement network veto by testing
`GateReason.UA_TRAP_403 in self.gate.blocking_causes(...)` (`nws_actor.py:800`). But
`_blocking_causes` reports the latch as `causes.append(global_entry.reason)`
(`gate.py:477-478`) — the global entry's *reason field*, not a fixed constant. Two
fail-closed paths set `ua_trap_blocked=True` with a DIFFERENT reason:
`GateReason.STATE_STORE_TAMPERED` (`:681-685`) and `GateReason.CORRUPT_PERSISTED_STATE`
(`:703-708`). In both of those states `blocking_causes` omits `UA_TRAP_403`, so
`network_allowed` returns `True` and polling continues — even though the gate is
simultaneously blocking settlement USE for the same reason. That is a fail-OPEN on the
network side of a module whose entire posture is fail-closed.

**Consequences for this plan, both mandatory:**

1. `SharedHostVeto.ua_trap_latched()` is implemented as
   `self._gate.ua_trap_latched()` — a **new, pure, read-only accessor** on
   `SettlementGate` returning `self._load_global().ua_trap_blocked` directly. It never
   goes through `blocking_causes` and never compares a `GateReason`. A test asserts it
   returns `True` under all three global block reasons.
2. The settlement-side defect is recorded as **R-12** and tracked. This plan does not fix
   it (that is a settlement change, and §8 non-goal 2 stands) but it must not be
   inherited, and a plan that silently copied the pattern would have doubled it.

Adding a pure query method to `SettlementGate` is a narrowly-scoped amendment to §8
non-goal 2: it changes no settlement behaviour, adds no mutator, and is required for the
capability object to be correct.

#### 4.3.4 Verdict on the smaller alternative: ONE gate with a forecast key namespace

The architect asked whether a second gating mechanism could be avoided entirely by giving
the forecast side its own key namespace inside the existing `SettlementGate` — it already
namespaces `gate:` vs `productidx:` by design (`shared_state.py:306-309`).

**Verdict: REJECTED in the form proposed (forecast pseudo-sites), ADOPTED in substance.**

- **Rejected as keyed pseudo-sites.** `_derive_cross_site_burst` (`gate.py:756-810`)
  counts **distinct `(venue, city)` pairs** with fresh 403 evidence (`:794-808`) and
  compares against `policy.site_threshold`, whose minimum permitted value is 2
  (`:265-270`) and whose default IS 2 (`:278`). Registering forecast pollers as extra
  sites means one physical city's 403s — one from its settlement poller, one from its
  forecast poller — would count as **two distinct sites** and immediately latch the
  global UA trap for all five cities. The policy's own docstring warns against exactly
  this class of error (`:230`, *"`site_threshold` below 2 is refused for that reason"*).
  A separate namespace with its own threshold would be a second, drifting copy of the
  backoff/latch logic — which is what the architect wanted to avoid.
- **Adopted in substance.** There is no second gating mechanism for the shared-host
  signal at all. The forecast reports 403s under the **same `(venue, city)` key**, so
  evidence aggregates by SITE rather than by POLLER — which is what the UA/host-scoped
  trap physically is. `_derive_cross_site_burst` keeps counting five sites and its
  threshold keeps meaning what it means.
- **What DOES get its own namespace** is the forecast's own state, which the settlement
  gate has no vocabulary for and no business holding: poll backoff, write-integrity
  violations, last-successful-write timestamps, and the D15 overdue watchdog. Those live
  under a `forecast:` key prefix in the same `StateStore`, alongside `gate:` and
  `productidx:` (`shared_state.py:306-309`). They are the forecast's business and must
  never be able to open or close a settlement site.

#### 4.3.5 Deployment shape: ONE PROCESS (D4)

Revision 1 was internally contradictory: §4.3 required sharing "the same
`SqliteStateStore`" while I-5 proposed a separate process. Those are mutually exclusive
as written, and under a separate process the latch veto — the primary R-1 mitigation —
silently evaporates. Revision 2 picks ONE shape and makes §4.2/§4.4/I-5 consistent with
it.

**Decision: the forecast Actors run in the SAME process as the settlement Actors, sharing
the same `StateStore` OBJECT and the same `SettlementGate` OBJECT.**

Grounds:

- `SqliteStateStore` is thread-confined by construction: `check_same_thread=True`
  (`sqlite_store.py:122`) with an explicit `RuntimeError` from any other thread
  (`:129-136`), and the class docstring states the rationale — every caller is a
  single-threaded asyncio task, and confinement *"fails LOUDLY ... rather than silently
  serializing it behind a lock"* (`:101-114`). Sharing the object inside one loop
  satisfies that. Two processes would mean two handles on one file and two writers on the
  gate's per-site keys, each writing a whole `_SiteEntry` blob (`gate.py:643`,
  `_save_site` at `:812-819`) — last-write-wins, so a forecast 403 write could silently
  clobber a concurrent settlement transition. There is no key-level merge anywhere in
  that module.
- The repo already states one-container intent, loudly: `_claim_process_slot`
  (`shared_state.py:353`, `:614-624`) refuses a second `SharedIngestState` because it
  *"would give four of the five cities a gate blind to the UA-trap latch the fifth just
  set."* A cross-process forecast poller is a milder version of exactly that objection.
- `runtime/health.AlertState` records the same assumption from the other side:
  *"Exactly one poll loop is expected to own an instance, matching every other
  single-writer assumption in this codebase (`SqliteStateStore`, `SettlementGate`)"*
  (`health.py:595-598`).

**Construction, stated exactly.** A new container `breezy/ingest/forecast_state.py`
`ForecastIngestState`, constructed by the node composition root in the same process,
alongside the existing `SharedIngestState`:

- Takes the **already-constructed** `StateStore` and `SettlementGate` objects as
  parameters. It does NOT construct a `SharedIngestState`, so `_claim_process_slot`
  (`shared_state.py:614-624`) is untouched and no second-container error arises.
- Builds its **own** `HttpTransport` (§4.2.1) with the forecast cap. This is where the
  second transport comes from — **not** by editing `SharedIngestState.__init__`
  (`shared_state.py:332-388`), which stays byte-identical.
- Builds the `SharedHostVeto` adapter over the injected gate (§4.3.2).
- Builds forecast catalogs under `BREEZY_FORECAST_CATALOG_BASE` (§4.4.1) and runs its own
  `assert_writer_lock_filesystem_supported` against THAT base — the settlement
  container's `_assert_deployment_preconditions` (`shared_state.py:363-366`) checked the
  settlement base, so the forecast base gets no coverage for free. State it; do not
  assume it.
- Claims its own process slot with the same guard shape, so a second
  `ForecastIngestState` is an error for the same reason the settlement one is.

**The `breezy-quote-tape` precedent is DROPPED, with its reason.** `pyproject.toml:234-237`
describes it as *"A SEPARATE process from `breezy`, not a subcommand of it"* — but
`breezy/runtime/quote_tape_cli.py` references no `StateStore`, no `SqliteStateStore` and
no `SettlementGate` (verified: zero matches). It shares nothing that a second writer could
corrupt. The forecast poller is the opposite case: its whole R-1 mitigation is reading and
writing state the settlement gate owns. The precedent does not transfer, and revision 1
cited it without checking.

**Two-writers-one-station-root, resolved as a non-issue.** Settlement and forecast write
to disjoint catalog bases (§4.7 B-4), so they take different writer locks and
`ConcurrentWriterError` (`catalog.py:286-294`) cannot arise between them. Within the
forecast base, one process holds one writer, so the contract is the same single-writer
contract settlement already has. If a future deployment ever splits the processes, the
contract becomes `ConcurrentWriterError` back-off — and, per this section, the latch veto
would have to be redesigned first.

#### 4.3.6 Aggregate request rate against `api.weather.gov`, as a number (D17)

`site_stagger_offset_seconds` documents the purpose of the current stagger as *"one
request per `interval / site_count` instead of five simultaneous ones per interval"*
(`runtime/composition.py:177-178`), and warns that simultaneous bursts under a single
User-Agent are *"the documented route into the NWS UA trap"* (`:179-181`).

Current, five sites on the 300 s default:

| Stream | Requests/hour |
|---|---|
| Settlement discovery list, 5 sites × 12 polls/h | **60** |
| Settlement product bodies (only when a new id appears; ~2 issuances/site/day) | **~1** avg, bursty to ~10 in a poll |
| **Current total** | **~61/h steady state** |

After this plan, forecast at a 3600 s interval (the I-0 placeholder; OQ-2 sets the real
value) with grid coordinates cached:

| Stream | Requests/hour |
|---|---|
| Forecast `/gridpoints/.../forecast/hourly`, 5 sites × 1 poll/h | **5** |
| Forecast `/points` re-resolution, weekly per site | **0.03** |
| **New total** | **~66/h — a 8% increase** |

Upper bound if I-0 forces a 1800 s interval AND `/points` must be re-resolved every poll:
5 sites × 2 polls/h × 2 requests = **20/h**, total ~81/h, **a 33% increase**. That is the
worst case this plan accepts without returning to review.

**Stagger decision (D17).** `site_stagger_offset_seconds` is **not** re-derived over
`2 * site_count`. It stays a pure, unmodified settlement function and is CALLED a second
time with different arguments: `site_stagger_offset_seconds(index, site_count=5,
poll_interval_seconds=<forecast interval>)`. The site count is unchanged; only the
interval differs, so the function's distinctness precondition (`site_count <=
poll_interval_seconds`, `:190-194`) holds trivially. Editing a documented-pure settlement
function to serve a forecast concern is refused.

Residual: a forecast poll can coincide with a settlement poll for the same site, since the
two offset sets are computed over different intervals. That is a two-request coincidence,
not a five-request burst, and the drop-not-queue overlap guard bounds it. If I-0 shows the
trap is sensitive at that scale, add a fixed phase shift to the forecast offsets — a new
constant, still not an edit to the settlement function.

**`/points` caching, resolved so that EITHER I-0 answer gives the same steady-state
count.** The grid reference `(office, grid_x, grid_y)` is resolved once per site and
stored under the forecast key namespace (§4.3.4), then re-resolved on a fixed weekly
schedule and on any `404` from the gridpoint endpoint. Steady state is therefore **one
request per poll** regardless of how I-0 answers question 7; that answer changes only the
re-resolution cadence. As a bonus this closes R-6: the weekly re-resolution compares
against the stored value and raises a forecast-side alert on change, which is a stronger
control than "it is visible in the data".

#### 4.3.7 Inherited hazards

1. **The UA trap is global and host-scoped.** Stage 1 hits the same `api.weather.gov`
   under the same `BREEZY_USER_AGENT`. The forecast Actor must (a) call
   `veto.ua_trap_latched()` before any network I/O and skip the poll when it is `True` —
   the same narrow-predicate shape as `NwsIngestActor.network_allowed`
   (`nws_actor.py:786-825`) but without §4.3.3's defect — and (b) join the stagger.
2. **Overlap guard.** `_poll_in_flight` with drop-not-queue semantics
   (`nws_actor.py:834-881`, flag at `:542`, set/cleared `:877`/`:881`) exists because
   queueing a slow cycle produces "an ever-growing backlog of polls against
   `api.weather.gov` — the burst shape that latches the UA trap". Same host, same hazard,
   same guard.
3. **Backtest safety.** Arm timers only from a running loop, per
   `nws_actor.py:594-613` — no network I/O in backtest by construction.

**Cadence.** `[UNVERIFIED]` — Increment 0 must measure how often the forecast actually
changes (compare `updateTime` across polls). Polling faster than the update cadence buys
nothing and spends UA-trap risk. OQ-2.

### 4.4 Persistence — disjoint base, append-only, natively-bounded reader

#### 4.4.1 Disjoint base

`catalog.py:347-348` already declares the rule. Implement it: a new
`BREEZY_FORECAST_CATALOG_BASE` setting, sibling to `BREEZY_CATALOG_BASE`
(`runtime/settings.py:52`, consumed `:324`), with a **startup assertion that neither path
is a prefix of the other after resolution** — mirroring the escape check at
`catalog.py:383-386`, which already uses `Path.resolve().is_relative_to(...)`. Reuse
`station_catalog_path`/`open_station_catalog` unchanged — already base-parameterised
(`catalog.py:341`, `:391`).

#### 4.4.2 One batch, one write — mandatory, and why it is worse here than for CLI (D8)

`nws_actor.py:889-898` records this as an observed real failure, verbatim:

> *"Writing one product per call was tried and is **wrong**: two products retrieved inside
> one clock tick share a `retrieved_at_ns`, so the second write is an exact
> `ts_init`-range rewrite, which the catalog discards **silently** with a bare `print`
> (`parquet.py:378-380`) and reports as `skipped` -- routing straight to
> `record_write_integrity_violation`, CRIT, hard-block. Observed for real: a preliminary
> and a final ingested in one poll blocked the site and lost one record."*

A single forecast fetch returns MANY periods spanning ~7 target days, and **all rows from
one poll share one `retrieved_at_ns`** because `FetchResult` stamps it once (`http.py:829-833`).
So a per-row write would silently discard all but one row **on every poll, from day one** —
not as an occasional collision but as the steady state. And it would be worse than the CLI
case in exactly the way that matters: for climate days the collision was CAUGHT, because
`skipped` routes to `record_write_integrity_violation` (`gate.py:1175`) → CRIT → hard
block. The forecast Actor deliberately holds no gate mutator (§4.3.2), so as revision 1
specified it, there would have been **no alarm at all**.

**Mandated:**

- All rows produced by one poll cycle are assembled into ONE list and written with
  **exactly one `write_records` call per record type** (`catalog.py:422-508`).
- The batch **aborts as a unit** on any hard failure, for the same reason the CLI batch
  does (`nws_actor.py:900-906`).
- A **forecast-namespaced `write_integrity_violation` equivalent** is recorded in the
  `forecast:` key namespace (§4.3.4) whenever `WriteOutcome.skipped` is non-empty
  (`catalog.py:316-338` names the non-empty `skipped` as an integrity event), and it
  raises a CRITICAL through the §4.9 alert sink. It blocks further forecast writes for
  that site; it never touches the settlement gate.
- Test and mutation named in §7.

**Second reason to batch, found in revision 2.** Query-time file pruning is derived from
each fragment's FILENAME (`parquet.py:2272-2277` → `_query_intersects_filename` `:2954-2967`
→ `_parse_filename_timestamps` `:2969-2983`), which encodes the fragment's `ts_init`
interval. One batch per poll produces one fragment covering a real interval, so pruning
works. A per-row loop would produce degenerate single-instant fragments in far greater
number — and it is exactly the pruning in §4.4.3 that keeps the read cost bounded.

#### 4.4.3 Reader — `read_forecast_as_of` in `persistence/catalog.py` (D1)

```
read_forecast_as_of(catalog, *, station, target_day: date, source: str,
                    as_of_ts_init: int) -> WeatherForecastDay | None
```

- `as_of_ts_init` is a **required keyword with no default**; non-`int` (notably `None`)
  raises `TypeError`. The rationale is quoted verbatim from `catalog.py:566-573` and
  the guard mirrors `:603-610`, applying with more force here because the silent failure
  is lookahead bias rather than a settlement mismatch.
- **The bound is pushed down to the native filter.** The implementation calls
  `_read(catalog, WeatherForecastDay, start=<see below>, end=as_of_ts_init)`
  (`catalog.py:923-930`), which reaches `pds.field("ts_init") <= used_end.value`
  (`parquet.py:2155-2156`). **There is no second implementation of the bound.**
- **What survives, and why it is not a selection module.** The only rules the native
  filter cannot express are (a) match `(station, target_day, source)` and (b) among the
  matches take max `(ts_init, revision_seq)`. Those are a private
  `_select_forecast(rows, ...)` helper in `persistence/catalog.py`, beside its only
  caller. **`breezy/domain/forecast_selection.py` is deleted from the design.** The
  `_select_current_climate_day` precedent (`catalog.py:667-712`) does not apply, because
  its stated reason for refusing the pushdown is that *"the selection rule is
  settlement-critical and must have exactly one implementation"* (`:688-691`) — and that
  rule ranks `is_final` FIRST (`nws_climate_day.py:71-76`), which the native filter
  genuinely cannot express. A forecast has no finality: the most recently *received*
  forecast is the answer, full stop.
- **A `start=` lower bound is passed too, and it is a performance control, not a
  correctness one.** D1 says R-3 should "largely dissolve"; revision 2 checked, and half
  of it does not. The `end=` bound prunes the FUTURE; it does nothing about the past, so a
  multi-year forecast archive would still be read in full on every tick. The fix is a
  lower bound derived from `target_day`, not from the caller: a forecast for target day
  `D` is only ever issued within `MAX_LEAD_DAYS` before it, so
  `start = utc_midnight_ns(D) - (MAX_LEAD_DAYS + 1) days`. This can never cause lookahead
  — it only narrows the past, and its worst possible failure is returning `None` where a
  stale row existed. The invariant is **enforced at write time** by the builder (a record
  whose `lead_time_ns` exceeds `MAX_LEAD_DAYS` is refused at build, not at decode) and
  pinned by a test. One extra UTC day of slack means no local-standard offset reasoning
  enters the read path at all.
- With both bounds, a lookup touches only the fragments whose filename interval
  intersects a ~9-day window (§4.4.2), so the per-tick row count is
  `polls/day × lead-days × sources` — hundreds, not the whole archive.

**There is deliberately NO unbounded accessor.** A *deliberate divergence* from the
observation precedent, which offers both (`catalog.py:620`). For observations the
unbounded read answers a real audit question. For forecasts it is only useful
retrospectively, and its existence is a permanently loaded footgun aimed at the exact bias
this design exists to wall out. If analysis later needs it, add it under a name that
cannot be typed by accident (e.g. `read_forecast_history_for_analysis`) and forbid it from
`breezy.strategy` by import-linter. Not in this plan.

### 4.5 Dedupe policy (was OQ-4)

**Decision: append unconditionally; do not build a dedupe index.** If a poll returns a
byte-identical payload (`raw_sha256` and `issuance_time_ns` unchanged), a new row is still
written. Reasons: it preserves "we asked at T and this is what we got", which is the whole
point of a point-in-time archive; and the alternative requires a `ProductIntegrityIndex`
-shaped structure (`ingest/product_index.py`) whose skip decision is itself a place
lookahead could hide.

Cost is bounded and now calculable: with hourly polling, 5 sites, one source, and
`MAX_LEAD_DAYS = 7`, a poll writes ~7 rows, so ~840 rows/day across all sites, ~300 k
rows/year. Against `NwsClimateDay`'s ~2 rows/site/day this is ~84× — which is precisely
why §4.4.3 bounds the read window rather than relying on the observation reader's
retention assumption (`catalog.py:693-702`), whose own docstring scopes it to
observations. R-8 measures it after 30 days.

### 4.6 Two sources, one consumer — explicit policy, no fallback chain

The repo's precedent is uncompromising: `registry/sites.py:352-354` — `settlement_site`
*"never returns `None` and never silently substitutes a neighbour"* — backed by
`never_substitute` validated non-empty at load (`:211-213`). Silent substitution between
forecast sources is the same defect wearing different clothes.

1. **A `ForecastSource` instance is bound to exactly ONE source at construction.**
   `CatalogForecastSource(catalog=..., source="nws_gridpoint_hourly", ...)` — required, no
   default, scalar not sequence. No fallback parameter, no source list, no ordering. A
   run's provenance is a property of its wiring, recorded in the run config, not an
   emergent outcome of which endpoint answered.
2. **Unavailability returns `None`, and that is a complete answer** for the *decision*.
   `forecast_source.py:34-42` sanctions it and the strategy skips (`strategy.py:242-243`).
   The degraded path is already designed and tested at the strategy. What it is NOT is a
   complete answer for *operations* — see D15/§4.9 and R-11/§4.11.
3. **Disagreement is MEASURED, not resolved.** Both sources are collected when both are
   enabled (disjoint `source` values, same catalog). A separate offline report —
   `scripts/analysis/` already exists and is under strict mypy (`pyproject.toml:176`) —
   computes the NWS-vs-Open-Meteo difference distribution per station, stratified by
   `lead_time_ns` (D7). A wide distribution means *the model is not ready*, not *pick one
   at runtime*. Nothing in the live path ever consults the other source.

**What Open-Meteo is FOR:** not redundancy. (a) an independent measurement for evaluating
NWS forecast skill without circularity; (b) a second candidate feature for a future
ensemble *fitted* on both, offline. Both uses are offline. Neither is a runtime failover.

### 4.7 Forecasts must never become a settlement input — structural enforcement

| # | Barrier | Mechanism | Checked by |
|---|---|---|---|
| B-1 | Coordinates unreachable from settlement | `EnrichmentCoordinates` absent from `SettlementSite` (`sites.py:95-115`), reachable only via `enrichment_coordinates()` (`:407-418`); `settlement_eligible` validated *exactly* `False` (`:298-301`) | Existing tests + fixture `settlement_eligible_true.toml` |
| B-2 | Forecast ingestion cannot reach the settlement gate except through the two-member capability | New import-linter `forbidden` contract: source `breezy.ingest.forecast_actor`, forbidden `breezy.ingest.gate` **and** `breezy.ingest.gate_veto`. The Protocol it does import (`breezy.ingest.network_veto`) imports neither — necessary because grimp counts `TYPE_CHECKING` imports (§4.3.2, verified) | `lint-imports` |
| B-3 | Settlement code cannot see forecast records | New `forbidden` contract: sources `breezy.settlement`, `breezy.domain.selection`, `breezy.normalize`; forbidden `breezy.domain.weather_forecast` | `lint-imports` |
| B-4 | Forecast bytes never share a filesystem root with settlement bytes | Disjoint base + startup non-nesting assertion (§4.4.1) | Unit test; `catalog.py:347-348` is the stated rule |
| B-5 | **Defence in depth only, and named as such (NB-10)** | `WeatherForecastDay` carries no `is_final` and no `tmax_f`, so a settlement path consuming it would not typecheck against `select_climate_day` (`domain/selection.py:140`) | `mypy` — but this is a TYPE barrier that a `cast` or a `dict` round-trip defeats. It is not structural and this plan does not count it as one |

B-2, B-3 and B-4 answer "structurally rather than by convention": they are
`pyproject.toml` contracts and a startup assertion that fail CI and boot respectively, not
docstrings. Note `pyproject.toml:73-81` treats the existing layers `ignore_imports` list as
*"current inspected debt"* — this plan adds **zero** new entries to it, and §4.9 is what
earns that (§5).

### 4.8 Gridpoint forecast high vs CLI observed high — and why Breezy DERIVES it (D6)

**They are not the same measurement, and the difference is not a rounding detail.**

`[UNVERIFIED in detail — Increment 0 must confirm against a live payload.]` Certain from
the repo side:

- The market settles on the **CLI observed high**: `NwsClimateDay.tmax_f`, parsed from
  `/products/{id}` verbatim text (`docs/plans/WEATHER_INGESTION_PROPOSAL.md:73` — *"the
  settlement datum"*), in **whole degrees F** (`nws_climate_day.py:123-125`), for a
  climate day defined as **local-standard midnight to midnight, never DST-aware**
  (`registry/sites.py:133-146`).
- A gridpoint forecast is a **model output on a grid cell**, not a reading from the
  station's sensor. Two mismatches:
  1. **Spatial.** The grid cell is an area; the CLI high is one specific ASOS sensor. The
     repo already treats station identity as sacred — `never_substitute` exists precisely
     because a neighbouring *station* is not acceptable (`sites.py:211-213`). A grid cell
     is a *weaker* substitute, not a stronger one. This mismatch is irreducible and is
     what calibration is for.
  2. **Temporal.** NWS forecast *periods* are day/night halves on local civil
     (DST-following) time; the climate day is local-**standard** midnight-to-midnight. The
     repo has been bitten by exactly this class of confusion — `sites.py:15-16` describes
     *"two genuinely different clocks in this system and they must never be confused"* and
     structurally separates them into two types with two accessors.

**Revision 2 reverses revision 1's lean on OQ-3.** Revision 1 justified the periodised
`/forecast` endpoint by citing the repo's "record verbatim, never compute" precedent. That
precedent does not transfer, and the citation was to the wrong field:

- `nws_climate_day.py:126-131` is about **`tavg_f`**, and its stated reason is that
  deriving `(tmax + tmin) / 2` *"would invent a **settlement** number, which is forbidden
  in the same terms as imputing a sentinel. The venue settles on the observed high, low
  and average, so the published integer **is** the settlement datum."* The rule is
  "never invent a settlement number", not "never compute".
- `predicted_high_f` is explicitly **not** a settlement number. §4.8's own closing
  paragraph says so, `ForecastSnapshot` makes no such claim (`models.py:87-95`), and B-3
  forbids settlement code from seeing the record at all.
- Meanwhile the temporal mismatch is not correctable after the fact. Recording period
  bounds lets calibration *measure* a bias whose sign and magnitude depend on where the
  diurnal peak falls relative to the boundary — which varies by site, by season and by
  synoptic pattern. On ~1 °F strike buckets that moves probability mass across a strike.
  Measuring a non-stationary bias is not the same as correcting it.

**Decision:**

- **Use `/forecast/hourly`.** Derive `predicted_high_f` as the max over hourly temperature
  values whose valid time falls in `[local-standard midnight(target_day), local-standard
  midnight(target_day + 1))` — the half-open window from
  `forecast_window.climate_day_bounds_ns` (§4.1.3), computed from
  `ClimateDayWindow.std_utc_offset_hours` (`sites.py:146`) and nothing else.
- **Record the window actually used**, not the window intended:
  `derivation_window_start_ns`, `derivation_window_end_ns`, `derivation_input_count`.
- **Version the derivation separately** (`derivation_version`), and fixture-test it
  against I-0's captured payloads with the same rigor `build_climate_day`
  (`ingest/records.py:225`) is tested with — including a DST-transition target day for
  each of the five sites, which is where a civil-vs-standard error would show up.
- **Periodised `/forecast` becomes a documented DEGRADED FALLBACK**, used only if I-0
  shows the hourly payload is prohibitive (R-5). If used, `source` and `source_endpoint`
  say so in the data, `derivation_input_count` is 1 or 2, and the plan states plainly that
  rows collected that way carry an uncorrectable window bias.

**What this does NOT change:** the strategies consume `expected_high_f` as a model input.
A biased-but-honest predictor is a legitimate feature. A predictor silently *labelled* as
the settlement measurement is not. This plan produces the former.

### 4.9 Health, alerts and the overdue watchdog (D5, D15)

#### 4.9.1 The forecast Actor DOES emit health and alerts

Revision 1 claimed zero new layers debt while proposing a health-and-alert-free Actor.
Both halves were wrong: `pyproject.toml:78` already carries
`breezy.ingest.nws_actor -> breezy.runtime.health` as inspected layers debt, so parity
would have added a second entry — and an ingestion feature whose entire value is an
uninterrupted forward archive cannot ship without an outage alarm.

**Resolution that keeps the zero-debt claim and EARNS it:**

- A primitive-typed sink Protocol is declared in `breezy/ingest/forecast_alerts.py`:
  `emit(self, *, key: str, severity: str, event: str, detail: str) -> None`. Every
  parameter is a builtin, so the module imports nothing from `runtime`.
- The **composition root in `runtime`** adapts it onto the real sink: `runtime.health`
  already exposes `AlertSink` as a `Protocol` (`health.py:376-386`) and
  `resolve_alert_sink` (`:495-511`) to pick logging-vs-webhook. The adapter constructs the
  `AlertPayload` (`health.py:343-375`, a concrete class — which is exactly why the ingest
  side cannot type against the real sink directly) and calls `emit_alert` (`:514`).
- Direction is `runtime -> ingest`, which is downward and legal (`pyproject.toml:59-71`).
  **No `breezy.ingest.forecast_actor -> breezy.runtime.health` edge is created.**
- Success criterion 5 (§11) now asserts this by running `lint-imports`, rather than
  claiming it.

The forecast health snapshot is written to its own file under the forecast namespace,
never mixed into `health-<venue>.<city>.json`, so an operator reading the settlement
runbook cannot mistake one for the other.

#### 4.9.2 The overdue watchdog (D15)

Settlement has `FINAL_CLI_OVERDUE` (`gate.py:136`, cause at `:504`, transition at
`:1416`), staleness thresholds, gap reconciliation, and an `AlertState` transition tracker
(`health.py:584-600`). The forecast side gets the minimum equivalent, in I-4, not as a
follow-up:

- `forecast_collection_overdue` — no successful forecast WRITE for `(venue, city, source)`
  within `overdue_threshold_seconds` (default 3 × poll interval). Latched in the
  `forecast:` key namespace so it survives a restart, cleared only by a successful write.
- Severity CRITICAL through §4.9.1's sink, and reflected in the forecast health snapshot
  so it is visible without a webhook — the same "the alert alone is not enough" reasoning
  the settlement Actor already records (`nws_actor.py:1840-1847`).
- **Why this is not deferrable.** Without it, a multi-day outage produces: no alert; a
  stale row returned happily by `read_forecast_as_of` (which bounds the future, not the
  past); and then a **silent stand-down** — `decision.py:57-66` returns a `FLAT` decision
  with `reason="stale_forecast"` once `ForecastSnapshot.is_stale` (`models.py:108-112`)
  trips against `cfg.stale_forecast_hours`. From the outside that reads as market
  conditions, not as "ingestion is dead."

#### 4.9.3 `published_at` is the issuance time — a named decision (NB-9)

`CatalogForecastSource` sets `ForecastSnapshot.published_at` from
`WeatherForecastDay.issuance_time_ns`, **not** from `retrieved_at_ns`. That is a decision,
not an implementation detail, because `published_at` is the sole input to
`is_stale(now, max_age_hours)` (`models.py:108-112`) which drives the `stale_forecast`
stand-down at `decision.py:57`. Consequences, stated:

- Staleness then measures *how old the forecast is*, which is the semantically right
  question for a model input, and it means a poller that keeps re-fetching an unchanged
  upstream forecast does NOT reset the staleness clock. Correct.
- But it also means a *collection* outage is invisible to `is_stale` until the last
  fetched forecast itself ages out. That gap is exactly what §4.9.2's watchdog covers,
  and the two controls are named as complementary rather than redundant.

### 4.10 The `ForecastSource` implementation

`breezy/strategy/weather_common/catalog_forecast_source.py`. Location forced by §4.1.5.

```
snapshot(*, station: str, climate_day: date, now: datetime) -> ForecastSnapshot | None
```

1. Convert `now` -> `as_of_ts_init` (UNIX ns).
2. `read_forecast_as_of(catalog, station=station, target_day=climate_day,
   source=self._source, as_of_ts_init=as_of_ns)`.
3. `None` -> return `None`. No fallback, no synthesis (§4.6).
4. Otherwise build `ForecastSnapshot(location_id=station, target_date=climate_day,
   published_at=<from issuance_time_ns>, expected_high_f=<predicted_high_f>,
   horizon_hours=<§4.10.1>, source=<record.source>, raw_payload_id=<record.raw_sha256>)`.

**`source` is set explicitly and pinned by test (NB-8).** `ForecastSnapshot.source`
defaults to `"SYNTHETIC-INJECTED"` (`models.py:103`). §4.6 makes provenance load-bearing,
so a test asserts that a snapshot built from a real record never carries that default —
mutation to catch: deleting the `source=` argument.

**Live and backtest use the same object.** In a backtest, `now` comes from
`self.clock.utc_now()` (`strategy.py:236`), which is simulated time. Because step 2's
bound derives from `now` and the reader is *incapable* of returning a row with
`ts_init > as_of_ts_init` (the filter is applied by the catalog itself,
`parquet.py:2155-2156`), the backtest cannot see a forecast it had not yet received — via
the same code path as live. That parity is the point: a separate backtest implementation
is a second place for the bound to be forgotten.

**Per-tick read cost (R-3, re-rated MED).** `snapshot()` is called on every quote and
depth update (`strategy.py:187`, `:201-217`, `:237-241`). §4.4.3's two-sided bound puts a lookup at
hundreds of rows over a handful of fragments rather than the whole archive, which is a
different order of problem from revision 1's unbounded read. Measure in I-6. **If a cache
is still needed, it must be delta-refreshing**: hold rows read up to `cached_upper`, and
on a call with a later bound read only `start=cached_upper + 1, end=new_bound`. That shape
is as-of-safe by construction, because every row it can ever hold came from a query whose
`end` was <= the bound in force when it was fetched. A cache keyed on anything but the
bound, or refreshed on a timer, is R-4. The §7 property test runs against the **public**
read path including any cache.

#### 4.10.1 Where `horizon_hours` comes from (OQ-1, resolved as BOTH (b) and (c))

**(b) Inject a settlement-instant resolver into `CatalogForecastSource`.** A
`SettlementInstantResolver` Protocol (declared in `breezy.strategy.weather_common`) with
`nominal_settlement_instant(*, venue, city, climate_day) -> datetime`. The default
implementation reads `SiteRegistry.settlement_deadline()` (`sites.py:394`). Injected, so
it stays swappable per venue for the eventual Kalshi move.

**(c) Amend the `forecast_source.py:49-51` docstring, which is literally false.** It
asserts *"Breezy has no equivalent wall-clock settlement source at the strategy layer"* —
but `SettlementDeadline` (`sites.py:150-174`) is exactly such a source and
`registry` is a legal downward import from `strategy` (`pyproject.toml:59-71`).

**The operative claim survives, and the amended docstring must say why.**
`SettlementDeadline` yields a **NOMINAL** deadline, never the realized instant, because it
is CONDITIONAL by construction: `settlement_delay_time_local` /
`settlement_delay_timezone` apply *"when the CLI reading disagrees with the 24-hour METAR
observation"* (`sites.py:165-168`) — and Breezy does not ingest METAR
(`TRADING_ENABLEMENT_FINDINGS.md:122-123`), so it cannot evaluate that condition. Worse,
`no_data_fallback_days` (`sites.py:174`) can move settlement by DAYS. `InstrumentClose`
remains the only authority for the realized instant. So the resolver returns a
**nominal** horizon and must be named and documented as such.

**The hazard the plan missed, and the constraint it imposes.** `horizon_hours` drives two
things with opposite error directions:

- `strategy.py:244-246` — `if forecast.horizon_hours <= halt_hours_before_settlement:
  flatten("settlement_halt")`. A horizon that is too SMALL flattens early. Errs **safe**.
- `HorizonSigmaParams.sigma_per_sqrt_hour_f` (`strategy.py:117-120`) — the probability
  model's sigma scales with the horizon. A horizon that is too small drives sigma toward
  `sigma_floor_f`, **understating uncertainty**. Errs **unsafe**.

A DELAYED settlement (the exact case `SettlementDeadline`'s conditional branch describes)
drives the nominal horizon toward zero and past it, collapsing sigma to the floor precisely
when the outcome is least settled. **Therefore the resolver contract must state that it
returns a nominal horizon, and the sigma path must not be allowed to collapse on that
basis** — at minimum, `horizon_hours` is floored at a configured minimum before it reaches
the sigma computation, and a test pins that a horizon of 0 does not yield
`sigma == sigma_floor_f`. Whether the halt path should use the unfloored value (it should,
since it errs safe) is a strategy-side decision recorded here and executed in I-6.

**How this differs from the fabricated clock that was deliberately removed.**
`forecast_source.py:45-48` records that the operator's bundle *"computed 'hours to
settlement' from a settlement clock it fabricated per-contract (a hardcoded default
timezone and 23:59-local settlement time)"* and that it was removed. This resolver is not
that, on two counts, and the amended docstring must state both or the removal is quietly
undone:

1. It reads **per-site, registry-verified, live-provenanced values** —
   `settlement_time_local` / `settlement_timezone` are loaded from `sites.toml`, whose
   header records that these fields were verified against venue documentation
   (`sites.toml:97-102`) — rather than hardcoding a default for every contract.
2. It is **venue-supplied and injected**, not strategy-computed. The strategy still
   receives one number through the existing seam and cannot reach the clock itself.

### 4.11 What the `None` sanction does not cover (D16 / R-11)

`forecast_source.py:34-42` sanctions "no forecast -> skip evaluation, never trade, never
flatten-for-lack-of-forecast", and `strategy.py:242-243` implements it as a bare early
return. Two consequences this plan must name rather than inherit silently:

1. **Evaluation bias.** If NWS outages correlate with volatile weather — plausible, and
   untested — then systematically skipping those episodes biases any forward evaluation of
   the strategy in an unknown direction.
2. **An already-open position is not flattened when the forecast disappears.** The early
   return happens BEFORE the `settlement_halt` check (`:244-246`), so once `snapshot()`
   starts returning `None` the position's protection rests entirely on
   `halt_hours_before_settlement` and `RiskLimits` — neither of which this plan audits,
   and neither of which is reached while the forecast is absent.

This is pre-existing strategy behaviour, and fixing it is out of scope (§8 non-goal 10).
But **this plan is what makes forecast unavailability routine rather than hypothetical**,
so it is tracked as **R-11** with an owner and it **gates live use at I-6/I-7**: before the
strategy is enabled against real forecast data, either show that an existing control
closes it, or land the control.

---

## 5. Layering — exactly which packages gain which imports

`pyproject.toml:51-81`, `exhaustive = true` (`:72`).

| Module | New imports | Direction | Legal today? |
|---|---|---|---|
| `breezy.domain.forecast_window` (new) | stdlib only | within `domain` | Yes, no change |
| `breezy.domain.weather_forecast` (new) | `pyarrow`, `nautilus_trader.core.data`, `nautilus_trader.serialization.arrow.serializer`, `breezy.domain.validation`, `breezy.domain.strict_arrow` | within `domain` | Yes, but needs **one** entry on the forbidden-nautilus `ignore_imports`: `breezy.domain.weather_forecast -> nautilus_trader` — identical to the waivers its two siblings hold (`pyproject.toml:104-105`). The `disallow_subclassing_any` override at `:220` is `breezy.domain.*`, already covering it — **no mypy edit needed** |
| ~~`breezy.domain.forecast_selection`~~ | — | — | **DELETED (D1)** |
| `breezy.ingest.http` (edit) | none new | — | Yes |
| `breezy.ingest.network_veto` (new, Protocol only) | `typing` | within `ingest` | Yes, no change. **Must not import `breezy.ingest.gate`** — grimp counts `TYPE_CHECKING` imports (§4.3.2, verified) |
| `breezy.ingest.gate_veto` (new, adapter) | `breezy.ingest.gate`, `breezy.ingest.network_veto` | within `ingest` | Yes, no change |
| `breezy.ingest.forecast_alerts` (new, Protocol only) | `typing` | within `ingest` | Yes, no change. Primitive-typed on purpose (§4.9.1) |
| `breezy.ingest.forecast_records` (new builder) | `breezy.domain.weather_forecast`, `breezy.domain.forecast_window`, `breezy.registry.sites` | downward | Yes, no change |
| `breezy.ingest.forecast_actor` (new) | `nautilus_trader`, `breezy.domain.weather_forecast`, `breezy.ingest.http`, `breezy.ingest.network_veto`, `breezy.ingest.forecast_alerts`, `breezy.ingest.forecast_records`, `breezy.persistence.catalog`, `breezy.registry.sites` | `ingest` -> `persistence\|registry` -> `domain`: **downward** | Yes. Needs `breezy.ingest.forecast_actor -> nautilus_trader` (same waiver `breezy.ingest.nws_actor` holds, `:107`) plus a `disallow_subclassing_any` override mirroring `:207-209`. Must **not** import `breezy.ingest.gate` or `gate_veto` (B-2) |
| `breezy.ingest.forecast_state` (new container) | `breezy.ingest.{http,gate,gate_veto,forecast_actor}`, `breezy.persistence.catalog`, `breezy.registry.sites` | within/downward | Yes, no change. It MAY import `gate` — it is the composition point, not the Actor |
| `breezy.persistence.catalog` (edit) | `breezy.domain.weather_forecast` | downward | Yes, no change (already holds `:108`) |
| `breezy.runtime.backtest_feed` (edit) | `breezy.domain.weather_forecast` + new `DataType` factory | downward | Yes, no change |
| `breezy.runtime.forecast_composition` (new) | `breezy.runtime.health`, `breezy.ingest.forecast_alerts`, `breezy.ingest.forecast_state` | `runtime` -> `ingest`: **downward** | Yes, no change. This is the §4.9.1 adapter and it is why the zero-debt claim holds |
| `breezy.registry.sites` (edit) | none | — | The registry is unchanged; `enrichment_coordinates()` (`:407-418`) is finally CALLED |
| `breezy.ingest.gate` (edit) | none new | — | One new pure read accessor `ua_trap_latched()` (§4.3.3). No mutator, no behaviour change |
| `breezy.strategy.weather_common.catalog_forecast_source` (new) | `breezy.persistence.catalog`, `breezy.domain.weather_forecast`, `breezy.registry.sites` | `strategy` TOP -> all downward | Yes, **no change** (nautilus waiver already wildcarded for `breezy.strategy.**` at `:133`; `disallow_subclassing_any` wildcarded at `:220`) |

**Net `pyproject.toml` changes:** 2 `ignore_imports` entries on the forbidden-nautilus
contract (each identical in kind to one already accepted), 1 `disallow_subclassing_any`
override for the new Actor module (mirroring `:207-209`), **2 new `forbidden` contracts**
(B-2, B-3), **zero** `layers` changes, and — now earned rather than asserted — **zero** new
entries on the layers contract's debt list (`:73-81`). No new top-level package, so
`exhaustive = true` is unaffected.

---

## 6. Build order

Each increment independently mergeable **except where D10 forces a pairing**. Ranked by
load-bearing-ness.

### I-0. Live read-only probe + evidence document — PREREQUISITE, blocks everything

Not code. A probe under the existing `live` marker (`pyproject.toml:46` — *"performs REAL
network I/O against api.weather.gov and needs `BREEZY_LIVE=1`; deselected by default"*),
producing a committed doc under `docs/evidence/`, following `sites.toml:97-102`'s
precedent for exactly this kind of live verification.

Must answer, with captured payloads:

1. Do `/points/{lat},{lon}` and `/gridpoints/{office}/{x},{y}/forecast/hourly` resolve on
   `api.weather.gov` for all five sites' `EnrichmentCoordinates`, with no 3xx? (A 3xx
   fails closed, `http.py:855-861`.) Record the response `Content-Type` — §4.2.3 depends
   on it.
2. **Payload size** for `/forecast/hourly`, for `/forecast`, and separately for raw
   `/gridpoints/{office}/{x},{y}`, against the 128 KiB default cap (`http.py:78`). Sets
   the forecast instance's `max_body_bytes` (§4.2.1).
3. Field names for the hourly temperature value, its valid-time interval, and the
   issuance/update time.
4. **Update cadence** — repeat-poll one gridpoint, record how often `updateTime` changes.
   Sets the poll interval (OQ-2) and therefore §4.3.6's rate.
5. **Is the WFO path segment three letters for all five sites?** (D11.) Record the
   `/points` response's `gridId` verbatim next to the registry's `issuing_office`, so the
   two-identifier distinction is documented in evidence, not just in a regex.
6. **Station/grid binding.** Does `/points` for a site's `EnrichmentCoordinates` resolve
   to a grid cell that plausibly contains that site's ICAO station? Record the returned
   `relativeLocation`, the cell's `forecastOffice`, and the site's `icao` side by side. A
   mismatch is a finding that changes what §4.8's spatial-mismatch paragraph is claiming,
   and it must be caught before I-1 freezes the field set.
7. **Is any historical/archived forecast retrieval available?** (§0.1.) Record the answer
   either way; a negative is a *finding*, not a failure.
8. Whether `/points` responses are stable enough for grid coordinates to be cached, or
   must be re-resolved. Per §4.3.6 this changes only the re-resolution cadence.

**Risk:** this probe spends UA-trap exposure against the host settlement depends on. Run
staggered, off-peak, well under existing pacing discipline, and stop on the first 403.

> **The captured payloads are EVIDENCE ONLY (D12).** They are committed under
> `docs/evidence/` for fixture use and for auditability. They must **never** be ingestible
> into the production forecast catalog. Structural bar, all three required: (a) they are
> stored with a `.probe.json` suffix that no production loader reads; (b) the builder
> `build_forecast_day` takes a `FetchResult` (`http.py:430-494`), never a file path, so a
> record cannot be constructed without a live retrieval instant; (c) a test asserts that
> no module outside `tests/` and `scripts/analysis/` reads from `docs/evidence/`.
> Rationale: a later "backfill" of these payloads under a plausible `retrieved_at_ns` is
> exactly the backdating this entire design exists to prevent, and it would be
> indistinguishable from real collection after the fact.

### I-1 + I-3 (PAIRED, D10). Record type + transport + parser + builder, behind a spike

**These two do not merge separately.** The reason is §4.1.4: `make_strict_decoder` rejects
any fragment whose column set differs from the registered schema
(`strict_arrow.py:150-158`), and only one `register_arrow` per class is permitted
(`nws_climate_day.py:16-19`), so **no additive migration exists** — the field set is
irreversible the moment I-4 writes its first row. Revision 1 first exercised the field set
at I-6 and began deployment at I-4, which meant the schema would have frozen before
anything proved it was right.

Contents:

- `domain/forecast_window.py` (§4.1.3) and `domain/weather_forecast.py` (§4.1) with one
  module-scope `register_arrow`.
- `fetch_grid_reference` + `fetch_gridpoint_hourly` on `HttpTransport` (§4.2.2), the
  parser, and `ingest/forecast_records.py::build_forecast_day` mirroring
  `ingest/records.py:225`. Fully testable with `respx` (`pyproject.toml:29`) against I-0's
  captured payloads. No allowlist change.
- **A throwaway end-to-end spike, run before the schema freezes and deleted after:**
  I-0 payload -> `build_forecast_day` -> `write_records` -> `read_forecast_as_of` ->
  `ForecastSnapshot`. Its only job is to prove the field set is sufficient for the
  consumer, while changing it is still free. Its deletion is part of the increment.
- The module docstring states the freeze in the words of §4.1.4.

**Review bar is raised accordingly:** the field set is reviewed as an irreversible
decision, not as a refactorable one.

### I-2. `read_forecast_as_of` (§4.4.3)

The typed wrapper: the key, the required-keyword/`TypeError` convention, the pushdown to
`end=`, the `start=` window, the `(ts_init, revision_seq)` tie-break, and the deliberate
absence of an unbounded accessor. Small, because the bound is native. Mergeable alone.

### I-4. `WeatherForecastActor` + veto + watchdog + wiring + the two import-linter contracts

Poll loop (§4.3), the `SharedHostVeto` Protocol/adapter and the new
`SettlementGate.ua_trap_latched()` accessor (§4.3.2-3), `ForecastIngestState` in the same
process (§4.3.5), disjoint base + non-nesting assertion (§4.4.1), one-batch-one-write plus
the forecast integrity alarm (§4.4.2), the alert seam and the overdue watchdog (§4.9),
`/points` caching and the forecast stagger (§4.3.6), B-2/B-3 (§4.7).

**First increment that writes bytes, so it starts the forward-collection clock** — the one
to prioritise for *deployment*, though I-1+I-3 is the one to prioritise for *correctness*.

### I-5. Wiring into the existing node — NOT a separate process

Per §4.3.5. Revision 1 listed a separate `breezy-forecast` entry point here; that is
withdrawn, with its reason. What remains in this increment is the composition-root work in
`runtime/forecast_composition.py` (§4.9.1) and the deployment-precondition assertions the
forecast base does not inherit (§4.3.5). It folds into I-4 if convenient.

### I-6. `CatalogForecastSource` — the increment that unblocks the strategies

§4.10, including the settlement-instant resolver, the nominal-horizon contract and the
sigma floor (§4.10.1). Includes `_DATA_TYPE_FACTORIES` registration
(`backtest_feed.py:121-124`) so forecasts replay, plus the topic-prefix-leak test
(§4.1.2), the `source` provenance pin (NB-8), and the R-3 measurement that decides whether
a delta-refreshing cache is needed. **R-11 is assessed here and gates live use.** After
this, `ForecastMispricingStrategy` is constructible and runnable — against *forward* data
only.

### I-7. Open-Meteo — the second source

New `HttpTransport` instance with `FORECAST_OPEN_METEO_HOSTS`, typed query-string builder,
new parser, `source="open_meteo"` (§4.2.4, §4.6). **Security-boundary review required
before merge**, with the grant stated exactly as in §4.2.4, plus the §4.2.3 `Accept`
decision if it is needed. Architecturally a no-op elsewhere: record type, reader, Actor
shape and `ForecastSource` were all designed for N sources from the start.

### I-8. (Conditional, ranked LAST) Historical forecast backfill

Only if I-0 answer #7 is positive. Must independently satisfy the pre-registration at
`decision_time_clearance_prereg_2026-08-27.md:189-194`, and must not be confused with
I-0's evidence payloads (D12). Explicitly not assumed by anything above.

**Ordering:** `I-0 -> (I-1 + I-3) -> I-2 -> I-4 -> I-5` is a genuine dependency chain. I-6
depends on I-2 and I-4. I-7 depends on I-1+I-3 and I-2.

---

## 7. Test strategy

This repo's standard of proof is mutation testing, so every critical row names the mutant
it must kill.

| Layer | Test | Mutation it must catch |
|---|---|---|
| Record | `ts_init == retrieved_at_ns`, NOT a constructor parameter; `from_dict` raises if they disagree (mirrors `nws_climate_day.py:294-298`) | Adding `ts_init` as a constructor parameter; deleting the `from_dict` equality check |
| Record | `issuance_time_ns > retrieved_at_ns` raises | Flipping the comparison; removing the guard |
| Record | Missing column in `from_dict` raises `KeyError`, never adopts a default | Replacing a subscript with `values.get(...)` — the exact defect `@customdataclass` was rejected for (`nws_climate_day.py:10-14`) |
| Record | Arrow round-trip through `schema()` preserves every field; a fragment with one column removed raises `SchemaDriftError` | Loosening `make_strict_decoder`'s column-set check (`strict_arrow.py:150-158`) |
| Record | `register_arrow` called exactly once at module scope (AST assertion) | Adding a second call (`nws_climate_day.py:16-19`) |
| Record | `predicted_low_f > predicted_high_f` raises | Removing the ordering invariant |
| Derivation | `predicted_high_f` equals the max over hourly values in `[local-standard midnight, next)`, per site, **including a DST-transition target day for each of the five sites** | Using `SettlementDeadline.settlement_timezone` instead of `ClimateDayWindow.std_utc_offset_hours`; using a closed rather than half-open window; off-by-one-hour on the boundary |
| Derivation | `lead_time_ns` recomputed from stored `target_day` + `issuance_time_ns` + registry offset equals the stored value | A second, divergent derivation appearing anywhere (D7) |
| Derivation | `derivation_input_count` equals the number of hourly values in the window, and a payload with a gap produces a count < 24 rather than a silently short max | Dropping the count field; computing it from the intended window rather than the actual one |
| **Point-in-time** | **The flagship test (D9).** `hypothesis` (`pyproject.toml:28`) generates, per `(station, target_day, source)` key, **>=2 contesting rows straddling the bound**. Asserts BOTH: (a) SAFETY — the returned row's `ts_init` is never `> as_of_ts_init`; (b) COMPLETENESS — the returned row is exactly the max-`ts_init`-<=-bound row, including a case where two rows share a `ts_init` and `revision_seq` breaks the tie. Explicit `@example`s at `ts_init == bound`, `bound + 1`, `bound - 1`, and `bound == 0` (§0.2's backend asymmetry) | `<=` -> `<` in the bound (killed only by the `ts_init == bound` example); a reader that always returns `None` (killed only by completeness); dropping the `revision_seq` tie-break; passing `end=` as something other than the bound |
| Point-in-time | Omitting `as_of_ts_init` is `TypeError`; passing `None` is `TypeError` | Adding a default; removing the `isinstance` guard (mirrors `catalog.py:603-610`) |
| Point-in-time | A later forecast for the same `(station, target_day, source)` APPENDS; the earlier row is still readable at an earlier bound | Any in-place update path; a `start=` bound that excludes the earlier row |
| Point-in-time | A row whose `lead_time_ns` exceeds `MAX_LEAD_DAYS` is refused **at build**, and the reader's `start=` window is proven to contain every buildable row | Widening the builder's lead check without widening the reader window, or vice versa (§4.4.3) |
| Point-in-time | If a cache is added: the property test above runs against the PUBLIC path including the cache | A cache keyed on anything but the bound; a timer-refreshed cache (R-4) |
| **Write** | **N rows sharing one `retrieved_at_ns`: assert exactly ONE `write_records` call and all N present on read-back (D8)** | **Reverting to a per-row write loop** — the mutant `nws_actor.py:889-898` says was tried in production and lost a record |
| Write | Non-empty `WriteOutcome.skipped` raises the forecast integrity alarm and blocks further forecast writes for that site | Treating `skipped` as success; routing it to the settlement gate instead |
| Transport | `respx` replay of I-0 payloads; malformed/oversize/non-UTF-8/3xx/403/429 each route to the right error | Any relaxation in `_fetch`'s error taxonomy |
| Transport | The office pattern REFUSES the registry's four-letter `issuing_office` (`KOKX`) and accepts `OKX`; `"OKX\n"` is refused | `\A[A-Z]{3}\Z` -> `\A[A-Z]{3,4}\Z`; `\Z` -> `$` (D11) |
| Transport | `_fetch` and every public fetch method carry **no** body-cap parameter; the settlement instance's cap is exactly 128 KiB | Adding a per-call `max_body_bytes` (D3) |
| Transport | The settlement instance's outgoing headers are byte-identical to today's after any §4.2.3 `accept` change | A per-call `accept`; changing the default |
| Transport | `api.open-meteo.com` refused by the settlement transport; `api.weather.gov` refused by the Open-Meteo transport | Widening `DEFAULT_ALLOWED_HOSTS` |
| Transport | A forecast method cannot be aimed at `/products/{id}` and vice versa (disjoint identifier shapes) | Loosening either pattern |
| **Actor** | **Attribute-reachability proof (D2):** the injected veto's public attribute set is exactly `{"ua_trap_latched", "report_forbidden_403"}`, and no attribute anywhere on it is a `SettlementGate` | Injecting the gate directly; adding any `record_*` passthrough; exposing `_gate` publicly |
| Actor | `veto.ua_trap_latched()` returns `True` under ALL THREE global block reasons: `UA_TRAP_403`, `CORRUPT_PERSISTED_STATE`, `STATE_STORE_TAMPERED` | Implementing it as `GateReason.UA_TRAP_403 in blocking_causes(...)` — the §4.3.3 fail-open |
| Actor | A forecast 403 records evidence under the **same** `(venue, city)` key; `_derive_cross_site_burst`'s distinct-site count is unchanged by the forecast poller's existence | Registering forecast pseudo-sites (§4.3.4) — the mutant that spuriously latches all five cities |
| Actor | A forecast poll SUCCESS changes no settlement gate state at all; a forecast timeout / oversize / 5xx / parse failure leaves the settlement gate untouched | Calling `record_successful_poll`; reporting non-403 failures |
| Actor | No timer armed with no running loop (backtest safety) | Removing the `get_running_loop` guard (`nws_actor.py:594-613`) |
| Actor | Overdue watchdog fires after `overdue_threshold_seconds` with no successful write, latches across a restart, and clears only on a write | Making the latch in-memory; clearing it on a failed poll (D15) |
| Layering | `lint-imports` green with both new contracts; a synthesised module importing `breezy.domain.weather_forecast` from `breezy.settlement` FAILS; a synthesised `forecast_actor` importing `gate` under `if TYPE_CHECKING:` also FAILS | Declaring the veto Protocol inside `gate.py` (§4.3.2). Mirrors the live-`lint-imports` technique in `tests/unit/test_strategy_module_gate.py` (`pyproject.toml:131-132`) |
| Layering | `lint-imports` green with **zero** new entries on the layers `ignore_imports` list (`pyproject.toml:73-81`) | Importing `runtime.health` from `ingest.forecast_actor` instead of using the §4.9.1 adapter (D5) |
| Topic | `WeatherForecastDay` does not prefix-collide with `NwsClimateDay`/`NwsRawProduct`; a hypothetical `WeatherForecastDayHourly` DOES, and the test says so | Adding a prefix-sharing record class (`backtest_feed.py:116-120`) |
| Snapshot | `ForecastSnapshot.source` built from a real record is never `"SYNTHETIC-INJECTED"` (`models.py:103`) | Dropping the `source=` argument (NB-8) |
| Snapshot | `published_at` comes from `issuance_time_ns`, not `retrieved_at_ns` | Swapping them — silently changing what `is_stale` measures (NB-9) |
| Horizon | A nominal horizon of 0 does not collapse sigma to `sigma_floor_f` | Removing the horizon floor on the sigma path (§4.10.1) |
| End-to-end | `ForecastMispricingStrategy` + `CatalogForecastSource` over a synthetic tape: a forecast written at `T+1` does not influence a decision at `T` | Any lookahead reintroduced anywhere on the public path |
| Filesystem | Forecast base nested inside settlement base (either direction) fails at startup | Removing the non-nesting assertion (§4.4.1) |
| Evidence | No module outside `tests/` and `scripts/analysis/` reads from `docs/evidence/` | A "backfill from evidence" loader (D12) |

Coverage: meet whatever the project gate is; no threshold invented here.

---

## 8. Non-goals

1. **Making the three strategies backtestable over history.** §0.1. This starts a forward
   clock.
2. **Any change to settlement BEHAVIOUR.** Settlement is CLI only, for this plan. Narrowly
   amended by §4.3.3: one new pure read-only accessor on `SettlementGate`, no mutator, no
   behaviour change.
3. **Any change to `ForecastSource` or `ForecastSnapshot`'s SHAPE.** The consumer contract
   is fixed. The `forecast_source.py` module DOCSTRING is corrected (§4.10.1) because it
   is factually false as written; the Protocol is untouched. `ForecastSnapshot`'s LOCATION
   is also frozen — with the cost of that freeze stated rather than hidden (§4.1.5).
4. **Porting `forecast_revision_strategy.py` / `calibration_mean_reversion_strategy.py`
   onto the seam.** They are push-shaped (`on_forecast_updated`,
   `forecast_revision_strategy.py:1483`) with their own local `ForecastSnapshot` (`:109`).
   Converting them is real work with real design questions and belongs in its own plan.
   This plan unblocks `ForecastMispricingStrategy`, which already speaks the seam
   (`strategy.py:103`, `:237-241`), and makes the data available to the other two.
5. **A probability/calibration model over forecast error.** REQ-ALPHA-04
   (`TRADING_ENABLEMENT_PLAN.md:529`).
6. **METAR / intraday observations.** A different absent ingestion family
   (`TRADING_ENABLEMENT_FINDINGS.md:122-123`) — and the reason `SettlementDeadline` can
   only ever be nominal (§4.10.1).
7. **Widening `DEFAULT_ALLOWED_HOSTS`.** Explicitly refused (§4.2.4).
8. **Conditional GET on forecast endpoints.** §4.2.2; revisit only with measured volume
   evidence.
9. **Fixing R-12**, the settlement-side UA-trap veto fail-open found while writing this
   revision (§4.3.3). Reported and tracked; not inherited.
10. **Fixing R-11**, the absent flatten-on-forecast-disappearance path (§4.11). Tracked
    with an owner, and it gates live use at I-6/I-7.
11. **Any live-trading enablement.** Operator-only gate.

---

## 9. Risks

| ID | Risk | Sev | Mitigation |
|---|---|---|---|
| R-1 | **Forecast polling latches the UA trap and takes settlement down.** Same host, same UA. The trap latches every site and clears only by manual operator action (`gate.py:1053-1059`) | **HIGH** | Join the stagger (§4.3.6, stated as a NUMBER: +8% steady state, +33% worst case); honour the latch as a network veto via `ua_trap_latched()` (§4.3.2), implemented so it cannot fail open (§4.3.3); overlap guard drop-not-queue; poll interval from I-0's measured cadence, not guessed; `/points` cached so the count does not double; I-0 run off-peak, aborted on first 403 |
| R-2 | **The `source` field becomes a de-facto fallback chain** as soon as someone adds `sources=[...]` "for robustness" | **HIGH** | §4.6's single-source-at-construction rule enforced by the constructor signature (required, no default, scalar not sequence) + a test asserting no sequence-typed source parameter |
| R-3 | **Per-tick catalog read cost.** `snapshot()` runs on every quote/depth update (`strategy.py:187`, `:201-217`) and forecasts accrue ~84× faster than observations (§4.5) | **MED** (was HIGH) | Re-rated by D1, but only half dissolved: the native `end=` bound prunes the future, not the past. §4.4.3 adds a `target_day`-derived `start=` bound so a lookup touches a ~9-day window, with file-level pruning (`parquet.py:2272-2277`). Measured in I-6; if a cache is still needed it must be delta-refreshing |
| R-4 | **A caching or convenience layer reintroduces lookahead** | **MED** (was HIGH) | Re-rated: the reader itself can no longer be the source, since the bound is applied by the catalog (`parquet.py:2155-2156`), not by Breezy code. The remaining surface is a cache, so §4.10's delta-refresh shape is mandated and the property test runs against the public path including it. The unbounded accessor is deliberately not built (§4.4.3) |
| R-5 | **Hourly payload exceeds the 128 KiB default** and someone raises the global constant (`http.py:78`), weakening settlement | MED | I-0 measures. The forecast instance carries its own cap (`http.py:536`) so the global is never touched; a test pins the settlement cap at 128 KiB and forbids a per-call lever (D3). Degraded fallback to `/forecast` is documented (§4.8) |
| R-6 | Gridpoint reassignment changes `(office, x, y)` for a fixed lat/lon mid-collection, silently changing what is measured | MED -> **LOW** | `grid_id`/`grid_x`/`grid_y` on every record makes it visible, AND §4.3.6's weekly `/points` re-resolution compares against the stored value and alerts on change — an active control, not just an audit trail |
| R-7 | The forecast window is assumed to equal the climate day, quietly biasing every calibration | **MED -> LOW** | D6: the window is DERIVED from `ClimateDayWindow.std_utc_offset_hours`, the actual window used is recorded, `derivation_input_count` makes a short window loud, and DST-transition days are fixture-tested per site (§7) |
| R-8 | Disk and fragment growth — append-only, no dedupe, ~300 k rows/year (§4.5) | LOW–MED | Measure after 30 days. `catalog.py:693-702`'s retention assumption is scoped to observations and does not transfer. §4.4.2's one-batch-one-write keeps fragments coarse enough for filename-based pruning to work |
| R-9 | I-0's probe itself trips a rate limit or the trap | MED | R-1 mitigations; the probe is the first thing to touch the network and the smallest possible request set |
| R-10 | Open-Meteo terms-of-use / attribution obligations for a commercial trading use | MED | Must be checked and recorded in I-7's review. Not technical, but real, and unverified in this plan |
| **R-11** | **An already-open position is never flattened when the forecast disappears** (`strategy.py:242-243` returns before the halt check at `:244-246`), and skipping outage episodes may bias forward evaluation | **HIGH** | D16. Pre-existing strategy behaviour, but this plan makes forecast unavailability routine. Tracked with an owner; **gates live use at I-6/I-7** — either show an existing control (`halt_hours_before_settlement`, `RiskLimits`) closes it, with the audit, or land the control. §4.11 |
| **R-12** | **Settlement's own UA-trap network veto fails OPEN under corrupt or tampered global gate state** — `network_allowed` matches `GateReason.UA_TRAP_403` (`nws_actor.py:800`) but `_blocking_causes` reports `global_entry.reason` (`gate.py:477-478`), which is `CORRUPT_PERSISTED_STATE` (`:703-708`) or `STATE_STORE_TAMPERED` (`:681-685`) on the two fail-closed paths | **MED** | Found while writing revision 2; **not caused by this plan and not fixed by it** (§8 non-goal 9). The forecast veto is specified so it cannot inherit the pattern (§4.3.3), with a test across all three reasons. Reported to the settlement owner separately |
| R-13 | The `schema_version` field creates false confidence that fields can be added later | MED | §4.1.4 states the opposite in the module docstring and I-1's review bar is raised accordingly; the I-1+I-3 pairing and the spike exist for this reason alone |

---

## 10. Open questions

**OQ-1 — RESOLVED (§4.10.1).** `horizon_hours` comes from an injected settlement-instant
resolver reading `SettlementDeadline`, returning an explicitly NOMINAL horizon, plus a
docstring correction and a sigma floor. Recorded here rather than deleted because the
resolution carries a live constraint on I-6.

**OQ-2 (blocking I-4). Poll cadence.** Still open; cannot be chosen before I-0 measures
the actual update cadence. Polling faster than upstream updates spends R-1 for zero
information. §4.3.6's numbers assume 3600 s and state the 1800 s worst case.

**OQ-3 — RESOLVED (§4.8, D6).** `/forecast/hourly` with a derived maximum over the
local-standard window; periodised `/forecast` is a documented degraded fallback gated on
I-0's payload size.

**OQ-4 — RESOLVED (§4.5).** Append unconditionally; no dedupe index. Cost calculated and
bounded by §4.4.3's read window and R-8's measurement.

**OQ-5 (I-7, still open). Does Open-Meteo belong in this repo at all, or in an offline
research tool?** §4.6 concludes both its uses are offline. If nothing in the live path ever
reads it, an argument exists that it should not be a Nautilus Actor at all but a standalone
collector. The lean is toward keeping it in-tree in the same record type — one record
shape, one reader, one set of guarantees — but the counter-argument (don't put non-live
code in the live process) is legitimate, and §4.3.5's one-process decision makes it
sharper: every Open-Meteo failure mode now lands in the settlement collector's process.
Decide at I-7, not before.

**OQ-6 (NEW, non-blocking). Should `ForecastSnapshot` move to `breezy.domain`?** §4.1.5
declines it for this plan and states the cost of declining. Revisit if strategy unit-test
import cost becomes measurable.

**OQ-7 (NEW, blocking I-6). `ForecastSource` returns the CURRENT forecast, not every
publication since the last poll — and `forecast_revision` is degraded until it can.**
The `ForecastSource.snapshot` Protocol as written returns only the forecast current as of
`now`. `ForecastRevisionStrategy` accumulates revision history by polling it
(`RevisionState.observe`), so any genuine NWS revision that lands AND is superseded
between two polls is permanently invisible: history retains only the later publication,
and `evaluate_instrument` scores ONE MERGED delta across what were two separately-scored
revision events. Three consequences, all affecting trading behaviour:

- a merged `d_t`/`d_p` can clear `min_temp_revision_f` / `min_unabsorbed_prob` when
  neither constituent revision would alone — a **false positive**;
- two opposite-sign revisions can net to roughly zero and both be skipped — a
  **false negative**;
- `window_end` anchors to the LATER publication, so a poll landing after
  `reaction_window_minutes` has already elapsed drops straight to the catch-up exit and
  never attempts an entry it could have traded.

Until I-6 lands, correctness requires a polling cadence strictly finer than BOTH the real
forecast-issuance interval and `reaction_window_minutes` — which ties this to OQ-2. The
behaviour is deliberately pinned, not silently tolerated, by
`test_a_publication_missed_between_polls_is_merged_not_scored` in
`tests/unit/test_forecast_revision_decision.py`.

**What I-6 must therefore provide:** `CatalogForecastSource` must be able to return EVERY
publication in an interval, not just the latest as-of instant. The append-only forecast
store (§4.4.1, OQ-4's unconditional-append policy) makes this natural and cheap — the rows
are already there, and `read_forecast_as_of`'s native `end=` bound (§4.4.3) is one half of
the range already. The Protocol change belongs to I-6; it was deliberately NOT made at
strategy-integration time, because no implementer exists yet and changing a Protocol with
no implementer is speculative.

---

## 11. Success criteria

- [ ] I-0 evidence doc committed, with captured payloads, sizes, cadence, the WFO/AWIPS
      identifier pair per site, the station/grid binding check, and an explicit answer on
      forecast-archive availability — and a test proving those payloads are not reachable
      by any production loader.
- [ ] `WeatherForecastDay` registered exactly once; `ts_init == retrieved_at_ns` enforced
      on construct AND decode; the module docstring states that the field set is final
      (§4.1.4).
- [ ] I-1 and I-3 merged together, after a throwaway end-to-end spike, before I-4 deploys.
- [ ] `read_forecast_as_of` is the ONLY forecast read path, and the as-of bound is the
      catalog's native `end=` filter with **no second implementation** in Breezy.
- [ ] The flagship property test proves BOTH safety and completeness, with explicit
      boundary examples, and kills the `<=` -> `<` mutant.
- [ ] No unbounded forecast accessor exists in `breezy.strategy`'s reachable surface.
- [ ] `lint-imports` green including both new `forbidden` contracts, **and** with zero new
      entries on the layers contract's `ignore_imports` debt list (`pyproject.toml:73-81`)
      — verified by running it, not asserted.
- [ ] `DEFAULT_ALLOWED_HOSTS` is still exactly `{"api.weather.gov"}`; the settlement
      transport's cap is still 128 KiB; `_fetch` carries no body-cap parameter.
- [ ] The object injected into the forecast Actor exposes exactly two members, neither of
      which can clear a settlement block, proven by attribute reachability rather than by
      call spying.
- [ ] `ua_trap_latched()` returns `True` under all three global block reasons.
- [ ] One poll cycle produces exactly one `write_records` call per record type, with all
      rows present on read-back.
- [ ] The forecast overdue watchdog fires, latches across a restart, and reaches an
      operator without a webhook.
- [ ] Forecast and settlement catalog roots provably disjoint at startup.
- [ ] `ForecastMispricingStrategy` runs end-to-end against forward-collected data with no
      lookahead, and R-11 has a written verdict before any live use.
- [ ] The plan's own honesty claim holds: no document produced by this work claims
      historical backtestability.
