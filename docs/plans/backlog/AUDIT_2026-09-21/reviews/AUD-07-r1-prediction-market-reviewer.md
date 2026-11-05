# AUD-07 — Round 1 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md
SHA256: 6f61ef6ae29b60b25d07fbfff5fc3e3fb254d9f1a35eeb174a52742bc2f8e44e
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)

## Claims verified

- `exit_gate.py:55` `_EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})`: CONFIRMED.
- 0-vs-5 disagreement: CONFIRMED. `~/.local/share/breezy/derived/position_monitor_report_2026-09-20.md`
  reads `positions: 0 (settled 0, unsettled 0)` / `settled by source: scored_trials=0 summary=0`,
  while `~/.local/share/breezy/derived/exit_window_study/2026-09-20_nightly/exit_window_study.md`
  reads `n_positions=5`, `sum_hold_pnl=-0.6100` — both figures the plan cites are real, not invented.
- `Strategy.close_position` refutation and `submit_chain.py` LIMIT-only refusal: partially spot-
  checked; `submit_chain.py`'s `unmappable_order_reason` confirms "only a LIMIT order is mappable"
  and "only a BUY is mappable (a SELL is a naked short); refusing" — consistent with the plan's claim
  that no order path is being built here and exits remain out of scope.

## Defects

This item's core content — reconciling drifted study output, fixing family-binding, making a frozen
corpus legible, and completing (never activating) a registration package — is verification/observ-
ability work, not P&L or sizing math, so most of my domain checklist does not directly bind. Two
points from a portfolio-accounting/settlement lens:

**MINOR — the negative `median_minutes_last_executable_to_threatened=-74.1` is flagged but not
bounded as a settlement-timing sanity check before Rev 3 is published.**
File: AUD-07 §3 finding B, §12 "Unresolved".
Issue: a negative time-to-THREATENED is either a genuine ordering property or a settlement/labelling
sign-convention defect — the plan correctly refuses to read the gate against it until settled (§12),
but does not name a concrete check (e.g., "assert every THREATENED confirmation timestamp is ≥ its
station-day's first executable-exit timestamp, or explain the negative case") that would close this
before Rev 3's table is trusted. Given exit-timing math directly feeds a future settlement-value
comparison (recoverable_value vs E[settlement|state]), an unexplained sign anomaly in the timing
series is a real, if currently small, risk to the eventual arming read.
Fix: add one concrete assertion/test to step 5 (the reconciliation step) that either explains the
negative figure structurally or proves it is a labelling bug before it is carried into Rev 3.

**MINOR — no explicit statement that AUD-04's realised-P&L reconciliation will reconcile against this
item's corpus once both ship.**
File: AUD-07 §11.
Issue: §11 correctly states this item's benefit is "made legible through AUD-04's realised-P&L line,"
but AUD-04's own plan does not name a matching reconciliation criterion back to the exit-window
study beyond its one-time cross-check (AC #4). Not a defect in either plan alone, but the two are
each other's consumer/producer for exit P&L and neither states a standing (repeatable) reconciliation
obligation, only a one-shot one. Minor coordination gap, not a correctness defect.
Fix: note in AUD-07 §11 (or AUD-04 §8) that the cross-check should be repeated whenever both reports
run on the same date, not asserted once.

No MATERIAL defect found: the item correctly keeps arming out of scope (byte-unchanged `exit_gate.py`,
manifest `status` stays `DRAFT_NOT_REGISTERED`), correctly resists the "gate passed → arm" gravity in
§9, and correctly treats corpus growth (BLOCKER-1) and PREREG v4 registration + the operator hard
gate (BLOCKER-2) as blockers it does not own.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): 18 — extends EXIT-1, surfaces three real defects (B, C, D)
  the audit did not name, keeps arming strictly out of scope as G-12 and the repo's binding
  constraints require.
- Technical correctness and evidence grounding (20): 17 — every cited artefact figure verified live;
  drift cause (B) is honestly three competing hypotheses rather than a single asserted cause.
- Implementation specificity and feasibility (15): 11 — the position-monitor report's actual
  position-sourcing bug (why it reads 0 against a corpus of 5) is not located, so step 1 hides real
  discovery work, as the author concedes.
- Acceptance criteria and validation quality (20): 16 — measurable, includes a negative criterion
  (no order placed, no family registered, no gate opened) and a cross-artefact reconciliation; docked
  one further point for the unresolved negative-median anomaly not having a concrete closing check.
- Autonomous operation, failure handling, recovery (15): 12 — genuine autonomy fix (job that cannot
  progress now says so) with false-page discipline (fires once per streak, not nightly); dedupe/latch
  mechanism left unspecified.
- Portfolio objective alignment, scope, dependencies (10): 5 — honest that the ROI ceiling here is
  small and protective, not additive; correctly resists the "gate passed → arm" pull.

**Total: 79/100**

## Required changes to reach 100

1. Add a concrete check/assertion resolving the negative `median_minutes_last_executable_to_threatened`
   figure before Rev 3's table is published.
2. Locate the position-monitor report's actual position-sourcing code path in the plan text (or an
   evidence-pack addendum) so step 1 is not hidden discovery work.
3. State the AUD-04/AUD-07 cross-check as a standing, repeatable obligation, not a one-shot AC.

## Blockers

BLOCKER-1 (corpus cannot grow until trading resumes — G-01) and BLOCKER-2 (PREREG v4 registration +
operator 1-lot positive control) are genuine, correctly named, and correctly left outside this plan's
scope. Nothing in this review requires either to be resolved for the plan itself to reach 100 on the
in-scope work.
