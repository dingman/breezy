# PLAN r3: EXEC-PAR, bounded per-market-slug parallel submit intents

Status: DRAFT r3 for peer review. Build-time only. This plan builds capability and does not re-enable orders. It was written read-only, and the coordinator saves it.
Supersedes r2. All 14 coordinator rulings are adopted. §11 maps every r2 finding to its resolution.

**Delta from r2**
- The midnight-roll defect is extracted as a standalone, K-neutral **WP-DR** that merges first.
- Admission is complete before any spend: the slug and scoped-refusal gate, the v2 predicate, a read-only ledger pre-check, and the entry-halt flag.
- Permit seeding is unchanged (durable fills only).
- Only unresolved AMBIGUOUS notional is bounded at admission (`f_adm = 0.50`), and the breaker fraction is separate and lower (`f_breaker = 0.25`).
- The breaker halts **entries only**, through a latch-held flag, with no veto-signature change.
- Unreadable slots are preserved byte-for-byte.
- The duplicate-order detector is specified.
- The cool-off is durable.
- "Neutral" is restated as "neutral except enumerated deltas".

## 0. Hard invariants (binding on every WP)

1. Nautilus Trader is immutable. Extend it only through the injected `StateStore`/latch seam and native config.
2. `allow_short` stays `False`.
3. Never weaken or delete a safety, settlement, contract, NO-SEND egress-firewall or import-pin test.
   - Widen exact sets only by named rows, keeping `==`.
   - Ordering pins are rewritten only to same-strength assertions on a renamed callee.
4. `exec/client.py` is byte-pinned. The floors never move: zero-fill 120 s, no-id 300 s, poll 5 s, backoff cap 300 s. There are **two re-pins** (WP-DR, WP4), each by the §4 procedure.
5. Operator caps (max daily budget, max per position = per order) are never assigned, defaulted or re-literalled. They may be read, read-only, through the existing readers.
6. `BREEZY_ORDERS_ENABLED`, permit minting and `fq-v1-halt-orders-off.conf` are untouched.
7. No mypy ceiling raise. No `type: ignore`, `Any` or `cast` in new code.
8. No `PREREG.json` edit.
9. M1-v3 window outcomes and tape for 2026-10-07..11-28 are never read. Every offline tool refuses such inputs.
10. Capability build only. Trading through K>1 needs the execution-design prereg (§9, D-PREREG).

## 1. Verified current-state facts (re-checked in code 2026-10-10)

**Store and latch**
- F1. `CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"`, `_SCHEMA_VERSION = 1` (`runtime/submit_intent.py:37-38`). `StateStore` is `get/set` only (:43-53), so keys cannot be enumerated.
- F2. `SubmitIntent.from_bytes` requires `v == 1` and ignores extra keys (:276-298). A v2 table is `SubmitIntentCorrupt` (latched) in v1 code. An extra key on a v1 record is tolerated.
- F3. `arm` refuses on OPEN or corrupt (:399-427). `retire` writes history first (:493-511). `is_latched` treats corrupt as latched (:386-397). `CorruptError` is a class attribute (:338), which is the layering pattern.
- F4. The resolver context is per-intent (`client.py:1094-1166`): `notional_usd`, `booking_id` (process-local), `wire_market_slug/price/outcome_side/action`, `baseline_venue_net/durable_net/ts_ns`. It is absent for a no-id window-only pass (:2691-2707).

**Submit path (`_submit_order`)**
- F5. Order of gates and effects:
  1. refusal gate at :6110 (denies all if `_trading_refusals` is non-empty);
  2. mapping check at :6189-6191;
  3. permit-missing at :6192;
  4. `is_latched` at :6204;
  5. `_submit_veto` at :6215-6218;
  6. body build at :6226-6237;
  7. **permit authorise and consume** at :6239-6254. `SessionNotionalExhausted` calls `_mark_budget_exhausted` at :6255-6257. That writes the durable day-stop marker (:5413-5438);
  8. `authorize_order_cost` at :6276. `DailyBudgetExhausted` also marks the day (:6282);
  9. `_intent_reconciled` at :6286;
  10. `arm` at :6291;
  11. `_note_ambiguous_open` at :6303;
  12. POST at :6327.
  - The pin is `test_execution_egress_firewall_guard.py:3066-3106`: `max(is_latched) < min(veto) < min(permit)`, with no `await` between.
- F6. `is_exit_order` is tag-derived (:6128-6149), computed before the :6204 gate.
- F7. `_refuse` dedupes on reason only and writes `instrument=""` (:6757-6761). The AMBIGUOUS refusal is appended at :6333 and :6580. Clears are guarded by `current_open() is None`: :3274-3282, **:3502-3514**, :4106-4115.
- F8. `_post_in_flight_intent_id` is a single `str | None` (:1838, :6325, :6349; reader :3747).
- F9. `base_slug_of` raises on an invalid slug or foreign venue (`symbology.py:298-314`). `leg_of` is at :289. YES and NO share a base slug.

**Resolver**
- F10. One intent per pass: `current_open()` at :2670. Poll at :588, backoff cap at :592, floors at :1596 and :1604, age gates at :3089 and :3752.
- F11. Singleton sites besides :2670:
  - identity guards at :3197, :3339 and :4063. Each is `current_open(); if None or id != mine: pop booking; return`;
  - refusal clears at :3274, :3502 and :4106.
- F12. The global `_resolver_consecutive_failures` is incremented at five sites (:2845, :2882, :2921, :3791, :3809) and reset on any mapped GET (:2934, :3815). It drives the 15 req/s-protecting sleep (:2613-2621), so it stays global.
- F13. **Ledger calls in the resolver on possibly prior-day bookings:** `true_up_booking` at :3231 (zero-fill, after `_retire`), :3408 (accept-fill, **before** `_retire` at :3429) and :4072 (no-id, after `_retire`). `_submit_order`'s own release and true-up sites use the same `now_ns` as the booking, so they cannot cross a day.
- F14. `_require_open_booking` raises `LiveTradingPermissionError` for any booking whose `day` differs from `utc_day_for_ns(now_ns)` (`operator_controls.py:438-447`), even before the ledger rolls (the roll is lazy, inside `authorize_order_cost`, :403-417).
  - **Consequence today (K=1):** an AMBIGUOUS order that crosses 00:00Z cannot be trued up. The zero-fill path skips the permit restore, `generate_order_canceled` and the LAST-statement AMBIGUOUS clear (:3274). The accept-fill path leaves the intent OPEN with a written fill record.
- F15. Boot order in `_connect`:
  1. the first resolver pass is awaited (:2174);
  2. the periodic resolver task is created in a `finally` (:2184-2196);
  3. `_reconcile_submit_intent` (:2312);
  4. `_seed_spend_from_durable_fills` (:2370, early `return` at :2422 when zero fills);
  5. `_spend_seeded = True` (:2223).
  - Awaits sit between 2 and 3. There is no `await` between 3 and 5.
  - Fill handlers (`record_fill` through `_retire`) are synchronous, so a fill is wholly before or wholly after the seed span.
- F16. `_RESOLVER_FILL_UNBUDGETED` (:732, :3458-3466) latches a global DURABLE refusal when `booking is None`, the order is not a SELL, and `_spend_seeded`.
- F17. `_resolver_contradiction_details` already exists (:1959, :3965, :4038), is surfaced at :2531, and is popped at `_retire` (:5924). `_resolver_leg_holding_qty(positions, slug, leg)` (:1531) returns the per-leg absolute magnitude, with 0 for the other leg and `None` when undetermined. The same-day branch at :3125 only logs and `continue`s. `_note_ambiguous_open` leaves `baseline = None` on a read failure (:5983-5990).

**Exposure and permit**
- F18. `DailySpendLedger.authorize_order_cost` is atomic under one lock (`operator_controls.py:348-427`). The roll resets `_spent_usd` and drops prior bookings (:403-417).
- F19. `seed_permit_budget_from_prior_spend` is once per `permit_id` and one-way (`safety.py:799-841`). It is called from `_seed_spend_from_durable_fills` (:2426) only when there is ≥1 fill. D3: a permit restore happens only with `booking is not None` (:3226-3250).
- F20. The submit throttle `output_drop=self._deny_new_order` (`risk/engine.pyx:140-150`) is a **drop**, upstream of `_submit_order`, so it wastes no permit slot. `max_order_submit_rate = "5/00:00:01"` (`node_config.py:698`). Free-balance denial is per order at `engine.pyx:949`, cumulative only within a list (:968). In-flight checks stay off (`node_config.py:876-901, 1036`).
- F21. `_submit_veto: Callable[[], str|None]` is consulted only at :6215. It is wired through `family_halt_submit_veto` (`composition.py:221`), `FqComposedVeto` (`app/trade.py:805`) and `node_config.py:816, 971-976`. `exit_wiring.py:278` separately refuses exits on `is_family_halted()`.
- F22. The supervisor marker is `supervisor_decode_marker.py:36-155` (`supervisor_admits_retirement_reason`), written at `trade_supervisor.py:2939`, read once at node boot (`node_config.py:1007`).

**Consumers of intent state (complete sweep of `src/`, `scripts/`)**
- The exec client: :2670, :3197, :3274, :3339, :3502, :4063, :4106 (`current_open`); :6204 and :6785 (`is_latched`); :1838, :3747, :6325, :6349 (in-flight id).
- `trial_day_latch.py:732, 753`; `continuous_strategy.py:1713, 1918, 2496, 2600, 2739`; `continuous_no_side.py:309`; `exit_wiring.py:183`.
- `settlement/exit_guard.py:163-192` (no live caller).
- `trade_supervisor.py:431-501` and their consumers :1298-1307, :1361-1377, :1476, :1866; marker write :2939.
- `clear_submit_intent_cli.py:125`.
- `prelaunch_intents.py:50-70`; `scripts/analysis/score_live_trials.py:190, 383-410, 531`; `scripts/ops/ambig_latch_phase_a_check.py`; `trade_cli.py:432, 538`.
- `forecast_quantile_ladder` uses its own `QuantileLadderLatch` (`decision.py:286`). It is not an intent-latch consumer and gains the benefit through the exec client. `fill_time_count.py` reads no singleton (WP0 re-verifies).

**Premise audit.** The constants are correct (the poll is at :588). "42% within 5 s" is confirmed. K=1, p_amb=0, p90 = 0.491 is reproduced (in-memory; WP0 commits it). "Drop" is the screen's policy and the code WAITs.

## 2. Native-Nautilus gap analysis

| Need | Native? | Verdict |
|---|---|---|
| Concurrent submission | Yes: one task per `SubmitOrder` (`live/execution_client.py:277-282`) | No gap. The serialisation is Breezy's venue-safety control. |
| Ambiguity resolution | In-flight check force-resolves FAILED | **Gap** (no client-order-id). Stays disabled. |
| Per-order notional and rate | `max_notional_per_order`; 5/s throttle that **drops** | Retained. The throttle drop is modelled (§7) and wastes no permit. |
| Free-balance denial | Per order | A native denial source. Modelled in both directions (§7). |
| Aggregate open exposure vs a daily budget | No | **Gap.** The ledger is the sole authority. |
| Per-slug durable exclusion with crash recovery | No | **Gap.** Built on the injected-latch seam. |

Options B (anonymous slots), C (queue) and D (second router) are rejected as in r1: B collapses into A, C cannot beat the floors, and D violates single-writer.

## 3. Design

### 3.1 Storage: one atomic table at `CURRENT_INTENT_KEY`
- Representation:
  - **v1 bytes whenever ≤1 slot is open, unconditionally** (this counts unreadable slots as open, see below). A 0→1 arm never writes v2.
  - v2 `{"v":2,"slots":{<key>:<intent record incl. slug>},"raw_slots":{<key>:<verbatim bytes>},"cooloff":{<slug>:<until_ns>}}` only while ≥2 slots are open and the v2 predicate holds.
- `SubmitIntent` gains a trailing optional `slug: str | None = None`. `to_bytes` emits `slug` only when set. A K=1 arm uses `slug=None`, so the bytes are identical to today.
- Every arm or retire is **one atomic `set`** of the whole table under the existing mutex and flock. History-first retire is unchanged. `reconcile_at_startup` copies history over matching slots.
- **Unreadable slots (ruling 6).** A slot that fails to decode is stored in `raw_slots` and rewritten **verbatim** by every later arm or retire. It counts as OPEN for the ≤1→v1 downgrade, so the table never downgrades while one exists. It **quarantines admission, which also denies exits.** A wholly undecodable table behaves as today.
  - The first unreadable slot logs ERROR once and surfaces through a client property for the alert watcher (WP5b).
  - Recovery is the CLI `--slot-key KEY --ack-unreadable-slot` (WP5a), which needs the existing evidence checks and an explicit ack.
- **Cool-off (ruling 9).** `cooloff` is durable in the table. On a v2→v1 downgrade or a drain to a RETIRED record, it is carried as an extra `cooloff` key on the v1 record (v1 readers ignore it). Slugs retired at boot (reconcile or the first pass) get a synthetic cool-off from boot time.
  - It is measured from the retire time (`retired_ns`), not from creation.
  - It applies to entries after zero-fill, no-fill **and fill** retires, and never to exits.
  - K=1 mode writes no cool-off, so the bytes stay identical.
- Legacy adoption:
  - A slug-less OPEN record takes the slug from `AmbiguousResolverContext.wire_market_slug`.
  - A missing context uses key `"?:<intent_id>"`, which **quarantines**.

### 3.2 Ordering, v2 predicate and the neutrality statement
- WP5a (supervisor decode, marker capability, CLI tolerance, analysis readers) deploys **before any v2 write**. The marker (`supervisor_decode_marker.py`) gains a trailing-optional `slot_schema_versions`, with `_SCHEMA_VERSION` unchanged and old markers decoding as empty. `supervisor_admits_slot_schema(store_path, 2)` uses the live-pid and start-ticks check.
- **Predicate** `v2_admitted()` is evaluated on every would-be 1→2 transition. It is **exception-contained and returns False on any error** (marker stat, `/proc`).
  - It is evaluated **inside `admission_refusal` before any spend** (§3.3), and again inside `arm_slot` as the arbiter. A False result is a WAIT.
- **K_eff := the configured K constant.** It is never derived from the predicate. The predicate only gates the 1→2 transition.
- **Neutrality statement (restated).** With K=1 the system is behaviourally identical to today **except the enumerated deltas** below. **WP-DR and WP4 are non-neutral merges**; WP0-WP3 are inert and WP5a/5b/6 are neutral at K=1.

| Delta | Effect at K=1 | Test |
|---|---|---|
| D0 (WP-DR) | A midnight-crossing AMBIGUOUS retire now completes: the cancel, the refusal clear and the permit restore run, and an accept-fill retires. | `test_*_after_midnight_*` (§5) |
| D1 (WP4) | A boot-inherited cross-process fill settles into the ledger instead of latching global `_RESOLVER_FILL_UNBUDGETED`. | `test_boot_fill_not_flagged_fill_unbudgeted` |
| D2 (WP4) | Open exposure that survives a day roll or a restart keeps counting against headroom instead of being dropped. | `test_booking_survives_day_roll_with_open_slot` |
| D3 (WP4) | `_refuse` dedupes on `(reason, instrument)`. | identical outputs at `instrument=""` |
| D4 (WP4) | `_post_in_flight_intent_ids` is a frozenset (one element). | existing in-flight tests |

All other behaviour at K=1 is covered by `test_k1_store_write_sequence_matches_golden_v1` (byte-identical writes) and `test_k1_differential_replay_identical_outputs`.

### 3.3 Admission before spend (rulings 2, 7)
Order inside `_submit_order` (all synchronous, no `await`; the pin chain `latch < veto < permit` is kept, with the latch callee renamed):
1. **:6110 gate:** deny only on **unscoped** refusals (`instrument == ""`). It makes no slug call, so nothing can raise there.
2. mapping check :6190, `permit_is_missing` :6192 (unchanged).
3. **Admission gate (replaces `is_latched` at :6204):**
   - Derive `slug = base_slug_of(order.instrument_id)` inside `try/except Exception → self._deny(...)` (`test_unmappable_instrument_denied_not_raised`).
   - Deny if a **scoped refusal** matches the slug.
   - Call `self._latch.admission_refusal(slug, is_exit_order)`. It evaluates, in order:
     - quarantine (denies exits too);
     - the v2 predicate on a would-be 1→2 transition;
     - the durable **entry-halt** flag (entries only);
     - same slug open;
     - K-full (entries);
     - cool-off (entries).
   - It returns a reason string or `None`.
4. **Read-only ledger pre-check** `self._ledger.exposure_admission_refusal(price_usd, quantity, now_ns)`:
   - It evaluates only the new exposure conditions: any unknown-notional key, `spent + uncharged + cost > budget`, and the AMBIGUOUS bound `ambiguous_total > 0 and ambiguous_total + cost > f_adm × budget`.
   - It takes the ledger lock but mutates nothing.
   - It does not evaluate the operator position cap or the plain `spent + cost > budget` check, which stay in-lock, so K=1 behaviour is unchanged.
5. `_submit_veto` (:6215), the body build, and the `if body["marketSlug"] != slug: return self._deny(...)` comparison (before the permit spend).
6. Permit spend, `authorize_order_cost` (the in-lock checks remain **the authority**), `_intent_reconciled`, `arm_slot` (which re-runs `admit` as the arbiter), `register_open_exposure`, `_note_ambiguous_open`, POST.

Required tests, each asserting that the permit remaining count and notional are untouched, no `_mark_budget_exhausted` marker is written, and no booking is made:
- `test_k_full_denial_before_permit_spend`;
- `test_same_slug_denial_before_permit_spend`;
- `test_v2_predicate_false_is_wait_before_permit_spend`;
- `test_v2_predicate_raises_is_wait_before_permit_spend`;
- `test_exposure_precheck_denial_before_permit_spend_no_day_stop_marker`;
- `test_entry_halt_denies_entries_before_permit_spend`.

`admit(table_view, slug, is_exit, k, entry_halted, now_ns)` is pure (domain):
- Quarantine denies all, including exits.
- **If `k == 1`:** deny iff any slot is open (≡ `is_latched`), for entries and exits alike.
- **If `k > 1`:** deny same slug; entries are denied when non-exit open slots ≥ k, or in cool-off, or entry-halted; exits are K-exempt and cool-off-exempt but slug-exclusive.
- The property test quantifies over `is_exit` and over arbitrary tables, including unreadable ones.

### 3.4 Singleton fields and sites (rulings 4, 7)
- **H0** `_post_in_flight_intent_ids: frozenset[str]` (whole-value reassignment; the reader is a membership test).
- **H5 resolver selection (:2670).** `current = self._latch.next_open_for_resolution(self._resolver_intent_failures, self._resolver_intent_served)`.
  - It passes two attributes (dicts), with no builtin call inside the coroutine.
  - It sorts by `(per-intent failures asc, last served asc, created asc)` and returns a `SubmitIntent` that carries `.slug`.
  - Unreadable slots are skipped (they are already in `raw_slots`) and logged once per key.
  - The per-intent counters mirror the five increment and two reset sites (F12). The global counter still drives the sleep.
- **H7 by-id guards (:3197, :3339, :4063)** use `self._latch.is_open_intent(intent_id)`.
- **Slug plumbing (ruling 7).** The three resolver bodies get `slug=current.slug or ""` from the `SubmitIntent` record field, **not** from the context. This covers the no-id window-only path where the context is None.
- **H8 refusal clears (:3274, :3502, :4106).**
  - Remove the AMBIGUOUS refusals scoped to `slug`, then also the unscoped AMBIGUOUS refusal **if** `self._latch.open_slot_count() == 0`. At K=1 this is exactly the old `current_open() is None` condition.
- **Refusal scope (rulings 5, MEDIUM-2).**
  - At each AMBIGUOUS append (:6333, :6580): `self._refuse(AMBIGUOUS_REASON, instrument=slug if self._latch.open_slot_count() > 1 else "")`.
  - The scope is decided from the table state at append time and stored on the `ClassifiedRefusal`, never from the predicate.
  - Scoped AMBIGUOUS is pinned `RefusalClass.DURABLE`.
  - `_refuse` dedupes on `(reason, instrument)`. It is a keyword-only addition and pin-neutral (`test_exec_refusal_health_surface.py:182-291`).
- **Tests.**
  - A ambiguous, B ambiguous, A retires: B's refusal survives.
  - `_map_position` success on A never clears A's AMBIGUOUS.
  - A K=1 unscoped refusal clears only when no slot is open.
  - A scoped refusal is cleared at its slot's retire.
  - `test_unscoped_refusal_raised_before_second_slot_clears_when_none_open`.
- `resume_if_refusals_cleared` keeps `is_latched()` (any open or quarantined slot ⇒ latched).

### 3.5 Exposure accounting (rulings 2, 3, 4, 10)
Additive `DailySpendLedger` methods in `operator_controls.py`. The existing methods and the "previous UTC day" refusals are **unchanged**, and no tests of them are touched.
- `register_open_exposure(key, notional_usd | None, charged, day, seeded_partial_usd, now_ns)`. Idempotent. `None` adds the key to a **per-key** `_unknown_keys` set. Entries are refused while that set is non-empty, and retiring a key removes only that key.
- `mark_ambiguous(key)`. Called at the two AMBIGUOUS sites (:6333, :6580) and for every boot-registered intent (fail-closed).
- `settle_open_exposure(key, realized_usd | None, now_ns) -> bool`.
  - Idempotent, and independent of the booking-day rule.
  - If the entry is uncharged, was created today and had a fill, it adds `max(realized − seeded_partial_usd, 0)` to `_spent_usd`. Otherwise it only removes.
- `has_open_exposure`, `uncharged_open_total`, `ambiguous_open_total`, `unknown_key_count`, and the pre-check `exposure_admission_refusal`.
- **Lazy-roll window (ruling 10).** `register`, `settle`, the pre-check and the totals call an internal `_roll_locked(now_ns)` first. It is the same pruning code as :403-417, but surviving **open** entries convert to uncharged instead of being dropped.
  - A settle between 00:00Z and the first new-day authorize therefore sees a consistent state.
  - Test: `test_settle_after_roll_before_next_authorize`.
- **Invariants.**
  - At every `authorize_order_cost`: `spent_today + uncharged_open + cost ≤ budget`.
  - The AMBIGUOUS fraction bound is `ambiguous_open_total + cost ≤ f_adm × budget`.
  - `f_adm = 0.50` and `f_breaker = 0.25` are Breezy-owned `Final` constants in `node_config.py` and are injected. `None` means the bound is off.
  - The bound raises `OpenExposureBoundExceeded(LiveTradingPermissionError)`, **not** `DailyBudgetExhausted`, so it never marks a day stop.
  - The budget is read via the existing reader and never assigned.
- **Boot (H6, ruling 3).** A new step runs inside the no-await span between `_seed_spend_from_durable_fills` and `_spend_seeded = True`.
  - It registers every still-OPEN intent as `charged=False` and marks it ambiguous, using the context's `notional_usd − seeded_partial` (`None` if there is no context).
  - Permit seeding is **unchanged**: durable fills only, as today. Open exposure is enforced by the ledger alone. A boot-registered intent has no booking, so D3 means no permit restore, and the permit is never debited for it.
  - Registering a partial's notional net of the seeded partial avoids the double count.
- **Retire (H9).** Each fill handler captures `registered = ledger.has_open_exposure(id)` at the top of the synchronous body. It settles with the realized cost **before** `_retire`.
  - The UNBUDGETED condition gains `and not registered`.
  - `_retire` calls `settle_open_exposure(id, None)` idempotently, so every zero-fill, no-fill and reject path releases headroom.
- Boot over budget: `authorize` and the pre-check deny. `_intent_reconciled` stays True, the resolver is independent, and the denial names the reason ("open exposure holds headroom") so it is a logged WAIT and not a silent deny.
- The reasoning about the boot interleave (F15) is: a fill handler is wholly before or wholly after the seed span. A fill before it is counted by the seed and its intent is not registered. A fill after it settles a registered intent. Test: `test_boot_interleave_retire_before_and_after_registration`.
- **Exactly-once property** (hypothesis): for any interleaving of seed, register, partial, full fill, zero-fill, day roll and settle, each fill's cost counts once in `spent_today`, open exposure is never dropped before settle, and partials are modelled (net of the seeded part).

### 3.6 Breaker (rulings 4, 8, 11)
Frozen numbers for the first K>1 deployment (restated in D-PREREG):
- **Stuck** = an AMBIGUOUS open intent with age > `floor + 600 s` (with-id 720 s; no-id 900 s), or any intent with a recorded CONTRADICTION.
- **Trip** at ≥ 2 stuck, **or** `ambiguous_open_total > f_breaker × budget` with `f_breaker = 0.25` (below `f_adm = 0.50`, so this trigger is live, with a non-vacuous test), **or** a DUPLICATE_SUSPECT.
- **CONTRADICTION is sticky.** The client keeps a monotonic `contradiction_events_total`. The watcher latches the durable entry-halt on any increase, and the latch survives the `_retire` pop. It clears only through an operator reset (CLI).
- **Duplicate detector (inside the resolver, recorded via `_resolver_contradiction_details`, kind `DUPLICATE_SUSPECT`):**
  - On each pass that reads eof-complete positions, for an intent with a baseline: `venue_leg_qty = _resolver_leg_holding_qty(positions, slug, leg)`, and the baseline leg magnitude is derived from `baseline_venue_net` with the NO-as-short-YES sign (`yes: max(net,0)`, `no: max(−net,0)`).
  - Suspect iff `venue_leg_qty − baseline_leg_qty > qty_est`, where `qty_est = notional_usd / Decimal(wire_price)`.
  - A `None` baseline or `None` leg qty is **not evaluable** (it resets the counter and never trips or crashes).
  - A lag guard requires age ≥ the 120 s floor and **confirmation on a second consecutive pass**. The per-intent counter is a dict with whole-value reassignment.
  - The cool-off after fill retires covers positions-feed lag after a prior same-slug fill. Manual trades still trip it (fail-closed) and are cleared by the operator.
- **Effect: entries only (ruling 11, decision).**
  - The watcher writes the durable `exec/polymarket_us/intent/entry_halt` key through new latch methods. `admission_refusal` reads it (one `get`) and denies entries only.
  - **Why not the family-halt veto.**
    - The veto has no entry/exit distinction. The breaker trips exactly when held positions may need selling, and halting exits would worsen a doubled position.
    - Changing `_submit_veto`'s signature would touch `family_halt_submit_veto`, `FqComposedVeto`, `app/trade.py:805`, `node_config.py:816, 971-976` and their tests (F21).
    - `exit_wiring.py:278` (`is_family_halted()`) is untouched because the breaker does not use the family-halt key.
  - **Pins named: none changes.** New allowlist row: `self._latch.admission_refusal` (already listed). The CLI gains `--reset-entry-halt`.
  - The watcher alerts the operator listing held positions, from the resolver-refreshed startup-position evidence (R-9a), and any stuck slot on a slug that has a held position (a stuck entry blocks that slug's exit, as it does today).
  - A new `AlertDetail` member needs the exhaustive-enum pin checked in WP5b.
- **The breaker never blocks the resolver.** The resolver never reads `entry_halt` or the veto. Test: a tripped breaker still retires a pending slot.

### 3.7 Exits and quarantine
- Exits are K-exempt only when K>1, and are always slug-exclusive. At K=1 they behave exactly as today (denied while anything is open).
- Quarantine, including an unreadable slot, denies exits too. This matches today's `is_latched`.
- `exit_guard.assert_settlement_close_permitted` gains an optional keyword `refusal_scopes`. With it, only unscoped refusals or the close's own base slug refuse. The existing signature and tests are untouched, and it has no live caller yet.
- The client exposes `trading_refusal_scopes` beside `trading_refusals`.
- `exit_wiring.check_exit_intent_for_ambiguous_send` (:183) uses a new `TrialDayLatch.open_submit_intents()` and matches by fingerprint, so a stale ambiguous exit in any slot halts the family. The `is_exit` flag is the tag-derived `is_exit_order` (F6).

### 3.8 Venue and subscription constraints
- Resolver GET load is unchanged (one intent per pass), well under 15 req/s. The added latency is ≤ (K−1)×5 s.
- No new WS subscriptions (the cap of 10 is shared). Fill detection stays GET-based. `subscribe_trades` stays off (test).
- The throttle comment at `node_config.py:681-698` is rewritten ("can never bind" is false at K>1). The value is not raised here.

## 4. Re-pin procedure (two re-pins)
Edit **only** `_EXEC_CLIENT_SHA256` at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`, after `python-reviewer` and `prediction-market-reviewer` approve the diff, and append a comment `# re-pinned <date>: <WP>, reviewer-approved`. `test_autonomy_envelope.py:901-916` reads it by AST from that single home. Never update the pin first, and never in a separate "make it green" commit.

## 5. Work packages (TDD order)

**Order:** WP-DR → WP0 → WP1 → WP2 → WP3 → WP5a → [supervisor restart, marker verified] → WP4 → WP5b → WP6 → WP7.
- WP-DR is independent of EXEC-PAR and mergeable first.
- WP0-WP3 are inert (no caller).
- Common gate: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -m pytest --basetemp=~/.cache/...`; `lint-imports` from the tree's cwd ("N kept, 0 broken"); `ruff`; `mypy` (no ceiling change); the full gate `scripts/ci/run_tests_no_egress.sh` after every merge, reading the exit code before any push.
- Every focused list includes:
  - the firewall guard, the exec-client tests, the latch tests, the ambiguous-resolver tests, and the AC6b cross-process budget test;
  - the operator-reserved and assignment-scan tests, the refusal-health-surface test, the pin tests, `tests/contract/test_live_fill_scoring_chain_contract.py`, and all `test_autonomy_*`.
- Briefs state the exact interpreter, no `uv run`/`pip`/`git stash`, own scratchpad, format only your own files, and worktree `PYTHONPATH` first.

### WP-DR: day-roll settle (standalone; K-neutral except D0; client.py re-pin #1)
- Scope: `client.py:3231, 3408, 4072` only.
  - At each site, **skip the ledger call when `booking.day != utc_day_for_ns(now_ns)`** and log it at INFO.
  - Wrap the ledger call in `except LiveTradingPermissionError` that logs ERROR and continues, so the cancel, the permit restore and the LAST-statement AMBIGUOUS clear always run.
  - The permit restore is session-scoped and keeps running.
  - It adds no `self._refuse` call (the 25-site producer pin) and no new allowlist rows (the helper bodies are not scanned coroutines).
  - It does not touch the ledger.
- RED tests (in `test_polymarket_us_exec_client.py`, using `ambig_latch_rig` with an injected clock, extended if it lacks clock control):
  - `test_zero_fill_retire_after_midnight_cancels_clears_refusal_and_restores_permit` (POST 23:59Z, retire 00:03Z);
  - `test_accept_fill_retire_after_midnight_retires_once_no_unbudgeted_no_stuck_refusal`;
  - `test_no_id_no_fill_after_midnight_clears_refusal`;
  - `test_same_day_paths_unchanged` (golden);
  - `test_ledger_raise_does_not_skip_cancel_or_refusal_clear`;
  - `test_fill_timestamped_before_midnight_resolved_after_is_not_counted_in_new_day`.
- Gates: the common gate plus the firewall guard, then re-pin #1.

### WP0: viability and premise verification (no production code)
Method and stop rule are in §7. RED (`tests/unit/test_exec_parallel_dhat.py`):
- `test_refuses_any_input_on_or_after_2026_10_07`;
- `test_k1_reproduces_p0_p90_0_491`;
- `test_simulation_uses_production_admit`;
- `test_throttle_5_per_s_drop_counted`;
- `test_free_balance_arm_a_fill_time` and `test_free_balance_arm_b_ambiguous_holds`;
- `test_stop_rule_uses_worse_free_balance_arm`;
- `test_ambiguous_fraction_bound_drop_counted_with_cb_sweep`;
- `test_cluster_bootstrap_ci_upper_bound_stop`;
- `test_first_5s_budget_fraction_arm`;
- `test_stuck_slot_reduces_effective_k`;
- `test_yes_and_no_share_one_slot`;
- `test_hold_constants_match_exec_client_source_ast`;
- `test_caps_read_only_ratio_bucket_only_never_printed_or_assigned`.
- Recorded verifications (file:line):
  - the cash account's `free` update timing and the AMBIGUOUS lock behaviour (`risk/engine.pyx`, accounts);
  - `subscribe_trades` is off;
  - `fill_time_count.py` reads no singleton;
  - `base_slug_of(order.instrument_id)` equals the wire slug on sampled YES and NO ids.

### WP1: pure admission model + Protocol (domain)
- RED:
  - `test_admit_k1_equals_is_latched_for_any_table_entries_and_exits` (the property over `is_exit`, unreadable slots and quarantine);
  - `test_admit_denies_same_slug`;
  - `test_admit_k_full_entries_only_when_k_gt_1`;
  - `test_exits_k_exempt_and_cooloff_exempt_only_when_k_gt_1`;
  - `test_quarantine_denies_exits`;
  - `test_entry_halt_denies_entries_not_exits`;
  - `test_cooloff_applies_after_fill_retire`;
  - `test_admit_pure_deterministic`.
- A `typing.Protocol` types the injected latch only if `mypy` accepts it without `Any`.

### WP2: slot table (runtime; inert)
- RED:
  - `test_k1_store_write_sequence_matches_golden_v1`;
  - `test_slug_key_only_when_set`;
  - `test_v1_reader_ignores_slug_and_cooloff_keys`;
  - `test_v2_table_is_corrupt_in_v1_code`;
  - `test_arm_and_retire_are_one_atomic_set`;
  - `test_crash_between_history_and_table_set_recoverable`;
  - `test_last_retire_writes_valid_v1_retired_with_cooloff`;
  - `test_retire_of_healthy_slot_preserves_unreadable_slot_bytes`;
  - `test_last_healthy_retire_does_not_downgrade_over_unreadable_slot`;
  - `test_unreadable_slot_quarantines_but_healthy_slot_resolvable`;
  - `test_legacy_open_adopted_by_context_slug`;
  - `test_legacy_open_without_context_quarantines`;
  - `test_boot_retired_slug_gets_synthetic_cooloff`;
  - `test_v2_predicate_false_or_raising_refuses_one_to_two`;
  - `test_entry_halt_key_set_read_reset`;
  - `test_concurrent_arm_slot_one_winner_per_slug`;
  - `test_is_open_intent_and_open_slot_count`.

### WP3: ledger open-exposure API (inert)
- RED (`test_daily_spend_ledger_open_exposure.py`; the existing day-rule tests are untouched):
  - the concurrent no-overshoot property including AMBIGUOUS;
  - `test_open_exposure_survives_day_roll_as_uncharged`;
  - `test_settle_after_roll_before_next_authorize`;
  - `test_settle_zero_fill_releases_headroom`;
  - `test_settle_uncharged_fill_adds_realized_minus_seeded_partial_once`;
  - `test_exactly_once_over_all_interleavings_incl_partials` (property);
  - `test_unknown_notional_is_per_key_and_clears_only_its_own_key`;
  - `test_precheck_is_read_only`;
  - `test_ambiguous_bound_only_counts_marked_ambiguous`;
  - `test_ambiguous_bound_raises_bound_exceeded_not_daily_budget_exhausted`;
  - `test_no_bound_when_nothing_ambiguous`;
  - `test_prior_day_booking_still_not_releasable` (existing semantics);
  - `test_operator_caps_never_assigned` (AST).

### WP5a: supervisor, marker, CLI, analysis (deploys BEFORE WP4)
- Files: `supervisor_decode_marker.py`, `trade_supervisor.py` (probes and consumers, marker write), `clear_submit_intent_cli.py`, `prelaunch_intents.py`, `score_live_trials.py`, `ambig_latch_phase_a_check.py`.
- RED:
  - `test_marker_slot_schema_field_and_old_marker_decodes_empty`;
  - `test_admits_slot_schema_requires_live_matching_pid`;
  - `test_probe_open_true_for_v2_with_open_slot`;
  - `test_probe_resolvable_false_for_unreadable_or_contextless_slot`;
  - `test_clear_cli_never_raises_uncaught_on_v2`;
  - `test_clear_cli_lists_slots_and_clears_by_intent_id`;
  - `test_clear_cli_unreadable_slot_requires_slot_key_and_ack`;
  - `test_clear_cli_refuses_erasing_table_over_open_slots`;
  - `test_clear_cli_reset_entry_halt`;
  - `test_score_live_trials_v2_open_not_absent`;
  - `test_prelaunch_observation_v2_open_is_ambiguous`;
  - `test_rollback_drill_after_drain_old_reader_sees_valid_v1_retired`.
- Deploy: merge, restart the supervisor (code loads once; window 01:00-16:40Z; the node survives), and verify the marker field.

### WP4: exec client (byte-pinned; NON-NEUTRAL: D1-D4; re-pin #2)
- Hunks: H0, §3.3 gates (:6110 unscoped only; the admission gate; the pre-check; the body-slug comparison), `arm_slot`, `register_open_exposure` and `mark_ambiguous`, H5, slug plumbing, H6, H7, H8, H9, `_refuse` scope and dedupe, the per-intent failure mirrors, and the `trading_refusal_scopes`, `contradiction_events_total` and unreadable-slot properties.
- The duplicate detector goes in the resolver and records via `_resolver_contradiction_details`.
- **Named allowlist rows (keep `==`; each checked against the `read/send/post/request` banned-word scan).**
  - Order coroutine: `base_slug_of`; `self._latch.admission_refusal` (replacing `is_latched`; `is_latched` stays for `resume_if_refusals_cleared`); `self._latch.arm_slot` (replacing `arm`); `self._latch.open_slot_count`; `self._ledger.exposure_admission_refusal`; `self._ledger.register_open_exposure`; `self._ledger.mark_ambiguous`.
  - Resolver coroutine: `self._latch.next_open_for_resolution`; `self._latch.is_open_intent`; `self._latch.open_slot_count`; `self._ledger.has_open_exposure`; `self._ledger.settle_open_exposure`.
  - The ordering pin is rewritten same-strength for the renamed callee. A new AST pin asserts no `await` between `authorize_order_cost` and `register_open_exposure`.
- RED (extend `test_polymarket_us_exec_client.py`):
  - the §3.3 pre-spend tests;
  - `test_two_distinct_slugs_both_post_concurrently`;
  - `test_exit_other_slug_passes_when_k_gt_1_but_not_at_k1`;
  - `test_k1_unscoped_refusal_denies_all_as_today`;
  - the §3.4 refusal tests;
  - `test_slot_b_resolves_while_a_open`;
  - `test_resolver_round_robin_skipping_backoff_slot`;
  - `test_global_backoff_still_drives_sleep`;
  - `test_one_503_slot_does_not_starve_others`;
  - `test_in_flight_frozenset_resolver_skips_first_post_after_second_completes`;
  - `test_resolver_floors_unchanged_120_300_5_300`;
  - `test_resolver_corrupt_slot_skipped_others_resolve`;
  - `test_slug_from_record_used_in_no_id_window_only_clear`;
  - `test_boot_registers_uncharged_with_zero_fills`;
  - `test_boot_context_less_unknown_key_denies_entries_no_crash`;
  - `test_boot_over_budget_resolver_still_retires_and_denial_is_logged_wait`;
  - `test_boot_permit_untouched_by_open_intent_registration`;
  - `test_boot_zero_fill_retire_no_permit_restore_d3`;
  - `test_boot_fill_not_flagged_fill_unbudgeted`;
  - `test_boot_partial_not_double_counted`;
  - `test_boot_interleave_retire_before_and_after_registration`;
  - `test_booking_survives_day_roll_with_open_slot`;
  - `test_body_slug_mismatch_denied`;
  - `test_duplicate_detector_leg_magnitude_no_sign`;
  - `test_duplicate_detector_none_baseline_not_evaluable`;
  - `test_duplicate_detector_needs_second_pass_and_age_floor`;
  - `test_duplicate_detector_records_contradiction_not_just_log`;
  - `test_k1_differential_replay_identical_outputs`.

### WP5b: node config, breaker, telemetry (neutral at K=1)
- Files: `node_config.py`, `trade_cli.py`, `app/trade.py`.
- Contents:
  - the constants `EXEC_PAR_MAX_CONCURRENT_INTENTS = 1`, `OPEN_EXPOSURE_BOUND_FRACTION = Decimal("0.50")` and `BREAKER_OPEN_AMBIGUOUS_FRACTION = Decimal("0.25")`, all `Final` and not env-derived;
  - the marker → `v2_admitted` wiring;
  - the breaker watcher (reading the client properties) with its alerts: unreadable slot, trip, held-position list, stuck slot on a held slug;
  - the throttle comment;
  - telemetry-only digest fields (per-station-day open exposure; orders and notional per 5 s window).
- RED:
  - `test_constants_are_final_and_not_env_derived`;
  - `test_k_forced_1_when_marker_absent`;
  - `test_subscribe_trades_off_and_inflight_interval_zero`;
  - `test_breaker_trips_at_two_stuck`;
  - `test_breaker_notional_trigger_fires_at_f_breaker_below_f_adm` (non-vacuous);
  - `test_contradiction_latches_entry_halt_sticky_until_operator_reset`;
  - `test_duplicate_suspect_trips`;
  - `test_entry_halt_allows_exits_and_resolver_still_retires`;
  - `test_breaker_does_not_use_family_halt_or_veto_signature`;
  - `test_first_unreadable_slot_alerts_once`;
  - `test_alert_detail_enum_pin_green`.

### WP6: strategy and exit readers (neutral at K=1)
- Files: `trial_day_latch.py` (add `admission_would_refuse(slug, is_exit)`, `open_submit_intents()`), `continuous_strategy.py:1713, 1918, 2496, 2600`, `continuous_no_side.py:309`, `exit_wiring.py:183`, `exit_guard.py`.
- The pre-filters use the **same read-only admission predicate** as the exec gate, including quarantine, K-full, cool-off and entry-halt. This keeps Resolution B (no hunt → WAIT-deny → clear-inflight loop).
- RED:
  - `test_prefilter_equals_exec_admission_for_all_tables` (property);
  - `test_hunt_proceeds_on_other_slug_when_not_k_full`;
  - `test_rearm_release_is_per_slug`;
  - `test_open_intent_wait_observation_names_slug`;
  - `test_exit_wiring_halts_on_stale_exit_in_any_slot`;
  - `test_exit_guard_scoped_refusal_permits_other_slug_close`;
  - `test_exit_guard_unscoped_refusal_still_refuses`.

### WP7: failure injection, replay, soak (no live)
- RED:
  - `test_crash_at_every_line_arm_slot_to_post_no_double_order`;
  - `test_post_timeout_leaves_slot_and_slug_denied`;
  - `test_restart_with_three_open_slots_rebooks_and_resolves_each`;
  - `test_late_fill_after_zero_fill_retire_then_rearm_same_slug_denied_by_cooloff`;
  - `test_late_fill_after_fill_retire_cooloff`;
  - `test_exit_and_entry_same_slug_serialised_both_orders`;
  - `test_supervisor_rolled_back_mid_run_blocks_v2_write`;
  - `test_drain_then_rollback_drill`;
  - `test_replay_bit_for_bit_fixed_clock`.
- Exit: a K-proposal blocked on D-PREREG's frozen SHA and on WP0 passing.

## 6. Gates per WP
Each WP runs the common gate plus its named files. WP-DR and WP4 also run the whole firewall suite, the exec import pin, the citation map and the refusal-producer pin, and the full gate after the re-pin. WP5a's supervisor restart is verified from the marker field and the supervisor log, not `pgrep`.

## 7. Viability (build gate only)

**Method (pre-2026-10-07 data only).**
- Re-extract candidates with instrument ids using the existing pre-window extractor bounds (`stage_minus1_triage_dmix.py` `FIRST/LAST`); hold inputs come from `WP0_c0_pre1007_orders.tsv`. The cands file keeps only `(ts, station)`.
- The model runs 1,000 seeded draws per day. Admission uses the **production `admit`** (domain import). p_amb ∈ {0, 0.05, 0.10, 0.18, 0.33}, with stuck-slot (K−1) and no-id arms.
- Arms, all counted in d̂ as drops:
  - the 5/s throttle (sliding 1 s window);
  - **free-balance, both directions:** arm A reduces `free` at accepted-fill time only; arm B also holds buying power for an AMBIGUOUS order for its whole stuck lifetime. **The stop rule uses the worse arm.** F ∈ {2c, 4c, budget proxy};
  - the **AMBIGUOUS fraction bound** `f_adm = 0.50`, over a **c/B sweep {0.05, 0.10, 0.25, 0.50}** as a stop-rule dimension, and `f_breaker = 0.25` reported as a halt rate.
- The live caps are a read-only input only: an optional flag reads them through the existing readers and prints a **ratio bucket only**, never a value, and never assigns anything. If it is unavailable, the worst bucket in the sweep is used.
- Statistic: day-clustered bootstrap (2,000 resamples) of the day-level p90 and p50. **STOP iff the 95% upper bound of d̂_p90 > 0.30** at the Wilson-upper p_amb = 0.33 with one stuck slot, the worse free-balance arm, the throttle and the bound, at the actual c/B bucket (or the worst bucket if unreadable).
- Extra arm: the share of the budget deployed in the first 5 s, over the c/B sweep (telemetry for D-PREREG).
- K ∈ {3..8} is reported. The smallest K whose CI upper bound ≤ 0.30 is the K candidate. K is frozen in D-PREREG before the 12-07 read.

**Preliminary point estimates (in-memory, no throttle, free-balance, bound or stuck arm yet; not binding):**

| K | p_amb = 0 p50/p90 | 0.18 p50/p90 | 0.33 p50/p90 |
|---|---|---|---|
| 1 (today) | 0.273 / **0.491** | 0.549 / 0.643 | 0.686 / 0.736 |
| 3 | 0.0 / 0.244 | 0.094 / 0.269 | 0.227 / 0.329 |
| 4 | 0.0 / 0.156 | 0.018 / 0.172 | 0.084 / 0.203 |
| 6 | 0.0 / 0.0 | 0.0 / 0.012 | 0.005 / 0.027 |

K=6 is not to be relied on until the CI and every arm have run. Caveats: the hold inputs contain no NO ≥ 0.90 order and every AMBIGUOUS order was YES; n_amb = 7; candidates are first-row, take-all and tie-free. This is a **build gate only**, with no claim about NO ≥ 0.90 ambiguity or hold times.

## 8. Risks, kill criteria, rollback

| # | Risk | Sev. | Containment |
|---|---|---|---|
| R1 | Same-slug temporal bleed | High | Durable cool-off after zero-fill, no-fill and fill retires (entries only); the two-pass duplicate detector |
| R2 | Stuck slots eat K | High | Breaker (≥2 stuck, `f_breaker`, sticky CONTRADICTION); the `f_adm` admission backstop |
| R3 | Exposure across restart or day roll | High | WP-DR; the §3.5 registry; per-key unknown-notional fail-closed |
| R4 | Scoped refusals mis-cleared | High | Scope decided at append time; clear rules in both directions; K=1 stays unscoped |
| R5 | Pin drift | Med | Named rows; same-strength ordering rewrite; banned-word scan |
| R6 | v2 bytes read by a stale supervisor | High | WP5a first; the predicate before spend and in the arbiter; v1 whenever ≤1 open |
| R7 | Lost unreadable slot | High | Raw bytes preserved; never downgrade over one; the CLI ack path; first-occurrence alert |
| R8 | Native drops lose burst candidates | Med | Counted in d̂; the throttle value is not raised |
| R9 | Concentration into one correlated 5 s repricing | Med | Telemetry and the first-5 s arm; D-PREREG stop criteria; no new cap here |
| R10 | Population mismatch in the hold inputs | Med | Build gate only; the NO ≥ 0.90 hold-time ramp gate in D-PREREG |
| R11 | A stuck entry blocks the exit of a held slug | Med | Equal to today; the alert on a stuck slot with a held position |

**Kill criteria.**
- WP0 stop rule (§7).
- Any duplicate-order evidence in WP7.
- A red full gate after a re-pin.
- An allowlist change that cannot be a named row.
- Any need to change `_submit_veto`'s signature.

**Rollback.**
1. **WP-DR and WP4 are non-neutral merges** (deltas D0-D4); their rollback is a code revert with its pin in the same commit, after the stated deltas are acknowledged.
2. Other WPs are neutral at K=1. K stays 1 until the gated activation.
3. After K>1: trip or halt entries, drain to ≤1 open (the table rewrites as v1), set K=1, revert code with its pin.
4. A rolled-back supervisor cannot admit v2, so the node refuses 1→2 transitions (the predicate before spend). If a v2 table is open, the old supervisor refuses launch and the CLI clears by intent id or slot key.
5. The halt drop-in and `BREEZY_ORDERS_ENABLED` are never touched.

## 9. D-PREREG: execution-design prereg (named deliverable, not written here)
Capability needs no prereg (no screen claim; `PREREG.json` untouched). **Trading a 12-07 WINNER through K>1 does**, because the screen scored drops as losses and parallel execution fills them. D-PREREG is owned by the coordinator, frozen before the 2026-12-07 read, and never edited afterwards. It must contain:
- The **complete K schedule** and promotion criteria (for example K=1 → 2 → ... with the fills and days required per stage and the hold conditions), with no K chosen post hoc.
- `f_adm = 0.50`, `f_breaker = 0.25` (separate values), the cool-off (120 s from retire), and the stuck definition (floor + 600 s or CONTRADICTION).
- The breaker triggers: ≥2 stuck, the notional trigger, DUPLICATE_SUSPECT with the confirm-twice rule; entries-only halt with exits allowed.
- An **AMBIGUOUS-rate halt**: halt promotion, and stop if the observed rate exceeds the Wilson-upper 0.33.
- **Slippage and fee parity:** the fill-price versus screen-ask tolerance, and fee parity against the screen.
- A **NO ≥ 0.90 hold-time re-measurement** as a ramp stage gate (the build gate used YES inputs).
- **Concentration** stop criteria from the first-5 s deployed-budget-fraction telemetry.
- A statement of independence from `PREREG.json`, and that no data from 2026-10-07 to 11-28 is used. Operator caps are referenced, never assigned.

WP7's K proposal and any K>1 activation are blocked on its frozen SHA.

## 10. Open questions for peer review
1. Is a durable entry-halt key (a latch-held flag) an acceptable substitute for a veto signature change, given the stated pins?
2. Is `qty_est = notional/price` adequate for the duplicate detector, or should a trailing-optional `wire_quantity` be added to `AmbiguousResolverContext` (AR-N6 pattern)?
3. Is `f_adm = 0.50` right as a backstop above `f_breaker = 0.25`?
4. Should the synthetic boot cool-off apply to every slug that had an OPEN slot at boot, or only to those retired by the first pass?
5. Does the confirm-twice lag guard (≥120 s age plus two passes) cover positions-feed lag enough, or does the feed need a measured bound (WP0)?
6. Do the WP-DR "log and continue" semantics for a ledger raise need a health-surface entry, given that a new `_refuse` call site would move the 25-site producer pin?

## 11. Change log (every r2 finding → r3 resolution)

**Coordinator rulings:** 1 → WP-DR (§5). 2 → §3.3 steps 3-4 and tests. 3 → §3.5 (permit unchanged; partials net of the seeded part). 4 → §3.5/§3.6 (`mark_ambiguous`; `f_breaker = 0.25`; sticky CONTRADICTION; c/B sweep in WP0). 5 → §3.2 (deltas table), §3.3 (`admit` at K=1), §3.4 (scope at append time). 6 → §3.1, WP2, WP5a, WP5b. 7 → §3.3 step 3 and §3.4 slug plumbing. 8 → §3.6. 9 → §3.1. 10 → §3.5. 11 → §3.6 (entries-only halt; no pinned signature changes). 12 → §7. 13 → §9. 14 → below.

**Architecture review (r2-A)**

| ID | Resolution |
|---|---|
| HIGH-1 | §3.2 deltas table; §3.3 `admit` K=1 ≡ `is_latched` over `is_exit`; WP4 named non-neutral (§8.1). |
| HIGH-2 | §3.2 and §3.3: the predicate is in `admission_refusal` before spend, exception-contained, plus the arbiter. Tests listed. |
| HIGH-3 | WP-DR (skip on `booking.day != today`, raise-safe, tests). §3.5 settle is booking-day independent. |
| HIGH-4 | §3.3: the :6110 gate is unscoped-only; the slug is derived at the admission gate in a try/except; `test_unmappable_instrument_denied_not_raised`. |
| MEDIUM-1 | §3.5: permit seeding unchanged (ruling 3). |
| MEDIUM-2 | §3.4: the scope is decided from `open_slot_count() > 1` at append time and stored on the refusal; K_eff is the configured constant (§3.2). |
| MEDIUM-3 | §3.1 and WP2: raw bytes preserved, counted for the downgrade, and quarantine denies exits. |
| MEDIUM-4 | §3.5: `seeded_partial_usd`; the exactly-once property includes partials. |
| LOW-1 | §3.1: the cool-off is durable (one answer). |
| LOW-2 | §3.1: v1 whenever ≤1 open, unconditionally. |
| LOW-3 | Accepted (single stat/read; exception-contained). |
| Q1, Q5, Q7 | Q1 satisfied via HIGH-4; Q5 via MEDIUM-3; Q7 via HIGH-2. |

**Safety review (r2-S)**

| ID | Resolution |
|---|---|
| C1 | §3.1, WP2, WP5a (verbatim `raw_slots`; the downgrade count; the CLI ack path; the alert). |
| H1 | WP-DR (skip, raise-safe, the 23:59Z/00:03Z test, both paths). |
| H2 | §3.3 `admit` and the property over `is_exit`; §3.7. |
| H3 | §3.6: per-leg magnitude with NO-sign; the `None` baseline is not evaluable; confirm-twice with the age floor; cool-off after fills; recorded in `_resolver_contradiction_details`. |
| H4 | §3.4: the slug comes from `SubmitIntent.slug`; the unscoped refusal clears when `open_slot_count() == 0`. |
| M1 | §3.6: entries-only halt, exits allowed, justified; held-position alert. |
| M2 | §3.7 and R11: equal to today; alert on a stuck slot with a held position; the cool-off excludes exits. |
| M3 | §3.1: durable. |
| M4 | §3.5 and F15: the boot interleave reasoning and test. |
| M5 | §3.5: the denial names the reason (logged WAIT); test in WP4. |
| L1 | §3.3: the tag-derived `is_exit_order`. |
| L2 | §3.4 H5: dict attributes are passed in, with no builtin call. |
| L3 | §3.6: `f_breaker < f_adm`; the non-vacuous test. |
| L4 | §3.3: the pre-check runs before the permit; tests assert the permit/booking are untouched. |

**Market review (r2-M)**

| ID | Resolution |
|---|---|
| HIGH-1 | §3.3 step 4: the read-only pre-check before the permit; the in-lock check stays authoritative; the no-day-stop-marker test. |
| HIGH-2 | §3.5: permit seeding unchanged; the ledger alone enforces open exposure; `test_boot_permit_untouched_by_open_intent_registration`. |
| HIGH-3 | §3.5: the bound applies to marked-AMBIGUOUS notional only (`mark_ambiguous`); WP0 models it with a c/B sweep as a stop-rule dimension. |
| HIGH-4 | §3.6: `f_breaker = 0.25` separate from `f_adm = 0.50`; sticky CONTRADICTION; both in D-PREREG. |
| MEDIUM-1 | §3.1: durable cool-off; the synthetic boot cool-off; measured from the retire time. |
| MEDIUM-2 | §3.5: `_roll_locked` in settle/register; per-key `_unknown_keys`; tests. |
| MEDIUM-3 | §7: both free-balance arms; the stop rule uses the worse. |
| MEDIUM-4 | §9: the full content list. |
| LOW (boot ordering, quarantine denies exits, Q1/Q6) | The boot interleave added to the property (§3.5); exits denied under quarantine stated (§3.7); Q1 and Q6 resolved by §3.3 and §3.1. |

**Plan-reviewed files:** `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r2.md` and the three r2 reviews in `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/reviews/`.
