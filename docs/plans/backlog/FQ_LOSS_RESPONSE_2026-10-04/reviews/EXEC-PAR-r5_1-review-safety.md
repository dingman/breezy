**Verdict: READY, 91/100.** E10′ routes as claimed, with the corrections below. E9 and E11 close the remaining items. No CRITICAL or HIGH issue.

**1. Routing: yes, with one timing correction.**
- An upgraded with-id context sends a FILLED order to `_resolve_accept_fill`.
- The path is `client.py:3141-3148`. `is_fill` holds, then `fill_confirmed` (`long_state is True`, or a complete activities join with at least one trade), then `_resolve_accept_fill`.
- The 120 s floor does not apply. It gates only the terminal zero-fill branch (:3089). An accept-fill resolves on the first pass after the GET shows FILLED, so convergence is at most one poll. The "after 120 s / floor + one poll" wording in E10′ is wrong but harmless. Fix the test's timing assertion.
- The resolver does not read the durable fill record. It rebuilds a synthetic one and rewrites the same key. The create-path record's real fee data and venue timestamp are overwritten with `fee_reconciled=False` and the discovery time. That is acceptable in this rare integrity-error case. State it in E10′.
- With the key unregistered and no booking, `settle(booking=None)` returns False and `registered` is False. The existing UNBUDGETED producer at :3466 therefore latches.

**2. Venue order id at :6467: yes.** The same branch already builds the record from `fill.venue_order_id.value`. `outcome.venue_order_id` is also in scope, as at :6628.

**3. Permitted callee: yes.** `self._note_ambiguous_open` is on the order-coroutine allowlist (`test_execution_egress_firewall_guard.py:2000`, and the equality set at :3203). No new row is needed.

**Conditions to fold into E10′ (MEDIUM, not blocking):**
- Pass `register_booking=False` and `booking=None`. The default `register_booking=True` writes the booking into `_ambiguous_bookings` (:6016). A stale booking there would make the resolver's `settle` raise on an unregistered key. It would still reach the latch via E2, but through a noisier path, and step 4 forbids it.
- Wrap the `_note_ambiguous_open` call in `try/except`. A store failure must not mask the original exception. If it fails, the intent stays no-id and falls back to the 300 s route, so log that.
- Emit `self._generate_submitted(order, now_ns)` before re-raising. It is already allowlisted (used near :6600).
  - The create path emits `OrderSubmitted` only after `_retire`, which the raise skips.
  - Without it the resolver's `generate_order_filled` hits an INITIALIZED order. Nautilus drops the event, so the venue position is invisible to the strategy until the next reconcile. The global latch limits the exposure, but the drop is silent.
- The test should assert `OrderSubmitted` and `OrderFilled` are emitted once each. It should also assert that the durable record is rewritten with the stated degradation.

**E9 closes my E1 side-effect item.** The order is `_note_resolver_error`, then `abandon_open_exposure`, then pop, then `_retire`. The cancel and permit restore run. The AMBIGUOUS clear is skipped, which is conservative.

**E11 closes the E4 item.** No `await` sits between `authorize_order_cost` and `register_open_exposure` (the sequence is `_intent_reconciled`, `arm_slot`, `register`), so the booking release is same-task and safe. Name the retirement reason explicitly as the existing `DEFINITIVE_REJECT` member. A new reason would be gated by the supervisor decode marker.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r5_1_delta.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/tests/unit/test_execution_egress_firewall_guard.py
