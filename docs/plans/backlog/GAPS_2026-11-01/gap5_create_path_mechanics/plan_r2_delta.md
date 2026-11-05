# GAP-5 plan r2 — delta over r1 (architect re-review 2026-11-01: REVISE on two HIGHs; security re-review: APPROVE)

Applies on top of `plan_r1.md`; where they differ the delta wins. Status: r2 — architect confirmation pending; security APPROVE carried (its 3 LOW notes folded below).

## R2-1 (A-HIGH-1) H5 fix location. `next_open_for_resolution` and its ordering (penalty, last-served, created) live in `src/breezy/runtime/submit_intent.py:932-971`; `client.py:3357` only calls it; the latch has no notion of a resting slot (the `resting` flag is on the client's resolver context). `runtime/submit_intent.py` stays OUT of scope. The H5 remedy is limited to the client-side cadence/backoff (`_RESOLVER_POLL_INTERVAL_SECS` `:707`, the backoff at `:711`/`:3290-3298`), with plain comparisons and no new callee. If the census shows the SERVING ORDER (H5b) is the cause, GAP-5 stops and reports; it does not build into the latch.

## R2-2 (A-HIGH-2) H5 split. `_resolver_consecutive_failures` (`client.py:3291-3298`) is ONE client-wide counter: repeated 404s on one context push every OPEN slot's wait toward 300 s, IOC slots included.
- Step 1 census: additionally log the backoff sleep in force at each HOLD and at each WAIT.
- §5 signatures: **H5a** = global backoff in force > 30 s at the time of the HOLD→bind delay; **H5b** = round-robin serving delay with backoff ≤ 30 s. CONFIRMED thresholds as in r1 (≥ 50% of HOLDs that later bound).
- Any H5a fix carries a RED test that IOC resolution latency is not worsened (`test_resolver_backoff_fix_does_not_delay_ioc_resolution`) and keeps `EXEC_RESOLVER_PERMITTED_CALLEES` at zero delta (asserted RED-first, per security LOW-1).

## R2-3 (A-LOW-3) The resolver binds only on `ACCEPTED && filled_qty == 0` (`client.py:3742-3750`) and does not read `_RESTING_CONFIRM_PENDING_STATUSES`; an H3 change therefore affects the inline confirm only. Stated in §4-H3.

## R2-4 (A-LOW-4 + security LOW-1) Step 0 (new, read-only, before step 4): close the five open citations — `client.py:8099` bind-raised exit; `submit_chain.py:85-92` WAIT semantics; the venue-state → `OrderStatus` mapping in `parse_order_status_report`; the supervisor watchdog/heartbeat interval vs the ≤ 15 s deadline ceiling; X1 `:685` superset vs set-equality. Output: a 5-line note in the census `.md`.

## R2-5 (security LOW-2/3) `UNCONFIRMED_GUARD_S` = census p95 of create→OrderAccepted, capped at 60 s; the chosen value and its citation go in the pin commit message. The "34/34 vs 23+18" denominator is reconciled by the census before any threshold is applied.

## R2-6 (architect r2 confirmation) r1 text struck so an implementer cannot follow it
- r1 §3 line 47: the phrase "or slot-serving order" is DELETED; slot-serving order is out of scope.
- r1 §4-H5 line 81 is REPLACED by: "H5a only: change the backoff in `_resolve_ambiguous_intents` (`client.py:3290-3298`) with plain comparisons; H5b → stop and report."
- r1 §6 line 109: `test_resolver_serves_resting_context_first` is REPLACED by `test_resolver_backoff_fix_does_not_delay_ioc_resolution` plus a zero-delta assertion on `EXEC_RESOLVER_PERMITTED_CALLEES`.
