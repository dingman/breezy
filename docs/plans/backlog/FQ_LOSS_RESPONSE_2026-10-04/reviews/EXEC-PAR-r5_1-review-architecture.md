**READY.** Score: 92/100. No new CRITICAL or HIGH.

**1. E4 closes my r5 HIGH: yes.**
- Exits are now excluded at both entry points: at arm time by `not is_exit_side`, matching how exits already skip the ledger (`client.py:6272-6274`), and at boot (H6) by `order_side != "SELL"`.
- A legacy context with no recorded side decodes as BUY (`client.py:1133` defaults to `LONG_ONLY_SIDE`), so it is counted, which is the conservative direction.
- The ledger also refuses a SELL registration, `mark_ambiguous` on an exit key is a no-op, and the exposure totals count BUY only.
- The `uncharged_open_total` and `ambiguous_open_total` totals can no longer pick up exits.
- The three named tests cover it at K=1 and at K>1.

**2. E2 satisfies condition 1: yes.**
- `abandon_open_exposure` cannot raise and adds no spend.
- The `settle` contract stays strict.
- The new allowlist row passes the banned-word scan (no read, send, post or request).
- The successor test asserts abandon was called, nothing escaped, the latch was reached and there is no self-heal. That is the evidence I asked for.

**3. E1 ordering: no CRITICAL or HIGH, but two MEDIUM conditions to fold into the WP4 brief.**
- **The good part.** Get → `settle` → pop → `_retire` fixes the r5 double-settle defect.
  - At zero-fill, the booking local is still non-None when the permit restore runs, so restore behaviour is unchanged (`client.py:3227-3244`).
  - The no-id restore (:4073-4082) is likewise unchanged.
- **MEDIUM-a (E1): a `settle` raise at the zero-fill or no-id site now leaves the intent OPEN forever.**
  - Today `_retire` (:3218, :4067) runs before the true-up (:3231, :4072), so a raise there still retires.
  - Under E1 the raise comes first, and r5's statement that these sites "propagate exactly as today" is no longer true.
  - The slot stays held and the same error repeats every pass. This fails closed (the slot is held and the breaker counts it as stuck), but nothing ever resolves it.
  - **Fix:** mirror E2 at these two sites: on a `settle` raise, call `_note_resolver_error`, then `abandon_open_exposure`, then `_retire`. Leave the AMBIGUOUS clear skipped, as today. Add `test_zero_fill_and_no_id_settle_raise_abandons_and_retires`.
- **MEDIUM-b (E5): the convergence claim is unproven.**
  - A create-path fill's pre-POST context carries no venue order id (`client.py:6305`), and the booking is not in `_ambiguous_bookings` (it is set only at :6344 and :6644).
  - So the resolver probably takes the no-id route after the 300 s floor, not the with-id accept-fill path.
  - It would then hit a registered, charged entry with no booking, which by E2's own contract raises.
  - **Fix:** `test_create_path_settle_raise_converges_to_resolver_latch` must exercise this real route. If it does not converge, have the create-path catch call abandon plus the latch locally.

Both conditions apply only after a same-day ledger integrity error (that is, a bug), and both fail closed. Neither blocks WP0–WP3, WP5a, or WP-DR.

Delta reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r5_1_delta.md
