# AUD-17 review — round 2

Plan: AUD-17-operator-caps-proven-through-the-v4-live-composition.md
sha256: 3c6a9620311e66bcbebb7810d9345bfe24503b8fe74b709f984b3f067fc5aff4
Round: 2
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Round-1 disposition audit

Round 1: this reviewer 91/100 (no material defects, one MINOR — synthetic order left implicit);
silent-failure-hunter 81/100 (**two MATERIAL** — vacuous-pass risk on assertion 1, no positive
control). §13's disposition table records all five items. Independently re-verified each against
the current plan body and the artefact, with special attention to the reviewer's flagged
round-1-vs-round-2 correction (the per-position cause), which is the specific item this brief
asked me to verify:

- Disposition 1 (hunter, MATERIAL — per-position denial never pinned to its own cause) —
  CONFIRMED ACCEPTED and the correction is independently verified TRUE from source, superseding
  round 1's own (my) enforcement map. See below.
- Disposition 2 (hunter, MATERIAL — no positive-control/ADMIT case scoped as a deliverable) —
  CONFIRMED FIXED: the ADMIT case is §6 assertion 2, scoped FIRST at §7 17b step 1, and §8 item 3
  explicitly states a denial transcript without a green ADMIT is not acceptance.
- Disposition 3 (hunter, MATERIAL structural — §9-vs-§7/§8 inconsistency) — CONFIRMED FIXED: §9
  now carries an explicit case→step→acceptance-item mapping table; every row is traceable.
- Disposition 4 (architect, MINOR — synthetic order left implicit) — CONFIRMED FIXED: §6 now
  states explicitly that the driven `Order` is hand-built via Nautilus test-order helpers, not
  produced by the v4 strategy's own decision path, and gives the structural reason (caps enforce
  at the exec-client boundary, independent of sizing, which is blocked on R-11/MP-B).
- Disposition 5 (self-raised — two-permit-fixture cost) — CONFIRMED closed in §12/§6/§7.

No rejection in either round-1 record; none was warranted.

## The specific verification this brief required — independently re-derived from source, not
taken from the plan's own corrected table

**The per-position ceiling raises a PLAIN `LiveTradingPermissionError`, never
`SessionNotionalExhausted`.** Read directly from `operator_controls.py`:
- `:384-387`: `position_cap = operator_max_position_cost_usd(); if cost > position_cap: raise
  LiveTradingPermissionError(...)` — no subclass.
- `:418`: the daily-budget branch raises `DailyBudgetExhausted` (a distinct subclass).
- `:119-125` (the comment immediately above the `DailyBudgetExhausted` class definition): *"raised
  ONLY by the daily-budget branch of `DailySpendLedger.authorize_order_cost`... The per-position
  ceiling and the clock-rewind branch stay plain `LiveTradingPermissionError` -- neither means the
  day's dollar ceiling was reached."* CONFIRMED verbatim, operator ruling dated 2026-09-14.

Cross-checked against `exec/client.py`'s `_submit_order`, read in full for this round:
- `assert_live_order_submission_permitted(...)` at `:3489`, raising `SessionNotionalExhausted`
  caught at `:3497` (plan cites `:3489-3496` / `:3497` — exact).
- `self._ledger.authorize_order_cost(...)` at `:3524`, raising `DailyBudgetExhausted` caught at
  `:3529` (plan cites `:3524-3528` / `:3529` — exact), **and** the bare `except
  LiveTradingPermissionError as exc:` immediately after, at `:3532` (plan cites `:3531` — off by
  one line, immaterial; this is cause 3, the per-position ceiling and everything else that raises
  plain `LiveTradingPermissionError`).
- `_deny` at `:3293` (plan cites `:3293-3302` — exact); `is_exit_side = order.side ==
  OrderSide.SELL` at `:3520` (exact); `self._submit_veto` check at `:3484` (plan cites `:3485` —
  off by one, immaterial); `self._intent_reconciled is not True` at `:3534`, with
  `RECONCILE_NOT_RUN_REASON` denial at `:3537` (plan cites `:3535` — off by two, immaterial).

**Verdict: the plan's three-cause table and its central correction (round 1 conflated the
per-position ceiling with the permit-derived `SessionNotionalExhausted` gate; they are different
ceilings at different call sites) are CONFIRMED CORRECT against source, exactly as revised.** The
handful of ±1-2 line citation drifts found above do not affect the substance of any claim and are
of the same trivial class already disclosed elsewhere in this backlog (AUD-13's `:821`→`:882`);
none is load-bearing for a design decision.

**The ADMIT positive control gating acceptance — independently checked for the vacuity risk the
brief specifically asked about.** §8 item 3 states plainly: "The ADMIT case must be green before
any denial case is accepted as evidence — a denial transcript submitted without it is not
acceptance." §7 17b scopes the ADMIT case as step 1, before any of the five denial/boundary tests.
Combined with the per-position "differential" (the same order, same composition, same permit,
denied at one ceiling and admitted when only that ceiling is raised — §6, §7 17b step 3, §8 item
4), this closes the exact vacuous-pass shape hunter's round-1 defect 2 identified: no denial
assertion in this plan can be satisfied by a harness that denies everything for an unrelated
reason, because (a) a success must be demonstrably reachable through the identical wiring, and (b)
a per-position denial specifically must be shown to vanish when — and only when — that one ceiling
moves.

## Additional claims verified this session

- `tests/unit/operator_control_env.py`'s docstring — read in full; independently confirms the
  "names no control, carries no value, restores in a `finally`" claims and the "exactly one path
  may [inject a value]" whitelist language the plan quotes.
- `test_operator_reserved_controls.py:708` (`test_the_mechanism_has_no_production_call_site_yet`)
  — read in full, including its body. The test's actual assertion pins the **set of files that
  import `operator_controls`** (an exact 6-file list), not the ledger-construction mechanism
  itself — the test's own name is stale relative to its docstring, which already documents six
  declared importers including `factories.py` and `safety.py`. This is exactly the ambiguity §7
  17a step 3 flags for the implementer to resolve ("determine which mechanism that test actually
  pins... report the answer either way") rather than assuming either reading. Correctly scoped as
  an open investigative step, not a defect in this plan.
- `pm_us_crh_v4.json` under `deploy/families/` — presence confirmed (round 1 carry-forward,
  unchanged).

## Defects

No MATERIAL defects found. No independently-found MINOR defects beyond the trivial ±1-2 line
citation drift noted above, which affects no claim's substance and required no correction to
accept.

## Per-criterion points (cap: 20/20/15/20/15/10)

- Fidelity to the audit gap and completeness: 20/20 — closes G-16 exactly as stated, and the
  revision's own re-verification surfaced and correctly fixed a THIRD denial cause the original
  gap description did not know about, which strengthens rather than narrows the closure.
- Technical correctness and evidence grounding: 20/20 — the three-cause table, every exception
  type, every catch site, the latch behavior, and the exit-side branch were independently
  re-derived from source this session (not from the plan's own text) and match exactly, including
  the specific correction this brief asked to be checked.
- Implementation specificity and feasibility: 15/15 — ten named tests in dependency order, an
  attribution strategy (type discrimination + imported-constant reason-equality + differential)
  that survives the layer-B file-set constraint with a stated empirical fallback, the synthetic-
  order bound now explicit with its structural reason, and the two-permit-fixture cost named.
- Acceptance criteria and validation quality: 20/20 — eight items; the ADMIT case gates every
  denial's acceptance; the differential is a required transcript element, not optional; three
  `git diff`-empty guards plus a layer-B file-set check make "weaken a safety test to go green"
  mechanically detectable.
- Autonomous operation, failure handling, recovery: 15/15 — directly targets the unattended-spend
  bound across a 10-hour permit and nightly relaunch; neither-control-set, boundary-admit
  (exactly-at-ceiling/-budget), no-cost-on-refusal, and the latch-must-not-be-cleared rule are all
  pinned as named tests; adds no new runtime control, correctly (this is a verification item).
- Portfolio objective alignment, scope, dependencies: 10/10 — no cap value or magnitude is read,
  assigned, or implied anywhere in the plan; R-12 (session order-count ceiling) and sizing
  (G-11/MP-B, blocked on R-11) are correctly excluded to their own owners; test-only change means
  rollback risk is nil.

**Total: 100/100**

## Required changes for full marks

None. No point was withheld without a nameable defect and required change; none could be named
this round. The trivial ±1-2 line citation drifts noted above do not rise to a defect (no claim's
substance depends on the exact line) and are noted only in the interest of completeness.

## Blockers

None named by the plan and none found independently. R-12 remains open and is explicitly and
correctly out of scope; this item creates no new ruling need and touches no operator-reserved
value.
