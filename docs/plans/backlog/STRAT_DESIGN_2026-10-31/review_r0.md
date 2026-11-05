# STRAT-DESIGN r0 — merged peer review (2026-10-31 ~04:30Z)

Three blind reviews of `design_r0.md` + `harness_entrypoints.md`: trading-bot-architect REVISE (D1–D10), prediction-market-reviewer
REVISE (D1–D10), python-reviewer fact check (every file:line/flag/path VERIFIED except the items under R12/R13). Verdict: **REVISE → r1**.
Deltas below are BINDING for r1; where reviewers disagreed the coordinator's resolution is stated.

## R1 Economic frame (binding before any ranking)
Every PM.us cell is economically null at qty 1: Card B ≈ 0.13 fills/day × 30 × ≤2¢ ≈ $0.08/month (not "<$2"); Card E at the
5-city overlap ≈ 137 station-days/month × 2–5% disagreement × ≤$1 < $7/month, and the two legs are NOT a lock (pays 2/1/0 by
direction; coin-flip without an ex-ante direction predictor). r1 must (a) print the corrected prize per cell at qty 1, (b) add one
line per cell "prize as a function of size" (the only lever is the operator-reserved caps — state it, never set it), (c) rank by
evidence cost to a decisive answer, not by prize, (d) apply the ~9% never-listed rate and 84/119 recorder coverage to every cell.

## R2 Backtests on the existing engine (operator: "the bot backtests")
No card in r0 runs on the Nautilus engine; r1 must name, per card, exactly one path: (i) a Depth10/trade_tick census through the
existing `wp7b_market_as_forecaster.sum_ask_row` or `maker_stage0_replay.queue_sizes` with a forced no-truth path, or (ii) an engine
run via ONE more `--strategy` choice + one `if` branch at `scripts/analysis/current_rung_hold_paper_replay.py:1475/1547` (a dynamic-
import call-site test pins the count — extend the pinned list, never bypass it). Before relying on the Stage 0 simulator for fills,
evaluate enabling `trade_execution=True` + `queue_position=True` on catalog `trade_tick` as a `BACKTEST_VENUE_CONFIG.md` amendment
(Nautilus-native null hypothesis). Any new script is declared "NEW EVALUATOR — exception requested" with the reason.

## R3 Card A
Add Σbid: buying NO on every band is the long-only basket (pays n−1 for sure, profits when Σ YES-bid > 1). Add a PASS rule for the
HIGH/LOW leg (r0 has only a kill). Abutment check must include open-ended tail bands. State legging risk (6–10 non-atomic legs) and a
leg-fill assumption. Replace "first instant per station-day" (listing-time bias) with a stated sampling rule.

## R4 Card B
Power: (σ/δ)²·(1.645+0.842)² = (0.1/0.005)²·6.19 ≈ 2,470 fills for 0.5¢ (≈275 for 1.5¢), not 250 → at 0.13/day ≈ 19,000 days.
Follow-up arm is infeasible under `e_min=0.04` (b_max ≤ 0.96 < 0.97 touch): pre-register `e_min ≤ 0.02` or drop the arm. Replace the
size census with Stage 0 `queue_sizes` + BUYER-print fill counts at the touch price (outcome-blind, excludes own orders, independent
units, window clean of own-order contamination per L-65 — 10-17..10-30 is NOT clean after 10-24). Breakeven p at b: 0.89→0.8968,
0.97→0.9720, 0.98→0.9814, 0.99→0.9907; the "sharp counterparty" claim is asserted, never tested — the census must measure adverse
selection on touch fills. `maker_design_nobid.py` loads truth (line 423) → not usable as a blind census.

## R5 Card C
Signed markout in the NBM-implied direction with a cluster null (|Δ| at 120 ms passes under H0 from tick flicker alone). Move off
P2's 09-21..10-13 window or declare a new trial under L-34. Drop the LAT-1 duplication. State that a pass only reopens the stale-ask
taker family P2 closed.

## R6 Card D
Offer rate is not mispricing (the band above the running max is cheap because it is unlikely; 20% is trivial under H0). Redefine as
ask − a pre-registered conditional probability computed WITHOUT the band decider (no sub-degree inference from integer-°C METAR), or
move the hour; resolve the 17Z/M1 D_17Z overlap under L-34; METAR row-level coverage must be counted first.

## R7 Card E
Step 1 = public Kalshi settled markets (`result`, `expiration_value`, no auth) vs IEM-archived NWS CLI daily max/min for all 24
stations over ≥90 days: runs K-2a without a depth tape or adapter. The r0 admission test is degenerate (Wilson LB = n/(n+3.84) at
z=1.96 → 0.959 at n=90 with zero misses; LB > 0.99 needs n > 380): replace with a stated disagreement rate + named mechanism. Allow
single-venue trading on a stable TWC≠CLI station. Do not make the kill depend on a tape that does not exist. The repo's CLI-basis
studies measure CLI vs ASOS/METAR, not TWC — say the TWC rate is unmeasured.

## R8 Fee sign (verify first)
Maker fee vs rebate (−0.0125 assumed in §4) flips the sign of every ≤0.5¢ maker cell at 0.97–0.99. Verify from venue docs before
ranking any maker cell; cite the doc.

## R9 LOW-only census as its own card (fresh sample; 84/119 captured; LOW truth needs tmin).

## R10 Missing mechanisms to add to §1
Depth10 queue-ahead distributions on disk as a pre-registered fill-probability model; `trade_tick` fill proxy (resolve the unit first);
cross-city correlation (effective n ≪ station-days); listing-time first-hour empty-bid hole; GTD 4 h rolling over the UTC-midnight cut.

## R11 §3 step 6 bare STOP → a defined next state (lesson: a plan must reach the goal state): the next state is the operator size
question (R1b) or the Kalshi venue question, stated as such.

## R12 Pre-run checklist (from §4 + fact check)
Recorded-day completeness per date (directory names ≠ recorded data; zombies, node-down days); the 204 `low` dirs are real ladders;
`trade_tick` unit; Σask abutment; `derived/settlement-truth` holds the csv + coverage.json too; Card B window clean of own orders.

## R13 Outcome-blind labelling
The blanket "Cards A–D do not read settlement" is FALSE: `market_calibration_scan.py` (settlement_truth.csv), `maker_design_nobid.py`
(truth after simulation), `p2_nbp_ask_murphy.py` (truth_cli_finals) all read truth. Only Depth10/trade_tick-only recounts qualify;
each card names its truth-free path explicitly.

Accepted as-is: §0 closed-cell table; §1 map structure; cheap-kill ordering principle; harness line citations (all VERIFIED).

## R8 RESOLVED (coordinator, 04:55Z, independent read of https://docs.polymarket.us/fees fetched 2026-10-31)
Schedule effective 2026-10-19 13:00 ET: taker θ = 0.0695 on p(1−p); **maker Tier 1 (< $10M prior-month maker volume) pays 0 and
receives no rebate**; rebates −0.0035…−0.0104 start at Tier 2. The −0.0125 rebate comes from the stale 08-25 snapshot
(`docs/evidence/venue/polymarket_us/docs_snapshots/fees_2026-08-25.md`). Binding for r1/r2: maker fee = 0 for every maker cell;
never credit a rebate; charging +θ·b(1−b) is a conservative bound only. Defect for the backlog (not this design): the repo fee model
`src/breezy/adapters/polymarket_us/fees.py` charges makers +θ by default (:267-289) and credits −0.0125 with `allow_maker=True`
(:356-376, `MAKER_FEE_COEFFICIENT` :83 "DOCUMENTED-NOT-WIRE-OBSERVED"); `expected_fee_for` (:446) returns −0.0125; the snapshot
needs refreshing. No live maker fill exists to observe the wire value (all 34 fills TAKER, fees ≥ 0).
