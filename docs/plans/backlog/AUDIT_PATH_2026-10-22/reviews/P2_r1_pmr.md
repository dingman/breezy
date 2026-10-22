# P2 r1 review — prediction-market-reviewer

**VERDICT: REQUEST-CHANGES.** The statistic and thresholds make FAIL mostly a power outcome, and the deletion rests on a D0 test of a D+1 strategy. I did not re-verify code paths. I checked the plan text against the WP-7b ruling only.

**Required changes**

1. **FAIL is currently "not significantly positive", which is not "no edge".**
   - The PASS bar is a CI lower bound ≥ +0.005.
   - WP-7b CIs were ±0.02–0.03 at 12 clusters (mid) and 64 clusters (ask). With roughly 30–60 clusters here, a PASS needs a true D of about +0.02 or more. Almost any realistic outcome therefore lands in FAIL.
   - The ruling's own section 7 says an underpowered non-detection was previously retracted.
   - Fix: split the outcomes into three.
     - PASS: lower bound ≥ +0.005.
     - FAIL: upper bound < 0 (or below a stated small positive, e.g. +0.005).
     - INCONCLUSIVE: anything else, so keep the code.
   - Only FAIL may trigger deletion, and the deletion list should be a recommendation, not a mandate.

2. **Resolution difference is not the taker decision statistic.**
   - A forecaster can have lower resolution and still win on local disagreements after fees.
   - The data is already in hand. Add realized taker P&L per event: outcome − ask − fee, with the same rule FQ used and a station-day-clustered CI.
   - This is about 10 lines. It is not out of scope, and "No ask-based gate" should be reversed.
   - Make FAIL require both D_res and the P&L CI to be unfavorable.
   - Caveat for the NO side: the bid side is thin, so P&L on NO takes is unreliable. Report YES-take P&L as primary and NO takes separately.

3. **The mid is the weak market forecaster, and the plan chooses it exclusively.**
   - WP-7b's mid set failed binning stability and produced 12 clusters. Its ask set (64 clusters) carried the conclusion.
   - Requiring both L0 sides selects liquid, near-the-money rungs.
   - Bids at or near a 1-cent placeholder bias the mid low.
   - Fix: score ask as a co-primary set, as WP-7b did. Require the bid to exceed a stated floor for the mid set. Report the cluster count for each set.

4. **D0 evidence does not justify deleting a D+1 strategy.**
   - At 09:00 LST on D, the market already reflects overnight and morning obs. FQ's edge, if any, was at D-1, when the market is less informed.
   - The plan's claim that D0 gives the forecast its strongest cycle ignores that the market is also better informed then.
   - Fix: add a D-1 instant, e.g. 09:00 LST on D-1. `VectorChain.at(t)` already supports this. Gate on it, or at least require FAIL at D-1 before any deletion.

5. **Cluster realism and correlation.**
   - The maximum is about 44 days × 4 stations = 176 station-days. WP-7b got 24 of 84 mid days, so expect roughly 40–60 here.
   - Station-day clusters ignore same-day cross-station correlation, since weather regimes are shared. Add a climate-day-clustered CI and gate on the wider of the two.
   - The 30-cluster floor counts station-days that may contribute one rung each. Also require a minimum event count.

6. **The "either instant passes" rule is not a sound multiple-comparison control, and (b) is effectively dead.**
   - Two looks at a one-sided 95% bound roughly double the false-pass rate.
   - Instant (b) needs a crossing day with a two-sided mid and at least 30 clusters. That is very unlikely out of about 176 station-days.
   - Fix: gate on one primary instant (D-1 or D0, declared up front). Treat the other as report-only.

**Cuts (over-engineering)**
- Drop instant (b) entirely. This removes the conditioned-NBP masses, `RunningExtremeAccumulator`, METAR ingestion and the tgroup filter. They are a large complexity cost for an event set that cannot gate.
- Drop the 5-bin sensitivity, the full-partition subset and the W−C residual reporting. Keep one reconstruction check.
- The null control is trivially true, so drop it. Keep the identity, positive and live-parity controls.
- The systemd, heartbeat and Monitor scaffolding is reasonable for a 1–4 hour job. Keep it only if the job really takes that long.

**Minor**
- Spending the sealed S2 holdout (days from 2026-07-01) is acknowledged in the plan and acceptable. State it in the evidence file.
- Multiple-comparison control on the reported-only items is unnecessary once they are non-gating.

**Confidence: 80.** Items 1–4 are reasoning from the plan text and the ruling's numbers. I did not check the code or the tape coverage.