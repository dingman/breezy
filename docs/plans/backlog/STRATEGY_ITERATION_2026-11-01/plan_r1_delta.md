# STRATEGY-ITERATION plan r1 — delta over r0 (2026-11-01, after architect REVISE + prediction-market-reviewer REVISE)

Applies on top of `plan_r0.md` (5079a266). Where this delta and r0 differ, the delta wins. Status: r1 — **blocked at Step B on BLOCKER-H pending an operator exception**; Step A is runnable now.

## D1. BLOCKER-H (architect, BLOCK). No existing script emits forward per-rung forecast probabilities for the tape window.
`nbp_skill_study` validate drops every climate day ≥ holdout start (`nbp_skill_study.py:760, :1906-1914`); the blend features build ends 2026-06-30; `multisource_blend_skill` writes only OOF rows and `result.json` from < 07-01 (`:714-727`); `p2_nbp_ask_murphy` computes `ladder_p_yes` internally but writes only markdown (`:608`). Producing a per-rung p file for [10-02, T_freeze) is evaluator logic → **operator exception required** (Card D precedent). Until granted, §4B/C/D of r0 are unbuildable; §4A is not affected.

## D2. Criterion restated to what the scan computes (architect HIGH; PM HIGH).
`market_calibration_scan.py` outputs per cell: mean excess `hit − (ask + fee)` with a day-block bootstrap percentile CI and a one-sided p (`:472-474, :578-600`), plus a per-run SPA p (`:603-612`). It has no Wilson LB, no `a_hi`, no `m`. Therefore:
- **Explore gate:** cell `p_one_sided × K_cum ≤ 0.05` (Bonferroni at the cumulative count) AND bootstrap LB of mean excess > m. The cross-run SPA of r0 §3 is DROPPED (joint resample across runs = new evaluator); each run's own `spa_p` is reported, not gated on.
- **Hurdle:** the realised mean `ask + fee(ask)` of the cell's takes, with the fee hurdle computed as `max over a in band of [a + fee(a)]` (rounded fee is non-monotonic: ≈0.02 at 0.5, 0.01 at 0.8, 0.00 at 0.95). `a_hi` is a screen only.
- **Clustering:** rungs within a station-day are mutually exclusive → the bootstrap block is the station-day (already the scan's day block; verify it is day, not rung).
- **Anti-gaming:** `m` is drawn from the declared grid {0.02, 0.03, 0.05} only; band edges are frozen at registration; a Wilson-on-win-rate criterion, if wanted, is inside the BLOCKER-H scope.
- **Literal 70% floor (operator option):** binds only for `a_hi ≤ 0.65` at m = 0.02; it is an operator preference with no economic basis and removes the cheap-ask cells where break-even < 0.70.

## D3. K_cum seeding and units (architect, PM HIGH).
K_cum starts at the sum of every cell already tested on these days: M1 `tested_cells` (35), P2, Card A (2 legs), Card E, WP-7b and AUD-02 cells. Each p-file variant (source × horizon × calibration map × blend weights) counts as its own unit in K. A read CONFIRM block is burned data, never explore data. A reopen on a new venue inherits the source × horizon × side priors.

## D4. Ledger (architect MED, L-75). r0's append-only `docs/evidence/.../variant_ledger.jsonl` is replaced by one immutable `runs/<run_id>.json` per run = the scan's own `--out` file (it already carries `tested_cells` and `spa_p`), kept under `~/.local/share/breezy/derived/strategy_iteration/` (precedent `maker_stage0_replay.py:45`). K_cum is a coordinator sum recorded in the PREREG at registration; `prereg_precommit_check` must refuse a PREREG whose cited K_cum is below the sum of the run files (small guard change, reviewed).

## D5. Budget enforcement (architect MED, PM MED). N = 240 cell-units and D = 28 calendar days from the Step B merge, **never restarted**; R ≤ 3. Enforcer = the coordinator at the registration checklist + the precommit check in D4. "Margin or calibration-map variant" is NOT 2 runs: every grid point is a unit (D3).

## D6. D_c (architect MED, PM HIGH). Formula confirmed: `D_c = 26 × (19.8/Δ)² × ((z_{α/R} + 0.84)/4.03)²`, a per-cell MDE rescale of M1 (4.03 = z_{0.05/35,two-sided} 3.19 + 0.84). Sidedness: one-sided. At R = 3:

| Δ | D_c (one-sided) | D_c (two-sided) |
|---|---|---|
| 5¢ | ≈ 221 d | ≈ 262 d |
| 10¢ | ≈ 55 d | ≈ 66 d |
| 15¢ | ≈ 25 d | ≈ 29 d |

r0's "75–95 days" is replaced by this table. D_c must also satisfy the frozen n_min of the cell.

## D7. HARM stop (PM MED). Replace "UB below break-even, or 2nd loss before n = 10" with the PREREG v2 sequential design verbatim: LD-OBF lower-side boundary on the Wilson statistic, α = 0.025, looks every 10 fills; disarm when the boundary is crossed. The loss-count rule is dropped (it would fire ≈ always at a 0.30 ask and ≈ 14% falsely even at 0.93).

## D8. Step A corrections (architect LOW). `multisource_blend_skill.py` requires `--c1-evidence`; do not re-run `p2_nbp_ask_murphy` (it scores days inside the sealed window) — cite the existing P2 evidence. Step A is runnable now, one heavy job at a time, MemoryMax=4G.

## D9. Step B scope if the exception is granted (architect MED). The p-file producer must emit rows only for [10-02, T_freeze) (or the frozen CONFIRM window); the scan gains a RED test refusing any p-file row dated before 2026-10-02; the byte-identical-default test against `m1/market_calibration_scan_v2.json` stays. The flag changes the cell key from 3 to 4 fields and bundles station-day exclusion — declare both in the PREREG.

## D10. Honesty (PM MED). Priors (1–5% NBP, 3–12% unscored) are reviewer judgement, unsourced. A PASS at qty 1 is worth ≈ $0–tens of $/month on PM.us, so the programme's expected dollar value is ≈ 0 before the operator's size decision.

## Operator decisions this plan now waits on
1. **BLOCKER-H exception:** authorise ONE new evaluator component — a forward per-rung forecast-probability emitter + the `--forecast-p` scan flag (D1, D9) — or decline, in which case the programme stops after Step A.
2. Whether the literal 70% floor applies (D2).
3. Size q (D10) and whether Kalshi capture runs in parallel.

Peer review of this delta: not yet; r1 is presented to the operator first because decision 1 gates everything after Step A.
