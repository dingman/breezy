# R-6.5b BUILD BRIEF — shipped write transport (2026-09-04, converged)

Source: `EXEC_SPINE_NEXT_2026-09-04.md` §B + §D. Verified against `b418424`. Hand to the
implementer verbatim; the implementer cannot see the review conversation.

## Role and rules
Land the shipped, signed POST transport for Polymarket.us as a small, write-only,
file-exact-exempted module, extending Nautilus only through `nautilus_pyo3.HttpClient`.
**Nautilus Trader is immutable.** RED tests first; their RED→GREEN output is the change
artifact. Gate: `scripts/ci/run_tests_no_egress.sh` (never bare pytest). Passed count must
rise by exactly the new test count and NEVER drop by even one (a drop = a safety test was
removed — stop the line). Widen barriers, never relax (L-12). Ships with ZERO send call
sites: `factories.py` constructs it; nothing dispatches through it until R-7.

## Files
CREATE `src/breezy/adapters/polymarket_us/write_transport.py` (NOT under `exec/`) and
`tests/unit/test_polymarket_us_write_transport.py`.
CHANGE `src/breezy/adapters/polymarket_us/factories.py` (the one and only importer),
`tests/unit/test_polymarket_us_readonly_guard.py`,
`tests/unit/test_cage_rule_constants_are_pinned.py`,
`tests/unit/test_execution_egress_firewall_guard.py`. Nothing else. `signing.py`,
`transport.py`, everything under `exec/**`: untouched.

## Decisions (implement, do not relitigate)
- **Shared client, injected.** `build_shared_http_client` (`transport.py:317-393`, exported
  `:65`) is the singleton; `factories.py:466-479` already consumes it. Extract the argument
  expression into ONE `_shared_polymarket_us_client(config)` helper both wrappers call.
  Constructor takes the client keyword-only; never mint a second client (it halves the
  `Quota`).
- **Dispatch spelling.** `client.post(url, headers=signed, keys=[QUOTA_KEY_PORTFOLIO])`
  (`transport.py:94`; pyo3 stub `nautilus_pyo3.pyi:5444-5452` accepts `keys=`). No `params`,
  no `body`, no per-call timeout. Never `client.request(...)`, never `nautilus_pyo3.http_post`.
- **Wrap, don't store (B3).** Mirror `_build_get_only_callable` (`transport.py:131-148`):
  closure over the client on a `__slots__ = ()` object; never an attribute. No module-level
  holder (B3-M, `readonly_guard:159`). `_build_post_only_callable`'s ONE caller is
  `write_transport.py` itself (as `transport.py:451`), not `factories.py`.
- **Write signer = SIBLING, not reuse.** `sign_headers` refuses POST by design. Mirror the
  shipped, B4-exempted `_sign_write_headers`
  (`scripts/venue/polymarket_us_write_signing_probe.py:351-376`): same
  `build_canonical_path_without_query` over `CanonicalRequest(method="POST", …)`, same key
  loader, same three header names; gated by `PERMITTED_WRITE_METHODS = frozenset({"POST"})`
  defined in `write_transport.py`. The read signer's POST refusal and the write signer's GET
  refusal both raise `MethodNotPermittedError`.
- **Unverified premise pinned.** `WRITE_CANONICAL_STRING_VERIFIED: Final[bool] = False` with
  a docstring: flips only by OP-4's probe artefact path; R-7 must refuse to wire a call site
  while `False`.
- **V1+V2+V3 stay INSIDE the exempted file:** `'POST'`, `'/v1/orders/open/cancel'`,
  `.post`. Public dispatch is `async def post_cancel_all(...)` (a coroutine; outside `exec/`
  it engages no async-lifecycle pin). Never name it `cancel_order`/`_cancel_all_orders`
  (`ORDER_LIFECYCLE_COROUTINES`, `egress_firewall_guard:1677-1685`).
- **Importer pin is a COPY** of `find_probe_importers` (`readonly_guard:882-924`; it
  hardcodes `_PROBE_MODULE_NAME` `:875`): four forms (plain import, from-import,
  `importlib.import_module`/`__import__`, dotted-string literal), roots `("src","scripts")`
  plus an explicit `tests/` sweep for the `BARRED_CALLEES` half. Exactly one importer,
  `factories.py`; no `__all__` re-export, no module-level alias, no `import *`.
- **RED 3 needs a NET-NEW AST helper** enumerating `nautilus_pyo3.X` attribute references in
  a file (none exists); budget it.

## RED tests (each must fail today; write first, paste failing output)
1. `test_the_write_callable_has_no_method_query_or_body_parameter`
2. `test_it_issues_exactly_one_post_to_the_one_pinned_path` (non-vacuity vs a widened allowlist)
3. `test_write_transport_references_exactly_the_permitted_pyo3_members` — `{HttpError, HttpTimeoutError}` (+`HttpClient` iff annotated); planted `SocketClient`/`WebSocketClient`/foreign exec config each fire
4. `test_build_post_only_callable_has_exactly_one_caller` — remove → red; second caller incl. under `tests/` → red
5. `test_write_transport_has_exactly_one_importer_and_it_does_not_re_export`
6. `test_the_write_signer_refuses_get_and_the_read_signer_refuses_post`
7. `test_b3_the_constructed_write_transport_exposes_no_write_capable_receiver` — `find_write_capable_receiver_exposures(...) == []` (`readonly_guard:522`); storing `_client` → red
8. `test_b4_raw_content_is_exactly_the_three_expected_violations` — `find_write_egress_violations(path, source)` equals exactly `[(V1,'POST'),(V2,'/v1/orders/open/cancel'),(V3,'.post')]` by `(rule, detail)`; non-vacuity both directions (without the exemption the real file trips `scan_write_egress`; a second file with the same literals still trips with the exemption in place)
9. `test_the_shipped_write_signer_and_the_probe_produce_the_same_canonical_string` — identical signature bytes over one injected timestamp and path (lives under `tests/`, outside the importer-pin roots)
10. `test_write_canonical_string_verified_is_false_until_op4`

## Barrier tests to WIDEN (never relax)
- `readonly_guard:240` `B4_EXEMPT_PATHS` += `"src/breezy/adapters/polymarket_us/write_transport.py"` (exact string).
- `readonly_guard:825` `_WRITE_SIGNING_PROBE_PATH = next(iter(B4_EXEMPT_PATHS))` → the literal `"scripts/venue/polymarket_us_write_signing_probe.py"` plus `assert _WRITE_SIGNING_PROBE_PATH in B4_EXEMPT_PATHS` (BLOCKING: with two members `next(iter)` re-points three tests at an arbitrary file).
- `readonly_guard:604-609` `BARRED_CALLEES` += `"_build_post_only_callable": "D3"`; update the key-set pin `:1497-1498`; add the one-caller exact-set pin.
- `cage_rule_constants:855,863` `two`/`== 2` → `three`/`== 3` and rename the function. `CAGE_EXEMPTIONS` is derived (`:733`) — do not hand-edit. Edit the EXISTING `RulePin(attr='B4_EXEMPT_PATHS')` (`:509-525`: `expected` gains the member; re-choose `widened` so it stays a strict superset) and `RulePin(attr='BARRED_CALLEES')` (`:176-188`). No new constant registered.
- `egress_firewall_guard:175-185` `_EGRESS_MODULE_BASENAMES` += `write_transport.py`; exactly one E1 row in `test_n2_…` (`:688`) after `factories.py`'s E2 row. No E0/E2/E3 rows.

## Invariants (binding)
Nautilus immutable. `allow_short` False. `PERMITTED_METHODS == frozenset({"GET"})`.
`signing.py` untouched. `transport.py` never write-capable, never in `B4_EXEMPT_PATHS`.
`PolymarketUSReadTransport` protocol method-free. Nothing under `exec/**` changes; `exec/`
never imports `write_transport` (R-7 will INJECT the built closure via the factory). Never
weaken/delete a safety, settlement, barrier or contract test. Never assign an
operator-reserved control. Never touch live enablement or the NO-SEND firewall beyond the
rows named here.

## Exit
Gate green; count up by exactly the new tests, never down; RED→GREEN output for all ten
tests kept; `scan_write_egress()` `[]` with the exemption and non-empty without it;
`.venv/bin/ruff check` clean on changed files; `WRITE_CANONICAL_STRING_VERIFIED is False`.
