# SUP-RESTART-ANYTIME r2: merged blind review (2026-10-03)

| Reviewer | Score | Verdict |
|---|---|---|
| silent-failure-hunter | 86 | NOT READY (1 HIGH) |
| trading-bot-architect | 90 | NOT READY (MEDIUMs) |

## Verified OK

- `SHADOW_DECISION` is data-driven (`strategy.py:713-770`, `:577-581`). A reconnect loop cannot emit it.
- Each spawn writes its own log, so a mark is post-boot.
- Check 5 (permit `expires_at_ns > now_ns` on the marking poll) is correctly placed.
- The flock races at 16:50 and 16:55 are sound.
- The step has no spawn, signal or store-write port.
- No hard invariant is touched.

## Owed in r3 (binding)

### SH1 [HIGH SFH / MED TBA]: delivery claim is false

`_send_permit_alert` (`trade_supervisor.py:958-974`) returns True unless `sink.emit` raises. `TeeAlertSink.emit` (`health.py:~364-366`) swallows webhook failures in `emit_alert`. T16b pins a raising sink, which production never uses.

Coordinator ruling:
- Correct the claim to "logged locally; webhook best effort".
- **Re-fire** the CRITICAL every 60 polls while deferral continues, until the mark or a terminal verdict.
- Add a test against the real `TeeAlertSink` with a failing webhook.

Do not build a new delivery mechanism in this plan. If an existing delivery-proof helper exists in the code (search for `deliver_with_proof`/outbox), cite it and use it only if it is already shipped.

### SM1 [MED SFH]: `LOG_NOT_CURRENT_DAY` after a supervisor restart is unpaged

A D-1 node with a live permit stays silent. Count it as a deferral so it reaches WARN and then CRITICAL.

### SM2 [MED SFH]: deliberately unarmed node

`orders_not_requested_seen` gives a false WARN and CRITICAL. Add a terminal `NOT_REQUIRED` verdict, matching B1, and give it a test.

### SM3 [MED both]: liveness marker

The depth-truncation WARN fires only when the cumulative count is 1 or a multiple of 100 (`data.py:1873`, `:555`). It is lumpy and is not a frame signal.

Coordinator ruling:
- Use **`SHADOW_DECISION` only**. Drop the depth marker.
- State the evidence honestly: 3 FQ days, max gap 15.1 s; 600 s gives a ≥39× margin.
- A node without the FQ family never marks. It is paged through SH1/SM1, which is honest fail-loud behaviour, and this is named as a residual.
- The PR re-measurement splits days by signal source and is a **merge-blocking checklist item**.

### SL1 [LOW]

- `latest_liveness_line_ns` uses the last *parseable* occurrence within a bounded scan.
- Check 9 is vacuous. State that the real guarantee is the pid→log binding (`find_adopted_node_log`) and test that binding.
- T14 uses the real `IncrementalLogReader`, including `read_from_start_and_mark_consumed`, to cover the 2 MiB cap and carry path.

## Approval bar

Both reviewers ≥95 and zero CRIT/HIGH.
