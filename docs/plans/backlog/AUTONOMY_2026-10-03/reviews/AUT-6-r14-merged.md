# AUT-6 r14: merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| silent-failure-hunter | 88 | NOT READY (1 HIGH) |
| trading-bot-architect | 94 | NOT READY (MEDIUMs) |

The architect re-probed on the host (`claude-review-a`, since removed). The results:

- `OnFailure=` fires on **every** watchdog failure, even with `StartLimitIntervalSec=0`.
- With `WatchdogSignal=SIGTERM`, the unit ends with `Result=watchdog`.
- The notifier reads `SubState=auto-restart` and `NRestarts` 0, 1, 2.
- `ExecStopPost` sees `SERVICE_RESULT=watchdog`.

The native-first ruling is applied faithfully. No hard invariant is touched. O-8 (recorder `StartLimitIntervalSec=0`) is JUSTIFIED (the 2026-09-09 incident).

## Cross-plan coordinator rulings (bind AUT-6 r15 AND AUT-1 r10)

- **X-4 (per-kill page is native).** Each recorder watchdog kill is paged through `OnFailure=breezy-autonomy-failed@%n.service`, which is AUT-6's notifier. For a member with the start limit disabled, the notifier pages on `SubState=auto-restart` + `Result=watchdog`, keyed `(unit, InvocationID)`, with delivery proof.
  - AUT-1's `ExecStopPost=` stop hook loses its paging duty.
  - The hook is either deleted, or kept as evidence only (it writes the stall record). The AUT-1 r10 planner decides which, with a justification.
  - #21's fallback dedupe simplifies to match.
- **X-5 (READY is not gated on counters).** `READY=1` is sent once the feed is connected and subscribed. Only `WATCHDOG=1` is gated on the advancing counters. AUT-1 owns the sender.
  - AUT-6's §3.5 contract and test state this rule.
  - Required test: a quiet-feed start does not time out.
- **X-6 (storm escalation).** The 3rd watchdog kill in a trading day sends one deduplicated CRITICAL, `watchdog_restart_storm`. After that, per-kill pages drop to WARN until the day rolls. AUT-6 #21 owns this.
- **X-7 (deferral is paged).** The first launch-window deferral of each stall sends a delivered WARN. Alternatively, #21 reports a `deferred` verdict. AUT-1's gate journals the deferral; AUT-6 delivers the WARN.
- X-1 to X-3 (from r14) stand.
- **Errata dedupe.** E-11 is the single vehicle for ARCH §4.5/§4.6 SELF_HEAL wording. AUT-1's ER-8 is withdrawn in favour of E-11, except for AUT-1-only text on the recorder unit.

## Owed in AUT-6 r15

- **DH1 [HIGH, SFH].** Apply X-5. Also add `TimeoutStartSec` reasoning against the 09:00Z rotate `try-restart`, and extend R-40 to cover a withheld READY.
- **DM1.** Apply X-4: the notifier branches, the per-kill page through `OnFailure`, and the simplified fallback.
- **DM2.** Notifier state handling:
  - For any state other than `auto-restart` or `failed`, check `NRestarts`/`Result` and page anything that is not provably a pending restart.
  - A `failed` state is sticky, so exhaustion is never missed.
  - Measure, or state as a bounded reading, the coalescing case.
- **DM3.** Apply X-6 (storm).
- **DM4.** Apply X-7 (deferral WARN).
- **DM5.** The exhaustion branch has no real-unit member today. State this, and give it a scratch-unit proof plus a real-unit "unreachable while interval 0" test.
- **DM6.** Remove the orphan clause at #28 (line ~412: "`gated_timer_enabled_early`… probe… Y4").
- **DL1.** Add a detector for a gate that always pings: an independent capture-counter cross-check versus `WatchdogTimestamp`.
- **DL2.**
  - Soften or measure "any finite limit would bring that failure back".
  - Fix the SIGTERM exit-shape text in §3.9 (`killed/TERM`).
  - Cite AUT-1's `capture_stall_drill_cli` as the natural SELF_HEAL live proof (O-9).
- **E-11 AMEND.** In ER-1:
  - Use the generic wording "sends `WATCHDOG=1` only while its liveness counter advances"; the recorder becomes a recorded exception.
  - Use the cap row "a member with the start limit disabled by recorded incident is bounded by its restart backoff, pages every watchdog failure through `OnFailure=`, and escalates to one storm page after 3 failures in a trading day".
  - Add: "the notifier pages any state it cannot prove is a pending restart".
- **E-11 ER-5 AMEND.** Append "and the gate journals and alerts WARN once per deferred stall".

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
