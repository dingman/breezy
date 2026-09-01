# BL-24 — Intraday temperature-observation data stream for Nautilus

**Date:** 2026-09-01. **Status:** PLAN, not implemented. **Author:** planner agent.
**Scope:** a data path, not a trading result. Claude/agents never backtest,
simulate, or execute; Nautilus alone does.

> NOTE (main session): this plan predates the execution-readiness and
> backtest-fidelity audits of 2026-09-01. Re-check its priority against those
> before implementing — the critical path may have moved.

## 0. GOAL STATE (falsifiable predicate)

> A `BacktestEngine` built by `breezy.runtime.backtest_harness` replays
> `StationObservation` records interleaved by `ts_init` with the venue
> `OrderBookDepth10` tape, and a `Strategy` subscribed to
> `station_observation_data_type()` under `NWS_BACKTEST_CLIENT_ID` receives them
> in `on_data` such that at every replayed instant `t`,
> `R(t) = max{ selected temperature of observations of that station's climate
> day whose ts_init <= t }` is computable from what the handler has seen and
> **depends on no record whose `ts_init > t`**.

**Falsification test (I-5):** `tests/integration/test_intraday_observation_backtest.py`
runs a real `BacktestEngine` with a probe strategy appending
`(clock.timestamp_ns(), R)` on every `on_data`. Three assertions: (1) `R` equals
the running max over the `ts_init`-ordered PREFIX at every instant, exact
equality; (2) an observation with `ts_event` 09:00 local but `ts_init` 18:00
local is invisible to `R` before its `ts_init` — the look-ahead channel tested
directly; (3) `R` resets on the climate-day boundary computed by
`climate_day_for_instant(..., std_utc_offset_hours)`, never by UTC date.

### Walk to goal

    I-1 record class -> I-2 catalog seam -> I-3 DataType + feed wiring -> I-5 fold + engine test = GOAL
                                   ^
                       I-4 IEM loader (supplies the rows I-5 replays)
                                   |
       deferred, NOT on the goal path: I-6 transport endpoint -> I-7 live Actor

### Gap hunt (L-3)

| Would-be gap | Claimed by | Why the goal fails without it |
|---|---|---|
| No `Data` subclass carrying an intraday temperature | I-1 | `add_data` refuses non-`Data`; `DataEngine._handle_data` logs-and-drops an unrecognized type |
| No Arrow schema -> no catalog round trip | I-2 | Records exist only in memory; a backtest cannot be re-run from disk |
| No shared `DataType` -> publisher/subscriber topic mismatch | I-3 | Subscriber receives ZERO records **with no error** (the W1 hazard) |
| No rows for the tape window | I-4 | Local ASOS cache ends 2026-01-02; price tape starts 2026-08-30. **No overlap.** Without a fetch the backtest replays an empty stream and I-5 is vacuous |
| No `R(t)` fold | I-5 | Nothing in Nautilus or in `src/breezy/strategy/` computes one today |

Nothing else stands between I-5 and the predicate: `weather_data` is already a
`Sequence[Data]` on `BreezyBacktestConfig` (`backtest_harness.py:416`), already
fed with `client_id=NWS_BACKTEST_CLIENT_ID` (`:787-792`), and `add_data` already
sorts the whole stream by `ts_init` (`engine.pyx:902-905`).

## 1. Null-hypothesis verdicts (L-1), against installed nautilus-trader 1.231.0

- **1.1 `Data` base + custom-type extension — NATIVE, sufficient.** `core/data.pyx:20`,
  abstract `ts_event` (`:29-39`), `ts_init` (`:41-51`). CONFIGURE.
- **1.2 A `Data` subclass carrying a scalar physical measurement — NATIVE, INSUFFICIENT.**
  Full inventory of `model/data.pyx` subclasses: `Bar`(:1474), `CustomData`(:2136),
  `OrderBookDelta`(:2452), `OrderBookDeltas`(:3079), `OrderBookDepth10`(:3441),
  `InstrumentStatus`(:3961), `InstrumentClose`(:4198), `QuoteTick`(:4400),
  `TradeTick`(:5037), `MarkPriceUpdate`(:5606), `IndexPriceUpdate`(:5850),
  `FundingRateUpdate`(:6093), `OptionGreeks`(:6287). Every one requires an
  `InstrumentId` or carries its value as a `Price`. Representing an observation
  as a `Bar` would require minting a synthetic instrument per station inside the
  venue namespace (`engine.pyx:874-887` validates
  `bar_type.instrument_id in cache.instrument_ids()`) — settlement-namespace
  pollution, not reuse. **Smallest correct extension: one hand-written subclass.**
- **1.3 Arrow serialization — NATIVE, sufficient.** `serialization/arrow/serializer.py:89`
  `register_arrow`, registry `:78`/`:128`; Breezy wraps it in `domain/strict_arrow.py`.
- **1.4 Catalog persistence — NATIVE, sufficient.** `write_records` (`persistence/catalog.py:422`)
  and `_read` (`:89`) reused unchanged.
- **1.5 Backtest routing + client registration — NATIVE, sufficient.** `CustomData`
  (`model/data.pyx:2136`), `add_data(..., client_id=)` (`engine.pyx:783`, registers
  at `:889-891`).
- **1.6 Interleaving by arrival time — NATIVE, sufficient.** `engine.pyx:903`
  sorts by `ts_init`. **This is why `ts_init` provenance is the safety argument.**
- **1.7 A running-extreme primitive — GENUINELY ABSENT, in Nautilus AND Breezy.**
  Every `cdef class` in `indicators/` searched. Only extreme-tracker is
  `DonchianChannel` (`volatility.pyx:305`), state `deque(maxlen=period)` over
  `Price` (`:330-331`), fed only by quote/trade/bar handlers (`:337`,`:353`,`:368`) —
  a fixed-count ROLLING window, not day-anchored, and takes no custom `Data`.
  **CORRECTION TO THE BRIEF:** `running_extreme_lock/strategy.py:304-319` does
  NOT compute a running max — `on_data` reads `data.tmax_f` off an
  `NwsClimateDay` CLI preliminary; `decision.py:212` does
  `running_f = observation.tmax_f`. No fold, accumulator or `max()` exists
  anywhere in `src/breezy/strategy/`. The accumulator must be AUTHORED.
- **1.8 An HTTP client fetching observations — GENUINELY ABSENT.** See §6.

## 2. The record class — `StationObservation` (I-1)

`src/breezy/domain/station_observation.py`. Hand-written `Data` subclass;
`@customdataclass` deliberately not used (reason at `nws_climate_day.py:10-14`).

| column | type | null | meaning |
|---|---|---|---|
| `station` | string | no | registry `cli_location`; never a network-derived id |
| `climate_day` | date32 | no | `climate_day_for_instant(...)`, local STANDARD time |
| `observed_at_ns` | int64 | no | measurement instant (METAR `valid`), UTC ns |
| `temp_c_tenths` | int64 | yes | METAR T-group value, native unit, unconverted |
| `temp_flag` | string | yes | sentinel when temp is None; closed vocabulary, paired exclusivity |
| `source_channel` | string | no | `"iem_asos_archive"` \| `"nws_api_observations"` |
| `station_source_id` | string | no | id used at the source (`"NYC"` IEM, `"KNYC"` NWS) |
| `assumed_publication_lag_ns` | int64 | yes | see §3 |
| `received_at_ns` | int64 | no | becomes `ts_init` |
| `raw_observation` | string | no | verbatim METAR |
| `raw_sha256` | string | no | provenance anchor |
| `source_url` | string | no | |
| `parser_version` / `registry_version` / `schema_version` | | no | |
| `ts_event` / `ts_init` | int64 | no | `== observed_at_ns` / `== received_at_ns` |

**Deliberately NO `temp_f` and NO `rounded_f` column.** A Fahrenheit column
invites joining against `NwsClimateDay.tmax_f` as the same quantity. It is not
(§5). Conversion is an explicit call `observation_basis_f(temp_c_tenths) -> int`,
named for the BASIS not for `tmax`. Pinned by
`test_the_observation_schema_carries_no_column_named_like_settlement`.

`from_dict` uses `values[...]` subscript throughout, **never `.get`** (the
`QuoteTapeGap.from_dict:186-202` precedent), plus cross-field identity checks
`ts_event != observed_at_ns -> ValueError`, `ts_init != received_at_ns -> ValueError`.
Exactly one module-scope `register_arrow` call (`nws_climate_day.py:383-389` shape).

## 3. The look-ahead trap, made INEXPRESSIBLE

`BacktestEngine` orders on `ts_init`. The trap is stamping `ts_init` from the
measurement instant. For fetched ARCHIVE rows the honest byte-receipt instant is
the fetch instant — later than the whole tape, so everything would replay after
the run ends. Anything else is a derivation and must be declared. Precedent:
`ArchivedClimateDay` sets `ts_event = ts_init = issuance_time_ns`
(`archived_climate_day.py:225-226`) and keeps the real fetch instant in a
separate non-timestamp column.

`__init__` takes `received_at_ns` but **not** `ts_init`, and refuses:
1. `received_at_ns <= observed_at_ns` -> `ValueError`. **This makes `ts_init == ts_event` unconstructible.**
2. lag declared and `received_at_ns != observed_at_ns + lag` -> `ValueError`.
3. lag declared and `<= 0` -> `ValueError` (closes the zero-lag back door into 1).

Paired vocabulary: `"nws_api_observations"` MUST have lag `None` (receipt is
measured); `"iem_asos_archive"` MUST have a non-None lag (arrival is derived and
says so). Every row therefore carries whether its replay position was measured or
assumed, and under what assumption.

**`ASSUMED_METAR_PUBLICATION_LAG_NS` is UNKNOWN.** Must be pessimistic: too large
only delays a signal; too small is look-ahead. **Resolving check:** poll
`/stations/{icao}/observations` for one station over ~48h, recording byte-receipt
against `properties.timestamp`, take P95/max. Until then use a stated pessimistic
placeholder marked UNKNOWN and report sensitivity.

## 4. Cadence, gaps, duplicates

**Cadence (archive path).** IEM `asos.py` is a bounded range query
(`settlement_alignment_study.py:408-433`), `report_type=1&2`, `tz=Etc/UTC`,
-1/+2-day pad (`:411-412`). Rows are irregular by nature — hence per-observation
records, not per-hour buckets.

**NO gap record — justified, not skipped.** `QuoteTapeGap` exists because a
websocket outage is indistinguishable from a quiet market and cannot be refetched
(`tape_records.py:56-65`). Neither holds here: the archive query is a bounded
range with a definite answer (absence is decidable by counting rows per
`(station, climate_day)`), and the source is refetchable. A gap record would add
a class, a join contract and the open-row merge hazard for a condition `COUNT(*)`
answers. **Instead I-4 ships a coverage preflight** (L-8 shape) reporting per
`(station, climate_day)`: row count, first/last `observed_at_ns`, largest
inter-observation gap, status `INTACT`/`SPARSE`/`ABSENT`. **Falsification of this
YAGNI call:** if I-7 ships and a poll outage becomes indistinguishable from a
quiet station, revisit.

**Duplicates and CORRECTIONS.** Dedupe `(station, observed_at_ns, raw_sha256)`
before the write (`write_records` refuses non-monotonic `ts_init`,
`catalog.py:440-442`). **Corrected METARs (`COR`) are a real trap:** a naive
running max keeps a spuriously high reading forever. The fold keeps
`observed_at_ns -> (ts_init, temp)` and recomputes `max(selected)` where selected
is the greatest-`ts_init` entry per `observed_at_ns`, so a downward correction
LOWERS `R(t)`. RED test: `test_a_corrected_observation_lowers_the_running_extreme`.

## 5. UNITS — carry forward (L-2)

**Settlement is the CLI integer `tmax_f`. Observations are METAR tenths of degC
from a different instrument on a different cadence. An observation-derived
maximum is NOT the settled maximum.** Measured basis `CLI tmax_f - ASOS daily
max`, n~1800/station: NYC mean **+0.655**, median **+1.0**, P(>=1) **55.99%**,
P(>=2) 8.47%; MIA +0.118; LAX +0.103; SFO +0.050; MDW -0.053.

Carried structurally, not by comment: (1) no F column exists; (2) the helper is
named `observation_basis_f` with the table in its docstring; (3) a schema test
fails if anyone adds a settlement-shaped column; (4) the fold's result is named
`running_observation_max_f`, never `running_tmax_f`.

## 6. Containment contract and the third endpoint (I-6, DEFERRED)

**What `tests/unit/test_probe_containment.py` asserts today:**
`test_probe_transport_public_surface_is_get_only` (`:297-310`) asserts set
EQUALITY on `{probe_get, probe_get_strict, fetch_discovery_list, fetch_product}`;
`test_the_settlement_fetch_methods_are_unreachable_from_a_probe` (`:324-330`);
`test_probe_transport_overrides_none_of_the_four_cited_controls` (`:230-237`);
`test_the_shipped_settlement_allowlist_is_untouched` (`:719-722`).

**How a third endpoint SATISFIES it (never weakens it):** the builder goes INSIDE
`HttpTransport` (the `:562-566` invariant; `_fetch` private at `:769`).
`_observations_url(icao)` -> `/stations/{seg}/observations`, `seg` validated by
`_ICAO_PATTERN = \A[A-Z]{4}\Z` — four letters, so no string satisfies both it and
`_CLI_LOCATION_PATTERN` (three letters) or `_PRODUCT_ID_PATTERN` (UUID),
preserving the "no method can be aimed at another's endpoint" property across
three endpoints. `fetch_station_observations(...)` -> `_fetch(allow_not_modified=True)`
(conditional GET correct for a mutable index, `:663-669`).
`test_probe_transport_public_surface_is_get_only` **goes RED — that is the
contract working.** Response: widen the expected set AND add a
`NotImplementedError` override on `ProbeTransport` AND extend the unreachability
test with a third case. The assertion stays an EQUALITY. `DEFAULT_ALLOWED_HOSTS`
needs no change (`shared_state.py:99`). **UNKNOWN:** whether the observations
endpoint honours `application/ld+json`; resolving check is one live read.

**The CRITICAL PATH does not touch this.** The backtest needs IEM
(`mesonet.agron.iastate.edu`), not `api.weather.gov`. `ProbeTransport` is wrong by
design (its output is stamped EVIDENCE ONLY — NEVER INGEST, `:677-681`);
`HttpTransport` is the settlement transport allowlisted to one host, and widening
it is what `test_no_probe_widens_the_shipped_default_allowlist` (`:942-959`)
exists to make loud. Precedent already in tree: `settlement_alignment_study.py`
imports bare `httpx` (`:31`) with an on-disk cache and lives in `scripts/analysis/`,
outside the venue-touching classifier. So **I-4 lives in `scripts/analysis/`**.

## 7. Increments

Command always: `scripts/ci/run_tests_no_egress.sh <paths>` (bare pytest aborts
on the egress firewall).

- **I-1 record class + strict Arrow.** New `domain/station_observation.py`.
  RED: `tests/unit/test_domain_station_observation.py` — 14 named tests incl.
  `test_ts_init_is_the_received_instant_and_is_not_a_constructor_parameter`,
  `test_a_record_whose_arrival_equals_its_measurement_is_refused` (the trap),
  `test_climate_day_is_local_standard_time_not_utc`,
  `test_from_dict_raises_on_a_missing_column` (parametrized over schema names),
  `test_the_observation_schema_carries_no_column_named_like_settlement`.
  Risk LOW — no existing path changes.
- **I-2 catalog seam.** New `persistence/observation_catalog.py`:
  `observation_catalog_path`, `assert_observation_base_disjoint` (mirrors
  `archive_catalog.py:21-39`), `read_station_observations` (mirrors `:53-86`).
  A THIRD disjoint base `~/.local/share/breezy/observations/` because an
  observation-derived max is not settlement truth. RED:
  `tests/contract/test_catalog_station_observations.py` — round trip, schema
  drift, type drift, non-monotonic refusal, missing-root-is-not-empty (L-8),
  base disjointness. Risk LOW. Depends I-1.
- **I-3 DataType + feed wiring + BARRIER W1.** New `ingest/observations.py` with
  `@lru_cache(maxsize=1) station_observation_data_type()`, no metadata
  (`nws_actor.py:373-377`). Add to `_DATA_TYPE_FACTORIES` (`backtest_feed.py:121-124`).
  **BARRIER FINDING:** `tests/unit/test_weather_data_type_barrier.py:94` hardcodes
  `_RECORD_NAMES = {"NwsClimateDay","NwsRawProduct"}` and `:98` pins
  `_FACTORY_MODULE` to one string, so `DataType(StationObservation)` built inline
  anywhere in `src/` or `scripts/` **is undetected today** — the exact silent
  zero-record hazard W1 exists to stop. I-3 must add the record name, add the
  factory name, and change `_FACTORY_MODULE: str` into
  `_FACTORY_MODULES: Mapping[str, frozenset[str]]`, keying the exemption on that
  map so `test_the_exemption_is_bound_to_the_factory_module_not_the_function_name`
  (`:256-268`) is preserved. This WIDENS coverage; it weakens nothing.
  Layer check: runtime -> ingest is downward, legal, no new import-linter entry.
  Risk MEDIUM — a topic mismatch fails silently by construction.
- **I-4 IEM loader + coverage preflight (CRITICAL PATH).** New
  `scripts/analysis/load_iem_observations.py`. Reuses `asos_url`,
  `fetch_bytes_cached`, `parse_metar_t_group`, `metar_temperatures`,
  `IEM_ASOS_IDS`, `climate_day_for_instant`. `--dry-run` default, explicit
  `--apply`. **UNKNOWN:** IEM same-day latency; resolving check is one live
  request for yesterday's window for one station, comparing row count against
  ~24, before the full load. Risk MEDIUM. Depends I-1, I-2.
- **I-5 `R(t)` fold + engine test — GOAL STATE.** New
  `strategy/weather_common/running_extreme.py` — `RunningDayExtreme`, pure, no
  Nautilus import, ~40 lines, correction-aware per §4. Then
  `tests/integration/test_intraday_observation_backtest.py` running a REAL
  `BacktestEngine` via `backtest_harness.backtest(...)` with
  `allow_idle_strategies=True`, incl.
  `test_a_late_arriving_early_observation_is_invisible_before_its_ts_init`.
  Extend `tests/support/synthetic_multi_strike_tape.py` rather than authoring a
  second harness. Risk MEDIUM — this increment reaches the predicate or proves it
  unreached.
- **I-6 third `HttpTransport` endpoint (LIVE, DEFERRED).** §6.2. Risk HIGH —
  blast radius 48 + 15 + 10 callers. Mitigation: adds a builder and a public
  wrapper only; changes no shared control; reuses `_fetch` verbatim.
- **I-7 `NwsObservationActor` (LIVE, DEFERRED, LAST).** Composition of
  `NwsIngestActor` patterns; `source_channel="nws_api_observations"`,
  `assumed_publication_lag_ns=None`, `received_at_ns = FetchResult.retrieved_at_ns`.
  Depends I-6. Risk MEDIUM.

## 8. Risks

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| R1 | Publication lag unmeasured; too small => look-ahead | HIGH | Pessimistic placeholder, UNKNOWN in docstring, stored per row; resolved by I-6 live measurement |
| R2 | ASOS cache ends 2026-01-02, tape starts 2026-08-30 — no overlap | HIGH | I-4 on the critical path; preflight fails loudly rather than replaying empty |
| R3 | Tape/observation overlap currently ONE day | HIGH | Data path proven either way; any economic reading is n=1 and must say so |
| R4 | Barrier W1 does not cover a new record class | HIGH | I-3 widens it AND asserts factory identity + topic string |
| R5 | Corrected METARs stick a spurious high into `R(t)` | MED | Correction-aware fold with its own RED test |
| R6 | Observation-derived max read as settled max | HIGH | §5: no F column, named helper, schema barrier test |
| R7 | `test_probe_transport_public_surface_is_get_only` RED on I-6 | MED | Expected and correct — widen the set AND close the method. Never relax |
| R8 | `write_records` refuses unsorted batch | LOW | Sort + dedupe in loader; asserted |
| R9 | IEM same-day latency unknown | MED | Named check in I-4 before full load |
| R10 | Three catalog islands to keep straight | LOW | `assert_observation_base_disjoint` |
| R11 | A fixed fact asserted in several places | MED | L-4: after any revision sweep every asserting site |

## 9. Deliberately NOT doing (YAGNI)

1. No live Actor on the critical path (nothing trades until economics are proven).
2. No gap record (§4, with its falsification condition).
3. No stored `temp_f`/`rounded_f` column — the absence IS the safety property.
4. No second `ClientId`, no new `BreezyBacktestConfig` field.
5. No separate `ArchivedStationObservation` class.
6. No Nautilus `Indicator` subclass for `R(t)` — the base takes `Price` updates.
7. No H4 strategy — this delivers the data path only.
8. No 1-minute ASOS, no resampling, no forecast enrichment.
9. No historical backfill beyond the tape window.
10. No `BacktestDataConfig` / high-level-API wiring.

## 10. Definition of done

- [ ] Goal-state predicate holds, evidenced by green
      `tests/integration/test_intraday_observation_backtest.py` incl. look-ahead.
- [ ] Every increment landed with RED->GREEN output as the artifact.
- [ ] `scripts/ci/run_tests_no_egress.sh` green over the whole suite.
- [ ] `lint-imports` green; no contract in `pyproject.toml:51-159` weakened.
- [ ] `test_probe_containment.py` green with assertions WIDENED, never relaxed.
- [ ] Barrier W1 covers `StationObservation`; non-vacuity test still fails
      without the exemption.
- [ ] No safety/settlement/contract test deleted or weakened; `allow_short`
      untouched; no operator-reserved control assigned; live-trading enablement
      and the NO-SEND egress firewall untouched.
- [ ] Every UNKNOWN resolved with evidence or still carrying its resolving check.
