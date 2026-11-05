# AUD-02 round-7 review — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: b9d1106884ccfe88160459cf7e3d4682fdf2e84cba0532ddca67b9a2b66dce4d
Round: 7 · Reviewer: prediction-market-reviewer (blind, independent)

## Verified against source (re-read this round)
- `_declared_positions` (client.py:2592-2622, `@staticmethod` on the class,
  line 2592) — CONFIRMED exact: refuses on absent/non-dict `positions`
  (:2595-2605) and on `payload.get("eof") is not True` (R-4P-1, :2606-2621),
  raising `ExecutionReportMappingError` (errors.py:208, confirmed
  `VenuePayloadError` subclass at that exact line). The round-6 citation
  (`_probe_authenticated`, auth_smoke.py:1015-1040) is correctly identified
  and corrected this round as a bare connectivity probe that parses neither
  field — the MATERIAL (silent-truncation-on-live-read) is real and now
  properly closed by reusing the node's own parser, not a second one.
- `get_authenticated` (http.py:116, confirmed) and `PERMITTED_METHODS =
  frozenset({"GET"})` (http.py:64, confirmed exact text "Barrier B1. The
  read-only slice dispatches GET and nothing else") — CONFIRMED the live
  read is GET-only, matching the plan's transport claim.
- Sign-agnostic rule: `Decimal(net) != 0` and RED test (18) (negative
  `net_position` refuses identically to positive) — directly closes the
  round-6 MINOR (untested NO/short-YES netting). No contradicting logic
  found.
- `docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,19` — grep-confirmed
  verbatim: line 1 "100% of decisions die upstream of pricing", line 19
  "No decision has ever reached the pricing gate." Matches the plan's
  citation exactly, grounding the settle-or-exit-wait acceptability
  argument in a real, checked artefact rather than an assertion.

## Sweep
No new defect found. The three round-6 items (MATERIAL: live-GET
pagination/eof gate; MINOR: untested NO-leg sign; MINOR: unstated wait
acceptability) are each closed with source-grounded mechanism, not prose
alone, and each is backed by an objective RED test (15)-(18). The
un-followed pagination cursor (R-4P-2) is disclosed as a residual in the
fail-closed direction (refuses rather than risking a partial-page false
"flat"), which is the correct posture, not a gap. The wait-acceptability
paragraph correctly separates "cost" (A1 stays unenforced during the wait,
the pre-existing status quo) from "likelihood" (zero decisions reach
pricing today) and states the un-bounded-refill residual honestly rather
than hiding it.

## Rubric (20/20/15/20/15/10 = 100)
- Fidelity to audit gap & completeness: 20/20 — every prior MATERIAL/MINOR
  across three rounds is closed with a source-grounded mechanism and a
  test, not a documentation patch.
- Technical correctness & evidence grounding: 20/20 — every file:line
  re-checked this round matches verbatim, including the correction of the
  round-6 citation itself.
- Implementation specificity & feasibility: 15/15 — parser reuse
  (`_declared_positions`), transport (`get_authenticated`), and the
  sign-agnostic comparison are all concretely specified with no remaining
  underspecified mechanism.
- Acceptance criteria & validation quality: 20/20 — 18 objective RED tests
  now cover staleness, newer-fill/exit, non-eof/partial pages, shape drift,
  and sign-agnostic netting.
- Autonomous operation, failure handling & recovery: 15/15 — fail-closed
  end-to-end (UNKNOWN=open=refuse, no override, cursor-incompleteness
  refuses); the wait's cost and residual are both stated honestly.
- Portfolio alignment, scope, dependencies: 10/10 — unaffected, unchanged.

**Total: 100/100.**

No HUNT-1/live-enablement/operator-cap violations found. No MATERIAL or
MINOR defect remains that I can find after re-verifying every load-bearing
citation in this round against current source.

## Blockers
None.
