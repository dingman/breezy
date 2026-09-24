# AUD-19 — round 1 — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: b57f9531297b8400a598b73323b668c28d662c965219bd42bf86f1ad487225d9
Reviewer: silent-failure-hunter (blind, independent)

## Claims verified against source (codegraph_explore, /home/jon/breezy)
- `PAPER_TRIAL_ID_PREFIX:92`, `filled_trials_from_engine:300-347` (trial_id built at :347) — CONFIRMED as cited.
- `assert_live_only`/`assert_paper_only` (`live_family_tally.py:148-180`) — plain `startswith`, no substring — CONFIRMED.
- `filter_rows_to_manifest_prefix` (`family_tally_v2.py:532-564`) keys on `manifest.trial_id_prefix` only (no `paper_replay/` literal) — CONFIRMED a family-scoped paper id (`paper_replay/<family>/...`) never matches a live `trial_id_prefix`; A1b's claim holds.
- `count_filled_takes` (`fill_time_count.py:101-159`) — plain `startswith(family_prefix)` — CONFIRMED symmetric non-match.
- Ruling `:140-203` — Q1 items 1-8 as quoted; item 7 excludes the fix from AUD-09 and assigns no owner; item 8 permits AUD-09b to run before the fix with a caveat — CONFIRMED.

## Defects
1. **MATERIAL — stale sidecar on crash/rerun.** `family_params.json` (C6) is written only after a successful run, into `--output-dir`, with no pre-run clear, no run-id, no atomicity. A crash after a prior successful run into the same `--output-dir`, followed by a re-run that itself fails before C6 executes, leaves the PRIOR run's sidecar in place; nothing distinguishes it as stale. AUD-09's scheduler (§4, the stated consumer) can silently attribute a failed/differently-parameterised run's rows to the old sidecar's `family_id`/`params_match`. No acceptance criterion (§8) or RED test covers this. **Required change:** delete/rename any pre-existing `family_params.json` before the run starts (fail loud if one is unexpectedly present), or stamp the sidecar with a run id AUD-09 must match.
2. **MATERIAL — `UNSCOPED_FAMILY_ID` ids untested against selectors.** D1 introduces a genuinely new id shape, `paper_replay/unscoped/...`, live in the window between 19a-merge and 19b-merge (permitted by ruling item 8). Step 2's live-selector test covers only two real `family_id`s + an old-shape id; step 4's D3 test covers only the old shape. No RED test asserts the `unscoped` shape is refused by live selectors or by any family-scoped paper read. **Required change:** add a test symmetric to D3's, asserting `paper_replay/unscoped/...` rows are accepted by unscoped `assert_paper_only`, refused by `assert_live_only`, and refused by any family-scoped read.
3. **MATERIAL — `whole_tape_paper_replay.py` call site untested.** It calls `run_one_precision_arm`→`filled_trials_from_engine`, both gaining required kwargs (`family_id`, `trial_id_prefix`). It appears only in prose (C5) and the diff allowlist (A8) — no §7/§8 RED test exercises its updated call path, so a signature-mismatch regression there is not caught by the plan's own gates. **Required change:** add a RED/GREEN test for `whole_tape_paper_replay.py`'s call site with the new required kwargs.

## Minor
- C2's `strategy_name` resolution and the existing `:1118` `if args.strategy == "continuous_rung_hold"` branch are not reconciled in the text — unclear whether :1118 must be edited to read the resolved value; left to the implementer (step 12's RED test covers the *outcome*, not this mechanism, so it is minor not material).

## Per-criterion (cap)
Fidelity 17/20 · Technical correctness 18/20 · Implementation specificity 12/15 · Acceptance criteria 15/20 · Autonomous operation/failure handling 11/15 · Portfolio alignment 10/10.
**Total: 83/100.**

## Blockers
None operator/evidence-side; all three MATERIAL defects are plan-authoring gaps, fixable without a ruling.
