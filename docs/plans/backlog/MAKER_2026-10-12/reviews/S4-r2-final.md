# S4 r2 final — security-reviewer — 2026-10-12
Verdict: NOT-READY — r2 lands every r1 BLOCKER/MAJOR in the plan body, but two MAJOR defects remain in the no-id/ADOPT path: P6 ("resolver set unchanged") is false, and the restart-fill claim is false against shipped code.

## Disposition check
| r1 review | # | r2 claims | verified? |
|---|---|---|---|
| architect | 1 BLOCKER | intent-keyed entry, `resting:` row, `_retire` carve-out, settle-only | YES: WP3 steps 1-5 + carve-out, 4c `settle(realized_usd=None)`. Real API is keyword-only `settle(key,*,booking,realized_usd,fill_ts_ns,now_ns)` (operator_controls.py:844); `_retire` leak check at client.py:~6683 matches. Plan shorthand is fine. |
| architect | 2 MAJOR | own-order rule P14 | YES: WP4b; trial_day_latch.py:1512-1552 cited correctly; absent key decodes False (fail closed). |
| architect | 3 MAJOR | pins P1-P5, P11 | PARTIAL: P1-P5 line cites all exist (firewall :1797, :1952, :2111, :2155, :2977, :4385). The resolver pin P6 is wrong (see R1). |
| architect | 4 MAJOR | ADOPT, resolver egress-free, P6 unchanged | PARTIAL: ADOPT idea present and no cancel in resolver. But "P6 unchanged" does not hold (R1) and the leg-based claim fails (R2). |
| architect | 5, 6, 7 | expire bound, `resting` param, TAKER/MAKER | YES: WP1/WP3/WP5 bodies. `classify_create_order_outcome` resting flag plus RED present. |
| architect | 8-12 MINOR | native GTD, no pending-cancel, admission check | YES. |
| security | 1 MAJOR | no double register | YES (WP3 + two RED tests). |
| security | 2 MAJOR | (a) REBUTTED by 300 s floor vs 65 s fate bound | YES, true: `_RESOLVER_NO_ID_MIN_AGE_NS=300 s`, `_NO_ID_FATE_FIXED_NS=65 s` (client.py:~1617-1625). (b)(c)(d) present in WP5/WP1. |
| security | 3, 4 MAJOR | S-6, GTC refused; body required, scope constant | YES: S-6, WP1 refusal, `post_cancel_all` body-required (zero client call sites today, confirmed). |
| security | 5 MAJOR | spy-based OS-block test | YES and fixable: classifier is `classify_canary_failure` :383, `os_egress_block_attested` :458; write_transport re-raises `from None` (:167-170), so the spy design is correct. |
| security | 6, 7-11 | settle once; this-process restore; allowlist id; x1 P20 | YES. |
| codex | 1, 2 BLOCKER | S-2 STOP; slug-ledger boot sweep | YES: S-2, 4e. Pre-POST context carries the wire slug (client.py:~7136, `wire_market_slug=body["marketSlug"]`), so the ledger is durable before egress. |
| codex | 3, 4, 5 | WS rejected with reasons; non-post-only STOP; commission sign | YES. |

## Spec v0.3 contradictions (plan line -> spec section)
None substantive. GTD/expire bound (plan :110) = spec §3; never-cross and TAKER-separate (:140, :279) = §3/§6; boot-sweep cost (:276) = §9.18; one-key settle (:165) = §4; K=1 retire (:49) = §9.2.
- MINOR: plan §12 "spec inputs 1-7" are already absorbed by v0.3 (§3 GTD/UTC-day, §3 churn, §9.2, §9.18, taker-separate). Mark them closed so a reader does not re-open them.

## Residual items
- R1 [MAJOR] §6.7 P6 and WP5 "with-id resolver ... binds and retires ACCEPTED_RESTING (WP3 steps 1-5)". The ADOPT -> with-id GET-NEW path runs inside resolver-scanned functions. `self.generate_order_accepted` is absent from `EXEC_RESOLVER_PERMITTED_CALLEES` (firewall :2155; only `generate_order_canceled/filled/rejected`). Also needed: a new `resting:` `_store_set`, which T42(iv) pins to ONE call site and ONE key (:2320), and any new binding helper, which must join `EXEC_RESOLVER_COROUTINES`. So the resolver pin IS touched. `test_resolver_permitted_callees_unchanged` would force a relaxation (S-4 STOP). Fix: name P6 and the T42(iv)/`test_ambig_no_id_firewall_delta.py` rows as WIDENED (no `post_*`, still egress-free), or have the resolver only hand the id to a non-resolver binder coroutine.
- R2 [MAJOR] WP5 "restart ... the resolver then sees either a fill leg (ADOPT) or nothing (NO_FILL)" (plan :210; goal 5) is false for a no-id resting order. In shipped code `no_id_aggressor_legs` reads AGGRESSOR legs only, a maker fill is the passive side; `_matches_echo` requires `tif == IOC_TIF` (no_id_attribution.py:259-272); `window_end = created + 120 s` (client.py:4337, `_NO_ID_WINDOW_FORWARD_NS`), so a fill hours later is `late`/unattributed -> CONTRADICTION; a leg-less maker fill is caught only by the holding-delta check -> `unexplained_holding_delta`/DUPLICATE_SUSPECT. All fail-closed (stuck AMBIGUOUS), not unsafe, but the claim and any RED for it cannot pass. Fix: state that the outcome is fail-closed AMBIGUOUS with the existing alert (or define the intended widening of `_matches_echo`/window and WIDEN-pin it), and drop "fill leg (ADOPT)".
- R3 [MINOR] `_open_order_verdict` returns `(bool,bool)` and ADOPT's `order_id` today comes only from legs (:361-362); WP5 must say the verdict signature and `NoIdEcho.resting` change (the `no_id_echo` property is deliberately object-light for the scanned bodies).
- R4 [MINOR] 4e: say what happens when the post-cancel re-read fails (latch `resting_cancel_unconfirmed`, no row deletion) and that the sweep also refuses while `CANCEL_ALL_SLUG_SCOPE_VERIFIED` is False.
- R5 [MINOR] A 30 s-lagged poll can leave durable_net behind a venue fill on the same instrument and spuriously CONTRADICT a concurrent no-id intent's holding-delta; note it as a fail-closed liveness cost.

## Invariants
- Nautilus immutable / native only: PASS (override hooks, native GTD timer).
- allow_short False, BUY NO only: PASS.
- No pin relaxed, WIDENED rows with evidence: FAIL until R1 (P6 mis-stated as unchanged); other P1-P20 rows PASS.
- Ledger intent-keyed + `settle()` once + reviewed `_retire` carve-out: PASS.
- No-id AMBIGUOUS zero resolver egress: PASS in intent (no cancel in resolver), but R1 changes the callee set.
- Boot sweep slug-scoped over durable pre-POST slug ledger, read-confirmed: PASS (R4 note).
- expire_time <= min(09:00 LST, permit expiry, UTC day), GTD + `manage_gtd_expiry`: PASS (LST term is the strategy's; adapter bounds the other two).
- Cancel without permit cannot place orders: PASS (POST-only signer, `/v1/order/{id}/cancel` allowlist id, bound-id only, cancel-all body = tc-temp slugs, scope-constant gated).
- No operator cap / enablement / PREREG touched: PASS.
