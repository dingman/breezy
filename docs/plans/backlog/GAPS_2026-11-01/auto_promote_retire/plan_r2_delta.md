# AUTO-PROMOTE-RETIRE plan r2 — delta over r1 (trading-bot-architect re-review 2026-11-01: 3 MEDIUM; prediction-market re-review: APPROVE with 3 LOW)

Applies on top of `plan_r1.md`; where they differ the delta wins. Status: r2 — confirmation pending (trading-bot-architect; prediction-market LOWs folded).

## R2-1 (A-M1) Look-k financial basis is the exact prefix P_k
`total_pnl > 0`, `cell_dead` and the n_p reconciliation for look k are evaluated on P_k ONLY (the contiguous final prefix that triggered the look), never on fills after it, so replayed missed looks are reproducible and free of look-ahead. LOSS_STOP alone is evaluated on the current complete set, every pass. An efficacy crossing blocked by `total_pnl ≤ 0` on P_k CONSUMES that look; there is no retroactive eligibility at a later pass. RED tests: `test_look_k_eligibility_uses_prefix_only_positive_prefix_negative_later` and the reverse; `test_blocked_efficacy_crossing_consumes_look`.

## R2-2 (A-M2 + PM-LOW-2) S0 power with the guards applied
`simulate_fixed_pi` / `simulate_drift` do not model the `total_pnl > 0` conjunct or the −60 LOSS_STOP. S0 reports power AND early-retire probability WITH both rules applied (extend the simulation harness in SEARCH-only mode; no new runner). PASS/KILL frozen before S0 runs: with-guards power ≥ 0.75 at the registered δ and n_max, early-retire probability under the alternative ≤ 0.10; otherwise KILL (the item stops at BLOCKED-NEEDS-PLAN, never relaxes). The 0.80 r1 figure is recorded as the no-guards upper bound.

## R2-3 (A-M3) Permit edit and entry-window cost bounded
The `trade.py:1300-1314` change ONLY passes `None` for the permit when the registry demand says RETIRED: no mint path, ledger, NO-SEND or permit test changes; existing permit tests stay byte-unchanged; security-reviewer sign-off is a named S4 gate. S0 measures the entry-withheld duration per slot (05:00 / 14:15 passes) and reports any overlap with the hunt window (hours 10–11 local; memory `hunt-window-opens-after-repricing`) as an ROI cost; outage policy = fail closed (entries withheld) with the withheld hours reported in S6 (PM-LOW-3).

## R2-4 (PM-LOW-1) Oldest-unsettled handling frozen at S0
A voided or cancelled oldest fill is removed from the prefix by its terminal label (never counted); a never-resolving oldest fill past the settlement horizon + 2 days routes the look to `TERMINAL_NO_INFORMATION` with an integrity refusal receipt. Frozen in the PREREG pins.

## R2-5 (A-LOW) The −60 contract-unit LOSS_STOP is pinned from the spec at registration; it is never derived from, scaled by, or proposed alongside an operator cap. Remaining `:line` citations are re-verified at S0 (Codex drafted without codegraph).
