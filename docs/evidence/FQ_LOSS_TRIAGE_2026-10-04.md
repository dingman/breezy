# FQ loss triage: 2026-10-04 (coordinator synthesis)

**Operator directive (10-04 about 20:20Z):** losing live trades were observed, and the strategy must be continually optimised toward identifying and executing winning trades.

**Decision (coordinator):** halt new entries on `pm_us_crh_fq_v1`. Open positions settle on their own, because FQ has no exit path. The resume bar and the repair plan are in `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/`.

## Evidence (three read-only investigations; scratch in the session scratchpad `loss-triage/`)

### Settled results
**FQ, settled (proxy truth; official CLI truth ends 09-28):**
- n=11 fills, which is 5 independent station-days. 1 win, net −0.64, ROI −39%.
- Including 3 locked 10-04 losses: n=14, 1 win, net −1.17.

**Pre-FQ crh live fills:** 9 fills, net −0.54 after fees, ROI −18.7%.

### Model against market
- Model Brier on the trades it took was **0.075**; the market ask's Brier on the same trades was **0.048**.
- Mean p_hat was 0.287 against a mean ask of 0.142.
- The model expected 3.15 wins; 1 occurred.

### Causes
- **The model is overconfident.** NBM published spreads of about 2 °F at D+1, while realised misses were 3–8 °F. The `docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md` gates G2.0–G2.3 FAILED. The take rule selects the largest model/market disagreements.
- **Correlated stacking.** 2–3 mutually exclusive rungs were taken per station-day.

### Ruled out
- Fee, side and sizing code.
- fee θ drift: θ was 0.0695 on every fill.
- The latency race.

### LAX 10-05 "<97" (p_hat 0.992, ask 0.64)
- **Verdict: GENUINE, no LEAK and no INPUT_DEFECT.** The bot's own code recomputes the value exactly from the NBM 13Z cycle, which was published 44 s before the take.
- **The real issue:** NBM was cold and tight in a heat regime: +4.4 °F error on 10-03 and +5.4 °F on 10-04.

### Controls
- There was no P&L, drawdown or calibration stop. The only automatic stop was fee drift.
- The PREREG tally cannot run on FQ, because no boundary artefact exists.
- `family_tally_v2`, `score_live_trials` and `portfolio_roi` all SKIP FQ.
- The position monitor saw 1 of 20 fills.
- `set_family_halt_cli` refused FQ. Fixed at `ce0c07bb`/`04eaa013`.
- The node holds the submit-intent flock for its whole run, so the halt can only be set in the node-down gap (about 16:40–16:50Z).
