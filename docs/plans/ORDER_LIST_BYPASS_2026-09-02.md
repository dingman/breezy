# `submit_order_list` naked-short bypass — design plan — **Revision 2**, 2026-09-02

Design only; no implementation. Successor to `docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md` §6.
Nautilus is exact-pinned (`nautilus_trader==1.231.0`); every citation was read in
`.venv/lib/python3.13/site-packages/`, every grep carried a positive control (L-8), and the
load-bearing facts were **executed, not read** (L-15).

## Changelog — Revision 1 → Revision 2

| # | Change | Why |
|---|--------|-----|
| C1 | Both measured findings **stand unchanged**: direction (A) is falsified (G1-G4), and the bypass is reachable with two plain `submit_order` SELLs and no `OrderList` (G6) | two reviews confirmed; no counter-evidence |
| C2 | **Revision 1's "least-confident" item is WITHDRAWN — answered in a file it already cited.** `inflight_check_interval_ms=0` (`node_config.py:701`) deliberately disables in-flight resolution, so a SUBMITTED order persisting forever is **designed behaviour**, not an open question | G10; I read `:699-700` and stopped one line short |
| C3 | **New §2.1** states the stuck-SUBMITTED consequence chain in full, why it is accepted, and a **diagnosability requirement** (RED-23); §7 carries it as a **disclosed accepted risk**, not a condition | a capital-preservation trade-off a reader must not have to reconstruct, disclosed where it becomes realizable |
| C4 | **New §8 (T-1)** records the same blindness at the STRATEGY layer, counts corrected; T-2 records cancel-replace as pre-existing | out of scope to fix; must not be lost |
| C5 | §3's residual restated per D6, with the ordering constraint that makes it true; `_FakeOrder` gains `is_closed` **and `client_order_id`** | the publish loop completes before **any** `cache.add_order`; D4 named only `_FakeCache` |

## §0 Measured facts

| # | Fact | Where / how |
|---|------|-------------|
| G1 | `OrderList.__init__` **never assigns `order_list_id` to its member orders** — it sets only `id/instrument_id/strategy_id/orders/first/ts_init` | `model/orders/list.pyx:50-72` |
| G2 | Every single-order `OrderFactory` method hardcodes `order_list_id=None`; only `bracket()` sets a real one | `common/factories.pyx:303,408,511,628,711,814,931,1047,1184` vs `:1351,1376..1705` |
| G3 | **EXECUTED.** Legs from `order_factory.limit(...)` wrapped in `OrderList(OrderListId("OL-1"), legs)` — RED-12's exact shape — carry `order_list_id=None`, `contingency_type=NO_CONTINGENCY`, `linked_order_ids=None`, `parent_order_id=None`, `tags=None`. Positive control: `factory.bracket(...)` returned a real `OrderListId` on all three legs | probe against the pinned wheel |
| G4 | Therefore an order-list member's `OrderInitialized` is **indistinguishable** from a plain `submit_order` member's on every field the event carries. No stateless discriminator exists | G1+G2+G3 |
| G5 | `Order.is_open_c()` is `ACCEPTED / TRIGGERED / PENDING_UPDATE / PENDING_CANCEL / PARTIALLY_FILLED` — **`INITIALIZED` and `SUBMITTED` are NOT open**; and `Cache.add_order` populates `_orders` and the venue/instrument/strategy indices but **never `_index_orders_open`** (only `update_order` writes it) | `model/orders/base.pyx` `is_open_c`; `cache/cache.pyx` `add_order` |
| G6 | **EXECUTED.** Two `submit_order` SELLs of 10 from one `on_order_filled`, against net long 10: **both approved, no raise.** Trace at the second screening — `cache.orders(...)` = `[BUY FILLED, SELL SUBMITTED, SELL SUBMITTED]`, `cache.orders_open(...)` = **`[]`** | probe via `scripts/ci/run_tests_no_egress.sh` |
| G7 | `Strategy._deny_order` calls `cache.add_order(order)` when absent, then applies `OrderDenied` (**closed**) and `cache.update_order`; `_deny_order_list` fans out to it. So **all three** denial paths — duplicate list id (`strategy.pyx:961-966`), duplicate client order id (`:975-985`), `MARKET_EXIT_IN_PROGRESS` (`:953-957`) — put the order in the cache as closed | `trading/strategy.pyx` `_deny_order` / `_deny_order_list` |
| G8 | `CacheFacade` already exposes `order(client_order_id)` (`cache/base.pyx:349`) and `orders(...)` (`:365`) — no new dependency | read |
| G9 | B4 run for real (L-15): `is_venue_touching('src/breezy/runtime/backtest_order_guard.py') is True`, `find_write_egress_violations(...) == []` | executed |
| G10 | **A SUBMITTED order can persist indefinitely, by design.** `LiveExecEngineConfig(inflight_check_interval_ms=0)` (`node_config.py:701`) against a 2000 ms Nautilus default; `live/execution_engine.py:574-575,591-592` guard the in-flight timer on `> 0`, and `:383-386` schedules continuous reconciliation only if an interval is truthy. Rationale at `node_config.py:616-640`: Polymarket.us has no client-order-id, so auto-resolving a stuck order risks a **doubled position**. No durability to clear it (`CacheConfig(database=None, flush_on_start=False)`, `:693`) — only a process restart | verified at both sites |
| G11 | `weather_common/risk.py:198-204` names two covers for the jointly-naked case — "every strategy skips evaluation entirely while any order is working (`cache.orders_open`)" and the backtest guard "sums working sell quantity straight from the cache". **Both read the same blind set.** Corrected counts: **14 call sites across 6 strategy modules** (the raw grep's 17 includes 3 prose references — `resting_ladder.py:258`, `risk.py:162`, `risk.py:199`) | grep, positive control 39 `self.cache.` hits |
| G12 | Those 14 split into **two** uses, both blind: **8 skip-gates** (`forecast_mispricing:298,391`; `calibration_mean_reversion:324,417`; `forecast_revision:320,413`; `running_extreme_lock:365`; `cli_settlement_print_lock:768`) and **5 feeds into `_signed_open_order_qty`** (`:402,428,439,971,424`), which sums `signed_decimal_qty()` into the risk snapshot's `pending_qty`; plus `resting_ladder.py:262`'s cancel loop | read |

**Exposure.** `resting_ladder.py:296-347` is safe only by its own `_exit_submitted` latch —
strategy-side bookkeeping, the invariant the guard exists to make unnecessary
(`backtest_order_guard.py:30-35`). The five weather strategies submit one order per decision per
instrument, so G6's shape needs two decisions inside one un-acked window: impossible in backtest
(next-tick accept), **possible in live**, where `SUBMITTED → ACCEPTED` is a venue round-trip. Live is
masked by the standing R-4 refusal (`exec/client.py:1338-1350`) and `strategies=[]`, not by the guard.

## §1 Decision 1 — direction (A), refuse SELLs carrying an `order_list_id`: **REJECT**

By G1-G4 the field is `None` on RED-12's orders, so the rule refuses nothing that matters: RED-12
stays `xfail`, the R-4 gate stays shut, and the repo gains a *decorative* safety rule — the worst
outcome available, because it reads like a closure. It would refuse only `OrderFactory.bracket()`
output (G2), which nothing produces. "`order_list_id` exists and round-trips" is **true and not the
operative question**: the field round-trips faithfully, it is simply never populated on the attack
shape — L-17 one level up, presence on the *class* read as presence on the *instance*. **The blunt
variant** ("refuse every SELL in any order list") is unimplementable at this observation point by G4,
not merely blunt, so the OCO/bracket foreclosure cost Revision 1 weighed is moot.

## §2 Decision 2 — the real defect: `orders_open` is the wrong set

`_working_sell_quantity` (`backtest_order_guard.py:249-276`) reads `cache.orders_open(...)`. By G5
that set **excludes an order the strategy has already committed to** while it is `INITIALIZED` or
`SUBMITTED`. `submit_order_list` widens that window (members enter the cache at `strategy.pyx:981`,
after the whole publish loop at `:944-951`); it did not create it.

**RECOMMENDATION — Increment 1, stateless, one expression. Land it alone.** Sum `leaves_qty` over
`cache.orders(instrument_id=...)` filtered to `order.side == OrderSide.SELL and not order.is_closed`,
in place of `cache.orders_open(...)`.

`not is_closed` is a strict **superset** of `is_open`, adding only INITIALIZED / SUBMITTED /
EMULATED / RELEASED, so `pending` only widens and the guard's ACCEPTED set only narrows (L-12's safe
direction); `cache.orders()` is dict-backed, so no double-count; `leaves_qty == quantity` at
INITIALIZED and is reduced only by fills, so the sum is the correct outstanding commitment at every
status. Still stateless — the cache remains the single source of truth. Domain review walked
multi-clip, partial-fill, cross-strike, cancel-replace and settlement-race exits: **no legitimate
exit is wrongly refused**, and multi-clip is strictly *improved* (the second clip finally sees the
first). It closes G6 outright but does **not** close RED-12 — inside `submit_order_list` no member is
in the cache at all — and must not be reported as if it did.

### §2.1 The stuck-SUBMITTED consequence chain, and why it is accepted

By G10 a SELL can sit in `SUBMITTED` indefinitely. Under Increment 1: **stuck SUBMITTED SELL →
counted in `pending` forever → every later SELL on that instrument refused → the bid side is
effectively empty (~0.3-contract median top-of-book) so there is no venue-side exit either → the
position rides to NWS settlement with no controlled exit.** A capital-preservation matter, not a
neutral fail-closed. Accepted, for three reasons — the third stronger than "bounded vs unbounded":

1. **Bounded downside.** Riding a binary to settlement is bounded — you hold what you hold, premium
   already sunk. A doubled position from a false in-flight resolve is not, which is why
   `inflight_check_interval_ms=0` was chosen (G10). Increment 1 is the **complement** of a decision
   this repo already made deliberately: both refuse to guess on a dedup-less venue.
2. **The status quo is worse.** Today the stuck SELL is invisible, so a second same-sized SELL is
   *approved* (G6). The trade is "possible blocked exit" for "possible unfunded position", and only
   one of those is a correctness failure.
3. **The cost is currently unrealizable, and becomes realizable exactly where it is disclosed.** No
   live order can be stuck SUBMITTED while `strategies=[]` (`node_config.py:699`) and the standing
   R-4 refusal hold. The benefit lands now; the cost cannot arrive before R-4 is removed — which is
   why §7 carries it as a disclosed risk rather than §2 as a blocker. **I therefore do not think it
   should block Increment 1**, said having been invited to argue the other side.

**Required mitigation — diagnosability, not an override.** `NakedShortRefusedError` must name the
orders making up `pending` (`client_order_id` + status per contributor). Without it the operator sees
only "naked short of N" and cannot distinguish "blocked by a stuck SUBMITTED order" from "the
strategy genuinely oversold" — and by L-16 a safety control nobody can diagnose is one they will
misread. Pinned by RED-23. **Rejected — an operator flag to waive the guard:** one flag is how a
guard becomes a decoration, the reasoning `backtest_harness`'s per-refusal overrides already record.
The remedy for a stuck order is a process restart (G10), already this repo's answer elsewhere.

## §3 Decision 3 — closing RED-12: a **cache-subordinate shim**, not direction (B)

Direction (B) is the right instinct with the wrong mechanism. An **event-driven** eviction lifecycle
(evict on `OrderDenied`, on the duplicate-id denial, on `MARKET_EXIT_IN_PROGRESS`, on orders that
never reach the venue) is where the risk lives: a missed eviction is a permanent silent false
refusal, and enumerating those paths is the audit burden that made §6 defer.

**RECOMMENDATION — Increment 2: make the state subordinate to the cache, so no eviction event exists
to miss.** The guard keeps `ClientOrderId -> (InstrumentId, Decimal)` for every SELL it approves; an
entry is **live only while `self._cache.order(client_order_id) is None`**.

```
pending = Σ leaves_qty over cache.orders(instrument_id) where SELL and not is_closed
        + Σ quantity    over shim entries for this instrument where cache.order(coid) is None
```

The two sums are **disjoint by construction** on that one predicate, so no double-count is possible
in any order state. The eviction table collapses to one row:

| Path | Entry | Why safe |
|---|---|---|
| Normal submit (`strategy.pyx:871` / `:981`) | inert next screening | order is in the cache |
| Duplicate list id (`:961-966`) / duplicate coid (`:975-985`) / `MARKET_EXIT_IN_PROGRESS` (`:953-957`) | inert | G7 — `_deny_order` calls `cache.add_order` |
| `RiskEngine` / exec-client denial | inert | already cached before the command was sent |
| **Guard raises on member k** | members `1..k-1` stay **live forever** | **the one residual** |

**Design constraint that makes that row true (D6, refined).** The publish loop (`:944-951`) completes
or raises **before any** `cache.add_order`/`add_order_list` (`:958-981`), so a raise on member k
leaves members **`1..k` uncached** — k included. The shim-live set is `1..k-1` **only if the guard
records an entry after both refusal rules pass**, never before screening. That ordering is a
requirement, not an implementation detail; RED-24 pins it. Pruning inert entries is memory hygiene,
never correctness, and uses the same predicate — a plain sweep inside `_working_sell_quantity`.

**The residual.** If the refusal is caught and the process continues, stale entries over-count
`pending` and refuse legitimate later SELLs for that instrument — the same shape as §2.1 and the same
acceptance. Both live dispatch paths in scope kill or latch (L-16); backtest aborts the run.

**Rejected — a `BreezyStrategy` base class that refuses `submit_order_list`.** Native and stateless,
but per-base-class and forgettable — a strategy subclassing `Strategy` directly bypasses it, the
exact failure that put the rule in the guard (`backtest_order_guard.py:30-35`) — and it leaves G6's
non-list shape wide open. **Rejected — intercept the `SubmitOrderList` command.**
`Strategy._send_risk_command` uses a point-to-point `msgbus.send`, not a publish, so no subscriber
can see it, and it arrives after `cache.add_order`. **Rejected — leave RED-12 tracked and unfixed.**
Defensible before G6; not after: the same class is reachable with **no** exotic API, and Increment 1
alone leaves a named, measured hole behind an R-4 gate that REDUCE_ONLY §7 refuses to game.

## §4 Decision 4 — does the fix belong in the guard? **Yes, and only there**

The guard is the sole chokepoint seeing all three submission routes (`strategy.pyx:855-859`,
`:944-951`, `algorithm.pyx:1204-1210`). Config cannot express it: `support_contingent_orders=False`
(`backtest_harness.py:759`) governs OCO/OTO semantics and is inert against a `NO_CONTINGENCY` list
(G3); the strategy-base route is rejected in §3. **No Nautilus file is touched; nothing is
subclassed, patched or wrapped** — this narrows Breezy's own predicate inside its own module.

## §5 What must NOT change

`_refuse_post_only` (`:188-201`) and its composition order in `on_order_event` (`:183-184`) — the
post-only refusal must still precede the naked-short one. The L-8 zero-discovery / silent-run
refusals in `backtest_harness.py` and their per-refusal overrides. `install_order_guard`
(`:290-298`) keeps its bare-handler shape and backtest wiring; `install_live_order_guard`
(`:301-359`) keeps `on_refusal` **required** (L-16); the `reconciliation` early-return (`:150-182`)
and its `xfail(strict=True)` pins stand. No barrier file edited; no attribute named
`post/put/patch/delete/request` added (use `dict.pop` / `set.discard`, never a method named
`delete`); B4 re-run for real per L-15 (G9 is the baseline); no exact-set equality touched; the
accepted set only narrows (L-12). No order-send or egress path — the guard reads `Cache` and
`Portfolio` only.

## §6 The RED list

`_FakeCache` (`tests/unit/test_runtime_backtest_order_guard.py:64-70`) implements only `orders_open`,
and `_FakeOrder` (`:57-61`) carries only `side`/`leaves_qty`/`is_reduce_only` — both **structurally
blind** to this class. Increment 1 adds `_FakeCache.orders` and `_FakeOrder.is_closed`; Increment 2
adds `_FakeCache.order(coid)` and `_FakeOrder.client_order_id`.

| # | Test | Pins |
|---|---|---|
| RED-13 | `test_two_plain_submit_order_sells_within_the_net_long_are_jointly_naked` — real engine, two `submit_order` SELLs of 10 from one `on_order_filled` vs net 10 → `raises(..., match="naked short of")`. **Currently fails (measured, G6)** | §2, the unpinned hole |
| RED-14 | `test_a_submitted_but_unaccepted_sell_counts_against_the_budget` — unit, widened fakes: a `SUBMITTED` SELL absent from `orders_open` is counted | the mechanism, not the symptom |
| RED-15 | **MUST PASS** `test_a_closed_sell_does_not_count_against_the_budget` — `FILLED` and `DENIED` SELLs contribute 0 | the anti-false-refusal floor |
| RED-16 | **MUST PASS** `test_a_legitimate_full_exit_still_passes_under_the_widened_set` — net 100, SELL 100 → no raise | regression floor |
| RED-23 | `test_the_refusal_names_every_order_it_counted` — message carries each contributor's `client_order_id` and status, so a stuck `SUBMITTED` blocker is identifiable | §2.1's mitigation |
| RED-12 | `test_an_order_list_of_two_sells_within_the_net_long_is_jointly_naked` (`tests/integration/test_backtest_run_refusals.py:646-676`) — **remove `@pytest.mark.xfail(strict=True)` in the commit that lands Increment 2** | the headline case |
| RED-17 | `test_a_single_member_order_list_within_the_net_long_passes` — net 10, one-SELL list of 10 → no raise | §1's rejection, made executable |
| RED-18 | `test_a_three_member_order_list_refuses_on_the_third_leg` — net 20, three SELLs of 10 → legs 1-2 pass, leg 3 refused, overage `10` in the message | the shim accumulates; it is not a list-ban |
| RED-24 | `test_a_refused_member_leaves_no_shim_entry` — after a refusal on leg k, `pending` counts `k-1` legs, not `k` | §3's record-after-approve constraint |
| RED-19 | **MUST PASS** existing `_NakedShortProbe` cases (`:459`, `:478`) green and unchanged | no drift on the common path |
| RED-20 | `test_an_approved_sell_stops_being_counted_once_the_cache_holds_it` — approve SELL 10, then place it in the fake cache as `SUBMITTED`; `pending` is **10, not 20** | the disjointness invariant |
| RED-21 | `test_a_denied_order_list_member_stops_counting` — order present in cache as `DENIED` → 0 from both sums | G7, the collapsed eviction table |
| RED-22 | **MUST PASS** RED-9 (`:503`) and RED-10 (`:566`) unchanged | settlement stays out of jurisdiction |

**Landing order.** (1) Widen the fakes. (2) RED-15/16/19/22 as characterisation — green before and
after. (3) RED-13/14/23 → green by Increment 1; **commit**. (4) RED-17/18/20/21/24 → green by
Increment 2, RED-12's marker stripped in that same commit; **commit**. (5) Gates:
`scripts/ci/run_tests_no_egress.sh` full, ruff, mypy, `lint-imports`, the B4 classifier run for real
(L-15), `test_cage_rule_constants_are_pinned.py`, `test_execution_egress_firewall_guard.py`. Meet or
exceed **5134 passed, 1 skipped, 4 deselected, 4 xfailed**; after Increment 2 expect **3 xfailed**
plus the new tests, every remaining xfail named in the commit message.

## §7 The R-4 gate — before `exec/client.py:1338-1350` is removed

Inherits REDUCE_ONLY §7 items 1-2 and 4-7 verbatim, and **replaces** item 3:

3. **Both** Increment 1 and Increment 2 landed.
   `test_an_order_list_of_two_sells_within_the_net_long_is_jointly_naked` (RED-12) **and**
   `test_two_plain_submit_order_sells_within_the_net_long_are_jointly_naked` (RED-13) GREEN with
   **no** xfail marker. RED-13 is a criterion in its own right: closing the order-list API while G6's
   plain-`submit_order` shape stays open satisfies the old wording and still ships a naked short.

**Disclosed accepted risk — NOT a condition to satisfy.** *A stuck `SUBMITTED` order permanently
blocks further SELLs on that instrument, by design.* It follows from `inflight_check_interval_ms=0`
(G10), is cleared only by a process restart, and §2.1 gives the chain and the reasoning. Restate it
in the R-4 removal commit message: removing the standing refusal is the moment it stops being
hypothetical. No numeric xfail target is a criterion; R-9 stays out of scope.

## §8 Tracked, NOT fixed here

**T-1 — the same blindness is load-bearing at the STRATEGY layer, and the codebase mis-documents its
own defence.** `weather_common/risk.py:198-204` presents two covers for the jointly-naked case; by
G11 they are **one query — `cache.orders_open` — and it is the blind one**. By G12 the 14 call sites
across 6 modules split into 8 "skip this decision cycle" gates and 5 feeds into
`_signed_open_order_qty`, so the risk snapshot's own `pending_qty` is blind to in-flight orders too.
Increment 1 does not touch them: after it lands the guard correctly refuses what a strategy wrongly
attempts — fail-closed and an improvement — but the strategy-level blind spot stays open and its
symptom becomes a guard refusal rather than a silent naked short. **The `risk.py:198-204` docstring
must be corrected in that follow-up**, since it asserts an independence that does not exist.
Deliberately out of scope: it touches six strategy modules, which would make two auditable guard
changes unreviewable.

**T-2 — cancel-replace false refusal.** A cancelling order still counted while its replacement is
screened can refuse a legitimate replace. Domain review confirms this exists **identically before and
after** Increment 1 — `PENDING_CANCEL` is already in `is_open`. Pre-existing, not introduced here.

## §9 Could not verify

- **[LEAST CONFIDENT — review first] T-1's severity.** I verified its call sites and the docstring
  error, but not whether any live strategy configuration can actually reach a jointly-naked decision
  through the skip-gates. That needs a strategy-level trace this increment did not run, and it sets
  T-1's priority.
- The `5134/1/4/4` baseline is the coordinator's figure; I ran targeted probes, not the suite.
- G6's probe did not cover multi-instrument or emulated orders. Emulated SELLs are neither open nor
  closed and would newly count under Increment 1 — correct in my reading (an emulated resting SELL is
  a real commitment), unexercised in practice (Breezy sets no `emulation_trigger`).
- The shim under a future venue honouring OCO is unexamined (REDUCE_ONLY §8). Renaming
  `BacktestOrderGuard` now it holds state is out of scope — `:307-317` already defers it.
