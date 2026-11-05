# EDGE_2026-09-27: backlog index (edge-hunting re-arm programme)

This work comes from the 09-27 audit: "is the bot armed to keep hunting and trading edges?" The answer was NOT ARMED. The A1 halt is deliberate: n=3 is not a demonstrated edge, and the portfolio ROI is -18.7%.

Each plan went through adversarial peer review (architect + python + security and/or prediction-market) until it converged. Implement through `/execute-backlog`: tdd-guide in a worktree, then review, then merge and the full gate.

| Order | ID | Plan (use the final revision + its appended amendment) | Status | Depends on |
|---|---|---|---|---|
| 1 | EDGE-2C | `EDGE-2C_no_leg_resolver_crash_plan_r1_2026-09-27.md` | READY (arch, sec, py) | — (hard precondition of any re-arm) |
| 1 | EDGE-1 | `EDGE-1_fee_drift_guard_plan_r2_2026-09-27.md` + final amendment | READY (arch, sec, dom, py) | — (closes AUD-12b; A0 precondition) |
| 1 | EDGE-6 | `EDGE-6_ops_reliability_plan_r2_2026-09-27.md` + final amendment | READY (arch, py); 6c-0 DEPLOYED 09-27 03:40Z | 6f after 6b; 6c = K1 retirement ruling first |
| 2 | EDGE-2 | `EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md` + convergence record | READY (arch, sec, py; dom r1) | EDGE-2C; Step 0 read-only venue queries gate slice E |
| 2 | EDGE-3 | `EDGE-3_per_family_halt_plan_r2_2026-09-27.md` + final amendment | READY (arch, sec; py closed by AM-3) | — (needed before any fresh family registers) |
| 3 | EDGE-5 | `EDGE-5_rearm_roadmap_plan_r4_2026-09-27.md` + final amendment | READY programme (arch, dom, py) | EDGE-1, EDGE-2C, EDGE-3, EDGE-6d, AUD-12 |
| — | EDGE-4 | `EDGE-4_DISPOSITION_2026-09-27.md` | FOLDED into AUD-18a (not built) | — |

## Binding cross-item rules
- **SEARCH/CONFIRM firewall** (EDGE-4 disposition): any statistic on tape station-days after the 2026-09-25 freeze permanently spends them for H-ARCHIVE-RECAL-2026-09. Declare the corpus explicitly.
- **α:** a hypothesis that gates a re-arm is tested at a programme-wide FWER of 0.025, so per_variant_alpha = 0.025/4/k (EDGE-5 RA-8b).
- **AUD-12** gates every CONFIRMED result and every re-arm (triage C_VALIDITY; `promotion_criteria.py:427`).
  - 12b = EDGE-1.
  - 12a = a two-peer ruling. Recommended: retain the 0.01 slippage placeholder as a conservative allowance. Replay slippage is 0 by construction (`paper_replay.py:157-169`).
- **Clearing the A1 halt and live enablement stay operator-only**, after a new A1-class ruling (RULING_A1 §7).

## Realistic outlook (EDGE-5)
- The infrastructure fast track completes around 10-04. A0 fee evidence closes no earlier than 09-30, after 5 consecutive complete days, and only once the EDGE-1 probe works.
- A CONFIRMED or REJECTED result on the trigger-4 off-window hypothesis is about 3–5 months of build and accrual away, and cannot come before AUD-12.
- An evidenced KILL, which leads to the parked Kalshi branch `wip/kalshi-s4-registry`, is judged more likely than CONFIRMED.

## Follow-ups (not yet planned)
- EDGE-2-LAG: sample fill-propagation latency on the first live fills.
- EDGE-2-SEEDSIDE: the seed counts SELL cost as spend; this over-counts, which is safe.
- FU-17b: `_do_boot_retry` split and interim WARN.
