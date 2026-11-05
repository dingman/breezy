# ARCH Rev 8 freeze review: merged (coordinator). architect 89, trading-bot-architect 88, security-reviewer 92. Final 88. NOT FROZEN.
**Contradiction resolved:** on the reserved INTEGRITY demand slot, security and trading say add it and the architect says unnecessary. The coordinator rules **add it**: a producer flood must not cause a self-inflicted venue outage. Duplicates are merged.

## HIGH
- **V1 [tr D1, arch 7, P6-17]: outbox durability.** The node CRITICAL outbox is write-once files under `evidence/alerts/outbox/`, written before enqueue. It is drained at boot and by the dead-man. Add `test_critical_survives_sigkill`.
- **V2 [arch 1]: C3 and `refit_run/v1`.**
  - Add `own_outcome_gate_decisions_changed` (int). The writer refuses an own-outcome lineage below `MIN_GATE_DECISIONS_CHANGED`, measured on the envelope probe set against the parent (the README's X22 ruling).
  - Add the outcomes `NOT_FITTABLE(reason)`, `NO_CHANGE(below_delta)` and `MINT_REFUSED_CEILING`.
- **V3 [arch 2, tr D4, P6-15, P6-16]: delivery proof for everything.**
  - Every alert emitted for a C6 detector action or a named failure mode uses `deliver_with_proof`, whatever its severity.
  - Delivery records carry `severity`, `attempt_kind` and `drill`.
  - `alerts_undeliverable` selects on `attempt_kind = canary` or `severity = CRITICAL`.

## MEDIUM
- **V4 [arch 3]**: Add the C5 columns `k_life`, `alpha_k`, `n_min_eff`, `n_cap` and `nomination_feasible`, required on SHADOW→CHALLENGER PROMOTE rows. The k check reads these columns.
- **V5 [arch 4]**: `registry_attest_expired` is armed only by ATTESTs dated after the family's latest →CHAMPION or RESUME row. That first ATTEST is exempt from the cadence limit.
- **V6 [arch 5]: recovery after the KILL or a TERMINAL event.** Add `ROOT_ADMIT`, SHADOW→CHAMPION:
  - only for a committed root with its own allowlist triple
  - only when the venue folds no CHAMPION or HALTED family
  - §4.4 preconditions apply, the 16:45Z pass writes it with its ACTIVATE, and it is counted
  - add tests
- **V7 [tr D2, arch 10]: launch-window table.** List every intraday firing in [16:30, 17:10), or suppress the unlisted ones. Give each an explicit `-w` and end time. Add a 16:47:30 lock-contention case. The 16:57:30 SWAP_CANCEL is best-effort, or the Z8 restore deadline is 17:00Z plus one poll.
- **V8 [tr D3, arch 8, P6-18]**: The restart argv is `["systemctl","--user","try-restart","--no-block",unit]`, with a subprocess timeout, enforced by the AST test.
- **V9 [sec 1, tr D5, P6-14]**: Reserve `DEMAND_INTEGRITY_RESERVED` slots. Producers write one file per (family, reason), idempotent on `verdict_id`, capped at `DEMAND_FILES_MAX − reserved`. A producer overflow alerts and does not veto the venue. Add `test_producer_demand_flood_cannot_exhaust_integrity_slot`.
- **V10 [sec 2]**: Require child `d0_climate_day ≥ effective_launch_date` and greater than every earlier lineage d0. Pin `trial_id_prefix == f"…/{child_id}/"`. Add a RED test.
- **V11 [sec 3]**: Selection and ACTIVATE re-verify both the manifest sha and the artefact sha. A LAUNCH-time byte-binding failure on a newly effective pair writes SWAP_CANCEL with `cause=target_integrity` and marks the target ineligible. Add `test_target_manifest_mismatch_marks_ineligible`.
- **V12 [sec 4]**: DRILL_INJECT: absent means PASS; any other read failure means ERROR, which never resumes. A drill row never overrides an existing non-DRILL halt class (first cause wins).
- **V13 [tr D6]**: Name the post-STOP venue-net source (AUT-2, Wave 0), or state the reviewed egress dependency. A STOP not finished by 16:41 means INCONCLUSIVE, then SWAP_CANCEL.
- **V14 [tr D7]**: Studies get `MemoryMax=14G` and `MemoryHigh=12G`, or record the measured node and recorder RSS in the policy block. AUT-6 HEALTH checks the sum against `MemAvailable`.
- **V15 [P7-12, P7-13]**: Add drill counters `drill_demotes` and `drill_halts` with ceilings, and a `TARGET_INELIGIBLE` row kind (cause `target_integrity`).

## LOW
- **V16 [arch 6]**: C4 (c) is a one-sided paired test with a ruling-set margin, INCONCLUSIVE below `MIN_CALIBRATION_BUCKETS`.
- **V17 [arch 9]**: The one-writer rule allows multiple writer process types serialised by the same named flock, each listed in the test.
- **V18 [sec 5, 6]**: `relaunch/v1` is an exact-set schema. `build_child_env` drops inbound registry keys before setting them. BOOTSTRAP precedes enabling `BREEZY_FAMILY_SOURCE=registry`.
- **V19 [tr D8, D9]**: `promote_enabled` requires `eta_date ≤ KILL − forward_window_days`. State the drill's cost in lost live days. A post-launch SWAP_CANCEL loses the day's entries. Test that the incumbent boot does not deadlock on the child's AMBIGUOUS intent.
