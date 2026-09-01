# Polymarket.us Read-Only Authenticated Path — Build Plan ("Step 1")

Status: plan artifact, revision 2, 2026-08-25. Implementation not started.

Revision 2 closes the findings of three independent adversarial reviews
(architecture, security, Python/Nautilus). Every venue claim below has been
re-opened and re-read in the cited artifact. Two claims in revision 1 were
withdrawn as unsourced; one reviewer correction was itself found mis-grounded
and is answered in §13.

Subordinate to, and consistent with:

- `docs/plans/archive/POLYMARKET_US_BUILD_PLAN.md` — binding constraints (`:13-25`),
  evidence standard (`:27-35`), transport decision (`:37-56`), phase table
  (`:58-71`), safety notes (`:101-113`).
- `docs/plans/TRADING_ENABLEMENT_PLAN.md` — Phase 2 read-path work items
  (`:316-357`), env settings list (`:610-619`), mypy registration
  (`:596-609`).
- `docs/plans/archive/TRADING_ENABLEMENT_FINDINGS.md` — gap register (`:212-249`),
  non-negotiables (`:252-274`).
- `docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md` — SEC-3 / SEC-4 (`:108-116`).
- `docs/evidence/venue/polymarket_us/VENUE_FACTS_2026-08-25.md`.
- Docs snapshots under `docs/evidence/venue/polymarket_us/docs_snapshots/`.
- SDK snapshot `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/`.
- Skills `.claude/skills/nautilus-trader-patterns/SKILL.md`,
  `.claude/skills/polymarket-us-integration/SKILL.md`.

Nautilus citations are to the installed
`.venv/lib/python3.13/site-packages/nautilus_trader/` at version 1.231.0.

---

## 1. Goal

Land a **read-only, authenticated** Polymarket.us path that proves, with live
evidence, that Breezy can:

1. Load Ed25519 credentials from the host environment into
   `PolymarketUSCredentials` without any secret entering a `NautilusConfig`.
2. Sign an authenticated request so `api.polymarket.us` accepts it
   (`X-PM-Access-Key` / `X-PM-Timestamp` / `X-PM-Signature`, ±30s window).
3. Perform authenticated **GET-only** reads against `api.polymarket.us` and
   unauthenticated reads against `gateway.polymarket.us`.
4. Subscribe to the markets WebSocket and land **real `QuoteTick`s for real
   weather markets in the Nautilus `DataEngine`**, via a native
   `LiveMarketDataClient` and a native `InstrumentProvider`.
5. Emit a durable, redacted evidence artifact from a one-shot smoke-test
   entrypoint proving 1–4 against the real venue.

Substrate for `POLYMARKET_US_BUILD_PLAN.md:66` (Phase 4) and the order-free
parts of `TRADING_ENABLEMENT_PLAN.md:316-357` items 2.1, 2.2, 2.3, 2.4, 2.6,
2.7.

## 2. Non-goals — and the structural guarantee

**Explicitly out of scope. Do not design, stub, or leave a seam for:**

| Out of scope | Enforced by |
|---|---|
| Any order create / cancel / amend path | No POST/DELETE code; §2 barriers |
| `LiveExecutionClient`, `LiveExecClientFactory` | Not created; not registered |
| Phase 5.1 canary / real-money probe (`BUILD_PLAN:71`) | `real_money` marker untouched |
| Risk caps, exposure caps, kill switch | Phase 5 of `BUILD_PLAN:67` |
| `BREEZY_TRADING_ENABLED` | Not read anywhere in this slice |
| `FeeModel` | `BUILD_PLAN:70` (Phase 8), backtest-only |
| Private WebSocket (`/v1/ws/private`) | Not connected; only `/v1/ws/markets` |

### 2.1 Barriers against live order submission

Revision 1 claimed three "independent" barriers. **They were not independent** —
all three assumed egress originates inside
`src/breezy/adapters/polymarket_us/`. Two concrete escape paths were found:

- **Escape A (outside the package).** A module anywhere else — e.g.
  `scripts/venue/` — can `from polymarket_us.auth import create_auth_headers`
  and POST `/v1/orders` itself. The shipped ban at
  `tests/unit/test_polymarket_us_phase0_safety.py:189-198` matches only
  `node.module == "polymarket_us"` **and** the imported name `PolymarketUS`;
  `polymarket_us.auth` is a different module string and is not matched at all.
- **Escape B (inside the package).** `nautilus_pyo3.HttpClient` is POST-capable
  (`core/nautilus_pyo3.pyi:5450-5459` defines `async def post(...)`, and
  `:5429` a generic `request(...)`). If the transport wrapper holds the client
  as an attribute, `client._transport._client.post(...)` reaches it — and
  contains no `"POST"` string literal for an AST scan to find. Storing a bound
  `client.get` method is also insufficient: `bound_method.__self__` exposes the
  same POST-capable client.

**Revised barriers, now genuinely layered:**

| # | Barrier | Closes |
|---|---|---|
| B1 | `PolymarketUSHttpClient` exposes exactly `get_authenticated` and `get_public`. Its one private dispatch helper asserts `method in _PERMITTED_METHODS` (`frozenset({"GET"})`) → `MethodNotPermittedError`. | Naive misuse |
| B2 | `Ed25519RequestSigner.sign_headers` raises `MethodNotPermittedError` for any method other than `GET`. An order request cannot be signed by Breezy code. | Signing a write |
| B3 | **`NautilusHttpTransport` holds the `HttpClient` in a GET-only callable closure, not as an attribute or bound pyo3 method.** `tests/unit/test_polymarket_us_transport.py::test_transport_does_not_expose_real_pyo3_client_through_bound_method_self` constructs the real pyo3 client and asserts no `transport` attribute has a `__self__` exposing callable `.post`; `tests/unit/test_polymarket_us_readonly_guard.py::test_b3_constructed_transport_exposes_no_write_capable_receiver` pins the same receiver graph with a write-capable double. Residual: deliberate closure-cell introspection can still recover the client; ordinary attribute and `__self__` paths cannot. | Escape B |
| B4 | **Repo-wide AST guard** over `src/` **and** `scripts/`: fails if any venue-touching module contains the literals `"POST"`, `"DELETE"`, `"PUT"`, `"PATCH"`, or `/v1/orders`; and fails on any `ast.Attribute` access named `post`/`put`/`patch`/`delete`/`request` on any receiver. | Escape B, plus drift |
| B5 | **Import ban on the SDK's signing module repo-wide.** `from polymarket_us.auth import …` and `import polymarket_us.auth` are permitted in **no** file except the one differential-oracle test named in Step 4. Implemented by prefix-matching `node.module.split(".")[0] == "polymarket_us"` rather than exact equality — which also repairs the shipped ban's blind spot. | Escape A |
| B6 | `safety.assert_live_order_submission_permitted` (shipped) remains the future single chokepoint. This slice adds **no caller**; Step 13 asserts that. | Regression |

B4 and B5 are the load-bearing ones because they are the only barriers whose
scope is the repository rather than one directory.

---

## 3. Decisions

### D1 — Environment variables: venue-qualified `POLYMARKET_US_*`

`TRADING_ENABLEMENT_PLAN.md:615-617` specifies `BREEZY_VENUE_ACCESS_KEY`,
`BREEZY_VENUE_PRIVATE_KEY_FILE`, `BREEZY_VENUE_API_BASE`,
`BREEZY_VENUE_GATEWAY_BASE`, `BREEZY_VENUE_WS_URL`. Shipped
`src/breezy/adapters/polymarket_us/credentials.py:25-26` defaults to
`POLYMARKET_US_KEY_ID` / `POLYMARKET_US_SECRET_KEY`.

**Decision: adopt `POLYMARKET_US_*`. The `BREEZY_VENUE_*` names are withdrawn.**

Rationale, in weight order:

1. **Kalshi makes a venue-anonymous credential name unrepresentable.** Kalshi is
   a committed second venue (`BUILD_PLAN` preamble; polymarket-us skill's Kalshi
   note) using **RSA-PSS SHA256**, not Ed25519 — a different key format and a
   different failure surface. One process will eventually hold both key sets,
   and a single `BREEZY_VENUE_ACCESS_KEY` cannot hold two values. This is the
   decisive argument.
2. **Shipped code and shipped tests already encode it.** `credentials.py:25-26`
   and `tests/conftest.py:47-60` name `POLYMARKET_US_*`. The `BREEZY_VENUE_*`
   names appear in **no** source file, test, or script — verified by grep across
   `src/`, `tests/`, `scripts/` with zero matches. Choosing the unshipped scheme
   is a rename with no offsetting benefit.
3. **The credential tripwire is name-matched.** `tests/conftest.py:47-60` aborts
   on a fixed list of Polymarket-shaped names. Venue-qualified names keep that
   list mechanically derivable from the venue package.

`BREEZY_*` remains correct for **process-wide** settings owned by
`runtime/settings.py`. Venue credentials and venue endpoints are not
process-wide.

> Revision 1 additionally cited `TRADING_ENABLEMENT_PLAN.md:580` as forbidding
> the generality `BREEZY_VENUE_*` implies. That line forbids a **generic
> multi-venue abstraction layer in code**, not an env-var naming scheme. The
> argument is withdrawn as an over-read; the decision rests on points 1–3.

**Migration:** doc-only. No code reads the old names. An errata note is added to
`TRADING_ENABLEMENT_PLAN.md:610-619` in the same change as Step 1, recording
that the five `BREEZY_VENUE_*` names are superseded by §7 below and that
`BREEZY_TRADING_ENABLED`, `BREEZY_BOUNDARY_UNRESOLVED_ALERT_FRACTION` and
`BREEZY_MAX_EXPOSURE_*` are unaffected.

### D2 — Two independent unlocks for live venue tests

Today `pytest_sessionstart` (`tests/conftest.py:113-122`) aborts the session if
any name in `POLYMARKET_CREDENTIAL_ENV_VARS` is set. Correct for the default
suite; it also makes the `venue_live` tests this plan introduces unrunnable.

Revision 1 proposed gating the abort on `BREEZY_VENUE_LIVE=1`. **That was
wrong**: it made one variable do double duty — silencing the credential
kill-switch *and* unlocking `venue_live` execution
(`tests/conftest.py:146-153`). A stray `BREEZY_VENUE_LIVE=1` in a shell profile,
combined with any CI or IDE invocation that overrides `-m`, would fire real
signed read requests where the default pytest credential tripwire previously
refused at startup.

**Decision: require two independently-named confirmations, neither of which
alone is sufficient.**

1. `pytest_sessionstart` aborts on present credentials **unless** both
   `BREEZY_VENUE_LIVE == "1"` **and** a second, distinctly-named variable
   `BREEZY_ALLOW_CREDENTIALED_PYTEST == "1"` are set. `BREEZY_VENUE_LIVE` alone
   no longer silences the abort; `BREEZY_ALLOW_CREDENTIALED_PYTEST` alone
   unlocks nothing, because the marker gate still deselects `venue_live`.
   Additionally the session must have been invoked with the explicit
   `--venue-live` flag (registered via `pytest_addoption`), which a stray
   environment variable cannot supply. All three are required.
2. When the exemption applies, print a one-line notice naming only the
   **variable names** present — never values.
3. A new autouse fixture `_scrub_venue_credentials` `monkeypatch.delenv`s every
   name in `POLYMARKET_CREDENTIAL_ENV_VARS` for any test **not** marked
   `venue_live` or `real_money`. So even inside a credentialed session, a unit
   test that calls `load_polymarket_us_credentials()` sees an empty environment
   and raises.
4. `POLYMARKET_CREDENTIAL_ENV_VARS` gains no new entries.
   `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY` and
   `POLYMARKET_US_SECRET_KEY_FILE` are already listed
   (`tests/conftest.py:48,51,52`). The **endpoint** variables
   (`POLYMARKET_US_API_BASE`, `_GATEWAY_BASE`, `_WS_URL`) are **not**
   credentials and must NOT be added — that would abort the live suite on
   non-secret configuration and teach the tripwire to cry wolf.

The existing guard `test_pytest_fails_fast_when_polymarket_credentials_are_present`
(`tests/unit/test_polymarket_us_phase0_safety.py:144`) stays GREEN unchanged:
its inner pytest sets none of the three unlocks. New sibling tests assert that
**each unlock alone** still aborts.

### D3 — Package location: `src/breezy/adapters/polymarket_us/`

`TRADING_ENABLEMENT_PLAN.md:325-336` proposes `src/breezy/venue/polymarket_us/`.
The shipped package is `src/breezy/adapters/polymarket_us/` and the shipped
Phase-0 tests import from it. **`adapters/` is authoritative**; it also matches
Nautilus's own `nautilus_trader/adapters/<venue>/` layout. Register
`"src/breezy/adapters"` in `[tool.mypy].files` (`pyproject.toml:63-71`) in
Step 1 — per `TRADING_ENABLEMENT_PLAN.md:596-599`, an unregistered package
silently escapes strict typing. Same errata note as D1.

### D4 — Authenticated REST transport: native `nautilus_pyo3.HttpClient`

`POLYMARKET_US_BUILD_PLAN.md:41-45` decides "B-for-REST": use the SDK **behind a
Breezy-owned protocol**, and explicitly anticipates "a contained private `_http`
seam **or a Breezy transport fallback** if contract tests require lower-level
control."

**Decision: exercise that sanctioned fallback for the authenticated path.** The
Breezy-owned protocol (`PolymarketUSReadTransport`) stands; its implementation
for `api.polymarket.us` is native `nautilus_pyo3.HttpClient`.

Evidence, re-read in the committed artifacts:

1. **No injectable transport.** `sdk_snapshot/.../client.py:66` constructs
   `httpx.Client(timeout=timeout)` internally; nothing can be passed in. The
   loopback oracle in §9 would have to monkeypatch a private attribute of a
   third-party object — a test asserting on our own patch, not on our code.
2. **No rate control.** The SDK has no throttle at all. `HttpClient`'s
   constructor takes `keyed_quotas: list[tuple[str, Quota]]` and
   `default_quota: Quota` (`core/nautilus_pyo3.pyi:5417-5425`), and
   `get(...)` takes `keys: list[str]` to select them (`:5441-5448`) —
   native, already built, and exactly what §8's per-endpoint budget needs.
3. **Response headers.** We must read `Retry-After` and `X-RateLimit-*`.
   `HttpClient` exposes them via the `header_keys` allow-list, and hides them by
   default (nautilus-trader-patterns trap 11). This is a deliberate,
   named construction argument.

> **Correction to `BUILD_PLAN:41-42`.** That line records as DIRECT EVIDENCE
> that "SDK 0.1.2 exports `AsyncPolymarketUS`". **The committed snapshot does
> not support it.** `grep -rn "AsyncPolymarketUS"` across
> `sdk_snapshot/polymarket_us_0.1.2/` returns zero matches; the only client
> class is the **synchronous** `class PolymarketUS` at `client.py:39`
> ("Synchronous client for the Polymarket US API"). Async *resource* wrappers
> exist (`resources/markets.py:41` `class AsyncMarkets`), but no async client
> owns them in the snapshot. Either the snapshot is partial or the claim is
> wrong; both are material because `BUILD_PLAN:24-25` bans importing the **sync**
> client, and the snapshot contains only a sync client. Step 1 records this as
> an amendment to `BUILD_PLAN` and to `VENUE_FACTS`. **It strengthens D4**: the
> sanctioned SDK REST path may not exist in the pinned version at all.

The SDK remains: (a) the **schema oracle** for paths, response shapes and the WS
subscribe envelope; (b) the **differential oracle** for the signature test
(Step 4). `polymarket-us==0.1.2` stays an optional extra
(`pyproject.toml:30`), and the sync-import ban is preserved and widened (B5).

### D5 — WebSocket: native transport, **Breezy-owned reconnect**

`POLYMARKET_US_BUILD_PLAN.md:46-53` chose native
`nautilus_pyo3.WebSocketClient` + `WebSocketConfig` for heartbeat, idle timeout
and reconnect backoff. That still holds for the transport — but revision 1's
claim that headers are "recomputed on every connect, including after a
reconnect" was **false**, and it is the exact failure it claimed to close. See
§5.3. Reconnect authentication becomes Breezy-owned.

---

## 4. Nautilus native capabilities reused (null hypothesis first)

| Capability | Used for | Evidence (re-read) |
|---|---|---|
| `LiveMarketDataClient` | Data client base — lifecycle, `is_connected`, typed `_subscribe_*` | `live/data_client.py:349-374`; hard-validates `instrument_provider` via `PyCondition.type` at `:361` |
| `LiveDataClientConfig` | Config base — `msgspec.Struct, kw_only, frozen, forbid_unknown_fields` | `live/config.py:222` |
| `LiveDataClientFactory` + `node.add_data_client_factory(name, FactoryClass)` | Node wiring; credentials resolved **in the factory** | `live/factories.py:27-33`; `live/node.py:230`; precedent `adapters/databento/factories.py:120-127` |
| `InstrumentProvider` / `InstrumentProviderConfig` | Instrument supply, required by the base | `BUILD_PLAN:65` |
| `BinaryOption` + `pUSD` | Native 0–1 prediction instrument; notional `qty × p`, multiplier 1 | nautilus-trader-patterns §"Natively provided for prediction markets" |
| `nautilus_pyo3.HttpClient` | Authenticated GET transport; `keyed_quotas`, `default_quota`, `header_keys`, per-call `keys` | `core/nautilus_pyo3.pyi:5417-5448` |
| `nautilus_pyo3.Quota` | `rate_per_second` / `rate_per_minute` / `rate_per_hour` factories | `core/nautilus_pyo3.pyi:5520-5527` |
| `nautilus_pyo3.WebSocketClient` + `WebSocketConfig` | WS transport: `heartbeat`, `idle_timeout_ms`, reconnect backoff/jitter/max-attempts; `is_active()`, `is_closed()`, `is_reconnecting()` | `core/nautilus_pyo3.pyi:5530-5566` |
| `RetryManager` (`live/retry.py`) | Bounded retry of **GET** reads only; returns `None` on failure | nautilus-trader-patterns §"Re-subscription" |
| `SecureString` | Runtime credential containment; already used at `credentials.py:41-42` | `common/secure.py:26-121` — **and see S15 for its documented limit** |
| `adapters.env.get_env_key` | Env read helper (raises `RuntimeError`, not `KeyError`) | nautilus-trader-patterns §"Config & secrets convention" |
| `Price.from_str` / `Quantity.from_str` / `Decimal` | All price/qty conversion; never `float()` | `BUILD_PLAN:66` exit gate |
| `QuoteTick`, `MessageBus`, `DataEngine`, `self._handle_data(...)` | Quote delivery | Native |
| `LiveClock.timestamp_ms()` | `X-PM-Timestamp` source, injectable | Native |

### Net-new, and why each is unavoidable

| New module | Why Nautilus cannot supply it |
|---|---|
| `signing.py` | 1.231.0 ships **no** Ed25519 request signer. Its two Polymarket adapters target **`.COM`** and sign EIP-712 by delegating to `py_clob_client_v2`, which is not installed and whose signing layer "is not in the tree to copy" (nautilus-trader-patterns §"Reference adapters"). Nothing to reuse. |
| `env.py` | `get_env_key` reads one string. No key **file**, no mode/ownership check, no `SecureString` wrapping. We call it where it applies and add only the file/permission/redaction layer. |
| `symbology.py` | Bundled `polymarket/common/symbol.py:20-41` splits on `-` and indexes `[0]`/`[1]`, which a slug scheme "breaks outright". `BUILD_PLAN:65` requires a test proving we never import it. |
| `errors.py` / `redaction.py` | Venue-specific status mapping; SEC-3 redaction contract. |
| `parsing.py` | Venue camelCase payload → Nautilus types. |
| Breezy-owned WS reconnect | See §5.3: the native reconnect cannot re-sign. |

Everything else is an implementation of a native base class, not a new
abstraction.

---

## 5. Open unknowns, and how the design stays correct either way

### 5.1 The canonical string — G3, and the query-string question

`TRADING_ENABLEMENT_FINDINGS.md:220-222` names G3 (does the request **body**
participate in the signed canonical string) as the gap where being wrong fails
100% of order submissions.

**This slice is GET-only, so both G3 branches produce byte-identical input.**
The seam is `signing.CanonicalRequest`, carrying `body: bytes = b""`, consumed by
an injectable strategy; resolving G3 later adds a builder function and changes a
factory selection, nothing else. A unit test asserts the shipped builders ignore
`body`, so the seam is proven inert here. Matches
`TRADING_ENABLEMENT_PLAN.md:239-242`.

**Withdrawn claim.** Revision 1 asserted that the venue authentication docs state
"Query string is INCLUDED in the path", and built a "documented divergence from
the SDK" on it. **That is false.** Re-read:

- `docs_snapshots/api-reference_authentication_2026-08-25.md:82`: *"The
  signature is built by combining the timestamp, HTTP method, and path"* — no
  mention of a query string.
- The same page's worked example (`:92-106`) signs `"/v1/portfolio/positions"`,
  a bare path with no query, and constructs `message = f"{timestamp}{method}{path}"`
  (`:94`).
- `sdk_snapshot/.../auth.py:26-27` builds the identical string, and
  `client.py:132` passes the **path only** while query params go separately to
  httpx (`client.py:135,138-144`).

The "query included" sentence exists only in the Breezy-authored
`.claude/skills/polymarket-us-integration/SKILL.md:83`, which cites no source.
**There is no documented divergence.** Docs and SDK agree: path only.

**Decision:** the default builder is `build_canonical_path_without_query`.
`build_canonical_path_with_query` still ships, and both are unit-tested from day
one — but it is now the **hypothesis to disprove** at smoke step C, not the
default. This is deferred *measurement*, not a deferred decision: the default is
chosen, on evidence, today. Step 1 also corrects `SKILL.md:83` and appends the
determination to `VENUE_FACTS`.

**Inherited protocol weakness (record, do not fix).** The canonical string
`timestamp + METHOD + path` has **no field delimiter**, so distinct
(timestamp, method, path) triples can in principle collide into identical signed
bytes. Not exploitable in this slice — `METHOD` is the fixed constant `"GET"`
and `timestamp` is clock-derived and 13 digits — but it is a venue protocol
weakness that matters once a write path with variable methods exists. Recorded
in `VENUE_FACTS` as an inherited weakness for future write-path work.

### 5.2 G15 — is `gateway.polymarket.us` reachable from a headless server?

`TRADING_ENABLEMENT_FINDINGS.md:246-248` flags a documented 403 to non-browser
fetches. **The repo's own evidence already contradicts the pessimistic branch**:
`VENUE_FACTS_2026-08-25.md:145,183,209,233,272,289,301,316,539,568,676,681,725`
records successful unauthenticated `GET https://gateway.polymarket.us/...` from
this host on 2026-08-25, with committed raw JSON. G15's favourable branch
(`TRADING_ENABLEMENT_PLAN.md:231-234`) is taken as **DIRECT EVIDENCE,
provisional**: one host, one date, one User-Agent.

Design so the pessimistic branch is cheap and loud:

- The gateway is reached **only** through `PolymarketUSHttpClient.get_public`.
- A `403` from the gateway raises typed `GatewayForbiddenError` — the named
  signal for a G15 regression, never a generic failure.
- The smoke test records the gateway status code and the effective User-Agent,
  so a future 403 is dated and attributable.
- The client sends an explicit, non-empty User-Agent — the adapter's own, per §7.
  It must **never** read `BREEZY_USER_AGENT`, which `runtime/settings.py`
  reserves exclusively for `ingest.http`.

Revision 1 additionally specified a `GATEWAY_FALLBACKS` mapping table routing
each public path to an authenticated equivalent on 403. **Dropped as YAGNI** —
no 403 has been observed from this host, the authenticated equivalents are
themselves unverified, and a speculative fallback that silently re-routes is
worse than a loud failure. If a 403 is ever observed, `GatewayForbiddenError`
names the path and the escalation follows `TRADING_ENABLEMENT_PLAN.md:233-234`.

### 5.3 WebSocket reconnect authentication — a correctness defect in revision 1

Revision 1 asserted that auth headers are "computed at each connect, including
after a native reconnect". **The pyo3 API makes that impossible.** Re-read at
`core/nautilus_pyo3.pyi:5530-5566`:

- `WebSocketConfig.__init__(url, headers: list[tuple[str, str]], heartbeat, ...)`
  — `headers` is **fixed at construction** (`:5531-5544`).
- `WebSocketClient.connect` is a **classmethod** taking that config
  (`:5547-5556`); the Rust layer reconnects internally, reusing those headers.
- `post_reconnection` fires **after** the handshake has already succeeded — it
  cannot supply headers to the handshake that just happened.

Consequence: a reconnect occurring more than 30 seconds after the original
`sign_headers` call replays a **stale `X-PM-Timestamp`** and the venue rejects
the handshake. `reconnect_max_attempts` cannot help — every attempt carries the
same dead timestamp.

**Remedy, in two parts:**

(a) **Establish whether `/v1/ws/markets` requires auth at all.** The SDK signs it
(`websocket/base.py:51` calls `create_auth_headers(..., "GET", self.path)`), so
assume **yes** until measured. Smoke step E1 (§10) connects **without** auth
headers and records the result. If the markets WS is public, this whole problem
disappears and the native reconnect is used unmodified — the best outcome, and
cheap to test.

(b) **If auth is required, Breezy owns reconnect.**
`PolymarketUSMarketsWebSocket` runs a supervisor task on the client's event loop
that polls `is_active()` / `is_closed()` / `is_reconnecting()`
(`:5559-5562`). On a dead socket it **builds a fresh `WebSocketConfig` with
freshly signed headers** and calls `WebSocketClient.connect(...)` again, then
replays subscriptions. Native reconnect is disabled for this path by setting
`reconnect_max_attempts=0`, so the two mechanisms cannot race. Backoff and
jitter are then Breezy's (via `RetryManager`), which is the cost of (b) and the
reason (a) is measured first.

### 5.4 Other unknowns carried, not resolved

| Gap | Effect here |
|---|---|
| G1 slug grammar | Slugs are **required operator input**, never derived. `VENUE_FACTS` observed e.g. `tc-temp-nychigh-2026-08-25-lt79f`. |
| G4 per-market tick / min-qty | Read from market metadata; never a constant (`FINDINGS:225-227`). |
| G6 WS schema, sequence numbers | Envelope taken from the SDK (§6, `websocket.py`). No sequence number assumed; `idle_timeout_ms` plus a staleness bound is the safety net. |
| G2, G7, G8 | Order-path gaps. Untouched — no order path exists here. |

---

## 6. File-by-file blueprint

All paths under `src/breezy/adapters/polymarket_us/` unless stated. Every
parameter is annotated: mypy `strict = true` is active repo-wide
(`pyproject.toml:60-62`) and will cover this package from Step 1 (D3).

### `redaction.py` (new)

Separated from `errors.py` so redaction has no dependency on the error
hierarchy and can be imported by the smoke script and the evidence writer.

```
REDACTED: str = "<redacted>"
SENSITIVE_HEADERS: frozenset[str] = frozenset({
    "x-pm-access-key", "x-pm-signature", "x-pm-timestamp", "authorization", "cookie",
})

def redact_headers(headers: Mapping[str, str]) -> dict[str, str]: ...
def redact_text(text: str, secrets: Iterable[str]) -> str: ...
def redact_url(url: str) -> str: ...
```

### `errors.py` (new)

```
class PolymarketUSError(Exception): ...
class CredentialSourceError(PolymarketUSError): ...
class MethodNotPermittedError(PolymarketUSError): ...
class SignatureClockSkewError(PolymarketUSError): ...
class VenueAuthError(PolymarketUSError): ...
class GatewayForbiddenError(PolymarketUSError): ...
class VenueRateLimitError(PolymarketUSError):
    def __init__(self, message: str, *, retry_after: str | None) -> None: ...
class VenueStatusError(PolymarketUSError):
    def __init__(self, message: str, *, status_code: int) -> None: ...
class VenueTransportError(PolymarketUSError): ...
```

Every `__str__` is built from `method`, `redact_url(path)`, `status_code` and a
`redact_headers(...)` view — never a raw header map, never a response body.

### `credentials.py` (modify)

Keep everything shipped. Add one field:

```
class PolymarketUSSecretsRefConfig(NautilusConfig, frozen=True):
    key_id_env_var: str = "POLYMARKET_US_KEY_ID"
    secret_key_env_var: str = "POLYMARKET_US_SECRET_KEY"
    secret_key_file_env_var: str = "POLYMARKET_US_SECRET_KEY_FILE"   # NEW
```

`__post_init__` validates it with the existing `_require_env_name`
(`credentials.py:83-91`). The module-level
`assert_config_type_excludes_secrets(PolymarketUSSecretsRefConfig)` at
`credentials.py:94` continues to pass — all three fields are `str` names.

### `env.py` (new)

```
def load_polymarket_us_credentials(
    secrets_ref: PolymarketUSSecretsRefConfig,
    *,
    env: Mapping[str, str] | None = None,
    require_key_file_mode: int = 0o600,
    require_owner_uid: int | None = None,   # defaults to os.getuid()
) -> PolymarketUSCredentials: ...
```

1. `key_id` from `secrets_ref.key_id_env_var` → `CredentialSourceError` naming
   the **variable** (never a value) if absent/blank.
2. Secret source — **file preferred**, and read **TOCTOU-safely**:
   - Revision 1 specified `Path.stat()` then read. That is a stat-then-read race
     with no ownership or symlink test: an attacker who can swap the path
     between the two calls passes the check and supplies a different file.
   - **Corrected procedure:** `fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)`,
     then `st = os.fstat(fd)` — checks apply to the **opened** file, and
     `O_NOFOLLOW` refuses a symlink at the final component outright. Assert
     `stat.S_ISREG(st.st_mode)`, `st.st_mode & 0o777 == require_key_file_mode`
     **exactly**, and `st.st_uid == require_owner_uid`. Read from `fd`; close in
     `finally`. Failures raise `CredentialSourceError` naming the path and the
     observed octal mode / uid — never contents.
   - **Residual assumption, documented:** this relies on POSIX mode and
     ownership semantics. On filesystems without them (FAT/exFAT, some network
     and container-overlay mounts, WSL DrvFs) the mode check is meaningless. The
     runbook requires the key on a POSIX-semantics local filesystem; the smoke
     script records `st.st_dev` and the filesystem type in its evidence.
   - Else `secret_key_env_var` if set, with a WARNING that a file source is
     preferred. **Both set → `CredentialSourceError`** (ambiguous source is a
     configuration bug, not a precedence question). Neither →
     `CredentialSourceError`.
   - **Residual gap, documented (review item 5a):** `O_NOFOLLOW` constrains the
     **final path component only**. A symlinked **ancestor directory** can still
     redirect the open — given `/etc/breezy/keys/pm.key`, an attacker able to
     replace `keys/` with a symlink defeats it. Closing this needs
     `openat2(RESOLVE_NO_SYMLINKS)`-style directory-walk resolution, which is
     Linux-specific and deliberately **not** implemented. Mitigation is
     operational: the whole directory chain must be owned by the running user or
     root and must not be group/world-writable. Recorded in the `env.py` module
     docstring as well.
3. Validate shape **without logging it**: base64-decodable, decoded length
   ∈ {32, 64} (`sdk_snapshot/.../auth.py:30-34` accepts both and truncates 64 →
   first 32). Failure reports the length only.
4. Wrap both in `SecureString`; return `PolymarketUSCredentials`.

> **⚠ Blocking I/O — trap for the async phase (review item 6).**
> `load_polymarket_us_credentials` does synchronous filesystem I/O
> (`os.open`/`os.fstat`/`os.read`). Nautilus runs its live clients on a single
> asyncio event loop, so calling this from a coroutine — e.g. inside
> `LiveMarketDataClient._connect` or a reconnect handler — **blocks the loop and
> stalls every other client on it**, including the settlement feed.
> **Rule:** load credentials **once at startup, before the loop runs** (in the
> adapter factory / `TradingNode` construction), or wrap the call in
> `asyncio.to_thread`. Never re-read the key file on the reconnect path.
> Mirrored as a comment at the `env.py` read site so it is visible where the
> mistake would be made.

### `signing.py` (new)

```
PERMITTED_METHODS: frozenset[str] = frozenset({"GET"})
DEFAULT_SKEW_TOLERANCE_MS: int = 30_000

class SigningVariant(enum.StrEnum):
    PATH_ONLY = "path_only"
    PATH_WITH_QUERY = "path_with_query"

@dataclass(frozen=True, slots=True)
class CanonicalRequest:
    timestamp_ms: int
    method: str
    path: str
    query_string: str = ""
    body: bytes = b""

CanonicalStringBuilder = Callable[[CanonicalRequest], bytes]

def build_canonical_path_without_query(request: CanonicalRequest) -> bytes:
    """DEFAULT. timestamp + METHOD + path. Ignores query_string and body.
    Evidence: api-reference_authentication_2026-08-25.md:82,94,105;
    sdk_snapshot/.../auth.py:26-27; client.py:132,135."""

def build_canonical_path_with_query(request: CanonicalRequest) -> bytes:
    """Hypothesis under test at smoke step C. Ignores body."""

BUILDERS: Mapping[SigningVariant, CanonicalStringBuilder]

class Ed25519RequestSigner:
    def __init__(
        self,
        credentials: PolymarketUSCredentials,
        *,
        clock: LiveClock,
        canonicalize: CanonicalStringBuilder = build_canonical_path_without_query,
        skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS,
    ) -> None: ...

    def sign_headers(
        self, method: str, path: str, *, query_string: str = "", timestamp_ms: int | None = None
    ) -> list[tuple[str, str]]: ...

    def assert_within_window(self, timestamp_ms: int) -> None: ...

    def __repr__(self) -> str: ...   # "Ed25519RequestSigner(<redacted>)"
```

**`sign_headers` returns `list[tuple[str, str]]`, not `dict[str, str]`.**
Revision 1 specified a dict, which fails at the pyo3 boundary and under mypy
strict: `WebSocketConfig.__init__` requires
`headers: list[tuple[str, str]]` (`core/nautilus_pyo3.pyi:5531-5544`). The list
form is therefore canonical. `HttpClient.get(...)` takes
`headers: dict[str, str] | None` (`:5441-5448`), so the **HTTP** call site
converts with `dict(signer.sign_headers(...))` at exactly one place in
`transport.py`; the **WebSocket** call sites (initial connect and Breezy
reconnect) pass the list through unchanged. Both conversions are pinned by test.

Other properties: `MethodNotPermittedError` for non-GET (B2); timestamp from the
injected `clock.timestamp_ms()`; `assert_within_window` on every sign so host
drift fails **locally with a named error** rather than as an opaque venue
rejection; the `SigningKey` built per call from
`credentials.secret_key.get_value()` and dropped.

Dependency: `nacl.signing.SigningKey` (PyNaCl), used by the SDK at
`sdk_snapshot/.../auth.py:6`. Add `pynacl` as a **direct** member of the
`polymarket-us` extra (`pyproject.toml:30`) rather than relying on a transitive
pin, asserted by `tests/unit/test_polymarket_us_dependency_pin.py`.

### `config.py` (new)

```
class PolymarketUSDataClientConfig(LiveDataClientConfig, frozen=True):
    secrets: PolymarketUSSecretsRefConfig = PolymarketUSSecretsRefConfig()
    api_base_url: str | None = None
    gateway_base_url: str | None = None
    ws_url: str | None = None
    market_slugs: tuple[str, ...] = ()
    user_agent: str | None = None
    signing_variant: SigningVariant = SigningVariant.PATH_ONLY
    http_timeout_secs: int = 10
    global_requests_per_second: int = 15
    instrument_requests_per_minute: int = 6
    book_requests_per_minute: int = 12
    ws_heartbeat_secs: int = 20
    ws_idle_timeout_secs: int = 60
```

`signing_variant` is a `StrEnum`, not a free string — a typo is a construction
error, not a silent fallback. `__post_init__` raises `SettingsError` naming the
offending field for any `None` or empty `market_slugs`: "Every venue parameter is
a REQUIRED INPUT with no default. Config construction must raise when any is
unset" (`TRADING_ENABLEMENT_FINDINGS.md:254-256`). `None` sentinels are how a
frozen kw-only msgspec struct expresses "required". The quota and timeout
numbers keep real defaults because they are **Breezy policy**, not venue truth.
`config.py` imports no `os`; endpoints are populated in the factory.
`assert_config_type_excludes_secrets(PolymarketUSDataClientConfig)` runs at
import, as `credentials.py:94` does.

### `transport.py` (new — split out of revision 1's `http.py`)

Revision 1 gave `http.py` four responsibilities (protocol, pyo3 wrapper, status
mapping, URL/signing orchestration) at an estimated 350–500 lines, against the
repo's 200–400-line norm. Split:

```
@dataclass(frozen=True, slots=True)
class VenueResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

class PolymarketUSReadTransport(Protocol):
    async def get(
        self, url: str, *, headers: Mapping[str, str], quota_key: str
    ) -> VenueResponse: ...

OBSERVED_RESPONSE_HEADERS: tuple[str, ...] = (
    "retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "date",
)

class NautilusHttpTransport:
    def __init__(
        self,
        *,
        timeout_secs: int,
        default_quota: Quota,
        keyed_quotas: list[tuple[str, Quota]],
        default_headers: dict[str, str],
    ) -> None:
        client = nautilus_pyo3.HttpClient(
            default_headers=default_headers,
            header_keys=list(OBSERVED_RESPONSE_HEADERS),
            keyed_quotas=keyed_quotas,
            default_quota=default_quota,
            timeout_secs=timeout_secs,
        )
        self._get = client.get          # CLOSURE-EQUIVALENT BINDING — barrier B3
        # `client` itself is NOT stored; no attribute path reaches .post/.request

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse: ...
```

Binding only the bound `get` coroutine is barrier **B3**: there is no
`transport._client` to walk to `.post`. The Python object graph still reaches
the client via `self._get.__self__`, which no accident produces and which B4's
attribute-access scan flags explicitly; the point is that the *ordinary*
attribute path is gone and the *extraordinary* one is a named lint failure.

### `http.py` (new — client only)

```
_PERMITTED_METHODS: frozenset[str] = frozenset({"GET"})

class PolymarketUSHttpClient:
    def __init__(
        self,
        *,
        transport: PolymarketUSReadTransport,
        signer: Ed25519RequestSigner,
        api_base_url: str,
        gateway_base_url: str,
        logger: Logger,
    ) -> None: ...

    async def get_authenticated(
        self, path: str, *, query: Mapping[str, str] | None = None, quota_key: str
    ) -> Mapping[str, Any]: ...

    async def get_public(
        self, path: str, *, query: Mapping[str, str] | None = None, quota_key: str
    ) -> Mapping[str, Any]: ...

    def _build_query_string(self, query: Mapping[str, str] | None) -> str:
        """Deterministic: sorted by key, percent-encoded. ONE value feeds both
        the signed canonical request and the dispatched URL."""

    async def _dispatch(
        self, method: str, base_url: str, path: str, query_string: str,
        *, authenticated: bool, quota_key: str,
    ) -> Mapping[str, Any]: ...
```

Return type is `Mapping[str, Any]`, not `Any` — mypy strict must be able to see
misuse at call sites.

Load-bearing properties:

- `_dispatch` asserts `method in _PERMITTED_METHODS` → `MethodNotPermittedError`
  (B1). It is the only place a request leaves this module; there is no public
  non-GET entry point.
- The signed canonical request and the dispatched URL are built from one
  `_build_query_string` result. Signing one string and sending another is the
  classic Ed25519 failure.
- Status mapping: 401/403 on `api` → `VenueAuthError`; 403 on `gateway` →
  `GatewayForbiddenError`; 429 → `VenueRateLimitError(retry_after=...)`;
  5xx → `VenueStatusError`; timeout/connect → `VenueTransportError`.
- Retries only via `RetryManager`, only for `VenueTransportError` /
  `VenueStatusError` / `VenueRateLimitError`. GET is idempotent; there is
  nothing non-idempotent in this slice to guard.
- **Never** logs headers. Logs `method`, `redact_url(path)`, `status`,
  `quota_key`, and the allow-listed rate-limit headers.

### `symbology.py` (new)

```
INSTRUMENT_SEPARATOR: str = "~"
POLYMARKET_US_VENUE: Venue = Venue("POLYMARKET_US")

def slug_to_instrument_id(slug: str, venue: Venue = POLYMARKET_US_VENUE) -> InstrumentId: ...
def instrument_id_to_slug(instrument_id: InstrumentId) -> str: ...
def assert_valid_slug(slug: str) -> None: ...
```

Per `BUILD_PLAN:65`: reserved separator `~`, never hyphen parsing, dotted slugs
rejected, round-trip invertible, no import of
`nautilus_trader.adapters.polymarket.common.symbol`.

### `parsing.py` (new)

```
def parse_binary_option(payload: Mapping[str, Any], *, venue: Venue, ts_init: int) -> BinaryOption: ...
def parse_quote_tick(payload: Mapping[str, Any], *, instrument: BinaryOption, ts_init: int) -> QuoteTick: ...
def parse_book_top(payload: Mapping[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]: ...
```

`Decimal` / `Price.from_str` / `Quantity.from_str` only; an AST test asserts no
`float(` call (`BUILD_PLAN:66`). camelCase keys pinned per `VENUE_FACTS` Q9.
Per-market `orderPriceMinTickSize` / `minimumTradeQty` drive precision; never a
constant (`FINDINGS:225-227`). **Pre-validate precision before constructing
`Price` / `Quantity`** — the Rust layer SIGABRTs rather than raising on bad
input (`TRADING_ENABLEMENT_FINDINGS.md` §E).

### `instruments.py` (new)

```
class PolymarketUSInstrumentProvider(InstrumentProvider):
    def __init__(
        self, *, client: PolymarketUSHttpClient, config: InstrumentProviderConfig,
        venue: Venue, market_slugs: tuple[str, ...], clock: LiveClock,
    ) -> None: ...
    async def load_all_async(self, filters: dict[str, Any] | None = None) -> None: ...
    async def load_ids_async(
        self, instrument_ids: list[InstrumentId], filters: dict[str, Any] | None = None
    ) -> None: ...
    async def load_async(
        self, instrument_id: InstrumentId, filters: dict[str, Any] | None = None
    ) -> None: ...
```

Loads `GET /v1/market/slug/{slug}` per configured slug via `get_public` with
`quota_key="instruments"`, parses via `parse_binary_option`, calls `self.add(...)`.
`info` carries numeric market id, event slug/id, city, climate date, high/low,
strike bounds and `city_day_cluster_id` per `BUILD_PLAN:65`. Results are cached
in-process for the session — instrument metadata is static data (§8) and
re-fetching it per subscription is the fastest way to exhaust the read budget.
This is the **minimum** provider satisfying the base class's `PyCondition.type`
check at `live/data_client.py:361`; the full Phase 3 provider supersedes it.

### `websocket.py` (new)

```
SUBSCRIPTION_TYPE_MARKET_DATA: str = "SUBSCRIPTION_TYPE_MARKET_DATA"
WS_PATH: str = "/v1/ws/markets"

class PolymarketUSMarketsWebSocket:
    def __init__(
        self, *, ws_url: str, signer: Ed25519RequestSigner | None,
        handler: Callable[[bytes], None], loop: asyncio.AbstractEventLoop,
        heartbeat_secs: int, idle_timeout_secs: int, logger: Logger,
    ) -> None: ...
    async def connect(self) -> None: ...
    async def subscribe_market_data(self, market_slugs: Sequence[str]) -> None: ...
    async def unsubscribe(self, request_id: str) -> None: ...
    async def close(self) -> None: ...
    def _build_config(self) -> WebSocketConfig: ...      # fresh headers each call
    async def _supervise(self) -> None: ...              # Breezy-owned reconnect
    async def _replay_subscriptions(self) -> None: ...
```

- `signer` is `None` when smoke step E1 shows the markets WS is public; then
  `_build_config` passes `headers=[]` and native reconnect is left enabled
  (`reconnect_max_attempts=None`). Otherwise `_build_config` calls
  `signer.sign_headers("GET", WS_PATH)` — returning `list[tuple[str, str]]`,
  passed straight through — and `_supervise` owns reconnect per §5.3, with
  `reconnect_max_attempts=0` so the two mechanisms cannot race.
- Subscribe envelope from `sdk_snapshot/.../websocket/base.py:95-108`:
  `{"subscribe": {"requestId": ..., "subscriptionType": ...}}`, with
  `"marketSlugs"` added **only when the slug list is non-empty** — the SDK guards
  it with `if market_slugs:` (`:105-106`), and the key is absent otherwise.
  Unsubscribe: `{"unsubscribe": {"requestId": ...}}` (`:110-117`).
  Subscription type constants from `websocket/markets.py:20-24`.
- Live subscriptions in a `dict[str, str]` slug→requestId; `_replay_subscriptions`
  iterates it, exactly once per slug (`BUILD_PLAN:66` exit gate).
- `heartbeat` and `idle_timeout_ms` come from `WebSocketConfig`; no hand-rolled
  idle watchdog.

### `data.py` (new)

```
class PolymarketUSDataClient(LiveMarketDataClient):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: PolymarketUSInstrumentProvider,
        config: PolymarketUSDataClientConfig,
        *,
        http_client: PolymarketUSHttpClient,
        ws: PolymarketUSMarketsWebSocket,
    ) -> None:
        super().__init__(
            loop=loop, client_id=client_id, venue=venue, msgbus=msgbus,
            cache=cache, clock=clock, instrument_provider=instrument_provider,
            config=config,
        )
```

Revision 1's signature omitted `client_id` and `venue`, which the base class
requires positionally (`live/data_client.py:349-360`) and which
`PyCondition.type(instrument_provider, ...)` at `:361` sits immediately after.
**Derivation, made explicit** — the factory's `create` signature
(`live/factories.py:33`, precedent `adapters/databento/factories.py:120-127`)
carries `name: str` but no venue:

- `client_id = ClientId(name)`. `name` is the key under which the client is
  registered in `data_clients` and passed to `add_data_client_factory`
  (`live/node.py:230`; nautilus-trader-patterns §"Factory & TradingNode
  wiring"), so this keeps routing consistent by construction. Precedent:
  `adapters/databento/data.py:137` uses `ClientId(name or DATABENTO)`.
- `venue = symbology.POLYMARKET_US_VENUE`, a module constant. This adapter
  serves exactly one venue, so the venue is a property of the adapter, not of
  the runtime config. (Databento passes `venue=None` at `data.py:138` because it
  is multi-venue; that is the opposite case and must not be copied.)
- A Step 11 test pins both: that `client_id` equals the registered name and that
  `venue` equals `POLYMARKET_US_VENUE`, by constructing through the factory.

Methods: `_connect`, `_disconnect`, `_subscribe_quote_ticks`,
`_unsubscribe_quote_ticks`, `_handle_ws_message`. `_connect` loads instruments →
connects WS → subscribes. `_handle_ws_message` parses and calls
`self._handle_data(quote)`. Callbacks stay on the event-loop thread per the
Phase 1.7 contract (`TRADING_ENABLEMENT_PLAN.md:261`); anything that could reach
`require_open` is scheduled onto the loop, never called from a transport thread.
Do **not** override optional base methods merely to raise — the base already
does and `_on_task_completed` swallows it (nautilus-trader-patterns).

### `factories.py` (new)

```
class PolymarketUSLiveDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: PolymarketUSDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> PolymarketUSDataClient: ...
```

**The only place credentials are resolved.** Calls
`load_polymarket_us_credentials(config.secrets)`, selects the canonical builder
from `BUILDERS[config.signing_variant]`, builds signer → transport (with the §8
quotas) → HTTP client → provider → WS → data client, deriving `client_id` and
`venue` as above. Also reads the §7 endpoint variables and raises `SettingsError`
naming any that is unset. Mandated by `developer_guide/adapters.md:263-266`;
precedent `adapters/databento/factories.py:59`. No `LiveExecClientFactory` is
created.

### `scripts/venue/polymarket_us_auth_smoke.py` (new, outside `src/`)

One-shot operator entrypoint, outside `src/breezy/` and outside mypy `files`,
matching the `scripts/analysis/` precedent (`TRADING_ENABLEMENT_PLAN.md:585`).
See §10.

### Files modified

| File | Change |
|---|---|
| `pyproject.toml` | add `"src/breezy/adapters"` to `[tool.mypy].files`; add `pynacl` to the `polymarket-us` extra |
| `tests/conftest.py` | D2: three-factor unlock, `pytest_addoption("--venue-live")`, `_scrub_venue_credentials` autouse fixture |
| `src/breezy/adapters/polymarket_us/credentials.py` | add `secret_key_file_env_var` |
| `src/breezy/adapters/polymarket_us/__init__.py` | export new public names |
| `tests/unit/test_polymarket_us_phase0_safety.py` | widen the SDK import ban to prefix-match `polymarket_us.*` (barrier B5) |
| `tests/unit/test_polymarket_us_dependency_pin.py` | assert the `pynacl` pin |
| `docs/plans/TRADING_ENABLEMENT_PLAN.md` | errata for D1 + D3 |
| `docs/plans/archive/POLYMARKET_US_BUILD_PLAN.md` | errata for the `AsyncPolymarketUS` evidence claim (D4) |
| `.claude/skills/polymarket-us-integration/SKILL.md` | correct the unsourced "query string is INCLUDED" line (`:83`) |
| `docs/evidence/venue/polymarket_us/VENUE_FACTS_2026-08-25.md` | append: the canonical-string determination, the delimiter weakness (§5.1), the rate-limit surface question (§8), the WS-auth determination (§5.3) |

---

## 7. Environment variable contract (exact)

| Variable | Required | Secret | Consumer | Notes |
|---|---|---|---|---|
| `POLYMARKET_US_KEY_ID` | yes | credential-adjacent (UUID) | `env.load_polymarket_us_credentials` | Tripwired at `tests/conftest.py:48` |
| `POLYMARKET_US_SECRET_KEY_FILE` | one of these two | **yes** | same | **Preferred.** `0600`, owned by the running uid, regular file, POSIX-semantics filesystem. Tripwired at `:52` |
| `POLYMARKET_US_SECRET_KEY` | one of these two | **yes** | same | Discouraged; warns. Tripwired at `:51`. Both set → error |
| `POLYMARKET_US_API_BASE` | yes | no | `factories` | e.g. `https://api.polymarket.us`. **Not** tripwired |
| `POLYMARKET_US_GATEWAY_BASE` | yes | no | `factories` | e.g. `https://gateway.polymarket.us` |
| `POLYMARKET_US_WS_URL` | yes | no | `factories` | e.g. `wss://api.polymarket.us` (path `/v1/ws/markets` appended) |
| `POLYMARKET_US_MARKET_SLUGS` | yes | no | `factories` | Comma-separated. No default — G1 unresolved |
| `POLYMARKET_US_USER_AGENT` | yes | no | `factories` | G15 attribution. Adapter-owned; **never** read `BREEZY_USER_AGENT` |
| `BREEZY_VENUE_LIVE` | for live tests / smoke | no | `tests/conftest.py`, smoke | Must be `1`. **Not sufficient alone** (D2) |
| `BREEZY_ALLOW_CREDENTIALED_PYTEST` | for live tests | no | `tests/conftest.py` | Must be `1`. **Not sufficient alone** (D2) |
| `--venue-live` (CLI flag) | for live tests | n/a | `tests/conftest.py` | Cannot be supplied by a leaked env var (D2) |

Every one is **required with no default**; the factory raises `SettingsError`
naming the variable when unset (`TRADING_ENABLEMENT_FINDINGS.md:254-256`).
Withdrawn: the five `BREEZY_VENUE_*` names at
`TRADING_ENABLEMENT_PLAN.md:615-617` — see D1.

---

## 8. Rate-limit budget and data flow

### 8.1 Which rate-limit surface governs

Two rate-limit snapshots exist and they describe **different API surfaces**.
Conflating them is the trap the polymarket-us skill's banner exists to prevent.

- **Retail (Stack A) — the surface Breezy uses.**
  `docs_snapshots/api-reference_rate-limits_2026-08-25.md:9,15,19-20`:
  *"Rate limits are enforced per API key"*; *"The Retail API enforces a global
  rate limit of **20 requests per second** per API key across all endpoints"*;
  table rows *"Global (all authenticated endpoints) | 20 requests per second per
  API key"* and *"Public (unauthenticated) | 20 requests per second per IP"*.
  Also `:31-51`: on 429, wait ≥1s then exponential backoff; and the 5-second
  order stopgap that reports `Global Rate Limit Exceeded` **without** being a
  rate limit — pure cancels exempt.
- **Institutional DMA (Stack B) — not our surface.**
  `docs_snapshots/trader-guide_rate-limits_2026-08-25.md:11,15,21-30`: limits
  *"per participant firm"*; a firm-wide **100 req/s** REST cap averaged over a
  minute; and per-endpoint minute windows — `ListInstruments` 6/min,
  `ListSymbols` 6/min, `GetOrderBook` 12/min, `GetBBO` 12/min,
  `SearchOrders`/`SearchExecutions`/`SearchTrades` 12/min, `GetTradeStats`
  60/min. This is the `api.prod.polymarketexchange.com` surface reached via
  Auth0/JWT, gRPC and FIX. **Retail never reaches Stack B**
  (`VENUE_FACTS_2026-08-25.md` Q10; polymarket-us skill §"API Stacks").

**Governing limit: 20 req/s per API key (authenticated) and per IP (public).**

**But the institutional per-endpoint caps are adopted prudentially.** They are
the venue's own statement that `ListInstruments`-class and `GetOrderBook`-class
reads are expensive and should be *cached client-side* and *streamed rather than
polled*. Nothing in the retail docs contradicts that, the retail surface is
younger, and being wrong costs us a 429 on the exact endpoint we need at
startup. Budgeting to the tighter number is free here: this slice makes a
handful of startup reads and then streams.

**Recorded as an open question**, appended to `VENUE_FACTS`: whether the retail
surface silently applies per-endpoint minute windows in addition to the
documented global 20/s. The smoke test measures it — see §10 step G.

### 8.2 Quota design

Revision 1 specified a flat `default_quota` of 10 req/s and nothing else. Even
under the correct retail limit that is structurally wrong for the prudential
budget above: loading 20 slugs at 10/s issues 20 `ListInstruments`-class reads
inside two seconds, blowing a 6/min window immediately. **Per-endpoint
`keyed_quotas` are required, not a flat default.**

`nautilus_pyo3.HttpClient.__init__` takes
`keyed_quotas: list[tuple[str, Quota]]` and `default_quota: Quota`
(`core/nautilus_pyo3.pyi:5417-5425`); `Quota` provides `rate_per_second` and
`rate_per_minute` classmethods (`:5520-5527`); and `get(...)` selects a keyed
quota via `keys: list[str]` (`:5441-5448`). Every call site therefore passes an
explicit `quota_key`, which is why it is a **required keyword argument** on
`PolymarketUSHttpClient.get_authenticated` / `get_public` — an unkeyed call is a
type error, not a silently-unthrottled request.

| `quota_key` | Endpoints | Quota | Source |
|---|---|---|---|
| `"instruments"` | `/v1/market/slug/{slug}`, `/v1/markets` | `Quota.rate_per_minute(6)` | Prudential (trader-guide `ListInstruments`) |
| `"book"` | `/v1/markets/{slug}/book`, `/bbo` | `Quota.rate_per_minute(12)` | Prudential (`GetOrderBook`/`GetBBO`) |
| `"portfolio"` | `/v1/portfolio/*` | `Quota.rate_per_minute(12)` | Prudential (`SearchOrders`-class) |
| `"default"` | everything else | `Quota.rate_per_second(15)` | Retail 20/s, with 25% headroom |

Consequences designed in: the instrument provider **caches for the session**
(§6) rather than re-reading per subscription; book state comes from the
**WebSocket stream**, not polling — which is what "Prefer streaming for
real-time data" says and what §5.3 makes reliable. A Step 5 test asserts each
public method passes a `quota_key` present in the table, so adding an endpoint
without a budget fails CI.

### 8.3 Flow

**Startup (in the factory, on the node's event loop):**

```
env (POLYMARKET_US_*)
  -> load_polymarket_us_credentials()   -> PolymarketUSCredentials(SecureString, SecureString)
  -> Ed25519RequestSigner(credentials, clock=LiveClock,
                          canonicalize=BUILDERS[config.signing_variant])
  -> NautilusHttpTransport(default_quota=Quota.rate_per_second(15),
                           keyed_quotas=[...§8.2...],
                           header_keys=OBSERVED_RESPONSE_HEADERS,
                           default_headers={"User-Agent": ...})
  -> PolymarketUSHttpClient(transport, signer, api_base, gateway_base)
  -> PolymarketUSInstrumentProvider(client, venue, market_slugs)
  -> PolymarketUSMarketsWebSocket(ws_url, signer_or_None, handler, loop)
  -> PolymarketUSDataClient(loop, ClientId(name), POLYMARKET_US_VENUE, ...)
     [registered via node.add_data_client_factory(name, PolymarketUSLiveDataClientFactory)]
```

**Authenticated read:**

```
caller -> get_authenticated(path, query=..., quota_key="portfolio")
  -> query_string = _build_query_string(query)              # ONE value
  -> ts = clock.timestamp_ms(); signer.assert_within_window(ts)
  -> header_pairs = signer.sign_headers("GET", path, query_string=qs, timestamp_ms=ts)
  -> _dispatch("GET", api_base, ...)                        # assert GET  (B1)
  -> transport.get(url, headers=dict(header_pairs), quota_key=...)   # pyo3 wants a dict
  -> status mapped in errors.py; 2xx body -> decode -> Mapping[str, Any]
```

**Public read:** identical minus signing; `base_url = gateway_base`; `403` →
`GatewayForbiddenError`, loud, no fallback (§5.2).

**Quote path:**

```
venue WS frame
  -> PolymarketUSMarketsWebSocket handler (event loop)
  -> PolymarketUSDataClient._handle_ws_message
  -> parsing.parse_quote_tick (Decimal / Price.from_str)
  -> self._handle_data(QuoteTick)
  -> Nautilus DataEngine -> MessageBus -> subscribed Actor/Strategy
```

**Reconnect:** public WS → native reconnect + `post_reconnection` replay.
Authenticated WS → `_supervise` detects `is_closed()`, rebuilds
`WebSocketConfig` with **freshly signed** headers, reconnects, replays each live
subscription exactly once per slug (§5.3).

---

## 9. Build order — numbered TDD steps, RED test first

Each step: write the named test, watch it FAIL, then implement. Keep the
RED→GREEN output as the change artifact. Every test runs under the **default**
kill-switched suite unless marked otherwise.

**Step 1 — Housekeeping, mypy registration, doc errata.**
RED: `tests/unit/test_polymarket_us_packaging.py::test_adapters_package_is_type_checked`
(parses `pyproject.toml`, asserts `"src/breezy/adapters"` ∈ `[tool.mypy].files`);
`::test_pynacl_is_pinned_in_the_polymarket_us_extra`.
GREEN: `pyproject.toml`. Also land the D1/D3/D4 errata and the `SKILL.md:83`
correction (docs, no test).

**Step 2 — Redaction and error taxonomy (SEC-3).**
RED: `tests/unit/test_polymarket_us_redaction.py::` —
`test_redact_headers_masks_access_key_signature_and_timestamp`,
`test_redact_text_masks_every_supplied_secret`,
`test_redact_url_strips_query_values`.
`tests/unit/test_polymarket_us_errors.py::test_venue_error_str_never_contains_header_values`.
GREEN: `redaction.py`, `errors.py`.

**Step 3 — Credential loading (SEC-3, TOCTOU).**
RED: `tests/unit/test_polymarket_us_env.py::` —
`test_missing_key_id_raises_naming_only_the_variable`,
`test_key_file_with_group_readable_mode_is_rejected` (`0o640` → error naming the
octal mode),
`test_key_file_with_0600_mode_loads_into_secure_string`,
`test_symlinked_key_file_is_rejected_by_o_nofollow` (symlink → `0600` target;
assert `CredentialSourceError`, not a successful read),
`test_symlink_swapped_between_stat_and_read_cannot_be_observed` (asserts the
implementation opens **once** and `fstat`s the descriptor — no second path
resolution),
`test_key_file_owned_by_another_uid_is_rejected` (skipped unless the runner can
create such a file; asserts the uid check exists via a stubbed `os.fstat`),
`test_both_secret_sources_set_is_rejected_as_ambiguous`,
`test_malformed_base64_secret_is_rejected_without_echoing_the_value`,
`test_secret_absent_from_str_and_from_formatted_traceback` (property test:
generated secret is absent from `str(exc)` **and** `traceback.format_exc()` —
SEC-3 "unscrubbed tracebacks"),
`test_no_committed_fixture_contains_an_ed25519_private_key` — see below.
GREEN: `env.py`, `credentials.py` field.

*Detection algorithm for the fixture scan* (revision 1 left it unimplementable).
Concretely: walk `tests/`, `docs/evidence/`, `scripts/` for files ≤1 MiB; for
each, regex every token matching `[A-Za-z0-9+/]{43,88}={0,2}`; for each token,
attempt `base64.b64decode(token, validate=True)`; **flag** when the decoded
length is exactly 32 or 64 bytes **and** the decoded bytes have Shannon entropy
≥ 7.0 bits/byte (random key material; excludes padded ASCII, repeated bytes,
and text that happens to be base64-shaped). Flagged tokens fail the test unless
the token is listed in a module-level `ALLOWED_TEST_VECTORS: frozenset[str]`
carrying at most the one public-key vector named in Step 4. Private keys are
never listed; the allow-list exists so the scan can coexist with a committed
*public* verification vector.

**Step 4 — Signing (mandatory hard gate).**
RED: `tests/unit/test_polymarket_us_signing.py::` —
`test_matches_the_sdk_reference_implementation_for_generated_keys` — the
**differential oracle**. Revision 1 specified an in-test-generated key *and* a
pinned literal signature, which cannot both hold, and a committed deterministic
seed is exactly what Step 3's scan must fail on. Instead: generate an ephemeral
Ed25519 key in-process, then for a hypothesis-generated matrix of
(timestamp, method="GET", path) assert
`dict(signer.sign_headers(...)) == polymarket_us.auth.create_auth_headers(key_id, secret_b64, method, path)`
modulo the injected timestamp. The SDK is already a pinned dependency
(`pyproject.toml:30`, `polymarket-us==0.1.2`), so the oracle is version-locked.
This test file is the **only** place barrier B5 permits importing
`polymarket_us.auth`; it is `@pytest.mark.skipif` when the extra is absent, and
a companion test asserts the extra is installed in CI so the skip cannot hide a
silent loss of the oracle.
Plus: `test_canonical_string_is_timestamp_method_path_concatenation`,
`test_default_builder_excludes_the_query_string` (the flipped default),
`test_alternate_builder_includes_the_query_string`,
`test_trailing_slash_is_preserved`,
`test_body_is_ignored_by_both_builders_for_a_get` (G3 inertness),
`test_timestamp_within_29s_is_accepted`,
`test_timestamp_at_31s_raises_clock_skew` (with ±30s boundary cases),
`test_non_get_method_raises_method_not_permitted`,
`test_sign_headers_returns_a_list_of_pairs_not_a_dict` (pyo3 boundary, item 4),
`test_signer_repr_is_redacted`,
`test_signature_is_over_utf8_bytes`.
GREEN: `signing.py`.

**Step 5 — Transport and HTTP client.**
RED: `tests/unit/test_polymarket_us_transport.py::` —
`test_transport_does_not_expose_the_http_client_as_an_attribute` (barrier B3:
asserts no attribute of `NautilusHttpTransport` is an `HttpClient`),
`test_transport_round_trips_against_a_loopback_server` — a real `http.server`
on `127.0.0.1` under `@pytest.mark.allow_socket` (`tests/conftest.py:14-15`),
asserting that `header_keys` actually surfaces `Retry-After` and that a
`Quota.rate_per_minute(6)` key delays the 7th call. Without this,
`keyed_quotas`/`header_keys`/`default_quota` are exercised only live and never
in CI. The autouse pyo3 constructor block (`tests/conftest.py:217-218`) is
bypassed for this test via the same `allow_socket` opt-out path.
`tests/unit/test_polymarket_us_http.py::` —
`test_get_authenticated_emits_the_three_x_pm_headers` (recording fake transport;
asserts header **names** and a non-empty base64 signature, and that the captured
log is redacted),
`test_signed_canonical_and_dispatched_url_share_one_query_string`,
`test_query_params_are_sorted_and_percent_encoded_deterministically`,
`test_only_get_reaches_the_transport` (`_dispatch("POST", ...)` →
`MethodNotPermittedError`),
`test_public_get_sends_no_auth_headers`,
`test_gateway_403_raises_gateway_forbidden_and_does_not_fall_back`,
`test_429_maps_to_rate_limit_error_carrying_retry_after`,
`test_401_maps_to_venue_auth_error_without_leaking_headers`,
`test_every_public_method_passes_a_known_quota_key` (§8.2),
`test_request_log_contains_no_secret_material` (SEC-3: no
`X-PM-Access-Key`/`X-PM-Signature` values in emitted records; the adapter never
sets any logger to DEBUG).
GREEN: `transport.py`, `http.py`.

**Step 6 — Symbology.**
RED: `tests/unit/test_polymarket_us_symbology.py::` —
`test_slug_round_trips_through_instrument_id` (hypothesis, over observed
grammar e.g. `tc-temp-nychigh-2026-08-25-lt79f`),
`test_dotted_slug_is_rejected`, `test_separator_bearing_slug_is_rejected`,
`test_adapter_never_imports_the_bundled_polymarket_symbol_module`.
GREEN: `symbology.py`.

**Step 7 — Parsing.**
RED: `tests/unit/test_polymarket_us_parsing.py::` —
`test_book_top_parses_to_decimal_not_float`,
`test_module_contains_no_float_call`,
`test_quote_tick_uses_per_market_tick_size_for_precision`,
`test_market_metadata_missing_tick_size_raises_rather_than_defaulting`,
`test_precision_is_validated_before_price_construction` (SIGABRT guard),
`test_camel_case_keys_are_pinned` (fixture from
`docs/evidence/venue/polymarket_us/raw/`).
GREEN: `parsing.py`.

**Step 8 — Config.**
RED: `tests/unit/test_polymarket_us_config.py::` —
`test_config_raises_settings_error_naming_each_unset_field`,
`test_signing_variant_rejects_an_unknown_string`,
`test_config_carries_no_secret_bearing_field`,
`test_config_json_round_trip_contains_only_env_var_names`,
`test_tokenize_config_succeeds_and_contains_no_secret`.
GREEN: `config.py`.

**Step 9 — Instrument provider.**
RED: `tests/unit/test_polymarket_us_instruments.py::` —
`test_load_ids_async_produces_binary_options_from_a_captured_payload`,
`test_instrument_info_carries_city_day_cluster_id`,
`test_repeated_load_of_the_same_slug_issues_one_request` (§8.2 caching),
`test_provider_uses_only_get_requests_with_the_instruments_quota_key`.
GREEN: `instruments.py`.

**Step 10 — WebSocket, loopback.**
RED: `tests/unit/test_polymarket_us_websocket.py::` (loopback WS under
`@pytest.mark.allow_socket`) —
`test_subscribe_envelope_matches_the_sdk_schema`,
`test_subscribe_omits_market_slugs_key_when_the_list_is_empty` (the SDK's
`if market_slugs:` guard at `websocket/base.py:105-106`),
`test_config_headers_are_a_list_of_pairs` (pyo3 boundary),
`test_supervisor_reconnect_rebuilds_config_with_a_fresh_timestamp` (§5.3: force
a close, assert the second `WebSocketConfig` carries a strictly later
`X-PM-Timestamp`),
`test_native_reconnect_is_disabled_when_auth_is_required`
(`reconnect_max_attempts == 0`),
`test_public_mode_leaves_native_reconnect_enabled_and_sends_no_headers`,
`test_resubscribes_exactly_once_per_slug_after_reconnect`,
`test_websocket_config_sets_heartbeat_and_idle_timeout`.
GREEN: `websocket.py`.

**Step 11 — Data client.**
RED: `tests/unit/test_polymarket_us_data.py::` —
`test_client_id_equals_the_registered_factory_name`,
`test_venue_equals_the_polymarket_us_venue_constant`,
`test_base_class_accepts_the_instrument_provider` (constructs through the
factory; the base's `PyCondition.type` at `live/data_client.py:361` must pass),
`test_connect_loads_instruments_then_connects_then_subscribes`,
`test_ws_market_data_frame_reaches_handle_data_as_a_quote_tick`,
`test_no_optional_base_method_is_overridden_only_to_raise`,
`test_callbacks_run_on_the_event_loop_thread` (Phase 1.7 contract).
GREEN: `data.py`.

**Step 12 — Factory and node wiring.**
RED: `tests/unit/test_polymarket_us_factories.py::` —
`test_factory_resolves_credentials_and_config_never_does`,
`test_factory_raises_settings_error_when_an_endpoint_variable_is_unset`,
`test_factory_selects_the_builder_named_by_signing_variant`,
`test_recording_node_calls_add_data_client_factory_before_build`,
`test_no_exec_client_factory_is_registered`.
GREEN: `factories.py`.

**Step 13 — Non-goal guards (a guard suite, not a TDD step).**
This step writes tests only; there is no implementation to make them pass,
because Steps 1–12 already satisfy them. Its purpose is to fail **later**, when
someone adds an order path outside this plan. Labelling it a TDD step was a
category error in revision 1.
`tests/unit/test_polymarket_us_readonly_guard.py::` —
`test_no_write_method_literal_anywhere_in_src_or_scripts` (B4, repo-wide),
`test_no_http_client_write_attribute_access` (B4, `ast.Attribute` on an
`HttpClient`-bound name),
`test_sdk_signing_module_is_imported_only_by_the_named_oracle_test` (B5,
prefix-matching `polymarket_us.*`),
`test_adapter_package_defines_no_live_execution_client`,
`test_safety_chokepoint_has_no_caller_in_this_slice` (B6),
`test_get_value_never_appears_inside_an_assert_statement` — repo-wide AST scan
for a `Call` to `.get_value()` anywhere within an `ast.Assert` node. pytest
rewrites assertions to print operand values on failure, so
`assert creds.secret_key.get_value() == expected` would dump the cleartext
secret into CI logs. Comparisons must go through a hash or `get_redacted()`.

**Step 14 — Live tests, gated.**
`tests/live/venue/test_polymarket_us_readonly_live.py`, every test
`@pytest.mark.venue_live` (deselected by default; requires all three D2 unlocks):
`test_authenticated_get_is_accepted_by_the_venue`,
`test_query_bearing_get_signed_without_the_query_is_accepted` (confirms the
flipped default),
`test_query_bearing_get_signed_with_the_query_is_rejected` (the disproof; if it
is *accepted*, both forms work and the finding is recorded, not failed),
`test_gateway_public_get_is_reachable_from_this_host` (G15),
`test_markets_websocket_accepts_an_unauthenticated_connect` (§5.3(a)),
`test_markets_websocket_delivers_at_least_one_quote_for_a_configured_slug`.
Assertions are on status codes, counts and header **names** — never on bodies
that could carry account data.

**Step 15 — Smoke script and evidence.** §10.

**Step 16 — Gates and review.** Default `pytest`, `ruff`, `mypy` (now covering
`src/breezy/adapters`), plus the OS-namespace run
`unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1 .venv/bin/python -m pytest`
(`tests/conftest.py:68-71`; `BUILD_PLAN:105-109`). Then independent review:
security-reviewer (credentials + signing), python-reviewer, prediction-market
reviewer (`TRADING_ENABLEMENT_PLAN.md` item 2.8).

---

## 10. Smoke test: procedure and evidence

`scripts/venue/polymarket_us_auth_smoke.py` — one-shot, GET-only.

**Preconditions (operator, credentialed host):** all §7 variables set;
`BREEZY_VENUE_LIVE=1`; key file `0600`, owned by the running uid, on a
POSIX-semantics filesystem; `polymarket-us` extra installed. The script refuses
to run if any is unmet.

**First action, before any credential is read: disable core dumps.**
`resource.setrlimit(resource.RLIMIT_CORE, (0, 0))`. Rationale under S15.

| Step | Action | Proves |
|---|---|---|
| A | `GET {gateway}/v1/market/slug/{slug}` unauthenticated | G15 branch; gateway reachable headless |
| B | `GET {api}/v1/portfolio/positions` authenticated, no query | Ed25519 signing accepted end-to-end |
| C | `GET {api}/…?a=1&b=2` signed **without** the query (default), then the same request signed **with** it | The canonical-string determination (§5.1) |
| D | Sign with `timestamp_ms = now - 120_000` | The ±30s window is real, not assumed |
| E1 | Connect `/v1/ws/markets` with **no** auth headers | Whether the markets WS is public (§5.3(a)) |
| E2 | Connect with auth headers; subscribe; run 120s | Real quotes arrive |
| F | Repeat E2 inside a minimal `TradingNode` with the factory registered | Quotes land in the **Nautilus `DataEngine`**, not merely our parser |
| G | Burst 8 `instruments`-key reads inside 60s, then 14 `book`-key reads | Whether retail enforces per-endpoint minute windows (§8.1 open question) |

**Evidence** → `docs/evidence/venue/polymarket_us/READONLY_AUTH_SMOKE_<UTC-date>.md`
plus a `SHA256SUMS` sidecar, matching
`docs/evidence/venue/polymarket_us/SHA256SUMS_2026-08-25.txt`:

- UTC start/end; host clock offset vs the venue's `Date` response header (the
  operational NTP check `BUILD_PLAN:85` asks for); `RLIMIT_CORE` as set.
- Key-file `st_dev` and filesystem type (the §6 residual assumption).
- Per request: method, path, query string, status, latency ms, and the header
  **names** sent — `X-PM-Access-Key`, `X-PM-Timestamp`, `X-PM-Signature` — with
  **all three values `<redacted>`**. Per SEC-4
  (`TRADING_ENABLEMENT_REVIEW.md:115-116`), `X-PM-Access-Key` is redacted too,
  not only the signature.
- Rate-limit headers observed; step G's 429s (if any) with their `Retry-After`.
- Step D's rejection status and venue message (redacted).
- Step E1's outcome — the WS-auth determination.
- Instrument ids loaded, WS frames received, `QuoteTick`s delivered, per-slug
  counts, and a timestamped log excerpt — behaviour asserted, not structure
  (`TRADING_ENABLEMENT_PLAN.md:353-355`; the R10 "green tests, dead deployment"
  lesson).
- An explicit `POSTs issued: 0`, counted from the client's own request log.
- Determinations appended to `VENUE_FACTS` as dated amendments.

A pre-commit check on the evidence file runs the Step 3 detection algorithm and
fails the run rather than committing a leak.

---

## 11. Security controls

| ID | Control | Where |
|---|---|---|
| S1 | No secret in any `NautilusConfig`; config carries env-var **names** only | `credentials.py:22-31`, `config.py`; `assert_config_type_excludes_secrets` at import; Step 8 |
| S2 | Runtime material only in `SecureString`; `SigningKey` built per call and dropped | `env.py`, `signing.py` |
| S3 | Credentials resolved **only** in the factory | `factories.py`; `developer_guide/adapters.md:263-266` |
| S4 (SEC-3) | Key file: `O_NOFOLLOW` open then `fstat` — regular file, mode exactly `0600`, `st_uid` = running uid. No stat-then-read race | `env.py`; Step 3 |
| S5 (SEC-3) | **No httpx DEBUG header logging.** The authenticated path uses `nautilus_pyo3.HttpClient`, not `httpx`, so httpx's DEBUG header logger is not in the path at all. A test asserts the adapter never sets any logger to DEBUG; the smoke script refuses to run under `BREEZY_LOG_LEVEL=TRACE/DEBUG` | `http.py`, smoke; Step 5 |
| S6 (SEC-3) | **Scrubbed tracebacks.** Secret material is never an argument to a function that can appear in a frame with a raw value: `env.py` validates shape then wraps immediately; `signing.py` takes `PolymarketUSCredentials`, never a `str`. Asserted against `traceback.format_exc()` | `env.py`, `signing.py`; Step 3 |
| S7 (SEC-3) | **No fixture loads a real key.** Every test generates an ephemeral key in-process; the Step 3 scan (entropy + decoded-length algorithm) fails on any committed private key. Step 4's oracle is differential, so no signature literal is committed | Steps 3, 4 |
| S8 (SEC-4) | Evidence redacts `X-PM-Access-Key`, `X-PM-Signature` **and** `X-PM-Timestamp`; pre-commit scan over the evidence file | §10 |
| S9 | Credential tripwire retained; exemption requires **three** independent factors, no one of which both silences the abort and unlocks execution; plus the autouse scrub | D2 |
| S10 | Network kill-switch and pyo3 constructor block untouched; the OS-namespace run remains the documented closure of the residual gap | `tests/conftest.py:61-71`; `BUILD_PLAN:105-109` |
| S11 | GET-only across ordinary adapter/script paths: six layered barriers B1–B6, two of them repo-wide, with B3 specifically pinned against attribute and `__self__` receiver exposure | §2.1 |
| S12 | Per-endpoint `keyed_quotas` with a required `quota_key` at every call site | §8.2 |
| S13 | Local clock-skew assertion before every signature | `signing.py` |
| S14 | Adapter owns its User-Agent; never reads `BREEZY_USER_AGENT` | `factories.py` |
| S15 | **Core dumps disabled.** `TRADING_ENABLEMENT_REVIEW.md:110-111` names core dumps an open channel. `SecureString` does not close it: `common/secure.py:50-52` stores the plaintext in `self._value`, an **immutable `str`**, alongside a `bytearray` mirror; `clear()` (`:103-120`) overwrites only the bytearray and then **rebinds** `self._value = ""`. Rebinding cannot scrub the original `str` object — its backing memory survives until GC and can page to swap or land in a crash dump. Remedy: `resource.setrlimit(RLIMIT_CORE, (0, 0))` as the first action of the smoke script and the live-test runner, before any credential is read; and `ulimit -c 0` (shell) / `LimitCORE=0` (systemd unit) documented as a **hard operator precondition** in the runbook. This mitigates, it does not eliminate: swap remains a residual risk, addressed operationally by an encrypted-swap or `swapoff` requirement in the runbook | Smoke script, live runner, runbook |
| S16 | `.get_value()` banned inside `assert` statements — pytest assertion rewriting would print cleartext into CI logs | Step 13 |

---

## 12. Risks and open questions

| # | Risk | Mitigation |
|---|---|---|
| R-A | The canonical string excludes the query but the venue includes it (or vice versa) | Default now matches docs **and** SDK (§5.1); both builders ship and are unit-tested; smoke step C measures; one enum value switches it |
| R-B | G3 body-signing resolved differently later | Inert here (GET-only); `CanonicalRequest.body` seam present and tested as ignored |
| R-C | G15 regresses (gateway 403 headless) | Typed `GatewayForbiddenError`, loud, no silent re-route; smoke records status + UA |
| R-D | Host clock drift silently breaks auth mid-session | S13 local pre-check; smoke step D; venue `Date`-header offset recorded |
| R-E | **WS reconnect replays a stale timestamp and the venue rejects the handshake** | The revision-1 defect. Closed by §5.3: measure whether auth is needed at all (E1); if it is, Breezy owns reconnect and rebuilds the config with fresh headers, with native reconnect disabled so they cannot race |
| R-F | Duplicate subscriptions after reconnect double-count quotes | Exactly-once resubscribe test (Step 10); `BUILD_PLAN:66` gate |
| R-G | G6: no sequence numbers → silent gap | `idle_timeout_ms` + staleness bound; the strategy refuses stale books in Phase 5. Not resolved here |
| R-H | `Price`/`Quantity` precision violation SIGABRTs | Pre-validate before construction (Step 7) |
| R-I | A future contributor adds an order path | B4 + B5 are repo-wide, not package-local (§2.1) |
| R-J | G1: a renamed slug silently stops resolving | Slugs are required operator input; a dead slug raises `VenueStatusError` at instrument load — a startup failure, not a silent gap |
| R-K | `polymarket-us` extra absent in production → `nacl` import error at signer construction | `pynacl` becomes a direct member of the extra; dependency-pin test asserts it |
| R-L | **`AsyncPolymarketUS` may not exist in 0.1.2** (D4), so `BUILD_PLAN:41-42`'s transport premise may be unsupported | This slice does not depend on it — the authenticated path is native `HttpClient`. Recorded as an errata; the SDK is used only as schema and differential oracle |
| R-M | Retail may silently enforce per-endpoint minute windows beyond the documented 20/s (§8.1) | Budgeted to the tighter prudential numbers already; smoke step G measures; finding appended to `VENUE_FACTS` |
| R-N | Secret material survives in memory and reaches a crash dump or swap | S15: core dumps disabled in-process and by operator precondition; swap handled operationally. Not fully eliminable given `SecureString`'s immutable-`str` backing |

**Open questions this slice does NOT answer** (carried forward unchanged):
G2, G4, G5, G7, G8, G9, G10, G11 per `TRADING_ENABLEMENT_FINDINGS.md:212-249`,
and `BUILD_PLAN:73-85`'s question table. None block a GET-only, order-free read
path.

---

## 13. Review response: one correction not adopted

**Reviewer finding:** *"The '20 req/s per key' rate limit does NOT exist in the
venue docs; the actual documented limits are 100 req/s firm-wide plus
per-endpoint minute windows (`trader-guide_rate-limits_2026-08-25.md:15,21-30`).
Delete the 20 req/s claim everywhere."*

**Not adopted, on evidence.** Both documents exist and describe **different API
surfaces**:

- `docs_snapshots/api-reference_rate-limits_2026-08-25.md:15` — *"The **Retail
  API** enforces a global rate limit of **20 requests per second** per API
  key across all endpoints"*, with `:19-20` tabulating 20/s authenticated per
  key and 20/s public per IP, and `:9` stating limits are *"enforced per API
  key"*.
- `docs_snapshots/trader-guide_rate-limits_2026-08-25.md:11,15,21-30` — the
  **Trader Guide**, i.e. institutional DMA. Limits are *"per participant
  firm"*; the surface is `api.prod.polymarketexchange.com` with Auth0 JWT,
  gRPC and FIX.

Breezy is on **retail** by operator decision (`BUILD_PLAN:18`: *"use the
Polymarket.us retail API, not institutional DMA"*), and *"Retail never reaches
Stack B"* (polymarket-us skill §"API Stacks"; `VENUE_FACTS` Q10). The 20 req/s
figure was correctly sourced; deleting it would have installed the wrong
venue's limits — precisely the `.us`/`.com`-class surface confusion the skill's
banner warns about.

**The reviewer's design critique is adopted in full**, and it was correct
independently of which number governs: a flat `default_quota` was structurally
wrong, and §8.2 now uses per-endpoint `keyed_quotas` with a required
`quota_key`. The institutional per-endpoint caps are adopted **prudentially**
(§8.1) because they are the venue's own signal that these reads are expensive,
and the residual ambiguity is recorded as R-M and measured at smoke step G.

All other findings from all three reviews are adopted; the material ones are
marked in place at §2.1 (barrier independence), §5.1 (withdrawn "query
included" claim, flipped default), §5.2 (dropped `GATEWAY_FALLBACKS`), §5.3 (WS
reconnect), §6 (`transport.py`/`redaction.py` split, TOCTOU, typed signatures,
`SigningVariant` enum, subscribe-envelope conditional), §8 (quota redesign),
D1 (withdrawn `:580` argument), D2 (three-factor unlock), D4 (re-grounded
evidence, `AsyncPolymarketUS` erratum), Step 3 (detection algorithm), Step 4
(differential oracle), Step 5 (loopback transport test), Step 13 (relabelled a
guard suite; `.get_value()` assert ban), and S15 (core dumps).
