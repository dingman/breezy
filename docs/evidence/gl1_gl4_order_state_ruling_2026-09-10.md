# Ruling — GL-1 and GL-4 order-state classification (2026-09-10)

**Status: RULED. Both HOLD. R-7 item 5 and R-4 invariant 1 stand unamended.**

Authority: coordinator ruling under the operator's standing grant (architecture and
risk trade-offs are the build side's call, resolved through the adversarial peer
loop, not by operator escalation). Two independent read-only analyses were
dispatched with L-32 as a binding prior; both returned HOLD.

## GL-1 — empty-executions create-order outcome

**Ruling: HOLD.** `200 + id + no executions + non-terminal or absent status`
remains **AMBIGUOUS**. Do not reclassify as ZERO_FILL.

Reasons:
- The venue create-order call blocks until filled, cancelled or expired up to
  `maxBlockTime` (=5); an empty executions list at ~5.2 s is the **timeout**
  shape, not an IOC cancel. The create response schema does not carry a terminal
  `state`/`cumQuantity`, so the body cannot distinguish the two.
- Booking 0 and cancelling an order that may still be working is the
  irreversible direction (L-32). Fail-closed stands.
- **There is no live evidence to rule on.** GL-1a diagnostics (`9ad11ff`) shipped
  AFTER the only live order (2026-09-05 20:19:54Z), so no create-order outcome
  has ever been logged with `body_kind`/`state=`/`cum=`. The row asks to rule
  from a body nobody has seen.
- At n=0 fills this is a **contingency for a state not yet reached**, not a
  blocker on the path to a first fill.

Falsifiers that would reopen it:
1. A live `body_kind=empty-executions state=ORDER_STATE_CANCELED|EXPIRED|REJECTED
   cum=0` — that is already ZERO_FILL under the EXISTING item 5; no amendment needed.
2. `state=absent cum=absent` plus a contemporaneous GET returning terminal with
   `cum=0` and no later fill/position — then consider a LOG-ONLY GET probe.
3. A live `GET /v1/order/{id}` 404 on an id create just returned — that would make
   path (b) fail-open and HARDEN this hold.

## GL-4 — automated retire of an AMBIGUOUS submit intent

**Ruling: HOLD — stay manual, fail-closed.** Do not amend R-7 item 5. Do not amend
R-4 invariant 1 (`client.py:171-176`): the refusal latch is node-global and never
self-clears. Do not call retire from `_submit_order` after any GET.
`breezy-clear-submit-intent` remains the ONLY exit from AMBIGUOUS, and only with a
positions plus no-fill attestation, and only when the node does not hold the flock.

Reasons:
- `generate_order_status_report` (`client.py:995-1042`) already maps **any**
  exception to `None`. That IS a false ABSENT. A 404 or empty result after a 5 s
  timeout can be index lag, clock skew, or a filled IOC dropped from history.
  A false ABSENT retires the intent for an order that filled, leaving an unbooked
  fill and real money in an untracked position. The hazard can be bounded, not excluded.
- Auto-retire would additionally have to DELETE the AMBIGUOUS `_trading_refusals`
  row or every later submit still dies — that is a second, deeper amendment — and
  releasing the held booking on a maybe-fill re-grants spend.
- **The row's own justification does not exist.** "Two plan reviews scored risk <6"
  appears only as a sentence in `PROGRESS.md`; there is NO review artifact in
  `docs/plans` or `docs/evidence`. Per L-32 an unbacked backlog claim is not a spec.
- Measured cost is ONE event (09-05), cleared manually. Same-afternoon salvage of
  1-3 stations is not worth an unbooked fill. The manual clear already has a
  flock-free window daily at 16:40-16:50Z.

Falsifiers that would reopen it:
1. A live no-id AMBIGUOUS AND a later same-afternoon executable take actually
   denied at arm (not yet observed).
2. A venue measurement showing `GET /v1/portfolio/positions` is linearizable with
   fills, excluding false ABSENT rather than bounding it.
3. The node staying up across the 16:40Z stop so the operator cannot clear without
   a mid-window SIGTERM.

**Approved follow-on (open, small): GL-4P.** On the next create-order AMBIGUOUS,
persist a positions snapshot alongside the existing GL-1a tokens as durable
evidence. Log-only. No retire, no `_trading_refusals` mutation, no booking release.
Purpose: learn whether the live shape is no-id or `200-id-no-exec`, which the one
observed event did not record.

## Bearing on a first fill

Neither blocker is on the critical path at n=0. Both describe what to do AFTER an
order returns an ambiguous state; neither prevents an order being sent. The actual
barriers remain: no supervisor running (GL-7) and no measurement of why takes do
not happen.
