# AUD-14 round-4 review — trading-bot-architect

Plan: AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
SHA256: 216721702a48e858978a3aab9e1ba8260ec6252ebea4f4064f2f7f8656ec191c
Round: 4 (FINAL)
Reviewer: trading-bot-architect

## Claims verified against source (this session, read-only)

| Claim | Verdict |
|---|---|
| `_do_self_check` signature and return annotation at `trade_supervisor.py:1198-1207`: `def _do_self_check(*, ports, now, store_path, log_dir, tracked_pid, node_log, state=None) -> tuple[int \| None, Path \| None, DaySchedulerState \| None]` | CONFIRMED verbatim |
| `Phase.SELF_CHECK` call site at `:1484-1496`: `tracked_pid, node_log, new_state = _do_self_check(...)`, `if new_state is not None: state = new_state`, `state = mark_phase_fired(state, phase, now)` immediately after | CONFIRMED — **the plan's claim that this call site is unchanged by the design is accurate: nothing in the proposed mechanism requires touching it**, since the escalation record lives outside `state` entirely and is read/written inside `_do_self_check`'s own body |
| Existing alert block at `:1296-1302`: `if result not in _SELF_CHECK_PASS_RESULTS: alert(ports.alert_sink, event="TRADE_SUPERVISOR_SELF_CHECK_FAIL", severity="WARN", detail=SELF_CHECK_ALERT_DETAIL[result])` | CONFIRMED — this is the single-WARN behaviour the plan is replacing |
| `_SELF_CHECK_PASS_RESULTS` at `:1193-1195` — `frozenset({PASS, PASS_ADOPTED_LOG_UNKNOWN})` | CONFIRMED |
| `_for_day` (`trade_supervisor_core.py:674-678`) and `initial_scheduler_state` (`:670-671`) — rollover wipes every `DaySchedulerState` field | CONFIRMED (this is the round-2 defect's root cause; the plan's chosen fix, a `SelfCheckEscalationState` with no `day` field, is not touched by this round's citations and was independently re-derived, not merely re-read) |
| `AlertDetail` enum at `:191-224`, docstring "Never exception text, never a config/permit value" (`:192-196`); no existing member collides with the three proposed new string values (`self_check_escalation_state_corrupt`, `self_check_escalation_store_unavailable`, `self_check_escalation_state_write_failed`) | CONFIRMED — no collision |
| `SqliteStateStore.get`/`.set` at `sqlite_store.py:155`/`:168` | CONFIRMED |
| `health.py` alert sink: `emit_alert` contains `BaseException` by contract (`:683`, `except BaseException: # deliberate`); a **separate**, not-used-here `AlertTransitionTracker`/dedupe mechanism exists (`:739-800`) for callers that fire many times per cycle | CONFIRMED, and this settles the round-4 brief's "alert storm" question: the supervisor's self-check phase fires **at most once per day** (17:05Z), and the plan's design calls the plain `alert()` wrapper directly, the same call shape the existing single-WARN behaviour already uses — a sustained store outage under this design therefore produces **at most one CRITICAL per day**, not a burst. "Trains the operator to ignore it" is a legitimate long-run risk for a daily-cadence alert, but it is the same cadence the existing (accepted) WARN already has, and the escalation is strictly more informative (CRITICAL vs WARN) at the same rate — not a new failure mode this plan introduces. |

## Coherence check (the round-4 brief's specific ask)

- **UNKNOWN-escalates-to-CRITICAL vs the sink contract:** coherent. `emit_alert` never raises and never rate-limits; nothing in the design routes around that contract.
- **UNKNOWN + PASS:** the plan states a PASS under an UNKNOWN count emits only the load-fault WARN, never a CRITICAL — correct, since `escalated_self_check_severity` returns `None` for a PASS result regardless of `count_known` (§6's stated truth table).
- **Alert storm / operator desensitisation:** addressed above — bounded to daily cadence by the scheduler itself, not by this design.

## Defects

**MINOR — the state fed to the pure reducer on `CORRUPT`/`UNAVAILABLE` is not explicit.** §6 states plainly, for `ABSENT`, "State = `SelfCheckEscalationState()`" — the only path permitted to start at zero. For `CORRUPT` and `UNAVAILABLE` it states the *count* is treated as UNKNOWN and drives severity via the `count_known` parameter, but it never states what `SelfCheckEscalationState` object is actually passed into `record_self_check_result` (and therefore written back) on those two paths. The likely intended answer — a fresh default state, since nothing decodable exists — is inferable and does not create a correctness problem (the severity decision is driven by the explicit `count_known` flag, not by whatever `consecutive_failures` value gets bumped from the fallback state), but an implementer following the plan literally has to make this call themselves rather than read it off the page. This is a clarification gap, not a design defect: no counter-example changes behaviour under either plausible reading, because `count_known=False` already forces CRITICAL on any FAIL independent of the numeric value carried forward.

**Required change:** one sentence in §6's failure-handling block, stating explicitly that `_load_self_check_escalation` returns `SelfCheckEscalationState()` (the same default as the `ABSENT` case) as the state operand for both `CORRUPT` and `UNAVAILABLE`, paired with the `EscalationLoadOutcome` value that keeps `count_known=False` downstream — so the write-back baseline after a resolved outage is unambiguous and an implementer is not asked to invent it.

No MATERIAL defect found. The three round-3 MATERIAL defects (absent/corrupt conflation; the unthreadable in-memory fallback; write-failure undistinguished from read-failure) are genuinely fixed: I independently re-derived the `_do_self_check` signature/call-site immutability, the three-outcome enum design, and the decide→emit→persist ordering from source rather than trusting §13's account, and all three hold.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Motive half (14a) fully closed and independently reproducible from the journal/commit correlation; the escalation half (14b) now fails toward alerting on every one of its own machinery's fault paths. Deducted 1: G-13's "hands-off" headline stays observable (deploy-restart automation correctly out of scope) and the self-check-never-runs case is only halved, both named with owners rather than hidden. |
| Technical correctness and evidence grounding | 20 | 18 | Every citation re-verified from source this session and correct, including the `_do_self_check` signature/call-site immutability claim that is load-bearing for acceptance item 11. Deducted 2: the one clarification gap above, and the mechanism has never been executed. |
| Implementation specificity and feasibility | 15 | 14 | Literal store key, JSON shape, enum members, reducer signature and the read-decide-write bracket ordering. Deducted 1 for the same clarification gap — the decode helper's exact placement and the CORRUPT/UNAVAILABLE state operand are the implementer's to infer. |
| Acceptance criteria and validation quality | 20 | 19 | Eleven items including the six-symbol negative `git diff`, the three-way fault distinguishability, and the unchanged-signature diff. Item 5 still needs a real restart to land, which is inherent to the item's subject, not a specification gap. |
| Autonomous operation, failure handling and recovery | 15 | 14 | Four distinct, named, tested fault paths with exactly one permitted silent case; the over-alerting consequence is bounded to daily cadence (verified above) rather than an open risk. Deducted 1: the never-ran case is still only halved, named with its owner (`AMENDMENT B-4`). |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Loss-avoidance framing on recorded numbers only (fee halt 3 days, permit lapse 11h, this FAIL 7 days); every exclusion names its owning work package; deconflicted from AUD-16b. |
| **Total** | **100** | **94** | |

## Required changes

One MINOR: state explicitly, in §6's failure-handling block, which `SelfCheckEscalationState` operand feeds the reducer on `CORRUPT`/`UNAVAILABLE` (recommended: the same `SelfCheckEscalationState()` default as `ABSENT`), so the write-back baseline after a resolved outage is specified rather than inferred.

## Blockers

None. No operator or strategy-lead ruling is required for either 14a or 14b.
