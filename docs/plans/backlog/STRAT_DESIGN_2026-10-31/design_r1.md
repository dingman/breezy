# STRAT-DESIGN r1 — 2026-10-31

Implements R1–R13 in `review_r0.md`. Design only: no backtest, census, live arm, or budget
number. `allow_short` stays false. Nautilus is not modified. `design_r0.md` §0 stands.
P4 is neither input nor output. Daily budget and per-position size are not inputs; every
prize(q) leaves q unset.

Shared power (R4). One-sided 5%, 80% power:

```
n = (σ/δ)² · (1.645 + 0.842)² = (σ/δ)² · 6.19
```

σ = 0.10: δ = 0.005 → 400 × 6.19 = **2,476 fills** (review: 2,470); δ = 0.015 → **275**.
At 0.13 fills/day, 2,476 fills are **19,046 days** (review: 19,000). Cross-city correlation
(§3.4) makes these durations a lower bound. A card that cannot name n for its estimand
does not borrow a PASS.

Shared sample (R3, R10, L-35). Not the first Depth10 frame (listing-hour empty bid).
One instant per station-day: the frame nearest 18:00 UTC on D−1 that is also ≥ 60 minutes
after the first frame where `assert_complete_partition` succeeds. Else the day is missing,
not a zero.

## 0. Delta compliance

| Delta | Status | Where |
|---|---|---|
| R1 | DONE | §1 |
| R2 | DONE | §4 path line per card; engine slot refused in §4.0; flag evaluation in §4.B |
| R3 | DONE | §4.A |
| R4 | DONE | §4.B |
| R5 | DONE | §4.C |
| R6 | DONE | §4.D |
| R7 | DONE | §4.E |
| R8 | DONE | §2 (wire sign UNRESOLVED; cells named) |
| R9 | DONE | §4.LOW |
| R10 | DONE | §3.1–§3.5 |
| R11 | DONE | §5 |
| R12 | DONE | §4.0, named on each card |
| R13 | DONE | Truth-free line on each card |

## 1. Economic frame

Qty 1 is null on every PM.us cell. r0's "<$2" and "<$5" treated one cent as a month.
Coverage (R1d), on every cell:

- Never-listed ~9% (`docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md` line 165).
  Factor 0.91. A skip is not a zero.
- Recorder 84/119. Not recomputed (operator brief, r0 §4). Unrecorded markets add **$0**.
  Do not gross a rate up by 119/84.
- Full-listing prior × full capture: f = 0.91 × 84/119 = 0.642.
- Card E's 137 is already 5 × 30 × 0.91. Do not apply 0.91 twice. 84/119 hits only a
  PM.us execution leg, not the public settlement read.

| Cell | Prize / month at q = 1 | prize(q), q unset |
|---|---|---|
| A YES lock | **$0** (published min Σask − 1 = +0.05). A one-day 1¢ lock is $0.01 × f = **$0.006** | `(1 − Σask − Σ θ a (1−a)) × q` only if every leg shows size ≥ q; else that day is $0 |
| A NO basket | **$0** prior (thick NO touch). Same 1¢ sketch: **$0.006** | `(Σ YES-bid − 1 − Σ θ b (1−b)) × q` only if every bid size ≥ q |
| A HIGH/LOW | **$0**. Not a lock. Undirected payoff is 2, 1, or 0 | `q × (payout − cost)`, payout ∈ {0, 1, 2}, not `q × $1` |
| B touch | **$0.08** = 0.13/day × 30 × ≤ $0.02 on the captured book. Do not apply f again | `30 × λ(q) × e`, λ(1) = 0.13/day, e ≤ $0.02 at q = 1, **λ(q) unknown for q ≠ 1** |
| C markout | **$0** (P2's take lost 5.3¢). A pass only reopens that family | `q × E[signed markout − taker fee]`; prior E ≤ 0 |
| D excluded ask | **$0**. An offer rate is not cash | `q × (0 − ask)` on p_hat = 0 bands, only after a later note. This card places nothing |
| E basis | **EV $0** without a direction. Notional, not EV: 137 × 0.05 × ≤ $1 = **$6.85**. PM.us leg × 84/119 ≤ **$4.83** | `q × d × v`; v = 0 until a named mechanism, then one band's value, q still unset |
| LOW | **$0**. 84/119 only caps how much LOW the recorder can show | `q × e_LOW × λ_LOW`; both unidentified |

Rank is evidence cost (§5), not these prizes. None clears the audit's $10–65 ceiling at
q = 1 (`AUDIT_independent_2026-10-22.md` §Proven 4).

## 2. Fee sign

**Documented: quadratic rebate, not a flat 1.25¢.** Snapshot
`docs/evidence/venue/polymarket_us/docs_snapshots/fees_2026-08-25.md` lines 15–28:
`Fee = Θ × C × p × (1−p)`; taker Θ = 0.06; maker Θ = **−0.0125** (max −$0.31 per 100 at
p = 0.50). Pin: `fees.py` `MAKER_FEE_COEFFICIENT`, lines 72–83, marked
DOCUMENTED-NOT-WIRE-OBSERVED. r0 §4's flat reading is rejected.

Per contract, that rebate versus charging live taker θ = 0.0695 (post-2026-09-17; the
snapshot still says 0.06):

| p | Taker 0.0695·p·(1−p) | Doc rebate | Gap |
|---|---|---|---|
| 0.97 | 0.202¢ | 0.036¢ | 0.24¢ |
| 0.98 | 0.136¢ | 0.025¢ | 0.16¢ |
| 0.99 | 0.069¢ | 0.012¢ | 0.08¢ |

A 0.5¢ gross edge does **not** flip under this formula. The flat 1.25¢ reading would.

**Wire sign: UNRESOLVED.** Audit §Proven 4: rebate sign and maker-fill behaviour unproven.
No maker fill since the arm. One payload coefficient, no maker/taker split (`fees.py`
lines 173–180). Post-only is refused (`MakerRebateUnmodelledError`), not booked at
−0.0125. The maker row was not re-cut after θ moved to 0.0695. The maker spec says read
the coefficient from fills, never assume the pin.

Flips **only if** the wire charges +0.0695 and the edge is smaller than the gap: Card B's
sub-0.24¢ slice, Card A's NO basket if posted, Card LOW if a later rule posts. A 0.5¢
Card B alternative does not flip. Cards C, D (no order), and E's taker leg do not: taker
θ is wire-observed. §5 does not use the rebate. Breakeven below is
p* = b·(1 + 0.0695·(1−b)).

## 3. Map additions (R10)

r0 §1.1–§1.9 stand except: the NO basket is a long-only trade (R3; r0 §1.3 said it was
not); E is not a lock (R1); r0's prize rank is withdrawn. The rows below are constraints,
not cards.

1. **Queue-ahead model.** `(A_gt, A_eq)` from `queue_sizes` (`maker_stage0_fill_pass.py`
   line 79) is the fill-probability model. Not fit on the 17 fills (L-56). Card B records it.
2. **`trade_tick` proxy.** 1,478 directories exist. Unit (contracts vs dollars) is
   unresolved. Until C3 passes, the proxy is a print count. Summing `size` is forbidden.
3. **Listing hour.** First hour is an empty-bid hole; QuoteTicks cannot show it (L-35).
   Header sample rule. A first-instant rule is withdrawn (R3).
4. **Correlation.** Effective n ≪ station-days. No ρ. Every n in §4 is the independent case.
   Card D requires ≥ 7 distinct dates. Card E does not pool stations.
5. **GTD across midnight.** `support_gtd_orders` is unverified (`BACKTEST_VENUE_CONFIG.md`
   line 64). A 4 h expiry that crosses 00:00 UTC splits one climate day into two orders.
   A later resting rule, if ever pre-registered, expires ≤ min(09:00 LST, permit end, next
   UTC midnight). This note authorizes none. Card A legs are not bound:
   `support_contingent_orders=False` (same spec, line 65).

## 4. Cards

### 4.0 Refused paths and checklist

Path (ii) — one more `--strategy` at `current_rung_hold_paper_replay.py` lines 1475 and
1547 — is selected by **no** card. That `main` builds `settlement_prices` from the final
climate day (lines 1249–1277), which fails R13. The dynamic-import pin is not extended
and not bypassed. No strategy class is added.

`sum_ask_row` (wp7b line 537) and `queue_sizes` (fill-pass line 79) do not open truth.
These CLIs do, and are not the path: wp7b `main` via `_load_corpus` (line 893);
`maker_design_nobid.py` line 423; `maker_stage0_replay.py` (`--truth` required);
`market_calibration_scan.py`; `p2_nbp_ask_murphy.py`. `maker_stage0_catalog_read.py`
reads `OrderBookDepth10` and `TradeTick` and does not import the truth loader (docstring
lines 14–16). It is Card B's print source.

Checklist (R12):

| Id | Before the run |
|---|---|
| C1 | Per-date completeness. A directory name is not data. Zombies and node-down days are missing, not quiet (L-8) |
| C2 | The 204 `low` names are real LOW ladders, else LOW and HIGH/LOW are refused |
| C3 | `trade_tick` unit, before any size sum (§3.2) |
| C4 | Abutment via `assert_complete_partition`: one open lower tail and one open upper (wp7b lines 184–203). A missing tail is refused, not dropped from the sum |
| C5 | Do not open `derived/settlement-truth` (parquet, csv, or `coverage.json`). A later join must count `coverage.json`; LOW's label is tmin |
| C6 | Card B's window excludes own orders (L-65) |

**NEW EVALUATOR — exception requested**, not built. One driver, two modes, separate
outputs, no mode that scores both:

1. `sum_ask_row` on Depth10 events for Card A and, second invocation, Card LOW. Must not
   call wp7b `main` or `_load_corpus`. If `RungEvent.settled` is required, pass a constant
   and do not write it. `SumAskRow` has no settlement field.
2. `queue_sizes` plus BUYER-print counts (`aggressor == BUYER`, fill-pass line 225) for
   Card B. Must not import `maker_design_nobid` or a truth path.

Reason: R2's census is these two functions, and no current CLI calls them without truth
(R13). Cards C and D need their own exception: neither function is their estimand.

Later class, only after a powered PASS: backtest-only subclass or a new frozen
`MakerRuleParams`, never an edit of `SHARP_V1`, never a live load. No exit sell.
Post-only stays a refusal while §2 is unresolved.

### 4.A YES asks, NO basket, HIGH/LOW

**Thesis.** Buying every YES ask profits when Σask + taker fees < 1. Buying every NO is
the long-only mirror: one NO loses, payout is n − 1, profit when Σ YES-bid > 1 after fees.
HIGH vs LOW is not a lock; both legs can settle false.

**Signal.** Sampled frame: `sum_ask_row` on YES asks. Same events, Σ bid if every bid is
present. A missing bid is one-sided (L-35): the NO leg is absent, not a YES failure.
Impossible pair: no integers t_lo ≤ t_hi with t_hi in the HIGH band and t_lo in the LOW
band. Open tails stay in. Both sizes ≥ 1. No forecast. No order in this card.

**Legging.** 6–10 legs, not atomic. A lock counts only when every leg shows size ≥ 1 at
the frame. A partial fill is not a lock. GTD does not bind legs (§3.5).

**Data.** `order_book_depths` is in the catalog.

**BACKTEST PATH.** Census via `sum_ask_row`, §4.0 mode 1. Not the engine.

**Outcome-blind.** Depth10 only. Counts and medians. No settlement column.

**PASS**, three separate legs. (1) ≥ 30 days with `overround_with_fee` ≤ −0.02 and
`min_ask_size` ≥ 1. (2) ≥ 30 days with Σ bid − 1 − Σ θ·b·(1−b) ≥ 0.02, θ = 0.0695, every
bid present and size ≥ 1. (3) ≥ 15 days with ≥ 1 impossible pair whose dead leg has ask
≤ 0.50 and size ≥ 1. r0 had no PASS on (3).

**KILL.** Zero frames for (1), or zero for (2), or zero days for (3). Each stops that leg
only. Under 30 partitioned days and none under the hurdle: INCONCLUSIVE, not a pass.

**Power.** A lock is not a noisy mean. R4's 2,476 is the warning: this PASS does not claim
a 0.5¢ mean edge. Checklist: C1, C2 on leg 3, C4, C5.

### 4.B Touch queue

**Thesis.** A longshot is collectable only by a NO bid a print can reach. The published
touch is 97–99¢ and thick. This card measures that size and the BUYER prints there. It
cannot measure a 0.5¢ edge.

**Signal.** `queue_sizes` at the touch (YES ask at `100 − b`). Thin: size ≤ 20 and best
NO bid ≥ 0.97. BUYER prints at that price, counted, not summed, until C3 passes.
Adverse selection, reported not gated: maker markout = −Δ YES mid at +60 s. The "sharp
counterparty" line was never tested. It stays UNTESTED unless prints ≥ 2,476. A handful
of prints is not a PASS and not a KILL (L-60).

**Arm.** r0's follow-up is **dropped**. `e_min = 0.04` forces b_max ≤ 0.96, below a
≥ 0.97 touch. This note does not register `e_min ≤ 0.02`. No live load.

**Data.** Depth10 and `trade_tick` are on disk. Print unit is not.

**BACKTEST PATH.** Census via `queue_sizes`, §4.0 mode 2. Not the engine.

**Flag evaluation (R2), not adopted.** `BACKTEST_VENUE_CONFIG.md` lines 59–62 set
`trade_execution=False` and `queue_position=False` on the claim that there is no trade
tape. The catalog now has `trade_tick`, so that sentence is stale. Flags stay off: unit
unresolved (§3.2), a maker fill would be mis-signed or refused (§2), and the spec is
outside this round's writes. Native queue on catalog prints is the parked null, after
unit and wire fee are both observed. Stage 0 is not an engine result.

**Outcome-blind.** No truth parquet, csv, or `coverage.json`. Not `maker_design_nobid.py`.

**Window.** 2026-10-17..2026-10-23. Excludes 10-09..10-13 (L-56) and every day after
10-23 (L-65: 10-17..10-30 is not clean after 10-24). Do not lengthen it to buy n.

**PASS.** ≥ 15 station-days with ≥ 1 thin frame, and median size at best NO bid ≥ 0.97
is ≤ 20. One day counts once. Fewer than 15 recorded days in the window: INCONCLUSIVE.

**KILL.** Median size > 20, or thin days < 5 while recorded days ≥ 15. Ends maker
variants on this venue until a new regime is declared. Already, before the census: the
0.5¢ claim is dead on power (2,476 fills, 19,046 days). A thin PASS does not revive it.

**Breakeven**, taker θ: 0.89 → 0.8968; 0.97 → 0.9720; 0.98 → 0.9814; 0.99 → 0.9907.
Checklist: C1, C3, C5, C6.

### 4.C Signed markout

**Thesis.** P2 killed the forecast as a level. The impulse is the signed mid change, in
the direction the NBM probability moved, 120 ms after `available_at` (cycles 13Z, 19Z D−1,
01Z D). Unsigned |Δ| passes under tick flicker alone (R5) and is not the gate.

**Signal.** Sign(Δ mid) × sign(NBM move), minus the same Δ on a matched 120 ms interval
with no release. Cluster median of that difference. Half-spread and taker fee from the
before frame. No order. A PASS only reopens the stale-ask taker family. It does not arm
it. Do not run `nbp_revision_latency.py` or write its files.

**Window.** 2026-10-14..2026-10-23. New trial (L-34): signed and flicker-adjusted, off
P2's 09-21..10-13 window, before own orders, not LAT-1's confirm period.

**Data.** NBP store and the quote tape. No settlement.

**BACKTEST PATH.** **NEW EVALUATOR — exception requested.** Not `sum_ask_row`, not `queue_sizes`,
not path (ii) (settlement load, and `latency_model=None` would fill the old ask — the
object under test). Reader: `OrderBookDepth10` timestamps plus NBP `available_at` only.

**Outcome-blind.** No `truth_cli_finals`, no settlement parquet. NBP is a release time.

**PASS.** ≥ 30 climate-day clusters and the median exceeds half-spread + taker fee. If
that hurdle is ≤ 1.5¢, required n is 275 and 30 clusters are INCONCLUSIVE, not PASS.
A 0.5¢ hurdle needs 2,476 and cannot pass here.

**KILL.** Median ≤ 0, or clusters < 30. Ends stale-quote taker designs. Not the other
cards. Checklist: C1, C5.

### 4.D Excluded bands, late morning

**Thesis.** "Ask ≤ 0.15 on the band above the running max" is not mispricing. That band
is cheap because it is unlikely; 20% is trivial under the null (R6). Integer °C does not
pick a °F band.

**Signal.** p_hat = 0 only for a YES band lying strictly below the °F interval of the
integer °C max (half-degree °C via ×9/5+32; no interior degree). Bands that intersect the
interval, and bands above it, are not scored. Estimand: ask − 0 on the excluded set.

**Hour (L-34).** Drop 17:00–18:00 UTC (M1 D_17Z). Keep 10:00–11:00 LST where that is not
the bin (EDT: 14:00 UTC). Where 10:00 LST is 17:00 UTC (PDT), use 11:00–12:00 LST. The
move is pre-registered, not a second look. Do not edit `market_calibration_scan.WINDOWS`.

**Data.** Quote tape in catalog. `metar-routine` exists; row coverage was not counted.

**BACKTEST PATH.** **NEW EVALUATOR — exception requested.** A subset is not a partition, so
`sum_ask_row` raises. `queue_sizes` takes no METAR row. Path (ii) reads settlement.
Reader joins Depth10 asks to METAR only.

**Outcome-blind.** No settlement file. The running max is an observation, not an outcome.

**G0 first.** ≥ 90% of station-days with a frame in the hour must have a METAR max row.
Else INCONCLUSIVE and the ask test does not run.

**PASS.** G0 met, ≥ 30 station-days, ≥ 7 distinct climate dates (§3.4), median ask on
excluded bands ≥ 0.10.

**KILL.** Median < 0.05, or denominator < 30 after the 17Z drop. Median in [0.05, 0.10)
is INCONCLUSIVE (the unpowered 3–8¢ band). A 10¢ shift at σ = 0.10 needs n = 6.19, hence
the 7-date floor. A 0.5¢ test needs 2,476 and is not the gate. Kill ends late-day
rounding designs on PM.us. Checklist: C1, C5, G0. C4 does not apply.

### 4.E CLI vs TWC, public labels

**Thesis.** PM.us settles on NWS CLI. Kalshi names The Weather Company. Repo CLI-basis
studies are CLI vs ASOS/METAR, not TWC. **The TWC rate is unmeasured.** The legs pay
2, 1, or 0 by direction. Without an ex-ante predictor, EV is a coin flip minus fees.
A stable named mechanism may later be traded on one venue. That is not an order.

**Signal.** Public Kalshi `result` and `expiration_value`, no auth, vs IEM CLI daily max
(HIGH) and min (LOW), 24 stations, HIGH and LOW separate. No depth, no adapter, no
`add_venue`. The five local JSON files are not the sample. `k1_kalshi_prior.py` stays
byte-unchanged.

**Data.** Not in the PM.us catalog. `us-lav-iem` is on disk; coverage vs 24 stations was
not counted.

**BACKTEST PATH.** Not (i), not (ii). **NEW EVALUATOR not requested.** Step 1 is the K-2a public
read (R7). A fill simulator would be the wrong exception. No `settlement_prices`.

**Outcome-blind.** Not the R13 sense: the question is the two public labels. The truth-free
ban still holds for Breezy's `settlement_truth` files, which this card does not open.

**Rate.** r0's Wilson bound is degenerate: LB = n/(n+3.84) = 0.959 at n = 90 with zero
misses; LB > 0.99 needs n > 380. Withdrawn. Per station, d = fraction of days the Kalshi
band ≠ the CLI band. Do not pool stations.

**PASS (candidate, not a trade).** n ≥ 118, d ≥ 0.02 in each half, same sign of bias in
both halves, and a named mechanism (hourly max vs calendar CLI, DST, or a documented
amendment rule — not "noise"). Amendments and voids are misses, not signal.

**KILL.** d < 0.02 on every station, or the only mismatches are amendments and voids.
A missing depth tape is not a kill. n in [90, 118) is INCONCLUSIVE.

**Power.** Same z's as R4, proportion against 0 at a 5-point rate:
n = 6.19 × (0.05 × 0.95) / 0.05² = **118** days. The old floor of 90 is short of that.
A 1% scatter is not the alternative. Checklist: none of C1–C6.

### 4.LOW

**Thesis.** LOW is not a second cut of HIGH. 204/2,041 names contain `low` until C2
says they are ladders. Report LOW captured/named; do not substitute 84/119. A missing
market is absent, not a zero overround.

**Signal.** `sum_ask_row` on LOW partitions, header sample, open tails, no HIGH rung, no
joint pair (that is §4.A leg 3). No order. A later edge trial's label is **tmin**. A tmax
join is the wrong outcome.

**Data.** LOW depth if C2 passes. tmin is not read. Whether `settlement_truth` stores
tmin is unverified.

**BACKTEST PATH.** Census via `sum_ask_row`, LOW invocation of §4.0 mode 1, its own output
directory. New trial (L-34): different instruments. Not the engine.

**Outcome-blind.** Depth10 only. Same ban as Card A. A file that joins tmax here is contaminated.

**PASS.** ≥ 30 LOW days with `sum_ask_row` returning, `min_ask_size` ≥ 1, captured/named
written out. Window 2026-09-21..2026-10-30, dropping any instrument the live family
manifest shows the maker rested. If that name check is skipped, end the window at
2026-10-23. The check reads the manifest's instrument set, not order ids.

**KILL.** < 10 complete LOW days, or C2 fails. A PASS is not a 0.5¢ claim. Checklist:
C1, C2, C4, C5.

## 5. Order

One job at a time. No truth join between jobs. No feed into P4.

| # | Job | Entry | Decides |
|---|---|---|---|
| 1 | A, three legs | `sum_ask_row`, mode 1, after the exception. Not wp7b `main` | A killed leg stays retired. A PASS goes to the operator size question for that leg: report prize(q), do not pick q, new note before any engine run |
| 2 | B | `queue_sizes`, mode 2, 10-17..10-23 | Kill retires PM.us maker variants. A thin PASS does not pass 0.5¢ (dead on power) or adverse selection (needs 2,476 prints) |
| 3 | LOW | `sum_ask_row`, LOW mode, after C2 | Kill drops the book. Pass only allows a later tmin note |
| 4 | D | G0, then the excepted reader | G0 fail stops. Kill: excluded bands are not offered rich. Pass writes a later note, not an order |
| 5 | C | excepted reader, 10-14..10-23 | Kill keeps the stale-ask family closed. Pass only reopens it as a new trial |
| 6 | E | public Kalshi fields vs IEM CLI, 24 stations, no auth | This is the Kalshi venue question. No tape. A candidate goes to the operator size question (single venue allowed, q unset). None closes it |

Next state (R11), never a bare stop.

- A PASS in 1–5 that also clears its power line → **operator size question**. Hand over
  prize(q). Stop.
- Else → **Kalshi venue question**, which is row 6.
- Row 6 with no candidate → goal state: both reserved questions are closed. No edge to
  size, no basis for a Kalshi venue. That is the conclusion. Do not open another cell.

## 6. Not verified, and assumed

Not verified: operator caps (not read, not set). Wire maker fee (§2 stays UNRESOLVED).
84/119 (applied, not recounted). `ts_event` inside parquet (inventory dates are directory
names; 2026-11-01 was listed, not settled, as of r0). That the 204 `low` names are ladders.
`trade_tick` unit. Row counts in `metar-routine`, the NBP store, `us-lav-iem`, and
`settlement_truth` including whether tmin is stored. Which instruments the live maker
rested, beyond the HIGH NO description. Kalshi JSON schema (files not opened). ρ. A
maker-schedule snapshot after 2026-09-17 (not found next to the 2026-08-25 page).

Assumed: P4's 0.13/day and the thick touch are what Card B remeasures. Abutment in
`assert_complete_partition` still matches slugs; a failing day is refused. θ = 0.0695 on
every day in these windows after 2026-09-17 17:00Z (that morning is outside them). No
card consumes M1-v3 labels, P4's α, or the Stage 0 verdict ledger.
