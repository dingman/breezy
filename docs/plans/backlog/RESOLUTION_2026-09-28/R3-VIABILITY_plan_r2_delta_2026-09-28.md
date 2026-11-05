# R3-VIABILITY — plan r2 delta (binding amendments to r1)

**Reviews:**
- architect: REQUEST_CHANGES, confidence 82.
- prediction-market-reviewer: READY-WITH-AMENDMENTS, confidence 76. It re-derived Wilson(2,5), f_req = 0.625, and the k≤16 / k≥17 boundary at n=35.

**The work is split into two builds:**
- **R3V-a:** batch runner plus wrapper.
- **R3V-b:** `r3_viability.py` plus the log firewall.

## R3V-a — batch runner (`replay_daily_runner.py`, `deploy/systemd/replay-daily-run.sh`)

1. **Driver timeout (L-53).**
   - Pass `timeout = remaining_budget - reserve` to the per-target subprocess. Today `_default_run_subprocess` at `:966-969` has none.
   - On `TimeoutExpired`, append a terminal `FAILED` row with `exception_type=DRIVER_TIMEOUT`, then stop the batch with a non-zero exit.
2. **Budget.**
   - If the budget is ≤ the reserve, including a negative budget, start zero targets, print one line and exit 0. Argparse must accept a negative value.
   - Derive the wrapper's budget from the measured wall time of `promotion_proposal`, which runs after the runner. Do not hard-code 1500.
3. **Protected window.** Never start a new target inside the existing no-start window `[16:35Z, 01:15Z)`. Reuse the existing window constants. A late run after a reboot (`Persistent=true`) must not grow into 20 minutes of work.
4. **Per-target `peak_rss_bytes`.**
   - Today's `RUSAGE_CHILDREN` delta (`:1306`, `:1319-1320`) records 0 for any target after the first that is smaller than an earlier one. Measure each child instead, e.g. `Popen` plus `os.wait4`.
   - Warn when a target exceeds a named constant `REPLAY_TARGET_RSS_WARN_BYTES` of 2 GiB.
5. **Per-batch state.**
   - `reset_skip_state`, the manifest resolve, `compute_drift`, `write_replay_drift` and `emit_new_drift_alerts` run ONCE per batch.
   - `FEE_REGIME_EXCLUDED` prints once per batch.
   - With `max_targets=1`, print no batch summary.
6. **Work dirs.** Remove each target's `mkdtemp` work dir after the target finishes.
7. **Byte-identity test.**
   - Use a golden stdout and row captured from pre-change code (`git show <base>:scripts/analysis/replay_daily_runner.py`), never `git stash`.
   - Use pre-freeze fixtures only. The post-freeze log withholding (R3V-b) is a declared, deliberate change.
8. **Nightly wrapper:** `--max-targets 6` (4 accrual plus slack).
9. **Backfill.** The coordinator runs the service once, by hand, on 2026-09-29 at about 10:30Z. That is after the 09:45Z ingest and before the 15:50Z timer, outside AUD-07 (02:10–08:40Z) and serialized through `breezy-studies.lock`.
   - Budget ≤ 3 h. `--max-targets 40`.
   - It uses the same unit under `systemd-run`, with `-p LimitNOFILE=524288`.
10. **Batch summary line.** It goes to stdout, which the wrapper sends to `$LOG`, with per-target `wall_s`. Assert it on stdout (L-52).
11. **Citation fix.** Cite per-target subprocess isolation to the unit comment (`breezy-replay-daily.service:32-35`), not to L-31.

**Added tests:**
- A driver timeout produces a FAILED row and a non-zero exit.
- A budget ≤ the reserve starts zero targets and exits 0.
- No target starts inside the protected window.
- Per-target RSS is correct when the second target is smaller.
- Drift alerts are not re-emitted per iteration.
- Work dirs are cleaned up.
- The wrapper's budget arithmetic is correct when `SECONDS` is past the budget.

## R3V-b — `scripts/analysis/r3_viability.py` and the log firewall

1. **n** counts COMPLETED, non-fee-void, whole-day, pre-freeze rows only. There is a minimum `n ≥ 20`; below it the verdict is `INSUFFICIENT_N`.
2. **Freeze date.** Source it from the hypothesis register's freeze record near `hypothesis_register.py:87`, not a new literal. State that climate_day 2026-09-25 counts as pre-freeze (the firewall binds `> 2026-09-25`).
3. **Wilson label.** Use z = 1.96 and label it "two-sided 95% / one-sided 97.5% upper bound".
4. **f_req.**
   - f_req = 300 / (r_max · D), with r_max = 4 and D = 120.
   - Cite 300 as 50% of 600 (`EDGE-4_DISPOSITION_2026-09-27.md:22`).
   - Reconcile r_max = 4 with R3-PROJ's 5/day in one line: the census counts NYC, but NYC is never CONFIRM-eligible (`SUPPORTED_STATIONS`, `current_rung_hold/config.py:76`; `replay_daily_runner.py:403`).
5. **Log firewall.** For `climate_day > 2026-09-25`, the COMPLETED line withholds `trials=` and `fills=`. A spy proves `fills` is never read on a post-freeze row.
6. **Tests:**
   - At n = 35, k = 16 gives NOT_VIABLE (upper bound 0.618) and k = 17 does not (upper bound 0.644).
   - Wilson(2,5) = (0.1176, 0.7693).
   - `required_f()` = 0.625.
   - n < 20 gives INSUFFICIENT_N.

## Blockers if R3 survives (documented, not built)
1. MECHANISM_ONLY validity. The fix is AUD-11 plus AUD-12 landing (`replay_results.py:51-58`; `AUD11_AND_AUD12_LANDED=False` at `replay_daily_runner.py:154`). These are programmes, not patches.
2. `UNDERPOWERED_NOT_REGISTERED` is not in `_ACTIVE_STATUSES` (`hypothesis_triage.py:102-104`).
3. There is no post-freeze filter in `_completed_on_whole_days` (`:541-553`).
4. **To verify:** whether the replay store directories carry the `mechanism_test_only` marker that `mechanism_test_guard.py:16-45` refuses.

## R3-E
The viability ruling is pre-freeze and replay-derived, so it cites no census CONFIRM count. R3-E binds only a later CONFIRM count. The ruling states this.
