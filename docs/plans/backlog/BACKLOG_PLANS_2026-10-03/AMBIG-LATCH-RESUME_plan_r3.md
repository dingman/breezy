# AMBIG-LATCH-RESUME — plan r3 (2026-10-03)

Status: DRAFT r3 for peer re-review. Plan only; nothing is implemented.
Supersedes: `AMBIG-LATCH-RESUME_plan_r2.md` (unchanged). Review applied: `reviews/AMBIG-LATCH-RESUME-r2-merged.md` (F1–F6 + 4 LOW; F1 and F3 are coordinator rulings, applied exactly). See **§R3 Disposition** at the end; the r2 disposition is kept below it for the record.
Item (docs/core/PROGRESS.md:96): AMBIG-LATCH-CLEAR (`3eb4a108`) leaves the exec client DEGRADED after the clear. Health reads DEGRADED while the client trades, and a later refusal does not re-alert. Call native `resume()` from outside the resolver.

Evidence base: commits `87b3725b` and `3eb4a108` (messages + diffs), `docs/plans/refactor_2026-10-01/EXECUTION_LOG_2026-10-02.md:96,113`, `tests/unit/test_execution_egress_firewall_guard.py:2099-2281` (resolver allowlist, `len` at :2270), `tests/unit/test_fq_caps_and_ambiguous_2026_10_01.py:387-419`, Nautilus `common/component.pyx` and `execution/engine.pyx`. New in r3: `src/breezy/runtime/trade_supervisor.py:1131-1189` (`_do_stop_prior`), `:1209-1261` (`_do_launch`), `:1582-1619` (`_handle_boot_retry_precheck_refusal`), `trade_supervisor_core.py:532-542` (`decide_launch_action`), `runtime/submit_intent.py:391-483, 556-596` (arm, `reconcile_at_startup`, the process flock), `exec/client.py:1936-2093` (`_connect` boot ordering), `:2379-2468` and `:2788-2980` (resolver predicates), `:5537-5569, 5800-5855` (arm → POST → AMBIGUOUS, with-id context), `:5896-5976` (`_refuse`), and `docs/core/LESSONS.md` L-48. `$NT` line numbers were read with `/usr/bin/grep -rn` against `.venv/lib/python3.13/site-packages/nautilus_trader` (positive control: `class Component` matched in `component.pyx`). Live-store figures (§2.7) were read with python `sqlite3` opened `file:...?mode=ro`, nothing written.

---

## §0 Problem and goal state

### Problem (three defects)

**D1. The FSM stays DEGRADED.**
- `_refuse` (`exec/client.py:5896-5976`) calls `self.degrade()` on the first refusal while not degraded.
- `_resolve_terminal_zero` (`:3100-3112`) clears the AMBIGUOUS entry from `_trading_refusals` as its last step.
- Nothing ever calls `resume()`, so the native state stays `DEGRADED` for the rest of the process. In `$NT` the only native `.resume()` / `.degrade()` call on an adapter is `adapters/betfair/data.py:401`.

**D2. The alert latch is permanent, and a refusal without a transition never alerts.**
- `install_component_degraded_alert` (`runtime/component_health_watch.py:628-703`) adds `component_id` to `alerted` on the first DEGRADED and never removes it, so a second `RUNNING -> DEGRADED` is silently swallowed.
- **New in r3 (F6):** `_refuse` degrades only when `not self.is_degraded` (`:5970-5976`, pinned by `test_polymarket_us_exec_client.py::test_a_second_degrade_is_never_triggered_once_the_refusal_list_empties`, `:1081`). Between a clear and the next resume the client is DEGRADED with an empty list, so a new AMBIGUOUS in that window publishes no `ComponentStateChanged` and reaches no alert path at all.

**D3. A filled AMBIGUOUS never clears (coordinator ruling A3).** `_resolve_accept_fill` (`:3114-3317`) retires the intent as `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, records the fill durably, trues up the booking, and publishes the native fill, but leaves the AMBIGUOUS entry in `_trading_refusals`. Pinned today by `test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` (`test_fq_caps_and_ambiguous_2026_10_01.py:387-419`). Provenance (F4): commit `87b3725b7780c3e39566eb407b7496c97ad36664`, message quoted verbatim:

> Cleared scope: _resolve_terminal_zero only, after a successful _retire and only
> when the durable latch has no open intent left; drops entries whose reason is
> exactly submit_chain.AMBIGUOUS_REASON (new list, no in-place mutation), one INFO
> line naming the reason and intent id. Inlined, not a helper, so the
> E0-NOSEND-RESOLVER permitted-callee set is unchanged.
>
> Still latches: every other refusal reason; the AMBIGUOUS refusal on any fill or
> accept-fill terminal path, on an incomplete join, on a non-terminal GET, and
> at create time (empty executions at maxBlockTime stays AMBIGUOUS; L-36, GL-1,
> R-7 unchanged).

The message lists the fill path under "Still latches" alongside the other un-cleared paths and gives **no safety rationale** for it; the incident it fixed was a zero-fill. Consequence: because `_submit_order` denies while `_trading_refusals` is non-empty (`:5357-5359`), **a filled AMBIGUOUS today denies every later order for the rest of the process**, and D1 then keeps it DEGRADED.

**Side effect of D1.** `ExecutionEngine._stop` / `stop_clients` (`$NT/execution/engine.pyx:727-729, 770-772`) call `client.stop()` only `if client.is_running` (RUNNING only, `component.pyx:1819-1828`). A client that stays DEGRADED is skipped by the engine's own stop; resuming restores the normal shutdown path.

### Goal state (acceptance test)

After **any** resolver retirement of an AMBIGUOUS intent (terminal zero-fill OR accept-fill), all of the following hold:
1. The intent is retired, the booking is trued up, the permit slot is restored (zero-fill) or kept spent (fill), and the AMBIGUOUS refusal is cleared, while every other refusal reason stays.
2. Within one resolver pass plus one `REFUSAL_REPOLL_INTERVAL` (60 s, `component_health_watch.py:476`), the exec client goes `DEGRADED -> RESUMING -> RUNNING` through native `Component.resume()`.
3. `client.is_degraded` is False and `client.is_running` is True.
4. **Every new AMBIGUOUS refusal produces exactly one `component_degraded` CRITICAL, never throttled (F3)**, within ≤ one `REFUSAL_REPOLL_INTERVAL` — including one that lands while the client is still DEGRADED inside the clear-to-resume window (F6). A non-AMBIGUOUS refusal episode alerts once, unless the throttle (§2.3) suppresses a same-or-subset reason set alerted less than `DEGRADED_ALERT_RENOTIFY_AFTER_NS` (1 h) earlier; a suppressed episode logs exactly one WARNING line instead.
5. No `DEGRADED -> RUNNING` transition happens while the durable submit intent is OPEN or corrupt, or while any entry remains in `_trading_refusals`. This includes a second AMBIGUOUS inside the clear-to-resume window (F6). If a refusal lands during RESUMING, the client ends DEGRADED (§2.6).
6. RUNNING is not proof the node can trade. Order admission is unchanged by the resume (§2.4).
7. **Activation never strands an OPEN intent with the node down (F1, L-48).** Every OPEN intent met during activation has a named clearing path (§5.1 clearing-path table), and a post-stop OPEN raises a named CRITICAL.

---

## §1 Null hypothesis (L-1): what Nautilus and Breezy already provide

| Need | Native / existing capability | Verdict |
|---|---|---|
| Leave DEGRADED | `Component.resume()` (`component.pyx:2003-2032`). Edges `(DEGRADED, RESUME) -> RESUMING` (`:1650`) and `(RESUMING, RESUME_COMPLETED) -> RUNNING` (`:1641`). The action `self._resume` is `pass` in `Component` (`:1904-1906`), not overridden by `ExecutionClient`, `LiveExecutionClient` or Breezy (grep `def _resume` in `src/`: 0 hits). | **REUSE as-is.** |
| Re-enter DEGRADED after a race | `Component.degrade()` (`:2098-2127`), legal from RUNNING (`:1638`). NOT legal from RESUMING (no `(RESUMING, DEGRADE)` edge; `:1640-1642` lists STOP, RESUME_COMPLETED, FAULT only). | **REUSE.** The RESUMING gap is handled by a post-resume re-check (§2.6). |
| Publish the transition | `_trigger_fsm` publishes `ComponentStateChanged` on `events.system.<id>`, stamped with `ts_event = self._clock.timestamp_ns()` (`:2187-2225`). An invalid trigger logs ERROR and returns (`:2192-2196`). | REUSE. `ts_event` is the throttle's clock. |
| Run periodically on the loop thread | `install_refusal_repoll_timer` (`component_health_watch.py:490-625`), armed in `trade_cli._run_node` (`trade_cli.py:625-635`). FU-8b already calls an alert installer's OWN returned closure from this timer, sharing its dedupe state (`:499-507`). | **REUSE.** Add the resume handler, and register the degraded-alert closure on the timer exactly as FU-8b does for its siblings (F6). |
| Reach the client from runtime | The `_exec_client_*_reader` idiom (`trade_cli.py:393-484`), `getattr(..., default)` for optional attributes. | REUSE the idiom. |
| "Is an AMBIGUOUS intent open?" | `SubmitIntentLatch.is_latched()` (`runtime/submit_intent.py:378-389`): True if OPEN or corrupt (fail-closed). | **REUSE.** |
| Clear AMBIGUOUS on a retirement | The inline clear in `_resolve_terminal_zero` (`:3100-3112`). Its callees are `self._latch.current_open`, `len` and `self._log.info`, all already in `EXEC_RESOLVER_PERMITTED_CALLEES` (`:2130`, `:2270`, `:2136`). | **REUSE the same inline block** in `_resolve_accept_fill`. No helper and no allowlist widening. |
| Count AMBIGUOUS episodes for alerting (F6) | No existing counter. The resolver blocks already assign attributes (`self._trading_refusals = ...` `:3106`, `self._resolver_contradiction_details = ...` `:2886`, `self._resolved_by_get_ts_ns[...] = ...` `:2843`); an `AugAssign` is not a `Call`, so it adds no callee. | **Add one int attribute**, incremented inside both clear blocks, read through one public property. The alternatives are rejected in §2.3a. |
| Alert re-notify throttle | `health.AlertState(renotify_after_ns=...)` (`health.py:518-578`): "false->true always fires; true->true re-fires after the window". It can never suppress a transition, and its other users depend on that rule. | **NOT reusable for a transition throttle.** Same name and units, closure state (§2.3). |
| Clear an OPEN intent while no node runs (F1) | The node's own boot: `_connect` awaits one immediate resolver pass (`client.py:2019-2025`) BEFORE `_publish_account_state`, `_reconcile_submit_intent` (`reconcile_at_startup`, `submit_intent.py:441-483`), the spend seed, and Nautilus's kernel reconciliation; then the periodic resolver runs for the process lifetime (`:2040-2043`). Nothing on the node's boot path refuses because an intent is OPEN; only the supervisor does (`_do_launch` `:1253-1261`, boot-retry `:1612-1619`). | **REUSE: the hand-spawned node IS the clearing path** (§5.1). No supervisor change. |

Conclusion: nothing new is invented except an in-closure throttle and one episode counter. The throttle exists because the one existing primitive has the opposite firing rule; the counter exists because a refusal inside an already-DEGRADED episode publishes nothing anything could observe.

---

## §2 Design

### 2.1 Resume call site: a sync client method, driven by the runtime re-poll timer

**New public sync method on `PolymarketUSExecutionClient`: `resume_if_refusals_cleared() -> bool`.**
- Placement: directly after `_refuse` and before `__repr__` (`client.py:~5977`), after the deny chain.
- Returns True iff the call ends with the client RUNNING.
- Callees are exactly `self._latch.is_latched`, `self.resume`, `self.degrade`, `self._log.info` and `self._log.warning`. Body, in order:
  1. `if not self.is_degraded: return False`. This is a property read. It skips RUNNING, RESUMING, DEGRADING, STOPPING and STOPPED. It matters most for STOPPED, because `(STOPPED, RESUME)` is also a legal native edge (`:1646`).
  2. `if self._trading_refusals: return False`. Any refusal reason keeps the client DEGRADED. **This is the F6 guard:** a second AMBIGUOUS inside the clear-to-resume window is appended by `_refuse` (`:5971`) and makes the list non-empty, so the resume is refused (T24).
  3. `if self._latch is None: return False`. Fail-closed, kept from r1.
  4. `try: latched = self._latch.is_latched()`, then `except Exception: self._log.warning(<type name only>); return False`.
  5. `if latched: return False`. This covers an OPEN or corrupt intent — and covers F6 a second time, because the second AMBIGUOUS intent stays OPEN until its own retirement.
  6. `self.resume()`.
  7. **Post-resume re-check (A5):** `if self._trading_refusals and not self.is_degraded:` log one WARNING (`health: a refusal landed during RESUMING; re-degrading`), call `self.degrade()`, and `return False`.
  8. `self._log.info("health: resumed from DEGRADED (no refusals, no open submit intent)")`, then `return True`.
- Thread safety: it runs on `node.kernel.loop` (the `_poll` hop), the same loop as the resolver, `_submit_order` and `_refuse`. It has no `await`. The only way a refusal can interleave between steps 1-5 and step 8 is re-entrantly, from a synchronous msgbus subscriber reacting to the RESUMING publish. Step 7 closes that window (§2.6).

**New public read-only property on the same class: `ambiguous_refusal_clears -> int`** (F6). Placed with the method above. Body: `return self._ambiguous_refusal_clears`. No callee.

**Runtime trigger: `_exec_client_resume_handler(node) -> Callable[[object], None]` in `runtime/trade_cli.py`.**
- Placed beside the `_exec_client_*_reader` helpers, using the same lazy lookup. A missing client or attribute is a no-op (`getattr(..., None)`).
- Appended LAST to `handlers=` at `trade_cli.py:629`. `_poll` already isolates each handler in `try/except Exception`.
- If the re-poll timer fails to arm (`trade_cli.py:634-635`), no resume happens. The client then stays DEGRADED, which is exactly today's behaviour (fail-safe). The F6 tick alert is also absent in that case; the transition alert still fires (today's behaviour), and the existing `refusal re-poll timer NOT armed` report names the loss.

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
- If the length changed, assign it, `self._ambiguous_refusal_clears += 1` (F6), and log one INFO: `resolver: cleared the AMBIGUOUS trading refusal (...) on fill retirement of intent <id>`.
- Use a new list with no in-place mutation, and do not add a helper.

The existing zero-fill block gets the same one added line, `self._ambiguous_refusal_clears += 1`, inside its `if len(kept_refusals) != len(self._trading_refusals):` branch (`:3106-3112`). `__init__` initialises `self._ambiguous_refusal_clears: int = 0` beside `self._trading_refusals` (`:1697`).

Why last:
- **Any raise above keeps the refusal, the conservative direction** (same reasoning as `3eb4a108`). That covers `record_fill` (early return on `_FILL_WRITE_FAILED`), the venue-id map, `_retire`, `true_up_booking`, `unrestore_live_trading_budget` and `generate_order_filled`.
- Once `_retire` has run, the next pass takes the `current is None` early return (`:3165-3167`), so nothing after `_retire` is ever retried. The clear therefore must not run before those steps.

**The cross-session early return (`_resolver_fill_order_unknown` True, `:3296-3297`) never reaches the clear. This is intended, not an omission (LOW), and it is complete:**
- `AMBIGUOUS_REASON` has exactly two `_refuse` producers, both inside `_submit_order` (`:5556`, `:5800`). An entry can therefore exist only in the process that submitted the order.
- A process that submitted the order finds it in `self._cache`, so the helper returns False (`:4244-4245`) and execution reaches the clear.
- A process that did not submit it (a respawn resolving a prior process's intent) has no AMBIGUOUS entry to clear, so returning early loses nothing; the AC6b `_RESOLVER_FILL_UNBUDGETED` latch on that path is deliberate and stays.
- The submit latch is a singleton, so no other intent's AMBIGUOUS entry can coexist.
- T15(iii) pins the producer premise.

**Kept refusals are unchanged.** `_VENUE_ID_MAP_WRITE_FAILED` (`:3253`) and `_RESOLVER_FILL_UNBUDGETED` (`:3291`), and every other reason, stay. So does the informational `RESOLVER_FILL_NOT_BOOKED` reconciliation latch, which lives in a separate dict and is not a trading refusal. Any of them keeps the client DEGRADED and denying.

**Firewall: no widening.** The block's callees (`self._latch.current_open`, `len`, `self._log.info`) are all already in `EXEC_RESOLVER_PERMITTED_CALLEES`; the counter is an `AugAssign`, not a call. `_resolve_accept_fill` and `_resolve_terminal_zero` are already in `EXEC_RESOLVER_COROUTINES`'s scan, so E0-NOSEND-RESOLVER scans the new lines unmodified. **Stop condition:** if implementation finds that either block needs any callee outside that set, or that the firewall flags the `AugAssign`, stop and report. Do not widen.

**This DOES change order admission, unlike the resume.**
- After a GET-confirmed fill, a later take is admitted again instead of being denied for the rest of the process.
- Justification:
  - The AMBIGUOUS refusal exists because the outcome is unknown. Once a terminal GET has confirmed the fill, `record_fill` has written it durably, `true_up_booking` has charged the filled cost to the ledger, and `_retire` has closed the singleton, the refusal no longer has a subject.
  - Exposure stays bounded by gates this item does not touch: the permit and its budget (the fill is spent, not restored; `unrestore` still applies when a superseded zero-fill had restored), the two operator caps, the latch, and the family halt.
  - It is the same reasoning `87b3725b`/`3eb4a108` already applied to zero-fill, now applied to the one remaining terminal.

**Predicate strength (F4): the evidence the clear rests on, side by side** (`client.py:2788-2980`).

| Requirement | Zero-fill retirement | Accept-fill retirement |
|---|---|---|
| Terminal GET made in THIS run (SAFETY H2, `:2840-2843`) | Required: terminal status, `filled_qty == 0` (`:2788-2790`) | Required: terminal status with `filled_qty > 0`, or a FILLED status (`:2795-2799`) |
| eof-complete positions read with a determinable leg state (`:2808-2837`) | Required | Required |
| Independent second source | Complete activities join with **0** trades, AND no create-time fill evidence (`:2880-2913`) | Own-leg LONG present (`long_state is True`), OR a complete activities join with **≥1** trade (`:2968-2970`) |
| Contradiction handling | A found trade or create-time fill evidence → `resolver_evidence_contradiction` CRITICAL, stays AMBIGUOUS (`:2881-2906`) | Fill not confirmed by either source → WARNING, stays AMBIGUOUS (`:2977-2980`) |
| Extra gates | 120 s min age (`:2914-2922`); same-day holding baseline (`:2932-2955`) | None; see below |
| Durable effect before the clear | `_retire`, booking true-up to zero, permit restore | `record_fill` (durable), venue-id map, `_retire`, true-up to the filled cost, `unrestore`, native fill |

The asymmetry is deliberate: zero-fill proves an *absence* (no trade), which is exposed to venue eventual-consistency, hence the min age and the holding baseline; accept-fill proves a *presence* (a held LONG or a recorded trade), which an eventually-consistent read can delay but cannot fabricate. On the fill path a false "fill" would charge the budget (the conservative direction), never restore it. **Required before merge: a written security-reviewer sign-off stating that the accept-fill confirmation predicate is at least as strong as the zero-fill one for the purpose of clearing the AMBIGUOUS refusal, or naming the gap.** The sign-off is recorded in the PR and the execution log.

**Docstring carve-out:** invariant 1 at `client.py:177-178` becomes "Sole carve-out: resolver-retired terminal zero-fill or accept-fill clears the AMBIGUOUS refusal only (2026-10-02; accept-fill 2026-10-03)". Its pin `test_a_latched_refusal_persists_across_a_reconnect_after_the_condition_clears` does not read the docstring and stays unedited and green.

### 2.3 Re-alert with a throttle; AMBIGUOUS is never throttled (A2 + F3, coordinator rulings)

All of this lives in `install_component_degraded_alert` (`component_health_watch.py:628-703`).

**New constant:**
```python
#: One hour. Caps a storm of NON-AMBIGUOUS repeat episodes at one identical
#: CRITICAL per hour. AMBIGUOUS episodes are exempt (F3): each one alerts.
#: Same units/name as health.AlertState.
DEGRADED_ALERT_RENOTIFY_AFTER_NS: Final[int] = 60 * 60 * 1_000_000_000
```

**Signature change:** three keyword-only parameters.
- `renotify_after_ns: int = DEGRADED_ALERT_RENOTIFY_AFTER_NS`. A `bool`, a non-int or a value ≤ 0 raises `ValueError` at install time.
- `ambiguous_reason: str | None = None`. The exact reason string that is never throttled. Passed by `trade_cli` as `submit_chain.AMBIGUOUS_REASON`, so `component_health_watch` keeps importing nothing from `adapters` (its imports today: `nautilus_trader.common.*` and `breezy.runtime.health` only).
- `ambiguous_clears: Callable[[], int] | None = None`. Reads `client.ambiguous_refusal_clears` (F6, §2.3a).
- With both `None` (every existing test and caller), behaviour is r2's minus nothing: the tick branch below is a no-op and no reason is exempt.

**Closure state:**
- `alerted: set[str]` (existing per-episode latch).
- `last_alert: tuple[int, frozenset[str]] | None = None` (when the last alert was emitted, and which reasons it carried).
- `ambiguous_alerted: int = 0` (F6: how many AMBIGUOUS episodes have been alerted in this process).

**Handler rules, on `ComponentStateChanged` for `component_id`:**
- **RUNNING:** `alerted.discard(component_id)`, then return. The episode ends; `last_alert` is NOT reset.
- **DEGRADED, already alerted this episode:** return. Unchanged; preserves `test_a_second_refusal_does_not_re_alert`.
- **DEGRADED, first in this episode:**
  1. `alerted.add(component_id)`.
  2. Read the reasons as today (the reader-failure fallback is unchanged).
  3. **If `ambiguous_reason` is in the reasons: always emit (F3), never suppress.** Set `last_alert`, and set `ambiguous_alerted = _ambiguous_episodes()` (below).
  4. Otherwise, compute `elapsed = event.ts_event - last_alert[0]`. **Suppress** iff `last_alert is not None`, `0 <= elapsed < renotify_after_ns`, and `frozenset(recorded) <= last_alert[1]`. Suppression logs one `logger.warning("component_degraded alert throttled component=%s reasons=%d since_last_s=%d", ...)` and returns.
  5. Otherwise, emit exactly as today and set `last_alert = (event.ts_event, frozenset(recorded))`.

**Handler rule on any other event (a re-poll tick, F6):** if `ambiguous_reason` or `ambiguous_clears` is `None`, return. Otherwise compute `_ambiguous_episodes() = ambiguous_clears() + (1 if ambiguous_reason in reasons() else 0)`. If it exceeds `ambiguous_alerted`, emit one `component_degraded` CRITICAL per owed episode (detail built by the existing `_detail(component_id, recorded)`) and set `ambiguous_alerted` to it. Never throttled. A raising reader propagates, and `_poll` logs it as a named handler failure (`component_health_watch.py:575-581`); the transition path is unaffected.

**Semantics:**
- The first-ever DEGRADED always alerts (cold start).
- **Every AMBIGUOUS episode alerts exactly once,** whether it arrives as a transition (normal case) or inside an already-DEGRADED window (F6, ≤ 60 s later on the next tick). Counting is exact: each AMBIGUOUS episode is either still present (+1) or was cleared (+1 to the counter) — a clear always follows the episode it ends, so no episode is counted twice, and none is lost even if it is added and cleared between two ticks.
- Non-AMBIGUOUS repeat episodes re-notify at most once per interval per repeated reason set, as ruled in A2. **A reason not alerted inside the window bypasses the throttle** (r2 refinement, kept).
- A clock that runs backwards (`elapsed < 0`) alerts. `REASONS_UNAVAILABLE` is a reason string like any other, so a reader failure after a real alert is a new reason set and alerts.
- Single-threaded on the loop (msgbus and `_poll` both run there, `component_health_watch.py:540-546`); in-memory and per process, like `AlertState`.

**Docstring Notes** become: "only the FIRST DEGRADED per degraded *episode* is considered; an episode ends on RUNNING. An episode carrying `ambiguous_reason` always alerts. A non-AMBIGUOUS repeat episode whose reasons were all alerted within `renotify_after_ns` is logged at WARNING instead. When registered on the re-poll timer, every AMBIGUOUS episode that produced no transition alerts on the next tick."

### 2.3a Why a counter (F6)

The second AMBIGUOUS in the clear-to-resume window is invisible to every existing signal: `_refuse` does not degrade (client already DEGRADED, `:5970-5976`, pinned at `test_polymarket_us_exec_client.py:1081`), the AMBIGUOUS reason string is identical, and a tick can miss it entirely if it is added and cleared inside one 60 s interval (same-process fill retirement measured at 3.2 s, §2.7). Rejected alternatives:
- Changing `_refuse` to degrade on an empty list: reverses R-6.5a (`:5938-5947`) and moves the 25-producer pin. No.
- Tagging the AMBIGUOUS entry with the intent id: edits both producers inside `_submit_order`, so the deny chain stops being byte-identical. No.
- Resuming from the resolver at clear time, which would close the window: `self.resume` is not in `EXEC_RESOLVER_PERMITTED_CALLEES`. Widening is forbidden. No.
- Reading the intent id from runtime: needs the latch plumbed into `_run_node` and a second store reader. More surface than one int. No.

### 2.4 Scope: what RUNNING does and does not mean, and why the resume cannot send (A4 + r1 §2.3)

**Scope statement (A4).**
- The FSM/health RUNNING state **never gates sending and is not proof the node can trade.**
- Sending stays gated, unchanged, by:
  - the `_trading_refusals` list (`_submit_order:5357`);
  - the live-trading permit and its budget (`safety.py`, minted at boot, ceilinged by A-1, untouched);
  - the submit-intent latch (`is_latched`);
  - the strategy-side family halt (`continuous_rung_hold/halt`, `trial_day_latch.family_halt_key`, read by the strategy never-arm gate);
  - the operator caps.
- `resume_if_refusals_cleared` reads none of these except `is_latched` and `_trading_refusals`, and writes none of them. `ambiguous_refusal_clears` is a pure read.
- Liveness for operators stays as the memory and runbook define it: process, log mtime, **permit unexpired**, and tape advancing. RUNNING does not replace it.
- Only the §2.2 accept-fill clear changes admission. It is the refusal-list edit justified there, not the FSM change.

**Proof the resume cannot send.** Each step is pinned by a §3 test.
1. **Trigger chain:** `LiveClock timer -> _on_timer -> loop.call_soon_threadsafe(_poll) -> _exec_client_resume_handler -> client.resume_if_refusals_cleared()`. No frame reaches `_order_sender`, `_private_read`, `submit_chain` or any `exec/` coroutine.
2. **Method body:** the callee set equals `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`; the property has no call. There is no `await`, neither is a coroutine, and there is no `create_task`, `asyncio.*` or `threading.*` (T5).
3. **Native actions:** `resume()` runs `Component._resume` and `degrade()` runs `Component._degrade`, both `pass`. An MRO pin (T6) asserts no class between the client and `Component` defines either.
4. **Published events:** `ComponentStateChanged` on `events.system.POLYMARKET_US` only. Subscribers: native none (`$NT` grep `events.system`: publisher only, `component.pyx:2223`); Breezy `component_health_watch` (alert-only); Breezy `strategy/current_rung_hold/composition.py:905-922` `_on_event` (`RefusalAlerter.report`). None submits, cancels or modifies an order (T7).
5. **Admission is unchanged by resume:** T20 and T21 (A4).
6. **The firewall is untouched:** T8a/T8b.

### 2.5 The "never resume while AMBIGUOUS is open" invariant

The guard is layered:
- **(a)** Both clears (`_resolve_terminal_zero` `:3100`, and the new accept-fill block) run only when `current_open() is None`.
- **(b)** The method requires an empty `_trading_refusals`.
- **(c)** The method independently requires `is_latched() is False`. This covers an OPEN or corrupt intent and the in-flight `arm -> post_order` window.
- **(d)** Steps 1-6 run in one synchronous frame, and step 7 re-checks after the only re-entrant window.

T2 and T3 pin (c) with the list empty. T24 pins (b) and (c) for the F6 second-AMBIGUOUS case.

### 2.6 Races (A5 + F6)

| Race | Mechanism | Outcome with r3 | Test |
|---|---|---|---|
| Refusal **during RESUMING** | Only re-entrantly, from a synchronous subscriber to the RESUMING publish (`resume()` runs `_trigger_fsm(RESUME)` -> publish -> `_trigger_fsm(RESUME_COMPLETED)` in one frame). `_refuse` sees `is_degraded` False and appends; its `degrade()` hits the missing `(RESUMING, DEGRADE)` edge (one native ERROR, no state change); then RESUME_COMPLETED moves to RUNNING with a non-empty list. No production subscriber calls `_refuse` today: latent, not live. | Step 7 logs a WARNING, calls `degrade()` (legal from RUNNING), returns False. Events: RESUMING, RUNNING (re-arm), DEGRADING, DEGRADED. The alert fires: a new reason bypasses the throttle; AMBIGUOUS always alerts; the same non-AMBIGUOUS reason inside the window is throttled. | T22 |
| Refusal **after resume** | Ordinary `_refuse` from RUNNING: `degrade()` runs. | DEGRADED; the re-armed alert fires subject to §2.3 (AMBIGUOUS: always). | T23 |
| **Second AMBIGUOUS before resume (F6)** | Clear at t0; the list is empty but the client is still DEGRADED. A take arms and goes AMBIGUOUS before the next tick: `_refuse` appends without degrading. | Resume refused at the tick (step 2, and step 5 while that intent is OPEN). The tick's degraded-alert handler sees `clears + present` exceed `ambiguous_alerted` and emits one CRITICAL, unthrottled. If the second AMBIGUOUS is also cleared before the tick, the tick still alerts (counter) and then resumes. | T24 |
| Resume vs an in-flight take | `is_latched` is True from `arm` onward; one loop thread. | No resume. | T2 |
| Resume from DEGRADING | `is_degraded` is False in DEGRADING. | No-op; the invalid `(DEGRADING, RESUME)` edge is never triggered. | T4(iii) |

### 2.7 Measured alert volume (A2), read-only from the live exec store

Source: `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, opened `mode=ro`, keys `exec/polymarket_us/intent/current` and `exec/polymarket_us/intent/history/*`. `submit_intent.py` has no prune or delete path, so the history is complete. Window: 2026-09-05 to 2026-10-03 (29 calendar days, store WAL mtime 16:15Z on 10-03). An intent is one take.

| Metric | Value |
|---|---|
| Takes (intents, excluding 1 `OPERATOR_CLEARED`) | **24** over 9 active days: **0.83/calendar day**, **2.7/active day**, max 6 (10-01). Since FQ went live: 10-01 = 6, 10-02 = 5, 10-03 = 2 (partial), so **~4.3/day** |
| AMBIGUOUS episodes (resolver-retired) | **5/24 = 20.8%**: 3 `STATUS_REPORT_ZERO_FILL_TERMINAL` (09-23, 10-01, 10-02) + 2 `STATUS_REPORT_ACCEPT_FILL_TERMINAL` (09-11, 09-13) |
| **IOC-miss rate** (zero-fill terminal / takes) | **3/24 = 12.5%** overall, **2/13 = 15.4%** since 10-01. `ACCEPTED_ZERO_FILL_TERMINAL` = 0 ever |
| Max AMBIGUOUS per day | **1** |
| Create-to-retire latency | Same process: 3.2 s (fill), 120.8 s, 138.3 s (zero-fill). Cross-process: 6.1 h (fill), 26.9 h (zero-fill) |

**Period mismatch (LOW), stated:** the current-rate figure multiplies a take rate from **2.3 days** (10-01 to the partial 10-03) by an AMBIGUOUS fraction from the **29-day** window. The two periods differ, and the 10-03 day is partial. Using the post-10-01 fraction instead (2 AMBIGUOUS / 13 takes = 15.4%) gives 4.3 × 0.154 ≈ **0.66/day**; using the 29-day fraction gives 4.3 × 0.208 ≈ **0.9/day**. The plan sizes to the upper figure.

**Expected `component_degraded` volume.**
- AMBIGUOUS: exactly one per episode, never throttled (F3): **≈0.17/calendar day historical; ≈0.66–0.9/day at the current take rate; observed max 1/day.**
- **Why exempting AMBIGUOUS cannot storm:** each AMBIGUOUS is one take, and the singleton latch admits no new `arm` until the previous intent is retired (`submit_intent.py:403-409`; same-process retire ≥ 3.2 s for a fill, ≥ 120 s min age for a zero-fill, `client.py:2914-2922`). AMBIGUOUS alerts are therefore bounded by the take rate (observed max 6 takes/day), not by refusal churn.
- Non-AMBIGUOUS: one per episode, subject to the 1 h throttle, which suppresses **0** of the observed episodes.
- Before this change: at most 1 alert per process.

---

## §3 Tests: RED -> GREEN

New tests go in new files or are appended to the named files. RED is shown by running each new test against the unmodified tree; record RED and GREEN output as the change artifact.

**Exactly two existing assertions are edited (F2 corrects r2's "only one"), both forced by the A3 ruling:**
1. `test_fq_caps_and_ambiguous_2026_10_01.py::test_a_fill_terminal_retirement_does_not_clear_the_ambiguous_refusal` (`:387-419`) is renamed to `test_a_fill_terminal_retirement_clears_the_ambiguous_refusal`. Its rig and the three retirement-reason assertions stay verbatim. The final line (`:419`) flips to `assert _AMBIGUOUS_REASON not in client.trading_refusals`. It pinned a scope choice (`87b3725b`, quoted in §0 D3), not a safety property.
2. `test_current_rung_hold_ambiguous_resolver.py::test_a_get_confirmed_fill_with_a_long_present_records_a_synthesized_fill_and_retires`, the assertion at `:1308` (`assert client.trading_refusals == refusals_before`, with `refusals_before` captured at `:1270` while the AMBIGUOUS entry is present). It goes RED under A3. It becomes:
   ```python
   assert submit_chain.AMBIGUOUS_REASON in refusals_before  # non-vacuity: the rig really was AMBIGUOUS
   assert client.trading_refusals == tuple(
       reason for reason in refusals_before if reason != submit_chain.AMBIGUOUS_REASON
   ), (<existing message, with "(the initial AMBIGUOUS ... still be present)" replaced by
        "(the initial AMBIGUOUS submit's own refusal is cleared by the fill retirement, A3)">)
   ```
   This keeps the test's purpose — `fee_reconciled=False` adds **no new** refusal — and is stricter than before: it now also proves the AMBIGUOUS entry was there and was removed, and that nothing else changed. (Import `submit_chain` if the file does not already; it is an existing module.)

Every other "still latches" pin stays unmodified: incomplete join (`:356`), non-terminal GET (`:382`), create time, permit-restore raise (`:464`), true-up raise (`:491`), and corrupt post-retire read (`:528`).

**The grep that bounds F2** (run on 2026-10-03; the implementer re-runs it and attaches the output to the PR):
```
/usr/bin/grep -rn --include=*.py "trading_refusals" tests/
```
Every hit was mapped to its enclosing test with an `ast` walk. The A3 change can only turn an assertion RED if it runs after a **same-process** accept-fill retirement while an AMBIGUOUS entry is present, and asserts that entry's presence (directly, by equality with a snapshot, or by `!= ()` when AMBIGUOUS is the only entry). Classification:
- **Goes RED, edited:** `test_fq_caps_and_ambiguous_2026_10_01.py:419` (edit 1); `test_current_rung_hold_ambiguous_resolver.py:1308` (edit 2).
- **After an accept-fill, but no AMBIGUOUS entry in that process (cross-process or seeded), unaffected:** `test_edge2_ac6b_cross_process_fill_budget.py:236, 276` (`_RESOLVER_FILL_UNBUDGETED in`), `:364, 407, 497, 655, 723` (`== ()`). An assertion `== ()` that passes today cannot fail after a change that only removes AMBIGUOUS entries.
- **Zero-fill or non-fill paths, unaffected:** `test_fq_caps_and_ambiguous_2026_10_01.py:283, 292, 322, 356, 382, 464, 491, 528`.
- **No resolver involved, unaffected:** `test_polymarket_us_exec_client.py` (all hits, including `:1081`, which pins that an emptied list does not re-degrade and is the D2/F6 premise), `tests/contract/test_exec_client_reconciliation_contract.py` (all hits), `test_settlement_exit_guard.py` (constructed tuples), `test_current_rung_hold_pre_arm_race.py:249`.

The full gate is the backstop: **any further RED in an existing test stops the build and is reported. It is never edited silently.**

| # | File | Test | RED today because |
|---|---|---|---|
| T1 | `tests/unit/test_ambig_latch_resume.py` (new) | `test_terminal_zero_clear_then_resume_returns_the_client_to_running`. Uses the `_arm_one_ambiguous_intent` + `_run_resolver_passes` rig. Precondition: `start()` ran and `is_degraded` is True after the take. After the pass, `resume_if_refusals_cleared()` returns True, `is_running` is True, `is_degraded` is False, and `ambiguous_refusal_clears == 1`. | AttributeError |
| T2 | same | `test_resume_refused_while_the_submit_intent_is_open`: list emptied by assignment, latch OPEN. Returns False and stays DEGRADED. | AttributeError |
| T3 | same | `test_resume_refused_when_the_latch_read_is_corrupt_or_raises`: corrupt singleton, then separately a raising `is_latched`. Both return False and stay DEGRADED. The raising case logs a WARNING with the type name only. | AttributeError |
| T4 | same | `test_resume_is_a_no_op_unless_degraded`: (i) RUNNING returns False with no `InvalidStateTrigger` ERROR; (ii) STOPPED stays STOPPED; **(iii) DEGRADING, concrete spy (LOW):** subscribe a handler to `events.system.POLYMARKET_US` on the rig's msgbus that, when `event.state == ComponentState.DEGRADING`, calls `client.resume_if_refusals_cleared()` and records `(return value, client.state)`; then call `client._refuse(_UNRELATED_REFUSAL)` from RUNNING. `degrade()` publishes DEGRADING synchronously before `_degrade()` and `DEGRADE_COMPLETED` (`component.pyx:2098-2127`), so the spy runs while the state is DEGRADING. Assert the record is `(False, ComponentState.DEGRADING)`, the final state is DEGRADED, and no `InvalidStateTrigger` ERROR is logged. (iv) a remaining `_UNRELATED_REFUSAL` returns False; (v) `_latch is None` returns False. | AttributeError |
| T5 | same | `test_resume_method_callee_set_is_exactly_pinned`: AST, `_dotted_callee` semantics. Method callees EQUAL `{self._latch.is_latched, self.resume, self.degrade, self._log.info, self._log.warning}`. The `ambiguous_refusal_clears` property body contains zero `Call` nodes. No `Await`/`AsyncFor`/`AsyncWith`; both are `FunctionDef`. Planting `self._order_sender.post_order` in a source copy fails (non-vacuity). | method absent |
| T6 | same | `test_resume_and_degrade_actions_are_the_native_no_ops`: for `name in ("_resume", "_degrade")`, `[c for c in type(client).__mro__ if name in vars(c)] == [Component]`. | GREEN today (guard) |
| T7 | same | `test_resume_publishes_only_the_component_state_topic_and_never_reaches_the_sender`: subscribe `*` and spy `post_order`. Topics are only `events.system.<id>`, states are `[RESUMING, RUNNING]`, and `sender.calls` is unchanged. | AttributeError |
| T8a | same | **Pure guard:** `test_the_resume_method_name_is_outside_every_firewall_scope`. `"resume_if_refusals_cleared"` and `"ambiguous_refusal_clears"` are not in `EXEC_RESOLVER_COROUTINES`, `ORDER_LIFECYCLE_COROUTINES` or `EXEC_PERMITTED_COROUTINE_NAMES`. None of `self.resume`, `self.degrade` or `self.resume_if_refusals_cleared` is in `EXEC_RESOLVER_PERMITTED_CALLEES` or `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` (constants imported read-only). | GREEN today (guard) |
| T8b | same | **RED:** `test_the_resume_method_exists_as_a_sync_method_on_the_client`. The `client.py` AST has `PolymarketUSExecutionClient.resume_if_refusals_cleared` as a `FunctionDef` placed after `_refuse`. | method absent |
| T9 | `tests/unit/test_exec_refusal_health_surface.py` (append) | `test_a_refusal_after_resume_re_alerts_exactly_once`. Real rig: refuse A (1 alert), clear, resume, refuse B (a different, non-AMBIGUOUS reason): 2 alerts. Refuse C while still DEGRADED: still 2. | 1 alert (D2) + AttributeError |
| T10 | same (append) | `test_running_re_arms_the_degraded_alert_for_the_same_component_only`. Synthetic events with `ts_event` gaps ≥ the window. DEGRADED(X), RUNNING(X), DEGRADED(X) gives 2. DEGRADED(X), RUNNING(OTHER), DEGRADED(X) gives 1. | 1 (D2) |
| T11 | `tests/unit/test_trade_cli.py` (append) | `test_repoll_timer_resumes_a_cleared_exec_client`: `RecordingNode` + `_fire_repoll` with a fake client. One fire gives one call. A missing client or attribute does not raise, and the siblings still fire. | 0 calls |
| T12 | same | `test_degraded_alert_and_resume_handler_are_wired_into_the_repoll_tuple`: captured `handlers` has length 5; index 3's `__qualname__` contains `install_component_degraded_alert`; the last element's `__qualname__` contains `_exec_client_resume_handler`. The degraded-alert install call received `ambiguous_reason == submit_chain.AMBIGUOUS_REASON` and a callable `ambiguous_clears`. | length 3 |
| T13 | `tests/unit/test_ambig_latch_resume.py` | **A3:** `test_accept_fill_retirement_clears_the_ambiguous_refusal_and_the_client_resumes`. Evidence `ORDER_STATE_FILLED`, cum=1, LONG held, avg_px 0.40 (the `_set_get_evidence` shape from `test_fq_caps...:240`). After one pass: retired `STATUS_REPORT_ACCEPT_FILL_TERMINAL`, AMBIGUOUS gone, the INFO "cleared ... on fill retirement" logged, `ambiguous_refusal_clears == 1`, and `resume_if_refusals_cleared()` returns True with `is_running`. | AMBIGUOUS still present |
| T14 | same | **A3:** `test_accept_fill_clear_keeps_every_other_refusal`. (i) Same-process: `record_venue_order_id` monkeypatched to raise: AMBIGUOUS is cleared but `_VENUE_ID_MAP_WRITE_FAILED` stays, so resume returns False. (ii) **Isolation test (LOW), not a reachable production state:** a cross-process (`booking is None`, `_spend_seeded`) BUY fill. The early return at `:3296-3297` means the clear block is never reached on this path (intended, §2.2); the test pins only that `_RESOLVER_FILL_UNBUDGETED` stays, `ambiguous_refusal_clears` is unchanged, and resume returns False. It does not claim a cross-process AMBIGUOUS entry can exist (T15(iii) pins that it cannot). | (i) AMBIGUOUS still present; (ii) AttributeError |
| T15 | same | **A3 guards** (GREEN today, pinned): (i) `record_fill` raising takes the `_FILL_WRITE_FAILED` early return and AMBIGUOUS stays. (ii) `generate_order_filled` raising (the resolver counts the error) keeps AMBIGUOUS. (iii) An AST pin: every `self._refuse(submit_chain.AMBIGUOUS_REASON)` call site is inside `_submit_order`. | GREEN (guard) |
| T16 | same | **A3:** `test_after_an_accept_fill_clear_a_take_reaches_the_sender`. Mirrors `test_terminal_zero_fill_retirement_clears_ambiguous_refusal_and_a_take_reaches_sender`: with the operator gate enabled and caps set, a second take after the clear reaches `post_order` exactly once, and the ledger shows the filled cost spent (not restored). | denied (AMBIGUOUS latched) |
| T17 | `tests/unit/test_component_health_watch_degraded_throttle.py` (new) | `test_a_repeat_non_ambiguous_episode_inside_the_window_is_throttled_and_logged_once`. Reason set `{_UNRELATED_REFUSAL}`, gap < 1 h: 1 alert, plus exactly one WARNING `component_degraded alert throttled`. | no throttle: 2 alerts (after the re-arm) |
| T18 | same | `test_a_repeat_episode_after_the_window_re_alerts`. Non-AMBIGUOUS reason, gap = `DEGRADED_ALERT_RENOTIFY_AFTER_NS` exactly: 2 alerts (boundary is `>=`). | constant missing |
| T19 | same | `test_a_new_reason_inside_the_window_bypasses_the_throttle`, `test_a_backwards_clock_alerts`, `test_a_reader_failure_after_an_alert_still_alerts`, `test_one_alert_per_episode_regardless_of_the_throttle`, `test_invalid_renotify_after_ns_is_rejected_at_install` (0, -1, `True`, `1.5`), `test_the_default_window_is_one_hour_and_trade_cli_uses_the_default`, **`test_a_tick_is_a_no_op_without_the_ambiguous_readers`** (a non-`ComponentStateChanged` event with both new kwargs `None`: 0 alerts, no raise; existing installs are unchanged). | constant/param missing |
| T20 | `tests/unit/test_ambig_latch_resume.py` | **A4:** `test_resume_leaves_order_admission_unchanged_while_the_permit_is_invalid`. Rig with no valid permit (no `enable_operator_gate`; if the rig cannot reach DEGRADED that way, an expired permit). Drive DEGRADED, empty the list, record the `_deny` reason for one take, then resume and submit the same take: **identical deny reason**, `post_order` calls 0. | AttributeError |
| T21 | same | **A4:** `test_resume_writes_nothing_durable_and_leaves_a_set_family_halt_set`. Write `family_halt_key(<family>)` and the legacy `continuous_rung_hold/halt` into the rig store, snapshot every `(key, value)`, resume, and snapshot again: **byte-identical**. `client._permit` is the same object and unchanged. | AttributeError |
| T22 | same | **A5:** `test_a_refusal_during_resuming_ends_degraded_and_re_alerts`. Install the real degraded alert on the rig bus with a recording sink, plus a subscriber that calls `client._refuse(_UNRELATED_REFUSAL)` on the RESUMING event. `resume_if_refusals_cleared()` returns False, `is_degraded` is True, the event sequence is `[RESUMING, RUNNING, DEGRADING, DEGRADED]`, the alert count is +1 (new reason), and one WARNING `refusal landed during RESUMING` is logged. | AttributeError |
| T23 | same | **A5 + F3:** `test_a_refusal_after_resume_re_degrades_and_re_alerts_subject_to_the_throttle`. (i) After a resume, `_refuse(_UNRELATED_REFUSAL)` gives DEGRADED; with the rig `TestClock` < 1 h since the same set was alerted: throttled (WARNING, no alert); advanced ≥ 1 h: alert. (ii) **F3:** the same cycle with `_refuse(AMBIGUOUS_REASON)` twice inside 1 h: **2 alerts, 0 throttle WARNINGs.** | AttributeError |
| T24 | same | **F6:** `test_a_second_ambiguous_inside_the_resume_window_refuses_resume_and_alerts`. Real degraded alert installed with `ambiguous_reason`/`ambiguous_clears` and a recording sink. AMBIGUOUS #1 → DEGRADED → 1 alert. Resolver clears it (`ambiguous_refusal_clears == 1`). **Before any tick**, a second take arms and `_refuse(AMBIGUOUS_REASON)` appends (no transition; `is_degraded` still True). Fire one re-poll (`_fire_repoll` order: degraded handler, then resume handler): (i) alerts == 2, no throttle WARNING; (ii) `resume_if_refusals_cleared()` returned False and `is_degraded` is True; (iii) a second fire adds no alert. Variant (b): AMBIGUOUS #2 is also cleared before the first fire → that fire emits alert 2 and then resumes (True). Variant (c): AMBIGUOUS #2 added and cleared, then #3 added, all before one fire → alerts == 3. | AttributeError / 1 alert |
| T25 | same | **F1 clearing-path guard:** `test_a_node_booted_over_a_prior_process_open_with_id_intent_retires_it`. Boot a fresh rig over a store holding an OPEN with-id intent and its `RESOLVER_CONTEXT_KEY_PREFIX` context written by a prior "process" (the shape a SIGTERM after `_note_ambiguous_open` leaves). (i) Venue evidence = FILLED + LONG: `_connect`'s immediate pass retires it `STATUS_REPORT_ACCEPT_FILL_TERMINAL` before `_reconcile_submit_intent`, and boot logs no `Trading refused` (cites the existing `test_edge2_ac6b_cross_process_fill_budget.py::test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded`; if that test already covers (i) exactly, (i) is dropped and the citation stands). (ii) Venue evidence = terminal zero-fill with `created_ns` 10 s before boot: the immediate pass does NOT retire (min age), a periodic pass after the clock passes 120 s does, and no trading refusal is latched. (iii) No context key (the no-id shape): N passes leave it OPEN and `is_latched()` stays True (pins that the no-id case has no autonomous path, §5.1). | GREEN (guard) expected; any RED stops the build |

**Unmodified and must stay green:**
- `test_execution_egress_firewall_guard.py`, the entire file and every allowlist constant. E0-NOSEND-RESOLVER now scans the accept-fill clear lines and the two counter lines.
- `test_fq_caps_and_ambiguous_2026_10_01.py` and `test_current_rung_hold_ambiguous_resolver.py`, except the two edits named above.
- `test_exec_refusal_health_surface.py`'s existing tests, including the 25-producer pin. No `_refuse` call site is added.
- `test_component_health_watch_*`, `test_polymarket_us_exec_client.py`, including the NODE-GLOBAL pin and `:1081`.
- `tests/contract/test_refusal_repoll_live_clock_contract.py`.
- Every supervisor test (`test_trade_supervisor.py`, `test_ct*_supervisor_*`): the supervisor is not touched.

**One re-pin, reviewer-approved (precedent `3eb4a108`):** `_EXEC_CLIENT_SHA256` in `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`, with the comment updated to name this item. The assertion text is unchanged. This is a pin constant, not an assertion edit. **Corrected hunk count (F2):** the PR records:
- `git diff -U0 <base> -- src/breezy/adapters/polymarket_us/exec/client.py`, showing **exactly five hunks**:
  - H1: docstring invariant 1, the carve-out line at `:177-178`. The only modified (non-added) line.
  - H2: `__init__`, one added line `self._ambiguous_refusal_clears: int = 0` beside `:1697`.
  - H3: `_resolve_terminal_zero`, one added line (the counter increment) inside the existing clear branch `:3106-3112`.
  - H4: the accept-fill clear block, additions only, after `generate_order_filled`.
  - H5: the new method and property, additions only, after `_refuse`.
- A check that the `_submit_order` body (the deny chain) is byte-identical in content. Its lines shift. Verify with `git show <base>:<path>` vs HEAD, extract `_submit_order` via `ast.get_source_segment`, and compare sha256 values.
- The old sha `76784ce8…68a4` (equal to the current on-disk sha, verified 2026-10-03) and the new sha.

**PR claims (F2), exactly:** "Two existing test assertions are edited, both forced by the A3 ruling (fq `:419` inverted; ambiguous_resolver `:1308` re-expressed as `refusals_before` minus AMBIGUOUS, stricter). One sha pin constant is re-pinned. No other existing test is edited; the attached grep classifies every `trading_refusals` assertion." Do not say "only one assertion".

**Gate:**
- `scripts/ci/run_tests_no_egress.sh`: the full gate. Read EXIT before any push.
- `lint-imports` from the tree root ("N kept, 0 broken").
- ruff and mypy on the three source files.
- In a worktree, set `PYTHONPATH` to the worktree `src`. Never `uv sync`, `uv run` or pip.

---

## §4 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/adapters/polymarket_us/exec/client.py` | H1 carve-out sentence. H2 counter init. H3 one counter line in the zero-fill clear. H4 the accept-fill inline clear (with counter) as the last statement of `_resolve_accept_fill`, with a comment citing A3, the conservative ordering and the intended cross-session early return. H5 `resume_if_refusals_cleared()` and `ambiguous_refusal_clears` after `_refuse`; the docstring cites `component.pyx:1650/1641/1646/1638`, the missing RESUMING->DEGRADE edge, `is_latched` fail-closed, the F6 guard, why it is not called from the resolver, and "RUNNING is not an order gate". | ~20 + ~65 lines |
| `src/breezy/runtime/trade_cli.py` | `_exec_client_resume_handler(node)` and `_exec_client_ambiguous_clears_reader(node)` (missing client or attribute → 0). Capture the degraded-alert handler (`degraded_h = install_component_degraded_alert(..., ambiguous_reason=submit_chain.AMBIGUOUS_REASON, ambiguous_clears=...)`). `handlers=(recon_h, stale_h, contradiction_h, degraded_h, resume_h)`. One sentence in the FU-8b docstring paragraph. | ~40 lines |
| `src/breezy/runtime/component_health_watch.py` | `DEGRADED_ALERT_RENOTIFY_AFTER_NS`. Three keyword parameters with validation. RUNNING re-arm, AMBIGUOUS exemption, throttle, tick branch (§2.3). Notes docstring. Imports unchanged; "alerts and does nothing else" stays true. | ~55 lines |
| `tests/unit/test_ambig_latch_resume.py` | New: T1-T8b, T13-T16, T20-T25. | new |
| `tests/unit/test_component_health_watch_degraded_throttle.py` | New: T17-T19. | new |
| `tests/unit/test_exec_refusal_health_surface.py` | Append T9 and T10. | append |
| `tests/unit/test_trade_cli.py` | Append T11 and T12. | append |
| `tests/unit/test_fq_caps_and_ambiguous_2026_10_01.py` | Edit 1 (rename + final assert). | 2 lines |
| `tests/unit/test_current_rung_hold_ambiguous_resolver.py` | Edit 2 (`:1308`, minus AMBIGUOUS, plus the non-vacuity assert). | ~6 lines |
| `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py` | Re-pin `_EXEC_CLIENT_SHA256` and its comment. | 2 lines |
| `docs/core/PROGRESS.md` | Close the row with the merge sha. | doc |

Not touched:
- `submit_intent.py`, `safety.py`, the permit and its ceiling, `operator.env` or either operator cap, live enablement, the A1 family halt, `allow_short` (stays `False`).
- The NO-SEND firewall test and its allowlists.
- **The supervisor** (`trade_supervisor.py`, `trade_supervisor_core.py`): F1 is met by the activation procedure, not by a supervisor change.
- `.venv/` Nautilus.

---
## §5 Live activation

- **Load point.** All three source files load in the node process (`breezy-trade`), so a node respawn is required. The supervisor does not import them, so no supervisor restart.
- **Timing.** Per "activate code immediately": after the gate-green merge, inside 01:00-16:40Z, use the 2026-10-02 hand-relaunch recipe (scratch script importing the supervisor's own `resolve_store_path`, `intent_lock_path`, `resolve_lock_holder_pid`, `intent_lock_is_free`, `probe_open_intent`, `node_log_path`, `spawn_node`, `_retain_spawned_child`, plus `breezy.runtime.health.emit_alert`/`resolve_alert_sink`/`AlertPayload` for the §5.1 CRITICAL, under `systemd-run --user --scope --unit=breezy-node-handrelaunch-<ts>`), **amended by §5.1: the recipe's "probe after stop; abort if OPEN" step is replaced by S3/S4/S5.**

### 5.1 Precondition, deferral, and the clearing path (A1 + F1, coordinator ruling)

**What the supervisor does with an OPEN intent (code evidence; corrects r2).**
- `_do_launch` (`trade_supervisor.py:1233-1261`): with the flock free and an OPEN (or corrupt) intent, `decide_launch_action` (`trade_supervisor_core.py:532-542`) returns `REFUSE_INTENT_OPEN`; it logs `launch_refused_intent_open`, emits CRITICAL `INTENT_OPEN_BLOCKS_ARM`, and spawns nothing.
- `_handle_boot_retry_precheck_refusal` (`:1592-1619`): the same decision; logs `boot_retry_precheck_refused_intent_open`, CRITICAL, spawns nothing.
- `_do_stop_prior` (`:1131-1189`) SIGTERMs the node at 16:40Z **without** probing the intent.
- So the supervisor never clears an OPEN intent and never launches over one. **r2's claim that the node "stays down until the supervisor's 16:50Z launch" and that the supervisor "handles it" is withdrawn.** With the node down and the intent OPEN, the supervisor alone produces exactly the L-48 deadlock (the brief cites L-39; L-39 is the operator-control census lesson, and the deadlock lesson is **L-48**, "A latch whose only clearing path it blocks is a deadlock" — this plan follows L-48 and also obeys L-39 by naming no reserved control by its environment-variable name).

**What the node does with an OPEN intent (code evidence).** Nothing on the node's boot path refuses because an intent is OPEN. `_connect` (`client.py:1977-2084`) opens the store, waits for instruments, **awaits one immediate resolver pass** (`:2019-2025`, Item 2 of 2026-09-12), starts the periodic resolver (`:2040-2043`), then publishes the account, runs `_reconcile_submit_intent` → `reconcile_at_startup` (`:2158-2176`; `submit_intent.py:441-483`: copies a matching retired history record, or retires on a durable fill record, else leaves it OPEN), seeds spend, and refreshes startup evidence. While the intent is OPEN, every new `arm` is refused (`submit_intent.py:403-409` → `LATCH_ARM_REFUSED_REASON`, `client.py:5537-5544`), so a node booted over an OPEN intent cannot send. **The hand-spawned node is therefore the clearing path; spawning it is safe.**

**"A boot with an unresolved intent refuses once" — verified and handled.**
- Origin: 2026-09-12. The first relaunched boot latched a reconciliation refusal because Nautilus reconciliation ran *before* the resolver wrote the fill record; the next relaunch reconciled cleanly.
- Current code: closed for the common case by the awaited immediate pass, which runs before reconciliation and the spend seed (`client.py:1997-2025`). Pinned by `test_edge2_ac6b_cross_process_fill_budget.py::test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded` and `::test_respawn_seed_books_the_cross_process_fill_into_ledger_and_permit`.
- Residual shapes, which still refuse once:
  - (i) The immediate pass cannot confirm a **fill** (a transient GET or positions failure, or `long_state` not True with an incomplete join). A later periodic pass then retires it after `_spend_seeded = True`, which latches `_RESOLVER_FILL_UNBUDGETED` by design (AC6b, `client.py:2063-2069`). If the fill reached reconciliation first, a reconciliation refusal is also possible.
  - (ii) A **zero-fill** younger than 120 s is never retired by the immediate pass (`:2914-2922`). It leaves no position, so it latches no refusal; the periodic pass retires it a few minutes later.
- Handling: step S5 below. At most one follow-up relaunch, run after the intent is retired. That relaunch's seed books the fill (`:2062`), so the boot is clean.

**Can the intent lock be held from P1 through SIGTERM (F1(b))? No, not without touching the node's lock semantics:**
- The node holds the intent flock exclusively (`LOCK_EX | LOCK_NB`) for its whole lifetime (`submit_intent.py:556-596`, `open_submit_intent_latch`). An external process cannot take it while the node lives. `intent_lock_is_free` (`trade_supervisor.py:310-330`) only probes it.
- `arm` takes no per-call flock. It relies on that process-lifetime lock plus the instance mutex (`submit_intent.py:391-419`), so an external holder could not block an arm even if it had the lock.
- The only other arm-blocking control is the family halt. Setting it would touch a live-enablement control, which this item must not do. Rejected.
- **The residual gap is bounded instead:**
  - Window **W** runs from the P1 read to the strategy stopping. It is the P1→SIGTERM gap (sub-second: same script invocation, no sleep) plus SIGTERM→strategy stop. Upper bound: SIGTERM→`TradingNode: DISPOSED` ≈ 10 s, measured on the 2026-09-05 and 2026-10-02 relaunches. So **W ≲ 11 s**.
  - At the post-10-01 take rate (4.3/day, §2.7), spread uniformly: P(an arm lands in W) ≈ 4.3 × 11 / 86,400 ≈ **5.5 × 10⁻⁴ per relaunch**.
  - Worst case, 6 takes clustered in one hour: 6 × 11 / 3,600 ≈ **1.8 %**.
  - The no-id sub-case (below) additionally needs SIGTERM to cancel the POST in flight, which is rarer still.
  - Every case in W is detected by S3 and has a named path below.

**P1, the pre-stop probe. It is authoritative and the only pre-stop probe (F5: r2's P2 log-tail check is dropped).** Why P1 alone is sufficient: `arm` writes the OPEN singleton to the store **before** any POST (`client.py:5538` precedes `:5550`), and the store is the same source the supervisor probes. A log tail adds no case the store misses. A `SubmitOrder` not yet armed is the W race, which a log tail cannot see either. With the node live, `probe_open_intent` must NOT be used: its guard `assert_no_live_node_before_intent_probe` forbids a live node pid. The scratch script runs this function, with the env copied in memory from the supervisor (never printed):
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
- The `mode=ro` WAL read was exercised against the live store on 2026-10-03 (§2.7). It takes no flock.
- Prints only `OPEN` or `CLEAR`. Any exception counts as OPEN.

**Deferral when P1 says OPEN (F1(a)): the node is never stopped.**
1. Do not SIGTERM. Record `AMBIG-LATCH-RESUME activation deferred: open intent at <UTC>` in the execution log.
2. The node keeps running, so its resolver keeps working on the intent. Re-run P1 every 5 minutes (same-process retire latency 3-138 s, §2.7).
3. When P1 says CLEAR, continue at S1. P1 and the SIGTERM run in the same script invocation with no sleep between them.
4. If 16:40Z arrives with P1 still OPEN, abandon the hand relaunch. **Stated truthfully:** at 16:40Z the supervisor's `_do_stop_prior` SIGTERMs the node anyway, and if the intent is still OPEN at 16:50Z, `_do_launch` refuses. That is the supervisor's existing daily behaviour, which this item neither adds nor fixes. If it happens, the clearing path is the S2–S5 sequence run by hand after 16:50Z: the node is already down, so S1's lock assertion and S2 are skipped. Record it in PROGRESS. If the intent retires before 16:50Z, the 16:50Z launch loads the new code normally.

**Relaunch steps (only after P1 says CLEAR):**
- **S1.** Copy the env and set `BREEZY_PERMIT_EXPIRY_CEILING_NS` to the day's first-boot `expires_at_ns` (A-1). Assert that the old pid holds the intent lock. Run P1 one final time; if it says OPEN, return to the deferral.
- **S2.** SIGTERM, with no sleep after S1's P1. Wait for `TradingNode: DISPOSED` in bytes written after the kill, then for `intent_lock_is_free`.
- **S3. Post-stop probe:** `probe_open_intent(store_path, node_pid=None)`. This is the supervisor's own guarded probe; the node is dead, so its guard holds.
  - CLEAR → S4.
  - **OPEN (the W race) → raise the named CRITICAL**, then S4 anyway. Never leave the node down over an OPEN intent: that is the L-48 deadlock, and the supervisor will not break it.
    - Alert: `emit_alert(resolve_alert_sink(), AlertPayload(severity="CRITICAL", event="AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT", site="global", detail=<d>))`.
    - `<d>` is `with_context` if a read-only (`mode=ro`) read finds the key `RESOLVER_CONTEXT_KEY_PREFIX + <intent_id>` (`client.py:454`; the key `_note_ambiguous_open` writes, `:5304`). Otherwise `<d>` is `no_context`.
    - The alert sink comes from the copied supervisor env (the alerts.env egress convention). Nothing is printed.
- **S4.** `spawn_node`, then the boot proof (§5.2).
- **S5. Clearing watch (only when S3 said OPEN).** Watch the new node log FILE for `resolver: retired intent <id>`.
  - `with_context`: the immediate pass retires a confirmable fill at boot; a zero-fill retires on a periodic pass once older than 120 s. If the log shows that retirement and also any `Trading refused:` line between boot and the retirement (the refuse-once shape (i)), run **one** follow-up relaunch via S1–S4. P1 must now say CLEAR. If the follow-up boot also logs `Trading refused:`, raise CRITICAL `AMBIG_LATCH_RESUME_RELAUNCH_REFUSED_AFTER_FOLLOW_UP`, stop, and record it in PROGRESS. Never loop.
  - `no_context`: SIGTERM landed between `arm` and a with-id POST response. Either the POST was cancelled (`client.py:5555-5569`, no venue order id) or it was never sent. **No autonomous clearing path exists in code.** A no-id AMBIGUOUS is operator-only by design (`client.py:5825-5828`, `breezy-clear-submit-intent`, node not live), and T25(iii) pins that. The node stays up, but every arm is denied by the latch, so it is safe. The CRITICAL names this state. Recorded as residual risk R-NOID (§7), with probability bounded above. Building a no-id resolver is out of this item's scope.

**Clearing-path table (L-48 "How to apply"; F1 row).**

| Latch state at activation | Who clears it | In which process | Inputs | Runs while the latch is closed and across a day boundary? | Test |
|---|---|---|---|---|---|
| OPEN, P1 before stop (F1(a)) | The live node's resolver; the node is not stopped | The running node | Durable resolver context + venue GET + positions + activities | Yes: the resolver runs for the process lifetime; past-day instruments load via the past-day loader (L-48 original fix) | Existing resolver suites; T13/T24 for the post-clear behaviour |
| OPEN after stop, with-id context (F1(c), race W) | The hand-spawned node: immediate pass at `_connect`, then periodic | New node from S4 | Same as above, read from the store the prior process wrote | Yes: nothing on the node boot path refuses on OPEN (§5.1); the latch blocks only `arm` | T25(i)(ii); `test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded` |
| Retired, but a refuse-once boot latched a refusal | S5 follow-up relaunch (at most one) | Second new node | The durable fill record; the boot seed books it | Yes | `test_respawn_seed_books_the_cross_process_fill_into_ledger_and_permit` |
| OPEN after stop, no context (no-id) | **Operator-only** `breezy-clear-submit-intent` (existing, unchanged) | CLI, node not live | Venue evidence | No autonomous path; named CRITICAL; residual R-NOID | T25(iii) pins the absence |
| OPEN at 16:50Z with node down (supervisor's own daily cycle) | Same as rows 2/4, run by hand after 16:50Z | New node | As above | As above; pre-existing supervisor behaviour, not introduced here | Supervisor suites unchanged |

### 5.2 Proof

- **Boot proof:** the 4 boot lines, the permit line, and supervisor `permit_watch_adopted_live_node`, all in the node log FILE (not journald), plus `refusal re-poll timer armed`.
- **Positive in-service proof**, at the next AMBIGUOUS take (≈0.66–0.9/day, §2.7), in this order:
  1. `Trading refused: <AMBIGUOUS_REASON>` plus a `component_degraded` CRITICAL;
  2. `resolver: retired intent ... (STATUS_REPORT_ZERO_FILL_TERMINAL | STATUS_REPORT_ACCEPT_FILL_TERMINAL)`;
  3. `resolver: cleared the AMBIGUOUS trading refusal ...`;
  4. within ≤ one `REFUSAL_REPOLL_INTERVAL` (60 s), `health: resumed from DEGRADED ...` plus the native `RUNNING` INFO line;
  5. on the next AMBIGUOUS take: a second `component_degraded` CRITICAL, **always** (F3) — never a `component_degraded alert throttled` WARNING for an AMBIGUOUS episode.
- **Negative proof:**
  - No `InvalidStateTrigger` ERROR from the client, except the §2.6 RESUMING race, which must then be followed by the `re-degrading` WARNING.
  - No `RESUMING`/`RUNNING` between an `arm` and its retirement.
  - Count of `Trading refused: <AMBIGUOUS_REASON>` lines == count of AMBIGUOUS `component_degraded` CRITICALs over the observation window (F3/F6).
  - The permit line and its expiry are unchanged by any resume.

## §6 Rollback

- `git revert <merge sha>`. This restores the prior `_EXEC_CLIENT_SHA256`, the inverted fq pin and the `:1308` assertion. Run the full gate, then hand-relaunch under the same §5.1 procedure.
- After rollback, behaviour is exactly `3eb4a108`: zero-fill clears, a fill keeps denying until respawn, health stays DEGRADED, and there is one alert per process.
- There is no durable state, schema or key to migrate. The method and property write nothing; the counter, alert and throttle state are in-memory.

## §7 Risks

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| Alert volume | AMBIGUOUS ≈0.66–0.9/day at the current take rate, max 1/day observed; bounded by the take rate by the singleton latch (§2.7). | AMBIGUOUS unthrottled (F3); 1 h throttle for non-AMBIGUOUS repeats only. |
| A new AMBIGUOUS goes unalerted inside the clear-to-resume window | Was certain under r2 (no transition). | F6 counter + tick branch (T24). |
| The throttle hides a genuinely new failure | Low. | AMBIGUOUS exempt; new-reason bypass; a backwards clock alerts; a reader failure alerts (T19). |
| The accept-fill clear re-admits orders after a fill | Intended (A3); it changes admission. | Runs last, only when `current_open() is None`, only for AMBIGUOUS. Budget, caps, latch and halt unchanged. T14-T16. Written security sign-off on predicate strength (F4). |
| A firewall widening would be needed | None measured: all callees are allowlisted; the counter is an `AugAssign`. | Stop condition in §2.2. |
| A refusal during RESUMING leaves the client RUNNING with refusals | Latent. | Step 7 re-check (T22). |
| An arm lands in the P1→stop window (W) | ≈5.5 × 10⁻⁴ per relaunch uniform; ≤1.8 % clustered worst case (§5.1). | S3 detects it; named CRITICAL; S4 spawns the clearing node; S5 handles refuse-once. |
| **R-NOID:** the W race cancels the POST before a venue id exists | A strict subset of the W race. | No autonomous path (by design, `client.py:5825-5828`). CRITICAL `no_context`; node up and latched (cannot send); operator CLI. Recorded, not fixed here. |
| Supervisor 16:40Z stop + 16:50Z refusal over an OPEN intent | Pre-existing daily behaviour, independent of this item. | Not claimed as handled. The §5.1 table row 5 names the hand clearing path. |
| ≤60 s of residual DEGRADED after a clear | Certain, harmless: DEGRADED gates nothing. | `REFUSAL_REPOLL_INTERVAL`. |
| A future `_resume`/`_degrade` override adds I/O | Low. | T6. |
| A future edit calls the method from the resolver | Low. | E0-NOSEND-RESOLVER unmodified; T8a. |
| The re-pin or the two assertion edits are read as weakening a safety test | Process risk. | Five-hunk record, deny-chain content sha, the attached `trading_refusals` grep and its classification, exact PR wording (F2); both edits named and ruled (A3); edit 2 is stricter. |
| `current_rung_hold` `_on_event` sees extra events | Negligible. | Its alerters dedupe on count change. |

## §8 Build sequence

1. Write T1-T25 and confirm RED, except the GREEN guards T6, T8a, T15 and T25. Capture the output.
2. `component_health_watch.py`: constant, parameters, re-arm, AMBIGUOUS exemption, throttle, tick branch. T10, T17-T19 GREEN.
3. `client.py` H2 + H5 (counter init, method, property): T1-T8b, T20-T23 GREEN.
4. `client.py` H3 + H4 + H1 (both clear blocks with the counter, the carve-out): T13, T14, T16 GREEN. Apply edits 1 and 2 to the existing tests. T15 stays GREEN.
5. Re-pin the sha; record the five-hunk diff, the deny-chain content sha, and the `trading_refusals` grep classification.
6. `trade_cli.py` handlers, reader and wiring: T9, T11, T12, T24 GREEN.
7. Full gate (EXIT=0), `lint-imports`, ruff, mypy.
8. Independent review by reviewers who did not build it:
   - `trading-bot-architect`: FSM, races, F6 counting, and the §5.1 activation and clearing path;
   - `security-reviewer`: the NO-SEND proof, the A3 admission change, the two assertion edits, and the **written F4 sign-off on predicate strength** (merge-blocking).
9. Merge, then the §5.1 procedure (P1 → S1-S5), §5.2 proof, and the PROGRESS update.

## §9 Self-assessment

**Score: 94/100.**

What is left for peers:
- **O1 (carry):** the new-reason throttle bypass for non-AMBIGUOUS sets. It only adds alerts.
- **O2 (carry):** `_latch is None` stays fail-closed.
- **O3 (carry):** whether the T20 rig can be built with no permit, or needs an expired one.
- **O4 (carry):** T1 assumes `_arm_one_ambiguous_intent` can be `start()`ed into RUNNING. If not, fall back to `_build_rig` from `test_exec_refusal_health_surface.py`.
- **O5 (new):** W's upper bound uses SIGTERM→DISPOSED (≈10 s) as a proxy for SIGTERM→strategy-stop. The true arm-capable window is shorter. A tighter measurement would only lower the bound.
- **O6 (new):** R-NOID is accepted as residual, with an operator-only clear. An autonomous no-id resolver would be its own item; peers should confirm that leaving it out of scope is acceptable under L-48, given the bound.

---

## §R3 Disposition

| Item | Disposition | Where |
|---|---|---|
| **F1** [TBA HIGH] no deadlock after STOP (coordinator ruling) | **Applied as ruled.** (a) P1 OPEN → never stop; defer while the live node's resolver works. (b) Holding the intent lock from P1 through SIGTERM is **infeasible** without changing the node's lock semantics: the node owns the exclusive flock for its whole life, and `arm` takes no per-call flock (`submit_intent.py:391-419, 556-596`). The family halt was rejected because it is an enablement control. The gap is bounded instead: W ≲ 11 s, ≈5.5 × 10⁻⁴ per relaunch, ≤1.8 % clustered. (c) Post-stop OPEN → named CRITICAL `AMBIG_LATCH_RESUME_RELAUNCH_OPEN_INTENT` (`with_context`/`no_context`), then **spawn anyway**: the node's boot does not refuse on OPEN, and its immediate and periodic resolver is the autonomous clearing path (`client.py:1997-2043`). "Refuses once" was verified: the 09-12 origin, closed by the awaited immediate pass; residual shapes are handled by one bounded S5 follow-up relaunch. The no-id sub-case has no autonomous path (operator-only by design) and is recorded as R-NOID. A clearing-path table was added. The "supervisor handles it at 16:50Z" claim is dropped and replaced with code-cited supervisor behaviour (`:1131-1189`, `:1233-1261`, `:1592-1619`). The brief cited **L-39**; L-39 is the operator-control census lesson (obeyed: no reserved control is named by its env var). The deadlock lesson applied is **L-48**. | §0 goal 7, §1, §5.1, §7 |
| **F2** [sec HIGH] disclose the second test edit | **Applied.** `test_current_rung_hold_ambiguous_resolver.py:1308` is re-expressed as `refusals_before` minus AMBIGUOUS, plus a non-vacuity assert (stricter). The `trading_refusals` grep is shown and every hit is classified. The hunk count is corrected (five, including the F6 counter lines), and the exact PR wording is given. | §3, §4 |
| **F3** [sec] AMBIGUOUS never throttled (coordinator ruling) | **Applied as ruled.** `ambiguous_reason` is exempt from the throttle; every AMBIGUOUS episode emits one CRITICAL; other reasons stay throttled. Storm bound: the singleton latch caps AMBIGUOUS alerts at the take rate. T17/T18 now use a non-AMBIGUOUS reason; T23(ii) pins the exemption. | §2.3, §2.7, §3, §5.2 |
| **F4** [TBA] pin provenance | **Applied.** `87b3725b` is quoted verbatim (full sha). A side-by-side predicate table is added. A written security-reviewer sign-off that the fill predicate is at least as strong as the zero-fill one is merge-blocking. | §0 D3, §2.2, §8 |
| **F5** [TBA] P2 log-tail | **P2 dropped; P1 is authoritative.** Reason: `arm` persists OPEN before any POST, so the store already shows every in-flight take; a log tail adds nothing. | §5.1 |
| **F6** [TBA] second AMBIGUOUS before resume | **Applied, with a design fix.** The resume is refused (step 2; step 5 while that intent is OPEN). The alert gap is real: no transition happens, pinned by `test_polymarket_us_exec_client.py:1081`. It is closed by `ambiguous_refusal_clears` (one int, incremented in both clear blocks, with no new callee) plus the degraded-alert closure registered on the re-poll timer (the FU-8b pattern). The count is exact even when an AMBIGUOUS is added and cleared between ticks. T24 covers three variants. | §0 D2, §2.1, §2.3, §2.3a, §2.6, §3 |
| LOW: period mismatch | **Applied.** 2.3-day rate × 29-day fraction is stated; bracket 0.66–0.9/day. | §2.7 |
| LOW: T14(ii) isolation | **Applied.** Labelled as an isolation test that does not represent a reachable AMBIGUOUS state. | §3 |
| LOW: cross-session early return | **Applied.** Stated as intended, with the reason. | §2.2 |
| LOW: T4(iii) DEGRADING spy | **Applied.** A concrete msgbus spy on the synchronous DEGRADING publish. | §3 |

Invariants restated: Nautilus is unmodified; `allow_short=False`; the caps, permit, ceiling and live enablement are untouched (the family halt was explicitly rejected as an F1 tool); the NO-SEND firewall and its allowlists are unmodified and not widened; the supervisor is unmodified; no safety test is weakened (the two ruled A3 assertion edits are disclosed, and one is stricter).

---

## §R2 Disposition (kept from r2 for the record)

| Item | Disposition | Where |
|---|---|---|
| **A1** [TBA HIGH] hard precondition on relaunch | Applied in r2; **revised in r3 by F1 and F5** (P2 dropped; post-stop OPEN now spawns the clearing node instead of leaving it down). | §5.1 |
| **A2** throttle now (coordinator ruling) | Applied in r2; **AMBIGUOUS exempted in r3 by F3.** | §2.3, §2.7 |
| **A3** accept-fill path in scope (coordinator ruling) | Applied in r2; **r3 corrects the test-edit count to two (F2) and adds the predicate table (F4).** | §0 D3, §2.2, §3 |
| **A4** [sec] scope in §2.3 | Applied. | §2.4, §3 |
| **A5** race tests | Applied; the F6 race was added in r3. | §2.1, §2.6, §3 |
| LOW: split T8 | Applied. | §3 |
| LOW: cite the re-poll constant | Applied. | §0, §5.2, §7 |
| LOW: record the re-pin diff and the new sha | Applied; **five hunks in r3.** | §3 |
