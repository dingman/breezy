# FU-8 Plan: resolver cross-session fill hardening

**Verdict up front:** the gap is real, but it is not the one in the row title. At HEAD a cross-session resolver fill is **silently dropped** by Nautilus. It is never misapplied. Adding a defensive `OrderSubmitted` (the evidence doc's idea) would not help. The native fix is a runtime `ExecutionMassStatus` built by the existing AUD-13b per-record builder. Keep the row open and re-scope it.

## Native contract (L-1 null hypothesis, checked against nautilus_trader 1.231.0)
- **Order not in cache:** `execution/engine.pyx:1253-1307` `_handle_event` looks up by `client_order_id`, then by `venue_order_id`. On a double miss it logs ERROR ("Cannot apply event to any order ... not found in the cache") and **returns**. No position, portfolio or strategy event results. This applies to **every** OrderEvent, including `OrderSubmitted` and `OrderAccepted`. So a defensive `_generate_submitted` before the resolver's fill is dropped by the same guard and fixes nothing.
- **Order in cache, bad state:** `_apply_event_to_order` (`engine.pyx:1586-1596`) catches `InvalidStateTrigger`, logs WARNING and returns `True`. `_handle_order_fill` (`:1333`) then books the fill to the portfolio while the order stays at its old status. At HEAD this case cannot be reached from the resolver:
  - In the same session, `_note_ambiguous_open` only runs after `_generate_submitted`, so the order is SUBMITTED and SUBMITTED→FILLED is legal.
  - Across sessions, the cache is in-memory (`node_config.py:221,586,958`, `CacheConfig(database=None)`), so the order is simply absent.
- **Native facility for "order unknown to this session":** `LiveExecutionEngine._reconcile_order_report` (`live/execution_engine.py:3053-3071`) calls `_generate_order` (`:3512-3614`), which creates `OrderInitialized(reconciliation=True)` and routes it to the claiming strategy (`external_order_claims`) or to `EXTERNAL`. It then emits `OrderAccepted` (`:3266-3267`) and the fills (`:3100-3101`, or CANCELED with trades at `:3279-3290`).
- The runtime entry point is `ExecutionClient._send_mass_status_report` (`execution/client.pyx:919-923`, sending to `ExecEngine.reconcile_execution_mass_status`, registered at `live/execution_engine.py:254`). That runs the same `_reconcile_order_report(report, trades)` loop as boot (`:1880-1908`).
- Do **not** use the single-report `_send_order_status_report`. It passes `trades=[]` (`:1831`), so an IOC partial reported CANCELED would book a cancel with no fill.
- Breezy already builds exactly this pair at boot: `_reports_for_record` (`client.py:3334-3395`) plus `_reconciled_commission` (`:3310-3332`), called from AUD-13b `_durable_reports_for_position`.

**The real gap.** Session A writes the resolver context. The node restarts; mid-day relaunches make this routine. Session B's boot reconciliation finds no durable fill record yet, so it books nothing. Session B's resolver then sees FILLED and calls `_resolve_accept_fill` → `record_fill` → `_retire` → `generate_order_filled`. Nautilus drops that event (ERROR log). The durable ledger is correct, but for the rest of session B Nautilus's portfolio, the strategy and the exit seam cannot see the position. Session C's AUD-13b would recover it, but only if the venue position is still open.

## Acceptance Criteria
1. **Cross-session:** when `self._cache.order(ClientOrderId(context.client_order_id))` is None at booking time, the resolver books the fill natively through one `_send_mass_status_report` holding one order report and one fill report from `_reports_for_record`. The Nautilus cache then holds the order (FILLED, or CANCELED with `filled_qty>0`) and a position for the instrument.
2. **Same session** (order in cache): behaviour is byte-identical to HEAD (`generate_order_filled`, `Money(0, USD)`, `context.strategy_id`).
3. **Fee unknown:** if `_reconciled_commission` returns None or raises, latch `FEE_COEFFICIENT_AMBIGUOUS` through `_latch_reconciliation_refusal`, the same as boot. It is then visible on `reconciliation_refusals`, which the AUD-13b alert watch reads. Nothing is booked and nothing is fabricated.
4. **Durable record unchanged:** the `DurableFillRecord`, the synthetic `GET-<id>` trade_id and the residual classification are all untouched. Resolver fills stay residual by PREREG.
5. **Order preserved:** `record_fill` → venue-id map → `_retire` → booking. A crash at any point still leaves boot-recoverable evidence.
6. The firewall guard stays green with **exactly one** new `EXEC_RESOLVER_PERMITTED_CALLEES` row and no relaxed comparison.

## Edge cases
- **IOC partial:** ordered ≠ filled gives a CANCELED report plus trades. Native books the fill before the cancel (`:3284-3288`). Test it explicitly (L-44 style: each terminal shape).
- **NO leg / SELL exit record:** side comes from `record.order_side` (`OrderSide[...]`) and the leg-resolved instrument. Never hardcode BUY.
- **Unclaimed instrument:** the order books under `EXTERNAL`/`VENUE`, the same as boot. `filter_unclaimed_external_orders` defaults to False (`live/config.py:180`). Breezy does not set it; verify.
- **Instrument missing from cache:** the engine no-ops (`:3056-3062`). Log WARNING, mirroring AUD-13b's `instrument_absent`.
- **Re-entry after `_retire`:** the existing ARCH M2 guard returns before booking, so there is no double book. Native `is_duplicate_fill_c` covers a later duplicate trade_id.
- **Helper raises:** `_resolve_ambiguous_intents` already wraps the call and routes to `_note_resolver_error`. Durable state is committed, so the next boot recovers.
- **Order in cache in a non-SUBMITTED state:** unreachable today. Pin it with a test rather than adding a guard (YAGNI).

## Architecture
The smallest extension is one new sync helper, `_book_resolver_fill(context, record, report, instrument, avg_px, now_ns)`. It replaces the `self.generate_order_filled(...)` block at `client.py:2663-2682`:
- If the order is in the cache, it runs the existing `generate_order_filled` call, moved verbatim.
- Otherwise it calls `_reconciled_commission`, then `_reports_for_record`, then `_assemble([o], [f], [])`, then `_send_mass_status_report`.

**Trade-offs considered:**
- **A. Alert-only** (the evidence doc's suggestion, needs one `self._cache.order` row): cheapest, but the position stays invisible to Nautilus until a restart. Rejected as the primary fix; it is the fallback if review rejects B.
- **B. Mass-status branch** (recommended): native, reuses AUD-13b, and leaves same-session behaviour unchanged.
- **C. Always use mass status:** simpler, but it changes proven same-session semantics (modelled fee instead of 0, a claim-routed strategy id, and fee-ambiguous refusals would now block in-session booking). Rejected; minimal change wins.

## File-by-File
- `src/breezy/adapters/polymarket_us/exec/client.py`
  - Add `_book_resolver_fill`, about 35 lines, next to `_reports_for_record`.
  - Replace lines 2663-2682 with a single call to it.
  - Update the docstring (lines 2537-2546) to state the cross-session contract.
- `tests/unit/test_execution_egress_firewall_guard.py`
  - Add one row, `"self._book_resolver_fill"`, to `EXEC_RESOLVER_PERMITTED_CALLEES`, with a rationale comment in the file's existing style.
  - Keep the `"self.generate_order_filled"` row (removing it is optional narrowing; leave it for a separate reviewed change).
- `tests/unit/test_current_rung_hold_ambiguous_resolver.py`: new behavioural tests (below).
- `docs/core/PROGRESS.md`: re-scope the FU-8 row text to "cross-session resolver fill dropped by native cache-miss guard". This is a doc edit by the coordinator.

## Test Strategy (RED first)
1. **RED, cross-session FILLED:** use a real in-memory `Cache` and exec engine with no order for `client_order_id`, a durable context, a GET showing FILLED, and positions long. Assert `cache.order(coid)` exists and is FILLED, and a position exists. At HEAD this fails because the event is dropped.
2. **RED, cross-session IOC partial (CANCELED, filled>0):** assert `order.filled_qty == record.cumulative_qty` and status CANCELED.
3. **RED, fee ambiguous:** a record dated in the 2026-09-17 ambiguous window. Assert the latch `FEE_COEFFICIENT_AMBIGUOUS` is set, no order is added, and the intent is still retired.
4. **Characterisation pin (L-33, not RED):** the same-session path still emits exactly one `OrderFilled` with `Money(0)` and `context.strategy_id`. Mutation check: delete the in-cache branch and the test must fail.
5. **Pin:** the create path has `_generate_submitted` before `_note_ambiguous_open` (AST order or behavioural). Protects the "unreachable" claim.
6. **Firewall-guard impact:**
   - `_resolve_accept_fill` stays scanned (E0-NOSEND-RESOLVER). Its only new callee is `self._book_resolver_fill`, which is +1 row (L-12 limit).
   - The helper sits outside `EXEC_RESOLVER_COROUTINES`, the same pattern as R-7-IMPL `_match_position_lag`. Its compensating control is `find_order_sender_reference_violations`: the helper may never reference `self._order_sender`, and `ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD` stays `{__init__, _submit_order}` unchanged.
   - `_send_mass_status_report` is a local msgbus send (`client.pyx:920`) with no socket, so E0-TRANSPORT and E0-INERT are unaffected. There are no new imports: `OrderStatusReport`, `FillReport` and `build_execution_mass_status` are already imported.
   - Run the full guard file plus `lint-imports`. Gate: `scripts/ci/run_tests_no_egress.sh`, with PYTHONPATH set in the worktree.

## Risks
- **Mass status side effects at runtime:** `_validate_reconciliation_state` is scoped to reported orders only (`:2138-2169`), and passing no position reports skips `_adjust_mass_status_fills`. Risk: low.
- **Commission divergence:** a cross-session booking uses the modelled fee while same-session uses 0. This matches boot AUD-13b, and the durable record (the ROI and fee source of truth) is unchanged. Risk: low; document it in the docstring.
- **Reviewer objects to an unscanned helper:** fall back to option A (one `self._cache.order` row plus an ERROR log) and accept the in-session blindness.
- **Strategy reacts to the reconciled fill:** it arrives through `external_order_claims` routing, the same route strategies already handle at boot.

## LESSONS compliance
- **L-1/L-11:** native reconciliation reused, and "native handles it" disproved with cited code.
- **L-12:** one row, equality kept.
- **L-14:** barrier derived from the scan rules above.
- **L-33:** pin tests carry mutation evidence.
- **L-36:** no second POST.
- **L-42:** fixtures written through the real `record_fill`.
- **L-43:** full gate after merge.
- **L-44:** both terminal shapes and both legs tested.
- **L-46:** no disguised helper; the SENDER-REF control is stated.
- **L-51:** no uv or stash.
- Invariants: `allow_short` untouched, no operator values read or written, no weakened tests.

## Confidence
- Native-contract findings: **high** (read directly from the installed source).
- Design: **medium-high**. Still to confirm by the RED tests:
  - that `_send_mass_status_report` is dispatched synchronously on the msgbus in the test harness;
  - that runtime `_generate_order` claim routing matches boot for the live strategies.
- Severity stays **LOW**: this is not evidenced live, and it self-heals at the next boot if the position is still open.
