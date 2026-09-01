# EXEC SPINE — shortest sound path to one real, filled, reconciled order

**Status:** **REVISED 2026-09-01 — review findings RESOLVED; R-1 … R-9 are buildable in order.**
**Date:** 2026-09-01. Supersedes `docs/plans/EXEC_CLIENT_NOSEND_PLAN.md` (1993 lines; terminal
state was a process that refuses every order — zero evidence value against the stop gate).

**Review history (2026-09-01, condensed — all findings now closed in this revision).**
Architecture verdict was RE-PLAN (bounded); security verdict SAFE WITH NAMED CONDITIONS.
Three defects and seven conditions were raised; R-1 … R-4 and R-6 survived in substance.

> 1. **R-7's null hypothesis was FABRICATED** — no native `{terminal, retryable, AMBIGUOUS}`
>    taxonomy exists (`AMBIGUOUS|Ambiguous` and `retryable|RETRYABLE` match **0 files** in
>    installed nautilus_trader 1.231.0), and it was load-bearing for a scope CUT. The real
>    missed native is `live/retry.py:65 RetryManager[T]` / `:242 RetryManagerPool[T]` — unwired
>    (0 refs in `live/execution_client.py`) and catastrophic here. → **R-7 rewritten**: taxonomy
>    declared Breezy-owned; `RetryManager` banned by name (barrier B8).
> 2. **The goal-state predicate was UNREACHABLE** — `CacheConfig(database=None)` is memory-only,
>    so after restart every Breezy position reconciles as foreign. → **rewritten** around a
>    durable FILL RECORD; OQ-1 promoted to an R-8 precondition.
> 3. **R-5's "cannot open exposure" was FALSE-framed** — `slugs` is OPTIONAL
>    (`types/orders.py:153-156`), so an ignored body degrades to cancel-ALL. → **rewritten**:
>    whole-account flatness via unfiltered `GET /v1/orders/open`; claim deleted; request budget
>    corrected from "two, max" to four.
>
> Security CRITICALs: C1 R-1 would have written the portfolio into a git-tracked directory
> (mitigated — `docs/evidence/venue/**/PRIVATE_*` ignore rule added and verified);
> C2 `find_secret_leak_offsets` (`polymarket_us_auth_smoke.py:716`) scans only supplied
> credential strings and **cannot see money**. Conditions 1-7 (PRIVATE_ prefix + ignore test,
> independent no-money assertion, key allowlist, B4/B6 narrowing with non-vacuity, write
> transport inside the N2 firewall, `redact_headers`/`redact_url` reuse, whole-account
> flatness) are folded into R-1, R-5 and R-7 below. Also fixed: `_probe_signing_variants` →
> **`_probe_canonical_string`** (`polymarket_us_auth_smoke.py:1042`, verified);
> `live/execution_engine.pyx` → **`.py`**; **OQ-5 CLOSED** from `live/config.py:119-121`.
> **Portability seams LABELLED (not abstracted) 2026-09-01** — see §Kalshi swap.
>
> **Provenance note (L-10).** Defect 1 originated as coordinator shorthand in a commissioning
> brief that the planner promoted to a verified native. Hence the standing rule below: every
> null-hypothesis verdict cites a `file:line` that was actually opened.

## Goal state

> Positive ROI observed from real, very small marketable orders, with the confidence-interval
> **lower bound** clearing break-even.

This plan reaches the first two prerequisites: **one real, filled, reconciled order** (R-1 … R-8)
and **settlement-as-exit** (R-9), without which a fill is an open position and no return exists.

### Goal-state predicate (R-8) — REWRITTEN for reachability

The old predicate required a restart to reconcile a Breezy position "without a synthetic zero
price", but nothing survives the restart: `CacheConfig(database=None)` is memory-only, a filled
IOC is not an open order, and `PositionStatusReport` carries no order id. The fix is a **durable
fill record**, not a stronger assertion.

**Durable FILL RECORD (built in R-4, written in R-7).** At fill application, before the
`OrderFilled` is published, Breezy writes to `SqliteStateStore` under key
`exec/polymarket_us/fill/<venue_order_id>` a record of
`(client_order_id, instrument_id, side, qty, last_px, ts_event, venue_order_id)`. This is the
same store that holds the venue-`id` → `ClientOrderId` map; one store, two key prefixes.

**The predicate holds when, after one live run and a full process restart:**
1. the venue reports exactly **one** filled order;
2. the in-process cache holds a matching `OrderFilled` for that `ClientOrderId`;
3. after restart, reconciliation classifies the resulting position as **Breezy-opened** by
   matching the durable fill record, supplies `avg_px_open` from the recorded `last_px`, and
   denies nothing — **no fallback to `instrument.make_price(0.0)` is reached**;
4. realized cost is within one tick of the price we sent;
5. **OQ-1 is CLOSED**: the observed `cost` semantics on `UserPosition` (signed / cumulative /
   net) are recorded from that restart and pinned by a mapper test. OQ-1 is a **precondition of
   declaring R-8 done**, not a deferral — an unclosed OQ-1 means R-8 is not done;
6. the R-7 submit-intent record is **retired** (no latch outstanding).

**Store thread affinity is a hard precondition of 3 and 6.** `SqliteStateStore` confines itself
to its constructing thread and raises `RuntimeError` off it (`sqlite_store.py:120` records
`threading.get_ident()`; `:128-135` raises; `:158`, `:173`, `:179` call `_check_thread`).
**Design rule:** the store is constructed lazily inside `_connect`, which runs on the exec
engine's event loop — never at config-build time on the main thread. **RED
`test_state_store_is_constructed_on_the_thread_that_writes_it`**: assert the ident captured at
construction equals the ident inside an `await`ed write, and that constructing on a foreign
thread and writing from the loop raises. A store built in the config builder passes every other
test and fails only here.

**End-to-end walk.** Node starts → exec client connects (store opened here) → account queried →
`AccountState` published → risk caps become live (§Ordering) → instruments loaded → strategy
emits a marketable IOC BUY of 1 contract → guard passes → intent record written → signed POST →
venue returns `id` (+ `executions`) → fill record written → `OrderFilled` → intent retired →
restart → mass status + fill record reconcile → settlement closes → one realized-PnL row.

## Non-goals (ruthlessly cut — do NOT design these)

| Cut | Why |
|---|---|
| Four-type authority algebra | One chokepoint already exists (`safety.py:626`, verified). |
| Full six-coroutine denial surface | Only `_submit_order` / `_cancel_order` get real bodies. |
| `/v1/portfolio/activities` fill mapping | Moot if `synchronousExecution` returns `executions` inline (OQ-4). |
| `reports.execution.{venue}` post-application verifier as a **blocker** | Alert only. |
| `exec/direction.py` | No consumer on this path. |
| Any classification beyond Breezy's own three outcomes (R-7) | **Not** because a native taxonomy exists — none does. Because three outcomes are what the latch needs; a fourth has no distinct action. |
| **Any venue-portability abstraction, interface, or indirection** | YAGNI. The seams are **labelled** (§Kalshi swap), never generalized. A second-venue interface built before a second venue exists is speculative and would be built against one venue's shape anyway. |

## Standing constraints (binding, every increment)

- **Nautilus Trader is IMMUTABLE.** Never modify, fork, patch, vendor, or reimplement it.
- **Every increment states an honest null-hypothesis verdict** — CONFIRMED (native present) or
  REFUTED (no native; Breezy-owned) — **with the `file:line` actually opened.** A fabricated
  native is the specific failure that caused this revision; an unverifiable citation is a
  defect regardless of whether the conclusion is right.
- **Every increment carries a portability tag** (VENUE-SPECIFIC / PORTABLE / MIXED). The tag is
  documentation of a seam, never a licence to add indirection.
- **Long-only, taker.** `allow_short=False` (`strategy/weather_common/risk.py:139`) never changes.
- **Operator-reserved controls stay unset.** Max **daily budget** and max **per position** are
  mechanism-only. Absence FAILS CLOSED. See §Operator controls.
- **Never weaken or delete a safety, settlement, or contract test to go green.**
- **Test gate is `scripts/ci/run_tests_no_egress.sh`**, never bare pytest. From R-5 onward the
  N2 session-abort is armed, so a bare run aborts before collection — by design.
- **TDD mandatory.** RED tests land before implementation; RED output is the change artifact.
- **Paired-barrier discipline.** Any barrier narrowing lands in the SAME commit as its
  compensating strengthening, with a **remove-the-caller non-vacuity proof**.

---

## Ordering enforcement: the risk engine is INERT until an account exists

**Verified** — `nautilus_trader/risk/engine.pyx:684-689` returns `True` when
`account_for_venue(...)` is `None`; `:691-692` does the same for a margin account. Every
Nautilus notional/position cap, `max_notional_per_order` included, is **inert** until a real
`AccountState` is cached. **No increment that can submit an order may land before R-4.**
*(PORTABLE — this is a Nautilus defect, identical at any venue.)*

Already pinned green by `tests/contract/test_risk_engine_ordering_enforcement.py`
(no-account over-cap order is NOT denied; with-account over-cap order IS denied on the
`ExecEngine.process` msgbus endpoint; with-account under-cap order is accepted — step 3 proves
step 2 denied on the cap, not on account presence).

**Belt-and-braces.** Start in `TradingState.HALTED`, flip to `ACTIVE` only after the account is
confirmed in cache. Whether HALTED dominates the fail-open is **unverified** — the test is the
arbiter. Fallback: a Breezy precondition in `_submit_order` refusing when
`cache.account_for_venue(POLYMARKET_US)` is `None`. One of the two is green before R-7.

## Operator controls — how the two reserved values arrive at runtime — **PORTABLE**

**Null hypothesis:** a new mechanism is needed. **REFUTED** — `_require_operator_value`
(`safety.py:494-500`, verified) reads `os.environ`, refuses `None`/blank, and has no default;
`_read_operator_money` (`:503-514`) refuses a non-money string and refuses `<= 0`;
`issue_live_trading_permit` (`:541-545`) demands `TRADING_ENABLED_ENV_VAR == "1"` with no
truthiness coercion; `_refuse` (`:221-225`) emits only `type(value).__name__`, never a value.
**R-6's two new controls reuse `_require_operator_value` verbatim.**

**Arrival path:** the operator exports the two variables in the shell that launches
`breezy-trade`. **Never** from a repo file, a fixture, a `conftest`, a committed `.env`, a
default argument, or an `os.environ.get(NAME, <fallback>)`.

**RED:**
- `test_no_repo_file_assigns_an_operator_reserved_control` — AST/text scan over `src/`,
  `scripts/`, `tests/`, and every tracked `*.env*`/`*.toml`/`*.yaml`: the two names appear only
  as bare reads, never on the left of an assignment and never with a default. Non-vacuity: plant
  a module doing `os.environ.setdefault(NAME, "5")` and the scan must fire.
- `test_operator_controls_have_no_default_on_any_path` — with a cleared environment, every entry
  point that could reach a submit raises `LiveTradingPermissionError` naming the missing control.
- `test_refusal_names_the_control_not_the_value`.

---

## Increments

### R-1 — Live shape capture (value-free) — **VENUE-SPECIFIC** — blocked until conditions 1-3

**Null hypothesis:** a Nautilus surface records venue response *shapes* without values.
**REFUTED (Breezy-owned)** — the host is `scripts/venue/polymarket_us_auth_smoke.py`
(`write_evidence` `:702`, `EVIDENCE_DIRECTORY` `:154`, both verified).

Capture **key names (allowlisted) and types only** — never values, never scales — for
`/v1/portfolio/positions`, `/v1/account/balances`, `/v1/orders/open`.

1. **Artifacts carry the `PRIVATE_` prefix.** `EVIDENCE_DIRECTORY` is git-tracked (135 files);
   0600/0700 modes do nothing against `git add`. The ignore rule
   `docs/evidence/venue/**/PRIVATE_*` exists and is verified.
2. **Independent no-money assertion.** `find_secret_leak_offsets` (`:716`) scans only supplied
   credential strings and offers **zero** protection against a balance reaching the artifact.
   R-1 ships its own assertion: the serialized artifact must contain **no numeric literal
   outside a fixed allowlist of structural integers** (key counts, array lengths).
3. **Key names are ALLOWLISTED.** An unrecognized key becomes `unknown_key_count: <int>`,
   **never a name** — a slug-keyed map would otherwise publish the portfolio as field names.
   **Drop "scales" entirely**; emit a type name only (`"decimal_string"`, `"float"`, `"int"`),
   never digit count or exponent, both of which disclose magnitude while matching no sentinel.

**Do NOT reuse `_frame_schema` (`:954`) or `data.py:_walk_structure` (`:534-565`).** Both emit
`safe_values[...] = str(value)` and interpolate dict keys into published paths.

**RED:** `test_shape_capture_artifact_path_is_git_ignored` (via `git check-ignore`);
`test_shape_capture_emits_no_scalar_values` — sentinels planted in **values, in KEYS, and in a
slug-keyed map**, all three absent; `test_unknown_key_becomes_a_count`;
`test_shape_capture_artifact_mode_is_0600`.
**Done when:** artifacts for all three paths exist, all four tests green. **OQ-6 closes here.**

### R-2 — Trading process — **PORTABLE**

**Null hypothesis:** Nautilus provides the process shell. **CONFIRMED** — `TradingNode` /
`NautilusKernel`. Breezy adds a config builder and an entry point.

Third builder in `runtime/node_config.py` (siblings verified at `:163 build_node_config` and
`:381 build_quote_tape_node_config`), settings loader, `breezy-trade` entry point mirroring
`runtime/quote_tape_cli.py` (`Node` protocol `:123`, `_run_node` `:177`, latched-fault exit
code). Config pins `CacheConfig(database=None, flush_on_start=False)` and
**`inflight_check_interval_ms=0`**.

> **Why 0, and cite the right authority.** The disable is a **CODE fact, not a documented one.**
> `live/execution_engine.py:574-575` and `:591-592` guard on
> `if self.inflight_check_interval_ms > 0` before arming the timer, so 0 genuinely disables
> in-flight checking. The config docstring (`live/config.py:111-114`) says only "the interval
> between checking whether in-flight orders have exceeded their threshold. This should not be
> set less than the `inflight_check_threshold_ms`" — it does **not** document a disable, and its
> guidance is in apparent tension with 0. Cite the engine lines in the config comment so a
> future reader does not "helpfully" raise it to 5000 and silently re-arm in-flight checking on
> a venue with no client-order-id. (Distinct from OQ-5, which closes what the *retries* do.)

**RED:** builder returns a config with exactly one exec client and the data client;
`inflight_check_interval_ms` is 0; entry point exits non-zero on a latched fault.
**Done when:** the process reaches `RUNNING` and exits `STOPPED` cleanly, with no exec client
behaviour yet.

### R-3 — `exec/endpoints.py` + report mappers — **VENUE-SPECIFIC**

**Null hypothesis:** Nautilus supplies the report *types*. **CONFIRMED** — `OrderStatusReport`,
`FillReport`, `PositionStatusReport`, `ExecutionMassStatus`. Breezy supplies venue→report
mapping only, narrowed to what reconciliation consumes.

**Verified defect — money is rounded before the mapper sees it.**
`sdk_snapshot/.../types/account.py:19-33` types every balance field as **`float`**, and the
shipped decoder uses bare `json.loads`, destroying the JSON literal. Use
`json.loads(body, parse_float=Decimal)` on the private-endpoint path. Market prices are
unaffected — `Amount` (`types/common.py`) carries `value` as a decimal **string**.
`AccountBalance.currency` must be identically `USD` to match `BinaryOption.currency`
(`parsing.py:1204`); non-USD is a hard refusal, never a coercion.

**RED:** `test_balance_decode_preserves_decimal_literal` (`0.1` must not become
`0.1000000000000000055…`); `test_non_usd_balance_is_refused`; per-report round-trips.
**Done when:** mappers are total over the R-1 shapes and refuse unknown-shape input.

### R-4 — The reconciling, order-refusing client — **MIXED** — de-inerts the risk engine

**Null hypothesis:** `LiveExecutionClient` provides the lifecycle. **CONFIRMED**; Breezy
subclasses it. **`_query_account` is absent** — called at `live/execution_client.py:332` with
nothing defining it, so it must be implemented or the call path raises.

Implement `_connect`, `_set_account_id`, `generate_account_state`, `_query_account`,
`generate_mass_status`, a bounded instrument wait, and the input precondition. **Only
`_submit_order` and `_cancel_order` get real denial bodies**; the other four raise unsupported.

This publishes the first `AccountState` and therefore makes every cap live for the first time.

Two inherited traps *(both PORTABLE — Nautilus behaviour, not venue behaviour)*:
- `generate_mass_status` returns `None` on **any** exception (`live/execution_client.py:498-514`,
  verified — `except Exception` at `:512`, `return None` at `:514`) → reconciliation failure →
  the trader never starts, silently. Catch and report **inside**; never leak.
- `avg_px_open is None` walks five fallbacks ending at `instrument.make_price(0.0)`.
  `UserPosition` has **no average-entry field** (`cost`, `qtyBought`, `netPosition`, all
  `total=False`). **Design:** for Breezy-opened positions, supply `avg_px_open` from the
  **durable fill record**; **refuse** foreign positions, never synthesize.

**Durable state, built here** *(mechanism PORTABLE, keying VENUE-SPECIFIC)*. No client-order-id
exists at this venue, so every Breezy order would reconcile as EXTERNAL, and `database=None`
means a restart orphans it. `SqliteStateStore` holds two key prefixes:
`exec/polymarket_us/venue_id/<id>` → `ClientOrderId`, and `exec/polymarket_us/fill/<id>` → the
fill record. The `exec/<venue>/` namespace **is** the seam: a second venue gets its own prefix,
not a shared one. **Opened inside `_connect`** (thread affinity, §Goal state).

**RED:** account state published with the right `AccountId` and a USD balance; mass status on an
empty account returns empty-but-non-`None`; a foreign position with no derivable entry price is
**refused**, never priced at zero; a position matching a durable fill record is priced from it;
`_submit_order` refuses; `test_state_store_is_constructed_on_the_thread_that_writes_it`.
**Done when:** the node starts, reconciles a flat account, and refuses every order.

### R-5 — Live signing probe (paired barrier) — **VENUE-SPECIFIC** — REWRITTEN

**Null hypothesis:** signing is unknown. **REFUTED** — `sdk_snapshot/.../auth.py` documents
`message = f"{timestamp}{method}{path}"`, no body; `client.py:132` uses it for **every** method
including POST. Residual risk is exactly one live confirmation (OQ-2).

**Probe:** `POST /v1/orders/open/cancel` with a non-empty body, signed two ways, to discriminate
whether the body joins the canonical string.

**Precondition — WHOLE-ACCOUNT flatness, not slug flatness.** `CancelAllOrdersParams` is
`TypedDict, total=False` and `slugs` is **OPTIONAL** (`types/orders.py:153-156`). A venue that
ignores an unrecognized or malformed `slugs` falls through to cancelling **every resting order
on the account**, operator-placed ones included. Therefore: an **unfiltered**
`GET /v1/orders/open` must return an **empty** list immediately before the first POST and again
immediately after the last. OQ-6 must be closed at R-1 first; if `GET /v1/orders/open` does not
report foreign orders, this precondition is unprovable and **R-5 does not run**.
**The claim "cannot open exposure" is deleted.** Cancel-all is exposure-reducing, but on a
non-flat account it is operator-destructive; flatness is what makes it safe, not the verb.

**Request budget: four, not two.** GET (pre-flat) + POST signed `path_only` + POST signed
`path_with_query` + GET (post-flat). The earlier "two requests, max" contradicted its own
two-hypothesis design. Follow the discriminating shape of **`_probe_canonical_string`**
(`polymarket_us_auth_smoke.py:1042-1095`, verified), including its "both accepted" (`:1087`) and
"inconclusive" (`:1089`) branches.

**Write transport placement (security condition 5).** The transport lands at
**`src/breezy/adapters/polymarket_us/exec/write_transport.py`**, which rule **E0**
(`_EGRESS_PATH_PREFIXES = ("src/breezy/adapters/polymarket_us/exec/",)`,
`test_execution_egress_firewall_guard.py:172`) classifies **by path, unconditionally**. A
`PolymarketUSWriteTransport` in `transport.py` would match E1 (basename), E2 (class suffix) and
E3 (function name) **none at all**, and the repo's first write-capable network surface would
ship outside its own egress firewall with every barrier green. In the **same commit**, update
the exact-set pin `test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules`
(`:688-698`) from the single `exec/__init__.py` entry to include the new module.

**Paired barriers (same commit as each narrowing):**
- **B4** (`find_write_egress_violations`, `test_polymarket_us_readonly_guard.py:257-292`)
  currently fires on **V1** (literal `"POST"`, `:267-268`), **V2** (`_ORDER_PATH_RE =
  /v\d+/orders?\b` at `:151` — `/v1/orders/open/cancel` **matches**), **V3** (`.post` /
  `.request` in `_WRITE_ATTRS`, `:150`, `:271-274`) and **V4** (the `getattr` bypass,
  `:275-291`). Narrow B4 by an **exact-path allowlist of exactly two modules**:
  `exec/write_transport.py` and the probe script. Non-vacuity, both directions: (a) remove
  either path from the allowlist and B4 must fire on it; (b) plant a third module with the same
  literals and B4 must fire. A loose B4 re-opens write egress repo-wide.
- Add a **third** canonical-string builder consuming the inert `CanonicalRequest.body` seam
  (`signing.py:122`, verified) and narrow the inertness pin to name the new consumer.
- The write transport carries its **own** method allowlist; do **not** widen
  `PERMITTED_METHODS = frozenset({"GET"})` (`signing.py:84`) and do **not** widen the GET-only
  closure `_build_get_only_callable` (`transport.py:129-148`).
- **B7 stays at zero callers through R-5** (stricter than the prior draft, deliberately): the
  cancel probe is not an order submission and needs no trading permit. B7 narrows at R-7.

**Redaction (security condition 6).** The write transport reuses `redact_headers`
(`redaction.py:70`) and `redact_url` (`ingest/http.py:282`). **No canonical string, no request
body, and no unredacted header may reach a log, an exception, or an artifact.** The canonical
string carries **no nonce** (`signing.py:134`, verified) and the venue tolerates ±30 s
(`DEFAULT_SKEW_TOLERANCE_MS = 30_000`, `:89`), so a captured key/timestamp/signature triple is a
30-second **bearer credential for an arbitrary body at that path** — and with no client-order-id
a replay cannot be deduplicated.

**Preserve the timeout signal** *(the one PORTABLE extract here — see §Kalshi swap)*.
`NautilusHttpTransport.get` (`transport.py:342-348`, verified) collapses `nautilus_pyo3.HttpError`
and `HttpTimeoutError` into one `VenueTransportError` with `from None`, destroying the
distinction the R-7 latch depends on. The **write** transport raises two distinct types,
`VenueWriteTimeoutError` and `VenueWriteTransportError`. Do not change the read path.

**RED:** write transport refuses any method outside its own allowlist; body joins the canonical
string in the new builder and not in the old; a forced failure's exception text contains none of
the access key, timestamp, signature, or body; a timeout raises `VenueWriteTimeoutError`
distinctly; the B4 allowlist non-vacuity proofs; the N2 exact-set pin includes the new module.
**Done when:** signing is confirmed live under whole-account flatness, or the probe returns
inconclusive and R-7 is blocked.

### R-6 — Live order guard + Breezy-owned caps — **PORTABLE** (verified)

**Null hypothesis:** a new guard is needed. **REFUTED** — `BacktestOrderGuard`
(`runtime/backtest_order_guard.py:107-205`) is venue-agnostic: **zero occurrences of
`POLYMARKET|polymarket_us` in the whole module** (verified), and it touches only
`cache.orders_open(instrument_id=...)` and `portfolio.net_position(...)`. Only
`install_order_guard` (`:208`, `engine: BacktestEngine`) is backtest-typed. The live installer
is a ~3-line sibling taking `(portfolio, cache, msgbus)` and subscribing to `ORDER_EVENT_TOPIC`
(`:80`).

**Coverage gap, verified:** `install_order_guard` and `_refuse_naked_short` (`:148`) have **no
behavioural test**. `test_runtime_backtest_order_guard.py:307` asserts the *source string*
`"install_order_guard(engine)"` appears in a file; `test_backtest_harness_refusal_precedence.py:294`
mentions `_refuse_naked_short` only in a docstring. R-6 adds real tests for both before
extending either.

**The exemption keys on the RECONCILIATION tag ONLY — never on order type.**
`generate_missing_orders` emits **MARKET** order events (`live/config.py:108-110`, verified:
"If MARKET order events will be generated during reconciliation"), not LIMIT. A type-keyed
exemption would be wrong today and silently wrong if the type changes upstream. Exempt exactly:
orders carrying the RECONCILIATION tag. Nothing else.

**Breezy-owned caps.** `safety.py` already enforces per-order and per-session notional
(`BREEZY_MAX_ORDER_NOTIONAL_USD`, `BREEZY_MAX_SESSION_NOTIONAL_USD`, none with defaults). The
two operator-reserved controls are **different quantities**, added here as mechanism-only via
`_require_operator_value`: max **daily** budget (rolling calendar-day spend-down) and max **per
position**. Unit declaration (L-2): for a long-only binary book, max loss = premium = price ×
qty, so *max per position* is **USD cost**, not contracts. Both unset; unset fails closed.

**RED:** the live installer installs on a live-shaped msgbus (behavioural, not a source-string
assertion); `_refuse_naked_short` refuses a naked short and names the instrument; a
RECONCILIATION-tagged **MARKET SELL** passes; an untagged MARKET SELL is still refused; an order
over a *set* daily budget is refused; an **unset** daily budget refuses everything and names the
missing control.
**Done when:** the live node reconciles with the guard installed and no crash.

### R-7 — `_submit_order` + `POST /v1/orders` with the durable ambiguity latch — **MIXED** — REWRITTEN

**Null hypothesis:** Nautilus classifies ambiguous submits. **REFUTED — no such native exists.**
Verified by exhaustive search of installed nautilus_trader 1.231.0: `AMBIGUOUS|Ambiguous` → **0
files**; `retryable|RETRYABLE` → **0 files**. The three-outcome taxonomy below is
**Breezy-owned** and is declared as such.

**Breezy-owned outcome taxonomy** (`exec/outcome.py`), exactly three: `DEFINITIVE_ACCEPT`
(venue returned an order `id`), `DEFINITIVE_REJECT` (structured rejection, no `id`), `AMBIGUOUS`
(anything else, including every transport-level failure). Ambiguity is the **default**, not a
leaf: an unrecognized response is AMBIGUOUS.

**Barrier B8 — `RetryManager` is FORBIDDEN by name.** `live/retry.py:65 RetryManager[T]` and
`:242 RetryManagerPool[T]` exist and are **not** wired into `LiveExecutionClient` (verified: 0
matches for `RetryManager|retry` in `live/execution_client.py`). They are opt-in, and they are
the first thing an implementer reaches for. **Wiring either to `submit_order` on a venue with no
client-order-id auto-resubmits and doubles the position.** New barrier B8 in
`test_polymarket_us_readonly_guard.py`: no module under `src/` or `scripts/` may import from
`nautilus_trader.live.retry`, reference `RetryManager`/`RetryManagerPool`, or pass a `retry_*`
kwarg on the submit path. Non-vacuity: plant a module importing `RetryManager` and B8 must fire.

**Write-ahead intent record — the latch, made durable by construction** *(PORTABLE)*. Before the
POST, Breezy writes `exec/polymarket_us/intent/<uuid>` to `SqliteStateStore`
(`instrument_id, side, qty, price, ts, canonical-request fingerprint — never headers, never the
signature`). The `<uuid>` is **Breezy-generated, not a venue id** — that is what makes the latch
portable. The record is **retired only on a definitive outcome**. Therefore:

> **`SUBMIT_AMBIGUOUS` is defined as "an un-retired intent record exists."**

Durable by construction — it survives a crash, a `SIGKILL`, and a restart, with no separate
persistence step to forget. It also survives `CancelledError`: `cancel_tasks_with_timeout`
(`live/cancellation.py:32`) cancels pending tasks at shutdown, and `CancelledError` is a
`BaseException` that escapes `except Exception` (the pattern at `live/execution_client.py:512`).
An in-process boolean flag would be cleared by exactly the failure it exists to catch.

**Latch behaviour.** While an un-retired intent exists: **never resubmit**, reconcile only,
refuse every new submission. Belt-and-braces, the submit path also wraps the POST in
`except asyncio.CancelledError:` (re-raised after ensuring the record is on disk) as well as
`except Exception:` — the record is written before the POST regardless, so both are redundant
safety, not the mechanism.

**Operator-clearing protocol (the only way out)** *(PORTABLE)*. A separate entry point,
`breezy-clear-submit-intent`, which: (1) refuses unless the operator ack env var is present
(`_require_operator_value`, no default); (2) requires the operator to supply the venue order id
the reconciliation resolved to, **or** the literal token for "reconciliation proved no order
exists"; (3) writes a retirement record carrying the operator id and the resolution; (4) never
runs automatically, never on a timer, and is never called from the trading process. Clearing on
a schedule, or on startup, would defeat the latch entirely.

**Chokepoint narrowing (B6/B7), paired.** Narrow **B6** (`BARRED_CALLEES`,
`test_polymarket_us_readonly_guard.py:401-405`, verified) to **exactly one** caller of
`assert_live_order_submission_permitted` at the exact path `exec/client.py::_submit_order`, and
**B7** to exactly one caller of `issue_live_trading_permit` at the `breezy-trade` entry point.
Non-vacuity for each: remove that caller and the "exactly one at this path" test must fail; add
a second caller anywhere and it must fail.

**IOC only** *(VENUE-SPECIFIC)*. Marketable, taker, long-only. Send `synchronousExecution=True`
with `maxBlockTime` (OQ-4) so the fill returns inline. Refuse a price of exactly `0.00` or `1.00`
at the Breezy precondition — `binary_option.pyx:144-145` passes `max_price=None, min_price=None`
(verified), so the instrument constrains nothing, and Breezy's own guard
(`parsing.py:282-283`) is inclusive.

**Nautilus in-flight checks.** **OQ-5 is CLOSED**: `live/config.py:119-121` (verified) reads
"The number of retry attempts the engine will make to **verify** the status of an in-flight
order with the venue" — verification, not resubmission. The real hazard is a *false terminal*
after the retry budget on orders we cannot query by id. Pin `inflight_check_interval_ms=0`,
citing `live/execution_engine.py:574-575,591-592` (the `> 0` guards) as the authority — **not**
the config docstring, which documents no disable. The engine is `live/execution_engine.py`,
**not** `.pyx`.

**RED:** a timeout leaves an un-retired intent and a second submit is refused; a `CancelledError`
mid-POST does the same; a **restart** with an un-retired intent on disk refuses every submit;
`DEFINITIVE_REJECT` retires the intent and does **not** latch; the venue `id` → `ClientOrderId`
map and the fill record are both persisted; a submit without a permit is refused at
`safety.py:626`; a non-IOC order is refused; `breezy-clear-submit-intent` refuses without the
operator ack; **B8 non-vacuity**; **B6/B7 non-vacuity**.
**Done when:** all green under `scripts/ci/run_tests_no_egress.sh`, ordering test green.

### R-8 — The first real order — **VENUE-SPECIFIC**

**Fee floor is bounded FIRST.** The prior "~$0.01 plus fees" is unbounded: a minimum/floor taker
fee can exceed a one-cent notional by orders of magnitude, so the "bounded known loss" framing
was unsupported. **Precondition:** obtain the venue's fee schedule — the docs snapshot, or
`/v1/order/preview` **only if OQ-3 proves it non-mutating** — and record a worst-case total cost
`notional + max(percentage_fee, minimum_fee)`. **If that bound cannot be established, R-8 does
not run.** If it exceeds the operator's per-order ceiling, R-8 does not run. See OQ-8.

Operator present. **One contract**, marketable, IOC, targeting a **losing rung offered at 0.01
in large size** (L-7/L-9): maximum path evidence at minimum bounded cost. This proves the order
path — **it is not an ROI sample**, and no ROI claim may cite it.

**Done when** the goal-state predicate holds in full, **including clause 5 (OQ-1 closed and
pinned) and clause 6 (intent retired)**.

### R-9 — Settlement as exit — **PORTABLE (economics) / VENUE-SPECIFIC (plumbing)**

Not needed to place one order; **strictly required to compute the ROI confidence interval.**
Settlement truth is already in hand and venue-portable — both venues settle on NWS — so the
*economics* carry over intact even if the resolution-report mapping does not. This is a mapping
increment, not a research one. Existing settlement tests are protected; none may be weakened.
Keep the settlement decision keyed on the NWS observation, **never** on a venue resolution
field: that single choice is what makes the economics survive a swap.

**Done when** a filled position produces one realized-PnL row through settlement and the
per-trade return feeds the CI estimator. At sigma/mu ~ 8 per trade, roughly **n ~ 300
station-days** are needed before a lower bound can clear break-even; R-9 starts that clock.

---

## What a Kalshi swap would cost

Labels only — **no abstraction, interface, or indirection is added for this**. The repo already
practises seam-labelling rather than generalizing (`weather_common/costs.py:63-65`: a
venue-neutral cost key keeps the move "a wiring change, not a strategy rewrite";
`polymarket_us/factories.py:109-111`: credentials venue-qualified because "Kalshi is a committed
second venue"). This section extends that practice to the exec spine.

| Inc | Tag | Survives a swap only if… | Swap cost |
|---|---|---|---|
| R-1 | VENUE-SPECIFIC | the keys-and-types walker stays free of venue path names | rewrite paths, **reuse the walker + all three safety tests** |
| R-2 | PORTABLE | the builder's venue-specific part is only the exec-client entry | **reconfigure** — but re-evaluate `inflight_check_interval_ms=0`: it is a *no-client-order-id* mitigation, and Kalshi may supply one |
| R-3 | VENUE-SPECIFIC | — (`parse_float=Decimal` and the USD refusal are reusable rules, not code) | **rewrite** |
| R-4 | **MIXED** | the `exec/<venue>/` key namespace stays per-venue, and the durable-fill-record shape stays keyed on `ClientOrderId` first | Nautilus lifecycle + the two trap mitigations **reconfigure**; mappers and the venue-id map **rewrite** |
| R-5 | VENUE-SPECIFIC | the two-error-type timeout/failure split is not welded to `signing.py` | **rewrite**; keep the split and the redaction discipline |
| R-6 | PORTABLE (verified) | the live installer takes `(portfolio, cache, msgbus)` and names no venue — as `backtest_order_guard.py` already does (0 venue refs) | **reconfigure** |
| R-7 | **MIXED** | the intent record stays keyed on a **Breezy-generated uuid**, and the three outcomes are defined over transport results, not venue status codes | latch, intent record, clearing protocol, B8 **reconfigure**; POST body/endpoint/IOC encoding **rewrite** |
| R-8 | VENUE-SPECIFIC | the fee-floor bound is expressed as `notional + max(pct, min)`, not a Polymarket constant | **rewrite** the schedule, reuse the rule |
| R-9 | PORTABLE (economics) | settlement is keyed on the NWS observation, never a venue resolution field | economics **carry over**; resolution mapping **rewrite** |

**Two corrections to the expected tagging, from source:**
1. **R-4 and R-7 are MIXED, not cleanly split.** R-7's latch is portable as a *mechanism*, but
   its **necessity** is venue-specific: it exists because this venue has no client-order-id. If
   the second venue supplies one (**UNVERIFIED — no Kalshi source in this repo; do not assume**),
   the venue-id map in R-4 disappears and the latch becomes belt-and-braces rather than the sole
   defence. Build it anyway: it is cheap, and it is also the only defence against a *lost
   response* on any venue.
2. **The egress firewall itself is VENUE-KEYED, and this is the sharpest swap hazard.**
   `_EGRESS_PATH_PREFIXES` is `src/breezy/adapters/polymarket_us/exec/`
   (`test_execution_egress_firewall_guard.py:172`); `_VENUE_NAME_RE` is `polymarket`,
   `_ADAPTER_PACKAGE` is `breezy.adapters.polymarket_us`, and
   `VENUE_TOUCHING_SCRIPT_PREFIXES` is `scripts/venue/`, `scripts/probes/`
   (`test_polymarket_us_readonly_guard.py:161-174`). A `breezy/adapters/kalshi/exec/` module
   would match **C1, C3, C4, C5, E0 — none of them**, and would ship entirely outside B4 and N2
   with every barrier green. That is security condition H3 one venue over. **Do not fix this
   now** (YAGNI, no Kalshi code exists); it is recorded here so the first Kalshi commit extends
   the classifiers **in the same commit**, exactly as R-5 does for `exec/write_transport.py`.

---

## Risks, sharpest first

**Resolvable now (before any real order)**
1. **Risk caps inert without an account** (`risk/engine.pyx:684-689`). Mitigation: the contract
   test + HALTED-until-account. If both mechanisms fail, R-7 does not land.
2. **A restart resubmits an ambiguous order and doubles the position.** The sharpest un-named
   money loss in the prior draft. Mitigation: latch = un-retired durable intent record (R-7),
   written before the POST, immune to `CancelledError` and `SIGKILL`.
3. **`RetryManager` wired to `submit_order`** — auto-resubmit with no client-order-id.
   Mitigation: barrier B8, by name, with non-vacuity.
4. **A restart orphans the position** (`database=None` is memory-only). Mitigation: durable fill
   record + venue-id map in `SqliteStateStore`, opened on the loop thread.
5. **Money rounded by bare `json.loads`.** Mitigation: R-3 `parse_float=Decimal`, pinned.
6. **A malformed/ignored `slugs` cancels the whole account.** Mitigation: whole-account flatness
   proven unfiltered, before and after (R-5).
7. **A write transport outside the N2 firewall.** Mitigation: `exec/` placement (E0) + exact-set
   pin updated in the same commit (R-5). *(Recurs at a venue swap — see §Kalshi swap.)*
8. **A 30-second replayable bearer credential in a log.** Mitigation: `redact_headers` /
   `redact_url`, with an exception-text test (R-5).
9. **Reconciliation MARKET SELLs crash the guard.** Mitigation: RECONCILIATION-tag exemption (R-6).
10. **Timeout signal destroyed at `transport.py:342-348`**, and **`generate_mass_status`
    swallowing to `None`** (`:512-514`) so the trader never starts. Mitigations: two distinct
    write-path error types (R-5); internal catch-and-report (R-4).
11. **`inflight_check_interval_ms` silently re-armed** by a future reader following the config
    docstring rather than the engine guards. Mitigation: the R-2 comment cites
    `live/execution_engine.py:574-575,591-592`, and the R-2 RED pins the value at 0.

**Resolvable ONLY by a real order**
12. **`cost` semantics on `UserPosition`** (OQ-1) — now a **blocking precondition of R-8 done**.
13. **Whether the body joins the canonical signing string** (OQ-2) — R-5 narrows to one live call.
14. **Whether `synchronousExecution=True` returns `executions` inline**, and `maxBlockTime`'s
    unit (OQ-4). If not, R-7's fill path needs a poll.

## Open questions

| # | Question | Closed by | Needs a real order? |
|---|---|---|---|
| OQ-1 | Are `UserPosition.cost` semantics (signed / cumulative / net) usable for entry price? | Restart after the first fill | **Yes** — and it **blocks R-8 done** |
| OQ-2 | Does the request body join the canonical signing string? | R-5 | **Yes** (one live confirmation) |
| OQ-3 | Is `POST /v1/order/preview` non-mutating? | R-5 secondary probe | Yes — if unproven, never call it |
| OQ-4 | Does `synchronousExecution=True` return `executions` inline, and what unit is `maxBlockTime`? | R-7 | **Yes** |
| ~~OQ-5~~ | ~~Do `inflight_check_retries` verify or resubmit?~~ | **CLOSED** — `live/config.py:119-121`: retries **verify**. Pin the interval to 0 per `live/execution_engine.py:574-575,591-592`. | — |
| OQ-6 | Does an unfiltered `GET /v1/orders/open` return orders Breezy did not place? | R-1 | No — **and R-5 is blocked until it is closed** |
| OQ-7 | Does the existing `_SHORT` ban collide with reading `intent` on an open order? | R-4 | No |
| OQ-8 | What is the venue's **minimum/floor** taker fee in absolute USD? | R-8 precondition (docs snapshot, or OQ-3-cleared preview) | No — **and R-8 is blocked until it is bounded** |

## Verification

Every increment runs `scripts/ci/run_tests_no_egress.sh`. RED output is kept as the change
artifact. No increment is "done" on a claim: done means the named tests are green under the gate
and the completion criteria are demonstrated. Every null-hypothesis verdict cites a `file:line`
that was actually opened — an unverifiable citation invalidates the increment even when its
conclusion happens to be right.
