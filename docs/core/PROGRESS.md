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
- **NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER LIVE MEASUREMENT** (`pm_us_crh_cont`, PREREG v3 BINDING, d0 2026-09-12; `pm_us_crh_v2` still REGISTERED). Demonstrated edge NONE; admissible n = 0 after 10 live days; 10 orders, 9 fills as of 09-24 (9 durable exec-fill-store records, exact match against real-event log lines net of inferred/relaunch noise; order 1, 09-05, has no `OrderSubmitted` line in any of its 20 sessions — open escalation, AUD-13). Multi-position ruling 09-14 (R-10) lifts the one-per-station bound; MP-A merged b5a7c04.
- **Readiness audit 2026-09-12** (`docs/evidence/READINESS_AUDIT_2026-09-12.md`): the KILL-clock counter read 0/15 for 09-05..09-11 BY MECHANISM (any-overlap rule + feed-wide gap fan-out; L-38), not by outage; the create-path accept-fill branch has never fired live; v3 has never been fill-replayed; alerts reach nobody.

---

## BACKLOG — verified open set (re-synced 2026-09-25 19:40Z against merges, evidence and host)

**Binding on EVERY item.** Never set `allow_short=True`; never weaken `BacktestOrderGuard` or any
safety, settlement, contract or NO-SEND firewall test (widen exact sets by one reviewed row, L-12);
never touch live-trading enablement; never invent an operator-reserved value; PREREG semantics change
only via a ruling under `docs/evidence/`. L-1 null-hypothesis verdict per increment. Durable processes
via `systemd-run --user` (L-26); worktree commands need `PYTHONPATH=<wt>/src`. Full gate after EVERY
merge. AUD plans: `docs/plans/backlog/AUDIT_2026-09-21/` (authoritative per item).

| ID | Sev | Open work (exact) | Source |
|---|---|---|---|
| ING-2 | **CRIT** | Quote-tape ingest fails EVERY run since 09-24 20:00Z (20×, unit failed now): `MemoryHigh=4G` < backlog working set → thrash + 30-min kill (L-49); the node resolves instruments from the converted catalog, so the next 16:50Z launch finds 0. Now: one-off drain (`systemd-run`, MemoryHigh 10G, pause+restore both ingest timers) before 16:50Z. Durable: bounded per-run memory / instruments-before-depths (`quote_tape_ingest_cli.py`) + unit sizing | L-49; 09-24 drain |
| AUD-09b | HIGH | Merge `backlog/aud-09b-b26-memory-2026-09-25` + `backlog/aud-09b-replay-bound-2026-09-25` (worktrees exist); B26 ruling (cgroup peak 11 GiB FAIL vs RSS 2.49 GB PASS); `enable breezy-replay-daily.timer` (failed "unit to trigger vanished"); ratchet B5 at 2× | AUD-09 amendment §7, §10.9 |
| AUD-07 | HIGH | M1c CAL-a/b/c (transient `breezy-aud07-m1c-seg-0926a` 09-26 02:10Z) → census/eps_pin/cal_check → 20k sweep (49 cells) → 80k → `--final` → `RULING_aud07_mixed_side_ldobf_<date>.md` (AC7); then base §7 steps 7, 7b, 8; branch-I tests 10–16 only if M2 = I | AUD-07 Exec-Rev2 §4-6 |
| AUD-18 | HIGH | Link+enable `breezy-hypothesis-triage.{service,timer}` (absent on host); §7 step 9 first watched run; ledger has no stratum/draw binding → every record MISSING_STRATUM_BINDING (`hypothesis_ledger.py:234`, triage `:484`) — new schema_version + binding | AUD-18; ae56ab8 |
| AUD-02 | MED | WP-D1 `discovery_set_equality.py` + note; A0 needs ≥5 consecutive fee-evidence days (1 so far); coordinator block / Amendment C pointer (DoD 10) | completion plan §2, §5 |
| AUD-05 | MED | §7 step 8: observe three consecutive 17:20Z v4 tally runs (1 so far) | AUD-05 §7 |
| AUD-10b | MED | Evidence doc `PROMOTION_PROPOSAL_MECHANISM_<date>.md` (C1–C20); unattended runs need the replay timer | AUD-10 §8 |
| TALLY-V2 | MED | `breezy-family-tally@pm_us_crh_v2` fails (structural-pin-guard `NO_NODE`, 09-25 17:20Z): fix or retire per the tally-scope ruling | host |
| HUNT-1 | CRIT/S | Strategy-lead ruling: close as moot (daf81a1: no hour clears zero) or name the all-hours build. NOT covered by AUD-01 (its §5/§12 exclude it) | `CONTINUOUS_HUNTING_GAP_2026-09-20.md` |
| SP-5/R-3 | S | Coverage diagnostic (blips vs outages vs dead-recorder rows) + §9 tolerance ruling (options i–iv, v1 §7 re-registration); unowned by any AUD item | `COVERAGE_KILL_CLOCK_2026-09-12.md` |
| R-7 | S | `PositionReportingLag`: keep+wire on the create path or delete (`position_reporting_lag.py:8`, zero producers) | P7 §8 |
| SP-3r | LOW | `_has_durable_fill_record` still a stub (`exec/client.py:1672`); order-1 (09-05) no-`OrderSubmitted` escalation | AUD-13 plan :146 |
| SP-7r | LOW | Doc truths H-2..H-6 (`deploy/systemd/README.md:3` "PREPARED, NOT ACTIVATED", `native_reuse_audit` :118/:131, GO_LIVE_BLOCKERS → gl1_gl4) | `HYGIENE_FREE_FIXES_2026-09-12.md` |
| ADM-1 | LOW | Σq admission skips IN_FLIGHT legs (`trial_day_latch.py:1546`): count them, or RED-prove the intent latch serializes | diagnosis §4 |
| FU-1 | MED | Position monitor `KeyError` on `^no` ids (`monitor_wiring.py:113,116`; `_facts` is YES-only) — fall back to the YES sibling (as `continuous_strategy.py:1142`) | 09-22 MDW fill log |
| FU-2 | MED | NO-side `no_take_shadow`/take lines omit the observation reading behind `p_miss_lower` (`continuous_strategy.py:2605`) — log value + ts | 09-22 audit |
| FU-3 | MED | ROI: attribute $40.00 + $0.99 UNEXPLAINED_CAPITAL_FLOW (09-13/09-14; `PRIVATE_portfolio_roi_2026-09-25.md:38`); add `_run`-level test for `DuplicateScoredTrialEconomicsMismatchError` | AUD-04 |
| FU-4 | LOW | Exit-window study: catch `OSError` on cached-file read per station; add N/M-stations-loaded line | 09-24 review |
| FU-5 | LOW | Resolver: overlapping connect passes (`client.py:1605`/`:1632`) log a false "could not be loaded" — serialize or say "load in flight" | node log 09-24 20:15Z |
| FU-6 | LOW | `halt_enforced: yes/no` digest field from the halt store | `AUD-03-FOLLOWUP-a1-digest-line.md` |
| AUD-11 | BLOCKED | §7 step 5 captured-tape proof: backtest OOM at 6G on base and branch — rerun with a higher cap in a quiet window | `POINT_IN_TIME_CLASSIFICATION_2026-09-21.md:134` |
| AUD-06b | BLOCKED | Needs an AUD-18 CONFIRMED edge + newly registered family (both step-8 horizons UNDERPOWERED) | AUD-06b |

**Order:** ING-2 (before 16:50Z) → AUD-09b → TALLY-V2 → AUD-18 deploy → AUD-07 (on its M1c clock) →
AUD-02/05/10b → FU-1..FU-3 → rulings HUNT-1, SP-5/R-3, R-7 (coordinator + peer loop) → LOW items.

**KILL clock / live n (09-25):** champion (v4) counter 10 covered-listed station-days (09-20..09-25);
v4 tally n=3 (1 win), under one completed look. Exec store 9 fills (newest 09-22). A1 halt SET 09-24.

**Closed since 09-21 (commit = record):** AUD-01a/b, 02b, 03, 04, 06a (R-11 INDETERMINATE), 08a/b,
09a, 10a, 12a/b, 13a-d (R-1, R-2), 14a/b, 15, 16, 17, 19a-c; R-5, R-12 rulings; WP-R1 fix e83fc5c;
live-store pins 7a39577; stuck intent CP05MNWMAWP6 retired 09-24. EXIT-1→AUD-07, MP-B→AUD-06b, SP-4→AUD-09.

**Closed 2026-09-20:** forecast-edge hunt TERMINAL (`RULING_forecast_edge_programme_closes_2026-09-20.md`); `pm_us_crh_rest_v5` folded CLOSED_NOT_REGISTERED; alert delivery shipped (`f97c26f`). Next phase: `docs/plans/POST_FORECAST_PHASE_2026-09-20.md`.

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
