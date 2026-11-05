# AUD-14 review — round 3

Plan: AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md
sha256: f393a2c49cecb7bbdb6cf80ab762bd7f1a0a473ec0d435282383113823588f67
Round: 3
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-2 disposition audit

Round 2: this reviewer gave 100/100 (no material defect found). silent-failure-hunter gave
73/100 with 1 MATERIAL — the escalation counter as originally designed lived on
`DaySchedulerState` and could not survive `_for_day`'s trading-day rollover. Per the coordinator's
instruction, the 73 was taken as the true reading, and this revision (3) redesigns the mechanism:
the counter moves to a new, non-day-keyed `SelfCheckEscalationState`, persisted at
`runtime:supervisor:self_check_escalation`, re-read fresh from the store at every self-check
rather than threaded through `DaySchedulerState`. Independently re-verified this session, from
source, not from the plan's narrative:

- `_for_day` (`trade_supervisor_core.py:674-678`) — confirmed exact: `return state if state.day
  == day else initial_scheduler_state(day)`. `initial_scheduler_state` (`:670-671`) confirmed
  `DaySchedulerState(day=day)`.
- `mark_phase_fired(state, phase, now)` at `trade_supervisor.py:1496` — confirmed it runs
  immediately after `_do_self_check` returns (`:1485-1495`), which is the second-`_for_day`-call
  problem the round-2 defect turned on. The new design sidesteps this by removing the counter
  from `DaySchedulerState` entirely, which is the correct fix for the round-2 defect.
- `_do_self_check`'s signature (`trade_supervisor.py:1198-1207`) — confirmed it already takes
  `store_path: Path`, so an I/O shell inside it can open a fresh `SqliteStateStore` connection,
  matching the plan's claim.
- `read_continuous_family_store_state` (`trade_supervisor.py:388-410`) — confirmed the
  fresh-connection pattern (`with SqliteStateStore(store_path) as store:`) the plan cites as
  precedent for the new read-decide-write bracket.
- `SqliteStateStore.get`/`set` (`sqlite_store.py:155,168`) — confirmed signatures match.
- `bootstrap_witness.py:82` — confirmed `WITNESS_STORE_KEY = "runtime:bootstrap_witness"`,
  supporting the colon-separated key convention cited (note: the supervisor's OWN existing keys,
  e.g. `CONTINUOUS_STARTUP_EVIDENCE_KEY = "exec/polymarket_us/startup_evidence"` and
  `CONTINUOUS_FAMILY_HALT_KEY = "continuous_rung_hold/halt"`, actually use slash separators, not
  colons — the plan's citation to `bootstrap_witness.py` for the convention is accurate as
  stated, it just is not the only convention already in this codebase; not a defect, since the
  plan never claims otherwise).
- `_SELF_CHECK_PASS_RESULTS` at `trade_supervisor.py:1193-1195` — confirmed exact.

The round-2 MATERIAL defect is genuinely fixed by the redesign: the new state is not day-keyed,
never calls `_for_day`, and is re-read from the store at every self-check, so boot/rollover/restart
collapse into one case exactly as claimed.

## New defect found this round (the redesign introduces a fresh contradiction)

**MATERIAL — the store-failure fallback path is unspecified and contradicts the design's own
stated rationale for its shape.**

§6 states the read-fresh-every-time design was chosen "exactly... over threading a second
long-lived in-memory object through the loop." Four paragraphs later, the same section requires:
"A store failure must fail loud and fall back to a process-local last-known
`SelfCheckEscalationState` (the shell keeps the last successfully-decoded value in a local
variable), never crash the poll loop."

These two sentences describe incompatible mechanisms. `_do_self_check` is called once per poll
cycle from `_run_forever`'s `Phase.SELF_CHECK` branch (`trade_supervisor.py:1484-1496`) and is
otherwise stateless between calls — the only values threaded across calls today are
`tracked_pid`, `node_log`, and `state: DaySchedulerState`, each explicitly returned by
`_do_self_check` and reassigned in the loop (`:1485-1495`). A "process-local last-known value...
kept in a local variable" that must survive from one poll cycle's store failure to the next
poll cycle's read is, by construction, "a second long-lived in-memory object threaded through
the loop" — the exact thing the design's own stated rationale says was avoided. The plan never
names:
- a new parameter added to `_do_self_check`'s signature to receive the last-known escalation
  state, or a corresponding change to its return tuple (currently `tuple[int | None, Path | None,
  DaySchedulerState | None]`, per `:1207`);
- a corresponding change to the `Phase.SELF_CHECK` call site (`:1485-1496`) to carry that new
  value forward the same way `state`/`tracked_pid`/`node_log` are carried today;
- or, as the alternative, an explicit decision to hold the fallback value in a module-level
  global inside `trade_supervisor.py` — which would be a new, untested-elsewhere persistence
  pattern in a module whose every other piece of cross-call state is explicit and threaded
  through `_run_forever`'s loop by parameter, the exact discipline this plan's own §6 cites
  approvingly elsewhere ("this shape was chosen... over threading a second long-lived in-memory
  object").

This is not a citation slip; it is the same class of defect the round-2 hunter found — a
mechanism whose own stated design rationale is contradicted by an unaddressed requirement four
paragraphs later, in the same section, about the same dataclass's failure path. §7 14b step 4
names a test for this behaviour
(`test_a_store_failure_logs_and_falls_back_to_the_in_memory_count_without_crashing_the_loop`) but
the test name presupposes an "in-memory count" whose home is nowhere specified, so an
implementer cannot write this test without first inventing — not following — a design the plan
claims is already decided.

**Required change (either one closes it, both are acceptable):**
(a) Specify the threading explicitly: extend `_do_self_check`'s return tuple with the resolved
`SelfCheckEscalationState`, extend its signature with an optional previous-escalation-state
parameter (mirroring how `state: DaySchedulerState | None` is already threaded), and add the
corresponding lines to the `Phase.SELF_CHECK` call site in §7's ordered steps — then the "avoids
threading a second long-lived object" sentence in §6 must be corrected, since the fallback design
does exactly that; **or**
(b) Drop the process-local fallback requirement. On a store failure, treat the counter as
`SelfCheckEscalationState()` (same as the unparseable-value case), log once, and state plainly
that a persistently failing store degrades the detector to "counts from zero on the next
successful read" rather than preserving an in-memory tally — which is a weaker but fully
self-consistent posture that needs no new threading.

Either resolution is a real, nameable design decision the plan has not made; leaving both
sentences standing is not.

## Other claims re-verified, no new defect

- `NautilusKernel`/permit-adjacent claims are out of scope for this plan (AUD-13's territory);
  not re-checked here.
- `SELF_CHECK_ALERT_DETAIL`, the WARN at `:1298-1302`, the five existing CRITICAL sites — all
  previously verified in round 1/2 by this reviewer and unchanged in this revision; spot-checked
  `:1298-1302` again this session and it is unchanged.
- The `2-consecutive-results, not 2-consecutive-days` threshold — unchanged from round 2, where
  this reviewer already stress-tested it and found no false-positive mechanism. Still sound.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 19/20 — motive half unchanged and independently
  reproducible; escalation half's day-rollover defect is genuinely fixed. Not deducted for the
  new defect (fidelity to the gap itself is intact); deducted for the same reason as prior rounds
  (deploy-restart automation correctly out of scope, "hands-off" remains observable not fixed).
- Technical correctness and evidence grounding: 16/20 — every citation checked resolves correctly
  at HEAD, and the round-2 fix is real. Deducted 3 for the fresh internal contradiction identified
  above (a design rationale sentence directly contradicted by a requirement in the same section,
  surviving a baseline self-score, round 1, round 2 hunter review, round 2 architect review, and
  this revision's own self-review) — the same pattern as round 2's defect, now on the failure path
  instead of the happy path.
- Implementation specificity and feasibility: 10/15 — the happy-path mechanism (dataclass, reducer
  signature, store key, JSON shape) is fully literal. Deducted 5: the store-failure fallback,
  which is a named, tested requirement (§7 14b step 4), has no specified home for its state, and
  an implementer must invent — not follow — the threading mechanism to write that test at all.
- Acceptance criteria and validation quality: 17/20 — eight items, still including the rollover
  replay and the negative `git diff`. Deducted 3: acceptance item covering the store-failure test
  cannot be objectively validated as written, because the mechanism the test exercises is
  unspecified.
- Autonomous operation, failure handling, recovery: 11/15 — store failure, unparseable value,
  revision-unresolvable, sink-unreachable are each named, but the store-failure path specifically
  — the one failure mode most likely to recur if `SqliteStateStore` has an outage — is the one
  whose recovery behaviour is internally contradictory. Deducted 4.
- Portfolio objective alignment, scope, dependencies: 10/10 — unaffected by this defect;
  loss-avoidance framing on recorded numbers only, every exclusion named with its owner.

**Total: 83/100**

## Required changes for full marks

- Resolve the store-failure fallback contradiction per one of the two options above, and correct
  whichever sentence in §6 is left standing so the design rationale and the failure-path
  requirement agree.
- No other change required; all round-1 and round-2 dispositions remain genuinely closed.

## Blockers

None. No operator or strategy-lead ruling is required by this defect or by anything else in the
plan; it is a design-specification gap the plan's own author can close without external input.
