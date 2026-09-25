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
| ADM-1 | B | LOW | Σq admission counts FILLED legs only (concurrent-arm race) | diagnosis §4 | S |
| HUNT-1 | B/S | **CRIT** | **Continuous hunting is REQUIRED and NOT met.** The `[12:00,17:00)` LST gate is a consequence of `P_HOLD_LOWER` covering `hour_lst` ∈ {12..16} only — removing it yields `None`, not hunting. Supersedes WIN-1 (wrongly deleted 09-20) | `CONTINUOUS_HUNTING_GAP_2026-09-20.md` | L |
| EXIT-1 | B/O | CRIT | **Exit seam BUILT, UNARMED** (c96c7f4; ruling 09-16). Decider→native IOC LIMIT SELL→exec exit seam; `pm_us_crh_exit_v4` DRAFT, no `exit_rule` → live family never sells. Study N=5: R-DEAD 0/5 fillable, R-THREAT 1/5 → gates FAIL. Before arming: PREREG v4 registration, 1-lot positive control, nightly study (15:20Z). `POSITION_EXIT_EXECUTION_2026-09-16.md` | plan §4 | L |
| MP-B | B/O | HIGH | Increment B: depth-capped, cent-safe, log-redacted sizing from the per-position cap (S2) + qty through scorer/store (S4b). **BLOCKED on R-11**: at mixed qty∈{1,2,3} the pre-solved LD-OBF boundary over-crosses (0.059 vs α 0.025; strict xfail `test_multi_position_validation_2026_09_14.py`) — re-validate at the real qty distribution, re-solve only then. Operator rulings 09-14 (per-order cap; daily budget = single-day stop) recorded in memory + day-stop plan | plan §3 Increment B | M |
| SP-3 | B | A/C DONE 09-13; B1/B2 open | Venue-id map live (proven on CFJ485874TMM); `generate_order_status_reports`/`generate_fill_reports` still return `[]` pending R-1/R-2; `_has_durable_fill_record` still a stub | `RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` | S |
| SP-4 | B | subclass DONE 09-13; replay **NOT RUN** | v3 backtest subclass, `--strategy continuous_rung_hold`, depth-basis gate landed; the one capped SFO 2026-09-01 replay has no artefact — run it (command in plan :80-91) in a quiet window, record filled trials or BLOCKED reason | `V3_BACKTEST_REPLAY_SUBCLASS_2026-09-12.md` | S |
| SP-5 | B/S | CRIT | Coverage / KILL clock: read-only diagnostic (blips vs outages vs never-resolved rows from dead recorders); dry-run of tonight's afternoon under the shard-local recorder; ruling package on §9 tolerance; truncation as a named reason | `COVERAGE_KILL_CLOCK_2026-09-12.md` | S+ruling |
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
| R-5 | Is PREREG v1's 60/150 tally still evidence (may `breezy-live-tally` stop)? | SP-1 I1 | P1 §8 |
| R-12 | The permit's session ORDER-COUNT ceiling (`floor(daily budget / per-position cap)`, min 1; `safety.py _derived_session_order_count`) can exhaust BEFORE the dollar budget under the 09-14 per-order ruling (many orders below the cap). The day stop marks only the two dollar ceilings; the count ceiling still refuses on its own. Operator: keep it (derive from daily / venue lot minimum) or drop it so the dollar budget is the only day stop | operator | day-stop plan D3 |
| R-11 | LD-OBF boundary validity at qty>1: H0 crossing 0.059 at mixed qty vs α 0.025 (qty≡1: 0.012). Re-validate at the real Increment-B qty distribution; re-solve the artefact only if it still fails | MP-B | validation slice |
| R-7 | `PositionReportingLag`: keep and wire on the create path later (recommended), never on the resolver path (`ts_event` is poll cadence) | SP-7 H-8 | P7 §8 |

**KILL clock (truth as of 09-13 14:15Z):** counter 0/15 for 09-05..09-13. Shard-local gap
accounting works (09-12 in-window overlaps = 0 on all four stations); the day is uncovered because
ingest stranded its Depth10 (ING-1). Zero-fill / retired-AMBIGUOUS takes are not trials; resolver
fills are residual. **Live n (09-24):** 10 orders, 9 fills (durable exec fill store, exact match against real-event log lines; order 1, 09-05, unmatched — AUD-13 escalation), admissible 0.

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

Audit backlog 09-21 (AUD-01..19; 19 READY, AUD-06b not; 09-24 merged: AUD-03, 05, 08a, 10a, 13d (13d amendment endorsed)): `docs/plans/backlog/AUDIT_2026-09-21/README.md` · Audits `docs/evidence/READINESS_AUDIT_2026-09-13.md` (delta), `READINESS_AUDIT_2026-09-12.md` · durable rules `docs/core/LESSONS.md`
(binding) · evidence `docs/evidence/` · runbook `docs/plans/R8_OPERATOR_RUNBOOK.md`
· programme narrative `docs/core/PROGRAMME_PATH.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`

## 2026-09-20 — WP-R1 calibration defect found in production (open)

`ZERO_CANDIDATES_EVALUATED_HALT` fired for MDW at 18:58Z on the first day the
detector ran live, while MDW demonstrably evaluated at 18:48Z and 19:03Z
(`IN_WINDOW_NOT_EXECUTABLE_WAIT`, same station, same window).

**Cause.** A pre-decision WAIT is not a "candidate evaluated". When every tick
in an observation window fails executability — an ordinary illiquid stretch —
the window closes with a candidate count of zero and the detector reads that as
a structural block.

**Why it matters.** This is exactly the false page WP-R1 was designed to avoid:
"the cost of a false page is an operator who stops reading alerts." The
all-refused arm is correctly guarded (homogeneous reason ∈
`STRUCTURAL_HALT_REASONS`); the zero-evaluation arm is not.

**Fix (not yet applied).** ZERO-EVALUATION must distinguish *no ticks observed*
(genuine: no eligible instrument, discovery collapse, subscription starvation)
from *ticks observed but none reached a decision* (ordinary market condition).
Gate it on observed tick count, not candidate count. Add a RED test built from
this exact MDW 18:58Z shape.

**Not a trading blocker** — observability only; the node was hunting normally
throughout. Verified same-window: WS subscriptions healthy (30 instruments
across LAX/MDW/MIA/SFO/NYC), no cap message (the apparent one was a GET URL
containing `limit` as a query parameter).
