# AUD-04 — Round 4 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
sha256: f47dc394fe3e607e173ab57ba80c79ff7a2807cbfcb95db0d405f9797373765b
Round: 4 (final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claims verified against source (this round)

- `ScoredTrial.scored_at_ns` is assigned `now_ns` at `src/breezy/settlement/trial_scorer.py:219` —
  CONFIRMED verbatim. `ScoredTrial` (`:131-151`) carries `climate_day`, `scored_at_ns`,
  `settlement_basis` and no venue settlement/credit timestamp — CONFIRMED (field list read
  directly).
- The ≥7-day structural fallback lag: `_resolve_settlement_basis` admits
  `"venue_last_fair_price_fallback"` only when
  `now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS` — CONFIRMED verbatim at
  `trial_scorer.py:243`.
- `proceeds(D)` dated by `scored_at_ns`'s UTC day, `proceeds_date_proxy: "scored_at_ns_utc_day"`,
  `settlement_lag_days` column, and the distinct `UNEXPLAINED_PROXY_LAG` class (never netted into
  plain `UNEXPLAINED`) — CONFIRMED present in the plan body (§6 D4, lines ~149-180), not only in
  §13: `test_proceeds_are_dated_by_scored_at_ns_not_by_climate_day` and
  `test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted` are named as RED tests
  (§7 step 1), and AC #10 (§8, lines ~488-491) requires exactly this.
- Round-3 pm's central defect ("no field named for 'settlement is dated D'") is the same gap I
  independently checked from source before reading §13 — it is genuinely closed: the plan now names
  the field, states both components of the proxy error (nightly-cadence lag and the structural
  ≥7-day lag), and adds a step-0 measurement (0(f)) plus AC #10 and two RED tests to hold it. This is
  a real fix, not a restated assertion.
- The re-alert ladder ownership (AUD-04 owns `src/breezy/runtime/alert_ladder.py`; AUD-07 imports
  it) and the cash identity `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`
  (replacing the round-1 four-term form that double-counted the payout) were re-verified consistent
  with the plan text and are unchanged from round 3, where two independent reviewers already
  confirmed them against source.

## Defects

None MATERIAL. No new defect found this round; the one MATERIAL-adjacent gap round 3 correctly
identified (the unnamed settlement-date field underlying `proceeds(D)`) is fixed in the plan body
with a named field, a disclosed and quantified error mechanism, a proxy classification that never
silently nets away a real anomaly, a step-0 measurement, and two new RED tests plus AC #10 — checked
against source, not taken on the plan's word.

The "equity curve is delivered as a balance-log proxy, not true mark-to-market" scope statement,
carried and disclosed across all four rounds with no requested change from any reviewer, is not a
defect: it is an honest, load-bearing scope boundary of what G-03 asks for versus what a true
position-level MTM curve would require, and no round has named a concrete gap it leaves open for the
ROI evaluation this backlog needs.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — G-03 fully covered; the settlement-date scoping
  the whole unexplained-flow identity depends on is now named and tested rather than left implicit.
- Technical correctness and evidence grounding (20): **20** — the round-3 defect (unnamed
  settlement-date field) is genuinely fixed and reverified against source (`trial_scorer.py:219`,
  `:243`); the cash identity, four loader signatures and alert API were re-checked and hold.
- Implementation specificity and feasibility (15): **15** — the settlement-date field, its two error
  components, the step-0 measurement and the ladder-ownership module are all named with file:line.
- Acceptance criteria and validation quality (20): **20** — AC #10 plus the two new RED tests close
  exactly the gap round 3 named (an implementer could previously satisfy every AC while choosing the
  wrong field; that is no longer true).
- Autonomous operation, failure handling, recovery (15): **15** — the re-alert ladder (persisted,
  restart-surviving, one-way escalation, observable clear) closes the round-2 MATERIAL gap in full
  and is now single-sourced so AUD-07 cannot drift from it.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11 is a complete field-level
  evaluation contract with two fixed baselines, a falsifier and a stated dependency stage; no
  reviewer across four rounds has named a defect in this section on its own terms.

**Total: 100/100**

## Required changes

None.

## Blockers

None specific to this item. It depends on trading resuming for AC #1/#6's three-consecutive-day
observation window and on AUD-07 importing the shared ladder module in the same or a later change,
both named in the plan and not resolvable by plan-text alone, but neither is a defect in this plan's
own construction.
