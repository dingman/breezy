# AUT-2 r5: merged (coordinator). PM 95 READY; SFH 93. Final 93 → r6. Zero CRITICAL, zero HIGH.

- **Q1, memory sizing. Both reviewers raised it, so it is the main item.**
  - Stop borrowing the scorer's 4.2 GB peak.
  - WP6 measures the label run's own peak first: cgroup `memory.peak` on a transient `systemd-run` against the real exec store. Size `MemoryMax` as the measured peak × 1.5, rounded up to 1 GiB, with a ceiling at the AUT-6 budget. The target is ≤4G, which makes the V14 hold moot.
  - Replace the borrowed-constant test with `test_label_unit_memory_max_from_measured_label_peak`, which reads the measurement artefact.
  - Where a hold still applies, emit an explicit HEALTH line `label_timer_held cause=memory_gate`, delivered through the outbox with delivery proof. Name the ING-2 S3a owner and deadline.
  - The proof-window tests assert that the window has not started while the timer is held.
  - Forbid a hand-run label unit as a workaround.
- **Q2:** list ING-2 S3a as a named upstream in §0 and the §6 ETA.
- **Q3:** define an intraday INCONCLUSIVE streak: N consecutive slots raises a CRITICAL. Add a test.
- **Q4:** name the `OnFailure=` target for the reconcile units, either a generic `breezy-unit-failed@` or the existing alert path. Add a test that delivery happens when the post-STOP unit is killed by timeout.
- **LOW:**
  - L1: if the `--record-skip` journal write fails, exit non-zero.
  - L2: guard the `Persistent=true` catch-up of `breezy-score-live-trials.timer` against [16:30Z, 17:10Z) and 01:00–04:30Z, with a test for the catch-up case.
  - L3: document dedup across the two locks.
