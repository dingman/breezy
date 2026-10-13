# S4 r4 delta: exec resting-order path, re-plan against the WP0 venue discovery

| Field | Value |
|---|---|
| ID / Revision | S4 / **DRAFT r4 delta rev 2**, ON TOP OF `S4_exec_resting_order_path_plan_r3.md` (r3 stands wherever silent). Supersedes rev 1 |
| Date | 2026-10-13 |
| Trigger | `docs/evidence/venue/polymarket_us/MAKER_S4_WP0_VENUE_DISCOVERY_2026-10-13.md` (§2,§4,§5,§6,§9) + rev 1 reviews `reviews/S4-r4-security-review.md`, `reviews/S4-r4-architect-review.md` (both REQUEST_CHANGES, dispositioned in §12) |
| Gate | S2 NOT-KILLED and S3 REACHABLE (r3 §3). Nothing here is built. Exception: WP1 step 0 (tests only) may be built now. S5 family stays SHADOW |
| Provisional | WP0 findings are `provisional: true` until `python-reviewer` + `prediction-market-reviewer` sign off; (a)(e)(g), S-2, S-6 stay WP6-gated |

**Invariants (binding on every WP and brief):** Nautilus Trader immutable (extend only via `LiveExecutionClient` overrides and native `Strategy` calls). `allow_short` stays `False`; BUY only. Never weaken or delete a safety, settlement, contract or NO-SEND firewall test; exact sets widen by ONE reviewed row per commit with a non-vacuity plant (L-12, L-46); only-relaxing-goes-green = S-4 STOP. Never touch live enablement or `BREEZY_ORDERS_ENABLED`; assign no operator-reserved value (max daily budget, max per position). S4 builds the exec path; nothing arms it. No `git stash`; `PYTHONPATH=<wt>/src`; never uv/pip; `lint-imports` "N kept, 0 broken" after every slice; briefs name the whole-tree guards (firewall, import gates, fee-theta pin, mypy ratchet) not only focused tests.

## 0. Premise ledger (every kept code claim, re-read this revision)

| Claim | Status |
|---|---|
| `parse_open_orders`: missing `eof` = complete, `eof` present and not True refuses, other envelope keys recorded in `OpenOrderRecord.unknown_keys` (capped 16) (`reports.py:1640-1643`, `:1790-1797`) | VERIFIED |
| `ORDER_STATE_TO_ORDER_STATUS`: `NEW`->ACCEPTED, `PENDING_NEW/PENDING_RISK`->SUBMITTED; `parse_order_status_report` (`reports.py:441`, `:1124`); resolver already branches on `report.order_status` + `filled_qty` (`client.py:3385-3395`) | VERIFIED |
| `parse_instrument_status` (`parsing.py:1035-1060`) carries raw `marketData.state` in `InstrumentStatus.reason`; data client publishes it on every book payload that has a state (`data.py:1780`) | VERIFIED |
| An exec client can READ the last `InstrumentStatus` (msgbus/cache) without importing the data client | **UNVERIFIED**; check at WP4 build (see §6); no behaviour depends on it |
| `_submit_order` removes the intent from `_post_in_flight_intent_ids` in a `finally` right after `post_order` (`client.py:7180`, `:7207-7208`); no-id resolver skips in-flight intents (`:4299`); AMBIGUOUS path = `_refuse` + `mark_ambiguous`, then `_note_ambiguous_open` which OVERWRITES the pre-POST context for the same intent key (`:7516-7583`) | VERIFIED |
| `_note_ambiguous_open` has NO `resting` field at HEAD (`:6707-6723`, only `wire_*` echoes) | VERIFIED; the durable-context field is new schema: version/migrate per L-47 at build |
| `_cancel_order` is in `ORDER_LIFECYCLE_COROUTINES` (`test_execution_egress_firewall_guard.py:1926`) so it is bound by the shared callee set and its banned-word loop `:3374-3381` (any callee containing read/send/post/request except `self._order_sender.post_order` fails) | VERIFIED |
| `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` (`:4374`) = `{__init__} | ORDER_LIFECYCLE_COROUTINES | EXEC_RESOLVER_COROUTINES`; `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) = `{__init__, _submit_order}` | VERIFIED |
| `write_transport.post_cancel_all(api_base_url, *, headers)` is BODILESS today, sends nothing but headers to `/v1/orders/open/cancel` (an account-wide cancel at the venue); no `src/` caller (`write_transport.py:160-175`) | VERIFIED |
| Signature = `timestamp + METHOD + path`; body and query are NOT signed (`signing.py:128-134`, `build_canonical_path_without_query`) | VERIFIED. Rev 1 l.51 "before any byte is signed" was wrong; the transport-side body check is the last control before the wire |
| `scripts/venue/polymarket_us_write_signing_probe.py:_signed_post_cancel_all` sends `body={}` to `/v1/orders/open/cancel` (`:325-336`, callers `:459`, `:655`) | VERIFIED |
| `settle(realized_usd)` receives `cumulative_qty * avgPx` (`client.py:3860`, `:3935`), i.e. price cost with NO commission; the budget ledger is commission-free | VERIFIED (resting path inherits it) |
| `_usd_commission` quantises to USD cents (`reports.py:1048`); a sub-cent venue fee/rebate books as $0.00 with a WARN, so native `FillReport.commission` loses a ~$0.003 maker rebate | VERIFIED |
| `taker_fee_bound` (rev 1) does not exist. Real names: `fees.taker_fee_at_fill(quantity, price, ts_event_ns, fee_coefficient_at_fill) -> Money | None`, `fees.expected_fee_for` (`fees.py:418`, `:560`); `exec/client.py:313` already imports from `fees` | VERIFIED; rev 2 uses `taker_fee_at_fill` |
| `Strategy` `manage_gtd_expiry=True` timer+cancel | r3-cited (`trading/strategy.pyx`), not re-read here; re-check at WP3 |
| `write_transport` may import `parse_weather_slug` (no import-linter contract forbids; both `adapters` layer) | per architect V2 (`pyproject.toml:74-106`); `lint-imports` at build is the proof |
| Observed venue order-id charset | **UNVERIFIED**; the id regex (§5) is frozen from WP0 evidence ids at build |

## 1. r3 assumption -> WP0 finding -> change

| # | r3 assumption (line) | WP0 finding | Change |
|---|---|---|---|
| 1 | WP5 books "the venue field with its venue sign" (l.147); `_assert_taker_fill` refuses maker Executions (`reports.py:1222`) | bps fields read `"0"` on every own order while `feeCoefficient` is 0.0695; passive legs of OTHERS showed negative; own sign UNOBSERVED | Fee comes ONLY from realised `Order.commissionNotionalTotalCollected`. Book RAW, never refuse (§4). bps = drift pin only |
| 2 | `KIND_ACCEPT_RESTING` from the create response (l.99-100) | Sync response for a rest UNVERIFIED | Rest is an ASYNC create (9-key body). 200+id never accepts; accept = bounded GET shows `OrderStatus.ACCEPTED` with `filled_qty == 0` AND cross-check (§6). `classify_create_order_outcome` untouched (P23 dropped) |
| 3 | Slug cancel-all body "non-empty, each tc-temp-*" (l.120) | Empty/missing `slugs` = ACCOUNT-WIDE; `tc-temp-sjc-dec-lt40` is `tc-temp-*` | Allowlist = `parse_weather_slug(slug) is not None`; four layers + disabled until WP6 (§5) |
| 4 | Sweep certifies by `?slugs=` re-read (l.132) | Filter honoured UNVERIFIED | Unfiltered `/v1/orders/open` + client-side filter; completeness = `parse_open_orders` semantics (§5) |
| 5 | Cancel confirm 30 s then cancel-all + latch (l.124-127) | `HALTED` blocks cancels (inferred); `EXPIRED` market expires orders | Any refused/unconfirmed cancel = RETRY-WHEN-OPEN with backoff, age-bound alert, latch only after `expire_time` (§6) |
| 6 | P11 widens `_ORDER_DRIFT_ALLOWED_KEYS` (l.183) | `unsolicitedCancelReason` is an Execution field, already allowed (`reports.py:333-340`) | P11 NO CHANGE; pin the 4-key Order allowlist (CHAR) |
| 7 | Order keys SDK-20 | Wire Order has 24 keys | Additive `WIRE_ORDER_KEYS` literal; the 20-key snapshot-equality row (`test_polymarket_us_exec_snapshot_drift.py:138`) stays UNEDITED |
| 8 | Fills/state via GET; WS rejected | `ORDER_SNAPSHOT` best effort | Confirms r3; GET is authority |
| 9 | Discovery tolerates non-daily slugs (never examined) | 71 listed = 60 daily + 11 non-daily; `provider.py:255-262` raises when a non-parsing slug's question matches the city pattern | Tolerance audit + characterisation first; code only if red (§7) |
| 10 | Cancel body `{marketSlug}` implicit | Body REQUIRED | Per-order cancel `POST /v1/order/{id}/cancel` body exactly `{"marketSlug": <bound slug>}` (§5) |
| 11 | `goodTillTime` format unspecified | Request string, response RFC3339 ns | Pure `format_good_till_time` floors to whole seconds; honoured-or-not stays S-6; a GET showing non-GTD tif is never bound |

## 2. Per-WP amended steps (only what changes)

### WP0 (r3 l.91-94): DONE provisional
- Add the two reviewer sign-offs to the evidence file. Every WP6/later probe brief: "extractors emit key names/booleans/signs only; never `repr` a nested object; no order rows in tool output".

### WP1 (l.96-103)
- **Step 0 (tests only, buildable now, blocks nothing exec-side):** discovery tolerance audit + characterisation test (§7).
- Shape (l.97): add `parse_weather_slug(slug) is not None`. Body (l.99): `RESTING_ORDER_BODY_KEYS` = `ORDER_BODY_KEYS` minus `{synchronousExecution, maxBlockTime}` plus `{goodTillTime}` (9 keys); `encode_order_body` (`submit_chain.py:578`) accepts exactly one of two sets (equality each). `format_good_till_time(expire_ns) -> str` pure, floored, never later than `expire_time`.
- NO `classify_resting_order_state`. Reuse native `parse_order_status_report` and `ORDER_STATE_TO_ORDER_STATUS` (Nautilus null hypothesis): the confirm verdict is `report.order_status is OrderStatus.ACCEPTED and report.filled_qty == 0` plus a pure `resting_echo_matches(report, wire_echo) -> bool` (slug, side, price, quantity, tif==GTD, goodTillTime within 1 s) in `submit_chain.py`. Anything else is HOLD (no new state enum).
- `reports.py`: `WIRE_ORDER_KEYS`, `resting_commission_total(order) -> Decimal` (signed, `_require`d, never `abs`), `assert_commission_bps_inert(order) -> BpsDrift | None`, `recognised_commission(raw, *, sign_verified) -> Decimal` = `raw if sign_verified else max(raw, 0)` (§4).

### WP2 (l.105-109): UNCHANGED (two new `RetirementReason` rows; a venue-initiated terminal is an order event, not an intent event).

### WP3 (l.111-117) -- inline confirm acts on NEW ONLY
- In `_submit_order`, the new branch fires only when `classify_create_order_outcome` yields AMBIGUOUS WITH a `venue_order_id` for a resting-shaped order (a 4xx REJECT, ZERO_FILL, taker `ACCEPT_FILL` or no-id AMBIGUOUS never enter it). It sits BEFORE the `_refuse(AMBIGUOUS_REASON)`/`mark_ambiguous` block (`client.py:~7516`) and only claims the order by binding.
- Order of operations: (1) write the with-id context with `resting=True` (+ the `wire_*` echoes) BEFORE awaiting confirm; (2) keep the intent in `_post_in_flight_intent_ids` across the whole window (move the `finally` removal at `:7207-7208` to after the confirm; verify the with-id resolver also skips in-flight intents, add the skip if absent, so it cannot bind twice); (3) `await self._confirm_resting_order(venue_order_id, wire_echo)` = GET `/v1/order/{id}` via `_private_read` every `RESTING_CONFIRM_POLL_S` (0.2) up to `RESTING_CONFIRM_DEADLINE_S` (5), both PROVISIONAL RulePins; GET-only helper returning `NEW_VERIFIED | HOLD`; (4) `NEW_VERIFIED` -> `_bind_resting_order` (store `resting:` row, retire `ACCEPTED_RESTING`, `generate_order_accepted`, release K=1); (5) anything else (PENDING at deadline, FILLED/PARTIAL, terminal zero, echo mismatch, unreadable, GET error, cancellation) -> fall through UNCHANGED to `_refuse` + `mark_ambiguous`: HOLD and the with-id resolver (120 s floor, trade-join evidence, L-36/L-52) decides. No inline fill booking, no inline terminal-zero retire.
- **K=1 slot and budget are NOT released at the confirm deadline**, only on a terminal/bound read (M5). A stop/shutdown/cancel in the window leaves the with-id context and in-flight set intact (`is_cancelled` re-raise as at HEAD).
- Resolver correction (V1): the with-id resolver applies NO age floor to `NEW`; it logs "neither terminal nor a fill" and polls every 5 s (`client.py:3385-3395`, `:589`). r4 therefore changes the resolver in exactly one place: a with-id context with `resting=True` whose GET shows `ACCEPTED`, `filled_qty == 0` and a matching echo calls the SAME `_bind_resting_order`. `_bind_resting_order` has exactly two callers (`_submit_order`, that resolver branch).
- Taker-on-create unchanged (`parse_fill_report`).

### WP4 (l.119-143)
- **4a** per-order and slug transport verbs and path pins: §5. **4c** cancel state machine: §6. **4e** boot sweep: §5 (while `SLUG_SCOPED_CANCEL_ALL_VERIFIED` is False it cancels per id from the ledger only). Arm gate keeps refusing for UNBOUND orders; own bound rows exempt (4b). 4b, 4d, 4f unchanged.
- Helper names are deliberately free of the banned words (read/send/post/request) so the `:3374-3381` ban stays UNEDITED: `_confirm_resting_order`, `_cancel_resting_order`, `_cancel_slug_orders`. Rev 1 names (`_post_slug_cancel_all`, `_confirm_resting_by_read`) would have tripped it.
- OS-block proof (l.143): add `test_post_cancel_all_with_empty_slugs_never_reaches_the_transport`.

### WP5 (l.145-166)
- Fill (l.147): at the FILLED observation (qty 1, one fill) book `resting_commission_total(order)` RAW to native `FillReport.commission`; `commission_raw` (exact string) + `commission_sign` stored in the durable record. Reachable for `FILLED_ANY` from BOTH the resting confirm hold-resolution and the poll: never through `parse_fill_report`/`_assert_taker_fill`. `liquidity_side`: MAKER only for a fill first observed after a recorded bind, else `NO_LIQUIDITY_SIDE` (create-cross vs maker indistinguishable); build-time check that Nautilus accepts it and no Breezy reader branches on TAKER.
- Envelope: `abs(commission) <= taker_fee_at_fill(quantity=1, price, ts_event_ns, None)` (theta from the pinned fee schedule; `None` = unpinned: skip with WARN). Outside the envelope: STILL BOOK raw, latch `resting_commission_out_of_envelope` (refuses NEW rests only), CRITICAL alert. Refusing to book would strand a real fill and deadlock WP6 (L-48).
- Every poll GET runs `assert_commission_bps_inert` (§4). No-id attribution (l.154-164) unchanged.

### WP6 (l.198-202)
- Same probe route/caps. (i) key-names-only record of the async rest response and first `GET`; (ii) first own passive fill: record `commissionNotionalTotalCollected` sign, flip `MAKER_COMMISSION_SIGN_VERIFIED` in a reviewed commit; (iii) GTD honoured (S-6); (iv) per-order cancel `{marketSlug}` and slug-scoped cancel-all on two slugs (S-2), run with ONLY own probe orders resting; flips `SLUG_SCOPED_CANCEL_ALL_VERIFIED` in a reviewed commit citing the artifact. WP6 must NOT import or reuse the legacy probe's `_signed_post_cancel_all`; NEVER send an empty-slug cancel-all, even as a negative control.

## 3. Complete pin-row list (r3 §6.7 deltas). Each row = its OWN commit + a plant that must trip; widen only, never `issubset`

| Row | Set / site | Delta | Test file |
|---|---|---|---|
| FW-1 | `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` (`:4374`) | WIDEN +`_cancel_resting_order` | `test_execution_egress_firewall_guard.py` |
| FW-2 | same | WIDEN +`_cancel_slug_orders` | same |
| FW-3 | `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) | WIDEN +`_cancel_resting_order` (r3's `_cancel_order` is NOT added; `_cancel_order` calls the helper, never the sender) | same |
| FW-4 | same | WIDEN +`_cancel_slug_orders` | same |
| P1a | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`:1952`) | WIDEN +`self._confirm_resting_order` (plant: used by `_submit_order` only) | same |
| P1b | same | WIDEN +`self._cancel_resting_order` (used by `_cancel_order` only) | same |
| P1c | same | WIDEN +`submit_chain.format_good_till_time`, +`submit_chain.build_resting_order_body`, +`submit_chain.unmappable_resting_order_reason` (pure, one row each, as r3) | same |
| P4a-c | `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) | WIDEN +`_confirm_resting_order`, +`_cancel_resting_order`, +`_cancel_slug_orders` (three commits) | same |
| N1 | NEW exact `EXEC_RESTING_CONFIRM_PERMITTED_CALLEES` | GET-only mirror of the resolver set (`self._private_read`, `order_by_id_path`, `parse_order_status_report`, `resting_echo_matches`, log); contains no `self._order_sender.*` | `test_resting_path_firewall_delta.py` |
| N2 | NEW exact `EXEC_CANCEL_SEND_PERMITTED_CALLEES` (body of `_cancel_resting_order`) | exactly one send callee `self._order_sender.post_cancel_order`; banned-word loop for THIS set allows that one name only | same |
| N3 | NEW exact `EXEC_SLUG_CANCEL_PERMITTED_CALLEES` (body of `_cancel_slug_orders`, was P25) | `self._order_sender.post_cancel_all`, `parse_weather_slug`, `self._store_get`, log. Plants: a second `post_cancel_all` reference in `_cancel_order`, `_cancel_resting_order` or the sweep fails; `_submit_order` referencing `_cancel_slug_orders` fails (M1) | same |
| N4 | NEW `EXEC_BOOT_SWEEP_PERMITTED_CALLEES` (was P24) | reads, `self._cancel_resting_order`, `self._cancel_slug_orders`, store, log; no `post_order` | same |
| N5 | NEW tree scan P26: `post_cancel_all` / `CANCEL_ALL_PATH` / literal `/v1/orders/open/cancel` | appears only in `write_transport.py` (+ the one N3 body); scans `src/` AND `scripts/`; exempt ONLY the legacy probe file `scripts/venue/polymarket_us_write_signing_probe.py` (its `body={}` is a deliberate 09-04 account-wide control), exemption pinned by file sha256 so any edit is a reviewed change; plant: a new script referencing the path fails; tests may use a recording client | same |
| T1 | `test_the_write_callable_has_no_method_query_or_body_parameter` (`test_polymarket_us_write_transport.py:322`) | UNEDITED and stays green (`slugs` is not `body`); ADD companion tightening: params of `post_cancel_all` == {self, api_base_url, headers, slugs} and of `post_cancel_order` == {self, api_base_url, headers, order_id, market_slug}; no `method/query/params/timeout_secs`, no caller bytes | same file |
| T2 | `test_it_issues_exactly_one_post_to_the_one_pinned_path` (`:339`) | TIGHTEN, never delete: recorded call keys == {url, headers, body, keys} for the two cancel verbs; path equality kept per verb; bodiless form must be absent | same file |
| T3 | NEW `CANCEL_ORDER_PATH_TEMPLATE == "/v1/order/{order_id}/cancel"` equality + pure `cancel_order_path(order_id)` used by BOTH the client signer and the transport URL (equal strings, test); id validated before building (frozen from WP0 evidence; refuses `/ ? # % .. whitespace`, empty, over-long); existing b3 exposure pins (`test_b3_the_constructed_write_transport_exposes_no_write_capable_receiver`) re-run UNEDITED | same file |
| P13 | `encode_order_body` equality (`submit_chain.py:578`) | `RESTING_ORDER_BODY_KEYS` = 9-key async set | `test_polymarket_us_resting_order_shape.py` |
| P16 | `test_cage_rule_constants_are_pinned.py` | + RulePins `RESTING_CONFIRM_DEADLINE_S`, `RESTING_CONFIRM_POLL_S`, `MAKER_COMMISSION_SIGN_VERIFIED` (False), `SLUG_SCOPED_CANCEL_ALL_VERIFIED` (False), `OBSERVED_COMMISSION_BPS` ("0"), `RETRY_WHEN_OPEN_MAX_AGE_S`, `RETRY_WHEN_OPEN_REALERT_S`, `CANCEL_RETRY_BACKOFF_S` | same |
| P23 | `FROZEN_SOURCE_SHA256["classify_create_order_outcome"]` | DROPPED; CHAR anchor `test_classify_create_order_outcome_source_hash_unchanged` | `test_ambig_no_id_firewall_delta.py` |
| P11 | `_ORDER_DRIFT_ALLOWED_KEYS` (`reports.py:291`) | NO CHANGE (CHAR pin: exactly 4 keys) | `test_polymarket_us_exec_reports.py` |
| P3 | `EXEC_QUERY_PERMITTED_CALLEES` | DROPPED (no `_read_market_state`, §6) | -- |
| W1 | `WIRE_ORDER_KEYS` 24-key literal | additive; `_ORDER_KEYS` (20) + snapshot-equality row UNEDITED | `test_polymarket_us_exec_reports.py` |

Net vs r3: widened exact-set rows are FW-1..4, P1a-c, P4a-c, four NEW sets (N1-N4), one NEW scan (N5), two TIGHTENED transport tests (T1 companion, T2), one NEW path pin (T3). The banned-word ban (`:3374-3381`) is untouched. Commit order: FW-1, FW-3 (helper `_cancel_resting_order`), FW-2, FW-4, then P1/P4, then N1-N5, then code.

## 4. Commission design

- **Read.** Poll/GET: `resting_commission_total(order)` over `Order.commissionNotionalTotalCollected` (`_require`d, `_parse_amount`). Create path: unchanged `parse_fill_report`. Neither reads `commissionsBasisPoints`, `makerCommissionsBasisPoints` or `feeCoefficient`.
- **Book raw.** Native `FillReport.commission` = raw signed value (cent-quantised by `_usd_commission`; a sub-cent rebate natively becomes $0.00 with a WARN, so `commission_raw` exact string + `commission_sign in {+,0,-}` are the audit truth). No `abs`, no flip, no maker constant. A negative maker commission is NEVER refused (L-48).
- **Recognition gate (H2).** `MAKER_COMMISSION_SIGN_VERIFIED` (False, RulePin). ONE accessor `recognised_commission` = `max(raw, 0)` while False. EVERY spend/cap/daily-budget/per-position/loss-stop/ROI/fee-drag reader goes through it. `settle(realized_usd)` is `qty*avgPx` and excludes commission (VERIFIED), so the operator budget is not exposed by the native booking; Nautilus portfolio PnL/account state DO see the raw sign and must not be a cap input. Static-scan test: no module under `src/` or `scripts/analysis/` outside the accessor reads `FillReport.commission` or `commission_raw` for those purposes (readers enumerated by the scan at WP5 step 0 and listed in evidence; list is UNVERIFIED until then). Positive commission is always counted as cost.
- **Drift pin.** `assert_commission_bps_inert(order) -> BpsDrift | None`: each present bps key must be `str` with `Decimal == 0`; returns a value-free `BpsDrift(key, observed_class)`; never raises (no lost fills).
- **If it drifts:** booking unchanged; latch `commission_bps_drift` (CRITICAL) refuses NEW rests only; cancels, polls, sweep continue; only a reviewed commit (pin + evidence) clears it.
- Taker side untouched: `_assert_taker_fill` still refuses a maker Execution (CHAR test kept); the poll path never calls it.

## 5. Cancel transport and cancel-all guard

1. **Transport.** `post_cancel_all(api_base_url, *, headers, slugs: Sequence[str])` builds the body INSIDE the transport (`{"slugs": [...]}`, never caller bytes), refuses an empty/non-sequence/duplicate/non-`parse_weather_slug` input, then re-parses its own body (`len >= 1`) before dispatch. Signatures do not cover the body, so this is the last control before the wire. `post_cancel_order(api_base_url, *, headers, order_id, market_slug)` builds `{"marketSlug": market_slug}` the same way, path from `cancel_order_path` (T3).
2. **Disabled until proven (H1).** `SLUG_SCOPED_CANCEL_ALL_VERIFIED: Final[bool] = False`. `_cancel_slug_orders(slug)` returns `UNSCOPED_UNVERIFIED` without sending while False; its callers fall back to per-order cancels. Flipped only by a reviewed commit citing the WP6 two-slug artifact. Until then no `post_cancel_all` byte can leave the process.
3. **Choke point** `_cancel_slug_orders(slug: str)`: scalar, non-empty, daily-grammar, present in the durable ledger (`resting:` rows + `resting=True` contexts). Strategy path never reaches it. Escalation passes the order's own bound slug; the sweep iterates ledger slugs; an EMPTY ledger issues zero POSTs; no slug list is derived from the universe or from an open-orders reply.
4. **Boot sweep while the pin is False:** per-order `post_cancel_order` by id, ledger ids only (`resting:` rows and with-id contexts). Unbound open orders on swept slugs are NOT cancelled; they are WARN-logged (id + `marketSlug` only) and keep the arm gate refusing. Pin True: per slug, UNFILTERED read, `_cancel_slug_orders`, UNFILTERED re-read.
5. **Certification.** The exit is an UNFILTERED `GET /v1/orders/open` parsed with `parse_open_orders`, with no order whose `marketSlug == slug`, AND all recorded unknown envelope keys empty (a future `nextCursor` refuses). Missing `eof` counts as complete (HEAD behaviour; "cannot prove completeness = UNREADABLE" would never certify, V3). POST status and `canceledOrderIds` are logged only. Log ids + slug only, no prices/sizes (M7). Unreadable/non-empty after the `expire_time` window latches `resting_cancel_unconfirmed`.

## 6. Resting-accept and cancel state machine (verdicts are native `OrderStatus` + `filled_qty`)

| Step | Observation | Action |
|---|---|---|
| Create | async POST 200 + id | with-id context (`resting=True`) written, intent stays in-flight, K=1 held, confirm (§2 WP3). 200 without id / non-4xx failure = existing AMBIGUOUS no-id path |
| Confirm | ACCEPTED, `filled_qty==0`, echo matches | bind (`_bind_resting_order`), release K=1 |
| Confirm | anything else / deadline / GET error / echo mismatch / tif not GTD | HOLD: existing `_refuse` + `mark_ambiguous`; with-id resolver decides; slot+budget stay held |
| Resolver | with-id `resting=True`, ACCEPTED, `filled_qty==0`, echo matches | same binder; terminal-zero and fills follow the existing resolver paths unchanged |
| Cancel | POST cancel (per id) then GET | GET authoritative: terminal zero -> `generate_order_canceled`/`_expired`, settle once, restore iff this-process id; fill -> fill path, no restore |
| Cancel | refused (any status), errored, or GET still ACCEPTED | RETRY-WHEN-OPEN: no event, no settle, no restore, no latch before `expire_time`; retry with backoff `CANCEL_RETRY_BACKOFF_S` (e.g. 5,10,20..cap), not every tick; budget held |
| Retry age | RETRY-WHEN-OPEN older than `RETRY_WHEN_OPEN_MAX_AGE_S` (RulePin, `max(goodTillTime+grace, 30 min)`) | non-latching CRITICAL alert via existing delivery, re-alert every `RETRY_WHEN_OPEN_REALERT_S`; node-down means the next boot sweep re-enters the same state |
| Deadline | `expire_time` passed and still non-terminal | latch `resting_cancel_unconfirmed` (CRITICAL, submits refused, cancels continue); escalation `_cancel_slug_orders` only if the pin is True |
| Venue-initiated | GET shows `CANCELED`/`EXPIRED`, `filled_qty==0`, no cancel of ours pending | VALID retirement as a solicited cancel (events, settle once, restore this-process only, delete row, INFO `venue_initiated_terminal`) |
| Poll | 3 failed GETs per id | latch `resting_query_unreadable` (r3) |

**Halt detection (Q3 decision).** No `_read_market_state`, no P3. Behaviour does not depend on knowing the market is halted: every refused/unconfirmed cancel takes the same safe path (retry, alert, latch after `expire_time`). The native `InstrumentStatus` (`reason` = raw state, VERIFIED) is used only as an optional annotation in the alert text IF an exec-side read of the last status exists (UNVERIFIED, WP4 build check: msgbus topic subscription or cache; if neither is native, omit). Security's objection (a 400/500 misread as halt suppressing escalation) cannot arise because nothing branches on the annotation and escalation is disabled until H1 clears. Halt auto-cancel is never relied on.

## 7. Discovery hardening (WP1 step 0: characterise first)

- `provider.py:255-262`: `parsed is None and city_name is not None` raises. `test_polymarket_us_discovery.py:653-664` (a non-`tc-temp` slug with a weather question must raise) STAYS UNEDITED. The fault is latent: the recorder already discovers all 71 listed markets.
- **Step 0 = tests only:** (a) CHAR test feeding the recorded 71-market fixture (60 daily + 11 non-daily) through `_weather_market_payloads`, asserting no raise and 60 candidates; (b) tolerance audit of the same fixture through `fee_drift_evidence_pull` (filters on `parse_weather_slug`), `capture_audit`, `label_run`, `parse_open_orders` (open order on a non-daily slug), `unmappable_resting_order_reason`. Any RED = a LIVE fault: fix at that site, full gate, recorder + node restart in the 01:00-16:40Z window. All green = no provider change merges (YAGNI, L-32).
- **If (a) is red**, the fix: for `parsed is None` keep the raise when the slug matches the DAILY prefix derived from `symbology._WEATHER_SLUG_RE` (one grammar source, no second regex; e.g. a public `daily_prefix_match(slug)` beside it) OR when `city_name` resolves to a configured registry city; otherwise `continue` after one structured WARN `non_daily_weather_slug_sighting` (dedupe set size-capped, L1) + per-cycle count; alert if a configured city yields zero parsed markets in a cycle (M6). No AUD-08 sidecar change.

## 8. Nautilus null-hypothesis

| Component | Native mechanism | Why nothing new |
|---|---|---|
| Rest accept | `parse_order_status_report` + `OrderStatus.ACCEPTED`, `generate_order_accepted` | No new state classifier; only the GET trigger is Breezy-side |
| Cancel verbs | `_cancel_order`/`_cancel_all_orders` overrides, `generate_order_cancel_rejected/canceled/expired` | Base bodies are `NotImplemented`; the venue verb is the gap |
| Commission | `FillReport.commission` signed `Money`; `PolymarketUSFeeModel` untouched | Gap is the venue sign, closed by WP6 evidence |
| Halt state | `InstrumentStatus.reason` already published (`parsing.py:1035`) | No market-state reader built |
| Venue-initiated terminal | native canceled/expired events | A branch in `_query_order` |
| GTD expiry | `StrategyConfig.manage_gtd_expiry` (r3-cited) | Venue `goodTillTime` is only the backstop |
| 24-key pin, bps drift guard | none | Test constant; same class as `_*_DRIFT_ALLOWED_KEYS` |

## 9. RED-first tests (names). **[CHAR]** = cannot fail before the change: characterisation, mutation evidence required (L-33: show the test going red under a named mutation)

- **WP1** `test_polymarket_us_resting_order_shape.py`: `test_resting_body_key_set_is_the_nine_key_async_set`, `..._omits_synchronous_execution_and_max_block_time`, `test_good_till_time_is_rfc3339_utc_whole_seconds_floored`, `..._never_later_than_expire_time`, `test_resting_shape_refuses_non_daily_weather_slug`, `test_resting_echo_matches_{slug,side,price,quantity,tif_gtd}_mismatch_is_false`, [CHAR] `test_ioc_body_key_set_unchanged`, [CHAR] `test_classify_create_order_outcome_source_hash_unchanged`. `test_polymarket_us_exec_reports.py`: `test_wire_order_keys_literal_is_the_24_observed_keys`, [CHAR] `test_order_drift_allowlist_stays_exactly_four_keys`, [CHAR] `test_order_with_unsolicited_cancel_reason_is_refused`, `test_resting_commission_total_is_signed_and_required`, `test_commission_bps_inert_accepts_string_zero`, `test_commission_bps_drift_flags_nonzero_and_nonstring_value_free`, [CHAR] `test_assert_taker_fill_still_refuses_a_maker_execution`, `test_recognised_commission_clamps_negative_while_unverified`. Discovery: [CHAR] 71-market no-raise/60-candidates test, [CHAR] `..._never_raises_on_non_weather_question`, existing `:653-664` test UNEDITED.
- **WP3** `test_polymarket_us_resting_submit.py`: `test_async_create_200_with_id_does_not_accept_until_get_accepted`, `test_confirm_new_binds_and_retires_accepted_resting`, `test_confirm_branch_only_on_ambiguous_with_id_not_reject_or_zero_fill`, `test_with_id_resting_context_written_before_confirm_awaits`, `test_intent_stays_in_post_in_flight_set_through_confirm`, `test_confirm_pending_at_deadline_holds_and_keeps_slot_and_budget`, `test_confirm_filled_terminal_zero_or_unreadable_hold_not_booked_inline`, `test_confirm_echo_mismatch_or_non_gtd_tif_holds`, `test_sync_response_echo_never_accepts`, `test_stop_during_confirm_leaves_context_intact`, `test_crash_between_post_and_confirm_resolves_via_with_id_resolver_bind`, `test_resolver_binds_accepted_resting_context_once`.
- **WP4** `test_polymarket_us_resting_cancel.py`: `test_cancel_body_is_exactly_market_slug_of_the_bound_row`, `test_cancel_order_path_signed_equals_dispatched`, `test_cancel_order_id_validation_refuses_path_metacharacters`, `test_post_cancel_all_refuses_empty_non_daily_duplicate_slugs`, `test_post_cancel_all_body_built_in_transport_and_reparsed`, `test_slug_helper_returns_unscoped_unverified_while_pin_false`, `test_slug_helper_refuses_empty_and_off_ledger_slug`, `test_boot_sweep_while_pin_false_cancels_per_id_ledger_only_and_leaves_unbound`, `test_empty_ledger_sweep_issues_zero_posts`, `test_sweep_exit_requires_empty_unfiltered_reread_with_no_unknown_envelope_keys`, `test_sweep_missing_eof_counts_complete`, `test_sweep_next_cursor_key_is_unreadable`, `test_sweep_ignores_canceled_order_ids_echo`, `test_refused_cancel_is_retry_when_open_backoff_not_every_tick`, `test_retry_when_open_holds_budget_and_emits_no_event`, `test_retry_when_open_alerts_after_age_bound_without_latching`, `test_latch_only_after_expire_time_passes`, `test_venue_initiated_terminal_settles_once_restores_this_process_only`, `test_unsolicited_cancel_reason_absent_on_get_is_not_required`.
- **WP5** `test_polymarket_us_resting_query.py`: `test_poll_fill_books_raw_signed_commission`, `test_filled_any_with_negative_commission_is_booked_not_refused`, `test_negative_maker_commission_persisted_raw_unrecognised_while_unverified`, `test_budget_and_cap_readers_use_recognised_commission_static_scan`, `test_positive_commission_always_counted`, `test_commission_outside_envelope_books_raw_and_latches_new_rests_only`, `test_bps_drift_latches_new_rests_keeps_cancels_and_booking`, [CHAR] `test_poll_never_reads_bps_or_fee_coefficient`.
- **Firewall** `test_resting_path_firewall_delta.py`: one plant per row of §3 (FW-1..4, P1a-c, P4a-c, N1-N5); `test_post_cancel_all_referenced_only_in_cancel_slug_orders`, `test_submit_order_never_references_cancel_helpers`, `test_banned_word_ban_unedited_and_new_helper_names_pass_it`, `test_scripts_scan_sees_a_planted_cancel_all_reference`, `test_legacy_probe_exemption_is_hash_pinned`.
- **WP6** `test_resting_order_lifecycle.py`: `test_lifecycle_async_rest_refused_cancel_retry_then_venue_expiry`, `test_wp6_probe_never_sends_empty_slug_cancel_all`.

## 10. Risk register delta (adds to r3 §8)

| Risk | WP | Guard |
|---|---|---|
| Fee sign inverted / rebate counted as income | 5/6 | raw persisted; `recognised_commission` clamp for every spend/cap/budget reader; static scan; taker refusal kept |
| Stranded real fill (refuse-on-negative or out-of-envelope) | 5 | book raw always; latch refuses only NEW rests (L-48) |
| Slug filter inert -> cancel-all is account-wide | 4/6 | `SLUG_SCOPED_CANCEL_ALL_VERIFIED=False` until WP6 two-slug proof; four layers; N3/N5 scan incl. `scripts/`; legacy probe hash-pinned |
| Inline confirm books a fill/terminal without floor or trade-join | 3 | confirm acts on NEW only; all else HOLD to the resolver (L-36/L-52) |
| Double bind / crash mid-confirm | 3 | with-id context first; in-flight set held; binder has two callers |
| Halted market blocks cancels indefinitely | 4 | backoff, age-bound non-latching CRITICAL, latch after `expire_time`; arm gate exempts own bound rows |
| Sweep certifies a false empty | 4 | unfiltered read, `parse_open_orders` semantics, unknown envelope keys must be empty |
| Discovery fault hides daily drift | 1 | characterise first; tripwire derived from `_WEATHER_SLUG_RE` + registry-city raise |
| 24-key drift blocks every poll | 5 | fail-closed; 3-strike latch; fix = reviewed allowlist row |
| Probe leaks order rows | 6 | key-name-only extractors in every brief |
| Venue ignores GTD (tif GTC on GET) | 1/6 | never bound; S-6 STOP |
| Sub-cent rebate rounds to $0 natively | 5 | `commission_raw` exact string is the audit value |

## 11. Open questions for peer review (max 3)

1. While `SLUG_SCOPED_CANCEL_ALL_VERIFIED` is False, the boot sweep leaves unbound open orders on swept slugs (WARN + arm gate refuses). Is "leave and refuse arming" right, or should a per-id cancel of an unbound order on a ledger slug be permitted (it may be a crashed no-id order of ours, or an operator's manual order)?

## 12. Disposition (every finding -> section)

| Finding | Disposition | Section |
|---|---|---|
| Sec H1 slug scoping unverified | accepted: pin False, helper disabled, sweep per-id | 5.2, 5.4, 3 (P16) |
| Sec H2 raw negative reaches spend readers | accepted: `max(raw,0)` accessor + static scan; `settle` verified commission-free | 4 |
| Sec H3 RETRY-WHEN-OPEN unbounded | accepted: backoff, age-bound alert, latch after `expire_time` | 6 |
| Sec H4 a/b/c/d transport, probe, id pin | accepted: T1 companion, T2 tighten, body built in transport, N5 scan + hash-pinned legacy probe, T3 path pin + id validation | 3, 5 |
| Sec M1 shared callee set | accepted: helpers only from their own coroutine; plants | 3 (N3, P1a/b) |
| Sec M2 one row per commit, names now | accepted: names listed, commit order | 3 |
| Sec M3 FILLED_ANY via taker path | accepted: raw booking never via `_assert_taker_fill` | 2 WP5, 9 |
| Sec M4 cross-check before bind | accepted: `resting_echo_matches` (+tif GTD) | 2 WP1, 6 |
| Sec M5 slot/budget at deadline | accepted | 2 WP3, 6 |
| Sec M6 regex duplicate / registry city | accepted, conditional on red characterisation | 7 |
| Sec M7 ids/slug only logging | accepted | 5.5 |
| Sec L1 dedupe cap, L2 envelope sign class, L3 completeness | accepted / accepted (raw booked, sign class logged) / resolved by V3 rule | 7, 4, 5.5 |
| Sec Q1 | book raw, never refuse, accessor | 4 |
| Sec Q2 | keep raise, WARN sufficient | 7 |
| Sec Q3 vs Arch Q3 | DECIDED: architect (native `InstrumentStatus`, no P3). Security's "no proxy" concern is met because behaviour never branches on halt state | 6 |
| Sec Q4 / Arch Q4 | inline confirm on NEW only | 2 WP3 |
| Sec Q5 / Arch Q5 | unfiltered read OK; completeness = `parse_open_orders` + empty unknown keys | 5.5 |
| Arch V1 `_submit_order`/resolver (no floor on NEW) | accepted; rev 1 l.115 corrected | 2 WP3 |
| Arch V2 transport may import `parse_weather_slug` | accepted; `lint-imports` proof | 0 |
| Arch V3 envelope completeness | accepted | 5.5 |
| Arch HIGH 1 completeness rule | accepted | 5.5 |
| Arch HIGH 2 unlisted firewall pins | accepted: keyword-free helper names keep ban unedited; FW/N rows | 3 |
| Arch HIGH 3 inline confirm too wide | accepted | 2 WP3, 6 |
| Arch HIGH 4 crash test / in-flight | accepted: context first, in-flight held | 2 WP3 |
| Arch HIGH 5 discovery vs existing test | accepted: characterise first | 7 |
| Arch MED classifier duplicates native | accepted: native status + `resting_echo_matches` | 2 WP1 |
| Arch MED `_confirm_resting_by_read` no pin | accepted: N1 | 3 |
| Arch MED native PnL / `settle` | stated: `settle` commission-free; native PnL sees raw | 4 |
| Arch MED `taker_fee_bound` unverified | renamed to `taker_fee_at_fill` | 0, 2 WP5 |
| Arch MED l.51 signature claim | corrected | 0, 5.1 |
| Arch MED regex duplicate | accepted | 7 |
| Arch MED/LOW characterisation labels | accepted | 9 |
| Arch sequencing | WP1 step 0 buildable now; live-fault path if red | 2, 7 |
| Rev 2 `Open questions` | one genuine | 11 |
