# AUT-1 r6 merged review (coordinator)

Scores: silent-failure-hunter 94; trading-bot-architect 92 with 1 HIGH. The final score is 92, so the plan goes to r7.

## Async payload writer threading
Raised by both reviewers. The tba reviewer rated it HIGH; the sfh reviewer rated it MEDIUM. I have ruled on it as coordinator.

- **W1: loop owns all state.** The payload thread does only the put: write, fsync, link. On failure it posts an immutable failure fact to a `queue.SimpleQueue` and touches nothing else. That means no writer health, counters, `_needs_newline`, dedupe map, marker, journal, `AlertOutbox` or DetectorEvent.
  - The event loop drains the failure queue on the 60 s tick and before every write, then runs the §3.3.3 failure path on-loop.
  - Any lock may cover memory only, never I/O.
  - Test: `test_async_thread_failure_never_mutates_writer_state_off_loop`.
- **W2: stuck and dead detection by age and liveness.** On each 60 s tick the loop checks two things:
  - the age of the oldest pending item, against `REFUSAL_PAYLOAD_MAX_PENDING_AGE_S`;
  - `thread.is_alive()`.

  Either failing raises `DetectorEvent(capture_writer_health, DISAGREE)` with cause `refusal_payload_thread_stuck` or `refusal_payload_thread_dead`.
  - The lifecycle actor owns thread start and stop. WP1 notes that the thread starts in WP8.
  - Tests: one with fsync held blocked, one with the thread killed.
- **W3: benchmark under real fsync load.** Run the 5 ms refusal-path benchmark under real fsync load, for example a concurrent `dd conv=fsync` on the same mount. State the residual journal-contention risk.
- **W4: record ordering (new R-12).** The C1 record may land before its payload. Log this in §11 as R-12. Online readers must tolerate a transient `capture_gap` until `REFUSAL_PAYLOAD_MAX_PENDING_AGE_S` has passed, and only then count it.

## Heal retry
- **W5:** apply the delivery-keyed hourly limit to retries. If a heal record ages past `HEAL_ALERT_RETRY_DAYS` still unmatched, raise a single CRITICAL.

## Low-severity items
- State the AUT-6 stuck-disk detection latency, about 25 min, and that it is acceptable at about 3 Takes a day.
- Optionally let WP4 merge earlier, since the T1 retry and the undeliverable fallback cover the outbox gap. The planner decides; record the reason.
- Require the liveness observation to carry both the log-mtime and tape-advance fields.
