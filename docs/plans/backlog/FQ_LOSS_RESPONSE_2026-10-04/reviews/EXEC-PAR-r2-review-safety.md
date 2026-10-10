**Verdict: NOT-READY, 66/100.**

r2 closes most of my r1 findings with sound designs, and I confirmed those closures in code. It leaves one unsafe silent-loss path and four HIGH gaps.

## r1 findings verified against code
- **Resolved:**
  - C1: the six singleton sites (:3197, :3339, :4063, :3274, :3502, :4106) get H7/H8, and `is_open_intent` and `next_open_for_resolution` are clean names.
  - C2: the table is a single record, so no scan or index is needed.
  - C3: WP5a lands first, with the marker.
  - H-1, H-2, H-5 and H-6: the `(reason, instrument)` dedupe, the `base_slug_of` slug at the gate, the in-flight frozenset, and admission before spend.
  - M-class items: the global backoff drives the sleep, and the throttle drop is upstream of the permit.
- **Partly resolved:** C4 and H-3/H-4. See H1 and H2 below.
- **Allowlist rows:**
  - The WP4 rows in §4 are sufficient for the bodies they name.
  - None of the callee names trips the banned-word scan on `read`, `send`, `post` or `request`.
  - `_retire` is a named callee and not a scanned coroutine, so `settle_open_exposure` inside it needs no row.
  - The H8 slug plumb (M1) may need one more row.

## CRITICAL

**C1. Unreadable slots can be silently dropped when the table is rewritten (§3.1).**
- §3.1 says every arm or retire is one atomic `set` of the whole table. It also says a malformed slot becomes an "unreadable-slot entry" that quarantines admission.
- It does not say the raw bytes of an unreadable slot are carried verbatim through the rewrite.
- A retire of a healthy slot re-serialises from decoded slots. That drops the unreadable one.
- The downgrade rule ("whenever the table would hold ≤1 OPEN slot", writing v1) counts only decodable OPEN slots. A table with one healthy slot and one unreadable slot would collapse to a v1 record, or to a RETIRED record when the last healthy slot retires.
  - That un-latches a possibly live AMBIGUOUS order and lifts the quarantine.
  - Nothing is logged.
- The CLI (WP5a) "clears by intent_id", but an unreadable slot has no readable id. The operator cannot clear it, and the quarantine is permanent unless the table is erased. WP5a's `test_clear_cli_refuses_to_erase_table_over_open_slots` would also block that erase.
- **Plan change:**
  - Preserve unreadable slot bytes opaquely (a raw-slot map). Count them as OPEN for the downgrade rule. Never downgrade to v1 while one exists.
  - Add RED tests: `test_retire_of_healthy_slot_preserves_unreadable_slot_bytes` and `test_last_healthy_retire_does_not_downgrade_over_unreadable_slot`.
  - Add a CLI clear-by-slot-key path with an explicit operator ack.

## HIGH

**H1. Cross-midnight booking at the fill and zero-fill sites (§3.5, F16) is not handled.**
- The ledger prunes lazily, only in `authorize_order_cost` (`operator_controls.py:403-417`).
- `true_up_booking` and `release_booking` raise `LiveTradingPermissionError` for any booking whose day differs from today (`operator_controls.py:443`). This is true even before a roll.
- `client.py:3226-3232` (zero-fill) calls `true_up_booking` after `_retire`.
  - That is a raise on a retired intent. It skips the permit restore, `generate_order_canceled`, and the LAST-statement AMBIGUOUS refusal clear (:3274-3282).
  - At K_eff>1 the slug-scoped refusal then stays forever, so the slug is dead until restart.
  - The Nautilus order is also never cancelled.
- The accept-fill site `:3405` calls `true_up_booking` before `_retire`, so the raise leaves the intent OPEN with a written fill record.
- The plan says only "settle before `_retire`". `_ambiguous_bookings` still holds the stale `SpendBooking`.
- **Plan change:** at every true-up or release site, route by `booking.day` against today. If the booking is prior-day, skip the ledger call and use `settle_open_exposure`. Make the sites raise-safe so the refusal clear and the cancel always run. Add a RED test: ambiguous POST at 23:59Z, zero-fill retire at 00:03Z, with the refusal cleared and the order cancelled.

**H2. Exit exemption breaks K_eff=1 neutrality (§3.3 versus §3.2 item 2).**
- §3.3 makes exits K-exempt. §3.2 claims `admit(K=1)` denies iff any intent is open (equivalent to `is_latched()`).
- WP1 has both `test_admit_k1_equals_is_latched_for_any_table` and `test_exit_is_k_exempt_but_slug_exclusive`. These conflict at K=1.
- After WP5a the marker admits v2. With the K constant still 1, an exit on slug B then arms a second slot while an entry on A is open.
  - That is a parallel-execution behaviour change, a v2 write, and a trade-flow change, all before the activation proposal and the D-PREREG.
- **Plan change:** the exit exemption applies only when `K_eff > 1`. At K=1, `admit` is exactly `is_latched`. Make the property test cover exits.

**H3. The breaker's duplicate-order test (§3.6) is under-specified and can false-trip or miss.**
- **Sign.** "Signed venue-net delta > wire qty" is wrong for NO. The venue nets NO as short YES (memory `venue-nets-no-holding-as-short-yes`). A duplicate NO buy gives a negative delta and is never detected.
  - The existing resolver compares per-leg magnitude: `_resolver_leg_holding_qty` (`client.py:1531`) returns 0 for the other leg.
  - Use the leg magnitude relative to the baseline.
- **Baseline can be None.** `_note_ambiguous_open` leaves `baseline = None` on a read failure (:5983-5990). The test is then undefined. It must be "not evaluable", never a trip or a crash.
- **Stale baseline.** The baseline is a REST read at arm time.
  - After a prior same-slug fill retired by ACCEPT_FILL or an exit, the venue positions page can lag, so that fill appears after the new baseline.
  - The cool-off (§3.8) covers only zero-fill and no-fill retires. That produces delta greater than qty, which counts as CONTRADICTION and makes a family halt that only the operator CLI can clear.
  - Manual trades trip it too. §9.8 accepts that, but a latching halt needs a confirm-twice read.
- **No input path.** The §3.6 input tuple `(intent_id, age, branch, contradiction)` carries no delta. The comparison must be computed inside the resolver and surfaced as `contradiction`.
  - The existing `venue_leg_qty > durable_qty` branch (:3125) only logs and `continue`s. It does not register a contradiction.
- **Plan change:** state the leg-magnitude formula, the None handling, a lag guard (confirm on a second pass or require age over the poll floor), the cool-off for fill retires, and where the contradiction is recorded.

**H4. The H8 scoped clear lacks the retired slot's slug on the no-id path.**
- The no-id resolver can run with `context is None` (`client.py:3735-3760`, "window-only mode"). `wire_market_slug` is therefore unavailable.
- By the clear site, `_retire` has already removed the slot. H8's "AMBIGUOUS refusal scoped to that slug" has no slug source.
- **Plan change:** carry the slug from the `SubmitIntent.slug` returned by `next_open_for_resolution` (record field, not context) into the three resolver bodies. Name the plumbing.
- An unscoped `instrument=""` refusal raised at K_eff=1 and still present after the K_eff>1 transition is never matched by a slug clear. That leaves a permanent global denial. It is safe but silent. Specify the clear rule for it (clear when no other slot is open).

## MEDIUM

**M1. The breaker's halt also blocks exits.**
- `_submit_veto` is consulted for all orders before the permit spend (`client.py:6215`), and `exit_wiring.py:278` also refuses on `is_family_halted()`.
- Confirmed: the breaker never blocks the resolver. `_submit_veto` has a single read site at :6215 inside `_submit_order`, and `record_policy_halt` writes only the halt key.
- The breaker trips when two or more AMBIGUOUS entries are stuck, which is exactly when held positions may need selling. Held positions cannot then be sold until an operator clears the halt.
- The plan should state this plainly and decide whether to exempt exits (a veto signature change). At minimum, alert the operator with the held-position list.

**M2. Exits can still be starved on the same slug (§3.7).**
- A stuck entry on slug S (the 96,824 s order) blocks the exit of any held position on S. That is the cooloff-plus-slug rule.
- This is equivalent to today, not worse. But r2 presents it as resolved.
- Add a breaker or alert input: "stuck slot on a slug with a held position".
- Clarify whether the 120 s cool-off applies to exits. It should not apply to exits, because a late fill cannot enlarge a SELL.

**M3. The cool-off storage is inconsistent.** §3.1 puts `"cooloff"` in the v2 table, but §3.8 says it is in memory only. The v1 downgrade would drop it. Pick one.

**M4. Boot registration (H6) timing.**
- The resolver task starts before `_reconcile_submit_intent` (:2194 versus :2227), and several awaits sit between them. H6 says "still OPEN after the first resolver pass", but the first pass is not awaited.
- The no-await span from seed to `_spend_seeded` is sound and I confirmed it (:2227-2236). But the registered set then reflects whatever has retired by that moment, and the ordering relative to a retire is racy.
- Confirm that `has_open_exposure` captured at the top of each synchronous fill-handler body (no await before the check) makes this safe. Add a test that interleaves a retire with the boot registration.

**M5. Over-budget at boot.** The plan says `_intent_reconciled` stays True and the resolver is independent. True for the resolver. But entry orders are denied silently. Make sure this is a logged WAIT that names the boot-inherited reason, not a silent deny.

## LOW
- **L1.** The `admit` exit predicate is `order.side == SELL`, but exit authorisation is tag-derived (`is_exit_order`). A SELL without valid exit tags would pass the K-exempt gate and be rejected later. This is harmless. Derive the flag consistently.
- **L2.** H5 passes `skip=...`, which may build a `frozenset(...)`. A builtin call inside the resolver coroutine needs a named allowlist row or an inlined comprehension.
- **L3.** The breaker's `f × budget` trigger can never fire under the admission bound (`open_other + cost > f × budget`). It matters only for boot-inherited or day-roll-surviving exposure. Say so, so the test does not pass vacuously.
- **L4.** `OpenExposureBoundExceeded` subclasses `LiveTradingPermissionError`, and `_submit_order` maps that to a plain deny that burns the booking only if released. Add an explicit test that the permit slot and the ledger booking are untouched, since the check runs after `authorize_order_cost`.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r2.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/composition.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/exit_wiring.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/trial_day_latch.py
