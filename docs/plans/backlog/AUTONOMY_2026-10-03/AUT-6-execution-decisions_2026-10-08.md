# AUT-6 execution decisions (2026-10-08, coordinator)

Binding inputs:
- `AUT-6-drift-health_plan_r15.md`;
- `reviews/AUT-6-r15-final.md`, which binds `AUT-6-r13-final.md`;
- `reviews/ARCH-ERRATA-rev9_2.md`.

The WP decomposition was done by the planner, read-only, on 2026-10-08. Only WP1 can be built end to end today.

## Decisions (planner defaults, adopted)

| # | Decision | Ruling |
|---|---|---|
| X-1 | Rows 6 and 7 deadlock: row 7 needs 6, and AUT-6 WP1b/5b/6/8 need row 7 | Split row 6. **6a** = WP1, WP2, WP3, WP3b, WP5 and WP9 (code). **6b** = WP1b activation, WP4, WP5b, WP6, WP7 and WP8, gated on rows 5 and 7 as listed. When 6a is DONE, 7a can start. |
| X-2 | The plan's writer id `legacy-<component>` (l.864) never matches AUT-1's reader regex `[a-z0-9_]{1,64}` (`capture_aut6_contract.py:48`) | Use `legacy_<component>`. |
| X-3 | The redeliver unit's `OnFailure=breezy-autonomy-failed@%n.service` target does not exist until WP4/WP7 | Ship the line and enable the timer now. Record the gap. Until then, check-alerts and AUT-1's delivery-record reader cover it. |
| X-4 | AUT-1 rows with `network="none"` cannot deliver | Give them a write-only `enqueue` API. Redeliver drains those entries, with no `f` record per entry. |
| X-5 | WP4's storm constant exists only in adapters (`recorder_watchdog.py:81`), and AUT-6 may not import adapters | Move it to `domain/` with an adapter alias, and have AUT-6 read it from `domain/`. This happens in WP4. |
| X-6 | `node_liveness`/`permit_lapsed` with FQ v1 orders off and permit capability absent | Before WP6, check the live permit state. If no permit is minted, add a case for orders off or halted, or the detectors page falsely. |
| X-7 | Score 3 (live proof) is unreachable under RULING_FQ-v2-NO-TRADE_2026-10-08 | Build WP9, and score it "machinery proven". The live-proof window opens only when a family sends again. |

## Stale plan anchors (fix them when you implement; do not edit the plan)

- l.1124/1129: ARCH-0 now owns the wrapper and table (`runtime/autonomy_sandbox/table.py:324`). The wait is already met.
- l.894: there are now five node sites: `trade.py:474,533,782,1201` and `node_config.py:521`.
- l.1142: `tests/unit/test_systemd_unit_contracts.py` does not exist. Use `tests/contract/test_autonomy_units*.py`.
- §3.8: the list of failing units dates from 10-02. Re-check it before WP3.

## WP3 slice plan (planner, 2026-10-08; built strictly in order, each slice branching from the previous one's tip)

| Slice | Content | Files |
|---|---|---|
| S1 | Failing units, wrapper exits and disposition | `deploy/systemd/{score-live-trials,portfolio-roi,asos-refresh,replay-daily}-run.sh`; `docs/evidence/unit_health/DISPOSITION_failed_units_2026-10-08.md`; `docs/evidence/aut6/WP3_verify_first_2026-10-08.md` (F2); `tests/unit/test_portfolio_roi_run_no_input.py`; `tests/unit/test_score_live_trials_skip_marker.py`; `tests/contract/test_autonomy_units_programme.py` |
| S2 | Health bwrap row, unit files and contract tests | V-6 in its E-7e form: in-row `systemctl` fails and reads go through the bus snapshot. STOP on any mismatch. The timer is not enabled |
| S3 | `unit_health.py` core | No permit or orders read anywhere (X-6, FQ-v2 NO-TRADE) |
| S4 | `unit_health_daemons.py`: invocation and daemon rules, intraday-stage classification | Fixtures only until WP6. `WATCHDOG_DAEMON_UNITS` stays empty until WP4 |
| S5 | `monitor_watch.py`: timers (both templates), producer, alert delivery, memory #31 | A not-deployed producer or canary is INCONCLUSIVE, never FAIL (decision X-8 below) |
| S6 | CLI pass, rollup, C4, runbook marker, `aut6.health` pin (last) | F6: p99 ≤ 90 s over 20 runs. STOP if it fails |

**Stale anchors found by the planner:**
- `discovery-pull` is now at 17:12Z, not 16:52Z.
- Exit 75 also occurs in `portfolio-roi-run.sh` and `replay-daily-run.sh`.
- The health bound is slot + 146 s (E-7e).
- There is a second timer template, `us-source-collector@`.
- The ARCH programme tests already exist in `test_capture_units.py:182` and `test_launch_window_table.py:421`. Extend them; do not copy them.

**Decisions that carry over to later work packages:**
- Watchdog checks move to WP4.
- AF3 moves to WP6.
- The AG3 stage-reset half moves to WP5b.

## Later decisions

| # | Decision | Ruling |
|---|---|---|
| X-8 | Producer, canary and daily-verdict staleness checks (#23, #26, #27) meet units that are not deployed yet (WP2, WP6, WP7) | Ruling, after silent-failure review (CHANGES applied). One committed table, `NOT_YET_DEPLOYED`, in `monitor_watch.py`, with rows `(unit, owner_wp, not_expected_until)`. A unit's row is deleted only by its owning WP's activation commit. A unit gets `INCONCLUSIVE(not_deployed)` only if ALL hold: (1) its row is present and today is before `not_expected_until`; (2) no file and no broken symlink for it exists in `~/.config/systemd/user`; (3) none of its artifacts exists (heartbeat, canary record, daily verdict, summary line, `armed.json`). Otherwise: a missing unit not in the table is FAIL CRITICAL; a broken link is FAIL `unit_link_broken`; an absent unit with artifacts present is FAIL `deployed_then_vanished`; past `not_expected_until`, WARN then CRITICAL on the `AUT4_REPLAY_EXPECTED_BY` clock. Unit names resolve from `deploy/systemd/` file names. INCONCLUSIVE never pages and never counts toward `unknown_streak`. It is listed as `not_deployed=[...]` in `day_<date>.json`. Tests: deleted link, broken symlink, renamed unit, artifact present while unit absent, unlisted absent unit, past deadline, plus the positive control (never-deployed listed unit reads INCONCLUSIVE). `test_every_deploy_systemd_unit_is_installed_or_listed` covers the rest. |
| X-9 | WP2 verify-first | Path B. See `AUT-6-WP2-pathB-ruling_2026-10-08.md` (in peer review). |
| X-10 | Redeliver unit `ReadWritePaths=` broke bwrap on this host | Fixed by a65ee68f/03789239, with a contract ban on mount-namespace directives in any wrapped unit. Every new AUT-6 unit inherits the ban. |
| X-11 | `nbp_drift.py` placement | `nbp_drift.py` holds the pure predicates; `check_drift`/`check_freshness` stay in the script. This is an accepted divergence from the plan text. |
