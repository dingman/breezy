# AUD-06b review — round 3 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06b-bounded-allocation-sizing.md
sha256: 200bfecb3a00d457672e402ee827c8655ef69236daed3078bbf6fbc3b211274d
Round: 3

## Round-2 remedy verification

- **Step 7a's cap-free re-parameterisation (round-2 MATERIAL, mine, accepted):** CONFIRMED fixed by
  reuse, not by a second scheme, exactly as required. The sweep runs over AUD-06a's own `cap-shaped`
  axis (`qty_i = clip(floor(R/ask_i), 1, Q_MAX_VALIDATED)`, `R` imported from AUD-06a's recorded grid
  `{2,3,5,8,13,21}`, never re-chosen here), the output is a curve (CP-upper per `R`, and per
  `side_mix` where AUD-06a publishes one), and the gate is `max over the grid ≤ 0.025`. I confirmed
  this against AUD-06a's own revision-3 text (§6 "Output: the validated envelope AND its expiry
  condition", "Sweep axes") in the same review batch — the grid and the `R` values are cited
  identically in both plans, which is exactly what "imported, never re-chosen" requires.
- **AC#6 restated over a well-defined quantity (round-2 MATERIAL consequence, accepted):** CONFIRMED —
  the merge-blocking criterion is now `max over swept R (and side_mix) of CP_upper ≤ 0.025`, objectively
  computable from the sweep table, not an ambiguous "the realised qty distribution".
- **`ENVELOPE_SWEEP_RECORD_SHA256` re-run trigger (round-2 MINOR, pm, accepted):** CONFIRMED —
  `test_the_pinned_envelope_sha_has_a_matching_pre_merge_sweep_record` is specified to go RED on a
  pin bump with a stale sweep record, closing the gap where AUD-06a could re-derive its envelope and
  only the sha pin (a runtime check) would move, with no fresh pre-merge sweep (a one-time CI check)
  re-run against the new artefact. This is a genuine, mechanically-enforced coupling between the two
  items rather than a documentation note.
- **G2 edge-unit contract (round-2 MINOR, pm, accepted):** CONFIRMED — `edge_unit:
  "usd_per_contract_after_fees"` as a refused-if-absent-or-different field, PLUS a structural
  `abs(edge_ci_*) > 1.0` sanity check independent of the producer's own label. Two independent
  enforcements of the same invariant is good defense-in-depth for exactly the failure this repo has
  already had once (a unit/sign confusion in a statistic feeding a decision).

## Fresh review of the full revision — no new material defect found

I specifically checked, per this review round's brief, whether step 7a genuinely reads no cap value:
the driver "reads the ask tape, applies `derive_order_quantity` under swept `R`" — since `R` is a
dimensionless ratio and the sweep never learns which `R` the live system occupies (the gate requires
the bound to hold at *every* swept `R`), this is a sound construction; `derive_order_quantity` itself
is monotonic in `cap` (round-2's finding), and sweeping the dimensionless proxy `R` rather than
`cap` avoids ever materializing the cap in the sweep's inputs or outputs. `test_the_premerge_sweep_reads_no_operator_reserved_value`
is the correct guard for this property.

I also checked the AC#9 cohort-review rule for the same sample-size-honesty concern AUD-04 was
required to state explicitly (an n=10 cohort being read as if it were powered evidence): AUD-06b's
own §11 table states the evaluation reads AUD-04's `n_fills`/`power_caveat` fields as an "honesty
gate... read BEFORE any of the above" — so the n-power caveat is inherited through AUD-04's schema
rather than needing to be restated here. I find no gap in this chain.

The four BLOCKERs (A: AUD-06a's envelope; B: AUD-02's edge, itself downstream of AUD-05; C: R-12
operator ruling on the session order-count ceiling; D: the per-position spend question) are correctly
named as blockers rather than decided, and none is resolvable by this or any prior review round.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **17** — matches round 2/3 self-score; re-scopes MP-B
  faithfully and adds the edge-gate artefact the source audit could not have named; `max_equity_fraction`
  remains a stated, triggered deferral rather than a silent drop.
- Technical correctness and evidence grounding (20): **16** — matches round 2/3 self-score; the IOC
  disposition, the native per-order notional cap, and the cent-rounding reuse were independently
  re-verifiable this round via citations cross-checked elsewhere in this batch (e.g.
  `_round_cost_up_to_cent` at `operator_controls.py:220-244`, confirmed while reviewing AUD-04); the
  `R` grid and the `1.0` USD sanity bound remain reasoned constructions, appropriately not over-claimed.
- Implementation specificity and feasibility (15): **11** — matches round 2/3 self-score; the sweep is
  now executable as specified, but the new offline driver is scoped, not written, and depends on an
  AUD-06a entry point that does not exist until that item ships — an honest, correctly-named
  sequencing gap rather than a hidden one.
- Acceptance criteria and validation quality (20): **16** — matches round 2/3 self-score; AC#6 is now
  objectively verifiable, AC#7b/#7c/#7d each add a negative control; AC#8/#9 remain unexercisable
  until trading resumes, declined rather than softened (correctly, per round 2's disposition #8 — a
  softened money-path acceptance criterion would be the wrong fix).
- Autonomous operation, failure handling, recovery (15): **12** — matches round 2/3 self-score; both
  gates and every clamp are fail-closed with no silent fallback to qty=1; the mid-session lapse rule
  (IOC never rests, fail-closed for new orders only, never touches an already-submitted order or open
  position) is now stated and grounded in `continuous_strategy.py:2531-2540`, independently plausible
  given IOC semantics.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 is a complete field-level
  evaluation contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as
  load-bearing rather than softened, a cohort-review revert rule and a falsifier. The round-2 mle
  deduction (5/10) cited only "the honest structural ceiling" with no named, fixable defect, while pm
  gave 10/10 on the same text across two rounds. I find no additional defect this round and award in
  full per this round's instruction — this remains the correct scoring outcome for an item whose
  low expected value is a fact about the live record, not a construction defect in the plan.

**Total: 82/100**

## Required changes to reach 100

None found this round beyond the items already named and accepted in round 2 as structurally open
(the offline driver being unwritten; AC#8/#9's dependency on trading resuming) — both are honestly
disclosed rather than hidden, and neither is closable by a text change alone.

## Blockers

- **BLOCKER-A (AUD-06a):** the validated qty envelope and its staleness predicate — unchanged, genuine.
- **BLOCKER-B (AUD-02):** a demonstrated edge for this family, itself downstream of AUD-05 — unchanged,
  genuine, and correctly the largest structural reason this item is P3.
- **BLOCKER-C (operator):** R-12, the session order-count ceiling question — unchanged, genuine,
  operator-only.
- **BLOCKER-D (operator):** the per-position spend question — unchanged, genuine, operator-only, posed
  but not answered by this plan as required.
