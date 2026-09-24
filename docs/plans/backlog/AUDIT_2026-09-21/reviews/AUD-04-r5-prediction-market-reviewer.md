# AUD-04 — Round 5 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
sha256: cf97bd4661a367b267a8bd2f077b171ea02b90f0152ed65fec69ceb0d568c711
Round: 5 (final)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claim verified: `SETTLED_THROUGH` cutoff, `PROVISIONAL_IN_FLIGHT`, anti-suppression test, AC #12

`SETTLED_THROUGH = D_now − max(7, observed p99 settlement_lag_days)` is present in the plan body
(§6 D4, not only §13), with the `7` floor tied to the structural fallback lag
(`trial_scorer.py:243`, `_resolve_settlement_basis` admitting `venue_last_fair_price_fallback` only
once `now_ns >= scheduled_release_at_ns + _SEVEN_DAYS_NS`) and the p99 read from step 0(f)'s
measured distribution rather than a literal — CONFIRMED. Days after the cutoff are computed,
printed, labelled `PROVISIONAL_IN_FLIGHT`, and excluded from the cumulative pass/fail determination
both ways (cannot breach it, cannot clear it) — CONFIRMED. The RED test
`test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check`
with its anti-suppression half (the identical breach placed at `D ≤ SETTLED_THROUGH` still FAILS) and
AC #12 are both present.

## The coordinator's specific check: can a permanently unscored settlement hide in the provisional tail forever?

**No — but not for the reason the cutoff fix addresses, and the mechanism has a real, deeper gap the
cutoff does not close.** I re-derived the cash identity against its own term scoping (§6 D4):

- `capital_deployed(D)` = Σ over fills whose **open** is dated `D`, of `cost + fee` (booked once, on
  the open day).
- `proceeds(D)` = Σ over positions whose **settlement** is dated `D`, of `payout` (booked once, on
  the settlement day, if it ever occurs).
- `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`.

For a position that opens on day `D1` and **never settles**: on `D1`, `Δbalance(D1)` reflects the
actual cash outflow of opening it (`−cost−fee`, all else equal), `proceeds(D1) = 0` (nothing settles
that day), and `capital_deployed(D1) = +cost+fee`. Substituting:
`unexplained(D1) = (−cost−fee) − 0 + (cost+fee) = 0`. **This holds by construction, regardless of
whether the position ever settles** — the deployment leg cancels against the balance leg on its own
day, and there is no settlement day, ever, on which a mismatch could appear. I checked the plan for
any companion mechanism (open-position aging, a maximum settlement horizon, a "days since open with
no proceeds" check) and found none — no occurrence of "still open", "position age", "unsettled",
"stuck", or "settlement horizon" anywhere in the document, and `SETTLED_THROUGH` only gates *when a
day's cumulative figure becomes gating*, not *whether a specific position's absence of proceeds is
ever compared against anything*.

**Consequence: the cash identity as specified cannot, at any cutoff, detect "this position opened and
never settled."** It is not merely that such a position hides in the provisional tail for
`max(7, p99)` days — once its open day `D1` crosses `SETTLED_THROUGH` and becomes gating, the
identity still reads `unexplained(D1) = 0` (a clean PASS) forever, because the term that would flag
a stuck position (proceeds arriving late or never) is scoped to the settlement day, which for a
permanently stuck position never exists. This is a distinct and more serious version of the
coordinator's question than "hides in the tail" — it hides **everywhere**, permanently, and the
report would show a fully reconciled, green cumulative figure while capital sits in a position that
silently never resolves. This is exactly the kind of operator-invisible failure this backlog's whole
premise (measurement before money) exists to prevent.

I checked whether this is legitimately another item's scope before scoring it as a defect here:
AUD-07 (closed, not re-reviewed) tracks whether the position **corpus is growing** (`n_positions_new_
since_previous_run == 0`), which is a pipeline-liveness signal, not a per-position aging check — a
healthy, growing corpus with one silently-stuck position inside it would not trip AUD-07's control.
Grepped AUD-07's plan text for the same terms with the same negative result. This gap is not covered
elsewhere in the reviewed cluster, and AUD-04 is the item that owns the P&L reconciliation contract,
so it is the right place to name and close it.

## Defects

1. **MATERIAL — the cash identity cannot detect a position that opens and never settles, at any
   `SETTLED_THROUGH` cutoff, by construction.** Verified by algebraic substitution against the
   identity's own stated term scoping; no companion staleness/aging check exists anywhere in the
   plan.
   **Required change:** add a standing, independent open-position staleness check, distinct from the
   cash identity (which cannot carry this signal): for every `capital_deployed(D)` row, if no
   matching `proceeds` row has appeared by a registered maximum settlement horizon (e.g.
   `climate_day + N` days, or `D + max(7, p99) + a stated grace margin` — a quantity the plan must
   name, not leave to the implementer), flag it `PERMANENTLY_UNSETTLED` and alert through the
   existing sink, independent of and in addition to the cumulative pass/fail determination. Add a RED
   test constructing exactly this fixture (an open position, no proceeds ever, elapsed time far past
   the horizon) and asserting it is flagged rather than silently reading as `unexplained(D) = 0`.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **18** — every element of G-03 is covered and the
  settled-through cutoff closes round 4's gap cleanly. −2 for defect #1: a permanently-stuck
  settlement is exactly the class of "unexplained flow" this item's own charter (G-03,
  reconciliation) exists to catch, and it is currently unreachable by any check in the plan.
- Technical correctness and evidence grounding (20): **16** — the cutoff's derivation, its floor and
  its anti-suppression test are all correct and re-verified against source. −4 for defect #1: the
  central claim that the cumulative check is now safe to gate on is not fully true — it is safe
  against transient in-flight lag but blind to permanent non-settlement, and the plan does not state
  this limitation.
- Implementation specificity and feasibility (15): **13** — the cutoff, its labelling and its
  separate non-gating tail figure are all concretely specified. −2 for defect #1: no staleness-check
  module, threshold or test is named.
- Acceptance criteria and validation quality (20): **16** — AC #12 and its RED/anti-suppression pair
  are objectively checkable. −4 for defect #1: no AC would catch an implementer who ships the
  cash-identity check alone and never builds a staleness detector — exactly the failure mode this
  round's brief asks reviewers to hunt for.
- Autonomous operation, failure handling, recovery (15): **15** — the re-alert ladder (persisted,
  restart-surviving, one-way escalation, observable clear) is unaffected by this finding and remains
  fully met.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's evaluation contract,
  baselines and falsifier are unaffected by this finding.

**Total: 88/100**

## Required changes to reach 100

1. Add the standing open-position staleness/aging check described above, independent of the cash
   identity, with a named maximum-settlement-horizon quantity (measured, not a literal, matching the
   plan's own discipline elsewhere), a RED test with a permanently-unsettled fixture, and a new
   acceptance criterion requiring it.

## Blockers

None. This defect is fixable entirely within this plan's own text and does not require an
operator/strategy-lead ruling or another item's scope.
