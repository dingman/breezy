# AUD-06a review — round 2 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06a-r11-boundary-revalidation.md
sha256: 97617646201ee5796c0772c29babd37e49b415888fa7357c520fbc0a6716446d
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 remedy verification (both reviewers' accepted defects)

| # | R1 defect | Verified in body against source |
|---|---|---|
| 1 (mle, MATERIAL) | independent diagnosis hypothesis ignored the recorded mechanism | CONFIRMED fixed. Re-read `tests/unit/test_multi_position_validation_2026_09_14.py:161-179` directly: the xfail `reason=` string is quoted **verbatim** in the plan's §2 and §6 (checked word-for-word: "higher qty pushes a station-day's variance up to 9x a single Bernoulli term, so I saturates far faster than the artefact's n_k/n_max=0.25-per-draw schedule assumes, and the realised-t boundary interpolation undershoots" — identical in both). "Raise the first look's n" is explicitly withdrawn in §6 and §12 with a stated, logically sound reason (an earlier look still interpolates at an uncovered `t`, relocating rather than removing the undershoot). §6 adds a `Δt_k` instrument with an explicit CONFIRM/REFUTE criterion and §7 step 4 stops the item on refutation. This is a genuine, well-reasoned fix, not a restatement. |
| 2 (both) | no re-validation/staleness trigger | CONFIRMED. §6 "Staleness trigger" names two concrete, dimensionless conditions (live median outside recorded `[p25,p75]`; live IQR beyond +50%/−33%) and states it is fail-closed at the AUD-06b consumer (refuse, not warn) — stronger than either round-1 reviewer asked for. |
| 3 (both) | CI method / replication count unpinned | CONFIRMED and independently re-verified numerically: 20000 reps is the REGISTERED qty≡1 study's own count (`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6, MC SE 0.001104 — re-read directly, matches). Clopper-Pearson one-sided 95% upper is pinned; the stated consequence ("observed rate must be ≲0.0232 to clear α=0.025") checks out arithmetically: `se ≈ sqrt(0.025·0.975/20000) ≈ 0.0011`, `0.025 − 1.645·0.0011 ≈ 0.0232`. This is quantitatively correct, not just asserted. |
| 4 (both) | `Var(S)` tolerance unpinned | CONFIRMED, [0.95,1.05] grounded against the registered study's observed [0.98,1.02] at the same rep count and the existing test's looser [0.85,1.15] (re-read at `test_multi_position_validation_2026_09_14.py:156`, confirmed [0.85,1.15] is the literal assertion bound there). |
| 5 (both) | `q_max ≥ 2` threshold asserted without justification | CONFIRMED removed; AC #4 now accepts `q_max = 1` as a legitimate published result, correctly re-scoping AUD-06b rather than quietly proceeding. |
| 6 | xfail must stay strict | CONFIRMED, §7 step 7 keeps it strict and replaces it only with more evidence (bounded-pass test + a second strict xfail outside the envelope), matching the "never delete/weaken a guard" floor. |
| 7 | portfolio-alignment framing | See fresh assessment below. |

## New verification this round (whole revised plan)

**MINOR — the closed-form guard test at step 2 asserts a YES/NO mixed-side property the sweep
itself never exercises, and the plan does not say whether that gap matters.**

File: AUD-06a §7 step 2 (`test_the_simulated_null_reproduces_the_registered_h0_variance_exactly`),
§6 "Sweep axes".

I read `_sample_station_day` in `tests/unit/test_multi_position_validation_2026_09_14.py:69-99`
directly: it draws `k` mutually-exclusive rungs with `held` from a single-winner categorical and
never sets `side` on any `StratumRow` (default `"yes"` per `current_rung_hold_v2.py:96-98`). The
plan's sweep axes (§6 "Sweep axes") are `q_max`, qty dispersion, and `k` — no `side`/NO-leg axis.
Yet §7 step 2 requires a closed-form test "including a YES/NO pair whose cross term is POSITIVE per
the amendment §3 sign breakdown" as an "L-41 guard." Read literally, that guard test exercises a
station-day shape the qty-envelope sweep will never actually simulate — it verifies the *formula*
(a legitimate, narrow unit check on `combine_station_day`, already excluded from change per AUD-05's
companion plan) but does not extend the R-11 sweep's coverage to mixed-side, mixed-qty station-days,
which are exactly the station-days AUD-05/AUD-07's live family can now produce. The plan does not
state whether `Q_MAX_VALIDATED` is intended to hold under a mixed-side, qty>1 station-day, or only
under the YES-only, qty>1 station-days the existing harness samples. If NO-side qty>1 draws are
possible in production (Increment 1 of the NO-side amendment does not itself cap qty, since sizing
lives in AUD-06b, not the amendment), the envelope this item publishes may not actually have been
validated for the station-day shape it will be applied to.
Fix: either (a) state explicitly in §6/§8 that the envelope's validity is scoped to YES-only
station-days and that a mixed-side qty>1 envelope is out of scope (deferred to a named follow-up),
or (b) add `side` as a sweep axis alongside `q_max`/dispersion/`k` so the published envelope
actually covers what AUD-06b/AUD-07 may size.

No MATERIAL defect found. The mechanism-diagnosis engagement, the staleness trigger, the pinned
methodology (reps, CI, seeds, `Var(S)` tolerance), and the AC #4 threshold removal are all
independently re-verified against source and hold up under a fresh read, not merely a restated
claim from §13.

## Round-1 "portfolio objective alignment" (item 7) — assessed fresh

§11 states the concrete enabling chain (fixed qty=1 caps ROI → this item is the precondition for
lifting it → realised ROI, if any, measured only via AUD-04's named fields against B0/B1), a
three-row plausible-vs-demonstrated table that explicitly declines any ROI claim, a numeric
baseline (0.059 vs α=0.025, q_max=1, R-11 open), a falsifier, and an honest statement that a
published `q_max=1` still counts as full success. This is a genuinely different document from a
restated "epistemic, not money-moving" assertion — it gives a checkable evaluation path. I find no
remaining defect to name here beyond what the item's honest zero-contribution framing already
costs it structurally (it cannot score high on a criterion measuring contribution to the objective
when it correctly contributes none yet).

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **18** — R-11 fully addressed; `max_equity_fraction`
  correctly deferred to AUD-06b rather than silently dropped; the mechanism is now the codebase's
  own recorded one.
- Technical correctness and evidence grounding (20): **18** — every load-bearing citation
  (xfail reason, registered formulas, amendment §6 rep count/SE, CP arithmetic) re-verified
  independently against source this round and holds exactly. Docked 2, not 0, for the unresolved
  side-scope question above — a genuine evidence-grounding gap about what the envelope actually
  covers, even though it is MINOR rather than blocking.
- Implementation specificity and feasibility (15): **13** — reps, CI, seeds, tolerance, staleness
  thresholds are all pinned in Amendment C's own text (re-verified, not merely claimed). Docked for
  the self-conceded "empirical-shaped" dispersion class being described rather than defined, and the
  side-scope gap above.
- Acceptance criteria and validation quality (20): **18** — reproduce-first gate, refutation branch,
  honest empty-envelope branch, threshold removed rather than asserted; all measurable and testable
  as written.
- Autonomous operation, failure handling, recovery (15): **13** — correctly forbids a timer; the
  staleness predicate is fail-closed at the one real consumer. Matches the author's own score; this
  is a legitimately strong section.
- Portfolio objective alignment, scope, dependencies (10): **7** — concrete chain, numeric baseline,
  falsifier, and an explicit decline of the ROI claim; matches the author's revised self-score,
  awarded on the same basis as AUD-05's item 7 (a genuinely honest, evidenced "zero contribution
  today" framing does not merit further deduction beyond the structural ceiling this criterion
  imposes on enabling-only work).

**Total: 87/100**

## Required changes to reach 100

1. State explicitly whether the published envelope covers mixed-side (YES/NO) qty>1 station-days,
   or scope it to YES-only and name the follow-up that would extend it — see MINOR above.
2. Define the "empirical-shaped" qty dispersion class concretely (e.g., pin it to the observed
   live/tape qty-eligible fill distribution, named the same way the `BE` prior already is) rather
   than leaving its exact shape to the implementer.

## Blockers

None requiring operator/strategy-lead ruling. The plan is correctly self-certifying that no
operator-reserved value enters the analysis, and this review found no reason to dispute that.
