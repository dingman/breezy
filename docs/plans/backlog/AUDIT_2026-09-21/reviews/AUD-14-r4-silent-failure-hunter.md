# AUD-14 — Round 4 review (silent-failure-hunter, FINAL)

**Plan file:** AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
**SHA256:** 216721702a48e858978a3aab9e1ba8260ec6252ebea4f4064f2f7f8656ec191c
**Round:** 4 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source this session

| Claim | Status |
|---|---|
| `_do_self_check` signature/return unchanged (`trade_supervisor.py:1198-1207`) | CONFIRMED — read verbatim |
| `Phase.SELF_CHECK` call site unchanged (`:1485-1496`), `mark_phase_fired` runs after | CONFIRMED |
| Existing WARN alert on first FAIL at `:1297-1303`, event `TRADE_SUPERVISOR_SELF_CHECK_FAIL` | CONFIRMED |
| `_SELF_CHECK_PASS_RESULTS` (`:1192-1195`) | CONFIRMED |
| `AlertDetail` (`trade_supervisor_core.py:191-224`) is `str, Enum`, docstring bans exception text/config values; three new members would append after `:224` as plain fixed strings | CONFIRMED — new members respect the fixed-enum contract |
| `SqliteStateStore.get`/`set` (`sqlite_store.py:155-176`): `get` returns `None` on absent key; no internal exception containment around the raw `sqlite3` calls in either `get` or `set` | CONFIRMED |
| `runtime:bootstrap_witness` key convention cited from `bootstrap_witness.py:82` | CONFIRMED |
| `_for_day`/`initial_scheduler_state`/`mark_phase_fired`/`_trading_day` untouched by the new mechanism | CONFIRMED — the new `SelfCheckEscalationState` mechanism is fully outside `DaySchedulerState` |
| `alert()` (`trade_supervisor.py:696-709`) is a direct, un-throttled pass-through to `emit_alert` — **no dedup/rate-limit/latch exists on this call path** (the separate `AlertCondition`/`dispatch`/`evaluate` renotify-latch machinery in `health.py:780-822` is a different framework, not used by the supervisor's `alert()`) | CONFIRMED — answers the brief's "is there a latch" question: **no**, so the stated "over-alerts rather than suppresses" consequence cannot be silently defeated by a latch reintroducing silence |

All three round-3 MATERIAL defects (corrupt-vs-absent conflation; unthreaded in-memory fallback; write-failure-after-decision undistinguished from read failure) are genuinely closed by design change, not patched: the three-outcome `EscalationLoadOutcome` enum, the dropped fallback (signature/call site verified byte-unchanged), and the decide→emit→persist ordering with a distinct `..._WRITE_FAILED` event are all present and internally consistent under trace (a PASS always resets to 0 regardless of prior load outcome; an UNKNOWN-count FAIL always escalates; the two-poll sustained-read-failure test and the write-failure-then-restart test both correctly demonstrate "duplicate, never lose").

## New defect found this round

### MINOR — the write-back state on a CORRUPT/UNAVAILABLE load is unspecified, so the persisted numeric count is silently rebased without an explicit rule
§6 states the load outcome for `CORRUPT`/`UNAVAILABLE` is "treated as UNKNOWN, never as zero" for the **severity decision**, and separately that "State = `SelfCheckEscalationState()` ... is the **only** path permitted to start at zero silently" for `ABSENT`. Neither §6 nor §7 states what `SelfCheckEscalationState` value `record_self_check_result` is actually applied to, and therefore what gets `store.set` back to disk, when the load outcome is `CORRUPT` or `UNAVAILABLE`-but-writable. The only structurally available default is the same `SelfCheckEscalationState()` zero used for `ABSENT` (nothing else is named), which means a corrupt-but-recoverable read silently rebases the *persisted* count to a low value in the same call that force-escalates *that one* FAIL to CRITICAL via the `count_known=False` override.

Traced through several sequences (day-N corrupt read mid-streak, corrupt-then-PASS, corrupt-then-FAIL), this does not appear to produce an actual **under-alert** — the `count_known` override forces CRITICAL on the corrupt call itself, and any immediately-following genuine FAIL still crosses the ≥2 threshold because it increments from the freshly-written low baseline. So this is not the same class of defect as round 3's (a demonstrated missed alert); it is a **specificity gap**: the plan does not state, and no test in §7 step 4 checks, what is actually persisted after a `CORRUPT`/`UNAVAILABLE`-but-writable load, and two materially different implementations (write the reducer's zero-based result vs. skip the write entirely and leave the corrupt bytes in place, alerting again next time) are both consistent with the prose as written, and neither is pinned.

**Required change:** state explicitly, in §6, what `SelfCheckEscalationState` is fed to `record_self_check_result` when the load outcome is `CORRUPT`/`UNAVAILABLE` (i.e., confirm it is the same zero default as `ABSENT`, or state otherwise), and whether `store.set` is attempted on that path at all; add one assertion (can ride on an existing §7 step 4 test) that checks what the store actually holds immediately after a corrupt-value FAIL.

## Attack points named in the brief

- **UNKNOWN + PASS:** `escalated_self_check_severity` returns `None` for every PASS result regardless of `count_known` (§6's stated truth table); a PASS under an UNKNOWN count therefore emits only the load-fault WARN (from the `CORRUPT`/`UNAVAILABLE` path itself), never an escalation. Consistent, verified against the stated signature, not vacuous.
- **Alert-storm / latch:** see the confirmed claim above — no latch exists on this call path, so the accepted "sustained outage over-alerts" consequence is real and cannot be silently converted into "sustained outage under-alerts because a latch swallowed the repeats."
- **`AlertDetail` fixed-enum contract:** the three new members are plain string literals appended to the existing closed `str, Enum`, consistent with its own docstring. No violation.
- **Vacuous tests:** none found. Each named test (including the two-poll sustained-read-failure test and the ordering test) asserts a behaviour that a naive/rejected implementation would fail, not a tautology.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | Motive half closed and independently reproduced across three rounds; the escalation half now fails toward alerting on every fault path of its own machinery. Deducted 2 (unchanged from revision 4's own accounting): G-13's "hands-off" headline stays observable, not fixed (correctly out of scope), and the self-check-never-runs case is only halved. |
| Technical correctness and evidence grounding | 20 | 19 | Every citation checked this session is accurate, including the no-latch claim newly verified via codegraph. Deducted 1 for the CORRUPT/UNAVAILABLE write-back ambiguity above, which is a correctness gap in what the design actually does to the store, not merely a documentation nit. |
| Implementation specificity and feasibility | 15 | 13 | Store key, JSON shape, reducer signature, severity truth table, ordering and the three fault events are all literal. Deducted 2: the write-back state on a fault load is unspecified (the new defect), and the decode helper's exact placement remains the implementer's. |
| Acceptance criteria and validation quality | 20 | 19 | Eleven items, now covering three-way fault distinguishability and the ordering pair by test. Deducted 1: no test checks what is actually persisted after a corrupt-value write, which is the one place the new defect could silently matter on a subsequent read. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Absent/corrupt/unavailable/write-failure are four distinct, tested paths; exactly one is silent by design; no latch can reintroduce silence. Deducted 1 for the same write-back ambiguity — a real but non-alerting residual, not a repeat of round 3's under-alert class. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected — loss-avoidance framing on recorded numbers, exclusions correctly scoped. |
| **Total** | **100** | **93** | |

## Required changes (summary)

1. State explicitly what state is fed to `record_self_check_result` (and whether `store.set` is attempted at all) on a `CORRUPT`/`UNAVAILABLE`-but-writable load, and add a test asserting what the store holds immediately afterward.

## Blockers

None. This is a build-side specificity gap, fixable within the plan's own scope. No BLOCKER.
