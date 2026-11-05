VERDICT: READY-WITH-CHANGES
SCORE: 81/100

**r1 findings:** A3, A6, A7, A8, A9 and A10 are resolved. A1, A2, A4 and A5 are only partly resolved; see H1, M1–M3 and L2 below.

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| H1 | HIGH | R1 can't be built as written. `accounting_rows(rows)` in `label_store` would need `is_final_row` and `LEGACY_SCORER_ID`, but both live in `breezy.analysis`, and persistence must never import analysis. `is_final_row` also needs `now_ns` and `deadline_ns`, which the signature doesn't take. | `pyproject.toml:152-160`; `completeness.py:82-93`; `legacy_crh_scorer.py:38` | Use a static predicate. For reasons {UNATTRIBUTED, None}, final means admissible, or UNATTRIBUTED, or `settled_outcome is not None`. Take `legacy_scorer_ids` as a parameter, as `coverage_partition:108` does. Add a test that the predicate equals `is_final_row` on the selected set. |
| H2 | HIGH | R2 understates re-pin churn. `closure_manifest.py` and `table.py` are both in the live `aut6.health` closure. WP-A's new manifest entry and WP-C's new bind therefore both change aut6.health's sha. WP-B's `label_store` edit changes aut2.label's sha. WP-A and WP-B run in parallel and both edit `label_store.py` and the report script. | `closure_manifest.py:18,46`; `test_autonomy_pins.py:597-599` | Each WP re-pins every affected component in its own commit, with AUT-6 co-signing the aut6.health re-pins. Run WP-A before WP-B, or make whichever merges second do the re-pin. Rollback reverts carry the matching re-pins. |
| H3 | HIGH | The binding band-semantics correction is not applied. The plan still uses the old figures (−4.63, 2 wins, FQ −4.17), P19, the S0-5(ii) STOP, Risks bullet 1, and the DISAGREE identity. `test_recipe_fixture_reproduces` is built from the audit's half-open recipe. | CORRECTION `:6-13` | Targets become 4 wins / −2.63 / FQ −2.17 / crh −0.46. All 9 legacy fills are `cli_final_check=AGREE` and `n_settlement_disagree=0`. Build the fixture through `bucket_facts_from_instrument_id`, including the MIA 09-13 and 09-15 upper-edge cases. |
| M1 | MED | E-TE1-b cites only r15:1471, which is just a boundary row. The NO_INPUT exit-0 rule WP-C changes is specified at r15:929, :1189 and :1235 (AUT-6 activation acceptance). | `AUT-6…r15.md:929,1189,1235,1471` | The erratum must amend all four lines. |
| M2 | MED | Booking is unspecified when the labels gate is closed. One pending fill makes `labels_consumable` false. If R7 then books nothing, all 25 FQ fills become overdue and R5 pages for every one. | `label_store.py:209`; `portfolio_roi_report.py:4088` | GATED_UNSETTLED_CAPITAL: book the final rows and mark only the pending fill. GATED_IDENTITY: book nothing. Test both. |
| M3 | MED | WP-B builds a second fill-level P&L table that overlaps existing code. `legacy_join` attributes legacy fills by latch key, while the report attributes them by family manifest, so the same fill has two attributions. `fill_pnl` also repeats the existing per-source totals. | `portfolio_roi_report.py:591-615,2795,3812-3830` | `build_fill_pnl` consumes `bucket_ledger_fills`. Assert that the LEGACY+RESIDUAL `fill_pnl` sum equals the existing totals. Add a trial-id agreement check between the two attributions (S0-5 plus a runtime refusal). |
| M4 | MED | The AST allow-list is ambiguous. The script's `_LabelView.accounting_rows()` has to reach the selector somehow. An attribute access (`label_store.accounting_rows`) bypasses a from-import check. | plan R1 and WP-B | Add an import-linter forbidden contract: no `breezy.*` module imports `labeling.accounting`. The AST guard must also cover attribute access. |
| L1 | LOW | `oldest_marker_ns` could quietly reset the R4 anchor. | `label_store.py:544-550` | Reuse `_marker_ns` so a bad file name raises MarkerCorrupt. `derived/label_outcomes` is absent today, which is correct; check it again before WP-E. |
| L2 | LOW | WP-E has no abort path. If steps 3–6 fail after the merge, the 17:40Z report pages for all 34 fills. Also, `verify` will flag the missing `breezy-autonomy-failed@` (P9). | `portfolio-roi-run.sh:102-115` | Revert WP-C before 16:30Z on abort. State in advance that the `verify` warning is expected. |
| L3 | LOW | The D3 docstring is stale after E-TE1-a. | `label_store.py:409` | Update the docstring and keep `test_only_admissible_rows…` unchanged. |
| L4 | LOW | `scored_trial_dedupe` is a clean move, but it belongs beside `read_scored_trials_pooled`. | `scored_trial_store.py:172` | Optionally place it in `persistence`. |
| L5 | LOW | The R8 pin test has no concrete mechanism. | — | Assert that no quote-tape module is in the aut2.label closure manifest. |

**Other lens checks**
- **R4:** sound. Lag is checked only for non-retired families of the matching kind, so `n=25` holds (`label_core.py:253-284`; `pins.py:115-120`).
- **WP-E window:** inside the bands, and the NeedDaemonReload preflight protects the symlinked units.
- **Rollback:** the order is safe once H2's re-pins are added.
- **Needs 3 and 8:** the reasoning holds; ING-2 is the quote-tape ingest (PROGRESS:73, ING-3 r1).

**Premises checked**
- P3 CONFIRMED (`:857-859`, `:892-894`)
- P10 CONFIRMED for legacy rows (`legacy_crh_scorer.py:125-138`)
- P11 CONFIRMED (`:4068-4074`, `:4216`)
- P13 CONFIRMED (`table.py:305-324`)
- P14 CONFIRMED (`label_core.py:124`; `verdicts.py:179-184`)
- P17 CONFIRMED, but the closure also includes `closure_manifest.py` itself (H2)
- P19 WRONG: void per the correction; the bot's scorer is right
- P20 CONFIRMED (`:523-541`; `label_run.py:639`)
- P21 CONFIRMED (`:2198`, `:2208`)
- R8's ING-2 premise CONFIRMED
- P15, P18 and P22 not re-checked