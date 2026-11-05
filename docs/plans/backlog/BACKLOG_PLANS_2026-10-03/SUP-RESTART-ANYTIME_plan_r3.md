# SUP-RESTART-ANYTIME: plan r3 (2026-10-03)

Status: DRAFT r3, for peer review. Plan only: no code.
Supersedes: `SUP-RESTART-ANYTIME_plan_r2.md` (unchanged). Reviews applied: `reviews/SUP-RESTART-ANYTIME-r2-merged.md` (SH1, SM1, SM2, SM3, SL1; see §R3 Disposition at the end) on top of `reviews/SUP-RESTART-ANYTIME-r1-merged.md` (S1–S6 and every LOW; §R2 Disposition, kept verbatim and re-checked for regressions in §R3).
Backlog row (docs/core/PROGRESS.md:97): "Proposed: adopting a live, ready node marks `launch_done`/`readiness_observed`, so the supervisor can deploy at any time. Needs a plan and peer review".
Related: CT13-FLAKE (PROGRESS.md:98), SUP-ADOPT-PERMIT, SUP-ADOPT-LOG-GLOB, FU-17, A-1, B1.

Every code citation below was read on 2026-10-03 through codegraph (`projectPath=/home/jon/breezy`) or a direct read of the named lines. Stage 0 (§6) was **run** on 2026-10-03 ~16:20Z; its numbers are in §6 and the scripts and raw output are in the session scratchpad `…/scratchpad/suprestart/` (`gaps.py`, `gaps_signal.py`, `gaps_7d.json`, `gaps_signal_7d.json`, `live_size_samples.txt`).

**What changed from r2, in one paragraph.** The r2 review found the "delivered CRITICAL" claim false: production's `TeeAlertSink` swallows a webhook failure inside `emit_alert`, so `_send_permit_alert` returns `True` regardless (SH1). r3 states the truth ("logged locally; webhook best effort") and adds the coordinator's mitigation: the CRITICAL is **re-fired every 60 polls** while deferral continues, with a test against the real `TeeAlertSink` + a failing real `WebhookAlertSink`. No new delivery mechanism is built (no shipped delivery-proof helper exists, §1). `LOG_NOT_CURRENT_DAY` becomes a counted deferral, because a restarted supervisor never re-runs STOP_PRIOR after 16:50 and nothing else pages a D−1 node with a live permit (SM1). A deliberately unarmed node gets a terminal `NOT_REQUIRED` verdict, matching B1 (SM2). The liveness marker is **`SHADOW_DECISION` only**; the depth-truncation WARN is dropped because it is rate-limited by a cumulative counter, not a frame signal (SM3). `latest_liveness_line_ns` takes the last *parseable* occurrence in a bounded scan, check 9's spawn-stamp clause is declared vacuous with the real guarantee (the pid→log binding) tested directly, and T14 runs on the real `IncrementalLogReader` (SL1).

**What changed from r1, in one paragraph (r2, kept).** The Stage 0 measurement tripped r1's own STOP gate: the node log goes silent for longer than the 60 s B1 poll (20 gaps > 60 s inside [17:10, 01:00) over 7 days, max 198.7 s), and counting only non-error lines is far worse (max 2 432 s), because the steady-state data-flow line is a WARN. So r2 drops r1's "log size grew across one poll" proof and replaces it with a **pinned positive line with an age threshold** (S1+S2): the timestamp of the newest Breezy-owned data-frame line must be within 600 s of the marking poll. r2 also requires the A-1 anchor before marking (S4), adds per-child deferral alerting with delivery (S3), drops the activation hold (S5), and drives the never-double-launch sweep through the real `next_due`/`_do_launch` plus real-flock variants at 16:50 and 16:55 (S6).

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
3. keeps that trading day's STOP_PRIOR, LAUNCH, RELAUNCH_CHECK, SELF_CHECK and MIDDAY_WATCH duties. For a healthy node, MIDDAY_WATCH is restored on the first or second B1 poll after the restart (≤ 2 × 60 s plus work). When proof is missing, the supervisor says so: a per-child WARN after 5 consecutive deferred polls and a CRITICAL after 12, re-fired every 60 further polls while the deferral persists (§2.4). Each alert is **logged locally; the webhook is best effort** (SH1);
4. never sets `launch_done`/`readiness_observed` for a node that is not proven ready. **Proven ready** means all of the following hold **on the single marking poll**:
   - the process is alive;
   - it is the verified flock holder, by a fresh `/proc/locks` probe on this poll;
   - its own permit line is latched, and `expires_at_ns > now_ns` for **this poll's** `now_ns`;
   - its strategy-subscribed marker is latched;
   - the day's A-1 anchor `first_boot_permit_expires_at_ns` is latched (S4);
   - its log is stamped inside the current trading day;
   - **fresh activity:** the newest parseable `SHADOW_DECISION` line (§2.1) in this child's own log has a timestamp `>= now − 600 s`. That the line is post-boot follows from the pid→log binding (`find_adopted_node_log` / `node_log_path`) and the per-child latch reset, not from the `>=` spawn-stamp clause, which is vacuous by construction (SL1, §2.1 check 9);
5. fails closed on the CT13 transient: a `None` holder probe means "not proven" on that poll, and it is retried the next poll. It never means "ready" and never means "dead, relaunch". A retry-looping node (one writing only reconnect or error lines), and a node whose permit has lapsed, never mark. A deliberately unarmed node (orders not requested) never marks and is not paged by this step (`NOT_REQUIRED`, terminal; B1 already WARNs once). A D−1 node with a live permit never marks and **is** paged by this step (SM1). A node without the FQ family composed never marks and is paged (SM3 residual R2).

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
| Log file → spawn time, and pid → log binding | `node_log_path` stamps `breezy-trade-YYYYMMDDTHHMMSSZ.log` (`:787-789`). `_NODE_LOG_NAME_RE` (`:798`). `find_adopted_node_log` (`:814-846`): the newest node-stamped log whose mtime is `>=` `/proc/<pid>` ctime, else `None`. | **Reuse** the stamp as current-trading-day evidence and the binding as the post-boot guarantee (SL1). |
| Positive data-frame line | `ForecastQuantileLadderStrategy._emit_shadow_decision` (`strategy/forecast_quantile_ladder/strategy.py:577-581`, `self.log.info(f"SHADOW_DECISION {line!r}")`), called unconditionally from `evaluate_snapshot` (`:564`) on every evaluated snapshot, which is reached only from `on_order_book_depth`/`on_quote_tick` → `_safe_evaluate` → `_evaluate_instrument_update` (`:713-770`). Data-driven: a reconnect loop cannot emit it. It is emitted whether or not the family is armed (it is not gated on the permit). **Rejected (SM3):** `_note_depth_truncation`'s WARN (`adapters/polymarket_us/data.py:1873-1880`) fires only when the cumulative truncation count is 1 or a multiple of 100 (`should_warn_at_count`, `:555-561`), so its cadence is lumpy and a function of book shape, not a frame signal. | **Reuse** `SHADOW_DECISION` as the single pinned marker (§2.1). No new emitter. |
| Alert path | `_send_permit_alert` (`:958-974`) returns `False` only when `sink.emit` itself raises. Production's sink is `resolve_alert_sink()` (`health.py:392-423`): bare `LoggingAlertSink` when no webhook is configured, else `TeeAlertSink(LoggingAlertSink(), WebhookAlertSink(url))`. `TeeAlertSink.emit` (`health.py:366-369`) calls `emit_alert` per branch, and `emit_alert` (`:479-510`) catches `BaseException` and logs `alert sink failed to emit … exception_type=…` at ERROR. **So in production the send always returns `True`, and a webhook failure is invisible to the caller** (SH1). `AlertDetail` is the closed detail enum (`core:257`). | **Reuse**, with the claim corrected to "logged locally; webhook best effort". The latch-on-`True` discipline is kept (it still matters for a sink that raises), and redundancy comes from the CRITICAL re-fire (§2.4). |
| Delivery-proof helper (SH1 ruling: cite only if shipped) | Searched `src/` for `deliver_with_proof`, `outbox`, `AlertOutbox`, `delivery_proof`: **zero hits.** The only delivery-reporting code is `check_alerts_cli` (`runtime/check_alerts_cli.py:122-157`), an operator one-shot that calls `sink.emit` and maps a raise to exit 3; it is not an in-loop helper. | **Not used; nothing is built** (coordinator ruling). |
| Containment | B1's `[D8]` try (`:2160-2222`) plus `_dispatch_permit_watch`'s outer `[A2]` try (`:2542-2559`). | **Reuse.** The new step runs inside `_do_permit_watch`'s try. |
| systemd `ExecReload=` / hot reload | A Python process cannot safely re-import changed modules in place, and nothing in the repo supports it. | **Rejected.** It does not remove the restart. |
| systemd `FileDescriptorStoreMax=` (memfd state carry-over) | Across a **deploy** it means unpickling old-schema state into new code, and it re-trusts latches (e.g. readiness of a node that died during the restart gap) without re-proving them. | **Rejected.** Re-deriving from live evidence is self-validating; carried-over state is not. |
| Persisting `DaySchedulerState` to the exec store (precedent `SELF_CHECK_ESCALATION_STORE_KEY`) | Same stale-latch and schema-drift objections, plus a new writer to the exec store during live trading. | **Rejected** for this item. |
| Nautilus | The supervisor is an external process manager; Nautilus has no process-supervision or adoption facility to extend. Nautilus log lines are only **read** (their timestamp prefix); nothing in the node changes. Nautilus emits no periodic heartbeat line in the node log (none observed across 6.2 M lines in Stage 0). | N/A. Nautilus stays immutable. |

**Conclusion.** The missing pieces are one pure decision, one positive-line projection added to the existing `latch_log_facts`, one state recorder, and a deferral-alert latch set. They are wired at one site (`_do_permit_watch`'s in-window branch), right after the existing adoption, replay and drain. There is no new adoption logic, no new reader, no unit change and no persistence.

---

## §2 Design

### 2.1 Pure core (in `trade_supervisor_core.py`, stdlib-only)

**Pinned positive line (S1, narrowed by SM3).** The liveness signal is named from code, not inferred from byte growth:

```
#: [SUP-RESTART-ANYTIME] Breezy-owned line emitted ONLY when the FQ strategy
#: evaluated a live venue snapshot (strategy.py:564/577-581, reached only from
#: on_order_book_depth / on_quote_tick). Pinned against its emitter (T19).
LIVENESS_POSITIVE_MARKER: Final[str] = "SHADOW_DECISION "
LIVENESS_MAX_AGE_NS: Final[int] = 600 * 1_000_000_000   # §6: >= 39x the measured 15.1 s max gap
LIVENESS_SCAN_MAX_OCCURRENCES: Final[int] = 64           # bounded backwards scan (SL1)

def latest_liveness_line_ns(log_text: str) -> int | None
    # Walk occurrences of the marker BACKWARDS (rfind with a moving end bound),
    # at most LIVENESS_SCAN_MAX_OCCURRENCES of them. For each, take the line
    # containing it (rfind "\n" before it), strip ANSI, and parse the Nautilus
    # prefix "YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ" -> epoch ns. Return the FIRST one
    # that parses, i.e. the last PARSEABLE occurrence. None if there is no
    # occurrence, or none of the scanned ones parses (fail closed).
```

**Why the last *parseable* occurrence (SL1).** A delta can begin mid-line: `IncrementalLogReader.read_new` prepends a 256-char carry, and `read_from_start_and_mark_consumed` stops at 2 MiB, so a marker can sit on a line whose timestamp prefix was cut off. Verified on 2026-10-03: the first `SHADOW_DECISION` hit in a byte-offset tail of the live log was exactly such a headless line. r2's "parse the line of the last occurrence, else `None`" would then discard a perfectly good earlier line in the same delta. The bound (64 occurrences) keeps the cost O(delta) and makes a pathological delta fail closed, never slow.

**Why `SHADOW_DECISION` only (SM3).** The depth-truncation WARN is dropped: it is emitted only when the cumulative truncation count is 1 or a multiple of 100 (`data.py:1873`, `should_warn_at_count` `:555-561`), so its spacing depends on how many levels the venue happens to publish, not on whether frames are arriving. `SHADOW_DECISION` is emitted on **every** evaluated venue snapshot (`evaluate_snapshot` → `_emit_shadow_decision`, unconditional, not permit-gated). "Any non-error line" and "any growth" stay rejected for the r2 reasons (§6: non-error max gap 2 432 s; raw growth counts reconnect WARNs and error lines from a retry-looping node, which S1 forbids). A node in a websocket reconnect loop (`websocket.py:958-962`) or an exception loop writes no `SHADOW_DECISION`: `_safe_evaluate` logs `… handler failed …` on an exception, never the marker. The honest cost: a node **without the FQ family composed** never marks (residual R2).

`latch_log_facts` (`core:1726-1772`) gains one projection, additive and order-independent:

```
ns = latest_liveness_line_ns(log_text)
if ns is not None:
    state = record_liveness_line_seen(state, now_utc, ns)   # keeps max(prev, ns)
```

Max-wins makes the carry harmless: a carry fragment re-presented in the next delta can only re-offer a timestamp already latched, never lower the latch, and never raise it above what the node actually wrote.

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
    NOT_REQUIRED = "not_required"                # SM2: orders not requested; B1 WARNs once (PermitCapability.NOT_REQUIRED)
    # non-terminal deferrals: counted toward §2.4 alerting
    HOLDER_UNPROVEN = "holder_unproven"          # CT13: None or mismatch on THIS poll
    PERMIT_ABSENT = "permit_absent"
    NOT_SUBSCRIBED = "not_subscribed"
    ANCHOR_UNKNOWN = "anchor_unknown"            # S4
    LOG_UNKNOWN = "log_unknown"                  # node_log None or stamp unparseable
    LOG_NOT_CURRENT_DAY = "log_not_current_day"  # SM1: D-1 node; nothing else pages it after a restart
    NO_FRESH_ACTIVITY = "no_fresh_activity"      # S1/S2/SM3
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
5. When `state.permit_issued_seen_expires_at_ns is None`: `NOT_REQUIRED` (terminal) if `state.orders_not_requested_seen`, else `PERMIT_ABSENT`. When it is latched: `PERMIT_EXPIRED` when it is `<= now_ns`. `now_ns` is **this poll's** clock reading, the same one the MARK is taken on (S1 "re-check on the same poll"). The order (latched permit first, then the not-requested latch) is exactly `permit_capability_valid`'s (`core:1593-1605`), so this step and B1 never disagree about NOT_REQUIRED (SM2).
6. `NOT_SUBSCRIBED` when not `state.strategy_subscribed_seen`.
7. `ANCHOR_UNKNOWN` when `state.first_boot_permit_expires_at_ns is None` (S4). `_do_midday_watch` refuses every relaunch without the anchor (A-1), so marking without it would restore a duty that cannot act.
8. `LOG_UNKNOWN` when `log_spawned_at is None`; `LOG_NOT_CURRENT_DAY` when `log_spawned_at < _at(state.day, STOP_PRIOR_UTC)`. **Both are counted deferrals** (SM1). Rationale: `next_due` dispatches STOP_PRIOR only in [16:40, 16:50) (`core:1102-1103`), so a supervisor restarted after 16:50 never re-runs it, and B1 classifies a D−1 node with an unexpired permit as `VALID` (no page). Without counting, that node would be silent all night.
9. `NO_FRESH_ACTIVITY` when `state.liveness_line_last_ns is None`, or `now_ns - it > LIVENESS_MAX_AGE_NS`. The r2 clause "`< log_spawned_at` (not post-boot)" is **kept as a cheap guard but is vacuous by construction** (SL1): the latch is cleared for every new child by `record_child_adopted`, and it is fed only from the tracked child's own per-spawn log, every line of which postdates the spawn stamp. The real post-boot guarantee is the **pid→log binding**: on the B1/SELF_CHECK/`_do_launch` adoption paths `find_adopted_node_log` returns only a node-stamped log whose mtime is `>=` `/proc/<pid>` ctime (`:814-846`), and on the spawn path the log is the one `node_log_path` created for that child. A different child's log cannot be bound unless it was written after this pid started; only one `breezy-trade` holds the intent flock (check 4), so a second concurrent writer is excluded. T18b tests the binding itself.
10. Otherwise `MARK`.

Checks 4, 5 (absence) and 6 are exactly `readiness_observed(...)`'s three conjuncts. The implementation calls `readiness_observed(...)` and maps a `False` to the specific reason (one shared predicate, no copy).

```
def is_deferral(v: ReadyAdoptionVerdict) -> bool          # the eight non-terminal members
def record_ready_adoption(state, now_utc) -> DaySchedulerState
    # = record_readiness_observed(mark_phase_fired(state, Phase.LAUNCH, now_utc), now_utc)
    #   and applies reset_ready_adoption_deferral (polls=0, critical_last_poll=None)
def record_liveness_line_seen(state, now_utc, ns: int) -> DaySchedulerState   # max-wins, _for_day
def record_ready_adoption_deferral(state, now_utc) -> DaySchedulerState       # +1
def reset_ready_adoption_deferral(state, now_utc) -> DaySchedulerState        # polls=0, critical_last_poll=None (terminal verdict or MARK)
def record_ready_adoption_alert_sent(state, now_utc, *, critical: bool) -> DaySchedulerState
    # WARN: warn_sent=True.  CRITICAL: critical_last_poll = deferral_polls (SH1 re-fire anchor)
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
ready_adoption_critical_last_poll: int | None = None   # SH1: deferral_polls value at the last CRITICAL sent; None = none yet
```

r2's `ready_adoption_critical_sent: bool` is replaced by `ready_adoption_critical_last_poll` (SH1 re-fire); the field count stays four. `record_child_adopted` adds those four to its `replace(...)`. That is purely additive: every existing field is cleared exactly as before. r1's `ready_adoption_log_size_probe` field and `record_ready_adoption_log_probe` are **dropped**.

**Why the log stamp proves the current trading day.** Permit-unexpired alone does not: a node hand-launched at D 10:00 has an unexpired 10 h permit at D 17:10, yet it belongs to trading day D−1. The stamp is written by `node_log_path` at spawn, and hand relaunches mirror `spawn()` (memory "hand-relaunch-mechanics"). `find_adopted_node_log` already binds the file to the pid (mtime ≥ `/proc/<pid>` ctime); that binding, not check 9's spawn-stamp clause, is what makes every latched `SHADOW_DECISION` line this child's own (SL1). An unknown log fails closed (`LOG_UNKNOWN`, counted); a D−1 log is counted too (`LOG_NOT_CURRENT_DAY`, SM1).

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
- The node and its log emitters. The pinned `SHADOW_DECISION` line already exists; nothing is added, reworded or re-gated (and the dropped depth-truncation WARN is untouched).

### 2.4 Deferral alerting (S3)

`decide_ready_adoption_alert(state)` (pure) is called by the step after every deferral:

| Condition | Alert | Latch |
|---|---|---|
| `deferral_polls >= READY_ADOPTION_WARN_POLLS` (5) and not `warn_sent` | `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED`, severity **WARN**, detail `AlertDetail.READY_ADOPTION_DEFERRED` | `warn_sent` |
| `deferral_polls >= READY_ADOPTION_CRITICAL_POLLS` (12) and `critical_last_poll is None` | same event, severity **CRITICAL**, detail `AlertDetail.READY_ADOPTION_UNPROVEN` | `critical_last_poll = deferral_polls` |
| `critical_last_poll is not None` and `deferral_polls - critical_last_poll >= READY_ADOPTION_CRITICAL_REFIRE_POLLS` (60) | same CRITICAL (re-fire, SH1) | `critical_last_poll = deferral_polls` |

If both WARN and CRITICAL are due on one poll (e.g. a send failure delayed the WARN), the CRITICAL wins and the WARN is latched with it; at most one alert is sent per poll.

- **Delivery: logged locally; webhook best effort (SH1, corrected).** Sent with `_send_permit_alert` (`:958-974`) on `ports.alert_sink`. What that does and does not prove:
  - The local supervisor-log line `breezy alert event=TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED … severity=…` is written by `LoggingAlertSink` (first branch of the Tee, or the bare sink when no webhook is configured).
  - The webhook POST is **best effort**. `TeeAlertSink.emit` contains each branch through `emit_alert`, so a webhook timeout/5xx/TLS failure is logged at ERROR (`alert sink failed to emit event=… exception_type=…`, `health.py:504-510`) and is **not** visible to `_send_permit_alert`, which returns `True`. r2's "observable delivery" claim was false and is withdrawn.
  - The latch-on-`True` / retry-next-poll discipline (B1 [A2]) is kept: it still matters for any sink that raises (a bare `WebhookAlertSink`, a test sink). In production it never triggers.
  - **Mitigation without a new mechanism:** the CRITICAL is **re-fired every 60 polls (~1 h)** while the deferral persists, until a MARK or a terminal verdict. Each re-fire is a fresh webhook attempt, so a transient webhook outage costs at most one hour of off-box silence, while the local log line is written every time. Bound: the window is 470 min, so at most ⌈(470 − 12) / 60⌉ = 8 CRITICALs per child per night.
  - No delivery-proof helper is shipped (§1 row "Delivery-proof helper"); none is built here (coordinator ruling).
- **Dedupe.** At most one WARN per child. The CRITICAL is sent at poll 12 and then once per 60 consecutive deferred polls. `warn_sent` and `critical_last_poll` clear on `record_child_adopted` (a new child gets a fresh budget) and on rollover. `reset_ready_adoption_deferral` (MARK or any terminal verdict) zeroes the counter **and** clears `critical_last_poll`, so the re-fire arithmetic can never go negative after a terminal interlude; `warn_sent` stays per child, which bounds WARN volume on a flapping child.
- **Thresholds.** 5 polls ≈ 5 min is ≥ 19× the measured in-window `SHADOW_DECISION` max gap (15.1 s, §6), so a healthy FQ node never WARNs. 12 polls ≈ 12 min is above `LIVENESS_MAX_AGE` (600 s), so the CRITICAL fires only after one full freshness horizon has passed without proof. 60 polls is the coordinator's re-fire period. All three are named constants in core.
- **What is counted.** CT13 `None`/mismatch (`HOLDER_UNPROVEN`), `PERMIT_ABSENT`, `NOT_SUBSCRIBED`, `ANCHOR_UNKNOWN`, `LOG_UNKNOWN`, `LOG_NOT_CURRENT_DAY` (SM1), `NO_FRESH_ACTIVITY` and `IO_ERROR`, the last being a persistent OSError, logged on each occurrence. **Not counted (terminal):** `NOT_IN_WINDOW`, `ALREADY_READY`, `NO_CHILD`, `PERMIT_EXPIRED`, `NOT_REQUIRED` (SM2).
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
| C1 | [17:00, 17:05) | D node live | SELF_CHECK at 17:05 adopts and reads the log, latching permit, subscribed and anchor. At 17:10 B1 runs with the tracked pid alive (no replay); its drain (17:05→17:10 delta) latches the newest parseable `SHADOW_DECISION` line; the step **marks on the first in-window poll** if that line is ≤ 600 s old. | existing + **new** |
| C2 | [17:05, 17:10) | D node live | Same as C1. | existing + **new** |
| C3 | [17:10, 01:00) | D node live and ready | Poll 1: B1 adopts plus byte-0 replay (permit, subscribed, anchor and the newest replayed `SHADOW_DECISION` line latched; the replay is capped at 2 MiB and then resumes at EOF, so on a large log (≈ 3 min of FQ output at 11.5 KB/s) the replayed line is old and the fresh one comes from the next delta). The step marks if that line is fresh, otherwise `NO_FRESH_ACTIVITY` (counted). Poll 2: B1's delta has fresh `SHADOW_DECISION` lines → `MARK`. Next iteration: MIDDAY_WATCH. No spawn, no signal. | **new** |
| C4 | [17:10, 01:00), CT13 transient | D node live | B1's adoption probe `None` → nothing adopted (existing fail-closed, retried). If adoption succeeded but the step's fresh probe is `None` → `HOLDER_UNPROVEN`, counted, retried. Persistent `None` → WARN at 5, CRITICAL at 12 polls, **never** a mark, **never** a spawn. | existing + **new** |
| C5 | [17:10, 01:00) | permit expired (e.g. a midday child at the A-1 ceiling) | `PERMIT_EXPIRED` (terminal) → never marked. B1 pages LAPSED/EXPIRED_AT_CEILING as today. | **new** (guard) |
| C6 | [17:10, 01:00) | previous-day node (STOP refused), unexpired permit | `LOG_NOT_CURRENT_DAY` (**counted**, SM1) → never marked → WARN at 5, CRITICAL at 12, re-fired every 60 polls. The old supervisor's STOP_PRIOR CRITICAL may also exist; the duplicate is the accepted fail-loud direction. Without counting, a restart after 16:50 leaves this node unpaged (STOP_PRIOR is not due again; B1 sees `VALID`). | **new** (guard + page) |
| C7 | [17:10, 01:00) | node booting (old was mid-midday-relaunch) | `PERMIT_ABSENT`/`NOT_SUBSCRIBED` deferrals until latched by B1's drain, then a mark once a fresh `SHADOW_DECISION` line arrives (measured ~6 s after spawn, §6). A boot that never completes ends in WARN/CRITICAL. Residual: B1 may also page ABSENT (§6 R5). | existing + **new** |
| C8 | [17:10, 01:00) | down | Nothing adopted → the step returns early. **No mark, no spawn.** B1 pages NO_NODE as today. | existing |
| C9 | [17:10, 01:00), old had already marked | D node live and ready | Identical to C3; nothing inherited. | **new** |
| C10 | [17:10, 01:00) | live but retry-looping (reconnect WARNs, no frames) | `NO_FRESH_ACTIVITY` forever → never marked → WARN, then CRITICAL, re-fired hourly. | **new** (S1) |
| C11 | [17:10, 01:00) | live, healthy, but **FQ family not composed** (no `SHADOW_DECISION` ever), or FQ composed but every instrument skips before `evaluate_snapshot` (`no_ask`/`no_ladder`/`no_std_offset`, `strategy.py:785-797`) | `NO_FRESH_ACTIVITY` → no mark → WARN/CRITICAL (re-fired) says MIDDAY is not restored. Fail-closed and loud; the duty is no worse than today. Named residual R2. In §6, 5 of the 7 measured trading days (09-26 → 09-30) had no FQ family and would have taken this row. | **new** (SM3 residual) |
| C12 | [17:10, 01:00) | live, deliberately **unarmed** (`PERMIT_NOT_REQUESTED_MARKER` latched, no permit line) | `NOT_REQUIRED` (terminal, SM2) → no mark, counter reset, **no** READY_ADOPTION alert. B1 sends its own once-per-day `NOT_REQUIRED` WARN as today. Parity with an un-restarted supervisor: `readiness_observed(...)` needs a permit, so RELAUNCH_CHECK never marks an unarmed node either and MIDDAY_WATCH is not due for it today. | **new** (SM2) |
| D1 | [00:00, 01:00) (UTC date rolled, trading day D) | D node live and ready | `_trading_day` → D; window still open → same as C3. §6: the in-window `SHADOW_DECISION` max gap (15.1 s, any hour) bounds this hour too; the 10-01 node's largest gap (14.7 s) fell at 00:48Z. | **new** |

**Never double-launch (invariant).** The new step has no spawn port. LAUNCH is due only in [16:50, 17:00) and spawns only on `lock_free and node_pid is None and not open_intent` (`:1223-1234`). MIDDAY_WATCH spawns only for a tracked child that is dead. Marking makes MIDDAY_WATCH due only for a node proven alive and holding the flock on that poll. T14 proves this through the **real** `next_due` and `_do_launch` (S6).

**The 16:45 engine pass and the 16:50 LAUNCH.** The step cannot act in [16:40, 17:10) (check 1 and the shell's early return), so STOP-before-16:45, the engine `engine.lock` pass and the 16:50 sequence are unchanged.

---

## §4 Tests: RED → GREEN

Placement: pure tests in `tests/unit/test_trade_supervisor_core.py`; shell tests in `tests/unit/test_trade_supervisor.py` (reusing `_make_ports`, `_utc`, `_DAY`, `_b1_common_kwargs`, `_RecordingAlertSink`); real-process tests in a new `tests/unit/test_ct14_supervisor_restart_anytime.py` modelled on `test_ct02_supervisor_adopt_real_child.py`. Every test is observed **failing first**. An ImportError counts as RED only for T1–T7e and T19; T8–T18b must fail on an assertion against current behaviour, except T16c and T18b, which pin existing behaviour that the plan relies on (they are characterisation tests and may be GREEN on first run; this is stated in the PR, not hidden). The RED→GREEN output is kept as the change artifact.

**Pure (core)**
- T1 `test_decide_ready_adoption_marks_only_when_every_proof_holds`. Table-driven: start from an all-true baseline, flip each input in turn, and assert the specific verdict for all 14 values. This includes `ANCHOR_UNKNOWN` (permit latched, anchor `None`), `PERMIT_EXPIRED` where the latched expiry equals `now_ns` exactly plus `now_ns` one ns past it, `NOT_REQUIRED` (permit `None`, `orders_not_requested_seen=True`), and **permit latched + `orders_not_requested_seen=True` → not `NOT_REQUIRED`** (latched permit wins, same order as `permit_capability_valid`). It also asserts `is_deferral` over the full enum: exactly the eight members of §2.4 "What is counted", with `LOG_NOT_CURRENT_DAY` in and `NOT_REQUIRED` out.
- T2 `test_decide_ready_adoption_window_boundaries`. 16:45, 17:05 and 17:09:59 → NOT_IN_WINDOW; 17:10:00 → evaluated; D+1 00:59:59 → evaluated; D+1 01:00:00 → NOT_IN_WINDOW.
- T3 `test_ready_adoption_keys_on_readiness_not_launch_done`. `launch_done=True, readiness_observed=False` → can MARK (B6). `readiness_observed=True` → ALREADY_READY.
- T4 `test_record_ready_adoption_sets_both_latches_and_nothing_else`. It sets `launch_done`, `readiness_observed`, resets the deferral counter and clears `ready_adoption_critical_last_poll`. Everything else is untouched: relaunch counters, `first_boot_permit_expires_at_ns`, `self_check_done`, `ready_adoption_warn_sent` and every other alert latch. Idempotent and `_for_day`-scoped.
- T5 `test_record_child_adopted_clears_ready_adoption_fields`, plus the rollover reset. It extends the existing reset-set expectation by the four new fields; no assertion is removed.
- T6 `test_node_log_spawned_at_parses_node_stamp_only`. Parses node stamps; `None` for `breezy-trade-supervisor.log` and its `-stdout-`/`.launch-` variants, and for an impossible date.
- T6b `test_node_log_name_re_matches_identically_to_frozen_r1_literal` (LOW). A corpus of about 20 names, including every production name shape seen in `~/.local/share/breezy/logs`, the supervisor variants, a trailing-newline name, a `.log.1` name and a wrong-digit-count name. `bool(new.match(n)) == bool(re.compile(r"^breezy-trade-\d{8}T\d{6}Z\.log$").match(n))` for every name. It also pins `new.pattern` to the exact r2 literal.
- T7 `test_permit_unexpired_alone_does_not_prove_current_day`. Stamp D 10:00, permit expiring D 20:00, now D 17:30 → LOG_NOT_CURRENT_DAY.
- T7b `test_latest_liveness_line_ns`. It parses the ANSI-wrapped Nautilus prefix (`\x1b[1m2026-10-03T16:39:02.215766648Z\x1b[0m [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {…}`, copied verbatim from a production log); returns the newest parseable line; `None` for reconnect/ERROR-only text, for depth-truncation-only text (SM3: no longer a marker), and for `""`. **SL1 cases:** (i) last occurrence on a headless line (text starts mid-line), earlier occurrence parseable → returns the earlier one; (ii) every occurrence headless → `None`; (iii) 64 headless occurrences after one parseable line → `None` (the parseable one is the 65th from the end, beyond the bound: fail closed); (iv) 63 headless after one parseable → returns the parseable one (64th from the end, inside the bound).
- T7c `test_latch_log_facts_records_liveness_max_wins`. A later delta with an older line never lowers the latch; existing `latch_log_facts` outputs are unchanged for text with no marker.
- T7d `test_decide_ready_adoption_alert_thresholds_dedupe_and_refire` (SH1). 4 → None; 5 → WARN; 6..11 → None; 12 → CRITICAL; 13..71 → None; 72 → CRITICAL; 132 → CRITICAL; after `reset_ready_adoption_deferral` (terminal) then 12 more deferrals → CRITICAL again at 12, never a negative-delta skip; after `record_child_adopted` → WARN again at 5. A CRITICAL whose send is not latched (send returned `False`) is due again on the next poll.
- T7e `test_log_not_current_day_is_a_counted_deferral` (SM1). Stamp D−1 16:50, permit unexpired, every other proof true, polls at D 20:00 + k·60 s → verdict `LOG_NOT_CURRENT_DAY` each poll, counter reaches 5 (WARN) and 12 (CRITICAL).

**Shell (fake ports and a fake clock driving `_run_forever` with `max_iterations`)**
- T8 `test_restart_at_2000_with_ready_node_restores_midday_watch_without_spawn`. Iteration 1 adopts plus replay; the log fixture has a `SHADOW_DECISION` line stamped 20:00:30 and now is 20:01 → MARK on iteration 1 (assert `restart_adopted_ready_node`). Next iteration dispatches MIDDAY_WATCH. `spawn` and `terminate_after_recheck` are never called. **RED today.**
- T9 `test_ct13_transient_holder_none_defers_mark_and_never_spawns`. Holder sequence `[pid, None, pid]` (the adoption probe succeeds, the marking probe is `None`) → no mark on that poll, mark on the next. Variant: persistent `None` → never marks, spawns 0, exactly one WARN at poll 5 and one CRITICAL at poll 12, through `_RecordingAlertSink`.
- T10 `test_expired_permit_node_is_never_marked`. The B1 alert set is unchanged versus the same run with the step disabled. Variant: the permit is unexpired at poll N−1 and expired at poll N, with a fresh `SHADOW_DECISION` line arriving at N → no mark (same-poll re-check).
- T10b `test_unarmed_node_is_not_required_never_marked_never_paged_by_step` (SM2). The node log carries `PERMIT_NOT_REQUESTED_MARKER`, the subscribed marker and fresh `SHADOW_DECISION` lines, no permit line; restart at 20:00, 200 polls. Assert: no `restart_adopted_ready_node`; zero `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED` alerts of either severity; exactly one B1 `NOT_REQUIRED` WARN (unchanged from the run with the step disabled); `spawn` 0, `terminate_after_recheck` 0. **RED against r2's design** (r2 would count `PERMIT_ABSENT` and page).
- T10c `test_d_minus_1_node_after_restart_is_paged` (SM1, shell). Real-scheduler run restarted at D 20:00 with a D−1-stamped live node, unexpired permit: no mark, WARN at poll 5, CRITICAL at 12 and 72, `spawn` 0, `terminate_after_recheck` 0 (STOP_PRIOR is not due, so nothing signals it).
- T11 `test_retry_looping_node_is_never_marked` (S1). The log grows by 50 KB/poll of reconnect WARN and ERROR lines with no pinned marker → never marked → WARN and CRITICAL.
- T11b `test_stale_liveness_line_is_never_marked`. The newest `SHADOW_DECISION` line is 601 s old → `NO_FRESH_ACTIVITY`; at 599 s → MARK.
- T11c `test_replayed_old_liveness_line_does_not_mark`. The replay contains only `SHADOW_DECISION` lines stamped hours ago and the delta has none → no mark.
- T11d `test_depth_truncation_only_node_is_never_marked` (SM3). A pre-FQ-shape log with frequent depth-truncation WARNs and no `SHADOW_DECISION` → never marked → WARN/CRITICAL. Pins that the dropped marker is really gone.
- T12 `test_node_down_at_restart_is_never_marked_and_never_spawned` (C8).
- T13 `test_1655_lock_held_adoption_flake_recovered_at_1710` (B6). `_do_launch` adoption fails → no spawn → SELF_CHECK at 17:05 adopts → at 17:10 the step marks → MIDDAY_WATCH. **RED today.**
- T14 `test_restart_sweep_never_double_launches_real_scheduler` (S6). Restart at every 5 min across 24 h (288 fresh `_run_forever` runs, each 30 min of fake clock). It uses the **real** `next_due`, `_do_launch`, `_do_stop_prior`, `_do_relaunch_check`, `_do_self_check`, `_do_permit_watch` and `_do_midday_watch`; only the process/flock ports are fakes. The fakes come from a single world model: one process table, one flock owner, a **real file** per child under `tmp_path` (written in the real Nautilus prefix format, with `SHADOW_DECISION` lines), and `spawn` adds a process, creates its log and takes the flock. **Log reading is real (SL1):** each fresh `_run_forever` gets a new real `IncrementalLogReader`, bound exactly as `default_ports` binds it (`read_log_new=reader.read_new`, `read_log_from_start=reader.read_from_start_and_mark_consumed`), so the 2 MiB replay cap, the resume-at-EOF offset and the 256-char carry are the production code paths. The invariants are asserted from the port call log, not from the model: concurrent live `breezy-trade` ≤ 1 at every port call; `spawn` ≤ 1 per trading day; `terminate_after_recheck` only in [16:40, 16:50); `restart_adopted_ready_node` only in [17:10, 01:00); MIDDAY_WATCH dispatched within 2 iterations of every in-window restart.
- T14c `test_real_reader_replay_cap_and_carry_paths` (SL1). Real `IncrementalLogReader`, real files, restart at 20:00. (a) **Cap:** a 3 MiB log whose boot lines (permit, subscribed) are in the first 2 MiB and whose only fresh `SHADOW_DECISION` lines lie beyond 2 MiB → poll 1: permit/subscribed/anchor latched, no fresh line (the replay skipped bytes 2–3 MiB and resumed at EOF), `NO_FRESH_ACTIVITY`; poll 2 (new fresh lines appended) → MARK. (b) **Carry:** the 2 MiB boundary falls inside a `SHADOW_DECISION` line, so the 256-char carry handed to poll 2 is a headless marker fragment; poll 2's appended text has one fresh parseable line → MARK, and with no fresh line appended → no MARK and the latch is not lowered or raised by the fragment. (c) **Partial write:** the appended delta ends mid-line after the marker → the earlier parseable line in the same delta is used.
- T15 `test_marked_adopted_child_death_relaunches_with_adopted_ceiling`, three variants (S4), each running through MIDDAY_WATCH. After the mark the child dies with a transient cause → one spawn with `BREEZY_PERMIT_EXPIRY_CEILING_NS` equal to the latched anchor.
  - (a) adopted by B1 at 20:00 (replay latches the anchor);
  - (b) adopted by `_do_launch` at a 16:55 restart, with RELAUNCH_CHECK latching the anchor;
  - (c) adopted by SELF_CHECK at a 17:06 restart, with `derive_self_check_facts` latching the anchor.

  A fourth variant, (d), builds a state with the permit latched and the anchor `None` → `ANCHOR_UNKNOWN`, no mark, counted, and no spawn ever.
- T16 `test_ready_adoption_step_exceptions`. `resolve_intent_lock_holder` raises `OSError` on every poll → `IO_ERROR`, a `ready_adoption_io_error` line per poll, counted → WARN and CRITICAL, no mark. It raises `RuntimeError` → B1 `[D8]` WATCH_FAILED, no mark, and the loop continues.
- T16b `test_ready_adoption_alert_send_failure_is_retried_not_latched`. A sink that **raises** (not the production Tee; this pins the latch-on-`True` discipline only) raises on the first CRITICAL send → no latch → resent next poll → latched once.
- T16c `test_ready_adoption_critical_through_real_tee_with_failing_webhook` (SH1). `ports.alert_sink = TeeAlertSink(LoggingAlertSink(), WebhookAlertSink("https://alerts.invalid/hook", client=httpx.Client(transport=httpx.MockTransport(<always 503>))))`: the **real** Tee and the **real** webhook sink, with an in-process mock transport, so no socket is opened and the NO-SEND gate is untouched. Persistent deferral for 133 polls. Assert: (a) `caplog` holds `breezy alert event=TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED … severity=CRITICAL` at polls 12, 72 and 132 (logged locally); (b) `caplog` holds `alert sink failed to emit event=TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED … exception_type=HTTPStatusError` for each of those sends (webhook failure visible only in the log); (c) the mock transport received exactly 4 requests (1 WARN + 3 CRITICAL: the re-fire really re-attempts the webhook); (d) `critical_last_poll` is latched after each send although the webhook failed, which pins in a test that `_send_permit_alert` cannot see a Tee branch failure, so no future reader re-asserts "delivery"; (e) no log line contains the webhook URL.

**Real process (CT-14, real `/proc/locks`)**
- T17 `test_real_flock_holder_with_fresh_liveness_line_is_marked_after_restart`. A real child takes the intent flock and writes a correctly stamped log: permit line, subscribed line, then a `SHADOW_DECISION` line in the real ANSI-wrapped Nautilus prefix format every 0.2 s. Drive `_run_forever` at fake 20:00 (fake clock aligned to the child's wall clock) with the real `resolve_lock_holder_pid` and `find_adopted_node_log`; `find_node_pid` is injected as in ct02. Assert the mark, zero spawns, and an unchanged child pid.
- T14b `test_real_flock_restart_at_1650_and_1655_adopts_without_spawn` (S6). The same real child; fresh `_run_forever` at fake 16:50:00 and, separately, 16:55:00. Assert `launch_adopted_live_node`, `spawn` called 0 times, the child pid unchanged and still the flock holder, and (at 16:55) readiness latched by RELAUNCH_CHECK.
- T18 `test_real_live_pid_not_holding_flock_is_never_marked`, mirroring ct02 `:242`.
- T18b `test_pid_to_log_binding_selects_only_this_childs_log` (SL1: the real guarantee behind check 9). Real child process, real `find_adopted_node_log`, real `/proc/<pid>` ctime, `tmp_path` log dir. (a) A D−1-stamped node log with fresh-looking `SHADOW_DECISION` lines whose mtime is set (`os.utime`) to before the child started, plus the child's own log written after start → returns the child's log, and a full step run marks from the child's log only. (b) Only the pre-start log exists → `None` → `LOG_UNKNOWN` (counted), no mark. (c) The supervisor's own `breezy-trade-supervisor.log` and its `-stdout-`/`.launch-` variants, touched after start → never returned. (d) `/proc/<pid>` unreadable (child reaped before the call) → `None`.

**Contract pin**
- T19 `test_liveness_marker_is_pinned_to_real_emitter`. In the ct08 style: `LIVENESS_POSITIVE_MARKER` is a prefix of the f-string literal in `_emit_shadow_decision`'s source (`inspect.getsource`, read as text), and `evaluate_snapshot`'s source calls `_emit_shadow_decision` unconditionally (no `if` between the `evaluate(...)` result and the call). It also asserts `"book level(s) discarded so far"` is **not** a liveness marker (SM3). A reworded or newly gated emitter therefore fails this test rather than silently disabling the mark.

**Unchanged and must stay green (cited, not edited):** `test_trade_supervisor.py:2100-2150`, `:2947`, `:3939`, `:3958`, `:5428`, `:6244-6470`, `:6777`, `:6803`, `test_ct02_*`, `test_ct13_*`, `test_ct08_*` (gains T19 only if it is placed there; otherwise untouched), `test_trade_supervisor_unit_directives.py` (KillMode pin).

**Gate (all required, read the EXIT code before any push):**
- Full gate, exact command, from the tree root: `scripts/ci/run_tests_no_egress.sh`. Through the project interpreter only; never `uv run`/`uv sync`/`pip` (shared venv).
- Focused (inside the gate's interpreter): `tests/unit/test_trade_supervisor_core.py tests/unit/test_trade_supervisor.py tests/unit/test_ct14_supervisor_restart_anytime.py tests/unit/test_ct02_supervisor_adopt_real_child.py tests/unit/test_ct13_supervisor_crash_readopt.py tests/unit/test_ct08_supervisor_contract_surface.py tests/unit/test_alert_egress.py`.
- Import contracts, exact command, run with the CWD at the tree root (it reads `pyproject.toml` from CWD; `python -m importlinter` is a no-op): `lint-imports`. Required output: the line `N kept, 0 broken`. In a worktree, set `PYTHONPATH` to the worktree's `src`.
- `ruff` and `mypy` clean on the touched files. Core stays stdlib-only. The marker is a string literal in core; core never imports the adapter or the strategy, and T19 reads the emitter's source as text. T16c imports `httpx`/`health` in the **test** only; the supervisor shell already imports `health`.

---

## §5 File-by-file changes

| File | Change | Size |
|---|---|---|
| `src/breezy/runtime/trade_supervisor_core.py` | Add `LIVENESS_POSITIVE_MARKER`, `LIVENESS_MAX_AGE_NS`, `LIVENESS_SCAN_MAX_OCCURRENCES`, `READY_ADOPTION_WARN_POLLS`/`_CRITICAL_POLLS`/`_CRITICAL_REFIRE_POLLS`, `latest_liveness_line_ns`, `ReadyAdoptionVerdict`, `is_deferral`, `decide_ready_adoption`, `decide_ready_adoption_alert`, the five recorders and `node_log_spawned_at`. Move `_NODE_LOG_NAME_RE` here with one capture group (pinned literal, §2.1). Add the four `DaySchedulerState` fields; extend `record_child_adopted`'s `replace`; add one additive projection to `latch_log_facts`. Add 2 `AlertDetail` members. | ~150 lines |
| `src/breezy/runtime/trade_supervisor.py` | Re-import `_NODE_LOG_NAME_RE`. Add `_ready_adoption_step`. Make the 3-line wiring change in `_do_permit_watch`'s in-window branch. **No new port.** | ~60 lines |
| `tests/unit/test_trade_supervisor_core.py` | T1–T7e | new tests only |
| `tests/unit/test_trade_supervisor.py` | T8–T16c (incl. T10b, T10c, T11d, T14c) | new tests only |
| `tests/unit/test_ct14_supervisor_restart_anytime.py` | T14b, T17, T18, T18b (new file) | new |
| `tests/unit/test_ct08_supervisor_contract_surface.py` | T19 (new test; existing tests untouched) | new test only |
| `deploy/systemd/README.md` | Replace the "restart only 01:00–16:40Z" guidance with: restart any time; verify `restart_adopted_ready_node` (in window), or `stop_prior_*`/`launch_adopted_live_node` (launch window); a `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED` page means MIDDAY_WATCH is not restored (expected on a node without the FQ family, or a D−1 node); alerts are logged locally and the webhook is best effort. | doc |
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
- The adopted rule is a **threshold proof on a pinned positive line**, requiring a line no older than 600 s. (r2 sized this against the depth ∪ SHADOW union, 3× its 198.7 s max. r3 narrows the marker to `SHADOW_DECISION` alone and re-measures it below: 600 s is ≥ 39× its 15.1 s max.)
- (r2 text, superseded by the r3 measurement and merge-blocking item below.) The PR records a re-run of `gaps_signal.py` over the 7 days preceding merge.

### Stage 0 r3: re-measurement split by signal source (SM3, run 2026-10-03 ~16:40Z)

**Method.** `gaps_by_source.py` (Appendix A; scratchpad `…/scratchpad/suprestart/gaps_by_source.py`, output `gaps_by_source.json`) streams the same 11 node logs read-only, niced, under a 2 GB `ulimit -v`. Per log and per signal it records the count, the largest in-window gap and its instant. A series resets outside [17:10, 01:00) and never spans two logs, so a relaunch is never counted as a gap.

| Node log (spawn) | Trading day | `SHADOW_DECISION` n in window | `SHADOW_DECISION` max gap | depth-truncation max gap (dropped marker, for contrast) |
|---|---|---|---|---|
| 20260926T165018Z | 09-26 | **0** (no FQ) | — | 198.7 s |
| 20260927T165036Z | 09-27 | **0** | — | 100.9 s |
| 20260928T165022Z | 09-28 | **0** | — | 182.2 s |
| 20260929T165048Z | 09-29 | **0** | — | 121.4 s |
| 20260930T165014Z | 09-30 | **0** | — | 87.6 s |
| 20261001T151202Z, 20261001T160158Z | (pre-16:40 hand launches) | 0 | — | — (no in-window lines) |
| 20261001T165011Z | 10-01 | 786 712 | **14.7 s** (10-02 00:48:11Z) | 49.1 s |
| 20261002T165039Z | 10-02 (to 20:05Z relaunch) | 206 765 | **11.6 s** | 25.3 s |
| 20261002T200526Z | 10-02 (20:05→20:55Z) | 68 741 | **9.4 s** | 33.2 s |
| 20261002T205521Z | 10-02 (20:55Z→01:00Z) | 503 253 | **15.1 s** (10-02 21:14:05Z) | 29.9 s |

**Honest statement of the evidence (coordinator ruling).** `SHADOW_DECISION` exists on **3 FQ days** in the sense of calendar dates 10-01 → 10-03, which is **2 trading days** (D = 10-01 and D = 10-02) and **4 node spawns**. Its in-window max gap is **15.1 s**; `LIVENESS_MAX_AGE` = 600 s is a **≥ 39× margin** (600 / 15.1 = 39.7). The first `SHADOW_DECISION` appears ~6 s after spawn (20:05:26 → 20:05:32; 20:55:21 → 20:55:27), which bounds C7's post-boot wait. The sample is small; the margin is what compensates for it. **5 of the 7 trading days had no FQ family**, and on those days a restart would have produced `NO_FRESH_ACTIVITY` → WARN → CRITICAL (re-fired) and no mark. That is the honest fail-loud behaviour, named as residual R2, not a defect to engineer around in this plan.

**Merge-blocking PR checklist item (SM3).** The PR description must contain, and the merge is blocked until it contains:
- [ ] The output of Appendix A's script re-run over every node log spawned in the **7 trading days preceding merge**, tabulated **per log and per signal source** as above.
- [ ] For every log with in-window `SHADOW_DECISION` lines: the max gap. **If any max gap exceeds 300 s** (half of `LIVENESS_MAX_AGE`), the merge stops: `LIVENESS_MAX_AGE_NS` is raised with the data in the same PR and re-reviewed, never silently.
- [ ] The count of trading days in that span **without** `SHADOW_DECISION` (no FQ family composed), stated as "a restart on such a day pages and does not restore MIDDAY_WATCH".
- [ ] Confirmation that the production node at merge time composes the FQ family (its log has `SHADOW_DECISION` lines), so the activation restart (§7) is expected to mark.

### Risks and residuals

- **R1. False MARK leads to MIDDAY_WATCH acting on the wrong node.** It needs every goal-4 proof on one poll, including a fresh flock-holder match, a current-day stamp, the anchor, and a pinned data line ≤ 600 s old. Even then, a false MARK can only make MIDDAY_WATCH relaunch a *dead* tracked child under the A-1 ceiling (≤ the day's first boot). Severity is low; T1/T7/T10/T11/T11b/T18 cover it.
- **R2. Single-marker dependence (C11, SM3).** The mark needs `SHADOW_DECISION`, i.e. the FQ family composed and at least one instrument reaching `evaluate_snapshot`. A node **without the FQ family never marks** (5 of the 7 measured trading days were like that). After a restart on such a day the step pages (WARN at 5, CRITICAL at 12, re-fired hourly) and MIDDAY_WATCH is not restored. That is honest fail-loud behaviour, the duty is no worse than today, and the page names the cause (`reason=no_fresh_activity` in the `ready_adoption_deferred` decision line). The remedy, if a non-FQ family becomes the production family, is a separate plan: a Breezy-owned periodic INFO line from a Nautilus clock timer in that strategy (a native extension). It is deliberately not built now (coordinator ruling; YAGNI). T19 makes a silent rewording or gating of the emitter impossible.
- **R3. CT13.** One extra `/proc/locks` read per poll, only until the MARK. The fail direction is "defer"; persistent deferral now pages (S3). If CT13 recurs, the PROGRESS row's planned `locks_path` fault-injection applies to T9 as well.
- **R4. Bounded budgets reset on restart.** `relaunch_attempts`, `midday_relaunch_attempts` and the boot-retry counters restart at 0 (true today). Worst case is up to 3 extra mid-day attempts per restart, never concurrent, each A-1-capped. Out of scope. `permit_capability_valid` may classify a ceiling lapse as LAPSED rather than EXPIRED_AT_CEILING after a restart (a classification-only page difference).
- **R5. Booting child adopted mid-relaunch (C7).** B1 may page ABSENT before the permit line appears. This is pre-existing and fails loud.
- **R6. FU-17 boot-retry counters are not re-latched on restart** (R4 class).
- **R7. Clock.** `now_ns` and `now` come from one clock read; windowing uses full datetimes. The line timestamps are node-written on the same host clock, and an NTP step of ≤ seconds is immaterial against 600 s. A node clock *ahead* of the supervisor makes the age negative, which is treated as fresh; that is acceptable because both read the same host clock.
- **R8. Replay cap.** The byte-0 replay reads ≤ 2 MiB and then resumes at EOF (`read_from_start_and_mark_consumed` sets the offset to the file size); on large logs the boot lines are within it (the permit is line 2), and the fresh `SHADOW_DECISION` line comes from the next incremental delta (C3 poll 2). The mark is then at most one poll later. T14c pins the cap, the resume-at-EOF and the carry fragment on the real reader (SL1).
- **R9. Off-box delivery is best effort (SH1).** A webhook outage during a deferral is visible only in the supervisor log (`alert sink failed to emit …`); the hourly re-fire retries it. A delivery-proof mechanism is out of scope by ruling.
- **R10. Out-of-scope observation (not acted on).** `check_alerts_cli` (`check_alerts_cli.py:122-157`) maps a raise from `sink.emit` to "NOT DELIVERED", but the production `resolve_alert_sink` returns a `TeeAlertSink`, which never raises; its 500-receiver test (`tests/integration/test_alert_webhook_delivery.py:208-221`) injects its own sink via `sink_factory`. Whether the operator probe can report "delivered" through the default Tee on a failing webhook is unverified here and is flagged to the coordinator for a separate backlog row.

---

## §7 Activation

1. Merge into `feat/data-capture-and-risk` after a green full gate (read the EXIT code before any push).
2. **Activate immediately, at any UTC instant** ("activate-code-immediately"). r1's "wait for 17:10Z if merged in [16:30, 17:10)" hold is **dropped** (S5). This change exists so a restart is safe at any instant, the sweep (T14) and the real-flock restarts at 16:50/16:55 (T14b) prove the launch window, and a hold contradicts the goal. No measurable condition gates activation beyond the green gate.
3. `systemctl --user restart breezy-trade-supervisor`. No daemon-reload; the unit is unchanged.
4. Verify:
   - the node pid and elapsed time are unchanged (`ps -o pid,etimes`);
   - `supervisor_started revision=<merge sha>`;
   - in [17:10, 01:00): `permit_watch_adopted_live_node`, then `restart_adopted_ready_node liveness_age_s=…` within 2 polls, then a MIDDAY_WATCH dispatch line on the next iteration;
   - no `TRADE_SUPERVISOR_*` CRITICAL and no `READY_ADOPTION_DEFERRED` (check the supervisor log, not only the webhook receiver: off-box delivery is best effort);
   - the node log has `SHADOW_DECISION` lines in the last 600 s (if the FQ family is not composed, the expected outcome is a page, not a mark; R2);
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

**Hard invariants, restated (binding on every implementer brief):**
- Nautilus Trader is unmodified: no patch, fork, bypass or reimplementation. Node log lines are only read.
- `allow_short` stays `False`. Nothing in this plan touches it.
- Never weaken or delete a safety, settlement or contract test to go green. Additions to reset-set/enum-set expectations are additive only.
- Never assign a value to an operator-reserved cap (max daily budget, max per position).
- Never touch live-trading enablement (`BREEZY_*_ENABLED`, permit minting/TTL, the A-1 ceiling env) or the NO-SEND execution-egress firewall. T16c uses an in-process `httpx.MockTransport`; no socket is opened.
- **The ready-adoption step never spawns or signals the node.** Its only port calls are `process_alive`, `resolve_intent_lock_holder` and `ports.alert_sink`; T14 asserts from the port call log that `spawn`/`terminate_after_recheck` are never called on its behalf.

---

## §R2 Disposition (merged review r1 → r2)

*Historical, kept verbatim from r2. Where it conflicts with r3 (the two-marker set, "seven" deferrals, "observable delivery", one-shot CRITICAL), §R3 and the body above govern.*

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

---

## Appendix A: SM3 measurement script (verbatim, read-only, run 2026-10-03)

Run from `~/.local/share/breezy/logs` with `ulimit -v 2000000; nice -n 15 python3 gaps_by_source.py <node logs…>`. It only reads; it imports nothing from the repo and needs no venv. Node-log selection is by name (`^breezy-trade-\d{8}T\d{6}Z\.log$`) and spawn stamp.

```python
"""SM3 r3: in-window [17:10,01:00) gaps split by signal source, per node log. Streaming, bounded."""
import re, sys, os, datetime as dt, json
ANSI=re.compile(rb'\x1b\[[0-9;]*m')
NT=re.compile(rb'^(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)\.(\d{9})Z ')
SIG={"shadow":b"SHADOW_DECISION ","depth":b"book level(s) discarded so far"}
out={}
for f in sys.argv[1:]:
    name=os.path.basename(f); r={k:{"n":0,"max_gap":0.0,"at":None,"first":None,"last":None} for k in SIG}
    last={k:None for k in SIG}
    with open(f,'rb') as fh:
        for raw in fh:
            head=ANSI.sub(b'',raw[:300]); m=NT.match(head)
            if not m: continue
            t=dt.datetime.fromisoformat(f"{m.group(1).decode()}T{m.group(2).decode()}").replace(tzinfo=dt.timezone.utc)
            mm=t.hour*60+t.minute; inw=(mm>=17*60+10) or mm<60
            for k,p in SIG.items():
                if not inw: last[k]=None; continue
                if p not in head: continue
                ts=t.timestamp()+int(m.group(3))/1e9; s=r[k]; s["n"]+=1
                if s["first"] is None: s["first"]=f"{t:%m-%dT%H:%M:%S}"
                s["last"]=f"{t:%m-%dT%H:%M:%S}"
                if last[k] is not None and ts-last[k]>s["max_gap"]:
                    s["max_gap"]=round(ts-last[k],1); s["at"]=f"{t:%m-%dT%H:%M:%S}"
                last[k]=ts
    out[name]=r
print(json.dumps(out,indent=1))
```

Limitation, stated: the marker must appear in the first 300 bytes of the line (true for every `SHADOW_DECISION` line, whose marker follows a ~70-byte prefix).

---

## §R3 Disposition (merged review r2 → r3)

| Item | Coordinator ruling | Disposition | Where |
|---|---|---|---|
| **SH1** [HIGH SFH / MED TBA] delivery claim false | Correct the claim; re-fire CRITICAL every 60 polls until mark/terminal; test with real `TeeAlertSink` + failing webhook; no new mechanism; cite a delivery-proof helper only if shipped | **Applied.** Verified: `_send_permit_alert` (`:958-974`) returns `False` only on a raise; `TeeAlertSink.emit` (`health.py:366-369`) contains each branch via `emit_alert` (`:479-510`), so production always returns `True`. Claim now reads "logged locally; webhook best effort" everywhere it appeared (§0 goal 3, §1, §2.4, §5 README row, §7). New `READY_ADOPTION_CRITICAL_REFIRE_POLLS` = 60; `ready_adoption_critical_sent: bool` → `ready_adoption_critical_last_poll: int | None`, cleared on MARK/terminal/new child/rollover. T7d (re-fire arithmetic), T16c (real Tee + real `WebhookAlertSink` on `httpx.MockTransport` 503: local line at 12/72/132, ERROR line per send, 4 webhook attempts, latch set despite failure). Helper search: `deliver_with_proof`/`outbox`/`AlertOutbox`/`delivery_proof` → zero hits in `src/`; `check_alerts_cli` is an operator one-shot, not an in-loop helper. Nothing built. | §0, §1 rows "Alert path"/"Delivery-proof helper", §2.1 fields, §2.4, §4 T7d/T16b/T16c, §6 R9/R10 |
| **SM1** [MED SFH] `LOG_NOT_CURRENT_DAY` unpaged after restart | Count as a deferral → WARN → CRITICAL | **Applied.** Moved into the deferral set (eight members). Root cause verified: `next_due` dispatches STOP_PRIOR only in [16:40, 16:50) (`core:1102-1103`), and B1 sees a D−1 node with an unexpired permit as `VALID`. C6 rewritten. T1 (`is_deferral` over the enum), T7e (pure), T10c (shell, real scheduler, `spawn`/`terminate` 0). | §2.1 enum + check 8, §2.4, §3 C6, §4 T1/T7e/T10c |
| **SM2** [MED SFH] deliberately unarmed node | Terminal `NOT_REQUIRED` matching B1, with a test | **Applied.** Check 5: permit `None` and `orders_not_requested_seen` → `NOT_REQUIRED` (terminal, not counted), in `permit_capability_valid`'s own order (`core:1593-1605`), so the step and B1 agree. Parity argued: `readiness_observed(...)` needs a permit, so an un-restarted supervisor never restores MIDDAY_WATCH for an unarmed node either. New row C12. T1 (incl. "permit latched wins"), T10b (200 polls: no step alert, B1's one WARN unchanged, no mark/spawn/signal). | §2.1 enum + check 5, §2.4, §3 C12, §4 T1/T10b |
| **SM3** [MED both] liveness marker | `SHADOW_DECISION` only; drop depth; honest evidence (3 FQ days, 15.1 s, ≥ 39×); non-FQ never marks → paged, named residual; PR re-measurement split by source is merge-blocking | **Applied.** `LIVENESS_POSITIVE_MARKERS` (2-tuple) → `LIVENESS_POSITIVE_MARKER = "SHADOW_DECISION "`. Emitter re-verified (`strategy.py:564`, `:577-581`, `:713-770`; unconditional, not permit-gated). Depth WARN rejected with the reason (`data.py:1873`, `should_warn_at_count` `:555-561`). Re-measured by source (§6 Stage 0 r3): SHADOW max gaps 14.7 / 11.6 / 9.4 / 15.1 s over 4 spawns = 2 trading days (calendar 10-01 → 10-03); 5 of 7 days had no FQ family. 600 / 15.1 = 39.7×. R2 and C11 rewritten as the fail-loud residual. Merge-blocking checklist with a 300 s stop rule; script in Appendix A. T7b/T11d/T17/T19 updated to the single marker. | §1, §2.1, §3 C1/C3/C11/D1, §4 T7b/T11d/T17/T19, §6 Stage 0 r3 + R2, Appendix A |
| **SL1** [LOW] (a) last parseable occurrence | Bounded scan | **Applied.** Backwards scan over ≤ 64 occurrences; first parseable wins; else `None`. Motivated by a verified headless `SHADOW_DECISION` fragment at a byte-offset tail of the live log. T7b cases (i)–(iv), T14c(c). | §2.1, §4 T7b/T14c |
| **SL1** (b) check 9 vacuous | State the real guarantee; test the binding | **Applied.** Check 9's spawn-stamp clause is kept as a guard but declared vacuous; the real guarantee is the pid→log binding (`find_adopted_node_log` `:814-846`, mtime ≥ `/proc/<pid>` ctime) plus the per-child latch reset plus the single flock holder. T18b tests the binding with a real child (pre-start log excluded, supervisor logs excluded, reaped pid → `None`). | §0 goal 4, §2.1 check 9 + stamp paragraph, §4 T18b |
| **SL1** (c) T14 on real reader | Real `IncrementalLogReader` incl. `read_from_start_and_mark_consumed`, 2 MiB cap and carry | **Applied.** T14's ports bind a fresh real reader per run exactly as `default_ports` does (`:1105-1117`), over real files. T14c adds the 3 MiB cap case (bytes 2–3 MiB skipped, resume at EOF), the carry-fragment case and the partial-write case. | §4 T14/T14c, §6 R8 |

**r1 regression check (each r1 item re-read against r3):**
- S1 (proof of liveness): still a pinned positive line from code, now one line; same-poll `expires_at_ns > now_ns` re-check unchanged (check 5, T10 variant); retry loop and lapsed permit never mark (C5, C10, T10, T11). **Held.**
- S2 (measure, STOP gate, cadence): r2's measurement kept; r3 adds the by-source run and a merge-blocking re-run; cadence text unchanged. **Held, strengthened.**
- S3 (deferral alerting, dedupe per child, OSError logged and counted): unchanged except the CRITICAL now re-fires and the delivery claim is corrected; `IO_ERROR` still logged each occurrence and counted. **Held.**
- S4 (anchor before mark, T15 variants): unchanged. **Held.**
- S5 (no activation hold): unchanged; §7 adds a pre-check of `SHADOW_DECISION` presence, which is a verification, not a hold. **Held.**
- S6 (real scheduler, real flock at 16:50/16:55): unchanged; T14 now also uses the real reader. **Held, strengthened.**
- LOWs (rollback window, `_NODE_LOG_NAME_RE` identity, STOP alert path): unchanged. **Held.**

**Self-score (planner): 95/100.** The residual deductions:
- R2: liveness depends on the FQ family; non-FQ days page instead of mark, by ruling. The evidence base is 2 trading days (4 spawns), which the 39× margin and the merge-blocking re-run only partly offset.
- R9: off-box delivery stays best effort by ruling; re-fire is mitigation, not proof.
- T14's process/flock layer is still a fake; only T14b/T17/T18/T18b touch real `/proc`.
