# AMBIG-LATCH-RESUME r6.1 delta (base bd32de69, 2026-10-08)

r6 and `reviews/AMBIG-LATCH-RESUME-r6-final.md` still apply wherever this delta does not replace them. The planner authored this delta and verified it read-only at bd32de69. Status: awaiting peer review by trading-bot-architect and security-reviewer before any build.

## D0. Anchors are cited by symbol
Line numbers are hints only. Builders resolve every anchor by symbol name with `codegraph_explore`, because SUP-RESTART-ANYTIME moves supervisor lines.

**Still exact at bd32de69:**
- **`client.py`**
  - The file is byte-identical. The pin at `test_forecast_quantile_ladder_manifest_and_markers.py:36` is still `76784ce8…68a4`.
  - Symbols: `_resolve_ambiguous_intents` :2379, `_resolve_terminal_zero` :2985, `_resolve_accept_fill` :3114, `_order_trade_activity` :3319, `_durable_net_qty` :3442, `_resolver_fill_order_unknown` :4199, `client_order_id_for` :4587, `_read_open_orders` :5054, `_retire` :5223, `_generate_submitted` :5246, `_note_ambiguous_open` :5255, `_submit_order` :5353, `_refuse` :5896, `__repr__` :5978, `AmbiguousResolverContext` :1086, `RESOLVER_CONTEXT_KEY_PREFIX` :454.
- **`trade_supervisor.py`:** `resolve_lock_holder_pid` :374, `probe_open_intent` :402, `spawn_node` :849, `_do_launch` :1209-1301, boot retry :1582, `permit_watch_adopted_live_node` :2068, `supervisor_started` :2492.
- **`trade_supervisor_core.py`:** `AlertDetail` :257, `LaunchAction` :341, `decide_launch_action` :532.
- **`submit_intent.py`:** `RetirementReason` :73, `_optional_enum` :207, `is_latched` :378, `arm` :391.
- **`account_activity.py`:** :36-48, :190, :363, :569, :599.
- **`component_health_watch.py`:** :476, :490, :612, :628.
- **`trade_cli.py`:** :629.

**Drifted (old → new):**
- **`submit_chain`:**
  - entry wire body :376-387 → :363-374
  - exit wire body :558-569 → :545-556
  - `_MAX_BLOCK_TIME` :134 → :135
  - `classify_create_order_outcome` :1200-1322 → :1187-~1318
  - no-response branch :1219-1233 → :1206-1220
  - `generate_submitted=False` :1231 → :1218
  - `retirement_member` :1508 → :1496
- **`config.py`:** `PolymarketUSExecClientConfig` :547 → :568.
- **`node_config.py`:**
  - The exec `msgspec_replace` site :945-967 → :997-1006. It already passes `retirement_reasons=RetirementReason` at :1002; the new kwarg goes into that same call.
  - In-flight-poller docstring → ~:872-900.
  - `LiveExecEngineConfig(inflight_check_interval_ms=0)` is at :1022.
- **Firewall guard (`test_execution_egress_firewall_guard.py`):**
  - `NETWORK_IMPORT_PREFIXES` :1758 (unchanged)
  - `EXEC_PERMITTED_COROUTINE_NAMES` :1797-~1916
  - `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` :1944-~2086
  - `EXEC_RESOLVER_COROUTINES` :2105-2115 (still 4 names)
  - `EXEC_RESOLVER_PERMITTED_CALLEES` :2124-~2302
  - `find_exec_resolver_violations` :2441-~2503
  - order-coroutine set-equality pin :3108-3219
  - `_set_resolver_last_failure_kind` helper :4082 and test :4124
  - X1 exec-import pin: test :3242, assertion :3642-3768
- **Twin pin** in `test_cage_rule_constants_are_pinned.py`: cited by symbol only.
- **T42(i) frozen literals:** copy them from the Phase B base commit, not from f45f5a65.

## D1. Supervisor key prefix comes from the domain module
Replaces the §2.9 "literal copy" bullet and the last clause of T44(vi).
- `trade_supervisor.py` imports `RESOLVER_CONTEXT_KEY_PREFIX` from `breezy.domain.exec_intent` (:35). `tests/unit/autonomy/test_exec_intent_parity.py::test_exec_key_prefixes_equal_client_constants` already pins it equal to the client constant.
- T44(vi) becomes: `trade_supervisor.RESOLVER_CONTEXT_KEY_PREFIX is exec_intent.RESOLVER_CONTEXT_KEY_PREFIX`.
- Result: `test_trade_supervisor.py` never imports `exec/`, so Phase A adds no X1 row.

## D2. Existing test edits
Replaces "No other existing test is edited" and adds §3.1 items 6–8.

### §3.1-6 X1 exec-import pin (exact set; widen by one reviewed row each, never relax ==)
- **Phase A adds 0 rows.** If T44(vi) instead compares against `client.*`, STOP and report.
- **Phase B adds exactly 3 rows.** Each carries the house comment "Old -> new … WIDENED, not relaxed (L-6/L-12) … carries no SOCKET_RESTORING_MARKERS … sender is a fake double, no socket".
  1. `tests/unit/test_ambig_latch_resume.py` (T1–T8b, T13–T16, T20–T25)
  2. `tests/unit/test_ambig_no_id_resolver.py` (T26–T40, T46b, T49–T51)
  3. `tests/unit/test_trade_cli.py` (T12 imports `exec.submit_chain.AMBIGUOUS_REASON`)
- **These must NOT import `exec/`:** `test_no_id_attribution.py` (T41), `test_no_id_attribution_purity.py` (T48), `test_ambig_no_id_firewall_delta.py` (T42), `test_component_health_watch_degraded_throttle.py` (T17–T19, literal reason), `test_supervisor_decode_marker.py` (T46), `test_retirement_reason_superset.py` (T47, AST by path), and the T43 append to `test_submit_intent_latch.py`.
- **Stop condition:** any further module appearing in the set.

### §3.1-7 AUT-1 V-15 closure count
- `test_aut1_wp0_closure_premises.py:52` asserts `len(walked) == 34`. Phase B's `client.py` import of `no_id_attribution` adds exactly one module, so it becomes `== 35`, with a comment naming this item.
- The fresh-process equality (`walked == imported`) is unedited and must stay green.
- Phase A must leave the count at 34. Verify this by running the test.

### §3.1-8 Disclosed guards (green and unedited)
- `test_alert_constants_and_egress_pin.py::test_alert_egress_import_pin`: the new modules `supervisor_decode_marker.py` and `no_id_attribution.py` import no network root.
- New `AlertDetail` members satisfy `test_alert_detail_is_always_the_fixed_enum_value`.

### Phase B PR wording
Append: "Three X1 rows added (named); one V-15 closure count 34→35."

## D3. Phase split: T46(v) moves to Phase B
- T46(v) asserts `node_config` sets `no_id_retire_admitted`. That is Phase B code, so the test would be red on Phase A.
- It moves to `test_ambig_no_id_resolver.py` as T46b. Phase A's T46 covers (i)–(iv) only.

## D4. Activation under orders-off
Replaces §5 steps 2–3, §5.1 P1/S1–S5, §5.2, §5.4 positive proof, §2.10 "Activation S3", and §6 "hand-relaunch".

**State:**
- RULING_FQ-v2-NO-TRADE_2026-10-08 is in force.
- `fq-v1-halt-orders-off.conf` sets `BREEZY_ORDERS_ENABLED=0`, and the permit is absent.
- No hand node relaunch is allowed for this item.
- Nothing in this item reads or writes enablement, the permit, or the caps.

**Phase A** (coordinator, within the 01:00–16:40Z window):
1. U0: merge after the full gate returns EXIT=0. Record the holder pid `<P>`.
2. U1: `systemctl --user restart breezy-trade-supervisor` (`KillMode=process` keeps the node).
3. U2: run the Phase A check script; it must exit 0. U2 is bound to the supervisor `MainPID`. Re-run U2 if the supervisor restarts again before Phase B merges.
- The restart window still applies after SUP-RESTART: U2 check 3's adoption line comes from the once-per-window adoption, which is only guaranteed in [01:00, 16:40).

**Phase B** (passive):
- B0: the U2 EXIT=0 output is attached to the merge record.
- Before merging, run the r3 `intent_open_ro` read-only probe and record OPEN or CLEAR. This is information only.
- Merge, preferably before 16:40Z. The node loads Phase B at the next 16:50Z LAUNCH, after the supervisor's own 16:40Z STOP_PRIOR.
- Not run: SIGTERM, `spawn_node`, the `AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT` alert, and the S5 relaunch.
- The §5.2 W race is moot, because no POST can be in flight while orders are off.

**Between phases:** the exposure is bounded by the first 16:50Z LAUNCH after the Phase B merge. While orders are off no new intent can be armed.

**§5.4 is scored "machinery proven"** (mirrors AUT-6 X-7):
- **M1:** U2 EXIT=0.
- **M2:** at the 16:50Z LAUNCH the supervisor log shows `launched pid=…` or `launch_to_resolve_open_intent shape=…`, and never `launch_refused_intent_open`.
- **M3:** the node log FILE shows:
  - `no_id_retire_admitted=True`;
  - `refusal re-poll timer armed name=… interval_s=60`;
  - the 4 boot lines;
  - the permit-capability line as it reads today;
  - a spawn-time HEAD that descends from `<PHASE_B_SHA>`.
- **M4 (negative):** no client `InvalidStateTrigger`, and no RESUMING or RUNNING while the latch is OPEN.

**DEFERRED-LIVE:** the r6 positive in-service proof is deferred to the first armed boot under T1/T2 and the first AMBIGUOUS after it. Add a PROGRESS row: `AMBIG-LATCH-RESUME: machinery proven <date>; live proof DEFERRED → first armed boot`.

**§6 Rollback:**
- Revert Phase B, run the full gate, and the next 16:50Z LAUNCH loads the reverted node.
- No supervisor restart and no hand relaunch.
- The read-only P1-CLEAR precondition is kept.

## D5. Sequencing
- **S-0:** SUP-RESTART-ANYTIME merges and activates before Phase A branches. Phase A then:
  - appends after SUP's tests;
  - adds its `AlertDetail` members after `READY_ADOPTION_*`;
  - leaves `test_ct08_supervisor_contract_surface.py` and `test_ct14_supervisor_restart_anytime.py` green and unedited.
- **Phase A merges before AUT-5a row 7a's first commit.** If 7a lands first: stop, rebase, and re-run the architect review.
- Neither C0 nor Phase A merged code is ever reverted.
- Security-reviewer F4 written sign-off, extended to the no-id predicate, is merge-blocking for Phase B.

## D6. Focused gates (both phases)
- Run these: `test_execution_egress_firewall_guard.py`, `test_cage_rule_constants_are_pinned.py`, `test_aut1_wp0_closure_premises.py`, `tests/unit/autonomy/test_exec_intent_parity.py`, `test_alert_constants_and_egress_pin.py`, `test_ct08_supervisor_contract_surface.py`.
- Phase A also runs `test_ct14_supervisor_restart_anytime.py`.
- `lint-imports` must report "N kept, 0 broken", run from the tree root.

## D7. New risks
| Risk | Mitigation |
|---|---|
| No in-service proof until a family is armed | "Machinery proven" scoring plus the DEFERRED-LIVE row |
| U2 goes stale if the supervisor restarts between phases | Re-run U2 against the current `MainPID` |
| Line anchors break after SUP-RESTART | Cite by symbol |

## Verdict
NOT-READY until peer-reviewed. After review, the build is gated on SUP-RESTART-ANYTIME being merged and activated.
- **Required reviewers:** trading-bot-architect and security-reviewer.
- **python-reviewer:** required at the build stage.
