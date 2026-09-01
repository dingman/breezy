# Strategy-facing weather-bucket facts — implementation plan

**Revision 2.** Revision 1 was reviewed by two independent peers; both returned
APPROVE WITH CHANGES. The architecture is unchanged and endorsed:
`Instrument.info` as the carrier, `breezy.domain` as the layer, a `Mapping`
signature rather than an `Instrument` one, keeping `provider._assert_bounds`,
and the C4 analysis (independently re-verified against the classifier source).
**No guard is weakened by this plan.**

What revision 2 changes: two findings that alter the plan's shape (§1.4, §1.6),
and a merged set of corrections. Several of them SHRINK the plan — one
increment is a deletion, and the AST barrier proposed in revision 1 is cut.

Scope: let a strategy answer two questions correctly without importing a venue
adapter — (1) what temperature bucket is this instrument, under the venue's real
CLOSED semantics, and (2) does this weather record apply to this instrument.

---

## 1. Problem statement, with evidence

### 1.1 The knowledge exists, is verified, and is then thrown away

`src/breezy/adapters/polymarket_us/symbology.py:29-66` records the finding that
governs everything below: the venue's PROSE is the source of truth for the
comparator and the interval is **CLOSED**. `gte72lt73f` is titled `"72° to
73°"`, so 73 is INSIDE the bucket. Under the naive strict reading of the slug's
`lt` token the captured ladders tile the degree line in **0 of 114** city/day
groups (orphaning every odd degree); under the prose reading, **114 of 114**.

`assert_bounds_cross_checked` (raising `BoundsSemanticsError`,
`errors.py:150-164`) already derives and returns the corroborated
`ClosedInterval`. It is called in exactly one place:

- `provider.py:395-405` — `def _assert_bounds(self, market, slug) -> None:`.
  **The return value is discarded.** The verified interval is computed and
  dropped on the floor.

Measured over the whole captured corpus via
`tests/unit/conftest.iter_captured_market_payloads`:

```
payloads 729   ok 729   fail 0   unparseable-slug 0
```

The cross-check refuses **zero** captured markets. There is no feasibility
obstacle to computing it for every instrument.

### 1.2 What the instrument actually carries today

`parsing.py:1083-1108` (`_weather_info`) writes into `BinaryOption.info` at
`parsing.py:1163`:

```python
"strike_bounds":        parsed.raw_bounds,      # "gte72lt73f"
"strike_bounds_parsed": parsed.bounds,          # (("gte",72),("lt",73))  VERBATIM TOKENS
"city": ..., "measure": ..., "climate_date": ..., "city_day_cluster_id": ...
```

`strike_bounds_parsed` is **the trap in machine-readable form**: the verbatim,
explicitly-not-settlement-safe token list that `WeatherSlug`'s own docstring
warns must be passed through `assert_bounds_cross_checked` before any
temperature is compared against it. The corroborated interval is **not** in
`info`. Neither is the settlement station.

`_weather_info` never calls the cross-check. The only call site is the live
provider — so **backtest instruments are never cross-checked at all**:
`tests/support/synthetic_multi_strike_tape.py:152` and
`synthetic_binary_tape.py:149` call `parse_binary_option` directly, bypassing
`provider._assert_bounds`. The path strategy authors write against is the one
with no guard.

### 1.3 The layering conflict that pushes authors to hardcode

- `strategy/harness_probe.py:30-36` instructs authors: *"Nothing from
  `breezy.adapters.polymarket_us` is imported. That import would make this
  module venue-touching under classifier C4"*. `strategy/resting_ladder.py:37`
  repeats it.
- C4 is real: `tests/unit/test_polymarket_us_readonly_guard.py`,
  `is_venue_touching`, returns True for any module importing
  `breezy.adapters.polymarket_us` or a submodule, activating V1–V4 — including
  **V3: any `ast.Attribute` named `post`/`put`/`patch`/`delete`/`request`, on
  any receiver**.
- It is also the portability rule (`CLAUDE.md`; `BACKTEST_VENUE_CONFIG.md` §8).

Consequence, in the tree: `BreezyStrikeLadderConfig` (`strike_ladder.py:130-131`)
takes `buckets: tuple[tuple[InstrumentId, int, int], ...]` — **the author types
the bounds in by hand** — with a 25-line docstring pleading for the closed
reading, and `OPEN_BOUND_F: int = 10_000` (`strike_ladder.py:90`) as a
hand-rolled infinity.

### 1.4 The record/instrument gap is not hypothetical — it is COMMITTED AND GREEN

Revision 1 described a synthetic wrong-day test. It does not need to be
synthesised. **The repo's flagship multi-instrument contract already does it:**

- `tests/contract/test_multi_instrument_weather_strategy.py:71-74` builds the
  ladder from `tc-temp-nychigh-2026-04-23-{gte72lt73f,gte70lt71f,gte74f}`.
- Its only weather record comes from `make_climate_day(...)`
  (`:122`), whose default is `_DAY = dt.date(2026, 8, 22)`
  (`tests/unit/test_persistence_catalog.py:50,61`).
- The contract file overrides `climate_day=` **zero** times (verified by grep;
  the four `make_climate_day` call sites at `:122,495,530,536` override
  `station`, `tmax_f`, `is_final`, `retrieved_at_ns` — never the day).

So the contract drives a climate day **121 days** away from the market it
settles, trades on it, and passes its assertions. Nothing anywhere objects.

It is worse than a stale date, and the second half is the part that matters for
step 5. The call site overrides `retrieved_at_ns=tape.weather_ts_ns` — an
**April**-derived instant from the tape — while leaving
`ts_event=_DAY_END_NS` at the **August 23** climate-day end
(`test_persistence_catalog.py:51,80`). The committed fixture therefore carries
`ts_event > ts_init` on a record flagged `is_final=True`: precisely the
misclassification signature `domain/nws_climate_day.py:39-58` names ("the
climate day had not ended when the bytes arrived, which means the product is
**not** a final"). It survives only because the constructor deliberately
enforces no ordering check — that check lives in `ingest.records.build_climate_day`,
which fixtures bypass.

**Consequence for the build order:** the moment `applies_to(station,
climate_day)` lands, every leg of that contract filters to zero and the suite
fails in bulk. Repairing it is not "update the tests" — it needs a coherent
`climate_day` / `ts_event` / `retrieved_at_ns` triple anchored on the tape's
April dates. That is its own step, with its own RED. See §5 step 4.

### 1.5 The structural cause of the money-losing defect: literal duplication

Also not what revision 1 assumed. `test_the_upper_edge_of_a_bucket_is_INSIDE_it`
**already exists and is green today**. So does the wrong-station test. The
missing-assertion theory is wrong.

What is actually wrong is `:84-88`:

```python
_BUCKETS = {WINNER: (72, 73), NEAR_MISS: (70, 71), FAR_SIDE: (74, OPEN_BOUND_F)}
```

`_BUCKETS` is hand-typed, fed into `BreezyStrikeLadderConfig.buckets`, **and**
read back by the assertions. The same literal sits on both sides of the test.
An author who types `(72, 72)` — the half-open reading — gets a green suite,
because the assertion is derived from the same wrong literal as the behaviour.
The 73-edge test cannot falsify the 73-edge error.

**This reframes the deliverable.** The fix is not a better assertion; it is
removing the literal, so that the bounds under test come from the venue's own
corroborated payload and the test can finally disagree with the author. If
`_BUCKETS` survives the migration, the trap survives and this plan delivers
nothing at the strategy layer.

### 1.6 The mapping is available and unambiguous today

Slug city tokens across the 729 captured markets: `nyc` 653, `mia` 24, `mdw` 22,
`lax` 18, `sfo` 12 — five tokens, `measure=high` for all 729. Registry pairs:
`(polymarket_us, NYC|SFO|MIA|MDW|LAX)`, each with `cli_location` equal to its
city key, and `NwsClimateDay.station` is exactly that `cli_location`
(`ingest/records.py:205,328`). Total and 1:1 over everything observed.

It must nonetheless be a **stored** value: `registry/sites.toml` is explicit
that nothing in it may be derived at runtime. See §4.3 for the complication
that `config.py` already derives it.

---

## 2. Options considered

*(Unchanged from revision 1 and endorsed by both reviews; retained in full
because the rejected options are the plan's main defence against re-litigation.)*

### Option A — Do nothing; document the rule harder

**Failure mode: observed, empirically.** The rule was documented in
`symbology.py:29-66`, in `BoundsSemanticsError`, and in
`BreezyStrikeLadderConfig`'s own docstring — and an author still read it
half-open with a green suite. §1.5 now makes the failure sharper: even the test
written specifically to catch it cannot, because it reads the author's own
literal. Documentation cannot fail a test run. Leaves §1.4 wholly unaddressed.
**Rejected.**

### Option B — Let strategies import `symbology`

**(1) C4.** `strategy/*.py` becomes venue-touching, activating V1–V4 on the one
layer whose job is to grow; V3 bans the attribute names
`post`/`put`/`patch`/`delete`/`request` on any receiver, permanently. The
pressure to widen C4 the first time a strategy wants `.request`-shaped naming
is exactly the erosion the barrier exists to prevent. **(2) Portability**
(`BACKTEST_VENUE_CONFIG.md` §8). **(3) Re-derivation:** `symbology` alone still
cannot answer either question — the authoritative reading needs the payload's
`description`/`title`, which are not in the `InstrumentId`.

**Precision for the reviewer:** import-linter does **not** forbid this.
`strategy` is the TOP layer, so `strategy -> adapters` is legal downward. The
blockers are C4 and portability, not the layer contract. **Rejected.**

### Option C — A venue-neutral lookup service in `runtime`

Second source of instrument data alongside `self.cache.instrument(...)`; needs
venue-dispatch logic; makes a runtime module venue-touching for no egress
reason; violates the null hypothesis, since Nautilus already delivers
per-instrument venue payload to the strategy. **Rejected as speculative
architecture.**

### Option D — Re-parse venue prose in the strategy from `Instrument.description`

Relocates prose parsing into the top layer, makes every strategy a second
implementation of `parse_prose_bounds`, and bypasses the slug-versus-prose
disagreement detector this plan is forbidden to weaken. **Rejected.**

### Option E (RECOMMENDED) — corroborated facts in `Instrument.info`; vocabulary and reader in `breezy.domain`

The adapter (which already holds the payload, the prose, and the cross-check)
writes verified scalars into `info`. A small venue-neutral module in the
**lowest** layer owns the key names, the type, and a fail-closed reader. Both
the adapter (writer) and the strategy (reader) depend **downward** on that one
module and never on each other.

---

## 3. Recommendation

**Option E.** The null hypothesis is very nearly right and the honest answer is
small: `Instrument.info` is the native carrier, instruments already reach the
strategy through `self.cache.instrument(...)`, and `parse_binary_option`
already writes weather fields there. This plan mostly *fixes what is written*.

Three corrections keep it from being a one-liner:

1. **What is written today is the wrong value** (§1.2): the corroborated
   interval is computed in the provider and discarded.
2. **The reader must not be a raw dict access.** `instrument.info["strike_lower_f"]`
   duplicates key strings per strategy, is untyped, and makes
   absent-means-`None`-means-no-bound — the same silent-wrong-answer failure in
   a new costume. It needs a typed, fail-closed reader importable by BOTH sides.
3. **Station is not in `info` at all** and cannot be derived without the
   registry (§1.6).

Placement: **`src/breezy/domain/weather_bucket_facts.py`**. `domain` is the
BOTTOM layer, so `strategy -> domain` and `adapters -> domain` are both legal
downward edges; the layers contract is `exhaustive = true`, so a NEW top-level
package would require a contract edit while `domain` requires none; and the
module imports nothing from `polymarket_us` and names no venue host, so it is
**not** venue-touching under C1–C4, and neither is a strategy importing it.

---

## 4. Concrete design

### 4.1 New: `src/breezy/domain/weather_bucket_facts.py` — layer `domain` (bottom)

Venue-neutral. Imports: `dataclasses`, `datetime`, `enum`,
`collections.abc.Mapping`, and `breezy.domain.validation`. **No
`nautilus_trader` import**, no adapter import, no registry import.

**Named `WeatherBucketFacts`, not `MarketFacts`.** The type is
`lower_f`/`upper_f`/`distance_f(reading_f: int)` — it cannot describe a
non-temperature market on any venue. The narrow name costs nothing now and
forecloses the "is this instrument OK" god-flag §8.6 worries about. The module
docstring states the scope boundary explicitly: **whole-degree Fahrenheit
temperature buckets only.**

```python
__all__ = [
    "CLIMATE_DAY_KEY", "MEASURE_KEY", "SETTLEMENT_STATION_KEY",
    "STRIKE_LOWER_F_KEY", "STRIKE_UPPER_F_KEY",
    "WEATHER_FACTS_STATUS_KEY", "WEATHER_FACTS_STATUS_KNOWN",
    "WEATHER_FACTS_STATUS_UNKNOWN",
    "Measure", "WeatherBucketFacts", "WeatherFactsUnavailableError",
    "is_weather_market", "read_weather_bucket_facts",
]

#: Key vocabulary written into `Instrument.info` by ANY venue adapter.
#: Scalars only -- str / int / None. See §4.4 for why not tuples.
WEATHER_FACTS_STATUS_KEY: str = "weather_facts_status"      # "KNOWN" | "UNKNOWN"
WEATHER_FACTS_STATUS_KNOWN: str = "KNOWN"
WEATHER_FACTS_STATUS_UNKNOWN: str = "UNKNOWN"
SETTLEMENT_STATION_KEY: str = "settlement_station"  # "NYC" -- NwsClimateDay.station
CLIMATE_DAY_KEY: str = "climate_date"               # "2026-04-23" -- see §4.4 note
MEASURE_KEY: str = "measure"                        # "high" | "low"
STRIKE_LOWER_F_KEY: str = "strike_lower_f"          # int | None (None = open below)
STRIKE_UPPER_F_KEY: str = "strike_upper_f"          # int | None (None = open above)

class WeatherFactsUnavailableError(ValueError): ...

@enum.unique
class Measure(enum.Enum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherBucketFacts:
    settlement_station: str
    climate_day: datetime.date
    measure: Measure
    lower_f: int | None      # inclusive
    upper_f: int | None      # inclusive

    def contains(self, reading_f: int) -> bool: ...
    def distance_f(self, reading_f: int) -> int: ...
    def applies_to(self, station: str, climate_day: datetime.date) -> bool: ...

def read_weather_bucket_facts(info: object) -> WeatherBucketFacts: ...
def is_weather_market(info: object) -> bool: ...
```

House-style points, each from an in-repo precedent:

- **`kw_only=True`.** `lower_f` and `upper_f` are adjacent same-typed ints;
  positional construction is a transposition waiting to happen in the very
  module written to prevent bounds mistakes.
- **`Measure` is an `@enum.unique` Enum**, per `settlement/coverage.py:66-80`
  (`CellClassification`), not a bare `str`. A venue token outside the enum is a
  refusal, not a string that flows onward.
- **`__all__`** per every other domain module.

Semantics, each of which is a test:

- **`contains` is CLOSED at both ends**: `lower_f <= r <= upper_f`, `None`
  meaning unbounded on that side. Its docstring carries the 114/114 evidence.
- **`distance_f`** is degrees from `reading_f` to the closed interval:
  always **`>= 0`** (unsigned — the §4.6 call site compares it against a
  tolerance and a signed value would silently pass one side), **`0`** when
  inside, and **`0`** on an unbounded near side (an open-below leg is at
  distance 0 from any reading below it, because it contains it).
- **`contains`/`distance_f` reject `bool` and non-`int`** via
  `domain/validation.require_int` (`validation.py:40-49`), which exists
  precisely because `bool` is an `int` subclass — otherwise `contains(True)`
  silently means `contains(1)`.
- **`applies_to` takes primitives**, not `NwsClimateDay`, so the coupling is
  one-way and Kalshi-portable. Call site:
  `facts.applies_to(data.station, data.climate_day)`.

**`read_weather_bucket_facts` fails closed.** It takes `object`, not `Mapping`,
and validates at runtime, adopting the guard shape of `assert_fee_schedule_known`
(`parsing.py:306-307`): `info = getattr(...)`-style tolerance of absence, then
`isinstance(info, Mapping)`. **Say it out loud in the docstring: `Instrument.info`
erases to `Any`, so mypy gives ZERO call-site protection and runtime validation
is the only guard there is.** It raises `WeatherFactsUnavailableError` when:

- `info` is absent or not a `Mapping`;
- the status key is absent, or is not `KNOWN`;
- any required key is missing, **or is present-but-`None`** (the non-weather
  branch at `parsing.py:1094-1100` writes `None` for exactly these keys, so
  present-and-`None` is the common case, not an exotic one);
- a type is wrong (`climate_day` not ISO-parseable, `lower_f` a `str`, measure
  outside the enum);
- `lower_f > upper_f`;
- **both `lower_f` and `upper_f` are `None`.** An unbounded-both-ways bucket
  makes `contains()` True for every reading, so the leg always looks like the
  winner. No captured market produces it — which is exactly why it would never
  be noticed.

**`is_weather_market` is NOT fail-open.** It returns `False` **only** on an
explicit `WEATHER_FACTS_STATUS_UNKNOWN`; an **absent** status key **raises**.
The naive fail-open version silently returns `False` for any instrument built
before this change, so a strategy pre-filtering with it would trade three of
four buckets and log nothing — the exact quiet-wrong-answer class this plan
exists to remove.

### 4.2 Signature choice: no `Instrument` overload

Called as `read_weather_bucket_facts(instrument.info)`. An overload taking
`Instrument` would need `nautilus_trader` in the domain module and a new entry
in the `forbidden` contract's `ignore_imports` (precedent exists:
`breezy.domain.nws_climate_day -> nautilus_trader`) to buy one saved attribute
access. **Not worth it.**

### 4.3 Modified: `src/breezy/registry/` — the station mapping as a STORED value

- **`sites.toml`:** add `venue_city_token = "nyc"` (etc.) to each of the five
  `[sites.polymarket_us.<CITY>]` tables, from the §1.6 census.
- **`sites.py`: a separate type and accessor — NOT a field on `SettlementSite`.**
  `sites.py:92-113` documents `SettlementSite` as *settlement-critical identity*
  and deliberately splits every other concern into its own type
  (`ClimateDayWindow`, `SettlementDeadline`, `EnrichmentCoordinates`), each
  reachable only through its own named accessor. **A venue slug token is
  symbology, not settlement identity**, and putting it on `SettlementSite`
  would be the first breach of a boundary that file argues for at length. So:

  ```python
  @dataclass(frozen=True, slots=True)
  class VenueSymbology:
      venue: str
      city: str
      venue_city_token: str

  # on SiteRegistry:
  def venue_symbology(self, venue: str, city: str) -> VenueSymbology
  def site_for_venue_city_token(self, venue: str, token: str) -> SettlementSite
  ```

  Load-time refusal if two sites in one venue share a token.

- **`registry_version` is NOT bumped. Decision, not an omission.** It is stamped
  into every persisted `NwsClimateDay` and `NwsRawProduct`
  (`domain/nws_climate_day.py:213`, `ingest/records.py:221,344`) and
  `ingest/records.py:18` requires it identical across the paired records. This
  change has **zero settlement semantics** — it adds a symbology token and
  changes no settlement value — so bumping it would split the persisted corpus
  on a version boundary that means nothing, for no diagnostic gain. Adding the
  field is additive and load-compatible. Revisit if a settlement-bearing value
  ever changes.

**Reconciliation with the derivation already in production — mandatory, same
increment.** `config.py:150-178` `discovery_city_codes_from_registry` already
derives the token as `city.lower()` and feeds it to
`provider._weather_market_payloads` (`provider.py:362`), which is what filters
discovery. If §4.3 lands alone, discovery filters on `city.lower()` while
`_weather_info` resolves on the stored token: they agree today and diverge the
day someone edits one, and the divergence passes discovery and then raises
mid-load. **Migrate `discovery_city_codes_from_registry` to read
`venue_symbology(...).venue_city_token` in the same increment**, or the
stored-value argument is not worth making. A test asserts the two paths agree
for every registered site.

Layer: `registry`. `adapters -> registry` is downward and legal. No venue host
string enters `sites.py`; `.toml` is not scanned by the guard; the registry
stays non-venue-touching.

### 4.4 Modified: `parsing.py` — write the VERIFIED facts, and DELETE the trap

`_weather_info(market, slug)` (`parsing.py:1083`) becomes:

```python
def _weather_info(
    market: Mapping[str, Any], slug: str, *, sites: SiteRegistry, venue_key: str
) -> dict[str, Any]:
```

On the weather branch it additionally:

1. calls `assert_bounds_cross_checked(parsed, description=..., title=...,
   reading_is_whole_degrees=True)` — the same call `provider.py:399-405` makes,
   **with the return value KEPT** — and writes `STRIKE_LOWER_F_KEY` /
   `STRIKE_UPPER_F_KEY` from it;
2. resolves `site = sites.site_for_venue_city_token(venue_key, parsed.city)` and
   writes `SETTLEMENT_STATION_KEY = site.cli_location`;
3. writes `MEASURE_KEY` and `WEATHER_FACTS_STATUS_KEY = KNOWN`.

**Deletions in the same increment:**

- **`strike_bounds_parsed` is DELETED** from both branches (`parsing.py:1098,1106`).
  Revision 1 kept it on the premise that consumers were unaudited. **The premise
  was false and I verified it:** a whole-tree grep finds only the two writes —
  **zero readers**, and no test pins the `info` key set. It is the trap-shaped
  key; keeping the trap in `info` while adding the correct value next to it is
  most of the original defect preserved. `strike_bounds` (the raw string) STAYS:
  it is the verbatim venue record and IS pinned, at
  `tests/unit/test_polymarket_us_parsing.py:212`.
- **No second climate-day key.** Revision 1 proposed `climate_day` alongside the
  existing `climate_date` (`parsing.py:1104`) — same ISO value, one character
  apart, same dict. That is the `strike_bounds`/`strike_bounds_parsed` mistake
  committed a second time. `CLIMATE_DAY_KEY` is therefore literally
  `"climate_date"`, reusing the existing key. Likewise `MEASURE_KEY` is
  `"measure"`, coinciding with the existing key by construction — asserted in a
  test, not left accidental.

**`venue_key` is a stored adapter constant, not a derivation.** `venue` here is
`Venue("POLYMARKET_US")` while the registry keys on `"polymarket_us"`; bridging
them with `.lower()` is exactly the runtime derivation §1.6 forbids. Add to the
adapter, beside `POLYMARKET_US_VENUE`:

```python
#: This adapter's key in `registry/sites.toml`. Stored, never derived from
#: `POLYMARKET_US_VENUE` -- the two namespaces are related by convention only.
REGISTRY_VENUE_KEY: str = "polymarket_us"
```

A test asserts it names a venue the packaged registry actually has.

**Failure behaviour, fail-closed:**

- `BoundsSemanticsError` propagates (already a `VenuePayloadError`). A climate
  market whose prose and slug disagree does not become an instrument.
- **Unknown `venue_city_token` refuses the INSTRUMENT, loudly — it does not
  fail the discovery pass.** (Decided, per §8.2 of revision 1, rather than left
  open.) Live risk is low because discovery is already city-filtered
  (`provider.py:362`), so an unmapped city rarely reaches the parser; and if
  every market were unmapped, `provider.py:257-263` already refuses a
  zero-instrument cycle with an explicit "refusing to treat this as a quiet
  market". The backtest and `_load_slugs` paths are not city-filtered, which is
  the case a per-instrument refusal serves well and a pass-level abort serves
  badly. Raised as `InstrumentDefinitionError`, which
  `parsing.py`'s own docstring already reserves for "must abort the load [of
  this instrument]" as distinct from a droppable frame.
- Non-weather market -> `WEATHER_FACTS_STATUS_KEY = UNKNOWN`, no fact keys, so
  `is_weather_market` returns `False` and the reader refuses.

**The registry lookup is scoped to the weather branch.** A non-weather market
never touches the registry. `parse_binary_option` (`parsing.py:1111`) gains
`sites: SiteRegistry | None = None`; **the default resolves at CALL time, not
at def time** — `sites if sites is not None else default_registry()` in the
body, never as a parameter default. `default_registry()` is `lru_cache`d
(`sites.py:417-418`), honours `BREEZY_REGISTRY_PATH`, `pytest-randomly` is
enabled, and nothing calls `cache_clear()`; a def-time default would bind one
process-wide registry to test-collection order. The provider passes its own
configured registry.

**Scalars only.** `to_dict_c`/`from_dict_c` in `binary_option.pyx` pass `info`
through verbatim, but any JSON/msgpack hop turns a tuple into a list. Pinned by
a round-trip test (§6.6).

**`reading_is_whole_degrees=True` is asserted at this call site**, as
`assert_bounds_cross_checked` demands, justified in a comment: the settlement
datum is `NwsClimateDay.tmax_f`, typed `int | None` via `require_optional_int`
(`nws_climate_day.py:199`). This is the same assertion `provider.py:405` already
makes — moved, not invented.

### 4.5 `provider._assert_bounds` — keep it

Once `parse_binary_option` cross-checks, `provider.py:395-405` is subsumed
(`load_all_async` calls `_assert_bounds` at `:275` then `parse_binary_option` at
`:277`). **Keep it anyway.** Deleting a guard to remove duplication is the wrong
trade for one extra prose regex per discovered market, and it keeps discovery
refusing before the parse. Add a comment naming the parse-time check as primary.
*(Endorsed by both reviews.)*

### 4.6 Modified: `strategy/strike_ladder.py` — consume the facts

- `BreezyStrikeLadderConfig`: replace
  `buckets: tuple[tuple[InstrumentId, int, int], ...]` with
  `instrument_ids: tuple[InstrumentId, ...]`. **Delete `station: str`** and
  **delete `OPEN_BOUND_F`** (`strike_ladder.py:90`) — both become derived facts.
- `on_start`: per id, `instrument = self.cache.instrument(id)`, then
  `facts = read_weather_bucket_facts(instrument.info)`. A missing instrument OR
  a refusing reader logs and `self.stop()`s the whole ladder, matching the
  existing all-or-nothing stance at `strike_ladder.py:172-186`. Cached in
  `self._facts: dict[InstrumentId, WeatherBucketFacts]`.
- `on_data`: replace `data.station != self.config.station`
  (`strike_ladder.py:218`) with a per-leg
  `facts.applies_to(data.station, data.climate_day)` filter — closing §1.4. A
  record applying to no leg is logged and ignored (correct: weather is
  client-scoped and other cities' records legitimately arrive).
- `_trade_ladder`: `facts.contains(observed_f)` and
  `facts.distance_f(observed_f) <= tolerance_f` replace the hand-typed
  `lower <= observed_f <= upper` (`:271`) and `_within_tolerance` (`:294-308`).

Imports added: `breezy.domain.weather_bucket_facts` only. No adapter import, so
C4 does not fire and the module stays Kalshi-portable.

### 4.7 Import direction — proof

```
strategy                     --> domain.weather_bucket_facts   legal (top -> bottom)
adapters                     --> domain.weather_bucket_facts   legal
adapters                     --> registry                      legal
domain.weather_bucket_facts  --> stdlib + domain.validation    (see note)
```

**Note, corrected from revision 1:** `domain` at PACKAGE level is not
stdlib-only — `domain/__init__.py` imports the record modules, which import
`nautilus_trader`. The load-bearing claim is about the MODULE:
`weather_bucket_facts` itself imports only stdlib plus `breezy.domain.validation`
(itself stdlib-only). That is what keeps it out of both import-linter ignore
lists.

**`weather_bucket_facts` must NOT be added to `domain/__init__.py`.** Local
convention would put it there, and that file's own docstring explains why it
re-exports: so each record type's module-scope `register_arrow` has run.
`weather_bucket_facts` registers nothing, is not a `Data` subclass, and adding
it would drag `nautilus_trader` into the import chain of anything that reaches
it through the package.

No new top-level package; the layers contract is `exhaustive = true`; **no edit
to either import-linter contract is required**. The `forbidden` contract carries
the wildcard `breezy.strategy.** -> nautilus_trader`, pinned by
`tests/unit/test_strategy_module_gate.py`, which also asserts that no strategy
module is named individually — so this plan must not add a per-module entry, and
does not need one.

### 4.8 C4 — proof the strategy layer stays clean

`is_venue_touching` fires on: C1 path under the adapter package; C2 path under
`scripts/venue/`; C3 an `ast.Constant` matching `(?:api|gateway)\.polymarket\.us`
or `polymarketexchange\.com`; C4 an absolute import whose first dotted segment is
`polymarket_us`, or of `breezy.adapters.polymarket_us[.*]`.

- `domain/weather_bucket_facts.py`: no such path, string, or import. Not
  venue-touching. Its key VALUES (`"settlement_station"`, `"KNOWN"`) match no C3
  pattern and no V1/V2 pattern.
- `strategy/*.py` importing it: unchanged classification.
- `registry/sites.py`: unchanged classification. The new `REGISTRY_VENUE_KEY =
  "polymarket_us"` lives in the ADAPTER (already C1 venue-touching), and the
  bare string matches neither `_VENUE_HOST_RE` (which requires an `api.`/
  `gateway.` prefix and a dot) nor any V-rule.
- `parsing.py`: already venue-touching (C1); the added code introduces no
  `post`/`put`/`patch`/`delete`/`request` attribute, no write-verb literal, no
  `/v1/orders`-shaped string, no `getattr` bypass. `dict.update` is not in
  `_WRITE_ATTRS`.

**No classifier, rule, or guard is weakened, widened, or exempted.** If review
finds a step requiring it, that step is wrong and should be cut, not the guard.

---

## 5. Build order — smallest useful increment first

1. **`domain/weather_bucket_facts.py`** + unit tests. Pure, no dependents, no
   behaviour change. Merges green alone.
2. **Registry `venue_city_token`**: `VenueSymbology`, both accessors, the
   `sites.toml` values, **and** the `config.discovery_city_codes_from_registry`
   migration off `city.lower()` — one increment, per §4.3, plus the test that
   the two paths agree.
3. **`parse_binary_option` writes the facts and deletes `strike_bounds_parsed`.**
   The behaviour change, gated by the whole-corpus test (§6.4). At this point
   the facts are on every instrument, the trap key is gone, and the
   discarded-value defect at `provider.py:399` is fixed — with nothing yet
   consuming it.
4. **Rewrite the multi-instrument contract fixture** (§1.4), as its own step
   with its own RED. It needs a coherent `climate_day` / `ts_event` /
   `retrieved_at_ns` triple anchored on the tape's April dates, satisfying the
   finals relations `nws_climate_day.py:39,58` describes. Land the wrong-day
   test (§6.1) here — RED before the fixture is fixed, GREEN after.
5. **Migrate `BreezyStrikeLadder`** to `read_weather_bucket_facts`; **delete
   `_BUCKETS` (`:84-88`) and the `OPEN_BOUND_F` import (`:58`)**, rebuilding
   `_ladder()`/`_config()` from `instrument_ids`; delete `OPEN_BOUND_F` and the
   `station` config from the strategy; add the `applies_to` filter.
6. **Docs tail:** update the `harness_probe.py:30-36` and `resting_ladder.py:37`
   paragraphs to point authors at `read_weather_bucket_facts` instead of leaving
   a prohibition with no alternative; `docs/core/PROGRESS.md`.

Increments 1–3 are independently mergeable. 4 precedes 5. 5 depends on 3.

**The sentence that ranks this work:** increments 1–4 fix the *adapter's*
discarded-value defect and the *fixture's* correlation defect. **Only increment
5 prevents the money-losing strategy defect.** Until `_BUCKETS` is deleted and
the ladder reads its bounds from the corroborated facts, an author can still
hand-type half-open bounds, and — per §1.5 — the test written to catch that will
still agree with them. A stop after increment 4 leaves the original hole open.

---

## 6. Test strategy

Ranked by what is genuinely RED today. Revision 1 claimed novelty for two tests
that already exist and are green; that is corrected here.

### 6.1 RED TODAY — the wrong-climate-day filter

`tests/contract/test_multi_instrument_weather_strategy.py` currently drives an
August 22 record into an April 23 market and trades (§1.4). After increment 5,
a record whose `climate_day` matches no leg must produce **zero orders**.

Three cases, because a filter so strict it trades nothing would pass a lone
negative test:

- right station, wrong day -> zero orders;
- wrong station (`LAX`), right day -> zero orders;
- right station AND right day -> trades.

This is the only test in the plan that fails on today's committed code for the
reason it was written.

### 6.2 RED-BY-DELETION — `_BUCKETS` removed

Deleting `_BUCKETS` (`:84-88`) is itself the test change that matters. Every
bucket assertion in that file — including
`test_the_upper_edge_of_a_bucket_is_INSIDE_it` (`:443`), green today — currently
reads the author's own literal on both sides (§1.5). After the deletion the
expected bounds come from the venue's corroborated payload via
`read_weather_bucket_facts`, and those assertions become **non-vacuous for the
first time**. Verification that the deletion is real: no `(72, 73)`-shaped
literal survives anywhere in the file.

### 6.3 The falsification unit test

In `tests/unit/test_weather_bucket_facts.py`, driven by the real captured
payload for a `gte<A>lt<B>f` market:

```
facts = read_weather_bucket_facts(parse_binary_option(captured(WINNER), ts_init=0).info)
assert facts.lower_f == 72 and facts.upper_f == 73
assert facts.contains(72) and facts.contains(73)       # 73 is the killer
assert not facts.contains(71) and not facts.contains(74)
assert facts.distance_f(74) == 1 and facts.distance_f(73) == 0
```

Note honestly what this does and does not add: an equivalent assertion exists
and passes at `:443` today. What is new is the *provenance* — the expected
values come from the venue payload, not from a literal the author also fed to
the code under test.

### 6.4 Whole-corpus load test — with the non-vacuity floor

Over `iter_captured_market_payloads()`: every payload parses; every `climate`
market yields `WEATHER_FACTS_STATUS_KNOWN`; `read_weather_bucket_facts` succeeds
for all. Baseline measured before implementation: **729/729**, so this must be
green on day one; red means the change regressed loading, not that the venue
changed.

**Assert `>= MIN_CAPTURED_MARKETS` (`tests/unit/conftest.py:24`, value 700)
first.** That constant exists precisely because a property asserted over an
empty corpus is worthless, and revision 1's version of this test would have
passed on an empty return.

**Also stated because it is a real coverage hole:** the corpus is 729/729
weather and **0 non-weather**, so the non-weather -> `UNKNOWN` branch has
**zero** corpus coverage and needs a hand-built payload. Same for the
`measure="low"` path (§8.1).

### 6.5 Ladder-tiling contract test

Group every captured market by `(city, measure, climate_date)`; assert the
`WeatherBucketFacts` intervals **partition the whole-degree line**: exactly one
open-below and one open-above leg, and each successive `lower_f == previous
upper_f + 1`.

Scope honestly: this is **the same property already asserted at
`tests/unit/test_polymarket_us_prose_bounds.py:211-240`, re-asserted at the
STORED-facts boundary.** It is not new evidence. It is worth having because the
existing test proves the *prose parser* tiles, while this one proves what
actually reaches `Instrument.info` after the cross-check, the station lookup and
the scalar round-trip — a different failure surface.

**Two floors, both currently missing from revision 1's version:**
`len(groups) >= MIN_LADDERS` (`test_polymarket_us_prose_bounds.py:47`, value
100) and the §6.4 market floor.

**Do not copy the existing sort helper.** `test_polymarket_us_prose_bounds.py:232`
sorts with `key=lambda b: (b[1] is not None, b[1] if b[1] else -999)`, and the
`if b[1]` is a falsy-zero bug: `lower_f == 0` takes the `-999` branch. Specify
instead:

```python
key=lambda f: (f.lower_f is None, f.lower_f)
```

**Reachability, verified rather than assumed:** the review cited `[0,-5,-2]` as
the mis-sort. That example needs a negative bound, and neither grammar can
produce one — the slug token regex is `(\d{1,3})` and all three prose regexes
are unsigned, so bounds are non-negative by construction. With no negatives, `0`
sorting as `-999` still lands first, which is correct. The bug is therefore
**latent, not live** (the corpus minimum `lower_f` is **54**; zero markets at
0). It is still specified out, because that helper is the one an implementer
would copy and the corpus is a summer capture — winter ladders reach 0 °F, and
a future signed reading would make it live.

### 6.6 Fail-closed reader tests

`read_weather_bucket_facts` raises `WeatherFactsUnavailableError` for: `info`
absent; `info` not a `Mapping`; empty mapping; status `UNKNOWN`; **status key
stripped but fact keys present** (the refactor case `assert_fee_schedule_known`
was designed against); **any required key present but `None`** (the non-weather
branch shape); `climate_date` not ISO; `lower_f` a `str`; `lower_f > upper_f`;
**both bounds `None`**; `measure` outside the `Measure` enum. Each asserts the
message names the offending key.

`is_weather_market`: `False` on explicit `UNKNOWN`; **raises** on an absent
status key; `True` on `KNOWN`.

`contains`/`distance_f`: reject `bool` and non-`int`; `distance_f >= 0` for
readings on both sides; `0` inside and `0` on an unbounded near side.

### 6.7 Adapter refusal and round-trip tests

- Synthetic payload whose prose states `"71 to 72"` while the slug says
  `gte72lt73f` -> `BoundsSemanticsError`, no instrument. Proves the cross-check
  is not bypassed.
- Prose stripped -> refusal, not a slug fallback.
- Unmapped city token (`tc-temp-denhigh-...`) -> `InstrumentDefinitionError` for
  that instrument only; a sibling mapped market in the same batch still loads.
- `BinaryOption.from_dict(json.loads(json.dumps(BinaryOption.to_dict(inst))))`
  yields identical facts. Pins the scalars-only rule.
- `strike_bounds_parsed` is absent from `info`; `strike_bounds` is still present
  (`test_polymarket_us_parsing.py:212` must stay green).
- Pin: `NwsClimateDay.tmax_f` is `int | None`, justifying
  `reading_is_whole_degrees=True`.
- Pin: `REGISTRY_VENUE_KEY` names a venue the packaged registry has.

### 6.8 Gates

- `tests/unit/test_polymarket_us_readonly_guard.py` re-run unchanged, plus one
  added assertion in that suite: `is_venue_touching` is `False` for
  `src/breezy/domain/weather_bucket_facts.py` and for every strategy module
  found by **`rglob("*.py")`** — not `glob("*.py")`, because
  `tests/unit/test_strategy_module_gate.py:26` exists to remember that a
  strategy in a subpackage escapes a single-star glob.
- import-linter, both contracts, **with no ignore-list edit**.

**Revision 1's proposed AST barrier is CUT.** It would have banned the
`*_KEY` string literals inside `src/breezy/strategy/`. Revision 1 already
conceded it cannot detect a hand-derived bucket — which is the actual hole — and
deleting `strike_bounds_parsed` (§4.4) plus deleting `_BUCKETS` (§5 step 5) is
what closes it. A barrier that does not stop the failure it is named for is
ceremony that will later be silenced.

---

## 7. What this plan deliberately does NOT do

- **Does not touch Nautilus Trader.** No subclass, no patch, no wrapper. It uses
  `Instrument.info` and `Cache.instrument` as shipped.
- **Does not build a Kalshi adapter or any venue abstraction layer.** It defines
  the key vocabulary where a future Kalshi adapter can write to it, and stops.
  No protocol, no adapter registry, no factory.
- **Does not model YES/NO topology.** `BACKTEST_VENUE_CONFIG.md` §8's
  one-book-two-sides difference is a *sides/exposure* concern, not a *facts*
  concern. `WeatherBucketFacts` says nothing about sides on purpose; conflating
  them is how exposure gets double-counted.
- **Does not weaken, widen, or exempt** C4, V1–V4, the fee guard, or
  `assert_bounds_cross_checked`. No ignore-list entry is added to either
  import-linter contract.
- **Does not generalise beyond whole-degree Fahrenheit temperature buckets.**
  Stated in the module docstring as a scope boundary, and the reason the type is
  named `WeatherBucketFacts`.
- **Does not settle anything.** `WeatherBucketFacts` reads no observation and
  decides no payoff; `contains()` is an interval predicate, not a settlement
  rule. Settlement selection (`is_final`, revisions, `domain/selection.py`) is
  untouched.
- **Does not migrate `harness_probe` or `resting_ladder`.** Neither reasons
  about buckets; a docstring pointer is the whole change.
- **Does not add forecast, edge, or sizing logic.**
- **Does not bump `registry_version`** (§4.3 — a decision, with its reason).

*(Revision 1 also listed "does not remove `strike_bounds_parsed`". That
non-goal is REVERSED in revision 2: the key has zero readers and is deleted in
increment 3. See §4.4.)*

---

## 8. Open questions and risks

**Requires live venue observation — the bot must discover these itself; the
operator supplies no venue facts.**

1. **`measure="low"` has never been observed.** All 729 captured markets are
   `high`, so the `Measure.LOW` branch has zero corpus coverage and no mapping
   from `low` to `NwsClimateDay.tmin_f` is proposed here. A strategy must not
   infer the field from `measure` without a capture. Detection: §6.4 asserts the
   observed measure set, so a new value surfaces as a test failure on the next
   capture rather than as silent behaviour.
2. **A newly-listed city refuses that instrument and logs loudly** — decided in
   §4.4, not left open. The residual risk is the inverse of an outage: a city
   silently absent from the traded universe. Mitigated by
   `provider.py:257-263`'s zero-discovery refusal and by the discovery filter at
   `provider.py:362`, but a partial-universe cycle is not currently alarmed.
   Worth a follow-up counter; out of scope here.
3. **The `venue_city_token` values are inferred from 729 captures**, not from
   venue documentation — the slug grammar is recorded UNRESOLVED in
   `symbology.py`. `nyc/mia/mdw/lax/sfo` is total and 1:1 over everything
   observed. A token that collides or changes case needs live re-observation.
4. **`reading_is_whole_degrees=True` is an assumption about SETTLEMENT made at
   parse time.** It is exactly the assumption `provider.py:405` already makes,
   backed by `tmax_f: int | None`. It breaks if the venue ever settles a city on
   a fractional or record-qualifier reading — a case this repo has already met in
   NWS parsing. Pinned by §6.7 but not *proven*; needs live confirmation per city
   before real money.
5. **The day-level corroboration: open a venue-observation task, land nothing.**
   (Answering revision 1's own question.) Measured over the corpus, `endDate` in
   `America/New_York` falls on `climate_date + 1 day` in **729 of 729** markets —
   but the hour is **not** the registry's 08:00 ET settlement instant, and it is
   not noise either. It partitions exactly by city group:

   | ET hour | markets | cities |
   |---|---|---|
   | 01:00 | 677 | `nyc` 653 + `mia` 24 |
   | 02:00 | 30 | `lax` 18 + `sfo` 12 |
   | 04:00 | 22 | `mdw` 22 |

   That is a per-city rule, and it is **non-monotonic against the site
   timezones**: Eastern cities at 01:00, Pacific at 02:00, and Central — between
   them — at 04:00. So it is not a fixed UTC instant rendered locally, and the
   relationship between the venue's trading close and its 08:00 ET settlement
   clock is unexplained. Encoding a day-corroboration check now would freeze a
   rule we cannot yet state, and the DST behaviour of that boundary is
   unobserved. **Open a venue-observation task; add no check in this plan.**
   Worth knowing before any settlement-timing work.
6. **`weather_facts_status` vs the existing `fee_schedule_status`.** Two
   independent status markers now live in `info`. Deliberate (they fail for
   different reasons and unlock different paths), and the narrow type name
   (§4.1) is the defence against them merging into an "is this instrument OK"
   god-flag. A reviewer should confirm that holds.
7. **Increment 4 is the largest unknown in the plan.** Rewriting the contract
   fixture's date triple touches a file with ~22 passing assertions written
   against an incoherent record (§1.4). The risk is that repairing coherence
   changes engine timing (the tape anchors on `max(activation_ns) + 1s`) and
   perturbs assertions unrelated to weather. It is scoped as its own increment
   with its own RED for exactly that reason, and it must land before increment 5
   rather than being folded into it.
