# FAILURE-KIND-DURABLE — plan r2 delta (binding amendments to r1)

**Reviews:**
- architect: REQUEST_CHANGES, confidence 75.
- python-reviewer: READY-WITH-AMENDMENTS, confidence 78.

They agree on the core: a trailing optional field on the durable ambiguous-intent context, where old code ignores the extra key, so rollback is safe.

1. **No `_retire` change.** Drop the clearing step and `test_retire_clears_durable_failure_kind`.
   - A context is read only for the currently OPEN intent.
   - `_retire` is a shared D9 exit, called from `_submit_order` (`:5564`, `:5652`, `:5665`) and permitted in BOTH `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` and `EXEC_RESOLVER_PERMITTED_CALLEES` (`firewall_guard:1955-1956`, `:2156`). Touching it widens the order path.
   - RED: `_retire`'s body AST is unchanged, and the order-coroutine allowlist is untouched.
2. **Helper discipline (L-48).** The new helper:
   - writes only when the kind CHANGES (the reset at `:2738` runs on every successful GET);
   - is synchronous and never awaits;
   - is wrapped in try/except that logs and never raises into the resolver.

   RED: a store that raises leaves the resolver alive and the intent AMBIGUOUS-resolvable.
3. **Firewall (L-12).**
   - Widen the E0-NOSEND-RESOLVER exact set by exactly one callee, the new helper, keeping equality.
   - Add an AST shape test mirroring `record_venue_order_id`: the helper reaches `_store_set` only on the resolver key prefix (`client.py:~452`) with a single key.
   - RED: a variant helper writing an arbitrary key is rejected by the shape check.
4. **Added tests.**
   - Rewriting the context keeps every other field byte-identical (`orderSide`, `createFillEvidence`, …).
   - After seeding from the durable kind on boot, the r2/r3 cause follow-up (`:2578`) does not fire a second time for the same kind.
   - L-42: the restart test writes its fixture through the real `_note_ambiguous_open` path and reads it back through the real resolver. There are no hand-built rows.
5. **Merge order.** This merges BEFORE BL-10. BL-10 rebases onto it, and the full gate runs after each merge. It loads at the next node spawn.
