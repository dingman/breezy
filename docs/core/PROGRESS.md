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
`exec/client.py:2214`, with AMBIGUOUS/no-fill spend still process-local). The three
session ceilings derive from the two caps at permit mint (`safety.py:552-608`).
Everything else is build-side.

## Standing verdicts that gate future work

- **G-02 ROI feasibility NO-GO** on the downstream programme (not the first fill). `docs/evidence/roi_feasibility_2026-08-26.md`.
- **G-01 prelim→final revision POWERED FAIL** on MDW/NYC/SFO; interior-bucket strategies dead. `docs/evidence/observation_lock_falsification_2026-08-31.md`.
- **Lock strategies DEAD (L-9); K1 DEAD at ask ≥2c.** Rev5 `pm_us_crh_fc_v1` (NBS point forecast) CLOSED 09-20 (`RULING_forecast_edge_programme_closes_2026-09-20.md`); `pm_us_crh_cont` NOT displaced. Probabilistic NBM-NBP family: plan CONVERGED 09-29 (`docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`), built S1–S4-infra + SL-9/SL-15. **PM.us confirmatory leg INFEASIBLE 09-30 → §6 node 4** (validate n_min 592, range [552, 645] > 520; `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md`). Holdout sealed; the weather-only S2 still runs at n_min; L + S4-infra carried as K-2 assets.
- **Price history is forward-only; a forecast archive is a CALIBRATION set.** Venue surface = 5 cities × daily HIGH. BL-6 (no NO-side instrument) is SUPERSEDED by the 09-14 operator ruling: NO-side hunting is a requirement (NO-1).
- **NO FAMILY HAS A PROVEN EDGE; CURRENT SENDING FAMILY IS UNDER LIVE MEASUREMENT** (`pm_us_crh_fq_v1`, S9 activation merged 60290e9d, d0 2026-10-02; `pm_us_crh_cont`/`pm_us_crh_v2` are prior registered families, not the current sender). Demonstrated edge NONE; admissible n = 0 after 10 live days; 10 orders, 9 fills as of 09-24 (9 durable exec-fill-store records, exact match against real-event log lines net of inferred/relaunch noise; order 1, 09-05, had no fill — AMBIGUOUS no-response, operator-cleared; `ORDER1_NO_ORDERSUBMITTED_2026-09-26.md`). Multi-position ruling 09-14 (R-10) lifts the one-per-station bound; MP-A merged b5a7c04.
- **Readiness audit 2026-09-12** (`docs/evidence/READINESS_AUDIT_2026-09-12.md`): the KILL-clock counter read 0/15 for 09-05..09-11 BY MECHANISM (any-overlap rule + feed-wide gap fan-out; L-38), not by outage; the create-path accept-fill branch has never fired live; v3 has never been fill-replayed; alerts reach nobody.

---

## BACKLOG — verified open set (re-synced 2026-09-28 18:00Z; every item dispositioned by `docs/evidence/RULING_backlog_resolution_2026-09-28.md`)

**Binding on EVERY item.** Never set `allow_short=True`; never weaken `BacktestOrderGuard` or any
safety, settlement, contract or NO-SEND firewall test (widen exact sets by one reviewed row, L-12);
never touch live-trading enablement; never invent an operator-reserved value; PREREG semantics change
only via a ruling under `docs/evidence/`. L-1 null-hypothesis verdict per increment. Durable processes
via `systemd-run --user` (L-26); worktree commands need `PYTHONPATH=<wt>/src`; never `uv`/`pip` from a
worktree (shared venv); never `git stash`. Full gate after EVERY merge. AUD plans: `docs/plans/backlog/AUDIT_2026-09-21/`.

**Revival path (RA-13):** R3 only; viability kill-screen R3V-b runs 10-01 (`R3-VIABILITY_plan_r2_delta`), as an evidence-gated watch (EDGE-4 ≥300 post-freeze CONFIRM station-days + `census_provenance:`); R2 physically absent, R4 unestimated. Programme KILL backstop 2027-01-25; Kalshi K-2 is the post-KILL successor.

### LIVE-PROOF owed (all merged 09-28, gate green after each merge; loads noted)
| ID | Merge | Proof owed (exact) |
|---|---|---|
| ING-2-AMEND2 | 9730f1e | 09-29 ~09:45Z post-rotation ingest: `extend_dedupe:` shows `custom_depth_truncation:<n>/0` + `flat_root=none`, deferred_instances=0, ≤600 s, cgroup `memory.peak` ≤2G (measured directly, never from RSS) → remove `zz-memory-containment-TEMPORARY.conf` + daemon-reload. `flat_root=custom_depth_truncation` WARN = native flat write happened → open structural fix |
| BL-10 | fdf28aa | Boot clean PROVEN 09-28 16:50Z (0 FATAL, permit issued ttl 10 h). Owed: first create-path order shows no permit refusal (none possible while A1 halt SET). Also fixes a real budget leak (raising `build_order_body` spent permit budget) |
| FAILURE-KIND-DURABLE | bdba573 | Next node spawn; a restart with an OPEN AMBIGUOUS intent names the durable kind (not `none`) in the stale CRITICAL |
| RECON-MIA-0913 | 97c4325 | 09-29 15:20Z exit study: per-trial reconciliation `matched=True` with `n_fee_unverified_excluded=1` |
| AUD-07 gate | 97c4325 | `--stage 80k` refused while `20k/DEFERRED` non-empty (repo copy; the pinned a40d433 copy drives the drain) |
| R3V-a | 8a2f8f2 | 09-29 10:30Z backfill `breezy-replay-backfill-0929` (40 targets, 3 h) then 15:50Z daily (6): `BATCH_SUMMARY` lines, rows appended, ends before 16:35Z |
| R3V-b | (gating) | 10-01: run `scripts/analysis/r3_viability.py`; if Wilson upper (z=1.96) < f_req 0.625 ⇒ RULING R3 not viable ⇒ programme KILL decision forward + K-2 planning |

### FQ LOSS RESPONSE (plan r3 + F1-errata-and-deltas_r3.md; E-25..E-28 filed)
FQ v1 halt FAILED 10-05 (cwd bug, 5 more fills); backstop orders-off drop-in live 01:01Z 10-06; CLI halt re-timed 16:40Z.
| Row | Status |
|---|---|
| F2 truth fetch | MERGED; units install next |
| F4 labels | build-now DONE (WP0-3,5,6,8 + plugins); promote waits AUT-6; see F4-open-items_2026-10-06.md |
| F5 prereg MC | DONE: STARVED; design frozen 072ab026 (RULING_FQ-PREREG-v2-AMENDMENT) |
| F6 bridge | waits F5 numerics (STALE_PARITY_H, n_par) |
| F7a stats move | DONE (merged) |
| F10 AUT-S | plan r2 READY; Phase 0: G2 empty -> Lane S not built; F13 is the binding lever |
| F13 US sources | READY; A0 done; C1 S1-S3 merged, S4 final gate; OPEN-7 before Phase A |
Row 7 note (FQ-R48): AUT-5a WP1-WP9 may merge (inert); WP10 stage S/L1/L2 waits F8, F6, resume bar, RC-5 (F9-B).

### AUTONOMY QUEUE (operator priority 2026-10-03; outranks every other BUILD/RUN row)
`/execute-backlog` takes the FIRST row not DONE/GATED whose Needs are DONE; never skip ahead; on finish set `DONE <sha>`. PLAN rows go to planner + peer review, not TDD. Every brief carries the area plan, `reviews/<area>-final.md` and ARCH errata. Detail: `docs/plans/backlog/AUTONOMY_2026-10-03/README.md`.
| # | ID | Work | Needs | Status |
|---|---|---|---|---|
| 3 | ING-2-AMEND2 | RUN live proof above, remove TEMPORARY drop-in | — | OPEN |
| 4 | ARCH-0 | BUILD Wave 0 core + E-7a bwrap wrapper + E-8a snapshot helper (plans: seam A r5, seam B r5; E-7d/E-7e/E-14 filed) | 1,2 | DONE 2026-10-04: seams A+B merged, V0–V21 PASS (V10 node-up 17:12Z); rulings reviews/ARCH-0-r1-merged.md |
| 5 | AUT-1a | BUILD capture offline (audit, settlement, refs) | 4 | IN PROGRESS: WP0–WP2, WP3 s1, WP5 stages 1–3 merged (d407ff3b); WP4 held for WP8; WP3 s2 waits AUT-6, WP6 AUT-4 |
| 6 | AUT-6 | BUILD drift/health, delivery proof (parallel with 5) | 4 | OPEN |
| 7 | AUT-5a | BUILD store wiring + demotion engine; owns `app/trade.py` | 4,6 | OPEN |
| 8 | AUT-1b | BUILD node DecisionRecord wiring | 5,7 | OPEN |
| 9 | AUT-2 | BUILD labels (2a then 2b) | 3,8 | OPEN |
| 10 | AUT-4 | BUILD eval (4a move, live sequential, offline) | 9 | OPEN |
| 11 | AUT-5b | BUILD policy ruling + drill clauses; PROMOTE stays off | 10 | OPEN |
| 12 | AUT-7 | BUILD 7a gate drill, 7b live drill | 11 | OPEN |
| 13 | AUT-3 | BUILD retraining; only once AUT-4 shows an edge or a new source exists | 10 | GATED |
Area closes only at an independent score of 3 after its live proof; scores now 2,1,0,2,1,2,2 (AUT-1..7).

### BUILD (`BP` = `docs/plans/backlog/BACKLOG_PLANS_2026-10-03`; build items in `BP/reviews/<ID>-r<N>-final.md`)
| ID | Sev | Open work (exact) | Source |
|---|---|---|---|
| CF-12-STAGE | LOW | READY plan `BP/CF-12-STAGE_plan_r1.md` (regenerate 185 ignores on HEAD; before W3) | CF-12 |
| CF-12-W3 | LOW | READY plan `BP/CF-12-W3_plan_r4.md`, after CF-12-STAGE | CF-12 trial 09-29 |
| DEFER-STREAK-LOAD | LOW | READY plan `BP/DEFER-STREAK-LOAD_plan_r2.md` | CF-12 triage 09-29 |

### RUN / ANALYSE
| ID | Open work (exact) |
|---|---|
| AUD-07 | 20k drain: `breezy-aud07-m1c-seg-0929a` armed 09-29 02:10Z (8 cells/night ⇒ ~4 nights; rename `20k/DEFERRED` before each run); then 80k → `--final` → AC7 ruling |
| AUD-10b | C12 met at 10G peak; cause = conversion of 16 cache-miss instances (`ANALYSIS_replay_10g_2026-09-28.md`); Stage 0 + R3-5 before drop-in removal, run after ING-2-AMEND2 proves out |
| R3 blockers (only if R3V-b says viable) | (1) MECHANISM_ONLY validity = AUD-11+AUD-12 landing; (2) `UNDERPOWERED_NOT_REGISTERED` not in `_ACTIVE_STATUSES`; (3) no post-freeze filter in `_completed_on_whole_days`. Real f so far 2/5 (Wilson .12–.77); f_req 0.625 |

### REFACTOR Rev 2.1 — COMPLETE 2026-10-02 (all steps live; log `docs/plans/refactor_2026-10-01/EXECUTION_LOG_2026-10-02.md`); open follow-ups
| ID | Open work (exact) |
|---|---|
| AMBIG-LATCH-RESUME | READY plan `BP/AMBIG-LATCH-RESUME_plan_r6.md` (two-phase merge; supersedes L-36 no-id clause) |
| SUP-RESTART-ANYTIME | READY plan `BP/SUP-RESTART-ANYTIME_plan_r4.md` |
| CT13-FLAKE (watch) | 1 failure under 4 concurrent gates; 0/100 reproduction under load, 0 misses in 500k `/proc/locks` reads. Hypothesis: a transient read returns None, so adoption fails closed. On a 2nd occurrence, add a `locks_path` fault-injection test |

### Comment backlog (R0.1)
- Queue live-file comment/docstring fixes for the next real edit of each file: `websocket.py:61-63` wrong `retry.py` lines; `operator_controls.py:267` non-existent `RiskLimits` and `:271-275` stale ledger persistence wording; `signing.py` / `write_transport.py:6` stale cage docstrings; `exec/client.py:660` cites `risk.py:139` but the flag is at `:224`.

### WATCH / GATED (no build owed; re-open only on the named trigger)
- **A1 floor (operator act):** EDGE-2-LIVE, EDGE-2-LAG, R-7-IMPL (first create-path `R7_POSITION_REPORTING_LAG`).
- **Evidence floor:** AUD-06b (CONFIRMED unit-qty edge + new family), CF-13 (live CCA/CCB), CF-14b (1-of-N stage-3 failure).
- **Trigger watches:** AMBIG-SIGN-TABLE (extend the no-id manual sign table if `SELL_SHORT` or any unobserved manual shape appears); EDGE-2-MULTIPAGE step 2 (`traversed N pages` or ≥80 activities); HUNT-1 (`RULING_HUNT-1…:34-38`); AUD-02 A0 close ≥09-30; PATH-B-SOURCE-GATE + AUD-12/RA-3 (dormant, flip only by own ruling); THIN-BOOK-REFUSAL = fill-rate evidence only; CF-2/CF-7 attach to any METAR station-selection plan; RA-11a on R2/R3/R4; SP-5b = step 0 of any R3 re-plan (before registration).
- **Rules:** HALT-FSM = accepted cosmetic (Nautilus swallows it; fail-safe; whitelist `InvalidStateTrigger STOPPED->START_COMPLETED` in greps); T-9 = per-family PREREG exit policy, no blind flatten; CF-4 accepted.


---

## Pointers

Audit backlog 09-21 (AUD-01..19; open/partial items listed in BACKLOG above): `docs/plans/backlog/AUDIT_2026-09-21/README.md` · Audits `docs/evidence/READINESS_AUDIT_2026-09-13.md` (delta), `READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
