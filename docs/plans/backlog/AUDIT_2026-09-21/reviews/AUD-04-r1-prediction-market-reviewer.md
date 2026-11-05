# AUD-04 — Round 1 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
SHA256: a75ce7cf6fee6214140f7439d3057b0e2f8924a3c6bfbb98571cd5eb68320964
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)

## Claims verified

- PortfolioAnalyzer citations (`analysis/analyzer.py:38`, `portfolio/portfolio.pyx:665-670`,
  `analysis/analyzer.py:208-211`, `backtest/engine.pyx:1446,1470,2211`, `analysis/tearsheet.py`):
  CONFIRMED against installed nautilus_trader==1.231.0 source. `record_trade` is gated on
  `updated_position.is_closed_c() and updated_position.realized_pnl is not None` exactly as quoted;
  `calculate_statistics`/`get_performance_stats_*` have no call site under `live/`. The plan's
  central "Nautilus analyzer is live-inert" claim is well grounded, not asserted.
- `DurableFillRecord` (client.py): CONFIRMED to carry `cumulative_fee` and a `fee_reconciled: bool`
  field, and `order_side` preserving sign with an explicit netting docstring ("a SELL record NETS
  against the longs (an R-8/R-9 partial exit)"). This substantiates I1's fee/side claims and
  confirms step-0(a)'s question ("reconciled or modelled fee") is real, not rhetorical.
- `redaction.py`: CONFIRMED it governs only headers/URLs/free text (SENSITIVE_HEADERS, `redact_url`
  re-export) and says nothing about balances — D6's claim that redaction is not the control here is
  accurate; the PRIVATE-artefact-only convention is the correct substitute control.
- Cross-check target: `exit_window_study/2026-09-20_nightly/exit_window_study.md` DOES report
  `sum_hold_pnl=-0.6100` and `n_positions=5` — AC #4's target value is real, not invented.

## Defects

**MINOR — NO-leg capital-deployed handling is correct by construction but untested explicitly.**
File: AUD-04 §6 I1, §7 step 1.
Issue: Per `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md:459`, the venue nets a held NO as a
short of YES at the venue level, while Breezy/Nautilus holds it as a LONG on the distinct `^no` leg
instrument (only BUY orders are ever mappable per `submit_chain.py:unmappable_order_reason` — "a
SELL is a naked short; refusing"). Because I1 reads Breezy's own leg-aware `DurableFillRecord`
ledger (not the venue's raw `netPosition`), summing "every fill" for capital-deployed is already
leg-correct by construction — a YES fill and a NO fill are two instruments, never netted against
each other. No re-derivation is needed, and D4's capital/proceeds split is fine once exits arm.
Failure: none today (no live exits exist), but the plan's RED test list (§7 step 1) has no test
covering a station-day with both a YES and a NO fill, despite this exact class of bug being the
subject of two corrected lessons in this repo's memory. An implementer under schedule pressure could
"simplify" the reader to a single per-station accumulator and reintroduce the netting bug the exit
plan already had to fix once.
Fix: add `test_a_no_leg_and_a_yes_leg_fill_on_one_station_day_are_both_counted_in_capital_deployed`
to §7 step 1, asserting the two legs are summed, not netted.

**MINOR — n=6 honesty is implied, not stated as a header caveat.**
File: AUD-04 §12 "Named risk".
Issue: The brief specifically asks whether the plan is honest that n=6 fills cannot demonstrate
improvement. §11 states the artefact's success is "binary and structural…never 'is the number good'"
and §12 names the risk of an operator reading P&L as a verdict on a family, mitigated by a header
statement that portfolio ROI and the sequential statistic are different estimands. That mitigates
conflation with PREREG, but does not itself warn that n=6 is statistically underpowered to show ROI
*improved* (vs. cash) — a reader could still misuse a positive ROI_B0 at n=6 as directional evidence.
Fix: add one explicit header line to the report template: "n=<k> fills; not a statistically powered
estimate of improvement over B0/B1 at this sample size."

No CRITICAL/HIGH-equivalent (MATERIAL) defect found in the denominator choice, fee handling,
deposit/withdrawal separation, or baseline design — all four are explicit, defensible, and
correctly scoped away from PREREG/annualisation.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): 17 — covers every element of G-03; "equity curve" honestly
  downgraded to an UNVERIFIED-semantics balance series.
- Technical correctness and evidence grounding (20): 17 — all cited Nautilus and repo source lines
  verified verbatim; central null-hypothesis question is correctly deferred to step 0 rather than
  assumed.
- Implementation specificity and feasibility (15): 12 — files/seams/reuse targets named; $0.05
  tolerance and balance-line parser anchor unspecified (author-conceded).
- Acceptance criteria and validation quality (20): 15 — measurable, includes independent cross-check
  (verified real); docked one further point for the missing NO/YES-leg partition test named above.
- Autonomous operation, failure handling, recovery (15): 12 — fail-closed on every input; no
  stale-input-growth detector (author-conceded, reasonable).
- Portfolio objective alignment, scope, dependencies (10): 5 — on-objective, tightly scoped; baseline
  choice (B0 headline) is a unilateral build decision, reasonably flagged as such.

**Total: 78/100**

## Required changes to reach 100

1. Add the two-leg (YES+NO same station-day) RED test to §7 step 1.
2. Add the n=6 power caveat to the report's header line.
3. Pin the $0.05 unexplained-flow tolerance to a measured basis (e.g., observed venue rounding) and
   specify the balance-line parser's anchor/regex.
4. Add a stale-input-growth detector (or explicitly defer it with a named follow-up item).

## Blockers

None. No operator-reserved value is touched; the plan is self-contained and actionable without a
ruling.
