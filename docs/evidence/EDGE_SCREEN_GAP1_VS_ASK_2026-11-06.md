# EDGE SCREEN 2026-11-06 — GAP-1 D0 champion blend vs Polymarket.us ask
SCREEN — not confirmatory; upper bound (zero slippage)
QUESTION: does the GAP-1 D0 champion blend have positive expectancy after fees as a YES taker against the Polymarket.us ask?
RESULT: UNANSWERABLE FROM DATA ON DISK — GAP-1 OOF probabilities cover 2021-01-01..2026-06-30, the quote tape starts 2026-08-30; 0 station-days overlap; 0 takes; the wiring self-check on SFO 2026-09-01 found a snapshot (ask 0.01, θ 0.06), so this is a data gap, not a bug; the repo encodes it (`blend_veto_descriptive.TAPE_START = 2026-08-30`, `PreTapeMarketPriceError`).
Reproduce: `docs/evidence/edge_screen_2026-11-06/gap1_edge_screen.py`; machine output `docs/evidence/edge_screen_2026-11-06/results.json`.
NEXT: forward-scoring the frozen blend on tape days (GAP-3) is running; its result will be appended as a second section.

## PRIOR EVIDENCE SUMMARY
- Live taker: 34 fills, ROI −41% on cost — `docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- P2 FQ v1 YES taker: −$0.0528/take, CI [−0.091, −0.008] — `docs/evidence/P2_NBP_VS_ASK_MURPHY_2026-10-22.md`
- M1 market scan: no cell survives; median MDE 19.8¢ at 26 days — `docs/evidence/M1_MARKET_SCAN_2026-10-04.md`
- Card A/E: KILL — `docs/evidence/STRAT_DESIGN_2026-10-31/` (card_a_census.md, card_e_cli_vs_twc.md)
- Forecast programme closed, "skill is in the price" — `docs/evidence/RULING_forecast_edge_programme_closes_2026-09-20.md`
- P4 maker: 0 fills since arming 10-24 — `docs/core/PROGRESS.md` (Standing verdicts)
- Zero fills of any kind since 2026-10-05 — `docs/core/PROGRESS.md` (Standing verdicts; not independently re-derived here)

---

# GAP-1 D0 champion vs Polymarket.us YES ask, net of fee
**SCREEN -- not confirmatory; upper bound (zero slippage).** Run 2026-11-05T02:38Z under
`systemd-run --user` (unit breezy-edge-screen-gap1-1793846303, 1.5 s, 202 MB peak). Script:
`gap1_edge_screen.py` (this dir); machine output `results.json`; log `run.log`.

## Answer
**Not answerable from the data on disk: the join is EMPTY (n = 0).** The GAP-1 out-of-fold
probabilities cover climate days 2021-01-01..2026-06-30; the Polymarket.us depth tape covers
climate days 2026-08-30..2026-11-05. Zero station-days are in both. No ask exists for any OOF
row, so no edge, P&L, hit rate, CI, mean(p - a) or calibration-vs-ask table can be computed.
Every R1/R2/R3 cell is n = 0 (CI undefined). Nothing was interpolated or extrapolated.

## Row counts at each join step (all from results.json "counts")

| step | n |
|---|---|
| oof_rows.jsonl rows (excl. header) | 15613 |
| horizon == D0 | 7824 |
| D0 rows with arm M3 (mu, sigma, nu) and f.jsonl anchor_ns | 7824 (0 missing, 0 duplicate) |
| OOF station-days with NWS CLI FINAL truth (settlement_truth.csv) | 7824 / 7824; observed_f == cli tmax_f on 7824; conflicts 0 |
| depth-tape instrument dirs | 2248 (1586 HIGH rungs on LAX/MDW/MIA/SFO; 662 non-HIGH/other/NO-leg) |
| tape station-days (HIGH, 4 stations) | 265, climate days 2026-08-30..2026-11-05 |
| station-days in BOTH OOF and tape | **0** |
| rung dirs read / joined rows / takes | 0 / 0 / 0 |

OOF D0 climate-day range: 2021-01-01..2026-06-30 (1968 distinct days, 4 stations).

## Decision rules (pre-stated, not swept) -- all empty
| rule | edge threshold | n takes | n station-days | hit rate | mean P&L/take | total P&L | 95% CI (station-day cluster, B=10000, seed 20260904) |
|---|---|---|---|---|---|---|---|
| R1 | > 0 | 0 | 0 | n/a | n/a | n/a | undefined |
| R2 | > 0.03 | 0 | 0 | n/a | n/a | n/a | undefined |
| R3 | > 0.05 | 0 | 0 | n/a | n/a | n/a | undefined |

Model-free mean(p - a): n = 0, undefined. 10-bin calibration table: every bin n = 0.

## Exact gating-instant rule (as coded)
The GAP-1 D0 forecast anchor is 10:00 LST on D0 (`f.jsonl.anchor_ns`, fixed standard time), which
is LATER than P2's 16:50Z-on-D-1 instant, so P2's instant is NOT used: the ask is the L0
`ask_price_0` of the first Depth10 snapshot at or after `anchor_ns` inside a closed 10-minute
window (`p2_nbp_ask_murphy.first_snapshot_in_window`), else the rung is dropped. Rung p =
F(hi+0.5) - F(lo-0.5) under the arm's Student-t (`student_t_cdf`), inclusive [A,B] from
`classify_directory`. Fee = `fee_on_ask(ask, taker_fee_coefficient_as_of(snapshot ts))`
(0.06 before 2026-09-17, 0.0695 after; unpinned -> drop). P&L = outcome - a - fee, qty 1.

## Fields used
oof_rows.jsonl: station, climate_day, horizon, arm_predictions.M3.{mu,sigma,nu}, observed_f
(cross-check). f.jsonl: station, climate_day, horizon, anchor_ns. settlement_truth.csv: station,
climate_day, is_final, tmax_f. Champion = arm M3 (highest-level LAMP blend, PASS cell M3:D0);
M1/M2 were not evaluated because no row reaches the join.

## Limitations
Zero slippage; qty 1 at L0; YES side only; no NO-side book; stations LAX/MDW/MIA/SFO (no NYC);
and, decisively, no temporal overlap between OOF forecasts and the venue tape. The repo already
encodes this gap (`blend_veto_descriptive.TAPE_START = 2026-08-30`, `PreTapeMarketPriceError`).
Answering the question needs GAP-1 champion forecasts for tape days (>= 2026-08-30) that are
genuinely out-of-sample (a frozen fit scored forward), which is GAP-3's forward test, not a
re-read of the existing OOF file. Mechanics self-check (not a result, `selfcheck.log`): one real SFO
2026-09-01 rung through the identical read_rung_tape -> first_snapshot_in_window -> fee path found a
snapshot (18:00:16Z, ask 0.01, theta 0.06), so the empty join is a data gap, not a wiring defect.
