# AUT-6 r13: Nautilus/systemd-native pressure test (2026-10-03)

**Verdict: FAIL** (silent-failure-hunter, read-only).
- The plan has zero hits for `WatchdogSec`, `sd_notify` or `Restart=on-watchdog`.
- The repo has no `sd_notify` use.
- Positive control: `Restart=always` appears in `breezy-quote-tape.service:116`.

## Coordinator ruling: native-first r14

**1. Delete the custom restart path.**
- Remove: `self_heal.py::restart_unit`, `SELF_HEAL_RESTARTABLE_UNITS`, the selfheal records and outcome files, the per-day cap and the per-InvocationID idempotency check.
- Replace with: `Type=notify` + `WatchdogSec=` + `Restart=on-watchdog`, plus `StartLimitBurst`/`StartLimitIntervalSec` for the cap.
- The daemon pings `WATCHDOG=1` only while its capture counters advance, as in the AUT-1 r9 design.
- When the start limit is exhausted, `OnFailure=` pages through a delivery-proven notifier.

**2. Delete the drill probe.** Remove its unit, timer, CLI and state file. Prove the mechanism once with a scratch transient unit in WP verify-first.

**3. Narrow the health unit.** It keeps `active`-state and failed-unit detection, but loses:
- the HUNG→restart path;
- the ALERT_ONLY/SELF_HEAL mode machinery tied to it;
- `self_heal_mode_degraded` and `state_lost`.

**4. Launch-window deferral.** If any is still needed, it goes in the watchdog-ping gate, not in an executor.

**5. Keep (justified gaps):**
- `deliver_with_proof`, the outbox, redeliver and the canary;
- the detectors;
- the memory check;
- the discovery-pull redesign;
- E-7a bwrap. `Type=notify` units need `NotifyAccess=all` under bwrap.

**6. ARCH SELF_HEAL wording.** Where ARCH P6-7/§4.5 describes a SELF_HEAL executor, file an errata request with exact replacement text. Under that text, SELF_HEAL is realised by systemd `Restart=on-watchdog`, and AUT-6 counts restarts (NRestarts) and pages.
