# PLAN r1: Bounded per-market-slug parallel submit intents (EXEC-PAR)

Status: DRAFT r1 for peer review. Build-time only. This plan builds capability and does not re-enable orders.
Author: trading-bot-architect. Read-only investigation. Nothing was edited, staged or saved by me.

## 0. Hard invariants (restated, binding on every WP)

1. Nautilus Trader is immutable. Extend it only through native mechanisms: the injected `StateStore`/latch and `LiveExecutionClient`.
2. `allow_short` stays `False`. NO buys stay represented as they are today.
3. Never weaken or delete a safety, settlement, contract, NO-SEND egress-firewall or import-pin test.
   - Widen exact sets only by named rows, keeping `==`.
   - Put the firewall guards in every focused gate list. A focused gate that omits them has already missed this class of failure.
4. `exec/client.py` is byte-pinned (`_EXEC_CLIENT_SHA256`).
   - The resolver floors (`_RESOLVER_ZERO_FILL_MIN_AGE_NS` 120 s, `_RESOLVER_NO_ID_MIN_AGE_NS` 300 s) are never lowered.
   - Re-pin procedure is in WP4.
5. Operator caps (max daily budget, max per position = per order) are never assigned, read into a new literal, or defaulted.
   - Aggregate open exposure across parallel intents must be bounded by the daily budget at submit time.
   - AMBIGUOUS intents count at full notional until retired.
6. `BREEZY_ORDERS_ENABLED`, permit minting and the `fq-v1-halt-orders-off.conf` drop-in are untouched. No WP enables trading.
7. No mypy ceiling raise. No `type: ignore`, `Any` or `cast` in new code.
8. No `PREREG.json` edit.
9. M1-v3 window outcomes and tape for 2026-10-07..11-28 are never read.
   - Every offline tool refuses inputs on or after 2026-10-07 (pattern: `test_refuses_any_input_on_or_after_2026_10_07`).

## 1. Verified current-state facts (file:line, checked in code 2026-10-10)

**Latch and intent lifecycle**
- F1. The intent store is a singleton. `CURRENT_INTENT_KEY = "exec/polymarket_us/intent/current"`, `_SCHEMA_VERSION = 1` (`src/breezy/runtime/submit_intent.py:37-38`).
- F2. `arm` raises `SubmitIntentLatched` if the singleton is OPEN (`submit_intent.py:399-427`, check at :416). A corrupt singleton counts as latched (:386-397).
- F3. `retire` writes history (`history_key(intent_id)`, :56-65) before the singleton (:493-511). `reconcile_at_startup` (:449-491) copies history back, or retires on a durable fill record.
- F4. The resolver context is already per-intent: `RESOLVER_CONTEXT_KEY_PREFIX + intent_id`. See `AmbiguousResolverContext` (`client.py:1094-1166`), which carries `notional_usd`, `booking_id`, `wire_market_slug`, `wire_price`, `wire_outcome_side`, `wire_action` and the holding baselines.
- F5. The singleton assumption is deep. Callers of the latch or intent state include:
  - `app/trade.py`;
  - `runtime/trade_supervisor.py` (`probe_open_intent*` at :431-501);
  - `runtime/clear_submit_intent_cli.py`;
  - `analysis/labeling/prelaunch_intents.py` and `analysis/fill_time_count.py`;
  - `strategy/current_rung_hold/{continuous_strategy,trial_day_latch,exit_wiring,composition}.py`;
  - `strategy/forecast_quantile_ladder/{decision,strategy,persistent_latch,latch,composition}.py`;
  - `adapters/polymarket_us/exec/{client,reports}.py`.

**Submit path (`_submit_order`, `client.py:6106-6347`)**
- F6. A global refusal gate sits at :6110. A non-empty `_trading_refusals` denies every order.
  - The AMBIGUOUS refusal is appended unscoped (`_refuse`, :6685; `instrument=""` per its docstring at :6706).
  - It is appended at :6333 (POST exception) and :6580 (classified AMBIGUOUS).
  - It is cleared only in the resolver (:3274-3282, :3498-3514, :4106-4115), and only while `self._latch.current_open() is None`.
  - **This is a second singleton, independent of the latch.** The earlier analyses (r4.3) did not name it.
- F7. The latch gate is `is_latched()` → `OPEN_INTENT_WAIT_REASON` (:6204-6205). It is a WAIT, with no money or permit spent. It runs synchronously with no `await` before `arm` (:6291).
- F8. Order of effects:
  1. body build and fingerprint (:6226-6237);
  2. permit authorise and consume (:6238-6254);
  3. `ledger.authorize_order_cost` (:6276);
  4. `_intent_reconciled` check (:6286);
  5. `latch.arm` (:6291);
  6. `_note_ambiguous_open` pre-POST context (:6303);
  7. POST (:6327).
  - A denial after step 2 wastes a permit slot. The latch gate at F7 precedes it for that reason.
- F9. Nautilus itself already runs each `SubmitOrder` as its own task (`live/execution_client.py:277-282`). There is no native serialisation.

**Resolver (`_resolve_ambiguous_intents`, `client.py:2533`)**
- F10. It processes exactly one intent per pass: `current = self._latch.current_open()` (:2670).
  - `_RESOLVER_POLL_INTERVAL_SECS = 5.0` is at **:588** (not :587 as r4.3 cites).
  - `_RESOLVER_BACKOFF_CAP_SECS = 300.0` at :592.
  - `_RESOLVER_ZERO_FILL_MIN_AGE_NS = 120 s` at :1596.
  - `_RESOLVER_NO_ID_MIN_AGE_NS = 300 s` at :1604.
  - The with-id age gate is at :3089. The no-id age gate is at :3752.
- F11. `_resolver_consecutive_failures` is one global counter driving the backoff (:2614-2621). One stuck intent slows resolution of every other one.
- F12. The resolver coroutine is firewall-scanned (E0-NOSEND-RESOLVER).
  - Its bodies are deliberately inlined. A new callee needs a named allowlist row (comments at :2603-2621, :2639).
  - `_submit_order` is covered by `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (comment at :6124-6127).

**Exposure and permit**
- F13. `DailySpendLedger.authorize_order_cost` books at submit under one lock (`operator_controls.py:348-427`).
  - It checks `cost > position_cap` (:387) and `_spent_usd + cost > daily_budget` (:418).
  - A booking stays at full cost until `true_up_booking` or `release_booking` (:457-523).
  - Ambiguous bookings persist in `self._ambiguous_bookings` (`client.py:6344`).
  - The ledger is in-memory and process-local (docstring :271-275).
  - **So the aggregate-open-exposure invariant already holds in-process.** It is thread-safe and counts AMBIGUOUS at full notional.
- F14. **Restart gap.** `_seed_spend_from_durable_fills` seeds only durable FILL records (`client.py:2370-2429`).
  - `AmbiguousResolverContext.booking_id` is "process-local ONLY" (:1100-1103). The reminted budget "starts whole".
  - With a singleton the gap is at most 1 × per-order cap. With K parallel intents it is up to K × per-order cap above the daily budget after a restart. This is the one new exposure hole the redesign opens, and WP3 must close it.
- F15. The permit budget is per-permit and thread-safe (`safety.py:349-358, 1032-1044`).
  - It enforces `remaining_order_count` and `remaining_notional_usd` at consume, and is restored on a confirmed zero-fill.
  - Per-order notional is checked against `permit.max_order_notional_usd` (:1010).

**Boot**
- F16. `_reconcile_submit_intent` (`client.py:2312-2330`) runs `latch.reconcile_at_startup`, then sets `_intent_reconciled = True`. Until then every order is denied `RECONCILE_NOT_RUN_REASON` (:6286-6289).
- F17. The supervisor refuses to launch on an OPEN or corrupt singleton unless it is resolvable. A resolvable OPEN decodes and is OPEN; the node's resolver retires it (`trade_supervisor.py:452-471`).

**Venue and Nautilus config**
- F18. The venue has no client-order-id, so there is no dedupe.
  - `node_config.py:895-901` says a native in-flight timeout "resolves as FAILED an order we have no id with which to ask about", a false terminal that is "the first step toward a doubled position".
  - Native in-flight checks are therefore deliberately disabled: `LiveExecEngineConfig(inflight_check_interval_ms=0)` at :1036.
- F19. Native `RiskEngine` is configured with:
  - `max_notional_per_order` (operator value);
  - `max_order_submit_rate="5/00:00:01"` (`node_config.py:698, 751-763`). Its comment says it "can never bind behind" the singleton. **With parallelism it can bind. That comment becomes false and must be restated** (WP5).
- F20. Venue limit: 20 requests/s per API key; Breezy's global budget is 15/s (`transport.py:111-125`). The resolver's per-pass reads (order GET, positions, up to `_RESOLVER_ACTIVITY_MAX_PAGES = 20` activity pages at :1585) share it.
- F21. The WS subscription cap is 10 per connection, shared across MARKET_DATA and TRADE (memory `venue-ws-subscription-cap-is-shared`).
  - The exec path is REST POST/GET only. I found no WS subscription in `exec/client.py`.
  - The node keeps `subscribe_trades` off (memory). WP0 re-verifies this from `node_config`.
- F22. YES and NO legs are separate Nautilus instruments on one venue market slug. `base_slug_of` and `leg_of` are at `symbology.py:289-298`. The venue nets a NO holding as short YES (memory `venue-nets-no-holding-as-short-yes`).

**Pins**
- F23. The pin lives at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`. `tests/unit/test_autonomy_envelope.py:901-916` reads it by AST from that single home. Only one value changes on a re-pin.

**Premise audit of the task statement**
- P1. Constants 120 s, 300 s, 5 s and 300 s are CORRECT. The poll constant is at :588, not :587.
- P2. "42% within 5 s" is CONFIRMED (`stage_minus1_triage_results.json`, main4 `share_first5s` = 0.4204; n = 333 candidates, 33 of 37 days).
- P3. "d̂_p90 ≥ 0.49 at p_amb = 0" is NOT in the checked-in script, which runs p ∈ {0.10, 0.18, 0.33} only.
  - I re-ran its model in memory on `stage_minus1_triage_cands.json` (pre-10-07 only, nothing written).
  - K = 1, p_amb = 0 gives p90 = **0.491**. It is confirmed. WP0 commits the arm.
- P4. "Drop" is a screen-parity policy of the shelved family (`r4_3_delta` A.6). In the code, a latched candidate is a **WAIT**, not a destroyed candidate.
  - See `OPEN_INTENT_WAIT_REASON` (`client.py:6205`) and the strategy pre-filter that re-ticks (`continuous_strategy.py:1908-1928`).
  - A candidate that persists past the 150 s hold could be retried. That is exactly why the screen scores it as a loss.
  - This plan does not rely on retry. It removes the cause instead.

## 2. Native-Nautilus gap analysis (null hypothesis tested)

| Capability needed | Native provides? | Verdict |
|---|---|---|
| Concurrent order submission | Yes. Each `SubmitOrder` runs as its own task (F9). No native singleton exists. | NO GAP. The serialisation is Breezy's, and it is a venue-safety control. |
| Per-instrument order state, OMS NETTING | Yes: ExecEngine plus Cache. | Used as-is. Not sufficient for ambiguity resolution (next rows). |
| Resolving an unknown-fate IOC | In-flight check (`_check_inflight_orders`) queries the venue, then force-resolves as FAILED after retries. | **GAP, proven by F18.** No client-order-id means a false terminal. Native in-flight stays disabled. |
| Order-fate evidence | `generate_order_status_report(s)`, `generate_mass_status`. | Used by the bespoke GET resolver. The resolver deliberately bypasses `generate_order_status_report` because it collapses four failure shapes into `None` (docstring at `client.py:2559-2564`). |
| Pre-trade per-order notional cap | `RiskEngine.max_notional_per_order`. | Already used; retained. |
| Submit rate cap | `max_order_submit_rate` (5/s). | Retained; becomes live (F19). Do not raise it in this plan. |
| Aggregate open exposure bounded by a daily budget | Not native. | Stays with `DailySpendLedger` (F13). WP0 confirms by reading `risk/engine.pyx` that no cumulative daily cap exists. |
| Per-slug open-intent uniqueness with durable crash recovery | Not native. | **GAP.** Built as an extension of the existing injected latch seam, not a parallel framework. |

Conclusion: Nautilus already provides concurrency, per-order caps and rate caps. The only gap is venue-specific (no client-order-id), so slug-scoped durable intent state and a bounded resolver are required. This is a native-extension build on the existing injected-latch seam (`app/trade.py:3-9`), with no Nautilus change.

## 3. Design options

### Option A (RECOMMENDED): per-market-slug slots plus a global bound K

- One OPEN intent per **base market slug** (`base_slug_of`, so YES and NO legs share a slot; F22).
- At most **K** OPEN intents globally.
  - K is a Breezy-stated `Final` constant in `node_config.py`, in the same style as `TRADE_RISK_MAX_ORDER_SUBMIT_RATE`.
  - K is never env-derived and is not an operator cap.
  - Default **K = 1**, which is bit-identical to today's behaviour.
  - Raising K is a separate gated commit after WP7 (recommend 6).
- A slot stays held while the intent is AMBIGUOUS, until the resolver retires it. Resolver floors are unchanged.
- The AMBIGUOUS refusal becomes **slug-scoped**.
  - Only that slug's submissions are denied while its slot is open.
  - An unscoped/DURABLE refusal still halts everything (unchanged).
- Why per-slug and not anonymous slots:
  - With no client-order-id, a no-id AMBIGUOUS is attributed by the wire echo (`wire_market_slug`, `wire_price`, `wire_outcome_side`, `wire_action`) plus a slug-level holdings baseline (`baseline_venue_net`, `baseline_durable_net`; F4).
  - Two concurrent in-flight orders on the same slug make that attribution ambiguous. Different slugs cannot cross-contaminate.
  - So same-slug exclusion is a **safety necessity**, not a tuning choice. Option B inherits it anyway.

### Option B: bounded global parallel slots (K anonymous intents)
- Simpler store, but it must still enforce same-slug exclusion to keep attribution valid, so it collapses into A with a weaker key.
- Rejected as a standalone option.

### Option C: queue with expiry (keep the singleton, hold candidates)
- It cannot beat the floors. One ambiguous order still blocks ≥ 120 s.
- It trades staleness risk for delay and violates the "no queue" parity of the screen.
- Rejected. Offline numbers in §5 show serial K = 1 fails even at p_amb = 0.

### Option D: out-of-process order router or second exec client
- Violates single-writer discipline and the one-latch-per-process model (`app/trade.py:3-9`). It adds a second flock domain and a reconciliation surface.
- Rejected.

### Trade-offs of A against the five required axes

1. **Safety under AMBIGUOUS**
   - The blast radius shrinks from "everything" to "that slug plus one of K slots".
   - A stuck intent (the 96,823.9 s MIA order) permanently consumes a slot.
     - Mitigation: a K-stuck breaker (§6) halts the family when stuck slots ≥ ceil(K/2).
     - Mitigation: the existing K6-style bound (OPEN at 13:00Z, or age > floor + 600 s) applies per slot.
   - The unscoped global refusal path is unchanged for DURABLE refusals (fee drift, fill-write failure, unreconciled).
   - A no-id AMBIGUOUS keeps its existing 300 s floor and holding-baseline attribution, now per slug.

2. **Exposure accounting**
   - The in-process ledger already satisfies the invariant (F13). WP3 adds a concurrency property test: N concurrent `authorize_order_cost` calls never exceed the daily budget, including AMBIGUOUS bookings.
   - WP3 closes the restart gap (F14): at boot, OPEN intents' `notional_usd` (from the resolver context, F4) is added to the ledger seed and the permit seed. This is fail-closed.
     - If any OPEN intent has no readable context, assume the full per-order cap per such intent.
     - If the sum cannot be bounded, deny all orders (`_intent_reconciled` stays False).
   - K is not an operator cap. Worst-case open notional is min(K × per-order cap, daily budget remainder). The ledger remains the sole authority.

3. **Venue rate limits**
   - POST burst: the native 5/s `max_order_submit_rate` now binds. Seen from a 5 s window, 42% of about 9 candidates is about 4 orders, which fits. WP0 simulates the token bucket.
   - Resolver reads: the resolver stays **one intent per pass**, round-robin over open slots, by oldest-unserved. GET load stays at the current per-pass level, under the 15 req/s budget.
   - Resolution latency for a slot rises by up to (K − 1) × 5 s. This is immaterial against the 120 s floor.

4. **WS subscription cap (10, shared)**
   - No new subscriptions. Fill detection stays GET-based. A WP guard test asserts the node config does not enable `subscribe_trades` or add private subscriptions.

5. **Boot-time unresolved-intent handling**
   - The legacy singleton OPEN is adopted into a slot using `context.wire_market_slug`.
   - If there is no context, or the slug is unknown, a **global quarantine** applies: no submissions until operator clear. This matches today's behaviour.
   - The supervisor launches when every OPEN record decodes and has a context (the `probe_open_intent_resolvable` generalisation). It refuses only on corrupt or unknown-slug records.
   - New submits on other slugs are allowed only after `_intent_reconciled` and the exposure re-booking succeed.

**Schema fence and rollback (decision for review).** The first slot write rewrites `CURRENT_INTENT_KEY` as a v2 tombstone. Old code reads it as `SubmitIntentCorrupt`, so it is latched and the supervisor refuses to launch it: a fail-closed rollback. Rolling back therefore needs a drain (all slots RETIRED) and an operator `breezy-clear-submit-intent`.

## 4. Work packages (TDD order)

Common gate list (run after every WP; the full suite after every merge):
- Interpreter: `PYTHONPATH=/home/jon/breezy/src /home/jon/breezy/.venv/bin/python -m pytest`.
- Use `--basetemp` under `~/.cache`, never `/tmp` (tmpfs fills RAM).
- Run from the tree's own cwd: `lint-imports` (demand "N kept, 0 broken"), `ruff`, `mypy` (no ceiling change).
- `scripts/ci/run_tests_no_egress.sh` for the full gate. Read the exit code, not the tail; never chain push after the gate.
- Focused lists MUST include these. Omitting them has produced false-green stacked gates:
  - `tests/unit/test_execution_egress_firewall_guard.py`;
  - `tests/unit/test_polymarket_us_exec_client.py`;
  - `tests/unit/test_submit_intent_latch.py`;
  - `tests/unit/test_current_rung_hold_ambiguous_resolver.py`;
  - `tests/unit/test_edge2_ac6b_cross_process_fill_budget.py`;
  - `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`;
  - `tests/unit/test_autonomy_envelope.py`;
  - `tests/contract/test_live_fill_scoring_chain_contract.py`;
  - `tests/unit/test_exec_refusal_health_surface.py`;
  - the import-pin and citation-map tests;
  - all `test_autonomy_*`.
- Briefs for implementers must say the following:
  - use the exact interpreter above, never `uv run` or `pip`;
  - format only your own files;
  - never `git stash` (blocked by hook);
  - give each agent its own scratchpad;
  - put `PYTHONPATH` of the worktree first, so tests do not silently check the primary tree.

### WP0: offline viability and premise verification (no production code; gates the rest)
- Files (new, `docs/evidence/m1v3/`): `exec_parallel_dhat.py` (adapted from `stage_minus1_triage_dmix.py`, keeping its pre-window `FIRST/LAST` bounds); results JSON.
- RED tests (`tests/unit/test_exec_parallel_dhat.py`):
  - `test_refuses_any_input_on_or_after_2026_10_07`;
  - `test_k1_reproduces_serial_baseline_p0_p90_0_491`;
  - `test_k1_reproduces_triage_p018_p90_0_645_and_p033_0_737`;
  - `test_distinct_slug_never_blocks_distinct_slug`;
  - `test_same_slug_blocked_until_hold_elapses`;
  - `test_yes_and_no_leg_share_one_slot_by_base_slug`;
  - `test_hold_constants_match_exec_client_source_ast` (`ast` parse, no import, so the exec import pin is not tripped);
  - `test_submit_rate_token_bucket_5_per_s_applied`;
  - `test_stuck_slot_sensitivity_reduces_effective_k`.
- Verifications to record with file:line (premise check before the peer loop):
  - `risk/engine.pyx` has no cumulative daily cap (§2);
  - `base_slug_of` maps both legs to one slug (F22);
  - `node_config` leaves `subscribe_trades` off (F21);
  - `ClassifiedRefusal` can carry a slug (`refusals.py:213-227`), yet `_refuse` writes `instrument=""` (F6).
- Stop rule: if the K = 6 arm with the stuck-slot sensitivity exceeds p90 0.30 at the Wilson-upper p_amb, STOP and shelve the plan.
- Gates: unit tests, ruff, mypy.

### WP1: pure admission and exposure model (domain; no I/O)
- File: `src/breezy/domain/exec_intent.py` (existing, adapters already import it) or a new sibling `exec_slots.py`.
- Sketch:
  - `admit(open_slugs: frozenset[str], slug: str, k_max: int, quarantined: bool) -> Admit | Wait(reason)`;
  - `aggregate_open_notional(open_notionals) -> Decimal`;
  - frozen dataclasses only; no `Any`.
- RED tests (hypothesis where noted):
  - `test_admit_denies_same_slug`;
  - `test_admit_denies_at_k_max`;
  - `test_admit_k1_equals_legacy_singleton_for_any_slug` (property: identical decisions to the singleton model);
  - `test_admit_denies_all_when_quarantined`;
  - `test_admit_is_pure_and_deterministic` (property);
  - `test_aggregate_never_negative_or_nan` (property).
- Gates: unit, `lint-imports` (domain stays below adapters), mypy.

### WP2: durable slot latch (runtime; the store seam)
- File: `src/breezy/runtime/submit_intent.py`, or a new `runtime/submit_intent_slots.py` re-exported by it. Not byte-pinned.
- Contents:
  - keys `exec/polymarket_us/intent/slot/<sha256(base_slug)[:32]>`;
  - schema v2;
  - `arm_slot(fingerprint, slug, now_ns)`;
  - `open_intents()`;
  - `is_slug_latched(slug)`;
  - `retire` unchanged in ordering (history first, then slot);
  - v2 tombstone fence at `CURRENT_INTENT_KEY`;
  - legacy-singleton adoption;
  - `reconcile_at_startup` per slot.
- RED tests (extend `tests/unit/test_submit_intent_latch.py` conventions and `ambig_latch_rig.py`):
  - `test_arm_slot_refuses_same_slug_and_allows_other_slug`;
  - `test_arm_slot_refuses_at_k_max`;
  - `test_crash_between_history_and_slot_write_leaves_slot_open_and_recoverable` (a store failure injected at each `set`);
  - `test_corrupt_slot_record_quarantines_all_submissions`;
  - `test_legacy_open_singleton_adopted_into_slot_by_context_slug`;
  - `test_legacy_open_without_context_global_quarantine`;
  - `test_first_slot_write_fences_singleton_as_v2_so_v1_reader_is_latched`;
  - `test_two_concurrent_arm_slot_calls_one_wins_per_slug` (mutex and flock);
  - `test_retire_wrong_slot_raises_mismatch`.
- Gates: the focused list plus `lint-imports` ("adapters never import `breezy.runtime`"; the adapter reaches the new API only through the injected latch object).

### WP3: exposure accounting under concurrency and restart (adapter-side tests first; the code lands in WP4)
- RED tests (new `tests/unit/test_exec_parallel_exposure.py`):
  - `test_n_concurrent_authorizations_never_exceed_daily_budget_counting_ambiguous` (hypothesis; `DailySpendLedger` plus the fake latch);
  - `test_ambiguous_booking_held_at_full_cost_until_retire`;
  - `test_boot_rebooks_open_intents_notional_into_ledger_and_permit`;
  - `test_boot_open_intent_without_context_assumes_full_per_order_cap`;
  - `test_boot_unbounded_exposure_keeps_intent_reconciled_false`;
  - `test_operator_caps_never_assigned_or_defaulted` (AST scan for new literals on the cap env paths).
- These tests stay RED until WP4 and are merged with it.

### WP4: exec client wiring (byte-pinned; the only edit to `client.py`)
- Hunks, each minimal and annotated with the hunk ID in the re-pin comment:
  - **H1** (:6204): `is_latched()` → `is_slug_latched(slug)`, the slug derived from `body["marketSlug"]`, i.e. before any permit spend. Keep a global-quarantine branch.
  - **H2** (:6110): refusal gate scopes AMBIGUOUS by slug. An unscoped or other reason still denies all. Needs a keyword-only slug on `_refuse`, which preserves the 25-site producer pin in `test_exec_refusal_health_surface.py`.
  - **H3** (:6291): `arm` → `arm_slot`. A `SubmitIntentLatched` refusal remains `LATCH_ARM_REFUSED_REASON` and releases the booking as today.
  - **H4** (:2670): `current_open()` → next-open-slot selection (round-robin, oldest unserved). The pass body is unchanged, so no `continue` semantics move.
  - **H5** (:3274, :3498, :4106): the AMBIGUOUS-refusal clear is scoped to the retired slot's slug. It no longer requires "no other OPEN intent".
  - **H6** (:2370): the boot seed adds the open intents' notionals (WP3).
  - **H7**: per-intent failure counters, replacing the single `_resolver_consecutive_failures` for slot selection. This avoids starving healthy slots behind a 503-ing one (F11).
  - **H8**: the K-stuck breaker input. The resolver exposes the open-slot ages; the breaker itself lives in the supervisor.
- Firewall allowlist rows, each added **by name, keeping `==`**:
  - `self._latch.arm_slot`;
  - `self._latch.is_slug_latched`;
  - `self._latch.next_open_for_resolution`;
  - `self._latch.open_intents`, if used.
  - Any other new callee is a plan defect: restructure instead (inline expressions).
- **Re-pin procedure.** After peer approval, edit only `_EXEC_CLIENT_SHA256` at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:37`, and append a comment in the existing style: `# re-pinned <date>: EXEC-PAR (H1-H8 per plan r?), reviewer-approved`. `test_autonomy_envelope.py` reads it by AST, so no other file needs the hash. A python-reviewer plus a prediction-market-reviewer approve the diff before the pin moves. The pin is never updated first and never in a separate "just make it green" commit.
- RED tests (extend `test_polymarket_us_exec_client.py`; use `ambig_latch_rig.py`):
  - `test_two_distinct_slugs_submit_concurrently_with_both_posted`;
  - `test_same_slug_second_order_is_wait_with_no_permit_or_booking_spent`;
  - `test_ambiguous_on_slug_a_does_not_deny_slug_b`;
  - `test_ambiguous_refusal_cleared_only_for_its_slug_on_retire`;
  - `test_durable_refusal_still_denies_all_slugs`;
  - `test_resolver_visits_each_open_slot_round_robin`;
  - `test_resolver_floors_unchanged_120_300_5_300`;
  - `test_one_503_ing_slot_does_not_stall_other_slots`;
  - `test_k1_behaviour_identical_to_singleton` (replay of the existing singleton fixtures);
  - `test_post_in_flight_tracking_correct_for_k_gt_1`.
    - Note: `_post_in_flight_intent_id` is a single field (:6325). It must become per-slot, or its readers must be shown not to need it. This is an open question.

### WP5: supervisor, CLI, native config, analysis readers
- Files:
  - `runtime/trade_supervisor.py` (probes at :431-501, plus the K-stuck breaker);
  - `runtime/clear_submit_intent_cli.py` (per-slot clear, with a drained-check before it clears the fence);
  - `runtime/node_config.py` (the K constant, default 1; restate the `max_order_submit_rate` comment at :681-698);
  - `analysis/labeling/prelaunch_intents.py`, `analysis/fill_time_count.py`, `scripts/ops/ambig_latch_phase_a_check.py`.
- RED tests:
  - `test_probe_open_intents_lists_all_slots`;
  - `test_launch_refuses_only_on_corrupt_or_contextless_slot`;
  - `test_k_stuck_breaker_trips_at_ceil_k_half_stuck_slots`;
  - `test_breaker_never_retires_an_intent`;
  - `test_clear_cli_requires_drain_or_explicit_slot`;
  - `test_node_config_k_is_final_constant_not_env_derived`;
  - `test_node_config_does_not_enable_subscribe_trades`;
  - `test_inflight_check_interval_ms_still_zero`.

### WP6: strategy read-side (existing families only; the new family consumes it later)
- Files: `strategy/current_rung_hold/{continuous_strategy,trial_day_latch,exit_wiring}.py` (`is_intent_open` at :1713, :1918, :2496); `strategy/forecast_quantile_ladder/{decision,persistent_latch,latch}.py`.
- Replace `is_intent_open()` with `is_slug_intent_open(slug)`. Keep a `DiagnosticsKey` for the old WAIT.
- Keep the strategy's own `_REARM_MIN_DELAY_SECS = 120` (`continuous_strategy.py:249`). The test that pins it equal to the resolver floor stays.
- RED tests:
  - `test_hunt_proceeds_on_other_slug_while_one_slug_intent_open`;
  - `test_hunt_waits_on_same_slug`;
  - `test_rearm_delay_equals_resolver_zero_fill_floor` (existing; unchanged).
- Gates: `tests/unit/test_current_rung_hold_*`, `tests/contract/test_rung_hold_families_mutual_exclusion_contract.py`.

### WP7: failure injection, replay, shadow soak (no live)
- RED tests, in the failure-injection style of `ambig_latch_rig.py`:
  - `test_crash_at_every_line_between_arm_slot_and_post_no_double_order_on_restart`;
  - `test_timeout_on_post_leaves_slot_open_and_slug_denied`;
  - `test_partial_fill_then_resolver_accept_fill_retires_only_that_slot`;
  - `test_restart_with_three_open_slots_rebooks_exposure_and_resolves_each`;
  - `test_stale_intent_does_not_block_other_slugs_forever` (the K-stuck path);
  - `test_replay_bit_for_bit_with_fixed_clock`.
- A paper/dry-run soak is separate and operator-neutral. Capability only; no enablement.
- Deliverable at WP7 exit: a proposal commit to raise K from 1 to 6. It is evidence-gated and goes through its own peer review.

Ordering and dependencies: WP0 → WP1 → WP2 → (WP3 tests with WP4) → WP5 → WP6 → WP7. WP5 and WP6 are independent of each other after WP4 and may run in parallel. Each WP lands as its own gate-green merge; the supervisor needs a restart after WP5 to load the code. Because K defaults to 1 until the last proposal, every merge before then is behaviour-neutral.

## 5. Viability metric and offline measurement

**Metric.** d̂_p90 is the 90th percentile across pre-window days of the per-day dropped share of candidates. The model draws 1,000 hold samples per day, following `stage_minus1_triage_dmix.py`. STOP iff d̂_p90 > 0.30.

**Data (pre-2026-10-07 only):**
- `docs/evidence/m1v3/stage_minus1_triage_cands.json` holds `(ts_event, station)` per candidate, 333 candidates, 33 days.
- It lacks the instrument. WP0 re-extracts candidates by running the existing pre-window extractor, keeping the instrument id and base slug. Without this, the same-slug arm cannot be tested.
- `WP0_c0_pre1007_orders.tsv` supplies the hold-model inputs: n = 39 posted, 7 AMBIGUOUS, h_post p50 0.169 s, p95 0.304 s; resolution 3.2 s (accept) and 125/126/144 s (zero-fill); 2 never resolved in logs; one stuck at 96,824 s.

**Method.** Event-driven simulation per day, arrivals sorted by `ts_event`.
1. Per candidate: draw AMBIGUOUS with probability p_amb. If it is, the branch is accept 1/5 (5 s) or zero-fill 4/5 (150 s); otherwise hold h = 0.3 s.
2. Admit via the WP1 `admit` (the same function the production path uses).
3. Add the 5/s token bucket to arrivals.
4. Report d̂ p50, p90 and day-clustered SE.
5. Sensitivities:
   - a stuck slot to 13:00Z, with probability 1/5 of zero-fills;
   - no-id share (300 s + 5 s);
   - p_amb ∈ {0, 0.05, 0.10, 0.18, 0.33}.

**Preliminary results (my in-memory run on the existing cands file; main4 stations; global-slot model; every candidate is a distinct rung):**

| K | p_amb = 0 p50/p90 | 0.18 p50/p90 | 0.33 p50/p90 |
|---|---|---|---|
| 1 (today) | 0.273 / **0.491** | 0.549 / 0.643 | 0.686 / 0.736 |
| 2 | 0.091 / 0.333 | 0.256 / 0.396 | 0.429 / 0.509 |
| 3 | 0.0 / 0.244 | 0.094 / 0.269 | 0.227 / **0.329** |
| 4 | 0.0 / 0.156 | 0.018 / 0.172 | 0.084 / 0.203 |
| 6 | 0.0 / 0.0 | 0.0 / 0.012 | 0.005 / 0.027 |
| unbounded | 0 | 0 | 0 |

Reading:
- The serial latch cannot pass at any p_amb (reproduces the shelved finding).
- K = 3 fails at the Wilson-upper p_amb. K ≥ 4 passes with margin, and K = 6 leaves headroom for one or two stuck slots.
- Per-slug exclusion costs nothing on this population: every candidate is a distinct rung and there are no timestamp ties.
- **Caveats, which travel with every result:**
  - the sample has no NO ask ≥ 0.90 order in its hold-model inputs;
  - candidates are first-row-only (an idealised take-all);
  - p_amb and the branch split are pinned (n_amb = 7 < 10);
  - the 5/s bucket and stuck-slot arms are not yet in the numbers above.
- These numbers are not binding until the committed WP0 artefact exists.

**Acceptance for the plan:** d̂_p90 ≤ 0.30 at p_amb = 0.33 with one stuck slot, with the 5/s bucket on. Otherwise STOP.

## 6. Risks, kill criteria, rollback

| # | Risk | Sev. | Containment |
|---|---|---|---|
| R1 | Cross-slug attribution failure: holdings baselines or the activities feed misattribute a fill. | High | Per-slug key on the base slug; no-id attribution requires the slug echo. WP7 tests; a CONTRADICTION result keeps the slot AMBIGUOUS. |
| R2 | A stuck slot (a 96,824 s order) eats K. | High | K-stuck breaker (halts new entries; never retires). Per-slot K6 bounds. K = 6 leaves headroom. |
| R3 | Restart exposure gap (F14). | High | WP3 rebooks open notionals at boot, fail-closed. |
| R4 | The unscoped AMBIGUOUS refusal (F6) is missed in some path, leaving a hidden global halt (safe but defeats the purpose) or a premature clear (unsafe). | High | H2 and H5 tests in both directions: `test_ambiguous_refusal_cleared_only_for_its_slug_on_retire`, `test_durable_refusal_still_denies_all_slugs`. |
| R5 | A firewall or import-pin drift from new callees. | Med | Callees minimised and allowlist rows named. The firewall guard sits in every focused gate. |
| R6 | Global resolver backoff starves healthy slots. | Med | H7 per-intent failure counters. |
| R7 | `_post_in_flight_intent_id` is a single field (:6325), a possible K > 1 hazard. | Med | WP4 audit of its readers; per-slot or proven unused. |
| R8 | The native 5/s rate cap denies burst orders. | Low-Med | Modelled in WP0. Do not raise it here; a raise is its own review. |
| R9 | The WP0 population caveat: no high-ask NO sample for the hold inputs. | Med | Caveat on every result. Re-measure after the first live NO≥0.90 fills; this is not a build gate. |
| R10 | Rollback hazard: old code ignores slot records. | High | v2 tombstone fence makes old code latched and the supervisor refuses it. Rollback needs a drain plus an operator clear. |

**Kill criteria.**
- STOP the plan at WP0 if viability fails (§5).
- Stop a WP and revert if:
  - any duplicate-order evidence appears in WP7;
  - the full gate is red after the pin move;
  - the firewall allowlist would need an unnamed or wildcard row.
- Runtime breaker (WP5), when K > 1 is eventually enabled:
  - trip when stuck slots ≥ ceil(K/2);
  - or when unresolved notional exceeds a stated fraction of the daily budget;
  - or on any attribution CONTRADICTION;
  - or on a duplicate-order signal.
  - The effect is a family halt only. It never retires an intent.

**Rollback.**
1. K stays 1 until the final gated proposal. Every earlier merge is behaviour-identical to the singleton.
2. To revert after K > 1: set K back to 1 (a reviewed constant), halt, drain all slots, and clear the fence only with the CLI's drained-check.
3. Reverting the code itself additionally requires the drain, because old code sees the v2 tombstone as latched.
4. The pin moves back with the code, in the same commit.
5. The halt drop-in and `BREEZY_ORDERS_ENABLED` are never touched at any point.

## 7. Open questions for peer review

1. **Slot key.** Is the base slug the right unit, given that the venue nets NO as short YES? Should the key be coarser, the station-day? That would reintroduce mutually-exclusive-rung serialisation, which the operator ruling of 2026-09-14 (no one-position-per-station) argues against.
2. **K = 6.** Is it right? Is a Breezy-stated constant acceptable, given that it is not one of the two operator-reserved caps? Does the cap need a second bound on unresolved notional (a fraction of the daily budget), or is the ledger alone sufficient?
3. **Tombstone fence.** Is the v2-tombstone-at-singleton rollback design correct, or is a mirror (the singleton holds the oldest OPEN) safer? Does the tombstone break any reader that treats `SubmitIntentCorrupt` specially (for example `probe_open_intent_resolvable` returns False and the operator is stranded)?
4. **Round-robin vs per-slot tasks.** Is one-intent-per-pass round-robin enough, or does the resolution latency (≤ (K − 1) × 5 s extra) matter for any gate (for example the `_REARM_MIN_DELAY_SECS = 120` equality pin)?
5. **Scoped AMBIGUOUS refusal.** Is adding a keyword-only slug to `_refuse` really pin-neutral for `test_exec_refusal_health_surface.py`, which is keyed by enclosing function and ordinal? If not, what is the least invasive scoped shape?
6. **Permit slot waste.** A deny after permit consume wastes a slot (F8). H1 puts the slug gate before the spend. Is there a remaining race between the H1 check and `arm_slot` once `arm_slot` is the arbiter? (The current argument relies on no `await` between them, per :6194-6205.)
7. **Native `RiskEngine`.** Does it have a cumulative or free-balance check that interacts with parallel BUYs on a cash account? WP0 reads `risk/engine.pyx`; the answer could add a native bound or a native denial source.
8. **Strategy interface.** Should the strategy-side `trial_day_latch` stay a thin per-slug view of the same store, or become a separate protocol? Should this plan define the protocol for the future `pm_us_nolong_d12_v1`, or leave it entirely out of scope?
9. **Is capability the right investment now?** The shelving decision says a WINNER read would need "a new plan and prereg for a different execution design". Does this plan need its own prereg for the execution-design change? My view is no: it is a safety-design change with no screen claim, and it needs the full peer loop. This is for the coordinator to confirm.
10. **Population mismatch.** The viability numbers use hold inputs from YES orders at limits ≤ 0.70 (R9). Is a pinned-constants result acceptable for a go/no-go on a build, given n_amb = 7?

---

**Summary**
1. Recommendation: Option A, per-base-slug durable slots with a global bound K (default 1 = today's behaviour; propose 6 after evidence). It keeps the resolver floors, the pin discipline and the ledger as the exposure authority. Offline, K = 6 gives d̂_p90 about 0.0–0.03 versus 0.49–0.74 for the serial latch.
2. Work packages: 8 (WP0–WP7), with WP0 as a hard viability gate and a single byte-pinned `client.py` change in WP4.
3. Biggest risk: the unscoped global AMBIGUOUS refusal at `client.py:6110`/`:6333`/`:6580` (a second singleton the earlier plans missed), combined with the restart exposure gap (open bookings are not re-booked at boot, so exposure could exceed the daily budget by up to K × per-order cap). Both have explicit hunks and RED tests (H2, H5, H6).
4. Premise check: the numbers hold with small corrections.
   - The poll constant is at `client.py:588`, not :587.
   - The p_amb = 0 figure of 0.49 is not in the checked-in script; I reproduced it (0.491) and WP0 commits it.
   - "Drop" is a screen-policy loss, while the code only WAITs.
   - The task text omits the second singleton (the refusal gate).
5. Not run: the 5/s token bucket and stuck-slot arms of the simulation. Those numbers are therefore preliminary until WP0 exists.

Relevant files (absolute):
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/src/breezy/runtime/submit_intent.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py
- /home/jon/breezy/src/breezy/runtime/node_config.py
- /home/jon/breezy/src/breezy/runtime/trade_supervisor.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_strategy.py
- /home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py
- /home/jon/breezy/docs/evidence/m1v3/stage_minus1_triage_dmix.py
- /home/jon/breezy/docs/evidence/m1v3/stage_minus1_triage_cands.json
- /home/jon/breezy/docs/evidence/m1v3/WP0_c0_pre1007_orders.tsv
