# Continuous hunting is a REQUIREMENT and is NOT met

**Date:** 2026-09-20. **Severity:** CRITICAL (requirement violation).
**Operator statement:** *"there is a definitive requirement that the trading
bot's strategy must be continuously hunting, never inside just a specific
window."*

## 1. What the bot actually does today

Entry evaluation is gated to `[12:00, 17:00)` LST:

```python
_WINDOW_START_HOUR_LST: Final[int] = 12      # strategy.py:154
_WINDOW_END_HOUR_LST:   Final[int] = 17      # strategy.py:155  (exclusive)
...
if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):   # :461
```
and the same pair again at `continuous_strategy.py:1306`. Outside it the
strategy refuses `outside_decision_window`.

## 2. The window is a CONSEQUENCE, not a policy

The take rule is `p_bound > price + fee`. `p_bound` comes from
`archive_table.P_HOLD_LOWER`, keyed
`(station, season, hour_lst, width_code, m_code)`. Measured:

```
archive entries: 240
hour_lst keys present:              [12, 13, 14, 15, 16]
hours with a DEFINED p_bound:       [12, 13, 14, 15, 16]
  hour 12: 48 cells, 48 defined     hour 15: 48 cells, 48 defined
  hour 13: 48 cells, 48 defined     hour 16: 48 cells, 48 defined
  hour 14: 48 cells, 48 defined
```

**There is no edge estimate outside 12–16 LST.** Deleting the gate would not
produce continuous hunting; it would produce `None` lookups. The window is the
table's coverage, exactly — `{12..16}` is `[12:00, 17:00)`.

So this is not a switch to flip. The blocking artefact is the archive table.

## 3. A naming collision that hid this

The live family is `continuous_rung_hold` / `pm_us_crh_cont`. **"Continuous"
there means continuous RE-EVALUATION — every tick inside the window, as against
v2's single snapshot.** It has never meant all-hours. The two senses were
conflated, and a family literally named "continuous" made a five-hour window
easy to narrate as normal. It is not normal; it is a requirement violation.

## 4. Coordinator error, recorded

WIN-1 in `docs/core/PROGRESS.md` covered exactly this work — *"Hunt opens after
the winning rung reprices (MIA 0.50→0.90 done 61 min pre-open): calibrate hours
10–11 LST, screen vs pre-window asks, PREREG-amend"* (source:
`STRATEGY_OPPORTUNITY_AUDIT_2026-09-18.md`). **I deleted it on 2026-09-20**
while trimming closed items, on a reviewer's remark that it was "timing on a
refuted-resolution signal". That was wrong: WIN-1 is about WINDOW COVERAGE, not
forecast skill, and is independent of the forecast ruling. Restored as HUNT-1.

## 5. The fix

1. Extend the edge study `scripts/analysis/mb_current_rung_edge_study.py`
   (study git sha `dd77357fc68a352d1b86cb695202bb2ce49273a1`) to every hour the
   venue quotes, not only 12–16 LST.
2. Regenerate the sha-pinned archive artefact; `P_HOLD_LOWER` /
   `P_HOLD_UPPER` gain cells for the new hours. Cells below `N_MIN` stay
   `None` — an under-powered hour is UNDEFINED, never `0.0`, and must refuse
   rather than trade on a fabricated bound.
3. Widen `_WINDOW_START/END_HOUR_LST` to the hours that now have defined cells,
   driven BY the table rather than hardcoded beside it.
4. PREREG-amend: the decision window is a registered selector parameter, so
   widening it changes the estimand. Per L-34 this is a class-C change — a new
   family with `n` reset, exactly as the θ drift was handled today
   (`pm_us_crh_v4`, `e3e8ac6`).

**Honest constraint:** step 1 is a measurement, not a code change. Hours the
study cannot power (thin overnight books, no listed markets) will legitimately
stay `None`, and "continuous" will in practice mean "every hour the venue
quotes with enough data to bound `p_hold`". Any hour that cannot be powered
must refuse, not guess.

## 6. Interaction with today's other constraints

- The live-trading permit TTL is **10 h** — a deliberate operator-facing safety
  bound sized as "the union of the four decision windows plus slack"
  (`R8_OPERATOR_RUNBOOK.md:138,178-181`), pinned by
  `test_the_permit_ttl_is_pinned_to_ten_hours`. A genuinely all-hours strategy
  exceeds one 10 h permit per day. **That bound is not to be quietly widened**
  — it is the same class of control as the fee pin. Widening it is an explicit,
  separate decision, and today's security review already struck a "second
  intraday process" workaround as a disguised way to double daily authority.
- The supervisor's daily cycle (16:40Z stop / 16:50Z launch) is sized to the
  same union and would need revisiting alongside.
