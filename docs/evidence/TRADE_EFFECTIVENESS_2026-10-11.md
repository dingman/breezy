# Trade effectiveness audit — 2026-10-11

Scope: every LIVE real-money Polymarket.us fill, 2026-09-04 .. 2026-10-11. Read-only audit (four parallel seams + coordinator re-score).

## Sources
- Fills: `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, table `state`, keys `exec/polymarket_us/fill/*` (34 rows, all BUY, qty 1, IOC).
- Truth: `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (NWS CLI finals; PM.us settles on NWS). Venue-side settlement NOT cross-checked.
- Official ROI: `derived/PRIVATE_portfolio_roi_2026-09-30.json` (9 fills, −0.46, ROI −18.7%); `derived/portfolio_roi.log` (10-01..10-08 skipped, 10-09..10-10 NO_INPUT).
- Funnel: `derived/decision_funnel/decision_funnel_2026-10-0{1..9}.json`, `…10-10.json`.
- Node logs: `logs/breezy-trade-2026*.log` (submit/fill/deny/AMBIGUOUS lines).

## Realized P&L (coordinator re-score of instrument band vs CLI tmax on the INSTRUMENT climate day)
| Period | Fills | Wins | Net | Notes |
|---|---|---|---|---|
| Sep (crh residual/cont/v4) | 9 | 2 | −0.46 | equals official 09-30 artifact |
| Oct (`pm_us_crh_fq_v1`) | 25 | 0 | −4.17 | no bot artifact scores these |
| Total | 34 | 2 (5.9%) | −4.63 | cost 6.36, fees 0.27, ROI −73% |

- Both wins are NO-side longshot entries: 09-15 MIA NO `gte92lt93` @0.09 (+0.91), 09-22 MDW NO `gte62lt63` @0.12 (+0.87). NO-side 3 fills / 2 wins / +1.65; YES-side 31 fills / 0 wins.
- FQ misses are directional and boundary: LAX 10-03/10-04 bought 91–96 °F, CLI 102 °F; MDW 61–64 °F bought, CLI 65 °F. Five FQ fills lost by exactly 1 °F: MIA 10-03 `gte88lt89` (87), MIA 10-03 `gte86lt87` (87), SFO 10-04 `lt83` (83), MIA 10-05 `gte89lt90` (90), SFO 10-06 `gte81lt82` (80). All 25 FQ fills are YES. Regenerate with the recipe below.
- Rejected seam result: one seam reported 4 wins / −2.63; it keyed outcomes to the ORDER date, not the instrument climate day. Re-score on instrument day refutes it.

## Statistical edge (per family, live only)
`pm_us_crh_cont` 3/0; `pm_us_crh_v4` 3/1 (Wilson 95% [.061,.792]); `pm_us_crh_v2` 0; `pm_us_crh_fq_v1` 25/0 (unscored by the bot); `pm_us_crh_rest_v5` shadow gate FAIL. No family demonstrates edge. M1-v3 untouched (read-once ≥ 12-07).

## Execution quality
Slippage vs IOC limit 0 on 34/34; no partials; submit→fill ~0.15–0.46 s; fill rate 34/43 submits. Fees 0.8 c/contract, matching θ=0.06 pre-09-17 and 0.0695 after. Execution cost ≈ 6% of gross loss — losses are selection, not cost. Operational cost: AMBIGUOUS latches ~6 h (09-11) and ~27 h (09-23→24), 2.7 h (10-02).

## Current state (10-11)
Not armed: `fq-v1-halt-orders-off.conf` drop-in (`BREEZY_ORDERS_ENABLED=0`); A1 halt `pm_us_crh_v4`; FQ halt `pm_us_crh_fq_v1`. Last fill 2026-10-05T19:31:03Z. No decision reached pricing since 10-06.

## Gaps
Decision-time ask not persisted (slippage vs quote unauditable); venue settlement not cross-checked; two AMBIGUOUS orders (09-05 SFO, 09-23 MIA) lack a terminal record; refusal counterfactual outcomes unmeasured.

## Re-score recipe
Parse `instrumentId` `tc-temp-<stn>high-<YYYY-MM-DD>-<band>f[^no]`; band `gteLltH` ⇒ YES iff L ≤ tmax < H; `ltH` ⇒ tmax < H; `^no` inverts; P&L = payout − cumulativeCost − cumulativeFee.

Backlog: TE-1..TE-3 in `docs/core/PROGRESS.md`; plans in `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/`.
