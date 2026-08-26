# Breezy — GO LIVE Plan

**Status:** authoritative roadmap from current state to first real trade.
**Created:** 2026-08-26.
**Supersedes nothing.** This is the index over `TRADING_ENABLEMENT_PLAN.md`,
`POLYMARKET_US_BUILD_PLAN.md` and `POLYMARKET_US_READONLY_AUTH_PLAN.md`; those
remain the detailed sources. Where this file and they disagree, they win on
detail and this file wins on sequencing.

---

## 1. Where the code actually is (audited 2026-08-26)

Audited by three independent read-only sweeps (docs/backlog state, execution
path, strategy/backtest seam). Findings, with citations, not claims:

**Built and live-validated**

- NWS ingestion substrate, five sites (NYC/SFO/MIA/MDW/LAX), running under a
  systemd user unit, writing `ParquetDataCatalog` on ext4.
- Settlement-truth classification: `normalize/classify.py:77`,
  `domain/selection.py:140`, as-of-settlement reads at
  `persistence/catalog.py:552`.
- Polymarket.us **read-path** market-data adapter:
  `PolymarketUSDataClient(LiveMarketDataClient)` at `adapters/polymarket_us/data.py:375`,
  registered by `PolymarketUSLiveDataClientFactory` at `factories.py:222`.
- Ed25519 request signing: `signing.py:185`, canonical `timestamp+METHOD+path`,
  30s skew bound.
- Venue quote-tape recorder (work item 1.1) — built, three-axis reviewed,
  **uncommitted, and never run against the live venue.**

**Not built at all**

- No `Strategy` subclass anywhere in `src/` or `tests/`.
- No `BacktestNode` / `BacktestEngine` harness. Both node configs register
  `catalogs=[]` (`runtime/node_config.py:195-206`, `:436-457`).
- No forecast model. `src/breezy/features/__init__.py` and
  `src/breezy/settlement/__init__.py` are **0 bytes**.
- No position sizing, no bankroll math, no risk gate.
- No `LiveExecutionClient`, no exec factory, no `submit_order`/`cancel_order`,
  no account/balance reporting, no fill parsing, no reconciliation report
  methods.
- Fee model unimplemented: `maker_fee`/`taker_fee` are `Decimal(0)` and
  `assert_fee_schedule_known` (`parsing.py:223`) raises rather than assume.

**Deliberate barriers that will block trading until explicitly removed**

| ID | Barrier | Location |
|----|---------|----------|
| B1 | HTTP dispatch `PERMITTED_METHODS` GET-only | `http.py:64`, raised `:178-181` |
| B2 | Signer refuses non-GET | `signing.py:84`, `:260-263` |
| B3 | Transport wraps pyo3 client in a GET-only closure | `transport.py:105-124` |
| B4 | Quota-key allowlist has no order bucket | `transport.py:81-83` |
| B6 | `assert_live_order_submission_permitted` + `LiveTradingPermit` | `safety.py:16,32-53` — **zero production callers today** |
| B7 | Static barrier suite fails CI on any POST/order literal | `tests/unit/test_polymarket_us_readonly_guard.py:1-80` |

These are features, not debt. Removing them is a Phase 4 activity with its own
review, never an incidental side effect of adding an execution client.

---

## 2. The two existential risks

Neither is an engineering problem. Both can end the programme, and both are
cheap to resolve **before** any further build.

### R1 — The settlement premise has already failed its pre-registered gate

The 2 °F bucket-alignment gate FAILED all five cities. The post-hoc guard-band
sweep did not rescue it: agreement DEGRADES as the guard tightens
(0.764 → 0.688) while retention collapses to 12.97%.

The residual is **not** boundary noise — it is one-directional bias. Misses run
68.5% → 99.3% "METAR below CLI" as the guard tightens; NYC is ~99.6%
one-directional at every band. KNYC (Central Park) reports ~29 observations/day
against ~306 at the airport ASOS sites, so sparse sampling systematically
misses the true daily maximum.

Systematic bias is correctable. Boundary noise is not. That distinction is the
whole question, and it is currently **untested**: the failed gate is SYMMETRIC
while the Tier-1 rule is ASYMMETRIC — it only buys once the observed running
max has already cleared the strike, and refuses the P≈0 side. A negative bias
is the *conservative* direction for that rule.

**This must be pre-registered and adversarially reviewed before it is tested.**
Adopting the asymmetric form as a post-hoc rescue for a failed symmetric gate
is exactly the methodological error the pre-registration discipline exists to
prevent. See backlog G-03.

### R2 — The price tape is the only irreversible item on the critical path

Weather history is retroactively available (the alignment study drew ~1,800
city-days per site from the IEM archive). Polymarket.us weather-market price
history is not, and never will be: those markets did not exist before 2026, so
no vendor can backfill them. **Every uncaptured day is permanently lost.**

Strategy, sizing, execution client, backtest harness and settlement package can
all be built later from a standing start. The tape cannot. This is why the
recorder — not a strategy and not a backtest — is the next action, and why the
14-day accumulation window should start on the earliest possible calendar day.

---

## 3. Why "write a strategy" and "run a backtest" are the wrong next actions

Both were considered and rejected on evidence:

- A backtest needs the weather series AND the market price series aligned in
  time. The market series does not exist. A backtest today would be a backtest
  of nothing.
- A strategy built now would encode an edge premise that has failed its only
  pre-registered test (R1). It would be built on an unvalidated foundation with
  no data available to test it against.

The correct sequence is: capture the irreversible thing, resolve the premise
for free, then build.

---

## 4. Phase sequence to first trade

Each phase names its own exit gate. No phase starts before its predecessor's
gate is green.

### Phase A — Unblock and start the tape *(critical path, calendar-bound)*

The recorder is built but has made **zero authenticated calls**. Every venue
host in every test is `.invalid`; 2412 green tests do not establish that a real
frame reaches parquet. `MARKET_SLUG_KEY = "marketSlug"` remains an unresolved
venue guess on which every routing decision rests — if it is wrong the recorder
captures nothing and looks exactly like a quiet market.

- Resolve `MARKET_SLUG_KEY` against a live authenticated response.
- Run the single gating live run; prove a real frame lands in parquet.
- Start continuous capture under systemd with disk alerting.

**Gate:** a real frame, from the real venue, read back from parquet by a
separate process.
**Requires the operator:** the three-lock credential gate
(`BREEZY_VENUE_LIVE=1` AND `BREEZY_ALLOW_CREDENTIALED_PYTEST=1` AND
`--venue-live`) exists so no automation trips it incidentally. Unlocking it is
an operator decision (D1/D2).

### Phase B — Free falsification *(parallel, no venue, no credentials, no wait)*

Per the review ruling, any of these can return a NO-GO for free, before a line
of adapter code.

- Preliminary→final revision-rate study (DOM-11) — prices the
  post-preliminary-CLI window, which plausibly dominates Tier 1. Runs on
  catalog data already on disk.
- ROI feasibility arithmetic (DOM-13) — central estimate from the worked
  example is tens of dollars per day gross, against 63 blocking requirements.
  ~30 minutes.
- Asymmetric-gate pre-registration + adversarial domain review (R1).

**Gate:** a written GO/NO-GO on each. A NO-GO on ROI or on the asymmetric gate
stops the programme, and that is a *success* of this phase, not a failure.

### Phase C — Land the amendment set *(parallel, document + cheap code)*

`TRADING_ENABLEMENT_PLAN.md` is **BLOCKED PENDING AMENDMENT** — all four
adversarial reviewers returned BLOCK. Thirty-eight findings (SEC-1..8,
ARC-1..8, DOM-1..13, STK-1..12) must be resolved into the plan before Phase 2
entry.

One of them is a live safety defect, not paperwork: **STK-1** — the autouse
socket blocker patches Python's `socket` only, and a `nautilus_pyo3` client
reached the OS and returned ECONNREFUSED while Python's socket read as blocked.
`respx` is equally void against it. With no venue sandbox, an ordinary
`uv run pytest -q` could transmit a signed order while every gate reads green.
This is fixed first and independently of the document work.

**Gate:** review ruling lifted from BLOCK; STK-1 closed with a RED→GREEN proof.

### Phase D — Premise falsification *(HARD GATE on everything downstream)*

Needs ≥14 days of joined weather + market tape, so it cannot start before
Phase A has been running for 14 calendar days.

Restructured per DOM-1 into (a) a settlement-alignment study producing a Wilson
lower bound on the METAR→CLI hit rate per city and per degree-of-clearance
stratum, as the GO/NO-GO, and (b) a capturability study on depth-weighted fill
price and printed trades. GO requires **both**.

**Gate:** written GO/NO-GO determination. NO-GO stops the programme.

### Phase E — Forecast model and alpha *(NOT YET IN BACKLOG)*

Deliberately excluded from the current backlog. Populating `features/` and
`settlement/`, building the probability estimator and calibration. Entered only
on a Phase D GO.

### Phase F — Execution client and first trade

Fee schedule discovery (a live probe, not a coding task), then
`LiveExecutionClient`, order factory, account/balance reporting, fill parsing,
reconciliation report methods, the read-only-guard rework, sizing and risk
gates. Then the single-order venue probe, then Tier-1 enablement.

**Requires the operator:** D1 KYC, D2 funding, D3 per-dispatch probe USD
ceiling, D4 `BREEZY_TRADING_ENABLED` live-trading enablement (no default), D5
risk caps.

---

## 5. Operator-only gates (nothing downstream proceeds without these)

| ID | Decision | Blocks |
|----|----------|--------|
| D1 | KYC | Phase A live run, Phase F entry |
| D2 | Funding | Phase F |
| D3 | Per-dispatch probe USD ceiling | Venue probe |
| D4 | `BREEZY_TRADING_ENABLED` (no default) | First trade |
| D5 | Risk caps | First trade |

Per the standing constraint, real-money enablement is an operator-only ceiling.
No agent, and no automation in this repo, may set D4.

---

## 6. What is genuinely autonomous vs. what is not

Stated plainly so the backlog's "green" gate is not misread:

- **Autonomous now:** Phase B studies, Phase C amendments and code fixes, the
  loader-side gap enforcement, disk alerting, dependency pinning, import-linter
  layering, marker registration.
- **Operator-gated:** everything in Phase A that touches the live venue, all of
  Phase F.
- **Calendar-bound:** Phase D cannot be compressed. Fourteen days is fourteen
  days.

An "all green" stopping gate is therefore reachable only over the autonomous
subset. The gated items are tracked as BLOCKED with their exact unlock
condition, never as failures.

---

## 7. Backlog

Tracked in `docs/core/PROGRESS.md` under "GO LIVE backlog". Per-item execution
plans live in `docs/plans/backlog/`.
