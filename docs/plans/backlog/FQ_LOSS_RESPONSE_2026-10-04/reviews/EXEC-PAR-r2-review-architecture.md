**Verdict: NOT-READY.** Score: 74/100.

r2 fixes the structural problems from r1: the single-record slot table, WP5a landing first, and the resolver identity guards. Four issues still block it:
- **Neutrality proof:** two of its five claims are false as written.
- **Marker predicate:** a false predicate still burns a permit slot.
- **Ledger:** the day-roll path breaks the client's true-up and release calls.
- **Refusal gate:** a raising slug helper sits at the top of `_submit_order`.

All four are fixes to the specification, not redesigns.

## r1 findings, checked against code

| r1 | Status | Evidence |
|---|---|---|
| C1 WP order | RESOLVED | WP5a lands first. The marker pattern exists (`supervisor_decode_marker.py:142-156`). The predicate is re-evaluated at every 1→2 transition. |
| C2 enumeration | RESOLVED | There is one atomic `set` of the whole table. The v2 table reads as corrupt in v1 code because `from_bytes` requires `v==1` (`submit_intent.py:285`). Extra keys are ignored (:287-298), so the F4 claim holds. |
| H-a gate position | RESOLVED; dissent accepted (Q1) | See "Q1" below. |
| H-b K-full permit waste | PARTIAL | See HIGH-2. |
| H-c resolver guards | RESOLVED | H7 covers :3197, :3339 and :4063. |
| H-d `_refuse` dedupe | RESOLVED | |
| H-e in-flight id | RESOLVED | The frozenset change is correct. |
| H-f re-book and UNBUDGETED | PARTIAL | See HIGH-3 and MEDIUM-1. |
| H-g missed readers | RESOLVED | I checked the consumer table: `exit_wiring.py:183`, `trade_cli.py:432/538`, `trade_supervisor.py:2939`, `app/trade.py:465/543`. |
| M1–M5, L1–L3 | RESOLVED | |

## HIGH

**HIGH-1. Neutrality proof claims 2 and 4 are false at K=1 (§3.2, §3.3, §3.5).**
- **Claim 2 fails for exits.**
  - `admit` makes exits K-exempt (§3.3, §3.7). At K=1, with an entry open on slug A, an exit on slug B is admitted. Today `is_latched()` denies it (`client.py:6204`; `submit_intent.py:386-397`).
  - Once WP5a is deployed and the marker is present, that exit performs a 1→2 transition. The node writes v2 with two open slots while K is still 1.
  - `test_admit_k1_equals_is_latched_for_any_table` only holds if it excludes `is_exit=True`.
  - **Required:** exits are K-exempt only when K_eff>1. Make the property test quantify over `is_exit` as well.
- **Claim 4 fails because the exposure changes are not additive at K=1.** Three of them run whatever K is:
  - the H6 boot registration;
  - the day-roll conversion;
  - the new UNBUDGETED condition (`... and not registered`).
  - At K=1 today, a boot-inherited cross-process fill latches the global DURABLE `_RESOLVER_FILL_UNBUDGETED` (`client.py:3460-3466`) and halts all trading until respawn. Under r2 it settles into the ledger and trading continues.
  - That may be the better behaviour, but it is a behaviour change, and it reaches production at the WP4 merge.
  - **Required:** restate the claim as "neutral except the enumerated exposure deltas". List each delta with its test, and name WP4 as non-neutral in §7 rollback item 1.

**HIGH-2. A false predicate is evaluated after the permit spend, which brings back r1 H-b.**
- §3.2 says that when `v2_admitted()` is false, `arm_slot` refuses as a WAIT. But `arm_slot` runs at `client.py:6291`, after `authorization.consume` at :6250.
- Every `arm` exception releases the booking only, not the permit (:6292-6297).
- `admission_refusal` (§3.3) does not include the predicate. So a K>1 node with a rolled-back supervisor burns one permit slot per 1→2 attempt.
- A predicate that raises (marker stat or `/proc` OSError) becomes `STORE_RAISED_REASON` after the spend (:6297).
- **Required:**
  - `admission_refusal` evaluates the same predicate on would-be 1→2 transitions.
  - The predicate is exception-contained and returns False on error.
  - Add the test `test_predicate_false_is_wait_before_permit_spend`.

**HIGH-3. The day-roll conversion breaks the client's true-up and release sites.**
- §3.5 converts open bookings into uncharged entries at the roll and says existing semantics are unchanged.
- But `_require_open_booking` raises on any prior-day booking (`operator_controls.py:443-447`). The client still calls true-up and release on those bookings:
  - `true_up_booking` at :3231 (zero-fill), :3408 (accept-fill, which runs **before** `_retire` at :3429) and :4072;
  - `release_booking` at :6288, :6294 and :6319.
- **Accept-fill path:**
  - Pass 1: `_ambiguous_bookings.pop` at :3406, then `true_up` raises, so the intent is never retired.
  - Pass 2: the booking is None. If pass 1 had already settled the registry, the UNBUDGETED condition fires and halts everything.
- **Zero-fill path:** the raise comes after `_retire`. The AMBIGUOUS clear at :3274, which runs last, is skipped, so the refusal stays until respawn.
- This defect exists at K=1 today (the 96,824 s order crossed midnight), but r2 adds state that depends on it.
- **Required:**
  - Each call site skips true-up and release when `booking.day != today`. Settlement then goes through the registry only.
  - Specify that the registry settle runs after the realized cost is computed and that re-entry is idempotent.
  - Add the test `test_day_rolled_ambiguous_fill_retires_once_no_unbudgeted_no_stuck_refusal` for both the fill and zero-fill paths.

**HIGH-4. `base_slug_of` can raise at the top of `_submit_order` (the scoped gate at :6110).**
- `base_slug_of` raises on an invalid slug or a foreign venue (`symbology.py:298-314`: `assert_valid_slug` and `VenuePayloadError`).
- §10 S-H-2 places it "at the top", before `unmappable_order_reason` (:6189-6191). An exception there escapes the coroutine, so the order is never denied and is left in a non-terminal state.
- **Required:**
  - The :6110 gate checks only unscoped refusals.
  - The slug and the scoped-refusal check move to the admission gate at :6204, which runs after the mapping check at :6190.
  - Alternatively, wrap the derivation so a raise becomes a deny.
  - Add the test `test_unmappable_instrument_denied_not_raised`.

## MEDIUM

**MEDIUM-1. The permit-seed specification contradicts itself (§3.5 H6).**
- `seed_permit_budget_from_prior_spend` applies once per `permit_id` (`safety.py:833-840`). `_seed_spend_from_durable_fills` already calls it when there is at least one fill (`client.py:2426`).
- So a separate H6 step's permit seed is a no-op on exactly the days with fills.
- You cannot both leave the early return at :2422 alone and do the permit seed "in the same once-only call".
- **Required:** fold the open notionals into the single seed computation. The ledger part through `register_open_exposure` stays separate.

**MEDIUM-2. K_eff is undefined, and the refusal scoping depends on it.**
- Claims 3 and 4 and H8 switch on K_eff. If K_eff is derived from the predicate, a supervisor rollback with two slots open gives K_eff=1. Unscoped AMBIGUOUS refusals then get cleared under the "existing" `current_open() is None` condition against a v2 table.
- **Required:** define scoping from the table state at the time the refusal is appended, meaning more than one slot open (or the configured K), never from the predicate. Store the scope on the refusal itself.

**MEDIUM-3. Q5, per-slot decode.** Skipping the unreadable slot is safe if three conditions are pinned by tests:
- quarantine also denies K-exempt exits;
- retiring a healthy slot re-writes the unreadable slot's raw bytes verbatim;
- an unreadable slot counts as open for the ≤1→v1 downgrade, so the table is never downgraded to v1 over a lost slot.
- None of these is stated in §3.1.

**MEDIUM-4. Partial-fill double count.**
- §3.5 boot counts open notional plus the durable partial. That is conservative, but `settle(uncharged, realized)` then adds the realized cost a second time.
- **Required:** settle must subtract the already-seeded partial, or the exactly-once property test must model partials explicitly.

## LOW

**LOW-1.** §3.1 gives v2 a `"cooloff"` field, while §3.8 says the cool-off lives in process memory. Pick one.

**LOW-2.** The §3.1 bullet "v1 bytes while ≤1 OPEN **and** the supervisor has not advertised" can be misread as "a 0→1 arm writes v2 once the marker exists". State it as "v1 whenever ≤1 open, unconditionally".

**LOW-3.** The predicate's `/proc` and marker reads are synchronous I/O on the event loop. Each is a single stat or read, so this is acceptable (Q7).

## Answers to §9 Q1, Q5 and Q7

**Q1: acceptable, conditional on HIGH-4.** The gate at :6204 already sits after the mapping check at :6190, so `base_slug_of` is safe there. The `<` chain at `test_execution_egress_firewall_guard.py:3081-3106` survives with one renamed row. The body-slug equality check covers wire divergence.

**Q5:** see MEDIUM-3.

**Q7:** acceptable in `arm_slot` (runtime layer, no adapter import), provided it is exception-contained and mirrored in `admission_refusal` (HIGH-2).

## Facts I checked and found correct

F2, F4, F6 (:3502), F9, F12–F15 (the `_connect` order is :2194 resolver task, :2210 reconcile, :2216 seed, :2223 `_spend_seeded`; no `await` between :2210 and :2223), F16 (:403-417, :443), F17, F20 (`engine.pyx:145-150`), F23.

H6 is placed between seed and `_spend_seeded`, and there is no `await` there, so registering only "still-OPEN" intents is race-free against the periodic resolver task started at :2194.

Plan reviewed: /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r2.md
