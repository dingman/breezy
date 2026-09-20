# PRE-REGISTRATION — WP-7 cheap-screen variant set and MULTIPLICITY_RULE (2026-09-20)

**Status: REGISTERED. This document is committed BEFORE the first cheap-screen
run. Its commit is the pre-registration proof.** A variant table produced by a
run whose commit predates this file is not admissible evidence under this rule.

Plan of record: `docs/plans/FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md`
WP-7 (R1-4). Upstream: `docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md`;
operator ruling `docs/evidence/RULING_forecast_edge_family_2026-09-18.md`.
Input evidence: `docs/evidence/FC_0b_FIT_AND_HOLDOUT_2026-09-19.md` (commit
`194c71f`).

## 0. Why this document exists before the run

Stage 0b established forecast **skill** and explicitly did not establish
tradeable **edge**: it contains no price, fee, fill or liftability. WP-7 is the
economic test. An economic test that may be re-run with a different window, a
different side, or a different screen until one clears a bar is not a test — it
is a search, and its winner is a selection artefact. The defence is to enumerate
the entire search up front, bound it, and correct for its size.

The failure this prevents is concrete and has a name in this repo: `L-7`
(the forecast may already be in the price) and the 09-02 forecast-family verdict
that was overturned for being a theoretical kill on an unfitted prior. The
symmetric error — a theoretical *confirmation* assembled from the best of many
unlogged variants — is what this rule refuses.

## 1. MULTIPLICITY_RULE (binding, verbatim obligations)

1. **(i) Bounded enumeration.** The full variant space is enumerated in §2
   below, before the first run. **No variant may be added ad hoc.** A variant
   not in §2 is not runnable under this registration; adding one requires a new
   registration document and restarts the confirmatory clock.
2. **(ii) Multiplicity correction.** Holm–Bonferroni across the **entire**
   enumerated set of `K_variants = 12`, at family-wise `alpha = 0.05`
   one-sided, applied to the **selection decision** — i.e. to the question
   "does any variant clear the bar". The per-cell measurement gate in §3 is a
   *measurement* gate and is not itself a hypothesis test; it does not consume
   alpha and does not substitute for the correction.
3. **(iii) Declared cap.** `K_variants = 12`. Exhausting the set without a
   survivor is a **legitimate halt that escalates to a strategy-lead ruling**.
   It is never grounds for a thirteenth variant. This is the one halt permitted
   to end the forecast-edge thesis, and only after all 12 tables exist.
4. **(iv) Full logging.** **Every** attempted variant's table is written to the
   run artefact, including variants that fail early, error, or return
   INSUFFICIENT-DATA. A variant that was run and not reported is a rule breach
   and invalidates the registration.
5. **(v) FIREWALL.** Variant search runs **only** on the 2021–2025 fit/holdout
   corpus. The confirmatory statistic (PREREG v6 `S_k`, pre-Stage-4) runs
   **only** on 2026 shadow and live data collected **after** the winning variant
   is frozen. A confirmatory peek at 2021–2025 after the freeze discards the
   confirmatory statistic; recovery is to freeze a new variant and restart the
   confirmatory series on post-freeze data.

## 2. The enumerated variant space — K_variants = 12

Three dimensions, fully crossed. Every mandated seed from WP-7 is present.

| Dim | Levels | Values |
|---|---|---|
| **A — decision window** | 3 | `A1` 09–12 LST · `A2` 12–17 LST · `A3` 10–11 LST |
| **B — side pricing** | 2 | `B1` YES only (listed instrument, at ask) · `B2` YES + NO (NO priced off the inverted YES bid ladder) |
| **C — ask screen** | 2 | `C1` no screen · `C2` screen against the pre-window ask |

`K_variants = 3 x 2 x 2 = 12`, identified `A{1..3}-B{1,2}-C{1,2}`.

Seed coverage: the two pre-registered windows 09–12 (`A1`) and 12–17 (`A2`) are
present; the WIN-1 pre-window hours 10–11 (`A3`) are present; NO-side pricing
(`B2`) is present; ask-screen variants (`C2`) are present.

### 2.0 Hour partition — resolved as WINDOW-POOLED (amendment A1)

The plan's clause (i) names "windows × **hour partitions** × side pricing ×
station subset". The first draft of this document dropped the hour dimension
from the enumeration and then re-admitted it in §3 as a free maximum ("clears
the bar within a reported hour"). That is the mandated dimension converted from
a corrected one into an uncorrected max-over-hours: a 12–17 window would get
five shots and pay for one, making the Holm correction cosmetic. Domain review
called it fatal as written, correctly.

**Resolution: the bar is evaluated on the WINDOW-POOLED cell.** Per-hour tables
are computed and reported as **diagnosis only and are never a selection
surface** — no variant may be declared a winner on the strength of one hour.
This keeps `K_variants = 12` rather than folding hours in (which would give
`(3+5+2) x 2 x 2 = 40` and a step-one threshold of `0.00125`, destroying power
for no inferential gain), and it removes the hour degree of freedom outright
instead of correcting for it. Pooling also raises n per cell, which is where
this study is weakest.

### 2.1 Station subset is NOT a variant dimension — declared now

The selection unit is **the four-station pool, always**. Per-station tables are
reported for diagnosis and are **never** a selection surface. Choosing a station
subset after seeing results is a researcher degree of freedom this registration
removes outright rather than corrects for. The §B(iii) continuation (reduce the
station set) remains available, but only via a ruling that names the new set
*before* its confirmatory series begins — never by picking the best subset from
a screen table.

### 2.2 Fixed across every variant (not searched)

Trial unit **one station-day, first filled take**, never per-hour rows.
Quantity 1. Hold to settlement; the exit seam stays UNARMED. Liftability is
qty=1 L0-fillable from Depth10. Incomplete tape days are excluded.

**Fee formula, pinned verbatim (amendment A2 — this was wrong in the first
draft).** The venue fee is **not** flat:

    fee = theta * price * (1 - price),  theta = 0.0695

matching `decision.py:394` (`break_even = price + _fee(price, coeff)`) and the
venue's own published schedule. At ask 0.30 the fee is 0.0146; at ask 0.50 it
reaches its maximum 0.0174. `theta` is never a searched parameter and never a
pinned edit — the 09-17 drift is recorded in
`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md` and is not
absorbed here. **`forecast_tape_screen.net_edge` currently subtracts
`DEFAULT_FEE = 0.0695` FLAT (`forecast_tape_screen.py:136`) and MUST NOT be
used unmodified for WP-7**: a flat subtraction inflates the hurdle by roughly
5x and would manufacture a null result that looks like "no edge found".

**Pinned decision parameters (amendment A3), all frozen before the first run:**

| Parameter | Pinned value |
|---|---|
| `p_fc` family | **rung** (the venue's actual trading unit), never the median family |
| rung eligibility | every legal rung scanned, both sides where `B2` |
| first-take tie-break | greatest post-fee margin; ties by lowest ask; then lowest rung lower bound — fully deterministic |
| `min_edge` for the take | `> 0` (identical to the live rule); the 0.03 median bar in §3 is a REPORTING gate, not the take threshold |
| cycle / lead | the latest cycle whose vintage `<= ` the decision instant; **no lead or cycle-age partition** |
| staleness bound | the live config's `stale_observation_minutes` — not a free parameter |
| `no_bid_side` (B2) | counted as a **no-take**, never a dropped day, so it depresses take counts honestly instead of inflating the positive rate by discarding hard days; the rate is reported |
| `sigma` | **frozen as fitted in 0b (amendment A4)**; any re-fit against price is a new registration, not a knob |
| bootstrap cluster | **date is the single PRIMARY and decisional cluster**; the station-clustered interval is reported as sensitivity only and is explicitly non-decisional |

## 3. The per-cell measurement gate (not a hypothesis test)

A cell is **reportable** only at `n >= 20` station-days. A cell **clears the
bar** when, **on the window-pooled cell** (§2.0 — never on a single hour):
`n >= 20` station-days, `> 50%` of trials have post-fee margin `> 0`, and the
**median** post-fee margin `>= 0.03`.

Margin is `p_fc - (price + fee)` evaluated at the liftable price on the side
being scored, i.e. the same quantity the live take rule uses. A flat
`median >= 0.03` is the **Stage-0 measurement gate only**; live trading uses
`margin(h, n_cell, cfg)` from `scoring.py`.

## 4. 0b PASS / INSUFFICIENT-DATA / halt

- **0b PASS** — at least one pre-declared variant clears §3 in at least one
  reported hour, **and** survives Holm–Bonferroni across all 12.
- **INSUFFICIENT-DATA (extend; never a verdict, never a PASS)** — any cell,
  hour or window that never reaches `n >= 20` station-days; or a two-lag PIT
  that flips PASS/FAIL for a cell. Extend the corpus or the shadow period.
  INSUFFICIENT-DATA exits 0 and never raises.
- **Halt** — all 12 variants fail with adequate n. Escalates to a strategy-lead
  ruling per §1(iii).

## 5. Predictions recorded now, against our own interest

Registered before the run so they cannot be retrofitted:

1. **The forecast is probably already in the price.** The venue prices the same
   public NBS guidance this study consumes. `L-7` is the standing expectation;
   §4.8 cycle-age-vs-margin is its test. A null result here is the *expected*
   outcome, not a surprise.
2. **CORRECTED (amendment A2). The hurdle is ~4.5–4.8 points gross, not ~10.**
   The first draft of this prediction asserted a flat 6.95-point fee and a
   ~10-point hurdle. That was wrong: the fee is `theta * price * (1 - price)`,
   i.e. 1.46 points at ask 0.30 and a maximum of 1.74 points at ask 0.50. So
   clearing a 0.03 median net bar needs roughly **4.5–4.8 points of gross
   edge**. I had overstated the hurdle by about 5x, which would have biased me
   toward reading a null as structural rather than as an artefact. Recorded
   because the error is the more interesting datum than the corrected number:
   the same flat-fee mistake is live in `forecast_tape_screen.py:136` and would
   have produced exactly that false null.
3. **The rung model is under-confident and will under-fire.** The 0b artefact
   measured uniform under-confidence on the rung family (mean signed deviation
   `+0.079`, 3 of 5 buckets breaching `epsilon = 0.05`). A screen using this
   `p_fc` should therefore produce **fewer** would-takes than a calibrated model
   would. A variant that produces many takes deserves suspicion, not celebration.
4. **`no_bid_side` will be material on the NO leg.** The YES bid side is
   frequently empty on this venue; `B2` variants must report the `no_bid_side`
   rate alongside their take counts, and a high rate makes a NO-side result
   unliftable regardless of its margin.
5. **The tradeable-family skill is +0.025 BSS, not +0.59 (amendment A5).** The
   0b headline of `BSS +0.59` is the **median-exceedance** family, which is not
   what the venue trades. On the **rung** family — the actual trading unit —
   0b measured Brier 0.2348 against a constant's 0.2409, i.e. **BSS +0.025**,
   with raw MAE 1.67–1.96 °F against a 2 °F rung. The forecast barely resolves
   the unit it would have to trade. Any WP-7 result must be read against that
   number, not the headline.
6. **If an edge survives, it is most likely a stale-repricing effect**, not
   superior meteorology: the venue prices the same public NBS guidance, so the
   plausible residual is the interval between a cycle publishing and the venue
   re-quoting, plus the empty-bid-side microstructure. `A3-B1-C2` (10–11 LST
   pre-window, YES, ask-screened) is the single variant in the set aimed at
   that mechanism, and is where I expect a survivor to appear if one does.

## 6. Sign-off

Registration is not effective until a prediction-market domain review has
signed off on the variant set and the multiplicity correction **before the
first run**, per WP-7 owner assignment (B runs; prediction-market-reviewer
signs the variant set and multiplicity). Record the sign-off verdict and its
date below.

| Role | Verdict | Date |
|---|---|---|
| Strategy lead (coordinator) | REGISTERED (amended A1–A5) | 2026-09-20 |
| prediction-market domain review | APPROVED WITH AMENDMENTS A1–A5 (A1, A2 blocking) — all five applied | 2026-09-20 |

### 6.1 Amendments applied from domain review

| # | Finding | Resolution |
|---|---|---|
| A1 (blocking) | Hour partition dropped from the enumeration, then re-admitted as a free max-over-hours — correction cosmetic | §2.0: bar is WINDOW-POOLED; per-hour tables diagnosis-only, never selective; `K_variants` stays 12 |
| A2 (blocking) | Fee asserted flat at 6.95 pts; real fee is `theta*price*(1-price)` (max 1.74 pts). `forecast_tape_screen.net_edge` subtracts it flat and would manufacture a null | §2.2 pins the formula; §5.2 corrects the hurdle to ~4.5–4.8 pts and records the error; the flat-fee code path is named as unusable for WP-7 |
| A3 | Eight unenumerated knobs (p_fc family, rung eligibility, tie-break, `min_edge`, lead/cycle, staleness, `no_bid_side`, bootstrap cluster) | §2.2 pins every one, with a single decisional bootstrap cluster |
| A4 | `sigma` re-fit against price would carry 2021–2025 selection into the frozen model | §2.2: sigma frozen as fitted in 0b; any re-fit is a new registration |
| A5 | Headline BSS +0.59 is the non-tradeable median family | §5.5: the rung family's +0.025 is recorded as the number WP-7 must be read against |

Holm–Bonferroni at FWER 0.05 one-sided across K=12 is retained on review advice:
BY under arbitrary dependence would be *stricter* at the first rejection
(`0.00134` vs Holm's `0.00417`), costing power, and FWER is the right error rate
when a single frozen winner carries live money.
