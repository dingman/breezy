# G-18 — Autonomous market discovery (replaces the static slug list)

**Phase:** A support — **on the critical path.** G-14 (continuous capture) must
not start without this.
**Opened:** 2026-08-26, on operator direction: *"The bot must be capable of
autonomous discovery, the operator will never provide that information."*

## Problem

`POLYMARKET_US_MARKET_SLUGS` is a **static, required, comma-separated env var**
(`factories.py:123-186`), and `PolymarketUSInstrumentProvider` fetches exactly
that tuple one slug at a time via `MARKET_BY_SLUG_PATH = "/v1/market/slug/{slug}"`
(`provider.py:57`, `:113-115`). `load_ids_async` actively **refuses** any
InstrumentId outside the configured tuple — "refusing to fetch an unbudgeted
market" (`provider.py:117-140`).

Weather market slugs are **per-day**: `tc-temp-nychigh-2026-08-25-lt79f`.

**Therefore continuous capture with a static list records nothing from day two
onward, and looks exactly like a quiet market.** G-14 is broken by construction
as currently built. This is the same silent-failure class as the three
already-documented tape traps, and it lands on the one dataset that cannot be
backfilled.

The fail-closed instinct in `provider.py:88-92` (an empty universe raises rather
than "loads silently and quoting nothing") is **right, and must be preserved** —
but it is currently pointed at the wrong input. It should fire on *discovery
returned zero*, every cycle, not on *the operator forgot a slug*, once at
construction.

## The venue does support enumeration — this is verified, not assumed

From the vendored SDK snapshot and, more importantly, from **captured payloads
already committed to this repo**:

- `GET /v1/markets` — list, with `limit`, `offset`, `orderBy`, `orderDirection`,
  `id[]`, `slug[]`, `eventSlug[]`, `archived`, `active`, `closed`,
  `liquidityMin/Max`, `volumeMin/Max`, `categories[]`
  (`sdk_snapshot/.../resources/markets.py:19`,
  `types/markets.py:99-115`). Corroborated by the venue's own OpenAPI snapshot
  at `docs_snapshots/api-reference_markets_get-markets_2026-08-25.md:15-80`.
- `GET /v1/events`, `GET /v1/series`, `GET /v1/search` also exist
  (`resources/events.py:12`, `series.py:12`, `search.py:12`).
- Weather series ids **35-44** are enumerated in `raw/series_limit100.json`;
  e.g. `weather-daily-high-nyc` = 35 (`VENUE_FACTS_2026-08-25.md:544-553`).

**Captured list responses already on disk:** `raw/markets_categories_climate.json`
(`GET /v1/markets?limit=20&categories=climate`), `raw/markets_tagIds_weather.json`,
`raw/markets_slug_open.json`, `raw/events_seriesId_35_active.json`,
`raw/series_limit100.json`, `raw/search_weather.json`.

Verified field set on a listed market object (read directly from
`markets_categories_climate.json`, 20 markets):

    active, archived, category, closed, comboEnabled, createdAt, description,
    endDate, ep3Status, ep3SyncedAt, feeCoefficient, gameStartTime, hidden, id,
    manualActivation, marketSides, marketType, minimumTradeQty,
    orderPriceMinTickSize, outcomePrices, outcomes, question, slug, sortOrder,
    sportsMarketType, sportsMarketTypeV2, startDate, status, tags, title,
    titleShort, updatedAt

So discovery has everything it needs: **`slug`**, **`endDate`**, **`active` /
`closed` / `archived` / `status`**, plus `orderPriceMinTickSize`,
`minimumTradeQty` and `feeCoefficient` per market.

**Two field-name facts that must not be conflated:**

- REST **list/market objects** use `slug` (verified above).
- WebSocket **market-data frames** use `marketSlug` — corroborated by
  `sdk_snapshot/.../websocket/types.py:84,136,153,173` (`_MarketDataPayload`).
  This is the key `MARKET_SLUG_KEY` guesses at (`data.py:148`). The guess is now
  **well-corroborated but still not venue-confirmed**: the SDK snapshot is
  evidence, not authority. G-12 stays open until a live frame proves it.

**No numeric strike field exists.** The strike lives only in the `slug` and in
`description` prose. Discovery must therefore parse the slug grammar — which
`symbology.py:18-19` records as **INFERRED and fallible**, with a known
disagreement (`lt81` vs venue prose "between 80F and 81F", `symbology.py:33-45`).
`assert_bounds_cross_checked` (`symbology.py:275-324`) already exists for this
and must be applied to every discovered market.

## Nautilus already provides the pattern — do not invent one

Null hypothesis upheld. `InstrumentProvider.initialize(reload=True)`
(`common/providers.py:150`) is the native **reload primitive**; Nautilus does not
schedule it. The scheduling pattern is bundled adapter prior art, and it is a
close match — same venue family, markets that open and resolve continuously:

`nautilus_trader/adapters/polymarket/data.py`:
- `_connect()` (`:180-194`) — `initialize()` once, push all instruments to the
  engine, then spawn `self.create_task(self._update_instruments(interval_mins))`
  if configured.
- `_update_instruments()` (`:410-418`) — `while True: await asyncio.sleep(...)`,
  `await self._instrument_provider.initialize(reload=True)`,
  `self._send_all_instruments_to_data_engine()`, wrapped for
  `asyncio.CancelledError`.
- `_disconnect()` (`:196-201`) — cancels the task.
- Cadence as config data: `update_instruments_interval_mins: PositiveInt | None`
  (`adapters/polymarket/config.py:120`).

**Rejected alternatives, each with a reason:** a separate `Actor` on a timer
(adds a second lifecycle and failure domain reaching into the client's provider;
no bundled adapter does this); `LiveMarketDataClient._update_instruments` (not a
base-class hook — adapter-authored by convention only); a `DataEngine` hook
(`DataEngine` only reacts to `Instrument` objects handed to it,
`data/engine.pyx:2575-2590` — it never originates a fetch).

## The ordering invariant that must not be violated

`StreamingFeatherWriter` looks up `cache.instrument(instrument_id)` and, when it
is `None`, **silently drops the record — no exception, no warning**
(`persistence/writer.py:228-239`). This repo has already been bitten by this
exact trap once.

Therefore: `_send_all_instruments_to_data_engine()` must complete, and
`cache.instrument(id)` must be non-`None`, **strictly before** any
`subscribe_quote_ticks` for that id. Nautilus does not enforce this — the design
must, and a property test must pin it.

Expiry has no native signal for this venue shape either: Nautilus does not evict
from `Cache` on market close, so the discovery loop must detect "this slug has
resolved" (via `closed` / `status` / `endDate`) and drive `unsubscribe_*` itself.

## Approach

1. Replace the required `POLYMARKET_US_MARKET_SLUGS` with a **discovery query
   config**: the venue filter parameters (categories/series/tag + active/closed
   flags), the city registry to map markets to our five sites, and a
   **required-no-default reload interval**.
2. Rewrite `PolymarketUSInstrumentProvider.load_all_async` to enumerate via
   `GET /v1/markets` with pagination, instead of iterating a fixed tuple.
   Preserve the fail-closed empty-universe guard, re-pointed at *discovery
   returned zero on this cycle*.
3. Port the `_connect` / `_update_instruments` / `_disconnect` task lifecycle
   onto `PolymarketUSDataClient`, following the bundled adapter's shape.
4. Enforce the ordering invariant of the previous section, with a property test.
5. Drive `unsubscribe_*` for resolved markets, keyed on the venue's own
   `closed` / `status` / `endDate` — never on our own clock.
6. Cross-check every discovered slug through `assert_bounds_cross_checked`
   against the market's `description` prose, and fail closed on disagreement
   rather than trading a misparsed strike.
7. Add a discovery quota bucket — `transport.py:73-82` currently has only
   `instruments` / `book` / `portfolio` / `default`.

## Instrumentation — non-optional, because the tape cannot be backfilled

A discovery failure must be **loud**, never indistinguishable from a quiet
market. `InstrumentProvider`'s own "No instruments were loaded" is INFO-level
(`providers.py:185`) and invisible to an unattended process.

Required, per cycle: instrument count before and after reload; an explicit alert
when the count hits zero or drops without a matching resolved-market
explanation; an explicit alert when a slug is discovered but
`cache.instrument(id) is None` after the engine push (a broken invariant, not a
business event); and a per-cycle audit record of which slugs were subscribed or
unsubscribed and why (new / resolved / discovery-missing). Persist **last
successful non-empty discovery** as a monitored fact — never infer health from
tape volume.

## Risks

- **Midnight rollover race.** If the next day's markets are not listable until
  00:00 UTC or later, a reload at :00 sharp loads nothing. The interval must be
  short enough to self-heal within one cycle — the bundled default of 60 minutes
  is far too slow for per-day markets; target 5-15 minutes.
- **Partial ladder coverage.** Pagination or filter defects could return a
  city's ladder incompletely. Assert ladder continuity per city-day and alert on
  gaps.
- **Slug grammar is inferred.** A grammar change at the venue silently shrinks
  the discovered universe. The cross-check in step 6 is what catches it.

## GREEN criterion

Discovery enumerates today's weather markets for the configured cities with no
operator-supplied slug list; new markets are picked up and resolved ones dropped
within one reload cycle without a node restart; the ordering invariant is
property-tested; a zero-discovery cycle raises loudly; and gates are green.
Verification is offline against the captured list payloads — **no live venue
call is required to build or test this.**
