VERDICT: READY-WITH-CHANGES
SCORE: 78/100

F1–F8 are resolved in substance. The r2 text does not carry the band-semantics correction. Two test-widening lists are incomplete, and two RED tests would not fail on an assertion as written.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| G1 | HIGH | The widening list misses a test that the new closure entry breaks. `test_manifest_holds_only_the_reviewed_components...` asserts `set(CLOSURE_MODULES) == {"breezy.runtime.autonomy_health_cli"}`. Adding a `label_run` closure fails it. S0-9 greps for `{"aut6.health"}` and would not find it. | `tests/unit/test_autonomy_closure.py:90` | Add it to the WP-A reviewed widenings: assert the set equals both entries and keep the `ClosureUnavailable` control. Extend the S0-9 grep to `CLOSURE_MODULES`. |
| G2 | HIGH | The r2 plan does not reflect the correction, which makes P19 void. P19 and the "coincidental cancellation" Risk entry are still in the plan. S0-5 still has the "(ii) is a STOP" clause. R3 still says "−4.63 reproduces". Live proof 2 still targets −4.63 / 2 wins / FQ −4.17, and an identity with nonzero DISAGREE deltas. | Plan lines 64, 87, 116-121, 291-293, 274 vs CORRECTION | Targets become 4 wins / −2.63 / FQ −2.17 / crh −0.46. S0-5 becomes "legacy store agrees with the corrections-aware CLI final for all 9", with MIA 09-13 and 09-15 upper-edge positive controls. `booked_total − cli_final_net_total` should be 0. `test_recipe_fixture_reproduces` needs an upper-edge-inclusive row, going through `bucket_facts_from_instrument_id`. |
| G3 | MED | P21's "nine `== 4`" list is wrong. The actual `== 4` hits are 283, 423, 2234, 2295, 4424, 5165, 5187, 5909, **5921, 5922**. Line 5910 is the `frozenset({1,2,3,4})` assertion. The test name `test_schema_version_is_four_and_every_prior...` also goes stale. | `tests/unit/test_portfolio_roi_report.py:5909-5922` | Replace the list with these 11 lines and rename the test. Keep S0-9 as an execution check. |
| G4 | MED | `test_moved_dedupe_reexported_by_script` passes today, because `_prr.dedupe_scored_trials` already exists. It is not RED. `test_recipe_fixture_reproduces`, `test_c2_total_stays_admissible_only` and `test_journal_line_dimensionless` also look green before any change. | `portfolio_roi_report.py:1316` | Make the first assert `fn.__module__ == "breezy.analysis.scored_trial_dedupe"`, with the stub module in place. Label the others as regression pins rather than RED. |
| G5 | MED | The wiring RED tests need `factory` to return something assertable. `LabelRunDeps` has required fields with no defaults, such as `exec_db`, `deliver` and `producer_code_sha`. A neutral `None` body gives AttributeError or TypeError, not an assertion failure. | `label_core.py:113-131` | The stub `factory` should return a `LabelRunDeps` with sentinel fields: `deliver=lambda *a: None`, `producer_code_sha="0"*64`, `plan` returning `()`. |
| G6 | MED | `label_run.__main__` will import `unit_wiring`, which needs `StudiesFlock` and the plugins from `label_run`. That is a circular import risk, and `unit_wiring` would sit inside the pinned closure. | `label_run.py:39-89`; `closure.py:98-121` | Specify a lazy import inside `main`, or put the default factory in a third module. Add a test that imports each module standalone. |
| G7 | LOW | Focused-gate paths are ambiguous. `test_aut2_attribution`, `_label_store`, `_label_run` and `_units_deploy` are in `tests/unit/`, not `tests/contract/`. Only `test_autonomy_units_programme.py` is in `tests/contract/`. | `find tests` | Write the full paths. |
| G8 | LOW | Re-pin churn is wider than stated. The `label_run` closure shares `breezy.runtime.alert_*` and `breezy.registry.sites` with `aut6.health`. | `closure_manifest.py`; `label_run.py:39-89` | Note it in the Risks. `test_committed_manifest_is_exactly_the_regen_output` (:745) and `test_closure_manifest_equals_grimp_closure` (:688) will fail until the manifest is regenerated. |

Direct answers to your questions:
- **Stub-first REDs:** mostly fail on assertions, except the G4 and G5 cases.
- **Focused-gate files:** all exist (G7 path caveat).
- **Dedupe move and import-linter:** safe. The moved code needs only `breezy.settlement` and `breezy.persistence`, and `analysis` may import both. `scripts/` is outside `root_packages`. Test monkeypatches of `_prr._default_scored_trials_dir` still work, because the script calls its own re-exported global at :4508 and :4515.
- **`scripts/ci/regen_closure_manifest.py`:** real. It accepts new entries as positional arguments and has a `--check` mode.

Premises:
- P17: CONFIRMED.
  - `pins.py:19-21`, `closure_manifest.py`, `autonomy_health_cli.py:90-96` and `test_autonomy_pins.py:101/:597` all match.
  - It adds `test_autonomy_closure.py:90` (G1).
- P18: not code-checkable by me.
- P19: VOID, per the correction.
- P20: CONFIRMED. `label_store.py:523-551` writes `marker_<now_ns>.json`, and `_marker_ns` parses the name.
- P21: PARTLY WRONG. The known-set at :2208 is confirmed; the `== 4` list is off (G3).
- P22: CONFIRMED. `settlement_clock.py:36` and `sites.py:413` match.
- `labels_consumable` stale check: CONFIRMED at `label_store.py:205`.
- Move list: CONFIRMED. `_default_scored_trials_dir` is at :3606.
- `_LABEL_GATED_STATUSES`: CONFIRMED at :2216-2218, which is the cited :2217.