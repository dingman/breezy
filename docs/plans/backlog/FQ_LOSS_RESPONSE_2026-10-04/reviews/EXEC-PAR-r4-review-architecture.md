**Verdict: NOT-READY.** Score: 88/100.

All my r3 findings are resolved. One new HIGH remains: a pin-governance gap with a one-paragraph fix. Once that text is in, I would accept r4 as READY without another full review round. No new CRITICAL.

## r3 findings, checked against the code

| r3 | Status | Evidence |
|---|---|---|
| CRITICAL-1, stale `now_ns` at K>1 | RESOLVED | F12 now states the hazard correctly (`client.py:6109` entry clock; `operator_controls.py:426` sets `_last_ns`; `:438-447` raises). §3.5: a fresh `self._clock.timestamp_ns()` (already allowlisted) is read at the three post-POST and three resolver sites. `settle` uses `eff_now = max(now_ns, _last_ns, _registry_last_ns)`. Tests: `test_concurrent_authorize_during_post_await_crossing_midnight_settles_via_registry` and the concurrent-task arms of the exactly-once property. |
| HIGH-1, WP-DR allowlist | RESOLVED | The WP-DR spec adds `utc_day_for_ns` as a named resolver row and has no blanket `except` (§5). The row being unused after WP4 is harmless: I found no non-vacuity or unused-row check in `test_execution_egress_firewall_guard.py`, and the set is checked with `==`. |
| HIGH-2, scope by slot count | RESOLVED | §3.4 scopes on `max_slots() > 1` (configured K); `test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed`. |
| MEDIUM-1, pre-check | RESOLVED | The roll is computed on a view. The budget is read only when the uncharged, ambiguous or unknown totals are non-zero. Any raise becomes a deny reason. The cost function is shared. |
| MEDIUM-2, midnight accept-fill | RESOLVED | `settle` uses the seed's own predicate (fill `ts_event` day == `eff_day`); `test_in_process_spend_equals_seed_after_restart`. |
| MEDIUM-3, reset needs node down | RESOLVED | §3.6: node down plus `--ack-held-positions-reviewed`, restated in D-PREREG. |

## §3.5 `settle` and the `_true_up_locked` refactor

**`eff_now` is sound.**
- `eff_now` never regresses, so the clock-rewind check (`operator_controls.py:438-441`) cannot trip on a stale clock from a concurrent task.
- The branch is chosen on `eff_day`, and `_day` is only ever set from the same clock that feeds `_last_ns` (:416, :426). So "same-day live booking" implies `booking.day == eff_day == _day`, and `_require_open_booking` (:443) cannot misfire on that branch.
- The cross-day branch matches the seed: a create-path fill keeps the venue `ts_event` and is charged to the booking day; a resolver fill is stamped at discovery (`client.py:3383`) and charged to the new day.

**The refactor is safe if one condition holds.**
- `true_up_booking` today validates its inputs outside the lock (type, finite, ≥0, round, ≤cost: `:496-513`), then calls `_require_open_booking` inside the lock (:515) before mutating.
- `_true_up_locked` must keep both the validation and the `_require_open_booking(booking, now_ns=eff_now)` call. Otherwise `settle` loses the "unknown, released or already trued-up" integrity errors that §3.5 promises.
- Keep the public methods as thin wrappers that pass the caller's `now_ns`, so the existing day-rule and rewind tests are unchanged.
- Spell this out in WP3, and add `test_settle_same_day_unknown_or_double_booking_still_raises`.

**Idempotency wording needs a fix.** `_retire` calls `settle(key, realized=None)` after the fill handler has already settled. State that a call with `booking=None` on an unregistered key is a no-op returning False, and that only a second settle carrying a booking raises.

## §3.6 heartbeat and fail-closed entry-halt

The design is sound: a dead watcher denies entries at K>1, store errors and garbage deny entries, and the resolver never reads the flag. Two conditions should be pinned:
- **Where the watcher runs.** It must be an event-loop task in the node, writing through the latch. If it ran on a separate thread, the latch mutex and the SQLite connection's thread affinity could make every write fail, silently disabling K>1 (fail-closed, but invisible).
- **No heartbeat writes at K=1.** "The check is off at K=1" does not say whether the watcher still writes the key. If it does, `test_k1_store_write_sequence_matches_golden_v1` and the neutrality claim break. State that there are no heartbeat writes at K=1, or exclude the key from the golden explicitly.

## New HIGH

**HIGH-1. The breaker's notional trigger needs the daily budget value, and getting it will move an operator-control pin that the plan says stays untouched.**
- §3.6 trips on `ambiguous_open_total > f_breaker × budget`, and the watcher lives in the runtime layer (WP5b: `trade_cli.py` / `app/trade.py`).
- Reading the budget means a new reference to `operator_controls` from one of those modules. `test_operator_reserved_controls.py:708-768` pins the exact importer list (a substring scan of `src/` and `scripts/`, `==` on 8 rows, documented as "WIDENED, not relaxed (L-12)").
- §3.6 claims "No pin changes", and WP5b names no widening.
- **Required, either:**
  - put the comparison inside the ledger, e.g. `DailySpendLedger.breaker_fraction_exceeded(f)`, using the existing reader with any raise treated as tripped, and surface it through a client property, so there is no new importer; or
  - declare the importer row by name in WP5b with an L-12 docstring entry, and add `test_operator_control_assignment_scan.py` to WP5b's gate.

## Open questions

**Q1: yes, D1 is an acceptable, non-weakening supersession.**
- The latch exists because the in-process ledger "cannot account for" a cross-process fill (`client.py:732-737`). Under D1 a registered intent's fill is accounted for: `settle` adds `max(realized − seeded_partial, 0)` under the seed's own predicate, and the equal-to-seed property proves it.
- Conditions:
  - the successor test asserts that `spent_today` increases by the realized amount, not merely that no latch fires;
  - `registered` is captured from `settle`'s return before `_retire`;
  - if `settle` raises, the handler aborts before the UNBUDGETED check (no partial path);
  - the WP-DR test is replaced by a named successor in the same commit, and the unregistered variant keeps the latch (as planned).

**Q4: no, keep `release_booking` at `:6288` and `:6294`.**
- Both sit in the same synchronous span as `authorize_order_cost` at :6276. The `arm_slot` predicate is synchronous I/O, so there is no `await` and no other task can advance `_last_ns` or roll `_day`. The release uses the same `now_ns` as the booking, so `_require_open_booking` cannot raise even at K>1.
- No registry entry exists yet at either site, so `settle` would be a no-op detour adding an allowlist dependency.
- **Required:** extend the new AST pin ("no await between `authorize_order_cost` and `register_open_exposure`") to also cover `authorize_order_cost` → the `:6288` and `:6294` releases, so the safety argument is enforced mechanically.

Plan reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r4.md
