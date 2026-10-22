# P2 NBP vs YES ask — Murphy resolution and taker P&L

Run date: 2026-10-22 (UTC). Elapsed seconds: 372.419.
Plan: `docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md`, r2.1 amendments overriding r2.
Thresholds were not moved after the tape was read.

## Ranges

- Scored climate days: 2026-09-03 through 2026-10-13.
- Fit range of the sealed FQ v1 artefact: 2021-01-01..2026-06-30 (`DEFAULT_SPLITS`). The JSON has no fit-date keys; this is the plan's range.
- The scored range spends days from the sealed S2 holdout (from 2026-07-01).
- Stations: LAX, MDW, MIA, SFO. No NYC. No NBP re-derive after 2026-10-12. No refit.
- Calibration sha256: `9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e`.

## Gate

The gating instant is the first Depth10 snapshot at or after 16:50:00Z on LST date D−1, inside a closed 10-minute window, else the rung is dropped. One instant only. The forecast vector is the newest pinned-cycle vector with `available_at_ns` at or before that snapshot's own timestamp, which is also `evaluate`'s `now_ns` and the cash-fee timestamp. The 19Z cycle of D−1 cannot become available inside that window, so the vector matches a lookup pinned at 16:50:00Z unless a later cycle was already visible. Rows whose snapshot vector was not the 16:50:00Z vector: 0.

`evaluate` is the production FQ v1 rule: `permit_covers=True`, the default `LadderEvConfig()` (slippage floor 0.01), a fresh latch per station-day, YES before NO. The hurdle uses `float(θ)` from `taker_fee_coefficient_as_of` of the snapshot. Cash P&L uses `θ·price·(1−price)` rounded half-even to the cent. θ is 0.06 before 2026-09-17T00:00Z, refused until 17:00Z that day, then 0.0695. Fee-unpinned ASK events stay in D_res and are not takes: 10.

Qty-1 P&L at the L0 ask ignores depth, so it is optimistic, which leans toward PASS.

## Census

Population (classified HIGH rung directories on the four stations, climate day in the scored range): 984.
ASK events: 946. Drops: 38. ASK + drops = population.
Scored by station: LAX 238 | MDW 237 | MIA 236 | SFO 235.
Truth keys excluded for conflicting `tmax_f` (anywhere in the file, not only this range): 0.

| reason | LAX | MDW | MIA | SFO | total |
|---|---|---|---|---|---|
| duplicate_rung | 0 | 0 | 0 | 0 | 0 |
| no_vector | 0 | 0 | 0 | 0 | 0 |
| vector_day_mismatch | 0 | 0 | 0 | 0 | 0 |
| no_book | 8 | 9 | 10 | 11 | 38 |
| no_truth | 0 | 0 | 0 | 0 | 0 |
| truth_conflict | 0 | 0 | 0 | 0 | 0 |
| no_yes_ask | 0 | 0 | 0 | 0 | 0 |
| ask_out_of_range | 0 | 0 | 0 | 0 | 0 |
| unknown_era | 0 | 0 | 0 | 0 | 0 |
| nonfinite_or_out_of_range | 0 | 0 | 0 | 0 | 0 |

`no_vector` is no pinned vector at the instant (the snapshot timestamp, or 16:50:00Z when the window is empty). `vector_day_mismatch` is a vector whose climate day is not D. `no_book` is no Depth10 snapshot in the closed 10-minute window. `truth_conflict` is a station-day whose finals disagree on `tmax_f` (excluded, not averaged). A station-day with no directory is not a drop.

## ASK set (primary)

- n events: 946
- station-day clusters: 160
- climate-day clusters: 40
- NBP: Brier 0.1425856047; REL 0.0080181078; RES 0.0059420356; UNC 0.1398265312
- YES ask: Brier 0.1115418605; REL 0.0011101660; RES 0.0286996982; UNC 0.1398265312
- D_res = RES(NBP) − RES(ask): -0.0227576626
- station-day 95% CI: [-0.0310675747, -0.0161564254]
- climate-day 95% CI: [-0.0301557900, -0.0166424732]
- wider CI: station-day [-0.0310675747, -0.0161564254]
- evaluable (n events ≥ 200 and climate-day clusters ≥ 30): True

Identity `|brier − reconstructed_brier| ≤ 1e-12` held for both systems. The null `D_res(ask, ask) = 0` held exactly. Both ran before the bootstrap and before the verdict.

Bootstrap: B=2000, seed 20260929, each clustering calling `cluster_bootstrap_draws` with that seed so each builds its own `Random`. The P&L interval is on the mean dollars per qty-1 take. On a width tie the smaller lower bound is the wider choice (harder to PASS).

## MID set (report only)

n events 781. NBP Brier 0.1704155415; REL 0.0113767544; RES 0.0035538835; UNC 0.1613775307. Ask Brier 0.1331901408; REL 0.0012366620; RES 0.0286236677; UNC 0.1613775307. D_res -0.0250697841. Report only; not an input to the verdict.

## YES taker P&L (decides FAIL; also a PASS input)

- takes: 150
- station-day clusters among takes: 100
- climate-day clusters among takes: 39
- sum USD: -7.9200000000
- mean USD per qty-1 take: -0.0528000000
- 95% CIs: station-day [-0.0906622517, -0.0076821192]; climate-day [-0.0908724832, -0.0114102564]; wider = station-day [-0.0906622517, -0.0076821192]
- evaluable (takes ≥ 30 and climate-day clusters among takes ≥ 30): True
- YES decision reasons: Refuse:below_margin=786, Take:take=150

## NO taker P&L (report only, not in the verdict)

NO asks come only from a captured NO-instrument book under the same 10-minute rule. `1 − YES bid` is not used.

- NO-instrument directories captured under the depth root: 0
- NO books read for an ASK event: 0
- priced NO takes: 0
- unpriced NO legs (ASK events with no usable NO ask in the window): 946
- NO P&L sum USD: 0
- NO P&L mean USD: 0

## Verdict

Pre-registered r2.1 table, PASS tested first. An overlap (D_res lower bound ≥ +0.005 and YES P&L upper bound < 0) is PASS, not a threshold change. Bounds of a statistic that is not evaluable are ignored. A lower bound of 0 does not PASS. An upper bound of 0 does not FAIL.

**FAIL**

A FAIL leads to its own reviewed change with its own impact check. This study deletes nothing.
