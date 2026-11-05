# SUP-RESTART-ANYTIME: plan r2 (2026-10-03)

Status: DRAFT r2, for peer review. Plan only: no code.
Supersedes: `SUP-RESTART-ANYTIME_plan_r1.md` (unchanged). Review applied: `reviews/SUP-RESTART-ANYTIME-r1-merged.md` (S1–S6 and every LOW); see §R2 Disposition at the end.
Backlog row (docs/core/PROGRESS.md:97): "Proposed: adopting a live, ready node marks `launch_done`/`readiness_observed`, so the supervisor can deploy at any time. Needs a plan and peer review".
Related: CT13-FLAKE (PROGRESS.md:98), SUP-ADOPT-PERMIT, SUP-ADOPT-LOG-GLOB, FU-17, A-1, B1.

Every code citation below was read on 2026-10-03 through codegraph (`projectPath=/home/jon/breezy`) or a direct read of the named lines. Stage 0 (§6) was **run** on 2026-10-03 ~16:20Z; its numbers are in §6 and the scripts and raw output are in the session scratchpad `…/scratchpad/suprestart/` (`gaps.py`, `gaps_signal.py`, `gaps_7d.json`, `gaps_signal_7d.json`, `live_size_samples.txt`).

**What changed from r1, in one paragraph.** The Stage 0 measurement tripped r1's own STOP gate: the node log goes silent for longer than the 60 s B1 poll (20 gaps > 60 s inside [17:10, 01:00) over 7 days, max 198.7 s), and counting only non-error lines is far worse (max 2 432 s), because the steady-state data-flow line is a WARN. So r2 drops r1's "log size grew across one poll" proof and replaces it with a **pinned positive line with an age threshold** (S1+S2): the timestamp of the newest Breezy-owned data-frame line must be within 600 s of the marking poll. r2 also requires the A-1 anchor before marking (S4), adds per-child deferral alerting with delivery (S3), drops the activation hold (S5), and drives the never-double-launch sweep through the real `next_due`/`_do_launch` plus real-flock variants at 16:50 and 16:55 (S6).

---

## §0 Problem and goal state

### Problem (verified in code)

`_run_forever` (`trade_supervisor.py:2638`; seed at `:2668`) seeds `state = initial_scheduler_state(_trading_day(clock()))`. Every latch starts out `False`/`None`, because `DaySchedulerState` is in memory only.

`next_due` (`trade_supervisor_core.py:1123-1128`) dispatches `MIDDAY_WATCH` only when `launch_done and (readiness_observed or boot_zero_instruments_seen)` and `watch_open_at <= now < watch_close_at`. That window runs from 17:10Z on trading day D to 01:00Z on D+1.

So a supervisor restarted at any instant in [17:10Z, 01:00Z) has `launch_done=False` for the rest of that trading day:

- B1 (`_do_permit_watch`, `:2139`) does adopt the live node, and it replays the node's boot log from byte 0 (SUP-ADOPT-PERMIT, `:2063-2075`, `:2012-2043`). Nothing ever sets `launch_done` or `readiness_observed`, though.
- `MIDDAY_WATCH` never becomes due. **The mid-day relaunch duty is lost for the rest of the day**: if the node dies at 21:00, nobody relaunches it.
- `midday_budget_live(launch_done=False, ...)` (`:2094-2101`) also changes B1's DEFERRED/NO_NODE classification.

That is why the memory "supervisor-changes-need-a-supervisor-restart" restricts restarts to [01:00Z, 16:40Z).

The next STOP_PRIOR is not lost. `_do_stop_prior` (`:1150-1151`) falls back to `find_node_pid()` when nothing is tracked, and `tests/unit/test_trade_supervisor.py:2947 test_adoption_at_1640_after_a_0300_start` pins that. Restarts inside the launch window are already handled by `_do_launch`'s [D2] adoption (`:1236-1243`) and by `_do_self_check`'s adoption (`:2333-2339`). The gap is therefore narrow and specific: **no path re-derives `launch_done` + `readiness_observed` for an adopted node after 17:10Z.**

### Goal state (acceptance test for the whole plan)

A `systemctl --user restart breezy-trade-supervisor` at **any** UTC instant:

1. never spawns a second `breezy-trade` while one holds the intent flock (no double launch);
2. never relaunches or signals a live, ready node outside the scheduled STOP_PRIOR;
3. keeps that trading day's STOP_PRIOR, LAUNCH, RELAUNCH_CHECK, SELF_CHECK and MIDDAY_WATCH duties. For a healthy node, MIDDAY_WATCH is restored on the first or second B1 poll after the restart (≤ 2 × 60 s plus work). When proof is missing, the supervisor says so: a per-child WARN after 5 consecutive deferred polls and a delivered CRITICAL after 12 (§2.4);
4. never sets `launch_done`/`readiness_observed` for a node that is not proven ready. **Proven ready** means all of the following hold **on the single marking poll**:
   - the process is alive;
   - it is the verified flock holder, by a fresh `/proc/locks` probe on this poll;
   - its own permit line is latched, and `expires_at_ns > now_ns` for **this poll's** `now_ns`;
   - its strategy-subscribed marker is latched;
   - the day's A-1 anchor `first_boot_permit_expires_at_ns` is latched (S4);
   - its log is stamped inside the current trading day;
   - **fresh post-boot activity:** the newest pinned positive line (§2.1) has a timestamp `>=` the log's spawn stamp and `>= now − 600 s`;
5. fails closed on the CT13 transient: a `None` holder probe means "not proven" on that poll, and it is retried the next poll. It never means "ready" and never means "dead, relaunch". A retry-looping node (one writing only reconnect or error lines), and a node whose permit has lapsed, never mark.

When this ships, the restart-window restriction in the memory and in `deploy/systemd/README.md` is retired. Merged supervisor code is then activated immediately, per the "activate-code-immediately" ruling (§7, no hold).

---

## §1 Null hypothesis (L-1): what already exists and is reused

| Need | Existing mechanism | Verdict |
|---|---|---|
| Node survives a supervisor restart | `KillMode=process` in `deploy/systemd/breezy-trade-supervisor.service`. The node is `start_new_session=True` but stays in the cgroup; only the supervisor main pid is signalled. | **Reuse unchanged.** No unit edit. |
| Identify the live node, fail closed | `_attempt_adoption` (`trade_supervisor.py:1193-1206`): `find_node_pid() == resolve_intent_lock_holder(lock)` over `/proc/locks`. Returns `None` on any mismatch or `None`, which is the CT13 fail-closed behaviour. | **Reuse.** No new adoption path. |
| Recover boot-time evidence after a restart | `_permit_watch_replay_boot_log_on_adoption` (`:2012-2043`): from-byte-0 replay (capped at `_ADOPTION_LOG_REPLAY_MAX_BYTES` = 2 MiB, `:209`) into `latch_log_facts`. That latches `strategy_subscribed_seen`, `permit_issued_seen_expires_at_ns`, `first_boot_permit_expires_at_ns` (A-1) and `boot_zero_instruments_seen`. OSError is retried, then fails loud. `derive_self_check_facts` (core `~:1947-1960`) latches the same set, including the A-1 anchor, on the SELF_CHECK adoption path; `_do_relaunch_check` (`:1326-1334`) on the LAUNCH adoption path. | **Reuse.** |
| Per-poll log drain in the window | B1's incremental drain `latch_log_facts(state, now, ports.read_log_new(node_log))` (`:2088-2092`). Before the mark nothing else is due in [17:10, 01:00), so `_run_forever` calls B1 with `handler_read_log=False` (`:2703-2712`) and this drain sees every new byte. | **Reuse.** The positive-line latch is added to `latch_log_facts` (one projection, no new reader). |
| Readiness predicate | `readiness_observed(holds_intent_lock, permit_issued, strategy_subscribed)` (`core:563-570`), used identically by RELAUNCH_CHECK (`:1355-1361`), the boot-retry hand-off and the midday recheck. | **Reuse.** The new rule calls it, then adds the extra guards from goal 4. |
| Latch writers | `record_readiness_observed` (`core:1227`), `mark_phase_fired(..., Phase.LAUNCH, ...)` (`core:1151-1164`). | **Reuse.** Both are composed; no parallel writer. |
| Per-child reset | `record_child_adopted` (`core:1167-1196`). | **Reuse.** Extended by four fields (§2.1). |
| Log file → spawn time | `node_log_path` stamps `breezy-trade-YYYYMMDDTHHMMSSZ.log` (`:787-789`). `_NODE_LOG_NAME_RE` (`:798`). `find_adopted_node_log` (`:814`). | **Reuse** the stamp as current-trading-day evidence. |
| Positive data-frame line | `PolymarketUSDataClient._note_depth_truncation` (`adapters/polymarket_us/data.py:1824`; WARN at `:1873-1880`, rate-limited by `should_warn_at_count`, `:555`, every `MISSING_ROUTING_KEY_WARN_EVERY` = 100, `:181`) and `ForecastQuantileLadderStrategy`'s `SHADOW_DECISION` INFO (`strategy/forecast_quantile_ladder/strategy.py:581`). Both are Breezy-owned and emitted only on the market-data path. | **Reuse** as a closed, pinned marker set (§2.1). No new emitter. |
| Alert path with observable delivery | `_send_permit_alert` (`:958-974`): same sink as every supervisor alert (`resolve_alert_sink` → `TeeAlertSink`, logging + webhook), but the send result is returned so a failed send is retried next poll and never latched. `AlertDetail` is the closed detail enum (`core:257`). | **Reuse** for S3; two new `AlertDetail` members. |
| Containment | B1's `[D8]` try (`:2160-2222`) plus `_dispatch_permit_watch`'s outer `[A2]` try (`:2542-2559`). | **Reuse.** The new step runs inside `_do_permit_watch`'s try. |
| systemd `ExecReload=` / hot reload | A Python process cannot safely re-import changed modules in place, and nothing in the repo supports it. | **Rejected.** It does not remove the restart. |
| systemd `FileDescriptorStoreMax=` (memfd state carry-over) | Across a **deploy** it means unpickling old-schema state into new code, and it re-trusts latches (e.g. readiness of a node that died during the restart gap) without re-proving them. | **Rejected.** Re-deriving from live evidence is self-validating; carried-over state is not. |
| Persisting `DaySchedulerState` to the exec store (precedent `SELF_CHECK_ESCALATION_STORE_KEY`) | Same stale-latch and schema-drift objections, plus a new writer to the exec store during live trading. | **Rejected** for this item. |
| Nautilus | The supervisor is an external process manager; Nautilus has no process-supervision or adoption facility to extend. Nautilus log lines are only **read** (their timestamp prefix); nothing in the node changes. Nautilus emits no periodic heartbeat line in the node log (none observed across 6.2 M lines in Stage 0). | N/A. Nautilus stays immutable. |

**Conclusion.** The missing pieces are one pure decision, one positive-line projection added to the existing `latch_log_facts`, one state recorder, and a deferral-alert latch set. They are wired at one site (`_do_permit_watch`'s in-window branch), right after the existing adoption, replay and drain. There is no new adoption logic, no new reader, no unit change and no persistence.

---

## §2 Design

### 2.1 Pure core (in `trade_supervisor_core.py`, stdlib-only)

**Pinned positive line (S1).** The liveness signal is named from code, not inferred from byte growth:

```
#: [SUP-RESTART-ANYTIME] Breezy-owned lines emitted ONLY on the market-data
#: path of a running node. Pinned against their emitters (contract test T19).
LIVENESS_POSITIVE_MARKERS: Final[tuple[str, ...]] = (
    "book level(s) discarded so far",   # data.py:1874-1880 _note_depth_truncation (Depth10 frame arrived)
    "SHADOW_DECISION ",                 # forecast_quantile_ladder/strategy.py:581 (decision on a live frame)
)
LIVENESS_MAX_AGE_NS: Final[int] = 600 * 1_000_000_000   # §6 Stage 0: 3x the measured 198.7 s max gap

def latest_liveness_line_ns(log_text: str) -> int | None
    # rfind each marker; for the line containing the LAST occurrence, strip ANSI
    # and parse the Nautilus prefix "YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ" -> epoch ns.
    # Max over markers. None if no marker, or if the prefix does not parse (fail closed).
```

Why these two lines and not "any non-error line" or "any growth": see §6 Stage 0. In short, the depth-truncation line is a **WARN**, yet it is the node's dominant steady-state data-flow line (pre-FQ days), so a non-error filter discards the real signal (max non-error gap 2 432 s in the window). Raw growth also counts reconnect WARNs and error lines from a retry-looping node, which is exactly what S1 forbids. Both pinned lines are produced only when a venue frame was actually received and processed. A node in a websocket reconnect loop (`websocket.py:958-962`) or an exception loop writes neither.

`latch_log_facts` (`core:1726-1772`) gains one projection, additive and order-independent:

```
ns = latest_liveness_line_ns(log_text)
if ns is not None:
    state = record_liveness_line_seen(state, now_utc, ns)   # keeps max(prev, ns)
```

Because B1's replay and B1's incremental drain both go through `latch_log_facts`, the latch sees the boot-log replay **and** every subsequent delta. A replayed line from hours ago is harmless: freshness is judged by the line's own timestamp, never by when it was read. The other handlers' inline readers (`_do_relaunch_check`, `_do_self_check`, `_do_midday_watch`) are **not** changed. Before the mark none of them runs in [17:10, 01:00), and after it the latch is no longer consulted (FU-1's byte-identical constraint is respected).

**Verdict.**

```
class ReadyAdoptionVerdict(str, Enum):
    MARK = "mark"
    # terminal: not a deferral; owned/paged elsewhere; resets the deferral counter
    NOT_IN_WINDOW = "not_in_window"
    ALREADY_READY = "already_ready"
    NO_CHILD = "no_child"                        # B1 pages NO_NODE
    PERMIT_EXPIRED = "permit_expired"            # B1 pages LAPSED / EXPIRED_AT_CEILING
    LOG_NOT_CURRENT_DAY = "log_not_current_day"  # D-1 node; STOP_PRIOR already paged CRITICAL
    # non-terminal deferrals: counted toward §2.4 alerting
    HOLDER_UNPROVEN = "holder_unproven"          # CT13: None or mismatch on THIS poll
    PERMIT_ABSENT = "permit_absent"
    NOT_SUBSCRIBED = "not_subscribed"
    ANCHOR_UNKNOWN = "anchor_unknown"            # S4
    LOG_UNKNOWN = "log_unknown"                  # node_log None or stamp unparseable
    NO_FRESH_ACTIVITY = "no_fresh_activity"      # S1/S2
    IO_ERROR = "io_error"                        # S3: OSError inside the step

def decide_ready_adoption(
    *, state: DaySchedulerState, now: dt.datetime, now_ns: int,
    child_alive: bool, holder_is_tracked: bool,
    log_spawned_at: dt.datetime | None,
) -> ReadyAdoptionVerdict
```

The checks run in this order; the first failing check wins, so each verdict is testable on its own.

1. `NOT_IN_WINDOW` unless `permit_watch_window(state.day)` contains `now`, i.e. [D 17:10Z, D+1 01:00Z). This is the same boundary as MIDDAY_WATCH/B1 (D1: no third boundary).
2. `ALREADY_READY` when `state.readiness_observed`. The key is readiness, **not** `launch_done` (case B6: `_do_launch` can set `launch_done=True` on a lock-held refusal without readiness, and that day must still be recoverable).
3. `NO_CHILD` when not `child_alive`.
4. `HOLDER_UNPROVEN` when not `holder_is_tracked`. The caller computes it from a **fresh** `resolve_intent_lock_holder` call on this poll, as `holder is not None and holder == tracked_pid`.
5. `PERMIT_ABSENT` when `state.permit_issued_seen_expires_at_ns is None`; `PERMIT_EXPIRED` when it is `<= now_ns`. `now_ns` is **this poll's** clock reading, the same one the MARK is taken on (S1 "re-check on the same poll").
6. `NOT_SUBSCRIBED` when not `state.strategy_subscribed_seen`.
7. `ANCHOR_UNKNOWN` when `state.first_boot_permit_expires_at_ns is None` (S4). `_do_midday_watch` refuses every relaunch without the anchor (A-1), so marking without it would restore a duty that cannot act.
8. `LOG_UNKNOWN` when `log_spawned_at is None`; `LOG_NOT_CURRENT_DAY` when `log_spawned_at < _at(state.day, STOP_PRIOR_UTC)`.
9. `NO_FRESH_ACTIVITY` when `state.liveness_line_last_ns is None`, or `< log_spawned_at` in ns (not post-boot), or `now_ns - it > LIVENESS_MAX_AGE_NS`.
10. Otherwise `MARK`.

Checks 4, 5 (absence) and 6 are exactly `readiness_observed(...)`'s three conjuncts. The implementation calls `readiness_observed(...)` and maps a `False` to the specific reason (one shared predicate, no copy).

```
def is_deferral(v: ReadyAdoptionVerdict) -> bool          # the seven non-terminal members
def record_ready_adoption(state, now_utc) -> DaySchedulerState
    # = record_readiness_observed(mark_phase_fired(state, Phase.LAUNCH, now_utc), now_utc)
    #   and resets ready_adoption_deferral_polls to 0
def record_liveness_line_seen(state, now_utc, ns: int) -> DaySchedulerState   # max-wins, _for_day
def record_ready_adoption_deferral(state, now_utc) -> DaySchedulerState       # +1
def reset_ready_adoption_deferral(state, now_utc) -> DaySchedulerState        # =0 (terminal verdict)
def record_ready_adoption_alert_sent(state, now_utc, *, critical: bool) -> DaySchedulerState
def decide_ready_adoption_alert(state) -> AlertSpec | None                    # §2.4
def node_log_spawned_at(name: str) -> dt.datetime | None
    # group(1) of _NODE_LOG_NAME_RE parsed as %Y%m%dT%H%M%SZ (UTC); None on any other shape
```

**`_NODE_LOG_NAME_RE` (LOW, choice pinned).** It moves into core as `re.compile(r"^breezy-trade-(\d{8}T\d{6}Z)\.log$")`: the r1 literal plus **one capture group around the stamp, nothing else**. A capture group cannot change what matches. The shell re-imports it under the same name, so `find_adopted_node_log` (`:834`) and existing tests keep working. There is one pattern and no derived second pattern; r1's "maybe a second pattern" hedge is withdrawn. T6b proves identical match behaviour against the frozen old literal.

**New `DaySchedulerState` fields**, all defaulted. All are cleared by `record_child_adopted` (a new child) and by `_for_day` (rollover):

```
liveness_line_last_ns: int | None = None        # newest pinned positive line seen for this child
ready_adoption_deferral_polls: int = 0          # consecutive non-terminal deferrals
ready_adoption_warn_sent: bool = False          # per-child, one-shot
ready_adoption_critical_sent: bool = False      # per-child, one-shot
```

`record_child_adopted` adds those four to its `replace(...)`. That is purely additive: every existing field is cleared exactly as before. r1's `ready_adoption_log_size_probe` field and `record_ready_adoption_log_probe` are **dropped**.

**Why the log stamp proves the current trading day.** Permit-unexpired alone does not: a node hand-launched at D 10:00 has an unexpired 10 h permit at D 17:10, yet it belongs to trading day D−1. The stamp is written by `node_log_path` at spawn, and hand relaunches mirror `spawn()` (memory "hand-relaunch-mechanics"). `find_adopted_node_log` already binds the file to the pid (mtime ≥ `/proc/<pid>` ctime). An unknown log fails closed (`LOG_UNKNOWN`, counted).

### 2.2 Shell step (in `trade_supervisor.py`)

```
def _ready_adoption_step(
    *, ports, state, now, now_ns, tracked_pid, node_log, store_path,
) -> DaySchedulerState
```

- It returns at once (no port calls) when `state.readiness_observed`, when `now` is outside the window, or when `tracked_pid is None`. The `tracked_pid is None` case is B1's NO_NODE or a failed adoption, which B1 already handles and pages.
- Otherwise, inside `try: … except OSError as exc:`, it reads `child_alive = ports.process_alive(tracked_pid)` and a **fresh** `holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))`. It computes `log_spawned_at = node_log_spawned_at(node_log.name) if node_log else None` and calls `decide_ready_adoption`. An `OSError` yields `IO_ERROR`, plus `log_decision("ready_adoption_io_error", error_type=type(exc).__name__)` on **every** occurrence; it is logged and counted (S3). Any other exception propagates to B1's `[D8]` containment, which gives WATCH_FAILED and never a mark (unchanged, T16).
- `MARK`: apply `record_ready_adoption` and log `log_decision("restart_adopted_ready_node", pid=tracked_pid, liveness_age_s=…)` at INFO. This is the activation evidence line.
- Terminal verdict: `reset_ready_adoption_deferral`.
- Deferral: `record_ready_adoption_deferral`; `log_decision("ready_adoption_deferred", reason=verdict.value, polls=n)` on the first deferral per child and on every alert threshold crossing (bounded log volume). Then §2.4.

There is **no new port**. r1's `log_size` port is dropped, so every `_make_ports(...)` fixture is untouched.

**Wiring (one site).** In `_do_permit_watch`'s in-window branch (`:2189-2200`), the current `return _permit_watch_adopt_and_evaluate(...)` becomes:

```
tracked_pid, node_log, state = _permit_watch_adopt_and_evaluate(...)
state = _ready_adoption_step(ports=..., state=state, now=now, now_ns=now_ns,
                             tracked_pid=tracked_pid, node_log=node_log, store_path=store_path)
return tracked_pid, node_log, state
```

It is not run in the `now >= window_close` branch (closed window, `NOT_IN_WINDOW` anyway). The step runs after B1's own drain on the same poll, so the liveness latch it reads is this poll's.

**B1 poll cadence (S2, stated).** B1 runs once per `_run_forever` iteration (`:2703` in the `Phase.NONE` branch, `:2760` after a dispatch). Between iterations the loop sleeps `phase_poll_interval_s(phase)` (`core:1892-1895`): `_SCHEDULE_POLL_INTERVAL_S` = 60 s (`core:1866`) for `NONE` and every phase except RELAUNCH_CHECK (15 s, `core:1874`; never due in this window). In [17:10, 01:00) before the mark the phase is `NONE`, so **the cadence is one poll per 60 s plus iteration work.**

**Effect.** On the iteration after `MARK`, `next_due` returns `MIDDAY_WATCH`. The existing handler then owns the node: mid-day relaunch with the A-1 ceiling, the readiness recheck and alerts. B1's `midday_budget_live` now sees `launch_done=readiness_observed=True`, which matches a supervisor that never restarted.

### 2.3 What is deliberately NOT changed

- `next_due`, `decide_launch_action`, `_do_launch`, `_do_stop_prior`, `_do_self_check`, `_do_midday_watch`, `_do_relaunch_check`, `derive_self_check_facts` and `decide_relaunch`. All existing restart tests (`test_trade_supervisor.py:2100-2150`, `:2947`, `:3939`, `:3958`, `:5428`, `:6244-6470`, `:6777-6820`) stay byte-identical and green.
- `deploy/systemd/breezy-trade-supervisor.service`. No edit, so no daemon-reload is needed; the symlink hazard does not apply.
- Permit minting, operator caps, `BREEZY_*_ENABLED`, the NO-SEND firewall and the A-1 ceiling env are all unchanged. **The step has no spawn, signal or store-write capability**: it calls only `process_alive`, `resolve_intent_lock_holder` and the alert sink.
- The node and its log emitters. Both pinned lines already exist; none is added or reworded.

### 2.4 Deferral alerting (S3)

`decide_ready_adoption_alert(state)` (pure) is called by the step after every deferral:

| Condition | Alert | Latch |
|---|---|---|
| `deferral_polls >= READY_ADOPTION_WARN_POLLS` (5) and not `warn_sent` | `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED`, severity **WARN**, detail `AlertDetail.READY_ADOPTION_DEFERRED` | `warn_sent` |
| `deferral_polls >= READY_ADOPTION_CRITICAL_POLLS` (12) and not `critical_sent` | same event, severity **CRITICAL**, detail `AlertDetail.READY_ADOPTION_UNPROVEN` | `critical_sent` |

- **Delivery.** Sent with `_send_permit_alert` (`:958-974`), the observable variant of the supervisor's shared sink. The latch is set **only if the send returns `True`**; a failed send is retried on the next poll (the same discipline as B1 [A2]).
- **Dedupe.** At most one WARN and one CRITICAL per child. Both latches clear on `record_child_adopted` (a new child gets a fresh budget) and on rollover. The counter resets on MARK and on any terminal verdict, so it means "consecutive".
- **Thresholds.** 5 polls ≈ 5 min is above the measured 7-day in-window max data gap (198.7 s), so a healthy node never WARNs. 12 polls ≈ 12 min is above `LIVENESS_MAX_AGE` (600 s), so the CRITICAL fires only after one full freshness horizon has passed without proof. Both are named constants in core.
- **What is counted.** CT13 `None`/mismatch (`HOLDER_UNPROVEN`), `PERMIT_ABSENT`, `NOT_SUBSCRIBED`, `ANCHOR_UNKNOWN`, `LOG_UNKNOWN`, `NO_FRESH_ACTIVITY` and `IO_ERROR`, the last being a persistent OSError, logged on each occurrence.
- `AlertDetail` gains exactly these two members. Any test that pins the enum's member set gains two entries; none is removed.

---

## §3 Restart instants across the day: correct behaviour

D = trading day (`_trading_day`; it opens at D 16:40Z). "Old" = the supervisor before restart; "new" = after.

| # | Restart instant (UTC) | Node state at restart | Correct behaviour after this plan | Path |
|---|---|---|---|---|
| A1 | [01:00, 16:30) | D−1 node live and ready | Nothing is due; B1 and MIDDAY windows are closed. No mark (`NOT_IN_WINDOW`). At 16:40 STOP_PRIOR finds the node by `find_node_pid` and SIGTERMs it. | existing (`:2947`) |
| A2 | [01:00, 16:30) | down | Nothing; LAUNCH at 16:50 as usual. | existing |
| B1 | [16:30, 16:40) | D−1 node live | Same as A1. | existing |
| B2 | [16:40, 16:50), STOP not yet done | D−1 node live | Fresh state → STOP_PRIOR due immediately → SIGTERM via the TOCTOU-rechecked terminate, before the 16:45 engine pass. If the supervisor was *down* across 16:45, the engine pass sees a node and defers (fail-closed, AUT-7 R4 row). | existing |
| B3 | [16:40, 16:50), STOP already done | down | STOP_PRIOR re-run → `stop_prior_noop`. No signal; no mark (window closed). | existing |
| B4 | [16:40, 16:50), STOP refused by old | D−1 node live, holder ≠ discovered | New re-runs STOP → same refusal and the same CRITICAL (re-verified: `_do_stop_prior` `:1159-1166`, `alert(... "TRADE_SUPERVISOR_STOP_PRIOR_REFUSED", "CRITICAL", AlertDetail.ADOPTION_REFUSED)` through `ports.alert_sink`). A duplicate page is the accepted direction. Never a second LAUNCH while the flock is held. | existing |
| B5 | [16:50, 17:00), old has launched D node | D node live | LAUNCH due → `_do_launch`: lock held → `REFUSE_LOCK_HELD` → `_attempt_adoption` → adopt, **no spawn**, `launch_done=True`. RELAUNCH_CHECK reads the full log (fresh reader) and latches readiness and the A-1 anchor (`:1326-1361`). Pinned by real-flock T14b at 16:50 and 16:55. | existing (`:3939`) |
| B6 | [16:50, 17:00), CT13 on the adoption probe | D node live | `launch_refused_lock_held` WARN, LAUNCH fired, nothing tracked, **no spawn**. SELF_CHECK at 17:05 re-attempts adoption (anchor latched by `derive_self_check_facts`). From 17:10 the step marks once proven (C1 path). **Today this day loses MIDDAY_WATCH; this plan closes that second gap.** | existing + **new** |
| B7 | [16:50, 17:00), child died | down, flock free | LAUNCH spawns once (lock free, no pid). Not a double launch. Residual: boot budget restarts at 0 (§6 R4). | existing |
| B8 | [16:50, 17:00), old crashed before spawning | down | LAUNCH spawns once. | existing |
| C1 | [17:00, 17:05) | D node live | SELF_CHECK at 17:05 adopts and reads the log, latching permit, subscribed and anchor. At 17:10 B1 runs with the tracked pid alive (no replay); its drain (17:05→17:10 delta) latches the newest pinned line; the step **marks on the first in-window poll** if that line is ≤ 600 s old. | existing + **new** |
| C2 | [17:05, 17:10) | D node live | Same as C1. | existing + **new** |
| C3 | [17:10, 01:00) | D node live and ready | Poll 1: B1 adopts plus byte-0 replay (permit, subscribed, anchor and the newest replayed pinned line latched; the replay is capped at 2 MiB, so on a large log the pinned line comes from the next delta). The step marks if a pinned line is fresh, otherwise `NO_FRESH_ACTIVITY` (counted). Poll 2: B1's delta has fresh pinned lines → `MARK`. Next iteration: MIDDAY_WATCH. No spawn, no signal. | **new** |
| C4 | [17:10, 01:00), CT13 transient | D node live | B1's adoption probe `None` → nothing adopted (existing fail-closed, retried). If adoption succeeded but the step's fresh probe is `None` → `HOLDER_UNPROVEN`, counted, retried. Persistent `None` → WARN at 5, CRITICAL at 12 polls, **never** a mark, **never** a spawn. | existing + **new** |
| C5 | [17:10, 01:00) | permit expired (e.g. a midday child at the A-1 ceiling) | `PERMIT_EXPIRED` (terminal) → never marked. B1 pages LAPSED/EXPIRED_AT_CEILING as today. | **new** (guard) |
| C6 | [17:10, 01:00) | previous-day node (STOP refused), unexpired permit | `LOG_NOT_CURRENT_DAY` (terminal) → never marked; STOP_PRIOR already paged CRITICAL. | **new** (guard) |
| C7 | [17:10, 01:00) | node booting (old was mid-midday-relaunch) | `PERMIT_ABSENT`/`NOT_SUBSCRIBED` deferrals until latched by B1's drain, then a mark once a fresh pinned line arrives. A boot that never completes ends in WARN/CRITICAL. Residual: B1 may also page ABSENT (§6 R5). | existing + **new** |
| C8 | [17:10, 01:00) | down | Nothing adopted → the step returns early. **No mark, no spawn.** B1 pages NO_NODE as today. | existing |
| C9 | [17:10, 01:00), old had already marked | D node live and ready | Identical to C3; nothing inherited. | **new** |
| C10 | [17:10, 01:00) | live but retry-looping (reconnect WARNs, no frames) | `NO_FRESH_ACTIVITY` forever → never marked → WARN, then CRITICAL. | **new** (S1) |
| C11 | [17:10, 01:00) | live, healthy, but a quiet book and no FQ family (neither pinned line emitted for > 600 s) | `NO_FRESH_ACTIVITY` → no mark → WARN/CRITICAL says MIDDAY is not restored. Fail-closed; it equals today's behaviour plus a page. Not observed in Stage 0 (§6 R2). | **new** |
| D1 | [00:00, 01:00) (UTC date rolled, trading day D) | D node live and ready | `_trading_day` → D; window still open → same as C3. Stage 0: max pinned-line gap in this hour 121.4 s. | **new** |

**Never double-launch (invariant).** The new step has no spawn port. LAUNCH is due only in [16:50, 17:00) and spawns only on `lock_free and node_pid is None and not open_intent` (`:1223-1234`). MIDDAY_WATCH spawns only for a tracked child that is dead. Marking makes MIDDAY_WATCH due only for a node proven alive and holding the flock on that poll. T14 proves this through the **real** `next_due` and `_do_launch` (S6).

**The 16:45 engine pass and the 16:50 LAUNCH.** The step cannot act in [16:40, 17:10) (check 1 and the shell's early return), so STOP-before-16:45, the engine `engine.lock` pass and the 16:50 sequence are unchanged.

---

## §4 Tests: RED → GREEN

Placement: pure tests in `tests/unit/test_trade_supervisor_core.py`; shell tests in `tests/unit/test_trade_supervisor.py` (reusing `_make_ports`, `_utc`, `_DAY`, `_b1_common_kwargs`, `_RecordingAlertSink`); real-process tests in a new `tests/unit/test_ct14_supervisor_restart_anytime.py` modelled on `test_ct02_supervisor_adopt_real_child.py`. Every test is observed **failing first**. An ImportError counts as RED only for T1–T7 and T19; T8–T18 must fail on an assertion against current behaviour. The RED→GREEN output is kept as the change artifact.

**Pure (core)**
- T1 `test_decide_ready_adoption_marks_only_when_every_proof_holds`. Table-driven: start from an all-true baseline, flip each input in turn, and assert the specific verdict for all 13 values. This includes `ANCHOR_UNKNOWN` (permit latched, anchor `None`) and `PERMIT_EXPIRED` where the latched expiry equals `now_ns` exactly, plus `now_ns` one ns past it.
- T2 `test_decide_ready_adoption_window_boundaries`. 16:45, 17:05 and 17:09:59 → NOT_IN_WINDOW; 17:10:00 → evaluated; D+1 00:59:59 → evaluated; D+1 01:00:00 → NOT_IN_WINDOW.
- T3 `test_ready_adoption_keys_on_readiness_not_launch_done`. `launch_done=True, readiness_observed=False` → can MARK (B6). `readiness_observed=True` → ALREADY_READY.
- T4 `test_record_ready_adoption_sets_both_latches_and_nothing_else`. It sets `launch_done`, `readiness_observed` and resets the deferral counter. Everything else is untouched: relaunch counters, `first_boot_permit_expires_at_ns`, `self_check_done` and every alert latch. Idempotent and `_for_day`-scoped.
- T5 `test_record_child_adopted_clears_ready_adoption_fields`, plus the rollover reset. It extends the existing reset-set expectation by the four new fields; no assertion is removed.
- T6 `test_node_log_spawned_at_parses_node_stamp_only`. Parses node stamps; `None` for `breezy-trade-supervisor.log` and its `-stdout-`/`.launch-` variants, and for an impossible date.
- T6b `test_node_log_name_re_matches_identically_to_frozen_r1_literal` (LOW). A corpus of about 20 names, including every production name shape seen in `~/.local/share/breezy/logs`, the supervisor variants, a trailing-newline name, a `.log.1` name and a wrong-digit-count name. `bool(new.match(n)) == bool(re.compile(r"^breezy-trade-\d{8}T\d{6}Z\.log$").match(n))` for every name. It also pins `new.pattern` to the exact r2 literal.
- T7 `test_permit_unexpired_alone_does_not_prove_current_day`. Stamp D 10:00, permit expiring D 20:00, now D 17:30 → LOG_NOT_CURRENT_DAY.
- T7b `test_latest_liveness_line_ns`. It parses the ANSI-wrapped Nautilus prefix (fixture lines copied verbatim from a production log); returns the max over both markers; `None` for reconnect/ERROR-only text, for a marker on a line with an unparseable prefix, and for `""`.
- T7c `test_latch_log_facts_records_liveness_max_wins`. A later delta with an older line never lowers the latch; existing `latch_log_facts` outputs are unchanged for text with no marker.
- T7d `test_decide_ready_adoption_alert_thresholds_and_dedupe`. 4 → None; 5 → WARN; 6..11 → None; 12 → CRITICAL; 13+ → None; after `record_child_adopted` → WARN again at 5.

**Shell (fake ports and a fake clock driving `_run_forever` with `max_iterations`)**
- T8 `test_restart_at_2000_with_ready_node_restores_midday_watch_without_spawn`. Iteration 1 adopts plus replay; the log fixture has a pinned line stamped 20:00:30 and now is 20:01 → MARK on iteration 1 (assert `restart_adopted_ready_node`). Next iteration dispatches MIDDAY_WATCH. `spawn` and `terminate_after_recheck` are never called. **RED today.**
- T9 `test_ct13_transient_holder_none_defers_mark_and_never_spawns`. Holder sequence `[pid, None, pid]` (the adoption probe succeeds, the marking probe is `None`) → no mark on that poll, mark on the next. Variant: persistent `None` → never marks, spawns 0, exactly one WARN at poll 5 and one CRITICAL at poll 12, through `_RecordingAlertSink`.
- T10 `test_expired_permit_node_is_never_marked`. The B1 alert set is unchanged versus the same run with the step disabled. Variant: the permit is unexpired at poll N−1 and expired at poll N, with a fresh pinned line arriving at N → no mark (same-poll re-check).
- T11 `test_retry_looping_node_is_never_marked` (S1). The log grows by 50 KB/poll of reconnect WARN and ERROR lines with no pinned marker → never marked → WARN and CRITICAL.
- T11b `test_stale_liveness_line_is_never_marked`. The newest pinned line is 601 s old → `NO_FRESH_ACTIVITY`; at 599 s → MARK.
- T11c `test_replayed_old_liveness_line_does_not_mark`. The replay contains only pinned lines stamped hours ago and the delta has none → no mark.
- T12 `test_node_down_at_restart_is_never_marked_and_never_spawned` (C8).
- T13 `test_1655_lock_held_adoption_flake_recovered_at_1710` (B6). `_do_launch` adoption fails → no spawn → SELF_CHECK at 17:05 adopts → at 17:10 the step marks → MIDDAY_WATCH. **RED today.**
- T14 `test_restart_sweep_never_double_launches_real_scheduler` (S6). Restart at every 5 min across 24 h (288 fresh `_run_forever` runs, each 30 min of fake clock). It uses the **real** `next_due`, `_do_launch`, `_do_stop_prior`, `_do_relaunch_check`, `_do_self_check`, `_do_permit_watch` and `_do_midday_watch`; only the ports are fakes. The fakes come from a single world model: one process table, one flock owner, a log per child with pinned lines, and `spawn` adds a process and takes the flock. The invariants are asserted from the port call log, not from the model: concurrent live `breezy-trade` ≤ 1 at every port call; `spawn` ≤ 1 per trading day; `terminate_after_recheck` only in [16:40, 16:50); `restart_adopted_ready_node` only in [17:10, 01:00); MIDDAY_WATCH dispatched within 2 iterations of every in-window restart.
- T15 `test_marked_adopted_child_death_relaunches_with_adopted_ceiling`, three variants (S4), each running through MIDDAY_WATCH. After the mark the child dies with a transient cause → one spawn with `BREEZY_PERMIT_EXPIRY_CEILING_NS` equal to the latched anchor.
  - (a) adopted by B1 at 20:00 (replay latches the anchor);
  - (b) adopted by `_do_launch` at a 16:55 restart, with RELAUNCH_CHECK latching the anchor;
  - (c) adopted by SELF_CHECK at a 17:06 restart, with `derive_self_check_facts` latching the anchor.

  A fourth variant, (d), builds a state with the permit latched and the anchor `None` → `ANCHOR_UNKNOWN`, no mark, counted, and no spawn ever.
- T16 `test_ready_adoption_step_exceptions`. `resolve_intent_lock_holder` raises `OSError` on every poll → `IO_ERROR`, a `ready_adoption_io_error` line per poll, counted → WARN and CRITICAL, no mark. It raises `RuntimeError` → B1 `[D8]` WATCH_FAILED, no mark, and the loop continues.
- T16b `test_ready_adoption_alert_send_failure_is_retried_not_latched`. The sink raises on the first CRITICAL send → no latch → resent next poll → latched once.

**Real process (CT-14, real `/proc/locks`)**
- T17 `test_real_flock_holder_with_fresh_liveness_line_is_marked_after_restart`. A real child takes the intent flock and writes a correctly stamped log: permit line, subscribed line, then a depth-truncation line in the real Nautilus prefix format every 0.2 s. Drive `_run_forever` at fake 20:00 (fake clock aligned to the child's wall clock) with the real `resolve_lock_holder_pid` and `find_adopted_node_log`; `find_node_pid` is injected as in ct02. Assert the mark, zero spawns, and an unchanged child pid.
- T14b `test_real_flock_restart_at_1650_and_1655_adopts_without_spawn` (S6). The same real child; fresh `_run_forever` at fake 16:50:00 and, separately, 16:55:00. Assert `launch_adopted_live_node`, `spawn` called 0 times, the child pid unchanged and still the flock holder, and (at 16:55) readiness latched by RELAUNCH_CHECK.
- T18 `test_real_live_pid_not_holding_flock_is_never_marked`, mirroring ct02 `:242`.

**Contract pin**
- T19 `test_liveness_markers_are_pinned_to_real_emitters`. In the ct08 style: each `LIVENESS_POSITIVE_MARKERS` entry is a substring of its emitter's source text. For `data.py` `_note_depth_truncation`, the f-string literal; for `forecast_quantile_ladder/strategy.py`, the `SHADOW_DECISION` literal. A reworded emitter therefore fails this test rather than silently disabling the mark.

**Unchanged and must stay green (cited, not edited):** `test_trade_supervisor.py:2100-2150`, `:2947`, `:3939`, `:3958`, `:5428`, `:6244-6470`, `:6777`, `:6803`, `test_ct02_*`, `test_ct13_*`, `test_ct08_*` (gains T19 only if it is placed there; otherwise untouched), `test_trade_supervisor_unit_directives.py` (KillMode pin).

**Gate (all required, read the EXIT code):**
- `scripts/ci/run_tests_no_egress.sh`, full gate, through the project interpreter; never `uv run`/`uv sync`.
- Focused: `tests/unit/test_trade_supervisor_core.py tests/unit/test_trade_supervisor.py tests/unit/test_ct14_supervisor_restart_anytime.py tests/unit/test_ct02_supervisor_adopt_real_child.py tests/unit/test_ct13_supervisor_crash_readopt.py tests/unit/test_ct08_supervisor_contract_surface.py`.
- `ruff`, `mypy`, and `lint-imports` from the tree root, demanding the "N kept, 0 broken" line. Core stays stdlib-only. The markers are string literals in core; core never imports the adapter or the strategy, and T19 reads their source as text.

---

## §5 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/runtime/trade_supervisor_core.py` | Add `LIVENESS_POSITIVE_MARKERS`, `LIVENESS_MAX_AGE_NS`, `READY_ADOPTION_WARN_POLLS`/`_CRITICAL_POLLS`, `latest_liveness_line_ns`, `ReadyAdoptionVerdict`, `is_deferral`, `decide_ready_adoption`, `decide_ready_adoption_alert`, the five recorders and `node_log_spawned_at`. Move `_NODE_LOG_NAME_RE` here with one capture group (pinned literal, §2.1). Add the four `DaySchedulerState` fields; extend `record_child_adopted`'s `replace`; add one additive projection to `latch_log_facts`. Add 2 `AlertDetail` members. | ~150 lines |
| `src/breezy/runtime/trade_supervisor.py` | Re-import `_NODE_LOG_NAME_RE`. Add `_ready_adoption_step`. Make the 3-line wiring change in `_do_permit_watch`'s in-window branch. **No new port.** | ~60 lines |
| `tests/unit/test_trade_supervisor_core.py` | T1–T7d | new tests only |
| `tests/unit/test_trade_supervisor.py` | T8–T16b | new tests only |
| `tests/unit/test_ct14_supervisor_restart_anytime.py` | T14b, T17, T18 (new file) | new |
| `tests/unit/test_ct08_supervisor_contract_surface.py` | T19 (new test; existing tests untouched) | new test only |
| `deploy/systemd/README.md` | Replace the "restart only 01:00–16:40Z" guidance with: restart any time; verify `restart_adopted_ready_node` (in window), or `stop_prior_*`/`launch_adopted_live_node` (launch window); a `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED` page means MIDDAY_WATCH is not restored. | doc |
| `docs/core/PROGRESS.md` | Close the row with the merge sha. Annotate CT13-FLAKE: "ready-adoption defers on a None holder; covered by T9". | doc |
| Memory `supervisor-changes-need-a-supervisor-restart.md` | Coordinator updates it after verified activation; not part of the code change. | — |

The unit file is **not** edited (its `KillMode=process` comment is incomplete but still true; a comment-only edit is deferred so this change never needs a daemon-reload).

---

## §6 Stage 0 measurement (run 2026-10-03) and risks

### Stage 0: node-log activity (S2 STOP gate)

**Method.** `gaps.py` and `gaps_signal.py` stream the node logs line by line (bounded memory: histogram + top-8 heap per series; 2 GB `ulimit -v`; niced). They cover 11 node logs spawned 09-26 → 10-02 (7 trading days; 2 of the files are 0.88 GB and 1.16 GB). Timestamps come from the line prefix, both the Nautilus `…T…nnnnnnnnnZ` form and the Python `YYYY-MM-DD HH:MM:SS,mmm` boot form. Gaps never span files, and window series reset outside their window. There was also a 180 s live `st_size` sample of the current node log at 16:16Z.

**Results: inter-line gaps.**

| Series | n gaps | > 60 s | > 120 s | > 180 s | max |
|---|---|---|---|---|---|
| all lines, whole day | 6 243 827 | 148 | 19 | 10 | 508.1 s (10-01 12:15Z, outside window) |
| all lines, [17:10, 01:00) | 1 612 920 | 17 | 3 | 2 (≤ 300 s) | 198.7 s (09-26 19:56Z) |
| all lines, [00:00, 01:00) | 349 770 | 3 | 1 | 0 | 121.4 s (09-30 00:04Z) |
| **non-error** lines, [17:10, 01:00) | 1 567 629 | 210 | 185 | 173 | **2 431.8 s** |
| **non-error** lines, [00:00, 01:00) | 345 911 | 11 | 10 | 10 | 2 431.8 s |
| **pinned union** (depth-truncation ∪ SHADOW_DECISION), [17:10, 01:00) | 1 610 270 | 20 | 3 | 2 | **198.7 s** |
| pinned union, [00:00, 01:00) | 349 697 | 4 | 1 | 0 | **121.4 s** |
| SHADOW_DECISION only (10-01 → 10-03 only), [17:10, 01:00) | 1 565 467 | 0 | 0 | 0 | 15.1 s |

(For the pinned union the "> 60 s" column counts gaps in the (60, ∞) buckets: 17 + 1 + 2 in-window.) The live sample at 16:16Z showed 2.08 MB in 180 s (≈ 11.5 KB/s, driven by SHADOW_DECISION); 4 of 180 one-second samples showed zero growth.

**Verdict: STOP gate TRIPPED; design switched (done in this r2).**
- Gaps exceed the 60 s poll: 17 all-line gaps and 20 pinned-line gaps > 60 s inside the window over 7 days. So r1's "strictly larger size one poll apart" would have deferred spuriously, and the docstring's "~100 KB/min" (`:702-706`) is false for pre-FQ days (3–9 MB/day ≈ 2–6 KB/min).
- "Non-error lines only" is refuted: the steady-state data line is a WARN (`_note_depth_truncation`), so the non-error series has 40-minute holes.
- The adopted rule is a **threshold proof on a pinned positive line**. It requires a pinned-line timestamp no older than 600 s, which is 3× the 7-day in-window maximum (198.7 s) and 5× the quiet-hour maximum (121.4 s). On this data, every in-window poll of a healthy node would have marked.
- The PR records a re-run of `gaps_signal.py` over the 7 days preceding merge. If its in-window pinned-union max exceeds 300 s (half the threshold), the PR raises `LIVENESS_MAX_AGE` with the data, never silently.

### Risks and residuals

- **R1. False MARK leads to MIDDAY_WATCH acting on the wrong node.** It needs every goal-4 proof on one poll, including a fresh flock-holder match, a current-day stamp, the anchor, and a pinned data line ≤ 600 s old. Even then, a false MARK can only make MIDDAY_WATCH relaunch a *dead* tracked child under the A-1 ceiling (≤ the day's first boot). Severity is low; T1/T7/T10/T11/T11b/T18 cover it.
- **R2. Pinned-line dependence (C11).** The depth-truncation line needs > 10 levels on some book; SHADOW_DECISION needs the FQ family composed. If a future family/venue has neither, the mark defers and the CRITICAL fires nightly after a restart. That is fail-loud, and the duty is no worse than today. The remedy, if it ever happens, is a separate plan: a Breezy-owned periodic INFO line from a Nautilus clock timer in the strategy (a native extension). It is deliberately not built now (YAGNI: not observed in 7 days). T19 makes a silent marker rewording impossible.
- **R3. CT13.** One extra `/proc/locks` read per poll, only until the MARK. The fail direction is "defer"; persistent deferral now pages (S3). If CT13 recurs, the PROGRESS row's planned `locks_path` fault-injection applies to T9 as well.
- **R4. Bounded budgets reset on restart.** `relaunch_attempts`, `midday_relaunch_attempts` and the boot-retry counters restart at 0 (true today). Worst case is up to 3 extra mid-day attempts per restart, never concurrent, each A-1-capped. Out of scope. `permit_capability_valid` may classify a ceiling lapse as LAPSED rather than EXPIRED_AT_CEILING after a restart (a classification-only page difference).
- **R5. Booting child adopted mid-relaunch (C7).** B1 may page ABSENT before the permit line appears. This is pre-existing and fails loud.
- **R6. FU-17 boot-retry counters are not re-latched on restart** (R4 class).
- **R7. Clock.** `now_ns` and `now` come from one clock read; windowing uses full datetimes. The line timestamps are node-written on the same host clock, and an NTP step of ≤ seconds is immaterial against 600 s. A node clock *ahead* of the supervisor makes the age negative, which is treated as fresh; that is acceptable because both read the same host clock.
- **R8. Replay cap.** The byte-0 replay reads ≤ 2 MiB; on large logs the boot lines are within it (the permit is line 2), and the pinned line comes from the next incremental delta (C3 poll 2). The mark is then at most one poll later.

---

## §7 Activation

1. Merge into `feat/data-capture-and-risk` after a green full gate (read the EXIT code before any push).
2. **Activate immediately, at any UTC instant** ("activate-code-immediately"). r1's "wait for 17:10Z if merged in [16:30, 17:10)" hold is **dropped** (S5). This change exists so a restart is safe at any instant, the sweep (T14) and the real-flock restarts at 16:50/16:55 (T14b) prove the launch window, and a hold contradicts the goal. No measurable condition gates activation beyond the green gate.
3. `systemctl --user restart breezy-trade-supervisor`. No daemon-reload; the unit is unchanged.
4. Verify:
   - the node pid and elapsed time are unchanged (`ps -o pid,etimes`);
   - `supervisor_started revision=<merge sha>`;
   - in [17:10, 01:00): `permit_watch_adopted_live_node`, then `restart_adopted_ready_node liveness_age_s=…` within 2 polls, then a MIDDAY_WATCH dispatch line on the next iteration;
   - no `TRADE_SUPERVISOR_*` CRITICAL and no `READY_ADOPTION_DEFERRED`;
   - outside the window, `restart_adopted_ready_node` is absent (expected); the next 16:40 STOP_PRIOR SIGTERMs the node.
5. Live proof of the goal state: the first restart that falls inside [17:10, 01:00) with a healthy node is the acceptance run; record its log lines in PROGRESS. The activation restart itself is the acceptance run if it lands in that window.

## §8 Rollback

`git revert <sha>`, gate, then restart the supervisor. **The rollback restart is subject to the OLD rule**, because the old code is what boots: restart only in **[01:00Z, 16:40Z)**, i.e. at or after 01:00:00Z and strictly before 16:40:00Z, per the "supervisor-changes-need-a-supervisor-restart" memory. If rollback is urgent inside [16:40Z, 01:00Z), restarting is still safe for STOP/LAUNCH/SELF_CHECK (existing adoption paths). It only forfeits that day's MIDDAY_WATCH, which is the pre-change documented behaviour. No state, schema, unit or store migration exists to undo.

## §9 Binding invariants: checklist

- [x] Operator caps, permit mint/TTL, A-1 ceiling, `BREEZY_*_ENABLED`, NO-SEND: untouched (§2.3). The plan only reads permit lines; it never mints, extends or enables.
- [x] No test is edited or weakened. Only new tests, plus additive entries in existing reset-set and enum-set expectations (T5; `AlertDetail` +2). None is removed.
- [x] Nautilus is untouched; node logs are only read. The node and its emitters are unchanged (§2.3).
- [x] No double launch (§3, T14 real scheduler, T14b real flock). No `launch_done` without proof (§2.1; T1/T3/T7/T10/T11/T11b/T15d). CT13 fails closed and now pages when persistent (T9).
- [x] No unit edit, so there is no symlink activation hazard.

---

## §R2 Disposition (merged review r1 → r2)

| Item | Disposition | Where |
|---|---|---|
| **S1** [SFH HIGH] proof of liveness | **Applied.** The pinned positive lines are named from code: `_note_depth_truncation`'s WARN "book level(s) discarded so far" (`adapters/polymarket_us/data.py:1874-1880`) and `SHADOW_DECISION` (`strategy/forecast_quantile_ladder/strategy.py:581`). They form the closed set `LIVENESS_POSITIVE_MARKERS`, pinned by T19. The "count only non-error lines" option was measured and rejected (non-error max gap 2 432 s in the window, because the frame line is a WARN). Freshness uses the line's own timestamp (≥ log spawn stamp, ≤ 600 s old). `expires_at_ns > now_ns` is evaluated with the marking poll's own `now_ns` (T10 variant). A retry-looping node never marks (C10, T11); neither does a lapsed one (C5, T10). | §0 goal 4–5, §2.1 checks 5/9, §3 C10, §4 T7b/T10/T11/T11b/T11c/T19 |
| **S2** [both] measure log advancement, STOP gate | **Run, and the gate tripped.** 7 days, 6.24 M gaps. In [17:10, 01:00): 17 all-line gaps > 60 s, max 198.7 s. In [00:00, 01:00): 3 > 60 s, max 121.4 s. Pinned union: in-window max 198.7 s, quiet hour 121.4 s. As the gate requires, the design was switched to a threshold proof (pinned line ≤ 600 s) before any build. B1 poll cadence stated: one B1 call per `_run_forever` iteration, 60 s sleep (`_SCHEDULE_POLL_INTERVAL_S`, core:1866) for `NONE`, so 60 s plus work in the window. The PR re-runs the measurement with a 300 s escalation rule. | §2.2 cadence, §6 Stage 0 |
| **S3** [SFH] deferral alerting | **Applied.** Seven non-terminal verdicts are counted, including CT13 `HOLDER_UNPROVEN`, `NO_FRESH_ACTIVITY` (r1's LOG_NOT_ADVANCING) and `IO_ERROR`. r1's `log_size` port no longer exists; every OSError inside the step is logged on each occurrence and counted. One-shot WARN at 5 polls, then CRITICAL at 12, through `_send_permit_alert` (observable delivery, latched only on a successful send, retried otherwise). Deduped per child via latches cleared by `record_child_adopted`. | §2.4, §4 T7d/T9/T16/T16b |
| **S4** [TBA] anchor before marking | **Applied.** Check 7 `ANCHOR_UNKNOWN` defers (counted). The T15 variants cover adoption via B1, via `_do_launch` (RELAUNCH_CHECK latches the anchor, `:1326-1334`) and via SELF_CHECK (`derive_self_check_facts` latches it); (d) is the missing-anchor case. | §2.1 check 7, §4 T15a–d |
| **S5** [TBA] activation hold | **Applied: the hold is dropped.** Activation is immediate at any instant; the evidence is T14 and T14b. | §7 step 2 |
| **S6** [TBA] tests against real code | **Applied.** T14 drives the real `next_due`, `_do_launch` and the other real handlers, with fakes only at the port layer, and asserts from the port call log. T14b uses a real-flock child with restarts at 16:50:00 and 16:55:00. | §4 T14, T14b |
| LOW: rollback restart window | **Applied.** [01:00Z, 16:40Z), endpoints stated; urgent in-window rollback consequences stated. | §8 |
| LOW: `_NODE_LOG_NAME_RE` identity, choice pinned | **Applied.** One pattern in core = the r1 literal plus a single capture group; re-exported under the same name; no second pattern. T6b checks identical match truthiness against the frozen r1 literal over a name corpus, and pins the new literal. | §2.1, §4 T6b |
| LOW: re-verify STOP's alert path | **Done.** `_do_stop_prior` `:1159-1166` REFUSE_ALERT → `alert(ports.alert_sink, event="TRADE_SUPERVISOR_STOP_PRIOR_REFUSED", severity="CRITICAL", detail=AlertDetail.ADOPTION_REFUSED)`; race → WARN `STOP_PRIOR_RACE_REFUSED` (`:1175-1183`). `alert` → `emit_alert` (fire-and-forget, contained) on the sink from `resolve_alert_sink` (Tee: logging + webhook when configured). B4's "same CRITICAL on re-run" holds. | §3 B4 |

**Dropped from r1:** the `log_size` port, `ready_adoption_log_size_probe`, `record_ready_adoption_log_probe`, `LOG_NOT_ADVANCING`, the "~100 KB/min" premise, and the 17:10Z activation hold.

**Self-score (planner): 93/100.** The residual deductions:
- R2: the liveness signal depends on market or family activity, with no heartbeat built (fail-loud, and not observed in 7 days).
- The 600 s / 5 / 12 constants are derived from one 7-day sample.
- T14's world model is still a fake at the port layer; only T14b/T17 touch real `/proc/locks`.
