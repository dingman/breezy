# S4 r4 delta: exec resting-order path, re-plan against the WP0 venue discovery

| Field | Value |
|---|---|
| ID / Revision | S4 / **DRAFT r4 delta rev 1**, applies ON TOP OF `S4_exec_resting_order_path_plan_r3.md` (r3 text stands wherever this delta is silent) |
| Date | 2026-10-13 |
| Trigger | `docs/evidence/venue/polymarket_us/MAKER_S4_WP0_VENUE_DISCOVERY_2026-10-13.md` (§2, §4, §5, §6, §9) plus four coordinator-verified facts (§1 rows 1, 3, 5, 7) |
| Gate | S2 NOT-KILLED and S3 REACHABLE (r3 §3 entry). Nothing here is built; the build starts the day both land. S5 family stays SHADOW. |
| Provisional | WP0 findings are `provisional: true` until `python-reviewer` + `prediction-market-reviewer` sign off (discovery §8). r4 builds on rows (b)(c)(d-shape)(f-field)(h)/S-3 as PINNED-provisional; (a)(e)(g) and the S-2/S-6 halves stay WP6-gated |

**Invariants (restated, binding on every WP and brief):** Nautilus Trader is immutable (extend only via `LiveExecutionClient` overrides and native `Strategy` calls). `allow_short` stays `False`; BUY only. Never weaken or delete a safety, settlement, contract or NO-SEND firewall test; exact sets widen by ONE reviewed row at a time with a non-vacuity plant (L-12); only-relaxing-goes-green = S-4 STOP. Never touch live enablement or `BREEZY_ORDERS_ENABLED`; never assign an operator-reserved value (max daily budget, max per position). S4 builds the exec path; nothing arms it. No `git stash`; `PYTHONPATH=<wt>/src`; no uv/pip; `lint-imports` "N kept, 0 broken" after every slice.

## 1. r3 assumption -> WP0 finding -> change

| # | r3 assumption (line) | WP0 finding | Change |
|---|---|---|---|
| 1 | WP5 poll fill books `commission` = "the venue field with its venue sign" (l.147); WP0(f) hoped for a maker bps field; `_assert_taker_fill` refuses maker Executions (`reports.py:1222`) | `makerCommissionsBasisPoints` and `commissionsBasisPoints` read `"0"` on every own order while `feeCoefficient` is 0.0695 and taker legs carry positive `commissionNotionalCollected`; passive legs of OTHER participants showed negative; sign from our viewpoint UNOBSERVED | Fee/rebate comes ONLY from realised `Order.commissionNotionalTotalCollected` (poll) / `Execution.commissionNotionalCollected` (create path). bps = drift pin only (§4). Raw signed value persisted; no rebate income recognised until WP6 observes an own passive fill |
| 2 | `KIND_ACCEPT_RESTING` from the create response with id + `state NEW`; body is IOC keys + `goodTillTime` incl. `synchronousExecution=true, maxBlockTime=5` (l.99-100) | Docs warn against sync on a rest; sync response for a rest UNVERIFIED; `GET /v1/order/{id}` readable (S-3 cleared) | Rest is an ASYNC create (no `synchronousExecution`, no `maxBlockTime`). Create 200+id never accepts; accept = `GET` shows `ORDER_STATE_NEW` (§6). Classifier `classify_create_order_outcome` is NOT touched (P23 dropped); new pure `classify_resting_order_state` |
| 3 | Slug-scoped cancel-all body "non-empty, each tc-temp-*" (l.120) | Empty/missing `slugs` = ACCOUNT-WIDE cancel; `tc-temp-sjc-dec-lt40` is a `tc-temp-*` slug that is not a daily market | Four-layer guard (§5); allowlist is `parse_weather_slug(slug) is not None`, not a prefix |
| 4 | Sweep certifies by re-read of `?slugs=` (l.132) | Filter honoured UNVERIFIED (cf. 09-05 `activities?marketSlug` inert); `canceledOrderIds` is not certification | Sweep re-reads UNFILTERED `/v1/orders/open` and filters by `marketSlug` client-side; exit only on that empty re-read (§5) |
| 5 | Cancel confirm: poll until terminal or 30 s then slug cancel-all + latch (l.124-127) | `HALTED` = no cancels allowed (institutional doc, retail inferred); `EXPIRED` market expires resting orders venue-side | Halt-refused cancel = RETRY-WHEN-OPEN (no escalation, no latch, budget held); venue-initiated EXPIRED/CANCELED is a valid retirement (§6) |
| 6 | P11: `_ORDER_DRIFT_ALLOWED_KEYS` + `unsolicitedCancelReason` "if observed" (l.183) | It is an EXECUTION field, absent on 3/3 Orders; already in `_EXECUTION_DRIFT_ALLOWED_KEYS` (`reports.py:333-340`) | P11 becomes NO CHANGE plus a pin that the Order allowlist stays exactly 4 keys |
| 7 | Order key pins implicitly SDK-20 (`_ORDER_KEYS`, `reports.py:246-269`) | Wire Order has 24 keys (+`outcomeSide, action, manualOrderIndicator, lastTransactTime`) | New additive pin `WIRE_ORDER_KEYS` = `_ORDER_KEYS \| _ORDER_DRIFT_ALLOWED_KEYS` == frozen 24-key literal. The snapshot-equality row (`test_polymarket_us_exec_snapshot_drift.py:138`, `_ORDER_KEYS == SDK Order`) stays UNEDITED at 20 |
| 8 | Fills/state via GET poll; WS rejected (l.78) | `ORDER_SNAPSHOT` best effort, no cursor, new vs SDK | Confirms r3; r3 §10 Q3 closed. WS stays unbuilt; GET is authority |
| 9 | Discovery tolerates non-daily slugs (never examined) | 71 listed = 60 daily + 11 non-daily; `provider.py:256-262` raises when a non-parsing slug's question matches `^(?:Highest\|Lowest) temperature in (.+?) on ` | WP1 step 0 hardening (§7) |
| 10 | Cancel body `{marketSlug}` implicit | Body REQUIRED; wrong-slug behaviour unobservable | Body = exactly `{"marketSlug": <bound slug>}`, slug == the `resting:` row slug (WP4a) |
| 11 | `goodTillTime` format unspecified | Request `string`, response RFC3339 UTC ns; honoured UNVERIFIED | Pure `format_good_till_time`: RFC3339 UTC, whole seconds, floored (never later than `expire_time`); honoured-or-not stays S-6/WP6 |

## 2. Per-WP amended steps (only what changes; r3 line refs)

### WP0 (r3 l.91-94): DONE provisional
- Record completion; r4 consumes the note. Add the two reviewer sign-offs to the evidence file. Output-hygiene incident (discovery §6): every WP6 and any later probe brief carries "extractors emit key names/booleans/signs only, never `repr` a nested object; no tool output of order rows".

### WP1 (l.96-103)
- **Step 0 (blocks the rest): discovery hardening + slug-grammar tolerance audit (§7).**
- Shape (l.97): add "instrument slug satisfies `parse_weather_slug(slug) is not None`" (daily grammar). All other admissions as r3.
- Body (l.99): `RESTING_ORDER_BODY_KEYS` = `ORDER_BODY_KEYS` minus `{synchronousExecution, maxBlockTime}` plus `{goodTillTime}` (9 keys). `format_good_till_time(expire_ns) -> str` pure. `encode_order_body` (`:578`) accepts exactly one of the two sets (equality each).
- Classifier (l.100): DROP the `resting` keyword and `KIND_ACCEPT_RESTING`. Add pure `classify_resting_order_state(order_payload) -> RestingState` in `submit_chain.py` over the parsed GET Order: `NEW | PENDING | FILLED_ANY | TERMINAL_ZERO | UNREADABLE`. `PENDING` = `PENDING_NEW`, `PENDING_RISK`. `FILLED_ANY` = `cumQuantity>0` or `FILLED`/`PARTIALLY_FILLED`. `TERMINAL_ZERO` = `CANCELED|EXPIRED|REJECTED` with `cumQuantity==0`. Anything else (unknown state, missing `state`, key drift) = `UNREADABLE`.
- New pure helpers in `exec/reports.py`: `WIRE_ORDER_KEYS`, `resting_commission_total(order) -> Decimal` (signed, `_require`d, never `abs`), `assert_commission_bps_inert(order) -> BpsDrift | None` (§4).
- RED additions are in §9.

### WP2 (l.105-109): UNCHANGED
- Still exactly two new `RetirementReason` rows. A venue-initiated terminal needs no third: the intent was already retired `ACCEPTED_RESTING`; the terminal is an order event, not an intent event.

### WP3 (l.111-117)
- After `post_order` returns 200 with an id for a resting-shape order and `classify_create_order_outcome` yields anything other than `KIND_ACCEPT_FILL` (it will yield AMBIGUOUS-with-id for an async rest), `_submit_order` awaits `_confirm_resting_by_read(venue_order_id)`: GET `/v1/order/{id}` via `_private_read` every `RESTING_CONFIRM_POLL_S` (0.2, PROVISIONAL; docs say ~100 ms), at most `RESTING_CONFIRM_DEADLINE_S` (5, PROVISIONAL, RulePin). Outcomes per §6; the K=1 latch is held across this bounded window only.
- `_bind_resting_order` (l.114) is unchanged and still has exactly two callers: `_submit_order` on `NEW`, and the with-id resolver on GET `NEW` of a `resting=True` context. The pre-POST resolver context (l.113) is the crash guard for the window between POST and confirm.
- Taker-on-create (l.116) unchanged; a durable create-path fill uses `parse_fill_report` (taker, positive commission) as today.

### WP4 (l.119-143)
- **4a** (l.120): `post_cancel_order` body is exactly `{"marketSlug": slug}`; `post_cancel_all` takes `slugs: Sequence[str]` and refuses (before any byte is signed) an empty sequence, a non-sequence, a duplicate, or any slug failing `parse_weather_slug`. Both bodies re-parsed at the transport boundary (`json.loads(body)["slugs"]` length >= 1).
- **4c** (l.124-127): confirm loop + halt branch + venue-initiated branch per §6. The "unconfirmed -> slug cancel-all" escalation applies ONLY when the market is read as not HALTED; it calls `_post_slug_cancel_all` (§5).
- **4e** (l.131-137): step 1 re-read is unfiltered (§5); step 4 gains a third outcome `RETRY_WHEN_OPEN` (halted slug): WARN not CRITICAL, row kept, intent not swept, sweep retried on the next poll tick while the client lives and at next boot. The arm gate keeps refusing only for UNBOUND orders (own rows stay exempt, 4b).
- 4b, 4d, 4f: unchanged.
- OS-block proof (l.143): add `test_post_cancel_all_with_empty_slugs_never_reaches_the_transport`.

### WP5 (l.145-166)
- Fill commission (l.147): `resting_commission_total(order)` at the FILLED observation (qty is 1 so there is exactly one fill; no delta bookkeeping, YAGNI). Booked to the native `FillReport.commission` with the venue's raw sign; the durable fill record stores `commission_raw` and `commission_sign`. `last_px` as r3. `_assert_taker_fill` untouched (poll path never calls `parse_fill_report`).
- Every poll GET also runs `assert_commission_bps_inert` (§4).
- Envelope check: `abs(commission) <= taker_fee_bound(price, 1)` computed from the pinned fee theta pin (never a new constant); outside = refuse to book, latch `resting_commission_out_of_envelope`, intent/order stay open for operator-free reconciliation (CRITICAL alert).
- Venue-initiated terminal (l.148): §6.
- No-id attribution (l.154-164), prior-process rule (l.161-164): UNCHANGED.

### WP6 (l.198-202)
- Positive-control additions (same automated probe route, same caps, still the bot's job): (i) record the create response shape of the ASYNC rest and the first `GET` while `NEW` (key names only; assert 24 keys; `commissionsBasisPoints`/`makerCommissionsBasisPoints` values); (ii) accept the first own passive fill if it occurs and record `commissionNotionalTotalCollected` sign, then flip `MAKER_COMMISSION_SIGN_VERIFIED` in a reviewed commit; (iii) GTD string accepted and honoured (S-6); (iv) per-order cancel `{marketSlug}` and slug-scoped cancel-all on two slugs (S-2). NEVER send an empty-slug cancel-all, even as a negative control. If no passive fill occurs: `MAKER_COMMISSION_SIGN_VERIFIED` stays False, which is safe (§4).

## 3. Amended pin-row list (r3 §6.7 deltas)

All unchanged r3 rows stand. Each WIDENED row adds named callees/keys only, with a plant test proving the guard still trips.

| Row | Exact set / site (file) | Delta vs r3 | Test file |
|---|---|---|---|
| P1 | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`tests/unit/test_execution_egress_firewall_guard.py:1952`) | r3 list with `self._order_sender.post_cancel_all` REMOVED; ADD `self._post_slug_cancel_all`, `self._confirm_resting_by_read`, `submit_chain.classify_resting_order_state`, `submit_chain.format_good_till_time`, `reports.resting_commission_total`, `reports.assert_commission_bps_inert`; `unmappable_resting_order_reason`/`build_resting_order_body` as r3. Exact names fixed at build and listed in evidence | same + `test_ambig_no_id_firewall_delta.py:532-538` follow-up |
| P3 | `EXEC_QUERY_PERMITTED_CALLEES` (new in r3) | GET-only; ADD `self._read_market_state` (`GET /v1/markets/{slug}/book`, `marketData.state`) iff no existing public-read seam is found at build (open question 3) | firewall guard |
| P4 | `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`) | r3 adds + `_post_slug_cancel_all`, `_confirm_resting_by_read` | firewall guard |
| P5 | `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` (`:4385`) | r3 `+ _cancel_order, _sweep_resting_orders_at_boot` becomes `+ _cancel_order, _post_slug_cancel_all` (the sweep reaches the sender ONLY through the choke point, so it is NOT added) | firewall guard |
| P11 | `_ORDER_DRIFT_ALLOWED_KEYS` (`reports.py:291`) | **NO CHANGE** (was a widening in r3). Pin: stays exactly `{action,lastTransactTime,manualOrderIndicator,outcomeSide}`; an Order carrying `unsolicitedCancelReason` still refuses | `tests/unit/test_polymarket_us_exec_reports.py` |
| P13 | `encode_order_body` equality (`submit_chain.py:578`) | `RESTING_ORDER_BODY_KEYS` is the 9-key async set above, not "IOC keys + goodTillTime" | `test_polymarket_us_resting_order_shape.py` |
| P16 | `test_cage_rule_constants_are_pinned.py` | r3 RulePin rows + `RESTING_CONFIRM_DEADLINE_S`, `RESTING_CONFIRM_POLL_S`, `MAKER_COMMISSION_SIGN_VERIFIED` (False), `OBSERVED_COMMISSION_BPS` ("0") | same |
| P23 | `FROZEN_SOURCE_SHA256["classify_create_order_outcome"]` | **DROPPED**: classifier untouched; add `test_classify_create_order_outcome_source_hash_unchanged` as a non-vacuity anchor | `test_ambig_no_id_firewall_delta.py` |
| P24 | `EXEC_BOOT_SWEEP_PERMITTED_CALLEES` (new) | reads, `self._post_slug_cancel_all`, local store, log. The sweep never references `post_cancel_all` directly | firewall delta |
| **P25 (the one NEW row)** | `EXEC_SLUG_CANCEL_PERMITTED_CALLEES` (new exact set for `_post_slug_cancel_all`) | `self._order_sender.post_cancel_all`, `parse_weather_slug`, `self._store_get`, log; `post_cancel_all` may appear in this ONE body in the whole tree (plant: a second reference in `_cancel_order` or the sweep must fail) | `tests/unit/test_resting_path_firewall_delta.py` |
| W1 (additive, widens nothing) | `WIRE_ORDER_KEYS` literal, 24 keys | frozen to the 24 observed keys; `_ORDER_KEYS` (20) and its snapshot-equality row stay UNEDITED | `test_polymarket_us_exec_reports.py` |

Net vs r3: 1 new WIDENED row (P25), 1 row removed (P23), 1 row downgraded to no-change (P11), 1 row reshaped (P5), 1 key-set definition changed (P13), 1 additive pin (W1). P2, P6-P10, P12, P14, P15, P17-P22 are as r3 (P22 prefix hash re-pins once, as r3).

## 4. Fee-sign design

- **Read sites.** Poll/GET path: `reports.resting_commission_total(order)` reads `Order.commissionNotionalTotalCollected` (`Amount`; `_require`d, absent never defaults, `_parse_amount` as `parse_fill_report` does, banker's quantisation via `_usd_commission`). Create path (taker): unchanged `parse_fill_report`. Neither site reads `commissionsBasisPoints`, `makerCommissionsBasisPoints`, or `feeCoefficient`.
- **Sign.** The raw signed value is the booked `FillReport.commission` and is stored verbatim (`commission_raw`) with `commission_sign in {+,0,-}` in the durable fill record. No `abs`, no sign flip, no maker constant.
- **Recognition gate.** `MAKER_COMMISSION_SIGN_VERIFIED` (module constant, False, RulePin). While False, every analytics consumer (S2/S5 economics, win-rate P&L) treats a negative maker commission as 0 income (conservative), reads `commission_raw` for the audit, and the fill is tagged `maker_fee_sign: unverified`. Flipped only in a reviewed commit citing the WP6 artifact (one observed own passive fill). Cost side (positive) is always counted.
- **Drift pin.** `assert_commission_bps_inert(order) -> BpsDrift | None`: for each of the two bps keys present, require `str` and `Decimal(value) == 0` (equal to `OBSERVED_COMMISSION_BPS`). Returns a `BpsDrift(key, observed_class)` (value-free: class only) instead of raising, so a fill is never lost to a pin.
- **If it changes** (non-zero or non-string): (1) booking is UNCHANGED (still realised commission, never adopt bps); (2) latch `commission_bps_drift` (CRITICAL alert via existing delivery) that refuses NEW resting submits only; cancels, polls, sweep continue; (3) only a reviewed commit (pin edit + evidence) clears it, same discipline as the fee theta drift (class C ruling, never a silent pin edit). Presence-only drift (a third bps key) is already caught by the 24-key refusal.
- **Taker side is untouched:** `_assert_taker_fill` still refuses a maker Execution (non-weakening test kept); the poll path does not route through it, so no relaxation is needed.

## 5. Cancel-all guard (empty slugs = account-wide cancel)

1. **Transport** (`write_transport.post_cancel_all`): `slugs` is a required non-empty sequence of `parse_weather_slug`-valid slugs; the encoded body is re-parsed and `len(body["slugs"]) >= 1` is asserted; failure raises before signing. The body-less form stays removed (r3 4a).
2. **Client choke point** `_post_slug_cancel_all(slug: str)`: a SCALAR slug (an empty or list-typed argument cannot be expressed), refused when `""`, non-daily, or not in the durable ledger (`resting:` rows plus `resting=True` contexts, r3 4e step 1). Builds `[slug]`; the single place in the tree that references `post_cancel_all` (P25).
3. **Call sites.** The strategy path never reaches it (r3 4d). `_cancel_order` escalation passes the order's own bound slug. The sweep iterates ledger slugs; an EMPTY ledger issues zero POSTs. No code path derives a slug list from the market universe or from the open-orders reply.
4. **Sweep exit.** Per slug: read UNFILTERED `GET /v1/orders/open` (record ids), `_post_slug_cancel_all(slug)`, re-read UNFILTERED, and certify the slug empty only if the reply is readable, complete (no further page indicated; if the envelope cannot prove completeness, UNREADABLE) and no order has `marketSlug == slug`. The POST status and `canceledOrderIds` are logged and never consulted. An empty-after re-read on a halted market is still the exit; a non-empty one on a HALTED slug is `RETRY_WHEN_OPEN`; otherwise unreadable/non-empty latches `resting_cancel_unconfirmed` (r3 4e step 4).
5. Unbound open orders on a swept slug are canceled and WARN-logged with the id (r3 / spec §9.18, unchanged).

## 6. Resting-accept and cancel state machine

States are read from `GET /v1/order/{id}` (Order, 24-key wire shape); `classify_resting_order_state` is pure.

| Step | Observation | Action |
|---|---|---|
| Create | async POST 200 + id | arm/ledger as r3; DO NOT accept; start `_confirm_resting_by_read`. 200 without id or non-200 non-4xx-status = existing AMBIGUOUS no-id path (r3 WP5) |
| Confirm | `NEW` | `_bind_resting_order`: store `resting:` row, retire `ACCEPTED_RESTING`, `generate_order_accepted`, K=1 released |
| Confirm | `PENDING` | keep polling until `RESTING_CONFIRM_DEADLINE_S` |
| Confirm | `FILLED_ANY` | existing fill paths; reported with taker fills (cannot tell create-cross from instant maker); WARN `resting_order_crossed` |
| Confirm | `TERMINAL_ZERO` | existing terminal-zero retire (no rest happened); settle once |
| Confirm | `UNREADABLE` / deadline / GET error | stay AMBIGUOUS-with-id (HOLD); the with-id resolver after its floor decides (`NEW` -> same binder). Never ACCEPT on a create response alone, never on `synchronousExecution` echoes |
| Cancel | POST 200 then GET terminal zero | `generate_order_canceled`/`_expired`, settle once, restore iff this-process id (r3 4c) |
| Cancel | POST refused/errored or still `NEW`, market state read HALTED | `RETRY_WHEN_OPEN`: no event, no settle, no restore, no latch, no escalation; retry every poll tick; budget stays held; GTD/venue expiry still bounds it |
| Cancel | POST refused/errored or still `NEW`, market NOT halted | after `CANCEL_CONFIRM_DEADLINE_S`: `_post_slug_cancel_all` escalation, re-read, else latch (r3 4c) |
| Cancel | GET shows fill | fill path; no restore (r3) |
| Venue-initiated | poll shows `CANCELED`/`EXPIRED` with `cumQuantity==0` and no cancel of ours pending | VALID retirement: `generate_order_canceled`/`_expired`, settle once, restore iff this-process id, delete the row, INFO log `venue_initiated_terminal` (`unsolicitedCancelReason` is an Execution field, not on the GET Order; record it only if a later frame supplies it, never required) |
| Venue-initiated | terminal with `cumQuantity>0` | fill path |
| Poll | 3 failed GETs per id | latch `resting_query_unreadable` (r3) |

Market-state read: only to classify a refused cancel (`marketData.state`, `MARKET_STATE_HALTED`). It is advisory: failure to read = treated as NOT halted for escalation purposes but escalation itself cannot make a halted market worse (the refusal repeats), so the worst case is the existing latch (alert, submits refused, cancels continue). Halt auto-cancel is NEVER relied on (institutional-doc inference).

## 7. Discovery hardening (`provider.py:255-262`, `_weather_market_payloads`)

- Today `parsed is None and city_name is not None` raises `VenuePayloadError`. A future monthly market whose question matches `... in <city> on ...` would abort discovery for ALL cities.
- New rule for `parsed is None`: if the slug still carries the DAILY prefix shape `^tc-temp-[a-z]{3}(high|low)-\d{4}-\d{2}-\d{2}-` (a genuine daily-grammar drift: bounds token changed) keep the RAISE (tripwire preserved); otherwise `continue` after recording a sighting. `tc-temp-sjc-dec-lt40`, `trc-yr-*` and every non-`tc-temp` slug never raise.
- Sighting = one structured WARN `non_daily_weather_slug_sighting slug=<..> family=<prefix>` deduped per process, plus a per-cycle count in the existing discovery summary log. No new sidecar schema (the AUD-08 sink is shaped for `city/climate_date`; extending it is scope growth, see open question 2).
- Pins in `tests/unit/test_polymarket_us_discovery.py`: the 11-slug fixture (recorded 71-market payload) discovers the 60 daily markets, raises on none, logs 11 sightings once; a daily-prefix slug with unparseable bounds still raises; a non-weather question never raises; the existing `test_discovery_refuses_weather_city_without_registry_truth` is UNEDITED.
- Tolerance audit (tests only, no code unless red): feed the same 71-market fixture through `fee_drift_evidence_pull` (already filters on `parse_weather_slug`, `:392`), `capture_audit`, `label_run`, `parse_open_orders` (open order on a non-daily slug), and `unmappable_resting_order_reason` (refuses non-daily). Any red = fix at that site in WP1 step 0.

## 8. Nautilus null-hypothesis (per new component; r3 §5 rows stand)

| Component | Native mechanism used | Why nothing new is built |
|---|---|---|
| Async rest + confirm | `LiveExecutionClient._submit_order` + `generate_order_accepted` | Event emission is native; only the GET-confirm trigger is Breezy-side (venue has no native ack stream we trust). Confirm loop is one awaited read inside the existing submit coroutine, not a service |
| `_post_slug_cancel_all`, `post_cancel_order` | `_cancel_order`/`_cancel_all_orders` overrides, `generate_order_cancel_rejected/canceled/expired` | Nautilus base bodies are `NotImplemented`; the venue verb is the only gap. One helper, one transport verb |
| Commission booking | native `FillReport.commission` / `generate_order_filled(commission=...)` | Nautilus carries signed `Money` unchanged; the gap is the venue's sign, closed by evidence (WP6), not by a new fee model. `PolymarketUSFeeModel` untouched |
| `assert_commission_bps_inert` | none (venue wire drift) | Same class as the existing `_*_DRIFT_ALLOWED_KEYS` guards in `reports.py`; no Nautilus counterpart |
| Halt classification | none; Nautilus has no venue-state concept for this venue | One advisory GET, no cache, no state machine of its own |
| Venue-initiated terminal | `generate_order_canceled`/`_expired` (native) | Same events as a solicited cancel; classification is a branch in `_query_order` |
| Discovery hardening | `InstrumentProvider.load_all_async` unchanged | Local `continue` + log in an existing filter loop |
| 24-key wire pin | none | A test constant; no runtime component |

## 9. RED-first test list (names only; files as r3 plus those named)

- **WP1** `test_polymarket_us_resting_order_shape.py`: `test_resting_body_key_set_is_the_nine_key_async_set`, `test_resting_body_omits_synchronous_execution_and_max_block_time`, `test_good_till_time_is_rfc3339_utc_whole_seconds_floored`, `test_good_till_time_never_later_than_expire_time`, `test_resting_shape_refuses_non_daily_weather_slug`, `test_classify_resting_order_state_{new,pending,filled_any,terminal_zero,unreadable_on_unknown_state}`, `test_classify_create_order_outcome_source_hash_unchanged`, `test_ioc_body_key_set_unchanged` (r3 names that assumed `KIND_ACCEPT_RESTING` are deleted, not weakened). `test_polymarket_us_exec_reports.py`: `test_wire_order_keys_literal_is_the_24_observed_keys`, `test_order_drift_allowlist_stays_exactly_four_keys`, `test_order_with_unsolicited_cancel_reason_is_refused`, `test_resting_commission_total_is_signed_and_required`, `test_commission_bps_inert_accepts_string_zero`, `test_commission_bps_drift_flags_nonzero_and_nonstring_value_free`, `test_assert_taker_fill_still_refuses_a_maker_execution`. `test_polymarket_us_discovery.py`: see §7.
- **WP3** `test_polymarket_us_resting_submit.py`: `test_async_create_200_with_id_does_not_accept_until_get_new`, `test_confirm_new_binds_and_retires_accepted_resting`, `test_confirm_pending_polls_until_deadline_then_holds_ambiguous_with_id`, `test_confirm_unreadable_holds_ambiguous_with_id`, `test_confirm_filled_any_is_reported_as_taker`, `test_confirm_terminal_zero_settles_once`, `test_sync_response_echo_never_accepts`, `test_crash_between_post_and_confirm_resolves_via_with_id_resolver`.
- **WP4** `test_polymarket_us_resting_cancel.py`: `test_cancel_body_is_exactly_market_slug_of_the_bound_row`, `test_post_cancel_all_refuses_empty_slugs_in_transport`, `test_post_cancel_all_refuses_non_daily_tc_temp_slug`, `test_post_cancel_all_refuses_missing_slugs_key_after_encode`, `test_slug_cancel_helper_refuses_empty_and_off_ledger_slug`, `test_empty_ledger_sweep_issues_zero_posts`, `test_sweep_exit_requires_empty_unfiltered_reread_not_post_status`, `test_sweep_ignores_canceled_order_ids_echo`, `test_sweep_reread_with_other_slug_orders_does_not_block_exit`, `test_sweep_reread_incomplete_envelope_is_unreadable`, `test_halted_market_cancel_refusal_is_retry_when_open`, `test_retry_when_open_holds_budget_and_emits_no_event`, `test_retry_when_open_does_not_escalate_or_latch`, `test_halted_then_expired_market_retires_via_venue_initiated_terminal`, `test_venue_initiated_cancel_settles_once_and_restores_this_process_only`, `test_unsolicited_cancel_reason_absent_on_get_is_not_required`, `test_market_state_read_failure_never_blocks_cancel`.
- **WP5** `test_polymarket_us_resting_query.py`: `test_poll_fill_books_realised_commission_total_with_venue_sign`, `test_poll_fill_never_reads_bps_or_fee_coefficient`, `test_negative_maker_commission_persisted_raw_and_unrecognised_while_unverified`, `test_positive_maker_commission_always_counted_as_cost`, `test_commission_outside_taker_envelope_refuses_booking_and_latches`, `test_bps_drift_latches_refuses_new_rests_and_keeps_cancels`, `test_bps_drift_does_not_change_booked_commission`.
- **Firewall** `test_resting_path_firewall_delta.py`: `test_post_cancel_all_referenced_only_in_post_slug_cancel_all`, `test_planting_post_cancel_all_in_sweep_fails`, `test_planting_post_cancel_all_in_cancel_order_fails`, `test_sweep_permitted_callees_exclude_post_order_and_post_cancel_order`, `test_read_market_state_is_get_only`.
- **WP6** `test_resting_order_lifecycle.py`: `test_lifecycle_async_rest_halted_cancel_retry_then_venue_expiry`, `test_probe_never_sends_empty_slug_cancel_all`.

## 10. Risk register delta (adds to r3 §8)

| Risk | WP | Guard |
|---|---|---|
| Fee sign inverted / rebate booked as income | 5/6 | raw sign persisted; income recognition gated by `MAKER_COMMISSION_SIGN_VERIFIED`; taker refusal kept; envelope check |
| bps fields start carrying real values | 5 | drift pin, new-submit latch, booking unchanged |
| Account-wide cancel from an empty/derived slug list | 4 | four layers (§5), P25 single choke point, never negative-controlled in WP6 |
| Non-daily `tc-temp-*` slug passes a prefix allowlist | 4/1 | allowlist is `parse_weather_slug`; resting shape refuses non-daily |
| Halted market blocks cancel and the sweep | 4 | RETRY-WHEN-OPEN; arm gate exempts own bound rows; bounded by GTD / venue expiry; no reliance on halt auto-cancel |
| Async create id but GET lags / `PENDING_*` | 3 | bounded confirm, then AMBIGUOUS-with-id (existing resolver); never accept on create |
| Discovery hardening hides real daily drift | 1 | daily-prefix tripwire keeps the raise; sightings counted per cycle |
| Inert `?slugs=` filter certifies a false empty | 4 | unfiltered read + client-side filter |
| 24-key wire drift makes every poll refuse | 5 | fail-closed by design; 3-strike latch; fix = reviewed allowlist row |
| Probe output leaks order rows (discovery §6) | 6 | key-name-only extractors in every brief; no `repr` of nested objects |
| GTD string formatted wrong / ignored | 1/6 | S-6 STOP stays; floor-to-second formatter; native `manage_gtd_expiry` timer remains primary |

## 11. Open questions for peer review (max 5)

1. While `MAKER_COMMISSION_SIGN_VERIFIED` is False, is "book raw, recognise no negative income" enough, or should a NEGATIVE realised maker commission refuse booking and stay AMBIGUOUS until WP6 resolves the sign?
2. Discovery hardening: keep the raise for daily-prefix-shaped slugs that fail to parse (this delta), or skip them too? Is a structured WARN sufficient as the "sighting", or does the AUD-08 sidecar need a non-city schema?
3. Halt detection needs `marketData.state`: reuse an existing exec-side public-read seam if one exists, or add `_read_market_state` (P3 row)? Is refusal-plus-still-`NEW` alone an acceptable proxy?
4. Inline bounded confirm in `_submit_order` (holds K=1 up to 5 s) versus deferring every rest to the with-id resolver after its floor (smaller diff, slower slot release): which does the K=1 / ">= 8 resting" throughput argument prefer?
5. Is the unfiltered `/v1/orders/open` re-read acceptable at expected volume (<= 8 own plus any manual orders), given the envelope's completeness signal is undocumented here?
