# `cli_settlement_print_lock` — adverse-selection sizing and the cost term

Date: 2026-09-01. Scope: **DESIGN ONLY.** No source file was modified by this
document. Read-only against `src/breezy/strategy/cli_settlement_print_lock/**`,
`src/breezy/strategy/weather_common/**`, `src/breezy/adapters/polymarket_us/{fees,parsing,errors}.py`,
`pyproject.toml` (import-linter contracts), and the installed
`.venv/lib/python3.13/site-packages/nautilus_trader/` tree.

Consumes: `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` §8,
`docs/strategies/breezy_strategy_cli_settlement_print_lock.md` §5 + CORRECTION,
`docs/evidence/first_in_window_capture_2026-09-01.md`,
`docs/evidence/observation_lock_falsification_2026-08-31.md`,
`docs/evidence/venue/polymarket_us/VENUE_FACTS_2026-08-25.md`.

Every number is either **[DERIVED]** here from a formula in source, or
**[MEASURED]** and quoted with its denominator from a named evidence file.
Nothing here is a new measurement.

Constants used throughout: `model_p` = 0.996896
(`strategy.py:186`, per-station Wilson-95% lower), `theta` = 0.06
([MEASURED] 20/20 captured weather markets carry `feeCoefficient: 0.06` —
`docs/evidence/venue/polymarket_us/raw/markets_tagIds_weather.json`), tick =
0.01, `slippage_prob` = 0.01 (UNMEASURED placeholder, BL-19 §8.6),
`fee(a) = theta * a * (1 - a)`, `cost(a) = fee(a) + slippage_prob`,
`edge(a) = model_p - a - cost(a)`.

---

## 0. Nautilus null-hypothesis verdicts (L-1)

Three things this design could have needed from Nautilus. All three checked
against installed source before anything new is proposed.

**L-1a — a pre-trade cost estimate in probability units. GAP IS REAL.**
`FeeModel` (`backtest/models/fee.pyx:33`) exposes exactly one method,
`get_commission(order, fill_qty, fill_px, instrument) -> Money`. It prices a
**fill that has already happened**: it needs an `Order` object, a filled
quantity and a filled price, and returns `Money`, not a probability. There is
no API anywhere in the installed package that answers "what would this cost if
I paid `a`?" for a contemplated price. The three concrete models —
`MakerTakerFeeModel` (`:67`), `FixedFeeModel` (`:115`),
`PerContractFeeModel` (`:168`) — are all flat-rate-on-notional or
flat-per-contract; none can express a `p * (1 - p)` term. A small pure helper
in Breezy is justified. It does **not** replace `PolymarketUSFeeModel`, which
stays the settlement-time authority; the helper is the gate-time estimate of
the same formula, and §2.6 pins them to each other by test.

**L-1b — a native `theta * p * (1 - p)` fee model. EXISTS, FORBIDDEN, AND
UNSAFE. DO NOT ADOPT.** `nautilus_trader/adapters/polymarket/fee_model.py::PolymarketFeeModel`
implements exactly `fee = qty * fee_rate * p * (1 - p)`. It is disqualified
three times over:

1. It is in the Polymarket **.com** adapter. The import-linter contract
   "Breezy never imports the Nautilus Polymarket .com adapter" carries no
   ignore entry for `nautilus_trader.adapters.polymarket`, so importing it
   fails `lint-imports`.
2. It reads `instrument.taker_fee` — the flat field
   `breezy.adapters.polymarket_us.errors.FeeScheduleUnknownError` documents as
   a placeholder that "silently reads as a FREE VENUE" — and returns
   `Money(0)` when it is `<= 0`. That is **fail-open**, the exact posture
   `fees.py:90-92` refuses.
3. It credits maker rebates (`infer_maker_rebate_rate`), which
   `MakerRebateUnmodelledError` says Breezy must not model until a real maker
   fill is observed.

**L-1c — a VWAP depth walk (BL-19 §8.4 calls it a prerequisite). NATIVE
CAPABILITY EXISTS AND WAS NOT USED.** `OrderBook.simulate_fills(order,
price_prec, size_prec, is_aggressive)` (`model/book.pyx:683`) returns the
per-level fill list for an aggressive order against the live book.
`running_extreme_lock/decision.py:247-296` hand-rolls a ladder walk instead.
This design does **not** add a depth walk to print-lock (see §1.6), but if one
is added later, the null hypothesis is `simulate_fills`, and lifting
`running_extreme_lock`'s hand-rolled walker into `weather_common` should not
proceed until that is disproved. Recorded as a finding, out of scope here.

---

## 1. Problem 1 — sizing rewards the disagreement it cannot explain

### 1.1 What is shipped today

`decision.py:257-260`:

```python
visible_depth = quote.ask_size or 0.0
quantity = math.floor(
    min(cfg.max_quantity, cfg.base_quantity + cfg.edge_qty_scale * edge, visible_depth),
)
```

with `base_quantity` 25.0, `max_quantity` 150.0, `edge_qty_scale` 400.0
(`config.py:130-132`). Size is affine and strictly increasing in `edge`, and
`edge` is strictly decreasing in `ask`. So size is strictly increasing in how
much the book disagrees with us, which is the finding.

### 1.2 First correction: the review's own arithmetic

The review states "edge 0.04 → 41 contracts, edge 0.30 (ask 0.65) → 145 at
the cap". Two defects, both making the current behaviour look milder than it
is:

* 25 + 400 x 0.30 = **145**, which is *below* `max_quantity` = 150. It is not
  "at the cap".
* Ask 0.65 does not produce edge 0.30 under either cost model. Under the
  shipped 0.015 scalar, edge(0.65) = 0.996896 - 0.65 - 0.015 = **0.331896**
  → 25 + 132.8 = 157 → clipped to **150**. Under BL-19's cost,
  edge(0.65) = **0.323246** → 154 → clipped to **150**. [DERIVED]

At ask 0.65 the sizer is already **at** the 150 cap, not one notch below it.

### 1.3 The defect stated in the unit that matters: dollars at risk

For a long-only binary the loss when wrong is the premium paid, `a + fee(a)`
per contract — not the payout. So the exposure question is cost basis, not
contract count. Under BL-19's cost model and today's sizer [DERIVED]:

| ask | fee | cost | edge | qty today | **cost basis today** |
|---:|---:|---:|---:|---:|---:|
| 0.99 | 0.000594 | 0.010594 | -0.003698 | refused | — |
| 0.98 | 0.001176 | 0.011176 | +0.005720 | 27 | $26.49 |
| 0.97 | 0.001746 | 0.011746 | +0.015150 | 31 | $30.12 |
| 0.95 | 0.002850 | 0.012850 | +0.034046 | 38 | $36.21 |
| 0.90 | 0.005400 | 0.015400 | +0.081496 | 57 | $51.61 |
| 0.80 | 0.009600 | 0.019600 | +0.177296 | 95 | $76.91 |
| 0.66 | 0.013464 | 0.023464 | +0.313432 | 150 | $101.02 |
| 0.65 | 0.013650 | 0.023650 | +0.323246 | 150 | $99.55 |
| 0.50 | 0.015000 | 0.025000 | +0.471896 | 150 | $77.25 |
| 0.21 | 0.009954 | 0.019954 | +0.766942 | 150 | $32.99 |
| 0.02 | 0.001176 | 0.011176 | +0.965720 | 150 | $3.18 |

The linear term stops binding above the 150 cap at ask 0.66095 [DERIVED,
solving 25 + 400 x edge(a) = 150]. **Capital at risk peaks at ~$101 at ask
≈ 0.66 and is $26.49 at the best-corroborated entry (0.98) — 3.8x more money
committed to the least-corroborated signal.** That is the finding, correctly
stated.

### 1.4 Second correction: the EV of case (b) is not what the review assumes

The review sets up (a) "the book has not absorbed the print" vs (b) "the book
knows something we do not", and treats (b) as a large expected loss. Work it
out. Let `P(b)` be the probability we are in case (b) and `pi_b` the true
settlement probability of the bucket we bought under (b). Then

    p_eff = (1 - P(b)) * model_p + P(b) * pi_b
    EV per contract = p_eff - a - cost(a)

Case (b) as the review describes it — *the market is right and we are wrong*
— means the market's price is the honest estimate, i.e. `pi_b ≈ a`. Substitute:

    EV = (1 - P(b)) * (model_p - a) - cost(a)                   [DERIVED]

At ask 0.65 that is positive whenever `(1 - P(b)) * 0.346896 > 0.02365`, i.e.
**`P(b) < 93.2%`**. At ask 0.21: `P(b) < 97.5%`. At ask 0.90: `P(b) < 84.1%`.
[DERIVED]

Three consequences, and they redirect the whole remedy:

1. **A refusal band on cheap asks is expensive, not free.** Refusing at ask
   0.65 forgoes `(1 - P(b)) * 0.3469 - 0.0237` per contract, which stays
   positive until 93% of deep discounts are model failures. A guard that also
   refuses case (a) is not merely "not free" — at these prices it is the most
   expensive thing in the option set.
2. **A cheap ask is the *cheapest* place to be wrong,** because the premium is
   the whole downside. Buying 150 contracts at 0.02 risks $3.18. The
   review's intuition that the danger scales with the discount is inverted in
   dollars.
3. **What actually goes wrong is not EV, it is concentration and
   repetition.** A systematic mapping fault (DST off-by-one binding
   `climate_date = D` to a record covering D-1) does not produce one bad
   trade; it produces one bad trade **per station-day, indefinitely**, while
   the sizer commits its largest cost basis to exactly those trades, and no
   feedback loop exists to notice, because `p_stable`'s 9105/9106 denominator
   contains neither the mis-mapping hazard nor the 11:00 ET METAR-review path
   (BL-19 §8.1(3)).

So the correct remedy shape is: **do not refuse anything the edge gate admits;
stop letting unverified disagreement buy more capital.**

### 1.5 RECOMMENDATION 1 — constant-cost-basis sizing, anchored on the base clip at the worst admissible ask

Replace the affine-in-edge term with a rule that holds **dollars at risk per
decision constant across the admitted price range**. The anchor is derived
from values already in the config, so no new tunable number is introduced and
no operator-reserved dollar control is assigned.

**Step 1 — the worst admissible ask, exactly.** Solve
`model_p - a - theta*a*(1-a) - slippage_prob = min_edge_after_costs`:

    0.06 a^2 - 1.06 a + 0.981896 = 0
    a = (1.06 - sqrt(1.1236 - 0.23565504)) / 0.12
      = (1.06 - 0.94230831) / 0.12
      = 0.98076408                                              [DERIVED]

On the 0.01 tick grid: **`a_max` = 0.98**. (This reproduces the §5 CORRECTION
block's 0.9817 → 0.98 by a slightly different route: the CORRECTION subtracts
from break-even, this solves the gate equation directly. Both floor to 0.98.)

**Step 2 — the implied per-decision cost-basis anchor.**

    A = base_quantity * (a_max + fee(a_max))
      = 25 * (0.98 + 0.001176)
      = 25 * 0.981176
      = $24.5294                                                [DERIVED]

This is *not a new risk budget*. It is the cost basis the strategy already
commits at its tightest admissible entry, read off the shipped
`base_quantity`. It is a **derived quantity, not a knob**, and it is
deliberately not a config field — see §1.7.

**Step 3 — the sizing rule.**

    quantity = floor(min(max_quantity,
                         A / (ask_p + fee(ask_p)),
                         visible_depth))

**Resulting behaviour** [DERIVED]:

| ask | qty today | **qty proposed** | cost basis proposed | Δ contracts |
|---:|---:|---:|---:|---:|
| 0.98 | 27 | **25** | $24.53 | -2 |
| 0.97 | 31 | **25** | $24.29 | -6 |
| 0.95 | 38 | **25** | $23.82 | -13 |
| 0.90 | 57 | **27** | $24.45 | -30 |
| 0.80 | 95 | **30** | $24.29 | -65 |
| 0.65 | 150 | **36** | $23.89 | -114 |
| 0.50 | 150 | **47** | $24.21 | -103 |
| 0.21 | 150 | **111** | $24.41 | -39 |
| 0.156 and below | 150 | **150** (cap binds) | ≤ $24.5, falling | 0 |
| 0.02 | 150 | **150** | $3.18 | 0 |

Size still rises as the contract gets cheaper — correctly, because the premium
falls faster than the count rises. What no longer rises is the money.

**Failure mode this closes.** The one the review names, restated precisely: a
systematic mapping or resolution-timing fault can no longer escalate its own
capital consumption by producing a larger apparent edge. Per-decision loss
ceiling becomes flat at ~$24.53 across the whole admitted band (falling below
ask 0.156), instead of peaking at ~$101 at ask 0.66. Repetition exposure is
already bounded by `max_event_notional` 1000 / `max_location_notional` 2000 /
`max_simultaneous_positions` 12 — the change makes those caps take ~4x longer
to fill on the suspicious band, which is ~4x more station-days of alert
history before the exposure is spent.

**What it costs, priced.** No opportunity is refused; only size is forgone.
Cost per trade, if case (a) is true with the full `model_p` [DERIVED]:

| ask | Δ contracts | edge/contract | **forgone EV** | loss avoided if wrong and `pi_b`=0 | P(b) at which the guard breaks even |
|---:|---:|---:|---:|---:|---:|
| 0.98 | 2 | 0.005720 | $0.01 | $1.96 | 0.6% |
| 0.97 | 6 | 0.015150 | $0.09 | $5.83 | 1.5% |
| 0.95 | 13 | 0.034046 | $0.44 | $12.39 | 3.4% |
| 0.90 | 30 | 0.081496 | $2.44 | $27.16 | 8.2% |
| 0.80 | 65 | 0.177296 | $11.52 | $52.62 | 18.0% |
| 0.65 | 114 | 0.323246 | $36.85 | $75.66 | 32.8% |
| 0.50 | 103 | 0.471896 | $48.61 | $53.05 | 47.8% |
| 0.21 | 39 | 0.766942 | $29.91 | $8.58 | 77.7% |
| 0.02 | 0 | 0.965720 | $0.00 | $0.00 | n/a |

Read honestly, and this is the price the operator asked for, not a wave of the
hand: the guard is a **clear win above ask 0.80** (it pays for itself if as few
as 18% of those disagreements are model failures, and costs at most $11.52 when
they are not), a **judgement call at 0.50-0.65** (needs 33-48%), and a **bad
trade below ask ~0.25** (needs 78%). Two mitigations of the bad end, both
structural rather than assumed:

* Below ask 0.156 the rule is a **no-op** — `max_quantity` = 150 already binds
  and nothing changes. The entire "bad trade" region of the table (0.21 and
  below) is a 39-contract difference at one price point, shrinking to zero.
* The forgone-EV column assumes case (a) at the full 0.996896. Substituting
  the honest mixture from §1.4, forgone EV at ask 0.50 is
  `103 * ((1 - P(b)) * 0.496896 - 0.025)`, which is $48.6 only at P(b) = 0 and
  falls to $23.0 at P(b) = 50%.

**Measured-reality check — how often does this bind at all?** The guard changes
the submitted order only when `visible_depth` exceeds the proposed size. The
risk layer already refuses any order whose ask side shows fewer than
`min_liquidity_contracts` = 25 contracts (`risk.py:302-313`, one-sided-book
branch → `liq = ask_size`), and `base_quantity` = 25 is exactly that floor. So
the change is inert unless the book shows ≥ 28 contracts at ask 0.90, ≥ 31 at
0.80, ≥ 37 at 0.65. Against the repo's own measured book shape — thin, median
top-of-book bid 0.3 contracts, depth clipping already binding — the expected
frequency is low, and the expected cost is correspondingly low. **That cuts
both ways and is stated as such: a guard that is usually inert also usually
protects nothing.** Its value is concentrated in the deep-book case, which is
also the only case where the current sizer can actually commit $101.

### 1.6 Options rejected, with the reason

| Option | Verdict | Why |
|---|---|---|
| Hard floor on ask (refuse implausibly cheap) | **REJECT** | §1.4: at ask 0.65 refusal forgoes positive EV until 93% of deep discounts are model failures. Independently rejected by BL-19 §8.4 on a different ground ("a deep discount IS the thesis"). Two independent derivations agreeing is the strongest evidence in this document. |
| Upper bound on edge (refusal) | **REJECT** | Algebraically identical to an ask floor: `edge > X` ⟺ `ask < model_p - cost - X`. Same cost, different spelling. |
| Cap the edge used for **sizing** (`min(edge, E)`) | **REJECT, but it is the near-miss** | Achieves flat *contracts* above `E`, which is the wrong invariant: flat contracts still means rising dollars as `E` is approached and a discontinuous kink at `E` that has no derivation behind it. Constant cost basis achieves flat *dollars* with no free parameter. |
| Invert the size/edge relationship outright | **SUBSUMED** | Recommendation 1 *is* the inversion in dollar terms, derived rather than sign-flipped. |
| Require corroboration before sizing up | **REJECT for v1** | There is no corroborating variable. `conviction` (boundary margin, `decision.py:264-271`) is the only candidate and it is currently computed and thrown away — but BL-19 §8.1(1) establishes margin conditioning can only *raise* `model_p`, and no measured margin-keyed table exists for the final print. Sizing up on it fabricates evidence; sizing *down* on margin 0 is defensible but is a second undermined knob for a hazard that constant-cost-basis already bounds. Named as a follow-up, not shipped. |
| Do nothing — "0.005 floor + 0.98 ceiling already bounds the region" | **REJECT, and the premise is wrong** | 0.98 is a **ceiling on ask**, i.e. a bound on the *expensive* end. It constrains nothing on the cheap side. The floor/ceiling pair leaves the entire ask ∈ (0, 0.98] band admitted with size rising monotonically across all of it. |
| Add a VWAP depth walk now | **DEFER** | BL-19 §8.4 calls it a prerequisite for `slippage_prob` = 0.01 being defensible. It is a real gap, but it is a separate change with its own null hypothesis (§0 L-1c) and its own blast radius. Constant-cost-basis sizing is orthogonal to it and does not depend on it. |

### 1.7 Why the anchor is not a config field

`A` is `base_quantity * (a_max + fee(a_max))`, all three inputs already
present. Exposing it as `max_cost_basis_per_decision: float` would create a
dollar-denominated per-decision knob that is one rename away from "maximum
notional per position" — an **operator-reserved control**. It stays derived,
in code, at the one call site. No value is assigned to either reserved
control by this design.

### 1.8 What would falsify Recommendation 1

1. **The §8.5 record shows fired-print asks cluster at 0.97-0.99.** Then the
   rule is a permanent no-op (25 contracts either way) and the whole exercise
   was theatre. This is the single most likely falsifier, and the capture that
   settles it is already specified.
2. **Books turn out to be deep on printed buckets** (ask depth routinely
   > 150). Then the guard binds on every trade, the forgone-EV column becomes
   the operating cost rather than a tail, and it must be re-argued against a
   measured `P(b)`.
3. **A measured deep-discount sample shows `pi_b` << `ask`** — i.e. when the
   market disagrees deeply it is not merely right but *specifically* right
   about this bucket being near-impossible. Then §1.4's `pi_b ≈ a` substitution
   fails, case (b) becomes a genuine EV loss, and a refusal band becomes
   justified after all. Recommendation 1 would then be too weak, not too
   strong.
4. **`theta` is not 0.06 on some traded market.** Every fee figure scales
   linearly in `theta`; `a_max` and therefore `A` move with it. The rule
   recomputes `A` per instrument from that instrument's own `theta`, so it
   self-corrects — but the tables above would need re-deriving.
5. **Tick is not 0.01 on some traded market.** `bucket_contract.py:41-43`
   warns the captured universe carries more than one. At a finer tick, `a_max`
   moves off 0.98 and `A` with it. Again self-correcting in code, wrong in the
   tables.

---

## 2. Problem 2 — a cost term in which the unsafe configuration cannot be written

### 2.1 The hazard, restated

`decision.py:245` is `edge = model_p - ask_p - cfg.transaction_cost_prob`.
One scalar. The safe cost model is `fee(a) + slippage`, which is not a scalar.
The dangerous partial migration is a one-line config edit:
`transaction_cost_prob = 0.0006`, `min_edge_after_costs = 0.005` →
`edge(0.99) = 0.996896 - 0.99 - 0.0006 = +0.006296 > 0.005` → **trades at
0.99**, which §8.2 computes as **-0.003698** after one tick of slippage.
[DERIVED]

The design goal is therefore not "compute the fee correctly". It is: **leave
no field in which a total cost can be written.**

### 2.2 Shape of the fix

Three moves, together sufficient:

1. **Delete `transaction_cost_prob` from `CliSettlementPrintLockConfig`.**
   After this there is no field meaning "total cost", so the unsafe edit has
   no target.
2. **The fee is not configurable at all.** It is computed from the
   instrument's own `theta`, which is a venue fact reaching the strategy by
   injection, never a config default (`fees.py:90-92`: no module default, no
   fallback — a strategy-side default would reintroduce the fallback the
   adapter refuses).
3. **`slippage_prob` is a required config field with no default, floored at
   one tick.** It is the only writable cost input, it is named for what it is,
   and it cannot be set below the smallest representable adverse price move.
   The minimum expressible cost is therefore `fee(a) + tick_size`, so
   `cost(0.99) >= 0.010594` and 0.99 is structurally refused.

**Proof the hazard is closed.** To trade at 0.99 an operator must write
`slippage_prob < 0.99 * ...` — precisely, must satisfy
`0.996896 - 0.99 - 0.000594 - s >= 0.005`, i.e. `s <= 0.001302`. The
construction-time validation `slippage_prob >= contract.tick_size` = 0.01
rejects every such value. There is no other writable cost input. [DERIVED]

### 2.3 Where `theta` is computed, and how it reaches the decision layer

**Layering, checked.** `pyproject.toml`'s layers contract puts `strategy` at
the TOP, above `runtime` and `adapters`. A direct
`breezy.strategy.* -> breezy.adapters.polymarket_us.*` import is therefore
*legal*. It is nonetheless rejected: it welds a strategy to one venue, against
Breezy's stated engineering priority 5 (portability to Kalshi), and no shipped
strategy currently imports an adapter. Use injection instead — the pattern the
repo already established for exactly this problem in
`weather_common/forecast_source.py` (a plain non-Nautilus `Protocol`, a
REQUIRED constructor argument, a named error on `None`, wired at the
construction site).

**New file — `src/breezy/strategy/weather_common/costs.py`** (strategy layer,
venue-neutral, pure, no adapter import):

```python
class UnknownFeeScheduleError(ValueError):
    """A cost computation was reached with no fee coefficient for the market."""


class FeeCoefficientSource(Protocol):
    """Resolves one market's venue fee coefficient (`theta`).

    A pull seam, not a push: called once per instrument at `on_start`, because
    a fee schedule is a static property of the market and cannot appear
    mid-session. Implementations MUST raise `UnknownFeeScheduleError` rather
    than return a default -- mirroring
    `breezy.adapters.polymarket_us.fees._fee_coefficient`, which raises rather
    than trading free.
    """

    def fee_coefficient_for(self, instrument_id: str) -> float: ...


def venue_fee_prob(*, executable_price: float, fee_coefficient: float) -> float:
    """`theta * p * (1 - p)`, in probability units, per contract.

    Pure. Non-negative on [0, 1]; symmetric about 0.5; maximal at 0.5;
    monotone decreasing on [0.5, 1]. Raises `ValueError` outside [0, 1] --
    outside that range the term goes NEGATIVE and would pay a rebate
    (`fees.py:178-184` refuses for the same reason).
    """


def trade_cost_prob(
    *,
    executable_price: float,
    fee_coefficient: float,
    slippage_prob: float,
) -> float:
    """`venue_fee_prob(...) + slippage_prob`.

    The two terms are kept SEPARATE and separately named because they behave
    oppositely as `p -> 1`: the fee vanishes (0.000594 at 0.99), the execution
    term does not. `slippage_prob` is UNMEASURED -- see BL-19 sections 2 and
    8.2, and the instrumentation in section 8.5 that is expected to replace
    the 0.01 placeholder with a figure derived from realised fills.
    """
```

These are the two signatures BL-19 §2 specified, verbatim. **Deviation from
BL-19 §2, stated:** BL-19 proposed placing them in `weather_common/risk.py`
"beside `edge_after_costs`". They go in a new `costs.py` instead — `risk.py`
is a 508-line portfolio-gating module, the cost seam brings a Protocol and its
own error type, and BL-19's actual requirement (that `edge_after_costs`'s
signature not change, because `cost` is already injected) is satisfied either
way. `edge_after_costs` is untouched.

**Shared type — `weather_common/bucket_contract.py`**, one additive field
(BL-19 §2's own recommendation, spelled as a float since the strategy layer
works in floats throughout):

```python
    #: The venue's per-market fee coefficient (`theta`), resolved once at
    #: `on_start` from a `FeeCoefficientSource`. `None` means UNRESOLVED, and
    #: an unresolved schedule is a NO-TRADE, never a free trade
    #: (`fees.py:90-92`). Defaults `None` so the three forecast strategies,
    #: which still use their own scalar `transaction_cost_prob`, are
    #: unaffected by this field.
    fee_coefficient: float | None = None
```

`MispricingContract` is `frozen=True, slots=True, kw_only=True`, so the field
is additive and every existing construction site keeps compiling.

**Adapter-backed implementation — `src/breezy/runtime/taker_cost.py`** (NEW
file; `runtime -> adapters` is downward and legal):

```python
class PolymarketUSFeeCoefficients:
    """`FeeCoefficientSource` backed by cached Polymarket.us instruments."""

    def __init__(self, instruments: Mapping[str, Instrument]) -> None: ...

    def fee_coefficient_for(self, instrument_id: str) -> float:
        # 1. `assert_fee_schedule_known(instrument)`  -- barrier F1's guard
        # 2. `read_fee_coefficient(instrument)`       -- see below
        # 3. `float(theta)`
        # Any `FeeScheduleUnknownError` is re-raised as
        # `UnknownFeeScheduleError` so the strategy layer never catches an
        # adapter-specific type.
```

**One adapter change is required and it is a promotion, not a rewrite:**
`breezy.adapters.polymarket_us.fees._fee_coefficient` (`fees.py:212-254`)
already performs exactly the read and re-validation needed (status marker,
absence, `bool` round-trip, `InvalidOperation`, range). Promote it to public
`read_fee_coefficient(instrument: Instrument) -> Decimal` and export it from
`adapters/polymarket_us/__init__.py`. Rename only; no behaviour change.
**Sequencing note: `src/breezy/adapters/polymarket_us/` and
`src/breezy/runtime/` are under concurrent edit by another agent. This step
must be sequenced after that work lands.** Fallback if the adapter cannot be
touched: duplicate the ~25 lines of validation in `runtime/taker_cost.py`.
That is a DRY violation on a fail-closed path and is the worse option — take
the rename.

### 2.4 Strategy wiring — exact signatures

`cli_settlement_print_lock/strategy.py`:

```python
class UnpricedInstrumentError(ValueError):
    """Raised at `on_start` when a configured instrument has no fee schedule.

    Same posture, and for the same reason, as `MissingObservationBoundError`
    above: a fee schedule is a STATIC property of a market, so deferring the
    refusal to decision time converts a loud startup failure into a permanent,
    silent no-op that the refusal counter cannot see (BL-19 section 8.5, null
    class N1 -- a pre-signal `None` never reaches `evaluate_order` and is
    never counted). `fees.py:90-92` is explicit that an unparseable
    coefficient raises rather than trading free; this is that rule, moved to
    the gate.
    """


    def __init__(
        self,
        config: CliSettlementPrintLockConfig,
        fee_coefficients: FeeCoefficientSource,
    ) -> None:
```

Mirrors `ForecastMispricingStrategy.__init__(self, config, forecast_source)`
(`forecast_mispricing/strategy.py:109-121`), including the explicit `is None`
check with a named error, so a caller that pushes `None` through an
`Optional`-typed call site still gets a loud refusal.

In `on_start`, inside the existing per-instrument loop, immediately before the
`MispricingContract(...)` construction at `strategy.py:247`:

```python
            try:
                theta = self._fee_coefficients.fee_coefficient_for(str(instrument_id))
            except UnknownFeeScheduleError as exc:
                raise UnpricedInstrumentError(...) from exc
```

and `fee_coefficient=theta` is added to the `MispricingContract(...)` keyword
arguments. Also in `on_start`, once per instrument:

```python
            if self._config.slippage_prob < float(instrument.price_increment):
                raise UnpricedInstrumentError(...)   # slippage below one tick
```

The tick floor lives at `on_start` rather than in the config because
`tick_size` is per-instrument and unknown at config construction
(`bucket_contract.py:41-43`: the captured universe carries more than one tick
size).

`_risk_limits()` (`strategy.py:276-293`) drops its
`transaction_cost_prob=cfg.transaction_cost_prob` line. See §2.7 — that
forwarding is already dead.

### 2.5 The decision call site — exact

`decision.py`, replacing the single line at `:245`:

```python
    fee_coefficient = contract.fee_coefficient
    if fee_coefficient is None:
        # An unresolved fee schedule is a NO-TRADE, never a free trade
        # (`adapters.polymarket_us.fees` docstring: "a market whose
        # coefficient we could not parse raises rather than trading free").
        # Unreachable through `strategy.py`, which raises at `on_start` -- this
        # is the independent-reuse guard, same posture as the degenerate-ask
        # guard above.
        return None

    fee_prob = venue_fee_prob(
        executable_price=ask_p,
        fee_coefficient=fee_coefficient,
    )
    cost = trade_cost_prob(
        executable_price=ask_p,
        fee_coefficient=fee_coefficient,
        slippage_prob=cfg.slippage_prob,
    )
    edge = model_p - ask_p - cost
    if edge < cfg.min_edge_after_costs:
        return None
```

`evaluate_instrument`'s signature is **unchanged**: the fee coefficient rides
on `contract`, which is already a parameter, and `slippage_prob` on `cfg`. The
function stays pure — no I/O, no clock, no adapter import.

The returned `SignalDecision.metadata` gains three keys, and this is
load-bearing for BL-19 §8.5, not decoration:

```python
            "fee_coefficient": fee_coefficient,
            "fee_prob": fee_prob,
            "slippage_prob": cfg.slippage_prob,
```

With `ask_p` (already carried as `market_probability`), `model_probability`
and `fee_prob` on the record, §8.5's requirement — "computed edge at
`slippage_prob` in {0.000, 0.010}" — is reconstructible offline from any
recorded decision, and the threshold is re-derivable **without re-running the
capture** when a measured slippage figure arrives. That is the whole point of
keeping the two terms separate and named.

### 2.6 Config changes

`CliSettlementPrintLockConfig`:

| Field | Action | Value | Why |
|---|---|---|---|
| `transaction_cost_prob` | **DELETE** | — | The scalar in which the unsafe configuration is written. §2.1. |
| `slippage_prob` | **ADD, REQUIRED, no default** | set 0.01 at the construction site | Same posture as `stale_observation_hours`: an explicit act at every construction site. Floored at `tick_size` in `on_start`. UNMEASURED — labelled as such in the docstring, with the §8.5 measurement obligation named. |
| `min_edge_after_costs` | **RETARGET** | `0.005` | BL-19 §8.6. Admits ask ≤ 0.98 (edge +0.005720), refuses 0.99 (-0.003698). |
| `min_model_edge` | **RETARGET** | `0.005` | `RiskManager.evaluate_order` re-applies `abs(edge) < min_model_edge` (`risk.py:421`) to the already-cost-netted number. Leaving it at 0.04 would silently override the decision layer's floor. |
| `edge_qty_scale` | **DELETE** | — | Recommendation 1: size no longer depends on edge. Deleting rather than zeroing removes the knob that re-enables the defect. |
| `base_quantity`, `max_quantity` | **KEEP** | 25.0, 150.0 | Now the anchor and the cap of the cost-basis rule. |
| `max_daily_trading_budget`, `max_notional_per_position` | **STAY UNSET** | — | Operator-reserved. Unchanged. |
| `allow_short` | **STAY `False`** | `False` | Unchanged. Long-only, taker. |
| `min_stable_prob` | **KEEP** | 0.97 | Non-binding at 0.996896. BL-19 §8.6. |

No change to `risk.py:100` (`RiskLimits.min_model_edge`) or `risk.py:116`
(`RiskLimits.transaction_cost_prob`) — but see §2.7, which corrects BL-19's
stated reason for leaving them alone.

**Tests this implies** (none of them a weakening):

* `test_cli_settlement_print_lock_strategy_construction.py:84` currently
  asserts `cfg.transaction_cost_prob == limits.transaction_cost_prob`. That
  assertion pins a plumbing equality for a field nothing reads (§2.7) and
  becomes unconstructible once the config field is gone. **Replace it with a
  strictly stronger structural pin:** assert that
  `CliSettlementPrintLockConfig` exposes **no** field whose name contains
  `transaction_cost` or otherwise denotes a total cost — i.e. assert the
  unsafe knob does not exist. That is a tightening, not a relaxation, and it
  is the test that keeps §2.1's hazard closed against a future re-add.
* A new test that `slippage_prob` below the instrument's `price_increment`
  raises `UnpricedInstrumentError` at `on_start`.
* A new test that a contract with `fee_coefficient=None` yields `None` from
  `evaluate_instrument` (the independent-reuse guard).
* An **agreement test** pinning `venue_fee_prob(executable_price=p,
  fee_coefficient=theta) * C` against
  `PolymarketUSFeeModel.get_commission(...)` for the same `(theta, p, C)`, up
  to the banker's-rounding quantum. The gate-time estimate and the
  settlement-time authority must not drift; this is the test that makes the
  duplication safe.
* Property tests on `venue_fee_prob`: non-negative on [0, 1], symmetric about
  0.5, maximal at 0.5, monotone decreasing on [0.5, 1], raises outside [0, 1].
* Property tests on the sizer: cost basis is constant in `ask` over the
  admitted range up to the `max_quantity` and depth clips; quantity is never
  negative, never NaN, never exceeds `max_quantity` or `visible_depth`; and
  quantity is **not** monotone increasing in edge (the regression guard for
  Recommendation 1).

### 2.7 Correction to BL-19 §4.1 — `RiskLimits.transaction_cost_prob` is dead

BL-19 §4.1 argues against changing `risk.py:116` because "changing them would
silently move every unpinned harness baseline". **That is not true of
`transaction_cost_prob`, and the distinction matters for the blast radius of
this change.** Verified by reading `risk.py` end to end: the identifier
`transaction_cost_prob` appears in that file exactly once, at its own
definition on line 116. `RiskManager.evaluate_order` never reads it;
`edge_after_costs` takes `cost` by injection; `quote_tradable` does not use
it. Every strategy reads its **own** `cfg.transaction_cost_prob` in its own
`decision.py`, and each `_risk_limits()` forwards a copy into a field no
consumer consumes.

Consequences:

* Removing the field from `CliSettlementPrintLockConfig` and dropping the
  forwarding line changes **no** risk-layer behaviour. The blast radius is one
  construction-site assertion (§2.6).
* BL-19's caution about `risk.py:100` (`min_model_edge`) is entirely correct
  and unaffected — that field *is* read, at `risk.py:421`.
* `RiskLimits.transaction_cost_prob` should be left in place for now (removing
  it is a four-strategy change outside this scope) but flagged as dead
  weight, with its misleading `# fees + expected slippage in prob units`
  comment corrected — BL-19 §1.2 already established it contains no slippage.

### 2.8 What would falsify Recommendation 2

1. **Measured slippage is materially below one tick.** The whole 0.98-vs-0.99
   decision rests on the 0.01 placeholder (BL-19 §8.2 says so plainly: at ask
   0.99 the edge after fee alone is +0.006302 and clears the floor; only the
   placeholder pushes it to -0.003698). If realised taker fills at level 0
   come in at the quoted ask, the tick floor on `slippage_prob` is refusing
   real trades and the floor must be re-derived — **not removed**, since a
   floor of zero restores the exact unsafe configuration §2.2 exists to
   forbid. The honest replacement would be a measured floor with the same
   fail-closed shape.
2. **A traded market carries no `feeCoefficient`.** Then `on_start` raises and
   the strategy will not run on it. Currently [MEASURED] 20/20 captured
   weather markets carry `feeCoefficient: 0.06`, so this is not the expected
   case — but if the venue stops publishing it, the correct response is that
   the strategy does not trade that market, never a 0.06 default.
3. **`theta` turns out to differ per market.** The design already reads it per
   instrument, so it self-corrects; only §1's tables would need re-deriving.
4. **A finer tick appears.** `a_max` moves off 0.98, the tick floor on
   `slippage_prob` loosens below 0.01, and 0.99-region prices become
   representable. Both §1's anchor and §2.2's proof recompute correctly from
   `contract.tick_size` — but the "buy at 0.98 or better" sentence stops being
   the summary.

---

## 3. Two further findings, recorded not actioned

1. **BL-19 §8.4's alert threshold is mis-calibrated.** It proposes alerting
   when the ask is "more than ~0.20 below break-even". Break-even is 0.996698,
   so that alert fires at any ask below **0.7967** [DERIVED] — which is most
   of the price range the strategy's own thesis predicts it will trade in
   (§2-3 of the spec: the ask "remains below `1 - cost - revision_haircut`"
   overnight). An alert that fires on the modal case is an alert nobody reads.
   Derive the threshold from the recorded ask distribution once §8.5's
   instrumentation has produced one; until then, log at INFO with the mapping
   fields and do not page.
2. **`conviction` is computed and never consumed.**
   `decision.py:264-271` computes `min(1.0, margin_f / 2.0)` and puts it on
   the `SignalDecision`; nothing downstream reads it. It is the only
   corroborating variable the strategy possesses (a print sitting on a bucket
   boundary loses the bucket to a single 1F correction; one in the middle
   survives it). Using it to size **up** is forbidden — no measured
   margin-keyed table exists for the final print, and BL-19 §8.1(1) shows the
   omission is currently conservative. Using it to size **down** at margin 0
   is defensible and is the natural next refinement once the §8.5 record can
   show whether margin-0 prints revise out of bucket at a different rate.
   Follow-up, not this change.

---

## 4. Build order

Phased, for the implementing agent. Phase 1 and Phase 2 are independent of
each other and may run in parallel; Phase 3 depends on both.

**Phase 0 — pre-flight (read-only, blocking).**
Confirm on the current captured instrument list that (a) every weather bucket
carries `info[FEE_COEFFICIENT_KEY]` with `fee_schedule_status = KNOWN`, and
(b) `price_increment` is 0.01 on all of them. If (a) fails anywhere, stop and
report — the fail-closed `on_start` raise would brick the strategy, and the
answer is not a default. If (b) fails, re-derive `a_max` and the §1 tables at
that tick before proceeding.

**Phase 1 — the cost seam (RED first).**
1. `weather_common/costs.py`: `UnknownFeeScheduleError`, `FeeCoefficientSource`,
   `venue_fee_prob`, `trade_cost_prob`. Property tests first.
2. `bucket_contract.py`: additive `fee_coefficient: float | None = None`.
3. Agreement test `venue_fee_prob` ↔ `PolymarketUSFeeModel.get_commission`.

**Phase 2 — the sizer (RED first).**
4. `decision.py` sizing block: replace the affine-in-edge term with the
   constant-cost-basis rule. Property tests first, including the
   non-monotone-in-edge regression guard.
5. Regression: pin the §1.5 table (ask → quantity) as a parametrised test.

**Phase 3 — wiring (depends on 1 and 2; SEQUENCED AFTER the concurrent
`adapters/polymarket_us/` and `runtime/` work).**
6. Adapter: promote `_fee_coefficient` → public `read_fee_coefficient`, export
   it. Rename only.
7. `runtime/taker_cost.py`: `PolymarketUSFeeCoefficients`.
8. `cli_settlement_print_lock/config.py`: delete `transaction_cost_prob` and
   `edge_qty_scale`; add required `slippage_prob`; retarget
   `min_edge_after_costs` and `min_model_edge` to 0.005.
9. `cli_settlement_print_lock/strategy.py`: `UnpricedInstrumentError`,
   constructor injection, `on_start` resolution + tick floor, drop the dead
   `transaction_cost_prob` forwarding.
10. `decision.py`: the §2.5 call site and the three metadata keys.
11. `scripts/analysis/run_weather_strategy_backtests.py`: supply the
    `FeeCoefficientSource` and `slippage_prob = 0.01` at the one construction
    site, with the derivation written out beside
    `STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK`.
12. Replace the construction-site assertion at
    `test_cli_settlement_print_lock_strategy_construction.py:84` with the
    stronger structural pin (§2.6).

**Phase 4 — docs.**
13. Amend `docs/strategies/breezy_strategy_cli_settlement_print_lock.md` §5's
    CORRECTION block to note that the 0.98 ceiling is now enforced
    structurally rather than by a config value, and record §3's two findings
    in `docs/core/PROGRESS.md`.

Gate for every phase: `scripts/ci/run_tests_no_egress.sh`, plus `lint-imports`
(the layers contract is touched by Phase 3) and `mypy --strict`.
