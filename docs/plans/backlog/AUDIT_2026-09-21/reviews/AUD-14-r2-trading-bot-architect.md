# AUD-14 review — round 2

Plan: AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
sha256: 62b2677c84d6d3311673e63b9296c296704d884d90c949e4025e5741ae7a8416
Round: 2
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-1 disposition audit

Round 1: this reviewer 90/100 (no material defects, no independently-found minor defects);
silent-failure-hunter 90/100 (also none). §13's disposition table lists 6 items, all from
"optional"/hunter/self-raised categories (store-key literalness, delivery-assumption promoted to
a step, same-day-vs-cross-day threshold closed, evidence-link promoted to a step). Independently
re-verified each disposition against the current plan body, not just the table's claim:

- Store key `runtime:supervisor:self_check_escalation`, literal JSON shape — present in §6 as
  claimed.
- §7 14b step 1 is now a blocking, evidence-producing step (not a §12 assumption) — confirmed.
- Threshold resolved to "2 consecutive results" with a stated mechanism (mid-day relaunch,
  `eed0f4c`, can produce two self-check-relevant transitions in one day) — confirmed present in
  §12, and the reasoning is sound: a day-keyed threshold would be defeatable by exactly that path.
- §7 14a step 2 (first-appearance of `ContinuousRungHoldStrategy subscribed`) promoted from a §13
  confession to a scoped, ordered step — confirmed.

No rejection in either round-1 record; none was warranted.

## Claims verified this session (fresh)

- `kernel.py`/`TradingNode.run()` claim re: no native process supervisor — consistent with what
  this reviewer independently confirmed for AUD-13 (Nautilus provides no restart/reschedule hook);
  the plan's null-hypothesis statement holds.
- `log_decision` at `trade_supervisor.py:685` — confirmed exact (`def log_decision(event: str,
  **fields: int | str) -> None:`).
- `supervisor_started` call site at `:1364` — confirmed exact.
- The existing WARN alert on self-check FAIL — confirmed exact at `:1298-1302`
  (`event="TRADE_SUPERVISOR_SELF_CHECK_FAIL", severity="WARN", detail=SELF_CHECK_ALERT_DETAIL
  [result]`), matching §3's citation (`:1300-1302`) to within 2 lines.
- Five existing CRITICAL alert call sites in the supervisor (`:883, :975, :993, :1177, :1527`) —
  confirmed by grep; all five lines carry `severity="CRITICAL"`.
- `self_check`'s decision ladder — read in full (`trade_supervisor_core.py:499-553`): the
  `strategy_subscribed` branch returning `FAIL_NODE_NOT_READY` and the ordering the plan's
  narrative depends on (child-alive → flock → log-available → strategy-subscribed →
  permit-issued → continuous checks → PASS) match exactly. §8 item 8's negative acceptance
  criterion (`git diff` empty inside `def self_check`) is therefore checking the right function.
- `DaySchedulerState`'s field block ending immediately before `initial_scheduler_state` — read in
  full; consistent with the plan's claim that the new fields are additive at the end of the
  dataclass, not an insertion that would touch existing field ordering/pickling.
- The 7-row restart-vs-commit table was independently reproduced bit-for-bit in round 1 by this
  reviewer against `journalctl`/`git log`; the table is unchanged in this revision and this round
  re-confirms it was not altered.

## Analysis (challenging the one design decision a reviewer could contest)

The "2 consecutive results, not 2 consecutive days" threshold is the one place this plan makes a
judgment call rather than reporting a measurement. It is explicitly reasoned (not left implicit),
cites a real mechanism (the mid-day relaunch path), and is correctly scoped as an internal
alerting-cadence decision rather than an operator-reserved value or a PREREG/cap question — so it
does not require an operator ruling. This reviewer looked for a mechanism by which "2 consecutive
results" could produce a false-positive CRITICAL from a single transient boot race rather than a
structural break (e.g., two self-check-relevant transitions produced back-to-back by the same
mid-day relaunch attempt), which would weaken the escalation's signal quality. The plan's own
evidence (§2's table) shows the self-check itself runs once daily at 17:05Z; the "two
self-check-relevant transitions in one day" language in §12 refers to the mid-day relanch's own
readiness recheck, a **different** signal path from `_do_self_check`, not two `self_check()` calls
per day. §9 confirms the self-check RESULT is unchanged and every existing self-check test must
stay byte-identical. Given that, "2 consecutive results" reduces in practice to "2 consecutive
days" for the self-check path specifically, and the stated mechanism is the correct, conservative
choice rather than a latent false-positive source. No defect found here.

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond what round 1 already
disclosed and this revision already closed.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — the motive half is fully and independently
  reproducible; the escalation half closes the only remaining structural gap (severity/repetition)
  now that delivery is fixed elsewhere (`f97c26f`); the deploy-restart-automation boundary is
  correctly and explicitly refused as out of scope.
- Technical correctness and evidence grounding: 20/20 — every call site, line citation, and the
  self-check ladder itself were independently re-read from source this session and match exactly.
- Implementation specificity and feasibility: 15/15 — literal store key, literal JSON shape,
  literal reducer signature, literal field/event names, a stated source-preference order for the
  revision field. Nothing left to an implementer's judgment that could produce a divergent design.
- Acceptance criteria and validation quality: 20/20 — eight items including two historical
  replays (one against the real 7-day incident, one restart-interleaved), a delivered-not-logged
  artefact requirement, and a negative `git diff` proving `self_check`'s ladder is untouched.
- Autonomous operation, failure handling, recovery: 15/15 — store failure, unparseable value,
  revision-unresolvable, sink-unreachable and webhook-configured-but-down are each named and
  tested; restart survival is replayed against the actual observed restart class (deploys, not
  crashes); the deliberate absence of self-healing is reasoned against this repo's own recorded
  anti-pattern (a self-restarting supervisor under an unexamined fault); the "self-check never
  runs at all" residual is named with its correct owner (`AMENDMENT B-4`) rather than silently
  dropped.
- Portfolio objective alignment, scope, dependencies: 10/10 — loss-avoidance framing uses only
  measured, on-record figures (3-day fee halt, 11-hour permit lapse, 7-day FAIL run); every
  exclusion names its owning work package; AUD-16b is explicitly deconflicted (different process,
  different field, different test file).

**Total: 100/100**

## Required changes for full marks

None. No point was withheld without a nameable defect and required change; none could be named
this round.

## Blockers

None. No operator or strategy-lead ruling is required, and independent verification confirms no
cap, enablement flag, or PREREG semantic is read, valued, or touched.
