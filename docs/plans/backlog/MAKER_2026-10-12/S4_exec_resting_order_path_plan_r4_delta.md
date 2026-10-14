# S4 r4 delta: exec resting-order path, re-plan against the WP0 venue discovery

| Field | Value |
|---|---|
| ID / Revision | S4 / **DRAFT r4 delta rev 3**, ON TOP OF `S4_exec_resting_order_path_plan_r3.md` (r3 stands wherever silent). Supersedes rev 2 |
| Date | 2026-10-13 |
| Trigger | `docs/evidence/venue/polymarket_us/MAKER_S4_WP0_VENUE_DISCOVERY_2026-10-13.md` + reviews `reviews/S4-r4-{security,architect}-review.md` (round 1) and `...-review-round2.md` (both REQUEST_CHANGES, fully dispositioned in §12) |
| Gate | S2 NOT-KILLED and S3 REACHABLE (r3 §3). Nothing here is built. Exception: WP1 step 0 (tests only) may be built now. S5 family stays SHADOW |
| Provisional | WP0 findings stay `provisional: true` until `python-reviewer` + `prediction-market-reviewer` sign off; (a)(e)(g), S-2, S-6 stay WP6-gated |

**Invariants (binding on every WP and brief):** Nautilus Trader immutable (extend only via `LiveExecutionClient` overrides and native `Strategy` calls). `allow_short` stays `False`; BUY only. Never weaken or delete a safety, settlement, contract or NO-SEND firewall test; exact sets widen by ONE reviewed row per commit with a non-vacuity plant (L-12, L-46); only-relaxing-goes-green = S-4 STOP. Never touch live enablement or `BREEZY_ORDERS_ENABLED`; assign no operator-reserved value (max daily budget, max per position); every constant below is a provisional RulePin, not an operator control. S4 builds the exec path; nothing arms it; the family stays SHADOW. No `git stash`; `PYTHONPATH=<wt>/src`; never uv/pip; `lint-imports` "N kept, 0 broken" after every slice; briefs name the whole-tree guards (firewall, import gates, fee-theta pin, citation map, mypy ratchet), not only focused tests; `--basetemp` under `~/.cache`.

## 0. Premise ledger (re-read this revision; line numbers from HEAD on `feat/data-capture-and-risk`)

| Claim | Status |
|---|---|
| `parse_open_orders`: missing `eof` = complete, `eof` not True refuses, other envelope keys recorded in `unknown_keys` (`reports.py:1640-1643`, `:1790-1797`); `ORDER_STATE_TO_ORDER_STATUS` NEW->ACCEPTED, `parse_order_status_report` (`reports.py:441`, `:1124`) | VERIFIED (rev 2) |
| `_submit_order`: `_post_in_flight_intent_ids` add `client.py:7180`; `finally` removal right after `post_order` `:7207-7208`; AMBIGUOUS = `_refuse` + `mark_ambiguous` + `_note_ambiguous_open` (`:7516-7568`) | VERIFIED |
| `_note_ambiguous_open` (`:6707`) has 3 callers: pre-POST no-id context `:7141` (`venue_order_id=NO_VENUE_ORDER_ID`), settle-failure upgrade `:7358`, post-`_refuse` with-id write `:7568`; NO `resting` parameter; every write OVERWRITES the key | VERIFIED |
| Context decode uses trailing-optional `payload.get(...)` outside the strict `try` (`:1248-1286`); an absent key takes its default. The L-47 schema-version premise of rev 2 is STRUCK (L-47 concerns evidence citation) | VERIFIED |
| `_adopt_no_id_venue_order` = `dataclasses.replace(context, venue_order_id=...)` then `_store_set` (`:4691`); ADOPT branch `:4654`; so a `resting` flag written in the PRE-POST context survives adoption | VERIFIED |
| Only the no-id resolver skips in-flight intents (`:4299`); the with-id resolver does NOT (`:2869-3300`) | VERIFIED; skip becomes a definite step (WP3) |
| `_resolve_accept_fill` A3 block clears the global `AMBIGUOUS_REASON` refusal inline (`:4046-4065`); the no-id path has the same (`:4823-4851`) | VERIFIED |
| `calculate_commission(self, instrument, last_qty, last_px, liquidity_side)` has NO order id parameter and `_refuse`s on MAKER (`:6559-6606`); `fees.py:275,449` raise on a sideless fill; resolver fill path hardcodes TAKER, `Money(0)` commission, `fee_reconciled=False` (`:4037-4038`, `:3879-3880`) | VERIFIED (arch H-5); carve-out is therefore keyed on the instrument's slug, not an id (§4) |
| `DurableFillRecord` ALREADY carries `venue_fee_raw: str | None` (`:968`, JSON `venueFeeRaw`, optional-on-read `:836`, written from `FillGeneration.commission_raw` `:7295`; readers `fee_source_for` `:894`, `:5533`, `:6057`, mirror `trial_day_latch.py:529`) | VERIFIED: the "new `commission_raw`" of the ruling IS this field (no second raw field, DRY); only `commission_sign` is new (trailing-optional) |
| `_cancel_order` refuses with `generate_order_cancel_rejected` (`:7587`); `_cancel_all_orders` raises `NotImplementedError` (`:7609`); `_query_order` is NOT defined in the client and is declared in `EXEC_DECLARED_UNIMPLEMENTED_COROUTINES = {"_query_order"}` (`test_execution_egress_firewall_guard.py:2111`, disjointness assertion `:2877-2898`) | VERIFIED |
| `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` is the union expression `{__init__} | ORDER_LIFECYCLE_COROUTINES | EXEC_RESOLVER_COROUTINES` (`:4374-4376`); `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD = {__init__, _submit_order}` (`:4385`); banned-word loop `:3374-3381` | VERIFIED |
| `order_by_id_path` (`endpoints.py:123-140`; `submit_chain.order_by_id_path` delegates) refuses `/ ? # \` and whitespace; `V2_ORDER_READ_PATH_ALLOWLIST` is `test_polymarket_us_readonly_guard.py:222` = `{endpoints.py: {"/v1/orders/open", "/v1/order/"}}` (the `:2512` cited by the reviewer is not that line) | VERIFIED |
| `write_transport.post_cancel_all(api_base_url, *, headers)` is BODILESS and account-wide, no `src/` caller (`write_transport.py:160-175`); signature = `timestamp + METHOD + path`, body NOT signed (`signing.py:128-134`); legacy probe `_signed_post_cancel_all` sends `body={}` (`:325-336`, `:459`, `:655`) | VERIFIED |
| `settle(realized_usd)` = `cumulative_qty * avgPx` (`:3860`, `:3935`): the budget ledger is commission-free; `authorize_order_cost`, `operator_controls.py`, `safety.py` have no commission reader | VERIFIED (sec round 2) |
| `_usd_commission` cent-quantises (`reports.py:1048`); `fees.taker_fee_at_fill(quantity, price, ts_event_ns, fee_coefficient_at_fill)` (`fees.py:560`) | VERIFIED |
| Commission readers outside `reports.py` (my grep over `src/`): `.cumulative_fee`: `prereg_admission.py:569,655`, `labeling/legacy_crh_scorer.py:120`, `labeling/reconcile.py:682,684,741`, `labeling/fq_scorer.py:338,408,424`, `labeling/accounting.py:622,691`, `runtime/exec_par_settled_pnl.py:175`, `exec_par_settled_pnl_driver.py:219`, `strategy/current_rung_hold/trial_day_latch.py:1828`, `continuous_helpers.py:152`, `exec/client.py:5536`. `event.commission`: `exit_wiring.py:231`, `continuous_strategy.py:2933`, `runtime/exec_par_counter_ingest.py:454`, `strategy/harness_probe.py:245` (log). `Position.realized_pnl`: `settlement/exit_guard.py:90-110` (REQUIRES it; Nautilus seeds it from `-commission`), `trial_scorer.py:10-14` (doc) | VERIFIED for `src/`; `scripts/` readers UNVERIFIED, enumerated at WP5 step 0 |
| `manage_gtd_expiry` GTD timer: `trading/strategy.pyx:393,888,998` (`:888` fires only when `time_in_force == GTD`); `_expire_gtd_order` -> `cancel_order` at `:1734-1748` | `:393/888/998` VERIFIED; `:1734-1748` architect-verified, re-check WP4 |
| `cancel_order` runs the `_cancel_order` coroutine in its own task (as `submit_order` does, `live/execution_client.py:277-282`) | UNVERIFIED; WP4 build check (a loop inside `_cancel_resting_order` depends on it) |
| `write_transport` importing `exec.endpoints` creates no import cycle / no import-linter break | UNVERIFIED; `lint-imports` + import smoke at WP4. Fallback: transport owns its own prefix constant and T3 asserts string equality with `endpoints.cancel_order_path` |
| Whether `fee_reconciled=False` on a poll-path record trips the I1b "fee not reconciled" refusal (`client.py:~701`) | UNVERIFIED; WP5 step 0 check. If it does, the poll path latches NEW rests only (never a global refusal) |
| Observed venue order-id charset | UNVERIFIED; the id regex (§5) is frozen from WP0 evidence ids at build, widen only by a reviewed evidence-cited row |
| `store` key-enumeration API for ledger membership (`resting:` rows + `resting=True` contexts) | UNVERIFIED name; WP4 build check; `_store_get` alone cannot enumerate |

## 1. r3 assumption -> WP0 finding -> change

| # | r3 assumption | WP0 finding | Change |
|---|---|---|---|
| 1 | WP5 books the venue fee with its venue sign; `_assert_taker_fill` refuses maker Executions | bps fields read `"0"` on own orders; own maker sign UNOBSERVED | Fee ONLY from realised `Order.commissionNotionalTotalCollected`; raw in `venue_fee_raw`; the RECOGNISED value feeds `cumulative_fee` and native `OrderFilled.commission` (§4); bps = drift pin |
| 2 | `KIND_ACCEPT_RESTING` from the create response | Rest is an ASYNC create (9-key body); sync response UNVERIFIED | 200+id never accepts; accept = bounded GET `ACCEPTED`, `filled_qty == 0`, echo match (§2 WP3). `classify_create_order_outcome` untouched |
| 3 | Slug cancel-all body "each tc-temp-*" | Empty/missing `slugs` = ACCOUNT-WIDE | Allowlist `parse_weather_slug(slug) is not None`, four layers, disabled until WP6 (§5) |
| 4 | Sweep certifies by `?slugs=` re-read | Filter honoured UNVERIFIED | Unfiltered `/v1/orders/open` + client-side filter (§5) |
| 5 | Cancel confirm 30 s then cancel-all + latch | `HALTED` blocks cancels (inferred) | Refused/unconfirmed cancel = RETRY-WHEN-OPEN, own-coroutine loop, early alert, late latch (§6) |
| 6 | P11 widens `_ORDER_DRIFT_ALLOWED_KEYS` | `unsolicitedCancelReason` is an Execution field | P11 NO CHANGE; CHAR pin on the 4 keys |
| 7 | Order keys SDK-20 | Wire Order has 24 keys | Additive `WIRE_ORDER_KEYS`; the 20-key snapshot-equality row (`test_polymarket_us_exec_snapshot_drift.py:138`) UNEDITED |
| 9 | Discovery tolerates non-daily slugs | 71 listed = 60 daily + 11 non-daily; `provider.py:255-262` can raise | Characterise first, code only if red (§7) |
| 10 | Cancel body implicit | Body REQUIRED | Per-order cancel `POST /v1/order/{id}/cancel` body exactly `{"marketSlug": <bound slug>}` (§5) |
| 11 | `goodTillTime` format unspecified | request string, response RFC3339 ns | Pure `format_good_till_time` floors to whole seconds; a GET showing non-GTD tif is never bound (S-6) |

## 2. Per-WP amended steps (only what changes)

### WP0: DONE provisional. Add the two reviewer sign-offs. Every WP6 brief: "extractors emit key names/booleans/signs only; never `repr` a nested object; no order rows in tool output".

### WP1 (r3 l.96-103)
- **Step 0 (tests only, buildable now):** discovery characterisation (§7).
- Shape: add `parse_weather_slug(slug) is not None`. `RESTING_ORDER_BODY_KEYS` = `ORDER_BODY_KEYS` minus `{synchronousExecution, maxBlockTime}` plus `{goodTillTime}` (9 keys); `encode_order_body` (`submit_chain.py:578`) accepts exactly one of two sets. `format_good_till_time(expire_ns) -> str` pure, floored, never later than `expire_time`.
- Confirm verdict = native: `report.order_status is OrderStatus.ACCEPTED and report.filled_qty == 0` plus pure `resting_echo_matches(report, wire_echo) -> bool` in `submit_chain.py` (slug, side, price, quantity, tif GTD, goodTillTime within 1 s). The NO leg compares through the leg mapping (`leg_of` / `position_leg`), never raw `side` (the venue shows a NO buy as SELL / BUY_SHORT). Anything else is HOLD. No new state enum, no `classify_resting_order_state`.
- `reports.py`: `WIRE_ORDER_KEYS`; `resting_commission_total(order) -> Decimal` (signed, `_require`d, never `abs`); `assert_commission_bps_inert(order) -> BpsDrift | None`; `recognised_commission(raw, *, sign_verified) -> Decimal` = `raw if sign_verified else max(raw, 0)`.
- The `InstrumentStatus` halt annotation is DROPPED (YAGNI); nothing reads market state.

### WP2: UNCHANGED (two `RetirementReason` rows, r3 P12; a venue-initiated terminal is an order event, not an intent event).

### WP3 (inline confirm acts on NEW ONLY)
1. Branch fires only when `classify_create_order_outcome` yields AMBIGUOUS WITH a `venue_order_id` for a resting-shaped order (4xx REJECT, ZERO_FILL, taker `ACCEPT_FILL`, no-id AMBIGUOUS never enter). It sits before `_refuse`/`mark_ambiguous`.
2. **Pre-POST context (`:7141`) carries `resting=True`** for a resting-shaped order, so a crash between POST and the with-id write is adopted by the no-id ADOPT path (`:4654`, `dataclasses.replace` keeps the flag) and then bound by the with-id resolver.
3. `AmbiguousResolverContext` gains `resting: bool = False`, trailing-optional `.get` decode (absent -> False); `_note_ambiguous_open` gains `resting: bool = False` and EVERY call for a resting order threads it (pre-POST, the with-id write BEFORE the confirm await, and the post-`_refuse` call at `:7568`); crash test asserts `context.resting is True` AFTER the HOLD branch.
4. **In-flight set:** the intent id is added before POST and removed in ONE `finally` wrapping POST + confirm (not held forever: a held id would starve K=1, L-48). Durability across the window comes from the with-id context, not the set. **The with-id resolver gains the in-flight skip as a DEFINITE step** (pure `in` test, no call, same shape as `:4299`); RED `test_with_id_resolver_skips_in_flight_intent`.
5. `await self._confirm_resting_order(venue_order_id, wire_echo)` = GET `/v1/order/{id}` via `_private_read` every `RESTING_CONFIRM_POLL_S` (0.5, quota `QUOTA_KEY_PORTFOLIO`) up to `RESTING_CONFIRM_DEADLINE_S` (5): GET-only helper returning `NEW_VERIFIED | HOLD`. `NEW_VERIFIED` -> `_bind_resting_order`; anything else (PENDING at deadline, FILLED/PARTIAL, terminal zero, echo mismatch, non-GTD tif, unreadable, GET error, cancellation) -> fall through to `_refuse` + `mark_ambiguous` + `_note_ambiguous_open(resting=True)`; the with-id resolver decides. No inline fill booking, no inline terminal-zero retire.
6. **The binder clears the global refusal.** `_bind_resting_order` (store `resting:` row, retire `ACCEPTED_RESTING`, `generate_order_accepted`, release K=1) ends with the same inline `AMBIGUOUS_REASON` clear as the A3 block (`:4046-4065`; last statement, scoped by slug at K>1). It has exactly two callers (`_submit_order`, the resolver branch). RED `test_resolver_bind_clears_ambiguous_refusal`. K=1 slot and budget are NOT released at the confirm deadline, only on a terminal/bound read.
7. Resolver branch: a with-id context with `resting=True`, GET `ACCEPTED`, `filled_qty == 0` and a matching echo calls the same binder (the resolver applies no age floor to NEW, `:3385-3395`). Terminal-zero and fills follow the existing resolver paths UNCHANGED.
8. **Cancel during HOLD (arch M-1):** `_cancel_order` resolves the venue id from the bound `resting:` row OR the with-id context (`resting=True`) and cancels by id through `_cancel_resting_order` (the same cancel state machine, §6). GTD expiry (`strategy.pyx:888` -> `_expire_gtd_order` -> `cancel_order`) lands in the same `_cancel_order`, so it is covered by the same row. Context lookup by client order id: UNVERIFIED that the context carries it; WP4 check, else use the venue-id -> client-id map. An unbound SUBMITTED order with no id yet: `generate_order_cancel_rejected` and let the venue `goodTillTime` expire it.

### WP4
- **4a** transport verbs + path pins (§5). **4c** cancel state machine (§6). **4e** boot sweep (§5). **4b, 4d, 4f** as r3; `_cancel_all_orders` loops the ledger and calls `_cancel_resting_order` DIRECTLY (not via `_cancel_order`, so no extra P1 callee).
- Helper names avoid read/send/post/request so the `:3374-3381` ban stays UNEDITED: `_confirm_resting_order`, `_confirm_cancel_terminal` (GET-only post-cancel read), `_cancel_resting_order`, `_cancel_slug_orders`, `_bind_resting_order`, `_sweep_resting_orders_at_boot`.
- **RETRY-WHEN-OPEN driver (arch M-2): the `_cancel_resting_order` coroutine itself.** It loops `POST cancel -> _confirm_cancel_terminal` with `asyncio.sleep(backoff)` until a terminal read; no `create_task`, no timer. Re-entry after a crash = the boot sweep (N4). Rejected drivers: the resolver tick (would put a send callee in a NO-SEND set, E0-NOSEND-RESOLVER) and a strategy-side timer (couples S4 to S5 state). The `_query_order` poll NEVER sends, so every GET-only set stays GET-only. Pin rows: N2 (send + `asyncio.sleep` + clock) and N1 (the GET helpers).
- OS-block proof: `test_post_cancel_all_with_empty_slugs_never_reaches_the_transport`.

### WP5 (r3 l.145-166)
- Poll (`_query_order` override, restored r3 P3) is the ONLY place a resting fill is booked raw. At the FILLED observation (qty 1): `resting_commission_total(order)` = raw; `venue_fee_raw` = exact string, `commission_sign in {+,0,-}` (new, trailing-optional); `cumulative_fee = recognised_commission(raw)`; native `OrderFilled.commission = Money(recognised)`. Never `parse_fill_report`/`_assert_taker_fill`. `liquidity_side`: MAKER only for a fill first observed after a recorded bind, else `NO_LIQUIDITY_SIDE`; build check that Nautilus accepts it and no Breezy reader branches on TAKER.
- **One rule for resolver paths (arch H-5a): resolver fill paths are UNCHANGED for S4.** A HOLD-resolved resting fill goes through `_resolve_accept_fill` as TAKER, `Money(0)`, `fee_reconciled=False` (as r3 l.152); no raw booking there. A bound-then-filled order books raw via the poll.
- **Reconciliation carve-out (arch H-5b):** `calculate_commission` has no order id (§0), so the carve-out is keyed on the instrument's base slug: for a MAKER fill, skip the `_refuse` only when the durable ledger holds a `resting:` row or `resting=True` context for that slug (key enumeration); price still at taker. Unbound MAKER still refuses (existing `test_calculate_commission_prices_a_maker_fill_at_taker_and_refuses` stays UNEDITED, plus a new CHAR). The method must still never raise.
- Envelope: `abs(commission) <= taker_fee_at_fill(1, price, ts_event_ns, None)` (`None` = unpinned: skip with WARN). Outside: STILL BOOK, latch `resting_commission_out_of_envelope` (NEW rests only), CRITICAL alert (L-48). Every poll GET runs `assert_commission_bps_inert`. No-id attribution unchanged.

### WP6
- Same probe route/caps. (i) key-names-only record of the async rest response and first GET; (ii) first own passive fill: record the commission SIGN, flip `MAKER_COMMISSION_SIGN_VERIFIED` in a reviewed commit; (iii) GTD honoured (S-6); (iv) per-order cancel `{marketSlug}` and slug-scoped cancel-all on two slugs (S-2) with ONLY own probe orders resting; flips `SLUG_SCOPED_CANCEL_ALL_VERIFIED` in a reviewed commit citing the artifact. WP6 must NOT import or reuse the legacy probe's `_signed_post_cancel_all`; NEVER send an empty-slug cancel-all, even as a negative control.

## 3. Complete pin-row list. Each row = its OWN commit + a plant that must trip; widen only, never `issubset`
(WIDEN = exact set gains one named entry; NEW = new exact set/scan; TIGHTEN = narrower assertion, nothing deleted; CHAR = unedited, mutation evidence.)

| Row | Set / site | Kind: delta | Test file |
|---|---|---|---|
| FW-1 | `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` (`:4374-4376`), a NAMED term `\| frozenset({...})` appended to the union expression | WIDEN: +`_cancel_resting_order` | `test_execution_egress_firewall_guard.py` |
| FW-2 | same term | WIDEN: +`_cancel_slug_orders` | same |
| FW-3 | `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) | WIDEN: +`_cancel_resting_order` (r3 P5 superseded; `_cancel_order` calls the helper, never the sender) | same |
| FW-4 | same | WIDEN: +`_cancel_slug_orders` | same |
| P1a | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`:1952`) | WIDEN: +`self._confirm_resting_order` (plant: only `_submit_order`) | same |
| P1b | same | WIDEN: +`self._cancel_resting_order`. Plant restated: referenced only from `_cancel_order`, `_cancel_all_orders`, `_sweep_resting_orders_at_boot`; any other coroutine fails | same |
| P1c | same | WIDEN: +`self._bind_resting_order` (callers `_submit_order` only here; resolver side is P6b) | same |
| P1d | same | WIDEN (pure, one commit each): +`submit_chain.format_good_till_time`, +`submit_chain.build_resting_order_body`, +`submit_chain.unmappable_resting_order_reason`, +`self.generate_order_expired`, +`self.generate_order_canceled`, +`self.generate_order_cancel_rejected` (r3 P1 content, re-confirmed against r3 l.173) | same |
| P2 | `test_no_shipped_exec_order_coroutine_awaits_anything` (`:2977`) + `EXEC_CANCEL_QUERY_AWAITED_CALLEES` | r3 row STANDS; the P2 commit names the new awaits (`_cancel_resting_order`, `_confirm_cancel_terminal`, `self._private_read`) | same |
| P3 | `EXEC_DECLARED_UNIMPLEMENTED_COROUTINES` (`:2111`) + NEW exact `EXEC_QUERY_PERMITTED_CALLEES` | r3 P3 RESTORED (only `_read_market_state` is dropped): set -> `frozenset()` (disjointness `:2877-2898` forces it), `_query_order` scanned GET-only: `self._private_read`, `order_by_id_path`, `parse_order_status_report`, `resting_commission_total`, `recognised_commission`, `assert_commission_bps_inert`, `resting_echo_matches`, store, log; no `post_*`, no `_order_sender` | same |
| P4a-e | `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) | WIDEN (five commits): +`_confirm_resting_order`, +`_confirm_cancel_terminal`, +`_cancel_resting_order`, +`_cancel_slug_orders`, +`_sweep_resting_orders_at_boot` (r3 P4's `_confirm_terminal_by_read` is renamed: it contains the banned word "read") | same |
| N1 | NEW exact `EXEC_RESTING_CONFIRM_PERMITTED_CALLEES` (bodies of `_confirm_resting_order`, `_confirm_cancel_terminal`) | `self._private_read`, `order_by_id_path`, `parse_order_status_report`, `resting_echo_matches`, `asyncio.sleep`, `UUID4`, `self._clock.timestamp_ns`, log; no `self._order_sender.*` | `test_resting_path_firewall_delta.py` |
| N2 | NEW exact `EXEC_CANCEL_SEND_PERMITTED_CALLEES` (body of `_cancel_resting_order`) | exactly one send callee `self._order_sender.post_cancel_order`, plus `self._write_signer.sign_headers`, `cancel_order_path`, `asyncio.sleep`, `self._clock.timestamp_ns`, `self._confirm_cancel_terminal`, store, log; banned-word loop for THIS set allows that one send name only | same |
| N3 | NEW exact `EXEC_SLUG_CANCEL_PERMITTED_CALLEES` (body of `_cancel_slug_orders`) | `self._order_sender.post_cancel_all`, `self._write_signer.sign_headers`, `parse_weather_slug`, store key enumeration, log. Plants: a second `post_cancel_all` reference in `_cancel_order`/`_cancel_resting_order`/sweep fails; `_submit_order` referencing `_cancel_slug_orders` fails | same |
| N4 | NEW `EXEC_BOOT_SWEEP_PERMITTED_CALLEES` (r3 P24 superseded) | reads, `self._cancel_resting_order`, `self._cancel_slug_orders`, store, log; no `post_order` | same |
| N5 | NEW tree scan (r3 P26) | SUBSTRING match `post_cancel_all`, `CANCEL_ALL_PATH`, `/v1/orders/open/cancel` (catches `_signed_post_cancel_all`, `_CANCEL_ALL_PATH`) in `src/` AND `scripts/`; allowed only in `write_transport.py` + the one N3 body; exempt ONLY the legacy probe, pinned by file sha256 ONE constant imported by BOTH N5 and the B4 exemption list; plants: a new script importing the probe helper; a new script naming the path | same |
| P6a | `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2155`) + `EXEC_RESOLVER_COROUTINES` (`:2128`) | r3 P6 STANDS (+`self._bind_resting_order`, +`self.generate_order_accepted`; coroutines +`_bind_resting_order`) | `test_execution_egress_firewall_guard.py` |
| P6b | same | WIDEN: +`submit_chain.resting_echo_matches` (resolver branch). The in-flight skip is a pure `in`, no row | same |
| P7 | V2 `V2_ORDER_READ_PATH_ALLOWLIST` (`test_polymarket_us_readonly_guard.py:222`) | WIDEN, own commit + plant (r3 P7 STANDS, SITE CHANGED: the literal `"/v1/order/{order_id}/cancel"` lives in `endpoints.py` built on `order_by_id_path`, so the entry is `{"/v1/orders/open","/v1/order/","/v1/order/{order_id}/cancel"}` and the "exactly two literals" test becomes "exactly three"; never spliced). Build check: read `test_v2_allowlist_every_write_path_still_trips_even_inside_endpoints`; if it enumerates the cancel path, it keeps tripping for every OTHER write path and this one literal is the single named exception; fallback if that cannot be done without weakening it: `order_by_id_path(id) + "/cancel"` (no V2 literal, no widening) | `test_polymarket_us_readonly_guard.py` |
| T1 | `test_the_write_callable_has_no_method_query_or_body_parameter` (`test_polymarket_us_write_transport.py:322`) | CHAR unedited + NEW companion: params of `post_cancel_all` == {self, api_base_url, headers, slugs}; of `post_cancel_order` == {self, api_base_url, headers, order_id, market_slug}; no `method/query/params/timeout_secs`, no caller bytes | same file |
| T2 | `test_it_issues_exactly_one_post_to_the_one_pinned_path` (`:339`; asserts `== {"url","headers","keys"}` at `:355`, calls bodiless at `:348`) | **WIDEN of an exact set + FORCED edit of a safety test** (r3 P17 superseded): recorded keys == {url, headers, body, keys} for the cancel verbs, per-verb path equality kept; own commit + plant (a bodiless call must fail) | same file |
| T3 | NEW `CANCEL_ORDER_PATH_TEMPLATE == "/v1/order/{order_id}/cancel"`; `cancel_order_path(order_id)` in `endpoints.py` on `order_by_id_path`; client signer and transport URL are equal strings | NEW: id allowlist regex fail-closed `^[A-Za-z0-9_-]{1,64}$` in BOTH builder and transport (frozen from WP0 ids; widen only by an evidence-cited row, never a denylist); `post_cancel_order` validates `market_slug` with `parse_weather_slug`, body via `json.dumps`; b3 exposure pins re-run UNEDITED | same file |
| CC-1 | `calculate_commission` MAKER refusal (`:6600`) | carve-out per §2 WP5: RED for a bound slug, CHAR that unbound MAKER still refuses | `test_polymarket_us_exec_client.py` |
| P9, P10, P12, P14, P15, P18-P22 | r3 rows | STAND as r3 §6.7 (P9 test moves, never deleted; P10 stale premise fixed; P12 two `RetirementReason`; P14 own-order exclusion; P15 `_retire` carve-out; P18 `_EXEC_CLIENT_SHA256` re-pin once at WP6; P19/P20/P21/P22 as r3). P21's two `_store_set` sites stay exactly as r3 | r3 files |
| P13 | `encode_order_body` equality | WIDEN: `RESTING_ORDER_BODY_KEYS` 9-key set | `test_polymarket_us_resting_order_shape.py` |
| P16 | `test_cage_rule_constants_are_pinned.py` | + RulePins: `RESTING_CONFIRM_DEADLINE_S` 5, `RESTING_CONFIRM_POLL_S` 0.5, `MAKER_COMMISSION_SIGN_VERIFIED` False, `SLUG_SCOPED_CANCEL_ALL_VERIFIED` False, `OBSERVED_COMMISSION_BPS` "0", `CANCEL_RETRY_BACKOFF_S` (5,10,20,40,60 cap), `RETRY_ALERT_AGE_S` 600, `RETRY_REALERT_S` 1800, `RETRY_LATCH_GRACE_S` 120, `RETRY_LATCH_FLOOR_S` 60 (each a constant; the per-order bound is a computed pure function, not a pin) | same |
| P5, P17, P24 | r3 | SUPERSEDED by FW-3/FW-4, T2, N4 (listed so none is both stale and live) | -- |
| P11 | `_ORDER_DRIFT_ALLOWED_KEYS` (`reports.py:291`) | CHAR: exactly 4 keys, no change | `test_polymarket_us_exec_reports.py` |
| P23 | `FROZEN_SOURCE_SHA256["classify_create_order_outcome"]` | DROPPED; CHAR `test_classify_create_order_outcome_source_hash_unchanged` | `test_ambig_no_id_firewall_delta.py` |
| W1 | `WIRE_ORDER_KEYS` 24 keys | NEW additive; the 20-key row UNEDITED | `test_polymarket_us_exec_reports.py` |

Commit order: FW-1, FW-3, FW-2, FW-4, P1a-d, P4a-e, P3, N1-N5, P6b, P7, T1-T3, CC-1, then code. The banned-word ban (`:3374-3381`) is untouched.

## 4. Commission design
- **Read.** Poll: `resting_commission_total(order)` over `commissionNotionalTotalCollected`. Create path unchanged (`parse_fill_report`). Neither reads `commissionsBasisPoints`, `makerCommissionsBasisPoints` or `feeCoefficient`.
- **Single recognition point (sec N-1, arch H-4).** `recognised = recognised_commission(raw, sign_verified=MAKER_COMMISSION_SIGN_VERIFIED)` (= `max(raw, 0)` while False). It is written into `DurableFillRecord.cumulative_fee` AND booked as native `OrderFilled.commission`, so every consumer (the 17 readers in §0: `exec_par_settled_pnl.py:175`, `exec_wiring.py:231`, `continuous_strategy.py:2933`, `exec_par_counter_ingest.py:454`, labeling scorers, `trial_day_latch.py:1828`, and `Position.realized_pnl` in `exit_guard.py:90-110`) sees a value that cannot be an unverified rebate. Raw lives only in `venue_fee_raw` (exact string, no float) + `commission_sign`. A negative maker commission is NEVER refused (L-48). Positive is always cost.
- **Static scan** (`test_budget_and_cap_readers_use_recognised_commission_static_scan`): (a) `venue_fee_raw`, `commission_raw`, `commissionNotionalTotalCollected`, `resting_commission_total` readers over `src/` AND `scripts/` must be in an allowlist with one disposition each (`fee_source_for` presence tests `:894`, `:5533`, `:6057`, `trial_day_latch.py:529` mirror, the writer `:7295`, audit/evidence CLIs); (b) the 17 current `.commission`/`.cumulative_fee`/`realized_pnl` readers are asserted by file:line-independent symbol to NEVER read `venue_fee_raw`/`commission_raw`. Day-one green, plant red.
- **Flip.** `MAKER_COMMISSION_SIGN_VERIFIED` becomes True only by a reviewed commit citing WP6; then `recognised == raw` and downstream consumers are re-reviewed in that commit.
- **Drift pin.** `assert_commission_bps_inert` returns a value-free `BpsDrift` (never raises). Drift latches `commission_bps_drift` (CRITICAL, NEW rests only); cancels, polls, sweep continue.
- Taker side untouched: `_assert_taker_fill` still refuses a maker Execution (CHAR).

## 5. Cancel transport and cancel-all guard
1. **Transport.** `post_cancel_all(api_base_url, *, headers, slugs)` builds `{"slugs": [...]}` INSIDE the transport via `json.dumps`, refuses empty/non-sequence/duplicate/non-`parse_weather_slug` input, re-parses its own body (`len >= 1`) before dispatch (signatures do not cover the body, so this is the last control before the wire). `post_cancel_order(api_base_url, *, headers, order_id, market_slug)` validates `order_id` against `^[A-Za-z0-9_-]{1,64}$` and `market_slug` with `parse_weather_slug`, builds `{"marketSlug": market_slug}` via `json.dumps`, path from `cancel_order_path` (T3).
2. **Disabled until proven.** `SLUG_SCOPED_CANCEL_ALL_VERIFIED: Final[bool] = False`; `_cancel_slug_orders(slug)` returns `UNSCOPED_UNVERIFIED` without sending while False; callers fall back to per-order cancels. Flipped only by a reviewed commit citing the WP6 two-slug artifact.
3. **Choke point** `_cancel_slug_orders(slug: str)`: scalar, non-empty, daily-grammar, present in the durable ledger via KEY ENUMERATION (`resting:` rows + `resting=True` contexts), not `_store_get`. The strategy path never reaches it; an EMPTY ledger issues zero POSTs; no slug list derives from the universe or an open-orders reply.
4. **Boot sweep while the pin is False:** per-order `post_cancel_order` by id, ledger ids only. **Unbound open orders are NEVER cancelled** (may be the operator's manual order): WARN-logged (id + `marketSlug` only), ONE CRITICAL alert via the existing delivery, and the arm gate keeps refusing. The sanctioned claim path is the no-id resolver's ADOPT (`:4654`): a positively attributed order becomes a with-id ledger id and is then cancellable. Pin True: per slug, UNFILTERED read, `_cancel_slug_orders`, UNFILTERED re-read.
5. **Certification.** UNFILTERED `GET /v1/orders/open` via `parse_open_orders`: no order with `marketSlug == slug` AND unknown envelope keys empty (a future `nextCursor` refuses). Missing `eof` = complete (HEAD behaviour). POST status and `canceledOrderIds` logged only. Logs: ids + slug only.

## 6. Resting-accept and cancel state machine (verdicts = native `OrderStatus` + `filled_qty`)

| Step | Observation | Action |
|---|---|---|
| Create | async POST 200 + id | with-id context (`resting=True`) written, intent in the in-flight set (removed by the single `finally` after confirm), K=1 held, confirm. No id / non-4xx failure = existing no-id AMBIGUOUS path |
| Confirm | ACCEPTED, `filled_qty==0`, echo matches | `_bind_resting_order`, clear AMBIGUOUS refusal, release K=1 |
| Confirm | else / deadline / GET error / mismatch / tif not GTD | HOLD: `_refuse` + `mark_ambiguous` + `_note_ambiguous_open(resting=True)`; with-id resolver decides; slot+budget held |
| Resolver | with-id `resting=True`, ACCEPTED, `filled_qty==0`, echo matches | same binder (clears the global refusal) |
| Cancel (bound or HOLD, incl. GTD expiry) | `_cancel_order` -> `_cancel_resting_order` by id (§2 WP3.8) | POST cancel, `_confirm_cancel_terminal` GET authoritative: terminal zero -> `generate_order_canceled`/`_expired`, settle once, restore iff this-process id; fill -> poll/fill path, no restore |
| Cancel refused / errored / still ACCEPTED | RETRY-WHEN-OPEN | loop inside `_cancel_resting_order`: no event, no settle, no restore; backoff `CANCEL_RETRY_BACKOFF_S`; budget held |
| Alert | age measured from the FIRST refused cancel exceeds `RETRY_ALERT_AGE_S` (600 s, independent of GTD) | non-latching CRITICAL via existing delivery, re-alert every `RETRY_REALERT_S`; node-down: the boot sweep re-enters |
| Latch | `now >= cancel_latch_deadline(first_refused, expire_time) = max(expire_time + RETRY_LATCH_GRACE_S, first_refused + RETRY_ALERT_AGE_S + RETRY_LATCH_FLOOR_S)` and still non-terminal | latch `resting_cancel_unconfirmed` (CRITICAL, submits refused, cancels continue); escalation `_cancel_slug_orders` only if its pin is True. Property test: the alert time is strictly before the latch time for every input |
| Venue-initiated | GET `CANCELED`/`EXPIRED`, `filled_qty==0`, no cancel of ours pending | VALID retirement as a solicited cancel (events, settle once, restore this-process only, delete row, INFO) |
| Poll | 3 failed GETs per id | latch `resting_query_unreadable` (r3) |

No `_read_market_state`, no halt annotation: behaviour never depends on knowing the market is halted.

## 7. Discovery hardening (WP1 step 0: characterise first)
- `provider.py:255-262`: `parsed is None and city_name is not None` raises; `test_polymarket_us_discovery.py:653-664` (non-`tc-temp` slug with a weather question must raise) stays UNEDITED.
- **Step 0 = tests only, buildable now:** (a) CHAR on a recorded 71-market fixture (60 daily + 11 non-daily) through `_weather_market_payloads`: no raise, 60 candidates; (b) tolerance audit of the same fixture through `fee_drift_evidence_pull`, `capture_audit`, `label_run`, `parse_open_orders`, `unmappable_resting_order_reason`. Any RED = a LIVE fault: fix at that site, full gate, restart in the 01:00-16:40Z window. All green = no provider change merges (YAGNI, L-32).
- If (a) is red: keep the raise when the slug matches the DAILY prefix derived from `symbology._WEATHER_SLUG_RE` (one grammar source) OR `city_name` resolves to a configured registry city; else `continue` after one WARN `non_daily_weather_slug_sighting` (size-capped dedupe) + per-cycle count; alert if a configured city yields zero parsed markets.

## 8. Nautilus null-hypothesis
| Component | Native mechanism | Why nothing new |
|---|---|---|
| Rest accept | `parse_order_status_report` + `OrderStatus.ACCEPTED`, `generate_order_accepted` | no state classifier; only the GET trigger is Breezy-side |
| Cancel verbs | `_cancel_order`/`_cancel_all_orders` overrides, native cancel events | base bodies are `NotImplemented`; the venue verb is the gap |
| Commission | `OrderFilled.commission` / `FillReport.commission` signed `Money`; `PolymarketUSFeeModel` untouched | the recognised value is booked; the sign gap closes by WP6 evidence |
| GTD expiry | `StrategyConfig.manage_gtd_expiry` (`strategy.pyx:888`) -> `cancel_order` | venue `goodTillTime` is only the backstop; it routes into the same `_cancel_order` |
| Query | `_query_order` native hook (restored override) | GET-only |
| Venue-initiated terminal | native canceled/expired events | a branch in the poll |
| 24-key pin, bps drift guard | none | test constant; same class as `_*_DRIFT_ALLOWED_KEYS` |

## 9. RED-first tests. **[CHAR]** = cannot fail before the change; mutation evidence required (L-33: show it red under a named mutation)
- **WP1** `test_polymarket_us_resting_order_shape.py`: `test_resting_body_key_set_is_the_nine_key_async_set`, `..._omits_synchronous_execution_and_max_block_time`, `test_good_till_time_is_rfc3339_utc_whole_seconds_floored`, `..._never_later_than_expire_time`, `test_resting_shape_refuses_non_daily_weather_slug`, `test_resting_echo_matches_{slug,side,price,quantity,tif_gtd}_mismatch_is_false`, `test_resting_echo_no_leg_compares_via_the_leg_mapping`, [CHAR] `test_ioc_body_key_set_unchanged`, [CHAR] `test_classify_create_order_outcome_source_hash_unchanged`. `test_polymarket_us_exec_reports.py`: `test_wire_order_keys_literal_is_the_24_observed_keys`, [CHAR] `test_order_drift_allowlist_stays_exactly_four_keys`, [CHAR] `test_order_with_unsolicited_cancel_reason_is_refused`, `test_resting_commission_total_is_signed_and_required`, `test_commission_bps_inert_accepts_string_zero`, `test_commission_bps_drift_flags_nonzero_and_nonstring_value_free`, [CHAR] `test_assert_taker_fill_still_refuses_a_maker_execution`, `test_recognised_commission_clamps_negative_while_unverified`. Discovery: [CHAR] 71-market no-raise/60-candidates, [CHAR] `..._never_raises_on_non_weather_question`, `:653-664` UNEDITED.
- **WP3** `test_polymarket_us_resting_submit.py`: `test_async_create_200_with_id_does_not_accept_until_get_accepted`, `test_confirm_new_binds_and_retires_accepted_resting`, `test_confirm_branch_only_on_ambiguous_with_id_not_reject_or_zero_fill`, `test_with_id_resting_context_written_before_confirm_awaits`, `test_pre_post_context_carries_resting_and_survives_adopt`, `test_intent_removed_from_in_flight_set_in_finally_after_confirm`, `test_confirm_pending_at_deadline_holds_and_keeps_slot_and_budget`, `test_confirm_filled_terminal_zero_or_unreadable_hold_not_booked_inline`, `test_confirm_echo_mismatch_or_non_gtd_tif_holds`, `test_stop_during_confirm_leaves_context_intact`, `test_crash_between_post_and_confirm_resolves_via_with_id_resolver_bind`, `test_resolver_binds_accepted_resting_context_once`; **architect RED:** `test_with_id_resolver_skips_in_flight_intent`, `test_hold_context_rewrite_keeps_resting_true` (asserts `context.resting is True` after HOLD), `test_resolver_bind_clears_ambiguous_refusal`, `test_cancel_during_hold_by_with_id_context` (and GTD expiry route), `test_maker_reconciliation_commission_does_not_refuse_bound_rest`; [CHAR] `test_unbound_maker_reconciliation_fill_still_refuses`, [CHAR] `test_absent_resting_key_decodes_false`, [CHAR] `test_sync_response_echo_never_accepts`.
- **WP4** `test_polymarket_us_resting_cancel.py`: `test_cancel_body_is_exactly_market_slug_of_the_bound_row`, `test_cancel_order_path_signed_equals_dispatched`, `test_cancel_order_id_allowlist_refuses_everything_outside_the_regex`, `test_post_cancel_order_refuses_non_daily_market_slug`, `test_post_cancel_all_refuses_empty_non_daily_duplicate_slugs`, `test_post_cancel_all_body_built_in_transport_and_reparsed`, `test_slug_helper_returns_unscoped_unverified_while_pin_false`, `test_slug_helper_refuses_empty_and_off_ledger_slug`, `test_boot_sweep_while_pin_false_cancels_per_id_ledger_only`, `unbound_unattributed_order_never_cancelled_by_sweep` (+ CRITICAL alert, arm gate refuses), `test_adopted_order_becomes_cancellable_ledger_id`, `test_empty_ledger_sweep_issues_zero_posts`, `test_sweep_exit_requires_empty_unfiltered_reread_with_no_unknown_envelope_keys`, `test_sweep_next_cursor_key_is_unreadable`, `test_sweep_ignores_canceled_order_ids_echo`, `test_refused_cancel_loops_in_the_cancel_coroutine_with_backoff`, `test_query_order_poll_never_sends`, `test_retry_when_open_holds_budget_and_emits_no_event`, `test_alert_age_measured_from_first_refused_cancel_and_precedes_latch` (property over inputs), `test_latch_only_after_computed_deadline`, `test_venue_initiated_terminal_settles_once_restores_this_process_only`, `test_unsolicited_cancel_reason_absent_on_get_is_not_required`; [CHAR] `test_sweep_missing_eof_counts_complete`.
- **WP5** `test_polymarket_us_resting_query.py`: `test_poll_fill_books_recognised_commission_to_cumulative_fee_and_native_event`, `test_raw_negative_commission_persisted_only_in_venue_fee_raw`, `test_filled_any_with_negative_commission_is_booked_not_refused`, `test_budget_and_cap_readers_use_recognised_commission_static_scan` (17 readers + `venue_fee_raw` allowlist), `test_position_realized_pnl_cannot_rise_on_unverified_rebate`, `test_positive_commission_always_counted`, `test_commission_outside_envelope_books_and_latches_new_rests_only`, `test_bps_drift_latches_new_rests_keeps_cancels_and_booking`, `test_hold_resolved_resting_fill_reports_taker_fee_unreconciled`, [CHAR] `test_poll_never_reads_bps_or_fee_coefficient`.
- **Firewall** `test_resting_path_firewall_delta.py`: one plant per row of §3; `test_post_cancel_all_referenced_only_in_cancel_slug_orders`, `test_submit_order_never_references_cancel_helpers`, `test_scripts_scan_sees_a_planted_cancel_all_reference` (planted import of the probe helper), `test_legacy_probe_exemption_is_hash_pinned_in_n5_and_b4`, [CHAR] `test_banned_word_ban_unedited_and_new_helper_names_pass_it`.
- **WP6** `test_resting_order_lifecycle.py`: `test_lifecycle_async_rest_refused_cancel_retry_then_venue_expiry`, `test_wp6_probe_never_sends_empty_slug_cancel_all`.

## 10. Risk register delta (adds to r3 §8)
| Risk | WP | Guard |
|---|---|---|
| Rebate counted as income via ANY reader (durable, native, `Position.realized_pnl`) | 5/6 | one recognition point feeds `cumulative_fee` and native commission; raw only in `venue_fee_raw`; two-sided static scan |
| Stranded real fill (refuse-on-negative or out-of-envelope) | 5 | book always; latch refuses only NEW rests (L-48) |
| Slug filter inert -> cancel-all account-wide | 4/6 | pin False until WP6; four layers; N3/N5 incl. `scripts/`; probe hash-pinned |
| Unbound order cancelled in error (operator's manual order) | 4 | never cancelled; CRITICAL alert + arm gate; ADOPT is the only claim path |
| Inline confirm books a fill/terminal | 3 | NEW-only; all else HOLD to the resolver (L-36/L-52) |
| Double bind / crash mid-confirm / stale AMBIGUOUS refusal | 3 | context first, `resting` threaded through every write, with-id in-flight skip, binder clears the refusal |
| K=1 starved by a held in-flight id | 3 | single `finally`; durability from the context |
| Halted market blocks cancels | 4 | in-coroutine backoff; alert 600 s from first refusal, latch strictly later; arm gate exempts own bound rows |
| Cancel loop dies with its task | 4 | boot sweep re-enters from the ledger; UNVERIFIED task-per-command check |
| Sweep certifies a false empty | 4 | unfiltered read, `parse_open_orders` semantics, unknown keys empty |
| Reconciliation refuses a bound maker fill | 5 | slug-keyed carve-out only for ledger slugs; unbound MAKER still refuses |
| Discovery fault hides daily drift | 1 | characterise first |
| 24-key drift blocks every poll | 5 | fail-closed; 3-strike latch; fix = reviewed allowlist row |
| Probe leaks order rows | 6 | key-name-only extractors |
| Venue ignores GTD | 1/6 | never bound; S-6 STOP |
| Poll quota | 3/5 | 0.5 s poll, 5 s confirm = at most 10 GETs per rest |

## 11. Open questions: NONE.
Closed: while `SLUG_SCOPED_CANCEL_ALL_VERIFIED` is False the sweep leaves unbound open orders, raises one CRITICAL alert via the existing delivery and the arm gate refuses (§5.4). Both round-2 reviewers concur; the claim path is the no-id resolver's ADOPT.

## 12. Disposition (every finding -> section)
| Finding | Disposition | Section |
|---|---|---|
| R1 Sec H1 slug scoping | pin False, helper disabled, per-id sweep | 5.2, 5.4, P16 |
| R1 Sec H2 raw negative at readers | accepted, superseded by sec N-1/arch H-4 single recognition point | 4 |
| R1 Sec H3 RETRY unbounded | backoff, early alert, late latch (sec N-2) | 6 |
| R1 Sec H4 transport/probe/id | T1/T2/T3, body in transport, N5, hash-pinned probe | 3, 5 |
| R1 Sec M1-M7, L1-L3, Q1-Q5 | accepted as rev 2; M7 logging, Q3 decided native-only then DROPPED annotation | 2, 4, 5, 7 |
| R1 Arch V1-V3, HIGH 1-5, MED, LOW | accepted as rev 2 (completeness, firewall rows, NEW-only confirm, crash test, discovery first) | 2, 3, 5, 7 |
| R2 Sec N-1 scan misses readers | recognised value feeds `cumulative_fee` + native; scan covers raw readers and the 17 | 0, 4 |
| R2 Sec N-2 alert age tied to GTD | age from first refusal, 600 s, latch floor after alert, computed bound, property test | 3 (P16), 6 |
| R2 Sec N-3 id denylist | allowlist regex both sides; `market_slug` via `parse_weather_slug`; `json.dumps` | 3 (T3), 5.1 |
| R2 Sec N-4 context overwrite | `resting` threaded through all three writes; post-HOLD assertion; pre-POST flag survives ADOPT | 2 WP3.2-3, 9 |
| R2 Sec N-5 N5 matching | substring match, planted import, probe pinned in N5 and B4 | 3 (N5) |
| R2 Sec R-1 sweep ruling, R-2, R-3, R-4 | adopted (alert + test; accessor = N-1; probe neutralisation recommended as a separate reviewed commit AFTER S4, then N5 drops the exemption; T-rows plus allowlist) | 3, 4, 5.4, 11 |
| R2 Sec round-1 PARTLY (H2, H3, H4d) | closed by N-1, N-2, N-3 | above |
| R2 Arch verification 1 (InstrumentStatus) | read is possible; annotation DROPPED (YAGNI) | 2 WP1 |
| R2 Arch verification 2 (id charset) | UNVERIFIED stays; `cancel_order_path` on `order_by_id_path`; regex frozen at build | 3 (T3) |
| R2 Arch verification 3 (reader list) | listed by file:line from codegraph/grep | 0, 4 |
| R2 Arch verification 4 (GTD) | VERIFIED; cancel-during-HOLD row | 0, 2 WP3.8 |
| R2 Arch verification 5 (with-id in-flight skip) | DEFINITE step + RED | 2 WP3.4 |
| R2 Arch verification 6 (L-47) | premise STRUCK; trailing-optional `.get`; CHAR | 0, 2 WP3.3 |
| R2 Arch verification 7 (liquidity side) | ONE rule: resolver unchanged, raw only via poll; slug-keyed carve-out | 2 WP5 |
| R2 Arch H-1 unlisted rows | P1c, P6b, P7 (V2 in `endpoints.py`, own commit) | 3 |
| R2 Arch H-2 P3 | restored; only `_read_market_state` dropped | 3 (P3) |
| R2 Arch H-3 HOLD path | `finally` around POST+confirm; `resting` threaded; binder clears refusal | 2 WP3.3-6 |
| R2 Arch H-4 fee field | `cumulative_fee = recognised`; raw only `venue_fee_raw` (existing field) | 0, 4 |
| R2 Arch H-5 taker-only paths | one rule + `calculate_commission` carve-out + RED/CHAR | 2 WP5, CC-1 |
| R2 Arch M-1 cancel in HOLD | by id from the context; GTD routes the same | 2 WP3.8, 6 |
| R2 Arch M-2 retry driver | `_cancel_resting_order` loop; poll never sends | 2 WP4, 6 |
| R2 Arch M-3 callee omissions | N1 (+sleep, UUID4, clock), N2/N3 (+signer, builder) | 3 |
| R2 Arch M-4 P1b plant | restated; `_cancel_all_orders` calls the helper directly | 3 (P1b) |
| R2 Arch M-5 standing rows | listed (P2, P6a, P7, P9, P10, P12, P14, P15, P18-P22 stand; P5/P17/P24 superseded) | 3 |
| R2 Arch LOW (pin constants, quota, key enumeration, NO-leg, N5/B4) | grace + floor pinned, per-order bound computed; poll 0.5 s; enumeration; leg mapping; one hash constant | 3, 5.3, 2 WP1 |
| R2 Arch T2 mislabel | WIDEN + forced safety-test edit, own commit + plant | 3 (T2) |
| R2 Arch FW-1/FW-2 union expression | named `\| frozenset({...})` term | 3 |
| R2 Arch RED/CHAR lists | five RED + three CHAR added | 9 |
| R2 Sec/Arch Q 11.1 | leave unbound, CRITICAL alert, arm gate; ADOPT is the claim path | 5.4, 11 |
| R2 Arch buildability | table below | 13 |

## 13. Buildability
| WP | Status | Blocked by |
|---|---|---|
| WP0 | DONE (provisional) | two reviewer sign-offs |
| WP1 | buildable; step 0 NOW | S2/S3 gate for the exec-side half; V2/T3 rows land with WP4 |
| WP2 | buildable | gate |
| WP3 | buildable once rev 3 passes peer review | gate; UNVERIFIED items: none block the design |
| WP4 | buildable after WP3 pins | UNVERIFIED builds checks: task-per-command, transport import cycle, store enumeration API, V2 write-path test |
| WP5 | buildable after P3 | UNVERIFIED: I1b refusal on `fee_reconciled=False`; `scripts/` reader enumeration |
| WP6 | after WP3-5 | operator-free probe route; flips are reviewed commits |
