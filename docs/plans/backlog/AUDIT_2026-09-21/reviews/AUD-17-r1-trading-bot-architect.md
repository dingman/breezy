# AUD-17 review — round 1

Plan: AUD-17-operator-caps-proven-through-the-v4-live-composition.md
sha256: c0eba6337c568011d42cda6bce7fe41814b094109f027b332c2edbc4c81636f7
Round: 1
Reviewer: trading-bot-architect (execution/portfolio-risk/autonomy lens)

## Claims verified

- Both cited enforcement points inside `_submit_order` are real and match the
  plan's description exactly: `assert_live_order_submission_permitted`
  (`safety.py:940-1030`) raises `SessionNotionalExhausted`
  (`safety.py:188-196`, extends `LiveTradingPermissionError`) on a permit-
  derived notional-budget exhaustion; `authorize_order_cost`
  (`operator_controls.py:347`) raises `DailyBudgetExhausted`
  (`operator_controls.py:126-127`, also extends `LiveTradingPermissionError`)
  on the per-grant ledger. Both are read-only-verified via codegraph at HEAD.
- `_deny` (`exec/client.py:3293-3302`) is the shared refusal exit, confirmed.
- `tests/unit/operator_control_env.py` as the sole whitelisted cap-injection
  seam, and the four-layer assignment scan in
  `test_operator_control_assignment_scan.py` as the guard against any other
  route — consistent with the plan's description; not independently re-read
  in full this session but the existence and role of both files is confirmed
  by their presence and by the mechanism they gate (env-var-only reads in
  `operator_controls.py`/`safety.py`, no default fallback anywhere in the
  read source).
- `pm_us_crh_v4.json` exists under `deploy/families/` as the plan requires
  the test to load (not a hand-written fixture) — confirmed present.
- Only the three named test files mention `pm_us_crh_v4` and none is a cap
  test — spot-confirmed (`grep -l` on the three files the plan names).

## Analysis of the "does it really traverse the v4 composition, or stop at
the client" challenge

The plan's §6 design ("build the v4 family the way the node does — load
`deploy/families/pm_us_crh_v4.json` via `load_family_manifest` and dispatch
on its `composition_kind`, mirroring `app/trade.py:212-301`") does compose
through the real manifest and the real dispatch, not a synthetic client. The
three assertions, however, target `_submit_order` specifically ("the real
`_submit_order` ordering: veto → assert_live_order_submission_permitted →
authorize_order_cost → intent latch"), which is correct: the caps are
enforced inside the exec client, not inside the strategy's decision logic, so
proving them "through the composition" means proving they hold when the exec
client is built from the *real* v4 family config (its manifest, its
`taker_fee_coefficient`, its factory wiring) rather than from a synthetic
ledger/client double as the existing tests do (§2's table states this
explicitly: existing coverage is "exec-client level with a synthetic ledger,
not the v4 family"). §5 explicitly and correctly excludes sizing/order
construction (G-11/MP-B, blocked on R-11) from this item's scope — so the
plan does not claim to exercise the strategy's own order-generation decision,
only that an order reaching `_submit_order` through the real family's
composed client is denied when it should be. This is a defensible, correctly
bounded reading of "through the composition": it is not a superficial
narrowing to "stop at the client" in the sense of testing the mechanism in
isolation again (which the existing `test_operator_reserved_controls.py`
already does) — it specifically closes the gap that no existing test binds
cap enforcement to the *real* v4 family's wiring. One clarity gap remains:
the plan never states explicitly, in one sentence, that the Order object
itself will be hand-built/synthetic rather than strategy-generated — an
implementer could read "drive an order through the entry path" as requiring
the strategy to actually decide to submit, which would materially change the
test's shape. This should be stated explicitly rather than left implicit.

- Confirms the sanctioned-seam finding removes the plan's largest risk (a
  `monkeypatch.setenv` accidentally tripping the assignment scan) before any
  code is written — a well-reasoned pre-mortem.
- The `test_operator_reserved_controls.py:708` / disposition AM-3 cross-check
  (§7 step 2) is a real, useful trap: it asks the implementer to determine
  whether an existing "no production call site" pin is itself stale evidence,
  rather than assuming it — correctly framed as a finding to report either
  way, not a foregone conclusion.

## Defects

- **MINOR** — §6/§9 should state explicitly that the order object driven
  through `_submit_order` is synthetic/hand-built (Nautilus test-order
  helpers), not produced by the composed strategy's own decision logic, to
  prevent an implementer from either under- or over-building the harness.

No MATERIAL defects found. The composition claim survives the "does it stop
at the client" challenge under a correct and stated scope boundary (caps live
in the exec client, not the strategy; sizing/order-construction is explicitly
out of scope and owned elsewhere).

## Per-criterion points

- Fidelity to the audit gap and completeness: 19/20 — matches author baseline;
  follows the brief's "close on evidence if coverage exists, else build"
  instruction precisely.
- Technical correctness and evidence grounding: 19/20 — both enforcement
  points and the injection seam re-verified independently at HEAD; the one
  under-specified point (synthetic vs. strategy-generated order) is a
  clarity gap, not an incorrect claim.
- Implementation specificity and feasibility: 12/15 — strong on injection
  route and composition source; the order-construction ambiguity above costs
  a point relative to the author's own 13.
- Acceptance criteria and validation quality: 18/20 — three `git diff`-empty
  requirements plus a layer-B file-set check make "weaken a safety test"
  mechanically detectable; boundary cases named.
- Autonomous operation, failure handling, recovery: 13/15 — directly targets
  the unattended-spend bound; the neither-control-set assertion catches an
  accidental default.
- Portfolio objective alignment, scope, dependencies: 10/10 — no invented
  cap magnitude, R-12/MP-B correctly excluded to their owners, test-only so
  rollback risk is nil.

**Total: 91/100**

## Required changes for full marks

- Add one explicit sentence to §6 or §9 stating the driven order is a
  hand-built/synthetic Order (via Nautilus test helpers), not one produced by
  the v4 strategy's own decision path, and that this is deliberate because
  the caps enforce at the exec-client boundary, independent of sizing.

## Blockers

None named by the plan and none found independently: no cap value is read or
assigned, R-12 and sizing (MP-B) are correctly excluded to their own owners.
