# Pre-registration: WP-7b — score the MARKET as a forecaster

**Date:** 2026-09-20 (written and committed BEFORE the first run)
**Size:** S. Analysis-only. No `src/` change, no ingest, no exposure.
**Supersedes as next action:** WP-14 (`ForecastLadderStrategy`), deferred.

## 0. Premise correction — read this first

Two reviewers, working blind, independently converged on the same conclusion:
**the realised-PnL screen is the wrong instrument.** Before stating the design,
the record must be corrected.

**Correction 1 — I cited the wrong family.** The figures "BSS +0.594 vs
no-skill" and "+0.081 over persistence" are the **median family**, whose event
is `settled >= the TRAIN per-(station, month) median`. The venue does not list
that binary. `docs/evidence/FC_0b_FIT_AND_HOLDOUT_2026-09-19.md:11` had already
WITHDRAWN the +0.594 headline as near-tautological — a constant predictor pins
it — and I propagated the withdrawn number anyway.

**On the traded unit (rung family, `FC_0b_FIT_AND_HOLDOUT_2026-09-19.md:68-98`):**

| quantity | value |
|---|---|
| `p_fc` Brier | 0.234822 |
| `p_fc` BSS vs constant base rate | **+0.0252** |
| calibration leg (`\|obs − pred\| <= 0.05`) | **FAIL** — 3 of 5 populated buckets |
| worst deviation | **0.1760** |
| worst failing bucket | n=462, \|dev\|=0.0745, **z=3.34** |

**Correction 2 — the direction of the miss is informative and was not acted
on.** The rung family is **UNDER-CONFIDENT in all five populated buckets**,
mean signed deviation **+0.0790**. Every bucket's observed frequency EXCEEDS
its predicted probability: the fitted sigma is too WIDE. The 0b document states
the operational consequence directly (`:98`):

> a live 'take when p > ask + fee' rule fed by it UNDER-FIRES: it declines
> rungs whose realised hit rate would have cleared the threshold.

This is a concrete, fixable mechanism, and it is consistent with the corrected
screen's near-zero realised result. It is NOT evidence of market efficiency.

**Correction 3 — the realised screen is underpowered.** Per-take PnL at a 0.10
ticket has sd ≈ 0.30; over 73 clustered station-days SE ≈ 0.035, so only edges
≳ 0.07/take are detectable. The plausible effect size is 0.01–0.03. The six
near-zero cells are a **non-detection**, not an absence
(`RULING_wp7_c2_realised_pnl_is_an_artefact_2026-09-20.md` §8).

**Correction 4 — the screen's take set is a selector artefact.** With
`MIN_EDGE_FOR_TAKE = 0.0` on a noisy `p_model`, the take set is the argmax of
model ERROR, not skill: a 0.03 overstatement flips a tail rung but not a mid
rung, so takes migrate into the cheap tail (mean ask 0.07–0.13) wherever the
skill actually lives. The screen therefore never sampled mid-priced rungs,
where the edge/hurdle ratio is 4–10× rather than ≈1.

**Conclusion.** Realised PnL over 59–63 takes cannot answer the programme
question. A paired Brier comparison over **thousands of rung-events** can, and
needs no new corpus.

## 1. The question

**Does the forecast carry information the market price does not already have,
on the unit the venue actually trades?**

## 2. Design

Treat the venue **mid** — and separately the **ask** — as a probabilistic
forecast of the rung outcome, on the same station-days the WP-7 join already
produced. No takes, no threshold, no variant sweep, no instant scan.

- **Unit of observation:** one (station, climate_day, rung) rung-event.
- **Decision instant:** ONE pre-declared instant per station-day — **09:00 LST**,
  first liftable quote at or after it. Reuse `decision_instant_ns` and
  `STATION_TIME_ZONES` from `a0a9ea8`. **No argmax over instants.** (See §5.)
- **Emit for every rung on the ladder, with no selection:**
  `(station, climate_day, rung, p_fc, L0 ask, L0 bid, mid, settled ∈ {0,1})`.
  `p_fc` from inputs timestamped ≤ the instant; quotes from that instant's
  Depth10 only; the outcome used solely as an aggregate label.
- **Refuse, never impute,** any instant where the ladder is not a complete
  partition — a partial ladder is not a partition.
- **Statistic:** paired `Brier_fc − Brier_mkt` on identical events, with a
  **date- and station-clustered block bootstrap CI**. Reuse the existing
  `Trial` / `brier` / `_clusters` machinery in
  `scripts/analysis/forecast_conditional_scoring.py` — do not write a second
  Brier.

## 3. Readings — PRE-DECLARED, binding, fixed before the first run

Exactly one reading is selected. No other outcome may be reported as a result.

- **(b) SKILL IS IN THE PRICE.** CI for `Brier_fc − Brier_mkt` straddles zero,
  or `Brier_fc` is significantly WORSE. → L-7 confirmed on the traded unit.
  **This is a programme-level conclusion and a SUCCESSFUL outcome**: no
  decision rule can recover edge that is not there. It goes straight to a
  ruling and the forecast-edge hunt on this surface stops.
- **`Brier_fc` significantly LOWER than `Brier_mkt`** → information beyond
  price exists. Then compare mean `|p_fc − p_mkt|` on take-eligible rungs
  against the hurdle `θ·p·(1−p) + half-spread`:
  - gap **<** hurdle → **(c) STRUCTURAL.** Real information, too small to
    monetise against fees and spread. Also a terminal conclusion.
  - gap **>** hurdle, yet realised PnL still non-positive → **(a) THE RULE IS
    THE PROBLEM.** First suspects, in order: the under-confident sigma (§0
    correction 2), then the instant-selection argmax, then the fixed
    zero-edge threshold.

## 4. Secondary measurement (same pass, near-zero marginal cost)

**Cross-rung consistency.** Exactly one rung settles at 1, so the ladder's asks
should sum to ≈1. Report the distribution of `Σask − 1` and
`Σask + Σfee − 1` per instant, **with L0 depth recorded**, so an apparent
overround or arb backed by 1 contract is visible as such. `Σask ≤ ~0.96–0.98`
would be a riskless long-only ladder buy — a venue-mechanics edge rather than a
forecasting edge, and legal under `allow_short = False`. Expect overround
(`Σask > 1`); that is itself the cleanest direct evidence for L-7's tail half,
and it validates tape completeness.

## 5. Ruling on the instant-selection dimension

`candidates.sort()` then first `c` with `−c[1] > MIN_EDGE_FOR_TAKE`
(`forecast_cheap_screen_wp7.py:720-723`) is an argmax over ~10⁴ instants × ~6
rungs on a noisy margin. Under a true-zero null it fires with probability → 1,
and fires on the noise tail. Holm over 12 variants is orthogonal and does not
touch it. It is **not salvageable as a search**.

**Ruling: collapse the dimension rather than correct it** — one pre-declared
decision instant per station-day. No instant selection ⇒ no correction needed,
and it is also the cheaper live strategy.

**Free falsification, to be run alongside:** re-run the corrected WP-7 screen
single-instant. If realised PnL shifts **UP** versus the scan, the scan was
harvesting noise and selection is confirmed. If unchanged, the scan is not the
driver. Pre-declared here so the answer cannot be chosen after the fact.

## 6. Power and its limits

Paired Brier over thousands of rung-events is far better powered than 59–63
realised takes. It is still bounded by **73 station-day clusters** — the
effective n for the CI is the number of clusters, not rows. State the cluster
count with every interval. A null remains a **non-detection at small
magnitudes**, never a proof of efficiency, and must be reported in those words.

## 7. Binding constraints

- The three readings above are fixed. **Selecting a reading after seeing the
  number is forbidden.**
- No threshold may be tuned, no gate re-registered, and no test weakened to
  obtain a pass. A **(b)** or **(c)** reading is a successful outcome.
- No real-money exposure. Analysis only.
- The outcome label is used ONLY as an aggregate scoring target, never as an
  input to any per-event decision.
- If the corpus cannot support the design, the result is INSUFFICIENT-DATA —
  never a weakened design that yields a number.

## 8. Acceptance test

A deterministic script producing (i) the paired `Brier_fc` vs `Brier_mkt` table
with clustered bootstrap CIs and the cluster count, (ii) the
mean-gap-vs-hurdle table, and (iii) the `Σask` distribution with depth. PASS =
this pre-registration exists in git **before** the first run, the run is
reproducible from the same inputs, and exactly one of the three readings in §3
is unambiguously selected.

## 9. Deferred pending this result

- **WP-13** — must NOT freeze the 0b density UNCHANGED. Its reliability already
  fails the pre-declared ε on the traded unit; sha-pinning it into the manifest
  would make that permanent. Re-scoped to "promote a RECALIBRATED table that
  passes ε out-of-sample on the untouched 2025 holdout", with the `lead_hours`
  UTC/local fix folded into the same refit. Refitting to recover a number is
  forbidden; refitting because the index is wrong is a correctness fix, and the
  fix is NOT to be evaluated on whether the edge improves.
- **WP-8** — blocked and mis-ordered: it cannot mint ε from 0b, because ε=0.05
  already fails on the rung family. Minting a looser ε is the forbidden move.
- **WP-15** — HALT at DRAFT. Do not register PREREG v6. Registering a
  sequential test spends α on a hypothesis with no positive screen and a
  failing calibration leg.
- **WP-14 / WP-16** — keep, unarmed, de-prioritised below this. If built, a
  **pre-registered abandonment criterion** is written at WP-14's start, or
  "build it unarmed" becomes an unbounded parking orbit.
- **WP-7** — recorded as **artefact incomplete**, neither PASS nor FAIL: only 6
  of 12 pre-declared cells ran. B2 (NO-side) is **unevaluable** — all 605 tape
  directories are YES-leg, zero `^no`. That is a corpus gap, not a variant
  exhaustion.
