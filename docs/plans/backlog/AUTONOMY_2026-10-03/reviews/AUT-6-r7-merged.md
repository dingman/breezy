# AUT-6 r7 merged review

Merged by the coordinator. Scores: trading-bot-architect 96 (READY), silent-failure-hunter 94. Final score is 94, so the plan goes to r8. There are no CRITICAL or HIGH findings.

## Findings to fix in r8

- **Y1 [SFH, MEDIUM] Crash hidden by rotate.**
  - **Change:** before accepting explanations (i) or (ii) for an InvocationID change, read how the stored invocation ended (`Result`, `ExecMainStatus`, `ExecMainCode`, from the journal or `systemctl show`). Accept only a systemd-initiated stop, i.e. SIGTERM from systemd.
  - **Rule:** a self-exit or crash is reported regardless of any rotate or selfheal record.
  - **Test:** crash, then auto-restart, then a rotate, all inside one pass interval.
- **Y2 [SFH, MEDIUM] Silent mode flip.**
  - **Change:** persist the last `self_heal_mode` in `seen/`. A drop from SELF_HEAL to ALERT_ONLY emits an explicit `self_heal_mode_degraded` finding with delivery proof and the cause (ruling unreadable or sha mismatch).
  - **Interaction:** #28 does not mis-name this cause.
  - **Test:** add one.
- **Y3 [SFH, LOW] Reboot between heal record and restart.**
  - **Change:** ARMED stores `boot_id`. HEALED requires the same boot and requires that the stopped invocation ended by a systemd SIGTERM.
- **Y4 [TBA, LOW] Over-paging on #28 `gated_timer_enabled_early`.** Make it WARN; it is CRITICAL only if the probe is not self-skipping.
- **Y5 [TBA, LOW] Build-side marker is manual.** Add `--mark-buildside-restart` to the activation checklist and to the supervisor-restart runbook steps.
- **Y6 [TBA, LOW] Mode flip while armed.** State explicitly that a flip to ALERT_ONLY while ARMED ends UNHEALED with a CRITICAL.
- **Y7 [SFH, LOW] Accuracy assumption.** `TIMER_MAX_INTERVAL_S` grace values state the AccuracySec they assume: 1 min for non-autonomy timers.
