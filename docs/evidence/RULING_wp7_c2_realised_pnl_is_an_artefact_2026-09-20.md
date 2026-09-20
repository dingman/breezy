# WP-7: the C2 realised-PnL result is an ARTEFACT (look-ahead contamination)

**Date:** 2026-09-20
**Status:** REFUTED. The result must not be cited as edge evidence.
**Supersedes the realised-PnL tables in:** `febfd94`, `4209fe3`
**Subject:** `scripts/analysis/forecast_cheap_screen_wp7.py`

## 1. The claim under test

An earlier run of the WP-7 cheap screen reported, for the C2 (pre-window ask
screen) variants:

| variant | n | win rate | mean ask | mean fee | mean realised PnL |
|---|---|---|---|---|---|
| A1-B1-C2 | 35 | 0.771 | 0.2117 | 0.0109 | **+0.5489** |
| A2-B1-C2 | 35 | 0.686 | 0.1663 | 0.0080 | **+0.5114** |
| A3-B1-C2 | 28 | 0.750 | 0.2289 | 0.0114 | **+0.5096** |

These reconcile exactly — `win − ask − fee` is an identity in `score_take`, so
the arithmetic was never in question.

**The result was challenged on plausibility alone:** a mean ask of ~0.21 winning
77% of the time is not a market inefficiency anyone leaves lying around. It is
the signature of a join or timing bug. Note also that the model's own mean
`p_yes` on those same takes is **0.284** — the forecast does not predict these
wins either. Whatever was selecting winners, it was not the forecast.

## 2. Hypotheses tested and cleared

- **Settlement join off-by-one / DST.** CLEAN. Both sides key on the climate day
  parsed from the instrument id (`parse_rung`).
- **Rung bound / side inversion.** CLEAN. The measured LAX 2026-08-31 ladder
  (`lt72f, gte72lt73f, gte74lt75f, gte76lt77f, gte78lt79f, gte80f`) partitions
  the integers only under the closed reading actually used. All 605 tape
  directories are YES-leg instruments; zero `^no`.
- **Liftability of sub-0.02 asks.** NOT THE DRIVER. `ask_size >= 1.0` is
  enforced; observed take sizes are mostly 5–160, and the 0.1-size rows are
  correctly excluded.
- **Tail concentration.** NOT THE DRIVER. The top-5 takes are 24–31% of total;
  excluding them the mean is still +0.43…+0.49. The artefact is systemic.

## 3. Root cause — two look-ahead defects

A rung's depth tape for climate day D **spans D−1..D+1**. Measured: LAX
2026-09-15 runs 2026-09-14 07:00 LST → 2026-09-16 00:01 LST, with 2,538 window
instants on D−1 against 14,795 on D.

**Defect 1 — the decision window is filtered by hour-of-day, not by date.**
`forecast_cheap_screen_wp7.py:510-511` reads `if inst.hour_lst not in hours:
continue`. Prior-day instants therefore satisfy the window, and because
`candidates.sort()` takes the earliest, **49–86% of all takes execute on the
prior local day.**

**Defect 2 — the screen reference is observed after the take.**
`_pre_window_ask` (`:448-455`) returns `prior[-1]` over the whole multi-day
tape, i.e. the 08:59 LST instant **on D** — up to 24 h *after* most take
instants. For 51–80% of C2 takes the reference lies in the future of the
decision. The C2 condition `ask(t) < ref` therefore reads, literally:

> *this rung's price rose over the next ~24 hours.*

That is an outcome leak, and it is the whole result.

**Measured leak size** on prior-day takes: C2 win rate 0.82 / 0.83 / 0.94, mean
PnL +0.586 / +0.602 / +0.644. On the *same instants* with the screen removed
(C1): win rate 0.16 / 0.20 / 0.17, mean PnL ≈ 0.000. The screen is doing all the
work, and it is doing it with hindsight.

## 4. Decisive experiment

The identical screen, re-run with instants date-scoped to the climate day and
**nothing else changed**:

| variant | n | win rate | mean ask | mean realised PnL |
|---|---|---|---|---|
| A1-B1-C2 | 63 | 0.111 | 0.138 | **−0.0343** |
| A2-B1-C2 | 57 | 0.088 | 0.107 | **−0.0246** |
| A3-B1-C2 | 59 | 0.102 | 0.145 | **−0.0519** |

**+0.55 → −0.03.** The entire reported edge was the contamination.

## 5. Further defects found in the same file

3. **[HIGH]** The decision instant is built at **09:00 UTC** (`:1062-1070`,
   `tzinfo=dt.UTC`) while the adjacent comment and registration §2.2 both say
   09:00 **LST**. For LAX that is 01:00 LST. Conservative in effect, but it is a
   registration non-compliance and it applies the same 09Z cycle to the A2
   (12–17) and A3 windows.
4. **[HIGH]** `hour_lst` uses `std_utc_offset_hours` year-round (`:736`). All
   four stations are on DST through September, so every window is labelled 1 h
   early.
5. **[MEDIUM]** The NO-leg ask screen (`:538-539`) compares
   `no_ask < 1 − pre_window_ask`; the pre-window NO ask is `1 − pre_window_bid`.
   Off by the spread. B1 variants are unaffected.
6. **[MEDIUM]** The reported `hour_lst` (`:571-574`) matches on `ts_ns` across
   all rungs rather than the chosen one, so the diagnostic can be attributed to
   the wrong rung.

## 6. Blast radius

Defects 1 and 2 contaminate **every** WP-7 number in `febfd94` and `4209fe3` —
not only the C2 cells. The C1 tables and the Spearman/Pearson claimed-vs-realised
correlations are computed over the same prior-day takes and are equally void.

## 7. Ruling

- The C2 realised-PnL result is **an artefact of look-ahead contamination** and
  is struck from the record as edge evidence.
- Requirement 3 (measurable positive edge under leakage-free evaluation)
  remains **UNMET**. The corrected measurement is negative.
- The defects are being fixed in the screen with RED-first regression tests,
  including a guard that fails loudly if any screen reference is timestamped at
  or after the instant it screens. The corrected table replaces §4 once that
  lands.
- No fix may be evaluated on whether it recovers a positive number. A
  correctly-measured negative is the successful outcome of a falsification run.
