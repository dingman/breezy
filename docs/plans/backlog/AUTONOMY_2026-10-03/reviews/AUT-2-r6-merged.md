# AUT-2 r6: merged (coordinator)
prediction-market-reviewer scored 95 (READY); silent-failure-hunter scored 94. Final score 94, so the plan goes to r7. There are zero CRITICAL and zero HIGH findings.

**Items**
- **V1** (both reviewers): `slot_guard` exits 255 on any internal error and 1 only on a deliberate refusal. Test with a planted ImportError.
- **V2** (PM): `--proof-window` is invoked from `label-outcomes-run.sh`, and the unit-guard test covers it. No hand step.
- **V3** (PM): the WP6 measure run has a precondition, `MemAvailable ≥ 16G + node/recorder RSS`, and aborts otherwise. Delivery is a dry run in that mode, with no real alerts and no real dedup journal (SFH L8).
- **V4** (SFH): post-STOP consecutive INCONCLUSIVE for N=2 days raises CRITICAL through delivery proof. Test it.
- **V5** (SFH): the reconcile units get their own failure notifier, which is CRITICAL, includes the unit name and uses `deliver_with_proof`. Do not depend on an upgrade of the WARN-only `study_failure_notifier`. Match the existing `@%n.service` spelling style.
- **V6** (SFH): set `TimeoutStopSec=5` on every AUT-2 oneshot, include it in the worst-end arithmetic, and add tests.
- **V7** (SFH): the dedup key includes an episode id; an intervening MATCH resets it.
- **V8** (SFH): pin a per-delivery deadline inside the 29 s post-read budget, and test with a hung sink.
- **V9** (LOW, both):
  - Fail closed (hold) on a missing or corrupt `aut6.memory_budget`.
  - Raise an intraday alert when the marker is stale (>26 h) even with zero fills.
  - If sizing exceeds 14G, surface a CRITICAL.
  - Cap MemoryHigh at 12G.
  - The test asserts the bound as stated (≥1.35×peak).
  - Treat the 10-24 and 10-31 dates as the primary path.
