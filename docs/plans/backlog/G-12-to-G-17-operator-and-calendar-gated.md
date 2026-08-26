# G-12 .. G-17 — Operator-gated and calendar-bound items

These items cannot be executed autonomously. Each is recorded with its exact
unlock condition so it is tracked as BLOCKED, never as a failure or an
oversight. Nothing here may be worked around, and no agent may unlock any of
them.

---

## G-12 — Resolve `MARKET_SLUG_KEY` against the live venue

**Unlock:** operator opens the three-lock credential gate
(`BREEZY_VENUE_LIVE=1` AND `BREEZY_ALLOW_CREDENTIALED_PYTEST=1` AND
`--venue-live`), which requires D1 (KYC).

**Why it matters more than it looks.** `MARKET_SLUG_KEY = "marketSlug"` is an
unresolved venue guess, and every routing decision in the recorder rests on it.
If it is wrong, the recorder captures nothing **and looks exactly like a quiet
market** — an indistinguishable silent failure on the one item whose data
cannot be recovered later.

**Steps once unlocked:** issue one authenticated GET against a live weather
market, capture the raw response body to `docs/evidence/venue/polymarket_us/`
with the access key redacted (SEC-4), and read the actual slug field name off
the real payload. Assert it in a contract test over the captured payload.

**Do not:** infer the key from the vendored SDK snapshot. That snapshot is
evidence, not authority, and this repo's standing lesson is that green tests
against `.invalid` hosts prove nothing about the live venue.

---

## G-13 — Gating live run of the recorder

**Unlock:** same three-lock gate; depends on G-12.

**Current state, verbatim from PROGRESS.md:** "**No live run has happened.**
Zero authenticated calls, zero live-network verification; every venue host in
every test is `.invalid`. 2401 green tests do not establish that a real frame
reaches parquet. This is exactly the standing lesson of this repo."

**Exit criterion:** one real frame, from the real venue, written to parquet and
read back **by a separate process** — matching the discipline already used for
the NWS substrate, where `read_raw_products` deliberately does not re-verify so
that an unchecked round-trip would prove nothing.

**Also prove from the venue side, not from our own counters (STK-6):** fetch
the account's order list and assert it is empty. "Zero POSTs" self-reported by
the code under test is not evidence.

---

## G-14 — Start continuous capture under systemd

**Unlock:** G-12 and G-13 green, plus G-10 (disk alerting) landed.

Model the unit on the existing NWS collector unit. **Do not** start capture
before disk alerting exists: one day's tape file is unbounded under
`rotation_mode=SCHEDULED_DATES`, and a full disk silently stops the one
collection that cannot be backfilled.

Start on the earliest possible calendar day. Every day not captured is
permanently lost, and G-16's 14-day clock does not start until this does.

---

## G-15 — Fee schedule discovery

**Unlock:** operator authorises a live authenticated probe.

`maker_fee`/`taker_fee` are `Decimal(0)` and `assert_fee_schedule_known`
(`parsing.py:223`) raises `FeeScheduleUnknownError` rather than assume zero —
correctly fail-closed. The formula `fee = theta * C * p * (1 - p)` is documented
at `parsing.py:28-49` but `theta` is `[UNKNOWN]`; `feeCoefficient` is stored
verbatim in `info` and never written through to the fee fields.

Until this is closed, **every net-edge number in the programme is a sensitivity
range, not a point estimate** — including G-02's ROI arithmetic. This is a
`polymarket-us-discovery` live-probe question, not a coding task.

---

## G-16 — Accumulate >= 14 days of joined tape

**Unlock:** calendar. Fourteen days after G-14 starts. Not compressible.

The weather series is retroactively available; the market price series is not
and never will be, because Polymarket.us weather markets did not exist before
2026. No vendor can backfill them.

---

## G-17 — Phase 1.5 premise falsification GO / NO-GO

**Unlock:** G-16 complete. **NO-GO stops the programme.**

Restructured per DOM-1, because the original gate measured a quantity that is
`>= 0.01` by tick construction and nets a fee provably `<= 6%` of it — **the
gate as written could not fail.** Replaced by two studies, and GO requires
**both**:

**(a) Settlement-alignment study** — a Wilson lower bound on the METAR->CLI hit
rate, per city and per degree-of-clearance stratum. Uses the asymmetric
formulation only if G-03's pre-registration cleared adversarial review. Sample
floor is a function of realized entry price (DOM-8): >= 200 settlements is
under-powered above ~0.985 entries, which is where the depth is.

**(b) Capturability study** — depth-weighted fill price and printed trades from
the captured tape. Valid only to level ten: the venue emits more levels than
`OrderBookDepth10` retains, and `DepthTruncation` records how many were dropped,
not what they were.

**Threshold discipline:** compare against a volume-weighted break-even, never
against the market-implied baseline — for a deterministic tier the
market-implied probability IS the price paid, so "beats the market" is a
tautology (DOM-7).

A NO-GO here is a successful outcome of the process. It costs the programme far
less than discovering the same thing after building the execution client.
