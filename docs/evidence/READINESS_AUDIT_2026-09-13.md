# Readiness audit — delta report, 2026-09-13 (HEAD 9b9a670, 14:50Z)

Supersedes the classification in `READINESS_AUDIT_2026-09-12.md` (HEAD e4848c3) where stated. Method: seven read-only Codex seams (Grok returned 402 on a two-word probe at 14:28Z), every classification-changing finding re-verified by the coordinator against the artefact. Gate at HEAD: `scripts/ci/run_tests_no_egress.sh` → 8953 passed, 0 failed, 1 skipped, 4 deselected, 3 xfailed, 207 s. Static: ruff 6 (none under src/breezy/adapters|runtime|strategy), `ruff format --check` 65 files, mypy src 6 errors all in `app/trade.py:363-377` (Protocol/Optional typing at the permit-mint call; behaviour pinned green), mypy tests+scripts 439/41, lint-imports 3 kept / 0 broken.

## Ground truth today

- Live node pid 895135 booted 2026-09-12T16:50:30Z on code that predates HF-1 (1d9f74a, 18:28Z) and HEAD (04:49Z 09-13). It halted all four families at boot (`breezy-trade-20260912T165030Z.log:289,325,361,397` "LONG or UNKNOWN") and has been RUNNING-but-halted since. The supervisor (pid 4061490) spawns a fresh venv process (`trade_supervisor.py:563-587`), so the 16:50Z cycle today is the first boot on HEAD.
- `covered_listed_station_days_2026-09-13.json` count 0 (fetch 09-05..09-13).
- Admissible n = 0; 0 fills / 9 live days; MB edge artefact 09-13 UNDERPOWERED (n_taken 7).
- No unit evaluates the v3 (`pm_us_crh_cont`) stop rule; every tally unit is v2 (`breezy-pm-crh-v2-tally.service:46`, `score-live-trials-run.sh:26`).

## Corrections to the 09-12 audit

1. **B1 root cause is the ingest pipeline, not the gap rule.** For 09-12 the in-window resolved-gap count is 0 for all four stations (shard-local accounting works). The day is uncovered because the catalog holds 0.134 min of in-window Depth10 (LAX 2 rows, MDW 0, MIA 0, SFO 1) against the 30-min floor (`structural_dead_stop.py:208,233`). Cause: the 15-minute ingest (`breezy-quote-tape-ingest-frequent.timer` `OnCalendar=*:0/15`) wrote a partial depth file for instance 233aa3ad covering 09:00:40Z–11:15:45Z; every later write of the growing range is refused by the catalog as non-disjoint (journal 2026-09-13T14:00:46Z "conversion of OrderBookDepth10 failed … would create non-disjoint intervals"; also QuoteTick, VenueSettlementSnapshot, DepthTruncation; instances 213d84f7, edb87425 likewise). Exit 3 is truthful (`quote_tape_ingest_cli.py:1350`). No tolerance ruling (R-3) rescues 09-12; max-gap<60 s rescues only 4 station-days, all 09-07.
2. **The HF-1/HF-4 fixes are merged but not running.** Editable install + long-lived process.
3. **B2 partially resolved.** Silent cost branch now loud and unit-pinned (`submit_chain.py:758-800`; `test_polymarket_us_submit_order_chain.py:1941-1997`); `record_venue_order_id` has three production callers (`client.py:1656,1794,2971`). Still open: `generate_order_status_reports`/`generate_fill_reports` return `[]` (`client.py:2126-2166`, gated on R-1); `_has_durable_fill_record` stub (`client.py:1224-1227`); no `_EXECUTION_DRIFT_ALLOWED_KEYS` (by R-6: no captured evidence exists); create-path `KIND_ACCEPT_FILL` never fired on a real order (both real fills went AMBIGUOUS→resolver).
4. **B3 partially resolved.** `ContinuousRungHoldBacktestStrategy` (`continuous_backtest_only.py:87,154`) routes through `_submission_armed()`; driver `--strategy continuous_rung_hold`; depth-basis gate present. The planned SFO 2026-09-01 replay has no artefact (`derived/paper_replay/scored_trials/v3/` absent; 0 files newer than 09-12).
5. **B4 open.** SP-6 de-scoped; `health.py:502-510` falls back to `LoggingAlertSink`; `~/.config/breezy/alerts.env` missing.
6. **SP-1 deployed as serialize, not disable.** Installed units are symlinks to `deploy/systemd`, diffs empty; k1 01:35Z, offer-gate 02:05Z, mb 13:30Z remain enabled under `breezy-studies.slice` + flock. PROGRESS.md:30,50 still calls those hypotheses dead/thin.

## Risk controls (re-verified at HEAD)

Enforced: `_submit_order` gates then permit→ledger→arm→sign→POST (`exec/client.py:2860-2934`, egress-firewall callee allowlist test); operator caps (`operator_controls.py:302`); permit ceilings derived (`safety.py:658,948`); native `max_notional_per_order` bypass=False (`node_config.py:565`); HF-4 release never while intent OPEN (`continuous_strategy.py:1043`); family halt on 2nd genuine fill (`:1213`, `trial_day_latch.py:471`); GET/POST signers disjoint; `allow_short=False`, cancel refused, no flatten path (`exit_guard.py:22`). Known design weakness: ledger in-memory per process — a same-day relaunch resets the daily budget; the durable bound is stations × 1 position × per-position cap.

## Classification

READY: venue auth/connect/permit; submit chokepoint and caps; intent latch; family halt; recorder; NWS ingest; v2 scorer/tally; v3 backtest subclass and driver; gate green.
BLOCKED: (1) ingest non-disjoint-interval collision strands every instance's afternoon → KILL clock unreachable and tape unusable for v3 replay; (2) running node is stale and halted; (3) no v3 tally/stop-rule producer (R-4 unruled); (4) alerts reach nobody; (5) demonstrated edge NONE — a strategy blocker, not an infrastructure one.
NON-BLOCKING: R-1 fee unit + native reports; `_has_durable_fill_record`; drift allowlist (needs evidence first); durable ledger; exit actor; static debt (65 format files, 439 mypy in tests/scripts, `app/trade.py` typing); dead strategy packages (~9.6k LOC unimported); k1/offer-gate/mb nightlies; Kalshi; LADDER_EV; PROGRESS/README contradictions.

## Shortest path

1. Verify the 16:50Z boot today runs HEAD: permit line, INFO startup-evidence summary, ≥1 station armed (not "LONG or UNKNOWN"). Zero build.
2. Fix the one ingest defect (partial-slice interval collision) and confirm a day reaches ≥30 min in-window Depth10 → first count > 0. Only true build item on the critical path.
3. Run the planned v3 SFO 2026-09-01 replay with the existing driver (command in `V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md:80-91`); record filled trials or BLOCKED reason. Zero build.
4. Wire the v3 tally producer + R-4 ruling so the live family has a stop rule. Small build.
5. Operator: one line in `~/.config/breezy/alerts.env`; verify one delivered alert.
6. Stop: disable k1/offer-gate/mb timers; park everything under NON-BLOCKING. Then accumulate takes; at 0 admissible fills in 9 days the first look (n=10) has no ETA.
