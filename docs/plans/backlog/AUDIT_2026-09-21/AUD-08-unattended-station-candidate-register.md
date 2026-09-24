# AUD-08 — Stop a single unlisted venue city from livelocking discovery, then record it as a station candidate

## 1. ID and actionable title

**AUD-08** — (a) stop one unregistered venue city from aborting — and then permanently
re-aborting — the whole Polymarket.us discovery reload cycle, and (b) turn that refused city into a
dated, machine-readable **station-candidate register** carrying a data-sufficiency status, and
**raise one unattended alert the first time a candidate appears** so the register is not a file
nobody reads.

Split into two independently actionable sub-items, deliberately re-split since round 1 so the
livelock fix is not carried by the register's priority:

- **AUD-08a — discovery livelock fix.** One unregistered city must not stop the four *traded*
  stations from loading tomorrow's cohort. Adapter-side, **in-process only: no new artefact, no new
  file format, no new unit**. *Round-2 change (A8-1 / M5 accepted):* the sighting **sidecar** the
  emitter reads is NOT part of 08a — it is specified as a first-class artefact in 08b (§6b), which
  is what keeps this sentence true. Round 2 found revision 2 asserting both at once.
- **AUD-08b — the candidate register.** The sighting sidecar (writer, path, schema, single
  sanctioned writer, crash rule) + venue-neutral record + fold + versioned JSONL writer + nightly
  emission + the new-candidate alert. This is the artefact AUD-09a reads (§6b, hand-off H1).

08b is skippable without breaking 08a. 08a is not skippable: it is the fix.

## 2. Source finding and class

- **Gap:** G-05 "Station discovery is static." Verdict **FALSE** (coordinator-verified). The
  eligibility path for a *new* station also touches **G-07** (promotion cannot change stations) —
  §6c states the whole sequence and names which steps are outside this backlog.
- **Evidence:** `SUPPORTED_STATIONS = ("LAX","MDW","MIA","SFO")` at
  `src/breezy/strategy/current_rung_hold/config.py:76` (re-read in round 3, still exact);
  `breezy-quote-tape.service` discovers listings unattended (2026-09-20T21:00:42Z: 60 markets /
  120 instruments) but nothing turns a new station into a backtest candidate.
- **Class:** **autonomous-operation failure** (08a — the node's response to a new city is a
  permanent discovery outage that also starves the live family) plus **missing capability**
  (08b — no candidate artefact exists).
  *Round-1 change:* the class order is inverted from the baseline. Both reviewers independently
  established that the livelock, not the absent register, is the load-bearing finding.
- Related standing facts: PROGRESS.md:31 "Venue surface = 5 cities × daily HIGH";
  memory `venue-skips-station-days` (~9% of station-days are never listed; a missing day is
  VENUE-NEVER-LISTED until a by-slug probe says otherwise).

## 3. Current behaviour, required behaviour, concrete gap

**Current — verified against source (line citations corrected in round 1, re-read in round 3).**

1. `PolymarketUSMarketDiscoveryConfig.city_codes` is **derived from the settlement registry**, not
   recited: `discovery_city_codes_from_registry` (`adapters/polymarket_us/config.py:155-183`)
   returns one `venue_city_token` per `(polymarket_us, city)` pair in `src/breezy/registry/sites.toml`
   (NYC, SFO, MIA, MDW, LAX — `sites.toml:117,154,193,239,279`).
2. `_weather_market_payloads` (`adapters/polymarket_us/provider.py:190-229`) parses every listed
   slug. A weather market whose `parsed.city` is **not** in `city_set` **raises `VenuePayloadError`**
   at **`provider.py:221-227`**: *"which has no polymarket_us entry in the settlement registry;
   refusing to trade or to skip a city Breezy holds no settlement truth for"*.
3. The raise is unconditional and precedes any `accepted.append(market)` (`provider.py:228`), so it
   aborts the whole `load_all_async` pass from inside `_discover_markets` — **before** the CF-14a
   stage-3 failure collector. No market of **any** city is loaded that pass.
4. `_run_one_reload_cycle` is wrapped in a blanket `except Exception` that logs RED and falls
   through to the next `asyncio.sleep(delay_secs)` pass (`adapters/polymarket_us/data.py:1253-1267`,
   re-read in round 1). So the failure is **not fatal — it is permanent**: every reload cycle fails
   identically until a human edits `sites.toml`.
5. Nothing anywhere writes a record of the refused city. The only trace is one RED log line per
   cycle (`data.py:1262`).

**Blast radius (round-1 finding, accepted).** The refusal is *not* scoped to the newcomer. The whole
payload is refused, so the node stops picking up **any** new listing — including tomorrow's cohort
for LAX/MDW/MIA/SFO. The node stays "active (running)", the tape keeps flowing for already-loaded
instruments, and the live family quietly has no instruments for the next climate day. That is
exactly the shape memory `venue-drift-kills-the-node-silently` records as already paid for
(09-20: permit lapsed 10.9 h while the node looked perfect) and memory
`a-healthy-node-can-still-be-unable-to-trade` names as a liveness class. 08a closes it.

**Required.**

- A listed city with no registry entry must (a) **never** stop the four settle-able cities from
  loading, and (b) produce a durable, dated **candidate record** that a scheduled job can read.
- The record must carry enough for a reader to decide whether the candidate is even *testable*:
  first-seen day, venue city token, observed cohort size, and a **data-sufficiency status**.
- **Someone must be told, once, that a candidate exists**, and told what act would move it toward
  eligibility. *Round-2 change (tba minor, coordinator-required):* a register nobody is prompted to
  read is the same class of defect as an alert nobody receives (memory `readiness-audit-2026-09-12`:
  "a detector without delivery is not a control"). §6b adds the notification; §6c states the whole
  eligibility sequence and its owners.
- The refusal to *trade* an unregistered city is **kept exactly as strict as today**. Recording a
  candidate never creates an instrument, never subscribes, never reaches a strategy.

**Concrete gap.** Three distinct defects: a **fail-stop that livelocks the reload loop**, an
**absent register**, and **no path from a recorded candidate to a human act**.

**Honest bound on value.** The venue surface is measured at 5 cities × daily HIGH (PROGRESS.md:31)
and all 5 are already in the registry. On Polymarket.us today 08b will most likely emit **zero**
sighting-derived candidates (the registry-seeded NYC row of §6b is the one row it will emit).
**No ROI claim is made for PM.us.** See §11.

## 4. Priority, rationale, dependencies, execution order

**Priority: P1** for AUD-08a, **P3** for AUD-08b.

- **08a is P1, raised from P2 in round 1** on the blast-radius argument above: the failure is not an
  expansion-only discovery outage, it is a livelock that can starve the *currently traded* family of
  tomorrow's instruments while every health signal reads green. Cost asymmetry decides it — a few
  hours of implementation against a class of silent halt this programme has paid days for twice
  (`POST_FORECAST_PHASE_2026-09-20.md` B-0).
- **It is P1 and not P0** — the evidenced counter-argument the round-1 reviewer asked for, stated
  rather than assumed: P0 in this backlog is reserved for defects blocking live trading *now*
  (G-01's two structural gates, memory `two-structural-gates-block-every-take`). The trigger here
  has **never been observed**: `city_codes` is derived from the registry and the registry covers all
  5 cities the venue has ever listed, so firing requires the venue to list a 6th city. That is a
  latent cliff, not an active halt. Ranking it P0 would displace a defect that is blocking takes
  today. **This is an argument about urgency, not about blast radius** — the blast radius is
  conceded in full.
- **08b is P3** because on this venue it produces a register with one registry-seeded row and no
  sightings. It earns its place as AUD-09a's named input (H1 below) and as the expansion-venue seam,
  not as near-term ROI.

**Dependencies.** None inbound. Outbound hand-offs are named in §6b (H1 to AUD-09; H2 explicitly
declined to AUD-10 and, since round 3, declined **without residue** — see §6b). Alert delivery for
the WARN path and the new-candidate notification depends on the shipped alert egress
(`f97c26f`, PROGRESS.md:84) — already live, so this plan does **not** re-plan it, it calls it.

**Execution order:** AUD-08a → AUD-08b.

## 5. Scope and explicit exclusions

**In scope.** `_weather_market_payloads` failure handling; the sighting **sidecar** (module, path,
schema, single sanctioned writer, reader, rotation, crash rule); a venue-neutral candidate record +
pure fold + versioned JSONL writer/reader; a provider-level accessor and an injected sink; a
scheduled emitter; the first-appearance alert; tests.

**Explicitly excluded.**

- Adding any city to `src/breezy/registry/sites.toml`. That file is *the single source of settlement truth* and
  its own header mandates independent live re-verification of `issuing_office` and
  `body_header_regex` per site before production use. Adding a site is a separate, evidenced act
  (§6c step 3).
- Widening `SUPPORTED_STATIONS` or `CurrentRungHoldConfig.stations` (`config.py:76,239-252`,
  `UnsupportedStationError` raised at `:245-252`). The allow-list stays closed (§6c step 4).
- Extending or recalibrating the frozen archive table (`archive_table.CORPUS_SHA256`, pinned by
  `ArchiveTablePinMismatchError`, `config.py:261-265`) for a new station. Outside this backlog
  entirely (§6c step 4).
- Subscribing to, parsing into an instrument, or capturing any unregistered city's market.
- Any live venue call not already made by the existing discovery cycle. The register is built from
  the *existing* `GET /v1/markets` payload — zero new request budget.
- Kalshi. Portability is a placement constraint here (§6b), not a deliverable.

## 6. Proposed changes (grounded)

**Nautilus null hypothesis (L-1) — grep RUN in round 1, output recorded.**
`/usr/bin/grep -rn "candidate\|rejected\|unsupported" .venv/lib/python3.13/site-packages/
nautilus_trader/common/providers.py` → **0 lines**. Positive control
`/usr/bin/grep -c "def add" <same file>` → **3**. `InstrumentProvider` holds only
`_instruments`/`_currencies` and exposes add/add_bulk/find/get_all/list_all/load*: a symbol either
becomes an `Instrument` or does not exist. There is no rejected/candidate concept and no
side-channel. **Verdict: GENUINELY ABSENT.** The native mechanism reused is the provider subclass
Breezy already owns (`PolymarketUSInstrumentProvider`, `provider.py:262`, constructed once at
`adapters/polymarket_us/factories.py:517 _shared_polymarket_us_instrument_provider`) plus the
existing reload loop (`data.py:1253`) as the scheduler — no new thread, timer, or service.

### AUD-08a — survive and record in memory (adapter-side, no artefact)

- `src/breezy/adapters/polymarket_us/provider.py:190-229`: `_weather_market_payloads` gains a
  keyword-only `collect_unregistered` flag and, **when true**, returns the sightings beside the
  payloads instead of raising at `:221-227`; when false it returns the payload tuple and raises
  exactly as today.
  *Round-1 change (m2 accepted):* the baseline's mutable `unregistered: list | None` out-parameter is
  replaced by this return-value form — same single-call-site widening (L-12 shape), no mutable
  argument, consistent with the repo's immutability default.
  ***Round-2 change (a1 accepted) — the signature is given in a form that is valid under
  `mypy --strict`.*** `[tool.mypy] strict = true` (pyproject.toml:158) and `files` includes
  `src/breezy/adapters` (`:160`) with no override for this module, so a return type that varies with
  a `bool` argument would have to be declared as a union, and `discovery_candidate_slugs`
  (`provider.py:181-187`, which calls `_weather_market_payloads(payload, city_codes)` positionally
  at `:187`) could not iterate it without narrowing. The plan therefore specifies **two `@overload`
  declarations on the literal bool over one implementation**:

  ```python
  @overload
  def _weather_market_payloads(
      payload: Mapping[str, Any], city_codes: tuple[str, ...],
      *, collect_unregistered: Literal[False] = False,
  ) -> tuple[Mapping[str, Any], ...]: ...

  @overload
  def _weather_market_payloads(
      payload: Mapping[str, Any], city_codes: tuple[str, ...],
      *, collect_unregistered: Literal[True],
  ) -> tuple[tuple[Mapping[str, Any], ...], tuple[UnregisteredCitySighting, ...]]: ...

  def _weather_market_payloads(
      payload: Mapping[str, Any], city_codes: tuple[str, ...],
      *, collect_unregistered: bool = False,
  ) -> tuple[Mapping[str, Any], ...] | tuple[
      tuple[Mapping[str, Any], ...], tuple[UnregisteredCitySighting, ...]
  ]: ...
  ```

  `discovery_candidate_slugs` and every existing test keep byte-identical behaviour and type because
  they never pass the flag and therefore bind the first overload. **A9's sibling criterion A13 is
  `mypy src/breezy` clean**, so a two-function shape (shared inner + two thin wrappers) is an
  acceptable substitute if the implementer finds overloads awkward — the constraint is the
  typecheck, not the spelling.
- `PolymarketUSInstrumentProvider._discover_markets` passes `collect_unregistered=True` and
  `load_all_async` exposes the sightings as `self._unregistered_city_sightings` beside the existing
  `_resolved_market_reasons`, logging **ONE** WARN per cycle naming every distinct city and its slug
  count — never one line per market. The WARN text names the cities, not a count only (memory
  `no-trade-day-diagnosis-gaps`). **This attribute is in-process state and is lost on restart; 08a
  makes no claim of durability.** Durability is 08b's sidecar, below.

### AUD-08b — the sighting sidecar, the register, and the notification

**Module placement decision (M1 accepted).** The record, the fold and the writer/reader go in
**`src/breezy/persistence/station_candidates.py`**, NOT in `adapters/polymarket_us/`. Reason: the
records already carry a `venue` field, and the plan's own portability justification is defeated if a
second venue adapter must import a sibling venue adapter to reuse them. Layer legality:
`persistence` sits below `adapters` in the `[tool.importlinter]` layers contract
(pyproject.toml:71-101), so the PM.us provider importing this module is a **downward** import and
legal; the reverse would not be. The module imports nothing above `domain`. Only the
*production* of sightings stays in the provider.

#### 6b.1 The sighting sidecar — a first-class artefact (round-2 A8-1 / M5 accepted)

Round 2 found revision 2's emitter reading "the recorder's sighting sidecar (written by 08a)" while
08a's own change list wrote no file, and §1 declared 08a artefact-free. Both reviewers were right
and the contradiction is resolved **by moving the sidecar into 08b and specifying it to the same
standard as the register**, not by weakening either statement.

| Field | Value |
|---|---|
| Module | `src/breezy/persistence/station_candidates.py` (same module as the register — one schema family, one import) |
| Path | `~/.local/share/breezy/derived/station_candidates/sightings/sightings-<UTC YYYY-MM-DD>.jsonl` |
| Record | `UnregisteredCitySighting` (fields below) + `schema_version` |
| `schema_version` | `SIGHTING_SCHEMA_VERSION: Final[int] = 1` |
| Writer | `append_sighting(path, sighting)` — `open(path, "a", encoding="utf-8")` on an `O_APPEND` handle, **one `json.dumps(...) + "\n"` per `write()` call**, flushed and closed per cycle |
| **Single sanctioned writer** | **the recorder process only.** Enforced by construction, not by convention: `PolymarketUSInstrumentProvider` gains a `SightingSink` capability (a one-method Protocol, mirroring `runtime/health.py:385 AlertSink`), **attached after construction**, never passed as a constructor/cache-key parameter. Two processes run this provider (the recorder and the trade node, §12) — which is exactly why the writer is an injected capability rather than a module-level path. The discriminator, the resolution path and the `lru_cache` interaction are decided in full immediately below |
| Concurrency rule | Exactly one writer by construction (above). No lock is specified **because none would be correct**: a lock would make two writers *work*, which is not the property wanted. A second writer is a defect, and **A14** is the test — since round 3 it asserts **both** halves: the trade-node composition attaches no sink, *and* exactly ONE `PolymarketUSInstrumentProvider` is constructed per process across both factories |
| Reader | `read_sightings(path) -> tuple[UnregisteredCitySighting, ...]` in the same module |
| Unknown version | a line whose `schema_version` is not `SIGHTING_SCHEMA_VERSION` raises `UnknownSightingSchemaError` naming path, line number and version seen — the emitter **refuses**, never guesses |
| Crash behaviour | a **trailing** partial line (the last line only, no `\n`) is skipped with a WARN and counted in the emitter's summary — a recorder killed mid-`write()` is the expected case and must not brick the nightly emitter. A malformed line that is **not** the last line is a hard refusal: it means interleaving, i.e. the two-writer defect |
| Rotation / retention | one file per UTC day by filename. **The day is resolved PER APPEND, never once at attach (round-4 a1)**: `append_sighting` recomputes `sightings-<UTC day>.jsonl` on every call and reopens the handle when the day changes. The day source is the **sighting's own `observed_ts_ns`**, converted to UTC — not the wall clock — so a line can never land in a file whose day differs from the day the record itself claims, and the emitter's filename-keyed fold and `last_folded_day` watermark stay consistent with the records they read. This is load-bearing because the recorder is long-running: a filename resolved once at attach would write days D+1…D+n into D's file, and the emitter would advance the watermark past D and make them unreachable. Residual, stated: a sighting produced by an in-flight reload cycle *after* the emitter has folded and pruned that day is lost — bounded by the venue re-sighting the city on the next cycle (§9). The emitter deletes sidecar files older than **35 days** after a successful fold (the register is the durable record; the sidecar is its input tape) |
| Idempotency | the fold is keyed on `(venue, city_token)` and is a no-op for a day already folded (A7), so re-reading the same sidecar twice changes nothing |

- `@dataclass(frozen=True, slots=True, kw_only=True) UnregisteredCitySighting`:
  `schema_version: int, venue: str, city_token: str, slug: str, climate_date: str,
  observed_ts_ns: int`.

**The provider's call-site for the sink, named (round-4 a1).** The one write path in this design is
`PolymarketUSInstrumentProvider.load_all_async`, at the point where it already assigns
`self._unregistered_city_sightings` and emits the single per-cycle WARN (§6a): immediately after
those two, the provider calls `sink.append(sighting)` once per sighting, `if self._sighting_sink is
not None`. It is **never** called from `_weather_market_payloads` (`provider.py:190-229`, a pure
payload parser that must stay I/O-free and is also the function `discovery_candidate_slugs` calls at
`:187`) nor from `_discover_markets` (which runs per payload page). One cycle, one flush, one WARN,
one set of appends — which is also what makes "flushed and closed per cycle" true.

**The discriminator and the cache key (round-3 A8-3 accepted in full).** Revision 3 said the sink was
"supplied at `factories.py:517` by the recorder composition" and named no field, and it proposed to
pass the sink *through* `_shared_polymarket_us_instrument_provider` — which is decorated
`@lru_cache(maxsize=1)` (`src/breezy/adapters/polymarket_us/factories.py:516`, signature
`(client, provider_config, discovery, clock)` at `:517-521`) and is called from **both** `create()`s:
the data factory at `factories.py:589-594` (`_shared_polymarket_us_instrument_provider(http_client,
_instrument_provider_config_for(config), config.market_discovery, clock)`) and the exec factory at
`:722` (the identical call over `venue_config`). The module comment at `:432-446` states the
invariant those two calls rest on — both factories call the same `@lru_cache(1)` getters "with an
equal-valued `config`, so exactly ONE transport (and therefore ONE rate-limiter token bucket), ONE
signer and ONE instrument provider exist for the process, never two independently-quota'd clients",
and `lru_cache` "raises `TypeError` if a config is ever unhashable" rather than silently building a
second graph. A sink object passed as a further argument makes the two call sites' cache keys
unequal, evicts at `maxsize=1`, constructs **two** `PolymarketUSInstrumentProvider`s, reinstates the
R-4 divergence the docstring at `:523-529` says this function dissolves, and puts **two appenders on
one sidecar inside one process** — the exact interleaving §9 treats as a hard refusal. Both halves
are therefore decided here, not left to the implementer:

| Question | Decision |
|---|---|
| **Discriminator** | **`config.subscribe_trades`** (`src/breezy/adapters/polymarket_us/config.py:333`, `subscribe_trades: bool = False` on `PolymarketUSDataClientConfig`). It already means "this process is the recorder" and nothing else: its own comment at `config.py:322-332` reads *"this is the quote-tape RECORDER's knob, set in `breezy.runtime.node_config.build_quote_tape_node_config` … The live trade node keeps the default and its wire traffic unchanged"*, and `factories.py:619-622` repeats it verbatim at the one other place it is read. **No new config field is added.** Rejected alternative — a new explicit field (e.g. `sighting_sink_enabled`) on `PolymarketUSMarketDiscoveryConfig`: it would be a *second* flag meaning "this process is the recorder", i.e. a standing drift surface against `subscribe_trades` (exactly the defect `config.py:318-320`'s "Never derived from `recorder_instance_id` or any other shared flag (L-6)" comment guards in the other direction), for no capability `subscribe_trades` does not already carry |
| **Which `create()` resolves it** | **`PolymarketUSLiveDataClientFactory.create` only** — `factories.py:589-594` is inside it, and `config` there IS the `PolymarketUSDataClientConfig` carrying the flag. Verified sufficient: the recorder registers **only** a data client factory (`src/breezy/runtime/quote_tape_cli.py:188`, `node.add_data_client_factory(...)`; there is no `add_exec_client_factory` anywhere in `quote_tape_cli.py`), while the trade node registers both (`src/breezy/runtime/trade_cli.py:402,405`). The exec factory therefore never runs in the recorder process and needs no discriminator at all |
| **Cache key** | **unchanged.** The sink is **not** a parameter of `_shared_polymarket_us_instrument_provider`. That function's signature — and therefore both call sites' `lru_cache` keys — stays exactly `(client, provider_config, discovery, clock)`, equal-valued and hashable at `:589-594` and `:722`, so `maxsize=1` still yields one provider |
| **How the sink reaches the provider** | **attached after construction.** In the data factory: `instrument_provider = _shared_polymarket_us_instrument_provider(...)` (unchanged), then `if config.subscribe_trades: instrument_provider.attach_sighting_sink(_shared_sighting_sink(str(SIGHTINGS_DIR)))`. `attach_sighting_sink` is **idempotent by identity** — re-attaching the same object is a no-op; attaching a *different* object raises `SightingSinkAlreadyAttachedError`. `_shared_sighting_sink` is itself a module-level `@lru_cache(maxsize=1)` getter over one hashable `str` directory argument, mirroring the module's existing `_shared_*` idiom (`factories.py:452,485,493,503,516`), so one process holds exactly one sink and exactly one open append handle |
| **Order independence** | the attach acts on the single cached provider whichever `create()` ran first, so the invariant cannot depend on Nautilus's client-construction order |

No Nautilus mechanism is added or bypassed: `@lru_cache`-shared module-level factory getters are the
shipped adapter idiom this module already cites at `factories.py:432-446`
(`nautilus_trader.adapters.polymarket.factories.get_polymarket_http_client` /
`get_polymarket_instrument_provider`, each `@lru_cache(1)` and called from both `create()`s). This
decision keeps that idiom intact rather than widening its key.

#### 6b.2 The register

- `@dataclass(frozen=True, slots=True, kw_only=True) StationCandidate`:
  `schema_version: int, venue: str, city_token: str, origin: Origin, first_seen_day: str,
  last_seen_day: str, distinct_slugs: int, distinct_climate_days: int, sufficiency: Sufficiency`.
- `Origin = Literal["SIGHTING", "REGISTRY_SEED"]` — *round-2 change (A8-2 accepted)*, see 6b.3.
- `STATION_CANDIDATES_SCHEMA_VERSION: Final[int] = 1` (M3 accepted).
- **Record key:** `(venue, city_token)`, where **`city_token` is ALWAYS the venue's lowercase
  token** — the `venue_city_token` of `src/breezy/registry/sites.toml` (`:121` gives
  `venue_city_token = "nyc"` under site key `[sites.polymarket_us.NYC]` at `:117`) — and **never**
  the registry's uppercase site key. Stated once here and binding on every input: it is already the
  domain a *sighting* is in (`parsed.city` tested against `city_set = city_codes`,
  `provider.py:221`, where `city_codes` is derived by `discovery_city_codes_from_registry`,
  `src/breezy/adapters/polymarket_us/config.py:155-183`, which refuses any non-lowercase code at
  `:214`), and §6b.3's seed path is derived into the same domain (round-3 A8-4). **Merge rule:**
  `first_seen_day` never moves;
  `last_seen_day` is monotone non-decreasing; `distinct_*` are monotone; `origin` never changes once
  set; ordering is deterministic by `(venue, city_token)`. Stated here *and* pinned as A5/A6.
- **Idempotency key:** `(venue, city_token, last_seen_day)` — re-running the emitter on the same day
  with the same sightings is a byte-identical no-op.
- **Retention (round-2 a3 accepted).** The register has no time-based expiry — a candidate is a
  standing fact and `first_seen_day` is evidence. It has a **bound**: the fold refuses to grow the
  register beyond the flood cap of §9 in one day, and a record whose `last_seen_day` is more than
  **180 days** old is **compacted, not deleted**: its `distinct_slugs`/`distinct_climate_days` are
  frozen and it is rewritten with `sufficiency` recomputed once and a `last_seen_day` left as-is.
  Compaction is idempotent and changes no key. Rationale for keeping rather than expiring: the whole
  value of the artefact is answering "has this venue ever listed city X", which an expiry would
  destroy. Pinned as **A15**.

#### 6b.3 The fold — two named inputs, so NYC has a producer (round-2 A8-2 accepted)

Round 2 established that revision 2's NYC claim and **A9** were unreachable: a sighting exists only
when `parsed.city not in city_set` (`provider.py:221`), NYC **is** in `city_codes` (it is one of the
five `(polymarket_us, city)` registry pairs, `sites.toml:117,…`), so NYC could never produce a
sighting, and three of the four `Sufficiency` values had no producer at all. The finding is accepted
in full. The fix is a **second named input**, not a deletion of the claim:

```
def merge_sightings(
    existing: Sequence[StationCandidate],
    sightings: Sequence[UnregisteredCitySighting],
    *,
    seed_cities: Sequence[tuple[str, str]],   # (venue, city_token), registry-derived
    today: str,
    sufficiency_by_city: Mapping[tuple[str, str], Sufficiency],
) -> tuple[StationCandidate, ...]
```

- `seed_cities` is computed **in the script**, not the fold, and **in the `venue_city_token`
  domain** (*round-3 A8-4 accepted*). Revision 3 emitted `default_registry().pairs()` pairs
  directly; `pairs()` returns the registry's `(venue, city)` **site keys**
  (`src/breezy/registry/sites.py:348-350`, "All `(venue, city)` pairs known to this registry"),
  i.e. `"NYC"` from `[sites.polymarket_us.NYC]` (`src/breezy/registry/sites.toml:117`; siblings
  `.SFO/.MIA/.MDW/.LAX` at `:154,193,239,279`). A seeded row would then key on
  `("polymarket_us","NYC")` while a sighting of the same city keys on `("polymarket_us","nyc")`:
  the "seeded and later sighted" merge rule below could **never** fire, the register would hold two
  rows for one city against A6's uniqueness premise, and **H1's join would break across the plan
  boundary** — `SiteRegistry.site_for_venue_city_token` (`src/breezy/registry/sites.py:393-401`)
  raises `SiteNotFoundError` for `"NYC"`, so AUD-09a's census would fail on the only row this
  register is expected to hold on PM.us. **Corrected derivation**, reusing the accessor the
  discovery config already uses rather than a second path: for each `(registered_venue, city)` from
  `default_registry().pairs()` (the same enumeration `settlement_alignment_study.load_sites` uses,
  `settlement_alignment_study.py:638-641`) with `registered_venue == venue`, emit
  `(venue, active_registry.venue_symbology(registered_venue, city).venue_city_token)` — the
  identical comprehension body to `discovery_city_codes_from_registry`
  (`src/breezy/adapters/polymarket_us/config.py:166-173`) — keeping **only** the pairs whose
  **station code** (`city`, the uppercase site key) is **not** in `SUPPORTED_STATIONS`
  (`config.py:76`). On `polymarket_us` today that set is exactly
  **{`("polymarket_us", "nyc")`}**. H1's `site_for_venue_city_token` join is valid on that token,
  and the four supported cities are filtered out before the join is ever attempted.
- Key rule for a seed: the same record key `(venue, city_token)`, with `origin="REGISTRY_SEED"`,
  `first_seen_day` = the day the seed was first folded, `distinct_slugs`/`distinct_climate_days`
  = 0 (a seed is not a sighting and never counts slugs). A city that is both seeded and later sighted
  keeps `origin="REGISTRY_SEED"` — origin records *how it entered*, and the seed entered first.
- **`Sufficiency` alphabet, now with a producer for each value:**
  `NO_SETTLEMENT_TRUTH` — no `(venue, city)` pair in `default_registry()`; true of every **sighting**
  by construction. `REGISTRY_ONLY_NO_CAPTURE` / `CAPTURED_INSUFFICIENT` / `CAPTURE_SUFFICIENT` —
  produced by the **seed** path, which is the registered-but-unsupported case (NYC). No value is
  dead on arrival, which was round 2's YAGNI objection.
- Sufficiency is **computed in the script and passed into the pure fold as data** (M4 accepted);
  `merge_sightings` never computes it and never does I/O. The script computes it with **no venue
  call**, from one integer:
  `count_covered_listed_station_days_from_catalog(catalog_root=catalog_root, cities=(city,))`.
  That function is **keyword-only** —
  `def count_covered_listed_station_days_from_catalog(*, catalog_root: Path, cities: Sequence[str] =
  DENSE_STATIONS, fetch_start: dt.date = ASOS_FETCH_START, fetch_end: dt.date = ASOS_FETCH_END) ->
  int` (`scripts/analysis/structural_dead_stop.py:219-225`) — so `catalog_root=` is passed by
  **keyword** (*round-3 a1 accepted*: revision 3 wrote it positionally, which is a `TypeError` at
  runtime and a strict-mypy error in `scripts/analysis`, a directory this plan itself notes is
  strict-covered, pyproject.toml:177). `cities=` is passed explicitly rather than accepting the
  `DENSE_STATIONS` default; the argument is the **station code** (the uppercase registry site key,
  the same domain `DENSE_STATIONS` is built from — `spec.city for spec in load_sites()`,
  `cli_basis_setup_win_rate_study.py:126-128`), *not* the lowercase `city_token` the register keys
  on. That function lives in `scripts/` and is unimportable from `src/breezy/**`; the seam above is
  exactly why the computation is the *script's* job. The ≥30 min afternoon-coverage rule
  (`structural_dead_stop.py:214`) is reused unmodified so the register and the KILL clock cannot
  disagree about "covered".
- **`catalog_root` is bound by name, and an unreadable catalog REFUSES rather than reading as `0`
  (round-4 A8-6 accepted in full).** Revision 4 wrote `catalog_root=catalog_root` without ever
  saying what binds `catalog_root`, and that parameter has **no default**
  (`structural_dead_stop.py:219-225`). Two consequences, both verified at source this round, made
  the omission *silently permissive* — the same shape this plan refuses everywhere else:
  1. **A wrong or absent root reads as `count=0`, i.e. a legitimate-looking
     `REGISTRY_ONLY_NO_CAPTURE`.** `count_covered_listed_station_days_from_catalog` performs **no
     root check of any kind** (`:219-251`): `discover_station_days` over a non-existent
     `depth_root` simply yields nothing and the function returns `0`, which §6b.3's mapping above
     turns into a *valid* sufficiency. A misconfiguration and a genuinely uncaptured city would be
     indistinguishable in the artefact.
  2. **An unhandled refusal.** The same call reaches `_resolved_gaps_from_catalog`, which raises
     `QuoteTapeGapDataUnavailable` when the gap partition cannot be read (`:253-266`). §9 did not
     enumerate it, so the nightly emitter would have aborted on an uncaught exception.
  That the shipped CLI guards all three itself is the proof the *library* call does not: `main()`
  refuses a non-directory root at `structural_dead_stop.py:355-361`, records
  `depth_root_present = depth_root.is_dir()` at `:363-365`, and catches
  `QuoteTapeGapDataUnavailable` at `:373-376`. The emitter is **not** `main()`, so it carries the
  same three guards itself.
  - **Binding, by name.** `scripts/analysis/station_candidate_register.py` takes a `--catalog-root`
    flag with `default=str(DEFAULT_QUOTE_TAPE_CATALOG)` — the identical `argparse` shape
    `structural_dead_stop.py:275-279` uses, over the identical constant
    (`DEFAULT_QUOTE_TAPE_CATALOG`, `ma_prelock_winner_ask_study.py:187`) — and the
    `breezy-quote-tape-rotate` wrapper passes
    `--catalog-root "${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}"`,
    resolved **byte-identically to `score-live-trials-run.sh:57-60`**, whose own comment states that
    env var names the same root `breezy-quote-tape(-ingest).service` already writes. This is the
    same env-then-constant resolution AUD-09's census applies to its `$QUOTE_CATALOG` (AUD-09
    §6b.3), so the two items can never read different catalogs.
  - **Refusal semantics — REFUSE, never `0`.** Before computing any sufficiency the emitter asserts
    `catalog_root.is_dir()` **and** `(catalog_root / "data" / "order_book_depths").is_dir()` (the
    `depth_root_present` distinction the shipped counter emits precisely because it matters), and it
    wraps the counter call in `except QuoteTapeGapDataUnavailable`. On **any** of the three — root
    absent or unreadable, `depth_root_present == false`, or the gap refusal — the emitter **exits
    non-zero having written nothing**: the register keeps its previous contents, the
    `last_folded_day` watermark is **not** advanced, and no sidecar is pruned. No seed row is ever
    written with a sufficiency derived from an uncounted catalog, so `REGISTRY_ONLY_NO_CAPTURE`
    means only what it says. **Chosen over "keep the previous value"** because a partially-computed
    fold is exactly the silently-permissive shape, and because "keep the previous value" has no
    answer for the *first* fold, where there is no previous value to keep.
  - **Alert path and watermark stay coherent under the refusal.** Nothing is lost: the unadvanced
    watermark means every unpruned sidecar day is re-folded on the next successful run (A17), and
    because a record's `first_seen_day` is the **fold** day (the fold's `today` argument, §6b.3), a
    fold delayed by a catalog outage *delays* the one-shot `BREEZY_STATION_CANDIDATE_NEW` alert
    rather than skipping it — `first_seen_day == today` still holds on the day the record first
    appears (A16). A catalog outage that persists is caught by §9's existing rule: three
    consecutive failed emissions escalate through the shipped alert sink.
- **The integer → `Sufficiency` mapping, stated (round-3 A8-5 accepted).** Revision 3 left the
  threshold to the implementer, so **A9** asserted only that sufficiency "agrees with" an `int`,
  which is not a testable predicate — and the threshold is the one number that decides whether a
  candidate reads as testable. The mapping is a total function of that count,
  `sufficiency_from_covered_listed_days(count: int) -> Sufficiency`, in
  `scripts/analysis/station_candidate_register.py`:

  | `count` | `Sufficiency` |
  |---|---|
  | `count < 0` | unreachable — the counter returns a non-negative `int`; the script raises `ValueError` rather than encode a fourth arm |
  | `count == 0` | **`REGISTRY_ONLY_NO_CAPTURE`** — registered in settlement truth, never captured |
  | `1 <= count < MIN_STRUCTURAL_DEAD_STATION_DAYS` | **`CAPTURED_INSUFFICIENT`** |
  | `count >= MIN_STRUCTURAL_DEAD_STATION_DAYS` | **`CAPTURE_SUFFICIENT`** |

  **Source constant, imported never re-declared, and why it is the right one.**
  `MIN_STRUCTURAL_DEAD_STATION_DAYS` (`scripts/analysis/structural_dead_stop.py:85`), which is
  `MIN_AFTERNOON_STATION_DAYS` — imported at `structural_dead_stop.py:58` and defined
  `MIN_AFTERNOON_STATION_DAYS: Final[int] = 15`
  (`scripts/analysis/ma_prelock_winner_ask_study.py:163`). It is the right constant because this
  register's question is the *same* question the KILL clock asks of the same counter's output:
  are there enough covered-listed afternoon station-days to discriminate? That module's own comment
  at `:82-84` says the stop "shares the exact same '15 station-days to discriminate' floor, never a
  second, potentially-drifting literal", and `tests/unit/test_structural_dead_stop.py:99` pins
  `MIN_STRUCTURAL_DEAD_STATION_DAYS == MIN_AFTERNOON_STATION_DAYS == 15`. Inventing a second
  threshold here would create exactly the drift that pin exists to prevent. **No new constant is
  declared**; the script imports it via the established cross-script `sys.path.insert` idiom
  (`structural_dead_stop.py:48`). Note this register **never** re-derives the KILL verdict — it
  reuses the floor, not `structural_dead()`.
  `NO_SETTLEMENT_TRUTH` is deliberately **not** in this mapping: it is the *sighting* path's value,
  assigned without calling the counter at all, because a sighting has no `(venue, city)` registry
  pair and therefore no station whose days could be counted.

#### 6b.4 Writer, emitter, notification

- **Writer/reader:** `write_station_candidates(path, candidates)` and
  `read_station_candidates(path) -> tuple[StationCandidate, ...]`, both in the same module. JSONL at
  `~/.local/share/breezy/derived/station_candidates/station_candidates.jsonl`, one line per
  candidate, stable key order, atomic temp + `os.replace`. **`read_station_candidates` refuses a
  line whose `schema_version` is not `STATION_CANDIDATES_SCHEMA_VERSION`**, raising
  `UnknownStationCandidateSchemaError` naming the path, the line number and the version seen — it
  never guesses and never silently skips.
- **Emitter:** extend the existing `deploy/systemd/breezy-quote-tape-rotate.service` wrapper with one
  extra Python invocation `scripts/analysis/station_candidate_register.py`, rather than adding a
  fifth timer. It folds **every unpruned sidecar day since a watermark** (*round-3 a3 accepted*).
  Revision 3 read "yesterday's and today's" files — a two-day window **shorter than §9's
  three-consecutive-failure escalation tolerance**, so a recovered emitter permanently skipped the
  days it missed and self-healing rested on an assumption about the venue re-listing the city rather
  than on a property of the design. The watermark is `last_folded_day`, a one-line JSON sidecar at
  `~/.local/share/breezy/derived/station_candidates/last_folded_day.json`
  (`{"schema_version": 1, "last_folded_day": "<UTC YYYY-MM-DD>"}`, atomic temp + `os.replace`,
  advanced **only** after a successful fold *and* a successful register write). The emitter folds
  every `sightings-<day>.jsonl` with `day > last_folded_day`, in ascending day order, bounded above
  by the 35-day pruning horizon. An **absent or unknown-version** watermark means "fold every
  unpruned sidecar file present" — safe, because the fold is idempotent under §6b.2's key (A7). A
  day whose file was pruned before it could ever be folded is reported in the summary line as
  `sidecar_days_lost`, so the residual bounded loss is observable rather than silent. It then
  computes `seed_cities` and `sufficiency_by_city`, folds, writes the register, compacts per A15,
  advances the watermark, and prunes sidecars older than 35 days. Disk-only, sub-second, no
  `breezy-studies.slice` budget. Pinned as **A17**.
  `scripts/analysis` is inside `[tool.mypy] files` (pyproject.toml:177) and `strict = true`
  (`:158`), so this script is strict-typed like the rest.
- **Notification — the new-candidate alert (round-2 tba minor accepted; coordinator-required).**
  When the fold produces a record whose `first_seen_day == today` **and** `origin == "SIGHTING"`,
  the emitter emits exactly one alert through the **already-shipped** path:
  `resolve_alert_sink(os.environ)` (`src/breezy/runtime/health.py:579`) then
  `emit_alert(sink, AlertPayload(...))` (`:668`), with
  `event="BREEZY_STATION_CANDIDATE_NEW"`, `site=f"{venue}/{city_token}"`, `severity="warning"`, and
  a `detail` that names **the act to open and its owner**: *"new venue city <token> recorded; to make
  it eligible a strategy-lead ruling under docs/evidence/ plus the sites.toml re-verification gate
  must be opened — see AUD-08 §6c"*. `AlertPayload.detail` is truncated to `MAX_ALERT_DETAIL_CHARS`
  and, by that class's own docstring, must carry **no absolute filesystem path and no state dump** —
  the detail above satisfies both.
  - **Once per candidate, not per night.** The dedupe is the **register itself**, not
    `runtime/health.AlertState`: `AlertState` is explicitly in-memory, per-process and never
    persisted (its own docstring: *"Cold start … there is no constructor parameter to seed prior
    state from a persisted source, and none should be added"*), so in a nightly one-shot every
    condition would cold-start `False` and re-fire every single night. Keying on
    `first_seen_day == today` is a durable, once-per-candidate property of the artefact. Pinned as
    **A16**, tested by folding the same candidate on two consecutive days and asserting exactly one
    emitted payload.
  - A seeded (`REGISTRY_SEED`) row never alerts: NYC's exclusion is a known standing fact, not news.

- **NYC** is the one registered-but-unsupported city (`config.py:74-75,88-95`: A14, hourly-only feed,
  50 min staleness bound miscalibrated). It is not a *discovery* candidate — it is already
  discovered and traded-refused upstream — but the register now records it **via the seed input**
  with its real capture-derived sufficiency, which makes the exclusion legible outside a docstring
  for the first time. *Round-2 note:* revision 2 made this claim with no producer; 6b.3 supplies one.

### 6c. Hand-offs, and the full path from candidate to eligibility

**H1 — AUD-08b → AUD-09a: REAL, and specified identically in both plans.**

| Field | Value |
|---|---|
| Artefact | `~/.local/share/breezy/derived/station_candidates/station_candidates.jsonl` |
| `schema_version` | `1` (`STATION_CANDIDATES_SCHEMA_VERSION`) |
| Writer | `breezy.persistence.station_candidates.write_station_candidates`, called by `scripts/analysis/station_candidate_register.py` |
| Reader | `breezy.persistence.station_candidates.read_station_candidates`, called by `scripts/analysis/replay_sufficiency_census.py` (AUD-09a) |
| Join key | `(venue, city_token)`, mapped to a station code by the registry's `venue_city_token` → site mapping |
| Unknown version | `UnknownStationCandidateSchemaError` — the census **fails**, never degrades |
| Idempotency key | `(venue, city_token, last_seen_day)` |

What AUD-09a does with it, stated here so the two plans cannot drift: for every candidate, the
census emits one census row with verdict `INSUFFICIENT` and reason
**`CANDIDATE_UNSUPPORTED_STATION`**, carrying the candidate's sufficiency. It is **not** added to
the replay queue — no station outside `SUPPORTED_STATIONS` can be replayed, because the frozen
archive table and the strategy allow-list both cover four stations only. The value of the read is
that "why is there no replay for city X" becomes answerable from one artefact instead of being
silent. That is the G-05 → G-06 connection, at its honest strength.

**H2 — AUD-08b → AUD-10: DECLINED, with no residual read (round-2 a2 / 10-2 accepted).**
A promotion proposal cannot widen the station allow-list: `SUPPORTED_STATIONS` is closed, the frozen
archive table covers those four stations only (`config.py:74-76`), and widening it is a class-C act
requiring a ruling artefact plus a `sites.toml` re-verification. A candidate therefore cannot enter
a proposal by any legitimate path; it enters a **ruling**. AUD-10b consequently does **not** read
this artefact, and instead carries a `C-STATIONS` criterion that is a **pure subset predicate over
the proposal's own stations** — it refuses any proposal whose stations are not a subset of
`SUPPORTED_STATIONS`, and it records reason `EXPANSION_REQUIRES_RULING`.
*Round-2 correction:* revision 2 additionally had `C-STATIONS` record "the register's candidate
count", which **requires reading the register** and therefore made "declined" false, while giving
that read no reader, no unknown-version rule and no missing-file rule — and AUD-10b's own refuse-on-
missing-input rule would then have made a missing register refuse a promotion proposal, which is
absurd. **The count clause is deleted from all three plans.** The visibility it was reaching for is
supplied properly by the new-candidate alert (6b.4), which is a push to a human rather than a number
buried in `criteria.json`. Justification against **G-07** is unchanged: promotion stays a human
decision on a machine-checked proposal; station *expansion* is a different, higher gate and is not
laundered through the promotion path.

**The eligibility sequence (round-2, coordinator-required; stated identically in AUD-08/09/10).**
A new station becomes tradable only through this ordered path. Steps marked **OUTSIDE** are not in
this backlog and no item here plans them:

| # | Step | Owner | In this backlog? |
|---|---|---|---|
| 1 | Venue lists a city with no registry entry → **sighting** recorded in the sidecar, folded into the register | automated (AUD-08a + AUD-08b) | **AUD-08** |
| 2 | **One alert**, on first appearance, naming the ruling to open and its owner | automated (AUD-08b §6b.4) | **AUD-08** |
| 3 | A **ruling artefact** under `docs/evidence/` authorising expansion, **and** the `src/breezy/registry/sites.toml` pre-production re-verification gate (independent live read-only `issuing_office` + body-header assertion) | strategy lead (ruling) + operator (gate) | **OUTSIDE** |
| 4 | **Archive-table extension / calibration** for the new station and widening `SUPPORTED_STATIONS` — the frozen corpus pin (`archive_table.CORPUS_SHA256`, enforced by `ArchiveTablePinMismatchError`, `config.py:261-265`) means a fifth station has no measured table today | strategy lead + implementer | **OUTSIDE** (excluded by AUD-08 §5 and AUD-10 §5) |
| 5 | **Capture**: a WS subscription for the new city, within the shared MARKET_DATA+TRADE subscription cap (memory `venue-ws-subscription-cap-is-shared`) — adding legs can degrade the YES tape | implementer, with its own cap evidence | **OUTSIDE** (AUD-08 §12 open question) |
| 6 | The station's days become **SUFFICIENT** in the census and are **replayed** | automated (AUD-09) | **AUD-09**, but only after 4 and 5 |
| 7 | A **promotion proposal** may name the station, because step 4 widened `SUPPORTED_STATIONS` and `C-STATIONS` is a subset predicate | automated (AUD-10b) | **AUD-10**, but only after 4 |
| 8 | **Arming**: four separate human acts — commit the manifest into `deploy/families/`, pin the artefact shas, change `sending_family_id`, file the class-C ruling | operator + strategy lead | **OUTSIDE** (AUD-10 §5, §9) |

The honest reading of this table: **AUD-08 owns steps 1–2 and nothing else.** Steps 3–5 and 8 are
human/ruling acts this backlog deliberately does not automate, and step 4 alone is a larger piece of
work than all of AUD-08. The table exists so that no reader mistakes a candidate record for
progress toward trading.

## 7. Ordered implementation steps (RED first)

1. **RED** `tests/unit/test_polymarket_us_discovery.py::
   test_an_unregistered_city_still_raises_when_collect_unregistered_is_false` — a golden pin that the
   default path is unchanged (characterisation; L-33 mutation evidence: flip the branch to
   `continue` unconditionally and show this test fails).
2. **RED** `…::test_an_unregistered_city_is_collected_and_the_registered_cities_still_load` — a
   payload with 4 registered cities + 1 unknown city yields 4 accepted payloads and 1 sighting.
3. **RED** `…::test_a_reload_cycle_with_an_unregistered_city_still_loads_tomorrows_cohort` — the
   livelock test proper: two consecutive `load_all_async` passes with the unknown city present both
   return the registered instruments. This is the test that closes §3's blast radius.
4. **GREEN** the two `@overload` declarations + `collect_unregistered` in `_weather_market_payloads`
   + the provider plumbing + the WARN. Run `mypy src/breezy` at this step, not at the end (A13).
5. **RED** `…::test_the_provider_exposes_one_warn_naming_every_unregistered_city` and
   `…::test_an_unregistered_city_never_becomes_an_instrument` (`provider.find(...)` is `None`;
   `active_market_slugs` excludes it).
6. **GREEN** the WARN and accessor. **AUD-08a ends here — no file has been written.**
7. **RED** `tests/unit/test_station_candidate_sightings.py` (08b begins): `append_sighting` writes
   one line per call; `read_sightings` round-trips; a trailing partial line is skipped with a WARN;
   a malformed **non-final** line is a hard refusal; `schema_version: 2` raises
   `UnknownSightingSchemaError` with path, line number and version; **and two appends whose
   `observed_ts_ns` straddle a UTC midnight land in two day-named files from one sink, with no
   filename resolved at attach time** (A12 rotation arm, round-4 a1).
8. **RED** `tests/unit/test_polymarket_us_factories.py::
   test_the_trade_node_composition_attaches_no_sighting_sink` (A14 (i)),
   `…::test_the_recorder_composition_attaches_one_file_backed_sink` (A14 (ii)), and
   `…::test_both_factories_construct_exactly_one_instrument_provider` (A14 (iii) — drive
   `PolymarketUSLiveDataClientFactory.create` **and** `PolymarketUSLiveExecClientFactory.create`
   in one process with equal-valued configs and assert provider identity).
9. **GREEN** the `SightingSink` Protocol, `append_sighting`/`read_sightings`, the module-level
   `@lru_cache(maxsize=1)` `_shared_sighting_sink(directory: str)` getter, the provider's idempotent
   `attach_sighting_sink` (+ `SightingSinkAlreadyAttachedError`), and the
   `if config.subscribe_trades:` attach inside `PolymarketUSLiveDataClientFactory.create`
   (`factories.py:589-594`). **`_shared_polymarket_us_instrument_provider`'s signature at
   `factories.py:517-521` is NOT touched** — that is the point of the decision in §6b.1.
10. **RED** `tests/unit/test_station_candidate_register.py`: `merge_sightings` is idempotent on a
    re-run of the same day under the stated idempotency key; `first_seen_day` never moves;
    `last_seen_day` is monotone; a city that disappears keeps its record; sufficiency is taken from
    `sufficiency_by_city` and never computed in the fold; **a `seed_cities` entry with no sighting
    produces a `REGISTRY_SEED` record with the seed's sufficiency** (A9); `origin` never changes;
    `read_station_candidates` raises `UnknownStationCandidateSchemaError` on `schema_version: 2`;
    the writer is atomic; a record older than 180 days compacts idempotently (A15); a seeded
    `("polymarket_us","nyc")` row plus a later sighting carrying the identical token collapse into
    exactly one record with `origin="REGISTRY_SEED"` (A6); `sufficiency_from_covered_listed_days`
    maps `0`/`14`/`15` to `REGISTRY_ONLY_NO_CAPTURE`/`CAPTURED_INSUFFICIENT`/`CAPTURE_SUFFICIENT`
    (A9); **an absent `--catalog-root`, an absent `data/order_book_depths`, and a
    `QuoteTapeGapDataUnavailable` refusal each make the emitter exit non-zero with the register
    byte-unchanged and `last_folded_day` unadvanced, and never emit `REGISTRY_ONLY_NO_CAPTURE`**
    (A9 fourth arm, round-4 A8-6); a three-day emitter outage folds all missed days on recovery and
    advances `last_folded_day` (A17).
11. **RED** `…::test_a_new_sighting_candidate_alerts_exactly_once_across_two_folds` (A16) and
    `…::test_a_registry_seed_never_alerts`, both against a recording fake `AlertSink`.
12. **GREEN** `src/breezy/persistence/station_candidates.py` + `scripts/analysis/
    station_candidate_register.py` (the `--catalog-root` flag defaulting to
    `DEFAULT_QUOTE_TAPE_CATALOG` plus the three pre-count guards of §6b.3, seed computation in the
    `venue_city_token` domain, `sufficiency_from_covered_listed_days`, the `last_folded_day`
    watermark read/advance, fold, write, alert, compaction, sidecar pruning).
13. **RED** a sibling assertion in `tests/unit/test_analysis_units_memory_capped.py` (or the rotate
    wrapper's own test) that the new invocation is inside the existing flock and slice discipline,
    **and that it passes `--catalog-root` resolved from `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG`
    exactly as `score-live-trials-run.sh:57-60` does** (round-4 A8-6).
14. **GREEN** the wrapper edit.
15. Gate: `scripts/ci/run_tests_no_egress.sh`, then `lint-imports`, then `mypy src/breezy`.
16. One dry run against a **recorded** discovery payload fixture (no live call), recording the
    emitted sidecar bytes and register bytes in the evidence doc.

## 8. Measurable acceptance criteria and required evidence

| # | Criterion | Evidence |
|---|---|---|
| A1 | A discovery payload with 4 registered + 1 unregistered city loads **4** markets and raises nothing | RED→GREEN for step 2 |
| A2 | Two consecutive reload cycles with the unknown city present both load the registered cohort — the livelock is gone | RED→GREEN for step 3 |
| A3 | The default (`collect_unregistered=False`) path is byte-identical: `discovery_candidate_slugs` still raises | step 1 + L-33 mutation evidence (2 perturbations, each failing a named test) |
| A4 | No unregistered city ever reaches `add()`, `active_market_slugs`, or a subscription | step 5 assertions |
| A5 | Exactly one WARN per cycle, naming every distinct unregistered city and its slug count | captured log text in the test |
| A6 | The register's record key is `(venue, city_token)` with `city_token` **always** the venue's lowercase token; `first_seen_day` never moves; `last_seen_day` is monotone; `origin` never changes; **and a seeded row plus a later sighting of the same city collapse into exactly ONE record with `origin="REGISTRY_SEED"`** (round-3 A8-4) | property tests from step 10, not a fixture byte-diff; the collapse arm seeds `("polymarket_us","nyc")`, folds a sighting carrying the identical token, and asserts `len(records) == 1` and `origin == "REGISTRY_SEED"` |
| A7 | Re-running the emitter on the same day is byte-identical under the idempotency key `(venue, city_token, last_seen_day)` | byte-diff of two consecutive emissions |
| A8 | `read_station_candidates` refuses an unknown `schema_version` with the path, line number and version seen | step 10 test |
| A9 | **A registry-seeded, registered-but-uncaptured city (`("polymarket_us","nyc")`) produces a `REGISTRY_SEED` record** whose `sufficiency` **equals** `sufficiency_from_covered_listed_days(count_covered_listed_station_days_from_catalog(catalog_root=<fixture>, cities=("NYC",)))` — an *equality* against §6b.3's stated mapping evaluated on the same fixture station-days, not an "agrees with". All three arms are pinned from one fixture family: `count=0` → `REGISTRY_ONLY_NO_CAPTURE`, `count=MIN_STRUCTURAL_DEAD_STATION_DAYS - 1` → `CAPTURED_INSUFFICIENT`, `count=MIN_STRUCTURAL_DEAD_STATION_DAYS` → `CAPTURE_SUFFICIENT`, with the boundary taken from the imported constant and never written as the literal `15` **Fourth arm (round-4 A8-6), asserting the absent-input behaviour rather than a value:** with `--catalog-root` pointing at a **non-existent** directory, and separately at a directory whose `data/order_book_depths` is absent, and separately with the counter raising `QuoteTapeGapDataUnavailable`, the emitter **exits non-zero, writes no register, leaves `last_folded_day` unadvanced and prunes no sidecar** — and in particular does **not** emit a row with `sufficiency="REGISTRY_ONLY_NO_CAPTURE"`. An absent catalog must never be readable as `count=0` | step 10 test driving both from one fixture; the fourth arm asserts exit code, the byte-unchanged register and the unchanged watermark. *Round-2: unreachable in revision 2 — §6b.3's seed input gives it a producer. Round-3 A8-5: the mapping it is an equality against is now stated, so the criterion has a pass condition. Round-4 A8-6: the absent-input arm closes the silently-permissive read.* |
| A10 | Zero new venue requests | request-count assertion against the fake HTTP client in `test_polymarket_us_provider.py` |
| A11 | `lint-imports` clean — `persistence` is an existing layer, so no `[tool.importlinter]` change is needed for this item | command output |
| A12 | **The sidecar round-trips, rotates, and survives a crash:** one line per `append_sighting`; a trailing partial line is skipped with a WARN and counted; a malformed non-final line refuses; an unknown `schema_version` raises `UnknownSightingSchemaError` with path/line/version; **and rotation is per append (round-4 a1)** — two `append_sighting` calls on one sink whose sightings' `observed_ts_ns` fall either side of a UTC midnight land in **two** files named for their own days, with no handle resolved at attach time | step 7 RED→GREEN, the rotation arm driving one sink across a synthetic UTC-midnight boundary |
| A13 | **`mypy src/breezy` is clean with the overloaded `_weather_market_payloads`**, and `discovery_candidate_slugs` still typechecks without a cast or `# type: ignore` | command output at step 4 and step 15 |
| A14 | **Exactly one process can write the sidecar, and exactly one provider exists that could:** (i) the trade-node composition attaches **no** sink (`config.subscribe_trades` is `False` there); (ii) the recorder composition (`subscribe_trades=True`) attaches the file-backed sink exactly once — a second `attach_sighting_sink` with the same object is a no-op, with a *different* object raises `SightingSinkAlreadyAttachedError`; (iii) **driving `PolymarketUSLiveDataClientFactory.create` and `PolymarketUSLiveExecClientFactory.create` in one process with equal-valued configs constructs exactly ONE `PolymarketUSInstrumentProvider`** — asserted both by identity (`data_provider is exec_provider`) and by `_shared_polymarket_us_instrument_provider.cache_info().misses == 1`. Clause (iii) is load-bearing: without it A14 can pass while the single-writer invariant is broken by cache eviction (round-3 A8-3) | step 8 RED→GREEN over `factories.py:516-521,589-594,722` |
| A15 | A register record older than 180 days compacts idempotently; no record is ever deleted; a second compaction is a byte-identical no-op | step 10 property test |
| A16 | **A new sighting-origin candidate emits exactly ONE alert across two consecutive folds**, whose `detail` names the ruling to open and its owner and contains no absolute path; a `REGISTRY_SEED` record emits none | step 11 RED→GREEN against a recording `AlertSink` |
| A17 | **A recovered emitter loses no sidecar day:** three sidecar days accumulate while the emitter fails, the fourth run folds **all** unpruned days newer than `last_folded_day` in ascending order and advances the watermark to the newest folded day; an immediate re-run is a byte-identical no-op; an absent watermark folds every unpruned file; a day pruned before it could be folded is counted in `sidecar_days_lost` (round-3 a3) | step 10 property test |

**Evidence artefact:** `docs/evidence/STATION_CANDIDATE_REGISTER_<date>.md` carrying A1–A17 and the
honest statement that the PM.us register is expected to hold exactly one row (the NYC seed) and zero
sightings.

## 9. Validation: failure cases, integration, autonomous operation

- **Malformed slug for an unregistered city.** `parse_weather_slug` returns `None` and the payload
  names a city → `provider.py:211-214` still raises. Unchanged, deliberately: a market Breezy cannot
  parse is a venue-shape event, not a candidate.
- **Flood.** Sightings are de-duplicated by `city_token` before logging, and the emitter refuses
  (loudly, exit non-zero, register untouched) a fold that would add **more new cities in one day
  than the number of `(venue, city)` pairs the settlement registry already holds for that venue**
  (5 for `polymarket_us` today). *Round-1 change (m4 accepted):* this replaces the uncited magic
  `32`. The cap is derived from a real property of the registry, scales with the venue, and its
  rationale is explicit: a one-day jump larger than the entire known surface is a venue-shape event
  needing a human, not an autonomous import.
- **Sidecar corruption / interleaving.** A malformed non-final line means two writers raced — the
  emitter refuses, exits non-zero, and the register is untouched. This is the loud failure the
  single-writer-by-construction rule (6b.1) exists to make impossible; if it ever fires, A14's
  premise has been broken and the register must not absorb the result.
- **Recorder crash mid-write.** Expected. The trailing partial line is skipped with a WARN; at most
  one sighting is lost, and the next cycle re-sights the same city (the venue keeps listing it), so
  the register self-heals on the following day.
- **Emitter outage across several days.** The `last_folded_day` watermark (§6b.4) makes recovery a
  property of the design rather than of the venue: every unpruned sidecar day newer than the
  watermark is folded on the next successful run, in order, and the residual (a day pruned before
  it could be folded, i.e. an outage longer than 35 days) is *counted and reported*, never silent.
  Pinned as **A17**.
- **The sufficiency counter refuses or its catalog is absent (round-4 A8-6).** Three distinct
  causes, one behaviour: the `--catalog-root` directory is absent or unreadable;
  `(catalog_root / "data" / "order_book_depths")` is absent (`depth_root_present == false`); or
  `count_covered_listed_station_days_from_catalog` raises `QuoteTapeGapDataUnavailable`
  (`structural_dead_stop.py:253-266`). In every case the emitter **exits non-zero having written
  nothing** — register untouched, `last_folded_day` unadvanced, no sidecar pruned — and it **never**
  substitutes `count=0`, which would have been recorded as a legitimate `REGISTRY_ONLY_NO_CAPTURE`
  and made a misconfiguration indistinguishable from an uncaptured city. Recovery is the watermark's
  (A17): the next successful run folds every unpruned day. Persistence is caught by the
  three-consecutive-failure escalation below.
- **Register corruption.** A JSONL line that fails to parse, or whose `schema_version` is unknown,
  is refused with the line number; the emitter exits non-zero and leaves the file untouched.
- **Repeated emitter failure.** Three consecutive failed emissions escalate through the shipped
  alert sink (`f97c26f`) rather than resting in the unit's failed state — the round-1 gap the
  baseline named but did not close.
- **Alert sink unconfigured.** `resolve_alert_sink` returns a bare `LoggingAlertSink` when
  `BREEZY_ALERT_WEBHOOK_URL` is unset (`health.py:579,607-611`), so the notification degrades to a
  local log line and never raises. `emit_alert` (`:668`) contains sink failures, so a webhook outage
  can never fail the emitter or corrupt the register.
- **Integration.** The trading node's composition is untouched: the builders still iterate their
  station set. The register is write-only from the node's perspective and is read only by AUD-09a's
  census (H1). The trade node writes no sidecar (A14).
- **Autonomous operation.** Emission rides an already-scheduled unit; a missed day self-heals via
  the existing `Persistent=true`; a permanently failing emitter surfaces as a failed unit **and** an
  alert; a **new candidate surfaces as its own alert once** (A16) rather than waiting on a periodic
  manual review.

## 10. Deployment, observability, rollback

- **Deploy:** library + script land with the merge; the wrapper edit is a one-line `ExecStart`
  addition to an already-installed unit — no new unit, no `systemctl enable`. The sink **attach**
  inside `PolymarketUSLiveDataClientFactory.create` (`factories.py:589-594`), gated on
  `config.subscribe_trades`, takes effect at the **recorder's** next restart
  (`breezy-quote-tape.service`); the trade node needs no restart at all, because its
  `subscribe_trades` is `False` and its code path is unchanged. Until the recorder restarts the
  sidecar is simply empty and the emitter reports zero sightings.
- **Observability:** one WARN per discovery cycle, the one-shot `BREEZY_STATION_CANDIDATE_NEW`
  alert, the emitter's summary line (sightings read, partial lines skipped, records written,
  records compacted, sidecars pruned), and the two artefacts.
- **Rollback:** revert the wrapper line (register stops updating), and/or revert the sink injection
  (sidecar stops growing), and/or revert the `collect_unregistered` flag (discovery returns to
  fail-stop). Three independent, non-stateful reverts, in that order of increasing blast radius. The
  register and sidecar files are additive and read by nothing that trades.

## 11. Relationship to portfolio-level ROI

**Demonstrated:** none. This adds **zero** trading capability on Polymarket.us and 08b is expected to
emit one seeded row and no sightings on the measured surface.

**Plausible, and stated as plausible:** (a) 08a removes a livelock whose realised analogue elsewhere
in this programme has cost days of silent non-trading; (b) 08b is the only seam by which an
expansion venue's larger city set becomes a *recorded and notified* input rather than a manual
`sites.toml` edit nobody is prompted to make.

**How it will be evaluated:** 08a by A1–A5 and A13 (mechanism); 08b by one number only — the count of
**sighting-origin** candidate records the AUD-09a census reads (seeded rows are excluded from this
count, since they are known in advance). If that count is 0 after 60 days AND no expansion venue
is in progress, 08b is recorded as *built, no candidates* and nothing further is invested. That is
an abandonment criterion, not a hedge. 08a is **not** subject to it: a latent-cliff fix is not
retired for failing to fire.

## 12. Assumptions, unresolved questions, blockers

- **Assumption (testable, untested here):** the venue's `GET /v1/markets` `categories=climate` page
  would in fact *return* a market for an unregistered city. Not observed — the surface has been 5
  cities throughout. If the venue never lists one, 08a closes a hazard that cannot fire and 08b's
  sighting path is provably empty (its seed path still produces the NYC row). Recorded honestly; it
  is the reason 08a is P1 and not P0 (§4).
- **Assumption (verified at source, round 3):** the recorder runs the same
  `PolymarketUSInstrumentProvider` (`breezy-quote-tape.service:92`; construction at
  `factories.py:516-537`), so it is the right emission point, and the trade node runs the same
  class — which is precisely why the sink is an attached capability discriminated by
  `config.subscribe_trades` (`config.py:333`) rather than resolved inside the provider, and why it
  is attached **after** construction rather than passed as an `lru_cache` key (§6b.1, A14).
  Also verified: the recorder registers only a data client factory
  (`src/breezy/runtime/quote_tape_cli.py:188`) while the trade node registers both
  (`src/breezy/runtime/trade_cli.py:402,405`), so the data factory is the only site that must
  resolve the discriminator.
- **BLOCKER (operator / strategy-lead, does NOT block this item):** adding any city to
  `src/breezy/registry/sites.toml` requires that file's own pre-production re-verification gate (independent
  agent, live read-only `issuing_office` + body-header assertion). A candidate record explicitly does
  **not** authorise that; it queues it, and since round 3 it also *announces* it (§6b.4). See §6c
  step 3.
- **BLOCKER (strategy lead, OUTSIDE this backlog, named so the sequence is honest):** a fifth
  station has no measured archive table. Extending or recalibrating the frozen corpus (§6c step 4)
  is a larger piece of work than all of AUD-08 and is not planned here.
- **Open question (no decision taken here):** whether a candidate should ever auto-promote to a
  capture subscription. Deliberately **not** designed: capture is bounded by a shared WS
  subscription cap across MARKET_DATA + TRADE (memory `venue-ws-subscription-cap-is-shared`),
  so adding legs can degrade the YES tape, the only asset the programme has. Any such proposal must
  carry its own cap evidence. §6c step 5.

## 13. Review history

**Baseline self-score (2026-09-21, author):** 81/100 — see round-1 records for the per-criterion
table as reviewed.

### Round 1

- **trading-bot-architect (autonomous-loop/pipeline lens): 78/100 · NOT READY**
- **code-architect (module boundaries, data contracts, layering, portability): 67/100 · NOT READY**

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL** — 08a's priority mismatched to blast radius; the abort poisons the whole payload and starves the four traded stations | tba | **ACCEPTED.** Split re-cut so 08a is its own sub-item (§1); re-scored **P2 → P1** with the blast radius conceded in full (§3 "Blast radius", §4); the evidenced urgency counter-argument for P1-not-P0 is stated in §4; a dedicated livelock RED test (§7 step 3) and criterion **A2** added. |
| **MATERIAL M1** — venue-namespaced module defeats the portability claim | ca | **ACCEPTED.** Record/fold/writer/reader moved to `src/breezy/persistence/station_candidates.py`; only sighting *production* stays in the provider; layer legality argued from pyproject.toml:71-101 (§6b). |
| **MATERIAL M2** — "AUD-09 consumes 08b's artefact" is unreciprocated | ca | **ACCEPTED, and made real.** Hand-off **H1** specifies artefact/schema_version/writer/reader/join key/unknown-version refusal/idempotency key. **H2** (→ AUD-10) explicitly DECLINED. Both mirrored in AUD-09 §6a and AUD-10 §6b. |
| **MATERIAL M3** — inter-stage artefact carries no versioned schema | ca | **ACCEPTED.** `STATION_CANDIDATES_SCHEMA_VERSION`, named reader, `UnknownStationCandidateSchemaError`, record key and merge rule in §6b, pinned as **A6/A7/A8**. |
| **MATERIAL M4** — sufficiency has no specified home; DENSE_STATIONS pin unresolved | ca | **ACCEPTED.** Seam stated: computed in the script, passed into the pure fold as data; fold signature given; explicit `cities=(city,)` argument (structural_dead_stop.py:219-222). A9 restated against it. |
| **MINOR m1 / tba minor** — line citations drift | both | **ACCEPTED.** Re-read and corrected throughout. |
| **MINOR m2** — mutable out-parameter | ca | **ACCEPTED.** Replaced with keyword-only `collect_unregistered` returning `(payloads, sightings)`. |
| **MINOR m3 / tba minor** — L-1 grep specified but not run | both | **ACCEPTED and DISCHARGED.** Output recorded in §6. |
| **MINOR m4** — uncited magic `32` flood cap | ca | **ACCEPTED.** Registry-derived cap with stated rationale (§9). |
| **tba** — no repeated-failure alert beyond unit state | tba | **ACCEPTED.** Three consecutive failed emissions escalate through the shipped alert sink (§9). |

**Rejections:** none. Every round-1 defect was accepted.

### Round 2

- **trading-bot-architect (autonomous-loop/pipeline lens): 78/100 · NOT READY**
- **architect (code-architect lens): 80/100 · NOT READY**

Both reviewers independently verified every round-1 disposition against the plan **body** and found
each fix real (module move, H1's seven rows, schema version, the sufficiency seam, the registry-
derived cap, the corrected line numbers). No round-1 acceptance was falsely claimed. Round 3
therefore leaves that text alone and changes only what follows.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL A8-1 / M5** — the 08a→08b sighting sidecar has no writer, path, schema, concurrency rule or crash behaviour, and its existence contradicts §1's "08a: no new artefact"; two processes run the provider, so concurrent appenders are the default case | both | **ACCEPTED IN FULL — the strongest finding of round 2, and the reviewers are right that revision 2's §13 understated it.** Resolved by *specifying* rather than deleting, and by **moving the sidecar out of 08a into 08b**, which is what makes §1 true again instead of merely re-worded. §6b.1 is a full artefact table: module, path, `SIGHTING_SCHEMA_VERSION`, `append_sighting`/`read_sightings`, `UnknownSightingSchemaError`, one-line-per-`write()` `O_APPEND` framing, daily rotation by filename, 35-day pruning. **Single sanctioned writer is enforced by construction**, not convention: an injected `sighting_sink: SightingSink \| None = None` on the provider, supplied at `factories.py:517` by the recorder composition and `None` by the trade node — with **A14** as the test. No lock is specified, deliberately: a lock would make a second writer *work*, and a second writer is the defect. Crash behaviour is split into the two real cases — a **trailing** partial line is skipped with a WARN (the expected recorder-kill case), a malformed **non-final** line is a hard refusal (it can only mean interleaving). RED tests at §7 steps 7–9; criteria **A12** and **A14**. |
| **MATERIAL A8-2** — NYC is IN `city_codes`, so it can never produce a sighting; A9 is unreachable and three of the four `Sufficiency` values have no producer | architect | **ACCEPTED IN FULL.** Verified: the sighting branch is `if parsed.city not in city_set` (`provider.py:221`) and NYC is one of the five registry pairs. Resolved by **giving the fold a second named input** rather than deleting the claim: `seed_cities: Sequence[tuple[str, str]]`, computed in the script from `default_registry().pairs()` (the enumeration `settlement_alignment_study.py:638-641` already uses) minus `SUPPORTED_STATIONS`. A new `origin: Literal["SIGHTING","REGISTRY_SEED"]` field carries the distinction, with its own key rule (seeds never count slugs, origin never changes, a seed never alerts). Every `Sufficiency` value now has a producer, and **A9 is restated against the seed path** and is reachable. §6b.3. |
| **MINOR a1** — the `collect_unregistered` signature is not expressible under `mypy --strict` | architect | **ACCEPTED.** Verified: `strict = true` at pyproject.toml:158, `files` includes `src/breezy/adapters` at `:160`, no override for this module, and `discovery_candidate_slugs` iterates the result at `provider.py:187`. §6a now gives **two `@overload` declarations on `Literal[True]`/`Literal[False]` over one implementation**, with a two-function shape named as an acceptable substitute, and **A13** (`mypy src/breezy` clean) added as the binding constraint. |
| **MINOR a2 (scored against AUD-10 as 10-2)** — H2 is called "declined" while `C-STATIONS` records the register's candidate count, which requires reading it | architect (both plans) | **ACCEPTED.** Decided **once, identically in AUD-08/09/10**: `C-STATIONS` becomes a **pure subset predicate with no register read**, and the candidate-count clause is **deleted** from AUD-08 §6b and AUD-10's criteria table. Reasoning for choosing this over a bounded read: AUD-10b's own §9 rule refuses on a missing or unknown-version input, so a bounded read would let a missing register refuse a promotion proposal — absurd, as the reviewer said. The visibility the count was reaching for is better served by a push (the new-candidate alert) than by a number in `criteria.json`. H2 is now declined **without residue**. |
| **MINOR a3** — no compaction/retention rule for a venue that churns city tokens | architect | **ACCEPTED.** §6b.2 states an explicit rule: no expiry (the artefact's whole value is the standing "has this venue ever listed X" fact), a per-day growth bound via the flood cap, and **compaction, not deletion**, of records untouched for 180 days — idempotent, key-preserving. Criterion **A15**. |
| **MINOR (tba)** — a candidate sits in the register with nothing prompting anyone; H2's "next step to eligibility" has no trigger or named owner | tba (coordinator-required) | **ACCEPTED, and taken further than the reviewer asked.** §6b.4 adds **one alert per candidate** through the already-shipped sink (`resolve_alert_sink`, `health.py:579`; `emit_alert`, `:668`), `event="BREEZY_STATION_CANDIDATE_NEW"`, whose `detail` names the ruling to open and its owner and carries no absolute path (`AlertPayload`'s own constraint). **The once-per-candidate dedupe deliberately does NOT use `runtime/health.AlertState`**: that class is explicitly per-process and never persisted (its docstring forbids seeding it), so in a nightly one-shot every condition cold-starts `False` and would re-fire every night — the register's own `first_seen_day == today` is the durable property instead. Criterion **A16**. §6c additionally states the **full eight-step eligibility sequence** with an owner per step and each step marked in/outside this backlog, so nobody mistakes a candidate record for progress toward trading. The same table appears in AUD-09 and AUD-10. |

**Rejections:** none. Both round-2 material findings are accepted in full, and the minor the
coordinator promoted (the missing notification) is accepted and widened into §6c's sequence table.
The one place this revision *departs* from a reviewer's literal wording is A8-1's option (b) —
"delete the sidecar and have the emitter obtain sightings another way" — which is **rejected on
evidence**: the only in-repo alternative is a fresh discovery call, which §5 excludes as new request
budget, or parsing the RED log line at `data.py:1262`, which is not a contract. Option (a),
specified in full, is taken.

**Revision 3 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | G-05's headline is "static stations"; this plan still does not make stations dynamic. §6c now states honestly that AUD-08 owns exactly two of the eight steps to eligibility and that step 4 alone is bigger than this item. That is completeness about the gap, not closure of it. |
| Technical correctness and evidence grounding | 20 | 17 | The §1/§6b contradiction is gone and the NYC producer exists. Every citation re-read in round 3 (`provider.py:187,211-214,221-227`; `config.py:76,245-252,261-265`; `factories.py:517`; `health.py:579,668`; pyproject.toml:158,160,177). Residual: the trigger scenario is still unobserved (§12), and the `sites.toml` line numbers are carried from round 1 rather than re-read this round. |
| Implementation specificity and feasibility | 15 | 12 | Sidecar, sink injection, overload signature, seed input and retention are all now decided. Residual: `SightingSink`'s exact Protocol body and the recorder-vs-node discriminator inside `_shared_polymarket_us_instrument_provider` are described by their required property (A14) rather than by the literal branch condition, which the implementer must read at `factories.py:517`. |
| Acceptance criteria and validation quality | 20 | 16 | A1–A16 are objective; A9 is reachable for the first time; A12/A14/A16 cover the artefact, the writer uniqueness and the notification. Residual: A16 tests two folds in one process, so a once-per-candidate property across a *machine restart* is argued (the register is durable) rather than tested. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Livelock closed, two distinct sidecar crash cases handled, flood cap derived, corruption refused, repeated-failure alert, and a candidate now pushes a notification instead of waiting to be found. Residual: if the single-writer invariant is ever broken, the emitter refuses loudly but the sidecar day is unrecoverable. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | ROI honesty preserved, hand-offs named, H2 declined without residue, abandonment criterion scoped to 08b's sighting count only, and the out-of-scope steps are named rather than implied. |
| **Total** | **100** | **83** | |

### Round 3

- **trading-bot-architect (autonomous-loop/pipeline lens): 100/100 · READY**
- **architect (code-architect lens): 81/100 · NOT READY**

**Readiness is the LOWER of the two: 81.** The 100 is recorded, not relied on: it found none of the
four defects below, each of which the architect verified at source and each of which I re-verified
independently before accepting. A perfect score that misses a reachable two-writer path is not
evidence of readiness.

Both reviewers confirmed every round-2 fix is real and sound (sidecar specified as a first-class
artefact, the `@overload` signature, the seed input with `origin`, the registry-derived flood cap,
the 180-day compaction, H2 declined without residue across all three plans, the one-shot alert on
the shipped `resolve_alert_sink`/`emit_alert` path). Revision 4 therefore changes **only** the
passages named below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL A8-3** — the single-writer-by-injection design is not implementable: no recorder-vs-trade-node discriminator reaches `_shared_polymarket_us_instrument_provider`, and passing a sink as a parameter changes the `@lru_cache(maxsize=1)` key so the data and exec factories would construct TWO providers = two appenders in one process | architect | **ACCEPTED IN FULL — the strongest finding of round 3, and correct at source.** Re-verified myself: `@lru_cache(maxsize=1)` at `factories.py:516` over `(client, provider_config, discovery, clock)` (`:517-521`); both `create()`s call it — data at `:589-594`, exec at `:722`; the module comment at `:432-446` states the equal-valued-key invariant and that `lru_cache` is left to raise on an unhashable config; the docstring at `:523-529` names the R-4 divergence one provider dissolves. §6b.1 now carries a four-row decision table: **(a) discriminator = `config.subscribe_trades`** (`config.py:333`, `subscribe_trades: bool = False`; its own comment at `:322-332` and `factories.py:619-622` both call it the recorder's knob and state the trade node keeps the default) — a new explicit field is *rejected*, with the reason stated (a second flag meaning "this is the recorder" is a drift surface for no new capability); **(b) resolved in `PolymarketUSLiveDataClientFactory.create` only**, verified sufficient because the recorder registers only a data client factory (`quote_tape_cli.py:188`) while the trade node registers both (`trade_cli.py:402,405`), so the exec factory never runs in the recorder process; **(c) the cache key is untouched** — the sink is **not** a parameter; it is attached after construction by an idempotent-by-identity `attach_sighting_sink`, whose argument comes from a module-level `@lru_cache(maxsize=1)` `_shared_sighting_sink(str)` getter mirroring the module's own `_shared_*` idiom (`:452,485,493,503,516`), so both call sites keep equal-valued hashable keys; **(d)** order independence stated. **A14 is extended to three clauses**, the third asserting exactly ONE `PolymarketUSInstrumentProvider` per process across both factories by identity *and* `cache_info().misses == 1` — the reviewer's point that A14 could otherwise pass while the invariant is broken is exactly right. §7 steps 8–9, §10 and §12 restated to match. |
| **MATERIAL A8-4** — `seed_cities` from `default_registry().pairs()` yields the site key `"NYC"`, but the record key `city_token` is the venue's lowercase `"nyc"`; the seed/sighting merge can never fire and H1's `site_for_venue_city_token` join raises | architect | **ACCEPTED IN FULL.** Re-verified: `pairs()` returns site keys (`sites.py:348-350`); `sites.toml:117` is `[sites.polymarket_us.NYC]` and `:121` is `venue_city_token = "nyc"`; `discovery_city_codes_from_registry` (`config.py:155-183`) derives the token via `venue_symbology(...).venue_city_token` and `PolymarketUSMarketDiscoveryConfig.__post_init__` refuses a non-lowercase code (`config.py:214`); `site_for_venue_city_token` (`sites.py:393-401`) raises `SiteNotFoundError` on an unknown token. Fixed in three places: §6b.2 now states **once, bindingly**, that `city_token` is ALWAYS the venue's lowercase token and never the site key; §6b.3's seed derivation emits `(venue, venue_symbology(venue, city).venue_city_token)` — the identical comprehension body to `config.py:166-173` — filtered by the *uppercase* station code against `SUPPORTED_STATIONS`, yielding `{("polymarket_us","nyc")}`; and **A6 gains a clause** asserting that a seeded row plus a later sighting of the same city collapse into exactly one record with `origin="REGISTRY_SEED"`. H1's join row is re-checked and remains valid: it joins on the lowercase token, which is now what the register holds. |
| **MATERIAL A8-5** — the seed path's `Sufficiency` value has no stated computation, so A9 asserts agreement with an `int` and has no pass condition | architect | **ACCEPTED IN FULL.** §6b.3 now states the mapping as a total function `sufficiency_from_covered_listed_days(count: int) -> Sufficiency`: `0` → `REGISTRY_ONLY_NO_CAPTURE`; `1..MIN_STRUCTURAL_DEAD_STATION_DAYS-1` → `CAPTURED_INSUFFICIENT`; `>= MIN_STRUCTURAL_DEAD_STATION_DAYS` → `CAPTURE_SUFFICIENT`; negative is unreachable and raises. **The constant is the right one and is argued, not asserted:** `MIN_STRUCTURAL_DEAD_STATION_DAYS` (`structural_dead_stop.py:85`) is `MIN_AFTERNOON_STATION_DAYS` imported at `:58` and defined `Final[int] = 15` at `ma_prelock_winner_ask_study.py:163`; that module's comment at `:82-84` says the KILL clock "shares the exact same '15 station-days to discriminate' floor, never a second, potentially-drifting literal", and `tests/unit/test_structural_dead_stop.py:99` pins the equality — so this register asks the same discrimination question of the same counter's output and must not invent a second threshold. `NO_SETTLEMENT_TRUTH` is explicitly excluded from the mapping (it is the sighting path's value, assigned without calling the counter). **A9 is restated as an equality** against that mapping, with all three arms pinned from the imported constant rather than the literal `15`. |
| **MINOR a1** — `count_covered_listed_station_days_from_catalog` is keyword-only; the plan called it positionally | architect | **ACCEPTED.** Verified: `def …(*, catalog_root: Path, cities: Sequence[str] = DENSE_STATIONS, fetch_start…, fetch_end…) -> int` at `structural_dead_stop.py:219-225`. §6b.3 now writes `catalog_root=catalog_root` and quotes the signature, and additionally states the domain trap the reviewer's fix exposes: `cities=` takes the **uppercase station code** (`DENSE_STATIONS` is `spec.city for spec in load_sites()`, `cli_basis_setup_win_rate_study.py:126-128`), not the lowercase `city_token` the register keys on. |
| **MINOR a2** — registry path drift (`registry/sites.toml` vs `src/breezy/registry/sites.toml`) | architect | **ACCEPTED.** Corrected at all four occurrences (§3, §5, §6c step 3, §12); the line numbers 117/121/154/193/239/279 were re-read this round and are correct. |
| **MINOR a3** — the two-day fold window is shorter than the three-failure escalation tolerance, so a recovered emitter permanently loses the days it missed | architect | **ACCEPTED, and closed by design rather than by an accepted loss.** §6b.4 replaces "yesterday's and today's" with a `last_folded_day` watermark (a one-line versioned JSON, atomic write, advanced only after a successful fold *and* register write): every unpruned `sightings-<day>.jsonl` newer than the watermark is folded in ascending order, an absent/unknown-version watermark folds everything unpruned (safe because the fold is idempotent, A7), and the one residual — a day pruned before it could be folded, i.e. an outage > 35 days — is **counted** as `sidecar_days_lost` in the summary rather than lost silently. New criterion **A17**; §9 gains the recovery case; §7 steps 10 and 12 updated. |

**Rejections:** none. All four material findings and all three minors are accepted. The one place
this revision departs from a reviewer's literal suggestion is A8-3's option "or a new explicit field
on `PolymarketUSMarketDiscoveryConfig`" — rejected **on evidence** (the reason is stated in §6b.1's
table, not merely asserted), in favour of the existing `subscribe_trades`.

**Revision 4 self-score (2026-09-21, author, conservative — scored against the round-3 rubric
weights, not against the improvement since revision 3):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | Unchanged and not claimed higher: G-05's headline is "static stations" and this plan still does not make stations dynamic — §6c states honestly that AUD-08 owns exactly two of eight steps and that step 4 alone is larger than this item. 08b's one PM.us row is now producible end to end (A8-4/A8-5 closed), which was the round-3 deduction; the structural completeness gap against G-05 remains. |
| Technical correctness and evidence grounding | 20 | 18 | The key-domain error, the keyword-only call and the path drift are fixed against source re-read this round (`factories.py:432-446,516-521,589-594,619-622,722`; `config.py:155-183,214,322-333`; `sites.py:348-350,393-401`; `sites.toml:117,121,154,193,239,279`; `structural_dead_stop.py:58,85,219-225`; `ma_prelock_winner_ask_study.py:163`; `quote_tape_cli.py:188`; `trade_cli.py:402,405`). Not 20: the venue-behaviour assumption in §12 is still unobserved, and `breezy-quote-tape.service:92` is carried from an earlier round rather than re-read. |
| Implementation specificity and feasibility | 15 | 13 | The two decisions the reviewer said were left with the implementer are now made in the plan: the discriminator (named field, named `create()`) and the sufficiency threshold (named constant, full mapping). Not 15: `SightingSink`'s exact Protocol method signature and the literal `SIGHTINGS_DIR` constant are still described by their required property rather than written out. |
| Acceptance criteria and validation quality | 20 | 17 | A9 now has a pass condition (an equality, three arms); A14 gained the one-provider-per-process clause that makes it able to catch the failure it exists to prevent; A6 gained the collapse clause; A17 covers watermark recovery. Not higher: A16 still tests two folds in one process, so once-per-candidate across a machine restart is argued from durability rather than tested. |
| Autonomous operation, failure handling, recovery | 15 | 13 | The "impossible by construction" interleaving case is now genuinely unreachable via the `lru_cache` path, and multi-day emitter recovery is a design property with a counted residual. Not 15: if the single-writer invariant were ever broken anyway, the emitter refuses loudly but that sidecar day is unrecoverable. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Unchanged; the round-3 reviewer found no defect here. ROI honesty, abandonment criterion scoped to 08b's sighting count, H2 declined without residue and consistent across three files, out-of-scope steps named with owners, no operator-cap or enablement contact. |
| **Total** | **100** | **88** | |

### Round 4

- **trading-bot-architect (autonomous-loop/pipeline lens): 100/100 · READY**
- **architect (code-architect lens): 91/100 · NOT READY**

**Readiness is the LOWER of the two: 91.** For the **second consecutive round** the
trading-bot-architect returned a perfect score while finding none of the architect's defects — and
for the second consecutive round the defect it missed is a *silently-permissive value*, not a
documentation nicety (round 3: a reachable two-writer path; round 4: an absent catalog reading as
`count=0`). The 100 is recorded, not relied on. Every architect finding below was re-verified at
source by me before acceptance.

Both reviewers confirmed every round-3 fix is real and correct at source — the `lru_cache`
discriminator decision with A14(iii), the `venue_city_token` seed domain, the
`MIN_STRUCTURAL_DEAD_STATION_DAYS` mapping, the keyword-only call, the `sites.toml` path, and the
`last_folded_day` watermark (which the reviewer recorded as *stronger* than what he asked for).
Revision 5 therefore changes **only** the passages named below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL A8-6** — the sufficiency counter's `catalog_root` is unbound, and a wrong/unreadable root is *silently permissive*: it reads as `count=0`, i.e. a legitimate-looking `REGISTRY_ONLY_NO_CAPTURE`; and `QuoteTapeGapDataUnavailable` is an unenumerated failure mode | architect | **ACCEPTED IN FULL, and re-verified independently.** The reviewer is right on both halves and the second half is worse than stated: `count_covered_listed_station_days_from_catalog` performs **no root check at all** (`structural_dead_stop.py:219-251`), and the proof is that the shipped CLI carries the guards *outside* it — `main()` refuses a non-directory root at `:355-361`, computes `depth_root_present = depth_root.is_dir()` at `:363-365`, and catches `QuoteTapeGapDataUnavailable` at `:373-376`. The emitter is not `main()`, so it must carry those three guards itself, and §6b.3 now says so. **(a) Bound by name:** `--catalog-root` with `default=str(DEFAULT_QUOTE_TAPE_CATALOG)` (`ma_prelock_winner_ask_study.py:187`), the identical `argparse` shape `structural_dead_stop.py:275-279` uses, with the wrapper passing `${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-…}` resolved **byte-identically to `score-live-trials-run.sh:57-60`** — whose own comment (`:57-59`) states that env var names the same root the quote-tape services write. Both offered options are in fact the same root, so both are taken, in the repo's own env-then-constant order; this is also how AUD-09's census resolves `$QUOTE_CATALOG`, so the two items cannot read different catalogs. **(b) REFUSE, never `0`:** an absent/unreadable root, `depth_root_present == false`, or a `QuoteTapeGapDataUnavailable` refusal makes the emitter **exit non-zero having written nothing** — register byte-unchanged, `last_folded_day` unadvanced, no sidecar pruned. "Exit non-zero" is chosen over "keep the previous value" with the reason stated: a partially-computed fold is the silently-permissive shape itself, and "keep the previous value" has no answer for the first fold. **Coherence with the alert path and the watermark is argued, not assumed:** the unadvanced watermark re-folds every unpruned day (A17), and because `first_seen_day` is the **fold** day, a delayed fold *delays* the one-shot alert rather than skipping it (A16). The case joins **§9** as its own enumerated failure. **(c)** **A9 gains a fourth arm** asserting the absent-input behaviour — exit code, byte-unchanged register, unadvanced watermark, and explicitly **no** `REGISTRY_ONLY_NO_CAPTURE` row. §7 steps 10, 12 and 13 restated. |
| **MINOR a1** — the sidecar's day resolution and rotation rule are unstated (a filename resolved once at attach would write D+1…D+n into D's file and the watermark would make them unreachable), A12 does not test rotation, and the provider's sink call-site is unnamed | architect | **ACCEPTED.** The reviewer's inference was correct and is now specification. §6b.1's rotation row states that `append_sighting` resolves `sightings-<UTC day>.jsonl` **per append** and reopens on a day change, and names the day source: the **sighting's own `observed_ts_ns`** converted to UTC, *not* the wall clock — so a line can never land in a file whose day differs from the day the record claims, which is what keeps the filename-keyed fold and the watermark consistent with the records they read. The one residual (a sighting produced by an in-flight cycle after that day was folded **and** pruned) is stated with its bound rather than glossed. The **call-site is named**: `PolymarketUSInstrumentProvider.load_all_async`, immediately after the `self._unregistered_city_sightings` assignment and the single per-cycle WARN — never `_weather_market_payloads` (`provider.py:190-229`, which must stay I/O-free because `discovery_candidate_slugs` calls it at `:187`) and never `_discover_markets`. **A12 gains a rotation arm** (two appends straddling a UTC midnight on one sink land in two day-named files) and §7 step 7 requires it. |

**Rejections:** none. Both round-4 findings are accepted in full.

**Revision 5 self-score (2026-09-21, author, conservative — scored against the standing rubric,
not against the improvement since revision 4):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | The seed row's *value* is now producible and trustworthy end to end, which was the round-4 deduction. Not higher, and not claimed higher: G-05's headline is "static stations" and this plan still does not make stations dynamic — §6c states that AUD-08 owns exactly two of eight steps and that step 4 alone is larger than this item. |
| Technical correctness and evidence grounding | 20 | 19 | The catalog binding, the three guard sites and the counter's no-root-check behaviour were read at source this round (`structural_dead_stop.py:219-251,253-266,275-279,355-361,363-365,373-376`; `ma_prelock_winner_ask_study.py:187`; `score-live-trials-run.sh:57-60`), on top of round-4's verified set. Not 20: the venue-behaviour assumption in §12 remains unobserved, and `breezy-quote-tape.service:92` is still carried from an earlier round rather than re-read. |
| Implementation specificity and feasibility | 15 | 14 | The last unmade input decision (what binds `catalog_root`) is made, with the flag, the default, the env var and the wrapper line all named; the sink's day resolution and call-site are written rather than inferred. Not 15: `SightingSink`'s exact Protocol method signature and the literal `SIGHTINGS_DIR` constant are still described by their required property. |
| Acceptance criteria and validation quality | 20 | 18 | A9's fourth arm makes the absent-catalog case a test rather than an assumption, and A12 now tests the rotation property the sink's correctness rests on. Not higher: A16 still tests two folds in one process, so once-per-candidate across a machine restart is argued from durability rather than tested. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The silently-permissive value is gone and the refusal is coherent with the watermark, the pruning and the alert; §9 now enumerates the counter's own refusal. Not 15: a catalog outage stalls the register entirely until the third-failure escalation fires, and a broken single-writer invariant still costs one sidecar day. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Unchanged; no reviewer has found a defect here since round 2. ROI honesty, abandonment criterion scoped to 08b's sighting count, H2 declined without residue across three files, out-of-scope steps named with owners, no operator-cap or enablement contact. |
| **Total** | **100** | **93** | |

**Latest score:** 93 (revision 5 self-score; round-4 peer scores 100 / 91; round-3 100 / 81;
round-2 78 / 80; round-1 78 / 67).
**Readiness:** **NOT READY — round 5 delta review pending.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `0b52192f890dcb53cae2b769b5746a8e93ee8c75ed6e1a96ac47f01147dc2090`
- **Baseline self-score:** 81/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `architect` round 5: 100/100 — `reviews/AUD-08-r5-architect.md`
  - `trading-bot-architect` round 5: 100/100 — `reviews/AUD-08-r5-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None on this item's scope. Residual stated in the plan: G-05's headline (a fifth live station) needs the operator + strategy-lead `sites.toml` re-verification and archive-table extension, outside this item; the trigger (a 6th listed city) has never been observed.
- **Full review history:** 10 records, `reviews/AUD-08-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
