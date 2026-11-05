# S4 — Exec resting-order path (GTD BUY NO, cancel, many orders under K=1)

| Field | Value |
|---|---|
| ID | S4 |
| Revision | r3 (supersedes r2; addresses `reviews/S4-r2-final.md` R1–R5 and `reviews/S4-r2-codex-venue.md`; conforms to spec v0.3) |
| Date | 2026-10-12 |
| Status | READY (nothing built) |
| Programme | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` **spec v0.3** §3, §4, §9.1, §9.2, §9.7, §9.18 |
| Prior art (unbuilt) | `docs/plans/RESTING_BID_HUNT_2026-09-16.md` §4 Rev 2 (venue facts reused; its heavier pieces dropped) |

## 0. r3 conformance table

| Verdict item | Plan § changed |
|---|---|
| R1 MAJOR: resolver pin IS touched | §6.7 P6 now WIDENED (two named callees); new scanned helper `_bind_resting_order` joins `EXEC_RESOLVER_COROUTINES`; T42(iv) WIDENED to exactly two `_store_set` sites/keys (P21); WP5 RED renamed |
| R2 MAJOR: no-id resting cannot ADOPT after restart | WP4e/WP5 rewritten: a prior-process no-id resting intent is never classified; boot sweep + read-confirm + holding check is its ONLY retirement route; new negative reason `BOOT_SWEEP_RESTING_NO_FILL` (WP2, supervisor-admitted); filled-while-down stays AMBIGUOUS fail-closed with alert; "fill leg (ADOPT)" dropped (§2 item 5) |
| R3 MINOR: verdict signature, `NoIdEcho.resting` | WP5 "No-id attribution change" names both signature changes |
| R4 MINOR: re-read failure, scope constant | WP4e bullets 4–5 |
| R5 MINOR: lagged poll vs holding delta | §8 row "Poll lag CONTRADICTs a concurrent no-id intent" |
| Spec v0.3 §12 inputs | §12 closed: all seven absorbed by v0.3 |
| Additional pins found while re-verifying | §6.7 P22 (`SUBMIT_PREFIX_SHA256`), P23 (`FROZEN_SOURCE_SHA256` for `classify_create_order_outcome`), P24 (new boot-sweep exact set) |

## 1. Hard invariants (binding on every WP and every brief)

- Nautilus Trader is immutable. Extend only via `LiveExecutionClient` overrides and native `Strategy` calls/config.
- `allow_short` stays `False`. Only BUY is mappable. NO is bought as the NO instrument (wire price via `leg_prices`).
- Never weaken or delete a safety, settlement, contract or NO-SEND firewall test. Every exact-set barrier is WIDENED by named reviewed rows (§6.7) with a non-vacuity proof, never relaxed (L-12). S-4 STOP if only relaxing turns it green.
- Never assign a value to the two operator caps. Never touch `BREEZY_ORDERS_ENABLED`, the live-orders ruling, or any enablement. S4 makes a path *possible*; it arms nothing.
- No frozen PREREG is edited; no pre-registered date moves. Stage 0 is never promotion evidence. The NO-TRADE ruling stays in force (this programme is its T2 route).
- Worktrees: `PYTHONPATH=<wt>/src`; no uv/pip; no `git stash`; one heavy job at a time; full gate after every merge (`--basetemp ~/.cache/...`, rm after reading EXIT); `cd <wt> && lint-imports` must print "N kept, 0 broken".

## 2. Goal state (acceptance test)

On the no-egress gate (fake sender/reader), a test Strategy on `PolymarketUSExecutionClient` proves:
1. `submit_order(LimitOrder BUY NO, qty 1, price ≤ B_CAP 0.80, TimeInForce.GTD, expire_time ≤ bound)` → `OrderAccepted`; intent retired `ACCEPTED_RESTING`; the K=1 slot is free (spec §9.2: no new intent model).
2. `cancel_order` → `OrderCanceled` only after a GET shows the order terminal; ledger settled once; permit slot restored (this-process ids only).
3. Station cancel = `cancel_order` on each of its ≤ MAX_RUNGS orders (2, or 1 under the spec §3 fallback). Slug-scoped cancel-all exists only for the boot sweep and the unconfirmed-cancel escalation.
4. Eight resting orders (spec §4 "≤ 8 simultaneous rests") coexist; fills found by native `query_order`, booked at venue price/commission, MAKER on the poll path, TAKER on the create path (spec §3 "taker fills counted separately").
5. A no-id AMBIGUOUS resting POST, **in the same process**, resolves by ADOPT of a single echo-matching open order or by two-pass NO_FILL. **After a restart**, it is never classified by the resolver: the boot sweep cancels on its slug, confirms by read, and the intent retires `BOOT_SWEEP_RESTING_NO_FILL` on two consistent holding reads, or stays AMBIGUOUS with a CRITICAL alert if a fill happened while down (fail-closed, bounded: the order is gone).
6. A map-bound resting order does not disarm any family's arm gate; an unbound open order still refuses.

Venue facts (S-1, S-2, S-6) are pinned by the WP6 positive control. Until then the two `*_VERIFIED` constants stay `False` and the adapter refuses every resting submit and the boot sweep does not run (§6 WP1, WP4e).

**Artifact:** `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`: RED→GREEN logs per WP, gate `EXIT=0` lines, the lint-imports line, one section per §6.7 pin row (diff + reviewer), the supervisor restart time, and the WP6 verdict or `POSITIVE_CONTROL: PENDING (<reason>)`.

## 3. Entry criteria and STOP conditions

**Entry (before WP1):** S2 Stage 0 verdict is NOT-KILLED or NOT-KILLED-UNSCREENED (never NO-GO); S3 A1 floor for the maker mix is not `unreachable_veto`; WP0 did not STOP. WP0 starts now (read-only).

**STOP (programme ends; record in evidence + PROGRESS):**
- S-1: a non-post-only GTD limit BUY NO does not rest on `tc-temp-*` (rejected, forced IOC, or requires `participateDontInitiate`). GTC+post-only at 0.01 (09-04) does not prove this.
- S-2: slug-scoped cancel-all is unavailable or not honoured (a second order on another slug must survive `{slugs:[X]}`). The boot sweep is the only remover of a no-id orphan after a restart.
- S-3: open orders cannot be enumerated (`GET /v1/orders/open` and `GET /v1/order/{id}` both unavailable).
- S-6: venue-side GTD expiry is not honoured (`goodTillTime` unaccepted, or the order outlives it).

**STOP (this step only; to the peer loop, never the operator):** S-4 a pin needs relaxing; S-5 the venue requires `participateDontInitiate` (spec §3 "never post_only unless the venue requires it" would then force a maker-fee branch in `fees.py`/`BacktestOrderGuard`, out of scope).

## 4. Simplest direct path

Keep the K=1 submit latch as a one-POST-at-a-time serializer. Retire it `ACCEPTED_RESTING` once the venue confirms a resting order with an id; eight concurrent orders are then eight `ACCEPTED` orders in the Nautilus cache. The ledger entry stays keyed by `intent_id` (registered at arm today) and is settled once on cancel or fill.

Every order is GTD with `expire_time ≤ min(D CANCEL_LST 09:00, permit.expires_at_ns, end of the booking's UTC day)` (spec §3). Every rest dies inside its permit, its daily-budget day and its venue backstop: no cross-permit restore, no cross-day double charge, no unbounded orphan.

Fills come from native `Strategy.query_order` on a timer through a `_query_order` override. Cancels are by id, confirmed by GET. Cancel-on-stop is the restart contract (spec §3): the strategy cancels at stop, and the boot sweep enforces it if stop did not finish. So after any restart no prior rest survives, and every no-id resting intent from a prior process is retired by the sweep, never by attribution.

**Not built:** a separate resting store; venue modify (cancel-then-submit); K>1 or a new intent model (EXEC-PAR slot table stays at effective K=1, `submit_intent.py:848`); the private WS order stream (§5); native continuous reconciliation; post-only / a maker-fee branch; adopting a prior process's rests; passive-leg attribution (§10 Q1).

## 5. Nautilus null-hypothesis check

| Need | Native capability (evidence) | Verdict |
|---|---|---|
| Resting limit | `TimeInForce.GTD` + `LimitOrder.expire_time`; venue enum maps `exec/reports.py:431-434`, states `:441-456`; `goodTillTime` in `_ORDER_KEYS` (`reports.py:246-269`) | Native. Adapter refuses at `submit_chain.py:331-332, :353`. **Gap: adapter shape.** |
| Client-side expiry | `StrategyConfig.manage_gtd_expiry=True` → timer + cancel at `expire_time` (`trading/strategy.pyx:888-889`, `:1912`; `trading/config.py:58,93`). Not `manage_stop` (closes positions, conflicts with hold-to-settlement). Spec hard cancels use `clock.set_time_alert`. | Native; maker strategy sets it. Venue `goodTillTime` is the backstop (S-6). |
| Events | `generate_order_accepted/canceled/expired/filled/cancel_rejected` (`execution/client.pxd:118,157,173,181,135`). No `generate_order_pending_cancel`: `Strategy.cancel_order` applies PENDING_CANCEL (`strategy.pyx:1299,1660`). | Native. Client never emits PENDING_CANCEL. |
| Verbs | `Strategy.submit_order`, `cancel_order` (`strategy.pyx:1089`), `cancel_orders` (`:1134`), `cancel_all_orders` (`:1215`), `query_order` (`:1527`) | Native. |
| Client hooks | `LiveExecutionClient._cancel_order/_cancel_all_orders/_batch_cancel_orders/_modify_order/_query_order` (`live/execution_client.py:516-532, 618-633`); Breezy bodies refuse/raise at `exec/client.py:7587, 7606, 7609, 7612` | **Gap: bodies** for cancel, cancel-all, query. Modify and batch keep raising. |
| Fill detection | Chosen: `_query_order` override (GET by id, emits events itself). Rejected: native report → `_generate_inferred_fill` (`execution_engine.py:3485`; loses commission, no durable record first, no settle); `open_check_*` (false REJECTED on `ORDER_NOT_FOUND_AT_VENUE`, `execution_engine.py:1319-1332, 1426-1483`, reachable because `generate_order_status_reports` returns `[]` for open_only, `client.py:5218-5219`); private WS order stream (docs `api-reference_orders_overview_2026-08-25.md:63-68`; never wire-verified, shares the 10-subs cap). 8 orders × 30 s ≈ 0.27 req/s of 20. | **Override `_query_order`.** |
| Arm gate | `startup_evidence_refusal_reason` (`strategy/current_rung_hold/trial_day_latch.py:1512-1552`) refuses on ANY open order; re-checked at arm/re-arm (`continuous_strategy.py:795, 2366`); evidence written by the client (`client.py:6270-6287`), refreshed by R-9a (`:2993-2997`) | **Gap: WIDENED own-order rule** (WP4b). |
| No-id resolution | `classify_no_id_evidence` (`no_id_attribution.py:308-363`); open-order rule `_open_order_verdict` (`:275-305`) returns `(contradiction, unreadable)` and treats any echo match as CONTRADICTION; ADOPT exists **only from aggressor legs** (`:329-336, :361-362`); `_matches_echo` requires `tif == IOC_TIF` (`:259-272`); window end = created + `_NO_ID_WINDOW_FORWARD_NS` (65 s fate-fixed + skew, `client.py:1627-1633, :4337`). A maker fill is the passive side, so it can never be a candidate. | **Gap: in-process resting ADOPT from open orders** (WP5); after restart, no attribution at all (WP4e). |
| Caps/exposure | `register_open_exposure` at arm keyed by `intent.intent_id` (`client.py:7122-7135`); `settle(key, *, booking, realized_usd, fill_ts_ns, now_ns)` (`operator_controls.py:844`); `restore_live_trading_budget` (`safety.py:857`, idempotent, current permit only), TTL 10 h (`:172`) | Reuse unchanged. **Gap: call sites** + `_retire` carve-out (`client.py:6683-6696`). |
| Retirement admission | `supervisor_admits_retirement_reason` (`runtime/supervisor_decode_marker.py:166-180`), precedent `_no_id_retire_admitted` and `_resolve_no_order` (`client.py:4693-4781`, settle-then-retire `RESOLVER_NO_ID_NO_FILL`) | Reuse; two new reasons (WP2). |
| Cancel transport | `post_cancel_all` (`write_transport.py:160-175`), body-less, zero call sites; sender = transport object (`client.py:1795, 1891`, `factories.py:835`) | **Gap:** `post_cancel_order`, slug body. No Protocol/factory change. |

## 6. Work packages

Routing (CLAUDE.md): build = Grok → Codex → Claude `tdd-guide` (seeded `nautilus-trader-patterns`, `polymarket-us-integration`); review = `python-reviewer` + `prediction-market-reviewer` + `security-reviewer` on every egress-touching WP. The coordinator re-runs every gate. Every brief restates §1.

**Focused gate (every WP):** `PYTHONPATH=<wt>/src scripts/ci/run_tests_no_egress.sh <list> --basetemp ~/.cache/breezy-gate/s4-<wp>`, list always including: `tests/unit/test_execution_egress_firewall_guard.py`, `tests/unit/test_polymarket_us_readonly_guard.py`, `tests/unit/test_cage_rule_constants_are_pinned.py`, `tests/contract/test_us_source_ingest_egress_guard.py` (incl. x1), `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`, `tests/unit/test_autonomy_*.py`, `tests/unit/test_ambig_no_id_firewall_delta.py`, `tests/unit/test_no_id_attribution.py`, `tests/unit/test_retirement_reason_superset.py`, `tests/unit/test_supervisor_decode_marker.py`, `tests/unit/test_polymarket_us_exec_client.py`, `tests/unit/test_daily_spend_ledger_open_exposure.py`, `tests/unit/test_live_trading_budget_restore.py`, plus the new S4 files. Then the full gate after merge, then lint-imports.

### WP0 — Venue discovery (read-only; `polymarket-us-discovery`; starts now)
- **Inputs:** `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_*`, `sdk_snapshot/polymarket_us_0.1.2/types/orders.py:70-180`, `PRIVATE_write_sequence_probe_20260904T170856Z.json`.
- **Pin from docs or mark UNVERIFIED:** (a) non-post-only GTD on `tc-temp-*`; (b) `goodTillTime` spelling/format/honoured; (c) `POST /v1/order/{id}/cancel` body `{marketSlug}`; (d) `{slugs:[…]}` cancel-all scoping; (e) create response for a rest under `synchronousExecution=true, maxBlockTime=5`; (f) maker commission field (`makerCommissionsBasisPoints`, `orders.py:92`) and **sign**; (g) halted-market auto-cancel, `unsolicitedCancelReason`; (h) private-WS order-stream snapshot (documentation only).
- **Budget:** GETs only, ≤ 60, ≤ 1 per 3 s. No POST. **Output:** dated note under `docs/evidence/venue/polymarket_us/` + skill rows (`provisional: true`). **Done:** (a)–(h) each PINNED or UNVERIFIED with a source line.

### WP1 — Resting shape + classifier (pure; `exec/submit_chain.py`)
- `unmappable_resting_order_reason(order, instrument, *, permit_expires_at_ns: int, now_ns: int) -> str | None`, a third shape; IOC (`:322-363`) and exit (`:448-483`) shapes stay byte-identical. Admits only: LIMIT, BUY, qty == 1, NO leg, price in (0, `RESTING_PRICE_CAP`=0.80 = spec B_CAP], `TimeInForce.GTD`, `now < expire_time ≤ min(permit_expires_at_ns, utc_day_end(now_ns))`, `post_only False`, no reduce-only/display/trigger. **GTC refused.** B_FLOOR 0.70, never-cross (`bid ≤ no_ask − 0.01`) and the CANCEL_LST term are strategy rules (the adapter has no book and no station tz).
- Refuses while `GTD_EXPIRY_VERIFIED is not True` or `CANCEL_ALL_SLUG_SCOPE_VERIFIED is not True` (module constants flipped only on WP6 evidence; `WRITE_CANONICAL_STRING_VERIFIED` precedent).
- `build_resting_order_body(order, instrument) -> dict` emits `RESTING_ORDER_BODY_KEYS` = IOC keys with `tif=GTD` + `goodTillTime`. `encode_order_body` (`:578`) accepts exactly `ORDER_BODY_KEYS` or `RESTING_ORDER_BODY_KEYS`, still equality.
- `classify_create_order_outcome(..., closing=False, resting: bool = False)` (`:1206`): `KIND_ACCEPT_RESTING` only when `resting`, id present, state `ORDER_STATE_NEW`; `resting=False` behaviour unchanged (source hash re-pinned, P23).
- `RETIRE_ACCEPTED_RESTING`, `RETIRE_BOOT_SWEEP_RESTING_NO_FILL` beside `:55-57`, mapped in `retirement_member` (`:1514`).
- **RED** (`tests/unit/test_polymarket_us_resting_order_shape.py`): `test_ioc_shape_still_refuses_gtc_byte_identically`, `test_resting_shape_admits_gtd_buy_no_qty1_at_080`, `test_resting_shape_refuses_gtc`, `test_resting_shape_refuses_expire_after_permit_expiry`, `test_resting_shape_refuses_expire_after_utc_day_end`, `test_resting_shape_refuses_while_slug_scope_unverified`, `test_resting_shape_refuses_while_gtd_unverified`, `test_resting_shape_refuses_{price_above_080,yes_leg,sell,post_only}`, `test_resting_body_key_set_is_exact`, `test_encode_refuses_a_mixed_key_set`, `test_classify_new_state_with_id_is_accept_resting_only_when_resting`, `test_ioc_new_state_with_id_stays_ambiguous`, `test_classify_resting_response_without_id_is_ambiguous`.
- **Done:** RED→GREEN; `test_polymarket_us_submit_order_chain.py`, `test_no_side_submit_chain_2026_09_14.py` pass unmodified.

### WP2 — Retirement vocabulary (supervisor-first; parallel with WP1)
- Add `RetirementReason.ACCEPTED_RESTING` and `RetirementReason.BOOT_SWEEP_RESTING_NO_FILL` (`runtime/submit_intent.py:128`). The fingerprint already hashes `time_in_force` (`domain/exec_intent.py:45`): no parity row.
- **Deploy:** merge → supervisor restart (01:00–16:40Z) → only then may a node write either reason.
- **Runtime guards:** boot-time bools `_resting_accept_admitted` and `_sweep_retire_admitted` from `supervisor_admits_retirement_reason(store, <reason>)`, mirroring `_no_id_retire_admitted`, fail-closed. Without the first, the client refuses the resting shape; without the second, a swept intent stays AMBIGUOUS with the existing `resolver_no_id_retire_blocked`-shaped CRITICAL detail (`client.py:4710-4730`).
- **RED:** `test_accepted_resting_round_trips_and_releases_the_slot`, `test_boot_sweep_resting_no_fill_round_trips`, `test_reconcile_at_startup_leaves_an_accepted_resting_record_retired`, `test_retirement_reason_set_is_widened_by_exactly_two_rows`, `test_resting_submit_refused_until_supervisor_admits_accepted_resting`, `test_sweep_retire_refused_until_supervisor_admits_boot_sweep_reason`.

### WP3 — Submit path (`exec/client.py` `_submit_order` :6880)
- **Dispatch:** `unmappable_resting_order_reason` when `order.time_in_force == GTD`, else today's path. Deny-chain order and no-await spans unchanged; the prefix hash is re-pinned once (P22). Arm-time `register_open_exposure(intent.intent_id, …)` (`:7122-7135`) stays **the only registration**.
- **Durable slug ledger, pre-POST:** the resolver context written before the POST (`:7136-7140`) already carries `wire_market_slug` (`client.py:1158`). Add trailing-optional `resting: bool = False` to `AmbiguousResolverContext`, serialised **only when True** (IOC context bytes unchanged; absent decodes `False`). No new store.
- **One binder, two callers (R1):** sync `def _bind_resting_order(self, context, venue_order_id: str, now_ns: int) -> None`, no `await`, no sender reference, scanned as a resolver helper (P6/P21). Steps, no `await` between: (1) `_store_set(f"{RESTING_KEY_PREFIX}{venue_order_id}", …)` → `{intent_id, slug, client_order_id, expire_time_ns}`; (2) rebind `self._resting_bookings = {**…, venue_order_id: (intent_id, booking)}` and `self._this_process_resting_ids = … | {venue_order_id}` (rebinding, not method calls: no new callee, resolver precedent `client.py:4348`); (3) `self._retire(intent_id, RETIRE_ACCEPTED_RESTING, now_ns)`; (4) `self.generate_order_accepted(…)`. Called by `_submit_order` on `KIND_ACCEPT_RESTING`, and by the with-id resolver on GET NEW of a `resting=True` context (WP5).
- **`_retire` carve-out:** the E1 leak check (`:6683-6696`) is skipped iff the reason is `RETIRE_ACCEPTED_RESTING` and `intent_id` is in `_resting_bookings` values. Any other retire with an open entry still counts.
- **Taker on create:** `KIND_ACCEPT_FILL` for a resting-shape order is booked as today with `liquidity_side=TAKER`, WARN `resting_order_crossed` (spec §3, counted separately).
- **RED** (`tests/unit/test_polymarket_us_resting_submit.py`): `test_resting_accept_emits_order_accepted_and_retires_accepted_resting`, `test_resting_accept_does_not_double_register_exposure` (+ `_day_roll_variant`), `test_accept_resting_does_not_count_as_registry_leak`, `test_other_retire_with_open_entry_still_counts_as_leak`, `test_resting_binding_row_written_before_accepted_event`, `test_resting_submit_decrements_the_permit_order_count`, `test_headroom_refusal_denies_a_resting_submit_without_a_post`, `test_eight_resting_orders_coexist_with_k1`, `test_a_ninth_order_is_refused_by_headroom_not_by_the_latch` (fixture caps only), `test_create_fill_on_resting_shape_is_taker`, `test_ioc_submit_path_is_byte_identical_for_ioc_orders`, `test_ioc_resolver_context_bytes_are_unchanged`.

### WP4 — Cancel path, boot sweep, own-order rule (new egress)
**4a transport** (`write_transport.py`): `CANCEL_ORDER_PATH_TEMPLATE="/v1/order/{id}/cancel"`; `post_cancel_order(api_base_url, *, order_id, headers, body)`, id checked by allowlist `^[A-Za-z0-9_-]{1,64}$`; `post_cancel_all(..., body)` with body **required** and exactly `{"slugs":[non-empty, each tc-temp-*]}` (body-less form removed; zero call sites, `:160`). POST only, existing signer `sign_headers(_WRITE_METHOD, <exact path>)`; no new key material.

**4b own-order rule:** `StartupOpenOrderSnapshot` gains `own_resting: bool` (True iff `venue_order_id` has a live `resting:` row with matching slug; parser `client.py:1446-1465` decodes absent as `False`). `startup_evidence_refusal_reason` (`trial_day_latch.py:1540`) refuses only if an open order with `own_resting is not True` remains. The maker strategy's arm gate is this same `startup_evidence_permits_arm`.

**4c `_cancel_order`** (`:7587`): refuses via `generate_order_cancel_rejected` unless sender injected, canonical verified, venue id bound. Never arms the intent, never asserts the permit (it only reduces risk). Flow: POST cancel → poll `GET /v1/order/{id}` until terminal or `CANCEL_CONFIRM_DEADLINE_S` (PROVISIONAL 30 s) →
- CANCELED/EXPIRED, `cumQuantity==0`: `generate_order_canceled`/`_expired`; `ledger.settle(intent_id, booking=…, realized_usd=None, fill_ts_ns=None, now_ns=…)` exactly once; `restore_live_trading_budget(venue_id)` iff in `_this_process_resting_ids`; delete the binding row;
- FILLED: WP5 fill path; no restore;
- unconfirmed: slug-scoped cancel-all on that slug, read-confirm, else latch `resting_cancel_unconfirmed` (existing alert delivery); submits refused, cancels continue. A bare 200 never emits CANCELED.

**4d `_cancel_all_orders`** (`:7609`): one `_cancel_order` per bound order on the slug; no venue cancel-all from the strategy path.

**4e boot sweep** `_sweep_resting_orders_at_boot()` in `_connect` (`client.py:2283`), before the startup evidence write. It is the cancel-on-stop enforcement (spec §3) and, after a restart, the **only** retirement route for a no-id resting intent (R2).
1. Slugs = all `resting:` rows ∪ slugs of `resting=True` resolver contexts (the durable pre-POST slug ledger). For each slug: read `/orders/open` (record ids), `post_cancel_all({slugs:[slug]})`, re-read, require nothing open on the slug, log canceled ids (WARN with id if unbound: a manual order on a family slug is canceled, accepted per spec §9.18).
2. Bound ids (`resting:` rows): GET by id; terminal with `cumQuantity==0` → delete row; `cumQuantity>0` → durable fill record first, then the existing seed-from-durable-fills accounting; nothing restored to the new permit, prior seeded spend stays charged.
3. **No-id `resting=True` contexts:** on a confirmed-empty slug, add `intent_id` to `_swept_resting_intent_ids` (process-local). WP5 performs the retirement reads; nothing else may retire it.
4. **Re-read fails or the slug is not empty (R4):** latch `resting_cancel_unconfirmed` (CRITICAL alert), delete no row, mark no intent swept; the intent stays AMBIGUOUS and the arm gate keeps refusing (unbound open orders). Next boot retries.
5. **Sweep does not run** if the sender is absent, canonical is unverified, or `CANCEL_ALL_SLUG_SCOPE_VERIFIED is not True` (R4): today's refusal + alert stands, no intent is swept.
- Mid-day relaunch (×3 per 5 min until 01:00Z) cancels every rest each time; the churn and queue reset are spec §3/§9.15 facts (new episode).

**4f on_stop:** the maker strategy calls `cancel_all_orders` per instrument (spec §3 restart contract). Best-effort under kernel shutdown; GTD expiry and 4e are the guards.

**RED** (`tests/unit/test_polymarket_us_resting_cancel.py`): `test_bare_200_does_not_emit_order_canceled`, `test_zero_fill_cancel_settles_exactly_once`, `test_cancel_settles_via_settle_not_release_booking`, `test_restore_only_for_this_process_ids`, `test_restore_is_idempotent_per_venue_order_id`, `test_cancel_post_200_but_get_filled_routes_to_fill_and_does_not_restore`, `test_unconfirmed_cancel_escalates_to_slug_cancel_all_and_latches`, `test_cancel_allowed_with_expired_permit`, `test_cancel_never_arms_the_submit_intent`, `test_client_never_emits_pending_cancel`, `test_cancel_signature_covers_the_exact_cancel_path`, `test_cancel_order_id_allowlist_refuses_traversal`, `test_cancel_all_never_posts_without_slug_body`, `test_slug_cancel_all_refused_while_scoping_unverified`, `test_boot_sweep_cancels_every_slug_in_the_durable_ledger_and_confirms_by_read`, `test_boot_sweep_marks_a_no_id_resting_intent_swept_only_on_a_confirmed_empty_slug`, `test_boot_sweep_reread_failure_latches_and_deletes_no_row`, `test_boot_sweep_does_not_run_while_slug_scope_unverified`, `test_boot_sweep_touches_no_slug_outside_the_ledger`, `test_boot_with_unbound_open_order_off_ledger_still_refuses_and_alerts`, `test_map_bound_resting_orders_do_not_refuse_arm`, `test_unbound_open_order_still_refuses_arm`, `test_pre_s4_evidence_bytes_decode_own_resting_false`.

**OS-block proof** (`tests/unit/test_polymarket_us_write_transport.py`): `test_post_cancel_order_is_refused_by_the_os_egress_block`, `test_post_cancel_all_with_slugs_is_refused_by_the_os_egress_block`. Each wraps the REAL `nautilus_pyo3.HttpClient` in a recording spy capturing the raw pyo3 exception before `write_transport` re-raises it `from None` (`:167-170, :186-189`), classifies it with `classify_canary_failure` (`test_execution_egress_firewall_guard.py:383-406`) as BLOCKED, asserts `VenueTransportError`, uses dummy credentials and a nonexistent id, and **fails, not skips**, when `os_egress_block_attested()` (`:458`) is False. The classifier is never edited.

### WP5 — Fill detection, AMBIGUOUS-resting, poll health (`exec/client.py`)
**`_query_order` override.** For a bound id: `GET /v1/order/{id}` via `_private_read` →
- `cumQuantity` delta > 0: durable fill record **first** (`record_fill`), then `generate_order_filled` with `last_px` = venue `avgPx` inverted to the NO leg via `leg_prices`, `commission` = the venue field **with its venue sign** (WP0(f); never the skill constant), `liquidity_side=MAKER` (a poll fill after `ACCEPTED_RESTING` is maker by construction); then `settle(intent_id, booking=…, realized_usd=<accept-fill basis>, fill_ts_ns=…, now_ns=…)`.
- CANCELED/EXPIRED/REJECTED: as 4c (EXPIRED = GTD backstop). Never calls `_send_order_status_report`.

**Poll:** the maker strategy calls `self.query_order(order)` per open rest on a native clock timer (PROVISIONAL 30 s). Three consecutive failed GETs for one id latch `resting_query_unreadable` (alert); submits refused, cancels continue.

**With-id AMBIGUOUS resting POST** (intent OPEN, booking held, cancels run): the existing with-id resolver after its floor. GET NEW on a `resting=True` context → `self._bind_resting_order(...)` (WP3). FILLED/terminal use today's accept-fill/terminal-zero paths; a resolver-booked fill on a resting context is reported with taker fills (never in the maker win rate), because the resolver cannot tell create-cross from later maker fill.

**No-id attribution change (R3)**, `no_id_attribution.py` (stays pure, outside `exec/`):
- `NoIdEcho` gains trailing `resting: bool = False`; the `no_id_echo` property (`client.py:1187-1205`) passes `resting=self.resting` (no new callee in scanned bodies).
- `_open_order_verdict(...) -> tuple[bool, bool, str | None]` = `(contradiction, unreadable, resting_candidate)`. When `echo.resting`, an echo-matching, in-window, unknown open order with `tif != IOC_TIF` is a candidate instead of a contradiction; two or more → contradiction; an IOC-tif open order is still a contradiction. `echo.resting False` → third element `None`, behaviour byte-equivalent.
- `classify_no_id_evidence` returns `NoIdVerdict(ADOPT, order_id=resting_candidate)` after the existing precedence (unattributed, late, open contradiction, multiple, incomplete). `_matches_echo` is **unchanged** (IOC-only): a maker fill never ADOPTs.

**No-id resting, same process:** ADOPT → `_adopt_no_id_venue_order` (unchanged) → with-id GET NEW → `_bind_resting_order`. Nothing visible → NO_FILL needs **two** verdicts ≥ 60 s apart, both after the 300 s floor (`_RESOLVER_NO_ID_MIN_AGE_NS`, `client.py:1625`), which already exceeds the 65 s fate-fixed bound (`:1627`). If it filled as maker before ADOPT, the counterparty aggressor row is `unattributed`/`late` → CONTRADICTION, stuck AMBIGUOUS with the existing alert (fail-closed, stated).

**No-id resting, prior process (R2).** In `_resolve_no_id_intent`, when `context.resting` and the intent was not armed by this process:
- not in `_swept_resting_intent_ids` → return before any classification (stays AMBIGUOUS, DEBUG log);
- swept → skip `classify_no_id_evidence`; on each pass read positions and activities (existing reads) and require (a) `holding_delta_consistent(...)` (`no_id_attribution.py:366`) is `True` against the context baseline, (b) no non-manual TRADE row on the context slug at/after `created_ns`. Two such passes ≥ 60 s apart → `_resolve_no_order(..., reason=RETIRE_BOOT_SWEEP_RESTING_NO_FILL)` (new keyword, default `"RESOLVER_NO_ID_NO_FILL"` keeps today's behaviour; settle-then-retire unchanged; gated by `_sweep_retire_admitted`).
- (a) `False` or (b) present → filled while down: stays AMBIGUOUS, CRITICAL `resting_no_id_fill_while_down` via `_resolver_contradiction_details`. Exposure is bounded (order canceled and read-confirmed, qty 1, held to settlement). (a) `None` → not evaluable, retry.

**RED** (`tests/unit/test_polymarket_us_resting_query.py`, `tests/unit/test_no_id_attribution_resting.py`, `tests/unit/test_polymarket_us_resting_restart.py`): `test_query_detects_fill_with_venue_signed_commission`, `test_query_fill_writes_durable_record_before_event`, `test_poll_fill_after_accepted_resting_is_maker`, `test_query_never_reaches_send_order_status_report`, `test_three_failed_polls_latch_resting_query_unreadable`, `test_resting_single_echo_match_open_order_is_adopt`, `test_ioc_echo_match_open_order_stays_contradiction`, `test_resting_two_echo_matches_stay_contradiction`, `test_resting_fill_leg_never_matches_echo`, `test_open_order_verdict_non_resting_is_unchanged`, `test_no_id_resting_no_fill_needs_two_reads`, `test_late_landing_post_after_first_read_is_caught_by_second_read`, `test_with_id_ambiguous_resting_new_state_binds_and_retires_accepted_resting`, `test_cancels_proceed_while_an_ambiguous_intent_is_open`, `test_prior_process_no_id_resting_intent_is_never_classified`, `test_unswept_no_id_resting_intent_stays_ambiguous`, `test_swept_no_fill_retires_boot_sweep_resting_no_fill_after_two_reads`, `test_swept_retire_refused_on_non_manual_trade_row_on_slug`, `test_restart_no_id_resting_filled_while_down_stays_ambiguous_and_alerts`, `test_resolve_no_order_default_reason_is_unchanged`, `test_resolver_permitted_callees_widened_by_exactly_the_named_rows`.

**Firewall delta:** new `tests/unit/test_resting_path_firewall_delta.py` (precedent `test_ambig_no_id_firewall_delta.py`): freezes pre-S4 literals, pins each new awaited callee, plants a violation per guard (incl. `post_order` into `_bind_resting_order` and `_sweep_resting_orders_at_boot`) to prove non-vacuity.

### 6.7 Exact-set pins and drift allowlists touched (each a WIDENED row; evidence = one section of the S4 evidence file + named test)
| # | Pin (file:line) | Change |
|---|---|---|
| P1 | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (firewall `:1952`) | + `self._bind_resting_order`, `self.generate_order_expired`, `self.generate_order_canceled`, `self.generate_order_cancel_rejected`, `submit_chain.unmappable_resting_order_reason`, `submit_chain.build_resting_order_body`, `self._order_sender.post_cancel_order`, `self._order_sender.post_cancel_all`, `self._private_read`, `restore_live_trading_budget`, `self._mark_budget_restored`, `self._ledger.settle` (exact names fixed at build, each listed in evidence). `test_submit_order_gains_no_callee_beyond_the_unchanged_order_allowlist` (delta `:532-538`) follows P1 |
| P2 | `test_no_shipped_exec_order_coroutine_awaits_anything` (`:2977`) | exempts exactly `_cancel_order`, `_cancel_all_orders`, `_query_order`; their awaits pinned by new exact set `EXEC_CANCEL_QUERY_AWAITED_CALLEES` |
| P3 | `EXEC_DECLARED_UNIMPLEMENTED_COROUTINES={"_query_order"}` (`:2111`) | → `frozenset()`; `_query_order` joins a scanned GET-only set `EXEC_QUERY_PERMITTED_CALLEES` (no `post_*`) |
| P4 | `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) | + `_sweep_resting_orders_at_boot`, `_confirm_terminal_by_read` |
| P5 | `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) | + `_cancel_order`, `_sweep_resting_orders_at_boot` |
| P6 | `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2155-2359`) + `EXEC_RESOLVER_COROUTINES` (`:2128-2146`) | **WIDENED (R1):** callees + `self._bind_resting_order`, `self.generate_order_accepted`; coroutines + `_bind_resting_order`. No `post_*`; still egress-free. `_resolve_no_order`'s new keyword adds no callee. Delta test `NEW_FUNCTIONS` (`:32`) + `_bind_resting_order` |
| P7 | readonly guard V2/B4 | cancel-path literal admitted in `write_transport.py` only; copycat still trips |
| P8 | E0 `test_n2_…expected_execution_egress_modules` (`:710`) | unchanged (no new module); E3 row + `post_cancel_order` iff E3 classifies methods |
| P9 | `test_the_other_four_lifecycle_coroutines_raise_unsupported` (`test_polymarket_us_exec_client.py:1650`) | modify + batch still raise; cancel/cancel-all/query move to positive tests; never deleted |
| P10 | `test_native_query_order_never_reaches_the_send_seam` (`:537`) | stale premise fixed + bound-id variant (today vacuous at `venue_order_id=None`, `:561`) |
| P11 | `_ORDER_DRIFT_ALLOWED_KEYS` (`reports.py:291`) | + `unsolicitedCancelReason` only if WP0(g)/WP6 observes it; `_EXECUTION_DRIFT_ALLOWED_KEYS` (`:333`) unchanged |
| P12 | `RetirementReason` (`submit_intent.py:128`) + `RETIRE_*` (`submit_chain.py:55-57`) | + `ACCEPTED_RESTING`, `BOOT_SWEEP_RESTING_NO_FILL` |
| P13 | `encode_order_body` key equality (`submit_chain.py:578`) | + `RESTING_ORDER_BODY_KEYS` alternative |
| P14 | `startup_evidence_refusal_reason` (`trial_day_latch.py:1512-1552`) + parser (`client.py:1446-1465`) | own-order exclusion (4b) |
| P15 | `_retire` E1 leak backstop (`client.py:6683-6696`) | `ACCEPTED_RESTING` carve-out |
| P16 | `test_cage_rule_constants_are_pinned.py` | RulePin rows `RESTING_PRICE_CAP`, `GTD_EXPIRY_VERIFIED`, `CANCEL_ALL_SLUG_SCOPE_VERIFIED`, `CANCEL_CONFIRM_DEADLINE_S` |
| P17 | `test_it_issues_exactly_one_post_to_the_one_pinned_path` (`test_polymarket_us_write_transport.py:339`) | per-method twins for cancel and cancel-all |
| P18 | `_EXEC_CLIENT_SHA256` (`test_forecast_quantile_ladder_manifest_and_markers.py`) | re-pinned once in WP6 with reviewer comment |
| P19 | `BANNED_MODULES` citations (`test_us_source_ingest_egress_guard.py:57, :62, :77`) | line citations re-pinned (not relaxations) |
| P20 | x1 `BANNED_EXEC_TRANSPORT_MODULES` (`:611-640`) | **unchanged**: no new transport import |
| P21 | T42(iv) `test_store_set_occurs_exactly_once_in_the_scanned_bodies_with_the_pinned_key` (delta `:448-453`) + `test_planting_a_second_store_set_fails_the_single_site_pin` (`:476-481`) | **WIDENED (R1):** exactly two sites, `_adopt_no_id_venue_order` (key unchanged) and `_bind_resting_order` (`f'{RESTING_KEY_PREFIX}{venue_order_id}'`); planting a third still fails |
| P22 | `SUBMIT_PREFIX_SHA256` (delta `:295`, test `:541-551`) | re-pinned once for the GTD dispatch before arm; diff in evidence |
| P23 | `FROZEN_SOURCE_SHA256["classify_create_order_outcome"]` (delta `:558-573`) | re-pinned once for the `resting` keyword; `test_ioc_new_state_with_id_stays_ambiguous` is the behavioural pin |
| P24 | new `EXEC_BOOT_SWEEP_PERMITTED_CALLEES` | exact set for `_sweep_resting_orders_at_boot`: reads, `post_cancel_all` only (never `post_order`/`post_cancel_order`), local store, log |

### WP6 — Integration, re-pin, positive control
- **Integration:** `tests/integration/test_resting_order_lifecycle.py` (test-only Strategy, `manage_gtd_expiry=True`; fake sender/reader): submit ×8 → poll → one fill → cancel-replace → station cancel → GTD expiry via native timer → stop → restart → boot sweep → swept no-id intent retires `BOOT_SWEEP_RESTING_NO_FILL`. Asserts events, ledger totals, permit count, arm-gate state.
- **Re-pin** P18/P19 once after WP3–WP5.
- **Positive control (venue):** automated, the bot's job, via the existing write-signing-probe route (`scripts/venue/polymarket_us_write_signing_probe.py`) inside existing caps; assigns no cap or enablement. Rest A (BUY NO, non-post-only, GTD, 0.01, far from touch; below B_FLOOR on purpose, the probe is not the strategy) on slug X and B on slug Y; per-order cancel A, GET-confirmed; re-rest A; `cancel_all {slugs:[X]}` → A canceled, **B alive** (S-2); B's short `goodTillTime` lapses → GET EXPIRED (S-6). Flip `CANCEL_ALL_SLUG_SCOPE_VERIFIED`/`GTD_EXPIRY_VERIFIED` only on that artifact, in a reviewed commit. Route unavailable → `POSITIVE_CONTROL: PENDING (<reason>)`; constants stay False; S5 shadow does not need it (spec §7.8 needs it before promotion).
- **Done:** full gate EXIT=0, lint-imports clean, three reviewers APPROVE, evidence file written.

## 7. Dependencies and UNVERIFIED

| Item | Path | State |
|---|---|---|
| Venue order docs | `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_{overview,create-order}_2026-08-25.md` | On disk |
| SDK types | `sdk_snapshot/polymarket_us_0.1.2/types/orders.py:70-180` | On disk |
| 09-04 probe | `PRIVATE_write_sequence_probe_20260904T170856Z.json`; probe script | On disk; proved cancel-ALL + post-only only |
| Non-post-only rest, GTD honoured, slug scope, maker fee sign, halted auto-cancel | none | UNVERIFIED until WP6 (constants gate it) |
| Probe route can cancel without a permit | not read | UNVERIFIED (WP6 falls back to PENDING) |
| Kernel stop order (`on_stop` vs `_disconnect`) | Nautilus | UNVERIFIED; not relied on (4e enforces) |
| Activities feed shows a TRADE row for a passive (maker) fill | venue | UNVERIFIED; WP5 restart rule (b) also requires (a), so a missing row cannot retire a filled intent alone |

## 8. Risks and guards

| Risk | Invariant | WP | Guard |
|---|---|---|---|
| Orphan rest after crash or no-id POST | caps, no unknown exposure | 1/4/5 | GTD ≤ permit/UTC-day (S-6); boot sweep over the pre-POST slug ledger (S-2); arm gate refuses unbound orders |
| No-id resting retired while it rests or after it filled | AMBIGUOUS safety | 4e/5 | same process: ADOPT on single open match, two-pass NO_FILL; prior process: never classified, retire only after confirmed-empty slug + two consistent holding reads + no trade row |
| Node deadlock on a prior-process no-id resting intent | availability | 2/4e/5 | `BOOT_SWEEP_RESTING_NO_FILL` retires the no-fill case; only filled-while-down stays AMBIGUOUS (bounded, alerted; §10 Q1) |
| Resolver gains a dangerous callee | NO-SEND | 5 | P6/P21 named rows only; `_bind_resting_order` scanned; plant tests |
| Ledger double-hold or raise | operator caps | 3/4 | intent-keyed entry only; `settle` once; carve-out scoped to `ACCEPTED_RESTING` |
| Cross-day/cross-permit accounting | single-day stop | 1 | expire bound; restore only for this-process ids |
| Own rests disarm every family | availability | 4b | WIDENED own-order rule; unbound still refuses |
| Account-wide cancel | unknown orders never cancelled silently | 4a | body required; scope-verified constant; manual order on a family slug canceled and WARN-logged with id (spec §9.18) |
| Cancel path fires in tests | NO-SEND | 4 | spy-based OS-block tests; P1–P5, P24; firewall delta |
| Native reconciliation false REJECTED | correctness | 5 | `open_check_*`/`inflight_check_*` off; fills via `query_order` only |
| Bid crosses | economics | 3 | strategy never-cross pre-check; create-path fill tagged TAKER, counted separately |
| Silent poll failure | detection | 5 | three-strike latch + alert |
| Poll lag CONTRADICTs a concurrent no-id intent (R5) | liveness | 5 | a 30 s-lagged poll can leave `durable_net` behind a venue fill on the same instrument, so a concurrent no-id intent's holding delta reads unexplained → CONTRADICTION/DUPLICATE_SUSPECT. Fail-closed; accepted liveness cost; the next pass after the poll books clears it only if no other evidence remains |
| Churn: relaunch ×3, UTC midnight, permit expiry cancel all rests | fill rate | 4e/1 | spec §3/§9.15: new episode, counted by Stage 0 and S5 |
| Old supervisor meets a new reason | supervisor safety | 2 | supervisor-first + two runtime admission checks |

## 9. Effort and evidence

| WP0 2 | WP1 4 | WP2 2 (+restart) | WP3 5 | WP4 10 | WP5 9 | WP6 5 | reviews and gates (~25 min × 6) 4 | **≈ 41 agent-hours** |
|---|---|---|---|---|---|---|---|---|

WP1 ∥ WP2; WP3→WP4→WP5 serial (all edit `exec/client.py`). Evidence: `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`.

## 10. Open questions for peer review

1. Filled-while-down no-id resting intent stays AMBIGUOUS (rare: no-id POST × restart within the resolver floor × maker fill). Is that acceptable, or should `_leg_from_trade` read the passive leg id so the sweep can ADOPT it by echo (a new attribution rule, more pins)?
2. Two-pass NO_FILL / holding reads ≥ 60 s apart: enough margin for `/orders/open` and positions eventual consistency?
3. Is the 30 s poll acceptable vs the private WS order stream, given cancels are read-confirmed anyway?
4. Should `CANCEL_CONFIRM_DEADLINE_S` escalation latch the whole client or only the slug (K=1 makes every refusal unscoped today)?

## 11. Reviewer conflicts and how r2/r3 resolve them

- **AMBIGUOUS no-id resting:** resolver cancel (r1 security) vs ADOPT (architect) vs orphan after restart (Codex) vs restart ADOPT impossible (r2 security R2). **r3:** ADOPT only in-process from open orders; after restart, sweep-only retirement with a new negative reason; resolver stays egress-free.
- **Resolver pin:** r2 claimed P6 unchanged; r2 security R1 showed otherwise. **r3:** WIDEN P6 + T42(iv) by named rows through one scanned binder, chosen over a non-resolver binder coroutine because it reuses one helper for both callers (DRY) and keeps every resolver-reachable write scanned.
- **Unverified slug scope:** security (per-order fallback) vs Codex (hard STOP). **Followed Codex** (S-2), plus refuse-until-verified constant; the sweep also refuses while unverified.
- **GTD:** native timer AND venue GTD (S-6). GTC refused.
- **Exposure key:** intent-keyed (zero ledger change).

## 12. Spec inputs

Closed. All seven r2 inputs (GTD not GTC, UTC-day expire term, relaunch/permit churn in the clock, K=1 released on resting accept with no new intent model, maker fee sign from the wire, taker fills separate, boot-sweep cancels manual orders on family slugs) are absorbed by spec v0.3 §2, §3, §9.2, §9.15, §9.18. Do not re-open them.

## 13. Review disposition

| Review | # | Disposition |
|---|---|---|
| S4-r2-final (security) | R1 MAJOR | ACCEPTED: §6.7 P6, P21; §WP3 binder; §WP5 RED renamed |
| S4-r2-final | R2 MAJOR | ACCEPTED: §WP4e step 3, §WP5 "prior process", §WP2 new reason; "fill leg (ADOPT)" removed |
| S4-r2-final | R3 MINOR | ACCEPTED: §WP5 "No-id attribution change" |
| S4-r2-final | R4 MINOR | ACCEPTED: §WP4e steps 4–5 |
| S4-r2-final | R5 MINOR | ACCEPTED: §8 row |
| S4-r2-final | spec §12 MINOR | ACCEPTED: §12 closed |
| S4-r2-codex-venue | READY-WITH-NOTES | no change required; venue facts stay gated by WP6 and the constants |
| r1 architect / security / codex | all | as dispositioned in r2 §13 (unchanged; carried in §5–§8 above) |
