# BL-10 — plan r2 delta (binding amendments to r1)

**Reviews:**
- security-reviewer: READY-WITH-AMENDMENTS, confidence 82.
- architect: REQUEST_CHANGES, confidence 80.

The coordinator merged both. Every amendment below is binding on the implementer. The r1 design stands otherwise: build and encode the body, fingerprint it with one helper in `submit_chain.py`, and bind and consume the authorization.

**Current exploitability (security #2).** No `await` sits between `encoded = …` (`client.py:5380`) and `post_order` (`:5424`), so no body substitution is possible today. BL-10 is defense-in-depth against future divergence (a retry path or a new await), not an active incident. §1 and §7 must say so.

## A1. Placement of `consume` (architect, L-48): hard requirement
Order of operations in `_submit_order`:
1. `build_order_body` / `build_exit_order_body`
2. `encode_order_body`
3. `request_fingerprint(method=_WRITE_METHOD, path=ORDERS_PATH, body=encoded)`
4. `authorization = assert_live_order_submission_permitted(..., request_fingerprint=fp)`
5. `authorization.consume(fp)`

Steps 1–5 run synchronously, with no await, and **before** `authorize_order_cost` and before `self._latch.arm(...)`.
- Delete r1's "retire/deny the latch" cleanup: once `consume` precedes `arm`, a refusal leaves nothing to clean.
- **RED:** a refused `consume` leaves NO OPEN submit intent and NO spent budget booking.

## A2. Exact-set widening (architect, L-12)
`authorization.consume` is a NEW callee. Widen these by exactly the reviewed rows and keep equality assertions:
- the firewall guard sets (`test_execution_egress_firewall_guard.py:1962-1985` and `:3114-3133`);
- the cage pin (`test_cage_rule_constants_are_pinned.py:530-559`, `:627-645`), where `order_fingerprint_bytes` → `request_fingerprint` is a replacement.

Never relax a comparison.

## A3. Added tests
1. A `build_order_body` that raises spends no budget and leaves no intent.
2. An exit-order branch mutation test: a one-byte mutation of the encoded exit body makes `consume` raise.
3. The existing "no await between veto and assert" ordering tests (`firewall_guard:2997-3069`) stay green UNCHANGED.
4. The helper uses the same `_WRITE_METHOD` and `ORDERS_PATH` constants that `sign_headers` uses; assert identity.
5. State in the test docstring that `consume` is single-use and self-enforcing (`safety.py:498-503`).
6. Mark RED tests 1, 2 and 4 as import-gated. Test 3 (`test_submit_order_consumes_authorization_for_encoded_transport_body_before_post`) must show a real assertion failure against a stub helper.

## A4. Gates
- security-reviewer signs off on the implementation diff before merge.
- The merge goes AFTER FAILURE-KIND-DURABLE, rebased onto it.
- Full `run_tests_no_egress.sh` gate after the merge.
- It loads at the next node spawn (16:50Z).
