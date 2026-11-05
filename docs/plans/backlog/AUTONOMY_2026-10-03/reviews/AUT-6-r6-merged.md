# AUT-6 r6 merged review (coordinator)

silent-failure-hunter scored 93 and trading-bot-architect scored 94, with zero CRITICAL and zero HIGH findings. Final score is 93, so the plan goes to r7.

- **U1 [both reviewers]:** do not enable the probe timer while SELF_HEAL is ALERT_ONLY. Enable it only after AUT-5b maps #21; the probe also checks the mode and skips with an INFO line if the mode is ALERT_ONLY. Test this. There must be no weekly false CRITICAL.
- **U2 [sfh]:** the second invocation writes HEALED only if a selfheal record exists for the prior InvocationID, and writes UNHEALED otherwise. Test this, including the reboot and manual-start cases.
- **U3 [sfh]:** the probe's SIGTERM handler exits 0 with no state write. Widen the RuntimeMaxSec margin, using 1800 or making the 1500 limit cover the whole run including the final write. Test this.
- **U4 [tba], coordinator correction:** "ING-2 S3a" does not exist. The real upstream is **ING-2-AMEND2** (docs/core/PROGRESS.md:52), the removal of `zz-memory-containment-TEMPORARY.conf` after the ≤2G memory.peak proof. Cite it by that name and line everywhere. Do not invent an owner or deadline; 2026-10-16 is AUT-6's own #31 escalation constant, not an ING-2 deadline.
- **U5 [tba]:** pin `AccuracySec=1s` on every slot-critical autonomy timer, with a test, and restate the slot arithmetic.
- **LOW:**
  - **S4:** the rotate must have started after the stored InvocationID's ActiveEnterTimestamp.
  - **Supervisor restarts:** use a named build-side marker so a merge restart pages WARN rather than CRITICAL.
  - **Oneshot count:** the test derives it from the unit files rather than hard-coding 19 or 20.
  - **Drill-probe HUNG:** record the HUNG-by-elapsed classification as observation O-3 in §11.
