# AUD-07 — Round 6 (delta) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
sha256: 911f5b8bf978a3a7f4ee69c68bedb0148b45c80bc4f84352dd6365f1b4b3da3f
Round: 6 (delta, final)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## My round-5 MATERIAL (sender-global family halt) — re-verified fixed

- `FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"` (`trial_day_latch.py:291`) — CONFIRMED
  exact, a single literal, non-family-parameterised key.
- `continuous_family_halt_key` (`trade_supervisor_core.py:158`) docstring — CONFIRMED verbatim:
  "Returns `CONTINUOUS_FAMILY_HALT_KEY` regardless of the argument… 'halted' is GLOBAL-equivalent to
  'this node's only sender is halted'… no matter which literal family id currently occupies that
  slot. A future increment that lifts cardinality-1 would need to widen this function's body… the
  parameter is threaded through now so that is a one-function change" — precisely what §12 now cites
  as the basis for deferring a family-scoped key to a separate future item.
- `submit_exit` (`exit_wiring.py:246`), veto at `:270-275` (`if strategy._latch.is_family_halted():
  … return`), state read at `trial_day_latch.py:1002` — all CONFIRMED exact.
- New PRECONDITION-2 (§4/§12), the positive-control sequence's step (0) (§5), `BLOCKED_FAMILY_HALT_SET`
  as a non-failure outcome, the clear→act→re-set citation to AUD-02 by id, and three read-only RED
  tests (§7 step 7c, AC #8c) are all present in the plan body, not only in §13. The honest "design
  tension" paragraph in §12 (a sender-global halt means an exit family cannot protect a halted entry
  family's positions) is a genuine acknowledgment, not glossed over, and its "acceptable today"
  grounds (no fill since 09-15; AUD-02b's refuse-to-set-while-open/UNKNOWN-is-open rule) are both
  independently confirmed present in AUD-02's own plan text (`open-position` / `refuse-to-set-while-
  open` / `UNKNOWN treated as open` all found at the cited sections).

**Fixed in full**, and the required change I asked for (state the precondition, add a check ahead of
the positive control) is exactly what was built.

## mle's round-5 MATERIAL (chronologically inverted no-peeking anchor) — independently re-derived, not taken on trust

Re-ran the chronology from git directly rather than trusting the plan's table:

| Commit | My own `git log -1 --format=%cI %s` | Plan's claim |
|---|---|---|
| `ebe7c46` | `2026-09-16T03:00:51Z` "position exit execution Rev 2…" | matches exactly |
| `bdcfd38` | `2026-09-16T03:06:57Z` "PREREG v4 (crh exit) DRAFT…" | matches exactly |
| `7c558a5` | `2026-09-16T03:24:56Z` "arming steps 0b and 1 retired by capture…" | matches exactly |
| `84d9042` | `2026-09-16T03:36:32Z` "Appendix A.3 — exit-window study result (R-DEAD 0/5…)" | matches exactly — **the anchor** |
| `537783a` | `2026-09-16T05:52:43Z` "§5.4 / PREREG v4 §5b two-layer AMBIGUOUS-exit cover…" | matches exactly — **the flagged row** |

All five timestamps reproduce to the second. The corpus fill-date table
(`POSITION_EXIT_EXECUTION_2026-09-16.md:476-480`) also reproduces exactly: earliest fill MIA `09-13`,
remaining four rows `09-15` — confirming `corpus_first_fill_date` (the old, wrong anchor) precedes
every 09-16 design artefact by construction and would test nothing, exactly as the fix states.

**The fix does not merely weaken the check into an unfalsifiable attestation.** It correctly
identifies a REAL post-anchor commit (`537783a`, the §5b two-layer AMBIGUOUS-exit cover) and flags it
`PROVENANCE_POSTDATES_READOUT` with a registration-time remedy (re-derive pre-anchor, or an explicit
ruling artefact with `n` reset to 0 excluding the N=5 rows — already the standing rule), rather than
silently passing it or excluding it from the corpus of parameters checked. The five new RED tests
include one exercising this real flagged row and one that fails a first-fill-date implementation, so
the fix is falsifiable in both directions.

## Regression sweep

- `exit_gate.py`'s empty-diff invariant, "no order/registration/positive-control/enablement" (AC #9),
  and DEP-2/DEP-3's sequencing are all unaffected by this revision.
- The halt-state read (step 0, §7 step 7c) is explicitly read-only and builds/sends nothing —
  consistent with this item's own "runs no control" framing throughout.
- No operator-reserved value is read, restated, defaulted or assigned; the AUD-02 citations are by id
  only, with no outcome of that item assumed.

No new defect found on a full re-sweep of both fixes and their surrounding text.

## Defects

None MATERIAL, none MINOR.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — both round-5 MATERIAL findings closed with
  precise, source-verified mechanisms; the authorisation chain and dependency sections now enumerate
  everything the arming decision needs, including the two gaps found this cluster.
- Technical correctness and evidence grounding (20): **20** — every citation independently
  re-verified exact, including five git-commit timestamps reproduced to the second from the
  repository itself, not taken from the plan's own claim.
- Implementation specificity and feasibility (15): **15** — the halt-state precondition, the
  per-parameter provenance classification, and the flagged-row remedy are all concretely specified
  with named tests exercising real, not hypothetical, data.
- Acceptance criteria and validation quality (20): **20** — AC #8b (corrected boundary, falsifiable
  both directions) and AC #8c (halt precondition, non-failure blocked state) are both objectively
  checkable.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected; the halt-blocked state
  is explicitly never recorded as a control failure, avoiding a false-page risk.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the design tension is
  recorded honestly rather than hidden, and the future family-scoped-halt item is correctly named as
  out of this item's scope.

**Total: 100/100**

## Required changes

None.

## Blockers

None text-fixable. Residual dependencies: PRECONDITION-1 (corpus growth, arming-decision-only),
PRECONDITION-2 (the shared family halt, closable by AUD-02b's clear→act→re-set route when needed),
DEP-2/DEP-3 (registration sequencing), and `RULING_A1`'s own §7 re-arm bar (not approached by this
item).
