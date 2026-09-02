# Blind risk views — audit findings, 2026-09-02

Three read-only sweeps, run after T-1 revealed that six separate defects in one
session shared a single shape: **a risk control reading a view that structurally
cannot contain what it needs.** T-1 fixed one instance (`cache.orders_open`
excludes INITIALIZED and SUBMITTED). This audit asked how many more exist.

Every claim below was verified at source by the coordinator before being
recorded. Line numbers are as of `ff21d94`.

## T-2 [HIGH, FIXING] `_flatten` returns early on a settled-only quantity

`forecast_mispricing/strategy.py`, `calibration_mean_reversion/strategy.py`,
`forecast_revision/strategy.py` — byte-identical. `_flatten` reads
`portfolio.net_position(nt_id)` and returns when it is ~0, **three lines above**
the cancel. `net_position` is settled-only: a `Position` exists only after a
fill. So with zero settled contracts and a working order, nothing is cancelled.

**Hazard.** 0 settled, BUY 200 submitted on tick N. On tick N+1 the final
`NwsClimateDay` arrives -> `_flatten(iid, "observation_received")` -> returns at
the guard. The BUY fills *after* the settlement-determining observation is
public — the exact outcome `flatten_on_observation` exists to prevent — and no
FLATTEN log line is emitted, so it is silent. Same path for `settlement_halt`.

**Own-goal, recorded deliberately.** T-1 deleted a `cache.orders_open`
pre-filter here and replaced its comment with "UNCONDITIONAL, deliberately"
while a second, equally blind pre-filter sat above it, unnoticed. Commit
`ff21d94`'s message repeats that false claim. This is [[L-18]] committed inside
the fix for the defect that motivated L-18.

**Residual that this fix does NOT close:** Nautilus `cancel_all_orders`
(`trading/strategy.pyx:1296-1298`) explicitly `continue`s on INITIALIZED, and
INITIALIZED is in none of `orders_open` / `orders_inflight` / `orders_emulated`.
An INITIALIZED order remains uncancellable by anyone.

## T-3 [HIGH] `open_position_count()` counts settled positions only

`weather_common/risk.py:231-233` — `sum(1 for q in self.position_qty.values()
...)`, and `position_qty` is built solely from `portfolio.net_position`.
Consumed by the `max_simultaneous_positions` refusal at `risk.py:496-499`.
Every *other* cap in `evaluate_order` uses `net_qty` (settled + pending);
this one alone does not. The sibling `pending_qty` — the field T-1 widened —
sits in the same snapshot and is never consulted here.

**Hazard.** `max_simultaneous_positions=12`, all instruments flat. A depth burst
delivers ticks for 20 contracts on one handler thread, so all 20 evaluate before
any fill returns. The per-instrument in-flight gate is keyed on *that*
instrument and cannot see orders on the other 19; `open_position_count()`
returns 0 every pass. 20 BUYs go out and fill: **20 positions against a cap of
12.** T-1 widened the query but not this consumer.

## T-4 [HIGH] `_equity()` returns a config constant or a connect-time snapshot

`_equity()` in all five strategies (e.g. `forecast_mispricing/strategy.py:422-433`),
consumed by `max_equity_fraction` at `risk.py:502-507` (default 0.08).
`Account.balance_total` returns `None` rather than zero when it has no
information; both misses `continue`, and the loop falls through to
`return self._config.starting_equity` — **default `10_000.0`**.

Worse, the balance never updates: Breezy's account carries
`calculate_account_state=False`, so `Portfolio.update_order` never touches a
balance on a fill, and `_publish_account_state` is reached only from `_connect`
and `_query_account`. `QueryAccount` is emitted only by `Strategy.query_account`
— **no Breezy strategy calls it** (0 hits across `src/` and `scripts/`).

**Hazard.** A constant and a stale reading are indistinguishable from a
measurement, and nothing logs the difference.

**Severity corrected on review — my first statement of it was wrong.** I wrote
that the cap "authorises $96 — 53% of true equity", which conflated payout with
cash. `contract_size = 1.0`, so `order_notional` is **max payout, not cash
outlay**: the cap is `0.08 x equity` *contracts*. `max_position_contracts=250`
therefore dominates whenever `0.08 x E > 250`, i.e. above E = $3,125, and at the
fabricated $10,000 the equity cap is 800 contracts and **inert**. Real cost at a
live-small $1,200: intended cap 96 contracts, actual 250 — **2.6x intended**,
not 8.3x, because `max_position` clamps it. Cash bite is price-dependent: 250
contracts at a 5c ask is $12.50; at 0.90 it is $225, i.e. 19% of a $1,200
account against an intended 8%. Real, bounded, and worst at high ask prices.

**A third mechanism, worse than either, found in review.** `risk.py:557` reads
`if portfolio.equity > 0 and order_notional > limits.max_equity_fraction *
portfolio.equity`. At `equity == 0.0` the condition is False: no clip, no
refusal, full size. The cap disappears exactly when the balance reads zero.

**But zero is NOT established as ruin — my second error here.** `balance_total`
returns the venue's `currentBalance` on an `AccountType.CASH` account. Position
value is a *separate* venue field, `assetNotional`, which nothing in Breezy
reads. Whether `currentBalance` includes position notional is **UNVERIFIED**.
So `equity == 0.0` is at least as plausibly "fully deployed and solvent" as
"drained". Refusing new BUYS at zero cash is right; refusing SELLS would
deadlock the close-only exit — the trap `risk.py:570-577` explicitly refuses to
create for the depth clip. Any fix must gate its refusals on
`signed_qty_delta > 0`. Two independent reviews reached that requirement
separately.

## T-5 [MEDIUM] Settlement halt is unreachable when the forecast source returns None

`forecast_mispricing/strategy.py:255-262`, mirrored in `calibration_mean_reversion`
and `forecast_revision`: `if forecast is None: return` executes **before** the
`halt_hours_before_settlement` check. 200 contracts held, T-minus-70 min, the
provider drops the station/day -> every tick returns early, `settlement_halt`
never fires, the position rides into settlement. The module docstring states
"never flatten-for-lack-of-forecast" is deliberate, so this is a stated trade —
but the exit it disables is the one the halt exists for, and the trade was
plausibly never made with this consequence in view. Decide explicitly.
`running_extreme_lock:333` uses a clock-derived horizon and is not exposed.

## T-7 [MEDIUM, NEW] The `ForecastSource` liveness contract is prose, and it is already violated

Found while implementing T-5. `forecast_mispricing:18-19` and
`forecast_source.py:53-56` state that `ForecastSnapshot.horizon_hours` "must
already be the live hours-remaining-to-settlement as of the `now` the source was
called with." **`ForecastSource` is a `Protocol` with no liveness constraint, and
no test pins it.** Of four in-repo implementations, one conforms
(`run_weather_strategy_backtests.py:513`, `hours_until(now, deadline)`) and
**two are explicitly frozen** — `_SyntheticForecastSource` admits it in its own
docstring ("held constant for this short test run rather than recomputed from
`now`"), and `_ConstantForecastSource` returns 24.0 and ignores `now` entirely.

**The divergence is realized, not hypothetical.** In two live-exercised fixtures
the instrument's native `expiration_ns` puts settlement 0.004-0.28 hours away
while the forecast source reports a constant 24.0 — a gap of nearly a full day,
in the value that feeds `hours_to_settlement` on every `PortfolioSnapshot` and
therefore every risk cap that reads it.

Consequence to weigh at go-live: a risk cap keyed on hours-to-settlement is only
as live as an unpinned prose contract. Whether this is inert in production
depends on the conforming implementation being the only one used outside tests —
worth confirming rather than assuming, since the same reasoning ("only the good
implementation is real") is what left the contract unpinned.

Also noted, same investigation: `settlement_deadline_by_station` in the backtest
script is keyed by **station** and takes the first matching instrument's
`expiration_ns` via `next(...)`. A station whose bucket ladder carried
non-uniform expirations would feed an arbitrary bucket's deadline where a
clock-derived value is per-instrument. Uniformity is asserted for synthetic tapes
(`tests/contract/test_multi_instrument_weather_strategy.py:114-118`) but nothing
enforces it in the script.

## T-6 [LOW] `node_config.py:11-14` describes a removed mechanism

The module summary says `build_trade_node_config` has "zero exec clients". It
now takes `exec_client_config` (`:554-558`) and its own docstring says the
opposite at `:575-583`. The NO-SEND property rests entirely on the standing
refusal inside `exec/client.py`, not on the absence of a client. An auditor
reading the summary concludes the process cannot submit, and treats the
client's internal cage as redundant.

## Dead and unwired controls (inventory, not defects today)

Nothing trades — all three live node configs pass `strategies=[]`
(`node_config.py:229, 480, 699`) — so these are preconditions on go-live, not
live holes. Verified caller counts:

- **The live-trading permit system is entirely unwired.**
  `assert_live_order_submission_permitted` (`safety.py:668`) has zero callers in
  `src/`; a barrier (B6/B7) bans it from having one.
  `LiveOrderSubmissionAuthorization` (`:408`) — the capability token it returns
  — has **zero consumers**, so even if the chokepoint were called, nothing
  requires possession of its output. `live_trading_budget_remaining` (`:646`)
  has zero callers, so budget exhaustion is unobservable.
  **Correction to the review that found this:** the per-order notional check is
  NOT missing — `safety.py:722` enforces
  `order_notional_usd > permit.max_order_notional_usd`. It is implemented and
  correct; it is simply inside the function nobody calls. R-7 therefore needs
  the chokepoint **wired plus a consumer that requires the authorization**, not
  a new notional gate built.
- **The entire strategy risk surface is backtest-only.** `RiskManager` and
  `evaluate_order` have zero occurrences in `runtime/` or `cli/`. Every cap —
  position, notional, event/location payout, position count, equity fraction,
  settlement halt — arrives only with the first `ImportableStrategyConfig`. Until
  then the live node's sole control is `BacktestOrderGuard` via
  `install_live_order_guard`, which covers post-only and naked-short and nothing
  else.
- `active_forbidden_403_sites` (`ingest/shared_state.py:563`) — zero src
  callers. The cross-site 403 burst window IS maintained, but its state never
  reaches a log or alert: a venue-wide 403 ban would be detected and silently
  discarded.
- `SalvageResult.require_complete` (`persistence/feather_preflight.py:258`) —
  zero src callers, and its producer `salvage_feather_file` has none either.
  Whoever first wires salvage into recovery will most naturally take `.table`
  and silently reintroduce the truncated-tape defect the module exists to close.
- `assert_archive_base_disjoint` (`persistence/archive_catalog.py:21`) — zero
  callers in `src/` or `scripts/`; its own docstring says it is "the ONLY check
  on those base values, not defence in depth". The archive job has not landed.
  It must run before that job's first `mkdir`, or an archive root can nest
  inside the settlement catalog and corrupt settlement truth.

## Checked and sound (negative results, on record)

The `exec/client.py` reconciliation surface (every failure latches a node-global
refusal rather than returning empty, incl. the three-way `_read_fill_index`);
`parse_account_balances` refusing empty/non-USD; `available_ask_depth` refusing
on unknown depth; `quote_tradable` checking negative age before staleness;
`_iter_mount_entries` degrading to fail-closed `UNDETERMINED`; `settled_qty`
correctly excluding pending for the close-only guard; the `SharedExposureMixin`
inheritance across all five strategies.

## T-8 [MEDIUM] T-5 fixes the EXIT; ENTRY is still gated on the frozen horizon

Residual after T-5, stated so it is not mistaken for closed. The settlement halt
now derives its horizon from the clock and the native `expiration_ns`, but
`hours_to_settlement=forecast.horizon_hours` still flows into the
`PortfolioSnapshot` (`forecast_mispricing:360`, `calibration:386`,
`revision:378`), and `RiskManager.evaluate_order`'s **first** gate is
`hours_to_settlement < halt_hours_before_settlement` (`risk.py:517`), with
`min_hours_to_settlement` right behind it.

**RETRACTED, both halves — I was wrong twice and the corrections matter.**

I claimed a frozen horizon lets a **new position open 90 minutes before
settlement**. It cannot. `risk.py:531` refuses the order on
`forecast_age_hours = now - published_at`, which is clock-derived and immune to
a lying `horizon_hours`. **No order ships.** The real exposure is narrower: the
`:519` `min_hours_to_settlement` gate can fail open only in the window
T-t in (1.0, 2.0) h — one hour wide — and divergence on any *submitted* order is
bounded by `stale_forecast_hours = 8.0`.

I also claimed the 24 h sigma bin **overstates** edge. **Backwards.** σ models
forecast error, a property of the forecast, and a forecast's error distribution
does not shrink because the clock advanced. A 24 h-lead forecast read at T-90min
still carries 24 h-lead error. Feeding the clock-derived 1.5 h would select the
~1.4 degF bin instead of ~2.8 degF — **halving σ and OVERSTATING edge**. So σ
must stay on issuance lead, and "re-plumb the horizon everywhere" would have
introduced a new bug. See [[T-11]].

**What survives:** `risk.py:517`'s halt gate is now redundant (T-5 flattens
upstream first), and `:519` is the one live gate exposure. T-8 is therefore
much smaller than written above — two call sites, not a five-strategy
re-plumbing.

**And an exit that a frozen source disables entirely:**
`calibration_mean_reversion/decision.py:88` reads `hours_left =
forecast.horizon_hours` to gate a `calibration_horizon_flatten` at
`min_horizon_hours = 6.0`. Against a frozen 24.0 that exit **never fires**. Same
class as T-5, different exit; conforming sources are unaffected, so this is
primarily a test-fidelity gap that becomes real the moment a source freezes.

Follow-up: derive the entry horizon from `_deadlines` as well, so one time base
serves both gates.

## T-9 [MEDIUM, POLICY] `halt_hours_before_settlement = 1.0` is an artifact, and flattening may be value-destroying

Two separate concerns, neither measured.

**The threshold.** 1.0 h is measured against the venue's `endDate`
(`parsing.py:1282`), which is administrative. The daily high locks mid-afternoon
local, so the economically meaningful lock time and the venue's end time are
different instants. The value is **UNVERIFIED by any measurement** and was
plausibly never chosen against data.

**The action may be worse than the exposure.** `_flatten` calls
`close_all_positions` unconditionally into a weather book whose bid side is
~0.3 contracts deep — a taker dump of a position that is about to pay $1. For a
position that is *winning* and near-certain, halting by dumping into an empty
bid destroys value that simply holding to settlement would realise.

**Correct policy plausibly differs by strategy family**, and the codebase already
splits this way: `running_extreme_lock:337` treats the halt as **entry-only** and
returns rather than flattening. The forecast family flattens. Whether the
forecast family should flatten unconditionally, or only when the position is
losing or unhedged, is an open trading-policy question — not a defect to patch
blind. Decide it against measured settlement outcomes, not intuition.

## T-10 [MEDIUM, TRAP] Two `hours_until` functions with REVERSED argument order

`weather_common/models.py:145` is `hours_until(later, now)`.
`scripts/analysis/weather_strategy_backtest_lib.py:250` is
`hours_until(now, deadline)`. **Same name, opposite argument order, and a wrong
import silently flips the sign of every horizon** — no error, no type mismatch,
just a negative horizon that reads as "already past settlement".

Currently contained, verified: `src/` imports nothing from `scripts/` (0
occurrences), so production code cannot reach the reversed variant, and T-5's
three new call sites all use the `models.py` one with `(deadline, now)`, matching
the `running_extreme_lock` precedent. `run_weather_strategy_backtests.py:513`
correctly uses the lib variant.

Containment is structural rather than deliberate, so it holds only while the
import boundary does. Renaming one of them removes the trap permanently.


## T-11 [HIGH] The backtest understates forecast error, so measured ROI is overstated

Found while scoping T-8, and the highest-value defect in this document because
it corrupts the numbers every strategy decision rests on.

`ForecastSnapshot.horizon_hours` serves two incompatible purposes with one
value. Time gates want the **live time-to-settlement**.
`ForecastErrorModel.sigma` (`probability.py:223`) models **forecast error**,
which is a property of the forecast — its **lead time at issuance**.

`_SequenceForecastSource.snapshot`
(`scripts/analysis/run_weather_strategy_backtests.py:491-514`) returns the
latest publication at or before `now` — its `published_at` and
`expected_high_f` — while setting `horizon_hours = hours_until(now, deadline)`.
So a forecast **issued at T-24h and read at T-3h reaches σ as a 3-hour
forecast**, selecting a ~1.4 degF bin for a forecast carrying ~2.8 degF error.

**σ understated ~2x -> edge overstated -> measured backtest ROI overstated**,
worst on the near-certain buckets where sizing is largest.

Note the source is **conforming to the stated contract** (`forecast_source.py`
says `horizon_hours` must be the live hours-remaining). The contract itself is
wrong for σ's purposes. The fix passes `hours_until(deadline,
forecast.published_at)` to σ and leaves `horizon_hours` alone for the gates —
`published_at` already exists at `models.py:110`, so the correct value was
always available and simply never used.

Expected consequence, stated in advance so it cannot be quietly absorbed:
**backtest edge and PnL should move DOWN.** A move up would contradict the
analysis and falsify it.