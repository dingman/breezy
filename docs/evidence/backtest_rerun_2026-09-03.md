# Backtest rerun — 2026-09-03 (plumbing-verification role; NOT a deployment signal)

Command: `.venv/bin/python scripts/analysis/run_weather_strategy_backtests.py --output-dir <dir>`
at `ee952ae`. Report: `~/.local/share/breezy/derived/strategy-backtests/weather_strategy_backtests_20260903T183651+0000.json`
(+ `.log`). Wall time ~35 min for 36 runs (2 conditions × 3 strategies × 6 settlement scenarios).

**Why it was run.** The operator's 09-03 loop mandate names a 75% backtest win-rate stop gate.
The gate is unsatisfiable on this venue (`docs/core/PROGRAMME_PATH.md`; prices are forward-only,
addressable winner notional ~$0.57 across the capture), so this run is the honest measurement
in the mandate's own terms, not an attempt to reach it.

**Defects found and fixed before it could run** (`1ed4985`, `ee952ae`): the runner raised
`KeyError: 'SFO'` because its constructed-forecast table covers NYC/MIA only while the tape
now carries five stations. Fix: exclude stations without a constructed input, print and
record the exclusion in the JSON (`excluded_stations`, `excluded_instrument_ids`,
`exclusion_reason`); no forecast was fabricated (L-17). 38 instruments (LAX/MDW/SFO)
excluded; 28 NYC/MIA instruments run. Docstring NYC preliminary corrected 78→79
(`backtest_roi_measurement_2026-08-31.md:55`).

**Result, as printed by the harness (`realistic` condition, fees + L2 depth + liquidity
consumption; latency NOT modelled — a known overstatement of reaction speed):**

| strategy | real-provenance scenario | orders | fills | realized P&L | note |
|---|---|---|---|---|---|
| calibration_mean_reversion | primary_real_preliminary | 0 | 0 | n/a | ALL REFUSED `shorts_disabled=2` |
| forecast_mispricing | primary_real_preliminary | 2 | 2 | **−$2.05** (−104.87% of $1.95 at risk) | BUY16@0.120, settled 0 |
| forecast_revision | primary_real_preliminary | 0 | 0 | n/a | ALL REFUSED `shorts_disabled=860` |

The five `sweep_*` scenarios substitute CONSTRUCTED observations and are plumbing checks, not
evidence; the one positive row (`sweep_nyc_82f`, +$14.24) is a counterfactual observation.
`naive` condition (no depth/fee realism) is reported in the JSON for the BL-4 comparison only.

**Gate reading.** Real-provenance trades: 1. Wins: 0. The harness prints no win rate. The
forecast family is KILLED (`grok_forecast_family_verdict_2026-09-02.md`); this rerun changes
nothing about that verdict and must not be quoted for or against capital deployment
(stop-gate memory, 2026-09-01).
