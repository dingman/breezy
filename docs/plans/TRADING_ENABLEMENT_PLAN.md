# Trading Enablement Plan — Breezy on Polymarket.us

Status: **BLOCKED PENDING AMENDMENT** — adversarial peer review 2026-08-24 returned
BLOCK from all four reviewers (architecture, security, prediction-market domain,
Python stack). Phases 0 and 1 are cleared to proceed; Phase 1.5 must be
restructured and Phase 2 entry is blocked. See
`docs/plans/TRADING_ENABLEMENT_REVIEW.md` for the required amendment set. Do not
implement from this document until those amendments land.

Original status: PLAN (peer review pending). Input: `docs/plans/TRADING_ENABLEMENT_FINDINGS.md`
(treated as settled for its section A resolutions). Repo state:
`docs/core/PROGRESS.md` (Phase 1 ingestion built and live-validated).

Section A of the findings is not re-litigated here. Where the findings record an
`[UNKNOWN]`, this plan states BOTH branches and never schedules work that assumes
one outcome.

---

## 1. Objective and non-goals

### Objective

Take Breezy from "NWS CLI ingestion live on five sites" to "placing and settling
real-money orders on Polymarket.us weather markets", through two enablement
tiers: a deterministic intraday path first, a model-priced path second.

### Non-goals (explicit)

| Non-goal | Reason |
|---|---|
| **Kalshi** | NautilusTrader 1.231.0 ships no Kalshi adapter. Kalshi is a later phase; nothing in this plan may hardcode Polymarket.us semantics into shared code in a way that a second venue cannot be added beside. Portability is a design constraint, not a deliverable. |
| Any modification, patch, fork or vendoring of NautilusTrader | Immutable foundation (CLAUDE.md). |
| Forking the shipped `adapters/polymarket/` (.com) adapter | Findings A1: incompatible at auth, custody and identifier layers simultaneously. We READ it as reference; we never copy it into `src/`. |
| PostgreSQL / TimescaleDB / Redis / DuckDB / vector store / feature store | See §7. |
| Multi-venue arbitrage, market making, sports/politics markets | Out of scope. Weather binaries only. |
| A general-purpose forecast model | Tier 2 needs a *calibrated conditional distribution for the day's max*, nothing broader. |

### Standing constraints this plan is bound by

1. Extension only through native mechanisms. Building `polymarket_us` on
   `LiveExecutionClient` / `LiveMarketDataClient` / `BinaryOption` IS the native
   mechanism (findings A1) and is not a violation.
2. **A live run is part of the definition of done for anything in the runtime
   path.** The unit suite was fully green twice while the deployment was dead
   (PROGRESS.md, "Standing lesson"). Every exit criterion below that touches a
   running process names a live artifact, not a test count.
3. TDD mandatory: RED -> GREEN, evidence retained. Gates: `uv run pytest -q`,
   `uv run ruff check .`, `uv run mypy`.
4. **Every new package must be added to `[tool.mypy].files` in `pyproject.toml`
   in the same change that creates it.** `src/breezy/features/` is currently
   absent from that list and would silently escape strict typing.
5. **No venue parameter gets a default value.** Config construction raises when
   any required venue input is unset. Precedent: `BREEZY_SITES`,
   `BREEZY_USER_AGENT`.
6. Real-money enablement is an operator-only ceiling. No agent, no checked-in
   config, and no inferred code path may set it.

---

## 2. Requirements register

Evidence grades carried from the findings: **[VERIFIED]** = observed in code or
a live capture; **[DOCUMENTED]** = stated by venue/Nautilus docs, not observed;
**[INFERRED]** = reasoned from adjacent evidence; **[UNKNOWN]** = a finding, and
a probe target.

Tiers: `BLOCKS-FIRST-TRADE` (Tier 1 cannot happen without it) /
`BLOCKS-SCALE` (Tier 1 can run at capped size; required before size increases or
Tier 2) / `LATER`.

### Venue (REQ-VENUE)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-VENUE-01 | A `polymarket_us` adapter package on native Nautilus base classes; the shipped `.com` adapter is never imported at runtime. | [VERIFIED] findings A1 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-02 | Ed25519 request signing: `X-PM-Access-Key` / `X-PM-Timestamp` / `X-PM-Signature`, ±30s clock window. | [VERIFIED] digest-verified capture | BLOCKS-FIRST-TRADE |
| REQ-VENUE-03 | Determine whether the request BODY participates in the Ed25519 canonical string (G3). If it does not, `timestamp + METHOD + path`; if it does, body-hash included. | [UNKNOWN] G3 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-04 | Order placement / cancel / status / fills / positions / balances endpoint paths and methods (G2). | [UNKNOWN] G2 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-05 | Weather market slug grammar; slug -> `InstrumentId` and back, deterministic and round-trippable (G1). | [UNKNOWN] G1 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-06 | Per-market `orderPriceMinTickSize` and `minimumTradeQty` read PER MARKET from the venue, never a global constant (G4). | [UNKNOWN] G4 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-07 | `intent` x `outcomeSide` x `action` required-combination matrix resolved and encoded with an explicit precedence rule (G7). Wrong-side-of-market hazard. | [UNKNOWN] G7 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-08 | Order idempotency inside the 30s signing window — a client-supplied idempotency key or an equivalent (G8). Without it, the venue's documented 5s "Global Rate Limit Exceeded" retry advice creates double positions. | [UNKNOWN] G8 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-09 | `gateway.polymarket.us` reachability from a headless server process (G15); documented as 403 to non-browser fetches. | [UNKNOWN] G15 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-10 | WebSocket subscribe/auth/heartbeat schema; whether sequence numbers exist at all (G6). If absent, the data client must detect gaps by another means or degrade to polling. | [UNKNOWN] G6 | BLOCKS-SCALE |
| REQ-VENUE-11 | Fee model `Theta * C * p * (1-p)`, taker `0.06`, maker `-0.0125` (a REBATE), implemented as a `FeeModel` subclass. The `.com` figures `0.05`/`0` must never reach it. | [VERIFIED] findings A3 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-12 | Position limits, self-trade prevention, and automated-trading ToS compliance (G11). Wash trading on a CFTC DCM is statutory. Captured as Phase 0 evidence; escalates to an operator matter ONLY if the captured text actually prohibits automated order flow. | [UNKNOWN] G11 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-13 | A credential-handling path: Ed25519 private key loaded from environment/secret file, never logged, never an attribute on any health/alert/snapshot type. | [VERIFIED] findings D5 — no secret path exists anywhere today | BLOCKS-FIRST-TRADE |
| REQ-VENUE-14 | Every venue config parameter is required-with-no-default; construction raises when unset. | [VERIFIED] findings G | BLOCKS-FIRST-TRADE |
| REQ-VENUE-15 | Rate-limit handling that is safe under REQ-VENUE-08: back off, never blind-retry a POST. | [DOCUMENTED] | BLOCKS-FIRST-TRADE |
| REQ-VENUE-16 | Market discovery: enumerate today's weather markets for our five cities and map each to a registry site. | [UNKNOWN] depends on G1 | BLOCKS-FIRST-TRADE |
| REQ-VENUE-17 | Instrument construction as `BinaryOption` with venue-sourced precision; pre-validate every `Price`/`Quantity` before construction (Rust panics abort the process, not raise). | [VERIFIED] findings E | BLOCKS-FIRST-TRADE |

### Data (REQ-DATA)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-DATA-01 | Intraday METAR observation ingestion from `api.weather.gov/stations/{id}/observations`, parsing the RAW message remark groups. The parsed `maxTemperatureLast24Hours` convenience field is null and must not be consumed. | [VERIFIED] alpha seam live check | BLOCKS-FIRST-TRADE |
| REQ-DATA-02 | A running-max feature per (site, climate day) derived from REQ-DATA-01, published on the message bus. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-DATA-03 | `src/breezy/features/` added to mypy `files` before any code lands in it. | [VERIFIED] findings C | BLOCKS-FIRST-TRADE |
| REQ-DATA-04 | Venue quote-tape recorder: capture top-of-book / trades for our markets to the catalog, running continuously from as early as possible. This is the only source of the market-implied baseline the Tier-1 bar requires, and the sole input to the Phase 1.5 premise-falsification gate. | [INFERRED] findings A4 | BLOCKS-FIRST-TRADE |
| REQ-DATA-05 | `SharedIngestState.__init__` must permit offline construction — it builds `HttpTransport` unconditionally (`shared_state.py:381-387`), so `BREEZY_USER_AGENT` is required even with no network. Blocking now that a backtest/replay path is in scope. | [VERIFIED] findings D3 | BLOCKS-FIRST-TRADE |
| REQ-DATA-06 | Weather records are already published on the in-process message bus (`nws_actor.py:1444-1452`); a `Strategy` can subscribe today. PROGRESS.md's `has_msgbus_backing=False` note must be corrected — it refers to `message_bus=None` (no Redis DATABASE), not to publication. | [VERIFIED] findings A2 | BLOCKS-FIRST-TRADE (doc fix) |
| REQ-DATA-07 | `DataType` metadata must come from the existing `lru_cache`d `nws_climate_day_data_type()` factory. Never construct `DataType` inline; never add metadata on one side only — topic identity is insertion ORDER while `__eq__` is a frozenset, so equality tests pass while production delivers zero messages. | [VERIFIED] findings E | BLOCKS-FIRST-TRADE |
| REQ-DATA-08 | NWS gridpoint forecast ingestion (a second, disjoint ingestion family). | [VERIFIED] findings B | BLOCKS-SCALE (Tier 2) |
| REQ-DATA-09 | Historical backfill of forecasts + observations + settled outcomes, sufficient for the model-grade bar (>=2,000 settled pairs; ~13 months at live rate). | [VERIFIED] findings A4 | BLOCKS-SCALE (Tier 2) |
| REQ-DATA-10 | Backtest replay is one-shot and memory-capped: streaming catalog replay RAISES for our record types (Rust `DataBackendSession` cannot see a Python `register_arrow` schema). Any replay harness must be built within that bound. | [VERIFIED] findings D4, contract-tested | BLOCKS-SCALE |
| REQ-DATA-11 | Before any METAR/ACIS station selection lands, `never_substitute` / `never_substitute_cli_locations` must be consumed or a `TODO(Phase 2)` placed at the selection call site. | [VERIFIED] PROGRESS.md open follow-up | BLOCKS-FIRST-TRADE |

### Alpha (REQ-ALPHA)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-ALPHA-01 | Deterministic P=1 rule: once observed running max >= strike (subject to the REQ-SETTLE-03 boundary operator), P is arithmetic, not estimated. | [VERIFIED] findings B | BLOCKS-FIRST-TRADE |
| REQ-ALPHA-02 | The asymmetry is encoded structurally: the observed running max is a LOWER bound. Trading P~1 off it is safe; trading P~0 off "we haven't seen it yet" is NOT and must be refused by the Tier-1 path entirely. | [VERIFIED] findings B | BLOCKS-FIRST-TRADE |
| REQ-ALPHA-03 | Fee- and slippage-inclusive edge at the INTENDED size, re-checked AFTER tick rounding, compared with strict `>`. Never `p > price`. | [VERIFIED] findings G | BLOCKS-FIRST-TRADE |
| REQ-ALPHA-04 | Conditional distribution model for the day's max given forecast + partial-day observations. | [INFERRED] | BLOCKS-SCALE (Tier 2) |
| REQ-ALPHA-05 | Walk-forward calibration enforced STRUCTURALLY by a time-bounded data view, not reviewer discipline. `read_climate_day_as_of_settlement(..., as_of_ts_init=)` is exactly this primitive and already exists with a mandatory bound. | [VERIFIED] findings C, `catalog.py:552` | BLOCKS-SCALE (Tier 2) |
| REQ-ALPHA-06 | P~0 (upper-tail) trades come only from REQ-ALPHA-04's model, never from absence of observation. | [VERIFIED] findings B | LATER (Tier 2) |
| REQ-ALPHA-07 | Market-implied probability baseline computed from REQ-DATA-04, as the comparison the Tier-1 bar is actually scored against. | [VERIFIED] findings A4 | BLOCKS-FIRST-TRADE |
| REQ-ALPHA-08 | **The premise itself must be measured before adapter work.** A persistent, fee-surviving gap must exist between the instant the outcome becomes physically determined (running max clears the strike) and the instant the market prices it. Measured from the tape alone. | [UNKNOWN] — the programme's central assumption | BLOCKS-FIRST-TRADE |

### Execution (REQ-EXEC)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-EXEC-01 | `LiveExecutionClient` subclass: submit / cancel / order-status / fill reports / position reports / account state. | [INFERRED] native surface | BLOCKS-FIRST-TRADE |
| REQ-EXEC-02 | `LiveMarketDataClient` subclass for quotes/trades/book. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-EXEC-03 | Instrument provider producing `BinaryOption` instruments with venue-sourced tick size and min qty (REQ-VENUE-06). | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-EXEC-04 | Explicit startup assertion that reconciliation SUCCEEDED. `generate_mass_status` swallows failure (bare `except Exception` -> log -> return None); combined with `generate_missing_orders=True` a venue outage at startup produces a node that believes it is flat. | [VERIFIED] findings E | BLOCKS-FIRST-TRADE |
| REQ-EXEC-05 | Strategy checks `cache.position(...)` before ANY SELL. CASH accounts return a POSITIVE balance impact for SELL, so the RiskEngine free-balance check never blocks a naked sell. | [VERIFIED] findings E | BLOCKS-FIRST-TRADE |
| REQ-EXEC-06 | All order prices/quantities pre-validated against instrument precision before constructing `Price`/`Quantity` — Rust panics SIGABRT rather than raising, as `TraderId` already demonstrably does (`node_config.py:82-100`). | [VERIFIED] | BLOCKS-FIRST-TRADE |
| REQ-EXEC-07 | Order submission is idempotent under retry (consumes REQ-VENUE-08). | [UNKNOWN] | BLOCKS-FIRST-TRADE |
| REQ-EXEC-08 | Trading horizon math reads `SettlementDeadline` from `registry/sites.py` (08:00 ET clock AND the 11:00 ET METAR-review delay, modeled separately). No hardcoded `08:00` anywhere. | [VERIFIED] findings C | BLOCKS-FIRST-TRADE |
| REQ-EXEC-09 | Adapter callback design must be compatible with the REQ-RISK-02 thread-confinement resolution, which is an INPUT to adapter design, not a later fix. | [VERIFIED] findings D6 | BLOCKS-FIRST-TRADE |

### Risk (REQ-RISK)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-RISK-01 | `gate.require_open(venue, city)` wired as the trading kill-gate. It has ZERO production callers today and was designed for exactly this (`nws_actor.py:789-791`). | [VERIFIED] findings C/D2 | BLOCKS-FIRST-TRADE |
| REQ-RISK-02 | Gate calls are thread-confined via `SqliteStateStore` (`sqlite_store.py:101-104`). A Strategy or exec-client callback calling `require_open` off the event-loop thread raises exactly when the halt matters. The call path must be proven on-loop or the store made loop-affine. **Resolved in Phase 1 as a cross-cutting constraint on adapter callback design.** | [VERIFIED] findings D6 | BLOCKS-FIRST-TRADE |
| REQ-RISK-03 | No trading halt latch may live in the Nautilus `Cache` — `Cache.reset()` can launder a permanent halt. | [VERIFIED] `health.py` | BLOCKS-FIRST-TRADE |
| REQ-RISK-04 | Adjacent strikes on one city-day are ONE bet. Sizing allocates per CLUSTER, not per market, with crude conservative cluster caps — not an estimated correlation matrix. | [VERIFIED] findings G | BLOCKS-FIRST-TRADE |
| REQ-RISK-05 | Per-cluster, per-city, per-day and total-exposure caps, all required-with-no-default, all sourced from operator-set budget ceilings. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-RISK-06 | Fractional-Kelly sizing bounded by REQ-RISK-05. | [INFERRED] | BLOCKS-SCALE |
| REQ-RISK-07 | A pre-trade safety gate that refuses on: gate not OPEN, stale observation, missing tick size, missing market-implied baseline, clock skew > venue window, reconciliation not asserted. Every refusal is counted and alerted. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-RISK-08 | Kill switch: an operator-reachable halt that stops new orders and cancels working orders, independent of the gate's data-integrity latches. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-RISK-09 | Real-money enablement flag with no default and no inferring code path. | [VERIFIED] findings G | BLOCKS-FIRST-TRADE |

### Settlement (REQ-SETTLE)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-SETTLE-01 | `src/breezy/settlement/` implemented. It is EMPTY today yet already in mypy's strict `files` list; its contract is fully specified in prose across `gate.py:875`, `catalog.py:552-587`, `nws_raw_product.py:211`, `nws_climate_day.py:77`. Largest single gap; absent from PROGRESS.md's follow-ups. | [VERIFIED] findings D1 | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-02 | Resolver: (site, climate day, strike) -> outcome, reading via `read_climate_day_as_of_settlement` with the deadline-sourced bound. | [VERIFIED] | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-03 | Bucket boundary operator `>` vs `>=` and rounding AT the strike (G5). The repo has ALREADY correctly frozen the resolver on this; guessing is the failure mode that freeze exists to prevent. | [UNKNOWN] G5 | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-03a | **`BOUNDARY_UNRESOLVED` must be LOUD, never silent.** The resolver emits a counter of markets refused for `BOUNDARY_UNRESOLVED`; the count enters the trading health snapshot; a WARNING alert fires when the refused fraction exceeds a configured share of addressable markets. A high fraction is the finding "G5 is now a first-trade blocker, not a deferred unknown" — green gates must not be able to hide an unaddressable market. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-04 | Does the venue settle off the FINAL or the PRELIMINARY CLI, and what happens when a Pacific final is late past 08:00 ET (G9)? Breezy's `is_final` gate makes it STRUCTURALLY unable to predict a preliminary-based settlement. Needs a running observation window — start on day one. | [UNKNOWN] G9 | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-05 | Post-settlement correction policy (G10). Breezy models supersession as post-settlement-capable; the venue's captured rules are silent. If the venue never re-settles, correction handling is a PRE-settlement race, not a recovery path. | [UNKNOWN] G10 | BLOCKS-SCALE |
| REQ-SETTLE-06 | Settlement disagreement between venue and Breezy's FINAL record: latch a halt for that city, book PnL at the VENUE's number, retain Breezy's value as dispute basis, exclude the day from calibration until classified. The captured Miami preliminary->final 5 F revision is the live scenario. | [VERIFIED] findings G, PROGRESS.md | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-07 | Payout math accepts a FRACTIONAL settlement price — "settles at last fair market prices" after 7 days without data means resolution is not always binary. | [VERIFIED] findings G | BLOCKS-FIRST-TRADE |
| REQ-SETTLE-08 | Backtest expiry: `BINARY_OPTION` is absent from `ENGINE_EXPIRING_INSTRUMENT_CLASSES`, so a backtest NEVER expires a binary. An `InstrumentClose` with `close_type=CONTRACT_EXPIRED` must be injected AND `settlement_prices` populated — `close.close_price` is never read by the matching engine. Without BOTH, every position silently shows open at end-of-run. | [VERIFIED] findings E | BLOCKS-SCALE |
| REQ-SETTLE-09 | 100% settlement reconciliation: every venue settlement matched against Breezy's resolver output, with disagreements classified. | [VERIFIED] findings A4 | BLOCKS-FIRST-TRADE |

### Ops (REQ-OPS)

| ID | Requirement | Evidence | Tier |
|---|---|---|---|
| REQ-OPS-01 | Every new package (`features`, `venue`, `alpha`, `strategy`) added to mypy `files` in the same change that creates it. | [VERIFIED] | BLOCKS-FIRST-TRADE |
| REQ-OPS-02 | A live run is part of DoD for every runtime-path change. `tests/live/` + `BREEZY_LIVE=1` is the existing mechanism. | [VERIFIED] PROGRESS.md | BLOCKS-FIRST-TRADE |
| REQ-OPS-03 | Trading alerts on the existing `runtime/health.py` substrate, including the cold-start-fires rule (a latch already true at boot must alert on the first cycle). | [VERIFIED] findings C | BLOCKS-FIRST-TRADE |
| REQ-OPS-04 | Redaction guarantee preserved: `health.py`'s guarantee is STRUCTURAL — there is no attribute slot to hold a credential. A credential-carrying config is the first thing that would punch through it. A test must pin that no venue credential is reachable from any snapshot/alert type. | [VERIFIED] findings D5 | BLOCKS-FIRST-TRADE |
| REQ-OPS-05 | Trading runbook: start/stop, kill switch, disagreement triage, credential rotation. | [INFERRED] | BLOCKS-FIRST-TRADE |
| REQ-OPS-06 | Verify post-persist health-ledger/snapshot convergence over a multi-cycle run before relying on either for trading alerting. | [VERIFIED] PROGRESS.md open action | BLOCKS-FIRST-TRADE |
| REQ-OPS-07 | Clock discipline: NTP-synced host, and a startup + periodic assertion that local clock skew is inside the venue's ±30s window. | [VERIFIED] REQ-VENUE-02 | BLOCKS-FIRST-TRADE |
| REQ-OPS-08 | MDW live ingestion proof (the only registry site not in the 2026-08-24 four-site proof). | [VERIFIED] PROGRESS.md | BLOCKS-FIRST-TRADE |
| REQ-OPS-09 | Live-test User-Agent read from `BREEZY_USER_AGENT`, skipping when unset; remove the hardcoded personal address at `tests/live/test_nws_live_ingest.py:86`. | [VERIFIED] PROGRESS.md | BLOCKS-SCALE |
| REQ-OPS-10 | Catalog row-count metric/alert (unbounded whole-catalog reads per lookup, `catalog.py:693`). | [VERIFIED] PROGRESS.md | LATER |
| REQ-OPS-11 | `CliContentError`-rate-per-site alert (fail-closed parsing turns one bad token into a full site outage; the `100R` fix closed one instance, not the class). | [VERIFIED] PROGRESS.md | BLOCKS-SCALE |
| REQ-OPS-12 | Correct PROGRESS.md's `has_msgbus_backing` note (REQ-DATA-06) and record this plan. | [VERIFIED] | BLOCKS-FIRST-TRADE |

### Count by tier

| Tier | Count |
|---|---|
| BLOCKS-FIRST-TRADE | 63 |
| BLOCKS-SCALE | 11 |
| LATER | 2 |
| **Total** | **76** |

Family sizes: REQ-VENUE 17, REQ-DATA 11, REQ-ALPHA 8, REQ-EXEC 9, REQ-RISK 9,
REQ-SETTLE 10 (incl. 03a), REQ-OPS 12. Counts recomputed mechanically from the
tables above; an earlier hand count in the drafting pass was wrong and is
superseded.

---

## 3. Phased plan

Ordering rule: **cheapest falsification first.** Phase 0 costs nothing (source
reads and unauthenticated GETs) and can invalidate whole downstream branches;
Phase 1 starts the two long-running observation windows (venue quote tape,
settlement-source observation) because their value is a function of elapsed
calendar time, not of engineering effort; **Phase 1.5 falsifies the programme's
central premise from those tapes alone, before a single line of adapter code**;
model code is last.

Agent routing per CLAUDE.md §3 (Python stack). Implementer default is
**tdd-guide** seeded with `python-patterns` / `python-testing`; **python-reviewer**
is the independent reviewer for every code phase and never reviews its own work.

### Phase 0 — Free falsification (no credentials, no money)

**Entry:** none. Start immediately.

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 0.1 | Read the open-source `polymarket_us` Python SDK source. Extract: endpoint paths+methods, the Ed25519 canonical-string construction (body or no body), the WS subscribe/auth/heartbeat schema, sequence numbers, idempotency keys, and the `intent`x`outcomeSide`x`action` matrix **including the SDK's own order-construction code paths, which are the primary read-only evidence for G7**. Record verbatim excerpts + SDK version + commit into `docs/evidence/venue/polymarket_us/`. | REQ-VENUE-03/04/06/07/08/10 | Explore | M |
| 0.2 | Probe `gateway.polymarket.us` and `api.polymarket.us` reachability from a headless server process — unauthenticated GET only, zero POSTs. Capture status codes and headers. | REQ-VENUE-09 | Explore | S |
| 0.3 | Harvest live weather-market slugs via public read endpoints for our five cities across several days; derive the slug grammar empirically; capture `orderPriceMinTickSize` / `minimumTradeQty` per market to test the "never a global constant" claim. | REQ-VENUE-05/06/16 | Explore | M |
| 0.4 | **Digest-capture the venue ToS / rulebook** on automated trading, position limits and self-trade prevention. This is an EVIDENCE-CAPTURE work item, not an approval checkpoint. It escalates to the operator ONLY if the captured text actually prohibits automated order flow — in which case the programme stops pending that ruling. | REQ-VENUE-12 | Explore | S |
| 0.5 | Determine the bucket boundary operator (`>` vs `>=`) and strike rounding from published rules + observed settled markets. If not determinable, record it as UNRESOLVED — do NOT guess. | REQ-SETTLE-03 | prediction-market-reviewer | M |
| 0.6 | **Read-only inference of the `intent`x`outcomeSide`x`action` matrix** from observed public order/trade data joined against 0.1's SDK order-construction code. Goal: make the Phase 5.1 real-money probe a CONFIRMATION fallback rather than the first resort. | REQ-VENUE-07 | Explore + prediction-market-reviewer | M |
| 0.7 | Adversarial review of 0.1–0.6 findings; explicitly flag anything still `[UNKNOWN]`. | — | prediction-market-reviewer + security-reviewer (0.1 signing only) | S |

**Exit criteria (verifiable artifacts):**
- A dated, digest-sidecar'd capture per item in `docs/evidence/venue/polymarket_us/`.
- A written determination for G2, G3, G6, G8, G15, and either a determination
  or an explicit UNRESOLVED for G1, G4, G5, G7, G11.
- **Branch on G15 (REQ-VENUE-09):** if `gateway.polymarket.us` is server-reachable ->
  proceed as planned. If it is 403-to-non-browser -> Phase 2 must route every call
  through `api.polymarket.us` only, and any capability that exists solely on the
  gateway becomes a hard blocker escalated with its own probe. Both branches are
  planned; neither is assumed.
- **Branch on G3 (REQ-VENUE-03):** signing implementation follows whichever
  canonical string the SDK source shows. If the SDK is ambiguous, the signer is
  built with the canonical string as an injected strategy and BOTH forms are unit
  tested, with the choice deferred to the Phase 5 single-order probe.
- **Branch on G7 (REQ-VENUE-07):** if 0.6 yields an unambiguous matrix ->
  encode it and treat 5.1 as confirmation only. If 0.6 is ambiguous -> the matrix
  stays an injected strategy and 5.1 is the resolving probe.
- **Branch on G11 (REQ-VENUE-12):** if the captured text permits automated order
  flow -> continue silently. If it prohibits or conditions it -> STOP and escalate
  the captured text to the operator; this is the one Phase 0 outcome that can
  halt the programme outright.

### Phase 1 — Long-lead observation windows + branch-independent foundations

**Entry:** Phase 0 exit. Items 1.1/1.2 start the moment 0.3 yields addressable
markets; they run continuously for the rest of the project.

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 1.1 | **Venue quote-tape recorder.** Read-only. Record top-of-book/trades for our cities' markets to a `ParquetDataCatalog` root, continuously, from today. Sole source of the market-implied baseline AND the sole input to Phase 1.5. | REQ-DATA-04, REQ-ALPHA-07/08 | tdd-guide | M |
| 1.2 | **Settlement-source observation window.** Record, per settled market: the venue's settlement value and timestamp, alongside Breezy's PRELIMINARY and FINAL CLI values. Answers G9 by accumulation. | REQ-SETTLE-04 | tdd-guide | M |
| 1.3 | Add `src/breezy/features` (and, when created, `venue`, `alpha`, `strategy`) to `[tool.mypy].files`. RED test: a deliberately untyped stub in the package fails `uv run mypy`. | REQ-DATA-03, REQ-OPS-01 | tdd-guide | S |
| 1.4 | Make `SharedIngestState` constructible offline: `HttpTransport` construction becomes lazy or injectable, so `BREEZY_USER_AGENT` is not required for a no-network path. Preserve fail-fast for the live path. | REQ-DATA-05 | tdd-guide | M |
| 1.5 | METAR intraday observation ingestion: fetch `stations/{id}/observations`, parse the RAW message remark groups. Pin with a real captured fixture where the convenience field is null and the remark carries the value. Consume `never_substitute_cli_locations` at station selection, or place the `TODO(Phase 2)` marker. | REQ-DATA-01, REQ-DATA-11 | tdd-guide | L |
| 1.6 | Running-max feature per (site, climate day), published on the bus via the `lru_cache`d data-type factory pattern. | REQ-DATA-02, REQ-DATA-07 | tdd-guide | M |
| 1.7 | **Resolve the `require_open` thread-confinement constraint (MOVED FROM PHASE 3).** Prove the intended call path is on the event-loop thread, or make `SqliteStateStore` loop-affine. A test must FAIL if `require_open` is called from another thread. **This is an INPUT to Phase 2 adapter callback design** — Phase 2 must not design callbacks blind to it. Publish the resulting callback-threading contract as a short design note consumed by the Phase 2 brief. | REQ-RISK-02, REQ-EXEC-09 | code-architect (contract), tdd-guide (build), python-reviewer | L |
| 1.8 | MDW live ingestion proof; multi-cycle run proving health-ledger/snapshot convergence. | REQ-OPS-08, REQ-OPS-06 | tdd-guide | S |
| 1.9 | Correct PROGRESS.md `has_msgbus_backing`; record this plan and the Phase 0 determinations. | REQ-DATA-06, REQ-OPS-12 | doc-updater | S |
| 1.10 | Independent review of 1.3–1.8. | — | python-reviewer | S |

**Exit criteria:**
- >=14 consecutive days of quote tape on disk, read back by a SEPARATE process
  (the Phase-1-ingestion evidence convention), with row counts per market-day.
- >=14 settled markets in the 1.2 ledger with both venue and Breezy values.
- A written, reviewed callback-threading contract from 1.7, plus a test that
  fails on an off-loop `require_open` call.
- `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` all clean.
- A **live run** of the METAR path against `api.weather.gov` producing a
  running-max series for at least one site, cross-checked by hand against raw
  METAR text (`docs/evidence/` artifact, per the existing convention).

### Phase 1.5 — Premise Falsification (HARD GATE on Phase 2 entry)

**This phase exists to convert a large sunk cost into one cheap script.** It runs
off the accruing quote tape and METAR data alone. **No adapter code, no strategy
code, no production package** — a throwaway analysis script under
`scripts/analysis/` (deliberately outside `src/breezy/`, deliberately not in
mypy `files`, deliberately not a deliverable).

**Entry:** Phase 1 exit — specifically >=14 days of joined quote tape and
running-max series covering the same market-days.

**The question:** joining recorded quotes to running-max strike-crossing times,
**is there a persistent, fee-surviving gap between the moment the outcome becomes
physically determined and the moment the market prices it?**

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 1.5.1 | Join the quote tape to the running-max series. For every (market, climate-day) where the running max crossed the strike before market close, compute the crossing timestamp `t_cross` and the venue's best ask (for the YES side) as a function of time after `t_cross`. | REQ-ALPHA-08 | tdd-guide | M |
| 1.5.2 | Measure the gap: `1.00 - ask(t)` for `t` in a series of horizons after `t_cross`. Report the distribution, not a point estimate — median, quartiles, and the fraction of crossings where any gap existed at all. | REQ-ALPHA-08 | prediction-market-reviewer | M |
| 1.5.3 | Net the measured gap of the **0.06 taker fee** on the fee curve `Theta * C * p * (1-p)` at `p` near 1, plus realistic slippage at the intended size. State the residual explicitly. | REQ-ALPHA-08, REQ-VENUE-11 | prediction-market-reviewer | M |
| 1.5.4 | Persistence check: is the gap present across cities and across days, or concentrated in a handful of market-days? A gap that exists only on 2 of 14 days is not a strategy. | REQ-ALPHA-08 | prediction-market-reviewer | S |
| 1.5.5 | Written GO / NO-GO determination with the measured numbers, reviewed adversarially. | REQ-ALPHA-08 | prediction-market-reviewer + trading-bot-architect | S |

**Exit criteria — one of two outcomes, stated as a measured number either way:**

- **GO:** a stated median gap magnitude, **net of the 0.06 taker fee and
  slippage at intended size**, that is positive and persistent across a majority
  of traded cities and market-days. The number and its dispersion are recorded in
  `docs/evidence/`. Phases 2 and 3 start.
- **NO-GO:** the gap is absent, negative after fees, or concentrated in too few
  market-days to be a strategy. **The programme stops here.** No adapter, no
  settlement package, no execution client is built. The correct response is to
  re-open the alpha question, not to proceed and hope.

**Phases 2 and 3 do not start until this passes.** This gate is the single
highest-leverage item in the plan: it costs one script and it is the only thing
standing between us and building an entire venue integration on an unfalsified
premise.

### Phase 2 — `polymarket_us` adapter (read path)

**Entry:** Phase 1.5 **GO**; Phase 0 exit; G15 branch chosen; slug grammar
determined OR an explicit fallback (operator-supplied slug list) adopted; the
Phase 1.7 callback-threading contract in hand.

Package layout (new):

```
src/breezy/venue/
  __init__.py
  polymarket_us/
    __init__.py
    config.py          # required-no-default config; raises when unset
    credentials.py     # Ed25519 key load; no __repr__, no dict export
    signing.py         # canonical string + signature (branch on G3)
    rest.py            # httpx client, rate-limit + backoff, idempotency
    ws.py              # websocket client (branch on G6)
    slugs.py           # slug <-> InstrumentId, round-trip tested
    instruments.py     # BinaryOption provider, venue-sourced precision
    data.py            # LiveMarketDataClient subclass
    fees.py            # FeeModel subclass: Theta*C*p*(1-p), 0.06 / -0.0125
    factories.py       # LiveDataClientFactory / LiveExecClientFactory
```

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 2.1 | `config.py` + `credentials.py`. Every parameter required, no defaults; construction raises naming the offending setting (`SettingsError` convention). Credential type has no `__repr__`, no serialization, and a test asserts it is unreachable from every health/alert/snapshot type. | REQ-VENUE-13/14, REQ-OPS-04 | tdd-guide, then security-reviewer | M |
| 2.2 | `signing.py`. Canonical string per the G3 determination; ±30s window; injectable clock. | REQ-VENUE-02/03 | tdd-guide | M |
| 2.3 | `rest.py`. Backoff that NEVER blind-retries a POST; idempotency key per REQ-VENUE-08. | REQ-VENUE-04/08/15 | tdd-guide | M |
| 2.4 | `slugs.py` + `instruments.py`. Round-trip property tests (hypothesis). Precision pre-validation before any `Price`/`Quantity` construction. | REQ-VENUE-05/06/17, REQ-EXEC-03 | tdd-guide | M |
| 2.5 | `fees.py`. Contract test pinning taker `0.06` / maker `-0.0125` and a test that FAILS if the `.com` `0.05`/`0` values ever appear. | REQ-VENUE-11 | tdd-guide + prediction-market-reviewer | M |
| 2.6 | `data.py` + `ws.py`, **designed against the Phase 1.7 callback-threading contract**. **Branch on G6:** if sequence numbers exist -> gap detection + resubscribe; if not -> a staleness watchdog plus REST reconciliation of book state, and the strategy refuses to trade on data older than a configured bound. | REQ-VENUE-10, REQ-EXEC-02/09 | tdd-guide | L |
| 2.7 | `factories.py` and wiring into a `TradingNodeConfig` alongside the existing ingest actors. | REQ-VENUE-01 | tdd-guide | M |
| 2.8 | Independent review: architecture + security + domain. | — | code-architect, security-reviewer, python-reviewer (parallel) | M |

**Exit criteria:**
- **A live read-only run**: real process, real credentials, subscribing to real
  markets, receiving real quotes into the Nautilus DataEngine, zero POSTs.
  Evidence file with instrument ids, quote counts, and a timestamped log excerpt.
- Read-path behaviour asserted (not structure): the node's registered clients and
  received-message counts, mirroring the Phase 1 lesson.
- A test proving every adapter callback that can reach `require_open` does so on
  the event-loop thread, per the 1.7 contract.
- All three gates clean; `venue` in mypy `files`.

### Phase 3 — Settlement package, kill-gate wiring, reconciliation

**Entry:** Phase 1.5 **GO**; Phase 1 exit (1.2 ledger running; 1.7 contract
landed). Independent of Phase 2 — run in parallel with it.

```
src/breezy/settlement/
  __init__.py
  resolver.py      # (site, climate_day, strike) -> outcome | UNRESOLVED
  deadlines.py     # SettlementDeadline -> as_of_ts_init bound
  reconcile.py     # venue settlement vs Breezy FINAL; disagreement classifier
  disagreement.py  # halt latch, dispute basis retention, calibration exclusion
  observability.py # BOUNDARY_UNRESOLVED counter, snapshot field, alert rule
```

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 3.1 | `deadlines.py`: derive the `as_of_ts_init` bound from `registry/sites.py` `SettlementDeadline` (08:00 ET clock AND the 11:00 ET METAR-review delay). Test that FAILS if any literal `08:00` appears in trading-horizon math. | REQ-EXEC-08 | tdd-guide | S |
| 3.2 | `resolver.py` on `read_climate_day_as_of_settlement`. **Branch on G5 (REQ-SETTLE-03):** if the operator is determined, encode it with the determination cited; if UNRESOLVED, the resolver returns `UNRESOLVED` for any observation within one tick of the strike, and the strategy refuses those markets. The resolver stays frozen either way — no guess. | REQ-SETTLE-01/02/03 | tdd-guide + prediction-market-reviewer | L |
| 3.3 | **`observability.py` — make `UNRESOLVED` loud.** Counter of markets refused for `BOUNDARY_UNRESOLVED`; the count is a field in the trading health snapshot; a WARNING alert fires when the refused fraction exceeds a configured share of addressable markets (required-no-default). A test asserts the alert fires at the threshold and that the counter is non-zero-reachable. **If the observed fraction is high in Phase 4's shadow run, the plan's ruling is explicit: G5 is no longer a deferred unknown, it is a first-trade blocker, and Phase 5 does not proceed until it is determined.** | REQ-SETTLE-03a, REQ-OPS-03 | tdd-guide + prediction-market-reviewer | M |
| 3.4 | Fractional settlement price support end to end. | REQ-SETTLE-07 | tdd-guide | M |
| 3.5 | `reconcile.py` + `disagreement.py`: latch a per-city halt, book at the VENUE number, retain Breezy's as dispute basis, exclude from calibration. Replay the captured Miami preliminary->final 5 F revision as the test scenario. | REQ-SETTLE-06/09 | tdd-guide | L |
| 3.6 | Wire `gate.require_open(venue, city)` as the trading kill-gate, **consuming the Phase 1.7 threading resolution** (the constraint itself is no longer discovered here). | REQ-RISK-01 | tdd-guide + python-reviewer | M |
| 3.7 | Halt-latch storage: assert no latch is reachable from the Nautilus `Cache`; a test calls `Cache.reset()` and asserts the halt survives. | REQ-RISK-03 | tdd-guide | M |
| 3.8 | **Branch on G9 (REQ-SETTLE-04):** if 1.2 shows the venue settles off the FINAL -> the existing `is_final` gate is correct and nothing changes. If it settles off the PRELIMINARY -> the resolver must be able to answer from the preliminary, `is_final` becomes a confidence attribute rather than a precondition, and a preliminary->final revision after settlement becomes a REQ-SETTLE-06 disagreement rather than a correction. Design both; implement the one the ledger shows. | REQ-SETTLE-04 | trading-bot-architect (design), tdd-guide (build) | L |
| 3.9 | Independent review. | — | prediction-market-reviewer + python-reviewer | M |

**Exit criteria:**
- Resolver output reconciles 100% against every settled market in the 1.2 ledger
  for which G9 has been determined, or the disagreements are classified.
- A live run in which `require_open` returns BLOCKED for a site whose gate is
  blocked, observed from the trading process (not a unit mock).
- The `BOUNDARY_UNRESOLVED` counter is present in a real health snapshot and the
  threshold alert is demonstrated firing.
- All three gates clean; `settlement` already in mypy `files`.

### Phase 4 — Execution client, Tier-1 strategy, replay harness

**Entry:** Phase 2 and Phase 3 exits.

```
src/breezy/strategy/
  __init__.py
  deterministic_max.py   # Tier 1
  safety.py              # pre-trade refusals (REQ-RISK-07)
  sizing.py              # cluster caps + fractional Kelly
src/breezy/venue/polymarket_us/execution.py   # LiveExecutionClient
```

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 4.1 | `execution.py`: submit/cancel/status/fills/positions/account. **Every POST path is code-complete but unreachable without the Phase 5 enablement flag.** | REQ-EXEC-01/07 | tdd-guide | L |
| 4.2 | Startup reconciliation assertion: node refuses to start trading unless `generate_mass_status` demonstrably succeeded. Test injects a venue outage and asserts refusal, not a flat-and-happy node. | REQ-EXEC-04 | tdd-guide | M |
| 4.3 | `safety.py`: refusals per REQ-RISK-07 including the `cache.position(...)` pre-SELL check and the clock-skew check. Every refusal counted and alerted. | REQ-EXEC-05, REQ-RISK-07, REQ-OPS-07 | tdd-guide + security-reviewer | L |
| 4.4 | `sizing.py`: cluster identification (adjacent strikes on one city-day = ONE bet), conservative cluster caps, then fractional Kelly bounded by them. Caps required-no-default. | REQ-RISK-04/05/06 | tdd-guide + prediction-market-reviewer | L |
| 4.5 | `deterministic_max.py`: P=1 only when the observed running max clears the strike under the REQ-SETTLE-03 operator. **Refuses the P~0 side entirely.** Fee+slippage-inclusive edge at intended size, re-checked AFTER tick rounding, strict `>`. | REQ-ALPHA-01/02/03 | tdd-guide + prediction-market-reviewer | L |
| 4.6 | Real-money enablement flag: no default, no inference, plus the kill switch. Test asserts that with the flag unset every POST path raises before any network call. | REQ-RISK-08/09 | tdd-guide + security-reviewer | M |
| 4.7 | Replay/backtest harness over the recorded quote tape + weather records. Inject `InstrumentClose(close_type=CONTRACT_EXPIRED)` AND populate `settlement_prices`; a test asserts zero open positions at end-of-run. Respect the one-shot, memory-capped replay bound. | REQ-SETTLE-08, REQ-DATA-10 | tdd-guide | L |
| 4.8 | Market-implied baseline computation from the tape, productionized from the Phase 1.5 throwaway script (the script is not promoted — the logic is re-implemented under test). | REQ-ALPHA-07 | tdd-guide | M |
| 4.9 | Trading alerts on the `health.py` substrate, including cold-start-fires and the `BOUNDARY_UNRESOLVED` fraction. | REQ-OPS-03, REQ-SETTLE-03a | tdd-guide | M |
| 4.10 | Trading runbook. | REQ-OPS-05 | doc-updater | M |
| 4.11 | Independent review: architecture, security, domain math. | — | code-architect, security-reviewer, prediction-market-reviewer, python-reviewer (parallel) | M |

**Exit criteria:**
- **A live shadow run**: real process, real quotes, real weather, strategy emits
  full order INTENTS with computed price/size/edge to the log and the tape, and
  submits nothing (flag unset). Evidence file covering >=14 days.
- Backtest over the recorded tape shows zero positions open at end-of-run.
- **The `BOUNDARY_UNRESOLVED` refused fraction from the shadow run is recorded.
  If it exceeds the configured threshold, Phase 5 does not start until G5 is
  determined** — per REQ-SETTLE-03a, this is a first-trade blocker, not a
  deferred unknown.
- `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` clean; all new packages
  in mypy `files`.

### Phase 5 — Venue probe, Tier-1 gate, first trade

**Entry:** Phase 4 exit, including the `BOUNDARY_UNRESOLVED` check. Requires
operator decisions D1–D5 (§5).

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 5.1 | **Single-order venue probe** at the venue minimum, under the operator's per-dispatch USD ceiling. Submit -> observe -> cancel or let settle. Confirms the Phase 0.6 read-only G7 inference (or resolves it if 0.6 was ambiguous), and resolves G3 residual, G8 and the real `orderPriceMinTickSize` in one shot. Log everything; capture verbatim request/response with the signature redacted. | REQ-VENUE-03/07/08, REQ-EXEC-07 | tdd-guide, reviewed by security-reviewer before dispatch | M |
| 5.2 | Score the shadow run against the **Tier 1 gate** (§4). | — | prediction-market-reviewer | M |
| 5.3 | First real trades at the operator's capital ceiling; daily settlement reconciliation. | REQ-SETTLE-09 | tdd-guide | M |
| 5.4 | Remaining BLOCKS-SCALE items: REQ-OPS-09, REQ-OPS-11, REQ-SETTLE-05 (G10). | | tdd-guide | M |

**Exit criteria:** Tier 1 gate PASSED with the checklist in §4 evidenced item by
item; >=20 real settled trades reconciled 100%; zero safety-gate violations.

### Phase 6 — Tier 2 model path

**Entry:** Phase 5 exit + sustained Tier-1 operation.

| # | Work item | REQ | Owner | Effort |
|---|---|---|---|---|
| 6.1 | NWS gridpoint forecast ingestion (second ingestion family). | REQ-DATA-08 | tdd-guide | L |
| 6.2 | **Backfill feasibility spike FIRST**, then historical backfill: forecasts + observations + settled outcomes to >=2,000 pairs. | REQ-DATA-09 | tdd-guide | L |
| 6.3 | Conditional max-temperature distribution model. | REQ-ALPHA-04 | trading-bot-architect (design), tdd-guide (build) | L |
| 6.4 | Walk-forward calibration enforced by a time-bounded data view built on `read_climate_day_as_of_settlement`. A test must FAIL if the fitting path can see data past its bound. | REQ-ALPHA-05 | tdd-guide + prediction-market-reviewer | L |
| 6.5 | Enable the P~0 upper-tail side, from the model only. | REQ-ALPHA-06 | tdd-guide | M |
| 6.6 | Score against the **Tier 2 gate** (§4). | — | prediction-market-reviewer | M |

---

## 4. The two-tier enablement gate

Both tiers require, without exception:

- [ ] **Zero safety-gate violations** across the whole evaluation window. A
      violation is any order that reached the venue while `require_open` was not
      OPEN, or that bypassed any REQ-RISK-07 refusal.
- [ ] **100% settlement reconciliation.** Every settled market matched against the
      resolver, every disagreement classified under REQ-SETTLE-06.
- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` clean at the
      evaluated commit.
- [ ] A live run — not a test suite — as evidence for every runtime-path claim.
- [ ] The `BOUNDARY_UNRESOLVED` refused fraction is below its configured
      threshold, or G5 has been determined and the resolver encodes it.

### Tier 1 — deterministic intraday path (execution-grade bar only)

Calibration statistics are meaningless for a quantity that is not being
estimated (findings A4), so no calibration criterion applies here.

- [ ] >=200 settlements observed in the evaluation window.
- [ ] >=30 settlements per traded city.
- [ ] Positive PnL at **1.5x stressed fees** (taker 0.09 rather than 0.06).
- [ ] **Beats the market-implied probability baseline**, computed from the
      REQ-DATA-04 tape — not merely climatology. This is the hard test.
- [ ] The Phase 1.5 measured gap is still present in the evaluation window —
      i.e. the premise did not decay between falsification and enablement.
- [ ] Every trade is a P~1 trade justified by an observed running max clearing the
      strike; **zero P~0 trades taken.**
- [ ] Edge recomputed after tick rounding on 100% of submitted orders, with the
      post-rounding value logged for audit.
- [ ] Zero orders submitted while REQ-SETTLE-03 returned UNRESOLVED for the strike.
- [ ] Startup reconciliation assertion (REQ-EXEC-04) fired successfully on every
      process start in the window; zero starts proceeded on a swallowed failure.
- [ ] Zero duplicate positions from retry (REQ-VENUE-08 proven in the live log).

### Tier 2 — model-priced path (execution-grade bar PLUS model-grade bar)

Everything in Tier 1, plus:

- [ ] BSS **CI-lower-bound > 0.05** versus ACIS climatology.
- [ ] **No reliability bin overconfident by > 0.05.**
- [ ] **>=400 settled pairs per traded stratum** and **>=2,000 overall.**
- [ ] Calibration fitted **walk-forward only**, enforced by the time-bounded data
      view — with a test proving the fitting path cannot see past its bound.
- [ ] The model-grade bar is met **per stratum**, not merely in aggregate.
- [ ] P~0 trades sourced exclusively from the model's upper tail; a test proves
      the "not yet observed" path cannot reach a P~0 decision.

---

## 5. Operator decision points

Per CLAUDE.md Pre-Auth, operator input is reserved strictly for maximum budgets
and operator-only enablement ceilings. These five are the complete list.
Everything else in this plan is our call.

| ID | Decision | Needed by | Why it is operator-only |
|---|---|---|---|
| **D1** | Complete KYC on Polymarket.us. | Phase 5 entry | Identity; cannot be delegated. |
| **D2** | Fund the account, and state the funded amount. | Phase 5 entry | Budget. |
| **D3** | **Per-dispatch venue-probe exception with a USD ceiling.** There is NO retail sandbox — every POST is real money. Grant a named, bounded exception for probe 5.1 (suggested: one order at the venue minimum, ceiling stated in USD, single dispatch, not standing). | Phase 5.1 | Real-money ceiling. |
| **D4** | **Live-trading enablement plus a capital ceiling.** The enablement flag has no default and no inferring code path; no agent and no checked-in config may set it. | Phase 5.3 | Operator-only enablement ceiling. |
| **D5** | **Risk-cap numbers that are budget ceilings**: max exposure per cluster, per city-day, and total open exposure, all in USD. These have no defaults; config construction raises when unset. | Phase 4.4 (as values), Phase 5.3 (binding) | Budget. |

Not operator decisions (stated so they are not manufactured into checkpoints):
adapter design, package layout, model choice, sizing formula, phase ordering,
which branch to take on any probe outcome, when a phase exits, whether to
refactor, the Phase 1.5 GO/NO-GO ruling, and every commit/merge in this plan.

**The one conditional escalation:** REQ-VENUE-12 / G11. The ToS and rulebook are
a Phase 0.4 evidence-capture work item, not an approval checkpoint. It becomes an
operator matter ONLY if the captured text actually prohibits or conditions
automated order flow — in which case the captured text is escalated verbatim and
the programme halts pending that ruling. Absent such text, no escalation occurs.

---

## 6. Risk register

Ordered by "could make this whole effort worthless", each with the cheapest
available early falsification.

| # | Risk | Cheapest falsification | When |
|---|---|---|---|
| R1 | **The venue settles off the PRELIMINARY CLI.** Breezy's `is_final` gate makes it structurally unable to predict such a settlement — the entire settlement-truth stack would be answering the wrong question. | Phase 1.2 observation ledger: record venue settlement value+time against Breezy's PRELIMINARY and FINAL for every settled market. Costs one recorder and calendar time. Start day one. | Phase 1 |
| R2 | **The market is not mispriced late in the day.** If the venue's book already prices P=1 the instant the running max clears the strike, the deterministic premise is dead and Tier 1 has no edge. This kills the premise, not just the implementation. | **Phase 1.5 is this test, and it is a hard gate on Phase 2 entry.** One throwaway script over the accruing tape + METAR. No adapter, no strategy code, no capital. A NO-GO stops the programme before the expensive phases begin. | **Phase 1.5 — gates Phase 2** |
| R3 | **`gateway.polymarket.us` is unreachable from a server process** (documented 403 to non-browser fetches). Invalidates a whole architecture branch. | Phase 0.2: one unauthenticated GET from a headless host. Minutes. | Phase 0 |
| R4 | **The Ed25519 canonical string includes the body.** 100% of order submissions fail auth. | Phase 0.1 SDK source read; residual resolved by the 5.1 single-order probe with an injectable signer. | Phase 0 / 5 |
| R5 | **Automated trading violates venue ToS, or self-trade prevention/position limits bite.** Wash trading on a CFTC DCM is statutory, not a fee footnote. | Phase 0.4: read and digest-capture the rulebook before any code. Escalates to the operator only if the captured text actually prohibits automated order flow. | Phase 0 |
| R6 | **Bucket boundary operator is guessed wrong** — systematically wrong settlement at exactly the strike, which is where all the volume is. | Phase 0.5; and structurally: the resolver returns UNRESOLVED within one tick of the strike if undetermined, so a wrong guess cannot be made. | Phase 0 / 3 |
| R6a | **`UNRESOLVED` silently eats the entire addressable market.** The safe degradation in R6 could refuse exactly the markets where all the edge lives, while every gate still reads green. | Phase 3.3: the refused-fraction counter, snapshot field and threshold alert. Phase 4's shadow run reports the real fraction; a high fraction promotes G5 from deferred unknown to first-trade blocker. | Phase 3 / 4 |
| R7 | **Wrong side of market** from the `intent`x`outcomeSide`x`action` matrix. Losses are immediate and directional. | Phase 0.6 read-only inference from public order/trade data plus the SDK's own order-construction code — the primary path. Phase 5.1's single-order probe at the venue minimum is the confirming fallback, not the first resort. | Phase 0 -> 5 |
| R8 | **Retry creates double positions** inside the 30s window. | Phase 0.1 SDK read for an idempotency key; Phase 5.1 observation. | Phase 0 / 5 |
| R9 | **The gate is called off the event-loop thread** and raises exactly when the halt matters (`SqliteStateStore` is thread-confined). Also a cross-cutting constraint on adapter callback design. | **Phase 1.7** — moved earlier so it is an input to Phase 2, not a Phase 3 discovery: a test that FAILS on an off-loop call, a published threading contract, and a live run observing a real BLOCKED refusal. | **Phase 1** |
| R10 | **Green tests, dead deployment** — the repo's standing lesson, twice realised. | Every phase exit requires a live artifact, never a test count. | Every phase |
| R11 | **Slug grammar is not stable** or is undocumented in a way that breaks silently when the venue renames markets. | Phase 0.3 multi-day harvest + Phase 1.1 continuous tape: a slug that stops resolving shows up as a tape gap, loudly. | Phase 0/1 |
| R12 | **Backfill is impossible or insufficient** for Tier 2, making the model path ~13 months away at live rates. | Phase 6.2 is scoped as a feasibility spike FIRST. Tier 1 does not depend on it — which is precisely why Tier 1 is first. | Phase 6 |
| R13 | **A credential leaks through the alerting substrate.** `health.py`'s redaction guarantee is structural today; a credential-carrying config is the first thing that could punch through it. | Phase 2.1: a test asserting no venue credential is reachable from any snapshot/alert type, written RED before `credentials.py` exists. | Phase 2 |
| R14 | **The premise decays between falsification and enablement** — the Phase 1.5 gap closes as other participants find it. | The Tier 1 gate re-checks the measured gap in the evaluation window; the continuously-running tape makes decay observable rather than inferred. | Phase 5 |

---

## 7. What we are deliberately NOT building

| Not building | Reason |
|---|---|
| **PostgreSQL / TimescaleDB / Redis / DuckDB / vector store / feature store** | Phase 1 shipped without them and the null hypothesis holds: native `ParquetDataCatalog` for the data plane, SQLite `StateStore` for the control plane. Nothing in this plan generates a workload they solve. `message_bus=None` and `cache.database=None` remain correct — `kernel.py:311-329` accepts only `'redis'`, and Breezy's durable state deliberately does not live in the Nautilus `Cache` (REQ-RISK-03). |
| **A fork, patch or vendoring of the shipped `adapters/polymarket/`** | Findings A1: incompatible at auth, custody and identifier layers simultaneously, and it hard-imports `py_clob_client_v2`, which is not installed. We read it as a reference for report-generation and websocket-client structure; we never copy it into `src/`. |
| **A settlement resolver ahead of the boundary-operator answer (G5)** | The repo has ALREADY correctly frozen the resolver on this. Guessing is the exact failure mode the freeze exists to prevent. Phase 3.2 encodes a determination or returns UNRESOLVED — it never guesses. Phase 3.3 makes that refusal loud so the freeze cannot silently hide an unaddressable market. |
| **A production feature/analysis package for Phase 1.5** | The premise-falsification script is deliberately throwaway: `scripts/analysis/`, outside `src/breezy/`, outside mypy `files`, not a deliverable. Promoting it would be building infrastructure for a question that might return NO-GO. Phase 4.8 re-implements the surviving logic under test. |
| **An adapter, settlement package or execution client before Phase 1.5 passes** | The whole point of the gate. A NO-GO means none of it should exist. |
| **A Kalshi adapter** | No adapter exists in 1.231.0; later phase. |
| **A generic multi-venue abstraction layer** | Speculative generality with one venue. Portability comes from keeping venue specifics inside `venue/polymarket_us/` and the rest of the code venue-agnostic — not from an abstract base class written before a second implementation exists. |
| **An estimated correlation matrix for cluster sizing** | Findings G: crude conservative cluster caps beat a correlation matrix estimated on weeks of data. Revisit only with years. |
| **A Nautilus `ProbabilityPriceFeeModel`-based fee path** | The doc-prescribed import raises `ImportError` in this build, and the native model is taker-only and cannot express a maker rebate (findings A3). We subclass `FeeModel` instead. |
| **Streaming catalog replay** | It RAISES for our record types (findings D4, contract-tested). The replay harness is one-shot and memory-capped by design. |
| **A P~0 path in Tier 1** | The observed running max is a LOWER bound only. "We haven't seen it yet" is not evidence of absence. Tier 1 refuses that side entirely; Tier 2 sources it from the model's upper tail. |
| **`ruff format` as a gate, or `lint-imports` contracts** | Pre-existing cosmetic drift and an unconfigured dependency (PROGRESS.md, LOW). Not on the path to a trade; not in scope here. |

---

## Appendix — new packages and their mypy registration

Every package below must be appended to `[tool.mypy].files` in `pyproject.toml`
in the same change that creates it, or it silently escapes strict typing.

```toml
files = [
    "src/breezy/normalize",
    "src/breezy/registry",
    "src/breezy/settlement",   # exists, empty, already registered
    "src/breezy/domain",
    "src/breezy/ingest",
    "src/breezy/persistence",
    "src/breezy/runtime",
    "src/breezy/features",     # ADD — Phase 1.3
    "src/breezy/venue",        # ADD — Phase 2
    "src/breezy/strategy",     # ADD — Phase 4
    "src/breezy/alpha",        # ADD — Phase 6
]
```

`scripts/analysis/` (Phase 1.5) is deliberately NOT registered: it is throwaway
falsification code, not a deliverable, and must not accrete into the runtime.

New env settings, all required-with-no-default, validated at load time via
`SettingsError` per the existing `runtime/settings.py` convention:
`BREEZY_VENUE_API_BASE`, `BREEZY_VENUE_GATEWAY_BASE`, `BREEZY_VENUE_WS_URL`,
`BREEZY_VENUE_ACCESS_KEY`, `BREEZY_VENUE_PRIVATE_KEY_FILE`,
`BREEZY_BOUNDARY_UNRESOLVED_ALERT_FRACTION`,
`BREEZY_MAX_EXPOSURE_CLUSTER_USD`, `BREEZY_MAX_EXPOSURE_CITY_DAY_USD`,
`BREEZY_MAX_EXPOSURE_TOTAL_USD`, `BREEZY_TRADING_ENABLED` (operator-only, D4).
