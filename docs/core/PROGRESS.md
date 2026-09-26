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
(`operator_controls.py:301`; in-memory per process BY DESIGN, `:252-265`). The three
session ceilings derive from the two caps at permit mint (`safety.py:552-608`).
Everything else is build-side.

## Standing verdicts that gate future work

- **G-02 ROI feasibility NO-GO** on the downstream programme (not the first fill). `docs/evidence/roi_feasibility_2026-08-26.md`.
- **G-01 prelim→final revision POWERED FAIL** on MDW/NYC/SFO; interior-bucket strategies dead. `docs/evidence/observation_lock_falsification_2026-08-31.md`.
- **Lock strategies DEAD (L-9); K1 DEAD at ask ≥2c.** Forecast-family KILL **SUPERSEDED 09-18 by ruling** `docs/evidence/RULING_forecast_edge_family_2026-09-18.md`: `pm_us_crh_fc_v1` Stage 0 per `docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md` (§0.3 binding); arming displaces `pm_us_crh_cont`.
- **Price history is forward-only; a forecast archive is a CALIBRATION set.** Venue surface = 5 cities × daily HIGH. BL-6 (no NO-side instrument) is SUPERSEDED by the 09-14 operator ruling: NO-side hunting is a requirement (NO-1).
- **NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER LIVE MEASUREMENT** (`pm_us_crh_cont`, PREREG v3 BINDING, d0 2026-09-12; `pm_us_crh_v2` still REGISTERED). Demonstrated edge NONE; admissible n = 0 after 10 live days; 10 orders, 9 fills as of 09-24 (9 durable exec-fill-store records, exact match against real-event log lines net of inferred/relaunch noise; order 1, 09-05, had no fill — AMBIGUOUS no-response, operator-cleared; `ORDER1_NO_ORDERSUBMITTED_2026-09-26.md`). Multi-position ruling 09-14 (R-10) lifts the one-per-station bound; MP-A merged b5a7c04.
- **Readiness audit 2026-09-12** (`docs/evidence/READINESS_AUDIT_2026-09-12.md`): the KILL-clock counter read 0/15 for 09-05..09-11 BY MECHANISM (any-overlap rule + feed-wide gap fan-out; L-38), not by outage; the create-path accept-fill branch has never fired live; v3 has never been fill-replayed; alerts reach nobody.

---

## BACKLOG — verified open set (re-synced 2026-09-26 16:35Z against merges, evidence and host)

**Binding on EVERY item.** Never set `allow_short=True`; never weaken `BacktestOrderGuard` or any
safety, settlement, contract or NO-SEND firewall test (widen exact sets by one reviewed row, L-12);
never touch live-trading enablement; never invent an operator-reserved value; PREREG semantics change
only via a ruling under `docs/evidence/`. L-1 null-hypothesis verdict per increment. Durable processes
via `systemd-run --user` (L-26); worktree commands need `PYTHONPATH=<wt>/src`; never `uv`/`pip` from a
worktree (shared venv); never `git stash`. Full gate after EVERY merge. AUD plans: `docs/plans/backlog/AUDIT_2026-09-21/`.

| ID | Sev | Open work (exact) | Source |
|---|---|---|---|
| ING-2 | HIGH | S3a merged 2d36198 (live). AC-S3-5: (a) fast path ΔRSS 0.171 GiB PASS; (b) forced EXTEND 1.0215 GiB FAIL → T-b (T-a already fired). **S3b** chunked EXTEND in TDD (`breezy-ing2-s3b`), incl. arm 3b + AC-S3-5(b) rerun ≤1 GiB. Then: T5′ EXTEND bound k=2 (deferred from S3b), deploy, and remove TEMPORARY drop-in `zz-memory-containment-TEMPORARY.conf` (12G/14G) only after a post-deploy EXTEND run is bounded — keep it through the 09-27 09:00Z rotation. Residual: deferred units have no alert | `ING-2_S3_plan_r2_2026-09-26.md` r3/r3.1 |
| T5′ | HIGH | Gate RED since 2d36198: `test_control_scales_far_faster_than_the_coalesced_treatment` sees control ΔRSS=0 under host memory pressure (file-backed RSS evicted). Redesign to a residency-invariant metric, thresholds unchanged, in TDD (`breezy-t5p`). Gates at 08535a9 were red on this test only (+ FU-11, since fixed) | 09-26 gate logs |
| AUD-07 | HIGH | Code S′ a40d433 merged; `breezy-aud07-m1c-seg-0927a` armed 09-27 02:10–08:40Z: CAL rerun → cal_check → 20k (F_GATE_MAX=1.0, PR-3) → 80k → `--final` → AC7 ruling; then base §7 steps 7, 7b, 8 | `RULING_aud07_m1c_eps_k_decision_rule_2026-09-26.md` |
| AUD-02 | MED | WP-D1 live (`breezy-discovery-pull.timer` 16:52Z; day 1 = 09-26); A0 fee-evidence earliest close 09-30; DoD 10 coordinator block / Amendment C pointer | completion plan §2, §5 |
| AUD-05 | MED | §7 step 8: observe three consecutive 17:20Z v4 tally runs (1 so far) | AUD-05 §7 |
| AUD-10b | MED | Replay timer now live (AUD-09b closed); proposal evaluates (`NO_PROPOSAL(C-ESTIMATOR,C-N,C-VALIDITY) INERT(C-PAIRED)`). Owed: evidence doc `PROMOTION_PROPOSAL_MECHANISM_<date>.md` (C1–C20) from unattended runs | AUD-10 §8 |
| AUD-18 | MED | (b) schema-v2 stratum/draw binding BLOCKED until a look-taking registration or REPLAY_VALIDITY flip | AUD-18 plan amendment |
| FU-3d | MED | Scored-path P&L is per-contract (residual is qty-scaled) — scale the scored path; track the fee_unverified ≤1¢ residual bias | FU-3c plan r1.1 |
| FU-9 | MED | ROI report: `StorePositiveControlFailedError` skips 4 station scans for `pm_us_crh_exit_v4` — investigate | 09-26 FU-3c run |
| FU-8b | LOW | Runtime refusals re-polled only on ComponentStateChanged (no timer) — add a native Nautilus clock timer re-poll | FU-8 plan r2 |
| SP-5b | LOW | Build indeterminate-exclusion of dead-recorder gap rows, prospective (new registrations only); 60 s tolerance REJECTED | `RULING_SP-5_R-3_coverage_tolerance_2026-09-26.md` |
| R-7-IMPL | LOW | Live from the 09-26 16:50Z spawn: confirm the first `R7_POSITION_REPORTING_LAG` line after a create-path fill | `RULING_R-7_position_reporting_lag_2026-09-26.md` |
| TALLY-V2 / DIGEST | LOW | Re-verify the 17:20Z v2 tally and the `halt_enforced` digest field after a normal 16:50Z launch | R-5 ruling §3(2); FU-6 |
| FU-7 | LOW | 09-25 review follow-ups: registrar `--registered-at` ISO validation; ingest `results_by_cls` collapses duplicate data_types; definitions-failing instance reselected every run; salvage `NotImplementedError` retried every run (7f353f94 mark_price, 44×/12h on 09-26 — pre-S3a); T7 name DEAD vs THREATENED; ingest R4 (03–09Z boot misses day-D definitions); `_select_replay_capture_instruments` `inspect.signature` dispatch | 09-25 reviews |
| HUNT-1 | CRIT/GATED | Requirement stands (operator, 9ddcb8b); nothing built until a re-open trigger fires. Never treat as moot | `RULING_HUNT-1_all_hours_hunting_2026-09-26.md` |
| AUD-11 | BLOCKED | §7 step 5 captured-tape proof: backtest OOM at 6G — rerun with a higher cap in a quiet window | `POINT_IN_TIME_CLASSIFICATION_2026-09-21.md:134` |
| AUD-06b | BLOCKED | Needs an AUD-18 CONFIRMED edge + newly registered family | AUD-06b |

**Closed 09-26:** WP-D1, R-7-IMPL build, AUD-07 eps_k build, OPS-1, FU-1b (ruling → FU-1d merged 5b13f26), FU-3c (c33c720), FU-8 (060f346), SP-5/R-3 ruling (→ SP-5b), AUD-09b C2 (B26 PASS, B5 set, timer enabled; `AUD09B_C2_B26_B5_2026-09-26.md`), FU-10 (08535a9, replay unit exec-state DB env), FU-11 (da7528a, step14 test isolation), FU-1d-reopen (S1 508c218 shared station-day exit cap pinned; S2 472bd22 defense-in-depth `unmappable_exit_order_reason` NO-leg gate; S3 `no_leg_mark_fidelity.py` + `NO_LEG_MARK_FIDELITY_2026-09-26.md` — n=9, NO=3, n(NO exit fills)=0, ruling's 2nd re-open trigger NOT EVALUABLE).

**Order:** T5′ → S3b → deploy + drop-in removal → AUD-07 (seg 0927a) → AUD-10b doc → FU-3d/FU-9 → SP-5b/FU-8b → LOW.
Watch: 16:50Z node spawn (ADM-1 pending-fills Σq, SP-3r durable-fill index, R-7 lag, FU-8 latch), 16:52Z discovery pull, 17:20Z tallies, 17:40Z ROI report.

**KILL clock / live n (09-25):** champion (v4) counter 10 covered-listed station-days (09-20..09-25);
v4 tally n=3 (1 win), under one completed look. Exec store 9 fills (newest 09-22). A1 halt SET 09-24.

**Parked (re-open trigger: a v3 verdict, or fills at rate).** Kalshi sibling (`wip/kalshi-s4-registry`,
`kalshi_crh_v1.json` DRAFT, S11 operator-only); LADDER_EV stage 2 (stage-1 modules stay);
whole-tape replay regen; G-16/G-17 (calendar; NO-GO stops the programme);
PREREG v2 residue; EXEC SPINE R-7 residue; blind-risk T-9/T-6/`max_simultaneous_positions`.
Debt carried without a slot: CF-1, CF-2 (no consumer), CF-4, CF-5b, CF-6, CF-7, CF-8, CF-11
(`ruff format --check` 268 files incl. 64 under src/), CF-12 (mypy 433/41, all tests+scripts;
ruff 24 incl. `persistence/family_manifest.py:42`), CF-13, CF-14b, PF-1, BL-10, GL-4P.

---

## Pointers

Audit backlog 09-21 (AUD-01..19; open/partial items listed in BACKLOG above): `docs/plans/backlog/AUDIT_2026-09-21/README.md` · Audits `docs/evidence/READINESS_AUDIT_2026-09-13.md` (delta), `READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
