# Order 1 (2026-09-05) — does HEAD still emit OrderFilled without OrderSubmitted?

## Question

AUD-16 §7 step 2 asks which of three holds for order 1
(`O-20260905-201949-L001-SFO-1`): log absent, log exists but order precedes
rotation, or the order genuinely never produced `OrderSubmitted`. The brief
for this doc additionally asserted "order 1 ... has a fill but no
`OrderSubmitted` line" and asked whether HEAD still has an execution path
that could produce that combination.

**Premise correction (verified against the artifact, not carried forward):**
order 1 has **no fill**. `~/.local/share/breezy/state/exec_polymarket_us.sqlite`
(`?mode=ro`) has zero `exec/polymarket_us/fill/*` rows referencing this
client_order_id, and `exec/polymarket_us/intent/history/ac87b697622e4b418f60a41623057e2f`
= `{"state": "RETIRED", "retirement_reason": "OPERATOR_CLEARED", ...}` — the
`breezy-clear-submit-intent --resolution no-order-exists` operator path, backed
by `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/evidence_for_clear_submit_intent.json`
(`"venue_order_id": null, "fill_record": null, "fills": []`). Current
`docs/core/PROGRESS.md:32` already states this correctly: "10 orders, 9 fills
... order 1 ... has no `OrderSubmitted` line ... — open escalation, AUD-13."
Order 1 is the one of ten orders that never filled. The AUD-16 §7 alternative
that holds is **(iii)**: the order genuinely never produced `OrderSubmitted` —
and, contrary to the brief, it also never produced `OrderFilled`. The
"escalation" is about missing evidence hygiene (no raw venue response was
logged for the AMBIGUOUS classification), not about a fill existing without a
submit record.

## Paths traced (file:line)

- `src/breezy/adapters/polymarket_us/exec/client.py:4042-4049` `_generate_submitted`
  — thin wrapper, unconditionally emits `OrderSubmitted`.
- `src/breezy/adapters/polymarket_us/exec/client.py:4414-4436` create-path
  `KIND_ACCEPT_FILL` branch — `_generate_submitted(order, now_ns)` at :4414 is
  called **unconditionally**, immediately before `generate_order_filled` at
  :4419. Comment at :4414-4418 names the exact invariant: "Nautilus's order
  FSM has NO (INITIALIZED, FILLED) transition ... so skipping `OrderSubmitted`
  here would make the `OrderFilled` below unbookable." This path is guarded.
- `src/breezy/adapters/polymarket_us/exec/client.py:4469-4507` AMBIGUOUS
  fallthrough — `_generate_submitted` at :4492-4493 is conditional on
  `outcome.generate_submitted`; `_note_ambiguous_open` (the only writer of a
  durable resolver context) at :4494-4507 is conditional on
  `outcome.venue_order_id is not None`.
- `src/breezy/adapters/polymarket_us/exec/submit_chain.py:1165-1297`
  `classify_create_order_outcome` — in every branch, `generate_submitted`
  is **exactly** `venue_order_id is not None` (response-is-None :1184-1198
  sets both False; 4xx-reject :1210-1223 sets both False/None;
  ACCEPT_FILL :1245-1258 and ZERO_FILL :1268-1281 set both
  True/order_id; the residual AMBIGUOUS return :1283-1297 sets
  `generate_submitted=order_id is not None`). Consequence: at HEAD, a durable
  `AmbiguousResolverContext` is **never written** (client.py:4494) without
  `_generate_submitted` having **already fired earlier in that same call**
  (client.py:4492-4493). Order 1 hit the `response is None` branch
  (confirmed in the log below): `venue_order_id=None`, `generate_submitted=False`,
  so `_note_ambiguous_open` never ran and no resolver context for order 1 was
  ever written — it could not have reached the resolver path below.
- `src/breezy/adapters/polymarket_us/exec/client.py:2408-2537`
  `_resolve_accept_fill` (the resolver's GET-confirmed-fill path) —
  `record_fill` (breezy's own durable ledger, :2468) and `_retire` (:2500) run
  first; `generate_order_filled` (:2518-2537) runs **unconditionally with no
  companion `_generate_submitted` call and no cache/state check**. It relies
  entirely on the create-time invariant above having already fired — in
  whatever node session wrote the resolver context, not necessarily the
  session that later resolves it (durable, cross-restart by design; see
  :2480-2487, :2507-2511 restart-reentry comments).

## Nautilus FSM behaviour (`.venv/.../nautilus_trader`)

- `model/orders/base.pyx:94-157` `_ORDER_STATE_TABLE` has no
  `(INITIALIZED, FILLED)` entry (valid predecessors of FILLED are SUBMITTED,
  ACCEPTED, CANCELED, PENDING_UPDATE, PENDING_CANCEL, TRIGGERED,
  PARTIALLY_FILLED only).
- `core/fsm.pyx:108-129` `FiniteStateMachine.trigger` raises
  `InvalidStateTrigger` **before** mutating `self.state` on a missing
  table entry — the order's status is left unchanged on an invalid transition.
- `execution/engine.pyx:1245-1343` `_handle_event`: looks the order up in
  `self._cache` by `client_order_id`, falling back to a `venue_order_id`
  index; if neither resolves, it logs an ERROR ("not found in the cache") and
  **returns without applying anything** — a clean drop, not a corruption.
  If the order **is** found, `_apply_event_to_order`
  (`execution/engine.pyx:1586-1615`) calls `order.apply(event)` inside a
  `try`; on `InvalidStateTrigger` it logs a **WARNING** ("`did not apply`")
  and **returns `True`** ("Continue processing for idempotent state
  transitions"). Because `True` is returned, `_handle_event` (:1330-1333)
  proceeds to `_handle_order_fill` and publishes the fill to the strategy /
  portfolio **even though the order object itself never transitioned and
  still reports its pre-fill status** — a genuine Nautilus-side silent
  inconsistency, but only reachable when the order **is present** in cache in
  some non-FILLED-eligible status (e.g. INITIALIZED). When the order is
  **absent** from cache entirely (the actual cross-restart scenario for a
  no-persistent-cache node), the event is dropped at :1282-1287/:1302-1307
  with an ERROR log, not misapplied.

## Log evidence

Order 1's actual boot is `~/.local/share/breezy/logs/breezy-trade-20260905T195100Z.log`
(not one of the four other 09-05 files first checked — it exists and is not
truncated at a rotation boundary, ruling out AUD-16 §7 alternatives (i)/(ii)):

```
20:19:49.004 OrderInitialized(client_order_id=O-20260905-201949-L001-SFO-1, ...)
20:19:49.004 [CMD]--> [Risk] SubmitOrder(... status=INITIALIZED, venue_order_id=None ...)
20:19:49.006 [INFO] ExecClient-POLYMARKET_US: Submit LimitOrder(... status=INITIALIZED ...)
20:19:54.212 [ERROR] ExecClient-POLYMARKET_US: Trading refused: create-order outcome is AMBIGUOUS; latch stays open and the booking is held
20:19:54.213 [INFO] ExecClient-POLYMARKET_US: DEGRADED
20:19:54.213 [ERROR] breezy: breezy alert event=component_degraded ... POLYMARKET_US DEGRADED after 1 refusal(s) ...
```

Five seconds elapsed between submit and refusal with **zero** intervening
venue-response detail logged — consistent with `classify_create_order_outcome`'s
`response is None` branch (submit_chain.py:1184-1198), never the residual
AMBIGUOUS-with-order-id branch. No `OrderSubmitted`, `OrderFilled`,
`InvalidStateTrigger`, or "not found in the cache" line exists anywhere in
this session for this order — because this order never reached
`_generate_submitted`, `_note_ambiguous_open`, or `_resolve_accept_fill` at
all. The eventual disposition is the operator's manual clear at
`2026-09-06T01:07:28Z` in the same log (`DEGRADED -> DISPOSE` lines at
:4448-4449), matching the `OPERATOR_CLEARED` retirement in the sqlite ledger.

## Verdict: **NOT-A-HEAD-DEFECT** (for the order-1 incident as stated)

Order 1 is not an instance of "OrderFilled emitted for an order that never
emitted OrderSubmitted" — it never emitted **either** event; it is a genuine
no-response AMBIGUOUS, correctly left with nothing bookable, and correctly
retired by the operator with a verified no-fill venue attestation. The
create-path branch that *does* reach `generate_order_filled`
(`KIND_ACCEPT_FILL`) unconditionally emits `OrderSubmitted` first, and the
only route to a durable resolver context (the AMBIGUOUS-with-id branch) is
gated by the identical condition that gates `_generate_submitted`, so at HEAD
a resolver context is never created without `OrderSubmitted` having already
been emitted in that same call.

**Residual, separately-tracked structural gap (not this incident):**
`_resolve_accept_fill` (client.py:2518) has no defensive `_generate_submitted`
call of its own — it depends on the create-time session having already
emitted `OrderSubmitted` and, implicitly, on Nautilus's cache still holding
that order state when the resolver later runs. If a resolver-discovered fill
is processed in a **different node session** than the one that wrote the
resolver context (a restart in between) and the live node runs an in-memory
(non-persistent) Nautilus cache, `generate_order_filled` for that order is
silently dropped by `execution/engine.pyx:_handle_event`'s cache-miss guard
(ERROR-logged, not applied) rather than corrupting the FSM — a different,
narrower failure mode (lost Nautilus-side fill bookkeeping, while breezy's own
`record_fill` ledger write at client.py:2468 still succeeds) than the one this
brief asked about. This is worth a hardening ticket (assert-and-alert if the
resolver's `generate_order_filled` is ever dropped) but is not evidenced by
any live incident and is not order 1.

No RED test is prescribed: there is no reproducing HEAD defect for the
order-1 incident. If the operator wants the residual gap above closed, the
RED test would assert that `_resolve_accept_fill` raises/alerts (rather than
silently proceeding) when Nautilus's own cache does not contain
`client_order_id` at the time `generate_order_filled` is about to be called —
a new precondition, not a fix to a reproduced failure.
