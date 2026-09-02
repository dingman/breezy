# Breezy — the programme path to a real-money ROI verdict

Extracted from `PROGRESS.md` on 2026-09-02 to keep that file inside its
size gate. This is the PLAN and its standing constraints; `PROGRESS.md`
carries OPEN state and links here. Revised 2026-09-01 unless noted.

**The stop gate as written is UNSATISFIABLE by backtest on this venue.** ROI is
a function of fill prices; price history is forward-only, so no weather or
forecast data produces a historical ROI. Both P2 probes: a forecast archive
yields a CALIBRATION dataset, not a backtest.
Measured: total addressable notional at any eventually-winning rung is **$0.574**
(NEGATIVE after fees; refused by `min_liquidity_contracts=25`). Power: sigma/mu
~ 8, so n ~ 300 station-days (~60 clean days at 5 stations) to clear break-even.

**Ordered path to a real-money ROI verdict (revised 2026-09-01):**
(2) K1 gates the calibration family BEFORE any forecast build —
`docs/evidence/k1_cheap_open_2026-09-01.md`. n=0; 30 D+1 entries captured
(09-01) enter the population once their CLI goes FINAL — missing is elapsed
time, not code. Viable at ask<=0.03 in ~20d / <=0.05 in ~9d; the 0.01
tick needs ~359d, so no plan may wait on it. Re-runs daily, unattended; (3) capture supervised to 2026-10-01 (D+1 book needs the recorder up before
local midnight); (4) execute the EXEC SPINE
(`docs/plans/EXEC_SPINE_2026-09-01.md`; R-1..R-4, W, R-6a landed). Next:
R-6c/d/e local; R-5R + R-6.5P VENUE-GATED (private backend 500/503, auth
proven); R-4P-2 (cursor pagination) open. Plan
`docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`; (5) forecast ingest (`docs/plans/forecast_ingest_2026-09-01.md`)
HELD until K1 reports; (6) accumulate ~300 station-days; (7) settle CAPACITY.
Backtest stays REFUTATION + plumbing only: offer survival is a counterfactual
about the venue's reaction to OUR order, recorded nowhere.
