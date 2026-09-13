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
- **Lock strategies DEAD (L-9); forecast family KILLED; K1 DEAD at ask ≥2c; candidate #2 THIN, NOT A GO.** Do not design a new family.
- **Price history is forward-only; a forecast archive is a CALIBRATION set.** Venue surface = 5 cities × daily HIGH; no NO-side instrument (BL-6).
- **NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER LIVE MEASUREMENT** (`pm_us_crh_cont`, PREREG v3 BINDING, d0 2026-09-12; `pm_us_crh_v2` still REGISTERED). Demonstrated edge NONE; admissible n = 0 after 8 live days; 2 orders, 1 fill (09-11 SFO @0.22, resolver path → residual by v3 §5).
- **Readiness audit 2026-09-12** (`docs/evidence/READINESS_AUDIT_2026-09-12.md`): the KILL-clock counter read 0/15 for 09-05..09-11 BY MECHANISM (any-overlap rule + feed-wide gap fan-out; L-38), not by outage; the create-path accept-fill branch has never fired live; v3 has never been fill-replayed; alerts reach nobody.

---

## BACKLOG — SHORTEST PATH TO A TESTABLE, RISK-CONTROLLED LIVE STATE (opened 2026-09-12)

**Binding constraints on EVERY item.** No item may: set `allow_short=True`; weaken
`BacktestOrderGuard` or any safety, settlement, or contract test; touch live-trading
enablement or the NO-SEND egress firewall; invent an operator-reserved value; or change
PREREG v3 §3/§5/§9 semantics except through a ruling artefact under `docs/evidence/`.
Every increment carries an L-1 null-hypothesis verdict citing installed Nautilus source.
Each plan below is peer-reviewed (Rev 2 dispositions inside the plan). Execute in plan
order; B = build, O = operator, S = strategy-lead ruling.

| ID | Own | Sev | Item | Plan | Size |
|---|---|---|---|---|---|
| SP-0 | B | DONE 09-12 | v3 launch state is build-side (flags are not operator controls, ruling 09-10). Decision 2026-09-12: the 16:50Z launch goes LIVE per the 09-10 operator direction and the 15:36Z freeze instruction; bound = 4 stations × 1 position × per-position cap, latch durable, ledger in-memory per process. Shadow stays a one-day reversible option (drop-in procedure, P1 §8 D-1) if SP-4's replay finds a hunt defect. | `SCOPE_STOP_AND_OPS_SERIALIZE_2026-09-12.md` §8 D-1 | — |
| SP-1 | B | **CRIT** | **No v3 tally exists** (timer runs `pm_us_crh_v2` only, `breezy-pm-crh-v2-tally.service:46`; wrapper gates structural-dead args on v2, `family-tally-v2-run.sh:73,85`) — wire a nightly `pm_us_crh_cont` producer (I5, needs R-4). Stop-doing + serialize: disable k1/offer-gate/mb timers and the 6-hourly ingest timer; `breezy-studies.slice` + flock; nothing heavy inside [17:00Z, 01:00Z) (LST union, `std_utc_offset_hours`, never DST — reviewer-corrected; margin `[16:45Z, 01:15Z)`); ingest exit code truthful (`quote_tape_ingest_cli.py:803-805` hardcodes `converted`); orphan node accepted under L-26; parking rules | `SCOPE_STOP_AND_OPS_SERIALIZE_2026-09-12.md` | M |
| SP-2 | B | CRIT | Create-path fill hardening: silent `filled_cost is None` (`submit_chain.py:664-666`); no-leg-selected skips the shape guard (H2); names-only execution key tree emitted and persisted on AMBIGUOUS; `_EXECUTION_DRIFT_ALLOWED_KEYS` gated on captured evidence (none exists today) | `EXEC_CREATE_PATH_HARDENING_2026-09-12.md` | M |
| SP-3 | B | HIGH | Native reconciliation fed from the durable store: venue-id map on submit/resolver; `generate_order_status_reports`/`generate_fill_reports` (`exec/client.py:1946,1961` return `[]`) gated on open positions; persist `tradeId`/`orderQty`; §5 idempotence with mutation evidence; stale docstrings | `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` | M |
| SP-4 | B | HIGH | v3 backtest-only subclass via one `_submission_armed()` seam (a permit-less subclass would replay the SHADOW path); driver `--strategy`; depth-basis CLEAN gate (L-35); one capped SFO 2026-09-01 replay | `V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md` | M |
| SP-5 | B/S | CRIT | Coverage / KILL clock: read-only diagnostic (blips vs outages vs never-resolved rows from dead recorders); dry-run of tonight's afternoon under the shard-local recorder; ruling package on §9 tolerance; truncation as a named reason | `COVERAGE_KILL_CLOCK_2026-09-12.md` | S+ruling |
| SP-6 | B/O | HIGH | Alert delivery: delivery receipt, shared sink, gap/disk/ingest routed to it, `breezy-alert-test`, `OnFailure=` template, word-boundary redaction test. OPERATOR supplies the destination (one line in `~/.config/breezy/alerts.env`); until then B4 stays open | `ALERT_DELIVERY_2026-09-12.md` | M |
| SP-7 | B | LOW | Free hygiene: permit-log leak scan (1.98%/run flake; `test_app_trade_main_permit_logging.py:115`), five doc truth insertions, three docstrings, `PositionReportingLag` disposition; no bulk reformat | `HYGIENE_FREE_FIXES_2026-09-12.md` | S |

**Execution order (from the 2026-09-12 peer reviews, Rev 1 dispositions land as Rev 2 in each plan):**
SP-1 I1/I2/I3 (window per R-B: `[17:00Z, 01:00Z)`; drop the 4G→2G ingest change; I5 needs a v3 SCORER pass and a v3-scoped count, not only a tally unit) → SP-2 → SP-3 (after SP-2; both edit
`_submit_order`; SP-3's venue-id call must sit right after `classify_create_order_outcome`, before
the kind dispatch, and widens the firewall callee allowlist explicitly) → SP-4 ‖ SP-6 ‖ SP-7 (the
permit-log leak-scan fix is owned by SP-6 A3; SP-7 H-1 defers to it) → SP-1 I5 after R-4 → SP-5
diagnostic is inert until the v3 tally receives the count (R-4).

**Rulings queue (strategy lead, artefacts under `docs/evidence/`; block only the increment named):**

| R | Question | Blocks | Source |
|---|---|---|---|
| R-1 | Fee unit on the reconciled `FillReport`: O1 recorded / O4 hybrid + `feeSource` admissible without amendment (reviewer: recommend O4); O2 bare modelled fee needs an amendment; O3 raw-else-refuse likely yields no report on today's record | SP-3 B1 | P3 §8 |
| R-2 | May a reconciled `OrderFilled` reach `on_order_filled` (`external_order_claims`)? | SP-3 B2 | P3 §8 |
| R-3 | §9 coverage tolerance: (i) keep any-overlap, (ii) duration X≈60 s, (iii) span-with-max-gap, (iv) never-resolved rows from dead processes; does a safety-stop calibration trigger v1 §7 re-registration? | SP-5 rule change | P5 §8 |
| R-4 | v3 §9 is "unchanged from v2" with no carve-out, so the v3 tally MUST receive a v3-scoped count (own `--family-manifest pm_us_crh_cont.json`, d0 09-12, never v2's JSON); today no unit runs the v3 tally at all | SP-1 I5 | P1 §8, R-F |
| R-5 | Is PREREG v1's 60/150 tally still evidence (may `breezy-live-tally` stop)? | SP-1 I1 | P1 §8 |
| R-6 | Evidence sufficiency for declaring `_EXECUTION_DRIFT_ALLOWED_KEYS` (repo precedent: one observed key tree) | SP-2 I4 | P2 §8 |
| R-7 | `PositionReportingLag`: keep and wire on the create path later (recommended), never on the resolver path (`ts_event` is poll cadence) | SP-7 H-8 | P7 §8 |
| R-8 | ABSENT slug on a FRESH eof-complete page = FLAT for candidate instruments at BOTH `_run_never_arm_walk` and `_rearm_permitted`; supersedes Slice-4 review item 5 (its PASS state was unreachable). Residuals R9/R14. | closed 09-12 | HF-1 |
| R-9a | Re-arm evidence freshness, build-side constants: `_REARM_EVIDENCE_MAX_AGE_NS`=180s (site 2 only) and `_EVIDENCE_REFRESH_AFTER_NS`=60s (resolver supply); floor 120s < ceiling ⇒ a healthy loop always clears. | closed 09-13 | HF-4 |

**KILL clock (truth as of 09-12):** counter 0/15 for 09-05..09-11 by mechanism; shard-local
accounting (d3f6c47) live in the recorder since 09-12 09:00Z; first real reading is the 09-13
14:15Z artefact. Zero-fill / retired-AMBIGUOUS takes are not trials; resolver fills are residual.

**Parked (re-open trigger: a v3 verdict, or fills at rate).** Kalshi sibling (`wip/kalshi-s4-registry`,
`kalshi_crh_v1.json` DRAFT, S11 operator-only); LADDER_EV stage 2 (stage-1 modules stay);
forecast ingest; whole-tape replay regen; G-16/G-17 (calendar; NO-GO stops the programme);
PREREG v2 residue; EXEC SPINE R-7 residue; blind-risk T-9/T-6/`max_simultaneous_positions`.
Debt carried without a slot: CF-1, CF-2 (no consumer), CF-4, CF-5b, CF-6, CF-7, CF-8, CF-11
(`ruff format --check` 268 files incl. 64 under src/), CF-12 (mypy 433/41, all tests+scripts;
ruff 24 incl. `persistence/family_manifest.py:42`), CF-13, CF-14b, PF-1, BL-10, GL-4P.

---

## Pointers

Audit `docs/evidence/READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(L-1..L-38, all binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
