# The NO-SEND execution client — implementation plan

**Status:** Revision 1, not executed. **Created:** 2026-08-31.

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
> **(a)** registers exactly one Polymarket.us **data** client and exactly one
> Polymarket.us **execution** client;
> **(b)** puts a non-`None`, `AccountType.CASH`, `USD`-denominated `Account`
> for venue `POLYMARKET_US` into the Nautilus `Cache`, built from a live
> `GET /v1/account/balances`, **before the trader starts**;
> **(c)** completes native startup reconciliation from
> `GET /v1/portfolio/positions`, `GET /v1/orders/open` and
> `GET /v1/portfolio/activities` **or refuses to start the trader**, with no
> path on which a venue position is absent from the cache and reconciliation
> still reports success;
> **(d)** answers **every one** of the eight order-lifecycle coroutines with a
> named, counted, alerted `OrderDenied` and never an `OrderSubmitted`;
> **(e)** while `scan_write_egress(("src", "scripts"))` reports zero violations
> outside the single V2-allowlisted path `exec/endpoints.py`, and zero V1 / V3 /
> V4 violations anywhere, and `http.PERMITTED_METHODS` and
> `signing.PERMITTED_METHODS` are still exactly `frozenset({"GET"})` and are
> never rebound.

**Falsifiers.** (a) `breezy-trade` is not an entry point, or the node it builds
carries an empty `data_clients` or `exec_clients`. (b) `cache.account_for_venue`
returns `None`, or an account in a currency other than `USD`, or the trader
starts before either is true. (c) A venue position exists that is absent from
the cache while reconciliation reports success. (d) Any lifecycle coroutine
produces anything other than `OrderDenied`, or a denial that is not named,
counted and alerted. (e) Any write-capable construct anywhere outside the one
allowlisted file. **And, for all five: the suite passing green while the clause
is unimplemented.**

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
| 4 | Observed response shapes for balances / positions / open orders / activities | an authenticated read against the live venue, and a redaction-safe shape recorder | **NS-1** — extends `scripts/venue/polymarket_us_auth_smoke.py`, which already performs `GET /v1/portfolio/positions` (`:163`) and already has a shape-without-values recorder (`:955`) |
| 5 | The cage-constant equality pins | the nine rule constants, which all exist today | **NS-2** |
| 6 | `build_trading_node_config` | native `TradingNodeConfig`; a `PolymarketUSDataClientConfig`, produced by the shipped `config_from_env` (`factories.py:197`); a settings loader for the trading role | **NS-3** (settings loader in the same increment) |
| 7 | `breezy-trade` | a `[project.scripts]` table (`pyproject.toml:255`) and a `main()` | **NS-3** |
| 8 | The node that actually runs | native `TradingNode`; `PolymarketUSLiveDataClientFactory` (`factories.py:320`); an exec factory | **NS-3** (data half), **NS-5** (exec half) |
| 9 | `exec/endpoints.py` | the B4/V2 narrowing, without which the file cannot land at all (`_ORDER_PATH_RE` matches `/v1/orders`, `/v1/orders/open`, `/v1/order/{id}`) | **NS-4, same commit** |
| 10 | `exec/reports.py` fixtures | observed payload shapes — the SDK snapshot types are all `total=False`, so every field is optional and nothing can be assumed present | **NS-1** |
| 11 | A CALLER for the report mappers | a `LiveExecutionClient` whose report coroutines `LiveExecutionEngine` invokes | **NS-5** |
| 12 | `exec/client.py` | the node config carrying its client config; the B6b narrowing; one new `ignore_imports` entry per new nautilus-importing module | **NS-3** (node) + **NS-5** (same commit) |
| 13 | An alert sink **in the trading process** | `resolve_alert_sink` (`health.py:495`) plus a construction site inside this process — today it is constructed only in `ingest_runtime` (`composition.py:352`), so every "loud" failure this plan specifies would be log-only | **NS-5**, in `exec/factories.py` |
| 14 | A true account in the cache | `_set_account_id` (`execution/client.pyx:148`) and `generate_account_state` (`:329`), both native; plus an observed balances shape | **NS-1** + **NS-5** |
| 15 | A started trader | reconciliation returning `True` — the kernel returns without starting the trader otherwise (`system/kernel.py:1027-1029`, `:1040`) | **NS-5** |

**Rows that read "nothing" before this plan: two.** Row 4 (the mappers had no
observed payload to map from — the predecessor deferred this to two open
questions and then specified mappers anyway) and row 13 (alerting had no
container in the trading process at all). Both are closed by placing an
increment **before** the artifact that needs it: NS-1 before NS-4, and the sink's
construction site inside the same increment as its only consumer.

---

## 3. Dependency check — performed after ordering

| Increment | Depends on | All earlier? |
|---|---|---|
| **NS-0** arm the firewall | nothing in this plan | — |
| **NS-1** read-only shape capture | nothing in this plan (script + operator credentials already exist) | — |
| **NS-2** cage + permit strengthening | nothing in this plan | — |
| **NS-3** the trading process | nothing in this plan | — |
| **NS-4** `exec/endpoints.py` + `exec/reports.py` | NS-0 (E0 rule armed before the second and third `exec/` files land), NS-1 (shapes) | **yes** |
| **NS-5** `exec/client.py` + config + factory | NS-0, NS-2 (pins are the baseline the B6b narrowing is measured against), NS-3 (the node), NS-4 (the mappers and the endpoint table) | **yes** |

**Result: no increment depends on a later one.** NS-1 and NS-2 are independent of
everything and of each other; NS-1 is placed second only because it is
operator-run and its latency should overlap the code work. The chain that
carries the goal state is NS-0 → NS-3 → NS-4 → NS-5, with NS-1 feeding NS-4 and
NS-2 feeding NS-5.

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
  without: the observed field names and types of the four authenticated
  responses. Without it, NS-4's mappers would be written against `total=False`
  TypedDicts in which every field is optional, so every real record would refuse
  and the process would reconcile nothing. Missing: everything else.
- **After NS-2**: still nothing of the predicate holds. What is added is that the
  cage cannot be *loosened* by a one-token diff, that `consume()` cannot be
  satisfied by a lying `Decimal` subclass, that a permit cannot be minted from
  any module in the tree, and that renewing a permit no longer resets the
  operator's session budget. Everything NS-3..NS-5 does is measured against these
  pins. Missing: the process, the reports, the client.
- **After NS-3**: clause **(a) half** holds — a `TradingNode` for the trading
  role exists, starts from `breezy-trade`, and carries exactly one Polymarket.us
  data client. `exec_clients` is still an explicit `{}`. Missing: (a) exec half,
  (b), (c), (d). This is the first increment whose output is a thing that *runs*.
- **After NS-4**: no clause completes, and no capability was added. What is added
  is the data every later clause consumes: the frozen `(method, path-template)`
  table for the read surface, and pure venue-JSON to Nautilus-report mappers
  with no caller yet. Clause **(e)** is now non-trivially true for the first
  time: the V2 allowlist exists and contains exactly one file. Missing: (a) exec
  half, (b), (c), (d).
- **After NS-5**: the whole predicate holds. Clause (a) completes (the exec
  client is registered and constructed), (b) holds (`_set_account_id` then
  balances then `generate_account_state` then a cache assertion Breezy owns),
  (c) holds (reconciliation is driven from real GETs and a discrepancy fails
  reconciliation rather than warning), (d) holds (all eight coroutines deny),
  (e) still holds (nothing NS-5 adds is write-capable). **Nothing is missing from
  the predicate.**

**Coverage.** (a) from NS-3 + NS-5. (b) from NS-1 + NS-4 + NS-5. (c) from NS-1 +
NS-4 + NS-5. (d) from NS-5. (e) from NS-0 + NS-2 + NS-4 + NS-5.

**Send column.** NS-0 none; NS-1 GET (operator-run script, already permitted);
NS-2 none; NS-3 GET + WS (the same surface the recorder already uses); NS-4 GET;
NS-5 GET. **No increment adds a write endpoint, a write verb, or a write
attribute.**

---

## 5. Module layout

```
src/breezy/adapters/polymarket_us/
    http.py  transport.py  signing.py     <- UNCHANGED, BYTE-FOR-BYTE. GET-only.
    safety.py                             <- NS-2: type-exactness, session-budget carry-forward
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
contextmanager. The trading process owns none of those either: its only such
resource is the alert sink, and the sink is constructed by, and torn down by,
the execution client (NS-5), because Nautilus gives an exec client exactly one
composition seam — the factory — and no accessor by which a caller could reach
the constructed client to inject one afterwards (`LiveExecutionEngine` exposes
`registered_clients` and `_clients` only; `TradingNode` exposes `cache`,
`portfolio`, `trader` and no kernel/engine accessor `[V]`).

**Consequence for every RED in this plan, stated once here so no increment has
to restate it:** the composed-node evidence is *structural* and is taken from a
node that is **constructed and never built or run** — exactly the technique
`tests/contract/test_node_composition_contract.py` already uses and asserts
(`:135-143`, and `test_building_the_runtime_and_node_opens_no_socket` at `:432`
`[V]`). `node.build()` constructs the venue clients, which construct a
`nautilus_pyo3.HttpClient` — blocked in tests by barrier N1 — so **no test in
this plan calls `node.build()` or `node.run()`.** Behavioural evidence is taken
one level down, against the real `LiveExecutionEngine` and `Cache` from
`nautilus_trader.test_kit.stubs`, which is already the established pattern in
this repo (13 test modules use `TestComponentStubs` `[V]`). NS-5's RED list
states the chain that joins the two levels without a gap.

---

## 6. Reuse ledger

### 6.1 Native — do NOT rebuild (null hypothesis CONFIRMED)

| Capability | Native anchor `[V]` | Breezy's job |
|---|---|---|
| The process container | `TradingNode` (`live/node.py`), kernel lifecycle (`system/kernel.py`), `add_data_client_factory` (`live/node.py:230`), `add_exec_client_factory` (`:251`) | **configure and instantiate one** — a config builder, a CLI, an entry point. No runtime. |
| Execution-client machinery | `LiveExecutionClient`: 8 coroutines to implement (`live/execution_client.py:598-636`), `generate_mass_status` (`:440-514`), `_await_account_registered` (`:534-567`) | subclass; implement the seams |
| Lifecycle event construction and msgbus routing | `execution/client.pyx`: `generate_account_state` (`:329`), `generate_order_denied` (`:370`) | call them |
| Startup reconciliation and its fail-closed gate | `live/execution_engine.py:1680-1730`; `system/kernel.py:1027-1029` — reconciliation false means the kernel returns and **`self._trader.start()` (`:1040`) is never reached** | supply reports; assert the match ourselves |
| Account registration in the cache | `_set_account_id` (`execution/client.pyx:148-152`), `_await_account_registered` | set the id FIRST, then assert the cache |
| Order cache, position tracking, the order state machine | `execution/client.pyx`, `model/orders/base.pyx` | obey |
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
| `QUOTA_KEY_PORTFOLIO` | `transport.py:93`, in `PERMITTED_QUOTA_KEYS` (`:98`), budgeted at 12/min | every exec-side read | **already exists, already permitted, currently unused in `src/`** — no new quota key, no widening |
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
5. **A Breezy-owned reconciliation match assertion.** See fact F-2.
6. **An alert sink construction site in this process.**
7. **Observed response shapes.** The venue SDK's TypedDicts are `total=False`
   throughout, so the schema constrains nothing.

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
4. `find_execution_egress_modules()` on the shipped tree returns **exactly**
   `[exec/__init__.py under E0]` — the "currently empty" pin (`:592-594` `[V]`)
   inverts to an exact-set pin. *Red today:* the set is empty and the rule that
   would populate it does not exist.

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

**Null hypothesis: the mechanism already exists.** The smoke script already
performs `GET /v1/portfolio/positions` (`:163` `[V]`, and the 2026-08-30 runs
record it returning 200 `[V]`), already redacts on two independent layers and
refuses to emit a file if secret-derived material survives (`:497-720` `[V]`),
and already contains a "describe one frame's shape without publishing nonscalar
payloads" facility for WebSocket frames (`:955` `[V]`). **Absent: applying that
facility to HTTP response bodies, and reading the other three endpoints.**

**Goal.** Extend the operator-run smoke to record, for
`GET /v1/account/balances`, `GET /v1/portfolio/positions`,
`GET /v1/orders/open` and `GET /v1/portfolio/activities`: the **field names,
their JSON types, their nesting, and their cardinality — never their values.**
Numeric fields are recorded as type plus **digit count and decimal-place
count**, never magnitude, because the fixed-point scale question (does the venue
send `0.53`, `53`, or `530000`?) is exactly what the mappers must not guess and
is not answerable from a type alone. One new evidence artifact under
`docs/evidence/venue/polymarket_us/`, with its `.sha256`, in the existing dated
format.

**REDs — and what makes each go red.**
1. The shape recorder applied to a dict containing a value that matches a
   secret's redaction pattern emits **no value**, and the existing
   post-redaction verification (`:710-720` `[V]`) passes. *Red today:* the
   recorder is frame-shaped and does not accept a JSON body.
2. A synthetic `GetAccountBalancesResponse`-shaped dict round-trips to a shape
   record naming every key and no value. *Red today:* no such function.
3. The four endpoint paths appear in the smoke's read plan with method `GET`,
   and the script's own write-request counter stays `0`. *Red today:* three of
   the four are not read.

**Files.** `scripts/venue/polymarket_us_auth_smoke.py`; its test module; the
emitted evidence artifact plus `.sha256`.

**Barriers.** `scripts/venue/` is venue-touching by path (rule C2,
`readonly_guard.py:128-131` `[V]`), so V1-V4 apply in full and **no
write-method literal and no `.post` may appear**. `/v1/orders/open` is an
order-path literal and therefore trips **V2** — this increment takes the **same
exact-path V2 allowance NS-4 takes**, or, preferably, imports the constant from
`exec/endpoints.py` once NS-4 exists. *Ordering note:* if the operator run
happens before NS-4, the allowance is granted here for this one file and removed
when NS-4 centralises the constant. State which happened in the commit message;
do not leave two allowlisted files standing.

**Completion.** A committed, hashed evidence artifact naming every field of the
four authenticated responses, with no value of any kind. **Everything NS-4 maps,
it maps from this artifact.**

**If the operator run cannot happen.** NS-4's mappers are written to refuse per
record by name, NS-5 ships, and clause (c) of the goal state is **not claimed**:
the process would start, emit an account only if the balances shape is among the
observed ones, and otherwise fail reconciliation and refuse to start the trader.
That is a correct fail-closed state and an incomplete goal state. Say so; do not
claim the predicate.

---

### NS-2 — Cage strengthening and the permit defects that stand alone

**Goal.** Make every rule constant unloosenable, and fix the three shipped
`safety.py` defects that need no new vocabulary. Strengthening *before*
narrowing means NS-4's and NS-5's narrowings are measured against a pinned
baseline.

**What is here, and why each qualifies.** A defect qualifies for this increment
if it is (i) a correction to already-shipped code, (ii) testable with a RED
today, and (iii) does not require inventing the authority vocabulary the SEND
half is built on. The three permit defects that fail (iii) — endpoint scope, the
fingerprint contract, the four authority types — are in section 8.

| # | Defect | Cite `[V]` | Fix |
|---|---|---|---|
| **D-1** | `consume()` compares notionals with `!=` and does not type-check, so a `Decimal` subclass overriding `__ne__` satisfies the re-check at any magnitude | `safety.py:463` | mirror `:676`'s existing `type(x) is not Decimal` guard |
| **D-2** | `issue_live_trading_permit` has **no caller barrier at all** and is re-exported in the package `__all__` | `safety.py:527`; `adapters/polymarket_us/__init__.py:107,191` | caller count pinned `== 0` with a one-entry path allowlist **declared and empty**, plus a proof that a planted caller fails; removed from `__all__` |
| **D-3** | Renewal resets the operator's budget: issuance re-reads the ceilings from the environment (`:548`) and installs a **fresh** `_Budget` under a fresh `permit_id` (`:575`); `_PERMIT_BUDGETS` (`:332`) is keyed per permit and aggregates nothing; `PERMIT_TTL_NS` is 15 minutes (`:157`), so renewal is forced — roughly 32 renewals on an 8-hour day | `safety.py` | a process-level session ledger keyed by `operator_id`, created on first issuance and **never reset**; renewal binds to the existing ledger and carries the REMAINING budget forward |

**Note on D-2's count.** It is `== 0` in this plan and stays `== 0` through NS-5:
nothing in the NO-SEND half mints a permit, because no GET requires one. The
predecessor had to flip `== 0` to `== 1`; here there is no flip, which is
strictly simpler and strictly stronger. Never `<= 1` — that is satisfied by zero
and passes while dead.

**The eight silent-failure counters, all landing here.**

| # | Failure mode | Counter |
|---|---|---|
| 1 | A directory-prefix *exemption* becomes a blanket allowance | every exemption is an exact path; each allowlist entry must resolve to an existing file; the frozenset is equality-pinned |
| 2 | Egress escapes the classifier — a module outside the package taking its base URL from the environment | `assert is_venue_touching(p) is True` for **every** path in section 5's layout, **including paths that do not yet exist** |
| 3 | The global rule is loosened instead of the file allowlisted | equality pins on all nine rule constants: `_WRITE_METHODS`, `_WRITE_ATTRS`, `_ORDER_PATH_RE`, `EGRESS_SCAN_ROOTS`, `SDK_IMPORT_ORACLE`, `_EGRESS_MODULE_BASENAMES`, `_EGRESS_CLASS_SUFFIXES`, `_EGRESS_CLASS_BASES`, `_EGRESS_FUNCTION_NAMES` |
| 4 | N2 blind to planned filenames | **NS-0** |
| 5 | A barrier written `<= 1` passes while dead | every count assertion is an equality, with a proof that both neighbours fail |
| 6 | An exec test marked `allow_socket` / `live` / `venue_live` / `real_money` restores the real pyo3 clients (`conftest.py:394-402` `[V]`) | static ban on those four markers in any test importing `...polymarket_us.exec` — **sound only because section 5.1's decision means no exec test ever needs a socket** |
| 7 | Data-path widening by rebinding `signing.PERMITTED_METHODS` on an imported module object | repo-wide AST ban on assignment to `PERMITTED_METHODS` / `PERMITTED_QUOTA_KEYS` / `_WRITE_*` |
| 8 | A rule constant is *narrowed* rather than widened, silently disarming a scan | the same equality pins as #3, which fail in both directions |

**REDs — one per defect, each failing on today's tree.**
1. A `Decimal` subclass whose `__ne__` returns `False` passes `consume(...)` at
   an arbitrary magnitude. *Red today:* `:463` is a bare `!=`.
2. Spending a permit's session budget and then issuing a second permit restores
   the full budget. *Red today:* `:575` installs a fresh `_Budget`.
3. A module outside the issuer mints a permit from the operator's environment.
   *Red today:* no caller barrier exists.
4. Widening `_WRITE_METHODS` by one token leaves the suite green. *Red today:*
   the constant is unpinned.
5. A planted `src/breezy/egress_outside_the_package.py` reading its base URL from
   `os.environ` is classified **not** venue-touching. *Red today:* C1-C4 do not
   cover it.
6. A test importing `...polymarket_us.exec` marked `@pytest.mark.allow_socket`
   is undetected. *Red today:* no such scan.
7. Rebinding `signing.PERMITTED_METHODS` from another module is unbanned.
   *Red today:* no such scan.

**Files.** `safety.py`; `adapters/polymarket_us/__init__.py`; the three guard
suites; new `tests/unit/test_cage_rule_constants_are_pinned.py`.

**Barriers.** Every change is strictly stronger. **No allowlist is created in
this increment.** `SandboxExecutionClient`, `AccountType.BETTING` and
`accounting/accounts/betting` are banned by name, each with a non-vacuity proof.
The AST bans on the tokens `_SHORT`, `OUTCOME_SIDE_NO` and any `1 - price` form
anywhere under `exec/` land here too: they cost nothing, they are prohibitions
rather than purity proofs (so indirection cannot defeat them), and the hazard
they name is the one a reviewer found in a comment that must NOT be "fixed"
(`risk.py:75-78`'s "short YES is spelled buy NO" is correct in context).

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
  calls `_run_node(config, node_factory, stderr)`, which constructs the node,
  registers the data client factory under the same name that keys
  `data_clients`, builds, runs, and **always** disposes. `KeyboardInterrupt` is
  exit 0, as the tape has it (`quote_tape_cli.py:158-168` `[V]`).
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
3. A real `TradingNode(build_trading_node_config(...), loop=loop)` is
   **constructed** with `node.trader` present and `node.is_built` false, and the
   construction opens **no socket** — the same assertion shape as
   `test_node_composition_contract.py:432` `[V]`. *Red today:* the builder does
   not exist.
4. `trade_cli._run_node` driven with a recording double registers
   `PolymarketUSLiveDataClientFactory` under **exactly** `POLYMARKET_US_CLIENT_NAME`
   — the same key that appears in `data_clients` — before `build()`. *Red today:*
   `trade_cli` does not exist. (This is the assertion whose absence makes a
   recorder silently record an empty tape; `quote_tape_cli.py:141-148` `[V]`
   documents the same hazard on the other process.)
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

**Completion.** A Breezy `TradingNode` for the trading role exists, starts from
its own entry point, and carries exactly one Polymarket.us data client and no
execution path. Clause (a) of the goal state holds at the data half. From here,
every increment names **this** node as the thing it changes.

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
and the kernel **does not start the trader** (`system/kernel.py:1027-1029`,
`:1040` `[V]`). Diagnostically nothing is lost — every refusal was already
logged and alerted — and the outcome is native fail-closed with no authored
machinery.
*(This rule is scope-dependent and is flagged as such: in the SEND half,
discarding a reconciliation while holding a live position abandons it, which is
exactly why the predecessor's per-record rule exists. It is stated here as a
consequence of "no position can exist", not inherited as universal.)*

**Every decode is refused unless it was observed.** The fixed-point question —
does the venue send a price as `0.53`, `53`, or `530000`? — is answered by NS-1's
artifact or not at all. A guessed decode reading a price 100x wrong is worse
than a refusal; the mapper refuses by name, per record.

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
5. `assert is_venue_touching("src/breezy/adapters/polymarket_us/exec/reports.py", tree) is True`.
   *Note:* this passes by rule C1 the moment the path string exists, so it is
   written **before** the file lands and its value is as a regression pin on C1,
   not as a discovery. Flagged rather than dressed up as a RED.

**Barriers.** **B4/V2 narrowed** — the first and only allowance this increment
creates. It is an **exact path** (`exec/endpoints.py`), never a prefix, paired in
the same commit with: the `(method, template)` frozenset equality pin, the
all-methods-are-GET assertion, `_ORDER_PATH_RE` pinned, and
`assert is_venue_touching(<that path>) is True`. **V1, V3 and V4 apply in full —
no write-method literal, no `.post`, no `.request`, no `getattr` bypass,
anywhere in this increment, including inside the allowlisted file.** The N2
exact-set pin grows by two.

**Completion.** `scan_write_egress()` reports zero violations outside the one
V2-allowlisted path. Clause (e) of the goal state is now non-trivially true.

---

### NS-5 — `exec/client.py`: the client that reconciles truthfully and refuses everything

**Null hypothesis: NATIVE — sufficient for the machinery, insufficient for five
seams.** `LiveExecutionClient` supplies everything but eight
`NotImplementedError` coroutines (`live/execution_client.py:598-636` `[V]`) and
the four report coroutines (`:343-438` `[V]`). **GENUINELY ABSENT:** the
`AccountState` emission, `_set_account_id`, `_query_account`, the reconciliation
match assertion, and an alert sink in this process.

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
`_connect` therefore, in this order: `_set_account_id(...)`, fetch balances,
assert currency identity, `generate_account_state(...)`,
`_await_account_registered()`, then **assert
`self._cache.account(self.account_id) is not None`** — never trusting the
await's return.

**2. Breezy owns the reconciliation match assertion.** With
`generate_missing_orders=False`, a position-quantity discrepancy logs a warning
and **`return True`** (`live/execution_engine.py:2501-2509` `[V]`). Native
"reconciled" therefore does not imply "matched", and a goal-state assertion
resting on the native result would pass **precisely in the state it was written
to detect**. Breezy compares its own `PositionStatusReport` set against the
cache and **fails reconciliation on any discrepancy**, in a named function
`exec/client.py::_assert_reconciled`. The failure route is NS-4's: return `None`
from `generate_mass_status`, so the kernel does not start the trader. No halt
machinery is authored.

**3. The currency identity, asserted at emission.** The emitted
`AccountBalance.currency` must be identically `USD`, which is the
`BinaryOption.currency` every Breezy instrument carries (`parsing.py:1204`
`[V]`). A balance emitted as `USDC` produces an account object that is present
and useless: `balance_free(USD)` returns `None` for a currency the account does
not hold. `_connect` fails closed on it. `AccountBalance.free` carries the
venue's **available/withdrawable** figure and never a total including
order-locked collateral; `locked` carries the difference. Both rules are pinned
by contract test against NS-1's observed shape.

**4. `_query_account` is defined explicitly.** It is called
(`live/execution_client.py:332` `[V]`) and **not defined anywhere in the class**
`[V]`; omitting it raises `AttributeError` inside a created task.

**5. All eight lifecycle coroutines refuse.** `_submit_order`,
`_submit_order_list`, `_modify_order`, `_cancel_order`, `_cancel_all_orders`,
`_batch_cancel_orders` each call `generate_order_denied`
(`execution/client.pyx:370` `[V]`) with a named reason, increment a named
counter, and emit an alert. `OrderDenied` is terminal and pre-venue: no
`OrderSubmitted` is ever generated. `_connect` and `_disconnect` are the only
two that do real work. Refusal reasons are module constants, one per coroutine,
so a denial is greppable and countable rather than a formatted string.

**Account shape, chosen once rather than defaulted.**
`account_type=AccountType.CASH`; `base_currency=None` (multi-currency, matching a
per-currency balance list) with rule 3's identity check as the control;
`oms_type=OmsType.NETTING`, pinned by test. Config pins, each stated rather than
defaulted because a defaulted value and a chosen one are indistinguishable in
review: `reconciliation=True` (`live/config.py:177` `[V]`),
`generate_missing_orders=False` (native default `True`, `:183` `[V]`),
`filter_unclaimed_external_orders=False` (native default already `False`, `:180`
`[V]`; set `True` it makes the engine silently discard an unclaimed external
report, `live/execution_engine.py:3575` `[V]`), `open_check_interval_secs=None`
and `position_check_interval_secs=None` (`:188` `[V]` — nothing this process
does benefits from a repeated check, and enabling one before a settlement exit
exists is how a wrong-price report would fire repeatedly).

**The alert sink gets its container here.** `resolve_alert_sink` (`health.py:495`
`[V]`) is called **exactly once**, in `PolymarketUSLiveExecClientFactory.create`
— the one composition seam Nautilus offers for an execution client
(`live/factories.py::LiveExecClientFactory.create` `[V]`) — and handed to the
client's constructor. The client closes it in `_disconnect`, duck-typing
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
carries `quota_key=QUOTA_KEY_PORTFOLIO`, which already exists, is already
permitted, and is currently unused in `src/` `[V]` — no quota key is added and
none is widened.

**REDs — and what makes each go red.**

*Composed-node level (a real `TradingNode`, constructed only, never built):*
1. `build_trading_node_config`'s `exec_clients` is **exactly**
   `{POLYMARKET_US_CLIENT_NAME: <the exec config parameter>}` under the per-site
   value table, and the other two sites are byte-unchanged. *Red today:* the
   site pins `{}`.
2. `trade_cli._run_node` driven with a recording double registers
   `PolymarketUSLiveExecClientFactory` under exactly `POLYMARKET_US_CLIENT_NAME`
   via `add_exec_client_factory` before `build()`. *Red today:* it registers
   only the data factory.

*Factory level (stub msgbus/cache/clock; transport and credential loader
monkeypatched at the module — the technique
`tests/unit/test_polymarket_us_factories.py:181-182` `[V]` already uses):*
3. `PolymarketUSLiveExecClientFactory.create(...)` returns a
   `PolymarketUSExecutionClient` whose `ClientId` derives from the registered
   name, whose venue is `POLYMARKET_US_VENUE`, whose `account_type` is `CASH`
   and whose `oms_type` is `NETTING`. *Red today:* no factory.
4. `create` resolves the alert sink **exactly once** and the client holds it.
   *Red today:* no sink is constructed anywhere in this process.
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
9. Each of the eight coroutines emits `OrderDenied` with its named reason,
   increments its counter, emits an alert, and **never** `OrderSubmitted`.
10. `_query_account` is awaited without `AttributeError`.
11. A venue position absent from the cache makes `generate_mass_status` return
    `None`. *Red today:* no client; and an implementation that trusts the native
    result fails this, because the native path returns `True`
    (`live/execution_engine.py:2503-2509`).
12. An unmappable record makes `generate_mass_status` return `None` **and** the
    per-record counter is non-zero **and** the other two report lists were
    non-empty when it happened — NS-4's two rules asserted together, so an
    implementation satisfying one by violating the other fails.

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
15. `uv run lint-imports` passes. *Red today:* four new modules import
    `nautilus_trader` and one imports `breezy.runtime.health`.

**A note on the gap between the two evidence levels.** No test builds or runs
the node (section 5.1), so nothing directly observes the real node handing our
config to our factory. That link is closed by a chain of three assertions rather
than by one integration test: RED 1 pins that `exec_clients` carries exactly our
config type under exactly the registered name; RED 2 pins that the same name is
handed to `add_exec_client_factory` with exactly our factory class; RED 3 pins
that our factory, given a config of that type, returns our client. Nautilus
resolves `data_clients` / `exec_clients` keys against registered factory names
(`live/node.py:230`, `:251` `[V]`, and the hazard is documented at
`quote_tape_cli.py:141-148` `[V]`), so the three together determine the
composition. **State this limitation in the test module; do not let a reader
believe a composed node was exercised.**

**Barriers.**
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
  nautilus-importing module (`exec.client`, `exec.config`, `exec.factories`, and
  `exec.reports` if it imports the report types), each of the same shape as the
  existing per-module entries, **plus** one entry
  `breezy.adapters.polymarket_us.exec.client -> breezy.runtime.health` — an
  upward `adapters -> runtime` import of exactly the same class as the recorded
  debt `breezy.ingest.nws_actor -> breezy.runtime.health` (`pyproject.toml:79`
  `[V]`). Recorded as inspected debt, with the alternative in OQ-3.
- **No write verb, no write attribute, no endpoint literal outside
  `exec/endpoints.py`, no signing change.**

**Completion.** The full goal-state predicate holds. `breezy-trade` starts,
connects, emits a true `USD` `CASH` account, reconciles the venue's positions and
open orders or refuses to start the trader, and denies every order — with
`scan_write_egress()` clean outside one file and both `PERMITTED_METHODS`
frozensets still `{"GET"}`.

---

## 8. Deferred — out of scope, with the reason

Not designed here, and **no hook is left for any of them** beyond what the
NO-SEND work independently requires.

| Deferred | Was | Why it is not here |
|---|---|---|
| The denial layer over the risk engine's fail-opens | E-5 | It denies orders *before Nautilus is consulted* on a path to a venue. There is no such path: all eight lifecycle coroutines already refuse unconditionally at NS-5, which is strictly stronger than a conditional pre-check. The fail-opens matter the moment one coroutine stops refusing — which is the first SEND increment. |
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
| **F-1** | `LiveExecutionClient` declares exactly **eight** coroutines to implement: `_connect`, `_disconnect`, `_submit_order`, `_submit_order_list`, `_modify_order`, `_cancel_order`, `_cancel_all_orders`, `_batch_cancel_orders` | `live/execution_client.py:598-636` |
| **F-2** | With `generate_missing_orders=False`, a position-quantity discrepancy logs a warning and **`return True`** — native "reconciled" does not imply "matched" | `live/execution_engine.py:2501-2509` |
| **F-3** | `generate_mass_status` gathers the three plural report coroutines in a bare `asyncio.gather` inside one `try` with no `return_exceptions`, and returns `None` on any exception | `live/execution_client.py:498-514` |
| **F-4** | A `None` mass status is counted as a reconciliation failure for that client | `live/execution_engine.py:1721-1727` |
| **F-5** | If reconciliation fails, the kernel **returns** and `self._trader.start()` is never reached | `system/kernel.py:1027-1029`, `:1040`; `_await_execution_reconciliation` at `:1335-1349` |
| **F-6** | `_await_account_registered` warns "Cannot await account registration: account_id not set" and **returns** when `account_id` is unset | `live/execution_client.py:544-546` |
| **F-7** | `self.account_id = None` at construction; `_set_account_id` is the only setter and asserts `self.id.to_str() == account_id.get_issuer()` | `execution/client.pyx:135`, `:148-152` |
| **F-8** | `generate_account_state(balances, margins, reported, ts_event, info)` builds and publishes the `AccountState`; nothing calls it for you | `execution/client.pyx:329-367` |
| **F-9** | `generate_order_denied(strategy_id, instrument_id, client_order_id, reason)` exists | `execution/client.pyx:370` |
| **F-10** | `_query_account` is **called** and **never defined** in `LiveExecutionClient` | called at `live/execution_client.py:332`; no `async def _query_account` anywhere in the module source |
| **F-11** | Native defaults: `reconciliation=True` (`:177`), `filter_unclaimed_external_orders=False` (`:180`), `generate_missing_orders=True` (`:183`), `inflight_check_interval_ms=2000` (`:184`), `inflight_check_threshold_ms=5000` (`:185`), `inflight_check_retries=5` (`:186`), `open_check_interval_secs=None` (`:188`) | `live/config.py` |
| **F-12** | `filter_unclaimed_external_orders=True` makes the engine **discard** an unclaimed external report | `live/execution_engine.py:3575` |
| **F-13** | The kernel raises `ValueError` only for an **unrecognized** `cache.database.type`; `"redis"` is the only supported value; **no connectivity probe anywhere** | `system/kernel.py:309-329` |
| **F-14** | `_ORDER_STATE_TABLE`: seven transitions into `FILLED`, zero from it | `model/orders/base.pyx:116,124,126,136,143,150,156` |
| **F-15** | `TradingNode.add_data_client_factory(name, factory)` at `:230`, `add_exec_client_factory(name, factory)` at `:251`; both take the factory **class** | `live/node.py` |
| **F-16** | `LiveExecClientFactory.create(loop, name, config, msgbus, cache, clock) -> LiveExecutionClient` is the exec-client extension point, and is the **only** composition seam for one | `live/factories.py` |
| **F-17** | `LiveExecutionEngine` exposes `registered_clients` and `_clients`; `TradingNode` exposes `cache`, `portfolio`, `trader` and no kernel or engine accessor — a constructed exec client is **not** reachable from outside | `dir()` over both classes on the installed 1.231.0 |

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
| **B-15** | `QUOTA_KEY_PORTFOLIO` (`transport.py:93`) is in `PERMITTED_QUOTA_KEYS` (`:98-106`), budgeted at 12/min, and has **no caller in `src/`** today | `transport.py`; grep of `quota_key=` under `src/breezy/adapters/polymarket_us/` |
| **B-16** | `PolymarketUSLiveDataClientFactory` (`factories.py:320`) with `create` at `:334`; `config_from_env` at `:197`; credentials loaded at `:364`. `test_module_defines_no_execution_client_factory` (`tests/unit/test_polymarket_us_factories.py:461`) is scoped to that module only, and `create` is already tested socket-free by monkeypatching `NautilusHttpTransport` and the credential loader (`:181-182`) | as cited |
| **B-17** | `resolve_alert_sink` (`health.py:495`), `emit_alert` catching `BaseException` (`:514-535`), `WebhookAlertSink.close` (`:479-492`). The sink is constructed **only** in `ingest_runtime` (`composition.py:352`) and torn down by `_close_alert_sink` (`:255-268`) — there is **no alert sink in any venue-facing process** | as cited |
| **B-18** | `BinaryOption.currency = USD` for every Breezy instrument | `src/breezy/adapters/polymarket_us/parsing.py:1204` |
| **B-19** | `safety.py`: `PERMIT_TTL_NS` = 15 min (`:157`), `_PERMIT_BUDGETS` keyed per permit (`:332`), `consume` compares notionals with a bare `!=` (`:463`), `issue_live_trading_permit` (`:527`) re-reads ceilings (`:548`) and installs a fresh `_Budget` (`:575`), `assert_live_order_submission_permitted` (`:626`) takes no method and no path, and there is already a `type(x) is not Decimal` guard at `:676` to mirror. `issue_live_trading_permit` is in the package `__all__` (`adapters/polymarket_us/__init__.py:107,191`) | as cited |
| **B-20** | Every read surface is GET and every write surface is POST in the SDK snapshot: `account.py:16`, `portfolio.py:18,26`, `orders.py:35,42` versus `orders.py:27,47,55,63,71,79` | `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/resources/` |
| **B-21** | The SDK's response types are `total=False` throughout; `GetUserPositionsResponse.positions` is a `dict[str, UserPosition]`; `UserPosition` carries `netPosition`, `cost`, `qtyBought`, `qtySold`, `cashValue`, `marketMetadata` — and **no explicit average-entry-price field**. `ActivityType` has seven members, of which only `ACTIVITY_TYPE_TRADE` and `ACTIVITY_TYPE_POSITION_RESOLUTION` are trade-like | `sdk_snapshot/polymarket_us_0.1.2/types/portfolio.py` |
| **B-22** | `docs/evidence/venue/polymarket_us/raw/` contains 27 captures, **none** of them an authenticated account, position, order or activity payload | listing of that directory |
| **B-23** | The operator smoke already issues `GET /v1/portfolio/positions` (`:163`) and recorded 200 responses on 2026-08-30; it records **no body**; it has a frame-shape-without-values recorder at `:955` and a post-redaction verification at `:710-720`; the artifact reports "HTTP methods issued: GET" and "write requests issued: 0" | `scripts/venue/polymarket_us_auth_smoke.py`; `docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_2026-08-30T155317+0000.md` |
| **B-24** | `tests/contract/test_node_composition_contract.py` constructs a genuine `TradingNode` and never builds or runs it (`:135-143`), and asserts the construction opens no socket (`:432`) | as cited |
| **B-25** | The import-linter layer order puts `runtime` **above** `adapters`, so `adapters -> runtime` is upward; `breezy.ingest.nws_actor -> breezy.runtime.health` is already recorded as inspected debt of that class (`:79`); the forbidden-`nautilus_trader` contract needs one `ignore_imports` entry per importing module | `pyproject.toml:55-142` |
| **B-26** | 13 test modules already build Nautilus components from `nautilus_trader.test_kit.stubs`, so the engine-level RED technique is established rather than new | grep of `test_kit` under `tests/` |

---

## 10. Open questions

| ID | Question | What would close it | If it does not close |
|---|---|---|---|
| **OQ-1** | The exact field names, nesting and fixed-point scale of `GetAccountBalancesResponse`, `GetUserPositionsResponse`, `GetOpenOrdersResponse` and `GetActivitiesResponse` | **NS-1**, from a live authenticated read | NS-4's mappers refuse by record and clause (c) of the goal state is not claimed (see NS-1, "if the operator run cannot happen") |
| **OQ-2** | Which venue field carries a position's **average entry price**. `UserPosition` has `cost` and `netPosition` but no explicit avg-px field (B-21) | NS-1's shape artifact | `PositionStatusReport.avg_px_open` is left `None` and `_assert_reconciled` compares quantity only, **stating that limitation in the code**, rather than deriving a price from `cost / netPosition` unverified |
| **OQ-3** | Should the alert primitives move below `adapters` instead of `exec/client.py` importing `breezy.runtime.health` upward? | A survey of `health.py`'s own dependencies; it is a `runtime` module with no obvious downward blocker | NS-5 adds one `ignore_imports` entry of the same class as the recorded `nws_actor` debt, and this stays open |
| **OQ-4** | Is `/v1/portfolio/activities` actually the fill source, and does it distinguish a fill from a deposit or transfer? | NS-1's shape artifact plus `ActivityType` (B-21) | The fill mapper maps `ACTIVITY_TYPE_TRADE` only and refuses every other type by name — a refusal, never a guess |
| **OQ-5** | Does the venue's 30-second signing window hold for these four endpoints? The 2026-08-30 smoke observed a **deliberately stale (-120 s) timestamp ACCEPTED** on `/v1/portfolio/positions` `[V]` | A repeat observation in NS-1 | Nothing in this plan depends on it; recorded so a future tightening is noticed rather than assumed |
| **OQ-6** | Is `base_currency=USD` strictly safer than `None`, given the currency-identity check? | A local test once a balances shape is known | `None` plus the identity check ships |
| **OQ-7** | Do the deferred permit defects (endpoint scope, fingerprint contract, authority types) need to land before *any* capability is minted, or only before the first exposure-opening one? | A review of the first SEND increment's plan | Treated as **hard prerequisites of the first increment that mints a capability**, which is the conservative reading |
| **OQ-8** | Does `GET /v1/orders/open` ever return an order Breezy did not place — for example one the operator placed manually on the same API key? | Observation in NS-1 | NS-4's order-status mapper maps them, NS-5 reports them, and reconciliation attributes them natively; nothing in this plan claims Breezy is the only actor on the key |

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

1. **Section 9.1 first.** Five of the predecessor's `[V]` claims were wrong. If
   any claim in 9.2 or 9.3 is wrong, the increment resting on it is wrong.
2. **Section 2 against section 3.** Does every artifact have a container, and is
   that container earlier?
3. **Section 1's predicate against section 4's walk.** Does the walk actually
   arrive, and does each increment add what it claims?
4. **The REDs.** For each, ask: *what makes this go red, and could a wrong
   implementation make it go green?* Two are already flagged as weak (NS-3 RED 6
   is vacuous until the builder lands; NS-4 RED 5 passes by rule C1 the moment
   the path string exists). Find the others.
5. **Section 8.** Is anything deferred that the goal state secretly needs? Is
   any hook left for something deferred?
6. **The scan.** After every increment: `scan_write_egress(("src","scripts"))`
   returns zero violations outside `exec/endpoints.py`, and both
   `PERMITTED_METHODS` frozensets are still `frozenset({"GET"})`.
