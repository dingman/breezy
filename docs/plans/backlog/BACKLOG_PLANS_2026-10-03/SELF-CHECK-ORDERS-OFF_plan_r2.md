# SELF-CHECK-ORDERS-OFF — plan r2 (2026-10-09)

Backlog row: `docs/core/PROGRESS.md` (SELF-CHECK-ORDERS-OFF, LOW, found in the SUP-RESTART review on 10-08).
Scope: supervisor self-check classification only. No node, exec-client, permit, cap, enablement, or drop-in change.
Author: planner agent (no write tool); saved verbatim by the coordinator. Status: READY r2 (r1 + peer-review amendments A1–A9 below; architect D2 APPROVE, python-reviewer READY-after-amendments).

## 0. Premise (verified from the live journal, 10-08)

```
2026-10-08T17:05:08Z INFO breezy.runtime.trade_supervisor self_check result=FAIL_SHADOW_MODE_NO_PERMIT continuous_phase0_clean=True continuous_startup_evidence_valid=True continuous_family_not_halted=False continuous_family_halt_source=per_family
breezy alert event=TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED site=trade_node severity=CRITICAL detail=self_check_fail_shadow_mode_no_permit
```

- Orders are off by design:
  - `~/.config/systemd/user/breezy-trade-supervisor.service.d/fq-v1-halt-orders-off.conf` sets `BREEZY_ORDERS_ENABLED=0`.
  - RULING_FQ-v2-NO-TRADE_2026-10-08 is in force.
  - The node logs `order submission permit not minted: orders not requested`.
- **A second signal is also in force:** the per-family halt (`continuous_family_not_halted=False`, `halt_source=per_family`).
  - A fix to the permit branch alone would turn this into `FAIL_CONTINUOUS_FAMILY_HALTED`.
  - That result also escalates to a CRITICAL `..._FAIL_REPEATED`.
  - So a permit-only fix does not meet the goal. See D2.

## 1. Code path (exact)

All references are to `src/breezy/runtime/`.

| Step | Location | Behaviour today |
|---|---|---|
| Marker constant | `trade_supervisor_core.py:155` `PERMIT_NOT_REQUESTED_MARKER` | `"order submission permit not minted: orders not requested"` |
| Permit marker and parse | `:94` `PERMIT_ISSUED_MARKER`; `:742-753` `_PERMIT_ISSUED_RE`, `parse_permit_expiry_ns` | Parses `expires_at_ns` |
| Latch | `:1863-1872` `record_orders_not_requested_seen` | Per-child, first-seen-wins; cleared by `record_child_adopted` |
| Latch-and-derive | `:2013-2076` `derive_self_check_facts` | Latches `orders_not_requested_seen` at `:2045-2046`. **`SelfCheckFacts` (`:2001-2010`) has no field for it, so it never reaches the decision. This is the defect.** |
| Decision | `:672-739` `self_check` | `:728-731`: no valid permit gives `FAIL_SHADOW_MODE_NO_PERMIT`, unconditionally. The continuous checks (`:732-738`, including `FAIL_CONTINUOUS_FAMILY_HALTED`) run only after the permit gate passes. |
| Shell | `trade_supervisor.py:2705-…` `_do_self_check` | Reads the log delta (`:2748`), calls derive (`:2751`), resolves `continuous_check` (`:2756-2766`), calls `self_check` (`:2768-2778`), seeds B1 on a permit FAIL (`:2782-2783`), logs `self_check result=…` via `self_check_log_fields` (`:2796-2805`) |
| Escalation and emit | core `:2130-2156` `self_check_result_alert` | WARN `TRADE_SUPERVISOR_SELF_CHECK_FAIL` on the first FAIL; CRITICAL `TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED` on a repeat. Emitted through `_emit_alert_spec` (`trade_supervisor.py:2671`). PASS membership is `_SELF_CHECK_PASS_RESULTS` (core `:1965-1967`). |
| Alert-detail map | core `:418-437` `SELF_CHECK_ALERT_DETAIL` | Every FAIL maps to a fixed `AlertDetail` |
| Precedent | core `:1688-1689` `permit_capability_valid` | B1 already maps `orders_not_requested_seen` to `NOT_REQUIRED` (a WARN, once per day). B1 is unchanged here. |
| Env source | `settings.py:144` `ORDERS_ENABLED_VAR`; `:395-396` `_parse_orders_enabled` (`== "1"`) | The supervisor reads none of it today. The child inherits the supervisor's env as-is (`spawn_node`, `trade_supervisor.py:911-938`). |

Line numbers were taken at feat 43b03682 and may have shifted. Re-verify with codegraph before editing.

## 2. Decisions

- **D1. "Permit not expected" requires agreement of two independent sources.**
  - The node's log marker: `state.orders_not_requested_seen`, or the live marker when `state is None`.
  - **AND** the supervisor's own env token: `os.environ.get(ORDERS_ENABLED_VAR) == "0"`, exactly.
  - Unset, blank, or any other value is **UNKNOWN**. It never counts as off, so there is no exemption (fail closed).
  - `"1"` is ON.
  - The core stays stdlib-only. The shell reads the env and passes a tri-state into the core.
- **D2. The family halt is not part of the D1 condition, but it is suppressed under D1.**
  - The halt is not an input to "is a permit expected". D1 alone answers the permit question.
  - Recommendation: when D1 holds, `self_check` skips only `FAIL_CONTINUOUS_FAMILY_HALTED`.
  - `phase0_clean` and `startup_evidence_valid` are still checked. They are integrity faults that matter whether orders are on or off.
  - Rationale: the halt exists to stop this family sending. Node and supervisor agreeing that orders are off is a strictly stronger no-send state. Paging on the halt is therefore the same false CRITICAL this row exists to remove.
  - The halt stays visible: `continuous_family_not_halted` and `continuous_family_halt_source` are already fields of the logged `self_check` line, unchanged.
  - When orders are re-enabled (env `1`), D1 is false and the halt check is back in force. That is fail-closed at re-arm.
  - **For peer review:** the alternative is to keep paging on the halt even when orders are off. This plan defaults to suppression, and a reviewer may veto. If vetoed, step S3's family-halt skip is dropped. The permit fix still lands, but the 10-08 configuration keeps paging.
- **D3. Both directions of disagreement page.**
  - (a) Marker seen, env ON or UNKNOWN: today's `FAIL_SHADOW_MODE_NO_PERMIT`, unchanged.
  - (b) Env OFF, no marker, no permit: today's `FAIL_SHADOW_MODE_NO_PERMIT`, unchanged.
  - (c) A permit was issued (latched or live) while the env is not ON: new `FAIL_ORDERS_ENV_MISMATCH`.
    - This is the drift case: a drop-in edit plus a supervisor restart while an adopted, order-capable node keeps the old env (`KillMode=process`).
    - Today it PASSes silently.
    - New `AlertDetail.SELF_CHECK_FAIL_ORDERS_ENV_MISMATCH = "self_check_fail_orders_env_mismatch"`.
    - It is added to `_PERMIT_FAIL_SELF_CHECK_RESULTS`, so B1's heartbeat seeding stays consistent.
  - A missing permit is never healthy when orders were requested. Only the exact pair (marker, env `"0"`) yields the new PASS.
- **D4. New PASS result `PASS_ORDERS_NOT_REQUESTED`.**
  - Not a plain `PASS`, so the log line says exactly what was verified (the same stance as `PASS_ADOPTED_LOG_UNKNOWN`).
  - It is added to `_SELF_CHECK_PASS_RESULTS`, so it emits no alert and resets the AUD-14b repeat counter.
- **Invariants:**
  - No read or write of any operator cap.
  - No change to `BREEZY_ORDERS_ENABLED` semantics, permit minting, `order_enablement.py`, the drop-in, `health_dropins.py`, B1 `permit_capability_valid`, or the exec client (its sha pins are untouched).
  - `self_check_log_fields` keeps its field set: only the `result=` value is new, and no env value is logged.
  - Nautilus is untouched.

## 3. Steps

- **S1. Core facts** (`trade_supervisor_core.py`).
  - `SelfCheckFacts` gains `orders_not_requested_seen: bool`.
  - `derive_self_check_facts` fills it:
    - with `state is None`: `PERMIT_NOT_REQUESTED_MARKER in log_text`;
    - otherwise: `state.orders_not_requested_seen`, read after the latch.
  - Pure. Low risk.
- **S2. Core enums.**
  - `SelfCheckResult` gains `PASS_ORDERS_NOT_REQUESTED` and `FAIL_ORDERS_ENV_MISMATCH`.
  - `AlertDetail` gains `SELF_CHECK_FAIL_ORDERS_ENV_MISMATCH`.
  - Update `SELF_CHECK_ALERT_DETAIL`, `_SELF_CHECK_PASS_RESULTS` and `_PERMIT_FAIL_SELF_CHECK_RESULTS`.
  - Add `OrdersEnv(str, Enum)` with `ON`, `OFF`, `UNKNOWN`.
  - Medium risk. Closed-set and superset tests over `AlertDetail`/`SelfCheckResult`, plus any citation-map line pins, must be updated as **widened** rows. Never relax an equality check.
- **S3. Core decision** (`self_check`).
  - New kwargs: `orders_not_requested_seen: bool = False` and `orders_env: OrdersEnv = OrdersEnv.ON`. The defaults keep every existing caller byte-identical.
  - Insert after the `strategy_subscribed` check:
    1. `if permit_issued and orders_env is not OrdersEnv.ON: return FAIL_ORDERS_ENV_MISMATCH`.
    2. `expected_no_permit = orders_not_requested_seen and orders_env is OrdersEnv.OFF and not permit_issued`.
    3. The existing permit gate runs only when `not expected_no_permit`.
    4. The continuous block runs as today, except that the `family_not_halted` check is skipped when `expected_no_permit` (D2).
    5. The final return is `PASS_ORDERS_NOT_REQUESTED if expected_no_permit else PASS`.
  - Keep the function under 50 lines. Extract `_permit_gate(...)` if needed.
  - Medium risk.
- **S4. Shell** (`trade_supervisor.py`).
  - `SupervisorPorts` gains `orders_env: Callable[[], OrdersEnv] = field(default=lambda: OrdersEnv.ON)`. The default preserves current behaviour for every fake port set.
  - New `resolve_orders_env()` sits beside `resolve_sending_family_id`.
    - It reads only `ORDERS_ENABLED_VAR`, imported from `breezy.runtime.settings`. The module already imports `SENDING_FAMILY_ID_VAR` from there, so there is no new import-linter edge.
    - It returns `ON` for `"1"`, `OFF` for `"0"`, and `UNKNOWN` otherwise.
    - It never logs the value.
  - Wire `orders_env=resolve_orders_env` in `default_ports`.
  - `_do_self_check` passes `orders_not_requested_seen=facts.orders_not_requested_seen` and `orders_env=ports.orders_env()` into `self_check`.
  - Low risk.
- **S5. Docs.**
  - Close the PROGRESS row once the proof is in (§5).
  - Add one line to the RULING_FQ-v2 evidence noting that the self-check now classifies orders-off.

## 4. RED tests (write first; capture RED→GREEN output)

`tests/unit/test_trade_supervisor_core.py`, pure `self_check`:
- T1 `test_self_check_orders_off_agreed_no_permit_passes_orders_not_requested`
- T2 `test_self_check_orders_requested_no_permit_still_fails_shadow_mode` (**positive control**: env ON, no marker, no permit gives `FAIL_SHADOW_MODE_NO_PERMIT`)
- T3 `test_self_check_marker_seen_but_env_on_fails_shadow_mode` (disagreement a)
- T4 `test_self_check_marker_seen_but_env_unknown_fails_shadow_mode` (unset is not off)
- T5 `test_self_check_env_off_without_marker_fails_shadow_mode` (disagreement b)
- T6 `test_self_check_permit_issued_while_env_off_fails_orders_env_mismatch` (disagreement c)
- T7 `test_self_check_permit_issued_while_env_unknown_fails_orders_env_mismatch`
- T8 `test_self_check_defaults_byte_identical_to_pre_change` (parametrised over the existing truth table, with the new kwargs omitted)
- T8b `test_self_check_orders_off_agreed_skips_family_halt_only`:
  - halted gives PASS_ORDERS_NOT_REQUESTED;
  - `phase0_clean=False` still gives `FAIL_CONTINUOUS_PHASE0_FORBIDDEN`;
  - invalid startup evidence still FAILs.
- T8c `test_self_check_env_on_family_halted_still_fails_family_halted`
- T8d `test_self_check_result_alert_orders_not_requested_emits_nothing_and_mismatch_maps_detail`

`tests/unit/test_trade_supervisor_core_r32.py`, derive:
- T9 `test_derive_self_check_facts_exposes_latched_orders_not_requested` (the marker was drained earlier; latch only)
- T10 `test_derive_self_check_facts_stateless_reads_live_marker`
- T11 `test_derive_self_check_facts_no_marker_is_false`

`tests/unit/test_trade_supervisor_cont_self_check.py`, `_do_self_check` with fake ports and a fake sink:
- T12 `test_do_self_check_orders_off_family_halted_logs_pass_orders_not_requested_and_no_alert`. This is the 10-08 replay: marker in the log, env OFF, `family_halted=True`, `halt_source=per_family`, phase0 clean, evidence valid.
- T13 `test_do_self_check_orders_requested_no_permit_pages` (positive control through the shell: a repeat count gives a CRITICAL `..._FAIL_REPEATED` with `self_check_fail_shadow_mode_no_permit`)
- T14 `test_do_self_check_marker_with_env_on_pages`
- T15 `test_resolve_orders_env_tristate`: inputs `"1"`, `"0"`, unset, `""`, `"yes"`, `" 0"`. Only `"1"` is ON and only `"0"` is OFF; the other four give UNKNOWN.
- Also: a `default_ports` assertion that `orders_env` is wired to `resolve_orders_env`.

**Gate:**
- Focused run: the three files above, plus every `test_autonomy_*`, the import and firewall guards, the citation map, and the `AlertDetail`/`SelfCheckResult` superset tests.
- Then the full `scripts/ci/run_tests_no_egress.sh`, with `--basetemp` under `~/.cache` and `PYTHONPATH` set to the worktree.
- `lint-imports` from the tree root; it must print "N kept, 0 broken".
- `ruff` on the touched files only.
- Read `GATE_EXIT` before any merge or push.

## 5. Activation

- Merge gate-green.
- Run `systemctl --user restart breezy-trade-supervisor` **inside 01:00–16:40Z**. `KillMode=process` keeps the node, and supervisor code loads only once.
- Confirm `supervisor_started` with the new build revision, plus the adoption line.
- **Proof** at the next 17:05Z, from `journalctl --user -u breezy-trade-supervisor --since "<day> 17:00 UTC" --until "<day> 17:20 UTC" -o cat | grep -viE 'https?://'`:
  - present: `self_check result=PASS_ORDERS_NOT_REQUESTED ... continuous_family_not_halted=False continuous_family_halt_source=per_family`;
  - absent: any `TRADE_SUPERVISOR_SELF_CHECK_FAIL` or `..._FAIL_REPEATED` alert between 17:05 and 17:10Z.
- A FAIL result is a failed activation. Revert the merge and restart again inside the window.

## 6. Risks

- **R1. Env drift** (an adopted node inherited a different env): covered by D3(c) and T6/T7, which page.
- **R2. Adoption clears the latch.** `record_child_adopted` clears `orders_not_requested_seen`. If an adopted node's marker sits outside the self-check's delta, the result falls back to `FAIL_SHADOW_MODE_NO_PERMIT`. That is the louder direction and acceptable. On the normal 16:50Z supervisor spawn, RELAUNCH_CHECK or derive drains the marker into the latch.
- **R3. D2 reduces family-halt visibility while orders are off.** Mitigations:
  - the halt fields stay in the logged line;
  - the check comes back automatically when the env returns to ON.
  Reviewers may veto (the D2 alternative).
- **R4. Closed-set and pin tests.** Adding enum members trips superset and equality pins. Fix them as widened rows only.
- **R5. B1 overlap.** B1 still sends its once-per-day `TRADE_SUPERVISOR_PERMIT_NOT_REQUIRED` WARN. That is intended, unchanged, and not a CRITICAL.
- **R6. Default port `ON`.** The fake-port default keeps the legacy FAIL behaviour, so a production wiring omission fails loud, never silent. T12/T15 and a `default_ports` assertion cover the wiring.
- **R7. Concurrent agents.** `SupervisorPorts` and `default_ports` are a shared edit surface with AMBIG-LATCH. Rebase onto the HEAD of `feat/data-capture-and-risk`. On a conflict, diff the dataclass against both parents.

## 7. Interplay

- **SUP-RESTART-ANYTIME D2.4 proof** (`ready_adoption_terminal verdict=not_required`, owed ≥17:10Z on 10-09):
  - It lives in the B1/ready-adoption path, which this change does not touch.
  - The 10-09 17:05Z self-check is expected to repeat the 10-08 CRITICAL. That is the baseline; it is not a regression.
- **AMBIG-LATCH-RESUME Phase A/B** (merged be9b80da/43b03682/004f306f):
  - §2.9 changes the launch path: `decide_launch_action`, `LAUNCH_TO_RESOLVE`, new defaulted `SupervisorPorts` probe fields, and the node-side resolver.
  - This plan touches none of those. It changes only `self_check`, its facts, and one additive defaulted port.
  - No exec-client sha or citation pin moves. A shared-file rebase is the only coupling (R7).

## 8. Success criteria

- [ ] T1–T15 (with T8b–T8d) go RED then GREEN. Full gate `GATE_EXIT=0`; lint-imports reports 0 broken.
- [ ] Supervisor restarted inside 01:00–16:40Z.
- [ ] The 17:05Z proof line is present, with no self-check alert.
- [ ] PROGRESS row closed with the commit sha and the proof timestamp.

## 9. r2 amendments (BINDING; they override §1–§8 where they conflict)

Reviews 2026-10-09:
- **trading-bot-architect:** REVISE → amendments A1–A3. D1 sufficient; D2 APPROVED on condition of A3; D3(c) correct with no false positive on any spawn path; no other paths missing.
- **python-reviewer:** REVISE → amendments A4–A9.

- **A1 (HIGH).** Add `PASS_ORDERS_NOT_REQUESTED` to **both** pass sets:
  - the core `_PASS_RESULT_VALUES` (core ~:798, used by `record_self_check_result`);
  - the shell `_SELF_CHECK_PASS_RESULTS`.
  - Test: `test_record_self_check_result_orders_not_requested_resets_consecutive_failures`, which asserts that a prior FAIL count goes to 0.
- **A2 (MEDIUM).** The adoption path re-latches the marker. Test: `test_adopted_node_boot_log_replay_relatches_orders_not_requested_then_self_check_passes`. It runs `record_child_adopted`, then the adoption boot-log replay containing the marker, then `derive_self_check_facts` + `self_check`, and expects `PASS_ORDERS_NOT_REQUESTED`. If the replay does not re-latch, STOP and report. Do not widen the latch semantics without a ruling.
- **A3 (MEDIUM; condition of the D2 approval).** `self_check_log_fields` adds two fields:
  - `orders_env=on|off|unknown`. This is the tri-state, never the raw value.
  - `family_halt_check=skipped|checked`.
  - The existing halt fields stay.
  - Test: the 10-08 replay (T12) asserts both fields appear in the line.
- **A4 (blocker).** `trade_supervisor_core` is in the `aut6.health` closure (`closure_manifest.py`). Re-pin `PRODUCER_SOURCE_SHA256["aut6.health"]` in `src/breezy/persistence/autonomy/pins.py` LAST, via `closure_sha256('breezy.runtime.autonomy_health_cli')`. No manifest regen is needed (no new imports). Add `tests/unit/test_autonomy_pins.py` to the focused gate.
- **A5. Construction sites.**
  - `SelfCheckFacts` is constructed only inside `derive_self_check_facts` (two sites). Both must set the new field.
  - The new `SupervisorPorts` field goes LAST, because the dataclass is frozen, slotted and keyword-defaulted.
- **A6. Added to the focused gate:**
  - `tests/unit/test_trade_supervisor.py`. It iterates over `AlertDetail` at ~1430/1940/8619; the new value must be lowercase and under 80 characters.
  - `tests/unit/test_trade_supervisor_cont_self_check.py`
  - `tests/unit/test_ct08_supervisor_contract_surface.py`, `test_ct02*`, `test_ct13*`, `test_ct14*`
  - `tests/unit/test_trade_supervisor_core_r32.py`
  - `tests/unit/test_runtime_import_isolation.py`
  - `tests/unit/test_autonomy_pins.py`
  - every `test_autonomy_*` and `test_aut6_*`
  - `tests/contract/`
  - `tests/unit/test_mypy_ratchet.py` (tests/unit ceiling is 1288; never raise it)
  - `tests/unit/test_study_failure_alert.py`
- **A7. Non-vacuity requirements.**
  - T12, T13 and T14 set `ports.orders_env` explicitly. T12 also sets an active `ContinuousFamilyCheck` with `family_not_halted=False`.
  - T1 and T8b pass a `ContinuousFamilyCheck(family_not_halted=False)`.
  - T9 uses a log delta WITHOUT the marker, with the latch pre-set.
  - T8 compares against hard-coded expected results, never against a re-derivation.
  - T8d asserts that every `FAIL_*` result has a `SELF_CHECK_ALERT_DETAIL` entry.
- **A8. Missing tests to add.**
  - `test_self_check_adopt_cleared_latch_without_marker_falls_back_to_shadow_mode_fail` (pins R2).
  - `test_orders_env_mismatch_seeds_b1_permit_alert` (`_PERMIT_FAIL_SELF_CHECK_RESULTS` seeding).
  - `test_expected_no_permit_does_not_mask_node_not_ready_child_exited_or_multiple_flock_holders` (precedence).
- **A9. Activation timing.** Today's 10-09 17:05Z CRITICAL is the expected baseline. Activate in 10-10's 01:00–16:40Z window; proof is at 10-10 17:05Z.
