# AUD-14 review (round 2)

**Plan file sha256:** 62b2677c84d6d3311673e63b9296c296704d884d90c949e4025e5741ae7a8416
**Round:** 2
**Reviewer:** silent-failure-hunter (independent, blind)

## Round-1 disposition verification

Round 1 (both records) found no material defect and the plan's §13 lists all round-1 required
changes as ACCEPTED and closed (store key spelled literally, delivery re-verification promoted to
a §7 step, same-day-vs-cross-day threshold resolved). I re-verified the store key
(`sqlite_store.py:155,168` `get`/`set`) and the `DaySchedulerState` field-block end (`:667`) —
both match the plan's citations exactly. Those closures are genuine.

**However, this round's fresh read of the whole revised plan against source finds a new,
material defect in the mechanism §6/§7 actually specify for the P1 item — the escalation counter
as designed does not survive the trading-day rollover it explicitly claims to survive, and the
plan does not name the fix.**

## MATERIAL defect — the counter cannot survive `_for_day`'s rollover reset as specified

§6 states: *"The counter is keyed on the RESULT, not the day, and `_for_day` must NOT reset it: a
rollover to a new trading day is precisely when the count must survive,"* and separately states
the new reducer `record_self_check_result` must match "the existing `record_*` family
(`record_readiness_observed`, `record_midday_alert_sent`, …) **exactly**."

I read `_for_day` and every existing `record_*`/`mark_phase_fired` function in
`src/breezy/runtime/trade_supervisor_core.py` this session:

```
def _for_day(state: DaySchedulerState, day: dt.date) -> DaySchedulerState:
    """Return state unchanged if it already belongs to day,
    otherwise a fresh state for day -- the day-rollover reset, applied
    consistently by every function in this section."""
    return state if state.day == day else initial_scheduler_state(day)
```

`initial_scheduler_state(day)` returns `DaySchedulerState(day=day)` — **every other field reverts
to its dataclass default**, including any new `consecutive_self_check_failures`/
`last_self_check_utc` fields §6 proposes adding to the same dataclass. Every existing `record_*`
function (`record_readiness_observed:820-822`, `record_strategy_subscribed_seen`,
`record_midday_alert_sent:886-...`, `mark_phase_fired:765-777`, etc.) opens with `effective =
_for_day(state, _trading_day(now_utc))` and then `replace(effective, <one field>=...)` —
unconditionally discarding every field the caller doesn't explicitly re-set, sourced from the
now-blank `effective`, not the pre-rollover `state`. This is not incidental: the docstring calls
it "the day-rollover reset, applied consistently by every function in this section," and it is
the load-bearing mechanism every other sticky/cross-day field in the class (e.g.
`relaunch_attempts`, `midday_alert_sent`) relies on to reset correctly each day.

If `record_self_check_result` is written to "match the existing `record_*` family exactly" (the
plan's own instruction), it too opens with `effective = _for_day(state, target_day)` — and on a
genuine day rollover this silently zeroes `consecutive_self_check_failures` before the reducer
ever runs its increment/reset logic, **directly contradicting the plan's own stated requirement
two sentences earlier that the counter must NOT reset on rollover.** This is not a hypothetical:
it is the exact scenario the plan's own flagship acceptance test drives — the historical
`FAIL_NODE_NOT_READY` sequence ran 2026-09-12 → 09-18, seven calendar days, each one a
`_trading_day` rollover in the running supervisor process. Under the design as specified,
`test_the_2026_09_12_to_09_18_sequence_escalates` (§7 14b step 5) would see the counter reset to
0 (or 1) on every one of those rollovers and could never reach the ≥2 threshold that is the whole
point of the test — unless the reducer deviates from "match `record_*` exactly" in a way the plan
never names (e.g. reading `state.consecutive_self_check_failures` directly rather than
`effective`'s, bypassing `_for_day`'s reset for this one field only). `mark_phase_fired`, called
immediately after `_do_self_check` in the polling loop (`trade_supervisor.py:~1493`), would
independently re-run `_for_day` a second time on the same state, compounding the same risk if the
first reducer's output is not already rollover-safe.

The persistence half (§6, the SQLite key) does not resolve this: it is scoped as protection
against a **process restart**, explicitly separate from the in-process day-rollover requirement
("a restart resets in-memory state… It is persisted in the `SqliteStateStore`"). Nothing in §6 or
§7 states that `record_self_check_result` reads the persisted value to reconstruct the counter on
every call (which would sidestep `_for_day` entirely) — if it did, that would itself need to be
named as the mechanism, and it is not.

**This is exactly the class of defect round 2 is asked to catch: a design claim ("must NOT
reset it") asserted in prose without being reconciled against the artefact's actual, documented,
intentional behaviour, on the plan's own P1 item, on the acceptance test built to replay the real
incident.**

**Fix required:** name explicitly how `record_self_check_result` (and, if it also touches the
field, `mark_phase_fired`) preserves `consecutive_self_check_failures`/`last_self_check_utc`
across a `_for_day` rollover — e.g. read `state.<field>` directly before computing `effective`
and thread it through `replace(...)`, stated as a deliberate, named deviation from "matches
`record_*` exactly" (not left implicit), with a test that actually drives a real `_for_day`
rollover (not just a bare reducer call with a fixed `day`) to prove it.

## Other claims verified (no other new defect found)

- `sqlite_store.py:155-168` (`get`/`set`) — CONFIRMED, matches §6's citation exactly.
- Alert sink containment (`health.py:668-689`) and two-branch delivery (`:800-814`) — not
  re-read line-by-line this session; treated as plan-internal per round-1's independent
  confirmation, no reason to doubt it.
- `trade_supervisor_core.py:499-553` (`self_check` ladder) untouched by 14b's design as stated —
  consistent with the plan's negative acceptance criterion (§8 item 8).

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 18 |
| Technical correctness and evidence grounding | 20 | 13 |
| Implementation specificity and feasibility | 15 | 9 |
| Acceptance criteria and validation quality | 20 | 14 |
| Autonomous operation, failure handling and recovery | 15 | 9 |
| Portfolio objective alignment, scope and dependencies | 10 | 10 |
| **Total** | **100** | **73** |

## Required changes to reach 100

1. Name the exact mechanism by which the escalation counter survives `_for_day`'s trading-day
   rollover reset — the plan currently asserts the requirement and contradicts it in the same
   section by requiring the reducer to match a family of functions whose entire contract is to
   discard exactly this kind of field on rollover.
2. Add a rollover-crossing test that actually calls the reducer across a real `_trading_day`
   boundary change (not a same-day sequence), proving the named mechanism works — the current
   `test_the_counter_survives_a_trading_day_rollover` name does not by itself establish this,
   since its body is unwritten and the design it would need to exercise is unspecified.
3. Re-verify `test_the_2026_09_12_to_09_18_sequence_escalates` (§7 14b step 5) against the fixed
   mechanism — as designed today this is the test most directly defeated by the defect above,
   since the historical sequence it replays crosses seven real day rollovers.

## Blockers

None operator-side. The defect above is a design-completeness gap this plan can close itself
before execution; it is not a ruling.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-14-r2-silent-failure-hunter.md
