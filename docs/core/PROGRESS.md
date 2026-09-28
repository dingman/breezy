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

## BACKLOG — verified open set (re-synced 2026-09-28 18:00Z; every item dispositioned by `docs/evidence/RULING_backlog_resolution_2026-09-28.md`)

**Binding on EVERY item.** Never set `allow_short=True`; never weaken `BacktestOrderGuard` or any
safety, settlement, contract or NO-SEND firewall test (widen exact sets by one reviewed row, L-12);
never touch live-trading enablement; never invent an operator-reserved value; PREREG semantics change
only via a ruling under `docs/evidence/`. L-1 null-hypothesis verdict per increment. Durable processes
via `systemd-run --user` (L-26); worktree commands need `PYTHONPATH=<wt>/src`; never `uv`/`pip` from a
worktree (shared venv); never `git stash`. Full gate after EVERY merge. AUD plans: `docs/plans/backlog/AUDIT_2026-09-21/`.

**Revival path (RA-13):** R3 only, as an evidence-gated watch (EDGE-4 ≥300 post-freeze CONFIRM station-days + `census_provenance:`); R2 physically absent, R4 unestimated. Programme KILL backstop 2027-01-25; Kalshi K-2 is the post-KILL successor.

### BUILD (plan → peer review → TDD → gate → merge)
| ID | Sev | Open work (exact) | Source |
|---|---|---|---|
| ING-2-AMEND2 | HIGH | 09-28 09:45Z removal check FAILED (chunks=324, peak 6G, 610 s, deferred_instances=45); TEMPORARY ingest drop-in stays. Diagnose + bound the path that still defers | ruling §2 |
| BL-10 | HIGH | Send-boundary fingerprint hashes caller-chosen bytes (`submit_chain.py:248-263`); fingerprint method+path+serialized body; security review | ruling §2 |
| FAILURE-KIND-DURABLE | MED | Persist last failure kind with the durable ambiguous intent; restart keeps it | `FAILURE-KIND-PERSIST_plan_r2` |
| RA-9f-A | MED | Zero-look `UNDERPOWERED_NOT_REGISTERED` registrar for `H-OFFWINDOW-T4-2026-09`; do NOT flip `HORIZON_TOLLING_LANDED` | `RULING_RA-9…:108,121-138` |
| SP-5b | MED | Build now (prospective trigger) with both architect fixes | `NIGHT_2026-09-26/SP-5b_plan_r1` |
| HALT-FSM | LOW | Halted strategy emits `InvalidStateTrigger STOPPED->START_COMPLETED` ×4/boot; stop cleanly, never arm | `continuous_strategy.py:883-914` |
| CF-5b / CF-6 / T-6 | LOW | chronic-UNREADABLE deduped alert; live-test contact from env; stale `node_config.py:11-14` summary | ruling §2 |
| CF-11 / CF-12 | LOW | `src/` format (105 files, one mechanical commit); mypy 2 collection blockers then re-measure (ruff 84) | ruling §2 |

### RUN / ANALYSE
| ID | Open work (exact) |
|---|---|
| AUD-07 | seg-0928a exit 0 but 32 cells in `20k/DEFERRED`; drain 20k in a gate-free night window; never advance to 80k while DEFERRED non-empty; then 80k → `--final` → AC7 ruling |
| AUD-10b | C12 met (09-28 15:50Z replay finished 15:58Z) but at **10G peak = the TEMPORARY cap**; explain vs the REPLAY-BIGINST claim, then Stage 0 + R3-5 byte-diff before drop-in removal |
| RECON-MIA-0913 | AUD04-FRESH proven 17:33Z (reconciliation ran): `matched=False n_exit_only=1` → `continuous_rung_hold/trial/MIA/2026-09-13`; find which side is wrong |
| R3-PROJ | Project EDGE-4 CONFIRM-day accrual vs 2027-01-25; no statistic on post-09-25 tape |

### WATCH / GATED (no build owed; re-open only on the named trigger)
- **A1 floor (operator act):** EDGE-2-LIVE, EDGE-2-LAG, R-7-IMPL (first create-path `R7_POSITION_REPORTING_LAG`).
- **Evidence floor:** AUD-06b (CONFIRMED unit-qty edge + new family), CF-13 (live CCA/CCB), CF-14b (1-of-N stage-3 failure).
- **Trigger watches:** EDGE-2-MULTIPAGE step 2 (`traversed N pages` or ≥80 activities); HUNT-1 (`RULING_HUNT-1…:34-38`); AUD-02 A0 close ≥09-30; PATH-B-SOURCE-GATE + AUD-12/RA-3 (dormant, flip only by own ruling); THIN-BOOK-REFUSAL = fill-rate evidence only; CF-2/CF-7 attach to any METAR station-selection plan; RA-11a on R2/R3/R4.
- **Rules:** T-9 = per-family PREREG exit policy, no blind flatten; CF-4 accepted.

**Closed 09-28 by ruling:** EDGE-2-REFACTOR, `max_simultaneous_positions` (dbd91d9), FU-8b/NOTIFIER (live), ING-2 residual alert (exit 4 → OnFailure), whole-tape regen, G-16/G-17, PREREG v2 residue, CF-1, CF-8, PF-1, GL-4P, AUD04-FRESH, EDGE-6, TRADE-ROW-DRIFT, SUP-ADOPT-LOG-GLOB (AUD-12a closed by its 09-27 ruling; LADDER_EV stage 2 PARKED). AUD-18 stays the R3 evidence producer (only (b) closed). PROBE-CLASSIFIER-DRIFT rides MULTIPAGE step 2.

**Host 09-28:** reboot 15:21Z killed node + 15:20Z study; node respawned 16:50:22Z (permit ttl 10 h); A1 halt SET (`source=legacy_attributed`); tape advancing.

---

## Pointers

Audit backlog 09-21 (AUD-01..19; open/partial items listed in BACKLOG above): `docs/plans/backlog/AUDIT_2026-09-21/README.md` · Audits `docs/evidence/READINESS_AUDIT_2026-09-13.md` (delta), `READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
