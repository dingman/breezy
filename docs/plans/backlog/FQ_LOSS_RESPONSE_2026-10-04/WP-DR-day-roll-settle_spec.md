# WP-DR: day-roll settle fix (standalone; K-neutral). Spec, 2026-10-10

This spec comes from EXEC-PAR r3 §5 (WP-DR) and the three r3 reviews:
- `reviews/EXEC-PAR-r3-review-{architecture,market,safety}.md`.

The coordinator resolved the reviewers' contradictions as recorded below. The defect is **live today at K=1**, while orders are off. It is independent of EXEC-PAR.

## Defect

`DailySpendLedger._require_open_booking` (`operator_controls.py:438-447`) raises `LiveTradingPermissionError` for any booking whose `day` differs from `utc_day_for_ns(now_ns)`. The resolver calls `true_up_booking` on bookings that may be from a prior day, at three sites:

- `client.py` ~:3231, the zero-fill path. It runs after `_retire`. The raise skips:
  - the permit restore;
  - `generate_order_canceled`;
  - the last-statement AMBIGUOUS clear (~:3274). The refusal then stays until respawn.
- ~:3408, the accept-fill path. It runs **before** `_retire` (~:3429). The intent stays OPEN with a fill record written. On the next pass the booking is None, and the global `_RESOLVER_FILL_UNBUDGETED` is latched.
- ~:4072, the no-id path. It runs after `_retire`, so the refusal clear is skipped.

Re-verify every line number against the code before editing; they drift.

## Fix (coordinator rulings)

1. **Day skip, not a catch-all.**
   - At each of the three sites: if `booking.day != utc_day_for_ns(now_ns)`, skip the ledger call and log INFO with the intent id, the booking day and today.
   - **No blanket `except LiveTradingPermissionError`.** Same-day ledger integrity errors must keep escalating exactly as today: over-cost true-up, double true-up, unknown booking, clock backwards.
   - Rationale: safety #1 and market W-1 outrank architecture HIGH-1's alternative.
2. **Firewall row.**
   - `utc_day_for_ns` becomes a new named row in `EXEC_RESOLVER_PERMITTED_CALLEES` (`tests/unit/test_execution_egress_firewall_guard.py`). Keep `==`.
   - It is a pure date function with no egress. Check it against the banned-word scan.
   - No other allowlist change is allowed. If the implementation needs one, STOP and report.
3. **Fill discovered on a new day against a prior-day booking (accept-fill path).**
   - Today's in-process ledger cannot count this spend: there is no additive API, and `seed_spent` is one-shot.
   - Treat it as **unbooked**. Latch the existing global DURABLE `_RESOLVER_FILL_UNBUDGETED` refusal, through the existing code path or condition, still not for SELLs.
   - That is fail-closed. A respawn re-seeds the spend correctly, by the fill's `ts_event` day, which the resolver stamps as discovery time.
   - The zero-fill and no-fill paths carry no spend, so skipping the call is complete for them.
4. **No new `self._refuse` call site.** The 25-site producer pin must not move. Reuse the existing UNBUDGETED producer.
5. **Pins.**
   - `_EXEC_CLIENT_SHA256` is re-pinned only after `python-reviewer` and `prediction-market-reviewer` approve the diff, by the coordinator, in the merge commit.
   - The implementer must **not** edit the pin.

## RED tests (`tests/unit/test_polymarket_us_exec_client.py`, injected clock; extend `ambig_latch_rig` if it lacks clock control)

- `test_zero_fill_retire_after_midnight_cancels_clears_refusal_and_restores_permit`: AMBIGUOUS POST at 23:59Z, zero-fill retire at 00:03Z.
- `test_no_id_no_fill_after_midnight_clears_refusal`
- `test_accept_fill_after_midnight_retires_once_and_latches_fill_unbudgeted`: retires exactly once; does not stay OPEN; UNBUDGETED is latched.
- `test_same_day_over_cost_true_up_still_escalates`: the existing behaviour is unchanged.
- `test_same_day_paths_unchanged`: golden.
- `test_later_same_day_authorize_after_skip_raises_nothing`: the stale booking is pruned on the next roll.

## Gates

Run the focused list:
- the firewall guard;
- `test_polymarket_us_exec_client.py` and `test_current_rung_hold_ambiguous_resolver.py`;
- `test_submit_intent_latch.py`, `test_edge2_ac6b_cross_process_fill_budget.py` and `test_exec_refusal_health_surface.py`;
- `test_operator_reserved_controls.py`;
- `tests/contract/test_live_fill_scoring_chain_contract.py`;
- all `test_autonomy_*`.

Also run `lint-imports` from the tree cwd and `ruff` on the touched files. mypy stays at or under its ceiling, with no `Any`, `cast` or `type: ignore`.

The only expected red is the `_EXEC_CLIENT_SHA256` pin; report it, but do not fix it. The full gate runs after the re-pin, at merge.
