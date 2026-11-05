# EDGE-2 — AMBIGUOUS `executions-present` order retired as ZERO_FILL: verify, harden the resolver, remediate if filled (plan r2, 2026-09-27)

Severity: HIGH (settlement correctness, cap-adjacent). Status: PLAN r2, answering round-1 review (architect, security, python: REQUEST_CHANGES; domain: no blockers). Needs the round-2 peer review before any slice is built.
Scope: venue order `CP05MNWMAWP6` (MIA 2026-09-23, YES BUY 1 @ 0.52 IOC, intent `5e50e0d9ee084cd68629b72d1ef81a6b`, client order `O-20260923-172207-L001-MIA-1`, instrument `tc-temp-miahigh-2026-09-23-gte82lt83f.POLYMARKET_US`) and the resolver class it exposed.
**Depends on EDGE-2C** (NO-leg resolver crash, separate standalone plan). r1 slice C is gone from this plan.

---

## r1→r2 changes

| Ruling | Change in r2 | Where |
|---|---|---|
| a (egress guard) | New coroutine `_order_trade_activity` gets exactly one row in `EXEC_RESOLVER_COROUTINES` (guard `:2070`) so its body is scanned; its callees are enumerated as reviewed rows in `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2081`). It is also one row in `EXEC_PERMITTED_COROUTINE_NAMES` (`:1797`, exact-equality with the defined coroutines at `~:2718`), because any new `async def` in `exec/` must be. `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`:1932`) and its exact pin (`:3040`) gain one row, `submit_chain.create_fill_evidence`, for `_submit_order`. Each list widens by exactly the reviewed rows (L-12). AC9 rewritten to name every list. | AC9, §5 slice A/D |
| b (widening mechanism) | r1 was wrong: the real `private_read` closure (`factories.py:794-826`) signs `query_string=""` and never calls `get_authenticated`. r2 rewrites the closure to render the query once, sign it and append it to the URL, mirroring `http.py:_dispatch` (`:179-205`). The renderer is extracted from `PolymarketUSHttpClient._build_query_string` (`http.py:156-177`) into a public module-level `build_query_string` (the method delegates, output byte-identical). New RED tests prove the signed and sent strings are equal and that page 2 is actually requested. | AC10, §4, §5 slice D, §7 |
| c (budget leak) | New AC6b. A cross-process `_resolve_accept_fill` (`booking is None`, `client.py:~2671`) latches a new refusal until respawn; the respawn's boot seed then books the durable fill. Chosen over a new ledger/permit debit primitive; justified in §3. Terminal-zero keeps the `booking is not None` gate (AC6). | AC6, AC6b, §3, slice B |
| d (slice E dating) | Slice E stamps `ts_event` from the trade row's `createTime`, never `now_ns`. E is built only when Step 0 Q2(i) ≥ 1. A Q1-only fill with no trade row goes to the clear tool plus a finding; E is not built for it. | AC8, §5 E, §6 decision table |
| e (activities completeness) | `sortOrder=SORT_ORDER_DESCENDING` passed explicitly (SDK `types/portfolio.py:111`); `complete` uses the **minimum** `createTime` across **all** pages read. Step 0 Q2 must prove ordering and cursor stability; slice D is not built until it does. | AC4(c), §6 Q2/Q2s, §8 |
| f (plumbing) | Picked: a new public `submit_chain.create_fill_evidence(body: bytes)` that parses the raw body itself with the module's own `_parse_json_object`. `_submit_order` passes `response.body`. `classify_create_order_outcome` and `CreateOrderOutcome` stay byte-unchanged (AC2, L-36). | §3 row F, §5 slice A |
| g (Nautilus null hypothesis) | §3 states the decisive reason: Breezy's `generate_fill_reports` (`client.py:3080-3107`) is built from Breezy's own durable fills (circular); `generate_position_status_reports` reads the same positions page (same settled blind spot); nothing native reads venue activities. | §3 |
| h (AC4(e) deadlock) | (e) applies to same-day reads only and compares the venue holding against Breezy's own durable net quantity on the instrument, which equals a create-time snapshot because the account-wide latch forbids any other Breezy order while the intent is OPEN. Clearing-path test added. | AC4(e), §4, §7 |
| i (domain) | The 120 s floor is stated as a borrowed, UNVERIFIED constant (`domain/position_reporting_lag.py:32`) kept as defence in depth. Follow-up EDGE-2-LAG captures a fresh-fill propagation sample. The same-day 09-23 ROI snapshot discrepancy (113¢ `UNEXPLAINED_CAPITAL_FLOW`, later settled to 0¢) is a named residual uncertainty. The create-time pin test uses a synthetic enum fixture and says so (log `:938` lists key names only). | AC4(d), §2.4, §6, §7, §10, §13 |
| j | `_RESOLVER_ZERO_FILL_MIN_AGE_NS` stays local to `exec/client.py`, with the equality pin test against `_REARM_MIN_DELAY_SECS`. AC4(b) and §4 now use one wording for `unknown`. | AC4(b)/(d), §4 |
| (split) | r1 slice C, r1 AC5 and the NO-leg tests move to EDGE-2C. r2 depends on it by ID. | §5, §12 |

---

## 1. Goal and acceptance criteria

Goal state: every with-id AMBIGUOUS intent is retired as zero-fill only on evidence that can tell a fill from a non-fill **at the time the resolver reads it** — including a past-day, already-settled market — and every resolver-path fill is charged against the daily budget before another order can be sent. The MIA 09-23 order is proven to be either unfilled or correctly booked by the bot's own tooling.

1. **AC1 (Step 0 verdict).** A read-only evidence pack exists under `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-23_MIA/`, PRIVATE files 0600 in a 0700 dir. Its README classifies `CP05MNWMAWP6` as exactly one of `FILL`, `PARTIAL_FILL`, `ZERO_FILL_BENIGN`, `CONTRADICTION`, `INCONCLUSIVE` (§6 table), with a passing positive control, and records the Q2s ordering/cursor-stability verdict (`STABLE` / `UNSTABLE` / `INCONCLUSIVE`).
2. **AC2 (create path unchanged).** `classify_create_order_outcome` (`exec/submit_chain.py:1178-1310`) and `CreateOrderOutcome` (`:155-192`) stay byte-unchanged; a source-hash pin makes that structural. `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking["200-id-no-exec"]` stays green. A new pin fixes the MIA 09-23 `executions-present` key tree (synthetic non-fill enum values) as KIND_AMBIGUOUS at create time.
3. **AC3 (create evidence persisted).** On every with-id AMBIGUOUS, the durable resolver context carries a closed-set `createFillEvidence` token: `none`, `fill_type_present`, `fill_type_unmappable`, or `unknown` (legacy blobs and unparseable bodies), plus closed-set execution `type` names and nested-order `state`/`cum` tokens. Names and enum literals only, never a price, quantity or id. A fill-type row that `_durable_execution` skips is named in the log detail, not dropped silently.
4. **AC4 (resolver zero-fill gate).** `_resolve_terminal_zero` is reached only when ALL hold:
   - (a) the GET maps to a terminal non-fill status with `cumQuantity == 0` (the L-36 authority, unchanged);
   - (b) `createFillEvidence ∉ {fill_type_present, fill_type_unmappable}`. `none` and legacy `unknown` are both admissible; **neither short-circuits** — both still require (c), (d) and (e);
   - (c) an activities read with `sortOrder=SORT_ORDER_DESCENDING` is **complete**: it reached `eof`, or the minimum `createTime` across all pages read is below the context's `createdNs`; and it contains **no** `ACTIVITY_TYPE_TRADE` whose `trade.aggressor.id` or `trade.passive.id` equals the venue order id. If Step 0 Q2s is not `STABLE`, slice D is not built (§8);
   - (d) the order is at least `_RESOLVER_ZERO_FILL_MIN_AGE_NS` old. **This 120 s value is borrowed from `_REARM_MIN_DELAY_SECS` and is UNVERIFIED** (`domain/position_reporting_lag.py:32`): it is defence in depth, not a latency-calibrated bound. Pinned equal to the strategy constant;
   - (e) **same-day reads only** (instrument from the session cache, not the past-day loader at `client.py:2251-2291`): the venue holding on (base slug, order leg) does not exceed Breezy's durable net quantity on that instrument. Past-day reads skip (e) (a settled position leaves the page — D2).

   If (c) finds a trade, or (b) carries fill evidence, the intent stays AMBIGUOUS and a CRITICAL `resolver_evidence_contradiction` is raised. If (c) cannot complete (read error, cap hit before `createdNs`), or (d) or (e) fails, it stays AMBIGUOUS. None of these is terminal.
5. **AC5 (moved).** NO-leg correctness is EDGE-2C's AC1-AC4. This plan requires EDGE-2C merged and uses its `base_slug_of` + leg-aware holding.
6. **AC6 (terminal-zero budget).** `restore_live_trading_budget` runs only when the AMBIGUOUS booking was taken in this process (`booking is not None`). A cross-process or next-day terminal-zero writes no `budget_restore/*` marker and credits nothing.
7. **AC6b (cross-process fill budget).** When `_resolve_accept_fill` records a fill with `booking is None`, the client latches `self._refuse(_RESOLVER_FILL_UNBUDGETED)` after the durable writes and before the `_resolver_fill_order_unknown` early return. No order can be sent until respawn; the respawn's `_seed_spend_from_durable_fills` (`client.py:1896`) books the fill into the ledger and permit. Same-process fills (`booking is not None`) are unchanged.
8. **AC7 (L-48 clearing paths).** End-to-end tests drive (i) the verbatim MIA 09-23 shape to RETIRED `STATUS_REPORT_ZERO_FILL_TERMINAL` (past-day loader instrument, positions `{}` eof, GET `EXPIRED qty=1 cum=0 leaves=0`, complete activities with no trade for the id); (ii) the same shape plus a trade row → AMBIGUOUS + CRITICAL; (iii) a same-day prior durable fill on the same slug and leg plus a true zero-fill → RETIRED (AC4(e) cannot wedge).
9. **AC8 (remediation, only if Step 0 Q2(i) ≥ 1).** A durable `fill/CP05MNWMAWP6` record and its `fill_index` entry are written only by bot tooling (slice E), with `ts_event` = the trade row's `createTime`. No hand-edited store row. ROI books it in the residual bucket; PREREG v3 tally n unchanged; ROI 09-23..09-26 net reconciliation stays `OK` within `per_day_tolerance`.
10. **AC9 (gates).** `scripts/ci/run_tests_no_egress.sh` passes in full; `lint-imports` after every slice. Exact-set changes, each a reviewed row with a comment citing this plan, and nothing else:
    - `EXEC_PERMITTED_COROUTINE_NAMES` (`test_execution_egress_firewall_guard.py:1797`): +`_order_trade_activity`.
    - `EXEC_RESOLVER_COROUTINES` (`:2070`): +`_order_trade_activity`.
    - `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2081`): +`self._order_trade_activity` and each callee the guard reports for the new body and the D wiring (expected: `trade_rows_for_order`, `TradeJoin`, `self._durable_net_qty`); `self._refuse` and `self._private_read` are already present.
    - `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`:1932`) **and** its exact pin (`:3040`): +`submit_chain.create_fill_evidence` (clears the banned-word loop at `:3115`: no `read/send/post/request`).
    - `tests/unit/test_exec_refusal_health_surface.py` producer pin (`:162`): +`_resolve_accept_fill#3` (placed after the existing two sites, so no ordinal renumbers).
    - `self._order_sender.post_order` stays absent from every resolver set.
11. **AC10 (signed query transport).** `private_read(path, query=None)` renders the query once with `build_query_string`, signs `sign_headers("GET", path, query_string=qs)` and fetches `path?qs`. With `query=None` the request is byte-identical to today. A test proves page 2 is requested with the page-1 `nextCursor`.

---

## 2. Evidence and root cause (file:line)

### 2.1 What happened
- **Create (09-23 17:22:07.907Z).** `~/.local/share/breezy/logs/breezy-trade-20260923T165046Z.log:938,943`: `create-order classified kind=ambiguous status=200 body_kind=executions-present rpc_code=none body_len=3572 state=absent cum=absent tree={'executions'[2]: {...'type'...,'order': {...'state','cumQuantity','leavesQuantity'...}}, 'id'}`. No `fill_parse_error=` tail (`client.py:4978-4986` appends it only when present). **The line lists key names only, not enum values** — the execution types are unrecoverable locally.
- **Why AMBIGUOUS.** `classify_create_order_outcome` (`submit_chain.py:1239-1271`) books a fill only when `_durable_execution` (`:637-658`) finds a fill-type row with non-empty `order.id`, `lastPx`, `lastShares`, `tradeId`. No `fill_parse_error`, so no fill-type row reached `parse_fill_report`: either both rows were non-fill types, or a fill-type row was skipped silently (`:647-657` `continue` with no diagnostic; L-37 class).
- **Why not create-time ZERO_FILL.** The branch (`:1275-1294`) requires `executions == []`; `_terminal_state`/`_cum_quantity` (`:609-634`) never read `executions[i].order`.
- **Resolver 09-23.** 285 GETs failed on `leavesQuantity != quantity - cumQuantity`; fixed by `df66327` (`reports.py:1181-1192`). Pinned shape `ORDER_STATE_EXPIRED qty=1 cum=0 leaves=0` (`tests/unit/test_polymarket_us_exec_reports.py:1209-1226`).
- **Retirement (09-24 20:15:51.560Z).** `breezy-trade-20260924T201520Z.log:322` `resolver: retired intent 5e50e0d9… (STATUS_REPORT_ZERO_FILL_TERMINAL)`. Durable: `intent/history` RETIRED; `budget_restore/CP05MNWMAWP6 = 1`; no `fill/CP05MNWMAWP6`; no trial record; a stale `inflight/MIA/2026-09-23 {"state":"open"}` remains.

### 2.2 How the resolver decided (`exec/client.py:2043-2461`)
- `is_terminal_zero` = status in `_RESOLVER_TERMINAL_STATUSES` and `filled_qty == 0` (`:2389-2391`). Correct; the L-36 authority.
- Corroboration `_resolver_long_position_state(positions, slug)` (`:1317-1336`, called `:2419-2420`) returns `False` when the slug is absent. On 09-24 the instrument came from the past-day loader and the market had settled, so "absent" proved nothing. **D2 (HIGH):** for a settled market the second leg is vacuous.

### 2.3 Further defects
- **D1 (HIGH).** The resolver never reads the create body's own evidence (`createDetail`/`fillParseError` persisted at `client.py:1057,1080`, never consulted).
- **D3 (MED, cap-adjacent).** `_resolve_terminal_zero` restores the permit (`:2533-2538`) even when `booking is None`; the ledger true-up above it is already same-process-only. `budget_restore/CP05MNWMAWP6` proves it fired on 09-24 for a 09-23 order. Clamped at the issued budget (`safety.py:906-909`), but it re-grants a slot the current permit never spent.
- **D4 (MED, L-37).** Diagnostics log key names only; `_durable_execution` skips fill rows silently.
- **D5 (HIGH, NO leg).** Moved to EDGE-2C.
- **D6 (HIGH, cap; found in round 1).** `_resolve_accept_fill` with `booking is None` (`client.py:~2671-2673`) trues up nothing, and `seed_permit_budget_from_prior_spend` applies once per permit (`safety.py:846`, `_SEEDED_PERMIT_BUDGETS`), as does the ledger's `seed_spent`. A fill resolved after boot for an order booked by a prior process is therefore charged to **neither** the ledger nor the permit for the rest of this process — the daily-budget cap is under-counted. Today that path needs `long_state is True`; slice D's "fill ∧ (held ∨ trade-for-id)" makes it newly reachable (settled markets, exits). AC6b closes it.
- **D7 (MED, exits; noted in EDGE-2C).** A fully filled exit leaves no holding, so a GET fill with `held is False` disagrees forever. Slice D's trade-for-id alternative resolves it.

### 2.4 Local corroboration already available (no venue call)
- `~/.local/share/breezy/derived/PRIVATE_portfolio_roi_2026-09-26.json`: `daily_reconciliation` 2026-09-23 and 2026-09-24 `OK`, `magnitude_cents` 0, both `provisional: True`; `per_day_tolerance` 1¢ per fill (`scripts/analysis/portfolio_roi_report.py:1390-1397`). An unbooked 0.52 debit plus fee would breach it.
- **Residual uncertainty (named).** The same-day 09-23 ROI snapshot showed a 113¢ `UNEXPLAINED_CAPITAL_FLOW` that later settled to 0¢. The later `OK` is the settled reading; the transient is not explained by this plan and Step 0's L1 row must record both readings, not only the latest.
- **Prior:** `ZERO_FILL_BENIGN` strongly favoured; still a book-vs-balance identity, not an order-level proof.
- Captured venue shape (L-17), `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`: TRADE rows carry `trade.aggressor.id`/`trade.passive.id`, `marketSlug`, `qtyDecimal`, `price`, `cost`, `createTime`. `activities_slug.json` (`marketSlug=` query) returned only ACCOUNT_DEPOSIT/REFERRAL_BONUS rows: **the `marketSlug` filter is not a trade filter; page unfiltered and filter client-side.**

### 2.5 Can an `executions-present` response ever end terminal-zero-fill?
- **At create time: no, and it stays no** (R-7 item 5, GL-1 ruling, L-32, L-36).
- **Via the resolver: yes, legitimately,** only if the create body carries no fill evidence (D1) and the corroboration can distinguish a fill at read time (D2). Neither held on 09-24.

---

## 3. Options and trade-offs

| # | Option | Verdict | Why |
|---|---|---|---|
| X | Reclassify `executions-present` non-fill + nested terminal cum 0 as create-time ZERO_FILL | **REJECT** | Changes a pinned create-path classification (GL-1/L-32/L-36); fail-open if wrong. |
| A | Positions-only corroboration; skip past-day (stay AMBIGUOUS) | Reject | Past-day AMBIGUOUS never clears: the 09-23/24 L-48 deadlock. |
| B | Activities TRADE join by order id, mandatory for every terminal-zero; positions a same-day leg | **CHOSEN** | Exact join key; valid before and after settlement; AMBIGUOUS is rare (4 with-id in 22 days). One rule (KISS). |
| B′ | Activities only on the past-day branch | Reject | Two regimes; same-day positions also lag (120 s UNVERIFIED). |
| C | `POSITION_RESOLUTION.beforePosition.qtyBought` | Step 0 cross-check only | Slug-level, confounded by other fills. |
| F1 | **`create_fill_evidence(body: bytes)`, public in `submit_chain`, parsing internally with `_parse_json_object`; `_submit_order` passes `response.body`** | **CHOSEN** | `classify_create_order_outcome` and `CreateOrderOutcome` stay byte-unchanged (L-36, AC2). Cost: a second `json.loads` of a ≤ few-KB body on the AMBIGUOUS-with-id branch only. |
| F2 | New public parse function called by both `classify_…` and `_submit_order` | Reject | Edits `classify_create_order_outcome`'s body; breaks the AC2 byte pin. |
| F3 | Attach `create_fill_evidence` to `CreateOrderOutcome` | Reject | `classify_…` would have to populate it; same break as F2. |
| G1 | **Cross-process fill: latch a refusal until respawn** | **CHOSEN** | Fail-closed and reuses two proven mechanisms: `_refuse` (already on the resolver allowlist, degrades the component) and the boot seed, which re-walks durable fills and charges both ledger and permit. The cap cannot be exceeded because no order can be sent while under-counted. Cost: trading pauses until the next respawn (daily 16:50Z or a mid-day relaunch), on an event that has occurred once in 22 days. Seed buckets by `ts_event` = discovery time, so a same-day respawn books it; a post-midnight respawn starts a new budget day, which is correct. |
| G2 | New ledger + permit debit primitive (`charge_cross_process_fill`) | Reject | A new mutation surface on the permit registry, whose seed is deliberately once-per-permit (`safety.py:846`); duplicates the boot seed; needs its own security review and cap tests. YAGNI for a rare event. |
| R-A | Remediation CLI `breezy-attest-late-fill` | **CHOSEN, conditional on Q2(i) ≥ 1** | Bot books; nobody hand-edits. |
| R-B | Re-open the RETIRED intent | Reject | No sanctioned un-retire; `retire` not idempotent. |
| R-C | Boot sweep re-verifying past zero-fill retirements | Defer | Forward path fixed by B. |

**Nautilus null hypothesis (L-1) — decisive reason.** The question is "did this venue order trade?", answered from venue-side trade records. Nautilus's reconciliation surface cannot answer it here:
- `generate_fill_reports` (`client.py:3080-3107`) is Breezy's own implementation, built from Breezy's **own durable fills** (`_durable_reconciliation_pass`). Asking it whether an unbooked order filled is circular: it can only return what Breezy already recorded.
- `generate_position_status_reports` (`client.py:3109`) reads the same `PORTFOLIO_POSITIONS_PATH` page, so it has the same settled-market blind spot as D2.
- `generate_order_status_report` collapses failures into `None` (GL-4); the native in-flight poller is disabled (`runtime/node_config.py:689-712`); native reconciliation cannot join this venue's orders (no client-order-id, L-36).
- **Nothing native reads venue activities.** B extends the existing Breezy resolver coroutine; no parallel mechanism.

---

## 4. Architecture and data flow

```
create POST ─► classify_create_order_outcome (UNCHANGED)
                └─ AMBIGUOUS with id ─► [NEW] submit_chain.create_fill_evidence(response.body)  (pure, closed-set)
                                        └─► _note_ambiguous_open(..., create_fill_evidence=…) ─► AmbiguousResolverContext
                                            (+createFillEvidence; absent in old blobs → "unknown")
resolver pass (per OPEN intent with context):
  instrument (cache = same-day | past-day loader)
  GET /v1/order/{id} ─► parse_order_status_report
     PARTIALLY_FILLED / non-terminal ─► stay AMBIGUOUS (unchanged)
     terminal / fill ─► positions read; EDGE-2C leg-aware held(base_slug, leg)
                        [NEW] await self._order_trade_activity(venue_order_id, created_ns) -> TradeJoin | None
                              pages private_read(PORTFOLIO_ACTIVITIES_PATH,
                                   query={limit:100, sortOrder:SORT_ORDER_DESCENDING[, cursor]})
                              until eof, or min(createTime over ALL pages) < created_ns, or 20 pages
     zero-fill   = GET terminal ∧ cum==0 ∧ createFillEvidence ∉ {fill_type_present, fill_type_unmappable}
                   ∧ join.complete ∧ join.trade_count==0 ∧ age ≥ _RESOLVER_ZERO_FILL_MIN_AGE_NS
                   ∧ (past-day ∨ venue_held_qty(leg) ≤ self._durable_net_qty(instrument))
         └─► _resolve_terminal_zero: retire; ledger true-up iff booking; [CHANGED] permit restore iff booking
     fill        = GET fill ∧ (held ∨ (join.complete ∧ join.trade_count ≥ 1))
         └─► _resolve_accept_fill: record_fill; true-up iff booking; retire; unrestore;
             [NEW] booking is None ─► self._refuse(_RESOLVER_FILL_UNBUDGETED)   (AC6b)
     contradiction = GET zero ∧ (join.trade_count ≥ 1 ∨ createFillEvidence ∈ {fill_type_present, fill_type_unmappable})
         └─► stay AMBIGUOUS + CRITICAL resolver_evidence_contradiction (health-surface dict, same pattern as open_intent_stale, client.py:2227-2250)
```

`createFillEvidence` wording (one rule, used in AC4(b) and here): `none` and `unknown` are admissible and never sufficient on their own; `fill_type_present` and `fill_type_unmappable` block zero-fill and raise the contradiction.

**AC4(e) baseline.** `self._durable_net_qty(instrument_id) -> Decimal` is a sync, read-only local helper: it walks the instrument's `FILL_INDEX_KEY_PREFIX` index (the same walk `_seed_spend_from_durable_fills` uses) and sums `cumulative_qty`, entries positive and exits negative per `DurableFillRecord.order_side`. While the intent is OPEN the account-wide latch forbids any other Breezy order, so this set cannot change between create and resolution: it **is** the create-time snapshot, without a new venue read on the order path. Any read failure returns undetermined → stay AMBIGUOUS. Like `self._resolver_fill_order_unknown` (guard `:2149-2157`), it is a read-only classifier listed as a callee only, not as a scanned resolver action site.

**Clearing paths (L-48).** The latch is the account-wide OPEN intent, cleared by the resolver in the node process on the first pass where the zero-fill or fill rule holds.
- A prior same-day holding is explained by the durable baseline, so it cannot wedge a true zero-fill (AC7(iii)).
- A contradiction clears on the next pass whose join yields the trade (→ fill), or at the day boundary (past-day reads skip (e)); otherwise `breezy-clear-submit-intent` with an attestation.
- An AC6b refusal clears on respawn, which re-seeds the budget from the durable fill.

**Activities transport (AC10).** `PrivateRead.__call__` (`exec/client.py:733-757`) gains `query: Mapping[str, object] | None = None`. The factory closure (`factories.py:794-826`) becomes:
`qs = build_query_string(query)`; `headers = signer.sign_headers("GET", path, query_string=qs)`; `url = f"{base}{path}" + (f"?{qs}" if qs else "")`; `transport.get(url, headers=headers, quota_key=PRIVATE_READ_QUOTA_KEY)`; non-2xx → `PrivateReadRefused(status, path, body)`; decode with `decode_private_payload` (Decimal-safe; unchanged). One rendered string feeds both signer and URL, the invariant `http.py`'s module docstring (`:17-22`) states. `build_query_string` is lifted verbatim from `PolymarketUSHttpClient._build_query_string` (`http.py:156-177`); the method delegates to it. `PORTFOLIO_ACTIVITIES_PATH` is imported from `account_activity`, never restated.

---

## 5. File-by-file plan

| Slice | File | Change | Deps |
|---|---|---|---|
| 0 | `scripts/venue/edge2_ambiguous_order_probe.py` (new, read-only) | Step-0 GETs (§6) via `PolymarketUSHttpClient.get_authenticated` + `QUOTA_KEY_PORTFOLIO`, constructed as in `polymarket_us_capital_flow_pull.py`. Never imports `exec/` or permit functions; never reads `/v1/account/balances`; 0600 files; ids redacted as in the 09-05 `probe.py.txt`. | none |
| A | `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | New public `create_fill_evidence(body: bytes) -> CreateFillEvidence` (frozen dataclass: `token`, `exec_types: tuple[str, ...]` from SDK `ExecutionType` literals, else `other`; `order_state`/`order_cum` tokens from the LAST `executions[i].order`: `0/nonzero/absent/unparseable`; `skips: tuple[str, ...]` naming why a fill-type row would be skipped). Parses with `_parse_json_object`; unparseable → token `unknown`. **`classify_create_order_outcome`, `_durable_execution`, `CreateOrderOutcome` byte-unchanged.** | — |
| A | `src/breezy/adapters/polymarket_us/exec/client.py` | `_submit_order` AMBIGUOUS-with-id branch (`:4988-5003`): `evidence = submit_chain.create_fill_evidence(response.body)`; pass to `_note_ambiguous_open` (`:4493`); append `exec_types=`/`order_state=`/`order_cum=`/`skips=` to the existing detail line. `AmbiguousResolverContext` (`:1028`) gains `createFillEvidence`; `from_bytes` defaults absent → `unknown`. | — |
| A | `tests/unit/test_execution_egress_firewall_guard.py` | `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`:1932`) and exact pin (`:3040`): +`submit_chain.create_fill_evidence`, one reviewed row each with a comment. | A |
| B | `src/breezy/adapters/polymarket_us/exec/client.py` | `_resolve_terminal_zero` (`:2533`): permit restore guarded by `booking is not None`; INFO `resolver: cross-process terminal-zero; permit restore skipped`. `_resolve_accept_fill`: after the unrestore block, before `_resolver_fill_order_unknown`, `if booking is None: self._refuse(_RESOLVER_FILL_UNBUDGETED)` with an ERROR naming the intent (no amount). New module constant `_RESOLVER_FILL_UNBUDGETED`. | — |
| B | `tests/unit/test_exec_refusal_health_surface.py` | Producer pin (`:162`): +`_resolve_accept_fill#3` with its classification row. | B |
| D | `src/breezy/adapters/polymarket_us/http.py` | Lift `_build_query_string`'s body into public module-level `build_query_string(query)`; the method delegates. Output byte-identical (existing http tests pin it). | — |
| D | `src/breezy/adapters/polymarket_us/factories.py:794-826` and `exec/client.py:733-757` (`PrivateRead`) | Closure rewritten per §4; protocol gains `query`; both docstrings updated (the "no query parameter, by construction" rationale is replaced by "one rendered string signed and sent"). `PrivateReadRefused` obligation unchanged. | — |
| D | `src/breezy/adapters/polymarket_us/account_activity.py` | New pure `trade_rows_for_order(page, venue_order_id) -> tuple[TradeActivityRef, ...]` (qty from `qtyDecimal`, `create_ts_ns`, `is_aggressor`; never amounts) and pure `page_min_create_ts_ns(page)`. TRADE rows stay excluded from `parse_external_flows`. | — |
| D | `src/breezy/adapters/polymarket_us/exec/client.py` | New coroutine `_order_trade_activity(venue_order_id, created_ns) -> TradeJoin \| None` (`TradeJoin(complete, trade_count, qty, last_trade_ts_ns)`); `_RESOLVER_ACTIVITY_MAX_PAGES = 20`; `_RESOLVER_ACTIVITY_SORT_ORDER = "SORT_ORDER_DESCENDING"`; tracks the running minimum `createTime` over all pages. New sync `_durable_net_qty`. New local constant `_RESOLVER_ZERO_FILL_MIN_AGE_NS = 120 * 1_000_000_000` (no strategy import; adapters sit below strategy). AC4 wiring, fill alternative, contradiction CRITICAL; boot INFO line `resolver: zero-fill corroboration=activities_v1 min_age_s=120 legs=yes,no`. | A, EDGE-2C, Step 0 Q2s = STABLE |
| D | `tests/unit/test_execution_egress_firewall_guard.py` | `EXEC_PERMITTED_COROUTINE_NAMES` +`_order_trade_activity`; `EXEC_RESOLVER_COROUTINES` +`_order_trade_activity`; `EXEC_RESOLVER_PERMITTED_CALLEES` +`self._order_trade_activity` and the new body's callees as reported by the guard run unmodified (expected `trade_rows_for_order`, `page_min_create_ts_ns`, `TradeJoin`, `self._durable_net_qty`), one reviewed, commented row each. | D |
| E (only if Q2(i) ≥ 1) | `src/breezy/runtime/attest_late_fill_cli.py` + `pyproject.toml` `breezy-attest-late-fill` | Mirrors `clear_submit_intent_cli.py`: refuses while the node holds the intent flock; `--venue-order-id`, `--evidence-dir`. Re-does GET + activities join read-only; refuses unless `trade_count ≥ 1`. Builds `DurableFillRecord` as `_resolve_accept_fill` does except **`ts_event` = the last matched trade row's `createTime`** (never `now_ns`) and fee from `commissionNotionalCollected` when present (`feeSource=RECORDED`, R-1), else `fee_reconciled False`. Writes via `record_fill` (fill + fill_index); idempotent on an existing `fill/<id>`. No latch, permit or trial row: residual by PREREG. | slice D reader |
| — | `docs/core/LESSONS.md` | Lesson (via the lessons skill, dedup first): "A corroborating read is only evidence if it can distinguish the outcome at the time it is read" (settled positions, create-body evidence, cross-process budget). | after merge |
| — | `docs/core/PROGRESS.md` | Rows `EDGE-2-LIVE` (first post-re-arm AMBIGUOUS) and `EDGE-2-LAG` (§6 follow-up). | after merge |

---

## 6. Step 0: read-only verification (before slice D or E is built)

One `systemd-run --user` oneshot, any hour, GETs only on `QUOTA_KEY_PORTFOLIO`/`QUOTA_KEY_BOOK`. Nothing touches the node, store or latch. Interpreter `/home/jon/breezy/.venv/bin/python`, `PYTHONPATH=/home/jon/breezy/src`. Every response saved raw with status and attempt metadata (09-05 `request_log.json` pattern). Wait on `ActiveState ∉ {active, activating}`.

| Tag | Call | Answers |
|---|---|---|
| Q1 `order_by_id` | `get_authenticated("/v1/order/CP05MNWMAWP6")` (`exec/endpoints.py:128`), parsed with `reports.parse_order_status_report`. Record `state, quantity, cumQuantity, leavesQuantity, avgPx, intent, outcomeSide, createTime, lastTransactTime`. | The L-36 authority today. |
| Q2 `activities_desc` | `get_authenticated(PORTFOLIO_ACTIVITIES_PATH, query={"limit":100, "sortOrder":"SORT_ORDER_DESCENDING"[, "cursor":c]})`, no `marketSlug`. Page to `eof` (cap 20) or until min `createTime` over all pages < `2026-09-23T17:21:00Z`. Filters: (i) TRADE with `aggressor.id` or `passive.id` == `CP05MNWMAWP6`; (ii) any TRADE on the slug; (iii) POSITION_RESOLUTION on the slug. | Order-level fill truth. |
| Q2s `ordering_and_cursor_stability` | (1) Assert `createTime` non-increasing across the concatenated Q2 pages. (2) Repeat Q2 ≥ 5 min later; assert the id sequence over the overlapping window is identical, with no duplicate and no gap across page boundaries. (3) One `SORT_ORDER_ASCENDING` traversal over the same window; assert it is the exact reverse. Verdict `STABLE` only if all three hold. | Whether `complete` in AC4(c) can be trusted. **Slice D is not built unless `STABLE`**; otherwise D is re-planned (complete only at `eof`). |
| Q2b `activities_types_trade` | Q2 plus `types=ACTIVITY_TYPE_TRADE`. | Cross-check only; not relied on. |
| Q3 `positions_market` | `/v1/portfolio/positions` with `market=<slug>`, and unfiltered to eof. | Measures the D2 premise. |
| Q4 `orders_open_slug` | `/v1/orders/open` with `slugs=<slug>`. | Must be empty. |
| Q5 `market_settlement` | Public market-settlement endpoint for the slug. | Payoff, for a FILL P&L only. |
| PC `positive_control` | Q1 + Q2 join for a known create-path fill inside the paged window (e.g. `CNC3HJD66WP9` or `CMSN9WPWWWPB`). | Join must find ≥ 1 TRADE, else Q2 is void. |
| L1 (local) | ROI rows for 09-23/24 (labels and `magnitude_cents` only) from the latest `PRIVATE_portfolio_roi_*.json` **and** the same-day 09-23 snapshot (records the 113¢ `UNEXPLAINED_CAPITAL_FLOW` transient); store keys `fill/CP05MNWMAWP6` (absent), `intent/history/5e50e0d9…` (RETIRED). | Book-vs-balance identity, with its transient. |

**Decision table (exactly one verdict):**

| Verdict | Condition | Action |
|---|---|---|
| `FILL` | Q2(i) qty sums to 1 (with PC passed), or Q1 `cum == quantity` / `state=FILLED`. | Q2(i) ≥ 1 → build slice E. Q1-only (no Q2(i) row) → not E: finding + `breezy-clear-submit-intent`-class operator path with attestation; coordinator ruling. |
| `PARTIAL_FILL` | Q2(i) sums to (0,1), or Q1 `0 < cum < quantity`. | As FILL. |
| `ZERO_FILL_BENIGN` | Q1 terminal `cum=0`, Q2 complete with zero Q2(i) rows, Q2s `STABLE`, PC passed, Q2(iii) absent or zero `beforePosition`, L1 `OK`. | No remediation. |
| `CONTRADICTION` | Q1 zero but Q2(i) ≥ 1; or Q1 fill with Q2 complete, PC passed and no Q2(i) row. | First case → slice E (trade rows exist). Second case → finding + clear tool, no E. Both: record that the GET is not authoritative. |
| `INCONCLUSIVE` | Any non-2xx, Q2 incomplete within the cap, PC failed. | Re-run; never conclude from partial pages. |

**Follow-up EDGE-2-LAG (cannot run in Step 0: no fresh fill exists while the A1 halt is SET).** On the first post-re-arm create-path fill(s), a read-only oneshot polls activities and positions every 5 s for 10 min and records, per fill, the delay from the trade's `createTime` to its first appearance on each page. Until n ≥ 1 sample exists, the 120 s floor stays labelled UNVERIFIED; any recalibration is a separate plan.

Never print or commit balances, account ids, key ids, cap values.

---

## 7. Test strategy (RED first)

**Slice A** (`tests/unit/test_polymarket_us_submit_order_chain.py`; existing pins untouched):
- `test_mia_0923_executions_present_nonfill_tree_stays_ambiguous_at_create` — key tree verbatim from log `:938`; **enum values `[EXECUTION_TYPE_NEW, EXECUTION_TYPE_EXPIRED]` and nested state are a synthetic fixture** (the log lists key names only), stated in the test docstring.
- `test_create_fill_evidence_none_for_nonfill_lifecycle_rows`
- `test_create_fill_evidence_fill_type_present_for_mapped_fill`
- `test_create_fill_evidence_unmappable_names_the_skipped_field`
- `test_create_fill_evidence_unknown_type_renders_other_never_value` (adversarial dict/list/long-string `type`)
- `test_create_fill_evidence_unparseable_body_is_unknown`
- `test_create_fill_evidence_reads_nested_order_state_and_cum_tokens`
- `test_classify_create_order_outcome_and_outcome_type_are_byte_unchanged` — source-hash pin on both.
- (`test_current_rung_hold_ambiguous_resolver.py`) `test_resolver_context_round_trips_create_fill_evidence`; `test_legacy_resolver_context_without_field_decodes_as_unknown`; `test_submit_order_passes_response_body_evidence_to_note_ambiguous_open`.

**Slice B:**
- `test_cross_process_terminal_zero_does_not_restore_current_permit` (no `budget_restore/*`, permit unchanged)
- `test_same_process_terminal_zero_still_restores_permit`
- `test_cross_process_accept_fill_latches_unbudgeted_refusal` — RED today: `booking=None`, fill recorded, no refusal. GREEN: `_RESOLVER_FILL_UNBUDGETED` in `trading_refusals`, component degraded, next `_submit_order` denied.
- `test_same_process_accept_fill_does_not_refuse`
- `test_respawn_seed_books_the_cross_process_fill_into_ledger_and_permit` — new client over the same store: `_seed_spend_from_durable_fills` includes the record; permit remaining reduced.
- `test_unbudgeted_refusal_precedes_the_order_unknown_early_return`

**Slice D:**
- `test_private_read_signs_and_sends_the_same_query_string` (factory tests; fake signer and transport record `query_string` and URL)
- `test_private_read_without_query_is_byte_identical_to_today`
- `test_build_query_string_matches_http_client_rendering` (`test_polymarket_us_http.py`)
- `test_order_trade_activity_requests_page_two_with_next_cursor` — RED: two-page fake; asserts the second URL carries `cursor=<nextCursor>` and `sortOrder=SORT_ORDER_DESCENDING`.
- `test_order_trade_activity_complete_uses_min_create_time_across_all_pages` — page 1 older than page 2 (out-of-order); completeness must use the global minimum.
- `test_terminal_zero_requires_complete_activities_with_no_trade_for_order`
- `test_trade_activity_for_order_id_blocks_zero_fill_and_raises_contradiction_critical`
- `test_create_fill_evidence_fill_type_blocks_zero_fill`
- `test_unknown_create_fill_evidence_still_requires_activities`
- `test_activities_read_failure_stays_ambiguous_and_counts_backoff`
- `test_activities_cap_before_created_ns_is_incomplete_and_stays_ambiguous`
- `test_zero_fill_before_min_age_stays_ambiguous`
- `test_min_age_constant_equals_strategy_rearm_floor` — `_RESOLVER_ZERO_FILL_MIN_AGE_NS == _REARM_MIN_DELAY_SECS * 1_000_000_000` (test imports both; production does not).
- `test_same_day_prior_durable_holding_does_not_block_true_zero_fill` — AC7(iii) clearing path.
- `test_same_day_unexplained_holding_blocks_zero_fill`
- `test_past_day_read_skips_holding_leg`
- `test_durable_net_qty_read_failure_stays_ambiguous`
- `test_fill_resolves_on_trade_join_when_holding_absent` (settled market / exit, D7)
- `test_mia_0923_past_day_shape_retires_zero_fill_with_empty_trade_join` — AC7(i).
- `test_mia_0923_past_day_shape_with_trade_row_stays_ambiguous` — AC7(ii); RED today.
- (`test_account_activity_parse.py`) `test_trade_rows_for_order_joins_aggressor_and_passive_ids`; `test_trade_rows_for_order_ignores_marketslug_match_without_id_match`; `test_page_min_create_ts_ns_handles_missing_and_malformed_times` (fixtures synthetic-from-captured).
- Egress guard and refusal pin pass with only the AC9 rows.

**Slice E (conditional):** `test_attest_late_fill_refuses_while_node_holds_flock`; `test_attest_late_fill_refuses_without_trade_join`; `test_attest_late_fill_stamps_ts_event_from_trade_create_time`; `test_attest_late_fill_writes_fill_and_index_idempotently`; `test_attested_fill_is_residual_and_leaves_tally_n_unchanged`; `test_roi_report_books_attested_fill_in_residual_bucket`.

Run: focused files, then `scripts/ci/run_tests_no_egress.sh` (basetemp under `/home/jon/.cache/breezy-gate/`, `-p LimitNOFILE=524288` when unit-launched), then `lint-imports`; read exit codes.

---

## 8. Execution order and parallelism

1. **EDGE-2C** (own plan) — merged first; D depends on it.
2. **In parallel:** Step 0 (slice 0), slice A, slice B. A and B touch disjoint `client.py` regions (`:4988-5003`/`:1028` vs `:2533`/`_resolve_accept_fill`); B merges first (smallest), A rebases.
3. **Slice D** only after A and EDGE-2C are merged **and** Step 0 records Q2s `STABLE` and PC passed. If Q2s is not `STABLE`, stop and re-plan D.
4. **Slice E** only if Step 0 Q2(i) ≥ 1. Needs D's pure `trade_rows_for_order` (can be cherry-picked); not D's wiring.
5. Implementer per slice: `tdd-guide` seeded with python-testing. Reviewers: `python-reviewer`, `silent-failure-hunter`; `security-reviewer` for A/D guard rows, the `private_read` rewrite and B's refusal. Worktrees use `PYTHONPATH=<wt>/src`, `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`. Never `uv`/`pip`/`git stash`. Full gate after every merge.

---

## 9. Deploy and verification

- Node code (A, B, D) goes live on the next node respawn (16:50Z daily); never kill the live node. Supervisor untouched.
- Liveness: node log FILE at `_connect` shows `resolver: zero-fill corroboration=activities_v1 min_age_s=120 legs=yes,no` (slice D).
- Behavioural proof is deferred to the first AMBIGUOUS after re-arm (A1 halt SET → no orders). Until then the evidence is the AC7 end-to-end tests. PROGRESS rows `EDGE-2-LIVE` and `EDGE-2-LAG`.
- Slice E (if built): one `systemd-run --user` oneshot in the flock-free window (16:40–16:50Z) or with the node down; wait on `ActiveState ∉ {active, activating}`; verify `fill/CP05MNWMAWP6` + fill_index; next 17:40Z ROI shows it in `n_residual` with net `OK`; 17:20Z v4 tally n unchanged.

---

## 10. Risk register

| Risk | L | I | Mitigation |
|---|---|---|---|
| Activities ordering or cursor unstable → false "no trade" | L | H | Q2s must be `STABLE` before D is built; completeness uses the global min `createTime`; PC measures the join; incomplete fails closed. |
| Activities lag a fill | M | H | GET + create-body evidence + same-day positions + the 120 s floor; any contrary signal blocks zero-fill. **The 120 s floor is borrowed and UNVERIFIED** (`domain/position_reporting_lag.py:32`), not a calibrated bound; EDGE-2-LAG measures it on the first live fills. |
| 09-23 ROI transient (113¢ `UNEXPLAINED_CAPITAL_FLOW` same day, later 0¢) hides something | L | M | Named residual uncertainty; L1 records both readings; Step 0 Q1/Q2 decide at order level regardless. |
| `private_read` rewrite desynchronises signed and sent query | L | CRIT | One rendered string for both (§4); tests prove equality and byte-identity for `query=None`; security review. GET-only; no write path. |
| AC6b refusal pauses trading until respawn | L | M | Rare event; fail-closed by design; respawn re-seeds. Chosen over a new cap primitive (§3 G2). |
| AC4(e) baseline wrong (exit sign, partial) | L | M | `_durable_net_qty` tests cover entries, exits and read failure; failure → undetermined, never retire. |
| Resolver coroutine dies on a new exception | M | H | EDGE-2C's per-intent guard pattern extends to every new call (D wraps join/baseline in log-count-continue). |
| Paging raises portfolio-quota pressure | L | M | ≤ 20 pages per pass, only while an intent is OPEN; backoff reuses `_resolver_consecutive_failures`. |
| Step 0 finds a fill without a trade row (Q1-only) | L | M | No E; finding + clear tool + coordinator ruling (§6). |
| Old contexts lack `createFillEvidence` | — | L | Decoded `unknown`; activities still required. |

---

## 11. LESSONS and invariant compliance

- **L-32 / L-36 / GL-1 / R-7 item 5:** create classifier and outcome type byte-unchanged and pinned; GET stays the authority; new legs only tighten zero-fill.
- **L-37:** skipped fill rows surfaced; names/enum-only diagnostics.
- **L-48:** clearing-path rows in §4; AC7 (i)-(iii) drive them, including the AC4(e) no-wedge case and the AC6b respawn clear.
- **L-17:** venue shapes cite captured bodies or the SDK snapshot; fixtures marked synthetic, including the create-time enum values.
- **L-12:** every exact set widened by named reviewed rows only (AC9); `post_order` stays excluded.
- **L-1:** decisive null-hypothesis reason in §3.
- **Invariants:** Nautilus untouched; `allow_short` stays `False`; no operator cap value read, logged or assigned (AC6b logs no amount; D3 reduces over-grant; D6 closes under-count); live enablement and the A1 halt untouched; stores written only by bot code paths.
- **Layers:** `adapters → persistence` permitted; min-age constant local to the adapter (no `adapters → strategy` import); slice E in `runtime`. `lint-imports` after every slice.

## 12. Dependencies on other EDGE items

- **EDGE-2C: hard dependency** (slice D needs its leg-aware holding and fail-closed guard). EDGE-2C is itself a hard precondition of any re-arm.
- EDGE-3 / EDGE-5 / any A1-class re-arm ruling: re-arm should land after EDGE-2 slices A, B and D are deployed, so the first post-re-arm AMBIGUOUS meets the hardened resolver and budget accounting.
- EDGE-1, EDGE-4, EDGE-6: none.

## 13. Confidence self-assessment

- **Step 0 outcome:** ~90% `ZERO_FILL_BENIGN` (GET `EXPIRED cum=0`, no `fill_parse_error`, ROI settled `OK`). Residual: vacuous 09-24 corroboration, unrecoverable create enums, and the unexplained same-day 113¢ transient.
- **Defects D1-D4, D6:** HIGH, each from source.
- **Fix design:** ~85%. Unknowns:
  1. Whether `/v1/portfolio/activities` honours `cursor`, `sortOrder` and `types` as the SDK declares — Q2s decides, and gates D.
  2. Whether settled positions remain on the positions page (Q3); B does not depend on it.
  3. Real activities/positions propagation lag — EDGE-2-LAG; 120 s stays UNVERIFIED until then.
  4. Whether the egress guard reports callees beyond the expected list for the new body — the implementer adds exactly what it demands, each reviewed.
  5. Whether a fee row is always present on TRADE activities (`commissionNotionalCollected`) for slice E; else `fee_reconciled False`.
