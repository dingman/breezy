**Overall verdict: NOT-READY.** Score: 80/100.

**WP-DR verdict: NOT-READY as written.** It becomes READY after one fix (HIGH-1 below).

r3 resolves most of my r2 findings. Two new issues block it:
- **CRITICAL-1, K>1 only:** in-flight order settlement fails whenever another order books in the meantime.
- **HIGH-1:** WP-DR's claim that it adds no allowlist rows is false against the firewall test.

## r2 findings, checked against the code

| r2 | Status | Evidence |
|---|---|---|
| HIGH-1 neutrality | RESOLVED | §3.3: at k=1, `admit` denies iff any slot is open, for exits too. §3.2 lists deltas D0-D4. |
| HIGH-2 predicate after spend | RESOLVED | The predicate runs inside `admission_refusal` (before :6239), is exception-contained, and is re-run by the arbiter. Tests listed. |
| HIGH-3 day-roll true-up | PARTIAL | WP-DR covers the right three sites, but see HIGH-1. |
| HIGH-4 `base_slug_of` raise | RESOLVED | The :6110 gate is unscoped-only and makes no call. The slug is derived at the :6204 gate inside try/except, after the mapping check at :6190. |
| MEDIUM-1 permit seed | RESOLVED | The permit is unchanged; the ledger alone enforces open exposure. |
| MEDIUM-2 K_eff / scope | RESOLVED in principle, but the chosen rule causes HIGH-2 | |
| MEDIUM-3 unreadable slot | RESOLVED | `raw_slots` kept verbatim, counted as open for the downgrade, and quarantine denies exits. |
| MEDIUM-4 partials | RESOLVED | `seeded_partial_usd`; the exactly-once property covers partials. |
| LOW-1/2/3 | RESOLVED | |

## CRITICAL

**CRITICAL-1. At K>1, settling an in-flight order raises once another order has booked (WP4; F13 is false at K>1).**
- The post-POST ledger calls in `_submit_order` reuse the `now_ns` captured at entry (`client.py:6109`):
  - `true_up_booking` at :6467-6469 (accept-fill);
  - `true_up_booking` at :6555-6557 (zero-fill);
  - `release_booking` at :6570 (reject).
- Meanwhile `authorize_order_cost` sets `_last_ns = now_ns` (`operator_controls.py:426`), and `_require_open_booking` raises if `now_ns < self._last_ns` (:438-441).
- So when order B (any slug) is authorized while order A's POST is awaited, A's true-up raises "clock moved backwards". If B is authorized after 00:00Z, the ledger's `_day` rolls and the check at :443 raises as well.
- :6467 sits in the `else:` of the `record_fill` try, so nothing catches the raise and it escapes the task. The fill record has already been written, but:
  - `_retire` (:6470) never runs, so the slot stays OPEN;
  - `OrderSubmitted` and `OrderFilled` (:6476-6498) are never emitted, so Nautilus position state desyncs from a real fill.
- At K=1 this is unreachable, because nothing else can book during A's await. That is why WP-DR is unaffected.
- **Required:**
  - Post-POST ledger calls read a fresh `self._clock.timestamp_ns()`, which is already allowlisted.
  - They use the WP-DR raise-safe skip.
  - The §3.5 registry calls (`settle`, `_roll_locked`) must tolerate a non-monotonic `now_ns` from concurrent tasks.
  - Add `test_concurrent_authorize_during_post_await_does_not_break_true_up` and a variant that crosses midnight.
  - Add concurrent-task interleavings to the exactly-once property.

## HIGH

**HIGH-1 (WP-DR). The "no new allowlist rows" claim is false.**
- All three bodies are scanned. `_resolve_terminal_zero`, `_resolve_accept_fill` and `_resolve_no_order` (the :4072 site) are members of `EXEC_RESOLVER_COROUTINES` (`test_execution_egress_firewall_guard.py:2113-2130`).
- The planned `utc_day_for_ns(now_ns)` comparison is a new callee. It is not in `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2140-2300`; my grep for `"utc_day_for_ns"` in the test file found nothing).
- **Required:** either add the named row, or, simpler, drop the explicit day comparison. The `except LiveTradingPermissionError` alone then covers the prior-day case; an `except` clause is not an `ast.Call`.
- Also correct §5's text "helper bodies are not scanned".

**HIGH-2. Scope chosen by slot count at append time defeats parallelism (§3.4).**
- `instrument=slug if open_slot_count() > 1 else ""` means the common case at K>1 (a lone in-flight order goes AMBIGUOUS) appends an unscoped refusal.
- The :6110 gate then denies every slug for at least 120 s until that slot retires.
- WP0's d̂ model assumes an AMBIGUOUS order holds one slot only, so the viability numbers do not reflect this behaviour.
- **Required:** scope whenever the configured K>1 (K_eff, which §3.2 already defines as the constant and never the predicate). Stay unscoped at K=1. Add `test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed`.

## MEDIUM

**MEDIUM-1. The ledger pre-check is not read-only, and its budget read can raise (§3.3 step 4).**
- §3.5 says the pre-check calls `_roll_locked` first, which mutates: it rolls the day and converts entries. That contradicts "mutates nothing" and `test_precheck_is_read_only`.
- `operator_max_daily_budget_usd()` raises when the control is unset. If the pre-check reads it unconditionally, an unset control now denies before the spend, which is a new K=1 delta, or crashes `_submit_order` if uncaught.
- **Required:**
  - Compute the roll on a copy, or document the mutation and drop the read-only test.
  - Read the budget only when the uncharged, ambiguous or unknown totals are non-zero, and contain any raise as a returned reason.

**MEDIUM-2 (WP-DR). The midnight accept-fill test asserts semantics that contradict the seed rule.**
- `test_fill_timestamped_before_midnight_resolved_after_is_not_counted_in_new_day` expects no in-process charge on the new day.
- The resolver stamps `ts_event = now_ns` (`client.py:3375-3383`), and the boot seed buckets by `ts_event` (:2418). So a respawn will charge this fill to the new day.
- In-process and post-restart accounting then disagree.
- **Required:** pick one rule. Charging the discovery day is the conservative choice and matches the seed. Make the test assert it.

**MEDIUM-3. Operator reset needs the node stopped.** The `--reset-entry-halt` CLI must take the flock, and the CLI refuses while the node holds it (`clear_submit_intent_cli.py:140-145`). State in §3.6 that resetting requires the node to be down. Otherwise a held position stays without any operator path short of a restart.

## WP-DR verdict detail

- **Scope is complete for K=1.**
  - The resolver ledger calls on possibly prior-day bookings are exactly :3231, :3408 and :4072.
  - :6288, :6294 and :6319 run synchronously in the same task as `authorize`, with no `await`, so they cannot cross midnight.
  - :6467, :6555 and :6570 cannot cross at K=1, because no other `authorize` can roll `_day` or advance `_last_ns` while the latch is held.
  - The pop-only sites (:3199, :3341, :4065) make no ledger call.
- **Pins:**
  - The refusal-producer pin is untouched (no new `_refuse`).
  - `EXEC_RESOLVER_PERMITTED_CALLEES` changes unless the HIGH-1 fix is taken.
  - The firewall ordering pins are untouched.
  - `_EXEC_CLIENT_SHA256` is the only planned pin change.
- **Fix needed:** apply HIGH-1. Also apply MEDIUM-2, or document it.

## Open questions

**Q1. The durable entry-halt key is acceptable and better than a veto signature change, with three conditions:**
- The writer runs in the node process, under the latch's mutex and flock.
- Reset needs the node down (MEDIUM-3).
- The read inside `admission_refusal` is one `get` and is exception-contained, so a raise means deny entries, not a crash.

It keeps `exit_wiring.py:278` and the family-halt chain (`app/trade.py:465, 543`) untouched. Entries versus exits is decided by the tag-derived `is_exit_order` (`client.py:6149`, SELL plus tag), so a NO-leg BUY entry is correctly treated as an entry.

**Q6. No new `_refuse` site; route the raise through the existing error counter.**
- In the WP-DR except branch, call `self._note_resolver_error(intent_id, exc)`. It is already in `EXEC_RESOLVER_PERMITTED_CALLEES` (`test_execution_egress_firewall_guard.py:2249`) and increments the surfaced resolver error counter.
- After the HIGH-1 change the catch also swallows non-day ledger errors (unknown booking, double true-up, clock backwards). Those must stay counted and visible, so log ERROR and do not let them pass silently.
- Producer-pin neutral.

Plan reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r3.md
