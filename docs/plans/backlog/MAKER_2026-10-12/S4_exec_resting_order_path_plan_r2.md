# S4 — Exec resting-order path (GTD BUY NO, cancel, many orders under K=1)

| Field | Value |
|---|---|
| ID | S4 |
| Revision | r2 (supersedes r1; addresses `reviews/S4-r1-architect.md`, `S4-r1-security-reviewer.md`, `S4-r1-codex-venue.md`) |
| Date | 2026-10-12 |
| Status | READY-FOR-REVIEW (nothing built) |
| Programme | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.3 §3, §4, §9.1, §9.2, §9.7 |
| Prior art (unbuilt) | `docs/plans/RESTING_BID_HUNT_2026-09-16.md` §4 Rev 2 (venue facts reused; its heavier pieces dropped) |

## 1. Hard invariants (binding on every WP and every brief)

- Nautilus Trader is immutable. Extend only via `LiveExecutionClient` overrides and native `Strategy` calls/config.
- `allow_short` stays `False`. Only BUY is mappable. NO is bought as the NO instrument (wire price via `leg_prices`).
- Never weaken or delete a safety, settlement, contract or NO-SEND firewall test. Every exact-set barrier is WIDENED by named reviewed rows (§6.7 table) with a non-vacuity proof, never relaxed (L-12). S-4 STOP if only relaxing turns it green.
- Never assign a value to the two operator caps. Never touch `BREEZY_ORDERS_ENABLED`, the live-orders ruling, or any enablement. S4 makes a path *possible*; it arms nothing.
- No frozen PREREG is edited. Stage 0 is never promotion evidence. The NO-TRADE ruling stays in force.
- Worktrees: `PYTHONPATH=<wt>/src`; no uv/pip; no `git stash`; full gate after every merge (`--basetemp ~/.cache/...`, rm after reading EXIT); `cd <wt> && lint-imports` must print "N kept, 0 broken".

## 2. Goal state (acceptance test)

On the no-egress gate (fake sender/reader), a test Strategy on `PolymarketUSExecutionClient` proves:
1. `submit_order(LimitOrder BUY NO, qty 1, price ≤ 0.80, TimeInForce.GTD, expire_time ≤ bound)` → `OrderAccepted`; intent retired `ACCEPTED_RESTING`; K=1 slot free.
2. `cancel_order` → `OrderCanceled` only after a GET shows the order terminal; ledger settled once; permit slot restored (this-process ids only).
3. Station cancel = `cancel_order` on each of its ≤ 2 orders. Slug-scoped cancel-all exists only for the boot sweep and the unconfirmed-cancel escalation.
4. Eight resting orders coexist; fills found by native `query_order`, booked at venue price/commission, MAKER/TAKER from the booking path.
5. A no-id AMBIGUOUS resting POST resolves by ADOPT (order visible) or two-pass NO_FILL (not visible); after a restart, the boot sweep cancels every order on every slug in the durable slug ledger and confirms by read.
6. A map-bound resting order does not disarm any family's arm gate; an unbound open order still refuses.

Venue facts (S-1, S-2, S-6) are pinned by the WP6 positive control. Until then the two `*_VERIFIED` constants stay `False` and the adapter refuses every resting submit (§6 WP1).

**Artifact:** `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`. It holds RED→GREEN logs per WP, gate `EXIT=0` lines, the lint-imports line, one section per pin row in §6.7 (diff + reviewer), the supervisor restart time, and the WP6 verdict or `POSITIVE_CONTROL: PENDING (<reason>)`.

## 3. Entry criteria and STOP conditions

**Entry (before WP1):** S2 Stage 0 verdict is not NO-GO; S3 A1 floor for the maker mix is not `unreachable_veto`; WP0 did not STOP. WP0 starts now (read-only).

**STOP (programme ends; record in evidence + PROGRESS):**
- S-1: a non-post-only GTD limit BUY NO does not rest on `tc-temp-*` (rejected, forced IOC, or requires `participateDontInitiate`). Codex F4: GTC+post-only at 0.01 (09-04) does not prove this.
- S-2 (r2, Codex F1): **slug-scoped cancel-all is unavailable or not honoured** (a second order on another slug must survive `{slugs:[X]}`). The boot sweep is the only remover of a no-id orphan after a restart, so per-order cancel alone is not enough.
- S-3: open orders cannot be enumerated (`GET /v1/orders/open` and `GET /v1/order/{id}` both unavailable).
- S-6 (r2, security F3): **venue-side GTD expiry is not honoured** (`goodTillTime` unaccepted, or the order outlives it). Without it a SIGKILL/OOM leaves rests nobody observes.

**STOP (this step only; to the peer loop, never the operator):** S-4 a pin needs relaxing; S-5 the venue requires `participateDontInitiate` (forces a maker-fee branch in `fees.py`/`BacktestOrderGuard`, out of scope).

## 4. Simplest direct path

Keep the K=1 submit latch as a one-POST-at-a-time serializer. Retire it `ACCEPTED_RESTING` once the venue confirms a resting order with an id. Eight concurrent orders are then just eight `ACCEPTED` orders in the Nautilus cache. The ledger entry stays keyed by `intent_id` (registered at arm today) and is settled once on cancel or fill.

Every order is GTD with `expire_time ≤ min(D 09:00 LST, permit.expires_at_ns, end of the booking's UTC day)`. So every rest dies inside its permit, its process's daily budget day and its venue backstop. That one bound removes cross-permit restore, cross-day double-charge and unbounded orphans; no extra machinery is needed.

Fills come from native `Strategy.query_order` on a timer through a `_query_order` override. Cancels are by id, confirmed by GET. A no-id AMBIGUOUS resting POST resolves in-process by ADOPT, which reuses the existing join. After a restart, one boot sweep runs slug-scoped cancel-all over the slugs we durably recorded before each POST.

**Not built:**
- a separate resting store (one key prefix in the existing store is enough);
- venue modify (cancel-then-submit instead);
- K>1 or a new intent model (spec §9.2 is a spec v0.3 input);
- the private WS order stream (§5);
- native continuous reconciliation;
- post-only / a maker-fee branch;
- adopting a prior process's rests (the boot sweep cancels them instead; queue position is lost, stated in §8).

## 5. Nautilus null-hypothesis check

| Need | Native capability (evidence) | Verdict |
|---|---|---|
| Resting limit | `TimeInForce.GTD` + `LimitOrder.expire_time`; venue enum maps `exec/reports.py:431-434`, states `:441-456`; `goodTillTime` already in `_ORDER_KEYS` (`reports.py:246-269`) | Native. Adapter refuses at `submit_chain.py:331-332, :353`. **Gap: adapter shape.** |
| Client-side expiry | `StrategyConfig.manage_gtd_expiry=True` → `Strategy` sets a timer and cancels at `expire_time` (`trading/strategy.pyx:888-889`, `:1912`; config `trading/config.py:58,93`). **Not** `manage_stop`: it closes positions (`config.py:61,94`), which conflicts with hold-to-settlement and SELL refusal. Spec v0.3 also uses `clock.set_time_alert` for hard cancels. | Native; the maker strategy sets it. Venue `goodTillTime` is the backstop (S-6). |
| Events | `generate_order_accepted/canceled/expired/filled/cancel_rejected` (`execution/client.pxd:118,157,173,181,135`). There is NO `generate_order_pending_cancel`: `Strategy.cancel_order` already applies PENDING_CANCEL (`strategy.pyx:1299,1660`). | Native. **The client never emits PENDING_CANCEL.** |
| Verbs | `Strategy.submit_order`, `cancel_order` (`strategy.pyx:1089`), `cancel_orders` (`:1134`), `cancel_all_orders` (`:1215`), `query_order` (`:1527`) | Native. |
| Client hooks | `LiveExecutionClient._cancel_order/_cancel_all_orders/_batch_cancel_orders/_modify_order/_query_order` (`live/execution_client.py:516-532, 618-633`); Breezy bodies refuse/raise at `exec/client.py:7587, 7606, 7609, 7612` | **Gap: bodies** for cancel, cancel-all, query. Modify and batch keep raising. |
| Fill detection | Chosen: `query_order` → our `_query_order` override, which GETs by id and emits events itself. Rejected (1): native `_query_order` → `generate_order_status_report` → `_send_order_status_report` → `_reconcile_order_report` → `_generate_inferred_fill` (`execution_engine.py:3485`). It loses venue commission, writes no durable record before the event, skips ledger settle, and opens the report-injection seam. Rejected (2): `open_check_*` → false REJECTED on `ORDER_NOT_FOUND_AT_VENUE` (`execution_engine.py:1319-1332, 1426-1483`). Breezy makes that reachable because `generate_order_status_reports` returns `[]` for open_only (`client.py:5218-5219`) and `generate_order_status_report` returns None on read error (`:5159-5165`). Rejected (3): **private WS order stream** (venue docs `api-reference_orders_overview_2026-08-25.md:63-68`). It is documented and lower-latency, but never wire-verified, unsnapshotted, and it shares the 10-subs/connection cap with MARKET_DATA. At 8 orders × 30 s polling ≈ 0.27 req/s of 20 req/s. Revisit if poll latency costs fills (§10 Q3). | **Override `_query_order`.** Poll failures latch loudly (WP5). |
| Arm gate | `startup_evidence_refusal_reason` (`strategy/current_rung_hold/trial_day_latch.py:1512-1552`) refuses on ANY open order. It is re-checked at arm/re-arm (`continuous_strategy.py:795, 2366`); evidence is written by the exec client (`client.py:6270-6287`) and refreshed mid-day by R-9a (`client.py:2993-2997`). `client.py:477` is only the reason constant. | **Gap: WIDENED own-order rule** (WP4b). |
| No-id resolution | `classify_no_id_evidence` (`no_id_attribution.py:308-365`): an echo-matching in-window open order is CONTRADICTION (`:296-304, :353-354`); an unreadable open-order read is INCOMPLETE (`:359-360`); ADOPT exists for legs (`:362-363`) and hands off to `_adopt_no_id_venue_order` (`client.py:4682-4691`) → with-id path | **Gap: resting ADOPT branch** (WP5). No resolver egress. |
| Caps/exposure | `register_open_exposure` at arm keyed by `intent.intent_id` (`client.py:7122-7135`); `settle(key, booking, realized_usd, fill_ts_ns)` (`operator_controls.py:844-891`); `release_booking`/`true_up_booking` raise for a registered booking (`:614-624`, `:635`). Permit: `assert_live_order_submission_permitted` (`safety.py:953`), `restore_live_trading_budget` (`:857`, idempotent per id, current permit only), TTL 10 h (`:172`) clamped to the first boot (`:682-692, :730`) | Reuse unchanged. **Gap: call sites** + a `_retire` carve-out (`client.py:6683-6696`). |
| Multi-order | K=1 latch; `RetirementReason` (`runtime/submit_intent.py:128`) | **Gap: one reason.** |
| Cancel transport | `post_cancel_all` (`write_transport.py:160-175`), body-less, zero call sites; sender is the transport object, `order_sender: Any` (`client.py:1795, 1891`), wired in `factories.py:835` | **Gap:** `post_cancel_order`, slug body. Same object, so no Protocol or factory change. |

## 6. Work packages

Routing (CLAUDE.md): build = Grok → Codex → Claude `tdd-guide` (seeded `nautilus-trader-patterns`, `polymarket-us-integration`); review = `python-reviewer` + `prediction-market-reviewer` + `security-reviewer` on every egress-touching WP. The coordinator re-runs every gate. Every brief restates §1.

**Focused gate (every WP):** `PYTHONPATH=<wt>/src scripts/ci/run_tests_no_egress.sh <list> --basetemp ~/.cache/breezy-gate/s4-<wp>`. The list always includes:
- `tests/unit/test_execution_egress_firewall_guard.py`, `tests/unit/test_polymarket_us_readonly_guard.py`, `tests/unit/test_cage_rule_constants_are_pinned.py`;
- `tests/contract/test_us_source_ingest_egress_guard.py` (incl. x1 `test_exec_import_pin_x1_is_superset_of_recorded_baseline`);
- `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`, `tests/unit/test_autonomy_*.py`, `tests/unit/test_ambig_no_id_firewall_delta.py`;
- `tests/unit/test_polymarket_us_exec_client.py`, `tests/unit/test_daily_spend_ledger_open_exposure.py`, `tests/unit/test_live_trading_budget_restore.py`;
- the new S4 test files.

Then the full gate after merge, then lint-imports.

### WP0 — Venue discovery (read-only; `polymarket-us-discovery`; starts now)
- **Inputs:** `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_*`, `sdk_snapshot/polymarket_us_0.1.2/types/orders.py:70-180` (`CancelOrderParams.marketSlug`, `CancelAllOrdersParams.slugs` `:147-156`), `PRIVATE_write_sequence_probe_20260904T170856Z.json`.
- **Pin from docs, or mark UNVERIFIED (write-verified facts wait for WP6):**
  - (a) non-post-only GTD on `tc-temp-*`;
  - (b) `goodTillTime` spelling, format, and whether it is honoured;
  - (c) per-order cancel `POST /v1/order/{id}/cancel` body `{marketSlug}`;
  - (d) `{slugs:[…]}` cancel-all scoping;
  - (e) create response for a rest under `synchronousExecution=true, maxBlockTime=5`;
  - (f) maker commission field name and **sign** (skill says −0.0125 rebate; never hard-coded);
  - (g) halted-market auto-cancel and the `unsolicitedCancelReason` field;
  - (h) private-WS order-stream doc snapshot (documentation only, §5).
- **Budget:** GETs only, ≤ 60, ≤ 1 per 3 s. No POST.
- **Output:** dated note under `docs/evidence/venue/polymarket_us/` + skill rows (`provisional: true`).
- **Done when:** (a)–(h) each PINNED or UNVERIFIED with a source line. S-1/S-2/S-3/S-6 checked on docs.

### WP1 — Resting shape + classifier (pure; `exec/submit_chain.py`)
- **Interfaces:**
  - `unmappable_resting_order_reason(order, instrument, *, permit_expires_at_ns: int, now_ns: int) -> str | None`, a third shape. The IOC (`:322-363`) and exit (`:448-483`) shapes stay byte-identical. It admits only: LIMIT, BUY, qty == 1, NO leg, price in (0, `RESTING_PRICE_CAP`=0.80], `TimeInForce.GTD`, `expire_time` set with `now < expire_time ≤ min(permit_expires_at_ns, utc_day_end(now_ns))`, `post_only False`, no reduce-only/display/trigger. **GTC is refused** (security F3; spec input). The D 09:00 LST term is the strategy's (station tz unknown to the adapter).
  - It refuses while `GTD_EXPIRY_VERIFIED is not True` or `CANCEL_ALL_SLUG_SCOPE_VERIFIED is not True`. Both are module constants flipped only on WP6 evidence, the `WRITE_CANONICAL_STRING_VERIFIED` precedent.
  - `build_resting_order_body(order, instrument) -> dict` emits `RESTING_ORDER_BODY_KEYS` = IOC keys with `tif=GTD` + `goodTillTime` (format per WP0(b)). `encode_order_body` (`:578`) accepts exactly `ORDER_BODY_KEYS` or `RESTING_ORDER_BODY_KEYS`, still equality.
  - `classify_create_order_outcome(..., closing=False, resting: bool = False)` (`:1206`). `KIND_ACCEPT_RESTING` only when `resting` and `id` present and state `ORDER_STATE_NEW`. Every other resting outcome follows today's paths (fill/reject/AMBIGUOUS). `resting=False` is byte-unchanged.
  - Constants: `RETIRE_ACCEPTED_RESTING = "ACCEPTED_RESTING"` beside `:55-57`, mapped in `retirement_member` (`:1514`).
- **RED** (`tests/unit/test_polymarket_us_resting_order_shape.py`):
  - `test_ioc_shape_still_refuses_gtc_byte_identically`, `test_resting_shape_admits_gtd_buy_no_qty1_at_080`, `test_resting_shape_refuses_gtc`;
  - `test_resting_shape_refuses_expire_after_permit_expiry`, `test_resting_shape_refuses_expire_after_utc_day_end`;
  - `test_resting_shape_refuses_while_slug_scope_unverified`, `test_resting_shape_refuses_while_gtd_unverified`;
  - `test_resting_shape_refuses_{price_above_080,yes_leg,sell,post_only}`;
  - `test_resting_body_key_set_is_exact`, `test_encode_refuses_a_mixed_key_set`;
  - `test_classify_new_state_with_id_is_accept_resting_only_when_resting`, **`test_ioc_new_state_with_id_stays_ambiguous`** (architect F6), `test_classify_resting_response_without_id_is_ambiguous`.
- **Done:** RED→GREEN. `test_polymarket_us_submit_order_chain.py` and `test_no_side_submit_chain_2026_09_14.py` pass unmodified.

### WP2 — Retirement vocabulary (supervisor-first; parallel with WP1)
- **Change:** add `RetirementReason.ACCEPTED_RESTING` (`runtime/submit_intent.py:128`). The order fingerprint already hashes `time_in_force` (`domain/exec_intent.py:45`), so there is no parity row (architect, verified).
- **Deploy:** merge → supervisor restart (01:00–16:40Z) → only then may a node write it.
- **Runtime guard (architect F11):** the client refuses the resting shape unless `supervisor_admits_retirement_reason(store, "ACCEPTED_RESTING")` (`runtime/supervisor_decode_marker.py:166`), mirroring `_no_id_retire_admitted` (`client.py:1904`), fail-closed.
- **RED:** `test_accepted_resting_round_trips_and_releases_the_slot`, `test_reconcile_at_startup_leaves_an_accepted_resting_record_retired`, `test_retirement_reason_set_is_widened_by_exactly_one_row`, `test_resting_submit_refused_until_supervisor_admits_accepted_resting`.

### WP3 — Submit path (`exec/client.py` `_submit_order` :6880)
- **Dispatch:** `unmappable_resting_order_reason` when `order.time_in_force == GTD`, else today's path. The deny chain, its order and its no-await spans are unchanged. Arm-time `register_open_exposure(intent.intent_id, booking.cost, booking=…)` (`:7122-7135`) stays **the only registration** (architect F1a, security F1).
- **Durable slug ledger, written pre-POST:** the existing resolver context (written before the POST, `:7136-7140`) already carries the wire echo with the slug. Add `resting: bool` to `AmbiguousResolverContext`; absent decodes as `False` (old rows are IOC by construction). No new store.
- **On `KIND_ACCEPT_RESTING`**, synchronous, no `await` between steps:
  1. durable binding row `resting:<venue_id>` → `{intent_id, slug, client_order_id, expire_time_ns}` via `_store_set`;
  2. in-memory `_resting_bookings[venue_id] = (intent_id, booking)`;
  3. `_this_process_resting_ids.add(venue_id)`;
  4. `_retire(intent_id, RETIRE_ACCEPTED_RESTING)`;
  5. `generate_order_accepted`.
- **`_retire` carve-out (architect F1c):** the E1 leak check (`:6683-6696`) is skipped iff `retire_name == RETIRE_ACCEPTED_RESTING` and `intent_id` is in `_resting_bookings` values. Any other retire with an open entry still counts and logs.
- **Taker on create (architect F7):** a create returning a fill (`KIND_ACCEPT_FILL`) for a resting-shape order is booked as today and tagged `liquidity_side=TAKER`, WARN `resting_order_crossed`.
- **RED** (`tests/unit/test_polymarket_us_resting_submit.py`):
  - `test_resting_accept_emits_order_accepted_and_retires_accepted_resting`;
  - **`test_resting_accept_does_not_double_register_exposure`** + `_day_roll_variant` (security F1);
  - **`test_accept_resting_does_not_count_as_registry_leak`**, `test_other_retire_with_open_entry_still_counts_as_leak`;
  - `test_resting_binding_row_written_before_accepted_event`;
  - `test_resting_submit_decrements_the_permit_order_count`, `test_headroom_refusal_denies_a_resting_submit_without_a_post`;
  - `test_eight_resting_orders_coexist_with_k1`, `test_a_ninth_order_is_refused_by_headroom_not_by_the_latch` (fixture caps only);
  - `test_create_fill_on_resting_shape_is_taker`, `test_ioc_submit_path_is_byte_identical_for_ioc_orders`.

### WP4 — Cancel path, boot sweep, own-order rule (new egress)
**4a transport** (`write_transport.py`):
- `CANCEL_ORDER_PATH_TEMPLATE="/v1/order/{id}/cancel"`;
- `post_cancel_order(api_base_url, *, order_id, headers, body)`, with the id checked by an **allowlist** `^[A-Za-z0-9_-]{1,64}$` (security F9);
- `post_cancel_all(..., body)`: body **required** and exactly `{"slugs":[non-empty, each tc-temp-*]}`. The body-less form is removed (zero call sites, `:160`), so the client can never post an account-wide cancel. POST only, existing signer.
- The client signs `sign_headers(_WRITE_METHOD, <exact path>)`. No new key material.

**4b own-order rule (architect F2):**
- `StartupOpenOrderSnapshot` gains `own_resting: bool`. The exec client sets it True iff `venue_order_id` has a live `resting:` row whose slug matches. The parser (`client.py:1446-1465`) decodes an absent key as `False` (fail closed).
- `startup_evidence_refusal_reason` (`trial_day_latch.py:1540`) refuses only if an open order with `own_resting is not True` remains. WIDENED rule; every other refusal is unchanged.
- The maker strategy's own arm gate is this same `startup_evidence_permits_arm` (obligation on the maker strategy builder; S4 tests it with the test Strategy).

**4c `_cancel_order`** (`:7587`):
- Refuses via `generate_order_cancel_rejected` unless the sender is injected, canonical is verified, and the venue id is bound. It never arms the intent and never asserts the permit (it only reduces risk). The order is already PENDING_CANCEL (native).
- Flow: POST cancel → poll `GET /v1/order/{id}` until terminal or `CANCEL_CONFIRM_DEADLINE_S` (PROVISIONAL 30 s) →
  - CANCELED/EXPIRED with `cumQuantity==0`: `generate_order_canceled`/`_expired`; then **`ledger.settle(intent_id, booking, realized_usd=None, now_ns)` exactly once** (security F6, architect F1b); then `restore_live_trading_budget(venue_id)` **iff** the id is in `_this_process_resting_ids` (security F7); then delete the binding row;
  - FILLED: WP5 fill path; no restore (security F11);
  - unconfirmed: slug-scoped cancel-all on that slug, read-confirm, else latch `resting_cancel_unconfirmed` (existing alert delivery). New submits are refused; cancels continue.
- A bare 200 never emits CANCELED.

**4d `_cancel_all_orders`** (`:7609`): one `_cancel_order` per bound order on the slug. No venue cancel-all call. That keeps cancel-all off the strategy path.

**4e boot sweep** `_sweep_resting_orders_at_boot()` in `_connect` (`client.py:2283`), before the startup evidence write:
- Slugs = all `resting:` rows ∪ `resting=True` resolver contexts (the durable slug ledger).
- For each slug: read `/orders/open` (record ids), `post_cancel_all({slugs:[slug]})`, re-read, require nothing open on the slug, log the canceled ids (WARN if any is unbound: a manual order on our slug).
- Fill-walk then reconciles any fill. Rows are deleted only for ids read as terminal. Nothing is restored to the new permit, and a prior process's seeded spend stays charged (conservative, security F7).
- If the sender is absent or canonical is unverified, there is no sweep, and today's refusal plus alert stands.
- Mid-day relaunch (3× per 5 min until 01:00Z) therefore cancels every rest each time. That churn and queue reset are accepted (§8).

**4f on_stop:** the maker strategy calls `cancel_all_orders` per instrument. This is best-effort (kernel shutdown). GTD expiry and the boot sweep are the guards (architect F12).

**RED** (`tests/unit/test_polymarket_us_resting_cancel.py`):
- `test_bare_200_does_not_emit_order_canceled`, **`test_zero_fill_cancel_settles_exactly_once`** (`_spent_usd` returns to pre-submit), **`test_cancel_settles_via_settle_not_release_booking`**;
- `test_restore_only_for_this_process_ids`, `test_restore_is_idempotent_per_venue_order_id`;
- `test_cancel_post_200_but_get_filled_routes_to_fill_and_does_not_restore`;
- `test_unconfirmed_cancel_escalates_to_slug_cancel_all_and_latches`, `test_cancel_allowed_with_expired_permit`, `test_cancel_never_arms_the_submit_intent`, `test_client_never_emits_pending_cancel`;
- **`test_cancel_signature_covers_the_exact_cancel_path`**, `test_cancel_order_id_allowlist_refuses_traversal`;
- **`test_cancel_all_never_posts_without_slug_body`**, **`test_slug_cancel_all_refused_while_scoping_unverified`**;
- `test_boot_sweep_cancels_every_slug_in_the_durable_ledger_and_confirms_by_read`, `test_boot_sweep_covers_a_no_id_ambiguous_resting_intent` (Codex F2), `test_boot_sweep_touches_no_slug_outside_the_ledger`, `test_boot_with_unbound_open_order_off_ledger_still_refuses_and_alerts`;
- **`test_map_bound_resting_orders_do_not_refuse_arm`**, **`test_unbound_open_order_still_refuses_arm`**, `test_pre_s4_evidence_bytes_decode_own_resting_false`.

**OS-block proof (security F5, replaces r1's unpassable design)** in `tests/unit/test_polymarket_us_write_transport.py`:
- `test_post_cancel_order_is_refused_by_the_os_egress_block` and `test_post_cancel_all_with_slugs_is_refused_by_the_os_egress_block`.
- Each wraps the REAL `nautilus_pyo3.HttpClient` in a recording spy that captures the raw pyo3 exception before `write_transport` re-raises it `from None` (`:167-170, :186-189`).
- Each classifies **that** exception with `classify_canary_failure` (`test_execution_egress_firewall_guard.py:383-406`) as BLOCKED, and asserts `VenueTransportError` is raised.
- Each uses dummy credentials/headers and a nonexistent id, and **fails, not skips**, when `os_egress_block_attested()` (`:458`) is False.
- The classifier is never edited.

### WP5 — Fill detection, AMBIGUOUS-resting, poll health (`exec/client.py`)
**`_query_order` override** (new body; it no longer raises unimplemented). For a bound id: `GET /v1/order/{id}` via `_private_read` →
- `cumQuantity` delta > 0: write the durable fill record **first** (existing `record_fill` path). Then `generate_order_filled` with `last_px` = venue `avgPx` inverted to the NO leg via `leg_prices`, `commission` = the venue commission field **with its venue sign** (WP0(f); a rebate is negative `Money`; never inferred from the skill constant), and `liquidity_side=MAKER`, because a poll-detected fill after `ACCEPTED_RESTING` is maker by construction (architect F7; the GET carries no executions, `reports.py:246-269`). Then `settle(intent_id, booking, realized_usd=<same basis the accept-fill path passes>, fill_ts_ns)`.
- CANCELED/EXPIRED/REJECTED: as in 4c (an EXPIRED rest is the GTD backstop firing).
- It never calls `_send_order_status_report`.

**Poll:** the maker strategy calls `self.query_order(order)` per open rest on a native clock timer (PROVISIONAL 30 s). Three consecutive failed GETs for one id latch `resting_query_unreadable` (alert). Submits are refused; cancels continue (Codex F3 "latch loudly").

**AMBIGUOUS resting POST** (intent OPEN, booking held, other submits wait, cancels run):
- *With id:* the existing with-id resolver after its 120 s floor (`client.py:1617`). GET NEW on a `resting=True` context binds and retires `ACCEPTED_RESTING` (WP3 steps 1–5). Terminal states use today's path.
- *No id (architect F4, followed):* in `_open_order_verdict` (`no_id_attribution.py:285-305`), when `echo.resting` is True, a **single** echo-matching in-window unknown open order is an ADOPT candidate, not CONTRADICTION. Two or more stay CONTRADICTION; IOC behaviour is byte-unchanged. ADOPT → `_adopt_no_id_venue_order` → with-id path → NEW → `ACCEPTED_RESTING`. **No cancel in the resolver**: `EXEC_RESOLVER_PERMITTED_CALLEES` (firewall `:2155`) stays egress-free.
- *No id, nothing visible:* NO_FILL for a resting context needs **two** NO_FILL verdicts ≥ 60 s apart (security F2b, eventual consistency of `/orders/open`). Both are read after the 300 s floor (`client.py:1625`), which already exceeds the 65 s fate-fixed bound set by the venue's signed-timestamp window (`:1617-1623`). A POST cannot land later (security F2a rebutted, §11).
- *Restart before resolution (Codex F2):* the boot sweep (4e) cancels on the context's slug and confirms by read. The resolver then sees either a fill leg (ADOPT) or nothing (NO_FILL).

**RED** (`tests/unit/test_polymarket_us_resting_query.py`, `tests/unit/test_no_id_attribution_resting.py`):
- `test_query_detects_fill_with_venue_signed_commission`, `test_query_fill_writes_durable_record_before_event`, `test_poll_fill_after_accepted_resting_is_maker`, `test_query_never_reaches_send_order_status_report`;
- `test_three_failed_polls_latch_resting_query_unreadable`;
- `test_resting_single_echo_match_open_order_is_adopt`, `test_ioc_echo_match_open_order_stays_contradiction`, `test_resting_two_echo_matches_stay_contradiction`;
- `test_no_id_resting_no_fill_needs_two_reads`, **`test_late_landing_post_after_first_read_is_caught_by_second_read`**;
- `test_with_id_ambiguous_resting_new_state_retires_accepted_resting`, `test_cancels_proceed_while_an_ambiguous_intent_is_open`;
- `test_restart_reconciles_a_fill_that_happened_while_down`, `test_resolver_permitted_callees_unchanged`.

**Firewall delta:** new `tests/unit/test_resting_path_firewall_delta.py` (precedent `test_ambig_no_id_firewall_delta.py`). It freezes pre-S4 literals, pins each new awaited callee, and plants a violation per guard to prove non-vacuity.

### 6.7 Exact-set pins and drift allowlists touched (each a WIDENED row; evidence = one section of the S4 evidence file + named test)
| # | Pin (file:line) | Change |
|---|---|---|
| P1 | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (firewall `:1952`) | + `self.generate_order_accepted`, `self.generate_order_expired`, `self.generate_order_canceled`, `self.generate_order_cancel_rejected`, `submit_chain.unmappable_resting_order_reason`, `submit_chain.build_resting_order_body`, `self._order_sender.post_cancel_order`, `self._order_sender.post_cancel_all`, `self._private_read`, `restore_live_trading_budget`, `self._mark_budget_restored`, `self._ledger.settle` (exact names fixed at build; each listed in evidence) |
| P2 | `test_no_shipped_exec_order_coroutine_awaits_anything` (`:2977`) | Exempts exactly `_cancel_order`, `_cancel_all_orders`, `_query_order`, whose awaits are pinned by a new exact set `EXEC_CANCEL_QUERY_AWAITED_CALLEES`. Every other coroutine still awaits nothing |
| P3 | `EXEC_DECLARED_UNIMPLEMENTED_COROUTINES={"_query_order"}` (`:2111`) | → `frozenset()`; `_query_order` joins a scanned GET-only set `EXEC_QUERY_PERMITTED_CALLEES` (resolver-style; no `post_*`) |
| P4 | `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) | + `_sweep_resting_orders_at_boot`, `_confirm_terminal_by_read` |
| P5 | `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) | + `_cancel_order`, `_sweep_resting_orders_at_boot` |
| P6 | `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2155`) | **unchanged**, asserted by `test_resolver_permitted_callees_unchanged` |
| P7 | readonly guard V2/B4 (`test_polymarket_us_readonly_guard.py`) | cancel-path literal admitted in `write_transport.py` only; copycat still trips |
| P8 | E0 `test_n2_…expected_execution_egress_modules` (`:710`) | unchanged (no new module); E3 row + `post_cancel_order` iff E3 classifies methods |
| P9 | `test_the_other_four_lifecycle_coroutines_raise_unsupported` (`test_polymarket_us_exec_client.py:1650`) | modify + batch still raise; cancel/cancel-all/query move to positive tests; never deleted |
| P10 | `test_native_query_order_never_reaches_the_send_seam` (`:537`) | stale premise fixed + **bound-id variant** (today vacuous at `venue_order_id=None`, `:561`) |
| P11 | `_ORDER_DRIFT_ALLOWED_KEYS` (`reports.py:291`) | + `unsolicitedCancelReason` **only** if WP0(g)/WP6 observes it (venue evidence note cited). `parse_open_orders` records unknown keys non-fatally (`:1643-1649`): no row. `_EXECUTION_DRIFT_ALLOWED_KEYS` (`:333`) unchanged |
| P12 | `RetirementReason` (`submit_intent.py:128`) + `RETIRE_*` (`submit_chain.py:55-57`) | + `ACCEPTED_RESTING` |
| P13 | `encode_order_body` key equality (`submit_chain.py:578`) | + `RESTING_ORDER_BODY_KEYS` alternative |
| P14 | `startup_evidence_refusal_reason` (`trial_day_latch.py:1512-1552`) + snapshot parser (`client.py:1446-1465`) | own-order exclusion (4b) |
| P15 | `_retire` E1 leak backstop (`client.py:6683-6696`) | `ACCEPTED_RESTING` carve-out |
| P16 | `test_cage_rule_constants_are_pinned.py` | RulePin rows `RESTING_PRICE_CAP`, `GTD_EXPIRY_VERIFIED`, `CANCEL_ALL_SLUG_SCOPE_VERIFIED`, `CANCEL_CONFIRM_DEADLINE_S` |
| P17 | `test_it_issues_exactly_one_post_to_the_one_pinned_path` (`test_polymarket_us_write_transport.py:339`) | per-method twins for cancel and cancel-all |
| P18 | `_EXEC_CLIENT_SHA256` (`test_forecast_quantile_ladder_manifest_and_markers.py`) | re-pinned once in WP6 with reviewer comment |
| P19 | `BANNED_MODULES` citations (`test_us_source_ingest_egress_guard.py:57` write_transport `147`, `:62` client `1771`, `:77` `post_order` `7182`) | line citations re-pinned (not relaxations) |
| P20 | x1 `BANNED_EXEC_TRANSPORT_MODULES` (`:611-640`) | **unchanged**: no new transport import |

### WP6 — Integration, re-pin, positive control
- **Integration:** `tests/integration/test_resting_order_lifecycle.py` (test-only Strategy with `manage_gtd_expiry=True`; fake sender/reader). Steps: submit ×8 → poll → one fill → cancel-replace → station cancel → GTD expiry via native timer → stop → restart → boot sweep. It asserts events, ledger totals, permit count and arm-gate state.
- **Re-pin** P18/P19 once after WP3–WP5.
- **Positive control (venue):** automated; the bot's job, never a UI step. It runs through the existing write-signing-probe route (`scripts/venue/polymarket_us_write_signing_probe.py`) inside existing caps, and assigns no cap or enablement.
  - Rest A (BUY NO, non-post-only, GTD, 0.01, far from touch) on slug X and B on slug Y.
  - Per-order cancel A, confirmed by GET. Re-rest A. `cancel_all {slugs:[X]}`, then A canceled and **B alive** (S-2). Let B's `goodTillTime` (short) lapse, then GET EXPIRED (S-6).
  - Flip `CANCEL_ALL_SLUG_SCOPE_VERIFIED` / `GTD_EXPIRY_VERIFIED` only on that artifact, in a reviewed commit.
  - If the route is unavailable: `POSITIVE_CONTROL: PENDING (<reason>)`. The constants stay False, so nothing can rest live; S5 shadow does not need it.
- **Done:** full gate EXIT=0, lint-imports clean, three reviewers APPROVE, evidence file written.

## 7. Dependencies and UNVERIFIED

| Item | Path | State |
|---|---|---|
| Venue order docs | `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_{overview,create-order}_2026-08-25.md` (cancel `overview:47-60`, private WS `:63-68`, GTC/GTD `create-order:164-174`) | On disk |
| SDK types | `sdk_snapshot/polymarket_us_0.1.2/types/orders.py:70-180` | On disk |
| 09-04 probe | `PRIVATE_write_sequence_probe_20260904T170856Z.json`; `scripts/venue/polymarket_us_write_signing_probe.py` | On disk; proved cancel-ALL + post-only only |
| Non-post-only rest, GTD honoured, slug scope, maker fee sign, halted auto-cancel | none | UNVERIFIED until WP6 (constants gate it) |
| Whether the probe route can authorize a cancel without a permit | not read | UNVERIFIED (WP6 falls back to PENDING) |
| Kernel stop order (strategy `on_stop` vs client `_disconnect`) | Nautilus | UNVERIFIED; not relied on |

## 8. Risks and guards

| Risk | Invariant | WP | Guard |
|---|---|---|---|
| Orphan rest after crash or no-id POST | caps, no unknown exposure | 1/4/5 | GTD ≤ permit/UTC-day (S-6 hard); boot sweep over the pre-POST slug ledger (S-2 hard); arm gate refuses unbound orders |
| No-id resting retired while it rests | AMBIGUOUS safety | 5 | ADOPT on a single echo match; two-pass NO_FILL; RED late-landing test |
| Ledger double-hold or raise | operator caps | 3/4 | intent-keyed entry only; `settle` once; leak carve-out scoped to `ACCEPTED_RESTING` |
| Cross-day/cross-permit accounting | single-day stop | 1 | expire bound makes it unreachable; restore only for this-process ids |
| Own rests disarm every family | availability | 4b | WIDENED own-order rule; unbound still refuses |
| Account-wide cancel | "unknown orders never cancelled silently" | 4a | body required; scope-verified constant; manual order on our slug is canceled and WARN-logged with id (accepted cost) |
| Cancel path fires in tests | NO-SEND | 4 | spy-based OS-block tests; P1–P5 exact sets; firewall delta |
| Native reconciliation false REJECTED | correctness | 5 | `open_check_*`/`inflight_check_*` off; fills via `query_order` only |
| Non-post-only bid crosses | economics | 3 | create-path fill tagged TAKER and counted separately; strategy pre-check `bid < best NO ask` |
| Silent poll failure | detection | 5 | three-strike latch + alert |
| Churn: relaunch ×3, UTC midnight, permit expiry each cancel all rests | fill rate | 4e/1 | accepted; queue resets counted as new t0 (spec §3) |
| Old supervisor meets the new reason | supervisor safety | 2 | supervisor-first + runtime admission check |

## 9. Effort and evidence

| WP0 2 | WP1 4 | WP2 2 (+restart) | WP3 5 | WP4 9 | WP5 7 | WP6 5 | reviews and gates (~25 min × 6) 4 | **≈ 38 agent-hours** |
|---|---|---|---|---|---|---|---|---|

WP1 ∥ WP2; WP3→WP4→WP5 serial (all edit `exec/client.py`). Evidence: `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`.

## 10. Open questions for peer review

1. Is the UTC-day-end term in the expire bound worth the churn (one re-rest per order at 00:00Z)? The alternative is cross-day settle accounting with RED tests.
2. Two-pass NO_FILL (≥ 60 s apart) for a no-id resting intent: is 60 s enough margin for `/orders/open` eventual consistency?
3. Is the 30 s poll acceptable vs the private WS order stream, given cancels are read-confirmed anyway?
4. Should the boot sweep refuse (rather than cancel and WARN) when the pre-read shows an unbound order on a ledger slug?
5. Should `CANCEL_CONFIRM_DEADLINE_S` escalation latch the whole client or only the slug (K=1 makes every refusal unscoped today)?

## 11. Reviewer conflicts and how r2 resolves them

- **AMBIGUOUS no-id resting:** r1/security (resolver cancel-all, wait-then-cancel) vs architect (ADOPT) vs Codex (orphan after restart). **Followed:** architect's ADOPT in-process, so the resolver stays egress-free. Codex's slug-ledger boot sweep covers restart. Security's second read and mandatory GTD are kept.
- **Unverified slug scope:** security (fall back to per-order cancel of bound ids) vs Codex (hard STOP). **Followed Codex:** per-order cancel cannot remove a no-id orphan. S-2 STOP, plus security's refuse-until-verified constant and RED tests.
- **GTD:** architect (native `manage_gtd_expiry`, venue backstop optional) vs security (venue expiry mandatory). **Both:** native timer AND venue GTD as S-6 hard precondition. GTC is dropped.
- **Exposure key:** security offered an atomic re-key alternative; architect and security agree on intent-keyed. **Followed intent-keyed** (zero ledger change).

## 12. Spec v0.3 inputs (not fixed here)

1. §3 says "rest GTC … expire_time": that is GTD. GTC is refused by the adapter.
2. The expire bound adds `end of the booking's UTC day`; overnight rests re-post at 00:00Z (queue reset, new t0).
3. Mid-day relaunch (×3/5 min) and permit expiry cancel every rest; the fill-rate clock (§9.15) should count that.
4. §9.2 "needs a new intent model" is false: K=1 retired on resting accept suffices.
5. Maker fee sign is read from venue fields; the `fee = θ·b·(1−b)` examples assume a positive taker θ.
6. A non-post-only bid that crosses fills as TAKER; §6 should count taker fills separately.
7. Boot-sweep cancel-all cancels any manual order on a family slug.

## 13. Review disposition

| Review | # | Disposition |
|---|---|---|
| architect | 1 BLOCKER | ACCEPTED: §WP3 (intent-keyed, binding row, carve-out), §4c settle-only |
| architect | 2 MAJOR | ACCEPTED: §WP4b, P14; gate cited at `trial_day_latch.py:1512-1552` |
| architect | 3 MAJOR | ACCEPTED: §6.7 P1–P5, P11; cancel reaches the transport via the same `_order_sender` (`client.py:1795`), so no Protocol change |
| architect | 4 MAJOR | ACCEPTED: §WP5 ADOPT; P6 unchanged |
| architect | 5 MAJOR | ACCEPTED: §WP1 expire bound (+ UTC-day term), §4c restore scope |
| architect | 6 MAJOR | ACCEPTED: §WP1 `resting` param + RED |
| architect | 7 MAJOR | ACCEPTED: §WP3 taker, §WP5 maker |
| architect | 8–12 MINOR | ACCEPTED: §5 (GTD/manage_gtd_expiry, no manage_stop; no pending-cancel; native path rejected with reasons), §WP2 admission check, §4e/4f |
| architect | mismatches | FIXED: `:477` constant only; `classify_create_order_outcome`; P10 bound-id; P19 rows `:57/:62/:77`; fingerprint already hashes TIF |
| security | 1 MAJOR | ACCEPTED: §WP3 + double-register RED and day-roll variant |
| security | 2 MAJOR | (b)(c)(d) ACCEPTED §WP5/§WP1. (a) REBUTTED: the 300 s floor already exceeds the 65 s fate-fixed bound of the signed-timestamp window (`client.py:1617-1625`) |
| security | 3 MAJOR | ACCEPTED: S-6, GTC refused |
| security | 4 MAJOR | ACCEPTED: refuse-until-verified + body required. Fallback-to-per-order superseded by Codex STOP (§11) |
| security | 5 MAJOR | ACCEPTED: spy design, fail-not-skip; classifier cited `:383-406` |
| security | 6 MAJOR | ACCEPTED: §4c single `settle(realized_usd=None)` |
| security | 7–11 MINOR | ACCEPTED: this-process restore; sender/signing named (no new keys, no factory change); id allowlist; x1 P20 + focused gate; FILLED-after-200 RED |
| codex | 1 BLOCKER | ACCEPTED: S-2 rewritten |
| codex | 2 BLOCKER | ACCEPTED: §4e boot sweep over the pre-POST slug ledger |
| codex | 3 MAJOR | ACCEPTED as documentation: §5 rejected alternative (3) + three-strike latch |
| codex | 4 MAJOR | ACCEPTED: S-1 strengthened; WP6 tests non-post-only |
| codex | 5 MINOR | ACCEPTED: §WP5 commission sign from venue; spec input 5 |
