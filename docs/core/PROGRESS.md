# Breezy — Progress and Backlog

**This file tracks OPEN state only.** Closed work, resolution narratives and
evidence summaries do not live here. They live in git history,
`docs/evidence/`, and `docs/core/archive/`.

## Maintenance contract (BINDING, enforced)

Hard budget **250 lines / 12 KB** (`.claude/hooks/progress-size-gate.sh`);
consolidate when it blocks, never raise it. An item LEAVES this file when it
closes — the commit is the record. Never restate evidence (link
`docs/evidence/`) or durable rules (`docs/core/LESSONS.md`). Severity tags mark
OPEN items only. Rationale L-5; pre-shrink copy in `docs/core/archive/`.

---

## Operator control contract (set 2026-08-30) — BINDING

Two reserved controls: **maximum daily budget** and **maximum per POSITION**.
They live ONLY in the operator's gitignored `operator.env`, present by NAME in
the supervisor/node env, enforced per grant by `DailySpendLedger.authorize_order_cost`
(`operator_controls.py:348`; process-local, re-seeded at boot from durable fills via
`exec/client.py:2214`). The three session ceilings derive from the two caps at
permit mint (`safety.py:552-608`). Everything else is build-side.

## Standing verdicts that gate future work

- **NO FAMILY HAS A PROVEN EDGE; NO FAMILY TRADES.** Node runs `pm_us_crh_fq_v1`
  with orders OFF (drop-in `fq-v1-halt-orders-off.conf`). Re-open only via
  `RULING_FQ-v2-NO-TRADE_2026-10-08.md` T1/T2/T3; review 2027-01-25.
- **Forecast-taker hunt CLOSED** (`RULING_forecast_edge_programme_closes_2026-09-20.md`:
  market resolution 1.98× forecast). Lock strategies DEAD (L-9). Cheap YES is a
  measured loser (M1 scan; TE-2 TAIL 44%). NBP PM.us leg INFEASIBLE (node 4).
  Live record: 34 fills / 4 wins / −2.63 (`TRADE_EFFECTIVENESS_2026-10-11.md`).
- **Price history is forward-only (from 2026-08-30)**; a forecast archive is a
  CALIBRATION set, never a backtest. Venue surface = 5 cities × daily HIGH.
- Pre-backlog state as of 2026-10-12 (every prior row, dispositioned):
  `docs/core/archive/PROGRESS_2026-10-12_pre-maker.md`. Items there are PARKED,
  not closed; nothing from it is scheduled while the MAKER programme runs.

---

## BACKLOG — MAKER programme (operator 2026-10-12: "replace the backlog with this work")

Spec: `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` (v0.3, T2
candidate). Plans: `docs/plans/backlog/MAKER_2026-10-12/` (`S<n>_*_plan_r<N>.md`,
peer reviews in `reviews/`). Execution order is strict; each step's STOP
condition ends the programme and the family stays at its last version.

**Binding on EVERY item.** Nautilus immutable; never `allow_short=True`; never
weaken `BacktestOrderGuard` or any safety, settlement, contract or NO-SEND
firewall test (widen exact sets by one reviewed row, L-12); never touch live
enablement or `BREEZY_ORDERS_ENABLED`; never invent an operator-reserved value;
never edit a frozen PREREG; Stage 0 is exploratory, never promotion evidence.
Durable processes via `systemd-run --user` (L-26) with RuntimeMaxSec + stall
watch; worktree commands need `PYTHONPATH=<wt>/src`; never `uv`/`pip` from a
worktree; never `git stash`; full gate after EVERY merge (basetemp under
~/.cache, rm after reading EXIT); `lint-imports` from the tree root.

| # | ID | Work | Needs | STOP condition | Status |
|---|---|---|---|---|---|
| 1 | S1 | Maker-window print census (recorder liveness + `trade_tick`, dedupe on trade_id) incl. a dated SEARCH declaration for post-09-25 tape; resolve/bracket `TRADE_QUANTITY_UNIT` from own fills | WP0: ≥10 GB disk | E below the n_eff ≥ 30 floor → UNDERPOWERED, route to Q1 | IN PROGRESS: WP0 FINAL 6068a00e (72 station-days); WP1+WP2 built, 4 blind reviews, gate-green; RUN ≥ 10-14 10:00Z per `S1_RUN_PROCEDURE_2026-10-14.md`; then WP3 (if single-hypothesis) + WP4 |
| 2 | S2 | Stage 0 exploratory maker replay (spec §6.0/§6.1, process-schedule episodes, pooled §6.9) → `docs/evidence/maker/STAGE0_REPLAY_*.md` | 1 | NO-GO (stressed fill rate < 0.10 or §6.9 FAIL) → programme ends; UNDERPOWERED-WAIT (n_eff < 30) is not a STOP | PLAN r4 READY 10-13 (r3 + `S2_stage0_replay_plan_r4_delta.md`, 3 verification rounds PMR+MLE); build WP0–WP6 on fixtures may start (delta (k)); run needs S1 outputs + amendment FINAL (`RULING_MAKER-S1_SEARCH_declaration_amendment_2026-10-13.md`, DRAFT until the frozen date set is filled after S1) + P2 backfill |
| 3 | S3 | A1 loss-floor reachability for the maker mix (FloorSpec on the FQ engine; FQ result byte-reproduced) → `docs/evidence/maker/A1_REACHABILITY_*.md` | build half (WP0/WP1/WP3) needs nothing; binding run needs 2 NOT-KILLED + window ruling | `unreachable_veto` at the stressed fill rate → not registrable, programme ends | BUILD HALF DONE 10-13 (merge d04cc918 + fix 9993960b, full gate EXIT=0): WP0 pins, WP1 FloorSpec (FQ byte-identical), WP3 maker CLI; plan r4 = r3 + delta rev 2; window ruling FINAL `RULING_MAKER-S3_loss_stop_window_2026-10-13.md`; WP4 step 0 calibration DONE 10-13 (b8f2e75f: sweep unit RuntimeMaxSec 7300 / binding 18700, MemoryMax 9G); binding run still needs S2 r_lo, S1 listing rate (derived in WP4), S5 WP0a cap pin |
| 4 | S4 | Exec resting path: GTD BUY NO, per-order + slug cancel-all, K=1 released on ACCEPTED_RESTING, boot sweep; ~24 WIDENED pin rows | 2, 3 PASS (WP0 discovery is read-only and starts now) | venue refuses non-post-only GTD or slug-scoped cancel-all → programme ends | WP0 DONE 10-13 (9710f303): read-only discovery `MAKER_S4_WP0_VENUE_DISCOVERY_2026-10-13.md` (17/60 GETs); WP1+ gated on 2,3; PLAN r4 READY 10-14 (`S4_exec_resting_order_path_plan_r4_delta.md` rev 3.1; 3 rounds security + architect, `reviews/S4-r4-*`; rev 3.1 accepted by coordinator check per the architect's round-3 terms); WP1 step 0 (71-market discovery characterisation test) may be built ahead of 2,3; UNVERIFIED only the venue order-id charset (fail-closed regex) |
| 5 | S5 | `no_ladder_maker` family (SHADOW, never submits), PREREG frozen before start (A1 stop, calendar split, read target 300/200), scorer + 9-gate advisory report | 2, 3 (S4 only at gate 8) | any §7 gate FAIL on the read-once holdout; UNSCREENED-TERMINAL power stop | PLAN r3 READY |

Review record: 11 r1 reviews, 6 r2 verifications (`reviews/`), r3 = conformance to spec v0.3. Known residuals: S4 no-id maker fill during node downtime stays AMBIGUOUS (fail-closed, alert); bid-live window ≈ 10 h/day under the 16:50Z launch + 10 h permit (spec §3). Disk: 121 GB free after 2026-10-13 00Z (789 gate basetemps removed); collectors reset after `disk_guard_refused`; LESSONS.md volume gate CLOSED 2026-10-13 (5b82b3de, 30 KB canonical; full text archived 4fb736f6).

Activation after S5 PASS remains manual (`BREEZY_SENDING_FAMILY_ID` + supervisor
restart + `live_orders_ruling`); no auto-arm path is built by this programme.

### Calendar obligations (pre-registered; never moved after seeing data)
| When | What |
|---|---|
| ≥ 2026-10-21 | F13 `source_lags_ns` freeze (T3 input) |
| ≥ 2026-12-07 | M1-v3 single read-once (`no_longshot_pooled_test.py`, default `--out`); T1 route |
| 2027-01-25 | NO-TRADE ruling review; RA-13 KILL backstop |

### Live-state watches (no build owed)
- `breezy-aud07-m1c-drain20k` timer: remove when DEFERRED empty (AUD-07, parked).
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
