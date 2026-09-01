# Capture specification — Gate 0 for every observation-lock strategy

Status: OPEN. Authored 2026-08-31 by the strategy-architect loop, iteration 1.
Supersedes nothing. Consumers: `running_extreme_lock`, `cli_settlement_print_lock`,
`lagged_anomaly_tail`.

## Why this document exists

Three observation strategies have PASSED their settlement-side gates on archive
data and NONE has an economic result. The blocker is not strategy design and not
harness code — it is that Breezy holds **no order-book data inside any of their
trigger windows**. Every strategy document written from here terminates at
"gate PASS, economics unknown" until this specification is executed.

Total captured book history today:

    5 instruments, NYC + MIA only, one calendar day (2026-08-30),
    6 minutes 9 seconds: 16:05:44Z -> 16:11:53Z

Overlap with `running_extreme_lock`'s trigger window: **zero station-days.**
Overlap with `cli_settlement_print_lock`'s: **zero station-days.**

This is the binding constraint on the entire programme. It is a DATA problem,
not a modelling problem.

## The number that decides everything

For the open-tail lock at margin 0 — the cell where the strategy concentrates
its entries — the measured Wilson-95%-lower settlement probability is
**0.996829** (N=9736, `docs/evidence/observation_lock_falsification_2026-08-31.md`
section 2). Against the venue's own fee function `theta * C * p * (1 - p)`
(`adapters/polymarket_us/fees.py`, theta = 0.06):

| Ask | Net edge (cents/contract) | Return on capital |
|---|---|---|
| 0.950 | +4.398 | +4.63% |
| 0.960 | +3.453 | +3.60% |
| 0.970 | +2.508 | +2.59% |
| 0.980 | +1.565 | +1.60% |
| 0.990 | +0.623 | +0.63% |
| 0.995 | +0.153 | +0.15% |
| **0.99663** | **0.000** | **break-even** |

**Break-even ask at margin 0 is 0.99663.** Above it the strategy loses money no
matter how well it is implemented. Below it the fee function is remarkably kind:
because `p * (1 - p)` collapses near the boundary, a near-certain contract costs
almost nothing to trade. The venue's fee structure is *structurally favourable*
to this strategy family. That is the single most encouraging fact in the
programme and it is worth stating plainly.

Everything therefore reduces to ONE empirical question:

> After an NWS CLI preliminary prints, do asks on the open-tail buckets that
> observation has ALREADY satisfied sit below 0.99663, and at what depth?

Nobody knows. It is unanswerable from held data.

## Gate 0-PRE — the parser must be able to SEE a one-sided book (BLOCKING)

**Do this before any capture. Capture without it records nothing on the target
books.**

`_parse_levels` raises `VenuePayloadError` when a side is empty
(`adapters/polymarket_us/parsing.py:528-529`), and `parse_book_levels` calls it
for BOTH sides (`:571-572`). An empty bid side therefore discards the ENTIRE
frame — including the ask side, which is the only side these strategies trade.

The market state every observation-lock strategy targets is precisely
"thin-or-empty bid, leftover ask". That state is currently **structurally
unrecordable**. Reported on the existing capture: 247 `VenuePayloadError`s and
zero depth rows across the five one-sided slugs.

This reframes Gate 0. The problem was never only the clock window. A perfectly
timed 14-day capture, run today, would still produce zero rows on exactly the
books that decide the strategy — and would then be misread as "no size, no
edge, strategy dead" when it is really instrument blindness.

**Requirement:** the depth path must record a one-sided book, preserving the
populated side, rather than rejecting the frame. A missing bid is a legitimate
venue state here, not a malformed payload. Whatever guarantees `parse_book_top`
relies on for a two-sided quote must be re-stated for the one-sided case rather
than silently dropped.

## Gate 0A — the SCREENING probe (cheap, do this AFTER 0-PRE)

Do NOT begin a 14-day capture before answering the screening question. If asks
sit at or above break-even, H1 and its whole family are dead and the full
capture is wasted effort.

- **Question:** on a station-day where a preliminary has printed a running max
  H, what is the ask (and its depth) on open-tail buckets with floor X <= H?
- **Minimum viable sample:** 3 station-days, any 3 of the 5 stations, sampled
  across the 19:00-01:00Z window at >= 1-minute cadence.
- **Instruments:** open **UPPER**-tail buckets ONLY (`gteXf`). Interior buckets
  are excluded — dead on MDW/NYC/SFO (Wilson upper on the revision rate exceeds
  0.05). The lower tail (`ltXf`) is ALSO excluded, and an earlier draft of this
  spec was wrong to include it: `H` is a running MAXIMUM, so it only ever rises.
  A `< X` bucket is therefore never locked by an observation — and if `H >= X`
  already, it settles NO. Only the upper tail locks. `decision.py` is right to
  skip any bucket with `upper_f is not None`.
- **Kill rule, pre-registered:** if the median ask on already-satisfied
  open-tail buckets is >= 0.99663 across the sample, the post-preliminary
  open-tail lock is REJECTED on economics and no further capture is authorised
  for it. Record the result either way; a negative here saves 14 days.
- **Cost:** three evenings of attended capture. No systemd unit required.

## Gate 0B — the FULL economic capture (only if 0A passes)

- **Instruments:** the five settlement stations' open-tail daily-high buckets.
- **Data type:** L2 `OrderBookDepth10` (NOT top-of-book). Depth is load-bearing:
  entry is VWAP-priced across the ladder and clipped to real depth
  (`running_extreme_lock/decision.py:124-160`), so a top-of-book capture cannot
  test the strategy that was actually built.
- **Windows, in clock terms** — stated so a capture plan can be written against
  them, which no prior brief did:
  - **19:00-01:00Z daily** — the preliminary window. Serves
    `running_extreme_lock`.
  - **05:00-13:00Z daily** — the final-print window. Serves
    `cli_settlement_print_lock`.
- **Cadence:** every book change, or >= 1 Hz snapshot if deltas are unavailable.
- **Duration:** >= 14 station-days per window (K2's minimum).
- **Settlement truth:** already held. NWS CLI archive, venue-portable to Kalshi.
  No venue dependency for the settlement side.

## What this unblocks, precisely

With 0B in hand, `running_extreme_lock` becomes the FIRST Breezy strategy
capable of an admissible ROI number, because it is the first that needs no
synthetic input of any kind:

| Input | Forecast strategies | Observation strategies |
|---|---|---|
| Market prices | real captured book | real captured book |
| Settlement price | real NWS observation | real NWS observation |
| Forecast | **SYNTHETIC — no ingestion exists** | **not required at all** |

The three forecast strategies (`forecast_mispricing`,
`calibration_mean_reversion`, `forecast_revision`) cannot produce an admissible
ROI under any amount of tuning until forecast ingestion (P3) exists, because a
synthetic forecast is an assumed input on the signal path. The observation
strategies have no such dependency. **The route to an empirically observed
positive ROI runs through the observation family, and only through it.**

## The shipped config currently refuses this entire strategy

Before any capture result can be interpreted, note that the live defaults
contradict the arithmetic above:

| Knob | Default | Effect on the region this spec targets |
|---|---|---|
| `min_model_edge` | 0.04 (`weather_common/risk.py:100`, `running_extreme_lock/config.py:113`, gated `risk.py:411`) | At p_model 0.9968 an ask of 0.970 gives edge 0.0268 < 0.04 -> REFUSED. Requires ask <= ~0.957. |
| `transaction_cost_prob` | 0.015 (`risk.py:116`, `config.py:119`) | ~25x the real fee at p=0.99, where the true cost is ~0.0002. |

So the strategy as shipped would refuse every fill this document's break-even
table describes. That is not necessarily wrong — a large `min_model_edge` is a
defensible way to demand only deeply stale asks — but it must be a DECISION,
not an inherited default. Resolve it before reading any capture result, or a
null result will be misattributed to the market.

Relatedly: the venue tick is 0.01, so an ask of 0.995 does not exist. Tradable
asks in this region are 0.99, 0.98, 0.97. The 0.995 row of the break-even table
is illustrative only.

## Standing constraints (unchanged, restated so this spec is self-contained)

- Long-only. `allow_short = False`. The bid side is genuinely unexecutable
  (median top-of-book bid 0.3 contracts).
- No reconstructed tapes of expired markets. A backfilled or synthesised ladder
  is NOT a substitute for capture; it fabricates the exact input that
  depth-aware sizing exists to test honestly.
- Edge priced against the ask at the size actually taken, never the midpoint,
  never top-of-book.
- The two operator-reserved controls (maximum daily budget; maximum per
  position) have no values and must not be invented here.

## Dependency

Both 0A and 0B require operator-gated venue access (PROGRESS.md G-13/G-14).
That is the gating item. It is not a build-side decision and this document does
not attempt to route around it.
