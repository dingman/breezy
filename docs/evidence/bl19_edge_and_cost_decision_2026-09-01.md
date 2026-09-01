# BL-19 — `min_model_edge` and `transaction_cost_prob`: derivation and decision

Date: 2026-09-01. Scope: DESIGN DECISION ONLY. No source file was modified by
this document. Read-only analysis against
`src/breezy/strategy/weather_common/risk.py`,
`src/breezy/strategy/running_extreme_lock/{config,decision,strategy}.py`,
`src/breezy/adapters/polymarket_us/fees.py`, and
`scripts/analysis/price_conditional_settlement_analysis.py`.

Evidence consumed: `observation_lock_falsification_2026-08-31.md`,
`h2_lower_tail_rejected_2026-09-01.md`, `first_in_window_capture_2026-09-01.md`,
`docs/strategies/FEEDBACK_FOR_GROK_2026-08-31.md` ss3/5, `docs/core/PROGRESS.md`
BL-19 / BL-21 / BL-13 / BL-10 / P6.

Every number below is either (a) recomputed here from a formula in source, and
labelled DERIVED, or (b) quoted from a named evidence file with its denominator,
and labelled MEASURED (elsewhere). Nothing here is a new measurement.

---

## 1. The problem, restated with the arithmetic corrected

`RiskLimits.min_model_edge = 0.04` (`risk.py:100`) and
`RiskLimits.transaction_cost_prob = 0.015` (`risk.py:116`) are inherited from
mid-probability forecast strategies. `running_extreme_lock` trades a
near-certain regime: MEASURED (`observation_lock_falsification_2026-08-31.md`
s2) Wilson-95% LOWER bound on `p_hold` at margin 0 is 0.996829 (N=9736).

### 1.1 Correction to BL-19's own worked example

BL-19 states the strategy "needs ask <= ~0.957", from `0.9968 - 0.04`. That
omits the cost term. Source (`running_extreme_lock/decision.py:296-297`)
computes

    edge = model_p - vwap_ask_p - cfg.transaction_cost_prob
    if edge < cfg.min_model_edge: return None

and `risk.py:421` re-applies `abs(edge) < limits.min_model_edge` to that same
already-cost-netted number. So the shipped requirement is

    ask <= p - min_model_edge - transaction_cost_prob
         = 0.996829 - 0.04 - 0.015
         = 0.941829                                            [DERIVED]

On a 0.01 tick that is **ask <= 0.94**, not 0.957. The shipped config demands a
5.3-point mispricing on a contract the model calls 99.68% certain. BL-19's
conclusion (the region is refused entirely) is correct; its threshold is 1.6
points too generous and should be corrected in the backlog entry.

### 1.2 The venue fee is concave and vanishes exactly where this strategy trades

Fee model, from source (`adapters/polymarket_us/fees.py:186`, formula documented
at `:84-88`): `fee = theta * C * p * (1 - p)`, `theta` read per market from
`instrument.info[FEE_COEFFICIENT_KEY]`. There is deliberately no module-level
default (`fees.py:90-92`). `theta = 0.06` is the documented worked example and
the analysis default (`scripts/analysis/price_conditional_settlement_analysis.py:42`).

Fee in probability units per contract, `theta = 0.06`  [DERIVED]:

| p | `0.06 * p * (1-p)` | ratio vs the shipped 0.015 |
|---:|---:|---:|
| 0.50 | 0.015000 | 1.00x (identical) |
| 0.90 | 0.005400 | 2.8x smaller |
| 0.97 | 0.001746 | 8.6x smaller |
| 0.99 | 0.000594 | 25.3x smaller |
| 0.99663 (break-even) | 0.000201 | 74.5x smaller |

Two facts fall out that BL-19 does not state:

1. **`0.015` is exactly `theta * 0.25` at `theta = 0.06` — the MAXIMUM of the
   fee curve.** The shipped constant is the worst-case fee at p = 0.50 and
   therefore contains, numerically, **zero slippage allowance**, despite the
   inline comment "fees + expected slippage in prob units" (`risk.py:116`).
   Treat the comment as aspirational: there is no slippage buffer in the system
   today. This matters for s4 — swapping the constant for the fee function does
   not "remove slippage", because none was ever there, but it also does not
   supply the slippage the comment promises.
2. BL-19's "~0.0002 at p = 0.99" and "roughly 25x smaller" are inconsistent
   with each other. 0.000201 is the fee at p = 0.9966 (the break-even price);
   at p = 0.99 the fee is 0.000594, which is the figure the 25x ratio matches.
   Both are right at their own p; the backlog entry pairs them wrongly.

### 1.3 Break-even, verified

`break_even_executable_price` (`scripts/analysis/price_conditional_settlement_analysis.py:157`)
solves `x + theta*x*(1-x) = p`. Closed form: `0.06x^2 - 1.06x + p = 0`, so
`x = (1.06 - sqrt(1.1236 - 0.24p)) / 0.12`.

At p = 0.996829: `x = (1.06 - sqrt(0.884361)) / 0.12 = (1.06 - 0.940405)/0.12
= 0.996627`.  [DERIVED] This reproduces the 0.99663 given in the brief.

Break-even by margin, using the MEASURED Wilson-lower table  [DERIVED]:

| margin_f | p (Wilson-95% lower) | break-even ask | highest representable ask below it (0.01 tick) |
|---:|---:|---:|---:|
| 0 | 0.996829 | 0.996627 | 0.99 |
| 1 | 0.998244 | 0.998132 | 0.99 |
| 4+ | 0.999418 | 0.999381 | 0.99 |

**The tick grid, not the knob, defines the decision set.** At every margin the
break-even lands between 0.99 and 1.00, so the only tradable prices are 0.99,
0.98, 0.97, … Any threshold expressed to four decimal places is theatre: this
strategy has three or four distinguishable decisions, not a continuum.

Note `MispricingContract.tick_size` (`weather_common/bucket_contract.py:41-43`)
is per-instrument and its own comment warns "the captured universe carries more
than one tick size". BL-19's "tick is 0.01" is an observed fact about the
captured instruments, not a venue invariant; the derivation below is written in
ticks, and the shipped scalar is its value at a 0.01 tick.

---

## 2. Knob 1 — `transaction_cost_prob`: make it a function, but only as a fee

### Decision: SPLIT it. `cost = venue_fee(ask) + slippage`, not one scalar.

A single scalar is being asked to carry two quantities with opposite behaviour
as `p -> 1`:

- the **venue fee**, `theta*p*(1-p)`, which is measurable, concave, and
  vanishes in the near-certain regime;
- **slippage / execution uncertainty**, which does NOT vanish. On a 0.01-tick
  book one adverse tick is 0.01 of probability — at the break-even price that
  is **50x the fee** (0.01 vs 0.000201). Near certainty, cost is dominated by
  tick granularity and depth, not by fees.

Collapsing those into one number is what makes the constant wrong in both
directions at once: 25x too large as a fee at p = 0.99, and zero as a slippage
allowance everywhere.

### Recommended form

Two pure functions, placed beside `edge_after_costs` in
`src/breezy/strategy/weather_common/risk.py` (that module already owns the
cost-netted-edge contract, and `edge_after_costs` already takes `cost` by
injection, so **its signature does not change** — only what the caller passes):

```
def venue_fee_prob(*, executable_price: float, fee_coefficient: float) -> float
def trade_cost_prob(*, executable_price: float, fee_coefficient: float,
                    slippage_prob: float) -> float
```

`venue_fee_prob` returns `fee_coefficient * executable_price * (1 - executable_price)`;
`trade_cost_prob` returns `venue_fee_prob(...) + slippage_prob`. Both pure,
side-effect free, property-testable (non-negative; symmetric about 0.5; maximal
at 0.5; monotone decreasing on [0.5, 1]). `executable_price` is the **VWAP ask
actually consumed**, not the level-0 tick — for `running_extreme_lock` that is
`vwap_ask_p` (`decision.py:287`), matching the existing edge line at `:296`.

Values it produces (`fee_coefficient = 0.06`, `slippage_prob = 0`): the table in
s1.2 — 0.015000 / 0.005400 / 0.001746 / 0.000594 at p = 0.50 / 0.90 / 0.97 / 0.99.

### `fee_coefficient` must be read per instrument and fail closed

Do NOT add a config field defaulting to 0.06. `fees.py:90-92` is explicit that
there is deliberately no module-level default and no fallback, because "a market
whose coefficient we could not parse raises rather than trading free". A
strategy-side default would reintroduce exactly that fallback on the gating
path. `MispricingContract` does not currently carry the coefficient; the
narrowest fix is to add `fee_coefficient: float | None` to
`weather_common/bucket_contract.py`, populate it at `on_start` from the cached
instrument's `info[FEE_COEFFICIENT_KEY]` (the same key `_fee_coefficient` reads,
`fees.py:224`), and **refuse the signal when it is `None`** — same posture as
`FeeScheduleUnknownError`. An unknown fee schedule is a no-trade, never a
free trade.

### `slippage_prob`: keep it a scalar, set it to one tick, and label it unmeasured

`running_extreme_lock` already walks the ask ladder and re-prices at the VWAP of
the clipped size (`decision.py:247-296`), so the *depth* component of slippage
is priced. The residual is quote-age drift (a quote may be up to
`stale_quote_minutes = 15.0` old, `risk.py:115`) and queue/partial-fill risk.
Breezy has never observed a live fill, so the honest value is unmeasured. Ship
the fail-closed placeholder — **one tick, 0.01** — and record it as a
measurement obligation: on the first live fills, compare realised fill price
against the quoted ask at decision time and re-derive.

---

## 3. Knob 2 — `min_model_edge`: is a flat absolute floor the right SHAPE?

### 3.1 The four candidates

**(a) Flat but lower.** Cheap, no new surface, reuses the existing double gate
(`decision.py:297` and `risk.py:421`). Weakness: an absolute edge floor means
different things at different prices — for fixed edge, return is `edge/ask`, so
a flat floor is lenient on cheap contracts and strict on expensive ones. In the
near-certain regime `ask ~ 1`, so absolute edge and return nearly coincide and
the objection is mostly theoretical *for this strategy*. It stays live for the
mid-probability strategies that share the knob name.

**(b) Margin-conditional `min_model_edge`.** REJECT. The margin conditioning is
already carried where it belongs: `model_p` is looked up from the measured
margin-keyed Wilson-lower table (`decision.py:222`, `_model_p_for_margin`;
design rationale in `running_extreme_lock/config.py:20-30` and
`FEEDBACK_FOR_GROK_2026-08-31.md` s3 item 7). Making the *floor* margin-
conditional too would apply the same conditioning twice — once raising `p` and
again raising the bar `p` must clear — which is not a stronger gate, it is an
uninterpretable one. The prior review's conclusion was that
`model_probability` must be margin-conditional. It is. That work is done.

**(c) Break-even-plus-buffer anchored on 0.99663.** REJECT AS STATED, ACCEPT
THE MATH. Algebraically, "edge = p - ask - cost >= floor" and "ask <=
break_even(p) - buffer" are the same rule written in probability space and in
price space; there is no new information in the restatement. The specific
proposal is worse than the general one because **anchoring on the constant
0.99663 hard-codes margin 0's p**: at margin 1 the break-even is 0.998132 and at
margin 4 it is 0.999381 (s1.3), so a fixed anchor silently mis-prices every
non-zero margin. Take from (c) the correct primitive — `break_even_executable_price`
already exists (`scripts/analysis/price_conditional_settlement_analysis.py:157`)
— and evaluate it per signal, not as a constant.

**(d) Return terms, `edge / ask >= r_min`.** REJECT AS THE PRIMARY GATE. It is
the economically meaningful quantity, and near p = 1 it is numerically almost
identical to (a) (dividing by `ask ~ 0.98` changes the threshold by ~2%). But it
is actively dangerous for cheap contracts: an ask of 0.02 against a claimed
model p of 0.9968 gives a ~4800% return and clears any return floor by orders of
magnitude. That is precisely the "pennies read as free certainty" failure the
first-capture evidence names
(`first_in_window_capture_2026-09-01.md`: measured asks 0.01-0.21 on unfired
tails, n=1824). A return floor supplies no upper sanity bound and would rank a
data error as the best trade in the book.

### 3.2 Recommendation: (a) — a flat absolute floor, re-derived as a MODEL-BIAS buffer

Keep the shape. Change what the number MEANS and therefore its value.

Once `cost` carries the real fee and an explicit slippage term (s2), everything
`min_model_edge` still has to absorb is **error in `p` itself**. Sampling error
is already priced — the table is a Wilson-95% LOWER bound. What remains is
POPULATION bias, and there is direct evidence it is non-zero:

`first_in_window_capture_2026-09-01.md` states the margin table was built by
sweeping every integer floor in `[H-5, H]` (a documented proxy;
`observation_lock_falsification_2026-08-31.md`, "What this evidence does NOT
establish"), while the venue lists exactly one `gte<N>f` per city-day, MEASURED
4-8F ABOVE the day's actual on 5 station-days. Its conclusion: "the table
describes a population the strategy cannot trade."

The direction of that bias is arguable and should be stated as an argument, not
a measurement: a fired trigger means the day cleared a rung the venue placed
above the forecast, i.e. an unusually hot day relative to expectation. The loss
event is a DOWNWARD revision of a printed preliminary — a data/QC event
(MEASURED pooled downward rate 0.21%, 20/9736) whose one fat-tail instance in
the sample was an unflagged bad preliminary (MDW 2021-12-30, `MAXIMUM 55` ->
final 39, 1/9736 = 0.0103%). Anomalous prints and anomalous heat are not
obviously independent, so the fired-trigger population may carry a HIGHER
bad-print rate than the swept population. The buffer must cover that
enrichment, not just the sampling error the Wilson bound already covers.

### 3.3 The arithmetic that fixes the value

A YES bought at `a` is EV-neutral when the true probability equals
`a + fee(a)`. The **tolerated total failure rate** is therefore `1 - a - fee(a)`,
and the headroom over the Wilson-implied failure rate (1 - 0.996829 = 0.003171)
is the model-bias budget  [DERIVED, theta = 0.06, margin 0]:

| ask | fee(ask) | net edge `p - ask - fee` | return `edge/ask` | break-even p | tolerated total failure rate | enrichment over measured 0.317% |
|---:|---:|---:|---:|---:|---:|---:|
| 0.99 | 0.000594 | 0.006235 | 0.63% | 0.990594 | 0.94% | 3.0x |
| 0.98 | 0.001176 | 0.015653 | 1.60% | 0.981176 | 1.88% | 5.9x |
| 0.97 | 0.001746 | 0.025083 | 2.59% | 0.971746 | 2.83% | 8.9x |
| 0.94 (today's requirement) | 0.003384 | 0.053445 | 5.69% | 0.943384 | 5.66% | 17.9x |

Read the last column as: "how many times worse than measured can the true
downward-print rate be before this trade loses money?" A 0.99 entry survives a
3x enrichment; 0.98 survives ~6x. Given that the population shift is *known to
exist* and *unquantified*, and given a single -16F unflagged print already sits
in the sample, a 3x cushion is not enough and a 6x cushion is defensible.
**Require ask <= 0.98.**

Translating to the knob, with `cost = fee(vwap_ask) + 0.01` slippage  [DERIVED]:

| ask | edge after fee AND slippage (margin 0) | clears 0.005? |
|---:|---:|---|
| 0.99 | 0.996829 - 0.99 - 0.000594 - 0.01 = **-0.003765** | no |
| 0.98 | 0.996829 - 0.98 - 0.001176 - 0.01 = **+0.005653** | yes |
| 0.97 | 0.996829 - 0.97 - 0.001746 - 0.01 = **+0.015083** | yes |

So **`min_model_edge = 0.005`** for `running_extreme_lock`. Check it is stable
across the margin table (it must not accidentally admit 0.99 at high margin):
at margin 4, p = 0.999418, ask 0.99 gives `0.999418 - 0.99 - 0.000594 - 0.01 =
-0.001176` — still refused. The rule reduces, at every margin and at a 0.01
tick, to a single legible sentence: **buy at 0.98 or better, never at 0.99.**

### 3.4 Companion refusal (recommended, and a TIGHTENING)

The floor has no upper sanity bound; s3.1(d) shows why that is dangerous.
Recommend an **implausible-discount refusal** on the same signal path: refuse
when `ask < break_even(p, theta) - max_discount`, with `max_discount = 0.10`
(ten ticks at the observed tick size), i.e. refuse a fired-tail ask at or below
0.89. Rationale: on a tail the observation has ALREADY satisfied, a market
quoting 0.21 or 0.02 is disagreeing with us by 78-98 points; the overwhelmingly
likelier explanations are an instrument-mapping error, a stale/degenerate book,
or a trigger bug — not edge. This converts Breezy's single most expensive
plausible failure (buying pennies while believing 99.7%) into a counted refusal
plus an alert. It cannot loosen anything, and it is the only new gate proposed
here.

---

## 4. Blast radius

### 4.1 These knobs are already per-strategy; the `RiskLimits` values are only defaults

Verified in source. Each strategy declares its own field and passes it
explicitly into `RiskLimits`:

| Strategy | config field | passed at |
|---|---|---|
| `forecast_mispricing` | `config.py:87`, `:94` | `strategy.py:197`, `:204` |
| `forecast_revision` | `config.py:100`, `:107` | `strategy.py:207`, `:214` |
| `calibration_mean_reversion` | `config.py:103`, `:110` | `strategy.py:216`, `:223` |
| `running_extreme_lock` | `config.py:113`, `:119` | `strategy.py:280`, `:287` |

So `risk.py:100` / `risk.py:116` bind only bare `RiskLimits()` constructions —
tests and harnesses (e.g. `tests/unit/test_weather_common_risk.py:129`, whose
comment pins "below default min_model_edge=0.04"). **Recommendation: do not
change `risk.py:100` or `risk.py:116`.** Changing them would silently move every
unpinned harness baseline while changing no shipped strategy's behaviour. The
narrowest scoping is already available: edit
`running_extreme_lock/config.py:113` and `:119` only.

### 4.2 What changing each knob would do to the three forecast strategies

**`min_model_edge` lowered globally (0.04 -> 0.005):** a 8x loosening of the
only pure-edge gate for three strategies that price at level 0 with no depth
walk (verified: no `vwap`/`ask_ladder` reference in
`forecast_mispricing/decision.py`, `calibration_mean_reversion/decision.py`,
`forecast_revision/decision.py`). Those strategies would begin taking trades on
edges smaller than a single 0.01 tick — i.e. inside their own price
granularity. **This is a loosening that must not happen. Do not touch it
globally.**

**`transaction_cost_prob` replaced by the fee function globally:** the fee
function is *below* 0.015 at every `p != 0.5` (s1.2), so this is a loosening
everywhere, largest exactly where a forecast strategy is most confident (at
p = 0.90 it frees 0.0096 of edge — nearly a full tick). Worse, since those three
price at level 0 only, the 0.015 constant is the closest thing they have to a
slippage allowance, however accidental (s1.2 fact 1). Migrating them without
first giving each an explicit `slippage_prob` would remove a buffer they
implicitly rely on.

There is also a definitional problem: `forecast_revision/decision.py:331`
computes `edge = abs(unabsorbed) - cfg.transaction_cost_prob`, where
`unabsorbed` is a forecast-revision magnitude, not a price-anchored edge. A fee
that is a function of the *executable price* is not even well-defined at that
call site without first choosing the ask. That strategy needs its own
treatment, not a mechanical substitution.

**Narrowest scoping, recommended:** introduce `venue_fee_prob` /
`trade_cost_prob` as shared pure helpers in `weather_common/risk.py`, but adopt
them at ONE call site — `running_extreme_lock/decision.py:272` and `:296`. Leave
the other three strategies on their scalar `cfg.transaction_cost_prob = 0.015`
and `min_model_edge = 0.04` until each is re-derived on its own evidence.
Per PROGRESS P2/P3, Breezy ingests no forecast data at all, so those three
cannot be re-derived today anyway; changing their gates now would only move
inadmissible numbers.

### 4.3 Relationship to P6

P6 ("wire boundary-conditional preliminary-revision cost into sizing;
`min_model_edge=0.04` is plausibly smaller than the revision cost it covers")
is about the FORECAST strategies, where 0.04 may be too small. This decision
concerns the OBSERVATION strategy, where it is far too large. Both can be true —
that is the argument for per-strategy values and against a shared global one.
Nothing here pre-empts P6.

---

## 5. Interaction with BL-21 — does this change how a null capture is read?

**No, and the point deserves sharpening.**

`running_extreme_lock/decision.py:217-219` returns `None` when
`running_f < tail_floor`, BEFORE any edge, cost, or ask arithmetic runs. On the
first in-window capture the trigger fired 0/4 (H1) and 0/4 (H2)
(`first_in_window_capture_2026-09-01.md`, `h2_lower_tail_rejected_2026-09-01.md`).
Therefore:

1. **No value of either knob would have changed that outcome.** Zero orders were
   formed, so zero `edge_below_minimum` refusals were possible. BL-19 is not the
   cause of the 0/4, and fixing BL-19 will not produce trades.
2. **The refusal counter cannot distinguish the two cases.** A pre-signal `None`
   never reaches `evaluate_order` and so is never counted (`RiskManager._refuse`
   docstring, `risk.py:370-390`; the same class of gap BL-10 records for
   `forecast_mispricing`'s pre-check). "Zero refusals" is therefore evidence of
   nothing on its own.
3. **An ask-vs-break-even comparison remains meaningless before the trigger
   fires**, exactly as `first_in_window_capture_2026-09-01.md` and
   `h2_lower_tail_rejected_2026-09-01.md` already pre-register. `p = 0.996829`
   is conditional on the observation having satisfied the tail. Comparing a
   0.02 ask on an unreached tail against a 0.99663 break-even would read a
   correctly-priced non-event as 99.7% certainty. BL-21's kill criterion —
   trigger rate < 0.20 over captured station-days — stays the only admissible
   test.

What this recommendation DOES change is the *interpretability of the next
capture that does fire*: with the decision set reduced to "0.98 or better", a
fired trigger produces a legible outcome (traded / refused with the ask on
record) rather than a config artifact. The missing measurement is named
explicitly in s7.

Applies equally to BL-13 (`cli_settlement_print_lock`, the new lead strategy).
Its trigger is designed to fire on most station-days, so it is the strategy that
will actually exercise these knobs — but it trades interior buckets after the
final print, whose p (MEASURED `p_stable` 99.989%, 9105/9106) and whose ask
distribution are both different. **Do not copy these values into BL-13.**
Re-derive them from the print-lock's own table when it is built.

---

## 6. Recommended values to ship

Scope: `src/breezy/strategy/running_extreme_lock/config.py` ONLY. No change to
`risk.py:100`, `risk.py:116`, or any other strategy's config.

| Knob | Current | Recommended | Derivation | Strategies affected |
|---|---|---|---|---|
| `min_model_edge` (`running_extreme_lock/config.py:113`) | 0.04 | **0.005** | Model-BIAS buffer only, once fee and slippage are priced separately. At margin 0 it admits ask <= 0.98 (edge +0.005653) and refuses 0.99 (edge -0.003765); stable at every margin in the table. 0.98 tolerates a 1.88% true failure rate = 5.9x the MEASURED 0.317% Wilson-implied rate, covering the known-but-unquantified population shift from the proxy floor sweep. (s3.3) | `running_extreme_lock` only |
| `transaction_cost_prob` (`running_extreme_lock/config.py:119`) | 0.015 | **removed as a cost constant; replaced by `trade_cost_prob(...)`** | 0.015 is exactly `theta*0.25`, the fee MAXIMUM at p = 0.50, and is 25.3x the true fee at p = 0.99 and 74.5x at break-even. Cost splits into a measurable concave fee and a non-vanishing execution term. (s1.2, s2) | `running_extreme_lock` only |
| new `slippage_prob` (`running_extreme_lock/config.py`) | n/a | **0.01** (one tick at the observed tick size), labelled UNMEASURED | No live fill has ever been observed. One adverse tick is the smallest representable execution loss; the depth component is already priced by the VWAP walk (`decision.py:283-296`). Fail-closed placeholder pending measurement. | `running_extreme_lock` only |
| new `fee_coefficient` source | n/a | **per-instrument, from `instrument.info[FEE_COEFFICIENT_KEY]`; refuse when absent** | `fees.py:90-92` — no module default, no fallback; a config default of 0.06 would reintroduce the fallback the adapter refuses. (s2) | `running_extreme_lock` only |
| new `max_discount_from_break_even` | n/a | **0.10** (recommended, a tightening) | Implausible-discount refusal: on a FIRED tail, an ask 10+ ticks below break-even implies a 10-98 point disagreement, likelier a mapping/data/trigger fault than edge. Captured unfired-tail asks were 0.01-0.21 (n=1824). (s3.4) | `running_extreme_lock` only |
| `RiskLimits.min_model_edge` (`risk.py:100`) | 0.04 | **unchanged, 0.04** | Binds only bare `RiskLimits()` (tests/harnesses). Lowering it would loosen three level-0-priced forecast strategies below their own tick granularity. (s4.1, s4.2) | none |
| `RiskLimits.transaction_cost_prob` (`risk.py:116`) | 0.015 | **unchanged, 0.015**; fix the misleading inline comment | The constant contains no slippage; the comment claims it does. Comment-only correction. (s1.2) | none |
| `forecast_*` / `calibration_*` values | 0.04 / 0.015 | **unchanged** | Level-0 pricing, no depth walk, no slippage term, and no forecast data ingested (PROGRESS P2/P3) — nothing to re-derive against today. See P6. (s4.2, s4.3) | none |

Not touched, deliberately: maximum daily trading budget and maximum notional per
position remain unset and operator-reserved. `allow_short` stays `False`
(the bid side is unexecutable; `risk.py:117-137`).

**Net behavioural change if shipped:** `running_extreme_lock` moves from "needs
ask <= 0.94" (unreachable) to "needs ask <= 0.98" (reachable in principle),
plus a new refusal for implausibly cheap fired-tail asks. It does NOT become
more likely to trade in the next capture, because the binding constraint is the
trigger rate, not the edge gate (s5).

---

## 7. What would falsify this recommendation

1. **Fired-trigger asks never reach 0.98.** The decisive missing measurement:
   the ask distribution on tails the observation HAS satisfied. Breezy has never
   observed one. If fired-tail asks cluster at 0.99 or 1.00, the honest
   conclusion is that the region is untradeable at any buffer that respects the
   population shift — and BL-19's answer becomes "the refusal was right, for the
   wrong reason." This recommendation does not assert the strategy is
   profitable; it asserts the current numbers cannot answer the question.
2. **Measured slippage exceeds one tick.** If live fills come in worse than
   quoted-ask + 0.01, `slippage_prob` rises and 0.98 stops clearing the floor
   (at slippage 0.02, ask 0.98 gives edge -0.004347) — the recommendation
   collapses to "0.97 or better", or to no trade.
3. **The fired-trigger downward-print rate exceeds ~1.8%.** That is the
   break-even failure rate at ask 0.98 (s3.3). Any post-hoc sample of fired
   triggers showing worse than that kills the 0.98 rule directly.
4. **`theta` is not 0.06 on the traded instruments.** Every fee figure here
   scales linearly in `theta`. It is a per-market value (`fees.py:90`); 0.06 is
   the documented worked example. A materially larger `theta` moves break-even
   down and the whole table with it.
5. **Tick size is not 0.01 on the traded instruments.** `bucket_contract.py:41-43`
   warns the captured universe carries more than one. At a 0.001 tick, prices
   between 0.99 and break-even become representable and the entire
   "0.98 or better" conclusion is replaced by a finer grid.
6. **The margin table's population bias is measured and found small.** The 5.9x
   cushion is chosen because the bias is known to exist and is unquantified. If
   forward capture shows the venue's listed floors behave like the swept floors,
   the buffer can honestly shrink and 0.99 comes back into scope.
7. **A depth-aware re-derivation shows the 0.98 level is never more than a few
   contracts deep.** The VWAP walk would then clip size to something too small
   to matter, making the whole gate moot for a different reason.

---

## 8. Addendum — `cli_settlement_print_lock` (BL-13), the lead strategy

Added 2026-09-01 after coordinator review. Sections 1-7 above scoped their
recommendation to `running_extreme_lock`; that strategy fired 0/4 on the first
in-window capture and is no longer the lead. The 05:00-13:00Z capture will test
BL-13's economics, so BL-13 needs its own derivation.

Worked from the design spec `docs/strategies/breezy_strategy_cli_settlement_print_lock.md`
(ss5, 8, "Plug-in contract", "Sizing", "Look-ahead rule") ONLY. Nothing under
`src/breezy/strategy/cli_settlement_print_lock/` was read or written — that
package is being created concurrently.

### 8.1 What `model_p` should be for an interior bucket after a final print

The spec fixes the definition: `model_probability` is `1 - p_revise_out_of_B`,
not a forecast CDF (spec s8, and the `SignalDecision` field note in the plug-in
contract). The measurement that estimates it is MEASURED `p_stable` = 99.989%
(9105/9106) — first final -> last pre-settlement value unchanged
(`observation_lock_falsification_2026-08-31.md` s1).

**Wilson 95% lower bound at that N**  [DERIVED, z = 1.959963984540054]:

| basis | k/n | point | Wilson-95% lower | break-even ask |
|---|---|---:|---:|---:|
| pooled, 5 stations | 9105/9106 | 0.9998902 | **0.9993782** | 0.9993385 |
| single station, 0 failures | 1820/1821 (as 0-fail) | 1.0000000 | **0.9968959** | 0.9966984 |
| single station, the 1 failure | 1819/1820 | 0.9994505 | **0.9968942** | 0.9966968 |

**Is a single scalar defensible here? Yes in SHAPE — but it must be the
PER-STATION bound (~0.9969), not the pooled 0.99938.** Three reasons, in
descending strength:

1. **`p_stable` measures value IDENTITY, which is strictly stronger than bucket
   MEMBERSHIP.** The metric counts a station-day as stable only if the printed
   value itself is unchanged. An interior bucket survives any revision that
   stays inside its bounds, so for a bucket wider than 1F a ±1F revision can
   leave the value changed but the bucket held. `p_stable` therefore
   UNDERSTATES bucket survival. There is a conditioning variable analogous to
   margin — the printed value's distance to the nearest bucket edge, in F — but
   conditioning on it can only RAISE `model_p`. Omitting it is conservative,
   which is the opposite of the tail case, where omitting margin conditioning
   over-priced the cell the strategy traded most
   (`FEEDBACK_FOR_GROK_2026-08-31.md` s3 item 7). **That asymmetry is the whole
   answer to "what replaces `_model_p_for_margin`": nothing has to, for v1.**
   Edge-distance conditioning is a later refinement that buys accuracy, not
   safety, and it needs the venue's actual bucket widths — which I could not
   determine without reading the captured instrument list.
2. **The binding constraint is sample size per site, not meteorology.** At
   N ≈ 1821 station-days, even ZERO observed failures certifies only 0.996896 at
   95%. No amount of stability in one station's history can certify past
   ~99.69% on this denominator. The pooled 0.99938 is available only if the five
   stations are exchangeable — and they are not obviously so: the CLI products
   are issued by five different WFOs (CLINYC / CLIMIA / CLIMDW / CLILAX /
   CLISFO, spec s2 table), with independent QC practice. Pooling across offices
   is an assumption, not a measurement. Ship the per-site bound; fail closed.
3. **`p_stable` does not contain two of the spec's own loss conditions.** Spec
   s4 lists (2) the 11:00 ET METAR-review path leaving the traded bucket and
   (3) station/climate-day mis-mapping (LST vs civil clock under DST). Neither
   is in the 9105/9106 denominator, which is computed from NWS record history
   alone. The shipped `model_p` must be read as "p_stable-derived only", with
   those two hazards UNMEASURED and handled structurally (spec's pure-function
   gates 1, 3, 5), not priced.

**Recommended `model_p` for v1: 0.9969** (per-station Wilson-95% lower, the
worse of the two per-site rows above, rounded down). Note this lands within
0.0001 of `running_extreme_lock`'s margin-0 bound (0.996829) — a coincidence of
DENOMINATOR, not of physics: the tail bound is hazard-limited (20 real downward
events in 9736), the print-lock bound is sample-size-limited (≈0 events in
1821). Do not read the agreement as corroboration.

The spec's suggested `min_stable_prob: float = 0.97` (plug-in contract) is a
floor on the looked-up value, not the value itself; 0.9969 clears it and the
field stays non-binding. Keep it.

### 8.2 Break-even, and the decision set on a 0.01 tick

At `model_p = 0.9968959`, `theta = 0.06`: break-even ask = **0.996698**
[DERIVED, same closed form as s1.3]. As with the tail case, break-even lands
between 0.99 and 1.00, so the tick grid gives at most three distinguishable
entries.

Per-station basis (`model_p = 0.9968959`)  [DERIVED]:

| ask | fee | edge, fee only | edge, fee + 1-tick slippage | return | tolerated total failure rate | cushion over the 0.3104% Wilson-implied rate |
|---:|---:|---:|---:|---:|---:|---:|
| 0.99 | 0.000594 | +0.006302 | **-0.003698** | 0.64% | 0.941% | 3.0x |
| 0.98 | 0.001176 | +0.015720 | **+0.005720** | 1.60% | 1.882% | 6.1x |
| 0.97 | 0.001746 | +0.025150 | +0.015150 | 2.59% | 2.825% | 9.1x |

Pooled basis, for contrast (`model_p = 0.9993782`, Wilson-implied failure
0.0622%)  [DERIVED]: ask 0.99 gives edge +0.008784 fee-only, **-0.001216** after
one tick of slippage, and a 15.1x cushion; ask 0.98 gives +0.008202 after
slippage and 30.3x.

**Recommendation: `min_model_edge = 0.005`, same cost treatment as s2. Admits
ask <= 0.98. Refuses 0.99 and above.** The same 6x-cushion standard applied to
the tail case in s3.3 selects the same entry price here, for a different
reason: there it was population bias, here it is the per-site denominator plus
the two unmeasured loss conditions in s8.1(3).

**Say plainly what is doing the work, because it is not the model.** On the
per-station basis, 0.99 fails on the SLIPPAGE PLACEHOLDER alone: edge after fee
is +0.006302, which clears a 0.005 floor, and only the unmeasured 0.01
slippage term pushes it to -0.003698. On the pooled basis the same is true
(+0.008784 -> -0.001216). So under BOTH bases, the single number deciding
whether print-lock may pay 0.99 is a placeholder no one has measured. That is
stated here rather than buried: see s8.5 for the instrumentation that makes it
recoverable, and s8.6 falsifier 2.

### 8.3 Two inherited traps BL-13 will walk into unless flagged

1. **The spec tells the implementer to copy `forecast_mispricing`'s folder**
   ("Implementation notes" item 1). That folder carries `min_model_edge = 0.04`
   (`forecast_mispricing/config.py:87`) and `transaction_cost_prob = 0.015`
   (`:94`). Copied verbatim they reproduce BL-19 exactly: the requirement
   becomes `ask <= 0.9969 - 0.04 - 0.015 = 0.9419` [DERIVED], i.e. **ask <= 0.94
   on the grid** — the same unreachable gate, in a new package, on the strategy
   that is now the lead. Copy the layout; do not copy those two values.
2. **The spec's own pre-registered economic kill reproduces the same
   over-charge.** Spec s5: "Required ask ceiling: `p_stable - c - 0.03`" with
   "a 2¢ cost assumption". At the pooled `p_stable` that is
   `0.99989 - 0.02 - 0.03 = 0.94989` -> ask ceiling 0.94 [DERIVED]; at the
   per-site bound, 0.9469 -> 0.94. Applied literally, that test declares the
   idea dead unless overnight asks sit at or below 0.94. Under the fee-correct
   treatment the ceiling is 0.98. **The pre-registered threshold must be
   recomputed with the venue fee model before it is used as a kill**, or BL-19's
   failure mode moves out of config and into a falsification test — where it
   would kill a live strategy rather than merely refuse it. Recommended
   replacement ceiling, stated in the spec's own form:
   `break_even(model_p, theta) - min_model_edge - slippage_prob` = 0.9867 at the
   per-site basis -> **0.98 on the grid**.

### 8.4 Do the s2/s6 rules carry over? (fee, slippage, discount band)

**`fee_coefficient`, per instrument, fail closed — CARRIES OVER UNCHANGED.** It
is a venue property, not a strategy property; the same `fees.py:90-92` no-default
posture applies. Its practical effect here is small (0.000594 at 0.99, 0.001176
at 0.98) — the reason to adopt it is that the alternative is the 0.015 constant,
which alone refuses the entire region (s8.3 trap 1).

**`slippage_prob = 0.01` — CARRIES OVER, and is if anything OPTIMISTIC here.**
Two differences push the other way from the tail case:

- Print-lock trades overnight into a book the spec itself calls thin ("Overnight
  top-of-book on these binaries is thin", s3; the same fact that makes shorts
  unexecutable — median top-of-book bid 0.3 contracts). A taker in a thin book
  slips more, not less.
- **The spec's "Sizing" section has no depth clause.** It sizes off the payout
  caps only. `running_extreme_lock` walks the ask ladder and re-prices at the
  VWAP of the clipped size (`decision.py:247-296`); print-lock as specified does
  not. This is exactly the omission `FEEDBACK_FOR_GROK_2026-08-31.md` s3 item 10
  raised against all three briefs ("a book of 5 contracts at 0.50 backed by 300
  at 0.99 reads as highly profitable at level 0 and is a loss on any real size").

  **Therefore: the VWAP depth walk is a prerequisite, not an option.** Without
  it, `slippage_prob` would have to absorb the depth-walk cost as well and one
  tick is not defensible. With it, one tick covers only quote-age drift and
  queue risk, which is what it is meant to cover.

**`max_discount_from_break_even = 0.10` — DOES NOT CARRY OVER. Do not copy it.**
The tail-case rationale was that the trigger is an outlier event, so a
penny ask meant the tail had not really been satisfied. Print-lock's trigger is
an ordinary event, and a deep discount is the STRATEGY'S OWN THESIS: spec s2-s3
says the ask "remains below `1 - cost - revision_haircut` because overnight flow
watches apps / METAR spots or waits for the 08:00 ET event". A 10-tick band
would refuse precisely the trades the strategy exists to take.

The honest problem is that a very low ask on a bucket containing the printed
value has two explanations that price alone cannot separate: (i) the lag thesis
is working, or (ii) we mapped the wrong station / climate day / bucket (spec s4
loss condition 3, "LST day, not civil clock during DST"). Recommendation for
v1: **no price-based refusal band.** The discriminator is not price, it is the
mapping, and the mapping check is already mandated and free — the spec's pure
gates 1 and 3 (`applies_to` station+climate_day; printed value inside bucket
bounds) plus the existing exclusive-bucket logic. Instead:

- emit a loud ALERT (not a refusal) when the ask sits more than ~0.20 below
  break-even, carrying station, climate_day, printed value, and bucket bounds,
  so an operator can eyeball the mapping;
- and record it (s8.5) so the ask distribution on TRIGGERED station-days becomes
  the measurement it currently is not.

If a later sample shows deep-discount fills are systematically mis-mappings
rather than edge, a band can be added then, derived from that sample.

### 8.5 What a NULL from the morning capture would and would not prove

This is the failure mode to guard: a config-induced null read as a dead market.
Four distinguishable nulls, only two of which are market facts.

| # | What happened | Is it a market fact? | Visible at the refusal counter? |
|---|---|---|---|
| N0 | No CLI final reached the strategy before the 2.0h halt | NO — feed/plumbing | no |
| N1 | Trigger fired; pure gate returned `None` (bucket bounds, `correction_flag`, `applies_to`, future timestamp) | NO — mapping/data | **no** |
| N2 | Trigger fired; signal formed; refused at the edge floor | **only if the ask was recorded** | yes (`edge_below_minimum`) |
| N3 | Trigger fired; signal formed; passed; no book / no ask / insufficient liquidity | YES — the market genuinely wasn't there | yes |

N0 is unlikely to be the market's fault: MEASURED halt-window hit rate is 98.66%
(9041/9164; Wilson-95% lower 98.40% [DERIVED]), far above the spec's own
operational kill of 0.20. A null of type N0 therefore points at spec s6's
conditional branch — the NWS client not delivering the morning CLI ahead of
settlement — not at the venue. (Supporting, N=2 station-days only, from
`FEEDBACK_FOR_GROK_2026-08-31.md` s1: NYC final received 06:25:55Z and MIA
08:42:55Z against an 08:00 ET / 12:00Z settlement — both leave more than 2.0h.)

N1 is the dangerous one: a pre-signal `None` never reaches `evaluate_order` and
so is never counted (`risk.py:370-390`; same class as BL-10). At the counter it
is indistinguishable from N0. This is the identical trap s5 documented for the
tail-locks, and it applies here even though the trigger is designed to fire on
most station-days.

**A null therefore proves nothing unless the capture records the decision
inputs.** Required instrumentation, per station-day, written regardless of
whether an order forms:

    station, climate_day, cli_received_ts, printed_value, is_final,
    correction_flag, revision_seq, mapped_instrument_id, bucket bounds,
    hours_to_settlement, level0_ask, ask_size, vwap_ask_at_intended_size,
    fee_coefficient, computed edge at slippage_prob in {0.000, 0.010},
    and the FIRST gate that stopped it (including pre-signal `None` reasons)

With that record, any null is decodable offline and — critically — the
threshold is re-derivable WITHOUT re-running the capture: if the asks were
0.99 and slippage turns out to be zero, the same tape yields trades under a
corrected `slippage_prob`. Without it, a null is uninterpretable and the
capture has to be repeated.

**What a null WOULD prove, given that record:** if triggered station-days show
asks at 0.995+/1.00, an empty ask side, or size below `min_liquidity_contracts`,
the settlement-source-lag thesis (spec s2) is refuted on those station-days.
That is a genuine market fact and an honest kill.

**What a null would NOT prove:** anything at all, if the asks were not recorded;
anything about the market, if the null is N0 or N1; and nothing about
profitability from N2 alone, since N2 at ask 0.99 is a config outcome driven by
an unmeasured slippage placeholder (s8.2), not a market verdict.

### 8.6 Recommended values for `cli_settlement_print_lock`

To be set in that package's own `config.py` when it lands. Unchanged from s6:
no edit to `risk.py:100`/`:116`, no edit to any other strategy, no value assigned
to the operator-reserved maximum daily trading budget or maximum notional per
position (spec "Sizing" leaves both unset — correct, keep it), and
`allow_short` stays `False` (spec s8; `risk.py:117-137`).

| Knob | Recommended | Derivation | Note vs `running_extreme_lock` |
|---|---|---|---|
| `model_p` source | **0.9969**, per-station Wilson-95% lower of `p_stable`; a scalar, no margin analogue | 0-failure bound at N ≈ 1821 is 0.996896; pooled 0.999378 assumes five WFOs are exchangeable | scalar is defensible here (value-identity is stronger than bucket-membership); a scalar was NOT defensible for the tail |
| `min_model_edge` | **0.005** | Admits ask <= 0.98 (edge +0.005720 after fee and one tick), refuses 0.99 (-0.003698); 6.1x cushion over the 0.3104% Wilson-implied failure rate | same value, different derivation |
| cost | **`trade_cost_prob` = `venue_fee_prob(vwap_ask, theta)` + `slippage_prob`**; never a 0.015 constant | 0.015 would force ask <= 0.94 (s8.3 trap 1) | carries over |
| `slippage_prob` | **0.01**, UNMEASURED, and optimistic here | thin overnight book; spec has no depth clause | carries over, weaker justification |
| VWAP depth walk | **prerequisite, not optional** | spec "Sizing" omits it; FEEDBACK s3 item 10 | already present in the tail strategy |
| `fee_coefficient` | per-instrument, refuse when absent | `fees.py:90-92` | carries over unchanged |
| `max_discount_from_break_even` | **do not carry over**; alert-only beyond ~0.20 below break-even | a deep discount IS the thesis (spec s2-s3), not an anomaly | explicitly different |
| `min_stable_prob` (spec field) | keep 0.97 | non-binding at 0.9969 | n/a |
| spec s5 ask ceiling | **recompute**: 0.98, not 0.94 | the 2¢/3¢ constants reproduce BL-19 inside a pre-registered kill | n/a |

**Net:** print-lock is tradable in principle at 0.98 or better and refuses 0.99.
Unlike the tail case, its trigger is designed to fire on most station-days, so
the ask distribution it meets is measurable in a single morning capture — which
makes the instrumentation in s8.5 the highest-value part of this addendum.

### 8.7 Additional falsifiers specific to BL-13

Additions to s7; s7 items 4 (theta) and 5 (tick size) apply unchanged.

8. **The morning CLI does not reach the strategy before the 2.0h halt.** Spec s6
   makes this the make-or-break dependency ("if the client only emits a
   climate-day record after venue settlement, this requires data Breezy does not
   have"). MEASURED halt-window hit rate 98.66% (9041/9164) is computed on NWS
   ISSUANCE times, not on Breezy RECEIPT times; the live receipt sample is N=79
   and steady-state only (`observation_lock_falsification_2026-08-31.md` s4).
   Receipt lag is the untested link.
9. **Overnight asks on the printed bucket sit above 0.98.** Then the strategy is
   refused for the right reason and the lag thesis is dead — see s8.5 for the
   record needed to make that claim.
10. **The five stations are not exchangeable and one is materially worse.**
    Would not change the recommendation (0.9969 is already the per-site bound)
    but would kill any later attempt to trade on the pooled 0.99938.
11. **Bucket widths are 1F.** Then the value-identity-vs-membership argument in
    s8.1(1) collapses to an equality and `p_stable` stops being conservative —
    it becomes exact. The recommendation survives, but its safety margin is
    smaller than stated. This is checkable from the captured instrument list and
    should be checked before the first live enablement.
12. **The 11:00 ET METAR-review path fires materially more than never.** It is
    absent from the 9105/9106 denominator entirely (s8.1(3)); a measured rate
    would have to be subtracted from `model_p`, and at 0.98 the entire budget
    for it is 1.88% total failure.
