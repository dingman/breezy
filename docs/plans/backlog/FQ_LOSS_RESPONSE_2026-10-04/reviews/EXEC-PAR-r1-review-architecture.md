**Verdict: NOT-READY.** I am 85/100 confident in that verdict.

The native-Nautilus case holds. The plan fails on three things:
- **Store design:** the store cannot enumerate keys, so per-slot keys cannot be listed.
- **WP ordering:** the node would write the new v2 record before the supervisor can decode it.
- **K=1 claim:** "K=1 is behaviour-identical" is false at H1, at the resolver identity guards, and in the durable format.

## CRITICAL

**C1. WP order breaks the supervisor decode-before-write rule (WP4 before WP5).**
- After WP4, the first `arm_slot` writes a v2 tombstone at `CURRENT_INTENT_KEY`. The supervisor still on old code decodes it as corrupt.
  - `probe_open_intent` returns True (`trade_supervisor.py:446-448`).
  - `probe_open_intent_resolvable` returns False (`:467-470`).
  - Every launch is then refused. This is the L-48 strand.
- The repo already has the right pattern for this hazard: the decode marker in `supervisor_decode_marker.py:1-20, 63-100`.
- So "every merge before then is behaviour-neutral" (§4 last paragraph, §6 rollback 1) is false.
- **Required:**
  - Split WP5 into WP5a, which ships before WP4: the supervisor decodes v2 and advertises a "slot-schema" capability, by extending the marker with a new field or a v2 marker.
  - The node writes v2 only when `supervisor_admits_*` is True. Otherwise it stays v1 and K is forced to 1.

**C2. The store has no way to enumerate keys, so `open_intents()` has no implementation.**
- `StateStore` is get/set only (`submit_intent.py:43-53`). No scan, delete or list exists anywhere in `src/` (I grepped for it).
- Keys like `slot/<sha256(slug)[:32]>` cannot be discovered at boot, by the resolver, or by the supervisor.
- An index key brings back a crash window across two `set`s.
- **Required:** make the v2 record at `CURRENT_INTENT_KEY` the slot table itself, `{v:2, slots:{base_slug: intent}}`.
  - Each arm or retire is then one atomic `set` under the existing mutex.
  - Keep history-first retire (`:509-510`) unchanged.
  - The fence and the index become the same record, which removes the crash window between them.

## HIGH

**H-a. H1 at `:6204` cannot use `body["marketSlug"]`, which does not exist until `:6226-6230`.**
- Moving the gate after the body build breaks the SAFETY C1 ordering pin.
  - The pin is `test_execution_egress_firewall_guard.py:3081-3101`. It requires an `is_latched` call, and requires it to come before the veto and the permit spend.
- **Required:** state the new position (after the body build, before `:6238`). Widen the pin by a named row for the new callee, keeping the `max(...) < min(...)` ordering and the no-await check. Name this test in WP4.

**H-b. At K=1, `is_slug_latched(slug)` is not equivalent to `is_latched()`.**
- Suppose the one slot is held on slug A and an order arrives on slug B.
  - B passes H1 and consumes the permit (`:6250`).
  - `arm_slot` then refuses on K, giving `LATCH_ARM_REFUSED`.
  - The booking is released but the permit slot is burned.
- This is exactly the waste F8 and F7 exist to prevent (open question 6).
- **Required:** the H1 gate must evaluate the full admission check (same slug OR at K OR quarantined) before the spend. The same predicate (WP1 `admit`) is reused inside `arm_slot`.

**H-c. Missed resolver singleton guards.**
- `_resolve_terminal_zero` `:3197-3200`, `_resolve_accept_fill` `:3339-3342` and no-id retire `:4063-4066` each check `current_open().intent_id == mine` and otherwise return early.
- At K>1, every non-selected slot would silently never retire. "Pass body unchanged" (H4) is wrong.
- **Required:** add hunk H9, which replaces these with `self._latch.is_open(intent_id)`. Add that as a named row in both `EXEC_RESOLVER_PERMITTED_CALLEES` (the current row is at `:2149`) and the exec allowlist.

**H-d. `_refuse` dedupes on the reason string alone (`client.py:6757`).**
- A slug-scoped AMBIGUOUS for slug B is dropped while A's entry exists.
- **Required:**
  - Change the dedupe key to `(reason, instrument)` (no new callee).
  - Pin `classification=DURABLE` on the scoped AMBIGUOUS. The reason is that `refusals_after_successful_reconcile` (`refusals.py:302-323`, called at `client.py:5073-5075`) drops TRANSIENT entries scoped to the slug being reconciled.
  - Add a test that `_map_position` success on slug A never clears A's AMBIGUOUS.

**H-e. `_post_in_flight_intent_id` is clobbered when K>1 (open question in WP4/R7).**
- It is set at `:6325` and cleared in `finally` at `:6349`. Its only reader is the no-id guard at `:3747`.
- With two concurrent POSTs: A sets the field, B overwrites it, then A's `finally` sets None while B is still in flight. B's no-id resolution is then unguarded. The 300 s floor only masks this.
- **Required:** make it a `frozenset[str]` with whole-value reassignment, as `_resolver_stale_alerted_intent_ids` does (`:1945`). The reader becomes a membership test. No new callee is needed.

**H-f. F14 and H6 ignore the existing `_RESOLVER_FILL_UNBUDGETED` control (`client.py:732-737, 3460-3466`).**
- If boot seeds open-intent notional with no `SpendBooking`, then a later cross-process fill still trips the global DURABLE refusal. That halts every slug until respawn, and the fill is double-counted against the seed.
- `seed_spent` is once-only and takes `max()` (`operator_controls.py:307-334`), and the early `return` at `client.py:2422` skips the seed when there are no fill records.
- **Required:** H6 must specify all of the following:
  - the seed formula when there are zero fills;
  - how a boot-rebooked intent later trues up or releases, or an explicit statement that it stays charged for the day;
  - the matching edit to the `:3460` condition.
- An `operator_controls.py` API change, if needed, must be listed in WP3/WP4.

**H-g. Readers that the tombstone breaks are not in WP5/WP6:**
- `scripts/analysis/score_live_trials.py:190,531` (raw singleton `state`);
- `strategy/current_rung_hold/continuous_no_side.py:309` (`is_intent_open`);
- `trial_day_latch.current_open_submit_intent` (`:753-773`), consumed at `continuous_strategy.py:2600` and by `exit_wiring.check_exit_intent_for_ambiguous_send`, which asks whether its own exit is stuck and needs a per-slug answer;
- `client.resume_if_refusals_cleared` (`:6785`);
- `trade_supervisor` probe consumers at `:1298-1307, 1361-1377, 1476, 1866`;
- `runtime/supervisor_decode_marker.py`.

## MEDIUM

**M1. Open question 3, the tombstone.** The fail-closed direction is right, but rollback is stranded today.
- The old `clear_submit_intent_cli.py:125` calls `latch.current()`, which raises an uncaught `SubmitIntentCorrupt` on v2. The old CLI cannot clear the fence.
- **Required:**
  - When the last slot retires, rewrite `CURRENT_INTENT_KEY` as a valid v1 RETIRED record.
  - While at most one slot is open, write v1 bytes exactly.
  - This makes K=1 durable-format identical, and makes rollback free once drained.

**M2. H7 per-intent counters must not replace the global backoff.**
- The counter already resets on any successful GET (`:2934`, `:3815`). So F11's claim that one stuck intent slows every other one is inverted: alternating slots keep the backoff near its base.
- The global sleep (`:2613-2621`) is the 15 req/s protection during a venue-wide 5xx.
- **Required:** keep the global counter for sleep. Add per-intent counters only to skip a slot when choosing which one to resolve.

**M3. The 5/s native throttler drops orders rather than queueing them.**
- `engine.pyx:145-150` sets `output_drop=self._deny_new_order` with a 1 s window.
- **Required:** WP0 must model this as a drop (counted in d̂). §3.3's "5 s window" reasoning must be restated.

**M4. Open question 7: native free-balance denial exists.** `engine.pyx:949` checks per order (cumulative only within a list, `:968`). WP0 must record whether parallel cash BUYs can be denied there before account state updates. This is a native denial source, not a cap.

**M5. WP1 `admit` parity.** It is "the same function the production path uses" only if `arm_slot` (runtime) calls it. Calling it from `_submit_order` would be an unlisted callee. State that.

## LOW

**L1. Typing.** `self._latch: Any` (`:1848`) means mypy cannot catch a typo in `arm_slot`/`is_slug_latched`. Consider a Protocol in `domain/` (the adapter imports domain only).

**L2. Exception type.** `is_latch_arm_refusal` matches by type name (`submit_chain.py:213-214`). Reuse `SubmitIntentLatched` for K-full. Do not add a new exception.

**L3. Open question 5.** A keyword-only slug on `_refuse` is pin-neutral. The pin keys on `self._refuse` call count and ordinal only (`test_exec_refusal_health_surface.py:266-291`, producer set `:182-242`).

## Answers

**Open question 4.** Round-robin is enough.
- `_REARM_MIN_DELAY_SECS` is measured from `last_attempt_ns` in event time (`continuous_strategy.py:2354, 2514`).
- The pin is constant equality only (`test_current_rung_hold_ambiguous_resolver.py:4004`).
- Extra resolver latency of (K−1)×5 s only lengthens the WAIT at `:2508`. No gate breaks.

**Open question 6.** There is no `await` between H1 and `arm_slot` (`:6204-6291` are synchronous). The real hole is K-full permit waste (H-b), not a race.

## Focus areas

**Native Nautilus.** The §2 analysis is sound. In-flight checks are correctly kept disabled (`node_config.py:876-901, 1036`). There is no native per-slug exclusion or daily cap.

**Layering.** Preserved, provided the new latch methods stay on the injected object and the new exceptions are exposed as class attributes (as with `CorruptError`, `submit_intent.py:338`).

**Hard invariants.** No WP violates them as written. However, H-a and H-c need named widenings of the firewall/ordering pins, and WP4 does not yet list them.

## Facts verified as wrong or incomplete

1. **F6/H5 cite `:3498`.** The clear is at `:3502-3514`; `:3498` is a comment.
2. **F11 framing.** The global counter resets on any success (`:2934`, `:3815`). It does not simply slow other intents.
3. **F14.**
   - It omits the `_RESOLVER_FILL_UNBUDGETED` latch (`:732`, `:3460-3466`).
   - The K=1 gap is not "≤1× cap". It is zero, because the boot singleton blocks all submits, and a cross-process fill after the seed latches a DURABLE refusal.
4. **F5 is incomplete.** See H-g.
5. **H1 location.** `body` is not built at `:6204`.
6. **H2 location.** The slug is unavailable at `:6110`: the instrument is read at `:6120` and the body at `:6230`.
7. **H4 "pass body unchanged".** False, because of `:3197`, `:3339` and `:4063`.
8. **§3.3 "fits in a 5 s window".** The native throttle is 5 per 1 s and drops excess orders.

All other cited lines check out: F1–F4, F7–F10, F12, F13, F15–F20, F22, F23, the constants at `:588/592/1585/1596/1604`, and the age gates at `:3089/3752`.

Plan reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r1.md
