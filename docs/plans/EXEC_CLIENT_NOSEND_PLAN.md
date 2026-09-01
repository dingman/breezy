# The NO-SEND execution client — implementation plan

**Status:** Revision 3 — **PARTIALLY EXECUTED, AND SUPERSEDED IN SCOPE.**
**Created:** 2026-08-31. **Status corrected:** 2026-09-01.

> **Do not resume this document as a work plan.** Two corrections, both verified
> on disk on 2026-09-01:
>
> 1. **The former "not executed" status line was FALSE.** NS-0 and NS-2 artifacts
>    are on disk and match this spec's shape:
>    `src/breezy/adapters/polymarket_us/exec/__init__.py` (docstring-only, as NS-0
>    specifies) and `tests/unit/test_cage_rule_constants_are_pinned.py`. Resuming
>    from the old line would have re-implemented landed work. (Verified: the
>    artifacts exist and match the specified shape. NOT verified: that they are
>    green, or that they match every RED line-by-line.)
> 2. **Every line citation in this document is stale.** Spot-checked: B6a and the
>    N2 pin have both moved roughly 150 lines from the positions cited here. Any
>    narrowing "measured against the baseline" would measure against nothing.
>    Re-derive citations before relying on them.
>
> **Why the scope is superseded.** This plan's terminal state is a process that
> refuses every order (see §1). That state was designed on 2026-08-31, when a
> backtest could still be imagined to satisfy the programme's stop gate. Under
> the restated gate — positive ROI from real, very small marketable orders with
> the confidence-interval lower bound clearing break-even — a
> refuses-everything process has an ROI evidence value of exactly zero.
> NS-0..NS-5 is mis-scoped **as a plan**; NS-3/NS-4/NS-5 remain largely correct
> **as increments** and are carried forward into the replacement spine.
>
> **Carry forward unchanged:** NS-5's paired barrier discipline (RED 16 and its
> Barriers section) — the N2 set grows to six in the same commit that narrows
> B6b from "zero subclasses" to "exactly one at an exact path with a non-vacuity
> proof", with B6a explicitly held at `== 0`. That is the strongest engineering
> in this document.
>
> **A safety fact this plan never names, now verified in installed Nautilus:**
> `risk/engine.pyx:684-689` — when `account_for_venue` returns `None`, the risk
> check does `return True` ("Temporary early return"); `:691-692` does the same
> for margin accounts. **Every notional and position cap is INERT until a real
> `AccountState` is in the cache.** Emitting that account is therefore a hard
> ordering prerequisite of any order submission, not a convenience. Enforce it
> with a test, not a sentence.

**What this document is.** `docs/plans/ORDER_EGRESS_PLAN.md` (revision 3, 2246
lines) designed the settlement identity, a four-type authority algebra and the
process container in one document with dense cross-references; three adversarial
rounds returned 16, then 5, then ~7 blocking findings, and the defect rate was
not falling. The coordinator cut the plan at the **NO-SEND / SEND seam**. This
document is the NO-SEND half and nothing else. It supersedes
`ORDER_EGRESS_PLAN.md` increments E-0..E-4; E-5..E-14 remain that document's
problem and are listed in section 8 with one line each on why they are not here.

**End state.** A Breezy trading process that starts, connects, emits a true
venue account, reconciles the venue's positions and open orders from the
read-only `GET` surface, and **refuses every order attempt** — with zero write
capability anywhere in the tree at any increment.

**Authority.** Raw captured venue evidence under
`docs/evidence/venue/polymarket_us/` outranks every document, including this
one. `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md` and
`EGRESS_PREREQUISITES_2026-08-31.md` are the inherited evidence base;
`ORDER_EGRESS_PLAN_REVIEW_2026-08-31.md` and
`ORDER_EGRESS_PLAN_REVIEW_R2_2026-08-31.md` remain binding where they are not
superseded by the narrower scope. **Every claim this document makes about
NautilusTrader or Breezy internals is in the section 9 ledger with a `file:line`
I opened myself; nothing is inherited on trust.** Five claims the predecessor
carried as `[V]` were false or miscounted and are corrected in section 9.1.

**Constraints that bind every increment.**

- NautilusTrader 1.231.0 is IMMUTABLE. Extend only through native extension
  points. Start from the null hypothesis that Nautilus already provides the
  capability, and prove otherwise before authoring anything.
- **Zero write capability at every increment.** No `.post`, no write-method
  literal, no submit / cancel / modify / preview / close-position endpoint,
  anywhere in `src/` or `scripts/`.
- No safety, contract or barrier test is weakened. A barrier that must change is
  re-expressed *more narrowly and more strictly* in the same commit.
- `DEFAULT_ALLOWED_HOSTS` is never widened. `api.weather.gov` is never touched.
  Files under `docs/evidence/` are evidence: never ingested, never re-fetched.
- Secrets are never committed and never logged.

---

## 1. GOAL STATE

### The predicate (single, falsifiable)

> Running `breezy-trade` on a venue-configured host builds and starts one
> Nautilus `TradingNode` that
> **(a)** has, after `node.build()`, exactly one Polymarket.us data client and
> exactly one Polymarket.us execution client **observably registered on the
> node's own engines** — `node.kernel.exec_engine.registered_clients ==
> [ClientId("POLYMARKET_US")]` and the registered client is an instance of
> `PolymarketUSExecutionClient`;
> **(b)** puts a non-`None`, `AccountType.CASH`, `USD`-denominated `Account`
> for venue `POLYMARKET_US` into the Nautilus `Cache`, built from a live
> `GET /v1/account/balances`, **before the trader starts**;
> **(c)** hands the engine, from `GET /v1/portfolio/positions` and
> `GET /v1/orders/open`, a report set in which **every** report names an
> instrument already in the cache **and every `PositionStatusReport` carries a
> non-`None` `avg_px_open` and a `None` `venue_position_id`** — otherwise
> **refuses the whole reconciliation and raises a CRITICAL alert** — and then,
> after the engine has applied that set, **verifies from the engine's own
> `reports.execution.{venue}` publication that each reported position is in the
> cache at the reported quantity and average price**, latching a refusal when it
> is not;
> **(d)** answers each of the **six** order-bearing lifecycle coroutines with
> the denial event its command's order state can actually accept — `OrderDenied`
> for the two submit paths, `OrderCancelRejected` / `OrderModifyRejected` for
> the four cancel/modify paths — every one named, counted and alerted, and
> never an `OrderSubmitted`. **This clause is a property of the CLASS, not of a
> `breezy-trade` run:** with `strategies=[]` no order source exists, so five of
> the six paths have no live caller and the sixth is reachable only if something
> outside this plan submits. It is verified by test, not by running the process,
> and the walk says so;
> **(e)** while `scan_write_egress(("src", "scripts"))` reports zero violations
> outside the single V2-allowlisted path `exec/endpoints.py`, and zero V1 / V3 /
> V4 violations anywhere, and `http.PERMITTED_METHODS` and
> `signing.PERMITTED_METHODS` are still exactly `frozenset({"GET"})` and are
> never rebound.

**Falsifiers.** (a) `breezy-trade` is not an entry point, or
`registered_clients` is empty or holds a client of another type after
`build()` — the case `live/node_builder.py:231-233` `[V]` produces silently
when a factory name does not match its `exec_clients` key. (b)
`cache.account_for_venue` returns `None`, or an account in a currency other
than `USD`, or the trader starts before either is true. (c) A venue position report naming an uncached
instrument, or carrying `avg_px_open is None`, or carrying a non-`None`
`venue_position_id`, reaches the engine; **or** a report set that passed the
check leaves the cache flat, or enters a position at a quantity or average price
other than the reported one — which is what the native zero-price fallback does
(F-26) and what the post-application check exists to catch. (d) Any of the six coroutines produces
`OrderSubmitted`, or emits an event its command's order state rejects (which
`execution/engine.pyx:1586-1594` `[V]` logs and discards, leaving the caller
with no denial at all). (e) Any write-capable construct anywhere outside the
one allowlisted file. **And, for all five: the suite passing green while the
clause is unimplemented.**

**"Refuses to start the trader" is not "refuses to start", and there are THREE
silent gates, not one.** `start_async` has three early returns, each of which
warns and leaves the process alive with no trader: `_await_engines_connected()`
(`system/kernel.py:1024`), `_await_execution_reconciliation()` (`:1028`) and
`_await_portfolio_initialization()` (`:1036`); only after all three does
`self._trader.start()` (`:1039`) run `[V]`. `TradingNode.run_async` then logs
`RUNNING` (`live/node.py:352`) and awaits the engine queue tasks (`:357+`)
`[V]`, so the process daemonises and would exit 0. The third gate is reachable
**by this plan specifically**: `Portfolio.initialize_orders` sets
`initialized = False` when `_accounts.update_orders` fails for any open order
(`portfolio/portfolio.pyx:289-300` `[V]`), and open external orders from
`/v1/orders/open` against a CASH account are exactly what this process feeds it.

**So the exit contract asserts the POSITIVE, and is therefore gate-agnostic.**
`trade_cli` reads `node.trader.state` after `run()` returns and **before**
`dispose()`: `ComponentState.STOPPED` means the trader ran; anything else means
some gate fired. Established by experiment, not by reading: a `Component` reads
`READY (1)` when never started, `RUNNING (3)` after `start()`, `STOPPED (5)`
after `stop()`, and `Trader` is a `Component` subclass exposing `.state`
(`uv run python`, constructing a real component and calling the transitions).
Enumerating the three gates would have left the fourth one Nautilus adds next
uncovered; asserting that the trader ran covers all of them. The client's
refusal latch survives as **diagnosis** — it names *which* refusal for the alert
detail — and is no longer what the exit code depends on. The residual — a live
process with no trader between the gate and operator intervention — is named,
not asserted away (OQ-9).

**What this predicate deliberately does NOT claim.** No order is ever
transmitted. No position is ever opened by Breezy. No PnL is ever realized. No
settlement is priced. No strategy is registered. Those are section 8.

### Why this is a complete, shippable state

An execution client that reconciles truthfully and refuses everything is the
only configuration in which the reconciliation path, the account emission, the
report mappers and the denial surface are all exercised against the real venue
while the worst possible defect costs nothing. It is also the only state in
which the read-only cage can be proven **structurally** — there is no write
module to allowlist, so "zero write capability" is a scan result rather than a
policy.

---

## 2. Container check — run BEFORE the walk was written

The question the predecessor's three revisions each failed to ask, asked of
every artifact this plan builds: **what must already exist for this to RUN, and
which increment builds that?** A row whose answer is "nothing" is a defect. A
row pointing at a LATER increment is a defect. The predecessor added this table
and then shipped a row reading "E-6, needing E-2 + E-7" — a dependency on a
later increment — because the table was written and not read. This one was read;
section 3 states the result.

| # | Artifact | What must already exist for it to RUN | Built by |
|---|---|---|---|
| 1 | The E0 path rule and the collection abort | `tests/conftest.py::pytest_sessionstart` and its existing `pytest.exit` (`:258`, `:268`); `find_execution_egress_modules` (`test_execution_egress_firewall_guard.py:447`); `scripts/ci/run_tests_no_egress.sh` | **all three already exist** — NS-0 wires them together |
| 2 | `exec/__init__.py` | the E0 rule armed, or the first file in the directory lands unclassified | **NS-0, same commit** |
| 3 | Every test run from NS-0 onward | an attested-and-substantiated OS egress block, because `exec/` is now non-empty | **NS-0**; CI already runs the suite this way (`.github/workflows/tests.yml:27`) |
| 4 | Observed response shapes for **balances, positions and activities** (three non-order paths) | an authenticated read against the live venue, and a recorder that emits **no values at all** — the existing `diagnose_frame_payload` publishes every scalar (`data.py:428-429` `[V]`) and is NOT reused | **NS-1** — extends `scripts/venue/polymarket_us_auth_smoke.py`, which already performs `GET /v1/portfolio/positions` (`:163`) |
| 4b | The observed shape of `GET /v1/orders/open` | the same recorder **plus** the path constant, which cannot live in `scripts/venue/` without creating a second V2-allowlisted file (see NS-1 Barriers) | **NS-4's own operator step**, importing `ORDER_PATH_OPEN` from `exec/endpoints.py` — never a second allowlist entry |
| 5 | The cage-constant equality pins | the nine rule constants, which all exist today | **NS-2** |
| 6 | `build_trading_node_config` | native `TradingNodeConfig`; a `PolymarketUSDataClientConfig`, produced by the shipped `config_from_env` (`factories.py:197`); a settings loader for the trading role | **NS-3** (settings loader in the same increment) |
| 7 | `breezy-trade` | a `[project.scripts]` table (`pyproject.toml:255`) and a `main()` | **NS-3** |
| 8 | The node that actually runs | native `TradingNode`; `PolymarketUSLiveDataClientFactory` (`factories.py:320`); an exec factory | **NS-3** (data half), **NS-5** (exec half) |
| 8b | An **observation** that composition succeeded | `node.build()` having run, plus `node.kernel` (a public instance attribute assigned at `live/node.py:71` `[V]`) and `exec_engine.registered_clients` (`execution/engine.pyx:212-221` `[V]`). `build()` (`live/node.py:272-281` `[V]`) constructs clients only — no connect, no socket, once both factories' transports are monkeypatched | **NS-3** (data), **NS-5** (exec) — both assert on the real node |
| 9 | `exec/endpoints.py` | the B4/V2 narrowing, without which the file cannot land at all (`_ORDER_PATH_RE` matches `/v1/orders`, `/v1/orders/open`, `/v1/order/{id}`) | **NS-4, same commit** |
| 10 | `exec/reports.py` fixtures | observed payload shapes — the SDK snapshot types are all `total=False`, so every field is optional and nothing can be assumed present. Fixtures are **hand-transcribed** from the evidence artifact into the test module; `docs/evidence/` is never read by code | **NS-1** (three paths), **NS-4's operator step** (open orders) |
| 10b | `exec/reports.py` passing CI | a `pyproject.toml` `ignore_imports` entry — it imports the Nautilus report types, and `uv run lint-imports` runs in CI (`.github/workflows/tests.yml:37` `[V]`) | **NS-4, same commit** |
| 10c | `generate_missing_orders=True` actually entering a reported position into the cache | the instrument in the cache — the reconciliation path logs at DEBUG and returns `True` when it is absent, at **five** sites (`live/execution_engine.py:2396-2400`, `:2435-2439`, `:2473-2477`, `:3057-3062`, `:3087-3092` `[V]`) | **NS-3** loads instruments through the data client's `PolymarketUSInstrumentProvider`; **NS-5** refuses any report set naming an uncached instrument |
| 11 | A CALLER for the report mappers | a `LiveExecutionClient` whose report coroutines `LiveExecutionEngine` invokes | **NS-5** |
| 12 | `exec/client.py` | the node config carrying its client config; the B6b narrowing; one new `ignore_imports` entry per new nautilus-importing module | **NS-3** (node) + **NS-5** (same commit) |
| 13 | An alert sink **in the trading process** | `resolve_alert_sink` (`health.py:495`) plus a construction site inside this process — today it is constructed only in `ingest_runtime` (`composition.py:352`), so every "loud" failure this plan specifies would be log-only | **NS-5**, in `exec/factories.py` |
| 14 | A true account in the cache | `_set_account_id` (`execution/client.pyx:148`) and `generate_account_state` (`:329`), both native; plus an observed balances shape | **NS-1** + **NS-5** |
| 15 | A started trader | reconciliation returning `True` — otherwise `start_async` returns at `:1029` and `self._trader.start()` (`:1039`) is never reached `[V]` | **NS-5** |
| 16 | An operator learning that the trader did NOT start | an alert sink (row 13) **and** a non-zero exit — the process otherwise daemonises with no trader (`live/node.py:349-357` `[V]`) | **NS-3** (the exit path and its predicate), **NS-5** (the alert, the latch, and the predicate's real body) |
| 17 | `trade_cli` reading the refusal latch | a reachable latch. `LiveExecutionEngine.registered_clients` returns `ClientId`s only and there is no public `get_client` (`execution/engine.pyx:212-221` `[V]`), so the client OBJECT has no native accessor — the latch is a module-level object in `exec/client.py`, imported directly | **NS-5**, both halves. NS-3 ships a `False`-returning predicate with its own test, so NS-3 needs nothing later |
| 18 | Post-application verification of the cache | a seam that runs after the engine applies reports and before the kernel decides — `_reconcile_execution_mass_status` publishes on `reports.execution.{venue}` (`live/execution_engine.py:1941-1944` `[V]`) and `MessageBus.publish` dispatches synchronously (`common/component.pyx:2832-2834` `[V]`); the client owns `self._msgbus`. **Proven by experiment, not by search** | **native, already present** — NS-5 subscribes. Revision 2 asserted this container did not exist |
| 19 | A position entering the cache at a TRUE cost basis | `report.avg_px_open` carrying a real venue value — without it the engine prices the synthetic reconciliation order at **zero** through five fallbacks (NS-5 rule 2b `[V]`) | **NS-1** (the field, via OQ-2) → **NS-4** (the mapper sets it) → **NS-5** (refuses a report without it). If NS-1 cannot answer OQ-2, clause (c) is not claimed |
| 20 | Instruments in the cache when reconciliation runs | the data engine's queue **drained**, which kernel ordering does not give: delivery is asynchronous (`live/data_engine.py:343` `[V]`) and `reconciliation_startup_delay_secs` applies only after startup reconciliation (`live/execution_engine.py:616-626` `[V]`) | **NS-5** — the exec client's own `_connect` waits, bounded, for a non-empty instrument set before returning. Revision 2 claimed kernel ordering was the container; it is not |
| 21 | An operator learning the trader never started for a reason the client cannot see | a check that does not depend on the client — two of the three kernel gates fire before or after the client is consulted | **NS-3**, `node.trader.state` read before `dispose()` |

**Rows that read "nothing" before this plan: two.** Row 4 (the mappers had no
observed payload to map from — the predecessor deferred this to two open
questions and then specified mappers anyway) and row 13 (alerting had no
container in the trading process at all). Both are closed by placing an
increment **before** the artifact that needs it: NS-1 before NS-4, and the sink's
construction site inside the same increment as its only consumer.

**Four rows added in revision 3 (18-21).** Row 18 exists because revision 2
asserted a container's *non-existence* and was wrong; rows 19 and 20 because
revision 2 adopted a native default and a native ordering without checking what
either does; row 21 because revision 2's exit contract covered one of three
gates. **Six rows were added in revision 2, each closing a container the first
revision asserted rather than checked.** Row 4b: revision 1 put an order-path literal in
`scripts/venue/`, which would have created a *second* V2-allowlisted file and
falsified goal clause (e) — the container for that literal is `exec/endpoints.py`,
which NS-4 builds, so the capture that needs it moves after NS-4. Row 8b:
revision 1 had no observation of composition at all, only a three-assertion
inference chain, because ledger claim F-17 wrongly said no accessor existed.
Row 10b: `exec/reports.py` had no `lint-imports` container and NS-4 had no Files
section. Row 10c: `generate_missing_orders` cannot enter a position into the
cache if the instrument is not loaded, and nothing in revision 1 established
that it was. Row 16: revision 1 said "refuses to start the trader" and treated
that as sufficient; the process actually daemonises, so *learning about it* is
itself an artifact needing a container. Row 17: the latch that row 16 depends on
has no native accessor, which is the second-order container question row 16
would otherwise have left unasked.

---

## 3. Dependency check — performed after ordering

| Increment | Depends on | All earlier? |
|---|---|---|
| **NS-0** arm the firewall | nothing in this plan | — |
| **NS-1** read-only shape capture, three non-order paths | nothing in this plan. **Checked against NS-1's own Barriers paragraph**, which is where revision 1's undeclared dependency hid: with `/v1/orders/open` removed, no path in NS-1 matches `_ORDER_PATH_RE` (`/v\d+/orders?\b` `[V]`), so NS-1 needs no allowance from NS-4 | — |
| **NS-2** cage strengthening + the issuer barrier | nothing in this plan | — |
| **NS-3** the trading process | nothing in this plan. **NS-3 had neither a Files nor a Barriers paragraph until revision 3, so revision 2's "mechanical" re-check could not have run on it** — the increment with the widest blast radius was the one exempted, which is the shape revision 2 itself indicted revision 1 for at NS-4. Both paragraphs now exist and the check was run on them: Files names `trade_cli.py`, `node_config.py`, `settings.py`, `pyproject.toml` and three test modules; Barriers names the node-config narrowing, cage layers 1-3 untouched, B6a/B6b unchanged, and the permanent empty literals. **Nothing in either is built by a later increment.** Revision 2's version of this row cited a refusal predicate whose body arrives in NS-5; revision 3 removes even that, because the exit contract now rests on `node.trader.state`, which is native | — |
| **NS-4** `exec/endpoints.py` + `exec/reports.py` (+ its operator step for the open-orders shape) | NS-0 (E0 rule armed before the second and third `exec/` files land), NS-1 (three shapes) | **yes** |
| **NS-5** `exec/client.py` + config + factory | NS-0, NS-2 (pins are the baseline the B6b narrowing is measured against), NS-3 (the node), NS-4 (the mappers and the endpoint table) | **yes** |

**Result: no increment depends on a later one.** NS-1 and NS-2 are independent of
everything and of each other; NS-1 is placed second only because it is
operator-run and its latency should overlap the code work. The chain that
carries the goal state is NS-0 → NS-3 → NS-4 → NS-5, with NS-1 feeding NS-4 and
NS-2 feeding NS-5.

**How this table is checked, and what revision 3's run produced.** The check is
mechanical: for each increment, re-read **its own Files and Barriers
paragraphs** and list every artifact named there that this plan creates. In
revision 2 that surfaced NS-1's `/v1/orders/open` literal, which is why the
open-orders capture became a step inside NS-4.

**Revision 3's run, verbatim result.** All six increments now have both
paragraphs. Scanning each increment's own Files and Barriers for references to a
later increment returns **two hits, both narrative rather than dependency**:
NS-1's Barriers says the open-orders shape is captured *by* NS-4 (explaining what
NS-1 does **not** do), and NS-2's Barriers says its AST ban set is re-asserted
*at* NS-4 and NS-5 (an obligation NS-2 places on them). Neither is an artifact
NS-1 or NS-2 needs in order to run. **No increment requires an artifact built
later.**

**The check has one precondition the document must satisfy itself: the
paragraphs have to exist.** They did not for NS-3, so revision 2's claim to have
run this check was true of five increments and false of the sixth — a claim
about the document's own process that the document did not support. Revision 3
adds both paragraphs and re-runs the check on all six. What it produced this
time: NS-3 clean (nothing later); **NS-4 gained one dependency it did not
declare** — its Files now name `tests/unit/test_polymarket_us_auth_smoke.py`,
because NS-4's operator step adds a fourth path and NS-1 RED 4 pins the
recorder's path set, so NS-1's test must be updated by NS-4; **NS-5 gained one**
— `tests/unit/test_execution_egress_firewall_guard.py`, because NS-0's exact-set
pin is an equality that NS-5's three new modules break. Both are dependencies on
**earlier** increments' artifacts, which is legal, and both were invisible until
the Files sections were made complete.

---

## 4. WALK — performed, increment by increment

Each line states what the increment **adds** to the goal predicate, and what is
still missing after it. This is the check, not a summary of it.

- **After NS-0**: nothing of the predicate holds. What is added is that no later
  increment can land an execution-egress file invisibly: the `exec/` directory
  is classified as an egress surface *before* it contains anything, and a suite
  run without the OS egress block **aborts before collection** instead of
  running the whole suite and printing red afterwards. Missing: everything.
- **After NS-1**: still nothing of the predicate holds, and no line of `src/`
  changed. What is added is the only input clauses (b) and (c) cannot be built
  without: the observed field names, types and nesting of **three** of the four
  authenticated responses — balances, positions, activities. Without it, NS-4's
  mappers would be written against `total=False` TypedDicts in which every field
  is optional, so every real record would refuse and the process would reconcile
  nothing. The fourth (`/v1/orders/open`) is deliberately **not** here: its path
  literal has no lawful home until `exec/endpoints.py` exists. Missing:
  everything else.
- **After NS-2**: still nothing of the predicate holds, **and `safety.py` is not
  opened at all**. What is added is that the cage cannot be *loosened* — or
  silently *narrowed* — by a one-token diff, that a permit cannot be minted from
  any module in the tree (`== 0` callers, no allowlist), and that a module
  reaching the venue from outside the package is classified. The two `safety.py`
  internals revision 1 admitted here are deferred with the authority model
  (section 8), because both are reachable only through a capability this plan
  pins at zero. Everything NS-3..NS-5 does is measured against these pins.
  Missing: the process, the reports, the client.
- **After NS-3**: clause **(a) half** holds — a `TradingNode` for the trading
  role exists, starts from `breezy-trade`, and carries exactly one Polymarket.us
  data client. `exec_clients` is still an explicit `{}`. Missing: (a) exec half,
  (b), (c), (d). This is the first increment whose output is a thing that *runs*.
- **After NS-4**: no clause completes, and no capability was added. What is added
  is the data every later clause consumes: the frozen `(method, path-template)`
  table for the read surface, pure venue-JSON to Nautilus-report mappers with no
  caller yet, and — via NS-4's own operator step, which imports the path constant
  rather than restating it — the fourth observed shape. Clause **(e)** is now
  non-trivially true for the first time: the V2 allowlist exists and contains
  exactly one file. Missing: (a) exec half, (b), (c), (d).
- **After NS-5**: the whole predicate holds. Clause (a) completes and is
  **observed** — `node.build()` runs in the test and
  `kernel.exec_engine.registered_clients` is read directly, which is the only
  check that catches `node_builder.py:231-233`'s silent zero-client build.
  (b) holds (`_set_account_id`, then balances, then `generate_account_state`,
  then a cache assertion Breezy owns). (c) holds in **both** halves: the input
  precondition refuses any report set with an uncached instrument, a missing
  cost basis or a non-`None` `venue_position_id`, and the
  `reports.execution.{venue}` subscriber then reads the cache **after** the
  engine wrote to it and latches a refusal if the position did not arrive at the
  reported quantity and price. `generate_missing_orders=True` is what enters it,
  and a real `avg_px_open` is what keeps that entry off the zero-price fallback.
  (d) holds for the six order-bearing coroutines, each with the event its
  command's order state can accept — **as a property of the class, verified at
  the `ExecEngine.process` endpoint; with `strategies=[]` five of the six have no
  live caller in a `breezy-trade` run, and the predicate now says so.** (e) still
  holds — nothing NS-5 adds is write-capable. **Nothing is missing from the
  predicate.** What it deliberately does not claim: that the process refuses to
  *start* (it daemonises; the trader-state exit contract is the compensation) and
  that the engine's own internal fail-opens are observable (they are not — the
  subscriber sees the cache, not the engine's reasoning). Both are in OQ-9.

**Coverage.** (a) from NS-3 + NS-5. (b) from NS-1 + NS-4 + NS-5. (c) from NS-1
(the cost-basis field, OQ-2) + NS-3 (the node the instruments load into) + NS-4
(the mapper's two rules) + NS-5 (precondition, config, verifier, instrument
wait). (d) from NS-5. (e) from NS-0 + NS-2 + NS-4 + NS-5. **Clause (c) is the
only one needing four increments, and it is the one both revision-3 blocking
findings attacked** — that is not a coincidence: it is the only clause whose
truth depends on framework behaviour rather than on Breezy's own code.

**Clause-to-RED map — every clause names the RED and the ASSERTION that carries
it.** Revision 2 claimed clause (c) was covered by a RED that asserted only
refusal; this table exists so that claim is checkable rather than asserted.

| Clause | RED | The assertion it makes |
|---|---|---|
| (a) | NS-3 RED 3 + NS-5 RED 1 | `node.kernel.{data,exec}_engine.registered_clients == [ClientId(POLYMARKET_US_CLIENT_NAME)]` on a **built** node, and the exec entry is a `PolymarketUSExecutionClient` instance |
| (a) non-vacuity | NS-3 RED 4 + NS-5 RED 2 | the same test with a misspelled factory name yields `[]` and **fails** |
| (b) | NS-5 REDs 6, 7, 8 | `cache.account_for_venue(POLYMARKET_US) is not None` after `_connect`; `_connect` **raises** with `account_id` unset; `_connect` **raises** on a non-`USD` balance |
| (c) refusal half | NS-5 RED 11 (three cases) | `generate_mass_status() is None` for an uncached instrument, for `avg_px_open is None`, and for a non-`None` `venue_position_id` |
| (c) entry half | **NS-5 RED 11b** | after a full reconciliation on a real `LiveExecutionEngine`, the **cache** holds a position at the reported signed quantity **and** the reported `avg_px_open` within 0.01% — and the same test fails against revision 2's `avg_px_open=None` design, because the position enters at zero |
| (c) detection half | NS-5 RED 11c | the `reports.execution.{venue}` handler sets the latch and emits CRITICAL when the cache diverges |
| (d) | NS-5 RED 9, one case per coroutine | the event **type** per path, asserted at the `ExecEngine.process` endpoint, with the named reason, the counter, an alert, and never `OrderSubmitted` |
| (e) | NS-0 RED 4, NS-2 REDs 3-4, NS-4 REDs, NS-5 REDs 13-16 | the exact-set pin, the rule-constant equality pins in **both** directions, `scan_write_egress()` zero outside one file, exactly one client and one factory subclass |
| the exit contract | NS-3 REDs 8-9 + NS-5 RED 12c | non-zero exit for any `trader.state != STOPPED`, the state read **before** `dispose()`, and a freshly imported client module unlatched |

**Send column.** NS-0 none; NS-1 GET (operator-run script, already permitted);
NS-2 none; NS-3 GET + WS (the same surface the recorder already uses); NS-4 GET;
NS-5 GET. **No increment adds a write endpoint, a write verb, or a write
attribute.**

---

## 5. Module layout

```
src/breezy/adapters/polymarket_us/
    http.py  transport.py  signing.py     <- UNCHANGED, BYTE-FOR-BYTE. GET-only.
    safety.py                             <- UNCHANGED. Its two internal defects are deferred (8)
    factories.py                          <- UNCHANGED (its own no-exec-factory barrier stays TRUE)
    exec/
        __init__.py       (NS-0)  docstring only; its existence arms the E0 rule
        endpoints.py      (NS-4)  the ONLY module holding venue order-path literals; data, no I/O
        reports.py        (NS-4)  venue JSON -> Nautilus reports; pure; no I/O, no clock, no decision
        client.py         (NS-5)  the ONE LiveExecutionClient subclass
        config.py         (NS-5)  PolymarketUSExecClientConfig
        factories.py      (NS-5)  PolymarketUSLiveExecClientFactory
src/breezy/runtime/
    node_config.py                        <- NS-3 adds build_trading_node_config (THIRD builder);
                                             NS-5 narrows that site's exec_clients
    trade_cli.py          (NS-3)  the `breezy-trade` entry point; composition inline, see 5.1
    settings.py                           <- NS-3 adds load_trading_settings
scripts/venue/
    polymarket_us_auth_smoke.py           <- NS-1 adds authenticated response-SHAPE capture
```

Seven new source files: six under `exec/` and one in `runtime/`. There is
deliberately **no** `denial.py`, `settlement.py`,
`direction.py`, `fingerprint.py`, `signing.py`, `transport.py`, `egress.py` or
`ambiguity.py` under `exec/`: each belongs to a capability this plan does not
build, and creating an empty seat for one is designing the send half (section 8).

### 5.1 The composition shape — one existing file is mirrored, and it is named

**The predecessor's shape claim was self-contradictory.** It said the trading
composition "mirrors the quote tape's existing shape exactly" while citing
`composition.py:272-310` — the *ingest* shape — and then wrote later increments'
REDs against "the node `trading_composition.trading_runtime` builds", which only
works if that function builds and starts a node. The ingest shape does not: it
is a `@contextmanager` that yields a runtime and never touches a node
(`composition.py:272-370` `[V]`), and node construction is a *separate* function
(`build_ingest_node`, `:462-486` `[V]`) whose lifecycle belongs to the CLI
(`cli.py:119-141` `[V]`). And there is **no `quote_tape_composition.py`**: the
tape's composition lives inline in `quote_tape_cli.py` (`run` at `:192`,
`_run_node` at `:141` `[V]`).

**Decision: mirror `src/breezy/runtime/quote_tape_cli.py`. Composition is
inline in `runtime/trade_cli.py`; there is no `trading_composition.py`.**

Rationale, and it is why the two shapes differ in the first place: the ingest
`@contextmanager` exists to own **non-node process resources** with teardown — a
SQLite store, shared ingest state, an alert sink (`composition.py:313-353`
`[V]`). The quote-tape process owns none of those and therefore has no
contextmanager. The trading process owns one: the alert sink. It is taken as a
**constructor parameter defaulting to `None`**, resolved by
`resolve_alert_sink()` when unset — the pattern already established at
`strategy/weather_common/refusals.py:123` `[V]` — so production resolves one
sink per client and a test injects a recorder without monkeypatching anything.

**One function is split out of the CLI, and only one:**
`build_trading_node(config, node_factory=TradingNode) -> Node`, mirroring
`composition.build_ingest_node` (`composition.py:462-486` `[V]`), which exists
for exactly this reason — it returns a node the caller may *inspect* before
deciding to run it. `trade_cli._run_node` calls it, then `node.run()`, and
always disposes. Without that split, every composed-node RED below would have to
call `run()`.

The trading process owns a **second** non-node resource: the refusal latch, a
module-level object in `exec/client.py` that `trade_cli` reads after `run()`
returns. It is not a contextmanager resource — nothing needs closing — and the
reason it is module-level rather than reached through the node is stated in NS-5
rule 7: `registered_clients` exposes `ClientId`s only and there is no public
`get_client`, so the alternative was an engine private.

**Composition is OBSERVED, not inferred — revision 1 had this backwards.**
Revision 1 asserted (ledger claim F-17) that `TradingNode` exposed no kernel or
engine accessor, and built a three-assertion inference chain around that
absence. **The claim was false.** `self.kernel = NautilusKernel(...)` is
assigned in `TradingNode.__init__` (`live/node.py:71` `[V]`) — a public
*instance* attribute, invisible to the class-level `dir()` the claim rested on.
So `node.kernel.exec_engine.registered_clients` (`system/kernel.py:906-915`;
`execution/engine.pyx:212-221` `[V]`) resolves, and composition can be read off
the node itself. The inference chain was not merely unnecessary, it was
**incapable of detecting the failure that matters**: `build_exec_clients` takes
`name = parts.partition("-")[0]` (`live/node_builder.py:220` `[V]`) and, when no
factory is registered under that name, logs an error and `continue`s
(`:231-233` `[V]`) — the node finishes `build()` with **zero** exec clients
while every link in the chain passes.

**Consequence for every RED in this plan, stated once here so no increment has
to restate it:** composed-node REDs construct a real `TradingNode`, call
`node.build()`, and read `kernel.exec_engine.registered_clients` /
`kernel.data_engine.registered_clients`. `build()` (`live/node.py:272-281`
`[V]`) calls only `build_data_clients` and `build_exec_clients` — it connects
nothing and opens no socket **provided both factories' transports and credential
loaders are monkeypatched**, which is the technique
`tests/unit/test_polymarket_us_factories.py:181-182` `[V]` already uses to
defeat the pyo3 block. **`node.run()` is still never called** — that is where
the event loop, the connections and the sockets are
(`live/node.py:338-363` `[V]`). Behavioural evidence below the node is taken
against the real `LiveExecutionEngine` and `Cache` from
`nautilus_trader.test_kit.stubs`, already the established pattern here (13 test
modules use `TestComponentStubs` `[V]`). The no-socket assertion itself is
carried over verbatim from
`tests/contract/test_node_composition_contract.py:432` `[V]`, and now covers a
node that has been **built**, not merely constructed — a strictly stronger
statement than the one revision 1 borrowed.

---

## 6. Reuse ledger

### 6.1 Native — do NOT rebuild (null hypothesis CONFIRMED)

| Capability | Native anchor `[V]` | Breezy's job |
|---|---|---|
| The process container | `TradingNode` (`live/node.py`), kernel lifecycle (`system/kernel.py`), `add_data_client_factory` (`live/node.py:230`), `add_exec_client_factory` (`:251`), and `node.kernel` (`:71`) for reading back what was composed | **configure and instantiate one** — a config builder, a CLI, an entry point. No runtime. |
| Execution-client machinery | `LiveExecutionClient`: 8 coroutines to implement — 2 lifecycle, **6 order-bearing** (`live/execution_client.py:598-636`) — `generate_mass_status` (`:440-514`), `_await_account_registered` (`:534-567`) | subclass; implement the seams |
| Lifecycle event construction and msgbus routing | `execution/client.pyx`: `generate_account_state` (`:329`), `generate_order_denied` (`:370-406`), `generate_order_modify_rejected` (`:531-537`), `generate_order_cancel_rejected` (`:575-581`) | call them — **and pick the one the target order's state can accept** (F-23), which is the whole content of NS-5 rule 5 |
| Commission on a reconciliation-inferred fill | `ExecutionClient.calculate_commission` (`execution/client.pyx:165-194`), an override hook returning `None` by default; the helper substitutes `Money(0, quote_currency)` (`live/reconciliation.py:503-507`) | **deliberately NOT overridden** — no read here establishes the fee model, and nothing in NO-SEND consumes PnL. Recorded as carry-forward row A2, not left silent |
| Startup reconciliation and its **partial** fail-closed gate | `live/execution_engine.py:1680-1732`; `system/kernel.py:1028-1029` — reconciliation false means `start_async` returns and **`self._trader.start()` (`:1039`) is never reached**. It is NOT a process abort: `run_async` logs `RUNNING` and awaits the queue tasks anyway (`live/node.py:349-357` `[V]`) | supply reports; **check our own inputs before handing them over**, and alert + latch when we refuse |
| Entering a reported venue position into the cache | `generate_missing_orders=True` — the native default (`live/config.py:183` `[V]`): the engine computes the difference, synthesises a reconciliation order report and applies it (`live/execution_engine.py:2511-2563` `[V]`) | **enable it.** Revision 1 pinned it `False`, inherited from a plan whose settlement exit needed that; with settlement deferred, `False` means every venue position is warned about and skipped (`:2501-2509` `[V]`) |
| Account registration in the cache | `_set_account_id` (`execution/client.pyx:148-152`), `_await_account_registered` | set the id FIRST, then assert the cache |
| Order cache, position tracking, the order state machine | `execution/client.pyx`, `model/orders/base.pyx` | obey |
| A post-reconciliation seam | `_reconcile_execution_mass_status` publishes on `reports.execution.{venue}` (`live/execution_engine.py:1941-1944`) after applying every report and before `return all(results)` (`:1949`); `MessageBus.publish` dispatches synchronously (`common/component.pyx:2832-2834`); the client owns `self._msgbus` | **subscribe.** Revision 2 said this did not exist and built around the absence |
| A post-application consistency check | `_validate_reconciliation_state` (`live/execution_engine.py:2130-2179`) — venue-order-id indexing, run right after the publish | **do not rebuild it, and do not rely on it: it only logs.** Its existence is evidence the framework expects divergence here |
| Whether the trader actually started | `Trader` is a `Component` with `.state`; `READY` when never started, `STOPPED` after a normal run | **read it in `trade_cli`** — covers all three silent kernel gates without enumerating them |
| Alert sink, webhook and logging | `runtime/health.py`: `resolve_alert_sink` (`:495`), `emit_alert` (`:514`), `WebhookAlertSink` (`:450`) with `close()` (`:479`) | **construct one in this process** — that is the whole gap |
| Rate-limited pooled HTTP with keyed quotas | `nautilus_pyo3.HttpClient`, already wrapped by `NautilusHttpTransport` | reuse byte-identical |

**Banned by name, unchanged from the predecessor:** `SandboxExecutionClient`
(`adapters/sandbox/execution.py` — hardcodes a `MakerTakerFeeModel` and
`LatencyModel(0)`), `AccountType.BETTING` and `accounting/accounts/betting`
(back/lay stake model, not a drop-in for a 0-1 binary).

### 6.2 The existing read adapter — reused VERBATIM

| Component | Path `[V]` | Used for | Changed? |
|---|---|---|---|
| `Ed25519RequestSigner` | `signing.py:185+`; `PERMITTED_METHODS = {"GET"}` at `:84` | signing every report GET | **BYTE-IDENTICAL** |
| `NautilusHttpTransport` | `transport.py`; the GET-only closure at `:129-148` | all report traffic | **BYTE-IDENTICAL** |
| `PolymarketUSHttpClient` | `http.py:94-270`; `get_authenticated` at `:116`; `PERMITTED_METHODS = {"GET"}` at `:64` | balances / positions / open orders / activities | **BYTE-IDENTICAL** |
| `QUOTA_KEY_PORTFOLIO` | `transport.py:93`, in `PERMITTED_QUOTA_KEYS` (`:98`), budgeted at 12/min | every exec-side read | **already exists and is already permitted** — no new quota key, no widening. Revision 1 called it "unused"; it has three live callers, all in `scripts/venue/polymarket_us_auth_smoke.py:1018,1062,1122` `[V]`, the very file NS-1 extends. It is unused **in `src/`**, which is the claim that matters, and NS-1's reads share its budget |
| `PolymarketUSInstrumentProvider` | `provider.py` | the instrument cache both clients share | unchanged |
| `PolymarketUSCredentials` + loader | `credentials.py`; used at `factories.py:364` | the exec client's own credential load | unchanged |
| Data-client factory shape | `factories.py:320-437` | the template `exec/factories.py` mirrors | unchanged |

`QUOTA_KEY_PORTFOLIO` existing, permitted and unused is the clearest single
piece of evidence that the read stack was built with this increment in view. It
is used as-is.

### 6.3 Genuinely absent — what Breezy must author

1. **A trading-role process.** Two `TradingNodeConfig` builders exist — ingest
   (`node_config.py:163`, `data_clients={}` at `:203`) and the quote tape
   (`:381`, `exec_clients={}` at `:460`) — and neither can trade *by
   construction*. Absent: a third config builder, a settings loader, a CLI, an
   entry point. This is configuration and composition, not a runtime. See
   correction C-1.
2. **Venue protocol translation** — venue JSON to `OrderStatusReport` /
   `FillReport` / `PositionStatusReport` / `AccountBalance`.
3. **`AccountState` emission.** `generate_account_state` exists; nothing calls it
   for you, and `account_id` starts as `None` (`execution/client.pyx:135`).
4. **`_query_account`.** It is *called* (`live/execution_client.py:332`) and
   never *defined* anywhere in the class `[V]` — an omission surfaces as an
   `AttributeError` inside a created task.
5. **A Breezy-owned precondition on the reports it hands over, AND a subscriber
   to the seam the engine already publishes on.** Nautilus reports reconciliation
   success while the cache does not reflect the venue on **at least nine**
   paths: instrument-not-loaded at **five** sites (`:2396-2400`, `:2435-2439`,
   `:2473-2477`, `:3057-3062`, `:3087-3092`), a quantity discrepancy under
   `generate_missing_orders=False` (`:2501-2509`), a closed order whose reported
   `filled_qty` differs (`:3204-3214`), a `FillReport` whose `venue_order_id` has
   no `OrderStatusReport` (`:1881-1907`), and — the one revision 2 created by
   flipping a config — a position entered at price **zero** when `avg_px_open` is
   `None` (F-26). Facts F-2, F-18, F-19, F-21, F-26. Two are closed by
   configuration, six by the input precondition, one is accepted and recorded
   (OQ-10). What Breezy authors is the precondition and the
   `reports.execution.{venue}` handler; the seam itself is native (F-28) and is
   **not** rebuilt — revision 2 thought it had to be, because it thought the seam
   did not exist.
6. **An alert sink construction site in this process.**
7. **Observed response shapes.** The venue SDK's TypedDicts are `total=False`
   throughout, so the schema constrains nothing.
8. **A value-free response-shape recorder.** The existing one publishes every
   scalar (F/B-23) and cannot be pointed at an account balance.
9. **A refusal DIAGNOSIS channel — not a refusal signal, which is native.**
   Nautilus leaves the process running when any of three gates fires
   (`system/kernel.py:1024`, `:1028`, `:1036`), but it does record whether the
   trader ran: `node.trader.state`. That is the signal, and it is native. What is
   absent is only *which* refusal fired, for the alert detail. Revision 2 claimed
   the client object had no public accessor; **it does — `get_clients_for_orders`
   (`execution/engine.pyx:364-400` `[V]`)** — but it resolves clients from an
   `Order`, and this process never has one, so a module-level latch in
   `exec/client.py` is authored instead. **The reason is a stated argument, not
   an absence.**
10. **A bounded wait for instruments to reach the cache.** Delivery is
   asynchronous (`live/data_engine.py:343`) and no native gate drains that queue
   before reconciliation; `reconciliation_startup_delay_secs` applies afterwards
   (`live/execution_engine.py:616-626`). The exec client's `_connect` waits.

---

## 7. Increments

Every increment is **[NO-SEND]**.

| | NS-0 | NS-1 | NS-2 | NS-3 | NS-4 | NS-5 |
|---|---|---|---|---|---|---|
| Network | none | GET (operator) | none | GET + WS | GET | GET |
| New write capability | none | none | none | none | none | none |

Mapping to the predecessor: NS-0 = E-0, NS-2 = E-1 (narrowed, see section 8),
NS-3 = E-2 (justification rewritten, see C-1), NS-4 = E-3 (narrowed), NS-5 = E-4
(extended). **NS-1 is new** and exists because the container check found E-3's
mappers had no input.

---

### NS-0 — Arm the egress firewall for `exec/`, and make it ABORT · MUST BE FIRST

**Why first.** `_EGRESS_MODULE_BASENAMES`
(`test_execution_egress_firewall_guard.py:161-171` `[V]`) contains none of this
plan's filenames — `endpoints.py`, `reports.py`, `client.py`, `config.py`,
`factories.py` — and `_EGRESS_FUNCTION_NAMES` (`:178-180` `[V]`) contains no
underscore form, while every coroutine a real client implements is
`_submit_order`, `_cancel_order`, and so on (`live/execution_client.py:608-633`
`[V]`). Of this plan's six files only `exec/client.py` would be classified
today, and only by rule E2 (it subclasses `LiveExecutionClient`).
`exec/endpoints.py` — the one file that will hold every venue order-path
literal — would be invisible to N2.

**And reporting is not stopping.** `find_execution_egress_modules` appears only
inside its own test module `[V]`; `tests/conftest.py` never consults it. A
failing assertion reddens **one test** while pytest runs everything else in the
same process. The mechanism to abort already exists and is already used:
`pytest_sessionstart` (`conftest.py:258`) calls `pytest.exit(...)` at `:268`
when credentials are present `[V]`. (`pytest_configure` at `:227` also runs
before collection; `sessionstart` is chosen because the precedent is there.)

**Goal.**
(a) Rule **E0**: any file under `src/breezy/adapters/polymarket_us/exec/` is an
execution-egress surface, by path. A prefix that *classifies hazard* fails
CLOSED as the directory grows, which is why the rule is a prefix while every
*exemption* in this plan is an exact path.
(b) Underscore forms added to `_EGRESS_FUNCTION_NAMES`.
(c) The N2 rule is consulted from `pytest_sessionstart` and **aborts the session
before collection** when egress modules exist without an attested-and-
substantiated firewall. The existing test-module assertion stays as its
non-vacuity proof.
(d) `exec/__init__.py`, docstring only, in the **same commit**.

**REDs — and what makes each go red.**
1. An in-memory `exec/transport.py` with no class, no known basename and no bare
   order verb yields an **E0** violation. *Red today:* the rule does not exist,
   so the scan returns `[]`.
2. A venue-touching module defining `async def _submit_order` is detected as
   **E3**. *Red today:* `_EGRESS_FUNCTION_NAMES` holds no underscore form.
3. A planted exec file with no attestation **aborts a child pytest session at
   sessionstart** — asserted by running a child process and checking it never
   reaches collection, not by asserting one test failed. *Red today:* conftest
   never consults the rule, so the child runs the whole suite.
3b. A planted exec file with `BREEZY_TEST_OS_EGRESS_BLOCK=1` attested but **no
   real block** also aborts. *Red today:* nothing checks. **This is the half
   revision 1 left untested**: it wrote "attested AND substantiated" into NS-0's
   goal while RED 3 covered only the unattested case, so a lying attestation
   passed. The sessionstart hook therefore calls `probe_real_egress_canary()`
   (`:387-413` `[V]`, which probes through the *original* pyo3 client and so is
   unaffected by conftest's socket patch) whenever egress modules exist and the
   attestation is present, and exits when the outcome is not `blocked`. Cost:
   one outbound connect attempt to RFC 5737 TEST-NET-2 per session in which
   `exec/` is non-empty — the same probe `test_n3` already makes, moved earlier.
4. `find_execution_egress_modules()` on the shipped tree returns **exactly**
   `[exec/__init__.py under E0]` — the "currently empty" pin (`:592-594` `[V]`)
   inverts to an exact-set pin. *Red today:* the set is empty and the rule that
   would populate it does not exist. **This pin is a standing obligation on
   every later increment:** it is an equality, so any increment adding an
   `exec/` module fails it until the expected set is updated in the same commit.
   NS-4 takes it to three, NS-5 to six, and both name this file in their own
   Files sections. Stated here because a pin that only its author remembers is
   how revision 2 left NS-5 unable to go green.

**Files.** `tests/unit/test_execution_egress_firewall_guard.py`;
`tests/conftest.py`; `src/breezy/adapters/polymarket_us/exec/__init__.py`.

**Barriers.** Cage layer 3 (`test_execution_egress_firewall_guard.py`) plus
conftest. Pure extension; nothing loosened. The N4 classifier is untouched:
`Connection refused` still classifies as REACHED (`:331-334` `[V]`).

**Accepted cost, stated rather than discovered later.** From this commit a bare
`uv run pytest -q` **aborts**. Every local run goes through
`scripts/ci/run_tests_no_egress.sh`, which is already what CI does
(`.github/workflows/tests.yml:27` `[V]`) and which keeps loopback usable inside
the namespace (`run_tests_no_egress.sh:32-43` `[V]`). This is the point of the
increment, not a side effect.

---

### NS-1 — Read-only authenticated response-SHAPE capture · operator-run

**Why this exists at all.** `docs/evidence/venue/polymarket_us/raw/` holds 27
captures and **not one of them is an authenticated account, position, order or
activity payload** `[V]` — every capture is market/public-side. The venue SDK's
own types are `total=False` throughout (`types/portfolio.py`, `types/orders.py`
`[V]`), so `UserPosition` declares `netPosition`, `cost`, `qtyBought`,
`qtySold`, `cashValue` and `marketMetadata` with **every field optional**, and
`GetUserPositionsResponse.positions` is a `dict[str, UserPosition]`, not a list.
A mapper written against that schema alone must refuse every real record, and a
process that refuses every record reconciles nothing — clause (c) of the goal
state would be unreachable. **This is the container-check row that read
"nothing".**

**Scope: three paths, not four.** `GET /v1/account/balances`,
`GET /v1/portfolio/positions`, `GET /v1/portfolio/activities`. **`GET /v1/orders/open`
is deliberately excluded** — see Barriers. Its shape is captured by NS-4's own
operator step, after `exec/endpoints.py` exists to hold the literal.

**The recorder is NEW. `diagnose_frame_payload` is NOT reused, and revision 1's
reuse of it was the most dangerous defect in the document.** The existing
facility does the **opposite** of what its docstring's paraphrase suggests:
`_walk_structure` executes `safe_values[prefix] = str(value)` for every
`str | int | float | bool | None` (`data.py:428-429` `[V]`), and the smoke
renders those under a literal `"Safe scalar values:"` table
(`polymarket_us_auth_smoke.py:627-635` `[V]`). Its docstring says "without
publishing **non**scalar payloads" (`:955` `[V]`) — it suppresses *containers*
and publishes *scalars*. Revision 1 paraphrased that as "shape without values",
which is the inverse. Pointed at `/v1/account/balances` it would have written
the operator's balance into a committed, hashed, public artifact. The stated
fail-closed net does not catch it either: `find_secret_leak_offsets` (`:307`
`[V]`) scans only the credential strings passed as `secrets`, and a balance is
not a credential. And because dict keys become published path segments
(`f"{prefix}.{key}"`, `data.py:435` `[V]`), a positions map keyed by market
publishes the portfolio *as field names*.

**Currently-committed evidence is clean.** `_frame_schema` is wired only to the
WebSocket frame handler and the recorded scalars are public order-book levels.
The hazard was the proposed new use, not the existing one, and nothing already
on disk needs remediation.

**Goal.** A new `describe_response_shape(body: Mapping) -> ResponseShape` in the
smoke script, whose result type **has no `safe_values` field at all** — the
absence is the guarantee, not a filter that could be widened later. It records:
the set of key **paths**, the JSON **type** at each path, and, for mappings
whose keys are data (a positions map keyed by market slug), the literal marker
`<dynamic-key>` in place of every key below the first dynamic level. It records
**no** value, **no** digit or decimal count, and **no** array length: all three
are value-derived, and the fixed-point scale question they were meant to answer
is answerable from the SDK snapshot's `Amount` type or from a **public** market
read, neither of which touches the operator's numbers. One new evidence artifact
under `docs/evidence/venue/polymarket_us/`, with its `.sha256`, in the existing
dated format.

**REDs — and what makes each go red.**
1. `describe_response_shape` applied to `{"balances": [{"currency": "USD",
   "available": "1234.56"}]}` produces a record in which the string `1234.56`
   **does not appear anywhere**, asserted against the rendered artifact text,
   not against the intermediate object. *Red today:* the only recorder present
   emits it under "Safe scalar values:".
2. Applied to a mapping keyed by market slug, no slug appears in the output;
   the path is `positions.<dynamic-key>.netPosition`. *Red today:* `data.py:435`
   interpolates the key.
3. `ResponseShape` has no attribute named `safe_values`, `values`, or
   `samples` — asserted by `dataclasses.fields`. *Red today:* the type reused
   would be `FrameSchema`, which has `safe_values`.
4. The three endpoint paths appear in the smoke's read plan with method `GET`,
   the script's write-request counter stays `0`, and **none** of the three
   matches `_ORDER_PATH_RE`. *Red today:* two of the three are not read.
5. `find_write_egress_violations` over the modified smoke script reports **zero**
   violations. *Red today:* passes today and must keep passing; it is stated
   because revision 1's version of this increment would have broken it.

**Files.** `scripts/venue/polymarket_us_auth_smoke.py`; its test module; the
emitted evidence artifact plus `.sha256`. **No `src/` file changes.**

**Barriers — and the forward dependency revision 1 hid here.**
`scripts/venue/` is venue-touching by rule C2 (`readonly_guard.py:128-131`
`[V]`), so V1-V4 apply in full: no write-method literal, no `.post`. Revision 1
also read `/v1/orders/open` here, which is an order-path literal and trips
**V2** (`_ORDER_PATH_RE = /v\d+/orders?\b` `[V]`). That would have required an
exact-path V2 allowance for `polymarket_us_auth_smoke.py` — a **second**
allowlisted file, falsifying goal clause (e). **Resolved by removing the path,
not by widening the allowlist:** the open-orders shape is captured in NS-4's
operator step, importing `ORDER_PATH_OPEN` from `exec/endpoints.py`, so the
literal only ever exists in the one file allowed to hold it. The three paths
NS-1 does read match no rule.

**What that resolution does NOT buy, stated because revision 2 overclaimed it.**
Moving the import moves the **literal**, not the request: NS-4's operator step
still issues `GET /v1/orders/open` from the same credentialed smoke script, in
the same process, against the same key. The security argument revision 2 made —
"it keeps an order path out of the file that handles live credentials" — is
**false and is withdrawn**. The surviving argument is the V2 one, and it is
sufficient on its own: goal clause (e) says *one* allowlisted file, and this
keeps it at one.

**Completion.** A committed, hashed evidence artifact naming every field path
and type of the three authenticated responses, containing no value, no key that
is itself data, and no count derived from a value. **Everything NS-4 maps for
balances, positions and activities, it maps from this artifact** — transcribed
by hand into the test module, never read from `docs/evidence/` by code.

**If the operator run cannot happen.** NS-4's mappers refuse per record by name,
NS-5 ships, and clause (c) of the goal state is **not claimed**: the process
would start, emit an account only if the balances shape is among the observed
ones, and otherwise refuse the reconciliation, alert, and latch a non-zero exit.
That is a correct fail-closed state and an incomplete goal state. Say so; do not
claim the predicate.

---

### NS-2 — Cage strengthening, and the one permit defect this plan can reach

**Goal.** Make every cage rule constant unloosenable, and close the one
`safety.py` defect whose consequence is reachable while nothing mints a permit.

**What is here, and what moved out.** Revision 1 admitted a defect to this
increment if it was (i) a correction to shipped code, (ii) testable with a RED
today, and (iii) free of the SEND half's authority vocabulary. Two of the three
defects it admitted fail its own criterion — and the review was right to say so.

| # | Defect | Cite `[V]` | Disposition |
|---|---|---|---|
| **D-2** | `issue_live_trading_permit` has **no caller barrier at all** and is re-exported in the package `__all__`, so any module in the tree may mint a permit from the operator's environment | `safety.py:527`; `adapters/polymarket_us/__init__.py:107,191` | **KEPT.** A caller barrier is a *cage* rule, not authority design: it constrains who may reach an existing function, needs no new state, and its consequence — self-issuance — is reachable today by any module. Pinned `== 0` callers in `src/` + `scripts/`, with **no allowlist structure at all**, plus a proof that a planted caller fails. Removed from `__all__`. |
| **D-1** | `consume()` compares notionals with `!=` and does not type-check, so a `Decimal` subclass overriding `__ne__` satisfies the re-check at any magnitude | `safety.py:463` | **MOVED to the SEND half** (section 8). `consume` is reachable only from a capability, which is minted only by the chokepoint, which this plan pins at **zero callers**. Fixing it here changes code no path in this plan executes. |
| **D-3** | Renewal resets the operator's budget: issuance re-reads the ceilings from the environment (`:548`) and installs a fresh `_Budget` under a fresh `permit_id` (`:575`); `_PERMIT_BUDGETS` (`:332`) aggregates nothing; `PERMIT_TTL_NS` is 15 minutes (`:157`), so renewal is forced | `safety.py` | **MOVED to the SEND half** (section 8). The fix *designs new authority state* — a process ledger keyed by `operator_id` — inside a plan whose whole seam is that the authority model is deferred. That is criterion (iii) violated by the increment that wrote the criterion. Its own residual hazard is recorded in the carry-forward table: the ledger key would be read from operator-controlled environment, so a successor must pin it at first issuance and refuse a different value, or changing one variable mints a fresh budget. |

**D-2's barrier is `== 0` with nothing to allow.** Revision 1 wrote "`== 0`
callers with a one-entry path allowlist **declared and empty**", which is
self-contradictory — a one-entry allowlist that is empty is a zero-entry
allowlist, and shipping an unused allowlist structure is the shape that later
gets filled in without a paired assertion. There is no allowlist. The rule is:
zero callers, anywhere in `src/` and `scripts/`, full stop. The SEND plan that
first needs a caller introduces the allowlist together with its `== 1` pin.

**The eight silent-failure counters.**

| # | Failure mode | Counter |
|---|---|---|
| 1 | A directory-prefix *exemption* becomes a blanket allowance | every exemption is an exact path; each allowlist entry must resolve to an existing file; the frozenset is equality-pinned |
| 2 | Egress escapes the classifier | **the planted-module RED (#5 below), and only that.** Revision 1 stated this as "`assert is_venue_touching(p) is True` for every path in section 5's layout". That assertion is **vacuous** for the six `exec/` paths — they pass on the C1 string prefix alone (`readonly_guard.py:189` `[V]`), before any file exists — and **false** for `runtime/settings.py`, which imports no venue module and classifies `False` (`:187-206` `[V]`), so it could not have landed as written. What has content is the negative case: a module that reaches the venue by a route C1-C4 miss. |
| 3 | The global rule is loosened instead of the file allowlisted | equality pins on all nine rule constants: `_WRITE_METHODS`, `_WRITE_ATTRS`, `_ORDER_PATH_RE`, `EGRESS_SCAN_ROOTS`, `SDK_IMPORT_ORACLE`, `_EGRESS_MODULE_BASENAMES`, `_EGRESS_CLASS_SUFFIXES`, `_EGRESS_CLASS_BASES`, `_EGRESS_FUNCTION_NAMES` |
| 4 | N2 blind to planned filenames | **NS-0** |
| 5 | A barrier written `<= 1` passes while dead | every count assertion is an equality, with a proof that both neighbours fail |
| 6 | An exec test marked `allow_socket` / `live` / `venue_live` / `real_money` restores the real pyo3 clients (`conftest.py:394-402` `[V]`) | static ban on those four markers in any test importing `...polymarket_us.exec` — **sound only because section 5.1's decision means no exec test ever needs a socket**, including the ones that now call `node.build()` |
| 7 | Data-path widening by rebinding `signing.PERMITTED_METHODS` on an imported module object | repo-wide AST ban on assignment to `PERMITTED_METHODS` / `PERMITTED_QUOTA_KEYS` / `_WRITE_*` |
| 8 | A rule constant is *narrowed* rather than widened, silently disarming a scan | the same equality pins as #3, which fail in both directions |

**REDs — and what makes each go red.**
1. A module outside the issuer mints a permit from the operator's environment.
   *Red today:* no caller barrier exists.
2. `issue_live_trading_permit` is importable from
   `breezy.adapters.polymarket_us`. *Red today:* it is in `__all__`
   (`__init__.py:191` `[V]`).
3. Widening `_WRITE_METHODS` by one token leaves the suite green. *Red today:*
   the constant is unpinned.
4. **Narrowing** `_EGRESS_CLASS_BASES` by removing `LiveExecutionClient` leaves
   the suite green. *Red today:* unpinned in that direction too, and this is the
   direction that silently disarms NS-0.
5. A planted `src/breezy/egress_outside_the_package.py` that reaches the venue
   with its base URL read from `os.environ` is classified **not**
   venue-touching. *Red today:* C1-C4 do not cover it. This is counter 2's whole
   content.
6. A test importing `...polymarket_us.exec` marked `@pytest.mark.allow_socket`
   is undetected. *Red today:* no such scan.
7. Rebinding `signing.PERMITTED_METHODS` from another module is unbanned.
   *Red today:* no such scan.

**Files.** `adapters/polymarket_us/__init__.py`; the three guard suites; new
`tests/unit/test_cage_rule_constants_are_pinned.py`. **`safety.py` is not
touched by this plan at all** — D-1 and D-3 were the only reasons to open it.

**Barriers.** Every change is strictly stronger. **No allowlist is created in
this increment.** `SandboxExecutionClient`, `AccountType.BETTING` and
`accounting/accounts/betting` are banned by name, each with a non-vacuity proof.
The AST bans on the tokens `_SHORT`, `OUTCOME_SIDE_NO` and any `1 - price` form
anywhere under `exec/` land here too: they are prohibitions rather than purity
proofs (so indirection cannot defeat them), and the hazard they name is the one
a reviewer found in a comment that must NOT be "fixed" (`risk.py:75-78`'s "short
YES is spelled buy NO" is correct in context). **But at NS-2 `exec/` contains
only `__init__.py`, so each of these scans passes over one docstring: they are
vacuous on the day they land and stay vacuous until NS-4.** Two consequences,
both required. (1) Each ban ships with a **planted-source non-vacuity proof** —
a synthetic module text containing the banned token, asserted to fail the scan —
so the scan is proven to work on the day it lands even though the tree gives it
nothing to find. (2) NS-4 and NS-5 each **re-assert** the ban set over their own
new modules in their own commits, named in their Barriers, rather than trusting
a scan written two increments earlier to still be reachable.

---

### NS-3 — The trading process: the container everything else runs inside

> **The justification the predecessor gave for this increment was false, and it
> is restated correctly here.** Revision 3 claimed "the process itself does not
> exist" and "First time a Breezy `TradingNode` exists at all", resting on
> `grep "TradingNode(" src/` returning zero. That grep returns zero because the
> repo passes the **class**, not a call: `node_factory: NodeFactory = TradingNode`
> (`quote_tape_cli.py:195`, `cli.py:147` `[V]`), then
> `node = node_factory(config); node.build(); node.run()`
> (`quote_tape_cli.py:151-157` `[V]`). **Two real `TradingNode`s are built and
> run today.** The true gap is narrower, and it is what this increment closes:
> (i) there is no `TradingNodeConfig` builder for the **trading role** — the
> ingest builder pins `data_clients={}` (`node_config.py:203` `[V]`) and both
> existing builders pin `exec_clients={}` and `strategies=[]` (`:204,212`;
> `:460,463` `[V]`), so registering an execution client into either one puts it
> in a process that has no venue data or is contractually not a trader; and
> (ii) there is no `breezy-trade` entry point (`pyproject.toml:255-260` `[V]`).

**Null hypothesis: NATIVE — sufficient for the runtime, absent for the
configuration.** `TradingNode`, the kernel lifecycle, and both factory
registration paths (`live/node.py:230`, `:251` `[V]`) are complete and are not
extended. Absent: a third config builder, a settings loader, a CLI, an entry
point. **Configuration and composition only — no runtime, no framework, no
abstraction over three processes.**

**Goal.**

- `node_config.build_trading_node_config(settings, data_client_config)` — the
  **third** `TradingNodeConfig(...)` call site. At this increment:
  `data_clients={POLYMARKET_US_CLIENT_NAME: data_client_config}`,
  **`exec_clients={}`**, **`strategies=[]`**, **`exec_algorithms=[]`**, all four
  as explicit literals so the source-level cage rule can read them.
  `catalogs=[]` and `actors=[]` for the reasons `build_node_config` already
  gives (`node_config.py:164-192` `[V]`). **No `StreamingConfig`** — the tape
  records, the trader trades.
- **`cache=CacheConfig(database=None, flush_on_start=False)`**, identical to
  both existing sites (`:199`, `:455` `[V]`). See "the Redis decision" below.
- `settings.load_trading_settings(env)` mirroring `load_quote_tape_settings`
  (`settings.py:517` `[V]`): a `PolymarketUSTradingSettings` frozen dataclass
  carrying `trader_id` and `log_level` and nothing else, with **no default for
  any operator gate**. Venue endpoints, slugs, user agent and signing variant
  are **not** re-read here — `config_from_env` (`factories.py:197` `[V]`) already
  owns that contract, and a second reader is a second competing policy for the
  same variables.
- `runtime/trade_cli.py` mirroring `quote_tape_cli.py` (section 5.1): `main()`
  calls `run(env=None, node_factory=TradingNode, stderr=None)`, which loads
  settings, builds the data client config, builds the node config, and then
  calls `_run_node(config, node_factory, stderr)`. `_run_node` delegates
  construction, factory registration and `build()` to
  **`build_trading_node(config, node_factory) -> Node`** — a named seam mirroring
  `composition.build_ingest_node` (`composition.py:462-486` `[V]`), which exists
  for exactly this reason: it returns a node the caller can *inspect* before the
  caller decides to run it. `_run_node` then calls `node.run()` and **always**
  disposes. `KeyboardInterrupt` is exit 0, as the tape has it
  (`quote_tape_cli.py:158-168` `[V]`). Splitting `build_trading_node` out is what
  makes RED 3 possible without a test ever calling `run()`.
- **The exit-code contract, asserted as a POSITIVE and therefore gate-agnostic.**
  After `node.run()` returns and **before** `node.dispose()`, `_run_node` reads
  `node.trader.state`; anything other than `ComponentState.STOPPED` means the
  trader never ran, and `_run_node` returns `EXIT_RUNTIME_ERROR` and emits a
  CRITICAL alert. This is the only way an operator's supervisor learns anything:
  the kernel has **three** silent gates (`system/kernel.py:1024`, `:1028`,
  `:1036` `[V]`), each of which warns, returns, and leaves the process
  daemonised with no trader (`live/node.py:349-357` `[V]`). Enumerating them
  would leave the fourth uncovered; asserting that the trader ran covers all of
  them and any future one. The state values are established by experiment, not
  by reading: a `Component` reads `READY (1)` before `start()`, `RUNNING (3)`
  after it and `STOPPED (5)` after `stop()`, and `Trader` is a `Component`
  subclass exposing `.state` (`uv run python`). **The order matters**: `dispose()`
  moves the state to `DISPOSED (9)`, so the read happens first. NS-5's refusal
  latch, when it arrives, only enriches the alert's detail — it is not what the
  exit code depends on, which is why NS-3 depends on nothing later.
- `breezy-trade = "breezy.runtime.trade_cli:main"` in `[project.scripts]`, a
  **separate** process from `breezy` and `breezy-quote-tape` for the reason
  `pyproject.toml:257-259` `[V]` already states about those two: the weather
  collector must start on a host with no venue configuration, and this one must
  refuse to start without it.
- `pyproject.toml` `ignore_imports`: one entry
  `breezy.runtime.trade_cli -> nautilus_trader`, of exactly the same shape as the
  existing `breezy.runtime.quote_tape_cli -> nautilus_trader` (`:141` `[V]`).

**The Redis decision, made explicitly and in the opposite direction to the
predecessor.** Revision 3 set `CacheConfig(database=DatabaseConfig(type="redis"))`
here and asserted "if Redis is unreachable the process refuses to start". **That
assertion is uncited and no Nautilus code produces it:** `system/kernel.py:309-329`
`[V]` selects a `CacheDatabaseAdapter` when `type == "redis"` and raises
`ValueError` only for an *unrecognized* type — it never probes connectivity.
Adopting it would have shipped a claimed native behaviour the native code does
not produce. More importantly the requirement itself is out of scope: a durable
cache exists so that a crash **while holding a position** cannot resurrect a
process with zero knowledge of its exposure. **This plan can never open a
position.** The venue's GET surface is the source of truth at every startup, and
reconciliation already fails closed. So: **`database=None`, the same as the
other two processes, and a durable cache is a hard prerequisite of the first
exposure-opening increment (section 8).** This also removes the only reason any
test in this plan would need a socket — see section 5.1 and NS-2 counter 6.

**REDs — and what makes each go red.**
1. `len(_node_config_calls()) == 3`. *Red today:* the pin is `== 2`
   (`test_runtime_node_config.py:340` `[V]`) and there are two sites.
2. The **per-site value table** below holds for all three sites, and an
   *unknown* enclosing function is a **failure**. *Red today:* the rule
   quantifies over every site and asserts emptiness of three fields
   (`:343-349` `[V]`), so it cannot express "this site may carry exactly one
   data client" and cannot detect a fourth site at all.
3. `build_trading_node(config, node_factory=TradingNode)` returns a node for
   which `node.is_built() is True` and
   `node.kernel.data_engine.registered_clients == [ClientId("POLYMARKET_US")]`,
   with the data factory's `NautilusHttpTransport` and credential loader
   monkeypatched, and the construction opens **no socket** — the assertion
   carried over from `test_node_composition_contract.py:432` `[V]`, now applied
   to a node that has been **built**. *Red today:* neither the builder nor the
   seam exists. **`is_built` is a method, not a property** (`live/node.py:185`
   `[V]`); revision 1 asserted on the bound object, which is always truthy and
   therefore always passed.
4. The same test, with the factory registered under a **misspelled** name,
   yields `registered_clients == []` and the test **fails**. *Red today:* no
   builder. This is the case `node_builder.py` produces silently — it applies
   `name = parts.partition("-")[0]` (`:220` `[V]`) and logs an error then
   `continue`s on a name with no registered factory (`:231-233` `[V]`) — and it
   is the reason the assertion reads `registered_clients`, not "the factory was
   called". `quote_tape_cli.py:141-148` `[V]` documents the same hazard on the
   other process, where its symptom is a recorder silently recording an empty
   tape.
5. `trade_cli.run` with the venue environment absent **exits non-zero without
   constructing a node**. *Red today:* no CLI.
6. Neither `ingest_runtime` (`composition.py:272`) nor `quote_tape_cli` can
   reach `build_trading_node_config`, asserted on the import graph. *Red today:*
   there is nothing to reach, so the assertion is written first and is vacuous
   until the builder lands — it is included because the two read-only processes
   must never acquire an order path by a call-graph change alone.
7. `uv run lint-imports` passes. *Red today:* a new module importing
   `nautilus_trader` breaks the forbidden-import contract until its
   `ignore_imports` entry lands in the same commit.
8. `_run_node` returns `EXIT_RUNTIME_ERROR` when `node.trader.state` is
   anything other than `ComponentState.STOPPED` after `run()` returns, and `0`
   when it is `STOPPED`, driven by a node double whose `trader.state` the test
   sets. *Red today:* no CLI. **This covers all three kernel gates without
   naming any of them**, which is the point of asserting the positive.
9. `_run_node` reads `trader.state` **before** `dispose()`. Asserted by ordering
   on a recording double: a `dispose()` that runs first would make the state
   `DISPOSED` and every run look refused. *Red today:* no CLI — and an
   implementation that disposes in a `finally` before reading fails this for
   exactly the right reason.

**The node-config barrier: narrowed, and strictly stronger.** Today's rule is
"at every `TradingNodeConfig(...)` site, `exec_clients`, `strategies` and
`exec_algorithms` are empty literals", plus "there are exactly 2 sites"
(`test_runtime_node_config.py:289-349` `[V]`). It is replaced, in the same
commit, by a rule keyed on the **enclosing function name**:

| Site | `data_clients` | `exec_clients` | `strategies` | `exec_algorithms` |
|---|---|---|---|---|
| `build_node_config` (ingest) | `{}` | `{}` | `[]` | `[]` |
| `build_quote_tape_node_config` | exactly `{POLYMARKET_US_CLIENT_NAME: <the data config parameter>}` | `{}` | `[]` | `[]` |
| `build_trading_node_config` (NS-3) | exactly `{POLYMARKET_US_CLIENT_NAME: <the data config parameter>}` | `{}`, becoming exactly `{POLYMARKET_US_CLIENT_NAME: <the exec config parameter>}` at NS-5 | `[]` **permanently in this plan** | `[]` **permanently** |

Five assertions make this stronger than what it replaces, and each lands in the
same commit as the change it covers: (1) every call site's enclosing function is
in the table — an unknown site is a **failure**, which the current rule cannot
express; (2) each field is pinned to its **exact expected value**, not merely to
emptiness, so the two existing sites become *harder* to change than they are
today; (3) `exec_algorithms == []` is asserted at all three sites
unconditionally; (4) the ingest and quote-tape builders are asserted
**byte-unchanged** by NS-3 and NS-5; (5) the count pin moves from `== 2` to
`== 3` and stays an equality.

**The `exec_clients` row pins IDENTITY, not cardinality.** The predecessor wrote
"`{}` to one key", which a swap of the registered client satisfies. The pin is
on the **exact key** (`POLYMARKET_US_CLIENT_NAME`) **and the exact value
expression** (the builder's own config parameter, read from the AST), so neither
the name nor the thing registered under it can change without failing.

**Files.** `src/breezy/runtime/trade_cli.py` (new — the CLI, `build_trading_node`,
`_run_node`, the exit contract); `src/breezy/runtime/node_config.py`
(`build_trading_node_config`, a third builder; the two existing builders
byte-unchanged); `src/breezy/runtime/settings.py` (`load_trading_settings`);
`pyproject.toml` (`[project.scripts]` entry `breezy-trade`, and one
`ignore_imports` entry `breezy.runtime.trade_cli -> nautilus_trader`);
`tests/unit/test_runtime_node_config.py` (the count pin `== 2` to `== 3` and the
per-site value table); new `tests/unit/test_trade_cli.py` and
`tests/contract/test_trading_node_composition_contract.py`. **No file under
`src/breezy/adapters/` is touched**, which is why this increment does not move
the N2 exact-set pin.

**Barriers.**
- **The node-config barrier is narrowed, not relaxed** — the table above, with
  the count pin staying an equality and the two existing sites asserted
  byte-unchanged. Strictly stronger in five ways, enumerated above.
- **Cage layers 1-3 untouched.** This increment adds no module under
  `adapters/polymarket_us/`, so `find_execution_egress_modules()`,
  `scan_write_egress()` and both `PERMITTED_METHODS` frozensets are unaffected
  and their pins must still pass unchanged.
- **B6a and B6b unchanged.** No `LiveExecutionClient` subclass, no import of one,
  no permit minted: `exec_clients={}` at the new site, pinned by the table.
- **`strategies=[]` and `exec_algorithms=[]` at the new site are permanent in
  this plan**, asserted at all three sites unconditionally.
- **No new egress.** The trading node's only network surface is the existing
  data client's GET + WS, reached through the byte-identical read stack; the CLI
  itself opens nothing, and RED 3 asserts `build_trading_node` opens no socket.

**Completion.** A Breezy `TradingNode` for the trading role exists, starts from
its own entry point, and carries exactly one Polymarket.us data client and no
execution path. Clause (a) of the goal state holds at the data half, and an
operator whose trader never starts learns it from a non-zero exit code. From
here, every increment names **this** node as the thing it changes.

---

### NS-4 — `exec/endpoints.py` + `exec/reports.py` on the EXISTING GET stack

**Null hypothesis: NATIVE — insufficient.** Nautilus defines the three report
types and gathers them in `generate_mass_status`
(`live/execution_client.py:499-503` `[V]`), which the engine calls at startup
(`live/execution_engine.py:1706-1712` `[V]`). It supplies no mapping from this
venue's JSON. **GENUINELY ABSENT: the mapping only.**

**Goal.** A frozen endpoint table and pure report mappers. Every source is
`GET`, so this reuses `PolymarketUSHttpClient` byte-identical and adds **no**
write capability.

| Nautilus surface | Venue call `[V]` (SDK snapshot) |
|---|---|
| `generate_account_state` (NS-5) | `GET /v1/account/balances` — `resources/account.py:16` |
| `generate_position_status_reports` | `GET /v1/portfolio/positions` — `resources/portfolio.py:18` |
| `generate_order_status_reports` | `GET /v1/orders/open` — `resources/orders.py:35` |
| `generate_order_status_report` | `GET /v1/order/{order_id}` — `resources/orders.py:42` |
| `generate_fill_reports` | `GET /v1/portfolio/activities` — `resources/portfolio.py:26` |

Every write endpoint on the same SDK resource — `POST /v1/orders` (`:27`),
`POST /v1/order/{id}/cancel` (`:47`), `.../modify` (`:55`),
`POST /v1/orders/open/cancel` (`:63`), `POST /v1/order/preview` (`:71`),
`POST /v1/order/close-position` (`:79`) `[V]` — is **absent from the table by
construction, not by comment**. The table is equality-pinned as a frozenset of
`(method, path-template)` pairs, and that **every method in it is `"GET"`** is
asserted separately, so an added entry fails twice.

**`exec/endpoints.py` holds paths and nothing else.** No HTTP call, no `.post`,
no `.request`, no decision, no `except`. It is data.

**`exec/reports.py` is pure.** No I/O, no clock read, no cache read, no
decision. Input: a mapping decoded from a response body plus the values the
caller supplies (`account_id`, `ts_init`). Output: a list of reports and a list
of named per-record refusals. **It never raises.** Purity is proven
behaviourally — the module is imported and called with no client, no clock and
no cache in scope, and asserted to produce identical output on two calls — not
by an AST name blacklist, which one level of indirection defeats.

**Refuse per RECORD, and then fail reconciliation as a whole.** These are two
rules, and the predecessor had only the first.
*Per record:* `generate_mass_status` gathers the three plural coroutines in a
bare `asyncio.gather` inside one `try` with no `return_exceptions`, and returns
`None` on any exception (`live/execution_client.py:498-514` `[V]`). A mapper that
raises therefore discards **all three** report types. So no mapper raises: each
returns what it could map plus a named `UnmappableRecordError` per record it
could not, every one counted and alerted with the field that was missing or
unrecognised.
*As a whole:* a partial map must never present as a clean reconciliation. So
NS-5's client, having called `super().generate_mass_status(...)`, returns `None`
when any per-record refusal occurred. The engine counts `None` as a failure for
that client (`live/execution_engine.py:1721-1727` `[V]`), reconciliation fails,
and `self._trader.start()` (`system/kernel.py:1039` `[V]`) is never reached.
Diagnostically nothing is lost — every refusal was already logged and alerted —
and the outcome is native fail-closed with no authored machinery.
**This rule is correct for NO-SEND and WRONG for SEND**, and that is not a
parenthetical: discarding a reconciliation while holding a live position
abandons it, with no cancel and no exit. It is carry-forward row A1, and the implementer writes that sentence as a comment above the
`return None`, so the successor plan meets it in the code and not only in a
document.

**`open_only` is silently ignored, and that is a venue limitation, not a
choice.** `generate_mass_status` issues `GenerateOrderStatusReports(open_only=False)`
(`live/execution_client.py:475-481` `[V]`) — the engine is asking for *all*
order status, not just open. The venue's only authenticated order listing is
`/v1/orders/open` (`resources/orders.py:35` `[V]`); `/v1/order/{order_id}`
(`:42`) requires an id we do not have for an order we have never seen. So the
mapper honours `open_only=False` as far as the venue permits and **states the
gap in its docstring and in one test**, rather than silently returning open
orders in response to a request for all of them.

**A `FillReport` without a matching `OrderStatusReport` is dropped natively.**
Fills are keyed by `venue_order_id` and applied only inside the loop over
`mass_status.order_reports` (`live/execution_engine.py:1881-1907` `[V]`). With
`/v1/orders/open` as the only order source, every fill of an order that has
since closed is discarded by the engine before Breezy sees any effect. The
mapper still maps them — they are cheap, and they are correct input the moment
an order source covering closed orders exists — but **no clause of the goal
state depends on a fill reaching the cache**, and positions come from the
position reports instead. Stated here so nobody later reads "fills are mapped"
as "fills are applied" (OQ-10).

**Every decode is refused unless it was observed.** The fixed-point question —
does the venue send a price as `0.53`, `53`, or `530000`? — is answered by NS-1's
artifact or not at all. A guessed decode reading a price 100x wrong is worse
than a refusal; the mapper refuses by name, per record.

**The position mapper has two rules that are not obvious and are load-bearing
for clause (c).**

*1. `venue_position_id` is set to `None`, always.* It is not cosmetic: it
chooses the reconciliation **branch**. `_reconcile_position_report` routes to
`_reconcile_position_report_hedging` whenever it is not `None`, and to the
netting path otherwise (`live/execution_engine.py:2331-2334` `[V]`). The venue's
positions response is a **keyed map** — `GetUserPositionsResponse.positions` is a
`dict[str, UserPosition]` (B-21 `[V]`) — so the obvious mapping puts that key
here and silently takes the hedging branch, on which `oms_type=NETTING`, F-2 and
every quantity cite in this plan describe a different function. Pinned by unit
test, and refused again at NS-5 (rule 2c) because mapper and client are separate
commits.

*2. `avg_px_open` MUST carry a real venue cost basis, and a record without one
is REFUSED like any other unmappable record.* With `avg_px_open=None` the engine
enters the position at price **zero** through a five-step fallback chain (NS-5
rule 2b, verified end to end). This makes OQ-2 — which venue field carries the
average entry price — a **hard prerequisite of clause (c)** rather than the
curiosity revision 2 called it: if NS-1's artifact does not answer it, this
mapper refuses every position record and the process does not trade. `cost /
netPosition` is the candidate and it is **not** to be used until the artifact
confirms both fields' meaning and scale.

**REDs — and what makes each go red.**
1. Each mapper round-trips the shapes recorded by NS-1 into the correct report
   type. *Red today:* the module does not exist.
2. An unmappable fill record leaves the order-status and position lists
   **intact**, increments a named counter, and emits an alert. *Red today:* no
   mapper; and an implementation that raises fails this for the right reason.
3. The endpoint frozenset is **equality-pinned** and every method in it is
   `"GET"`; adding any entry fails. *Red today:* no table.
4. `find_write_egress_violations` over `exec/endpoints.py` reports **only** V2
   violations, and `scan_write_egress(("src","scripts"))` reports zero
   violations outside that one exact path. *Red today:* the file does not exist,
   and once it does the scan fails until the exact-path allowance lands in the
   same commit.
5. `uv run lint-imports` passes. *Red today:* `exec/reports.py` importing the
   Nautilus report types breaks the forbidden-import contract until its
   `ignore_imports` entry lands in the same commit — the container revision 1
   never named.
6. `exec/endpoints.py` contains **no** `import` statement, asserted on its AST.
   *Red today:* the file does not exist; the assertion exists so that the "it
   imports nothing, so it needs no `ignore_imports` entry" claim above cannot
   quietly stop being true.
7. The order-status mapper's docstring and one test record that the venue cannot
   satisfy `open_only=False`. *Red today:* no mapper.
8. *(Not a RED, flagged as such.)*
   `assert is_venue_touching("src/breezy/adapters/polymarket_us/exec/reports.py", tree) is True`
   passes by rule C1 the moment the path string exists, before any file lands.
   It is a regression pin on C1, not a discovery, and it is listed here so it is
   not miscounted as evidence.

**Files.** `src/breezy/adapters/polymarket_us/exec/endpoints.py`;
`src/breezy/adapters/polymarket_us/exec/reports.py`; `pyproject.toml` (one
`ignore_imports` entry, see Barriers); `tests/unit/test_polymarket_us_readonly_guard.py`
and `tests/unit/test_execution_egress_firewall_guard.py` (the V2 allowance and
the N2 exact-set pin); new `tests/unit/test_polymarket_us_exec_reports.py`;
`scripts/venue/polymarket_us_auth_smoke.py` **and its test module
`tests/unit/test_polymarket_us_auth_smoke.py`** (NS-1 RED 4 pins the recorder's
path set; this increment adds a fourth path, so that assertion is updated here
or the increment cannot go green). **Revision 1 had no Files section here at
all**, which is how the `lint-imports` container went missing.

**The operator step, inside this increment.** Once `exec/endpoints.py` exists,
the NS-1 recorder is pointed at `GET /v1/orders/open` by **importing**
`ORDER_PATH_OPEN` from `exec/endpoints.py` rather than restating the literal, so
no second file is ever V2-allowlisted. A second dated evidence artifact is
emitted. NS-4 is not complete until it exists, or until the order-status mapper
is shipped refusing by record with that stated (see NS-1's fallback).

**Barriers.** **B4/V2 narrowed** — the first and only allowance this increment
creates. **`lint-imports`:** `exec/reports.py` imports the Nautilus report types,
so `pyproject.toml` gains
`breezy.adapters.polymarket_us.exec.reports -> nautilus_trader`, of exactly the
same shape as the twelve existing adapter entries (`:88-142` `[V]`), in the same
commit; CI runs `uv run lint-imports` (`.github/workflows/tests.yml:37` `[V]`).
`exec/endpoints.py` imports nothing and needs no entry — asserted, so that an
import added to it later fails rather than silently acquiring one. It is an **exact path** (`exec/endpoints.py`), never a prefix, paired in
the same commit with: the `(method, template)` frozenset equality pin, the
all-methods-are-GET assertion, `_ORDER_PATH_RE` pinned, and
`assert is_venue_touching(<that path>) is True`. **V1, V3 and V4 apply in full —
no write-method literal, no `.post`, no `.request`, no `getattr` bypass,
anywhere in this increment, including inside the allowlisted file.** **NS-2's
AST ban set (`_SHORT`, `OUTCOME_SIDE_NO`, any `1 - price` form) is re-asserted
over the two new modules in this commit** — NS-2's version scanned a directory
holding only `__init__.py` and was vacuous. **The N2 exact-set pin (NS-0 RED 4)
grows from one entry to THREE** —
`exec/__init__.py`, `exec/endpoints.py`, `exec/reports.py` — in this same
commit, or this increment cannot go green.

**Completion.** `scan_write_egress()` reports zero violations outside the one
V2-allowlisted path. Clause (e) of the goal state is now non-trivially true.

---

### NS-5 — `exec/client.py`: the client that reconciles truthfully and refuses everything

**Null hypothesis: NATIVE — sufficient for the machinery, insufficient for six
seams.** `LiveExecutionClient` supplies everything but eight
`NotImplementedError` coroutines (`live/execution_client.py:598-636` `[V]`) — two
lifecycle (`_connect`, `_disconnect`) and **six order-bearing** — and the four
report coroutines (`:343-438` `[V]`). **GENUINELY ABSENT:** the `AccountState`
emission, `_set_account_id`, `_query_account`, the report precondition, the
refusal latch, and an alert sink in this process.

**Goal.** One `PolymarketUSExecutionClient(LiveExecutionClient)`, one
`PolymarketUSExecClientConfig`, one `PolymarketUSLiveExecClientFactory`,
registered into NS-3's node.

**1. `account_id` must be set explicitly, first.** `execution/client.pyx:135`
`[V]` initialises `self.account_id = None`, and `_set_account_id` (`:148-152`,
which asserts `self.id.to_str() == account_id.get_issuer()`) is the only setter.
The failure mode is silent in exactly the way this plan exists to prevent:
`_await_account_registered` logs "Cannot await account registration: account_id
not set" and **returns as if successful** (`live/execution_client.py:544-546`
`[V]`). A `_connect` that fetched balances, called `generate_account_state` and
awaited registration would produce one warning and **no account in the cache**.
`_connect` therefore, in this order: **wait for instruments** (rule 2e),
`_set_account_id(...)`, fetch balances, assert currency identity,
`generate_account_state(...)`, `_await_account_registered()`, then **assert
`self._cache.account(self.account_id) is not None`** — never trusting the
await's return.

*One constraint on the identifiers, found by trying it rather than by reading
the assertion.* `_set_account_id` asserts `self.id.to_str() ==
account_id.get_issuer()`, and `get_issuer()` splits on the **first hyphen**:
constructing a client as `ClientId("POLYMARKET-US")` with
`AccountId("POLYMARKET-US-001")` raises, because the issuer parses as
`"POLYMARKET"` (`uv run python`, both cases run). `POLYMARKET_US` — the name
already used throughout this tree — is hyphen-free and passes, with the account
id `f"{POLYMARKET_US_CLIENT_NAME}-{suffix}"`. Pinned by test, because the failure
is a startup crash and the fix is a naming convention nobody would guess.

**2. Reconciliation truth is enforced on the INPUT *and* verified on the
OUTPUT. The post-reconciliation seam EXISTS — revision 2 said it did not, and
that was the fifth absence-claim failure in this workstream.**

*The seam, established by doing the thing rather than searching for it.*
`_reconcile_execution_mass_status` publishes the mass status on
`reports.execution.{mass_status.venue}` (`live/execution_engine.py:1941-1944`
`[V]`) **after** every order and position report has been applied (the position
loop ends at `:1937`) and **before** `return all(results)` (`:1949` `[V]`), and
`MessageBus.publish` dispatches **synchronously** to each subscriber's handler
(`common/component.pyx:2832-2834` `[V]`). All of that call chain runs inside
`_await_execution_reconciliation` before the kernel decides. An
`ExecutionClient` owns `self._msgbus` and can subscribe to it.

**Probe used, and why this one has no blind spot:** two positive experiments
under `uv run python`, not a search. (1) A real `MessageBus`, a handler
subscribed to `reports.execution.POLYMARKET_US`, and a publish — the handler ran
*between* the statements before and after the publish, proving synchronous
dispatch; the wildcard form `reports.execution.*` also matched. (2) A real
`ExecutionClient` built from `test_kit` stubs — `client._msgbus.subscribe(...)`
then `msgbus.publish(...)` delivered the message. **Revision 2's probe grepped
`live/execution_client.py` and `execution/client.pyx`; the seam is in a third
file, and a search for something that is not where you look will always find
nothing.** The rule this plan now follows, stated once for every absence claim
in it: *try to do the thing.* Section 12 makes it a review instruction.

*A second thing revision 2 never found:* `_validate_reconciliation_state`
(`:2130-2179` `[V]`), a native post-application consistency check over
venue-order-id indexing — which **only logs**, collecting `issues` and emitting
one `warning`. It is evidence that the framework itself expects post-application
divergence, and it is not a control.

**So the decision is BOTH, and each half is here for a reason the other cannot
serve:**

- **(i) The input precondition is the only lever that can STOP the trader.** The
  publish happens after `results` is assembled, and a subscriber cannot change
  `all(results)`. Refusing before handing over — returning `None` from
  `generate_mass_status` — is still the only route to a failed reconciliation.
- **(ii) The post-application verifier is the only thing that can SEE whether
  the cache reflects the venue.** Revision 1's `_assert_reconciled` was
  *mistimed*, not impossible: it read the cache before the engine wrote to it.
  Moved to the publish handler, it reads the cache after.

**(a) The input precondition — three checks, each with its own fail-open
behind it.** Every report this client emits must satisfy all three, and any
failure refuses the whole set (counter, `instrument_id` in a CRITICAL alert,
`generate_mass_status` returns `None`):

| Check | The fail-open it closes |
|---|---|
| `self._cache.instrument(report.instrument_id) is not None` | the instrument-not-loaded family — **five** identical DEBUG + `return True` sites (`:2396-2400`, `:2435-2439`, `:2473-2477`, `:3057-3062`, `:3087-3092` `[V]`) |
| `report.avg_px_open is not None` on every `PositionStatusReport` | the zero-cost-basis chain (rule 2b) |
| `report.venue_position_id is None` on every `PositionStatusReport` | branch misrouting (rule 2c) |

**(b) `generate_missing_orders=True` is right in MECHANISM and dangerous in
DEGREE — it can enter a real venue position at a cost basis of ZERO.** The
native default is `True` and reverting to it was correct; that was a claim about
the default, and it said nothing about the behaviour. LESSONS L-2 exactly. The
chain, every step verified:

1. Cache flat, venue reports a position → netting diff path (`:2557`).
2. `_create_position_reconciliation_report` (`:2839`) calls
   `calculate_reconciliation_price(..., target_position_avg_px=report.avg_px_open, ...)`
   (`:2855-2861` `[V]`). Its documented scenario 1 is *flat to position:
   reconciliation_px = target_avg_px* (`live/reconciliation.py:549-586` `[V]`) —
   so with `avg_px_open=None` it returns `None`.
3. Fallback 1: `self._cache.quote_tick(report.instrument_id)` (`:2872` `[V]`).
   **`None` in this process** — with `strategies=[]` nothing subscribes, so no
   quote is ever cached.
4. Fallback 2: `current_avg_px`, which is `None` for a flat cache (`:2879-2880`).
5. `else:` branch at `:2946-2954` `[V]` — `avg_px = None` (`:2949`), a warning, and a
   synthetic **MARKET** `OrderStatusReport` with `avg_px=None`, `FILLED`
   (`:2986-3010` `[V]`).
6. `_reconcile_order_report` logs `"report.avg_px was `None` when a value was
   expected"` (`:3103` `[V]`) and continues.
7. `_generate_inferred_fill` → `create_inferred_order_filled_event`: `order.avg_px`
   is `None`, `report.avg_px` is falsy, `report.price` is `None` on a MARKET
   order, so `last_px = instrument.make_price(0.0)`
   (`live/reconciliation.py:492-493` `[V]`, carrying the comment *"Retain
   original fallback for now"*).
8. The diff report's return value is **discarded** — `if diff_report:
   self._reconcile_order_report(...)` with no result captured (`:2556-2557`
   `[V]`) — and `_reconcile_position_report_netting` returns `True` (`:2606`
   `[V]`).

**Net: the position enters the cache at quantity-correct, price-zero, and
reconciliation reports success.** Clause (c) would have read green on a false
cache. **The fix is at the input, and it is the only place it can be**: NS-4's
position mapper sets `avg_px_open` from a real venue cost basis and NS-5 refuses
any report without one, which puts step 2 on scenario 1 and produces a **LIMIT**
report priced at the venue's own average (`:2919-2945` `[V]`). This promotes
OQ-2 from a curiosity to a **hard prerequisite of clause (c)** — see rule 2e.

**(c) `venue_position_id` chooses the reconciliation BRANCH, and every cite in
this plan is netting-only.** `_reconcile_position_report` routes to
`_reconcile_position_report_hedging` whenever `report.venue_position_id is not
None`, and to the netting path otherwise (`:2331-2334` `[V]`). The venue's
positions response is a **keyed map** (`GetUserPositionsResponse.positions` is a
`dict[str, UserPosition]`, B-21 `[V]`), so a mapper that reaches for the obvious
identifier would put the key there and silently take a branch on which F-2, the
`generate_missing_orders` behaviour and every quantity cite in this document are
about a different function. **NS-4's mapper sets `venue_position_id=None`,
pinned by unit test, and NS-5 refuses a non-`None` one** — belt and braces,
because the mapper and the client are separate commits and the branch is chosen
by data, not by config. `oms_type=NETTING` and this pin now agree.

**(d) The post-application verifier.** In `_connect`, the client subscribes to
`reports.execution.{venue}` with a handler that, for each
`PositionStatusReport` it published, asserts `self._cache` holds a position for
that instrument at the reported signed quantity **and** at
`avg_px_open` within the same 0.01% relative tolerance the engine's own log-only
check uses (`:2591` `[V]`). Any mismatch: counter, CRITICAL alert naming
the instrument, refusal latch set. It **cannot** fail the reconciliation — that
is stated, not glossed — and it is what makes clause (c)'s second half
falsifiable (RED 11b). It also covers the two paths the input precondition
cannot: a native fail-open firing on data that passed the precondition, and the
hedging branch if the `venue_position_id` pin is ever broken.

**(e) The ordering this all depends on is NOT guaranteed by the kernel, and
revision 2 claimed it was.** `start_async` runs `_connect_clients()` `:1022`,
`_await_engines_connected()` `:1024`, then reconciliation `:1028` `[V]` — but
that proves only that each client's `_connect` **returned**. Instrument delivery
is **asynchronous**: Breezy's data client calls `_handle_data(instrument)` per
instrument (`data.py:767-775` `[V]`), which reaches
`LiveDataEngine.process`, and that **enqueues** (`live/data_engine.py:343`
`[V]`); `check_connected` (`data/engine.pyx:324`) does not drain the queue. This
tree already knows the race — `data.py:881-886` `[V]` logs *"cache.instrument is
None after engine push; refusing to subscribe"* and Breezy's discovery path
degrades on it. **And the mitigation suggested in review does not apply:**
`reconciliation_startup_delay_secs` (default `10.0`, `live/config.py:199` `[V]`)
is awaited **after** `self._startup_reconciliation_event.wait()`
(`live/execution_engine.py:616-626` `[V]`), before the *continuous* checks — it
does nothing for startup reconciliation. So the exec client establishes the
precondition itself: **`_connect` waits, bounded, until
`self._cache.instrument_ids(venue=POLYMARKET_US_VENUE)` is non-empty before
returning**, and on timeout refuses — which fails `_await_engines_connected`,
the FIRST gate, and is caught by the trader-state exit contract.

*The consequence of the instrument check, stated rather than discovered later:*
the provider loads weather markets only, so a venue position in any other market
refuses reconciliation and the process does not trade. That is the designed
answer under goal clause (c); carry-forward row A10 records that the SEND half
must re-decide it.


**3. The currency identity, asserted at emission.** The emitted
`AccountBalance.currency` must be identically `USD`, which is the
`BinaryOption.currency` every Breezy instrument carries (`parsing.py:1204`
`[V]`). A balance emitted as `USDC` produces an account object that is present
and useless: `balance_free(USD)` returns `None` for a currency the account does
not hold. `_connect` fails closed on it. `AccountBalance.free` carries the
venue's **available/withdrawable** figure and never a total including
order-locked collateral; `locked` carries the difference. Both rules are pinned
by contract test against the **field names and types** NS-1 recorded — NS-1
records no values, so no test may assert one.

**4. `_query_account` is defined explicitly.** It is called
(`live/execution_client.py:332` `[V]`) and **not defined anywhere in the class**
— probed by grepping `live/execution_client.py` and `execution/client.pyx` for
`def _query_account`, which finds only the call `[V]`. **That probe sees those
two files; it would not see a definition injected by a mixin or a subclass, and
none exists in our tree.** Omitting it raises `AttributeError` inside a created
task.

**5. Per-coroutine refusal semantics — six coroutines, three event types.**
A blanket "all eight emit `OrderDenied`" is wrong twice: `_connect`/`_disconnect`
take no command, and `OrderDenied` is reachable only from `INITIALIZED` /
`RELEASED` (`model/orders/base.pyx:95,107` `[V]`), so on an `ACCEPTED` order it
raises `InvalidStateTrigger`, which `_apply_event_to_order` catches, warns about,
and `return True` (`execution/engine.pyx:1586-1594` `[V]`) — the refusal
vanishes.

| coroutine | command | IDs the command carries | event emitted |
|---|---|---|---|
| `_submit_order` | `SubmitOrder` | `command.order` (`messages.pxd:124-125` `[V]`) | `generate_order_denied(strategy_id, instrument_id, client_order_id, reason, ts_event)` — five params (`execution/client.pyx:370-406` `[V]`) |
| `_submit_order_list` | `SubmitOrderList` | `command.order_list.orders` (`:139-140` `[V]`) | one `generate_order_denied` **per order** |
| `_modify_order` | `ModifyOrder` | `client_order_id`, `venue_order_id` (`:156-159` `[V]`) | `generate_order_modify_rejected(strategy_id, instrument_id, client_order_id, venue_order_id, reason, ts_event)` (`execution/client.pyx:531-537` `[V]`) |
| `_cancel_order` | `CancelOrder` | `client_order_id`, `venue_order_id` (`:175-178` `[V]`) | `generate_order_cancel_rejected` — same six params (`execution/client.pyx:575-581` `[V]`) |
| `_cancel_all_orders` | `CancelAllOrders` | adds only `order_side` (`:188-189` `[V]`) — but **inherits `client_id`, `trader_id`, `strategy_id` and `instrument_id` from `TradingCommand`** (`:110-121` `[V]`); what it lacks is a `client_order_id` | one cancel-rejected per order resolved from `self._cache.orders_open(instrument_id=command.instrument_id, side=command.order_side)` (`cache/cache.pyx:4710-4716` `[V]`) — which is well-formed precisely *because* `instrument_id` is inherited; when that set is empty, **no event** — counter and alert only |
| `_batch_cancel_orders` | `BatchCancelOrders` | `command.cancels`, a list of `CancelOrder` (`:199-200` `[V]`) | one cancel-rejected per element |

Two honest consequences, written into the module docstring rather than
discovered by the first SEND-half reader:
- `OrderModifyRejected` / `OrderCancelRejected` change an order's state only from
  `PENDING_UPDATE` / `PENDING_CANCEL` (`model/orders/base.pyx:1055-1060` `[V]`);
  this client never emits `OrderPendingUpdate` / `OrderPendingCancel`, so the
  rejection is published on the message bus and recorded on the order, and the
  order's status is untouched. No exception is raised — unlike the `OrderDenied`
  path, the FSM is simply not triggered.
- With NS-3's `strategies=[]`, **no order can exist for these five paths to act
  on.** They are barriers, exercised by tests and by nothing else. Their value is
  that the first caller in the SEND half meets a named, counted, alerted refusal
  instead of a `NotImplementedError` — and `_submit_order`, the only one a
  strategy reaches first, is the one whose `OrderDenied` is fully effective.

Every refusal increments a counter named by a module constant (one per
coroutine, so a denial is greppable and countable rather than a formatted
string) and emits an alert at `WARN`.

**6. `calculate_commission` is NOT overridden, and that is a decision with a
consequence.** The base returns `None` (`execution/client.pyx:165-194` `[V]`).
It is reachable in NO-SEND: an `OrderStatusReport` whose `filled_qty` exceeds the
cached order's makes the engine generate an inferred fill (`:3220`,
`_generate_inferred_fill` at `:3485-3505` `[V]`), which passes this client to
`create_inferred_order_filled_event`, and a `None` commission **falls back to
`Money(0, quote_currency)`** (`live/reconciliation.py:503-507` `[V]`). So a
reconciled fill records zero fee. No read this plan performs establishes the
venue's fee model, and nothing in NO-SEND consumes realised PnL — no strategy, no
sizing, no exit. Zero is therefore recorded knowingly, and the constraint has a
carry-forward row A2: **a SEND half that computes PnL must override
this before it trusts a reconciled fill.**

**7. Reconciliation failure must be LOUD, because the process survives it.**
When reconciliation fails, `start_async` returns early (`system/kernel.py:1028-1029`
`[V]`) and `run_async` goes on to log `RUNNING` (`live/node.py:352` `[V]`) and
await the queue tasks (`:357+` `[V]`): the process daemonises with no trader and
would otherwise exit 0. So, **before** returning `None` from
`generate_mass_status`, the client emits a `CRITICAL` alert and sets a refusal
latch. The alert cannot wait for shutdown — `_disconnect`, which closes the
webhook sink, never runs on that path.

*What the latch is FOR, now that it is not what the exit code depends on.* The
exit contract asserts the positive — `node.trader.state == ComponentState.STOPPED`
after `run()` and before `dispose()` — which covers all three silent kernel
gates (section 1) including the two no latch could ever see. The latch is
**diagnosis**: it names which refusal fired, for the alert detail and for the
test surface.

*Where it lives, and the alternative rejected — stated as a reason, not an
absence.* Revision 2 claimed there is "no public `get_client`". **There is a
public accessor: `ExecutionEngine.get_clients_for_orders(list[Order])`
(`execution/engine.pyx:364-400` `[V]`).** It is unusable here for a stated
reason rather than a missing one: it resolves clients from `order.venue` and
`cache.client_id(order.client_order_id)`, so it needs at least one `Order`
object, and this process — `strategies=[]`, every submission refused — never has
one. Fabricating an `Order` in `trade_cli` purely to look a client up is worse
than a module constant. So the latch is a **module-level object in
`exec/client.py`** with `set(reason)` / `is_set` / `reset()`, imported directly.
The cost is module-level mutable state: the exec test module carries an autouse
fixture calling `reset()`, and RED 12c asserts a freshly imported module is
unlatched.

**Account shape, chosen once rather than defaulted.**
`account_type=AccountType.CASH`; `base_currency=None` (multi-currency, matching a
per-currency balance list) with rule 3's identity check as the control;
`oms_type=OmsType.NETTING`, pinned by test. Config pins, each stated rather than
defaulted because a defaulted value and a chosen one are indistinguishable in
review: `reconciliation=True` (`live/config.py:177` `[V]`),
`generate_missing_orders=True` (rule 2(a); native default, `:183` `[V]`),
`filter_unclaimed_external_orders=False` (native default already `False`, `:180`
`[V]`; set `True` it makes the engine silently discard an unclaimed external
report, `live/execution_engine.py:3575` `[V]`), `filter_position_reports=False`
(native default, `:181` `[V]` — set `True` it drops **every** position report and
goal clause (c) becomes unachievable in silence), `open_check_interval_secs=None`
(`:188` `[V]`) and `position_check_interval_secs=None` (`:195` `[V]` — nothing
this process does benefits from a repeated check, and enabling one before a
settlement exit exists is how a wrong-price report would fire repeatedly).

**The alert sink gets its container here, using the pattern already in the
tree.** The client takes `sink: AlertSink | None = None` and does
`self._sink = resolve_alert_sink() if sink is None else sink` — verbatim the
injection pattern at `strategy/weather_common/refusals.py:113-124` `[V]`, so
tests inject a recording sink with no monkeypatching and production resolves the
default. `resolve_alert_sink` (`health.py:495` `[V]`) is therefore called at most
once per client. The client closes the sink in `_disconnect`, duck-typing
`close()` best-effort exactly as `composition._close_alert_sink` does
(`composition.py:255-268` `[V]`), because `LoggingAlertSink` owns nothing and
`WebhookAlertSink` owns an `httpx.Client` (`health.py:479-492` `[V]`). Every
named refusal, every unmappable record and every reconciliation failure in this
plan goes through `emit_alert` (`health.py:514` `[V]`), which catches
`BaseException` so a failing sink can never abort the path it is reporting on.
**Without this, every "loud" failure this plan specifies would be log-only in
the one process that trades.**

**The factory mirrors `factories.py:320-437` `[V]`** — it asserts the config
type rather than narrowing the signature, loads credentials with blocking I/O at
`build()` time (never in a coroutine and never on a reconnect path), and builds
its own `Ed25519RequestSigner`, `NautilusHttpTransport` and
`PolymarketUSHttpClient` from the same shipped classes. Every read it issues
carries `quota_key=QUOTA_KEY_PORTFOLIO`, which already exists and is already
permitted — no quota key is added and none is widened.

**REDs — and what makes each go red.**

*Composed-node level — a real `TradingNode`, BUILT and observed directly
(section 5.1), never run:*
1. `build_trading_node(config)` yields a node with
   `node.kernel.exec_engine.registered_clients == [ClientId(POLYMARKET_US_CLIENT_NAME)]`
   and the registered client is an instance of `PolymarketUSExecutionClient`.
   *Red today:* the NS-3 site pins `exec_clients={}`, so the list is empty.
   **This is the assertion revision 1 could not make**: the three-assertion
   inference chain it used passes even when `build_exec_clients` logs
   "No LiveExecClientFactory registered" and `continue`s
   (`live/node_builder.py:231-233` `[V]`), leaving zero exec clients.
2. The same test with the factory registered under a **misspelled** name yields
   `registered_clients == []` and **fails**. *Red today:* trivially, but it is
   what makes RED 1 non-vacuous, and it pins the `name.partition("-")[0]`
   truncation at `live/node_builder.py:220` `[V]`.

*Factory level (stub msgbus/cache/clock; transport and credential loader
monkeypatched at the module — the technique
`tests/unit/test_polymarket_us_factories.py:181-182` `[V]` already uses, and the
same monkeypatch is what keeps `node.build()` socket-free above):*
3. `PolymarketUSLiveExecClientFactory.create(...)` returns a
   `PolymarketUSExecutionClient` whose `ClientId` derives from the registered
   name, whose venue is `POLYMARKET_US_VENUE`, whose `account_type` is `CASH`
   and whose `oms_type` is `NETTING`. *Red today:* no factory.
4. A client constructed with `sink=None` resolves the default sink; one
   constructed with a recording sink uses it and calls `resolve_alert_sink`
   **never**. *Red today:* no client, and an implementation that resolves
   unconditionally fails the second half for the right reason.
5. `create` rejects a config of the wrong type. *Red today:* no factory.

*Engine level (`LiveExecutionEngine` and `Cache` from `test_kit` stubs, on an
event loop, with a stub HTTP client returning NS-1-shaped payloads):*
6. After `_connect`, `cache.account_for_venue(POLYMARKET_US)` is **not `None`**
   and `account_id` is set. *Red today:* no client.
7. `_connect` with `account_id` deliberately unset does **not** silently
   succeed — it raises rather than reproducing `:544-546`'s warn-and-return.
   *Red today:* no client; and an implementation relying on
   `_await_account_registered` alone fails this for the right reason.
8. A balances payload in a non-`USD` currency makes `_connect` raise.
9. **Per coroutine, one test each, asserting the event TYPE from the table
   above:** `_submit_order` and each order of `_submit_order_list` produce
   `OrderDenied`; `_modify_order` produces `OrderModifyRejected`; `_cancel_order`
   and each element of `_batch_cancel_orders` produce `OrderCancelRejected`;
   `_cancel_all_orders` produces one cancel-rejected per open order in the cache
   matching instrument and side, and **zero events with a non-zero counter** when
   the cache holds none. Every case: the named reason constant, the counter
   incremented, an alert emitted, and **no `OrderSubmitted` ever**. *Red today:*
   no client — and an implementation that emits `OrderDenied` for the cancel and
   modify paths fails on the type assertion, which is the whole point of
   splitting it.
   **The assertion surface, named — and established by experiment, because the
   obvious two are both wrong.** Asserting on the *order object* works for the
   submit paths (`_handle_submit_order` does not emit `OrderSubmitted` before
   calling the client, so the order is still `INITIALIZED` and `OrderDenied`
   applies) but **fails silently for modify and cancel**: with no order in the
   cache the engine logs and `return`s without applying
   (`execution/engine.pyx:1261-1267`, `:1281-1287`, `:1301-1307` `[V]`).
   Asserting on the `events.order.*` topic fails for the same reason — the
   engine drops before it publishes. **The surface is the message-bus ENDPOINT
   the client sends to: `ExecEngine.process`** (`execution/client.pyx:913-917`
   `[V]`). Verified by experiment: a real `ExecutionClient` on a stub bus with a
   handler registered on that endpoint captured `OrderCancelRejected` and
   `OrderDenied`, with the reason string intact, with **no engine and no cached
   order** (`uv run python`). Each RED registers that handler and asserts on the
   captured event types.
10. `_query_account` is awaited without `AttributeError`.
11. Three refusal tests, one per input check (rule 2a): a `PositionStatusReport`
    naming an instrument **absent from the cache**; one with `avg_px_open is
    None`; one with a **non-`None` `venue_position_id`**. Each makes
    `generate_mass_status` return `None`, with the counter incremented and the
    `instrument_id` in the alert. *Red today:* no client; and an implementation
    that hands any of them over and trusts the engine fails, because the native
    paths `return True` in all three cases.
11b. **Clause (c)'s second half, which revision 2 asserted and never tested.**
    Drive a full reconciliation on a real `LiveExecutionEngine` with a stub
    client returning one valid position report, then assert on the **cache**:
    a position exists for that instrument at the reported signed quantity **and**
    at the reported `avg_px_open` within 0.01%. *Red today:* no client. **And it
    is red for a second reason that is the point of the test:** with
    `avg_px_open` set to `None` — revision 2's specification — the same test
    produces a position at price **zero** (the chain in rule 2b), so this RED
    fails against revision 2's own design and passes only against a mapper that
    supplies a real cost basis.
11c. The post-application verifier fires: with the engine driven so the cache
    ends at a quantity different from the report, the handler subscribed to
    `reports.execution.{venue}` sets the latch and emits a CRITICAL alert.
    *Red today:* no subscriber exists — and the seam it uses is proven by the
    two experiments in rule 2, not asserted.
12. An unmappable record makes `generate_mass_status` return `None` **and** the
    per-record counter is non-zero **and** the other two report lists were
    non-empty when it happened — NS-4's two rules asserted together, so an
    implementation satisfying one by violating the other fails.
12b. A reconciliation failure sets the refusal latch and emits a `CRITICAL`
    alert **before** `generate_mass_status` returns, asserted on the recording
    sink. *Red today:* no latch exists; and an implementation that alerts from
    `_disconnect` fails, because `_disconnect` is never reached on that path.
12c. A freshly imported `exec/client.py` is **unlatched**, and `trade_cli`
    returns exit code 0 for an unlatched run and non-zero for a latched one.
    *Red today:* no latch and no mapping; this is the test that makes the
    module-level latch's isolation cost visible rather than incidental.

*Static:*
13. Exactly **one** `LiveExecutionClient` subclass exists in `src/` + `scripts/`,
    at exactly `exec/client.py`, and exactly one `LiveExecClientFactory`
    subclass at exactly `exec/factories.py`; `== 1` each, with proofs that `== 0`
    and `== 2` both fail. *Red today:* the B6b barrier
    (`test_polymarket_us_readonly_guard.py:550` `[V]`) asserts **zero**, so this
    increment fails it until the narrowing lands in the same commit.
14. `scan_write_egress()` still reports zero violations outside
    `exec/endpoints.py`. *Red today:* passes today and must keep passing —
    written so that a `.post` introduced anywhere in NS-5 fails it.
15. `uv run lint-imports` passes. *Red today:* three new modules import
    `nautilus_trader` and one imports `breezy.runtime.health`.
16. **The N2 exact-set pin still holds.** NS-0 RED 4 replaced N2's `== []` with
    an equality against the exact expected set, and this increment lands three
    more `exec/` modules — so N2 **fails until its expected set is updated in
    this same commit**, to exactly
    `{exec/__init__.py, exec/endpoints.py, exec/reports.py, exec/client.py,
    exec/config.py, exec/factories.py}`. *Red today:* the pin names three files,
    not six. This is a defect revision 2 created with its own tightening and did
    not carry into the increments that trip it.

**Barriers.**
- **The N2 exact set becomes SIX entries** (RED 16). Every increment that adds
  an `exec/` module updates that set in the same commit; NS-0 states the rule,
  NS-4 grows it to three, NS-5 to six.
- **NS-2's AST ban set is re-asserted** over `exec/client.py`, `exec/config.py`
  and `exec/factories.py` in this commit — the increment that adds modules is
  the increment that proves the ban still reaches them.
- **B6b narrowed** (`tests/unit/test_polymarket_us_readonly_guard.py:550` `[V]`):
  today it bans, repo-wide in `src` + `scripts`, any class subclassing
  `LiveExecutionClient` / `LiveExecClientFactory` / `LiveExecutionClientFactory`
  **and any `ImportFrom` naming them**. It becomes: **exactly one** subclass and
  **exactly one** factory subclass, each at its exact pinned path, importable
  nowhere else — with the non-vacuity proof it never had. This is the second and
  last allowance this plan creates.
- **B6a UNCHANGED at zero.** `test_safety_chokepoint_has_no_caller_in_this_slice`
  (`:570` `[V]`) stays `== 0`: nothing in this plan calls
  `assert_live_order_submission_permitted`, because no GET requires a permit.
  The predecessor had to relax this to `== 1`; here it does not move.
- **`test_module_defines_no_execution_client_factory`
  (`tests/unit/test_polymarket_us_factories.py:461` `[V]`) stays TRUE and
  UNCHANGED** — it is scoped to `adapters/polymarket_us/factories.py`, and the
  exec factory lives at `exec/factories.py`.
- **Cage layer 4** — only the NS-3 site's `exec_clients` changes, under the
  per-site value table; `strategies` and `exec_algorithms` stay `[]` there.
- **`pyproject.toml`** gains one `ignore_imports` entry per new
  nautilus-importing module — `exec.client`, `exec.config`, `exec.factories`
  (`exec.reports`'s entry landed in NS-4) — each of the same shape as the twelve
  existing per-module entries (`:88-142` `[V]`), **plus** one entry
  `breezy.adapters.polymarket_us.exec.client -> breezy.runtime.health`: an
  upward `adapters -> runtime` import of exactly the same class as the recorded
  debt `breezy.ingest.nws_actor -> breezy.runtime.health` (`pyproject.toml:78`
  `[V]`). Recorded as inspected debt, with the alternative in OQ-3.
- **No write verb, no write attribute, no endpoint literal outside
  `exec/endpoints.py`, no signing change.**

**Files.** `src/breezy/adapters/polymarket_us/exec/client.py`, `exec/config.py`,
`exec/factories.py`; `src/breezy/runtime/node_config.py` and
`src/breezy/runtime/trade_cli.py` (the `exec_clients` site, the factory
registration, and the refusal predicate's real body); `pyproject.toml`;
`tests/unit/test_polymarket_us_readonly_guard.py` (B6b narrowing);
**`tests/unit/test_execution_egress_firewall_guard.py` (N2's expected set, RED
16)**; new `tests/unit/test_polymarket_us_exec_client.py` and
`tests/contract/test_trading_node_composition_contract.py`.

**Completion.** The full goal-state predicate holds. `breezy-trade` starts,
connects, emits a true `USD` `CASH` account, and reconciles the venue's positions
and open orders **into a cache verified against the venue's own quantities and
average prices** — or refuses, alerts `CRITICAL` and exits non-zero by way of the
trader-state check. Every order is refused on all six order-bearing coroutines,
`scan_write_egress()` is clean outside one file, and both `PERMITTED_METHODS`
frozensets are still `{"GET"}`.

---

## 8. Deferred — out of scope, with the reason

Not designed here, and **no hook is left for any of them** beyond what the
NO-SEND work independently requires.

| Deferred | Was | Why it is not here |
|---|---|---|
| The denial layer over the risk engine's fail-opens | E-5 | It denies orders *before Nautilus is consulted* on a path to a venue. There is no such path: all **six order-bearing** coroutines already refuse unconditionally at NS-5, which is strictly stronger than a conditional pre-check. The fail-opens matter the moment one coroutine stops refusing — which is the first SEND increment. |
| Settlement as exit | E-6 | Settlement realizes PnL on a position. **This plan can never open a position**, so there is nothing to settle. (It also could not use `generate_order_filled` on a filled order: `_ORDER_STATE_TABLE` has **seven** transitions *into* `FILLED` — `model/orders/base.pyx:116,124,126,136,143,150,156` `[V]` — and **zero** transitions *from* it. The predecessor said eight; the count was wrong and the load-bearing half was right.) |
| Order-source / strategy enablement | E-7 | A registered strategy exists to produce orders. Every order is refused, so registering one adds a denial trace and a second thing that can be misconfigured. `strategies=[]` stays an explicit empty literal at all three node-config sites, pinned. |
| `ExecAlgorithm`s | — | Permanently `[]` at all three sites. An `ExecAlgorithm` reaches `submit_order` in its own right (`node_config.py:213-217` `[V]`), so enabling one opens an order source outside any strategy. |
| The write chain: `exec/{signing,transport,egress}.py`, the endpoint allowlist, `POST /v1/orders`, cancel | E-8, E-12, E-13 | Every increment here is NO-SEND by construction, and "zero write capability in the tree" is a scan result rather than a policy only for as long as none of these exists. |
| The four-type authority algebra: `Submit`/`Cancel`/`ReduceOnly`/`Preview` | E-1 6.3.1, R2-BL-4 | **Multi-type authority is not needed until a write endpoint exists.** A capability type exists to distinguish which write a bearer may perform; with zero writes there is exactly one meaningful authority state, and designing four types now is designing the SEND half. |
| Permit endpoint scope (BL-8) and the fingerprint contract (BL-10) | E-1 | Both are properties of a capability minted to authorize a *request body at a path*. No permit is minted anywhere in this plan (B6a stays `== 0`). Fixing them requires inventing the scope vocabulary the deferred authority algebra is built on. **Both are hard prerequisites of the first increment that mints a capability** — see OQ-7. |
| Durable (Redis-backed) cache and crash recovery | E-2 / E-4 G6 | Durability exists so a crash *while holding a position* cannot resurrect a process blind to its exposure. No position can exist. The venue's GET surface is the source of truth at every startup. **Hard prerequisite of the first exposure-opening increment.** |
| The `(status, body) -> {terminal, retryable, AMBIGUOUS}` classification table and `RetryManagerPool` wiring | E-3, E-11 | The table exists to make an *ambiguous write* survivable. A failed read on this path already fails closed through the kernel's reconciliation gate, with no ambiguity to resolve. |
| The ambiguity latch, the one-in-flight invariant, synthetic-rejection interception | E-11 | All three are properties of an in-flight *submission*. |
| Live probes: signature scheme, preview, single-order | E-9, E-10, E-14 | Each transmits a `POST`. |
| `exec/direction.py` — the `OrderSide -> (intent, outcomeSide, action, price)` map | E-7 | It exists to construct a request body. No body is constructed. The `1.00 - X` inversion hazard is *inert* while no request is built; the AST **prohibitions** on `_SHORT`, `OUTCOME_SIDE_NO` and any `1 - price` form under `exec/` are retained at NS-2 anyway because they cost nothing. |
| The `payout_cap x price` conversion | 4.2 vs E-5 | Deleted in the predecessor's 4.2 and still specified in its E-5 — a self-contradiction in which an implementer following the increment trips the increment's own scan. **Neither the conversion nor the scan is inherited here**: no cap is computed anywhere in this plan. |
| The AST purity scan over the settlement identity function | E-6 | The identity it guarded is deferred. The *principle* is retained: this plan contains **no name-blacklist AST scan used as a proof of purity**, because one level of indirection defeats it — an impure helper called by a pure-looking function passes. Where this plan needs a property proven it proves it behaviourally (NS-4), and its AST scans are used only for *prohibitions* (a token must not appear), which indirection cannot defeat. |
| `safety.py` D-1: `consume()` compares notionals with a bare `!=` and no type check, so a `Decimal` subclass overriding `__ne__` satisfies the re-check at any magnitude (`safety.py:463` `[V]`) | NS-2 rev 1 | `consume` is reachable only from a capability, minted only by the chokepoint, which this plan pins at **zero callers**. Fixing it here changes code no path in this plan executes. The mirror it should use already exists at `safety.py:676` `[V]`. |
| `safety.py` D-3: renewal resets the operator's budget — issuance re-reads the ceilings (`:548`) and installs a fresh `_Budget` under a fresh `permit_id` (`:575`), `_PERMIT_BUDGETS` (`:332`) aggregates nothing, and `PERMIT_TTL_NS` is 15 minutes (`:157`), so renewal is forced `[V]` | NS-2 rev 1 | The fix **designs new authority state** — a process ledger keyed by `operator_id` — inside a plan whose seam is that the authority model is deferred. **Residual for the successor:** that key would be read from operator-controlled environment, so it must be pinned at first issuance and a different value refused; otherwise changing one variable mints a fresh budget, which is the same defect one level up. |


### 8.1 Carry-forward — constraints this half establishes that the SEND half must honour

These are not deferred *work*; they are **findings already paid for** that a
successor would otherwise re-derive or, worse, contradict. They are split into
two tables because they carry different evidence, and revision 2 merged them —
leaving inherited assertions as the only claims in this document exempt from its
own "nothing is inherited on trust" rule.

**8.1a — established by THIS document, each `[V]`.**

| # | Constraint | Where established |
|---|---|---|
| A1 | **`generate_mass_status` returning `None` on any refusal is correct for NO-SEND and WRONG for SEND.** Discarding a reconciliation while a position is open abandons it, with no cancel and no exit (`live/execution_engine.py:1721-1727`). NS-4 requires this sentence as a code comment above the `return None` | NS-4 |
| A2 | **`calculate_commission` must be overridden before any PnL is trusted.** Not overridden here, so a reconciliation-inferred fill records `Money(0, quote_currency)` (`live/reconciliation.py:503-507`) | NS-5 rule 6 |
| A3 | **The instrument-not-loaded fail-open has five sites** (`live/execution_engine.py:2396-2400`, `:2435-2439`, `:2473-2477`, `:3057-3062`, `:3087-3092`), all DEBUG + `return True`. The input precondition is the single control covering all five; any widening of the instrument universe must keep it | NS-5 rule 2a |
| A4 | **`generate_missing_orders=True` enters a position at price ZERO when `avg_px_open` is `None`** — five fallbacks ending at `instrument.make_price(0.0)` (`live/reconciliation.py:492-493`), with the result discarded (`:2556-2557`) and reconciliation reporting success. A real cost basis on every position report is a hard prerequisite, not a nicety | NS-5 rule 2b |
| A5 | **`venue_position_id` selects the reconciliation BRANCH** (`live/execution_engine.py:2331-2334`). This plan is netting-only and pins it to `None`; a SEND half wanting hedging must re-verify every quantity cite in this document against `_reconcile_position_report_hedging` | NS-4 mapper rule 1 |
| A6 | **The kernel has three silent exit gates**, not one (`system/kernel.py:1024`, `:1028`, `:1036`), and the portfolio one is reachable from external open orders on a CASH account (`portfolio/portfolio.pyx:289-300`). Assert the positive — `trader.state == STOPPED` — rather than enumerating gates | NS-3 exit contract |
| A7 | **Instrument delivery to the cache is asynchronous** (`live/data_engine.py:343`) and no native gate drains that queue before reconciliation; `reconciliation_startup_delay_secs` applies afterwards (`live/execution_engine.py:616-626`). Any client depending on the instrument cache at connect time must wait for it itself | NS-5 rule 2e |
| A8 | **`AccountId.get_issuer()` splits on the first hyphen**, so a hyphenated `ClientId` makes `_set_account_id` raise. `POLYMARKET_US` is safe; a rename to `POLYMARKET-US` is a startup crash | NS-5 rule 1 |
| A9 | **Order events for an uncached order are dropped by the engine before publication** (`execution/engine.pyx:1261-1267`, `:1281-1287`, `:1301-1307`), so the assertion surface for refusal events is the `ExecEngine.process` endpoint | NS-5 RED 9 |
| A10 | **OQ-11 must be RE-DECIDED, not inherited.** In NO-SEND, a venue position outside the instrument universe refuses reconciliation and the process does not trade — correct, because refusing forfeits no capability when the process cannot trade anyway. **Once trading is live the trade-off inverts:** refusing means one unrelated position halts all trading | coordinator decision 2026-08-31 |

**8.1b — INHERITED and NOT verified by this document.** Each carries the cite
its source gave. The successor's first duty is to re-verify at that cite; none
of these may be acted on as established.

| # | Constraint | Source cite | Verification status |
|---|---|---|---|
| B1 | `TradeId` is capped at **36 characters**, so a composite settlement identity is unconstructable — `TradeId("SETTLE-{slug}-{setTime}-{px}")` raises `ValueError: 'value' out of range [1, 36], was 67`, and `"SETTLE-" + slug` alone is 39 for a real weather slug. `VenueOrderId` has **no** cap, so the defect is one-sided | R3 review C-a, run against 1.231.0 with a slug from `raw/book_open_510636.json` | **Inherited, unverified here** |
| B2 | The settlement price is at `marketData.stats.settlementPx` in a `/book` response — **not** `stats.settlementPx` — and the identically-named field in a `bbo_*` response is at `marketData.settlementPx`, carrying **no** method and **no** setTime, and must be excluded | R3 review C-c | **VERIFIED HERE `[V]`**: a recursive key walk of `raw/book_closed_15806.json` yields exactly `marketData.stats.settlementPx`; `bbo_closed_15806.json` yields exactly `marketData.settlementPx`; `market_closed_15806_by_slug.json` yields no settlement key at all |
| B3 | A venue settlement **correction** is lost two ways, by mechanism: if the price changes but `setTime` does not, the `VenueOrderId` is unchanged and the order is already `FILLED`, so `_reconcile_fill_report` rejects it as an overfill with `allow_overfills=False` (`live/execution_engine.py:3333-3341`) and the correction is **discarded with a warning**; if `setTime` changes, both ids differ and a full-size fill lands on a flat position — a **phantom short** | R3 review C-d | **Inherited, unverified here** — revision 2 recorded this as a hazard label with no mechanism, which a successor could not act on |
| B4 | The settlement fill's **side, quantity, `venue_position_id` and emission precondition are unspecified** in the predecessor; a settled market Breezy never traded emits a closing report and **opens** a position at 0.00/1.00 | R3 review C-g, against `ORDER_EGRESS_PLAN.md:1369-1453` | **Inherited, unverified here** |
| B5 | The settlement gate has a fourth conjunct available for free: `settlementSetTime` at or after expiration | `ORDER_EGRESS_PLAN.md` | **Field presence verified here `[V]`** — `marketData.stats.settlementSetTime` sits beside `settlementPx` in `book_closed_15806.json`, with `settlementPriceCalculationMethod`. The **semantics** are inherited and unverified |
| B6 | The `known issuer == 1` pin collides with the operator probe scripts, which must dispatch under a permit: every route either breaks the pin or drags an exec factory into a probe script | R3 review, "The issuer `== 1` barrier collides with E-9/E-10" | **Inherited, unverified here.** Note this plan keeps the issuer barrier at `== 0` (B6a), so the collision is created by the first SEND increment, not by this one |
| B7 | **`POST /v1/orders` was reachable under TWO authority types, and the reduce-only one decremented order count but NOT budget** — leaving the operator's maximum-daily-budget ceiling with zero coverage on a path that posts live orders. Bears directly on one of the operator's two reserved controls | R3 review C-e | **Inherited, unverified here** |

---

## 9. Claims ledger

Every claim this plan makes about NautilusTrader or Breezy. `[V]` means **I
opened the file at that line and confirmed both the text and the inference drawn
from it.** Anything I could not confirm is an open question in section 10, not a
`[V]`. Nautilus paths are relative to the installed
`nautilus_trader==1.231.0`; Breezy paths are repo-relative.

### 9.1 Corrections to the predecessor's own `[V]` claims

| # | `ORDER_EGRESS_PLAN.md` said | Actually | Consequence here |
|---|---|---|---|
| **C-1** | "the process itself does not exist"; "First time a Breezy `TradingNode` exists at all" (`:19`, `:228`) | **False.** `node_factory: NodeFactory = TradingNode` (`quote_tape_cli.py:195`, `cli.py:147`) then `node_factory(config); node.build(); node.run()` (`quote_tape_cli.py:151-157`). Two real nodes are built and run. The true gap is: no trading-**role** config builder, and no `breezy-trade` entry point. | NS-3's justification rewritten. The increment survives; its stated reason does not. |
| **C-2** | E-2 "mirrors the quote tape's existing shape exactly" **and** cites `composition.py:272-310` | Two different shapes. There is no `quote_tape_composition.py`; the tape's composition is inline in `quote_tape_cli.py`. `ingest_runtime` is a `@contextmanager` yielding a runtime and never touching a node; `build_ingest_node` neither builds nor runs. | Section 5.1 picks one, names it, and every RED is written against it. |
| **C-3** | "If Redis is unreachable the process refuses to start" | Uncited, and no Nautilus code produces it: `system/kernel.py:309-329` raises only for an *unrecognized* `cache.database.type` and never probes connectivity. | Redis dropped from scope entirely (NS-3); the assertion is not made. |
| **C-4** | The node-config barrier row: `exec_clients` "`{}` to one key" | A cardinality pin, which a swapped client satisfies. | NS-3's table pins the exact key **and** the exact value expression. |
| **C-5** | "`_ORDER_STATE_TABLE` has **eight** transitions INTO `FILLED`" | **Seven** — `model/orders/base.pyx:116,124,126,136,143,150,156`. Zero transitions *from* `FILLED`, which is the load-bearing half and is correct. | Corrected at the one place the fact appears (section 8). |

The predecessor's stale text at `:473` ("primary is the endpoint") and `:2028`
describes a settlement-source arrangement its own revision 3 reverted. **No
settlement source is described anywhere in this document**, so none of that text
is inherited.

### 9.2 NautilusTrader 1.231.0 — all `[V]`

| # | Fact | Cite |
|---|---|---|
| **F-1** | `LiveExecutionClient` declares exactly **eight** coroutines to implement — `_connect` and `_disconnect`, which take no command, plus **six order-bearing** ones: `_submit_order`, `_submit_order_list`, `_modify_order`, `_cancel_order`, `_cancel_all_orders`, `_batch_cancel_orders` | `live/execution_client.py:598-636` |
| **F-2** | With `generate_missing_orders=False`, a position-quantity discrepancy logs a warning and **`return True`** — native "reconciled" does not imply "matched". Since the cache starts empty, **every** venue position is such a discrepancy. With the native `True`, the engine takes the diff path at `:2511-2563` and enters the position | `live/execution_engine.py:2501-2509`, `:2511-2563` |
| **F-3** | `generate_mass_status` gathers the three plural report coroutines in a bare `asyncio.gather` inside one `try` with no `return_exceptions`, and returns `None` on any exception | `live/execution_client.py:498-514` |
| **F-4** | A `None` mass status is counted as a reconciliation failure for that client | `live/execution_engine.py:1721-1727` |
| **F-5** | If reconciliation fails, the kernel **returns** and `self._trader.start()` is never reached. Order in `start_async`: `_connect_clients()` `:1022`, `_await_engines_connected()` `:1024`, `_await_execution_reconciliation()` `:1028`, `_trader.start()` `:1039` | `system/kernel.py:1022-1039`; `_await_execution_reconciliation` at `:1335-1349` |
| **F-6** | `_await_account_registered` warns "Cannot await account registration: account_id not set" and **returns** when `account_id` is unset | `live/execution_client.py:544-546` |
| **F-7** | `self.account_id = None` at construction; `_set_account_id` is the only setter and asserts `self.id.to_str() == account_id.get_issuer()` | `execution/client.pyx:135`, `:148-152` |
| **F-8** | `generate_account_state(balances, margins, reported, ts_event, info)` builds and publishes the `AccountState`; nothing calls it for you | `execution/client.pyx:329-367` |
| **F-9** | `generate_order_denied(strategy_id, instrument_id, client_order_id, reason, ts_event)` — **five** parameters, not four. `generate_order_modify_rejected` and `generate_order_cancel_rejected` each take **six** (`..., venue_order_id, reason, ts_event`) | `execution/client.pyx:370-406`, `:531-537`, `:575-581` |
| **F-10** | `_query_account` is **called** and **never defined** in `LiveExecutionClient` | called at `live/execution_client.py:332`. **Absence probe:** grep for `_query_account` across `live/execution_client.py` and `execution/client.pyx`, which finds only the call. That probe sees definitions in those two files; it would not see one injected by a mixin or a `.pxd`-declared method, and none exists |
| **F-11** | Native defaults: `reconciliation=True` (`:177`), `filter_unclaimed_external_orders=False` (`:180`), `generate_missing_orders=True` (`:183`), `inflight_check_interval_ms=2000` (`:184`), `inflight_check_threshold_ms=5000` (`:185`), `inflight_check_retries=5` (`:186`), `filter_position_reports=False` (`:181`), `open_check_interval_secs=None` (`:188`), `position_check_interval_secs=None` (`:195`) | `live/config.py` |
| **F-12** | `filter_unclaimed_external_orders=True` makes the engine **discard** an unclaimed external report | `live/execution_engine.py:3575` |
| **F-13** | The kernel raises `ValueError` only for an **unrecognized** `cache.database.type`; `"redis"` is the only supported value; **no connectivity probe anywhere** | `system/kernel.py:309-329` |
| **F-14** | `_ORDER_STATE_TABLE`: seven transitions into `FILLED`, zero from it | `model/orders/base.pyx:116,124,126,136,143,150,156` |
| **F-15** | `TradingNode.add_data_client_factory(name, factory)` at `:230`, `add_exec_client_factory(name, factory)` at `:251`; both take the factory **class** | `live/node.py` |
| **F-16** | `LiveExecClientFactory.create(loop, name, config, msgbus, cache, clock) -> LiveExecutionClient` is the exec-client extension point, and is the **only** composition seam for one | `live/factories.py` |
| **F-17** | ~~`TradingNode` exposes no kernel or engine accessor; a constructed exec client is not reachable from outside~~ **WITHDRAWN — the claim was FALSE.** `TradingNode.kernel` is a public **instance** attribute assigned in `__init__` (`live/node.py:71`), and `node.kernel.exec_engine` (`system/kernel.py:906-915`) `.registered_clients` (`execution/engine.pyx:212-221`) resolves. **The probe was `dir()` over the class, which cannot see instance attributes** — an absence claim inheriting its probe's blind spot. Section 5.1 and REDs 1-2 now observe the built node directly | `live/node.py:71`, `system/kernel.py:906-915`, `execution/engine.pyx:212-221` |
| **F-18** | The instrument-not-loaded fail-open has **five** sites in the reconciliation path, all DEBUG-log + `return True` | `live/execution_engine.py:2396-2400`, `:2435-2439`, `:2473-2477`, `:3057-3062`, `:3087-3092` |
| **F-19** | Fill reports are applied **only inside the loop over `mass_status.order_reports`**, keyed by `venue_order_id`, so a `FillReport` with no matching `OrderStatusReport` is silently dropped | `live/execution_engine.py:1881-1907` |
| **F-20** | An `OrderStatusReport` whose `filled_qty` exceeds the cached order's makes the engine generate an **inferred fill**, passing the execution client so `calculate_commission` is consulted; the base returns `None` and the helper substitutes `Money(0, quote_currency)` | `live/execution_engine.py:3220`, `:3485-3505`; `live/reconciliation.py:503-507`; `execution/client.pyx:165-194` |
| **F-21** | A **sixth** related fail-open: an already-closed order reporting a different `filled_qty` logs and `return True  # Consider it reconciled to avoid infinite loops` | `live/execution_engine.py:3204-3214` |
| **F-22** | `start_async` runs `_connect_clients()` (`:1022`), `_await_engines_connected()` (`:1024`), `_await_execution_reconciliation()` (`:1028`), `_initialize_portfolio()` (`:1034`), `_await_portfolio_initialization()` (`:1036`), then `_trader.start()` (`:1039`). **Three of these are silent early returns.** ~~A data client that loads instruments inside `_connect` therefore has them in the cache before reconciliation~~ — **that inference is WITHDRAWN**: the ordering proves only that `_connect` returned. `_handle_data` reaches `LiveDataEngine.process`, which **enqueues** (`live/data_engine.py:343`), and `check_connected` (`data/engine.pyx:324`) does not drain the queue | `system/kernel.py:1022-1039`; `live/data_engine.py:343` |
| **F-25** | `reconciliation_startup_delay_secs` (default `10.0`, `live/config.py:199`) is awaited **after** `self._startup_reconciliation_event.wait()`, before the *continuous* checks — it does nothing for startup reconciliation | `live/execution_engine.py:610-626` |
| **F-26** | With `report.avg_px_open is None`, the netting diff path prices the synthetic reconciliation order through five fallbacks ending at `instrument.make_price(0.0)`, entering a real position at cost **zero**; the diff report's result is discarded and the position reconciliation returns `True` | `live/execution_engine.py:2855-2861`, `:2872`, `:2946-2954`, `:2986-3010`, `:3103`, `:2556-2557`, `:2606`; `live/reconciliation.py:492-493` |
| **F-27** | `_reconcile_position_report` routes on **data, not config**: `venue_position_id is not None` takes the HEDGING branch | `live/execution_engine.py:2331-2334` |
| **F-28** | `_reconcile_execution_mass_status` publishes the mass status on `reports.execution.{venue}` after applying every report and before `return all(results)`; `MessageBus.publish` dispatches synchronously; the wildcard form `reports.execution.*` also matches | `live/execution_engine.py:1941-1944`, `:1949`; `common/component.pyx:2832-2834`; **two positive experiments under `uv run python`** |
| **F-29** | `_validate_reconciliation_state` is a native post-application consistency check that **only logs** | `live/execution_engine.py:2130-2179` |
| **F-30** | `Portfolio.initialize_orders` sets `initialized = False` when `_accounts.update_orders` fails for any open order, which gates `_await_portfolio_initialization` | `portfolio/portfolio.pyx:289-300`; `system/kernel.py:1036`, `:1351-1367` |
| **F-31** | A `Component` reads `READY` before `start()`, `RUNNING` after it, `STOPPED` after `stop()` and `DISPOSED` after `dispose()`; `Trader` is a `Component` subclass exposing `.state` | **positive experiment under `uv run python`**; `core/rust/common.pyx::ComponentState` |
| **F-32** | `AccountId.get_issuer()` splits on the **first hyphen**, so `_set_account_id` raises for a hyphenated `ClientId` | **positive experiment under `uv run python`**; `execution/client.pyx:148-152` |
| **F-33** | `ExecutionEngine.get_clients_for_orders(list[Order])` is a **public** accessor returning `ExecutionClient` objects, resolved from `order.venue` and `cache.client_id(order.client_order_id)` | `execution/engine.pyx:364-400` |
| **F-34** | The engine **drops** an order event whose order is not in the cache, before any publication | `execution/engine.pyx:1261-1267`, `:1281-1287`, `:1301-1307` |
| **F-35** | An `ExecutionClient` sends every generated order event to the msgbus **endpoint** `ExecEngine.process` | `execution/client.pyx:913-917`; **positive experiment** |
| **F-23** | `OrderDenied` is reachable only from `INITIALIZED`/`RELEASED`; on any other state `_apply_event_to_order` catches `InvalidStateTrigger`, warns and `return True`. `OrderModifyRejected`/`OrderCancelRejected` trigger the FSM only from `PENDING_UPDATE`/`PENDING_CANCEL` and otherwise leave the order untouched **without raising** | `model/orders/base.pyx:95,107`, `:1055-1060`; `execution/engine.pyx:1586-1594` |
| **F-24** | Every trading command inherits `client_id`, `trader_id`, `strategy_id` and `instrument_id` from `TradingCommand` (`messages.pxd:110-121`). `CancelAllOrders` **adds** only `order_side` (`:188-189`) — what it lacks is a `client_order_id`, not an `instrument_id`; `BatchCancelOrders` adds `cancels`, a list of `CancelOrder` (`:199-200`); `Cache.orders_open` filters by `venue`, `instrument_id`, `strategy_id`, `side`, `account_id` | `execution/messages.pxd`; `cache/cache.pyx:4710-4716` |

### 9.3 Breezy — all `[V]`

| # | Fact | Cite |
|---|---|---|
| **B-1** | Two `TradingNodeConfig` sites: `build_node_config` (ingest, `:163`; `data_clients={}` `:203`, `exec_clients={}` `:204`, `strategies=[]` `:212`, `exec_algorithms=[]` `:218`) and `build_quote_tape_node_config` (`:381`; one data client `:459`, `exec_clients={}` `:460`, `strategies=[]` `:463`, `exec_algorithms=[]` `:464`). Both pin `CacheConfig(database=None, flush_on_start=False)` (`:199`, `:455`) | `src/breezy/runtime/node_config.py` |
| **B-2** | Both existing processes build and run a real `TradingNode`: `node_factory: NodeFactory = TradingNode` (`quote_tape_cli.py:195`, `cli.py:147`); `node_factory(config); node.build(); node.run()` (`quote_tape_cli.py:151-157`); ingest goes through `build_ingest_node` (`cli.py:129`) | as cited |
| **B-3** | The tape's composition is **inline** in `quote_tape_cli.py` (`run` `:192`, `_run_node` `:141`); the ingest composition is a `@contextmanager` (`composition.py:272`) plus a separate `build_ingest_node` (`:462`) that neither builds nor runs | as cited |
| **B-4** | Entry points are `breezy` (`:256`) and `breezy-quote-tape` (`:260`) only; `:257-259` states the two are deliberately separate processes | `pyproject.toml` |
| **B-5** | The node-config barrier pins `len(_node_config_calls()) == 2` (`:340`) and quantifies over **every** site asserting `exec_clients` / `strategies` / `exec_algorithms` are empty literals (`:343-349`). `data_clients` is **not** among the parametrized fields | `tests/unit/test_runtime_node_config.py` |
| **B-6** | B6b bans, repo-wide in `src` + `scripts`, any subclass of `LiveExecutionClient` / `LiveExecClientFactory` / `LiveExecutionClientFactory` **and any import of those names** | `tests/unit/test_polymarket_us_readonly_guard.py:550` |
| **B-7** | B6a asserts **zero** callers of `assert_live_order_submission_permitted` in `src` + `scripts` | `tests/unit/test_polymarket_us_readonly_guard.py:570` |
| **B-8** | `_WRITE_METHODS = {POST,PUT,PATCH,DELETE}` (`:112`), `_WRITE_ATTRS = {post,put,patch,delete,request}` (`:113`), `_ORDER_PATH_RE = /v\d+/orders?\b` (`:114`) — the regex matches `/v1/orders`, `/v1/orders/open` and `/v1/order/{id}`, and does **not** match `/v1/account/balances`, `/v1/portfolio/positions` or `/v1/markets/{slug}/settlement`. `is_venue_touching` returns True for anything under `src/breezy/adapters/polymarket_us/` (C1, `:189`) and under `scripts/venue/` (C2, `:128-131`) | `tests/unit/test_polymarket_us_readonly_guard.py` |
| **B-9** | `_EGRESS_MODULE_BASENAMES` (`:161-171`) contains none of this plan's filenames; `_EGRESS_FUNCTION_NAMES` (`:178-180`) contains no underscore form; `_EGRESS_CLASS_BASES` (`:174`) does contain `LiveExecutionClient`. `find_execution_egress_modules` (`:447`) appears only in this module. `test_n2_the_shipped_tree_currently_has_no_execution_egress_module` (`:592-594`) is the "currently empty" pin | `tests/unit/test_execution_egress_firewall_guard.py` |
| **B-10** | N2's canary probes through the **original** pyo3 `HttpClient` captured before conftest's block (`:387-413`), so the autouse socket patch does not interfere with it. `Connection refused` classifies as REACHED, never blocked (`:331-334`) | same file |
| **B-11** | `_block_network_sockets` is **autouse** and patches `socket.socket.connect` / `connect_ex` for every test not marked `allow_socket` / `live` / `venue_live` / `real_money`; those four markers additionally **restore the real pyo3 clients** | `tests/conftest.py:383-407`, `:336-342`, `:394-402` |
| **B-12** | `pytest_configure` at `:227`, `pytest_sessionstart` at `:258` with an existing `pytest.exit(..., returncode=2)` at `:268` — both run before collection | `tests/conftest.py` |
| **B-13** | CI runs the whole suite under the OS egress block (`.github/workflows/tests.yml:27`), then ruff, mypy and `lint-imports` (`:30-37`). The launcher keeps loopback usable inside the namespace (`scripts/ci/run_tests_no_egress.sh:32-43`) | as cited |
| **B-14** | `http.PERMITTED_METHODS = frozenset({"GET"})` (`http.py:64`); `signing.PERMITTED_METHODS = frozenset({"GET"})` (`signing.py:84`); `get_authenticated(path, *, query, quota_key)` requires `quota_key` (`http.py:116-135`), refused unless in `PERMITTED_QUOTA_KEYS` (`transport.py:180`) | as cited |
| **B-15** | `QUOTA_KEY_PORTFOLIO` (`transport.py:93`) is in `PERMITTED_QUOTA_KEYS` (`:98-106`), budgeted at 12/min, and has **no caller in `src/`** today — it does have **three live callers in `scripts/venue/polymarket_us_auth_smoke.py` (`:1018`, `:1062`, `:1122`)**, which is the file NS-1 extends. **Probe:** grep of `QUOTA_KEY_PORTFOLIO` across `src/` and `scripts/`; it sees literal references, not one built by string concatenation | `transport.py:93`, `:98-106`; grep across `src/` and `scripts/` |
| **B-16** | `PolymarketUSLiveDataClientFactory` (`factories.py:320`) with `create` at `:334`; `config_from_env` at `:197`; credentials loaded at `:364`. `test_module_defines_no_execution_client_factory` (`tests/unit/test_polymarket_us_factories.py:461`) is scoped to that module only, and `create` is already tested socket-free by monkeypatching `NautilusHttpTransport` and the credential loader (`:181-182`) | as cited |
| **B-17** | `resolve_alert_sink` (`health.py:495`), `emit_alert` catching `BaseException` (`:514-535`), `WebhookAlertSink.close` (`:479-492`). The sink is constructed at **four** sites, not one: `ingest_runtime` (`composition.py:352`, torn down by `_close_alert_sink` `:255-268`), `ingest/nws_actor.py:2070` (lazy), `strategy/weather_common/refusals.py:123`, and as a default argument at `composition.py:279`. The load-bearing half stands — **no alert sink exists in any venue-facing process** — and `refusals.py:113-124` is the established `sink=None -> resolve_alert_sink()` injection pattern NS-5 adopts | as cited |
| **B-18** | `BinaryOption.currency = USD` for every Breezy instrument | `src/breezy/adapters/polymarket_us/parsing.py:1204` |
| **B-19** | `safety.py`: `PERMIT_TTL_NS` = 15 min (`:157`), `_PERMIT_BUDGETS` keyed per permit (`:332`), `consume` compares notionals with a bare `!=` (`:463`), `issue_live_trading_permit` (`:527`) re-reads ceilings (`:548`) and installs a fresh `_Budget` (`:575`), `assert_live_order_submission_permitted` (`:626`) takes no method and no path, and there is already a `type(x) is not Decimal` guard at `:676` to mirror. `issue_live_trading_permit` is in the package `__all__` (`adapters/polymarket_us/__init__.py:107,191`) | as cited |
| **B-20** | Every read surface is GET and every write surface is POST in the SDK snapshot: `account.py:16`, `portfolio.py:18,26`, `orders.py:35,42` versus `orders.py:27,47,55,63,71,79` | `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/resources/` |
| **B-21** | The SDK's response types are `total=False` throughout; `GetUserPositionsResponse.positions` is a `dict[str, UserPosition]`; `UserPosition` carries `netPosition`, `cost`, `qtyBought`, `qtySold`, `cashValue`, `marketMetadata` — and **no explicit average-entry-price field**. `ActivityType` has seven members, of which only `ACTIVITY_TYPE_TRADE` and `ACTIVITY_TYPE_POSITION_RESOLUTION` are trade-like | `sdk_snapshot/polymarket_us_0.1.2/types/portfolio.py` |
| **B-22** | `docs/evidence/venue/polymarket_us/raw/` contains 27 captures, **none** of them an authenticated account, position, order or activity payload | listing of that directory |
| **B-23** | The operator smoke already issues `GET /v1/portfolio/positions` (`:163`) and recorded 200 responses on 2026-08-30; it records **no body**; it has a frame-shape-without-values recorder at `:955` and a post-redaction verification at `:710-720`; the artifact reports "HTTP methods issued: GET" and "write requests issued: 0" | `scripts/venue/polymarket_us_auth_smoke.py`; `docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_2026-08-30T155317+0000.md` |
| **B-24** | `tests/contract/test_node_composition_contract.py` constructs a genuine `TradingNode` and never builds or runs it (`:135-143`), and asserts the construction opens no socket (`:432`) | as cited |
| **B-25** | The import-linter layer order puts `runtime` **above** `adapters`, so `adapters -> runtime` is upward; `breezy.ingest.nws_actor -> breezy.runtime.health` is already recorded as inspected debt of that class (`:78`); the forbidden-`nautilus_trader` contract needs one `ignore_imports` entry per importing module | `pyproject.toml:55-142` |
| **B-26** | 13 test modules already build Nautilus components from `nautilus_trader.test_kit.stubs`, so the engine-level RED technique is established rather than new | grep of `test_kit` under `tests/` |


### 9.4 Withdrawn — claims revision 1 of THIS document made and cannot defend

Recorded rather than deleted, because a withdrawn claim that vanishes is
indistinguishable from one that was never made.

| # | Revision 1 claimed | Actually | Where it was swept |
|---|---|---|---|
| **W-1** | F-17: `TradingNode` exposes no kernel or engine accessor (probe: class-level `dir()`) | **False** — `self.kernel` is an instance attribute (`live/node.py:71` `[V]`). The probe could not see it | §5.1 rewritten to direct observation; NS-3 REDs 3-4 and NS-5 REDs 1-2; §9.2 F-17 marked withdrawn; §4's NS-5 bullet; container-check rows 8b and 17; §6.1's process-container row |
| **W-2** | `_assert_reconciled` compares reports against the cache inside `generate_mass_status` | **Mistimed.** The engine applies reports only *after* that call (`live/execution_engine.py:1710-1712`, `:1732` `[V]`), and with `database=None` the cache is empty at that moment, always | NS-5 rule 2 replaced by an input precondition; RED 11 rewritten; OQ-2's wording; OQ-9 added |
| **W-3** | `generate_missing_orders=False` | **Inverted the mechanism.** With `False` every venue position is a discrepancy that warns and `return True` (`:2501-2509` `[V]`), making goal clause (c) unachievable | NS-5 rule 2(a) and the config pin list; §6.1 gained the `generate_missing_orders=True` row |
| **W-4** | "All eight lifecycle coroutines refuse" with `generate_order_denied` | **Two are not order-bearing, and `OrderDenied` is invalid on four of the six** (F-23) | Goal clause (d) and its falsifier; §4 walk; NS-5 rule 5 table; RED 9 |
| **W-5** | NS-1 reuses `diagnose_frame_payload` to record "shape without values" | **Inverted.** `_walk_structure` publishes every scalar verbatim (`data.py:428-429` `[V]`); the docstring suppresses *non*scalars | NS-1 rewritten around a new value-free recorder; container-check row 4; §6.3 item 8; §2's summary of added rows |
| **W-6** | "If Redis is unreachable the process refuses to start" | Uncited and false (C-3) | Withdrawn in revision 1 already; Redis is out of scope entirely |
| **W-7** | "There is no post-reconciliation seam" (revision 2, OQ-9 and NS-5 rule 2) | **False.** The engine publishes on `reports.execution.{venue}` after applying every report and before deciding (F-28). The probe grepped two files; the seam is in a third. **The fifth absence-claim failure in this workstream** | NS-5 rule 2 (both halves); OQ-9 rewritten; §2 row 18; §6.1 gained two rows; §4's NS-5 bullet; new RED 11c |
| **W-8** | "There is no public `get_client`" (revision 2, NS-5 rule 7 and §6.3 item 9) | **False.** `get_clients_for_orders` is public (F-33). The conclusion survives, the reason does not: it needs an `Order` and this process has none | NS-5 rule 7; §6.3 item 9; §2 row 17 |
| **W-9** | F-22: "kernel ordering means instruments are in the cache before reconciliation" | **Over-reached.** The ordering proves `_connect` returned; delivery is asynchronous (F-22 as corrected, F-25) | F-22 rewritten; NS-5 rule 2e; §2 row 20; §6.3 item 10 |
| **W-10** | `generate_missing_orders=True` adopted as "the native default, therefore right" | **Right about the default, silent about the behaviour** — it enters a position at cost zero when `avg_px_open` is `None` (F-26). A null-hypothesis argument for native is not an argument that native is safe | NS-5 rule 2b; NS-4's position mapper; goal clause (c) and falsifier; §2 row 19; OQ-2 promoted to a blocker; new RED 11b |
| **W-11** | "All six order-bearing coroutines refuse" stated as a property of a `breezy-trade` run | **A property of the class.** With `strategies=[]` five of six have no live caller | Goal clause (d); §4's NS-5 bullet |
| **W-12** | NS-1's V2 resolution "keeps an order path out of the file that handles live credentials" | **False.** Moving the import moves the literal, not the request; NS-4's operator step still issues the GET from the same credentialed script. The V2 argument survives alone | NS-1 Barriers |

---

## 10. Open questions

| ID | Question | What would close it | If it does not close |
|---|---|---|---|
| **OQ-1** | The exact field names, nesting and fixed-point scale of `GetAccountBalancesResponse`, `GetUserPositionsResponse`, `GetOpenOrdersResponse` and `GetActivitiesResponse` | **NS-1**, from a live authenticated read | NS-4's mappers refuse by record and clause (c) of the goal state is not claimed (see NS-1, "if the operator run cannot happen") |
| **OQ-2 — PROMOTED to a hard prerequisite of clause (c)** | Which venue field carries a position's **average entry price**. `UserPosition` has `cost` and `netPosition` but no explicit avg-px field (B-21) | NS-1's shape artifact — **field names and types only; NS-1 records no values, so no arithmetic can be checked against it.** Confirming that `cost` and `netPosition` mean what their names suggest, at a known scale, is the whole of what is needed | **Revision 2 answered "leave `avg_px_open` as `None`, nothing consumes it". That was wrong: the engine consumes it, and `None` enters the position at price ZERO (F-26).** So: no answer means the position mapper refuses every record and the process does not trade — loudly, and correctly. `cost / netPosition` is **not** to be used until the artifact confirms both fields |
| **OQ-3** | Should the alert primitives move below `adapters` instead of `exec/client.py` importing `breezy.runtime.health` upward? | A survey of `health.py`'s own dependencies; it is a `runtime` module with no obvious downward blocker | NS-5 adds one `ignore_imports` entry of the same class as the recorded `nws_actor` debt, and this stays open |
| **OQ-4** | Is `/v1/portfolio/activities` actually the fill source, and does it distinguish a fill from a deposit or transfer? | NS-1's shape artifact plus `ActivityType` (B-21) | The fill mapper maps `ACTIVITY_TYPE_TRADE` only and refuses every other type by name — a refusal, never a guess. **Note that mapped is not applied:** with `/v1/orders/open` as the only order source, the engine drops any fill without a matching order report (F-19), so no goal clause depends on this answer |
| **OQ-5** | Does the venue's 30-second signing window hold for these four endpoints? The 2026-08-30 smoke observed a **deliberately stale (-120 s) timestamp ACCEPTED** on `/v1/portfolio/positions` `[V]` | A repeat observation in NS-1 | Nothing in this plan depends on it; recorded so a future tightening is noticed rather than assumed |
| **OQ-6** | Is `base_currency=USD` strictly safer than `None`, given the currency-identity check? | A local test once a balances shape is known | `None` plus the identity check ships |
| **OQ-7** | Do the deferred permit defects (endpoint scope, fingerprint contract, authority types) need to land before *any* capability is minted, or only before the first exposure-opening one? | A review of the first SEND increment's plan | Treated as **hard prerequisites of the first increment that mints a capability**, which is the conservative reading |
| **OQ-8** | Does `GET /v1/orders/open` ever return an order Breezy did not place — for example one the operator placed manually on the same API key? | Observation in NS-1 | NS-4's order-status mapper maps them, NS-5 reports them, and reconciliation attributes them natively; nothing in this plan claims Breezy is the only actor on the key |
| **OQ-9 — CLOSED by experiment 2026-08-31** | Is there any seam at which Breezy can observe the **outcome** of reconciliation, rather than only its input? | **Closed:** `reports.execution.{venue}`, published after application and before the kernel decides, dispatched synchronously (F-28). Revision 2 answered "no" from a two-file grep and was wrong | **The residual is now narrow and stated exactly:** the subscriber observes the **cache**, not the engine's reasoning, and it **cannot fail the reconciliation** — `all(results)` is already assembled when the publish happens. So a divergence is detected, alerted and latched, but the trader still starts. Prevention remains the input precondition; detection is the subscriber; and there is no third thing available |
| **OQ-10** | Does the process need an order source covering **closed** orders, so that fills apply (F-19) and inferred fills stop being silently dropped? | The venue exposing a closed-order or order-history listing; `/v1/order/{order_id}` needs an id we never hold | Fills are mapped and not applied. No goal clause depends on a fill reaching the cache; positions come from the position reports. Carried to the SEND half, where a fill that does not apply is a real exposure error |
| **OQ-14 (NEW, found during NS-2 implementation, blocks NS-4)** | X3's `_SHORT` ban is a raw-text prohibition under `exec/`, as specified — but the venue SDK's `OrderIntent` literals include `ORDER_INTENT_BUY_SHORT` and `ORDER_INTENT_SELL_SHORT`. If NS-4's `exec/reports.py` must read an open order's `intent`, it collides with the ban | Inspect the `/v1/orders/open` payload captured by NS-1: does an open weather order carry an `intent` field, and does its value contain `_SHORT`? | **The ban is not to be loosened by NS-4 on its own authority.** Either the mapper never reads `intent` (state that, and pin it), or the ban gains a narrowly-scoped, separately-argued exemption for reading a venue enum it does not act on. A ban that is relaxed the first time it fires was never a barrier |

| **OQ-11 — CLOSED 2026-08-31, decided, not escalated** | May the operator's account hold a position in a market **outside** the instrument provider's weather universe? | **Not an operator question.** The operator's reserved controls are maximum daily budget and maximum per position; this is a correctness decision and therefore ours. It also cannot be closed by an NS-1 capture: a position count is value-derived and the recorder rule forbids cardinality | **DECIDED: refuse, loudly** — NS-5 rule 2(b) refuses reconciliation, the process does not trade, and the `instrument_id` is named in a `CRITICAL` alert. Rationale: in NO-SEND, refusing costs *nothing* — the process cannot trade anyway, so "refuses to start trading" forfeits no capability, while proceeding would tolerate exposure we cannot see and would set clause (c) aside on its first real test. **The trade-off inverts for the SEND half**, where refusing has a real cost (an unrelated position halts live trading), so that half must re-decide rather than inherit this. Recorded as carry-forward row A10 |

---

## 11. Non-goals

1. **A fourth process, or a shared "process framework".** NS-3 is the third
   instance of an existing shape (settings loader, config builder, CLI, entry
   point), not a generalisation over three cases. Three concrete builders that
   read clearly beat one parameterised builder whose read-only guarantees depend
   on its arguments — and the cage is asserted per site.
2. **Trading inside the ingest or quote-tape process.** Both keep their current
   literals forever, pinned per site. The tape's value is that it keeps
   recording when trading halts.
3. **Any Breezy-authored retry loop, state machine, position ledger or halt
   framework.** The native reconciliation gate is the fail-closed mechanism.
4. **Kalshi portability.** Venue-specific by construction; the seams (report
   mappers, endpoint table) are portable. Nothing is generalised speculatively.
5. **Re-planning `DATA_CAPTURE_AND_RISK_PLAN.md`.** Its P0-P7 sequence is
   unchanged, and NS-0..NS-5 are independent of it.

---

## 12. How to review this document

Attack in this order.

1. **Sections 9.1 and 9.4 first.** Five of the predecessor's `[V]` claims were
   wrong, and **twelve** of this document's own across two revisions. If any
   claim in 9.2 or 9.3 is wrong, the increment resting on it is wrong.
   **Attack the absence claims hardest, and hold them to this rule:** an absence
   claim about the framework is established by **trying to do the thing** —
   subscribe and see whether a message arrives, call the accessor and see whether
   it resolves, construct the identifier and see whether it raises — never by
   searching for it. A positive experiment has no blind spot to inherit; a grep
   over the wrong file always returns nothing. Five absence claims in this
   workstream failed, every one of them a search. Where this document now makes
   an absence or behaviour claim about Nautilus, it names the experiment (F-28,
   F-31, F-32, F-35, and the two in NS-5 rule 2); where it still rests on a
   search, say so and demand an experiment.
1b. **Then hold the claims ABOUT THIS DOCUMENT to the same standard.** "The
   dependency check was run on every increment" requires every increment to have
   the paragraphs it runs on — revision 2's did not, at NS-3. "RED 11 verifies
   clause (c)" requires RED 11 to contain that assertion — revision 2's did not.
   For every process claim, find the artifact it names and check that it exists
   and says what the claim says.
2. **Section 2 against section 3.** Does every artifact have a container, and is
   that container earlier?
3. **Section 1's predicate against section 4's walk.** Does the walk actually
   arrive, and does each increment add what it claims?
4. **The REDs.** For each, ask: *what makes this go red, and could a wrong
   implementation make it go green?* Five are flagged as weak or non-discovering
   in place: NS-3 RED 6 (vacuous until the builder lands); NS-4 RED 8 (passes by
   rule C1 the moment the path string exists — labelled *not a RED*); NS-4 RED 6
   (an AST assertion that a file imports nothing, which is a pin rather than a
   discovery); NS-5 RED 2 (trivially red, but it is what makes RED 1
   non-vacuous); NS-2's AST bans (vacuous on the day they land — they carry
   planted-source non-vacuity proofs and are re-asserted at NS-4 and NS-5
   instead). Find the others. **Then check the converse**, which is how revision
   2 failed here: for each clause of the predicate, name the RED that asserts it
   and read that RED's assertion. Clause (c)'s "the position actually enters the
   cache" had no RED at all in revision 2 while OQ-9 claimed one covered it.
5. **Section 8, and 8.1 hardest.** Is anything deferred that the goal state
   secretly needs? Is any hook left for something deferred? **Rows 1 and 3-6 of
   8.1 are inherited and unverified** — if one is wrong, say so here rather than
   letting the SEND half inherit it a second time.
6. **The scan.** After every increment: `scan_write_egress(("src","scripts"))`
   returns zero violations outside `exec/endpoints.py`, and both
   `PERMITTED_METHODS` frozensets are still `frozenset({"GET"})`.
