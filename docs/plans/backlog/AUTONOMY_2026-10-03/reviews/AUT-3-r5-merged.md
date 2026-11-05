# AUT-3 r5: merged (coordinator). prediction-market-reviewer 96 (READY), mle-reviewer 90 (1 HIGH, cross-plan). Patch to r6.
- **I1 [mle HIGH, mle MEDIUM]**: The AM reproduction unit runs `OnCalendar=09:35:00`, `AccuracySec=1s`, `TimeoutStartSec=4139`, `TimeoutStopSec=60`, with no `RuntimeMaxSec`, so it ends by 10:45:00Z (as the READY AUT-4 r6 requires).
  - The fit rule becomes `runtime_s × 1.2 + 600 ≤ 4139`; otherwise queue the lineage for the PM slot.
  - Update §3.7 line ~271, the slot table (~280, ~537) and the end-time statements.
  - Add `test_repro_am_ends_by_1045z`.
- **I2 [pm 1]**: The WP9 pass criterion states that `DENSITY_REPRO=not_claimed` can never raise `REPRO_PASS`.
- **I3 [pm 2]**: The WP7 unit test asserts `WATCHDOG_MAX_PING_GAP_S = 600`.
