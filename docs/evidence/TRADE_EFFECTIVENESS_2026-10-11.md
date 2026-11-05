# Trade effectiveness audit — 2026-10-11

Scope: every LIVE real-money Polymarket.us fill, 2026-09-04 .. 2026-10-11. Read-only audit (four parallel seams + coordinator re-score).

## Sources
- Fills: `~/.local/share/breezy/state/exec_polymarket_us.sqlite`, table `state`, keys `exec/polymarket_us/fill/*` (34 rows, all BUY, qty 1, IOC).
- Truth: `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (NWS CLI finals; PM.us settles on NWS). Venue-side settlement NOT cross-checked.
- Official ROI: `derived/PRIVATE_portfolio_roi_2026-09-30.json` (9 fills, −0.46, ROI −18.7%); `derived/portfolio_roi.log` (10-01..10-08 skipped, 10-09..10-10 NO_INPUT).
- Funnel: `derived/decision_funnel/decision_funnel_2026-10-0{1..9}.json`, `…10-10.json`.
- Node logs: `logs/breezy-trade-2026*.log` (submit/fill/deny/AMBIGUOUS lines).

## CORRECTION (2026-10-11, same day) — band semantics
The first version of this document scored `gte{A}lt{B}f` as half-open [A, B). That is WRONG. The settlement-grade venue rule is the INCLUSIVE interval [A, B] (a 2 °F rung titled "A° to B°"): `docs/evidence/venue/polymarket_us/THRESHOLD_SEMANTICS_2026-08-25.md`, `symbology.slug_closed_interval`, `labeling.instrument_facts.bucket_facts_from_instrument_id`. `lt{B}` means tmax ≤ B−1, and `gte{A}` means tmax ≥ A. The bot's own scorer was right. The seam that this document "rejected" (4 wins / −2.63) was correct. The superseded figures were 2 wins / −4.63, FQ 0/25 / −4.17, and NO-side 2/3.

## Realized P&L (re-score of the instrument band, inclusive [A,B], against CLI tmax on the INSTRUMENT climate day)
| Period | Fills | Wins | Net | Notes |
|---|---|---|---|---|
| Sep (crh residual/cont/v4) | 9 | 2 | −0.46 | equals the official 09-30 artifact, fill for fill |
| Oct (`pm_us_crh_fq_v1`) | 25 | 2 | −2.17 | no bot artifact scores these |
| Total | 34 | 4 (11.8%) | −2.63 | cost 6.36, fees 0.27, ROI −41% on cost |

- Wins: 09-13 MIA YES `gte91lt92` @0.70 (tmax 92, +0.30); 09-22 MDW NO `gte62lt63` @0.12 (tmax 64, +0.87); 10-03 MIA YES `gte86lt87` @0.11 (tmax 87, +0.88); 10-05 MIA YES `gte89lt90` @0.48 (tmax 90, +0.50).
- NO side: 3 fills / 1 win / +0.65 (09-15 MIA NO `gte92lt93` lost: tmax 93 is inside [92,93]). YES side: 31 fills / 3 wins.
- FQ misses include the LAX 10-03/10-04 heat bust (bought 91–96 °F, CLI 102 °F) and MDW 10-02 (bought 61–64 °F, CLI 65 °F). Edge-distance counts must be recomputed with the inclusive rule. The earlier "five 1 °F losses" list used the wrong rule and is withdrawn.

## Statistical edge (per family, live only)
`pm_us_crh_cont` 3/0; `pm_us_crh_v4` 3/1 (Wilson 95% [.061,.792]); `pm_us_crh_v2` 0; `pm_us_crh_fq_v1` 25/2 (unscored by the bot); `pm_us_crh_rest_v5` shadow gate FAIL. No family demonstrates edge. M1-v3 untouched (read-once ≥ 12-07).

## Execution quality
Slippage vs IOC limit 0 on 34/34; no partials; submit→fill ~0.15–0.46 s; fill rate 34/43 submits. Fees 0.8 c/contract, matching θ=0.06 pre-09-17 and 0.0695 after. Fees 0.27 ≈ 10% of the −2.63 net loss — losses are selection, not cost. Operational cost: AMBIGUOUS latches ~6 h (09-11) and ~27 h (09-23→24), 2.7 h (10-02).

## Current state (10-11)
Not armed: `fq-v1-halt-orders-off.conf` drop-in (`BREEZY_ORDERS_ENABLED=0`); A1 halt `pm_us_crh_v4`; FQ halt `pm_us_crh_fq_v1`. Last fill 2026-10-05T19:31:03Z. No decision reached pricing since 10-06.

## Gaps
Decision-time ask not persisted (slippage vs quote unauditable); venue settlement not cross-checked; two AMBIGUOUS orders (09-05 SFO, 09-23 MIA) lack a terminal record; refusal counterfactual outcomes unmeasured.

## Re-score recipe
Parse `instrumentId` `tc-temp-<stn>high-<YYYY-MM-DD>-<band>f[^no]`; band `gteLltH` ⇒ YES iff L ≤ tmax ≤ H (inclusive); `ltH` ⇒ tmax < H; `^no` inverts; P&L = payout − cumulativeCost − cumulativeFee. Band rule: use `bucket_facts_from_instrument_id`; never hand-roll it.

Backlog: TE-1..TE-3 in `docs/core/PROGRESS.md`; plans in `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/`.
