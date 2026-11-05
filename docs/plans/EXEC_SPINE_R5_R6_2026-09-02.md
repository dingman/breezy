# EXEC SPINE — R-5 / R-6 increment plan (2026-09-02)

**Status:** PLAN ARTIFACT, **REVISION 4 (2026-09-02)**. Revision 1 absorbed three blind peer
reviews (APPROVE WITH AMENDMENTS). Revision 2 absorbed a **live read-only venue capture** and a
**targeted containment re-review**. Revision 3 absorbs **the implementation and review of
increment W** — the first increment of this plan to be built, which found a systematic
under-enumeration of barriers across four increments and one native idiom the plan had not
anticipated. Revision 4 absorbs a **security review of Revision 3's containment reversal**
(ACCEPT WITH CONDITIONS): the reversal stands, but one justification for it was an accounting
fiction and is replaced by five restoring commitments (§3 R-6.5, D1-D5). Every finding was re-verified against source or against the
capture by the author before acceptance; two Revision-1 statements are corrected **against** the
author. Changes: §11 (Revision 4), §12 (Revision 3), §13 (Revision 2), §14 (Revision 1).

> **Two conditions gate this plan from outside engineering, and neither is a task.**
> **(1)** The venue's PRIVATE backend is DOWN (2026-09-02, deterministic over 5 attempts):
> balances 500/13, positions 503/14, orders-open 503/14. **Auth is PROVEN**, so this is
> availability, not access. **(2)** R-6.5P's flatness precondition is therefore currently
> **unsatisfiable**, and it now REFUSES TO RUN rather than assuming. Both clear themselves when
> the backend recovers; see §3 R-5R and R-6.5P.
**Parent:** `docs/plans/EXEC_SPINE_2026-09-01.md` (Revision 2). This document does **not**
supersede it. It re-plans §R-5 and §R-6 only, and it **re-sequences** them. Every other
section of the parent stands unchanged.
**Predecessor increment:** R-4 landed at `a331ef8` (`src/breezy/adapters/polymarket_us/exec/client.py`).
**Branch/base:** `feat/data-capture-and-risk` @ `be6858d`.

Every citation below is a `path:line` the author opened. Installed Nautilus is
`/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/` (1.231.0), abbreviated
`$NT` throughout. Recursive negatives use shell `grep -r` with a positive control in the same
command (standing constraint; L-11's tooling trap).

---

## 0. HEADLINE — the parent plan's R-5/R-6 split is no longer the right one, and R-5 is
## currently BLOCKED by the parent plan's own precondition

Three facts, each verified below, change the sequencing:

1. **R-4 is a library, not a spine segment. It has ZERO construction sites.**
   `grep -rn "PolymarketUSExecutionClient" src/ scripts/` returns exactly one hit outside its
   own module — a *docstring cross-reference* in `src/breezy/adapters/polymarket_us/fees.py:209`.
   `build_trade_node_config` still pins `exec_clients={}` (`src/breezy/runtime/node_config.py:654`),
   and no `LiveExecClientFactory` exists for this venue. **Nothing in the running process ever
   instantiates the R-4 client.** Therefore the parent plan's load-bearing claim — "R-4 publishes
   the first `AccountState` and therefore makes every cap live for the first time"
   (`EXEC_SPINE_2026-09-01.md:336`) — is **true of the class and false of the process**. Every
   Nautilus cap in the live trading node is still inert (`$NT/risk/engine.pyx:682-689`), and
   `build_trade_risk_engine_config`'s `max_notional_per_order` mapping
   (`node_config.py:544-546`) enforces nothing at runtime today.

2. **R-5's stated precondition is not met, so R-5 does not run.** The parent plan says
   OQ-6 "closes at R-1" and that **"R-5 is blocked until it is closed"**
   (`EXEC_SPINE_2026-09-01.md:454`, `:1033`). R-1's *code* landed (`e7ccfbd`,
   `scripts/venue/polymarket_us_shape_capture.py`), but its **"Done when: artifacts for all three
   paths exist"** did not: `find docs/evidence -name 'PRIVATE_*'` returns **nothing**, and the
   newest venue smoke artifact is `docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_2026-08-30T155317+0000.md`
   — dated **before** the auth resolution. The shape capture has never been run against the venue.
3. **R-5 as written is the only increment in the entire plan that creates a write-capable
   network surface under `src/`, and it would have to punch through the repo's strongest
   structural guarantee to do it.** E0-INERT
   (`tests/unit/test_execution_egress_firewall_guard.py:1514-1932`, live scan at `:1932`)
   asserts that **no module under `exec/` may import a network client** — `NETWORK_IMPORT_PREFIXES`
   (`:1537-1553`), plus `BANNED_EXEC_TRANSPORT_MODULES` (`:1612-1621`) and
   `BANNED_EXEC_TRANSPORT_NAMES` (`:1626-1634`), which names `NautilusHttpTransport` explicitly.
   The parent plan's security condition 5 puts `exec/write_transport.py` under exactly that path
   (`EXEC_SPINE_2026-09-01.md:464-472`), and **the parent plan never mentions that E0-INERT must
   be narrowed at all.** That omission is the single largest gap this plan found in the parent.

Conclusion, stated plainly because the brief asked for a judgement and not a hedge:

> **R-5-as-written should NOT be built next**, and its own precondition (OQ-6/OQ-B) is open, so
> by the parent plan's text it cannot run at all.
>
> **But the venue QUESTION should be asked now.** Revision 1 splits R-5 into **R-6.5P** — the
> signing probe as an evidence-only `scripts/venue/` script, covered by B4 (which already scopes
> an allowlist entry for it) and shipping nothing under `src/` — and **R-6.5**, the importable
> write transport, which stays adjacent to R-7 where its consumer is. Revision 0 rejected the
> early probe on a claim that was half wrong; see §3 R-6.5P.
>
> **Sequence (Revision 2): R-4P-1 → W → [R-5R-0, R-5R-3 now] → R-6a → R-6c → R-6d → R-6e →
> {R-5R-1, R-4P-2, R-6.5P — all gated on the venue} → R-7-PRE → R-6.5 → R-7.**
>
> **R-4P-1 goes first and is small:** a live capture found that R-4 as landed reconciles **page
> one** of its own positions and never inspects `eof` — a latent defect in committed code (risk
> 0). W follows, because R-4 is otherwise a library nothing constructs. The venue-gated set can
> be built but not *run*; the R-6* increments are pure local code and are unaffected by the
> outage, which is what makes them the right work to do while it persists.
>
> **And §6 concedes what Revision 0 concealed:** this walk's end state is one real order and one
> realized-PnL row — **not** the goal state. The strategy-origination workstream (S-1/S-2) is
> undecomposed anywhere in the repo, and this plan re-pins `strategies=[]` rather than closing it.
## 1. Null-hypothesis verdicts, up front

Three forms only, per L-11: `NATIVE CONFIRMED` · `NATIVE EXISTS, DECLINED BECAUSE <cost>` ·
`GENUINE GAP — verified absent (+ positive control)`.

| # | Capability the increment would build | Verdict | Citation actually opened |
|---|---|---|---|
| N1 | Register an exec client with the live node | **NATIVE CONFIRMED** | `TradingNodeConfig.exec_clients` + `LiveExecClientFactory`. Registration is `LiveNodeBuilder.add_exec_client_factory` (`$NT/live/node_builder.py:114`) and construction is `build_exec_clients` (`:201-246`). **Citation corrected in Revision 1:** Revision 0 cited `:163,177`, which is inside `build_data_clients` (`:143`) — the fact was right and the line was the data path's. Breezy's own precedent is `PolymarketUSLiveDataClientFactory` (`src/breezy/adapters/polymarket_us/factories.py`). **Configure + a factory; author no process machinery.** |
| N2 | A health/degraded surface for `trading_refusals` | **NATIVE CONFIRMED — AND UNWIRED** | `Component.degrade()` `$NT/common/component.pyx:2098`; FSM `RUNNING→DEGRADING` `:1638` and `DEGRADING→DEGRADED` `:1649`; `is_degraded` `:1857-1864`; `_trigger_fsm` publishes `ComponentStateChanged` on topic `events.system.<component_id>` `:2210-2225`. `ExecutionClient` is a `Component`. **Zero consumers**: `grep -rn "is_degraded\|\.degrade()"` across `$NT/live/ $NT/system/ $NT/execution/ $NT/trading/` → **0 files**; positive control, `client` → **23 files** in the same roots. So the mechanism exists, publishes an event, and nothing native reacts to it. **Use it. Do not build a Breezy health hook.** |
| N3 | Import `breezy.runtime.health` from the exec client | **BARRED — by Breezy's own barrier, not by Nautilus** | `BANNED_EXEC_TRANSPORT_MODULES` names `breezy.runtime.health` (`tests/unit/test_execution_egress_firewall_guard.py:1619`). N2's msgbus route needs no import and is therefore the only compliant path. |
| N4 | Per-instrument order refusal (narrowing R-4's node-global latch) | **GENUINE GAP — the nearest native cannot express "deny"** | `RiskEngine.set_max_notional_per_order` (`$NT/risk/engine.pyx:279`) is per-instrument and runtime-settable, **but** `Condition.positive(new_value)` at `:304` refuses `0`, and `None` *disables* the check; and the read site `if max_notional_setting:` (`$NT/risk/engine.pyx:677`) treats a falsy value as "no cap". So the only per-instrument native knob **cannot be set to deny — setting it to zero would be rejected, and if it were accepted it would REMOVE the cap.** |
| N5 | Node-global trading halt | **NATIVE EXISTS, DECLINED BECAUSE it is the wrong granularity for R-6** | `RiskEngine.set_trading_state` `$NT/risk/engine.pyx:228`; `TradingState.HALTED` denies at `:559` and `:1137-1147`. It is node-global — exactly the property R-6 exists to narrow — and it denies *upstream* of the exec client, so the client's own refusal reasons never reach the denial message. Keep it as the belt-and-braces the parent plan already names (`EXEC_SPINE_2026-09-01.md:202-205`); do not make it the per-instrument mechanism. |
| N6 | Long-only / naked-short guard, live | **NATIVE ABSENT, BREEZY CODE ALREADY EXISTS — reuse, do not author** | `src/breezy/runtime/backtest_order_guard.py:113 BacktestOrderGuard.__init__(portfolio, cache)`, `:154 _refuse_naked_short`, `:214 install_order_guard(engine)`, `:221 msgbus.subscribe(topic=ORDER_EVENT_TOPIC, ...)`. `grep -c "POLYMARKET\|polymarket_us"` on that module → **0**. Only the *installer* is backtest-typed. Live installer = `BacktestOrderGuard(portfolio, cache)` + one `msgbus.subscribe`. **Parent plan's verdict CONFIRMED as still true.** |
| N7 | Operator-reserved control arrival mechanism | **NATIVE ABSENT, BREEZY MECHANISM EXISTS — reuse verbatim** | `_require_operator_value` `src/breezy/adapters/polymarket_us/safety.py:494-501` (no default, refuses blank); `_read_operator_money` `:503-515` (refuses non-money, refuses `<=0`); `_read_operator_count` `:517-525`. Precedent that this shape already reaches a native config: `operator_max_order_notional_whole_usd` `:527-567` feeding `build_trade_risk_engine_config` `node_config.py:539-547`. |
| N8 | Transient (429/5xx/timeout) vs durable refusal classification | **GENUINE GAP — verified absent** | `grep -rn --include='*.py' --include='*.pyx' "retryable\|RETRYABLE\|AMBIGUOUS\|Ambiguous" $NT` → **0 files**; positive control `retry_` → 32 files, `ambiguous` → 3 (all prose). Re-verified by the author, matching the parent plan's finding. `$NT/live/retry.py:65 RetryManager[T]` exists but is a *retry executor*, not a classifier, and is **banned by name** under barrier B8 (parent plan §R-7). Breezy-owned, declared as such. |
| N9 | Reversing `calculate_account_state` once set | **GENUINE GAP — verified absent** | `grep -rn "deregister_calculated_account" $NT` → **0**; positive control `deregister_cash_borrowing` → **1** (`$NT/accounting/factory.pyx:102-118`). The flag is a process-global dict `_ISSUER_ACCOUNT_CALCULATED` (`:25`), read at account construction (`:128`), and there is no way back. See §4. |
| N10 | Does the request body join the canonical signing string (OQ-2) | **GENUINE GAP IN EVIDENCE, not in code** | The venue SDK snapshot builds `f"{timestamp}{method}{path}"` with no body (`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/auth.py:26-27`), and Breezy mirrors it (`src/breezy/adapters/polymarket_us/signing.py:128-134`). `CanonicalRequest.body` is an inert seam (`signing.py:122`). **No amount of source reading closes this — only a live POST does.** That is precisely why it should be answered adjacent to its consumer, not weeks early. |
| N11 | Is the *query string* signed | **ALREADY MECHANISED, NEVER RUN** | `_probe_canonical_string` `scripts/venue/polymarket_us_auth_smoke.py:1042-1096`, with explicit "both accepted" (`:1080`) and "inconclusive" (`:1091`) branches. This is a **GET-only** discriminator and needs no write capability. It has not been run since auth was resolved. |

---

## 2. The R-5 / R-6 boundary this plan adopts, and why

**The parent plan's boundary cuts across the NO-SEND / SEND seam.** R-5-as-written lands a
write transport; R-6 lands purely local logic; R-7 lands the send. So the tree would carry a
write-capable module with no consumer for the whole duration of R-6 — exactly the entanglement
L-4 tells us to cut at a principled seam ("here, NO-SEND / SEND").

**Revision 1 sharpens this: the venue QUESTION and the shipped CAPABILITY are separable too.**
Revision 0 deferred both together, on a claim about `scripts/venue/` that was half wrong (§3
R-6.5P). Splitting them answers OQ-D early at strictly lower containment cost.

| Increment | Owns | Write capability |
|---|---|---|
| **W** — wire the client | The client is CONSTRUCTED by the node. `AccountState` reaches the cache. Caps de-inert **in the process**, not in a test. | none |
| **R-5R** — read-only venue truth | OQ-B, the query-signing half, a `cost`-semantics observation, the fee bound. | none |
| **R-6.5P** — the signing probe, EARLY | Answers OQ-D from a `scripts/venue/` script. Pays only the B4 allowlist the parent already scoped. **Ships nothing under `src/`.** | evidence only, not importable by the trading process |
| **R-6a** — live long-only guard | The guard installed on a live msgbus; the union exemption. | none |
| **R-6c** — health surface | `degrade()` **plus an operator-facing subscriber**; the exact-set `_refuse` inventory. | none |
| **R-6d** — refusal taxonomy | Transient vs durable, HTTP-status only. | none |
| **R-6e** — operator controls | The two reserved controls as mechanism; unset fails closed. | none |
| **R-7-PRE** | Closes the risk engine's no-account fail-open, **upstream**. | none |
| **R-6.5** — shipped write transport | The importable transport, the third canonical builder, the E0-INERT narrowing, four containment commitments, N2 widening. | **yes — the first thing under `src/` that has any** |
| **R-7** | `_submit_order` + the durable ambiguity latch. | yes |

**Why the shipped R-6.5 sits adjacent to R-7:** its barrier changes (B4, N2, E0-INERT, the
importer allowlist) and R-7's (B6/B7, B8, B9) are the same class of change against the same
files, and the paired-barrier rule requires each narrowing to land with its compensating
strengthening. One reviewer should hold the whole write-egress picture at once. Landing them a
month apart means the second reviewer inherits a narrowed E0-INERT as background.

**Argument against, kept so it can be attacked:** four separately-landable R-6 increments plus
R-6.5P plus R-7-PRE is more review overhead than one R-6. That is accepted deliberately —
Revision 0's monolithic R-6 hid that R-6e touches the operator-control contract while R-6a does
not, and hid a cut increment (R-6b) inside a bundle that otherwise looked sound.
## 3. The increments

### R-4P — cursor pagination on the private read — **MIXED** — *lands before W; step 1 is small*

**This increment did not exist before Revision 2. It exists because a live capture found a
latent defect in landed R-4 code and a direct collision with a containment property that two
reviews praised.** Both halves are stated here rather than left to an implementer.

#### The defect

The private surface is **cursor-paginated**. `GetUserPositionsResponse` carries `nextCursor` and
`eof` (`sdk_snapshot/.../types/portfolio.py:48-50`); `GetActivitiesResponse` carries the same
(`:117-119`); `GetUserPositionsParams` carries `market`, `limit`, `cursor` (`:36-42`).
**Measured: `eof`/`cursor`/`nextCursor`/`page` occur ZERO times in `exec/client.py`,
`exec/reports.py` and `exec/endpoints.py`**, and zero times anywhere in `src/`. R-4's
`_declared_positions` (`exec/client.py:881-894`) takes `payload["positions"]` and stops.

So R-4 reconciles **page 1** and calls it the book. See risk 0.

#### The collision, stated exactly

`PrivateRead.__call__(self, path: str)` has no params argument (`exec/client.py:347`), and both
the security review and this plan's own commitment **C4** treat that absence as a containment
property: a query smuggled into `path` breaks the canonical signing string and can collide with
V2's `_ORDER_PATH_RE` (`test_polymarket_us_readonly_guard.py:151`, which matches `/v1/order`
**and** `/v1/orders`). **You cannot paginate without either a parameter or exactly that
smuggling.** Resolved as follows, and pinned.

#### Resolution — a TYPED CURSOR, not a params mapping, and not single-page-only

**First, name the property correctly.** The containment property is *not* "the read takes no
arguments". It is **"no free-form query string is ever concatenated into the signed path"**. A
`params: Mapping[str, str]` argument would break that property (any key, any value, any
`&`/`?`/`/`). A single typed cursor does not.

**Rejected: documented single-page-only with a hard refusal when `eof` is false.** It fails
closed, which is right, but as a *terminal* design it bricks reconciliation on any account with
more positions than one page — and we do not know the page size (OQ-J). A node that can never
reconcile is a node that can never trade, permanently, for an ordinary condition. That is L-6's
corollary: fail-closed on a routine condition converts noise into an outage. **It is however the
right INTERIM**, which is why it is step 1.

**R-4P-1 — refuse the truncation (small; lands before W).** `_declared_positions` reads `eof`
and **refuses via `_refuse` when `eof` is absent or false**, converting a silent prefix into a
loud, latched refusal that denies every order. Nothing paginates yet. This is strictly safer
than today and is a handful of lines.
*RED:* `test_a_non_terminal_positions_page_latches_a_refusal`;
`test_an_absent_eof_is_treated_as_non_terminal` (absent is not terminal — the envelope is
`total=False`, so a missing `eof` is unknown, not `True`);
`test_a_terminal_page_reconciles_normally` (non-vacuity: the increment cannot pass by refusing
everything).

**R-4P-2 — the typed cursor.** Signature becomes:

```
async def __call__(self, path: str, *, cursor: str | None = None) -> Mapping[str, Any]: ...
```

with five pinned constraints:

1. **Exactly one extra parameter, keyword-only, `str | None`.** No `params`, no `Mapping`, no
   `**kwargs`. *RED:* `test_private_read_signature_admits_no_free_form_query` inspects the
   Protocol's signature and asserts the parameter names are exactly `("path", "cursor")` and no
   parameter annotates to a mapping or `VAR_KEYWORD`.
2. **`path` stays a bare path.** *RED:* `test_private_read_refuses_a_path_containing_a_query` —
   a `path` containing `?`, `&` or `#` is refused, so the V2 literal and the canonical string
   both see what they see today.
3. **The cursor is an opaque token, charset-validated.** Refuse anything outside
   `[A-Za-z0-9_\-=.]{1,512}`. The venue types it as a bare `str` (`:49`) and says nothing more,
   so Breezy constrains it rather than trusting it. *RED:* a cursor containing `&`, `?`, `/` or
   a newline is refused. **This is what makes the parameter structurally not a free-form query.**
4. **The cursor reaches the signer through `query_string`, never through `path`.** The signer
   already takes it (`signing.py:249`) and `build_canonical_path_with_query` (`:137-146`) exists
   precisely to test whether the venue signs it. **Consequence, and it is load-bearing:
   pagination is the FIRST thing in Breezy that depends on OQ-M's answer.** If the venue signs
   the query and Breezy does not (or vice versa), every page after the first 401s. So **OQ-M is a
   hard precondition of R-4P-2**, and R-4P-1 is what makes the wait safe.
5. **A hard page budget.** A maximum page count, with a latched refusal on exceeding it — never
   a truncation. A venue returning a cyclic `nextCursor` must not spin reconciliation forever.
   *RED:* `test_a_cyclic_cursor_latches_a_refusal_rather_than_looping`.

**C4 is UNCHANGED.** C4 governs the **write** callable, which never paginates and still takes no
query argument of any kind. Only the READ protocol gains a typed cursor. The two commitments were
never actually in conflict; what conflicted was C4's *rationale as stated* ("no query argument")
with the venue's shape. The rationale is restated above as "no free-form query in the signed
path", which both satisfy.

**Portability:** MIXED. Cursor pagination is a venue fact; "the read seam admits no free-form
query" is the portable rule.

**Barrier files that change:** none. R-4P adds no network capability and no write verb.

---

### W — wire the execution client into the trading node — **MIXED** — *the dominating increment*

**Null hypothesis:** Nautilus provides client registration. **CONFIRMED (N1).** Breezy authors a
factory and a config; no process machinery.

**What lands**

1. `PolymarketUSLiveExecClientFactory` (a `LiveExecClientFactory` subclass) and a
   `PolymarketUSExecClientConfig`, beside the existing data-side factory in
   `src/breezy/adapters/polymarket_us/factories.py`. Registered via
   `node.add_exec_client_factory(...)` (`$NT/live/node_builder.py:114`); constructed by
   `build_exec_clients` (`:201-246`).
2. `build_trade_node_config` gains `exec_clients={POLYMARKET_US_CLIENT_NAME: exec_client_config}`,
   replacing `exec_clients={}` (`node_config.py:654`). **`strategies=[]` and `exec_algorithms=[]`
   stay empty and are re-pinned** — so W makes the node capable of *reconciling* and *refusing*,
   never of originating an order. (§6 is explicit that this is also why the walk does not reach
   the goal state.)
3. **The `PrivateRead` construction site**, repairing R-4's Protocol erasure. `PrivateRead` is a
   `typing.Protocol` (`exec/client.py:335-347`), not `runtime_checkable`, and the client's own
   constructor says `callable()` "is the strongest check available" (`:479-486`). **The GET-only
   guarantee therefore lives at the wiring site.** The factory builds it as a closure over the
   existing GET-only callable (`transport.py:129-148`) and `Ed25519RequestSigner`, whose
   `PERMITTED_METHODS = frozenset({"GET"})` (`signing.py:84`, refusal at `:260-265`) is the actual
   enforcement. **W widens neither.**
4. **No `params` smuggling.** `PrivateRead.__call__(self, path: str)` has no query argument
   (`exec/client.py:347`). A query appended to `path` would be signed by
   `build_canonical_path_without_query` as a path segment while the venue verifies the bare path
   — and would trip V2 if it matched `/v\d+/orders?`. If pagination is ever needed the Protocol
   gains an explicit `query` parameter feeding the signer's `query_string` (`signing.py:249`).
   **Not in W.**
5. **`account_number`'s source is named and pinned.** `grep -rn "account_number" src/ scripts/`
   outside `exec/client.py` returns **zero producers**: it exists only as a constructor parameter
   (`:469`) and becomes the `AccountId` suffix (`:535-537`). W must name where it comes from —
   the operator's venue configuration, alongside the credentials at
   `~/.config/breezy/polymarket.env` — and pin its **stability across restarts**, because the
   durable store's keys (`exec/polymarket_us/...`) survive independently of it, so a changed
   `account_number` silently re-labels every event while orphaning nothing. See OQ-I.
6. **The exec-engine config pin moves onto the real config.** R-4's in-flight/interval pin
   asserts over a hand-built config. W re-points it at the output of `build_trade_node_config`,
   so a later edit adding `position_check_interval_secs` cannot re-arm the settlement-zero
   landmine (`_create_flat_position_report`, `$NT/live/execution_engine.py:1022`) with R-4's pin
   still green.

**RED tests (each with what it catches)**

| Test | Catches |
|---|---|
| `test_the_trade_node_config_registers_exactly_one_exec_client` | The literal defect this increment exists to fix. Asserts the key equals `POLYMARKET_US_CLIENT_NAME`, so the derived `AccountId` issuer is the one every other assumption keys on. |
| `test_the_wired_private_read_signs_exactly_one_get_over_the_bare_path` | Protocol erasure. Drives the **constructed** `client._private_read`, not the erased Protocol. *(Revision 4: this is the name W actually shipped, `tests/unit/test_polymarket_us_factories.py:571`. My Revision-2 list invented `…refuses_every_method_but_get`, which never existed — and could not, since the closure has no method parameter: `"GET"` is a hardcoded literal at `factories.py:712`. A structural absence beats a runtime refusal, and R-6.5's D4 mirrors this shape rather than the invented one.)* |
| `test_the_wired_private_read_has_no_query_parameter_in_its_signature` | The query-in-`path` smuggle, asserted on the signature (`test_polymarket_us_factories.py:595`). |
| `test_the_exec_client_is_not_constructed_on_the_main_thread` | Store thread affinity (`runtime/sqlite_store.py:120,128-135`) surviving the move to a real factory. The factory passes an *opener*, never an opened store. |
| `test_the_trade_node_config_still_declares_no_strategies_and_no_exec_algorithms` | Scope creep. |
| `test_the_inflight_and_check_interval_pins_hold_on_the_shipped_config` | Risk 13: a pin that tests a config nobody ships. |
| **`test_a_failed_connect_is_observable_and_does_not_exit_zero`** | **The silent non-start (risk 2).** R-4's `_open_state_store` raises (`exec/client.py:640`); `_on_task_completed` logs it and skips `actions` (`$NT/live/execution_client.py:212-226`); `_set_connected(True)` never runs; `_await_engines_connected` only *warns* (`$NT/system/kernel.py:1310-1316`); `start_async` returns with no trader (`:1024`); and `_exit_code_for_completed_run` reports only market-data faults (`trade_cli.py:127-144`) — so the process exits **`EXIT_OK`** having never traded. Pins the observable outcome and a non-zero exit. |
| `test_account_number_is_stable_across_a_restart` | OQ-I: a re-labelled `AccountId` against durable keys that did not change. |

**Done-when predicate — it must distinguish healthy from latched.** *(Revision 0's "every order
is denied" is satisfied identically by a healthy client and by one that timed out loading
instruments — the same anti-recurrence discipline §5 applies to the signing probe, omitted here.)*

`breezy-trade` starts against the live venue **and all of the following hold**:

1. `client.trading_refusals == ()` — no latch;
2. `instrument_provider.count > 0` — the load actually succeeded;
3. exactly one `AccountState` with a USD balance is in the cache;
4. `generate_mass_status` returns non-`None`;
5. `client.settled_positions` is recorded (empty or not) rather than unknown;
6. a submitted order is denied **with the standing R-4 reason** (`exec/client.py:329-332`), not
   with a latched-refusal reason;
7. the process exits `STOPPED` with `EXIT_OK` — and a **forced** store failure exits non-zero.

**Barrier files that change — CORRECTED in Revision 3, from actually implementing W**

Revision 2 said "the N2 exact-set pin … nothing else." **That was wrong, and the error is
instructive: I enumerated the barriers I had read rather than the barriers that gate the change.**
Implementing W required widening **four**, and a later increment reading "only N2 changes" would
have under-scoped its own barrier work and discovered the rest mid-implementation.

| # | Barrier | Why W trips it |
|---|---|---|
| 1 | N2 exact-set pin, `test_execution_egress_firewall_guard.py:705-721` | A `LiveExecClientFactory` subclass is classified **E2** (`_EGRESS_CLASS_BASES`, `:186-189`) and `factories.py` is venue-touching, so a new `(…/factories.py, "E2")` row appears. |
| 2 | `PERMITTED_EXECUTION_CLIENTS`, `test_polymarket_us_readonly_guard.py:734-743` | An equality on `(path, class, base)` whose docstring **literally read** "Factories stay banned outright — R-4 wires no client into a node". W is the increment that makes that sentence false. |
| 3 | Its meta-pin, `test_cage_rule_constants_are_pinned.py:511`, `:777` | Every cage constant is registered in `CAGE_RULE_PINS`, and the coverage test is an **EQUALITY** — `assert pinned == plans_nine \| added_with_a_reason` (`:780`). A changed constant that is not re-pinned fails here. |
| 4 | `TestTheReadOnlyCageIsDeclaredNotDefaulted`, `test_runtime_node_config.py:347` | Two sub-rules fire: the build-site **count** (`assert len(_node_config_calls()) == 3`, `:376`) and the per-field rule, since `exec_clients` stops being an empty literal for the trading role. |

**And the barrier suite is denser than this plan's prose has been assuming.** Four further
mechanisms apply automatically to any constant or exemption an increment adds, and no increment
below may claim "no barrier changes" without checking them:

- `test_every_pin_refuses_a_widened_neighbour` / `…_narrowed_neighbour` (`:714`, `:721`) —
  parametrized over every pin, so a new constant inherits both for free.
- `test_the_cage_grants_exactly_one_exemption` (`:808`) — a **count** pin on `CAGE_EXEMPTIONS`.
  **Every allowlist ENTRY** R-6.5P and R-6.5 add trips this, not just the constant.
- `test_every_cage_exemption_is_an_exact_path_not_a_prefix` (`:800`) — the "exact path, never a
  prefix" rule this plan states for R-6.5 is **already mechanised**; R-6.5 inherits it rather
  than inventing it.
- `test_p1_no_module_rebinds_a_pinned_constant_anywhere_in_the_repo` (`:900`) — scanned across
  `src`, `scripts` **and** `tests`.

W adds no network capability `data.py` does not already have. What it adds is a *classified*
execution surface, and four separate mechanisms exist to make that impossible to land silently.

**Portability:** MIXED. The factory is VENUE-SPECIFIC; the `exec_clients` wiring is PORTABLE.
### R-5R — read-only venue truth — **VENUE-SPECIFIC** — **BLOCKED ON VENUE AVAILABILITY, not on engineering**

**Measured 2026-09-02, deterministic across 5 attempts over ~10 minutes: the venue's PRIVATE
backend is down.**

| Path | Result | Class |
|---|---|---|
| `/v1/account/balances` | **500**, grpc 13 INTERNAL | implemented, failing |
| `/v1/portfolio/positions` | **503**, grpc 14 UNAVAILABLE | implemented, down |
| `/v1/orders/open` | **503**, grpc 14 UNAVAILABLE | implemented, down |
| `/v1/orders` (**GET**) | **501**, grpc 12 UNIMPLEMENTED | route not registered for this verb |
| `/v1/portfolio/activities` | **200**, envelope parsed | **WORKING** |
| `/v1/markets` (public gateway) | **200** | working — so this is the private surface specifically |

**Auth is PROVEN and is not the problem.** A signed GET to `/v1/portfolio/activities` returned
**200** with a parsed envelope; the same path unsigned returned **401**; a signed unknown path
returned **404 / grpc 5**. That is a three-way discrimination — accept, reject, not-found — and
it settles authentication in the affirmative. *(Standing repo finding, now discharged rather than
repeated: four earlier smoke runs recorded FAIL on quote COUNT, not on auth.)*

**So R-5R is not a task; it is a TRIGGER.** Writing it as a task would produce an increment that
an implementer starts, cannot finish, and quietly reports as blocked — which is how a plan
accumulates work that never completes. It is expressed as a re-probe condition instead.

#### R-5R-0 — the RUNNER gap, which must be closed first — *the one piece of actual code here*

**Revision 1 said "closing OQ-6 is an execution task with zero code". That was wrong, and it was
my error.** R-1 landed a shape **describer** and never a **runner**:
`scripts/venue/polymarket_us_shape_capture.py` has **no `main()`, no `argparse`, no `__main__`,
and performs no I/O** — verified by grep; its own docstring says it is pure. And
`polymarket_us_auth_smoke.py`'s CLI takes only `--quote-window-secs`, `--evidence-dir` and
`--skip-rate-limit-probe` (`:1276-1295`) — **no path argument** — and hardcodes
`PORTFOLIO_PATH = "/v1/portfolio/positions"` (`:163`). The capture that produced the table above
required an ephemeral driver supplied from outside the repo. **That is not repeatable, and these
paths must be re-probed every time the backend's state might have changed.**

**Owner: this plan. The runner is R-5R-0**, a script under `scripts/venue/` that takes the
endpoint path as an argument, calls the existing describer, and writes a `PRIVATE_`-prefixed 0600
artifact. Constraints, so it cannot become a second write-capable surface by accident:

- It is **GET-only by construction**, reusing the same GET-only callable (`transport.py:129-148`)
  and signer (`PERMITTED_METHODS = frozenset({"GET"})`, `signing.py:84`) that W wires. It does
  **not** import, and may not import, anything from R-6.5P or R-6.5.
- It lives under `scripts/venue/`, which B4 already classifies venue-touching
  (`test_polymarket_us_readonly_guard.py:169-172`), so V1-V4 apply to it unchanged and **it
  requires NO allowlist entry** — a GET-only runner trips none of them.
- The endpoint is a **caller argument validated against a plain-path charset**
  (`_validate_endpoint`, `polymarket_us_shape_capture.py:573`), never a literal, so V2 never sees
  `/v1/orders` in source. This is the same reason R-1's module lives where it does.
- *RED:* `test_the_shape_runner_is_get_only` (a non-GET request is refused before any credential
  is used); `test_the_shape_runner_imports_no_write_surface` (an AST import scan);
  `test_the_shape_runner_records_a_grpc_status_class_not_a_verdict` (see R-6d).

#### R-5R-1 — the re-probe trigger

**Trigger:** run R-5R-0 against `/v1/account/balances`, `/v1/portfolio/positions` and
`/v1/orders/open`. Re-run daily, unattended, and on any operator signal that the venue has
changed state. **Nothing downstream starts until at least `/v1/portfolio/positions` and
`/v1/account/balances` return 200**, because those two are the whole of R-4's read surface.

**The two branches, and what distinguishes them — OQ-K, the highest-leverage unknown here.**
`/v1/portfolio/positions` returned **200 on 2026-08-30** and **503 today**, which is consistent
with both of:

| Branch | What it means | Discriminator |
|---|---|---|
| **Transient platform outage** | A wait. Nothing to build, nothing to ask. | The 200 returns unaided; and `/v1/portfolio/activities` (also private, also account-scoped) is **already** 200, which is mild evidence *against* a whole-surface outage. |
| **Persistent per-account condition** — e.g. a clearing account not provisioned, or an entitlement that lapsed | A venue-support conversation. **Nothing in this repo can resolve it**, and no amount of engineering makes it go away. | Two signals, both cheap: (a) the 500-vs-503 SPLIT — `/v1/account/balances` fails with INTERNAL while its neighbours fail with UNAVAILABLE, which is not the signature of one dependency being down; (b) `activities` returning 200 with a well-formed envelope proves the account resolves on at least one private path. |

**If the condition persists past a small number of daily re-probes, it stops being an engineering
question and becomes an operator/venue one, and the plan should say so rather than keep
re-probing.** That escalation is named here so it is a decision rather than a drift.

#### R-5R-2 — what R-5R records once the surface returns

1. **OQ-B**: whether an unfiltered `GET /v1/orders/open` returns orders Breezy did not place.
   Hard precondition of R-6.5P.
2. **OQ-J**: the positions page size and whether `eof` is true on page 1 for this account —
   directly feeding R-4P.
3. **OQ-C**: the `cost`/`qtyBought`/`qtySold` key shapes, recorded as *shape only*. Does **not**
   close OQ-1, which needs a restart after a real fill (`EXEC_SPINE_2026-09-01.md:1028`).
4. **OQ-E**: the fee bound attempted from the docs snapshot only. `POST /v1/order/preview` is
   **not** called — OQ-3 is unproven and the parent plan's rule is "if unproven, never call it".

#### R-5R-3 — OQ-M is unblocked NOW, and should be run NOW

`_probe_canonical_string` (`polymarket_us_auth_smoke.py:1042-1096`) discriminates whether the
query string is signed. It currently targets `PORTFOLIO_PATH` (`:163`) = `/v1/portfolio/positions`
— **503**. Re-point it at **`/v1/portfolio/activities`**, the one private path measured **200**,
and it runs today. This is worth doing immediately rather than waiting, because **OQ-M is a hard
precondition of R-4P-2**: pagination is the first thing in Breezy that puts a query on a signed
request, and getting the variant wrong 401s every page after the first.

**Barrier files that change:** none.

**Done when:** the runner exists and is repeatable (R-5R-0); OQ-M carries one of the four coded
outcomes (R-5R-3); and, once the backend returns, OQ-B and OQ-J carry verdicts recorded as
`ANSWERED`/`PARTIAL` per §5 — never as a bare status code (L-8).

---

### R-6a — the live long-only order guard — **PORTABLE** — *its own increment*

*Revision 1 splits Revision 0's monolithic R-6. R-6a and R-6e are separately landable and are
separately reviewable; bundling them hid that R-6e touches the operator-control contract and
R-6a does not.*

**Null hypothesis:** a new guard is needed. **REFUTED (N6).**

`install_live_order_guard(portfolio, cache, msgbus) -> BacktestOrderGuard`, a ~3-line sibling of
`install_order_guard` (`backtest_order_guard.py:214-222`). **Coverage gap, re-verified:**
`test_runtime_backtest_order_guard.py:307` asserts the *source string*
`"install_order_guard(engine)"` appears in a file, and `_refuse_naked_short` is named only in a
docstring at `test_backtest_harness_refusal_precedence.py:294`. **R-6a adds behavioural tests for
both before extending either.**

*Naming note, raised not resolved:* installing a class literally named `BacktestOrderGuard` into
a live node is a legibility hazard. Renaming it touches backtest tests and is **out of scope**;
the live installer's docstring must state the class is venue- and mode-agnostic and cite the
0-venue-reference measurement.

**The exemption keys on the UNION of (a) the RECONCILIATION tag and (b) the deterministic
settlement `ClientOrderId`** — never on order type. Re-verified: `generate_missing_orders` emits
MARKET events (`$NT/live/config.py:108-110`), and a **claimed** order carries `tags=None` because
`external_order_claims` short-circuits `StrategyId("EXTERNAL")` assignment
(`$NT/trading/config.py:91`; `$NT/live/execution_engine.py:3565`). A tag-only exemption refuses
every R-9 settlement leg and **the failure looks like a working guard**.

**RED:** `test_the_live_installer_installs_on_a_live_shaped_msgbus` (behavioural, defeating the
existing source-string assertion); `test_refuse_naked_short_refuses_and_names_the_instrument`;
`test_a_reconciliation_tagged_market_sell_passes_the_live_guard`;
`test_a_claimed_settlement_order_with_tags_none_passes_the_live_guard` (the trap that looks like
a working guard); `test_an_untagged_unclaimed_market_sell_is_still_refused`.

**Barrier files that change: none — basis CORRECTED in Revision 5; the conclusion held, the
reasoning did not.** Revision 3 asserted `backtest_order_guard.py` carries **0** venue references,
so B4 never classifies it. **Both halves are false, and were measured false on 2026-09-02:** the
file carries **6** venue references (module docstring line 6, docstrings 93/106, f-strings
145/165/166), and `is_venue_touching()` returns **True** on it — classifier rule **C5**
(`_VENUE_NAME_RE = /polymarket/i`) matches the venue's NAME in *any* `ast.Constant`, and a module
docstring is an `ast.Constant`. The file has been in B4 scope all along; it simply has **0**
current V1-V4 violations (also measured). So R-6a lands clean — but **because it adds no write
verb, not because the file is unclassified.**

**The live trap this correction exposes:** V3 bans any `ast.Attribute` whose name is in
`{post, put, patch, delete, request}` — *syntactically, on any object whatsoever*. Nautilus's
`MessageBus` HAS a `.request()` method. An installer written as `msgbus.request(...)` would trip
V3 inside a file the plan claimed was exempt. Mirror `install_order_guard` and use
`msgbus.subscribe(topic=..., handler=...)`; `subscribe` is not in the banned set. Do NOT
"fix" a V3 hit by narrowing the classifier or the attribute set — that is the exact L-12
violation (widen an exact-set barrier, never relax the comparison).

Continuing the enumerated §3 W check: it adds no cage constant, so the
`CAGE_RULE_PINS` equality (`test_cage_rule_constants_are_pinned.py:780`) is unaffected; it adds
no exemption, so the exemption **count** pin (`:808`) is unaffected; and it defines no class
whose base is in `_EGRESS_CLASS_BASES`, so N2 is unaffected.

**The install SITE is the design decision, and it is pinned here.** The guard attaches to
`node.kernel.msgbus` in `trade_cli` after `node.build()` — the same shape as
`install_order_guard` (`backtest_order_guard.py:220-221`), which reads `engine.kernel.msgbus`.
It is **not** registered as an `Actor`, so `actors=[]` (`node_config.py:697`) stays an untouched
empty literal. *(Residual, recorded: the read-only cage's per-field rule covers `strategies` and
`exec_algorithms` (`test_runtime_node_config.py:377`) and `exec_clients` separately — it does
**not** cover `actors`. An `Actor` could therefore be added without tripping the cage. That is
defensible, since only `Strategy` and `ExecAlgorithm` can reach `submit_order`, but it means
"the cage would have caught it" is not available as an argument for anything actor-shaped.)*

If R-6a finds itself editing a barrier, it has grown a send path and the increment is wrong.

**Done when:** the wired live node reconciles with the guard installed, no crash, five tests green.

---

### ~~R-6b — per-instrument refusal~~ — **CUT in Revision 1**

**The hazard I used to justify it is fabricated at both cited sites, and I verified the
load-bearing one myself rather than accepting the correction.**

- `_committed_basis` (`src/breezy/strategy/cli_settlement_print_lock/strategy.py:882-887`)
  iterates `self.cache.positions_open(instrument_id=nt_id)` — **instrument-scoped**. A refused
  instrument's zero-priced position cannot contaminate another instrument's basis. The
  contamination path Revision 0 described does not exist.
- `forecast_mispricing/strategy.py:419` reads `account.balance_total(...)`, which is the
  venue-reported balance that §4 shows Nautilus never touches (`$NT/portfolio/portfolio.pyx:502`,
  `calculate_account_state` False). That citation never carried the weight assigned to it.

**Three further reasons the increment should not exist, independent of the refutation:**

1. It buys operational convenience for a node that, per §6, has `strategies=[]` and **cannot
   originate an order for any instrument anyway**. The convenience has no consumer.
2. There is no data. The client has never run live (§0 fact 1), so the premise that
   unattributable positions are common enough to matter is unmeasured.
3. It is the **only** piece of Revision 0's R-6 that weakens R-4's node-global,
   never-self-clearing refusal latch (`exec/client.py:160-167`) — the strongest guarantee R-4
   landed. Trading a verified guarantee for an unmeasured convenience is the wrong direction.

**OQ-F survives as a question** (§9). Re-open the increment only if W's live runs show
unattributable positions are actually common, and only with fresh evidence for the hazard.

*Provenance, recorded per L-10:* the fabricated hazard entered through a commissioning brief and
Revision 0 promoted it to a verified constraint without opening either cited line. That is the
exact L-10 failure shape — coordinator shorthand becoming a subagent's verified fact — and the
countermeasure that caught it was the mandatory peer review.

---

### R-6c — the operator-facing health surface — **PORTABLE**

**Null hypothesis:** Breezy needs a health hook. **REFUTED (N2, N3)** — but Revision 0's
increment shipped the native FSM call *alone*, which is **less operator signal than exists
today**, and that is corrected here.

**What Revision 0 got wrong.** `degrade()` publishes `ComponentStateChanged` to
`events.system.<component_id>` (`$NT/common/component.pyx:2222-2225`) where **nothing native and
nothing in Breezy subscribes**. Meanwhile `_refuse` *already* logs at ERROR
(`exec/client.py:1365`) and `trading_refusals` is *already* an exposed property (`:546-554`). So
"call `degrade()`" alone adds an unobserved event and removes nothing — a health surface in name
only.

**Therefore R-6c ships the subscriber, or it does not ship.** Three parts, one commit:

1. `self.degrade()` on the first refusal — legal from `RUNNING`, which OQ-A now proves is always
   the state when `_connect`'s refusals fire (§9).
2. **An operator-facing subscriber**, at the wiring layer (never under `exec/`, which may not
   import `breezy.runtime.health` — `test_execution_egress_firewall_guard.py:1619`). It
   subscribes `events.system.*`, and on a `ComponentStateChanged` to `DEGRADED` from the exec
   client emits one alert through the existing `AlertSink` seam (`runtime/health.py:73`,
   `resolve_alert_sink` `:81`) carrying the refusal reasons.

   **Its host is a decision, and Revision 3 makes it: a plain `msgbus.subscribe` in `trade_cli`
   after `node.build()` — NOT an `Actor`.** An `Actor` would populate `actors=[]`
   (`node_config.py:697`), and although the read-only cage does not currently police that field
   (see R-6a's residual), the field is declared as an empty literal deliberately and the
   subscriber has no need of the `Actor` lifecycle: it holds no state, subscribes once, and
   emits. Same attachment point as R-6a's guard, which keeps one wiring idiom instead of two.
3. **The exact-set `_refuse` inventory test** (below), which is what makes the L-6 judgement
   auditable instead of hand-counted.

**L-6, applied properly this time.** Revision 0 hand-enumerated the `_refuse` producers and
**listed 21 of 25** — the misses include `:944`, the non-long-position refusal, which is
arguably the most safety-relevant reason in the file. *Making a "DEGRADED is routine" judgement
on 84% of the producers is precisely the failure L-6 exists to prevent.* So:

- **RED `test_the_refusal_producer_set_is_exactly_pinned`** — an AST scan asserting the EXACT set
  of `self._refuse(` call sites in `exec/client.py` (**25 today**: `:659, 666, 670, 691, 769,
  779, 864, 905, 921, 944, 969, 994, 1002, 1025, 1035, 1051, 1058, 1081, 1152, 1160, 1178, 1181,
  1250, 1259, 1267`). A new producer turns it red, forcing a triage rather than an inheritance.
  **Non-vacuity:** plant a 26th and the test must fire.
- All 25 are re-triaged as ROUTINE or EXCEPTIONAL in the increment. Several are routine — a
  venue-priced foreign position (`:994`) is ordinary on an account an operator has also traded
  by hand. **Therefore DEGRADED is a health INDICATOR, not a kill switch, and R-6c must not wire
  it to process exit.**

**RED:** `test_the_refusal_producer_set_is_exactly_pinned`;
`test_a_refusal_during_connect_emits_exactly_one_operator_alert` (the subscriber actually
alerts — the test Revision 0 lacked); `test_degrading_the_exec_client_does_not_stop_the_node`
(L-6); `test_a_second_refusal_does_not_re-alert` (the ERROR log is already deduplicated at
`:1362-1364`; the alert must be too).

**Done when:** a refusal produces a DEGRADED component state, exactly one operator alert
carrying the reasons, and a node that keeps running.

---

### R-6d — transient vs durable refusals — **PORTABLE**

**Null hypothesis:** a native taxonomy exists. **GENUINE GAP (N8).** Breezy-owned, two classes:
`TRANSIENT` (HTTP 429 or 5xx observed at boot) and `DURABLE` (everything else, which is the
**default**).

Transient refusals are the only ones that may be re-derived on a subsequent successful reconcile
of the same instrument. Durable ones keep R-4's invariant 1 exactly. **The default is the safe
direction and is tested as the default**, not as a fallback branch nobody exercises.

*Scope limit, stated rather than papered over:* timeout-driven classification is **excluded**.
`NautilusHttpTransport.get` collapses `HttpError` and `HttpTimeoutError` into one
`VenueTransportError` with `from None` (`transport.py:343-348`), and the parent plan forbids
changing the read path (`EXEC_SPINE_2026-09-01.md:503`). R-6d classifies on HTTP status only;
timeouts arrive with the write path's two distinct error types at R-6.5.

**The measured error envelope, from the 2026-09-02 capture — and it is worse than a generic
taxonomy would assume.** The venue returns `google.rpc.Status` — `{code: int, message: str,
details: list}` — and **the `message` string is IDENTICAL across codes 5, 12, 13 and 14.** It
carries zero discriminating information. Two hard rules follow:

1. **Classify on `code` and HTTP status ONLY. Never on message text.** A substring match on the
   message would classify a 501 UNIMPLEMENTED identically to a 503 UNAVAILABLE — i.e. it would
   treat "this venue will never implement this" as "retry in a minute". *RED:*
   `test_the_classifier_ignores_message_text` — two payloads with identical messages and
   different codes must classify differently; **non-vacuity:** a classifier that reads `message`
   must fail it.
2. **The envelope may NOT be assumed on the auth-rejection path.** The measured **401 body is not
   JSON at all** (33 bytes). A parser that assumes `google.rpc.Status` throws exactly where it
   hurts most — on the credential path, during boot, where the exception is easily misread as a
   venue outage rather than a rejected signature. *RED:*
   `test_a_non_json_401_body_classifies_without_raising`.

**The code map, stated rather than inferred:** `14 UNAVAILABLE` and `13 INTERNAL` are TRANSIENT
candidates (implemented, failing); `12 UNIMPLEMENTED` is **DURABLE and permanent** — retrying it
is pure waste and it must never be classified transient; `5 NOT_FOUND` is DURABLE. Anything
unrecognised is DURABLE, the default.

**RED:** `test_a_transient_http_status_is_reclassified_on_a_later_successful_reconcile`;
`test_an_unclassified_refusal_is_durable`; `test_a_timeout_is_not_classified_transient`;
`test_the_classifier_ignores_message_text`; `test_a_non_json_401_body_classifies_without_raising`;
`test_grpc_12_unimplemented_is_never_transient`.

---

### R-6e — the two operator-reserved controls, as mechanism only — **PORTABLE** — *its own increment*

**Null hypothesis:** a new mechanism is needed. **REFUTED (N7).** Reuse `_require_operator_value`
(`safety.py:494-501`) verbatim.

- **Max daily budget** — a rolling calendar-day USD spend-down. `RiskLimits` has no time
  dimension (`docs/core/PROGRESS.md:29-31`), so the accumulator is Breezy-owned. Unit: **USD
  notional spent** (L-2).
- **Max per position** — unit is **USD cost**, not contracts: for a long-only binary book max
  loss = premium = price x qty (L-2).

**No value is assigned anywhere in this repo.** Arrival path: the operator exports the two
variables in the shell that launches `breezy-trade`. Never from a repo file, a fixture, a
`conftest`, a committed `.env`, a default argument, or `os.environ.get(NAME, <fallback>)`.
Absence FAILS CLOSED — with both unset every order is refused, and the refusal names the missing
control and never its value (`safety.py:221-225` emits only `type(value).__name__`).

**RED:** `test_no_repo_file_assigns_an_operator_reserved_control` (AST/text scan over `src/`,
`scripts/`, `tests/` and every tracked `*.env*`/`*.toml`/`*.yaml`; **non-vacuity: plant
`os.environ.setdefault(NAME, "5")` and the scan must fire**);
`test_operator_controls_have_no_default_on_any_path`;
`test_refusal_names_the_control_not_the_value`.

**Barrier files that change: none for R-6c, R-6d or R-6e** — verified against §3 W's enumerated
list on the same four grounds given under R-6a (no venue classification, no new cage constant, no
new exemption, no `_EGRESS_CLASS_BASES` subclass).
### R-6.5P — the signing probe, EARLY, as evidence-only under `scripts/venue/` — **VENUE-SPECIFIC**

**Revision 1 splits Revision 0's R-6.5 in two, because Revision 0's reason for deferring the
whole thing rested on a claim that is false.** Revision 0 rejected a `scripts/venue/` probe as
shipping "entirely outside the N2 firewall with every barrier green". **Half of that is wrong
and it is the important half.** Precisely:

- **N2's E-rules would NOT classify it** — E0 is a path prefix on `exec/`
  (`test_execution_egress_firewall_guard.py:172`), and E1/E2/E3 key on basenames, class bases and
  order-verb function names that a probe script carries none of. That much of Revision 0 was
  right, and it is *immaterial*: N2 governs the pytest session's egress attestation, which is
  **already armed** for every run because `exec/` has held modules since R-3.
- **B4's write-verb rules DO cover it, and B4 is the barrier that actually governs a POST.**
  `EGRESS_SCAN_ROOTS = ("src", "scripts")` (`test_polymarket_us_readonly_guard.py:124`) and
  `VENUE_TOUCHING_SCRIPT_PREFIXES` names `scripts/venue/` explicitly (`:169-172`) — with a
  comment stating exactly why it was written before the directory existed: "or the first probe
  written there is exempt from every write-verb rule and nobody notices."

So "probe early" and "do not narrow E0-INERT early" were never mutually exclusive. **R-6.5P runs
the signing probe now, paying only the B4 allowlist narrowing the parent plan already scoped
(`EXEC_SPINE_2026-09-01.md:477-482`), and ships NOTHING under `src/`.** OQ-D is answered before
R-7 designs around it, at strictly lower containment cost.

**Precondition, hard:** OQ-B CLOSED at R-5R with a verdict of `ANSWERED`. If an unfiltered
`GET /v1/orders/open` does not report foreign orders, whole-account flatness is unprovable and
**R-6.5P does not run** — the parent plan's own rule (`EXEC_SPINE_2026-09-01.md:454`), preserved.

**What lands:** one script under `scripts/venue/`, plus the B4 exact-path allowlist entry for it
alone. It is **not importable by the trading process** (scripts are not a package) and **nothing
under `src/` gains any write capability**. Everything the parent plan specifies carries over
unchanged: whole-account flatness proven unfiltered before and after, the four-request budget,
`redact_headers` (`redaction.py:70`) / `redact_url` (`ingest/http.py:282`), the 30-second
replayable-bearer-credential hazard (`signing.py:89`; no nonce at `:128-134`), and the
`_probe_canonical_string` four-outcome shape (`polymarket_us_auth_smoke.py:1042-1096`).

**HARD SAFETY GATE — the barriers cannot prove this, and the venue currently cannot answer it.**

*The re-review's formulation, kept because it is better than mine:* **the barriers make the write
capability's ARRIVAL impossible to ship silently; they do not, and structurally cannot, prove the
DESTRUCTIVE SAFETY of the operation once it runs.** Every barrier in this plan is a static AST
scan of source SHAPE. The property that actually makes a cancel-all safe is a RUNTIME fact —
whole-account flatness, "not the verb" (§5) — and no AST scan reaches it. Revision 1 half-admitted
this and left it resting on the author's intent. Two things close the residual:

1. **A mechanized structural assertion of the ORDER of operations.** An AST check over the probe
   script asserting that an unfiltered `GET /v1/orders/open` call appears **before** the POST and
   another **after** it, in the same function. *Non-vacuity:* delete either GET, or move one
   after the POST, and the test must fire. This does not prove flatness — nothing static can —
   but it removes "the author forgot the check" from the failure set, which is the part that is
   mechanizable.
2. **A REFUSE-TO-RUN precondition on the pre-flight GET, and this is currently UNSATISFIABLE.**
   The flatness check is performed by `GET /v1/orders/open` — **which is returning 503 / grpc 14
   UNAVAILABLE on every one of five attempts (2026-09-02, §3 R-5R).** So the one check that makes
   a cancel-all safe on this account **cannot presently be performed at all**. Therefore:

   > **R-6.5P REFUSES TO RUN unless its pre-flight `GET /v1/orders/open` returns HTTP 200 with an
   > empty order list.** Not a warning. Not an assumption. Not a fallback to "probably flat". Any
   > non-200 — 503, 500, 429, a timeout, a malformed body — is a refusal to proceed, and the
   > post-POST GET is held to the same standard.

   Absent this gate, the first write this system ever performs would be a **cancel-all fired at
   an account whose state we are structurally unable to observe**, on a venue whose `slugs`
   filter is optional and whose documented degradation is cancel-ALL
   (`sdk_snapshot/.../types/orders.py:153-156`).

   **This is a VENUE-AVAILABILITY gate, not an engineering one.** Nothing is built to satisfy it
   and nothing can be; it clears itself when the private backend recovers (OQ-B / OQ-K), and it
   is therefore a re-probe trigger exactly like R-5R-1, not a task.

*Consequence for the sequence:* R-6.5P was moved EARLY in Revision 1 to de-risk calendar. **That
rationale survives, but its precondition is now blocked**, so in practice R-6.5P runs when R-5R-1
reports `/v1/orders/open` healthy. R-5R-3 (the query-signing half, OQ-M) is unaffected and runs
today against `/v1/portfolio/activities`.

**Two shape constraints this plan adds:**

- **No query argument.** The probe's write callable takes `(path, body)` and **no query
  parameter**, the same reasoning that makes `PrivateRead.__call__(self, path)` safe
  (`exec/client.py:347`). A cancel-all POST that later grows a filter parameter would sign one
  string while the venue verifies another, and the consequence is a **misfired cancel on a live
  account**, not a 401 — `slugs` is optional (`sdk_snapshot/.../types/orders.py:153-156`) so the
  documented degradation is cancel-ALL.
- **Narrow excepts only.** The two new error types are raised from `except (HttpError,
  HttpTimeoutError)`, never `except Exception` and never `except BaseException`.
  `CancelledError` is a `BaseException` in 3.13 and must propagate; the read path's own comment
  at `transport.py:343` is the model for the tuple, not for the collapse.

**B4 non-vacuity, both directions** (per the parent plan): remove the probe's path from the
allowlist and B4 must fire on it; plant a second script with the same literals and B4 must fire.

**Done when:** OQ-D carries `AUTH_OK` / `AUTH_REJECTED` / `INCONCLUSIVE` / `TRANSPORT_FAULT` per
the §5 table, under proven whole-account flatness, with a git-ignored 0600 artifact.

---

### R-6.5 — the shipped write transport — **VENUE-SPECIFIC** — *stays adjacent to R-7*

The *shipped, importable* write transport under `src/breezy/adapters/polymarket_us/exec/` still
lands next to R-7, because that is where its consumer is. R-6.5P has already answered OQ-D by
then, so this increment is pure engineering with no venue unknown left in it.

#### FIRST — does the write transport share the read path's `HttpClient`? **YES, and answering it
#### changes this increment's shape substantially.**

**The rate-limit fact, verified.** `nautilus_pyo3.HttpClient.__init__` takes `keyed_quotas` and
`default_quota` as **constructor arguments** (`$NT/core/nautilus_pyo3.pyi:5416-5424`), so the
token bucket is scoped to the OBJECT. Two clients are two independent buckets while the venue
enforces per **account** — up to 2x the intended request rate. Every shipped multi-client adapter
solves this with module-level `@lru_cache(1)` singletons shared by both factories, including
Nautilus's own Polymarket adapter: `get_polymarket_http_client` (`$NT/adapters/polymarket/factories.py:42-43`)
and `get_polymarket_instrument_provider` (`:100-101`), called from the data factory (`:169`,
`:178`) and the exec factory (`:232`, `:246`). **13 of the shipped `adapters/*/factories.py` use
`lru_cache`** — this is the dominant idiom, not one adapter's taste.

**Decision: the write path SHARES the read path's client, and receives its POST capability by
INJECTION — the same idiom R-4 already uses for `PrivateRead`.**

**The second-order consequence is large, and it is the reason this question had to be answered
before the E0-INERT spec rather than after.** If the write transport is *handed* a
POST-capable callable built outside `exec/` — exactly as `exec/client.py` is handed `PrivateRead`
so that it "imports no network-capable client at all" (its module docstring) — then:

- **`exec/` never imports `nautilus_pyo3` at all, so the E0-INERT narrowing is NOT NEEDED.** The
  CRITICAL that Revisions 1 and 2 spent most of their containment budget on **disappears**, and
  `exec/` keeps its inertness guarantee absolutely rather than by exception.
- **C-A's member-level allowlist becomes empty** for that module — there is no `nautilus_pyo3`
  member to allow, because there is no reference.
- The shared singleton is preserved by construction, since the callable is built from the one
  client the read path already made.

**What that costs — and Revision 4 corrects the accounting, because Revisions 3's version was a
fiction.** Revision 3 claimed the cost was "closed by widening E1, and a classifier widening is a
strengthening". **That is wrong on two counts, both verified:**

- **E1 classification RESTRICTS NOTHING.** `find_execution_egress_modules` has exactly four
  consumers — the firewall-existence check (`:547`), the N2 exact-set pin (`:715`), and
  N2-ABORT's two child-gate preconditions (`:869`, `:898`). It carries **no** import rule, **no**
  member allowlist, **no** caller rule. Only E0-INERT restricts, and E0-INERT is scoped by its
  own test to the `exec/` prefix — `test_e0_inert_is_scoped_to_the_exec_package`
  (`:2041-2046`), whose docstring reads *"`transport.py` legitimately holds the venue HTTP
  client"* and whose non-fire proof asserts on **`transport.py` itself**: the exact file family
  this reversal routes construction into.
- **Nothing was owed on that axis anyway.** As of increment W, `factories.py` is **already**
  E2-classified — `("src/breezy/adapters/polymarket_us/factories.py", "E2")` sits in the N2 pin
  at `:733`. N2-ABORT already fires regardless of what R-6.5 chooses. A widening that changes no
  behaviour cannot pay for anything.

**The honest accounting.** The reversal **eliminates two** risks — any `exec/` module importing a
network client, and the doubled rate bucket — and **gives up one**: the member-shape guarantee.
Under alternative (A), a member-level allowlist made importing `SocketClient`, `WebSocketClient`
or another venue's exec config **structurally impossible at the construction site**. Under the
reversal there is no import-shape rule at that site at all. **That is a genuine loss, not a
relocation**, and this plan credited it as paid for. Security condition 5
(`EXEC_SPINE_2026-09-01.md:464-472`) was protecting exactly this: its own comment block
(`test_execution_egress_firewall_guard.py:164-172`) foresaw `transport.py`/`factories.py` as
blind to E1/E2/E3 by name. Reversing it surrenders the import-shape guarantee, and the fix is to
**restore that guarantee at the new site**, not to revert the design.

**Five commitments do that. D2 and D3 are load-bearing.**

**D1 — the modules, named.** Two sites, because the read path already splits them and the write
path must mirror it rather than invent a third shape:
* **`src/breezy/adapters/polymarket_us/transport.py`** hosts the POST-capable builder — a twin of
  `_build_get_only_callable` (`transport.py:129`), constructed against the **shared**
  `HttpClient`. This is the module that mints the capability.
* **`src/breezy/adapters/polymarket_us/factories.py`** mints the injected closure handed into
  `exec/`, a twin of the `private_read` closure (`factories.py:700-718`). It references **no**
  `nautilus_pyo3` member in code today (its single occurrence, `:413`, is a comment), and it must
  stay that way.

**D2 — a member-level allowlist on `transport.py`, mirroring alternative A's C-A.** This is the
construction site now losing E0-INERT's protection, so it is where the rule belongs. **Correction
to the condition as posed: the allowlist is NOT `{"HttpClient"}`.** `transport.py` legitimately
references four members today — `HttpClient`, `HttpError`, `HttpTimeoutError` and `Quota` (the
error pair is what `transport.py:343` catches; `Quota` builds the rate budget). The rule is an
**equality on the actual set**, extended by exactly whatever the POST builder needs and no more.
What matters is what it EXCLUDES: `SocketClient` (`$NT/core/nautilus_pyo3.pyi:5587`, raw TCP,
which this repo's own barrier calls "entirely unguarded", `:134-135`), `WebSocketClient`
(`:5547`), and every other venue's exec config (e.g. `:10192`). *RED:*
`test_the_venue_transport_references_exactly_the_permitted_pyo3_members`; **non-vacuity:** plant
each of the three excluded names and each must fire. **Doing this makes the reversal strictly
better than alternative (A) rather than a trade** — (A) protected only `exec/`, which under the
reversal has nothing to protect.

**D3 — a caller allowlist on the BUILDER FUNCTION, not only on the wrapper.** C1-C4 gate the
wrapper; the closure builder is what actually **mints** the capability, and today any caller
holding the client and the signer could construct an equivalent write-capable closure without
tripping anything. Note the read twin's protection is **module privacy, not a rule**:
`_build_get_only_callable` has exactly one caller (`transport.py:325`), and nothing enforces
that. So the POST builder's name goes in the `BARRED_CALLEES` mechanism
(`test_polymarket_us_readonly_guard.py:401-405`) with an exact-path one-caller pin — the same
shape as B6/B9, no new machinery — scanned **repo-wide**, since a fixture or CI helper minting a
write closure is invisible under `EGRESS_SCAN_ROOTS`. **Non-vacuity, both directions:** remove
the one legitimate caller and the pin must fail; add a second anywhere and it must fail.

**D4 — the wiring-site test, named — and the condition's premise needs one correction.** The
review asked for a twin of `test_the_wired_private_read_refuses_every_method_but_get`. **That test
does not exist under that name**; my own Revision-2 RED list invented it. What W actually shipped
is better: `test_the_wired_private_read_signs_exactly_one_get_over_the_bare_path`
(`tests/unit/test_polymarket_us_factories.py:571`, which drives the CONSTRUCTED `client._private_read`)
and `test_the_wired_private_read_has_no_query_parameter_in_its_signature` (`:595`). And the
reason there is no "refuses every method" test is that **the closure has no method parameter to
refuse with** — `"GET"` is a hardcoded literal at `factories.py:712`. A structural absence beats a
runtime refusal. **So the write twin is specified the same way, not as a refusal test:**
`test_the_wired_write_call_has_no_method_and_no_query_parameter_in_its_signature` and
`test_the_wired_write_call_issues_exactly_one_post_to_the_one_pinned_path` — the cancel-all path,
pinned as a constant, with **non-vacuity against a widened write-side path allowlist**.

> **D4's corollary, and it is the 2am trap.** `Ed25519RequestSigner.sign_headers` raises
> `MethodNotPermittedError` for anything outside `PERMITTED_METHODS = frozenset({"GET"})`
> (`signing.py:84`, `:260-265`), so a write closure calling `sign_headers("POST", ...)` **raises
> with the shipped signer**. `PERMITTED_METHODS` must **NOT** be widened — it is the read slice's
> barrier B2 and is constant-pinned. The write path therefore needs its **own signer type with
> its own permitted set**, and that separate gate is what D4's tests must exercise. An
> implementer who resolves this by adding `"POST"` to the existing frozenset has silently
> converted every read-path signer in the process into a write-capable one.

**D5 — the prose correction** is the paragraph above: N2-ABORT already fires via W's E2 row, and
E1's real contribution here is **audit-trail visibility, not restriction**.

**Scope of the residual, from the review and worth recording:** at TEST level the reversal enables
nothing new — N1's native-client monkeypatch and N2's attested OS-level firewall are process-wide
backstops indifferent to where an object was constructed or who wired it, so even a fixture wiring
a mis-scoped write-capable object into an exercised component cannot reach the real network under
pytest. **The gap is production/script level only**, which is exactly what D2 and D3 close.

**Rejected alternative (A): construct the client inside `exec/write_transport.py`.** It keeps E0's
path classification for free, and it costs the E0-INERT narrowing, the member allowlist, a second
token bucket unless the singleton is threaded through anyway, and a permanent exception to the one
guarantee that currently makes NO-SEND a property of the tree. Documented so the choice is
re-makeable, not so it is re-made.

**Everything below therefore applies ONLY IF a reviewer prefers alternative (A).** It is retained
in full because the decision above is a judgement, not a proof, and the reviewer who reverses it
must not have to re-derive the specification.

**CRITICAL (conditional on alternative A) — the E0-INERT narrowing, specified exactly, because the
under-specification IS the defect.** Revision 0 said "model it on `EXEC_ASYNC_LIFECYCLE_MODULES`" and stopped. That set
exempts exactly ONE prefix:

```
banned_prefixes = (
    NETWORK_IMPORT_PREFIXES - {"asyncio"} if async_permitted else NETWORK_IMPORT_PREFIXES
)                                            # test_execution_egress_firewall_guard.py:1863-1865
```

Every real transport prefix stays banned even for the async-permitted module. A write transport
needs a real one, and an implementer cloning the pattern would write `- NETWORK_PERMITTED` with
`NETWORK_PERMITTED` set to whatever made the test green. **Therefore, committed now:**

1. **The permitted prefix is `nautilus_trader.core.nautilus_pyo3` — and it must be described
   honestly, because Revision 1's phrase "the single permitted import" invited a reader to
   picture a narrow HTTP shim. It is not one.** That module is a ~860-symbol compiled Rust
   surface which, besides `HttpClient` (`$NT/core/nautilus_pyo3.pyi:5416`), exposes
   **`WebSocketClient` (`:5547`)**, **`SocketClient` (`:5587`) — raw TCP, which this repo's own
   barrier file calls "entirely unguarded" (`test_execution_egress_firewall_guard.py:134-135`)**
   — and complete execution-client configs for **other venues entirely**
   (e.g. `InteractiveBrokersExecClientConfig`, `:10192`). Permitting the PREFIX does not
   constrain which SYMBOL gets instantiated.
   It is chosen anyway, because the alternatives are worse: it is the client the read path
   already uses, it is rate-limited and TLS-fixed in Rust, and adding a second HTTP stack to the
   process would be a new failure mode for no gain. But a prefix exemption alone is **not
   sufficient**, which is why constraint 1b exists.

   **1b. A MEMBER-LEVEL allowlist, because the evasion idiom is already in this codebase.**
   E0-INERT's native-client check inspects **only `ast.ImportFrom` aliases**
   (`test_execution_egress_firewall_guard.py:1880-1889`), so
   `from nautilus_trader.core import nautilus_pyo3` followed by attribute access trips nothing —
   and that is exactly the form the read path uses (`transport.py:36`, with the module docstring
   at `:21` saying the client "is looked up as `nautilus_pyo3.HttpClient` at construction time"
   deliberately). Nothing in C1-C4 or the prefix equality constrains it. **Therefore:** an exact
   member allowlist for `write_transport.py`, in the idiom of `EXEC_PERMITTED_COROUTINE_NAMES`
   (`:1576`) — the ONLY `nautilus_pyo3` member that module may reference, by attribute or by
   name, is **`HttpClient`**. *RED:*
   `test_the_write_transport_references_exactly_one_pyo3_member` (an AST scan of every
   `ast.Attribute` whose value resolves to the `nautilus_pyo3` name, asserting the referenced-set
   **equals** `{"HttpClient"}`); **non-vacuity:** plant `nautilus_pyo3.SocketClient`,
   `nautilus_pyo3.WebSocketClient` and an `InteractiveBrokers*` reference in that module and each
   must fire.
   `EXEC_NETWORK_TRANSPORT_MODULES = frozenset({"src/breezy/adapters/polymarket_us/exec/write_transport.py"})`,
   and the computation becomes an explicit two-set subtraction with each subtrahend a literal:
   `- {"asyncio"}` for async-permitted, `- {"nautilus_trader.core.nautilus_pyo3"}` for
   network-permitted. **`asyncio` is NOT implied by network permission** and must be granted (or
   not) separately.
3. **Strengthening — an EQUALITY on the residual, not a subtraction a reviewer must trust:**
   `test_e0_inert_the_write_transport_may_import_exactly_one_network_prefix` asserts
   `banned_prefixes_for(write_transport_path) == NETWORK_IMPORT_PREFIXES - {"asyncio", "nautilus_trader.core.nautilus_pyo3"}`
   — an exact set, so widening it later is a visible diff. **Non-vacuity:** plant an
   `import httpx` in that module and E0-INERT must still fire; plant it in a second module beside
   it and E0-INERT must fire there too.
4. **Strengthening — a closed coroutine inventory** for the module, in the shape of
   `EXEC_PERMITTED_COROUTINE_NAMES` (`:1576`), containing exactly the transport's one public
   coroutine.

**CRITICAL — containment made structural, four commitments.** Revision 0 relied on convention.
Three verified routes bypass it: E0-NOSEND inspects only functions named in
`ORDER_LIFECYCLE_COROUTINES` (`:1820`), so `_connect` or `_publish_account_state` could call the
transport; no importer allowlist exists, so any module may import it; and B4 fires only on
literal `POST`/`PUT`/`PATCH`/`DELETE` and attributes named exactly `post`/`put`/`patch`/
`delete`/`request` (`test_polymarket_us_readonly_guard.py:149-150`), so a wrapper named
`send_signed` or `execute` evades it. Therefore:

- **(C1) One public method, name pinned in an exact-set test** — the same idiom as the coroutine
  inventory. The transport exposes exactly one public callable and the test asserts the module's
  public surface **equals** that one name.
- **(C2) The module and its class join `BANNED_EXEC_TRANSPORT_MODULES` (`:1612-1621`) and
  `BANNED_EXEC_TRANSPORT_NAMES` (`:1626-1634`)**, so no *other* module under `exec/` may import
  it — including `client.py`, until R-7 narrows that deliberately with its own strengthening.
  This is a **widening of a ban list**, i.e. a strengthening, not a narrowing.
- **(C3) An importer allowlist**: an exact-path set naming the only modules permitted to import
  the transport, scanned over `EGRESS_SCAN_ROOTS`. At R-6.5 that set is **empty** — the module
  ships with **zero importers** — and R-7 adds exactly one, `exec/client.py`, in its own commit
  with its own non-vacuity proof. Non-vacuity here: plant an importer anywhere and the test must
  fire.
- **(C4) No query argument** on the write callable, exactly as R-6.5P (see above).

**Barrier enumeration — CORRECTED in Revision 3.** Revisions 1-2 named N2 and B4 and stopped;
§3 W shows that is systematically under-scoped. The full set for R-6.5P *and* R-6.5:

| Barrier | Trips because |
|---|---|
| N2 exact-set pin (`:705-721`) | a new classified module appears; **widen the list, never relax the `==`** (L-12). |
| E1 `_EGRESS_MODULE_BASENAMES` (`:176-186`) | **Revision 4: OPTIONAL, and it pays for nothing.** N2-ABORT already fires via W's `factories.py` E2 row (`:733`), and E1 carries no restriction. Add it for audit-trail visibility if desired; do **not** book it as a compensating control. |
| **D2 — `transport.py` member allowlist** (new constant) | the actual import-shape control at the construction site; equality over the real member set, excluding `SocketClient`/`WebSocketClient`/foreign exec configs. |
| **D3 — POST-builder caller pin** in `BARRED_CALLEES` (`test_polymarket_us_readonly_guard.py:401-405`) | the capability-minting function, one caller, scanned **repo-wide**. |
| B4 `find_write_egress_violations` (`:257-292`) | the write verb; exact-path allowlist, both-direction non-vacuity. |
| `CAGE_RULE_PINS` **equality** (`test_cage_rule_constants_are_pinned.py:780`) | **every** new constant — the B4 allowlist frozenset, the importer allowlist, and (under alternative A) `EXEC_NETWORK_TRANSPORT_MODULES` and the member allowlist — must be registered, or the equality fails. |
| `test_the_cage_grants_exactly_one_exemption` (`:808`) | a **count** pin: **each allowlist ENTRY** trips it, not just the constant. R-6.5P adds one, R-6.5 adds another. |
| `test_every_cage_exemption_is_an_exact_path_not_a_prefix` (`:800`) | already mechanises this plan's "exact path, never a prefix" rule — inherited, not invented. |
| widened/narrowed-neighbour tests (`:714`, `:721`) | inherited automatically by every new pin. |
| `test_p1_no_module_rebinds_a_pinned_constant…` (`:900`) | scanned across `src`, `scripts` and `tests`. |
| E0-INERT + its member allowlist | **only under alternative (A)**. Under the shared-injection decision above, untouched. |

**Placement, and the alternative recorded rather than assumed.** The transport lives under
`exec/` so E0 classifies it by path. `scripts/venue/` would keep E0-INERT intact but is not an
option for a *shipped* transport, because the trading process must be able to import it at R-7.
The R-6.5P/R-6.5 split is precisely what lets the repo have both: the early evidence with no
`src/` write capability, and the shipped capability only when its consumer exists.

---

### R-7-PRE — close the risk engine's no-account fail-open — **PORTABLE** — *hard precondition of R-7*

**Promoted from Revision 0's OQ-G, because filing it as a question was wrong.** It is not
unknown; it is verified and unmitigated.

`$NT/risk/engine.pyx:688-689` returns `True` — **order allowed** — when
`self._cache.account_for_venue(...)` is `None`, with the source's own comment calling it a
"Temporary early return". Today R-4's blanket refusal of every order masks it entirely. **R-7
removes that net**: the moment `_submit_order` has a real body, an account-registration race — a
slow `/v1/account/balances`, a reconnect, a cache flush — silently allows an order through an
immutable framework path that nothing else in this plan closes. Nautilus is immutable, so the
denial must happen **upstream** of that fast path.

**Done when:** a contract test drives a `SubmitOrder` with no cached account and asserts the
order is DENIED, and asserts the denial originates **upstream** of `_check_orders_risk_for_account`
— i.e. from `TradingState.HALTED` (`$NT/risk/engine.pyx:559`) or from Breezy's own
`_submit_order` precondition (`exec/client.py:1300-1304`), not from the notional cap.
**Non-vacuity:** remove the upstream denial and the order must be ALLOWED, proving the fail-open
is real and that the test is measuring the mitigation rather than an accident.
## 4. The `calculate_account_state` branch: which one this plan assumes, and why that is safe

The brief is right that this is process-global and that Breezy's own backtest flips it. Verified
end to end:

- `Portfolio.update_order` returns before touching any balance unless the flag is set
  (`$NT/portfolio/portfolio.pyx:502` — `if not account.calculate_account_state: return`).
- The flag defaults `False` at account construction (`$NT/accounting/factory.pyx:128`,
  `_ISSUER_ACCOUNT_CALCULATED.get(issuer, False)`), keyed on `AccountId.get_issuer()`, which is
  everything before the first `-` (`$NT/model/identifiers.pyx:980`).
- `BacktestExecutionClient.__init__` calls `AccountFactory.register_calculated_account(exchange.id.value)`
  when `frozen_account` is false (`$NT/backtest/execution_client.pyx:83-84`), and Breezy's
  harness passes `frozen_account=False` (`src/breezy/runtime/backtest_harness.py:768`) with
  `venue=POLYMARKET_US_VENUE` (`:713`).
- **The issuer collides exactly.** `POLYMARKET_US_VENUE = Venue("POLYMARKET_US")`
  (`symbology.py:110`); `POLYMARKET_US_CLIENT_NAME = "POLYMARKET_US"` (`factories.py:107`);
  R-4 builds `AccountId(f"{client_id.value}-{account_number}")` (`exec/client.py:535-537`), whose
  issuer is `"POLYMARKET_US"`. Same string.
- **There is no way back (N9):** `deregister_calculated_account` does not exist (0 hits;
  positive control `deregister_cash_borrowing` = 1 at `$NT/accounting/factory.pyx:102`).
  Note also that `register_calculated_account` guards against `_ISSUER_ACCOUNT_TYPE`, not
  `_ISSUER_ACCOUNT_CALCULATED` (`:76-78`), so repeat registration does **not** raise.

**The branch this plan assumes: `calculate_account_state is False`, in the live process.**

**Why that is safe in-process, structurally rather than by luck:** the `breezy-trade` process
builds a `TradingNode`, never a `BacktestEngine`; `register_calculated_account` appears nowhere
under `src/` (only `backtest_harness.py` reaches it, transitively, via `add_venue`); and
`build_trade_node_config` constructs no venue. Consequently, in production
`Portfolio.update_order` never debits the balance for a reconciled fill, and the venue's own
published balance is authoritative — as R-4's contract test already records
(`tests/contract/test_exec_client_reconciliation_contract.py:494-537`).

**Why this plan nonetheless refuses to leave it as an assumption.** In the **test** process the
branch is genuinely indeterminate: `pytest-randomly>=3.16` is a dependency (`pyproject.toml:27`)
and ten test modules build a backtest engine, so whether the flag is set when a given contract
test runs is a function of the random seed. R-4's existing pin handles this by asserting *both*
branches. **R-6 makes it a checked precondition instead of an assumption:**
`test_the_exec_account_is_not_a_calculated_account` asserts the flag is `False` at the wiring
site, and the client **latches a refusal** if it is `True`. That converts the parent plan's
"if it is ever flipped True, that is the signal to build a post-reconciliation re-publish"
(`EXEC_SPINE_2026-09-01.md:422-425`) from a note into a mechanism, at the cost of one boolean
read. Nothing in R-5R, R-6a/c/d/e, R-6.5P or R-6.5 reasons about a balance without going through it.

---

## 5. The credential and signing surface, and a success predicate that cannot repeat the old confusion

**Credentials already exist and are not created by any increment here.**
`~/.config/breezy/polymarket.env` (0600, 7 lines, mtime 2026-09-01) plus
`~/.config/breezy/polymarket_us_secret.key`. The env-var names are
`POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY`, `POLYMARKET_US_SECRET_KEY_FILE`
(`src/breezy/adapters/polymarket_us/credentials.py:37-39`). Ed25519; the loader accepts both the
32-byte seed and the 64-byte `seed || public` form (`signing.py:157-182`), matching the venue SDK.
**No increment here commits, echoes, logs, or writes a credential**, and
`Ed25519RequestSigner.__repr__` already returns `REDACTED` (`signing.py:285-286`).

**How a signing probe proves auth without any order path existing.** *(This predicate
governs R-6.5P, which now runs early as an evidence-only script; R-6.5 inherits it unchanged.)*

`POST /v1/orders/open/cancel` is a **cancel-all** endpoint, not an order-submission endpoint. It
cannot open exposure. It *can* be operator-destructive on a non-flat account — `slugs` is
OPTIONAL in `CancelAllOrdersParams` (`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py:153-156`),
so an ignored or malformed `slugs` degrades to cancelling every resting order. **Whole-account
flatness, proven by an unfiltered `GET /v1/orders/open` immediately before the first POST and
immediately after the last, is what makes it safe — not the verb.** No `/v1/orders` POST body is
ever constructed, and neither R-6.5P nor R-6.5 lands an `_submit_order` body: R-7 does.

**The success predicate, written so the standing repo failure cannot recur.**

The standing finding is that four earlier authenticated smoke runs recorded FAIL, and those
verdicts turned out to be failures on **quote count** — a data-volume observation — not on
authentication. The predicate must therefore be stated over the *authentication outcome of a
named request*, never over a downstream count, and it must have an explicit third value.

For each of the two signed POSTs (`path_only`, `path_with_query`) record a triple
`(http_status, venue_error_code, canonical_variant)` and classify:

| Predicate | Meaning | Recorded as |
|---|---|---|
| status is a 2xx | the signature verified for that variant | `AUTH_OK` |
| status is 401/403 **and** the body carries a signature/authentication error code | the signature did not verify for that variant | `AUTH_REJECTED` |
| status is 401/403 with **no** recognisable auth error code | ambiguous — could be authorization, not authentication | `INCONCLUSIVE` |
| status is 4xx other than 401/403 | request was **authenticated** and rejected on content — this **is** an `AUTH_OK` for signing purposes and must be recorded as such | `AUTH_OK (content-rejected)` |
| status is 5xx, or the transport raised | says nothing about signing | `TRANSPORT_FAULT` |
| no response at all within the timeout | says nothing about signing | `TRANSPORT_FAULT` |

**How a failure is distinguished from a network fault:** by the class above and by the
requirement that a `TRANSPORT_FAULT` **never** produces a signing verdict. This is exactly what
the two distinct write-path error types (`VenueWriteTimeoutError` / `VenueWriteTransportError`)
are for — the read path collapses them (`transport.py:342-348`) and must not be changed.

**And the anti-recurrence clause, stated as a rule the artifact must satisfy:**

> The probe artifact records a signing verdict **only** from the classification table above.
> It may **not** derive a signing verdict from any count, any row total, any byte length, or any
> downstream data volume. A run that returns `AUTH_OK` and zero useful data records
> `AUTH_OK` — with the data question filed separately. Mechanised by a test that plants an
> artifact whose auth field is `AUTH_OK` and whose row count is 0, and asserts the reported
> verdict is `AUTH_OK`. (L-8's amendment: a status code, a byte count and a non-empty response
> are all compatible with zero usable data — and the converse, which bit us, is that zero usable
> data is compatible with working auth.)

**OQ-2's outcome, and both branches:** if `path_only` alone is accepted, the shipped default
(`build_canonical_path_without_query`, `signing.py:128`) is correct and R-7 changes nothing. If
`path_with_query` alone is accepted, the default flips and every read path's signature changes
too — which is why the query half is worth closing at R-5R, weeks earlier and for free. If both
are accepted the venue does not verify that segment, and the third canonical builder (the one
consuming `CanonicalRequest.body`, `signing.py:122`) becomes the only remaining question.

---

## 6. Reachability — and the honest admission that this plan's end state is NOT the goal state

**L-3 is binding on this plan too, and Revision 0 violated it in exactly the way it accused the
parent plan of violating it.** Revision 0's walk ended `... → R-9 → *first realized-PnL row* →
accumulate n → BCa lower bound → **goal**`. The arrow "→ accumulate n →" concealed an
undecomposed workstream, which is L-3's precise signature: *work that has never been decomposed
is work that never appears on the critical path.* Corrected here.

**The goal state** (parent plan §Goal state): *positive ROI observed from real, very small
marketable orders, with the confidence-interval lower bound clearing break-even.*

**What the walk actually reaches.** `R-1..R-4 (landed)` → `W` → `R-5R` → `R-6.5P` → `R-6a` →
`R-6c` → `R-6d` → `R-6e` → `R-7-PRE` → `R-6.5` → `R-7` → `R-8` → `R-9` terminates at:

> **ONE real, manually-placed, filled, reconciled order, closed by settlement into exactly one
> realized-PnL row.**

That is a proven *order path* and a proven *measurement device*. **It is not one ROI sample.**
The parent plan says so itself about R-8: "This proves the order path — **it is not an ROI
sample**, and no ROI claim may cite it" (`EXEC_SPINE_2026-09-01.md:758`).

**Why it cannot be more than that: the node loads no strategy, and this plan re-pins that.**
`strategies=[]` is pinned at `node_config.py:225` (recorder), `:476` (quote tape) and `:655`
(trade), `exec_algorithms=[]` beside it, and **W deliberately re-pins both**
(`test_the_trade_node_config_still_declares_no_strategies_and_no_exec_algorithms`). No
`ImportableStrategyConfig` for any Breezy strategy exists on the trade path. So no increment
between here and R-9 can ORIGINATE an order; R-8's single order is placed by hand with an
operator present.

### The missing workstream, decomposed, ranked by calendar

| # | Workstream | Why it is not in this plan | Calendar |
|---|---|---|---|
| **S-1** | **Strategy origination in the live node.** An `ImportableStrategyConfig` for a chosen strategy, its `external_order_claims` (needed by R-9 anyway, `$NT/trading/config.py:91`), instrument-id wiring, and the live-vs-backtest config split. | Undecomposed anywhere in the repo. It is the *second* long pole and has the same invisibility profile L-3 describes. | weeks, unstarted |
| **S-2** | **Un-caging the node.** Flipping `strategies=[]` is a barrier-visible change: the read-only cage is asserted as *declared, not defaulted* (`TestTheReadOnlyCageIsDeclaredNotDefaulted` reads the call). Needs its own increment and its own paired-barrier work. | Deliberately out of scope — it is the change that makes the process able to trade unattended, which is a different risk class from everything here. | days, gated on S-1 |
| **S-3** | **Operator enablement.** `BREEZY_TRADING_ENABLED == "1"` exactly (`safety.py:583`), plus the two reserved values. | **Operator-only. Not ours to schedule, plan, or default.** | operator |
| **S-4** | **Sample accumulation.** ~245 resolved offered trades to separate a true 5% from 12% (`docs/core/PROGRESS.md:63-73`); the R-9 BCa estimator needs a sample to run on. | Pure elapsed time; no code. | **plausibly 1.5+ years** |
| **S-5** | **The candidate-#2 / K1 verdict**, which decides whether any strategy is worth loading. K1 is measured at n=0 with the population arriving on the clock (`docs/core/PROGRESS.md:198-200`). | Elapsed capture, not code. | ~9-20 days for the viable ask bands |

**What this ranking actually argues.** S-4 dominates in wall-clock by two orders of magnitude
and it **cannot start until S-1 → S-3 are done, which cannot start until R-8 exists**. So the
spine is not competing with the strategy work; it is upstream of the strategy work's own
measurement. That is the reachability argument for building it now — and it is a *weaker* claim
than Revision 0 made, because it concedes the spine alone never reaches the goal.

### What W + R-5R + R-6* bring closer, concretely

- W is the **first time any Nautilus risk cap is enforced in the trading process.** Today
  `build_trade_risk_engine_config`'s `max_notional_per_order` (`node_config.py:544-546`) is
  configured and inert.
- W is the first live exercise of R-4's entire design: balance parse, position mapper, the
  three-step `avg_px_open` resolution, the never-`None` mass-status contract, thread affinity.
  All of those are proven only against fixtures today.
- R-5R closes OQ-B, a hard precondition of R-6.5P and therefore of R-7 and everything after.
- R-6a/c/d/e are preconditions of R-7 (the guard must not refuse reconciliation legs) and of R-9
  (the claimed-`ClientOrderId` exemption), and R-6e finally gives the two operator-reserved
  controls a home — an open consequence since 2026-08-30 (`docs/core/PROGRESS.md:27-33`).

### What they do NOT bring closer — plainly

- **None of them moves the strategy verdict by one basis point.** Candidate #2 is 12.3% against
  a 6.285% break-even (~1.9x), the single resolved live event **LOST**, and adverse selection is
  unsettled (`docs/core/PROGRESS.md:63-73`).
- **None of them produces a realized-PnL row.** That is R-9, behind R-7 and R-8.
- **None of them makes the node able to originate an order.** That is S-1/S-2, which no plan in

### One more thing this plan must not claim confidence about

**R-3's report mappers have still never met a real payload, and as of 2026-09-02 they cannot.**
Both entries in `PRIVATE_READ_PATHS` (`exec/endpoints.py:83-86`) are unreadable:
`/v1/account/balances` → 500 (grpc 13 INTERNAL) and `/v1/portfolio/positions` → 503 (grpc 14
UNAVAILABLE). So `parse_account_balances`, `parse_position_status_report` and
`derive_position_cost_basis` are exercised **only against fixtures authored from a type snapshot
that is demonstrably ahead of the deployed venue** (§3 R-7 note). Any increment whose confidence
rests on those mappers being correct — W's done-predicate above all — must say so, and W's first
live run is the first evidence either way. **This is L-8's shape one layer up: a green test suite
over hand-written fixtures is compatible with a mapper that has never seen the real thing.**

---
  this repo currently decomposes.
## 7. Sequencing judgement — is building this NOW right?

**The case for stopping the spine and doing strategy work instead.** Candidate #2 is ~1.9×
break-even with the single resolved live event a loss; adverse selection needs order 1.5 years to
settle; K1 is measured at n=0 with the population arriving on the clock. Every lock-strategy
family is dead (L-9, three refutations). One could argue the spine is a large investment against
an edge that may not survive its own first hundred trades.

**The case for advancing the spine anyway, which I find stronger, and here is why.**

3. **The spine advances at zero strategy risk.** W and R-6* make the node reconcile and refuse;
   `strategies=[]` stays pinned, so nothing in this plan can originate an order. If candidate #2
   dies tomorrow, none of W, R-5R, R-6a, R-6c, R-6d, R-6e or R-7-PRE is wasted — each is venue-
   and strategy-agnostic, and R-6a/c/d/e are tagged PORTABLE and verified so.

**The honest limit on all three, added in Revision 1.** Points 1-3 argue the spine should be
built; none of them argues it is *sufficient*. §6 now states the end state as one real order plus
one realized-PnL row, and names S-1/S-2 — strategy origination and un-caging the node — as an
undecomposed workstream that this plan does not touch and actively re-pins. **The strongest
honest form of the argument is: S-4 (sample accumulation, ~1.5 years) is the binding wall-clock
constraint, it cannot begin until S-1..S-3 are done, and those cannot begin until R-8 exists.
The spine is upstream of the clock, not on it.**

**But the parent plan's R-5 specifically does NOT dominate.** It builds a **write-capable network
surface under `src/`** whose only consumer (R-7) is several increments and one operator-gated
decision away. Its cost is not the code — it is the permanent narrowing of E0-INERT, the one
barrier that makes NO-SEND a property of the tree. Pay that when the consumer exists.

**And Revision 0 over-claimed the corollary.** It concluded that because the *capability* should
wait, the *question* must wait too. That conflated two things B4 and N2 already separate: a
`scripts/venue/` probe is covered by B4's write-verb rules (`test_polymarket_us_readonly_guard.py:124,169-172`)
and ships nothing importable. **R-6.5P therefore asks the venue question now and pays only the
allowlist narrowing the parent plan already scoped.**

**And a defect the sequencing question surfaced that outranks everything above.** The parent plan
lists R-4 as landed and moves on. R-4's client has **zero construction sites** and
`exec_clients={}` is still pinned. **The dominating increment is W.** It is small, it is the only
thing that makes every R-4 claim true of the running process, and it is the only increment here
that generates live venue evidence — exactly the input every later increment is starved of.

**Sequencing verdict (Revision 2): R-4P-1 → W → [R-5R-0, R-5R-3 immediately] → R-6a → R-6c →
R-6d → R-6e → {R-5R-1, R-4P-2, R-6.5P: venue-gated} → R-7-PRE → R-6.5 → R-7.**

**The venue outage changes the sequencing argument, and in a direction worth stating.** Revision
1 argued the spine should advance because it is the long pole. Revision 2 adds that the private
surface being down makes the *venue-evidence* half of the spine un-advanceable at any speed —
which leaves the LOCAL half (R-4P-1, W's code, R-6a/c/d/e, R-7-PRE) as the only work that can
progress at all. That is a stronger argument for doing it now, not a weaker one: it is the only
thing not blocked. The corollary is that no schedule may be built on R-5R-1, R-4P-2 or R-6.5P
until OQ-K resolves, because one of its two branches is a venue-support conversation this repo
cannot have. **What I would not accept is
building R-5-as-written next**: its precondition (OQ-6/OQ-B) is open, so by the parent plan's own
text it cannot run at all.
---

## 8. Risks, sharpest first

0. **R-4 SILENTLY RECONCILES PAGE 1 OF ITS OWN POSITIONS — a latent defect in landed code, and
   the sharpest item in this plan.** *Concrete failure:* `GetUserPositionsResponse` is a CURSOR-
   paginated envelope carrying `nextCursor` and `eof`
   (`sdk_snapshot/.../types/portfolio.py:48-50`), and `GetUserPositionsParams` carries
   `market`/`limit`/`cursor` (`:36-42`). R-4's `_declared_positions` (`exec/client.py:881-894`)
   reads `payload["positions"]` and stops. **Measured: `eof`, `cursor`, `nextCursor` and `page`
   occur ZERO times across `exec/client.py`, `exec/reports.py` and `exec/endpoints.py`.** So on
   any account whose position count exceeds the page size, Breezy reconciles a PREFIX of its own
   book, reports less exposure than it holds, and — because the missing positions are simply
   absent rather than refused — **latches no refusal at all**. Every cap then sizes against a
   portfolio that does not contain risk the account is carrying, which is precisely the failure
   R-4's own docstring says exclusion would cause (`exec/client.py:100-111`) — arriving by a
   different door. It is silent, it fires on ordinary data, and it produces a plausible number.
   *Mitigation:* **§3 R-4P**, in two steps, the first of which is small and lands before W.

1. **R-4's client is never constructed, so every downstream increment builds on an unexercised
   design.** *Concrete failure:* R-6a, R-6.5P, R-6.5 and R-7 land on top of it, and the first live
   connect refuses on a balance or position shape no fixture had, latching a node-global refusal
   that denies every order for a reason discoverable on day one. *Mitigation:* W first, run live,
   with the §3-W success predicate (which distinguishes healthy from latched — see risk 5).
2. **W has a SILENT NON-START path that exits zero.** *Concrete failure:* R-4's
   `_open_state_store` **raises** on a non-durable store (`exec/client.py:640`). That exception
   is caught by `_on_task_completed` (`$NT/live/execution_client.py:212-226`), which logs it and
   **skips `actions`** — so `_set_connected(True)` never runs, `check_connected()` stays `False`,
   `_await_engines_connected()` times out and merely warns (`$NT/system/kernel.py:1024,1310-1316`),
   and `start_async` **returns without starting the trader** (`:1024`). Breezy's own
   `_exit_code_for_completed_run` (`runtime/trade_cli.py:127-144`) reports only a *market-data*
   fault, so the process exits **`EXIT_OK`** having never traded and never reconciled. A
   supervisor sees success. *Mitigation:* W RED test
   `test_a_failed_connect_is_observable_and_does_not_exit_zero`. **CLOSED in Revision 3** — W
   shipped `src/breezy/adapters/polymarket_us/exec_fault.py`, a lock-guarded, first-fault-wins
   latch reset at run start and checked **before** the market-data fault in
   `_exit_code_for_completed_run`, so an exec-side `_connect` failure now exits non-zero instead
   of `EXIT_OK`. Independently reviewed as sound; retained as a risk record, not an open item.
3. **Narrowing E0-INERT by cloning the async pattern grants far more than intended.**
   *Concrete failure:* `banned_prefixes = NETWORK_IMPORT_PREFIXES - {"asyncio"} if async_permitted
   else NETWORK_IMPORT_PREFIXES` (`test_execution_egress_firewall_guard.py:1863-1865`) subtracts
   exactly ONE prefix. A write transport needs a *real* network prefix, and an implementer
   cloning the shape writes `- NETWORK_PERMITTED` where `NETWORK_PERMITTED` is whatever made the
   test green — plausibly the whole ten-element set. Every barrier named in Revision 0 stays
   green while `exec/` regains leave to import `httpx`, `socket`, `ssl` and the pyo3 client.
   *Mitigation:* §3 R-6.5 names the single permitted prefix and requires an **equality** test on
   the residual banned set, not a subtraction a reviewer must trust.
4. **Write-transport containment is conventional, not structural.** *Concrete failure, three
   independent routes:* (a) E0-NOSEND's callee allowlist only inspects functions named in
   `ORDER_LIFECYCLE_COROUTINES` (`test_execution_egress_firewall_guard.py:1820`), so
   may call the transport with every barrier green; (b) any module *outside* `exec/` may import
   it, since no importer allowlist exists; (c) **inside** an allowlisted module, B4 does not fire
   at all — by design, since the allowlist exempts it from V1-V4 wholesale — so nothing there
   constrains how many write-capable entry points the module grows.
   **CORRECTION TO REVISION 1, against my own text.** Revision 1 wrote that "a wrapper named
   `send_signed` or `execute` evades B4 entirely". **That is false and the record is corrected
   here.** B4's V3 fires on the ATTRIBUTE NAME of the internal verb call, not on the wrapper's
   name, and `nautilus_pyo3.HttpClient` has no verb-hiding synonym — its entire send surface is
   `request` (`$NT/core/nautilus_pyo3.pyi:5426`), `get` (`:5436`), `post` (`:5444`) and `patch`
   (`:5453`), and `request`/`post`/`patch` are all in `_WRITE_ATTRS`
   (`test_polymarket_us_readonly_guard.py:150`). So for any NON-allowlisted module a wrapper
   evades nothing. C1's real contribution is therefore **capping write-capable entry points to
   one auditable name inside the module where B4 is deliberately silent** — which is a narrower
   and more honest justification than Revision 1 gave it, and it argues for C1 and C3 more
   strongly, not less.
   in §3 R-6.5.
5. **W cannot tell success from failure.** *Concrete failure:* "every submitted order is denied"
   is satisfied identically by a healthy client and by one that timed out loading instruments
   (`exec/client.py:659`) and now denies everything for the wrong reason. This is the same
   anti-recurrence discipline Revision 0 wrote for R-6.5 and omitted for W. *Mitigation:* W's
   done-predicate asserts `trading_refusals == ()`, `instrument_provider.count > 0`, and the
   settled-position list, not just the denial.
6. **`degrade()` gets wired to something fatal.** *Concrete failure:* a venue-priced foreign
   position — ordinary on an account the operator has also touched by hand — latches a refusal,
   degrades the client, and a supervisor exits the process. L-6 verbatim: a signal with **25**
   writers, several routine, promoted to a kill switch. *Mitigation:* the exact-set `_refuse`
   test and the full 25-site triage in §3 R-6c, plus
   `test_degrading_the_exec_client_does_not_stop_the_node`.
7. **The risk engine fails OPEN with no account, and R-7 removes the net that hides it.**
   *Concrete failure:* `$NT/risk/engine.pyx:688-689` returns `True` — order allowed — when
   `account_for_venue(...)` is `None`. Today R-4's blanket refusal masks it. The moment R-7 gives
   `_submit_order` a real body, an account-registration race (a slow `/v1/account/balances`, a
   reconnect, a cache flush) silently ALLOWS an order through an immutable framework path that
   nothing in this plan closes. *Mitigation:* **R-7-PRE**, a hard precondition, §3.
8. **A signing FAIL is recorded when the venue merely returned nothing useful.** *Concrete
   failure:* the probe returns 2xx with an empty payload, an implementer reads a row count and
   records FAIL, and R-7 is blocked on a verdict that was never about signing — the exact
   confusion four prior smoke runs produced. *Mitigation:* the §5 classification table and its
   anti-recurrence clause, mechanised by a test.
9. **A query smuggled into a signed path.** *Concrete failure, two severities:* on the READ path
   (`PrivateRead.path`, `exec/client.py:347`) a paginated `?limit=100` is signed as if it were a
   path segment and every read 401s — annoying, and misreadable as an auth regression. On the
   WRITE path the same mistake is a **misfired cancel on a live account**: a cancel-all POST that
   grows a filter parameter signs one string while the venue verifies another, and the venue's
   handling of the unrecognised filter is undefined — `slugs` is optional
   (`sdk_snapshot/.../types/orders.py:153-156`), so the documented degradation is cancel-ALL.
   *Mitigation:* W's bare-path test, and R-6.5's write callable carries **no query argument at
   all**, the same shape `PrivateRead` has.
10. **A transient venue blip becomes a restart-only latch.** *Concrete failure:* a 429 during
    boot latches DURABLE; the node runs for hours refusing every order while the venue is fine.
    *Mitigation:* R-6d — limited to HTTP-status classification, because the read path collapses
    timeouts (`transport.py:343-348`) and the parent plan forbids changing it.
11. **`calculate_account_state` flips for this issuer.** *Concrete failure:* impossible in
    production (no `BacktestEngine` in `breezy-trade`); in **test** it happens at random under
    `pytest-randomly`, costing a debugging session on a non-defect. *Mitigation:* §4's checked
    precondition.
12. **W's factory turns the N2 exact-set pin red and someone relaxes it.** *Concrete failure:*
    `==` becomes a subset check to get green, and any execution-egress module can thereafter
    land silently. *Mitigation:* L-12 stated in the increment; the widening specified as a named
    row with its own non-vacuity check.
13. **The exec-engine config pin tests a hand-built config, not the shipped one.** *Concrete
    failure:* R-4's in-flight/interval pin asserts over a config constructed in the test. A later
    edit adding `position_check_interval_secs` to `build_trade_node_config` re-arms the
    settlement-zero landmine (`_create_flat_position_report`, `$NT/live/execution_engine.py:1022`)
    **with R-4's pin still green**. *Mitigation:* W moves the pin onto the real
    `build_trade_node_config` output.
14. **OQ-E stays unbounded and R-8 never runs.** *Concrete failure:* the spine completes and
    stops one increment short. *Mitigation:* R-5R attempts the docs bound early, so the shortfall
    surfaces at R-5R rather than at R-8.
## 9. Open questions — unresolved from source, marked as such

Revision 2 status after the 2026-09-02 live shape capture. Two of Revision 0's questions were
closed by reading in Revision 1; three new ones are opened by the venue's measured state.

| # | Question | Status |
|---|---|---|
| ~~OQ-A~~ | Is the exec client `RUNNING` when `_connect`'s refusals fire, so `degrade()` is legal? | **CLOSED — YES, by reading.** `NautilusKernel.start_async` calls `_start_engines()` (`$NT/system/kernel.py:1021`) BEFORE `_connect_clients()` (`:1022`). `_start_engines` calls `self._exec_engine.start()` (`:1270`), and `ExecutionEngine._start` (`$NT/execution/engine.pyx:666-668`) calls `client.start()` **synchronously**, driving the FSM to `RUNNING` (`$NT/common/component.pyx:1634`). Only then does `LiveExecutionClient.connect()` (`$NT/live/execution_client.py:243-249`) schedule `_connect`. |
| ~~OQ-H~~ | Is a pending-degrade recording needed? | **CLOSED — NO**, it depended on OQ-A. |
| **OQ-B** | Does an unfiltered `GET /v1/orders/open` return orders Breezy did not place? (= OQ-6) | **OPEN AND BLOCKED ON VENUE AVAILABILITY, not on engineering.** `/v1/orders/open` → **503 / grpc 14 UNAVAILABLE**, deterministic across 5 attempts over ~10 minutes (2026-09-02). Re-probe trigger in §3 R-5R. |
| **OQ-C** | Does `UserPosition.cost` include trading fees? (R-4 invariant 5) | OPEN, and now doubly so: `/v1/portfolio/positions` is **503**, so the shape has not been observed either. |
| **OQ-D** | Does the request body join the canonical signing string? (= OQ-2) | OPEN. Only a live POST answers. **Its query-half sibling is now probeable** — see OQ-M. |
| **OQ-E** | Venue minimum/floor taker fee in absolute USD? (= OQ-8) | OPEN. Blocking for R-8. |
| **OQ-F** | Is per-instrument refusal worth building? | Open as a question; **the increment is CUT** (§3 R-6b). |
| ~~OQ-G~~ | Does `TradingState.HALTED` dominate the no-account fail-open? | **PROMOTED to a hard precondition of R-7** (§3 R-7-PRE). |
| ~~OQ-I~~ | Source and restart-stability of `account_number`? | **CLOSED by W.** `ACCOUNT_NUMBER_ENV_VAR = "POLYMARKET_US_ACCOUNT_NUMBER"` (`src/breezy/adapters/polymarket_us/factories.py:171`), a required env var with **no default**, read once in `exec_config_from_env` (`:320`) — and correctly avoiding this repo's falsy-as-unset bug class. Restart-stability is the operator's shell export, the same arrival path as every other operator value (§3 R-6e). |
| **OQ-J** *(new)* | **How many pages does `/v1/portfolio/positions` return for this account, and what is the page size?** | OPEN, blocked with OQ-B. `GetUserPositionsResponse` carries `nextCursor`/`eof` (`sdk_snapshot/.../types/portfolio.py:48-50`) and `GetUserPositionsParams` carries `market`/`limit`/`cursor` (`:36-42`). **R-4 as landed reads page 1 and never inspects `eof`** — see §3 R-4P and risk 1. |
| **OQ-K** *(new)* | Is the private-surface outage TRANSIENT, or a PERSISTENT per-account condition (e.g. an unprovisioned clearing account)? | OPEN. `/v1/portfolio/positions` returned **200 on 2026-08-30** and **503 today**, which is consistent with both. Discriminator in §3 R-5R. **This is the single highest-leverage unknown in the plan right now**: one branch is a wait, the other is a venue-support conversation that nothing in this repo can resolve. |
| **OQ-L** *(new)* | Does **`POST /v1/orders`** exist, and does **`GET /v1/order/{id}`** exist? | OPEN — and **not** answered by the 501 that was measured. See §3 R-7 note: what was probed is `GET /v1/orders`, and in the SDK `/v1/orders` is the **POST create** path (`sdk_snapshot/.../resources/orders.py:26-31`); the single-order read is `GET /v1/order/{id}` — **singular** (`:40-42`) — which was **not probed**. |
| **OQ-M** *(new)* | Is the query string signed? (the GET-only half of OQ-D) | OPEN but **now unblocked**: `_probe_canonical_string` currently targets `PORTFOLIO_PATH = /v1/portfolio/positions` (`polymarket_us_auth_smoke.py:163`), which is 503. Re-point it at `/v1/portfolio/activities`, the one private path measured **200**. See §3 R-5R. |
## 10. Standing constraints this plan does not restate but is bound by

Nautilus is immutable. `allow_short=False` permanently (`strategy/weather_common/risk.py:139`);
long-only, taker-only. No operator-reserved value is assigned anywhere in this repo — the two
controls arrive from the operator's shell via `_require_operator_value`, and absence fails
closed. No safety, settlement, or contract test is weakened or deleted. Every barrier change is
a **widening** with a non-vacuity proof, never a relaxation (L-12). TDD is mandatory; RED output
is the change artifact. The gate is `scripts/ci/run_tests_no_egress.sh`, never bare pytest —
and note that the N2 session abort is **already armed today**, since `exec/` has held modules
since R-3; the parent plan's "from R-5 onward" (`EXEC_SPINE_2026-09-01.md:181-182`) is stale and
should be corrected there.

**A CLASSIFIER IS NOT A CONTROL.** Being classified determines which rules a module is
CONSIDERED BY; it never itself restricts. E1/E2/E3 membership adds a row to N2's exact-set pin and
feeds N2-ABORT's session gate (`find_execution_egress_modules`'s only consumers:
`test_execution_egress_firewall_guard.py:547`, `:715`, `:869`, `:898`) — and carries no import
rule, no member allowlist and no caller rule. **When a design moves a capability out from under a
restricting rule, the compensating control must be another RESTRICTING rule at the new location.**
A reclassification is bookkeeping, and crediting it as payment is how a *relocated* risk gets
recorded as an *eliminated* one. This plan did exactly that in Revision 3 and it took a security
review to catch; see §3 R-6.5, commitments D1-D5.

**A SECOND client, provider, or transport SHARES the first one's object graph by default.**
Nautilus's rate limiter is an in-process token bucket scoped to each `HttpClient` **object** —
`keyed_quotas`/`default_quota` are constructor arguments (`$NT/core/nautilus_pyo3.pyi:5416-5424`)
— while the venue enforces per **account**. So two clients are two buckets and up to **2x** the
intended request rate, worst exactly at startup when two instrument providers load together. The
shipped idiom is a module-level `@lru_cache(1)` singleton called from both factories:
`get_polymarket_http_client` (`$NT/adapters/polymarket/factories.py:42-43`) and
`get_polymarket_instrument_provider` (`:100-101`), used by the data factory (`:169`, `:178`) and
the exec factory (`:232`, `:246`); **13 of the shipped `adapters/*/factories.py` use `lru_cache`**.
**Any decision NOT to share must be argued explicitly against the per-account rate limit, in the
increment that makes it.** The trap is that the reasoning *against* sharing is locally sound —
`LiveExecClientFactory.create` is a stateless `staticmethod` with no channel to the data factory —
which is precisely why the singleton is module-level rather than passed. R-6.5's answer is in §3.

**Production type-narrowing never uses a bare `assert`.** Under `python -O` asserts are stripped
and the narrowing silently vanishes, so a construct that reads as a guarantee becomes a no-op in
exactly the deployment mode where nobody is watching. Use `cast` or a raise-based helper; the repo
already has both idioms. *(Test code is unaffected — `assert` is the test idiom and `-O` is not
used there.)*

**The SDK snapshot is NOT evidence of venue capability.** `docs/evidence/venue/polymarket_us/sdk_snapshot/`
documents `/v1/orders` (`resources/orders.py:26-31`), which the deployed venue answers **501 grpc
12 UNIMPLEMENTED** to a GET. The snapshot therefore **leads deployment**, and no increment may
cite it as proof that an endpoint exists, is routed, or behaves as typed. It remains excellent
evidence of *shape* (field names, types, envelopes) — which is how R-3 and R-4P legitimately use
it — and no evidence of *availability*. Availability is established only by a live probe, per
L-8's rule that a coverage claim cites an observation and never a document.

**Narrow excepts on every new error path.** `CancelledError` is a `BaseException` in Python 3.13
and must propagate. The write path's two new error types are raised from an explicit
`except (HttpError, HttpTimeoutError)` tuple — never `except Exception`, never
`except BaseException`. R-4 already applies this reasoning at `exec/client.py:741-745`
(`generate_mass_status` deliberately catching `Exception` and NOT `CancelledError`), and the
parent plan applies it to the R-7 latch (`EXEC_SPINE_2026-09-01.md:679-682`).

---

## 11. What Revision 4 changed, and why

Input: a **security review of Revision 3's containment reversal** — verdict ACCEPT WITH
CONDITIONS. The reversal stands; one of my justifications for it did not. Every claim below was
re-verified against the tree before acceptance, and three of the five conditions needed precision
corrections that are recorded with them.

| Change | Severity | Cause |
|---|---|---|
| **"Widening E1 pays for the reversal" REMOVED as an accounting fiction; honest accounting substituted** | **HIGH** | Verified: `find_execution_egress_modules` has four consumers — `:547`, `:715`, `:869`, `:898` — and carries **no** import, member or caller rule. Only E0-INERT restricts, and `test_e0_inert_is_scoped_to_the_exec_package` (`:2041-2046`) proves non-fire **using `transport.py`**, the very file the reversal routes construction into. And nothing was owed: `factories.py` is **already** E2-classified as of W (`:733`), so N2-ABORT fires either way. The reversal **eliminates two** risks and **gives up one** — the member-shape guarantee — which the plan had credited as paid. |
| **Five commitments D1-D5 added to R-6.5**, restoring the guarantee at the new site | **HIGH** | D1 names both modules (`transport.py` mints the capability; `factories.py` mints the injected closure — it references no pyo3 member in code, `:413` being a comment). D2 and D3 are load-bearing. |
| **D2 correction: the member allowlist is NOT `{"HttpClient"}`** | MEDIUM | `transport.py` legitimately references four members — `HttpClient`, `HttpError`, `HttpTimeoutError`, `Quota`. The rule is an **equality on the real set**; what matters is the exclusions (`SocketClient` `:5587`, `WebSocketClient` `:5547`, foreign exec configs `:10192`). A literal `{"HttpClient"}` would have failed on landing and invited someone to "fix" it by loosening the comparison. |
| **D3 accepted, with the read twin's protection correctly characterised** | HIGH | `_build_get_only_callable` has exactly one caller (`transport.py:325`) — by **module privacy, not by any rule**. So the POST builder needs a real pin: `BARRED_CALLEES` with an exact-path one-caller equality, scanned **repo-wide** (a fixture minting a write closure is invisible under `EGRESS_SCAN_ROOTS`). |
| **D4 correction: the test the condition asked me to twin does not exist** | MEDIUM | `test_the_wired_private_read_refuses_every_method_but_get` was invented by my own Revision-2 RED list. W shipped `…signs_exactly_one_get_over_the_bare_path` (`test_polymarket_us_factories.py:571`) and `…has_no_query_parameter_in_its_signature` (`:595`). There is no method-refusal test because **the closure has no method parameter** — `"GET"` is hardcoded at `factories.py:712`. The write twin is specified as structural absence, not refusal. W's RED list corrected to the shipped names. |
| **D4 corollary added: the write path needs its OWN signer** | **HIGH** | `sign_headers` raises for anything outside `PERMITTED_METHODS = frozenset({"GET"})` (`signing.py:84`, `:260-265`), so a POST closure **raises with the shipped signer**. The 2am resolution — adding `"POST"` to that frozenset — would convert every read-path signer in the process into a write-capable one. Named so it cannot be discovered under time pressure. |
| **Standing rule added (§10): a classifier is not a control** | MEDIUM | Generalises the finding: classification decides which rules consider a module, never what it may do. Crediting a reclassification as payment is how a relocated risk is recorded as an eliminated one. |
| Residual scoped: **production/script level only** | LOW | N1's monkeypatch and N2's attested OS firewall are process-wide and indifferent to construction site, so the reversal enables nothing new under pytest. |

**No condition rejected.** Three were sharpened against the tree (D2's literal, D4's premise, D3's
characterisation of the read twin), and the two load-bearing ones — D2 and D3 — are adopted as
posed. The review's core correction stands: I recorded a surrendered guarantee as a purchased one,
and the remedy is a restricting rule at the new site, not a revert.

---

## 12. What Revision 3 changed, and why

Input: **increment W was implemented and reviewed** (green: 5096 outcomes, 0 failures;
uncommitted pending one fix). Building a plan's own increment is the sharpest available test of
that plan, and it found one systematic error and one native idiom the plan had not anticipated.
Every item below was re-verified against the tree or installed source before acceptance.

| Change | Severity | Cause |
|---|---|---|
| **W's barrier list corrected from one barrier to four**, plus four inherited mechanisms enumerated | **HIGH** | I enumerated the barriers I had read, not the barriers that gate the change. `PERMITTED_EXECUTION_CLIENTS` (`test_polymarket_us_readonly_guard.py:734`) — whose docstring **literally read** "Factories stay banned outright — R-4 wires no client into a node" — its meta-pin (`test_cage_rule_constants_are_pinned.py:511,777`), and `TestTheReadOnlyCageIsDeclaredNotDefaulted` (`test_runtime_node_config.py:347`, including the build-site **count** at `:376`) all had to widen. A later increment citing "only N2 changes" as precedent would have under-scoped itself. |
| **R-6a / R-6c / R-6d / R-6e re-audited**; "none" replaced with the four-part basis on which it is none; R-6.5's list expanded to nine entries | HIGH | The suite is denser than this plan's prose assumed. Newly enumerated: the `CAGE_RULE_PINS` **equality** (`:780`), the exemption **count** pin (`:808` — **each allowlist ENTRY** trips it), the exact-path-not-prefix rule (`:800`, which already mechanises what R-6.5 was going to invent), the auto-inherited widened/narrowed-neighbour tests (`:714`, `:721`), and P1's repo-wide rebinding scan (`:900`). |
| **R-6.5 now answers "share or construct?" — SHARES, by injection — which DOWNGRADES the E0-INERT CRITICAL to conditional** | **CRITICAL** | The rate limiter is an in-process bucket scoped to each `HttpClient` object (`$NT/core/nautilus_pyo3.pyi:5416-5424`); two clients are 2x the intended rate against a per-account limit. Handing the write path an injected POST callable — R-4's own `PrivateRead` idiom — means `exec/` never imports `nautilus_pyo3`, so **the E0-INERT narrowing and C-A's member allowlist are not needed at all**, and `exec/` keeps its inertness absolutely. The cost (the POST object sits outside E0's path classification) is paid by **widening E1** — a strengthening — instead of narrowing an inertness rule. **This reverses the parent plan's security condition 5 and a reviewer should look at it deliberately;** alternative (A) is retained in full so reversing costs no re-derivation. |
| **R-6a's and R-6c's attachment point pinned**: `node.kernel.msgbus` after `node.build()`, **not** an `Actor` | MEDIUM | Keeps `actors=[]` (`node_config.py:697`) an untouched empty literal and keeps one wiring idiom. **Residual recorded:** the cage's per-field rule covers `strategies`/`exec_algorithms` (`test_runtime_node_config.py:377`) and `exec_clients` separately — **not** `actors` — so "the cage would have caught it" is unavailable for anything actor-shaped. |
| **Two standing rules added (§10)**: the shared-object-graph default, and no bare `assert` for production narrowing | MEDIUM | The first generalises the CRITICAL above, with the trap named: the reasoning against sharing is *locally sound* (`LiveExecClientFactory.create` is a stateless `staticmethod`), which is exactly why the singleton is module-level. The second: `-O` strips asserts, so a guarantee becomes a no-op in the one mode nobody watches (observed at `node_config.py:679`). |
| **OQ-I CLOSED**; **risk 2 CLOSED** | LOW | `ACCOUNT_NUMBER_ENV_VAR` (`factories.py:171`), read in `exec_config_from_env` (`:320`), required, no default. `exec_fault.py` closes the silent-`EXIT_OK` path. |

**What W's implementation confirmed sound, so later increments may rely on it:** store
thread-confinement survived the wiring; every barrier widening stayed a **full equality** rather
than degrading to membership — the audit found them *stricter* than this plan's prose described
(`exec_clients` is pinned to EXACTLY one entry, not "at least one"); and the `exec_fault` latch is
lock-guarded, first-fault-wins, reset at run start, and checked before the feed fault.

**The generalisable lesson, recorded because it will recur.** A plan's barrier list is not a
literature review — it is a claim about which mechanisms *gate the change*, and it must be derived
by asking "what would refuse this?" rather than by recalling what was read. Revisions 0-2 got this
wrong the same way three times across four increments, and only implementing one of them surfaced
it.

---

## 13. What Revision 2 changed, and why

Two inputs: a live read-only shape capture (2026-09-02) and a targeted re-review of Revision 1's
containment amendments (verdict: C-B and C-C closed; C-A and C-D correctly diagnosed but
incompletely closed). Every claim below was re-verified against source or against the capture
before acceptance.

| Change | Severity | Cause |
|---|---|---|
| **New increment R-4P** — cursor pagination on the private read, in two steps, landing before W | **CRITICAL** | Latent defect in LANDED code. `GetUserPositionsResponse` carries `nextCursor`/`eof` (`sdk_snapshot/.../types/portfolio.py:48-50`) and `GetUserPositionsParams` carries `market`/`limit`/`cursor` (`:36-42`); `eof`/`cursor`/`nextCursor`/`page` occur **zero** times across `exec/client.py`, `exec/reports.py`, `exec/endpoints.py`. R-4 reconciles **page 1** and calls it the book. Now risk 0. |
| The `PrivateRead`-vs-pagination collision **resolved explicitly**: a typed, charset-validated, keyword-only `cursor`, routed through the signer's `query_string` and never into `path`; page budget; five pinned constraints. Single-page-only adopted as the INTERIM (R-4P-1), rejected as the terminal design. | CRITICAL | The containment property was misnamed. It is not "the read takes no arguments" but "no free-form query is concatenated into the signed path". **C4 is unchanged** — it governs the write callable, which never paginates. |
| **R-5R rewritten as a TRIGGER, not a task** | CRITICAL | Private backend down, deterministic over 5 attempts: balances 500/13, positions 503/14, orders-open 503/14, `/v1/orders` GET 501/12; `/v1/portfolio/activities` **200**; public `/v1/markets` 200. Auth **PROVEN** (signed 200, unsigned 401, unknown-path 404/5). Blocked on availability, not engineering. |
| **R-5R-0 added — the RUNNER, which R-1 never landed** | HIGH | **Revision 1's "closing OQ-6 is an execution task with zero code" was my error.** `polymarket_us_shape_capture.py` has no `main()`, no `argparse`, no `__main__` and does no I/O; the smoke CLI takes only `--quote-window-secs`/`--evidence-dir`/`--skip-rate-limit-probe` (`:1276-1295`) and hardcodes `PORTFOLIO_PATH` (`:163`). Owner named; GET-only by construction; needs no B4 allowlist. |
| **OQ-K added and named the highest-leverage unknown**: transient outage vs persistent per-account condition, with two cheap discriminators and an escalation rule | HIGH | `/v1/portfolio/positions` was 200 on 2026-08-30 and 503 today. One branch is a wait; the other is a venue-support question no engineering resolves. |
| **R-6.5P gains a HARD SAFETY GATE**: refuse-to-run unless the pre-flight `GET /v1/orders/open` returns 200 with an empty list — plus an AST ordering assertion that both GETs bracket the POST | **CRITICAL** | C-D. Barriers make the capability's ARRIVAL unshippable-in-silence; they cannot prove the operation's DESTRUCTIVE SAFETY at runtime. And the flatness check's endpoint is **currently 503**, so absent the gate the first write would be a cancel-all at an unobservable account. |
| **C-A closed properly: a MEMBER-level allowlist** (`{"HttpClient"}` only) plus honest prose about what the prefix contains | **CRITICAL** | `nautilus_pyo3` is a ~860-symbol surface including `WebSocketClient` (`:5547`) and `SocketClient` (`:5587`, which the barrier file itself calls "entirely unguarded", `:134-135`) and other venues' exec configs (`:10192`). E0-INERT's native-client check inspects **only `ImportFrom` aliases** (`:1880-1889`), and the read path already uses the module-import-plus-attribute form (`transport.py:36`) that dodges it. The prefix equality was right; the prefix was not narrow. |
| **Risk 4(c) corrected AGAINST my own text** | MEDIUM | Revision 1 claimed a wrapper named `send_signed` "evades B4 entirely". **False.** V3 matches the internal verb attribute, and `HttpClient`'s whole send surface is `request`/`get`/`post`/`patch` (`$NT/core/nautilus_pyo3.pyi:5426,5436,5444,5453`), three of which are in `_WRITE_ATTRS`. C1's real contribution is capping entry points inside the module where B4 is deliberately silent. |
| **OQ-L added** — the 501 does NOT establish what it was read as | MEDIUM | What was probed is `GET /v1/orders`. In the SDK `/v1/orders` is the **POST create** path (`sdk_snapshot/.../resources/orders.py:26-31`); the single-order read is `GET /v1/order/{id}` — **singular** (`:40-42`) — and was **not probed**. So `POST /v1/orders` (R-7) and `/v1/order/{id}` (R-7's clearing protocol) both remain open. **L-11 binds venue gap claims exactly as it binds Nautilus ones.** |
| **OQ-M added and unblocked**: re-point `_probe_canonical_string` from the 503 positions path to the 200 activities path | MEDIUM | Runnable today, and it is a **hard precondition of R-4P-2** — pagination is the first thing in Breezy to put a query on a signed request. |
| **OQ-J added**; §6 gains "R-3's mappers have never met a real payload" | MEDIUM | Both `PRIVATE_READ_PATHS` entries are unreadable, so the mappers are exercised only against fixtures written from a snapshot demonstrably ahead of the deployed venue. |
| Standing rule added (§10): **the SDK snapshot is not evidence of venue capability** | MEDIUM | 501 on a snapshot-documented path proves the snapshot leads deployment. |

**C-B and C-C: no change required.** C-B confirmed closed, with the correction above recorded in
both directions. C-C confirmed closed and correctly sequenced — the re-review verified that
Breezy's own `_submit_order` no-cached-account refusal (`exec/client.py:1300-1304`) is what
currently masks the native fail-open, which is exactly what R-7-PRE's non-vacuity clause asserts,
and that nothing in W/R-5R/R-6.5P/R-6a/c/d/e touches that structure.

**One thing I decline to change.** R-6.5P stays sequenced early rather than being folded back
into R-6.5. Its precondition is blocked *by the venue*, not by engineering, and a blocked trigger
costs nothing while a merged increment would silently re-acquire the E0-INERT cost that splitting
it was meant to avoid. When `/v1/orders/open` returns, R-6.5P runs immediately; nothing has to be
re-planned for that to happen.

---

## 14. What Revision 1 changed, and why

Absorbed from three blind peer reviews (architecture; security/containment; Nautilus/Python
correctness), each finding re-verified against source by the author before acceptance.

| Change | Severity | Cause |
|---|---|---|
| §6 rewritten: end state is **one real order + one realized-PnL row, NOT the goal state**; S-1..S-5 workstream decomposed and calendar-ranked | CRITICAL | Revision 0's `→ accumulate n →` concealed an undecomposed workstream. **L-3 applied to my own plan.** `strategies=[]` pinned at `node_config.py:225,476,655` and re-pinned by W. |
| R-6.5 split into **R-6.5P** (early, `scripts/venue/`, evidence-only) and **R-6.5** (shipped transport, adjacent to R-7) | HIGH | Revision 0 rejected the early probe claiming it would be "outside N2 with every barrier green". **Half wrong, and the important half:** B4 covers `scripts/venue/` (`test_polymarket_us_readonly_guard.py:124,169-172`). Probe-early and defer-E0-INERT were never exclusive. |
| E0-INERT narrowing **fully specified**: one named prefix (`nautilus_trader.core.nautilus_pyo3`), a second exact-path frozenset, and an **equality** test on the residual banned set | CRITICAL | `banned_prefixes = NETWORK_IMPORT_PREFIXES - {"asyncio"} ...` (`:1863-1865`) subtracts one prefix; a verbatim clone would have granted all ten. |
| Four **structural containment commitments** (C1-C4) for the write transport | CRITICAL | E0-NOSEND inspects only `ORDER_LIFECYCLE_COROUTINES` (`:1820`); no importer allowlist exists; B4 misses a wrapper named `send_signed`. Containment was conventional. |
| **R-6b CUT** | HIGH | Hazard refuted at source: `_committed_basis` iterates `cache.positions_open(instrument_id=nt_id)` — instrument-scoped (`cli_settlement_print_lock/strategy.py:882-887`). Second citation read `balance_total`, which §4 shows is never touched. |
| **R-7-PRE** added as a hard precondition | HIGH | `$NT/risk/engine.pyx:688-689` fails OPEN with no account; R-7 removes R-4's masking latch. Filing it as OQ-G was wrong. |
| W: done-predicate distinguishes healthy from latched; `test_a_failed_connect_is_observable_and_does_not_exit_zero` added | HIGH | "Every order denied" is satisfied by a latched client. Silent non-start verified end to end: `exec/client.py:640` raises → `$NT/live/execution_client.py:212-226` skips `actions` → `$NT/system/kernel.py:1310-1316` warns → `trade_cli.py:127-144` exits **`EXIT_OK`**. |
| R-6c: exact-set `_refuse` inventory test; **all 25** sites re-triaged; operator-facing subscriber now part of the increment | HIGH | Revision 0 hand-listed **21 of 25**, missing `:944` (non-long position). An L-6 judgement on 84% of producers is the failure L-6 exists to prevent. And `degrade()` alone had no subscriber, shipping less signal than the existing ERROR log. |
| **OQ-A and OQ-H CLOSED by reading** | MEDIUM | `_start_engines()` (`kernel.py:1021`) precedes `_connect_clients()` (`:1022`); `execution/engine.pyx:667-668` calls `client.start()` synchronously. Declaring it unreadable was itself an unproven gap claim (L-11). |
| R-6 split into **R-6a / R-6c / R-6d / R-6e**; **OQ-I** added for `account_number` (zero producers); exec-engine config pin moved onto the shipped config | MEDIUM | Bundling hid that R-6e touches the operator-control contract. R-4's pin tests a hand-built config, so a later `position_check_interval_secs` edit would re-arm the settlement-zero landmine with the pin green. |
| N1 citation corrected to `node_builder.py:114` / `:201-246`; narrow-except discipline stated | LOW | `:163,177` is inside `build_data_clients`. |

**Not changed, and why.** The correctness reviewer re-opened ~40 installed-source citations and
found no case of a claimed gap that is actually native — N4, N8 and N9 all reproduce as genuinely
absent under positive-controlled greps. The null-hypothesis table stands as written apart from
N1's citation.

**One partial disagreement, recorded.** On R-6c the review offered "either land a subscriber or
cut it and declare `trading_refusals` + the ERROR log to be the health surface". I took the first
option rather than the second, because the ERROR log is not queryable by a supervisor and
`trading_refusals` requires holding a client reference; the msgbus event plus the existing
`AlertSink` seam (`runtime/health.py:73,81`) is a real surface for one increment's work. The
subscriber lives at the wiring layer, never under `exec/`, which may not import
`breezy.runtime.health` (`test_execution_egress_firewall_guard.py:1619`).
