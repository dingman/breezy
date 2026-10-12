# Strategy specification — `pm_us_no_ladder_maker` (current: v0.3, 2026-10-12)

Status: DESIGN ARTIFACT, NOT REGISTERED, NOT EVALUATED. No Nautilus report exists
for any version. Nothing in this file is a performance claim.

Role split (binding): Claude designs; the Breezy/Nautilus bot backtests,
evaluates, promotes, deploys, arms, and monitors. This file is a specification
for the bot to evaluate, never a substitute evaluation.

Relationship to standing rulings: this is a **T2 candidate** under
`docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` ("A new family with its own
prereg whose floor passes the §4.6 gate for its own mix"). It does not touch,
amend, or reopen any closed family. The NO-TRADE ruling stays in force until the
bot's own gates pass. It is not yet a prereg and freezes nothing.

Execution plans: `docs/plans/backlog/MAKER_2026-10-12/` (S1–S5). Where a plan
and this spec disagree, the spec version named in the plan header governs until
the plan is revised.

---

## 1. Hypothesis

**H-MAKER-NO.** On Polymarket.us daily-HIGH ladders (5 cities, six rungs), the
ask ladder carries a persistent overround (mean Σask +0.29; zero instants ≤0.98,
`RULING_forecast_edge_programme_closes_2026-09-20.md`). A maker that rests NO
bids on rungs the forecast-conditional distribution puts far from the realized
high buys NO *below* the NO ask and earns part of that overround.

Why it could persist: the overround is paid by uninformed flow, not by a model;
it survived a full month of tape unchanged; the venue's subscription and listing
frictions deter professional makers on a 1-cent-tick, 6-rung surface.

Why this is not the closed taker hunt: the forecast ruling closed *predicting
better than the price* (market resolution 1.98× the forecast's). This family
does not need the forecast to out-resolve the price. It needs the forecast to be
*reliable* in the far tails (p_NO ≥ 0.94), the one property the ruling measured
as the forecast's strength (reliability 0.0087 vs market 0.0267). The ruling
names the maker hypothesis as "never refuted by this work".

Hostile prior evidence, stated plainly: `pm_us_crh_rest_v5` (a different
placement rule, YES side, proxy fills) was underpowered and negative (19 proxy
fills, mean P&L per fill −0.134 / −0.334, `RESTING_BID_HUNT_2026-09-16.md` §2),
and that plan already warned that resting bids are picked off when the
observation moves against them (E[pnl | fill] < 0, lines 162-177). FQ v1 lost
43.7% of its money to TAIL events. The M1 scan found no positive cell. The
cheap-YES-loser evidence does **not** automatically transfer to maker fills.

**What would falsify it: adverse selection.** If NO bids fill disproportionately
on the station-days where the tail occurs, the realized win rate falls below the
bid-implied breakeven and the family loses. §6.9 is a pre-specified screen for
exactly this, and it is a promotion gate (§7.9).

## 2. Inputs (all already ingested; nothing new to build for data)

| Input | Source in repo | Use |
|---|---|---|
| Forecast predictive distribution of daily HIGH | NBM NBP quantiles via the FQ `quantile_actor` + sha-pinned calibration artefact (`deploy/families/artefacts/nbp_calibration_*.json`); cycles 13Z/19Z/01Z | p_YES(rung) = P(high ∈ [A,B] inclusive); p_NO = 1 − p_YES (point estimate; bounds reported) |
| Live book | `OrderBookDepth10` (bids and asks, 10 levels; empty side padded with a size-0 level); the NO book arrives via the YES slug subscription | bid placement, queue estimate |
| Trade prints | `trade_tick` stream in the quote-tape catalog (published on the YES leg only, from 2026-09-17; `TRADE_QUANTITY_UNIT` UNRESOLVED, `parsing.py:225-231`, three hypotheses: contracts, USD YES notional, USD taker notional) | fill simulation in evaluation |
| Observations | existing METAR/ASOS ingest (integer-°C 5-min rows, 20–45 min lag) | kill-switch only, never a signal |
| Settlement truth | NWS CLI FINAL via `breezy-truth-*` timers (`settlement_truth.parquet`); CLI FINAL wins conflicts | outcome labels |
| Fee | per-market `feeCoefficient` (taker θ = 0.0695 since 09-17), fee = θ·C·p·(1−p); the maker coefficient is read from venue fill fields, never assumed (the skill pins a −0.0125 rebate; if the wire shows a positive maker fee, runs under taker θ are unevaluable and the bot says so) | net edge |

Stations: LAX, MDW, MIA, SFO. **NYC excluded** (the config refuses KNYC; no NBS
archive for NYC; hourly-only obs). Reopen NYC only in a later revision with its
own calibration evidence.

## 3. Decision rule (per station-day, per rung, NO leg only)

```
constants: P_MIN = 0.94, B_CAP = 0.80, E_MIN = 0.10, B_FLOOR = 0.70,
           STALE_H = 8, MAX_RUNGS = 2, CANCEL_LST = 09:00

for each listed station-day S and each rung R of S:
  on each forecast release, book update, and clock alert:
    vector = latest forecast vector for S (value_at); if vector.climate_day != S.day:
             abstain "forecast_day_mismatch" and cancel any resting bid on S
    age    = now - vector.available_at                # repo convention
    if age > STALE_H hours: cancel all bids on S; continue
    p_no   = 1 - P_model(high_S ∈ R)                 # inclusive [A,B], point estimate
    if p_no < P_MIN: cancel any resting bid on (S,R); continue
    b_max  = min(B_CAP, p_no - E_MIN - fee_est(b))
    if b_max < B_FLOOR: cancel; continue              # no bids below 0.70
    best_bid = top of NO bid book EXCLUDING our own resting order (size-0 pad ignored)
    no_ask   = best NO ask
    bid = min(b_max, best_bid + 0.01, no_ask - 0.01)   # NEVER cross; maker only
    if the NO bid side is empty: bid = min(b_max, no_ask - 0.01)
    if bid < B_FLOOR: cancel; continue
    rest limit BUY NO qty=1 at bid, time-in-force GTD with
      expire_time = min(S.day CANCEL_LST, permit.expires_at, end of booking UTC day)
    never post_only unless the venue requires it
    if a resting bid exists at a different price: cancel-replace (new episode)
  hard cancels (all resting bids of S), TIME-TRIGGERED by native clock alerts
  (Nautilus clock.set_time_alert) and by venue-side GTD expiry, never only on
  the next market event:
    - S.day CANCEL_LST (backstop; with STALE_H = 8 the forecast rule usually binds first)
    - any observation for S within 1 rung (2 °F) of R's lower edge; with an
      integer-°C observation the band is widened to the full 1.8 °F ambiguity
    - process stop (cancel-on-stop is the restart contract; a relaunch re-posts
      with a new episode), permit expiry, or family halt
  filled positions: HOLD TO SETTLEMENT. No exit leg (exit seam is unarmed).
```

Effective resting window (the bot reports it, Claude does not assume it): with
cycles at 13Z/19Z/01Z and STALE_H = 8, the forecast rule alone would allow
bids for day S from the first same-day vector (the D−1 13Z cycle) until about
11Z on S. In practice the **permit binds first**: the node launches daily at
16:50Z and the permit lasts 10 h (`trade_supervisor_core.py:37-38`,
`safety.py:172`), so under the current schedule bids rest only from launch to
about 02:50Z on S, roughly 10 hours, all before the station's local climate
day begins; the observation cancel therefore never fires in that window. A
longer window needs a schedule or permit-TTL change, which is a separate
ruling, not a knob of this spec. All interruptions (permit, boot, relaunch)
are cancels with re-posts. Every interruption
cancels and re-posts, which resets queue position; the fill-rate clock in
§9.15 counts that churn, and Stage 0 simulates the same process schedule so its
fill rate transfers.

Abstention (no bid at all on S): forecast missing/stale/for another climate
day; market shape drift refused by the exec layer; AMBIGUOUS intent open on S;
family halt set; any venue field outside the allowlist; S not listed by D−1
12:00Z; NO ask at or below the intended bid (marketable: never cross).

Contract selection bound: at most **MAX_RUNGS = 2** rungs per station-day (the
two lowest p_YES rungs that pass P_MIN), never adjacent to the forecast modal
rung, both bids ≥ B_FLOOR. Two NO positions on one ladder are mutually exclusive
in loss (at most one rung settles YES), so stacking adds expectancy without a
second tail exposure. **Live precondition:** the existing
`exclusive_bucket_conflict` guard may group sibling NO legs by `event_key`
(`risk.py:433-442`); the family needs a reviewed per-family
`allow_overlapping_exclusive_yes`-style admission for NO legs, verified by a
test, before the PREREG freezes. If that admission is refused, MAX_RUNGS = 1
and the sample clock in §9.15 doubles. Two rungs are **not** two independent
weather draws: every statistic in §6 is reported on both the position unit and
the station-day unit, and the gates use the stricter.

Breakeven arithmetic (peer-verified; the bot re-derives it from realized
bids, Claude never substitutes it for a measurement). EV per contract at win
rate w and bid b is `w − (b + fee)`, fee = θ·b·(1−b):

| bid | fee | w* (breakeven) | EV @ w=0.85 | EV @ 0.90 | EV @ 0.94 |
|---:|---:|---:|---:|---:|---:|
| 0.70 | 0.0146 | 0.7146 | +0.135 | +0.185 | +0.225 |
| 0.75 | 0.0130 | 0.7630 | +0.087 | +0.137 | +0.177 |
| 0.80 | 0.0111 | 0.8111 | +0.039 | +0.089 | +0.129 |
| 0.85 | 0.0089 | 0.8589 | −0.009 | +0.041 | +0.081 |

Consequence: with B_CAP = 0.80 an observed 85% win rate is positive-EV in point
estimate only. For the **Wilson lower bound** (n = 200, iid) to clear breakeven
the observed rate must be ≥ 0.87 at b = 0.80 and ≥ 0.91 at b = 0.85; clustering
makes the bound worse, not better. Observed 0.85 at n = 200 has an iid lower
bound of 0.794. The gate in §7 therefore checks net expectancy's one-sided
bound directly and reports the win-rate bound as a separate number.

A bid that is filled as TAKER (a race in which our order crosses) is counted
separately: it is in P&L but not in the maker win rate, and it is reported.

## 4. Sizing, exposure, risk (inside existing controls)

- Quantity 1 contract per order (code-locked `order_quantity = 1`).
- Per order cost ≤ the operator per-position cap; daily notional ≤ the operator
  daily budget; both enforced by `DailySpendLedger.authorize_order_cost`. The
  spec names no value for either.
- Resting exposure is registered at arm under the intent key and settled on
  cancel or fill through `settle()` only; it counts against open-exposure
  headroom (`_require_exposure_headroom_locked`); the strategy cancels rather
  than queues when headroom is refused.
- Structural limits enforced as pure checks in the strategy's decide step and
  counted by `RefusalCounter` (the shadow run has no portfolio, so
  `RiskManager.evaluate_order` is vacuous there): qty 1, ≤ MAX_RUNGS per
  station-day, ≤ 8 simultaneous rests, `allow_short = False` always. NO is
  bought as the NO instrument.
- **One loss stop:** the A1 loss floor on the station-day clock, exactly the
  object the S3 reachability check certifies and the PREREG freezes. The v0.2
  "LD-OBF on Wilson every 10 positions" is dropped (two stops would need two
  reachability proofs). The stop's variance carries the cluster design-effect
  inflation (1.5 ceiling); the stop is a harm stop, outside the RA-13 efficacy
  α spend; looks are ordered by settlement time.
- **Reachability pre-check before freeze** (the check that killed FQ v2): the
  A1 loss floor must not freeze as `unreachable_veto` for this family's own mix
  at the Stage 0 **stressed** fill rate. The existing tooling is FQ-hardwired
  and must be parameterised (S3). If the floor is unreachable, the family is
  not registrable and this file says so instead of being frozen.

## 5. Platform independence

The rule uses only: a calibrated predictive distribution, a two-sided book, a
per-market fee coefficient, inclusive band semantics, and an authoritative
settlement value. Kalshi needs a settlement-source swap (The Weather Company,
not NWS CLI) and its own ladder grammar; nothing in §3 is venue-specific beyond
`fee_est`, GTD support, and the NO-instrument representation.

## 6. Evaluation protocol for the bot (specified before any test)

**6.0 Feasibility facts the bot confirms first.** Executable price history
exists only from 2026-08-30 and trade prints only from 2026-09-17 (forward-only;
the venue has no historical book endpoint), so Stage 0's first replayable
climate day is 2026-09-18. The trade-print census stops at 2026-09-25. Reading
tape after that date is governed by RA-13 B-3: a census does not lift it; a
dated SEARCH declaration does, and it forfeits those station-days for the
EDGE-4 revival trigger (S1 costs it; 14 are already SEARCH). Stage 0 and the
shadow run also fall inside the NBP holdout window frozen by
`RULING_holdout_freeze_and_forward_window_2026-10-03`; they read it only as
descriptive evidence under that ruling's clause 3, which is consistent with
Stage 0 being exploratory. There is no historical sample on which a maker fill
can be simulated at the 200-position scale. **The confirmatory evaluation is
therefore prospective**: a shadow run on the live tape, scored on NWS CLI FINAL
truth.

**Stage 0 (exploratory, never promotion evidence, the simplest direct path).**
Before any exec-path build, the bot replays the §3 rule over the censused
recorded tape with the §6.1 fill rule, simulating the live process schedule
(boot, 10 h permit, relaunch cancels), and reports: maker fill rate (base and
stressed, denominator = all covered bid-bearing station-days, never only
print-eligible days), realized bid distribution, win rate of simulated fills vs
the model's p_NO, bid-live hours per station, descriptive net expectancy with
its upper bound, and the §6.9 statistic. Verdict table, frozen before the run:
**NO-GO** (base fill rate < 0.10 point estimate, or §6.9 FAIL), **NOT-KILLED**
(base and stressed fill rate ≥ 0.10 and §6.9 PASS), **NOT-KILLED-UNSCREENED**
(fill rates pass but §6.9 is below its minimum power). Base passes but
stressed fails is NO-GO. A verdict requires the S1 station-day floor
(effective n ≥ 30 climate-date-adjusted); below it Stage 0 emits
UNDERPOWERED-WAIT with its n and interval, and no build starts. The word GO is
never emitted by Stage 0. A negative descriptive expectancy is reported, not a
kill.
If the quantity unit is only bracketed (USD, undecided between the two USD
hypotheses), the replay runs under both and the conservative one governs the
kill. NO-GO stops the family with no build. This is a `scripts/analysis` study
on data already on disk, not a new subsystem.

**6.1 Fill simulation (shadow).** Precondition: `TRADE_QUANTITY_UNIT` resolved
or bracketed. **Inversion:** prints are published on the YES leg; a resting NO
bid at b is filled by a YES **BUYER** print at p_yes ≥ 1 − b (NO price ≤ b) on
the same slug. Episode = one rest from t₀ to cancel, fill, or expiry;
cancel-replace, relaunch, and permit expiry start new episodes. Price-priority
trade-through rule: queue ahead Q₀ = displayed NO size at prices ≥ b at t₀ plus
our own 1; a BUYER print at NO price > b reduces Q₀ (it consumed better bids);
a BUYER print at NO price ≤ b first consumes the remaining Q₀, and the episode
is FILLED when cumulative such volume reaches Q₀ (Q₀ already includes our own
contract). Prints with ambiguous
aggressor (`NO_AGGRESSOR`) are never credited. When the NO bid side is empty no
fill is credited from an implied price. A marketability guard refuses episodes
whose book frame is stale or truncated (`DepthTruncation` records). Recorder
gaps (`custom_quote_tape_gap`) are subtracted from every episode. The mandatory
stress is Q₀ doubled, i.e. 2 × (size ahead + 1). One position = one completed
station-day-rung economic position at qty 1.

**6.2 Splits.** The development/holdout boundary and the calendar cap are
**calendar dates fixed in the PREREG before the run starts** (not a percentage
of a run whose length depends on the result). The holdout begins the day after
a one-calendar-day purge and is read once, outcome-blind, at a read target of
300 positions (200 × the 1.5 design-effect ceiling) and 200 station-days. Cluster
unit for every interval = **climate date**, with 7-day blocks for the
confirmatory interval (same-station persistence) and climate-date clusters
reported beside it. Report effective n = positions / realised design effect.

**6.3 Candidate-search budget: zero planned revisions.** A change after the
freeze is a fork; it becomes a new family version with its own PREREG and its
own α allocation. §7.4 therefore reads "revisions = 0; α from the ledger".

**6.4 Minimum sample.** Gate 2 uses the realised effective n on the holdout:
≥ 200 effective positions and ≥ 200 station-days, whichever binds.

**6.5 Costs and outcomes.** Taker fee formula at the observed θ per market,
maker coefficient only as read from the wire; **no** midpoint fills; capital
lockup from fill to settlement (D+1 08:00 ET, or 11:00 ET on CLI/METAR
conflict); a position unresolved past D+14 is a LOSS in the primary
calculation; a void is a refund minus fee (refund assumed 0 until verified);
corrections reported separately; CLI FINAL wins conflicts.

**6.6 Baselines (report-only, not a gate; minimum n 30 each).** (a)
price-matched taker: buy NO at the ask on the same rungs at the same instants;
(b) forecast-only: FQ-style take at the same p_NO without the maker wait. Units:
per eligible rung-day and per unit of deployed capital.

**6.7 Stress.** Gated (point estimates, re-decided): fill rule at 2 × (size
ahead + 1); forecast quantiles shifted ±1 °F (re-decides p_NO and bids); θ
raised to 0.08; maker coefficient set to the taker coefficient. Report-only:
by-station leave-one-out; by-month split.

**6.8 Reporting.** Win rate with a cluster-bootstrap interval, n, effective n,
station-day n, net expectancy with its one-sided bound at α_family, portfolio
return on deployed capital, profit factor, max drawdown of the daily P&L
series, turnover, exposure by station, counts of losses / breakevens / voids /
unresolved / excluded / taker-filled, realized bid distribution, fill rate,
bid-live hours. Every number traces to committed episode records, forecast
provenance, bootstrap seed, and sha256-pinned inputs.

**6.9 Adverse-selection screen (pre-specified).** The VERDICT is computed on
the POOLED set of filled episodes (all p_NO strata together, so the minimum is
reachable at the §6.2 read target: ~12 expected losses at 300 positions); the
strata (0.94–0.96, 0.96–0.98, >0.98) are reported descriptively only. Compare
the realized YES-settlement rate of FILLED episodes (p_YES at the fill
instant) with the model's mean p_YES for those episodes and with the
settlement rate of UNFILLED episodes (scored counterfactually).
Non-inferiority form: FAIL if the filled loss rate exceeds 1.5 × model p_YES
(margin `as_margin`) by an exact tail test at α 0.05, or exceeds the unfilled
loss rate by the same test. A verdict needs at least 10 expected losses pooled;
below that the screen is UNSCREENED, never PASS. An outcome-blind power check
at a pre-registered day stops the run early as UNSCREENED-TERMINAL if the
pooled expected-loss count cannot reach 10 by the calendar cap.
A FAIL is terminal for the hypothesis as stated. This is a screen for GROSS
adverse selection with a power line, never proof of its absence.

## 7. Promotion gate (bot-enforced, all required)

1. Observed win rate ≥ 0.85 on the untouched holdout (point estimate), with the
   cluster-bootstrap lower bound reported beside it.
2. Realised effective n ≥ 200 positions and ≥ 200 station-days on the holdout.
3. Net expectancy and portfolio return > 0 after costs; the one-sided lower
   bound on expectancy at α_family (nested in the RA-13 ledger, 7-day block
   clusters) excludes 0.
4. Revisions = 0; α_family from the ledger; a revised family is a new PREREG.
5. All §4 limits respected; every gated §6.7 stress remains net-positive.
6. No leakage (every decision uses forecasts with `available_at ≤ decision
   time`, the repo's visibility operator, `forecast_state.py:321`), no
   selective exclusion, no mid fills, no un-censused tape in the sample.
7. Integration checks + live-data shadow run pass (signal, pricing, order
   construction, settlement mapping with inclusive [A,B], risk enforcement).
8. Existing permit/credentials/caps support live operation; the A1 loss-floor
   reachability check passes for this family's own mix; S4 merged gate-green
   with its venue positive controls (resting GTD accepted, cancel scoped).
9. §6.9 PASS on the holdout (UNSCREENED is not PASS).

Claude reports "observed 85%" and "lower bound" as two different numbers and
never claims the second from the first.

## 8. Design history

| Version | Date | Hypothesis / change | Nautilus report | Verdict |
|---|---|---|---|---|
| v0.1 | 2026-10-12 | H-MAKER-NO, initial parameters (P_MIN .94, B_CAP .80, E_MIN .10, cancel 09:00 LST, 2 rungs/station-day, 4 stations) | none | peer-reviewed SOUND-WITH-CAVEATS ×2; superseded |
| v0.2 | 2026-10-12 | Hostile prior evidence; corrected breakeven table; §6.9 gate; maker-side print matching; station-day unit; α nested in RA-13; Stage 0; exec-path blockers in §9 | none | superseded after 11 plan reviews |
| v0.3 | 2026-10-12 | Fixes from the S1–S5 r1 reviews and r2 plans: §6.1 inversion corrected (YES BUYER at p_yes ≥ 1 − b) with a price-priority trade-through rule, episodes, gap subtraction, marketability guard; Stage 0 verdict table (NO-GO / NOT-KILLED / NOT-KILLED-UNSCREENED), denominator and first replayable day 09-18; forecast climate-day match, age from `available_at`, STALE_H 8 h; GTD with expire ≤ min(09:00 LST, permit, UTC day); never-cross rule; cancel-on-stop restart contract; B_FLOOR 0.70; MAX_RUNGS 2 conditional on the exclusive-conflict admission; one loss stop (A1 station-day clock); zero planned revisions; calendar-date split, outcome-blind read target 300/200; unresolved = LOSS, void = refund − fee; baselines report-only; gated vs report-only stresses; §6.9 non-inferiority with a 10-loss minimum; gate 3 one-sided at α_family; leakage operator `≤`; taker fills counted separately; honest sample clock and disk/tape facts (§9) | none | not evaluated |

Peer-review record (internal gate input, not evidence): v0.1 reviewed by a
bot-fit reviewer and a domain-math reviewer; the five S1–S5 r1 plans reviewed
by eleven reviewers (`docs/plans/backlog/MAKER_2026-10-12/reviews/`); all
findings folded into v0.3 or the r2 plans.

## 9. Integration gaps (the bot cannot run the requested loop today)

Blockers for any live or shadow-with-orders run:
1. **The exec path is IOC-only at four layers.** `exec/submit_chain.py:331,448`
   refuse any non-IOC order and `:344,461` refuse post_only/display/expire;
   `exec/client.py:5584` hard-codes IOC; `_cancel_order` (`client.py:7587-7600`)
   unconditionally rejects and modify/cancel-all raise `NotImplementedError`.
   Resting bids and every cancel in §3 have **no venue path**. Building one
   touches the byte-pinned exec client and the NO-SEND/egress pins (WIDENED-row
   discipline), not just strategy code (S4).
2. **The K=1 submit slot** is retired only on IOC outcomes; a resting accept
   needs a new retirement reason that releases the slot (no new intent model
   is needed; S4).
3. **`TRADE_QUANTITY_UNIT` is UNRESOLVED** (`parsing.py:225-231`); prints are
   YES-leg only. §6.1 cannot run until the unit is resolved or bracketed (S1).

Gaps for the evaluation loop:
4. No historical backtest of executable prices is possible (forward-only tape
   from 2026-08-30, prints from 09-17); trade-print census after 2026-09-25
   missing; post-freeze tape needs a dated SEARCH declaration (S1).
5. No maker fill simulator exists; §6.1 and Stage 0 are a build (S2, a
   `scripts/analysis` study, the smallest build on this list).
6. The FQ calibration artefact has no exposed P(high ∈ [A,B]) API for an
   arbitrary rung, and the FQ decision path is gated to D+1 takes
   (`decision.py:138 NotDPlus1`) under the permanent F6 veto; p_NO needs its own
   loader, with a tail-reliability table from out-of-sample days.
7. The observation kill-switch and the timed cancels have no cancel actuator
   (exit seam AUD-07 is built and UNARMED); native clock alerts exist (S4/S5).
8. A1 reachability tooling (`fq_loss_floor_mc_*.py`, `fq_loss_floor_np_bound.py`)
   is hard-wired to FQ mixes; an all-NO world vetoes on `g1_unreachable` by
   construction. Must be parameterised and run before freeze (S3).
9. No climate-date / block cluster bootstrap, design-effect, purge or
   read-once tooling for this family; the M1-v3 read-once pattern is reusable
   (S5).
10. No standard win-rate / drawdown / profit-factor / turnover outputs;
    `portfolio_roi_report` emits ROI vs baselines only (S5).
11. Strategy parameters are not manifest-declarative; a new rule needs a new
    `composition_kind` and strategy code (S5).
12. Promotion is advisory (`promotion_criteria` emits `PROPOSAL`, explicitly
    never arms); activation is a manual `BREEZY_SENDING_FAMILY_ID` edit plus
    supervisor restart plus a `live_orders_ruling`. No auto-promote-and-arm path
    exists (AUT-5b is an enum, not a code path). This programme does not build
    one.
13. No performance-deterioration demotion or auto-rollback of a sender.
14. No exit leg is armed; hold-to-settlement is a design choice and its losses
    are counted, never excluded.
15. Sample-size clock: 4 stations × ~0.91 listing × ≤2 rungs × maker fill rate
    (measured at Stage 0, stressed), with episodes cut by the 10 h permit,
    daily boot and relaunches, and gate 2 needing 200 **effective** positions
    on the **holdout alone**. At a 0.3 fill rate that is roughly 230–320
    shadow days in total; at 0.1 about 720; at 0.25 about 330; MAX_RUNGS = 1
    doubles each. Every one passes the 2027-01-25 RA-13 review date, which the
    PREREG must address explicitly (a relative window is a label, not a
    licence). No faster route exists that does not widen risk.
16. Trade prints exist only from 2026-09-17 and the maker window crosses the
    09:00Z instance rotation, so Stage 0 has at most ~25–30 pre-freeze
    station-days; the rest needs the SEARCH declaration (S1).
17. Disk: ~5 GB free at planning time; collectors and gates refuse under 10 GB.
    Every step's WP0 clears space first.
18. The boot-sweep cancel-all on family slugs cancels any manual order resting
    on those slugs; accepted and documented (S4).
