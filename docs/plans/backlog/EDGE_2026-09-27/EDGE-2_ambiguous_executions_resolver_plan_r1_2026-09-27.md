# EDGE-2 — AMBIGUOUS `executions-present` order retired as ZERO_FILL: verify, harden the resolver, remediate if filled (plan r1, 2026-09-27)

Severity: HIGH (settlement correctness). Status: PLAN r1. Needs the mandatory peer review (trading-bot-architect, python-reviewer and silent-failure-hunter, plus security-reviewer because the change touches the egress-firewall allowlist) before any slice is built.
Scope: venue order `CP05MNWMAWP6` (MIA 2026-09-23, YES BUY 1 @ 0.52 IOC, intent `5e50e0d9ee084cd68629b72d1ef81a6b`, client order `O-20260923-172207-L001-MIA-1`, instrument `tc-temp-miahigh-2026-09-23-gte82lt83f.POLYMARKET_US`) and the resolver class it exposed.

---

## 1. Goal and acceptance criteria

Goal state: every with-id AMBIGUOUS intent is retired as zero-fill only on evidence that can actually tell a fill from a non-fill **at the time the resolver reads it**. That includes a past-day, already-settled market and a NO-leg order. The MIA 09-23 order is proven to be either unfilled or correctly booked by the bot's own tooling.

1. **AC1 (Step 0 verdict).** A read-only evidence pack exists under `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-23_MIA/`, with PRIVATE files at 0600. Its README classifies `CP05MNWMAWP6` as exactly one of `FILL`, `PARTIAL_FILL`, `ZERO_FILL_BENIGN`, `CONTRADICTION` or `INCONCLUSIVE`, using the decision table in §2.4. A positive control shows that the same join finds a known filled order.
2. **AC2 (create path unchanged).** `classify_create_order_outcome` (`exec/submit_chain.py:1178-1310`) stays byte-unchanged. The pin `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking["200-id-no-exec"]` stays green. A new pin fixes the MIA 09-23 `executions-present` non-fill tree as KIND_AMBIGUOUS at create time.
3. **AC3 (create evidence persisted).** On every with-id AMBIGUOUS, the durable resolver context carries a closed-set `createFillEvidence` token. The values are `none`, `fill_type_present`, `fill_type_unmappable` and `unknown`, plus the closed-set execution `type` names and the nested-order `state`/`cum` tokens. This is names and enum literals only, never a price, quantity or id. A fill-type row that `_durable_execution` skips for a missing field is surfaced in `fill_parse_error`, not dropped silently.
4. **AC4 (resolver zero-fill gate).** `_resolve_terminal_zero` is reached only when ALL of these hold:
   - (a) the GET maps to a terminal non-fill status with `cumQuantity == 0`;
   - (b) `createFillEvidence` is `none` (legacy `unknown` falls through to (c) and never short-circuits);
   - (c) an activities read that reaches back past the order's `createdNs` contains **no** `ACTIVITY_TYPE_TRADE` whose `aggressor.id` or `passive.id` equals the venue order id;
   - (d) the order is at least `_RESOLVER_ZERO_FILL_MIN_AGE_NS` old (120 s, pinned equal to `_REARM_MIN_DELAY_SECS`);
   - (e) the leg-signed positions read does not show a holding on the order's leg.

   If (c) fails, the intent stays AMBIGUOUS and a CRITICAL `resolver_evidence_contradiction` is raised. If (c) cannot be completed (read error, non-eof, or the cap is hit before `createdNs`), the intent stays AMBIGUOUS. None of these outcomes are terminal.
5. **AC5 (NO leg).** For a `^no` intent the resolver derives the base slug with the existing leg helpers. It does not raise `VenuePayloadError` at `exec/client.py:2419`. It reads a NO holding as `netPosition < 0` on the base slug, per the "venue nets a NO holding as short YES" ruling. A NO-leg terminal fill resolves through `_resolve_accept_fill` and does not deadlock.
6. **AC6 (budget).** `restore_live_trading_budget` runs only when the AMBIGUOUS booking was taken **in this process** (`booking is not None`). A cross-process or next-day terminal-zero writes no `budget_restore/*` marker and credits nothing to the current permit.
7. **AC7 (L-48 clearing path).** An end-to-end test drives the verbatim MIA 09-23 shape and ends RETIRED `STATUS_REPORT_ZERO_FILL_TERMINAL`. The shape is: past-day instrument via `_resolver_instrument_loader`, positions page `{}` with `eof:true`, GET `EXPIRED qty=1 cum=0 leaves=0`, and an activities page with no trade for the id. A second test uses the same shape plus a trade row for the id; it must stay AMBIGUOUS and raise the CRITICAL.
8. **AC8 (remediation, conditional on AC1 ∈ {FILL, PARTIAL_FILL, CONTRADICTION}).** A durable `exec/polymarket_us/fill/CP05MNWMAWP6` record plus its `fill_index` entry are written only by bot tooling (§5, slice E). No hand-edited store row exists. The ROI report books it in the residual bucket, and PREREG v3 tally n is unchanged (resolver fills are residual by PREREG). The ROI 09-23..09-26 net reconciliation stays `OK` within `per_day_tolerance`.
9. **AC9 (gates).** `scripts/ci/run_tests_no_egress.sh` passes in full. `lint-imports` passes after every slice. The egress-firewall guard is widened by exactly the reviewed rows listed in §5 and by nothing else.

---

## 2. Evidence and root cause (verified this session, file:line)

### 2.1 What happened
- **Create (09-23 17:22:07.907Z).** Node log `~/.local/share/breezy/logs/breezy-trade-20260923T165046Z.log:938,943`:
  - `create-order classified kind=ambiguous status=200 body_kind=executions-present rpc_code=none body_len=3572 state=absent cum=absent tree={'executions'[2]: {...'type'...,'order': {...'state','cumQuantity','leavesQuantity'...}}, 'id'}`.
  - The line has **no `fill_parse_error=` tail** (`client.py:4978-4986` appends it only when present).
  - The durable context `exec/polymarket_us/resolver/5e50e0d9…` has `fillParseError: None` and the same `createDetail`.
- **Why AMBIGUOUS and not a fill.** `classify_create_order_outcome` (`submit_chain.py:1239-1271`) books a fill only when `_durable_execution` (`:637-658`) finds a row that has `type ∈ {EXECUTION_TYPE_FILL, EXECUTION_TYPE_PARTIAL_FILL}` (`:692-721`) and a non-empty `order.id`, `lastPx`, `lastShares` and `tradeId`. There was no `fill_parse_error`, so **no fill-type row reached `parse_fill_report`**. Either both rows were non-fill types (for example NEW plus EXPIRED), or a fill-type row was skipped silently for a missing or empty field. Skipped rows append nothing to `errors`: `:647-657` `continue` with no diagnostic. That second possibility is an L-37-class gap.
- **Why not create-time ZERO_FILL.** The ZERO_FILL branch (`:1275-1294`) requires `executions == []`. `_terminal_state`/`_cum_quantity` (`:609-634`) read only the top level and `payload.order`, never `executions[i].order`. That is why the detail line shows `state=absent cum=absent`.
- **Resolver on 09-23.** The resolver tried 285 GETs, and each failed on `leavesQuantity != quantity - cumQuantity` (log `:949…`). `df66327` fixed this with a state-aware check (`reports.py:1181-1192`). The pinned shape is `ORDER_STATE_EXPIRED qty=1 cum=0 leaves=0` (`tests/unit/test_polymarket_us_exec_reports.py:1209-1226`; `STATION_STALL_DIAGNOSIS_2026-09-24.md:194-197`).
- **Retirement (09-24 20:15:51.560Z).** `breezy-trade-20260924T201520Z.log:322` reads `resolver: retired intent 5e50e0d9… (STATUS_REPORT_ZERO_FILL_TERMINAL)`. `:323-324` then shows `OrderCanceled` for an order not in the cache (a cross-process event, harmless).
  - Durable state: `intent/history/5e50e0d9…` has `RETIRED` and `STATUS_REPORT_ZERO_FILL_TERMINAL`; `budget_restore/CP05MNWMAWP6 = 1`.
  - There is **no** `fill/CP05MNWMAWP6` record and **no** `continuous_rung_hold/trial/MIA/2026-09-23/*` record.
  - A stale `continuous_rung_hold/inflight/MIA/2026-09-23/… {"state":"open"}` remains.

### 2.2 How the resolver decided (`exec/client.py:2043-2458`)
- The GET is mapped by `parse_order_status_report`. `is_terminal_zero` requires a status in `_RESOLVER_TERMINAL_STATUSES` and `filled_qty == 0` (`:2389-2391`). **This gate is correct and is the L-36 authority.**
- The corroboration is `_resolver_long_position_state(positions, slug)` (`:1317-1336`, called `:2419-2420`), and it **returns `False` when the slug is absent** (`:1325-1326`). On 09-24 20:15Z the instrument came from the past-day loader (`:2251-2291`) and the 09-23 market had closed. So "slug absent" was **not evidence of no fill**: a settled position leaves the positions page. The corroboration leg of this retirement was therefore vacuous.
- **Defect D2 (HIGH).** For any past-day or settled market, the second leg of the zero-fill decision proves nothing. The only authority left is the GET.

### 2.3 Further defects found while tracing (all verified from source)
- **D1 (HIGH).** The resolver never reads the create body's own evidence. `createDetail`/`fillParseError` are persisted (`client.py:1057,1080`), but no resolver branch consults them. A create body with an unmappable FILL row followed by a GET `cum=0` retires as zero-fill and restores budget.
- **D3 (MED, cap-adjacent).** `_resolve_terminal_zero` calls `restore_live_trading_budget` (`client.py:2533-2538`) even when `booking is None`, i.e. when the booking belonged to a prior process. "Resolution E: same-process only" is applied to the ledger true-up (`:2527-2532`) but not to the permit restore.
  - The 09-24 process restored a slot and notional to **its own** permit for an order spent under the 09-23 permit. `budget_restore/CP05MNWMAWP6` proves it fired.
  - The clamp (`safety.py:906-909`) bounds this at the issued budget. It still re-grants a slot the current permit never spent.
- **D4 (MED, diagnostics, L-37).**
  - `_body_detail`/`_detail_tree_token` log key NAMES only. The execution `type` enum values are not recorded, so `[NEW, EXPIRED]` cannot be told apart from `[FILL(unmappable), EXPIRED]` after the fact.
  - `_durable_execution` skips fill-type rows silently.
  - The raw create body is not persisted, which is correct for redaction. The consequence is that **the 09-23 execution types can no longer be recovered locally**, so Step 0 must use venue reads.
- **D5 (HIGH, NO leg).** Checked live in this session: `instrument_id_to_slug(no_leg_instrument_id(slug))` raises `VenuePayloadError: … contains the reserved instrument separator '^'`.
  - At `client.py:2419` that call sits **outside** any `try`, after a terminal GET.
  - A with-id NO-leg AMBIGUOUS therefore escapes `_resolve_ambiguous_intents` at the moment of resolution. The periodic task dies and the intent stays OPEN, which is the L-48 deadlock class.
  - `_resolver_long_position_state` also has no leg: a NO holding (venue: short YES, `netPosition < 0`) reads as "no LONG".
  - No NO-leg with-id AMBIGUOUS has happened yet. The two prior resolver contexts, `428709da` (MIA 09-13) and `5af9eba3` (SFO 09-11), are both YES. The defect is therefore latent, and armed for the first NO-side AMBIGUOUS.

### 2.4 Local corroboration already available (no venue call)
- `~/.local/share/breezy/derived/PRIVATE_portfolio_roi_2026-09-26.json`: `daily_reconciliation` classifies 2026-09-23 and 2026-09-24 as `OK`, with net `OK` and `magnitude_cents` 0. Both rows are `provisional: True`.
  - `per_day_tolerance` is 1 cent per fill (`scripts/analysis/portfolio_roi_report.py:1390-1397`).
  - An unbooked 0.52 debit, plus its fee and any 1.00 settlement credit, would breach the tolerance on at least one of these days.
  - **Prior: `ZERO_FILL_BENIGN` is strongly favoured.** This is still a book-vs-balance identity and not an order-level proof, so Step 0 must still run.
- Captured venue shape (L-17 provenance), `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`:
  - An `ACTIVITY_TYPE_TRADE` row carries `trade.aggressor.id` and `trade.passive.id` (full `Order` objects), `marketSlug`, `qtyDecimal`, `price`, `cost` and `createTime`.
  - `ACTIVITY_TYPE_POSITION_RESOLUTION` carries `beforePosition.{netPosition,qtyBought,…}`.
  - **`activities_slug.json` (query `marketSlug=<slug>`) returned only ACCOUNT_DEPOSIT and REFERRAL_BONUS rows.** The `marketSlug` filter is not a trade filter. **Page unfiltered and filter on the client side.**

### 2.5 Answer to question (b): can an `executions-present` response ever end terminal-zero-fill?
- **At create time: no, and it must stay no.** R-7 item 5, the GL-1 ruling (`docs/evidence/gl1_gl4_order_state_ruling_2026-09-10.md`), L-32 and L-36 (`LESSONS.md:1324-1336`) pin `classify_create_order_outcome` byte-unchanged. Reclassifying "all executions non-fill plus nested terminal plus cum 0" as create-time ZERO_FILL would be a new create-path ruling (§3 option X, rejected).
- **Via the resolver: yes, legitimately.** L-36 treats the GET as a new evidence source, not a reclassification, so the create body's shape does not by itself forbid a later terminal-zero. It is legitimate **only if** the create body does not itself carry fill evidence (D1) and the corroboration can distinguish a fill at read time (D2, D5). Neither condition held on 09-24. The GET was right in all likelihood (§2.4), but the design was not.
- "Venue represents a NO buy as SELL/BUY_SHORT" (`RULING_x3_*`, memory) applies to AC5/D5. Every activities join and position sign must be leg-aware: a NO order's aggressor `intent` is `ORDER_INTENT_BUY_SHORT`, and its holding is `netPosition < 0` on the base slug.

---

## 3. Options and trade-offs

| # | Option | Verdict | Why |
|---|---|---|---|
| X | Reclassify `executions-present` non-fill plus nested terminal cum 0 as create-time ZERO_FILL | **REJECT** | It changes a pinned create-path classification (GL-1 / L-32 / L-36) and needs a strategy-lead ruling. The gain is about one resolver poll (~5 s). If wrong, the failure is fail-open (L-32: irreversible direction). |
| A | Keep positions as the only corroboration and skip past-day markets (stay AMBIGUOUS) | Reject | Past-day AMBIGUOUS then never clears. That recreates the 09-23/24 L-48 deadlock. |
| B | Activities TRADE join by order id as the mandatory corroboration for **every** terminal-zero; positions stays as a same-day leg | **CHOSEN** | Exact join key (`aggressor.id`/`passive.id`), from a captured shape. Valid before and after settlement. AMBIGUOUS is rare (4 with-id events in 22 days), so a few paged GETs cost little. One uniform rule is simpler than two regimes (KISS). |
| B′ | Activities join only on the past-day branch | Alternative | Smaller blast radius, but two regimes. Same-day positions also lag (R-7 `PositionReportingLag`, 120 s floor unverified). Rejected for B. |
| C | Use `POSITION_RESOLUTION.beforePosition.qtyBought` for the slug | Supplement only | Slug-level, not order-level. Another Breezy or external fill on the slug confounds it. Used in Step 0 as a cross-check, not in the resolver. |
| R-A | Remediation: one-shot bot CLI `breezy-attest-late-fill` (read-only venue GETs, then `record_fill` via the exec client's own record shape) | **CHOSEN, conditional** | Mirrors `breezy-clear-submit-intent` (flock-gated, operator-free window 16:40–16:50Z or node down). The bot books; nobody hand-edits a store. Build it only if AC1 ∈ {FILL, PARTIAL_FILL, CONTRADICTION} (YAGNI). |
| R-B | Re-open the RETIRED intent so the resolver re-resolves it | Reject | Mutates latch history by hand. `retire` is not idempotent (ARCH M2), and there is no sanctioned un-retire. |
| R-C | Boot-time sweep that re-verifies every recent `STATUS_REPORT_ZERO_FILL_TERMINAL` against activities | Defer | Retro-automation for a class whose forward path is fixed by B. Reopen only if Step 0 finds a real miss. |

**Null-hypothesis check (L-1): does Nautilus provide this?**
- The native in-flight poller stays disabled (`runtime/node_config.py:689-712`): retry exhaustion resolves FAILED, a false terminal.
- Native reconciliation cannot join this venue's orders, because the venue has no client-order-id (L-36).
- `generate_order_status_report` collapses failures into `None` (GL-4).
- Nothing native reads venue activities. B extends the existing Breezy resolver coroutine and does not add a parallel mechanism.

---

## 4. Architecture and data flow

```
create POST ──► classify_create_order_outcome (UNCHANGED)
                  └─ AMBIGUOUS with id ──► [NEW] submit_chain.create_fill_evidence(payload)  (pure, closed-set)
                                          └─► _note_ambiguous_open(... create_fill_evidence=…) ──► AmbiguousResolverContext (+createFillEvidence, backward-compatible default "unknown")
resolver pass (per OPEN intent with context):
  instrument (cache | past-day loader)
  GET /v1/order/{id} ──► parse_order_status_report
     PARTIALLY_FILLED / non-terminal ──► stay AMBIGUOUS (unchanged)
     terminal/fill ──► [NEW] leg-aware slug + leg-signed holding  (fixes D5)
                       [NEW] activities join: page GET /v1/portfolio/activities (no marketSlug filter), cursor to eof
                             or until oldest createTime < context.createdNs; collect TRADE rows with aggressor.id|passive.id == venue_order_id
     zero-fill decision = GET terminal ∧ cum==0 ∧ createFillEvidence∈{none,unknown} ∧ activities complete ∧ no trade for id
                          ∧ age ≥ _RESOLVER_ZERO_FILL_MIN_AGE_NS ∧ ¬holding(leg)
         └─► _resolve_terminal_zero: retire; ledger true-up iff booking; [CHANGED] permit restore iff booking (fixes D3)
     fill decision  = GET fill ∧ (holding(leg) ∨ trade-for-id present) ──► _resolve_accept_fill (unchanged body)
     contradiction  = GET zero ∧ (trade-for-id ∨ createFillEvidence ∈ {fill_type_present, fill_type_unmappable})
                      ──► stay AMBIGUOUS + CRITICAL resolver_evidence_contradiction (health-surface entry, same mechanism as open_intent_stale)
```

Clearing path (L-48 row): the latch is the account-wide OPEN intent. It is cleared by the resolver in the node process, on the first pass where the zero-fill or fill decision holds. Inputs are the GET, the activities pages and the positions page. The driving test is AC7.
- For a contradiction, the clearing path is the next pass whose activities join yields the trade, which resolves as a fill through `_resolve_accept_fill`.
- If the contradiction persists (GET fill but no trade and no holding, or GET zero but trade present), `breezy-clear-submit-intent` stays the exit, with an attestation.

**Activities transport.** `PrivateRead.__call__(path)` (`exec/client.py:733-757`) has no query parameter. The factory closure is at `factories.py:794`.
- Widen the protocol to `__call__(path, query: Mapping[str, str | int] | None = None)`, defaulting to `None`. Existing call sites are unchanged.
- The closure passes `query` to `PolymarketUSHttpClient.get_authenticated(path, query=…)`. `get_authenticated` already signs with a query; `scripts/venue/polymarket_us_capital_flow_pull.py:129-131` proves it.
- The path constant is imported from `account_activity.PORTFOLIO_ACTIVITIES_PATH`, never restated (FU-13b AC8).
- Layering: `adapters` may import `adapters.polymarket_us.account_activity` (same layer), which imports `persistence` (a lower layer).

---

## 5. File-by-file plan

| Slice | File | Change | Deps |
|---|---|---|---|
| 0 | `scripts/venue/edge2_ambiguous_order_probe.py` (new, read-only) | Step-0 GETs from §6, using `PolymarketUSHttpClient.get_authenticated` plus `QUOTA_KEY_PORTFOLIO`, the same client construction as `polymarket_us_capital_flow_pull.py`. It never imports `exec/` or permit functions, and writes 0600 files under `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-23_MIA/`. Account ids and key ids are redacted as in the 09-05 `probe.py.txt`. It never reads `/v1/account/balances`. | none |
| A | `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | New pure `create_fill_evidence(payload) -> CreateFillEvidence`, a frozen dataclass with these fields: `token ∈ {none, fill_type_present, fill_type_unmappable}`, `exec_types: tuple[str, ...]` (SDK `ExecutionType` literals, anything else → `other`), and `order_state`/`order_cum` tokens from the LAST `executions[i].order` (`0/nonzero/absent/unparseable`). New pure `_durable_execution_skips(payload) -> list[str]` names why a fill-type row was skipped. **`classify_create_order_outcome` and `_durable_execution` stay byte-unchanged (AC2).** | — |
| A | `src/breezy/adapters/polymarket_us/exec/client.py` | `_submit_order` AMBIGUOUS branch (`:4965-5003`): compute `create_fill_evidence` from the parsed body and pass it to `_note_ambiguous_open` (`:4493`). Log `exec_types=`/`order_state=`/`order_cum=` and any skip reasons on the existing AMBIGUOUS detail line. Add a `createFillEvidence` field to `AmbiguousResolverContext` (`:1028`); `from_bytes` defaults an absent field to `unknown` (old blobs decode). | submit_chain A |
| B | `src/breezy/adapters/polymarket_us/exec/client.py` | `_resolve_terminal_zero` (`:2533`): guard the permit restore with `booking is not None`. Log INFO `resolver: cross-process terminal-zero; permit restore skipped (booking held by a prior process)`. | — |
| C | `src/breezy/adapters/polymarket_us/exec/client.py` | Replace `slug = instrument_id_to_slug(instrument.id)` / `_resolver_long_position_state(positions, slug)` (`:2419-2420`) with the existing leg helpers: `leg_of(instrument.id)`, plus the base-slug derivation `_map_position`/`_find_instrument` already use (AUD13A F5). Then call `_resolver_holding_state(positions, base_slug, leg) -> bool \| None`: YES → `net > 0`, NO → `net < 0`, absent → `False`, malformed → `None`. Wrap the derivation in the loop's fail-closed pattern (log, count, `continue`), so no exception can end the coroutine. | — |
| D | `src/breezy/adapters/polymarket_us/exec/client.py` | New coroutine `_order_trade_activity(venue_order_id, created_ns) -> TradeJoin \| None`: pages activities with `limit=100`, following `nextCursor` up to `_RESOLVER_ACTIVITY_MAX_PAGES = 20`. It returns `TradeJoin(complete: bool, trade_count: int, qty: Decimal)`, or `None` on a read error. `complete` means eof, or the oldest `createTime` on the page is below `created_ns`. Wire in the AC4 decision and the contradiction branch, which adds a `resolver_evidence_contradiction` CRITICAL through the same health-surface dict pattern as `open_intent_stale` (`:2227-2250`). New constant `_RESOLVER_ZERO_FILL_MIN_AGE_NS = 120 s`. | A, C |
| D | `src/breezy/adapters/polymarket_us/account_activity.py` | New pure `trade_rows_for_order(page, venue_order_id) -> tuple[TradeActivityRef, ...]`, joining `trade.aggressor.id`/`trade.passive.id`. `TradeActivityRef` holds qty (`qtyDecimal`), `create_ts_ns` and `is_aggressor`, and **never** amounts. Module docstring: TRADE rows remain excluded from `parse_external_flows`; this is a separate reader. | — |
| D | `src/breezy/adapters/polymarket_us/exec/client.py` (`PrivateRead`) and `src/breezy/adapters/polymarket_us/factories.py:794` | Add the optional `query` parameter and forward it to `get_authenticated`. The `PrivateReadRefused` obligation is unchanged. | — |
| D | `tests/unit/test_execution_egress_firewall_guard.py` | Widen `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2081`) by exactly these reviewed rows, one per new callee, each with a comment citing this plan: `self._order_trade_activity`, `_resolver_holding_state`, `leg_of`, and the base-slug helper (name fixed at implementation). Replace `_resolver_long_position_state` and `instrument_id_to_slug` if they are removed. Any `_submit_order` callee pin gets one row for `submit_chain.create_fill_evidence`. `self._order_sender.post_order` stays absent. | A, C, D |
| E (conditional) | `src/breezy/runtime/attest_late_fill_cli.py` plus a `pyproject.toml` `[project.scripts]` row `breezy-attest-late-fill` | Mirrors `clear_submit_intent_cli.py`: it refuses while the node holds the intent flock, and takes `--venue-order-id` and `--evidence-dir`. It re-does the GET plus activities join itself, read-only, and refuses unless the join yields `trade_count ≥ 1` for the id. It constructs `DurableFillRecord` exactly as `_resolve_accept_fill` does, except that the fee comes from the trade rows' `commissionNotionalCollected` when present (`feeSource=RECORDED` per the R-1 ruling, else `fee_reconciled False`). It writes it through the exec client's `record_fill` (fill plus fill_index) and is idempotent on an existing `fill/<id>`. It writes no latch, permit or trial-scoring row: residual by PREREG. | slice D reader |
| — | `docs/core/LESSONS.md` | Add a lesson (via the lessons skill, dedup first): "A corroborating read is only evidence if it can distinguish the outcome at the time it is read". It covers settled-market positions, NO-leg sign, and create-body evidence ignored. Related: L-36, L-37, L-48. | after merge |

---

## 6. Step 0: read-only verification (next session, before any slice is built)

Run as one `systemd-run --user` oneshot at any hour. It performs GETs only on `QUOTA_KEY_PORTFOLIO` and `QUOTA_KEY_BOOK`. Nothing touches the node, the store or the latch. Interpreter: `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=/home/jon/breezy/src`. `POLYMARKET_US_USER_AGENT` is set as for the capital-flow pull. Every response is saved raw with status and attempt metadata (the 09-05 `request_log.json` pattern).

| Tag | Call (existing code path) | What it answers |
|---|---|---|
| Q1 `order_by_id` | `get_authenticated("/v1/order/CP05MNWMAWP6")`, the path from `exec/endpoints.py:128 order_by_id_path`. Parse the `order` with `reports.parse_order_status_report`, using the instrument from the local catalog loader (the same one the resolver uses). Record `state, quantity, cumQuantity, leavesQuantity, avgPx, intent, outcomeSide, createTime, lastTransactTime`. | The L-36 authority today. Is `state=EXPIRED, cum=0` still reported ~3 days later? |
| Q2 `activities_all` | `get_authenticated(PORTFOLIO_ACTIVITIES_PATH, query={"limit":100[, "cursor":c]})`, **no `marketSlug`**. Page to `eof` (cap 20) or until the oldest `createTime` < `2026-09-23T17:21:00Z`. Client-side filters: (i) `type=ACTIVITY_TYPE_TRADE` with `trade.aggressor.id == "CP05MNWMAWP6"` or `trade.passive.id == "CP05MNWMAWP6"`; (ii) any TRADE with `trade.marketSlug == "tc-temp-miahigh-2026-09-23-gte82lt83f"`; (iii) `ACTIVITY_TYPE_POSITION_RESOLUTION` with `positionResolution.marketSlug == <slug>`. | Order-level fill truth. Also settlement of any holding on the slug. |
| Q2b `activities_types_trade` | Same, with `query={"limit":100, "types":"ACTIVITY_TYPE_TRADE"}` (SDK `GetActivitiesParams.types`). | Cross-check that the `types` filter behaves. Evidence for slice D's page budget. Not relied on. |
| Q3 `positions_market` | `get_authenticated("/v1/portfolio/positions", query={"market": <slug>})`, and unfiltered to `eof`. Record presence of the slug, `netPosition`, `qtyBought`, `qtySold`, `expired`. | Does a settled/expired position still appear? Measures the D2 premise. |
| Q4 `orders_open_slug` | `get_authenticated("/v1/orders/open", query={"slugs": <slug>})`. | Must be empty. A resting remnant would be a separate hazard. |
| Q5 `market_settlement` | Public `get_public` on the market-settlement endpoint per `docs_snapshots/api-reference_markets_get-market-settlement_2026-08-25.md`, for `<slug>`. | Payoff of the rung. Needed only for a FILL P&L. |
| PC `positive_control` | Q1 plus the Q2 join for a known create-path fill in the store (e.g. `CNC3HJD66WP9` or `CMSN9WPWWWPB`; pick one whose date is inside the paged window). | The join must find ≥1 TRADE for a known fill. If it does not, the Q2 verdict is void (memory: a positive control). |
| L1 (local) | ROI report rows for 2026-09-23/24 (labels and `magnitude_cents` only) from the latest `PRIVATE_portfolio_roi_*.json`, plus store keys `fill/CP05MNWMAWP6` (absent) and `intent/history/5e50e0d9…` (RETIRED). | Book-vs-balance identity (§2.4). |

**Decision table (write exactly one verdict in the README):**

| Verdict | Condition |
|---|---|
| `FILL` | Q1 `cumQuantity == quantity` (1), or Q1 `state=FILLED`, **or** the Q2(i) trade qty sums to 1. |
| `PARTIAL_FILL` | Q1 `0 < cumQuantity < quantity` (fractional shares exist: `learn_trading_basics_fractional-shares`), or Q2(i) sums to (0, 1). |
| `ZERO_FILL_BENIGN` | Q1 terminal (`EXPIRED`/`CANCELED`/`REJECTED`) with `cum=0`, **and** Q2 complete (reached before 17:21Z 09-23) with zero Q2(i) rows, **and** PC passed, **and** Q2(iii) either absent or `beforePosition.netPosition == 0` / `qtyBought == 0`, **and** L1 09-23/24 are `OK` within tolerance. (Benign means the two create executions were non-fill lifecycle rows.) |
| `CONTRADICTION` | Q1 zero but Q2(i) ≥ 1 row, or Q1 fill but no Q2(i) row with Q2 complete and PC passed. **Treat as FILL for remediation.** Record a finding that the GET is not authoritative, and escalate slice D to make activities primary. |
| `INCONCLUSIVE` | Any read non-2xx, Q2 incomplete within the cap, or PC failed. Re-run; never conclude from partial pages. |

Never print or commit: balances, account ids, key ids, cap values. Raw PRIVATE files are 0600 in a 0700 dir, as for the 09-05 pack.

---

## 7. Test strategy (RED first; every test fails before its slice's code change)

**Slice A (`tests/unit/test_polymarket_us_submit_order_chain.py`, new tests; existing pins untouched):**
- `test_mia_0923_executions_present_nonfill_tree_stays_ambiguous_at_create`. Pin; verbatim key tree from the log `:938`, types `[EXECUTION_TYPE_NEW, EXECUTION_TYPE_EXPIRED]`.
- `test_create_fill_evidence_none_for_nonfill_lifecycle_rows`
- `test_create_fill_evidence_fill_type_present_for_mapped_fill`
- `test_create_fill_evidence_unmappable_when_fill_row_missing_trade_id`. Also asserts that `_durable_execution_skips` names the missing field.
- `test_create_fill_evidence_unknown_type_renders_other_never_value`. Adversarial `type` dict/list/long string (I6 class).
- `test_create_fill_evidence_reads_nested_order_state_and_cum_tokens`
- `test_classify_create_order_outcome_is_byte_unchanged`. Source-hash pin on the function body, so L-36's "byte-unchanged" is structural.

**Slice A (`tests/unit/test_current_rung_hold_ambiguous_resolver.py`):**
- `test_resolver_context_round_trips_create_fill_evidence`
- `test_legacy_resolver_context_without_field_decodes_as_unknown`

**Slice B:**
- `test_cross_process_terminal_zero_does_not_restore_current_permit`. Asserts `booking=None`: no `budget_restore/*` key, and permit remaining unchanged.
- `test_same_process_terminal_zero_still_restores_permit`. Regression; existing behaviour preserved.

**Slice C:**
- `test_no_leg_terminal_get_does_not_raise_on_reserved_separator`. RED today: `VenuePayloadError` at `:2419`.
- `test_no_leg_holding_is_negative_net_on_base_slug`
- `test_no_leg_terminal_fill_with_short_yes_position_resolves_accept_fill`. Guards against the L-48 deadlock.
- `test_yes_leg_holding_semantics_unchanged`
- `test_malformed_net_position_stays_ambiguous_for_both_legs`

**Slice D:**
- `test_terminal_zero_requires_complete_activities_with_no_trade_for_order`
- `test_trade_activity_for_order_id_blocks_zero_fill_and_raises_contradiction_critical`
- `test_create_fill_evidence_fill_type_blocks_zero_fill`
- `test_activities_read_failure_stays_ambiguous_and_counts_backoff`
- `test_activities_cap_before_created_ns_is_incomplete_and_stays_ambiguous`
- `test_zero_fill_before_min_age_stays_ambiguous`
- `test_min_age_constant_equals_strategy_rearm_floor`. Pins `_RESOLVER_ZERO_FILL_MIN_AGE_NS == _REARM_MIN_DELAY_SECS * 1e9`, so the two cannot drift.
- `test_mia_0923_past_day_shape_retires_zero_fill_with_empty_trade_join`. AC7 clearing path: past-day loader instrument, positions `{}` with eof, GET `EXPIRED 1/0/0`, activities with no trade row.
- `test_mia_0923_past_day_shape_with_trade_row_stays_ambiguous`. The incident regression; RED today, because it retires.
- `test_trade_rows_for_order_joins_aggressor_and_passive_ids`, in `test_account_activity.py`. Fixture derived from the captured `activities_p0.json` shape (names only, synthetic values).
- `test_trade_rows_for_order_ignores_marketslug_match_without_id_match`
- `test_private_read_query_is_forwarded_and_signed`, in the factory tests. It also asserts that `PrivateReadRefused` on non-2xx is still raised.
- Egress guard: `test_execution_egress_firewall_guard.py` passes with only the listed rows added. `post_order` absence is still asserted.

**Slice E (conditional):**
- `test_attest_late_fill_refuses_while_node_holds_flock`
- `test_attest_late_fill_refuses_without_trade_join`
- `test_attest_late_fill_writes_fill_and_index_idempotently`
- `test_attested_fill_is_residual_and_leaves_tally_n_unchanged`
- `test_roi_report_books_attested_fill_in_residual_bucket`

Run: focused files first, then `scripts/ci/run_tests_no_egress.sh` (full gate, basetemp under `/home/jon/.cache/breezy-gate/`, `-p LimitNOFILE=524288` when unit-launched). Then `lint-imports`, and read the exit codes (memory: `-q` doubling).

---

## 8. Execution order and parallelism

1. **Step 0** (read-only probe, slice 0). This is independent of everything else and runs first in the next session. Its verdict decides whether slice E exists.
2. **Slices A, B and C** in parallel worktrees. B and C both touch `client.py`, but in disjoint regions (`:2533` vs `:2419`). Merge B first (smallest), then rebase C.
3. **Slice D** after A and C merge (it needs `createFillEvidence` and the leg-aware holding).
4. **Slice E** only if Step 0 returns FILL, PARTIAL_FILL or CONTRADICTION. It needs slice D's pure `trade_rows_for_order`, which can be cherry-picked early; it does not need slice D's resolver wiring.
5. Implementer per slice: `tdd-guide`, seeded with python-testing. Reviewers: `python-reviewer`, `silent-failure-hunter`, and `security-reviewer` for the D allowlist and the `PrivateRead` widening. Each worktree uses `PYTHONPATH=<wt>/src` and `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`. Never `uv`/`pip`; never `git stash`. Run the full gate after every merge.

---

## 9. Deploy and verification

- Node code (A–D) goes live on the **next node respawn** (16:50Z daily); never kill the live node. The supervisor is untouched.
- Proof of liveness: node log FILE at `_connect` shows one INFO line `resolver: zero-fill corroboration=activities_v1 min_age_s=120 legs=yes,no`. Add that line in slice D.
- Behavioural proof: with the A1 halt SET no order is sent, so no AMBIGUOUS can arise. **The live proof of D is deferred to the first AMBIGUOUS after re-arm**, stated like R-7-IMPL. Until then the evidence is the AC7 end-to-end tests on the verbatim shape. PROGRESS.md gets an `EDGE-2-LIVE` watch row.
- Slice E (if built) runs once, as a `systemd-run --user` oneshot, in the flock-free window (16:40–16:50Z) or while the node is down. Wait for `ActiveState ∉ {active, activating}`.
  - Verify `fill/CP05MNWMAWP6` plus the fill_index row exist.
  - The next 17:40Z ROI report shows the fill in `n_residual` with net reconciliation `OK`.
  - The 17:20Z v4 tally n is unchanged.

---

## 10. Risk register

| Risk | L | I | Mitigation |
|---|---|---|---|
| The activities endpoint drops or reorders old trades, or pagination is unstable, giving a false "no trade" | L | H | Require `complete`. The PC positive control in Step 0 measures the join. Contradiction and incomplete outcomes both fail closed. |
| Activities lag behind a fill (index lag) | M | H | The 120 s min-age floor, plus the GET, plus the create-body evidence, plus positions on the same day. Any single contrary signal blocks zero-fill. |
| Widening `PrivateRead` opens a write path | L | CRIT | GET-only protocol unchanged; the query dict is data. Security review. The NO-SEND guard is widened by named rows only; `post_order` stays excluded. |
| Resolver coroutine dies on a new exception | M | H | Every new call sits inside the loop's existing `try/log/continue` pattern. The test covers the NO-leg separator crash (D5). |
| Paging raises portfolio-quota pressure on the live node | L | M | At most 20 pages per pass, only while an intent is OPEN; backoff reuses `_resolver_consecutive_failures`. |
| Step 0 finds a FILL | L | H | Slice E books it as residual. ROI and capital-deployed correct themselves from the durable record. No cap was exceeded: the 09-23 order was within its own permit, and the D3 over-grant is clamped. |
| Old durable contexts lack `createFillEvidence` | — | L | Decoded as `unknown`, so activities are still required. Never short-circuits to zero-fill. |
| A stale `inflight/MIA/2026-09-23 open` row misleads a reader | L | L | Out of scope. Past-day key, never re-read for a new day. Noted for the coordinator. |

---

## 11. LESSONS and invariant compliance

- **L-32 / L-36 / GL-1 / R-7 item 5.** Searched and cited (§2.5). The create classifier is unchanged and pinned, and the GET stays the authority. The new legs only **tighten** zero-fill, so they are fail-closed.
- **L-37.** Skipped fill rows are now surfaced. Diagnostics stay names/enum-only (SEC-H1).
- **L-48.** Clearing-path row in §4. AC7 drives the real stuck shape end to end, including a past-day instrument and a node booted after the latch was set.
- **L-17.** Every venue shape used cites a captured body (`AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`, `activities_slug.json`) or the SDK snapshot (`types/portfolio.py`, `types/orders.py`). Fixtures are marked synthetic-from-captured.
- **L-12.** The allowlist is widened by one reviewed row per callee. No safety, settlement, contract or NO-SEND test is weakened.
- **L-1.** Null-hypothesis verdict in §3.
- **Invariants.**
  - Nautilus is untouched.
  - `allow_short` stays `False`.
  - No operator cap value is read or assigned; D3 reduces over-grant.
  - Live enablement and the A1 halt are untouched.
  - Stores are written only by bot code paths (the resolver and the slice-E CLI), never by hand.
  - Memory "never hand-compute a result the bot should produce": Step 0 classifies, and the bot books.
- **Layers.** `adapters → persistence` is permitted. There is no new `runtime → strategy` import. The slice-E CLI lives in `runtime`, which imports `adapters` (permitted). `lint-imports` runs after every slice.

## 12. Dependencies on other EDGE items

- EDGE-3 (per-family halt): no code dependency. Any re-arm that follows from EDGE-3 or a new A1-class ruling should land **after** EDGE-2 slices B–D are deployed, so the first post-re-arm AMBIGUOUS meets the hardened resolver.
- EDGE-1 and EDGE-4: none.

## 13. Confidence self-assessment

- **Step 0 outcome.** About 90% `ZERO_FILL_BENIGN`: GET `EXPIRED cum=0` (`STATION_STALL_DIAGNOSIS:194`), no `fill_parse_error`, and ROI 09-23/24 `OK` at magnitude 0. Not 100%, because the 09-24 corroboration was vacuous and the create execution types are unrecoverable.
- **Defect findings D1–D5.** HIGH confidence; each is verified from source, and D5 was reproduced live in this session.
- **Fix design.** About 80% (MEDIUM-HIGH). Unknowns:
  1. Whether `/v1/portfolio/activities` honours `cursor`, `types` and `sortOrder` as the SDK declares. Step 0 Q2/Q2b measure it.
  2. Whether settled or expired positions remain on the positions page. Q3 measures it; option B does not depend on the answer.
  3. The exact base-slug helper name for `^no` in `client.py`. AUD13A F5 says `_map_position` already resolves it; the implementer names it.
  4. Whether `_submit_order` has its own pinned callee set needing a row for `create_fill_evidence`. The implementer runs the guard unmodified first and adds exactly the rows it demands.
  5. Whether any other store key must change for a FILL verdict, e.g. the trial record. PREREG residual rules say no; slice E tests pin it.
