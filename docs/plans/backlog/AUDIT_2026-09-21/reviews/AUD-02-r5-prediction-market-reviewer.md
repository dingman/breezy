# AUD-02 round-5 review — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 99bcc4abdd830b7c2e36b59475adb88f35e33886af9bd9dde243320a79adfd3c
Round: 5 · Reviewer: prediction-market-reviewer (blind, independent)

## Round-4 MATERIAL defects — re-verified against source, not trusted from diff text

1. **Exit-seam veto — FIXED.** `submit_exit` (exit_wiring.py:246,270-275, source
   read again this round) still refuses on `is_family_halted()`. The revision
   adds a mandatory pre-set open-position read from
   `StartupPositionEvidence`/`read_startup_position_evidence`
   (client.py:401,3009-3096: `eof_complete`, `position_read_refused`,
   `positions[].net_position` all present exactly as cited), refuses on any
   non-zero position or UNKNOWN, and discloses the clear→exit→re-set sequence.
   CONFIRMED correct and closes the defect.

2. **Self-check — reviser's correction of my round-4 premise is RIGHT.**
   Verified directly: `SELF_CHECK_UTC = dt.time(17, 5)`
   (trade_supervisor_core.py:34), `_do_self_check` has exactly ONE call site
   (trade_supervisor.py:1485, confirmed by grep), `mark_phase_fired`
   (:765,777) latches `self_check_done` so it cannot re-fire same day. My
   round-4 claim of a per-tick repeating alert was WRONG — it is once daily.
   `self_check` (trade_supervisor_core.py:499-553) evaluates
   `FAIL_CONTINUOUS_FAMILY_HALTED` LAST (line 551-552), after child-alive,
   flock, readiness, permit and phase0/startup-evidence checks (lines
   534-550) — a genuine failure always wins and is never masked, confirmed
   by reading the full branch order. The distinct alert detail
   `self_check_fail_continuous_family_halted` already exists
   (SelfCheckResult.FAIL_CONTINUOUS_FAMILY_HALTED, line 276; mapped in
   SELF_CHECK_ALERT_DETAIL, referenced at :293-295 per the diff). The
   plan's decision not to add a new state/dedup layer is sound — doing so
   would edit a live safety check's PASS/FAIL map to quieten a deliberate
   stop, which the repo's own binding constraint forbids. CONFIRMED FIXED,
   premise correction accepted.

## Other reviewer's findings — verified present and real
- Store-path pre-flight: `node_store_path_check` (exec_state_db_path.py:142-182,
  read in full this round) returns exactly `MATCH`/`MISMATCH`/`NO_NODE`/
  `DISCOVERY_FAILED`; `main` (:185-214) already refuses on MISMATCH/
  DISCOVERY_FAILED using the same accept-set the plan specifies. CONFIRMED
  wired into the plan's §6.5/§7 step 0c as claimed.
- Non-vacuous verification: `--status` read-only mode + forced-submit RED
  test (10) replace the old "next would-be submit" check, which was
  genuinely vacuous under today's zero-decision funnel
  (DECISION_FUNNEL_2026-09-20.md, independently plausible given the
  Round-4 evidence already on file). CONFIRMED, real fix.

## New MINOR finding (round 5, not previously flagged)
The "REFUSE to set while any non-zero `net_position`... unless the run
records an explicit, reasoned acceptance in `--reason`" override (§6.5,
§8(i)) names no concrete enforcement mechanism — no dedicated flag (e.g.
`--accept-open-position <slug>`) and no RED test exercises the override
path; RED test (12) only covers the refusal branch, not the
acceptance-to-proceed branch. As written this is a free-text `--reason`
string satisfying only the existing `MIN_REASON_LENGTH` check, not a
verified, slug-matched acknowledgment — an operator could satisfy it with
boilerplate text and the CLI would proceed with a position open. Required
change to reach 100: define the override as a distinct, testable mechanism
(e.g. a flag naming the exact slug, cross-checked against the evidence
record) with its own RED test.

## Rubric (20/20/15/20/15/10 = 100)
- Fidelity to audit gap & completeness: 19/20 — both MATERIALs closed with
  source-grounded fixes; the override-path gap above is the one remaining
  softness.
- Technical correctness & evidence grounding: 19/20 — every file:line
  re-checked this round matches; 1 point held for the override mechanism
  not being grounded in an actual code path.
- Implementation specificity & feasibility: 13/15 — CLI additions are
  concrete and mirror existing code precisely; the override flag is
  underspecified (see above).
- Acceptance criteria & validation quality: 18/20 — 12 RED tests are
  objective and cover both new defects' core behaviour; the override branch
  has no test.
- Autonomous operation, failure handling & recovery: 14/15 — self-check and
  exit-seam interactions are now correctly disclosed, tested, and bounded;
  1 point held for the same override softness (a mis-used acceptance could
  leave a position both open and unexitable with no code-level guard).
- Portfolio alignment, scope, dependencies: 10/10 — unaffected, unchanged
  from round 4's clean assessment.

**Total: 93/100.**

No HUNT-1/live-enablement/operator-cap violations found this round. No new
MATERIAL defect — the override-mechanism gap is MINOR (a clarification/
specification gap, not a blocking safety hole, since the default path is
REFUSE and the override requires deliberate operator action either way).

## Blockers
None. The required change above is a plan-text/design specification fix,
not an operator ruling or unavailable evidence.
