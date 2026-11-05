VERDICT: NOT-READY  
SCORE: 58/100  
Strongest fail reason: label-lag is still an unresolved ruling, but live proof requires an exit-0 label run with a marker.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| F1 | BLOCKER | Plan can still fail live proof on first label run: backlog labels older than 24h can raise `aut2.label_lag`, while the plan defers the ruling to S0-7. | `verdicts.py:195-197`; `label_core.py:281-297`; plan `TE-1_plan_r1.md:44-47`, `:166-170` | Make S0-7 a pre-implementation ruling with tests for the chosen backlog semantics. |
| F2 | BLOCKER | P12 overclaims cross-check evidence. Binding audit says venue-side settlement was NOT cross-checked. | `docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md:6-8`; plan `TE-1_plan_r1.md:29` | Remove the AFOS/no-disagreement premise or supply the missing verified artefact before relying on it. |
| F3 | HIGH | NO_INPUT change is a contract break, not just wrapper logic. Current tests pin skip-marker NO_INPUT exit 0. | `test_portfolio_roi_run_no_input.py:64-72`; `test_autonomy_units_programme.py:260-268`; wrapper `portfolio-roi-run.sh:102-109` | Enumerate and update every contract test with positive controls; keep absent-marker exit 1. |

Premises checked:
- P1 CONFIRMED: `score-live-trials-run.sh:185-189`, `:202-217`, `:355-369`.
- P2 CONFIRMED: `portfolio-roi-run.sh:102-115`; tests `test_portfolio_roi_run_no_input.py:64-82`.
- P3 CONFIRMED: `label_run.py:5-7`, `:857-859`.
- P4 CONFIRMED: `label_core.py:113-131`, `:300-424`.
- P5 CONFIRMED conditionally: epoch rule `epoch.py:108-110`; no capture files observed.
- P6 CONFIRMED: `attribution.py:209-258`, `:251`.
- P7 CONFIRMED: `memory_gate.py:128-129`; `constants.py:106`; `FQ-LOSS-RESPONSE_plan_r3.md:173`.
- P8 CONFIRMED: `alert_proof.py:216`; `PROGRESS.md:76`.
- P9 CONFIRMED: `breezy-autonomy-alert-redeliver.service:10-13`; `breezy-autonomy-canary.service:12-15`; `breezy-autonomy-health.service:18-21`.
- P10 CONFIRMED: `fq_scorer.py:352`, `:417-427`, `:451-452`; `completeness.py:52-61`.
- P11 CONFIRMED: `portfolio_roi_report.py:4068-4074`, `:4109-4118`, `:4216-4224`, `:4242`, `:4347`.
- P12 WRONG: `docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md:7`.
- P13 CONFIRMED: `table.py:295-324`; `test_aut2_units_deploy.py:175-185`.
- P14 CONFIRMED as risk path: `verdicts.py:195-197`; `label_core.py:281-297`; `constants.py:55`.
- P15 CONFIRMED: `test_aut2_attribution.py:305-322`.
- P16 CONFIRMED: `breezy-label-outcomes.service:7-12`; `breezy-label-outcomes.timer:8-14`.

Two runtime artefacts the plan cites, `derived/score_live_trials.log` and a related log, were not present in this checkout. Codex made no file modifications.