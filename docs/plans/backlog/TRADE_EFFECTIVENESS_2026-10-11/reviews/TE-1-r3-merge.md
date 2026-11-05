# TE-1 r3 review merge — coordinator rulings (binding on r3.1)

Scores: domain 93 READY, architecture 90 READY, python 86 RWC (2 HIGH), codex 88 NOT-READY (1 BLOCKER). Every finding is text-sized. All are accepted. r3.1 is a targeted revision, followed by a python and codex confirmation pass.

1. **The S0-9 grep is too broad** (codex R3-F1). Use the regex `== 4(?![0-9])` via `/home/jon/breezy/.venv/bin/python` or `grep -P`. Also list `test_portfolio_roi_report.py:4708` (`== 4000`) as a known non-hit. Add `not_wired` to the S0-9 patterns (python H2).
2. **Shared closure re-pin** (python H1, arch N6). The `aut2.label` closure contains `autonomy_sandbox.table`, `binds`, `registry.sites` and `alert_*`.
   - The WP-C `table.py` bind re-pins **both** `aut6.health` and `aut2.label`.
   - General rule: any change to `table.py`, `sites.py`, `alert_*` or `closure_manifest` re-pins both producers.
   - Rollback carries both.
   - Fix P26.
   - Fix R2: the dedupe move belongs to WP-A, not WP-B.
3. **The `not_wired` test** (python H2). `tests/unit/test_aut2_label_run.py:580-591` gets a reviewed WP-A widening row, never a deletion (L-12).
   - Keep the fail-closed control by injecting a refusing factory or an unpinned producer, and assert the new refusal.
   - Update the `label_run.py:7` docstring.
4. **Factory type** (python M2, arch N1). The factory is `factory(args) -> UnitWiring`, unchanged from the `UnitFactory` contract.
   - The stub returns a `UnitWiring` whose `deps` holds the sentinels.
   - List sentinels for `lock`, `aut6`, `unit_max_bytes`, `measured_peak_bytes`, `proof_window` and `slot_ns`.
   - A single `_resolve_factory(unit_factory)` helper is called from both `main` (:857) and `_measure_main` (:892) (python L1).
5. **Drop the forbidden import-linter contract and its pkgutil test** (python M1, arch N2). It is vacuous, as tested in scratch.
   - The AST guard over `src/` and `scripts/` is the only guard. It matches the fully qualified `breezy.analysis.labeling.accounting` (not the bare name `accounting`) for Import, ImportFrom and Attribute nodes.
   - It covers analysis-internal modules too, which is the real AUT-3/4/5 risk.
   - Keep the planted-mutation RED.
6. **`roi_accounting_status`** (arch N3).
   - OK only if every fill is SETTLED_NWS_IMPLIED or EXIT. Otherwise it is gated.
   - Map GATED_UNLABELLED_FQ explicitly.
   - Add a test.
7. **WP-E abort path** (arch N4). The pre-WP-C wrapper exits 0 with NO_INPUT on the closed reason, not 1. Fix that statement.
   - Abort sequence: disable the timer, `mv` `derived/label_outcomes` to a dated sibling, revert WP-C with its re-pins, unlink, `daemon-reload`, gate.
8. **LEGACY runtime check** (arch N5). In S0-5, assert that `total_realised_pnl_all_settled(scored_trials)` equals the SCORED-bucket sum (−0.54) before WP-B. Otherwise, compare against the SCORED-bucket subset.
9. **Risks** (arch N7). Add as known and outside the 34-fill goal: a future pre-epoch fill labelled before the CLI final becomes UNATTRIBUTED, final, null P&L, and raises a daily CRITICAL.
10. **Event names** (domain R3-2). `PORTFOLIO_ROI_NO_INPUT` and `PORTFOLIO_ROI_LABEL_IDENTITY` are new names. E-TE1-b distinguishes the alert from the wrapper's journal token `PORTFOLIO ROI NO_INPUT`.
11. **S0-1 wording** (domain R3-1). The store already holds `^no` instrument ids and camelCase `orderSide`, so there is no normalisation step.
12. **Subprocess import test** (python L2). Pass `env` with `PYTHONPATH=<tree>/src` and `sys.executable`.
13. **Verified fact to cite** (codex S0-12 output): `pm_us_crh_fq_v1` is non-retired; v4, cont and v2 are retired. Therefore n=25.
