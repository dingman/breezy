# STRAT-DESIGN r2 — 2026-10-31

Implements G1–G10 in `review_r1.md`. Design only: no backtest, census, live arm, or
budget number. `allow_short` stays false. Nautilus is not modified. No safety, settlement,
contract, pin, or NO-SEND test is weakened. Daily budget and per-position size are not
set; every prize leaves q unset. P4 is neither input nor output.

Shared power, where a card estimates a mean. One-sided 5%, 80%:
`n = (σ/δ)² · 6.19`, `σ = √(p(1−p))`. Binding fill counts are the review's
(the formula gives 7,205 / 801 / 4,853 / 539 / 2,451): **7,240** and **805** at
b = 0.97 (0.5¢ / 1.5¢); **4,850** and **539** at b = 0.98; **2,476** only at p ≈ 0.99.
"≈55,700 days" is 7,240 / 0.13. That rate is not an input.

## 0. Delta compliance

| Delta | Status | Where |
|---|---|---|
| G1 | DONE | §2. −0.0125 tables and the wire-sign frame are gone. p* = b |
| G2 | PARTIAL | §4 paths. One flag each on wp7b and the catalog reader. E/C/D exceptions named. Instrument exclusion is specified and fail-closed; `FamilyManifest` has no instrument-id field (§4.0) |
| G3 | DONE | §3 verdict. Flags not flipped (out of this round's writes) |
| G4 | DONE | §4.A. Leg 3 dropped. Rounding, age, offset, slippage, Depth10 unit gate specified. The unit was not measured (no run) |
| G5 | DONE | §4.B. Touch-queue prior only. Fill counts above. Not a venue-wide kill |
| G6 | PARTIAL | §4.C mean and test. Same instrument-set gap as G2 |
| G7 | DONE | §4.D. Estimand is the YES bid. σ = 0.10 not used |
| G8 | DONE | §4.LOW reuses §4.A leg 1. Coverage is reported, not the gate |
| G9 | DONE | §4.E. One mechanism. Bonferroni k = 3. Power at that k is low and is not relaxed |
| G10 | DONE | `prereg_r2.md`, §5. P4's rate and the thick-touch assumption are not in §6 |

## 1. Economic frame

Unchanged from r1 except the fee corrections in §2 and the withdrawal of λ = 0.13/day.
Qty 1 is null on every PM.us cell. Coverage, on every cell:

- Never-listed ~9%. Factor 0.91. A skip is not a zero.
- Recorder 84/119. Not recomputed. Unrecorded markets add **$0**. Do not gross up by 119/84.
- Full-listing prior × full capture: f = 0.91 × 84/119 = 0.642.
- Card E's 137 is already 5 × 30 × 0.91. Do not apply 0.91 twice. 84/119 hits only a PM.us execution leg.

`fee(p)` means one contract, θ = 0.0695, banker's-rounded to the cent (§2). Maker fee is 0,
so it never appears inside a prize.

| Cell | Prize / month at q = 1 | prize(q), q unset |
|---|---|---|
| A YES lock | **$0** (published min Σask − 1 = +0.05). A one-day 1¢ lock is $0.01 × f = **$0.006** | `(1 − Σask − Σ fee(a)) × q` only if every leg shows size ≥ q; else that day is $0 |
| A NO basket | **$0** prior. Same 1¢ sketch **$0.006**. Taker fees; not a maker post | `(Σ YES-bid − 1 − Σ fee(1−b)) × q` only if every bid size ≥ q; else $0 |
| A pair | No prize. Leg dropped (§4.A). Payoff is 0, 1, or 2 | none |
| B touch | **Unidentified.** Not 0.13 × 30 × $0.02. Maker fee does not change an unknown λ | `30 × λ(q) × e`. λ(q) and e are not taken from P4. e is not reduced by a maker fee |
| C markout | **$0** (P2's take lost 5.3¢). A powered pass is the size question; it places nothing | `q × E[signed markout − taker fee]`; prior E ≤ 0 |
| D dead band | **$0**. Buying NO at `1 − YES bid` is not this card | `q × (yes_bid − fee(1 − yes_bid))` only after a later note. This card places nothing |
| E basis | **EV $0** without a direction. PASS-floor notional, not EV: 137 × 0.02 = **$2.74**. PM.us leg × 84/119 = **$1.93**. **$6.85** = 137 × 0.05 is the 5% alternative, not the floor. Kalshi fees absent | `q × d × v`; v = 0 until the one named mechanism, then one band's value |
| LOW | **$0**. Same economics as A leg 1, not a coverage prize | `q × e_LOW × λ_LOW`; both unidentified |

Rank is the order in §5, not these prizes. None clears the audit's $10–65 ceiling at q = 1.

## 2. Fees

Schedule effective 2026-10-19 13:00 ET (`review_r0.md` R8 RESOLVED). Taker fee
θ · p · (1 − p) with θ = 0.0695. Maker Tier 1 (prior-month maker volume under $10M)
pays 0 and receives no rebate. The −0.0125 figure is the stale 2026-08-25 snapshot.
It is not used. No cell is "unresolved pending the wire." Nothing reopens if a rebate
is imagined. Tier 2+ rebates (−0.0035…−0.0104) are not credited.

Maker breakeven is the bid. p* = b at 0.89, 0.97, 0.98, and 0.99. There is no
`b · (1 + 0.0695 · (1 − b))` maker hurdle.

Taker gap at those bids, unrounded, θ · b · (1 − b): **0.202¢ / 0.136¢ / 0.069¢** at
0.97 / 0.98 / 0.99. A maker edge equal to that gap does not flip: the maker pays none of it.

Rounding, used by `overround_with_fee`. `venue_fee` calls `fee_on_ask`
(`decision.py` `_fee`): `ROUND_HALF_EVEN` of θ · p · (1 − p) to $0.01, per leg, then
`math.fsum`. Not round-after-sum. At p = 0.97 the unrounded 0.202¢ rounds to **$0.00**.
`SumAskRow.overround_with_fee` is `sum_ask + sum_fee − 1` with that per-leg sum.

Post-only stays a refusal. The reason is no longer the sign. `fees.py` still charges
makers +θ by default (`get_commission`, lines 267–289) and, with `allow_maker=True`,
credits −0.0125 (`_maker_commission`, lines 356–376). `expected_fee_for` (line 446)
returns −0.0125. A maker fill priced by that model is not Tier 1. This design does not
edit `fees.py`.

## 3. Engine amendment

**VERDICT: conditional yes, used by no card in §4.** `backtest()` consumes catalog
`TradeTick` only after two flag flips. It does not today.

`TradeTick` is already in `VENUE_MARKET_DATA_TYPES` (harness lines 219–228) and
`add_data` already groups `market_data` (lines 783–784). `backtest()` (line 1026)
takes no queue flag. No current caller puts the trade tape in `market_data`.

Installed Nautilus 1.231.0. Docstring: `trade_execution` lets trades move the market
and match; `queue_position` fills a limit only after size ahead at placement trades
through, or the level is deleted, and requires `trade_execution=True`. The constructor
stores the bool (`engine.pyx` line 4045) and does not check it. With the flag false,
`process_trade_tick` returns at line 4640 (last price only; L2 book unchanged; no
match). Queue decrement (line 4702) is after that return.

With both true, at L2_MBP: the print does not rewrite the book (L1 only, line 4620).
Matching is a transient bid/ask override (lines 4685–4692), restored after `iterate`
(lines 4720–4727). The queue snapshots displayed size (lines 7010–7047) and decrements
by `tick.size` on the opposite aggressor or on `NO_AGGRESSOR` (lines 7086–7096).
Precision mismatch raises (lines 4610–4617).

To turn it on, and nothing else: (1) `BACKTEST_VENUE_CONFIG.md` lines 59 and 62 become
`True` (the "no trade tape" sentence is stale; 1,478 `trade_tick` dirs exist);
(2) harness lines 747 and 752 become `True` in the same `add_venue` call, caller
passes `TradeTick` in `market_data`. Do not touch the order guard or `allow_short`.
Do not change `fee_model` (line 737): §2 voids the sign refusal, not the `fees.py`
defect. A fill PnL from this path is unusable until makers price at 0. Replace the
pin that the flags are false; do not delete it to go green.

C3 and the Depth10 unit (§4.0) come first: a wrong `tick.size` walks the queue wrong.
No §4 card calls `backtest()`. The only successor is a maker-fill note that does not
exist, and only if §4.B does not kill the touch-queue prior. Stage 0 is not that path.

## 4. Cards

Order matches §5. Shared rules live here once.

### 4.0 Shared

**Sample, Cards A and LOW.** One frame per station-day. Target 18:00:00 UTC on D−1.
Max offset: `ts_event` in [17:30:00, 18:30:00) UTC, else the day is missing. Max age:
`|ts_event − 18:00:00Z| ≤ 60s`, else missing. Also `ts_event` at least 60 minutes after
the first frame where `assert_complete_partition` succeeds, else missing (listing hole,
L-35). Not the first frame. Not "nearest" with no cap.

**Non-crossed.** Every rung has no bid, or bid < ask. A crossed rung drops the frame.
Leg 2 also needs every bid present. A missing bid drops leg 2 only (one-sided book).

**Slippage.** One tick ($0.01) per leg before a PASS can reach the size question.
6–10 legs ≈ 6–10¢. r1's −0.02 margin is inside that bound and is not a PASS.

**Own-order exclusion.** Not a date cut (L-65). `deploy/families/pm_us_*.json` names
stations, `d0_climate_day`, and `trial_id_prefix`. It does not name instrument ids
(`FamilyManifest`; the live boundary artefact is `not_applicable_boundary.json`).
The set is the instrument ids in the trial records under those prefixes, including
taker families from 2026-09-13 and `pm_us_crh_fq_v1` (d0 2026-10-02), not only
`pm_us_no_maker_sharp_v1` (d0 2026-10-25). Drop a frame or print on that instrument
at or after its first own order. The artefact lists instrument ids and a count, never
order ids. If the set cannot be built, the run REFUSES. Do not shorten the window
instead. Card E has no PM.us book and does not use this rule.

**C1–C5** stand (review, accepted). C3 also gates Depth10: `ask_size_0` divided by
`_fixed_scalars()` is not a contract count until the artefact prints the scalar, one
raw integer, and the unit. Until that line is written, every size comparison is
INCONCLUSIVE, not a PASS and not a KILL. Do not sum `trade_tick.size` before C3.
**C6** is this section's instrument set, not "exclude 10-24 onward."

**Paths.** No card uses `current_rung_hold_paper_replay.py` (settlement load, lines
1249–1277). No new `--strategy`. Dynamic-import pin untouched.

### 4.E CLI vs TWC — run 1

**Thesis.** PM.us settles on NWS CLI. Kalshi names The Weather Company. Repo studies
are CLI vs ASOS/METAR. The TWC rate is unmeasured. Without one ex-ante mechanism, EV
is a coin flip. This card does not place an order.

**Estimand.** One mechanism only: Kalshi `expiration_value` integer °F minus the IEM
CLI calendar-day extremum (tmax on HIGH, tmin on LOW). d = mismatches / days.
Amendments and voids count as mismatches. Hourly-max, DST, and amendment-rule stories
are not estimated.

**Data / path.** **NEW EVALUATOR — exception requested.** Not in the tree. Public
Kalshi `result` and `expiration_value`, no auth, joined to IEM CLI. Not the five local
JSON files. `k1_kalshi_prior.py` stays byte-unchanged. No `add_venue`, no depth, no
`settlement_truth`. The truth-free ban still applies to Breezy's truth files.

**Extensions.** None. A second mechanism is a new trial (L-34), not a section of this one.

**Window.** Climate days 2026-07-05 through 2026-10-30 inclusive (118 days). Halves by
calendar, not by the sample median: 2026-07-05..2026-09-01 and 2026-09-02..2026-10-30,
59 days each. Stations: the 24 CLI ids in
`docs/evidence/venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md`
lines 17–40, HIGH and LOW series in that table. A missing series is missing, not replaced.

**Sample.** No book. Offset and age do not apply. A day missing either label is missing,
not a match. Do not pool stations. m = 24 × 2 = 48.

**Exclusion.** None (no own orders on this tape).

**PASS.** At least one station-side has ≥ 3 mismatches in each half, and the mean
(Kalshi − CLI) has the same sign in both halves. Under a true 1% rate, Bin(59, 0.01):
P(X ≥ 2) = 0.118, P(both halves, same sign) ≈ 0.007, family-wise ≈ 0.28. Bonferroni
α = 0.05/48 ≈ 0.00104. P(X ≥ 3) = 0.0215; both halves × ½ ≈ **2.3×10⁻⁴**; family-wise
≈ **0.011**. k = 2 fails the correction. k = 3 is the smallest integer that meets it.
**P(PASS under H0) ≈ 0.011** family-wise.

**KILL.** Every station-side has fewer than 2 mismatches in the 118 days, or every
mismatch is an amendment or a void. A missing depth tape is not a kill. n < 118 on a
side is INCONCLUSIVE for that side, not a zero.

**Power.** At a true 2% rate, P(one half ≥ 3) ≈ 0.11 and P(both) ≈ 0.013. At 5%,
P(both) ≈ 0.33. The old n = 6.19 × (0.05 × 0.95) / 0.05² = **118** was for a single
5-point test, not for k = 3 across 48 sides. This PASS is a family-wise screen. It is
not an 80% test of the $2.74 floor. The threshold is not lowered to buy power.

**Decides.** The Kalshi venue question. A PASS goes to the operator size question
(one venue, q unset, prize at the 2% floor $2.74 / $1.93). A KILL closes that question.
Either way §5 continues to D unless a PASS stopped on the size question.

### 4.D Excluded bands — run 2 is G0 only

**Thesis.** A YES band strictly below the running max is cheap because it is dead.
Buying that YES is not the trade. Buying the NO pays `1 − YES bid`.

**Estimand.** The YES bid on that excluded set. Not the ask. σ = 0.10 is not the
error model. Integer °C maps through ×9/5+32 with no interior degree. Bands that
intersect the interval, and bands above it, are not scored.

**Data / path.** **NEW EVALUATOR — exception requested**, one, because a subset is not
a partition (`sum_ask_row` raises) and `queue_sizes` takes no METAR row. Depth10 bids
joined to `metar-routine` only. Run 2 is `--g0-only` and does not compute the bid
median. No `settlement_truth`. The running max is an observation, not an outcome.
Do not edit `market_calibration_scan.WINDOWS`.

**Extensions.** None inside the G0 process. The bid test is a later invocation of the
same evaluator, after G0 passes, still one exception.

**Window.** 2026-09-21..2026-10-30 inclusive.

**Sample.** G0: any frame in the hour counts as "has a frame." Hour: 10:00–11:00 LST
where that is not 17:00 UTC; where 10:00 LST is 17:00 UTC (PDT), 11:00–12:00 LST.
Max offset for the later bid test: nearest 10:30 LST, `|offset| ≤ 15 min`. Max age:
`|frame.ts − 10:30 LST| ≤ 60s`. Else that day is missing, not a zero bid.

**Exclusion.** §4.0. A contaminated instrument does not enter the G0 denominator.

**G0 PASS (run 2).** ≥ 90% of station-days that have a frame in the hour also have a
METAR max row for that hour. This is coverage, not an edge. **P(PASS under H0)** is not
a false-edge rate. The bid test does not run in this process.

**G0 KILL.** None. Below 90% is INCONCLUSIVE and the bid test is not run.

**Bid test, frozen now, not run 2.** PASS: G0 met, ≥ 30 station-days, ≥ 7 distinct
dates, median YES bid ≥ 0.10, size gate only after the Depth10 unit line.
**P(PASS under H0) ≈ 0**: dead-band prices at or under 0.03 cannot clear 0.10.
KILL: median YES bid ≤ 0.03, or the denominator < 30 after the 17Z drop. KILL is the
expected outcome. Median in (0.03, 0.10) is INCONCLUSIVE. There is no n = 6.19 claim.

**Decides.** G0 fail stops this card. Bid KILL ends late-day rounding designs on PM.us
and does not end other cards. Bid PASS writes a later note. It does not place an order
and does not reach the size question on this evidence (the null says the PASS will not
happen; a PASS would be a new trial, still q unset).

### 4.A YES asks and the NO basket

**Thesis.** Buying every YES ask profits when Σask + taker fees < 1, after one tick
of slippage per leg. Buying every NO is the long-only mirror. A HIGH/LOW pair pays
0, 1, or 2. It is not a lock. Leg 3 is dropped: "≥ 15 days with a dead ask ≤ 0.50"
has **P(PASS under H0) ≈ 1**, and "pair sum + fees < 1" is the same gate on two cheap
asks. An inventory of impossible pairs may be written. It cannot PASS.

**Estimand.** Leg 1: `overround_with_fee` on a complete YES partition. Leg 2:
`Σ bid − 1 − Σ fee(1 − b)` on the same frame. No forecast. No order.

**Data / path.** One flag on the existing script:
`python -m scripts.analysis.wp7b_market_as_forecaster --census-only`.
The flag does not exist yet. Until it does, this card does not run. With the flag,
`main` must not call `collect` or `_load_corpus` (line 893) and must not build a
`RungEvent` (`p_fc` and `settled` are required fields; a constant shim is still a
label). `sum_ask_row` stays as written. The flag fills `SumAskRow` from Depth10 asks
(ask fields only) via `assert_complete_partition` and `fee_on_ask`. Not wp7b `main`
as it stands. Not the engine (`support_contingent_orders=False`; a lock is not one order).

**Extensions, same flag, same process, separate sections.** Leg 2's bid sum. BUYER-print
counts (`aggressor` name `BUYER`), counted not summed, until C3. The dropped pair
inventory. Not new runners.

**Window.** 2026-09-21..2026-10-30 inclusive. Not the 64 partitions that produced +0.29.

**Sample.** §4.0. ≥ 30 station-days and ≥ 7 distinct dates, both, or INCONCLUSIVE.

**Exclusion.** §4.0.

**PASS.** Leg 1: `overround_with_fee ≤ −0.01 × n_rungs`, `min_ask_size ≥ 1` only after
the Depth10 unit line. Leg 2: the bid excess ≥ `0.01 × n_rungs`, every bid present and
size ≥ 1 after that same line. G4's unrounded basket fee is
`0.0695 · (1 − Σb²) ≈ 5–6¢`, so `Σbid ≳ 1.075` before slippage. The gate uses rounded
per-leg fees plus the tick bound, which is stricter. **P(PASS under H0) ≈ 0** on both
legs: published min Σask − 1 = +0.05, fees ≥ 0 after rounding, hurdle ≤ −6¢, and
crossed or stale frames are excluded rather than counted. A PASS is not a 0.5¢ mean
(that would need 7,240 fills at b = 0.97). It is a lock screen.

**KILL.** Zero frames clear leg 1, or zero clear leg 2, among ≥ 30 partitioned
station-days. Each leg dies alone. Under 30 days, or the unit line missing: INCONCLUSIVE.

**Decides.** A killed leg stays retired. A PASS goes to the operator size question for
that leg: report prize(q), do not pick q. No engine run in this card.

### 4.LOW

**Thesis.** LOW is not a second cut of HIGH. 204/2,041 names contain `low` until C2
says they are ladders. A missing market is absent, not a zero overround.

**Estimand.** The same object as §4.A leg 1, on LOW partitions only. Captured/named is
a report column, not the gate. r1's "≥ 30 days with `sum_ask_row` returning" is a
coverage gate, **P(PASS under H0) ≈ 1**, and is withdrawn.

**Data / path.** Second invocation of `--census-only`, LOW instrument filter, its own
output file. Same ban on `RungEvent` and on `_load_corpus`. A later edge trial's label
is tmin. A tmax join is the wrong outcome and is not opened.

**Extensions.** None beyond the leg-1 sections. No HIGH rung and no pair inventory.

**Window.** 2026-09-21..2026-10-30 inclusive. New instruments, so L-34 is a new trial
only because the hurdle was frozen in §4.A before either result exists.

**Sample.** §4.0, including offset, age, non-crossed, ≥ 30 station-days and ≥ 7 dates.

**Exclusion.** §4.0.

**PASS / KILL.** Same hurdle, same **P(PASS under H0) ≈ 0**, same size-unit gate as
leg 1. KILL also if C2 fails or complete LOW days < 10. A PASS is not a 0.5¢ claim
(7,240 / 4,850 / 2,476 as in the header, by price).

**Decides.** C2 fail or KILL drops the LOW book. A PASS only allows a later tmin note.
It reaches the size question only with prize(q) and q unset.

### 4.C Signed markout

**Thesis.** P2 killed the forecast as a level. The impulse is the signed mid change
after an NBM release. The median of a 1¢ tick at 120 ms is 0, so a median gate KILLs
by construction and is not used.

**Estimand.** Cluster mean of signed Δ mid. Sign is the sign of the largest |Δp| across
bands in that cycle. Δ mid is that band's mid only. Two bands within 0.01 of each other
in |Δp|, or an exact tie, exclude the cluster. They are not scored as 0. Subtract
nothing from a matched quiet interval; the null is "mean ≤ 0", tested directly.
Half-spread and taker fee come from the before frame. No order.

**Data / path.** **NEW EVALUATOR — exception requested**, one. Not `sum_ask_row`, not
`queue_sizes`, not the engine (`latency_model=None` would fill the old ask). Reader:
`OrderBookDepth10` timestamps and NBP `available_at` only. Cycles 13Z, 19Z on D−1, 01Z
on D. Do not run `nbp_revision_latency.py` or write its files.

**Extensions.** None.

**Window.** 2026-10-14..2026-10-23 inclusive. Off P2's 09-21..10-13 window. These dates
are not "before own orders" (taker fills since 09-13, FQ live since 10-01).

**Sample.** Instant = `available_at + 120 ms`. Before frame: `ts ≤ available_at` and
`available_at − ts ≤ 5s`. After frame: in `(available_at + 120ms, available_at + 120ms + 1s]`.
That is the max offset and the max age. Outside it the cluster is missing, not a zero.

**Exclusion.** §4.0.

**PASS.** ≥ 30 climate-day clusters and, if the hurdle ≤ 1.5¢, ≥ **275** (80% at
σ = 0.10). One-sided cluster bootstrap of the mean, cluster = climate day, α = 0.05,
95% lower bound > half-spread + taker fee. Seed and replicate count are fixed in the
evaluator before the mean is read. A 0.5¢ hurdle needs **2,476** and cannot pass.
**P(PASS under H0) = 0.05** by the test. Fewer than the power floor is INCONCLUSIVE
even if the bound clears.

**KILL.** Mean ≤ 0, or clusters < 30. Bound includes 0: INCONCLUSIVE. KILL closes
this family only.

**Decides.** A PASS that meets the power floor → size question, prize(q), q unset, stop.
No order. Otherwise the stale-ask family stays closed.

### 4.B Touch queue — last

**Thesis.** This is a confirmatory measurement of size at the NO touch, not an edge
test. The 0.5¢ and 1.5¢ claims are already dead on the fill counts in the header
(7,240 / 805 at 0.97; 4,850 / 539 at 0.98; 2,476 only at p ≈ 0.99). This card does not
try to collect them. It does not assume the touch is thick.

**Estimand.** `queue_sizes` at the touch: `(A_gt, A_eq)` from
`maker_stage0_fill_pass.py` line 79. Thin: displayed size ≤ 20 and best NO bid ≥ 0.97.
Markout (−Δ YES mid at +60s) is a mid change, not a fill payoff. It is reported and
not gated.

**Data / path.** One flag, `--queue-census`, on the existing
`scripts/analysis/maker_stage0_catalog_read.py` (no CLI today; the flag is the
extension, not a new script). It reads `OrderBookDepth10` and `TradeTick` through
`CatalogSession`, calls `queue_sizes`, counts BUYER prints, and writes one artefact.
It does not import a truth loader and does not append
`verdict_ledger.jsonl`. `--bench` is the wrong path: `maker_stage0_replay.py`
`_require` (lines 130–136) still demands `--truth` in bench mode, and that CLI is the
verdict driver. Not the engine (§3).

**Extensions.** BUYER-print counts, same flag. Not a size sum before C3.

**Window.** `ts_event ≥ 2026-10-19T17:00:00Z` (13:00 ET, EDT) through climate day
2026-10-30. The fee change is the start. Do not start at 10-17 and do not end at 10-23
to buy cleanliness.

**Sample.** Every in-window frame with max age 60s (gap to the previous same-instrument
depth frame ≤ 60s). A staler frame is not a thin reading. No 18:00 target, so no
offset-from-18:00; the window edges are the offset cap. One station-day counts once.

**Exclusion.** §4.0. Recorded days are days left after that drop.

**PASS.** ≥ 15 station-days with ≥ 1 thin frame, and the median size at best NO bid
≥ 0.97 is ≤ 20, and the Depth10 unit line is present. **P(PASS under H0)** is not a
rate: H0 is not "the touch is thick." A PASS accepts the thin-touch prior as still
open. It does not accept a 0.5¢ edge.

**KILL.** Median size > 20, or thin days < 5 while recorded days ≥ 15. This kills the
touch-queue prior only. It does not end maker variants on the venue. Recorded days
< 15: INCONCLUSIVE. Do not lengthen the window to buy n.

**Decides.** KILL: do not write a maker-fill successor (§3 stays unused). PASS: the
prior is not dead, and it is still not an edge. No size question from this card.

## 5. Order and end states

One job at a time. No truth join between jobs. No feed from or into P4. Thresholds for
runs 1 and 2 are frozen in `prereg_r2.md`, which must carry a sha256 of this file
before either run starts.

| # | Job | Entry | Decides |
|---|---|---|---|
| 1 | E | NEW EVALUATOR, prereg | Kalshi venue question. PASS → size question, stop. KILL → that question is closed; continue |
| 2 | D G0 | NEW EVALUATOR `--g0-only` | Coverage. Fail stops this card only. The bid test is not in this row |
| 3 | A | `--census-only`, after the flag exists | A killed leg stays retired. A PASS → size question for that leg, stop |
| 4 | LOW | `--census-only`, second invocation, after C2 | KILL drops the book. PASS → later tmin note, or size question if the hurdle cleared |
| 5 | C | its one exception | KILL keeps stale-ask closed. A powered PASS → size question, stop |
| 6 | B | `--queue-census` | KILL of the touch-queue prior. Not a venue-wide maker ban. PASS does not price 0.5¢ |

Next state, and no other:

- A PASS in row 1, 3, 4, or 5 that is allowed to reach size → **operator size question**.
  Hand over prize(q). Stop. Do not pick q.
- Row 1 KILL → the **Kalshi venue question** is closed. Rows 2–6 still run.
- Rows 2–6 all kill or stay inconclusive, and row 1 killed → both reserved questions
  are closed. No edge to size, no basis for a Kalshi venue. That is the conclusion.
- Row 6 KILL does not by itself close the program if an earlier PASS already stopped
  on the size question. It never authorizes a new cell outside this list.

D's bid test, if G0 passes, is an invocation between rows 2 and 3. Its KILL is this
card only. Its PASS does not reach the size question (§4.D).

## 6. Not verified, and assumed

Not verified, and not filled from P4: operator caps (not read, not set). That prior-month
maker volume is under $10M (Tier 1 is binding anyway; a rebate is still not credited).
84/119, not recounted. `ts_event` inside parquet (inventory dates are directory names).
That the 204 `low` names are ladders. `trade_tick` unit and the Depth10 size unit.
Row counts in `metar-routine`, the NBP store, and `us-lav-iem` against the 24 stations.
Whether `settlement_truth` stores tmin (not opened). The instrument set itself (§4.0
says how to build it; this note did not build it). ρ. Kalshi's own fee schedule
(absent from the prize on purpose). `support_gtd_orders`. Catalog `TradeTick` precision
against `BinaryOption`.

Assumed: θ = 0.0695 on taker legs after 2026-09-17 17:00Z. Maker fee 0 on every maker
cell in this note. 2026-10-19 13:00 ET = 17:00 UTC. Abutment in
`assert_complete_partition` still matches slugs; a failing day is refused. No card
consumes M1-v3 labels, P4's α, P4's fill rate, or the Stage 0 verdict ledger.
The touch is not assumed thick. λ is not assumed to be 0.13/day.
