# S4 — Exec resting-order path (GTC BUY NO, cancel, multi-order intents)

| Field | Value |
|---|---|
| ID | S4 |
| Revision | r1 |
| Date | 2026-10-12 |
| Status | DRAFT (not peer-reviewed; nothing built) |
| Programme | MAKER_2026-10-12, `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2 §3, §9.1, §9.2, §9.7 |
| Prior art (unbuilt) | `docs/plans/RESTING_BID_HUNT_2026-09-16.md` §4 (Rev 2). This plan reuses its venue facts and drops its heavier pieces (see §4). |

## 1. Hard invariants (restated, binding on every WP)

- Nautilus Trader is immutable. We extend it only through `LiveExecutionClient` overrides and native `Strategy` calls.
- `allow_short` stays `False`. Only BUY is mappable. NO is bought as the NO instrument (`outcomeSide=NO`, wire price `1-b` via `leg_prices`).
- Never weaken or delete a safety, settlement, contract or NO-SEND firewall test. An exact-set barrier is WIDENED by one reviewed row, with a non-vacuity proof, and is never relaxed (L-12).
- Never assign a value to the two operator caps (max daily budget, max per position). Never touch `BREEZY_ORDERS_ENABLED`, the live-orders ruling, or any live enablement. This plan makes a path *possible*. It arms nothing.
- No frozen PREREG is edited. Stage 0 results are never promotion evidence. The NO-TRADE ruling (`docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`) stays in force.
- Worktree runs use `PYTHONPATH=<wt>/src`. No uv/pip from a worktree. No `git stash`. Full gate after every merge.

## 2. Goal state (acceptance test)

A Nautilus `Strategy` running on `PolymarketUSExecutionClient` can do all of the following, proven on the no-egress gate against a fake sender and once against the venue:
1. `submit_order(LimitOrder BUY, NO instrument, price ≤ 0.80, qty 1, TimeInForce.GTC or GTD, post_only=False)` → `OrderAccepted` (resting).
2. `cancel_order(order)` → `OrderCanceled`, emitted only after a GET read confirms the order is terminal at the venue.
3. Cancel-all-for-station (≤ 2 instruments) → every resting order on those slugs is confirmed canceled by a read.
4. Cancel-replace = cancel, confirmed, then a new submit. Venue modify is not used.
5. Eight resting orders (4 stations × 2 rungs) held in the Nautilus cache at once, with fills detected and booked at the venue-attested price and commission.
6. Ledger, permit and exposure stay correct: resting notional counts against headroom, and a confirmed zero-fill cancel releases the booking and restores the permit's order-count slot.

**Emitted artifact:** `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`. It holds RED→GREEN logs per WP, gate `EXIT=0` lines, the `lint-imports` "N kept, 0 broken" line, every pin diff with its reviewer, and the WP6 positive-control verdict (or `PENDING` with the reason).

## 3. Entry criteria and STOP conditions

**Entry (all required before WP1 starts; WP0 may start at once because it is read-only):**
- S2 Stage 0 verdict = GO (fill rate ≥ 0.1 and §6.9 not FAIL).
- S3 A1 loss floor reachable for the maker mix (not `unreachable_veto`).
- WP0 does not STOP.

**STOP (the programme ends; record in the evidence file and in PROGRESS):**
- S-1: the venue does not accept a resting GTC/GTD limit on `tc-temp-*` weather markets. Example: rejected, or forced IOC-only for this market class.
- S-2: per-order cancel AND slug-scoped cancel-all are both unavailable, or both unconfirmable by any read.
- S-3: a resting order cannot be enumerated (`GET /v1/orders/open` and `GET /v1/order/{id}` both unavailable). If nothing can be read back, nothing may rest.

**STOP (this step only; escalate to the peer-review loop, not the operator):**
- S-4: a firewall pin can only be made green by relaxing it, not by widening it.
- S-5: the venue requires `participateDontInitiate` for resting orders. That forces a maker-fee branch in `fees.py`/`BacktestOrderGuard`, which is out of scope here.

## 4. Simplest direct path

Keep the submit-intent latch exactly as it is: a one-POST-at-a-time serializer (K=1). It now gets **retired when a resting order is confirmed accepted**, so it is never held while the order rests. "Eight concurrent orders" is then just the Nautilus cache holding eight `ACCEPTED` orders. There is **no new intent model, no EXEC-PAR K>1, and no separate durable resting store.**

The adapter gains four things:
- a resting order shape in `submit_chain.py`;
- a per-order cancel POST in `write_transport.py`;
- `_cancel_order`, `_cancel_all_orders` and `_query_order` overrides in `exec/client.py`;
- an AMBIGUOUS rule for resting POSTs: cancel by slug, confirm by read, then fall into the existing IOC no-id resolver.

The strategy detects fills by calling native `Strategy.query_order` on a timer.

Machinery deliberately NOT built, and why:
- **Separate keyed resting store** (RESTING_BID_HUNT §4.4). Nautilus's cache plus the existing venue-id map row already carry the client↔venue binding. Restart safety comes from the existing boot gate plus cancel-on-stop (§6 WP4).
- **Venue modify.** Cancel-then-submit gives the same result and needs no `_modify_order`. That method keeps raising.
- **Private WS order stream.** Never wire-verified. A poll keeps WS subscriptions unchanged, so the 10-per-connection cap is unaffected.
- **Native continuous reconciliation** (`open_check_interval_secs`). See §5, row "Fill detection".
- **post_only / maker-fee branch.** Not required (S-5 decides), and `BacktestOrderGuard._refuse_post_only` (`runtime/backtest_order_guard.py:337`) stays as is.

## 5. Nautilus null-hypothesis check

| Need | Native capability (evidence) | Verdict |
|---|---|---|
| Resting limit order | `TimeInForce.GTC/GTD`, `LimitOrder.expire_time`; the venue enum maps already exist (`exec/reports.py:431-434`: GTC→`TimeInForce.GTC`, GTD→`TimeInForce.GTD`; states `:441-456`, `ORDER_STATE_NEW`→`ACCEPTED`) | Native. The adapter refuses it at `submit_chain.py:331-332` (`unmappable_order_reason`) and `:353` (expire_time); the exit twin is at `:448-473`. **Gap: the adapter shape.** |
| Accept / cancel / fill events | `ExecutionClient.generate_order_accepted / generate_order_canceled / generate_order_expired / generate_order_filled / generate_order_cancel_rejected` (`nautilus_trader/execution/client.pxd:118,157,173,181,135`) | Native. We call these and never re-implement order state. |
| Strategy verbs | `Strategy.submit_order`, `cancel_order` (`trading/strategy.pyx:1089`), `cancel_orders` (`:1134`), `cancel_all_orders` (`:1215`), `query_order` (`:1527`), `modify_order` (`:1011`, unused) | Native. |
| Client cancel hooks | `LiveExecutionClient._cancel_order/_cancel_all_orders/_batch_cancel_orders/_modify_order` (`live/execution_client.py:618-633`) | Native hooks. Breezy's bodies refuse or raise (`exec/client.py:7587-7613`). **Gap: bodies.** |
| Fill detection | `Strategy.query_order` → `LiveExecutionClient._query_order` (`live/execution_client.py:516-532`) → `generate_order_status_report`. Rejected alternative: `LiveExecEngineConfig.open_check_interval_secs` → `_check_orders_consistency` (`live/execution_engine.py:1282-1335`). With `open_check_open_only=True` (default) a filled order just vanishes and is never resolved (`:1318-1328`). With `False`, `_handle_missing_orders_at_venue` (`:1347`) ends in `_resolve_order_not_found_at_venue` "before marking as REJECTED". That is a false terminal on a venue with no client-order-id, which is the same hazard `runtime/node_config.py:981-1010` documents for `inflight_check_interval_ms=0`. | **Use native `query_order`; override `_query_order`** so it emits accepted/filled/canceled for known resting orders. Never enable `open_check_*` or `inflight_check_*`. Never enable `position_check_interval_secs`. |
| Open-order and by-id reads | Already shipped: `exec/endpoints.py` `OPEN_ORDERS_PATH`, `order_by_id_path` (V2-allowlisted). The boot gate already refuses on `startup_open_orders_present` (`exec/client.py:477`, snapshot `:1380-1465`). `generate_order_status_report` already GETs by id (`:5142-5189`). | Native seam plus existing read. No new read path. |
| Cancel-all transport | `write_transport.PolymarketUSWriteTransport.post_cancel_all` (`write_transport.py:160`), zero production call sites; body-less | Exists. **Gap:** optional `{slugs:[…]}` body; no per-order cancel. |
| Caps / exposure | `DailySpendLedger.authorize_order_cost` (`operator_controls.py:504`), `release_booking` (`:601`), `true_up_booking` (`:635`), `register_open_exposure` (`:749`), `settle` (`:844`), `_require_exposure_headroom_locked` (`:727-747`). Permit: `assert_live_order_submission_permitted` (`safety.py:953`), `restore_live_trading_budget` (`:857`, idempotent per venue order id). | Reuse unchanged. **Gap:** the call sites for resting accept and confirmed cancel. |
| Multi-order | K=1 latch `exec_par_constants.py:15`; `SubmitIntentLatch.arm/retire` (`runtime/submit_intent.py:626-680`). The slot is held only from arm to retire. | No model change. **Gap:** one new `RetirementReason` value. |

**Genuinely missing (and nothing else):** the resting body shape; the per-order cancel POST; three client method bodies; one retirement reason; the AMBIGUOUS-resting rule; and the ledger/permit call sites on accept and confirmed-cancel.

## 6. Work packages

Routing: build = Grok, then Codex, then Claude `tdd-guide` (seeded with `nautilus-trader-patterns` and `polymarket-us-integration`). Review = `python-reviewer` + `prediction-market-reviewer` + `security-reviewer` (each WP that touches egress). The coordinator re-runs every gate itself. Every WP briefs the invariants in §1.

Gate, every WP: `PYTHONPATH=<wt>/src scripts/ci/run_tests_no_egress.sh <focused list> --basetemp ~/.cache/breezy-gate/s4-<wp>`. Then the full gate after merge (rm the basetemp after reading EXIT). Then `cd <wt> && lint-imports`, which must print "N kept, 0 broken". The focused list ALWAYS includes:
- `tests/unit/test_execution_egress_firewall_guard.py`
- `tests/unit/test_polymarket_us_readonly_guard.py`
- `tests/unit/test_cage_rule_constants_are_pinned.py`
- `tests/contract/test_us_source_ingest_egress_guard.py`
- `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`
- `tests/unit/test_autonomy_*.py`
- `tests/unit/test_ambig_no_id_firewall_delta.py`
- `tests/unit/test_polymarket_us_exec_client.py`

### WP0 — Venue discovery (read-only; `polymarket-us-discovery` agent; starts now)
- **Inputs:**
  - `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_*`
  - `sdk_snapshot/polymarket_us_0.1.2/resources/orders.py:44-66`
  - `PRIVATE_write_sequence_probe_20260904T170856Z.json`
  - RESTING_BID_HUNT Appendix A
- **Read-only actions:** refresh doc snapshots for create/cancel/cancel-all/open-orders/private-WS and fees; read `feeCoefficient` plus any maker field on the 4-station market objects; read the 09-04 probe artifact for the `synchronousExecution` value it used on the resting create.
- **Must pin, or mark UNVERIFIED:**
  - (a) GTC on `tc-temp-*` (09-04 proved GTC+`participateDontInitiate` at 0.01, but not without post-only);
  - (b) the GTD `goodTillTime` spelling and format, and whether the venue expires it;
  - (c) per-order cancel `POST /v1/order/{id}/cancel` body `{marketSlug}`, with no response body;
  - (d) whether cancel-all honours `{slugs:[…]}`;
  - (e) the create response shape for a resting order under `synchronousExecution=true, maxBlockTime=5` (expected: `id` plus state NEW, no executions);
  - (f) the maker coefficient sign and value on climate markets (skill: −0.0125 rebate; spec: read from the wire);
  - (g) whether resting orders on a `MARKET_STATE_HALTED` market are auto-canceled (`unsolicitedCancelReason`).
- **Budget gate:** read-only GETs only, ≤ 60 requests, ≤ 1 req/3 s. No POST of any kind.
- **Output:** a dated evidence note under `docs/evidence/venue/polymarket_us/` plus skill discovery-log rows (`provisional: true`).
- **STOP check:** S-1/S-2/S-3 on doc evidence alone. Any write-verified fact waits for WP6.
- **Done when:** each of (a)–(g) is PINNED or UNVERIFIED with a source line.

### WP1 — Resting order shape (pure; `submit_chain.py` only)
- **Modify:** `src/breezy/adapters/polymarket_us/exec/submit_chain.py`. No new module, so the E0 exact set (`test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules`) is unchanged.
- **Interfaces:**
  - `unmappable_resting_order_reason(order, instrument) -> str | None` is a THIRD shape. The IOC shape (`:322-363`) and the exit shape (`:448-483`) stay byte-identical.
  - It admits only: LIMIT, BUY, qty == 1, NO leg (`_outcome_token` == NO), price in (0, `RESTING_PRICE_CAP` = 0.80], `time_in_force ∈ {GTC, GTD}`, `post_only False`, no reduce-only, no display_qty, no trigger.
  - GTD requires `expire_time`. GTC requires it absent.
  - `build_resting_order_body(order, instrument) -> dict` emits `RESTING_ORDER_BODY_KEYS` = the IOC key set with `tif` ∈ {GTC, GTD}, plus `goodTillTime` iff GTD. It keeps `synchronousExecution: True`, `maxBlockTime: "5"` unless WP0(e) says otherwise.
  - `encode_order_body` (`:578`) accepts exactly `ORDER_BODY_KEYS` or `RESTING_ORDER_BODY_KEYS`. It stays an equality check, widened by one alternative.
  - `classify_create_order` gains `KIND_ACCEPT_RESTING`: `id` present, state ∈ {`ORDER_STATE_NEW`, `ORDER_STATE_PARTIALLY_FILLED`} with leaves > 0. Anything else follows today's classification.
- **RED tests first** (new `tests/unit/test_polymarket_us_resting_order_shape.py`):
  - `test_ioc_shape_still_refuses_gtc_byte_identically`
  - `test_ioc_shape_still_refuses_post_only`
  - `test_resting_shape_admits_gtc_buy_no_qty1_at_080`
  - `test_resting_shape_refuses_price_above_080`
  - `test_resting_shape_refuses_yes_leg`
  - `test_resting_shape_refuses_sell`
  - `test_resting_shape_refuses_post_only`
  - `test_resting_shape_refuses_gtd_without_expire_time`
  - `test_resting_body_key_set_is_exact`
  - `test_encode_refuses_a_mixed_key_set`
  - `test_classify_new_state_with_id_is_accept_resting`
  - `test_classify_resting_response_without_id_is_ambiguous`
- **Done when:** RED shown failing, then GREEN. The existing `tests/unit/test_polymarket_us_submit_order_chain.py` and `test_no_side_submit_chain_2026_09_14.py` pass unmodified.

### WP2 — Retirement vocabulary (supervisor-first, as AMBIG-LATCH-RESUME C0 did)
- **Modify:** `src/breezy/runtime/submit_intent.py` `RetirementReason` (`:128`) by adding exactly `ACCEPTED_RESTING`, meaning "the venue confirmed a resting order with an id; the slot is released; the order lives in the Nautilus cache and the venue-id map". Mirror the change in `src/breezy/domain/exec_intent.py` if `tests/unit/autonomy/test_exec_intent_parity.py` requires it.
- **Deploy order:** merge, then restart the supervisor (01:00–16:40Z window), and only then may a node write the value. An older decoder must never meet it.
- **RED:** `test_accepted_resting_round_trips_and_releases_the_slot`, `test_reconcile_at_startup_leaves_an_accepted_resting_record_retired`, `test_retirement_reason_set_is_widened_by_exactly_one_row`.
- **Done when:** GREEN, the supervisor is restarted, and the evidence file records the restart time.

### WP3 — Submit path: resting branch, ledger, permit (`exec/client.py`)
- **Modify:** `_submit_order` (`exec/client.py:6880`). It dispatches on `unmappable_order_reason` vs `unmappable_resting_order_reason`. The rest of the deny chain is unchanged and runs first: sender injected, canonical verified, permit, reconcile ran, arm.
- **On `KIND_ACCEPT_RESTING`**, in this order and with no `await` between the first two:
  1. write the venue-id map row (existing writer, `:3655` family);
  2. `register_open_exposure(key=<venue order id>, notional=b, booking=…)`, so the resting notional counts in `_require_exposure_headroom_locked`;
  3. retire the intent `ACCEPTED_RESTING`;
  4. `generate_order_accepted(venue_order_id=…)`.
  The permit's session count was already decremented at submit by `assert_live_order_submission_permitted`, so a resting submit counts.
- **On an immediate full fill:** today's accept-fill path, unchanged.
- **RED** (new `tests/unit/test_polymarket_us_resting_submit.py`):
  - `test_resting_accept_emits_order_accepted_and_retires_accepted_resting`
  - `test_resting_accept_registers_open_exposure_before_retire`
  - `test_resting_submit_decrements_the_permit_order_count`
  - `test_headroom_refusal_denies_a_resting_submit_without_a_post`
  - `test_eight_resting_orders_coexist_with_k1`: arm/POST/retire ×8, all ACCEPTED in cache, `open_slot_count()==0`
  - `test_a_ninth_order_is_refused_by_headroom_not_by_the_latch` (fixture caps only; no real cap value)
  - `test_ioc_submit_path_is_byte_identical_for_ioc_orders`

### WP4 — Cancel path (new egress: `write_transport.py` + `exec/client.py`)
- **Modify** `src/breezy/adapters/polymarket_us/write_transport.py`:
  - add `CANCEL_ORDER_PATH_TEMPLATE = "/v1/order/{id}/cancel"` and `post_cancel_order(api_base_url, *, order_id, headers, body)`. The id is validated with the same forbidden-character rule as `endpoints.order_by_id_path`.
  - `post_cancel_all` gains an optional `body` (`{"slugs":[slug]}`) and stays body-less by default.
  - POST only, signed by the existing `Ed25519WriteRequestSigner`.
- **Modify** `exec/client.py`:
  - `_cancel_order` (`:7587`): refuses (via `generate_order_cancel_rejected`) unless the sender is injected, canonical is verified, the order is a known resting order (venue id bound), and `orders_enabled_requested` was True at boot. **It does NOT require an unexpired permit:** a cancel only reduces risk, and a resting order can outlive the 10 h permit TTL (listing D-1 09:45Z to cancel D 09:00 LST is about 31 h). **It does NOT arm the submit intent:** a cancel creates no exposure, and an AMBIGUOUS create must be able to cancel while its slot is OPEN.
  - Flow: POST cancel, then `generate_order_pending_cancel` semantics, then confirm by `GET /v1/order/{id}` (terminal CANCELED/EXPIRED/FILLED). On CANCELED/EXPIRED with filled 0: `generate_order_canceled`/`_expired`, then `settle(realized 0)` + `release_booking`, then `restore_live_trading_budget(venue_order_id)`. On FILLED: the WP5 fill path.
  - Unconfirmed after `CANCEL_CONFIRM_DEADLINE_S` (PROVISIONAL 30 s, build-side constant): escalate to slug-scoped cancel-all, then latch a named refusal `resting_cancel_unconfirmed`, which reaches the existing alert delivery.
  - `_cancel_all_orders` (`:7609`): slug of `command.instrument_id`, slug-scoped `post_cancel_all`, then confirm by `GET /v1/orders/open` showing nothing on that slug, then per-order events as above.
  - `_batch_cancel_orders` and `_modify_order` keep raising `NotImplementedError` unchanged. The strategy cancels a station by calling `cancel_order` on each of its ≤ 2 orders.
- **Restart rule:** strategy `on_stop` calls `cancel_all_orders(instrument_id)` for every instrument with a resting order. The existing boot gate (`startup_open_orders_present`, `:477`) keeps refusing to arm when a prior process left orders. A **boot sweep** is added: if every open order is on a `tc-temp-*` slug and binds to a venue-id map row of ours, cancel by slug, re-read, and arm only if the account book is empty. Any open order NOT bound to a map row keeps today's refusal and alerts. Unknown orders are never cancelled silently.
- **Pins widened (one reviewed row each, with a non-vacuity proof):**
  - `test_polymarket_us_readonly_guard.py` V2/B4: the per-order cancel literal is admitted in `write_transport.py` only. A copycat module carrying it still trips.
  - `test_execution_egress_firewall_guard.py`: if E3 classifies `post_cancel_order`, the expected-set row in `test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules` gains it, still as an equality.
  - `test_cage_rule_constants_are_pinned.py` RulePin rows for any constant touched.
  - `tests/unit/test_polymarket_us_write_transport.py` `test_it_issues_exactly_one_post_to_the_one_pinned_path` gets a per-method twin.
  - `tests/unit/test_polymarket_us_exec_client.py::test_the_other_four_lifecycle_coroutines_raise_unsupported` is WIDENED: modify and batch still raise; cancel-all is moved to a positive test. It is never deleted.
- **Security: proving cancel cannot fire under the firewall.**
  - New `test_post_cancel_order_is_refused_by_the_os_egress_block` in `tests/unit/test_polymarket_us_write_transport.py`. It builds the REAL `PolymarketUSWriteTransport` over a real `nautilus_pyo3.HttpClient`, calls `post_cancel_order` against `api.polymarket.us`, and asserts the outcome classifies as BLOCKED by the barrier-N4 classifier (`test_execution_egress_firewall_guard.py:408-448`), never as "reached". Twin: `test_post_cancel_all_with_slugs_is_refused_by_the_os_egress_block`.
  - Unit-level: `test_cancel_refuses_without_injected_sender_and_posts_nothing`, `test_cancel_refuses_when_canonical_unverified`, `test_cancel_refuses_an_order_with_no_bound_venue_id`.
- **Other RED** (new `tests/unit/test_polymarket_us_resting_cancel.py`):
  - `test_bare_200_does_not_emit_order_canceled`
  - `test_get_terminal_canceled_emits_canceled_releases_booking_restores_permit_slot`
  - `test_restore_is_idempotent_per_venue_order_id`
  - `test_cancel_that_finds_filled_routes_to_fill_path`
  - `test_unconfirmed_cancel_escalates_to_slug_cancel_all_and_latches`
  - `test_cancel_allowed_with_expired_permit`
  - `test_cancel_never_arms_the_submit_intent`
  - `test_boot_sweep_cancels_only_map_bound_orders`
  - `test_boot_with_unbound_open_order_still_refuses_and_alerts`
  - `test_on_stop_cancels_all_resting_orders`

### WP5 — Fill detection and AMBIGUOUS-resting (`exec/client.py`)
- **`_query_order` override.**
  - For a known resting order: `GET /v1/order/{id}`, then:
    - `cumQuantity` delta > 0 → `generate_order_filled` with `last_px` = venue `avgPx` (inverted to the NO leg via `leg_prices`), `commission` from `commissionNotionalTotalCollected`, and `liquidity_side` MAKER/TAKER from the execution `aggressor` when present, else NO_LIQUIDITY_SIDE plus a WARN;
    - the durable fill record is written FIRST (the existing `record_fill` path), so a restart reconciles;
    - then `true_up_booking`/`settle(realized)`;
    - CANCELED/EXPIRED/REJECTED → as in WP4.
  - It never calls `_send_order_status_report`. That keeps `test_native_query_order_never_reaches_the_send_seam` green **unmodified**.
  - The strategy calls `self.query_order(order)` for each open resting order on a native clock timer (PROVISIONAL 30 s). At 8 orders that is about 0.27 req/s, against the 20 req/s venue limit.
- **AMBIGUOUS for a resting POST (the safety semantics).** A resting POST with no usable response leaves the intent OPEN and the booking held, as today. All other *submits* wait (`OPEN_INTENT_WAIT_REASON`). *Cancels* still run. The IOC argument that "the order's fate is fixed by created + 65 s" (`client.py:1625-1627`) is **false for a resting order**: an unseen GTC can rest forever with no trade, no position and no activity. So today's no-id negative-evidence retirement would be UNSOUND. Rule:
  - **With id** (POST returned an id but no state): `GET /v1/order/{id}` after the existing 120 s floor (`:1617`). NEW → bind it and retire `ACCEPTED_RESTING`. Terminal → today's resolver.
  - **No id:** immediately send a slug-scoped cancel-all for the intent's slug (we hold at most one order per slug by construction). Then confirm `GET /v1/orders/open` shows nothing on the slug. Only then may the existing no-id resolver (300 s floor, `:1625`) retire on negative activity/positions evidence. A fill found there is booked as today.
  - GTD (if WP0(b) pins it) adds a venue-side expiry at the hard-cancel time as defence in depth.
  - The intent fingerprint (`domain/exec_intent.intent_fingerprint`) must carry `tif` so the resolver can tell a resting intent from an IOC one. Check that it already hashes `time_in_force`; if not, this is a reviewed parity-test row.
- **Firewall delta:** new `tests/unit/test_resting_path_firewall_delta.py`, on the precedent of `test_ambig_no_id_firewall_delta.py`. It freezes the pre-S4 literals, pins the exact new awaited callees (`post_cancel_order`, `post_cancel_all`, `_private_read`), and proves each guard non-vacuous by planting.
- **RED** (new `tests/unit/test_polymarket_us_resting_query.py`):
  - `test_query_detects_partial_then_full_fill_with_venue_commission`
  - `test_query_fill_writes_durable_record_before_event`
  - `test_query_never_reaches_send_order_status_report`
  - `test_taker_aggressor_on_resting_fill_is_flagged`
  - `test_no_id_ambiguous_resting_cancels_by_slug_before_negative_retire`
  - `test_no_id_negative_evidence_alone_cannot_retire_a_resting_intent`
  - `test_with_id_ambiguous_resting_new_state_retires_accepted_resting`
  - `test_cancels_proceed_while_an_ambiguous_intent_is_open`
  - `test_restart_reconciles_a_fill_that_happened_while_down`: map row → GET → durable record → positions agree, no `record_venue_disagreement`.

### WP6 — Integration, re-pin, positive control
- **Integration:** `tests/integration/test_resting_order_lifecycle.py` uses a test-only Strategy and a fake sender/reader. It runs submit ×8 → query → one fill → cancel-replace one → cancel-all-for-station → stop. Each step asserts the native events, the ledger totals and the permit count.
- **Re-pin** (after ALL code WPs, once):
  - update `_EXEC_CLIENT_SHA256` in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py`, with a comment `# re-pinned <date>: MAKER S4 resting path (WP3-WP5), reviewer-approved (<names>)`;
  - update the line-number citations for `exec/client.py` in `tests/contract/test_us_source_ingest_egress_guard.py` `BANNED_MODULES` (`:61` class line, `:76` `post_order` call line). These are citation rows, not relaxations.
  - `test_autonomy_envelope.py` reads the pin by AST and needs no edit.
- **Positive control (venue):** re-run the 09-04 sequence through the ADAPTER: rest 1 BUY NO at 0.01 far from the touch (GTC; then GTD if pinned), enumerate, per-order cancel, confirm by GET; then rest again, slug cancel-all, confirm. This is automated (bot's job, never a UI step). It runs only through the existing write-signing-probe authorization route, within the existing caps. This plan sets no enablement and assigns no cap. If that route is unavailable, record `POSITIVE_CONTROL: PENDING (<reason>)`. S5 shadow does not need it; live arming later does.
- **Done when:** full gate EXIT=0, lint-imports clean, three reviewers APPROVE, and the evidence file is written.

## 7. Data and tooling dependencies

| Item | Path | State |
|---|---|---|
| Venue order docs | `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_{overview,create-order}_2026-08-25.md` | On disk. Cancel endpoints are at `overview:47-60`; GTC/GTD at `create-order:164-174` |
| SDK order types | `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py:70-180` | On disk |
| 09-04 resting probe | `docs/evidence/venue/polymarket_us/PRIVATE_write_sequence_probe_20260904T170856Z.json`; builder `scripts/venue/polymarket_us_write_signing_probe.py` | On disk; proved cancel-ALL only |
| Private WS order stream | not snapshotted | UNVERIFIED, not used |
| Per-order cancel behaviour | SDK + docs only | UNVERIFIED until WP6 |
| GTD `goodTillTime` honoured | docs only | UNVERIFIED |
| GTC without `participateDontInitiate` on weather | none | UNVERIFIED (WP0(a), WP6) |
| Maker coefficient on climate markets | skill says −0.0125; θ_taker drifted to 0.0695 | UNVERIFIED; read from the wire per fill |

## 8. Risks and guards

| Risk | Invariant at stake | WP | Guard |
|---|---|---|---|
| A resting order no process knows about (crash, permit lapse) | caps, no unknown exposure | WP4/5 | Cancel on stop. Boot gate refuses on open orders. Boot sweep cancels only map-bound orders. GTD venue expiry if pinned. |
| No-id AMBIGUOUS retired on negative evidence while the order still rests | AMBIGUOUS safety | WP5 | Slug cancel-all plus read confirmation BEFORE the no-id resolver may retire; RED `test_no_id_negative_evidence_alone_cannot_retire_a_resting_intent` |
| Cancel path fires in tests | NO-SEND firewall | WP4 | OS-block tests on the real transport; the firewall-delta test; E3/V2 rows widened, never relaxed |
| Native reconciliation marks a live order REJECTED | correctness | WP5 | `open_check_*`/`inflight_check_*` stay off; fills come only via `query_order` |
| Non-post-only bid crosses the spread and fills as taker | economics (spec assumes maker) | WP5 + strategy | Strategy pre-check `bid < best NO ask`. `aggressor=true` is flagged and counted separately, never silently re-priced. |
| Cancel-replace churn exhausts the session order count | permit | WP4 | `restore_live_trading_budget` on a confirmed zero-fill cancel (idempotent, clamped) |
| Ledger counts a reservation twice, or never releases it | operator caps | WP3/4 | `register_open_exposure` once per venue id; `settle` exactly once; RED tests on totals |
| New retirement reason meets an old supervisor decoder | supervisor safety | WP2 | Supervisor-first deploy and restart before any node write |
| Byte-pin or citation updated without review | NO-SEND | WP6 | Re-pin comment names the reviewers; `test_autonomy_envelope` enforces a single pin home |
| A `fees.py`/`BacktestOrderGuard` change creeps in | taker fee model / F2 barrier | all | Out of scope. S-5 STOP if post-only is required. |

## 9. Effort and evidence

| WP | Agent-hours |
|---|---|
| WP0 | 2 |
| WP1 | 3 |
| WP2 | 2 (+ supervisor restart) |
| WP3 | 5 |
| WP4 | 7 |
| WP5 | 7 |
| WP6 | 5 |
| Reviews and gates (≈ 25 min per full gate × 6) | 4 |
| **Total** | **≈ 35 agent-hours, about 3 working days serial** |

WP1 and WP2 run in parallel. WP3–WP5 run serially, because they all edit `exec/client.py`.

Evidence artifact: `docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_path_evidence.md`.

## 10. Open questions for peer review (max 5)

1. **GTC (spec) vs GTD.** GTD with `goodTillTime` = the D 09:00 LST hard cancel gives a venue-side backstop that does not depend on our cancel path or the permit TTL. Should the spec move to GTD if WP0/WP6 pin it?
2. **Sync vs async create.** Is `synchronousExecution=true, maxBlockTime=5` acceptable for resting orders? It reuses today's classifier. The venue recommends async for resting orders, and async would need a with-id PENDING_NEW branch.
3. **Boot sweep.** Is auto-cancelling map-bound orders at boot correct? The alternative is adopting them into the new process's cache, which keeps queue position but needs native external-order adoption plus strategy re-binding.
4. **Fill-detection cadence.** Is a 30 s `query_order` poll an acceptable latency for the §3 kill-switch path, given that cancels are confirmed by read anyway?
5. **Non-post-only crossing.** Is a strategy-side `bid < best NO ask` pre-check enough, or must the exec shape also refuse a resting order priced at or through the cached NO ask (a cache read inside `_submit_order`)?
