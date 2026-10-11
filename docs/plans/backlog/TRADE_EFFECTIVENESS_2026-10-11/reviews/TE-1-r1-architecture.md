VERDICT: READY-WITH-CHANGES
SCORE: 78/100

Option 1 re-scoped is the right shape. It reuses the existing label pipeline, the FQ scorer, the coverage and marker checks and the overlap guard, and builds nothing parallel. Running WP6-promote ahead of AUTONOMY row 9 is sound for pre-epoch fills only. Four HIGH gaps must close before build.

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| A1 | HIGH | WP-B's P&L view breaks an existing rule. `admissible_rows` is documented and tested as "the one selection rule for any P&L or ROI aggregate" (D3). The plan treats the split as a peer-loop matter and never names D3. | `src/breezy/persistence/autonomy/label_store.py:408-414`; `tests/unit/test_aut2_label_store.py:386-401` | Add an ARCH/AUT-2 erratum that narrows D3 to statistics. Put an `accounting_rows` selector next to `admissible_rows` in `label_store`, and add an AST guard so AUT-3/4/5 modules can import only `admissible_rows`. That guard is what actually prevents leaks into AUT-4/AUT-5 verdicts. |
| A2 | HIGH | The new NO_INPUT rule ("gated → alert, exit 1") will page every trading day. Fresh fills always leave labels pending, which gives `GATED_UNSETTLED_CAPITAL`. AUT-6 also owns portfolio-roi's exit behaviour, so this change is theirs to agree. | `portfolio_roi_report.py:4088-4089`; `AUT-6-drift-health_plan_r15.md:1471` | Alert only on fills older than the settlement deadline plus `LABEL_LAG_MAX_H` that still have no P&L. Get AUT-6 to co-sign the erratum. |
| A3 | HIGH | Rollback step 3 is unsafe. Once FQ labels exist, the pre-WP-B code reads them, the unlabelled-FQ count drops to 0, and the report publishes the wrong ROI (P11) with status OK. "Nothing reads them" is wrong. | `portfolio_roi_report.py:4202-4224` | Never revert WP-B on its own. Rollback is: disable the timer, then revert WP-C. If WP-B ever has to go, move the labels root aside first (move, not delete). |
| A4 | HIGH | Units are activated by `ln -s` into `~/.config/systemd/user`. WP-E has no link step for the label pair, so `enable` fails. Rollback leaves dangling links behind. Merging WP-C on the primary tree also makes the edited score-live-trials pair live at anyone's next `daemon-reload`. | `deploy/systemd/README.md:6,45,343` | WP-E: run the gate on a branch, then merge, link, preflight and reload in one window (outside 13:55–14:30Z and the launch window). Rollback: unlink the label pair. |
| A5 | MED | Accounting P&L summed over label rows can double-count (DUPLICATE_FILL rows still carry `realized_pnl`). The overlap guard only checks admissible rows. | `fq_scorer.py:314`; `portfolio_roi_report.py:4206` | Build `fill_pnl` per ledger fill with a fixed source order (legacy, then residual, then C2). Build `family_pnl` from `fill_pnl`. Widen the overlap check to accounting rows. |
| A6 | MED | The `score-live-trials-run.sh` change is not needed. All 9 CRH fills settled before 10-01, and only the sending family trades. Writing the skip marker after scorers actually ran also changes what the marker reason means. | `score-live-trials-run.sh:202-217` | Drop it. Keep only the portfolio-roi wrapper change. If kept, use a new closed reason token. |
| A7 | MED | Nothing enforces "scorer before label run". `score-live-trials` holds no studies lock, so the 13:55 move's lock arithmetic in the staged README rests on a false premise. A worst-case run ends at 14:17:30, overlapping the 14:15 label start. | deployed `.service:59-61`; `promote/README.md:11-14` | The label run should check for the same-day scorer marker (ok or skipped), or this should be accepted explicitly as stale-safe. |
| A8 | MED | S0-6 (measure the label peak) cannot run in Stage 0. `--measure-peak` refuses `not_wired` until WP-A exists. | `label_run.py:892-894` | Move it into WP-D only. |
| A9 | MED | Once AUT-1b writes the capture epoch, the live label unit changes behaviour silently. Row 9 could also promote the units a second time. | plan "Forward compatibility" | Add the label unit's switch to the POST_EPOCH path to AUT-1b's acceptance. Mark row 9's WP6-promote part DONE-by-TE-1. |
| A10 | LOW | `portfolio_roi_report.py` is already over 4,400 lines. | — | Put the selection logic in `src/`. |

On row 9: running promotion ahead is justified because every fill is pre-epoch (P5, P6). AUT-1b (Need 8) only matters for post-epoch admissible rows. The plan never says why Need 3 (ING-2-AMEND2) doesn't apply; that should be stated in the ruling.

Premises checked:
- P1 CONFIRMED (`:185-189`, `:202-217`)
- P2 CONFIRMED in code (`:102-115`); log lines not re-read
- P3 CONFIRMED (`:857-859`)
- P4 CONFIRMED (`:113-131`, `:300-424`)
- P5 CONFIRMED: both globs are empty
- P6 CONFIRMED (`:209-258`)
- P7 CONFIRMED (`memory_gate.py:128`; `constants.py:106` = 4)
- P8 CONFIRMED (`alert_proof.py:216`)
- P9 CONFIRMED: there are three dangling `OnFailure=` units and no notifier file
- P10 CONFIRMED. `admissible=False` is hard-coded for every FQ row (`fq_scorer.py:352`), and UNATTRIBUTED counts as final (`completeness.py:60`).
- P11 CONFIRMED (`:4068-4074`, `:4216`, `:4347`)
- P12 CONFIRMED in code (`:41-69`); `coverage.json` not re-read
- P13 CONFIRMED (`table.py:305-324`)
- P14 PARTLY WRONG. `:790` is the proof-window path only. In the daily path the lag start is an injected dependency (`label_core.py:124,282`). The intended rule is `verdicts.lag_start_ns` (settlement time capped at the deadline, `verdicts.py:179-184`). The backlog FAIL conclusion still holds. Option (a) belongs in the factory, not in `verdicts`.
- P15 CONFIRMED (`test_aut2_attribution.py:305-324`)
- P16 CONFIRMED (fixture `:7-12`)