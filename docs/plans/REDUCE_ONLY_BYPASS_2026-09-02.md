# `reduce_only` naked-short bypass — design plan — **Revision 2**, 2026-09-02

Design only; no implementation. Nautilus is exact-pinned (`nautilus_trader==1.231.0`, verified in
`.venv/lib/python3.13/site-packages/nautilus_trader-1.231.0.dist-info`); every citation was read in
that tree, each grep with a positive control (L-8: a 0-match is not a fact). Successor to
`docs/plans/R6A_GUARD_SEMANTICS_2026-09-02.md` §3, which tracked this and deferred it.

## Changelog — Revision 1 → Revision 2

| # | Change | Why |
|---|--------|-----|
| C1 | The two deletions (§1, §2) are **unchanged** and now **execution-verified**: three patched variants were built and run — neither deletion alone refuses the jointly-naked pair, both together do, and every legitimate-exit shape passes under all four variants. A domain trace of full/partial/multi-clip/multi-strike exits and expiry settlement found **no** legitimate reducing sell the net-long test refuses | the "correct by construction" claim in §1(b) is no longer an argument, it is a measurement |
| C2 | **New §6: `Strategy.submit_order_list` defeats the guard outright** — no flag, no forgery, plain SELLs. Same class (guard state lags reality), different mechanism, strictly worse. Tracked as RED-12 `xfail(strict=True)`, not fixed here | verified at source (F12-F14); closing it needs real state, not a token deletion |
| C3 | **§7's R-4 gate restated and de-gamed**: the "xfail count drops 4→3" criterion is **withdrawn**. It was both wrong (RED-2 off −1, RED-12 on +1 → net 4→4) and *gameable* — it passes while an equivalent gap survives via another API. Named tests replace the count, and removal of `exec/client.py:1338-1350` is gated on **both** classes | a count cannot distinguish "this class closed" from "an equivalent gap survives" |
| C4 | **§5 corrected**: my Revision-1 falsifying shape (`on_order_filled` re-entrancy) **cannot occur**. The real residual is `on_order_accepted`-shaped, currently unreachable — and it yields a *correct* refusal, not a false one | two reviewers converged; verified at source (F14) |
| C5 | The marker-removal requirement is promoted to its own gate line: a reviewer ran the existing `xfail(strict=True)` body against the both-deletions module under real pytest and got `XPASS(strict)`, which **FAILS the suite** | it is now execution-verified, not a housekeeping note |

**Accepted, with a refinement rather than a pushback.** Tracking §6 instead of closing it here is
right, for the affirmative reason §6 gives: the guard is **stateless**, and closing that hole
requires mutable state with a real eviction lifecycle. The refinement: tracking is not deferral into
the unknown — a stateless candidate fix is named, so §7's gate is gating on bounded work.

## §0 Measured facts

| # | Fact | Where |
|---|------|-------|
| F1 | `reduce_only` is an ordinary public `OrderFactory` kwarg (`bint reduce_only = False`) on every factory method | `common/factories.pyx:242,321,426,531,644,729,834,952,1071` |
| F2 | `RiskEngine._handle_submit_order` validates reduce-only **only** `if command.position_id is not None`, and `Strategy.submit_order`'s `position_id` defaults `None` — so on the default path it never runs | `risk/engine.pyx:424-433`; `trading/strategy.pyx:805-808` |
| F3 | And when it does run it is jointly-naked-blind: `would_reduce_only` compares **this order's** `leaves_qty` to `position.quantity` only, so N reduce-only sells each `== position.quantity` all pass | `model/orders/base.pyx:955-987` |
| F4 | Cash check: `is_position_reducing_sell = order.is_reduce_only or pending_sell_qty <= available_long_qty` — the flag alone short-circuits the comparison | `risk/engine.pyx:976-988` |
| F5 | Nautilus's own `submitted_sell_qty` sums `leaves_qty` over `orders_open(..., OrderSide.SELL)` with **no reduce-only filter**; `available_long_qty = net_long − submitted_sell_qty` | `risk/engine.pyx:716-738` |
| F6 | `OrderInitialized` carries **no** `position_id` (absent in `model/events/order.pyx:197-636`; positive control: 7 `reduce_only` hits in range). It **does** carry `reduce_only`, `order_list_id`, `contingency_type`, `linked_order_ids`, `tags` — all public readonly | `model/events/order.pxd` (OrderInitialized block) |
| F7 | The backtest settlement leg (`EXPIRATION-LEG-<uuid4>`) is a bare `MarketOrder(reduce_only=True)` passed to `cache.add_order` + `_generate_order_accepted` + `apply_fills` — **it publishes no `OrderInitialized`** and never reaches the guard. All open orders are cancelled immediately before | `backtest/engine.pyx:5945-5978`; already stated at `backtest_order_guard.py:46-52` |
| F8 | `Strategy.close_position` sets `reduce_only=True` **and** passes `position_id=position.id`, so the native exit does reach F2's check — and passes it | `trading/strategy.pyx:1398-1415` |
| F9 | **No Breezy code sets `reduce_only=True` on an order.** The only `src/` hit is `use_reduce_only=True`, a venue *config* flag, at `backtest_harness.py:761` | grep over `src/ tests/ scripts/` |
| F10 | `support_contingent_orders=False` on the backtest venue — OCO/OTO semantics are not modelled here | `backtest_harness.py:757-759` |
| F11 | Live node is `strategies=[]`, `exec_algorithms=[]` — nothing there can publish `OrderInitialized` today | `node_config.py:699-700` |
| F12 | `Strategy.submit_order_list` publishes **every** member's `OrderInitialized` in a first loop and only then populates the cache — and the intervening `add_order_list` does **only** `self._order_lists[id] = order_list`, never touching `_orders` or the open index | publish loop `trading/strategy.pyx:944-951`; `add_order_list` `:967` → `cache/cache.pyx:2275-2294`; `cache.add_order` loop `:980-981` |
| F13 | `ExecAlgorithm` does the **reverse** and is safe — `cache.add_order` at `:1204` precedes the publish at `:1206-1210`, under Nautilus's own comment *"Add to cache before publishing to ensure order is available for event handlers"* (`:1203`) | `execution/algorithm.pyx:1194-1210` |
| F14 | On the fill path, `_apply_event_to_order` calls `cache.update_order` — which `discard`s a closed order from `_index_orders_open` — **before** `_handle_order_event` publishes the event to the strategy | `execution/engine.pyx:1586,1617,1341-1345`; `cache/cache.pyx` `update_order` open/closed index block |

**Exposure, stated accurately.** Latent in live — three independent masks: F11, the standing R-4
refusal (`exec/client.py:1338-1350`), and `strike_ladder.py:303-306` being BUY-only by design.
**Exploitable in backtest today.** By F9 **no existing backtest result is affected**: all ten order
construction sites in `src/breezy/strategy/**` (`resting_ladder.py:342`, `strike_ladder.py:305`,
`forecast_mispricing/strategy.py:351,359`, `forecast_revision/strategy.py:373,381`,
`calibration_mean_reversion/strategy.py:377,385`, `forecast_edge.py:169`, `harness_probe.py:199`,
`running_extreme_lock/strategy.py:412`, `cli_settlement_print_lock/strategy.py:916`) default
`reduce_only=False`, so every order ever submitted was already fully screened. Verified, not assumed.

## §1 Decision 1 — what `reduce_only` means to the guard: **nothing**

**RECOMMENDATION.** Delete `or event.reduce_only` from the side filter at
`backtest_order_guard.py:195`. Run the identical net-long test for every SELL. One token.

**Reasoning.** (a) By F1 the flag is strategy-settable — the forgery shape R-6a deleted for
`tags`/`ClientOrderId`; an exemption keyed on an attacker-settable field is a documented bypass.
(b) The existing test *is already the right test for a reducing sell*: a genuinely reducing sell
satisfies `pending + quantity <= net` by the definition of reducing, so running it cannot refuse a
legitimate exit — **now measured** (C1), across full, partial, multi-clip and multi-strike exits and
expiry settlement. (c) The exemption's justification is **void**: by F7 the settlement leg never
reaches the guard, and `:46-52` already says so — the code and its test at `:259-269` contradict a
docstring three screens above them. (d) Nautilus is no substitute (F2/F3/F4): skipped on the default
path, jointly-naked-blind even when it runs (F8). Ours is strictly stronger, which is the only
justification for extending at all.

**Rejected — require `position_id`, delegate to Nautilus.** Structurally impossible here:
`OrderInitialized` has no `position_id` (F6); it lives on the `SubmitOrder` command the guard never
sees. Also insufficient (F3), and it pushes venue policy into every strategy's call signature.
**Rejected — key the exemption on `contingency_type`/`linked_order_ids`.** Present on the event (F6)
but equally settable through the same constructors: closes a forgeable key with a second forgeable
key, and by F10 contingent orders are not modelled here. **Rejected — refuse every reduce-only SELL
outright.** Refuses a legitimate exit — exactly R-6a's original failure mode; self-disqualifying.

## §2 Decision 2 — `_working_sell_quantity`: count reduce-only sells

**RECOMMENDATION.** Delete `and not order.is_reduce_only` at `backtest_order_guard.py:242`.
`pending` becomes the sum of `leaves_qty` over **every** open SELL. One clause.

**Is the exclusion ever correct?** Two candidate justifications; both fail here. (1) *"The
settlement leg is reduce_only and would make a strategy's exit look naked"* (`:259-262`) — the leg
**is** in the cache (F7) and does appear in `orders_open`, but its window is one synchronous block
that opens by cancelling every open order (`engine.pyx:5945-5946`); see §5, corrected and narrower
than Revision 1 claimed. (2) *"OCO/bracket legs are jointly legitimate"* — true in general
(`OrderFactory.bracket` sets `reduce_only=True` on both children,
`common/factories.pyx:1511,1540,1567,…`; only one can fill), but **not here**: F10 disables
contingent orders and no Breezy code builds a bracket. If they are ever enabled the discriminator is
contingency provenance, not `reduce_only` — a future amendment, not something to pre-build (YAGNI).

**Positive argument.** F5: Nautilus's own overselling accounting counts *all* open sells,
reduce-only included. Breezy's exclusion is a **divergence from** Nautilus, not an inheritance.

**Both decisions are required; neither is sufficient** — execution-verified (C1). §1 alone still
passes two reduce-only sells each sized to the whole net long (the first stays invisible in
`pending`); §2 alone still passes one oversized reduce-only sell (the early return fires first).

## §3 Decision 3 — where the fix belongs: **the guard, and only the guard**

**RECOMMENDATION.** Two deletions in `src/breezy/runtime/backtest_order_guard.py` plus prose. No
change to any strategy, to `exec/client.py`, or to venue config. The guard sits at all three
submission chokepoints: `Strategy.submit_order`
(`trading/strategy.pyx:855-859`), `Strategy.submit_order_list` (`:944-951` — **this one lags the
cache; §6**), and `ExecAlgorithm` (`algorithm.pyx:1204-1210`, cache-first and sound — F13). A
strategy-base rule would be per-strategy, forgettable, and would duplicate the invariant — the
failure that put the rule in the guard originally (`backtest_order_guard.py:30-35`). Nothing in
Nautilus needs extending beyond R-6a: this narrows Breezy's own predicate.

**What changes for backtest:** nothing any current Breezy code exercises (F9), and nothing for the
settlement leg (F7). Backtest keeps `install_order_guard`'s bare-handler shape, unchanged.
**What changes for live:** dormant (F11), same status as R-6a's install.

## §4 Decision 4 — what proves the fix

Two existing tests **pin the bypass** and must be **inverted in place, not deleted** — the guard
gains cases and loses none. Deletion criterion, verbatim for the commit message (mirroring R-6a D3):
*these tests pin an exemption keyed on an attacker-settable field, and cite a settlement leg that by
`backtest/engine.pyx:5945-5978` never reaches the guard.* Neither is a safety, settlement or contract
test: the settlement path they name is proven out of jurisdiction by RED-9.

| # | RED test | Pins |
|---|----------|------|
| RED-1 | `test_a_reduce_only_sell_against_no_position_is_still_refused` — inversion of `test_a_reduce_only_sell_is_exempt` (`test_runtime_backtest_order_guard.py:268`), same inputs, now `pytest.raises` | §1 |
| RED-2 | `test_two_reduce_only_sells_within_the_net_long_are_jointly_naked` — **remove the `xfail(strict=True)`** at `:379-400` | §1+§2, the headline case |
| RED-3 | `test_a_working_reduce_only_sell_counts_against_the_budget` — inversion of `:259`: working reduce-only 10, incoming plain SELL 10, net 10 → refused | §2 |
| RED-4 | `test_an_oversized_reduce_only_sell_is_refused` — net 100, reduce-only 101 → refused | §1, without depending on F2 ever firing |
| RED-5 | **MUST PASS** `test_a_legitimate_reduce_only_exit_sized_to_the_net_long_passes` — net 100, no working sells, reduce-only SELL 100 → no raise | the anti-R-6a case |
| RED-6 | **MUST PASS** `test_a_partial_reduce_only_exit_beside_a_working_reduce_only_exit_passes` — net 100, working reduce-only 40, incoming reduce-only 60 → no raise | the accounting is additive, not a blanket ban |
| RED-7 | `test_a_mixed_working_pair_is_jointly_naked` — working non-reduce-only 10 + incoming reduce-only 10 vs net 10 → refused | the flag confers nothing in either direction |
| RED-8 | `test_a_reduce_only_buy_is_never_a_naked_short` | regression floor |
| RED-9 | `test_the_expiration_settlement_leg_publishes_no_order_initialized_to_the_guard` — drive `check_instrument_expiration` with the guard subscribed; assert no `OrderInitialized` for `EXPIRATION-LEG-*` reaches the handler | **load-bearing**: the behavioural evidence that inverting `:268` cannot endanger settlement (F7) |
| RED-10 | `test_a_harness_run_holding_a_long_to_expiration_still_settles_under_the_guard` — end-to-end via `backtest_harness` with `settlement_prices`, using a probe strategy that overrides **`on_order_accepted`** (not only `on_order_filled`) and submits nothing; run completes and the position settles | §5 as corrected — covers the **accept** window, the only window that exists |
| RED-11 | `test_the_refusal_message_says_reduce_only_is_not_a_licence` — `:202-220` is the only remediation a future author reads | author-facing correctness |
| RED-12 | **`xfail(strict=True)`** `test_an_order_list_of_two_sells_within_the_net_long_is_jointly_naked` — `submit_order_list` with two plain SELLs of 10 against net 10; reason text cites F12/F13 by line and states that a **stateless** guard cannot close it | §6's tracked hazard, recorded beside the class it belongs to |

Same commit, prose: the old `xfail` reason (`:379-399`), the guard message (`:202-220`),
`backtest_order_guard.py:20-24` (which quotes F4 approvingly), the chokepoint prose (`:30-52`), and
`docs/core/PROGRESS.md:209-214`.

**Landing order.** (1) RED-5/6/8 first as characterisation tests — GREEN before *and* after.
(2) RED-1/RED-4 → GREEN by the `:195` deletion. (3) RED-3/RED-7 → GREEN by the `:242` deletion.
(4) RED-2 → GREEN only once both land; strip the marker. (5) RED-9/RED-10. (6) RED-12 lands xfail.
(7) Prose. (8) Gates: `scripts/ci/run_tests_no_egress.sh` (full), ruff, mypy, `lint-imports`, the B4
classifier run for real per L-15 (`is_venue_touching`,
`tests/unit/test_polymarket_us_readonly_guard.py:230`), `test_cage_rule_constants_are_pinned.py`.
Barrier check: no attribute named `post/put/patch/delete/request` added or renamed (two deletions
plus docstrings); no barrier file edited; no exact-set equality touched, and the guard's *accepted*
set only narrows — L-12's safe direction.

## §5 [CORRECTED] The settlement-leg window behind §2

Revision 1 named `on_order_filled` re-entrancy as the falsifying shape. **It cannot occur.** By F14
`_apply_event_to_order` calls `cache.update_order` — which discards a closed order from
`_index_orders_open` — *before* `_handle_order_event` publishes to the strategy, so by the time
`on_order_filled` runs the leg is closed and absent from `orders_open()`. A *partial* fill correctly
leaves it open at the reduced `leaves_qty`, which is the accounting §2 wants.

The real residual is **accept-shaped**: `_generate_order_accepted` (`backtest/engine.pyx:5966`)
publishes while the leg is ACCEPTED and therefore open, immediately before `apply_fills` (`:5971`).
**Unreachable today** — no Breezy strategy overrides `on_order_accepted`; all re-entrant submission
is from `on_order_filled` (grep over `src/breezy`, positive control passed). **And if reached, the
refusal is correct, not false**: the position is still open at full size with a full-size close leg
working, so any additional SELL is genuinely naked. §2 carries no false-refusal risk here — only a
scenario where a correct refusal aborts a run. RED-10 pins the accept window.

## §6 [TRACKED, NOT FIXED] `Strategy.submit_order_list` defeats the guard outright

By F12, `submit_order_list` publishes **all** members' `OrderInitialized` in one loop *before*
any of them enters `_orders` or the open index — `add_order_list` only records the list object. So
when the guard screens each member, `_working_sell_quantity` reads `pending=0` for **every** one:
`self.submit_order_list(OrderList(id, [sell(10), sell(10)]))` against a net long of 10 passes both
legs and nets a naked short. Plain SELLs; no `reduce_only`, nothing attacker-settable. Same class as
§1/§2 — **guard state lags reality** — by a different mechanism, and strictly worse.

F13 shows this is a Nautilus ordering defect, not a design intent: `ExecAlgorithm` populates the
cache *before* publishing, under the comment *"Add to cache before publishing to ensure order is
available for event handlers"* (`algorithm.pyx:1203`). Nautilus is immutable here, so the ordering
cannot be corrected upstream and the guard must absorb it.

**Not fixed here**, for an affirmative reason: the guard is **stateless**, which is most of why it
is auditable. Closing this means tracking orders the guard has approved but the cache does not yet
hold — mutable state with a real eviction lifecycle (`OrderDenied`; the duplicate-id denial at
`strategy.pyx:975-985`; `MARKET_EXIT_IN_PROGRESS` at `:953-957`). A design increment, not a token
deletion; bundling it would make two auditable deletions hard to review and to revert.

**Tracking is bounded.** A stateless candidate exists and should be that increment's first
evaluation: `OrderInitialized` carries `order_list_id` (F6), Breezy uses no order lists (only
`exec/client.py:1376`'s denial body names them) and `support_contingent_orders=False` (F10) — so
*refusing any SELL that is a member of an order list* closes the hole with no state, in the same
"refuse what this venue cannot model" idiom as `_refuse_post_only`. A candidate, not a
recommendation: it needs its own RED list and review.

## §7 The R-4 gate — what must be true before `exec/client.py:1338-1350` is removed

**The count-based criterion from Revision 1 is WITHDRAWN.** "The suite's xfail count drops from 4 to
3" is wrong (RED-2 comes off, RED-12 goes on → net 4→4) and, worse, **gameable**: it passes cleanly
while §6's hole stays wide open, so it cannot distinguish "the `reduce_only` class closed" from "an
equivalent gap survives through another API". Gate on named tests and on both classes:

1. **Both** §1 and §2 landed (neither alone closes the jointly-naked case; C1 measured this).
2. `test_two_reduce_only_sells_within_the_net_long_are_jointly_naked` is GREEN and carries **no**
   xfail marker; RED-1..RED-11 green.
3. **§6's hole is closed** — `test_an_order_list_of_two_sells_within_the_net_long_is_jointly_naked`
   (RED-12) is GREEN with **no** xfail marker. **Removal of the standing refusal is gated on BOTH
   classes, not on `reduce_only` alone.** Removing it while RED-12 is still `xfail` ships a naked
   short to a live venue silently — the exact sequencing failure `PROGRESS.md:213-214` already
   records for this item.
4. The full gate passes at or above the pinned baseline (`5125 passed, 1 skipped, 4 deselected,
   4 xfailed`), with every xfail that remains named and justified in the commit message. No numeric
   xfail target is a gate criterion.
5. The guard is proven live-**effective**, not merely installed: R-6a's live install is dormant by
   F11, so either a strategy is registered on that node and a naked SELL is shown refused **before**
   `cache.add_order`, or the removal ships behind a config that keeps `strategies=[]`.
6. The live refusal is observable (L-16): R-6a §4's `on_refusal` reporter covers the naked-short
   rule, exercised end-to-end by the `trade_cli` stderr/latch test.
7. `PROGRESS.md:209-214` restated in the same commit — the gate now names two classes, not one.

Explicitly **not** in the gate: R-9. Different milestone, as R-6a §3 already separated.

**Marker removal is load-bearing and execution-verified (C5).** A reviewer ran the existing
`xfail(strict=True)` body against the both-deletions module under real pytest and got
`XPASS(strict)` — which **fails the suite**. The marker must come off in the same commit as the
deletions; there is no ordering in which it can be left for later.

## §8 Could not verify

- Nothing here is proven on a live node: by F11 that path is dormant and this plan does not change it.
- The `5125/1/4/4` baseline is the coordinator's figure; design-only task, suite not run by me.
- C1's three-variant execution and the `XPASS(strict)` result (C5) are reviewer runs, adopted after
  checking they match what F1-F14 predict; I did not re-run them.
- §6's candidate fix is a sketch: its interaction with a future venue that honours OCO is unexamined.
