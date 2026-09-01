# Forecast ingest & vintage layer — Open-Meteo previous-runs (2026-09-01)

**Status:** PLAN, not executed. **Scope:** make a point-in-time-correct forecast
archive available to Nautilus. **Not** strategy, features, backtest, execution,
or sizing.

## 0. Evidence classes

| Class | Status |
|---|---|
| This repo's source | VERIFIED, `file:line` cited, read via codegraph |
| Probe captures under `docs/evidence/open_meteo_*` | VERIFIED as *what the probes recorded* |
| Open-Meteo semantics not covered by a probe | INFERRED — flagged, gated behind I-0 |

**Correction to the commissioning brief (VERIFIED, and confirmed independently
by the coordinator).** "Archive depth confirmed back to 2019" is **NOT** what the
evidence says, and the claim originated as a misread of a 200-OK response that
carried no data.

- `PROBE_REPORT.md:39` — `q3_archive_depth_2019` returned HTTP 200, 5079 bytes.
- `PROBE_REPORT.md:62` — but that step is recorded as *partial*: "2xx, but the
  payload did not carry the datum this step was designed to extract." Same for
  `q3_archive_depth_2024`.
- `PROBE_REPORT.md:61` — only `q3_archive_depth_2022` ANSWERED: rows=168,
  first_time 2022-01-01T00:00, last_time 2022-01-07T23:00.
- `PROBE_REPORT.md:83` — coverage explicitly recorded as NON-CONTIGUOUS and
  "an unexplained gap, not a clearance".
- Bisect probe (`open_meteo_coverage_bisect_probe_2026-08-31T011135Z`):
  2024-01-01 → **0/168 for all four models**; boundary bracketed between
  2023-12-09 (covered) and 2024-01-01 (empty); interior 2022→2023 CONTIGUOUS.
- Same bisect: at 2022-01-01, `ecmwf_ifs025` and `icon_seamless` were **0/168** —
  only `best_match` and `gfs_seamless` carried data. Model coverage is not
  uniform across the span.

**So the usable archive is a span from <=2022 to ~2023-12, PLUS the present,
with an unmeasured hole between.** This is R-2 and it materially bounds what
this plan can deliver. A 200 response is not data — this is the L-8 class of
error and it must not recur: every coverage claim cites a row count, never a
status code.

## 1. Goal / non-goals

**Goal.** Ingest hourly surface forecasts from
`previous-runs-api.open-meteo.com/v1/forecast` for the five registry stations,
storing each value with the instant it was **available** distinct from the
instant it is **about**, such that a consumer physically cannot read a forecast
that post-dates its as-of instant.

**Non-goals.** Choosing variables/predictors (other track). Any strategy,
sizing, backtest or execution design — Nautilus owns those. Touching the
settlement path, the settlement gate, `api.weather.gov`, or the NO-SEND egress
firewall.

**Reality check, carried forward.** A forecast archive cannot produce a
backtest, because prices are forward-only. This layer produces a
**calibration/forecast-error dataset**. Nothing here changes that.

**Transfer risk, added by the coordinator.** The covered span (2022–2023) does
not overlap the price tape (2026, forward-only). A model calibrated on
2022–2023 forecasts is applied to 2026 forecasts produced by NWP systems that
have since been upgraded. That is a real generalization risk, not a data-volume
problem, and it must be stated wherever a calibration number is reported.

## 2. Null hypothesis: what Nautilus already provides (checked, reused)

| Need | Native capability | Verdict |
|---|---|---|
| Custom record type on the data bus | `Data` subclass + `DataType(cls)`; precedent `nws_climate_day_data_type()` `nws_actor.py:381-389` | **REUSE** — one `@lru_cache(maxsize=1)` factory |
| Parquet persistence | `ParquetDataCatalog` (`persistence/catalog.py:200`) | **REUSE**, no wrapper beyond `write_records` (`catalog.py:422`) |
| Arrow (de)serialization | `register_arrow(...)` at module scope; precedent `nws_raw_product.py:332-337` | **REUSE** with `make_strict_encoder`/`make_strict_decoder` (`domain/strict_arrow.py:85,125`) |
| As-of row filtering | Catalog `end=` pushdown filters `ts_init <= end` (`catalog.py:689-691`) | **PARTIAL** — coarse prefilter only; the vintage bound is NOT `ts_init` (§4) |
| Scheduled polling | `Actor` + clock timers; precedent `NwsIngestActor.on_start` `nws_actor.py:594`, `_arm_timers:636` | **REUSE** at I-8 only |
| Hardened HTTP (allowlist/TLS floor/size cap/redirect alarm) | `HttpTransport` (`ingest/http.py:522`); extension precedent `ProbeTransport(HttpTransport)` `probe_transport.py:231` | **REUSE by subclass** |
| Request budgeting | `RequestBudget` at the single `_fetch` chokepoint (`probe_transport.py:366-387`) | **REUSE** |
| "Make the unsafe read inexpressible" | `PartitionedQuoteTapeGaps.__iter__` raises (`persistence/quote_tape_gaps.py:56-61`) | **REUSE the pattern** (§4.3) |

**Genuinely must be built:** the vintage-derivation policy (§4.1), the record
type and Arrow schema, the payload parser, one transport subclass, the as-of
view, and the backfill script. Nothing else.

## 3. Data model

**Tall/long: one row per `(station, model, variable, valid_time,
run_offset_days, archive_fetch_epoch)`.** Wide-per-variable is *unreachable*,
not merely undesirable: `make_strict_decoder` raises `SchemaDriftError` on any
unexpected **or** missing column (`strict_arrow.py:150-158`), and
`register_arrow` permits one registration per class — so an additive column
migration has no path. Tall makes a new variable add **rows**, never columns,
which is what "feature-agnostic" has to mean here.

`OpenMeteoForecastPoint(Data)` — `src/breezy/domain/open_meteo_forecast_point.py`:

| column | Arrow | note |
|---|---|---|
| `station` | string, req | registry city key; pinned by `registry_version` |
| `model` | string, req | VERIFIED accepted: `best_match`, `ecmwf_ifs025`, `gfs_seamless`, `icon_seamless`, `meteofrance_seamless` (`PROBE_REPORT.md:66`). Coverage per model is NOT uniform — see §0 |
| `variable` | string, req | base name as returned; never interpreted here |
| `value` | float64, **nullable** | null is meaningful: the archive's coverage hole (R-2), never a defect to repair |
| `unit` | string, req | verbatim from `hourly_units` |
| `valid_time_ns` | int64, req | == `ts_event` |
| `run_offset_days` | int64, req | 0 = current run; 1..7 = `_previous_dayN` (max 7 VERIFIED `:59`) |
| `available_at_ns` | int64, req | **the vintage bound** (§4.1) |
| `vintage_policy_version` | string, req | a change of assumption is visible *in the data* |
| `lead_time_ns` | int64, req | one canonical helper, never re-derived |
| `retrieved_at_ns` | int64, req | == `ts_init` |
| `archive_fetch_epoch` | string, req | backfill-run id; two fetches of the same history stay distinguishable |
| `capture_mode` | string, req | `live` \| `archive_backfill` |
| `grid_lat_deg`,`grid_lon_deg`,`grid_elevation_m` | float64, req | as **returned** — a silent grid move must be detectable |
| `request_sha256`,`response_sha256` | string, req | makes the restatement diff computable from the catalog alone |
| `source_channel`,`registry_version`,`parser_version`,`schema_version` | | precedent `nws_climate_day.py:329-351` |
| `ts_event`,`ts_init` | int64, req | `ts_event == valid_time_ns`; `ts_init == retrieved_at_ns`, re-checked in `from_dict` as `nws_raw_product.py:275-279` |

## 4. Vintage semantics — the hard requirement

### 4.1 Two clocks, and the min-of-upper-bounds rule

`ts_init = retrieved_at_ns` is preserved unchanged. It is **provenance**, not
vintage: a 2022 forecast backfilled in 2026 honestly has `ts_init` in 2026.
Stamping a backdated `ts_init` is exactly what the evidence README forbids.

`available_at_ns` is a **separate, first-class column** and the only legal
as-of bound. It must be an *upper bound* on true public availability — reading
`available_at_ns <= C` then guarantees the data truly existed by `C`.

Two independent upper bounds exist, so take the tighter:

```
run_day         = utc_date(valid_time) - run_offset_days   # valid-time anchored; VERIFIED :63,:84
floor_ns        = end_of_utc_day(run_day) + PUBLICATION_LAG_SLACK_NS
available_at_ns = min(retrieved_at_ns, floor_ns)           # N == 0 collapses to retrieved_at_ns
```

Both terms are upper bounds, so their min is one too. Consequences: live rows
get the exact receipt instant; archive rows get the historical bound; archive
`N == 0` rows collapse to "available only in 2026" and are therefore invisible
to any historical as-of query — failing safe with no special case.

`PUBLICATION_LAG_SLACK_NS` is a named constant in `src/breezy/forecast/vintage.py`,
justified against `q5_publication_lag_*` (`:64`) and stamped as
`vintage_policy_version`.

**Constructor guard.** `__init__` recomputes the policy and refuses any record
whose `available_at_ns` is earlier than the derived value, or later than
`retrieved_at_ns` — mirroring the `ts_event > ts_init` refusal at
`nws_raw_product.py:193-199`. A backdated record is **unconstructible**.

### 4.2 Epoch selection defaults to the EARLIEST, deliberately

`domain/selection.py` picks **max** `ts_init` — correct for settlement
corrections. The forecast archive inverts it: the read path selects, per natural
key, the **earliest `archive_fetch_epoch` that covers the window**. A later
re-fetch cannot silently improve history. Restatements stay on disk, reachable
only through the named audit path. This divergence is stated in the module
docstring so nobody "fixes" it into consistency with `selection.py`.

### 4.3 The query path: as-of is not optional

`src/breezy/persistence/forecast_catalog.py`:

- `load_forecast_asof(catalog, *, as_of_ns, station, ...) -> AsOfForecastView` —
  the **only** sanctioned read. `as_of_ns` is keyword-required, no default,
  applied *before* any epoch/ordering logic.
- Raw rows come back inside `_UnvintagedForecastRows`, whose `__iter__`/`__len__`
  raise `UnvintagedForecastReadError` (the `quote_tape_gaps.py:56-61` pattern).
  Values are unreachable without stating an as-of instant.
- Exactly one escape hatch, named to be grep-able and embarrassing:
  `unbounded_for_audit_only()`.
- Catalog `end=` may be used **only** as a coarse prefilter; the authoritative
  filter is `available_at_ns`, in one function.

### 4.4 How a maintainer reintroduces lookahead — and what stops them

| Attack | Stop |
|---|---|
| Filters on `ts_init` instead of `available_at_ns` | Fails **safe** (archive `ts_init` all-2026 → empty), and T2 makes it a hard failure |
| Adds a default `as_of_ns=None` "for convenience" | T5 asserts no default; `None` is not an accepted type |
| Iterates raw catalog rows directly | `_UnvintagedForecastRows.__iter__` raises; T6 asserts zero production refs to the audit hatch |
| Backdates `retrieved_at_ns` on a backfill | Irrelevant by construction — it is not the bound; the constructor floor still binds |
| Loosens the slack constant "for more data" | `vintage_policy_version` changes, T3 pins the constant, mixed-policy rows detectable |
| Ingests committed `.probe.json` evidence | T7: no production loader accepts `.probe.json`; `docs/evidence/` is off every ingest path |

## 5. Ingest path

### 5.1 Transport — `src/breezy/ingest/open_meteo_transport.py`

`OpenMeteoForecastTransport(HttpTransport)`, modelled on `ProbeTransport`
(`probe_transport.py:231-296`):

- `allowed_hosts = frozenset({"previous-runs-api.open-meteo.com"})`; re-uses the
  `SETTLEMENT_HOSTS` refusal (`:252-262`) so it can never be aimed at
  `api.weather.gov`.
- `fetch_discovery_list`/`fetch_product` closed with `NotImplementedError` (`:277-295`).
- **One** public method,
  `fetch_hourly_forecast(*, station, model, start_date, end_date, variables, previous_day_indices)`.
  Path is the module constant `/v1/forecast`; coordinates come from
  `registry.enrichment_coordinates(venue, city)` (`registry/sites.py:407`,
  backed by `sites.toml:139-143`, `settlement_eligible = false`), never from the
  caller. Query values validated against explicit patterns before assembly.
- **Two-URL invariant respected, and tightened.** `http.py:562-566` requires the
  caller supply WHAT, never WHERE. `ProbeTransport._probe_url` accepts an
  arbitrary validated path — acceptable for a probe, **not** for production.
  This class exposes no path parameter at all; it is strictly *narrower* than
  the invariant, so no extension or justification is needed.
- `accept="application/json"` per-instance (`http.py:580-584`); `max_body_bytes`
  per-instance (`http.py:536`) sized from q9 (7026 B for 7d x 7 vintages x 1
  variable, `:68`) — cap 2 MiB, with request shaping keeping any window under it.
- `allow_not_modified=False`: no validators are ever sent, so an unsolicited 304
  correctly raises the existing integrity alarm (`http.py:850-867`).
- `timezone=UTC` pinned on every request so §4.1 day arithmetic is unambiguous.

### 5.2 Failure, retry, idempotency

- Does **not** drive `SettlementGate` and does not import it. Forecast
  unavailability is not a settlement event.
- Non-2xx or `TransportError` → record the failure against the window, skip the
  window, **write nothing partial**.
- Bounded exponential backoff with jitter, honouring `Retry-After`
  (`FetchResult.retry_after`, `http.py:847`). A `RequestBudget` caps the run and
  aborts on exhaustion (`probe_transport.py:381`).
- **One window, one batch, one write.** Every row from one response shares
  `retrieved_at_ns`; per-row writes would be exact `ts_init`-range rewrites that
  `ParquetDataCatalog._write_chunk` discards **silently** with a bare `print`
  (real-world failure recorded at `nws_actor.py:889-898`). `write_records`
  (`catalog.py:422`) surfaces a skip; a skip is a hard error here.
- **Idempotency.** Re-running a window under a new `archive_fetch_epoch` appends
  rather than collides; §4.2's earliest-epoch rule means a re-run cannot change
  history. A resume ledger keyed `(station, model, window, epoch)` skips
  completed windows.

## 6. Ordered work breakdown — RED test first, every step

**I-0 — Verification probes (BLOCKING; freeze no schema before it lands).**
Extend the existing evidence-only probe scripts. RED: unit tests over recorded
payloads asserting each new question has an extractor. Answers required: the
upper boundary of the modern coverage span and the width of the 2024→2026 hole
(R-2); whether variables other than `temperature_2m` accept `_previous_dayN`;
`timezone=` behaviour; licence/terms (q8 UNANSWERED `:67`); a second q6 capture
for the restatement diff (`:65`). **Every coverage answer must cite a row count,
never a status code** (§0). Evidence-only, never ingested.

**I-1 — `src/breezy/forecast/vintage.py`.** RED: `available_at == min(retrieved,
floor)` across a case table incl. `N == 0`, live-future rows, DST-adjacent days;
`lead_time_ns` single-helper test. GREEN: pure module — no I/O, no clock, no
`nautilus_trader` import (mirrors `normalize/climate_day.py:1-13`).

**I-2 — `domain/open_meteo_forecast_point.py`.** RED: constructor refuses a
backdated `available_at_ns`; refuses `available_at_ns > retrieved_at_ns`;
`from_dict` refuses `ts_init != retrieved_at_ns`; Arrow round-trip;
`SchemaDriftError` on a dropped column.

**I-3 — `normalize/open_meteo_hourly.py`.** RED: against fixtures **copied**
into `tests/fixtures/open_meteo/` from I-0 (never read from `docs/evidence/`).
Parser iterates whatever `hourly` keys the payload carries — asserted by a test
that adds an unknown variable to a fixture and expects rows, not an error. Nulls
preserved as nulls.

**I-4 — `ingest/open_meteo_transport.py`.** RED: no path parameter on the public
surface; settlement host refused; `fetch_discovery_list`/`fetch_product` raise;
oversize body capped; unsolicited 304 alarms. Fake httpx transport — no network.

**I-5 — `persistence/forecast_catalog.py` + `AsOfForecastView`.** RED: T1–T6.
This is the increment the plan exists for.

**I-6 — `scripts/ingest/open_meteo_backfill.py`.** RED: resume ledger skips
completed windows; a mid-run failure writes no partial window; budget exhaustion
aborts. Writes to a forecast catalog root **distinct** from the settlement root.

**I-7 — Contract tests + import-linter.** T6, T7, and a layers rule forbidding
`breezy.forecast.*` → `breezy.ingest.gate`.

**I-8 — Live forward capture Actor.** Deferred; not on the critical path.
Reuses `NwsIngestActor`'s timer shape and nothing of its gate coupling.

## 7. Tests (all under `scripts/ci/run_tests_no_egress.sh`, no live network)

- **T1 — property (hypothesis).** *Safety*: every returned row has
  `available_at_ns <= as_of_ns`. *Completeness*: every input row with
  `available_at_ns <= as_of_ns` and the selected epoch **is** returned.
  Completeness is mandatory — safety alone is satisfied by a reader that always
  returns empty. `@example` at `available_at_ns == as_of_ns`, `-1ns`, `+1ns`.
- **T2 — flagship anti-lookahead.** Fixture: valid time `T`, two vintages `N=2`
  and `N=1` with **different values**, both written in **one batch so their
  `ts_init` is identical**. Read as-of an instant between the two `available_at`
  bounds. Must return the `N=2` value and never the `N=1` value. Because
  `ts_init` is identical, a mutant filtering on `ts_init` returns both or neither
  and **fails** — the test cannot pass by accident. Named mutants that must die:
  `<=`→`<` on `available_at`; `available_at`→`ts_init`; bound applied after epoch
  selection instead of before.
- **T3** — slack constant and `vintage_policy_version` pinned; changing the
  constant without the version fails.
- **T4** — `capture_mode == "live"` ⟹ `available_at_ns == retrieved_at_ns`;
  `archive_backfill` with `N>=1` ⟹ `available_at_ns < retrieved_at_ns`.
- **T5** — `load_forecast_asof` signature has no default for `as_of_ns`.
- **T6** — zero production modules reference `unbounded_for_audit_only` or
  `available_at_ns` outside `forecast/vintage.py` and `persistence/forecast_catalog.py`.
- **T7** — no production loader accepts `.probe.json`; `docs/evidence/` is
  unreachable from any ingest entry point.
- **T8** — one-window-one-write: a skipped `write_records` chunk raises, never warns.

## 8. Risks, sharpest first

- **R-1 — the archive is itself a restatement channel, and its vintage is
  unverifiable.** `q6_values_ever_restated` is **UNANSWERED** (`:65`). If
  Open-Meteo re-processes history, the value stamped as "the 2022 run" is a claim
  about a model run, not about what any participant could have seen — and every
  calibration conclusion inherits that. *Mitigation:* the q6 cross-run diff is a
  **required gate** before any calibration claim; the sha256 columns make the
  diff computable from the catalog; `archive_fetch_epoch` + earliest-epoch
  selection keeps restatements visible instead of silently merged. **This risk
  cannot be eliminated by this plan — only measured.**
- **R-2 — coverage hole of unknown width, and non-uniform model coverage.**
  2022→2023-12-09 contiguous; 2024-01-01 empty for all four models; 2026-08
  covered. At 2022-01-01 only 2 of 4 models carried data. The modern span's lower
  boundary is unprobed. *Mitigation:* I-0 blocks; nulls stored as nulls and never
  imputed; the dataset ships with a per-model coverage report.
- **R-2b — generalization across the gap.** The covered span (2022–2023) is
  separated from the live period (2026) by the hole, and the NWP models were
  upgraded in between. A calibration fitted on the old span may not transfer.
  *Mitigation:* report calibration separately for the recent covered window; treat
  any cross-gap claim as provisional.
- **R-3 — a maintainer reintroduces lookahead.** *Mitigation:* §4.4; the dominant
  failure mode is over-restriction, not lookahead.
- **R-4 — read-path memory.** The settlement reader loads a whole station root
  per lookup (`catalog.py:693-702`); tall format multiplies rows by
  (vintages x variables). *Mitigation:* mandatory window on the loader, measured
  at I-5; revisit before any multi-year read.
- **R-5 — licence/terms UNANSWERED** (`:67`). *Mitigation:* I-0 must resolve
  before any recurring production dependence.
- **R-6 — silent grid/model drift.** *Mitigation:* returned lat/lon/elevation
  stored per row; a drift test compares against `registry_version`.
- **R-7 — `_previous_dayN` may be temperature-only.** Would make
  "feature-agnostic" hollow for other variables. *Mitigation:* I-0.

## 9. Open questions

1. Exact model-run initialization hour behind `previous_dayN` — absorbed by the
   slack, but the slack needs a justified number.
2. Is `N` relative to the valid day or the request's reference day? Probe says
   valid-time anchored (`:84`); I-0 must confirm at a month boundary.
3. Does `timezone=` change `time` semantics, and is the default GMT?
4. Which variables accept `_previous_dayN` (R-7).
5. Lower boundary of the modern coverage span, and the hole's width (R-2).
6. Licence terms (R-5).
7. Does `ParquetDataCatalog.query` push `start=` down on `ts_event` as well as
   `ts_init`? Affects R-4 only, never correctness — the vintage filter never
   moves into the catalog.
8. Relationship to `docs/plans/FORECAST_INGESTION_PLAN.md` (rev 2, NWS-first,
   not executed). Its D8 (one-batch-one-write), D10 (schema final at first cut),
   D12 (evidence-only), D13 (`issuance_time_ns` naming) are adopted here. Whether
   that plan is superseded or runs alongside is a coordination decision.

---

**Handover note.** Three things above are load-bearing and easy to lose in a
rewrite: the min-of-upper-bounds derivation in §4.1, the earliest-epoch
inversion in §4.2 (it deliberately contradicts `domain/selection.py`), and T2's
identical-`ts_init` fixture construction — that detail is the only reason the
flagship test cannot pass vacuously. The commissioning brief's premise that the
archive reaches 2019 is refuted by the repo's own committed evidence; I-0 is a
blocking gate, not a formality.
