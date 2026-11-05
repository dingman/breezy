# FU-8 Plan r2: resolver cross-session fill (A: named refusal, no booking)

**Verdict up front:** r1's premise was wrong on two counts. Once the boot is traced, the evidence supports **option A**, not B or B-guarded. Session B's boot already makes a still-held position visible to Nautilus at the correct quantity. It does this in one of two ways: AUD-13b books the resolver's own record with full attribution, or Nautilus creates a synthetic RECONCILIATION position. What remains is a gap in **order attribution**, not in the position. Any runtime booking would double the position (L-47) or open a phantom long on a settled market (L-18). Severity stays **LOW**.

## Boot trace: what session B leaves in the cache (nautilus_trader 1.231.0, OMS NETTING, `client.py:1405`)
- **Boot order.** `_connect` awaits one resolver pass with `first_pass_immediate=True` (`client.py:1722`) **before** kernel reconciliation. Only after that does it start the periodic task (`:1742`), whose first pass sleeps first (`:2079-2087`).
- **T1, the one-shot pass resolves FILLED (the common case).**
  - `record_fill` → `_retire` → `generate_order_filled` (`:2608-2682`). The native event is dropped because the order is not in a fresh cache (`engine.pyx:1253-1307`, ERROR log).
  - Kernel `generate_mass_status` (`:2877`) then finds the **new** record. If `_records_explain_position` (`:3277-3308`) holds, `_durable_reports_for_position` builds the order and fill reports under the real `client_order_id`.
  - Nautilus books the order and the position with the right qty, claimed by the station strategy (`_station_claims`, `composition.py:418-440`, today and yesterday, both legs).
  - r1's "boot books nothing" is false here. The only defect is a misleading native ERROR line.
- **T2, the fill is resolved only after the boot snapshot** (the one-shot pass saw PENDING, a GET failure or no instrument, or a periodic pass interleaved after `_durable_reconciliation_pass` memoised its records at `:3118-3212`):
  - **Venue still holds (LONG, not expired):**
    - The records do not explain the position, so `RECORD_VENUE_DISAGREEMENT` is latched and alerted at boot. Order and fill reports are suppressed. The position report **is** forwarded (`:3086-3090`, `:3554-3567`).
    - `_reconcile_position_report_netting` (`execution_engine.py:2466-2566`) sees `positions_open` = 0 against the venue qty. With `generate_missing_orders=True` it creates a synthetic RECONCILIATION order for the full venue qty. `_generate_order` (`:3549-3563`) routes that order to the claiming strategy, or to EXTERNAL.
    - Entry price comes from `_entry_price`: venue cost basis, else 0.00 plus a refusal (`client.py:124-151`).
    - **The position is visible and its qty is correct.** A later resolver booking would make it 2×.
  - **Venue closed or settled:** `expired` → gated out (`:3527-3538`). A FLAT report is never forwarded (`:3540-3545`). Nautilus holds nothing.
    - `_resolver_long_position_state` (`:1292-1311`) ignores `expired`, so an expired position with `netPosition>0` still passes the LONG gate.
    - Under B, that fill would therefore open a **phantom long on a settled market**.
- **B-guarded collapses:**
  - Its "no open position accounts for the fill" guard fails in every venue-held T2 case, because the synthetic position accounts for it.
  - Its "venue still holds" guard fails in every closed case.
  - It would book only when the boot never forwarded the position (`positions_read_failed` or `instrument_absent`). Both are already named at boot. Covering those two cases would add a positions GET and a qty-matching race, a large risk for a narrow case. **Rejected.**

## Acceptance Criteria
1. **Same session** (the order is in `self._cache`): behaviour is byte-identical to HEAD. `generate_order_filled` stays verbatim at `:2663-2682`, with `Money(0, USD)` and `context.strategy_id`.
2. **Cross-session, before the snapshot** (T1): when `_boot_snapshot_started` is False, skip `generate_order_filled` and log one INFO line saying the fill is "deferred to boot durable reconciliation (AUD-13b)". Nothing is latched. The later boot pass books the fill natively and with attribution.
3. **Cross-session, after the snapshot** (T2): skip `generate_order_filled`.
   - Latch a new named refusal, `RESOLVER_FILL_NOT_BOOKED` (detail `"RESOLVER_FILL_NOT_BOOKED"`), through `_latch_reconciliation_refusal`. The subject is `_redact_order_id(venue_order_id)`.
   - Log one ERROR line stating the instrument, the fill qty and the Nautilus net qty from `positions_open` (log only, no branching).
4. **Nothing is booked at runtime:**
   - No `_send_mass_status_report`, no `_send_order_status_report`, no `generate_order_*` on the cache-miss path.
   - Nautilus net qty after the resolver equals net qty before it.
5. **Durable path unchanged:** `record_fill` → venue-id map → `_retire` → unrestore run before the new check. The `DurableFillRecord`, the `GET-<id>` trade_id and the PREREG residual classification are untouched.
6. **The boot counts line stays byte-identical:** the refusals sum (`:3198-3200`) iterates the four boot latches only.
7. **Firewall:** exactly one new `EXEC_RESOLVER_PERMITTED_CALLEES` row, and no relaxed comparison.

## Edge cases
- **Race during the mass status:** `_boot_snapshot_started` is set at the top of `generate_mass_status`, before its first await. A resolve in flight at that point latches even if the snapshot would later have caught the record. The failure direction is a false alert, never silence.
- **NO leg:** the subject and log use the leg-resolved `context.instrument_id` (`^no`). The YES sibling is untouched.
- **SELL exit record:** same classification. No side logic is added.
- **Instrument loaded by the resolver after boot** (the prior-day loader, `:2210-2250`): this is T2 with no Nautilus position. It latches, and the next boot's AUD-13b books it if the venue still holds. The pre-existing `instrument_absent` behaviour is unchanged (out of scope).
- **Re-entry after `_retire`:** the ARCH M2 guard (`:2555-2558`) returns first. The latch dedupes by `(latch, subject)`.
- **Helper raises:** the existing `_resolve_ambiguous_intents` wrapper routes to `_note_resolver_error`. Durable state is already committed.
- **Reconnect:** the flag is never reset. A later cache miss latches, which is the conservative direction.

## Architecture
- **New flag.** `self._boot_snapshot_started: bool = False` (in `__init__`), set True as the first statement of `generate_mass_status`.
- **New helper.** A sync helper `_resolver_fill_order_unknown(context, report) -> bool`, about 25 lines, placed next to `_latch_reconciliation_refusal`:
  - It returns False when `self._cache.order(ClientOrderId(...))` exists.
  - Otherwise it classifies per AC2/AC3 and returns True.
  - It takes **no sender or transport parameter** and never references `self._order_sender`.
- **Call site.** In `_resolve_accept_fill`, immediately before `self.generate_order_filled(`: `if self._resolver_fill_order_unknown(context, report): return`.
- **Rejected alternatives:**
  - **B:** doubles the position or opens a phantom long.
  - **B-guarded:** books only in already-latched residual cases, at the cost of new GETs and races.
  - **C, always mass status:** same flaws, plus it changes same-session semantics.

## File-by-File
- `src/breezy/adapters/polymarket_us/exec/client.py`:
  - Add the `RESOLVER_FILL_NOT_BOOKED` constant next to `:457-464`, and add its entry to `_RECONCILIATION_REFUSAL_DETAILS` (`:475-480`).
  - Add a new `_BOOT_PASS_REFUSAL_LATCHES` tuple of the four existing latches, and use it in the sum at `:3198-3200`.
  - Add the flag, the helper and the one-line call site.
  - Update the docstrings at `:2537-2546` and `:2043-2050` (crash safety).
- `src/breezy/runtime/component_health_watch.py:250-257`: add `"RESOLVER_FILL_NOT_BOOKED"`, so the alert is not sent as `RECONCILIATION_REFUSAL_UNKNOWN`.
- `tests/unit/test_execution_egress_firewall_guard.py`:
  - Add one row, `"self._resolver_fill_order_unknown"`, with a rationale comment.
  - Keep `"self.generate_order_filled"`, because it is still called.
  - Add the helper to **neither** `EXEC_RESOLVER_COROUTINES` nor `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` (security condition a).
- `tests/unit/test_current_rung_hold_ambiguous_resolver.py` and `tests/unit/test_component_health_watch_reconciliation_refusal_alert.py`: the tests listed below.
- `docs/core/PROGRESS.md` (coordinator): re-scope the FU-8 row to "cross-session resolver fill: attribution gap only; named refusal".

## Test Strategy (RED first; real `Cache` plus `LiveExecutionEngine`, fixtures written through the real `record_fill` per L-42)
1. **RED, T1 boot ordering:** the one-shot pass with the flag False. Assert `generate_order_filled` is not called, the INFO deferred line is logged and no latch is set. Then a real `generate_mass_status` → `reconcile_execution_mass_status`. Assert the order is in the cache under the real coid and the position qty equals the record qty.
2. **RED, T2 venue held (architect 6a):** the boot mass status carries the position report only (no record), which seeds the synthetic RECONCILIATION position. Run accept-fill. Assert net qty equals the venue qty (not 2×), no order for the coid, and `RESOLVER_FILL_NOT_BOOKED` latched.
3. **RED, T2 venue closed or settled (6b):** an expired position, and separately a FLAT one. Assert no Nautilus position before or after, and the latch is set.
4. **RED, NO leg (6c):** a `^no` context. Assert the same as test 2 on the NO instrument, and the YES instrument has no position.
5. **Security (c), strengthened:** on the cache-miss path, spies on `_send_mass_status_report`, `_send_order_status_report` and `generate_order_filled` record zero calls, and the intent is still retired.
6. **Characterisation pin (L-33):** same session emits exactly one `OrderFilled` with `Money(0)` and `context.strategy_id`. Mutation check: forcing the helper to return True must fail this test.
7. **Race:** a resolve while `generate_mass_status` is suspended at its first await → the latch is set.
8. **Alert:** the watch maps the new detail verbatim.
9. **Counts line:** `test_reconciliation_durable_reports_contract.py:713-718` stays **unchanged** and green.
10. **Periodic-reconciliation pin (6d):** already pinned at `test_runtime_trade_node_config.py:269,283-284` and `test_exec_client_reconciliation_contract.py:184-188`. Cite them in the helper docstring. A books nothing, so its safety does not depend on them.
11. **Gates:** the full firewall-guard file, `lint-imports`, and `scripts/ci/run_tests_no_egress.sh`, with PYTHONPATH set in the worktree.

## Risks
- **[MED] Alert delivery latency.** The watch polls only on `events.system.*` (`component_health_watch.py:285-314`). A runtime latch therefore alerts at the next component state change, not immediately. It is unverified whether any runtime publisher fires periodically. Mitigations: the ERROR log line, the boot `RECORD_VENUE_DISAGREEMENT` alert that already fired for the same instrument in T2-held, and the next boot's AUD-13b re-attribution. Reviewer to rule whether this delivery is sufficient (L: a detector without delivery is not a control).
- **[LOW] Attribution in T2.** The position sits under a synthetic order with the venue cost basis (or 0.00 plus a refusal). This is pre-existing boot behaviour and is now named. It self-heals at the next boot if the venue still holds.
- **[LOW] Flag semantics** assume `generate_mass_status` is boot-only. That holds while the periodic checks stay None (pinned).

## Review response
| Item | Resolution |
|---|---|
| Security (a) | Kept: the helper is in neither scope set. |
| Security (b) | Kept: the signature is `(context, report)` only. |
| Security (c) | Strengthened: test 5 proves no report and no native event on any cache-miss path. |
| Arch 1 [HIGH] premise | Accepted. Traced in the boot trace section. Booking removed from scope. |
| Arch 2 [HIGH] guard | B-guarded evaluated and rejected; the architect's own fallback, A, adopted with a named latch. |
| Arch 3 [MED] mass-status side effects | Moot: no runtime mass status. The shutdown skip is not reachable. |
| Arch 4 [MED] periodic and timing | Test 10 cites the existing pins. The resolver-vs-boot window is handled by the flag (test 7). |
| Arch 5 [LOW] fee θ at discovery time | Moot at runtime. At boot it is the pre-existing documented upper bound (`client.py:3320-3325`). |
| Arch 6a–6c | Tests 2, 3 and 4. |
| Arch 6d | Test 10. |
| Arch 6e | Not applicable (no native reconcile call). Test 5 covers the no-send property. |
| Arch 7 node_config lines | Corrected: the trade node is `node_config.py:958` (cache) and `:966` (exec engine). |

## LESSONS
- **L-1/L-11:** native boot reconciliation is shown to already cover the position.
- **L-12:** one row, equality kept.
- **L-18/L-47:** no double booking and no phantom position.
- **L-33:** mutation-checked pin.
- **L-36:** no second POST.
- **L-42:** fixtures via `record_fill`.
- **L-43:** full gate after merge.
- **L-44:** each terminal shape and both legs.
- **L-46:** the helper is not disguised, and the SENDER-REF control is stated.
- **L-51:** no uv, pip or stash.
- **Invariants:** `allow_short` untouched, no operator values, no weakened tests.

## Confidence
- Boot trace: **high**. Read from the installed `execution_engine.py` and from `client.py` at HEAD.
- Design: **high** for correctness, because A books nothing and so cannot misbook. **Medium** for alert timeliness (Risk MED), pending the reviewer's ruling.

## r2.1 (coordinator, 2026-09-26): round-2 reviews merged

**Architect: REQUEST_CHANGES (small; no further round needed).** The boot trace holds against the code:
- `kernel.py:1022-1029`.
- Mass status is boot-only; its only native caller is `execution_engine.py:1710`.
- The race fails in the safe direction: `_resolve_accept_fill` is sync, and `record_fill` precedes the check with no await in between.
- AC6 holds **only if** `_BOOT_PASS_REFUSAL_LATCHES` lands. Otherwise the sum at :3198-3200 raises KeyError, which reaches the outer except at :2887 and blinds the boot. This makes `_BOOT_PASS_REFUSAL_LATCHES` load-bearing.

**Silent-failure-hunter: delivery INADEQUATE.**
- `component_health_watch` re-polls only on native `ComponentStateChanged` transitions (`:229,261-315`) and has no timer. A runtime latch can sit unalerted until the next boot.
- `_latch_reconciliation_refusal` only logs a WARNING.
- Separately, if boot `generate_mass_status` raises before `_durable_reconciliation_pass` (`client.py:2887-2904`), a T1-deferred fill gets the generic `_refuse` fallback and no named latch.

**Contradiction resolved.**
- The architect rules the delay acceptable because this is a LOW attribution gap: the position is visible, and T2-held is already alerted at boot via `RECORD_VENUE_DISAGREEMENT`.
- The hunter is right that the watch has no runtime delivery.
- Resolution: the new latch is **informational, NOT a control**. Its docstring, and the AC, say so explicitly. Runtime delivery for ALL runtime latches is a pre-existing, cross-cutting gap, so it gets its own row, **FU-8b** (a periodic re-poll of the existing `refusals()`/`emit_alert` closure via a native Nautilus clock timer in the composition root; never a synthetic `ComponentStateChanged`, which would spoof a native event).
- Risk [MED] → [LOW].

**Folded changes.**
1. **AC2 rewritten.** A T1 deferral ends in exactly one of these boot outcomes:
   - booked (records explain the position);
   - `RECORD_VENUE_DISAGREEMENT`;
   - `FEE_COEFFICIENT_AMBIGUOUS`;
   - `POSITIONS_READ_FAILED`;
   - settled/flat (nothing held, nothing latched; accepted in writing, because a settled market has no position to attribute);
   - the boot mass status itself failing into the generic `_refuse` fallback. This is pre-existing and named as a residual under FU-8b.

   Test 1 gains two cases: T1 on a settled market (nothing booked, no latch, INFO only) and T1 with disagreement (`RECORD_VENUE_DISAGREEMENT` latched).
2. **T1/T2 asymmetry for settled markets is ACCEPTED.** T2 still latches `resolver_fill_not_booked` on a settled market. That latch is informational: it tells a reviewer a fill landed after the snapshot.
3. **Naming.** The latch value is `"resolver_fill_not_booked"` (lowercase, matching :456-464). The detail is `"RESOLVER_FILL_NOT_BOOKED"`.
4. **New guard test.** Every entry in `_BOOT_PASS_REFUSAL_LATCHES` has a `refusals_<latch>` field in `_RECONCILIATION_COUNT_FIELDS`, and `resolver_fill_not_booked` has none (so the counts line stays byte-identical).
5. **Edge case named.** If the kernel's connect timeout aborts before reconciliation (`kernel.py:1024-1025`), a T1 deferral lands on the next boot. The durable record survives, so this is safe.

**STATUS: CONVERGED.**
- Security: APPROVE, with conditions (a)–(c) kept.
- Architect: its REQUEST_CHANGES items are folded in, and it asked for no further round.
- Hunter: its finding is routed to FU-8b.
