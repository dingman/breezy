# R-7 build brief (2026-09-04) — DRAFT, under peer review

Authored by code-architect against `757daba` (R-6.5b landed). Consumes EXEC_SPINE_NEXT §A/§D. The send path is wired but structurally unreachable until the operator's OP-1..OP-4 positive control and enablement; operator-reserved caps are named by role only.

## R-7 BUILD BRIEF — the send path, wired and structurally unreachable

Repo `/home/jon/breezy` @ `757daba`. Gate: `scripts/ci/run_tests_no_egress.sh`. RED first. Nautilus immutable; `allow_short` False; never assign an operator-reserved control; never weaken a barrier.

### 0. Verify before writing (three commands, shell grep — Grep tool is blind under `.venv`)
- `grep -n "generate_order_filled\|generate_order_rejected\|generate_order_submitted" .venv/lib/python3.13/site-packages/nautilus_trader/live/execution_client.py` — expect **0**: they are inherited from `execution/client.pyx` (`generate_order_submitted:411`, `generate_order_rejected:447`, `generate_order_accepted:491`, `generate_order_filled:820`, verified). Record the 0 as the "not overridden in live" fact.
- `grep -n "async def post" -A 9 .venv/.../core/nautilus_pyo3.pyi` → `post(url, params, headers, body: bytes|None, keys, timeout_secs)` (`:5444-5452`, verified). `body` is the ONLY new kwarg `post_order` needs.
- Signing covers `timestamp + method + path` only (`docs_snapshots/api-reference_orders_create-order_2026-08-25.md`, `X-PM-Signature`). **The body is unsigned** → `Ed25519WriteRequestSigner` and `signing.py` are untouched by R-7.

### 1. Call chain — `exec/client.py::_submit_order`, denying at every step
Replace `_STANDING_ORDER_REFUSAL` (`:1399`) only. `_submit_order` keeps its two existing refusals first (latched `trading_refusals`; `cache.account_for_venue(...) is None`), then makes **exactly one new call**: `await self._dispatch_submit(command)`. Every failure below is `generate_order_denied` (no venue contact), except D8/D9.

| # | step | denies when | primitive |
|---|---|---|---|
| D1 | send capability present | `self._order_sender is None` (factory declined to inject) | `factories.py` |
| D2 | canonical-string predicate | `self._write_canonical_verified() is not True` | injected zero-arg callable reading `write_transport.WRITE_CANONICAL_STRING_VERIFIED` **at call time** (Q2: injection, never import) |
| D3 | permit | `not isinstance(permit, LiveTradingPermit)` or `assert_live_order_submission_permitted(...)` raises | `safety.py:569`, authorization first positional + `isinstance` guard on the returned capability |
| D4 | order shape → body | any refusal in §2 | pure mapper, no I/O |
| D5 | caps re-read **and** ledger reserve (one call, caps read per call) | `LiveTradingPermissionError` — enablement/budget/position absent, malformed, exhausted, clock rewound | `DailySpendLedger.authorize_order_cost(price_usd=, quantity=, now_ns=)` → `SpendBooking` (`operator_controls.py:299-378`) |
| D6 | startup reconciliation ran | `self._intent_reconciled is not True` | set **only** by `latch.reconcile_at_startup(has_durable_fill_record=…, now_ns=…)` in `_connect` (§D "R-7 must call reconcile_at_startup before first arm") |
| D7 | latch arm | `SubmitIntentLatched` (prior crash / duplicate arm) or `SubmitIntentInvalidFingerprint` / `SubmitIntentLockNotHeld` | `SubmitIntentLatch.arm(fingerprint, now_ns=)`; fingerprint = sha256 over `(instrument_id, side, qty, price, tif, client_order_id)` — never headers, never the signature. **Ledger reserve precedes arm; on D7 the booking is released.** |
| D8 | sign + POST | — | `signer.sign_headers("POST", ORDERS_PATH)` → `write.post_order(base_url, headers=…, body=…)` |
| D9 | outcome | see below | retire / release |

**Ordering vs the blueprint:** `trial_day_latch.commit` (strategy side, already committed) → D1–D7 arm → POST → retire. The intent latch is armed *after* the trial commit and never before.

**D3 one-caller pin stays exactly one.** `post_order` is a **sibling method on `PolymarketUSWriteTransport`** reusing the SAME `self._post` closure built in `__init__`. It never calls `_build_post_only_callable`; the D3 caller count is unchanged at 1, and a new RED asserts `post_order`'s AST body contains no reference to that name.

**D9 outcome rules (EXEC_SPINE §R-7 taxonomy, three leaves, AMBIGUOUS is the default):**
- `DEFINITIVE_ACCEPT` — status 200 **and** `id` present **and** a durable fill record (`executions[*].order.id`, `lastPx`, `lastShares`, `tradeId` ALL present; `total=False`, absence expected, L-17): `true_up_booking(filled_cost_usd=avgPx×cumQuantity)` → `retire(intent_id, DEFINITIVE_ACCEPT)` → `generate_order_submitted` → `generate_order_filled` (§3).
- `DEFINITIVE_REJECT` — **4xx AND a `google.rpc.Status`-shaped body AND no `order.id`**: `release_booking` → `retire(..., DEFINITIVE_REJECT)` → `generate_order_rejected`. This exact triple, nothing looser.
- `AMBIGUOUS` — everything else: 5xx, `VenueTransportError`, `CancelledError`, empty/unparseable body, 200-with-`id`-but-no-durable-execution, 4xx **with** an `id`. **Latch stays OPEN, booking is NOT released** (spend stands; releasing budget on a maybe-filled order re-grants it), `generate_order_submitted` only if an `id` was returned, and a `trading_refusal` is latched. Exit is the operator clear tool (§4).

### 2. Order body — 1-contract limit IOC BUY
Schema: `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_create-order_2026-08-25.md`, `POST /v1/orders`, `CreateOrderRequest`. `price` is `Amount{value: decimal STRING, currency:"USD"}`; `quantity` is a JSON **number** (double); `tif` an enum string. Nautilus `OrderFactory.limit(..., time_in_force=TimeInForce.IOC)` maps:

| Nautilus | venue field | value |
|---|---|---|
| `instrument.info["slug"]` (same key `_assert_market_matches` checks, `reports.py:472`) | `marketSlug` | required |
| `OrderType.LIMIT` | `type` | `ORDER_TYPE_LIMIT` |
| `order.price` | `price` | `{"value": f"{px:.2f}", "currency":"USD"}` |
| `order.quantity` | `quantity` | `1` (int-valued float) |
| `TimeInForce.IOC` | `tif` | `TIME_IN_FORCE_IMMEDIATE_OR_CANCEL` |
| `OrderSide.BUY` + YES leg | `outcomeSide`+`action` | `OUTCOME_SIDE_YES` + `ORDER_ACTION_BUY` (never `intent`; `outcomeSide` takes priority if both set — send one form only) |
| — | `manualOrderIndicator` | `MANUAL_ORDER_INDICATOR_AUTOMATIC` |
| — | `synchronousExecution` / `maxBlockTime` | `true` / `"5"` — the ONLY way `executions` is populated ("Executions if synchronous execution was requested"), i.e. the only source of the durable fill record C-11 relies on |

**Refused before any POST (deny, unmappable):** `order_type != LIMIT`; `time_in_force != IOC`; `side != BUY` (a SELL is a naked short); `quantity != 1` or non-integral; `price <= 0.00` or `>= 1.00` (`binary_option.pyx:144-145` constrains nothing; `parsing.py:282-283` is inclusive); `post_only`, `reduce_only`, `display_qty`, `expire_time`, `trigger_price` set; instrument not a `BinaryOption` with a resolvable slug; no YES/NO leg derivable from `instrument.info`. `participateDontInitiate` is never sent (maker-only). `cashOrderQty`, `slippageTolerance`, `goodTillTime` never sent.

### 3. Reports → native events (R-7-FILL, R-7-STATUS)
- **Fill.** From a durable `Execution`, build the `FillReport` with the SHIPPED `reports.parse_fill_report(payload, instrument=, account_id=, report_id=, ts_init=)` (`reports.py:744`) — it already refuses non-fill `type`s and non-taker executions (`_assert_taker_fill:708`) — then call `generate_order_filled(strategy_id, instrument_id, client_order_id, venue_order_id=VenueOrderId(order["id"]), venue_position_id=None, trade_id=TradeId(execution["tradeId"]), order_side=BUY, order_type=LIMIT, last_qty, last_px, quote_currency=USD, commission=Money(commissionNotionalCollected), liquidity_side=TAKER, ts_event=transactTime_ns)` (`execution/client.pyx:820-900`). Commission is the **measured** venue number, never `fees.py`'s model. `generate_fill_reports` keeps returning `[]` until the ORDER surface is read — a `FillReport` is NEVER synthesised from activities.
- **Reject.** `generate_order_rejected(strategy_id, instrument_id, client_order_id, reason=<OrdRejectReason + status>, ts_event)` (`client.pyx:447`). `due_post_only` stays default `False`.
- **R-7-STATUS.** `generate_order_status_report` (currently `None`, `client.py:857-871`) becomes a by-id `GET /v1/order/{id}` over the **read** seam `private_read`, parsed by the shipped `reports.parse_order_status_report` (`:631`). Build the path from a module constant + templated id so `_ORDER_PATH_RE` (`readonly_guard:192,342`) does not fire on a literal — **prefer templating over growing an exemption**.

### 4. Operator clear tool — `breezy-clear-submit-intent`
Console script (runbook §8 names it; `scripts/venue/` holds probes, not operator tools): `pyproject.toml [project.scripts]` += `breezy-clear-submit-intent = "breezy.runtime.clear_submit_intent_cli:main"` (a SIXTH process, commented in the house style at `:230-256`). Contract: acquires the SAME exclusive flock via `open_submit_intent_latch` — **if the node holds it, refuse (exit 2)**, the two can never both act; requires the operator ack env var (no default) AND `--yes`; requires `--resolution {order-id=<id>|no-order-exists}` with `--evidence <path>` to a positions + fill-record artefact (**open-orders emptiness is never proof** — a filled IOC is not an open order); prints the OPEN intent (`intent_id`, `fingerprint`, `created_ns`, state) BEFORE clearing, never headers or signature; then `retire(intent_id, RetirementReason.OPERATOR_CLEARED, now_ns=)` (`submit_intent.py:78`). Exit 0 cleared / 2 refused / 3 nothing OPEN. Never called from the trading process, never on a timer, never at startup.

### 5. Barriers — every row, `file:line`, OLD → NEW, non-vacuity
| barrier | file:line | OLD → NEW | non-vacuity |
|---|---|---|---|
| E0-NOSEND callees | `test_execution_egress_firewall_guard.py:1707-1723` | 9 entries → **10**: `+ "self._dispatch_submit"`. Register `_dispatch_submit` as an order coroutine with its OWN exact allowlist constant `EXEC_SUBMIT_DISPATCH_PERMITTED_CALLEES` (permit/ledger/latch/sender/generate_* only) | plant `asyncio.create_task`, `self.create_task`, `threading.Thread(...).start()` in EACH coroutine → each must fire in both |
| B6 | `readonly_guard.py:609` (`assert_live_order_submission_permitted`) | 0 callers → **exactly 1** at `src/breezy/adapters/polymarket_us/exec/client.py::_dispatch_submit` | remove → RED; add a second anywhere under `src`+`scripts` → RED |
| B7 | `readonly_guard.py:610` (`issue_live_trading_permit`) | 0 callers → **exactly 1** at `src/breezy/runtime/trade_cli.py::main` | same, both directions |
| B9 (new) | `readonly_guard.py:607-612` `BARRED_CALLEES` | 3 keys → **5**: `+ "post_order":"B9"`, `+ "clear_submit_intent":"B10"`; key-set pin `:1497-1498`; cage `RulePin(attr='BARRED_CALLEES')` `test_cage_rule_constants_are_pinned.py:176-188` re-choose widened/narrowed | `post_order` pinned to exactly one caller (`exec/client.py::_dispatch_submit`); `clear_submit_intent` scanned **REPO-WIDE** (`REPO_WIDE_SCAN_ROOTS`, `:139`) pinned to exactly one caller, its own `main` — a conftest calling it must go RED |
| D3 | `readonly_guard.py:611` `_build_post_only_callable` | **UNCHANGED, exactly 1** (`write_transport.PolymarketUSWriteTransport.__init__`) | new RED: `post_order`'s AST body references it zero times; planting a second construction → RED |
| B4 | `readonly_guard.py:240-246` | **UNCHANGED, 2 members** — `exec/client.py` must NOT be exempted | `'/v1/orders'`, `'POST'`, `.post` literals live ONLY in `write_transport.py` (`ORDERS_PATH`); a planted literal in `exec/client.py` → V1/V2/V3 fire |
| cage count | `test_cage_rule_constants_are_pinned.py:864-873` | **UNCHANGED `== 3`** | assert explicitly as a non-change; R-7 adds no exemption |
| `_EGRESS_MODULE_BASENAMES` | `egress_firewall_guard.py:175-185` | **UNCHANGED** (`exec/client.py` already covered) | — |
| B8 (new) | `readonly_guard.py` | new: no `src/`+`scripts/` module may import `nautilus_trader.live.retry`, reference `RetryManager`/`RetryManagerPool`, import/subclass `nautilus_trader.adapters.polymarket*`, or `importlib.import_module` a dotted literal containing `live.retry`; no `retry_*` kwarg on the submit path | plant each of the four forms → each fires |
| C-10 zero-ref pins | new | `submit_intent` / `operator_controls` exact-set reference pins: **zero → exactly the R-7 call sites** | add a second importer → RED |

### 6. RED tests (all fail today)
1. `test_a_submit_with_a_granted_authorization_dispatches_and_generates_order_submitted` (the §A exit criterion)
2. `test_the_chain_denies_when_the_enablement_control_is_absent`
3. `test_the_chain_denies_when_either_operator_cap_is_absent` (parametrised over both, identical refusal)
4. `test_the_chain_denies_when_the_daily_ledger_is_exhausted_and_issues_no_post`
5. `test_a_latch_left_open_by_a_prior_crash_refuses_every_submit_until_cleared`
6. `test_no_post_is_reachable_while_the_write_canonical_string_is_unverified` — **structural**: the only way any test reaches the POST is `monkeypatch.setattr(write_transport, "WRITE_CANONICAL_STRING_VERIFIED", True)`; a repo-wide scan asserts exactly one such monkeypatch fixture and that no other test constructs a sender
7. `test_a_second_arm_within_one_process_is_refused_and_issues_no_post`
8. `test_a_4xx_with_a_status_body_and_no_order_id_retires_and_releases_the_booking`
9. `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking` (parametrised: 5xx / transport error / `CancelledError` / 200-with-id-no-executions / 4xx-with-id)
10. `test_a_raising_state_store_before_the_post_means_no_post_occurs`
11. `test_reconcile_at_startup_runs_before_the_first_arm` (contract test; unset flag → deny)
12. `test_a_non_ioc_or_non_buy_or_multi_contract_order_is_refused_before_any_body_is_built` (parametrised over the §2 refusal list)
13. `test_the_order_body_matches_the_venue_schema_exactly` (exact-key set vs the docs snapshot; price a decimal string, quantity a number)
14. `test_a_fill_report_is_never_built_without_a_venue_order_id`
15. `test_the_commission_booked_is_the_measured_venue_number_not_the_modelled_fee`
16. `test_clear_submit_intent_refuses_while_the_node_holds_the_lock` / `..._refuses_without_yes_and_the_operator_ack` / `..._prints_the_open_intent_before_clearing`
17. `test_b6_b7_b8_b9_d3_non_vacuity` (one module per barrier row in §5)

### 7. File plan (size budgets)
- CHANGE `exec/client.py` (1535 → ≤1750): `_submit_order` body, new `_dispatch_submit` (≤120), `_build_order_body` (≤90), outcome classifier (≤70), `_connect` reconcile hook, `generate_order_status_report`.
- CHANGE `write_transport.py` (174 → ≤230): `ORDERS_PATH`, `post_order(base_url, *, headers, body: bytes) -> VenueResponse`.
- CHANGE `factories.py`: inject `order_sender`, `write_canonical_verified`, `permit`, ledger, latch into `PolymarketUSExecClientConfig`/`create`; **decline to inject the sender while the flag is False** (belt; D2 is braces).
- CHANGE `runtime/trade_cli.py` (B7 one caller), `runtime/node_config.py` (config fields).
- CREATE `src/breezy/runtime/clear_submit_intent_cli.py` (≤220). CHANGE `pyproject.toml:230-256`.
- CREATE `tests/unit/test_polymarket_us_submit_order_chain.py` (≤700), `tests/unit/test_clear_submit_intent_cli.py` (≤300). CHANGE the 3 barrier modules.

### 8. Least-confident decisions (odds it survives review/venue)
1. **`synchronousExecution=true, maxBlockTime="5"`** — required for `executions`, but OQ-4 is unmeasured and it blocks the venue call on the loop thread. **0.6.** If it 400s, every send is AMBIGUOUS and R-8 needs a clear-tool run per order.
2. **`outcomeSide`+`action` over `intent`** — docs say `outcomeSide` wins if both set; sending one form is safer, but the NO leg's slug↔side derivation is untested. **0.7.**
3. **AMBIGUOUS does not release the booking** — conservative (spend stands) but permanently consumes budget on a transport blip. **0.75.**
4. **Clear tool as a console script rather than `scripts/venue/`** — matches the runbook's named artefact and gets `src/` barrier coverage; a reviewer may prefer the probe directory. **0.7.**
5. **D2 as an injected predicate rather than an import** — the only shape satisfying "injection never import" AND "monkeypatch is the sole route to the POST". **0.8.**
6. **B6 caller is `_dispatch_submit`, not `_submit_order`** — EXEC_SPINE §R-7 pins the path `exec/client.py::_submit_order`; splitting keeps the E0 callee allowlist minimal but changes the pinned path string. **0.55 — flag for review.**

## Converged peer review (2026-09-04) — BINDING over the draft above

Reviewers: trading-bot-architect (BLOCK, 5), security-reviewer (APPROVE-WITH-AMENDMENTS, 6 + D2 spec), python-reviewer (ACCEPT-WITH-AMENDMENTS, 13-row verification table). Coordinator decisions:

1. **Cites.** "readonly_guard.py" and "egress_firewall_guard.py" are NOT source files: every §5 constant lives in `tests/unit/test_polymarket_us_readonly_guard.py` and `tests/unit/test_execution_egress_firewall_guard.py` (line numbers as cited are exact). D3's chokepoint is `safety.py:668` (`assert_live_order_submission_permitted`); `safety.py:569` is `issue_live_trading_permit`. `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` has **8** entries today (8 → 9). `ORDER_LIFECYCLE_COROUTINES` (`:1682-1690`) must ALSO be widened or the new pin never applies. B6/B7 `RulePin` is `module="readonly"` at `test_cage_rule_constants_are_pinned.py:177`.
2. **Chokepoint path stays `exec/client.py::_submit_order`** (the peer-converged pin in EXEC_SPINE_NEXT §A). No `_dispatch_submit` coroutine. Pure helpers (body builder, outcome classifier, refusal predicates — no I/O, no awaits) move to a NEW `src/breezy/adapters/polymarket_us/exec/submit_chain.py` so `client.py` (already 1535 lines against an 800 ceiling) does not grow; add `submit_chain.py` to `_EGRESS_MODULE_BASENAMES` as a RED before the split (basename absent → scan silent). `_submit_order`'s allowlist is ENUMERATED, not described: `assert_live_order_submission_permitted`, `self._ledger.authorize_order_cost`, `self._ledger.release_booking`, `self._ledger.true_up_booking`, `self._latch.arm`, `self._latch.retire`, `self._order_sender.post_order`, the D2 read, `self.generate_order_submitted`, `self.generate_order_rejected`, `self.generate_order_filled`, `self.generate_order_denied`, `self._log.*`, `self._cache.account_for_venue`, `self._clock.timestamp_ns`, and the pure `submit_chain.*` helpers. Anything else → RED.
3. **B9 is its own one-caller pin, never `BARRED_CALLEES`** (that dict asserts ZERO callers; adding `post_order` there makes R-7 uncallable). New scanner: ungated (NOT via `is_venue_touching`), over `REPO_WIDE_SCAN_ROOTS` = src+scripts+tests, pinning `post_order` → exactly `exec/client.py::_submit_order` and `clear_submit_intent` → exactly its own `main`; non-vacuity: plant a second caller in a `tests/` conftest AND in a plain `src/` module with no venue literal — both RED.
4. **Retirement reasons are the real enum** (`submit_intent.py:73-78`): `DEFINITIVE_REJECT`, `ACCEPTED_WITH_DURABLE_FILL`, `ACCEPTED_ZERO_FILL_TERMINAL`, `STARTUP_FILL_RECORD_MATCH`, `OPERATOR_CLEARED`. "DEFINITIVE_ACCEPT" does not exist.
5. **Outcome taxonomy corrected (BLOCKER).** A synchronous IOC is terminal at response time. `200 + id + executions==[]` is **ACCEPTED_ZERO_FILL_TERMINAL** — but ONLY when the response body also carries an explicit terminal order state (`status` ∈ the venue's terminal set for IOC, cite the snapshot enum) AND `cumQuantity == 0`; then `true_up_booking(filled_cost_usd=0)` → `retire(ACCEPTED_ZERO_FILL_TERMINAL)` → `generate_order_submitted` + `generate_order_rejected`/canceled per Nautilus semantics for an unfilled IOC (builder cites `client.pyx`). `200 + id + no executions + NON-terminal or absent status` stays AMBIGUOUS. AMBIGUOUS (5xx, transport error, `CancelledError`, unparseable body, 4xx-with-id) keeps the latch OPEN and the booking held; exit is the clear tool. Rationale: the bid side is empty (median 0.3 contracts), so IOC misses are the COMMON path — an AMBIGUOUS-by-default rule would drain the daily budget and demand a clear-tool run per miss.
6. **D2 unforgeability.** Preferred: NO injection — `_submit_order` reads `write_transport.WRITE_CANONICAL_STRING_VERIFIED` as a bare module-attribute lookup at call time (`import ... write_transport` at module scope, never `from ... import`). The builder FIRST verifies with a planted-import RED probe that importing `write_transport` inside `exec/client.py` trips no E0-TRANSPORT/B4/basename barrier; if it does, fall back to injection PLUS a cage `RulePin` asserting exactly one construction site passes `write_canonical_verified=` and its AST is exactly `lambda: write_transport.WRITE_CANONICAL_STRING_VERIFIED`. Either way the factory declines to inject the sender while the flag is False (belt) and test 6's repo-wide "one monkeypatch fixture only" scan stays.
7. **Order attributes.** `is_post_only`, `is_reduce_only` (`model/orders/base.pyx:206-207`); gate on `order.has_trigger_price`; `expire_time` property exists. Slug: `instrument.raw_symbol` is what `_assert_market_matches` (`reports.py:472`) compares; `info["slug"]` carries the same value (`parsing.py:1309,1325`) — send `marketSlug` from `raw_symbol`.
8. **Enablement cadence (clarification, not a change).** Enablement is read once by `issue_live_trading_permit` (B7, `trade_cli.py::main`); only the two dollar caps are re-read per order (`operator_controls.py:328-331`). Do not describe D5 as re-checking enablement.
9. **B8** adds `__import__` (constant or built) and `getattr(nautilus_trader, "live")` chains; concatenation-built dotted strings are an ACCEPTED residual (same limit as B5) and are named as such.
10. **RED test 18:** caplog test (precedent `test_polymarket_us_secret_exposure.py:141`) that the AMBIGUOUS refusal log line and the clear tool's pre-clear print contain no header, signature, or nonce fragment.
11. **Async.** `HttpClient.post` is `async def`; `synchronousExecution`/`maxBlockTime="5"` blocks venue-side while this coroutine awaits — no loop or thread block. Per-client submission stall of ≤5 s is accepted.
12. **Residual goal-state gap 6** (startup clock-skew / signer-window assertion) is NOT closed by R-7 and is recorded as open in EXEC_SPINE_NEXT.

Build routing: Grok (default for building), read-only fallback to tdd-guide only on a hard Grok failure. Verification is unconditional: diff read, gate re-run, barrier OLD→NEW table re-derived by Claude reviewers before cherry-pick.
13. **D6 amended (from the runtime-wiring review, binding):** `self._latch` is INJECTED at construction via a new `PolymarketUSExecClientConfig.submit_intent_latch: SubmitIntentLatch | None`, populated once by the composition root's single `open_submit_intent_latch` call before `node.build()`; the exec client never opens the latch itself. `_connect` calls `self._latch.reconcile_at_startup(has_durable_fill_record=…, now_ns=…)` on the injected instance before setting `self._intent_reconciled`. With the field unset the send chain denies at D6 (RED). See `docs/plans/CRH_RUNTIME_WIRING_BRIEF_2026-09-04.md` converged item 2.
