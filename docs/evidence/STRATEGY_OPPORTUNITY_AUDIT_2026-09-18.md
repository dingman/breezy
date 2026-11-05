# Strategy opportunity audit — 2026-09-18

Five read-only seams (information/latency, decision model, execution/exit, universe/window, measurement) plus one tape probe (venue repricing vs the bot's window). Per-seam returns and the probe are in the 2026-09-17/18 session scratchpad (`audit/result_*.md`); this file is the merged ranking.

## Ranked opportunities

| # | Opportunity | Why it matters | Evidence | Impact | Effort | Status |
|---|---|---|---|---|---|---|
| 1 | **Hunt starts after the winning rung has repriced.** Window opens 12:00 LST (`strategy.py:154`, fixed standard offset `:214-220`). Tape: 09-15 MIA winning rung went 0.50→0.90 in 43 min (15:16–15:59Z), finishing 61 min BEFORE the 17:00Z open; 09-16 MIA last cheap print 0.31 at 14:31Z, 0.88 at open; MDW 09-16 0.50→0.75 entirely before 18:00Z. Calibrate archive P(hold) for LST hours 10–11 (same IEM/CLI corpus, hour-keyed study `mb_current_rung_edge_study.py:168`), screen it against recorded pre-window asks exactly as the band Stage 0b did (0.25–0.75 ask bucket gate), then PREREG-amend the window. | The market prices the hold thesis during the hour the bot is not looking. | probe `result_F.md`; quote parquet 13–16Z | H | M | NEW |
| 2 | **Pre-registered SECONDARY endpoint on shadow-scored offer-tape rows.** ~20k eligible rows/day vs ~0.9 fills/day; score `p_bound − break_even` vs CLI finals, trial unit = first eligible snapshot per station-day (mirror the live latch), never feeds S_k. | Learn whether the climatological selector beats the market 10–50× faster than live fills; today admissible n=0 after 6 live days. | `offer_tape.py:82-248`; PREREG v3 §2:27; seams B1/E4/E9 | H (information) | M + ruling | NEW |
| 3 | **Re-score the live family's own P(hold) against tape asks nightly (descriptive study).** Same posture as K1; feeds #2. The band screen showed the 0.25–0.75 bucket at 32% positive / median −0.30; the live table has not been screened the same way. | Tells whether the current family can ever pass before its look clock even starts. | seam E-6/E-8/E-9 | H | M | NEW |
| 4 | **Truncate the hunt to the first 60–90 min after (a corrected) open**; refuse takes once the rung has repriced past the edge. | Post-METAR takes at 0.9+ are the L-9 lock trade with no seller. | tape: decisions stop by 13:01/15:08/15:56 LST; seam D-1/D-5 | H | S | NEW (PREREG hour filter) |
| 5 | **Do not burn the station-day latch on `illegal_cell`** (m=1 ceiling / open_lower); wait for an m=0 rung. | 11/26 replay days latched illegal then lost the day. | `gate_attribution_replay_2026-09-10.md:16-47`; `decision.py:29-33` | H | M | NEW (check GL-3) |
| 6 | **Per-rung WAIT/refusal counters and a per-tick reason for MDW.** | Funnel loss is >99% pre-decision and cannot be attributed by rung today. | `strategy.py:277,416,471-481`; seam E-3 | M | S | NEW |
| 7 | **Cut the observation poll from 300 s toward the 92 s NWS floor.** | 09-15 SFO fill lost a latency race on a 0.006 edge; blind 0–300 s after each NWS publish plus ~21 min API lag. | `nws_observation_config.py:40-41`; `LOSING_DAY_DIAGNOSIS_2026-09-15.md:11,16` | M | S | NEW |
| 8 | **Live IEM 5-min T-group as a second observation channel** (parser exists, `iem_observations.py:30-53`). | More exact running-max samples between hourly METARs; lag equal to NWS, so precision only. | seam A3 | M | M | NEW |
| 9 | **Forecast-conditioned P(hold).** 09-15 archive said 0.36/0.59/0.30 where the market said 0.11/0.24/0.09 and the market was right; the bot ingests no forecast (L-9). Plan parked, archive has no 2026 overlap. | The only information the market has that the bot does not. | `docs/plans/forecast_ingest_2026-09-01.md`; seam A4 | H if it works | L | Parked; needs its own kill gate |
| 10 | **Refuse one-sided books at entry** (bid empty 2.6 s before the 09-15 SFO take). | Avoids taking into a book that cannot exit. | `decision.py:384-386`; diagnosis §4.7 | L | S | NEW |
| 11 | Kalshi stations (24 cities, HIGH and LOW) as the only station lever; PM.us has none. | Linear in trials/day; only if coverable. | seam D-4 | M | L | Parked (wip/kalshi-s4-registry) |
| 12 | NO-side refusal counter (`_evaluate_no_side_shadow` drops Refuse silently). | Silence ≠ no NO edge. | seam E-11 | M | S | NEW |

## Do-not-do (evidence says no)
- Raise qty / per-position cap: multiplies edge, never creates it; venue body pins `"quantity": 1` (`submit_chain.py:352`); MP-B blocked on R-11.
- Replace the Wilson lower bound with the point estimate: ~4 pp more takes of the selector that lost 09-15 (L-21).
- Arm the exit seam now: R-DEAD 0/5 fillable, exit side gone a median 93 min before DEAD (EXIT-1, L-9).
- Buy the adjacent rung as a "hedge": that is the live hunt already; 09-15 MDW stacked two losers (R-10).
- Re-admit NYC (T-group rate 29/day vs ~305) or substitute stations (A14, L-13).
- Band decider (BAND-1 STOPPED 09-17); earlier boot (0 minutes gained under the current LST window — the gain in #1 comes from the window, not the boot).

## Contradictions resolved
- Seam D said "no MIA minutes lost" (true relative to the code's own LST window); seam A suspected the window itself is late. The tape probe confirms A: the repricing happens before 12:00 LST on MIA/MDW. #1 is therefore a window question, not a boot question.
- Seam B corrects the coordinator's shorthand: the PREREG v3 look boundary is LD-OBF on S_k; Wilson is the terminal/cell-dead rule.

## Coverage gaps
- Pre-window asks exist in parquet only where ING-1 did not strand the day (MIA 09-16 dead from 14:31Z); #1's screen needs the recorder gap fix or the 09-17+ tapes.
- Whether the decision ask at submit matches the fill price is reconstructed, not logged (`_maybe_submit` has no px line).
- Only 09-14/15/16 have full funnel breakdowns; the pre-decision loss share is from one audited day.
