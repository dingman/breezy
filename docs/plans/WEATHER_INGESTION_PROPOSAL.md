# Breezy — Weather Data Ingestion Implementation Proposal (v6)

Status: **APPROVED by operator 2026-08-22. Phase 0 in progress. No production code written.**
Scope: ingesting **NWS** (primary/authoritative) and **Open-Meteo** (secondary/enrichment) into the NautilusTrader-based system.

**What v6 is.** v5 appended its corrections as a §12 appendix rather than folding them into the body, leaving ~12 places where §§1–11 still asserted what §12 had already refuted — an implementer following the phase plan would have built the rejected design. v6 folds every correction into the text, records the operator's decisions as settled, and deletes superseded alternatives. **There is no appendix of corrections. If it is in this document, it is current.** Revision history is §11; it is a record, not a source of design.

Evidence base: 7 design agents, 3 adversarial reviewers, 2 verification agents, a native-extension audit, a full official-documentation review, and a 4-seam verification pass (coverage/consistency, empirical API verification, Open-Meteo design, settlement fidelity). Nautilus claims are executed against the installed **1.231.0**, not read from docs.

> **Documentation version trap — read first.** `nautilustrader.io/docs/latest` serves **2.x/develop**, not our version; there is no version-pinned 1.231 URL (it 404s). On that page, `from nautilus_trader.model import register_custom_data_class` raises `ImportError` here, and `DataType("Name", …)` with a string first arg is a 2.x change. The claim *"BacktestDataConfig accepts built-in catalog data types, not arbitrary custom types"* is **2.x-only and false for 1.231.0** — custom-data replay was executed end-to-end here. Authoritative reference for this install: the vendored tree at `docs/reference/nautilus/v1.231.0/`. Where docs and shipped code disagree, **trust the code**.

---

## 0. Operator decisions (settled 2026-08-22)

| # | Decision | Consequence |
|---|---|---|
| 1 | **Cities: the venue's five.** NYC, San Francisco, Miami, Chicago, Los Angeles | **Philadelphia is dropped** — it is not a Polymarket.us weather market. The `nws-cli-settlement` skill invented it |
| 2 | **User-Agent: `breezy-data@gopoint.com`** (role mailbox, must receive mail) | Blocks all live NWS fetching until created |
| 3 | **Open-Meteo: free tier**, no API key, 10,000 calls/day | Phase 3 only. Free-tier terms are non-commercial and a trading bot is not — flagged once, operator's call, revisit before live capital |
| 4 | **Retention/WORM deferred** | Raw products still land in the catalog with digests from day one, so the 7-year requirement stays satisfiable later without migration |
| 5 | **ACIS disagreement halts the station**, auto-resume on agreement | Fully autonomous; no operator in the loop |
| 6 | **Post-settlement corrections auto-adopt** | Truth and calibration update automatically. Venue P&L stays immutable. The old `\|Δ\| > 5 °F ⇒ operator ack` gate is **removed**; a physically impossible value is still rejected as bad data (validation, not a human gate) |
| 7 | **Venue discovery / KYC track: not yet** | Data ingest first. Phases 0–2 are venue-independent |
| 8 | **`httpx` for weather fetching approved**, scoped — venue traffic keeps `HttpClient` | The one deliberate deviation; bypasses nothing Nautilus owns |
| 9 | **Market rules-snapshot mechanism deferred** | The resolver's rounding/threshold operators stay **explicitly unimplemented** rather than guessed. A manual verbatim snapshot of the venue FAQ is captured in Phase 0 |
| 10 | **Phase 0 (docs + config) proceeds first** | This document, the three skills, the registry, the pin |

---

## 1. Proposed architecture

**Four components.** v5's three, plus the feature layer the coverage audit found had no owner — derived/enriched data was being implicitly homed in `normalize/`, which is meant to be pure and settlement-facing.

| Component | Owns | Nautilus-free? |
|---|---|---|
| `normalize/` | pure functions: parse → classify → validate → `ClimateDayReading` (plain frozen dataclass) | **Yes** — `mypy --strict` clean |
| `domain/` | catalog record types + explicit Arrow schemas | No |
| `features/` | derived/enriched features (bias, ensemble spread). **ENRICHMENT-grade only** | **Yes** |
| `ingest/` | Nautilus `Actor`s: poll, publish, persist, recover | No |

```
src/breezy/
  registry/{sites.py,sites.toml}   # settlement binding — single source of truth
  normalize/                       # PURE: no I/O, no clock, no nautilus
    cli_parse.py  classify.py  climate_day.py  units.py  reading.py
    openmeteo_bucket.py            # reuses climate_day.py — no second bucketing rule
  domain/
    nws_climate_day.py  nws_raw_product.py
    openmeteo_forecast_run.py      # disjoint catalog root
  features/openmeteo_features.py   # bias, ensemble spread — never read by settlement/
  ingest/nws_actor.py  ingest/open_meteo_actor.py  ingest/http.py
  settlement/resolver.py           # operates on ClimateDayReading, not on records
  persistence/backfill.py          # pyiem lives HERE ONLY
tests/{unit,contract,integration,replay,fixtures}/
docs/evidence/venue/polymarket_us/ # verbatim hashed venue-rules snapshots
```

**Layer separation:** raw (`NwsRawProduct`) → normalized (`NwsClimateDay` → `ClimateDayReading`) → derived (`features/`) → signal → execution. `settlement/` consumes the plain `ClimateDayReading`, never a Nautilus record and never a feature. Signal and execution are Phase 4 and out of scope for this document.

---

## 2. NWS integration design

### 2.1 Source inventory and grade

| Endpoint | Role | Grade |
|---|---|---|
| `/products/types/CLI/locations/{loc}` | discovery list (conditional GET) | metadata |
| `/products/{id}` | verbatim `productText` — **the settlement datum** | **SETTLEMENT** |
| `/stations/{icao}/observations` | METAR; venue conflict-branch input | advisory |
| `/gridpoints/.../forecast` | forward forecast | advisory |
| `data.rcc-acis.org/StnData` | independent cross-check | advisory (veto only) |

Nothing but `/products/{id}` is ever a settlement value. The monthly/seasonal CLM product is excluded structurally (the discovery endpoint and the AWIPS-PIL allowlist both reject it) — but that exclusion is now asserted by a named test rather than left implicit.

### 2.2 Station binding — venue-authoritative

The binding source is no longer a skill's prose table but **the venue's own published rules**, snapshotted verbatim in `docs/evidence/venue/polymarket_us/`:

| City | Station named by venue | Settlement source |
|---|---|---|
| New York | KNYC (Central Park) | NWS Daily Climate Report (CLI) |
| San Francisco | KSFO | CLI |
| Miami | KMIA | CLI |
| Chicago | KMDW (Midway) | CLI |
| Los Angeles | KLAX | CLI |

The venue also fixes four things previously guessed at: settlement at **08:00 ET the day following** the contract date; **no data within one week ⇒ settles at last fair-market prices**; measured quantities are **observed high, low and average** temperature; and — confirming a branch v5 listed as unresolved — *"if the CLI reading is inconsistent with the 24-hour METAR observation for the same location, settlement may be delayed until 11:00 AM ET for review."* **08:00 ET is therefore not the only settlement instant**: a CLI/METAR disagreement opens a review window to 11:00 ET, which is exactly the interval in which our own CLI-vs-METAR conflict rule (§4.7) must already have blocked trading. Per-site CLI product ids are published as `CLINYC`/`CLISFO`/`CLIMIA`/`CLIMDW`/`CLILAX`.

**The guard that matters.** A single WFO issues CLI products for multiple cities, and this is now empirically confirmed for **every** one of our five sites: KOKX issues NYC+JFK+LGA+EWR; KLOT issues MDW+ORD; KLOX issues LAX+BUR+LGB; KMTR issues SFO+OAK+SJC; KMFL issues MIA+FLL+APF — identical `issuingOffice` in every case. **Office matching is worthless.** Binding requires **CLI-location id + a per-city product-body header regex** (`THE CENTRAL PARK NY CLIMATE SUMMARY`, `THE CHICAGO-MIDWAY CLIMATE SUMMARY`, …). That body assertion is the only check that catches a KOKX product that is silently JFK.

The CLI id is **not** derivable by stripping `K` from the ICAO — KNYC is a Central Park COOP site, not an airport. It is also **not** the AWIPS PIL: the `/locations/{loc}` path segment is `NYC`/`MDW`, while `CLINYC` is the PIL appearing on line 3 of the product text. Conflating the two is a live defect in the `polymarket-us-integration` skill. Store the tuple explicitly; never derive.

Each `body_header_regex` in the registry is machine-checked against a real multi-city corpus to match only its own site. The counterexample worth remembering: `^\.\.\.THE\s+CHICAGO.*CLIMATE\s+SUMMARY` matches **both** Midway and O'Hare. Patterns also need `\s+` tolerance — the observed Burbank header contains a double space. A startup liveness assertion refuses to trade a market whose live `issuingOffice`/header does not match, and a weekly drift job re-verifies.

**Registry keying.** `sites.toml` is keyed `(venue, city)` — e.g. `[sites.polymarket_us.NYC]` — from day one, though only one venue exists today. Keying on city alone forces a painful migration of every persisted record when Kalshi arrives. This is cheap now and expensive later.

### 2.3 Polling — native primitives only

`Clock.set_timer` for cadence (defined once on base `Clock`, so `TestClock` and `LiveClock` behave identically and cadence is replayable — verified); `live/retry.py`'s `get_exponential_backoff(..., jitter=True)` + `RetryManager` for retries. Transport is `httpx` (§6). v1 hand-rolled all three — a prime-directive violation caught in review.

### 2.4 Classification — pure and clock-free

**Corrected against a live 20-product corpus (2026-08-22).** Earlier versions of this plan — and the `nws-cli-settlement` skill — asserted that a final CLI reads `CLIMATE REPORT FOR <yesterday>` while a preliminary reads `CLIMATE SUMMARY`. **That is false.** Both issuances read `...THE <SITE> CLIMATE SUMMARY FOR <DATE>...`. The discriminator is a separate line: the **preliminary carries `VALID TODAY AS OF 0400 PM LOCAL TIME.`** and the final does not.

**Refined again during Phase 1, against the captured real pair.** `REPORT` vs `SUMMARY` does not discriminate *at all*, because **both strings appear in both products** in different positions: the top masthead reads `CLIMATE REPORT` in each, and the headline sentence reads `CLIMATE SUMMARY` in each. Code keying on the masthead would therefore misparse *both* issuances identically rather than merely misclassifying one — a worse failure, because it looks like a parser bug rather than a settlement bug.

Classification therefore keys on **(the presence/absence of that `VALID TODAY AS OF …` line, plus the headline `summary_date`)** — never on `issuanceTime`, and never on `REPORT` vs `SUMMARY` wording. This is the single highest-consequence parsing rule in the system: misreading a preliminary as final settles on a value NWS has not finalized. Test #1 (`test_preliminary_cli_is_not_settlement_grade`) pins it against real fixtures of both issuances for the same day.

Classification predicates are pure functions with no clock access, so they behave identically live and in replay.

### 2.5 Parsing — deliberate deviation, decided in Phase 1

**Earlier versions mandated pyIEM. Phase 1 reverses that: `normalize/cli_parse.py` is our own parser, and pyIEM is an optional `backfill` extra only.** This is a conscious deviation, recorded here so it is not mistaken for an oversight.

The reasoning, weighed against a review that flagged the deviation as HIGH:

- pyIEM pulls a 48-package dependency tree with two undeclared imports, and `pyiem.parser()` **opens a live PostgreSQL connection** on its default construction path — in a module that must stay pure and import-safe.
- It is regex-heavy fixed-width parsing, so it carries the ReDoS exposure that motivated the `ProcessPoolExecutor` containment in §6. A security review measured our own patterns as free of catastrophic-backtracking shapes.
- Our parser fails **closed**: every ambiguity raises `CliParseError` before any partially-populated result can be constructed, at 100% branch coverage.

**The reviewer's underlying point stood, and was the real risk: the regexes had been validated against one NWS office (KOKX).** That was answered with evidence rather than argument.

**Result (executed):** real CLI products were captured for all five cities across five different WFOs — KOKX, KMTR, KMFL, KLOT, KLOX — and **all four new offices parsed cleanly on the first run with no code change**. Every office renders the `...THE <SITE> CLIMATE SUMMARY FOR <DATE>...` headline and the `TEMPERATURE (F)` → `YESTERDAY` → `MAXIMUM`/`MINIMUM`/`AVERAGE` → blank → `PRECIPITATION (IN)` structure identically. The only cross-office variance observed is the observed-time column format (`2:19 PM` at KMTR/KLOX/KMFL vs `301 PM` at KOKX), which the parser never reads. A cross-city rejection matrix additionally proves each site's `body_header_regex` — read from `sites.toml`, not copied — rejects every sibling's real header.

**If a future office renders the temperature block in a way the parser cannot handle, that finding — not the abstract argument — reopens the pyIEM decision.**

Two parsing rules that are load-bearing regardless of parser:
- The structural allowlist (line count/length, WMO header shape, AWIPS PIL == `CLI{loc}`, body-header regex) is applied **before** the parser sees the text.
- Temperature extraction is anchored to the **`YESTERDAY` subsection**. The `TEMPERATURE (F)` block also contains `NORMAL` and `RECORD` subsections with their own `MAXIMUM`/`MINIMUM` lines; a first-match-in-block search would silently return a record high as the observed high — a mis-parse rather than a rejection, and a wrong settlement.

### 2.6 Normalization

Climate day is a **fixed standard-time UTC offset year-round** (`timezone(timedelta(minutes=std_offset))`), never `ZoneInfo` — DST aliasing would silently shift the window and settle the wrong day. Units are stored as published (°F integers for CLI); no conversion happens on the settlement path. Missing values use nullable columns plus a sentinel-kind flag (`M`/`T`/`MS`/`MB`), never an imputed number.

---

## 3. Open-Meteo enrichment design (Phase 3)

Designed now, built after the NWS slice replays clean. **Free tier, no API key, 10,000 calls/day** (operator decision 3).

### 3.1 Endpoints and roles

| Endpoint | Role | Grade |
|---|---|---|
| `/v1/forecast` (hourly `temperature_2m`, `precipitation`, `snowfall`; `timezone=GMT`; ECMWF IFS + GFS + ICON, +HRRR ≤18 h) | live near-term signal | ENRICHMENT |
| `/v1/ensemble` (GEFS, ECMWF-EPS members) | spread as an uncertainty proxy | ENRICHMENT |
| `/v1/previous-runs` (`{var}_previous_dayN`) | **the backtest source** | ENRICHMENT |
| `/v1/archive` (ERA5) | climatology prior only | ENRICHMENT |

No Open-Meteo variable is ever settlement-grade. Verify un-keyed free-tier availability of previous-runs and ensemble before Phase 3 commits to them.

**Never consume Open-Meteo daily aggregates for any variable.** Its daily buckets are local-wall-clock-anchored with a fixed 24 h stride and a known unfixed DST defect (issue #488), so they would silently disagree with settlement. We bucket hourly ourselves using the **same** `climate_day.py` function as NWS — one bucketing rule, not two.

**Backtest source selection.** Historical Forecast is **banned**: it stitches each run's first few hours, so a value at T came from a run initialized 0–5 h before T ≈ 24 h lookahead. Previous Runs anchors on *valid* time and is the backtest source (archive from Jan 2024, N≤7). Budget a ~6 h publication lag — a run does not publish until well after init.

### 3.2 Join without equivalence

Key `(site_id, target_climate_day_epoch)` is a **coordination key, not an equivalence claim**. Grid ≠ station is large: GFS ~25 km, HRRR ~3 km, and the 90 m DEM downscaling corrects elevation, not urban heat island or siting. KNYC is famously unrepresentative of its cell; expect 1–3 °C systematic Tmax bias. Learned per-site walk-forward from **settled** pairs, that bias is where the edge actually is — which is precisely why Open-Meteo is a feature and never a settlement value.

Binding lives in a namespaced `[sites.polymarket_us.NYC.open_meteo]` sub-table with `lat`, `lon`, `elevation_m` and an explicit `settlement_eligible = false`, so no code path reads enrichment coordinates through the settlement accessor.

**Open-Meteo is named explicitly in the banned-substitute list (§6).** It is the most tempting fallback — always available, never reports "missing" — and the furthest from the settlement site.

### 3.3 Revisions — append-only

Identity key `(model, init_time_ns, valid_time_ns, variable, site_id)`. A later harvest returning a different value for the same key is a **CRIT data-quality alarm, appended, never an overwrite**. (Whether Previous Runs values are ever restated is empirically unresolved — the design assumes the worst case.) `ts_event = init_time_ns`; `ts_init = retrieved_at_ns`.

Point-in-time correctness requires **two** filters at query time: `init_time_ns ≤ T` (the run existed) **and** `retrieved_at_ns ≤ T − publication_lag` (we could actually have had it).

### 3.4 Isolation

A separate `open_meteo_gate` (OPEN/DEGRADED/BLOCKED) with its own supervised task, with **no wiring path into `resolve_settlement`'s gate check**. This Actor-level separation is the mechanism that makes "Open-Meteo outage ⇒ settlement unaffected" enforced rather than merely asserted. Cadence: hourly forecast poll ×5 cities ≈ 120 calls/day, well inside the 10k limit; previous-runs and ensemble on a daily batch. No conditional-GET equivalent exists, so cache by content-hash-before-insert.

### 3.5 Features

`features/openmeteo_features.py` (pure): inter-model and ensemble-member spread as an uncertainty proxy; lead-time-bucketed forecast-vs-CLI bias learned walk-forward from **settled pairs only**. Consumed by the future strategy layer, never by `settlement/`.

---

## 4. Data normalization and provenance model

### 4.1 Records — hand-written classes with explicit Arrow schemas

**The pattern is a plain `Data` subclass** with hand-written `__init__`, `ts_event`/`ts_init` properties, `to_dict`/`from_dict`, a `schema()` classmethod, and **exactly one** `register_arrow(cls, cls.schema(), encoder, decoder)` call at module scope — the in-tree pattern from `adapters/betfair/data_types.py` (six calls at `:738-805`), `databento`, `binance`, `hyperliquid` and `common/signal.py`.

**Not `@customdataclass`.** We require a decoder that **raises on missing columns**, and the decorator's injected `from_arrow` can never do that — it calls `from_dict`, which passes missing keys through as dataclass defaults. Betfair is the in-tree precedent for "the decorator cannot express what this type needs." Since we must override that behaviour anyway, hand-writing the class is *fewer* moving parts.

Two rejected predecessors, recorded so they are not reinvented: the decorator plus a private `_schema` class attribute was ruled a **bypass** (underscore-private, its enabling guard at `model/custom.py:157` covered by no docstring, test or adapter, and no class in the package hand-writes it); a second `register_arrow` layered over the decorator's own registration was ruled a bypass of framework-owned global state, and silently diverges (the second call wins in `_SCHEMAS` but leaves `cls._schema` unchanged, while `to_arrow` reads `cls._schema`).

**Because we hand-write the class, the decorator's constraints do not apply to us.** `frozen=True` breakage, the PEP 563 ban, the no-inheritance rule, unusable `NewType` ids and mypy-blind constructors are **decorator artifacts, not platform limits**. They remain documented in the `nautilus-trader-patterns` skill as hazards for anyone who reaches for the decorator, and the contract-test suite pins them there — but no Breezy record class is subject to them.

Consequences for the data model:

- **Missing values** use genuinely nullable Arrow columns plus a `*_flag` string column for the sentinel kind. No `missing_mask` bitfield; no "annotate `float`, pass `None`" lie that the type-checker would enforce against us.
- **Schema evolution** is guarded by our own strict decoder. Drift is otherwise **silent and non-deterministic** — pyarrow infers the schema from the first fragment only and whichever fragment sorts first wins: new-schema-last silently overwrites new data with defaults, new-schema-first injects `None` past a dataclass default. The strict decoder converts silent corruption into a loud failure.
- **`catalog.custom_data(...)` returns `CustomData` wrapper objects, not raw instances** — callers unwrap `.data`. Its parameter is `cls`, **not** `data_cls` (`catalog/base.py:202`), and `as_nautilus=True` double-wraps because `query` already wraps custom classes.
- **Arrow `nullable=False` is not enforced on write** (executed): `pa.RecordBatch.from_pylist([{"v": 1}], schema=<d not null, v>)` yields `{"d": None, "v": 1}` with no error, and extra keys are dropped silently. Our encoder validates the dict itself rather than trusting the schema to reject it.
- **The bundled `dicts_to_record_batch` swallows every exception** (prints and returns `None`), turning a decode failure into an opaque assertion. Not used.

**Known limitation — strict decoding is one-sided, but narrower than first measured.** The strict decoder compares the *unified dataset* schema, which pyarrow infers from the first/oldest fragment, against the registered schema. Both real version-drift directions are caught. A **later** divergent fragment while the first still matches was initially found to coerce silently to NULL.

Adding `tavg_flag` (§4.1 record content) unexpectedly closed most of that hole, because the paired value/flag invariant is itself a detector. Re-measured on the pinned install for a later-fragment divergence:

| Dropped column | Outcome |
|---|---|
| `tavg_f` | **Caught** — `ValueError: tavg_f is missing, so tavg_flag must name the sentinel kind` |
| `source_channel`, `is_final` (non-null) | **Caught** — field guards raise `TypeError` |
| `tavg_flag` while its value is present | **Undetected**, coerced to `None` |

The residual hole is therefore only a nullable `*_flag` column dropped alongside a present value — and that state is unreachable through our own strict encoder. All three cases are pinned in `test_drift_detection_is_one_sided_when_the_first_fragment_matches`. A per-record `schema_version` assertion or a periodic catalog-wide schema audit would close it entirely; that remains Phase 2 work, now at lower priority.

**Verified on 1.231.0 by execution:** a hand-written `Data` subclass with `date32` and nullable `int64` round-trips construct → `to_dict` → `to_arrow` → `write_data` → `query` → `from_arrow` with values and nulls intact, with zero private-API surface.

**Do not switch to the pyo3 catalog** despite its immunity to drift: its on-disk layout is incompatible with the Python catalog's, which reads **0 records** from a pyo3-written catalog — and since `BacktestNode.load_catalog` builds the Python catalog, adopting pyo3 forfeits `BacktestDataConfig` replay.

**Record content.** `NwsClimateDay`: `station, climate_day, tmax_f, tmin_f, tavg_f, tmax_flag, tmin_flag, is_final, correction_flag, revision_seq, is_superseded, issuing_office, issuance_time_ns, retrieved_at_ns, parser_version, registry_version, raw_sha256, source_channel, schema_version`. `NwsRawProduct`: the full provenance set plus verbatim `raw_text`, `raw_sha256`, `response_sha256`.

### 4.2 Timestamps

- **`ts_init` = `retrieved_at_ns`** — when *Breezy* received and validated it, stamped once and propagated, never re-stamped from `clock.now()`. Replay order then equals real arrival order. Not issuance time: if we are down and fetch late, issuance time lets the backtest know things before we did.
- **`ts_event` = semantic instant.** Finals: end of climate day (LST). **Preliminaries: issuance time.** The `ts_event ≤ ts_init` invariant is scoped to finals and contract-tested there. **Corrected justification (Phase 1):** earlier text claimed the invariant is *violated* by preliminaries — it is not, since under the issuance-time rule above it holds for them too. The real reason to scope it is that the **type must not enforce it globally**, because a preliminary carrying a climate-day-end `ts_event` would violate it, and the record class must be able to represent that rather than reject it at construction.
- Forecasts: `ts_event` = model **run** time; the target day is a separate field.
- **Banned:** `use_ts_event_for_ts_init=True` on any read path.

### 4.3 Corrections and revisions — one rule

**Corrections are new records with a strictly later `ts_init`. Never a rewrite.** The settlement reader selects **max-`ts_init` per `(cli_location, summary_date)`**.

This is the only revision rule, and it exists because the alternatives are broken, not merely inelegant. The catalog **silently discards** a re-write whose computed filename already exists — `parquet.py:379` prints a bare message and returns normally, with no exception and no logger. `delete_data_range` **no-ops** for an identifier-less custom type (it substring-matches `"/data/<name>/"`, which a flat directory never contains). A *partial* overlap raises, so the catalog is loud about overlap and silent about exact re-write — precisely our case. The previously-proposed `delete_data_range + skip_disjoint_check` path and the "rewrite loop" are both **deleted from this plan**; the latter also reimplemented Nautilus's private filename/interval scheme (`_make_path`, `_timestamps_to_filename`).

Where a genuine bulk migration is ever needed, it goes through public APIs only: `catalog.custom_data(...)` to read → transform → `write_data` into a **fresh catalog** → directory swap. Never construct a filename or path.

**Auto-adoption (operator decision 6).** A correction requires a **new product id from the authoritative list plus correction evidence** (`CCA|CCB|CORRECTED|CORRECTION`). It is then adopted automatically — truth and calibration update with no human in the loop. Sanity bounds still reject physically impossible values as bad data. Same product id returning a different `sha256` is a **CRIT integrity event**, not a revision.

**After venue settlement:** truth updates, but **venue P&L is immutable** — persist `outcome_venue` and `outcome_truth` separately. P&L uses venue; calibration uses truth.

### 4.4 As-of queries

`settlement/resolver.py` exposes an explicit `as_of_ts_init` bound. Replay achieves point-in-time correctness implicitly (Nautilus delivers in `ts_init` order and a strategy only sees `ts_init ≤ T`), but post-hoc audit — *"what would the resolver have returned at 07:55 ET on day X"* — needs it as a first-class queryable capability rather than a full replay run. A test asserts the as-of path and live replay agree.

### 4.5 Provenance integrity

`sha256(raw_text)` alone is circular — we compute it, store it, and it is part of the dedupe key. Required: an **append-only hash-chained ledger** where each entry covers `(prev_entry_digest, response_sha256, raw_sha256, retrieved_at_ns)`, with the daily chain head anchored to an independent append-only destination — tamper-*evidence*, not merely resistance. (Scope note: the null-hypothesis test has not been applied to this component; before building it, confirm no native or off-the-shelf facility covers it.)

**Raw text lives in the catalog as `NwsRawProduct`, not only on the filesystem.** Verifying a digest against a filesystem side-channel that does not exist during replay would break live/backtest parity at the single most safety-critical predicate. The filesystem store remains a backup; the verification path reads the catalog.

Path components derive **only** from the registry object and a typed date, never from parsed text — interpolating an extracted `cli_location` into a path is a path-traversal write primitive.

### 4.6 Contamination barrier — honestly scoped

This is strong discipline plus real tests, **not a proof**. A future "fall back to a model value when the CLI is absent" branch could legitimately import both islands and pass every structural layer; and an NWS-only backtest cannot detect it, because with no Open-Meteo data the branch is dead code and the regression stays green.

1. Separate types, disjoint field names and units (`tmax_f: int` vs `model_tmax_c: float`).
2. **Disjoint catalog roots**: `data/nws/<site>/` vs `data/enrichment/open_meteo/<site>/`, asserted disjoint by test.
3. An `import-linter` **layers/independence** contract — transitive, not a direct-import ban. A direct ban only catches `settlement → domain.openmeteo_*`; a transitive contract also catches a laundering module three hops away.
4. `resolve_settlement(...)` cannot *name* an Open-Meteo type. `ClimateDayReading` carries `source_grade: Literal["SETTLEMENT"]`, set only by `ClimateDayReading.from_nws(...)`. This is visibility, not an unforgeable token — the reading is still constructible directly, and honesty about that is the point.
5. **The test that actually matters:** run the *degraded* path **with Open-Meteo data present** and assert no position action results.

### 4.7 Conflict resolution

| Pair | Winner | Blocks trading? |
|---|---|---|
| CLI vs METAR (Δ≥1 °F) | CLI | Yes — the venue delays settlement to 11:00 ET for review; we block for the whole window |
| CLI rev N vs N+1 | N+1 | Yes, until re-derivation |
| CLI vs ACIS (Δ≥1 °F) | CLI | **Yes — halt that station, auto-resume on agreement** |
| CLI vs Open-Meteo | CLI, always | No (divergence expected) |
| Cross-check **unavailable** | — | DEGRADED; BLOCKED inside the conflict window |

---

## 5. NautilusTrader integration approach

**Ingestion is Actor-only.** v5's §12 concluded "`LiveDataClient` fetches, `Actor` derives," but that is a non-sequitur from its own evidence: with a catalog registered and `update_catalog=False` (the default), the engine serves a data request **directly from the catalog with no client at all** (`data/engine.pyx:2005-2009`). Phase 1 therefore needs no client — the Actor fetches from NWS itself and calls `write_data` explicitly, and warm start reads back through `request_data`. Per the prime directive (smallest correct native extension), Actor-only stands. Revisit only if `update_catalog=True` is ever genuinely needed — that flag *bypasses* the catalog and routes to a client, so it is a fetch-and-persist path requiring a client to exist, not the free backfill-persistence it was once described as.

In-tree precedent for Actor-as-ingest: `persistence/loaders.py:190 InterestRateProvider` polls an external OECD feed, publishes custom data, and reschedules with `set_time_alert`.

- **Publishing:** payloads MUST be wrapped — `CustomData(DataType(NwsClimateDay, {...}), rec)`. `data/engine.pyx:2541-2573` dispatches on concrete type; anything not `CustomData` is **logged and dropped**.
- **Topics** are built from `DataType` metadata and matched by msgbus **glob**, and routing is fragile in three ways: a metadata-bearing subscriber never receives a metadata-less publication; metadata **key order** changes the topic string while `DataType.__eq__` uses a frozenset and compares **equal** (so equality-based tests pass while production silently never delivers); and a `DataType(WeatherObs)` subscriber matches `WeatherObsHourly` by prefix. Mitigations: **one shared `DataType` factory per type**, `isinstance` checks in every handler, and no class named as a prefix of another.
- **Backtest replay of custom data works — executed end-to-end.** `BacktestDataConfig(data_cls=…, client_id=…)` streams registered custom types. Three requirements: **`client_id` is mandatory** (`node.py:728-730` raises `ValueError` without it); `data_cls` needs the **colon** form `"pkg.module:Class"` (`resolve_path` does `rsplit(":")`; the v1.231.0 docs' own dotted example at `concepts/data/index.md:947` is a doc bug — use `Data.fully_qualified_name()`, which returns the colon form natively); and `metadata` must be a literal dict, since a callable fails to msgspec-encode when `BacktestRunConfig(...).id` is computed. Field names are `start_time`/`end_time`, not `start`/`end`; `add_data` has no `venue` parameter.
- **Metadata does not select data.** Two configs differing only by metadata replay every row twice. `write_data(..., identifier=...)` is silently ignored for a custom type with no `instrument_id`, and `query(..., identifiers=[...])` returns empty. **Per-station separation uses one catalog root per station** — which means warm start, the write path and the exit test all need explicit N-catalog wiring. This is a load-bearing abstraction and Phase 1 must design it, not assume it.
- **Catalog:** `write_data(list[Data], …)`; there is no `write(data_type=, df=)`. Records must be non-decreasing in `ts_init`. The **silent write-skip** (§4.3) means a successful return does not mean data was written — the ingest path checks explicitly.
- **Live custom data is not auto-persisted** — `_handle_custom_data` has no `update_catalog` branch. The Actor writes to the catalog explicitly.
- **Warm start:** `Actor.request_data(...)` → catalog. Responses publish on **`historical.data.…`** and land in **`on_historical_data`**, not `on_data`.
- **Restart state:** `Actor.on_save()`/`on_load()` plus `Cache.add(str, bytes)`/`Cache.get(str)`. **This requires all three of `save_state=True`, `load_state=True` and `CacheConfig.database` set** — with the default `database=None`, `on_save` is **never called and no error is raised**. The gate's persistence is therefore a deployment requirement, needing an explicit startup config assertion plus a test that fails when `database` is unset.
- **Blocking work uses the native executor.** `Actor.register_executor(loop, executor)` accepts any `concurrent.futures.Executor`; `run_in_executor` executes **inline** when none is registered (`actor.pyx:1091-1093`), so backtests stay deterministic. A privately-held side-car pool is *not* the native route. `ProcessPoolExecutor` requires picklable callables, so the parse entry point is a module-level function over `str`, never a bound method over a Nautilus object.
- **Streaming replay (`chunk_size`) is UNVERIFIED for our pattern.** v5 reported it raises `RuntimeError` for Cython `@customdataclass` types lacking `ts_init` in the Arrow schema — but our hand-written class registers `ts_init` explicitly, and a verification pass could not reproduce the error signature in this install. A **one-shot** backtest was executed successfully. Treat one-shot as the working assumption and **re-verify `chunk_size` against the real record class before Phase 1 exit**; if it genuinely fails, replay size is capped by memory and that must be stated as a known limit.

**What we genuinely build** (each confirmed absent from Nautilus): settlement classification, station binding, revision/supersession, and source precedence. Nautilus has no generic revision mechanism (`is_revision` is Bar-only), no provenance fields on `Data`, no conflict arbitration, and no custom-data quality gating (`validate_data_sequence` covers core types only). That is the complete build list.

---

## 6. Reliability and data-quality controls

Governing rule: **enrichment degrades, settlement halts.**

**Gate.** Per-site `OPEN/DEGRADED/BLOCKED`, **persisted** and reloaded at startup, **defaulting to BLOCKED** until a successful verified poll (holding it in memory with no initial value lets a crash-loop launder every halt). Poll tasks are supervised (`add_done_callback` ⇒ BLOCKED + CRIT) with an independent freshness watchdog, and `resolve_settlement()` re-checks the gate **at use time**. Persistence depends on the cache-database config above.

| Failure | Behaviour |
|---|---|
| 403 | disambiguate UA-trap vs abuse-block; UA-trap ⇒ CRIT + BLOCK all; abuse ⇒ hard backoff + DEGRADED |
| 400 | no retry; CRIT; code defect |
| 429/5xx/timeout | backoff + quota; DEGRADED after 3; BLOCKED if the final window elapses |
| redirect (3xx) | CRIT integrity alarm — **redirects disabled** |
| oversize body / parse timeout | reject before parse / REJECTED + BLOCKED |
| malformed text, parser exception | REJECTED, raw retained; CRIT; BLOCK site |
| sanity-bound violation | REJECTED; CRIT; ACIS cross-check |
| ambiguous headline | AMBIGUOUS; CRIT; BLOCK site |
| late final CLI | WARN 06:00 / CRIT 07:30; DEGRADED → BLOCKED at 08:00 ET settlement (11:00 ET if the venue's METAR-review branch opens) |
| absent final (the 2025 shutdown ran 43 days) | BLOCKED; hand to the venue's 7-day last-fair-price fallback; **never** substitute METAR, ACIS **or Open-Meteo** |
| cross-check unavailable | DEGRADED; BLOCKED inside the conflict window |
| ingest task death | BLOCKED + CRIT |
| clock skew \|host − NWS Date\| > 5 s | alarm; monotonic time for intervals |
| Open-Meteo outage | features absent; settlement unaffected (separate gate, §3.4) |

**Transport — `httpx` for weather, `HttpClient` for venue traffic** (operator decision 8). Required controls: https-only + host allowlist; TLS verify always on, min TLS 1.2; **redirects disabled**; explicit no-proxy plus a startup assertion that `HTTP(S)_PROXY`/`SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`/`SSLKEYLOGFILE` are unset-or-approved; and a body-size cap applied *before* decompression completes.

`nautilus_pyo3.HttpClient` cannot honour these, verified: its constructor is exactly `(default_headers, header_keys, keyed_quotas, default_quota, timeout_secs, proxy_url)` — `max_redirects=0` raises `TypeError`; there is no TLS-version control and no `verify` flag; `HttpResponse` is fully buffered with no streaming interface, so a pre-decompression size cap is impossible; its underlying reqwest client *follows* redirects by default, making the 3xx alarm unobservable; and `header_keys` is a **response**-header allowlist defaulting to empty, so `Retry-After` and `X-RateLimit-*` are unreadable unless named at construction — silently defeating the backoff behaviour the docs themselves ask for.

This bypasses nothing: Nautilus does not own outbound HTTP for third-party data sources, `HttpClient` is described only as what an adapter *"typically comprises"*, and there are zero references to any HTTP library across the 1.231.0 doc tree. We still use `Clock` scheduling, `live/retry.py` backoff, and `Actor` for everything else. Venue traffic keeps `HttpClient`, where its keyed rate-limiter is the sanctioned mechanism. A side benefit: `httpx` *is* the injectable seam, restoring `respx`-based transport testing that a compiled Rust type makes impossible.

**Other controls.** 128 KiB body cap before decompression completes (real CLI products <64 KiB); `Accept-Encoding: identity` or a decompressed ceiling; strict UTF-8 (`errors="replace"` would silently mutate the settlement datum *and* its digest); JSON size/depth caps. Parser containment: structural allowlist before pyIEM, parsed in a `ProcessPoolExecutor` with a 5 s kill and `RLIMIT_AS`/`RLIMIT_CPU` — pyIEM is regex-heavy fixed-width parsing, and a ReDoS inside the asyncio task would stall the **entire Nautilus event loop**. Cache: conditional GET only on the discovery list; `/products/{id}` bodies are immutable by id, so never revalidate them. Secrets/PII: User-Agent from env, a **role mailbox** (`breezy-data@gopoint.com`) not a personal address, since it lands in every fixture and log line; `redact_url()` at the transport boundary; URLs never used as metric labels; gitleaks over `tests/fixtures/`, `docs/`, `.claude/`. Supply chain: exact `==` pins and **`nautilus-trader~=1.231`** (corrected in Phase 0 from `>=1.231.0`, which silently permitted a resolver upgrade that would invalidate every contract test); committed hashed lockfile; `uv sync --locked`; `pip-audit` gate; on any parser-dependency bump, re-parse the full fixture corpus and **fail on any diff to a previously settled value**.

**Observability.** Metrics `nws.http.{requests,retries,conditional_hit_ratio}`, `nws.cli.{ingested,parse_failures,sanity_violations,final_latency,final_missing,revisions}`, `nws.acis.mismatch`, `nws.gate.state`, `open_meteo.gate.state`. Alerts `CliFinalOverdue`, `NwsForbidden403`, `ParserFailure`, `SanityBoundViolation`, `StationBindingViolation`, `AcisDisagreement`, `PostSettlementRevision`, `GateBlocked`, `IntegrityViolation`. Every settlement-touching log line carries `product_uuid, site_id, cli_location, issuing_office, climate_day, issuance_time, retrieved_at, sha256[:12], revision_seq, is_final, correction_flag, state, parser_version, registry_version`.

**Retention.** Deferred by operator decision 4. Raw products carry digests in the catalog from day one, so a 7-year WORM regime remains addable later without migration.

---

## 7. Testing strategy

**Stack:** `pytest`, `pytest-asyncio` (strict), `pytest-cov`, `hypothesis` (narrow), `pytest-randomly`, `import-linter`, `mypy`, `ruff`, **`respx`** (viable now that weather transport is `httpx`). **Rejected:** `freezegun`/`time-machine` — Nautilus ships `TestClock`, and monkeypatching global time would hide the missing injectable-clock seam.

**mypy scope (widened in Phase 1).** `--strict` now covers `normalize/`, `registry/`, `settlement/`, `features/`, **`domain/` and `ingest/`** — 17 source files, clean. Earlier versions claimed `domain/` was unreachable because only 4 `.pyi` stubs ship and the Cython modules are unstubbed. In practice that produces exactly **two** errors, both `Class cannot subclass "Data" (has type "Any")`. The fix is a narrow per-module waiver of `disallow_subclassing_any` for `breezy.domain.*` plus `ignore_missing_imports` for `pyarrow.*`/`nautilus_trader.*` — every other strict check still applies there. Do not widen those waivers.

**Fixtures:** verbatim body + `meta.json` (url, allowlisted headers, status, `captured_at`, `sha256_body`) + hand-verified `expected.json`; `test_fixture_integrity` recomputes every digest. Corpus: CLI preliminary, final, **CCA correction**, multi-station, M/T/MS/MB sentinels, time-format variants, 403/503/400/429, METAR with null `maxTemperatureLast24Hours`, ACIS normal + future-date `M`, Open-Meteo forecast/previous-runs/error. No test touches the network (autouse socket-blocking fixture).

**Contract tests** (run first on any version bump) pin every executed behaviour: `ts_init` sorting and non-monotonic rejection; `client_id` required when `instrument_id` is None; `resolve_path` colon requirement; `start_time`/`end_time` field names; explicit-schema round-trip including nullable and `date32`; schema-drift detection; the silent write-skip; `CustomData` unwrapping; `DataType` frozenset-equality vs topic key-order; metadata-does-not-filter; `on_save` inert without a cache database; `HttpClient` constructor shape; `test_pyiem_parse_opens_no_socket`; a `__version__` canary. Decorator-specific behaviours (`frozen=True` raises, PEP 563 breaks it, no inheritance, `NewType` unusable) are pinned as **hazard documentation for the skill**, not as constraints on our record classes.

**The tests to write first:**

1. `test_preliminary_cli_is_not_settlement_grade`
2. `test_summary_date_from_headline_not_issuance_time`
3. `test_climate_day_uses_local_standard_time_year_round` — across DST transitions, all five cities
4. `test_station_binding_rejects_nearby_station` — KNYC≠KLGA/KJFK/KEWR, KMDW≠KORD
5. `test_cli_body_header_must_match_expected_site` — the KOKX-issues-four-CLIs guard
6. `test_monthly_clm_product_is_rejected_not_merely_unfetched`
7. `test_dedupe_key_is_not_uuid`
8. `test_correction_after_settlement_supersedes_via_later_ts_init`
9. `test_delete_data_range_is_never_relied_upon`
10. `test_settlement_requires_verified_digest_from_catalog` — not from the filesystem
11. `test_explicit_arrow_schema_roundtrips_nullable_fields`
12. `test_schema_drift_is_detected_not_silently_defaulted`
13. `test_rewrite_of_same_timestamp_range_is_not_silently_skipped`
14. `test_as_of_resolver_agrees_with_live_replay`
15. `test_settlement_has_zero_transitive_import_of_open_meteo` (import-linter)
16. `test_open_meteo_catalog_root_disjoint_from_nws_catalog_root`
17. `test_degraded_path_with_open_meteo_present_takes_no_position`

**Replay/parity:** identical features live vs backtest; no feature at T sees `ts_event > T`; a corrected value does not appear at the original timestamp; live and backtest topic strings byte-identical.

**Coverage:** 90% line / 85% branch global; **100% branch** on classification, resolver, station binding and climate-day math — small, fully enumerable modules where an untaken branch is a silent wrong settlement. Enforced per-module, not as a global average.

---

## 8. Phased implementation plan

**Phase 0 — Correct the record (docs and config only). IN PROGRESS.**
This document (v6). Correct `nautilus-trader-patterns` (the refuted API claims and the added hazards in §4.1/§5). Correct `nws-cli-settlement` (drop Philadelphia; qualify "use pyIEM" with the offline-construction requirement). Correct `polymarket-us-integration` (the wrong WFO identifiers). Replace both prose station tables with `registry/sites.toml`, keyed `(venue, city)`, verified against the live API. Snapshot the venue FAQ verbatim with a digest into `docs/evidence/venue/polymarket_us/` (sha256 `e7a85e6e…`, retrieved 2026-08-22). Fix the `pyproject.toml` pin to `~=1.231`.

**Phase 1 — Minimal vertical slice: NYC only, NWS only, one Actor.**
`sites.toml` (NYC) + the two record types with explicit schemas + pure `normalize/` + one `Actor` that polls via `clock.set_timer`, publishes, persists via `catalog.write_data`, and recovers via `request_data` + `on_save`/`on_load`. Includes the per-station catalog-root wiring design, the cache-database startup assertion, and re-verification of `chunk_size` against the real record class.

**Exit test:** replay the captured corpus through `BacktestNode` using one `BacktestDataConfig` per station **catalog root**, asserting the strategy's `(topic, ts_init, revision_seq, tmax_f)` callback sequence is bit-identical to a live dry run over the same window — including a correction arriving after the initial settlement.

**Phase 2 — Breadth.** The remaining four cities; METAR + ACIS advisory paths; conflict/gate logic; IEM AFOS backfill (api.weather.gov retains ~7 days); full alarm set; the security control checklist.

**Phase 3 — Open-Meteo.** §3 as designed: hourly-UTC ingestion with our own standard-time bucketing, Previous Runs harvesting, ensemble spread, bias features, separate gate, and the contamination tests. Free tier.

**Phase 4 — Signal & execution.** Out of scope; begins only after Phase 1–3 evidence exists. Before any adapter work: **investigate `nautilus_pyo3.polymarket`** — 1.231.0 ships a complete Rust/PyO3 V2 adapter exporting `PolymarketUpDownEventSlugConfig`, native slug-based event configuration we had assumed we would hand-roll. (The legacy Cython `nautilus_trader.adapters.polymarket` does not import — it needs the uninstalled `py_clob_client_v2`.) Also native and not to be hand-rolled: `ProbabilityPriceFeeModel` (`fee = qty · rate · p · (1−p)`, taker-only), `BinaryOption` (notional `qty × p`, multiplier and lot 1), and `pUSD` as a first-class currency. Trap: `AccountType.BETTING` uses decimal-odds math that goes negative below p=1 — use `CASH` + `NETTING`.

Phases 0–2 have **zero venue dependency** — if credentials slip, they still deliver.

---

## 9. Key risks and open items

**Technical risks (ranked):**

1. **`ts_init` semantics drift** — stamping `clock.now()` instead of propagating `retrieved_at_ns` silently destroys replay fidelity, and the backtest returns a plausible, wrong answer.
2. **Topic-metadata divergence** — worsened by `DataType` equality ignoring key order, so a wrong-order subscription looks correct and never fires while equality-based tests pass.
3. **Silent catalog write-skip** — a write whose timestamp range matches an existing filename returns successfully without writing. Mitigated by the append-only correction rule (§4.3) plus an explicit post-write check.
4. **Schema evolution** — non-deterministic (whichever fragment sorts first wins) and undocumented for custom data. Mitigated by explicit nullable schemas plus a decoder that refuses to default missing columns.
5. **Contamination via a well-meaning helper** — defeats the type barrier, and an NWS-only backtest cannot detect it. Only the degraded-path test can.
6. **Settlement-grade misclassification** — rare, invisible in testing (0 corrections in a 200-product sample), expensive in production.
7. **Per-station catalog roots are asserted but not yet designed** — N roots changes warm start, the write path and the exit test. Phase 1 must produce the wiring, not assume it.

**Open, to be resolved by execution (not blocking Phase 0/1):**

- `chunk_size` streaming replay against the real record class (§5).
- Un-keyed free-tier availability of Open-Meteo previous-runs and ensemble endpoints; the `models=` identifier strings (docs conflict); whether Previous Runs values are ever restated.
- Whether `ProbabilityPriceFeeModel` is reachable from a Cython `BacktestVenueConfig` or only the PyO3 backtest node.
- Bucket boundary semantics (`>` vs `≥`) and the precise "last fair-market prices" definition. (The CLI-vs-METAR conflict trigger is now **answered**: the venue delays settlement to 11:00 ET for review — §2.2.) **These are rules-text questions and the resolver's rounding/threshold operators stay explicitly unimplemented until they are answered** (operator decision 9) — guessing them is the failure mode the deferred snapshot mechanism exists to prevent.
- WBAN/GHCN ids beyond KNYC (94728).

**Deferred by operator decision:** WORM storage and the 7-year retention custodian (4); the automated market rules-snapshot mechanism (9); the Polymarket.us KYC/discovery track (7); the Open-Meteo commercial licence (3, revisit before live capital).

**Kalshi forward-compatibility.** Universal (weather layer): the climate-day standard-time rule, prelim/final classification, revision/supersession, provenance, staleness thresholds. Venue-specific (adapter): the station table — already keyed `(venue, city)` — settlement timing, conflict branch, fee formula, tick/min size, rounding and boundary operator. Note that **Kalshi has no native Nautilus support of any kind** (zero symbols in `nautilus_pyo3`, zero mentions across 206 doc pages), so portability rests entirely on our own abstraction. Per YAGNI, no Kalshi-specific code is written now; the `(venue, city)` registry key is the single cheap concession.

---

## 10. Native-extension audit

**Nothing in this plan modifies, patches, or forks NautilusTrader.** No monkeypatching, no vendored source, no writes into site-packages, no unsupported Cython subclassing (`Data` is designed for subclassing).

Native facilities adopted rather than reinvented: `Actor.register_executor`/`run_in_executor`; `Data.fully_qualified_name()` for `data_cls`; `live/retry.py` backoff; `Clock.set_timer`; `Actor.on_save`/`on_load` + `Cache.add`/`get` for restart state; `DataEngine.register_catalog` + `request_data` for warm start; `BacktestDataConfig` custom-data replay; `ProbabilityPriceFeeModel`, `BinaryOption` and `pUSD` at Phase 4.

Confirmed to have no framework analogue, and therefore genuinely ours to build: settlement classification, station binding, revision/supersession, source precedence, and the settlement gate.

One deliberate deviation, operator-approved: **outbound HTTP via `httpx` for weather sources** (§6). Nautilus does not own outbound HTTP for third-party data, so this bypasses nothing.

---

## 11. Revision history

**v1 → v2** (peer review — architecture REJECT, Python/library REJECT, security APPROVE-WITH-CHANGES): five layers → three components; Phase 1 reduced to one Actor; native `Clock`/retry adopted instead of hand-rolled equivalents; gate persisted and defaulting to BLOCKED; raw text moved into the catalog; predicates made pure; `ts_event ≤ ts_init` scoped to finals; full security control set added; Open-Meteo deferred to Phase 3.

**v2 → v3** (operator challenge): the plan had been built on the bare `@customdataclass` decorator and reported its limits as platform limits.

**v3 → v4** (native-extension audit): three v3-introduced defects removed — the `_schema` trick (ruled a bypass), a second `register_arrow` over the decorator's registration (ruled a bypass), and a catalog "rewrite loop" (ruled a reimplementation of private filename/interval logic). Corrected a factual error repeated across versions: `GreeksData` is not a hand-written `register_arrow` exemplar; the v1.231.0 *docs* show it that way but the shipped code does not.

**v4 → v5** (official-documentation review): the pinned docs were vendored and read in full by six parallel reviews, each verifying by execution. Eleven deltas; five invalidated v4 assertions.

**v5 → v6** (4-seam verification + operator decisions): v5's corrections were an appendix, leaving ~12 unreconciled contradictions in the body — an implementer following §8 would have built the rejected design. v6 folds everything into the text and deletes superseded alternatives. Substantive changes beyond reconciliation: the `LiveDataClient` conclusion is **reversed** back to Actor-only (v5 derived it as a non-sequitur from its own evidence); D5's streaming-replay limit is **downgraded to unverified** (it was likely tested against the abandoned decorator type, and could not be reproduced); Philadelphia is **dropped** and the station bindings re-sourced from the venue's own published rules rather than a skill's prose; a `features/` layer is added; the registry is keyed `(venue, city)`; an explicit as-of query is added; Open-Meteo gains a full design (ensemble endpoint, two-filter point-in-time rule, separate gate, disjoint catalog roots, transitive import-linter contract) and is named in the banned-substitute list; `respx` is restored to the test stack; corrections become fully autonomous per operator decision.

---

**Approved 2026-08-22. Phase 0 in progress; no production code until Phase 0 output is reviewed.**
