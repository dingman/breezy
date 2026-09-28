# RA-9f-A — plan r2 delta (binding amendments to r1 Plan A)

**Reviews:**
- prediction-market-reviewer: READY-WITH-AMENDMENTS, confidence 80. It verified every ruling constant against `RULING_RA-9…:56-58,108-126`.
- architect: REQUEST_CHANGES, confidence 80.

The coordinator merged both.

## Amendments

1. **`freeze_commit`.** Drop the `git rev-parse HEAD` at append time.
   - For `H-OFFWINDOW-T4-2026-09` only, require an explicit `--freeze-commit` that validates as 40-hex. The CLI refuses that flag today at `hypothesis_register.py:433-439`, so add a per-id branch.
   - The live append refuses on a dirty tree (`git status --porcelain` non-empty) as well.
   - RED: a missing, malformed or dirty-tree append is refused.
2. **Registered-at.** The `_UNDERPOWERED_REGISTRATIONS` entry carries the ruling date `2026-09-27`.
   - RED: `--registered-at 2026-09-26` is refused.
3. **Constants.** The constants test pins every ruling §4 field:

   | Field | Value |
   |---|---|
   | `min_station_days` | 300 |
   | `programme_alpha_override` | 0.025 |
   | MDE | 0.0964 |
   | bound | 0.04 |
   | fee θ | 0.0695 |
   | slippage | 0.01 |
   | qty | 1 |
   | `mde_reference_ask` | 0.30 |
   | `mde_variance_bound` | 0.25 |
   | `max_single_day_leg_share_cap` | 0.20 |
   | `k_variants` | 1 |
   | look plan | `SINGLE_LOOK` |
   | `power_is_primary_only` | True |
   | `disposition` | `"NORMAL"` |
   | statistic | `MEAN_E…`, per the ruling |

4. **`HORIZON_TOLLING_LANDED`** stays False (`hypothesis_ledger.py:164`). Keep the regression test.
5. **Live append.** This is a coordinator-run production write, separate from the merge.
   - Back up `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl` first.
   - Run the append outside the `breezy-hypothesis-triage` window (01:20Z). Per L-50, first confirm that triage does not rewrite the file.
   - Verify the result: exactly one new line, and the duplicate run leaves the bytes unchanged.
6. **Citation fixes:** `hypothesis_ledger.py:164` (not 157), and the PROGRESS row.
