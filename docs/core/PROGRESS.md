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
- **NO FAMILY TRADES** until P4 below arms under its own plan. Node runs
  `pm_us_crh_fq_v1` orders OFF (drop-in `fq-v1-halt-orders-off.conf`).
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
| 1 | P1 | Latency pre-flight on the sharp maker replay (L = 1 s gate, 5 s report) | $0, ~½ day | G0 reproduce 17 fills / 1.96 from committed HEAD; G1 `sharp_l1` ≥ 10 stress fills, no loser | G0 miss = STOP; G1 fail → maker programme ends | READY — `P1_plan_r2.md` (+r2.1) |
| 2 | P2 | NBP p vs venue ask at the 16:50Z D−1 launch | — | — | — | **FAIL** 10-22 (`docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`; YES P&L −0.053/take, n 150, UB −0.008; D_res −0.023; independent PMR TRUSTWORTHY-WITH-CAVEATS). P2-DEL closed: keep FQ v1 dormant behind the orders-off drop-in, no deletion (`P2DEL_impact_check_r1.md`) |
| 3 | P3 | Venue probe: ONE qty-1 GTD rest at $0.01 for 4 h | ≤ $0.01 | NEW to G−30 s, EXPIRED at G+60 s, echo ±1 s | CLAMPED / EARLY / LATE → multi-hour resting unsupported | READY — `P3_plan_r2.md` (+r2.1) |
| 4 | P4 | Live qty-1 maker bids, sharp as built on `arm/integration`, live GTD capped at 4 h, existing caps (needs P1 + P3 PASS) | ≤ ~$21 lag-bounded | ≤ 1 loss in the first 37 settled station-days (p0 0.8747) AND net > 0 | 2nd loss = FAIL; < 8 station-days by day 21 or day 75 = STOP | READY — `P4_plan_r2.md` (+r2.1, items 1–9) |
| 5 | P5 | Scale decision (only if P4 PASS) | operator | projected net clears operator hurdle | PM.us capped at tens of $/month → Kalshi question | READY — `P5_plan_r2.md` (+r2.1); one formula vs the operator hurdle |

### Calendar obligations
| When | What |
|---|---|
| 2026-12-31 | Drop-in allowlist row expiry (`health_dropins.py:55`) → CRITICAL `allowlist_mismatch` unless renewed by a reviewed row; never edit the drop-in by hand |

### Live-state watches (no build owed)
- FD-FLAKE / CT13-FLAKE: on a 3rd occurrence add the per-test fd snapshot / `locks_path` fault-injection test.
- Recorder vs host reboot: an unclean reboot truncates the live instance (10-19 02:34Z cost 10-18 + 10-19 to the S2 trigger); before any planned reboot `systemctl --user stop breezy-quote-tape.service` and wait for `Stopped` (`deploy/systemd/README.md:89-102`).
