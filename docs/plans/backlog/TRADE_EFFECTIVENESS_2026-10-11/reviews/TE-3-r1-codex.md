VERDICT: NOT-READY  
SCORE: 76/100

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| F1 | BLOCKER | The offer-tape census is mislabelled. The 9 qualifying distinct rungs are 8 finite `gte…lt…` interiors plus 1 open-lower `lt65` tail, not 9 interior rungs. §6 still uses λ=9/4. | The plan notes the SFO `lt65` tail at `TE-3_plan_r1.md:47-52`. Observed output: `distinct 9 by_shape {'interior': 8, 'open': 1}`, `reached_taken_by_shape {'interior': 2, 'open': 0}`. | Restate the census and the λ arithmetic as either 8 interior over 4 days, or "8 interior + 1 open tail". |
| F2 | LOW | n=1485 is off by one if the threshold is `MDE <= 0.04`. The raw n is 1485.161991, so the integer n is 1486. The verdict is unaffected against the 420 ceiling. | Constants at `hypothesis_ledger.py:177-196`. Formula at `sample_size.py:42-48`. Observed output: `n_raw=1485.161991 ceil=1486`, `recompute 1485 0.0400021816`, `1486 0.0399887197`. | Say "about 1485" or use 1486. |

Strongest argument that INFEASIBLE is wrong (hypothesis only): the "structural ceiling" depends on the assumed first_forward_day `2026-10-26` (`TE-3_plan_r1.md:148`). That date gives `5 × 84 = 420` (`:157`), which is below `n_min=445` (`:172`). If the prereg were frozen right after the plan date, the window would run `2026-10-12..2027-01-17`, which is 98 days. The ceiling would then be `490`, so the binomial δ=0.04 path is not structurally impossible. It is still improbable on rate and impossible under the ledger.

Premise checklist:

- **P1 wins/fills:** CONFIRMED.
  - The audit reports both NO wins and 3 NO-side fills at +1.65 (`TRADE_EFFECTIVENESS_2026-10-11.md:12-20`).
  - The DB output confirms the three fill IDs, instruments, costs and fees.
  - The truth grep confirms MIA 09-15=93, MIA 09-21=88, MDW 09-22=64.
- **P2 NO-denominated pricing:** CONFIRMED (`decision.py:455-488`, `market_calibration_scan.py:242-245`, `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:32-36`).
- **P3 M1-v3 NO-favourite screen:** CONFIRMED (`PREREG.json:8-10,27,43`; `M1v3...plan.md:10,91,192-195`).
- **P4 bot NO rule/offer rows:** CONFIRMED (`config.py:233-247`; `continuous_no_side.py:213-296,383-388`).
- **P5 offer census:** WRONG as written (see F1). The "no files after 09-23" claim holds. The `offer_tape_*` listing shows only 09-16, 17, 19, 20, 21, 22 and 23.
- **P6 M1 coverage:** CONFIRMED (`market_calibration_scan_v2.json:553-560,572`).
- **P7 ledger constants and arithmetic:** CONFIRMED except for the off-by-one in F2.
- **P8 governance/backstop/firewall:** CONFIRMED (`RULING_RA-13...md:45-48,89-97`; `RULING_R3-VIABILITY...md:42-50`).
- **P9 adverse prior/anecdote:** CONFIRMED (`LESSONS.md:492-504`). Observed output: `P_ge_2_of_3_at_p_0.12=0.039744`.