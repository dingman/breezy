# AUT-1 r5 merged review

Merged by the coordinator. trading-bot-architect scored 95 (READY); silent-failure-hunter scored 93. The final score is 93, so the plan goes to r6. There are zero CRITICAL and zero HIGH findings.

- **T1 [sfh M1] Heal-alert retry.**
  - On its next probe, the watch re-sends every heal record that has no matching delivered record. It exits 1 if the send still fails.
  - The roll-up reports `heal_alert_undelivered` explicitly.
  - Tests: `test_undelivered_heal_alert_is_resent_next_probe` and `test_rollup_reports_heal_alert_undelivered`.
- **T2 [sfh M2] NBP actor outbox wiring.**
  - Gate the WP4 activation on WP8 so that the outbox is wired before the actor can heal.
  - Also, if the outbox is absent at heal time, the actor logs CRITICAL and writes the heal record with `alert=undeliverable`, which T1 retries.
  - Add a test.
- **T3 [sfh M3 + tba M1] Strategy-thread fsync.**
  - **Coordinator ruling:** refusal-payload puts move to the async option (b), off the event loop. This keeps the merge-time p99 budget on the take path only.
  - The take path keeps its benchmark budget. A runtime out-of-process guard is added: the AUT-6 liveness detector (node log mtime plus tape advance, an existing ARCH member) is named as the stuck-disk signal, and AUT-1 asserts the dependency.
  - Add `CAPTURE_REFUSAL_PATH_P99_BUDGET_MS`, or document that refusal puts never block.
  - Tests cover each of these.
- **T4 [tba M2] Event-string contract.** Add a contract test against the real AUT-6 `deliver_with_proof`, checking that the `event` string is verbatim and filename-safe.
- **LOW items.**
  - **L1:** state that AUT-2 and AUT-4 read `eval_seq` from the stored record and never re-derive it.
  - **L2:** the watch, settlement, drill and drill-guard CLIs exit 1 on a failed delivery.
  - **L3:** an R2 test replays the reorder ordinal range (1,000,000 and up) and the 4-entry window identically.
  - **L4:** pin the `launched pid=` journal text with a test against `trade_supervisor.py:1300`.
