# PLAN r4: EXEC-PAR, bounded per-market-slug parallel submit intents

Status: DRAFT r4 for peer review. Build-time only. This plan builds capability and does not re-enable orders. It was written read-only; the coordinator saves it.
Supersedes r3. All 11 coordinator rulings are adopted. §10 maps every r3 finding to its resolution.

**Delta from r3**
- **WP-DR** is a prerequisite with its own authoritative spec (§5).
- The ledger gets one **`settle`** entry point. It tolerates concurrent tasks and non-monotonic clocks, applies the day-skip rule to all six post-booking sites, and uses the seed's own predicate.
- The post-POST ledger calls and the resolver's ledger calls use a **fresh clock**.
- Refusal scope keys on the configured K.
- The duplicate detector uses a new `wire_quantity`.
- The entry-halt read fails closed, and a watcher heartbeat makes the breaker fail closed too.
- The §7 stop rule is rebuilt around realized order cost over budget.

## 0. Hard invariants (binding on every WP)

1. Nautilus Trader is immutable. Extend it only through the injected `StateStore`/latch seam and native config.
2. `allow_short` stays `False`.
3. Never weaken or delete a safety, settlement, contract, NO-SEND egress-firewall or import-pin test.
   - Widen exact sets only by named rows, keeping `==`.
   - Ordering pins are rewritten only to same-strength assertions on a renamed callee.
   - A test whose asserted behaviour is deliberately superseded is replaced only by a named successor test plus a retained variant for the unchanged case (§3.2, D1).
4. `exec/client.py` is byte-pinned. The floors never move: zero-fill 120 s, no-id 300 s, poll 5 s, backoff cap 300 s. There are **two re-pins**: WP-DR (by the coordinator) and WP4.
5. Operator caps (max daily budget, max per position = per order) are never assigned, defaulted or re-literalled. They may be read, read-only, through the existing readers.
6. `BREEZY_ORDERS_ENABLED`, permit minting and `fq-v1-halt-orders-off.conf` are untouched.
7. No mypy ceiling raise. No `type: ignore`, `Any` or `cast` in new code.
8. No `PREREG.json` edit.
9. M1-v3 window outcomes and tape for 2026-10-07..11-28 are never read. Every offline tool refuses such inputs.
10. Capability build only. Trading through K>1 needs D-PREREG (§8).

## 1. Verified current-state facts (re-checked in code 2026-10-10)

**Store and latch**
- F1. `CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"`, `_SCHEMA_VERSION = 1` (`runtime/submit_intent.py:37-38`). `StateStore` is `get/set` only (:43-53), so keys cannot be enumerated.
- F2. `SubmitIntent.from_bytes` requires `v == 1` and ignores extra keys (:276-298). A v2 table is `SubmitIntentCorrupt` (latched) in v1 code.
- F3. `arm` refuses on OPEN or corrupt (:399-427). `retire` writes history first (:493-511). `is_latched` treats corrupt as latched (:386-397). `CorruptError` is a class attribute (:338).
- F4. The resolver context is per-intent (`client.py:1094-1166`) with trailing-optional fields decoded via `.get` (:1236-1262). It is absent for a no-id window-only pass (:2691-2707). `_note_ambiguous_open` has two call sites, :6303 (pre-POST) and :6628 (with-id overwrite). It leaves `baseline = None` on a read failure (:5983-5990).

**Submit path (`_submit_order`)**
- F5. Gates and effects, in order:
  1. refusal gate :6110;
  2. mapping check :6189-6191;
  3. permit-missing :6192;
  4. `is_latched` :6204;
  5. `_submit_veto` :6215-6218;
  6. body build :6226-6237;
  7. **permit authorise and consume** :6239-6254, where `SessionNotionalExhausted` calls `_mark_budget_exhausted` (:6255-6257; durable day-stop, :5413-5438);
  8. `authorize_order_cost` :6276 (`DailyBudgetExhausted` also marks the day, :6282);
  9. `_intent_reconciled` :6286;
  10. `arm` :6291;
  11. `_note_ambiguous_open` :6303;
  12. POST :6327.
  - The pin is `test_execution_egress_firewall_guard.py:3066-3106`: `max(is_latched) < min(veto) < min(permit)`, with no `await`.
  - `now_ns` is captured once at :6109.
- F6. `is_exit_order` is tag-derived (:6128-6149).
- F7. `_refuse` dedupes on reason only and writes `instrument=""` (:6757-6761). The AMBIGUOUS refusal is appended at :6333 and :6580. Clears are guarded by `current_open() is None`: :3274-3282, :3502-3514, :4106-4115.
- F8. `_post_in_flight_intent_id` is a single `str | None` (:1838, :6325, :6349; reader :3747).
- F9. `base_slug_of` raises on an invalid slug or foreign venue (`symbology.py:298-314`). YES and NO share a base slug.
- F10. **Wire facts.**
  - The wire body hard-codes `"quantity": 1` (`submit_chain.py:373`).
  - The wire `price.value` is the YES-side price, so `1 − price` on the NO leg (:363-368).
  - `order_notional_usd = instrument price × order quantity` (:245-246).
  - So `notional / wire_price` is wrong on the NO leg (a NO buy at 0.92 has wire price 0.08).

**Ledger calls and clocks**
- F11. **Ledger calls after booking** (nine sites):
  - resolver: `true_up_booking` :3231 (zero-fill, after `_retire`), :3408 (accept-fill, **before** `_retire` :3429), :4072 (no-id, after `_retire`);
  - post-POST in `_submit_order`: `true_up_booking` :6467 (accept-fill, in the `else:` of the `record_fill` try, uncaught), :6555 (zero-fill), `release_booking` :6570 (reject);
  - pre-POST: `release_booking` :6288, :6294, :6319 (same task, no `await` since `authorize`).
- F12. **`now_ns` staleness.**
  - The three post-POST sites reuse the :6109 entry `now_ns`, across the POST `await`.
  - The resolver sites use `now_ns` captured at :3013 or :3750, before further awaits.
  - `authorize_order_cost` sets `_last_ns = now_ns` (`operator_controls.py:426`), and `_require_open_booking` raises if `now_ns < _last_ns` (:438-441) or if `booking.day != utc_day_for_ns(now_ns)` (:443-447).
  - At K=1 nothing authorizes during an await (the latch is held), so none of this is reachable. **At K>1 any concurrent authorize (or a day roll) makes A's later true-up or release raise**, which for :6467 escapes the task. The fill record is written, but the slot stays OPEN and `OrderSubmitted`/`OrderFilled` are never emitted.
- F13. Resolver-path fills are stamped `ts_event = now_ns` (discovery time, `client.py:3372-3383`). The create-path fill carries the venue execution time. The boot seed buckets by `ts_event` day (:2418).
- F14. Boot order in `_connect`:
  1. the first resolver pass is awaited (:2174);
  2. the periodic resolver task is created (:2184-2196);
  3. `_reconcile_submit_intent` (:2312);
  4. `_seed_spend_from_durable_fills` (:2370; early `return` at :2422 when zero fills);
  5. `_spend_seeded = True` (:2223).
  - There is no `await` between 3 and 5. Fill handlers are synchronous, so each is wholly before or wholly after the seed span.
- F15. `_RESOLVER_FILL_UNBUDGETED` (:732, :3458-3466) latches a global DURABLE refusal when `booking is None`, the order is not a SELL, and `_spend_seeded`.
- F16. `_resolver_contradiction_details` exists (:1959, :3965, :4038), is surfaced at :2531 and is popped at `_retire` (:5924). `_resolver_leg_holding_qty` (:1531) gives the per-leg absolute magnitude (0 for the other leg, `None` if undetermined). The same-day branch at :3125 only logs and continues.
- F17. `seed_permit_budget_from_prior_spend` is once per permit and one-way (`safety.py:799-841`). D3: a permit restore happens only with `booking is not None` (:3226-3250).
- F18. The submit throttle `output_drop=self._deny_new_order` (`risk/engine.pyx:140-150`) is a drop, upstream of `_submit_order`. `max_order_submit_rate = "5/00:00:01"` (`node_config.py:698`). Free-balance denial is per order (`engine.pyx:949`). In-flight checks stay off (`node_config.py:876-901, 1036`).
- F19. `_submit_veto: Callable[[], str|None]` is read only at :6215 (wired through `family_halt_submit_veto`, `FqComposedVeto` and `node_config.py:816, 971-976`). `exit_wiring.py:278` separately refuses on `is_family_halted()`.
- F20. The supervisor marker is `supervisor_decode_marker.py:36-155`, written at `trade_supervisor.py:2939`, read once at node boot (`node_config.py:1007`).
- F21. Firewall: all of `_resolve_terminal_zero`, `_resolve_accept_fill` and `_resolve_no_id_intent` are in `EXEC_RESOLVER_COROUTINES` (`test_execution_egress_firewall_guard.py:2113-2130`), so their bodies are scanned. `self._clock.timestamp_ns` and `self._note_resolver_error` are already permitted.

**Consumers of intent state (complete sweep of `src/`, `scripts/`)**
- The exec client: :2670, :3197, :3274, :3339, :3502, :4063, :4106 (`current_open`); :6204, :6785 (`is_latched`); :1838, :3747, :6325, :6349 (in-flight id).
- `trial_day_latch.py:732, 753`; `continuous_strategy.py:1713, 1918, 2496, 2600, 2739`; `continuous_no_side.py:309`; `exit_wiring.py:183`; `exit_guard.py:163-192` (no live caller).
- `trade_supervisor.py:431-501` and consumers :1298-1307, :1361-1377, :1476, :1866; marker write :2939; `clear_submit_intent_cli.py:125`.
- `prelaunch_intents.py:50-70`; `scripts/analysis/score_live_trials.py:190, 383-410, 531`; `scripts/ops/ambig_latch_phase_a_check.py`; `trade_cli.py:432, 538`.
- `forecast_quantile_ladder` uses its own `QuantileLadderLatch`. It is not a consumer and gains the benefit through the exec client. `fill_time_count.py` reads no singleton (WP0 re-verifies).

**Premise audit.** The constants are correct (the poll is at :588). "42% within 5 s" is confirmed. K=1, p_amb=0, p90 = 0.491 is reproduced (in-memory; WP0 commits it). "Drop" is the screen's policy; the code WAITs.

## 2. Native-Nautilus gap analysis

| Need | Native? | Verdict |
|---|---|---|
| Concurrent submission | Yes: one task per `SubmitOrder` | No gap. The serialisation is Breezy's venue-safety control. |
| Ambiguity resolution | In-flight check force-resolves FAILED | **Gap** (no client-order-id). Stays disabled. |
| Per-order notional and rate | `max_notional_per_order`; 5/s throttle that **drops** | Retained. The drop is modelled and wastes no permit. |
| Free-balance denial | Per order | A native denial source. Modelled both ways (§6). |
| Aggregate open exposure vs a daily budget | No | **Gap.** The ledger is the sole authority. |
| Per-slug durable exclusion with crash recovery | No | **Gap.** Built on the injected-latch seam. |

Options B (anonymous slots), C (queue) and D (second router) are rejected as before.

## 3. Design

### 3.1 Storage: one atomic table at `CURRENT_INTENT_KEY`
- **Encoding rule.**
  - v1 bytes whenever ≤1 slot is open **and no unreadable slot exists**. This is unconditional on the marker, so a 0→1 arm never writes v2.
  - **A lone unreadable slot stays v2**, because it cannot be encoded as v1.
  - v2 is `{"v":2,"slots":{<key>:<intent record incl. slug>},"raw_slots":{<key>:<base64>},"cooloff":{<slug>:<until_ns>}}`, written only while ≥2 slots are open (counting unreadable ones) or an unreadable slot exists, and only when the v2 predicate holds.
- `SubmitIntent` gains a trailing optional `slug: str | None = None`; `to_bytes` emits it only when set. A K=1 arm uses `slug=None`, so the bytes are identical to today.
- Every arm or retire is **one atomic `set`** of the whole table under the existing mutex and flock. History-first retire is unchanged. `reconcile_at_startup` copies history over matching slots.
- **Unreadable slots.**
  - A slot whose JSON value fails record validation is stored in `raw_slots` as **base64 of its canonical JSON text**, and re-emitted identically by every later arm or retire.
  - A table that is not valid UTF-8 JSON is a whole-table corruption: latched, with the existing CLI path.
  - An unreadable slot counts as OPEN, never downgrades the table, and **quarantines admission, which also denies exits**.
  - The first unreadable slot logs ERROR once and is exposed through a client property for the alert watcher.
  - **Recovery:** CLI `--slot-key KEY --ack-unreadable-slot`. It first **dumps the raw bytes to an evidence file** beside the store (`<store>.unreadable_slot.<key>.<ts>.bin`, fsynced; it aborts if the dump fails) and only then removes that slot. It needs the existing evidence checks and the node down.
- **Cool-off.**
  - It is durable in the table's `cooloff` map, measured from the retire time.
  - On downgrade or drain to a v1 record it is carried as an extra `cooloff` key (v1 readers ignore it).
  - **An arm from an empty (v1 RETIRED) table preserves unexpired `cooloff` entries.**
  - It applies to entries after zero-fill, no-fill and fill retires, never to exits.
  - **Every slug OPEN at boot gets a synthetic cool-off from boot time.**
  - K=1 mode writes none, so its bytes stay identical.
- Legacy adoption: a slug-less OPEN record takes `AmbiguousResolverContext.wire_market_slug`. A missing context uses key `"?:<intent_id>"`, which quarantines.

### 3.2 Ordering, predicate and neutrality
- WP5a (supervisor decode, marker capability, CLI tolerance, analysis readers) deploys **before any v2 write**. The marker gains a trailing-optional `slot_schema_versions`, and `supervisor_admits_slot_schema(store_path, 2)` uses the live-pid and start-ticks check.
- The v2 predicate `v2_admitted()` is evaluated on every would-be 1→2 transition. It is **exception-contained and returns False on error**. It is evaluated inside `admission_refusal` (before any spend) and again in `arm_slot` (the arbiter). A False result is a WAIT.
- **K_eff := the configured K constant.** It never derives from the predicate.
- **Neutrality statement.** With K=1 the system is behaviourally identical to today **except the enumerated deltas**. WP-DR and WP4 are non-neutral merges. WP0-WP3 are inert, and WP5a/5b/6 are neutral at K=1.

| Delta | Effect at K=1 | Test |
|---|---|---|
| D0 (WP-DR, own spec) | A midnight-crossing retire completes; an accept-fill against a prior-day booking latches `_RESOLVER_FILL_UNBUDGETED`. | the spec's tests |
| D1 (WP4) | A fill against a *registered* intent (boot-inherited, or booked on a prior day) settles through the registry instead of latching UNBUDGETED. This **supersedes** WP-DR's latch for registered intents only. The unregistered cross-process case still latches. | `test_accept_fill_after_midnight_settles_via_registry_no_latch`, and retained `test_accept_fill_unregistered_intent_still_latches_fill_unbudgeted` |
| D2 (WP4) | Open exposure that survives a roll or a restart keeps counting against headroom. | `test_booking_survives_day_roll_with_open_slot` |
| D3 (WP4) | `_refuse` dedupes on `(reason, instrument)`. | identical outputs at `instrument=""` |
| D4 (WP4) | `_post_in_flight_intent_ids` is a frozenset. | existing tests |
| D5 (WP4) | Ledger calls after booking go through `settle` with a fresh clock. | `test_settle_same_day_equals_true_up_and_release` (property) |

Everything else at K=1 is covered by `test_k1_store_write_sequence_matches_golden_v1` and `test_k1_differential_replay_identical_outputs`.

### 3.3 Admission before spend
Order inside `_submit_order`, all synchronous (the pin chain `latch < veto < permit` is kept, with the latch callee renamed):
1. **:6110 gate:** deny only on **unscoped** refusals (`instrument == ""`). It makes no slug call.
2. Mapping check, then `permit_is_missing` (unchanged).
3. **Admission gate (replaces `is_latched`):**
   - Derive `slug = base_slug_of(order.instrument_id)` inside `try/except Exception → self._deny`.
   - Deny on a scoped refusal for that slug.
   - Call `self._latch.admission_refusal(slug, is_exit_order)`.
4. **Read-only ledger pre-check** `self._ledger.exposure_admission_refusal(price_usd, quantity, now_ns)` (§3.5).
5. `_submit_veto`, the body build, and `if body["marketSlug"] != slug: return self._deny(...)`.
6. Permit spend, `authorize_order_cost` (the in-lock checks are **the authority**), `_intent_reconciled`, `arm_slot` (re-runs `admit`), `register_open_exposure`, `_note_ambiguous_open`, POST.

`admission_refusal` evaluates, in order:
- quarantine (denies exits);
- the v2 predicate on a would-be 1→2 transition;
- **the entry-halt flag** (entries only; fail-closed, see §3.6);
- the **watcher heartbeat** (K>1 only, see §3.6);
- same slug open;
- K-full (entries);
- cool-off (entries).

Required tests, each asserting that the permit remaining count and notional are untouched, no `_mark_budget_exhausted` marker is written, and no booking is made:
- `test_k_full_denial_before_permit_spend`;
- `test_same_slug_denial_before_permit_spend`;
- `test_v2_predicate_false_is_wait_before_permit_spend`;
- `test_v2_predicate_raises_is_wait_before_permit_spend`;
- `test_exposure_precheck_denial_before_permit_spend_no_day_stop_marker`;
- `test_entry_halt_denies_entries_before_permit_spend`;
- `test_entry_halt_store_raise_denies_entries_not_raises`;
- `test_entry_halt_garbled_value_denies_entries`;
- `test_stale_heartbeat_denies_entries_at_k_gt_1_only`.

`admit(table_view, slug, is_exit, k, entry_halted, now_ns)` is pure (domain):
- Quarantine denies all, including exits.
- **If `k == 1`:** deny iff any slot is open (≡ `is_latched`), for entries and exits.
- **If `k > 1`:** deny the same slug; entries are denied when non-exit open slots ≥ k, in cool-off, or entry-halted; exits are K-exempt and cool-off-exempt but slug-exclusive.
- The property quantifies over `is_exit`, arbitrary tables and unreadable slots.

### 3.4 Singleton fields and sites
- **H0** `_post_in_flight_intent_ids: frozenset[str]`.
- **H5 selection (:2670).** `current = self._latch.next_open_for_resolution(self._resolver_intent_failures, self._resolver_intent_served)`.
  - It passes two attribute dicts, so no builtin call.
  - It sorts by `(per-intent failures, last served, created)` and returns a `SubmitIntent` with `.slug`.
  - Unreadable slots are skipped and logged once per key.
  - The per-intent counters mirror the five increment and two reset sites. The global counter still drives the sleep.
- **H7 by-id guards (:3197, :3339, :4063)** use `self._latch.is_open_intent(intent_id)`.
- **Slug plumbing.** The three resolver bodies receive `slug=current.slug or ""` from the `SubmitIntent` record, not from the context. This covers the no-id window-only path.
- **Refusal scope (ruling 2).**
  - At each AMBIGUOUS append (:6333, :6580): `self._refuse(AMBIGUOUS_REASON, instrument=slug if self._latch.max_slots() > 1 else "")`.
  - **Scope keys on the configured K**, so a lone ambiguous order at K>1 is scoped and other slugs proceed. K=1 stays unscoped (neutral).
  - The scope is stored on the `ClassifiedRefusal` and pinned `RefusalClass.DURABLE`.
  - `_refuse` dedupes on `(reason, instrument)` (keyword-only; pin-neutral, `test_exec_refusal_health_surface.py:182-291`).
- **H8 clears (:3274, :3502, :4106).** Remove AMBIGUOUS refusals scoped to `slug`, and also the unscoped AMBIGUOUS refusal if `self._latch.open_slot_count() == 0`. At K=1 this is the old condition.
- **Tests.**
  - `test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed`;
  - A ambiguous, B ambiguous, A retires: B's refusal survives;
  - `_map_position` success on A never clears A's AMBIGUOUS;
  - a K=1 unscoped refusal clears only when no slot is open.
- `resume_if_refusals_cleared` keeps `is_latched()` (any open or quarantined slot ⇒ latched).

### 3.5 Exposure accounting
Additive `DailySpendLedger` methods in `operator_controls.py`. Existing public methods, their "previous UTC day" refusals and their tests are unchanged. Their bodies are factored into `_true_up_locked` and `_release_locked`, which the new code reuses.

**API**
- `register_open_exposure(key, notional_usd | None, *, booking | None, seeded_partial_usd, now_ns)`. Charged iff a same-day booking is given. A `None` notional adds `key` to a **per-key** `_unknown_keys` set (entries are refused while non-empty; retiring a key removes only that key).
- `mark_ambiguous(key)`. Called at :6333 and :6580 and for every boot-registered intent.
- `settle(key, *, booking | None, realized_usd | None, fill_ts_ns | None, now_ns) -> bool` is the **single entry point for the nine sites of F11 except the three pre-POST ones**. Pre-POST release also uses `settle(realized=None)` at :6319, where an entry is already registered.
  - It computes `eff_now = max(now_ns, _last_ns, _registry_last_ns)` and then `eff_day`. **It tolerates non-monotonic `now_ns` from concurrent tasks** (a stale `now_ns` never rolls back and never raises "clock moved backwards").
  - **Same-day live booking:** `realized_usd` not None → `_true_up_locked`, else `_release_locked`. Genuine integrity errors still raise exactly as today (over-cost true-up, double settle, unknown booking), so they stay visible.
  - **Prior-day booking or no booking (registered uncharged entry): the booking day-skip.** Add `max(realized − seeded_partial, 0)` to `_spent_usd` iff `realized` is set and **the fill record's `ts_event` day == `eff_day`**. This is the *same predicate as the boot seed*.
  - It removes the entry. It returns True iff the key was registered, and increments a `cross_day_settles_total` counter surfaced to the digest.
- `has_open_exposure(key)`, `uncharged_open_total()`, `ambiguous_open_total()`, `unknown_key_count()`.
- Day roll: `_roll_locked(eff_now)` is the existing pruning code (:403-417), except that surviving **open** entries convert to uncharged instead of being dropped. It only rolls forward.

**Invariant**: at every `authorize_order_cost`, `spent_today + uncharged_open + cost ≤ budget` and `ambiguous_open_total + cost ≤ f_adm × budget`.
- `f_adm = 0.50` and `f_breaker = 0.25` are Breezy-owned `Final` constants in `node_config.py`, injected at construction. `None` means the bound is off.
- **Exceptions in the lock.**
  - The existing `spent + cost > budget` raises `DailyBudgetExhausted` (day-stop, unchanged).
  - **If `spent + cost ≤ budget` but `spent + uncharged + cost > budget`, it raises the non-day-stop `OpenExposureBoundExceeded(LiveTradingPermissionError)`.** The same type is raised for the AMBIGUOUS bound.

**Pre-check** `exposure_admission_refusal(price_usd, quantity, now_ns) -> str | None`:
- Genuinely read-only: it takes the lock and **computes the roll on a view** (no mutation).
- It uses the **same cost function** as the in-lock path (`order_cost_usd`, rounding up to the cent), so the boundary agrees to the cent.
- It reads the budget **only if** `uncharged`, `ambiguous` or `unknown` totals are non-zero (`unknown > 0` denies without reading it). Any `LiveTradingPermissionError` (unset control, clock rewind) is **returned as a deny reason, with no marker**.
- It evaluates only the new conditions. The plain `spent + cost > budget` and the position cap stay in-lock only, to keep K=1 neutral.
- The in-lock raise after a passing pre-check (a rare race) is a non-day-stop type, and `_submit_order` already treats it as a plain deny.

**Fresh clock (ruling 1).** At the three post-POST sites in `_submit_order` and the three resolver sites, `now_ns` for the ledger call is a **fresh `self._clock.timestamp_ns()`** read immediately before the call (already allowlisted). Together with `settle`'s tolerance this covers stale and concurrent clocks.

**Boot (H6).** In the no-await span between `_seed_spend_from_durable_fills` and `_spend_seeded = True`:
- Register every still-OPEN intent as uncharged, marked ambiguous, with the context's `notional_usd − seeded_partial` (`None` if the context is absent).
- Permit seeding is **unchanged**: durable fills only. Open exposure is enforced by the ledger alone, and no permit restore happens (D3).
- A fill handler is wholly before or wholly after this span (F14).

**Retire.** Each fill handler captures `registered = self._ledger.settle(...)` before `_retire`. The UNBUDGETED condition becomes `not registered and booking is None and not SELL and _spend_seeded`. `_retire` calls `settle(key, realized=None)` idempotently.

**Exactly-once property** (hypothesis). Over any interleaving of seed, register, partial, full fill, zero-fill, day roll and settle, **including two concurrent tasks with stale and fresh `now_ns`, and midnight crossings**:
- each fill's cost counts once in `spent_today`;
- open exposure is never dropped before settle;
- partials net out (P + (R − P) = R);
- **at quiescence the in-process `spent_today` equals the boot seed's total over the same durable fill records** (`test_in_process_spend_equals_seed_after_restart`).

### 3.6 Breaker
Frozen numbers for the first K>1 deployment (restated in D-PREREG):
- **Stuck** = an AMBIGUOUS open intent with age > `floor + 600 s` (with-id 720 s; no-id 900 s), or any intent with a recorded CONTRADICTION.
- **Trip** at ≥ 2 stuck, **or** `ambiguous_open_total > f_breaker × budget` (`f_breaker = 0.25 < f_adm = 0.50`, so it is live), **or** a DUPLICATE_SUSPECT.
- **Duplicate detector (inside the resolver; recorded in `_resolver_contradiction_details`, kind `DUPLICATE_SUSPECT`).**
  - New trailing-optional `wire_quantity: str | None` on `AmbiguousResolverContext` (AR-N6 pattern; JSON key `wireQuantity`). It is written from `str(body["quantity"])` at both `_note_ambiguous_open` call sites. An old blob decodes as `None`.
  - On each pass with eof-complete positions and a baseline:
    - `venue_leg_qty = _resolver_leg_holding_qty(positions, slug, leg)`;
    - the baseline leg magnitude comes from `baseline_venue_net` with the NO-as-short-YES sign (`yes: max(net,0)`, `no: max(−net,0)`), via a pure `_leg_magnitude_of_signed_net` (a named resolver row);
    - suspect iff `venue_leg_qty − baseline_leg_qty > Decimal(wire_quantity)`. **No division by the wire price.**
  - A `None` baseline, `None` leg quantity or `None` `wire_quantity` is **not evaluable**: it resets the counter and never trips or crashes.
  - **Lag guard:** age ≥ `L_feed` and confirmation on a **second consecutive pass**. `L_feed` is the WP0-measured positions-feed lag bound, or **300 s** if it cannot be measured.
  - Cool-off after fill retires covers lag after a same-slug prior fill. Manual trades still trip it (fail-closed).
  - A duplicate that adds no more than one order's quantity is undetectable. Exposure there is bounded by the cap.
- **Sticky until operator reset.**
  - `contradiction_events_total` is a monotonic in-memory counter. The watcher latches the durable entry-halt on any increase, and the latch survives the `_retire` pop.
  - *Durability:* a crash between detection and the latch loses only the in-memory event. Detection is a pure function of durable state (the context baseline) plus the venue positions, so it re-fires after restart within `L_feed` plus two passes, and open intents persist.
- **Watcher latency and liveness.**
  - The watcher polls the client properties **at most every 5 s (one resolver poll)**, so the latch latency is ≤ one poll. At most K orders can be admitted in that window.
  - **Heartbeat:** every poll the watcher writes `…/intent/breaker_heartbeat` through a latch method. At K>1, `admission_refusal` **denies entries when the heartbeat is older than 60 s** (12 polls) or absent more than 60 s after boot, and alerts once. A dead watcher therefore fails closed. At K=1 the check is off (neutral).
- **Entry-halt key `…/intent/entry_halt`.**
  - Absent ⇒ not halted. A decodable `{"v":1,...}` ⇒ halted. **A store exception or an undecodable value ⇒ deny entries.**
  - The writer runs in the node under the latch's mutex and flock.
- **Effect: entries only.**
  - The halt uses no family-halt key and no veto, so `_submit_veto`'s signature, `family_halt_submit_veto`, `FqComposedVeto` and `exit_wiring.py:278` are untouched. **No pin changes.**
  - Exits stay allowed, because the breaker trips exactly when held positions may need selling, and halting exits would worsen a doubled position.
  - The watcher alerts the operator with the held-position list (from the resolver-refreshed startup-position evidence) and any stuck slot on a slug that has a held position. It needs a new `AlertDetail` member (the exhaustive-enum pin is checked in WP5b).
- **Operator reset (`--reset-entry-halt`).** It takes the intent flock, so it **requires the node to be down** (the CLI refuses while the node holds it, `clear_submit_intent_cli.py:140-145`), and it requires `--ack-held-positions-reviewed`. Both conditions are restated in D-PREREG.
- **The breaker never blocks the resolver.** The resolver reads neither `entry_halt` nor the veto. Test: a tripped breaker still retires a pending slot.

### 3.7 Exits and quarantine
- Exits are K-exempt only when K>1, and always slug-exclusive. At K=1 they behave as today. Quarantine denies exits (as `is_latched` does today).
- `exit_guard.assert_settlement_close_permitted` gains an optional keyword `refusal_scopes`; the existing signature and tests are untouched. The client exposes `trading_refusal_scopes`.
- `exit_wiring.check_exit_intent_for_ambiguous_send` (:183) uses `TrialDayLatch.open_submit_intents()` and matches by fingerprint.
- A stuck entry on slug S blocks that slug's exit (equal to today). The alert in §3.6 covers it.

### 3.8 Venue and subscription constraints
Resolver GET load is unchanged, with an added latency of ≤ (K−1)×5 s. There are no new WS subscriptions (the cap of 10 is shared), `subscribe_trades` stays off (test), and the throttle comment at `node_config.py:681-698` is rewritten (the value is not raised).

## 4. Re-pin procedure
Edit **only** `_EXEC_CLIENT_SHA256` (`tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`) after `python-reviewer` and `prediction-market-reviewer` approve the diff, appending `# re-pinned <date>: <WP>, reviewer-approved`. `test_autonomy_envelope.py:901-916` reads it by AST. An implementer never edits the pin. WP-DR's re-pin is the coordinator's.

## 5. Work packages (TDD order)

**Order:** WP-DR → WP0 → WP1 → WP2 → WP3 → WP5a → [supervisor restart, marker verified] → WP4 → WP5b → WP6 → WP7.
- Common gate: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -m pytest --basetemp=~/.cache/...`; `lint-imports` from the tree's cwd ("N kept, 0 broken"); `ruff`; `mypy` (no ceiling change); the full gate `scripts/ci/run_tests_no_egress.sh` after every merge, reading the exit code before any push.
- Every focused list includes the firewall guard, the exec-client, latch, ambiguous-resolver and AC6b tests, the operator-reserved and assignment-scan tests, the refusal-health-surface test, the pin tests, `tests/contract/test_live_fill_scoring_chain_contract.py` and all `test_autonomy_*`.
- Briefs state the exact interpreter, no `uv run`/`pip`/`git stash`, own scratchpad, format only your own files, and worktree `PYTHONPATH` first.

### WP-DR (prerequisite; authoritative spec, not redesigned here)
The day-roll settle fix is specified in `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md` and is being implemented independently. Per that spec:
- At the three resolver sites a prior-day booking skips the ledger call.
- There is no blanket `except`.
- `utc_day_for_ns` becomes a named resolver-allowlist row.
- A new-day accept-fill against a prior-day booking latches the existing `_RESOLVER_FILL_UNBUDGETED`.
- There is no new `_refuse` call site, and the re-pin is the coordinator's.

EXEC-PAR treats WP-DR as merged. WP4 builds on it: `settle` supersedes the inline skip and the UNBUDGETED latch **for registered intents only** (D1), and the `utc_day_for_ns` row stays (a harmless unused row; the allowlist sets are checked with `==` on the declared set).

### WP0: viability and premise verification (no production code)
Method and stop rule are in §6. RED (`tests/unit/test_exec_parallel_dhat.py`):
- `test_refuses_any_input_on_or_after_2026_10_07`;
- `test_k1_reproduces_p0_p90_0_491`;
- `test_simulation_uses_production_admit`;
- `test_throttle_5_per_s_drop_counted`;
- `test_free_balance_arm_a_fill_time` and `test_free_balance_arm_b_ambiguous_holds`;
- `test_stop_rule_uses_worse_free_balance_arm`;
- `test_ambiguous_bound_drop_counted_per_cost_over_budget_bucket`;
- `test_k_reported_per_bucket_no_worst_bucket_fallback`;
- `test_cluster_bootstrap_ci_upper_bound_stop`;
- `test_first_5s_budget_fraction_arm`;
- `test_stuck_slot_reduces_effective_k`;
- `test_yes_and_no_share_one_slot`;
- `test_hold_constants_match_exec_client_source_ast`;
- `test_caps_read_only_ratio_bucket_only_never_printed_or_assigned`;
- `test_positions_feed_lag_bound_measured_or_300s_default`.
- Recorded verifications (file:line):
  - the cash account's `free` update timing and the AMBIGUOUS lock behaviour;
  - `subscribe_trades` is off;
  - `fill_time_count.py` reads no singleton;
  - `base_slug_of(order.instrument_id)` equals the wire slug on sampled YES and NO ids.

### WP1: pure admission model + Protocol (domain)
- RED:
  - `test_admit_k1_equals_is_latched_for_any_table_entries_and_exits`;
  - `test_admit_denies_same_slug`;
  - `test_admit_k_full_entries_only_when_k_gt_1`;
  - `test_exits_k_exempt_and_cooloff_exempt_only_when_k_gt_1`;
  - `test_quarantine_denies_exits`;
  - `test_entry_halt_denies_entries_not_exits`;
  - `test_cooloff_applies_after_fill_retire`;
  - `test_admit_pure_deterministic`.

### WP2: slot table (runtime; inert)
- RED:
  - `test_k1_store_write_sequence_matches_golden_v1`;
  - `test_slug_key_only_when_set`;
  - `test_v1_reader_ignores_slug_and_cooloff_keys`;
  - `test_v2_table_is_corrupt_in_v1_code`;
  - `test_arm_and_retire_are_one_atomic_set`;
  - `test_crash_between_history_and_table_set_recoverable`;
  - `test_last_retire_writes_valid_v1_retired_with_cooloff`;
  - `test_arm_from_empty_preserves_unexpired_cooloff`;
  - `test_retire_of_healthy_slot_preserves_unreadable_slot_bytes_base64`;
  - `test_lone_unreadable_slot_stays_v2`;
  - `test_last_healthy_retire_does_not_downgrade_over_unreadable_slot`;
  - `test_unreadable_slot_quarantines_but_healthy_slot_resolvable`;
  - `test_legacy_open_adopted_by_context_slug`;
  - `test_legacy_open_without_context_quarantines`;
  - `test_every_slug_open_at_boot_gets_synthetic_cooloff`;
  - `test_v2_predicate_false_or_raising_refuses_one_to_two`;
  - `test_entry_halt_set_read_reset_and_fail_closed_read`;
  - `test_heartbeat_write_and_staleness_k_gt_1_only`;
  - `test_concurrent_arm_slot_one_winner_per_slug`;
  - `test_is_open_intent_and_open_slot_count_and_max_slots`.

### WP3: ledger API (inert)
- RED (`test_daily_spend_ledger_open_exposure.py`; the existing day-rule tests are untouched):
  - `test_settle_same_day_equals_true_up_and_release` (property);
  - `test_concurrent_authorize_during_post_await_does_not_break_true_up`;
  - `test_concurrent_authorize_during_post_await_crossing_midnight_settles_via_registry`;
  - `test_settle_tolerates_stale_now_ns_never_raises_clock_backwards`;
  - `test_settle_over_cost_same_day_still_raises`;
  - `test_open_exposure_survives_day_roll_as_uncharged`;
  - `test_settle_after_roll_before_next_authorize`;
  - `test_settle_uncharged_adds_realized_minus_partial_iff_ts_event_day_is_today`;
  - `test_in_process_spend_equals_seed_after_restart` (property over day-roll interleavings);
  - `test_exactly_once_over_all_interleavings_incl_partials_and_concurrent_tasks` (property);
  - `test_unknown_notional_is_per_key`;
  - `test_precheck_is_read_only_view_roll`;
  - `test_precheck_uses_inlock_cost_function_boundary_to_the_cent`;
  - `test_precheck_reads_budget_only_when_totals_nonzero`;
  - `test_precheck_budget_unset_or_clock_rewind_is_deny_no_marker`;
  - `test_uncharged_overrun_raises_non_day_stop_type`;
  - `test_ambiguous_bound_counts_only_marked_ambiguous`;
  - `test_cross_day_settles_counter`;
  - `test_prior_day_booking_still_not_releasable_via_public_methods`;
  - `test_operator_caps_never_assigned` (AST).

### WP5a: supervisor, marker, CLI, analysis (deploys BEFORE WP4)
- Files: `supervisor_decode_marker.py`, `trade_supervisor.py`, `clear_submit_intent_cli.py`, `prelaunch_intents.py`, `score_live_trials.py`, `ambig_latch_phase_a_check.py`.
- RED:
  - `test_marker_slot_schema_field_and_old_marker_decodes_empty`;
  - `test_admits_slot_schema_requires_live_matching_pid`;
  - `test_probe_open_true_for_v2_with_open_slot`;
  - `test_probe_resolvable_false_for_unreadable_or_contextless_slot`;
  - `test_clear_cli_never_raises_uncaught_on_v2`;
  - `test_clear_cli_lists_slots_and_clears_by_intent_id`;
  - `test_clear_cli_unreadable_slot_requires_key_ack_and_dumps_evidence_first`;
  - `test_clear_cli_aborts_if_evidence_dump_fails`;
  - `test_clear_cli_refuses_erasing_table_over_open_slots`;
  - `test_clear_cli_reset_entry_halt_requires_node_down_and_ack_held_positions`;
  - `test_score_live_trials_v2_open_not_absent`;
  - `test_prelaunch_observation_v2_open_is_ambiguous`;
  - `test_rollback_drill_after_drain_old_reader_sees_valid_v1_retired`.
- Deploy: merge, restart the supervisor, verify the marker field.

### WP4: exec client (byte-pinned; NON-NEUTRAL D1-D5; re-pin #2)
- Hunks: H0, the §3.3 gates, `arm_slot`, `register_open_exposure` and `mark_ambiguous`, H5, slug plumbing, H6, H7, H8, `settle` at all post-booking sites with a fresh clock, the UNBUDGETED condition, `_refuse` scope and dedupe, `wire_quantity` (context field and both call sites), the duplicate detector, and the properties (`trading_refusal_scopes`, `contradiction_events_total`, unreadable slots, open-intent ages, held-position inputs).
- **Named allowlist rows (keep `==`; each checked against the `read/send/post/request` banned-word scan).**
  - Order coroutine: `base_slug_of`; `self._latch.admission_refusal` (replacing `is_latched`; `is_latched` stays for `resume_if_refusals_cleared`); `self._latch.arm_slot` (replacing `arm`); `self._latch.max_slots`; `self._latch.open_slot_count`; `self._ledger.exposure_admission_refusal`; `self._ledger.register_open_exposure`; `self._ledger.mark_ambiguous`; `self._ledger.settle`.
  - Resolver coroutine: `self._latch.next_open_for_resolution`; `self._latch.is_open_intent`; `self._latch.max_slots`; `self._latch.open_slot_count`; `self._ledger.has_open_exposure`; `self._ledger.settle`; `_leg_magnitude_of_signed_net`.
  - The ordering pin is rewritten same-strength. A new AST pin asserts no `await` between `authorize_order_cost` and `register_open_exposure`.
- RED (extend `test_polymarket_us_exec_client.py`):
  - the §3.3 pre-spend tests;
  - `test_two_distinct_slugs_both_post_concurrently`;
  - `test_concurrent_authorize_during_post_await_does_not_break_true_up` (client level, at :6467, :6555 and :6570);
  - `test_concurrent_authorize_during_post_await_crossing_midnight_no_stuck_slot_events_emitted`;
  - `test_accept_fill_after_midnight_settles_via_registry_no_latch`;
  - `test_accept_fill_unregistered_intent_still_latches_fill_unbudgeted`;
  - `test_resolver_ledger_calls_use_fresh_clock_at_k_gt_1`;
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
  - `test_body_slug_mismatch_denied`;
  - `test_unmappable_instrument_denied_not_raised`;
  - `test_wire_quantity_written_at_both_call_sites_and_old_blob_decodes_none`;
  - **duplicate detector, per leg at both price extremes:** `test_duplicate_detector_{yes,no}_{at_0_08,at_0_92}_single_fill_does_not_trip` and `..._doubled_holding_trips` (eight cases);
  - `test_duplicate_detector_none_baseline_or_wire_quantity_not_evaluable`;
  - `test_duplicate_detector_needs_second_pass_and_lag_guard_age`;
  - `test_duplicate_detector_records_contradiction_not_just_log`;
  - `test_k1_differential_replay_identical_outputs`.

### WP5b: node config, breaker, telemetry (neutral at K=1)
- Files: `node_config.py`, `trade_cli.py`, `app/trade.py`.
- Contents:
  - the constants `EXEC_PAR_MAX_CONCURRENT_INTENTS = 1`, `OPEN_EXPOSURE_BOUND_FRACTION = Decimal("0.50")`, `BREAKER_OPEN_AMBIGUOUS_FRACTION = Decimal("0.25")`, and the heartbeat age (60 s), all `Final` and not env-derived;
  - the marker → `v2_admitted` wiring;
  - the watcher (≤5 s) with its heartbeat and alerts;
  - the throttle comment;
  - digest telemetry (`cross_day_settles_total`, per-station-day exposure, orders and notional per 5 s window).
- RED:
  - `test_constants_are_final_and_not_env_derived`;
  - `test_k_forced_1_when_marker_absent`;
  - `test_subscribe_trades_off_and_inflight_interval_zero`;
  - `test_breaker_trips_at_two_stuck`;
  - `test_breaker_notional_trigger_fires_at_f_breaker_below_f_adm`;
  - `test_contradiction_latches_entry_halt_sticky_until_operator_reset`;
  - `test_duplicate_suspect_trips`;
  - `test_watcher_latency_at_most_one_poll`;
  - `test_watcher_heartbeat_written_each_poll_and_dead_watcher_denies_entries_with_alert`;
  - `test_entry_halt_allows_exits_and_resolver_still_retires`;
  - `test_breaker_does_not_use_family_halt_or_veto_signature`;
  - `test_first_unreadable_slot_alerts_once`;
  - `test_alert_detail_enum_pin_green`;
  - `test_digest_reports_cross_day_settle_counter`.

### WP6: strategy and exit readers (neutral at K=1)
- Files: `trial_day_latch.py` (add `admission_would_refuse(slug, is_exit)` and `open_submit_intents()`), `continuous_strategy.py:1713, 1918, 2496, 2600`, `continuous_no_side.py:309`, `exit_wiring.py:183`, `exit_guard.py`.
- The pre-filters use the **same read-only admission predicate** as the exec gate, including quarantine, K-full, cool-off, **entry-halt and the stale-heartbeat denial**.
- RED:
  - `test_prefilter_equals_exec_admission_for_all_tables` (property);
  - `test_admission_would_refuse_reflects_entry_halt` and `..._stale_heartbeat`;
  - `test_hunt_proceeds_on_other_slug_when_not_k_full`;
  - `test_rearm_release_is_per_slug`;
  - `test_open_intent_wait_observation_names_slug`;
  - `test_exit_wiring_halts_on_stale_exit_in_any_slot`;
  - `test_exit_guard_scoped_refusal_permits_other_slug_close` and `..._unscoped_still_refuses`.

### WP7: failure injection, replay, soak (no live)
- RED:
  - `test_crash_at_every_line_arm_slot_to_post_no_double_order`;
  - `test_post_timeout_leaves_slot_and_slug_denied`;
  - `test_restart_with_three_open_slots_rebooks_and_resolves_each`;
  - `test_late_fill_after_zero_fill_or_fill_retire_then_rearm_same_slug_denied_by_cooloff`;
  - `test_exit_and_entry_same_slug_serialised_both_orders`;
  - `test_supervisor_rolled_back_mid_run_blocks_v2_write`;
  - `test_drain_then_rollback_drill`;
  - `test_crash_after_detection_before_latch_redetects_after_restart`;
  - `test_replay_bit_for_bit_fixed_clock`.
- Exit: a K-proposal blocked on D-PREREG's frozen SHA, on the WP0 artefact hash, and on re-running the §6 stop rule at the actual cost/budget bucket.

## 6. Viability (build gate; activation gate re-run)

**Method (pre-2026-10-07 data only).**
- Re-extract candidates with instrument ids using the existing pre-window bounds. Hold inputs come from `WP0_c0_pre1007_orders.tsv`.
- The model runs 1,000 seeded draws per day. Admission uses the **production `admit`**.
- p_amb ∈ {0, 0.05, 0.10, 0.18, 0.33}, with stuck-slot (K−1) and no-id arms.
- Arms, all counted in d̂ as drops:
  - the 5/s throttle (sliding 1 s window);
  - **free-balance, both directions** (arm A: reduce at accepted-fill time only; arm B: an AMBIGUOUS order also holds buying power for its stuck lifetime), with the stop rule using the worse arm;
  - the **AMBIGUOUS bound** `f_adm = 0.50`.
- **Sweep variable:** the *realized order cost over the daily budget* (orders are about 1 contract at ≤ $1), in buckets {≤0.02, 0.05, 0.10, 0.25, 0.50}. It is **not** the per-position cap.
- The live caps are a read-only input: an optional flag reads them through the existing readers and prints a **bucket label only**, never a value, and assigns nothing.
- Statistic: day-clustered bootstrap (2,000 resamples) of the day-level p90 and p50.
- **Reporting:** the smallest K (3..8) whose CI upper bound ≤ 0.30 **per bucket**, at p_amb = 0.33 (Wilson upper) with one stuck slot, the worse free-balance arm, the throttle and the bound.
- **Build gate (WP0):** the build proceeds iff **some** bucket in the table passes at K ≤ 8. There is **no worst-bucket fallback STOP**. If the bucket is unknown, WP0 reports the table only.
- **Activation gate:** re-run the stop rule once the actual bucket is known. K>1 activation is blocked unless the CI upper bound at that bucket is ≤ 0.30.
- Extra arm: the share of the budget deployed in the first 5 s per bucket (telemetry for D-PREREG).

**Preliminary point estimates** (in-memory, no throttle, free-balance, bound or stuck arm; not binding):

| K | p_amb = 0 p50/p90 | 0.18 p50/p90 | 0.33 p50/p90 |
|---|---|---|---|
| 1 (today) | 0.273 / **0.491** | 0.549 / 0.643 | 0.686 / 0.736 |
| 3 | 0.0 / 0.244 | 0.094 / 0.269 | 0.227 / 0.329 |
| 4 | 0.0 / 0.156 | 0.018 / 0.172 | 0.084 / 0.203 |
| 6 | 0.0 / 0.0 | 0.0 / 0.012 | 0.005 / 0.027 |

K=6 is not to be relied on until the CI and every arm have run. Caveats: the hold inputs contain no NO ≥ 0.90 order and every AMBIGUOUS order was YES; n_amb = 7; candidates are first-row, take-all and tie-free. This is a **build gate**, with no claim about NO ≥ 0.90 ambiguity or hold times.

## 7. Risks, kill criteria, rollback

| # | Risk | Sev. | Containment |
|---|---|---|---|
| R1 | Same-slug temporal bleed | High | Durable cool-off (entries only) after all retires; the two-pass detector |
| R2 | Stuck slots eat K | High | Breaker (≥2 stuck, `f_breaker`, sticky); `f_adm` backstop |
| R3 | Exposure across restart, day roll or concurrent tasks | High | WP-DR; `settle` with a fresh clock; the registry; per-key unknown-notional fail-closed |
| R4 | Scoped refusals mis-cleared | High | Scope keys on configured K; clear rules in both directions |
| R5 | Pin drift | Med | Named rows; same-strength rewrite; banned-word scan |
| R6 | v2 bytes read by a stale supervisor | High | WP5a first; the predicate before spend and in the arbiter |
| R7 | Lost unreadable slot | High | base64 `raw_slots`; never downgrade; evidence-dump CLI; alert |
| R8 | Native drops lose burst candidates | Med | Counted in d̂ |
| R9 | Concentration into a correlated 5 s repricing | Med | Telemetry; D-PREREG stop criteria |
| R10 | Hold-input population mismatch | Med | NO ≥ 0.90 ramp gate in D-PREREG |
| R11 | A stuck entry blocks that slug's exit | Med | Equal to today; alert |
| R12 | A dead watcher | Med | Heartbeat-based fail-closed entry denial at K>1 |

**Kill criteria.**
- The WP0 build gate fails in every bucket.
- Any duplicate-order evidence in WP7.
- A red full gate after a re-pin.
- An allowlist change that cannot be a named row.
- Any need to change `_submit_veto`'s signature.

**Rollback.**
1. **WP-DR and WP4 are non-neutral** (D0-D5). Their rollback is a code revert with the pin in the same commit.
2. Other WPs are neutral at K=1.
3. After K>1: trip or halt entries, review the held positions and reset the entry-halt, drain to ≤1 open (the table rewrites as v1), set K=1, then revert code with its pin.
4. **Old code ignores the entry-halt key and the heartbeat**, so after a code rollback the breaker is silently inert. Therefore the rollback is only valid at K=1 with the halt reviewed and reset first.
5. A rolled-back supervisor cannot admit v2, so the node refuses 1→2 transitions. If a v2 table is open, the old supervisor refuses launch and the CLI clears by intent id or slot key.
6. The halt drop-in and `BREEZY_ORDERS_ENABLED` are never touched.

## 8. D-PREREG: execution-design prereg (named deliverable, not written here)
Capability needs no prereg (no screen claim; `PREREG.json` untouched). **Trading a 12-07 WINNER through K>1 does.** D-PREREG is owned by the coordinator, frozen before the 2026-12-07 read, and never edited afterwards. It must contain:
- The **complete K schedule** and promotion criteria (fills and days per stage, hold conditions), with no K chosen post hoc.
- `f_adm = 0.50`, `f_breaker = 0.25` (separate values), the cool-off (120 s from retire; **entries only**; exits exempt), the stuck definition (floor + 600 s or CONTRADICTION), and the heartbeat age (60 s).
- **Detector definition:** per-leg magnitude vs baseline with the NO-as-short-YES sign; `wire_quantity` used directly; `None` is not evaluable; confirm on a second pass; the lag guard `L_feed` (the WP0-measured value or 300 s).
- **Breaker and reset procedure:** triggers (≥2 stuck, the notional trigger, DUPLICATE_SUSPECT); an entries-only halt with exits allowed; the **reset requires the node to be down and an acknowledgement that held positions were reviewed**.
- An **AMBIGUOUS-rate halt**: stop promotion and halt if the observed rate exceeds the Wilson-upper 0.33.
- **Slippage and fee parity** against the screen ask.
- A **NO ≥ 0.90 hold-time re-measurement** as a ramp stage gate.
- **Concentration** stop criteria from the first-5 s deployed-fraction telemetry.
- **Parallel-execution fills never feed the M1-v3 verdict statistic or its look schedule.**
- The **frozen WP0 artefact hash and the chosen K's CI** at the actual cost/budget bucket.
- A statement of independence from `PREREG.json`, that no data from 2026-10-07 to 11-28 is used, and that operator caps are referenced, never assigned.

## 9. Open questions for peer review
1. D1 replaces WP-DR's UNBUDGETED latch for registered intents with a registry settle, via a named successor test and a retained unregistered variant. Is that an acceptable (non-weakening) supersession?
2. Is `L_feed` (the WP0 measurement, else 300 s) the right guard, with the second-pass confirmation?
3. Is a 60 s heartbeat age right (12 polls)?
4. Should `settle` also be used at the pre-POST release sites :6288 and :6294, where no entry is registered yet (they stay on `release_booking`, which is same-task, no `await`, so safe)?
5. `wire_quantity` is always 1 today (hard-coded). Is it worth adding for a constant, versus asserting the constant? I add it because a future multi-quantity order would silently break the detector.

## 10. Change log (every r3 finding → r4 resolution)

**Coordinator rulings.** 1 → §3.5 fresh clock, tolerance, `settle`, tests in WP3/WP4. 2 → §3.4 refusal scope. 3 → §3.6 detector, heartbeat, fail-closed read. 4 → §3.5 settle predicate and the seed-equality property. 5 → §3.5 pre-check. 6 → §3.1. 7 → §3.6 reset. 8 → §3.1 synthetic boot cool-off. 9 → §6. 10 → §8. 11 → below. WP-DR → §5.

**Architecture review (r3-A)**

| ID | Resolution |
|---|---|
| CRITICAL-1 | F11/F12; §3.5 `settle` with a fresh clock at six sites and tolerance; tests in WP3/WP4; concurrent interleavings in the exactly-once property. |
| HIGH-1 (WP-DR allowlist) | WP-DR spec names the `utc_day_for_ns` row; §5 reference; F21 corrects "helper bodies not scanned". |
| HIGH-2 (scope by slot count) | §3.4: scope keys on the configured K (`max_slots() > 1`); `test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed`. |
| MEDIUM-1 (pre-check) | §3.5: view-based roll; shares the in-lock cost function; the budget is read only when totals are non-zero; raises become denies. |
| MEDIUM-2 (WP-DR test premise) | Handled in the WP-DR spec; EXEC-PAR D1 uses the seed predicate (`ts_event` day == today) so in-process and post-restart agree. |
| MEDIUM-3 (reset needs node down) | §3.6 reset and D-PREREG. |
| Q1 conditions | The writer runs under the latch mutex and flock; reset needs the node down; the read is exception-contained and fail-closed (§3.6). |
| Q6 | Moot: WP-DR has no blanket catch (spec). Integrity errors still raise. |

**Safety review (r3-S)**

| ID | Resolution |
|---|---|
| 1 (blanket except) | The WP-DR spec has no catch; `settle` keeps integrity errors raising (`test_settle_over_cost_same_day_still_raises`). |
| 2 (allowlist row) | WP-DR spec row; §5. |
| 3 (undercount after midnight) | §3.5: `settle` adds realized when the fill `ts_event` day == today (the seed's predicate); WP-DR latches UNBUDGETED in the interim. |
| 4 (scope by count) | §3.4. |
| 5 (`qty_est` wrong for NO) | F10; §3.6: `wire_quantity` used directly; eight per-leg per-price-extreme tests. |
| 6 (stale booking) | WP-DR spec test `test_later_same_day_authorize_after_skip_raises_nothing`; the ledger prunes on the next roll. |
| 7 (pre-check vs authority) | §3.5: shared cost function; the non-day-stop type for the uncharged overrun; read-only view. |
| 8 (entry-halt liveness / fail-closed) | §3.6: heartbeat denial at K>1, the fail-closed `get`, a rollback note (§7.4). |
| 9 (raw_slots contradictions) | §3.1: a lone unreadable slot stays v2; base64; non-UTF8 is whole-table corruption; the evidence dump. |
| 10 (skip counter) | `cross_day_settles_total` in `settle`, digest in WP5b (the WP-DR interim is a log line only, per its spec). |
| 11 (entry-halt in `admission_would_refuse`) | WP6 tests. |
| 12 (`contradiction_events_total` durability) | §3.6: documented as re-detectable from durable state; `test_crash_after_detection_before_latch_redetects_after_restart`. |

**Market review (r3-M)**

| ID | Resolution |
|---|---|
| HIGH-1 (`qty_est` NO leg) | As S-5. |
| HIGH-2 ("created today") | §3.5: the seed predicate; `test_in_process_spend_equals_seed_after_restart`. |
| MEDIUM-1 (stop rule) | §6: cost/budget buckets; K per bucket; the stop at the actual bucket; the activation re-run; no worst-bucket fallback. |
| MEDIUM-2 (arm from empty) | §3.1; `test_arm_from_empty_preserves_unexpired_cooloff`. |
| MEDIUM-3 (D-PREREG gaps) | §8: all five items. |
| LOW-1 | The pre-check does not evaluate plain `spent + cost > budget`, to keep K=1 neutral. In-lock still marks the day, so the re-arm gate stops. |
| LOW-2 | The reset needs `--ack-held-positions-reviewed` (§3.6, §8). |
| Open questions 4, 5 | Synthetic boot cool-off for every slug OPEN at boot (§3.1); `L_feed`, else 300 s (§3.6). Watcher latency ≤ one poll (§3.6). |

**Plan-reviewed files:** `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r3.md`, the three r3 reviews, and `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md`.
