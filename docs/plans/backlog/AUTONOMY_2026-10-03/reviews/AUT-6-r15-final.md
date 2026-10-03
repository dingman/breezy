# AUT-6 r15: FINAL (APPROVED 2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| silent-failure-hunter | 95 | 0 |
| trading-bot-architect | 96 | 0 |

**Plan.** `AUT-6-drift-health_plan_r15.md` is **READY**. It supersedes r13 as the AUT-6 build plan.

**Errata.** E-11 is ADOPTED in `ARCH-ERRATA-rev9_2.md`.

**Re-probe.** The architect re-ran a throwaway unit, `claude-review-b`. It reproduced §0.1 (31) and (36). On exhaustion, the unit ends `failed` with `Result=watchdog` and `NRestarts=2`.

## Binding build items

Brief these together with the plan, `reviews/AUT-6-r13-final.md`, and the errata.

1. **Storm tail.** While kills continue after the storm page, re-send one CRITICAL `watchdog_restart_storm_ongoing` every 6 h, reusing the marker mechanism. Kills 4 and later must never page only WARN for the rest of the day (SFH LOW-1, TBA LOW-1).
2. **Real unit values.** `test_notifier_worst_end_below_member_min_failure_interval` is parameterised on each member's real unit-file values: `RestartSec`, W and `TimeoutStartSec`. Range bounds alone are not enough.
3. **`member_start_timeout`.** Dedupe per trading day after the 3rd page. The 1st and 3rd stay CRITICAL.
4. **Dropped-trigger latency.** R-42 states the worst-case latency of the #21 fallback when a trigger is dropped while the notifier runs.
5. **`GATE_CROSSCHECK_FLAT_S` fails closed.** If V-W5 has not pinned it, the check fails closed and never falls back to a default.
6. **Cross-plan dependency.** The recorder-side deliverables belong to AUT-1 r10: X-1..X-5, X-7, and the rotate `TimeoutStartSec` of at least the measured sum + 30 s. AUT-6 WP4 tests gate them.
7. **(Added 2026-10-03, from the AUT-1 r10 review MED-1.)** AUT-6's unit-health checks and its liveness checks (#21, #22, `watchdog_disarmed`, the gate cross-check) must treat the recorder's `ActiveState=activating`/`SubState=start` as healthy. That holds for as long as the recorder's own `TimeoutStartSec` allows, per AUT-1 r11 a max start of 4500 s with `EXTEND_TIMEOUT_USEC` during the listing hole, inside a rotate bound of 4680 s; both derive from `QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS`, so read the constant and never hard-code it. Required test: `test_unit_health_tolerates_activating_within_member_start_budget`. Its positive control is a recorder still `activating` after `TimeoutStartSec`, and that case must page.
