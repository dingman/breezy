# G-12 .. G-17 — Operator-gated and calendar-bound items

These items cannot be executed autonomously. Each is recorded with its exact
unlock condition so it is tracked as BLOCKED, never as a failure or an
oversight. Nothing here may be worked around, and no agent may unlock any of
them.

---

## G-12 — Resolve `MARKET_SLUG_KEY` against the live venue

**Unlock:** ~~operator opens the three-lock credential gate~~ — **CORRECTED
2026-09-01: this gate is already open and is NOT the blocker.** Credentials are
present (`~/.config/breezy/polymarket.env`: `POLYMARKET_US_KEY_ID`,
`POLYMARKET_US_SECRET_KEY_FILE`), D1/KYC is satisfied, and the gate has been
opened for **four** read-only smoke runs (one 2026-08-25, three 2026-08-30).
**SUPERSEDED SAME DAY by diagnosis — read this, not the line above.** All four
runs did return `Connectivity verdict: FAIL`, but the verdict is
`authenticated_ok AND quotes_delivered > 0 AND node_failure is None`
(`scripts/venue/polymarket_us_auth_smoke.py:1363`) — it fails on the QUOTE
count, not on auth. **Authenticated connectivity IS proven:**
`READONLY_AUTH_SMOKE_2026-08-30T154900+0000.md:34-38` shows step B
(`GET /v1/portfolio/positions`, authenticated) -> **200**, with the
path+query-signed variant -> **401** as a discriminating negative control, and
step D (deliberately stale -120s) -> **200**, i.e. the venue does not enforce a
signing window. **G-12 IS RESOLVED:** the 2026-08-25 run value-matched the key
against a configured slug and recorded `marketData.marketSlug`
(`READONLY_AUTH_SMOKE_2026-08-25T221131+0000.md:2144`) — this is a parsed
payload, NOT log text. The `MARKET_SLUG_KEY = "marketSlug"` leaf guess
(`data.py:160`) is CORRECT under a `marketData` parent, which the nested lookup
at `data.py:616-622` already handles.

**Clock skew is REFUTED as a cause.** The "56593 ms host clock offset" in the
report headers is a measurement artifact: `_clock_offset_ms`
(`polymarket_us_auth_smoke.py:890-907`) compares `time.time()` *at call time*
against the *first* response's `Date` header, and is called at checkpoint time,
so it measures elapsed run duration. Real signing-time offset is logged at
`:49164` — **779 ms**, against a 15 000 ms guard that never fired.

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

**Current state (CORRECTED 2026-09-01).** The previously-quoted line "**No
live run has happened.** Zero authenticated calls" is **false**: four
authenticated read-only smoke runs were executed against
`https://api.polymarket.us` and are archived under
`docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_*.md`. The four `FAIL` verdicts are real but mean
something narrower than they read: the formula fails on `quotes_delivered > 0`,
not on auth (see G-12 above). **Venue frames HAVE reached the Nautilus
DataEngine** — the 2026-08-25 run delivered **11 QuoteTicks from 11 frames**
with 1 instrument loaded (`READONLY_AUTH_SMOKE_2026-08-25T221131+0000.md:2150-2152`).
Only the *parquet* clause survives.

**THE ACTUAL OPEN DEFECT (was never diagnosed until 2026-09-01):** the
2026-08-30 run loaded **60 instruments**, received **268 WS frames** (218
`market_data`, 50 `error`) and delivered **0 QuoteTicks** (`:49085-49089`,
`:70-73`) — a 0% conversion rate where 08-25 got 100%. Two differences to test:
60 instruments vs 1, and the 08-30 runs subscribed to **2026-08-31** slugs
(`tc-temp-nychigh-2026-08-31-...`) while running on 08-30, i.e. **next-day
markets**. One-sided books explain at most 35 of the 218 frames (183 carry
`marketData.bids[0]`), so `parse_book_top`'s one-sided refusal
(`parsing.py:606-633`) is NOT a sufficient explanation.

**Caveat on the ~872 `marketSlug` hits in the 2.8 MB file:** those specific
occurrences are Breezy's own log text. Do not cite that file for slug
resolution — cite the 08-25 run, which resolved it by value-matching. 2401 green tests do not establish that a real frame
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
