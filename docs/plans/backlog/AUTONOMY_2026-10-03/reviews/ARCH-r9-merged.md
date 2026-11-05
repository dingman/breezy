# ARCH Rev 9 freeze review: merged (coordinator). architect 92 (1 HIGH), trading-bot-architect 92 (0 HIGH), security-reviewer 88 (1 HIGH). Final 88.
Duplicates merged; no contradictions. Rev 9.1 is a targeted patch.

## HIGH
- **U1 [arch D1, sec N4]: the d0 rule.** It binds only the family's FIRST PROMOTE, DRILL_PROMOTE or ROOT_ADMIT row. ROLLBACK and RESUME of a family that has already been CHAMPION are exempt. The resolver checks against that first row. Add `test_rollback_to_earlier_child_passes_d0_rule` and `test_resume_not_subject_to_d0_rule`.
- **U2 [sec N1, tr D6, arch D2]: ROOT_ADMIT gating.**
  - Add a policy-block key `root_admit_enabled`, default false, with a pins ceiling.
  - Add `ROOT_ADMIT_COOLDOWN_H` ≥ 24 after any TERMINAL event on the venue.
  - Require a fee-verified AUT-6 PASS, and an engine-held record that no operator-set (A1 `policy_halt`) halt stands on the venue.
  - Add `test_root_admit_refused_after_operator_halt_within_cooldown`.
  - Add ROOT_ADMIT to the "widening kinds" list, the §4.4 preconditions, the Y6 required columns and §4.1.

## MEDIUM
- **U3 [tr D1, sec N2]: outbox claim recovery.**
  - The boot drain and the dead-man reclaim `claimed/*` entries older than `ALERT_OUTBOX_STALE_S`.
  - A claimed file is removed only after its delivery record is written.
  - Fsync the directory after the write and after the rename.
  - Delivery is at-least-once.
  - Add a kill-between-claim-and-send case to `test_critical_survives_sigkill`.
  - The dead-man row reads "read-only except outbox drain". List the outbox in the one-writer test as write-once plus rename-claim [arch D4].
- **U4 [tr D2, sec N3]: post-STOP positions read.**
  - Name the credential source.
  - The module sits under `src/breezy`, inside the §4.3 pin closure, and outside `persistence.autonomy`.
  - It uses a transport that exposes only `get_authenticated`, with the endpoint literal pinned via `validate_endpoint` and no query parameters except the cursor.
  - Add a cursor loop with a page cap.
  - Extend `test_poststop_venue_read_is_get_only`, and add the module to the NO-SEND guard's coverage.
  - Record the L-1 check of why a node-side `on_stop` PositionMark snapshot is insufficient as venue truth (it is node belief).
- **U5 [tr D4]**: Name the venue-net source for the intraday RECONCILIATION producer. Node-derived marks are tagged `reconciliation_source=node_belief`.
- **U6 [tr D5]: the 14G study cap.** State the measured peak per study. Either raise the cap for named studies that run outside the live window and outside any other heavy slot, or declare those studies out of scope. Do not let the hard cap silently OOM-kill a scheduled study.
- **U7 [sec N5]**: DRILL_INJECT opens the marker relative to a verified directory descriptor. ENOENT on the directory itself is ERROR.
- **U8 [P1-13, arch, tr]**: Add `derived/capture_payloads/quote/<sha>.json` (ask, bid, ts_event). The C1 DecisionRecord requires `depth_ref` OR `quote_ref`.

## LOW
- **U9 [P1-14]**: `eval_ns` = the decision's event time (`ts_event`). Add a separate `wall_ns` field.
- **U10 [P1-15]**: C4 sanctions `INCONCLUSIVE` with `metrics.day_status=NO_INPUT`.
- **U11 [P1-16]**: `try-restart` of an ACTIVE allowlisted recorder classified HUNG is permitted.
- **U12 [tr D3, arch D3]**: Canary rows in §5.2 are scheduled canaries only; retries are suppressed until 17:10Z.
- **U13 [sec N6]**: Validate demand-file `family_id` and `reason` against the fold and the closed enum. Rejected-verdict demands are archived.
- **U14 [sec N7]**: `build_child_env` strips or pins an inbound `BREEZY_FAMILY_SOURCE`.
