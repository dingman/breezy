# RULING FQ-PREREG-v2-AMENDMENT (coordinator, 2026-10-06)

**What is frozen.** The PREREG FQ v2 design JSON `F5_prereg_v2_design.json` in this directory, at the sha recorded in its `frozen_sha` key. `scripts/analysis/prereg_precommit_check.py` enforces the freeze: canonical-JSON equality with the committed blob, the sha must be an ancestor of HEAD, and the constants must match the MC module.

**Contents.**
- **e-process:** m_cap 2, X_max 4.0, heavy-tailed e-LOND at T=4, and agrapa_v1 betting on both e_a and e_b.
- **Pins:** θ 0.0695, ask floor 0.05, one-tick haircut.
- **Power table:** joint-power `n_e_power` {889, 1208, 1373, 1483} at δ_h 0.16. It is the worst case over the take-rate interval and the edge-excess sweep (the MC `headline_basis`).
- **KILL:** hedged CS at α_kill 0.05.
- **Parity gate (F6):** single look, n_par 15, δ_par 0.01, α_par 0.10, bootstrap seed 20261006 with 10,000 replicates, `stale_parity_h` 36.

**δ_h is a design-effect pin, not a feasibility claim.** 0.16 is the smallest grid effect for which every k=1..4 is tabulable. It is about 50 % ROI on a 0.30 ask (FQ-R14).

**Verdict: STARVED.**
- At the pinned design N exceeds the available n at every grid point. At 0.25 takes/day, uptime 0.9, the window 2026-10-10 → KILL 2027-01-25 gives 24 takes against N ≥ 846.
- Live e-process confirmation is infeasible before KILL. Every `e_process` nomination is infeasible under E-25 rule 6a.
- No forward-only shadow source is registered (GAP-13, FQ-R38), so F12 PROMOTE stays gated.

**Consequence.**
- The pre-registered M1 fallback applies (FQ-R14). The offline route (M1 scan, F13 sources and timing) is the primary edge search.
- The Takes e-process stays the KILL and capital-protection instrument. The KILL CS is unaffected by starvation.

**Parity feasibility (binding on F9 acceptance).**
- t_par = 2026-12-16 against the KILL−14 d cutoff of 2027-01-11. It needs a fill rate of about 72 % or more (15 fills in 93 days at 0.225 takes/day).
- Parity power was not computed and is recorded as weak.
- The gate is DEMOTE-only, and UNDERPOWERED never acts.
- If fills are still below n_par at KILL−14 d, continuation protection rests on F6 and `live.drawdown` alone.
- `take_rate_lower` 0.25 is revisited once v2 forward takes accrue.

**Consumption.** F6 may read `stale_parity_h`, `n_par`, `delta_par` and `alpha_par`. F7b may read every other key. Both read only the frozen blob.

**Invariants.** No operator-reserved control appears. Holdout days ≥ 2026-07-01 stay sealed. Venue prices are execution cost only.

**Provenance.**
- MC: `docs/evidence/f5/fq_resume_n_mc_seed20261006.json` (seed 20261006).
- Draft: trading-bot-architect. Adjudication: prediction-market-reviewer.
- The adjudicator overrode the draft on four items: `n_e_power` (draft omitted the sweep rows), `n_par` 20→15 (20 was infeasible at IOC fill rates), `delta_par` 0.02→0.01, `alpha_par` 0.05→0.10 (restrictive direction), and `stale_parity_h` 48→36 (fail closed).
- The coordinator adopted the adjudicated values.
