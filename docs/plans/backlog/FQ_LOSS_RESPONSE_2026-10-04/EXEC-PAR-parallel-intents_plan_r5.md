# PLAN r5: EXEC-PAR, bounded per-market-slug parallel submit intents (final revision)

Status: DRAFT r5 for the final peer check. Build-time only. This plan builds capability and does not re-enable orders. It was written read-only; the coordinator saves it.
Supersedes r4. All 14 coordinator rulings are adopted. §10 maps every r4 finding to its resolution. §9 lists the items that remain judgement calls.

**Delta from r4**
- The breaker-notional comparison moves **inside the ledger**, so there is no new `operator_controls` importer.
- A failed `settle` keeps the booking reachable until the outcome is decided and cannot self-heal.
- Every existing test that asserts the UNBUDGETED latch against an armed or registered intent is listed, with a successor and a retained variant.
- The pre-check never suppresses the day stop.
- `seeded_partial` is derived from the durable record under the seed's own day filter.
- The heartbeat is a single event-loop-owned breaker record, written only after a fully evaluated poll, and it carries the last resolver-pass time.
- K is forced to 1 at boot if the cost/budget bucket drifts out of the frozen bucket.

## 0. Hard invariants (binding on every WP)

1. Nautilus Trader is immutable. Extend it only through the injected `StateStore`/latch seam, native Actors/timers and native config.
2. `allow_short` stays `False`.
3. Never weaken or delete a safety, settlement, contract, NO-SEND egress-firewall or import-pin test.
   - Widen exact sets only by named rows, keeping `==`.
   - Ordering pins are rewritten only to same-strength assertions on a renamed callee.
   - A test whose asserted behaviour is deliberately superseded is replaced only by a named successor plus a retained variant of the unchanged scenario (§3.2, D1).
4. `exec/client.py` is byte-pinned. The floors never move: zero-fill 120 s, no-id 300 s, poll 5 s, backoff cap 300 s. There are **two re-pins**: WP-DR (the coordinator's, at merge) and WP4.
5. Operator caps (max daily budget, max per position = per order) are never assigned, defaulted or re-literalled. They are read only through the existing readers and never printed.
6. `BREEZY_ORDERS_ENABLED`, permit minting and `fq-v1-halt-orders-off.conf` are untouched.
7. No mypy ceiling raise. No `type: ignore`, `Any` or `cast` in new code.
8. No `PREREG.json` edit.
9. M1-v3 window outcomes and tape for 2026-10-07..11-28 are never read. Every offline tool refuses such inputs.
10. Capability build only. Trading through K>1 needs D-PREREG (§8).
11. **No new `operator_controls` importer.** The importer pin `test_operator_reserved_controls.py:708-768` (the exact `==` importer list, "WIDENED, not relaxed (L-12)") stays unchanged. No new `self._refuse` call site (the 25-site producer pin) is added.

## 1. Verified current-state facts (re-checked in code 2026-10-10)

**Store and latch**
- F1. `CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"`, `_SCHEMA_VERSION = 1` (`runtime/submit_intent.py:37-38`). `StateStore` is `get/set` only (:43-53).
- F2. `SubmitIntent.from_bytes` requires `v == 1` and ignores extra keys (:276-298). A v2 table is `SubmitIntentCorrupt` (latched) in v1 code.
- F3. `arm` refuses on OPEN or corrupt (:399-427). `retire` writes history first (:493-511). `is_latched` treats corrupt as latched (:386-397). `CorruptError` is a class attribute (:338).
- F4. The resolver context (`client.py:1094-1166`) decodes trailing-optional fields via `.get` (:1236-1262). `_note_ambiguous_open` has two call sites, :6303 (pre-POST) and :6628 (with-id overwrite). It leaves `baseline = None` on a read failure (:5983-5990).

**Submit path (`_submit_order`)**
- F5. Gates and effects, in order:
  1. refusal gate :6110;
  2. mapping check :6189-6191;
  3. permit-missing :6192;
  4. `is_latched` :6204;
  5. `_submit_veto` :6215-6218;
  6. body build :6226-6237;
  7. **permit authorise and consume** :6239-6254 (`SessionNotionalExhausted` → `_mark_budget_exhausted`, :6255-6257; durable day-stop, :5413-5438);
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
- F9. `base_slug_of` raises on an invalid slug or foreign venue (`symbology.py:298-314`).
- F10. The wire body hard-codes `"quantity": 1`, and the wire `price.value` is YES-denominated, so `1 − price` on the NO leg (`submit_chain.py:363-373`). `order_notional_usd = instrument price × order quantity` (:245-246).

**Ledger calls and clocks**
- F11. **Ledger calls after booking.**
  - Resolver: `true_up_booking` :3231 (zero-fill, after `_retire`), :3408 (accept-fill, before `_retire` :3429), :4072 (no-id, after `_retire`). All three **pop `_ambiguous_bookings` before the ledger call** (:3226, :3405, :4069).
  - Post-POST in `_submit_order`: `true_up_booking` :6467 (inside the `else:` of the `record_fill` try, uncaught), :6555, `release_booking` :6570.
  - Pre-POST: `release_booking` :6288, :6294, :6319. :6288 and :6294 sit in the same synchronous span as `authorize_order_cost` (:6276).
- F12. **Stale clocks at K>1.**
  - The post-POST sites reuse the :6109 clock across the POST `await`.
  - The resolver sites use `now_ns` captured at :3013 or :3750, before further awaits.
  - `authorize_order_cost` sets `_last_ns = now_ns` (`operator_controls.py:426`). `_require_open_booking` raises if `now_ns < _last_ns` (:438-441) or `booking.day != utc_day_for_ns(now_ns)` (:443-447).
  - At K=1 nothing authorizes during an await. At K>1 any concurrent authorize or day roll makes the later true-up or release raise (for :6467 the exception escapes the task).
- F13. Resolver-path fills are stamped `ts_event = now_ns` (discovery time, `client.py:3372-3383`). The create-path fill carries the venue time. The boot seed buckets by `ts_event` day (:2418) and sums raw `cumulative_cost` (:2420) without filtering `order_side`. In-process `true_up_booking` rounds realized cost up to the cent (`operator_controls.py:508`).
- F14. Boot order in `_connect`:
  1. the first resolver pass is awaited (:2174);
  2. the periodic resolver task is created (:2184-2196);
  3. `_reconcile_submit_intent` (:2312);
  4. `_seed_spend_from_durable_fills` (:2370; `now_ns` at :2402; early `return` at :2422 when zero fills);
  5. `_spend_seeded = True` (:2223).
  - There is no `await` between 3 and 5. Fill handlers are synchronous, so each is wholly before or wholly after the span.
- F15. `_RESOLVER_FILL_UNBUDGETED` has **one** producer, `self._refuse` at :3466 (condition :3460-3464: `booking is None and order_side != "SELL" and _spend_seeded`). The "third `_refuse` site" wording in `test_polymarket_us_exec_client.py:748` means the third `_refuse` in that function.
- F16. `_resolver_contradiction_details` exists (:1959, :3965, :4038), is surfaced at :2531 and is popped at `_retire` (:5924). `_resolver_leg_holding_qty` (:1531) gives the per-leg absolute magnitude. The same-day branch at :3125 only logs.
- F17. `seed_permit_budget_from_prior_spend` is once per permit and one-way (`safety.py:799-841`). D3: a permit restore happens only with `booking is not None` (:3226-3250).
- F18. The submit throttle `output_drop=self._deny_new_order` (`risk/engine.pyx:140-150`) is a drop, upstream of `_submit_order`. `max_order_submit_rate = "5/00:00:01"` (`node_config.py:698`). Free-balance denial is per order (`engine.pyx:949`). In-flight checks stay off (`node_config.py:876-901, 1036`).
- F19. `_submit_veto: Callable[[], str|None]` is read only at :6215. `exit_wiring.py:278` separately refuses on `is_family_halted()`.
- F20. The supervisor marker is `supervisor_decode_marker.py:36-155`, written at `trade_supervisor.py:2939`, read once at node boot (`node_config.py:1007`). A live-node WAL read from the supervisor has precedent (`trade_supervisor.py:509-520`).
- F21. The resolver helper bodies `_resolve_terminal_zero`, `_resolve_accept_fill` and `_resolve_no_id_intent` are in `EXEC_RESOLVER_COROUTINES` (`test_execution_egress_firewall_guard.py:2113-2130`) and are scanned. `self._clock.timestamp_ns` and `self._note_resolver_error` are already permitted.
- F22. **WP-DR worktree (implemented, commit pending).**
  - The diff in `.claude/worktrees/agent-a06ff6c5f14021f97` pops the booking first at each of the three sites.
  - It then skips the ledger call when `booking.day != utc_day_for_ns(now_ns)`.
  - On the accept-fill path it additionally sets `booking = None`, so the existing UNBUDGETED producer fires.
  - It adds the `utc_day_for_ns` firewall row, no `except`, and no new `_refuse`.
- F23. The cross-process UNBUDGETED tests today:
  - `test_edge2_ac6b_cross_process_fill_budget.py`: `test_cross_process_accept_fill_latches_unbudgeted_refusal` (:203, asserts :236); `test_cross_process_no_leg_buy_fill_latches_unbudgeted_refusal` (:246, :276); `test_legacy_context_without_order_side_refuses_as_a_buy` (:284, :324); `test_unbudgeted_refusal_precedes_the_order_unknown_early_return` (:544, :579). The exemption assertion `UNBUDGETED not in` at :456 stays green.
  - `test_ambig_no_id_resolver.py::test_cross_process_sigterm_mid_post_untracked_fill_is_adopted_and_recorded` (:582, asserts :612).
  - `test_ambig_latch_resume.py:485-500` calls `_refuse` directly and is unaffected.
  - A repo-wide sweep (`tests/`, `scripts/`) found no others.

**Consumers of intent state (complete sweep)**
- The exec client: :2670, :3197, :3274, :3339, :3502, :4063, :4106 (`current_open`); :6204, :6785 (`is_latched`); :1838, :3747, :6325, :6349 (in-flight id).
- `trial_day_latch.py:732, 753`; `continuous_strategy.py:1713, 1918, 2496, 2600, 2739`; `continuous_no_side.py:309`; `exit_wiring.py:183`; `exit_guard.py:163-192` (no live caller).
- `trade_supervisor.py:431-501` and consumers :1298-1307, :1361-1377, :1476, :1866; marker write :2939; `clear_submit_intent_cli.py:125`.
- `prelaunch_intents.py:50-70`; `scripts/analysis/score_live_trials.py:190, 383-410, 531`; `scripts/ops/ambig_latch_phase_a_check.py`; `trade_cli.py:432, 538`.
- `forecast_quantile_ladder` uses its own `QuantileLadderLatch` and gains the benefit through the exec client. `fill_time_count.py` reads no singleton (WP0 re-verifies).

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
| A timer-driven watcher on the node loop | Yes: `Actor` with `clock.set_timer` (the `FeeDriftProbeActor` precedent) | Used. No thread. |

Options B (anonymous slots), C (queue) and D (second router) are rejected as before.

## 3. Design

### 3.1 Storage: one atomic table at `CURRENT_INTENT_KEY`
- **Encoding.**
  - v1 bytes whenever ≤1 slot is open **and no unreadable slot exists**. A 0→1 arm never writes v2.
  - A lone unreadable slot stays v2.
  - v2 is `{"v":2,"slots":{<key>:<intent record incl. slug>},"raw_slots":{<key>:<base64>},"cooloff":{<slug>:<until_ns>}}`, written only while ≥2 slots are open (counting unreadable ones) or an unreadable slot exists, and only when the v2 predicate holds.
- `SubmitIntent` gains a trailing optional `slug: str | None = None`, emitted only when set. A K=1 arm uses `slug=None`, so the bytes are identical to today.
- Every arm or retire is **one atomic `set`** of the whole table under the existing mutex and flock. History-first retire is unchanged. `reconcile_at_startup` copies history over matching slots.
- **Unreadable slots.**
  - A slot whose JSON value fails record validation is stored in `raw_slots` as **base64 of its canonical JSON text** and re-emitted identically by every later arm or retire.
  - The decoder uses strict base64 (`validate=True`). **A bad `raw_slots` entry is a whole-table corruption** (latched, existing CLI path), never a silent drop. A table that is not valid UTF-8 JSON is likewise whole-table corruption.
  - An unreadable slot counts as OPEN, never downgrades the table, and quarantines admission (which also denies exits). The first one logs ERROR once and is exposed through a client property.
  - **Recovery CLI** `--slot-key KEY --ack-unreadable-slot` (node down):
    - `KEY` is validated against `[A-Za-z0-9._-]{1,128}|\?:[0-9a-f]{32}` (rejecting `/` and `..`).
    - The evidence file name uses a SHA-256 prefix of the key, never the key itself: `<store>.unreadable_slot.<sha256(key)[:16]>.<ts>.bin`.
    - It is created mode `0600` and **fsynced, along with its directory**, before the slot is removed. The CLI aborts if the dump fails.
    - It stores the **original table bytes exactly as read** (not re-serialised), with a header naming the key and carrying the slot's canonical JSON for convenience (labelled canonicalised).
- **Cool-off.**
  - It is durable in `cooloff`, measured from `retired_ns`, and carried as an extra `cooloff` key on a v1 record (v1 readers ignore it).
  - **An arm from an empty (v1 RETIRED) table preserves unexpired `cooloff` entries.**
  - It applies to entries after zero-fill, no-fill and fill retires, never to exits.
  - **Every slug OPEN at boot gets a synthetic cool-off from boot time.**
  - K=1 mode writes none, so its bytes stay identical.
- Legacy adoption: a slug-less OPEN record takes `AmbiguousResolverContext.wire_market_slug`. A missing context uses key `"?:<intent_id>"`, which quarantines.

### 3.2 Ordering, predicate and neutrality
- WP5a (supervisor decode, marker capability, CLI tolerance, analysis readers) deploys **before any v2 write**. The marker gains a trailing-optional `slot_schema_versions`, and `supervisor_admits_slot_schema(store_path, 2)` uses the live-pid and start-ticks check.
- The v2 predicate is evaluated on every would-be 1→2 transition. It is **exception-contained and returns False on error**. It is evaluated inside `admission_refusal` (before any spend) and again in `arm_slot` (the arbiter). A False result is a WAIT.
- **K_eff := the configured K constant**, further reduced to 1 only by the boot-time bucket check (§3.9). It is never derived from the predicate.
- **Neutrality statement.** With K=1 the system is behaviourally identical to today **except the enumerated deltas**. WP-DR and WP4 are non-neutral merges; WP0-WP3 are inert; WP5a/5b/6 are neutral at K=1. No heartbeat or breaker record is written at K=1.

| Delta | Effect at K=1 | Test |
|---|---|---|
| D0 (WP-DR) | A midnight-crossing retire completes; a new-day accept-fill against a prior-day booking latches UNBUDGETED. | the WP-DR spec's tests |
| D1 (WP4) | A fill against a *registered* intent settles through the registry, adding the realized cost once, instead of latching UNBUDGETED. **Gated on `test_in_process_spend_equals_seed_after_restart`.** | §3.7 and the table in WP4 |
| D2 (WP4) | Open exposure surviving a roll or a restart keeps counting against headroom. | `test_booking_survives_day_roll_with_open_slot` |
| D3 (WP4) | `_refuse` dedupes on `(reason, instrument)`. | identical outputs at `instrument=""` |
| D4 (WP4) | `_post_in_flight_intent_ids` is a frozenset. | existing in-flight tests |
| D5 (WP4) | Ledger calls after booking go through `settle` with a fresh clock. | `test_settle_same_day_equals_true_up_and_release` (property) |
| D6 (WP4) | The context blob gains trailing-optional `wireQuantity`; old blobs decode `None`. A quantity-equality deny is added (never true today). | the wire-quantity tests; WP4 sweeps blob-byte comparisons |

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
5. `_submit_veto`, the body build, then two comparisons (no calls beyond the allowlisted `submit_chain.order_quantity_decimal`):
   - `if body["marketSlug"] != slug: return self._deny(...)`;
   - `if body["quantity"] != submit_chain.order_quantity_decimal(order): return self._deny(...)`. This pins the wire quantity to the order quantity for both `_note_ambiguous_open` call sites, which receive the same `body` and `order`.
6. Permit spend, `authorize_order_cost` (the in-lock checks are **the authority**), `_intent_reconciled`, `arm_slot` (re-runs `admit`), `register_open_exposure`, `_note_ambiguous_open`, POST.

`admission_refusal` evaluates, in order:
- quarantine (denies exits);
- the v2 predicate on a would-be 1→2 transition;
- **the breaker record** (K>1 only; entries only; **one store `get`** serves the halt flag and the heartbeat, §3.6);
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
- `test_breaker_record_store_raise_or_garbled_denies_entries_not_raises`;
- `test_stale_heartbeat_or_stale_resolver_pass_denies_entries_at_k_gt_1_only`;
- `test_inlock_bound_race_after_passing_precheck_is_plain_deny` (the permit slot may burn once; no day-stop).

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
  - The loop top records `self._resolver_last_pass_ns = self._clock.timestamp_ns()` (a plain attribute, an allowlisted callee), exposed as a property.
- **H7 by-id guards (:3197, :3339, :4063)** use `self._latch.is_open_intent(intent_id)`.
- **Slug plumbing.** The three resolver bodies receive `slug=current.slug or ""` from the `SubmitIntent` record.
- **Refusal scope.** At each AMBIGUOUS append (:6333, :6580): `self._refuse(AMBIGUOUS_REASON, instrument=slug if self._latch.max_slots() > 1 else "")`.
  - **Scope keys on the configured K**, so a lone ambiguous order at K>1 is scoped and other slugs proceed. K=1 stays unscoped.
  - The scope is stored on the `ClassifiedRefusal` and pinned `RefusalClass.DURABLE`.
  - `_refuse` dedupes on `(reason, instrument)` (keyword-only; pin-neutral, `test_exec_refusal_health_surface.py:182-291`).
- **H8 clears (:3274, :3502, :4106).** Remove AMBIGUOUS refusals scoped to `slug`, and also the unscoped AMBIGUOUS refusal if `self._latch.open_slot_count() == 0`.
- **Tests.**
  - `test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed`;
  - A ambiguous, B ambiguous, A retires: B's refusal survives;
  - `_map_position` success on A never clears A's AMBIGUOUS;
  - a K=1 unscoped refusal clears only when no slot is open.
- `resume_if_refusals_cleared` keeps `is_latched()`.

### 3.5 Exposure accounting
Additive `DailySpendLedger` methods in `operator_controls.py`. The existing public methods, their "previous UTC day" refusals and their tests are unchanged.

**Refactor.**
- `_true_up_locked(booking, filled, eff_now)` and `_release_locked(booking, eff_now)` carry the existing bodies, **including the input validation** (exact `Decimal`, finite, ≥0, cent-up rounding, `realized ≤ booking.cost`) **and the call `_require_open_booking(booking, now_ns=eff_now)`**. They therefore keep the "unknown, released or already trued-up" integrity errors.
- The public `true_up_booking` and `release_booking` become **thin wrappers** that take the lock and pass the caller's `now_ns`, so the existing day-rule and rewind tests are unchanged.

**API**
- `register_open_exposure(key, notional_usd | None, *, booking | None, seeded_partial_usd, now_ns)`. It stores the booking on the entry. Charged iff a same-day booking is given. A `None` notional adds `key` to a **per-key** `_unknown_keys` set.
- `mark_ambiguous(key)`. Called at :6333 and :6580 and for every boot-registered intent.
- `settle(key, *, booking | None, realized_usd | None, fill_ts_ns | None, now_ns) -> bool`:
  - `eff_now = max(now_ns, _last_ns, _registry_last_ns)`. **It tolerates non-monotonic `now_ns`.**
  - **Unregistered key with `booking=None`: a no-op returning False** (so `_retire`'s idempotent `settle(key, booking=None, realized=None)` after a handler's settle is safe). **A settle that carries a booking for an unregistered key, a mismatched booking, or a double settle raises** the same integrity error as the wrappers.
  - **Same-day live booking:** `_true_up_locked` (realized set) or `_release_locked`. Genuine integrity errors raise exactly as today.
  - **Prior-day booking or uncharged entry:** add `max(round_up(realized) − seeded_partial, 0)` to `_spent_usd` iff `realized` is set and **the fill record's `ts_event` day == `eff_day`** (the seed's own predicate).
  - It is **atomic**: validation precedes mutation, so a raise leaves the entry and booking intact.
  - It removes the entry on success, returns True iff the key was registered, and increments `cross_day_settles_total`.
- `has_open_exposure`, `uncharged_open_total`, `ambiguous_open_total`, `unknown_key_count`.
- **`breaker_fraction_exceeded(f: Decimal | None = None) -> bool`.**
  - It returns False without reading the budget if `ambiguous_open_total() == 0`.
  - Otherwise it reads the budget with the existing reader and returns `ambiguous_open_total > f × budget`.
  - **Any raise (unset control, clock) counts as tripped (True).**
  - `f=None` uses the ctor-injected `breaker_fraction`. It adds no `operator_controls` importer.
- Day roll: `_roll_locked(eff_now)` is the existing pruning code, except that surviving **open** entries convert to uncharged instead of being dropped. It only rolls forward.
- The fractions reach the ledger through exec-client config fields (set in the runtime layer, consumed by `factories.py`, an existing declared importer), since `adapters` cannot import `runtime`.

**Invariant**: at every `authorize_order_cost`, `spent_today + uncharged_open + cost ≤ budget` and `ambiguous_open_total + cost ≤ f_adm × budget`.
- `f_adm = 0.50` and `f_breaker = 0.25` are Breezy-owned `Final` constants. `None` means the bound is off.
- **In-lock exceptions.**
  - The existing `spent + cost > budget` raises `DailyBudgetExhausted` (day-stop, unchanged).
  - If that passes but `spent + uncharged + cost > budget`, or the AMBIGUOUS bound fails, it raises the non-day-stop `OpenExposureBoundExceeded(LiveTradingPermissionError)`.

**Pre-check** `exposure_admission_refusal(price_usd, quantity, now_ns) -> str | None`:
- Genuinely read-only: it takes the lock and **computes the roll on a view**.
- It uses the **same cost function** as the in-lock path (cent-up).
- **It returns `None` whenever plain `spent + cost > budget`**, so the in-lock check raises `DailyBudgetExhausted` and the durable day-stop marker is written as today. `test_precheck_defers_to_inlock_day_stop_when_uncharged_positive_and_budget_exhausted`.
- It reads the budget only if the uncharged, ambiguous or unknown totals are non-zero (`unknown > 0` denies without reading it). A `LiveTradingPermissionError` becomes a returned deny reason with no marker.
- Otherwise it denies only on the new conditions.

**Fresh clock, shared stamp.**
- Every ledger call after booking (three post-POST sites, three resolver sites) takes one fresh `self._clock.timestamp_ns()` read just before the call.
- In `_resolve_accept_fill` that same read is also the `ts_event` of the resolver-stamped fill record and the `fill_ts_ns` passed to `settle`, so the record day and `eff_day` cannot disagree (a 23:59:59.9 discovery is stamped and settled on the same day).

**`seeded_partial_usd` derivation (H6).**
- From the durable fill record `FILL_KEY_PREFIX + venue_order_id` read at registration, using the seed's own day filter: `P = record.cumulative_cost` iff `utc_day_for_ns(record.ts_event) == seed_day`, else **0**. `seed_day` is the `today` computed in `_seed_spend_from_durable_fills` (it stores `self._seed_day`).
- **A no-id intent (`venue_order_id == ""`) has no lookup: P = 0.** A record landing after registration cannot exist at boot (a crash after `record_fill` before `_retire` retires on fingerprint match in `reconcile_at_startup`).
- Tests:
  - `test_seeded_partial_zero_for_prior_day_record`;
  - `test_seeded_partial_zero_for_no_id_intent`;
  - `test_prior_day_partial_then_today_final_fill_counts_full_realized`;
  - `test_today_partial_then_final_counts_realized_once`.

**Boot (H6).**
- In the no-await span between the seed and `_spend_seeded = True`, register every still-OPEN intent as uncharged and marked ambiguous, with the context's `notional_usd − P` (`None` notional if there is no context).
- A registration exception propagates out of `_connect` (fail closed, as the seed does). `test_boot_registration_failure_fails_connect_closed`.
- Permit seeding is **unchanged** (durable fills only). No permit restore happens for these (D3).

**Retire and the integrity-error path (ruling 2).**
- The three resolver sites and the three post-POST sites call `settle` **before** removing anything from `_ambiguous_bookings`. They use `.get(...)` first and `.pop(...)` only after `settle` returns, so the booking stays reachable until the outcome is decided.
- **Accept-fill handler, `settle` raises (same-day integrity error: over-cost, double settle, unknown booking):**
  - log ERROR with the exception type and count it via `_note_resolver_error`;
  - set `settle_failed`, force the unbooked path (`registered = False`, `booking = None`);
  - abandon the registry entry with `settle(key, booking=None, realized_usd=None)`, which adds no spend (the authorized cost stays charged, which is conservative);
  - fall through to the existing `_retire` and the single existing UNBUDGETED producer (F15), which latches the global DURABLE refusal.
  - The visible end state is today's (retired plus global halt) in one pass. **It cannot self-heal**: no later pass adds the realized cost. A respawn re-seeds correctly.
  - *Why not abort and retry:* a perpetually OPEN intent would keep the slug's slot held (blocking the exit of a held position) and would make the latch unreachable without a new `_refuse` site (a pin move). See §9, item 1.
- **Zero-fill and no-id sites (after `_retire`):** a raise propagates exactly as today (counted by `_note_resolver_error`); the booking stays in the dict (a harmless leak, since the intent is already retired); the AMBIGUOUS clear is skipped (conservative).
- `registered` is captured from `settle`'s return **before** `_retire`. The UNBUDGETED condition becomes `not registered and booking is None and order_side != "SELL" and _spend_seeded`.
- **Interaction with WP-DR (F22).** WP-DR pops first and forces `booking = None` on a prior-day accept-fill. WP4 replaces the three inline skips with `settle` (which carries the day logic), replaces the pop-first ordering with get-then-pop, and replaces the forced `booking = None` with `registered`. Until WP4 merges, WP-DR's behaviour stands.

**Exactly-once property** (hypothesis), restricted to **BUY records**, rounding **both sides cent-up identically**:
- over any interleaving of seed, register, partial, full fill, zero-fill, day roll and settle, including two concurrent tasks with stale and fresh `now_ns`, and midnight crossings;
- each fill's cost counts once in `spent_today`, open exposure is never dropped before settle, and partials net out;
- at quiescence the in-process `spent_today` equals the seed's total over the same records (`test_in_process_spend_equals_seed_after_restart`).
- *Documented, accepted, pre-existing exceptions (the seed is not changed):* the seed sums raw `cumulative_cost` and includes SELL (exit) records (F13), so it is conservative-high relative to in-process. The production difference is ≤1 cent per BUY fill, plus the SELL records, always in the safe direction.

### 3.6 Breaker
Frozen numbers for the first K>1 deployment (restated in D-PREREG):
- **Stuck** = an AMBIGUOUS open intent with age > `floor + 600 s` (with-id 720 s; no-id 900 s), or any intent with a recorded CONTRADICTION.
- **Trip** at ≥ 2 stuck, **or** the client property `ambiguous_notional_breaker_tripped` (= `ledger.breaker_fraction_exceeded()`, `f_breaker = 0.25 < f_adm = 0.50`), **or** a DUPLICATE_SUSPECT.
- **Duplicate detector: a belt for stuck slots, not a general double-POST detector.**
  - It is evaluated only on intents old enough to pass the lag guard, so most AMBIGUOUS intents (which retire at about 125-144 s) are never examined.
  - A duplicate on a normally resolving order is caught only by the cool-off and positions reconciliation. This framing is repeated in D-PREREG.
  - New trailing-optional `wire_quantity: str | None` on `AmbiguousResolverContext` (AR-N6 pattern; JSON key `wireQuantity`), written from `str(body["quantity"])` at both `_note_ambiguous_open` sites.
  - On each pass with eof-complete positions and a baseline:
    - `venue_leg_qty = _resolver_leg_holding_qty(positions, slug, leg)`;
    - the baseline leg magnitude comes from `baseline_venue_net` with the NO-as-short-YES sign (`yes: max(net,0)`, `no: max(−net,0)`), via a pure `_leg_magnitude_of_signed_net`;
    - suspect iff `venue_leg_qty − baseline_leg_qty > Decimal(wire_quantity)`. **No division by the wire price.**
  - `None` baseline, leg quantity or `wire_quantity` is **not evaluable** (it resets the counter; never trips or crashes).
  - **Lag guard:** age ≥ `L_feed` (the WP0-measured positions-feed lag bound, else **300 s**) and **confirmation on a second consecutive pass**.
  - A duplicate that adds no more than one order's quantity is undetectable (exposure stays cap-bounded).
- **Sticky until operator reset.**
  - `contradiction_events_total` is a monotonic in-memory counter. The watcher latches the halt on any increase, and the latch survives the `_retire` pop.
  - *Durability:* a crash between detection and the latch loses only the in-memory event. Detection is a pure function of durable state (the context baseline) plus the venue positions, so it re-fires after restart within `L_feed` plus two passes.
- **The breaker record `…/intent/breaker`** (one key, one writer):
  - `{"v":1,"halted":null|{"reason","ts_ns"},"hb_ns":int,"resolver_pass_ns":int}`.
  - The watcher is the only writer, through latch methods under the latch mutex (read-modify-write preserves `halted`). Only the reset CLI (node down) rewrites `halted` to `null`.
  - **Watcher = a native `Actor` with a timer on the node's event loop** (the `FeeDriftProbeActor` precedent), registered through `_FamilyComposition.extra_actors`. It is **registered only when K>1**, so **K=1 has no heartbeat or breaker writes** and the golden-bytes test is unaffected.
  - Each timer tick (every 5 s, so latch latency is ≤ one poll) evaluates every trigger. **It writes `hb_ns` and `resolver_pass_ns` only after the whole evaluation completes without raising** (`test_heartbeat_not_written_when_poll_evaluation_raises`). `resolver_pass_ns` is read from the client property.
  - `admission_refusal` (K>1 only), from the **single** `get`, denies entries when:
    - the record is absent more than 60 s after boot;
    - the `get` raises, or the value is garbled or undecodable;
    - `halted` is set;
    - `now − hb_ns > 60 s` (12 polls);
    - `now − resolver_pass_ns > 600 s` (2 × the 300 s backoff cap, so a venue-wide 5xx backoff does not false-trip, while a dead resolver task does).
  - **Dead-watcher alert.** The adapter cannot alert, so a **supervisor-side check** in an existing periodic supervisor tick (WP5b identifies which; WP5b adds `probe_breaker_record(store_path)`, a read-only WAL read with the §1 F20 precedent) emits the alert through the existing sink when K>1 and the heartbeat or resolver-pass age exceeds its bound while the node is live.
  - *Contention:* heartbeat writes at 5 s go through the latch mutex into the same store. `test_heartbeat_write_does_not_block_arm_slot`. They are not coalesced (the cadence is already the minimum that bounds latency).
- **Effect: entries only.**
  - No family-halt key and no veto are used, so `_submit_veto`'s signature, `family_halt_submit_veto`, `FqComposedVeto` and `exit_wiring.py:278` are untouched. **No pin changes.**
  - Exits stay allowed, because the breaker trips exactly when held positions may need selling.
  - The watcher alerts the operator with the held-position list (from the resolver-refreshed startup-position evidence) and any stuck slot on a slug that has a held position (a stuck entry blocks that slug's exit, as today). It needs a new `AlertDetail` member (the exhaustive-enum pin is checked in WP5b).
- **Operator reset (`--reset-entry-halt`):** it takes the intent flock, so it **requires the node to be down**, and it requires `--ack-held-positions-reviewed`.
  - The cost of that restart (the resolver and exits are unavailable for the restart window) is recorded in D-PREREG. An in-node reset is rejected: it would add an in-node command surface with a write path.
- **The breaker never blocks the resolver.** The resolver reads neither the record nor the veto.

### 3.7 D1 supersession: complete test sweep
After WP4 every in-process intent is registered at arm and every intent OPEN at boot is registered by H6. The UNBUDGETED latch therefore cannot fire for them. It is **retained as defence-in-depth** for a missing registry entry (a registry bug), which tests reach through a ledger double whose `register_open_exposure` is a no-op. D1 is **gated on `test_in_process_spend_equals_seed_after_restart` passing**.

| Existing test (asserts the latch) | Named successor (same commit): `spent_today` rises by exactly the realized amount, once, no latch | Retained original scenario (registry double, unregistered) |
|---|---|---|
| `test_cross_process_accept_fill_latches_unbudgeted_refusal` (ac6b :203) | `test_cross_process_accept_fill_of_registered_intent_adds_spend_once_no_latch` | `test_cross_process_accept_fill_unregistered_intent_latches_unbudgeted_refusal` |
| `test_cross_process_no_leg_buy_fill_latches_unbudgeted_refusal` (:246) | `test_cross_process_no_leg_buy_fill_of_registered_intent_adds_spend_once_no_latch` | `..._unregistered_intent_latches_unbudgeted_refusal` |
| `test_legacy_context_without_order_side_refuses_as_a_buy` (:284) | `test_legacy_context_registered_counts_as_a_buy_once_no_latch` | `test_legacy_context_unregistered_refuses_as_a_buy` |
| `test_unbudgeted_refusal_precedes_the_order_unknown_early_return` (:544) | `test_registered_order_unknown_intent_adds_spend_once_then_early_return_no_latch` | `..._unregistered_latch_precedes_the_order_unknown_early_return` |
| `test_cross_process_sigterm_mid_post_untracked_fill_is_adopted_and_recorded` (no-id :582, assert :612) | `test_registered_no_id_adopted_fill_adds_spend_once_no_latch` | `..._unregistered_latches_ac6b` |

- The exemption assertions (`UNBUDGETED not in`, ac6b :456) stay green unchanged.
- The retained variants carry a comment: production reaches the latch only via a registry failure.
- The WP-DR spec's `test_accept_fill_after_midnight_retires_once_and_latches_fill_unbudgeted` gets the same successor in the same commit, and keeps its unregistered variant.

### 3.8 Exits and quarantine
- Exits are K-exempt only when K>1, and always slug-exclusive. At K=1 they behave as today. Quarantine denies exits (as `is_latched` does today).
- `exit_guard.assert_settlement_close_permitted` gains an optional keyword `refusal_scopes`; the existing signature and tests are untouched. The client exposes `trading_refusal_scopes`.
- `exit_wiring.check_exit_intent_for_ambiguous_send` (:183) uses `TrialDayLatch.open_submit_intents()` and matches by fingerprint.

### 3.9 Bucket drift guard and venue constraints
- **Bucket derivation (value-free).** A ledger method `cost_budget_bucket() -> str` reads both operator readers (existing importer) and returns only a label from a fixed ordered list {≤0.02, 0.05, 0.10, 0.25, 0.50}. Because realized order cost ≤ the per-position cap, it derives the **upper** bound from `cap / budget`.
- **At `_connect` when the configured K>1:** `_connect` compares the label with the D-PREREG-frozen label (a `Final` in `node_config.py`, passed through config). If the label exceeds it, **or the derivation raises**, the client calls `self._latch.force_k1(reason)`. `max_slots()` then returns 1, an ERROR is logged, and the watcher alerts via the `k_forced_to_1_reason` property. This needs no prereg edit. Test: `test_bucket_outside_frozen_label_forces_k1_and_alerts`.
- Resolver GET load is unchanged, with an added latency of ≤ (K−1)×5 s. No new WS subscriptions (the cap of 10 is shared). `subscribe_trades` stays off (test). The throttle comment at `node_config.py:681-698` is rewritten (the value is not raised).

## 4. Re-pin procedure
Edit **only** `_EXEC_CLIENT_SHA256` (`tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`) after `python-reviewer` and `prediction-market-reviewer` approve the diff, appending `# re-pinned <date>: <WP>, reviewer-approved`. `test_autonomy_envelope.py:901-916` reads it by AST. An implementer never edits the pin.

## 5. Work packages (TDD order)

**Order:** WP-DR → WP0 → WP1 → WP2 → WP3 → WP5a → [supervisor restart, marker verified] → WP4 → WP5b → WP6 → WP7.
- Common gate: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -m pytest --basetemp=~/.cache/...`; `lint-imports` from the tree's cwd ("N kept, 0 broken"); `ruff`; `mypy` (no ceiling change); the full gate `scripts/ci/run_tests_no_egress.sh` after every merge, reading the exit code before any push.
- Every focused list includes the firewall guard, the exec-client, latch, ambiguous-resolver and AC6b tests, `test_operator_reserved_controls.py` and `test_operator_control_assignment_scan.py`, the refusal-health-surface test, the pin tests, `tests/contract/test_live_fill_scoring_chain_contract.py` and all `test_autonomy_*`.
- Briefs state the exact interpreter, no `uv run`/`pip`/`git stash`, own scratchpad, format only your own files, and worktree `PYTHONPATH` first.

### WP-DR (prerequisite; authoritative spec, not redesigned here)
The day-roll settle fix is specified in `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md` and implemented in the worktree `/home/jon/breezy/.claude/worktrees/agent-a06ff6c5f14021f97` (commit pending; see F22). EXEC-PAR treats it as merged and builds on it as described in §3.5 ("Interaction with WP-DR") and §3.7.

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
- `test_build_gate_requires_a_bucket_at_or_above_0_05`;
- `test_per_bucket_order_cost_distribution_reported`;
- `test_cluster_bootstrap_ci_upper_bound_stop`;
- `test_first_5s_budget_fraction_arm`;
- `test_stuck_slot_reduces_effective_k`;
- `test_yes_and_no_share_one_slot`;
- `test_hold_constants_match_exec_client_source_ast`;
- `test_caps_read_only_bucket_label_only_never_printed_or_assigned`;
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
  - `test_bad_base64_in_raw_slots_is_whole_table_corruption`;
  - `test_lone_unreadable_slot_stays_v2`;
  - `test_last_healthy_retire_does_not_downgrade_over_unreadable_slot`;
  - `test_unreadable_slot_quarantines_but_healthy_slot_resolvable`;
  - `test_legacy_open_adopted_by_context_slug`;
  - `test_legacy_open_without_context_quarantines`;
  - `test_every_slug_open_at_boot_gets_synthetic_cooloff`;
  - `test_v2_predicate_false_or_raising_refuses_one_to_two`;
  - `test_breaker_record_single_get_fail_closed_read_and_halted_preserved_across_heartbeat`;
  - `test_force_k1_makes_max_slots_one`;
  - `test_concurrent_arm_slot_one_winner_per_slug`;
  - `test_is_open_intent_open_slot_count_max_slots`.

### WP3: ledger API (inert)
- RED (`test_daily_spend_ledger_open_exposure.py`; the existing day-rule tests are untouched):
  - `test_settle_same_day_equals_true_up_and_release` (property);
  - `test_settle_same_day_unknown_or_double_booking_still_raises`;
  - `test_settle_unregistered_key_with_no_booking_is_noop_false`;
  - `test_settle_unregistered_key_carrying_a_booking_raises`;
  - `test_settle_is_atomic_on_raise`;
  - `test_public_true_up_and_release_wrappers_unchanged`;
  - `test_concurrent_authorize_during_post_await_does_not_break_true_up`;
  - `test_concurrent_authorize_during_post_await_crossing_midnight_settles_via_registry`;
  - `test_settle_tolerates_stale_now_ns_never_raises_clock_backwards`;
  - `test_settle_over_cost_same_day_still_raises`;
  - `test_open_exposure_survives_day_roll_as_uncharged`;
  - `test_settle_after_roll_before_next_authorize`;
  - `test_settle_uncharged_adds_realized_minus_partial_iff_ts_event_day_is_today`;
  - `test_in_process_spend_equals_seed_after_restart` (property: BUY records, cent-up on both sides, concurrent tasks, day-roll interleavings);
  - `test_exactly_once_over_all_interleavings_incl_partials_and_concurrent_tasks`;
  - `test_unknown_notional_is_per_key`;
  - `test_precheck_is_read_only_view_roll`;
  - `test_precheck_uses_inlock_cost_function_boundary_to_the_cent`;
  - `test_precheck_defers_to_inlock_day_stop_when_uncharged_positive_and_budget_exhausted`;
  - `test_precheck_reads_budget_only_when_totals_nonzero`;
  - `test_precheck_budget_unset_or_clock_rewind_is_deny_no_marker`;
  - `test_uncharged_overrun_raises_non_day_stop_type`;
  - `test_ambiguous_bound_counts_only_marked_ambiguous`;
  - `test_breaker_fraction_exceeded_false_without_reading_when_no_ambiguous`;
  - `test_breaker_fraction_exceeded_true_on_any_raise`;
  - `test_cost_budget_bucket_returns_label_only`;
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
  - `test_clear_cli_rejects_slot_key_with_path_characters`;
  - `test_clear_cli_unreadable_slot_requires_key_ack_and_dumps_original_bytes_0600_fsynced_first`;
  - `test_clear_cli_evidence_filename_uses_key_hash_not_key`;
  - `test_clear_cli_aborts_if_evidence_dump_fails`;
  - `test_clear_cli_refuses_erasing_table_over_open_slots`;
  - `test_clear_cli_reset_entry_halt_requires_node_down_and_ack_held_positions`;
  - `test_score_live_trials_v2_open_not_absent`;
  - `test_prelaunch_observation_v2_open_is_ambiguous`;
  - `test_rollback_drill_after_drain_and_reset_old_reader_sees_valid_v1_retired`.
- Deploy: merge, restart the supervisor, verify the marker field.

### WP4: exec client (byte-pinned; NON-NEUTRAL D1-D6; re-pin #2)
- Hunks: H0, the §3.3 gates (including the two body comparisons), `arm_slot`, `register_open_exposure` and `mark_ambiguous`, H5 (including `_resolver_last_pass_ns`), slug plumbing, H6 (seed-day and `seeded_partial`), H7, H8, `settle` at all post-booking sites with get-then-pop and the integrity-error path (§3.5), the UNBUDGETED condition, `_refuse` scope and dedupe, `wire_quantity`, the detector, the shared-clock stamp, `force_k1` and the bucket check, and the properties (`trading_refusal_scopes`, `contradiction_events_total`, `ambiguous_notional_breaker_tripped`, `resolver_last_pass_ns`, unreadable slots, open-intent ages, held-position inputs, `k_forced_to_1_reason`).
- **Named allowlist rows (keep `==`; each checked against the `read/send/post/request` banned-word scan).**
  - Order coroutine: `base_slug_of`; `self._latch.admission_refusal` (replacing `is_latched`; `is_latched` stays for `resume_if_refusals_cleared`); `self._latch.arm_slot` (replacing `arm`); `self._latch.max_slots`; `self._latch.open_slot_count`; `self._ledger.exposure_admission_refusal`; `self._ledger.register_open_exposure`; `self._ledger.mark_ambiguous`; `self._ledger.settle`.
  - Resolver coroutine: `self._latch.next_open_for_resolution`; `self._latch.is_open_intent`; `self._latch.max_slots`; `self._latch.open_slot_count`; `self._ledger.has_open_exposure`; `self._ledger.settle`; `_leg_magnitude_of_signed_net`.
  - The `utc_day_for_ns` row from WP-DR stays (unused after WP4; harmless under `==`).
- **AST pins (new):**
  - no `await` between `authorize_order_cost` and `register_open_exposure`;
  - **no `await` between `authorize_order_cost` and each of the pre-POST `release_booking` calls at :6288 and :6294.** This enforces mechanically why those two stay on `release_booking`; no registry entry exists yet and the clock is the booking's own.
  - Ordering pin: `latch < veto < permit`, rewritten same-strength.
- RED (extend `test_polymarket_us_exec_client.py`):
  - the §3.3 pre-spend tests;
  - `test_two_distinct_slugs_both_post_concurrently`;
  - `test_concurrent_authorize_during_post_await_does_not_break_true_up` (client level, :6467, :6555, :6570);
  - `test_concurrent_authorize_during_post_await_crossing_midnight_no_stuck_slot_events_emitted`;
  - `test_resolver_ledger_calls_use_fresh_clock_at_k_gt_1`;
  - `test_resolver_fill_ts_event_and_settle_share_one_clock_read`;
  - **`test_settle_over_cost_retry_does_not_self_heal`**: an over-cost fill → ERROR + `_note_resolver_error` + UNBUDGETED latched + registry entry abandoned with no spend added; no later pass raises `spent_today` to the realized amount; the booking was reachable (not popped) until the outcome was decided;
  - `test_settle_raise_at_zero_fill_site_keeps_booking_and_propagates`;
  - the §3.7 successor and retained tests (ten);
  - `test_accept_fill_after_midnight_settles_via_registry_no_latch` (successor to WP-DR's latch test) plus its unregistered variant;
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
  - `test_boot_interleave_retire_before_and_after_registration`;
  - the `seeded_partial` tests of §3.5;
  - `test_boot_registration_failure_fails_connect_closed`;
  - `test_bucket_outside_frozen_label_forces_k1_and_alerts` and `..._derivation_raise_forces_k1`;
  - `test_body_slug_mismatch_denied`;
  - `test_body_quantity_not_equal_order_quantity_denied`;
  - `test_unmappable_instrument_denied_not_raised`;
  - `test_wire_quantity_written_at_both_call_sites_and_old_blob_decodes_none`;
  - **duplicate detector, per leg at both price extremes:** `test_duplicate_detector_{yes,no}_{at_0_08,at_0_92}_single_fill_does_not_trip` and `..._doubled_holding_trips` (eight cases);
  - `test_duplicate_detector_none_baseline_or_wire_quantity_not_evaluable`;
  - `test_duplicate_detector_needs_second_pass_and_lag_guard_age`;
  - `test_duplicate_detector_records_contradiction_not_just_log`;
  - `test_k1_differential_replay_identical_outputs`.

### WP5b: node config, breaker watcher, telemetry (neutral at K=1)
- Files: `node_config.py`, `trade_cli.py`, `app/trade.py`, `trade_supervisor.py`, a new `runtime/breaker_watcher.py` (an Actor).
- Contents:
  - the `Final` constants `EXEC_PAR_MAX_CONCURRENT_INTENTS = 1`, `OPEN_EXPOSURE_BOUND_FRACTION = Decimal("0.50")`, `BREAKER_OPEN_AMBIGUOUS_FRACTION = Decimal("0.25")`, the heartbeat age (60 s), `RESOLVER_PASS_STALE_NS` (600 s) and `EXEC_PAR_FROZEN_BUCKET` (set from D-PREREG), none env-derived and passed to the client via config fields;
  - the marker → `v2_admitted` wiring;
  - the watcher Actor (K>1 only);
  - the supervisor `probe_breaker_record` check and alerts (unreadable slot, trip, held-position list, stuck slot on a held slug, dead watcher, `k_forced_to_1`);
  - the throttle comment;
  - digest telemetry (`cross_day_settles_total`, heartbeat-stale denial count, dropped-candidate share by denial reason, per-station-day exposure, orders and notional per 5 s window).
- **No new `operator_controls` importer.** `test_operator_reserved_controls.py:708-768` is unchanged. `test_operator_control_assignment_scan.py` joins this WP's gate.
- RED:
  - `test_constants_are_final_and_not_env_derived`;
  - `test_k_forced_1_when_marker_absent`;
  - `test_no_operator_controls_importer_added` (the importer-list assertion);
  - `test_subscribe_trades_off_and_inflight_interval_zero`;
  - `test_watcher_not_registered_at_k1_and_no_breaker_writes`;
  - `test_watcher_is_an_actor_timer_task_on_the_node_loop`;
  - `test_breaker_trips_at_two_stuck`;
  - `test_breaker_notional_trigger_via_ledger_fires_below_f_adm`;
  - `test_contradiction_latches_halt_sticky_until_operator_reset`;
  - `test_duplicate_suspect_trips`;
  - `test_watcher_latency_at_most_one_poll`;
  - `test_heartbeat_not_written_when_poll_evaluation_raises`;
  - `test_heartbeat_write_does_not_block_arm_slot`;
  - `test_dead_watcher_denies_entries_and_supervisor_alerts`;
  - `test_dead_resolver_task_denies_entries_via_resolver_pass_age`;
  - `test_backoff_cap_resolver_pass_age_does_not_false_trip`;
  - `test_halt_allows_exits_and_resolver_still_retires`;
  - `test_breaker_does_not_use_family_halt_or_veto_signature`;
  - `test_first_unreadable_slot_alerts_once`;
  - `test_alert_detail_enum_pin_green`;
  - `test_digest_reports_cross_day_settles_and_denial_reasons`.

### WP6: strategy and exit readers (neutral at K=1)
- Files: `trial_day_latch.py` (add `admission_would_refuse(slug, is_exit)` and `open_submit_intents()`), `continuous_strategy.py:1713, 1918, 2496, 2600`, `continuous_no_side.py:309`, `exit_wiring.py:183`, `exit_guard.py`.
- The pre-filters use the **same read-only admission predicate** as the exec gate, including quarantine, K-full, cool-off, the breaker halt and the stale-heartbeat and stale-resolver denials.
- RED:
  - `test_prefilter_equals_exec_admission_for_all_tables` (property);
  - `test_admission_would_refuse_reflects_breaker_halt`, `..._stale_heartbeat` and `..._stale_resolver_pass`;
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
  - `test_drain_then_reset_then_rollback_drill`;
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
- **Sweep variable:** realized order cost over the daily budget (orders are about 1 contract at ≤ $1), in buckets {≤0.02, 0.05, 0.10, 0.25, 0.50}. WP0 also reports, per bucket, the distribution of actual per-order cost values (ask × 1 contract) from the pre-window candidates.
- The live caps are a read-only input only: an optional flag calls `cost_budget_bucket()` and prints the **bucket label only**.
- Statistic: day-clustered bootstrap (2,000 resamples) of the day-level p90 and p50.
- **Reporting:** the smallest K (3..8) whose CI upper bound ≤ 0.30 **per bucket**, at p_amb = 0.33 (Wilson upper) with one stuck slot, the worse free-balance arm, the throttle and the bound.
- **Build gate (WP0):** the build proceeds iff **some bucket ≥ 0.05** passes at K ≤ 8 (the ≤0.02 bucket makes `f_adm` irrelevant and cannot satisfy the gate alone). There is **no worst-bucket fallback STOP**. If the bucket is unknown, WP0 reports the table only.
- **Activation gates:**
  - re-run the stop rule at the actual bucket (CI upper bound ≤ 0.30);
  - the passing bucket label is **frozen in D-PREREG**;
  - at node boot with K>1 the §3.9 guard forces K=1 if the derived upper-bound label exceeds it.

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
| R1 | Same-slug temporal bleed | High | Durable cool-off (entries only) after all retires; the stuck-slot detector |
| R2 | Stuck slots eat K | High | Breaker (≥2 stuck, `f_breaker`, sticky); `f_adm` backstop |
| R3 | Exposure across restart, day roll or concurrent tasks | High | WP-DR; `settle` with a shared fresh clock; the registry; per-key unknown-notional fail-closed |
| R4 | Scoped refusals mis-cleared | High | Scope keys on configured K; clear rules in both directions |
| R5 | Pin drift | Med | Named rows; same-strength rewrite; banned-word scan; no new importer |
| R6 | v2 bytes read by a stale supervisor | High | WP5a first; the predicate before spend and in the arbiter |
| R7 | Lost unreadable slot | High | base64 `raw_slots`; never downgrade; original-bytes evidence dump |
| R8 | Native drops lose burst candidates | Med | Counted in d̂; live dropped-share stop in D-PREREG |
| R9 | Concentration into a correlated 5 s repricing | Med | Telemetry; D-PREREG stop criteria |
| R10 | Hold-input population mismatch | Med | NO ≥ 0.90 ramp gate in D-PREREG |
| R11 | A stuck entry blocks that slug's exit | Med | Equal to today; alert |
| R12 | A dead watcher or resolver task | Med | Heartbeat plus resolver-pass fail-closed denial; supervisor alert |
| R13 | An integrity error in the ledger | High | Visible: ERROR, resolver error count and the global UNBUDGETED latch; no self-heal |
| R14 | Caps drift after the freeze | Med | The boot-time bucket guard forces K=1 |

**Kill criteria.**
- The WP0 build gate fails in every bucket ≥ 0.05.
- Any duplicate-order evidence in WP7.
- A red full gate after a re-pin.
- An allowlist change that cannot be a named row, or any new `operator_controls` importer.
- Any need to change `_submit_veto`'s signature or add a `_refuse` site.

**Rollback.**
1. **WP-DR and WP4 are non-neutral** (D0-D6). Their rollback is a code revert with the pin in the same commit.
2. Other WPs are neutral at K=1.
3. After K>1: review the held positions, then reset the breaker record (`halted → null`, node down). Drain to ≤1 open (the table rewrites as v1), set K=1, and verify the breaker record is `halted: null` **before** reverting code.
4. **Old code ignores the breaker record**, so after a code rollback the breaker is silently inert and a stale `halted` would persist undetected on a later roll-forward. The rollback drill therefore asserts the record is reset (WP5a/WP7).
5. A rolled-back supervisor cannot admit v2, so the node refuses 1→2 transitions. If a v2 table is open, the old supervisor refuses launch and the CLI clears by intent id or slot key.
6. The halt drop-in and `BREEZY_ORDERS_ENABLED` are never touched.

## 8. D-PREREG: execution-design prereg (named deliverable, not written here)
Capability needs no prereg (no screen claim; `PREREG.json` untouched). **Trading a 12-07 WINNER through K>1 does.** D-PREREG is owned by the coordinator, frozen before the 2026-12-07 read, and never edited afterwards. It must contain:
- The **complete K schedule** and promotion criteria (fills and days per stage, hold conditions), with no K chosen post hoc.
- `f_adm = 0.50`, `f_breaker = 0.25`, the cool-off (120 s from retire; **entries only**; exits exempt), the stuck definition (floor + 600 s or CONTRADICTION), the heartbeat age (60 s) and the resolver-pass bound (600 s).
- **The frozen passing bucket label**, and the rule that a boot-time upper-bound label above it forces K=1 and alerts, with no prereg edit.
- **Detector definition:** per-leg magnitude vs baseline with the NO-as-short-YES sign; `wire_quantity` used directly and asserted equal to the order quantity; `None` is not evaluable; confirm on a second pass; `L_feed` (WP0-measured, else 300 s). **It is a stuck-slot belt, not a general double-POST detector.**
- **Breaker and reset:** triggers; an entries-only halt with exits allowed; the **reset requires the node to be down and an acknowledgement that held positions were reviewed**; the **recorded cost** that the reset restart interrupts the resolver and exits for its duration.
- An **AMBIGUOUS-rate halt**: stop promotion and halt if the observed rate exceeds the Wilson-upper 0.33.
- A **live dropped-candidate-share stop**: the share of candidates denied by `OpenExposureBound`, K-full, cool-off and the throttle against the 0.30 bar (the live counterpart of the build-gate metric).
- **Alert and halt thresholds:** the heartbeat-stale denial count and a non-zero-rate threshold on `cross_day_settles_total`.
- **Slippage and fee parity** against the screen ask.
- A **NO ≥ 0.90 hold-time re-measurement** as a ramp stage gate.
- **Concentration** stop criteria from the first-5 s deployed-fraction telemetry.
- **Parallel-execution fills never feed the M1-v3 verdict statistic or its look schedule.**
- The **frozen WP0 artefact hash and the chosen K's CI** at the actual bucket.
- A statement of independence from `PREREG.json`, that no data from 2026-10-07 to 11-28 is used, and that operator caps are referenced, never assigned.

## 9. Open questions for peer review (judgement calls; none blocks WP-DR or WP0)
1. **Reconciling rulings 2 and 3 on a settle raise.**
   - r5 keeps the booking reachable until the outcome is decided, but on an accept-fill integrity error it retires and latches in one pass instead of aborting. The reasons: aborting leaves the intent OPEN (holding the slot of a held position) and makes the existing producer unreachable without a new `_refuse` site.
   - It never self-heals. Peers should confirm they accept this literal deviation from "abort before the UNBUDGETED check".
2. Is `L_feed` (the WP0 measurement, else 300 s) with second-pass confirmation the right guard?
3. Is 60 s for the heartbeat and 600 s for the resolver pass right (12 polls; 2 × the backoff cap)?
4. The bucket guard derives an upper bound from `cap / budget`. Is that conservative enough, given that realized order cost is typically well below the cap?

## 10. Change log (every r4 finding → r5 resolution)

**Coordinator rulings.** 1 → §3.5 `breaker_fraction_exceeded`, WP5b gate. 2 → §3.5 retire path, F22. 3 → §3.7. 4 → §3.5 refactor and settle contract. 5 → §3.5 pre-check. 6 → §3.5 `seeded_partial`. 7 → §3.5 property. 8 → §3.5 shared stamp. 9 → §3.1 CLI. 10 → §3.6. 11 → §3.9, §6, §8. 12 → WP4 AST pins. 13 → §3.3 step 5, §3.6, §8. 14 → below.

**Architecture review (r4-A)**

| ID | Resolution |
|---|---|
| HIGH-1 (importer pin) | `ledger.breaker_fraction_exceeded` (any raise → tripped) plus a client property; no new importer; `test_operator_reserved_controls.py:708-768` named unchanged; `test_operator_control_assignment_scan.py` in the WP5b gate; `test_no_operator_controls_importer_added`. |
| Q1 conditions | §3.7 and §3.5: the successors assert `spent_today` rises by the realized amount; `registered` is captured from `settle`'s return before `_retire`; the raise path is defined; the WP-DR successor is in the same commit with the unregistered variant. |
| Q4 | WP4 AST pin extended to the :6288 and :6294 releases. |
| `_true_up_locked` condition | §3.5 refactor (validation and `_require_open_booking` kept; thin wrappers); `test_settle_same_day_unknown_or_double_booking_still_raises`. |
| Idempotency wording | §3.5: `booking=None` on an unregistered key is a no-op returning False; a second settle carrying a booking raises. |
| Watcher location | §3.6: a native Actor timer on the node loop. |
| No heartbeat at K=1 | §3.2 and §3.6: the watcher is not registered at K=1; `test_watcher_not_registered_at_k1_and_no_breaker_writes`. |

**Safety review (r4-S)**

| ID | Resolution |
|---|---|
| H1 (pop erases escalation) | §3.5: get-then-pop; the failure path abandons the entry, retires and latches; `test_settle_over_cost_retry_does_not_self_heal`; the WP-DR interaction stated (F22). |
| H2 (AC6b tests flip) | §3.7: the full sweep (five existing tests plus the WP-DR successor), named successors and retained unregistered variants; the latch retained as defence-in-depth; D1 gated on the equality property. |
| M1 (pre-check suppresses day stop) | §3.5: the pre-check returns None when plain `spent + cost > budget`; the test. |
| M2 (`seeded_partial`) | §3.5: derived from the durable record under the seed's day filter; 0 for a prior-day record and for no-id; four tests. |
| M3 (evidence dump) | §3.1: key regex, hashed filename, 0600, fsync of file and directory, original bytes, bad base64 is whole-table corruption. |
| M4 (heartbeat proves only the watcher) | §3.6: the single breaker record carries `resolver_pass_ns`; stale denial; the supervisor-side dead-watcher alert. |
| M5 (stamping) | §3.5: one fresh clock read for `ts_event`, `fill_ts_ns` and `settle`. |
| L1 (reset cost) | §3.6 and §8: recorded; an in-node reset rejected with the reason. |
| L2 (heartbeat contention) | `test_heartbeat_write_does_not_block_arm_slot`; no coalescing, with the reason. |
| L3 (two gets) | §3.6: one record, one `get`. |
| L4 (retained-variant naming) | §3.7: the comment that production reaches the latch only via a registry failure. |

**Market review (r4-M)**

| ID | Resolution |
|---|---|
| MEDIUM-1 (gameable build gate) | §6: pass only on a bucket ≥ 0.05; the frozen label in §8; the boot-time guard (§3.9). |
| MEDIUM-2 (property fidelity) | §3.5: BUY only; cent-up both sides; the seed's raw-sum and SELL-inclusive conservative bias documented as an accepted pre-existing exception. |
| MEDIUM-3 (`seeded_partial` zero rule) | As S-M2 (prior-day partial plus a today final-fill test). |
| MEDIUM-4 (no live check) | §8: the dropped-candidate-share stop and the alert thresholds. |
| MEDIUM-5 (cap drift) | §3.9: the boot guard forces K=1, with no prereg edit; the drift rule in §8. |
| LOW-1 (detector framing) | §3.6 and §8: a stuck-slot belt; the quantity-equality assertion (§3.3). |
| LOW-2 (heartbeat after full evaluation) | §3.6; `test_heartbeat_not_written_when_poll_evaluation_raises`. |
| LOW-3 (digest alert threshold) | §8. |
| LOW-4 (race test) | §3.3: `test_inlock_bound_race_after_passing_precheck_is_plain_deny`. |
| LOW-5 (rollback key) | §7.3-7.4: reset before rollback; the drill asserts it. |
| Open questions 1-5 | Answered as accepted: D1 (§3.7); `L_feed` (§3.6); the 60 s heartbeat (§3.6); the pre-POST sites (WP4 AST pin); `wire_quantity` with the equality assertion (§3.3). |

**Plan-reviewed files:** `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r4.md`, the three r4 reviews, `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/WP-DR-day-roll-settle_spec.md`, and the WP-DR worktree diff in `/home/jon/breezy/.claude/worktrees/agent-a06ff6c5f14021f97`.
