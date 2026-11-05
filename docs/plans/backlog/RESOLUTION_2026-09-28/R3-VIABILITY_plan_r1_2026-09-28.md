# PLAN — R3-VIABILITY r1 (batched replay + pre-freeze backfill + kill rule)

Author: Claude code-architect (read-only), 2026-09-28. Saved by the coordinator. Grok and Codex were unavailable: Grok returned 402, and Codex had no credit.

## 1. Verified problem

- **At most one replay per day.**
  - The docstring of `replay_daily_runner.py:4` says "replays AT MOST one (station, climate_day)". `run_once` selects at `:1216` and returns at `:1437`.
  - The unit fires once a day at 15:50Z. The 7 existing rows came from hand-runs on 09-26. The 09-27 run timed out: 30 min wall, 12 min CPU, 3.4G, the L-49 signature.
  - The census is the fixed cost: about 8 min and a 10G peak. The replay is cheap: 51–138 s at ≤1.1G.
- **Head-of-line risk.** `BLOCKED` is not terminal (`replay_results.py:68`), and selection is oldest-first (`:472`). A persistently BLOCKED day would stall the queue.
- **The eligible backlog is about 30 days, not 86.**
  - Of the 86 pre-freeze whole-days, 17 are NYC, which is not in `SUPPORTED_STATIONS` (`:403`). Another 34 are θ=0.06 days, excluded by the fee-schedule rule (`:410-429`). That leaves 35 eligible, of which 5 are already replayed.
  - Post-freeze, at most **4 days accrue per day**, because NYC is never eligible.
- **f.** The LAX and MDW 09-01 rows are fee-void (`fee_schedule_mismatch`). The valid sample is **f = 2/5**, Wilson 95% [0.12, 0.77].
- **Three further R3 blockers (CONFIRM stays 0 until they are resolved):**
  1. Triage's `_passes_c_validity` requires `validity != "MECHANISM_ONLY"` (`hypothesis_triage.py:368-369`, `:674`). Every runner row is MECHANISM_ONLY (`replay_results.py:58`).
  2. H-ARCHIVE-RECAL-2026-09 has status `UNDERPOWERED_NOT_REGISTERED`, which is not in `_ACTIVE_STATUSES` (`:102`).
  3. `_completed_on_whole_days` (`:541-553`) has no post-freeze filter.

## 2. L-1
Nautilus `BacktestNode` multi-config buys nothing: engine start-up is not the cost. It would also drop the per-day subprocess isolation (L-31) and the provenance digest. Breezy has no multi-target flag. **A bounded loop over the existing single-target path is the smallest change.**

## 3. Design
1. **Batch mode.** Take one census, then loop the existing one-target body (`_run_one`) until one of these:
   - the queue is empty;
   - `--max-targets` is reached;
   - `--budget-s` minus a 240 s reserve is spent;
   - the first target with a non-zero exit, which stops the batch loudly so `OnFailure` fires.

   Re-read the results file each iteration. Keys tried in this batch are excluded, which fixes the BLOCKED head-of-line problem.
2. **The wrapper** passes `--max-targets 16 --budget-s $((1500 - SECONDS))`. `TimeoutStartSec=1800` is unchanged. The run ends by about 16:20Z, before the 16:35Z no-start window and the 16:50Z node spawn, under one hold of `breezy-studies.lock`.
3. **Backfill.** Oldest-first order drains the ~30 pre-freeze days in 2 nightly runs. No separate job and no AUD-07 or ingest contention.
4. **Log firewall.** For `climate_day > 2026-09-25`, the COMPLETED line prints `post-freeze: counts withheld`, with no `trials=` or `fills=`.
5. **`scripts/analysis/r3_viability.py` (new).**
   - Pre-freeze rows only, filtered by the row's date before `fills` is read.
   - Drops fee-void rows. Keeps COMPLETED rows on whole-days.
   - Outputs k, n, the Wilson interval, f_req and a verdict.

## 4. Decision rule
- **Formula:** f_req = 300 / (r_max · D).
  - r_max = 4 station-days per day, the structural cap; choosing it favours R3.
  - D = 120 post-freeze climate days with a replay row before the 01:20Z triage on 2027-01-25.
  - So f_req = **0.625**.
- **Verdict:** after the backfill, if the Wilson 95% upper bound of k/n (pre-freeze) is below f_req, **R3 is ruled not viable**.
  - At n=35 that happens when k ≤ 16.
  - Blockers 1–3 are fixed only if R3 survives.
- Pre-freeze f describes the SEARCH corpus, so it is an upper-bound screen.

## 5. Files
- `scripts/analysis/replay_daily_runner.py`:
  - `_run_one`, `run_batch`, the `exclude` argument on `select_target` / `_pre_fee_eligible_rows`;
  - `FREEZE_CLIMATE_DAY`, the log withholding;
  - `--max-targets` (default 1, today's behaviour), `--budget-s`.
- `deploy/systemd/replay-daily-run.sh`: the new flags.
- `scripts/analysis/r3_viability.py`: new.
- `deploy/systemd/README.md`: wording.

## 6. RED tests
1. `max_targets=3` with 5 eligible targets gives 3 driver calls and 3 rows.
2. An always-BLOCKED target is never re-selected within a batch.
3. The budget reserve is honoured, under a fake monotonic clock.
4. The first FAILED target stops the batch with a non-zero exit.
5. With no `--max-targets`, the output is byte-identical to today's.
6. A post-freeze COMPLETED line has no `trials=` or `fills=`.
7. The wrapper argv carries both flags.
8. `r3_viability` excludes post-freeze and fee-void rows, and a spy proves `fills` is never read on a post-freeze row.
9. Wilson(2,5) = (0.1176, 0.7693), and `required_f()` = 0.625.

## 7. Acceptance
- The full gate and `lint-imports` pass.
- The first unattended 15:50Z run appends ≥2 rows, CPU/wall >0.3, and ends before 16:35Z.
- Every eligible pre-freeze key has a terminal row by night 2.
- The `r3_viability` output is quoted in a ruling, with the `census_provenance:` line from a `--no-instance-spans-cache` run (R3-E).

## 8. Risks
- The census stays the 10G consumer. Keep the TEMPORARY drop-in until REPLAY-BIGINST Stage 0 passes.
- Post-freeze rows are written but never read outside triage (tests 6 and 8).
- Pre-freeze f is a proxy.

## 9. Rollout
- 09-28: build.
- 09-29 and 09-30, 15:50Z: batch runs.
- 10-01: viability ruling.
