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

- **Audit 2026-10-22** (`docs/evidence/AUDIT_independent_2026-10-22.md`): taker
  falsified live (34 fills / 4 wins / −2.63; Σprice 6.36 expected wins); maker-sharp
  17/17 is an in-sample nomination (LB 0.839 < breakeven 0.865–0.888); PM.us ceiling
  ≈ $10–65/month even with an edge. Primary failure = edge, compounded by process.
- **P4 ARMED 10-24 13:08Z**: `pm_us_no_maker_sharp_v1` is the only sending family from the
  16:50Z launch; the FQ v1 orders-off drop-in is backed up, not deleted (rollback = restore it).
- Prior backlog (ARM maker-sharp, MAKER S2–S5, BLOCKERS, calendar reads) is
  ARCHIVED, not scheduled: `docs/core/archive/PROGRESS_2026-10-22_pre-audit.md`.
  `arm/integration` (c614fb0b) is unmerged; P4 decides whether it is reused.

---

## BACKLOG — Shortest credible path (operator 2026-10-22: "replace the backlog … simple is often better")

Plans: `docs/plans/backlog/AUDIT_PATH_2026-10-22/P<n>_plan_r<N>.md` (peer reviews in
`reviews/`). Strict order; a FAIL ends the chain at that item. The plan is the
pre-registration — thresholds never move after data is read.

**Binding on every item.** Nautilus immutable; `allow_short=False`; never weaken a
safety, settlement, contract or NO-SEND test; never set or invent an operator cap;
simplest change that answers the question — no new harness, unit, ledger or ruling
unless the plan names why.

| # | ID | Work | Cost | PASS | FAIL / STOP | Status |
|---|---|---|---|---|---|---|
| 1 | P1 | Latency pre-flight on the sharp maker replay | — | — | — | **PASS** 10-22 (`docs/evidence/P1_latency_preflight_2026-10-22.md`; G0 exact set 17 / 1.96 at 8de5ebd4 on `design/maker-nobid-2026-10-21`; G1 `sharp_l1` 17 stress fills, 0 losers; L=5 s 16/16) |
| 2 | P2 | NBP p vs venue ask at the 16:50Z D−1 launch | — | — | — | **FAIL** 10-22 (`docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`; YES P&L −0.053/take, n 150, UB −0.008; D_res −0.023; independent PMR TRUSTWORTHY-WITH-CAVEATS). P2-DEL closed: keep FQ v1 dormant behind the orders-off drop-in, no deletion (`P2DEL_impact_check_r1.md`) |
| 3 | P3 | Venue probe: ONE qty-1 GTD rest at $0.01 for 4 h | ≤ $0.01 | NEW to G−30 s, EXPIRED at G+60 s, echo ±1 s | CLAMPED / EARLY / LATE → multi-hour resting unsupported | **PASS** 10-23 (`docs/evidence/P3_GTD_PROBE_2026-10-23.md`; order D947ECW011MQ NEW at confirm/mid/G−30, EXPIRED at G+60 s, echo ≤1 s, no fill, account clean; run from 061856dd on `arm/b2-control`). Licenses a 4 h live GTD only |
| 4 | P4 | Live qty-1 maker bids, sharp as built on `arm/integration`, live GTD capped at 4 h, existing caps (needs P1 + P3 PASS) | ≤ ~$21 lag-bounded | ≤ 1 loss in the first 37 settled station-days (p0 0.8747) AND net > 0 | 2nd loss = FAIL; < 8 station-days by day 21 or day 75 = STOP | ARMED 10-24 13:08Z (feat 83b138b6; drop-in backed up in `~/.config/systemd/user/dropin-backups/`; rollback = restore it). Churn fix ed888605 + OnFailure template aec552b6 + LAX truth promote 84eba08b/c29bb74c all live; last full gate 7f438daa EXIT 0 |
| 5 | P5 | Scale decision (only if P4 PASS) | operator | projected net clears operator hurdle | PM.us capped at tens of $/month → Kalshi question | READY — `P5_plan_r2.md` (+r2.1); one formula vs the operator hurdle |

### P4 live read — 2026-10-27/28 (coordinator; evidence `docs/evidence/P4_LIVE_READ_2026-10-27.md`, `_2026-10-28.md`)
- **Tally (12:50Z 10-28):** 0 fills / 0 station-days after 4 windows; zero is real (durable store, node logs, D1 artefact agree). Not execution: constrained replay keeps 9/17 fills. Cause: thin-queue opportunity ÷3 since 10-13, disagree rungs 0/day since 10-17 (regime) + SEL-1 (own order in the pricing book; fixed b639a015, live 10-27 19:18Z, **0 REPLACED cancels since** vs the prior self-ratchet). **Projection:** day-21 STOP (≈11-14) near-certain; thresholds unchanged; P4 runs on (r2.2 amendment: fills tagged pre/post fix).
- **Premise reassessment (10-28, trading-bot-architect, 5 candidates):** nothing on PM.us is worth designing before the ruling; LAT-1 Stage 0 (built, outcome-free, prize ≈ $0.03/day, prereg UNFROZEN) is a closure item at the ruling, not now; early regime STOP is a permissible r2.3 amendment but buys nothing (qty 1, no successor) → not filed. At the ruling: P5/Kalshi question to the operator (C5 = read-only Kalshi P2 analogue).
- INCIDENT 10-28 (venue added 3 Order fields → `resting_query_unreadable` latch) FIXED e5cdf116, LIVE since 23:45Z 10-28 (L-48). OPEN residue: live confirmation of the mapper fix needs the first boot that posts; first-fill checklist: record value-free types of the three fields; decide whether `estimatedCommission` joins the fee-drift watch.
- **Lost windows:** 10-27 16:52–19:18Z (venue 401 on balances, transient, cause UNVERIFIED); 10-28 20:20–02:50Z (incident). Both covered recorder days.
- **Defects OPEN:** [MED] OPS-4 ROI `GATED_IDENTITY n_labels_gated=25` = marker absent because `breezy-label-outcomes` was never promoted (plan r2 READY, see cycle line). Acceptance: report reproduces audit 34 fills / 4 wins (Σcost 6.36, payout 4.00; fee recompute UNVERIFIED) with `n_labels_gated=0`. [MED] OPS-2 maker writes no `no_ladder_maker/trial/*` latch keys → scorer/ROI attribute a sharp fill only via ledger. [MED] SEL-2 `reconcile.py:74-75` spends a slot on a refused post. [MED] permit order-count budget exhausts 30–40 min before window end (design consequence of caps; not to change). [LOW] AMBIGUOUS→GET `component_degraded` CRITICAL per order (4–5/day). [PROCESS] ARM-gate `unreadable == 0` never held; no waiver on record.
- **Routing:** Grok RESTORED 10-28 (probe exit 0; used for the code read + both fixes, verified against the diff); Codex `model_not_found`; Claude sub-agents otherwise. L-67: probe the route first.
- **[HIGH] EXEC-FOREIGN-POS — operator ruling 10-29 (bot ignores the operator's manual venue activity).** Stage A LIVE, MET; Stage B MERGED 284cff57, boot reads 10-30 KEEP (`P4_LIVE_READ_2026-10-30.md`), 10-31 `foreign=10 refusals=0`, 0 `kind=open_order` → foreign-ORDER path still UNEXERCISED (item OPEN until a manual DAY order exists at boot). D-A CLOSED 11-01 (own bound rests excluded; stale own orders still counted). D-B CLOSED 11-01: resting-confirm GET right after create returns 404 (now logged), retry maps.py change for D-A + D-B status log → byte re-pin (aut2.label + aut6.health) → gate → relaunch.
- **OPS-4** (`docs/plans/backlog/OPS4_LABEL_PROMOTION_2026-10-30/plan_r2.md` + `plan_r2_1_delta_D15.md`): S0 SATISFIED (`OPS4_S0_2026-10-31.md`, artefact b73508f3: peak 0.231 GiB, 34 fills). S1 BUILT 11329cd9 (reviews APPROVE; pins once; D12 strict); gate GREEN e0feb2a3, pushed. **S3 ENABLED 05:08Z 11-01; FIRST FIRE 14:15Z FAILED** (`OPS4_S3_2026-11-01.md`: exit 2 in 1 s, `not_under_unit` refusal, no marker; OnFailure alert fired; scorer 13:55Z success). Not re-run by hand. **S3b** (root cause: bwrap `--unshare-cgroup-try` hides the cgroup leaf; S0 ran outside bwrap) 40dec67b gate GREEN + pushed; next fire 05:00Z 11-02; acceptance `n_labels_gated=0` at the 17:40Z ROI run. ROI exit 1 daily since 10-26 = GATED_IDENTITY, not new. P4 day-21 ≈ 11-14; then SEL-2; [OPS-5 MED] host timer owed.
- **ALERT-4XX KEPT** fcad450c — first full quota day 10-31: 16 deliveries, 15 × 2xx, 0 × 4xx, CRITICAL 7/7, `webhook.backoff` never needed (`P4_LIVE_READ_2026-10-31_D1.md`); 1 lost non-CRITICAL on a `ReadTimeout` (plan's degrade path). NEW shape to classify: `discovery active market count dropped from 126 to 84` (1×). P4 D1 10-31: 5 posts, 3 accepted, **0 fills** (day 7/21).
- **STRAT-DESIGN (operator 10-31: Grok designs, bot backtests).** Artifacts `docs/plans/backlog/STRAT_DESIGN_2026-10-31/`. Facts: PM.us prize ≈ $0 at qty 1 for every cell (size = operator lever); maker Tier 1 fee 0 since 10-19 ([MED] `fees.py` charges makers +θ / credits −0.0125: DEFECT); **Card E KILLED** (`docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.md`, TWC = NWS CLI 5185/5186 → Kalshi-for-basis closed). **Card A CLOSED: ONE look 19:20Z 10-31 → leg 1 KILL, leg 2 KILL** (`card_a_census.md` 5d2c52e9; 149 station-days). Never re-run. **Card D CLOSED-UNRUN 11-01** (`card_d_g0_amendment_r1.md` e7735297; architect + PM reviewer APPROVE: BLOCKER-H = no existing script+flag yields the estimand and a new evaluator is forbidden by the 10-21 ruling; prize ≈ $0 at qty 1; expected KILL; zero looks spent; revival conditions in r1 §7). L-75 extended to writer `.md` (Card E disclosure → sidecar). **No design card open; every PM.us qty-1 cell ≈ $0 → next design starts from the size question or a new surface.** Follow-up: `DEFAULT_SPLITS` lacks cl.1's end date (architect change). Engine path inert for makers until order guard + `fees.py` change (J4). Route: Grok EXHAUSTED 402 since ~15:15Z 10-31 (two write runs died status-1 mid-task), Codex `model_not_found` → Claude sub-agents (tdd-guide/architect/pm-reviewer); re-probe Grok each cycle.
- **Next action (cycle end 11-01 16:55Z, external event pending = 05:00Z label fire + 16:50Z boot read):** (1) OPS-4 S3b DONE: 40dec67b gate GREEN (29851 passed), PUSHED 16:48Z; 05:00Z 11-02 catch-up fire = first test of the fix, checked at wake `c8f0b6e2` 05:13Z (record MemoryPeak); acceptance `n_labels_gated=0` at the 17:40Z ROI run after a successful label fire; (2) D-A + D-B LIVE 16:50Z boot, read MET (`P4_LIVE_READ_2026-11-01.md`: startup lines 4 vs 35, 1 stale own order kept; resting-confirm refusal = transient 404, cause DETERMINED) → both CLOSED; observation: 23 ambiguous creates / 46 OPEN-intent denials in 50 min (known mechanism, 3.6× post volume); (3) Card D DONE (CLOSED-UNRUN) → next design brief must start from size / new surface (Grok when funded); (4) HOLDOUT-END plan r2 APPROVED (`docs/plans/backlog/HOLDOUT_END_2026-11-01/plan_r2.md` 4c3cb789; administrative correction: `final_rows_for_report(include_holdout)` unbounded, forward label, guard refuses holdout only per cl.2, two pin sites + TE-2 sidecar, two commits) → BUILT 2f5df3a0 (code+tests) + d1f7e120 (pins 5718264c→eb5322a9 + TE-2 sidecar); python+PM reviews APPROVE; full gate on d1f7e120 running → push on EXIT=0; (5) operator size question open. Wakes: `c8f0b6e2` 05:13Z 11-02, daily `db1e44f2`/`fc4d504c` 13:07Z and `c45d8c0a`/`bb2925bd` 17:08Z (session-only).

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
