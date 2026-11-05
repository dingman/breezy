# T-1 — `orders_open` blindness at the strategy layer

Design plan, 2026-09-02. **Revision 2.** No source edits. Nautilus 1.231.0 immutable.

**Changelog (R1 -> R2).** Four targeted changes, no restructuring: (1) §4 gains a missed scope item, the `_NoOpenOrdersCache` stub at `tests/unit/test_weather_strategy_quote_staleness.py:59-61`; (2) **D4's premise now verifies TRUE** on a stronger mechanism than R1 gave, so the 5146/1/4/3 baseline should not move; (3) the empirical check is nonetheless promoted from expectation to an explicit **merge gate**; (4) D3's hazard **attribution is corrected** — the gate blindness is pre-existing, not created by the guard fix. §5 and §6 re-ranked accordingly. Severity finding (§0) and census corrections (§1) unchanged — both reviewed and approved.

## 0. Verdict on the priority question

**T-1 is a sizing/exposure-correctness defect, not a naked-short safety one — and its worst instance is on the BUY side, where nothing backstops it.** The brief's framing ("gates are backstopped, `pending_qty` is not") is half right and understates the gates.

The guard screens `event.side != OrderSide.SELL -> return` (`backtest_order_guard.py:234-235`). It is a **SELL-only** backstop. This bot is long-only; BUYs are the dominant flow. So inside an INITIALIZED/SUBMITTED window a strategy: passes the blind gate; computes `delta = target_qty - current_qty` from `portfolio.net_position`, which excludes the in-flight order; re-submits the same delta — a duplicate BUY, up to 2x intended size — against risk caps blind by the **same** query, since `pending_qty` feeds `net_qty` (`risk.py:180`) and every cap reads `net_qty` (`risk.py:248, 256, 350, 453, 455, 474`).

`risk.py:454-455` is `max_position_contracts` — an **operator-reserved control** (default 250.0, `risk.py:97`). **Cap breach, confirmed by sequence:** settled 0 -> BUY 200 passes (`projected = 0+200 <= 250`) -> a later cycle inside the submit->ACCEPTED window still reads `net_qty = 0`, because the gate and `pending_qty` are the same blind query -> second BUY 200 passes -> net 400 against a 250 cap. There is no downstream catch: `max_notional_per_order` is a per-ORDER ceiling re-evaluated per submit, the cum-notional check is a per-invocation cash-solvency test, and Nautilus's `RiskEngine` holds **zero** cumulative position caps. `max_position_contracts` is the only one, and it is fed by the blind query.

Fix it — scoped by §2, which finds one of the three uses should be fixed by DELETING the query, and one left alone.

## 1. Corrected census — the brief and PROGRESS both mis-bin

Raw grep = 22 lines; 8 are prose. **14 real calls.** The brief and `docs/core/PROGRESS.md:197-202` bin them "8 gates + 5 `pending_qty`" = 13 — one short of their own total — and mis-bin three sites. Verified:

| Class | Sites |
|---|---|
| **A** in-flight gate in `_maybe_submit` | `forecast_mispricing:298`, `calibration_mean_reversion:324`, `forecast_revision:320`, `running_extreme_lock:365`, `cli_settlement_print_lock:768` (5) |
| **B** *cancel*-gate in `_flatten` — `if orders_open: cancel_all_orders(...)` then `close_all_positions(...)` | `forecast_mispricing:391`, `calibration_mean_reversion:417`, `forecast_revision:413` (3) |
| **C** `pending_qty` feed | `forecast_mispricing:402`, `calibration_mean_reversion:428`, **`forecast_revision:424`**, `running_extreme_lock:439`, `cli_settlement_print_lock:971` (5) |
| **D** cancel-sweep in the ladder probe | `resting_ladder.py:262` (1) |

Two corrections that change the work: **class B is not a skip-gate** — it gates a *cancel*, opposite failure direction; and `resting_ladder.py:262` is not a `pending_qty` feed (it builds no `PortfolioSnapshot`) — the omitted site is `forecast_revision:424`. Only 3 strategies define `_flatten` (`:386`, `:412`, `:408`), verified, which is why B is 3. `_signed_open_order_qty` is duplicated verbatim five times: `fm:429`, `cmr:455`, `rel:466`, `cspl:998`, `fr:451`.

## 2. Decisions

### D1 — the correct query

**RECOMMENDATION.** One predicate — `not order.is_closed` over `cache.orders(instrument_id=...)` — shared by A and C. Nothing new for B or D.

`is_closed_c` (`base.pyx:435-442`) = DENIED/REJECTED/CANCELED/EXPIRED/FILLED; its complement is a strict superset of `is_open_c` (`base.pyx:421-430`), adding exactly INITIALIZED/SUBMITTED/EMULATED/RELEASED — the widening the guard already justifies at `backtest_order_guard.py:309-314`. A and C ask different questions ("anything in flight?" vs "how much am I committed to?") but are answered from one list, so they are one call: the gate is `if working`, the size is `sum(signed) over working`.

*Rejected — `orders_open() + orders_inflight()`.* Index-backed and O(1), but `is_inflight_c` (`base.pyx:444-449`) is SUBMITTED/PENDING_CANCEL/PENDING_UPDATE only, so INITIALIZED stays invisible — and INITIALIZED is live-reachable, since the ExecEngine drains its own queue and a later handler invocation can observe it. It also diverges from the guard's predicate, re-creating the "two spellings of one question" T-1 exists to remove. The O(all-orders-ever) scan is not a real objection at this trade rate.

*Rejected — a Breezy-side in-flight ledger keyed on `on_order_*` events.* Duplicates cache state, needs cancel/reject/partial-fill bookkeeping, can drift. The guard already rejected this (`backtest_order_guard.py:327-331`).

### D2 — shared helper, and where it lives

**RECOMMENDATION.** New `src/breezy/strategy/weather_common/inflight.py`: `working_orders(cache, instrument_id)` and `signed_working_qty(orders)`. The five strategies import both; the five `_signed_open_order_qty` copies are deleted; one module carries the semantics docstring.

**The guard is NOT refactored onto it.** `runtime/` importing `strategy/weather_common/` is a layering inversion, and the guard is fixed, safety-critical and heavily tested. The 3-line duplication is the deliberate cost of not touching a correct safety module for zero correctness gain; `inflight.py` cross-references `_working_sell_orders` so the pair stays discoverable.

*Rejected — the helper in `risk.py`.* `risk.py` is pure policy over a `PortfolioSnapshot` and imports no cache; a cache-reading function there couples policy to runtime. *Rejected — a `WeatherStrategyBase` mixin.* Speculative: no shared base exists, and creating one to hold two functions exceeds the defect.

### D3 — class B: delete the gate, do not widen it

**RECOMMENDATION.** Remove the `if self.cache.orders_open(...)` at `fm:391`, `cmr:417`, `fr:413`; call `self.cancel_all_orders(nt_id)` unconditionally. Three call sites disappear rather than being fixed.

Nautilus's `cancel_all_orders` (`strategy.pyx:1215-1300`) already queries `orders_open` **plus** `orders_emulated` **plus** `orders_inflight`, logs and returns cleanly when all three are empty (`:1266-1270`), and skips INITIALIZED in its cancel loop (a venue that has not seen an order cannot cancel it). The Breezy gate is a NARROWER pre-filter in front of a WIDER native query — it can only suppress a cancel Nautilus would have performed.

**Attribution, corrected (R2).** The gate blindness here is **pre-existing** — the Breezy gate has always read the blind query, so a SUBMITTED reducing SELL has always escaped cancellation before `close_all_positions` (`strategy.pyx:1418-1489`) submits a further SELL for the whole position. What the guard fix changed is only the **symptom**: that pair previously passed as a silent naked short, and now raises `NakedShortRefusedError` (re-raised on live by `install_live_order_guard`), so the exit path aborts visibly. That is the guard working as designed, not damage it caused.

Deleting the cancel-gate **shrinks** this window rather than widening it: Nautilus's own `cancel_all_orders` reaches the SUBMITTED order through `orders_inflight`, which the Breezy pre-filter was suppressing. **Honest residual, unchanged:** INITIALIZED is skipped in the cancel loop and cannot be cancelled at all, and cancel is asynchronous — the SELL moves to PENDING_CANCEL, which the guard still counts, while `close_all_positions` runs in the same synchronous call. A flatten can still be refused. The residual is **narrowed, not closed**; it is a cancel/close *sequencing* defect, tracked separately and explicitly out of T-1 scope.

*Rejected — widening B like A/C.* Strictly worse: keeps a redundant gate whose only possible effect is suppressing a correct native cancel.

### D4 — the behaviour change on class A (premise now VERIFIED)

Widening A makes strategies skip when an order is INITIALIZED or SUBMITTED but not yet ACCEPTED. The newly-skipped shape is exactly: a second decision cycle firing inside the submit-to-accept window on the same instrument.

- **Backtest: no additional skips. Premise verified (R2).** R1 argued from `OrderInitialized` being published before `cache.add_order` — that speaks to *visibility*, not *timing*, and was the weaker claim. The actual mechanism is the call stack: `Strategy.submit_order` -> `MessageBus.send`, which is a **direct in-process `handler(msg)` call, not a queue** -> `RiskEngine._handle_submit_order` -> the submit throttler, which defers only above a configured rate this bot never approaches, with `latency_model=None` in the harness. The whole chain therefore runs synchronously in one call stack and the order reaches ACCEPTED before control returns for the next `QuoteTick`. **No plausible mechanism exists for the widened gate to drop a backtest cycle, so the 5146/1/4/3 baseline should not move.** Merge gate in §4 measures rather than assumes it.
- **Live:** one network round-trip per submission. `_evaluate_and_act` fires on every `QuoteTick`/`OrderBookDepth10`, so a handful of cycles per submission fall in the window on a fast book.

**Desirable, not merely safe.** What "proceeded" in that window was a duplicate order sized against a position that did not yet include the first — a 2x BUY, not a trade the strategy chose. Skipping forgoes no trade: the original is still working and the next cycle re-evaluates.

### D5 — `pending_qty` semantics: is the fix theatre?

**RECOMMENDATION.** Widen the query; do **not** change the representation now.

- Widening fixes what the signed net CAN express: aggregate committed exposure. A long-only book is BUY-dominated and same-signed, so the net is lossless in the common case and `net_qty` / `max_position_contracts` become correct. That is §0's operator-cap harm, fixed. Confirmed further: class A's gate permits at most **one** working order per instrument, so the mixed-sign net cannot arise while the gate holds — the representation does not defeat the fix.
- Widening does **not** fix the jointly-naked case at `risk.py:192-197`: a +50 net may be a 60 BUY against a 10 SELL, and the SELL component is unrecoverable from a signed scalar. **The representation is a real limitation and must not be advertised as fixed.**
- Not theatre, because that case is now genuinely covered elsewhere: the guard sums working SELLs from `cache.orders(...)` plus the cache-subordinate shim, in **both** modes (`backtest_order_guard.py:396-465`).

*Rejected (deferred) — splitting into `pending_buy_qty`/`pending_sell_qty`.* Right eventually, but `PortfolioSnapshot` carries a 69-caller blast radius and the only consumer that ever needed the split is the guard, which does not read `PortfolioSnapshot` at all. YAGNI until a policy rule needs the sell leg.

**Verified non-issue:** `signed_decimal_qty()` (`base.pyx:934-953`) is built from `leaves_qty`, not `quantity`, so widening onto PARTIALLY_FILLED orders does **not** double-count fills already in `position_qty`.

### D6 — the `risk.py:198-204` docstring

Same change. It is wrong on three counts, not one: (1) its two "independent covers" are one query with one hole; (2) "the second is backtest-only" is stale — `install_live_order_guard` wires the identical class onto a live `MessageBus`; (3) after D3, "every strategy skips evaluation entirely while any order is working" is false for the FLAT path, which never consulted a gate at all. Replacement states: the jointly-naked case is covered at submit time by the guard in both modes; `pending_qty` stays a signed net and still cannot express it; `settled_qty` is unchanged and remains the only quantity a sell may net against. `PROGRESS.md:197-202` carries the same mis-count and is corrected in the same commit.

## 3. RED list (each must fail on today's tree)

- **RED-1** (C, headline) — `net_position=0`, one SUBMITTED BUY of 200 cached; assert `pending_qty` == 200, `net_qty` == 200. Today: 0.
- **RED-2** (C -> operator cap) — settled 0, one SUBMITTED BUY 200, `max_position_contracts=250`; assert a second +200 refuses `max_position` or clips `room` to 50. Today it passes unclipped to net 400. This is §0's confirmed breach sequence.
- **RED-3** (A) — one SUBMITTED order; assert `_maybe_submit` emits no second `submit_order`. Today it submits.
- **RED-4** (A) — INITIALIZED (not yet SUBMITTED); same assertion. Guards the `orders_open+orders_inflight` shortcut rejected in D1.
- **RED-5** (B) — SUBMITTED SELL present, `_flatten` invoked; assert a `CancelAllOrders` command is issued. Today none is sent.
- **RED-6** (B) — no orders at all; assert `_flatten` still calls `close_all_positions` and raises nothing. Pins the cancel no-op path.
- **RED-7** (C) — PARTIALLY_FILLED BUY, 60 of 100 filled; assert `pending_qty` == 40, `net_qty` == 100. Pins `leaves_qty` semantics (D5).
- **RED-8** (docs) — extend a prose guard (precedent: `tests/unit/test_backtest_harness_prose_guard.py`) to assert `settled_qty`'s docstring no longer claims a backtest-only cover. Prevents regression of D6.

A/C coverage for **all five** strategies, not one — they are five copies, and a test on one proves nothing about the other four.

## 4. Scope, sequencing, merge gate, and what must NOT change

1. `weather_common/inflight.py` + unit tests (RED-1, RED-7).
2. **Widen the test stub (R2, previously missed).** `tests/unit/test_weather_strategy_quote_staleness.py:59-61` — `_NoOpenOrdersCache` defines only `orders_open`, is bound as `self.cache` in `_StrategyHarness:71`, and is driven against **real** `_maybe_submit` bodies via `STRATEGY_MAYBE_SUBMIT:43` (parametrized at `:145`). It breaks with `AttributeError` the instant class A/C switch to the shared helper. Same shape as the three `_FakeCache` widenings the guard increments needed. Widen the stub (add `orders`), never delete or skip the test.
3. `forecast_mispricing` — A (`:298`), B (`:391`), C (`:402`), delete `:429-433`. Land and gate alone; it is the template.
4. Replicate to `calibration_mean_reversion`, `forecast_revision`, `running_extreme_lock`, `cli_settlement_print_lock` (latter two: no B).
5. `risk.py:157-206` docstrings + `PROGRESS.md:197-202` (D6).

Optionally one commit per strategy; never split the docstring from the code change — D6 is the point of T-1.

**MERGE GATE for class A (R2).** Do not land class A on D4's argument alone. Required: RED-3 and RED-4 green, **and** a real backtest run showing the baseline **5146 passed / 1 skipped / 4 deselected / 3 xfailed unchanged**. D4's mechanism is now well-argued, but it is inferred, and it is config-conditional — it holds because `latency_model=None` and the submit throttler sits below its rate in *this* harness, which a future config could change without touching this code. This session has produced repeated cases of a confident premise proving wrong, so the premise is measured, not assumed. If the count moves, the widened gate is dropping cycles, D4's conclusion is falsified, and class A is re-argued on measured numbers before merge — the count is never reconciled by weakening an assertion.

**Must not change:** anything under `.venv/**/nautilus_trader/`; `backtest_order_guard.py` behaviour (a cross-reference comment is the most it may receive); `settled_qty`'s return value; `PortfolioSnapshot` field names/types; `resting_ladder.py:262` (class D — a probe whose `open_orders_at_sweep` counter is a venue-behaviour *measurement* pinned by `tests/integration/test_resting_ladder_backtest.py`; widening it would silently redefine what was measured); `allow_short`; edge, fee and break-even math (untouched by every change here — confirmed); any barrier file. No new order-send or egress path.

## 5. Verification status

- **D4's premise: VERIFIED** (was R1's sole open item). Mechanism in D4; conclusion is that the baseline should not move. It remains an *inference from configuration*, which is why §4's merge gate measures it anyway.
- Everything in §1 and §2 is verified against source. Items closed since the brief: only 3 strategies have `_flatten`; no strategy submits an `OrderList` (class C needs no shim analogue); `_NoOpenOrdersCache`'s single-method shape confirmed at `:59-61`.
- Nothing in this plan is now unverified. The open risks below are judgement calls, not unmeasured facts.

## 6. Least-confident decision

**D3's residual scoping** (promoted from second place now that D4 verifies). Deleting the cancel-gate narrows the flatten-refusal window but does not close it: INITIALIZED SELLs are uncancellable and PENDING_CANCEL still counts toward the guard's sum. I judge that acceptable to leave open because the pre-existing alternative is a silent naked short and the residual is strictly smaller than today's window — but that is a scoping judgement, not a proof. If review disagrees, T-1 grows a cancel/close sequencing increment and is re-scoped rather than shipped as "fixed".

Second: **D5's deferral** of the `pending_buy_qty`/`pending_sell_qty` split. Sound while class A's gate holds one working order per instrument, so the mixed-sign net cannot arise; it becomes wrong the moment any strategy is allowed concurrent working orders. Whoever relaxes that gate must revisit D5 in the same change.
