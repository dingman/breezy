# AUT-6 r1: merged review (coordinator). trading-bot-architect 82, silent-failure-hunter 82. Final 82, NOT READY.
Duplicates merged; no contradictions.

## HIGH
- **H1 [ops1]: boot grace.** `node_liveness` must not page between 16:50Z and 17:10Z (the permit line only exists from about 17:10Z). Start the window at 17:05Z, or key a boot-grace rule to the new log's creation. Test the transition.
- **H2 [ops2]: halted-by-design is not a failure.** Read the A1 halt and the venue-champion fold. While the family is halted or not champion, report PASS with `reason=family_halted`. Test it.
- **H3 [sf1; ARCH W13]: canary.**
  - Any `delivered=true` row counts as proof: an inline CRITICAL, a redeliver or a check.
  - Add a second canary slot (for example 16:30Z) and an hourly retry after a failure.
  - Declare the drill's veto cost, or schedule the drill outside the trading window.
  - RED test: one failed canary does not veto the next window.
- **H4 [sf2]: UNKNOWN fails closed.** After N consecutive UNKNOWNs, emit a DetectorEvent and a CRITICAL. A veto detector's persistent UNKNOWN must not read as healthy. Test it.
- **H5 [sf3, ops10]: unit health.**
  - Persist the last-seen InvocationID per unit so a fail-then-succeed between passes is still counted.
  - A `systemctl` or bus error means UNKNOWN, never zero failures.
  - Check timer liveness (`LastTriggerUSec` against the schedule).
  - Run an automated sweep of `run-*` transients outside the scope regex, with an ownership or exclusion rule so other agents' transients don't pollute the metric.
- **H6 [sf4, ops4]: monitor the monitors.**
  - The health unit writes a heartbeat that the dead-man checks. ARCH assigns the dead-man to AUT-5; AUT-6 provides the heartbeat and the delivery.
  - Add a producer-stale meta-detector that is independent of the producer.
  - A missing intraday verdict means an alert, never silence.
  - Exempt the light intraday producer from the [16:30Z, 17:10Z) restart deferral.
- **H7 [sf5]: delivery for every ALERT-class detector.** Assign a severity to each detector (#9, #11, #12, #14, #16, #20, #24). Queue and retry every ALERT-class alert, not only CRITICALs. A write-on-change alert must still be resent after a delivery failure.

## MEDIUM
- **H8 [ops3, sf6]**: Define the tape mtime source (recorder live root versus ingest output). Set the threshold to cadence plus margin (≥1500 s) and justify the log-mtime threshold for a quiet feed. Add a flapping RED test and an all-good positive control.
- **H9 [ops5]**: Add a "daily verdict absent >30 h" detector and a retry slot when the 05:30Z producer misses the flock.
- **H10 [ops6, sf9]: live proof.**
  - Name the natural `permit_lapsed` event precisely, or define an injection path.
  - Start the 7-day window after the AUT-5b ruling date.
  - A missing or stale day rollup fails the day.
- **H11 [ops7, sf12]: HALT class.** Make the drill-HALT ARCH delta (C-4) an explicit blocking dependency owned by ARCH; it is passed to the ARCH revision. Give a fallback proof with a probability estimate and a deadline.
- **H12 [ops8]**: INTEGRITY-class detectors keep the code-fixed HALT proposal as a floor when the policy file is unreadable. Define what protects the venue when the engine marks the verdict ERROR.
- **H13 [sf7]**: The self-heal classifier requires a memory-pressure signal (`MemorySwapPeak > 0` or PSI), not just the CPU/wall ratio.
- **H14 [sf8]**: An outbox write failure is logged, counted and tested.

## LOW
- **H15 [ops9]**: The 14G ingest drop-in plus a 16G study is about 30G on a 31G host. Give it an owner and a deadline, not just "AUT-1's disposition".
- **H16 [sf10]**: Add a named expected-skip counter in the gate for the policy-map test.
- **H17 [sf11]**: `follow_redirects` is off and a 3xx counts as not delivered. Test it.

## ARCH deltas to absorb
- /home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-r4-merged.md:
  - W1: intraday verdicts with 8 h validity and ATTEST every 6 h.
  - W9: node-side delivery off the event loop.
  - W11: a persisted self-heal counter.
  - W12: detectors include drill fills.
  - W13: the canary.
- Systemd: `RuntimeMaxSec` does nothing on oneshot; use `TimeoutStartSec`. Your C-2 is accepted.
