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
| ING-2 | HIGH | S3a+S3b merged and LIVE (S3b 0974667, chunked EXTEND). Owed: observe the first EXTEND-path ingest run after the 09-27 09:00Z rotation (journal `ingested …` not all `skipped-already-converted`); if its peak ≪ 12G, remove `zz-memory-containment-TEMPORARY.conf` + daemon-reload. 19:15Z run (3.4G) converted nothing — not evidence. Residual: deferred units have no alert | `ING-2_S3_plan_r2_2026-09-26.md` |
| AUD-07 | HIGH | `breezy-aud07-m1c-seg-0927a` armed 09-27 02:10–08:40Z: CAL rerun → cal_check → 20k (F_GATE_MAX=1.0, PR-3) → 80k → `--final` → AC7 ruling; then base §7 steps 7, 7b, 8 | `RULING_aud07_m1c_eps_k_decision_rule_2026-09-26.md` |
| AUD-02 | MED | WP-D1 live; 09-26 16:52Z timer run failed pre-fix (`-m` fix 2e109ec merged later, unit is a symlink — 09-27 run is the first real check); 17:29Z rerun OK. A0 fee-evidence earliest close 09-30; DoD 10 coordinator block / Amendment C pointer | completion plan §2, §5 |
| AUD-05 | MED | §7 step 8: three consecutive 17:20Z v4 tally runs — 2 so far (09-25, 09-26); 3rd = 09-27 17:20Z | AUD-05 §7 |
| AUD-10b | MED | Evidence doc `PROMOTION_PROPOSAL_MECHANISM_2026-09-26.md`: 19/20 PASS (C7 closed 55781d0). Only C12 open: judge idempotency after the 09-27 15:50Z unattended replay (same hash only if inputs unchanged — else record why) | AUD-10 §8 |
| AUD-18 | MED | (b) schema-v2 stratum/draw binding BLOCKED until a look-taking registration or REPLAY_VALIDITY flip | AUD-18 plan amendment |
| FU-8b-DEPLOY | LOW | Merged 150c10c; live on next node respawn (never kill a live node to deploy). Proof: node log FILE shows `refusal re-poll timer armed name=breezy-refusal-repoll interval_s=60`, then `refusal re-poll alive … ticks=60` hourly | FU-8b plan r2 |
| DIGEST | LOW | FU-12 merged 1bae25a: digest now writes a halt-state artefact with no tape. Verify 09-27 09:20Z: `derived/decision_funnel/decision_funnel_2026-09-26.json` exists with `halt_enforced` and `decision_tape_present:false` (A1 halt SET ⇒ no offer tape since 09-23 is expected) | FU-12 |
| R-7-IMPL | LOW | Confirm the first `R7_POSITION_REPORTING_LAG` line after a create-path fill — NOT evaluable while the A1 halt is set (no fills possible) | `RULING_R-7_position_reporting_lag_2026-09-26.md` |
| SP-5b | LOW/DEFERRED | Coordinator ruling (plan doc addendum): build before the next champion/family registration, with the two trading-bot-architect fixes (exclude `gs_boundary_*.json` from AC-11; restart-race test) | `NIGHT_2026-09-26/SP-5b_plan_r1_2026-09-26.md` |
| FU-17 | HIGH | Zero-instrument boot refusal (`NoTradableInstrumentsError`, exit 2) is classified non-transient by the supervisor (`relaunch_declined reason=exit cause is not transient`, supervisor.log:260) and never relaunched — one ingest stall = one lost trading day (09-04, 09-07, 09-24, 09-25 all ingest-caused per L-49). Plan + review (relaunch path) | `NIGHT_2026-09-26/FU-7b_measurement_DROP_2026-09-26.md` M3 |
| FU-7a-FOLLOWUP | LOW | Narrow `quote_tape_salvage.py:~368` `except NotImplementedError` to the deserialise call-site (today it spans all of `_salvage_one_file`) | FU-7a review |
| HUNT-1 | CRIT/GATED | Requirement stands (operator, 9ddcb8b); nothing built until a re-open trigger fires. Never treat as moot | `RULING_HUNT-1_all_hours_hunting_2026-09-26.md` |
| AUD-11 | BLOCKED | §7 step 5 captured-tape proof: backtest OOM at 6G — rerun with a higher cap in a quiet window | `POINT_IN_TIME_CLASSIFICATION_2026-09-21.md:134` |
| AUD-06b | BLOCKED | Needs an AUD-18 CONFIRMED edge + newly registered family | AUD-06b |

**Closed 09-26:** WP-D1, R-7-IMPL build, AUD-07 eps_k build, OPS-1, FU-1b (→ FU-1d 5b13f26), FU-3c (c33c720), FU-8 (060f346), SP-5/R-3 ruling (→ SP-5b), AUD-09b C2, FU-10 (08535a9), FU-11 (da7528a), FU-9 (734eec6), TALLY-V2 (17:20Z v2 OK). **Night 09-26 (all full-gated green):** T5′ (8711b22, chunk-count + white-box `peak_pending_bytes`), FU-1d-reopen (efd281e; S1 shared station-day exit cap, S2 NO-leg exit refusal at `unmappable_exit_order_reason`, S3 `NO_LEG_MARK_FIDELITY_2026-09-26.md` n(NO exit fills)=0), ING-2 S3b (0974667), FU-3d (6dbce7e; qty==1 guard at BOTH scored-store writers incl. paper replay; markdown-only fee_unverified disclosure; FU-3c erratum band p∈[~0.315,~0.685]), FU-8b (150c10c; kernel-clock re-poll + hourly heartbeat), FU-12 (1bae25a; digest halt state without tape), AUD-10b C7 (405c6dd), FU-13 (fe19b4a; PROXY_LAG requires payout capacity — 09-13 → CAPITAL_FLOW), FU-14 (9519c79; EXTEND zero-row file fails the type, exit 3), FU-15 (9e6ef7c; intent-lock errors keep errno). **Late night:** FU-7 A/B/C (6297d11 salvage-unsupported terminal marker; d6e0457 registrar ISO date; df2a74b replay shim removed; items 2, 3, 5 dropped with evidence — 0 defs-fail in 7 d), FU-13b (cb10b0b; read-only `/v1/portfolio/activities` puller `breezy-capital-flow-pull.timer` 17:30Z DEPLOYED, first run 7 records; ROI report v3-additive net reconciliation — 09-13 now `EXPLAINED_EXTERNAL_FLOW`, `settled_cumulative_passes_net=True`, raw verdict unchanged), FU-7b DROPPED with evidence (`NIGHT_2026-09-26/FU-7b_measurement_DROP_2026-09-26.md`: 0 of 53 boots in the window; supervisor cannot spawn 01:00–16:40Z, pinned `test_trade_supervisor.py:1847-1848,1902-1903,1958`; reopen triggers T1 in-window 'resolved 0' log, T2 schedule change, T3 pre-hour-10 trading ruling, T4 today_by_station change; preferred design if reopened = (i′) per-file markers for closed live definitions files), FU-16 (bc07a4a; test harness never stopped/disposed ~228 strategies — full gate now green at soft NOFILE 1024).

**Order:** 09-27 watch (02:10Z AUD-07 seg → 09:00Z rotation + ING-2 drop-in → 09:20Z digest → 15:50Z replay/AUD-10b C12 → 16:50Z node (FU-8b arm line) → 16:52Z discovery pull → 17:20Z AUD-05 #3) → FU-7b plan → FU-7a follow-up → SP-5b at trigger.
Watch: 16:50Z node spawn (permit line + tape advancing; A1 halt SET ⇒ never arms), 16:52Z discovery pull, 17:20Z tallies, 17:30Z capital-flow pull (one `CAPITAL_FLOW_PULL status=OK` line) → 17:40Z ROI report (`settled_cumulative_passes_net` expected True; raw stays False by design).

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
