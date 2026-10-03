# AMBIG-LATCH-RESUME — plan r1 (2026-10-03)

Status: DRAFT for peer review. Plan only; nothing is implemented.
Item (docs/core/PROGRESS.md:96): AMBIG-LATCH-CLEAR (`3eb4a108`) leaves the exec client DEGRADED after the clear. Health reads DEGRADED while the client trades, and a later refusal does not re-alert. Call native `resume()` from outside the resolver.

Evidence base: commit `3eb4a108` (message + diff), `docs/plans/refactor_2026-10-01/EXECUTION_LOG_2026-10-02.md:113`, `tests/unit/test_execution_egress_firewall_guard.py`, Nautilus `common/component.pyx` and `execution/engine.pyx`. All `$NT` line numbers below were read with `/usr/bin/grep -rn`. The positive control was `class Component`, which matched 2 lines in `component.pyx`.

---

## §0 Problem and goal state

### Problem (two defects, not one)

**D1. The FSM stays DEGRADED.**
- `_refuse` (`exec/client.py:5896-5976`) calls `self.degrade()` on the first refusal while not degraded.
- `_resolve_terminal_zero` (`:3100-3112`) clears the AMBIGUOUS entry from `_trading_refusals` as its last step.
- Nothing ever calls `resume()`, so the native state stays `DEGRADED` for the rest of the process. In `$NT` the only native `.resume()` / `.degrade()` call on an adapter is in `adapters/betfair/data.py:401`, so nothing native will move it either.

**D2. The alert latch is permanent.** This defect was not named in the item, but the goal state needs it fixed.
- `install_component_degraded_alert` (`runtime/component_health_watch.py:669-681`) adds `component_id` to `alerted` on the first DEGRADED and never removes it.
- So even after D1 is fixed, `RUNNING -> DEGRADED` a second time is silently swallowed.
- Fixing D1 alone does NOT satisfy "a later refusal re-alerts".

**Side effect of D1.** `ExecutionEngine._stop` / `stop_clients` (`$NT/execution/engine.pyx:727-729, 770-772`) call `client.stop()` only `if client.is_running`, and `is_running` means RUNNING only (`component.pyx:1819-1828`). A client that stays DEGRADED is therefore skipped by the engine's own stop. Resuming puts shutdown back on the normal path every never-degraded session already takes.

### Goal state (acceptance test)

After a GET-confirmed terminal zero-fill, all of the following hold:
1. The intent is retired, the booking is trued up, the permit slot is restored, and the AMBIGUOUS refusal is cleared. This is unchanged from `3eb4a108`.
2. Within one re-poll interval (≤60 s), the exec client goes `DEGRADED -> RESUMING -> RUNNING` through the native `Component.resume()`.
3. `client.is_degraded` is False and `client.is_running` is True.
4. The next refusal of any reason drives a fresh `degrade()` (the `_refuse` gate `was_already_degraded` is now False) and emits exactly ONE new `component_degraded` CRITICAL alert.
5. No `DEGRADED -> RUNNING` transition ever happens while the durable submit intent is OPEN or corrupt, or while any entry remains in `_trading_refusals`.

---

## §1 Null hypothesis (L-1): what Nautilus and Breezy already provide

| Need | Native / existing capability | Verdict |
|---|---|---|
| Leave DEGRADED | `Component.resume()` (`component.pyx:2003-2032`). FSM edges are `(DEGRADED, RESUME) -> RESUMING` (`:1650`) and `(RESUMING, RESUME_COMPLETED) -> RUNNING` (`:1641`). The action is `self._resume`, which is `pass` in `Component` (`:1904-1906`). It is not overridden by `ExecutionClient`, by `LiveExecutionClient` (grep: 0 hits in `execution/client.pyx`, `live/execution_client.py`), or by Breezy (grep `def _resume` in `src/`: 0 hits). | **REUSE as-is.** No custom state, no wrapper, no override. |
| Publish the transition | `_trigger_fsm` publishes `ComponentStateChanged` on `events.system.<id>` for every trigger (`:2187-2225`). An invalid trigger is caught, logged at ERROR, and returns (`:2192-2196`). | REUSE. Because of that ERROR, the caller must gate on `is_degraded` so a RUNNING client is never "resumed" every minute. |
| Run code periodically on the loop thread, outside any exec coroutine | `install_refusal_repoll_timer` (`component_health_watch.py:490-625`): a native `Clock.set_timer` hops through `loop.call_soon_threadsafe` to `_poll`, which calls a handler tuple. It is already armed in `trade_cli._run_node` (`trade_cli.py:625-635`) with `(recon_h, stale_h, contradiction_h)`. Its thread model is measured (`tests/contract/test_refusal_repoll_live_clock_contract.py`). | **REUSE.** Add one handler. No new timer, and no new thread hop (L-16). |
| Reach the client from runtime | The `_exec_client_*_reader` idiom: `node.kernel.exec_engine._clients.get(ClientId(...))`, which is a `cdef readonly` dict (`trade_cli.py:393-484`). | REUSE the idiom. |
| "Is an AMBIGUOUS intent open?" | `SubmitIntentLatch.is_latched()` (`runtime/submit_intent.py:378-389`) is True if OPEN and True if corrupt (fail-closed). It is already an `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` member, used as the SAFETY C1 pre-spend re-check. | **REUSE.** It is stricter than `current_open()`, which raises on corruption. |
| Alert on DEGRADED | `install_component_degraded_alert`. | EXTEND by one line (re-arm on RUNNING). No new alert type. |

Conclusion: nothing new is invented. The change is one native call, gated by one existing latch predicate, triggered by one existing timer, plus one re-arm line in an existing subscriber.

---

## §2 Design

### 2.1 Call site: a sync client method, driven by the runtime re-poll timer

**New public sync method on `PolymarketUSExecutionClient`: `resume_if_refusals_cleared() -> bool`.**
- Placement: directly after `_refuse`, which is the end of the class (`client.py:~5977`). That is AFTER the deny chain, so the deny-chain lines named in the sha-pin message do not move.
- Body, in order. The only callees are `self._latch.is_latched`, `self.resume`, `self._log.info` and `self._log.warning`.
  1. `if not self.is_degraded: return False`. This is a property read, not a call. It skips RUNNING, RESUMING, STOPPING and STOPPED. Most importantly it skips STOPPED, because `(STOPPED, RESUME)` is ALSO a legal native edge (`:1646`) and must never be taken from here.
  2. `if self._trading_refusals: return False`. Every refusal reason, not only AMBIGUOUS, keeps the client DEGRADED.
  3. `if self._latch is None: return False`. This is fail-closed: with no latch, the client cannot prove that no intent is open.
  4. `try: latched = self._latch.is_latched()`, then `except Exception: self._log.warning(<type name only>); return False`.
  5. `if latched: return False`. This covers an OPEN intent: the in-flight window between `_latch.arm` and the AMBIGUOUS `_refuse`, a no-id AMBIGUOUS, and a boot with an unresolved intent. It also covers a corrupt singleton.
  6. `self.resume()`, then `self._log.info("health: resumed from DEGRADED (no refusals, no open submit intent)")`, then `return True`.
- Thread safety: it runs on `node.kernel.loop` (the `_poll` hop), which is the same loop the resolver, `_submit_order` and `_refuse` run on. It is fully synchronous with no `await`, so no check can be invalidated between steps 1-5 and step 6.

**Runtime trigger: a new helper `_exec_client_resume_handler(node) -> Callable[[object], None]` in `runtime/trade_cli.py`.**
- It sits next to the four `_exec_client_*_reader` helpers and uses the same lazy lookup.
- A missing client, or a client without `resume_if_refusals_cleared`, is a no-op (`getattr(..., None)`), never a raise.
- It is appended LAST to the `handlers=` tuple at `trade_cli.py:629`, so the three alert polls run first in each tick.
- `_poll` already wraps each handler in its own `try/except Exception`, so a raise cannot block a sibling or a later tick.

**Why not the alternatives:**
- **From the resolver.** This trips E0-NOSEND-RESOLVER (`find_exec_resolver_violations`, `test_execution_egress_firewall_guard.py:2435-2496`). Widening the allowlist is prohibited.
- **From `_submit_order`.** This is an ORDER_LIFECYCLE coroutine with its own allowlist (E0-NOSEND, `:2360-2409`). Same prohibition.
- **A client-owned `self._clock.set_timer`.** The LiveClock callback runs on a Rust/tokio thread (L-16, measured). That would duplicate the hop `install_refusal_repoll_timer` already owns.
- **On `ComponentStateChanged`.** The clear is not a state change, so nothing would fire.
- **A new async coroutine in `exec/`.** It breaks the E0-INERT coroutine-inventory equality (`EXEC_PERMITTED_COROUTINE_NAMES`). It is also unnecessary, because the method is sync.
- **Putting the predicate in runtime.** That would make runtime read the private `_latch` and `_trading_refusals`. Keeping the predicate beside the state it reads is cohesive, and runtime only triggers.

### 2.2 Re-alert: re-arm the DEGRADED alert on RUNNING

In `install_component_degraded_alert._on_component_state` (`component_health_watch.py:672-681`):
- When the event is for `component_id` and `event.state == ComponentState.RUNNING`, call `alerted.discard(component_id)` and return.
- The DEGRADED branch is unchanged.
- Update the Notes docstring to say: "only the FIRST DEGRADED per degraded *episode*; an episode ends on RUNNING."

Existing behaviour that is preserved, and pinned by tests that stay unmodified:
- `test_a_second_refusal_does_not_re_alert`: there is no RUNNING between the refusals, so there is still one alert.
- `test_a_non_degraded_transition_does_not_alert`: DEGRADING and RUNNING still emit nothing.
- `test_a_degraded_transition_from_another_component_is_ignored`: the component filter runs first.

### 2.3 Proof the call site cannot send orders

Each step below is pinned by a test in §3.

1. **Trigger chain.** The chain is `LiveClock timer -> _on_timer -> loop.call_soon_threadsafe(_poll) -> _exec_client_resume_handler -> client.resume_if_refusals_cleared()`. None of these frames reaches `_order_sender`, `_private_read`, `submit_chain` or any `exec/` coroutine.
2. **Method body.** The callee set is exactly `{self._latch.is_latched, self.resume, self._log.info, self._log.warning}`. It has no `await`, it is not a coroutine, and it contains no `self.create_task`, `asyncio.*` or `threading.*`. An AST pin enforces this (T5).
   - `is_latched` is a local store read. It is already allowlisted on the order path as an inert re-check.
3. **`resume()`.** It calls `Component._resume`, which is `pass`. An MRO pin (T6) checks that no class between `PolymarketUSExecutionClient` and `Component` defines `_resume`, so a future override cannot silently add an action.
4. **Published event and its subscribers.** The only output is `ComponentStateChanged` on `events.system.POLYMARKET_US`, published twice (RESUMING, then RUNNING). Its subscribers in the live node:
   - **Native:** none. Grep of `$NT` for `events.system` finds only the publisher (`component.pyx:2223`).
   - **Breezy:** `component_health_watch` (four alert installers, which are alert-only and pinned by `test_the_watch_module_reaches_no_venue_and_no_socket` and `test_neither_the_refusal_path_nor_the_watch_module_can_stop_the_process`).
   - **Breezy:** `strategy/current_rung_hold/composition.py:905-922` `_on_event`, which only calls `RefusalAlerter.report(now_ns=...)` and deduplicates on count change.
   - None of these submits, cancels or modifies an order. T7 asserts this at runtime by subscribing `*` during `resume_if_refusals_cleared()` and requiring every published topic to equal `events.system.<client id>`.
5. **DEGRADED is not an order gate.** Order admission keys only on `_trading_refusals`, the permit and the latch (`_submit_order:5357`). Native routing never reads client state: `ExecutionEngine` uses `is_running` only in `_stop` / `stop_clients`, and `RiskEngine` has 0 hits. The existing pin `test_terminal_zero_fill_retirement_clears_ambiguous_refusal_and_a_take_reaches_sender` already proves a take reaches the sender while the client is still DEGRADED. So resuming opens no send path that was closed before; it changes health reporting only.
6. **The firewall is untouched.** The new method is not in `EXEC_RESOLVER_COROUTINES` or `ORDER_LIFECYCLE_COROUTINES`. It is also NOT added to `EXEC_RESOLVER_PERMITTED_CALLEES`, so any future attempt to call it from the resolver fails E0-NOSEND-RESOLVER unmodified. T8 makes this explicit.

### 2.4 The "never resume while AMBIGUOUS is open" invariant

The guard is layered:
- **(a)** `_resolve_terminal_zero` clears AMBIGUOUS only when `current_open() is None` (`:3100`). This is existing behaviour.
- **(b)** The new method requires an empty `_trading_refusals`, so an uncleared AMBIGUOUS blocks the resume.
- **(c)** The new method independently requires `is_latched() is False`, so an OPEN or corrupt intent blocks the resume even when the list is empty. This covers the in-flight `arm -> post_order` window and any future clear path.
- **(d)** Both checks and `resume()` run in one synchronous frame on the loop thread.

T2 and T3 pin (c) with the list empty.

---

## §3 Tests: RED -> GREEN

All new tests go in new files or are appended to the named files. No existing assertion is edited, weakened or deleted. RED is shown by running each new test against the unmodified tree; record the RED and GREEN outputs as the change artifact.

| # | File | Test | RED today because |
|---|---|---|---|
| T1 | `tests/unit/test_ambig_latch_resume.py` (new) | `test_terminal_zero_clear_then_resume_returns_the_client_to_running`: uses the `_arm_one_ambiguous_intent` + `_run_resolver_passes` rig. Precondition (non-vacuity): `client.start()` was called and `client.is_degraded` holds after the AMBIGUOUS take. After the terminal-zero pass, call `client.resume_if_refusals_cleared()`: it returns True, `is_running` is True and `is_degraded` is False. | `AttributeError`: the method does not exist |
| T2 | same | `test_resume_refused_while_the_submit_intent_is_open`: DEGRADED, `_trading_refusals` emptied by assignment, latch still OPEN. The method returns False and `is_degraded` stays True. | AttributeError |
| T3 | same | `test_resume_refused_when_the_latch_read_is_corrupt_or_raises`: corrupt the singleton, then separately monkeypatch `is_latched` to raise. Both return False and stay DEGRADED, and the second case logs a WARNING carrying the type name only. | AttributeError |
| T4 | same | `test_resume_is_a_no_op_unless_degraded`: (i) RUNNING returns False with no ERROR "InvalidStateTrigger" logged; (ii) STOPPED returns False and the state stays STOPPED (guards the native STOPPED->RESUME edge); (iii) any remaining refusal (the `_UNRELATED_REFUSAL` shape) returns False; (iv) `_latch is None` returns False. | AttributeError |
| T5 | same | `test_resume_method_callee_set_is_exactly_pinned`: AST walk of `resume_if_refusals_cleared` using the firewall test's `_dotted_callee` semantics. Callees must EQUAL `{self._latch.is_latched, self.resume, self._log.info, self._log.warning}`, with no `Await`, `AsyncFor` or `AsyncWith`, and the function is a `FunctionDef`. Planting `self._order_sender.post_order` in a source copy must fail (non-vacuity). | method absent, so the pin fails |
| T6 | same | `test_resume_action_is_the_native_no_op`: `[c for c in type(client).__mro__ if "_resume" in vars(c)] == [Component]`. | GREEN today. This is a pre-existing-truth guard and is listed as a pin, not as RED. |
| T7 | same | `test_resume_publishes_only_the_component_state_topic_and_never_reaches_the_sender`: subscribe `*` on the rig msgbus and spy `_order_sender.post_order`. After a successful resume, every published topic is `events.system.<client id>`, the states are `[RESUMING, RUNNING]`, and `sender.calls` has not grown. | AttributeError |
| T8 | same | `test_the_resume_method_is_outside_every_firewall_scope_and_unreachable_from_the_resolver`: asserts `"resume_if_refusals_cleared"` is NOT in `EXEC_RESOLVER_COROUTINES`, `ORDER_LIFECYCLE_COROUTINES` or `EXEC_PERMITTED_COROUTINE_NAMES`, and that neither `"self.resume"` nor `"self.resume_if_refusals_cleared"` is in `EXEC_RESOLVER_PERMITTED_CALLEES` or `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`. It imports these constants from the firewall test module read-only. | GREEN for the constants, RED for the AST "method exists" precondition in the same test |
| T9 | `tests/unit/test_exec_refusal_health_surface.py` (append) | `test_a_refusal_after_resume_re_alerts_exactly_once`: real rig, start, refuse A (1 alert), clear the list, `resume_if_refusals_cleared()`, then refuse B: 2 alerts total. Then refuse C while still DEGRADED: still 2. | Fails at 1 alert (D2) and on the AttributeError (D1) |
| T10 | same file (append) | `test_running_re_arms_the_degraded_alert_for_the_same_component_only`: synthetic msgbus events DEGRADED(X), RUNNING(X), DEGRADED(X) give 2 alerts. DEGRADED(X), RUNNING(OTHER), DEGRADED(X) give 1. | Gives 1 today (D2) |
| T11 | `tests/unit/test_trade_cli.py` (append) | `test_repoll_timer_resumes_a_cleared_exec_client`: uses the existing `RecordingNode` + `_fire_repoll` harness with a fake client exposing `resume_if_refusals_cleared` (records calls). One `_fire_repoll` gives exactly one call. A node with no client, or a client lacking the attribute, does not raise and the other handlers still fire. | Gives 0 calls today |
| T12 | `tests/unit/test_trade_cli.py` (append) | `test_resume_handler_is_wired_last_in_the_repoll_handler_tuple`: monkeypatch `install_refusal_repoll_timer` to capture `handlers`. Length is 4, and the last one is the resume handler (its `__qualname__` contains `_exec_client_resume_handler`). | Length is 3 today |

**Unmodified and must stay green:**
- `test_execution_egress_firewall_guard.py`, the entire file and every allowlist constant.
- `test_fq_caps_and_ambiguous_2026_10_01.py`.
- `test_exec_refusal_health_surface.py`'s existing tests, including the 25-producer pin. No `_refuse` call site is added.
- `test_component_health_watch_*`.
- `tests/contract/test_refusal_repoll_live_clock_contract.py`.

**One re-pin, reviewer-approved, precedent `3eb4a108`:** `_EXEC_CLIENT_SHA256` in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`.
- The reviewer must confirm three things: the client diff is confined to the one new method appended after `_refuse`; lines 1-5977 are byte-identical (`git diff` shows additions only, after the deny chain); and the docstring carve-out names this item.
- This is an update of a byte-identity pin to a reviewed new value. It is not a relaxation, and no assertion text changes.

**Gate:**
- `scripts/ci/run_tests_no_egress.sh`: the full gate, read EXIT before any push.
- `lint-imports` run from the tree root (demand "N kept, 0 broken"). Runtime may import nothing new from `exec/`, because the handler uses `getattr` on the looked-up object.
- ruff and mypy on the three source files.
- In a worktree, set `PYTHONPATH` to the worktree `src`. Never `uv sync` or `uv run`.

---

## §4 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/adapters/polymarket_us/exec/client.py` | Append `resume_if_refusals_cleared()` after `_refuse` (§2.1). Its docstring cites `component.pyx:1650/1641/1646`, the `is_latched` fail-closed rationale, why it is not called from the resolver (E0-NOSEND-RESOLVER), and "DEGRADED is an indicator; resume changes no order admission". Nothing else in the file changes. | ~40 lines incl. docstring |
| `src/breezy/runtime/trade_cli.py` | Add `_exec_client_resume_handler(node)` after `_exec_client_resolver_contradiction_reader`. Add `resume_h = _exec_client_resume_handler(node)` and pass `handlers=(recon_h, stale_h, contradiction_h, resume_h)`. Add one sentence to the `_run_node` FU-8b docstring paragraph. | ~25 lines |
| `src/breezy/runtime/component_health_watch.py` | In `install_component_degraded_alert`, add the RUNNING re-arm branch (§2.2) and update the Notes paragraph. The module docstring's "alerts and does nothing else" stays TRUE, because the resume is NOT in this module. | ~6 lines |
| `tests/unit/test_ambig_latch_resume.py` | New: T1-T8. | new |
| `tests/unit/test_exec_refusal_health_surface.py` | Append T9 and T10. | append |
| `tests/unit/test_trade_cli.py` | Append T11 and T12. | append |
| `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` | Re-pin `_EXEC_CLIENT_SHA256` (reviewer-approved). | 1 line |
| `docs/core/PROGRESS.md` | Close the AMBIG-LATCH-RESUME row with the merge sha. | doc |

Not touched:
- `submit_intent.py`, `safety.py`, the permit, `operator.env` or any operator cap, live-enablement or A1 halt, `allow_short`.
- The supervisor and the `.venv/` Nautilus package.

---

## §5 Live activation

- **Load point.** All three source files load in the node process (`breezy-trade`). Activation requires a node respawn. The supervisor process does not import them, so no supervisor restart is needed.
- **Timing.** Per "activate code immediately", relaunch right after the gate-green merge, inside 01:00-16:40Z, using the established hand relaunch: `systemd-run --user`, mirroring `spawn()`, with the A-1 permit ceiling and the open-intent probe after stop.
  - **Technical hold condition:** do not relaunch while the open-intent probe shows an OPEN intent. A boot with an unresolved intent refuses once. Wait for the resolver to retire it, or defer to the next scheduled launch.
  - Outside the window, the change loads at the next scheduled launch.
- **Boot proof.** The usual 4 boot lines, the permit line, and supervisor `permit_watch_adopted_live_node`, all in the node log FILE, not journald. The `refusal re-poll timer armed` line must be present, since that is the trigger.
- **Positive in-service proof.** Expected at the first AMBIGUOUS take, which is routine because every IOC miss is AMBIGUOUS. In the node log file, in this order:
  1. `Trading refused: <AMBIGUOUS_REASON>` plus a `component_degraded` CRITICAL alert;
  2. `resolver: retired intent ... (STATUS_REPORT_ZERO_FILL_TERMINAL)`;
  3. `resolver: cleared the AMBIGUOUS trading refusal`;
  4. within ≤60 s, `health: resumed from DEGRADED ...` plus the native `RUNNING` INFO line from the client;
  5. on the NEXT AMBIGUOUS take, a SECOND `component_degraded` alert.
- **Negative proof.** No `InvalidStateTrigger` ERROR lines from the client. A `RESUMING`/`RUNNING` line must never appear between an `arm` and its retirement.

## §6 Rollback

- `git revert <merge sha>`. This also restores the prior `_EXEC_CLIENT_SHA256`, then run the full gate and do a hand relaunch.
- Behaviour after rollback is exactly the `3eb4a108` state: trading continues, and health stays DEGRADED after the first refusal.
- There is no durable state, schema or store key to migrate. The method writes nothing, and the alert set is in-memory.

## §7 Risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| **Alert volume.** Every IOC miss is AMBIGUOUS, so every miss now produces one CRITICAL `component_degraded` alert, where before only the first per process did. | Likely. Bounded by the take count, which the operator caps already limit. | This is the requested behaviour ("a later refusal will not re-alert" is the defect). There is still one alert per episode, not per refusal. If peers judge the volume a problem, the follow-up is an `AlertState(renotify_after_ns)` throttle on this alert (the existing primitive). That is out of scope here; do not pre-build it (YAGNI). |
| ≤60 s of residual DEGRADED after the clear. | Certain, harmless. DEGRADED gates no order. | It is the re-poll interval. Shortening it is not justified. |
| The `_resolve_accept_fill` path never clears AMBIGUOUS (`test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal`), so the client stays DEGRADED after a filled AMBIGUOUS. | Existing behaviour, out of scope. | The predicate requires an empty refusal list, so this plan resumes only after the clears that already exist. Record it as a follow-up row only if peers rule that the fill path should clear. |
| A future `_resume` override adds an action that reaches I/O. | Low. | T6 MRO pin. |
| A future edit calls the method from the resolver. | Low. | E0-NOSEND-RESOLVER rejects it unmodified, and T8 makes that explicit. |
| `is_latched` / `_require_held` raises when the latch is not held. | Low. | Caught; return False and log a WARNING with the type name only (T3). |
| A resume racing an in-flight take. | None. It runs single-threaded on the loop thread, the method is fully sync, and `is_latched` is True from `arm` onward. | T2. |
| The sha re-pin is read as weakening a safety test. | Process risk. | The reviewer verifies an additions-only diff after the deny chain (§3). The pin's assertion is unchanged. |
| `current_rung_hold` `_on_event` re-evaluates alerters on two extra events per resume. | Negligible. | The alerters dedupe on count change. |

## §8 Build sequence

1. T1-T12 written and RED, except T6, which is GREEN as a guard. Capture the output.
2. `client.py` method: T1-T8 GREEN, then re-pin the sha.
3. `component_health_watch.py` re-arm: T9 and T10 GREEN.
4. `trade_cli.py` handler and wiring: T11 and T12 GREEN.
5. Full gate (EXIT=0), `lint-imports`, ruff and mypy.
6. Independent review. Before merge, two reviewers who did not build the change: `prediction-market-reviewer` or `trading-bot-architect` for FSM and invariants, and `security-reviewer` for the NO-SEND proof in §2.3.
7. Merge, then the §5 relaunch, then update PROGRESS.

## §9 Self-assessment

**Score: 90/100.**

Open points for peers:
- Whether the alert-volume risk needs the throttle in this item rather than as a follow-up.
- Whether `_latch is None` returning fail-closed (never resume in a latch-less shadow node) is the right default.
- Rig detail: T1 assumes the `_arm_one_ambiguous_intent` rig can be `start()`ed into RUNNING before the take. If it cannot, T1 must build the rig through the `_build_rig` path from `test_exec_refusal_health_surface.py` instead.
