# Grok — R-6.5b pre-implementation measurements (2026-09-03)

Verbatim Grok output (`--always-approve`, scratchpad-only writes, `git status` empty at the end),
tree `4e43886`. Measures plan §3 D2/D6/D7 and §6 against the real barrier source and pyo3 `.pyi`.
Open plan decision surfaced: D1 (share the read `HttpClient`/`Quota`) requires injecting a
prebuilt client into the GET-only wrapper, i.e. a `transport.py` constructor change; the plan lists
`PolymarketUSReadTransport`/`_build_get_only_callable` as must-not-change. Resolve in Rev 7:
either inject (a non-write constructor change, exemption-free) or accept a second client with its
own bucket. Implementation is gated on the operator R-6.5P positive control (AUTH_OK).

---


From `.venv/.../nautilus_pyo3.pyi:5416-5518` (no `HttpClient.put`, no `http_put`):

| Surface | Signature | Instance quota `keys=` |
|---|---|---|
| `HttpClient.request` | `(method: HttpMethod, url, params=None, headers=None, body=None, keys=None, timeout_secs=None)` | yes |
| `HttpClient.post` | `(url, params=None, headers=None, body=None, keys=None, timeout_secs=None)` | yes |
| `HttpClient.patch` / `.delete` | same family; delete has no `body` | yes |
| `http_post` / `http_patch` / `http_delete` | `(url, params=None, headers=None, body=None, timeout_secs=None)` | **no** |

GET path today: `transport.py:343` `await self._get(url, headers=dict(headers), keys=[quota_key])` → `HttpClient.get` (`:5436-5443`). Constructor quota: `:317-323`. Probe already uses `write_client.post(..., headers=, body=, keys=)` (`polymarket_us_write_signing_probe.py:396-401`).

**Recommend `client.post(url, headers=..., keys=[quota_key])`** (no `params`, no `body`, no per-call timeout). (a) same instance + `Quota` as GET. (b) one attribute-name B4 hit: V3 `.post` (`_WRITE_ATTRS` `:167`). `client.request(HttpMethod.POST)` is also V3 (`.request`) but adds `HttpMethod` to D2 and a generic verb. `http_post` is V5 and **cannot** share the bucket.

## 2. Throwaway builder (scratchpad only)

Virtual path `src/breezy/adapters/polymarket_us/write_transport.py`.

**Raw:**
```
is_venue_touching(virtual C1 path): True
is_venue_touching(scratch real path): True   # C6: nautilus_pyo3/HttpError names

B4:
  write_transport.py:10: [V2] order-path literal '/v1/orders/open/cancel'
  write_transport.py:37: [V1] write-method literal 'POST'
  write_transport.py:19: [V3] write-capable attribute .post
rules: V1, V2, V3   (no V4/V5)

B3 wrapped (post-only callable, twin of _build_get_only_callable:129): []
B3 leaky (stores client): <object>:0: [B3] _client exposes write-capable receiver directly
```

C-class: C1 on the real path; C6 even without C1. **B3 live tests do not reach a write object** — only `NautilusHttpTransport` (`test_polymarket_us_readonly_guard.py:1054-1073`) and a `LeakyTransport` fixture (`:1076-1087`). No parametrization. A `PolymarketUSWriteTransport` instance is **not** inspected until a new test is added.

Exemption must cover **V1+V2+V3 in this file**. Keep the POST literal and `/v1/orders/...` **inside** the exempted module — if they move to `factories.py`, V1/V2 fire there with no exemption. D2 AST members on the throwaway: `{HttpError, HttpTimeoutError}` (no `Quota`/`HttpClient` ctor if client is injected). Exclude `SocketClient`/`WebSocketClient`.

## 3. B6/B7 shape (D3)

`BARRED_CALLEES` `:497-501` is a deny map; `find_barred_callers` is `(path, source)` only (`:1339-1351` pins no exemption arg). Throwaway callers: `[]`.

| Piece | Row |
|---|---|
| Ban map | `"_build_post_only_callable": "D3"` (mints the write callable; parent D3) |
| One-caller pin | exact-set `[(src/breezy/adapters/polymarket_us/write_transport.py, D3)]` — constructor is the Call; `FunctionDef` is not |
| Public dispatch | `post_cancel_all` — **do not** name it `_cancel_all_orders`/`cancel_order` or E3 adds extra N2 rows (`firewall:199-213`) |
| Scan | widen this name to `src`+`scripts`+`tests` (plan: fixtures under `EGRESS_SCAN_ROOTS` are invisible) |

`find_probe_importers` (`:775`, `_PROBE_MODULE_NAME` hardcoded) **cannot be reused as-is**: a `write_transport` import returns `[]`. Copy the four forms (import / from / `import_module` / `__import__` / dotted-string), rename the token, assert **exactly one** importer (`factories.py:461-478` is the share site). Probe pin is **zero** importers and has **no** re-export rule; D4 still needs `__all__`/alias/`import *` non-vacuity on that one importer.

## 4. N2 cost

`_EGRESS_MODULE_BASENAMES` (`firewall:175-185`) = `{execution.py, execution_client.py, exec_client.py, order_submit.py, order_router.py, orders.py, trading.py}`. `write_transport.py` **not** in set.

```
_scan_source(virtual path, throwaway): []
would E1 fire after adding basename? True
```

Adding the basename is **exactly one** new N2 row: `(src/breezy/adapters/polymarket_us/write_transport.py, E1)`. No E0 (not under `exec/`), no E2 (class suffix/base miss), no E3 if verbs stay off the lifecycle set. Append after `factories.py` E2 in `test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules` (`:716-741`).

## 5. Write-signer (D6)

Do **not** widen `PERMITTED_METHODS` (`signing.py:84`) or edit `signing.py`. Sibling type in the **exempted** file, `PERMITTED_WRITE_METHODS = frozenset({"POST"})`, same `sign_headers` gate.

Runtime trip: `MethodNotPermittedError` (`errors.py:87-92`) at `Ed25519RequestSigner.sign_headers` (`signing.py:260-265`) — read signer refuses POST today; write signer refuses GET. Handing the write type to `PolymarketUSHttpClient` (`http.py:103`, `_dispatch` always `_GET` `:66,128-129`) fails on the first `sign_headers("GET", ...)`. `http.py:189` is a second GET-only check. **UNVERIFIED:** no `isinstance` on the read ctor; method-set mismatch is the only runtime lock. Put `{"POST"}` only in the exempted file or V1 hits `signing.py`.

D1 share: `NautilusHttpTransport` builds `HttpClient` as a **local** (`:317-325`) and `_shared_polymarket_us_transport` (`factories.py:461-478`) never holds it. Sharing the bucket requires injecting one prebuilt client into both GET-only and POST-only wrappers — GET-only constructor change, **not** a `transport.py` exemption. **UNVERIFIED** whether that injection is treated as a `transport.py` freeze vs “never exempted, never write-capable”.

## Rows R-6.5b must add

| Barrier | Row | Class |
|---|---|---|
| B4 `B4_EXEMPT_PATHS` | `src/breezy/adapters/polymarket_us/write_transport.py` | **NARROWING** |
| `CAGE_EXEMPTIONS` | 2 → 3; rename `test_the_cage_grants_exactly_two_exemptions` (`:832`) | **NARROWING** |
| D2 new frozenset | `{HttpError, HttpTimeoutError}` (+ `HttpClient` iff annotated); pin `transport.py` `{HttpClient, HttpError, HttpTimeoutError, Quota}` unchanged. Test named in R5 D2 is **unlanded**. | WIDENING |
| `BARRED_CALLEES` | `"_build_post_only_callable": "D3"` + one-caller equality; update `:1348` key set | WIDENING (ban) |
| Importer pin | copy `find_probe_importers` → `write_transport`, exact `{factories.py}` | WIDENING |
| N2 `_EGRESS_MODULE_BASENAMES` + exact-set | `write_transport.py` / one E1 row | WIDENING |
| B3 | new test on constructed write transport (wrap, don’t store) | new pin |
| `PERMITTED_METHODS` / `signing.py` | **untouched** | none |

## Checklist (≤10)

1. Land `write_transport.py`: injected client + write signer; `_build_post_only_callable`; `post_cancel_all(url)` → `client.post(url, headers=signed, keys=[QUOTA_KEY_PORTFOLIO])`; no `method`/`query`/`body` params.
2. File-exact B4 exemption; non-vacuity both directions (V1+V2+V3 raw).
3. D2 equality on pyo3 members; plant `SocketClient`/`WebSocketClient`/foreign exec config.
4. `BARRED_CALLEES` + one-caller pin; zero-vs-second-caller RED.
5. One-importer pin on `factories.py` + re-export non-vacuity.
6. Wrap client (B3 `[]`); add B3 test — storing `_client` is RED.
7. Inject shared `HttpClient` into GET wrapper without exposing it; don’t construct a second client.
8. Sibling write signer `{"POST"}` in this file; RED: write refuses GET, read refuses POST (`MethodNotPermittedError`).
9. Add basename → one N2 E1 row; don’t use E3 verb names.
10. Gate on R-6.5P `AUTH_OK`. No live orders.

```
git status --short
```
(empty)


---

## The brief Grok answered

# Investigation brief — R-6.5b pre-implementation measurements (plan §3 D2/D6/D7 and §6)

Repo `/home/jon/breezy` (HEAD `4e43886`). Do not spawn subagents. **Repo writes are FORBIDDEN in this run**: you may run shell commands and write files ONLY under `/tmp/claude-1000/-home-jon-breezy/9c684471-86b5-4072-929b-97ee4d0c33af/scratchpad/`; `git status --short` must be empty when you finish — paste it. Never modify anything under `.venv/`. No network calls. Under 120 lines.

## Invariants (binding)
Nautilus Trader is immutable. `allow_short` stays `False`. Never weaken/delete a safety, barrier or contract test. Never assign a value to an operator-reserved control. Never touch live-trading enablement or the NO-SEND firewall. `signing.py` and `PERMITTED_METHODS == {"GET"}` are untouched. No live orders.

## Context
`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md` §3 (R-6.5b: the shipped write transport — a separate write-signer type D6, a small `src/breezy/adapters/polymarket_us/write_transport.py` outside `exec/` D4/D7, a member-level pyo3 allowlist D2, a `BARRED_CALLEES` entry for the POST builder D3) and §6's least-confident decision: *"Unverified whether B3 already reaches the write builder's construction site, and unverified how the pyo3 client spells a POST. If it is `client.request(...)`, V3 fires inside the write module on an attribute name the exemption must then cover. Run B3 and B4 against a throwaway builder before fixing the allowlist's shape."* R-6.5b is gated on the operator's R-6.5P positive control; this brief does the measurements so implementation is short once that lands. Also read: the landed R-6.5P probe `scripts/venue/polymarket_us_write_signing_probe.py` (how it signs POST locally via `CanonicalRequest` + `build_canonical_path_without_query`, and what it calls on the client), `src/breezy/adapters/polymarket_us/transport.py` (`NautilusHttpTransport`, `PolymarketUSReadTransport`, `_build_get_only_callable`, quota keys, `VenueResponse`), and the barrier source `tests/unit/test_polymarket_us_readonly_guard.py` (B3 `find_write_capable_receiver_exposures`, B4 V1–V5 + C1–C6 + `B4_EXEMPT_PATHS`, B6/B7 `find_barred_callers`/`BARRED_CALLEES`), `tests/unit/test_cage_rule_constants_are_pinned.py`, and `tests/unit/test_execution_egress_firewall_guard.py` (N2 `_EGRESS_MODULE_BASENAMES`, E1/E2/E3).

## Measure and report
1. **How the pyo3 HttpClient spells a POST.** From `.venv/lib/python3.13/site-packages/nautilus_trader/core/nautilus_pyo3.pyi`: every method/free function that can issue a non-GET (`HttpClient.request(method=HttpMethod.POST, …)`, `HttpClient.post`, `http_post`, …), their exact signatures (url, headers, body, keys/quota, timeout), and what `transport.py`'s GET path uses today. Which spelling should the write builder use so that (a) it shares the read path's `HttpClient` instance and rate-limit `Quota` (plan D1) and (b) it trips exactly one B4 rule by an attribute name the file-exact exemption can cover?
2. **Throwaway `write_transport.py` under the scratchpad** (never under the repo): the smallest builder that takes an already-constructed client + a write signer and issues one POST to `/v1/orders/open/cancel` with signed headers, no query, no body. Then, importing the barrier module from the repo, RUN `is_venue_touching`, `find_write_egress_violations`, and B3 `find_write_capable_receiver_exposures` (read its parametrization: what objects does it inspect, and would a `PolymarketUSWriteTransport` instance be reached?) against that file/object, and paste the raw results. State which rules fire (expected: C-classified venue-touching; V1/V2/V3 or V5 raw violations — list them) and therefore exactly what the exemption row and the D2 member allowlist must cover.
3. **B6/B7 shape for the builder pin** (plan D3): read `find_barred_callers`/`BARRED_CALLEES` and `test_b7_the_caller_barrier_has_no_exemption_mechanism`; propose the exact `BARRED_CALLEES` entry and the one-caller exact-path pin for the builder, and check whether the module-level importer pin from R-6.5P (`find_probe_importers`) can be reused for `write_transport.py`'s one-importer pin.
4. **N2 cost**: confirm that adding the basename `write_transport.py` to `_EGRESS_MODULE_BASENAMES` is the only N2 row (plan D4 says one), by running the E1/E2/E3 classifier over the throwaway placed at the real path virtually (i.e. call the classifier function on the scratchpad file with the intended repo path string).
5. **Write-signer type (D6)**: from `signing.py`, the minimal separate type whose permitted set is `{"POST"}` and which the read closure can never be handed by mistake (what runtime check trips, per the plan's non-vacuity RED "the write signer refuses GET and the read signer refuses POST").

Output: numbered findings with `file:line`, the raw barrier outputs, the exact rows/constants R-6.5b must add (as a table: barrier → row → widening/narrowing), the pyo3 spelling recommendation with its reason, and a ≤10-line implementation checklist for R-6.5b. Mark anything unverifiable UNVERIFIED. End with `git status --short` output (must be empty).
