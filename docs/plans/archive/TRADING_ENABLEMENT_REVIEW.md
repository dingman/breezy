# Trading Enablement Plan — Adversarial Peer Review Record (2026-08-24)

Four independent blind reviewers against
`docs/plans/TRADING_ENABLEMENT_PLAN.md`: code-architect (architecture),
security-reviewer (capital safety and credentials), prediction-market-reviewer
(domain math and market mechanics), python-reviewer (stack and testability).

**All four returned BLOCK.** All four independently judged the plan's evidence
discipline, phase ordering and the falsification-gate *concept* to be strong.
Every block is on specific defects, not on the approach.

Consensus: **Phase 0 and Phase 1 proceed. Phase 1.5 must be restructured before
it is run. Phase 2 entry is blocked.**

---

## Cross-review synthesis — findings no single reviewer could reach

### S1. The domain review's fix RESOLVES the architecture review's circularity

The architecture review found the Phase 1.5 gate circular: its only input is a
venue quote tape, which requires the venue read path (signing, REST, slugs, WS)
that Phase 2 delivers — and Phase 2 is gated on Phase 1.5. It proposed moving
the read-only transport ahead of the gate.

The domain review, independently, found the gate measures the wrong quantity
altogether. With a 0.01 tick the best ask cannot exceed 0.99, so `1.00 - ask`
is >= 0.01 **by construction on every crossing**, and the fee it is netted
against is provably <= 6% of that gap (`fee/gap = Theta * p`). The gate as
specified **returns GO mechanically and cannot fail**. The question that
actually decides the strategy is the rate at which "METAR running max >= X"
implies "settled CLI max >= X" — the break-even is 97.6% at a 0.97 entry and
99.06% at 0.99.

**These combine.** The settlement-alignment study needs **no venue data at
all** — archived METAR against the `NwsClimateDay` records already in the
catalog, N in the thousands, runnable today. Making it the PRIMARY gate both
fixes the tautology and dissolves the circularity: the programme's GO/NO-GO no
longer depends on data that requires the blocked phase to collect. The quote
tape becomes a secondary capturability measurement, not the gate's sole input.

This is the single most valuable outcome of the review and neither reviewer
could have reached it alone.

### S2. Two reviewers converge on "the plan measures magnitude, never probability"

Domain: the plan computes gap size and never computes the failure rate that
gap is being paid to accept. Stack: the gate has no pre-registered numeric
threshold, no sample floor, and selects its horizon after seeing the data —
the plan enforces walk-forward discipline structurally for the Tier-2 *model*
(REQ-ALPHA-05) and then grants the *premise* exactly the freedom it forbids
the model. Same defect, two vocabularies.

### S3. The null hypothesis was applied unevenly, in both directions

Stack review: NautilusTrader 1.231.0 already ships `ed25519_signature` (typed
in `nautilus_pyo3.pyi:519`), a rate-limited `HttpClient` with `Quota`, and a
`WebSocketClient` carrying heartbeat, idle-timeout and reconnect-backoff
configuration. The plan's Phase 2 layout hardcodes `httpx` and an unnamed
websocket library and adds an Ed25519 dependency. CLAUDE.md's null hypothesis
was discharged for `BinaryOption`/`LiveExecutionClient`/`FeeModel` and never
applied to signing, HTTP or WS — the three modules carrying new dependencies.

Architecture review, opposite direction: the plan declines the native durable
order/position cache (`cache.database`) on the grounds that "nothing in this
plan generates a workload they solve" — false the moment an order exists, and
it means an idempotency key cannot survive a crash inside the 30-second signing
window it exists to protect.

**Net: the adapter shrinks (build venue-specific logic on native transport
primitives) and the persistence story grows (durable order state is required).**

### S4. A correction to the merged findings this session produced

`TRADING_ENABLEMENT_FINDINGS.md` §A3 states the native fee model "is
documented as taker-only and unable to express a maker rebate". The
architecture review verified this is false of `PolymarketFeeModel`
(`adapters/polymarket/fee_model.py:224-324`, `common/parsing.py:352-395`),
which implements exactly the `qty * rate * p * (1-p)` curve AND returns a
negative `Money` for `LiquiditySide.MAKER`. The taker-only property belongs to
`ProbabilityPriceFeeModel`, a different class, genuinely absent from this
build. Two objects, one conclusion, wrong reasoning.

The decision to write our own `FeeModel` survives on different grounds: the
shipped model infers the rebate as a category-derived *share of the taker fee*
with no injection seam for a flat `-0.0125` coefficient, and the whole
`adapters/polymarket` package is unimportable without `py_clob_client_v2`.
A3, REQ-VENUE-11 and the §7 row must be rewritten with the true reason.

---

## Required amendments before Phase 2 entry

### From the security review

- **SEC-1** The trading kill-gate has no freshness dimension. `_derive_state`
  is a pure read of latch booleans; staleness is a PUSH latch set by a
  watchdog that must be *called*. An ingest process killed uncleanly after a
  successful poll leaves the gate OPEN forever. The trading check must require
  OPEN **and** observation age within a required-no-default bound **and** a
  writer liveness heartbeat. Test: kill the writer uncleanly, assert refusal.
- **SEC-2** `SettlementGate._load_site` serves from an in-instance cache whose
  safety invariant is enforced in a different module. A second reader (the
  strategy) caches the first result forever, so a mid-session BLOCK is never
  observed — falsifying `require_open`'s own "never rely on an earlier
  decision" promise at the exact call site it was built for. Specify the read
  path, not just the call.
- **SEC-3** Credential defence closes only the channel `health.py` already
  closes. Open: httpx header logging at DEBUG (`BREEZY_LOG_LEVEL` is operator
  settable), unscrubbed tracebacks, core dumps, no key-file mode check (the
  repo enforces 0600 for a *health snapshot* but not for the private key),
  and no rule barring fixtures from loading a real key.
- **SEC-4** Key rotation is a runbook bullet, not a requirement — while
  Phase 5.1 mandates committing captured venue traffic to a git-tracked
  evidence directory redacting only the signature, **not `X-PM-Access-Key`**.
- **SEC-5** The no-idempotency branch is the one branch the plan never states.
  The hazard is not the retry, it is the AMBIGUOUS OUTCOME: a timed-out POST
  leaves an unknown position, and the disambiguation surface (order status) is
  itself `[UNKNOWN]` G2. Needs a `SUBMIT_AMBIGUOUS` state that latches a
  per-market halt, plus fault-injection in Phase 4 — not a Tier-1 gate
  criterion evaluated after 20 real trades.
- **SEC-6** REQ-RISK-08 (kill switch cancels working orders) and Phase 4.6
  ("every POST path raises when the flag is unset") **contradict** — cancel is
  a POST. Clearing the enablement flag, the first act of any incident, would
  disable the cancel path. Replace the verb rule with a POST-kind allowlist:
  cancel and read-only always permitted, exposure-increasing requests gated.
- **SEC-7** Phase 5.1 has no authorization mechanism distinct from D4, and no
  loss bound under the interpretation the plan did not model: if the venue
  applies the price to the other leg, a 0.02 limit becomes 0.98 and the loss
  bound flips from `price*qty` to `(1-price)*qty` — up to 49x.
- **SEC-8** The compliance escalation threshold ("only if it prohibits
  automated flow") is too narrow for a CFTC DCM, and REQ-DATA-04 starts
  recording venue market data in Phase 1 before the terms governing storage
  and redistribution have been read.

### From the architecture review

- **ARC-1** No durable order/position ledger. `cache.database=None` means every
  order-id link and lifecycle event dies with the process; recovery rests on
  `generate_missing_orders=True`, which SYNTHESIZES orders it cannot match.
  Adopt the native cache backing or specify a durable idempotency/order
  journal with a written recovery procedure.
- **ARC-2** The Phase 1.5 circularity — superseded by S1 above.
- **ARC-3** `t_cross` is undefined; the obvious reading (METAR valid time)
  produces a false GO. See DOM-2.
- **ARC-4** No dependency-direction rule is stated, and all four new packages
  land on both ends of the existing `ingest` <-> `runtime` cycle.
- **ARC-5** The `alpha/` vs `features/` split is arbitrary and Tier-1 alpha has
  a third home in `strategy/` — three homes for one concern, with the edge/fee/
  rounding math near-certain to be re-derived and drift.
- **ARC-6** Process topology, failure domains and restart-mid-position are
  unaddressed. The ingest path is deliberately fail-fast; fail-fast is
  catastrophic for a node holding open positions, and nothing states which
  wins. Also: REQ-RISK-02 is stated too weakly — the store confines to the
  CONSTRUCTING thread (composition, main thread, before the loop runs), not
  "the event-loop thread". Those coincide today only by accident.
- **ARC-7** Phase 3 is half-parallel at best: 3.3's alert denominator needs
  Phase 2.4 market discovery; 3.4 "end to end" needs Phase 4.1; 3.5/3.8 need
  venue settlement records. Split into 3a (parallel) and 3b (after Phase 2).
- **ARC-8** Phase 1.7 must widen from a threading contract to a design-constraint
  pack covering durability/idempotency, fee-rate sourcing, the replay record-type
  constraint, and the `DataType` metadata trap.

### From the domain review

- **DOM-1** *(the headline)* Phase 1.5 measures a quantity that is >= 0.01 by
  tick construction and nets a fee provably <= 6% of it. **The gate cannot
  fail.** Restructure into (a) a settlement-alignment study producing a Wilson
  lower bound on the METAR->CLI hit rate per city and per degree-of-clearance
  stratum — no venue data, runnable now — as the GO/NO-GO, and (b) a
  capturability study on depth-weighted fill price and printed trades.
  GO requires both.
- **DOM-2** `t_cross` keyed on METAR *valid* time grants the analysis 5-45
  minutes of information the strategy will not have. Redefine as Breezy's own
  receipt timestamp.
- **DOM-3** Kelly is a category error at P=1 (f\* = 1.0, nothing clamps) and
  numerically unstable near it: f\* traverses 0 -> 0.81 over a two-point move
  in an unmeasured parameter. Replace with cap-and-depth sizing on the measured
  lower bound; ban p = 1.0 from sizing math by test.
- **DOM-4** Six METAR->CLI divergence modes are unenumerated and unpriced,
  against a total failure budget of ~1-2%: C->F rounding at 1 F granularity
  (31.1 C = 87.98 F, and the trigger lives exactly where the conversion
  decides), intraday METAR CORs revising a temperature downward after Breezy
  has traded, LST-vs-clock window, METAR group choice vs the CLI's ASOS
  5-minute derivation, station identity vs the venue's named station, and the
  venue's CLI-vs-METAR tiebreak.
- **DOM-5** REQ-ALPHA-03's strict `>` permits trading at one basis point of
  edge. Needs a required-no-default minimum-edge floor.
- **DOM-6** REQ-DATA-04 records top-of-book only, but Phase 1.5.3 and
  REQ-ALPHA-03 both require slippage at the intended size. **Amend the tape
  schema to L2 depth plus venue and receipt timestamps BEFORE Phase 1.1 starts
  recording** — discovering this at 1.5.1 costs another 14 calendar days.
- **DOM-7** "Beats the market-implied baseline" is a tautology for a
  deterministic tier — the market-implied probability IS the price paid.
  Replace with hit-rate lower bound vs volume-weighted break-even.
- **DOM-8** >=200 settlements is under-powered above ~0.985 entries, which is
  where the depth is; make it a function of realized entry price.
- **DOM-9** Market trading hours appear nowhere in the register. The daily max
  occurs 14:00-16:00 local = 17:00-19:00 ET for LAX/SFO; if trading closes
  before then, Tier 1 is a three-city strategy.
- **DOM-10** No adverse-selection reasoning. The 0.97 offer may exist because
  the seller knows the trigger is wrong; the strategy would preferentially
  trade exactly the markets where its own trigger is defective.

Opportunity findings (raise the ceiling rather than fix a defect):

- **DOM-11** The **post-preliminary-CLI window** is the largest missed trade.
  REQ-ALPHA-02's "unobserved is not absent" reasoning is correct and *expires*
  at ~16:00 local, when the preliminary publishes a full-day max rather than a
  lower bound. That window is two-sided, determinate, runs on ingestion that is
  already live, and its risk — the preliminary->final revision rate — is
  measurable today from the existing catalog. It plausibly dominates Tier 1.
- **DOM-12** Minimum-temperature contracts are ignored entirely — the exact
  mirror, determined by ~08:00 local, shorter capital lock, and every
  supporting requirement is shared.
- **DOM-13** No programme-level ROI feasibility arithmetic before committing to
  63 blocking requirements. Central estimate from the worked example is tens of
  dollars per day gross. 30 minutes of arithmetic, before Phase 1.5.1.

### From the stack review

- **STK-1** *(empirically demonstrated)* The autouse socket blocker patches
  Python's `socket` only. A `nautilus_pyo3` client reached the OS and returned
  ECONNREFUSED while Python's socket was blocked. `respx` is equally void
  against it. With no venue sandbox, an ordinary `uv run pytest -q` can
  transmit a signed order while every gate reads green.
- **STK-2** Phase 1.7 targets the wrong invariant — see ARC-6.
- **STK-3** The null hypothesis was never applied to signing/HTTP/WS — see S3.
- **STK-4** The Phase 1.5 gate has no pre-registered threshold, no sample
  floor, and post-hoc horizon selection — see S2.
- **STK-5** mypy `files` is necessary but not sufficient: `strict = true` plus
  `disallow_subclassing_any` will reject `FeeModel`, `Strategy` and the live
  client subclasses on day one. The repo deliberately keeps such waivers
  module-scoped; pre-declare them rather than reaching for a package-wide one.
- **STK-6** Several exit criteria are self-reported counters produced by the
  code under test — including "zero POSTs" and "zero safety-gate violations".
  Prove them from the venue side (fetch the account's order list, assert
  empty). Also: no `venue_live` marker exists, and `--strict-markers` requires
  registering it in the same change.
- **STK-7** No fixture strategy. Needs a loopback fake venue echoing raw header
  bytes (the `allow_socket` marker currently has zero users), contract tests
  over captured payloads, and slug property tests that assert REJECTION, not
  only round-trip — a round-trip-only property is satisfied by identity.
- **STK-8** The Phase 4.7 replay harness is infeasible at the implied volume:
  including any weather record forces one-shot for the whole run, dragging
  ~100M quotes into memory. Shard by `(city, climate-day)` and enforce a
  per-run cap at config time.
- **STK-9** `import-linter` should move from cosmetic to required — it is the
  enforcement mechanism for ARC-4's missing layering rule and for the "never
  import the .com adapter" ban.
- **STK-10** `nautilus-trader~=1.231` is loose while the entire `contract/`
  suite pins measured 1.231.0 behaviour. Pin `==`.
- **STK-11** Several work items have no natural RED test (all of Phase 0; the
  proposed mypy RED test requires deleting its own stub to go green).
  Restructure or label explicitly as non-TDD operational items.
- **STK-12** `Decimal` vs `float` at the money boundary is unaddressed.
  `Price(0.51, 2)` accepts a float and rounds silently; the strict-`>` edge
  comparison can return a different boolean in binary float than in `Decimal`,
  at the tick boundary where the volume is.

---

## Ruling

Amend before implementation. The amendment set is large but almost all of it is
document work plus two cheap studies that need no venue access, no credentials
and no calendar wait:

1. The **settlement-alignment study** (DOM-1) — historical METAR vs the
   `NwsClimateDay` records already in the catalog. This becomes the primary
   GO/NO-GO and dissolves the Phase 1.5 circularity.
2. The **preliminary->final revision-rate study** (DOM-11) — same data, already
   in the catalog, and it prices the window that may dominate the whole tier.
3. The **ROI feasibility arithmetic** (DOM-13) — 30 minutes.

Any of the three can return a NO-GO for free, before a line of adapter code.
That is the correct next action.
