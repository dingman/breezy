# F5 pin request r1: merged peer review and coordinator rulings (2026-10-08)

Reviewed: `F5-pin-request_r1.md`. Peers: architect (SOUND-WITH-CAVEATS) and prediction-market-reviewer (SOUND-WITH-CAVEATS). Both reviewers found the KILL constants to be byte-for-byte equal between production and the MC, and the guard to be demote-only. Neither found a leak in the r1 design.

## Converged defects (r2 must fix)

| # | Sev | Defect | Fix in r2 |
|---|---|---|---|
| M1 | HIGH | Rule (vi) rebuilds `check_not_refrozen` (`scripts/analysis/multisource_blend_pin_guards.py:200-229`, PIN-R8b) in a weaker form. | Reuse it. Consumers load amendments with the F13 `load_verified_prereg` pattern (`multisource_blend_skill.py:274-297`), which refuses UNFROZEN. Add a PIN-R8(c)-style content-digest test per file. |
| M2 | HIGH | The floor may be unreachable at the real horizon (about 24 takes by 2027-01-25; c√t ≈ 6.9 contracts against a maximum loss of about 7). This violates L-38. | Add an MC reachability and power gate before c freezes: the loss fraction needed at t_horizon, and the power at a stated negative edge. If the floor cannot fire, r2 must say so and propose the alternative, never freeze a dead stop. |
| M3 | HIGH | The H0 bundle joint is undefined when Σ BE > 1 across sibling rungs (overround). | Specify the joint and state which direction is conservative. |
| M4 | HIGH | F6b inputs are unspecified: the NO-fill sign convention (venue SELL/BUY_SHORT, NO netted as short YES), multi-contract and partial fills, the runtime source of the arming timestamp, and the `truth_sha` feed. | Pin these in the floor file, or list them as inputs that must be frozen before F6b is built. |
| M5 | MED | KILL is coupled to the BLOCKED floor under a single freeze. Rule (iii) also collides with envelope keys. | Use three files: **A0 KILL (freeze-ready now)**, A1 floor, A2 guard. Exempt the envelope keys (`frozen_sha`, `amends`, `amendment_id`, `provenance`) from the overlap rule. |
| M6 | MED | `--amendment` mode edits the parent checker. | Write a sibling `scripts/analysis/prereg_amendment_check.py` that imports `validate_defects`, `check_frozen_blob` and `check_not_refrozen`, so the parent file stays byte-unchanged. |
| M7 | MED | `kill_lambda_max` duplicates `MAX_LAMBDA` (`prereg_precommit_check.py:73`). `content_sha256` would add a third canonical form. `kill_hedge_theta` has no consumer. | Check by import, never by retyping. Reuse the existing canonical form. Drop `kill_hedge_theta` and keep `kill_bar_rule`. |
| M8 | MED | The per-day guard |Z| ignores sequential multiplicity in the false-block rate. Two occupied bins is too weak. The rung is known to be under-confident. | The MC uses the ever-blocked probability over the horizon, a minimum count per bin, and a positive control showing that real out-of-fold windows reach OK. |
| M9 | MED | The √t fill clock is wrong for mixed prices and exclusive bundles. The S_t definition has gaps (θ drift on 09-17, exits via c96c7f4, voids, partials). | Clock in settled station-days with standardised bundle increments. Take BE from the ledger fee, or fail closed on θ drift. Define exits, voids and partials. |
| M10 | MED | KILL power at a mild negative edge is unmeasured (`p_kill_under_null_stream` 0.0025 at −0.019). | Add a KILL power row at a stated negative edge to A0's evidence. This is reporting only; it changes no constants. |
| M11 | LOW | S_t restart after a FAIL or re-arm is unstated. Only `obs` is omitted. | A re-arm after a FAIL needs a new ruling and a new epoch. |

## Coordinator rulings on the open questions (peer-converged; Q11 and Q12 per architect)

| Q | Ruling |
|---|---|
| 1 α_guard | 0.10, calibrated by MC to the ever-blocked rate. |
| 2 CI rule | Point-in-band, as the code does today. |
| 3 Pooling | `per_side`. An absent side is skipped. A present side with fewer than `n_guard_min` takes blocks PASS, and that consequence is stated. |
| 4 Bet rule / min_range | Pinned (additive, so it does not relax L-12). |
| 5 α_floor | 0.10, subject to the M2 reachability gate. |
| 6 t_unit | Settled station-days, with standardised bundle increments. |
| 7 pnl_unit | Qty ≡ 1 per contract. Dollar P&L is a diagnostic only. |
| 8 t_horizon | 2027-01-25, in days. |
| 9 Past horizon | Fail-closed (UNKNOWN, veto). The coordinator owns recalibration. |
| 10 epoch_anchor | The v2 arming-ruling timestamp. There is no pre-v2 window. A re-arm after a FAIL needs a new ruling. |
| 11 Split | Three files: A0 KILL (now), A1 floor, A2 guard. |
| 12 Out of scope | Accepted. Forward-source registration (E-25 6b) must refuse while A2 is missing or UNFROZEN. The 6b owner carries that guard. |

## r2 verification (2026-10-08)

Both reviewers verified r2. The architect marked every one of M1–M11 FIXED. The domain reviewer returned SOUND-WITH-CAVEATS: M8 PARTIAL and the rest FIXED-WITH-CAVEATS. The KILL body was checked byte for byte against `confidence_sequence.py` and `fq_mc_eprocess.py`.

**A0 is READY to implement (both peers).** These are binding build conditions:
- **A0-C1.** In `kill_betting_rule`, sums run over every covered calendar day *including zero-take days (y = 0)*, not just "settled days". Fix the wording in the JSON body before the freeze.
- **A0-C2.** The sibling CLI copies the `_REPO_ROOT` sys.path bootstrap (`prereg_precommit_check.py:36-39`) above its `scripts.*` imports.
- **A0-C3.** `amends.path` resolves against the git top-level, not the cwd.
- **A0-C4.** The Phase 0 STOP runs first, on the full tree: `check_not_refrozen(F5_prereg_v2_design.json)` must not raise.
- **A0-C5.** The AST test selects the `np.maximum` min-range literal, not the cap numerator.
- **A0-C6.** Use a single Defect code `REFROZEN` for any `check_not_refrozen` Refusal.
- **A0-C7.** Drop "plus the parent loader" from §3.4.
- **Seed 20261008 is CONFIRMED by the coordinator.**

**Carried into A1/A2 r3 (not blocking A0):**
- **D1.** Same-rung netting loss enters x_d as a zero-variance mean shift.
- **D2.** Exit-cost sensitivity row or margin.
- **D3.** Qty weighting stated.
- **D4.** Correlated same-day station sensitivity, or a calendar-day tick.
- **D5.** G1/G3 run at the pinned t_min and at a stated take rate.
- **D6.** Epoch id persisted in the artefact. Fee-reconcile and void must not un-latch a FAIL.
- **M8 positive control.** If `real_pool_ok_rate` ≈ 0, A2 is a permanent veto, and 6b registration must say so loudly.
- **G3 floor.** Power at −0.16 must be ≥ 2.5 × α_floor, or the gate fails.
- **Domain rulings on r2 §10 (endorsed):**
  1. Refusal channel: unlink, written after a durable refusal-reason record.
  2. Anchor: (a), the ledger row; refuse if absent.
  3. If G1 fails at 0.10: the smallest α in {0.20, 0.30} with margin; otherwise `unreachable_veto`.
  4. Tripwire freeze: yes, subject to the G3 floor.

## r3 verification (2026-10-08, prediction-market-reviewer)

**Verdict: SOUND-WITH-CAVEATS.** Phase 2 steps 2–4 (the core, checker R5 for A1, and the floor MC script) are **READY TO BUILD**. D6 is PARTIAL; its defects (n2–n4, n6) bind F6b (step 9), not steps 2–4.

**Build conditions (binding on steps 2–4):**
- **n1.** `_exit_record` returns TOTAL proceeds (`reconcile.py:681-694`). The core divides by the sold quantity to get the per-contract v. `InvalidExitFill` maps to a refusal.
- **n5.** H1 δ = −0.16 is infeasible for a leg with BE < 0.16. Clamp p ≥ 0 and report the share of clamped legs.
- **n8.** R5 for A1 must also enforce:
  - `power_class` consistent with `measured_power` (edge_capable ⇒ ≥ 0.8);
  - `s6_feasible_rate ≤ alpha_floor + 3·c_mc_se`, with `c_mc_se` finite and > 0;
  - Decimal comparisons;
  - `_check_payload` receives the draft flag, so that `--draft` accepts PENDING_* only in draft mode.
- **n9.** A named epsilon `SIGMA_EPS` defines "zero-σ". Refuse if a σ² of −ε or below appears (a numerical defect). Guard 0 < BE̅ < 1 before building a row.
- **§10 rulings:**
  1. `κ_exit = max(pool median half-spread, 0.02)`; p_exit 0.10 and ρ_bind 0.25 are accepted.
  2. The G1 margin ⌊0.8·T_low⌋ is accepted.
  3. The Wilson rule requires n ≥ 74 windows, or A2 is "indeterminate" and stops. Use a cluster-aware interval.
  4. The zero-σ carry is accepted. The MC carries the carry and reports max|carry/σ_next|.

**F6b-binding (step 9):**
- **n2.** The latch is keyed by an `epoch_id` read from the registry, which is circular. Persist a `current_epoch` pointer, or treat any latch as FAIL while the registry is unreadable.
- **n3.** The `from_state ∉ senders` rule excludes RESUME (HALTED→CHAMPION). A RESUME with a ruling after a latch must start a new epoch. Filter on `venue` and verify the `transition_hash` chain.
- **n4.** `epoch_id` in `truth_sha` is audit-only at runtime, because the probe never recomputes `truth_sha`. Say so.
- **n6.** Dedupe refusal records. Treat EEXIST on the latch as already latched. Create subdirectories with mode 0700.

The analysis also expects A1 to land as `unreachable_veto`: an all-lose YES longshot gives Z ≈ −0.33/tick, so it needs about 53 ticks to cross, against about 27 available.

## M10 result and ruling (2026-10-08)

Evidence: `docs/evidence/f5/fq_kill_power_negative_edge_seed20261008.json` (seed 20261008, 2000 replicates, n_max 2000, about 24 takes by 2027-01-25). The script was domain-reviewed and is CORRECT.

| δ | p_kill by kill date | p_kill by n_max | median n | clipped mean Y |
|---|---|---|---|---|
| 0 | 0 | 0.29 | — | −0.0065 |
| −0.04 | 0 | 0.9995 | 539 | −0.018 |
| −0.08 | 0 | 1.0 | 286 | −0.029 |
| −0.16 | 0 | 1.0 | 160 | −0.050 |

**Rulings:**
- **KILL cannot protect capital before 2027-01-25.** About 24 takes are available, and the first look is at 20. Even at δ = −0.16, the median kill needs about 160 takes (≈ 640 days). No pre-January decision may cite KILL as loss protection.
- **Pre-January loss control.** The only pre-January loss controls are the F6 floor (expected `unreachable_veto`) and the two operator caps. Every arming record must therefore state the worst-case loss as the daily budget × the days armed. The value is the operator's; the statement of it is mandatory.
- **The δ = 0 result of 0.29 is a design property.** It is not a defect. The x_max = 4 clip binds when BE < 0.2, so BE-fair outcomes have a negative clipped mean, and the F7B-R22 premise E[Y_clipped] ≥ 0 does not hold. The frozen KILL will eventually kill a family that is exactly break-even at low BE. That is a late, conservative failure, not a safety failure.
- **The r2-verification prediction was wrong.** It said "δ = 0 reproduces p_kill ≈ 0". The script's docstrings that repeat it are corrected in the M10 merge.
