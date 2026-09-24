# AUD-06b — Round 2 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
SHA256: a7c4628ed4b51ed45f021f8e99c0f8202c635349a8f522a26f35b422994d7eca
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)

## Round-1 defect disposition verification, and the brief's specific checks

**Specific check 1 — EDGE_GATE symmetric with the envelope gate, fail-closed, no silent qty=1
fallback.** CONFIRMED, and this was my own round-1 MATERIAL finding (the asymmetry between a
sha-checked BLOCKER-A and a commit-message-asserted BLOCKER-B). §6 G1/G2 now put both constants in
one module, `src/breezy/persistence/sizing_gates.py`, built on the existing sha-recompute idiom.
Independently re-verified this round: `src/breezy/persistence/gs_boundary_artefact.py` (the pattern
the plan says G1/G2 follow) genuinely implements `inputs_sha256` recompute-and-refuse at
`load_boundary_artefact:219-266` — the precedent is real, not asserted. `derive_order_quantity`'s
five refusal conditions (§6) are symmetric across G1 and G2 (absent/mismatched sha; wrong
`family_id`; CI not excluding 0; stale envelope; `Q_MAX_VALIDATED < 1`), and §6 states explicitly
"it does not fall back to qty=1 and it does not warn," backed by
`test_sizing_refuses_rather_than_falling_back_to_qty_one_when_a_gate_is_unsatisfied` (§7 step 1) and
AC#1's negative-control requirement. This is the correct fix for the largest defect in round 1.

**Specific check 2 — the bounded first cohort must not assign or imply a value for either operator
cap.** CONFIRMED. `COHORT_QTY_CEILING = min(Q_MAX_VALIDATED, 2)` (a contract count) and a 10-order
first-cohort window (an order count) are both dimensionless build-side constants; neither reads,
restates, defaults, or bounds either the per-position dollar cap or the daily dollar budget. §12
states this explicitly ("neither is an operator-reserved cap and neither assigns a value to one").

**Specific check 3 — partial rejection of the depth-staleness constant (D3), verify at
`decision.py:~426-446`.** Re-checked against live source this round, independent of the plan's own
claim. `_evaluate_no_side` (`decision.py:424-446`) sources `size` for the NO side from
`inputs.bid_size` on the SAME `DecisionInputs` object the caller constructed for this evaluation,
passed into `_finalize_take` (`:373-420`), where the executable gate
(`executable_ask_lower < price < executable_ask_upper and size >= config.minimum_displayed_size`,
`:391-393`) runs against it directly — there is no separately fetched or cached ladder in this path,
confirming the plan's premise that the size clamp reads the triggering frame, not a second read. The
partial rejection (declining a new depth-staleness constant in favour of pinning the existing source
and adding `test_the_executable_clamp_reads_the_triggering_frame_not_a_cached_ladder`) is well
grounded and is the right call: a second freshness policy alongside `config.stale_observation_minutes`
would be a genuine divergence risk, not a control.

**Other round-1 items, spot-verified:**
- Native per-order notional cap (`RiskEngineConfig.max_notional_per_order`) staying load-bearing
  rather than relaxed: unchanged in this revision, correctly excluded in §5.
- `_round_cost_up_to_cent` reuse for the cent-safe floor: consistent with AUD-04's independently
  re-verified citation of the same function this round.
- Pre-merge realised-qty sweep (mle MATERIAL — was post-merge): CONFIRMED moved to a pre-merge gate
  (§7 step 7a), with the bounded cohort correctly retained as defence-in-depth rather than a
  substitute (§7 step 7b), and the load-bearing assumption (the realised qty distribution is
  reproducible offline from the sizing function + historical ask tape) stated in §12 with an
  explicit fallback-must-be-recorded-as-a-weakening clause if it proves false.

## Fresh review of the full revision (new defects)

**MINOR — G2's `edge_ci_lower <= 0` refusal condition assumes a sign/unit convention for "edge" that
this plan does not itself define, and AUD-02 (the producer) is outside this round's review set.**
File: AUD-06b §6 G2, §9.
Issue: the gate correctly refuses when the edge CI does not exclude 0, but "edge" here needs to be
unambiguously per-contract expected P&L in the same currency unit `order_cost_usd` uses (not, say,
a probability-scale edge or a per-dollar rate), or `E[pnl] × qty` in §3's own framing stops being
literally true. This is an interface risk between two plans reviewed in parallel, not a defect
within AUD-06b's own text, but AUD-06b is the consumer and the one item that can lose money on a
unit mismatch, so it is worth naming here even though it is not fully closeable from this plan
alone.
Fix: state explicitly in §6 G2 the exact unit AUD-02's artefact must publish `edge_ci_lower`/
`edge_ci_upper` in (USD per contract, after fees), and add a unit-sanity assertion at the gate (e.g.
refuse if `|edge_ci_lower|` is implausibly large relative to a typical ask, catching a
probability-vs-dollar unit confusion structurally rather than trusting the producer).

**MINOR — the pre-merge realised-qty sweep (§7 step 7a) re-runs AUD-06a's sweep at the realised
distribution but does not state which AUD-06a artefact sha it must be pinned against, leaving a
window where AUD-06a's envelope could be re-derived (a legitimate future event, since it is a
one-shot study) without this item's pre-merge gate being required to re-run.**
File: AUD-06b §7 step 7a, §6 G1.
Issue: G1 pins `ENVELOPE_ARTEFACT_SHA256` at the sizing-gate level (good, and correctly fail-closed
on mismatch), but step 7a's PRE-MERGE gate is a one-time CI check, not a runtime gate — so if
AUD-06a's envelope is later re-derived (its own §9 anticipates this) after AUD-06b has already
merged, there is no stated mechanism requiring step 7a's sweep to re-run against the new artefact.
G1's runtime sha-check would still catch a *mismatched pin*, but would not by itself trigger a fresh
pre-merge-style realised-qty sweep against the NEW envelope before it takes effect.
Fix: state in §7 step 7a (or §9) that any future re-derivation of AUD-06a's envelope requires
re-running the pre-merge realised-qty sweep before the new `ENVELOPE_ARTEFACT_SHA256` is pinned into
`sizing_gates.py`, not only that the runtime gate will refuse a stale/mismatched pin.

No MATERIAL defect. This is the money-moving item in the backlog and I held it to the highest
scrutiny in this round: the fail-closed posture is genuinely symmetric across both preconditions now
(the single most important fix), the cent-safe rounding is consistent with AUD-04's independently
re-verified citation of the same function, the depth clamp correctly reads the triggering frame with
no fabricated staleness surface, and no operator-reserved value is read, restated, defaulted, or
assigned anywhere in the text, including the first-cohort bound.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **18** — re-scopes MP-B rather than duplicating it, adds
  the edge-gate artefact the original audit could not have known about. −2 for deferring
  `max_equity_fraction` as a recommendation ("no for this increment") rather than a decision with a
  stated re-evaluation trigger.
- Technical correctness and evidence grounding (20): **18** — the native per-order notional cap, the
  cent-rounding reuse, and the D3 depth-clamp source are all independently re-verified against live
  source this round. −2 for the edge-unit ambiguity at the G2 interface boundary.
- Implementation specificity and feasibility (15): **12** — gate module, five refusal conditions,
  clamp source, cohort constants and merge gate are all named precisely. −3 for the offline-replay
  harness for step 7a being specified by intent rather than by a named driver, and the envelope
  re-derivation gap above.
- Acceptance criteria and validation quality (20): **18** — byte-identity merge gate, a property
  test, symmetric negative controls, a pre-merge envelope re-check, a cohort review rule. −2 because
  AC#8/AC#9 cannot be exercised until trading resumes — noted as a structural fact (see Blockers) but
  the criteria themselves would benefit from a stated fallback measurement if the drought continues
  materially past the first-cohort window.
- Autonomous operation, failure handling, recovery (15): **13** — every clamp and both gates are
  fail-closed with no silent fallback; the partial-rollback compensating control (bounded cohort) is
  named explicitly. −2 because rollback genuinely cannot act on already-open positions, and a
  mid-session gate lapse (e.g. envelope goes stale intraday) refuses new orders but the plan does not
  state whether/how an in-flight but unfilled order is affected.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 is a complete field-level
  evaluation contract with registered baselines, an explicit "this item can reduce ROI" row treated
  as load-bearing rather than softened, a cohort-review decision rule, and a falsifier. The low
  expected value today is a fact about the live record (no proven edge, forecast programme
  TERMINAL), not a defect of this plan's construction, and the plan does not overstate it anywhere I
  could find. Full marks; the four blockers are named separately below, per this round's scoring
  guidance, rather than deducted here.

**Total: 89/100**

## Required changes to reach 100

1. State the exact unit and currency convention AUD-02's edge artefact must publish
   `edge_ci_lower`/`edge_ci_upper` in, and add a unit-sanity assertion at the G2 gate.
2. State that any future re-derivation of AUD-06a's envelope requires re-running the pre-merge
   realised-qty sweep before the new sha is pinned into `sizing_gates.py`.
3. Turn the `max_equity_fraction` deferral from a recommendation into a stated decision with a named
   re-evaluation trigger (e.g., "revisit once AUD-04 establishes balance semantics," already implied
   but not made a criterion).
4. Name the offline-replay driver (or state that none exists and one must be built) for §7 step 7a.
5. State the in-flight-order disposition if a gate lapses mid-session (refuse new submissions only,
   or also cancel resting orders derived under the now-stale gate).

## Blockers

BLOCKER-A (AUD-06a's envelope + staleness predicate) and BLOCKER-B (AUD-02's family-scoped edge
artefact) are build preconditions, both now code-enforced rather than asserted — the central fix of
this revision. BLOCKER-C (R-12, the session order-count ceiling vs. derived qty) and BLOCKER-D (is
the per-position cap still the intended per-order spend once qty is derived from it) are genuinely
operator-only rulings this plan correctly poses without answering, and correctly gates merge on
(§7 step 7c: "sizing must not merge before R-12 rules"). No change to this plan's text can resolve
BLOCKER-C or BLOCKER-D; per this round's scoring guidance they are named here rather than scored
down.
