**Verdict: NOT-READY. Confidence 82/100 in that verdict.**

The direction is sound: per-slug slots, K=1 default, and the resolver floors untouched. But the plan misses several single-valued sites that would fail silently at K>1, and it has a deploy-ordering hole that strands the supervisor. Every finding below was read from the code; I edited nothing.

## CRITICAL

**C1. The resolver's identity guards are not covered by H4/H5.**
- `client.py:3197`, `:3339` and `:4063` each run `current = self._latch.current_open(); if current is None or current.intent_id != X: self._ambiguous_bookings.pop(X); return`.
- That is a singleton assumption in three more sites. H4 covers only :2670 and H5 covers only the refusal clears at :3274/:3498/:4106.
- At K>1, or against a tombstone, these guards either raise `CorruptError` or see a different slot's intent. The resolver then pops the booking without a true-up, returns without retiring, and the slot never resolves.
- The booking leak is fail-closed. The stuck slot silently eats K, and no log line marks the failure.
- The firewall allowlist is also insufficient. `EXEC_RESOLVER_PERMITTED_CALLEES` (`test_execution_egress_firewall_guard.py:2149`) names `self._latch.current_open`, and the plan's WP4 rows are `arm_slot`, `is_slug_latched`, `next_open_for_resolution` and `open_intents`.
- A by-id lookup callee (e.g. `get_open(intent_id)`) is needed for the three guards. It must be a named row.
- **Plan change:** list all six `current_open()` sites in H4/H5. Name the by-id callee. Add a RED test where slot B resolves while slot A is still OPEN.

**C2. Slot enumeration has no storage primitive, and the plan is silent on it.**
- `StateStore` is `get/set` only (`submit_intent.py:43-53`), with no prefix scan.
- `open_intents()` and `next_open_for_resolution()` cannot enumerate keys of the form `slot/<sha256(slug)[:32]>`. The hash is also one-way, so the slug cannot be recovered from the key.
- The plan therefore needs either an index key or a scan of the loaded-instrument universe.
- An index key brings a new crash window (index write versus slot write) and its own corruption mode.
- A scan of loaded instruments cannot see an OPEN slot whose instrument failed to load. That leaves an invisible stuck slot at boot and a hole in the supervisor probe.
- **Plan change:** specify the enumeration mechanism and its write ordering. Add crash-at-each-set tests for the index. Store the slug in the intent record itself.

**C3. The WP4-before-WP5 ordering strands the supervisor.**
- The first `arm_slot` writes a v2 tombstone at `CURRENT_INTENT_KEY`.
- `probe_open_intent_resolvable` (`trade_supervisor.py:452-471`) returns False on `SubmitIntentCorrupt`, and `probe_open_intent` returns True.
- If WP4 is deployed (even at K=1, since the tombstone is written regardless) before WP5, any restart with an OPEN AMBIGUOUS slot is refused by the supervisor.
- That is the L-48 stranded-intent failure. Operators would be forced to clear an intent whose order may have filled.
- It also contradicts "every merge before K>1 is behaviour-neutral". The on-disk format changes at the first arm.
- **Plan change:** land the supervisor, CLI and analysis readers (WP5) before or together with the WP4 activation. Or gate slot writes behind the K constant until WP5 is live, so K=1 keeps writing the legacy singleton.

**C4. Restart re-booking (H6) collides with AC6/D3 and AC6b, and the plan does not address either.**
- `_ambiguous_bookings` is empty after a restart. `_resolve_terminal_zero` restores a permit slot only if `booking is not None` (`client.py:3226-3250`, rule D3), because the permit was never debited by this process.
- If WP3 re-books via a real ledger booking and registers it, the resolver will restore a permit slot that nothing debited. That is the D3 violation.
- If WP3 re-books via `seed_spent`, the exposure can never be released on retire. It is a day-keyed idempotent seed, so a retired zero-fill leaves the daily budget permanently reduced until the next restart.
- Separately, `:3458-3467` latches the global DURABLE refusal `_RESOLVER_FILL_UNBUDGETED` whenever `booking is None`, the order is not a SELL, and `_spend_seeded` is true.
- With several restart-inherited slots, each fill resolved by GET halts all slugs for the rest of the process.
- **Plan change:** state which accounting API the boot re-book uses. Specify its release on retire and the permit-restore behaviour. Specify how AC6b and `_RESOLVER_FILL_UNBUDGETED` treat re-booked slots. Add RED tests for each.

## HIGH

**H-1. The `_refuse` dedupe swallows a second slug's AMBIGUOUS.**
- `client.py:6757` returns early if any existing refusal has the same `reason`.
- Scoped refusals for slugs A and B share one reason string, so B's entry is never recorded.
- When A retires, H5 clears "AMBIGUOUS", and B has no refusal left.
- The slot still guards B's own slug. But the plan's "AMBIGUOUS denies that slug" claim and the health surface then under-report.
- **Plan change:** dedupe on `(reason, instrument)`. Add a two-slug test, A ambiguous then B ambiguous then A retires, asserting B's refusal survives.

**H-2. H2 cannot derive the slug at the refusal gate.**
- The gate is at `:6110`. `body["marketSlug"]` is built at `:6226`, after the gate.
- The plan says only "scopes AMBIGUOUS by slug" and does not say how the slug is obtained there.
- **Plan change:** derive the slug from `base_slug_of(order.instrument_id)` (`symbology.py:289`) before the gate. Add a test that the two derivations are equal.

**H-3. The exit path and strategy readers undercount at K>1 or defeat the benefit.**
- `exit_wiring.py:183` and `continuous_strategy.py:2600` call `current_open_submit_intent()`, which returns one intent.
- `exit_wiring.py:183-197` matches that intent's fingerprint to detect a stale ambiguous EXIT and halt the family. At K>1 an exit intent in any slot but the "returned" one is never detected. That is a silent miss of a safety halt.
- The WP6 file list cites `exit_wiring` for `is_intent_open`, but the real consumer is `current_open_submit_intent`. It also omits `continuous_no_side.py:309` (`self._latch.is_intent_open()`), and `continuous_strategy.py:2600` and `trial_day_latch.py:753`.
- If any of these keeps the global predicate, the strategy still WAITs globally and the redesign silently delivers nothing.
- The WP6 and F5 claim that `forecast_quantile_ladder/{decision,latch,persistent_latch}` use the intent latch is wrong. Their `is_latched` is `QuantileLadderLatch`, a different latch (`decision.py:286`). That is harmless but misleads the review.
- **Plan change:** enumerate every consumer of `current_open_submit_intent` and `is_intent_open`. Give `exit_wiring` a by-fingerprint or all-open-slots lookup.

**H-4. Exits compete for K and are blocked by scoped refusals.**
- `exit_guard.py:165-192` blocks any exit when `trading_refusals` is non-empty. The `trading_refusals` property returns reasons only (`client.py:2052`), so the scope is lost.
- One slug's AMBIGUOUS therefore still blocks exits on all slugs. The "blast radius shrinks" claim is false for the exit seam.
- Exits also take a slot and a K position. K stuck entries block the sell-identified-losers seam (ruling 2026-09-16).
- **Plan change:** reserve exit capacity outside K, or document exits as K-exempt. Make `exit_guard` scope-aware, or state the residual global block.

**H-5. `_post_in_flight_intent_id` is not an open question; it is a defect.**
- It is set at `:6325` and cleared in `finally` at `:6349`. With A and B both in flight, B overwrites A's id. A's `finally` then clears B's.
- The no-id resolver skip at `:3747` then fails to protect B.
- The 300 s no-id floor and the POST timeout bound the damage. This is a silent invariant break, not a double order.
- **Plan change:** make it a set (`frozenset`, as the existing `_resolver_stale_alerted_intent_ids`) and add the RED test already named.

**H-6. The K-full check lands after permit consume.**
- H1 gates only on the slug, before the spend. The K check lives in `arm_slot` (`:6291`), after permit consume at `:6238-6254` and after `authorize_order_cost`.
- A denial there wastes a permit order slot. The restore path is confirmed-zero-fill only.
- **Plan change:** H1 must apply the full `admit()`, covering slug, K and quarantine, before any spend. `arm_slot` is only the arbiter.

**H-7. Corrupt-slot handling stalls the resolver for every slot.**
- Today `current_open` raising `CorruptError` leads to `continue` (`:2671-2690`). With multiple slots, one corrupt record stops resolution of all the healthy ones.
- Plan says "corrupt slot quarantines all submissions" but not what the resolver does for the healthy slots.
- **Plan change:** the resolver should skip the corrupt slot, log once per key (the existing `_resolver_corrupt_logged` flag is global), and continue with the others.

## MEDIUM

- **M1. Tombstone, rollback and the CLI.**
  - `clear_submit_intent_cli.py:124-125` calls `latch.current()`, which raises `SubmitIntentCorrupt` on a v2 tombstone. That is uncaught, so the operator is stranded.
  - The plan's WP5 CLI work must handle the tombstone, or rollback and drain cannot complete.
  - Specify write order. Tombstone-then-slot is safe. Slot-then-tombstone leaves old code able to arm after a crash.
  - A drained check must tolerate the fence, or the CLI would erase the fence over OPEN slots.
- **M2. Analysis readers silently undercount.**
  - `score_live_trials.py:190` and `:383-410` read the raw singleton and degrade to `"absent"` on a tombstone. The `intent_state` field then reports "absent" for takes with OPEN slots.
  - `prelaunch_intents.py:50-70` (`_ReadCurrent`) returns "corrupt" or None, and `fill_time_count.py` has the same dependency.
  - WP5 lists these but without tests for the undercount direction.
  - **Plan change:** add RED tests that a tombstone plus OPEN slots yields OPEN, not absent.
- **M3. Resolver global backoff and counters.**
  - `_resolver_consecutive_failures` drives backoff at `:2614-2621` and is written at `:2845`, `:2882`, `:2921`, `:3791`, `:3809`.
  - H7 mentions "slot selection" but not the sleep interval. A 503-ing slot must not set the sleep for the others.
  - The per-intent dicts (`_resolver_last_failure_kind`, `_resolver_stale_alert_details` and similar) are already keyed by id. That is fine.
  - **Plan change:** name that the sleep computation also moves to the selected slot's counter.
- **M4. Round-robin starvation.** One intent per 5 s pass means 6 slots wait up to 30 s each, which is fine against 120 s. But a slot in 503-backoff must not be re-selected ahead of healthy ones (oldest-unserved ordering needs the backoff in its key).
- **M5. Contextless slot after an arm→context crash.**
  - Crash between `arm_slot` and `_note_ambiguous_open` (`:6291` to `:6303`) leaves an OPEN slot with no context and no recoverable slug.
  - The plan says "contextless slot refuses launch" for the supervisor and "assume full per-order cap" for exposure.
  - The slug must be recoverable without the context. The slot key is one-way, so store the slug in the intent record (an explicit v2 schema field).
- **M6. The firewall-ordering pin will break on H1.**
  - `test_execution_egress_firewall_guard.py:3070-3140` pins `self._latch.is_latched` ordering and "no await between the latch gate, the veto and the permit spend".
  - H1 renames the callee, so the test needs a named, same-strength update. Keep the ordering and no-await assertions for the new callee.
  - `is_latched` stays allowlisted for `resume_if_refusals_cleared`.
  - `test_the_order_coroutine_callee_allowlist` uses `==` and the banned-word scan (`read`/`send`/`post`/`request`). `next_open_for_resolution` and `open_intents` contain none, but check any new callee name against that scan.
  - The WP4 callee list should enumerate which rows go on the order allowlist and which on the resolver allowlist.
- **M7. Rate-limit comment and burst.** Beyond restating the comment at `node_config.py:681-698`, the native 5/s denial source must be reflected in H-6, because a RiskEngine denial after permit consume wastes a permit slot. WP0 should simulate that.

## LOW

- **L1. Verified pin-safe.** `_refuse(reason, *, classification=...)` is already keyword-extensible, and the producer pin is keyed by function#ordinal. Adding `slug=` is pin-neutral, assuming the planted-producer tests at `test_exec_refusal_health_surface.py:326-346` are unchanged.
- **L2. Hazard if the AMBIGUOUS refusal's `instrument` is set to the slug.** `_map_position` calls `refusals_after_successful_reconcile(..., instrument=slug)` at `:5073`. It clears only TRANSIENT, so AMBIGUOUS (DURABLE by default) survives today.
  - Add a pin test that scoped AMBIGUOUS entries are never TRANSIENT, so a future reclassification cannot clear them on reconcile.
- **L3. Hash truncation.** `sha256(slug)[:32]` is fine, but the record should still carry the slug and verify it on read.
- **L4. Small plan inaccuracies.** WP6/F5 attributes intent-latch use to the forecast_quantile_ladder files, which is wrong (see H-3). WP0 should also assert that `fill_time_count.py` actually consumes slot data.

## Invariants check
- **Never weaken tests:** nothing in the plan weakens a test. Its stated approach is widening by named rows, keeping `==`. But C1 shows the named rows are incomplete, and M6 shows the ordering pin needs a same-strength rewrite.
- **Resolver floors:** the plan keeps 120 s, 300 s, 5 s and 300 s. No violation.
- **Pin and re-pin procedure:** the procedure is sound.
- **No `Any`, `cast` or `type: ignore`:** no violation stated.
- **Nautilus immutable and orders never enabled:** respected.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r1.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/refusals.py
- /home/jon/breezy/src/breezy/runtime/submit_intent.py
- /home/jon/breezy/src/breezy/runtime/trade_supervisor.py
- /home/jon/breezy/src/breezy/runtime/clear_submit_intent_cli.py
- /home/jon/breezy/src/breezy/settlement/exit_guard.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/exit_wiring.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_no_side.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/trial_day_latch.py
- /home/jon/breezy/scripts/analysis/score_live_trials.py
- /home/jon/breezy/tests/unit/test_execution_egress_firewall_guard.py
- /home/jon/breezy/tests/unit/test_exec_refusal_health_surface.py
