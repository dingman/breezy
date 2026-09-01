# Trading Enablement — Merged Findings (coordination artifact)

Merged from five blind specialist seams dispatched 2026-08-24: Nautilus native
surface (architect), Polymarket.us venue demands (Explore), alpha layer
(trading-bot-architect), risk/market mechanics (prediction-market-reviewer),
codebase readiness (code-explorer). This file is the INPUT to the planning
gate, not the plan.

Evidence grades are carried through from the seams. `[UNKNOWN]` is a finding,
not a gap in the research.

---

## A. Contradictions between seams — resolved here

### A1. Does NautilusTrader's shipped Polymarket adapter serve our venue? NO.

The architect seam found 1.231.0 ships a complete first-party Polymarket
adapter (39 modules, `adapters/polymarket/`) and concluded the correct default
under the null hypothesis is "Breezy writes no venue adapter at all", flagging
.com-vs-.us as its #1 blocking unknown.

The venue seam independently established, from a digest-verified capture plus
the venue skill, that Polymarket.us is:

- Ed25519 request signing via `X-PM-Access-Key` / `X-PM-Timestamp` /
  `X-PM-Signature` headers, ±30s clock window, no wallet.
- Fiat USD custodied by a CFTC-regulated DCO. No pUSD, no Polygon, no
  ERC-20 collateral.
- Slug-addressed markets (`GET /v1/market/slug/{slug}`), hosts
  `api.polymarket.us` / `gateway.polymarket.us`.
- Fee `Theta * C * p * (1-p)` with taker `0.06`, maker `-0.0125` (a rebate).

The shipped adapter is EIP-712 order signing with `POLYMARKET_PK`, Gnosis-Safe
proxy signature types, pUSD-on-Polygon collateral, `condition_id`/`token_id`
identifiers, `clob.polymarket.com`, and a hard module-scope import of
`py_clob_client_v2` (which is not installed in this venv).

**RESOLUTION: incompatible at the auth, custody, and identifier layers
simultaneously. The shipped adapter is NOT reusable as a client for our
venue.** It remains highly valuable as (a) proof that `BinaryOption`,
`LiveExecutionClient` and `LiveMarketDataClient` are the right native base
classes, and (b) a reference implementation for the report-generation and
websocket-client structure Nautilus expects. Breezy MUST BUILD a
`polymarket_us` adapter on the native base classes. This does not violate the
immutable-foundation rule — it is the intended native extension mechanism.

Corollary: the architect's TRAP-1 (the `resolve_poll_*` config being accepted
and silently ignored by the Python data client) becomes moot, because we do
not use that client. Breezy drives settlement itself either way.

### A2. Are weather records published on the message bus? YES.

`docs/core/PROGRESS.md` records `has_msgbus_backing=False`, which has been read
as "records are not published". The code disagrees and the code wins:
`nws_actor.py:1444-1452` `_publish_records` calls `self.publish_data(...)`,
invoked at `:1049` every poll and at `:1486` in `warm_start`.
`has_msgbus_backing=False` refers to `message_bus=None` in
`node_config.py:152` — i.e. no Redis-backed message-bus DATABASE. The
in-process bus exists and is being published to. A `Strategy` can subscribe
today. PROGRESS.md should be corrected.

### A3. Fee model — two numbers in the repo, one venue.

`docs/reference/nautilus/digests/prediction-markets-native-support.md:198`
carries Weather taker `0.05` / maker `0` — those are Polymarket**.com**
figures and must never reach the .us fee model. Use `0.06` / `-0.0125`.

> **[CORRECTED]** The paragraph originally here was wrong on a checkable
> fact, and the peer review caught it (recorded as S4 in
> `TRADING_ENABLEMENT_REVIEW.md`). It claimed the shipped fee model could not
> express the probability curve or a maker rebate. It can:
> `PolymarketFeeModel` (`adapters/polymarket/fee_model.py:224-324`,
> `common/parsing.py:352-395`) **does** implement `qty * rate * p * (1-p)` and
> **does** return a negative `Money` for `LiquiditySide.MAKER`. The taker-only
> limitation belongs to `ProbabilityPriceFeeModel`, a different class.

What is actually true: the doc-prescribed `ProbabilityPriceFeeModel` import
raises `ImportError` in this build (`execution/__init__.py` is docstring-only;
`backtest/models/fee.pyx` defines only Maker/Taker, Fixed, PerContract), so
that class is genuinely absent. `PolymarketFeeModel` exists and has the right
shape, but it is bound to the **.com** adapter — the same adapter A1 shows is
unusable at the auth, custody and identifier layers — and carries .com rates.

**The conclusion is unchanged but now rests on different grounds:** Breezy must
build its own `FeeModel` subclass because the correctly-shaped implementation
is welded to an unusable adapter, NOT because Nautilus cannot express the
curve. Per CLAUDE.md's null hypothesis, the native shape should be the
reference for that subclass rather than something re-derived from scratch.

### A4. Two different paper-trade bars were proposed. Both are right, for
different paths.

The alpha seam proposed a model-grade bar: BSS CI-lower-bound > 0.05 vs ACIS
climatology, no reliability bin overconfident by >0.05, >=400 settled pairs
per traded stratum and >=2,000 overall. At ~5 pairs/day that is ~13 months
forward — which is why historical backfill is not optional for the model path.

The risk seam proposed an execution-grade bar: >=200 settlements, >=30 per
city, zero safety-gate violations, positive PnL at 1.5x stressed fees, and —
the harder test — beating the MARKET-IMPLIED probability baseline, not just
climatology.

**RESOLUTION: a two-tier enablement gate.** Tier 1 (deterministic intraday
path, where P is arithmetic rather than estimated) is gated on the
execution-grade bar only — calibration statistics are meaningless for a
quantity that is not being estimated. Tier 2 (model-priced path) additionally
requires the full model-grade bar, per stratum, with walk-forward calibration.
Both tiers require zero safety-gate violations and 100% settlement
reconciliation.

---

## B. The strategic finding: what we ingest is labels, not signal

`NwsClimateDay` is only ever written AFTER the climate day has largely
elapsed — preliminary at ~16:00 local, final ~02:27 the next day. A contract
on today's high is tradeable long before either exists. Therefore:

**Everything Breezy has built so far is settlement truth and training labels.
It contains no tradeable signal at all.** A second, disjoint ingestion family
is required before any model-priced trade: forecasts (NWS gridpoints) and
intraday observations (METAR).

The exploitable structure, and the reason the first trade should not be a
model trade: the daily max is a running maximum. Once observed temperature
reaches the strike, P = 1 as arithmetic, not as prediction — no model, no
residual distribution, no calibration. The alpha seam verified live that
`api.weather.gov/stations/KNYC/observations` serves this, with one critical
defect: the parsed `maxTemperatureLast24Hours` field is null while the raw
METAR remark groups carry the data. The raw message must be parsed; the
convenience field must not be consumed.

Asymmetry that must be encoded: the observed running max is a LOWER bound.
Trading P=1 off it is safe. Trading P=0 off "we haven't seen it yet" is NOT —
the true max can fall between observations. The P~0 side must come from the
model's upper tail only.

---

## C. What is already built and wired to nothing

- `gate.require_open(venue, city)` has ZERO production callers. The
  fail-closed settlement gate — 3 states, 29 reasons, 15 CRIT, persisted,
  re-derived per call, default-BLOCKED — was designed as the trading kill-gate
  and is documented as such at `nws_actor.py:789-791`. The ingest path
  deliberately uses a narrower predicate to avoid first-boot deadlock.
- `src/breezy/settlement/` is empty but already in mypy's strict `files` list.
  Its contract is fully specified in prose across `gate.py:875`,
  `catalog.py:552-587`, `nws_raw_product.py:211`, `nws_climate_day.py:77`.
- `src/breezy/features/` is empty and NOT in mypy `files` — adding it is a
  required first step.
- `read_climate_day_as_of_settlement(..., as_of_ts_init=)` exists with a
  mandatory bound, alongside `read_climate_day_including_corrections` marked
  "never call this from a settlement, reconciliation or retry path". This
  split is the single most important pre-existing contract for the trading
  build, and it is also exactly the primitive a no-lookahead backtest needs.
- `registry/sites.py` `SettlementDeadline` already models the venue's 08:00 ET
  clock AND the 11:00 ET METAR-review delay, separately from the climate-day
  window. Trading horizon math reads these; no hardcoded "08:00" is permitted.
- `runtime/health.py` alerting substrate, including the cold-start-fires rule
  that a latch already true at boot must alert on the first cycle.

## D. Blockers the existing backlog does not name

1. `src/breezy/settlement/` empty — the largest gap, absent from PROGRESS.md's
   open follow-ups entirely.
2. `require_open` has no callers (D1's consequence).
3. `SharedIngestState.__init__` builds `HttpTransport` unconditionally
   (`shared_state.py:381-387`), so `BREEZY_USER_AGENT` is required even for
   offline construction. PROGRESS.md defers this "unless a backtest path
   lands". A backtest path is exactly what this work needs — it is now
   blocking.
4. Streaming catalog replay RAISES for these record types (the Rust
   `DataBackendSession` cannot see a Python `register_arrow` schema);
   backtest replay is one-shot and therefore memory-capped. Contract-tested,
   not in PROGRESS.md.
5. No secret-handling path exists anywhere in the codebase. `health.py`'s
   redaction guarantee is structural — there is no attribute slot to hold a
   credential — and a credential-carrying config is the first thing that would
   punch through it.
6. `gate.require_open` is thread-confined via `SqliteStateStore`
   (`sqlite_store.py:101-104`). A Strategy or exec-client callback calling it
   off the event-loop thread raises exactly when the halt matters.
7. Nautilus `Cache` must never hold a trading halt latch — `health.py` already
   records that `Cache.reset()` can launder a permanent halt.

## E. Nautilus traps that survive into our own adapter

- `BINARY_OPTION` is absent from `ENGINE_EXPIRING_INSTRUMENT_CLASSES`, so a
  backtest NEVER expires a binary. An `InstrumentClose` with
  `close_type=CONTRACT_EXPIRED` must be injected AND `settlement_prices`
  populated — `close.close_price` is never read by the matching engine.
  Without both, every position silently shows open at end-of-run.
- `DataType` metadata is topic identity by insertion ORDER, while `__eq__`
  compares a frozenset. Equality-based unit tests pass while production
  delivers zero messages. Use the existing `lru_cache`d
  `nws_climate_day_data_type()` factory; never construct `DataType` inline;
  never add metadata on one side only.
- CASH accounts return a POSITIVE balance impact for SELL, so the RiskEngine
  free-balance check never blocks a naked sell. The strategy gate must check
  `cache.position(...)` before any SELL.
- `generate_mass_status` swallows reconciliation failure (bare `except
  Exception` -> log -> return None). Combined with
  `generate_missing_orders=True`, a venue outage at startup produces a node
  that believes it is flat. An explicit startup assertion is required.
- `TraderId` SIGABRTs rather than raising on bad input; assume the same class
  of Rust panic for `Price`/`Quantity` precision violations. Pre-validate.

## F. The venue unknowns that actually block a first trade

Ranked. Probes G2/G3 need no credentials and no venue network at all — they
are reads of the open-source `polymarket_us` Python SDK — and should run first
because they are free and they also settle several other rows.

- G1 weather market SLUG GRAMMAR — undocumented. We cannot address the
  instrument we intend to trade.
- G2 order placement / cancel / status / fills / positions / balances endpoint
  paths and methods — none documented. SDK source read.
- G3 whether the request BODY is part of the Ed25519 canonical string — the
  documented recipe is `timestamp + METHOD + path` with no body hash. If wrong,
  100% of order submissions fail auth. SDK source read.
- G4 per-market `orderPriceMinTickSize` and `minimumTradeQty` — per-market,
  never a global constant, never observed.
- G5 bucket boundary operator `>` vs `>=` and rounding at the strike. The repo
  has ALREADY correctly frozen the resolver on this; guessing is the failure
  mode that freeze exists to prevent.
- G6 WebSocket subscribe/auth/heartbeat schema and whether sequence numbers
  exist at all — the entire WS surface is two URLs and nothing else.
- G7 the `intent` x `outcomeSide` x `action` required-combination matrix —
  three overlapping direction encodings with no documented precedence rule.
  A wrong-side-of-market hazard. Needs order submission -> operator exception.
- G8 order idempotency inside the 30s window. The venue's documented
  "Global Rate Limit Exceeded" 5-second stopgap invites a retry; without
  idempotency that retry is a double position.
- G9 does the venue settle off the FINAL or the PRELIMINARY CLI, and what
  happens when a Pacific final is late past 08:00 ET. Breezy's `is_final` gate
  makes it structurally unable to predict a preliminary-based settlement.
  Needs a running observation window — start early.
- G10 post-settlement correction policy. Breezy models supersession as
  post-settlement-capable; the venue's captured rules are silent. If the venue
  never re-settles, correction handling is a PRE-settlement race, not a
  recovery path.
- G11 position limits, self-trade prevention, automated-trading ToS. Wash
  trading on a CFTC DCM is statutory, not a fee footnote.
- G15 whether `gateway.polymarket.us` is reachable from a server process at
  all — it is documented as returning 403 to non-browser fetches. Cheap, and
  it invalidates a whole architecture branch if it fails.

There is NO retail sandbox. Every POST is real money.

## G. Non-negotiables carried from the seams

- Every venue parameter is a REQUIRED INPUT with no default. Config
  construction must raise when any is unset. Precedent: `BREEZY_SITES` has
  deliberately no "all sites" default.
- Never `p > price`. Edge is fee-inclusive, slippage-inclusive at the intended
  size, re-checked AFTER tick rounding, compared with strict `>`.
- Adjacent strikes on one city-day are ONE bet. Kelly allocates per cluster,
  not per market. Crude conservative cluster caps beat an estimated
  correlation matrix built on weeks of data.
- Walk-forward calibration enforced STRUCTURALLY by a time-bounded data view,
  not by reviewer discipline. Fitting calibration on full history is the
  standard way a weather bot's paper results look profitable and its live
  results do not.
- Settlement disagreement between venue and Breezy's FINAL record latches a
  halt for that city, books PnL at the VENUE's number, retains Breezy's value
  as dispute basis, and excludes the day from calibration until classified.
  The captured Miami preliminary->final 5 F revision is the live scenario.
- "Settles at last fair market prices" after 7 days without data means
  resolution is NOT always binary. Payout math must accept a fractional
  settlement price.
- Real-money enablement is an operator-only ceiling with no default and no
  code path that infers it. No agent and no checked-in config may set it.
