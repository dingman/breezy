# M1 model-free market calibration scan: 2026-10-04

**Status: VALID. Screening only (FQ-R14). Not nomination evidence.**

## Inputs and outputs
- **Code:** `scripts/analysis/market_calibration_scan.py`, branch `backlog/fq-m1-scan-2026-10-04`, commits b379fd18 and 5c1e78cc.
- **Raw output:** `docs/evidence/m1/market_calibration_scan_v2.{json,md}`.
- **Run:** under systemd-run with MemoryMax=4G, read-only, against the converted `data/` catalog.
- **Data:** 3977 observations over 26 days. Truth is FINAL through 09-28, with join coverage 1.000 inside that horizon.

## Question
Does Polymarket.us misprice weather rungs systematically, independent of any model?
- **Trade simulated:** buy YES or NO at the executable Depth10 ask, then hold to settlement.
- **Measure:** excess = settle − (ask + θ·p·(1−p)), with θ taken from `hypothesis_ledger.EVIDENCED_FEE_THETA` (0.0695).
- **Cells:** window (D-1 18Z, D 12Z, D 17Z, UTC) × side × ask decile.
- **Statistics:** day-block bootstrap, Bonferroni over 35 cells, White's reality check and Hansen's SPA.

## Result
**No cell survives.**
- Bonferroni: none.
- Reality-check p = 0.349. SPA p = 0.416.
- Best cell: D_17Z YES ask 0.3–0.4, n=49 over 22 days, +14.2¢, CI [+1.0, +29.6]¢, Bonferroni p = 0.58.

**Power: the null is NOT "no edge".**
- The median per-cell MDE (80% power, Bonferroni) is **19.8¢**. Mid-ask cells sit at 19–40¢.
- A realistic 3–8¢ edge is invisible at 26 days. It would need about 15× the data.

**Negative cells are informative (reliable losers, consistent with the favourite–longshot bias):**

| Cell | Excess | CI |
|---|---|---|
| YES 0.0–0.1, D_17Z | −1.7¢ | [−2.4, −0.8] |
| YES 0.0–0.1, D-1_18Z | −2.3¢ | CI upper −0.5 |
| YES 0.0–0.1, D_12Z | −1.9¢ | CI upper −0.1 |
| YES 0.4–0.5, D_12Z | −19.6¢ | [−29.6, −10.2] |
| YES 0.5–0.6, D_17Z | −19.4¢ | CI upper −4.3 |

- These are not Bonferroni-significant as edges, because the test is one-sided for edge > 0. Still, every CI lies entirely below 0. **Buying cheap YES is a reliable loser.**
- That matches the FQ v1 failure. Its takes were low-ask YES rungs, where the model disagreed most with the market.

## Caveats (from the reviews: prediction-market-reviewer SOUND-WITH-CAVEATS, python-reviewer fixes applied)
- **Optimistic ask.** The ask is the top level at size ≥ 1, with no slippage or fill model, so a positive cell is an upper bound.
- **Fixed UTC windows.** D_17Z is 09:00 PST but 12:00 EST, so the windows are not local-time equivalent.
- **Fee before 09-17.** θ was 0.06 before 2026-09-17T17:00Z (`fees.py`). The scan uses 0.0695 flat, which is pessimistic by under 0.3¢ on those days. That is immaterial at this MDE.
- **NO-side selection.** NO observations need a YES bid level, so 436 were skipped. Selection is on an observable, not a leak.
- **Unrecorded windows.** 326 windows have no Depth10 row (unlisted or not recorded).
- **Few clusters.** 26 clusters mean percentile CIs under-cover. That inflates false positives and cannot hide an edge.
- **File length.** The script is 857 lines, over the 800 guideline. A split is a follow-up (PROGRESS).

## Decision
- **Promote nothing; trade nothing.**
- **Re-run** with the same pre-registered windows and bins once truth extends. The MDE shrinks as 1/√days, so halving it needs about 4× the days (~100+).
- **The D_17Z YES 0.3–0.4 cell** is a hypothesis to freeze before forward days (FQ-R14), never a trade rule.
- **The reliable-loser cells are a filter input for any v2 take rule.** No YES take at an ask below 0.10 unless the model is independently validated there.
