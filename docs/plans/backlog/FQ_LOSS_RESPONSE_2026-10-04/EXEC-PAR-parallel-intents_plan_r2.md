# PLAN r2: EXEC-PAR, bounded per-market-slug parallel submit intents

Status: DRAFT r2 for peer review. Build-time only. It builds capability and does not re-enable orders. Read-only investigation; the coordinator saves this text.
Supersedes r1. Every r1 review finding is resolved or justified in the change log (§10).

**Summary of what changed from r1**
- The v2 record is now the slot table itself, at `CURRENT_INTENT_KEY`, and is written only after the supervisor admits it.
- Admission runs before any spend.
- All singleton-valued fields and consumers are enumerated and given hunks.
- A new ledger open-exposure API is added.
- The breaker has frozen numbers.
- A separate execution-design prereg is a named deliverable.

## 0. Hard invariants (binding on every WP)

1. Nautilus Trader is immutable. Extend it only through the injected `StateStore`/latch seam and native config.
2. `allow_short` stays `False`.
3. Never weaken or delete a safety, settlement, contract, NO-SEND egress-firewall or import-pin test.
   - Widen exact sets only by named rows, keeping `==`.
   - Ordering pins are rewritten only to same-strength assertions on the renamed callee.
4. `exec/client.py` is byte-pinned. Floors stay: zero-fill 120 s, no-id 300 s, poll 5 s, backoff cap 300 s. The re-pin procedure is in WP4.
5. Operator caps (max daily budget, max per position = per order) are never assigned, defaulted or re-literalled. They are only read through the existing readers.
6. `BREEZY_ORDERS_ENABLED`, permit minting and `fq-v1-halt-orders-off.conf` are untouched.
7. No mypy ceiling raise. No `type: ignore`, `Any` or `cast` in new code.
8. No `PREREG.json` edit.
9. M1-v3 window outcomes and tape for 2026-10-07..11-28 are never read. Every offline tool refuses such inputs.
10. Capability build only: no WP trades. Trading through K>1 needs the separate execution-design prereg of §8.

## 1. Verified current-state facts (file:line, re-checked 2026-10-10)

**Latch and store**
- F1. `CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"`, `_SCHEMA_VERSION = 1` (`runtime/submit_intent.py:37-38`).
- F2. `StateStore` is `get/set` only (`submit_intent.py:43-53`). There is no scan, delete or list, so per-slot keys cannot be enumerated. This is why the slot table lives in one record (§3.1).
- F3. `arm` refuses on an OPEN or corrupt singleton (:399-427). `retire` writes history before the singleton (:493-511).
- F4. `SubmitIntent.from_bytes` requires `v == 1` and ignores unknown extra keys (:276-298). So a v2 table reads as `SubmitIntentCorrupt` (latched) in v1 code, and an extra `slug` key in a v1 record is tolerated by v1 readers.
- F5. The resolver context is per-intent: `RESOLVER_CONTEXT_KEY_PREFIX + intent_id` (`client.py:1094-1166`). It carries `notional_usd`, `booking_id` (process-local), `wire_market_slug`, `wire_price`, `wire_outcome_side`, `wire_action` and the baselines.

**Submit path (`_submit_order`)**
- F6. The global refusal gate is at `client.py:6110`. The AMBIGUOUS refusal is appended unscoped (`_refuse` :6685, `instrument=""` at :6760) from :6333 and :6580. The clears are at :3274-3282, **:3502-3514** and :4106-4115, and each is guarded by `self._latch.current_open() is None`. This is a **second singleton** besides the latch.
- F7. `_refuse` dedupes on the reason string only (:6757).
- F8. Gate order today:
  1. `is_latched()` at :6204;
  2. `_submit_veto` at :6215-6218;
  3. body build at :6226-6237;
  4. permit authorise and consume at :6239-6254;
  5. `authorize_order_cost` at :6276;
  6. `_intent_reconciled` check at :6286;
  7. `arm` at :6291;
  8. `_note_ambiguous_open` at :6303;
  9. POST at :6327.
  - Pinned by `tests/unit/test_execution_egress_firewall_guard.py:3066-3101`: `max(is_latched_lines) < min(veto_lines) < min(permit_spend_lines)`, with no `await` in between.
- F9. `_post_in_flight_intent_id` is a single `str | None` (:1838, set :6325, cleared in `finally` :6349). Its only reader is the no-id guard (:3747).
- F10. `self._latch: Any` (:1848). The latch is injected and the adapter never imports `breezy.runtime` (layers contract; `CorruptError` class attribute at `submit_intent.py:338`).

**Resolver**
- F11. One intent per pass: `current_open()` at :2670. Poll interval at :588. Backoff cap at :592. Floors at :1596 and :1604. Age gates at :3089 and :3752.
- F12. **Six more singleton sites** beyond :2670:
  - identity guards at :3197, :3339 and :4063. Each has the shape `current_open(); if None or id != mine: pop booking; return`;
  - refusal clears at :3274, :3502 and :4106.
- F13. `_resolver_consecutive_failures` is one global counter. It is incremented at five sites (:2845, :2882, :2921, :3791, :3809) and reset on any mapped GET (:2934, :3815). So it resets whenever any intent succeeds. It protects the 15 req/s budget during a venue-wide 5xx (sleep at :2613-2621), so it **stays global for the sleep**. It is not "one stuck intent slows all".
- F14. Boot order in `_connect` (:2200-2230):
  1. the first resolver pass runs `first_pass_immediate`;
  2. `_reconcile_submit_intent` (:2312);
  3. `_seed_spend_from_durable_fills` (:2370; early `return` at :2422 when there are zero fills);
  4. `_spend_seeded = True` (:2223).
  - Steps 3-4 are synchronous with no `await` between them.
- F15. `_RESOLVER_FILL_UNBUDGETED` (:732, :3458-3467): a fill resolved with `booking is None`, not a SELL, and `_spend_seeded` latches a **global DURABLE** refusal until respawn.

**Exposure**
- F16. `DailySpendLedger.authorize_order_cost` is atomic under one lock (`operator_controls.py:348-427`).
  - Bookings stay at full cost until `true_up_booking` or `release_booking` (:457-523).
  - **At a UTC day roll, prior-day bookings are dropped and `_spent_usd` is reset to 0 (:403-417).**
  - `_require_open_booking` then refuses to release a prior-day booking (:443). So an AMBIGUOUS order that survives 00:00Z stops counting while its slot and exposure persist (the 96,824 s order did).
  - r1's "the ledger already satisfies the invariant" is false across a day roll or restart.
- F17. `seed_spent` is one-shot and takes `max()` (:307-334). `AmbiguousResolverContext.booking_id` is process-local (:1100-1103).
- F18. D3: a permit slot is restored on zero-fill only when `booking is not None` (:3226-3250).
- F19. The permit budget is per-permit and thread-safe (`safety.py:349-358, 1032-1044`). The ledger is the only daily-budget authority.

**Native**
- F20. `RiskEngine` order-submit `Throttler` uses `output_drop=self._deny_new_order` (`risk/engine.pyx:140-150`). Excess orders are **dropped, not queued**, upstream of `_submit_order`, so no permit is spent on a throttled order. Per-order free-balance denial is at `engine.pyx:949`; cumulative notional is checked only within one order list (:968).
- F21. `max_order_submit_rate = "5/00:00:01"` (`node_config.py:698`), and its comment ("can never bind behind the latch", :681-697) becomes false at K>1. In-flight checks are disabled (`node_config.py:1036`) because the venue has no client-order-id (:895-901).
- F22. Venue limit: 20 req/s, Breezy budget 15 req/s (`transport.py:111-125`). The exec path is REST only. The WS cap of 10 is shared MARKET_DATA/TRADE, and the node keeps `subscribe_trades` off (WP0 re-verifies).
- F23. YES/NO legs share one base slug: `base_slug_of(InstrumentId)` (`symbology.py:298-310`) and `leg_of` (:289).

**Consumers of intent state (complete sweep; `Grep` of `src/` and `scripts/`)**

| Consumer | Site | Needs |
|---|---|---|
| exec client | :2670, :3197, :3274, :3339, :3502, :4063, :4106 (`current_open`); :6204, :6785 (`is_latched`); :1838, :3747, :6325, :6349 (in-flight id) | H2, H5, H7, H8, H0 |
| `trial_day_latch` | :732 `is_intent_open`; :753 `current_open_submit_intent` | per-slug, all-open views |
| `continuous_strategy` | :1713, :1918 (pre-filters), :2496 (re-arm in-flight release), :2600 (observation), :2739 (calls exit check) | per-slug admission view |
| `continuous_no_side` | :309 | per-slug admission view |
| `exit_wiring` | :183 `current_open_submit_intent()` (fingerprint match to halt on stale ambiguous EXIT) | per-fingerprint lookup |
| `exit_guard` | :163-192 (reasons only; no live caller yet) | scope-aware |
| `trade_supervisor` | probes :431-501; consumers :1298-1307, :1361-1377, :1476, :1866; marker write :2939 | WP5a |
| `clear_submit_intent_cli` | :125 `latch.current()` (uncaught on v2) | WP5a |
| analysis | `prelaunch_intents.py:50-70` (`_ReadCurrent`); `scripts/analysis/score_live_trials.py:190, 383-410, 531` (raw state, degrades to "absent"); `scripts/ops/ambig_latch_phase_a_check.py`; `fill_time_count.py` (WP0 re-verify: no singleton read found) | WP5a |
| `trade_cli` | :432 `trading_refusals`; :538 `resume_if_refusals_cleared` | scoped reader |
| `forecast_quantile_ladder` | its `is_latched` is `QuantileLadderLatch` (`decision.py:286`), a **different latch**; r1 was wrong to list it | none; FQ gets the benefit via the exec client |

**Premise audit**
- P1. The constants are correct. The poll constant is at :588, not :587.
- P2. "42% within 5 s" is confirmed (0.4204 over 333 candidates).
- P3. p_amb = 0, K = 1, p90 = 0.491 is reproduced (in-memory run; WP0 commits the arm).
- P4. "Drop" is the screen's parity policy. In code a latched candidate is a WAIT. This plan does not rely on retry.

## 2. Native-Nautilus gap analysis (unchanged conclusion; two additions)

| Need | Native? | Verdict |
|---|---|---|
| Concurrent submission | Yes: one task per `SubmitOrder` (`live/execution_client.py:277-282`) | No gap. The serialisation is Breezy's venue-safety control. |
| Ambiguity resolution | In-flight check force-resolves FAILED after retries | **Gap** (F21): no client-order-id, so a false terminal. Stays disabled. |
| Per-order notional / rate | `max_notional_per_order`, 5/s Throttler | Retained. The throttler **drops** (F20). It is modelled as a drop in WP0 (d̂ counts it). It is upstream of the permit, so it wastes no permit slot. |
| Free-balance denial | Per-order (`engine.pyx:949`) | A native denial source, not a cap. WP0 records when the cash account's `free` updates relative to the fill and AMBIGUOUS paths (§6.1). |
| Aggregate open exposure vs a daily budget | No | **Gap.** The ledger remains the sole authority (§3.5). |
| Per-slug durable exclusion with crash recovery | No | **Gap.** Built on the existing injected-latch seam. |

## 3. Design (Option A, adopted rulings)

Option B (anonymous slots) collapses into A, since it still needs same-slug exclusion for no-id attribution. Option C (queue) cannot beat the floors. Option D (second router/exec client) violates single-writer. All are rejected as in r1.

### 3.1 Storage: the slot table IS the singleton record (rulings 1, A-C2)
- Representation of `CURRENT_INTENT_KEY`:
  - **v1 bytes** (exactly today's) while at most one intent is OPEN **and** the supervisor has not advertised the slot schema, or whenever the table would hold ≤1 OPEN slot after a retire.
  - **v2** `{"v":2,"slots":{<key>:<intent record incl. slug>},"cooloff":{...}}` only while ≥2 slots are open **and** the supervisor admits v2 (§3.2).
- `SubmitIntent` gains a trailing optional `slug: str | None = None`.
  - `to_bytes` emits the `slug` key only when set. K_eff=1 arms with `slug=None`, so bytes are identical to today.
  - Records written inside a v2 table carry the slug. A v2→v1 downgrade of the one remaining OPEN intent writes a v1 record plus the extra `slug` key, which v1 readers ignore (F4).
  - A slug-less OPEN record is adopted via `AmbiguousResolverContext.wire_market_slug`. No context means key `"?:<intent_id>"`, which forces **quarantine** (admit denies all) until retired or cleared.
- Every arm and retire is **one atomic `set`** of the whole table under the existing mutex and flock.
  - There is no index, no scan and no per-slot key, so there is no new crash window.
  - History-first retire is unchanged: `history_key(intent_id)` is set before the table. `reconcile_at_startup` copies history over matching slots.
- When the last slot retires, `CURRENT_INTENT_KEY` becomes a valid v1 RETIRED record (A-M1). Rollback is free once drained.
- Slot decode is per slot. A malformed slot becomes an unreadable-slot entry, which quarantines admission. Healthy slots stay resolvable (S-H7). A wholly undecodable table behaves as today (latched; the resolver `continue`s).

### 3.2 Ordering and the precise behaviour-neutral claim (ruling 2, A-C1, S-C3)
- WP5a lands first: the supervisor decodes v2, the CLI and analysis readers tolerate it, and the marker advertises capability.
  - The marker (`runtime/supervisor_decode_marker.py:36-100`) gains a trailing-optional field `slot_schema_versions: frozenset[int]`. Old markers lack it and decode as empty. `_SCHEMA_VERSION` stays 1.
  - New function `supervisor_admits_slot_schema(store_path, version=2)`, same live-pid and start-ticks identity check as `supervisor_admits_retirement_reason` (:142-155).
- The node's slot latch is constructed with an injected predicate `v2_admitted: Callable[[], bool]`. It is **evaluated at each transition from ≤1 to ≥2 open slots**, not just at boot.
  - If false, the arm is refused as a WAIT (K_eff = 1). A supervisor rolled back mid-run therefore cannot be written past.
- **Claim (K_eff=1 is neutral), with proof obligations:**
  1. Store-write sequence: for every existing fixture, the sequence of `(key, bytes)` writes is byte-identical to the pre-change golden (`test_k1_store_write_sequence_matches_golden_v1`).
  2. Admission: `admit(open, slug, K=1, ...)` denies iff any intent is open or the table is quarantined, which is `is_latched()`. Proven by a property test over arbitrary tables.
  3. Refusals: at K_eff=1 `_refuse` writes `instrument=""` (unscoped), exactly as today. Scoping applies only when K_eff>1. This preserves the "refusal outlives a failed clear" branch at :3263-3273.
  4. Exposure: the fraction bound applies only when another open intent exists, which is never at K_eff=1. The new registry methods are additive.
  5. Source-level change: `client.py` changes and is re-pinned (a byte change, not a behaviour change). The claim is behavioural, shown by differential replay.
- Deployment sequence: WP5a merge → supervisor restart (code loads once; window 01:00-16:40Z, `KillMode=process` keeps the node) → marker verified → WP4. Before the restart, WP4 cannot write v2 (predicate false). K stays 1 until the activation proposal.

### 3.3 Admission before spend (ruling 3, A-Ha, A-Hb, S-H6, M-L4)
- `admit(table, slug, is_exit, k_max, quarantined) -> Admit | Wait(reason)` is pure (domain). Denies on: same slug, K-full (non-exit slots ≥ K, exits exempt), quarantine, or slug cool-off (§3.8).
- `arm_slot` (runtime; holds mutex and flock) is the **sole arbiter** and calls `admit`. A K-full or same-slug loss raises `SubmitIntentLatched`, so `is_latch_arm_refusal` (type-name match, `submit_chain.py:213`) still classifies it (A-L2).
- `_submit_order` calls the read-only `self._latch.admission_refusal(slug, is_exit)` (a named callee that wraps `admit`), **before the veto and before the permit/ledger spend**, in the slot occupied today by `is_latched`.
- **Where I contradict the ruling, with evidence.**
  - The ruling says "after the body build". The `base_slug_of(order.instrument_id)` derivation and the SELL test (`order.side == OrderSide.SELL`, a comparison) need no body.
  - Keeping the gate at its present position preserves the pin's existing `<` chain (latch < veto < permit; body build already sits between veto and permit). Moving it after the body build would force the pin to be re-ordered.
  - So the pin changes by exactly one named callee row (`is_latched` → `admission_refusal`), with the `max(...) < min(...)` and no-await assertions kept verbatim (A-Ha).
- The slug is `base_slug_of(order.instrument_id)`. After the body build and before the permit spend, an inline `if body["marketSlug"] != slug: return self._deny(...)` is added (a comparison, not a call). Test: `test_instrument_slug_equals_body_market_slug`.
- Race: nothing awaits between the gate and `arm_slot` (F8, synchronous). The arbiter makes this a belt-and-braces property. A loser releases the booking as today; the permit slot is not burned because the predicate ran first.

### 3.4 Singleton fields and sites (ruling 4)
- **H0.** `_post_in_flight_intent_ids: frozenset[str]`, whole-value reassignment (`| {id}`, `- {id}`). The reader becomes a membership test. No new callee.
- **H5 (resolver selection, :2670).** `current = self._latch.next_open_for_resolution(skip=...)` returns the best readable open intent.
  - Order key: `(per-intent consecutive failures asc, last_served asc, created_ns asc)`.
  - Per-intent failure counters are a plain dict updated by whole-value reassignment, mirroring the 5 increment and 2 reset sites (F13).
  - The **global** counter keeps driving the sleep. Per-intent counters only influence selection.
- **H7 (identity guards, :3197, :3339, :4063).** Replace `current_open()` by `self._latch.is_open_intent(intent_id)`, a by-id callee. Test: slot B resolves while slot A is OPEN.
- **H8 (refusal clears, :3274, :3502, :4106).** At K_eff>1 the clear removes the AMBIGUOUS refusal scoped to that slug, regardless of other open slots. At K_eff=1 the existing condition is kept. A new callee `self._latch.open_intent_count` is avoided: the condition is computed by `is_open_intent`/a local.
- **`_refuse`.** Keyword-only `instrument: str = ""`. Dedupe key `(reason, instrument)`. Scoped AMBIGUOUS is pinned `RefusalClass.DURABLE`, because `refusals_after_successful_reconcile` clears TRANSIENT entries scoped to the reconciled slug (`refusals.py:302-323`, `client.py:5073`). Pin-neutral (`test_exec_refusal_health_surface.py:182-291` keys on call count/ordinal). Tests:
  - A ambiguous, B ambiguous, A retires: B's refusal survives.
  - `_map_position` success on A never clears A's AMBIGUOUS.
- **Gate at :6110.** Unscoped refusals deny all. Scoped ones deny only the order's slug. Implemented as a `for` loop with comparisons, so no new callee.
- **Corrupt handling.** The resolver skips unreadable slots, logs once per slot key (the existing `_resolver_corrupt_logged` bool becomes a frozenset), and continues.
- **`resume_if_refusals_cleared`** keeps `is_latched()` (any open or quarantined slot ⇒ latched). It stays allowlisted by name.

### 3.5 Exposure accounting API (ruling 5, S-C4, S-H2, A-Hf, M-H1, M-H2)
**Invariant (true statement):** at every `authorize_order_cost`,
`spent_today_gross + uncharged_open_exposure + cost ≤ daily_budget`.
- `uncharged_open_exposure` is the notional of OPEN intents with no live booking on today's accumulator. These are boot-inherited intents and intents that survived a day roll.
- Open-AMBIGUOUS notional is therefore never silently dropped.

New additive methods on `DailySpendLedger` (`operator_controls.py`; existing methods' semantics and the "previous UTC day" refusals are unchanged, so their tests stay):
- `register_open_exposure(intent_key, notional_usd | None, charged, day, now_ns)`.
  - Idempotent by key.
  - `None` means unknown notional and sets `_unbounded`, which makes `authorize_order_cost` refuse entries. This applies to a context-less slot.
  - It never calls `operator_max_position_cost_usd()`, so there is no crash when the control is unset (M-H2).
- `settle_open_exposure(intent_key, realized_usd | None, now_ns) -> bool`.
  - Idempotent. Returns True iff the key was registered.
  - For an **uncharged** entry with a fill whose day is today, it adds `realized_usd` to `_spent_usd`. For a charged entry it only removes (the existing `true_up`/`release` already adjusted spend).
- `has_open_exposure(intent_key)`, `open_exposure_total()`, `uncharged_open_total()`.
- In the existing day-roll pruning block (:403-417), surviving **open** bookings are converted to uncharged entries before the reset. They are not dropped.
- `authorize_order_cost` additions (inside the same lock, after the existing checks):
  - refuse if `_unbounded`;
  - raise `DailyBudgetExhausted` if `spent + uncharged + cost > budget`;
  - **fraction bound:** if another open intent exists, raise a new `OpenExposureBoundExceeded(LiveTradingPermissionError)` when `open_other + cost > f × budget`.
    - This is deliberately not `DailyBudgetExhausted`, so it does not trip the single-day stop (`_mark_budget_exhausted`).
    - `f` is a Breezy-owned `Final` constant (§3.6) injected at construction. Default `None` means off.
    - The budget is read via the existing reader, never assigned.

Client use:
- After `authorize_order_cost` and `arm_slot` succeed (synchronous, no `await`), `register_open_exposure(intent_id, notional, charged=True)`. New AST pin: no `await` between `authorize_order_cost` and `register_open_exposure`.
- **Boot (H6).** A new step runs inside the no-await span between `_seed_spend_from_durable_fills` and `_spend_seeded = True` (F14).
  - Runs even when there are zero fills (the early `return` at :2422 is left alone; this is a separate step).
  - For each open intent still OPEN after the first resolver pass, register `charged=False` with the context's `notional_usd`, or `None` if there is no context.
  - The permit is seeded with `fills + open notionals` in the same once-only call. Fail-closed; the permit then stays debited for the process (D3 means no restore without a booking).
  - Partial fills are counted twice (open notional plus the durable partial). Documented as conservative.
- **Retire.** The fill sites capture `registered = ledger.has_open_exposure(id)` and call `settle_open_exposure(id, realized)` **before** `_retire`.
  - `_RESOLVER_FILL_UNBUDGETED` fires only when `booking is None and not SELL and _spend_seeded and not registered` (F15).
  - `_retire` (the one chokepoint, :5905) calls `settle_open_exposure(id, None)` idempotently, so every zero-fill, no-fill and reject path releases headroom.
- **Over-budget at boot.** `authorize_order_cost` denies. `_intent_reconciled` stays True and the resolver is independent of `authorize`, so slots retire and headroom returns. This avoids the 09-24 deadlock shape.
- **D3.** Boot-registered intents have `booking is None`, so no permit slot is restored. Test it.
- Exact-once property: for any interleaving of seed, register, fill, zero-fill and day roll, each distinct fill is counted exactly once and open exposure is never dropped before settle.

### 3.6 Breaker (ruling 6, M-H3, S-C2 risk R2)
Frozen numbers for the first K>1 deployment (re-stated in the execution prereg):
- **Stuck** = an AMBIGUOUS open intent with age > `floor + 600 s` (with-id: 720 s; no-id: 900 s), or an intent whose resolver outcome was CONTRADICTION.
- **Trip** at ≥ 2 stuck intents.
- **Open-AMBIGUOUS notional** > `f × runtime daily budget`, with **f = 0.50** (Breezy-owned `Final` in `node_config.py`, never an operator cap, and the same `f` as §3.5's admission bound).
- **Duplicate-order test:** for a slug, `observed signed venue-net delta since baseline > wire order quantity` (the single slot's own order). The baselines already exist for every intent (`capture_holding_baseline=True`, :6311). A positive result is counted as a CONTRADICTION (so stuck) and also trips the breaker immediately.
- **Effect:** a family halt only, via the existing `record_policy_halt` / `family_halt_submit_veto` path (`app/trade.py:340-486`, `_submit_veto` at :6215).
  - The veto is read only by `_submit_order`. The resolver never consults it, so **the breaker never blocks resolution**. Test: with the breaker tripped, a pending slot still retires.
  - The breaker never retires an intent; stuck slots leave only via the resolver or an operator clear.
- **Input:** the client exposes a read-only property of `(intent_id, age_ns, branch, contradiction)` tuples, the same seam as `stale_ambiguous_intent_alerts` (`client.py:2511`, `trade_cli._exec_client_stale_intent_reader`). The watcher lives in the runtime layer.

### 3.7 Exits (ruling 7, S-H3, S-H4)
- Exits are **K-exempt but slug-exclusive**: `admit(..., is_exit=True)` skips the K check but still denies a slug that has an open intent. The exit/entry same-slug test runs in both orders.
- Entry bookings are unchanged (SELLs never book budget).
- `exit_guard.assert_settlement_close_permitted` gains an optional keyword `refusal_scopes: Sequence[tuple[str, str]] | None`. When given, it refuses only for unscoped entries or for the close's own base slug. The existing signature and tests are unchanged, and it has no live caller yet.
- The client exposes `trading_refusal_scopes` (pairs) beside `trading_refusals` (reasons).
- `exit_wiring.check_exit_intent_for_ambiguous_send` (:183) uses a new `TrialDayLatch.open_submit_intents()` (all open) and matches by fingerprint. Test: a stale ambiguous exit in any slot halts the family.

### 3.8 Late-fill and cool-off (M-M1)
- After a zero-fill or no-fill retire, the slug is denied for `SLUG_SETTLE_COOLOFF_NS = 120 s` (equal to the zero-fill floor), so a late fill cannot fold into a new slot's baseline.
- It lives in process memory (the strategy's durable `_REARM_MIN_DELAY_SECS = 120` covers restarts) and applies only at K_eff>1. It is part of `admit`.

### 3.9 Venue and subscription constraints
- Resolver: still one intent per pass, so GET load per pass is unchanged and under 15 req/s (F22). Latency for a slot rises by ≤ (K−1)×5 s, which is immaterial against the 120 s floor and does not touch the `_REARM_MIN_DELAY_SECS` pin (constant equality only, `test_current_rung_hold_ambiguous_resolver.py:4004`; the delay is measured in event time at `continuous_strategy.py:2354, 2514`).
- No new subscriptions (WS cap 10). Test: node config keeps `subscribe_trades` off.
- The native 5/s throttle may drop burst orders. The comment at `node_config.py:681-697` is rewritten and the value is not raised here.

## 4. Work packages (TDD order)

Common gate: `PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python -m pytest --basetemp=~/.cache/...`, never `/tmp`. `lint-imports` run from the tree's own cwd must show "N kept, 0 broken". `ruff`, `mypy` with no ceiling change. Full gate `scripts/ci/run_tests_no_egress.sh`, reading the exit code before any push, after every merge.
- Every focused list includes:
  - `test_execution_egress_firewall_guard.py`;
  - `test_polymarket_us_exec_client.py`;
  - `test_submit_intent_latch.py`;
  - `test_current_rung_hold_ambiguous_resolver.py`;
  - `test_edge2_ac6b_cross_process_fill_budget.py`;
  - `test_operator_reserved_controls.py` and `test_operator_control_assignment_scan.py`;
  - `test_exec_refusal_health_surface.py`;
  - `test_forecast_quantile_ladder_manifest_and_markers.py` and `test_autonomy_envelope.py`;
  - `tests/contract/test_live_fill_scoring_chain_contract.py`;
  - all `test_autonomy_*` and the import-pin tests.
- Briefs state: exact interpreter, no `uv run`/`pip`/`git stash`, format only your own files, own scratchpad, worktree `PYTHONPATH` first.

**Order:** WP0 → WP1 → WP2 (inert) → WP3 (inert) → WP5a → [supervisor restart, marker check] → WP4 → WP5b → WP6 → WP7. WP0-WP3 change no running behaviour: nothing calls the new code and the ledger fraction is off.

### WP0: viability and premise verification (no production code; a hard gate)
Method and results are in §6. RED (`tests/unit/test_exec_parallel_dhat.py`):
- `test_refuses_any_input_on_or_after_2026_10_07`;
- `test_k1_reproduces_p0_p90_0_491_and_triage_p018_p033`;
- `test_admit_used_by_simulation_is_the_production_admit` (imports the domain function);
- `test_throttle_5_per_s_drops_and_counts_in_dhat`;
- `test_free_balance_denial_arm_counts_in_dhat`;
- `test_cluster_bootstrap_ci_on_p90_stop_on_upper_bound`;
- `test_first_5s_budget_fraction_arm_reported`;
- `test_stuck_slot_reduces_effective_k`;
- `test_yes_and_no_leg_share_one_slot_by_base_slug`;
- `test_hold_constants_match_exec_client_source_ast`.
- Verifications recorded with file:line:
  - `risk/engine.pyx` and the cash account's `free` update timing relative to the fill and AMBIGUOUS paths;
  - `subscribe_trades` is off in `node_config`;
  - `fill_time_count.py` reads no singleton;
  - `base_slug_of(order.instrument_id)` equals the wire slug for sampled YES and NO ids.
- Stop rule: §6.

### WP1: pure admission model + Protocol (domain)
- Files: `src/breezy/domain/exec_intent.py` (or sibling), plus a `typing.Protocol` for the injected slot latch (A-L1). The adapter types `self._latch` against it only if `mypy` accepts it without `Any`; otherwise a documented typed field.
- RED:
  - `test_admit_denies_same_slug`;
  - `test_admit_denies_at_k_non_exit`;
  - `test_exit_is_k_exempt_but_slug_exclusive`;
  - `test_admit_denies_all_when_quarantined_or_unreadable_slot`;
  - `test_admit_k1_equals_is_latched_for_any_table` (property);
  - `test_admit_pure_deterministic`;
  - `test_cooloff_denies_slug_until_expiry`.

### WP2: slot table in `submit_intent.py` (runtime; inert)
- RED:
  - `test_k1_store_write_sequence_matches_golden_v1`;
  - `test_slug_key_emitted_only_when_set`;
  - `test_v1_reader_ignores_extra_slug_key`;
  - `test_v2_table_decodes_as_corrupt_in_v1_code`;
  - `test_arm_slot_one_atomic_set_per_arm_and_retire`;
  - `test_crash_between_history_and_table_write_recoverable` (store failure at each `set`);
  - `test_last_retire_writes_valid_v1_retired_record`;
  - `test_two_open_downgrade_to_one_writes_v1_with_slug`;
  - `test_unreadable_slot_quarantines_but_healthy_slot_resolvable`;
  - `test_legacy_open_adopted_by_context_slug`;
  - `test_legacy_open_without_context_quarantines`;
  - `test_v2_write_refused_as_wait_when_predicate_false`;
  - `test_predicate_reevaluated_at_each_one_to_two_transition`;
  - `test_concurrent_arm_slot_one_winner_per_slug`;
  - `test_is_open_intent_by_id`;
  - `test_open_submit_intents_lists_all`.

### WP3: ledger open-exposure API (`operator_controls.py`; inert)
- RED (`tests/unit/test_daily_spend_ledger_open_exposure.py`; existing day-rule tests untouched):
  - `test_concurrent_authorizations_never_exceed_budget_incl_open_ambiguous` (hypothesis);
  - `test_ambiguous_booking_survives_utc_day_roll_as_uncharged`;
  - `test_uncharged_exposure_counts_against_headroom`;
  - `test_settle_zero_fill_releases_headroom`;
  - `test_settle_uncharged_fill_adds_realized_once`;
  - `test_exactly_once_over_all_seed_register_fill_interleavings` (property);
  - `test_unknown_notional_sets_unbounded_and_refuses_entries`;
  - `test_register_never_reads_operator_caps`;
  - `test_fraction_bound_off_when_no_other_open_intent`;
  - `test_fraction_bound_raises_open_exposure_bound_not_daily_budget_exhausted`;
  - `test_prior_day_booking_still_not_releasable` (existing semantics kept);
  - `test_operator_caps_never_assigned` (AST).

### WP5a: supervisor, marker, CLI, analysis readers (deploys BEFORE WP4)
- Files:
  - `runtime/supervisor_decode_marker.py`;
  - `runtime/trade_supervisor.py` (probes :431-501 and their consumers :1298-1307, :1361-1377, :1476, :1866; marker write :2939);
  - `runtime/clear_submit_intent_cli.py`;
  - `analysis/labeling/prelaunch_intents.py`;
  - `scripts/analysis/score_live_trials.py`;
  - `scripts/ops/ambig_latch_phase_a_check.py`.
- RED:
  - `test_marker_advertises_slot_schema_and_old_marker_decodes_empty`;
  - `test_admits_slot_schema_requires_live_matching_pid`;
  - `test_probe_open_intent_true_for_v2_table_with_open_slot`;
  - `test_probe_resolvable_true_for_v2_with_contexts_false_for_unreadable`;
  - `test_launch_refuses_only_on_corrupt_or_contextless_or_unreadable_slot`;
  - `test_clear_cli_lists_slots_and_clears_by_intent_id`;
  - `test_clear_cli_never_raises_uncaught_on_v2`;
  - `test_clear_cli_refuses_to_erase_table_over_open_slots`;
  - `test_score_live_trials_v2_with_open_slots_reports_open_not_absent`;
  - `test_prelaunch_observation_v2_open_is_ambiguous_not_unknown`;
  - `test_rollback_drill_after_drain_old_reader_sees_valid_v1_retired`.
- Deploy: merge, restart the supervisor, verify the marker field, then proceed.

### WP4: exec client (byte-pinned) + firewall rows + re-pin
- Hunks: H0, H1 (scoped refusal gate), H2 (admission gate), H3 (body-slug equality), H4 (`arm_slot` and register), H5, H6 (boot), H7, H8, H9 (settle sites), `_refuse` dedupe and scope, per-intent failure mirrors, and the scoped property.
- **Named allowlist rows (keep `==`; check each against the banned-word scan `read/send/post/request`).**
  - Order coroutine: `base_slug_of`; `self._latch.admission_refusal` (replaces `is_latched`; `is_latched` stays allowlisted for `resume_if_refusals_cleared`); `self._latch.arm_slot` (replaces `arm`); `self._ledger.register_open_exposure`.
  - Resolver coroutine: `self._latch.next_open_for_resolution`; `self._latch.is_open_intent`; `self._ledger.has_open_exposure`; `self._ledger.settle_open_exposure`.
  - Ordering pin rewritten same-strength for the renamed callee. A new AST pin: no `await` between `authorize_order_cost` and `register_open_exposure`.
- **Re-pin.** After approval by `python-reviewer` and `prediction-market-reviewer`, edit only `_EXEC_CLIENT_SHA256` at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`. Append a comment line in the existing style: `# re-pinned <date>: EXEC-PAR H0-H9, reviewer-approved`. `test_autonomy_envelope.py:901-916` reads it by AST.
- RED (extend `test_polymarket_us_exec_client.py`, `ambig_latch_rig.py`):
  - `test_two_distinct_slugs_both_post_concurrently`;
  - `test_same_slug_second_is_wait_no_permit_no_booking_spent`;
  - `test_k_full_is_wait_before_permit_spend`;
  - `test_exit_other_slug_passes_when_k_full`;
  - `test_ambiguous_on_a_does_not_deny_b_when_scoped`;
  - `test_k1_unscoped_refusal_denies_all_as_today`;
  - `test_two_slug_ambiguous_a_retires_b_refusal_survives`;
  - `test_scoped_ambiguous_is_durable_and_survives_map_position_success`;
  - `test_slot_b_resolves_while_a_open`;
  - `test_resolver_visits_slots_round_robin_skipping_backoff_slot`;
  - `test_global_backoff_still_drives_sleep`;
  - `test_one_503_slot_does_not_starve_others`;
  - `test_in_flight_ids_frozenset_resolver_skips_first_post_after_second_completes`;
  - `test_resolver_floors_unchanged_120_300_5_300`;
  - `test_boot_open_intent_registered_uncharged_zero_fills`;
  - `test_boot_context_less_slot_unbounded_denies_entries_no_crash`;
  - `test_boot_over_budget_resolver_still_retires`;
  - `test_boot_zero_fill_retire_no_permit_restore_d3`;
  - `test_boot_fill_not_flagged_fill_unbudgeted`;
  - `test_booking_survives_day_roll_with_open_slot`;
  - `test_body_slug_mismatch_denied`;
  - `test_k1_differential_replay_identical_outputs`.

### WP5b: node config, breaker, telemetry
- Files: `runtime/node_config.py`, `runtime/trade_cli.py`, `app/trade.py`.
- Contents:
  - `EXEC_PAR_MAX_CONCURRENT_INTENTS: Final[int] = 1` and `OPEN_EXPOSURE_BOUND_FRACTION: Final[Decimal] = Decimal("0.50")` (Breezy-owned, never env-derived);
  - marker → `v2_admitted` wiring;
  - the breaker watcher;
  - rewrite of the throttle comment;
  - telemetry-only digest fields: per-station-day open exposure, and orders and notional per 5 s window.
- RED:
  - `test_k_constant_is_final_and_not_env_derived`;
  - `test_k_is_forced_to_1_when_marker_absent`;
  - `test_node_config_does_not_enable_subscribe_trades`;
  - `test_inflight_check_interval_ms_still_zero`;
  - `test_breaker_trips_at_two_stuck_slots`;
  - `test_breaker_trips_on_contradiction`;
  - `test_breaker_trips_on_open_ambiguous_notional_gt_f_budget`;
  - `test_breaker_trips_on_holdings_delta_gt_wire_qty`;
  - `test_breaker_never_retires_and_resolver_still_runs_when_tripped`;
  - `test_breaker_sets_family_halt_only_via_record_policy_halt`.

### WP6: strategy and exit readers
- Files:
  - `trial_day_latch.py`: add `is_slug_intent_open(slug)`, `admission_would_refuse(slug, is_exit)`, `open_submit_intents()`. Keep the old methods;
  - `continuous_strategy.py:1713, 1918, 2496, 2600`;
  - `continuous_no_side.py:309`;
  - `exit_wiring.py:183`;
  - `settlement/exit_guard.py`.
- The pre-filters use the **same read-only admission predicate** as the exec gate (not a bare slug test). This keeps Resolution B's property: no hunt → WAIT-deny → clear-inflight loop at K-full.
- RED:
  - `test_hunt_proceeds_on_other_slug_when_not_k_full`;
  - `test_hunt_waits_when_k_full_or_same_slug`;
  - `test_prefilter_equals_exec_admission_for_all_tables` (property);
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
  - `test_late_fill_after_zero_fill_retire_then_rearm_same_slug`;
  - `test_exit_and_entry_same_slug_serialised_both_orders`;
  - `test_supervisor_rolled_back_mid_run_blocks_v2_write`;
  - `test_drain_then_rollback_drill`;
  - `test_replay_bit_for_bit_fixed_clock`.
- Exit: a proposal to raise K above 1, which is **blocked on the execution-design prereg SHA (§8)** and on WP0 passing.

## 5. Gates per WP
Each WP runs the common gate plus its own named files. WP4 additionally runs the whole firewall suite, the exec import pin, the citation map and the refusal-producer pin, and the full gate after the re-pin. WP5a's supervisor restart is verified by reading the marker file field and the supervisor log, not by `pgrep`.

## 6. Viability (ruling 8; a build gate only)

### 6.1 Method (pre-2026-10-07 data only)
- Candidates: re-extract with instrument ids from the pre-window tape (the existing cands file keeps only `(ts, station)`). Source and bounds: `stage_minus1_triage_dmix.py` (`FIRST/LAST`). Hold inputs: `WP0_c0_pre1007_orders.tsv`.
- Model per day (1,000 seeded draws): admit via the **production** `admit` (domain import). The 5/s Throttler is **a drop** (sliding 1 s window; the dropped candidate counts in d̂). Native free-balance denial is modelled as a drop, with free-balance sweep `F ∈ {2c, 4c, budget proxy}` and `free` reduced at accepted-fill time and never by AMBIGUOUS orders (to be confirmed by the §4 WP0 verification). Include one stuck slot (K_eff = K−1), the no-id share, and p_amb ∈ {0, 0.05, 0.10, 0.18, 0.33}.
- Statistic: day-clustered bootstrap (2,000 resamples of days) for p90 and p50. **STOP iff the 95% upper bound of d̂_p90 > 0.30** at the Wilson-upper p_amb = 0.33 with one stuck slot, the throttle drop and the free-balance arm on.
- Extra arm: the share of the (parametrised) daily budget deployed in the first 5 s, over c/B ∈ {0.05, 0.10, 0.25, 0.50}. It informs the prereg (§8) and sizes the concentration risk. It is not a gate.
- Report K ∈ {3..8}; the smallest K whose CI upper bound ≤ 0.30 is the K candidate. K is not tuned after the 12-07 read (it is frozen in the prereg).

### 6.2 Preliminary numbers (in-memory run on the existing cands file; no throttle, free-balance or stuck arm yet; point estimates, no CI)

| K | p_amb = 0 p50/p90 | 0.18 p50/p90 | 0.33 p50/p90 |
|---|---|---|---|
| 1 (today) | 0.273 / **0.491** | 0.549 / 0.643 | 0.686 / 0.736 |
| 3 | 0.0 / 0.244 | 0.094 / 0.269 | 0.227 / 0.329 |
| 4 | 0.0 / 0.156 | 0.018 / 0.172 | 0.084 / 0.203 |
| 6 | 0.0 / 0.0 | 0.0 / 0.012 | 0.005 / 0.027 |

- These are not binding. Do not rely on K=6 until the CI and the three added arms run (M-M3).
- Caveats that travel with every result: hold inputs contain no NO ≥ 0.90 order and every AMBIGUOUS order was YES; n_amb = 7 forces pinned branch constants; candidates are first-row, take-all and tie-free (they understate same-slug ladder retries). The result is a **build gate only**, with no claim about NO ≥ 0.90 ambiguity or hold times.

## 7. Risks, kill criteria, rollback

| # | Risk | Sev. | Containment |
|---|---|---|---|
| R1 | Same-slug temporal bleed (late fill into a new slot's baseline) | High | Cool-off 120 s (§3.8); WP7 test; exit/entry both orders |
| R2 | Stuck slots eat K | High | §3.6 breaker (≥2 stuck); the open-ambiguous fraction bound; operator clear is the only exit besides the resolver |
| R3 | Exposure across restart or day roll | High | §3.5 registry, `uncharged` path, `_unbounded` fail-closed; WP3/WP4 tests |
| R4 | Scoped refusals mis-cleared, or unscoped missed | High | K_eff=1 stays unscoped; H8 and the dedupe tests in both directions |
| R5 | Firewall or ordering pin drift | Med | Named rows only; same-strength rewrite; banned-word scan |
| R6 | v2 bytes read by a stale supervisor | High | WP5a first; marker and live-pid check re-evaluated at every 1→2 transition; ≤1-open writes v1 |
| R7 | Resolver latency from round-robin | Low | ≤(K−1)×5 s vs the 120 s floor; no gate depends on it |
| R8 | Native drops (throttle/free-balance) lose burst candidates | Med | Modelled in d̂ (§6); the rate is not raised here |
| R9 | Concentration: the whole budget deployed in one correlated 5 s repricing | Med | Telemetry plus the first-5 s arm; no new cap invented here; for the operator's visibility only |
| R10 | Population mismatch in the hold inputs | Med | Caveat; build gate only |

**Kill criteria.**
- WP0 stop rule (§6.1): shelve if it fails.
- Any duplicate-order evidence in WP7.
- A red full gate after the re-pin.
- An allowlist change that cannot be a named row.
- Runtime: the §3.6 breaker.

**Rollback.**
1. K_eff stays 1 until the gated activation. Every earlier merge is behaviourally neutral by the proof in §3.2.
2. To revert after K>1: halt (breaker or operator), drain until ≤1 slot is open, whereupon the table has been rewritten as v1. Then set K=1 and revert code with its pin in the same commit.
3. A rolled-back supervisor cannot admit v2, so the node refuses further 1→2 transitions. If a v2 table is open at that moment, the old supervisor refuses launch; the CLI (WP5a) can clear by intent id.
4. The halt drop-in and `BREEZY_ORDERS_ENABLED` are never touched.

## 8. Named deliverable: execution-design prereg (ruling 9, M-prereg)

The capability build needs no prereg (no screen claim; `PREREG.json` untouched). **Trading a 12-07 WINNER through K>1 does.** The screen scored drops as losses. Parallel execution fills those candidates, so it changes slippage, timing, ambiguity mix and rate-limit behaviour, and none of that is validated by the screen.

**Deliverable D-PREREG** (not written here; the coordinator owns it; frozen before the 2026-12-07 read; never edited afterwards):
- K, `f`, and the slug cool-off.
- The stuck definition, breaker numbers (≥2 stuck; fraction `f`) and the duplicate-order test.
- The ramp (for example K=2 first) and stop criteria under parallel execution.
- The evidence to hold K at 1 (the WP0 CI result, the WP7 drills).
- Operator caps referenced, not assigned.

WP7's K proposal and any K>1 activation are blocked on D-PREREG's frozen SHA.

## 9. Open questions for peer review

1. **Gate position.** Is the argument in §3.3 for keeping the admission gate before the veto (instead of after the body build) acceptable? I think yes: it keeps the `<` chain and needs no body field.
2. **Permit seeding at boot.** The permit is debited for open boot intents and stays debited (D3 gives no restore). Conservative, but is the lost session capacity acceptable?
3. **Fraction bound `f = 0.50`.** Is a 50% default right, and should it apply to all open intents (as built) or only to AMBIGUOUS ones?
4. **Realized-cost addition on an uncharged fill.** It counts only fills whose day is today. Is cross-day handling (fill resolved after the day roll) correct to ignore for budget, since a prior-day spend is "gone" by existing design?
5. **Per-slug decode.** Is skipping an unreadable slot (with admission quarantine) safe, or should it halt the family?
6. **Cool-off in memory.** Is lack of durability across restarts acceptable, given the durable strategy re-arm delay?
7. **Marker re-evaluation cost.** The predicate stats a file at each 1→2 transition. Acceptable inside `arm_slot` (runtime layer, not the adapter)?
8. **Duplicate-order test.** `delta > wire qty` assumes one slot per slug and no manual trades on that slug. Manual trading on the account would trip it. Is that acceptable (fail closed)?

## 10. Change log (review finding → r2 resolution)

**Architecture review (A-)**

| ID | Resolution |
|---|---|
| C1 WP order | §3.2, WP5a before WP4; the marker capability field; the node writes v2 only when admitted, else K_eff=1; behaviour-neutral claim restated with a 5-part proof. |
| C2 enumeration | §3.1: the table IS the record; one atomic `set`; no scan or index; slug stored in each record. |
| H-a H1 location | §3.3: the gate stays before the veto (evidence given); the pin widened by one named row; `base_slug_of`; the body-equality check. |
| H-b K-full permit waste | §3.3: the full `admit` runs before spend; `arm_slot` is the arbiter and reuses `admit`. |
| H-c resolver guards | §3.4 H7 `is_open_intent`; named rows; the slot-B-resolves test. |
| H-d `_refuse` dedupe | §3.4: `(reason, instrument)`; scoped AMBIGUOUS pinned DURABLE; the `_map_position` test. |
| H-e in-flight id | §3.4 H0: frozenset. |
| H-f F14/H6/UNBUDGETED | §3.5: seed with zero fills; settle/release on retire; the matching condition at the fill sites; D3. |
| H-g missed readers | §1 consumer table; WP5a and WP6. |
| M1 tombstone | §3.1: v1 bytes while ≤1 open; a valid v1 RETIRED record on the last retire; the CLI is tolerant (WP5a). |
| M2 global backoff | §3.4 H5: the global counter drives the sleep; per-intent only for selection. |
| M3 throttle drops | F20, §2 and §6: modelled as a drop. |
| M4 free-balance | §2, §6.1: modelled as a drop arm; WP0 verification. |
| M5 `admit` parity | §3.3: `arm_slot` calls it; the exec client uses the named wrapper `admission_refusal`. |
| L1 typing | WP1 Protocol. |
| L2 exception | §3.3: reuse `SubmitIntentLatched`. |
| L3 `_refuse` pin | §3.4 (pin-neutral, confirmed). |
| Facts 1-8 | F6 (:3502), F13, F14/F15/§3.5 (K=1 gap is zero; the gap exists only at K>1), the F5 table, the H1/H2 locations, H4, and §3.9 (throttle). |

**Safety review (S-)**

| ID | Resolution |
|---|---|
| C1 guards | H7, plus six sites listed in F12. |
| C2 enumeration | As A-C2; the slug is in the record; the crash-at-each-set test (WP2). |
| C3 order | As A-C1. |
| C4 re-book | §3.5: the exact API, release on retire, D3, the UNBUDGETED condition, and tests. |
| H-1 dedupe | As A-H-d, with the two-slug test. |
| H-2 slug at :6110 | §3.3/§3.4: `base_slug_of(order.instrument_id)` at the top; the equality test. |
| H-3 exit/strategy readers | §3.7, WP6, F5 table. |
| H-4 exits compete | §3.7: K-exempt, slug-exclusive, scope-aware `exit_guard`. |
| H-5 in-flight id | H0. |
| H-6 K-full waste | §3.3. |
| H-7 corrupt stall | §3.1 per-slot decode; §3.4 skip and per-key log. |
| M1 CLI/rollback | WP5a; §3.1 v1 return; the drill tests. |
| M2 analysis undercount | WP5a RED tests (open, not absent). |
| M3 backoff | A-M2. |
| M4 starvation | The H5 order key includes per-intent backoff. |
| M5 contextless slot | §3.1 slug in the record; §3.5 unknown notional is unbounded and fail-closed. |
| M6 firewall pin | §3.3, WP4: a same-strength rewrite and the per-allowlist row listing. |
| M7 rate/permit | F20: the throttle is upstream of the permit, so no permit waste; modelled as a drop. |
| L1-L4 | L1 confirmed pin-neutral; L2 DURABLE pin test; L3 the record carries and verifies the slug; L4 the F5 FQ correction and the `fill_time_count` verification in WP0. |

**Market review (M-)**

| ID | Resolution |
|---|---|
| H-1 day roll | §3.5 invariant restated; open bookings carried at the day roll; a test. |
| H-2 re-book gaps | §3.5: zero fills, context-less (unbounded, no cap read), over-budget with the resolver live, the double-count documented, and tests. |
| H-3 breaker | §3.6: frozen numbers, CONTRADICTION counts as stuck, the duplicate test, the bound, and the never-blocks-the-resolver test. |
| H-4 in-flight id | H0 with the concurrent-POST test. |
| M-1 same-slug bleed | §3.8 cool-off; WP7 late-fill and exit/entry tests. |
| M-2 concentration | R9, telemetry (WP5b), the first-5 s arm (§6.1), no new cap. |
| M-3 viability | §6: the bootstrap CI upper bound; the throttle as a drop; the free-balance arm; K=6 not relied on until run; a build gate only. |
| M-4 K frozen | §8: K and `f` frozen in the prereg before the read. |
| Prereg | §8: D-PREREG named, not written. |
| L-1 to L-4 | The rollback drill (WP5a/WP7); round-robin latency in §3.9; the `_refuse` pin confirmed; the arbiter and loser-release in §3.3. |
