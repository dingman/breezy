# RULING — NBP probabilistic family: PM.us confirmatory leg infeasible → §6 node 4 (2026-09-30)

**Status:** DECIDED by the coordinator under the operator's standing pre-authorisation, after two blind adversarial peer reviews. This is a zero-look record: no holdout row was opened, and no α or slot is spent.

## Trigger

Ruling `RULING_forecast_nbp_reopen_2026-09-29.md` §12 **A-3** fixes three things:
- σ_d is the **validation-split**, station-day-clustered SD of the per-station-day mean paired Brier difference (M2 − M1);
- n_min = ⌈((z₀.₉₇₅ + z₀.₈)·σ_d / 0.0152)²⌉;
- the ceiling is **520** final station-days.

A-3 says: "If the recomputed n_min exceeds 520 … the PM.us confirmatory leg is then declared infeasible before the KILL and routes to plan §6 node 4 **immediately**, with no waiting for accrual."

## Measurement

The validate stage covered 2025-01-01..2026-05-03, pre-holdout. The code is feat/data-capture-and-risk at SL-8f (common-bin D_res, validation-selected correction and recalibration). The evidence note is `NBP_S2_VALIDATE_RESULT_2026-09-30.md`.

| Quantity | Value |
|---|---|
| σ_d (point) | 0.1320 |
| σ_d 95% CI (station-day cluster bootstrap, B=200) | [0.1274, 0.1378] |
| n_min (point) | 592 |
| n_min range | [552, 645], wholly > 520 |
| σ_d needed for n_min ≤ 520 | ≤ 0.1237, below the CI floor |
| Fit | all versions converged; κ = ∞ (full pooling) |
| Selected G2.0 correction | linear LST day-length (validation CRPS 1.553 vs none 1.614) |
| Selected recalibration | none (validation Brier 0.2113) |

The pre-holdout gate diagnostics are in-sample by plan design, so they are not the S2 verdict:
- G2.0 FAIL (March −0.58 °F);
- G2.0a PASS;
- G2.1 FAIL (0.4–0.5 bucket, observed 0.584 vs predicted 0.45);
- G2.2 d_res(M2−M1) −0.0034 [−0.0081, +0.0013];
- G2.3 d_res(M2−M0) +0.0038 [−0.0005, +0.0087], below X = 0.0152.

## Peer review (blind, adversarial)

- **mle-reviewer (Claude): SOUND-WITH-CAVEATS.** σ_d follows A-3 exactly. In-sample estimation biases σ_d **downward**, so the true value is more likely higher, which strengthens infeasibility. No bug flips the verdict. A-3 applies at this stage.
- **Grok Build (read-only): SOUND-WITH-CAVEATS.** It re-derived n_min 592 and the range [552, 645] exactly. No bug found. It clarifies that the node-4 routing is the *ruling's* A-3 consequence and not a plan-§6 trigger sentence. The later weather-only S2 still runs.
- A Codex review was launched but hit its usage limit before returning; the trigger is recorded here.

## Caveats (non-blocking, tracked as follow-ups)

1. The σ_d CI uses B=200, while the plan's gate convention is 2,000 draws.
2. The JSON `power` block should carry the in-sample label.
3. Only the forecast-centred mid rung is scored per event.
4. M1's own G2.0–G2.3 plus the independent D_res(M1−M0) were not run, so the M1 fallback is unevaluated. An M1 failure would route to §6 node 2 and not to registration.
5. March G2.0 rejects by 0.00016 under the Holm threshold. The printed family size (18) includes an untested stratum.

## Consequences (plan §6 node 4 + A-3)

- **Declared:** the PM.us confirmatory leg of H-FC-NBP-EV-2026-09 is infeasible before the 2027-01-25 KILL. S3b will not register this family on PM.us.
- **The holdout stays sealed.** S2 still runs as weather-only skill evidence when final holdout n ≥ n_min. It is not an accrual wait for PM.us.
- **Keep L (SL-15) running.** Its unit files are in the repo and not yet installed.
- **Finish S4-infra as a K-2 asset** (Kalshi, 24 cities, with a per-station TWC-vs-CLI reconciliation first [RA-13:60]).
- **Revival path:** carry the model to K-2, where 24 cities multiply n (plan §4.x, line ~416). GEFS + EMOS remains the one independent-information lever, and only through a new S0-class ruling.
- **No live trading change.** A1 halt stays SET, and the strategy stays shadow-only and DRAFT_NOT_REGISTERED.
