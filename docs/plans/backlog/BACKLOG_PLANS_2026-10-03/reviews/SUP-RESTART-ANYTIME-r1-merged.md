# SUP-RESTART-ANYTIME r1: merged review (coordinator)

Scores: TBA 92, SFH 84 (one HIGH). Final score: 84, so the plan goes to r2.

- **S1 [SFH HIGH]: proof of liveness.** The mark requires a fresh post-boot activity signal, not merely log growth. Count only non-error lines, or use a pinned positive line, for example a data-frame or heartbeat line already emitted by the node; name it from code. Re-check `expires_at_ns > now_ns` on the same poll that marks. A retry-looping node, or one whose permit has lapsed, never marks.
- **S2 [both]: measure log advancement (Stage 0).** Measure 7 days of node-log gaps, including the quiet window 00:00–01:00Z. This is a **STOP gate**: if gaps exceed the poll interval, switch the design to a multi-sample or threshold proof before building. State the B1 poll cadence.
- **S3 [SFH]: deferral alerting.** After N consecutive non-terminal deferrals (CT13 None, HOLDER_UNPROVEN, LOG_NOT_ADVANCING, a persistent `log_size` OSError), raise a one-shot WARN, then a CRITICAL through the existing supervisor alert path with delivery. Dedupe per child. A persistent OSError must be logged and counted.
- **S4 [TBA]: anchor before marking.** The step requires `first_boot_permit_expires_at_ns` to be latched before it marks, otherwise it defers. Add T15 variants for adoption via `_do_launch` and via SELF_CHECK.
- **S5 [TBA]: activation hold.** Drop the "hold activation until 17:10Z" hedge, or tie it to a stated measurable condition. It contradicts the goal.
- **S6 [TBA]: tests against real code.** T14 asserts invariants from the real `next_due` and `_do_launch`. Add real-flock variants at 16:50 and 16:55.
- **LOW:**
  - The rollback restart window is stated explicitly.
  - A test proves the old and new `_NODE_LOG_NAME_RE` match identically, and the choice is pinned.
  - Re-verify STOP's alert path.
