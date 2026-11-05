# RULING — EDGE-6c-R: `breezy-k1-daily` disposition (2026-09-27)

**Decision: RETIRE the scheduled unit.** Keep the script, its library functions and the snapshot history.
The coordinator decides this under the standing pre-authorization, after a two-peer adversarial loop. It needs no operator input, because it touches no budget or position cap.

## Peer loop
| Peer | Verdict | Notes |
|---|---|---|
| Codex (evidence gather, read-only) | RETIRE, HIGH | Found no live consumer. Its slice list was incomplete, and one row was wrong (`test_asos_refresh_re_home.py` has no K1 reference). |
| architect | APPROVE-RETIRE with conditions C1–C6 | 9 citations verified, 1 refuted, 1 partly wrong. It found six gaps in the slice (below). |
| prediction-market-reviewer | RETIRE, HIGH | Added fact K-E9. |

## Facts (plan §2.3 K-E1..K-E8 plus these)
- **No consumer.** Nothing reads `~/.local/share/breezy/k1/`, `k1_*.md` or `k1_daily.log`: not `src/`, `scripts/`, `deploy/`, tests, `~/.claude/bin`, the installed units, or `docs/evidence`. No PREREG, KILL witness or hypothesis-ledger entry depends on the output.
- **Unrefutable at the daily cadence (K-E3, sharpened).**
  - Pooled ≤0.01 accrues about 0.2 qualifying observations per day: n=6 on 09-12, n=9 on 09-27.
  - Separating 3% from 1% needs n≈96, about 435 days away. Refuting at zero YES needs n≈359, about 4.8 years away.
  - ≤0.05 is FAMILY_DEAD (n=179, k=2, Wilson-high 0.0398 < break-even 0.0529).
  - **≤0.02 and ≤0.03 are UNDERPOWERED, not dead.** PROGRESS's "K1 DEAD at ask ≥2c" is scoped to the ≤0.05 family.
- **Mis-timed (K-E5).** The recorder's first D+1 observation lands about 5 h 13 min after listing, so K1's "cheap open" is not the true open until EDGE-6d lands.
- **K-E9 (new): SEARCH/CONFIRM firewall breach.**
  - The 09-27 report computes verdict statistics over climate-day 09-26 entries, with entry timestamps 2026-09-25T14:5x–15:00Z. That is post-freeze tape, and it was undeclared.
  - Each nightly run permanently spends H-ARCHIVE-RECAL-2026-09 CONFIRM station-days (README binding rule; EDGE-4 disposition). That is the long pole of EDGE-5.
- **Reversible.** Inputs are the retained quote tape and settlement catalog (`k1_cheap_open_settlement.py:147-150`). No pruning of either exists anywhere in the repo.

## Containment (done 2026-09-27 ~03:55Z)
`systemctl --user disable --now breezy-k1-daily.timer` plus `daemon-reload`. `list-timers` shows NEXT `-`. The repo unit files stay in place until the retirement slice merges.

## Conditions (binding on the retirement slice)
- **C1.** Re-open trigger: EDGE-6d is live (true-open capture) and a declared SEARCH corpus exists. Re-running then is a manual `k1_cheap_open_settlement.py` invocation, never a timer.
- **C2.** One reviewed row per pin. The heavy-study band is replaced by DISCOVERY, never left to run over an empty parametrization, which pytest would silently skip (L-24 anti-vacuity). Required: any `deploy/systemd/*.service` with `MemoryHigh ≥ 12G` equals the declared heavy set (now empty), with a negative control on a synthetic heavy unit.
  - Pins: `test_analysis_units_serialized.py` :366-387, :559-563, :613-617, :653-663 (the timer-exists row only), :741.
  - `test_alerts_env_deploy.py` :27-28 and :80.
  - `test_position_monitor_report_deploy.py:300` and `test_exit_window_study_deploy.py:358` are re-anchored to a surviving wrapper or a shared constant.
  - `test_analysis_units_memory_capped.py:30` self-heals (`is_file()` filter): leave it and say so.
  - `test_study_failure_alert.py:178-228` needs no change.
- **C3.** Remove the timer, service, `k1-daily-run.sh` and `~/.config/systemd/user/breezy-k1-daily.service.d/zz-timeout-TEMPORARY.conf` together, then `daemon-reload`. Prove it: nothing K1 in `list-timers`, and `DropInPaths` is empty.
- **C4.** Keep `k1_cheap_open_settlement.py`, `tape_arrow_columns.py` and the snapshots. The six importers still import, and `test_k1_cheap_open_settlement.py` and `test_k1_kalshi_prior.py` stay green.
- **C5.** Mark the README install/enable lines RETIRED, the way AUD-15 did. Update the PROGRESS row.
- **C6.** Full `scripts/ci/run_tests_no_egress.sh` plus `lint-imports` after the merge.
