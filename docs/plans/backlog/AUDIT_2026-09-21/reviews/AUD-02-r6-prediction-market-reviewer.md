# AUD-02 round-6 review — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: ed594d4e50fae1b131399ee579efdba9cef35dc71823d85b667ad70db76670a7
Round: 6 · Reviewer: prediction-market-reviewer (blind, independent)

## Verified against source (re-read this round, not trusted from diff)
- `StartupPositionEvidence` is written ONLY at end of `_connect`
  (`_refresh_startup_position_evidence`, client.py:3102-3133) and via
  `_write_startup_position_evidence` (client.py:3053-3096) — never at fill
  or exit time. CONFIRMED: the staleness defect is real; a post-reconnect
  fill/exit is genuinely invisible to this source alone.
- Fix: live read-only GET (`polymarket_us_auth_smoke.py:164` `PORTFOLIO_PATH`,
  confirmed) is now the default; the durable-evidence fallback is gated on
  `ts_ns` age plus a cross-check against `TrialDayLatch.iter_fill_records`
  (trial_day_latch.py:1102, confirmed exists) and `record_exit`
  (trial_day_latch.py:918, confirmed exists) — UNKNOWN on any newer record.
  CONFIRMED sound and grounded in real symbols.
- NO-SEND firewall scope: `scripts/ci/run_tests_no_egress.sh` (read in full)
  is an OS-level network-namespace block wrapped specifically around the
  pytest run (`run_bwrap`/`run_unshare` invoke `pytest`), not a blanket ban
  on all scripts — confirms the plan's claim that a build-side, operator-run
  positions GET outside the test suite does not cross that firewall.
- Override removal: grep-confirmed `--reason`'s only length gate is
  `MIN_REASON_LENGTH` (clear_family_halt_cli.py) with no slug-matching
  logic anywhere in this repo today — the round-5 MINOR (unenforceable
  override) is fully resolved by deleting the escape rather than
  re-specifying it; §6.5/§7 step 0c/§8(i)/§9 are now mutually consistent
  (no override language remains in any of them).

## Coordinator's two questions

**Is removing the override safe in every market state, incl. a position
that cannot be exited (empty book) and settles tomorrow?** Yes, and it is
the correct default: the plan's replacement rule is "wait for settlement or
exit first, then set" — there is no unsafe state, only a DELAY (the halt
cannot be set until the book empties by settlement or fill). Given
`pm_us_crh_v4` currently takes nothing (zero-decision funnel, 6 historical
fills total), the practical odds of hitting this delay are low. **Gap:**
the plan states "weather positions settle within a day" as the bound but
never explicitly ties the delay's acceptability to the family's current
near-zero live exposure — an implementer reading only §6.5 doesn't see the
likelihood argument, only the mechanism. MINOR, not MATERIAL: the
mechanism is fail-safe regardless of likelihood (it can only ever refuse
too long, never send unsafely).

**Is NO-leg/short-YES netting handled so a NO holding is never read as
flat?** The rule text is present and repeated verbatim from round 4/5
("Apply the leg sign before judging flat: the venue nets a NO holding as a
short YES") and is directionally correct — a short-YES `net_position` is
non-zero and a `!= 0` comparison would correctly catch it if implemented as
a numeric (Decimal) comparison. **Gap:** none of the 14 RED tests (§7 step
0a) explicitly exercises a NEGATIVE `net_position` value. Given this exact
netting bug is a named, previously-corrected repo defect (MEMORY:
"venue-nets-no-holding-as-short-yes"), the absence of a dedicated test is a
real, nameable gap — required change: add a RED test asserting a negative
`net_position` (representing a NO/short-YES holding) refuses exactly like
a positive one, not merely relying on the prose reminder.

## Rubric (20/20/15/20/15/10 = 100)
- Fidelity to audit gap & completeness: 19/20 — both prior defects (MATERIAL
  staleness, MINOR override) fully and correctly closed; 1 point held for
  the delay-acceptability framing gap above.
- Technical correctness & evidence grounding: 19/20 — every file:line
  re-checked this round matches; 1 point held for the untested sign-netting
  claim.
- Implementation specificity & feasibility: 15/15 — GET-default plus
  dual-bounded fallback (age + fill/exit cross-check) is fully concrete,
  no remaining underspecified mechanism (the round-5 override gap is gone,
  not patched).
- Acceptance criteria & validation quality: 18/20 — 14 objective RED tests
  cover staleness (13), newer-fill/exit (14), and refusal (12); none covers
  a negative `net_position` specifically — required change above.
- Autonomous operation, failure handling & recovery: 14/15 — fail-closed
  throughout (UNKNOWN=open=refuse, no override, no silent degrade); 1 point
  held for the same delay-framing gap (an operator hitting the wait state
  has no plan-stated reassurance it's expected/low-probability).
- Portfolio alignment, scope, dependencies: 10/10 — unaffected, unchanged.

**Total: 95/100.**

No HUNT-1/live-enablement/operator-cap violations found. No new MATERIAL
defect this round — both required changes above are MINOR (test coverage /
documentation completeness), not safety holes, since the underlying
mechanism is fail-closed either way.

## Blockers
None. Both required changes are plan-text/test-specification fixes.
