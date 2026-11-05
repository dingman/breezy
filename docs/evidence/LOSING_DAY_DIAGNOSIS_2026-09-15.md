# Losing-day diagnosis — 2026-09-15 (pm_us_crh_cont, first four create-path fills)

Coordinator merge of six blind read-only agents (forensic log/state reconstruction, live board evaluation with the shadow-monitor modules, configuration/channel inventory, SFO decision-path reconstruction, domain-math review, architecture review). Numbers are the agents' own reads; settlement is 2026-09-16 08:00 ET and nothing below is settlement-grade.

## 1. What happened
| # | Time (UTC) | Position | Fill | Entry cell → archive p_hold | Break-even | Status by observation | Prelim CLI |
|---|---|---|---|---|---|---|---|
| 1 | 18:00:04 | MDW YES [80,81] | 0.11 + 0.01 fee | (MDW,SON,12,w0,m1) → 0.3581 | 0.12 | DEAD: R 81 at fill (rung top), 82 ten min later, 85 by 20:53Z | 85 |
| 2 | 18:23:33 | MDW YES [82,83] | 0.24 + 0.01 | (MDW,SON,12,w0,m0) → 0.5944 | 0.25 | DEAD: R 85 | 85 |
| 3 | 18:12:19 | MIA NO [92,93] | 0.09 + 0.00 | (MIA,SON,13,w0,m1) → p_miss 0.2970 (log: 0.1541 at decision) | 0.09 | LOSING: R = 93 inside the rung since 17:55Z, peak passed | 93 |
| 4 | 20:12:06 | SFO YES [71,72] | 0.44 + 0.01 | (SFO,SON,12,w0,m0) → 0.4606 | 0.4548 | DEAD 2 min BEFORE the fill: IEM METAR valid 20:10Z read 73 | none yet |
Committed 0.88 + 0.03 fees. Every held leg's exit side is now empty (asks 0.01 × 10^5–10^6, no bids; MIA YES bid 0.99, no ask). Last executable 1-lot exits: 0.04 / 0.01 / 0.01 / 0.01 (18:07Z, 20:03Z, 19:36Z, 20:12:13Z). Expected realized loss if settlement follows observation: −0.91. No refusals for staleness, depth, sibling, day-stop or count; no AMBIGUOUS orders; the NO first-order residual containment is OPEN (capture CLI not yet run).

## 2. Mechanism, per take
- Takes 1–3: the registered rule fired correctly on cells with an archive edge and lost the draw. The market priced 0.11 / 0.24 / 0.09 against archive bounds of 0.36 / 0.59 / 0.30 and was right four for four (L-21 signature: a pooled climatological cell does not know the afternoon is running hot).
- Take 4: latency race. `NwsObservationActor` polls api.weather.gov every 300 s; the node's running max still read 71 (cell m0) at 20:12:06Z while a 73 °F reading valid 20:10Z existed. The 50-min staleness bound is a feed-outage detector by construction and cannot catch a 2-minute boundary race. Edge at decision was 0.0058. The node itself logged the SFO book as one-sided (empty bids) 2.6 s before the order; the entry gate looks only at the ask.
- None of the four decision inputs (R, cell, p_bound, BE, staleness) is persisted; the YES take path writes no diagnostic line. Reconstruction above is from code constraints and an independent METAR fetch.

## 3. Statistics
- P(0/4) under the registered H0 (held ~ Bern(BE)): 0.88·0.91·0.75·0.55 ≈ 0.33. Under the archive's own p_hold (SFO excluded): ≈ 0.18. Today is not informative about the estimator; the structural findings below are.
- Admissible n after today, once the scorer reads v3 keys: 3 (the NO fill is residual by the NO-side amendment §8). Today the scorer parses only 2-part station/climate_day latch keys, so n = 0 and neither the LD-OBF looks (first at n=10) nor the per-stratum cell_dead kill (n ≥ 60) is ticking — an L-38 MISSING stop. The −60 contract-unit dollar halt would need ~60 more days like today.
- The archive table has no latency axis and no METAR-vs-5-minute cadence axis (L-13); live METAR T-group rows are exact and never trigger the corpus's integer-°C widening; the boundary case R = rung top (m1) is a registered covariate but still left a 0.24 archive-minus-ask gap on take 1.

## 4. Self-improvement path (channel: B = build-side now; C = successor family via ruling; nothing is an operator knob)
| Rank | Change | Channel | Status |
|---|---|---|---|
| 1 | Scorer reads 3-part instrument-keyed latches → today's fills become admissible; LD-OBF and stratum kill start ticking | B | BUILT 2026-09-15 (this branch) |
| 2 | Per-decision evidence persisted for every take AND refusal (side, p_bound, BE, R interval, staleness, cell, admission), offer-tape JSONL on by default | B | BUILT 2026-09-15 |
| 3 | Scheduled board analysis: nightly shadow-monitor report after the scorer, as a timer | B | BUILT 2026-09-15 |
| 4 | Shadow monitor NO-leg thesis semantics (LOCKED/DEAD inverted for NO) | B (monitor bug) | BUILT 2026-09-15 |
| 5 | m1 (rung-top-at-entry) and ask-band strata reported by the tally once n > 0 | B | existing study strata; needs rank 1 + ING-1 |
| 6 | Entry latency guard (newest observation age vs venue clock) and/or refuse when R is within one reporting interval of the rung top | C | needs the rank-2 evidence stream + a replay study, then a successor PREREG (n resets) |
| 7 | One-sided-book policy at ENTRY (empty bid side = refuse) | C | same; today's SFO book was one-sided at the take |
| 8 | Archive recalibration/coverage (SFO absent cells, hours 12–16 only, latency axis) | C | successor family with re-solved boundary |
| 9 | ING-1 (Depth10 ingest collision) and the recorder at its memory watermark | B ops (already CRIT in PROGRESS) | blocks marks, corpus and structural-dead clock |

## 5. Don'ts
No exits (no counterparty; L-7/L-9). No in-place parameter changes to pm_us_crh_cont (PREREG v1 §7 / v3 §10). No reading 0/4 as falsification (n≈4). No waiting for time to advance clocks that are not ticking.

## 6. Expect
Settlement tomorrow should confirm four losses (provisional until the FINAL CLI). Tally: n moves 0 → 3, verdict CONTINUE; nothing stronger is possible at this n.
