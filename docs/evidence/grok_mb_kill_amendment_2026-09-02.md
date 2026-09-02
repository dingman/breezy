# Grok — M_B kill criterion amended after the audit (2026-09-02)

Verbatim Grok output, read-only (`--permission-mode plan`, no shell, no subagents), tree `528272b`.
Supersedes the kill sentence in `grok_mb_design_2026-09-02.md` §1.

---


**Taken set (unchanged screen, new evidence).** Afternoon-covered dense station-day; **first** lagged executable current-rung snapshot (ask ∈ (0.05, 0.95), size ≥ 1.0); archive `edge = p_hold_lower − ask − 0.06·ask·(1−ask) > 0`; cell not `n/a` / m=1 / open-lower. One trial per station-day. `held` = CLI in **that** rung. Archive p_hold still selects; it is not the edge.

**Kill.** Over taken trials: k = Σ held, n = |taken|, ā = mean ask, `BE(a) = a + 0.06·a·(1−a)`. Wilson 95% **upper** on k/n (`wilson_interval`, z=1.959963984540054) **< BE(ā)** → family dead. Same test per **station** and per ask-band `{(0.05,0.15], (0.15,0.30], (0.30,0.95)}` vs that stratum’s mean ask; any stratum with n≥60 and upper < BE_s is cell-dead. Family also dead if every tape-visited cell is n/a / m=1 / open-lower. Must hold at lag **10 and 15**.

**n.** Kill may fire at **n≥60**. Survive needs **n≥150**. Below the relevant floor: **UNDERPOWERED**, not dead, not alive. n=60 kills a near-zero realized rate (the overrun pattern). It cannot yet kill a market-efficient p≈ask fee leak; that leak is not this test at this n.

**Survive.** n≥150, Wilson 95% **lower** of k/n **> BE(ā)**, no n≥60 stratum cell-dead, lag 10 **and** 15. Season-local (no season pool). One day’s +0.53 is not a survive.

**Independence.** One trial per station-day. Snapshot-weighted pools forbidden. Same-calendar-day stations are weakly dependent (Wilson anti-conservative; SS2). Do not treat 3 stations on one climate day as 3 climate draws.

**Do not further-condition the entry filter.** Morning ΔT → noon-to-15:00 climb is in the same ASOS series; month vs season is a finer climatology bin (`n_min=90` still fits ~5×30 days). Both are still unconditional-on-forecast. The 09-01 miss is **forecast**-conditioning. We ingest no forecasts and must not fake them (forecast family already killed; no `ForecastSource`). Month / morning-ΔT may be **sensitivity tables** on this taken set. Promoting them to the screen before this kill runs is moving the goalposts. If this kill fires, a ΔT-conditioned screen is a new measurement, not an M_B resurrection.

**Clock.** ~3 dense afternoon-covered station-days/day. Taken ⊂ covered (09-01: **1 taken / 4 covered**). At 3 taken/day: n=60 ~20 climate days (~2026-09-22); n=150 ~50 days (~2026-10-21), still SON. If taken stays ~1/day: 60 / 150 calendar days. Archive table is frozen; only the tape-side Wilson waits.

**Next step.** SURVIVE → BL-24 is worth building so a Nautilus backtest can price the cell. Not a GO to exec or live. A kill leaves G-02 / recorder + offer-gate.

**UNVERIFIED:** taken rate going forward; IEM vs `api.weather.gov` lag; whether cheap-band mean ask stays ~0.06.


---

## The brief Grok answered

# Short follow-up — amend M_B's kill criterion after the audit

Read-only, files only: NO shell, NO subagents (`run_terminal_command` and `spawn_subagent` are unavailable). Repo root is the cwd. Under 60 lines. Invariants unchanged (Nautilus immutable; `allow_short=False`; no safety/contract test weakened; no operator-reserved control assigned; no live enablement; no live orders).

Your M_B design (`docs/evidence/grok_mb_design_2026-09-02.md`) was implemented and run (`docs/evidence/mb_current_rung_edge_2026-09-02.md`, `scripts/analysis/mb_current_rung_edge_study.py`). Part A reproduced exactly under independent audit (read the audit note at the top of the evidence file). Findings: m=0 interior Wilson-lower p_hold is 0.66–0.84 at h=13/15 JJA/SON on dense stations; the MDW 09-01 noon trial had ask 0.06 on rung [91,92] with p_hold_lower 0.594 (edge +0.53 by your formula) — and the day settled 93, above the rung. The market was right; the archive number is an unconditional base rate while the ask is forecast-conditioned. Your kill sentence ("dead if no station-day's first lagged current-rung snapshot has Wilson-lower p_hold above ask + fee") therefore cannot fire — base rates will exceed low asks on most days — and cannot confirm anything either.

**Amend the kill criterion so it discriminates.** I expect it to be your forecast-memo paper-join shape: over the taken trials (first executable lagged current-rung snapshot per station-day with edge > 0 by the archive formula), the REALIZED hold fraction's Wilson 95% upper bound below `ask + 0.06·ask·(1−ask)` (stratum-wise or at the pooled mean ask) kills; state n (≥60? ≥150?), the stratification (station; season; ask band), independence (one trial per station-day), and what a SURVIVE looks like. Also say whether the archive p_hold should be conditioned further using data in hand (e.g. on the noon-to-15:00 climb distribution given the morning's warming rate from the same ASOS series, or on month rather than season) so the entry filter is less naive — or whether that is exactly the forecast-conditioning we cannot do without ingest and should not fake. Give the sample clock at ~3 dense station-day trials per day. Be direct.
