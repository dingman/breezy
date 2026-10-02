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
| RA-9f-A | 16f403d | DONE live 18:25Z: ledger line 4 `H-OFFWINDOW-T4-2026-09 UNDERPOWERED_NOT_REGISTERED` freeze 16f403d; duplicate refused, bytes unchanged. Backup in session scratchpad |
| RECON-MIA-0913 | 97c4325 | 09-29 15:20Z exit study: per-trial reconciliation `matched=True` with `n_fee_unverified_excluded=1` |
| AUD-07 gate | 97c4325 | `--stage 80k` refused while `20k/DEFERRED` non-empty (repo copy; the pinned a40d433 copy drives the drain) |
| R3V-a | 8a2f8f2 | 09-29 10:30Z backfill `breezy-replay-backfill-0929` (40 targets, 3 h) then 15:50Z daily (6): `BATCH_SUMMARY` lines, rows appended, ends before 16:35Z |
| R3V-b | (gating) | 10-01: run `scripts/analysis/r3_viability.py`; if Wilson upper (z=1.96) < f_req 0.625 ⇒ RULING R3 not viable ⇒ programme KILL decision forward + K-2 planning |
| CF-11 | merged, gate green | `src/` formatted (104 files); `exec/client.py` left unformatted (formatting surfaces 6 noqa-sensitive findings) |
| CF-12 W0+W1 | 1792e8c | Gate green 09-29 01:55Z, pushed. In-gate ratchet `tests/unit/test_mypy_ratchet.py`; runtime+strategy now CLEAN (16 errors, triage all-unreachable); CI mypy advisory. Plan `docs/plans/CF-12_MYPY_BURNDOWN_Rev2_2026-09-29.md` |

### BUILD
| ID | Sev | Open work (exact) | Source |
|---|---|---|---|
| CF-12-STAGE | LOW | `backlog/stage-cf12-w2-2026-09-29` @4b0b4f6 (Wave 2: 185 unused ignores removed, Codex, AST-verified; ratchet rejects mypy exit 2) — gate armed `breezy-gate-stage-cf12` 08:50Z (waits for AUD-07) → log `~/.cache/breezy-gate/stage-cf12.log`; EXIT=0 ⇒ ff-merge + push | CF-12 |
| CF-12-W3 | LOW | 314 `import-not-found` (bare sibling-script imports): config-only `mypy_path` fix NOT viable (exit 2, duplicate module `x` vs `scripts.analysis.x`) → design pass (normalize qualified imports or invocation) | CF-12 trial 09-29 |
| DEFER-STREAK-LOAD | LOW | `ingest_deferral_streak.load_state` (:190-195) accepts non-str `first_deferred_utc` from disk unchecked | CF-12 triage 09-29 |

### RUN / ANALYSE
| ID | Open work (exact) |
|---|---|
| AUD-07 | 20k drain: `breezy-aud07-m1c-seg-0929a` armed 09-29 02:10Z (8 cells/night ⇒ ~4 nights; rename `20k/DEFERRED` before each run); then 80k → `--final` → AC7 ruling |
| AUD-10b | C12 met at 10G peak; cause = conversion of 16 cache-miss instances (`ANALYSIS_replay_10g_2026-09-28.md`); Stage 0 + R3-5 before drop-in removal, run after ING-2-AMEND2 proves out |
| R3 blockers (only if R3V-b says viable) | (1) MECHANISM_ONLY validity = AUD-11+AUD-12 landing; (2) `UNDERPOWERED_NOT_REGISTERED` not in `_ACTIVE_STATUSES`; (3) no post-freeze filter in `_completed_on_whole_days`. Real f so far 2/5 (Wilson .12–.77); f_req 0.625 |

### REFACTOR Rev 2.1 (executed 2026-10-02; log `docs/plans/refactor_2026-10-01/EXECUTION_LOG_2026-10-02.md`)
| ID | Open work (exact) |
|---|---|
| R3.1 / R3.2a / R3.2b / R3.4 | HELD (plan §3.0): start only after the FQ live proof plus one clean trading day. CT-1/2/4/7/8/12/13 are merged and strengthened (CT-12 drives the exec-client `submit_veto` and `try_submit`) |
| NWS-INGEST-RESTART | Target 2026-10-03 morning (after FQ d0 closes). R1.5b (health I/O injected into `nws_actor`; debt row paid, 4 → 2 with R1.6) is merged at d6914fca but NOT yet loaded. nws-ingest has been running since 2026-09-28 15:21Z, so a restart deploys 37 files of ingest/persistence changes. Deferred past FQ d0. After the restart: two poll cycles with no "health emission failed" line, `breezy-check-alerts`, and the boot egress-status line |
| R3.6 | After NWS-INGEST-RESTART is clean: C3 of `R1_5b` design (move `_alert_conditions`/`_emit_health` to `ingest/nws_health.py`; `ts_init` nudge stays) |
| EMIT-HEALTH-CRITICAL | MERGED 806a8942, loads with NWS-INGEST-RESTART: after 3 consecutive `_emit_health` failures, one CRITICAL `health_emission_failing` reaches the composed sink off-loop (bounded), plus the log marker `NWS_HEALTH_EMISSION_FAILING`; renotify 24 h. Post-restart check: grep the marker is absent |

### Comment backlog (R0.1)
- Queue live-file comment/docstring fixes for the next real edit of each file: `websocket.py:61-63` wrong `retry.py` lines; `operator_controls.py:267` non-existent `RiskLimits` and `:271-275` stale ledger persistence wording; `signing.py` / `write_transport.py:6` stale cage docstrings; `exec/client.py:660` cites `risk.py:139` but the flag is at `:224`.

### WATCH / GATED (no build owed; re-open only on the named trigger)
- **A1 floor (operator act):** EDGE-2-LIVE, EDGE-2-LAG, R-7-IMPL (first create-path `R7_POSITION_REPORTING_LAG`).
- **Evidence floor:** AUD-06b (CONFIRMED unit-qty edge + new family), CF-13 (live CCA/CCB), CF-14b (1-of-N stage-3 failure).
- **Trigger watches:** EDGE-2-MULTIPAGE step 2 (`traversed N pages` or ≥80 activities); HUNT-1 (`RULING_HUNT-1…:34-38`); AUD-02 A0 close ≥09-30; PATH-B-SOURCE-GATE + AUD-12/RA-3 (dormant, flip only by own ruling); THIN-BOOK-REFUSAL = fill-rate evidence only; CF-2/CF-7 attach to any METAR station-selection plan; RA-11a on R2/R3/R4; SP-5b = step 0 of any R3 re-plan (before registration).
- **Rules:** HALT-FSM = accepted cosmetic (Nautilus swallows it; fail-safe; whitelist `InvalidStateTrigger STOPPED->START_COMPLETED` in greps); T-9 = per-family PREREG exit policy, no blind flatten; CF-4 accepted.

**Closed 09-28 by ruling:** EDGE-2-REFACTOR, `max_simultaneous_positions` (dbd91d9), FU-8b/NOTIFIER (live), ING-2 residual alert (exit 4 → OnFailure), whole-tape regen, G-16/G-17, PREREG v2 residue, CF-1, CF-8, PF-1, GL-4P, AUD04-FRESH, EDGE-6, TRADE-ROW-DRIFT, SUP-ADOPT-LOG-GLOB (AUD-12a closed by its 09-27 ruling; LADDER_EV stage 2 PARKED). AUD-18 stays the R3 evidence producer (only (b) closed). PROBE-CLASSIFIER-DRIFT rides MULTIPAGE step 2.

**Host 09-28:** reboot 15:21Z killed node + 15:20Z study; node respawned 16:50:22Z (permit ttl 10 h); A1 halt SET (`source=legacy_attributed`); tape advancing.

**FQ go-live:** `pm_us_crh_fq_v1.json` REGISTERED (S8) with `live_orders_ruling=RULING_operator_fq_live_real_orders_2026-10-01`, density artefact sha-pinned to the committed byte copy, boundary artefact pinned to the `not_applicable_boundary.json` sentinel; S9 activation merged 60290e9d and the supervisor sends `pm_us_crh_fq_v1` for d0 2026-10-02 (`docs/plans/FQ_GO_LIVE_PLAN_2026-10-01.md` §4/§5).

---

## Pointers

Audit backlog 09-21 (AUD-01..19; open/partial items listed in BACKLOG above): `docs/plans/backlog/AUDIT_2026-09-21/README.md` · Audits `docs/evidence/READINESS_AUDIT_2026-09-13.md` (delta), `READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
