# Breezy — Trading System Architecture

**Status:** DESIGN ARTIFACT. Authorises nothing. Builds nothing. Trades nothing.
**Written:** 2026-08-27.
**Type:** plan artifact for adversarial peer review, per the §2 planning gate.

**Subordinate to, and does not supersede:**

- `docs/plans/archive/GO_LIVE_PLAN.md` — phase sequencing A–F and operator gates D1–D5.
- `docs/plans/TRADING_ENABLEMENT_PLAN.md` (+ `_AMENDMENTS.md`) — the 85-requirement
  register. **It carries a BLOCK header and this document does not lift it.**
- `docs/evidence/asymmetric_gate_prereg_2026-08-26.md` revision 14 — **BINDING**.
  This document WIRES it. It does not re-derive, re-interpret, soften, or extend
  any of its clauses. Where this document and the pre-registration appear to
  disagree, the pre-registration wins and this document is defective.
- `docs/core/PROGRESS.md` — G-01..G-19 backlog and the standing paper-close lesson.

**What this document adds that those do not:** the *structure* of the trading
system — component boundaries, the interfaces between them, where each binding
constraint physically enters the code, and a build order. The requirement
register says WHAT must be true; this says WHERE it is enforced and in which
order it can be built.

---

---

## Revision history

**Revision 2 — 2026-08-27.** Amended in response to two independent adversarial
peer reviews (domain/architecture + security). Every numeric claim in those
reviews was independently verified by execution before amendment. Revision 1's
defects, in the order they matter:

1. **§5.4 promoted a per-CELL result to a per-CITY result.** Unreachability is a
   property of the `[0,1)` boundary stratum, not of a city. Every city's
   `[1,2)`-and-above cells CLEAR. Rewritten as a per-cell table.
2. **§5.4 routed through the wrong anchor branch.** Branch B requires a cell
   below 200 cases; every boundary cell carries ~1,820. **Branch A fires**, and
   applying the `2c-1` fiat doubling to figures that are *already* boundary-bucket
   rates double-counts. Verdict unchanged, route wrong.
3. **The archive extension is NOT "the only path avoiding rejection-by-
   arithmetic".** It moves the margin (~0.20 rather than ~0.38), not the verdict.
   Demoted from build slot 1 (§13.1).
4. **§4.4 was a caveat-then-use paper close** — the >0.5 °F figures were
   correctly flagged as not-`H(c,k)`, then used for a dollar column and summed
   into "~$8.6/day". Column and sentence DELETED. They are also **lookahead-
   contaminated**, which revision 1 never said.
5. **§4.4 used point estimates where §4.1 mandates Wilson lower bounds** — a 5.6%
   overstatement of the document's only positive number.
6. **§5.2's coverage rule was defeated by its own wording.**
   `STRUCTURALLY_UNREACHABLE` *is* a verdict, so "has not reached a verdict" never
   fired: the boundary stratum was permanently exempted while the city traded on
   wide-clearance strata. That is the exact defect the coverage rule exists to
   prevent, reintroduced by rendering.
7. **§6.2 was sold as conservative and is not** — a max-clip step function trades
   the full cap exactly where Kelly authorises ~0.
8. **§4.5's `epsilon` had an unnamed bootstrap deadlock**, and its reference size
   dissolved the circularity rather than resolving it.
9. **§8.1's central claim was false** — the proposed B2 change widened
   `PERMITTED_METHODS` in `signing.py`, the module the data client itself calls
   (`http.py:202`). The data path was not byte-for-byte unchanged.
10. **`LiveTradingPermit` is forgeable in one line** (public frozen dataclass, no
    issuer, no authenticity) and its `issued_at_ns` is never read anywhere in
    `src/`. N1 was therefore strictly weaker than the B2 it replaced.

Sections carrying a `REVISED 2026-08-27` note were rewritten. **Do not re-derive
the revision-1 text from any surviving fragment.**

**Upheld unchanged by review, verified:** the five §4.4 subtractions
(arithmetically correct to 6 dp), §6.1's Kelly derivation and every row of its
table, the maker/taker handling, the `SandboxExecutionClient` ban and its
reasoning, §9.3's lookahead guard, and §4.1's omission of an exit fee.

**One point of registered disagreement with the review — see §5.4.3.** The
per-cell numbers the review supplies are stratified by distance from the day's
**FINAL** METAR max. That is the same hindsight quantity the review's own C3
finding forbids. The table is adopted as instructed and used for feasibility
illustration; it is flagged as lookahead-contaminated and may not gate anything.

## 0. The design axiom

Two findings are ground truth and are not re-argued here:

- **R1 — the settlement premise is falsified as a general claim.** Unrestricted
  rounded-METAR↔CLI agreement is LAX 0.9530, MDW 0.9485, MIA 0.9625, SFO 0.9519
  against a Wilson-95%-lower-bound gate of > 0.9906 — four FAILED. Only NYC
  passed (0.9990), and NYC is *excluded from the primary verdict* by the
  pre-registration on sampling-density grounds. At MDW, **56.37% of nonzero days
  are METAR > CLI** (mean +0.0527 °F, tail at +7/+9/+12 °F) — the direction that
  manufactures false-positive threshold hits.
  Source: `docs/evidence/settlement_alignment_diagnosis_2026-08-25.md`.
- **R2 — ROI is NO-GO.** ~$3/day pessimistic, ~$9/day central, ~$15/day
  optimistic net per 100 contracts per city-day cluster. Theta is now pinned at
  0.06 (729/729 captured observations), which sits in the *worse* half of the
  0.00–0.09 range originally swept, so the verdict does not improve. Re-derived
  in §4.4 below with theta fixed.
  Source: `docs/evidence/roi_feasibility_2026-08-26.md`.

**Therefore the axiom, which every section below is answerable to:**

> The critical path of this system is a **measuring instrument**, not a trading
> strategy. Its job is to determine whether an edge exists and to refuse to act
> when it does not. Trading is a *conditional output* of the instrument, reached
> only when several independent measurements affirmatively pass. Nothing on the
> critical path may be correct only if the edge exists.

Two operational consequences, stated now so they can be attacked:

1. **Fail-closed is the default path, not the exception.** Every gate below
   defaults to NO-TRADE on absent data, absent calibration, absent verdict,
   expired verdict, or unparseable venue field. There is no code path where a
   missing input resolves to a permissive value.
2. **The system must be fully useful when the answer is "no edge".** If G-17
   returns NO-GO, everything in §§1–4 and §7 and §9 is still the instrument that
   produced that answer, and §§6, 8 never get built. That is a *success* state
   of this architecture, not a write-off.

### 0.1 The governing principle, restated as a design rule

> "The bot itself must be capable of autonomous discovery, the operator will
> never provide that information."

**This document introduces zero new operator-supplied facts.** Operator input is
confined to the five ceilings already declared in `GO_LIVE_PLAN.md` §5 — D1 KYC,
D2 funding, D3 per-dispatch probe USD ceiling, D4 `BREEZY_TRADING_ENABLED`,
D5 risk caps. Every one of those is money, authorisation, or a spend cap.

Everything else is discovered. A non-exhaustive audit of the facts this design
consumes and where each comes from:

| Fact | Source | Operator? |
|---|---|---|
| `theta` (fee coefficient) | per-market `info[fee_coefficient]`, parsed from the venue payload | no |
| `orderPriceMinTickSize` | per market, `parsing.py:1129` | no |
| `minimumTradeQty` | per market, `parsing.py:1130` — **VARIES: 378 slugs at 0.01, 302 at 1** | no |
| tradeable market set | `PolymarketUSInstrumentProvider` discovery (G-18) | no |
| market trading hours (DOM-9) | venue `startDate`/`endDate` per market | no |
| settlement station (ICAO) | `series.py` market-description join | no |
| `H(c,k)` settlement hit rate | G-17 study over tape + CLI | no |
| `p̂_anchor(c,k)` | IEM archive, per the pre-registration §7 | no |
| minimum-edge floor `ε` | **derived from tape** — see §4.5. Not typed by a human. | no |
| bankroll, risk caps | D2 / D5 | **yes — ceilings** |
| live-trading enablement | D4 | **yes — ceiling** |

The minimum-edge floor is the only place where the "required-no-default" wording
of REQ-ALPHA-03 could have been read as an operator input. §4.5 resolves it as a
machine-derived, versioned quantity that is *absent* until the tape can produce
it — and absence means no trading.

---

## 1. Component map

Each component carries the mandatory **null-hypothesis line**: the Nautilus
1.231.0 capability that was checked and why it does not suffice. A component
without that line is a defect.

| # | Component | Package | Status today |
|---|---|---|---|
| C1 | Running-max feature actor | `breezy/features/` | 0 bytes |
| C2 | Settlement resolver | `breezy/settlement/` | 0 bytes |
| C3 | Probability boundary (interface only) | `breezy/alpha/` | absent |
| C4 | Calibration store + no-trade gate | `breezy/alpha/calibration/` | absent |
| C5 | Edge computation (pure) | `breezy/alpha/edge.py` | absent |
| C6 | Settlement-risk gate (wires the prereg) | `breezy/risk/settlement_gate.py` | absent |
| C7 | Sizing (pure) + exposure caps | `breezy/risk/` | absent |
| C8 | Pre-trade safety gate | `breezy/risk/pretrade.py` | absent |
| C9 | Halt/kill store | reuse `runtime/sqlite_store.py` | exists |
| C10 | Strategy | `breezy/strategy/` | absent |
| C11 | Execution egress + cage rework | `breezy/adapters/polymarket_us/exec/` | absent (deliberately) |
| C12 | Backtest / replay harness | `breezy/backtest/` | absent |
| C13 | Decision journal | `breezy/persistence/decisions.py` | absent |

**C1 — Running-max feature actor.** *Null hypothesis:* checked `Actor`,
`Cache`, and the native data types. `Actor` + msgbus publication is exactly the
right vehicle and `NwsIngestActor` (`ingest/nws_actor.py:429`) already
demonstrates the pattern; `Cache` cannot hold it because `Cache.reset()` would
launder it (REQ-RISK-03 reasoning). But no native `Data` subclass carries "the
running maximum temperature observed for (site, climate-day) as of a receipt
timestamp" — `MarkPriceUpdate` / `IndexPriceUpdate` / `FundingRateUpdate` are
prices, as `tape_records.py` already established for two other record types.
**Extension:** an `Actor` subclass publishing a hand-written `Data` subclass with
exactly one `register_arrow` call, per the pattern `tape_records.py` already
proved. No new scheduler, no new bus.

**C2 — Settlement resolver.** *Null hypothesis:* checked `InstrumentClose` and
the backtest expiry path. `InstrumentClose` is the *carrier* for a settlement
outcome and is used in §9 — but `BINARY_OPTION` is absent from
`ENGINE_EXPIRING_INSTRUMENT_CLASSES` (verified: the set is
`{FUTURE, FUTURES_SPREAD, OPTION, OPTION_SPREAD}` at
`model/instruments/base.pyx:67`), so nothing native decides *what* a weather
binary settles to. That decision is a domain question about CLI products.
**Extension:** `(site, climate_day, strike) -> Outcome`, reading exclusively via
the existing `read_climate_day_as_of_settlement(..., as_of_ts_init=)`
(`persistence/catalog.py:552`), which is already the structural walk-forward
primitive REQ-ALPHA-05 demands.

**C3 — Probability boundary.** *Null hypothesis:* Nautilus has no forecasting,
distribution, or probability-estimation surface at all — it is an execution and
backtest framework. Nothing to reuse. **Extension:** an interface only (§3); the
model behind it is deliberately out of scope.

**C4 — Calibration store.** *Null hypothesis:* checked `Cache`, `PortfolioAnalyzer`
and `nautilus_trader.analysis`. `PortfolioAnalyzer` computes realised PnL
statistics from executions; it has no notion of prediction-vs-outcome pairs,
strata, or a rolling calibration error. `Cache` is volatile and resettable.
**Extension:** its own SQLite tables, single-writer, written by a scheduled batch
job — never by the trading path.

**C5 — Edge computation.** *Null hypothesis:* `FeeModel` is native and is
**reused as the sole fee authority** — `PolymarketUSFeeModel` already subclasses
it. Nautilus has no expected-value or edge surface. **Extension:** pure functions
that *call* the fee model rather than re-deriving its formula (§4.2).

**C6 — Settlement-risk gate.** *Null hypothesis:* checked `RiskEngine`. It
enforces `max_notional_per_order`, `max_order_submit_rate`,
`max_order_modify_rate`, `bypass`, `debug` — verified by field inspection of
`RiskEngineConfig`. It has no concept of a domain hypothesis, a Wilson bound, or
a per-city verdict. **Extension:** a domain gate in front of order construction.
`RiskEngine` is retained *underneath* as an independent second layer, not
replaced.

**C7 — Sizing.** *Null hypothesis:* Nautilus has no position-sizing surface;
`OrderFactory` constructs orders from a quantity you supply. **Extension:** pure
functions.

**C8 — Pre-trade gate.** *Null hypothesis:* `RiskEngine` again, plus
`assert_live_order_submission_permitted` (`safety.py:32`), which already exists
and today has **zero production callers** by design (barrier B6). **Extension:**
the domain refusal set of REQ-RISK-07 assembled in one place, terminating in the
existing chokepoint. The chokepoint is reused, not rewritten.

**C9 — Halt store.** *Null hypothesis:* `Cache` — explicitly rejected by
REQ-RISK-03 because `Cache.reset()` can launder a permanent halt.
`SqliteStateStore` (`runtime/sqlite_store.py`) already exists and already backs
the ingestion `SettlementGate`. **Reused as-is**; this design adds rows, not a
new store. Note its documented confinement: the store is confined to the
*constructing* thread (REQ-RISK-02 / STK-2), which is an input to C11's callback
design, not a later fix.

**C10 — Strategy.** *Null hypothesis:* `Strategy` is the native extension point
and provides every hook needed (verified hook list in §7). **Reused directly.**
No scheduler, no loop driver, no orchestration layer is introduced.

**C11 — Execution egress.** *Null hypothesis:* `LiveExecutionClient` is the
native extension point and supplies `generate_order_status_report(s)`,
`generate_fill_reports`, `generate_position_status_reports`,
`generate_mass_status`, `generate_account_state` and the whole order-event
generator family (verified by attribute inspection). **Reused directly.** The
extension is not a parallel client; it is the venue-specific transport beneath
it, plus the cage rework in §8.

**C12 — Backtest harness.** *Null hypothesis:* `BacktestEngine` /
`BacktestNode` are native and are used. **One native component is explicitly
REJECTED and must be banned — see §9.1**: `SandboxExecutionClient` hardcodes
`fee_model=MakerTakerFeeModel()` and `latency_model=LatencyModel(0)` with no
config seam (verified verbatim at
`adapters/sandbox/execution.py:109-124`; `SandboxExecutionClientConfig` carries
no fee or latency field). That is a hole in barrier F2 and a correctness defect
for this venue.

**C13 — Decision journal.** *Null hypothesis:* checked `CacheConfig.database`
(field verified present) — it durably persists orders, positions and account
events, and REQ-OPS-13 is satisfied by enabling it. But it stores Nautilus
domain objects, not *why* a decision was made, and it stores nothing at all for
a NO-TRADE decision. A gate that refuses silently is unauditable. **Extension:**
an append-only decision table recording every trade AND no-trade decision with
its inputs.

---

## 2. Data flow

```
NWS observations ──▶ C1 running-max Actor ──┐
NWS CLI products ──▶ C2 settlement resolver ─┤
IEM archive ───────▶ (offline) p̂_anchor ─────┤
                                             │
venue quotes/depth ▶ PolymarketUSDataClient ─┤
venue instruments ─▶ InstrumentProvider ─────┤
                                             ▼
                        ┌──────────────────────────────────┐
                        │ C10 Strategy.on_data/on_quote/   │
                        │     on_order_book_depth          │
                        └──────────────┬───────────────────┘
                                       ▼
              C3 probability ─▶ C6 settlement-risk gate ─▶ C5 edge
                                       │  (any FAIL ⇒ size 0)
                                       ▼
                              C4 calibration gate
                                       │  (uncalibrated ⇒ size 0)
                                       ▼
                                   C7 sizing
                                       │  (below min qty ⇒ size 0)
                                       ▼
                              C8 pre-trade gate ──▶ C13 journal (ALWAYS)
                                       │
                        (size > 0 AND all gates pass)
                                       ▼
                    C11 egress ─▶ assert_live_order_submission_permitted
                                       ▼
                                    venue
```

Every arrow into the decision is a *veto*. None of them is a vote. The design has
no path where a strong signal on one axis compensates for a failed gate on
another.

---

## 3. The probability boundary (C3)

The model is deliberately out of backlog scope (GO_LIVE_PLAN Phase E). What is
in scope now is the **interface**, so that everything downstream can be built,
tested and falsified against a stub.

### 3.1 What it consumes

Declared as the closed input set. An implementation that reaches for anything
else is a boundary violation, catchable by import-linter (G-07 contract already
exists).

- **Observed running max** for `(site, climate_day)` as of a receipt timestamp —
  from C1. Never the METAR *valid* time (DOM-2 / ARC-3: `t_cross` is Breezy's own
  receipt timestamp; valid time grants 5–45 minutes of information the live
  strategy will not have and produces a false GO).
- **NWS gridpoint forecast products** (REQ-DATA-08, Tier 2).
- **Climatology** from the CLI archive already on disk.
- **The quote tape** — permitted ONLY as a feature, never as the probability
  itself. Reading price as probability is the exact circularity that BLOCKed the
  pre-registration three times (the discredited `p̂ = 0.985` anchor). A test must
  assert the Tier-1 path's probability is independent of price.

### 3.2 What it must emit

```
ProbabilityEstimate:
    instrument_id      : InstrumentId
    site               : str
    climate_day        : date
    strike_f           : Decimal
    boundary_operator  : Literal[">", ">="]   # from C2/REQ-SETTLE-03; never guessed
    p_yes              : Decimal              # in [0, 1]
    p_yes_lower_95     : Decimal              # Wilson or model-native lower bound
    clearance_f        : Decimal | None       # running_max - strike; None if not fired
    observed_at_ns     : int                  # Breezy RECEIPT time
    inputs_digest      : str                  # hash of the exact inputs used
    model_version      : str
    tier               : Literal["TIER1_DETERMINISTIC", "TIER2_MODEL"]
```

Binding properties of the interface:

- **`Decimal` only.** No float crosses this boundary (STK-12 / REQ-ALPHA-03).
- **`p_yes_lower_95`, not `p_yes`, is what §4 and §6 consume.** The point
  estimate is recorded for calibration and never for sizing.
- **`p_yes = 1.0` is banned from sizing math by test** (REQ-RISK-06). For Tier 1
  the deterministic arithmetic gives `p_yes = 1`, and that is *correct as a
  statement about the model* — but the quantity that reaches sizing is not
  `p_yes`, it is the settlement-adjusted `q` of §4.1, which is strictly below 1
  by construction because `H_lb(c,k) < 1`.
- **`clearance_f` is first-class and mandatory.** It is the stratification key
  for the entire settlement-risk gate. An estimate that cannot state its
  clearance cannot be traded.
- **Emission is a refusal, not a default.** The interface returns
  `ProbabilityEstimate | Refusal(reason)`. There is no "best guess" return.

### 3.3 Calibration and validation regime (C4)

- **Persisted pairs.** Every emitted estimate is journalled (C13) and later
  joined to the C2 resolver outcome. Both trade and no-trade decisions are
  journalled, so the calibration population is not conditioned on having traded
  — otherwise the calibration set is exactly the selection-biased subset the
  strategy already liked.
- **Strata, not a global number.** At minimum: city × clearance band (the
  pre-registration's five bands `[0,1) [1,2) [2,3) [3,5) [5,∞)`) × lead time.
  Adding a global figure is permitted for reporting and forbidden for gating.
- **Rolling error** computed by a scheduled batch job, versioned, stored. The
  trading path READS the current version. It never computes calibration inline.
- **The no-trade gate is the default path.** A stratum trades only if it
  affirmatively passes: sample count ≥ its floor AND rolling error within
  threshold AND the verdict not expired. Missing stratum ⇒ no trade. This is the
  same fail-closed shape as the pre-registration's UNDERPOWERED handling and is
  deliberately not a separate mechanism.
- **The thresholds are NOT invented here.** Sample floors come from the
  pre-registration's `N(c,k)` construction; the rolling-error threshold is
  **[NEEDS DERIVATION]** and must be derived from the same break-even arithmetic
  as §4.5's edge floor, not chosen. Until derived, the gate is closed. Marking it
  needing derivation is the honest state; writing a plausible number here would
  be exactly the failure this repo has repeatedly shipped.

---

## 4. Edge computation (C5)

### 4.1 The quantity being computed

For a BUY of `C` YES contracts at an achievable average fill price `p`, held to
settlement:

```
q          = P(contract settles YES | all evidence at decision time)
payout     = 1.00 per contract, in USD           [ASSUMPTION — see §11, REQ-SETTLE-07]
fee_entry  = PolymarketUSFeeModel.get_commission(order, qty, price, instrument)
           = theta * C * p * (1 - p),  banker's-rounded to $0.01
EV_total   = C * q  -  C * p  -  fee_entry  -  0          [no exit fill: held to settlement]
EV_per_ct  = q - p - theta * p * (1 - p)
```

**`q` is not the model's probability.** It is the model's probability *composed
with settlement risk*:

```
q = p_yes_lower_95  *  H_lb(c, k)
```

where `H_lb(c,k)` is the pre-registration's Wilson-95%-lower bound on the
one-sided hit rate for city `c` and clearance stratum `k`. For Tier 1,
`p_yes_lower_95 = 1` by arithmetic and therefore `q = H_lb(c,k)` exactly. **This
is where R1 enters the money math** — not as a haircut applied afterwards, but as
the definition of the probability being traded on.

### 4.2 The fee has exactly ONE definition

`fee_entry` is obtained by **calling** `PolymarketUSFeeModel.get_commission`
with a real `Order`/`Quantity`/`Price`/`Instrument`. The formula
`theta*C*p*(1-p)` appears in this document for exposition and **may not be
re-implemented in `edge.py`**. Two implementations of one quantity will drift;
that is finding #5 of the standing paper-close lesson in a new location.

A static test must assert that `theta * ... * (1 - ...)` appears in no module
other than `fees.py`.

Three consequences carried through from `fees.py`, unchanged:

- **Post-only orders raise `MakerRebateUnmodelledError`.** The documented maker
  coefficient is a −0.0125 **rebate** modelled as a +0.06 cost; a posting
  strategy is negative *by construction* and unevaluable. §8 must preserve this
  at the execution boundary, not only in backtest.
- **Incidental maker fills warn loudly** and their numbers are not clean.
- **The per-fill vs cumulative banker's-rounding approximation differs in BOTH
  directions.** No "never understates" claim is available and none is made here.

### 4.3 Break-even, and the exact trade predicate

`EV_per_ct > 0` rearranges to the break-even price function:

```
BE(p, theta) = p + theta * p * (1 - p)
```

`dBE/dp = 1 + theta*(1 - 2p) > 0` for `theta <= 1` on `[0,1]`, so `BE` is
strictly increasing and invertible in `p`. (Stated because the standing lesson
requires formulas to be simplified, not read — this one does not collapse.)

**Worked table, theta = 0.06 pinned (729/729 observations), computed with
`Decimal`:**

| `p` | `BE(p, 0.06)` | `BE(p, 0.09)` stressed |
|---:|---:|---:|
| 0.95 | 0.952850 | 0.954275 |
| 0.97 | 0.971746 | 0.972619 |
| 0.98 | **0.981176** | 0.981764 |
| 0.99 | 0.990594 | 0.990891 |
| 0.996 | 0.996239 | 0.996359 |
| 0.9967 | 0.996897 | 0.996996 |

**The trade predicate (REQ-ALPHA-03), strict `>`, Decimal, checked AFTER tick
rounding and AT the intended size:**

```
q  -  BE(p_bar, theta)  >  epsilon
```

where `p_bar` is the **depth-weighted average fill price for the intended size**,
after rounding the limit price UP to the instrument's `price_increment` (up = the
conservative direction for a buy), and `epsilon` is the derived minimum-edge
floor of §4.5.

Equivalently, and more useful in code, invert it into a **maximum admissible
price**:

```
p_max(q, theta, epsilon) = largest tick-aligned p with BE(p, theta) + epsilon <= q
```

This is the strategy's limit price ceiling. It exists because `BE` is monotone
(above). Both forms must not be implemented; pick `p_max` and derive the
predicate from it, or the two will drift.

### 4.4 What R1 does to this arithmetic — the load-bearing derivation

> **REVISED 2026-08-27 (review round 1).** Revision 1 (a) used point estimates
> where §4.1 mandates Wilson **lower** bounds — NYC's headline was +$1.78 and is
> actually **+$1.68**, a 5.6% overstatement of the only positive number in the
> document; (b) placed a per-**threshold-case** rate next to a per-**city-day**
> concordance with no flag, though their mismatch rates differ ~4x; and (c)
> quoted the boundary-restricted figures in a dollar column and summed them to
> "~$8.6/day, squarely inside the ~$9/day central band" — a caveat-then-use paper
> close, over a **mixture** of four restricted figures plus NYC's unrestricted
> one. **That sentence and that dollar column are deleted and may not be
> reinstated.**

**Denominators, stated before any number.** Two populations appear in the source
diagnosis and they are not interchangeable:

- **threshold-case** — one row per (city-day × margin bucket), 4 buckets per
  city-day, ~7,280 per city. The bucket weights are **design-imposed and uniform
  (25% each)**, which is *not* the clearance distribution the strategy faces.
- **city-day** — one row per city-day, ~1,820 per city. This is the concordance
  `c` the pre-registration §7 uses.

At MDW these read 0.9485 and 0.7990 respectively — a ~4x difference in mismatch
rate. **The pooled threshold-case agreement rate is retired from this section as
a gating input:** with uniform synthetic bucket weights it is a hit rate against
no real population. It survives in exactly one row below, labelled, only to
reconcile with revision 1's headline.

**Every table in this document from here on states its denominator in the
header.**

#### 4.4.1 The stratum the strategy actually decides in

`BE(p, theta)` is indexed by city and stratum **through `p`**, and §4.3 proves it
is strictly increasing in `p`. Revision 1 pinned `p = 0.98` everywhere and then
reasoned as if feasibility were a property of the stratum alone. It is not.
`p = 0.98` is an **assumption with no derivation in this repo** (§4.7 and §11
A12). Everything below is conditional on it and is labelled as such.

**Denominator: threshold-cases within the boundary bucket (n ≈ 1,820 per city).
`q` is the Wilson 95% LOWER bound. `p = 0.98`, `theta = 0.06`, `BE = 0.981176`.**

| City | ≤0.5 °F bucket rate | Wilson-95% lower | `q − BE(0.98)` /contract | per 100 contracts |
|---|---:|---:|---:|---:|
| NYC | 0.9983 | 0.9951 | +0.013924 | **+$1.39** |
| MIA | 0.8505 | 0.8334 | −0.147776 | −$14.78 |
| SFO | 0.8105 | 0.7917 | −0.189476 | −$18.95 |
| LAX | 0.8121 | 0.7935 | −0.187676 | −$18.77 |
| MDW | 0.7990 | 0.7800 | −0.201176 | −$20.12 |

*Reconciliation row, pooled threshold-case denominator (n ≈ 7,256), retired as a
gating input:* NYC's pooled unrestricted Wilson lower is 0.998010, giving
0.998010 − 0.981176 = **+0.016834 = +$1.68 per 100**. This is the corrected form
of revision 1's +$1.78 headline.

**R1 does not shrink the edge at the boundary. It inverts the sign, by an order
of magnitude, at four of five cities** — and the one city with a positive number
is the one the pre-registration excludes from the primary verdict.

#### 4.4.2 The wide-clearance strata — no dollar figures, and here is why

Above 0.5 °F of boundary distance, every city's Wilson lower bound exceeds
`BE(0.98, 0.06) = 0.981176`:

| City | >0.5 °F Wilson-95% lower | exceeds `BE(0.98)`? |
|---|---:|---|
| LAX | 0.999297 | yes |
| MIA | 0.998959 | yes |
| SFO | 0.997833 | yes |
| NYC | 0.998111 | yes |
| MDW | 0.996880 | yes |

**No dollar column is computed from this table, and none may be.** Three reasons,
each independently sufficient:

1. **These figures are lookahead-contaminated.** The restriction conditions on
   `abs(unrounded_metar_max_f − threshold_f)` — distance from the day's **FINAL**
   METAR max, a hindsight quantity. Pre-registration §7 [R7] point 1 explicitly
   forbids exactly this: §4 conditions on the **intraday running max at receipt
   time**, and substituting the final max "would reintroduce exactly the
   look-ahead that DOM-2 exists to prevent". Revision 1 flagged these figures as
   *symmetric and not `H`* but never as *contaminated*, which is the more serious
   defect.
2. **The contamination is biased favourably.** Filtering on final-max distance
   retains the days that *ended* far from the strike — a population
   systematically safer than the just-crossed state in which the decision is
   actually made.
3. **Summing them across cities produces a mixture, not a statistic.** Revision 1
   summed four restricted figures and one unrestricted one as though they were
   one quantity.

What this table is permitted to establish, and nothing more: **boundary distance
is the variable that moves the sign.** That is why §5.3 makes clearance a
first-class input and why the whole architecture is indexed on
`(city, clearance stratum)`.

#### 4.4.3 Reading against R2

Revision 1 computed a daily-dollar figure here and compared it to G-02's central
band. **That computation is withdrawn** — its inputs were contaminated and mixed.

The honest statement: **this architecture does not reverse R2 and offers no
number that bears on whether R2 is reversible.** It is the instrument that would
measure a reversal if the tape shows one.

### 4.5 The minimum-edge floor `epsilon`

> **REVISED 2026-08-27 (review round 1).** Revision 1 (a) never named a bootstrap
> deadlock that makes `epsilon` permanently unobtainable as specified; (b) chose
> the *smallest* tradeable clip as the reference size, which measures the
> **minimum** slippage over all sizes — a directional choice in the
> anti-conservative direction, presented as neutral circularity-breaking; and (c)
> claimed "neither is a judgement call" about a construction containing at least
> three judgement calls.

REQ-ALPHA-03/DOM-5 require the floor (strict `>` alone would permit trading at
one basis point of edge). The governing principle forbids the operator supplying
it. It is machine-derived, versioned, stored, and read by the trading path.

#### 4.5.1 The bootstrap deadlock, named

Revision 1 defined `epsilon`'s first term over "the observed decision-to-
acknowledgement latency distribution". **There are no acknowledgements without
submitted orders.** §13.2 listed `epsilon`'s unlock as "tape", but the
market-data tape contains quotes, trades and depth — **no order acknowledgements
whatsoever**. As specified, `epsilon` would be permanently ABSENT, the trading
path permanently closed, and §12's "measured epsilon exceeds measured edge"
falsifier permanently unevaluable. A falsifier that can never be evaluated is not
a falsifier; it is the DOM-1 non-falsifiability defect in a new location.

#### 4.5.2 Resolution: two terms with different unlocks

```
epsilon = eps_quote_drift + eps_size
```

| Term | What it prices | Measurable from | Unlock |
|---|---|---|---|
| `eps_quote_drift` | adverse movement of the best ask between decision time and a plausible arrival time, at a **fixed** notional | the quote tape alone — no orders needed | **G-16 tape** |
| `eps_size` | additional adverse movement from walking the book to the intended size, plus round-trip latency measured against real acknowledgements | requires submitted orders | **D3 probe ceiling** |

**Both terms must be present for the trading path to open.** `eps_size` is
therefore an operator-gated unlock (D3 — a spend cap, a legitimate ceiling), not
a data-gated one, and §13 is corrected accordingly. `eps_quote_drift` alone is
**not** a permissible floor: using it alone silently sets `eps_size = 0`, which
is the anti-conservative default this document exists to forbid.

#### 4.5.3 The judgement calls, named rather than denied

Revision 1 asserted "neither is a judgement call". That was false. At least three
are, and each must be pre-registered before measurement, not chosen after:

1. **The quantile.** "95th percentile" is a choice. A tail-risk-averse reading
   argues for a higher one.
2. **The reference notional for `eps_quote_drift`.** Revision 1 used the smallest
   tradeable clip. On a `minimumTradeQty = 0.01` market — **378 of 680 observed
   slugs** — that clip is ~$0.0098 of notional, its depth-weighted fill price
   simply *is* the best ask, and the term therefore acquires **zero size
   dependence**. The circularity was not resolved; it was dissolved by measuring
   a different quantity. Replaced: the reference notional is the **median
   intended clip implied by the §6.4 caps at the D5 ceiling**, which is a real
   size and is known before any trade.
3. **"Half-width of the `H_lb` interval"** — a specific and arguable way to price
   statistical uncertainty.

**Until both terms exist, `epsilon` is ABSENT and the trading path is closed.**
Required-no-default means the config points at a stored version and construction
raises when there is none. There is no fallback constant, and writing one into
this document would be the defect this repo keeps shipping.

#### 4.5.4 The expected outcome, stated in advance

Tick size is 0.01 and NYC's corrected boundary-stratum edge is +0.0139/contract —
**1.4 ticks.** A 95th-percentile adverse move in a book quoted on a 0.01 grid is
**≥ 0.01 essentially by definition**, because one tick is the smallest
non-zero move available. It is therefore **expected**, not hypothetical, that
`eps_quote_drift` alone consumes most or all of the measured edge. §12 is
corrected to record this as the expected outcome.

### 4.6 Tick rounding, minimum quantity, depth

> **REVISED 2026-08-27 (review round 1).** Revision 1's `minimumTradeQty` worked
> example described a code path that cannot execute — see the dead-algebra note
> below. Caught by tracing what an implementer would run, per the standing lesson.

All three are per-market venue facts, never constants:

- **`orderPriceMinTickSize`** — 0.01 in 729/729 observations, read per market from
  `parsing.py:1129`. The limit price rounds **UP** for a buy. The edge predicate
  is re-evaluated at the rounded price.
  **Magnitude, computed:** at NYC's corrected boundary edge of 0.0139/contract,
  one tick of upward rounding is 0.01 — **72% of the total edge**, and `p_max`
  admits roughly one price level. Rounding is not a rounding error here; it is
  the dominant cost term after the fee.
- **`minimumTradeQty`** — **VARIES: 378 slugs at 0.01, 302 at 1.**
  **DEAD ALGEBRA, verified in code.** `parsing.py:1173` and `parsing.py:1178`
  construct `size_increment` and `min_quantity` from the **same value**, so on
  every instrument this parser builds they are identical by construction.
  Therefore §6.2's step 4 (`if sized < min_quantity → 0`) **can never fire**: any
  value that survives `floor_to(raw, size_increment)` is already a multiple of
  `size_increment` and hence ≥ `min_quantity` unless it is zero, which step 3
  already produced. Revision 1's worked example ("a cap-derived size of 0.6 on a
  min-qty-1 market is a NO-TRADE") is delivered entirely by step 3, and §6.3's
  corresponding property test passes trivially against an implementation that
  omits step 4 altogether.
  **Disposition:** keep step 4 as a guard against the two fields diverging in
  future, and add a **contract test that FAILS if `min_quantity != size_increment`
  ever becomes true** for a parsed instrument — that failure is the signal that
  step 4 has become live and its behaviour must be re-reviewed. Do not describe
  step 4 as an active protection; it is a tripwire.
- **Depth.** `p_bar` is computed by walking `OrderBookDepth10`. The venue can
  publish more than ten levels (captured book: 12 bids / 14 offers) and
  `DepthTruncation` records only *how many* levels were dropped, not their prices
  or sizes. **If the intended size is not fillable within the visible ten levels,
  the size is refused, not estimated.**

### 4.7 The joint distribution of clearance and price — the unexamined dependency

> **NEW 2026-08-27 (review round 1).** This is the deepest open finding in the
> document and it may kill the strategy independently of any anchor, any gate and
> any settlement statistic.

Every positive number in this document is conditional on an entry price
`p = 0.98` that **has no derivation anywhere in this repo**. §4.3 proves `BE` is
strictly increasing in `p`; §4.4.1 then holds `p` fixed while varying the
stratum. That is backwards, because **clearance and price are not independent —
they move together.**

**The mechanism.** At the `FIRE` decision the observed running max has *just*
crossed the strike. Clearance is therefore in `[0,1)` **by construction**.
Reaching `[2,3)` or `[5,∞)` requires waiting for the temperature to rise further
— by which time the market has observed the same thing and repriced toward 1.00,
and the 1.4-cent gap that made the trade worth taking is gone.

**The consequence.** The strata that CLEAR the break-even may be practically
unreachable, and the stratum in which the decision is actually made is the one
that fails. Inverting the break-even gives the maximum payable price per city at
the boundary stratum (Wilson lower, `theta = 0.06`):

| City | boundary Wilson lower | `p_max` — max payable price at that stratum |
|---|---:|---:|
| NYC | 0.9951 | 0.9948 |
| MIA | 0.8334 | 0.8247 |
| LAX | 0.7935 | 0.7833 |
| SFO | 0.7917 | 0.7815 |
| MDW | 0.7800 | **0.7694** |

**MDW's `[0,1)` stratum is not unreachable. It is unreachable *at 0.98*.** It is
FEASIBLE at any entry price at or below ~0.769. Whether the book ever offers
0.769 at the moment of a fresh crossing is an empirical question nobody in this
repo has asked.

**This is the cheapest falsifier in the entire system.** Measuring the joint
distribution of `(clearance_f at decision time, best ask at decision time)`
requires **the quote tape and the weather feed only — no settlement outcomes, no
G-17, no anchor, no operator gate.** If wide-clearance observations consistently
quote above their `p_max`, the strategy is dead regardless of everything else in
this document, and that is knowable in week one of capture rather than after the
full §7 archive extension and a 42-day gate cycle.

It is promoted to build slot 3 in §13.1 and to open question #1 in §14.
## 5. The settlement-risk gate (C6) — wiring R1

This component **wires** `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`
revision 14. It re-derives nothing. Its entire job is to make the
pre-registration's classifications physically block orders.

### 5.1 Inputs

```
SettlementVerdict:                       # written by the G-17 study, read-only here
    city                : str
    stratum             : ClearanceBand  # [0,1) [1,2) [2,3) [3,5) [5,∞)
    classification      : Literal[
        "GO", "NO_GO", "UNDERPOWERED", "NOT_YET_ANSWERABLE",
        "STRUCTURALLY_UNREACHABLE", "PROVISIONAL_UNDERPOWERED",
        "OUT_OF_SCOPE_DOM9", "THETA_CONTINGENT",
    ]
    H_lower_95          : Decimal | None # None for every non-GO classification
    branch              : Literal["A", "B"]        # which anchor branch fired
    anchor_value        : Decimal
    sample_count        : int
    evaluated_at_ns     : int
    evaluation_round    : int            # 1, 2 or 3 — the 42-day expiry counter
    study_version       : str
```

The pre-registration requires that a study output carrying fewer than *branch,
sample count, anchor value, feasibility classification* per cell "is incomplete
and may not be used for a verdict". The schema above makes an incomplete verdict
unrepresentable rather than merely discouraged.

### 5.2 Behaviour — the classification-to-action table

| Classification | Trading action | Source clause |
|---|---|---|
| `GO` | `q = H_lower_95`; trade permitted subject to every other gate | §6 threshold |
| `THETA_CONTINGENT` | trade permitted **only** while the live parsed `theta` is at or below the value the verdict was conditioned on; otherwise refuse | §6 fee dependency |
| `NO_GO` | refuse, per city | §7 decision granularity 1 |
| `UNDERPOWERED` | refuse. **Never pooled upward** to manufacture power | §7 |
| `NOT_YET_ANSWERABLE` | refuse. Distinct from PASS and may not be reported as one | §7 coverage |
| `PROVISIONAL_UNDERPOWERED` | refuse; carries no `N(c,k)`; must be reported by name | §7 [R13] |
| `STRUCTURALLY_UNREACHABLE` | refuse **and raise a programme-level escalation**; may NOT be converted to NO-GO by the 42-day clock | §7 [R6] |
| `OUT_OF_SCOPE_DOM9` | refuse for that city; excluded from the rule-3 failure tally | §4 [R10] |

#### 5.2.1 The coverage rule — CORRECTED

> **REVISED 2026-08-27 (review round 1). This correction is load-bearing and
> revision 1 answered it wrong by accident.** Revision 1 rendered the rule as:
> "if the `[0,1)` stratum **has not reached a verdict** in an in-scope city, that
> city's determination is `NOT_YET_ANSWERABLE`". But **`STRUCTURALLY_UNREACHABLE`
> IS a verdict.** Under §5.4's own arithmetic, four cities' `[0,1)` cells return
> exactly that — so the coverage rule would never have fired, the boundary
> stratum would have been permanently exempted, and `[1,2)`-and-above (which
> CLEARS at all five cities) would have traded. The one stratum whose divergence
> motivated the entire pre-registration would have been the one stratum silently
> excused. That is the defect the coverage rule exists to prevent, reintroduced
> by wording.

**Pre-registration §7, verbatim:** "the `[0,1)` stratum must reach a verdict — not
UNDERPOWERED — in every in-scope city", and "A PASS carried entirely by
wide-clearance strata is void."

**Binding enumeration. A `[0,1)` cell SATISFIES the coverage rule if and only if
its classification is one of exactly three values:**

```
COVERAGE_SATISFYING = { GO, NO_GO, THETA_CONTINGENT }
```

**Every other classification at `[0,1)` VOIDS the city** — no stratum of that
city trades, including strata that individually returned GO:

```
COVERAGE_VOIDING = { UNDERPOWERED,
                     NOT_YET_ANSWERABLE,
                     PROVISIONAL_UNDERPOWERED,
                     STRUCTURALLY_UNREACHABLE }
```

Implementation constraints, so this cannot be re-broken:

- The rule is enforced **at the city level**, never per stratum. A per-stratum
  rendering lets the wide bands trade while the boundary band is silent.
- The enumeration is a **closed set match**, never a negation. `not in
  COVERAGE_VOIDING` is forbidden: a classification added later would default to
  *permitted*, which is this defect a third time. A classification absent from
  both sets must raise.
- A test must assert that each of the four voiding classifications, injected at
  `[0,1)`, produces zero orders in a city whose other four strata are all `GO`.

#### 5.2.2 Expiry and programme rejection

- **Expiry.** `evaluation_round > 3` ⇒ the city converts to `NO_GO`. The gate
  refuses on a verdict older than the current evaluation window, so a stale
  verdict cannot quietly keep authorising trades.
- **Rule 3 — programme rejection and halt-and-unwind.** Two or more cities at
  `NO_GO` (arrived at initially *or by expiry conversion*, and excluding
  `OUT_OF_SCOPE_DOM9` cities) rejects the formulation programme-wide. The gate
  then **halts new position-taking in every city immediately, including cities
  already live, and holds open positions to settlement rather than force-closing
  them.** This binds "regardless of how profitable the live cities appear at the
  time". §10.3 implements it as a specific halt kind, because a generic kill
  switch that cancels and flattens would violate it.
### 5.3 Boundary distance is a first-class input

`clearance_f` from §3.2 is the stratification key. It is not derived inside this
gate from anything else, it is not optional, and an estimate lacking it is
refused. This is the single design consequence of R1 that touches every other
component: the system's unit of decision is `(city, clearance stratum)`, not
`(city)` and not `(market)`.

### 5.4 Per-cell feasibility — the arithmetic the implementer will hit first

> **REVISED 2026-08-27 (review round 1). Revision 1 of this section was wrong in
> two ways and right in its verdict, which is the most dangerous combination.**
> (a) It promoted a per-**cell** result to a per-**city** result — unreachability
> is a property of the `[0,1)` stratum, not of a city, and every city's
> `[1,2)`-and-above cells CLEAR. (b) It routed through **Branch B**, applying the
> `2c − 1` fiat doubling. Branch B fires only for cells below **200 cases**;
> every boundary cell carries **~1,820**. **Branch A fires.** Worse, the `c`
> values revision 1 fed to `2c − 1` were *already* the boundary-bucket rates — all
> METAR>CLI mismatches fall in the ≤0.5 °F bucket — so the doubling
> **double-counted**. The classification came out the same; the route was wrong,
> and a route that is wrong for the right answer will be wrong for the next one.

#### 5.4.1 The per-cell table

**Denominator: threshold-cases within the bucket. `theta = 0.06`,
`BE(0.98, 0.06) = 0.981176`. Branch A throughout (every cell ≫ 200 cases).**

| City | bucket | n | rate | Wilson-95% lower | `BE` vs anchor | Classification |
|---|---|---:|---:|---:|---|---|
| LAX | ≤0.5 °F (→ `[0,1)`) | 1820 | 0.8121 | 0.7935 | `BE` > anchor | **STRUCTURALLY UNREACHABLE** |
| MDW | ≤0.5 °F (→ `[0,1)`) | 1826 | 0.7990 | 0.7800 | `BE` > anchor | **STRUCTURALLY UNREACHABLE** |
| MIA | ≤0.5 °F (→ `[0,1)`) | 1813 | 0.8505 | 0.8334 | `BE` > anchor | **STRUCTURALLY UNREACHABLE** |
| SFO | ≤0.5 °F (→ `[0,1)`) | 1799 | 0.8105 | 0.7917 | `BE` > anchor | **STRUCTURALLY UNREACHABLE** |
| NYC | ≤0.5 °F (→ `[0,1)`) | 1814 | 0.9983 | 0.9951 | `BE` < anchor | **FEASIBLE** (excluded from primary verdict) |
| LAX | >0.5 °F (→ `[1,2)`+) | 5460 | 1.000000 | 0.999297 | `BE` < anchor | **CLEARS** |
| MDW | >0.5 °F (→ `[1,2)`+) | 5478 | 0.998357 | 0.996880 | `BE` < anchor | **CLEARS** |
| MIA | >0.5 °F (→ `[1,2)`+) | 5439 | 0.999816 | 0.998959 | `BE` < anchor | **CLEARS** |
| SFO | >0.5 °F (→ `[1,2)`+) | 5397 | 0.999074 | 0.997833 | `BE` < anchor | **CLEARS** |
| NYC | >0.5 °F (→ `[1,2)`+) | 5442 | 0.999265 | 0.998111 | `BE` < anchor | **CLEARS** |

#### 5.4.2 What this does and does not mean

1. **Unreachability is per-CELL.** `[0,1)` is unreachable at four cities;
   `[1,2)`-and-above clears at **all five**. There is no city-level rejection here.
2. **The gate still closes those four cities** — but through §5.2.1's coverage
   rule, not through a city-level anchor verdict. A `STRUCTURALLY_UNREACHABLE`
   `[0,1)` cell is COVERAGE-VOIDING, so `[1,2)`+ does not get to trade behind it.
   **If §5.2.1 is rendered wrongly, this table becomes an argument for trading
   four cities on their wide strata.** That is precisely what revision 1's wording
   permitted.
3. **The archive extension does not change this verdict.** It moves the boundary
   margin from ~0.38 (`0.981176 − 0.60` under the discredited Branch-B route) to
   ~0.20 (`0.981176 − 0.78`). Both are unreachable. Its real value is (a)
   populating `[1,2)`, `[2,3)`, `[3,5)`, `[5,∞)` as *genuine* Branch-A cells on
   receipt-time clearance rather than the two-bucket final-max proxy above, and
   (b) quantifying the size of the `[0,1)` gap so the escalation of
   pre-registration §7 [R6] step 3 is argued from a number. It is demoted from
   build slot 1 (§13.1).
4. **Feasibility is conditional on `p`.** Every row assumes `p = 0.98`. §4.7
   shows MDW's `[0,1)` cell is FEASIBLE at `p ≤ 0.7694`. "Unreachable" here means
   *unreachable at the assumed price*, and that assumption is undischarged.

#### 5.4.3 Pre-registered expectation, recorded BEFORE the extension runs

So the archive extension cannot become a fishing expedition, and per the
pre-registration's own discipline that predictions are recorded before
computation:

- **Expected:** the `[0,1)` stratum returns `STRUCTURALLY_UNREACHABLE` at LAX,
  MDW, MIA and SFO, and FEASIBLE at NYC (which is excluded from the primary
  verdict regardless).
- **Expected anchor magnitude at MDW `[0,1)`:** ~0.78, i.e. the boundary-bucket
  Wilson lower bound above. **An extension result materially above ~0.86 at MDW
  means the receipt-time construction has diverged from the final-max proxy by
  more than measurement noise can explain, and must be reconciled BEFORE its
  number is used for anything.** A surprisingly favourable anchor is a defect
  report, not a result.
- **Falsification of the mechanism:** if `[1,2)`+ cells fail to clear on
  receipt-time clearance when they clear on final-max distance, the favourable
  bias of §4.4.2 point 2 is confirmed and quantified.

#### 5.4.4 Registered disagreement with the review

**Stated because burying it would be the paper-close pattern.** The per-cell
numbers above are stratified by **distance from the day's FINAL METAR max**. That
is the same hindsight quantity the review's own C3 finding correctly identifies as
forbidden by pre-registration §7 [R7] point 1 and biased favourably. The table is
adopted as instructed and is genuinely useful for feasibility illustration, but:

- it may **not** gate anything, populate a `SettlementVerdict` row, or be read as
  a preview of `H(c,k)`;
- the mapping ≤0.5 °F → `[0,1)` and >0.5 °F → `[1,2)`+ is an **approximation
  across different variables** (boundary distance from the final max vs clearance
  from the running max at receipt), not a relabelling;
- consequently the extension's value is understated by "it changes the margin,
  not the verdict". It is also **the only lookahead-free version of this very
  table.** The demotion from slot 1 is accepted on cost/urgency grounds — slots
  1–3 are cheaper and more decisive — not on the ground that the extension is
  merely cosmetic.
## 6. Sizing and risk limits (C7)

### 6.1 Kelly is banned, and here is the derivation

REQ-RISK-06/DOM-3 remove Kelly from Tier 1. The justification, computed rather
than asserted. Buying at `p` with payout 1, net odds `b = (1-p)/p`, the Kelly
fraction is

```
f*(q, p) = q - (1 - q) * p / (1 - p)
df*/dq   = 1 + p/(1 - p)
```

At `p = 0.98`: `df*/dq = 50`.

| `q` | `f*` at `p = 0.98` |
|---:|---:|
| 0.9500 | −1.50 (i.e. short) |
| 0.9800 | 0.00 |
| 0.9812 | 0.06 |
| 0.9900 | 0.50 |
| 0.9969 | **0.845** |
| 0.9990 | 0.950 |

**A 1.7-percentage-point range in `q` moves Kelly from 0% to 84.5% of bankroll.**
`q` here is `H_lb(c,k)`, a Wilson *lower bound* whose width is exactly what the
pre-registration spends a thousand lines trying to establish. Sizing off a
50×-amplified function of the least certain input in the system is the wrong
instrument. Fractional Kelly does not fix it — it scales the whole column and
leaves the 50× sensitivity intact.

### 6.2 What replaces it: cap-and-depth sizing

> **REVISED 2026-08-27 (review round 1). Revision 1 called this rule conservative.
> It is not, and the claim is withdrawn.** A max-clip step function trades the
> **full permitted cap** at `q` one ulp above the epsilon boundary — exactly where
> §6.1's own table says correct Kelly is ~0.06 of bankroll. Refusing to scale UP
> with edge is conservative; refusing to scale DOWN near the gate boundary is the
> opposite, and it is most aggressive precisely where the estimate is least
> reliable.

A **pure function**, no I/O, deterministic, unit- and property-testable:

```
size(
    q               : Decimal,      # settlement-adjusted probability, < 1 by construction
    p_bar           : Decimal,      # depth-weighted fill price at intended size
    theta           : Decimal,      # per market
    epsilon         : Decimal,      # derived floor (§4.5)
    caps            : ExposureCaps, # already-resolved
    visible_depth   : Decimal,      # fillable qty within OrderBookDepth10
    size_increment  : Decimal,      # per market
    min_quantity    : Decimal,      # per market — see §4.6 dead-algebra note
) -> Decimal                        # contracts; 0 means NO TRADE
```

#### 6.2.1 The boundary-calibrated cap

The cap is not a free parameter. It is **calibrated at the gate boundary**:

```
cap_boundary_fraction(p_bar, theta, epsilon)
    = f_kelly( q = BE(p_bar, theta) + epsilon,  p = p_bar )
    = q - (1 - q) * p_bar / (1 - p_bar)
cap_contracts = floor_to( cap_boundary_fraction * bankroll / p_bar, size_increment )
```

Worked, at `p_bar = 0.98`, `theta = 0.06` (`BE = 0.981176`):

| `epsilon` | `q` at the boundary | `cap_boundary_fraction` |
|---:|---:|---:|
| 0.001 | 0.982176 | 0.1088 |
| 0.005 | 0.986176 | 0.3088 |
| 0.010 | 0.991176 | 0.5588 |

**Why this satisfies both constraints.** The clip is a fixed cap at runtime — no
Kelly arithmetic is evaluated per decision, and no size scales with the magnitude
of the edge, so DOM-3/REQ-RISK-06's removal of Kelly *sizing* holds. But because
`f_kelly` is monotone increasing in `q` and every admitted trade has
`q > BE + epsilon` by the §4.3 predicate, **the clip is bounded above by the
Kelly fraction for every trade the gate admits.** Revision 1's rule had no such
bound and could exceed Kelly by any margin.

**Flag for the domain reviewer:** this re-introduces Kelly arithmetic in a
bounded, off-decision-path form. DOM-3's removal of Kelly is honoured in letter
(no runtime Kelly sizing) and, this design argues, in spirit (Kelly is used to
*bound* a cap, not to set a size). **prediction-market-reviewer must rule on
whether that reading of DOM-3 is admissible.** The alternative the review offered
— `size = min(cap, fractional_kelly(q_lower_bound))` — is rejected here only
because it evaluates Kelly on the decision path and reintroduces the 50×
sensitivity of §6.1 directly into the size. If the reviewer disagrees, that
alternative is the fallback and this section is rebuilt on it.

#### 6.2.2 The rule, in order

1. If `q − BE(p_bar, theta) <= epsilon` → **0**.
2. `raw = min(cap_contracts, cap_cluster, cap_city_day, cap_day, visible_depth)`.
3. `sized = floor_to(raw, size_increment)`.
4. If `sized < min_quantity` → **0**. Never round up.
   **This step is a tripwire, not an active protection** — see §4.6: the parser
   builds `min_quantity` and `size_increment` from the same value, so on every
   instrument it produces today the condition cannot be true.
5. Re-evaluate step 1 at the `p_bar` implied by `sized`. If it now fails → **0**.

**Step 5 refuses rather than bisecting to the largest passing size. This is
intentional**, and the reason is stated so it is not mistaken for an oversight: a
bisection search optimises size against a `p_bar` curve derived from ten visible
book levels whose eleventh level is unknown, and it would systematically select
the size that sits exactly at the edge of the priceable region. Refusing costs
trades that a bisection would have taken; taking them would mean sizing to the
boundary of what the tape can price. Revisit only if the §13.1 slot-3
capturability measurement shows refusals are the dominant rejection reason.

### 6.3 Properties that must be property-tested (hypothesis-style)

- `size(...) >= 0` always; never NaN; never negative.
- `size(...) <= every individual cap`, for all inputs.
- **`size(...) <= visible_depth`**, for all inputs.
- `size(...) * p_bar <= cap_boundary_fraction * bankroll` — the Kelly bound of
  §6.2.1 holds for every admitted trade.
- `size(...) == 0` whenever `q − BE(p_bar, theta) <= epsilon` (inclusive — strict
  `>` is required to trade).
- `size(...) == 0` whenever `visible_depth < min_quantity`.
- `size(...)` is a multiple of `size_increment`.
- `size(...)` is monotone non-decreasing in `visible_depth`, non-increasing in
  every cap being tightened.
- **`size(...)` is NOT required to be monotone in `q`** — it is a step function of
  the gate. Asserting monotonicity in `q` would assert the design is something
  other than what it is.
- `q = 1.0` as an input raises (REQ-RISK-06).
- **Separate CONTRACT test (not a property test):** fails if a parsed instrument
  ever has `min_quantity != size_increment`. That failure means §6.2.2 step 4 has
  become live and must be re-reviewed. See §4.6.

### 6.4 Exposure caps

Layered, all required-no-default, all sourced from the D5 operator ceiling and D2
bankroll — the only legitimate operator inputs:

| Layer | Unit | Rationale |
|---|---|---|
| per **cluster** | contracts | REQ-RISK-04: adjacent strikes on one city-day are ONE bet. Sizing allocates per cluster, never per market. |
| per **city-day** | contracts | one city's settlement source failing is one correlated event |
| per **day** (all cities) | contracts | a common-mode NWS/CLI failure hits every city at once |
| **portfolio** | fraction of bankroll | total capital at risk |

Correlation is handled by **crude conservative cluster caps, not an estimated
correlation matrix** (REQ-RISK-04). Estimating a correlation matrix from ≤70
city-days would be fitting noise.

#### 6.4.1 The portfolio-cap unit conversion — a money boundary

> **ADDED 2026-08-27 (review round 1).** Revision 1 expressed the portfolio cap as
> a bankroll fraction while the other three caps are in contracts, and never said
> what price converts between them. An unstated conversion at a money boundary is
> how a wrong number enters silently.

Capital at risk per YES contract held to settlement is the price paid, so:

```
cap_portfolio_contracts = floor_to( portfolio_fraction * bankroll / p_bar,
                                    size_increment )
```

**`p_bar` — the depth-weighted fill price at the intended size — is the correct
denominator, not the best ask, not the mid, and not 1.00.** `Decimal` throughout;
no float may appear in this conversion (STK-12).

#### 6.4.2 Capital lock and time to resolution — MISSING, and it matters

> **ADDED 2026-08-27 (review round 1).** Revision 1 contained no time term
> anywhere: not in EV, not in sizing, not in the caps.

Two facts make this material rather than academic:

1. At the corrected boundary edge — ~0.014 gross on ~0.98 of committed capital —
   the **holding period is a first-order determinant of return on capital.** The
   same absolute edge over 20 hours and over 7 days differ by a factor of ~8 in
   annualised terms, and the day's capital can only be turned once (G-02's
   assumption A6).
2. **A5 is not hypothetical:** REQ-SETTLE-07 records that a market with no data
   "settles at last fair market prices" after **7 days**. That is a 7-day capital
   lock at a *fractional* payout — simultaneously the longest lock and the worst
   payout, and it is currently priced nowhere.

**Required, [NEEDS DERIVATION]:** an expected-time-to-resolution term entering
(a) EV as an opportunity-cost deduction against a stated alternative-use rate,
and (b) the day-level cap as a concurrency limit, since capital locked in a
7-day-resolving market is unavailable to every subsequent city-day. Until
derived, the day cap must be set as if **every** position could lock for 7 days —
the conservative reading — rather than assuming daily turnover.
## 7. Strategy lifecycle on Nautilus (C10)

`Strategy` is used directly. Verified hook surface in 1.231.0 includes
`on_start`, `on_stop`, `on_reset`, `on_resume`, `on_degrade`, `on_fault`,
`on_dispose`, `on_data`, `on_historical_data`, `on_quote_tick`, `on_trade_tick`,
`on_order_book`, `on_order_book_deltas`, `on_order_book_depth`, `on_instrument`,
`on_instrument_close`, `on_instrument_status`, `on_event`, the full
`on_order_*` / `on_position_*` families, and `on_save`/`on_load`.

**No scheduler is introduced.** Periodic work uses the native
`self.clock.set_timer(...)`. No `ExecAlgorithm` is proposed for Tier 1: exec
algorithms exist to slice large orders across time, and Tier-1 clips are bounded
by visible depth in a single book. Introducing one would be speculative
abstraction. It is named here as the correct extension point *if* capturability
later shows size must be worked — and only then.

### 7.1 Hook-by-hook

| Hook | Responsibility |
|---|---|
| `on_start` | **Assert reconciliation SUCCEEDED** (REQ-EXEC-04 — `generate_mass_status` swallows failure via bare `except` → log → return `None`, and combined with `generate_missing_orders=True` a venue outage at startup produces a node that believes it is flat). Assert clock skew inside the venue's ±30 s window. Load halt latches from C9 (**not** `Cache`). Subscribe to instruments, quotes, `OrderBookDepth10`, and the weather `DataType` **via the existing `lru_cache`d `nws_climate_day_data_type()` factory** — never constructed inline (REQ-DATA-07: topic identity is insertion ORDER while `__eq__` is a frozenset, so equality tests pass while production delivers zero messages). Start the staleness timer. |
| `on_data` | Weather records → recompute running max → re-evaluate the affected cluster. |
| `on_order_book_depth` | Refresh `p_bar` / `visible_depth` for subscribed markets. |
| `on_quote_tick` | Cheap staleness bookkeeping only; decisions are driven by depth, since `p_bar` needs depth and the top of book is not a fill price at size. |
| timer (native `clock.set_timer`) | Staleness sweep: any signal older than its per-type max age latches a per-city refusal. Writer-liveness heartbeat check (REQ-RISK-01). |
| `on_order_filled` | Journal the fill; update cluster exposure; re-check caps. |
| `on_event` | Detect `SUBMIT_AMBIGUOUS` conditions → latch a per-market halt (REQ-EXEC-07/SEC-5). |
| `on_instrument_close` | Settlement received → hand to C2 for reconciliation against Breezy's resolver; disagreement → REQ-SETTLE-06 (latch a per-city halt, book PnL at the VENUE's number, retain Breezy's as dispute basis, exclude the day from calibration until classified). |
| `on_stop` | Cancel **working orders only**. **Does NOT flatten positions** — §5.2's halt-and-unwind rule requires open positions be held to settlement. |
| `on_degrade` / `on_fault` | Latch a global halt. |

### 7.2 Every SELL checks the cache first

REQ-EXEC-05: CASH accounts return a **positive** balance impact for SELL, so the
`RiskEngine` free-balance check never blocks a naked sell. The strategy must call
`cache.position(...)` before constructing any SELL. This is a Nautilus behaviour,
not a Breezy one, and it is why the check lives in the strategy.

### 7.3 Disconnect, restart, and idempotency

Nautilus runs a long-lived `TradingNode`, not a cron-invoked cycle. That is the
immutable foundation and is accepted. Run-to-completion idempotency is therefore
obtained differently, from three native or near-native mechanisms:

1. **Durable cache.** `CacheConfig.database` (field verified present) is enabled.
   **CORRECTION 2026-09-01:** Redis is the ONLY backend (`system/kernel.py:312`;
   `:324-329` raises for anything else; `common/config.py:385` requires >=6.2), and
   `docs/plans/EXEC_SPINE_2026-09-01.md` DECLINES that dependency in favour of a
   Breezy `SqliteStateStore` fill record. Nautilus does persist orders and positions
   natively when configured (`cache/cache.pyx:393-394`, `:1366-1368`;
   `cache/database.pyx:709-755`) — so this is a DECLINED NATIVE, not a gap (L-11).
   `cache.database = None` is unacceptable once orders exist (REQ-OPS-13), and
   `generate_missing_orders=True` cannot be the recovery story because it
   *synthesises* orders it cannot match.
2. **Deterministic client order IDs.** `OrderFactory` generates IDs from an
   incrementing counter — restart-safe only via `set_client_order_id_count`,
   which restores a counter, not an identity. Tier-1 needs identity: the same
   decision, re-derived after a crash, must produce the **same** client order ID
   so a retry is a duplicate the venue rejects rather than a second position.
   **REFUTED 2026-09-01 FOR THIS VENUE — DO NOT BUILD IDEMPOTENCY ON IT.**
   Polymarket.us `CreateOrderParams`
   (`docs/evidence/venue/polymarket_us/sdk_snapshot/.../types/orders.py:111-128`)
   carries NO client-order-id field, so the venue CANNOT reject a duplicate on
   identity — a deterministic ID would be a mechanism that silently does nothing
   while reading as protection. Idempotency must be enforced Breezy-side by an
   un-retired submit-intent latch written before the request leaves the process
   (EXEC_SPINE R-7), and `RetryManager` is banned by name (barrier B8).
   **Extension:** a deterministic ID derived from
   `(city, climate_day, cluster_id, decision_seq)`. *Null hypothesis line:*
   checked `OrderFactory` and `ClientOrderId` — Nautilus supplies the type and
   the counter but no content-addressed identity scheme, because idempotency
   under retry is a venue-protocol concern (REQ-VENUE-08). This also satisfies
   REQ-VENUE-15: back off, never blind-retry a POST.
3. **Startup reconciliation as a hard assertion**, per 7.1. `LiveExecEngineConfig`
   supplies `reconciliation`, `reconciliation_lookback_mins`,
   `reconciliation_startup_delay_secs`, `open_check_*`, `position_check_*` and
   `inflight_check_*` (fields verified) — all reused. What is added is the
   assertion that reconciliation actually succeeded, because the native path
   logs and continues.

**Reconciliation mismatch halts. It never self-heals.**

---

## 8. Execution path and the cage (C11) — highest-risk section

> **REVISED 2026-08-27 (security review round 1). Revision 1 of this section
> contained a false central claim and a permit mechanism that was strictly weaker
> than the barrier it replaced.** Both are corrected below. Every finding in this
> revision note was independently verified by the coordinator.
>
> - **§8.1's core claim was FALSE.** Revision 1 said the data path stays
>   "byte-for-byte unchanged", then proposed changing `PERMITTED_METHODS` in
>   `signing.py` — the module the data client holds and calls at `http.py:202`.
> - **`LiveTradingPermit` is forgeable in one line.** It is a public frozen
>   dataclass with no issuer and no authenticity; a permit with a $1e9 cap was
>   constructed in the review. N1 as specified was therefore **strictly weaker
>   than B2**, which refuses non-GET before the signing key is even loaded.
> - **`issued_at_ns` is validated positive and NEVER READ anywhere in `src/`.**
>   One permit authorised every order for the whole process lifetime.
> - **B6 is TWO guards and revision 1 addressed one**, silently deleting the other
>   under a heading reading "No barrier is removed without a named replacement."
> - **N4 was satisfiable by `try/except: pass`**, because the chokepoint returns
>   `None`.
> - **§8.4 was internally inconsistent** — it required a write-capable transport
>   that N3 would fail in CI.
> - **§8.3's ordering constraint was prose with no mechanism.**

### 8.0 Honest statement of what this section costs

The read-only slice today has **six independent barriers** on the write path. The
design below reduces that, on the sanctioned egress path, to **effectively one
enforced chain** — the capability chokepoint of §8.5 — with static guards
constraining what may exist around it. Every other module in the repo keeps all
six.

That reduction is the irreducible cost of being able to trade at all. It is
stated here rather than left to be discovered, because a section claiming
"defence in depth" while collapsing to a single control is the paper-close
pattern applied to security.

### 8.1 The core design decision: a second path, with its own key and its own signer

Relaxing `PERMITTED_METHODS` on the data path is rejected: it converts a
*structural* guarantee ("no module in this repo can emit a non-GET request") into
a *behavioural* one, and does so for a client that never needs to write.

**Corrected design:** the write path gets its **own signing module, its own key
load, and its own method frozenset**, importing nothing from the data-path
signer.

```
breezy/adapters/polymarket_us/
    http.py  transport.py  signing.py   ← UNCHANGED, byte-for-byte. GET-only.
                                          Verified: no shared frozenset is widened.
    exec/
        signing.py     ← own key load, own frozenset {POST, DELETE}, own canonicalisation
        transport.py   ← write-capable pyo3 client; own quota bucket
        egress.py      ← the single dispatch surface; holds the capability chain
        client.py      ← LiveExecutionClient subclass; calls egress only
```

**B2 therefore becomes UNCHANGED**, which is strictly better than revision 1's
proposal and is the direct consequence of the review's finding.

**Path-segment validation before signing.** The HTTP method set is prefix-free,
so no cross-method signature collision exists despite the canonical string's
missing delimiter (verified). The residual is **same-method path ambiguity**:
every interpolated path segment must match `^[A-Za-z0-9_-]+$` before it enters
the canonical string, enforced in `exec/signing.py`.

### 8.2 The permit: issuer, authenticity, expiry, spend-down

Revision 1 treated `LiveTradingPermit` as if construction implied authority. It
does not. Four changes, all required together:

1. **Single-issuer factory.** `LiveTradingPermit` gains a private construction
   guard; the only sanctioned constructor lives in one issuer module which is the
   only place that reads D4 (`BREEZY_TRADING_ENABLED`) and D3/D5.
2. **Provenance verified at use.** The permit carries an authenticity tag over its
   own fields, minted by the issuer from a process-unique secret and **verified in
   `exec/signing.py` before any canonical string is built.** A hand-constructed
   permit fails verification rather than being trusted for its `max_order_notional_usd`.
3. **Expiry, checked against the injected Nautilus `Clock`** — never
   `time.time()`. `issued_at_ns` becomes load-bearing instead of decorative.
4. **Spend-down budget and use count.** The permit carries a remaining aggregate
   notional and a remaining use count, both decremented durably. One permit no
   longer authorises unbounded orders for a whole process lifetime.

**Guard N1 (replaces revision 1's N1):** a static test asserting the literal
`LiveTradingPermit(` appears **only** in the issuer module and its own tests.

### 8.3 Barrier-by-barrier disposition

| ID | Today | Disposition | Replacement guarantee |
|---|---|---|---|
| **B1** `PERMITTED_METHODS` GET-only (`http.py:64`) | data path | **UNCHANGED** | — |
| **B2** signer refuses non-GET (`signing.py:84`) | data path | **UNCHANGED** (corrected from revision 1) | write signing lives in `exec/signing.py` with its own key and frozenset |
| **B3** GET-only closure over the pyo3 client (`transport.py:105-124`) | data path | **UNCHANGED**; `exec/transport.py` gets its own closure | **N2:** the egress closure permits a hardcoded enumerated set of `(method, path)` pairs and refuses everything else. Allowlist by **kind**, not verb (SEC-6/REQ-RISK-08): read/status/cancel always permitted; submit/replace/increase additionally require kill switch clear AND D4 set. |
| **B4** repo-wide static write-verb ban | all of `src/`, `scripts/` | **NARROWED** — the total ban applies to every module except an enumerated allowlist | **N3**, corrected below |
| **B5** SDK signing-module import ban | prefix-matched | **UNCHANGED** | — |
| **B6a** chokepoint has zero production callers (`safety.py:32`) | `src/`, `scripts/` | **CHANGED** — it gains exactly one | **N5a:** guard inverts to "**exactly one** caller, and it is in `exec/egress.py`". Zero→two both fail CI. |
| **B6b** `test_adapter_package_defines_no_live_execution_client` (`readonly_guard.py:533`) — bans **subclassing OR importing** `LiveExecutionClient` | adapter package | **CHANGED — named, not silently deleted.** Revision 1's tree shipped exactly the banned subclass while claiming no barrier was removed. | **N5b:** exactly **one** subclass of `LiveExecutionClient` may exist, it must be `exec/client.py`, and the import may appear in no other module. A second subclass, or the import anywhere else, fails CI. |
| **B7** static barrier suite | CI | **EXTENDED**, never weakened | N1–N10 |
| **F1/F2** fee barriers | backtest venues | **EXTENDED** — F2 has a hole (§9.1) | **N6** |

**N3, corrected.** Revision 1 exempted exactly one module from B4, then §8.4
required a *separate* write-capable transport — which would itself contain
`.post` and fail CI. Resolved: **N3 is an enumerated allowlist of exactly three
file paths** — `exec/signing.py`, `exec/transport.py`, `exec/egress.py` — hardcoded
in the guard. A fourth entry fails CI. `exec/client.py` is **not** on the list and
must contain no write verb; it calls egress. The revision-1 "under 200 lines"
guidance applies to `egress.py` alone.

Remaining new barriers:

- **N6 — `SandboxExecutionClient` banned** by import and construction (§9.1).
- **N7 — `BREEZY_TRADING_ENABLED` (D4) has no default and no inferring code
  path.** Static scan for any assignment, `getenv` default, `or`-fallback or
  `try/except` producing a truthy value the operator did not set. REQ-RISK-09.
- **N8 — post-only refusal survives at the execution boundary**, not only in
  backtest: the modelled maker fee is wrong **in sign**.
- **N9 — dry-run routes to a stub egress that cannot import the write-capable
  transport**, asserted statically.
- **N10 — egress refuses to CONSTRUCT when §10.4's circuit-breaker thresholds are
  absent.** Revision 1 left nothing preventing live egress while drawdown and
  rejection-count thresholds were `[NEEDS DERIVATION]`. Same treatment as N7:
  no default, no inference, construction raises.

### 8.4 The capability chokepoint — a type error, not a convention

Revision 1's N4 asserted that `assert_live_order_submission_permitted` "is called
on every path". Because it returns `None`, that assertion is satisfied by
`try: assert_...(...) \nexcept Exception: pass`. **N4 is deleted.**

Replaced by a structural mechanism: the chokepoint returns a **single-use
capability** bound to a hash of `(method, path, body, order_notional_usd)`, and
`exec/transport.py`'s dispatch **requires that capability positionally**. Then:

- skipping the chokepoint is a **TypeError at the call site**, not a policy
  violation a static scan must catch;
- a capability minted for one request cannot dispatch a different one — the hash
  binds method, path, body and notional together;
- single-use means a replay inside the 30 s signing window cannot re-dispatch.

The chokepoint's five existing refusal conditions (credentials complete, permit
present, `manualOrderIndicator` explicit, notional positive, notional ≤ permit
max) are **unchanged**; §8.2's provenance, expiry and spend-down checks are added
alongside them.

### 8.5 Quota, retry, and the shared budget

Revision 1 never mentioned the quota allowlist. Disposition:

- **`PERMITTED_QUOTA_KEYS` on the data path is UNCHANGED and gains no order
  bucket.** `exec/transport.py` carries its **own** allowlist with its own order
  bucket. The two are separate objects; neither can grant the other's keys.
- **The venue budget is shared and finite.** Revision 1's "retry-with-same-ID"
  had no cap and no backoff, which would burn a budget shared with the data path
  and **blind the strategy mid-position** — the worst possible moment. Required:
  a hard retry cap, exponential backoff, and a **reserved data-path share that
  egress cannot consume**. Exhausting the egress share latches
  `HALT_NEW_EXPOSURE`; it must never starve quotes.
- Retries reuse the deterministic client order ID of §7.3 (REQ-VENUE-08/15: back
  off, never blind-retry a POST).

### 8.6 Halt reads: fail-closed, and thread ownership resolved here

Revision 1 left both unspecified.

- **Fail-closed, explicitly:** any exception, timeout, or absent row when reading
  a halt latch is treated as `HALT_ALL_DISPATCH`. There is no code path where an
  unreadable halt store resolves to permitted.
- **Thread ownership.** `SqliteStateStore` is confined to its **constructing**
  thread (REQ-RISK-02/STK-2), and egress runs on the Nautilus event loop. This is
  resolved **here, in the adapter design**, not later: the halt store used by
  egress is constructed on the event-loop thread that egress dispatches from, and
  a startup assertion pins the owning thread identity. If a future topology
  separates them, an explicit loop-affine accessor is required — never a
  cross-thread call to the existing store. REQ-EXEC-09 makes this an *input* to
  adapter design, not a later fix.

### 8.7 The sequencing constraint, now with a mechanism

STK-1's residual (G-04) is an **in-process constructor block for known pyo3
clients, not a kernel-level egress block.** Today that is tolerable only because
B4 means no module in the repo can emit a POST. **The moment `exec/` exists, an
ordinary `uv run pytest -q` could transmit a signed order while every gate reads
green.**

Revision 1 stated this as prose with no enforcement. **Corrected to a guard test:**

```
if any file under exec/ exists:
    assert a firewall/network-namespace attestation file is present and current
    assert a real connect() to a canary address RAISES in-process
```

Both conditions, not either. The attestation alone is a claim; the live canary
connect is the check. The test fails CI if `exec/` exists without both.

### 8.8 What the egress module may and may not contain

- **May:** endpoint constants, request construction, the permit-carrying signing
  call, the chokepoint call, capability threading, response parsing, capped
  retry-with-same-ID.
- **May not:** any decision logic, any sizing, any edge computation, any gate.
  Every refusal has already happened upstream. A transport that can decide is a
  second, undocumented risk surface.
- **Must:** be the only module importing `exec/transport.py`, and stay under 200
  lines. Size is a reviewability property here, not style.
## 9. Backtest harness (C12)

### 9.1 Barrier F2 has a hole, and it must be closed first

F2 fails the suite if any module constructs a `BacktestEngine` venue without
`fee_model=PolymarketUSFeeModel()`. **`SandboxExecutionClient` does not go
through `BacktestEngine.add_venue`.** It constructs `SimulatedExchange` directly
with `fee_model=MakerTakerFeeModel()` hardcoded
(`adapters/sandbox/execution.py:109-124`), and `SandboxExecutionClientConfig`
exposes no fee or latency field (verified by field inspection).

Consequences, both directions stated:

- **Fees, safe direction but useless.** `MakerTakerFeeModel` computes
  `notional * taker_fee = theta*C*p`. At `theta = 0.06`, `C = 100`, `p = 0.98`:
  **$5.88 against the venue's true $0.1176 — a 50× overstatement.** Relative
  error is `1/(1-p)`, unbounded as `p → 1`, which is exactly where weather
  Tier-1 trades sit. Every paper trade would look catastrophically unprofitable.
  Fail-safe for a go/no-go, worthless for calibration.
- **Latency, DANGEROUS direction.** `LatencyModel(0)` means zero latency, i.e.
  perfect capturability. Combined with the above, a sandbox run would be
  simultaneously too pessimistic on cost and too optimistic on fill.

Nautilus is immutable, so this cannot be patched. **Resolution:** barrier N6 bans
`SandboxExecutionClient`. Paper mode is implemented instead as §9.2.

### 9.2 Dry-run / paper mode

A first-class mode flag that runs the **entire** pipeline — discovery, weather,
probability, settlement gate, calibration, edge, sizing, pre-trade gate, decision
journalling — and stubs **only** the final dispatch inside `exec/egress.py`. The
stub records the order that would have been sent, with its exact signed-canonical
inputs minus the signature.

Paper results feed the same calibration tables, **tagged by mode**, so paper and
live are never silently pooled. Barrier N9 asserts the stub cannot import the
write-capable transport.

This is more work than reusing the native sandbox, and §9.1 is why.

### 9.3 Backtest wiring

- `BacktestEngine.add_venue(..., fee_model=PolymarketUSFeeModel())` — mandatory
  under F2.
- **Expiry must be injected.** `BINARY_OPTION` is absent from
  `ENGINE_EXPIRING_INSTRUMENT_CLASSES` (verified: `{FUTURE, FUTURES_SPREAD,
  OPTION, OPTION_SPREAD}`), so a backtest **never** expires a binary. An
  `InstrumentClose` with `close_type=CONTRACT_EXPIRED` must be injected **AND**
  `settlement_prices` populated — `close.close_price` is never read by the
  matching engine. Without **both**, every position silently shows open at
  end-of-run and the PnL is meaningless (REQ-SETTLE-08).
- **Replay is one-shot and memory-capped.** Streaming catalog replay RAISES for
  Breezy's custom record types — the Rust `DataBackendSession` cannot see a
  Python `register_arrow` schema (REQ-DATA-10, contract-tested). Any harness must
  be built inside that bound; a streaming harness will fail at runtime, not at
  design time.
- **Same code, injected clock and data source.** The harness replays through the
  *production* decision functions. A parallel reimplementation is prohibited: the
  point of the harness is to test what runs.
- **Lookahead guard is structural, not disciplinary.** All catalog reads go
  through `read_climate_day_as_of_settlement(..., as_of_ts_init=)`
  (`catalog.py:552`), which carries a mandatory bound. All timestamps are Breezy
  **receipt** timestamps, never METAR valid times (DOM-2). A test must assert
  that no harness path reads a valid-time field.

### 9.4 What a backtest on ~14 days of tape actually answers

Stated bluntly, because overclaiming here is how a false GO gets manufactured.

**It CAN answer:**
1. **Mechanical correctness** — does the pipeline run end to end, do orders
   construct, does settlement resolve, does the fee model get called.
2. **Determinism** — replaying identical inputs reproduces identical decisions
   bit-for-bit. This is the regression guard for every later refactor.
3. **Capturability** (the pre-registration's second required gate) — was the
   quoted size actually available at the quoted price, within visible depth,
   at the moment of decision.
4. **Trade-count upper bound** — how many `FIRE` events were tradeable at all.
   If this is near zero, the strategy does not exist and no further analysis is
   needed. **This is the cheapest available falsifier and should be computed
   first.**

**It CANNOT answer whether the strategy is profitable, and here is the
arithmetic:** 14 days × 5 cities = **70 city-days**, one cluster each per
REQ-RISK-04. Split across five clearance strata that is ~14 observations per
`(city, stratum)` cell, against a Branch-A archive-sufficiency bar of **200
cases** and live floors `N(c,k)` that are larger still. Every cell would be
UNDERPOWERED by the pre-registration's own rule, and pooling upward to
manufacture power is explicitly forbidden. **A PnL number from this harness is
noise with a dollar sign in front of it and may not be reported as a result.**

The harness output should therefore be shaped so a PnL total is *hard to
extract*: report trade counts, capturability rates, refusal-reason histograms and
determinism hashes. Not a equity curve.

---

## 10. The kill path

### 10.1 Where the latch lives

`SqliteStateStore` (C9), **never** the Nautilus `Cache` — `Cache.reset()` can
launder a permanent halt (REQ-RISK-03). Checked at the top of every decision, not
cached across decisions: `SettlementGate.require_open` already documents this
("callers must call this immediately before acting on a site's data, never rely
on a decision made earlier"), and REQ-OPS-15 flags that a second reader caching
the first result forever would falsify exactly that promise.

### 10.2 Automatic trips — no human required

| Trip | Scope | Source |
|---|---|---|
| Ingestion gate not OPEN | per city | REQ-RISK-01 |
| Observation older than its max age | per city | REQ-RISK-01 (freshness dimension, SEC-1) |
| Writer-liveness heartbeat stale | global | REQ-RISK-01 — an uncleanly killed writer must refuse trading even if the last stored latch read OPEN |
| Clock skew > venue ±30 s window | global | REQ-OPS-07 / REQ-VENUE-02 |
| Startup reconciliation did not succeed | global | REQ-EXEC-04 |
| `SUBMIT_AMBIGUOUS` (submit timed out / status ambiguous) | per market | REQ-EXEC-07 / SEC-5 — read/status/cancel/reconciliation only until resolved |
| Settlement disagreement venue vs Breezy FINAL | per city | REQ-SETTLE-06 |
| `BOUNDARY_UNRESOLVED` fraction over threshold | alert + per market refusal | REQ-SETTLE-03a |
| Settlement verdict absent / expired / non-GO | per city or stratum | §5.2 |
| Calibration stratum uncalibrated or drifted | per stratum | §3.3 |
| `theta` parsed differs from the verdict's conditioning value | per market | §5.2 THETA-CONTINGENT |
| Intended size exceeds visible depth | per market, refusal | §4.6 |
| Repeated order rejections | global | circuit breaker |
| Drawdown threshold | global | **[NEEDS DERIVATION]** — see 10.4 |

Every refusal is **counted, journalled with its reason, and alerted** (REQ-RISK-07).
A silent refusal is indistinguishable from a quiet market, which is the same
failure shape as G-12's `MARKET_SLUG_KEY` hazard.

### 10.3 The halt-and-unwind rule requires TWO halt kinds

A generic kill switch would violate the pre-registration. §5.2 rule 5 requires
that a programme-wide rejection **halts new position-taking everywhere while
holding open positions to settlement rather than force-closing them** — closing
early realises a loss on a premise not shown false for that city.

```
HALT_NEW_EXPOSURE   : refuse submit/replace/increase.
                      Cancel WORKING orders. Hold positions to settlement.
                      ← programme rejection, verdict expiry, calibration failure
HALT_ALL_DISPATCH   : additionally refuse everything except
                      read / status / cancel / reconciliation.
                      ← credential compromise, reconciliation mismatch,
                        SUBMIT_AMBIGUOUS, clock skew
```

Neither kind flattens positions automatically. **Nothing in this architecture
force-closes a position without a human.** That is a deliberate asymmetry: an
automated flatten under a data fault is itself a trade made on faulty data.

### 10.4 Circuit-breaker numbers

The drawdown threshold, the rejection-count threshold and the reset policy are
**[NEEDS DERIVATION]**. They are expressible as fractions of the D5 operator
ceiling (legitimate — a ceiling), but the fractions themselves must be derived
from the measured distribution of daily PnL once any exists. Writing plausible
numbers here would be inventing them.

> **ADDED 2026-08-27 (security review round 1).** Revision 1 left nothing
> preventing egress from being enabled while these thresholds were absent — a
> `[NEEDS DERIVATION]` marker in a document does not stop a process from starting.
> **Barrier N10 (§8.3): egress refuses to CONSTRUCT when the thresholds are
> absent**, with the same no-default/no-inference treatment as D4.

Until derived, the conservative reading applies: no automatic reset, and any trip
requires a human to clear. Only a human clears any latch; nothing in the codebase
may clear one.
### 10.5 Alerting must not block the trading path

Alerts go through the existing `runtime/health.py` substrate, including its
cold-start-fires rule (a latch already true at boot must alert on the first
cycle). The redaction guarantee there is **structural** — there is no attribute
slot that can hold a credential — and a credential-carrying config would be the
first thing to punch through it (REQ-OPS-04). Alert delivery is asynchronous;
a failed alert never blocks or unblocks a decision.

---

## 11. Assumption register

> **REVISED 2026-08-27 (review round 1).** A4 was near-tautological as written and
> is restated; A12 and A13 are added for assumptions revision 1 relied on silently.

Every item is an assumption or unverified inference, not a fact.

| # | Assumption | Evidence | If wrong |
|---|---|---|---|
| A1 | `theta = 0.06` holds for future weather markets | 729/729 captured observations, 680 distinct slugs, both OPEN and RESOLVED — all *captured*, none future | Break-even shifts; effect small (§4.3), and THETA_CONTINGENT exists for it |
| A2 | `feeCoefficient` IS the taker coefficient | inferred from 0.06 matching documented taker theta; **never stated by the payload** | Every cost number is wrong |
| A3 | Banker's rounding to $0.01 | docs snapshot only | Small per-fill; confirm on the first real fill |
| A4 | **No fee is charged on the winning payout notional** (RESTATED) | Revision 1 said "no fee at settlement", which is **near-tautological**: under `theta*C*p*(1-p)`, a settlement at `p ∈ {0,1}` charges exactly zero by the formula's own shape. The substantive hypothesis is a **separate fee levied on the payout notional**, which the formula would not express at all. | A payout-notional fee raises break-even directly and every number in §4.4 worsens. **Cheapest assumption to falsify — check the first captured settlement's charged commission.** |
| A5 | Settlement pays exactly 1.00 | REQ-SETTLE-07: a market with no data "settles at last fair market prices" after 7 days | Fractional payout AND a 7-day capital lock; see §6.4.2 |
| A6 | One cluster per city-day | REQ-RISK-04 | More clusters improve ROI linearly; most likely *pessimistic* assumption here |
| A7 | The IEM archive's METAR is the same estimator the venue's CLI consumes | **cannot be established from local data** (diagnosis §2) | The entire anchor construction measures the wrong relationship |
| A8 | `MARKET_SLUG_KEY = "marketSlug"` | **an unresolved venue guess** (G-12) | The recorder captures nothing and looks like a quiet market |
| A9 | REQ-SETTLE-03 boundary operator (`>` vs `>=`) and rounding AT the strike | **UNKNOWN (G5)**; resolver deliberately frozen | Every boundary-stratum trade potentially on the wrong side |
| A10 | Trading hours permit LAX/SFO (DOM-9) | unknown; derivable from per-market `startDate`/`endDate` | Breadth drops to three cities |
| A11 | Venue settles off the FINAL CLI | **UNKNOWN (G9/REQ-SETTLE-04)**; Breezy's `is_final` gate is *structurally unable* to predict a preliminary-based settlement | A class of settlements unpredictable by construction |
| **A12** | **`p = 0.98` is a reachable entry price at the moment of a fresh crossing** | **NO derivation anywhere in this repo.** Inherited from G-02's worked example, which took it from a single observed quote neighbourhood. Every feasibility classification in §4.4 and §5.4 is conditional on it. | §4.7: the strategy may be dead on price alone. This is the load-bearing undischarged assumption in the document. |
| **A13** | **Uniform 25% margin-bucket weights in the threshold-case denominator reflect a real population** | They are **design-imposed by the study script**, not observed | Any pooled threshold-case rate is a hit rate against no real population — which is why §4.4 retires it |
## 12. What this design cannot do, and what falsifies it

> **REVISED 2026-08-27 (review round 1).** "Measured epsilon exceeds measured
> edge" is moved from hypothetical falsifier to **expected outcome**, and the
> clearance/price joint distribution is added as the cheapest falsifier.

**Cannot:**

1. **Establish that an edge exists.** ~14 days is structurally insufficient (§9.4).
2. **Evaluate any maker or posting strategy.** The modelled maker fee is wrong in
   *sign*. If capturability requires posting, this architecture cannot assess the
   resulting strategy at all and must halt until a real maker fill is observed.
3. **Price any fill beyond visible depth level ten.**
4. **Distinguish an IEM archive artifact from a genuine instrumentation
   difference** (A7).
5. **Detect a change in the venue's settlement source.** Reconciliation catches
   the consequence one settlement late — too late for any position open at the time.
6. **Recover a lost day of tape.**
7. **Discharge A12.** Nothing in this document derives the entry price its every
   positive number depends on.

**EXPECTED outcomes — not hypotheticals, and the design must be correct when they
occur:**

- **`epsilon` exceeds the measured edge.** Tick is 0.01; the corrected boundary
  edge is ~1.4 ticks; a 95th-percentile adverse move on a 0.01 grid is ≥ 0.01
  essentially by definition (§4.5.4). The trade predicate is then never satisfied
  and the system correctly never trades. **This is the single most likely
  terminal state of the programme and the architecture must reach it cleanly
  rather than by crashing or by quietly lowering a floor.**
- **`[0,1)` returns STRUCTURALLY UNREACHABLE at LAX, MDW, MIA, SFO** (§5.4.3),
  and via the corrected coverage rule (§5.2.1) those four cities do not trade.

**Falsified by any of:**

- **The joint distribution of `(clearance_f, best ask)` at decision time** shows
  wide-clearance observations consistently quoting above their `p_max` (§4.7).
  **Cheapest falsifier in the system** — quote tape plus weather feed only, no
  settlement outcomes, no G-17, no anchor, no operator gate. Week one, not month
  two.
- G-17 returns NO-GO at two or more in-scope cities → programme-wide rejection;
  §§6, 8, 10 are never built.
- The archive-derived `p̂_anchor(c,k)` remains below `BE(c,k)` across the theta
  range → an evidence-based NO-GO.
- The tradeable-population count from §9.4 is near zero → there is no strategy.
- A4 turns out false (a payout-notional fee exists) → break-even rises.
- DOM-9 resolves against LAX/SFO → three-city breadth.

**What would NOT falsify it, and must not be treated as if it did:** a positive
PnL number from the 14-day harness (§9.4).
## 13. Sequencing and build order

Three categories, and the boundaries between them are hard.

### 13.1 Buildable NOW — no venue, no credentials, no calendar, no operator

> **REVISED 2026-08-27 (review round 1).** Revision 1 put the pre-registration §7
> archive extension in slot 1, on the ground that it was "the only path avoiding
> rejection-by-arithmetic". That ground was wrong — it moves the margin (~0.20
> instead of ~0.38), not the verdict (§5.4.2). It is demoted to slot 4. The three
> items now ahead of it are cheaper, more decisive, and two of them cost no code
> at all.

| Order | Item | Cost | Why here |
|---:|---|---|---|
| **1** | **Re-issue §5.4 as a per-cell table across all five strata** using the corrected Branch-A route | an afternoon, no code | The current classification is right by luck through a wrong route. Everything downstream reads this table. |
| **2** | **Resolve §5.2.1 in writing and in a test** — does `STRUCTURALLY_UNREACHABLE` at `[0,1)` void the city? | small, one guard test | **Revision 1 answered this wrong by accident, and the wrong answer trades four cities on wide-clearance strata.** Highest consequence-per-hour item in the document. |
| **3** | **Measure the joint distribution of `(clearance_f, p_ask)` at decision time** from the first tape | one study, no settlement outcomes needed | §4.7 — the cheapest falsifier in the system. If wide-clearance observations quote above `p_max`, the strategy is dead regardless of any anchor, and it is knowable in week one. |
| 4 | **Pre-registration §7 archive extension** — simulated running max, receipt-time proxy, day-boundary assignment, five-bin stratification, `wilson_lower_bound` reuse, early/late diagnostic with the 14:00 split and 12:00–16:00 sweep | substantial | Populates `[1,2)`+ as genuine Branch-A cells on **receipt-time** clearance, and produces the only lookahead-free version of §5.4's table (§5.4.4). Pre-registered expectations are recorded at §5.4.3 **before** it runs. |
| 5 | **External network namespace / CI firewall** + the §8.7 guard test | infra lead time | Must precede any file under `exec/`. Start early because it may need infrastructure. |
| 6 | C1 running-max feature actor; C2 settlement resolver (fail-closed on the unresolved REQ-SETTLE-03 boundary operator) | — | Both packages are 0 bytes. Add to mypy `files` in the same change (REQ-OPS-01/REQ-DATA-03). |
| 7 | C5 edge pure functions + C7 sizing pure functions with §6.3's properties, incl. the `min_quantity != size_increment` contract test | — | Pure, no I/O. `epsilon` stays ABSENT; exercised via injected test values. |
| 8 | C13 decision journal + C4 calibration schema | — | Must exist before the first decision, including the first NO-TRADE decision. |
| 9 | C12 backtest harness skeleton on **synthetic** data, F2-compliant, with `InstrumentClose` + `settlement_prices` injection and the one-shot memory bound | — | Proves mechanics before real tape. |
| 10 | C3 probability interface + Tier-1 stub; C6 settlement gate reading an **empty** verdict table | — | Empty table ⇒ every city refuses. Test that first. |
| 11 | C10 strategy, dry-run only, wired to the stub egress (N9) | — | End-to-end with zero write capability in the process. |

Items 1, 2, 3 and 5 are mutually independent and can be dispatched in parallel.
Item 4 is independent of 1–3 but is sequenced after them on value density. Items
6–11 stage behind 6.
### 13.2 Blocked on data — calendar-bound, cannot be compressed

| Item | Unlock |
|---|---|
| G-16 tape accumulation | 14 calendar days after G-14 |
| G-17 `H(c,k)`, `H2(c,k,q)`, capturability | G-16 |
| **`eps_quote_drift`** (§4.5.2) | **G-16 tape — quotes only, no orders needed** |
| **`eps_size`** (§4.5.2) | **NOT tape. Requires submitted orders ⇒ operator gate D3.** Listed here only to be struck: revision 1 put all of `epsilon` under "tape", which was the bootstrap deadlock of §4.5.1. |
| Calibration thresholds (§3.3) | tape + outcomes |
| Circuit-breaker numbers (§10.4) | any PnL distribution |
| Populating the C6 verdict table | G-17 |
| **`(clearance_f, p_ask)` joint distribution (§4.7)** | **quote tape + weather feed only — no settlement outcomes, no G-17.** Available in week one of capture; build slot 3. |

> **REVISED 2026-08-27 (review round 1).** Revision 1 listed `epsilon`'s unlock as
> "tape". The market-data tape contains **no order acknowledgements**, so as
> specified `epsilon` was permanently unobtainable, the trading path permanently
> closed, and §12's own falsifier permanently unevaluable. Split per §4.5.2:
> `eps_quote_drift` is data-gated, `eps_size` is operator-gated (D3). **Both are
> required before the trading path opens** — `eps_quote_drift` alone silently sets
> `eps_size = 0`.

### 13.3 Blocked on operator ceilings — and ONLY ceilings

| Gate | Blocks | Nature |
|---|---|---|
| D1 KYC | Phase A live run, Phase F | authorisation |
| D2 funding | Phase F, bankroll input to caps | money |
| D3 per-dispatch probe USD ceiling | the single-order venue probe **AND `eps_size` (§4.5.2), and therefore the whole trading path** | spend cap |
| D4 `BREEZY_TRADING_ENABLED` | first trade | authorisation, no default (N7) |
| D5 risk caps | first trade | spend caps |

**No agent and no automation in this repo may set D4.** And to restate the
governing principle in its operative form: **the operator supplies no facts.**
If a future design step finds itself wanting to ask the operator what the fee is,
what the tick size is, which markets exist, when trading closes, or what the
settlement source is — that is a discovery task the bot must perform, and the
wanting-to-ask is the bug.

### 13.4 Dispatch routing for the implementing agents

Per the routing boundary: this document is a design. Implementation goes to the
python-specialist tier (RED-first via tdd-guide seeded with the python-testing
skill); domain-math review of §§4, 5, 6 goes to prediction-market-reviewer; the
§8 cage rework additionally requires security-reviewer sign-off before the egress
module lands; code review of diffs goes to python-reviewer.

Items 1, 2, 3 and 5 of §13.1 are mutually independent and are dispatched in
parallel. Item 4 is independent but sequenced after 1–3 on value density. Items
6–11 stage behind 6.

**Two items in §13.1 are documents, not code** (slots 1 and 2). They still go
through review: slot 1 to prediction-market-reviewer, slot 2 to
prediction-market-reviewer **and** python-reviewer, because slot 2's output is a
closed-set enumeration that must land as a guard test, not as prose.

---

## 14. Open questions this document deliberately does not answer

> **REVISED 2026-08-27 (review round 1).** Reordered: the clearance/price joint
> distribution is promoted to #1 because it can terminate the programme on its own
> and is the cheapest thing here to measure.

1. **The joint distribution of `(clearance at decision time, price at decision
   time)`** — §4.7. Clearance and price move together: at `FIRE` the clearance is
   `[0,1)` by construction, and reaching a clearing stratum requires waiting for a
   rise the market also observes and prices. **Every positive number in this
   document depends on this distribution and nobody has looked at it.** Build slot
   3.
2. **A12 — the entry price.** `p = 0.98` has no derivation. §4.7's `p_max` column
   is the shape of the answer; the data is not in the repo.
3. **`epsilon`'s exact estimator** (§4.5) — specified in shape, with its three
   judgement calls named and its two terms' unlocks separated. Not valued.
4. **The rolling-calibration-error threshold** (§3.3) — needs derivation from the
   same break-even arithmetic as `epsilon`.
5. **Drawdown and rejection-count circuit-breaker thresholds** (§10.4). Egress
   cannot construct without them (N10).
6. **Time-to-resolution / capital-lock term** (§6.4.2) — absent from EV and from
   sizing; material at a ~1.4-tick edge.
7. **Whether DOM-3's removal of Kelly admits §6.2.1's boundary-calibrated cap.**
   Explicitly referred to prediction-market-reviewer. If not admissible, the
   fallback is `size = min(cap, fractional_kelly(q_lower_bound))` and §6.2 is
   rebuilt on it.
8. **Whether Tier 2** (model-priced, P≈0 side) is ever entered. Downstream of a
   Phase D GO that does not exist.
9. **REQ-ALPHA-09 minimum-temperature contracts.** The exact Tier-1 mirror, and
   every interface here is symmetric in `measure ∈ {high, low}` — but `series.py`
   reports the five `weather-daily-low-*` series as **UNRESOLVED** (no capture
   carries an event for them), so their settlement stations are unknown. They
   enter when discovery resolves them.
