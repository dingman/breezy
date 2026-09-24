# AUD-06b — Round 1 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
SHA256: 17adee53cb96fe92e87fb41a6923a72cba4101b222ac22ef2243389fb410d154
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)

## Claims verified

- `RiskEngineConfig.max_notional_per_order` native and wired: CONFIRMED. `risk/config.py:44` defines
  `max_notional_per_order: dict[str, int] = {}`; `risk/engine.pyx:192-196` (`_initialize_risk_checks`)
  installs it per instrument; `:675-679` reads it (`max_notional_setting = self._max_notional_per_order
  .get(instrument.id)`); `:912-917` denies with `NOTIONAL_EXCEEDS_MAX_PER_ORDER` exactly as quoted.
  The plan's "nothing is built for this, it is relied on" framing is accurate.
- `operator_controls.py`'s `ROUND_UP`-to-cent authorisation: CONFIRMED — `_round_cost_up_to_cent`
  uses `amount.quantize(_CENT, rounding=ROUND_UP)`, shared between `order_cost_usd` (the cap) and
  the ledger true-up, matching the plan's claim that authorisation and sizing "cannot disagree."
- `submit_chain.py` only-BUY-is-mappable / leg-aware instrument routing: CONFIRMED
  (`unmappable_order_reason`: "only a BUY is mappable (a SELL is a naked short); refusing").
  Relevant to my lens: this structurally forecloses the short-YES/NO-netting ambiguity this repo has
  previously been bitten by (see AUD-04 review) — sizing code built on top of this path inherits that
  safety property for free, which the plan does not claim but benefits from.

## Defects

**MATERIAL — the two hard preconditions (BLOCKER-A envelope, BLOCKER-B demonstrated edge) are
enforced asymmetrically, and the more dangerous one is unenforced.**
File: AUD-06b §7 step 0, §8 AC #1, §12 BLOCKER-A/BLOCKER-B.
Issue: BLOCKER-A (AUD-06a's non-empty qty envelope) IS machine-enforced — `Q_MAX_VALIDATED` is a
module constant "carrying the artefact sha," with a NEW test
`test_the_envelope_constant_carries_the_artefact_sha_it_was_derived_from` (§7 step 1) that fails the
build if the constant does not trace to a real published artefact. BLOCKER-B (AUD-02 publishing an
edge estimate for *this family* whose CI excludes 0) has no equivalent: §7 step 0 says only "Assert
in the commit message and the plan amendment that AUD-02 published an edge estimate…If either is
absent, stop." That is a human-diligence gate, not a test — there is no analogous sha-pinned
constant or CI-bound assertion tying the sizing code to a specific, verifiable AUD-02 artefact. This
is precisely the sizing-vs-edge failure class my checklist flags (sizing must not precede a
demonstrated edge, and that dependency must be structurally enforced, not asserted) — and it is
exactly the question the coordinator asked me to verify. The asymmetry matters because BLOCKER-B is
the one whose violation loses money (`E[pnl]×qty` more negative as qty grows when `E[pnl]<0`, per the
plan's own §3), while BLOCKER-A's violation only over-spends alpha. The repo has already made the
mirror-image mistake once (`POST_FORECAST_PHASE_2026-09-20.md` B-1: sizing/scoring keyed to the wrong
family's statistic) — the plan cites B-1 in step 0 but does not close the same hole for itself.
Failure scenario: an implementer (or an agent under schedule pressure) lands S2/S4b with a stale or
mis-attributed AUD-02 result cited in the commit message — nothing in CI catches it, because no test
reads AUD-02's artefact sha the way `test_the_envelope_constant_carries_the_artefact_sha_it_was_
derived_from` reads AUD-06a's.
Fix: add an `EDGE_DEMONSTRATED_ARTEFACT_SHA` (or equivalent) constant sourced from AUD-02's published
edge-estimate artefact, consumed the same way `Q_MAX_VALIDATED` consumes AUD-06a's, with a test
(`test_the_edge_gate_constant_carries_the_artefact_sha_it_was_derived_from`) asserting it resolves to
a real, family-scoped artefact before S2/S4b can be merged. Absent that, BLOCKER-B is a policy, not a
gate.

**MINOR — R-12 (session order-count ceiling) is correctly named as an operator blocker but its
interaction is described, not bounded, in the meantime.**
File: AUD-06b §9, §12 BLOCKER-C.
Issue: correctly deferred to the operator per the repo's binding constraint (never assign a value to
an operator-reserved control), and correctly flagged as a real dependency-in-fact rather than
fabricated or silently assumed. Not a defect in the ruling-deferral itself. But §9's exposure bound
("Worst-case daily exposure remains `min(daily budget, Σ cost_i)`…enforced under one lock") is stated
as unconditionally true today, when it is actually contingent on R-12 being resolved in a way that
does not let sizing outrun the count ceiling before the dollar ceiling binds — the plan should state
that this exposure bound is provisional until R-12 rules, not present it as already established.
Fix: qualify §9's exposure-bound sentence as "holds once R-12 is resolved; until then, sizing must
not merge" (which is already true given the ordered dependency in §4, but §9 reads as unconditional
on its own).

No other MATERIAL defect: the sizing formula, lot-size sourcing, thin-book/depth clamp, cent-safe
rounding, and byte-identity merge gate are all correctly specified and independently verified against
source where cited.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): 16 — re-scopes MP-B correctly; `max_equity_fraction`
  deferral is reasoned, not silent.
- Technical correctness and evidence grounding (20): 16 — every native citation verified against
  installed source; formula and re-pins correctly inherited from the MP plan.
- Implementation specificity and feasibility (15): 11 — `Q_MAX_VALIDATED`'s module and the
  depth-staleness bound unspecified (author-conceded); compounds with the gate-enforcement gap above.
- Acceptance criteria and validation quality (20): 13 — byte-identity and property tests are strong,
  but AC #1 ("gate evidence… cited by artefact path and sha in the commit") is not itself a test for
  the edge precondition the way it is for the envelope — docked for the asymmetric enforcement above.
- Autonomous operation, failure handling, recovery (15): 10 — every sizing clamp is fail-closed
  (refuse, not resize), which is correct and important; docked because the one precondition that can
  actually lose money is gated by commit-message diligence, not a fail-closed code path, which is the
  opposite of this item's own stated philosophy for every other clamp.
- Portfolio objective alignment, scope, dependencies (10): 3 — correctly the lowest-priority, most
  cautious item in the cluster; author's own self-score of 3/10 here is fair and this review agrees.

**Total: 69/100**

## Required changes to reach 100

1. Add a code-enforced, sha-pinned gate for BLOCKER-B (AUD-02's edge artefact), mirroring
   `Q_MAX_VALIDATED`'s treatment of BLOCKER-A, with a matching test.
2. Qualify §9's exposure-bound sentence as conditional on R-12's resolution.
3. Name `Q_MAX_VALIDATED`'s home module and the depth-staleness bound for the depth clamp explicitly.

## Blockers

BLOCKER-A (AUD-06a envelope), BLOCKER-B (AUD-02 edge), BLOCKER-C (R-12, operator), and BLOCKER-D
(operator: is the per-position cap still the intended per-order spend once sizing derives from it)
are all genuine and correctly left undecided here — none may be resolved by this plan or this review.
The MATERIAL defect above is about *how* BLOCKER-B is checked at merge time, not about resolving it.
