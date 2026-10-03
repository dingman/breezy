# ARCH Rev 9.1 confirm: merged (coordinator). architect 93, trading-bot-architect 94, security-reviewer 96 (FROZEN). Final 93; zero CRITICAL or HIGH.
Rev 9.2 is a wording patch.
- **Z1 [arch 1]: d0.** Replace with "≥ the `effective_launch_date` of the child's first →CHAMPION row (PROMOTE CHALLENGER→CHAMPION or DRILL_PROMOTE) that took effect in the fold; a ROOT_ADMIT root is exempt (its d0 is committed)".
- **Z2 [arch 2]**: Define "standing" as an uncleared `policy_halt` key with detail ≠ `fee_schedule_drift` on any family of the venue, cleared only by W15 build-side incident handling.
- **Z3 [tr 2]**: A halt-mirror record that is absent, unreadable or older than `HALT_MIRROR_MAX_AGE_S` makes ROOT_ADMIT refused (fail closed).
- **Z4 [tr 1]: outbox claim.**
  - The claim step calls `os.utime` to set the claim time.
  - Reclaim ages from the claim using `ALERT_CLAIM_STALE_S` (≥ 3× `ALERT_DELIVERY_TIMEOUT_S`).
  - Add a test that two concurrent drainers send at most once per claim window.
- **Z5 [tr 3]**: State the intraday positions-read slot spacing against the shared `portfolio` quota. A quota refusal gives INCONCLUSIVE, never PASS.
- **Z6 [tr 4]**: A failed 16:45Z canary is still recorded, and the 17:00Z dead-man reports it.
- **Z7 [sec 1, arch 4]**: Add ROOT_ADMIT and DRILL_PROMOTE to the §4.4 INTEGRITY-freeze lists. Add ROOT_ADMIT to the 16:45Z-only horizon list.
- **Z8 [sec 2]**: `_validate_endpoint` is renamed public `validate_endpoint` on the move.
- **Z9 [arch 3]**: The triggering event is the handler's event. Add a deterministic `eval_seq` to the `decision_id` hash and `test_decision_id_unique_per_take`.
