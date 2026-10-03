# AUT-6 r4 (final round): merged (coordinator). silent-failure-hunter 94, trading-bot-architect 92. Final 92; zero CRITICAL or HIGH. Polish to r5.
Duplicates merged: sf 6 and ops 4 (wall time), and sf 8 and ops 6 (short-timeout units).

- **F1 [sf 1]**: Add a write-once `alerts/armed.json`, written on the first delivered canary and read by #5. Both directories absent while armed means veto. Test that the marker survives a 3-day gap.
- **F2 [sf 2]**: Each pass reconciles `systemctl --user list-units --failed` against the journal-derived invocations. Any in-scope failed unit missing from the journal read means UNKNOWN plus a `journal_blind` finding. Test it.
- **F3 [sf 3]**: Any INTEGRITY demand write error (ENOSPC, EACCES, slot) sends CRITICAL `integrity_demand_write_failed` through `deliver_with_proof` and counts in #23. Add a RED test.
- **F4 [sf 4]**: When the fold is unreadable, write #26 FAIL under `_host/` and alert directly. The pass counts in `passes_unknown_streak`.
- **F5 [sf 5]**: Reserve 16 outbox slots for `severity=CRITICAL` out of `ALERT_OUTBOX_MAX`. Test it.
- **F6 [sf 6, ops 4]**: WP3 verify-first: the health pass p99 is ≤ 90 s. Test it.
- **F7 [sf 7]**: #22 includes `NRestarts` growth for `Restart=always` daemons.
- **F8 [sf 8, ops 6]**: Oneshot SELF_HEAL membership requires `TimeoutStartSec ≥ 600`. Drop canary, redeliver and intraday from the tuple and their evidence rows.
- **F9 [ops 1]**: For #15, if `max_frame_gap_ns` over [eval_ns, fill_ts] is above 2 s, the result is `INCONCLUSIVE reason=frame_gap`, never FAIL. Add `test_wide_frame_gap_is_inconclusive_not_halt`.
- **F10 [ops 2]**: Each health pass records `MemAvailable`, and the daily #31 verdict uses the 24 h minimum. Add a RED test.
- **F11 [ops 3]**: Identify studies-flock holders by a static scan of `ExecStart`. A `MemoryMax=infinity` is +inf and FAILs. Add `test_memory_budget_infinity_memorymax_fails`.
- **F12 [ops 5]**: Add V-5 on a scratch transient unit: `try-restart` of an activating oneshot, recording `Result` and `InvocationID`.
- **F13 [ops 7]**: #23 evaluates a failed 16:30Z or 16:45Z canary slot only after 17:11Z.
