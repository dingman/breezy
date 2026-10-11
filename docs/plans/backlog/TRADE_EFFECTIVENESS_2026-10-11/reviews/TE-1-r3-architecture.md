VERDICT: READY
SCORE: 90/100

All of H1–H3 are resolved, and no BLOCKER or HIGH finding remains. Of the r2 items, M1–M3, L1 and L3–L5 are resolved. M4 and L2 are resolved only in part (N2 and N4 below). Four MEDs (N1–N4) should go into the WP briefs.

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| N1 | MED | WP-A types the factory wrongly. It says `factory(args) -> LabelRunDeps` with a `LabelRunDeps` stub, but `UnitFactory` returns `UnitWiring`, and `main` reads `wiring.deps/.lock/.unit_max_bytes/.aut6/.measured_peak_bytes/.proof_window/.slot_ns`. Merge 7/G5 carried the same error. | `label_run.py:684-697,860-869` | `factory(args) -> UnitWiring`. The stub returns a `UnitWiring` whose `deps` holds the sentinels. Don't change the `UnitFactory` contract. |
| N2 | MED | The new forbidden contract (ten non-analysis packages → `accounting`) adds nothing. Those packages are already forbidden from importing all of `breezy.analysis`. The real D3 risk is verdict builders inside `analysis` (AUT-3/4/5), and only the AST guard covers that. | `pyproject.toml:152-160` | Either point the contract at analysis-internal sources, or drop it and name the AST guard as the only guard. The AST guard should match the fully qualified `breezy.analysis.labeling.accounting`, not the bare name `accounting` (`nautilus_trader.accounting` exists). |
| N3 | MED | R6/R7 leave the existing GATED_UNLABELLED_FQ state unmapped and never define how `roi_accounting_status` is derived. An after-run fill with a consumable marker would show `roi_accounting_status=OK` while that fill is unbooked. | `portfolio_roi_report.py:2217-2224,4217-4223` | `roi_accounting_status` is OK only if every fill is SETTLED_NWS_IMPLIED (or EXIT). Otherwise it is gated. Map GATED_UNLABELLED_FQ explicitly and add a test. |
| N4 | LOW | The WP-E abort path states the wrong fallback. On the closed skip reason the pre-WP-C wrapper prints NO_INPUT and exits 0, not 1. The abort path also leaves out `disable --now` and moving any markers it wrote. | `portfolio-roi-run.sh:103-109` | Correct the expectation. Abort = disable the timer, `mv` `derived/label_outcomes` to a dated sibling, revert WP-C with its re-pin, unlink, `daemon-reload`, gate. |
| N5 | LOW | The LEGACY runtime check compares a per-fill sum with a whole-store total: `total_realised_pnl_all_settled(scored_trials)` sums every scored trial, not only SCORED-bucket fills. | `portfolio_roi_report.py:4241` | S0-5 asserts the store total equals the SCORED-bucket Σ (−0.54) before WP-B. |
| N6 | LOW | R2's WP-B bullet credits the dedupe move to WP-B, but the move happens in WP-A. | plan R2 | Fix the attribution. Add a general rule: any regeneration of `closure_manifest` also re-pins `aut6.health` (P26). |
| N7 | LOW | A future pre-epoch fill labelled before the CLI final would be UNATTRIBUTED, final, with null P&L for good. That means a daily CRITICAL. | `fq_scorer.py:451-452`; `completeness.py:87-88` | Add it to Risks as known, outside the 34-fill goal. |

**Lens checks**
- **`accounting_rows`:** the static predicate equals `is_final_row` on the selected set. With reason None it reduces to admissible or settled; UNATTRIBUTED is final.
- **Re-pin choreography:** sound. `pins.py` is outside the closure; WP-A and WP-C both change the `aut6.health` sha; the order is strictly sequential.
- **Dedupe move:** allowed. `persistence` sits above `settlement`, and the moved code needs only `ScoredTrial`.
- **R7:** P28 holds.
- **E-TE1-b lines:** all five correct.
- **`build_fill_pnl`:** the three-bucket partition holds, and C2 rows carry `client_order_id`.

**Premises checked**
- P24 CONFIRMED (`completeness.py:52-62,82-93`)
- P25 CONFIRMED (`label_core.py:130`; `completeness.py:108`)
- P26 CONFIRMED (`closure_manifest.py:18,33,35-38,46`, no `label_store`)
- P27 CONFIRMED (`test_autonomy_closure.py:90`; `test_autonomy_pins.py:101,599,688,745`); the schema lines were not re-counted
- P28 CONFIRMED (`portfolio_roi_report.py:4077-4090`; `label_store.py:200-209`)
- P29 CONFIRMED (`:591-615,2576,2629`)
- P30 CONFIRMED (`label_store.py:165-166`)
- P31 CONFIRMED (`label_core.py:253-256,278-284`)
- P32 CONFIRMED (r15 `:929`, `:1189`, `:1235`, `:1471` boundary row, `:1539`)
- P33 CONFIRMED (`pins.py:19-21`)
- P34 CONFIRMED (`pyproject.toml:78-99`; `scored_trial_store.py:49,172`)
- P3 CONFIRMED (`label_run.py:857-858,892-893`)
- P2 CONFIRMED but incomplete: the closed reason exits 0 (N4)
- P23 and P35, and the fill-store totals, were not re-checked (read-only, no store access)