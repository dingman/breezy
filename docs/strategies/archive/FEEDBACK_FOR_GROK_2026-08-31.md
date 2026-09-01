> **ARCHIVED 2026-09-01 — CONSUMED.** This feedback was folded into
> `docs/prompts/GROK_STRATEGY_DESIGN_BRIEF.md`; that brief is authoritative.
> Counts of existing strategies in this doc are stale (five exist, not three).

# Feedback on the three-strategy handoff pack

To: the strategy-document author. From: implementation.
All claims below are measured or read from source; every number carries its
denominator. Evidence: `docs/evidence/observation_lock_falsification_2026-08-31.md`.

## 0. Status correction — do not read this as "all three failed"

| Strategy | Settlement-side gate | Economic gate | Status |
|---|---|---|---|
| `cli_settlement_print_lock` | PASS (both) | never run | UNREFUTED, unconfirmed |
| `running_extreme_lock` open tail | PASS | never run | UNREFUTED, unconfirmed |
| `running_extreme_lock` interior | **FAIL on MDW/NYC/SFO** | n/a | **DEAD** |
| `lagged_anomaly_tail` | never run | never run | UNTESTED |

Measured: `p_stable` 99.989% (9105/9106); halt-window 98.66% (9041/9164);
`p_hold` 99.79% (9716/9736). All far above the thresholds the briefs set.
The meteorology held up. The economics were never testable.

## 1. THE STRUCTURAL PROBLEM — fix this first

Every brief orders its falsification the same way: settlement-side test first,
economic overlay ("in-life `OrderBookDepth10` only") second. Given Breezy's
actual price holdings, the second test can never run, so every brief is
*structurally guaranteed* to terminate at "gate PASS, economics unknown."

Breezy's entire order-book history: **5 instruments, NYC+MIA only, one calendar
day, 6 minutes 9 seconds** (2026-08-30 16:05:44Z→16:11:53Z).

Worse, the windows are **disjoint**, not merely thin. For that same climate day:

    MIA preliminary received 20:32:55Z   NYC preliminary received 20:50:55Z
    MIA final       received 08:42:55Z+1 NYC final       received 06:25:55Z+1
    book captured           16:05:44Z → 16:11:53Z

`running_extreme_lock` fires only AFTER a preliminary prints; the book capture
ends 4h21m BEFORE the earliest preliminary. `cli_settlement_print_lock` fires
after the FINAL prints — 14+ hours after the book went dark. Overlap is ZERO.

The briefs correctly forbid reconstructing tapes of expired markets, but never
acknowledge that this makes their own economic kill tests unrunnable today.
That gap between constraint and test design is the single biggest defect.

**Asks for the next revision:**
- Add a **Gate 0: price-data prerequisite** to every brief, stated in
  instrument-hours: "this strategy's economic test requires captured L2 depth on
  the target instrument during [trigger window]; N station-days needed = X."
  A brief whose Gate 0 is unmet should say so on page one, not on page four.
- State the *trigger window in clock terms* per strategy, so a capture plan can
  be written against it. `running_extreme_lock` needs ~20:00-24:00Z; the current
  capture ran 16:05Z. Nobody noticed because no brief stated the window.
- Stop treating the economic overlay as a confirmation step. It is the binding
  gate. Order it FIRST in the falsification section.

## 2. Factual errors — each verified against source

1. **"Two of the three current strategies emit only `SHORT_YES` and are refused
   by `allow_short=False`"** (`running_extreme_lock.md`, impl. note 2). FALSE as
   a code contract. All three have `LONG_YES` branches:
   `calibration_mean_reversion/decision.py:163`, `forecast_revision/decision.py:303`,
   `forecast_mispricing/decision.py:142`. This was a *measured-run observation*
   from one backtest window, restated as a property of the code. It sent the
   implementer looking for a long-capable template that was never missing.

2. **"PT stations... window may be 0-4.5h; often tight vs halt"** and the
   prediction that LAX/SFO may have no legal window. REFUTED. Against the real
   configured halt (`min_hours_to_settlement = 2.0`, which binds above
   `halt_hours_before_settlement = 1.0`): KLAX 95.6% (1757/1837), KSFO 99.4%
   (1805/1816). Both clear comfortably.

3. **"Edge... strengthens as evening progresses"** implies `p_hold` improves
   monotonically with issuance hour. REFUTED. By local hour:
   16:00 = 99.83% (6018), 17:00 = 99.65% (1998), 18:00 = 99.87% (1590).
   Non-monotone. It is already near-maximal at the afternoon issuance.

4. **"RiskManager.evaluate_order order of checks"** presented as a 10-item
   ordered list. Actually **13 top-level gates plus 6 ordered quote subchecks**
   (`weather_common/risk.py:382-467` and `:291-316`). Presented as
   authoritative and copied into two briefs; an implementer following it would
   mis-order refusals.

5. **`halt_hours_before_settlement` is dead in practice, and both briefs lean on
   it.** `cli_settlement_print_lock` calls halt-hours "the binding interaction"
   (section 7) and lists the halt firing as loss condition #5. In source
   (`risk.py:395-398`) `settlement_halt` (1.0h) is checked BEFORE
   `too_close_to_settlement` (2.0h) — but under a monotonically decreasing
   clock, 2.0h is always crossed first, so `settlement_halt` never fires. The
   real binding gate is `min_hours_to_settlement = 2.0`. This is our defect,
   not the document's, but it invalidates the brief's timing arithmetic:
   recompute every station window against 2.0h, not 1.0h.

6. **`WeatherBucketFacts.distance_f`** is the natural-looking primitive for
   "how far past the floor" and cannot serve: it returns 0 for ANY reading
   inside the interval, and an open tail contains everything above its floor
   (`src/breezy/domain/weather_bucket_facts.py:75-84`). Margin must be
   computed directly. Worth
   naming, because the brief's "haircut by empirical P(...)" is vague enough to
   lead straight into it.

## 3. Design-shape errors

7. **Flat `min_p_hold = 0.96` / flat `p_stable` are the wrong SHAPE.** The
   hazard is margin-conditional and the strategy fires the instant
   `H >= tail_floor` — i.e. it concentrates entries at margin 0, the
   worst-conditioned cell. A pooled average silently over-prices exactly where
   it trades most. Measured, Wilson 95% LOWER bound by margin (N=9736):

       margin 0: 99.6829%   1: 99.8244%   2: 99.8798%
       margin 3: 99.9094%   4: 99.9418%   5+: 99.9418%

   Downward events by magnitude: -1F x11, -2F x4, -3F x2, -4F x2, -16F x1.
   `model_probability` must be a function of margin carrying the LOWER bound,
   not a scalar threshold. Please specify config knobs as tables where the
   underlying hazard is conditional.

8. **Internal inconsistency in `running_extreme_lock`.** Loss condition #1 names
   `correction_flag` / `revision_seq` as the mechanism, but the 7-step decision
   algorithm never gates on the record's own flags. `cli_settlement_print_lock`
   has the gate. Whenever a brief names a loss mechanism, its algorithm must
   either gate on it or say explicitly why the base rate already prices it.

9. **The freshness blocker was real and under-specified.** Both briefs flagged
   "if the gate is forecast-only, raise a blocker" — correct instinct, but it
   WAS forecast-only (`forecast_age_hours: float`, no sentinel), and resolving it
   required a change to the SHARED risk contract used by all strategies. A brief
   that depends on a cross-cutting contract change should say so as a
   prerequisite with an owner, not as a conditional footnote.

10. **No brief specifies depth-aware sizing** — a serious omission given all three
   mandate "every fill treated as a taker against the live ask." Taker execution
   + a thin book + top-of-book pricing means the edge is assumed rather than
   earned. In review this was a live defect: a book of 5 contracts at 0.50 backed
   by 300 at 0.99 reads as highly profitable at level 0 and is a loss on any real
   size. Every brief needs an explicit "price the edge at the VWAP of the size
   you intend to take, and clip size to available depth" clause.

11. **`lagged_anomaly_tail`'s test is proxy-only and the brief under-weights it.**
    Historical Polymarket listings are unavailable, so "the tail contract that
    would have been listed" is unobtainable and the P90 proxy is the only path.
    The brief says "write it down; do not hide it" — good — but should go further
    and state that a proxy-based economic result cannot promote the strategy past
    paper status.

## 4. What was RIGHT — preserve these

- **Naming falsification thresholds up front, before any code.** This is why the
  interior-bucket path could be killed cleanly instead of being tuned until green.
  Keep doing this; it is the pack's best feature.
- **The "this requires data Breezy does not have" device.** Exactly the right
  construct. It should simply be promoted to Gate 0 (§1).
- **Long-only discipline.** Well-founded: the bid side is genuinely unexecutable.
- **Refusing to invent the two operator-reserved values.** Correct, and it held
  through implementation.
- **Edge vs ask, never midpoint. Look-ahead rules.** Specific, correct, testable.
- **Build order** (`open_tail_only=True` first) — vindicated. The powered study
  later proved the interior path dead on 3/5 sites.

## 5. One measured fact the next revision should absorb

The symmetric preliminary→final revision rate is 6.84% pooled (13.96% MDW,
11.79% NYC) — but **97% of revisions are UPWARD**; the downward rate is 0.21%.
A running maximum rising after the afternoon issuance is physically expected.

This single distinction decides two strategies: it kills every design needing
exact equality (interior buckets) and leaves every design needing only a
one-sided threshold (open tails) intact. The briefs treat "revision risk" as one
undifferentiated hazard. Please make direction explicit wherever revision risk
is invoked.

## 6. Suggested addition — a fourth brief worth designing

The economics are blocked on capture, not on ideas. The highest-value next
document is not a fourth strategy but a **capture specification**: which
instruments, which clock windows, at what cadence, for how many station-days, to
make the existing three testable. Derived from §1, that is roughly: the five
settlement stations' tail instruments, 19:00-01:00Z daily (preliminary window)
plus 05:00-13:00Z (final window), for >=14 days. Without it, every strategy
document written from here will terminate at the same "economics unknown."
