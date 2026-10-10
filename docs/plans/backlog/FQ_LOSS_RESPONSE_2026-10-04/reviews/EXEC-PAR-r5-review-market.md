**READY (91/100).** I found no new CRITICAL or HIGH findings in r5.

## r4 items: all resolved
- **MEDIUM-1 (gameable build gate):** the build gate now needs a passing bucket of 0.05 or higher (§6), with `test_build_gate_requires_a_bucket_at_or_above_0_05`. The trivial ≤0.02 bucket can no longer satisfy it.
- **MEDIUM-2 (property fidelity):** the property is restricted to BUY records and rounds both sides cent-up identically (§3.5). The seed's raw-sum and SELL-inclusive bias is documented as an accepted exception that always errs conservative (F13).
- **MEDIUM-3 (`seeded_partial`):** it is derived with the seed's own day filter, and is 0 for a prior-day record or a no-id intent. All four tests are named, including the prior-day partial followed by a today final fill.
- **MEDIUM-4 (no live counterpart):** §8 adds the live dropped-candidate-share stop against 0.30, plus alert thresholds for heartbeat-stale denials and `cross_day_settles_total`.
- **MEDIUM-5 (cap drift):** §3.9 adds a boot-time value-free bucket guard. When K>1 and the derived label exceeds the frozen one, or the derivation raises, it forces K=1 and alerts, with no prereg edit. This is machine-enforced, not procedural.
- **LOW items:** the detector is framed as a stuck-slot belt, with `wire_quantity` asserted equal to the order quantity. The heartbeat is written only after a full evaluation. The rollback requires the breaker record to be reset first, with a drill. The in-lock race test is named.
- **Settle integrity path:** this is sound.
  - `settle` is atomic, with validation before mutation.
  - Get-then-pop keeps the booking reachable until the outcome is decided.
  - An accept-fill raise abandons the registry entry, retires, and latches the global DURABLE refusal in one pass.
  - The pre-check now defers to the in-lock day stop when plain `spent + cost > budget`.

## §9 answers
- **Question 1 (accept the deviation):** yes. Retiring and latching in one pass is the right fail-closed choice. Aborting would leave the intent OPEN, hold the slug's slot (blocking the exit of a held position), and make the single UNBUDGETED producer unreachable without a new `_refuse` site that moves the 25-site pin.
  - One wording correction: "the authorized cost stays charged, which is conservative" is false for the over-cost case, where realized cost exceeds the authorized booking. That case undercounts until respawn. It is harmless because the global DURABLE latch halts all trading, and the respawn seed counts the fill. Say so explicitly, and test that the latch is reached on the over-cost path.
- **Question 4 (`cap / budget` as the bucket guard):** yes, it is conservative enough and the right direction. Realized cost cannot exceed the per-position cap, because `authorize_order_cost` rejects any larger cost. A higher cost ratio means more ambiguous-bound drops, so a cap-based label is an upper bound on the drop risk.
  - Condition: the frozen passing label must be expressed in the guard's units. The activation re-run (§6) should be evaluated at cost = cap, not at the typical realized cost. If D-PREREG froze a realized-cost label such as ≤0.02 while the guard compares cap-ratio labels, the guard would force K=1 spuriously. That fails safe, but it makes K>1 unreachable.
  - Also define the label for a ratio above 0.50 as a sentinel above every bucket, so it always forces K=1.

## Non-blocking notes (not findings)
- Add a test that a node restarted with K forced to 1 over an open v2 table (left by a prior K>1 run) still resolves every open slot. Resolver selection must not depend on `max_slots()`, and the table must downgrade to v1 on drain.
- WP0 should print the per-bucket order-cost distribution in both units (realized cost and cap-based), so the frozen label is unambiguous.

Files checked:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r5.md` (:226-305, :355-375, :660-738)
