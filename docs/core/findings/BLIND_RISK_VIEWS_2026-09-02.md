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
