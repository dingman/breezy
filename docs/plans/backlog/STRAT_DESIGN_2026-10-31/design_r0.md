# STRAT-DESIGN r0 — 2026-10-31

Design only. No backtest in this round. Nothing here arms, sizes, or amends the live
sharp maker (P4 runs to its own stop). The daily budget and the per-position cap are
not assigned. Every entry below is a buy. `allow_short` stays false. Nautilus is not
modified. No new harness, runner, or unit.

Prize column: dollars a **qty-1** book could keep in a month **if** the mechanism is
real, after the venue fee θ·b·(1−b) with θ = 0.0695. Qty 1 is the size the live
maker and the cited replays already use, not a new cap. The independent audit's
ceiling for the whole PM.us weather book, even with an edge, is about $10–65/month
(`docs/evidence/AUDIT_independent_2026-10-22.md` §Proven 4; D0 ladder notional about
$0.4–2.6k/day). A cell that cannot clear that ceiling at qty 1 cannot clear it by
wishing for size.

## 0. Closed — do not re-propose

| Closed | Why it stays closed | Cite |
|---|---|---|
| Taker rung families | 34 fills, 4 wins, −2.63; expected wins Σprice = 6.36 | Audit §Proven 1 |
| Forecast edge on PM.us HIGH rungs | Ask-set resolution of the market is 1.98× the forecast; D = −0.015, CI excludes 0 | `RULING_forecast_edge_programme_closes_2026-09-20.md` §2–4 |
| BSS +0.594 headline | Withdrawn; the ask set is the result, and it is negative | same ruling; operator 2026-10-31 |
| NBP as a PM.us leg | n_min 592 > ceiling 520 | `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30.md` |
| NBP vs the YES ask | D_res −0.023; 150 YES takes, −$0.053/take, CI upper −0.008 | `P2_NBP_VS_ASK_MURPHY_2026-10-22.md` |
| Band decider | No live sub-degree source; integer-°C METAR is a 1–2 °F band | operator; L-9 |
| Sharp qty-1 NO maker at the 89¢ cap | 0 fills in 7 days: bid sits 8–10¢ behind a 97–99¢ NO touch with ≥100 ahead | `P4_LIVE_READ_2026-10-30.md` §5 |
| Sharp 17/17 replay | Nomination on one 92-day tape; one-sided LB 0.839 < breakeven 0.865–0.888 | Audit §Proven 3; `MAKER_sharp_v1_leakage_audit_2026-10-21.md` |
| CRH resting bids arm A | Underpowered negative (19 proxy fills) | `RESTING_BID_HUNT_2026-09-16.md`, cited by the maker spec §1 |
| Near-certain lock | The winning rung is not offered | L-9 |
| Cheap-NO taker band 0.06–0.12 | Underpowered on 5 stations (n ≥ 1486) | `RULING_TE-3_NO_CHEAP_LONGSHOT_2026-10-11.md` |

Binding for anything that survives: L-7 (public information has no offer), L-21 (climatology is not the comparator), L-34 (a re-look is a new trial), L-35 (empty bid is invisible on QuoteTicks; use Depth10), L-40 (trial unit is the station-day), L-56 (motivating fills do not count), L-60 (power from the estimator you will actually run), L-64 (pre-register the opportunity monitor), L-65 (the tape does not contain our orders). Do not score settlements on the frozen M1-v3 forward window (NO ask ≥ 0.90, read-once on or after 2026-12-07, `no_longshot_pooled_test.py`).

## 1. Inefficiency map

### 1.1 Longshot overround

**Mechanism.** M1, model-free, buys the Depth10 ask and holds: YES asks in 0.00–0.10 lose 1.7–2.3¢ with the whole CI below 0 (`M1_MARKET_SCAN_2026-10-04.md`). That is the classic longshot: cheap contracts settle less often than their price. The 2026-09-20 ruling's other face — ask-bin mean 0.967 settling 0.25 at n = 12 — is the same wide book, not a powered favorite bias, and is not reused as a sample. The overround is also structural: mean Σask − 1 = +0.29, minimum +0.05, zero complete ladders at or under 0.98 (`RULING_forecast_edge_programme_closes_2026-09-20.md` §3). On 2026-10-22 the audit measured Σ of YES best asks at 1.05–1.22.

**Why it is not closed by the market.** A taker who buys the cheap YES pays the overround. The side that would collect it is a seller of that YES, which under `allow_short = false` is a **buyer of NO**. Professionals already sit there: the NO touch is 97–99¢ with ≥100 contracts (`P4` §5). The mispricing, if it survives, is inside a queue we do not reach at 89¢, and it is smaller than one tail loss (at 99¢, θ·b·(1−b) ≈ 0.0007, so breakeven win rate ≈ 0.991; one loss wipes on the order of 200 wins of a 0.5¢ edge).

**Counterparty.** Retail lifting cheap YES. Not a slow professional.

**Prize.** Under $2/month at qty 1. The $10–65 ceiling is the whole book, not this cell. **Evidence cost.** Low: Depth10 is on disk. **Rank.** 2 by prize among things the PM.us tape can actually test; 1 by how fast a kill falls out.

### 1.2 Maker microstructure with a real queue

**Mechanism.** The Stage 0 fill pass already models price priority: size strictly ahead, size at our price, own 1 included, BUYER prints only, gaps removed, stress = 2× (`maker_stage0_fill_pass.py` lines 6–11 and `queue_sizes` at line 79). The Nautilus engine does **not**: `queue_position=False`, `trade_execution=False`, `latency_model=None` (`backtest_harness.py` lines 738–752). The 17 stress fills survived a 1 s and a 5 s placement lag (`P1_latency_preflight_2026-10-22.md`) and still failed the breakeven lower bound. Live, 99.8% of rest-hours were in the ≥100-ahead stratum and that stratum had 0 fills in 988 h. The thin-queue burst that produced the 17 fills (about 3.5 h/station-day on 10-09..10-13) fell about 3×, and disagree-rungs went to 0/day from 10-17 (L-64).

**Why a new price does not fix it.** Pennying an 89¢ bid cannot pass 100 contracts quoted 8–10¢ higher. Joining 97–99¢ joins the back of that size. Crossing is a take, and takes are closed. A rule that only posts when size at the touch is small is the same rule that filled in-sample and then lost its regime.

**Counterparty.** Whoever is happy to buy NO at 97–99¢. They are the market, not the mark.

**Prize.** About $0–2/month if any thin-touch hour remains; $0 on the published regime. **Evidence cost.** Lowest of the maker family: an outcome-blind recount, no settlement. **Rank.** 3. Pre-killed unless the recount disagrees with §5.

### 1.3 Band-sum (complete HIGH partition)

**Mechanism.** Bands of one daily high are a partition. Buy every YES ask only if the sum is < 1 after fees on every leg. That is a lock. Selling the basket is impossible here (`allow_short` false), so Σbid > 1 is not a trade we can do.

**Evidence.** Against, strongly: minimum Σask − 1 = +0.05 on 64 verified partitions through the forecast-edge sample; audit spot-check 1.05–1.22. Nobody has published the same sum on days after 2026-09-20. **Counterparty.** Would have to be a seller of every band at once. Not observed. **Prize.** $0 on the prior. A single locked cent on a rare instant is still inside the ceiling and is unobserved. **Evidence cost.** Cheapest test in this note. **Rank.** 5 as a strategy, 1 as the first kill.

### 1.4 HIGH vs LOW on the same station-day

**Mechanism.** HIGH ≤ H and LOW ≥ H+1 cannot both happen. The books are separate. A quote pair that prices both as likely is incoherent. It is **not** a lock: both legs can settle false, so buying both loses. The only buy that expresses the constraint is NO on the impossible tail, after the other ladder has already made it impossible. That is cross-book information, public, and L-7 applies.

**Evidence.** For existence of a LOW tape only: 204 of 2,041 Depth10 directories have `low` in the name (name census, this round; not checked for complete ladders). Against a trade: no joint-incoherence study exists; the forecast programme says the HIGH book is already a better forecaster than NBP; NYC/MDW LOW and PHL HIGH were absent from the registry on 2026-10-22 (audit §Proven 4). **Counterparty.** A LOW-only quoter who does not watch the HIGH ladder. **Prize.** Unknown, prior under $5/month, and only on days both ladders are listed. **Evidence cost.** Low, same pass as §1.3. **Rank.** 4.

### 1.5 Adjacent-day coupling

**Mechanism.** Tomorrow's high depends on today's settlement beyond what the 13Z/19Z/01Z NBM already says. **Why it should not be open.** The market's resolution is 1.98× the forecast that already includes persistence. Yesterday's CLI is public before the next book is tradable (L-7). **Counterparty.** A D+1 opener who ignores the print. Unobserved as a residual. **Prize.** Prior $0. **Evidence cost.** Medium (a residual-after-NBM study would be a new look at a closed family). **Rank.** 8. Not carded. Re-open only if a pre-registered residual resolution test, fit without the old forecast splits, beats the ask. That test is not authorized here.

### 1.6 Stale quotes after a forecast update

**Mechanism.** A new NBM cycle moves the fair band before the book does. A taker lifts the old ask. **Evidence against.** P2: at the 16:50Z D−1 book, the YES ask out-resolves NBP by 0.023 Brier and the take loses 5.3¢. Live taker decision-to-fill was about 120 ms and the signal was still wrong (audit §Proven 2, LAX 10-05). LAT-1 (`nbp_revision_latency.py`) is a latency scorer with an unfrozen prereg; it refuses climate days on or after 2026-10-28 and is not a licence to trade. **Counterparty.** A slow updater. If our ingest is slower than the book, we are the mark (L-7). **Prize.** Prior $0. **Evidence cost.** Low if restricted to an outcome-blind markout. **Rank.** 6.

### 1.7 Settlement source: PM.us NWS CLI vs Kalshi TWC

**Mechanism.** PM.us settles on NWS CLI. Kalshi's rules name The Weather Company as the authority and the CLI id only as the station (`PREREG_v1_kalshi_current_rung_hold_DRAFT_2026-09-04.md` lines 47–48). An older memo treats TWC as a reader of the same CLI (`k1_kalshi_prior_2026-09-02.md` line 34). Both can be true and still diverge (hourly max vs CLI calendar day, DST, amendments). A divergence that is known **before** both books stop being tradable is a basis: buy YES on the venue that will pay and NO on the venue that will not. A divergence that is noise is not a trade. K-2a already requires per-station reconciliation before any label is shared: n ≥ 90, Wilson lower bound on bucket agreement > 0.99, else excluded; same-office collisions (EWR/NYC, PHL/TTN, AUS/SAT) each need their own body match (`K-2a_kalshi_plan_r1.md` §3). That test has not been run (WA-2 is still a draft).

**Counterparty.** Someone treating the two settlements as the same number. **Prize.** The only open cell that can exceed the PM.us $10–65 ceiling, and only on a station whose agreement **fails** for a stable reason. Expected prize today is $0 because the rate is unmeasured. A 1% random disagreement is not tradable ex ante. **Evidence cost.** High relative to a tape census (public historical reads, not the PM.us harness). On disk now: five HIGH series JSON files plus `candles.jsonl` under `~/.local/share/breezy/kalshi/` (CHI, LAX, MIA, NY, SFO). No Kalshi depth catalog. No LOW series files. **Rank.** 1 by option value, last by what the bot can backtest this week.

### 1.8 Late day: hour 10–11 local, METAR vs CLI rounding

**Mechanism.** By late morning the running max rules out the lower bands. Integer-°C METAR still leaves two °F bands alive, and CLI can print either. If one of those two is offered cheap, the rounding is not in the price. **Evidence against.** `p_hold` rising through the day is the max becoming known, and the price rises with it (`ALL_HOURS_EDGE_TABLE_2026-09-20.md` §3). Running max has already converged by 17:00 local (LAX P(R_17 = R_23) = 99.4%); the CLI-vs-ASOS basis is real and the **offer** at a cheap ask was the gate that failed (`cli_basis_boundary_study_2026-09-02T044737Z.md` §2–3; L-9). M1's D_17Z window is 17:00 UTC (09:00 PST / 12:00 EST), not 10:00–11:00 local, so this hour is not that cell. **Counterparty.** A book still showing the overnight ladder. **Prize.** Prior $0. M1's median cell MDE at 26 days was 19.8¢; a 3–8¢ edge needed about 15× the days. Two months of tape does not get there. **Evidence cost.** Low for an offer census, hopeless for a powered PnL test. **Rank.** 7.

### 1.9 Venue switch to Kalshi (24 cities, 5-minute clock)

**Mechanism.** Not an edge. A larger sample and a faster observation clock. 24 cities × ~30 days is on the order of 600 station-days a month before the ~9% skip (`PREREG_v1_current_rung_hold_2026-09-04.md` line 165) and before same-weather correlation. That still does not power TE-3's n = 1486 in one month, and it does nothing if the 5-minute book also refuses the certain rung (L-9 travels until measured). The forecast-edge close "does not transfer as a negative" to Kalshi (`RULING_forecast_edge_programme_closes_2026-09-20.md` §6) and does not transfer as a positive either. **Prize.** Unbounded by the PM.us ceiling only on paper. No depth, no measured notional. **Evidence cost.** Blocked: nothing under `/mnt/storage/breezy/catalog` is a Kalshi tape. Parked registry branch is not a catalog. **Rank.** Tied with §1.7; do not multiply $10–65 by 24/5.

### Rank

| # | Cell | Prize / month at qty 1 | Evidence cost | First test |
|---|---|---|---|---|
| 1 | TWC vs CLI basis, then Kalshi scale | $0 now; only upside past $65 | High; not on this harness | WA-2, after it is reviewed. Not this round |
| 2 | Longshot, collected only by a NO bid the queue can reach | < $2 | Low | Card B census |
| 3 | Any other maker price on the same touch | $0–2 | Lowest | Card B, same census |
| 4 | HIGH vs LOW joint quotes | < $5 prior | Low | Card A, second count |
| 5 | Band-sum lock | ~$0 | Lowest | Card A, first count |
| 6 | Stale book after a forecast cycle | ~$0 | Low | Card C |
| 7 | Hour 10–11 local rounding | ~$0 | Low for offers; PnL underpowered | Card D |
| 8 | Adjacent day beyond NBM | ~$0 | Do not spend | Not carded |

## 2. Strategy cards

Shared implementation rule. A survivor extends `NoLadderMakerStrategy` (`src/breezy/strategy/no_ladder_maker/strategy.py` line 205) or a backtest-only subclass in the same style as `CurrentRungHoldBacktestStrategy`. Parameters are a new frozen `MakerRuleParams`, not an edit of `SHARP_V1` (`params.py` lines 39–49), so P4's live process is unchanged. Settlement PnL, if a fill is ever assumed, goes through `backtest()` (`backtest_harness.py` line 1026) with `settlement_prices` in {0, 1}. Whether the fill happens is **not** an engine question (`queue_position=False` at line 752). Bound it with the existing Stage 0 queue accounting, stress ×2, and report the engine path as an upper bound that ignores the queue. Qty 1. Hold to the engine's settlement close. No exit sell. Post-only: a bid that would cross is a refusal, not a take.

### Card A — partition and HIGH/LOW quote census

**Thesis.** The only structural trade this account can do without a forecast is a complete HIGH ladder whose YES asks sum to less than 1 after fees. HIGH/LOW coupling is a second, weaker claim: how often the two books disagree by more than the spread. Neither claim has been counted on the post-2026-09-20 tape.

**Signal.** At each Depth10 instant where every band of one station-day HIGH ladder has a top ask of size ≥ 1: S = Σ ask. Separately, when a LOW ladder for the same station-day has a top ask: flag a pair (HIGH band H_lo..H_hi, LOW band L_lo..L_hi) if the two intervals cannot co-occur and both asks are ≤ 0.50 (both sides priced as live). No forecast. No settlement in this card.

**Entry / exit.** None in this card. A later card may buy the full HIGH basket only if S + Σ θ·a·(1−a) < 0.98 and every leg's top size ≥ 1, qty 1, GTD until the first missing ask, cancel if any leg cannot be posted. That later card does not exist unless this one passes. Do not buy both sides of a HIGH/LOW contradiction.

**Data.** Already in the catalog: `order_book_depths` under the quote-tape root in §4. Truth is not read.

**Nautilus.** No strategy class until the census passes. The census is a read of the catalog the harness already uses (`ParquetDataCatalog` via `maker_stage0_probe.py` line 223 and `market_calibration_scan.py`). It is not a new runner.

**Backtest spec.** Do not start `BacktestEngine` for this card. The engine cannot see a multi-instrument lock as one decision, and `queue_position=False` would fill every leg against a stale book (`liquidity_consumption` does not create size that was never there, but a lock backtest that ignores queue is fiction). Entry point for the tape read: `python -m scripts.analysis.market_calibration_scan` is the wrong statistic (single-rung excess). Use the partition check already in `scripts/analysis/wp7b_market_as_forecaster.py` (`main` at line 1287; the 2026-09-20 ruling cites its sum over complete partitions). Restrict the **new** count to climate days 2026-09-21 through 2026-10-30 inclusive. Do not reuse the 64 partitions that produced the +0.29 result as the sample. Output is counts and a median S, written outside the live catalog root.

**Pre-registered criterion.** PASS only if both hold: (1) at least 30 distinct station-days contain one instant with S < 1, and the median of (1 − S − Σ fees) on those instants is ≥ 0.02; (2) the station-day count uses one instant per station-day (the first), so a single wild print cannot make the 30. There is no t-test: a lock is not a mean of noisy PnL. Sample on the shelf is about 40 days × up to 5 HIGH stations. If fewer than 30 days are fully partitioned in the files, the result is INCONCLUSIVE, not PASS.

**Kill.** Zero instants with S < 1, or fewer than 30 station-days and none of them under 1. HIGH/LOW: kill the joint claim if the flagged-pair count is 0. Either kill stops that leg. It does not kill Card B.

### Card B — touch queue, not another 89¢ arm

**Thesis.** The longshot overround is collectable only by a NO bid that can be reached by a print. The published live book says it cannot: the touch is 97–99¢ and thick. This card recounts **size at the touch**, which is not the same number as size ahead of an 89¢ bid, and dies if the touch is thick.

**Signal.** For each Depth10 frame on a HIGH NO book (or the YES book inverted: NO bid = 1 − YES ask, NO size = YES ask size), record best NO bid and displayed size at that price. A frame is thin only if that size is ≤ 20 and the best bid is ≥ 0.97. No `p_NO`, no settlement, no order.

**Entry / exit.** Not in this card. A follow-up arm, only if the census PASSes, would be `MakerRuleParams` with `b_cap` left at the touch (min of best+1¢ and ask−1¢, and still ≤ the price whose fee-inclusive cost is ≤ p_NO − 0.04) and an added refusal when size at the touch > 20. That arm is not designed in full here because the census is expected to kill it. It would still be qty 1, post-only, cancel by 09:00 local as the current rule does, hold to settlement. It must not be loaded into the live node.

**Data.** Same Depth10 root. Window: 2026-10-17 through 2026-10-30 (the published post-burst regime). Do not include 10-09..10-13; those days nominated the dead arm (L-56).

**Nautilus.** None until PASS. The recount is `queue_sizes` (`maker_stage0_fill_pass.py` line 79) applied at the touch price rather than at 0.89. Bench mode of the Stage 0 CLI (`maker_stage0_replay.py` lines 1–15, `--bench`) times the frozen rule; it is not this census and must not be pointed at a new ledger.

**Backtest spec.** Outcome-blind. No `run_backtest`. No truth parquet. If a later arm is ever simulated, drive it through `replay_station_day` / `simulate_station_day` as `maker_design_nobid.py` already does (module docstring lines 1–5), with a **new** output directory under `derived/replay/design/`, never the Stage 0 verdict ledger (`maker_stage0_replay.py` line 45). The design fence `NO_BID_CEILING = 0.90` (`maker_design_config.py` lines 54–55) exists to protect M1-v3. A touch study at ≥ 0.97 must not emit a settlement column at all, so it cannot be spliced into that read-once.

**Pre-registered criterion.** PASS only if thin frames (size ≤ 20 at a best NO bid ≥ 0.97) occur on at least 15 distinct station-days in the window and the median displayed size at the touch, over all frames with a NO bid ≥ 0.97, is ≤ 20. One station-day counts once. Expected fills are not estimated from the 17.

**Kill.** Median touch size > 20, or fewer than 5 thin station-days. That kill is the end of maker variants on this venue until a new regime is declared in advance. Do not raise `b_cap` on the live family in response.

**Power note, so a PASS cannot be over-read.** At b = 0.99, fee ≈ 0.0007, breakeven probability ≈ 0.991. An edge of 0.5¢ has trial SD on the order of 0.10 (one loss pays −0.99). n ≈ (1.645+0.842)² × 0.01 / 0.005² ≈ 250 fills for 80% power at one-sided 5%. At the live-adjusted 0.13 fills/day (`P4` §5) that is years of qty-1 trading. A PASS on this census authorizes a paper queue study, not a live arm and not a claim of edge.

### Card C — forecast-release markout

**Thesis.** P2 killed the forecast as a **level**. It did not measure the **impulse**: the change in the mid in the 120 ms and the 60 s after `available_at_ns` of a pinned cycle (13Z, 19Z D−1, 01Z D). If that move is smaller than half the spread plus the fee, there is no stale ask to lift.

**Signal.** For each cycle release with a Depth10 frame before and after: Δ = mid_after − mid_before, same rung. Spread = ask − bid at the before frame. Fee = θ·ask·(1−ask) at the before ask. No order.

**Entry / exit.** None. A take would be the closed family.

**Data.** NBP store `~/.local/share/breezy/derived/nbp` (present) and the quote tape. Restrict climate days to 2026-09-21..2026-10-13 so the window matches P2's scored end and does not enter LAT-1's confirm period (D ≥ 2026-10-28).

**Nautilus.** None. Entry point: `scripts/analysis/nbp_revision_latency_io.py` already points `DEFAULT_TAPE` at `/mnt/storage/breezy/catalog/quote_tape/polymarket_us` (line 38). Do not run `nbp_revision_latency.py` stages; its prereg is unfrozen and a stage run would be a different trial. A markout is a new, smaller question and must not be written into LAT-1's output files.

**Backtest spec.** Not an engine run. The harness has no latency (`latency_model=None`), so an engine fill at the old ask would invent the edge this card is testing.

**Pre-registered criterion.** On station-day clusters, the median |Δ| at 120 ms is the statistic. PASS only if that median exceeds half-spread + fee on more than half of the releases, with at least 30 climate-day clusters. The 60 s number is reported and is not the gate (a minute is long enough for everyone).

**Kill.** PASS fails, or fewer than 30 clusters. Kill ends stale-quote taker designs.

### Card D — hour 10–11 local, offer only

**Thesis.** L-9 says the decided rung is not offered. This card tests that sentence at 10:00–11:00 **local standard time**, per station, on the two °F bands that touch the running max of the public METAR. It does not test whether those bands settle.

**Signal.** In 10:00–11:00 LST, if a running max M °F is known from the existing METAR/ASOS archive: look at the band containing M and the band above it. Record the YES ask size ≥ 1, if any. An "offer" is an ask ≤ 0.15. No fill, no PnL.

**Entry / exit.** None. If offers exist, a second document must pre-register a settlement test before any truth file is joined. That document is not this one.

**Data.** Quote tape plus the METAR archive under `/mnt/storage/breezy/us_source_archive/metar-routine` (directory exists; row-level coverage was not counted in this round). Window: 2026-09-21..2026-10-30. M1's three UTC windows stay untouched (L-34).

**Nautilus.** None. A backtest-only `CurrentRungHold` replay (`current_rung_hold_paper_replay.py` line 1332 calls `backtest`) answers a different, already-failed question (take the current rung). Do not retune it onto this hour.

**Backtest spec.** Offer census only. `market_calibration_scan.WINDOWS` (lines 152–156) is D−1 18Z, D 12Z, D 17Z UTC and must not be edited to sneak this hour in.

**Pre-registered criterion.** Denominator = station-days with both a METAR running max and a Depth10 frame in that hour. PASS only if the neighbor band (the one above M) shows an ask ≤ 0.15 on at least 20% of the denominator, and the denominator is ≥ 40. 

**Kill.** Rate < 5%, or denominator < 40. Kill ends late-day rounding designs on PM.us. Power: do not compute a PnL MDE. M1 already showed a 3–8¢ effect is invisible at this sample.

### Card E — Kalshi basis, then scale

**Thesis.** Two settlements of one station-day can differ, and 24 cities change the sample size. Neither statement is an edge until the difference is measured per station and a book exists to trade it. This card does not authorize the measurement's fetch. WA-2 is a draft (`WA-2_stage0_prereg.md`); its acceptance line (n ≥ 90, Wilson lower bound > 0.99) is the right line and is not amended here.

**Signal.** After a reviewed reconciliation, and only on an EXCLUDED station with a named mechanism (not a 1% scatter): the signal is "CLI band ≠ TWC band" known from public obs before both venues stop trading. Entry would be buy the side that pays on each venue, qty 1, only where both asks sum with fees to less than 1. No such order can be simulated today.

**Data that exists.** Five settled-market JSON files and `candles.jsonl` for KXHIGH of CHI, LAX, MIA, NY, SFO. Data that does not: a Kalshi Depth10 catalog, LOW series, the other 19 cities, a TWC-vs-CLI table.

**Nautilus.** The harness venue is `POLYMARKET_US` (`backtest_harness.py` lines 711–712). There is no Kalshi `add_venue` block. Building one would be a new venue config, which this round does not propose. `k1_kalshi_prior.py` stays byte-unchanged (WA-2 invariant).

**Backtest spec.** None. The bot cannot run Card E on the current harness. A paper number from `candles.jsonl` is not a backtest and must not be quoted as one.

**Pre-registered criterion.** Inherited from K-2a §3, not reinvented: a station is tradable for a basis strategy only if it is EXCLUDED by the Wilson test for a reason a reviewer writes down, on n ≥ 90, HIGH and LOW separate. PASS of **admission** (agreement lower bound > 0.99) is a KILL for the basis trade on that station.

**Kill.** Zero excluded stations, or no Depth10-equivalent Kalshi tape by the time admission finishes. Also kill if the only divergences are amendments and voids (K-2a counts those as misses, not as signal).

## 3. Experiment order

Cheapest kill first. Each row is one bot job. Do not start the next settlement-reading job. Cards A–D do not read settlement.

| Order | Job | Decides |
|---|---|---|
| 1 | Card A, Σask on 2026-09-21..2026-10-30, one instant per station-day | If kill: no ladder lock. Expected |
| 2 | Card A, HIGH/LOW impossible pairs, same days | If kill: no joint-structure trade |
| 3 | Card B, touch size on 2026-10-17..2026-10-30 | If kill: stop designing PM.us makers. This is the audit's residual, and the published book already points at kill |
| 4 | Card D, 10:00–11:00 LST asks | If kill: L-9 holds in the morning too |
| 5 | Card C, 120 ms markout, days through 2026-10-13 | If kill: no stale-forecast take |
| 6 | Stop | If 1–5 kill, PM.us has no open cell that clears a criterion written in advance. Card E waits on a reviewed WA-2 and a tape this catalog does not have. Do not invent a runner for it |

A PASS on 1 or 2 is the only result that earns a later engine run, and that run still has to be pre-registered in a new note before truth is joined. A PASS on 3 earns a paper queue study under the M1-v3 fence, not a live change. P4 is not an input to these jobs and these jobs are not an input to P4.

## 4. Not verified, and what was assumed

Not verified in this round:

- Operator cap magnitudes. Not read, not set.
- Maker fee sign on a real weather fill. Zero maker fills since the arm date, so the rebate of −0.0125 pinned in the skill is still an assumption. Every number above uses taker θ = 0.0695 as a cost, never a rebate. A rebate would matter at 99¢ (a flat 1.25¢ dwarfs a 0.5¢ edge) and is unidentified.
- `ts_event` min and max inside parquet. The span 2026-08-30..2026-11-01 is from **directory names** (63 distinct dates, 2,041 depth dirs). 2026-11-01 is a listed day as of this writing, not a settled day. Live-instance directory mtimes run 2026-09-02..2026-10-31 (101 instances).
- That all 204 `low` directories are real LOW ladders rather than a substring hit.
- Trade-tick quantity unit (contracts vs dollars). The maker spec still marks it unresolved. Card B does not need prints.
- Row counts inside `metar-routine`, the NBP store, and `settlement_truth.parquet` (the parquet file is present, about 1.1 MB; contents not scanned).
- Whether `~/.local/share/breezy/catalog/quote_tape/polymarket_us` and `/mnt/storage/breezy/catalog/quote_tape/polymarket_us` are a symlink or a bind. They resolve to the same path.
- Kalshi `candles.jsonl` schema. Not opened. Not a depth tape.
- The 9% skip, the "recorder sees 84 of 119 markets", and "D0+ bid size p50 about 55" are taken from the operator brief and from `PREREG_v1` / the audit. Not recomputed.
- `wp7b_market_as_forecaster.py` still computes Σask the way the 2026-09-20 ruling describes. The ruling was checked; the function body was not re-read line by line.

Assumed, and used:

- P4's §5 queue description applies to the NO touch and not only to our 89¢ order. The recount in Card B is what would falsify that assumption.
- Complete-partition logic from the forecast-edge note (abutting integer bands) still matches the slugs. Card A must re-check abutment the way that note did, or refuse the day.
- One instant per station-day is enough to kill a lock. It is not enough to size one.
- No candidate here may consume M1-v3's forward labels, P4's α, or the Stage 0 verdict ledger.
