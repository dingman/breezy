# AUD-14 — Classify every supervisor restart, and stop a multi-day self-check FAIL from being invisible

## 1. ID and actionable title

**AUD-14** — Resolve G-13's UNVERIFIED restart motive with journal-vs-commit evidence, then
close the two defects the evidence actually exposes: (a) the supervisor records no build
revision, so a restart's motive is unrecoverable after the fact; (b) a 17:05Z self-check that
FAILs day after day alerts at WARN once per day and never escalates — it ran **seven
consecutive days** unnoticed.

## 2. Source finding and class

- **Gap:** G-13 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:87-90`). Verdict **FALSE**
  for hands-off operation; **motive UNVERIFIED** (agent-reported).
- **Class:** **autonomous-operation failure**, with a **verification gap** on the motive.

**Evidence collected read-only for this plan (2026-09-21).** The brief required evidence
first; here it is, and it changes the item.

**All seven Stopped→Started cycles, from `journalctl --user -u breezy-trade-supervisor.service`,
each correlated against `git log` on `src/` and `deploy/`:**

| # | Restart (UTC) | Nearest preceding commit | Δ | Classification |
|---|---|---|---|---|
| 1 | 2026-09-10T16:43:56 | `cd3f8e8` 16:43:10 docs(evidence) | 46 s | deploy-adjacent (weak — a docs commit) |
| 2 | 2026-09-12T01:24:03 | `7938032` 01:24:03 `deploy(supervisor): CUT to pm_us_crh_cont` | **0 s** | **deploy-driven** |
| 3 | 2026-09-12T01:37:20 | `a858b93` 01:37:12 v3-aware self-check | 8 s | **deploy-driven** |
| 4 | 2026-09-15T15:06:58 | `eed0f4c` 15:06:40 merge mid-day relaunch | 18 s | **deploy-driven** |
| 5 | 2026-09-19T04:01:44 | `a115691` 04:00:41 fix(venue) bonusHold | 63 s | **deploy-driven** |
| 6 | 2026-09-19T04:20:17 | `fbc5eea` 04:19:33 merge WP-11b | 44 s | **deploy-driven** |
| 7 | 2026-09-20T15:26:18 | `e3e8ac6` 15:26:04 open `pm_us_crh_v4` at θ=0.0695 | **14 s** | **deploy-driven** |

Every cycle is a clean `Stopping` → `Stopped` → `Started` (an operator `systemctl --user
restart`), with **no `Main process exited`, no `Failed`, no crash line**, and every one lands
within **≤63 s of a commit**. **G-13's implied "recovery restarts" are not in evidence: 6 of 7
are unambiguously deploy-driven and the 7th is deploy-adjacent.** A deploy restart is
legitimate — but it is human intervention in a loop that claims to be hands-off, and nothing in
the system records that it happened or why. (Round-1 peer review independently reproduced this
table bit-for-bit, including the 0-second match on `7938032` and the 46-second gap on
`cd3f8e8`.)

**The self-check failures are a SEPARATE defect, and their cause is already fixed:**

```
2026-09-12T17:05:01Z  self_check result=FAIL_NODE_NOT_READY      <- alert WARN
2026-09-13T17:05:11Z  FAIL_NODE_NOT_READY
2026-09-14T17:05:07Z  FAIL_NODE_NOT_READY
2026-09-15T17:05:14Z  FAIL_NODE_NOT_READY
2026-09-16T17:05:09Z  FAIL_NODE_NOT_READY
2026-09-17T17:05:05Z  FAIL_NODE_NOT_READY
2026-09-18T17:05:05Z  FAIL_CHILD_EXITED
2026-09-19T17:05:33Z  PASS      <- after restart #6 deployed 1859498
2026-09-20T17:05:44Z  PASS
```

Commit `1859498` ("fix(wp0a): accept both rung-hold subscribe markers; reap the supervisor
child") is the fix, and its own message states the mechanism: `STRATEGY_SUBSCRIBED_MARKER`
named only `CurrentRungHoldStrategy` while the live family logs `ContinuousRungHoldStrategy
subscribed`, so `self_check` fell through `trade_supervisor_core.py:542-543` to
`FAIL_NODE_NOT_READY`; readiness was never observed, `next_due` never entered `MIDDAY_WATCH`,
and `_do_launch` discarded the spawn `Popen` so `waitpid` never ran — a killed child sat
`<defunct>`, which is `FAIL_CHILD_EXITED` on 09-18.

**Correction to that commit message, from this plan's own journal read:** it says the FAIL ran
"since 2026-09-15". The journal shows **2026-09-12T17:05:01Z** — three days earlier, consistent
with `7938032` (the `pm_us_crh_cont` cut) landing at 09-12T01:24. The diagnosis window in the
commit message is understated; the fix is still correct. **The one link still unverified — when
`ContinuousRungHoldStrategy subscribed` first appeared in a node log — is promoted from a §13
confession to a §7 step so it is closed, not disclosed.**

## 3. Current behaviour, required behaviour, concrete gap

**Current.**
1. Deploying a supervisor/node change requires a human to `systemctl --user restart` the unit.
   Nothing records that a restart happened for a deploy, or which revision is now running:
   `supervisor_started` logs `stop_prior_utc/launch_utc/self_check_utc/lock_path/log_dir` and
   **no build identity at all**.
2. A self-check FAIL emits exactly one alert per day at `severity="WARN"`
   (`trade_supervisor.py:1300-1302`, `event="TRADE_SUPERVISOR_SELF_CHECK_FAIL"`). Seven
   consecutive daily FAILs produce seven identical WARNs and no escalation. Until `f97c26f`
   (09-20) every one of them went to a log file nobody reads.

**Required.**
1. Every restart is attributable after the fact: the supervisor logs the revision it is running
   at start, so "which build is live, and did it change at that restart?" is answerable from
   the journal alone.
2. A self-check FAIL that **repeats** is CRITICAL, not a seventh WARN. Repetition is the signal
   that distinguishes a transient boot race from a structural break.
3. The escalation survives a supervisor restart, and a gap in the self-check series is itself
   visible.

**Concrete gap.** One missing log field, and one missing consecutive-failure counter.

## 4. Priority, rationale, dependencies, execution order

**Priority: 14a = P3, 14b = P1.**

- **14a (evidence + revision line)** is P3: the evidence half is already done in §2; the
  remaining code is one INFO field. Low value, near-zero risk.
- **14b (repeat-FAIL escalation)** is **P1**. A readiness FAIL ran seven days. It was detected
  every single day and it changed nothing. That is the exact failure shape recorded in memory
  as *"a detector without delivery is not a control"* — and the delivery half was fixed on
  09-20 by `f97c26f`, which means the **severity and repetition half is now the only remaining
  hole**. It is also the cheapest remaining item in this cluster.

**Dependencies.** 14b depends on the alert egress shipped in `f97c26f` (**already merged**, so
it is satisfied, not blocking). No dependency on any other AUD id. AUD-15 shares the
"a failing unit must alert" theme but touches different units and is independently actionable.
AUD-16b adds a family-id line to the **node**; 14a adds a revision field to the **supervisor** —
different process, different file, different test module, and neither blocks the other.

**Execution order:** 14a evidence (done) → 14b → 14a code.

## 5. Scope and explicit exclusions

**In scope:**
- **AUD-14a** — the restart-classification evidence doc (§2 promoted to `docs/evidence/`), plus
  ONE new field on the existing `supervisor_started` line carrying the running revision.
- **AUD-14b** — a consecutive-FAIL counter held in **its own store-backed record**, NOT on
  `DaySchedulerState` (§6 names the mechanism and why the round-2 design was wrong), a CRITICAL
  alert on the second and subsequent consecutive FAIL, survival across **both** a trading-day
  rollover and a supervisor restart, and — added this revision — a specified, tested fault path
  for the counter's own persistence in which **only a genuinely absent key may start at zero
  silently**; a corrupt value, a read failure and a write failure each alert under their own
  fixed event and each fail toward alerting rather than toward a silent reset (§6, §9).

**Explicitly excluded:**
- **Automating the deploy restart.** A deploy restart is a human decision about which revision
  runs live; making it automatic is a change to live-trading enablement posture and is NOT a
  build-side call. Out of scope, named as such.
- Any change to the permit TTL, to the mint site, or to `LAUNCH_UTC`/`STOP_PRIOR_UTC` — those
  are POST_FORECAST_PHASE work packages **B1/B3** and remain theirs. In particular, AUD-14 must
  not introduce a second permit mint (`AMENDMENT A-1`).
- Any change to `self_check`'s decision ladder (`trade_supervisor_core.py:534-553`). 14b adds an
  escalation on top of the result; it never reclassifies a result.
- Re-fixing the marker/reap defect. `1859498` already did, and two consecutive PASS days
  (09-19, 09-20) are the evidence.
- The `PASS_ADOPTED_LOG_UNKNOWN` fail-open at `:540-541`. Real, but it is
  POST_FORECAST_PHASE `AMENDMENT A-2`'s subject, not AUD-14's.
- **A detector for the self-check never running at all** (the unit or timer itself stopped).
  Real residual, and deliberately NOT absorbed: the supervisor cannot observe its own absence.
  14b closes the cheap half of it — the persisted record carries the last self-check UTC, so
  the *next* self-check can report the gap — but a true dead-man's switch belongs with the
  supervisor's watch-window work (`AMENDMENT B-4`, which already established the watch window
  closes at 01:00Z while the permit lapses at 02:50Z). Named here with its owner, not solved.

## 6. Proposed changes grounded in inspected code

**Native mechanism.** None applicable — the supervisor is a Breezy-owned process outside the
Nautilus kernel (the null-hypothesis check is not engaged because Nautilus provides no process
supervisor: `TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md:19-22` already recorded the search —
`kernel.py` has no `restart`/`reschedule` hook and `TradingNode.run()` returns `None`).
Alerting reuses the existing `breezy.runtime.health` sink (`AlertPayload`/`emit_alert`/
`resolve_alert_sink`), which the supervisor already imports at `trade_supervisor.py:44-50` and
already uses at CRITICAL severity in five places (`:883, :975, :993, :1177, :1527`).

**14a — revision on `supervisor_started`.**
`log_decision` (`trade_supervisor.py:685-693`) accepts `int | str` fields only and its docstring
binds it: *"never an exception object, never an environ mapping, never anything that could
carry a value from the seven operator-reserved controls."* A revision string is a static build
identifier and satisfies that contract. Source of the value, in order of preference:
1. a `BREEZY_BUILD_REVISION` env var if the launch shell exports one; else
2. `importlib.metadata.version("breezy")` if it carries one; else
3. the literal `"unknown"`.
**It must never shell out to `git`** — the supervisor is long-lived, unattended, and
`subprocess` on a repo it does not own is a new failure surface for zero benefit. Absence is
reported as `revision=unknown`, never omitted.

**What the field does and does not answer (stated so no reader over-reads it).** It records
**what** is running, never **why** the restart happened. The supervisor observes that it was
started; it cannot observe whether systemd was asked to restart it by a human deploying, by a
crash-loop, or by a boot. Motive is inferred *after the fact* by comparing consecutive
`revision=` values across restarts — a changed revision is deploy-driven, an unchanged revision
is not — which is exactly the inference §2 had to make by hand from commit timestamps, now
made from the journal alone. A field claiming to name the trigger would be attributing a cause
the process cannot know, and is deliberately not added.

**14b — repeat-FAIL escalation.** Every name below is literal, not descriptive.

- **Where the counter lives — DECIDED, with the mechanism named. It does NOT go on
  `DaySchedulerState`.** Revision 2 put it there, required `_for_day` not to reset it, and in the
  same breath required the new reducer to match the `record_*` family "exactly" — two
  instructions that contradict each other. Round-2 review was right; the design is changed, not
  defended. Read at HEAD (`trade_supervisor_core.py:674-678`):

  ```python
  def _for_day(state: DaySchedulerState, day: dt.date) -> DaySchedulerState:
      """Return ``state`` unchanged if it already belongs to ``day``,
      otherwise a fresh state for ``day`` -- the day-rollover reset, applied
      consistently by every function in this section."""
      return state if state.day == day else initial_scheduler_state(day)
  ```

  `initial_scheduler_state(day)` is `return DaySchedulerState(day=day)` (`:670-671`) — every
  other field reverts to its dataclass default. `record_readiness_observed` (`:820-822`) is the
  family's shape: `effective = _for_day(state, _trading_day(now_utc))` then
  `replace(effective, <field>=...)`. **Two independent facts make a `DaySchedulerState`-resident
  counter unworkable, and either alone is fatal:**
  1. `_trading_day` (`:681-690`) rolls the trading day at `STOP_PRIOR_UTC` = **16:40Z**, and the
     self-check runs at **17:05Z**. Every consecutive pair of daily self-checks is therefore
     already on opposite sides of a rollover — the 09-12..09-18 sequence crosses **seven** of
     them, so the flagship replay test (§7 14b step 5) is the test the defect defeats first.
  2. Even a rollover-safe reducer would be undone one line later: the poll loop calls
     `mark_phase_fired(state, phase, now)` at `trade_supervisor.py:1496`, immediately after
     `_do_self_check` returns (`:1485-1495`), and `mark_phase_fired` (`:765-777`) re-runs
     `_for_day` on the same state.

  **Carrying the two fields forward inside `_for_day` was the alternative considered and
  REJECTED.** `initial_scheduler_state` has 47 call sites and `_for_day`'s reset is the
  documented, load-bearing contract every other sticky field in the class depends on ("applied
  consistently by every function in this section"). Special-casing two fields inside it would put
  a cross-day counter into a class whose own docstring defines it as "per-trading-day 'phase
  already fired' bookkeeping" (`:600-607`), and would make each of those 47 sites a place the
  carry-over has to be re-reasoned about. The counter is not per-day state and does not belong in
  a per-day type.

- **The chosen mechanism: a separate, store-backed record with its own pure reducer.**
  `DaySchedulerState`, `initial_scheduler_state`, `_for_day` and `mark_phase_fired` are **not
  touched at all**. Consequences, both deliberate: no other caller of
  `initial_scheduler_state`/`_for_day` can inherit unintended carry-over (the audit of "every
  other caller" therefore returns *none affected*, and §8 item 8 pins that with a `git diff`),
  and §9's "every existing supervisor test stays green byte-unchanged" holds by construction
  rather than by hope.
  - **New frozen dataclass** in `trade_supervisor_core.py`, beside the existing pure types:

    ```python
    @dataclass(frozen=True, slots=True)
    class SelfCheckEscalationState:
        consecutive_failures: int = 0
        last_self_check_utc: str = ""   # "" means never observed
    ```

    It carries **no `day` field**. Not being day-keyed *is* the mechanism.
  - **New pure reducer** in the same module — pure, no I/O, no clock, no `dt.date`:
    `def record_self_check_result(state: SelfCheckEscalationState, result: str, *, now_utc: str)
    -> SelfCheckEscalationState`. It increments `consecutive_failures` when `result` is a FAIL,
    resets it to `0` on `PASS`/`PASS_ADOPTED_LOG_UNKNOWN` (the members of
    `_SELF_CHECK_PASS_RESULTS`, `trade_supervisor.py:1193-1195`), and sets
    `last_self_check_utc=now_utc` on **every** result. It never calls `_for_day`. This is a
    deliberate, named deviation from "matches the `record_*` family exactly" — that instruction
    is withdrawn, because the `record_*` contract is the day-rollover reset and this field must
    not have one.
  - **Source of truth: the persisted store value, read fresh at every self-check — on boot, on a
    rollover, and after a restart alike.** The I/O shell `_do_self_check`
    (`trade_supervisor.py:1198-1207`, which already takes `store_path`) reads the key, decodes it
    into a `SelfCheckEscalationState`, applies the reducer, decides the severity from the
    returned `consecutive_failures`, and writes the new value back. This read-decide-write bracket
    around a pure reducer follows `read_continuous_family_store_state`'s existing
    fresh-connection pattern (`trade_supervisor.py:388-410`). Because the value is re-read every
    time, "boot", "trading-day rollover" and "process restart" collapse into the *same* case and
    none of them needs special handling — which is exactly why this shape was chosen over
    threading a second long-lived in-memory object through the loop. **That sentence is
    load-bearing and the failure path below honours it:** revision 3 paired it with a
    "process-local last-known value in a local variable" fallback, which is the same long-lived
    object by another name and cannot survive between two calls of a function the loop invokes
    fresh each poll. The fallback is **dropped** (§6's failure-handling block), not the rationale;
    `_do_self_check`'s signature and return tuple are unchanged as a result.
- `_do_self_check` (`trade_supervisor.py`, alert emitted at `:1299-1302`) keeps its existing
  WARN on the first FAIL, and emits `severity="CRITICAL"` with a distinct
  `event="TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"` once the counter is ≥ 2. A PASS (or
  `PASS_ADOPTED_LOG_UNKNOWN`) resets the counter to 0.
- `detail` stays a fixed enum string from `SELF_CHECK_ALERT_DETAIL`
  (`TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md:151-153` — the alert `detail` is a fixed enum,
  never exception text, never a value-bearing string). The consecutive count travels as an
  `int` field on the log line, never inside `detail`.
- **Persistence — the store key is literal, not described.** The counter must survive both a
  trading-day rollover (every consecutive self-check pair crosses one, above) and a supervisor
  restart — six of the seven observed restarts were deploys. It is persisted in the
  `SqliteStateStore` the
  supervisor already opens (imported at `trade_supervisor.py:52`; `get(key)`/`set(key, bytes)`
  at `sqlite_store.py:155,168`) under exactly:

  ```
  runtime:supervisor:self_check_escalation
  ```

  — colon-separated, matching `bootstrap_witness.py:82`'s `runtime:bootstrap_witness`
  convention and never tilde-separated (composite ids use `^`/`:`; a tilde breaks catalog
  queries). The value is a JSON object with exactly two keys,
  `{"consecutive_failures": <int>, "last_self_check_utc": "<iso8601Z>"}` — the two
  `SelfCheckEscalationState` fields by name, one-to-one, so encode/decode is total and needs no
  mapping table. No value-bearing field, nothing derived from an operator-reserved control.
- **Failure handling — EVERY failure of the escalation machinery itself fails TOWARD alerting.**
  This item exists because a detector ran seven days without reaching anyone; a counter whose own
  fault paths degrade to silence would reproduce that failure at the one point least likely to be
  noticed. Three load outcomes, never conflated, resolved by one helper in the shell —
  `_load_self_check_escalation(store_path) -> tuple[SelfCheckEscalationState, EscalationLoadOutcome]`,
  with `EscalationLoadOutcome` a new `(str, Enum)` in `trade_supervisor_core.py` beside
  `AlertDetail`:
  1. **`ABSENT`** — `store.get(key)` returned `None`. `SqliteStateStore.get`
     (`sqlite_store.py:155-166`) returns `None` for a missing key by contract, so this is the
     legitimate first-boot / first-deploy case. State = `SelfCheckEscalationState()`, and this is
     the **only** path permitted to start at zero **silently**: no alert, one field
     `escalation_state=absent` on the existing `self_check` log line. The count is *known*.
  2. **`CORRUPT`** — a value was **present** but did not decode into exactly the two declared keys
     (not JSON, not an object, a missing or extra key, a wrong scalar type). A present-but-
     undecodable value is a persistence **fault**, not an absence: on day 5 of a real FAIL streak
     it would otherwise silently reset `consecutive_failures=5` to zero and restart the clock,
     which is precisely the seven-day shape this item exists to kill. It **alerts through the
     existing sink** — `alert(ports.alert_sink, event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_
     STATE_CORRUPT", severity="WARN", detail=AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT)` —
     and the count is then treated as **UNKNOWN**, never as zero. The undecodable bytes are never
     logged, never measured, never placed in `detail`.
  3. **`UNAVAILABLE`** — opening the store or calling `get` raised. `sqlite_store.py:155-176` has
     no internal containment around its `sqlite3` calls, so this is reachable. It alerts as
     `event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE"`, `severity="WARN"`,
     `detail=AlertDetail.SELF_CHECK_ESCALATION_STORE_UNAVAILABLE`; the exception is caught at this
     helper alone, named by TYPE only in the log line (the module's value-free stance), and never
     propagates — the poll loop's control flow is unchanged. The count is **UNKNOWN**.
- **The state operand on a fault load, and what is written back — STATED, not left to the
  implementer.** On `CORRUPT` and on `UNAVAILABLE`, `_load_self_check_escalation` returns the
  **same `SelfCheckEscalationState()` default as `ABSENT`** as its state operand — nothing
  decodable exists, so no other value is available — paired with the fault
  `EscalationLoadOutcome` that keeps `count_known=False` downstream. The fault paths differ from
  `ABSENT` in what they *do* with that operand, never in the operand itself: `ABSENT` is silent
  and its count is **known**; a fault alerts and its count is **UNKNOWN**. **`store.set` IS
  attempted on both fault paths**, carrying the **reducer's output** — never the bare default,
  and never skipped — and a raise there is the `..._WRITE_FAILED` path below. (On `UNAVAILABLE`
  the write will usually fail too, so the load-fault WARN and the write-failure WARN are both
  emitted: two facts, two events, no conflation.)
  **Why the reducer's output and not the bare default — the three sequences reasoned through,
  against the binding rule that a write-back must never rebase the persisted count in a way that
  under-alerts on the NEXT poll:**
  1. **FAIL under a corrupt read, then FAIL.** The reducer turns the zero default into
     `consecutive_failures=1`, so **1** is persisted. This call has already escalated to CRITICAL
     through `count_known=False`; the next poll reads 1, increments to 2, and escalates **by
     count**. Persisting the pre-reducer **0** instead would make that next FAIL a *first* FAIL —
     a WARN where a CRITICAL is owed. That is precisely the under-alert this rule forbids, and it
     is why "write back the default" is rejected **by name**.
  2. **FAIL under a corrupt read, then PASS.** **1** is persisted; the PASS then resets it to
     **0** on the next poll. No escalation is owed after a PASS and none is emitted — the
     transient self-clears without a human clearing the key.
  3. **PASS under a corrupt read, then FAIL.** The reducer resets to `0`, so **0** is persisted.
     This *is* a rebase, and it is the one legitimate one: a PASS is a **directly observed**
     result saying the check passed now, which retires whatever streak the unreadable bytes may
     have held, exactly as a PASS against a readable store does. The following FAIL is then a
     genuine first FAIL and WARN is the correct severity. A zero written on the strength of an
     observed PASS is evidence; a zero written on the strength of an unreadable key is the
     silent reset this item exists to kill — only case 3 is the former.
  The rejected alternative — **skip the write and leave the corrupt bytes in place** — buys no
  alert coverage and costs operability: case 1 escalates either way (the next poll re-reads
  `CORRUPT` and forces CRITICAL again), but the key never self-heals, so the corrupt WARN repeats
  every day until a human clears it. Writing the reducer's output repairs the key inside the same
  poll at zero cost in coverage, and §7 step 4 asserts the persisted value in all three cases.
- **UNKNOWN escalates; it never silently resets. The round-3 contradiction is resolved by
  DROPPING the in-memory fallback — one design, stated to the signature.** The two options the
  round-3 architect named were (a) thread an explicit last-known `SelfCheckEscalationState`
  through `_do_self_check`'s signature/return and the `Phase.SELF_CHECK` call site, or (b) drop
  the fallback and make a store fault escalate. **(b) is chosen**, because (a) reintroduces the
  long-lived in-memory object this design's own rationale rejects, adds a fourth threaded value to
  a five-argument call site, and still degrades to zero on the first poll after a restart — the
  dominant real-world case (6 of 7 observed restarts were deploys). Concretely, therefore:
  - `_do_self_check`'s signature and return tuple are **UNCHANGED**:
    `def _do_self_check(*, ports, now, store_path, log_dir, tracked_pid, node_log, state=None) ->
    tuple[int | None, Path | None, DaySchedulerState | None]` (`trade_supervisor.py:1198-1207`).
  - The `Phase.SELF_CHECK` call site is **UNCHANGED**: `tracked_pid, node_log, new_state =
    _do_self_check(...)` at `trade_supervisor.py:1485-1493`, `if new_state is not None: state =
    new_state` at `:1494-1495`, `state = mark_phase_fired(state, phase, now)` at `:1496`. No new
    value is carried across polls, by design — that is the point of (b).
  - When the count is UNKNOWN **and the result is a FAIL**, the FAIL alert is emitted at the
    **escalated** severity: `severity="CRITICAL"`, `event="TRADE_SUPERVISOR_SELF_CHECK_FAIL_
    REPEATED"`, and `detail=` the store-fault detail (corrupt or unavailable) rather than
    `SELF_CHECK_ALERT_DETAIL[result]`, so a reader can tell an escalation-by-count from an
    escalation-by-unknown. A PASS under an UNKNOWN count emits the load-fault WARN only.
  - **Stated consequence, accepted deliberately:** a sustained store outage makes every FAIL a
    CRITICAL — the detector **over-alerts rather than suppresses**. Degrading to a silent zero
    (revision 3's naive reading, under which `consecutive_failures` could never exceed 1 while the
    store was down and the CRITICAL could never fire) is not acceptable and is explicitly rejected.
  - The severity decision is a **pure function** in `trade_supervisor_core.py`, unit-testable with
    no I/O: `def escalated_self_check_severity(*, result_is_fail: bool, consecutive_failures: int,
    count_known: bool) -> str | None` — `None` for a PASS result, `"CRITICAL"` when
    `result_is_fail and (not count_known or consecutive_failures >= 2)`, `"WARN"` otherwise.
- **Ordering inside the read-decide-write bracket: DECIDE → EMIT → PERSIST. Decided, with the
  loss/duplication analysis stated.** The bracket is: (1) load, (2) apply
  `record_self_check_result`, (3) resolve severity, (4) `alert(...)`, (5) `store.set(key, json)` —
  the write is **last**, after the alert call returns.
  - Under **persist → emit**, a restart or crash landing between the two **loses** that check's
    escalation outright: the count is advanced on disk, nothing was delivered, and no later run
    can tell that an alert was owed. Restarts are the dominant event here (6 of 7 observed were
    deploys, §2), so this is not a hypothetical interleaving.
  - Under **decide → emit → persist**, a failed or interrupted write leaves the stored count one
    behind; the next FAIL re-derives a count that can produce the **same** escalation again. That
    is a duplicate CRITICAL — noisy, visible, and recoverable — never a missing one.
  - **The chosen ordering can duplicate an escalation but can never lose one**, which is the only
    direction this item's genesis permits. Pinned by test (§7 14b step 4).
  - A `store.set` that raises is caught at the same helper boundary, logged with `error_type` only,
    and alerted once as `event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED"`,
    `severity="WARN"`, `detail=AlertDetail.SELF_CHECK_ESCALATION_STATE_WRITE_FAILED` — a **distinct
    event from the read-failure one**, so a write outage is never read back as a read outage. The
    alert already emitted is never retried, withdrawn or duplicated by the write failure itself.
- **Three new `AlertDetail` members**, appended to the closed enum at
  `trade_supervisor_core.py:191-224` after `MIDDAY_RELAUNCHED_CHILD_NOT_READY` (`:224`), each a
  fixed string carrying no value, consistent with that enum's own docstring (`:192-196`, "Never
  exception text, never a config/permit value"):

  ```python
  SELF_CHECK_ESCALATION_STATE_CORRUPT = "self_check_escalation_state_corrupt"
  SELF_CHECK_ESCALATION_STORE_UNAVAILABLE = "self_check_escalation_store_unavailable"
  SELF_CHECK_ESCALATION_STATE_WRITE_FAILED = "self_check_escalation_state_write_failed"
  ```

  `SELF_CHECK_ALERT_DETAIL` (`:280-296`) is **not** touched: it maps `SelfCheckResult` to a detail
  and the three new members are not self-check results.
- **Series-gap visibility (the cheap half of the excluded dead-man's switch):** when the stored
  `last_self_check_utc` is more than ~26 h before the current self-check, the result line
  carries a `self_check_gap_hours` int field. It does not alert by itself — the run that
  observes it is a run that happened — but it makes a missed day recoverable from the journal
  instead of invisible.

## 7. Ordered steps

**AUD-14a**
1. Promote §2's table into a dated doc under `docs/evidence/`, regenerating both halves
   (journal + `git log`) at execution time so the table is reproducible, not copied.
2. **Close the one open evidence link:** grep the node-log archive for the first appearance of
   `ContinuousRungHoldStrategy subscribed` and record its timestamp next to the 09-12T17:05:01Z
   first FAIL, confirming (or correcting) the marker-mismatch causal chain end to end. Record
   the answer either way — a disconfirmation is a finding, not a failure.
3. RED: `tests/unit/test_trade_supervisor.py` ::
   `test_supervisor_started_logs_a_revision_field`, and
   `test_an_absent_revision_logs_unknown_rather_than_omitting_the_field`.
4. GREEN: add the field to the `supervisor_started` `log_decision` call.
5. RED (safety): `test_the_revision_field_is_never_read_from_an_operator_reserved_variable` —
   assert the resolver consults only the three named sources.

**AUD-14b**
1. **Delivery re-verification as a recorded step, not an assumption.** Before any code: confirm
   `BREEZY_ALERT_WEBHOOK_URL` is configured and that a CRITICAL is delivered end to end
   (`tests/integration/test_alert_webhook_delivery.py` path), and paste the evidence line into
   the item's transcript. If delivery has regressed, 14b ships a detector with no destination
   and must stop until it is restored.
2. RED (pure core, no I/O): `tests/unit/test_trade_supervisor_core.py` ::
   `test_a_second_consecutive_self_check_failure_increments_the_counter`,
   `test_a_pass_resets_the_consecutive_failure_counter`,
   `test_the_reducer_records_the_self_check_utc_on_every_result`,
   `test_the_escalation_reducer_takes_no_date_and_never_touches_day_scheduler_state`
   (signature/type assertion — the deviation from the `record_*` family is structural, so pin it
   rather than trusting a comment).
2a. **RED (pure core, the severity decision and the codec — no I/O, no store).**
   `tests/unit/test_trade_supervisor_core.py` ::
   `test_a_pass_result_resolves_to_no_severity_at_all`,
   `test_a_first_failure_with_a_known_count_resolves_to_warn`,
   `test_a_second_consecutive_failure_with_a_known_count_resolves_to_critical`,
   `test_an_unknown_count_resolves_a_failure_to_critical_even_at_a_count_of_one` — the
   fail-toward-alerting rule for `escalated_self_check_severity`, pinned in the pure layer where
   it cannot be confused with a store fixture;
   `test_the_escalation_codec_round_trips_both_fields_by_name`,
   `test_the_codec_rejects_a_missing_key_an_extra_key_and_a_wrong_scalar_type` — the decode is
   total and every rejection is reported as `CORRUPT`, never coerced to a default.
2b. **RED — the rollover boundary, driven for real, not simulated.** In
   `tests/unit/test_trade_supervisor.py`, call `_do_self_check` twice against a real
   `SqliteStateStore` in `tmp_path`, with `now` at `2026-09-12T17:05Z` and `2026-09-13T17:05Z` —
   two instants `_trading_day` (`trade_supervisor_core.py:681-690`, boundary `STOP_PRIOR_UTC`
   16:40Z) puts on **different** trading days — threading `DaySchedulerState` through and calling
   `mark_phase_fired` between them exactly as the poll loop does at `trade_supervisor.py:1496`:
   `test_the_counter_survives_a_real_trading_day_rollover_at_1640z` (FAIL then FAIL ⇒ count 2,
   CRITICAL on the second),
   `test_a_pass_after_a_rollover_resets_the_counter_to_zero` (FAIL then PASS ⇒ count 0, no
   CRITICAL, and the stored value is rewritten, not merely ignored),
   `test_the_rollover_still_resets_every_existing_day_scheduler_state_field` — the
   no-unintended-carry-over guard: the same two-day sequence must leave
   `readiness_observed`/`launch_done`/`strategy_subscribed_seen`/`relaunch_attempts` reset by
   `_for_day` exactly as they are today.
3. RED (shell): `tests/unit/test_trade_supervisor.py` ::
   `test_the_first_self_check_failure_alerts_at_warn`,
   `test_the_second_consecutive_failure_alerts_at_critical`,
   `test_the_repeated_failure_alert_detail_is_a_fixed_enum_and_carries_no_value`.
4. **RED (persistence and the fault paths, keyed on the literal store key). Every test below
   asserts a failure of the escalation machinery fails TOWARD alerting**; two of the revision-3
   names are deliberately retired because they encoded the rejected design (see §13 round-3
   dispositions 1 and 2):
   `test_the_consecutive_counter_survives_a_supervisor_restart`,
   `test_a_gap_of_more_than_26_hours_since_the_last_self_check_is_reported_as_a_field`,
   — **absent vs corrupt, observably different** (the two paths a single "unparseable or absent"
   branch used to collapse):
   `test_an_absent_key_starts_the_counter_at_zero_and_emits_no_alert` (the only silent-zero path;
   asserts the sink received **nothing** from the load, and `escalation_state=absent` is on the
   log line),
   `test_a_corrupt_stored_value_alerts_where_an_absent_key_is_silent` — the same two calls, one
   with no key and one with garbage bytes at the literal key, asserting the corrupt call emits
   `TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT` and the absent call emits no load alert
   at all, and — **write-back case 3 (PASS under a corrupt read)** — feeding the
   corrupt call a **PASS** and asserting the store then holds exactly
   `{"consecutive_failures": 0, ...}`: the one rebase to zero that an *observed* result licenses
   (§6), with `last_self_check_utc` advanced so the write is proven to have happened rather than
   been skipped,
   `test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero` —
   plant `{"consecutive_failures": 5, ...}` corrupted, feed a FAIL, assert CRITICAL with the
   corrupt `detail` and **not** a WARN; then — **write-back case 1 (FAIL under a corrupt read,
   then FAIL)** — read the store back immediately and assert it holds exactly
   `{"consecutive_failures": 1, ...}` (the reducer's output: **not** `0`, **not** the planted `5`),
   and drive a **second** poll against that repaired value asserting the next FAIL reaches CRITICAL
   **by count** — the assertion that fails if an implementer persists the bare default, which is
   the under-alert §6 rejects by name;
   — **write-back case 2 (FAIL under a corrupt read, then PASS):** the same first call followed by
   a PASS, asserting the store returns to `{"consecutive_failures": 0, ...}` and that no CRITICAL
   is emitted on the second poll,
   — **read failure, sustained across polls** (the test the rejected in-memory fallback could not
   pass):
   `test_a_store_read_failure_alerts_and_escalates_a_failure_to_critical` — which also asserts
   the write **was attempted** on the fault path (§6): with the store wholly unavailable, both
   `TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE` and
   `TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED` are emitted, so a skipped write
   cannot pass as a contained read failure,
   `test_a_sustained_read_failure_still_escalates_on_the_second_of_two_consecutive_polls` — drive
   `_do_self_check` **twice**, with `store.get` raising on both calls, and assert a CRITICAL on
   **both**; a single-call test cannot distinguish a correct design from one that silently counts
   from zero every poll, which is exactly why this one is multi-poll,
   — **write failure, after the alert decision:**
   `test_a_write_failure_after_a_critical_decision_still_delivers_the_alert_and_is_reported_
   distinctly` — fail `store.set` only (never `get`), assert the CRITICAL still reached the sink,
   that `TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED` is emitted, and that it is a
   different event from the read-failure one,
   `test_a_write_failure_then_a_restart_duplicates_but_never_loses_the_escalation` — day 2's FAIL
   decides CRITICAL, the write fails, a restart is simulated (a fresh store read against the same
   `tmp_path` store), day 3's FAIL is fed, and a CRITICAL is asserted **again**; the duplicate is
   the accepted cost of the decide→emit→persist ordering and the test states so,
   `test_the_alert_is_emitted_before_the_store_write` — the ordering itself, pinned by recording
   the sequence of sink and store calls, so a later refactor cannot quietly swap to persist-first
   and reintroduce the losable interleaving.
5. **Regression replay (the real acceptance):** `test_the_2026_09_12_to_09_18_sequence_escalates`
   — feed the seven recorded results (`FAIL_NODE_NOT_READY` ×6, `FAIL_CHILD_EXITED` ×1) and
   assert ≥1 CRITICAL is emitted on day 2, not day 7. This is the historical incident replayed
   against the new code.
6. **Restart-interleaved replay:** `test_the_sequence_still_escalates_when_a_restart_falls_on_
   day_3` — the same seven results with a simulated process restart between days 3 and 4,
   asserting the count is read back from the store and the CRITICAL cadence is unchanged. Six
   of seven observed restarts were deploys, so a counter that resets on restart would have
   silently defeated itself in the real incident.
7. GREEN, then `lint-imports` + `mypy`, then the full gate `scripts/ci/run_tests_no_egress.sh`
   (addopts already carries `-q`; never add `-q`).

## 8. Acceptance criteria and required evidence

1. A dated evidence doc classifying **all 7** restarts with journal timestamps and commit
   SHAs, stating the count of recovery-driven restarts (expected: **0**, from §2), and carrying
   the first-appearance timestamp of `ContinuousRungHoldStrategy subscribed` from §7 14a step 2.
2. RED→GREEN transcripts for every test in §7.
3. `test_the_2026_09_12_to_09_18_sequence_escalates` passes: the seven-day historical sequence
   produces a CRITICAL on the **second** day. `test_the_sequence_still_escalates_when_a_restart_
   falls_on_day_3` passes with the same cadence.
4. **A delivered alert artefact**, not a log line: the recorded webhook-delivery evidence from
   §7 14b step 1, pasted into the transcript. This is the acceptance item that distinguishes
   this item from the defect it is fixing.
5. `journalctl --user -u breezy-trade-supervisor.service` after the next deploy restart shows a
   `supervisor_started … revision=<value>` line, and the value differs from the previous
   restart's — demonstrating the deploy-vs-not inference the field exists to support.
6. The persisted value is readable at the literal key `runtime:supervisor:self_check_escalation`
   and contains exactly the two specified JSON keys.
7. Full gate green; `lint-imports` and `mypy` clean.
8. **Negative evidence, explicitly required:** no test in this item may be made green by
   changing `self_check`'s ladder, and none may be made green by changing the day-rollover
   contract. `git diff -- src/breezy/runtime/trade_supervisor_core.py` must show **no change
   inside** `def self_check` (`:499-553`), **no change to** `DaySchedulerState` (`:599-667`),
   `initial_scheduler_state` (`:670-671`), `_for_day` (`:674-678`), `_trading_day` (`:681-690`)
   or `mark_phase_fired` (`:765-777`) — the escalation record is additive and lives beside them,
   never inside them. This is the acceptance item that proves the round-2 defect was fixed by
   design change rather than by a special case bolted into a shared reducer.
9. **The escalation machinery's own faults are alertable, and absence is not a fault.** A
   transcript showing: a corrupt stored value producing a delivered
   `TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT`, an absent key producing **no** load
   alert, and a store read failure producing a CRITICAL on a FAIL rather than a WARN. The three
   are shown side by side, because the acceptance is that they are *distinguishable*. **The
   transcript also quotes the stored value read back immediately after each of the three
   fault-load write-back cases** (§6): `1` after a FAIL under a corrupt read, `0` after a PASS
   under a corrupt read, and both the unavailable-store and write-failed events when the store is
   wholly down — so "what is persisted after a fault" is an observed artefact, not an inference.
10. **The ordering is proven, not asserted:** the RED→GREEN transcript for
   `test_the_alert_is_emitted_before_the_store_write` and for
   `test_a_write_failure_then_a_restart_duplicates_but_never_loses_the_escalation`, which together
   pin "can duplicate, can never lose".
11. **`_do_self_check`'s signature and the `Phase.SELF_CHECK` call site are unchanged** —
   `git diff -- src/breezy/runtime/trade_supervisor.py` shows **no change** to the `def
   _do_self_check(...)` parameter list or return annotation (`:1198-1207`) and **no change at
   all** to the `Phase.SELF_CHECK` call site (`:1485-1496`); only the handler's body moves. This
   is the acceptance item that proves the
   round-3 fallback contradiction was closed by dropping the in-memory value rather than by
   quietly threading one.

## 9. Validation

**Failure cases.**
- **Stored key absent** (`store.get` → `None`) → start at zero, **silently**: one
  `escalation_state=absent` field, no alert. This is the only legitimate zero-start and the only
  silent path in the whole mechanism. Pinned by test.
- **Stored value present but undecodable (CORRUPT)** → a delivered WARN
  (`TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT`, fixed-enum `detail`), and the count is
  treated as **UNKNOWN**, never as zero — so a FAIL under a corrupt value escalates to CRITICAL
  instead of silently restarting a streak clock that may already be at five. The state operand is
  the same `SelfCheckEscalationState()` default as `ABSENT` and the **reducer's output is written
  back** (1 after a FAIL, 0 after a PASS — never the bare default), which repairs the key without
  ever leaving the next poll's FAIL looking like a first FAIL (§6). Pinned by two tests, one of
  which asserts the corrupt path is observably different from the absent path, and each of which
  asserts what the store actually holds afterwards.
- **Store read failure (UNAVAILABLE)** → a delivered WARN with its own distinct event, the
  exception contained at the load helper and named by TYPE only, the poll loop untouched, and a
  concurrent FAIL escalated to CRITICAL. A *sustained* outage therefore **over-alerts** (every
  FAIL is CRITICAL) rather than suppressing; that direction is chosen deliberately (§6) and is
  pinned by a **two-poll** test, because a single-call test cannot tell a correct design from one
  that counts from zero every poll.
- **Store write failure after the alert decision** → the alert has already been dispatched
  (decide → emit → persist), so nothing is lost; the failure is logged with `error_type` only and
  alerted once under its own event, distinct from the read-failure event. The stored count is one
  behind, so the next FAIL can re-emit the same escalation — a **duplicate, never a loss**, which
  is the direction the restart profile (6 of 7 deploys) demands. Both properties pinned by test.
- Revision unresolvable → `revision=unknown`. Never a raise, never an omitted field (an absent
  field is indistinguishable from an old binary).
- Alert sink raising → already contained by the existing `emit_alert` path
  (`health.py:668-689` catches `BaseException` by contract); the new call site adds no new raise
  and cannot change the poll loop's control flow.
- Webhook configured but unreachable → the local log line still lands (both sink branches are
  independent, pinned by `tests/unit/test_alert_egress.py`); the CRITICAL is *decided* whether
  or not it is *delivered*, and the count is not re-tried or duplicated (`dispatch`'s contract,
  `health.py:800-814`).

**Integration behaviour.** 14b sits entirely inside `_do_self_check`'s existing alert branch,
a new pure reducer, and a new store key. Nothing in the day-scheduler seam moves: the 47
`initial_scheduler_state` call sites, the 21 `mark_phase_fired` call sites and the 20
`record_readiness_observed` call sites are untouched, so there is no site at which the rollover
reset could now carry a field forward unintentionally. The self-check RESULT is unchanged, so every existing self-check test
(`tests/unit/test_trade_supervisor.py`, `tests/unit/test_trade_supervisor_cont_self_check.py`)
must stay green **byte-unchanged** — that is the integration assertion. 14a's field is additive
on an existing `log_decision` call; no supervisor control flow keys on it, and no readiness
marker gains a substring (touching `STRATEGY_SUBSCRIBED_MARKER` is how `1859498` happened).

**Autonomous operation.** The point of this item is the autonomy property itself.
- **Detection:** after 14b a structural readiness break announces itself as CRITICAL on day
  two instead of accumulating identical WARNs, and the escalation survives the restart class
  (deploys) that actually occurs in this system — 6 of 7 observed restarts.
- **Recovery:** deliberately none. It does not make the system restart itself, and it
  deliberately does not try: a self-restarting supervisor under an unexamined fault is how a
  10 h permit becomes two. The correct autonomous response to a repeated structural FAIL is a
  loud, delivered, human-routed CRITICAL, not a retry loop.
- **Residual, named with its owner:** if the self-check never runs at all, nothing here fires.
  14b makes the gap *visible on the next run* (`self_check_gap_hours`), which is the cheap half;
  a true dead-man's switch belongs with `AMENDMENT B-4`'s watch-window work (§5).

## 10. Deployment, observability, rollback

- Both halves ship by ordinary merge, live at the **next deploy restart** — which, per §2, is
  itself the human action this item is documenting. Note the irony explicitly in the evidence
  doc: restart #8 will be AUD-14's own deploy, and it will be the first one whose `revision=`
  line exists.
- Observability: one new field on an existing line; one new alert event name; one int field on
  the self-check result line. No new unit, no new timer, no env change.
- Rollback: both changes are additive and independently revertable. Reverting 14b restores the
  single daily WARN and leaves the store key orphaned but harmless (an unread key); reverting
  14a removes one log field. Neither touches control flow that can refuse an order.

## 11. Relationship to portfolio-level ROI

**Demonstrated: none, and the honest framing is a loss-avoidance one.** The measured cost of
the gap is on record and is not invented: the fee halt ran **three days** and the permit lapse
**eleven hours**, both emitted and neither delivered
(`POST_FORECAST_PHASE_2026-09-20.md:242-255`), and the readiness FAIL documented here ran
**seven days**. Those are days the bot could not have traded even with an edge.

**Plausible benefit:** AUD-14b shortens the detection-to-attention latency of any future
structural break from "never" to "one day". It generates no return by itself, and no dollar
figure is attached to it here.

**Evaluated by:** the §8 acceptance items, and thereafter by a standing observation — no
self-check FAIL sequence longer than one day without a CRITICAL in the journal.

## 12. Assumptions, unresolved questions, blockers

**No blockers.** Nothing here needs an operator or strategy-lead ruling: no cap is read or
valued, no enablement flag is touched, no PREREG semantics change, no second permit mint.
Independently confirmed by round-1 review.

**Assumptions:**
- `BREEZY_ALERT_WEBHOOK_URL` is configured and CRITICALs are delivered (`f97c26f`, 09-20).
  **This is no longer only an assumption:** §7 14b step 1 makes re-verification a recorded
  execution step with its own evidence line, and §8 item 4 makes the delivered artefact
  acceptance.
- Restart #1 (09-10T16:43:56) is classified *deploy-adjacent*, not deploy-driven: the nearest
  commit is a docs commit 46 s earlier. It is the one restart whose motive cannot be closed
  from the artefacts. Record it as such — do **not** round it up to "deploy" to make the table
  tidy.
- The supervisor process, not the node, is the right site for this counter. That holds because
  the 17:05Z self-check is the supervisor's own phase. It would NOT hold for a permit-lapse
  detector — `AMENDMENT B-4` verified the supervisor's watch window closes at 01:00Z while the
  permit lapses at 02:50Z. **Do not reuse this item's site for that one.**

**Resolved this revision (was an open question):** the CRITICAL threshold is **2 consecutive
results**, not 2 consecutive days. Reason: a same-day repeat is itself abnormal, and a
day-keyed threshold would have been defeated by the mid-day relaunch path (3×/5 min to 01:00Z,
merge `eed0f4c`), which can produce two self-check-relevant transitions inside one trading day.
The cross-day case is still covered because the counter survives rollover
(`test_the_counter_survives_a_trading_day_rollover`). This is now a decision, not an open
question; a round-2 reviewer who disagrees should argue it as a defect with a mechanism.

## 13. Review history

**Baseline self-score (2026-09-21, author): 90/100.** Named weaknesses: G-13's "hands-off"
headline only partly closed; `ContinuousRungHoldStrategy subscribed` first-appearance not
verified; store key namespace described but not spelled; item-4 acceptance lands after merge;
no self-healing added.

### Round 1 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-14-r1-trading-bot-architect.md`) | 90/100 | **None found.** Reproduced the 7-row table bit-for-bit independently. |
| silent-failure-hunter (`AUD-14-r1-silent-failure-hunter.md`) | 90/100 | **None found.** Confirmed the sink exists and that the "trivially-true detector" anti-pattern does not recur here. |

**Dispositions — every defect and every named required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | architect | Optional: state explicitly that the revision field records *what* is running, never *why* | **ACCEPTED.** §6 now carries a dedicated paragraph, and it goes further than requested: it specifies the actual inference the field enables (compare consecutive `revision=` values across restarts — changed ⇒ deploy-driven), and §8 item 5 makes that comparison an acceptance item rather than leaving the field decorative. |
| 2 | hunter | Spell the store-key namespace literally | **ACCEPTED.** §6 gives the literal key `runtime:supervisor:self_check_escalation`, its colon convention (matching `bootstrap_witness.py:82`, and explicitly not tilde-separated), the exact two-key JSON value, and the `sqlite_store.py:155,168` `get`/`set` API it uses. §8 item 6 pins it. |
| 3 | hunter | Turn the §12 delivery assumption into an explicit §7 step with its own evidence line | **ACCEPTED.** §7 14b step 1 is now a blocking, recorded re-verification, §8 item 4 requires the delivered artefact, and §12 is reworded from "assume" to "recorded execution step". |
| 4 | hunter | MINOR — same-day vs cross-day threshold left as an open question | **ACCEPTED and CLOSED.** §12 no longer carries it as an open question: the threshold is **2 consecutive results**, with the mechanism-level reason (the mid-day relaunch path `eed0f4c` can produce two self-check-relevant transitions in one day, so a day-keyed threshold is defeatable) and the note that cross-day is still covered by rollover survival. |
| 5 | hunter | MINOR — delivery assumed, correctly flagged; "not scored down" | **SUPERSEDED by disposition 3** — no longer an assumption at all. |
| 6 | (author, round 1 §13) | `ContinuousRungHoldStrategy subscribed` first-appearance not verified | **ACCEPTED (self-raised, now closed).** Promoted from a §13 confession to §7 14a step 2 and §8 item 1, with the instruction to record a disconfirmation as a finding. |

**Rejections:** none from either record. Nothing either reviewer raised was found unsupported
by the artefact.

**Points withheld in round 1 without a named change — round 2 must justify or award.** Both
records scored 90/100 while reporting **no material and (architect) no independently-found
minor defects**. The 10 withheld points break down as: fidelity 18/20, technical correctness
19/20, implementation specificity 13/15, acceptance 18/20, autonomous operation 13/15,
portfolio 9/10. Only the specificity deduction was tied to a stated shortfall (the store key,
now closed by disposition 2) and only the two hunter deductions came with required changes
(now closed by dispositions 2-4). **The deductions on fidelity, technical correctness,
acceptance, autonomous operation and portfolio alignment were made without naming any change
that would recover them.** This revision nonetheless closed concrete shortfalls against each
of those criteria on its own initiative:
- *Fidelity*: the last open evidence link (§7 14a step 2) is now a deliverable.
- *Technical correctness*: the alert-sink containment contract and the two-branch delivery
  behaviour are now cited to source (`health.py:668-689`, `:800-814`) rather than asserted.
- *Acceptance*: a **delivered** artefact (item 4), the literal store-key read (item 6), and the
  revision-changed comparison (item 5) were added.
- *Autonomous operation*: restart-interleaved replay (§7 14b step 6), unparseable-value
  handling, and `self_check_gap_hours` were added; the dead-man's-switch residual is named
  with its owner in §5 and §9 rather than left implicit.
Round 2 should either award these criteria or name the specific change that would.

**Revision 2 self-score (honest, post-revision):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Motive half fully closed and independently reproduced; the last evidence link is now scoped. G-13's "hands-off" headline remains only *observable*, not *fixed* — deploy restarts are still human, correctly and explicitly out of scope. |
| Technical correctness and evidence grounding | 20 | 19 | Every timestamp, commit correlation and call site is from a command run against the artefact; the store API and sink contract are cited to source. The `1859498` causal chain's last link is a scoped step, not yet a measured fact. |
| Implementation specificity and feasibility | 15 | 14 | Literal store key, literal JSON shape, literal reducer signature, literal field and event names, literal source order for the revision. The exact rendered `log_decision` field order is still the implementer's. |
| Acceptance criteria and validation quality | 20 | 19 | Eight items including two historical replays, a delivered artefact, a literal key read, and a negative `git diff` on `self_check`. Item 5 still needs a real restart, so it lands after merge. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Store, revision, sink, unreachable-webhook and unparseable-value paths all specified and tested; restart survival is replayed against the real restart class. No self-healing, by reasoned design. The never-ran case is halved, not closed, and is named with its owner. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Loss-avoidance framing on recorded numbers only; every exclusion names its owning work package; deconflicted from AUD-16b. |
| **Total** | **100** | **95** | |

### Round 2 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`AUD-14-r2-silent-failure-hunter.md`) | **73/100** | **1 MATERIAL** — the escalation counter as designed cannot survive `_for_day`'s trading-day rollover. |
| trading-bot-architect (`AUD-14-r2-trading-bot-architect.md`) | **100/100** | None found. Re-verified `log_decision:685`, `supervisor_started:1364`, the WARN at `:1298-1302`, the five CRITICAL sites, and the `self_check` ladder. |

**Readiness is the LOWER of the two, 73** — the split is itself the finding. The architect's
100/100 was awarded after re-reading the `self_check` ladder and the `DaySchedulerState` field
block and finding "nothing left to an implementer's judgment that could produce a divergent
design"; the hunter read `_for_day` and found the exact opposite on the same dataclass. Two
independent reviewers, one artefact, a 27-point spread: **a perfect score is not evidence of
absence, and this revision treats the 73 as the true reading.** Coordinator verification
independently confirmed the hunter.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — §6 required `_for_day` not to reset the new counter while also requiring the reducer to match the `record_*` family "exactly"; `_for_day` returns `initial_scheduler_state(day)` on rollover, wiping every field, so the counter resets daily and the flagship seven-day replay cannot pass | **ACCEPTED IN FULL — the defect is real and the design is changed, not patched.** Verified from source this session: `_for_day` at `trade_supervisor_core.py:674-678` returns `state if state.day == day else initial_scheduler_state(day)`; `initial_scheduler_state` at `:670-671` is `DaySchedulerState(day=day)`. Two facts the hunter's record did not have make it worse: (a) `_trading_day` (`:681-690`) rolls at `STOP_PRIOR_UTC` **16:40Z** while the self-check runs at 17:05Z, so *every* consecutive self-check pair already crosses a rollover — not just the seven-day replay; (b) the poll loop calls `mark_phase_fired(state, phase, now)` at `trade_supervisor.py:1496`, the line after `_do_self_check` returns (`:1485-1495`), re-running `_for_day` a second time — so even a rollover-safe reducer would be undone. **Mechanism chosen:** the counter leaves `DaySchedulerState` entirely for a new `SelfCheckEscalationState` frozen dataclass with **no `day` field**, its own pure reducer that never calls `_for_day`, and the **persisted store value as the single source of truth, re-read fresh at every self-check** — so boot, rollover and restart are one case. The rejected alternative (carry two fields forward inside `_for_day`) is named in §6 with its reason: 47 `initial_scheduler_state` call sites and a documented "applied consistently by every function in this section" contract. §6 rewritten; §5 scope bullet corrected. |
| 2 | hunter | Required change 2 — add a test that drives a **real** `_for_day` rollover, not a same-day sequence | **ACCEPTED.** §7 14b step **2b** is new and drives `_do_self_check` twice against a real `SqliteStateStore`, at `2026-09-12T17:05Z` and `2026-09-13T17:05Z` — opposite sides of the 16:40Z `_trading_day` boundary — with `mark_phase_fired` called between them exactly as the loop does. Three named tests: rollover survival, **PASS-after-rollover resets to zero**, and `test_the_rollover_still_resets_every_existing_day_scheduler_state_field` (the unintended-carry-over guard the coordinator required). |
| 3 | hunter | Required change 3 — re-verify the seven-day replay against the fixed mechanism | **ACCEPTED.** §7 14b step 5 is unchanged in intent and now reachable: with the counter outside `DaySchedulerState` and re-read from the store each time, seven rollovers are seven ordinary reads. Step 6 (restart-interleaved) is unchanged and is now the *same* code path, which is the design's own argument for itself. |
| 4 | hunter | "Every other caller of `initial_scheduler_state`/`_for_day` must be checked for unintended carry-over" (coordinator-required audit) | **ACCEPTED, and the answer is NONE AFFECTED — by construction.** The chosen mechanism touches `DaySchedulerState`, `initial_scheduler_state`, `_for_day`, `_trading_day` and `mark_phase_fired` not at all, so the 47/21/20 call sites (codegraph blast radius) keep byte-identical behaviour. §8 item 8 was extended from a single negative `git diff` on `def self_check` to a **six-symbol** negative diff pinning exactly that, so the fix cannot later be re-implemented as a special case inside a shared reducer. |
| 5 | architect | None; 100/100, "no point withheld without a nameable defect" | **NOT AWARDED — recorded as a miss.** The architect read `DaySchedulerState`'s field block in full and concluded the new fields were "additive at the end of the dataclass, not an insertion that would touch existing field ordering" — true, and beside the point: the defect was four lines below, in `_for_day`. Per the coordinator's instruction this 100 is not treated as evidence of correctness. The one design decision it *did* stress-test (2-consecutive-results vs 2-consecutive-days, §12) survives the redesign unchanged and is re-confirmed: the escalation record is not day-keyed at all, which makes "consecutive results" the only coherent reading. |
| 6 | architect | Confirmed all round-1 dispositions genuinely closed | **NOTED**, no change required. |

**Rejections:** none. The hunter's MATERIAL defect is accepted in full and drove a design change.

**Revision 3 self-score (conservative — a MATERIAL design defect survived a baseline and a full
round of review on the P1 item, so no criterion is scored as if the plan had been clean):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged in substance: motive half closed and independently reproduced; G-13's "hands-off" headline remains observable, not fixed, with the deploy-restart automation correctly out of scope. |
| Technical correctness and evidence grounding | 20 | **17** | Every citation in the new §6 was read from source this session (`:674-678`, `:670-671`, `:681-690`, `:600-607`, `:820-822`, `:1193-1195`, `:1198-1207`, `:1485-1496`, `:388-410`). Deducted 3, not 1: a contradiction between two sentences of the same section survived the baseline self-score AND a full review round, which is evidence about this plan's self-checking, not only about the one defect. The new mechanism is verified against HEAD but has never been executed. |
| Implementation specificity and feasibility | 15 | **13** | The dataclass body, reducer signature, purity constraint, store key, JSON shape and the read-decide-write bracket are all literal, and the rejected alternative is named with its reason. Deducted 2: the exact decode/encode helper placement and the shell's local-variable fallback plumbing are still the implementer's, and the new seam has no executed precedent in this file. |
| Acceptance criteria and validation quality | 20 | 19 | Eight items, now including a six-symbol negative `git diff`, a real-rollover test, a PASS-after-rollover reset test, and an existing-field-reset guard. Item 5 still lands after merge (it needs a real restart). |
| Autonomous operation, failure handling, recovery | 15 | **13** | Store failure, unparseable value, revision-unresolvable, sink-unreachable and webhook-down are named and tested; rollover and restart now share one code path. Deducted 2: the store is now a hard dependency of the escalation decision on every self-check (previously in-memory with the store as backup), so a persistently failing store degrades the detector to per-process counting — contained and logged, but a genuinely weaker posture than the prose implied before this revision. The never-ran case is still halved, named with its owner. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: loss-avoidance framing on recorded numbers only; every exclusion names its owning work package; deconflicted from AUD-16b. |
| **Total** | **100** | **91** | |

### Round 3 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-14-r3-trading-bot-architect.md`) | **83/100** | **1 MATERIAL** — the store-failure fallback is unspecified and contradicts §6's own stated rationale. |
| silent-failure-hunter (`AUD-14-r3-silent-failure-hunter.md`) | **74/100** | **3 MATERIAL** — corrupt conflated with absent; the fallback is unthreadable plumbing that collapses to per-call reset; write-failure-after-decision undistinguished from read failure. |

**Readiness is the LOWER, 74.** Both reviewers independently confirmed the round-2 redesign is a
genuine fix (`_for_day` at `trade_supervisor_core.py:674-678`, `mark_phase_fired` at
`trade_supervisor.py:1496`, the non-day-keyed record) and then both landed on the same seam: the
failure paths. All four defects are the same class — **the escalation machinery's own faults
degraded toward silence, in an item whose entire genesis is a detector that reached nobody.**
Revision 4 treats that as the unifying finding, not as four patches.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — corruption treated identically to "never observed": a present-but-undecodable value silently resets a live streak to zero, with only a log line | **ACCEPTED IN FULL.** §6's single "unparseable or absent" branch is replaced by **three named load outcomes** on a new `EscalationLoadOutcome` enum. `ABSENT` (verified contract: `SqliteStateStore.get`, `sqlite_store.py:155-166`, returns `None` for a missing key) is the **only** silent-zero path. `CORRUPT` alerts through the existing sink with a new fixed `AlertDetail` member and yields an **UNKNOWN** count, never zero — so the day-5-of-a-streak scenario the reviewer named now escalates instead of restarting the clock. §7 step 4 adds `test_a_corrupt_stored_value_alerts_where_an_absent_key_is_silent` (the two paths asserted observably different in one test) and `test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero`; §8 item 9 makes the three-way distinguishability an acceptance artefact. |
| 2 | hunter + architect | **MATERIAL (both, independently)** — the "process-local last-known state" fallback has no home: `_do_self_check` is called fresh each poll with all cross-call state threaded explicitly (`state`, `tracked_pid`, `node_log` at `trade_supervisor.py:1485-1495`), so a local variable cannot survive between calls; the naive implementation degrades a sustained store outage to "always reset, never escalate", and §6's own rationale sentence forbids the long-lived object the fallback requires | **ACCEPTED IN FULL. ONE design is decided and specified to the signature — option (b), drop the fallback.** Verified from source before choosing: `_do_self_check`'s signature and return tuple at `trade_supervisor.py:1198-1207` (`-> tuple[int | None, Path | None, DaySchedulerState | None]`) and the call site at `:1485-1496` (three values carried, `mark_phase_fired` on the next line) — threading a fourth would add a long-lived object this design explicitly rejects **and** would still start from zero on the first poll after a restart, which is 6 of 7 observed events. So: **no new parameter, no new return value, call site unchanged** (§8 item 11 pins both with a `git diff`), and instead an UNKNOWN count (from `CORRUPT` or `UNAVAILABLE`) **escalates a FAIL to CRITICAL** with a store-fault `detail`. A sustained outage now **over-alerts instead of suppressing** — stated as an accepted consequence in §6 and §9 rather than hidden. The rationale sentence in §6 is corrected in place: it now says explicitly that the failure path honours it and that revision 3's fallback was the same object by another name. The reviewer's required multi-poll test is added verbatim in intent: `test_a_sustained_read_failure_still_escalates_on_the_second_of_two_consecutive_polls`, and revision 3's `test_a_store_failure_logs_and_falls_back_to_the_in_memory_count_without_crashing_the_loop` is **retired** because its name presupposed the rejected design and it passed trivially under the naive implementation. |
| 3 | hunter | **MATERIAL** — write-failure-after-the-decision is not distinguished from read failure, and no ordering is stated, in the item whose dominant real-world event is a restart | **ACCEPTED IN FULL, with the ordering decided and the analysis stated.** §6 now fixes the bracket as **decide → emit → persist** and gives the interleaving analysis both ways: persist→emit **loses** an escalation when a restart lands between the two (count advanced on disk, nothing delivered, no later run can tell an alert was owed); emit→persist leaves the count one behind so the next FAIL can re-emit the **same** escalation — a duplicate, never a loss. Chosen accordingly: **can duplicate, can never lose.** A failing `store.set` is caught at the same helper, logged by `error_type` only, and alerted under its **own** event/detail, distinct from the read-failure pair. Tests added: `test_a_write_failure_after_a_critical_decision_still_delivers_the_alert_and_is_reported_distinctly`, `test_a_write_failure_then_a_restart_duplicates_but_never_loses_the_escalation`, and `test_the_alert_is_emitted_before_the_store_write` (the ordering pinned by call sequence, so a refactor cannot silently swap to persist-first). §8 item 10 makes the pair acceptance. |
| 4 | hunter | Required: RED tests for corrupt value, missing key, read failure sustained across ≥2 self-checks, write failure then restart | **ACCEPTED — all four exist by name** in §7 step 4 (`test_an_absent_key_starts_the_counter_at_zero_and_emits_no_alert`, the two corrupt tests, the two-poll read-failure test, the two write-failure tests), plus §7 step **2a**, which pins the fail-toward-alerting rule in the **pure** layer (`escalated_self_check_severity`) and the codec's totality, where neither can be confused with a store fixture. |
| 5 | architect | Required: correct whichever §6 sentence is left standing so rationale and failure path agree | **ACCEPTED.** The rationale sentence stands and is now load-bearing; the fallback sentence is gone. The correction is written into §6 at the rationale itself, not only in this table, so a future reader meets it where the contradiction was. |
| 6 | both | The round-2 MATERIAL (rollover) is genuinely closed; `DaySchedulerState`/`_for_day`/`mark_phase_fired` untouched | **NOTED**, no change required; §8 item 8's six-symbol negative diff is unchanged and still pins it. |

**Rejections:** none. All four defects were reproduced from source before editing.

**Revision 4 self-score (conservative — a MATERIAL failure-path defect has now survived on this
P1 item in two successive rounds, on a plan whose whole subject is a detector that failed
silently; no criterion is scored as if the plan had ever been clean):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | **18** | Motive half closed and independently reproduced twice; the escalation half now fails toward alerting on every fault path of its own machinery, which is what "closing the gap" means here. Deducted 2: G-13's "hands-off" headline remains observable rather than fixed (deploy-restart automation correctly out of scope), and the self-check-never-runs case is still only halved. |
| Technical correctness and evidence grounding | 20 | **16** | Every citation in the new §6 was re-read from source this revision (`:1198-1207` signature and return annotation, `:1485-1496` call site, `:1297-1303` alert block, `_SELF_CHECK_PASS_RESULTS` `:1193-1195`, `AlertDetail` `:191-224` and its docstring `:192-196`, `SELF_CHECK_ALERT_DETAIL` `:280-296`, `sqlite_store.py:155-176`). Deducted 4: a self-contradiction inside one section survived a baseline, two review rounds and a revision, and both round-3 reviewers found the same seam independently — that is evidence about this plan's self-checking, not only about the one defect. The mechanism is verified against HEAD and has still never been executed. |
| Implementation specificity and feasibility | 15 | **13** | Now literal at the previously-unspecified point: the load helper and its return type, the three outcomes, the pure severity function's full signature and truth table, the three new enum members with their exact string values, the bracket ordering, and the explicit statement that the handler signature and call site do **not** change. Deducted 2: the decode helper's placement and the json encode call are still the implementer's, and no part of this seam has an executed precedent in this file. |
| Acceptance criteria and validation quality | 20 | **18** | Eleven items now: two historical replays, a delivered artefact, the literal key read, a six-symbol negative diff, the three-way fault distinguishability (item 9), the ordering pair (item 10), and the unchanged-signature diff (item 11). Deducted 2: item 5 still lands after merge, and the over-alerting consequence of a sustained outage is accepted by argument rather than measured against a real outage. |
| Autonomous operation, failure handling, recovery | 15 | **12** | This is the criterion round 3 scored 8 and 11 on, and it is where the revision is concentrated: absent/corrupt/unavailable/write-failure are four distinct, named, tested paths and exactly one of them is permitted to be silent. Deducted 3 rather than 1: a sustained store outage now converts every FAIL into a CRITICAL, which is the right direction but is genuinely noisy and untested against a real outage; and the never-ran case is still halved, named with its owner. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: loss-avoidance framing on recorded numbers only; every exclusion names its owning work package; deconflicted from AUD-16b. |
| **Total** | **100** | **87** | |

### Round 4 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-14-r4-trading-bot-architect.md`) | **94/100** | **None MATERIAL.** 1 MINOR — the `SelfCheckEscalationState` operand fed to the reducer on `CORRUPT`/`UNAVAILABLE` is not explicit. |
| silent-failure-hunter (`AUD-14-r4-silent-failure-hunter.md`) | **93/100** | **None MATERIAL.** 1 MINOR — the same point, reached independently: the write-back state on a fault load is unspecified, and no test checks what the store holds afterwards. |

**Readiness is the LOWER, 93.** Both reviewers independently confirmed all three round-3
MATERIAL defects genuinely closed by design change (the three-outcome `EscalationLoadOutcome`,
the dropped in-memory fallback with the signature verified byte-unchanged, and the
decide→emit→persist ordering with its own `..._WRITE_FAILED` event), and both then landed on
the **same single remaining MINOR** from opposite directions — the architect calling it a
clarification gap, the hunter a specificity gap in what the design does to the store. Two blind
readers converging on one unspecified line is the strongest signal available that it is the last
one, and it is treated as such rather than argued down.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter + architect | **MINOR (both, independently)** — §6 never states which `SelfCheckEscalationState` operand feeds `record_self_check_result`, nor whether `store.set` is attempted at all, when the load outcome is `CORRUPT` or `UNAVAILABLE`-but-writable; two materially different implementations (write the reducer's zero-based result vs. skip the write and leave the corrupt bytes) are both consistent with the prose and neither is pinned | **ACCEPTED IN FULL, and answered by reasoning the write-back through rather than by asserting a default.** Re-verified from source this revision before writing: `SqliteStateStore.get` (`sqlite_store.py:155-166`) returns `None` for an absent key and `set` (`:168-176`) contains nothing — both raw `sqlite3` calls — so `ABSENT`, `CORRUPT` and `UNAVAILABLE` are three genuinely reachable outcomes; `_do_self_check`'s signature and return annotation (`trade_supervisor.py:1198-1207`) and the existing single WARN block (`:1297-1303`) are unchanged by this edit. §6 now states: the operand on **both** fault paths is the same `SelfCheckEscalationState()` default as `ABSENT` (nothing decodable exists, so no other value is available), paired with the fault outcome that keeps `count_known=False`; and **`store.set` IS attempted on both, carrying the reducer's OUTPUT, never the bare default and never skipped.** The three sequences are reasoned in the plan against the rule the coordinator set — a write-back must never rebase the persisted count so as to under-alert on the NEXT poll: **FAIL→FAIL** persists **1**, so the next FAIL escalates by count (persisting the pre-reducer **0** would turn the next FAIL into a first FAIL — a WARN where a CRITICAL is owed, and that alternative is now rejected **by name**); **FAIL→PASS** persists 1, then the PASS resets to 0 and the transient self-clears; **PASS→FAIL** persists **0**, the one legitimate rebase, because a PASS is a *directly observed* result that retires any streak the lost bytes held. The skip-the-write alternative is rejected explicitly: it escalates identically on FAIL→FAIL but never self-heals, so the corrupt WARN repeats daily until a human clears the key. |
| 2 | hunter | Required: add an assertion (may ride on an existing §7 step 4 test) checking what the store actually holds immediately after a corrupt-value FAIL | **ACCEPTED, and extended from one assertion to one per case.** §7 step 4 now carries a write-back assertion on each existing corrupt test: `test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero` reads the store back and asserts exactly `{"consecutive_failures": 1, ...}` — **not** `0`, **not** the planted `5` — then drives a second poll asserting the next FAIL reaches CRITICAL **by count** (the assertion that fails if an implementer persists the bare default), and carries the FAIL→PASS case as its closing clause; `test_a_corrupt_stored_value_alerts_where_an_absent_key_is_silent` gains the PASS-under-corrupt case, asserting `{"consecutive_failures": 0, ...}` with `last_self_check_utc` advanced, which proves the write happened rather than was skipped. `test_a_store_read_failure_alerts_and_escalates_a_failure_to_critical` additionally asserts that **both** the store-unavailable and the write-failed events are emitted when the store is wholly down, so a skipped write cannot pass as a contained read failure. §8 item 9 makes the three read-back values a required transcript artefact, and §9's CORRUPT bullet states the rule where a reader meets it. |
| 3 | both | All three round-3 MATERIAL defects independently re-derived from source and confirmed closed; `_do_self_check` signature/call-site immutability, the no-latch property of `alert()` (`trade_supervisor.py:696-709`), the `AlertDetail` fixed-enum contract, and the daily alert cadence all verified | **NOTED**, no change required. The architect's cadence finding is recorded because it bounds an accepted consequence rather than creating one: the self-check phase fires at most once per day, so a sustained store outage produces at most one CRITICAL per day — the same cadence as the existing accepted WARN, at a strictly more informative severity. |

**Rejections:** none. The single MINOR was reproduced from source before editing.

**Points withheld in round 4 without a named change.** Both records deduct beyond the one
defect they name — the architect 6 points, the hunter 7, against a single MINOR both describe
as non-behaviour-changing. The deductions are accepted rather than contested: each is tied in
the record to a stated shortfall this revision does **not** close (the mechanism has still never
been executed; item 5 needs a real restart; the never-ran case is still halved with its owner
named; a sustained outage's over-alerting is accepted by argument, not measured). No criterion
is scored in the table below as if those were absent.

**Revision 5 self-score (conservative — this is a P1 item that carried a MATERIAL defect in each
of rounds 2 and 3, and the round-4 finding, though MINOR, was again about what the failure path
actually does rather than about what the prose says it does; no criterion is scored as if the
plan had ever been clean):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | **18** | Unchanged: motive half closed and independently reproduced across four rounds; the escalation half now fails toward alerting on every fault path of its own machinery, including — new this revision — what it persists on that path. Deducted 2, unchanged: G-13's "hands-off" headline stays observable rather than fixed (deploy-restart automation correctly out of scope), and the self-check-never-runs case is still only halved. |
| Technical correctness and evidence grounding | 20 | **17** | The fault-load write-back is now derived from the store contract rather than assumed: `get` returning `None` only for an absent key (`sqlite_store.py:155-166`) and the absence of containment in `get`/`set` (`:155-176`) were re-read this revision, as were `_do_self_check`'s signature (`trade_supervisor.py:1198-1207`) and the WARN block (`:1297-1303`). Deducted 3: a self-contradiction inside one section survived two review rounds earlier in this plan's life, and the mechanism — including the new write-back rule — has still never been executed. |
| Implementation specificity and feasibility | 15 | **14** | Now literal at the last unspecified point: the state operand on both fault paths, whether `set` is attempted, and which value is persisted in each of the three sequences, with the two rejected alternatives named. Deducted 1: the decode/encode helper's exact placement remains the implementer's. |
| Acceptance criteria and validation quality | 20 | **19** | Eleven items; item 9 now requires the read-back value after each fault-load case as a quoted artefact, which is the one place the round-4 MINOR could have mattered silently. Deducted 1: item 5 still lands after merge, and the over-alerting consequence of a sustained outage is still accepted by argument rather than measured against a real outage. |
| Autonomous operation, failure handling, recovery | 15 | **13** | Four distinct fault paths, exactly one silent by design, and the persisted state after each is now specified and asserted — so the machinery self-heals a corrupt key instead of alerting on it daily forever. Deducted 2: the never-ran case is still halved with its owner named, and a sustained store outage still converts every FAIL into a CRITICAL — the right direction, untested against a real outage. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: loss-avoidance framing on recorded numbers only; every exclusion names its owning work package; deconflicted from AUD-16b. |
| **Total** | **100** | **91** | |

**Latest score:** 91 (revision 5 self-score). Round-4 peer scores **94** (architect) and **93**
(hunter); **readiness is taken from the 93**. Round-3 peer scores 83 and 74; round-2, 73 and 100.
**Readiness: NOT READY — round 5 delta review pending.**
**Blockers: none.** No operator or strategy-lead ruling is required, and none is created.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `c7646c8da5fe70b6f5eaf4b09bdfa4735c578c2442274c5cd752abf46e5e5db3`
- **Baseline self-score:** 90/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `silent-failure-hunter` round 5: 100/100 — `reviews/AUD-14-r5-silent-failure-hunter.md`
  - `trading-bot-architect` round 5: 100/100 — `reviews/AUD-14-r5-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None.
- **Full review history:** 10 records, `reviews/AUD-14-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
