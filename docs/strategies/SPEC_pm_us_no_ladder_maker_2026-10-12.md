# Strategy specification — `pm_us_no_ladder_maker` (current: v0.2, 2026-10-12)

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
bid-implied breakeven and the family loses. §6.9 is a pre-specified test for
exactly this, and it is a promotion gate (§7.9).

## 2. Inputs (all already ingested; nothing new to build for data)

| Input | Source in repo | Use |
|---|---|---|
| Forecast predictive distribution of daily HIGH | NBM NBP quantiles via the FQ `quantile_actor` + sha-pinned calibration artefact (`deploy/families/artefacts/nbp_calibration_*.json`) | p_YES(rung) = P(high ∈ [A,B] inclusive); p_NO = 1 − p_YES |
| Live book | `OrderBookDepth10` (bids and asks, 10 levels; empty side padded with a size-0 level) | bid placement, queue estimate |
| Trade prints | `trade_tick` stream in the quote-tape catalog (published on the YES leg only; `TRADE_QUANTITY_UNIT` is UNRESOLVED, `parsing.py:225-232`) | fill simulation in evaluation |
| Observations | existing METAR/ASOS ingest (integer-°C 5-min rows, 20–45 min lag) | kill-switch only, never a signal |
| Settlement truth | NWS CLI FINAL via `breezy-truth-*` timers (`settlement_truth.parquet`) | outcome labels |
| Fee | per-market `feeCoefficient` (θ = 0.0695 since 09-17), fee = θ·C·p·(1−p); maker coefficient read from the market, never assumed (the fee model today has the taker coefficient only) | net edge |

Stations: LAX, MDW, MIA, SFO. **NYC excluded** (the config refuses KNYC; no NBS
archive for NYC; hourly-only obs). Reopen NYC only in a later revision with its
own calibration evidence.

Forecast update cadence = the NBP release cadence (the bot states it in the
report; the spec does not assume a faster one).

## 3. Decision rule (per station-day, per rung, NO leg only)

```
for each listed station-day S and each rung R of S:
  at listing and at each forecast release:
    p_no   = 1 - P_model(high_S ∈ R)                 # inclusive [A,B]
    if p_no < P_MIN: cancel any resting bid on (S,R); continue   # P_MIN = 0.94
    b_max  = min(B_CAP, p_no - E_MIN - fee_est(b))    # B_CAP = 0.80, E_MIN = 0.10
    if b_max < B_FLOOR: cancel; continue              # B_FLOOR = 0.50 (no lottery bids)
    best_bid = top of NO bid book; if the NO bid side is empty, no implied
               price is used — the bid is placed at b_max
    bid = min(b_max, best_bid + 0.01)
    rest GTC limit BUY NO qty=1 at bid; never post_only (guard refuses post_only)
    if a resting bid exists at a different price: cancel-replace
      (queue position resets; the evaluation treats the replace as a new t0)
  hard cancels (all resting bids of S):
    - D 09:00 local standard time (before the hunt-window repricing, hours 10–11)
    - any observation for S within 1 rung (2 °F) of R's lower edge; with an
      integer-°C observation the band is widened to the full 1.8 °F ambiguity
    - forecast age > 6 h, or no forecast for S
    - p_no drops below P_MIN
  filled positions: HOLD TO SETTLEMENT. No exit leg (exit seam is unarmed).
```

Abstention (no bid at all on S): forecast missing/stale; market shape drift
refused by the exec layer; AMBIGUOUS intent open on S; family halt set; any
venue field outside the allowlist; S not listed by D−1 12:00Z.

Contract selection bound: at most **2 rungs per station-day** (the two lowest
p_YES rungs that pass P_MIN), never adjacent to the forecast modal rung. Two NO
positions on one ladder are mutually exclusive in loss (at most one rung
settles YES), so stacking adds expectancy without a second tail exposure. They
are **not** two independent weather draws: every statistic in §6 is reported on
both the position unit and the station-day unit, and the gates use the stricter.

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
the observed rate must be ≥ 0.87 at b = 0.80 and ≥ 0.91 at b = 0.85; climate-date
clustering makes the bound worse, not better. Observed 0.85 at n = 200 has an
iid lower bound of 0.794. The gate in §7 therefore checks net expectancy's CI
directly and reports the win-rate bound as a separate number.

## 4. Sizing, exposure, risk (inside existing controls)

- Quantity 1 contract per order (code-locked `order_quantity = 1`).
- Per order cost ≤ the operator per-position cap; daily notional ≤ the operator
  daily budget; both enforced by `DailySpendLedger.authorize_order_cost`. The
  spec names no value for either.
- Resting exposure counts against open-exposure headroom
  (`_require_exposure_headroom_locked`); the strategy cancels rather than queues
  when headroom is refused.
- `RiskLimits` tunables for this family: `min_model_edge = 0.10`,
  `max_simultaneous_positions = 8` (4 stations × 2 rungs), `exclusive_bucket_conflict`
  on, `max_event_notional` / `max_location_notional` at current defaults.
- `allow_short = False` always. NO is bought as the NO instrument.
- Loss stop: the family's own pre-registered group-sequential stop (LD-OBF on
  the Wilson bound, look every 10 completed positions), with α **allocated from
  the RA-13 programme-wide FWER budget by the prereg**, not fixed here.
- **Reachability pre-check before freeze** (the check that killed FQ v2): the
  A1 loss floor must not freeze as `unreachable_veto` for this family's own mix.
  The existing tooling is hard-wired to FQ mixes and must be parameterised
  (§9.8). If the floor is unreachable at the expected ~2 positions/day, the
  family is not registrable and this file says so instead of being frozen.

## 5. Platform independence

The rule uses only: a calibrated predictive distribution, a two-sided book, a
per-market fee coefficient, inclusive band semantics, and an authoritative
settlement value. Kalshi needs a settlement-source swap (The Weather Company,
not NWS CLI) and its own ladder grammar; nothing in §3 is venue-specific beyond
`fee_est` and the NO-instrument representation.

## 6. Evaluation protocol for the bot (specified before any test)

**6.0 Feasibility facts the bot confirms first.** Executable price history
exists only from 2026-08-30 (forward-only; the venue has no historical book
endpoint). The trade-print census stops at 2026-09-25, and RA-13 B-3 may bar
reads of tape after that date until a census is run. There is no historical
sample on which a maker fill can be simulated at the 200-position scale.
**The confirmatory evaluation is therefore prospective**: a shadow run on the
live tape, scored on NWS CLI FINAL truth, as the project already does for M1-v3.

**Stage 0 (exploratory, never promotion evidence, the simplest direct path).**
Before any exec-path build, the bot replays the §3 rule over the censused
recorded tape (2026-08-30 → last censused day) with the §6.1 fill rule and
reports: maker fill rate, realized bid distribution, win rate of simulated fills
vs the model's p_NO, and the §6.9 adverse-selection statistic. A Stage 0 fill
rate below 0.1, or a §6.9 FAIL, stops the family at v0.2 with no build. This is
a `scripts/analysis` study on data already on disk, not a new subsystem.

**6.1 Fill simulation (shadow).** Preconditions: `TRADE_QUANTITY_UNIT` resolved
(dollars vs contracts); YES→NO price inversion stated (a NO buy at b is a YES
print at price ≤ 1 − b with aggressor SELLER on the same slug). A resting bid at
b placed at t₀ counts FILLED only when cumulative *maker-side-matched* traded NO
size at price ≤ b after t₀ exceeds the displayed NO bid size at ≥ b at t₀ (we are
last in queue). Prints with ambiguous aggressor (`NO_AGGRESSOR`) are never
credited. A cancel-replace resets t₀. When the NO bid side is empty no fill is
credited from an implied price. Depth truncation: displayed size is a lower
bound, so the base rule is optimistic and §6.7's 2× stress is mandatory, not
optional. One position = one completed station-day-rung economic position;
partial fills aggregate.

**6.2 Splits.** Development window = first 60% of calendar days of the shadow
run; final holdout = last 40%, purged by one calendar day, read once. Cluster
unit for every interval = **climate date** (all stations on a date share a
synoptic regime). Report effective n = positions / design effect.

**6.3 Candidate-search budget.** ≤ 3 parameter revisions (P_MIN, B_CAP, E_MIN,
cancel hour) on the development window; the holdout is read once for the last
registered revision. Every revision, result and rejection is logged in §8.

**6.4 Minimum sample.** 200 completed positions on the holdout; raise to
200 × design effect if the climate-date design effect exceeds 1.5. Also report
the station-day count; gate 2 uses the smaller effective n.

**6.5 Costs.** Taker fee formula at the observed θ per market, maker coefficient
only as read from the wire (a wrong-sign fee makes the run unevaluable); **no**
midpoint fills; capital lockup from fill to settlement (D+1 08:00 ET, or 11:00
ET on CLI/METAR conflict); voids (7-day no-data rule) and corrections reported
separately and excluded from the win count; unresolved positions carried as
exposure.

**6.6 Baselines.** (a) price-matched taker: buy NO at the ask on the same rungs
at the same instants; (b) forecast-only: FQ-style take at the same p_NO without
the maker wait. The family must beat both on net expectancy.

**6.7 Stress.** Fill rule tightened to "traded size ≥ 2× displayed size"
(mandatory); forecast quantiles shifted ±1 °F; by-station leave-one-out;
by-month split; θ raised to 0.08; maker coefficient set to the taker
coefficient.

**6.8 Reporting.** Win rate with a climate-date cluster-bootstrap 95% CI, n,
effective n, station-day n, net expectancy with CI, portfolio return on
deployed capital, profit factor, max drawdown of the daily P&L series,
turnover, exposure by station, counts of losses/breakevens/voids/unresolved/
excluded, realized bid distribution, fill rate.

**6.9 Adverse-selection test (pre-specified).** Within each p_NO stratum
(0.94–0.96, 0.96–0.98, >0.98), compare the realized YES-settlement rate of
FILLED bids with the model's mean p_YES for those bids and with the settlement
rate of UNFILLED bids in the same stratum (scored counterfactually). FAIL if the
filled-bid loss rate exceeds 1.5× the model p_YES with a one-sided cluster
bootstrap p < 0.05, or if filled-bid loss rate exceeds unfilled-bid loss rate by
the same test. A FAIL is terminal for the hypothesis as stated.

## 7. Promotion gate (bot-enforced, all required)

1. Observed win rate ≥ 0.85 on the untouched holdout (point estimate), with the
   cluster-bootstrap lower bound reported beside it.
2. ≥ 200 completed positions, dependence-aware (climate-date clusters; the
   smaller of position-effective n and station-day n).
3. Net expectancy and portfolio return > 0 after costs; cluster-bootstrap 95% CI
   for expectancy excludes 0.
4. Multiplicity: ≤ 3 revisions; Holm over the revisions, nested inside the
   RA-13 programme FWER allocation.
5. All §4 limits respected; every §6.7 stress remains net-positive.
6. No leakage (every decision uses forecasts with issue time < decision time;
   `ref.ts < take.ts` assert), no selective exclusion, no mid fills, no
   un-censused tape in the sample.
7. Integration checks + live-data shadow run pass (signal, pricing, order
   construction, settlement mapping with inclusive [A,B], risk enforcement).
8. Existing permit/credentials/caps support live operation; the A1 loss-floor
   reachability check passes for this family's own mix.
9. §6.9 adverse-selection test PASS on the holdout.

Claude reports "observed 85%" and "lower CI bound" as two different numbers
and never claims the second from the first.

## 8. Design history

| Version | Date | Hypothesis / change | Nautilus report | Verdict |
|---|---|---|---|---|
| v0.1 | 2026-10-12 | H-MAKER-NO, initial parameters (P_MIN .94, B_CAP .80, E_MIN .10, cancel 09:00 LST, 2 rungs/station-day, 4 stations) | none | peer-reviewed SOUND-WITH-CAVEATS ×2 (bot-fit review; domain-math review); superseded |
| v0.2 | 2026-10-12 | Same hypothesis. Added: hostile prior evidence (§1); corrected breakeven table and Wilson-bound requirement (§3); §6.9 adverse-selection gate; maker-side print matching, quantity-unit precondition, queue reset, no implied-price fills (§6.1); station-day unit beside position unit; α nested in RA-13; Stage 0 exploratory replay as the simplest first step; exec-path blockers in §9 | none | not evaluated |

Peer-review record (internal gate input, not evidence): v0.1 reviewed 2026-10-12
by a bot-fit reviewer (2 blockers: IOC-only exec path, one-shot latch; 6 majors)
and a domain-math reviewer (1 blocker: fill-simulation completeness; 3 majors:
adverse selection, point-estimate gate, win inflation). All items are folded into
v0.2 or listed in §9.

## 9. Integration gaps (the bot cannot run the requested loop today)

Blockers for any live or shadow-with-orders run:
1. **The exec path is IOC-only at four layers.** `exec/submit_chain.py:331,448`
   refuse any non-IOC order and `:344,461` refuse post_only/display/expire;
   `exec/client.py:5584` hard-codes IOC; `_cancel_order` (`client.py:7587-7600`)
   unconditionally rejects and modify/cancel-all raise `NotImplementedError`.
   Resting bids and every cancel in §3 have **no venue path**. Building one
   touches the byte-pinned exec client and the NO-SEND/egress pins (WIDENED-row
   discipline), not just strategy code.
2. **The K=1 submit slot and one-shot latch cannot hold resting orders**
   (`submit_intent.py:1378-1381`; an OPEN intent denies every other order). Two
   resting rungs per station-day plus cancel-replace needs a new intent model.
3. **`TRADE_QUANTITY_UNIT` is UNRESOLVED** (`parsing.py:225-232`); prints are
   YES-leg only. §6.1 cannot run until the unit is resolved from the wire.

Gaps for the evaluation loop:
4. No historical backtest of executable prices is possible (forward-only tape
   from 2026-08-30); trade-print census after 2026-09-25 missing; RA-13 B-3 may
   bar reading that tape until censused.
5. No maker fill simulator exists; §6.1 and Stage 0 are a build (a
   `scripts/analysis` study, the smallest build on this list).
6. The FQ calibration artefact has no exposed P(high ∈ [A,B]) API for an
   arbitrary rung, and the FQ decision path is gated to D+1 takes
   (`decision.py:138 NotDPlus1`) under the permanent F6 veto; p_NO needs its own
   loader, calibrated for the tail stratum this family uses.
7. The observation kill-switch and the 09:00 LST cancel have no cancel actuator
   (exit seam AUD-07 is built and UNARMED).
8. A1 reachability tooling (`fq_loss_floor_mc_*.py`, `fq_loss_floor_np_bound.py`)
   is hard-wired to FQ mixes; a maker mix at ~2 positions/day likely hits the
   same α_eff ≈ 0.02–0.03 wall. Must be parameterised and run before freeze.
9. No climate-date cluster bootstrap, design-effect, Holm, purge/walk-forward or
   candidate-budget tooling; only per-family sequential looks exist.
10. No standard win-rate / drawdown / profit-factor / turnover outputs;
    `portfolio_roi_report` emits ROI vs baselines only.
11. Strategy parameters are not manifest-declarative; a new rule needs a new
    `composition_kind` and strategy code.
12. Promotion is advisory (`promotion_criteria` emits `PROPOSAL`, explicitly
    never arms); activation is a manual `BREEZY_SENDING_FAMILY_ID` edit plus
    supervisor restart plus a `live_orders_ruling`. No auto-promote-and-arm path
    exists (AUT-5b is an enum, not a code path). Claude will not build one.
13. No performance-deterioration demotion or auto-rollback of a sender.
14. No exit leg is armed; hold-to-settlement is a design choice and its losses
    are counted, never excluded.
15. Sample-size clock: 4 stations × ~0.91 listing × ≤2 rungs × unknown maker
    fill rate. At 0.3 → ≈2 positions/day → ~100 shadow days to 200 positions.
    No faster route exists that does not widen risk (more rungs, lower P_MIN,
    higher B_CAP, NYC, or crossing the spread all change the risk surface).
