**Overall verdict: NOT-READY, 63/100.** r3 resolves most r2 findings, but one new design bug defeats the point of the plan, and two specifications are wrong against the code.

**WP-DR alone: NOT-READY.** The idea is right and the stale-booking worry does not hold. Three defects need fixing before it merges (items 1, 2 and 6 below).

## r2 findings: status

| r2 finding | Status |
|---|---|
| Arch HIGH-1/2/3/4, MEDIUM-3 | Resolved on paper: `admit` at K=1 is equivalent to `is_latched` for exits, the predicate runs before spend, the :6110 gate is unscoped-only, the slug derivation is exception-contained, and `raw_slots` is preserved. |
| Safety C1 (unreadable slot lost) | Resolved by `raw_slots`; one spec contradiction remains (item 9). |
| Safety H1 (midnight) | Partly resolved by WP-DR; see items 1, 2, 3 and 6. |
| Safety H3 (duplicate detector) | Partly resolved. The sign handling is correct, but `qty_est` is wrong for NO (item 5). |
| Safety H4 (slug at clear) | Resolved by the record slug, but the scoping rule creates item 4. |
| Safety M1 (halt blocks exits) | Resolved by the entry-halt flag. Its liveness is unspecified (item 8). |
| Market HIGH-1 (day stop from pre-check) | Mostly resolved; two gaps remain (item 7). |

## HIGH

**1. WP-DR's `except LiveTradingPermissionError: log and continue` converts a visible halt into a log line.**
- The ledger's other raises are integrity errors the docstring says to "surface, never absorb". Examples: `realized > booking.cost`, already trued-up or released, unknown booking, clock backwards (`operator_controls.py:438-447`, `:480-509`).
- Today, a raise at the accept-fill `true_up_booking` (`client.py:3408`, before `_retire` at :3429) leaves the intent OPEN. The next pass sees `booking is None` and latches the global DURABLE `_RESOLVER_FILL_UNBUDGETED` (:3458-3466).
- With the blanket except, the retire proceeds, `booking` is non-None so UNBUDGETED never fires, and an over-cost fill is unbooked. Nothing halts; there is only an ERROR line. The same applies to the zero-fill (:3231) and no-id (:4072) sites.
- **Fix:**
  - Catch nothing. The day-mismatch skip already removes the only expected raise.
  - If a catch is kept, log the exception and surface it through the health path, not only an ERROR line.
  - Add a RED test that a same-day over-cost true-up still escalates.
- Open question 6 answers itself: a new `_refuse` site moves the 25-site pin by a named row, which the invariants allow.

**2. WP-DR's "no new allowlist rows" is false.**
- `_resolve_terminal_zero`, `_resolve_accept_fill` and `_resolve_no_id_intent` are all in `EXEC_RESOLVER_COROUTINES` (`test_execution_egress_firewall_guard.py:2113-2127`), so their bodies are scanned.
- `utc_day_for_ns` is not in `EXEC_RESOLVER_PERMITTED_CALLEES` (grep returns nothing), so the plan's `booking.day != utc_day_for_ns(now_ns)` would fail E0-NOSEND-RESOLVER.
- **Fix:** name the `utc_day_for_ns` row in WP-DR, keeping `==`. Alternatively, compute the day without a call (e.g. compare against a day carried on the context).

**3. Skipping the ledger call undercounts a fill that lands after midnight.**
- If a booking made on day D is skipped and the venue fill's `ts_event` falls on D+1, the D+1 budget never sees that cost.
- The UNBUDGETED refusal does not fire, because `booking` is not None.
- WP-DR's tests cover only the fill timestamped before midnight (:296), not the reverse.
- **Fix:** if the fill's UTC day equals today and the booking day differs, take the unbooked path (count it or flag UNBUDGETED). Add the reverse test.

**4. The refusal-scope rule makes the first AMBIGUOUS global at every K (§3.4).**
- The AMBIGUOUS refusal is appended as `instrument=slug if open_slot_count() > 1 else ""`.
- The count includes the intent's own slot. The common case is a lone ambiguous order, with count 1, so the refusal is unscoped.
- The :6110 gate then denies every slug until that slot retires (at least 120 s). That is today's behaviour, and it defeats the plan's purpose.
- Scoping happens only when other slots were already open when the POST returned.
- **Fix:** scope on `K > 1` (the configured constant, §3.2), not on the table count. K=1 stays unscoped.
- Add a RED test: with K>1, a lone ambiguous order on A does not deny B.

**5. The duplicate-detector `qty_est` is wrong for NO and unnecessary.**
- `qty_est = notional_usd / Decimal(wire_price)`. The wire body carries a hard-coded `"quantity": 1` (`submit_chain.py:373`).
- `wire_price` is `1 − price` on the NO leg (`submit_chain.py:363-368`). `notional_usd` is `order.price × qty` (`submit_chain.py:245-246`).
- For a NO order at 0.10, `qty_est` is about 0.11, so every normal fill trips (a false halt). At NO 0.90, `qty_est` is about 9, so a real duplicate is never seen.
- **Fix:** use the wire quantity constant (1) as the estimate. Or add the trailing-optional `wire_quantity` field in `AmbiguousResolverContext`. Open question 2 resolves to "add the field".
- Add a RED test per leg at both price ends.

**6. WP-DR's goal "retire completes" omits the booking-popped state on skip.**
- On skip, `_ambiguous_bookings.pop` has already run. The stale `SpendBooking` stays in the ledger's `_bookings` until the next `authorize_order_cost` roll prunes it (`operator_controls.py:403-417`).
- This does not mis-account: the ledger resets on the next roll. The test list should assert the permit restore and cancel run, which the plan does.
- It should also assert that no further ledger error occurs on a later same-day authorize. I found no stale-booking hazard on this path.
- Treat this as a test addition only. It is the answer to the "stale bookings" question.

## MEDIUM

**7. Pre-check versus authority (§3.3).** The two checks can disagree in two ways that mark a day stop or waste a permit slot.
- **Cost rounding.** In-lock cost is rounded up to the cent (`_round_cost_up_to_cent`, `operator_controls.py:464`). If `exposure_admission_refusal(price_usd, quantity, ...)` computes the cost differently, it can pass at the boundary while the in-lock check fails by a cent.
  - If the in-lock uncharged check raises `DailyBudgetExhausted`, that writes the durable day-stop marker (:6282, :5413-5438).
  - If it raises `OpenExposureBoundExceeded` (:6284), the permit slot is already spent.
  - **Fix:** share the in-lock cost function and exception mapping, and state that the in-lock `spent + uncharged + cost` check raises the non-day-stop type.
- **Read-only claim.** §3.5 says the pre-check calls `_roll_locked`, which mutates (prunes bookings and resets `_spent_usd`). `test_precheck_is_read_only` conflicts.
  - It also needs a defined result when the operator budget control is unset or the clock moved backwards. Those raise `LiveTradingPermissionError` today (:396-402). Map them to a deny without a marker.

**8. Entry-halt key (§3.6).**
- The watcher writes the flag asynchronously. If the watcher task dies there is no alert, so the breaker fails open.
- **Fix:** add a watcher heartbeat or liveness alert, and a test.
- `admission_refusal` does a store `get` per order. A garbled value or a store exception must fail closed (deny entries) and not raise out of `_submit_order`. The :6110 and slug `try/except` do not cover it.
- Rolled-back code ignores the key, so the breaker goes inert silently. The rollback section should say so.

**9. `raw_slots` spec contradictions (§3.1).**
- The first bullet says the table is v1 whenever at most one slot is open, counting unreadable ones.
- A lone unreadable slot cannot be encoded as v1, and the WP2 test correctly requires staying v2. Reword the rule.
- The plan should state how "verbatim bytes" is stored in JSON (encoded, e.g. base64) and what happens to non-UTF8 input.
- The CLI `--slot-key --ack-unreadable-slot` removes a slot that has no intent id. It cannot write `history_key`. Require dumping the raw bytes to an evidence file before removal.

## LOW
- **10.** WP-DR's INFO log on skip is a single line. Add a counter surfaced to the digest, so repeated midnight crossings are visible.
- **11.** The `exit_guard` and `trial_day_latch` hunks in WP6 are correct, but nothing tests the entry-halt flag in `admission_would_refuse`. Add one test.
- **12.** `contradiction_events_total` is in memory. A crash between detection and the watcher's latch loses the event until re-detection (the detector needs two consecutive passes again). Document it.

## Checked and fine
- The breaker never blocks the resolver. `_submit_veto` has a single reader at `client.py:6215`, and the new entry-halt key is read only inside `admission_refusal`.
- The WP4 allowlist rows are sufficient for the order and resolver bodies, apart from the WP-DR `utc_day_for_ns` row (item 2).
- The `admit` property at K=1 now covers exits.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r3.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/submit_chain.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py
- /home/jon/breezy/tests/unit/test_execution_egress_firewall_guard.py
