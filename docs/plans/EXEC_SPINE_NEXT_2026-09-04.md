# EXEC SPINE — remaining sequence and the R-6.5b build brief (2026-09-04)

Distilled by code-architect from Rev 7 (`EXEC_SPINE_R65_R7_2026-09-02.md`) and the parent
plan (`EXEC_SPINE_2026-09-01.md`), verified against code at `cf0188f`. Operator
instruction 2026-09-04: continue toward the live-small stop gate; only
`BREEZY_TRADING_ENABLED`, the two budget values, and the R-6.5P positive-control order
stay operator-only. **Status: DRAFT — under peer review (architect, python-reviewer,
security-reviewer).**

Verified state: `write_transport.py` does not exist; `B4_EXEMPT_PATHS` has one member
(`test_polymarket_us_readonly_guard.py:240-242`); `CAGE_EXEMPTIONS` len pinned `== 2`
(`test_cage_rule_constants_are_pinned.py:863`); `submit_intent` and
`operator_controls`/`DailySpendLedger` have zero references in `src/`+`scripts/`;
`_submit_order` ends at `_STANDING_ORDER_REFUSAL` (`exec/client.py:1399`);
`DepthAwareTradeCost` (`strategy/weather_common/costs.py:228-253`) has no fixed-cost
term; `settlement/` has no `exit_actor.py`.

## A. Remaining increments

| id | what | files | plan § | depends on | operator-only | exit criterion |
|---|---|---|---|---|---|---|
| OP-1 | Operator rests BUY 1 @ $0.01 far below best ask; confirms resting in venue UI | none | Rev7 §1 D1 | — | YES | visible in UI |
| OP-2 | `scripts/venue/polymarket_us_write_signing_probe.py --positive-control` (`:665-671`) | none | Rev7 §1 D1 | OP-1 | YES | reason `PREFLIGHT_NOT_EMPTY` (`:171`,`:522`); `PREFLIGHT_NOT_200` = re-run; `OQB_NO` (`:177`) = OQ-B answered NO |
| OP-3 | Operator cancels the resting BUY; failed cancel is a stop, not a retry | none | Rev7 §6 | OP-2 | YES | unfiltered open-orders empty |
| OP-4 | Real probe run on the proven-flat account | none | Rev7 §1 | OP-3 | YES | artefact records the POST's HTTP status → OQ-D closed (the plan's `AUTH_OK` token does not exist in the shipped probe, C-6) |
| R-6.5b | shipped write transport: `write_transport.py`, `PERMITTED_WRITE_METHODS={"POST"}`, `post_cancel_all`, B4 exemption as a NARROWING | §B | Rev7 §3 | OP-4 (OQ-D) — see review question Q1 | no | §B |
| R-7 | `_submit_order` gets a body: authorization first positional + isinstance guard; both caps re-read per call; ledger release only on 4xx+`google.rpc.Status`+no `order.id`; latch arm→POST→retire; standing refusal removed only here; B8 built | `exec/client.py`, `runtime/trade_cli.py`, `runtime/node_config.py`, 4 barrier test modules | Rev7 §4 | R-6.5b, R-6.5a (`4f76137`) | no | `test_a_submit_with_a_granted_authorization_dispatches_and_generates_order_submitted` green and the passed count never drops |
| R-7-FILL | `generate_fill_reports` stays `[]` until the ORDER surface is read (`Execution.order/lastPx/lastShares/tradeId`); an activities `Trade` may be R-8 evidence, never a `FillReport` | `exec/client.py:887-899`, `exec/reports.py` | Rev7 §7 | OQ-B; deferrable behind the `[]`-with-reason refusal | no | `test_a_fill_report_is_never_built_without_a_venue_order_id` + non-vacuity |
| R-8-PRE-1 | fixed-per-order cost term in `DepthAwareTradeCost`/`trade_cost_prob` (stack cannot express a floor today) | `costs.py`, `fees.py` | parent §R-8 | none — buildable today | no | `test_a_fee_floor_survives_a_one_contract_order` |
| R-8-PRE-2 | measure OQ-8 (venue minimum taker fee) from the docs snapshot; preview WITHDRAWN (OQ-3 unproven) | `docs/evidence/` | parent OQ-8; Rev7 §4 D2 | R-8-PRE-1 | no | a recorded `notional + max(pct, min)` bound; unbounded ⇒ R-8 does not run |
| R-8 | first real order: 1 contract, marketable, IOC; store `avgPx`+`cumQuantity` | — | parent §R-8 | R-7, R-8-PRE-2 | YES: live-trading enablement plus the two operator-reserved caps (max daily budget, max per position), exported in the operator's shell only | goal-state clauses 1–6 |
| R-9-PRE | guards: (a) `r_i = pnl/(avg_px_open*qty*mult)` divides by zero for an unpriced forward — guard + exclude from the BCa sample; (b) settlement-as-exit via `_send_order_status_report` bypasses `_submit_order`'s refusal latch — R-9 consults `trading_refusals` itself, never closes an unattributable position | `settlement/`, new `settlement/exit_actor.py` | parent §R-4 amendments; PROGRESS "Guard before R-9" | none — buildable today (parent §R-9 tests 1, 2, 10) | no | R-9 tests 1+10 green; `tests/contract/test_reconciliation_settlement_price_hazard.py:535` `xfail(strict)` flips to pass when R-9 lands |
| R-9 | `SettlementExitActor`, NWS-keyed 1.00/0.00, `external_order_claims`, BCa estimator | `settlement/exit_actor.py` | parent §R-9 | R-8 (a real fill) | no | all ten §R-9 REDs green; OQ-9 blocks done, not build |

OQ-B ordering: only R-7-FILL and the order-status surface need OQ-B. R-6.5b and R-7
proceed with OQ-B open because R-7 lands the path DENYING (B7 stays at zero callers) and
the fill/status reports keep returning `[]` with their stated reason.

## B. Build brief — R-6.5b (hand verbatim to the implementer)

**Role.** Land the shipped, signed POST transport for Polymarket.us as a small, write-only,
file-exact-exempted module, extending Nautilus only through `nautilus_pyo3.HttpClient`;
Nautilus Trader is immutable. RED tests first; gate `scripts/ci/run_tests_no_egress.sh`.

**Preconditions.** (1) OQ-D — see review question Q1 below. (2) The M_B verdict gate in
`docs/core/PROGRESS.md` is LIFTED by the operator (2026-09-04).

**Files.** CREATE `src/breezy/adapters/polymarket_us/write_transport.py` (NOT under
`exec/` — Rev 7 §1 D4 governs; the parent §R-5 location is stale, C-7) and
`tests/unit/test_polymarket_us_write_transport.py`. CHANGE
`src/breezy/adapters/polymarket_us/factories.py` (the one and only importer),
`tests/unit/test_polymarket_us_readonly_guard.py`,
`tests/unit/test_cage_rule_constants_are_pinned.py`,
`tests/unit/test_execution_egress_firewall_guard.py`. Nothing else.

**Decisions already made.**
- D1 shared client: INJECTED, never re-minted. `build_shared_http_client` at
  `transport.py:317-393` (exported `:65`, consumed `factories.py:461-480`). A second client
  halves the `Quota`. Keyword-only constructor argument.
- Dispatch spelling (measured): `client.post(url, headers=signed, keys=[QUOTA_KEY_PORTFOLIO])`.
  No `params`, no `body`, no per-call timeout. Rejected: `client.request(HttpMethod.POST, …)`;
  `nautilus_pyo3.http_post` (trips V5, cannot share the bucket).
- B3 wrap-don't-store: mirror `_build_get_only_callable` (`transport.py:131-148`) — closure
  over the client on a `__slots__ = ()` object; never an attribute.
- B3-M: no module-level holder of an `HttpClient` (`B3M_HTTP_CLIENT_CTOR_NAMES`,
  `readonly_guard:159`).
- V1+V2+V3 scope: `'POST'`, `'/v1/orders/open/cancel'`, `.post` all INSIDE the exempted
  file. `PERMITTED_WRITE_METHODS = frozenset({"POST"})` lives in `write_transport.py`;
  `signing.py` and `PERMITTED_METHODS` untouched. The write signer reuses
  `Ed25519RequestSigner.sign_headers`' gate so read refuses POST and write refuses GET
  (`MethodNotPermittedError`).
- Importer pin is a COPY: `find_probe_importers` (`readonly_guard:882-924`) hardcodes
  `_PROBE_MODULE_NAME` (`:875`); copy its four forms with the new token; roots
  `("src","scripts")` plus `tests` for the `BARRED_CALLEES` half; exactly one importer,
  `factories.py`; no `__all__` re-export, no module-level alias, no `import *`.
- Public dispatch is `post_cancel_all` (never `cancel_order`/`_cancel_all_orders`,
  which are `ORDER_LIFECYCLE_COROUTINES`, `egress_firewall_guard:1677-1685`).

**RED tests (each must fail today).**
1. `test_the_write_callable_has_no_method_query_or_body_parameter`
2. `test_it_issues_exactly_one_post_to_the_one_pinned_path` (non-vacuity vs a widened allowlist)
3. `test_write_transport_references_exactly_the_permitted_pyo3_members` — `{HttpError, HttpTimeoutError}` (+`HttpClient` iff annotated); planted `SocketClient`/`WebSocketClient`/foreign exec config each fire
4. `test_build_post_only_callable_has_exactly_one_caller` — remove → red; second caller incl. under `tests/` → red
5. `test_write_transport_has_exactly_one_importer_and_it_does_not_re_export`
6. `test_the_write_signer_refuses_get_and_the_read_signer_refuses_post`
7. `test_b3_the_constructed_write_transport_exposes_no_write_capable_receiver` — `find_write_capable_receiver_exposures(...) == []`; storing `_client` → red
8. `test_b4_raw_non_vacuity_both_directions`

**Barrier tests to WIDEN (never relax, L-12).**
- `readonly_guard:240` `B4_EXEMPT_PATHS` += `src/breezy/adapters/polymarket_us/write_transport.py` (paid for by RED 8).
- `readonly_guard:825` `_WRITE_SIGNING_PROBE_PATH = next(iter(B4_EXEMPT_PATHS))` → explicit literal (C-2: with two members this re-points three tests at an arbitrary file).
- `readonly_guard:604-609` `BARRED_CALLEES` += `"_build_post_only_callable": "D3"`; key-set pin `:1497-1498`; one-caller exact-set pin.
- `cage_rule_constants:855,863` `two`/`== 2` → `three`/`== 3`, rename the function; register new constants in `CAGE_RULE_PINS` (`:821`). `CAGE_EXEMPTIONS` is derived (`:733`), not hand-edited (C-3).
- `egress_firewall_guard:175-185` `_EGRESS_MODULE_BASENAMES` += `write_transport.py` (a ban-list widening); exactly one E1 row in `test_n2_…` (`:688`) after `factories.py`'s E2 row. No E0, E2, E3.

**Invariants.** Nautilus immutable. `allow_short` False. `PERMITTED_METHODS ==
frozenset({"GET"})`. `signing.py` untouched. `transport.py` never write-capable, never in
`B4_EXEMPT_PATHS`. `PolymarketUSReadTransport` protocol method-free. Nothing under `exec/**`
changes. Never weaken a safety/settlement/contract test. Never assign an operator-reserved
control. Ships write-capable with ZERO send call sites: `factories.py` constructs it;
nothing dispatches through it until R-7.

**Exit.** Gate green; passed count rises by exactly the new test count and never drops;
RED→GREEN output for all eight tests kept; `scan_write_egress()` `[]` with the exemption
and non-empty without it.

## C. Plan-vs-code contradictions (resolve in review)

1. [BLOCKING → LIFTED 09-04] PROGRESS verdict gate ("no R-6.5b/R-7 until M_B survives") vs Rev 7 §5 (R-6.5b blocked on OQ-B only). Operator lifted the M_B gate; OQ-D remains.
2. [HIGH] `_WRITE_SIGNING_PROBE_PATH = next(iter(B4_EXEMPT_PATHS))` (`readonly_guard:825`) breaks silently at two members.
3. [MEDIUM] `CAGE_EXEMPTIONS` is derived (`cage_rule_constants:733`); only the `len` assertion and name change.
4. [MEDIUM] Rev 7 §3 D1 mislocates the client factory: it landed in `transport.py:317-393`, not `factories.py`; `assert_clean_proxy_env` `:359`, UA check `:362` — §6's least-confident item discharged.
5. [MEDIUM] Rev 7 §3 D2 asserts a per-module pyo3 member pin for `transport.py` that does not exist.
6. [MEDIUM] `AUTH_OK` is Rev-3 lexicon; the shipped probe emits `PREFLIGHT_NOT_200 / PREFLIGHT_NOT_EMPTY / POSTFLIGHT_* / OQB_NO / INTERRUPTED` (`:170-182`). R-6.5b's precondition is the recorded POST status.
7. [MEDIUM] Parent §R-5 puts the transport under `exec/`; Rev 7 §1 D4 puts it outside so E0-INERT (pyo3 import ban inside `exec/`) is not engaged. Rev 7 governs.
8. [LOW] Parent "B9" and Rev 7's `BARRED_CALLEES` row are one control under two names.
9. [LOW] §7 addendum (`FillReport` needs the order surface) vs Rev 7 §4 D2 (ledger true-up on a durable fill record): at R-8's n=1 the record can come from `CreateOrderResponse.executions` (`sdk_snapshot/.../types/orders.py:129-133`, `total=False`). State it.
10. [LOW] Nothing pins `submit_intent`'s zero production references; R-7 adds the exact-set pin when it converts.

## Review questions (peer review must answer)

- **Q1.** May R-6.5b be BUILT with OQ-D open, pinning the write canonical-string assumption
  as a single named constant whose acceptance the operator's probe later confirms, given
  the module ships with zero send call sites? Or does an unverified premise in shipped code
  violate L-1/L-11 regardless of reachability?
- **Q2.** Is Rev 7 §1 D4's placement OUTSIDE `exec/` still right given
  `_EGRESS_MODULE_BASENAMES` and the E1 row — i.e. is a write-capable module outside the
  `exec/` prefix a bypass risk the security audit named?
- **Q3.** For R-7: with no venue idempotency key on retail create-order
  (`DOCS_RECHECK_2026-09-03.md`), is the latch arm→POST→retire ordering plus
  `inflight_check_interval_ms=0` sufficient against a double send across a process crash?
- **Q4.** Are R-8-PRE-1 and R-9-PRE truly independent of OQ-D so they may land now?

---

## D. Peer review 2026-09-04 — CONVERGED for R-6.5b (architect, python-reviewer, security-reviewer: all ACCEPT-WITH-AMENDMENTS)

**Q1 — build with OQ-D open: YES.** The write canonical string is already shipped and
B4-exempted in the probe (`scripts/venue/polymarket_us_write_signing_probe.py:351-376`,
`_sign_write_headers`); R-6.5b duplicates a shipped premise, adds none. Conditions:
(i) `WRITE_CANONICAL_STRING_VERIFIED: Final[bool] = False` in `write_transport.py`, pinned
`False` by `test_write_canonical_string_verified_is_false_until_op4`; R-7 refuses to wire a
call site while it is `False` (its own RED gate, flipped only with the OP-4 artefact path);
(ii) RED 9 `test_the_shipped_write_signer_and_the_probe_produce_the_same_canonical_string`
— identical signature bytes over one injected timestamp and path, so OQ-D's measurement on
the probe's copy covers the shipped copy.

**Q2 — outside `exec/`: YES.** Covered by C1 (`readonly_guard:300`), C6 (`:317-321`), B4,
one voluntary E1 row. Import graph is BINDING: `factories.py → write_transport.py →
{nautilus_pyo3, signing, transport.QUOTA_KEY_PORTFOLIO}`; `exec/client.py` NEVER imports
`write_transport` — R-7 receives the built closure as a constructor argument from
`PolymarketUSLiveExecClientFactory.create` (injection, never import). The real bypass is
that `scan_write_egress` skips an exempted path entirely (`:397-402`): hence RED 8 is
replaced by an EXACT-SET content test (amendment 3).

**Q3 — double send across a crash:** the latch (`submit_intent.py:335-363,385-421`) prevents
it; recovery routes through `has_durable_fill_record`, which nothing supplies, so a crash
leaves the latch OPEN and every submit refuses account-wide until the operator clear tool —
fail-closed and correct at n=1; the plan states it. R-7 exit criterion gains: trade node
startup calls `latch.reconcile_at_startup(...)` before the first `arm`, with a contract test.
`inflight_check_interval_ms=0` contributes nothing here.

**Q4 — R-8-PRE-1 / R-9-PRE independent: YES.** R-8-PRE-1 reduced to pins (`3b669d5`;
OQ-8: no minimum fee, `OQ8_MINIMUM_FEE_2026-09-04.md`). R-9-PRE landed `b418424`.

**Amendments applied to §B (the implementer brief in `docs/plans/R65B_BUILD_BRIEF_2026-09-04.md` is authoritative):**
1. Write signer = SIBLING of `Ed25519RequestSigner` mirroring `_sign_write_headers`; `signing.py` and `PERMITTED_METHODS` untouched. (python-reviewer's injectable-`permitted_methods` alternative REJECTED: it adds a knob to a pinned security boundary.)
2. RED 9 (probe/shipped equality). 3. RED 8 → `test_b4_raw_content_is_exactly_the_three_expected_violations` (exact set `[(V1,'POST'),(V2,'/v1/orders/open/cancel'),(V3,'.post')]` + two-direction non-vacuity). RED 3 needs a NET-NEW AST helper enumerating `nautilus_pyo3.X` references (none exists).
4. Cage row: only `len == 2 → 3` + rename; edit the EXISTING `RulePin(attr='B4_EXEMPT_PATHS')` (`:509-525`, re-choose `widened`) and `RulePin(attr='BARRED_CALLEES')` (`:176-188`); no new constant registered.
5. `_build_post_only_callable`'s ONE caller is `write_transport.py` itself (mirroring `transport.py:451`), not `factories.py`; `tests/` needs its own `find_barred_callers` sweep.
6. `factories.py` obtains the singleton via one `_shared_polymarket_us_client(config)` helper both wrappers call (`factories.py:466-479`; divergence is a startup `ValueError`, `transport.py:299-314,374-377`).
7. `GET /v1/order/{id}` EXISTS (`sdk_snapshot/.../resources/orders.py:42,106`); the native-inflight decline rests on the REJECTED-guess reason alone; fix the comment beside `inflight_check_interval_ms=0`.
8. New row **R-7-STATUS**: by-id order read on the READ seam, NOT gated on OQ-B; `/v1/order/` fires V2 (`_ORDER_PATH_RE`, `readonly_guard:192,342`) — take a narrowing exemption with two-direction non-vacuity, or template the path. Blocks R-8.
9. C-2 is BLOCKING for R-6.5b: replace `next(iter(B4_EXEMPT_PATHS))` with the literal probe path plus `assert _WRITE_SIGNING_PROBE_PATH in B4_EXEMPT_PATHS`.
10. C-6: OQ-D is CLOSED-YES iff the probe's `write_status` is 200 or a non-401/403 carrying a `CancelAllOrdersResponse`-shaped body; 401/403 is CLOSED-NO and `WRITE_CANONICAL_STRING_VERIFIED` stays `False`.
11. C-9: a durable fill record MAY come from `CreateOrderResponse.executions[*].order.id/lastPx/lastShares` (`total=False`, absence expected, L-17); missing any → not durable, latch stays OPEN. Never synthesise a `FillReport`.
12. C-10: R-7 adds exact-set zero-reference pins for `submit_intent` AND `operator_controls`/`DailySpendLedger`.
13. `post_cancel_all` is a coroutine; outside `exec/` it engages no async-lifecycle pin (mirrors `transport.py:144`).

**Goal-state gaps (L-3) — new rows/notes, all before R-8:** (1) R-7-STATUS (above); (2) crash-restart: only exit is the operator clear tool — name its artefact in the runbook; (3) IOC leaves no resting remainder, so no cancel path is required for R-8 — state it, `post_cancel_all` stays zero-call-site; (4) T-9: hold-to-settlement (1.00/0.00) is the ACCEPTED exit; `HALTED` halts entries only via the strategy pre-check, never a flatten; (5) private WebSocket fills deferred behind by-id polling at n=1; (6) one startup clock-skew assertion against the venue (signer window); (7) `docs/plans/R8_OPERATOR_RUNBOOK.md` (OP-1..OP-4, three env vars, clear tool) is an R-8 precondition; (8) the realized-PnL row's owner is Nautilus `Position.realized_pnl` at settlement close (R-9), never `activities.trade.realizedPnl`.

Residual gap (security, MEDIUM): a dynamically computed import string is invisible to
AST pins and caught only by B3's runtime scan plus review — documented, not closed.
