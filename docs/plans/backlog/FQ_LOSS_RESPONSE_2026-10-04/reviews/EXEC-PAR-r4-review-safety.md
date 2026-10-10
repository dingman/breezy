**Verdict: NOT-READY, 76/100.** All r3 findings are resolved or sensibly answered. Two HIGH gaps remain, both in §3.5 and D1, plus a handful of MEDIUM items. Fix the two HIGH items and the plan is READY.

## r3 findings: status
- **Resolved:**
  - Blanket catch and the allowlist row: the WP-DR spec has no `except` and names `utc_day_for_ns`.
  - Refusal scope: it now keys on `max_slots() > 1`.
  - Duplicate detector: the `qty_est` bug is fixed. I confirmed the hard-coded `"quantity": 1` and the NO-leg complement price in `submit_chain.py:363-373`.
  - Pre-check cost function and read-only view.
  - Lone unreadable slot staying v2.
  - Entry-halt read failing closed.
  - Reset requiring the node to be down.
- **Resolved with new defects:** the `settle` design (H1 below), the D1 supersession (H2), and the pre-check (M1).

## HIGH

**H1. Popping the booking before `settle` erases the escalation of an integrity error.**
- All three resolver sites pop `_ambiguous_bookings` before the ledger call (`client.py:3226`, `:3405`, `:4069`). The accept-fill site calls it before `_retire` (:3408 versus :3429).
- Today, an over-cost raise at :3408 leaves the intent OPEN with a written fill record. The next pass finds `booking is None` and latches the global `_RESOLVER_FILL_UNBUDGETED`, so the error becomes a visible halt.
- Under r4, the same-day over-cost true-up still raises on pass 1, as the plan promises. On pass 2 the booking is gone, but the intent is registered. `settle` then takes the "no booking, registered" branch and adds `realized − seeded_partial`, with no latch, because `registered` is True.
- The integrity error therefore surfaces once as a resolver error count and then heals silently. That weakens today's fail-closed behaviour even though the spec says errors "stay visible".
- **Plan change:** do not pop the booking until `settle` has returned. Keep the booking on the registry entry, so a retry hits the same error. Or make a failed `settle` set a latch (existing UNBUDGETED producer, no new `_refuse` site). Add `test_settle_over_cost_retry_does_not_self_heal`.

**H2. D1 silently flips existing AC6b tests, and the retained variant tests an unreachable path.**
- After WP4 every in-process intent is registered at arm, and every intent OPEN at boot is registered by H6. The UNBUDGETED latch (`not registered and booking is None ...`) then cannot fire in production.
- At least these existing tests assert the latch against an armed or registered intent:
  - `test_edge2_ac6b_cross_process_fill_budget.py:203`, `:246`, `:284` and `:544`;
  - `test_ambig_no_id_resolver.py:612`.
- The `:203` test arms an intent through `_arm_one_ambiguous_intent` and pops only `_ambiguous_bookings`. It would now see `registered=True` and fail.
- D1 names only the WP-DR-successor test and a new retained variant (`..._unregistered_intent_still_latches`). That variant covers a state production cannot reach.
- Invariant 3 allows supersession only by a named successor plus a retained variant for the unchanged case.
- **Plan change:**
  - List every affected existing test by name.
  - Give each a named successor that asserts the new correct outcome: the cost is added once, and no latch fires.
  - Keep each original test's scenario alive by unregistering through a constructible state. Examples: `register_open_exposure` raised at boot, or the context is lost.
  - State that the latch is retained as defence-in-depth for a missing registry entry.
  - Gate D1 on `test_in_process_spend_equals_seed_after_restart` passing, since it replaces a halt with accounting.

## MEDIUM

**M1. Pre-check precedence can suppress the day-stop.**
- The pre-check denies when `spent + uncharged + cost > budget`. With uncharged > 0 and the budget truly exhausted, it denies first with no marker. The authoritative in-lock `spent + cost > budget` (`operator_controls.py:418`) is never reached.
- The durable day-stop marker (:5413-5438) is therefore never written, and the strategy's re-arm gate depends on it. Without the marker, hunt ticks repeat the WAIT-deny loop.
- **Fix:** return None from the pre-check whenever plain `spent + cost > budget`, so the in-lock check raises `DailyBudgetExhausted` as today. Add a test with uncharged > 0 and an exhausted budget.

**M2. `seeded_partial_usd` derivation is unspecified.**
- It must come from the durable fill record for the order and use the same day filter as the seed (`client.py:2418`, `ts_event` day == today). A record stamped another day was not seeded, so its partial must be 0.
- A no-id intent has no `venue_order_id` to look up.
- Without this, `R − P` can double-subtract or leave a gap. Specify the lookup, the day filter and the no-id case. Add tests for each.

**M3. The evidence dump builds a filename from untrusted table content.**
- The path `<store>.unreadable_slot.<key>.<ts>.bin` uses `KEY`, which comes from the corrupt table or the CLI argument. `/` or `..` would traverse the path.
- **Fix:** validate the key against the slot-key regex before use, create the file `0600`, and fsync the directory as well as the file.
- The dump holds "base64 of canonical JSON text", so it is not the original bytes. Re-serialisation can change number formats or collapse duplicate keys. Either keep the original bytes or label the file as canonicalised.
- State that an invalid `raw_slots` entry (bad base64) is a whole-table corruption (latched), never a silent drop.

**M4. The heartbeat proves the watcher loop, not its inputs.**
- A watcher that keeps writing heartbeats while the resolver task is dead sees an empty or stale slot list and never trips. That is the breaker failing open on the failure mode it exists for.
- **Fix:** expose the last resolver-pass timestamp as a client property. The watcher includes it in the heartbeat, or `admission_refusal` denies entries when the resolver pass is older than N polls.
- Also say who emits "alerts once" when the watcher is the dead component. The adapter cannot import the alert sink, so name a supervisor-side check.

**M5. `eff_now` stamping mismatch.**
- A resolver fill is stamped `ts_event = now_ns` captured before the awaits (:3372-3383). `settle` computes `eff_day` from `max(fresh, _last_ns, _registry_last_ns)`.
- A fill discovered at 23:59:59.9 and settled at 00:00:00.1 is stamped day D and excluded from D+1 spend. The seed buckets it the same way, so the invariant holds. But the ledger undercounts real cash by one order per midnight crossing.
- **Fix:** stamp `ts_event` and `fill_ts_ns` from the same fresh clock read used for `settle`, or document the bounded undercount in D-PREREG. I found no path where `eff_now` moves a genuine fill into the wrong day on its own. The stale-high `_last_ns` case is already fail-closed on the authorize side.

## LOW
- **L1.** Reset needs the node down (`clear_submit_intent_cli.py:140-145`). That removes the resolver and exit capability during a possibly false-positive duplicate trip. Record the cost in D-PREREG, or add an in-node reset with the same ack.
- **L2.** Heartbeat writes every 5 s go through the latch mutex into the same sqlite store. Add a test that they do not block `arm_slot`, and consider coalescing them.
- **L3.** The stale-heartbeat and entry-halt reads cost two store `get` calls per order. Cache within the single synchronous admission call.
- **L4.** The "retained unregistered" test name suggests the latch still guards a case. Add a comment that production reaches it only via a registry failure (see H2).

## Checked and fine
- The allowlist rows in WP4 are named: `self._latch.max_slots`, `open_slot_count`, `self._ledger.settle`, `_leg_magnitude_of_signed_net`. None trips the banned-word scan.
- The fresh clock uses an already-permitted callee.
- Pre-POST release sites (:6288, :6294, :6319) stay safe without an `await` since `authorize`.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r4.md
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py
- /home/jon/breezy/tests/unit/test_edge2_ac6b_cross_process_fill_budget.py
- /home/jon/breezy/tests/unit/test_ambig_no_id_resolver.py
