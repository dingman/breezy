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
| EDGE-DEPLOY | HIGH | EDGE-2C (9c3f01b) + EDGE-1 (c32b53b) merged, gate 13565/0; node code, live on the next 16:50Z respawn. Proof in node log FILE: `event=fee_drift_probe outcome=AGREE` (θ registered 0.0695) and no resolver crash on a NO-leg intent | `EDGE_2026-09-27/README.md` |
| EDGE-2 | HIGH | ALL SLICES MERGED (A aeffea6, B b736ba4, D 1a3f23c; E dropped, Step 0 ZERO_FILL_BENIGN); gate 13809/0. Live at the 16:50Z respawn. Proof: node log `resolver: zero-fill corroboration=activities_v1 min_age_s=120 legs=yes,no`. Open: EDGE-2-LIVE (first post-re-arm AMBIGUOUS), EDGE-2-LAG, EDGE-2-MULTIPAGE, EDGE-2-REFACTOR | `AMBIGUOUS_ORDER_2026-09-23_MIA/README.md` |
| EDGE-3 | MED | MERGED 4b87de5 (gate 13773/0); live legacy halt sha256 5a82b401… = fixture. Supervisor restarted 08:55Z on it; node code live at the 16:50Z respawn. Proof: node boot log reads v4 HALTED via legacy attribution, and the 17:05Z self-check reports `continuous_family_halt_source` | `EDGE-3…r2` |
| EDGE-6 | MED | 6b LIVE 5947e5f (07:31Z no-op run 45 s vs p50 399 s). 6d LIVE dd2e3e8 (09-27 recorder discovery 09:00:12 → 09:15:13Z). 6c-R RETIRED: slice merged 833bada, host C3 done 09-27 (units+drop-in removed, no K1 timer, DropInPaths empty); C6 gate batch7 13850/0 — DONE. 6f MERGED fc90947 | `EDGE-6…r2` |
| EDGE-5 | CRIT | RA-2/RA-3/RA-8b/RA-9c/RA-9e merged (inert); RA-5a VERIFIED-ISOLATED. RA-9 UNDERPOWERED_NOT_REGISTERED (5b1e3fb). **RA-13 PARTIAL (79923e5): trigger-4 path KILLED (RA-9b/RA-10/RA-9c2 CLOSED); programme KILL backstop 2027-01-25 unless R2 sub-degree obs / R3 EDGE-4 revival (+§6.6 conjunction, B-1) / R4 new powered estimand; RA-11a PARKED.** K-1 memo DONE f991051 (17 candidate new stations, 0 admissible today, 11 triage prerequisites). Open: RA-13-FW (AUD-05/AUD-07 firewall check); RA-9d (needs schema v3 horizon field); RA-2b + Path A record; RA-8c | `RULING_RA-13_programme_kill_2026-09-27.md` |
| AUD-12 | HIGH | 12a RULED: retain 0.01 as a conservative qty-1 allowance (93dc12f). 12b = EDGE-1, live at respawn. AUD-12 lands only when the RA-3 flag is flipped by its own ruling | `RULING_AUD-12a_slippage_allowance_2026-09-27.md` |
| ING-2 | HIGH | S3a+S3b merged and LIVE (S3b 0974667, chunked EXTEND). Owed: observe the first EXTEND-path ingest run after the 09-27 09:00Z rotation (journal `ingested …` not all `skipped-already-converted`); if its peak ≪ 12G, remove `zz-memory-containment-TEMPORARY.conf` + daemon-reload. 19:15Z run (3.4G) converted nothing — not evidence. Residual: deferred units have no alert | `ING-2_S3_plan_r2_2026-09-26.md` |
| ING-2-AMEND | HIGH | 09-27 09:45Z post-rotation conversion peaked at rss 7374 MB / 773 s (FAILED the removal check). **ING-2-RSS FIXED + LIVE**: guarded identifier-filtered EXTEND dedupe for tick types (d37b6e6; behavioural RED ΔRSS 62664 KiB vs 0) + stdout `extend_dedupe:` line (0607b7f; seen in the journal at 11:45Z). **Drop-in removal criterion:** first post-rotation run (~09-28 09:45Z) whose `extend_dedupe:` line shows chunks>0 with cgroup memory peak ≤2G, elapsed ≤600 s and deferred_instances=0 → remove `zz-memory-containment-TEMPORARY.conf` + daemon-reload. Residual: sibling-EXTEND same-key race (covered by A8) | `ing2rss` plan r2 (scratchpad) |
| AUD-07 | HIGH | seg-0927a INCOMPLETE (exit 3: cal_b cell 47 deferred at cutoff; host contended by test gates). RESUME armed `breezy-aud07-m1c-seg-0928a` 09-28 02:10Z (cell-resumable). **No full test gates 02:10–08:40Z.** Then CAL-c → cal_check → 20k → 80k → `--final` → AC7 ruling → base §7 steps 7, 7b, 8 | `RULING_aud07_m1c_eps_k_decision_rule_2026-09-26.md` |
| AUD-02 | MED | WP-D1 live; 09-26 16:52Z timer run failed pre-fix (`-m` fix 2e109ec merged later, unit is a symlink — 09-27 run is the first real check); 17:29Z rerun OK. A0 fee-evidence earliest close 09-30; DoD 10 coordinator block / Amendment C pointer | completion plan §2, §5 |
| AUD-05 | MED | §7 step 8: three consecutive 17:20Z v4 tally runs — 2 so far (09-25, 09-26); 3rd = 09-27 17:20Z | AUD-05 §7 |
| AUD-10b | MED | Evidence doc `PROMOTION_PROPOSAL_MECHANISM_2026-09-26.md`: 19/20 PASS (C7 closed 55781d0). Only C12 open: judge idempotency after the 09-27 15:50Z unattended replay (same hash only if inputs unchanged — else record why) | AUD-10 §8 |
| AUD-18 | MED | (b) = RA-2 MERGED d10272b (schema v2; the 3 v1 lines byte-identical; binding predicate False for every live record) | AUD-18 plan amendment |
| FU-8b-DEPLOY | LOW | Merged 150c10c; live on next node respawn (never kill a live node to deploy). Proof: node log FILE shows `refusal re-poll timer armed name=breezy-refusal-repoll interval_s=60`, then `refusal re-poll alive … ticks=60` hourly | FU-8b plan r2 |
| R-7-IMPL | LOW | Confirm the first `R7_POSITION_REPORTING_LAG` line after a create-path fill — NOT evaluable while the A1 halt is set (no fills possible) | `RULING_R-7_position_reporting_lag_2026-09-26.md` |
| SP-5b | LOW/DEFERRED | Coordinator ruling (plan doc addendum): build before the next champion/family registration, with the two trading-bot-architect fixes (exclude `gs_boundary_*.json` from AC-11; restart-race test) | `NIGHT_2026-09-26/SP-5b_plan_r1_2026-09-26.md` |
| HUNT-1 | CRIT/GATED | Requirement stands (operator, 9ddcb8b); nothing built until a re-open trigger fires. Never treat as moot | `RULING_HUNT-1_all_hours_hunting_2026-09-26.md` |
| AUD-06b | BLOCKED | Needs an AUD-18 CONFIRMED edge + newly registered family | AUD-06b |
| FOLLOW-UPS 09-27 | LOW | EDGE-2-MULTIPAGE; THIN-BOOK-REFUSAL (winning-rung level-0 median 0.58 < qty 1); RA-8b str override raises TypeError not ValueError; 7 gate tests hardcode `REPO_ROOT/.venv` (worktrees need a symlink); study-failed alert is cause-agnostic (exit 4 ≡ 2/3); SUP-ADOPT-PERMIT (supervisor restart after the node's permit expiry fires a false CRITICAL permit_absent — adoption must re-parse the boot permit line; 09-27 08:55Z); RA-9c hard gate (no look-taking v2 registration before stratum-scoped scoring); EDGE-2-REFACTOR (`_resolve_ambiguous_intents` ~530 lines); `exit_control_precondition` halt-key ValueError outside try; digest docstring drift | this session |


**Order (next session, re-synced 09-27 ~04:30Z):**
1. Wave 1 merged 09-27 07:45Z. Remaining: EDGE-2 A/B/D, EDGE-3, EDGE-6f + K1 slice, RA-2; then RA-5a/RA-6/RA-11a.
2. Keep the 09-27 watch: 09:00Z rotation + ING-2-AMEND, 09:20Z digest, 15:50Z replay/AUD-10b C12, 16:50Z node/FU-8b, 16:52Z discovery (6a proof), 17:20Z AUD-05 #3.
3. SP-5b at its trigger.
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
