# S4 r4 delta (rev 3) — architect review, round 3 (final) — 2026-10-14

Verdict: REQUEST_CHANGES (bounded; a rev 3.1 applying N-1..N-8 may be accepted by coordinator check). Recorded verbatim by the coordinator (reviewer had no write tool).

## Round-2 disposition
| # | Status | Evidence / gap |
|---|---|---|
| H-1a/b | RESOLVED | P1c (l.104), P6b (l.115) |
| H-1c | PARTLY | site chosen (l.116) but the fallback is a splice; widening mislabelled (N-1) |
| H-2 | RESOLVED; list incomplete | P3 restored (l.107); booking/terminal callees missing (N-5) |
| H-3 | RESOLVED | l.71-74: one `finally`, `resting` threaded, binder clears refusal |
| H-4 | RESOLVED; sub-issues | `cumulative_fee` = recognised (l.133); `fee_reconciled`, `commission_sign` open (N-3, N-4b) |
| H-5a/b | RESOLVED | l.86 one rule; l.87 slug-keyed carve-out (N-7) |
| M-1 | RESOLVED; new race | l.76; two terminal owners (N-2) |
| M-2 | RESOLVED; new gap | own-task loop verified; `_cancel_all_orders` head-of-line blocking (N-6) |
| M-3 | PARTLY | N2 lacks terminal-action callees; N3 lacks the banned-word exception (N-5) |
| M-4, M-5, T2, FW union, LOWs | RESOLVED | enumeration API undecided (N-4) |

## UNVERIFIED items, checked now
1. `cancel_order` own task: VERIFIED (`live/execution_client.py:301-309`; `cancel_all_orders` `:311-317`).
2. `write_transport` → `exec.endpoints`: VERIFIED safe (`exec/__init__.py` empty; `endpoints.py:72-73` imports only errors/transport; contracts `pyproject.toml:74-106` are top-level layers; x1 only constrains exec→transport). Fallback constant unnecessary; still run `lint-imports`.
3. I1b: VERIFIED does not trip on its own (`_refuse(_FEE_UNRECONCILED)` inline in `_submit_order` `client.py:7381-7385`); poll record value undecided (N-3).
4. Order-id charset: UNVERIFIED (venue data); build-time check stands.
5. Store key enumeration: `SqliteStateStore.keys_with_prefix` (`runtime/sqlite_store.py:188`), `.delete` (`:178`) exist, but the client's store type `ClosableStateStore` (`ingest/gate.py:1499`) offers only get/set/close; client wraps `_store_set`/`_store_get` (`client.py:6176-6180`) (N-4).
6. Context carries client order id: VERIFIED (`AmbiguousResolverContext.client_order_id` `:1110`, written `:6770`; key `RESOLVER_CONTEXT_KEY_PREFIX + intent_id` `:6788` → look up via open latch slots).
7. `_expire_gtd_order`: VERIFIED `strategy.pyx:1734-1748`.
8. V2 allowlist `test_polymarket_us_readonly_guard.py:222`: VERIFIED.
9. `calculate_commission` `:6559-6565`, MAKER refusal `:6600-6606`: VERIFIED.
10. `venue_fee_raw` `:968`, decoded `:1065`; `trial_day_latch.py:529` is a docstring mention, not a reader.
11. Banned-word loop `:3374-3381` iterates only `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`; no new P1 name contains read/send/post/request.

## New findings
HIGH
- **N-1 (P7 l.116) fallback is a splice.** `order_by_id_path(id) + "/cancel"` builds a write path from the allowlisted read prefix; `"/cancel"` alone does not trip V2 (L-46 bypass). Allowlist docstring (`readonly_guard:213-221`) says per-order cancel stays refused; parametrized test lists `"/v1/order/{id}/cancel"` (`:2567`). Fix: strike the fallback; relabel P7 "WIDEN + FORCED edit of a safety test" (like T2); same commit updates the docstring and adds parametrized cases proving `{id}`, `{order_id}/modify` and suffix variants still trip.
- **N-2 (§6 l.154 + WP3.8 l.76) two terminal owners for a cancel during HOLD.** Resolver terminal-zero path and `_confirm_cancel_terminal` can both see CANCELED → double settle/restore; resolver can bind while PENDING_CANCEL. Fix: process-local `_cancel_in_flight` set keyed by venue id; resolver skips those ids (pure `in`, shape of `:4299`); while the target is a context the cancel loop does not retire (resolver owns retirement); for bound rows the cancel loop or poll owns retirement guarded by a synchronous check-and-delete of the `resting:` row with no await between. RED: `test_cancel_during_hold_settles_once`, `test_resolver_does_not_bind_while_cancel_in_flight`, `test_poll_and_cancel_confirm_book_one_fill`.
- **N-3 (WP5 l.85) `fee_reconciled` for the poll record undecided.** Six readers: `exec_par_settled_pnl.py:176`, `prereg_admission.py:179`, `continuous_helpers.py:150`, `fq_loss_stop_core.py:214`, `trade_quantity_unit.py:210`, `fee_source_for` (`:894`). Fix: `fee_reconciled = (recognised == raw)`; a clamped negative is unreconciled (settled P&L floors at the taker model; prereg excludes the fill until the WP6 flip). State the exclusion for S2/S5.

MED
- **N-4 key enumeration/delete:** do not widen `ClosableStateStore` (~55 test files). Keep one `resting:index` key with a three-way read mirroring `_read_fill_index` (`:6127-6146`); HOLD contexts via open latch slots; retire by rewriting the index.
- **N-5 pin-row list:** (a) P1d "widens" `generate_order_canceled`/`_cancel_rejected` already in P1 (`firewall:1959`, `:1963`) — strike; `generate_order_expired` belongs to whichever body emits it. (b) N2 lacks terminal callees (`generate_order_canceled`/`_expired`, `self._ledger.settle`, restore pair, `self._refuse`, alert sink, `cancel_latch_deadline`, index write). (c) P3 lacks booking callees (`generate_order_filled`, `DurableFillRecord`, `self.record_fill`, `Money`, `taker_fee_at_fill`, `self._refuse`, terminal set). (d) `_cancel_order`/`_cancel_all_orders` lookups have no row: add one sync helper (`self._resting_cancel_target`) with its own P1 row. (e) N3 needs the same single banned-word exception as N2 for `self._order_sender.post_cancel_all`. (f) N1 must not copy the ban (`self._private_read` contains "read").
- **N-6 (WP4 l.79) head-of-line blocking in cancel-all:** one attempt per id, round-robin, before the backoff loop; pin in N2; RED `test_cancel_all_attempts_every_id_before_backoff`.
- **N-4b `commission_sign`:** drop (derivable from the signed `venue_fee_raw` string; would widen an unlisted exact key-set `test_polymarket_us_exec_client.py:4090-4107` and the golden `golden_exec_par_wp4_k1.json`).

LOW
- **N-7 (l.87):** carve-out matches slug AND qty == 1 AND `last_px` == bound row price; store unavailable → refuse, never raise; CHAR `test_calculate_commission_never_raises_with_store_closed`.
- **N-8:** no await between the `finally` and the HOLD writes (l.72-73); state and test.

## Buildability
WP0 done (provisional); WP1 buildable (step 0 now); WP2 buildable; WP3 steps 1-7 buildable, step 8 needs N-2 + N-5(d); WP4 blocked by N-1, N-4, N-5(b)(e), N-6; WP5 blocked by N-3, N-4b, N-5(c); WP6 after WP3-5.
