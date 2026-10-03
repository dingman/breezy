# AUT-7 r5 final: READY. Security 95, architect 95, zero CRITICAL or HIGH.
E-5 consumption was judged correct by both reviewers. The cooldown is required by ARCH C5. The outage is fail-safe and replaces a roughly 28-day strand.

Binding on the WP briefs (carried into implementation):
- **MEDIUM (arch):** the restorative RESUME must also refuse when the episode holds an `abandoned` journal record, or when the genuine-fault predicate is true for r0001. Extend `test_restorative_resume_never_for_child_or_after_genuine_fault`.
- **MEDIUM (sec):** give a bounded exit to these cases: a second failure in the episode, `target_load_failed`, and a pre-effect close failure that leaves a HALTED ROLLBACK_FAILED child. Either RETIRE a drill-only ROLLBACK_FAILED family after N days, so that ROOT_ADMIT opens, or document it as an incident-handled residual in K-20.
- **LOW:**
  - Restate the outage bound as ≤48h00m, measured from the C 16:50 LAUNCH.
  - Add the marker sweep to the 16:32:30, 16:37:30 and 16:42:30 rows.
  - E10 always re-runs after an integrity-flag clear.
  - Add E7 to the restorative RESUME conditions.
- **E-7/E-8 (adopted 2026-10-03):** consume per the table in ARCH-ERRATA-rev9_2.md 'E-7/E-8 consumption by plan' (binding build item).
- **E-9 (adopted 2026-10-03):** any multi-command oneshot bounds each command and sums the bounds (ARCH-ERRATA E-9). Binding build item.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
