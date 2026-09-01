# ROI Feasibility Arithmetic (G-02 / DOM-13)

Date: 2026-08-26.
Scope: programme-level order-of-magnitude arithmetic before committing to the
remaining trading build.

## Verdict

**NO-GO for committing to the downstream adapter / settlement / execution build
on the current worked-example economics.**

This is not a NO-GO on continuing the free studies or the read-only tape work.
It is a NO-GO on treating the deterministic Tier-1 edge as programme-level ROI
until the live tape proves substantially better fill size, breadth, or gap
magnitude than the worked example supports.

At 100 contracts per city-day cluster, the scenario range is roughly:

| Scenario | Net per day | Capital locked | Dominant sensitivity |
|---|---:|---:|---|
| Pessimistic, run first | about **$3/day** | about **$300** | fill price / slippage after the book prices out |
| Central | about **$9/day** | about **$500** | one tick of slippage on a small gross edge |
| Optimistic | about **$15/day** | about **$500** | whether five cities and no slippage are actually reachable |

The result scales linearly with contract count only until depth, risk caps, or
capital lock-up bind. The current repo does not contain measured depth at the
intended size, an operator capital ceiling, or a resolved fee schedule, so a
larger dollar claim would be invented rather than evidenced.

## Exact Inputs Restated From The Plan

Quoted-from-repo-artifact inputs:

- Breezy is targeting daily-temperature real-money orders on Polymarket.us
  weather markets, initially through a deterministic intraday path and later a
  model-priced path (`docs/plans/TRADING_ENABLEMENT_PLAN.md:24-26`).
- The plan carries **63** `BLOCKS-FIRST-TRADE` requirements and **76** total
  requirements (`docs/plans/TRADING_ENABLEMENT_PLAN.md:183-190`).
- Tier 1 is deterministic: once the observed running max has cleared the strike,
  `P=1` is arithmetic, not estimated (`docs/plans/TRADING_ENABLEMENT_PLAN.md:114`).
- The running max is only a lower bound: Tier 1 may buy the P~1 side, but must
  refuse the P~0 side (`docs/plans/TRADING_ENABLEMENT_PLAN.md:115` and
  `docs/plans/TRADING_ENABLEMENT_PLAN.md:494-495`).
- Edge must be fee- and slippage-inclusive at intended size, checked after tick
  rounding, with strict `>` (`docs/plans/TRADING_ENABLEMENT_PLAN.md:116` and
  `docs/plans/TRADING_ENABLEMENT_PLAN.md:496-497`).
- The central premise is a persistent, fee-surviving gap between physical
  determination and market pricing, measured from tape
  (`docs/plans/TRADING_ENABLEMENT_PLAN.md:121` and
  `docs/plans/TRADING_ENABLEMENT_PLAN.md:288-296`).
- The Tier-1 evaluation bar requires positive PnL at **1.5x stressed fees**:
  taker `0.09` rather than `0.06`
  (`docs/plans/TRADING_ENABLEMENT_PLAN.md:487-490`).
- The review says this ROI arithmetic is one of the studies that can return a
  NO-GO before any adapter code (`docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md:269-276`).
- DOM-13 says the central estimate from the worked example is "tens of dollars
  per day gross" before committing to 63 blocking requirements
  (`docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md:216-218`).

The plan sections requested do **not** state a measured account size, intended
contract quantity, market close, realized ask, slippage, or opportunity-cost
floor. Those are therefore not quoted facts below; they are assumptions or
unknowns.

## Fee And Slippage Constraints

Quoted-from-repo-artifact fee inputs:

- The parser documents the venue fee as `fee = theta * C * p * (1 - p)`, with
  `theta` coming from `feeCoefficient`, not from Nautilus flat `maker_fee` /
  `taker_fee` fields (`src/breezy/adapters/polymarket_us/parsing.py:28-49`).
- `FEE_SCHEDULE_STATUS_UNKNOWN` is the recorded state today; the only unlocking
  state is `KNOWN`, and nothing writes it in this slice
  (`src/breezy/adapters/polymarket_us/parsing.py:189-201`).
- `assert_fee_schedule_known` fails closed and states that `maker_fee` and
  `taker_fee` hold placeholder `Decimal(0)`, not verified zero fees
  (`src/breezy/adapters/polymarket_us/parsing.py:223-255`).
- Instrument parsing records `feeCoefficient` in `info` and sets
  `fee_schedule_status` to `UNKNOWN`
  (`src/breezy/adapters/polymarket_us/parsing.py:1054-1067`).

Fee handling in this note:

- `theta = 0.09` is quoted from the Tier-1 stressed-fee bar and used
  pessimistically. Bias: unfavorable to ROI.
- `theta = 0.06` is quoted from the current plan's unstressed taker assumption
  and used centrally. Bias: neutral relative to the old plan, but unsafe until
  the fee schedule is live-resolved.
- `theta = 0.00` is used only as the optimistic lower-bound sensitivity. Bias:
  favorable to ROI; it is not a claim that the venue is free.
- The verdict firms up only when the live fee-schedule discovery item closes and
  marks the schedule known.

Measured and quoted depth inputs:

- `OrderBookDepth10` carries ten levels per side
  (`src/breezy/adapters/polymarket_us/parsing.py:124-126`).
- The parser documents that `book_open_510636.json` has 12 bid levels and
  14 offer levels, so truncation is real
  (`src/breezy/adapters/polymarket_us/parsing.py:561-568`).
- Measured in this run with
  `jq '.marketData | (.bids|length), (.offers|length)' docs/evidence/venue/polymarket_us/raw/book_open_510636.json`:
  **12** bids and **14** offers.
- `DepthTruncation` records how many levels were dropped and joins to the depth
  record by timestamp; it does not preserve the dropped prices or sizes
  (`src/breezy/adapters/polymarket_us/tape_records.py:427-443`).
- Runtime warning text states slippage measured from this tape is valid only up
  to the tenth level (`src/breezy/adapters/polymarket_us/data.py:857-864`).

## Formula

For a buy of `C` YES contracts at average fill price `p`, assuming binary
settlement at 1:

```text
gross_edge = C * (1 - p)
venue_fee  = theta * C * p * (1 - p)
net_edge   = gross_edge - venue_fee - explicit_slippage_cost
capital_locked = C * p
daily_net = net_edge * reachable_cities * clusters_per_city_day
```

In the scenario table, `p` is already the post-slippage average fill price, so
there is no separate slippage subtraction line. That prevents double-counting
slippage while still making the fill-price sensitivity visible.

## Assumptions Used For The Arithmetic

Assumed input register:

| Input | Value | Bias direction | Why used |
|---|---:|---|---|
| Contract unit `C` | 100 contracts | Neutral as a scaling unit; favorable if misread as executable size | The repo has no intended size or capital ceiling. Reporting per 100 contracts avoids inventing bankroll. |
| Clusters per city-day | 1 | Unfavorable to ROI | REQ-RISK-04 says adjacent strikes on one city-day are one bet (`docs/plans/TRADING_ENABLEMENT_PLAN.md:144`). |
| Pessimistic reachable cities | 3 | Unfavorable to ROI | DOM-9 says LAX/SFO may be unreachable if trading closes before 17:00-19:00 ET (`docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md:198-200`). |
| Central / optimistic reachable cities | 5 | Favorable to ROI | GO LIVE says all five current sites are NYC/SFO/MIA/MDW/LAX (`docs/plans/archive/GO_LIVE_PLAN.md:17-20`). |
| Pessimistic fill `p` | 0.99 | Unfavorable to ROI | Represents the market nearly pricing P=1 or two 0.01 ticks of adverse fill versus a 0.97 example. |
| Central fill `p` | 0.98 | Mildly unfavorable to ROI | Represents a one-tick adverse fill on a 0.97 offer. |
| Optimistic fill `p` | 0.97 | Favorable to ROI | Preserves the 0.97 worked-example neighborhood without slippage. |
| Capital turn | about once per day | Unfavorable to ROI | Daily-temperature contracts cannot be recycled repeatedly within the same city-day cluster; the plan also treats settlement/reconciliation as daily gates. |

Unknowns not filled in:

- Operator capital ceiling and risk caps.
- Intended trade size.
- Actual depth-weighted fill price at intended size.
- Market trading hours.
- Actual live fee coefficient / fee schedule state.
- Whether the quoted gap persists across enough market-days to be a strategy.

## Scenarios

### 1. Pessimistic Scenario First

Inputs:

- 3 reachable cities.
- 100 contracts per reachable city-day.
- Average fill `p = 0.99`.
- Fee coefficient `theta = 0.09`.
- One cluster per city-day.

Arithmetic:

```text
gross per city = 100 * (1 - 0.99) = about $1
fee per city   = 0.09 * 100 * 0.99 * 0.01 = about $0.09
net per city   = about $0.90
daily net      = 3 * about $0.90 = about $3
capital locked = 3 * 100 * 0.99 = about $300
```

Dominant sensitivity: fill price / capturability. At this edge size, two ticks
of adverse fill nearly consume the trade before fees matter. If depth beyond the
tenth level is needed to fill intended size, this scenario may still be too
favorable because the retained tape does not show the dropped prices or sizes.

### 2. Central Scenario

Inputs:

- 5 reachable cities.
- 100 contracts per reachable city-day.
- Average fill `p = 0.98`.
- Fee coefficient `theta = 0.06`.
- One cluster per city-day.

Arithmetic:

```text
gross per city = 100 * (1 - 0.98) = about $2
fee per city   = 0.06 * 100 * 0.98 * 0.02 = about $0.10
net per city   = about $1.90
daily net      = 5 * about $1.90 = about $9
capital locked = 5 * 100 * 0.98 = about $500
```

Dominant sensitivity: one tick of slippage. Moving from 0.97 to 0.98 removes
about one dollar per 100 contracts per city, which is far larger than the fee
movement across the plausible `theta` range near `p` close to 1.

### 3. Optimistic Scenario

Inputs:

- 5 reachable cities.
- 100 contracts per reachable city-day.
- Average fill `p = 0.97`.
- Fee coefficient `theta = 0.00` as an upper-bound sensitivity only.
- One cluster per city-day.

Arithmetic:

```text
gross per city = 100 * (1 - 0.97) = about $3
fee per city   = 0
net per city   = about $3
daily net      = 5 * about $3 = about $15
capital locked = 5 * 100 * 0.97 = about $500
```

Dominant sensitivity: whether this is executable at size. This is the best case
in the table and still only reaches the "tens of dollars per day gross" critique
at the 100-contract unit. Larger sizes scale linearly only if the live book has
enough depth inside the retained ten levels and risk caps permit the exposure.

## Sensitivities Pending G-15 And DOM-9

### G-15 / Fee Schedule Discovery

At the optimistic worked-example price `p = 0.97`, five cities, and 100 contracts
per city-day, daily net moves roughly:

| Theta | Daily net |
|---:|---:|
| 0.00 | about $15 |
| 0.03 | about $15 |
| 0.06 | about $14 |
| 0.09 | about $14 |

At the central fill `p = 0.98`, five cities, and 100 contracts per city-day,
daily net moves roughly:

| Theta | Daily net |
|---:|---:|
| 0.00 | about $10 |
| 0.03 | about $10 |
| 0.06 | about $9 |
| 0.09 | about $9 |

Conclusion: fee schedule resolution is mandatory for correctness, but near
`p` close to 1 it is not the largest economic sensitivity. Across `theta =
0.00..0.09`, the daily result moves by about **$1/day per 500 contracts of
five-city exposure** at `p = 0.97`, and less at `p = 0.98`.

### DOM-9 / Three Cities Versus Five

Using the central fill `p = 0.98`, `theta = 0.06`, and 100 contracts per
city-day:

```text
3-city daily net = about $6
5-city daily net = about $9
```

Conclusion: DOM-9 moves the result by about **two-thirds** in relative terms
because 5 cities / 3 cities is the whole breadth multiplier. In absolute terms,
at the 100-contract unit, the movement is only a few dollars per day.

### Slippage / Capturability

At 100 contracts per city:

```text
p = 0.97 gross = about $3 per city
p = 0.98 gross = about $2 per city
p = 0.99 gross = about $1 per city
```

Conclusion: a single 0.01 tick of adverse average fill costs about **$1 per
100 contracts per city**, before fees. This dominates the fee uncertainty and
can dominate the city-count uncertainty if intended size pushes past visible
depth. Because the venue can publish more than ten levels and Breezy's native
tape retains only ten, any fill requiring levels beyond ten is currently
unpriced.

## Decision Boundary

This arithmetic does not prove the strategy impossible. It proves the current
worked-example economics are too small to justify proceeding into the 63
blocking-requirement build as though ROI were established.

To reverse the NO-GO, the later evidence must show at least one of:

- materially larger measured gap than `0.97..0.99` implies;
- depth-weighted fills at materially larger size without walking the book;
- five-city reachability after DOM-9 trading-hours resolution;
- an operator capital/risk ceiling large enough that the linear scaling remains
meaningful after depth and cluster caps;
- a stated opportunity-cost floor that these measured daily dollars clear.

Until then, the programme should continue only on free falsification and
irreversible tape capture, not on irreversible downstream trading build.
