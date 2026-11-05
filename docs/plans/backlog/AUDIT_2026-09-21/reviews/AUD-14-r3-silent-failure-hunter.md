# AUD-14 — Round 3 review (silent-failure-hunter)

**Plan file:** AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
**SHA256:** f393a2c49cecb7bbdb6cf80ab762bd7f1a0a473ec0d435282383113823588f67
**Round:** 3
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source (this session)

| Claim | Status |
|---|---|
| `_for_day` (`trade_supervisor_core.py:674-678`) returns `initial_scheduler_state(day)` on rollover, wiping all fields | CONFIRMED — read verbatim |
| `_trading_day` rolls at `STOP_PRIOR_UTC`=16:40Z (`:681-690`) while self-check runs at 17:05Z, so every consecutive self-check pair crosses a rollover | CONFIRMED |
| `mark_phase_fired` is called at `trade_supervisor.py:1496`, the line immediately after `_do_self_check` returns (`:1485-1495`), and re-runs `_for_day` | CONFIRMED — read verbatim, exact line |
| `record_readiness_observed` at `:820-822` is `_for_day` + `replace(...)`, the family shape cited | CONFIRMED |
| `log_decision` (`:685-693`) is int/str fields only, docstring matches the "never an operator-reserved value" citation | CONFIRMED |
| `alert()` (`:696-709`), `emit_alert` (`health.py:668-689`, `BaseException` catch, contract as described) | CONFIRMED |
| `SqliteStateStore.get`/`set` (`sqlite_store.py:155-176`) — `get` returns `None` on absent key, raises `TypeError` on wrong types; no internal exception containment around the sqlite3 calls themselves | CONFIRMED |
| The round-2 MATERIAL defect (counter dies on rollover) is genuinely fixed by moving to a separate, non-day-keyed `SelfCheckEscalationState` re-read from the store every self-check | CONFIRMED as a structural fix — `DaySchedulerState`/`_for_day`/`mark_phase_fired` untouched by the new mechanism |

Prior-round dispositions re-checked: round-2 hunter's MATERIAL defect (73/100) is correctly closed by the redesign; the architect's round-2 100/100 is correctly not treated as evidence (per the coordinator's own ruling, re-confirmed here). No round-1/round-2 disposition is reopened.

## New defects found this round (revision 3 introduces or leaves unresolved)

### MATERIAL — corruption is treated identically to "never observed", collapsing an alertable fault into a bare log line
§6: "An unparseable or absent stored value is treated as `SelfCheckEscalationState()` ... and logged once; fail-open on the counter is correct here because the alternative (refusing to run the self-check) removes the detector entirely."

This conflates two different conditions under one behaviour:
- **Absent key** (`store.get` returns `None`): legitimate on first boot / first deploy of this feature. Zeroing is correct and not worth alerting.
- **Present but unparseable value** (corrupt JSON, wrong keys): an actual persistence fault. The plan's own opening motive is "a detector without delivery is not a control" / "alerts that reach nobody"; yet its own corruption path for the escalation counter itself is a bare `logged once` — no WARN/CRITICAL through the sink specified anywhere in §6-§9.

Concretely: if the store value is corrupted mid-incident (e.g. on day 5 of a real seven-day FAIL streak, `consecutive_failures=5`), the corruption **silently resets the escalation counter to zero** and restarts the FAIL-streak clock from day 1 — extending real-world detection-to-attention by however long the corruption persists, with only a log line (which this very plan's genesis names as the exact anti-pattern: "until `f97c26f` every one of them went to a log file nobody reads"). §9's failure-case list does not distinguish "absent" from "corrupt" and neither test list (§7 step 4) names a test that a *corrupt-but-present* value alerts distinctly from a legitimate never-observed absence.

**Required change:** distinguish `store.get(key) is None` (silent, expected) from a present-but-undecodable value (a fault: emit a WARN, e.g. `event="SELF_CHECK_ESCALATION_STATE_CORRUPT"`, in addition to resetting to zero and logging), and add a RED test asserting the two paths are observably different (one alerts, one does not).

### MATERIAL — the "process-local last-known state" fallback is unspecified plumbing that most naturally collapses to the exact failure this item exists to fix
§6: "A store failure must fail loud and fall back to a process-local last-known `SelfCheckEscalationState` (the shell keeps the last successfully-decoded value in a local variable), never crash the poll loop."

`_do_self_check` is called fresh on every poll from the loop (`trade_supervisor.py:1198-1207`), with all cross-call state threaded explicitly as parameters (`state: DaySchedulerState | None`, `tracked_pid`, `node_log` — the existing pattern). A genuine "local variable" inside `_do_self_check` cannot survive between separate invocations; for the fallback to actually persist across polls during a sustained store outage, it must be threaded through the poll loop exactly like `state` is — as an explicit new parameter/return value. **§6/§7/§8 never name this parameter, its type, or its threading contract**, and the round-3 self-score itself concedes the plumbing is unspecified ("the shell's local-variable fallback plumbing are still the implementer's" — Implementation specificity deduction).

This matters because the round-2 fix's entire rationale for moving off `DaySchedulerState` was "read fresh from the store every time... which is exactly why this shape was chosen over threading a second long-lived in-memory object through the loop" (§6). The store-failure fallback reintroduces precisely that long-lived object, informally, with no specified contract. The most natural naive implementation — a local variable re-initialized to `SelfCheckEscalationState()` inside `_do_self_check` on every call, since no parameter is named for it — means a **sustained store outage silently degrades the detector to "always reset, never escalate"**: consecutive_failures never exceeds 1 in memory because there is nowhere for the in-memory value to live between calls, and the CRITICAL escalation (requiring ≥2 consecutive results) can never fire while the store is down. That is exactly the "detector without delivery" failure mode this whole item exists to close, reintroduced at the one point (persistence loss) it is least likely to be noticed.

§7 step 4's `test_a_store_failure_logs_and_falls_back_to_the_in_memory_count_without_crashing_the_loop` is a single-call test and cannot distinguish a correct threaded fallback from the naive per-call-reset implementation described above — both pass it trivially.

**Required change:** explicitly thread the fallback value through the poll loop as a new parameter/return, named and typed in §6 exactly as `state`/`tracked_pid` are (e.g. `_do_self_check(..., last_known_escalation: SelfCheckEscalationState | None = None) -> (..., SelfCheckEscalationState)`), and add a RED test that drives ≥2 consecutive polls through a sustained store outage and asserts the CRITICAL escalation still fires on the second FAIL — not merely that a single call doesn't crash.

### MATERIAL — write-failure-after-decision is not distinguished from read-failure, and is exactly the restart scenario this item cares most about
§9 covers "Store unavailable/corrupt" as a single generic bullet without stating read/write ordering inside `_do_self_check`'s "read-decide-write bracket" (§6), and without a dedicated test for a **write** that fails after the CRITICAL decision has already been computed (and possibly alerted). Given 6 of 7 observed restarts are deploys (§2's own table) and the counter's persisted value is what a restart reads back, a write that fails on the last self-check before a restart silently understates the persisted count on the next boot — the exact "restart-interleaved" risk §7 step 6 otherwise treats as central ("a counter that resets on restart would have silently defeated itself in the real incident"). A failed write is not a reset, but it is an equally silent understatement with no distinct test.

**Required change:** state the read-decide-write ordering explicitly (does the write happen before or after the alert is dispatched?), and add a RED test that fails the `store.set` call specifically (not `store.get`) after a CRITICAL decision and asserts the alert still fires and the failure is logged distinctly from a read failure.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | Motive half closed and independently reproduced; escalation half's mechanism is sound at the structural (rollover) level but the fault-handling gaps above are part of "closing the gap", not decoration. |
| Technical correctness and evidence grounding | 20 | 14 | Every citation checked this session is accurate. Deducted for the corruption/absence conflation and the unthreaded-fallback claim, both of which are technical mischaracterizations of what the described mechanism actually does under failure. |
| Implementation specificity and feasibility | 15 | 9 | The store key, JSON shape, reducer signature and rollover mechanism are fully literal (this is real, verified work). The fallback plumbing — the exact gap that defeats the item under a store outage — is explicitly unspecified, which is a specificity failure at the load-bearing point. |
| Acceptance criteria and validation quality | 20 | 15 | Eight items including two historical replays and a negative diff. Missing: a test distinguishing corrupt-vs-absent, a multi-poll fallback-persistence test, and a write-failure-specific test. |
| Autonomous operation, failure handling, recovery | 15 | 8 | This is where all three defects land hardest: the corruption path and the store-outage fallback both degrade toward silence rather than toward alerting, which is the opposite of the criterion's own bar. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected — loss-avoidance framing on recorded numbers, exclusions correctly scoped. |
| **Total** | **100** | **74** | |

## Required changes (summary)

1. Distinguish corrupt-stored-value (alert) from absent-key (silent, correct) — currently identical.
2. Name and thread the store-failure fallback as an explicit parameter/return across polls (mirroring `state`), and test escalation surviving ≥2 consecutive polls during a sustained outage.
3. Specify read/write ordering and add a dedicated write-failure test distinct from read-failure, given restarts are the dominant real-world trigger.

## Blockers

None of the above requires an operator/strategy-lead ruling — all three are build-side design/test-completeness gaps, fixable within this plan's own scope. No BLOCKER.
