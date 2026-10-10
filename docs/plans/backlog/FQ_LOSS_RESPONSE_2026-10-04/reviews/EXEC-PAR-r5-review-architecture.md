**Verdict: NOT-READY.** Score: 90/100.

One new HIGH remains: exit orders are swept into the exposure registry. The fix is a single scoping rule. Everything else from r4 is closed against the code.

**1. r4 HIGH-1 and its conditions: all resolved**
- **HIGH-1 (importer pin): resolved.**
  - The breaker comparison now lives inside the ledger as `breaker_fraction_exceeded` (§3.5, r5:244-248), and any raise counts as tripped. The ledger already reads the budget in its own module.
  - The fractions arrive through `factories.py` (r5:250), which is already on the pinned importer list (`test_operator_reserved_controls.py:759-768`).
  - Invariant 11 and `test_no_operator_controls_importer_added` hold that list unchanged.
- **`_true_up_locked` condition: resolved.** It keeps the input validation and `_require_open_booking(..., now_ns=eff_now)`, and the public methods become thin wrappers (r5:230-231, matching `operator_controls.py:496-515`).
- **Idempotency wording: resolved.** `booking=None` on an unregistered key is a no-op returning False, and a second settle carrying a booking raises (r5:238).
- **Watcher on the event loop: resolved.** It is a native `Actor` timer (r5:323). The `FeeDriftProbeActor` precedent exists (`strategy/current_rung_hold/fee_drift_probe.py`), as does the `extra_actors` seam (`runtime/trade_cli.py:552, 654`).
- **No breaker writes at K=1: resolved.** The watcher is registered only when K>1, so nothing is written at K=1.
- **Q4 AST pin: resolved.** It now covers the releases at :6288 and :6294 (r5:499).

**2. §9 Q1: yes, retire-and-latch in one pass is acceptable, and it is safer than aborting.**
- Aborting re-creates today's stuck shape. In `_resolve_accept_fill` the durable fill is written first (`client.py:3392`); the true-up comes later (:3408) and `_retire` after that (:3429). So an abort leaves the intent OPEN with its fill recorded, re-runs the handler every pass, and keeps the slot of a held position.
- One pass reuses the existing producer (`_resolve_accept_fill#3`, `client.py:3466`), so the producer pin does not move. The end state is the same as today's cross-process-fill halt: the authorized cost stays charged, and a respawn re-seeds.
- **Condition 1:** the "abandon" call `settle(key, booking=None, realized_usd=None)` hits a registered, charged key. Under r5:238 that reads as a "mismatched booking", which raises. A raise there would escape after `record_fill`, which is exactly the abort shape again. The plan must define it as non-raising: either name a separate `abandon_open_exposure(key)`, or add an explicit carve-out in the settle contract. `test_settle_over_cost_retry_does_not_self_heal` must cover it.
- **Condition 2:** the latch stays gated on `_spend_seeded`. A raise during the boot pass before the seed is still covered, because the seed counts the durable record.

**3. New HIGH: exits are registered and settled as daily spend**
- r5:177 registers every armed order, and r5:342 says "every in-process intent is registered at arm"; H6 registers "every still-OPEN intent". Exits are not excluded.
- An exit has no booking, because `is_exit_side` skips `authorize_order_cost` (`client.py:6272-6274`). So under r5:240 it is an "uncharged entry", and its fill adds the realized amount to `_spent_usd`.
- That contradicts the documented rule that the daily budget counts gross entry spend only, and that exits "never debit the daily counter" (`client.py:6260-6271`).
- It is also an undeclared K=1 delta. Exit fills would spend the operator's daily budget, so the day-stop can trip early.
- It also inflates the f_adm and f_breaker AMBIGUOUS totals, so a stuck exit can halt entries.
- **Required:**
  - Register only orders where `not is_exit_side`, at both arm time and in H6 (use `context.order_side != "SELL"`).
  - Alternatively, let `settle` add spend only for BUY entries, and exclude SELL keys from `uncharged_open_total` and `ambiguous_open_total`.
  - Add `test_exit_fill_never_adds_daily_spend_or_exposure` at K=1 and K>1.
  - Note in the r5:296 property that registration is BUY-only.

No other new CRITICAL or HIGH. Plan reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r5.md
