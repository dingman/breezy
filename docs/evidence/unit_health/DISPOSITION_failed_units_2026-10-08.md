# Failed-unit disposition, 2026-10-08 (AUT-6 WP3 slice S1)

Supersedes the 10-02 list in plan r15 §3.8, which was stale. Evidence is read-only `systemctl --user` and
`journalctl --user` (no secret values quoted). Verify-first record: `docs/evidence/aut6/WP3_verify_first_2026-10-08.md`.

## A. Units failed at the time of the census (`list-units --failed --all`, ~20:50Z)

| Unit | Root cause (journal) | Disposition |
|---|---|---|
| `breezy-autonomy-alert-redeliver.service` | `2026-10-08T20:10:09 ... bwrap: No permissions to create a new namespace, likely because the kernel does not allow non-privileged user namespaces.` then `Main process exited, code=exited, status=1/FAILURE`; also `Failed to enqueue OnFailure=breezy-autonomy-failed@breezy-autonomy-alert-redeliver.service.service job, ignoring: Unit ... not found.` Both failures (20:10:09, 20:10:58Z) were manual starts of the timer-linked-but-not-enabled unit during WP1 bring-up (`is-enabled`: `linked`; the timer has never triggered). | **Fixed upstream of S1** by a65ee68f / 03789239 (X-10: `ReadWritePaths=` mount namespace broke the bwrap userns; contract ban added), committed 20:14Z, after this failure. **Reset-failed at activation (pending)**: one `reset-failed` once the fixed unit is live and a manual run exits 0; not yet done. The missing `OnFailure=` target is X-3 (lands with WP4/WP7); not a defect of S1. |

## B. Units named in plan §3.8 that are no longer failed

Already reset before this slice began (`LoadState=not-found` or `Result=success`). Listed so none is silently dropped.

| Unit | Root cause | Disposition |
|---|---|---|
| `breezy-portfolio-roi.service` | `2026-10-08T17:40:00Z PORTFOLIO ROI SKIPPED -- no score-live-trials success marker for 2026-10-08`, `status=1/FAILURE` (also 10-07). `score-live-trials` correctly SKIPs the FQ sending family (`score_live_trials.log`: `2026-10-08T14:15:00Z SCORE LIVE TRIALS SKIPPED -- composition_kind=forecast_quantile_ladder has no score_live_trials`) and wrote no marker, so the downstream report failed every day. | **Fix merged, unverified until the first scheduled run (10-09 17:40Z)**: `score-live-trials-run.sh` writes `score_live_trials_ok_<date>.skipped` (`reason=composition_kind_has_no_scorer`); `portfolio-roi-run.sh` prints `PORTFOLIO ROI NO_INPUT -- upstream skipped: composition_kind_has_no_scorer`, exit 0. An absent marker, or one with a reason outside the closed set, still exits 1. The skip marker is written tmp-then-`mv -T` and the write is checked (unwritable: `SCORE LIVE TRIALS FAILED -- cannot write the skip marker`, exit 1, no marker). **Known gap, accepted (bounded to one day):** if the sending family changes from a scorer-bearing family to FQ (or back) between 14:15Z score-live-trials and 17:40Z portfolio-roi, that day's marker no longer matches and the report exits 1 (or reports NO_INPUT) once; the next 14:15Z run realigns it. Takes effect at the next 17:40Z run once the primary tree carries the commit (wrappers are read at run time; no daemon-reload needed). |
| `breezy-fee-evidence-pull.service` | `2026-10-08T11:10:00 fee_drift_evidence_pull: date=2026-10-08 complete=False markets_listed=0 ok=0 reason=empty listing: the /v1/markets query (categories=['climate'], active=True, closed=False, archived=False) matched zero weather markets`, `status=1/FAILURE`. Same signature on 2026-10-01 (11:10Z); the other 11 days of 2026-09-27..10-07 show `complete=True markets_listed=60 ok=60`. Both empty days were Thursdays (n=2, a pattern worth watching, not a finding). | **Keep, exit 1 is correct**: an empty listing is incomplete evidence and must not look like a clean day. It self-recovered the next day both times. No S1 change. Recommend the health pass classify it as a data-availability finding (the 12 other days are the control), not a unit fault. |
| `breezy-replay-daily.service` | Not failed: every run since 10-01 is `Finished`, but replay has not run since 09-30. See section C. | See section C. |
| `breezy-parity-mem-1d`, `breezy-parity-mem-7d` (transient) | `2026-10-01T03:56:54 ... status=1/FAILURE` (74 s, 2 GB) and `04:17:43 ... status=1/FAILURE` (20 min, 5.8 GB). Journal shows two agent benchmark runs of `scripts/analysis/nbp_shadow_parity.py` from worktree `fq-parity-mem` (`--start-date 2026-09-01`, end 09-01 and 09-07); the 7d run logged many `Cannot find instrument ... No data has been loaded` errors, but no parity-mismatch message and no exit reason is retained. **Cause of exit 1 not determined** (plan r15's 'parity mismatch' is not supported by the retained journal). | Agent benchmarks; already reset. Nothing to do. |
| `run-p814078-i21773018` (transient) | `2026-10-02T19:09:05 Started ... scripts/analysis/nbp_shadow_parity.py --start-date 2026-09-25 --end-date 2026-09-25 ... --output .../r31-parity/report.json`, then `19:09:06 ... status=2/INVALIDARGUMENT` (1.3 s wall, 190 MB). No stderr retained, so **the cause is not determined** (exit 2 within 1.3 s suggests an argument/validation refusal, unconfirmed). | Agent ad-hoc run. Already reset; nothing to do. |
| `breezy-replay-backfill-0929` (transient) | `2026-09-29T12:38:25 ... status=1/FAILURE`, 2 h 08 min, 10 G peak. | One-time backfill, superseded. Already reset; nothing to do. |
| `fq-halt-20261005` (transient) | No journal left for the name; `LoadState=not-found`. | Already reset; superseded by the 10-06 re-time. Nothing to do. |
| `breezy-discovery-pull.service` | 10-02/10-03 `Failed with result 'timeout'`, 13.9 s CPU over 30 min, 4 GB swap peak (working set > 1 GB, L-49). | **Fixed by WP3b** (wave 1). Latest run `2026-10-08T20:09:50Z Finished`. |
| `jetbrains-remote-dev.service` | Foreign (`Invalid environment assignment, ignoring: -Xmx2g`). | Foreign per plan §3.9; the health rollup lists it under `foreign_failed`. Not ours. |

## C. replay-daily stalled since 10-01 (R3V-a): by design idle, with a masking bug

Facts (`replay_daily.log`, `wrapper_skip_state`, journal):

- Last real replay: `2026-09-29T15:54:30Z replay daily ok`; last runner activity `2026-09-30T16:17:39Z REPLAY DAILY FAILED` (MIA `DRIVER_TIMEOUT`). `replay_results.jsonl` mtime 2026-09-30 16:17:38Z.
- 10-01, 10-02, 10-03: `REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder has no replay_daily_runner` (S7 branch, `resolve_rc=3`, exit 0). The sending family is `pm_us_crh_fq_v1`, so there is nothing to replay: **by design idle**.
- 10-04 .. 10-08: `SKIPPED -- another study holds the studies lock` (`wrapper_skip_state` = `5 LOCK_CONTENTION`), with `BREEZY_REPLAY_SKIPPED_STALLED ... 5 consecutive wrapper skips` alerts on 10-06, 10-07, 10-08.
- Cause of the contention: `breezy-exit-window-study` starts at 15:20Z and was killed by its 30 min `TimeoutStartSec` at **15:50:02Z** on 10-07 and 10-08 (`Failed with result 'timeout' ... Consumed 13.065s CPU time over 30min 2.042s wall clock time`), i.e. 2 s after replay-daily fires at 15:50:00Z. Since 10-04 the two have collided. The study was contained in wave 1 (20:10Z run: `Finished`, 8 s).

Conclusion: the replay is idle by design for the FQ family (no replay machinery applies), so replaying nothing is correct. What is broken is order of checks: the wrapper takes the studies lock BEFORE resolving the family, so a lock collision records `LOCK_CONTENTION` and raises `STALLED` alerts for a job that would have skipped for composition anyway. Exit 75 is not involved (the 75 paths are lock-infra failures, never hit).

Proposed disposition (not built in S1, outside its file list's intent): (1) **Built in this slice's review follow-up:** the FQ composition skip (`resolve_rc=3`) now runs `replay_daily_runner.py --reset-skip-state` before `exit 0` (a failed reset exits 1), so the stale `5 LOCK_CONTENTION` counter clears on the first FQ run instead of persisting. Corrected 10-09 15:50Z acceptance: the FQ run logs `REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder ...`, exits 0, and `wrapper_skip_state` reads `0 ` afterwards (not 'resets on a real replay', which an FQ day never reaches); no further `STALLED` alert. This also needs the primary tree to carry the commit (wrappers read at run time). (2) Still a separate follow-up, NOT done here (lock/family resolution order is unchanged): resolve the family and take the `composition_kind` skip (exit 0, no recorder) before the lock in `replay-daily-run.sh`, so an FQ day never counts toward `LOCK_CONTENTION`. This needs a new test next to `test_a_forecast_quantile_ladder_sending_family_skips_without_replay_tooling` and must keep `systemctl show` failure non-zero.

## D. Exit 75 (EX_TEMPFAIL) wrapper paths: kept as real failures

Plan r15 §3.8 listed `asos-refresh-run.sh`, `portfolio-roi-run.sh` and `replay-daily-run.sh` `SKIPPED-INFRA ... exit 75` as "would fail as expected behaviour". Re-read: all nine lock-taking wrappers (`asos-refresh`, `decision-funnel-digest`, `decisions-retention`, `exit-window-study`, `hypothesis-triage`, `portfolio-roi`, `position-monitor-report`, `replay-daily`, `station-candidate-register`) share one preamble where 75 means the studies lock directory or file cannot be created/opened (or `HOME` and `XDG_RUNTIME_DIR` are both unset). That is a broken environment, not an expected condition: continuing would let 10-24 GB studies overlap. The existing test `tests/unit/test_analysis_units_serialized.py::test_every_flock_wrapper_refuses_loudly_when_the_lock_dir_is_unwritable` pins exit 75 and `SKIPPED-INFRA`, and every owning unit carries `OnFailure=`. None of the three has ever exited 75 in the retained journal.

Decision: exit 0 would hide a failure; `SuccessExitStatus=75` would do the same (and `us-source-collector@.service`, which does use it, is a per-instance `flock -E 75` overlap guard, a different meaning). Neither was done. The lock-busy paths already exit 0. `tests/contract/test_autonomy_units_programme.py` encodes the distinction and forbids `SuccessExitStatus=75` on those units.

## E. score-live-trials with no sending family

`BREEZY_SENDING_FAMILY_ID` is present on `breezy-trade-supervisor.service` today (`systemctl --user show -p Environment` lists the name; value not printed here), and the score-live-trials unit has no `Environment`/`EnvironmentFile` of its own. An absent id still means the supervisor unit drifted, not "nothing is armed": the wrapper keeps exit 1 and writes **no** skip marker, pinned by the existing `test_the_counter_refuses_when_the_sending_family_id_is_absent_or_unregistered` and a new test. No family ids are invented; `no_sending_family` is NOT in the closed reason vocabulary.

## F. Wrapper skip paths not treated as benign, and the one plan deviation

`tests/contract/test_autonomy_units_programme.py::test_every_wrapper_skip_path_exits_success` now FAILS a benign skip whose `say` has no following `exit` unless an explicit `_CARVE_OUTS` row (wrapper, message, expected `return N`, caller path to exit 0, reason) matches and its path is verified in the file. Three rows: replay-daily and score-live-trials FQ skips (`return 3` / `return 2`, caller exits 0) and asos-refresh `SKIPPED-LOCK` (falls through; tail exits 0 unless a fetch FAILED). Each row is checked live, so a stale one fails.

"... no score-live-trials success marker for <date>" lines are deliberately NOT in `_BENIGN_SKIP`; all three exit 1:

- `portfolio-roi-run.sh`: reads the `.skipped` marker first (NO_INPUT, exit 0); a missing marker with no skip marker is a real failure.
- `family-tally-v2-run.sh`: the FQ composition skip (line ~145, exit 0) precedes the marker check, so an FQ day never reaches it; for scorer-bearing families a missing marker means the scorer failed or did not run.
- `live-tally-run.sh` (v1 PREREG tally): **open gap, not fixed in S1**: it has no FQ branch, so while FQ is the sending family it exits 1 daily with "no score-live-trials success marker". It is outside S1's file list and a real behaviour decision (retire/skip the v1 tally under FQ); flagged for the coordinator.

Plan deviation: plan r15 §3.8 called for `test_every_wrapper_skip_path_exits_success` to treat `SKIPPED-INFRA` exit 75 as success. It does not: exit 75 stays a failure (see section D), and the test asserts the two labels never cross (`SKIPPED-INFRA` always 75, plain `SKIPPED` never 75). Reason: 75 means the studies-lock directory or file is unusable; exit 0 or `SuccessExitStatus=75` would hide a broken lock that lets 10-24 GB studies overlap.

## Activation record, X-16 steps 1-5 (2026-10-09, feat `0d459241`)

- **Failed units at the seed** (`systemctl --user list-units --failed --plain --no-legend`): empty, count 0. No owned
  unit was failed, so the seed did not hide anything.
- **Step 1 (install):** created under `~/.local/share/breezy/` mode 0700: `.bwrap_probe/` in `evidence/unit_health`,
  `derived/verdicts`, `evidence/alerts` and `cache/aut6_health_bus`; `evidence/unit_health/buildside_restart/`;
  and the empty health lock `evidence/unit_health/.health.lock` (0600). `systemctl --user link` of
  `breezy-autonomy-health.service` and `.timer` from `/home/jon/breezy/deploy/systemd/`, then `daemon-reload`.
  Both units: `LoadState=loaded`, `UnitFileState=linked`, `ActiveState=inactive`. The timer is NOT enabled.
- **Step 3:** `evidence/unit_health/fold_export_seen` absent and `evidence/registry/` absent (so the fold reads
  `not_deployed` until 2026-11-16 or the first export). sha256 of the live
  `fq-v1-halt-orders-off.conf` equals the allowlist row (`5ff0d6a1…e09d`).
- **Step 4:** `python -m breezy.runtime.autonomy_health_cli --seed-cursor-now` exit 0:
  `AUTONOMY_HEALTH_SEED cursor=baseline reason=activation_baseline since_us=1791534020151869`; the journaled
  `cursor_reset__<ts_ns>.json` carries `reason=activation_baseline`.
- **Step 5:** one `--dry-run` in the health row's real bwrap argv: `pass_result=UNKNOWN failed_units=0
  new_failures=0 foreign_failed=0 journal_blind=0 drift=0 allowlisted=1 cursor_reset=0
  unknown_reasons=timer_property_missing:breezy-autonomy-health.timer:block`. Findings: none (zero CRITICAL). Listed
  not deployed: `registry_export` and the producer-daily and producer-intraday service and timer.
  Allowlisted: `breezy-trade-supervisor.service:fq-v1-halt-orders-off.conf`. The single UNKNOWN reason is the
  health timer itself: a linked, inactive timer is not loaded, so the snapshot has no block for it; it clears once
  the timer is enabled and active (step 6, not done here).
