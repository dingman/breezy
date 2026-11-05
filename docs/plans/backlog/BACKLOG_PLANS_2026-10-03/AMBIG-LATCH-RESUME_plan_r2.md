# AMBIG-LATCH-RESUME — plan r2 (2026-10-03)

Status: DRAFT r2 for peer re-review. Plan only; nothing is implemented.
Supersedes: `AMBIG-LATCH-RESUME_plan_r1.md` (unchanged). Review applied: `reviews/AMBIG-LATCH-RESUME-r1-merged.md` (A1–A5 + 3 LOW). See **§R2 Disposition** at the end.
Item (docs/core/PROGRESS.md:96): AMBIG-LATCH-CLEAR (`3eb4a108`) leaves the exec client DEGRADED after the clear. Health reads DEGRADED while the client trades, and a later refusal does not re-alert. Call native `resume()` from outside the resolver.

Evidence base: commits `87b3725b` and `3eb4a108` (messages + diffs), `docs/plans/refactor_2026-10-01/EXECUTION_LOG_2026-10-02.md:96,113`, `tests/unit/test_execution_egress_firewall_guard.py:2099-2281` (resolver allowlist, `len` at :2270), `tests/unit/test_fq_caps_and_ambiguous_2026_10_01.py:387-417`, Nautilus `common/component.pyx` and `execution/engine.pyx`. `$NT` line numbers were read with `/usr/bin/grep -rn` against `.venv/lib/python3.13/site-packages/nautilus_trader` (positive control: `class Component` matched in `component.pyx`). Live-store figures (§2.7) were read with python `sqlite3` opened `file:...?mode=ro`, nothing written.

---

## §0 Problem and goal state

### Problem (three defects)

**D1. The FSM stays DEGRADED.**
- `_refuse` (`exec/client.py:5896-5976`) calls `self.degrade()` on the first refusal while not degraded.
- `_resolve_terminal_zero` (`:3100-3112`) clears the AMBIGUOUS entry from `_trading_refusals` as its last step.
- Nothing ever calls `resume()`, so the native state stays `DEGRADED` for the rest of the process. In `$NT` the only native `.resume()` / `.degrade()` call on an adapter is `adapters/betfair/data.py:401`.

**D2. The alert latch is permanent.** `install_component_degraded_alert` (`runtime/component_health_watch.py:628-703`) adds `component_id` to `alerted` on the first DEGRADED and never removes it, so a second `RUNNING -> DEGRADED` is silently swallowed.

**D3. A filled AMBIGUOUS never clears (new in r2, coordinator ruling A3).** `_resolve_accept_fill` (`:3114-3317`) retires the intent as `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, records the fill durably, trues up the booking, and publishes the native fill, but leaves the AMBIGUOUS entry in `_trading_refusals`. Pinned today by `test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` (`test_fq_caps_and_ambiguous_2026_10_01.py:387`). Provenance: commit `87b3725b` scoped the clear to terminal zero-fill as a *scope choice* ("Still latches: ... the AMBIGUOUS refusal on any fill or accept-fill terminal path"); it gives no safety rationale for the fill path. Consequence, stronger than a health defect: because `_submit_order` denies while `_trading_refusals` is non-empty (`:5357-5359`), **a filled AMBIGUOUS today denies every later order for the rest of the process**, and D1 then keeps it DEGRADED.

**Side effect of D1.** `ExecutionEngine._stop` / `stop_clients` (`$NT/execution/engine.pyx:727-729, 770-772`) call `client.stop()` only `if client.is_running` (RUNNING only, `component.pyx:1819-1828`). A client that stays DEGRADED is skipped by the engine's own stop; resuming restores the normal shutdown path.

### Goal state (acceptance test)

After **any** resolver retirement of an AMBIGUOUS intent (terminal zero-fill OR accept-fill), all of the following hold:
1. The intent is retired, the booking is trued up, the permit slot is restored (zero-fill) or kept spent (fill), and the AMBIGUOUS refusal is cleared, while every other refusal reason stays.
2. Within one resolver pass plus one `REFUSAL_REPOLL_INTERVAL` (60 s, `component_health_watch.py:476`), the exec client goes `DEGRADED -> RESUMING -> RUNNING` through native `Component.resume()`.
3. `client.is_degraded` is False and `client.is_running` is True.
4. The next refusal of any reason drives a fresh `degrade()` and the DEGRADED alert re-arms. It emits one new `component_degraded` CRITICAL alert, unless the throttle (§2.3) suppresses it. Suppression applies only when the same-or-subset reason set was alerted less than `DEGRADED_ALERT_RENOTIFY_AFTER_NS` (1 h) earlier. A suppressed episode logs exactly one WARNING line instead.
5. No `DEGRADED -> RUNNING` transition happens while the durable submit intent is OPEN or corrupt, or while any entry remains in `_trading_refusals`. If a refusal lands during RESUMING, the client ends DEGRADED (§2.6).
6. RUNNING is not proof the node can trade. Order admission is unchanged by the resume (§2.4).

---

## §1 Null hypothesis (L-1): what Nautilus and Breezy already provide

| Need | Native / existing capability | Verdict |
|---|---|---|
| Leave DEGRADED | `Component.resume()` (`component.pyx:2003-2032`). Edges `(DEGRADED, RESUME) -> RESUMING` (`:1650`) and `(RESUMING, RESUME_COMPLETED) -> RUNNING` (`:1641`). The action `self._resume` is `pass` in `Component` (`:1904-1906`), not overridden by `ExecutionClient`, `LiveExecutionClient` or Breezy (grep `def _resume` in `src/`: 0 hits). | **REUSE as-is.** |
| Re-enter DEGRADED after a race | `Component.degrade()` (`:2098-2127`), legal from RUNNING (`:1638`). NOT legal from RESUMING (no `(RESUMING, DEGRADE)` edge; `:1640-1642` lists STOP, RESUME_COMPLETED, FAULT only). | **REUSE.** It is the same call `_refuse` makes. The RESUMING gap is handled by a post-resume re-check (§2.6). |
| Publish the transition | `_trigger_fsm` publishes `ComponentStateChanged` on `events.system.<id>`, stamped with `ts_event = self._clock.timestamp_ns()` (`:2187-2225`). An invalid trigger logs ERROR and returns (`:2192-2196`). | REUSE. `ts_event` is the throttle's clock, so the subscriber needs no clock of its own. |
| Run periodically on the loop thread | `install_refusal_repoll_timer` (`component_health_watch.py:490-625`), armed in `trade_cli._run_node` (`trade_cli.py:625-635`). Thread model is measured (`tests/contract/test_refusal_repoll_live_clock_contract.py`). | **REUSE.** Add one handler. |
| Reach the client from runtime | The `_exec_client_*_reader` idiom (`trade_cli.py:393-484`). | REUSE the idiom. |
| "Is an AMBIGUOUS intent open?" | `SubmitIntentLatch.is_latched()` (`runtime/submit_intent.py:378-389`): True if OPEN or corrupt (fail-closed). | **REUSE.** |
| Clear AMBIGUOUS on a retirement | The inline clear in `_resolve_terminal_zero` (`:3100-3112`). Its callees are `self._latch.current_open`, `len` and `self._log.info`, all already in `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2130`, `:2270`, `:2136`). | **REUSE the same inline block** in `_resolve_accept_fill`. No helper and no allowlist widening. |
| Alert re-notify throttle | `health.AlertState(renotify_after_ns=...)` (`health.py:518-578`). Its rule is "false->true always fires; true->true re-fires after the window". That is a *standing-condition* re-notifier: it can never suppress a transition, and each new DEGRADED episode is a transition. Adopting it would require changing its semantics, which its other users depend on (`halt_detector`, `weather_common/refusals`, `current_rung_hold/composition`). | **NOT reusable for a transition throttle.** Keep the same name and units (`renotify_after_ns`, int ns), and implement it as closure state beside the existing `alerted` set (§2.3). |

Conclusion: nothing new is invented except an in-closure throttle. That throttle exists because the one existing primitive has the opposite firing rule.

---

## §2 Design

### 2.1 Resume call site: a sync client method, driven by the runtime re-poll timer

**New public sync method on `PolymarketUSExecutionClient`: `resume_if_refusals_cleared() -> bool`.**
- Placement: directly after `_refuse` and before `__repr__` (`client.py:~5977`), after the deny chain.
- Returns True iff the call ends with the client RUNNING.
- Callees are exactly `self._latch.is_latched`, `self.resume`, `self.degrade`, `self._log.info` and `self._log.warning`. Body, in order:
  1. `if not self.is_degraded: return False`. This is a property read. It skips RUNNING, RESUMING, DEGRADING, STOPPING and STOPPED. It matters most for STOPPED, because `(STOPPED, RESUME)` is also a legal native edge (`:1646`).
  2. `if self._trading_refusals: return False`. Any refusal reason keeps the client DEGRADED.
  3. `if self._latch is None: return False`. Fail-closed, kept from r1; see §R2 open point O2.
  4. `try: latched = self._latch.is_latched()`, then `except Exception: self._log.warning(<type name only>); return False`.
  5. `if latched: return False`. This covers an OPEN or corrupt intent.
  6. `self.resume()`.
  7. **Post-resume re-check (A5):** `if self._trading_refusals and not self.is_degraded:` log one WARNING (`health: a refusal landed during RESUMING; re-degrading`), call `self.degrade()`, and `return False`.
  8. `self._log.info("health: resumed from DEGRADED (no refusals, no open submit intent)")`, then `return True`.
- Thread safety: it runs on `node.kernel.loop` (the `_poll` hop), the same loop as the resolver, `_submit_order` and `_refuse`. It has no `await`. The only way a refusal can interleave between steps 1-5 and step 8 is re-entrantly, from a synchronous msgbus subscriber reacting to the RESUMING publish. Step 7 closes that window (§2.6).

**Runtime trigger: `_exec_client_resume_handler(node) -> Callable[[object], None]` in `runtime/trade_cli.py`.**
- Placed beside the `_exec_client_*_reader` helpers, using the same lazy lookup. A missing client or attribute is a no-op (`getattr(..., None)`).
- Appended LAST to `handlers=` at `trade_cli.py:629`. `_poll` already isolates each handler in `try/except Exception`.
- If the re-poll timer fails to arm (`trade_cli.py:634-635`), no resume happens. The client then stays DEGRADED, which is exactly today's behaviour (fail-safe).

**Why not the alternatives:** this is unchanged from r1.
- Calling from the resolver trips E0-NOSEND-RESOLVER.
- Calling from `_submit_order` trips E0-NOSEND.
- A client-owned `set_timer` callback runs on a tokio thread (L-16).
- No `ComponentStateChanged` fires on a clear.
- A new coroutine breaks E0-INERT.
- Putting the predicate in runtime would mean reading private state from runtime.

### 2.2 Accept-fill clears AMBIGUOUS (A3, coordinator ruling)

In `_resolve_accept_fill`, as the **last statement**, after `self.generate_order_filled(...)` (`:3298-3317`), add the same inline block `_resolve_terminal_zero` uses (`:3100-3112`):
- `if self._latch.current_open() is None:`, then build a new list without entries whose `reason == submit_chain.AMBIGUOUS_REASON`.
- If the length changed, assign it and log one INFO: `resolver: cleared the AMBIGUOUS trading refusal (...) on fill retirement of intent <id>`.
- Use a new list with no in-place mutation, and do not add a helper.

Why last:
- **Any raise above keeps the refusal, the conservative direction** (same reasoning as `3eb4a108`). That covers `record_fill` (early return on `_FILL_WRITE_FAILED`), the venue-id map, `_retire`, `true_up_booking`, `unrestore_live_trading_budget` and `generate_order_filled`.
- Once `_retire` has run, the next pass takes the `current is None` early return (`:3165-3167`), so nothing after `_retire` is ever retried. The clear therefore must not run before those steps.

**The cross-session early return (`_resolver_fill_order_unknown` True, `:3296-3297`) never reaches the clear, and that is complete:**
- `AMBIGUOUS_REASON` has exactly two `_refuse` producers, both inside `_submit_order` (`:5556`, `:5800`). An entry can therefore exist only in the process that submitted the order.
- A process that submitted the order finds it in `self._cache`, so the helper returns False (`:4244-4245`) and execution reaches the clear.
- The submit latch is a singleton, so no other intent's AMBIGUOUS entry can coexist.
- T15 pins this premise.

**Kept refusals are unchanged.** `_VENUE_ID_MAP_WRITE_FAILED` (`:3253`) and `_RESOLVER_FILL_UNBUDGETED` (`:3291`), and every other reason, stay. So does the informational `RESOLVER_FILL_NOT_BOOKED` reconciliation latch, which lives in a separate dict and is not a trading refusal. Any of them keeps the client DEGRADED and denying.

**Firewall: no widening.** The block's callees (`self._latch.current_open`, `len`, `self._log.info`) are all already in `EXEC_RESOLVER_PERMITTED_CALLEES`. `_resolve_accept_fill` is already in `EXEC_RESOLVER_COROUTINES`, so E0-NOSEND-RESOLVER scans the new lines unmodified. **Stop condition:** if implementation finds the clear needs any callee outside that set, stop and report. Do not widen.

**This DOES change order admission, unlike the resume.**
- After a GET-confirmed fill, a later take is admitted again instead of being denied for the rest of the process.
- Justification:
  - The AMBIGUOUS refusal exists because the outcome is unknown. Once a terminal GET has confirmed the fill, `record_fill` has written it durably, `true_up_booking` has charged the filled cost to the ledger, and `_retire` has closed the singleton, the refusal no longer has a subject.
  - Exposure stays bounded by gates this item does not touch: the permit and its budget (the fill is spent, not restored; `unrestore` still applies when a superseded zero-fill had restored), the two operator caps, the latch, and the family halt.
  - It is the same reasoning `87b3725b`/`3eb4a108` already applied to zero-fill, now applied to the one remaining terminal.
- The security reviewer must sign off on this specifically.

**Docstring carve-out:** invariant 1 at `client.py:177-178` becomes "Sole carve-out: resolver-retired terminal zero-fill or accept-fill clears the AMBIGUOUS refusal only (2026-10-02; accept-fill 2026-10-03)". Its pin `test_a_latched_refusal_persists_across_a_reconnect_after_the_condition_clears` does not read the docstring and stays unedited and green.

### 2.3 Re-alert with a throttle (A2, coordinator ruling: build now)

All of this lives in `install_component_degraded_alert` (`component_health_watch.py:628-703`).

**New constant:**
```python
#: One hour. The measured AMBIGUOUS-episode rate is <=1/day (§2.7), so this never
#: binds on observed data; it caps a storm (e.g. a venue outage turning every take
#: AMBIGUOUS) at one identical CRITICAL per hour. Same units/name as health.AlertState.
DEGRADED_ALERT_RENOTIFY_AFTER_NS: Final[int] = 60 * 60 * 1_000_000_000
```

**Signature change:** add a keyword-only parameter `renotify_after_ns: int = DEGRADED_ALERT_RENOTIFY_AFTER_NS`. A `bool`, a non-int or a value ≤ 0 raises `ValueError` at install time. `trade_cli.py:608-612` is unchanged and takes the default.

**Closure state:** keep the existing `alerted: set[str]` (the per-episode latch). Add `last_alert: tuple[int, frozenset[str]] | None = None` (when the last alert was emitted, and which reasons it carried).

**Handler rules, on `ComponentStateChanged` for `component_id`:**
- **RUNNING:** `alerted.discard(component_id)`, then return. The episode ends; `last_alert` is NOT reset.
- **DEGRADED, already alerted this episode:** return. This is unchanged and preserves `test_a_second_refusal_does_not_re_alert`.
- **DEGRADED, first in this episode:**
  1. `alerted.add(component_id)`. The episode is consumed whether it alerts or is suppressed.
  2. Read the reasons as today (the reader-failure fallback is unchanged).
  3. Compute `elapsed = event.ts_event - last_alert[0]`.
  4. **Suppress** iff `last_alert is not None`, `0 <= elapsed < renotify_after_ns`, and `frozenset(recorded) <= last_alert[1]`. Suppression logs one `logger.warning("component_degraded alert throttled component=%s reasons=%d since_last_s=%d", ...)` and returns.
  5. Otherwise, emit exactly as today and set `last_alert = (event.ts_event, frozenset(recorded))`.

**Semantics:**
- The first-ever DEGRADED always alerts (cold start).
- After a RUNNING re-arm, the next episode alerts unless it is a repeat of an already-alerted reason set inside the window. **Re-notification is at most once per interval per repeated episode,** as ruled.
- **A reason the operator has not been alerted on inside the window bypasses the throttle.** This refinement keeps the throttle from hiding a new, durable reason (for example `_FILL_WRITE_FAILED`) behind a routine AMBIGUOUS alert from a few minutes earlier. It never adds alerts in the routine AMBIGUOUS-only case. Peers should confirm it reads as within the A2 ruling (§R2 note).
- A clock that runs backwards (`elapsed < 0`) alerts. The failure direction is toward the operator.
- `REASONS_UNAVAILABLE` is a reason string like any other, so a reader failure after a real alert is a new reason set and alerts.
- The handler is single-threaded on the loop and the state is in-memory and per process, like `AlertState`.

**Docstring Notes** become: "only the FIRST DEGRADED per degraded *episode* is considered; an episode ends on RUNNING. A repeat episode whose reasons were all alerted within `renotify_after_ns` is logged at WARNING instead of re-alerted."

### 2.4 Scope: what RUNNING does and does not mean, and why the resume cannot send (A4 + r1 §2.3)

**Scope statement (A4).**
- The FSM/health RUNNING state **never gates sending and is not proof the node can trade.**
- Sending stays gated, unchanged, by:
  - the `_trading_refusals` list (`_submit_order:5357`);
  - the live-trading permit and its budget (`safety.py`, minted at boot, ceilinged by A-1, untouched);
  - the submit-intent latch (`is_latched`);
  - the strategy-side family halt (`continuous_rung_hold/halt`, `trial_day_latch.family_halt_key`, read by the strategy never-arm gate);
  - the operator caps.
- `resume_if_refusals_cleared` reads none of these except `is_latched` and `_trading_refusals`, and writes none of them.
- Liveness for operators stays as the memory and runbook define it: process, log mtime, **permit unexpired**, and tape advancing. RUNNING does not replace it.
- Only the §2.2 accept-fill clear changes admission. It is the refusal-list edit justified there, not the FSM change.

**Proof the resume cannot send.** Each step is pinned by a §3 test.
1. **Trigger chain:** `LiveClock timer -> _on_timer -> loop.call_soon_threadsafe(_poll) -> _exec_client_resume_handler -> client.resume_if_refusals_cleared()`. No frame reaches `_order_sender`, `_private_read`, `submit_chain` or any `exec/` coroutine.
2. **Method body:** the callee set equals `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`. There is no `await`, it is not a coroutine, and there is no `create_task`, `asyncio.*` or `threading.*` (T5).
3. **Native actions:** `resume()` runs `Component._resume` and `degrade()` runs `Component._degrade`, both `pass`. An MRO pin (T6) asserts no class between the client and `Component` defines either.
4. **Published events:** `ComponentStateChanged` on `events.system.POLYMARKET_US` only. Subscribers:
   - native: none (`$NT` grep `events.system`: publisher only, `component.pyx:2223`);
   - Breezy `component_health_watch` (alert-only);
   - Breezy `strategy/current_rung_hold/composition.py:905-922` `_on_event` (`RefusalAlerter.report`).
   
   None of them submits, cancels or modifies an order (T7).
5. **Admission is unchanged by resume:** T20 and T21 (A4).
6. **The firewall is untouched:** T8a/T8b.

### 2.5 The "never resume while AMBIGUOUS is open" invariant

The guard is layered:
- **(a)** Both clears (`_resolve_terminal_zero` `:3100`, and the new accept-fill block) run only when `current_open() is None`.
- **(b)** The method requires an empty `_trading_refusals`.
- **(c)** The method independently requires `is_latched() is False`. This covers an OPEN or corrupt intent and the in-flight `arm -> post_order` window.
- **(d)** Steps 1-6 run in one synchronous frame, and step 7 re-checks after the only re-entrant window.

T2 and T3 pin (c) with the list empty.

### 2.6 Races (A5)

| Race | Mechanism | Outcome with r2 | Test |
|---|---|---|---|
| Refusal **during RESUMING** | It can only happen re-entrantly, from a synchronous subscriber to the RESUMING publish (`resume()` runs `_trigger_fsm(RESUME)` -> publish -> `_trigger_fsm(RESUME_COMPLETED)` in one frame). `_refuse` then sees `is_degraded` False and appends. Its `degrade()` hits the missing `(RESUMING, DEGRADE)` edge: one native ERROR is logged, there is no state change, and then RESUME_COMPLETED moves to RUNNING with a non-empty list. No production subscriber calls `_refuse` today, so this is a latent gap, not a live one. | Step 7 sees `_trading_refusals` non-empty while RUNNING. It logs a WARNING, calls `degrade()` (legal from RUNNING), and returns False. The events are RESUMING, RUNNING (re-arm), DEGRADING, DEGRADED. The alert fires: the new reason bypasses the throttle; the same reason inside the window is throttled. | T22 |
| Refusal **after resume** | The ordinary `_refuse` from RUNNING: `was_already_degraded` is False, so `degrade()` runs. | DEGRADED, and the alert re-armed by RUNNING fires subject to §2.3. | T23 (both within and beyond the window) |
| Resume vs an in-flight take | `is_latched` is True from `arm` onward, and everything runs on one loop thread. | No resume. | T2 |
| Resume from DEGRADING | `is_degraded` is False in DEGRADING. | No-op, so the invalid `(DEGRADING, RESUME)` edge is never triggered. | T4 |

### 2.7 Measured alert volume (A2), read-only from the live exec store

Source: `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, opened `mode=ro`, keys `exec/polymarket_us/intent/current` and `exec/polymarket_us/intent/history/*`. `submit_intent.py` has no prune or delete path, so the history is complete. Window: 2026-09-05 to 2026-10-03 (29 calendar days, store WAL mtime 16:15Z on 10-03). An intent is one take.

| Metric | Value |
|---|---|
| Takes (intents, excluding 1 `OPERATOR_CLEARED`) | **24** over 9 active days: **0.83/calendar day**, **2.7/active day**, max 6 (10-01). Since FQ went live: 10-01 = 6, 10-02 = 5, 10-03 = 2 (partial), so **~4.3/day** |
| AMBIGUOUS episodes (resolver-retired) | **5/24 = 20.8%**: 3 `STATUS_REPORT_ZERO_FILL_TERMINAL` (09-23, 10-01, 10-02) + 2 `STATUS_REPORT_ACCEPT_FILL_TERMINAL` (09-11, 09-13) |
| **IOC-miss rate** (zero-fill terminal / takes) | **3/24 = 12.5%** overall, **2/13 = 15.4%** since 10-01. `ACCEPTED_ZERO_FILL_TERMINAL` = 0 ever, which confirms every IOC miss goes AMBIGUOUS |
| Max AMBIGUOUS per day | **1** |
| Create-to-retire latency | Same process: 3.2 s (fill), 120.8 s, 138.3 s (zero-fill). Cross-process: 6.1 h (fill), 26.9 h (zero-fill) |

**Expected `component_degraded` volume.**
- At most one per in-process AMBIGUOUS episode, plus any non-AMBIGUOUS refusal episode.
- Observed history implies about 5 per 29 days: **≈0.17/calendar day, ≈0.56/active day, never more than 1/day**.
- At the post-10-01 take rate (4.3/day × 20.8%): **≈0.9/day**.
- The 1 h throttle suppresses **0** of the observed episodes. It exists for the storm case, where it caps repeats at ≤1 per hour per reason set.
- Before this change: at most 1 alert per process.

---

## §3 Tests: RED -> GREEN

New tests go in new files or are appended to the named files. RED is shown by running each new test against the unmodified tree; record RED and GREEN output as the change artifact.

**One existing assertion is intentionally inverted** (A3, coordinator ruling), and it is the only exception:
- `test_fq_caps_and_ambiguous_2026_10_01.py::test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` is renamed to `test_a_fill_terminal_retirement_clears_the_ambiguous_refusal`.
- Its rig and the three retirement-reason assertions stay verbatim. The final line flips to `assert _AMBIGUOUS_REASON not in client.trading_refusals`.
- It pinned a scope choice (`87b3725b`), not a safety property.
- Every other "still latches" pin stays unmodified: incomplete join, non-terminal GET, create time, permit-restore raise, true-up raise, and corrupt post-retire read.
- The reviewer must confirm that this is the only edited assertion in the diff.

| # | File | Test | RED today because |
|---|---|---|---|
| T1 | `tests/unit/test_ambig_latch_resume.py` (new) | `test_terminal_zero_clear_then_resume_returns_the_client_to_running`. Uses the `_arm_one_ambiguous_intent` + `_run_resolver_passes` rig. Precondition: `start()` ran and `is_degraded` is True after the take. After the pass, `resume_if_refusals_cleared()` returns True, `is_running` is True and `is_degraded` is False. | AttributeError |
| T2 | same | `test_resume_refused_while_the_submit_intent_is_open`: list emptied by assignment, latch OPEN. Returns False and stays DEGRADED. | AttributeError |
| T3 | same | `test_resume_refused_when_the_latch_read_is_corrupt_or_raises`: corrupt singleton, then separately a raising `is_latched`. Both return False and stay DEGRADED. The raising case logs a WARNING with the type name only. | AttributeError |
| T4 | same | `test_resume_is_a_no_op_unless_degraded`: (i) RUNNING returns False with no `InvalidStateTrigger` ERROR; (ii) STOPPED stays STOPPED; (iii) DEGRADING (driven by a spy that blocks `DEGRADE_COMPLETED`, or a direct `_fsm` read of the rig) returns False; (iv) a remaining `_UNRELATED_REFUSAL` returns False; (v) `_latch is None` returns False. | AttributeError |
| T5 | same | `test_resume_method_callee_set_is_exactly_pinned`: AST, `_dotted_callee` semantics. Callees EQUAL `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`. No `Await`/`AsyncFor`/`AsyncWith`, and it is a `FunctionDef`. Planting `self._order_sender.post_order` in a source copy fails (non-vacuity). | method absent |
| T6 | same | `test_resume_and_degrade_actions_are_the_native_no_ops`: for `name in ("_resume", "_degrade")`, `[c for c in type(client).__mro__ if name in vars(c)] == [Component]`. | GREEN today (guard) |
| T7 | same | `test_resume_publishes_only_the_component_state_topic_and_never_reaches_the_sender`: subscribe `*` and spy `post_order`. Topics are only `events.system.<id>`, states are `[RESUMING, RUNNING]`, and `sender.calls` is unchanged. | AttributeError |
| T8a | same | **Pure guard (LOW split):** `test_the_resume_method_name_is_outside_every_firewall_scope`. `"resume_if_refusals_cleared"` is not in `EXEC_RESOLVER_COROUTINES`, `ORDER_LIFECYCLE_COROUTINES` or `EXEC_PERMITTED_COROUTINE_NAMES`. None of `self.resume`, `self.degrade` or `self.resume_if_refusals_cleared` is in `EXEC_RESOLVER_PERMITTED_CALLEES` or `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (constants imported read-only). | GREEN today (guard) |
| T8b | same | **RED (LOW split):** `test_the_resume_method_exists_as_a_sync_method_on_the_client`. The `client.py` AST has `PolymarketUSExecutionClient.resume_if_refusals_cleared` as a `FunctionDef` placed after `_refuse`. | method absent |
| T9 | `tests/unit/test_exec_refusal_health_surface.py` (append) | `test_a_refusal_after_resume_re_alerts_exactly_once`. Real rig: refuse A (1 alert), clear, resume, refuse B (a different reason, so it bypasses the throttle): 2 alerts. Refuse C while still DEGRADED: still 2. | 1 alert (D2) + AttributeError |
| T10 | same (append) | `test_running_re_arms_the_degraded_alert_for_the_same_component_only`. Synthetic events with `ts_event` gaps ≥ the window. DEGRADED(X), RUNNING(X), DEGRADED(X) gives 2. DEGRADED(X), RUNNING(OTHER), DEGRADED(X) gives 1. | 1 (D2) |
| T11 | `tests/unit/test_trade_cli.py` (append) | `test_repoll_timer_resumes_a_cleared_exec_client`: `RecordingNode` + `_fire_repoll` with a fake client. One fire gives one call. A missing client or attribute does not raise, and the siblings still fire. | 0 calls |
| T12 | same | `test_resume_handler_is_wired_last_in_the_repoll_handler_tuple`: captured `handlers` has length 4, and the last element's `__qualname__` contains `_exec_client_resume_handler`. | length 3 |
| T13 | `tests/unit/test_ambig_latch_resume.py` | **A3:** `test_accept_fill_retirement_clears_the_ambiguous_refusal_and_the_client_resumes`. Evidence `ORDER_STATE_FILLED`, cum=1, LONG held, avg_px 0.40 (the `_set_get_evidence` shape from `test_fq_caps...:240`). After one pass: retired `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, AMBIGUOUS gone, the INFO "cleared ... on fill retirement" is logged, and `resume_if_refusals_cleared()` returns True with `is_running`. | AMBIGUOUS still present |
| T14 | same | **A3:** `test_accept_fill_clear_keeps_every_other_refusal`. (i) `record_venue_order_id` monkeypatched to raise: AMBIGUOUS is cleared but `_VENUE_ID_MAP_WRITE_FAILED` stays, so resume returns False. (ii) A cross-process (`booking is None`, `_spend_seeded`) BUY fill: `_RESOLVER_FILL_UNBUDGETED` stays, so resume returns False. | AMBIGUOUS still present |
| T15 | same | **A3 guards** (GREEN today, pinned): (i) `record_fill` raising takes the `_FILL_WRITE_FAILED` early return and AMBIGUOUS stays. (ii) `generate_order_filled` raising (the resolver counts the error) keeps AMBIGUOUS. (iii) An AST pin: every `self._refuse(submit_chain.AMBIGUOUS_REASON)` call site is inside `_submit_order`. That is the premise for the cross-session-return completeness argument in §2.2. | GREEN (guard) |
| T16 | same | **A3:** `test_after_an_accept_fill_clear_a_take_reaches_the_sender`. Mirrors `test_terminal_zero_fill_retirement_clears_ambiguous_refusal_and_a_take_reaches_sender`: with the operator gate enabled and caps set, a second take after the clear reaches `post_order` exactly once, and the ledger shows the filled cost spent (not restored). | denied (AMBIGUOUS latched) |
| T17 | `tests/unit/test_component_health_watch_degraded_throttle.py` (new) | `test_a_repeat_episode_inside_the_window_is_throttled_and_logged_once`. Same reason set, gap < 1 h: 1 alert, plus exactly one WARNING `component_degraded alert throttled`. | no throttle: 2 alerts (after the re-arm) |
| T18 | same | `test_a_repeat_episode_after_the_window_re_alerts`. Gap = `DEGRADED_ALERT_RENOTIFY_AFTER_NS` exactly: 2 alerts (boundary is `>=`). | constant missing |
| T19 | same | `test_a_new_reason_inside_the_window_bypasses_the_throttle`, `test_a_backwards_clock_alerts`, `test_a_reader_failure_after_an_alert_still_alerts`, `test_one_alert_per_episode_regardless_of_the_throttle`, `test_invalid_renotify_after_ns_is_rejected_at_install` (0, -1, `True`, `1.5`), `test_the_default_window_is_one_hour_and_trade_cli_uses_the_default`. | constant/param missing |
| T20 | `tests/unit/test_ambig_latch_resume.py` | **A4:** `test_resume_leaves_order_admission_unchanged_while_the_permit_is_invalid`. Rig with no valid permit (no `enable_operator_gate`; if the rig cannot reach DEGRADED that way, an expired permit). Drive DEGRADED, empty the list, record the `_deny` reason for one take, then resume and submit the same take: **identical deny reason**, `post_order` calls 0. | AttributeError |
| T21 | same | **A4:** `test_resume_writes_nothing_durable_and_leaves_a_set_family_halt_set`. Write `family_halt_key(<family>)` and the legacy `continuous_rung_hold/halt` into the rig store, snapshot every `(key, value)`, resume, and snapshot again: **byte-identical** (halt, intent singleton and permit-restore keys untouched). `client._permit` is the same object and unchanged. | AttributeError |
| T22 | same | **A5:** `test_a_refusal_during_resuming_ends_degraded_and_re_alerts`. Install the real degraded alert on the rig bus with a recording sink, plus a subscriber that calls `client._refuse(_UNRELATED_REFUSAL)` on the RESUMING event. `resume_if_refusals_cleared()` returns False, `is_degraded` is True, the event sequence is `[RESUMING, RUNNING, DEGRADING, DEGRADED]`, the alert count is +1 (new reason), and one WARNING `refusal landed during RESUMING` is logged. | AttributeError |
| T23 | same | **A5:** `test_a_refusal_after_resume_re_degrades_and_re_alerts_subject_to_the_throttle`. After a resume, `_refuse(AMBIGUOUS_REASON)` gives DEGRADED. With the rig `TestClock` at < 1 h since the last alert: throttled (WARNING, no alert). Repeat the cycle with the clock advanced ≥ 1 h: alert. | AttributeError |

**Unmodified and must stay green:**
- `test_execution_egress_firewall_guard.py`, the entire file and every allowlist constant. E0-NOSEND-RESOLVER now scans the accept-fill clear lines.
- `test_fq_caps_and_ambiguous_2026_10_01.py`, except the one inversion named above.
- `test_exec_refusal_health_surface.py`'s existing tests, including the 25-producer pin. No `_refuse` call site is added.
- `test_component_health_watch_*`, `test_polymarket_us_exec_client.py`, including the NODE-GLOBAL pin.
- `tests/contract/test_refusal_repoll_live_clock_contract.py`.

**One re-pin, reviewer-approved (precedent `3eb4a108`):** `_EXEC_CLIENT_SHA256` in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`, with the comment updated to name this item. The assertion text is unchanged. The r1 claim of "additions only after the deny chain" no longer holds under A3. The PR must instead record the following (LOW):
- `git diff -U0 <base> -- src/breezy/adapters/polymarket_us/exec/client.py`, showing **exactly three hunks**:
  - H1: docstring invariant 1, the carve-out line at `:177-178`. This is the only modified (non-added) line.
  - H2: the accept-fill clear block, additions only, after `generate_order_filled`.
  - H3: the new method, additions only, after `_refuse`.
- A check that the `_submit_order` body (the deny chain) is byte-identical in content. Its lines shift by H2's length. Verify with `git show <base>:<path>` vs HEAD, extract the `_submit_order` function via `ast.get_source_segment`, and compare the sha256 values.
- The old sha `76784ce8…68a4` (equal to the current on-disk sha, verified 2026-10-03) and the new sha.

**Gate:**
- `scripts/ci/run_tests_no_egress.sh`: the full gate. Read EXIT before any push.
- `lint-imports` from the tree root ("N kept, 0 broken").
- ruff and mypy on the three source files.
- In a worktree, set `PYTHONPATH` to the worktree `src`. Never `uv sync`, `uv run` or pip.

---

## §4 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/adapters/polymarket_us/exec/client.py` | H1: carve-out sentence (§2.2). H2: the accept-fill inline clear as the last statement of `_resolve_accept_fill`, with a comment citing A3, the conservative ordering and the cross-session completeness argument. H3: `resume_if_refusals_cleared()` after `_refuse`. Its docstring cites `component.pyx:1650/1641/1646/1638`, the missing RESUMING->DEGRADE edge, `is_latched` fail-closed, why it is not called from the resolver, and "RUNNING is not an order gate". | ~15 + ~55 lines |
| `src/breezy/runtime/trade_cli.py` | `_exec_client_resume_handler(node)`. `handlers=(recon_h, stale_h, contradiction_h, resume_h)`. One sentence in the FU-8b docstring paragraph. | ~25 lines |
| `src/breezy/runtime/component_health_watch.py` | `DEGRADED_ALERT_RENOTIFY_AFTER_NS`. The `renotify_after_ns` keyword with validation. The RUNNING re-arm and the throttle (§2.3). Notes docstring. The module docstring's "alerts and does nothing else" stays true. | ~35 lines |
| `tests/unit/test_ambig_latch_resume.py` | New: T1-T8b, T13-T16, T20-T23. | new |
| `tests/unit/test_component_health_watch_degraded_throttle.py` | New: T17-T19. | new |
| `tests/unit/test_exec_refusal_health_surface.py` | Append T9 and T10. | append |
| `tests/unit/test_trade_cli.py` | Append T11 and T12. | append |
| `tests/unit/test_fq_caps_and_ambiguous_2026_10_01.py` | The one A3 inversion (rename + final assert). | 2 lines |
| `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` | Re-pin `_EXEC_CLIENT_SHA256` and its comment. | 2 lines |
| `docs/core/PROGRESS.md` | Close the row with the merge sha. | doc |

Not touched:
- `submit_intent.py`, `safety.py`, the permit and its ceiling, `operator.env` or either operator cap, live enablement, the A1 family halt, `allow_short` (stays `False`).
- The NO-SEND firewall test and its allowlists.
- The supervisor.
- `.venv/` Nautilus.

---

## §5 Live activation

- **Load point.** All three source files load in the node process (`breezy-trade`), so a node respawn is required. The supervisor does not import them, so no supervisor restart.
- **Timing.** Per "activate code immediately": after the gate-green merge, inside 01:00-16:40Z, use the 2026-10-02 hand-relaunch recipe (scratch script importing the supervisor's own `resolve_store_path`, `intent_lock_path`, `resolve_lock_holder_pid`, `intent_lock_is_free`, `probe_open_intent`, `node_log_path`, `spawn_node`, `_retain_spawned_child`, under `systemd-run --user --scope --unit=breezy-node-handrelaunch-<ts>`). Outside the window, the change loads at the 16:50Z scheduled launch.

### 5.1 Hard precondition and deferral path (A1)

**Never relaunch while an intent is OPEN.** A boot with an unresolved intent refuses once. The probe runs twice: before stop (read-only) and after stop (the supervisor's own probe).

**P1, pre-stop probe (node live, read-only).** `probe_open_intent` must NOT be used here. Its guard `assert_no_live_node_before_intent_probe` forbids a live node pid, and passing `node_pid=None` while the node is live would defeat that guard. Instead, the scratch script runs this exact function, with the env copied in memory from the supervisor (never printed):
```python
import os, sqlite3
from breezy.runtime.exec_state_db_path import resolve_store_path
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY, SubmitIntent, SubmitIntentCorrupt, SubmitIntentState,
)
def intent_open_ro(environ) -> bool:
    path = resolve_store_path(environ)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM state WHERE key = ?", (CURRENT_INTENT_KEY,)).fetchone()
    finally:
        con.close()
    if row is None:
        return False
    try:
        return SubmitIntent.from_bytes(bytes(row[0])).state is SubmitIntentState.OPEN
    except SubmitIntentCorrupt:
        return True  # fail closed, same stance as is_latched / probe_open_intent
```
- The `mode=ro` WAL read was exercised against the live store on 2026-10-03 (§2.7). It takes no flock, and SQLite serves concurrent readers.
- The script prints only `OPEN` or `CLEAR`. Any exception counts as OPEN.

**P2, log-tail check.** Read the last 2,000 lines of the live node log FILE. If any `SubmitOrder` has no matching terminal event (accepted, filled, canceled, rejected or denied), treat it as OPEN.

**Deferral path when P1 or P2 says OPEN.** The node is never stopped.
1. Do not SIGTERM. Record `AMBIG-LATCH-RESUME activation deferred: open intent at <UTC>` in the execution log.
2. Re-run P1 and P2 every 5 minutes. Measured same-process retire latency is 3-138 s (§2.7), so one or two re-probes normally clear.
3. As soon as both say CLEAR, continue at step S1. The probe and the SIGTERM run in the same script invocation, with no sleep in between, so the gap is sub-second.
4. If 16:40Z arrives with the probe still OPEN, abandon the hand relaunch. The change then loads at the 16:50Z scheduled launch, through the supervisor's own launch path and its own intent handling. Record it in PROGRESS.

**Relaunch steps (only after P1 and P2 say CLEAR):**
- **S1.** Copy the env, set `BREEZY_PERMIT_EXPIRY_CEILING_NS` to the day's first-boot `expires_at_ns` (A-1), and assert that the old pid holds the intent lock.
- **S2.** SIGTERM. Wait for `TradingNode: DISPOSED` in bytes written after the kill, then for `intent_lock_is_free`.
- **S3. Post-stop probe:** `probe_open_intent(store_path, node_pid=None)`. This is the supervisor's own guarded probe; the node is dead, so its guard holds. **If it returns True** (an arm landed in the sub-second P1-to-SIGTERM gap):
  - do NOT `spawn_node`;
  - record `deferred after stop: open intent`;
  - the node stays down until the supervisor's 16:50Z launch. A SIGTERM exit classifies UNKNOWN, so the supervisor logs `midday_relaunch_declined` and does not relaunch mid-day. That is the existing, accepted behaviour.
  
  This residual window is the price of A1's "never relaunch while OPEN", and P1, P2 and the no-sleep ordering keep it sub-second.
- **S4.** `spawn_node`, then the boot proof.

### 5.2 Proof

- **Boot proof:** the 4 boot lines, the permit line, and supervisor `permit_watch_adopted_live_node`, all in the node log FILE (not journald), plus `refusal re-poll timer armed`.
- **Positive in-service proof**, at the next AMBIGUOUS take (≈0.9/day at the current rate, §2.7), in this order:
  1. `Trading refused: <AMBIGUOUS_REASON>` plus a `component_degraded` CRITICAL;
  2. `resolver: retired intent ... (STATUS_REPORT_ZERO_FILL_TERMINAL | STATUS_REPORT_ACCEPT_FILL_TERMINAL)`;
  3. `resolver: cleared the AMBIGUOUS trading refusal ...`;
  4. within ≤ one `REFUSAL_REPOLL_INTERVAL` (60 s, `component_health_watch.py:476`), `health: resumed from DEGRADED ...` plus the native `RUNNING` INFO line;
  5. on the next AMBIGUOUS take, either a second `component_degraded` (≥1 h later, or new reasons) or one `component_degraded alert throttled` WARNING (<1 h, same reasons).
- **Negative proof:**
  - No `InvalidStateTrigger` ERROR from the client. The single exception is the §2.6 RESUMING race, which must then be followed by the `re-degrading` WARNING.
  - No `RESUMING`/`RUNNING` between an `arm` and its retirement.
  - The permit line and its expiry are unchanged by any resume.

## §6 Rollback

- `git revert <merge sha>`. This restores the prior `_EXEC_CLIENT_SHA256` and the inverted pin. Run the full gate, then hand-relaunch under the same §5.1 precondition.
- After rollback, behaviour is exactly `3eb4a108`: zero-fill clears, a fill keeps denying until respawn, health stays DEGRADED, and there is one alert per process.
- There is no durable state, schema or key to migrate. The method writes nothing, and the alert and throttle state is in-memory.

## §7 Risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| Alert volume | Measured ≈0.17/day historical, ≈0.9/day at the current take rate, max 1/day observed (§2.7). | 1 h same-reason throttle (A2), built now. A suppressed repeat logs one WARNING. |
| The throttle hides a genuinely new failure | Low. | New-reason bypass, a backwards clock alerts, and a reader failure alerts (T19). |
| The accept-fill clear re-admits orders after a fill | Intended (A3); it changes admission. | The clear runs last, only when `current_open() is None`, and only for AMBIGUOUS. The permit budget, caps, latch and halt are unchanged. T14, T15 and T16. Security sign-off is required. |
| The accept-fill clear needs a firewall widening | None measured: all three callees are allowlisted. | Stop condition in §2.2. E0-NOSEND-RESOLVER scans it unmodified. |
| A refusal during RESUMING leaves the client RUNNING with refusals | Latent (no production subscriber refuses). | Step 7 re-check (T22). |
| An open intent at activation | Routine on take days. | §5.1 P1/P2 deferral; S3 post-stop guard; never relaunch OPEN. |
| ≤60 s of residual DEGRADED after a clear | Certain, harmless: DEGRADED gates nothing. | The interval is `REFUSAL_REPOLL_INTERVAL`. |
| A future `_resume`/`_degrade` override adds I/O | Low. | T6. |
| A future edit calls the method from the resolver | Low. | E0-NOSEND-RESOLVER unmodified; T8a. |
| The sha re-pin or pin inversion is read as weakening a safety test | Process risk. | §3 three-hunk record plus the deny-chain content-sha check; the inversion is named, singular and ruled (A3). |
| `current_rung_hold` `_on_event` sees extra events | Negligible. | Its alerters dedupe on count change. |

## §8 Build sequence

1. Write T1-T23 and confirm RED, except the GREEN guards T6, T8a and T15. Capture the output.
2. `component_health_watch.py`: constant, parameter, re-arm and throttle. T10 and T17-T19 go GREEN.
3. `client.py` H3, the method: T1-T8b, T20-T23 GREEN.
4. `client.py` H2 and H1, the accept-fill clear: T13, T14 and T16 GREEN. Invert the one A3 pin. T15 stays GREEN.
5. Re-pin the sha and record the three-hunk diff and the deny-chain content sha.
6. `trade_cli.py` handler and wiring: T9, T11 and T12 GREEN.
7. Full gate (EXIT=0), `lint-imports`, ruff, mypy.
8. Independent review by reviewers who did not build it:
   - `trading-bot-architect` for the FSM, races and activation;
   - `security-reviewer` for the NO-SEND proof, the A3 admission change and the pin inversion.
9. Merge, then the §5.1 precondition, relaunch, §5.2 proof, and the PROGRESS update.

## §9 Self-assessment

**Score: 95/100.**

What is left for peers:
- **O1:** whether the new-reason throttle bypass (§2.3) is within the A2 ruling. It only ever adds alerts, never removes one the plain ruling would send.
- **O2:** keep `_latch is None` fail-closed, carried from r1. A latch-less node is a shadow node that never sends, so staying DEGRADED there costs nothing.
- **O3:** whether the T20 rig can be built with no permit, or needs an expired one. The test names both.
- **O4 (r1 carry):** T1 assumes `_arm_one_ambiguous_intent` can be `start()`ed into RUNNING. If not, fall back to the `_build_rig` path from `test_exec_refusal_health_surface.py`.

---

## §R2 Disposition

| Item | Disposition | Where |
|---|---|---|
| **A1** [TBA HIGH] hard precondition on relaunch | **Applied.** Exact read-only pre-stop probe (P1, `mode=ro`, corrupt counts as OPEN; it deliberately avoids `probe_open_intent`, whose guard forbids a live node), a log-tail check (P2), a step-by-step deferral (re-probe every 5 min, abandon at 16:40Z, load at 16:50Z), and a post-stop guarded probe (S3) that refuses to spawn. Never relaunch while OPEN. | §5.1 |
| **A2** throttle now (coordinator ruling) | **Applied as ruled.** `renotify_after_ns` keyword and `DEGRADED_ALERT_RENOTIFY_AFTER_NS` = 1 h. Re-notify at most once per interval per repeated episode. Re-arm on RUNNING. Throttle and re-arm tests T17-T19 and T10. Refinement (O1): a new reason bypasses the throttle. `health.AlertState` was evaluated and rejected, because its rule always fires on a transition. **Measured:** 24 takes in 29 days (0.83/day; 4.3/day since 10-01); IOC-miss rate 12.5% overall, 15.4% since 10-01; AMBIGUOUS 20.8%; max 1 AMBIGUOUS/day; expected alerts ≈0.17/day historical, ≈0.9/day current; throttle binds 0 times on observed data. | §2.3, §2.7, §3 |
| **A3** accept-fill path in scope (coordinator ruling) | **Applied.** An inline clear as the last statement of `_resolve_accept_fill`, gated `current_open() is None`, AMBIGUOUS only. **No allowlist widening:** the callees `self._latch.current_open`, `len` and `self._log.info` are already permitted, and the stop condition is stated. RED->GREEN in T13, T14 and T16, with guards in T15. The one existing pin that asserted the opposite is inverted and named (scope pin from `87b3725b`, not a safety property). Also stated explicitly: this clear, unlike the resume, re-admits orders. | §0 D3, §2.2, §3 |
| **A4** [sec] scope in §2.3 | **Applied.** RUNNING never gates sending and is not proof the node can trade. The real gates are listed. T20 (identical deny under an invalid permit, 0 sends) and T21 (store byte-identical, family halt still set) cover it. | §2.4, §3 |
| **A5** race tests | **Applied, plus a design fix.** A refusal during RESUMING previously ended RUNNING with refusals pending, because there is no `(RESUMING, DEGRADE)` edge (`component.pyx:1640-1642`). The new step 7 re-check re-degrades. T22 covers the during-RESUMING race and T23 the after-resume race (throttled and unthrottled). | §2.1, §2.6, §3 |
| LOW: split T8 | **Applied:** T8a is the pure guard and T8b the RED test. | §3 |
| LOW: cite the re-poll constant | **Applied:** `REFUSAL_REPOLL_INTERVAL` = 60 s, `component_health_watch.py:476`. | §0, §5.2, §7 |
| LOW: record the re-pin diff and the new sha | **Applied and corrected:** under A3 the diff is three hunks, not additions-only. The PR records `git diff -U0`, the deny-chain content sha check, and the old (`76784ce8…68a4`, verified on disk) and new shas. | §3 |
| r1 open: throttle now or later | Resolved by A2: now. | §2.3 |
| r1 open: `_latch is None` | Kept fail-closed (O2). | §2.1, §9 |
| r1 open: T1 rig | Carried as O4. | §9 |

Invariants restated: Nautilus is unmodified; `allow_short=False`; the caps, permit, ceiling and enablement are untouched; the NO-SEND firewall and its allowlists are unmodified and not widened; no safety test is weakened (the single A3 inversion is a ruled scope pin and is disclosed).
