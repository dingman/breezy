# SUP-RESTART-ANYTIME: plan r1 (2026-10-03)

Status: DRAFT r1, for peer review. Plan only: no code.
Backlog row (docs/core/PROGRESS.md:97): "Proposed: adopting a live, ready node marks `launch_done`/`readiness_observed`, so the supervisor can deploy at any time. Needs a plan and peer review".
Related: CT13-FLAKE (PROGRESS.md:98), SUP-ADOPT-PERMIT, SUP-ADOPT-LOG-GLOB, FU-17, A-1, B1.

Every code citation below was read on 2026-10-03 through codegraph (`projectPath=/home/jon/breezy`) or a direct read of the named lines.

---

## §0 Problem and goal state

### Problem (verified in code)

`_run_forever` (`trade_supervisor.py:2668`) seeds `state = initial_scheduler_state(_trading_day(clock()))`. Every latch starts out `False`/`None`, because `DaySchedulerState` is in memory only.

`next_due` (`trade_supervisor_core.py:1123-1128`) dispatches `MIDDAY_WATCH` only when `launch_done and (readiness_observed or boot_zero_instruments_seen)` and `watch_open_at <= now < watch_close_at`. That window runs from 17:10Z on trading day D to 01:00Z on D+1.

So a supervisor restarted at any instant in [17:10Z, 01:00Z) has `launch_done=False` for the rest of that trading day:

- B1 (`_do_permit_watch`) does adopt the live node, and it replays the node's boot log from byte 0 (SUP-ADOPT-PERMIT, `trade_supervisor.py:2063-2075`, `:2012-2043`). Nothing ever sets `launch_done` or `readiness_observed`, though.
- `MIDDAY_WATCH` never becomes due. **The mid-day relaunch duty is lost for the rest of the day**: if the node dies at 21:00, nobody relaunches it.
- `midday_budget_live(launch_done=False, ...)` also changes B1's DEFERRED/NO_NODE classification.

That is why the memory "supervisor-changes-need-a-supervisor-restart" restricts restarts to [01:00Z, 16:40Z).

The next STOP_PRIOR is not lost. `_do_stop_prior` (`:1150-1151`) falls back to `find_node_pid()` when nothing is tracked, and `tests/unit/test_trade_supervisor.py:2947 test_adoption_at_1640_after_a_0300_start` pins that. The restarts inside the launch window are already handled by `_do_launch`'s [D2] adoption (`:1236-1243`) and by `_do_self_check`'s adoption (`:2333-2339`). The gap is therefore narrow and specific: **no path re-derives `launch_done` + `readiness_observed` for an adopted node after 17:10Z.**

### Goal state (acceptance test for the whole plan)

A `systemctl --user restart breezy-trade-supervisor` at **any** UTC instant:

1. never spawns a second `breezy-trade` while one holds the intent flock (no double launch);
2. never relaunches or signals a live, ready node outside the scheduled STOP_PRIOR;
3. keeps that trading day's STOP_PRIOR, LAUNCH, RELAUNCH_CHECK, SELF_CHECK and MIDDAY_WATCH duties. MIDDAY_WATCH is restored within 2 polls (≤ 120 s plus one poll) of the restart, and only for a node **proven** ready;
4. never sets `launch_done`/`readiness_observed` for a node that is not proven ready. Proven ready means all of the following:
   - alive;
   - it is the verified flock holder **at the marking poll**;
   - its own permit line is latched with `expires_at_ns > now`;
   - its strategy-subscribed marker is latched;
   - its log belongs to the current trading day;
   - its log is advancing;
5. fails closed on the CT13 transient: a `None` holder probe means "not proven" on that poll, and it is retried the next poll. It never means "ready" and never means "dead, relaunch".

When this ships, the restart-window restriction in the memory and in `deploy/systemd/README.md` is retired. Merged supervisor code is then activated immediately, per the "activate-code-immediately" ruling.

---

## §1 Null hypothesis (L-1): what already exists and is reused

| Need | Existing mechanism | Verdict |
|---|---|---|
| Node survives a supervisor restart | `KillMode=process` in `deploy/systemd/breezy-trade-supervisor.service`. The node is `start_new_session=True` but stays in the cgroup; only the supervisor main pid is signalled. | **Reuse unchanged.** No unit edit. |
| Identify the live node, fail closed | `_attempt_adoption` (`trade_supervisor.py:1193-1206`): `find_node_pid() == resolve_intent_lock_holder(lock)` over `/proc/locks`. Returns `None` on any mismatch or `None`, which is the CT13 fail-closed behaviour. | **Reuse.** No new adoption path. |
| Recover boot-time evidence after a restart | `_permit_watch_replay_boot_log_on_adoption` (`:2012-2043`): from-byte-0 replay into `latch_log_facts`. That latches `strategy_subscribed_seen`, `permit_issued_seen_expires_at_ns`, `first_boot_permit_expires_at_ns` (A-1) and `boot_zero_instruments_seen`. OSError is retried, then fails loud. | **Reuse.** It already runs on every B1 adoption in [17:10, 01:00). |
| Readiness predicate | `readiness_observed(holds_intent_lock, permit_issued, strategy_subscribed)` (`core:563-570`), used identically by RELAUNCH_CHECK, the boot-retry hand-off and the midday recheck. | **Reuse.** The new rule calls it, plus two extra guards (permit unexpired, log advancing/current-day) that the brief requires. |
| Latch writers | `record_readiness_observed` (`core:1227`), `mark_phase_fired(..., Phase.LAUNCH, ...)` (`core:1151-1164`). | **Reuse.** Both are composed; no parallel writer. |
| Per-child reset | `record_child_adopted` (`core:1167-1196`). | **Reuse.** It is extended by one field. |
| Log file → spawn time | `node_log_path` stamps `breezy-trade-YYYYMMDDTHHMMSSZ.log` (`:787-789`). `_NODE_LOG_NAME_RE` (`:799`). `find_adopted_node_log` (`:815`) picks the newest node-stamped log whose mtime ≥ `/proc/<pid>` ctime. | **Reuse** the stamp as current-trading-day evidence. |
| Containment | B1's `[D8]` try (`:2160-2222`) plus `_dispatch_permit_watch`'s outer `[A2]` try (`:2542-2559`). | **Reuse.** The new step runs inside `_do_permit_watch`'s try. |
| systemd `ExecReload=` / hot reload | A Python process cannot safely re-import changed modules in place, and nothing in the repo supports it. | **Rejected.** It does not remove the restart. |
| systemd `FileDescriptorStoreMax=` (memfd state carry-over) | It would persist `DaySchedulerState` across restarts, but across a **deploy** that means unpickling old-schema state into new code. It also re-trusts latches (e.g. readiness of a node that died during the restart gap) without re-proving them. | **Rejected.** Re-deriving from live evidence is self-validating; carried-over state is not. |
| Persisting `DaySchedulerState` to the exec store (precedent: `SELF_CHECK_ESCALATION_STORE_KEY`, `:2418-2421`) | Same stale-latch and schema-drift objections. It would also add a writer to the exec store during live trading. | **Rejected** for this item. |
| Nautilus | The supervisor is an external process manager; Nautilus has no process-supervision or adoption facility to extend. The node itself is untouched. | N/A. Nautilus stays immutable. |

**Conclusion.** The only missing piece is one pure decision plus one state recorder. They are wired at one site (`_do_permit_watch`'s in-window branch), right after the existing adoption and replay. There is no new adoption logic, no unit change and no persistence.

---

## §2 Design

### 2.1 New pure core (in `trade_supervisor_core.py`, stdlib-only, beside `decide_midday_recheck`)

```
class ReadyAdoptionVerdict(str, Enum):
    MARK = "mark"
    NOT_IN_WINDOW = "not_in_window"
    ALREADY_READY = "already_ready"
    NO_CHILD = "no_child"
    HOLDER_UNPROVEN = "holder_unproven"          # CT13: None or mismatch
    PERMIT_ABSENT = "permit_absent"
    PERMIT_EXPIRED = "permit_expired"
    NOT_SUBSCRIBED = "not_subscribed"
    LOG_NOT_CURRENT_DAY = "log_not_current_day"  # stamp < trading-day open, or unparseable / unknown log
    LOG_NOT_ADVANCING = "log_not_advancing"      # no prior size probe yet, or size did not grow

def decide_ready_adoption(
    *, state: DaySchedulerState, now: dt.datetime, now_ns: int,
    child_alive: bool, holder_is_tracked: bool,
    log_spawned_at: dt.datetime | None,
    log_size: int | None,
) -> ReadyAdoptionVerdict
```

The checks run in this order. The first failing check wins, which makes each verdict testable on its own.

1. Window. `permit_watch_window(state.day)` must contain `now`, i.e. [D 17:10Z, D+1 01:00Z). This is the same boundary as MIDDAY_WATCH/B1 (D1: no third boundary). Outside it the verdict is `NOT_IN_WINDOW`.
2. `ALREADY_READY` when `state.readiness_observed`. The keying is on readiness, **not** on `launch_done`. See case C3 below: `_do_launch` can set `launch_done=True` on a lock-held refusal without readiness, and that day must still be recoverable.
3. `NO_CHILD` when not `child_alive`.
4. `HOLDER_UNPROVEN` when not `holder_is_tracked`. The caller computes `holder_is_tracked` from a **fresh** `resolve_intent_lock_holder` call on this poll, as `holder is not None and holder == tracked_pid`.
5. `PERMIT_ABSENT` when `state.permit_issued_seen_expires_at_ns is None`, and `PERMIT_EXPIRED` when it is `<= now_ns`.
6. `NOT_SUBSCRIBED` when not `state.strategy_subscribed_seen`.
7. `LOG_NOT_CURRENT_DAY` when `log_spawned_at is None` or `log_spawned_at < _at(state.day, STOP_PRIOR_UTC)`.
8. `LOG_NOT_ADVANCING` when `log_size is None`, or `state.ready_adoption_log_size_probe is None`, or `log_size <= probe`.
9. Otherwise `MARK`.

Checks 4–6 are exactly `readiness_observed(...)`'s three conjuncts. The implementation calls `readiness_observed(...)` and then maps a `False` result to the specific reason (one shared predicate, no copy).

```
def record_ready_adoption_log_probe(state, now_utc, size: int) -> DaySchedulerState
def record_ready_adoption(state, now_utc) -> DaySchedulerState
    # = record_readiness_observed(mark_phase_fired(state, Phase.LAUNCH, now_utc), now_utc)
def node_log_spawned_at(name: str) -> dt.datetime | None
    # parses the stamp of _NODE_LOG_NAME_RE; None on any other shape
```

`_NODE_LOG_NAME_RE` is moved, unchanged, from `trade_supervisor.py:799` into core so that the pure parser and `find_adopted_node_log` share one pattern. The shell re-imports it under the same name, so existing references and tests stay valid.

New `DaySchedulerState` field:

```
#: [SUP-RESTART-ANYTIME] Per-child size of the adopted node's log at the
#: previous ready-adoption poll. Two strictly increasing samples one poll
#: apart are the "log advancing" proof. Cleared by record_child_adopted
#: (a new child) and by _for_day (rollover).
ready_adoption_log_size_probe: int | None = None
```

`record_child_adopted` adds `ready_adoption_log_size_probe=None` to its `replace(...)`. That is purely additive: every existing field is still cleared exactly as before.

**Why "advancing" is measured by size growth rather than an mtime-age threshold.** `IncrementalLogReader`'s own docstring (`:702-706`) records ~100 KB/min of node log growth. Strict growth across one 60 s poll is therefore a threshold-free proof, and it needs no new tunable constant. Stage 0 re-measures it (§6 R2).

**Why the log stamp proves the current trading day.** Permit-unexpired alone does not: a node hand-launched at D 10:00 has an unexpired 10 h permit at D 17:10, yet it belongs to trading day D−1. The stamp is written by `node_log_path` at spawn, and hand relaunches mirror `spawn()`, per the "hand-relaunch-mechanics" memory. `find_adopted_node_log` already binds the file to the pid (mtime ≥ `/proc/<pid>` ctime). An unknown log (`None`) fails closed.

### 2.2 New shell step (in `trade_supervisor.py`)

```
def _ready_adoption_step(
    *, ports, state, now, now_ns, tracked_pid, node_log, store_path,
) -> DaySchedulerState
```

- It returns at once (no port calls) when `state.readiness_observed`, or when `tracked_pid is None`, or when `node_log is None`. The last case means the log is unknown, and degrading never marks.
- Otherwise it reads `child_alive = ports.process_alive(tracked_pid)`, a fresh `holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))`, and `size = ports.log_size(node_log)`. It then calls `decide_ready_adoption`.
- On `MARK` it applies `record_ready_adoption` and logs `log_decision("restart_adopted_ready_node", pid=tracked_pid)` at INFO, with no alert. This is the activation evidence line.
- On every other verdict, when `size is not None`, it records the probe. On `HOLDER_UNPROVEN` it also logs `log_decision("ready_adoption_deferred", reason=verdict.value)`, which makes the CT13 transient observable (de-duplicated to the first occurrence per child via the probe being `None`). There is no alert: B1's existing capability alerting is unchanged and stays the paging path.

New port, defaulted so that every existing `_make_ports(...)` test fixture is unaffected:

```
log_size: Callable[[Path], int | None] = field(default=_log_size)  # os.stat(...).st_size; None on OSError
```

**Wiring (one site).** In `_do_permit_watch`'s in-window branch (`:2189-2199`), the current `return _permit_watch_adopt_and_evaluate(...)` becomes:

```
tracked_pid, node_log, state = _permit_watch_adopt_and_evaluate(...)
state = _ready_adoption_step(ports=..., state=state, now=now, now_ns=now_ns,
                             tracked_pid=tracked_pid, node_log=node_log, store_path=store_path)
return tracked_pid, node_log, state
```

The step is not run in the `now >= window_close` branch, where the window is closed and the step would be a no-op anyway. It inherits B1's `[D8]` containment and `[A2]` outer containment. Any exception from the step yields `WATCH_FAILED` handling through `_contain_permit_watch_failure`, never a mark.

**Effect.** On the iteration after `MARK`, `next_due` returns `MIDDAY_WATCH` (`core:1123-1128`). The existing handler then owns the node: mid-day relaunch with the A-1 ceiling, the readiness recheck and alerts. B1's `midday_budget_live` now sees `launch_done=readiness_observed=True`, which matches a supervisor that never restarted.

### 2.3 What is deliberately NOT changed

- `next_due`, `decide_launch_action`, `_do_launch`, `_do_stop_prior`, `_do_self_check`, `_do_midday_watch` and `decide_relaunch`. All existing restart tests (`test_trade_supervisor.py:2100-2150`, `:2947`, `:3939`, `:3958`, `:5428`, `:6244-6470`, `:6777-6820`) stay byte-identical and green.
- `deploy/systemd/breezy-trade-supervisor.service`. No edit, so no daemon-reload is needed to activate; the symlink hazard does not apply.
- Permit minting, operator caps, `BREEZY_*_ENABLED`, the NO-SEND firewall and the A-1 ceiling env all stay unchanged. The supervisor still never spawns from this step. **The step has no spawn, signal or store-write capability**: it receives only read ports.

---

## §3 Restart instants across the day: correct behaviour

D = trading day (`_trading_day`; it opens at D 16:40Z). "Old" = the supervisor before restart; "new" = after.

| # | Restart instant (UTC) | Node state at restart | Correct behaviour after this plan | Path (existing / new) |
|---|---|---|---|---|
| A1 | [01:00, 16:30) | D−1 node live and ready | Nothing is due; B1 and MIDDAY windows are closed. No mark: `NOT_IN_WINDOW`, and marking would be useless anyway. At 16:40 STOP_PRIOR finds the node by `find_node_pid` and SIGTERMs it. | existing (`:2947`) |
| A2 | [01:00, 16:30) | down | Nothing; LAUNCH at 16:50 as usual. | existing |
| B1 | [16:30, 16:40). Canary 16:30; the launch window opens. | D−1 node live | Same as A1. The trading day is still D−1, so `_for_day` rolls at 16:40 regardless. | existing |
| B2 | [16:40, 16:50), STOP not yet done by old | D−1 node live | Fresh state → STOP_PRIOR is due immediately → SIGTERM via the TOCTOU-rechecked terminate. Required **before** the 16:45 engine pass, which needs "no node runs" (AUTONOMY_ARCHITECTURE.md:879-885). A restart delays STOP only by the restart duration (seconds). If the supervisor was *down* across 16:45 (crash + `RestartSec=60`), the engine pass sees a node, its §4.4 check fails, and it defers. That is fail-closed and already the designed behaviour (R4 row, AUT-7). | existing |
| B3 | [16:40, 16:50), STOP already done by old | down (stopped) | Fresh state → STOP_PRIOR is re-run → `find_node_pid()` None, holder None → `stop_prior_noop`. Idempotent, with no signal, so it never disturbs the 16:45 pass. **No mark**: the window is not open, and a node seen here is by definition D−1's. | existing |
| B4 | [16:40, 16:50), STOP refused by old (REFUSE_ALERT) | D−1 node live, holder ≠ discovered | New re-runs STOP → same refusal and the same CRITICAL (a duplicate page, the accepted direction). Never a second LAUNCH while the flock is held (see B6). | existing |
| B5 | [16:50, 17:00), old has launched D node | D node live (ready or booting) | LAUNCH is due on fresh state → `_do_launch`: `lock_free=False` → `REFUSE_LOCK_HELD` → `_attempt_adoption` → adopt, **no spawn**, `launch_done=True`. RELAUNCH_CHECK then latches readiness from a fresh reader (offset 0 = full log) with `holder == tracked_pid`. | existing (`:3939`) |
| B6 | [16:50, 17:00), CT13 transient on the adoption probe | D node live | `_attempt_adoption` → None → `launch_refused_lock_held` WARN, LAUNCH marked fired, nothing tracked, **no spawn** (the flock is held). RELAUNCH_CHECK returns early. SELF_CHECK at 17:05 re-attempts adoption. From 17:10, B1 adopts and **the new step marks readiness** once proven (C3), restoring MIDDAY_WATCH. **Today this day loses MIDDAY_WATCH; that is a second gap this plan closes.** | existing + **new** |
| B7 | [16:50, 17:00), old launched but the child died | down, flock free | Fresh state → LAUNCH spawns once (the lock is free and no pid is present). This is a relaunch inside the cutoff, and it is not a double launch: the flock plus `launch_refused_pid_present` (`:1227-1231`) forbid concurrency. Residual: the boot relaunch budget restarts at 0 (§6 R4). | existing |
| B8 | [16:50, 17:00), old crashed before spawning | down | LAUNCH spawns once. | existing |
| C1 | [17:00, 17:05) | D node live | Nothing is due until 17:05. SELF_CHECK adopts (`:2333-2339`) and reads the full log (fresh reader). The window is not yet open, so no mark. At 17:10 B1 runs with the tracked pid alive (no re-adoption), and the new step probes the size. At 17:11 it marks → MIDDAY_WATCH. | existing + **new** |
| C2 | [17:05, 17:10) | D node live | Same as C1 (SELF_CHECK is due immediately). | existing + **new** |
| C3 | [17:10, 01:00) | D node live and ready | Poll 1: B1 adopts plus the byte-0 replay (permit, subscribed and A-1 anchor latched); the step records the size probe (`LOG_NOT_ADVANCING`). Poll 2: the size grew, the holder is fresh-verified, the permit is unexpired and the stamp is ≥ D 16:40 → `MARK`. Poll 3: MIDDAY_WATCH. No spawn, no signal. | **new** |
| C4 | [17:10, 01:00), CT13 transient | D node live | If B1's `_attempt_adoption` sees None, nothing is adopted this poll (existing fail-closed) and it is retried next poll. If the adoption succeeded but the step's fresh holder probe is None, the verdict is `HOLDER_UNPROVEN` → no mark, logged, retried next poll. A persistent None never marks and never spawns; B1's existing capability alerting covers the operator signal. | existing + **new** |
| C5 | [17:10, 01:00) | D node live, permit expired (e.g. a midday child at the A-1 ceiling) | `PERMIT_EXPIRED` → never marked. B1 classifies LAPSED/EXPIRED_AT_CEILING as today. MIDDAY_WATCH stays off, which is correct: the node cannot trade, and relaunching it would not widen the A-1 ceiling either. | **new** (guard) |
| C6 | [17:10, 01:00) | live node from a previous trading day (STOP refused), unexpired permit | `LOG_NOT_CURRENT_DAY` → never marked. | **new** (guard) |
| C7 | [17:10, 01:00) | live node booting (old was mid-midday-relaunch) | Permit or subscription not yet latched → no mark. The step re-evaluates every poll; the latches come from B1's ordinary incremental drain (`:2088-2092`). It marks once the node is proven ready. Residual: B1 may page ABSENT for this booting child (§6 R5). | existing + **new** |
| C8 | [17:10, 01:00) | down | `_attempt_adoption` → None (no pid) → nothing tracked → the step returns early. **No mark, no spawn.** B1 pages NO_NODE as today. Intended: without proof that today's launch happened and of its A-1 anchor, a supervisor must not spawn a sending node mid-day (`_do_midday_watch` itself refuses without the anchor, A-1). | existing |
| C9 | [17:10, 01:00), old had already marked and the node is fine | D node live and ready | Identical to C3. The new process re-proves from evidence; it inherits nothing. | **new** |
| D1 | [00:00, 01:00) (UTC date rolled, trading day D) | D node live and ready | `_trading_day` → D; the window is still open → same as C3. | **new** |

**Never double-launch (invariant, proved by construction plus the sweep test T14).** The new step has no spawn port in its signature. LAUNCH is only ever due in [16:50, 17:00), and it spawns only on `lock_free and node_pid is None and not open_intent`. MIDDAY_WATCH spawns only for a tracked child that is dead. Marking makes MIDDAY_WATCH due only for a node proven alive and holding the flock at that poll.

**The 16:45 engine pass and the 16:50 LAUNCH.** The new step can never run in [16:40, 17:10), because the window check runs first. So this plan changes nothing about STOP-before-16:45, the engine's `engine.lock` pass, or the 16:50 resolver/LAUNCH sequence.

---

## §4 Tests: RED → GREEN

Placement: pure tests go in `tests/unit/test_trade_supervisor_core.py`; shell tests in `tests/unit/test_trade_supervisor.py` (reusing `_make_ports`, `_utc`, `_DAY`, `_b1_common_kwargs`, `_RecordingAlertSink`); real-process tests in a new `tests/unit/test_ct14_supervisor_restart_anytime.py` modelled on `test_ct02_supervisor_adopt_real_child.py`. Each test below must be observed **failing first**: an ImportError for the new symbols counts as RED only for T1–T4, and T5–T16 must fail on an assertion against current behaviour. The RED→GREEN output is kept as the change artifact.

**Pure (core)**
- T1 `test_decide_ready_adoption_marks_only_when_every_proof_holds`. Table-driven: start from an all-true baseline, flip each input in turn, and assert the specific verdict for each of the ten values.
- T2 `test_decide_ready_adoption_window_boundaries`. 16:45, 17:05 and 17:09:59 → NOT_IN_WINDOW; 17:10:00 → evaluated; D+1 00:59:59 → evaluated; D+1 01:00:00 → NOT_IN_WINDOW.
- T3 `test_ready_adoption_keys_on_readiness_not_launch_done`. `launch_done=True, readiness_observed=False` → can MARK (case B6). `readiness_observed=True` → ALREADY_READY.
- T4 `test_record_ready_adoption_sets_both_latches_and_nothing_else`. It sets `launch_done` and `readiness_observed`. It leaves untouched `relaunch_attempts`, `midday_relaunch_attempts`, `first_boot_permit_expires_at_ns`, `self_check_done` and every alert latch. It is idempotent and day-scoped (`_for_day`).
- T5 `test_record_child_adopted_clears_ready_adoption_log_size_probe`, plus the rollover reset. This extends the existing rollover-reset test pattern by adding a new field to the expected reset; no existing assertion is removed.
- T6 `test_node_log_spawned_at_parses_node_stamp_only`. It parses node stamps and returns None for `breezy-trade-supervisor.log` and its `-stdout-`/`.launch-` variants.
- T7 `test_permit_unexpired_alone_does_not_prove_current_day`. Stamp D 10:00, permit expiring D 20:00, now D 17:30 → LOG_NOT_CURRENT_DAY.

**Shell (fake ports and a fake clock driving `_run_forever` with `max_iterations`)**
- T8 `test_restart_at_2000_with_ready_node_restores_midday_watch_without_spawn`. Iteration 1 adopts (B1). Iteration 2 marks: assert the `restart_adopted_ready_node` line. Iteration 3 dispatches MIDDAY_WATCH (spy on `_do_midday_watch`, or on `next_due` returning it). `spawn` and `terminate_after_recheck` are never called. **RED today**: MIDDAY_WATCH never dispatches.
- T9 `test_ct13_transient_holder_none_defers_mark_and_never_spawns`. The holder sequence is `[pid, None, pid, pid]` (the adoption probe succeeds and the marking probe is None) → no mark on that poll; it marks on a later poll. Variant: a persistent None never marks and spawns 0 times.
- T10 `test_expired_permit_node_is_never_marked`. Asserts the B1 alert set is unchanged versus a run with the step disabled.
- T11 `test_non_advancing_log_is_never_marked`: the size stays constant.
- T12 `test_node_down_at_restart_is_never_marked_and_never_spawned` (C8).
- T13 `test_1655_lock_held_adoption_flake_recovered_at_1710` (B6). `_do_launch` adoption fails → no spawn → from 17:10 the step marks → MIDDAY_WATCH. **RED today.**
- T14 `test_restart_sweep_never_double_launches`. Restart at every 5 min across 24 h (288 fresh `_run_forever` runs, each advancing 30 min of fake clock). The world model has one live ready node, which the D 16:40 STOP_PRIOR removes, plus a successor spawned at 16:50. Assert: concurrent live `breezy-trade` ≤ 1 at every step; spawn count ≤ 1 per trading day; terminate only inside [16:40, 16:50); `restart_adopted_ready_node` only inside [17:10, 01:00).
- T15 `test_marked_adopted_child_death_relaunches_with_adopted_ceiling`. After the mark the child dies with a transient cause → MIDDAY_WATCH relaunch spawns once with `BREEZY_PERMIT_EXPIRY_CEILING_NS` equal to the adopted node's latched expiry. This proves that the duty is restored and that the A-1 ceiling is never widened.
- T16 `test_ready_adoption_step_exception_is_contained_as_watch_failed`. `log_size` raises → no mark, and the loop continues.

**Real process (CT-14, real `/proc/locks`)**
- T17 `test_real_flock_holder_with_growing_log_is_marked_after_restart`. Spawn a real child that takes the intent flock and appends a permit line, a subscribed line and a heartbeat line every 0.2 s to a correctly stamped log. Drive `_run_forever` at fake 20:00 with the real `resolve_lock_holder_pid` / `find_adopted_node_log` / `_log_size`. Assert the mark, zero spawns, and that the child pid is unchanged.
- T18 `test_real_live_pid_not_holding_flock_is_never_marked`, mirroring ct02 `:242`.

**Unchanged and must stay green (cited, not edited):** `test_trade_supervisor.py:2100-2150` (pure `next_due` restart table), `:2947`, `:3939`, `:3958`, `:5428`, `:6244-6470`, `:6777`, `:6803`, `test_ct02_*`, `test_ct13_*`, `test_trade_supervisor_unit_directives.py` (KillMode pin).

**Gate (all required, read the EXIT code):**
- `scripts/ci/run_tests_no_egress.sh`, full gate, run through the project interpreter; never `uv run`/`uv sync`.
- Focused: `tests/unit/test_trade_supervisor_core.py tests/unit/test_trade_supervisor.py tests/unit/test_ct14_supervisor_restart_anytime.py tests/unit/test_ct02_supervisor_adopt_real_child.py tests/unit/test_ct13_supervisor_crash_readopt.py`.
- `ruff`, `mypy`, and `lint-imports` from the tree root, demanding the "N kept, 0 broken" line. Core must stay stdlib-only.

---

## §5 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/runtime/trade_supervisor_core.py` | Add `ReadyAdoptionVerdict`, `decide_ready_adoption`, `record_ready_adoption`, `record_ready_adoption_log_probe` and `node_log_spawned_at`. Move `_NODE_LOG_NAME_RE` here unchanged (it may need a capture group added for the stamp; if so, a second pattern is derived from the same literal, never edited in place). Add the `ready_adoption_log_size_probe` field with its docstring. Add one kwarg in `record_child_adopted`'s `replace`. | ~90 lines |
| `src/breezy/runtime/trade_supervisor.py` | Add the `_log_size` default port and the `SupervisorPorts.log_size` field (defaulted). Re-import `_NODE_LOG_NAME_RE`. Add `_ready_adoption_step`. Make the 3-line wiring change in `_do_permit_watch`'s in-window branch. | ~50 lines |
| `tests/unit/test_trade_supervisor_core.py` | T1–T7 | new tests only |
| `tests/unit/test_trade_supervisor.py` | T8–T16 | new tests only |
| `tests/unit/test_ct14_supervisor_restart_anytime.py` | T17–T18 (new file) | new |
| `deploy/systemd/README.md` | Replace the "restart only 01:00–16:40Z" guidance with "restart any time; verify `restart_adopted_ready_node` (in window) or `stop_prior_*`/`launch_adopted_live_node` (launch window)". | doc |
| `docs/core/PROGRESS.md` | Close the SUP-RESTART-ANYTIME row with the merge sha. Annotate CT13-FLAKE: "ready-adoption defers on a None holder; covered by T9". | doc |
| Memory `supervisor-changes-need-a-supervisor-restart.md` | Coordinator updates it after verified activation; this is not part of the code change. | — |

The unit file is **not** edited. `KillMode=process`'s comment says "re-adopts ... at the next 16:40Z cycle". It is now incomplete but still true, and a comment-only edit is deferred so that this change never needs a daemon-reload.

---

## §6 Risks and residuals

- **R1. False MARK leads to MIDDAY_WATCH acting on the wrong node.** It needs all seven proofs on one poll, including a fresh flock-holder match and a current-day stamp. Even then, a false MARK can only make MIDDAY_WATCH relaunch a *dead* tracked child, under the A-1 ceiling taken from that child's own permit, which is ≤ the day's first boot. Severity is low; T1/T7/T10/T11/T18 cover it.
- **R2. "Log advancing" premise.** It rests on the ~100 KB/min figure in a docstring (`:703`). Stage 0 (before RED): measure the maximum inter-write gap of real node logs over [17:10, 01:00) for the last 7 days, using epoch mtimes / sizes per the "measure-catalog-freshness" memory. If any 60 s window shows zero growth on a healthy node, a stall merely delays the MARK by one poll, which is fail-safe and costs no correctness. Record the measured maximum in the PR.
- **R3. CT13.** The new step adds one extra `/proc/locks` read per poll, only until the MARK. The fail direction is "defer", never "mark" and never "dead". There is no increase in flake impact. If CT13 recurs, the PROGRESS row's planned `locks_path` fault-injection test applies equally to T9.
- **R4. Bounded budgets reset on restart.** `relaunch_attempts`, `midday_relaunch_attempts` and the boot-retry counters start from 0 after a restart (true today as well). Worst case: each restart grants up to 3 extra mid-day relaunch attempts. These are never concurrent, and each is capped by the A-1 ceiling. This is out of scope and recorded for a follow-up only if restarts become frequent. Related: `permit_capability_valid` classifies a ceiling lapse as LAPSED rather than EXPIRED_AT_CEILING after a restart, because attempts = 0 (a classification-only page difference).
- **R5. Booting child adopted mid-relaunch (C7).** B1 may page ABSENT before the permit line appears, because `last_midday_relaunch_attempt_at` is None. This is pre-existing behaviour and fails loud. It is not addressed here.
- **R6. FU-17 boot-retry state lost on restart.** `boot_zero_instruments_seen` is re-latched by the byte-0 replay, but the boot-retry attempt counters are not (R4 class).
- **R7. Clock or step regressions.** `now_ns` comes from the same clock as `now`; windowing uses full datetimes (`midday_watch_window_end`), never `.time()`.

---

## §7 Activation

1. Merge into `feat/data-capture-and-risk` after a green full gate (read the EXIT code before any push).
2. Activate immediately ("activate-code-immediately"), **with one concrete exception**: if the merge lands in [16:30Z, 17:10Z), wait for 17:10Z. The new code is safe there by design, but its first live restart should not coincide with the only window where an unproven fault forfeits the day.
3. Run `systemctl --user restart breezy-trade-supervisor`. No daemon-reload; the unit is unchanged.
4. Verify:
   - the node pid and elapsed time are unchanged (`ps -o pid,etimes`);
   - the supervisor log shows `supervisor_started revision=<merge sha>`;
   - in [17:10, 01:00): `permit_watch_adopted_live_node`, then `restart_adopted_ready_node` within ~2 polls, then a MIDDAY_WATCH dispatch line on the next poll;
   - no `TRADE_SUPERVISOR_*` CRITICAL;
   - outside the window: `restart_adopted_ready_node` is absent (expected), and the next 16:40 STOP_PRIOR SIGTERMs the node.
5. Live proof of the goal state: the first restart that falls inside [17:10, 01:00) with a healthy node is the acceptance run. Record its log lines in PROGRESS.

## §8 Rollback

`git revert <sha>`, gate, then restart the supervisor. **The rollback restart is subject to the OLD rule** (the old code is what boots), so it is done in [01:00Z, 16:40Z). If rollback is urgent inside [17:10, 01:00), restarting is still safe for STOP/LAUNCH. It only forfeits that day's MIDDAY_WATCH, which is today's documented behaviour. No state, schema, unit or store migration exists to undo.

## §9 Binding invariants: checklist

- [x] Operator caps, permit mint/TTL, A-1 ceiling, `BREEZY_*_ENABLED`, NO-SEND: untouched (§2.3).
- [x] No test is edited or weakened. Only new tests and one new field in a reset-set expectation are added (T5 adds an assertion and removes none).
- [x] Nautilus is untouched; the node binary and its logs are only read.
- [x] No double launch (§3 invariant, T14). No `launch_done` without proof (§2.1, T1/T3/T7/T10/T11). CT13 fails closed (T9).
- [x] No unit edit, so there is no symlink activation hazard.
