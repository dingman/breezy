# Backtest venue configuration — POLYMARKET_US

Status: **IMPLEMENTED.** `src/breezy/runtime/backtest_harness.py:713-714` calls
`engine.add_venue(venue=POLYMARKET_US_VENUE, ...)` and names this document as its
authority at `backtest_harness.py:3`. (The previous line — "specified, not yet
implemented ... as of 2026-08-27" — was true when written and is now false.) This
document fixes the argument values before the harness is written, so that the
defaults — several of which are silently wrong for a 0-1 binary market — are
chosen deliberately rather than inherited.

Every claim below was verified against the installed Nautilus Trader 1.231.0
source. Nautilus is IMMUTABLE; nothing here proposes changing it. Every choice
is a native `add_venue` argument or an injected data record.

## 0. The finding that governs everything else

**`InstrumentClose.close_price` is never read by the engine.**

`SimulatedExchange.process_instrument_close` (`backtest/engine.pyx:4832-4848`)
stores the object as a *trigger* only, and only when
`close_type == InstrumentCloseType.CONTRACT_EXPIRED`. `END_OF_SESSION` falls
through and is silently discarded.

The settlement price comes exclusively from the `settlement_prices` dict passed
to `add_venue` (`engine.pyx:5965-5978`):

```
if self._settlement_prices and self.instrument.id in self._settlement_prices:
    ... apply_fills(order, fills=[(settlement_price, position.quantity)], ...)
else:
    self.fill_market_order(order)     # <-- closes at the PREVAILING BOOK
```

So an `InstrumentClose` carrying `close_price=Price(1.00)`, with the instrument
**absent from `settlement_prices`**, closes the position at the last market
price. For a weather binary, **settlement IS the PnL** — this silently replaces
the entire economics of the strategy with a mark-to-market artifact.

The error is worse than random: it is *mean-reverting*. Winners close near 0.97
instead of 1.00 and losers near 0.03 instead of 0.00, compressing the PnL
distribution symmetrically. Variance falls, the equity curve smooths, and
**Sharpe improves**. Nothing logs and nothing raises. `settlement_prices`
defaults to `None`, so this is the behaviour you get by doing nothing.

## 1. Argument table

| Argument | Value | Reason |
|---|---|---|
| `venue` | `Venue("POLYMARKET_US")` | — |
| `oms_type` | `OmsType.NETTING` | Token-balance CLOB: you hold N YES tokens, not lots. HEDGING would permit simultaneous long and short in one `InstrumentId` — economically impossible — and would fan `positions_open` at settlement. |
| `account_type` | `AccountType.CASH` | See §2. Explicitly **not** `BETTING`, and not `MARGIN`. |
| `base_currency` | `USD` | **Not `None`.** Multi-currency removes the last remaining sell check — see §2. |
| `starting_balances` | `[Money(<capital>, USD)]` | Capital allocation is an operator budget decision, not a venue fact. |
| `book_type` | `BookType.L2_MBP` | See §3. The `L1_MBP` default is a trap. |
| `fill_model` | `FillModel()` (default) | See §4. Never `BestPriceFillModel`. |
| `fee_model` | `PolymarketUSFeeModel()` | Mandatory; barrier F2 fails the build otherwise. Also yields fee = 0 at settlement for free (§5). |
| `latency_model` | `None` — **a known overstatement** | Zero-latency fills. Uncalibratable without live observation (§6). Must be labelled in any result. |
| `liquidity_consumption` | `True` | Default `False` lets each iteration fill against the full book independently (`engine.pyx:608-611`) — one stale Depth10 snapshot refills infinitely. Requires `book_type != L1_MBP` (`engine.pyx:4697`). |
| `trade_execution` | `False` | The adapter publishes no `TradeTick`. `True` arms the bid/ask-override path (`engine.pyx:4686-4692`) if a trade ever leaks in. |
| `bar_execution` | `False` | No bars. Inert at L2 but explicit, and stays safe if `book_type` changes. |
| `bar_adaptive_high_low_ordering` | `False` | No bars. |
| `queue_position` | `False` | Requires `trade_execution=True`, which requires a trade tape Breezy does not have. |
| `reject_stop_orders` | `True` (default) | Correct. |
| `support_gtd_orders` | `True` (default) — **unverified** | Whether the venue honours GTD is an unobserved venue fact (§6). |
| `support_contingent_orders` | `False` | Do not backtest OCO/OTO semantics never observed on the venue. The `True` default grants them silently. |
| `use_reduce_only` | `True` (default) | The engine's own settlement close order is `reduce_only=True` (`engine.pyx:5957`). |
| `use_position_ids` | `True` (default) | — |
| `use_random_ids` | `False` (default) | Determinism. |
| `use_market_order_acks` | `False` (default) | — |
| `allow_cash_borrowing` | `False` (default) | `True` disables every `free`-balance check (`risk/engine.pyx:949,968,1001,1026`). |
| `frozen_account` | `False` (default) | — |
| `default_leverage` / `leverages` / `margin_model` | omit | Ignored on CASH. |
| `price_protection_points` | `None` — **unit undefined** | Docstring does not define "points" against `price_increment`. Do not guess a boundary that might reject every marketable order. |
| `routing` | `False` (default) | Single venue. |
| `settlement_prices` | `{instrument_id: 0.0 or 1.0}` for **every** instrument in the run | See §0 and §5. |
| `oto_trigger_mode` | omitted (default `OtoTriggerMode.PARTIAL`) | Inert while `support_contingent_orders=False`. **Not covered by the source-level argument pin** because it is not passed. |
| `use_message_queue` | omitted (default `True`) | An engine-internal mechanism, not a venue fact. **Not covered by the source-level argument pin.** |

## 2. `account_type` — CASH, with a harness-side guard

`CashAccount.balance_impact` (`accounting/accounts/cash.pyx:489-493`) returns
`-notional` for BUY and **`+notional` for SELL**. The `RiskEngine` check
(`risk/engine.pyx:949`) is `(free + balance_impact) < 0`, which with a positive
impact **can never fire for a SELL**.

1.231.0 exempts position-reducing sells entirely (`risk/engine.pyx:975-987`), so
the only sells reaching that gate are **naked** ones — precisely where it is
meaningless. The secondary gate (`:996-1006`, `cum_notional_sell > free`)
compares gross proceeds against free cash and passes trivially for any sensible
size; it is not a solvency check.

Economically: on a Polymarket CLOB you cannot sell tokens you do not hold.
"Short YES" is not a venue primitive — it is spelled "buy NO", a separate
`InstrumentId` with its own book and its own edge. After a naked short fills,
the account shows *more* free cash than before and carries no reserve, because
Nautilus reserves against open **orders**, not open **positions**. Sizing logic
then compounds off capital that does not exist, while terminal PnL arithmetic
stays correct — so the backtest looks fine.

**Therefore: `AccountType.CASH` plus an invariant that no SELL exceeds the
cached net long quantity for that instrument.**

That invariant lives in **the harness**, not in each strategy. It was
originally specified strategy-side, and that placement was wrong: it asks every
strategy author to re-derive the rule from this paragraph, which they may never
read. One did not, and it cost a verified live failure — a `LIMIT SELL` for 500
contracts against a **zero** position and \$1,000 of cash was accepted and
filled 50, with no rejection and no warning anywhere.

It is enforced by `breezy.runtime.backtest_order_guard.BacktestOrderGuard`,
which subscribes to the native `events.order.*` message-bus topic and screens
each `OrderInitialized` at **submit** time — the earliest observation point the
framework offers (`trading/strategy.pyx:855-859` publishes it before the
duplicate-id check, before `cache.add_order`, and before the `RiskEngine`). A
SELL is refused when `already-working sells + this order > net long`, unless it
is `reduce_only`. The engine's own settlement leg never passes through the
screen: `check_instrument_expiration` adds its order to the cache directly and
publishes no `OrderInitialized` (`backtest/engine.pyx:5952-5966`).

A strategy is still free to keep its own guard, and `resting_ladder` does; what
changed is that forgetting one is no longer silent.

`BETTING` is the tempting wrong answer and is definitively wrong.
`BettingAccount.balance_impact` (`accounting/accounts/betting.pyx:84-86`)
computes BUY as `-notional * (price - 1.0)`, assuming decimal odds >= 1.01. For
`price` in [0,1] the term `(price - 1.0)` is negative, so the BUY impact flips
**positive** — buying would appear to add cash. `MARGIN` invents leverage on an
instrument with `margin_init = margin_maint = 0`
(`instruments/binary_option.pyx:146-147`) and a hard $1 payout cap.

## 3. `book_type` — L2_MBP

Breezy can capture `QuoteTick`, `OrderBookDepth10`, `InstrumentStatus`, plus its
own `DepthTruncation` / `QuoteTapeGap` / `VenueSettlementSnapshot` records — ten
levels per side.

Under `L1_MBP` (the default), levels 2-10 are discarded, and a MARKET order that
exhausts top-of-book fills its **entire remaining quantity** at
`last_fill_px ± one price_increment` (`engine.pyx:7437-7460`). One tick is $0.01
— 1% of maximum payout. An order for 5,000 contracts into a book holding 40 at
0.98 fills 40 @ 0.98 and 4,960 @ 0.99. That backtest looks excellent and is
fiction.

**Coupling that must be stated:** `process_quote_tick` updates the internal book
**only** under `L1_MBP` (`engine.pyx:4551`). Choosing `L2_MBP` makes the
QuoteTick tape inert for execution — the book is driven **entirely** by Depth10.
So Depth10 coverage, not quote coverage, is the binding constraint on backtest
validity, and `QuoteTapeGap` intervals must be evaluated against the **depth**
stream. Any window with quotes but no depth is a window where orders match
against a frozen or absent book.

`L3_MBO` is unavailable: the venue publishes aggregated levels, not per-order
queue identity.

**Per-instrument precision.** Depth10 book orders must match
`instrument.size_precision` exactly or the engine raises `RuntimeError`
(`engine.pyx:4444-4471`). Captured instruments carry **variable** size
precision — one market has `size_precision=2, min_quantity=0.01`, another
`size_precision=0, min_quantity=1`. Precision must be read per instrument, never
from a venue-wide constant.

## 4. `fill_model` — the default is the honest choice

`FillModel()` defaults are `prob_fill_on_limit=1.0`, `prob_slippage=0.0`
(`backtest/models/fill.pyx:59-63`).

`prob_slippage` is **inert under L2_MBP** (`engine.pyx:7382` gates on L1);
tuning it would be a no-op that reads like risk modelling, which is worse than
leaving it alone. `prob_fill_on_limit=1.0` is optimistic for a resting maker
order, but Breezy is taker-only by construction: `PolymarketUSFeeModel` refuses
post-only orders (`MakerRebateUnmodelledError`) because the modelled maker fee
is wrong **in sign**.

**`BestPriceFillModel` must never be used.** It returns a synthetic book with
`UNLIMITED = 1_000_000` at best bid/ask and `fill_limit_inside_spread() -> True`
(`fill.pyx:165-190`). On a market where real depth is often tens of contracts,
that is catastrophic.

The correct lever for thinness is real Depth10 data plus
`liquidity_consumption=True` — not a coin flip.

## 5. Settlement injection

Requires **two coordinated artifacts**. Either alone is silently wrong.

**(a) The trigger** — one `InstrumentClose` per instrument, in the data stream:

```python
InstrumentClose(
    instrument_id=instrument.id,
    close_price=Price(px, instrument.price_precision),  # recorded for audit; ENGINE IGNORES IT
    close_type=InstrumentCloseType.CONTRACT_EXPIRED,    # END_OF_SESSION is silently dropped
    ts_event=<VenueSettlementSnapshot settlementSetTime>,
    ts_init=<strictly greater than the last depth/quote ts_init for this instrument>,
)
```

**(b) The price** — `settlement_prices` at `add_venue` time. Derived per
instrument from Breezy's own recorded truth:

1. Take the `VenueSettlementSnapshot` with `is_terminal=True`.
2. Parse `settlement_px` as `Decimal`.
3. **Assert it is exactly `0` or `1`.** A weather binary settling anywhere else
   is a void or ambiguous resolution and must **raise** — never be silently
   quantized to `price_precision=2`.
4. Cast to `float` for the dict.

### Invariants to pin as tests, in the spirit of barrier F2

- `set(settlement_prices) ⊇ {instruments receiving a CONTRACT_EXPIRED close}`.
  A miss falls into the `fill_market_order` branch. **Highest-value guard in the
  entire configuration.**
- Every value is exactly `0.0` or `1.0`. Anything else fabricates a settlement
  fee the venue never charges: `PolymarketUSFeeModel` computes
  `theta * C * p * (1-p)`, which is zero **only** at the endpoints.
- Every `InstrumentClose.ts_init` strictly exceeds the last market-data
  `ts_init` for its instrument. `_expiration_processed` is a one-shot latch
  (`engine.pyx:5936-5941`) that also **cancels all open orders**; an early close
  kills the instrument for the rest of the run and yields a shorter, calmer,
  entirely plausible equity curve.
- Gate the trigger on `is_terminal`, never on the mere presence of
  `settlementPx` — that field appears on live markets too, meaning something
  different.

### 1a. Settlement is the ONLY trigger, not merely the timing

`BinaryOption.instrument_class == BINARY_OPTION`, which is **absent** from
`ENGINE_EXPIRING_INSTRUMENT_CLASSES` (`model/instruments/base.pyx:67` — the set
is exactly `FUTURE`, `FUTURES_SPREAD`, `OPTION`, `OPTION_SPREAD`). So
`_instrument_has_expiration` is `False` for every Breezy instrument and the
time-based expiration branch **can never fire**.

The injected `InstrumentClose` is therefore the *sole* settlement trigger. An
omitted or mis-ordered close does not merely mis-time settlement — the position
**never settles at all**, and is left marked to the last quote as unrealised.
This makes the §5 ordering invariant stronger than "get the timestamp right":
it is the difference between a settled book and a permanently open one.

## 6. Requires live venue observation

The bot must discover these itself; the operator never supplies venue facts.

| Item | What must be observed |
|---|---|
| `latency_model` | Round-trip submission → `OrderAccepted` → first fill, sampled across the day. `VenueClockOffset` is the right substrate but not the same quantity. Until measured, `latency_model=None` **overstates reaction speed**. |
| True book depth | Whether the ladder exceeds 10 levels. `DepthTruncation` records already measure this. If truncation is common, L2 on Depth10 *understates* size — conservative, but must be quantified. |
| Maker fee coefficient | Sign and magnitude. Documented `-0.0125` (a rebate) but unobserved. Until a maker fill is captured, every maker result is unevaluable **by sign**. |
| Settlement regimes | Whether a void or early expiry ever yields `settlement_px` outside {0, 1}. Determines whether §5 step 3 is a guard or a blocker. |
| `support_gtd_orders` | Whether the CLOB honours GTD. The `True` default backtests an order type that may not exist. |
| Per-market size precision | Already known to vary. Must be read per instrument (§3). |

## 7. Ranked: wrong but looks fine

Ranked by (probability of getting it wrong) x (invisibility).

1. **`settlement_prices` missing or incomplete.** §0. Mean-reverting error,
   flattering direction, `None` is the default.
2. **`book_type` left at `L1_MBP`.** Unlimited size at one tick worse than
   top-of-book. Converts an unfillable strategy into a profitable one. It is
   the default.
3. **`liquidity_consumption` left `False`.** One snapshot refills infinitely.
   The error you make *after* fixing (2).
4. **CASH without a naked-short guard.** Free balance rises when a short fills;
   sizing compounds off phantom capital. Terminal PnL still correct, so the only
   symptom is positions that could never have been funded. Closed by
   `breezy.runtime.backtest_order_guard` — see §2.
5. **`base_currency=None`.** `BinaryOption.get_base_currency()` returns `None`,
   so both sell-check branches (`risk/engine.pyx:996`, `:1007`) evaluate False
   and **every sell check disappears.** Strictly worse than (4).
6. **`oms_type=HEDGING`.** PnL sums correctly; the position ledger describes an
   impossible state.
7. **`fee_model` defaulted.** Low only because barrier F2 fails the build.
   Absent it, this would rank second — it would charge a nonzero settlement fee.
8. **`support_contingent_orders=True`.** Grants order semantics never observed.

## 8. Kalshi portability

`account_type=CASH`, `base_currency=USD`, `oms_type=NETTING`, and
`book_type=L2_MBP` transfer cleanly. These do not:

- **YES/NO topology.** Polymarket: two `InstrumentId`s, two books. Kalshi: two
  sides of **one** book — resting a NO bid *is* offering YES. Getting the
  mapping wrong double-counts exposure.
- **Naked shorting.** Kalshi permits collateralized shorts, so the strategy-side
  guard correct here becomes an artificial constraint there — silently
  suppressing trades rather than erroring.
- **Fee formula.** Same `theta*C*p*(1-p)` shape, so fee-is-zero-at-settlement
  survives, but theta differs and Kalshi rounds **up** per trade where
  Polymarket uses banker's rounding on the cumulative.
- **Price bounds.** Kalshi trades 0.01-0.99; 0.00 and 1.00 are settlement-only.
- **`trade_execution=False`.** Kalshi publishes a real trade tape. This choice is
  correct *today* only because Breezy has no trade data — that reason expires.

## 9. Open, stated as unknown

- Whether L2 is *materially* better than L1 in this universe depends on how
  often real depth exceeds one level. The mechanism argument is airtight from
  the engine source; the magnitude is unmeasured.
- `price_protection_points` semantics.
- Whether resting-limit behaviour under L2 + `liquidity_consumption=True` is
  adequately conservative. `engine.pyx:7519-7524` shows the MAKER branch
  skipping fills and leaving the order open — the conservative direction — but
  the full maker path was not traced, and the fee model refuses maker-intent
  orders anyway, so this is moot rather than resolved.
- `starting_balances` sizing — an operator budget decision.
