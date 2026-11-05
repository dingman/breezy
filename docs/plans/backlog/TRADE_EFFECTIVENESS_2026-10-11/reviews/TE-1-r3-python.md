VERDICT: READY-WITH-CHANGES
SCORE: 86/100

G1–G8 are resolved in the plan text. The 12 tests I listed in the focused gate are real paths, but five of the non-`test_autonomy_*` paths come from the plan's own list. They are `test_aut2_completeness.py`, `test_aut2_attribution.py`, `test_aut2_label_store.py`, `test_aut2_label_run.py` and `test_aut2_units_deploy.py`. Two HIGH findings remain, so the verdict is not READY. Both are one-line fixes in plan text, and the gate would catch either one.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| H1 | HIGH | WP-C re-pins only `aut6.health`, but the `aut2.label` closure already contains `breezy.runtime.autonomy_sandbox.table`. I computed both closures with `closure_from_grimp`: 219 modules for `label_run` and 62 for `autonomy_health_cli`. They share `table`, `binds`, `registry.sites`, `alert_proof` and others. The WP-C `table.py` bind therefore changes the `aut2.label` sha as well. Left unpinned, the unit prints `producer_unpinned` and exits 2 at activation. P26 and R2 have the same gap. | `table.py:305-324`; closure run, scratchpad | WP-C re-pin covers `aut6.health` and `aut2.label`. State that any `table.py`, `sites.py` or `alert_*` change re-pins both producers. Rollback carries both. |
| H2 | HIGH | The default-factory wiring breaks an existing test with no widening row. `test_default_mode_without_a_deps_wiring_fails_closed` calls `main(...)` with no factory and asserts `reason=not_wired`. S0-9 does not grep `not_wired`, and no widening list names the test. Do not delete it (L-12). | `tests/unit/test_aut2_label_run.py:580-591`; `label_run.py:7,857-858,892-893` | Add a WP-A widening row. Keep the fail-closed control by injecting a refusing factory or an unpinned producer, and assert the new refusal. Add `not_wired` to S0-9. Update the `label_run.py:7` docstring. |
| M1 | MED | The import-linter contract is vacuous. I tested it in a scratch config. A forbidden contract whose forbidden module sits inside the source package is silently KEPT (`source=["breezy"]` on a module imported by `label_core` still passed). The plan's ten non-analysis sources already cannot import `breezy.analysis`, because of the existing contract at `pyproject.toml:150-160`. The exhaustive-list test therefore protects nothing. | scratch `lint-imports` runs; `pyproject.toml:155-158` | Drop the contract and its pkgutil test, or label it as defence in depth. The AST guard (attribute access, `src/` and `scripts/`) is the real control, so keep its planted-mutation RED. |
| M2 | MED | The plan types the stub `factory` as returning `LabelRunDeps`. `UnitFactory` returns `UnitWiring` (`deps`, `lock`, `unit_max_bytes`, `aut6`, `measured_peak_bytes`, `proof_window`, `slot_ns`). Sentinels must be built inside a `UnitWiring`. | `label_run.py:690-697,860-868` | Change the signature to `factory(args) -> UnitWiring`. List the sentinel fields for `lock`, `aut6` and the rest. |
| L1 | LOW | The lazy import is needed in `main` (`:857`) and in `_measure_main` (`:892`). The plan says "inside main". WP-D needs the `--measure-peak` path wired. | `label_run.py:880-895` | Use one `_resolve_factory(unit_factory)` helper called from both. |
| L2 | LOW | The subprocess standalone-import test must set `PYTHONPATH=<tree>/src`, or it checks the primary tree. Note the grimp closure follows lazy imports, so `unit_factory_default` and `unit_wiring` are inside the `aut2.label` pin, which the plan already assumes. | memory: worktree-needs-pythonpath | Pass `env` and `sys.executable` explicitly. |

Checks you asked for:
- **Lazy import and cycle:** feasible. There is no top-level cycle once `StudiesFlock` is reached only from `unit_factory_default`. The factory sentinel stub works once M2 is fixed.
- **Schema widening list:** exact. I re-grepped the file. The `== 4` lines are 283, 423, 2234, 2295, 4424, 5165, 5187, 5909, 5921 and 5922. The frozenset is at `:5910` and the test name at `:5908`. The `:4708` hit (`4000`) is a false positive. The known-set is at `portfolio_roi_report.py:2208`.
- **Focused-gate paths:** all 12 exist, including `test_aut2_completeness.py` and `tests/contract/test_autonomy_units_programme.py`.

Premises P23–P35:
- P23: CONFIRMED. `slug_closed_interval` returns `(None, B-1)` for `lt{B}`, `(A, None)` for `gte{A}` and `(A, B)` otherwise. `contains` is closed at both finite ends.
- P24: CONFIRMED.
- P25: CONFIRMED. Both parameters exist.
- P26: PARTLY WRONG. It omits that `table` is shared with `aut2.label` (H1).
- P27: CONFIRMED. `:90` and `:5908-5922` match. `test_autonomy_pins.py:599,688,745` also match.
- P28: CONFIRMED.
- P29: CONFIRMED. Totals are at `:2576` and `:2629`.
- P30: CONFIRMED.
- P31: CONFIRMED.
- P32, P35: not checked. The AUT-6 r15 lines and the L-numbers were not opened.
- P33: CONFIRMED (`pins.py:19-21`).
- P34: CONFIRMED. `scored_trial_store.py:49` imports `breezy.settlement.trial_scorer`.

Relevant paths:
- /home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r3.md
- /home/jon/breezy/tests/unit/test_aut2_label_run.py
- /home/jon/breezy/src/breezy/analysis/labeling/label_run.py
- /home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py