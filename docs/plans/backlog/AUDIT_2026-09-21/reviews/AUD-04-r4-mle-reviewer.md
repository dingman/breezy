# AUD-04 review — round 4 (FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: f47dc394fe3e607e173ab57ba80c79ff7a2807cbfcb95db0d405f9797373765b
Round: 4

## Claims verified (unchanged from the initial round-4 pass)

- `ScoredTrial` (`src/breezy/settlement/trial_scorer.py:131-151`) — no settlement timestamp field —
  CONFIRMED.
- `scored_at_ns=now_ns` assigned at `:219` — CONFIRMED.
- `_resolve_settlement_basis`'s `fallback_due = now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS`
  at `:243` — CONFIRMED.
- `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py:641`) — CONFIRMED, only
  `ts_event` (a fill time), no settlement/credit timestamp.
- Shared ladder module ownership (`src/breezy/runtime/alert_ladder.py`) legality for both consumers —
  CONFIRMED: both AUD-04's `scripts/analysis/portfolio_roi_report.py` and AUD-07's equivalent
  `scripts/analysis` module sit outside `[tool.importlinter]`'s `containers = ["breezy"]` layered
  contract (`pyproject.toml:58-92`), so importing `breezy.runtime.alert_ladder` from either is not a
  layer violation.

## Reconciliation (per the coordinator's request — every withheld point resolved to (a) a named,
fixable defect with a required change, or (b) awarded with any external cause recorded as a
BLOCKER/note)

**Fidelity to the gap and completeness — withheld 2/20 originally.** The sole reason given
("'equity curve' is delivered as a balance-log proxy, not a true mark-to-market equity curve") is not
fixable by any plan-text change: a genuine mark-to-market equity curve requires sampling live
order-book/position value at each point in the portfolio's history, an infrastructure component that
does not exist anywhere in this repo today (the only per-position mark-tracking that exists,
`position_monitor.py`'s `_MonitoredPosition`, is scoped to the exit-decision seam, not a historical
equity series, and building one is a materially larger, separate undertaking). This is external to
this item's scope, not an oversight the plan could close with a paragraph or a test.
**Disposition: AWARD in full.** **BLOCKER/note:** a true mark-to-market equity curve requires a new
position-valuation history pipeline; recommend a future backlog item; this item's balance-log cash-flow
proxy is the best measurement available today and is honestly and explicitly scoped as such (§11).
→ **20/20**

**Technical correctness and evidence grounding — withheld 2/20 originally.** One of the two named
reasons ("the step-0 null hypothesis about closed positions is still UNVERIFIED by design") is inherent
to RED-first practice — a plan cannot assert an empirical fact about the live record before measuring
it — and is awarded. **The second reason is a genuine, fixable defect found on this re-reading, not
previously named:** §6 D4's own text states the cumulative `Σ_D unexplained` is "the authoritative
detector" because "a proxy misdating produces equal-and-opposite per-day breaches that cancel" — this
is algebraically correct **only once both the credit day and the scoring day fall inside the measured
window**. For a live, continuously-updated report (this item's actual operating mode, not the closed
5-day worked example in §6), a settlement whose true venue credit already happened but whose
`scored_at_ns` UTC day has **not yet occurred** — up to the structural ≥7-day fallback lag the plan
itself derives from `trial_scorer.py:243` — produces a persistent, uncancelled `unexplained(D)` on the
credit day for as long as that report keeps running before the scorer catches up. The plan nowhere
states a "settled-through" cutoff (e.g., excluding the trailing `max(observed settlement_lag_days)`
days, or a stated conservative constant bounded by the structural 7-day figure) below which the
cumulative-zero invariant is not yet expected to hold. Without this, a report run near "today" can show
a nonzero cumulative `unexplained` that is not a bug, and nothing in the plan distinguishes that
transient state from a genuine reconciliation failure.
**Disposition: keep 1 point withheld. Required change:** add to §6 D4 a stated "settled-through" cutoff
— the report's cumulative `Σ_D unexplained` check applies only to days at or before
`D_now − max(7, observed p99 settlement_lag_days)`, and days inside that trailing window are reported
individually (still visible, still carrying `proceeds_date_proxy`/`settlement_lag_days`) but excluded
from the cumulative-zero pass/fail determination. → **19/20**

**Implementation specificity and feasibility — withheld 2/15 originally.** The sole reason ("the ladder
extraction adds a new module AUD-07 must sequence against, and a ship-order contingency... is stated")
is, on inspection, a concrete, testable mechanism, not a gap: the plan states AUD-04 owns the module,
AUD-07 imports it, the dependency is acyclic (AUD-07 → AUD-04 only, enforced by
`test_the_alert_ladder_module_imports_nothing_from_the_exit_window_study` and `lint-imports`), and a
named fallback exists if AUD-07 ships first (inline ladder plus a RED-on-divergence cross-test, deleted
on switch to the shared import). There is no further specificity a plan-text change could add — a firm
build-order mandate across two independently-scheduled backlog items is a coordinator/scheduling
decision, not something either plan's text can unilaterally impose.
**Disposition: AWARD in full.** → **15/15**

**Acceptance criteria and validation quality — withheld 2/20 originally.** One component (AC#1's
three-calendar-day observation window) is an unavoidable property of a control that must observe
three consecutive runs, and AC#4's dependence on AUD-07 shipping is an honestly-named cross-item
dependency — both awarded. **The second point is kept, tied to the same defect found under Technical
correctness above:** no acceptance criterion requires the settled-through cutoff, so nothing in §8 would
catch an implementer who ships the cumulative check without one.
**Disposition: keep 1 point withheld. Required change:** add an AC (e.g. new AC #12) requiring that the
cumulative `Σ_D unexplained` check excludes the trailing settled-through window from its pass/fail
determination, with a RED test asserting a synthetic in-flight (not-yet-scored) settlement inside that
window does not fail the cumulative check. → **19/20**

**Autonomous operation, failure handling, recovery — withheld 1/15 originally.** The sole reason ("every
rung still depends on the timer firing") is a property shared by every scheduled unit in this backlog
(AUD-05's D-F, AUD-07's D), named honestly rather than hidden, and is not a defect specific to this
plan's design — no plan-text change closes "a stopped systemd timer is only caught by systemd state."
**Disposition: AWARD in full.** → **15/15**

**Portfolio objective alignment, scope, dependencies — already 10/10.** No change.

## Final per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20**
- Technical correctness and evidence grounding (20): **19**
- Implementation specificity and feasibility (15): **15**
- Acceptance criteria and validation quality (20): **19**
- Autonomous operation, failure handling, recovery (15): **15**
- Portfolio objective alignment, scope, dependencies (10): **10**

**Total: 98/100**

## Remaining defect and required change

1. **MINOR.** §6 D4's cumulative `Σ_D unexplained` invariant has no stated settled-through cutoff, so a
   live/ongoing report can show a transient nonzero cumulative value near "today" purely from in-flight
   settlement lag (up to the structural ≥7-day fallback), indistinguishable in the plan's own text from
   a genuine reconciliation failure. **Required change:** state a settled-through cutoff (§6 D4) and add
   a corresponding AC/RED test asserting an in-flight settlement inside that window does not fail the
   cumulative check.

## Blockers / notes (external, not deductions)

- **Note (not a blocker):** a true mark-to-market equity curve is out of this item's scope; it requires
  a position-valuation history pipeline that does not exist in this repo. Recommend a future backlog
  item; this item's balance-log proxy is correctly and honestly scoped as a cash-flow measurement, not
  an equity curve.
