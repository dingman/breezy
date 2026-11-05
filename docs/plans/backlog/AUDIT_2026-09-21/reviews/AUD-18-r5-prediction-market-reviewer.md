# AUD-18 — Round 5 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 99b95223debe99d7300f507031009ed0016bf956a63e94d4130fd229ae881f41
Round: 5

## Round-4 MATERIAL (power check mis-cited; inputs unstated) — GENUINELY FIXED

Verified line-by-line against source:
- `polymarket_us_fee` (`fees.py:277`) returns `theta * quantity * price * (1-price)` in dollars. For a `qty=1` contract this is symmetric in the leg's own fill price regardless of side — `StratumRow`'s own docstring already establishes `entry_ask`/`fee` as "the LEG'S OWN ask/fee" for YES or NO (`current_rung_hold_v2.py:99-104`). `BE = a + theta*a*(1-a) + slippage` is therefore the correct per-contract break-even hold probability for EITHER leg, an additive extension of the repo's own `break_even_row = entry_ask + fee`.
- θ=0.0695 confirmed at `FEE_SCHEDULE_PIN_2026-09-18.md:7` ("The 2026-09-17 move to `0.0695`") and `:47` ("## 2026-09-17 diagnosis: drifted theta = 0.0695") — this is the CURRENT venue-charged coefficient (memory `venue-fee-theta-drift-2026-09-17`), correctly distinguished from the STALE `config.py:226` default `Decimal("0.06")`, which the pin doc's own reconciliation table (`:127`) independently lists as one of the stale carriers.
- Worked arithmetic reproduced independently: `z_(1-0.003125)=2.7344` (interpolated table check, matches), `z_0.80=0.8416` (standard constant), `n=300`: `3.5760/34.6410=0.1032`; `n=600`: `3.5760/48.9898=0.0730` — both match. `BE(a=0.30,theta=0.0695,slippage=0.01) = 0.30+0.014595+0.01 = 0.324595` — exact.
- AUD-12's `slippage_prob` placeholder confirmed `0.01` (one tick), UNMEASURED (`AUD-12-cost-model-slippage-and-fee-drift.md:114`), matching the plan's worked example and its re-run obligation.
- Both prior mis-citations (`ROIBoundUnderpowered` — a post-hoc n-floor; `combine_station_day`/`score_combined` — realized-row estimators) are explicitly withdrawn for this purpose, with the correct reason stated, and each keeps its own legitimate role elsewhere in the plan.
- The new mechanism is genuinely outcome-free: `recompute_mde(per_variant_alpha, n_station_days)` reads no `StratumRow`/draw, uses the pinned conservative `q(1-q)<=1/4` bound (itself the repo's own established convention behind `I_MAX=40.0`, `PREREG_v2 §3-4:55-60`), and `register_hypothesis` recomputes rather than trusts the ruling's stated number.

## Sweep

No contradiction found: §9's worked illustration and §11's ROI framing both consistently state `UNDERPOWERED_NOT_REGISTERED` as the expected first-intake disposition; no remaining section implies a likely `CONFIRMED` outcome (grep for optimistic-outcome language returned nothing). Enforcement is mechanical and layered correctly: the pure statistical MDE (`recompute_mde`) and the market-terms `BE` translation are properly separated — the former is code-enforced (D13), the latter is the human-readable justification a peer ruling states for its plausibility bound — a sound and auditable split. Length grew to 961 lines and this is stated plainly, consistent with rounds 3-4's honest accounting; no requirement, test, or acceptance criterion was cut.

No new defects found, MATERIAL or MINOR, after full re-sweep of the changed sections and re-verification of every citation this round introduced or restated.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — the loop is complete and honest: a mechanically-enforced, pre-data power gate now backs the "produce or honestly refuse" goal state.
- Technical correctness and evidence grounding: 20/20 — fee formula, θ citation, config staleness, BE arithmetic, and z-values all independently re-derived and confirmed exact.
- Implementation specificity and feasibility: 15/15 — `recompute_mde` signature, the five-clause enforcement (vi-a..vi-e), and the dataclass's recorded inputs are concrete and directly testable.
- Acceptance criteria and validation quality: 20/20 — D13 now pins the computation itself, not just the refusal branch.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected, unchanged since round 3, still solid.
- Portfolio alignment, scope and dependencies: 10/10 — unaffected, clean.

**Total: 100/100.**

## Blockers

None.
