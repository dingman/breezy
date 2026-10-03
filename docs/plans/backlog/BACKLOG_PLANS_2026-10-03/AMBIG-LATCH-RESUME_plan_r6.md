# AMBIG-LATCH-RESUME — plan r6 (2026-10-03)

Status: DRAFT r6 for peer re-review. Plan only; nothing is implemented.
Supersedes: `AMBIG-LATCH-RESUME_plan_r5.md` (unchanged on disk).
Reviews applied:
- **r6:** `reviews/AMBIG-LATCH-RESUME-r5-merged.md`: item 1 (coordinator ruling: route (d) manual-leg reconciliation, plus the restated residual bound), item 2 (ordering checked on TRADE rows only), item 3 (Phase A ancestry check by `git merge-base --is-ancestor` alone), item 4 (DM1 forward skew stated as a symmetric choice, not derived) and item 5 (T48 scope; `account_activity` pinned too).
- r5: `reviews/AMBIG-LATCH-RESUME-r4-merged.md`: DH1 (two-phase activation enforced in the build), DM1 (bounded attribution window), DM2 (firewall scan coverage and module purity), DM3 (activity completeness by ordered early termination), DM4 (holding delta and an automated exit for R-CONTRA) and DL1.
- r4: `reviews/AMBIG-LATCH-RESUME-r3-merged.md`: CH1 (coordinator ruling: an automated no-id resolver is mandatory), CM1, CM2 and CL1.
- Not regressed: `reviews/AMBIG-LATCH-RESUME-r1-merged.md` (A1–A5 and 3 LOW), `reviews/AMBIG-LATCH-RESUME-r2-merged.md` (F1–F6 and 4 LOW) and the r3 items above.
- See **§R6 Disposition** after §9. The r5, r4, r3 and r2 dispositions are kept below it for the record.
- Every r6 change is marked **(r6, <item>)** in the body; r5 markers are kept.

Item (docs/core/PROGRESS.md:96): AMBIG-LATCH-CLEAR (`3eb4a108`) leaves the exec client DEGRADED after the clear. Health reads DEGRADED while the client trades, and a later refusal does not re-alert. Call native `resume()` from outside the resolver. **r4 scope growth (ruled):** every AMBIGUOUS shape must retire autonomously, including no-id. The supervisor must never strand a resolvable OPEN intent with the node down.

**Evidence base.** Everything r3 cites is re-verified at HEAD `f45f5a65`. New in r4:
- **Exec client** (`src/breezy/adapters/polymarket_us/exec/client.py`):
  - `:5537-5569`: arm, then POST, then the exception AMBIGUOUS.
  - `:5800-5855`: the classified AMBIGUOUS, with-id and no-id.
  - `:2379-2544`: resolver loop entry, including the context-absent `continue` at `:2538-2544`.
  - `:2788-2983`: predicates.
  - `:2985-3112`: `_resolve_terminal_zero`.
  - `:3319-3440`: `_order_trade_activity`.
  - `:4199-4250`: `_resolver_fill_order_unknown`.
  - `:5223-5244`: `_retire`.
  - `:5255-5305`: `_note_ambiguous_open`.
  - `:1085-1142`: `AmbiguousResolverContext`.
  - `:449-454`: `RESOLVER_CONTEXT_KEY_PREFIX`.
  - `:401-404`: "This venue issues no client order id".
  - `:1505-1516`: page cap and the 120 s floor.
- **Submit chain and transport:**
  - `submit_chain.py:376-387, 558-569`: the exact entry and exit wire bodies.
  - `submit_chain.py:1200-1322`: `classify_create_order_outcome`.
  - `submit_chain.py:134`: `_MAX_BLOCK_TIME = "5"`.
  - `submit_chain.py:1508`: `retirement_member` is a `getattr`.
  - `write_transport.py:177-194`: `post_order` raises `VenueTransportError` on `HttpError`/`HttpTimeoutError`.
  - `signing.py:89`: `DEFAULT_SKEW_TOLERANCE_MS = 30_000`.
  - `write_transport.py:102-109`.
- **Venue SDK snapshot:**
  - `types/orders.py:111-125`: `CreateOrderParams` has no client-id field.
  - `types/orders.py:171-174`: `GetOpenOrdersResponse` is `orders` only, with no cursor or eof.
  - `types/portfolio.py:95-119`.
- **Activities row shape:**
  - Captured in `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`, which is git-tracked.
  - Every TRADE row carries `aggressor` and `passive` order objects. Each has `id`, `marketSlug`, `outcomeSide`, `action`, `price.value`, `quantity`, `tif`, `manualOrderIndicator` and `createTime`.
- **Runtime:**
  - `runtime/submit_intent.py:73-93`: `RetirementReason`.
  - `runtime/submit_intent.py:391-419`: `arm`.
  - `runtime/clear_submit_intent_cli.py:69-152`.
  - `runtime/trade_supervisor.py:402-420`: `probe_open_intent`.
  - `runtime/trade_supervisor.py:1063-1113`: `SupervisorPorts`, `default_ports`.
  - `runtime/trade_supervisor.py:1131-1189, 1209-1261, 1582-1619`.
  - `runtime/trade_supervisor_core.py:341-346`: `LaunchAction`.
  - `runtime/trade_supervisor_core.py:532-542`: `decide_launch_action`.
- **Tests:**
  - `tests/unit/test_execution_egress_firewall_guard.py:1797-1830, 1938-2297, 2435-2496, 3110-3200`: the scanned sets, both allowlists, the resolver scanner, and the set-equality pin on the order-coroutine allowlist only.
  - `tests/unit/test_trade_supervisor.py:391-398, 5282-5301`.
  - `tests/unit/test_current_rung_hold_ambiguous_resolver.py:5705-5741`.
- **Lessons:** `docs/core/LESSONS.md` L-36 (`:1324-1345`) and L-48 (`:1530-1541`).
- **Store and logs, all read-only:** the store is `~/.local/share/breezy/state/exec_polymarket_us.sqlite`. It was copied with the sqlite backup API from a `file:...?mode=ro` connection to the session scratchpad and queried there, so nothing was written to the live store. Node logs are `~/.local/share/breezy/logs/breezy-trade-*.log`, 2026-09-04 to now. The supervisor log is `breezy-trade-supervisor.log`.

**New in r5** (re-verified at HEAD `f45f5a65`; store re-copied read-only the same way on 2026-10-03 late):
- **Supervisor (DH1):**
  - `trade_supervisor.py:849-876` `spawn_node`: `subprocess.Popen([node_bin], cwd=str(repo_root), ...)` at `:866-876`. A respawned node loads whatever is checked out; the supervisor keeps the code it loaded at its own start.
  - `:402-420` `probe_open_intent`: `SubmitIntent.from_bytes` → `SubmitIntentCorrupt` counts as OPEN (`:416-419`).
  - `submit_intent.py:207-219` `_optional_enum`: an unknown `retirement_reason` string raises `SubmitIntentCorrupt` (`:216-219`). An old supervisor therefore reads a singleton retired `RESOLVER_NO_ID_NO_FILL` as OPEN and refuses every launch (the L-48 deadlock).
  - `:2492-2500` the `supervisor_started ... revision=<sha>` line (`_resolve_build_revision`, `:904-917`); `:2068` `log_decision("permit_watch_adopted_live_node", pid=...)`; `:942-968` `alert(..., severity=...)`; `:374` `resolve_lock_holder_pid`.
  - `stop_intent_marker.py`: the existing precedent for a supervisor-written durable marker beside the store, with pid + `/proc` start-tick identity (`_process_start_ticks`, `:137`).
  - `node_config.py:945-967`: the `msgspec_replace(exec_client_config, ...)` site where node-boot facts are injected into `PolymarketUSExecClientConfig` (`config.py:547`).
- **Firewall (DM2):** `test_execution_egress_firewall_guard.py:2099-2110` `EXEC_RESOLVER_COROUTINES` (4 names today), `:2118-2300` `EXEC_RESOLVER_PERMITTED_CALLEES` (contains `self._store_get`, `record.to_bytes`, `self._set_resolver_last_failure_kind`; **not** `self._store_set`), `:2436-2496` `find_exec_resolver_violations` (scans only bodies named in `EXEC_RESOLVER_COROUTINES`), `:4020-4062` the single-key shape pin of `_set_resolver_last_failure_kind`. `_note_ambiguous_open` is a permitted *callee* of `_submit_order` (`:1938-2085`) and is not itself scanned.
- **Activities ordering (DM3):**
  - `account_activity.py:599-635` `page_min_create_ts_ns` and its docstring: the EDGE-2 coordinator amendment keeps `_order_trade_activity` eof-only and calls the `min(createTime)` branch UNLICENSED pending a multi-page observation.
  - Git-tracked capture `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json` (query `{limit: 100}`, default order): 10 rows, `eof: true`, timestamps **non-increasing with one exact tie** (two TRADE rows at `2026-08-05T13:40:00.704590303Z`).
  - Local, git-ignored (`.gitignore:23`, `PRIVATE_*`) captures `AMBIGUOUS_ORDER_2026-09-23_MIA/PRIVATE_activities_desc_r1_p0.json` and `_desc_r2_p0.json` (query `sortOrder=SORT_ORDER_DESCENDING`): 35 rows each, `eof: true`, identical across the two runs, non-increasing, the same tie. `PRIVATE_activities_asc_p0.json` is the exact reverse. `PRIVATE_summary.json`: one page on every run.
  - Node logs: **0** `activities join ... traversed N pages` INFO lines across 67 node log files, i.e. no resolver activities read has ever needed a second page.
- **Venue-time offset (DM1, DL1).** Store history `created_ns` joined to the captured trade `createTime` of the same order, for the 9 Breezy fills in the 09-23 capture (09-11 to 09-22): **venue trade time − local `created_ns` = 0.075 s to 0.215 s** (median 0.130 s). That includes 2 with-id AMBIGUOUS episodes (09-11 +0.191 s, 09-13 +0.108 s).
- **Pre-POST holdings (DM4).** `_submit_order` makes **no** venue read before `post_order` (its only `await` is the POST, `client.py:~5550`; E0-NOSEND forbids another). The pre-POST holding evidence that already exists is local:
  - the durable `STARTUP_EVIDENCE_KEY` record (`StartupPositionEvidence`, `:1259-1381`): per-slug signed `net_position`, `eof_complete`, `position_read_refused`, `ts_ns`. It is rewritten from an eof-complete positions GET at the end of `_connect`, after each terminal-zero, and by the resolver's age-gated refresh every `_EVIDENCE_REFRESH_AFTER_NS` = 60 s (`:584-592`, `:2486-2514`), so it is ≤ ~65 s old while the resolver is healthy;
  - `_durable_net_qty(instrument_id)` (`:3442-3473`), Breezy's own durable fills, each with `ts_event` (`DurableFillRecord`, `:949-957`).
- **Same-day test (DM4 exit).** `:2923-2936`: "same-day" is membership in `self._instrument_provider.list_all()`, and "the node loads only today's instruments into the provider". A past-day instrument skips the positions leg (D2).
- **Manual trades on the account.** The 35-row capture holds MANUAL aggressors only on 2026-08-05 (pre-go-live) and 2026-09-27 (`*-cfb-*` college-football markets, not weather). **0** MANUAL trades on a same-day Breezy weather instrument since go-live. Every AUTOMATIC aggressor after 2026-09-05 maps to a Breezy intent in the store.
- **Volume refresh:** the store now holds **27** distinct intents (3 more on 2026-10-03, all `ACCEPTED_WITH_DURABLE_FILL`); there is still exactly 1 no-id AMBIGUOUS. §2.7 keeps the r4 figures; they are unchanged in substance.

**New in r6** (re-verified at HEAD `f45f5a65`; the store re-copied read-only with the sqlite backup API from a `mode=ro` connection into the session scratchpad):
- **Same-day membership (item 1).** `client.py:2923-2936`: "same-day" is membership in `self._instrument_provider.list_all()`. The provider loads the venue's *active* markets, not a date window: `provider.py:334-338` drops `closed=true` / resolved markets, and `:585-599` adds every remaining discovered market. So an instrument leaves `list_all()` at the first node boot after the venue resolves its market.
- **Market resolution time (item 1).** The 11 `ACTIVITY_TYPE_POSITION_RESOLUTION` rows in the 35-row `SORT_ORDER_DESCENDING` capture (`afterPosition.updateTime`) fall at **D+1 12:01Z to 15:01Z** for climate day D (09-21, 09-22, 09-15 ×4, 09-13, 09-11, 08-08, 08-09). All are before the 16:50Z launch on D+1. The tracked capture shows a weather market listed from about D−1 09:45Z (`startDate`) with `endDate` D+1 05:00Z.
- **Take lead (item 1).** Store fill and context records (28 with a slug and a time): lead 0 days = 13, lead 1 day = 14 (the forecast family takes D+1's market on D), lead −1 = 1. One lead-1 take was at 16:02Z, before the 16:40Z stop (2026-10-01T16:02Z on the 10-02 market).
- **Manual-leg shapes (item 1).** In the 35-row capture, every MANUAL aggressor carries `outcomeSide`, `action`, `side` and `intent`: `(YES, BUY, ORDER_SIDE_BUY, ORDER_INTENT_BUY_LONG)` ×3 and `(YES, SELL, ORDER_SIDE_SELL, ORDER_INTENT_SELL_LONG)` ×1. The AUTOMATIC NO buys are `(NO, BUY, ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)` ×3, matching the 2026-09-14 NO-side preview capture. `ORDER_INTENT_SELL_SHORT` has never been observed. The trade's fill quantity is `trade.qtyDecimal` (the field `_trade_qty_decimal` reads, `account_activity.py:363-370`). The leg's `quantity` is the *order* quantity (19 vs 19 here, but 7.63 for a partially matched order in the tracked capture), so it cannot be used as the fill size. The manual flag on a leg is not parsed anywhere in `src/` today (`manualOrderIndicator` appears only in `submit_chain.py`, `reports.py` and `safety.py`); it is parsed by the planned `NoIdLeg.manual` (§2.8.5).
- **Activity ordering by type (item 2).** `_activity_create_ts_ns` (`account_activity.py:569-596`) reads a different field per type: `trade.createTime`, `positionResolution.afterPosition.updateTime`, or the balance change's top-level-then-nested `createTime` (L-17). Measured with that function, read-only, on every capture under `docs/evidence/` that holds non-TRADE rows:
  - tracked `AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`: 10 rows (5 TRADE, 2 POSITION_RESOLUTION, 2 ACCOUNT_DEPOSIT, 1 REFERRAL_BONUS), **0** inversions across all types, 0 among TRADE rows;
  - tracked `.../activities_slug.json`: 3 non-TRADE rows, 0 inversions;
  - local `PRIVATE_activities_desc_r1_p0.json` and `_r2_p0.json`: 35 rows (17 TRADE, 11 POSITION_RESOLUTION, 3 REFERRAL_BONUS, 3 ACCOUNT_DEPOSIT, 1 TRANSFER), **0** inversions across all types; `PRIVATE_activities_asc_p0.json` is the exact reverse (33 inversions under a descending check, as expected).
  - The two `PRIVATE_v1_portfolio_activities_*.probe.json` files hold no activities page.
  - So the venue's order is *consistent* with one key across types on 2 distinct pages. That is corroboration, not proof of the venue's sort key (§2.8.5).
- **Phase A revision (item 3).** `supervisor_started ... revision=<sha>` comes from `resolve_build_revision` (`build_sha.py:147-172`): the `BREEZY_BUILD_REVISION` env override first, then the source-tree HEAD truncated to 12 hex, then the package version, then `"unknown"`.
- **`account_activity` purity (item 5).** Its own imports are exactly `__future__`, `calendar`, `hashlib`, `logging`, `re`, `collections.abc`, `dataclasses`, `datetime`, `decimal`, `typing` and `breezy.persistence.external_capital_flows` (`account_activity.py:36-48`). The module body has no `await`, no `async`, and no `open`. Its one first-party import, `external_capital_flows`, does file I/O (`os.open` at `:271`) and imports `os`/`pathlib`, but has no network import. `_parse_rfc3339_ns` (`:190-205`) is a regex, `datetime.strptime` and `calendar.timegm`.

---

## §I Hard invariants (restated; never violated)

1. **Nautilus Trader is immutable.**
   - No file under `.venv/` is touched.
   - Native `Component.resume()`/`degrade()` and the native order events are only *called*.
   - The Nautilus in-flight poller stays disabled (L-36: "retry exhaustion resolves FAILED, a false terminal on a venue with no client-order-id", `runtime/node_config.py:689-712`).
2. **`allow_short` stays `False`.** No order-shape, side or leg logic changes. Both wire bodies stay byte-identical (`submit_chain.py:376-387, 558-569`).
3. **No safety, settlement or contract test is weakened or deleted.** Every existing test edit is ruled and disclosed:
   - (a) The two A3 assertion edits, kept from r3.
   - (b) The `_EXEC_CLIENT_SHA256` re-pin.
   - (c) The NO-SEND resolver allowlist and scanned-set constants. **Additions only:** `EXEC_RESOLVER_PERMITTED_CALLEES` gains **17** named non-egress callees (r4's 12, plus 4 from r5 DM2/DM4, plus 1 from r6 item 1: the pure `manual_leg_net_effect`). `EXEC_RESOLVER_COROUTINES` gains **4** names, so more code is scanned (r5 DM2 adds `_adopt_no_id_venue_order`). `EXEC_PERMITTED_COROUTINE_NAMES` gains the 2 new coroutine names (§2.8.7).
   - (d) **The ruled inversion of T25(iii)** (CL1). r3's planned T25(iii) pinned the *absence* of an autonomous no-id path; r4 replaces it with positive resolver tests. T25 is a planned test, not yet in the tree. The existing tree test `test_open_intent_without_a_durable_context_makes_no_get_and_stays_open` stays **unedited and green**.
   - (e) One binding-lesson amendment (L-36's "only no-id path" clause, §2.8.0), ruled by the coordinator.
   - (f) **(r5, DM3) One scoped, ruled supersession of the EDGE-2 "complete from eof ONLY" amendment**, for the new `_no_id_trade_activity` only: completeness may also come from ordered early termination (§2.8.6). `_order_trade_activity`, `page_min_create_ts_ns` and every EDGE-2 test stay byte-identical. No test is edited by this.
   - No other existing test is edited. Any further RED stops the build and is reported, never edited silently.
4. **The operator caps (max daily budget, max per position) are not touched, read, named by env-var, or given a value.**
   - The permit, its ceiling and `safety.py` are unchanged.
   - `restore_live_trading_budget` is only called, through the existing zero-fill pattern.
5. **Live enablement and the NO-SEND execution-egress firewall are untouched in substance.**
   - No new egress callee: the only network reads the new code awaits are the existing GET seams `self._private_read` (positions and activities) and `self._read_open_orders`.
   - **(r5, DM2)** The one new *local* write callee in the resolver allowlist, `self._store_set`, is shape-pinned to a single call site (`_adopt_no_id_venue_order`) with a single key shape (T42(iv)). `no_id_attribution.py` is pinned pure (T48). **(r6, item 5)** T48 checks each module's *own* imports only; `account_activity.py` is pinned the same way, and its one first-party import's file I/O is stated (§Evidence r6).
   - `self._order_sender.post_order` stays absent from every resolver set. The set-equality pin on `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` stays **unedited and green**, because `_submit_order` gains no new callee.
   - The sandbox, scanners, E0-INERT, N1–N5 and X1–X3 are unmodified.
   - Proof: T42, the callee-set test, plus T8a/T8b.
6. **No operator step is needed to resume, ever.**
   - Every OPEN shape has an autonomous clearing path (§5.3 table).
   - Every residual is fail-closed (no order can be sent), paged CRITICAL, and bounded (§7).
   - **(r5)** Every CRITICAL raised over an OPEN intent names an automated next step and a cadence: the 60 s no-id re-check (DM4), **(r6)** including the manual-leg reconciliation (route (d)), the first launch after the market resolves (DM4 past-day exit, restated bound), the next node boot (DH1 marker re-read), or the resolver poll.
   - Activation needs no operator step either: the Phase A check script (§2.11) is run by the coordinator, not by the operator.
   - `breezy-clear-submit-intent` is unchanged and stays available, but nothing depends on it.

---

## §0 Problem and goal state

### Problem (five defects)

**D1. The FSM stays DEGRADED.**
- `_refuse` (`client.py:5896-5976`) calls `self.degrade()` on the first refusal while not degraded.
- `_resolve_terminal_zero` (`:3100-3112`) clears the AMBIGUOUS entry as its last step.
- Nothing ever calls `resume()`, so the native state stays `DEGRADED` for the rest of the process.
- In `$NT`, the only native `.resume()` or `.degrade()` call on an adapter is `adapters/betfair/data.py:401`.

**D2. The alert latch is permanent, and a refusal without a transition never alerts.**
- `install_component_degraded_alert` (`runtime/component_health_watch.py:628-703`) adds `component_id` to `alerted` and never removes it.
- `_refuse` degrades only when `not self.is_degraded` (`:5970-5976`, pinned at `test_polymarket_us_exec_client.py:1081`).
- So between a clear and the next resume, a new AMBIGUOUS publishes no `ComponentStateChanged` at all (F6).

**D3. A filled AMBIGUOUS never clears (ruling A3).**
- `_resolve_accept_fill` (`:3114-3317`) retires, records, trues up and publishes the fill, but leaves AMBIGUOUS in `_trading_refusals`.
- This is pinned by `test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` (`test_fq_caps_and_ambiguous_2026_10_01.py:387-419`).
- Provenance (F4): commit `87b3725b7780c3e39566eb407b7496c97ad36664`, quoted verbatim:

> Cleared scope: _resolve_terminal_zero only, after a successful _retire and only
> when the durable latch has no open intent left; drops entries whose reason is
> exactly submit_chain.AMBIGUOUS_REASON (new list, no in-place mutation), one INFO
> line naming the reason and intent id. Inlined, not a helper, so the
> E0-NOSEND-RESOLVER permitted-callee set is unchanged.
>
> Still latches: every other refusal reason; the AMBIGUOUS refusal on any fill or
> accept-fill terminal path, on an incomplete join, on a non-terminal GET, and
> at create time (empty executions at maxBlockTime stays AMBIGUOUS; L-36, GL-1,
> R-7 unchanged).

- The message lists the fill path under "Still latches" and gives no safety rationale; the incident it fixed was a zero-fill.
- Today a filled AMBIGUOUS denies every later order for the rest of the process (`_submit_order:5357-5359`).
- **Side effect of D1:** `ExecutionEngine._stop`/`stop_clients` (`$NT/execution/engine.pyx:727-729, 770-772`) call `client.stop()` only `if client.is_running`, so a DEGRADED client is skipped.

**D4 (CH1, new). A no-id AMBIGUOUS needs the operator.**
- `_submit_order` creates a **no-id** AMBIGUOUS on two paths:
  - (a) Any exception from `post_order` (`:5549-5569`). That includes `VenueTransportError` from a pyo3 `HttpError`/`HttpTimeoutError` (`write_transport.py:182-189`) and `CancelledError` on SIGTERM, which is re-raised at `:5567-5568`.
  - (b) A classified response with no venue id (`:5800-5828`): no response (`submit_chain.py:1219-1233`), a non-JSON body, a 5xx or a non-rpc 4xx without an id, or a 200 without an id.
- `_note_ambiguous_open` is called only `if outcome.venue_order_id is not None` (`:5825`), so no resolver context exists.
- The resolver then `continue`s forever (`:2538-2544`).
- The only path out is `breezy-clear-submit-intent`, which requires an operator acknowledgement, an evidence file and a stopped node (`clear_submit_intent_cli.py:95-145`).
- **r3's claim that R-NOID is "a strict subset of the W race" is false and is withdrawn.** A no-id outcome is a steady-state shape, measured in §2.8.2.

**D5 (CM1, new). The supervisor strands any OPEN intent with the node down.**
- `_do_stop_prior` SIGTERMs the node at 16:40Z without probing the intent (`trade_supervisor.py:1131-1189`).
- `_do_launch` (`:1233-1261`) and the boot retry (`:1592-1619`) then refuse at 16:50Z if any intent is OPEN (`decide_launch_action`, `trade_supervisor_core.py:532-542`).
- Only a running node's resolver can retire an intent, so this is the L-48 deadlock.
- **It has happened live:**
  - `breezy-trade-supervisor.log` shows `2026-09-24T16:50:11Z ... launch_refused_intent_open`.
  - The OPEN intent was `5e50e0d9…` (AMBIGUOUS 2026-09-23 17:22:07Z, with-id). It stayed OPEN for 26.9 h and retired `STATUS_REPORT_ZERO_FILL_TERMINAL` only after a hand launch at 2026-09-24 20:15Z (store history, §2.7).

### Goal state (acceptance test)

After **any** AMBIGUOUS episode, with or without a venue id, in the same process or across a process or day boundary, all of the following hold:

1. The intent is retired with venue evidence, and the booking is trued up.
   - The permit slot is restored on a no-fill retirement (zero-fill or no-id no-fill) or kept spent on a fill.
   - The AMBIGUOUS refusal is cleared, and every other refusal reason stays.
   - Contradictory or incomplete evidence instead keeps it AMBIGUOUS and pages CRITICAL (goal 8).
2. Within one resolver pass plus one `REFUSAL_REPOLL_INTERVAL` (60 s, `component_health_watch.py:476`), the client goes `DEGRADED -> RESUMING -> RUNNING` through native `Component.resume()`.
3. `client.is_degraded` is False and `client.is_running` is True.
4. **Every new AMBIGUOUS refusal produces exactly one `component_degraded` CRITICAL, never throttled (F3)**, within ≤ one `REFUSAL_REPOLL_INTERVAL`. That includes one landing inside the clear-to-resume window (F6).
   - A non-AMBIGUOUS episode alerts once, unless the 1 h throttle suppresses a same-or-subset reason set. A suppressed episode logs exactly one WARNING.
5. No `DEGRADED -> RUNNING` happens while the durable intent is OPEN or corrupt, or while any refusal remains, including a second AMBIGUOUS inside the window (F6). A refusal during RESUMING ends DEGRADED.
6. RUNNING is not proof the node can trade. Order admission is unchanged by the resume (§2.4).
7. **(rewritten, CH1/CM1/CM2) Neither the activation nor the daily supervisor cycle strands an OPEN intent with the node down.**
   - Every OPEN shape has a named autonomous clearing path (§5.3).
   - The supervisor launches over any decodable OPEN intent so the node's resolver can retire it (§2.9).
   - A CRITICAL raised while an intent is OPEN names the automated next action (§2.10).
8. **(new, CH1) A no-id AMBIGUOUS is resolved autonomously:**
   - (a) A venue order or fill found in complete reads is adopted, its venue id is taken, and the existing with-id GET path resolves it. A found fill goes through the existing accept-fill path.
   - (b) Nothing found in all complete reads, with the positions baseline unchanged after the minimum age, retires it `RESOLVER_NO_ID_NO_FILL`. **(r5, DM4)** "Unchanged" is judged on the holding **delta** against a pre-POST snapshot when one is valid, else on the absolute r4 rule (§2.8.6).
   - (c) Anything contradictory or incomplete keeps it AMBIGUOUS and pages CRITICAL. It is never retired on partial evidence. **(r5)** It is re-checked automatically every 60 s and has a named automated exit (§2.8.6, §7). **(r6, item 1)** A holding moved by the operator's own manual trades on the slug is reconciled against those trades in the same scan (route (d)).
   - (d) **(r5, DH1)** The node retires `RESOLVER_NO_ID_NO_FILL` only when the running supervisor has proven it can decode that member (§2.11). Otherwise the intent stays AMBIGUOUS and pages CRITICAL.

---

## §1 Null hypothesis (L-1): what Nautilus and Breezy already provide

| Need | Native / existing capability | Verdict |
|---|---|---|
| Leave DEGRADED | `Component.resume()` (`component.pyx:2003-2032`). Edges `(DEGRADED, RESUME) -> RESUMING` (`:1650`) and `(RESUMING, RESUME_COMPLETED) -> RUNNING` (`:1641`). The action `_resume` is `pass` (`:1904-1906`) and is never overridden. | **REUSE as-is.** |
| Re-enter DEGRADED after a race | `Component.degrade()` (`:2098-2127`) is legal from RUNNING (`:1638`). There is no `(RESUMING, DEGRADE)` edge (`:1640-1642`). | **REUSE**, plus the post-resume re-check (§2.6). |
| Publish the transition | `_trigger_fsm` publishes `ComponentStateChanged` stamped `ts_event` (`:2187-2225`). | REUSE. It is the throttle's clock. |
| Run periodically on the loop thread | `install_refusal_repoll_timer` (`component_health_watch.py:490-625`), armed in `trade_cli._run_node` (`:625-635`). FU-8b calls installer closures from the timer. | **REUSE.** |
| "Is an intent open?" | `SubmitIntentLatch.is_latched()` (`submit_intent.py:378-389`), fail-closed. | **REUSE.** |
| Clear AMBIGUOUS on retirement | The inline block in `_resolve_terminal_zero` (`:3100-3112`). | **REUSE the same block** in accept-fill and no-id no-fill. |
| Alert re-notify | `health.AlertState`: false→true always fires, so it cannot suppress a transition. | Not reusable. An in-closure throttle is used instead (§2.3). |
| **No-id resolution, native (CH1)** | The Nautilus in-flight poller (`LiveExecEngine` `inflight_check_*`) asks the adapter by client order id. This venue has none (`client.py:401-404`; SDK `CreateOrderParams` has no such field), and the poller's retry exhaustion resolves FAILED, a false terminal. L-36 keeps it disabled (`node_config.py:689-712`), so it is **rejected by a binding lesson**. `generate_order_status_report` collapses four failure shapes into `None` (ARCH M1, `client.py:2405-2410`), so it is not a fail-closed evidence source. | **Native gap is real. Extend Breezy's own resolver.** |
| No-id evidence reads | `self._private_read(PORTFOLIO_POSITIONS_PATH)` and `self._declared_positions`; `self._read_open_orders()` (strict `parse_open_orders`); the activities page loop of `_order_trade_activity` (`:3319-3440`); the AC4(e) baseline `_resolver_leg_holding_qty`/`_durable_net_qty` (`:2932-2955`); the past-day instrument loader (`:2637-2702`). All are already in the resolver allowlist. | **REUSE every read seam. No new endpoint and no new egress.** |
| Attribute a venue order without its id | The venue echoes our body fields on every activities order object and open-order row (captured). The singleton latch guarantees no other Breezy order can be created while this intent is OPEN (`submit_intent.py:403-409`). The durable venue-id map (`VENUE_ORDER_ID_KEY_PREFIX`, `client_order_id_for`, `:4587`) names every prior Breezy order that got an id. | **REUSE the latch window and the map. Add one pure attribution module (§2.8.5).** |
| Resolve once an id is known | The entire with-id path: GET → predicates → `_resolve_terminal_zero` / `_resolve_accept_fill` (`:2703-2983`), including AC4 contradictions, the 120 s floor, SAFETY H2 and AC6b. | **REUSE unchanged**, by adopting the id into the durable context. |
| Clear an OPEN intent while no node runs | The node's own boot: `_connect` awaits one immediate resolver pass before reconciliation (`client.py:2019-2025`) and then runs the periodic resolver (`:2040-2043`). Nothing on the boot path refuses on OPEN. Only the supervisor does. | **REUSE. The supervisor launches the clearing node instead of refusing (§2.9).** |

Conclusion. The genuinely new pieces are listed below. Everything else is reuse.
- An in-closure throttle and one episode counter (r3).
- A pre-POST durable context (an existing callee, `_note_ambiguous_open`, called earlier).
- One no-id resolver branch, with a pure attribution module.
- One retirement-reason member.
- One additive supervisor launch action.

---

## §2 Design

§2.1–§2.6 are r3's design, carried unchanged except where a line says "r4". §2.7 is re-measured. §2.8–§2.10 are new.

### 2.1 Resume call site: a sync client method, driven by the runtime re-poll timer

**New public sync method on `PolymarketUSExecutionClient`: `resume_if_refusals_cleared() -> bool`.**
- Placed directly after `_refuse`, before `__repr__` (`client.py:~5977`).
- Returns True iff the call ends with the client RUNNING.
- Its callees are exactly `self._latch.is_latched`, `self.resume`, `self.degrade`, `self._log.info` and `self._log.warning`.

Body, in order:
1. `if not self.is_degraded: return False`. This skips RUNNING, RESUMING, DEGRADING, STOPPING and STOPPED. `(STOPPED, RESUME)` is a legal native edge (`:1646`).
2. `if self._trading_refusals: return False`. This is the F6 guard: a second AMBIGUOUS appended by `_refuse` (`:5971`) keeps the client DEGRADED (T24).
3. `if self._latch is None: return False`. Fail-closed.
4. `try: latched = self._latch.is_latched()`, then `except Exception:` log a WARNING with the type name only and `return False`.
5. `if latched: return False`. This covers OPEN and corrupt, and covers F6 a second time.
6. `self.resume()`.
7. **Post-resume re-check (A5):** `if self._trading_refusals and not self.is_degraded:` log one WARNING `health: a refusal landed during RESUMING; re-degrading`, call `self.degrade()` and `return False`.
8. Log `self._log.info("health: resumed from DEGRADED (no refusals, no open submit intent)")` and `return True`.

Thread safety. The method runs on `node.kernel.loop` (the `_poll` hop), the same loop as the resolver, `_submit_order` and `_refuse`, and it has no `await`. A refusal can interleave only re-entrantly, from a synchronous subscriber to the RESUMING publish, and step 7 closes that.

**New read-only property: `ambiguous_refusal_clears -> int`** (F6). Its body is `return self._ambiguous_refusal_clears`, with no callee.

**Runtime trigger: `_exec_client_resume_handler(node) -> Callable[[object], None]`** in `runtime/trade_cli.py`.
- It sits beside the `_exec_client_*_reader` helpers and uses `getattr(..., None)`.
- It is appended LAST to `handlers=` at `trade_cli.py:629`, and `_poll` isolates each handler.
- If the timer fails to arm (`:634-635`), the client stays DEGRADED, which is today's behaviour. The existing `refusal re-poll timer NOT armed` report names the loss.

**Why not the alternatives** (unchanged from r1):
- The resolver: trips E0-NOSEND-RESOLVER.
- `_submit_order`: trips E0-NOSEND.
- A client-owned `set_timer`: runs on a tokio thread (L-16).
- A clear publishes no `ComponentStateChanged`.
- A new coroutine: breaks E0-INERT.
- A runtime predicate: would read private state from runtime.

### 2.2 Accept-fill clears AMBIGUOUS (A3, coordinator ruling)

**The change.**
- In `_resolve_accept_fill`, as the **last statement**, after `self.generate_order_filled(...)` (`:3298-3317`), add the same inline block `_resolve_terminal_zero` uses (`:3100-3112`).
- Then `if len(...) changed`: assign the new list, `self._ambiguous_refusal_clears += 1` (F6), and one INFO line: `resolver: cleared the AMBIGUOUS trading refusal (...) on fill retirement of intent <id>`.
- The zero-fill block gains the same one counter line inside its `if len(kept_refusals) != len(self._trading_refusals):` branch.
- `__init__` initialises `self._ambiguous_refusal_clears: int = 0` beside `self._trading_refusals` (`:1697`).

**Why last.** Any raise above it keeps the refusal, which is the conservative direction. That covers `record_fill` (`_FILL_WRITE_FAILED`), the venue-id map, `_retire`, `true_up_booking`, `unrestore_live_trading_budget` and `generate_order_filled`. Once `_retire` has run, the next pass takes the `current is None` early return (`:3165-3167`).

**The cross-session early return (`:3296-3297`) never reaches the clear. This is intended and complete.**
- `AMBIGUOUS_REASON` has exactly two `_refuse` producers, both in `_submit_order` (`:5556`, `:5800`). An entry can therefore exist only in the submitting process.
- That process finds the order in `self._cache` (`:4244-4245`).
- A respawn has no entry to clear.
- The latch is a singleton.
- T15(iii) pins the producer premise. **r4 adds no `_refuse` call site anywhere**, so the 25-producer pin in `test_exec_refusal_health_surface.py` stays unedited.

**Kept refusals.**
- `_VENUE_ID_MAP_WRITE_FAILED` (`:3253`), `_RESOLVER_FILL_UNBUDGETED` (`:3291`) and every other reason stay.
- So does the informational `RESOLVER_FILL_NOT_BOOKED` latch, which is a separate dict.

**Firewall.**
- The block's callees (`self._latch.current_open`, `len`, `self._log.info`) are already allowlisted, and the counter is an `AugAssign`.
- **Stop condition:** if either block needs any other callee, stop and report.

**This changes order admission (intended).** After a GET-confirmed fill, a later take is admitted again. The refusal has no subject left, because:
- `record_fill` is durable;
- `true_up_booking` charged the filled cost;
- `_retire` closed the singleton.

Exposure stays bounded by the permit and its budget, the two operator caps, the latch and the family halt.

**Predicate strength (F4)**, from `client.py:2788-2983`:

| Requirement | Zero-fill retirement | Accept-fill retirement |
|---|---|---|
| Terminal GET in THIS run (SAFETY H2, `:2840-2843`) | Terminal with `filled_qty == 0` | Terminal with `filled_qty > 0`, or FILLED |
| eof-complete positions read with a determinable leg (`:2808-2837`) | Required | Required |
| Independent second source | Complete activities join with **0** trades, and no create-time fill evidence (`:2880-2913`) | Own-leg LONG, or a complete join with **≥1** trade (`:2968-2970`) |
| Contradiction | CRITICAL `resolver_evidence_contradiction`; stays AMBIGUOUS | WARNING; stays AMBIGUOUS |
| Extra gates | 120 s min age; same-day holding baseline | None |

**Why the gates differ.** Zero-fill proves an absence, which is exposed to eventual consistency. Accept-fill proves a presence, which a read can delay but cannot fabricate. A false "fill" charges the budget, which is the conservative direction.

**Required before merge:** a written security-reviewer sign-off that the accept-fill predicate is at least as strong as the zero-fill one for clearing the AMBIGUOUS refusal, or naming the gap. **r4 extends the sign-off to the no-id no-fill predicate (§2.8.6).**

**Docstring carve-out.** Invariant 1 at `client.py:177-178` becomes "Sole carve-out: resolver-retired terminal zero-fill, accept-fill or no-id no-fill clears the AMBIGUOUS refusal only (2026-10-02; accept-fill and no-id 2026-10-03)".

### 2.3 Re-alert with a throttle; AMBIGUOUS is never throttled (A2 + F3)

All of this lives in `install_component_degraded_alert` (`component_health_watch.py:628-703`).

**New constant:**
```python
#: One hour. Caps a storm of NON-AMBIGUOUS repeat episodes at one identical
#: CRITICAL per hour. AMBIGUOUS episodes are exempt (F3): each one alerts.
#: Same units/name as health.AlertState.
DEGRADED_ALERT_RENOTIFY_AFTER_NS: Final[int] = 60 * 60 * 1_000_000_000
```

**New keyword-only parameters:**
- `renotify_after_ns: int = DEGRADED_ALERT_RENOTIFY_AFTER_NS`. A `bool`, a non-int, or a value ≤ 0 raises `ValueError`.
- `ambiguous_reason: str | None = None`. `trade_cli` passes `submit_chain.AMBIGUOUS_REASON`, so the module imports nothing from `adapters`.
- `ambiguous_clears: Callable[[], int] | None = None`.

**Closure state:**
- `alerted: set[str]`;
- `last_alert: tuple[int, frozenset[str]] | None`;
- `ambiguous_alerted: int = 0`.

**Handler rules on `ComponentStateChanged` for `component_id`:**
- **RUNNING:** `alerted.discard(component_id)`. `last_alert` is not reset.
- **DEGRADED, already alerted this episode:** return. This preserves `test_a_second_refusal_does_not_re_alert`.
- **DEGRADED, first in this episode:**
  1. `alerted.add`.
  2. Read the reasons; the fallback is unchanged.
  3. **If `ambiguous_reason` is in the reasons, always emit** and set `last_alert` and `ambiguous_alerted`.
  4. Otherwise compute `elapsed = event.ts_event - last_alert[0]`. Suppress iff `0 <= elapsed < renotify_after_ns` and `frozenset(recorded) <= last_alert[1]`. Suppression logs one WARNING `component_degraded alert throttled component=%s reasons=%d since_last_s=%d`.
  5. Otherwise emit and set `last_alert`.

**Any other event (a re-poll tick, F6):** if either new kwarg is `None`, return. Otherwise compute `episodes = ambiguous_clears() + (1 if ambiguous_reason in reasons() else 0)`. If it exceeds `ambiguous_alerted`, emit one CRITICAL per owed episode and set `ambiguous_alerted`. This is never throttled.

**Semantics:**
- The first DEGRADED always alerts.
- Every AMBIGUOUS episode alerts exactly once, by transition or on the next tick.
- Non-AMBIGUOUS repeats re-notify at most once per hour per repeated reason set, and a new reason bypasses.
- A backwards clock alerts, and a reader failure is a new reason set.
- Everything runs single-threaded on the loop.

**r4.** The no-id no-fill clear (§2.8.6) increments the same counter, so a no-id episode is counted exactly like the other two terminals.

### 2.3a Why a counter (F6)

The second AMBIGUOUS in the clear-to-resume window is invisible to every existing signal:
- `_refuse` does not degrade (`:5970-5976`).
- The reason string is identical.
- An add-and-clear can fall between two ticks (3.2 s same-process fill retirement, §2.7).

Rejected alternatives:
- Degrade on an empty list: reverses R-6.5a and moves the 25-producer pin.
- Tag the entry with the intent id: edits both producers.
- Resume from the resolver: `self.resume` is not allowlisted, and widening is forbidden.
- Read the intent id from runtime: needs a second store reader.

### 2.4 Scope: what RUNNING does and does not mean (A4)

- RUNNING **never gates sending and is not proof the node can trade.**
- Sending stays gated, unchanged, by:
  - `_trading_refusals` (`_submit_order:5357`);
  - the live-trading permit and its budget;
  - the submit-intent latch;
  - the strategy-side family halt (`trial_day_latch.family_halt_key`);
  - the operator caps.
- `resume_if_refusals_cleared` reads only `is_latched` and `_trading_refusals`, and writes none of the gates.
- Operator liveness stays: process, log mtime, **permit unexpired**, tape advancing.
- Only the accept-fill and no-id clears change admission.

**Proof the resume cannot send** (each step is pinned by a §3 test):
1. **Trigger chain:** `LiveClock timer -> _on_timer -> call_soon_threadsafe(_poll) -> _exec_client_resume_handler -> resume_if_refusals_cleared()`.
2. **Callee set:** exactly `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`, with no await or async (T5).
3. **Native actions:** `_resume`/`_degrade` are `pass` (T6 MRO pin).
4. **Events:** only `events.system.POLYMARKET_US`. Its subscribers are alert-only (T7).
5. **Admission unchanged:** T20, T21.
6. **Firewall:** T8a/T8b.

### 2.5 The "never resume while AMBIGUOUS is open" invariant

The guard is layered:
- (a) Every clear runs only when `current_open() is None`.
- (b) The method requires an empty `_trading_refusals`.
- (c) The method requires `is_latched() is False`.
- (d) Steps 1–6 run in one synchronous frame, and step 7 re-checks.

T2, T3 and T24 pin these.

### 2.6 Races (A5 + F6)

| Race | Outcome | Test |
|---|---|---|
| Refusal **during RESUMING** (re-entrant subscriber only; latent) | Step 7 logs a WARNING and degrades. Events: RESUMING, RUNNING, DEGRADING, DEGRADED. The alert fires subject to §2.3. | T22 |
| Refusal **after resume** | DEGRADED; the alert fires subject to §2.3. AMBIGUOUS always alerts. | T23 |
| **Second AMBIGUOUS before resume (F6)** | Resume refused (steps 2 and 5). The tick emits one CRITICAL from `clears + present`. | T24 |
| Resume vs an in-flight take | `is_latched` is True from `arm` onward, so no resume. | T2 |
| Resume from DEGRADING | No-op. | T4(iii) |
| **r4: resolver no-id pass vs an in-flight POST** | `_post_in_flight_intent_id` skips the no-id branch while this process's POST is awaited. The 300 s min age is a second bound (§2.8.4). | T31 |
| **r4: a no-id pass on the same intent as a with-id rewrite** | Both run on one loop. The with-id `_note_ambiguous_open` overwrites the same key synchronously, before any later resolver pass reads it. | T30 |

### 2.7 Measured volume (A2), re-measured read-only in r4 — **r3's figures were off by one**

Source and method:
- The store was copied with the sqlite backup API from a `mode=ro` connection, and the copy was queried. Keys: `exec/polymarket_us/intent/history/*` and `intent/current`.
- `submit_intent.py` has no prune path.
- **Correction:** `intent/current` (`81faafc3…`, RETIRED) duplicates its own history record. r3 counted it as a 25th intent. There are **24 distinct intents**, and every one of them POSTed an order.
- Window: 2026-09-05 20:19Z to 2026-10-03 (29 calendar days).
- Cross-check: the node logs contain exactly **6** `create-order outcome is AMBIGUOUS` events (09-05, 09-11, 09-13, 09-23, 10-01, 10-02). That equals 5 resolver-retired intents plus 1 operator-cleared intent.

| Metric | Value |
|---|---|
| Takes (intents) | **24** over 10 active days. 0.83/calendar day; max 6 (10-01). Since 10-01: 13 (10-01 = 6, 10-02 = 5, 10-03 = 2 partial) ≈ **4.3/day** |
| Retirement reasons | 18 `ACCEPTED_WITH_DURABLE_FILL`, 3 `STATUS_REPORT_ZERO_FILL_TERMINAL`, 2 `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, 1 `OPERATOR_CLEARED` |
| AMBIGUOUS episodes | **6/24 = 25 %**: 5 with-id (resolver) plus 1 no-id (operator) |
| IOC-miss rate (zero-fill terminal / takes) | 3/24 = 12.5 %; 2/13 = 15.4 % since 10-01 |
| Max AMBIGUOUS per day | **1** |
| Create-to-retire | Same process: 3.2 s (fill), 120.8 s and 138.3 s (zero-fill). Cross-process: 6.1 h (fill, 09-11), 26.9 h (zero-fill, 09-23, the D5 incident) |

**Period mismatch (LOW), kept.** A 2.3-day take rate times a 29-day fraction:
- 4.3 × 0.154 ≈ **0.66/day** (post-10-01 fraction);
- 4.3 × 0.25 ≈ **1.1/day** (29-day fraction, now including the no-id episode).
The plan sizes to the upper figure.

**Expected `component_degraded` volume.**
- AMBIGUOUS: exactly one per episode, unthrottled: ≈0.21/calendar day historically, ≈0.66–1.1/day now, observed max 1/day.
- Bounded by the take rate through the singleton latch (`submit_intent.py:403-409`).
- Non-AMBIGUOUS: the throttle suppresses 0 observed episodes.

### 2.8 The automated no-id resolver (CH1, coordinator ruling: mandatory)

#### 2.8.0 Binding-lesson conflict, surfaced (CLAUDE §7)

L-36's rule (`docs/core/LESSONS.md:1336-1340`) says:
- "B10 still holds: `clear_submit_intent` is not invoked and stays the only no-id path".
- The resolver is "a new retire caller for an AMBIGUOUS OPEN intent, **with a venue order id only**".
- The code comment at `client.py:5826-5828` repeats this.

CH1's ruling (option (a) mandatory; "nothing except the two caps may need an operator") supersedes the "only no-id path" clause. It does so the same way L-36 itself superseded R-7 item 5 "for the with-id class only".

**This plan does not proceed silently over the lesson:**
- The coordinator ruling is the authority.
- The change amends L-36 in the same merge. A new dated paragraph says: "Superseded 2026-10-03 (AMBIG-LATCH-RESUME r4, coordinator ruling CH1) for the no-id class: an automated no-id resolver retires on complete reads only. `clear_submit_intent` stays available and is never invoked by code."
- Every other L-36 clause is preserved:
  - `classify_create_order_outcome` stays byte-unchanged.
  - The pin `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking` stays green and is not reused.
  - Fail-closed on every read failure.
  - The in-flight poller stays disabled.
- **If the coordinator does not confirm the supersession in the r4 review, stop before step 1 of §8.**

#### 2.8.1 Premises verified (and two design-floor premises corrected)

**P-a: there is no client order id at the venue.**
- The create body carries exactly the keys at `submit_chain.py:376-387` (entry) and `:558-569` (exit).
- SDK `CreateOrderParams` (`types/orders.py:111-125`) has no client-id field.
- `client.py:401-403` says "This venue issues no client order id".
- **So the design floor's "activities join by `client_order_id`" cannot be an id join.**

The faithful equivalent:
1. The pre-POST context is keyed by **`intent_id`**. That id is returned by `arm` (`:5538`) before the POST, is a fresh UUID4, and uses the same `RESOLVER_CONTEXT_KEY_PREFIX + intent_id` scheme as every existing context. The context **carries** `client_order_id`.
2. The context also carries the exact wire fields the venue echoes on its own order objects: `marketSlug`, `price.value`, `outcomeSide`, `action`, quantity 1, `TIME_IN_FORCE_IMMEDIATE_OR_CANCEL` and `MANUAL_ORDER_INDICATOR_AUTOMATIC`. All of these are captured on every activities aggressor/passive order object.
3. The join is an **attribution join on the venue's echo of our own body**, inside the singleton-latch time window.

**P-b: the open-orders endpoint has no `eof`.**
- `GetOpenOrdersResponse` is `{orders}` only (`types/orders.py:171-174`). The captured `orders_open_all.json` payload keys are `['orders']`.
- Its completeness criterion is **one strict parse of the whole list**: `parse_open_orders` raises on malformed rows (`_read_open_orders`, `:5054-5074`), and a raise counts as INCOMPLETE.
- "eof-complete" in the design floor applies to positions and activities.

**P-c: the venue's timestamp window.**
- "Timestamps must be within **30 seconds** of server time" (`docs_snapshots/api-reference_authentication_2026-08-25.md:82`).
- The local signer enforces the same ±30 s (`signing.py:89`, `write_transport.py:102-109`).
- The headers are signed immediately after `arm` (`:5545-5548`). So a POST the venue accepts was accepted no later than about `created_ns + 30 s` venue-time.
- An IOC is terminal within `maxBlockTime` = 5 s (`submit_chain.py:134`).

**P-d: Breezy never rests an order.** Both bodies hard-code `tif = _TIF_IOC` (`submit_chain.py:381, 563`). A Breezy fill is therefore always the **aggressor** leg of a trade row.

**P-e: the account carries non-Breezy activity.** The captured pages show:
- MANUAL orders, including `TIME_IN_FORCE_DAY` resting orders and non-weather markets;
- older AUTOMATIC trades (2026-08-05/08/09);
- AUTOMATIC counterparty legs.
Attribution must therefore never assume "every aggressor is Breezy" (§2.8.5).

#### 2.8.2 How often the no-id shape occurs (store + logs, read-only)

| Fact | Value |
|---|---|
| Distinct intents | 24 (§2.7) |
| AMBIGUOUS intents | 6 |
| **No-id AMBIGUOUS** | **1**: `ac87b697…` |
| With-id AMBIGUOUS | 5. Each has a `exec/polymarket_us/resolver/<id>` context key, and exactly those 5 keys exist |
| Share of AMBIGUOUS | 1/6 = 16.7 % |
| Share of intents | 1/24 = 4.2 % |
| Since the no-id episode | 0 of the next 23 takes (28 days). 0 `create-order AMBIGUOUS detail: path=exception` lines in any node log. 0 `durable store raised before the post` lines |
| Expected rate | At the current ≈4.3 takes/day: 4.3 × 0.042 ≈ **0.18/day, about one every 5–6 days**. Not negligible, so the automated resolver is justified on frequency as well as policy |

**The single no-id episode in detail:**
- `O-20260905-201949-L001-SFO-1`: BUY 1 `tc-temp-sfohigh-2026-09-05-gte73lt74f` @0.28 IOC, created 2026-09-05 20:19:49.006Z.
- It was the first live order, 28 min after a node launch that followed a venue 5xx outage.
- The refusal came 5.2 s after submit, with no detail line. Per `docs/evidence/ORDER1_NO_ORDERSUBMITTED_2026-09-26.md:96-108` it is consistent with the classified `response is None` branch (`submit_chain.py:1219-1233`); detail logging was added the same evening.
- It was retired `OPERATOR_CLEARED` (history `retired_ns == created_ns`, the CLI's `now_ns=current.created_ns`, `clear_submit_intent_cli.py:138`). The clear was at 2026-09-06 01:07:28Z, 4.8 h later, on the operator's evidence file `evidence_for_clear_submit_intent.json`:
  - positions `{}`, eof;
  - open orders `[]`;
  - `activities_mentioning_market: []`.
- **That evidence is exactly r4's no-fill predicate.** T41(vii) replays the tracked capture through the attribution classifier as a real-data positive control.

#### 2.8.3 Pre-POST durable context (the design floor: "persist at arm time, before the POST")

**`AmbiguousResolverContext` gains four trailing-optional fields** (`client.py:1085-1142`).
- Each follows the AR-N6 shape already used by `create_detail`/`order_side`: JSON keys `wireMarketSlug`, `wirePrice`, `wireOutcomeSide`, `wireAction`, each `str | None = None`, read via `.get` outside the strict `try`.
- An old blob decodes them as `None`. No schema version, no migration.
- A new constant `submit_chain.NO_VENUE_ORDER_ID: Final[str] = ""` denotes "no venue id yet". It is stored in the existing `venue_order_id` field.

**`_note_ambiguous_open` gains these keyword-only parameters:**
- `wire_market_slug`, `wire_price`, `wire_outcome_side`, `wire_action` (default `None`);
- `register_booking: bool = True`.
- When `register_booking` is False, it writes the context but skips `self._ambiguous_bookings[intent_id] = booking`, so a take that ends non-AMBIGUOUS leaves no in-memory entry.
- **(r5, DM4)** `capture_holding_baseline: bool = False`. Only the pre-POST call passes True (below).
- Existing callers and tests are unaffected by the defaults.

**(r5, DM4) The pre-POST holding snapshot.** `AmbiguousResolverContext` gains three more trailing-optional AR-N6 fields: `baselineVenueNet: str | None`, `baselineDurableNet: str | None` and `baselineTsNs: int | None`. Old blobs decode them as `None`.
- **Source.** No new venue read is possible before the POST (E0-NOSEND; the POST is `_submit_order`'s only `await`). The snapshot is therefore the **existing durable venue-holding evidence**: the `STARTUP_EVIDENCE_KEY` record, an eof-complete positions GET at most ~65 s old while the resolver is healthy (§Evidence r5).
- **Computed by** a new sync helper `self._holding_baseline(instrument_id, slug) -> HoldingBaseline | None`, called only from inside `_note_ambiguous_open` when `capture_holding_baseline` is True. It reads only local state: `self.read_startup_position_evidence()`, `self._read_fill_index`, `self._store_get` and `DurableFillRecord.from_bytes`.
- **It returns `None`** (no baseline, so the resolver uses the absolute r4 rule) when any of these hold:
  - the evidence is absent, undecodable, `position_read_refused`, or not `eof_complete`;
  - the slug's `net_position` is `None` (unknown). An absent slug on an eof-complete record is `"0"`;
  - `_durable_net_qty` is `None`;
  - **(r6, item 1) the baseline is older than the attribution window start:** `now_ns - evidence.ts_ns > _NO_ID_WINDOW_BACKSKEW_NS` (120 s). `now_ns` here is the take's `created_ns`. This guarantees the activities scan, which reads back to `created_ns - 120 s`, covers every manual trade made after the snapshot, which route (d) needs. The resolver's 60 s refresh keeps the evidence ≤ ~65 s old, so this only removes a baseline that the refresh has already let go stale;
  - **the baseline is not quiet:** some durable fill on this instrument has `ts_event > evidence.ts_ns - _NO_ID_BASELINE_QUIET_NS`, with `_NO_ID_BASELINE_QUIET_NS: Final[int] = 300 * 1_000_000_000`. This excludes a snapshot that may not yet reflect a recent Breezy fill (or exit) on the same instrument. A lagging exit record could otherwise mask our own untracked entry fill. Resolver-written records stamp `ts_event` at discovery, an upper bound, so the quiet test errs toward "not quiet".
- **Otherwise** it returns `(baselineVenueNet = the slug's signed venue net, baselineDurableNet = str(_durable_net_qty), baselineTsNs = evidence.ts_ns)`.
- **Why it is safe in `_submit_order`.** The call happens inside the already-permitted callee `_note_ambiguous_open`, so `_submit_order` gains no callee and the set-equality pins stay unedited. T42(vi) pins `_note_ambiguous_open` and `_holding_baseline` as await-free, with no `_private_read`, no sender reference, and exactly the one existing `self._store_set` (the context key). A raise inside `_holding_baseline` is caught there and yields `None`, so it can never block or deny a take.

**`_submit_order` (H9). Inserted between a successful `arm` (`:5544`) and `sign_headers` (`:5545`):**
```python
try:
    self._note_ambiguous_open(
        intent_id=intent.intent_id,
        venue_order_id=submit_chain.NO_VENUE_ORDER_ID,
        order=order,
        notional_usd=order_notional,
        booking=booking,
        now_ns=now_ns,
        register_booking=False,
        capture_holding_baseline=True,  # r5 DM4
        wire_market_slug=body["marketSlug"],
        wire_price=body["price"]["value"],
        wire_outcome_side=body["outcomeSide"],
        wire_action=body["action"],
    )
except Exception:  # noqa: BLE001 - fail closed: never POST without a durable context
    if booking is not None:
        self._ledger.release_booking(booking, now_ns=now_ns)
    return self._deny(order, submit_chain.STORE_RAISED_REASON, now_ns)
self._post_in_flight_intent_id = intent.intent_id
```

**The POST `try`** (`:5549-5569`) gains `finally: self._post_in_flight_intent_id = None`. The except body has no `await`, so nothing interleaves before the `finally` runs.

**Two booking registrations, one per no-id branch.** Each is a subscript assignment, not a call: `self._ambiguous_bookings[intent.intent_id] = booking`.
- In the exception branch, after the existing `_refuse` and the two `_log.error` lines, and before `if submit_chain.is_cancelled(exc): raise`.
- As a new `else:` of `if outcome.venue_order_id is not None:` (`:5825`).
- The with-id `_note_ambiguous_open` call (`:5845-5855`) gains the same four `wire_*` kwargs. It overwrites the same key with the venue id and keeps the echo fields.

**Why these exact statements:**
- **No new callee in `_submit_order`.** `self._note_ambiguous_open`, `self._ledger.release_booking` and `self._deny` are all in `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (`test_execution_egress_firewall_guard.py:1938-2085`).
- `body[...]` is a `Subscript`, and the attribute writes are `Assign`. So the **set-equality pin on that allowlist** (`:3110-3200`) and its twin in `test_cage_rule_constants_are_pinned.py:~520-600` stay **unedited and green**.
- The deny chain before `arm` (`:5355-5536`) is byte-identical. The PR records an `ast` prefix sha check up to and including the `arm` statement.
- **No `await` between `arm` and the context write.** The resolver, which runs on the same loop, can therefore never observe an r4-armed OPEN intent without its context.
- A context-write failure **never POSTs**:
  - the booking is released;
  - the deny reason is the existing `STORE_RAISED_REASON`;
  - no `_refuse` is added (25-producer pin untouched);
  - the intent stays OPEN **without** context and is retired by the window-only mode (§2.8.6(B)) after the min age. That is true by construction, because nothing was sent.
  - The permit slot already consumed is lost for the day, which is the conservative direction.

**Store growth.** One context key per take, about 0.5 KB. Existing contexts are never deleted either. At about 4.3 takes/day that is about 0.8 MB/year, which is negligible.

#### 2.8.4 When the no-id branch may act: in-flight guard, min age, window

- **Dispatch.** In `_resolve_ambiguous_intents` there are two dispatch points:
  1. **(A) Attributed mode.** After the existing instrument block (`:2637-2702`, which already loads past-day instruments) and **before** the GET at `:2703`: `if context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID: await self._resolve_no_id_intent(current.intent_id, current.created_ns, context, instrument); continue`.
  2. **(B) Window-only mode.** At the existing context-absent `continue` (`:2538-2544`): `await self._resolve_no_id_intent(current.intent_id, current.created_ns, None, None); continue`.
- **The with-id path from `:2703` onward is byte-unchanged.**
- **The in-flight guard is the first statement:** `if intent_id == self._post_in_flight_intent_id: return` (debug log). It is the same-process bound, independent of HTTP timeouts. `post_order` passes no `timeout_secs` (`write_transport.py:183-185`), so the POST duration is not bounded by our code.
- **The min age is the second statement, before any read:** `if now - created_ns < _RESOLVER_NO_ID_MIN_AGE_NS: return`.
  - `_RESOLVER_NO_ID_MIN_AGE_NS: Final[int] = 300 * 1_000_000_000`.
  - Rationale (P-c): the venue's acceptance deadline is about `created_ns + 30 s`, plus a clock offset of at most 30 s, plus the 5 s `maxBlockTime`. That fixes the order's fate by about `created_ns + 65 s`.
  - The remaining ≥ 235 s is eventual-consistency margin for the activities and positions feeds, about 2× the with-id 120 s floor (`:1516`) that gates the same activities read.
  - **(r5, DL1) Measured latencies beside the margin:**
    - same-process create-to-fill-retirement (POST, GET, positions and activities all visible): **3.2 s** observed (§2.7). The 300 s min age is ≈ 94× that;
    - venue trade `createTime` minus local `created_ns`: **0.075–0.215 s** over 9 Breezy fills (§Evidence r5). The 120 s forward window (below) is ≈ 558× the maximum.
  - So there are **no extra venue reads during a normal take**. The existing tree test `test_open_intent_without_a_durable_context_makes_no_get_and_stays_open` (`test_current_rung_hold_ambiguous_resolver.py:5705`), which runs its passes at age ≈ 0, stays unedited and green.
- **(r5, DM1) The attribution window is bounded on both sides: `[created_ns - _NO_ID_WINDOW_BACKSKEW_NS, created_ns + _NO_ID_WINDOW_FORWARD_NS]`, both ends inclusive.**
  - `_NO_ID_WINDOW_BACKSKEW_NS: Final[int] = 120 * 1_000_000_000`, as in r4. That is 4× the 30 s venue window, so a skewed venue `createTime` cannot fall before the window.
  - `_NO_ID_WINDOW_FORWARD_NS: Final[int] = _NO_ID_FATE_FIXED_NS + _NO_ID_WINDOW_FORWARD_SKEW_NS = 65 s + 55 s = 120 s`.
  - `_NO_ID_FATE_FIXED_NS = 65 s` is P-c: 30 s venue timestamp tolerance, plus 30 s clock offset, plus 5 s `maxBlockTime`.
  - **(r6, item 4) The skew is a choice, not a derivation: `_NO_ID_WINDOW_FORWARD_SKEW_NS = 55 s`.** r5's "derived" was wrong and is withdrawn. 55 s is chosen **only** so that the forward bound equals the back-skew (120 s), giving a window symmetric about `created_ns`. Nothing derives the number 55. What it has to absorb is three terms the 65 s does not cover:
    - (i) local `created_ns` to `sign_headers`: one synchronous SQLite commit for the pre-POST context plus header signing. That is milliseconds and has no `await`;
    - (ii) venue-side queueing between accepting and matching, which no venue doc bounds;
    - (iii) `createTime` granularity.
    - Term (ii) has no documented bound, so no derivation is possible. The evidence is empirical: the measured total of all three, plus any real clock offset, is 0.075–0.215 s (n = 9), so 55 s is ≈ 256× the measured maximum and the whole window ≈ 558×. T32 pins the constant at exactly 55 s and the sum at 120 s.
    - **Why not tighten.** A smaller skew would shrink R-OTHER-AUTOMATION's 240 s exposure (§7), but a real late leg of ours would then be `leg_after_attribution_window`, a CONTRADICTION that fails toward liveness loss. With n = 9 and no documented bound on (ii), the plan keeps the symmetric choice and records the exposure instead.
  - **Rows after the window end are scanned, never attributed.** A leg later than `created_ns + 120 s` that is not ignored by rules 1, 3 or 4 of §2.8.5 (including an exact echo match) is unattributed: `CONTRADICTION("leg_after_attribution_window")`. Under the singleton latch no other Breezy order exists while this intent is OPEN, so such a leg has no innocent Breezy explanation.
  - **The window bound is now inside the min age:** 300 s ≥ 120 s + 180 s of feed margin, so every row that could be attributed has had ≥ 180 s to appear before the first no-id read.
  - A prior Breezy take inside the back-skew is real: 4 intents were created within 3 s on 2026-09-30. Its rows are excluded by the durable venue-id map (§2.8.5).
- **(r5, DM4) Re-check cadence.** After any `CONTRADICTION` or `INCOMPLETE` verdict, the branch makes no further reads for that intent until `_NO_ID_RECHECK_INTERVAL_NS: Final[int] = 60 * 1_000_000_000` has passed. The state is a plain dict, `self._no_id_next_check_ns[intent_id]`, written by subscript assignment with no callee. The re-check is automatic and indefinite, at most 3 GETs (positions, open orders, ≥1 activities page) per minute, which is the same order as the existing 60 s evidence refresh.

#### 2.8.5 Attribution (new pure module, outside `exec/`, so its body is not under E0-NOSEND by path; it does no I/O)

The module is `src/breezy/adapters/polymarket_us/no_id_attribution.py`. It is a sibling of `account_activity.py` and reuses its RFC3339 parser through **one** new public alias, `parse_rfc3339_ns = _parse_rfc3339_ns` (one additive line). **(r6, item 2)** r5's second alias, `activity_create_ts_ns`, is dropped: ordering is now checked on TRADE rows only, and a TRADE row's time is `trade.createTime` through `parse_rfc3339_ns`.

**(r5, DM2) Purity is enforced, not asserted.** T48 parses the module's AST and fails on:
- any import of `asyncio`, `os`, `socket`, `ssl`, `http`, `urllib`, `requests`, `httpx`, `aiohttp`, `subprocess`, `threading`, `pathlib`, `io` or `nautilus_trader.network`, and any name in the firewall's `NETWORK_IMPORT_PREFIXES` (`test_execution_egress_firewall_guard.py:1758`);
- any `Await`, `AsyncFunctionDef`, `AsyncFor` or `AsyncWith`;
- any call to `open`, `exec`, `eval`, `__import__` or `getattr`;
- any import from `breezy.adapters.polymarket_us.exec`, `breezy.runtime` or a `*transport*`/`*signing*` module.
- Allowed imports are exactly `dataclasses`, `decimal`, `enum`, `typing`, `collections.abc` and the one `account_activity` alias (r6). T48 pins that set by equality, so a new import is a deliberate test edit.
- Non-vacuity: planting `import asyncio`, or a planted `async def`, in a copy of the source makes T48 fail.
- **(r6, item 5) Scope, stated.** T48 inspects a module's **own** source only. It does not walk transitive imports. Two compensating pins:
  - **T48(b): `account_activity.py` is pinned too.** Its import set is pinned by equality to today's literal (`__future__`, `calendar`, `hashlib`, `logging`, `re`, `collections.abc`, `dataclasses`, `datetime`, `decimal`, `typing`, `breezy.persistence.external_capital_flows`), with no `Await`/`AsyncFunctionDef`/`AsyncFor`/`AsyncWith` and no call to `open`, `exec`, `eval` or `__import__`.
  - **T48(c): the aliased function is pinned pure.** The body of `_parse_rfc3339_ns` calls only `isinstance`, `TypeError`, `ValueError`, `_RFC3339_RE.match`, `match.groups`, `datetime.strptime`, `.replace`, `calendar.timegm`, `parsed.timetuple`, `.ljust` and `int` (set equality).
  - **Stated, not pinned:** `account_activity`'s one first-party import, `breezy.persistence.external_capital_flows`, does file I/O (`os.open`, `:271`) for its own writer, and imports `os` and `pathlib`. It has no network import. `no_id_attribution` imports only the `ExternalCapitalFlow`-free alias `parse_rfc3339_ns` and never reaches that writer; importing the module runs no I/O. Any I/O reachable from the resolver is still covered by the resolver scanner on the calling side (§2.8.7).

**Pure types and functions:**
- `NoIdLeg(order_id, market_slug, outcome_side, action, price: Decimal | None, quantity: Decimal | None, tif, manual: bool, trade_create_ns, intent: str | None, fill_qty: Decimal | None)`. `manual` is True iff `manualOrderIndicator == "MANUAL_ORDER_INDICATOR_MANUAL"`. **(r6, item 1)** `intent` is the aggressor order's `intent` string, and `fill_qty` is the trade's `qtyDecimal`, parsed strictly (`None` if absent or not a finite Decimal; never `_trade_qty_decimal`'s silent 0). Neither field makes a row uninterpretable. They are read only by `manual_leg_net_effect`, where `None` makes reconciliation unavailable.
- `no_id_aggressor_legs(page, window_start_ns, prev_row_ts_ns: int | None) -> NoIdLegScan(legs: tuple[NoIdLeg, ...], passive_manual: tuple[bool, ...], uninterpretable_rows: int, out_of_order: bool, passed_window_start: bool, last_row_ts_ns: int | None)`. **(r5, DM3)** `prev_row_ts_ns` is the last parsed row time of the previous page, so the ordering check spans page boundaries. **(r6, item 2)** Both `prev_row_ts_ns` and `last_row_ts_ns` are TRADE-row times only.
  - For every `ACTIVITY_TYPE_TRADE` row it parses `trade.createTime`; an unparseable time counts as uninterpretable.
  - For rows at or after `window_start_ns` (with no upper cut; the window end is applied by the classifier), it extracts the aggressor order object (`trade.aggressor`, falling back to `aggressorExecution.order`, the same two locations as `_leg_status`) and the passive leg's `manualOrderIndicator`. A missing or non-string field on such a row is uninterpretable.
  - Non-TRADE rows follow `trade_rows_for_order`'s rules.
  - **(r6, item 2) Ordering is checked on TRADE rows only.** Every `ACTIVITY_TYPE_TRADE` row's `trade.createTime` must be `<=` the previous TRADE row's on this page, or `<= prev_row_ts_ns` (the last TRADE row time of the previous page) for the first TRADE row. A TRADE row strictly newer than its TRADE predecessor sets `out_of_order`. Ties are legal: the tracked capture has an exact tie. Non-TRADE rows are never used for ordering, whether or not their time parses.
    - **Why TRADE-only, and not "prove the venue sorts all types by one key".** (1) *Soundness needs only TRADE ordering.* Only a TRADE row can carry an aggressor leg, ours or a foreign one, so early termination is sound iff no TRADE row newer than `window_start_ns` can follow the first older TRADE row. That is exactly what the TRADE-only check verifies on every row read. (2) *A mixed-type check adds a liveness hazard with no safety gain.* `_activity_create_ts_ns` reads a different field per type (`positionResolution.afterPosition.updateTime`; the balance change's top-level-then-nested `createTime`, L-17). Nothing says these are the venue's sort key. One mis-keyed resolution row (11 in the 35-row history, one per settled market, landing D+1 12–15Z while an overnight intent can be OPEN) would make every read `INCOMPLETE("activities_out_of_order")` until it scrolled below the window. (3) *The captures cannot prove a sort key.* 0 cross-type inversions over 2 distinct pages (10 rows and 35 rows, 23 non-TRADE rows, §Evidence r6) is consistent with one key, but two pages are not a proof. The plan records them as corroboration only and does not depend on them.
    - The ruling's "strictly descending" is implemented as **non-increasing**, because the capture falsifies strict descent. A strict check would mark the real feed out-of-order on every read. This is disclosed in §R5.
    - A TRADE row whose time does not parse is uninterpretable (unchanged).
  - `passed_window_start` is True iff some **TRADE** row's parsed time is strictly `< window_start_ns` (r6, item 2). TRADE rows after that row on the same page are still ordering-checked, so a newer TRADE row below it is `out_of_order`. If no TRADE row older than the window start is found, the scan runs to `eof` or the page cap (INCOMPLETE). Every filled prior take leaves such a row, so this only matters for an account with no older trade in ≤ 2000 rows.
- `classify_no_id_evidence(*, legs, passive_manual, legs_complete, open_orders, open_orders_ok, known_order_ids, echo: NoIdEcho | None, window_start_ns, window_end_ns) -> NoIdVerdict`. `NoIdVerdict` is one of `ADOPT(order_id)`, `NO_FILL`, `CONTRADICTION(token)` or `INCOMPLETE(token)`, where each token comes from a closed set of names. **(r5)** `window_end_ns` is `created_ns + _NO_ID_WINDOW_FORWARD_NS` (DM1). `legs_complete` is False on `out_of_order` (DM3).
- **(r5, DM4)** `holding_delta_consistent(*, base_venue_net: str, now_venue_net: str, base_durable_net: str, now_durable_net: Decimal, leg_sign: int, manual_net: Decimal = Decimal(0)) -> bool | None`. It computes the "foreign" holding `venue_net - leg_sign * durable_net` at the baseline and now, and returns True iff `foreign_now - foreign_base == manual_net`. It returns `None` if any input fails to parse as a finite `Decimal`. `leg_sign` is +1 for `OUTCOME_SIDE_YES` and -1 for `OUTCOME_SIDE_NO`, because the venue nets a NO holding as short YES. Pure. **(r6, item 1)** `manual_net` is the new keyword; with its default the function is r5's.
- **(r6, item 1, route (d))** `manual_leg_net_effect(*, legs, passive_manual, slug: str, after_ns: int, now_ns: int, settle_ns: int, straddle_ns: int) -> ManualNet`. `ManualNet` is `(value: Decimal | None, status: Literal["ok", "unsettled", "unreconcilable"])`. Pure. It sums the signed venue-net effect of every **MANUAL aggressor** leg on `slug` with `trade_create_ns > after_ns`:
  - The sign comes from a closed table keyed by `(outcome_side, action, intent)`, with only the observed shapes (§Evidence r6): `(YES, BUY, ORDER_INTENT_BUY_LONG) = +fill_qty`, `(YES, SELL, ORDER_INTENT_SELL_LONG) = −fill_qty`, `(NO, BUY, ORDER_INTENT_BUY_SHORT) = −fill_qty`. The venue nets a NO holding as short YES, so a NO buy lowers the slug's net. `(NO, SELL, ORDER_INTENT_SELL_SHORT)` has never been observed, so it is **not** in the table (L-37: declare a value only once it has been seen).
  - `status="unreconcilable"` (value `None`) if any such leg has a shape outside the table, a `None` intent or `fill_qty`, or `|trade_create_ns - after_ns| <= straddle_ns` (it may or may not be in the snapshot), **or** if any TRADE row on `slug` after `after_ns` has a MANUAL **passive** leg (the operator's resting order was hit; the ruling counts aggressor legs only, so such a row is not reconciled and the route is closed).
  - `status="unsettled"` (value `None`) if any counted leg has `trade_create_ns > now_ns - settle_ns`, i.e. positions may not reflect it yet. The next 60 s re-check retries.
  - Otherwise `status="ok"` and `value` is the sum. With no manual legs on the slug, it is `Decimal(0)`.
  - `slug` is the echo slug. Legs on other slugs never move this slug's net and are skipped.

**Classification rules, applied per leg at or after `window_start_ns` in this order:**
1. `order_id in known_order_ids` (the durable venue-id map names a prior Breezy order): **ignore**.
2. Attributed mode (`echo` not None): the leg **matches** iff all of the following hold. A match makes it a **candidate**:
   - `market_slug == echo.slug`;
   - `outcome_side == echo.outcome_side`;
   - `action == echo.action`;
   - `price == Decimal(echo.price)`, a Decimal compare so `"0.28" == "0.2800"`;
   - `quantity == 1`;
   - `tif == IOC`;
   - not manual.
3. `manual` is True (the operator's own aggressor order): **ignore**.
4. The passive leg is MANUAL (the operator's resting order was hit by a counterparty, which can be AUTOMATIC per P-e): **ignore**.
5. Otherwise this is an AUTOMATIC, unknown, in-window aggressor that is not our echo, or any such leg in window-only mode. Under the singleton latch no other Breezy order could exist, so the evidence is unattributable: **`CONTRADICTION("unattributed_automated_trade_in_window")`**.
6. **(r5, DM1)** Rule 2 applies only when `trade_create_ns <= window_end_ns`. A leg that survives rules 1, 3 and 4 with `trade_create_ns > window_end_ns`, whether or not it matches the echo, is **`CONTRADICTION("leg_after_attribution_window")`**. It is checked before rule 2, so a late echo match is never a candidate.

**Open orders** (each is an `OpenOrderRecord` with `create_time`, `tif`, `market_slug` and `price`):
- An in-window, unknown order that is IOC, or that matches the echo slug and price, gives **`CONTRADICTION("in_window_open_order")`**. A Breezy IOC never rests, so this would be anomalous.
- Non-IOC in-window orders are ignored: the operator's MANUAL `DAY` orders cannot be Breezy's (P-d).
- An open-order read failure, i.e. `open_orders_ok` False, gives `INCOMPLETE("open_orders_read")`.

**Verdict precedence: CONTRADICTION, then INCOMPLETE, then the rest.**
- **More than one** distinct candidate id gives `CONTRADICTION("multiple_candidates")`.
- `legs_complete` False (neither eof nor ordered early termination, page cap, or uninterpretable rows) gives `INCOMPLETE("activities_incomplete")`. **(r5, DM3)** An ordering violation gives `INCOMPLETE("activities_out_of_order")`.
- **Exactly one** candidate gives `ADOPT(id)`.
- **Zero** candidates gives `NO_FILL`, but only as far as attribution is concerned. The positions baseline is checked in the client (§2.8.6).

#### 2.8.6 The resolver branch: `async def _resolve_no_id_intent(intent_id, created_ns, context, instrument)` (scanned)

**Reads.** Each one follows the existing pattern: `try` around the await, and on exception a WARNING, `self._resolver_consecutive_failures += 1`, then return. The intent stays AMBIGUOUS.
1. Positions: `self._private_read(PORTFOLIO_POSITIONS_PATH)`, then `self._declared_positions(...)`.
2. Open orders: `self._read_open_orders()`.
3. Activities: `self._no_id_trade_activity(window_start_ns)`. This is a new scanned coroutine with the same page loop as `_order_trade_activity`: `_RESOLVER_ACTIVITY_MAX_PAGES` (20) by `_RESOLVER_ACTIVITY_PAGE_LIMIT` (100), `SORT_ORDER_DESCENDING`. It returns `NoIdTradeJoin(complete, out_of_order, legs, passive_manual, uninterpretable_rows, pages)` and accumulates by tuple unpacking (`found = (*found, *scan.legs)`), not by a call.
   - **(r5, DM3) Completeness: `eof` OR ordered early termination.** r4 used `eof` only, so the read could never complete once the account held more than 20 × 100 = 2000 rows.
     - The loop stops with `complete=True` on the first page whose scan has `passed_window_start` and not `out_of_order`, or on `eof: true`.
     - It stops with `complete=False, out_of_order=True` on any ordering violation, including across a page boundary through `prev_row_ts_ns = scan.last_row_ts_ns`.
     - It stops with `complete=False` on the page cap, a missing cursor, a malformed page, or uninterpretable rows, exactly as in r4.
     - **Why it is sound.** With non-increasing order among TRADE rows (r6, item 2), every TRADE row after the first TRADE row older than `window_start_ns` is also older, so it can hold neither our leg nor an attributable one. Non-TRADE rows cannot hold a leg at all. The ordering assumption is checked on every TRADE row actually read, never assumed. A violation is INCOMPLETE, so the intent stays AMBIGUOUS.
     - **Ordering assumption, pinned by a test against a captured response:** T41(ix) runs the git-tracked `AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`. The local 35-row `SORT_ORDER_DESCENDING` captures (git-ignored `PRIVATE_*`) agree and are cited, not used by tests.
     - **Measured headroom.** The account's whole history was 35 rows on 2026-09-27 (2026-07-28 to 09-27, one page). No resolver read has ever needed page 2 (0 `traversed` lines in 67 node logs). An upper bound on the post-10-01 row rate is ≈ 9 rows/day (≤ 2 rows per take at ≈ 4.3 takes/day).
       - **eof-only (r4):** it would reach the 2000-row cap after ≈ (2000 − 35) / 9 ≈ **218 days** (around May 2027). After that every no-id read would be permanently INCOMPLETE.
       - **Early termination (r5):** it reads only rows newer than `created_ns - 120 s`. While the intent is OPEN no Breezy take can add rows (singleton latch), so those are resolutions and manual activity only. At the observed maximum OPEN age (26.9 h) that is ≤ ~10 rows, i.e. **one page against a 20-page cap, ≈ 200× headroom**. The cap would bind only after ≈ 2000 / 9 ≈ 222 days of continuous OPEN.
     - **Residual, stated:** a cursor that silently *skips* rows across a page boundary cannot be detected by an ordering check. The eof-only path already places the same trust in the cursor, and early termination almost always ends on page 0, so this adds no new trust.
     - **Ruled scope:** this supersedes the EDGE-2 "eof ONLY" amendment for `_no_id_trade_activity` only (§I.3(f)). `_order_trade_activity` stays byte-identical and eof-only.
   - **Duplication is deliberate.** `_order_trade_activity` is EDGE-2-pinned and stays byte-identical, and the new loop is about 45 lines. A follow-up `RESOLVER-PAGE-LOOP-DRY` is recorded in §7 instead of refactoring a safety-pinned coroutine here.

**Known ids.** `known = {leg.order_id for leg in legs if self.client_order_id_for(VenueOrderId(leg.order_id)) is not None}`, and likewise for open-order ids. This is a local store read (`:4587`). Our own no-id order can never be in the map, by definition.

**Echo.** In attributed mode, `NoIdEcho` is built from the four `wire_*` fields. If any of them is `None`, which means an old-blob context written before r4, the branch falls back to **window-only rules** (the echo is `None`).

**Positions baseline,** checked only when the classifier says NO_FILL:
- **Attributed, same-day instrument.** "Same-day" uses the same `self._instrument_provider.list_all()` walk as `:2932-2936`. With `v = _resolver_leg_holding_qty(positions, slug, leg)` and `d = self._durable_net_qty(instrument.id)`:
  - `None` for either gives INCOMPLETE.
  - **(r5, DM4) Delta first.** If the context carries a valid pre-POST baseline (§2.8.3), the check is made against the manual trades since the snapshot (**r6, item 1, route (d)**), all from the same complete scan:
    1. `m = manual_leg_net_effect(legs=<this pass's legs>, passive_manual=..., slug=echo.slug, after_ns=context.baseline_ts_ns, now_ns=now, settle_ns=_RESOLVER_ZERO_FILL_MIN_AGE_NS, straddle_ns=_NO_ID_MANUAL_STRADDLE_NS)`.
       - `_RESOLVER_ZERO_FILL_MIN_AGE_NS` (120 s, existing) is reused as the settle time: positions are given the same 120 s the with-id zero-fill gives the same feeds.
       - `_NO_ID_MANUAL_STRADDLE_NS: Final[int] = 30 * 1_000_000_000` is new. It is the venue's 30 s timestamp tolerance (P-c): a manual trade that close to the snapshot may or may not be in it.
    2. `m.status == "unsettled"`: `INCOMPLETE("manual_leg_unsettled")`. The next 60 s re-check retries, and within ≤ 120 s the leg is settled.
    3. `m.status == "unreconcilable"`: `CONTRADICTION("unexplained_holding_delta")` with detail `manual_reconcile=<reason>`, where the reason is one of `unknown_shape`, `missing_field`, `straddles_snapshot` or `manual_passive_leg`.
    4. Otherwise: `holding_delta_consistent(base_venue_net=context.baseline_venue_net, now_venue_net=<the slug's signed netPosition on this read, "0" if absent>, base_durable_net=context.baseline_durable_net, now_durable_net=d, leg_sign=..., manual_net=m.value)`.
       - True: the baseline passes. With manual legs counted, one INFO line `resolver: no-id holding delta reconciled by <n> manual leg(s)` is logged.
       - False: `CONTRADICTION("unexplained_holding_delta")`.
       - None: INCOMPLETE.
    - Why the delta is sound: under the latch no Breezy fill on this instrument can be recorded between the pre-POST snapshot and now, except ours. An untracked fill of ours changes `venue_net` by `leg_sign × 1` and leaves `d` unchanged, so the foreign holding moves by one more than the manual trades explain, and the check fails. A manual holding that already existed at the snapshot cancels out, which is the DM4 case.
    - **(r6) Why route (d) is sound, and stricter than r5.** The scan reads back to `created_ns - 120 s` and, by §2.8.3, `baseline_ts_ns >= created_ns - 120 s`, so every manual trade after the snapshot is in the scan. Route (d) passes only if the foreign move equals the signed manual fills exactly, which leaves no room for an untracked fill of ours. r5's zero test implicitly assumed `manual_net = 0`. It would have passed "manual SELL 1 plus our untracked BUY 1" (delta 0). r6 now computes `manual_net = −1` and fails it. With no manual legs on the slug, r6 equals r5.
    - **Residual, stated.** A false pass needs our fill to be reflected in positions but missing from activities (≥ 300 s after arm), *and* a manual fill of exactly offsetting size to be reflected in activities but not yet in positions (≥ 120 s after it). That requires the two feeds to lag in opposite directions at once. It is the same activities-lag trust the whole no-fill predicate already places (O10).
  - **Absolute (r4 rule)** applies only when the context has no valid baseline (an old blob, or a missing, refused or not-quiet snapshot). Entry (`wire_action` BUY): `v > d` gives `CONTRADICTION("unexplained_holding")`. Exit (SELL): `v < d` gives the same contradiction.
- **Attributed, past-day instrument.** The baseline leg is skipped, in parity with AC4(e) D2, because a settled market leaves the positions page (`:2923-2931`). The complete activities join remains the evidence. This is stated, not hidden.
- **Window-only.** For **every** instrument in `self._instrument_provider.list_all()`: `None` gives INCOMPLETE, and `v != d` gives `CONTRADICTION("unexplained_holding")`. There is no context, so there is no baseline and no delta.

**(r5, DM4; r6, item 1) Automated exit from a holding contradiction (no operator step).** An `unexplained_holding*` contradiction is re-checked every 60 s (§2.8.4). It leaves AMBIGUOUS by one of four automated routes:
- (a) The evidence becomes consistent: a transient read clears, or the manual trade is reversed. The next re-check then retires or adopts as usual.
- **(d) (r6, coordinator ruling) Manual-leg reconciliation, inside the 60 s re-check.** In the same complete activities scan, the foreign-holding delta is reconciled against the in-scan MANUAL aggressor legs on the slug since the snapshot (`manual_leg_net_effect`, above). If the delta equals their signed sum, the holding is consistent and the no-fill retirement proceeds. This clears the typical manual-trade trigger at the first re-check where the manual legs are ≥ 120 s old, i.e. ≤ 3 re-checks. Anything else stays AMBIGUOUS: an unreconcilable shape, a straddling leg, a MANUAL passive leg, or a mismatch. Route (d) needs a valid baseline, so it applies only in attributed same-day mode.
- (b) **The first launch after the market resolves (restated bound).** The intent blocks trading, so the node is stopped at 16:40Z and the supervisor launches to resolve at 16:50Z (§2.9). "Same-day" is membership in `self._instrument_provider.list_all()` (`:2923-2936`), and the provider loads the venue's **active** markets (`provider.py:334-338, 585-599`). **r5's "≤ one daily cycle" was misstated and is withdrawn:** a take before 16:40Z on day D is relaunched at 16:50Z on D with its market still listed, so that launch does not exit. The exit is the first node boot after the venue resolves the market. At that boot the instrument is past-day, the positions leg is skipped (AC4(e) D2 parity), and the decision rests on the complete activities scan and the open-orders read. That run retires `RESOLVER_NO_ID_NO_FILL` if those are negative, or ADOPTs if a matching leg exists.
  - **Bound, restated: at most two daily cycles from the take** (the 16:50Z launch on D+1 at the latest, where D is the market's climate day). Weather markets resolve at D+1 12:01Z to 15:01Z (n = 11), always before the 16:50Z launch on D+1 (§Evidence r6). So for a D0 take the exit is the first or second launch after the take (≤ ~41 h), and for a lead-1 take made at or after 16:50Z on D−1 it is the second (≤ 48 h).
  - **Disclosed edge, against the store.** A lead-1 take made *before* 16:40Z on D−1 sees three launches: 16:50Z on D−1 and on D (both still listed), then 16:50Z on D+1. That is 48 h 48 min for the one observed case (10-01T16:02Z on the 10-02 market), and at most ≈ 55 h from the earliest listing (≈ D−1 09:45Z). In wall-clock terms, that is two daily cycles plus the fraction of the day before the first 16:40Z stop. It is reported to the coordinator in §R6, not hidden.
  - A market resolving after 16:50Z on D+1 (never observed) moves the exit one cycle later. It is still automated and still paged.
  - Any earlier boot, such as the mid-day relaunch, exits sooner if it falls after the resolution.
- (c) If the activities scan itself contradicts (an unattributed AUTOMATIC leg), (b) does not apply and the intent stays AMBIGUOUS. That is R-OTHER-AUTOMATION, bounded in §7.
- **Evidence for the bound being rarely exercised:** the delta removes the "manual buy before the take" case outright, and route (d) removes the "manual trade on the same slug after the snapshot" case whenever its shape is in the table. What is left for (b) is: an unobserved manual shape (`SELL_SHORT`), a MANUAL passive fill, a manual trade within 30 s of the snapshot, or a not-quiet baseline combined with a manual holding. Observed: 0 MANUAL trades on a same-day Breezy weather instrument since go-live (§Evidence r5).
- The CRITICAL detail names the route: `next=no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution`.

**Outcomes:**
- **ADOPT(id)** (found order or fill; covers MED-2, SIGTERM mid-POST with an untracked fill):
  1. `self._adopt_no_id_venue_order(context, id)` writes **one key**, the same `RESOLVER_CONTEXT_KEY_PREFIX + intent_id` context, with `venueOrderId = id` and every other field unchanged, including the r5 baseline fields.
     - **(r5, DM2) It is in `EXEC_RESOLVER_COROUTINES`, so its body is scanned** by `find_exec_resolver_violations`, not merely shape-pinned.
     - Its body is exactly `adopted = dataclasses.replace(context, venue_order_id=venue_order_id)` then `self._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{adopted.intent_id}", adopted.to_bytes())`.
     - It has three callees, all added to the allowlist (§2.8.7 #13–#15). It has no `try`: a store failure propagates to the caller's `try`, which calls `_note_resolver_error`, and the intent stays AMBIGUOUS.
     - The single-key shape is *also* pinned (T42(iv)), in the style of `_set_resolver_last_failure_kind` (`:4062`).
  2. **Same-process only**: `cached = self._cache.order(ClientOrderId(context.client_order_id))`. If `cached is not None and cached.status is OrderStatus.INITIALIZED`, call `self._generate_submitted(cached, now_ns)`. Both no-id create paths leave the order INITIALIZED, because `generate_submitted` is False when there is no id (`submit_chain.py:1231`, `:1320`). Nautilus has no `(INITIALIZED, FILLED)` edge (`client.py:5696-5700`), so this must precede any fill.
  3. Log a WARNING: `resolver: no-id intent <id> adopted venue order <redacted>; resolving on the with-id path`. Return.
  - **The next pass takes the unchanged with-id path:** the GET by id, then `PARTIALLY_FILLED` keep-polling, terminal-zero predicates (120 s floor already satisfied, complete join, AC4(e), contradictions), or accept-fill (`_resolve_accept_fill`). The accept-fill path covers the cross-process case (`_resolver_fill_order_unknown`, T1/T2, AC6b) and the A3 clear.
  - **A found fill therefore goes through the existing accept-fill path, as required.**
- **NO_FILL** (with the baseline passing):
  1. `self._resolved_no_id_ts_ns[intent_id] = now_ns`. This is the SAFETY H2 analogue: set only by a complete negative pass in THIS run.
  2. Call `self._resolve_no_order(intent_id, context, now_ns, positions)`, inside the same `try/except Exception -> self._note_resolver_error` wrapper as `:2962-2966`.
- **CONTRADICTION(token):**
  - Write `self._resolver_contradiction_details = {**..., intent_id: {"severity": "CRITICAL", "event": "resolver_evidence_contradiction", "site": "global", "intent_id": intent_id, "venue_order_id": "none", "no_id": "true", "reason": token, "next": <per token>}}`.
  - **(r5; r6 item 1)** `next` is `no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution` for `unexplained_holding*`, and `no_id_recheck_60s` for every other token. Both name the automated cadence (DM4, route (d)).
  - Set `self._no_id_next_check_ns[intent_id] = now_ns + _NO_ID_RECHECK_INTERVAL_NS`.
  - Log one ERROR. The intent stays AMBIGUOUS.
  - Delivery uses the existing `contradiction_h` on the re-poll timer (FU-8b). `_retire` clears the entry (`:5244`).
- **INCOMPLETE(token):** one WARNING; the intent stays AMBIGUOUS, and **(r5)** the next re-check is in 60 s (`_no_id_next_check_ns`). **(r6)** The closed INCOMPLETE token set gains `manual_leg_unsettled`.
  - A persistent INCOMPLETE pages through the **existing** `open_intent_stale` CRITICAL after 15 min (`:2581-2604`) in attributed mode.
  - In window-only mode, which has no context, the same dict entry is written inside `_resolve_no_id_intent` once `age >= _STALE_INTENT_ALERT_AFTER_NS`, with `"venue_order_id": "none"`, `"no_context": "true"` and `"next": "no_id_resolver_window_only"`. The same whole-value reassignment shape is used, so no new callee is needed.

**`def _resolve_no_order(intent_id, context, now_ns, positions)`** (scanned). It mirrors `_resolve_terminal_zero` (`:2985-3112`) step for step:
0. **(r5, DH1) Supervisor-decode guard.** `if not self._no_id_retire_admitted:` stay AMBIGUOUS. This is an attribute read with no callee.
   - Write the contradiction-details entry `{"severity": "CRITICAL", "event": "resolver_no_id_retire_blocked", "reason": "supervisor_decode_marker_absent", "no_id": "true", "next": "next_node_boot_rereads_supervisor_marker", ...}` with the same whole-value reassignment shape, plus one ERROR. Return.
   - `_no_id_retire_admitted` comes from `PolymarketUSExecClientConfig.no_id_retire_admitted: bool = False`, which is set only at node boot (§2.11). **Fail-closed default.**
   - ADOPT is not gated: it retires through existing reason members that every supervisor decodes.
1. Refuse unless `intent_id in self._resolved_no_id_ts_ns` (ERROR, return): the H2 analogue.
2. `current = self._latch.current_open()`. If it is None or a different intent, pop the booking and return.
3. `self._retire(intent_id, "RESOLVER_NO_ID_NO_FILL", now_ns)`, then INFO `resolver: retired intent <id> (RESOLVER_NO_ID_NO_FILL)`.
4. Booking (`self._ambiguous_bookings.pop(intent_id, None)`):
   - **Same process:** `true_up_booking(..., ZERO)`. Then, if `self._permit is not None and context is not None`, call `restore_live_trading_budget(permit=..., venue_order_id=f"noid:{intent_id}", order_notional_usd=context.notional_usd)`, which is idempotent per key (`safety.py:857-875`), and on True call `self._mark_budget_restored(f"noid:{intent_id}")`.
   - **Cross-process:** INFO only, with no restore (AC6/D3 parity).
   - In the store-fail case the booking was already released at `_submit_order`, so nothing is registered.
5. `self._write_startup_position_evidence(...)` from `positions`, exactly as zero-fill does at `:3075-3081`, so the strategy's re-arm gate re-evaluates.
6. **Same process, with context:** if the cached order is INITIALIZED, call `self.generate_order_rejected(strategy_id=StrategyId(...), instrument_id=InstrumentId.from_str(...), client_order_id=ClientOrderId(...), reason=_NO_ID_NO_FILL_REASON, ts_event=now_ns)`. `(INITIALIZED, REJECTED)` is the legal edge the create path's REJECT branch already uses (`:5792`). `_NO_ID_NO_FILL_REASON` is the constant `"resolver: complete venue reads show no order and no fill for this no-id submit"`.
7. **Last:** the same inline AMBIGUOUS clear block as `:3100-3112`, plus `self._ambiguous_refusal_clears += 1` (§2.2). Any raise above it keeps the refusal.

**Retirement reason.** `RetirementReason.RESOLVER_NO_ID_NO_FILL = "RESOLVER_NO_ID_NO_FILL"` is added to `runtime/submit_intent.py:73-93`. It is additive, with a round-trip test in the style of `test_status_report_accept_fill_terminal_retires_and_round_trips` (`test_submit_intent_latch.py:860`).
- `retirement_member` is `getattr(reasons, name)` (`submit_chain.py:1508-1509`), so the adapter needs no import.
- Grep for consumers of retirement-reason strings in `src/` and `scripts/`: only `submit_intent.py`, `clear_submit_intent_cli.py`, `node_config.py`, `factories.py`, `config.py`, `client.py` and `submit_chain.py`. None of them switch on the full member set (T43 re-runs the grep).
- The name says what is proven: complete reads show no fill and nothing resting. It does not say "no order". A zero-fill IOC the venue did accept is, economically, the same outcome.

**Predicate strength (F4 extended), side by side.** Written security sign-off is merge-blocking.

| Requirement | With-id zero-fill (`:2880-2966`) | **No-id no-fill (r4)** |
|---|---|---|
| Terminal-state evidence | Terminal GET in this run (H2) | No GET is possible. Instead: the IOC fate is fixed by about `created_ns + 65 s` (P-c), and **min age 300 s** (vs 120 s) |
| Positions | eof-complete read; leg determinable | Same read; leg baseline mandatory on same-day. **(r5) Delta against the pre-POST snapshot when valid and quiet, else absolute.** **(r6) The delta must equal the signed MANUAL aggressor fills on the slug since the snapshot exactly (route (d)); the snapshot must be ≥ `created_ns - 120 s`.** **Window-only: every same-day instrument must have `v == d`** |
| Activities | eof-complete join by venue id with 0 trades | Scan complete by eof **or (r5) by ordered early termination**, every row ordering-checked. **Every** aggressor leg from `window_start` onward is classified. **Any** unattributed AUTOMATIC leg, and any non-ignored leg after `created_ns + 120 s`, is a contradiction. 0 candidates required |
| Open orders | Not used | Strict full-list parse; no in-window IOC or echo-matching order |
| Contradiction | CRITICAL, stays | CRITICAL, stays (6 closed-set tokens: `multiple_candidates`, `unattributed_automated_trade_in_window`, `in_window_open_order`, `unexplained_holding`, `unexplained_holding_delta`, `leg_after_attribution_window`); re-checked every 60 s |
| Supervisor can decode the reason | n/a (existing members) | **(r5)** Required: `no_id_retire_admitted` (§2.11) |
| H2 guard | `_resolved_by_get_ts_ns` | `_resolved_no_id_ts_ns` |
| Durable effect | Retire, true up 0, restore, native cancel, clear | Retire, true up 0, restore (keyed `noid:<intent>`), native reject (same process only), clear |

**GL-1 vs R-7 (domain rule) holds.**
- The create-time classification is byte-unchanged, so empty executions at `maxBlockTime` still classify AMBIGUOUS (`submit_chain.py:1295-1322`).
- r4 retires only on the complete-read predicate above, never on create-time evidence, and never on partial or contradictory reads.

#### 2.8.7 NO-SEND firewall: delta and proof (no new egress callee)

**`EXEC_RESOLVER_COROUTINES` gains 4 names** (more code scanned): `_resolve_no_id_intent`, `_no_id_trade_activity`, `_resolve_no_order` and **(r5, DM2) `_adopt_no_id_venue_order`**, the only new resolver-reachable helper that writes durable state.

**`EXEC_PERMITTED_COROUTINE_NAMES` gains 2** (E0-INERT coroutine-name list): `_resolve_no_id_intent` and `_no_id_trade_activity`.

**`EXEC_RESOLVER_PERMITTED_CALLEES` gains exactly 17** (r4's 12, plus r5's #13–#16, plus r6's #17). Each one, and why it is not egress:

| # | Callee | Why it is not egress |
|---|---|---|
| 1 | `self._resolve_no_id_intent` | Scanned coroutine |
| 2 | `self._no_id_trade_activity` | Scanned coroutine. It awaits only `self._private_read(PORTFOLIO_ACTIVITIES_PATH, query)` |
| 3 | `self._resolve_no_order` | Scanned sync helper |
| 4 | `self._adopt_no_id_venue_order` | Callee-only. One local store key, shape-pinned |
| 5 | `no_id_aggressor_legs` | Pure; outside `exec/` |
| 6 | `classify_no_id_evidence` | Pure; outside `exec/` |
| 7 | `NoIdTradeJoin` | Frozen dataclass constructor |
| 8 | `self.client_order_id_for` | Local store read (`:4587`) |
| 9 | `VenueOrderId` | Native value type |
| 10 | `self._cache.order` | Local cache read |
| 11 | `self._generate_submitted` | Native event publish (`:5246-5253`); already in the order-coroutine allowlist |
| 12 | `self.generate_order_rejected` | Native event publish; already in the order-coroutine allowlist |
| 13 | `self._store_set` | **(r5, DM2)** One local SQLite key, no path, no socket, no `await`. Needed because `_adopt_no_id_venue_order` is now scanned. **Compensating pin, T42(iv):** across the bodies of *every* name in `EXEC_RESOLVER_COROUTINES`, `self._store_set` occurs exactly once, inside `_adopt_no_id_venue_order`, and its key is exactly `f"{RESOLVER_CONTEXT_KEY_PREFIX}{adopted.intent_id}"`. A second site, or any other key, fails the test |
| 14 | `dataclasses.replace` | Pure stdlib copy of a frozen dataclass |
| 15 | `adopted.to_bytes` | Pure encode of `AmbiguousResolverContext` (the same shape as the existing `record.to_bytes`) |
| 16 | `holding_delta_consistent` | **(r5, DM4)** Pure; in `no_id_attribution.py`, outside `exec/`, purity-pinned by T48 |
| 17 | `manual_leg_net_effect` | **(r6, item 1)** Pure; in `no_id_attribution.py`, outside `exec/`, purity-pinned by T48. Reads only the already-scanned legs |

(r5) The DH1 guard (`self._no_id_retire_admitted`), the DM3 ordering fields and the DM4 re-check dict are attribute reads or subscript assignments, with no callee. `_holding_baseline` is called only from `_note_ambiguous_open`, never from a resolver body.

Everything else the new code calls is already allowlisted, including `self._private_read`, `self._read_open_orders`, `self._declared_positions`, `self._instrument_provider.list_all`, `_resolver_leg_holding_qty`, `self._durable_net_qty`, `self._retire`, `self._ambiguous_bookings.pop`, `self._ledger.true_up_booking`, `restore_live_trading_budget`, `self._mark_budget_restored`, `self._write_startup_position_evidence`, `self._latch.current_open`, `ClientOrderId`, `StrategyId`, `InstrumentId.from_str`, `self._note_resolver_error`, `range`, `page.get`, `isinstance`, `len`, `_redact_order_id`, `self._clock.timestamp_ns` and `self._log.*`.

**Unchanged:** `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` and its set-equality pins, `ORDER_LIFECYCLE_COROUTINES`, every scanner, N1–N5 and X1–X3.

**The proof is the callee-set test T42.** It asserts:
- (i) `NO_ID_RESOLVER_ADDITIONS` equals exactly the 17-name set above, and `EXEC_RESOLVER_PERMITTED_CALLEES - NO_ID_RESOLVER_ADDITIONS` equals the pre-change set. The pre-change set is frozen in the test as a literal copied from `f45f5a65`. **(r5)** Likewise, `EXEC_RESOLVER_COROUTINES` minus the 4 new names equals its frozen pre-change literal.
- (ii) `self._order_sender.post_order`, `self._order_sender`, `self._write_signer.sign_headers` and every name containing `post`, `send` or `cancel` are absent from all three resolver sets.
- (iii) An AST walk of the three new functions: every `Await` targets exactly one of `self._private_read`, `self._read_open_orders`, `self._no_id_trade_activity` or `self._resolve_no_id_intent`. Every `self._private_read` argument 0 is one of the `Name`s `PORTFOLIO_POSITIONS_PATH` or `PORTFOLIO_ACTIVITIES_PATH`, i.e. **existing GET reads only**.
- (iv) **(r5, strengthened)** `self._store_set` appears exactly once across all `EXEC_RESOLVER_COROUTINES` bodies, inside `_adopt_no_id_venue_order`, with the key `f"{RESOLVER_CONTEXT_KEY_PREFIX}{adopted.intent_id}"`. `_adopt_no_id_venue_order` is in `EXEC_RESOLVER_COROUTINES`, and `find_exec_resolver_violations` returns `[]` on the real `client.py`.
- (v) Non-vacuity: planting `self._order_sender.post_order(...)` into a copy of each new function, **including `_adopt_no_id_venue_order` (r5)**, makes `find_exec_resolver_violations` fire. Planting a second `self._store_set(...)` into `_resolve_no_order` fails (iv).
- (vi) **(r5, DM2/DM4)** `_note_ambiguous_open` and `_holding_baseline` contain no `Await`, no `self._private_read`, no `self._read_open_orders` and no `_order_sender`/`_write_signer` reference. `self._store_set` occurs once in `_note_ambiguous_open` (the context key) and zero times in `_holding_baseline`.

**Stop condition:** if implementation needs any callee beyond these 17, or any await target beyond (iii), stop and report. Do not widen.

### 2.9 The supervisor launches to resolve instead of refusing (CM1)

**Change (additive; existing pins stay green unedited).**

- `trade_supervisor_core.LaunchAction` gains `LAUNCH_TO_RESOLVE = "launch_to_resolve"`. `AlertDetail` gains `INTENT_OPEN_LAUNCH_TO_RESOLVE = "intent_open_launch_to_resolve"`.
- `decide_launch_action(*, lock_free, open_intent_detected, open_intent_resolvable: bool = False)`:
  - not lock free: `REFUSE_LOCK_HELD`, unchanged;
  - open and resolvable: `LAUNCH_TO_RESOLVE`;
  - open and not resolvable: `REFUSE_INTENT_OPEN`, unchanged;
  - otherwise `LAUNCH`.
  - The existing pins `test_trade_supervisor.py:391-398` call without the new kwarg and stay green.
- A new probe in `trade_supervisor.py`, beside `probe_open_intent` (`:402-420`): `probe_open_intent_resolvable(store_path, *, node_pid) -> bool`.
  - It is guarded by the same `assert_no_live_node_before_intent_probe`.
  - It returns True iff the singleton **decodes** and is OPEN.
  - A corrupt singleton returns False, which keeps today's refusal, because the node's resolver treats corrupt as OPEN-unknown and never retires it (`client.py:2516-2533`).
  - It needs no adapter import and no context read: every decodable OPEN shape now has an in-node path (§5.3).
- `SupervisorPorts` gains `probe_open_intent_resolvable: Callable[..., bool] = field(default=lambda *a, **kw: False)`. `default_ports` wires the real probe.
  - Every existing fake port is built without the field and gets the default, so the existing boot-retry pin (`:5282-5301`, probe True) still refuses and stays green.
- **(r5, DH1) Shape probe.** A new `probe_open_intent_shape(store_path, *, node_pid) -> OpenIntentShape`, behind the same `assert_no_live_node_before_intent_probe`. It does one read-only `SqliteStateStore.get` of `_RESOLVER_CONTEXT_KEY_PREFIX + intent_id` and a `json.loads`:
  - `WITH_ID`: `venueOrderId` is a non-empty string;
  - `NO_ID`: `venueOrderId == ""`;
  - `NO_CONTEXT`: the key is absent;
  - `UNKNOWN`: undecodable, or any exception.
  - `_RESOLVER_CONTEXT_KEY_PREFIX` is a literal copy in `trade_supervisor.py`, so the supervisor does not import the exec client. T44(vi) pins it equal to `client.RESOLVER_CONTEXT_KEY_PREFIX`.
  - `SupervisorPorts.probe_open_intent_shape` defaults to `lambda *a, **kw: OpenIntentShape.UNKNOWN`, which fails toward the louder alert.
- `_do_launch` (`:1233-1261`): on `LAUNCH_TO_RESOLVE`, call `log_decision("launch_to_resolve_open_intent", shape=<shape>)`. Then **(r5, DH1)** alert by shape:
  - `WITH_ID`: WARN `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE`, detail `INTENT_OPEN_LAUNCH_TO_RESOLVE`;
  - `NO_ID`, `NO_CONTEXT` or `UNKNOWN`: **CRITICAL** `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE_NO_ID`, new detail `AlertDetail.INTENT_OPEN_LAUNCH_TO_RESOLVE_NO_ID = "intent_open_launch_to_resolve_no_id"`, whose runbook line names `next=node_no_id_resolver` (no "operator").
  - Then **fall through to the existing LAUNCH spawn**, with the same D3 retry budget.
- `_handle_boot_retry_precheck_refusal` (`:1592-1619`): `LAUNCH_TO_RESOLVE` is treated as `LAUNCH` (return `None`), with the same shape-dependent alert.
- **(r5, DH1) Decode marker writer.** Immediately after the `supervisor_started` line (`:2492`), the supervisor calls `write_supervisor_decode_marker(store_path)` (§2.11). A raise is logged as `supervisor_decode_marker_write_failed` and never stops the supervisor. Without the marker, the node fails closed on no-id retirement.

**Why launching over an OPEN intent is safe:**
- The new node cannot send: `_submit_order` denies `OPEN_INTENT_WAIT_REASON` at `:5451-5452` **before** any permit spend, and `arm` refuses (`submit_intent.py:403-409`).
- Nothing on the node's boot path refuses on OPEN, and the immediate pass runs before reconciliation and the spend seed (`client.py:1997-2025`).
- The permit, caps, family halt and enablement are untouched.
- The 16:40Z `_do_stop_prior` is unchanged.

**CM1 proof: every resolvable path retires without a hand step.** Consider an intent that is OPEN when the 16:40Z stop kills node N. The 16:50Z node N+1 is launched (LAUNCH_TO_RESOLVE) and runs the immediate pass at `_connect`, then periodic passes.

| OPEN shape at 16:40Z | Retired by | When |
|---|---|---|
| With-id, fill confirmable | N+1 immediate pass (`STATUS_REPORT_ACCEPT_FILL_TERMINAL`), before the seed, so the boot is clean | At N+1 boot (about 16:50Z) |
| With-id, zero-fill | N+1 immediate or periodic pass; the 120 s age is already past | About 16:50Z |
| With-id, fill **not** confirmable at the immediate pass | A later periodic pass retires it. AC6b then latches `_RESOLVER_FILL_UNBUDGETED` **by design** (`:2063-2069`), and that day's trading is refused until the next 16:50Z launch, whose seed books the fill. **No hand step; bounded at ≤ 1 trading day; observed 0 times** (0 log lines). Residual R-UNBUDGETED (§7) | Intent: minutes. Trading: the next launch |
| No-id with an r4 context | N+1: attributed mode. Age is ≥ 300 s, because N was stopped at 16:40Z, so the newest possible arm is ≥ 10 min old by 16:50Z. NO_FILL retires; ADOPT then resolves on the with-id path on the next pass | About 16:50–16:52Z |
| OPEN, context absent (old code, or the store-fail branch) | N+1: window-only mode | About 16:50Z if the evidence is negative |
| Corrupt singleton | **Not resolvable.** `REFUSE_INTENT_OPEN` and CRITICAL `INTENT_OPEN_BLOCKS_ARM`, as today. 0 observed | Residual R-CORRUPT |
| Contradictory or incomplete evidence | The node is up and the intent stays AMBIGUOUS, with CRITICAL `resolver_evidence_contradiction` or `open_intent_stale` (domain rule). 0 contradictions observed in any log | Residual R-CONTRA |

The live D5 incident (2026-09-24) is row 2 and would have cleared at 16:50Z.

### 2.10 Every CRITICAL raised over an OPEN intent names the automated next action (CM2)

- **Activation S3** (§5.1): `AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT`. The detail is one of:
  - `shape=with_id next=resolver_get` (the context has a venue id);
  - `shape=no_id next=no_id_resolver_attributed` (the context's venue id is empty);
  - `shape=no_context next=no_id_resolver_window_only` (no context key).
  - The "operator-only" wording of r3 is gone.
- **In-node no-id contradiction:** **(r6)** `next=no_id_recheck_60s`, or `next=no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution` for a holding token (§2.8.6). r5's `stays_ambiguous_resolver_keeps_polling` disagreed with §2.8.6 and is replaced.
- **Window-only stale:** `next=no_id_resolver_window_only`.
- **Supervisor:** the WARN `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE` for a with-id intent; **(r5, DH1)** the CRITICAL `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE_NO_ID` for a no-id, no-context or unknown shape (`next=node_no_id_resolver`). The existing `INTENT_OPEN_BLOCKS_ARM` CRITICAL is now raised only for a **corrupt** singleton.
- **(r5) In-node:** `resolver_no_id_retire_blocked` (`next=next_node_boot_rereads_supervisor_marker`); holding contradictions (**r6** `next=no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution`). Its detail enum is unchanged; the runbook line names "corrupt singleton; node resolver cannot read it".
- No message says "operator". Pinned by T38(v) and T45.

### 2.11 (r5, DH1) Restart ordering enforced in the build: two phases, a decode marker, a check script

**The hazard.** `spawn_node` runs the node from `cwd=repo_root` (`trade_supervisor.py:866-876`), so a respawn loads whatever is merged. The supervisor keeps the `submit_intent` it loaded at its own start. Suppose an old supervisor is still running when a node with no-id code retires `RESOLVER_NO_ID_NO_FILL`. That supervisor's `_optional_enum` (`submit_intent.py:207-219`) raises `SubmitIntentCorrupt`, `probe_open_intent` returns OPEN (`:416-419`), and every later launch is refused. That is L-48 again. r4 relied on doing U1 before the node steps in the docs. r5 makes the build enforce it.

**Phase A merge (supervisor-side only).** Contents:
- **C0**, the `RetirementReason.RESOLVER_NO_ID_NO_FILL` member (`submit_intent.py`), with T43. That is the entire `submit_intent` change.
- `runtime/supervisor_decode_marker.py` (new).
- The `trade_supervisor_core.py` and `trade_supervisor.py` changes (§2.9, including the marker writer and the shape probe).
- `scripts/ops/ambig_latch_phase_a_check.py` (new).
- Their tests: T43, T44, T45, T46, T47.
- No node-side file changes. Phase A nodes still run r3-equivalent exec code, which never emits the new reason.

**Then, in the 01:00–16:40Z window:** U1, a supervisor restart (`KillMode=process`, so the node pid is unchanged), and then the check script.

**The marker, `runtime/supervisor_decode_marker.py`** (runtime layer; file I/O beside the store, in the style of `stop_intent_marker.py`):
- **Path:** `<store>.supervisor_decode`. It is not a store key, so the supervisor never writes to the SQLite store while a node holds it.
- **`write_supervisor_decode_marker(store_path)`:** writes atomically (tmp file, then `os.replace`) the JSON `{"v": 1, "pid": os.getpid(), "start_ticks": _process_start_ticks(os.getpid()), "revision": <supervisor_started revision>, "retirement_reasons": sorted(m.value for m in RetirementReason)}`. It overwrites on every supervisor start.
- **`supervisor_admits_retirement_reason(store_path, reason) -> bool`:** returns True iff all of the following hold. Anything else returns False (fail-closed):
  - the file decodes with `v == 1`;
  - `reason in retirement_reasons`;
  - `pid` is alive **and** its current `/proc` start ticks equal `start_ticks`, so the writer is the *running* supervisor, never a stale file from an older incarnation.

**Node-side guard (Phase B).**
- At node boot, `node_config.py`'s existing `msgspec_replace(exec_client_config, ...)` site (`:945-967`) sets `no_id_retire_admitted=supervisor_admits_retirement_reason(store_path, "RESOLVER_NO_ID_NO_FILL")`.
- The client keeps it as `self._no_id_retire_admitted`, and `_resolve_no_order` step 0 enforces it (§2.8.6).
- `node_config` logs one INFO line at boot, `no_id_retire_admitted=<True|False>`, which is the §5.4 boot proof.
- **Marker absent** means the intent stays AMBIGUOUS and pages CRITICAL `resolver_no_id_retire_blocked`. Its automated exit is the next node boot (at the latest the 16:50Z launch-to-resolve), which re-reads the marker.
- The field is never read from the environment and is not an enablement control. It gates only a *retirement* path, never an order.
- **Residual (R-MARKER):** a supervisor restarted *after* node boot onto older code is not seen until the next node boot. That requires reverting Phase A in the primary tree, which §6 forbids. It is bounded at ≤ one daily cycle and is fail-safe in the other direction: the old supervisor would refuse to launch, which pages `INTENT_OPEN_BLOCKS_ARM`.

**Superset test, T47.** The node's emitted reason names must be a subset of the reasons the supervisor writes and decodes:
- (i) Collect every string literal passed as the reason argument of `self._retire(...)` in `client.py`, plus every `retirement_member` name in `submit_chain.py`, by AST.
- (ii) Assert that set ⊆ `{m.value for m in RetirementReason}` ⊆ the `retirement_reasons` that `write_supervisor_decode_marker` writes (on a tmp path).
- (iii) Assert that `probe_open_intent` on a store whose singleton is RETIRED with each such member returns False (decodes, not corrupt).
- Non-vacuity: a planted `self._retire(x, "NOT_A_MEMBER", n)` fails (ii).

**`scripts/ops/ambig_latch_phase_a_check.py <PHASE_A_SHA> <PRE_RESTART_NODE_PID>`.** It is read-only (no store write, no signal, no network) and runs with the venv interpreter by explicit path. It prints only `PASS`/`FAIL` per check and exits 0 iff all three pass:
1. **The running supervisor's code descends from the Phase A merge (r6, item 3: ancestry alone).**
   - `systemctl --user show breezy-trade-supervisor -p MainPID` gives `MainPID`.
   - The revision is the marker's `revision` field. The marker is bound to `MainPID` by its pid and `/proc` start ticks (check 2). It must equal the `revision=` of the newest `supervisor_started` line in `breezy-trade-supervisor.log`.
   - The revision must be a hex sha (7–40 chars). The `resolve_build_revision` fallbacks, a package version or `"unknown"`, FAIL.
   - **The check is `git merge-base --is-ancestor <PHASE_A_SHA> <revision>`, exit 0, and nothing else.** No timestamp is compared: neither the committer `%ct` (which carries over a rebase or cherry-pick and so proves nothing about ancestry) nor `ActiveEnterTimestamp`.
   - It FAILs if `systemctl --user show breezy-trade-supervisor -p Environment` names `BREEZY_BUILD_REVISION`. That override would make the revision a declared value, not the tree HEAD. Only the key's presence is tested, and no value is printed.
   - Check 2 is still the capability proof: the running pid's own loaded enum lists the member. Check 1 corroborates it.
2. **Decode check of the new member.**
   - `supervisor_admits_retirement_reason(store_path, "RESOLVER_NO_ID_NO_FILL")` is True, and the marker `pid` equals `MainPID`.
   - In-process, a synthetic RETIRED `SubmitIntent` with that member round-trips through `to_bytes`/`from_bytes` (memory only).
3. **Same-pid adoption.**
   - A `permit_watch_adopted_live_node pid=<P>` line appears after that `supervisor_started` line, with `P == <PRE_RESTART_NODE_PID>`.
   - `P` also equals `resolve_lock_holder_pid(intent_lock_path(store_path))`, a read-only `/proc/locks` read.

**Phase B merge (everything node-side).**
- **Precondition:** the Phase A check's `EXIT=0` output is attached to the Phase B merge record (§8 step B0). A non-zero exit blocks the merge; the fix goes forward on Phase A.
- **Contents:** `client.py`, `submit_chain.py`, `no_id_attribution.py`, `account_activity.py`, `config.py`/`node_config.py` (the `no_id_retire_admitted` field), `trade_cli.py`, `component_health_watch.py`, the firewall constants, the L-36 paragraph and the remaining tests.
- **Defence in depth if the precondition were skipped:** the node-side guard keeps the node from ever writing the new reason under a supervisor that cannot decode it.

**The between-phases window.** Phase A's `LAUNCH_TO_RESOLVE` may spawn a still-old node over a no-id OPEN intent. The old node cannot resolve it and cannot send (`OPEN_INTENT_WAIT`), so that is today's stuck state with the node up instead of down. It now pages CRITICAL (`..._NO_ID`) and clears when Phase B relaunches the node. The window is bounded because Phase B follows in the same 01:00–16:40Z window. MED-2 (TBA) is otherwise covered by the split.

---

## §3 Tests: RED -> GREEN

**Artifact rules.**
- New tests go in new files or are appended to the files named.
- RED is shown by running each new test against the unmodified tree. Record RED and GREEN output as the change artifact (§5 TDD).
- A row marked "GREEN (guard)" is a pin that must be green before and after.
- **(r5)** Every rig that expects a `RESOLVER_NO_ID_NO_FILL` retirement (T25(iii)/(iv), T33, the T35 variant, T38, T39(i), T49) builds the client with `no_id_retire_admitted=True`. T50 pins the False default.
- **(r5)** Phase A tests (T43–T47) are written and run RED→GREEN in the Phase A branch. All other tests belong to Phase B.

### 3.1 Existing tests that change (complete list; every one is ruled and disclosed)

1. **A3 edit 1 (r3).**
   - `test_fq_caps_and_ambiguous_2026_10_01.py::test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` (`:387-419`) is renamed to `..._clears_the_ambiguous_refusal`.
   - Its rig and the three retirement assertions stay verbatim.
   - `:419` flips to `assert _AMBIGUOUS_REASON not in client.trading_refusals`.
2. **A3 edit 2 (r3, F2).** `test_current_rung_hold_ambiguous_resolver.py:1308` becomes:
   ```python
   assert submit_chain.AMBIGUOUS_REASON in refusals_before  # non-vacuity
   assert client.trading_refusals == tuple(
       reason for reason in refusals_before if reason != submit_chain.AMBIGUOUS_REASON
   ), (<existing message, "(the initial AMBIGUOUS submit's own refusal is cleared by the fill retirement, A3)">)
   ```
   This is stricter than before: no new refusal is added, and the AMBIGUOUS entry was really present and was removed.
3. **Sha re-pin.** `_EXEC_CLIENT_SHA256` in `test_forecast_quantile_ladder_manifest_and_markers.py:36` is re-pinned, with its comment updated to name this item. This is a pin constant, not an assertion.
4. **Firewall constants, additions only (r4, §2.8.7)** in `test_execution_egress_firewall_guard.py`:
   - `EXEC_RESOLVER_PERMITTED_CALLEES` +17 (r5 +16, r6 +1);
   - `EXEC_RESOLVER_COROUTINES` +4 (r5: `_adopt_no_id_venue_order` is scanned);
   - `EXEC_PERMITTED_COROUTINE_NAMES` +2.
   - Each entry gets a comment citing this plan, in the house style of the EDGE-2 AC9 and FAILURE-KIND-DURABLE additions.
   - **No scanner, pin, assertion or other constant in the file changes.**
   - If any test in that file asserts the *size* of those three sets, it is updated by exactly the stated delta, and the edit is listed in the PR (T42 re-derives the delta independently). The implementer greps `len(EXEC_RESOLVER\|len(EXEC_PERMITTED` and attaches the output.
5. **CL1: the ruled inversion of T25(iii).**
   - r3's planned T25(iii) asserted that a no-context OPEN intent is never retired ("pins the absence of an autonomous no-id path").
   - r4 replaces it with T25(iii)/(iv), which are positive resolver tests.
   - T25 was planned and is not in the tree, so no committed test is edited by this.
   - The **committed** sibling `test_current_rung_hold_ambiguous_resolver.py::test_open_intent_without_a_durable_context_makes_no_get_and_stays_open` (`:5705`) stays **unedited and green**. It runs below the 300 s min age, so it now pins "no read before the min age". The PR states this explicitly.

**The bounding grep** is re-run and attached to the PR:
- `/usr/bin/grep -rn --include=*.py "trading_refusals" tests/` (F2 classification, carried from r3).
- `/usr/bin/grep -rn --include=*.py "RESOLVER_CONTEXT_KEY_PREFIX\|_ambiguous_bookings\|_note_ambiguous_open" tests/`. Every hit is mapped to its test. Any assertion that a take leaves **no** context key, or that `_ambiguous_bookings` is empty after a non-AMBIGUOUS take, must be reported. The grep on 2026-10-03 found none: every hit reads or writes a context deliberately.
- **Any further RED in an existing test stops the build and is reported. It is never edited silently.**

### 3.2 New tests

| # | File | Test and assertion | RED today because |
|---|---|---|---|
| T1 | `tests/unit/test_ambig_latch_resume.py` (new) | `test_terminal_zero_clear_then_resume_returns_the_client_to_running`: the `_arm_one_ambiguous_intent` + `_run_resolver_passes` rig; after the pass, `resume_if_refusals_cleared()` is True, `is_running`, not `is_degraded`, and `ambiguous_refusal_clears == 1` | AttributeError |
| T2 | same | `test_resume_refused_while_the_submit_intent_is_open`: list emptied, latch OPEN; returns False, stays DEGRADED | AttributeError |
| T3 | same | `test_resume_refused_when_the_latch_read_is_corrupt_or_raises`: both cases return False; the raising case logs a WARNING with the type name only | AttributeError |
| T4 | same | `test_resume_is_a_no_op_unless_degraded`: (i) RUNNING gives False with no `InvalidStateTrigger`; (ii) STOPPED stays STOPPED; (iii) a DEGRADING msgbus spy records `(False, DEGRADING)`, ends DEGRADED, no `InvalidStateTrigger`; (iv) a remaining unrelated refusal gives False; (v) `_latch is None` gives False | AttributeError |
| T5 | same | `test_resume_method_callee_set_is_exactly_pinned`: callees EQUAL `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`; the property has 0 Calls; no Await; a planted `post_order` fails | method absent |
| T6 | same | `test_resume_and_degrade_actions_are_the_native_no_ops`: the MRO owners of `_resume`/`_degrade` are `[Component]` | GREEN (guard) |
| T7 | same | `test_resume_publishes_only_the_component_state_topic_and_never_reaches_the_sender`: topics are `events.system.<id>` only, states `[RESUMING, RUNNING]`, `sender.calls` unchanged | AttributeError |
| T8a | same | `test_the_resume_method_name_is_outside_every_firewall_scope`: both new names are absent from the three scanned sets; `self.resume`/`self.degrade`/the method are absent from both callee allowlists | GREEN (guard) |
| T8b | same | `test_the_resume_method_exists_as_a_sync_method_on_the_client`: a `FunctionDef` after `_refuse` | method absent |
| T9 | `tests/unit/test_exec_refusal_health_surface.py` (append) | `test_a_refusal_after_resume_re_alerts_exactly_once`: refuse A (1 alert), clear, resume, refuse B (2), refuse C while DEGRADED (still 2) | 1 alert |
| T10 | same | `test_running_re_arms_the_degraded_alert_for_the_same_component_only` | 1 |
| T11 | `tests/unit/test_trade_cli.py` (append) | `test_repoll_timer_resumes_a_cleared_exec_client`: one fire gives one call; a missing client or attribute is a no-op and the siblings still fire | 0 calls |
| T12 | same | `test_degraded_alert_and_resume_handler_are_wired_into_the_repoll_tuple`: length 5, index 3 is the degraded alert, the last is the resume handler; the kwargs are `ambiguous_reason == submit_chain.AMBIGUOUS_REASON` and a callable `ambiguous_clears` | length 3 |
| T13 | `test_ambig_latch_resume.py` | `test_accept_fill_retirement_clears_the_ambiguous_refusal_and_the_client_resumes`: FILLED, cum 1, LONG; retired `STATUS_REPORT_ACCEPT_FILL_TERMINAL`; AMBIGUOUS gone; INFO "cleared ... on fill retirement"; clears == 1; resume True | AMBIGUOUS present |
| T14 | same | `test_accept_fill_clear_keeps_every_other_refusal`: (i) venue-map write raises, so `_VENUE_ID_MAP_WRITE_FAILED` stays and resume is False; (ii) **isolation test**: cross-process `_RESOLVER_FILL_UNBUDGETED` stays and clears are unchanged | (i) AMBIGUOUS present; (ii) AttributeError |
| T15 | same | Guards: (i) `record_fill` raises, so AMBIGUOUS stays; (ii) `generate_order_filled` raises, so AMBIGUOUS stays; (iii) AST: every `self._refuse(submit_chain.AMBIGUOUS_REASON)` is inside `_submit_order` **and the total `_refuse` call-site count equals the pre-r4 count** (r4 adds none) | GREEN (guard) |
| T16 | same | `test_after_an_accept_fill_clear_a_take_reaches_the_sender`: one `post_order`; the ledger shows the fill spent | denied |
| T17 | `tests/unit/test_component_health_watch_degraded_throttle.py` (new) | `test_a_repeat_non_ambiguous_episode_inside_the_window_is_throttled_and_logged_once` | 2 alerts |
| T18 | same | `test_a_repeat_episode_after_the_window_re_alerts` (boundary `>=`) | constant missing |
| T19 | same | New-reason bypass; backwards clock; reader failure; one per episode; invalid `renotify_after_ns` (0, -1, `True`, `1.5`); default 1 h; a tick is a no-op without the readers | param missing |
| T20 | `test_ambig_latch_resume.py` | `test_resume_leaves_order_admission_unchanged_while_the_permit_is_invalid`: identical deny reason, 0 `post_order` | AttributeError |
| T21 | same | `test_resume_writes_nothing_durable_and_leaves_a_set_family_halt_set`: store snapshot byte-identical; `_permit` is the same object | AttributeError |
| T22 | same | `test_a_refusal_during_resuming_ends_degraded_and_re_alerts`: `[RESUMING, RUNNING, DEGRADING, DEGRADED]`, +1 alert, one WARNING | AttributeError |
| T23 | same | `test_a_refusal_after_resume_re_degrades_and_re_alerts_subject_to_the_throttle`: (i) throttle and window; (ii) AMBIGUOUS twice in 1 h gives **2 alerts, 0 throttle WARNINGs** | AttributeError |
| T24 | same | `test_a_second_ambiguous_inside_the_resume_window_refuses_resume_and_alerts`: variants (a), (b), (c) exactly as r3 (alerts 2/2/3; resume False/True) | 1 alert |
| **T25** | same | **Rewritten (CL1).** `test_a_node_booted_over_prior_process_open_intents_retires_every_shape`. A fresh rig boots over a store written by a "prior process". (i) With-id + FILLED + LONG: the immediate pass retires `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, no `Trading refused` (or cite `test_edge2_ac6b_cross_process_fill_budget.py::test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded` if identical). (ii) With-id terminal zero created 10 s before boot: not retired at the immediate pass; retired by a periodic pass after 120 s. **(iii) Inverted:** a no-id r4 context (`venueOrderId == ""`, wire fields set) created 10 s before boot; venue evidence negative (activities eof with no in-window rows, open orders `[]`, positions `v == d`). The immediate pass makes **no** activities or open-orders read; after the clock passes `created_ns + 300 s` a periodic pass retires `RESOLVER_NO_ID_NO_FILL`, `is_latched()` is False, and there is no restore (cross-process). **(iv) Inverted:** OPEN with **no** context key and the same evidence: window-only mode retires it after 300 s | (i)/(ii) GREEN (guard); (iii)/(iv) never retires (stays OPEN) |
| T26 | `tests/unit/test_ambig_no_id_resolver.py` (new) | `test_pre_post_context_is_durable_before_the_post_is_awaited`. The sender spy, inside `post_order`, reads `RESOLVER_CONTEXT_KEY_PREFIX + intent_id` from the store: it decodes with `venue_order_id == ""`, `wire_market_slug/price/outcome_side/action` equal to the encoded body's fields, `created_ns == intent.created_ns`, `client_order_id == order.client_order_id.value`; and `intent_id not in client._ambiguous_bookings` | key absent |
| T27 | same | `test_a_pre_post_context_write_failure_denies_without_posting`: `_store_set` raises for the resolver prefix only. `post_order` calls == 0; one `OrderDenied` with `STORE_RAISED_REASON`; ledger remaining equals the pre-take value (booking released); `client.trading_refusals == ()`; intent OPEN with no context (handed to T39(i)) | POSTs |
| T28 | same | `test_exception_path_keeps_the_no_id_context_and_registers_the_booking`: (a) `VenueTransportError`: AMBIGUOUS refusal, context `venue_order_id == ""`, `client._ambiguous_bookings[intent_id] is booking`, `_post_in_flight_intent_id is None`; (b) `CancelledError`: re-raised, context present, `_post_in_flight_intent_id is None` | no context; KeyError |
| T29 | same | `test_classified_no_id_path_registers_the_booking`, parametrized: 200 `{}`, 502 `b"<html>"`, 200 non-JSON. Same assertions as T28(a); `classify_create_order_outcome` output is byte-identical to today (`kind == KIND_AMBIGUOUS`, `venue_order_id is None`) | KeyError |
| T30 | same | `test_with_id_ambiguous_overwrites_the_pre_post_context_and_keeps_the_echo`: the context has the venue id **and** the four wire fields; the booking is registered. Plus `test_an_old_context_blob_decodes_with_none_wire_fields` (AR-N6) and `test_a_context_with_an_empty_venue_id_round_trips` | wire fields absent |
| T31 | same | `test_the_no_id_branch_skips_an_intent_whose_post_is_in_flight`: a `_SlowSender` holds the POST, the clock is advanced past `created_ns + 300 s`, one resolver pass runs. `_private_read.paths` gains no activities or open-orders path; the intent stays OPEN; after the POST raises, `_post_in_flight_intent_id is None` | method absent |
| T32 | same | `test_no_id_branch_makes_no_read_below_the_min_age`: age 299.999 s gives zero activities/open-orders reads; 300 s gives the reads. Plus `test_no_id_min_age_is_at_least_the_with_id_floor`: `_RESOLVER_NO_ID_MIN_AGE_NS >= _RESOLVER_ZERO_FILL_MIN_AGE_NS` and `>= 300e9`; and `_NO_ID_WINDOW_BACKSKEW_NS >= 4 * 30e9`. **(r5, DM1)** `_NO_ID_WINDOW_FORWARD_NS == 65e9 + _NO_ID_WINDOW_FORWARD_SKEW_NS == 120e9`; `_RESOLVER_NO_ID_MIN_AGE_NS - _NO_ID_WINDOW_FORWARD_NS >= 180e9`. **(r6, item 4)** `_NO_ID_WINDOW_FORWARD_SKEW_NS == 55e9` exactly and `_NO_ID_WINDOW_FORWARD_NS == _NO_ID_WINDOW_BACKSKEW_NS` (the symmetric choice is pinned as a choice; the test's docstring says it is not derived). **(r6, item 1)** `_NO_ID_MANUAL_STRADDLE_NS == 30e9`. **(r5, DM4)** `_NO_ID_RECHECK_INTERVAL_NS == 60e9`; after a CONTRADICTION, a pass 59.999 s later makes no read and a pass at 60 s re-reads | constants missing |
| T33 | same | `test_same_process_no_id_no_fill_retires_clears_restores_and_resumes`. After a T28(a) AMBIGUOUS and 300 s, negative evidence. Retired `RESOLVER_NO_ID_NO_FILL`; INFO line; booking trued up to 0; `restore_live_trading_budget` applied **once** keyed `noid:<intent_id>` (a second pass is a no-op); `OrderRejected` emitted once for the cached order; `_write_startup_position_evidence` called; AMBIGUOUS cleared; `ambiguous_refusal_clears == 1`; `resume_if_refusals_cleared()` True; a component_degraded CRITICAL was emitted for the episode (count 1) | stays OPEN |
| T34 | same | `test_same_process_no_id_found_fill_is_adopted_and_books_through_accept_fill`. The activities page carries one in-window aggressor leg matching the echo, with unknown id `X`. Pass 1: context `venue_order_id == "X"`, exactly one `OrderSubmitted`, intent still OPEN, no fill event. Pass 2: GET(`X`) is FILLED with LONG, so retired `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, durable fill record under `X`, one `OrderFilled`, AMBIGUOUS cleared (A3). Nautilus order status is FILLED with no `InvalidStateTrigger` | stays OPEN |
| T35 | same | `test_cross_process_sigterm_mid_post_untracked_fill_is_adopted_and_recorded` (MED-2). The store holds an OPEN intent and a no-id r4 context from a prior process; a fresh rig boots; the matching trade is present. Adopt at the first pass at least 300 s old (no `OrderSubmitted`: the order is not in the cache), then the with-id path records the durable fill. It follows `_resolver_fill_order_unknown` T1/T2 exactly as today: no `OrderFilled`, AC6b latch iff `_spend_seeded`. Variant: negative evidence gives `RESOLVER_NO_ID_NO_FILL` with **no** restore and **no** native event | stays OPEN |
| T36 | same | `test_no_id_contradictions_stay_ambiguous_and_page_critical`, parametrized over the tokens: `multiple_candidates`; `unattributed_automated_trade_in_window`; `in_window_open_order`; `unexplained_holding` (no baseline; entry `v > d`; exit `v < d`); **(r5)** `unexplained_holding_delta` (valid baseline, venue net moved by `leg_sign × 1` with `d` unchanged); **(r5)** `leg_after_attribution_window` (an exact echo match at `created_ns + 120 s + 1 ns`). Each: intent OPEN; `_resolver_contradiction_details[intent_id]` has `event == "resolver_evidence_contradiction"`, `no_id == "true"`, `reason == token`, and `next` per §2.8.6 (**r6** `no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution` for holding tokens, `no_id_recheck_60s` otherwise); one ERROR; AMBIGUOUS refusal still present; no retire and no adopt | AttributeError |
| T37 | same | `test_no_id_incomplete_reads_stay_ambiguous`, parametrized: activities neither eof nor early-terminated (page cap; empty cursor); **(r5)** an out-of-order row on one page; **(r5)** page 2's first row newer than page 1's last row; one uninterpretable in-window row; an unparseable TRADE `trade.createTime` anywhere (r6: a non-TRADE row's unparseable time is ignored, T41(x-b)); activities, open-orders or positions read raises; `_durable_net_qty` returns None. Each: OPEN, WARNING, no contradiction entry. Then at age ≥ 15 min: the `open_intent_stale` CRITICAL entry exists (attributed: the existing block; window-only: the new entry with `no_context == "true"`, `next == "no_id_resolver_window_only"`) | AttributeError |
| T38 | same | `test_non_breezy_rows_are_ignored_and_no_fill_retires`: (i) an in-window aggressor whose id maps to another client order id; (ii) a MANUAL aggressor; (iii) an AUTOMATIC non-matching aggressor whose **passive** leg is MANUAL; (iv) an AUTOMATIC row before the window. All are ignored, giving `RESOLVER_NO_ID_NO_FILL`. **(v)** Every CRITICAL detail emitted by T33–T39 contains `next=` and no "operator" substring | AttributeError |
| T39 | same | `test_window_only_mode`: (i) the T27 store-fail intent with negative evidence retires after 300 s (the clearing path for the store-fail branch); (ii) **any** unknown AUTOMATIC in-window aggressor gives a `unattributed_automated_trade_in_window` contradiction (no adoption without an echo); (iii) one same-day instrument with `v != d` gives `unexplained_holding`; (iv) an old-blob context (wire fields `None`) uses window-only rules | stays OPEN |
| T40 | same | `test_resolve_no_order_refuses_without_a_this_run_negative_pass`: a direct call gives no retire and one ERROR "SAFETY H2". Plus `test_resolve_no_order_is_idempotent_against_an_already_retired_intent` | AttributeError |
| T41 | `tests/unit/test_no_id_attribution.py` (new, pure) | (i) Decimal price equality `"0.28" == "0.2800"`; (ii) window boundary inclusive at `window_start_ns`; (iii) quantity `7.63` does not match 1; (iv) a missing `manualOrderIndicator` on an in-window row is uninterpretable; (v) `aggressorExecution.order` fallback; (vi) a non-TRADE row with a `trade` key is uninterpretable (parity with `trade_rows_for_order`). **(vii) Real-data positive control:** load the git-tracked `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json` (10 rows, eof), echo `{slug: tc-temp-sfohigh-2026-09-05-gte73lt74f, price: "0.28", outcomeSide: OUTCOME_SIDE_YES, action: ORDER_ACTION_BUY}`, window start `2026-09-05T20:19:49.006Z - 120 s`, open orders from `orders_open_all.json` (`[]`): verdict `NO_FILL`, matching the operator's 2026-09-06 attestation. **(viii)** The same capture with one AUTOMATIC aggressor's `createTime`, slug and price rewritten to match the echo and fall inside the window gives `ADOPT(<that id>)`. **(ix) (r5, DM3; r6, item 2) Ordering pin against the captured response:** on the same tracked capture, every TRADE row's `trade.createTime` is non-increasing, **at least one exact tie exists** (so a strict check is shown wrong on real data), `out_of_order is False`, and with `window_start` = `2026-08-09T00:00Z` the scan reports `passed_window_start` at the first older **TRADE** row. **(x)** Swapping two adjacent TRADE rows of that capture gives `out_of_order` and `INCOMPLETE("activities_out_of_order")`. **(x-b) (r6, item 2)** Rewriting the capture's first `POSITION_RESOLUTION` row's `afterPosition.updateTime`, and separately an `ACCOUNT_DEPOSIT` row's `createTime`, to a time newer than every row does **not** set `out_of_order`, and the verdict is unchanged (non-TRADE rows never gate ordering). **(xi)** A `prev_row_ts_ns` older than the page's first TRADE row gives `out_of_order` (the cross-page check). **(xii) (r5, DM1)** An echo match at exactly `window_end_ns` is `ADOPT`; at `window_end_ns + 1` it is `CONTRADICTION("leg_after_attribution_window")`; a MANUAL aggressor after the window end is ignored. **(xiii) (r5, DM4)** `holding_delta_consistent`: a pre-existing manual LONG of 3 at both ends is True; +1 on the YES leg with `d` unchanged is False; the NO leg uses `leg_sign = -1` (venue net −1 → −2 is False); an unparseable input is `None`; **(r6)** `manual_net=Decimal(2)` with a +2 move is True, and with a +3 move is False. **(xiv) (r6, item 1)** `manual_leg_net_effect`: (a) the sign table is pinned by equality to the three observed shapes, and the tracked capture's MANUAL `(YES, SELL, SELL_LONG)` aggressor gives `−qtyDecimal`; (b) `(NO, SELL, SELL_SHORT)`, a `None` intent and a missing `qtyDecimal` each give `unreconcilable`; (c) a leg at `after_ns ± 30 s` gives `unreconcilable` (`straddles_snapshot`); (d) a MANUAL passive leg on the slug after `after_ns` gives `unreconcilable`; (e) a leg newer than `now_ns - 120 s` gives `unsettled`; (f) legs on another slug, AUTOMATIC legs and legs at or before `after_ns - 30 s` are not counted; (g) no legs gives `ok`, `Decimal(0)`; (h) the fill size is `qtyDecimal`, not the order's `quantity` (a leg with order `quantity` 7.63 and `qtyDecimal` 2 contributes 2) | module missing |
| T42 | `tests/unit/test_ambig_no_id_firewall_delta.py` (new) | **The callee-set test (§2.8.7 (i)–(vi)).** It imports the firewall constants read-only and asserts: the exact 17-callee (r6) and 4-scanned-name deltas against frozen pre-change literals; `post_order`/`_order_sender`/`sign_headers` and every `post`/`send`/`cancel` name are absent from all resolver sets; await targets and `_private_read` path arguments are exactly the existing GET seams; **(r5)** `_adopt_no_id_venue_order` is scanned and `self._store_set` occurs exactly once across all scanned bodies with the pinned key; the planted-`post_order` non-vacuity including in `_adopt_no_id_venue_order`; **(r5)** the `_note_ambiguous_open`/`_holding_baseline` await-free, egress-free pin | new names absent |
| T43 | `tests/unit/test_submit_intent_latch.py` (append) | `test_resolver_no_id_no_fill_retires_and_round_trips` (the `:860` pattern). Plus `test_retirement_reason_consumers_are_only_the_known_modules`: an AST/grep walk of `src/` and `scripts/` for `RetirementReason.` attribute uses and member-set iteration finds no consumer that enumerates the members | AttributeError |
| T44 | `tests/unit/test_trade_supervisor.py` (append) | (i) `decide_launch_action(lock_free=True, open_intent_detected=True, open_intent_resolvable=True) is LaunchAction.LAUNCH_TO_RESOLVE`; with `False` it is `REFUSE_INTENT_OPEN`; lock held still gives `REFUSE_LOCK_HELD`. (ii) `probe_open_intent_resolvable`: OPEN gives True, corrupt False, RETIRED False, absent False; it raises `PreLaunchProbeInvariantError` with a live `node_pid`. (iii) `_do_launch` with fake ports (`probe_open_intent_state` True, `probe_open_intent_resolvable` True) spawns exactly once, logs `launch_to_resolve_open_intent`, emits WARN `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE`, and emits **no** `INTENT_OPEN_BLOCKS_ARM`. (iv) Boot-retry precheck with the same ports returns `None` (launch). (v) Corrupt (`probe_open_intent_state` True, resolvable False): refused exactly as today. **(r5, DL1) (iii-b)** The boot-retry precheck with a corrupt singleton (state True, resolvable False) returns the refusal and **`ports.spawn` is called 0 times**; the same assertion is added to (v) for `_do_launch`. **(r5, DH1) (vi)** The shape alert: `WITH_ID` gives exactly one WARN `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE`; `NO_ID`, `NO_CONTEXT` and `UNKNOWN` each give exactly one **CRITICAL** `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE_NO_ID` and still spawn once. `probe_open_intent_shape` on real store fixtures returns each of the four shapes, and raises with a live `node_pid`. `trade_supervisor._RESOLVER_CONTEXT_KEY_PREFIX == client.RESOLVER_CONTEXT_KEY_PREFIX` | AttributeError |
| T45 | same | `test_the_existing_intent_open_pins_hold_with_default_ports`: the `:5282` fake with no `probe_open_intent_resolvable` still refuses (the default port returns False). `test_no_supervisor_alert_detail_says_operator` | GREEN (guard) / AttributeError |
| **T46** (r5, DH1) | `tests/unit/test_supervisor_decode_marker.py` (new) | (i) Write, then `supervisor_admits_retirement_reason(..., "RESOLVER_NO_ID_NO_FILL")` is True for the live test pid. (ii) It is False for: an absent file; bad JSON; `v != 1`; the reason missing from the list; a dead `pid`; a live `pid` with different `start_ticks` (pid reuse). (iii) The write is atomic: no partial file is ever visible (a tmp file plus `os.replace`, checked by patching `os.replace` to raise, which leaves the prior file intact). (iv) `_run` writes the marker after `supervisor_started`, and a write failure logs `supervisor_decode_marker_write_failed` and does not stop the supervisor. (v) `node_config` sets `no_id_retire_admitted` from the marker; it is False when the marker is absent | module missing |
| **T47** (r5, DH1) | `tests/unit/test_retirement_reason_superset.py` (new) | The superset test (§2.11): node-emitted reason names ⊆ `RetirementReason` ⊆ the marker's `retirement_reasons`; `probe_open_intent` decodes a RETIRED singleton of every such member as not-OPEN; the planted unknown-reason non-vacuity | the member is absent |
| **T48** (r5, DM2; r6, item 5) | `tests/unit/test_no_id_attribution_purity.py` (new) | (a) The `no_id_attribution.py` purity pin (§2.8.5): forbidden imports, async constructs and calls; the import set is pinned by equality; planted `import asyncio` / `async def` / `import os` non-vacuity. **(b)** `account_activity.py`: its import set equals today's literal, with no async construct and no `open`/`exec`/`eval`/`__import__` call; non-vacuity by a planted `import socket`. **(c)** `_parse_rfc3339_ns`'s callee set equals the §2.8.5 literal; non-vacuity by a planted `open(...)`. The docstring states that T48 checks each module's own source only, not transitive imports | module missing |
| **T49** (r5, DM4) | `tests/unit/test_ambig_no_id_resolver.py` | `test_pre_existing_manual_holding_does_not_block_no_fill_retirement`: the startup evidence shows a manual LONG of 2 on the echo slug, `d == 0`, and the record is quiet. The pre-POST context carries `baselineVenueNet == "2"`, `baselineDurableNet == "0"` and `baselineTsNs`. Negative activities and open orders; positions still 2 after 300 s. Retired `RESOLVER_NO_ID_NO_FILL` (with r4's absolute rule this was a permanent contradiction). Variants: (a) a durable fill on the instrument with `ts_event` inside `evidence.ts_ns - 300 s` gives no baseline, the absolute rule applies, and the result is `unexplained_holding`; (b) refused or non-eof evidence gives no baseline; **(b-2) (r6)** evidence with `created_ns - ts_ns = 120 s + 1 ns` gives no baseline, and at exactly 120 s it gives one; (c) `_holding_baseline` raising leaves the take POSTed exactly once and the context without a baseline; (d) the `unexplained_holding` contradiction, then a node rebooted on a provider without that instrument (past-day), with negative activities and open orders, retires `RESOLVER_NO_ID_NO_FILL`: the automated exit. **(e) (r6, item 1, the first-relaunch case)** The same contradiction for a take whose market is still listed at the next launch: reboot 1 has a provider that **still lists** the instrument (the 16:50Z launch on the take day, market not yet resolved), so the positions leg runs, the result is still `unexplained_holding_delta` with the r6 `next`, and there is no retire. Reboot 2 has a provider without the instrument (after resolution), and it retires `RESOLVER_NO_ID_NO_FILL`. The test asserts exactly two reboots, matching the restated bound | stays OPEN |
| **T51** (r6, item 1, route (d)) | `tests/unit/test_ambig_no_id_resolver.py` | `test_manual_trade_after_the_snapshot_is_reconciled_within_the_recheck`, same-day attributed mode with a valid quiet baseline, negative open orders, and no AUTOMATIC in-window leg. (i) A MANUAL `(YES, BUY, BUY_LONG)` aggressor with `qtyDecimal` 2 on the echo slug 10 s after the snapshot; venue net +2; `d` unchanged. At the first pass (leg < 120 s old) the result is `INCOMPLETE("manual_leg_unsettled")` with no contradiction entry. At the pass where the leg is ≥ 120 s old (≤ 3 re-checks) it retires `RESOLVER_NO_ID_NO_FILL` and logs the INFO `reconciled by 1 manual leg(s)`. (ii) The same with `(YES, SELL, SELL_LONG)` and net −2. (iii) The NO-leg echo with `(NO, BUY, BUY_SHORT)` 1 and net moved −1. (iv) Manual +2 but net +3 (our untracked fill): `CONTRADICTION("unexplained_holding_delta")`. (v) **Stricter than r5:** manual SELL_LONG 1 plus net unchanged (our untracked BUY 1 masked): CONTRADICTION; the test notes r5 would have retired. (vi) The leg 20 s after the snapshot: CONTRADICTION with `manual_reconcile=straddles_snapshot`. (vii) `SELL_SHORT`: `manual_reconcile=unknown_shape`. (viii) A MANUAL passive leg on the slug: `manual_reconcile=manual_passive_leg`. (ix) No manual legs: identical to T49 (r5 behaviour preserved). Every CRITICAL carries the r6 `next` and no "operator" | stays OPEN |
| **T50** (r5, DH1) | `tests/unit/test_ambig_no_id_resolver.py` | `test_no_id_retire_is_blocked_without_the_supervisor_marker`: `no_id_retire_admitted=False` (the default) plus negative evidence gives no retire, the intent OPEN, a `resolver_no_id_retire_blocked` CRITICAL entry with `next == "next_node_boot_rereads_supervisor_marker"`, and the AMBIGUOUS refusal still present. ADOPT still proceeds with the flag False. With the flag True, the same rig retires (T33) | AttributeError |

**These must stay green unmodified, apart from §3.1:**
- `test_execution_egress_firewall_guard.py`: all tests, scanners, pins and the order-coroutine set-equality pin. Only the three constants grow.
- `test_cage_rule_constants_are_pinned.py`.
- `test_polymarket_us_submit_order_chain.py`, including L-36's `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking[...]` (not reused).
- `test_exec_refusal_health_surface.py`, including the 25-producer pin.
- `test_polymarket_us_exec_client.py`, including `:1081` and the AR-N6 decode test (`:4287-4361`).
- `test_current_rung_hold_ambiguous_resolver.py`, except edit 2, and including `:5705`.
- `test_edge2_ac6b_cross_process_fill_budget.py`, `test_trade_supervisor.py` (existing), `test_ct*_supervisor_*`, `test_clear_submit_intent_cli.py` (the CLI is unchanged), and `tests/contract/*`.

### 3.3 Gate (exact commands; read EXIT before any push)

Primary tree (`/home/jon/breezy`):
```bash
cd /home/jon/breezy
# Phase A focused
scripts/ci/run_tests_no_egress.sh tests/unit/test_submit_intent_latch.py \
  tests/unit/test_trade_supervisor.py tests/unit/test_supervisor_decode_marker.py \
  tests/unit/test_retirement_reason_superset.py; echo "EXIT=$?"
# Phase B focused
scripts/ci/run_tests_no_egress.sh tests/unit/test_ambig_latch_resume.py \
  tests/unit/test_ambig_no_id_resolver.py tests/unit/test_no_id_attribution.py \
  tests/unit/test_no_id_attribution_purity.py \
  tests/unit/test_ambig_no_id_firewall_delta.py \
  tests/unit/test_component_health_watch_degraded_throttle.py; echo "EXIT=$?"   # focused
scripts/ci/run_tests_no_egress.sh; echo "EXIT=$?"                                 # full gate
.venv/bin/lint-imports            # from the tree root; require "N kept, 0 broken"
.venv/bin/ruff check src/breezy/adapters/polymarket_us/exec/client.py \
  src/breezy/adapters/polymarket_us/exec/submit_chain.py \
  src/breezy/adapters/polymarket_us/no_id_attribution.py \
  src/breezy/adapters/polymarket_us/account_activity.py \
  src/breezy/runtime/submit_intent.py src/breezy/runtime/trade_cli.py \
  src/breezy/runtime/component_health_watch.py src/breezy/runtime/trade_supervisor.py \
  src/breezy/runtime/trade_supervisor_core.py \
  src/breezy/runtime/supervisor_decode_marker.py src/breezy/runtime/node_config.py \
  src/breezy/adapters/polymarket_us/config.py scripts/ops/ambig_latch_phase_a_check.py
.venv/bin/mypy <the same thirteen files>
```

In a worktree `<wt>`:
- Prefix the test commands with `PYTHONPATH=<wt>/src BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`.
- Run `cd <wt> && PYTHONPATH=<wt>/src /home/jon/breezy/.venv/bin/lint-imports`.
- **Never** `uv sync`, `uv run` or pip.
- If the gate runs under `systemd-run`, pass `-p LimitNOFILE=524288` and put `--basetemp` on `~/.cache`.
- Read the exit code; `-q` doubles into `-qq`.
- **(r5)** The full gate runs once per phase, before each merge (EXIT=0 both times).

---

## §4 File-by-file changes

**(r5, DH1)** Column "Ph" is the merge phase (§2.11). A is supervisor-side and merges first; B merges only after the Phase A check exits 0.

| File | Ph | Change | Size |
|---|---|---|---|
| `src/breezy/runtime/submit_intent.py` | A | **Commit C0 (never reverted, §6):** `RetirementReason.RESOLVER_NO_ID_NO_FILL` with a docstring comment citing CH1 | 6 lines |
| `src/breezy/runtime/supervisor_decode_marker.py` | A | **New (r5).** `write_supervisor_decode_marker`, `supervisor_admits_retirement_reason`; reuses `stop_intent_marker._process_start_ticks` through a public alias | ~80 |
| `scripts/ops/ambig_latch_phase_a_check.py` | A | **New (r5).** The read-only three-check script (§2.11) | ~90 |
| `tests/unit/test_supervisor_decode_marker.py`, `tests/unit/test_retirement_reason_superset.py` | A | New: T46, T47 | new |
| `src/breezy/adapters/polymarket_us/exec/client.py` | B | H1: docstring carve-out (§2.2), plus invariant text "no-id AMBIGUOUS: resolved by the no-id resolver (r4)" replacing the operator-only sentence. H2: `__init__` gains `_ambiguous_refusal_clears = 0`, `_post_in_flight_intent_id: str \| None = None` and `_resolved_no_id_ts_ns: dict[str, int] = {}`. H3: zero-fill counter line. H4: accept-fill clear block. H5: `resume_if_refusals_cleared` + `ambiguous_refusal_clears`. H6: `AmbiguousResolverContext` + 4 wire fields (`to_bytes`/`from_bytes`). H7: two dispatch points in `_resolve_ambiguous_intents` (`:2538-2544` and before `:2703`). H8: `_note_ambiguous_open` + 5 kwargs. H9: `_submit_order` pre-POST block, `finally`, two booking assignments, and the with-id call's 4 kwargs (§2.8.3; the comment at `:5826-5828` is rewritten). H10: constants `_RESOLVER_NO_ID_MIN_AGE_NS`, `_NO_ID_WINDOW_BACKSKEW_NS`, `_NO_ID_NO_FILL_REASON`; `NoIdTradeJoin`; `_resolve_no_id_intent`, `_no_id_trade_activity`, `_resolve_no_order`, `_adopt_no_id_venue_order`. **H11 (r5):** `_NO_ID_FATE_FIXED_NS`, `_NO_ID_WINDOW_FORWARD_SKEW_NS`, `_NO_ID_WINDOW_FORWARD_NS`, `_NO_ID_BASELINE_QUIET_NS`, `_NO_ID_RECHECK_INTERVAL_NS`; the 3 baseline context fields; `_holding_baseline`; `capture_holding_baseline`; `_no_id_next_check_ns`; `_no_id_retire_admitted`; the early-termination loop. **H12 (r6):** `_NO_ID_MANUAL_STRADDLE_NS`; the baseline-age condition in `_holding_baseline`; route (d) in the same-day delta branch; the `manual_leg_unsettled` INCOMPLETE token; the r6 `next` string | ~20 + ~65 (r3) + ~290 + ~90 (r5) + ~30 (r6) |
| `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | B | `NO_VENUE_ORDER_ID: Final[str] = ""`. `classify_create_order_outcome` and both bodies are **byte-unchanged** | 3 lines |
| `src/breezy/adapters/polymarket_us/no_id_attribution.py` | B | **New.** `NoIdLeg`, `NoIdLegScan`, `NoIdEcho`, `NoIdVerdict`, `no_id_aggressor_legs`, `classify_no_id_evidence`, **(r5)** `holding_delta_consistent`, ordering fields, window end; **(r6)** `NoIdLeg.intent`/`fill_qty`, TRADE-only ordering, the `manual_net` kwarg, `ManualNet` and `manual_leg_net_effect` with its closed sign table (§2.8.5). Pure; no I/O; purity-pinned (T48) | ~290 |
| `src/breezy/adapters/polymarket_us/account_activity.py` | B | One additive public alias, `parse_rfc3339_ns` (**r6, item 2:** r5's `activity_create_ts_ns` alias is dropped). No other change; pinned by T48(b)/(c) | 2 lines |
| `src/breezy/adapters/polymarket_us/config.py` | B | **(r5)** `PolymarketUSExecClientConfig.no_id_retire_admitted: bool = False` (never env-read) | 4 lines |
| `src/breezy/runtime/node_config.py` | B | **(r5)** Set `no_id_retire_admitted` from `supervisor_admits_retirement_reason` at the existing `msgspec_replace` site (`:945`) | ~6 |
| `src/breezy/runtime/trade_cli.py` | B | r3: `_exec_client_resume_handler`, `_exec_client_ambiguous_clears_reader`, the degraded-alert kwargs, `handlers=(recon_h, stale_h, contradiction_h, degraded_h, resume_h)` | ~40 |
| `src/breezy/runtime/component_health_watch.py` | B | r3: the constant, 3 kwargs, re-arm, AMBIGUOUS exemption, throttle, tick branch | ~55 |
| `src/breezy/runtime/trade_supervisor_core.py` | A | `LaunchAction.LAUNCH_TO_RESOLVE`; `AlertDetail.INTENT_OPEN_LAUNCH_TO_RESOLVE` and (r5) `INTENT_OPEN_LAUNCH_TO_RESOLVE_NO_ID`; (r5) `OpenIntentShape`; `decide_launch_action(..., open_intent_resolvable=False)` | ~25 |
| `src/breezy/runtime/trade_supervisor.py` | A | `probe_open_intent_resolvable`; (r5) `probe_open_intent_shape` and `_RESOLVER_CONTEXT_KEY_PREFIX`; the `SupervisorPorts` fields with defaults; the `default_ports` wiring; the `_do_launch` and boot-retry branches with the shape-dependent alert (§2.9); (r5) the marker write after `supervisor_started` | ~85 |
| `tests/unit/test_execution_egress_firewall_guard.py` | B | Additions only to 3 constants (§3.1 item 4) | ~50 (comments) |
| `tests/unit/test_no_id_attribution_purity.py` | B | New: T48 | new |
| `tests/unit/test_ambig_latch_resume.py` | B | New: T1–T8b, T13–T16, T20–T25 | new |
| `tests/unit/test_ambig_no_id_resolver.py` | B | New: T26–T40, (r5) T49, T50, (r6) T51 | new |
| `tests/unit/test_no_id_attribution.py` | B | New: T41 | new |
| `tests/unit/test_ambig_no_id_firewall_delta.py` | B | New: T42 | new |
| `tests/unit/test_component_health_watch_degraded_throttle.py` | B | New: T17–T19 | new |
| `tests/unit/test_exec_refusal_health_surface.py` | B | Append T9, T10 | append |
| `tests/unit/test_trade_cli.py` | B | Append T11, T12 | append |
| `tests/unit/test_submit_intent_latch.py` | A | Append T43 | append |
| `tests/unit/test_trade_supervisor.py` | A | Append T44, T45 | append |
| `tests/unit/test_fq_caps_and_ambiguous_2026_10_01.py` | B | Edit 1 | 2 lines |
| `tests/unit/test_current_rung_hold_ambiguous_resolver.py` | B | Edit 2 | ~6 lines |
| `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` | B | Re-pin `_EXEC_CLIENT_SHA256` | 2 lines |
| `docs/core/LESSONS.md` | B | L-36: the dated supersession paragraph (§2.8.0). Nothing else in L-36 changes | doc |
| `docs/core/PROGRESS.md` | A, B | Record both merge shas and the Phase A check output; close the row after Phase B | doc |

**Not touched:**
- `safety.py`, the permit and its ceiling, `operator.env` and either operator cap.
- Live enablement, the family halt and `allow_short` (stays `False`).
- `clear_submit_intent_cli.py`.
- Both wire bodies and `classify_create_order_outcome`.
- `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` and its pins.
- `.venv/` Nautilus.
- `_order_trade_activity` and `page_min_create_ts_ns` (byte-identical; r5 DM3 adds a separate loop).
- The SQLite store schema, and the supervisor's store access. The marker is a file beside the store (r5).

**PR record:**
- `git diff -U0 <base> -- src/breezy/adapters/polymarket_us/exec/client.py`, with hunks H1–H10 labelled.
- The `ast` prefix sha of `_submit_order` up to and including the `arm` statement, equal at base and HEAD.
- The old sha `76784ce8…68a4` and the new `_EXEC_CLIENT_SHA256`.
- The three greps from §3.1.
- **(r5)** Phase B's record also attaches the Phase A check output (`EXIT=0`).
- **PR wording, exactly (Phase B):** "Two existing test assertions are edited, both forced by the A3 ruling. One sha pin constant is re-pinned. Three NO-SEND resolver constants gain additions only (17 callees, 4 scanned names, 2 coroutine names), with no new egress callee, as proven by T42; the one new local-write callee, self._store_set, is pinned to a single call site and key. One planned test (r3 T25(iii)) is inverted per CL1; no committed test is inverted. L-36's 'only no-id path' clause is superseded by coordinator ruling CH1. The EDGE-2 'eof ONLY' completeness amendment is superseded for the new no-id activities scan only, per ruling DM3."
- **PR wording, exactly (Phase A):** "Supervisor-side only: one additive RetirementReason member (never reverted), launch-to-resolve with a shape-dependent alert, and a supervisor decode marker. No existing test is edited."

---

## §5 Live activation

**Load points:**
- `client.py`, `submit_chain.py`, `no_id_attribution.py`, `account_activity.py`, `trade_cli.py`, `component_health_watch.py` and `submit_intent.py` load in the node (`breezy-trade`).
- `trade_supervisor*.py` **and `submit_intent.py`** load in `breezy-trade-supervisor.service`. The supervisor decodes the singleton (`probe_open_intent`, `:412-420`).

**Ordering hazard, and its fix (r5, DH1: enforced by the build, not only by these steps).** An old supervisor decoding a singleton retired `RESOLVER_NO_ID_NO_FILL` raises `SubmitIntentCorrupt` (`submit_intent.py:207-219`). That counts as OPEN, so the 16:50Z launch would be refused, which is the L-48 deadlock again. Therefore (§2.11):
1. **Phase A merge**, then **U1, the supervisor restart**, then the **Phase A check script** (EXIT=0). The supervisor writes the decode marker at start.
2. **Phase B merge**, allowed only with the check's EXIT=0 attached, then the **node relaunch** (S1–S5).
3. All of this happens inside one 01:00–16:40Z window, the same day ("activate code immediately"). If Phase B cannot land that day, Phase A is safe on its own (§2.11, between-phases window).
4. Even if the order were violated, the Phase B node refuses to write the new reason without a valid marker from the running supervisor (`no_id_retire_admitted`).

The new supervisor works unchanged with the still-old node, through D2 adoption.

### 5.1 Steps (amends r3's §5.1; A1/F1/F5 carried)

- **U0 (r5).** Merge Phase A (gate EXIT=0). Record the live node pid `<P>` (the `resolve_lock_holder_pid` read).
- **U1. Supervisor restart** (after the Phase A merge).
  - Run `systemctl --user restart breezy-trade-supervisor`.
  - `KillMode=process` means the node pid is unchanged.
  - Verify: `permit_watch_adopted_live_node pid=<same pid>` and `permit_accepted_gap`. A one-off `permit_absent_in_decision_window` CRITICAL is a known false positive until SUP-ADOPT-PERMIT; note it if it appears.
- **U2 (r5, DH1). Phase A check.** Run `/home/jon/breezy/.venv/bin/python scripts/ops/ambig_latch_phase_a_check.py <PHASE_A_SHA> <P>` and read `EXIT`.
  - 0: attach the output to the Phase B merge record, then merge Phase B (gate EXIT=0).
  - Non-zero: **do not merge Phase B.** Fix forward on Phase A and repeat U1–U2.
  - The coordinator runs this; no operator step.
- **P1. Pre-stop probe.** This is authoritative; P2 stays dropped (F5).
  - It is the `mode=ro` function `intent_open_ro(environ)` from r3, copied verbatim. It reads `CURRENT_INTENT_KEY`; corrupt counts as OPEN; any exception counts as OPEN; it prints only `OPEN` or `CLEAR`.
  - Never use `probe_open_intent` against a live node.
- **Deferral when P1 says OPEN (F1(a)).** Never SIGTERM.
  - Record `AMBIG-LATCH-RESUME activation deferred: open intent at <UTC>`.
  - Re-run P1 every 5 min. The live node's resolver keeps working: a with-id intent retires in 3–138 s. A no-id intent under the old node cannot retire, so the deferral then runs to 16:40Z.
  - At 16:40Z abandon the hand relaunch. **r4:** at 16:50Z the restarted supervisor (U1) LAUNCHES_TO_RESOLVE over the OPEN intent. Once Phase B is merged, that node runs the no-id code, so every shape retires autonomously (§2.9). **No hand step.** (r5) A no-id or no-context shape pages CRITICAL `..._NO_ID` at that launch.
- **S1.** Copy the env and set `BREEZY_PERMIT_EXPIRY_CEILING_NS` to the day's first-boot `expires_at_ns` (A-1). Assert the old pid holds the intent lock. Run P1 a final time.
- **S2.** SIGTERM with no sleep after S1's P1. Wait for `TradingNode: DISPOSED` in bytes written after the kill, then for `intent_lock_is_free`.
- **S3. Post-stop probe:** `probe_open_intent(store_path, node_pid=None)`.
  - CLEAR: go to S4.
  - **OPEN (the W race, ≈5.5 × 10⁻⁴ per relaunch; ≤1.8 % clustered):** raise CRITICAL `AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT` through `emit_alert(resolve_alert_sink(), AlertPayload(...))`, from the copied supervisor env, printing nothing. Then go to S4 anyway.
  - **The detail names the automated next action (CM2):**
    - `shape=with_id next=resolver_get`;
    - `shape=no_id next=no_id_resolver_attributed`;
    - `shape=no_context next=no_id_resolver_window_only`. The old node (pre-r4) wrote no pre-POST context, so a SIGTERM-cancelled POST from it lands here.
  - The shape comes from a `mode=ro` read of `RESOLVER_CONTEXT_KEY_PREFIX + <intent_id>` and its `venueOrderId`.
- **S4.** `spawn_node`, then the boot proof (§5.4).
- **S5. Clearing watch** (only when S3 said OPEN). Watch the new node log FILE for `resolver: retired intent <id>`.
  - `with_id`: as r3. One follow-up relaunch (S1–S4) if a `Trading refused:` line appears between boot and retirement (refuse-once shape (i)). A second refusal raises `AMBIG_LATCH_RESUME_RELAUNCH_REFUSED_AFTER_FOLLOW_UP` and the watch stops; never loop.
  - `no_id` / `no_context`: expect `RESOLVER_NO_ID_NO_FILL` at `created_ns + 300 s` or later, or `adopted venue order` followed by a with-id retirement. A `resolver_evidence_contradiction` (`no_id=true`) or an `open_intent_stale` CRITICAL means the intent stays AMBIGUOUS and the node is up and cannot send. That is residual R-CONTRA (§7): record it in PROGRESS; the resolver re-checks every 60 s, **(r6)** reconciling manual legs on each re-check (route (d)), and the first launch after the market resolves is the automated exit for a holding contradiction, at most two daily cycles from the take (§2.8.6). (r5) A `resolver_no_id_retire_blocked` line means the marker check failed at boot: re-run U2 and record the result. The next node boot re-reads the marker.

### 5.2 Why the hand relaunch cannot hold the lock across SIGTERM (F1(b), carried)

- The node owns `LOCK_EX | LOCK_NB` for its lifetime (`submit_intent.py:556-596`).
- `arm` takes no per-call flock.
- The family halt is an enablement control and is rejected.
- W ≲ 11 s, bounded as in r3.

### 5.3 Clearing-path table (L-48 "How to apply")

| Latch state | Who clears it | Process | Inputs | Runs while the latch is closed and across a day boundary? | Test |
|---|---|---|---|---|---|
| OPEN, with-id | Resolver GET path (unchanged) | Running node, or the launched node | Context, GET, positions, activities | Yes; past-day loader (`:2637-2702`) | Existing suites; T25(i)(ii) |
| OPEN, no-id with an r4 context | **No-id resolver, attributed** (§2.8) | Running node, or the launched node | Context echo, positions, open orders, activities, durable venue-id map | Yes; past-day loader; immediate pass at boot | T25(iii), T33–T38 |
| OPEN, no context (old-code W race; store-fail branch) | **No-id resolver, window-only** | Running node, or the launched node | Positions (all same-day), open orders, activities, venue-id map | Yes | T25(iv), T27, T39 |
| OPEN at 16:50Z, node down (daily cycle; D5) | **Supervisor `LAUNCH_TO_RESOLVE`** spawns the node, then rows 1–3 | New node | As above | Yes | T44, T45 |
| Retired, but a refuse-once AC6b latch remains | The next 16:50Z launch's seed (automatic), or the S5 follow-up relaunch during activation | Next node | Durable fill record | Yes; bounded ≤ 1 trading day | `test_respawn_seed_books_the_cross_process_fill_into_ledger_and_permit` |
| OPEN, corrupt singleton | **None automated** (residual R-CORRUPT): the supervisor refuses and pages CRITICAL `INTENT_OPEN_BLOCKS_ARM` | — | — | Fail-closed and paged | T44(v) |
| OPEN, contradictory or incomplete evidence | The resolver re-checks every 60 s (r5). It self-clears if the evidence becomes complete and consistent. **(r6)** A manual trade on the slug is reconciled in the re-check (route (d)). **(r5, DM4; r6 restated)** Any other holding contradiction exits automatically at the first launch after the market resolves (past-day: positions leg skipped). Only an activities contradiction remains residual R-CONTRA / R-OTHER-AUTOMATION | Node; then the launched node | As above | Yes. Route (d): ≤ 3 re-checks. Holding otherwise: ≤ two daily cycles from the take (≈ 49–55 h for a lead-1 take before 16:40Z on D−1, disclosed) | T36, T37, T49(d)(e), T51 |
| OPEN, no-id, supervisor marker absent at node boot (r5) | The next node boot re-reads the marker (at the latest the 16:50Z launch); ADOPT is unaffected | Next node | Marker file | Yes; ≤ one daily cycle | T46, T50 |

### 5.4 Proof

- **Boot proof:**
  - (r5) the Phase A check output (EXIT=0) and, in the node log FILE, the boot-time `no_id_retire_admitted=True` INFO line that `node_config` emits;
  - the 4 boot lines, the permit line, and `refusal re-poll timer armed`, in the node log FILE;
  - the supervisor's `permit_watch_adopted_live_node`;
  - `lint-imports` evidence from the gate.
- **Positive in-service proof,** at the next AMBIGUOUS (≈0.66–1.1/day):
  - `Trading refused: <AMBIGUOUS_REASON>`;
  - a `component_degraded` CRITICAL;
  - `resolver: retired intent ...`, one of `STATUS_REPORT_ZERO_FILL_TERMINAL`, `STATUS_REPORT_ACCEPT_FILL_TERMINAL` or `RESOLVER_NO_ID_NO_FILL`;
  - `resolver: cleared the AMBIGUOUS trading refusal ...`;
  - `health: resumed from DEGRADED ...` within ≤ 60 s;
  - the next AMBIGUOUS gets a second CRITICAL, never a throttle WARNING.
  - A no-id episode (≈0.18/day) additionally shows no activities or open-orders read before `created_ns + 300 s`. It then shows either the no-id retirement, or `adopted venue order`, then a with-id retirement.
- **Negative proof:**
  - no `InvalidStateTrigger` from the client, except the §2.6 race followed by `re-degrading`;
  - no `RESUMING`/`RUNNING` between an `arm` and its retirement;
  - the count of `Trading refused: <AMBIGUOUS_REASON>` equals the count of AMBIGUOUS CRITICALs;
  - the permit line and its expiry are unchanged by any resume;
  - no `launch_refused_intent_open` in the supervisor log unless the singleton is corrupt.

---

## §6 Rollback

- **C0 (the `RetirementReason` member) is never reverted.** Old code must still decode a singleton or history record retired `RESOLVER_NO_ID_NO_FILL`. Otherwise `_optional_enum` raises `SubmitIntentCorrupt`, the latch reads as latched, and the supervisor refuses to launch (§5).
- **(r5) Phase A's C0 and the marker writer are never reverted.** The `LAUNCH_TO_RESOLVE` branch may be reverted alone, which returns to today's refusal and is safe. Rollback normally means **reverting Phase B only**.
- **Revert Phase B (C1..Cn):** `git revert <C1>^..<Cn>`. This restores the old `_EXEC_CLIENT_SHA256`, the two A3 pins, the firewall constants and L-36.
- Then run the full gate, restart the supervisor (U1), and hand-relaunch the node under §5.1.
- **Precondition: P1 says CLEAR.** If an r4 no-id context is OPEN, the old resolver would GET `order_by_id_path("")`. That fails and stays AMBIGUOUS, which is fail-closed but stuck. So defer the rollback until the r4 node has retired it.
- **After rollback** the behaviour is `3eb4a108` plus a harmless unused enum member.
- No schema migration is needed: the context fields are trailing-optional, and a pre-POST context left behind for a retired intent is never read.

---

## §7 Risks and residuals

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| Alert volume | AMBIGUOUS ≈0.66–1.1/day; max 1/day observed; bounded by the take rate | AMBIGUOUS unthrottled (F3); 1 h throttle for others |
| Unalerted AMBIGUOUS in the clear-to-resume window | Was certain under r2 | F6 counter plus tick (T24) |
| The accept-fill clear re-admits orders | Intended (A3) | Runs last, only when `current_open() is None`. F4 sign-off |
| **The no-id no-fill retirement is wrong (a fill existed)** | Requires **all** of: (1) no matching aggressor leg in a complete activities read (eof, or r5 ordered early termination) ≥ 300 s after arm; (2) no unexplained holding on the same-day leg, by delta or absolute; (3) no in-window IOC open order. The venue's own 30 s timestamp window fixes the order's fate by about `created_ns + 65 s`; measured venue trade lag 0.075–0.215 s | Min age 300 s; completeness by eof or ordered termination, with every row ordering-checked; any uninterpretable row means INCOMPLETE; any unattributed automated leg, in-window or after it, means CONTRADICTION; positions baseline (delta requires a *quiet* snapshot); supervisor marker; written F4-extended security sign-off (merge-blocking); T41(vii)/(ix) real capture |
| Wrong adoption (another order's id) | Requires an in-window AUTOMATIC unknown aggressor that matches slug, side, action, price, qty 1 and IOC exactly, and is not in the venue-id map. The singleton latch excludes any other Breezy order; two candidates mean CONTRADICTION | The with-id path still re-checks by GET plus positions before any retirement |
| Pre-POST write adds latency before the POST | One SQLite commit (`SqliteStateStore.set` COMMITs), the same cost as `arm`'s own write a few µs earlier | None needed; the take is IOC |
| **R-NOCTX** (old-code W race at activation; store-fail branch) | ≈5.5 × 10⁻⁴ per activation; store-fail observed 0 times | Window-only mode retires it if nothing is in the window. Otherwise it stays, paged CRITICAL |
| **R-CONTRA** (contradictory or persistently incomplete evidence) | 0 `evidence contradiction` lines in any node log; 3 `open_intent_stale` (all with-id, pre-L-48 fix). 0 MANUAL trades on a same-day Breezy weather instrument since go-live | Fail-closed (cannot send), CRITICAL with `next=`, **automated 60 s re-check (r5)**. **(r5, DM4)** The "manual buy before the take" case is removed by the holding delta. **(r6, item 1)** A manual trade on the same slug after the snapshot is reconciled by route (d) within ≤ 3 re-checks when its shape is in the table. The remaining holding residual (an unobserved manual shape, a MANUAL passive fill, a manual trade within 30 s of the snapshot, or a not-quiet snapshot plus a manual holding) **exits automatically at the first launch after the market resolves**, because the instrument is then past-day and the positions leg is skipped. **Bound, restated: ≤ two daily cycles from the take.** r5's "≤ one daily cycle" is withdrawn. The disclosed edge is a lead-1 take before 16:40Z on D−1: ≈ 49 h observed and ≤ ≈ 55 h, three launches. An activities-side contradiction is R-OTHER-AUTOMATION. The with-id AC4(e) absolute check (`:2943-2953`, EDGE-2-pinned, unchanged) has the same existing past-day exit |
| **R-CORRUPT** (corrupt singleton) | 0 observed | Fail-closed; supervisor CRITICAL; the node treats it as OPEN-unknown. The only shape needing a human, and it needs a store repair, not a trading decision |
| **R-UNBUDGETED** (cross-process fill confirmed after the seed) | 0 observed | AC6b by design; trading refused for the rest of that day; the next launch books it; no hand step |
| **R-OTHER-AUTOMATION** (another automated tool trades the account) | AUTOMATIC non-Breezy trades seen only 2026-08-05..09, before go-live. Every AUTOMATIC aggressor since 2026-09-05 maps to a Breezy intent (§Evidence r5) | **(r5, DM1) Corrected: r4's "never a wrong retirement" was wrong.** (a) A foreign AUTOMATIC leg that does not match the echo, in or after the window, is CONTRADICTION. It pages, stays AMBIGUOUS, re-checks every 60 s, and does **not** exit at the daily launch, so it is bounded only by the other tool stopping. (b) **A wrong outcome is possible** iff a foreign AUTOMATIC order matches all seven echo fields (slug, side, action, price, qty 1, IOC, AUTOMATIC) inside the now-bounded 240 s window `[created − 120 s, created + 120 s]`, is not in the venue-id map, and ours left no leg. Then ADOPT takes the wrong id, and the with-id path may retire on that order's GET: accept-fill books a foreign fill as Breezy's (budget charged, the conservative direction; one contract of position mis-attributed), or zero-fill retires ours. If ours also left a leg, the result is `multiple_candidates`, a CONTRADICTION. DM1's upper bound shrinks the exposure from `[created − 120 s, +∞)` to 240 s. Observed precondition frequency: 0 |
| Old supervisor decodes the new reason as corrupt | Certain if the order of U1 and S-steps were wrong | **(r5, DH1) Enforced in the build:** Phase A then U1 then the check script (EXIT=0) is the precondition for the Phase B merge; the node-side marker guard fails closed; T47 superset test; C0 and the marker writer are never reverted (§6) |
| **R-MARKER (r5)** (marker absent or invalid at node boot) | Only if the supervisor is down at node boot, the marker write failed, or the supervisor was restarted after node boot onto older code (forbidden by §6) | No-id NO_FILL stays AMBIGUOUS with CRITICAL `resolver_no_id_retire_blocked` (`next=next_node_boot_rereads_supervisor_marker`); ADOPT unaffected; bounded ≤ one daily cycle |
| **Activities completeness (r5, DM3)** | eof-only would hit the 2000-row cap in ≈ 218 days | Ordered early termination needs ≈ 1 page (≈ 200× headroom at the 26.9 h max OPEN age). An out-of-order row means INCOMPLETE. Residual: an undetectable cursor *skip* across pages, the same trust the eof path already places in the cursor |
| Firewall delta read as weakening | Process risk | Additions only; T42 frozen delta, await-target and path proof, non-vacuity; order-coroutine pin untouched |
| `_no_id_trade_activity` duplicates the page loop | Maintainability | Deliberate (EDGE-2 pins). Follow-up `RESOLVER-PAGE-LOOP-DRY` recorded in PROGRESS |
| **Route (d) false pass (r6)** | Needs our fill reflected in positions but missing from activities ≥ 300 s after arm, *and* an exactly offsetting manual fill reflected in activities but not yet in positions ≥ 120 s after it. 0 MANUAL trades on a same-day Breezy weather instrument since go-live | Exact-equality reconciliation; the 120 s settle guard; the 30 s straddle guard; a closed sign table (an unseen shape closes the route); MANUAL passive fills close the route. Stricter than r5, which assumed `manual_net = 0` (T51(v)) |
| `client.py` grows ~375 lines (5983 already, far over 800) | Pre-existing debt | Pure logic moves to `no_id_attribution.py`. No refactor in this item (YAGNI); noted for the refactor backlog |
| The L-36 supersession is not confirmed | Blocks the item | §2.8.0 stop gate before §8 step 1 |

---

## §8 Build sequence

0. **Review gate.**
   - The coordinator confirms the L-36 supersession (§2.8.0) and the DM3 scoped EDGE-2 supersession (§I.3(f)).
   - Run `codegraph_explore` with `projectPath=/home/jon/breezy` on every symbol in §4 before editing.

**Phase A (r5, DH1). One branch; merges first.**

A1. **C0:** write T43 (RED), add the `RetirementReason` member (GREEN), and commit it alone.
A2. Write T44 (including (iii-b) and (vi)), T45, T46 and T47; confirm RED except T45's guard.
A3. `supervisor_decode_marker.py`: T46 GREEN. Then T47 GREEN.
A4. Supervisor: `trade_supervisor_core.py` and `trade_supervisor.py` (§2.9, including the shape probe and the marker write): T44, T45 GREEN.
A5. `scripts/ops/ambig_latch_phase_a_check.py`, plus a dry-run against the current (pre-merge) supervisor. It must print `FAIL` on check 1, which proves non-vacuity.
A6. Full gate (EXIT=0), `lint-imports`, ruff, mypy. Independent review: `trading-bot-architect` (ordering, deadlock-freedom) and `python-reviewer`.
A7. ff-merge Phase A, then U0 → U1 → U2 (§5.1). **Stop unless U2 prints EXIT=0.**

**Phase B. Rebased on Phase A; merge precondition: U2 EXIT=0 attached (B0).**

B0. Attach the U2 output to the Phase B merge record.
1. (Phase B starts here; C0 is already merged.)
2. Write T1–T42, T48, T49, T50 and (r6) T51, and confirm RED, except the GREEN guards T6, T8a, T15 and T25(i)(ii). Capture the output.
3. `component_health_watch.py`: T10, T17–T19 GREEN.
4. `client.py` H2 + H5: T1–T8b, T20–T23 GREEN.
5. `client.py` H3 + H4 + H1, plus edits 1–2: T13–T16 GREEN.
6. `no_id_attribution.py` + the one alias (r6): T41 (including (ix)–(xiv)) and T48 (a)–(c) GREEN.
7. `submit_chain.NO_VENUE_ORDER_ID`, `client.py` H6 + H8 + H9: T26–T30 GREEN. Confirm the order-coroutine set-equality pins are still green **unedited**.
8. `client.py` H7 + H10 + H11 + H12 (r6), `config.py` + `node_config.py` (`no_id_retire_admitted`), plus the firewall constant additions: T25(iii)(iv), T31–T40, T42, T49, T50 and T51 GREEN. Stop if any callee is outside §2.8.7.
9. `trade_cli.py` wiring: T9, T11, T12 and T24 GREEN.
10. (Supervisor work was done in Phase A. Re-run T44–T47 here; they must stay GREEN.)
11. Re-pin the sha. Record hunks, the prefix sha and the greps. Add the L-36 paragraph.
12. Full gate (EXIT=0), `lint-imports` ("N kept, 0 broken"), ruff, mypy (§3.3).
13. **Independent review**, by reviewers who did not build it:
    - `trading-bot-architect`: FSM, races, no-id attribution and min age, the supervisor launch-to-resolve, the activation order;
    - `security-reviewer`: the T42 NO-SEND delta (including the `self._store_set` single-site pin), the A3 and no-id admission changes, the DM3 ordered-termination soundness (TRADE-only ordering, r6), the DM4 delta predicate and the r6 route (d) reconciliation, and the **written F4 sign-off extended to the no-id predicate** (merge-blocking);
    - `python-reviewer`: code quality.
14. ff-merge Phase B (B0 attached). Then the §5.1 node steps S1–S5 (U1 was already done in Phase A), then the §5.4 proof, then the PROGRESS update and the `RESOLVER-PAGE-LOOP-DRY` follow-up row.

---

## §9 Self-assessment

**Score (r6): 95/100.**

What is left for peers:
- **O1–O4 (carry):** the new-reason throttle bypass; `_latch is None` fail-closed; the T20 rig permit; the T1 rig.
- **O5 (carry):** the W bound uses SIGTERM→DISPOSED as a proxy.
- **O6 (r3), closed:** R-NOID is no longer accepted as residual; there is an automated resolver.
- **O7 (new):** the 300 s min age and 120 s back-skew rest on the venue's *documented* 30 s timestamp window (`api-reference_authentication_2026-08-25.md:82`), not on an observed rejection. Same-process safety does not depend on it, because of the in-flight guard. Cross-process, the POSTing process is dead. A probe that sends a stale-timestamp *read* (GET) would confirm the server-side enforcement without any write; it is optional and out of scope.
- **O8 (new):** window-only and attributed modes treat any unattributed AUTOMATIC in-window aggressor as a contradiction. That is conservative, but it pages instead of retiring if the operator ever runs other automation on this account.
- **O9 (new):** a past-day no-id instrument skips the positions leg (AC4(e) D2 parity), leaving the complete activities scan as the evidence.
- **O10 (new):** activity-feed eventual consistency beyond 300 s is unmeasured for no-id. The with-id path relies on 120 s for the same feed with 0 contradictions in 5 episodes.
- **O11 (r5):** the DM3 ordering assumption is pinned on a captured *default-order* page (tracked) and two local `SORT_ORDER_DESCENDING` pages (git-ignored). No real multi-page descending traversal has been observed; across-page ordering is checked on every read, but a cursor skip is undetectable (same trust as eof).
- **O12 (r5):** the "strictly descending" ruling is implemented as non-increasing, because the capture has an exact tie. Peers should confirm that reading.
- **O13 (r5):** the DM4 delta uses the durable startup-evidence snapshot (≤ ~65 s old) as the "pre-POST holding". A fresh pre-POST venue read is impossible under E0-NOSEND. The quiet test (300 s) is a design choice, not a measurement.
- **O14 (r5):** the DH1 marker is a file, not a store key, so the supervisor never writes the SQLite store while a node is live. Peers may prefer a store key.
- **O15 (r6):** the restated bound, "≤ two daily cycles from the take", is exact for D0 takes and for lead-1 takes at or after 16:50Z on D−1. A lead-1 take before 16:40Z on D−1 sees three launches (≈ 49 h observed, ≤ ≈ 55 h). This is disclosed rather than hidden. It rests on 11 observed resolution times (D+1 12:01Z to 15:01Z). Route (d) makes the path rare.
- **O16 (r6):** route (d)'s sign table holds only the three observed manual shapes. `SELL_SHORT` is excluded until observed (L-37), and MANUAL passive fills close the route, per the ruling's "aggressor legs". Both fall back to route (b).
- **O17 (r6):** TRADE-only ordering is chosen over a venue-key proof. The 0-inversion cross-type measurement on 2 pages is corroboration only.

---

## §R6 Disposition

| Item | Disposition | Where |
|---|---|---|
| **1** [MED, both]: DM4(b) bound misstated | **Applied as ruled, with both parts.** **(a) Route (d) added.** In the same complete activities scan, `manual_leg_net_effect` sums the signed fills (`trade.qtyDecimal`, never the order `quantity`) of the MANUAL aggressor legs on the echo slug after the snapshot. The sign comes from a closed `(outcomeSide, action, intent)` table holding only the observed shapes: BUY_LONG +, SELL_LONG −, BUY_SHORT − (the venue nets NO as short YES). If the foreign-holding delta equals that sum exactly, the holding is consistent and the no-fill retirement proceeds within the 60 s re-check cadence, ≤ 3 re-checks given the 120 s settle guard. Anything else stays AMBIGUOUS: an unseen shape (`SELL_SHORT`), a missing field, a leg within 30 s of the snapshot, a MANUAL passive leg on the slug, or a mismatch. Two supporting changes: a baseline older than `created_ns - 120 s` is not captured, so the scan provably covers every post-snapshot manual trade; and the "manual" flag is parsed by the planned `NoIdLeg.manual`, since nothing in `src/` parses it today. Route (d) is **stricter than r5**: r5's zero test passed "manual SELL 1 + our untracked BUY 1" (T51(v)). **(b) Bound restated:** "same-day" is `list_all()` membership, and the provider lists the venue's *active* markets (`provider.py:334-338, 585-599`). So the exit is the first boot after the market resolves. Resolution is observed at D+1 12:01Z to 15:01Z (n = 11), so the exit is ≤ 16:50Z on D+1, **≤ two daily cycles from the take**. r5's "≤ one" is withdrawn. **Tested:** T49(e) covers the first-relaunch case (market still listed: no exit) and the second (exit). **Disclosed to the coordinator:** the store holds lead-1 takes, one at 10-01T16:02Z on the 10-02 market. A lead-1 take before 16:40Z on D−1 sees three launches (≈ 49 h observed, ≤ ≈ 55 h). That is "two daily cycles" plus the part of the day before the first stop, and the plan states it rather than rounding it away. | §Evidence r6; §I.6; goal 8(c); §2.8.3; §2.8.5; §2.8.6; §2.8.7 #17; §2.10; §5.1 S5; §5.3; §7; T32, T36, T41(xiii)(xiv), T49(b-2)(e), T51 |
| **2** [MED, sec]: mixed-type ordering can starve liveness | **Chose TRADE-only ordering.** Why: (1) soundness of early termination needs only TRADE ordering, because only a TRADE row can carry a leg; (2) `_activity_create_ts_ns` uses a different field per type, and a single mis-keyed `positionResolution` row (one per settled market, landing while an overnight intent is OPEN) would starve every read, for no safety gain; (3) the captures cannot prove a venue sort key. Measured anyway with the real function on every capture holding non-TRADE rows: 0 cross-type inversions on the tracked 10-row page and on the 35-row descending pages (23 non-TRADE rows in total), and the ascending page is the exact reverse. That is recorded as corroboration only. `passed_window_start` and `prev_row_ts_ns` are TRADE-only. r5's `activity_create_ts_ns` alias is dropped. T41(x-b) pins that a newer non-TRADE row does not trip ordering. | §Evidence r6; §2.8.5; §2.8.6; §4; T37, T41(ix)(x)(x-b)(xi) |
| **3** [LOW]: Phase-A ancestry check | **Applied.** Check 1 is now `git merge-base --is-ancestor <PHASE_A_SHA> <revision>` alone. The revision is the marker's, bound to `MainPID` by pid and start ticks, and it must equal the newest `supervisor_started` revision and be a hex sha. No `%ct` and no `ActiveEnterTimestamp` comparison remains. It FAILs if the unit sets `BREEZY_BUILD_REVISION` (key presence only, no value printed), since that override would make the revision a declaration, not the tree HEAD. | §Evidence r6; §2.11 |
| **4** [LOW]: DM1 forward skew | **Applied.** 55 s is stated as a **symmetric choice, not derived**; r5's "derived" is withdrawn. The reason no derivation exists is given: venue queueing has no documented bound. The empirical margin (≈ 256× the measured maximum of 0.215 s, n = 9) and the reason for not tightening (a tighter window fails toward liveness) are stated. T32 pins 55 s exactly and forward == back-skew. | §2.8.4; T32 |
| **5** [LOW]: T48 scope | **Applied, both ways.** It is stated that T48 checks a module's own source only. `account_activity.py` is pinned too: T48(b) pins its import set by equality, with no async constructs and no `open`/`exec`/`eval`/`__import__`. T48(c) pins `_parse_rfc3339_ns`'s callee set. Its one first-party import, `external_capital_flows`, has file I/O (`os.open`, `:271`) but no network; that is stated, not hidden. | §I.5; §2.8.5; T48 |

**Not regressed (checked item by item):**
- **r5 DH1:** two phases, the marker, node-side fail-closed, T47; only check 1's mechanics changed. **DM1:** the window and rule 6 are unchanged, and only the skew's justification wording changed. **DM2:** the scan of `_adopt_no_id_venue_order`, the single-site `_store_set` pin and T48(a) are unchanged; the allowlist grows by one pure callee (16 → 17), still with 0 egress. **DM3:** eof-or-ordered termination and non-increasing ties are unchanged, now on TRADE rows. **DM4:** the snapshot, quiet test, delta and 60 s re-check are unchanged; route (d) adds an exact-equality term that defaults to r5 when there are no manual legs (T51(ix)). **DL1:** unchanged.
- **r4 CH1/CM1/CM2/CL1, r3 F1–F6, r2 A1–A5:** unchanged. Every new CRITICAL `next=` still names an automated route and never "operator" (T38(v), T45, T51).
- `_order_trade_activity`, `page_min_create_ts_ns`, `_activity_create_ts_ns`, `classify_create_order_outcome`, both wire bodies and `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` and its pins are byte-unchanged.

**Invariants restated (r6).**
- Nautilus is unmodified, and its in-flight poller stays disabled.
- `allow_short` stays False, and both wire bodies are byte-unchanged.
- No safety, settlement or contract test is weakened. The only ruled changes are the disclosed ones: the two A3 edits, the sha re-pin, the constant additions (17 callees, 4 scanned names, 2 coroutine names), the planned-test T25(iii) inversion, the L-36 supersession and DM3's scoped EDGE-2 supersession (no test edited).
- The two operator caps, the permit and its ceiling are untouched, unread and unnamed.
- Live enablement and the family halt are untouched. `no_id_retire_admitted` gates a retirement, never an order, and is never env-read.
- The NO-SEND firewall gets **no new egress callee**. r6 adds one pure, I/O-free callee (`manual_leg_net_effect`), proven by T42 and T48.
- No operator step is needed to resume or to activate. Route (d), the re-check and the post-resolution launch are all automated, and the Phase A check is run by the coordinator.

---

## §R5 Disposition

| Item | Disposition | Where |
|---|---|---|
| **DH1** [HIGH, both]: enforce restart ordering in the build | **Applied as ruled.** **Phase A** = C0 + the supervisor changes (launch-to-resolve, shape probe, decode-marker writer) + the `submit_intent` change (C0 is its only change) + the check script. Then a supervisor restart in 01:00–16:40Z. Then `scripts/ops/ambig_latch_phase_a_check.py`, which verifies (1) the supervisor started after the Phase A merge (systemd `ActiveEnterTimestamp` > merge time, and `supervisor_started revision` descends from the Phase A sha), (2) a decode check of the new member (a live, pid+start-tick-bound marker lists it, plus an in-memory `SubmitIntent` round-trip), and (3) `permit_watch_adopted_live_node` for the same pid as the lock holder. **EXIT=0 is the Phase B merge precondition.** **Phase B** = everything node-side. **Node-side guard:** `_resolve_no_order` refuses `RESOLVER_NO_ID_NO_FILL` unless `no_id_retire_admitted`, set at boot from the running supervisor's marker. The default is False. Absent means it stays AMBIGUOUS and pages CRITICAL `resolver_no_id_retire_blocked`; the next boot re-reads. **Superset test** T47: node-emitted reasons ⊆ `RetirementReason` ⊆ the marker's list, and the supervisor decodes every one. **Launch alert:** launch-to-resolve over no-id, no-context or unknown is CRITICAL `TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE_NO_ID`; with-id stays WARN. The between-phases window is stated and bounded. | §2.9, §2.11, §4 (Ph column), §5, §6, §7, §8 Phase A/B; T44(vi), T46, T47, T50 |
| **DM1** [MED, sec]: bound the attribution window | **Applied.** The window is `[created − 120 s, created + 120 s]`. Forward = 65 s (P-c) + **skew 55 s, derived**: arm→sign latency, undocumented venue queueing and `createTime` granularity, against a measured total of 0.075–0.215 s (n = 9, store × capture), chosen symmetric with the back-skew (≈ 558× the measured max). Any non-ignored leg after the end, including an echo match, is `CONTRADICTION("leg_after_attribution_window")`. Min age 300 s ≥ window end + 180 s. **R-OTHER-AUTOMATION corrected:** r4's "never a wrong retirement" is withdrawn. The wrong-adoption path is stated with its preconditions and its conservative failure direction, and it is bounded to the 240 s window. | §2.8.4, §2.8.5 rule 6, §7; T32, T36, T41(xii) |
| **DM2** [MED, sec]: firewall scan coverage | **Applied.** `_adopt_no_id_venue_order` is added to `EXEC_RESOLVER_COROUTINES`, so its body is scanned. Its three callees (`self._store_set`, `dataclasses.replace`, `adopted.to_bytes`) are allowlisted, and `self._store_set` is compensated by a single-site, single-key pin across all scanned bodies (T42(iv)) plus planted non-vacuity. `no_id_attribution.py` is pinned pure by T48: forbidden asyncio/os/network/subprocess/transport imports, no async constructs, no `open`/`exec`/`eval`/`getattr`, an equality-pinned import set, and non-vacuity. T42(vi) also pins the unscanned `_note_ambiguous_open`/`_holding_baseline` as await-free and egress-free. Totals: +16 callees, +4 scanned names, +2 coroutine names, 0 egress. | §I.3(c), §I.5, §2.8.5, §2.8.6, §2.8.7; T42, T48 |
| **DM3** [MED, sec]: activity completeness cap | **Applied, with one disclosed reading.** `_no_id_trade_activity` completes on `eof` **or** on the first parsed row older than the window start (early termination). Every row read is ordering-checked within and across pages; any row newer than its predecessor is `INCOMPLETE("activities_out_of_order")`. **"Strictly descending" is implemented as non-increasing:** the git-tracked capture `AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json` holds an exact timestamp tie (two TRADE rows at `2026-08-05T13:40:00.704590303Z`), as do the local 35-row `SORT_ORDER_DESCENDING` captures. A strict check would fail every real read. **Pinned by test** T41(ix) on the tracked capture, with tie existence asserted, plus swap and cross-page violations, (x) and (xi). **Headroom, measured:** 35 rows of total history on 09-27; 0 multi-page resolver reads in 67 node logs; eof-only would exhaust the 2000-row cap in ≈ 218 days, early termination needs ≈ 1 page (≈ 200×). Scoped supersession of EDGE-2's eof-only rule for this scan only; `_order_trade_activity` is untouched. | §I.3(f), §2.8.5, §2.8.6, §7, §9 O11/O12 |
| **DM4** [MED, arch]: R-CONTRA has no automated exit | **Applied.** **Pre-POST snapshot:** `_submit_order` has no pre-POST venue read and cannot gain one (E0-NOSEND). The pre-POST context therefore records the existing durable venue-holding evidence (`STARTUP_EVIDENCE_KEY`, eof-complete, ≤ ~65 s old) plus Breezy's durable net. This is done inside the already-permitted `_note_ambiguous_open`, so there is no new `_submit_order` callee. It is used only when *quiet* (no durable fill on the instrument within 300 s of the snapshot), which closes a lagging-exit masking path. **Delta, not absolute:** foreign holding = venue net − leg_sign × durable net, compared at the baseline and now; a mismatch is `unexplained_holding_delta`. **Named cadence:** a 60 s automated re-check. **Automated exit, no operator step:** the next daily launch makes the instrument past-day (the provider loads only today's instruments, `:2923-2931`), so the positions leg is skipped and the complete activities scan decides. Bound ≤ one daily cycle. **Residual named and bounded with evidence:** a manual trade on the same slug after the snapshot, or a not-quiet snapshot plus a manual holding; 0 MANUAL trades on a same-day Breezy weather instrument since go-live. | §2.8.3, §2.8.4, §2.8.6, §5.3, §7; T36, T41(xiii), T49 |
| **DL1** [LOW] | **Applied.** The 3.2 s observed fill-retirement latency and the 0.075–0.215 s venue trade lag are recorded beside the 300 s margin (≈ 94×) and the 120 s window. T44(iii-b) asserts `spawn` is called 0 times when the singleton is corrupt on the boot-retry path; (v) asserts the same on `_do_launch`. | §2.8.4; T44 |

**Not regressed (checked item by item):**
- **r1 A1–A5 and r2 F1–F6:** the resume method, throttle, F6 counter and A3 clears are unchanged.
- **r3 CH1:** the automated no-id resolver is kept. **CM1:** launch-to-resolve is kept, now with a shape-dependent alert. **CM2:** every new CRITICAL carries `next=` and no "operator" (T38(v), T45). **CL1:** the inversion is unchanged.
- **r4's verified-OK list:** deny before any spend at `:5451-5452`; `arm` refuses on OPEN; launch-to-resolve deadlock-free at 16:40/16:50Z; multi-match is CONTRADICTION; the r4 additions are additive and non-egress.
- `_order_trade_activity`, `classify_create_order_outcome`, both wire bodies and `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` and its pins are byte-unchanged.

**Invariants restated (r5).**
- Nautilus is unmodified, and its in-flight poller stays disabled.
- `allow_short` stays False, and both wire bodies are byte-unchanged.
- The two operator caps, the permit and its ceiling, live enablement and the family halt are untouched. `no_id_retire_admitted` gates a retirement, never an order, and is never env-read.
- The NO-SEND firewall gains additions only (16 callees, 4 scanned names, 2 coroutine names) and **no new egress callee** (T42).
- No safety, settlement or contract test is weakened. The only ruled changes are the L-36 supersession and the T25(iii) inversion, plus the disclosed A3 edits, sha re-pin and constant additions carried from r4. DM3's scoped EDGE-2 supersession edits no test.
- No operator step is needed to resume or to activate. The Phase A check is run by the coordinator, and every residual has an automated exit or is bounded and paged.

---

## §R4 Disposition

| Item | Disposition | Where |
|---|---|---|
| **CH1** [HIGH, both]: no-id AMBIGUOUS needs the operator; automated resolver mandatory (coordinator ruling) | **Applied as ruled; see the notes below.** | §0 D4, goals 1/7/8; §1; §2.8; §3 T25–T43; §5.3; §7 |
| **CM1** [MED, sec]: 16:40Z stop / 16:50Z refusal deadlock (L-48) | **Applied, by the "supervisor relaunches rather than refusing" alternative.** `LaunchAction.LAUNCH_TO_RESOLVE` launches over any *decodable* OPEN intent (additive kwarg plus a port with a False default, so the existing pins `:391-398` and `:5282-5301` stay green unedited); the boot retry does the same. Safety: `_submit_order` denies OPEN_INTENT_WAIT before any spend, and `arm` refuses. The §2.9 table proves every resolvable shape retires after the 16:50Z launch with no hand step. **Live evidence that D5 is real:** `launch_refused_intent_open` at 2026-09-24T16:50:11Z; intent `5e50e0d9` stranded 26.9 h until a hand launch. Residuals named with bounds: R-CORRUPT (0 observed), R-CONTRA (0 contradictions logged), R-UNBUDGETED (≤ 1 trading day, 0 observed). **New ordering hazard found and fixed:** the supervisor also decodes `submit_intent`, so it is restarted **before** the node (§5), and C0 is never reverted (§6). | §0 D5; §2.9; §5; §6; §7 |
| **CM2** [MED]: the S5 CRITICAL for `no_context` must name the automated next action | **Applied.** S3 details are `shape=with_id next=resolver_get`, `shape=no_id next=no_id_resolver_attributed` and `shape=no_context next=no_id_resolver_window_only`. The in-node no-id contradiction and window-only stale entries carry `next=`, and the supervisor's WARN names launch-to-resolve. No message says "operator" (T38(v), T45). | §2.10; §5.1 S3/S5 |
| **CL1** [LOW]: T25(iii) pins the absence of a no-id path | **Inverted and disclosed as a ruled test change,** like F2. T25(iii) (r4 no-id context) and T25(iv) (no context) now assert autonomous `RESOLVER_NO_ID_NO_FILL` retirement after 300 s. T25 was a *planned* test; no committed test is inverted. The committed `test_open_intent_without_a_durable_context_makes_no_get_and_stays_open` stays unedited and green, now pinning "no read before the min age". | §I.3(d); §3.1 item 5; §3.2 T25 |
| **Correction: r3 §2.7 off by one** | r3 counted `intent/current` as a 25th intent. There are 24 distinct intents, all POSTed: 6 AMBIGUOUS (5 with-id, 1 no-id), IOC miss 3/24. The reviewers' "1 of 25" is therefore "1 of 24". Upper volume figure 1.1/day. | §2.7 |
| **Correction: design-floor premises** | P-a: there is no venue client order id, so the context is keyed by `intent_id` (known pre-POST) and carries `client_order_id` plus the venue-echoed wire fields; the "activities join by `client_order_id`" becomes an attribution join on the echo. P-b: open orders have no `eof`, so completeness is a strict full-list parse. | §2.8.1 |
| **Binding-lesson conflict surfaced** | L-36 "`clear_submit_intent` ... stays the only no-id path" conflicts with CH1. It is ruled superseded for the no-id class, with L-36 amended in the same merge, and a stop gate if the coordinator does not confirm. | §2.8.0; §8 step 0 |

**How CH1 was applied:**
- **Pre-POST durable context.** It is keyed by `intent_id` (P-a: the venue has no client order id), carries `client_order_id` and the four venue-echoed wire fields, and is written synchronously after `arm` and before the POST. It reuses the already-permitted `_note_ambiguous_open`, so the order-coroutine allowlist and its set-equality pins are unchanged. A failed write never POSTs.
- **Min age 300 s, derived from evidence:** the venue's 30 s timestamp window, `maxBlockTime` 5 s, and about 2× the with-id 120 s floor. A same-process in-flight guard is added.
- **Complete reads only:**
  - eof-complete positions;
  - a strict full-list open-orders parse (P-b: that endpoint has no `eof`);
  - eof-complete activities, attributed by echo inside the singleton-latch window, excluding known venue ids, MANUAL aggressors and MANUAL-passive rows.
- **Found order or fill:** ADOPT the venue id into the durable context, emit `OrderSubmitted` same-process, and continue on the **unchanged with-id path**. Any fill goes through the existing accept-fill path, which covers MED-2 (SIGTERM mid-POST, untracked fill; T35).
- **Nothing found, baseline unchanged:** `RESOLVER_NO_ID_NO_FILL`, with an H2 analogue, a zero-fill-style true-up and restore, and the A3 clear.
- **Contradictory or incomplete:** stays AMBIGUOUS, CRITICAL `resolver_evidence_contradiction` (`no_id=true`) or `open_intent_stale`. Never retired on partial evidence.
- **Context-absent OPEN** (old-code W race; store-fail) is handled by a window-only mode.
- **Verified against `:2788-2983`:** side-by-side predicate table, and GL-1/R-7 hold (create-time classification byte-unchanged).
- **Frequency from store and logs:** 1/24 intents (4.2 %), 1/6 AMBIGUOUS; the 09-05 no-response case; ≈0.18/day at the current rate.
- **Rewritten:** R-NOID (now R-NOCTX/R-CONTRA), goal 7, and the clearing table (rows 2–4). r3's "strict subset of W" claim is withdrawn.
- **NO-SEND:** +12 non-egress resolver callees, +3 scanned names, +2 coroutine names, proven by T42.

**Invariants restated.** Nautilus is unmodified, and its in-flight poller stays disabled. `allow_short=False`, and both wire bodies are byte-unchanged. The caps, permit, ceiling, live enablement and family halt are untouched. The NO-SEND firewall gains additions only, with no new egress callee, as proven by T42; the order-coroutine pins are untouched. No safety, settlement or contract test is weakened. The ruled edits are listed in §3.1, including the CL1 inversion of a planned test. No operator step is needed to resume; the only human-repair case is a corrupt store (R-CORRUPT), which is fail-closed and paged.

---

## §R3 Disposition (kept from r3 for the record)

| Item | Disposition | Where |
|---|---|---|
| **F1** [TBA HIGH] no deadlock after STOP (coordinator ruling) | **Applied as ruled.** (a) P1 OPEN → never stop; defer while the live node's resolver works. (b) Holding the intent lock from P1 through SIGTERM is **infeasible** without changing the node's lock semantics: the node owns the exclusive flock for its whole life, and `arm` takes no per-call flock (`submit_intent.py:391-419, 556-596`). The family halt was rejected because it is an enablement control. The gap is bounded instead: W ≲ 11 s, ≈5.5 × 10⁻⁴ per relaunch, ≤1.8 % clustered. (c) Post-stop OPEN → named CRITICAL `AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT` (`with_context`/`no_context`), then **spawn anyway**: the node's boot does not refuse on OPEN, and its immediate and periodic resolver is the autonomous clearing path (`client.py:1997-2043`). "Refuses once" was verified: the 09-12 origin, closed by the awaited immediate pass; residual shapes are handled by one bounded S5 follow-up relaunch. The no-id sub-case has no autonomous path (operator-only by design) and is recorded as R-NOID. A clearing-path table was added. The "supervisor handles it at 16:50Z" claim is dropped and replaced with code-cited supervisor behaviour (`:1131-1189`, `:1233-1261`, `:1592-1619`). The brief cited **L-39**; L-39 is the operator-control census lesson (obeyed: no reserved control is named by its env var). The deadlock lesson applied is **L-48**. | §0 goal 7, §1, §5.1, §7 |
| **F2** [sec HIGH] disclose the second test edit | **Applied.** `test_current_rung_hold_ambiguous_resolver.py:1308` is re-expressed as `refusals_before` minus AMBIGUOUS, plus a non-vacuity assert (stricter). The `trading_refusals` grep is shown and every hit is classified. The hunk count is corrected (five, including the F6 counter lines), and the exact PR wording is given. | §3, §4 |
| **F3** [sec] AMBIGUOUS never throttled (coordinator ruling) | **Applied as ruled.** `ambiguous_reason` is exempt from the throttle; every AMBIGUOUS episode emits one CRITICAL; other reasons stay throttled. Storm bound: the singleton latch caps AMBIGUOUS alerts at the take rate. T17/T18 now use a non-AMBIGUOUS reason; T23(ii) pins the exemption. | §2.3, §2.7, §3, §5.2 |
| **F4** [TBA] pin provenance | **Applied.** `87b3725b` is quoted verbatim (full sha). A side-by-side predicate table is added. A written security-reviewer sign-off that the fill predicate is at least as strong as the zero-fill one is merge-blocking. | §0 D3, §2.2, §8 |
| **F5** [TBA] P2 log-tail | **P2 dropped; P1 is authoritative.** Reason: `arm` persists OPEN before any POST, so the store already shows every in-flight take; a log tail adds nothing. | §5.1 |
| **F6** [TBA] second AMBIGUOUS before resume | **Applied, with a design fix.** The resume is refused (step 2; step 5 while that intent is OPEN). The alert gap is real: no transition happens, pinned by `test_polymarket_us_exec_client.py:1081`. It is closed by `ambiguous_refusal_clears` (one int, incremented in both clear blocks, with no new callee) plus the degraded-alert closure registered on the re-poll timer (the FU-8b pattern). The count is exact even when an AMBIGUOUS is added and cleared between ticks. T24 covers three variants. | §0 D2, §2.1, §2.3, §2.3a, §2.6, §3 |
| LOW: period mismatch | **Applied.** 2.3-day rate × 29-day fraction is stated; bracket 0.66–0.9/day. | §2.7 |
| LOW: T14(ii) isolation | **Applied.** Labelled as an isolation test that does not represent a reachable AMBIGUOUS state. | §3 |
| LOW: cross-session early return | **Applied.** Stated as intended, with the reason. | §2.2 |
| LOW: T4(iii) DEGRADING spy | **Applied.** A concrete msgbus spy on the synchronous DEGRADING publish. | §3 |

Invariants restated: Nautilus is unmodified; `allow_short=False`; the caps, permit, ceiling and live enablement are untouched (the family halt was explicitly rejected as an F1 tool); the NO-SEND firewall and its allowlists are unmodified and not widened; the supervisor is unmodified; no safety test is weakened (the two ruled A3 assertion edits are disclosed, and one is stricter).

---

## §R2 Disposition (kept from r2 for the record)

| Item | Disposition | Where |
|---|---|---|
| **A1** [TBA HIGH] hard precondition on relaunch | Applied in r2; **revised in r3 by F1 and F5** (P2 dropped; post-stop OPEN now spawns the clearing node instead of leaving it down). | §5.1 |
| **A2** throttle now (coordinator ruling) | Applied in r2; **AMBIGUOUS exempted in r3 by F3.** | §2.3, §2.7 |
| **A3** accept-fill path in scope (coordinator ruling) | Applied in r2; **r3 corrects the test-edit count to two (F2) and adds the predicate table (F4).** | §0 D3, §2.2, §3 |
| **A4** [sec] scope in §2.3 | Applied. | §2.4, §3 |
| **A5** race tests | Applied; the F6 race was added in r3. | §2.1, §2.6, §3 |
| LOW: split T8 | Applied. | §3 |
| LOW: cite the re-poll constant | Applied. | §0, §5.2, §7 |
| LOW: record the re-pin diff and the new sha | Applied; **five hunks in r3.** | §3 |
