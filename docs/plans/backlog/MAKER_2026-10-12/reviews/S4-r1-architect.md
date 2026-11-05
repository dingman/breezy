# S4 r1 review — architect — 2026-10-12
Verdict: UNSOUND — the direction is native and minimal, but the ledger steps, firewall pins, never-arm gate and AMBIGUOUS rule contradict shipped code; r2 can fix all of it with no new machinery.

## Findings (ranked)
1. [BLOCKER] §6 WP3 step 2, WP4 cancel flow, WP5 fill — ledger steps don't match the shipped API.
   (a) Exposure is already registered at arm, keyed by intent_id (client.py:7122-7135). A second register_open_exposure(key=venue id) double-holds one booking.
   (b) release_booking raises for a registered booking (operator_controls.py:614-624), so "settle(realized 0) + release_booking" raises. true_up_booking raises the same way (:656). Every settlement must go through settle(key, booking, realized_usd=None|cost, fill_ts_ns).
   (c) Retiring ACCEPTED_RESTING while the entry is held trips the leak backstop in _retire (client.py:6683-6696): resolver_error_count++ and an ERROR on every resting accept.
   Required: keep the intent-keyed entry; keep a durable venue_id -> (intent_id, booking) binding; add a reviewed carve-out in _retire for ACCEPTED_RESTING only; settle by intent_id on cancel/fill. RED tests: test_accept_resting_does_not_count_as_registry_leak, test_cancel_settles_via_settle_not_release_booking.
2. [MAJOR] §6 WP4 restart rule, §5 "Open-order reads" — the never-arm gate is strategy-side, not at client.py:477 (that line is only the constant). startup_evidence_refusal_reason (trial_day_latch.py:1512-1552) refuses on ANY open order. It is re-checked at re-arm (continuous_strategy.py:795, 2366), and the R-9a refresh re-enumerates open orders (client.py:2993).
   Result: the maker's own resting orders will disarm current_rung_hold, and any family on that gate, all day.
   Required: own-order exclusion by venue-id-map binding as a WIDENED rule. An unbound open order still refuses. RED: test_map_bound_resting_orders_do_not_refuse_arm, test_unbound_open_order_still_refuses_arm. Name the maker strategy's own arm gate.
3. [MAJOR] §6 WP3–WP5 pins — exact-set barriers the plan does not name (test_execution_egress_firewall_guard.py):
   - EXEC_ORDER_COROUTINE_PERMITTED_CALLEES (:1952). New rows: self.generate_order_accepted, self.generate_order_expired, submit_chain.unmappable_resting_order_reason, submit_chain.build_resting_order_body, the cancel-send callee(s), self._private_read in _cancel_order/_cancel_all_orders, restore_live_trading_budget, self._mark_budget_restored.
   - test_no_shipped_exec_order_coroutine_awaits_anything (:2977): the cancel coroutines will await.
   - EXEC_DECLARED_UNIMPLEMENTED_COROUTINES={"_query_order"} (:2111) becomes empty. The new _query_order body awaits a GET and must join a scanned set (resolver-style allowlist).
   - EXEC_PERMITTED_COROUTINE_NAMES (:1797) for any new helper coroutine (confirm-cancel, boot sweep).
   - ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD={"__init__","_submit_order"} (:4385) if cancel goes through _order_sender. The plan never says how cancel reaches write_transport (sender protocol widening vs a new injected object): decide it.
   - Drift: _ORDER_DRIFT_ALLOWED_KEYS (reports.py:291) for order-level fields on a canceled/expired/halted resting GET (WP0(g) unsolicitedCancelReason). parse_open_orders unknown keys. Name each as a WIDENED row with its evidence file.
4. [MAJOR] §6 WP5 AMBIGUOUS rule — the premise is false. Today's no-id resolver cannot retire NO_FILL while the rest is visible: an echo-matching in-window open order is a CONTRADICTION (no_id_attribution.py:296-304, 353-354), and a failed open-order read is INCOMPLETE (:359-360). It fails closed (stuck); it is not unsound.
   Minimal fix: for a resting-TIF intent, treat a single echo-matching in-window unknown open order as an ADOPT candidate. The existing _adopt_no_id_venue_order (client.py:4682) then hands it to the with-id path and ACCEPTED_RESTING.
   This avoids the plan's slug cancel-all from the resolver, which would be the first write ever admitted to EXEC_RESOLVER_PERMITTED_CALLEES (its docstring excludes egress by construction, :2148-2154). It also avoids depending on WP0(d): if the slugs filter is ignored, cancel-all wipes all 8 rests. Keep cancel-all only as the hard-cancel fallback.
5. [MAJOR] §6 WP4 "does NOT require an unexpired permit", §10 Q1 — resting lifetime vs permit and UTC day.
   - The permit TTL is 10 h and clamped to the first boot (safety.py:682-692, 730). A ~31 h rest outlives it and its process.
   - restore_live_trading_budget raises for a permit unknown to the process (tests in test_live_trading_budget_restore.py).
   - settle of a prior-UTC-day booking never releases (operator_controls.py:901-909), and a next-day fill is added again. That double-charges the operator's single-day stop.
   Required (simplest): bound expire_time <= min(D 09:00 LST, permit.expires_at_ns), so every rest dies inside its permit and process. Otherwise, specify cross-process/cross-day accounting with RED tests. Cancel-without-permit stays correct.
6. [MAJOR] WP1 KIND_ACCEPT_RESTING — classify_create_order_outcome (submit_chain.py:1206) has no TIF input. If the new branch is unconditional, an IOC create returning NEW+id (today AMBIGUOUS, :1324-1338) would be retired ACCEPTED_RESTING with the slot released.
   Required: a resting: bool parameter (like closing, :1212). RED: test_ioc_new_state_with_id_stays_ambiguous.
7. [MAJOR] WP5 liquidity_side / §8 crossing guard — GET /v1/order/{id} has no executions (_ORDER_KEYS, reports.py:246-269; RetirementReason note submit_intent.py:141-147). So "aggressor when present" is always absent from the poll and the taker-crossing guard is blind.
   Use the booking path instead: a create-path fill (KIND_ACCEPT_FILL) = TAKER; a poll-detected fill after ACCEPTED_RESTING = MAKER.
8. [MINOR] §10 Q1 GTC vs GTD — native answer: LimitOrder GTD plus StrategyConfig.manage_gtd_expiry=True (strategy.pyx:888-889, 1721-1734) gives a native client-side cancel at expire_time; the venue goodTillTime is the backstop if WP0(b) pins it. Do not use manage_stop: it closes positions (trading/config.py:61-64), which conflicts with hold-to-settlement and SELL refusal. Say both.
9. [MINOR] WP4 "generate_order_pending_cancel semantics" — not an ExecutionClient method (client.pxd has accepted/cancel_rejected/canceled/expired/filled at 118/135/157/173/181). Strategy.cancel_order already applies PENDING_CANCEL (strategy.pyx:1299, 1660). The client must not emit it.
10. [MINOR] §5 fill-detection row — the native path query_order → _send_order_status_report → _reconcile_order_report → _generate_inferred_fill (execution_engine.py:3485) is not listed as a rejected alternative. State why the override wins: venue commission, durable record first, ledger settle, and closing the report-injection seam.
11. [MINOR] WP2 — add a runtime check: the node refuses the resting shape unless supervisor_admits_retirement_reason(store, "ACCEPTED_RESTING") (supervisor_decode_marker.py:166-180), mirroring _no_id_retire_admitted. Add the adapter-side RETIRE_ACCEPTED_RESTING constant and retirement_member mapping (submit_chain.py:55-57, 1514).
12. [MINOR] WP4 on_stop / boot sweep — on_stop cancel is best-effort during kernel shutdown; the GTD expiry and boot sweep are the real guards. The boot sweep is a POST from _connect and needs its own scanned allowlist. The mid-day relaunch (3x per 5 min) cancels every rest each time: state that churn.

## Cited-vs-actual mismatches
- exec/client.py:477 "boot gate": actual = constant only. Gate is trial_day_latch.py:1512-1552, used at continuous_strategy.py:795, 2366.
- "classify_create_order": actual name classify_create_order_outcome (submit_chain.py:1206).
- test_native_query_order_never_reaches_the_send_seam "stays green unmodified": vacuous here. It passes only because it uses venue_order_id=None (test_polymarket_us_exec_client.py:561). Its premise ("always returns None"; also firewall :2094-2111) is stale: generate_order_status_report returns real reports for a bound id (client.py:5142-5189). Add a bound-id variant.
- BANNED_MODULES citation rows are at test_us_source_ingest_egress_guard.py:57 (write_transport 147), :62 (1771), :77 (7182). The plan cites :61/:76 and omits the write_transport row, which WP4 shifts.
- intent_fingerprint already hashes time_in_force (domain/exec_intent.py:45). WP5's "check" resolves to yes; no parity row needed.
- False-REJECTED claim VERIFIED: execution_engine.py:1319-1332 (open_only=False path), :1426-1483 (single query, then ACCEPTED→REJECTED "ORDER_NOT_FOUND_AT_VENUE"). Breezy makes it reachable because generate_order_status_reports returns [] for open_only (client.py:5218-5219) and generate_order_status_report returns None on any read error (:5159-5165): a transient GET fault leads to a false REJECTED.

## What the plan gets right
- Release the K=1 slot on a confirmed resting accept; no new intent model, no K>1, no separate store.
- Fill detection via native Strategy.query_order plus an override; open_check_*/inflight_check_*/position_check stay off.
- Cancel confirmed by GET, never by a bare 200; cancel neither arms the intent nor needs the permit; modify and batch keep raising.
- Supervisor-first rollout of the new retirement reason, matching the AMBIG-LATCH-RESUME C0 precedent.

## Unverified
Venue behaviour (WP0 a–g); whether parse_open_orders refuses unknown keys; restore_live_trading_budget on an expired-but-known permit; kernel stop ordering of strategy on_stop vs client _disconnect; the current supervisor marker's reason list.
