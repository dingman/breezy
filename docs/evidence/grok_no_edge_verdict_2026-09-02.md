# Grok design memo — no harvestable long-only edge on Polymarket.us daily-high books (2026-09-02)

Strategy design is routed to Grok by standing operator instruction. Verbatim Grok output
to the brief at the end of this file, read-only (`--permission-mode plan`,
`--disallowed-tools spawn_subagent,run_terminal_command`) against tree `135fc1f`.
An independent Claude evidence survey reached the same three refutations with the same
citations before this brief was written. Claude verification note: the memo says
`src/.../exec/` is empty (L-3) — stale; R-3..R-6.5a have landed, and R-6.5P is built.
That does not touch the verdict. Decisions taken: `docs/core/PROGRESS.md`.

---


## Invariants
Nautilus Trader is immutable. `allow_short` stays `False` (long-only; every sell reduces a long). Never weaken or delete a safety, settlement, barrier, or contract test. Never assign an operator-reserved control (max daily budget, max per position — unset, `docs/core/PROGRESS.md`). Never touch live-trading enablement or the NO-SEND firewall. The bot has never sent a live order; this memo asks for none.

## 1. Families — reject, then the only remainder

**(a) Pre-lock afternoon taker on true R(t) — reject as a family; measure once, then kill.**  
This is H3/H4 in costume (`docs/strategies/archive/H3_intraday_running_max_lock.md`, `H4_headroom1_afternoon_lock.md`). L-9 already closed it: “identify the near-certain rung, then buy it” has no seller (`docs/core/LESSONS.md`). H4 on 2026-08-31: after trigger, h=1 held 375/375 MDW, 381/381 MIA, 372/372 SFO, **ask present 0%**; other rungs offered 100% at 0.01–0.03 (`docs/evidence/h4_preliminary_economic_read_2026-09-01.md` §2–§4.1). Post-print: 0 asks / 3,332 winner rows (`docs/evidence/print_lock_refuted_2026-09-01.md`). `running_extreme_lock` reads CLI *preliminary* `tmax_f`, not a running max (`docs/plans/intraday_observation_ingest_2026-09-01.md` §1.7; `running_extreme_lock/decision.py`).  

The untested hole is real as a **coverage** gap, not a mechanism: H4 missed the early trigger window (§1); LAX winner was offered on 7/63 snapshots at **0.99**, all before 18:00 LST — not 0.50–0.90. MM watches the same public ASOS; Breezy is not faster (L-9: 300 s CLI poll). A 0.99 taker on a still-climbable rung pays `a + 0.06 a (1−a) ≈ 0.9906` for a contract that is not yet CLI-certain (H3 kill: METAR↔CLI basis at h=0 is 15–55% by station). No information edge, no price.

**(b) Long-only maker — reject.**  
Post-lock, NYC winner was `bids[0]=0.99 × 7682.70`, asks empty. A rest bid ≤0.99 joins a queue to buy a contract that pays $1 at 08:00 ET. Counterparty must *sell* YES. Rational hold-to-settlement dominates: sell @0.99 vs $1 loses a cent; maker rebate `0.0125·0.99·0.01 ≈ 0.00012` does not close it. Pre-lock, the people who sell as R(t) jumps sell the **previous** favorite (now a cheap loser), not the new winner. A bid on the current R(t) rung is filled by (i) profit-takers who think the high goes higher, or (ii) an MM dumping inventory — both adversely selected against a slower or equal observer. Rebate at p=0.30 is `0.0125·0.3·0.7 ≈ 0.0026` / contract; one wrong-rung fill wipes it.  

Also unevaluable and unexecutable: `MakerRebateUnmodelledError` refuses post-only until a real maker fill is observed (`src/breezy/adapters/polymarket_us/errors.py`); read-only HTTP signs GET only (`MethodNotPermittedError`); `src/breezy/adapters/polymarket_us/exec/` is empty (L-3). No retail trade history to measure markout (`polymarket-us-integration` discovery 2026-09-02).

**(c) Losers-offered-cheap / winner-bid-rich, no short — mostly dead; one thin remainder, not a GO.**  
Long-only cannot sell the 0.99 bid and cannot lift an absent winner ask. Remaining buys are cheap YES:

| Object | Status |
|---|---|
| Post-peak 0.01 dump | Lottery already lost (L-9 amendment; H1/H2 tails 4–8 °F out, trigger 0/4) |
| D−1 cheap open (K1/H5/`lagged_anomaly_tail`) | Kalshi prior, modern exhaustive era: ≤0.02 n=456 k=2; ≤0.03 n=1002 k=12; ≤0.05 n=2317 k=35 — Wilson 95% upper below fee-inclusive BE; all five stations DEAD at ≤0.05; 1¢ n=133 all NO, needs 356 (`docs/evidence/k1_kalshi_prior_2026-09-02.md`). Our tape n=0 settled (`docs/evidence/k1_cheap_open_2026-09-01.md`). H5’s own K1 was the family kill (`docs/strategies/H5_grok_design_2026-09-01.md`). Forecast family independently dead (`docs/evidence/grok_forecast_family_verdict_2026-09-02.md`) |
| CLI-basis boundary (candidate #2) | Settlement-side **real and thin**: `P(win\|setup, h≥17)` Wilson lower **0.1213** pooled n=101,590 (~1.9× BE at a 5¢ ask); NYC discarded (L-13 cadence). **Not a GO**: archive ≠ offered population; offer-gate n=1 dense event (LAX 2026-08-31 `gte80f` @0.01) **LOST** (settled 79); adverse selection needs ~245 offered settlements, ~1.5 yr; clip 250 contracts = $2.50–$12.50 (`docs/core/PROGRESS.md`; `docs/evidence/cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md`; `docs/evidence/cli_basis_offer_gate_settlement_2026-09-02T053500Z.md`) |

G-02 already **NO-GO** on the execution build at ~$3–15/day (`docs/evidence/roi_feasibility_2026-08-26.md`). BL-25: 57% of $24.53 notionals exceed level-0; p90 walk 0.137.

**(d) No family; pivot.**  
**Pivot = stop weather-strategy implementation on this book class.** Keep `breezy-quote-tape` and the nightly offer-gate (free option on book-structure change: winner starts being offered inside (0.05, 0.95), or two-sided mids appear). Do **not** pivot to Kalshi weather cheap-open — same settlement product, family already dead there. A different Polymarket.us class (sports, 0.001 tick, min qty 1) is a **new discovery**, not a strategy; no evidence it has a long-only edge. Do not spend forecast ingest, BL-24, or EXEC spine to hunt an edge the book does not offer.

## 2. Single first measurement (read-only)

**Join** (analysis script, not a Nautilus `Strategy`; L-8 preflight first):

- Tape: `OrderBookDepth10` under `~/.local/share/breezy/catalog/quote_tape/polymarket_us`, `ts_event` clock.
- R(t): IEM ASOS fetch **2026-08-30 → last complete climate day**, 5-min LAX/MDW/MIA/SFO only (NYC hourly = contaminated, L-13). `R(t) = max` of the same whole-°F basis H4 used, observations with `valid ≤ t`. Cache-end vs H4/offer-gate 2026-08-31 rows is **UNVERIFIED** — fetch anyway; do not trust overlap.
- Settlement: CLI final `tmax_f`, `is_final`, not superseded. Winner = unique rung with `contains(tmax_f)`.

**Quantity.** Per dense station-day, at every depth snapshot in local-standard 12:00–17:00: winner `ask_px`, `ask_sz`, `hour_lst`, `m = R(t) − winner_floor`. Report (i) any snapshot with winner ask ∈ **(0.05, 0.95)** while `R(t)` inside the winner rung (`m ≥ 0` and `R(t) ≤ ceiling`); (ii) first time winner ask vanishes; (iii) first time ask ≥ 0.99. One row per station-day: min ask in that cell, size at that min, coverage minutes.

**Sample to discriminate.** ≥ **15 afternoon-covered** dense station-days (≥30 min Depth10 in 12:00–17:00 LST). H4’s evening tail does not count. ~4 calendar days × 4 stations if coverage is real; wait if not.

**Kill in one sentence.** Dead if those 15 days contain **zero** winner asks in (0.05, 0.95) while R(t) is in-rung — the climb window is the 0.99/empty book L-9 already measured.

## 3. Kill criteria and budget (engineer-encodable)

`M_A` = measurement (2). `M_2` = offer-gate, dense stations, h≥17, first qualifying ask per station-day.

- **K-A (lock window):** `n_afternoon ≥ 15` AND `count(winner_ask ∈ (0.05, 0.95) ∧ R in-rung) = 0` → family A dead. Stop.
- **K-2 (basis remainder):** `n_offered ≥ 50` AND Wilson 95% **upper** of offered-win rate ≤ `ask + 0.06·ask·(1−ask)` (stratum threshold) → #2 dead. At 0/1 that bound is 1.0; do not trade the bound.
- **K-depth:** if a surviving cell’s level-0 size < 1.0 contract at the recorded ask, unexecutable (BL-25 / `insufficient_depth`).
- **K-programme:** G-02 stands until a cell clears K-A or K-2 *and* has lift-able size. No new strategy package, no BL-24, no forecast ingest, no exec client until then.

**Budget ceiling (engineering, not operator controls):** **$0 live notional.** Do not set max daily budget or max per position. Compute cost = one join script + one IEM fetch + unattended offer-gate. If K-A and K-2 both fire, strategy spend on this product is **zero**.

## 4. What must not be spent
(1)–(3) need **no live orders**: tape + IEM + CLI are public/read-only; HTTP write remains forbidden. After a pass that this memo does not expect: the first live-small would still be blocked on unset operator ceilings, empty `exec/`, NO-SEND, and `MakerRebateUnmodelledError` for any post-only. A later live-small, if ever authorized, would be a **taker IOC** on one dense station, one rung, size clipped to native `OrderBook.simulate_fills` and existing `RiskLimits` (not new operator values), hold-to-settlement, no flatten into the 0.3-lot bid — and only after K-A or K-2 actually leaves a cell alive with displayed size that persists to the next snapshot (H5 K5). Do not build that path now.

**UNVERIFIED:** ASOS cache end-date vs 2026-08-31 rows already cited; `expiration_ns`↔`endDate` per slug; bid-size stats on one-sided books (OQ-13); LAX 0.99 ask size; whether 2026-08-30/09-01 tapes actually cover 12:00–17:00 LST (H4 proves 08-31 East did not); Kalshi winner-offer analogue (candles, no size).


---

## The brief Grok answered

# Design brief — what strategy family, if any, survives on Polymarket.us daily-high weather books

You are the strategy designer for Breezy, a weather-prediction trading bot on Nautilus Trader 1.231.0 trading Polymarket.us daily-high-temperature bucket markets (5 stations: NYC, MIA, MDW/CHI, LAX, SFO; settles on the NWS CLI product; buckets are 2°F interiors plus open tails; prices in (0,1) on a 0.01 tick; taker fee θ·a·(1−a) with θ=0.06; settlement 08:00 America/New_York next morning). Work READ-ONLY, from files only: you have NO shell and NO subagents in this run — do not attempt `run_terminal_command` or `spawn_subagent`; every fact you need is in the cited Markdown under docs/ and the source under src/ and scripts/. Do the analysis yourself. Repo root is the cwd.

## Invariants (binding — restate them, do not violate them in any recommendation)
Nautilus Trader is immutable. `allow_short` stays `False` (long-only; every sell reduces a long). Never weaken or delete a safety/settlement/barrier/contract test. Never assign a value to an operator-reserved control (max daily budget, max per position). Never touch live-trading enablement or the NO-SEND execution-egress firewall. The bot has never sent a live order and this brief asks for NO live orders.

## The honest state (2026-09-02) — every family in the tree is dead or unexecutable
1. **Forecast family** (`forecast_mispricing`, `calibration_mean_reversion`, `forecast_revision`): KILLED by your own memo today — `docs/evidence/grok_forecast_family_verdict_2026-09-02.md`. Under honest σ (24h≈2.8°F) there is little or no defensible edge at real forecast leads; `min_entry_edge=0.06` was an artifact; Breezy ingests NO forecasts, so every backtest was synthetic.
2. **Observation-lock family** (`running_extreme_lock`, `cli_settlement_print_lock`): settlement-side gates PASS (`docs/evidence/observation_lock_falsification_2026-08-31.md`: p_stable 99.989%, open-tail p_hold 99.79%) but the family is REFUTED on the EXECUTION side three separate times (`docs/core/LESSONS.md` L-9): the settling rung is uniquely unoffered. Post-final-print: 0 asks in 3,332 pooled depth rows across five stations, while NYC level-0 shows `bids[0] = 0.99 × 7682.70` and every ask level `0.00 × 0.00` (`docs/evidence/print_lock_refuted_2026-09-01.md`). Pre-print, across every captured 2026-08-31 depth snapshot: asks on the settling rung MDW 0/58, MIA 0/54, NYC 0/56, SFO 0/59 — "winner uniquely unoffered" — while every OTHER rung was offered on 100% of snapshots at 0.01–0.03 (`docs/evidence/h4_preliminary_economic_read_2026-09-01.md` §4.1). One observation of a 0.99 ask on LAX `gte78lt79f` in 7 of 63 snapshots, all BEFORE 18:00 LST. Note also: `running_extreme_lock` does not actually read an intraday running max — it reads a CLI *preliminary* record; no intraday observation type exists in-bot (BL-24, `docs/plans/intraday_observation_ingest_2026-09-01.md`, peer-reviewed RESUME WITH AMENDMENTS, not implemented).
3. **Cheap D-1 open family** (K1, `docs/evidence/k1_cheap_open_2026-09-01.md`): buys cheap rungs (median entry ask 0.16, strata ≤0.01–0.05) at the D-1 open with no observation. On our tape n=0 settled. Kalshi prior over 30,323 settled markets (`docs/evidence/k1_kalshi_prior_2026-09-02.md`): in the modern exhaustive-bucket era, ask ≤0.02 n=456 k=2, ≤0.03 n=1002 k=12, ≤0.05 n=2317 k=35 — Wilson 95% upper bound well below fee-inclusive break-even at every cell; all five stations independently DEAD at ≤0.05; only the 1¢ stratum (n=133, all NO, needs 356) is underpowered. Candlesticks carry no size, so fillability is unverified.

**Book structure, as measured:** the only standing liquidity is (a) offers of YES at 0.01–0.03 on every rung that will lose, and (b) a large bid queue at 0.99 for the rung that will win. Median top-of-book bid across weather markets is 0.3 contracts (`docs/evidence/` BL-25: 57% of $24.53 orders exceed level-0 depth; p90 walk 0.137). A long-only taker therefore has: cheap losers to buy (K1 — dead) or nothing.

**Data in hand:** a live quote/depth tape under systemd since 2026-08-30 (Depth10 + QuoteTick, five stations, all rungs); ~5 years of 5-minute ASOS observations for LAX/MDW/MIA/SFO (NYC contaminated) in `~/.local/share/breezy/archive/settlement-alignment-cache`, ending 2026-01-02 — so NO overlap with the tape without a fresh IEM fetch (public, unauthenticated); the NWS CLI settlement archive 2020–2026; the Kalshi candlestick cache (no size). No forecast archive is ingested.

## What I need from you (design, not implementation)
1. **Is there any family with a defensible MECHANISM on this venue**, given the refutations above? Consider explicitly, and reject with reasons where warranted: (a) a pre-lock afternoon entry driven by a true intraday running max R(t) — buy the rung R(t) already implies while its ask still exists (the untested window: the winner is unoffered post-print and pre-print in evening snapshots, but was it offered at 0.5–0.9 mid-afternoon while R(t) was climbing into it?); (b) a MAKER role for a long-only bot — resting BUY bids on the likely winner below 0.99, filled by whoever sells into a rising running max — including who the counterparty would be and why they would sell; (c) any structure that exploits the losers-offered-cheap / winner-bid-rich asymmetry without shorting; (d) "no family; pivot" as a legitimate answer — say what the pivot would be (a different market class on the same venue? a different venue? a different role?) and what evidence would justify it.
2. **The single first measurement**, using ONLY data in hand plus an IEM ASOS fetch for 2026-08-30 onward: define the join (tape × R(t) × CLI settlement), the exact quantity (e.g. for each station-day, the ask price and size on the eventual winner as a function of the margin R(t) − rung_floor and of local time), the sample needed to discriminate, and the kill criteria. Name what would make this family dead in one sentence.
3. **Kill criteria and a budget ceiling** for the family you recommend, stated so an engineer can encode them.
4. **What must not be spent:** confirm no live orders are needed for (1)–(3), and say what a live-small step would be for AFTER the measurement passes, in one paragraph.

Be direct. If the honest answer is that this venue's weather books carry no long-only edge and the programme should stop spending on strategy until the book structure changes, say that first and defend it. Cite files by path. Mark anything you could not verify UNVERIFIED. Length: under 180 lines.
