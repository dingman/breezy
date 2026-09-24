# AUD-18 — A closed, multiplicity-controlled design/backtest/iterate programme that produces (or honestly refuses) AUD-02's "genuinely independent edge estimate"

## 1. ID and actionable title

**AUD-18** — A bounded, pre-registered hypothesis-testing PROGRAMME that sits
above the mechanical replay engine (AUD-09) and consumes its artefacts, so that
"design, backtest, and iterate on the strategy" (operator request, verbatim)
stops meaning one-off scratchpad studies and starts meaning: every candidate
strategy change is registered before any data is looked at, is evaluated only
once real station-days accumulate to a pre-declared minimum, is scored under a
programme-wide multiplicity correction so repeated tries cannot manufacture
significance, and the programme as a whole reaches either a signed positive-
expectancy evidence pack or an honest, evidenced KILL — never an indefinite
"still looking."

## 2. Source finding, verdict, class

Gap **G-02** (`AUTONOMY_ROI_AUDIT_2026-09-21.md:37-43`, verdict FALSE): no
demonstrated edge; the live family's own `p_hold` table is independently
CONFIRMED invalid for live use (`DECISION_FUNNEL_2026-09-20.md`, "archive-table
train/serve skew", domain reviewer: **"UNSALVAGEABLE, not merely
miscalibrated"** absent real historical venue ladders, which do not exist).
**Class: verification/research-programme gap** — the missing piece is not a
code defect, it is a governed process that turns future capture into an
admissible edge estimate or an admissible refusal.

**Relationship to AUD-02 (read, not restated):** AUD-02 adopts
`POST_FORECAST_PHASE_2026-09-20.md` as the plan of record for G-02 and widens
A1's precondition to require "a genuinely independent edge estimate" computed
**without** relying on the collider-conditioned `P_HOLD` cells
(`DECISION_FUNNEL_2026-09-20.md`, "Why 'recalibrate on the gate-pass subsample'
is NOT the remedy"). AUD-02 does not say how that estimate would be produced if
one ever could be — it names the precondition and the blocker. **AUD-18 is the
engine that would produce it**, under a protocol strong enough that its output
is trustworthy evidence rather than a fourth retracted result (this repo has
already retracted three: memory `implausible-result-is-a-leak`,
`bss-headline-is-the-wrong-family`, and the underpowered-negative correction in
`RULING_forecast_edge_programme_closes_2026-09-20.md` §7).

## 3. Current behaviour, required behaviour, concrete gap

**Current.** Every hypothesis this repo has tested was pre-registered and
scored **individually** (`PREREG_v2`..`v5`, `PREREG_WP7b_MARKET_AS_FORECASTER`).
One document, `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`, DID
register a bounded, Holm–Bonferroni-corrected variant space (`K_variants=12`)
for one hypothesis (the forecast-taker cheap screen) — but that correction is
**scoped to that one hypothesis's own variant space**, not to the programme.
Nothing tracks cumulative alpha spent **across** hypothesis classes (forecast
taker, maker/resting, NO-side, archive-table recalibration, …) over the
programme's life. AUD-09/AUD-10 build the mechanical replay/promotion pipeline
for **one already-armed family** and explicitly exclude any multi-hypothesis or
multi-variant design question (AUD-09 §5: no change to the driver's family
argument; AUD-10 §5: `C-PAIRED` is a single champion-vs-challenger predicate).
**No artefact today decides which of the several live, partially-explored
hypothesis classes is worth the next compute-hour**, and nothing prevents a
future run from re-testing a class after a bad look the way the repo's own
discipline note (`RULING §7`) records it already had to catch three times by
hand.

**Required.** A single programme-level pre-registration ledger that: (a) is the
one place a new hypothesis is admitted, with its own bounded variant
enumeration, metric, minimum-n stopping rule, and abandonment criterion, mirror-
ing the already-proven shape of `PREREG_WP7_MULTIPLICITY_RULE` and the WP-table
shape in `POST_FORECAST_PHASE §1`; (b) tracks a programme-wide family-wise alpha
budget so a hypothesis is only evaluated when its pre-declared look boundary is
reached, and the budget is visibly spent, never silently re-spent by a re-run;
(c) triages every registered hypothesis against AUD-09a's replay-sufficiency
census **before** any compute is spent, so an insufficient-data hypothesis is
PARKED, not evaluated on a starved sample; (d) computes the confirmatory
statistic only through the repo's own existing, reused settlement primitives
(`combine_station_day`/`score_combined`, `settlement/current_rung_hold_v2.py`)
over station-day-clustered draws, on the ONE station-day observation §6.1 pins
for both the power check and the confirmatory test — the MEAN excess per take,
never the station-day SUM, gated on AUD-11/AUD-12 validity exactly as
AUD-10's `C-VALIDITY` already gates promotion; (e) ends at one of two states,
both concrete: a signed evidence pack under `docs/evidence/` with a CI that
excludes zero, handed to AUD-02's A1 and readable by AUD-10b, **or** the
declared cap exhausted with no survivor, escalating to the strategy lead as a
programme KILL — the same shape `PREREG_WP7_MULTIPLICITY_RULE §1(iii)` already
uses for one hypothesis, raised to programme scope.

**Concrete gap.** No programme-level alpha ledger exists; no artefact joins
AUD-09's sufficiency/results census to a hypothesis's own stopping rule; no
document states which of the still-open hypothesis classes are triaged IN vs
OUT before compute is spent (§6.3 does this explicitly, for the first time).

## 4. Priority, rationale, dependencies, execution order

- **P1.** Not P0: no live-money safety issue (this item never arms anything).
  It is the item that decides whether continued PM.us engineering investment
  is evidence-justified at all — every day it is absent, ad hoc studies keep
  running without a shared alpha budget, which is exactly the failure this
  item's own §3 evidence (three retracted results) shows already happened.
- **Depends on AUD-09 (a and b)** for the mechanical replay engine and its two
  hand-off artefacts this item reads: `replay_sufficiency.jsonl` (H0) and
  `replay_results.jsonl` (H3). AUD-18 builds no replay capability of its own.
- **Depends on AUD-11 and AUD-12 by id**, exactly as AUD-10's `C-VALIDITY`
  does: no hypothesis may be CONFIRMED while `validity == "MECHANISM_ONLY"` or
  `params_match == false`; only PARKED/EVALUATING states are reachable until
  both land.
- **Depends on AUD-02** for the standing evidence (the calibration-defect
  finding, the terminal forecast-taker ruling) that scopes which hypothesis
  classes are admissible at all (§5), and for A1's status as the ruling
  authority for the flagship family specifically — AUD-18 supplies A1's
  evidence, it does not replace A1.
- **Feeds AUD-10b**: a CONFIRMED hypothesis's evidence pack is the input
  `C-ESTIMATOR`/`C-N` need for any family **other than** the current champion;
  for the champion itself it is A1's input via AUD-02.
- **Execution order:** AUD-09a/b land first (already ordered in their own
  plan) → AUD-11/AUD-12 flip `REPLAY_VALIDITY` → AUD-18's ledger + triage
  script land and are exercised against whatever the census already shows →
  first hypothesis intake (§7 step 8) → ongoing.

## 5. Scope and explicit exclusions

**In scope.** (a) The programme-level pre-registration ledger format and the
multiplicity rule governing it (§6.1); (b) a pure core module
(`hypothesis_ledger.py`) plus two I/O scripts (register, triage) that enforce
it mechanically against AUD-09's artefacts (§6.2–§6.4); (c) triage of the
specific hypothesis classes named in §6.3 against present-day data sufficiency,
including which are CLOSED and must not be re-run; (d) the hand-off contracts
to AUD-02 and AUD-10b (§6.5).

**Explicitly excluded.**

- **Re-running the forecast-taker hunt.** CLOSED, TERMINAL
  (`RULING_forecast_edge_programme_closes_2026-09-20.md`). Not reopened here
  under any circumstance, per the brief's own instruction and the ruling's §4.
- **Deciding A1.** That is AUD-02's named strategy-lead BLOCKER; this item
  supplies inputs to it, never the ruling.
- **Building any new pricing/window/side strategy VARIANT's implementation.**
  Once a hypothesis is registered (§7 step 8), the variant's own code change
  (e.g., a maker/resting config, a NO-side config) is a **separate**, smaller
  work package with its own RED/GREEN cycle, scoped and briefed when that
  hypothesis is actually triaged IN — not designed speculatively here. This
  item builds the LEDGER and the TRIAGE, not the strategies it will govern.
- **Any change to `ContinuousRungHoldBacktestStrategy`, `backtest_harness.py`,
  the fill model, or `current_rung_hold_paper_replay.py`** — reused unchanged,
  same exclusion AUD-09 §5 states.
- **Widening `SUPPORTED_STATIONS` or building a Kalshi adapter.** The Kalshi
  surface is named in §6.3 as a future class and is explicitly NOT scheduled —
  memory `polymarket-us-first-kalshi-secondary` is binding; Kalshi lives on
  `wip/kalshi-s4-registry` and needs its own measurement track, not this one.
- **Any edit to AUD-09's or AUD-10's plan text, wrapper, or named script
  set.** Both are closed at 100/100 and AUD-09 **B18**/AUD-10 **C19** close
  `deploy/systemd/replay-daily-run.sh` to three named scripts
  (`replay_sufficiency_census.py`, `replay_daily_runner.py`,
  `promotion_proposal.py`), failing "an unnamed fourth". AUD-18 appends no
  `"$PY"` invocation there; it ships its own unit/timer/wrapper (§6.4b) and a
  non-regression RED (§7 step 5, D5).
- **Any group-sequential (repeated-look) design, and the NEW pinned boundary
  artefact one would require** (a reference table at any `alpha != 0.025` or
  `i_max != 40`). The shipped loader refuses off-pin artefacts by design
  (`gs_boundary_artefact.py:269-272`), and §6.1 shows no allocation under this
  programme's multi-hypothesis budget can ever reach the pinned `0.025`.
  `LD_OBF` is therefore WITHDRAWN as a selectable look policy here (§6.1);
  reinstating it is a future amendment needing its own ruling and its own
  pinned artefact, registered as separate work.
- **A heavy job.** The triage script (§6.4) is cheap (JSONL joins, no tape
  scan): its own unit is a `Type=oneshot` timer sibling of the existing
  nightly analysis units, capped an order of magnitude below them — not a new
  study, and it never reads the tape.

## 6. Proposed changes (grounded in inspected code/config/data flows)

### 6.1 The multiplicity rule, raised from one hypothesis to programme scope

**Native precedent, not invention.** `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md`
already proves this shape works in this repo: bounded enumeration (§1.i),
Holm–Bonferroni family-wise correction at the *selection* decision (§1.ii), a
**declared cap** whose exhaustion is "a legitimate halt that escalates to a
strategy-lead ruling" (§1.iii), full logging of every attempted variant
including failures (§1.iv), and a freeze-date firewall separating the search
corpus from the confirmatory corpus (§1.v). AUD-18 does not re-derive this
math; it **generalises the ledger** so the same discipline spans every
hypothesis class registered over the programme's life, not just one document's
12 variants.

**The mechanism, stated once and implementable exactly as written: FIXED
a-priori alpha allocation (Bonferroni split at registration), never a
data-dependent step-down.**

- The programme declares, before any intake, three constants that live in the
  ledger module (§6.2): `PROGRAMME_ALPHA` (one-sided), `MAX_HYPOTHESES` — the
  pre-declared maximum number of LOOK-TAKING hypotheses the programme will EVER
  register — and `MAX_VARIANTS_PER_HYPOTHESIS`, the hard ceiling on any one
  hypothesis's bounded enumeration.
- **The constants are derived, not chosen for roundness.** `MAX_HYPOTHESES = 4`
  is exactly §6.3's own count of hypotheses that could ever take a look under
  this programme: the three genuinely open classes (archive-table
  recalibration, NO-side hunting, the hours 10-11 repricing window) plus ONE
  reserve slot for the "genuinely different" maker/resting redesign §6.3 names
  as a possible future registration. Nothing else in §6.3 is registerable —
  the forecast-taker class is CLOSED/TERMINAL and Kalshi is out of scope — so a
  larger cap would be alpha given away to hypotheses that do not exist, and a
  smaller one would refuse a class §6.3 already lists as open.
  `MAX_VARIANTS_PER_HYPOTHESIS = 4` encodes the programme's standing
  preference for **fewer, sharper hypotheses over broad variant sweeps**: at
  PM.us sample sizes a 12-wide sweep buys breadth at a 3x alpha cost per
  variant, and this repo's own WP-7 history is the evidence that the breadth
  did not pay. Together they floor `per_variant_alpha` at
  `0.05 / 4 / 4 = 0.003125` one-sided — roughly 6x the ≈0.0005 a 12-variant
  split under an 8-hypothesis cap would have left.
- At registration a hypothesis receives `allocated_alpha = PROGRAMME_ALPHA /
  MAX_HYPOTHESES`, split again across its own bounded enumeration:
  `per_variant_alpha = allocated_alpha / k_variants`, with
  `1 <= k_variants <= MAX_VARIANTS_PER_HYPOTHESIS`. Allocation happens ONCE,
  at registration, before any of that hypothesis's data is opened, and is
  **never recycled**: a REJECTED variant's share is not returned to the pool,
  and once `MAX_HYPOTHESES` look-taking registrations exist
  `register_hypothesis` REFUSES a further intake rather than shrinking anyone's
  prior allocation.
- **Zero-look records consume neither a slot nor alpha.** Two record kinds are
  bookkeeping, not tests, and are therefore registered with
  `allocated_alpha = 0.0`, counted OUTSIDE `MAX_HYPOTHESES`, and exempt from
  the `k_variants` ceiling: the CLOSED forecast-taker disposition record (§7
  step 7, `status=REJECTED`, `k_variants=12` matching its own prior
  pre-registration — it was scored there, never here) and an
  `UNDERPOWERED_NOT_REGISTERED` record (next bullet). Neither may ever carry a
  `HypothesisLook` row, and a look attempted against one is a hard refusal.
- **A POWER CHECK precedes every allocation; an underpowered hypothesis is
  refused, not registered.** Controlling the error rate says nothing about
  whether the allocated alpha can detect anything, and this repo has already
  paid for that omission once (the underpowered-negative correction,
  `RULING_forecast_edge_programme_closes_2026-09-20.md` §7, at the far looser
  `alpha = 0.05`). So: before any of a hypothesis's data is opened, the §7 step
  8 peer ruling MUST state the **minimum detectable effect (MDE)** at the
  assigned `per_variant_alpha` for the pre-registered `min_station_days`, and a
  **plausibility bound**: the largest true effect the ruling is willing to
  assert this venue could plausibly carry. `register_hypothesis` REFUSES any
  hypothesis whose MDE exceeds that bound, writing an
  `UNDERPOWERED_NOT_REGISTERED` record that **consumes no alpha and no slot**,
  so a hypothesis the sample cannot resolve costs the programme nothing instead
  of silently burning a quarter of its budget.
- **The MDE convention is PINNED, mechanical and outcome-free — it is not a
  judgement call, and it is RECOMPUTED by the code.** A prospective MDE needs
  an *assumption*, never realized rows: `combine_station_day`/`score_combined`
  (`src/breezy/settlement/current_rung_hold_v2.py:298,348`) are estimators over
  REALIZED `StratumRow` data and `ROIBoundUnderpowered`/`compute_roi_bound`
  (`src/breezy/settlement/roi_bound.py:100,130,173`) is a POST-HOC `n >=
  MIN_NON_EXCLUDED_N` floor on already-collected rows that computes no effect
  size — **neither is precedent for a pre-data MDE, and neither is cited for
  that purpose here** (both keep their existing, correct roles at §6.4 step 4
  and in settlement). The pinned convention instead is:
  - **Unit of analysis = the station-day (clustered).** `n` is the
    pre-registered number of station-days (`min_station_days` summed over the
    registered strata) — never the number of takes.
  - **Variance input = the conservative, outcome-free Bernoulli bound
    `q(1 - q) <= 1/4`.** This is this repo's OWN established convention, not a
    new one: it is the derivation behind the shipped boundary artefact's pin
    `I_MAX = 40.0` (`src/breezy/persistence/gs_boundary_artefact.py:75-78`,
    "`n_max/4` -- the Bernoulli variance bound"), specified as
    `I_max = n_max x 1/4 = 160/4 = 40`, "the theoretical bound, fixed once, ex
    ante", in `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md:55-60`,
    which **forbids substituting a live or look-1 estimate**. The same
    prohibition binds here: sourcing the variance from a peek at this
    hypothesis's own draws is the defect the freeze-date firewall exists to
    prevent.
  - **The station-day OBSERVATION is PINNED as a MEAN, not a sum -- this is
    what makes `1/4` a true bound for ANY side mix, ANY leg count and ANY
    dependence.** For a station-day `d` carrying `m_d >= 1` takes, the
    observation entering BOTH the power check and the confirmatory test is
    `X_d = (1 / m_d) * Sum_i (W_i - BE_i)`, where `W_i` in `{0, 1}` is whether
    leg `i`'s OWN side won and `BE_i` is that leg's OWN break-even net of
    `theta = 0.0695` and slippage (the `BE` formula below). **Derivation:**
    each term `W_i - BE_i` takes exactly two values, `1 - BE_i` and `-BE_i`,
    so it lies in an interval of width `1`; an average of numbers each lying
    in a width-`1` interval lies in an interval of width at most `1`; and by
    **Popoviciu's inequality** a random variable confined to an interval of
    width `w` has `Var <= w^2 / 4`, hence `Var(X_d) <= 1/4`. That argument
    uses NO independence and NO side-mix assumption, so it holds for a mixed
    YES+NO station-day and for any `m_d`. **The station-day SUM does NOT have
    this property**, which is why it is not the statistic here:
    `combine_station_day`'s covariance term
    (`src/breezy/settlement/current_rung_hold_v2.py:342-344`,
    `variance -= 2 * qty_i * qty_j * s_i * s_j * q_i * q_j`) SUBTRACTS only
    when the two legs share a side (`s_i * s_j = +1`); for an OPPOSITE-side
    pair it **ADDS**, and at `q = [0.5, 0.5]`, `qty = 1`, one YES leg and one
    NO leg the SUM's variance is `0.25 + 0.25 + 0.5 = 1.0` -- **four times**
    `VARIANCE_BOUND`, and NOT refused by the admission gate, which fires only
    on `Sum_i q_i > 1` (`current_rung_hold_v2.py:331`) while this day sums to
    exactly `1.0`. Mixed-side designs are not hypothetical here: NO-side
    hunting is one of §6.3's three open, registerable classes. **What the mean
    statistic estimates, stated honestly:** the AVERAGE EDGE PER TAKE,
    equal-weighted WITHIN a station-day and equally across station-days. It is
    **NOT the day's P&L** -- a station-day with many legs counts exactly once,
    the same as a one-leg day, so a design that concentrates its takes on a
    few days is measured on its per-take edge, not its aggregate return. That
    is deliberate and CONSERVATIVE for this purpose: it caps the variance at
    `1/4` without assuming anything about how legs co-move, and it keeps the
    unit of analysis the clustered station-day §6.1 already pins. Aggregate
    return is the subject of ROI accounting (§6.4 step 4's `roi_bound` path
    and settlement), which correctly keeps the SUM.
  - **Zero-take station-days (`m_d = 0`) are EXCLUDED at a NAMED filter stage,
    BEFORE any statistic is computed -- and are COUNTED, never silently
    dropped.** `X_d` is defined only for `m_d >= 1` (an average over no takes
    is undefined), and `m_d = 0` is not a corner case here. AUD-09 **§6b.3**'s
    `replay_results.jsonl` schema records `trials, fills` on every row and
    admits `outcome = COMPLETED` independently of `fills`
    (`docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md:697-702`),
    so a mechanically successful replay that found no eligible take writes a
    legitimate `COMPLETED` row with `fills = 0`. That is this bot's DOMINANT
    real-world state, not a hypothetical:
    `docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,11-16` MEASURES **0 of
    40,796** decisions reaching a price on 2026-09-20 and **0 of 53,624** on
    2026-09-16. Feeding such a row's (empty) leg set to the reused primitive
    would RAISE -- `combine_station_day` refuses an empty `rows` outright
    (`src/breezy/settlement/current_rung_hold_v2.py:318-319`, "a combined draw
    over nothing is undefined") -- so the filter is what keeps the triage from
    crashing, and it is stated here rather than left implicit:
    - **The filter stage is §6.4 step 4's DRAW-SET CONSTRUCTION**, between the
      `C-VALIDITY` gate and the FIRST call to `combine_station_day`. A replay
      row with `fills == 0` is dropped there, before any draw exists, so the
      empty-day `ValueError` is unreachable on this path by construction.
    - **Both counts are REPORTED on the look row** (§6.2):
      `n_station_days_observed` (every admissible replay row for the variant,
      `fills = 0` INCLUDED) and `n_station_days_with_takes` (those surviving
      the filter). A day that produced no take is visible as data about the
      strategy, never as a silent absence.
    - **`n`, `min_station_days` and `n_station_days` mean station-days WITH
      `>= 1` take** -- everywhere in this item: §6.1's MDE formula, §6.4 step 3's
      scheduling recomputation, the §7 step 8 ruling, and the confirmatory look.
      The power check's `n` is therefore the WITH-TAKES count, so a hypothesis
      can never be scored on a sample smaller than the one its MDE was computed
      against by counting empty days toward it.
    - **A hypothesis whose take-rate cannot reach `min_station_days` with-takes
      days inside its horizon is caught by the horizon/KILL rule, never silently
      diluted:** it simply stays `PARKED_INSUFFICIENT_DATA`, emits §6.4 step 7's
      advisory alert at the declared horizon, and is read under §6.6 -- the same
      machinery a data-blocked class already uses. No look is taken, no alpha
      is spent, and no test is scored on a starved sample.
    - **The SELECTION CAVEAT, stated honestly:** conditioning on `m_d >= 1` IS
      conditioning on the strategy's own trigger, so the estimand is explicitly
      "edge per take GIVEN the strategy took" -- which is exactly what
      `MEAN_EXCESS_PER_TAKE` claims to be, and exactly the input AUD-06a/AUD-06b
      need. It says NOTHING about how OFTEN the strategy trades. The look row
      therefore reports the TAKE RATE
      (`n_station_days_with_takes / n_station_days_observed`) ALONGSIDE the
      estimate, and the §7 step 8 ruling reads it: a CONFIRMED edge at a
      near-zero take rate is handed on with that rate attached, never as a
      headline on its own.
  - **A MANDATORY, ALPHA-FREE, VETO-ONLY POOLED-P&L GATE stands between a
    passing primary test and any `CONFIRMED` disposition.** The MEAN
    equal-weights station-days regardless of leg count while real P&L is
    leg-weighted (at the pinned `qty = 1` each leg's face value is $1, so
    `W_i - BE_i` IS that leg's realized net P&L per contract), and the two can
    disagree IN SIGN: nine one-leg station-days winning at `ask ~ 0.02`
    (`X_d ~ +0.94` each) against ONE hundred-leg station-day losing at
    `ask ~ 0.98` (`X_d ~ -0.98`, capped in `[-1, 1]` by construction no matter
    how many legs) give `Sum_d X_d ~ +7.5` -- a decisive primary CONFIRM --
    while pooled dollars are `9 x 0.94 + 100 x (-0.98) ~ -89.5`, decisively
    NEGATIVE. A confirmatory result that can lose money in aggregate is not the
    "genuinely independent edge estimate" §3 requires, so:
    - **The gate.** Over the SAME confirmatory sample -- same variant, same
      with-takes station-days, same single look -- compute
      `pooled_net_pnl_per_contract = Sum_d x_d`, where `x_d` is
      `CombinedDraw.x` from the EXISTING SUM machinery,
      `combine_station_day` (`src/breezy/settlement/current_rung_hold_v2.py:298`,
      `x = sum(qty * ((1.0 if row.held else 0.0) - be) ...)` at `:337-340`).
      No new estimator, no new field on any AUD-09/AUD-10 artefact. **"Net"
      means net of cost:** each leg's `BE_i = break_even_row(entry_ask_i, fee_i)`
      (`:76-84`) already carries the venue fee at the evidenced
      `theta = 0.0695` and AUD-12's slippage allowance, exactly as this
      section's `BE = a + theta * a * (1 - a) + slippage` defines it. A
      `CONFIRMED` disposition REQUIRES `pooled_net_pnl_per_contract > 0`
      STRICTLY.
    - **It can only VETO, never promote.** Primary passes AND pooled `> 0` ->
      `CONFIRMED`. Primary passes AND pooled `<= 0` -> the named non-confirming
      TERMINAL status `PRIMARY_PASSED_PNL_VETO`: the variant is never re-looked,
      is NOT handed to AUD-02/A1 (H5) or AUD-10b (H6), and its alpha IS
      CONSUMED -- the look was taken, and pretending otherwise would be the
      re-spend §6.1 exists to prevent. Primary FAILS -> `REJECTED` regardless of
      the pooled number; a positive pooled P&L can NEVER rescue a failed
      primary.
    - **Why a veto-only gate needs no alpha allocation.** It can only SHRINK
      the rejection region -- the set of outcomes declared `CONFIRMED` is a
      strict SUBSET of the primary test's -- so the Type-I error rate under H0
      remains bounded by that variant's `per_variant_alpha`, unchanged, and the
      union bound over the programme is untouched. It is not a second
      hypothesis test and must not be corrected as one. The cost is POWER, not
      validity, and it is accepted deliberately (the same trade §12 already
      records for a forfeited variant share).
    - **Leg-count concentration is bounded too, because it is cheap.** The look
      row records `max_single_day_leg_share` -- the largest share of the
      variant's TOTAL legs contributed by any ONE station-day -- and the design
      PRE-REGISTERS a cap on it. **The cap is PINNED at `0.20`**, one number for
      every hypothesis, not a per-hypothesis dial -- and it is a PRAGMATIC,
      PRE-REGISTERED CONCENTRATION GUARDRAIL, not a derived property of the
      estimator: it is pinned in the same spirit as the conventional
      `POWER = 0.80`, fixed once, before any data, so that no look can choose
      it. **What it does NOT do, said plainly: a leg-COUNT share does not bound
      a P&L-DOLLAR share.** Each leg contributes `W_i - BE_i`, which depends on
      that leg's OWN entry ask and outcome, so a station-day sitting just under
      `0.20` of the legs can still carry a disproportionate share of the pooled
      dollars. **The money-losing-CONFIRM gap is closed by the STRICT
      `pooled_net_pnl_per_contract > 0` condition above, NOT by this cap** --
      at the pinned `qty = 1` that pooled sum IS the sample's exact realised net
      P&L per contract, so a sample that lost money cannot reach `CONFIRMED`
      however its legs are distributed. This cap is an ADDITIONAL ROBUSTNESS
      SCREEN on top of that: it refuses an estimate whose evidence base sits in
      one station-day even when the pooled dollars are positive. PM.us's
      5-station daily-HIGH surface reaches `0.20` naturally at any
      `min_station_days` this programme could pre-register. A look whose
      realized share EXCEEDS the pre-registered cap records that fact and takes
      the SAME terminal state, `PRIMARY_PASSED_PNL_VETO` with
      `veto_reason = "LEG_SHARE_ABOVE_CAP"` -- an estimate carried by one day
      is not a programme result.
  - **Which statistic each use of `combine_station_day` needs -- checked use
    by use, because the two are not interchangeable.** (a) §3(d), §6.4 step 4
    and §7 step 3 -- the CONFIRMATORY TEST statistic and its clustered
    bootstrap CI: **MEAN** (`MEAN_EXCESS_PER_TAKE`), for the bound above;
    `combine_station_day`'s per-leg `held_i - BE_i` terms and its admission /
    same-rung-fold / opposite-side refusals are still the reused primitive
    that BUILDS those terms -- only the across-leg aggregation changes from
    sum to mean. (b) §6.1's power check: **MEAN**, same reason -- and this is
    the use the `1/4` bound is consumed by. (c) ROI ACCOUNTING wherever the
    repo already does it (`src/breezy/persistence/realized_draws.py`,
    `scripts/analysis/family_tally_v2.py`, settlement): **SUM**, unchanged and
    correct -- P&L is additive across legs, a mean would understate a
    many-leg day's realized return, and no `1/4` bound is claimed there.
    AUD-18 changes NOTHING about (c).
  - **Order quantity is PINNED at 1 for every hypothesis this programme
    registers.** Under the MEAN statistic pinned above the `1/4` bound no
    longer DEPENDS on this (the mean of `W_i - BE_i` terms carries no `qty`
    factor at all), so the pin is belt-and-braces rather than load-bearing --
    but it stays, both because it is the live family's own convention and
    because it removes the `qty^2` blow-up from every statistic this item
    touches, including the SUM used for ROI accounting:
    `combine_station_day` scales each leg's variance by `qty^2`
    (`src/breezy/settlement/current_rung_hold_v2.py:341`: `variance = sum(qty *
    qty * q * (1.0 - q) ...)`) and its admission gate bounds only
    `sum_i q_i <= 1`, never `qty`. At `qty_i = 2` a single leg alone
    contributes `4 * q(1 - q)`, up to `1.0` -- four times the assumed ceiling,
    which would make the recomputed MDE UNDER-state the true MDE, the UNSAFE
    direction (a hypothesis would look adequately powered when it is not).
    Unit quantity is not a new convention invented here: it is the live
    family's own pinned one -- `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md:110-113`
    (SS2.2 "Fixed across every variant (not searched) ... Quantity 1"), and
    `CurrentRungHoldConfig.__post_init__` already raises
    `InvalidOrderQuantityError` ("order_quantity must be exactly 1",
    `src/breezy/strategy/current_rung_hold/config.py:253-255`). Every
    hypothesis registered by AUD-18 is therefore **evaluated at unit
    quantity**, and `register_hypothesis` REFUSES -- naming the reason
    `NON_UNIT_ORDER_QUANTITY` -- any hypothesis whose declared design carries
    `order_quantity != 1`. **Sizing above 1 is NOT this item's subject:** it
    belongs to **AUD-06a**'s boundary revalidation and **AUD-06b**'s sizing
    (both cited by id only). A CONFIRMED unit-quantity edge is the INPUT those
    items need -- never a licence to size.
  - **Design effect.** Multiple takes per station-day are handled
    CONSERVATIVELY: **one effective observation per station-day**, unless the
    hypothesis pre-registers a different, stated effective-sample rule in the
    ruling artefact.
  - **Power is a pinned design constant, not a per-hypothesis dial:**
    `POWER = 0.80` one-sided (the conventional value, declared once here and
    asserted in §6.2 — a hypothesis may not raise or lower it to pass).
  - **<a id="power-primary-only"></a>§6.1 POWER-PRIMARY-ONLY -- the SINGLE
    canonical statement of this rule. §7 step 8, §9, §11 and §12 CITE this
    anchor and must never restate or re-derive it; §6.2's `power_is_primary_only`
    field, §7 step 1's RED and D13 clause (i) ENFORCE it as binding artefacts.** **`POWER = 0.80` is the
    PRIMARY TEST's design power ONLY, and every MDE computed from it is an
    UPPER BOUND on `P(reach CONFIRMED)` -- stated here because the pooled-P&L
    veto above makes those two different quantities.**
    The `POWER` the formula consumes is
    `P(primary CI excludes zero | true effect = MDE)`. A `CONFIRMED`
    disposition requires that AND the mandatory veto
    (`pooled_net_pnl_per_contract > 0` strictly, plus the concentration
    screen), and because the `CONFIRMED` set is a STRICT SUBSET of the primary
    rejection region -- the same containment that makes the veto alpha-free --
    `P(CONFIRMED | true effect = MDE) <= 0.80`, STRICTLY lower whenever a
    true-positive draw can fail the veto (exactly the counterexample's shape).
    **The size of that shortfall is NOT bounded analytically by this design and
    NO number is asserted for it here:** it depends on the realized leg-count
    and entry-price heterogeneity ACROSS station-days, unknown before the data
    is opened. It is therefore handled MECHANICALLY, in the conservative
    direction:
    - **It is RECORDED, never inferred.** The power check that gates
      registration MUST report `power_is_primary_only = true` (§6.2's record
      field), and the §7 step 8 ruling MUST carry the same flag. A power
      statement without it is not a complete statement of what was checked.
    - **The REFUSAL direction is safe a fortiori.** Registration refuses on
      `MDE > mde_plausibility_bound` computed from the PRIMARY-only power, and
      composite power can never EXCEED primary power -- so a hypothesis judged
      underpowered on the primary test is underpowered on the composite too.
      The `UNDERPOWERED_NOT_REGISTERED` disposition can never be wrong in the
      permissive direction.
    - **The ADMITTING direction is LABELLED, never upgraded.** An "adequately
      powered" verdict is a PRIMARY-ONLY verdict wherever it is written -- the
      ruling, the record, and any downstream citation by AUD-02/A1 or AUD-10b
      -- and must never be restated as "an 80% chance that a real edge reaches
      `CONFIRMED`".
    - **Narrowing the gap is a FUTURE amendment, not an assumption made here.**
      It would need a simulation-based composite-power estimate under an
      explicit leg-count/entry-price model, with its own ruling (§12).
  - **The formula, one-sided z-test:**
    `MDE = (z_(1-per_variant_alpha) + z_POWER) * sqrt(1/4) / sqrt(n)`
    `    = (z_(1-per_variant_alpha) + z_POWER) / (2 * sqrt(n))`.
  - **The MDE is in MARKET terms — an edge per take NET of costs, never a raw
    hit rate.** It is the excess of the true per-take hold probability `q` over
    the break-even `BE` at a pre-registered reference ask `a`:
    `BE = a + theta * a * (1 - a) + slippage`, where `theta * C * p * (1 - p)`
    is the shipped venue fee arithmetic (`polymarket_us_fee`,
    `src/breezy/adapters/polymarket_us/fees.py:277`) and **`theta` is the
    CURRENT EVIDENCED coefficient `0.0695`**
    (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:7,47`).
    The config default `required_fee_coefficient = Decimal("0.06")`
    (`src/breezy/strategy/current_rung_hold/config.py:226`) is **STALE for this
    purpose and must not be used.** `slippage` is the allowance owned by
    **AUD-12** (cited by id; AUD-12 §6(a) records `slippage_prob` as an
    UNMEASURED hardcoded one-tick placeholder) — until AUD-12 lands, the ruling
    uses that documented placeholder, says so, and **this power check MUST be
    re-run and the ruling re-issued when AUD-12 publishes a measured value.**
  - **The plausibility bound is set in the §7 step 8 ruling BEFORE any data is
    opened**, and the ruling artefact records EVERY input alongside it: `n`,
    `per_variant_alpha`, `POWER`, the variance bound, `theta`, the slippage
    allowance and the reference ask. A bound stated without its inputs is not
    auditable and is refused.
  - **ENFORCEMENT — the code does not trust the caller's number.**
    `register_hypothesis` does NOT accept a caller-supplied MDE. It
    **RECOMPUTES** the MDE from the recorded inputs with the formula above and
    refuses on: (a) mismatch against the ruling's stated MDE beyond a pinned
    float tolerance; (b) any input outside its pinned source — `theta` other
    than the evidenced coefficient, or a variance bound other than `1/4` unless
    the record carries a stricter bound with a stated OUTCOME-FREE
    justification; (c) `MDE > mde_plausibility_bound`, which is the
    `UNDERPOWERED_NOT_REGISTERED` disposition (alpha `0.0`, no slot).
- Every variant is evaluated under exactly one design (§6.4 step 3):
  **`SINGLE_LOOK` at its `per_variant_alpha`. That is the ONLY look policy this
  item admits.** Group-sequential looks are **WITHDRAWN**, for an arithmetic
  reason stated plainly: the only boundary artefact this repo ships is pinned
  to `alpha = 0.025` at `i_max = 40`, and `load_boundary_artefact` hard-refuses
  every other pin (`src/breezy/persistence/gs_boundary_artefact.py:78,82,269-272`).
  Under ANY multi-hypothesis budget `per_variant_alpha = PROGRAMME_ALPHA /
  MAX_HYPOTHESES / k_variants` is bounded above by `0.05 / 4 = 0.0125` — 2x too
  small at the most generous allocation the programme can make, and smaller
  still for any `k_variants > 1`. `LD_OBF` could therefore never have been
  selected by any real registration; offering it would be dead text. Generating
  a new pinned artefact at a reachable alpha is excluded from this item (§5).
  **Recorded as a possible FUTURE amendment:** a hypothesis that genuinely
  needs repeated looks reopens this with its own ruling AND a newly generated,
  pinned boundary artefact at its own allocated alpha — neither of which exists
  today, so until both do, any `look_policy` other than `SINGLE_LOOK` is
  refused at registration.

**What IS controlled:** the family-wise error rate across the pre-declared
hypothesis budget — at most `MAX_HYPOTHESES x k_variants` pre-registered tests
whose nominal alphas sum by construction to at most `PROGRAMME_ALPHA`
(Bonferroni/union bound; no independence between classes assumed or needed).
**What is NOT controlled, said plainly:** anything beyond that cap. A
hypothesis conceived after the budget is exhausted is REFUSED, not squeezed in;
a post-hoc hypothesis suggested by looking at the data is refused outright — it
has no pre-allocated share and cannot acquire one. Widening the programme is a
NEW registration document with its own declared cap, exactly as
`PREREG_WP7_MULTIPLICITY_RULE §1.i` requires for a thirteenth variant.

**Holm is deliberately NOT used at programme level.** Holm–Bonferroni is a
step-down over *data-dependent p-values* ranked at ONE simultaneous
fixed-sample selection decision. This programme's intake is adaptive and
sequential over time, so no such simultaneous p-value set exists, and a fixed
design budget is not a p-value and cannot be substituted for one.
`PREREG_WP7_MULTIPLICITY_RULE §1.ii`'s Holm stays valid precisely where it
already lives — inside that one document, over its 12 variants, at its single
fixed-sample selection decision — and is neither generalised nor re-applied
here. The programme ledger's role is allocation, bookkeeping and gating.

### 6.2 `src/breezy/analysis/hypothesis_ledger.py` — pure core

Lives in the `breezy.analysis` layer **already created** by AUD-09 §6 (below
`app`, above `strategy`; forbidden from `nautilus_trader` direct import per the
same `allow_indirect_imports = true` contract AUD-09/AUD-10 add) — no new layer,
no new import-linter contract. Frozen dataclasses only, no I/O:

```python
HYPOTHESIS_LEDGER_SCHEMA_VERSION: Final[int] = 1

#: Programme-level, fixed BEFORE any intake (§6.1); never re-derived from data.
PROGRAMME_ALPHA: Final[float] = 0.05        # one-sided, the whole programme's budget
MAX_HYPOTHESES: Final[int] = 4              # = SS6.3's three open classes + one reserve slot
MAX_VARIANTS_PER_HYPOTHESIS: Final[int] = 4 # fewer, sharper hypotheses (SS6.1)
#: Floor on any real allocation: 0.05 / 4 / 4. Asserted, never re-derived.
MIN_PER_VARIANT_ALPHA: Final[float] = 0.003125

#: SS6.1 POWER CHECK -- pinned design constants, identical for every hypothesis.
POWER: Final[float] = 0.80                  # declared once; never a per-hypothesis dial.
                                            # PRIMARY-test design power ONLY: because
                                            # CONFIRMED also requires the SS6.1 pooled-P&L
                                            # veto, every MDE below is an UPPER bound on
                                            # P(reach CONFIRMED). The gap is not bounded
                                            # analytically and no number is asserted for it.
VARIANCE_BOUND: Final[float] = 0.25         # Popoviciu on the SS6.1 MEAN statistic: each
                                            # (W_i - BE_i) spans width 1, so their mean does
                                            # too, so Var <= 1/4 for ANY side mix, ANY leg
                                            # count, ANY dependence (gs_boundary_artefact.py
                                            # :75-78; PREREG_v2:55-60)
#: The ONE admitted station-day observation, for the power check AND the
#: confirmatory test (SS6.1). The station-day SUM is NOT admitted here: its
#: opposite-side covariance term (current_rung_hold_v2.py:342-344) can reach
#: variance 1.0 inside the Sum-q <= 1 admission gate.
STATION_DAY_STATISTIC: Final[str] = "MEAN_EXCESS_PER_TAKE"
PINNED_ORDER_QUANTITY: Final[int] = 1       # SS6.1: registration constraint, not a dial
                                            # (PREREG_WP7 SS2.2:110-113; config.py:253-255)
EVIDENCED_FEE_THETA: Final[float] = 0.0695  # FEE_SCHEDULE_PIN_2026-09-18.md:7,47 -- NOT
                                            # config.py:226's stale 0.06
#: SS6.1 ZERO-TAKE RULE. A station-day with no realized take carries no X_d (a mean
#: over no takes is undefined) and is dropped at SS6.4 step 4's draw-set construction,
#: BEFORE any statistic -- combine_station_day itself refuses an empty day
#: (current_rung_hold_v2.py:318-319). Both counts are reported on every look row.
#: Every "n"/"min_station_days"/"n_station_days" here means WITH-TAKES station-days.
ZERO_TAKE_STATION_DAYS_EXCLUDED: Final[bool] = True
#: SS6.1 POOLED-P&L VETO. Alpha-free and VETO-ONLY: it can only shrink the rejection
#: region, never enlarge it, so it is not a second test and consumes no allocation.
#: CONFIRMED requires pooled_net_pnl_per_contract > 0 STRICTLY, computed from
#: combine_station_day's OWN SUM (CombinedDraw.x, current_rung_hold_v2.py:337-340),
#: net of theta = 0.0695 and AUD-12's slippage through each leg's BE_i (:76-84).
POOLED_PNL_VETO_REQUIRED: Final[bool] = True
#: SS6.1 concentration cap: the largest share of a variant's TOTAL legs any ONE
#: station-day may contribute. Pinned once, never a per-hypothesis dial. A
#: PRE-REGISTERED PRAGMATIC GUARDRAIL, not a derived bound -- a leg-COUNT share does
#: NOT bound a P&L-DOLLAR share. The money-losing-CONFIRM gap is closed by the strict
#: pooled_net_pnl_per_contract > 0 condition; this is an extra robustness screen.
MAX_SINGLE_DAY_LEG_SHARE: Final[float] = 0.20

@dataclass(frozen=True, slots=True, kw_only=True)
class HypothesisRecord:
    schema_version: int
    hypothesis_id: str            # e.g. "H-NO-SIDE-REST-2026-09-XX"
    hypothesis_class: str         # closed enum, §6.3
    registered_at: str            # ISO date, pre-registration commit date
    k_variants: int               # declared cap, bounded at registration
    allocated_alpha: float        # PROGRAMME_ALPHA / MAX_HYPOTHESES, assigned at registration
    per_variant_alpha: float      # allocated_alpha / k_variants -- the ONLY alpha a look may spend
    min_station_days: int         # per-variant minimum n before a look -- station-days
                                  # WITH >= 1 take (SS6.1 zero-take rule); a fills = 0
                                  # day NEVER counts toward it
    max_single_day_leg_share_cap: float
                                  # SS6.1 concentration cap, pre-registered by the SS7 step
                                  # 8 ruling; must equal MAX_SINGLE_DAY_LEG_SHARE
    mde_at_allocated_alpha: float # the SS7 step 8 ruling's stated MDE; RECOMPUTED and
                                  # cross-checked at registration, never trusted (SS6.1)
    mde_plausibility_bound: float # that ruling's stated bound; MDE above it => refused
    power_is_primary_only: bool   # ALWAYS True: POWER and mde_at_allocated_alpha describe
                                  # the PRIMARY test only, so the MDE is an UPPER bound on
                                  # P(reach CONFIRMED) under SS6.1's pooled-P&L veto; the
                                  # SS7 step 8 ruling carries the same flag, and a record
                                  # asserting False is REFUSED at registration (SS6.1)
    #: Every MDE input, recorded so the recomputation is reproducible and auditable
    #: (SS6.1). Any input off its pinned source is a refusal, not a warning.
    mde_reference_ask: float      # the pre-registered ask the break-even is taken at
    mde_fee_theta: float          # must equal EVIDENCED_FEE_THETA
    mde_slippage_allowance: float # AUD-12's allowance (its placeholder until AUD-12 lands)
    mde_variance_bound: float     # must equal VARIANCE_BOUND unless a stricter, stated,
                                  # OUTCOME-FREE justification is recorded
    station_day_statistic: Literal["MEAN_EXCESS_PER_TAKE"]
                                  # the SS6.1 station-day observation; must equal
                                  # STATION_DAY_STATISTIC -- any other value (notably a
                                  # station-day SUM) is refused at registration, because
                                  # VARIANCE_BOUND is derived for the MEAN only
    order_quantity: int           # the design's declared per-leg quantity; must equal
                                  # PINNED_ORDER_QUANTITY -- the qty^2 term in
                                  # combine_station_day:341 is what VARIANCE_BOUND assumes away
    look_policy: Literal["SINGLE_LOOK"]   # the ONLY admitted design, SS6.1/SS6.4 step 3
    freeze_commit: str            # git sha; corpus before this sha is SEARCH, after is CONFIRM
    status: Literal[
        "REGISTERED", "PARKED_INSUFFICIENT_DATA", "EVALUATING",
        "CONFIRMED", "REJECTED", "ABANDONED_CAP_EXHAUSTED",
        "UNDERPOWERED_NOT_REGISTERED",   # zero-look record: no slot, no alpha (SS6.1)
        "PRIMARY_PASSED_PNL_VETO",       # SS6.1 veto: the primary test passed but pooled
                                         # net P&L did not (or one day carried the legs) --
                                         # TERMINAL, alpha CONSUMED, never handed to H5/H6
    ]

@dataclass(frozen=True, slots=True, kw_only=True)
class HypothesisLook:
    hypothesis_id: str
    variant_id: str                # one of the K_variants
    looked_at: str
    n_station_days: int            # WITH-TAKES station-days -- the confirmatory n (SS6.1)
    n_station_days_observed: int   # every admissible replay row, fills = 0 INCLUDED (SS6.1)
    n_station_days_with_takes: int # those surviving the zero-take filter; == n_station_days
    take_rate: float               # with_takes / observed -- reported ALONGSIDE the estimate,
                                   # because conditioning on a take says nothing about how
                                   # OFTEN the strategy trades (SS6.1 selection caveat)
    ci_lower: float
    ci_upper: float
    pooled_net_pnl_per_contract: float  # SS6.1 VETO: Sum_d CombinedDraw.x over the SAME
                                        # sample; must be > 0 STRICTLY for CONFIRMED
    max_single_day_leg_share: float     # realized concentration; above the record's cap is
                                        # the same terminal veto state
    veto_reason: Literal["NONE", "POOLED_PNL_NON_POSITIVE", "LEG_SHARE_ABOVE_CAP"]
    alpha_spent_cumulative: float  # this variant's single-look alpha; never exceeds
                                   # per_variant_alpha
    is_terminal_look: bool         # after a terminal look the variant is permanently ineligible

def programme_budget_remaining(records: Sequence[HypothesisRecord]) -> int: ...
    # MAX_HYPOTHESES minus the LOOK-TAKING records (zero-look records -- the REJECTED
    # disposition row and UNDERPOWERED_NOT_REGISTERED -- are excluded); 0 => REFUSED
def alpha_remaining(record: HypothesisRecord, looks: Sequence[HypothesisLook]) -> float: ...
    # per_variant_alpha minus THIS variant's own spend -- no cross-variant pooling
def register_hypothesis(...) -> HypothesisRecord: ...  # validates
                                                       # 1 <= k_variants <= MAX_VARIANTS_PER_HYPOTHESIS
                                                       # (zero-look records exempt); REFUSES when the
                                                       # programme budget is exhausted; ASSIGNS
                                                       # allocated_alpha/per_variant_alpha (never
                                                       # caller-supplied); refuses any look_policy
                                                       # other than "SINGLE_LOOK"; refuses -- as
                                                       # UNDERPOWERED_NOT_REGISTERED, consuming no
                                                       # slot and no alpha -- any hypothesis whose
                                                       # RECOMPUTED MDE exceeds its
                                                       # mde_plausibility_bound (SS6.1 power check);
                                                       # REFUSES, naming NON_UNIT_ORDER_QUANTITY, any
                                                       # record whose order_quantity != 1 (SS6.1);
                                                       # REFUSES, naming
                                                       # NON_MEAN_STATION_DAY_STATISTIC, any record
                                                       # whose station_day_statistic !=
                                                       # STATION_DAY_STATISTIC (SS6.1); REFUSES,
                                                       # naming NON_PINNED_LEG_SHARE_CAP, any
                                                       # record whose max_single_day_leg_share_cap
                                                       # != MAX_SINGLE_DAY_LEG_SHARE (SS6.1)
def recompute_mde(*, per_variant_alpha: float, n_station_days: int) -> float: ...
    # SS6.1's pinned formula, the ONLY admitted derivation:
    #   (z(1 - per_variant_alpha) + z(POWER)) * sqrt(VARIANCE_BOUND) / sqrt(n_station_days)
    # VARIANCE_BOUND is admissible here ONLY because the station-day observation is
    # STATION_DAY_STATISTIC (the SS6.1 MEAN): Popoviciu bounds it at 1/4 for any side
    # mix, leg count or dependence. The formula and both worked numbers are UNCHANGED
    # by the round-7 statistic pin -- the bound it consumes is still exactly 1/4.
    # Outcome-free by construction: it reads no StratumRow and no realized draw.
def is_variant_eligible(record: HypothesisRecord, looks: Sequence[HypothesisLook],
                        variant_id: str) -> bool: ...  # False once an "already-looked" row exists,
                                                       # and always False for a zero-look record
def pooled_net_pnl_per_contract(draws: Sequence[CombinedDraw]) -> float: ...
    # SS6.1's VETO gate: the SUM of combine_station_day's OWN `x` term
    # (current_rung_hold_v2.py:337-340) over the SAME with-takes station-day draws the
    # primary test consumed -- the existing SUM reused, never a new estimator. Alpha-free
    # because it is veto-only: it can only shrink the CONFIRMED set, never enlarge it.
```

Both dataclasses carry `schema_version` and are written/read through the
**same versioned-JSONL discipline** AUD-09's H0/H1/H3 hand-offs use: an
unknown version is a hard refusal (`UnknownHypothesisLedgerSchemaError`),
never a silent fallback, and a duplicate `hypothesis_id` on `REGISTERED` is a
hard error — the identical contract shape AUD-09 §6b.4 already establishes for
this exact class of problem, reused rather than re-invented.

### 6.3 Hypothesis classes — what is CLOSED, what is triaged, and on what evidence

This is the first artefact in the repo that states, in one place, the
disposition of every named PM.us hypothesis class against **today's** data
sufficiency, rather than leaving that judgement scattered across memories.

| Class | Disposition | Evidence | Action here |
|---|---|---|---|
| **Forecast taker** (rung-level, any window/side/screen variant already covered by `PREREG_WP7_MULTIPLICITY_RULE`'s 12) | **CLOSED, TERMINAL** | `RULING_forecast_edge_programme_closes_2026-09-20.md`: market resolution 1.98x the forecast's, CI95 `[-0.03229,-0.00373]` | Registered here as `status=REJECTED`, cap exhausted, so a future registration attempt under this class is a hard refusal, not a silent no-op — see §7 step 7 |
| **`pm_us_crh_v4` archive-table recalibration** (fix the train/serve skew so the family can price at all) | **BLOCKED on data, not closed** | `DECISION_FUNNEL_2026-09-20.md`: "the family is currently UNSALVAGEABLE, not merely miscalibrated" **absent real historical venue ladders, which do not exist**; the corpus is 2021-2025 CLI-derived, the live decision path needs interval-aware venue-priced ladders that only exist from tape start (2026-08-30) forward | Registered `PARKED_INSUFFICIENT_DATA`; re-triaged automatically (§6.4) as AUD-09a's census accumulates SUFFICIENT station-days; **not** evaluated until `min_station_days` is met per-cluster (station × season × hour × width × m — the corpus's own strata) |
| **Maker/resting-bid redesign** (`pm_us_crh_rest_v5` folded `CLOSED_NOT_REGISTERED` as originally drafted) | **CLOSED as drafted; a genuinely different redesign is a NEW registration** | `POST_FORECAST_PHASE §0.2`: "resting −2.550 vs IOC −2.09... loses more than the baseline it must beat" | A future redesign is a fresh `hypothesis_id` with its own `K_variants`; this item does not propose one, per §5's exclusion |
| **NO-side hunting** | **BLOCKED on capture, not closed** — standing requirement (memory `no-side-hunting-is-a-requirement`) | `POST_FORECAST_PHASE §0.3`/work packages C0-C2: NO leg has **never been priced** (zero `^no` dirs in `order_book_depths`/`quote_tick`/`trade_tick`); C1/C2's own n≥30 gate, owned by AUD-02, is upstream of this item | Registered `PARKED_INSUFFICIENT_DATA`; triage (§6.4) reads C1/C2's own capture progress once it exists — this item adds no new capture path, per §5 |
| **Hours 10-11 repricing window (HUNT-1/WIN-1)** | **BLOCKED, structurally, not closed** | `DECISION_FUNNEL_2026-09-20.md`: 100% of decisions die upstream of pricing (`observation_ambiguous` then `illegal_cell`); HUNT-1 is "moot" until Gate 1/Gate 2 are fixed — and the funnel's own follow-on measurement REJECTED all three candidate fixes to Gate 1 ("no live sub-degree high-cadence observation source has been found to exist") | Registered `PARKED_INSUFFICIENT_DATA` with reason `OBSERVATION_GATE_UNRESOLVED`; owned upstream by AUD-01/the Gate-1 design track, cited by id, never re-decided here |
| **Kalshi surface** (24 cities, 5-min cadence) | **Out of programme scope** | memory `polymarket-us-first-kalshi-secondary`, `kalshi-lists-24-cities-all-5min` | Not registered; named for completeness only, per §5's exclusion |

**Reading this table honestly:** four of six classes are BLOCKED on data or on
an upstream structural gate, not on lack of ideas — which is exactly the
"backtest ROI unobtainable here" condition the operator flagged. The
programme's job is not to force a result out of an insufficient sample; it is
to make the insufficiency VISIBLE, dated, and automatically re-checked as
capture accumulates, and to escalate honestly once the declared horizon (§6.6)
is reached without a survivor.

### 6.4 `scripts/analysis/hypothesis_triage.py` — I/O wrapper, reused inputs only

Run from **AUD-18's own** wrapper/unit (§6.4b), ordered strictly after the
AUD-09 run and consuming its artefacts **read-only** — never as a fourth
invocation inside AUD-09a's wrapper, whose named script set is closed (§5).
It:

1. Reads `hypothesis_ledger.jsonl` (this item's own artefact).
2. Reads `replay_sufficiency.jsonl` (AUD-09a, H0) and `replay_results.jsonl`
   (AUD-09b, H3) — **read-only, no new fields requested of either artefact**.
3. For each `REGISTERED`/`PARKED_INSUFFICIENT_DATA`/`EVALUATING` hypothesis,
   recomputes whether `min_station_days` is now met **per stratum**, using
   the census's own `(station, climate_day)` sufficiency verdicts joined to
   `replay_results.jsonl`'s completed rows -- **counting only completed rows
   carrying `fills >= 1`**, per SS6.1's zero-take rule, so a run of `fills = 0`
   `COMPLETED` days never advances a hypothesis toward its look. **This recomputation is a
   scheduling decision only — it never scores anything.** Nightly
   re-evaluation of an `EVALUATING` hypothesis as its n grows would be
   uncorrected repeated significance testing, and no fixed alpha allocation
   (§6.1) can license it. The valid design is fixed at registration and there
   is exactly ONE (`look_policy` is a required `HypothesisRecord` field, §6.2,
   whose only admitted value is `SINGLE_LOOK`):

   - **`SINGLE_LOOK`.** A variant is evaluated **exactly once, ever**, at its
     pre-registered `min_station_days`. The invariant is mechanical, not
     procedural: the presence of ANY `HypothesisLook` row for
     `(hypothesis_id, variant_id)` in `hypothesis_evaluations.jsonl` — the
     "already-looked" ledger entry — makes that variant permanently
     ineligible; a later run skips it and records
     `skip_reason="ALREADY_LOOKED"`. Growing n after the look changes
     nothing.

   Group-sequential (`LD_OBF`) monitoring is WITHDRAWN from this item for the
   arithmetic reason §6.1 states: no allocation under a multi-hypothesis budget
   can reach the shipped artefact's pinned `alpha = 0.025`
   (`gs_boundary_artefact.py:78,82,269-272`), and generating a new pinned
   artefact is excluded (§5). It is recorded as a FUTURE amendment, not a
   selectable design; the triage therefore never loads a boundary artefact at
   all, and any other `look_policy` is refused upstream at registration.

   **Composition with the programme allocation (§6.1).** The two levels never
   double-count because the allocation is fixed a priori and the single look
   spends only inside it: `per_variant_alpha` is assigned at registration by
   the Bonferroni split, and a variant's ENTIRE spend — its one single-look
   alpha — is bounded by that one number. No step-down, no re-ranking, no
   recycling of a rejected variant's share; the union bound over all
   pre-registered variants is `PROGRAMME_ALPHA` whatever order intake happens
   in.
4. On reaching a pre-declared look for a hypothesis whose replay rows all
   carry `validity != "MECHANISM_ONLY"` and `params_match == true` (the
   **same** gate as AUD-10's `C-VALIDITY` — reused, not reimplemented), calls
   `load_realized_draws` (`src/breezy/persistence/realized_draws.py:249` —
   **not** `current_rung_hold_v2.py`, whose line 249 is unrelated) together
   with `combine_station_day`/`score_combined`
   (`src/breezy/settlement/current_rung_hold_v2.py:298,348`) over the
   admissible station-day draws for that hypothesis's variant — reusing their
   per-leg `held_i - BE_i` terms and their admission/fold/opposite-side
   refusals, but aggregating ACROSS legs as §6.1's pinned
   `MEAN_EXCESS_PER_TAKE`, never the station-day SUM, so the confirmatory test
   is on the SAME observation the power check was computed for (any ROI
   accounting this path also reports keeps the SUM, §6.1) — computes a
   station-day-clustered bootstrap CI (the same method
   `DECISION_FUNNEL_2026-09-20.md`'s "Clustering resolved" section already
   uses, B=400, whole station-days resampled — cited, not reinvented), and
   applies the variant's registered `look_policy` boundary from step 3.

   **Draw-set construction here IS the named zero-take filter stage (SS6.1).**
   Before the first `combine_station_day` call, every replay row with
   `fills == 0` -- legitimately `COMPLETED` under AUD-09 SS6b.3's schema
   (`AUD-09-scheduled-per-station-replay.md:697-702`) -- is dropped, so that
   primitive's empty-day `ValueError`
   (`src/breezy/settlement/current_rung_hold_v2.py:318-319`) is unreachable on
   this path; the step records `n_station_days_observed`,
   `n_station_days_with_takes` and their ratio for the look row, and the
   confirmatory `n` is the WITH-TAKES count.

   **The step ALSO computes SS6.1's veto inputs on the SAME draw set, in the
   same pass:** `pooled_net_pnl_per_contract` (the SUM of each admitted draw's
   own `CombinedDraw.x`, `current_rung_hold_v2.py:337-340`) and
   `max_single_day_leg_share` (the largest share of the variant's total legs
   from any one station-day). Both are recorded on the look row whatever the
   primary result; they GATE only step 6's disposition, and they spend no
   alpha.
5. Appends one `HypothesisLook` row to `hypothesis_evaluations.jsonl`
   (append-only, duplicate `(hypothesis_id, variant_id, looked_at)` is a hard
   error, mirroring H0/H3's own idempotency-key rule).
6. Updates `status` on the ledger: CI excludes zero on the confirmatory look
   **AND** SS6.1's pooled-P&L veto passes (`pooled_net_pnl_per_contract > 0`
   STRICTLY and `max_single_day_leg_share` within the record's pre-registered
   `max_single_day_leg_share_cap`) → `CONFIRMED`; CI excludes zero but either
   veto condition fails → `PRIMARY_PASSED_PNL_VETO`, terminal, with
   `veto_reason` naming which condition fired, the variant's alpha CONSUMED
   (the look was taken) and NO H5/H6 hand-off — a veto never promotes and never
   rescues; CI does not, and the variant's own alpha is exhausted →
   that variant is REJECTED, never re-looked; all `K_variants` for a
   hypothesis exhausted with no `CONFIRMED` variant → `ABANDONED_CAP_EXHAUSTED`
   and **one alert** via the shipped `resolve_alert_sink`/`emit_alert` path
   (`runtime/health.py:579,668`), naming the hypothesis id and the disposition
   — reusing WP-B0's already-delivered egress, exactly as AUD-09b's stall
   escalation (§6b.3) does, no new transport.
7. Insufficient data (§6.3's BLOCKED rows) is never silently retried forever:
   a hypothesis PARKED for longer than a declared horizon (default: the same
   `21 days` abandonment window `POST_FORECAST_PHASE`'s C1 already uses for an
   analogous "n accrues too slowly" case) emits one advisory alert naming the
   stall, without changing status — data insufficiency is not a failed test,
   and must not be scored as one.

### 6.4b Scheduling — AUD-18's own unit, ordered after AUD-09, never inside its wrapper

Because AUD-09 **B18**/AUD-10 **C19** close `deploy/systemd/replay-daily-run.sh`
to a named set of three and fail an unnamed fourth (§5), AUD-18 ships the
smallest possible scheduling surface of its own, in the shape every existing
nightly analysis unit already uses (`deploy/systemd/breezy-offer-gate-daily.{service,timer}`
+ `offer-gate-daily-run.sh` is the pattern copied):

- **`deploy/systemd/breezy-hypothesis-triage.service`** — `Type=oneshot`,
  `WorkingDirectory=/home/jon/breezy`, `Slice=breezy-studies.slice`,
  `UMask=0077`, no `[Install]`, no `EnvironmentFile` (this process holds no
  venue credential, opens no socket, and reads only local JSONL).
  **`After=breezy-replay-daily.service`** so it can never precede the AUD-09
  run it consumes. `StandardOutput=journal`/`StandardError=journal`,
  `SyslogIdentifier=breezy-hypothesis-triage`, `TimeoutStartSec=600`.
- **Memory caps, stated as values here because they are engineering
  parameters, not operator caps:** `MemoryHigh=1G` / `MemoryMax=2G` — an
  order of magnitude below the 12G/16G the tape studies declare, because this
  job's inputs are two JSONL files and a bounded draw set, and deliberately
  far below the host so a runaway is OOM-killed in its OWN cgroup (the
  2026-09-11 K1 incident's standing rule, memory `unit-memory-cap-is-containment`).
  Asserted by `tests/unit/test_analysis_units_memory_capped.py`.
- **`deploy/systemd/hypothesis-triage-run.sh`** — the repo's existing wrapper
  discipline verbatim: `set -uo pipefail`; `say()` logging; then
  `LOCK="$LOCK_DIR/breezy-studies.lock"`, `exec 9>>"$LOCK"`,
  **`flock -n 9 || { say "SKIPPED -- another study holds the studies lock"; exit 0; }`**
  — the SAME host-wide lock and the same skip-not-kill semantics
  `offer-gate-daily-run.sh:61,68-70` and AUD-09's own wrapper use, so the
  one-heavy-job-at-a-time discipline holds across items and `After=` ordering
  is belt-and-braces on top of it, never a substitute. Exactly one `"$PY"`
  invocation: `scripts/analysis/hypothesis_triage.py`. No JSONL parsing in
  shell. Asserted by `tests/unit/test_analysis_units_serialized.py`.
- **`deploy/systemd/breezy-hypothesis-triage.timer`** — `Persistent=true`,
  `AccuracySec=1min`, **`OnCalendar=*-*-* 01:20:00 UTC`** — a concrete value,
  chosen against the enumerated tick list (`breezy-k1-daily` 01:35,
  `breezy-offer-gate-daily` 02:05, `breezy-quote-tape-rotate` 09:00,
  `breezy-mb-daily` 13:30, `breezy-score-live-trials` 14:15,
  `breezy-live-tally` 14:30, `breezy-position-monitor-report` 15:00,
  `breezy-exit-window-study` 15:20, AUD-09's decided `breezy-replay-daily`
  15:50, `breezy-family-tally@` 17:20, `breezy-quote-tape-ingest`
  00,06,12,18:15, plus the `*:0/15` ingest stepper): `01:20` collides with no
  existing `HH:MM` tick (`tests/unit/test_deploy_timer_hours.py` forbids a
  duplicate), is the first free minute AFTER the protected LST-union no-start
  window `[16:35Z, 01:15Z)` closes (`deploy/systemd/README.md`), and sits 15
  min clear of the next unit at 01:35. It reads the PRECEDING 15:50 replay
  run's artefacts, complete hours earlier — the maximum headroom available on
  the shared `breezy-studies.lock`, so this cheap job is the least likely of
  any admissible slot to skip behind a long study. `After=` ordering remains
  belt-and-braces on top of the lock, never a substitute.
- **Failure alerting.** A non-zero exit, an unreadable/absent AUD-09 artefact,
  or an unknown schema version emits exactly one `CRITICAL` alert through the
  **shipped** sink — `resolve_alert_sink`/`emit_alert`
  (`src/breezy/runtime/health.py:579,668`), WP-B0's already-delivered egress —
  before exiting non-zero. A detector without delivery is not a control
  (memory `readiness-audit-2026-09-12`): a silent triage failure must not be
  able to stall the programme unobserved.

### 6.5 Hand-offs

**H4 — AUD-09a/b → AUD-18 (real, read-only).** `replay_sufficiency.jsonl` and
`replay_results.jsonl`, exactly as specified in AUD-09 §6b.4/H0 — no new
fields, no schema change requested of AUD-09.

**H5 — AUD-18 → AUD-02 (A1's evidence pack).** For the `pm_us_crh_v4`
archive-table-recalibration class specifically: the moment (if ever) that
class reaches `CONFIRMED`, this item's `hypothesis_evaluations.jsonl` row plus
a dated, signed evidence doc under `docs/evidence/` (same convention as every
other evidence artefact this backlog cites) **is** the "genuinely independent
edge estimate" AUD-02 §6.2's widened A1 precondition requires. Until then, A1
proceeds on AUD-02's own stated expectation — "very likely (ii)."

**H6 — AUD-18 → AUD-10b (candidate-family evidence, non-champion only).** A
`CONFIRMED` hypothesis outside the current champion's own lineage is exactly
the input `C-ESTIMATOR`/`C-N` need to evaluate a **new** family's promotion
criteria (AUD-10 §6b.3) — read-only, no change requested of AUD-10's own
schema.

### 6.6 Programme-level KILL criterion

Mirroring `PREREG_WP7_MULTIPLICITY_RULE §1.iii` raised to programme scope: if,
after **all currently BLOCKED classes in §6.3 have had a full opportunity to
clear their data-sufficiency bar** (measured, not assumed — re-triaged nightly
per §6.4) **and** the archive-table-recalibration class specifically reaches
`ABANDONED_CAP_EXHAUSTED` or stays `PARKED_INSUFFICIENT_DATA` past the horizon
fixed by the pre-registration PEER RULING (§7 step 8 — an in-plan engineering
step, not an external blocker), the honest programme conclusion —
stated plainly, exactly as `POST_FORECAST_PHASE §2` already states it for the
flagship family — is **"nothing arms," and PM.us daily-high rungs close as a
programme.** This is the acceptance test's non-trading branch (§8); it is not
a failure of this plan, it is the plan doing its job.

## 7. Ordered implementation or verification steps

1. **RED** `tests/unit/test_hypothesis_ledger.py`: `register_hypothesis`
   refuses `k_variants < 1` and a duplicate `hypothesis_id`; an unknown
   `schema_version` refuses with path/line/version named. **Allocation REDs
   (§6.1):** (i) the ASSIGNED `allocated_alpha` is exactly
   `PROGRAMME_ALPHA / MAX_HYPOTHESES` and `per_variant_alpha` exactly
   `allocated_alpha / k_variants`, a caller-supplied alpha is refused, and the
   summed nominal alpha over every registered variant NEVER exceeds
   `PROGRAMME_ALPHA` for any admissible registration sequence; (ii) a
   programme whose budget is exhausted (`MAX_HYPOTHESES` records) REFUSES the
   next registration rather than re-allocating or shrinking an existing share,
   and a REJECTED hypothesis's share is NOT returned to the pool; (iii) ANY
   `look_policy` other than `"SINGLE_LOOK"` is REFUSED at registration, naming
   the refused value and §6.1's withdrawal reason; (iv) `alpha_remaining`
   equals `per_variant_alpha` minus that variant's own spend over a fixture set
   of `HypothesisLook` rows, with no cross-variant pooling; (v) `k_variants >
   MAX_VARIANTS_PER_HYPOTHESIS` is REFUSED for a look-taking registration, the
   assigned `per_variant_alpha` is never below `MIN_PER_VARIANT_ALPHA` for any
   admissible registration, and `MAX_HYPOTHESES` equals §6.3's open-class count
   plus one reserve; **(vi) the POWER CHECK (§6.1):** a registration whose
   `mde_at_allocated_alpha` exceeds its `mde_plausibility_bound` is refused and
   written as `UNDERPOWERED_NOT_REGISTERED`, that record consumes NO alpha
   (`allocated_alpha == 0.0`) and NO slot (`programme_budget_remaining` is
   unchanged by it), it can never carry a `HypothesisLook` row, and the same
   holds for the §7 step 7 `REJECTED` disposition record (which is also exempt
   from the `k_variants` ceiling at its `k_variants=12`). **The MDE COMPUTATION
   itself is pinned, not just the refusal branch:** (vi-a) `recompute_mde`
   reproduces §6.1's formula on two worked numeric examples — at
   `per_variant_alpha = 0.003125` (`z = 2.7344`), `POWER = 0.80`
   (`z = 0.8416`) and `VARIANCE_BOUND = 0.25`, `n = 300` gives
   `(2.7344 + 0.8416) / (2 * sqrt(300)) = 3.5760 / 34.6410 = 0.1032` and
   `n = 600` gives `3.5760 / 48.9898 = 0.0730`, each asserted to 4 dp, **and
   the same test asserts the record carries `power_is_primary_only == True`** --
   both figures are the PRIMARY test's design power only and are an UPPER bound
   on `P(reach CONFIRMED)` under §6.1's veto -- while a registration whose
   record carries `power_is_primary_only == False` is REFUSED;
   (vi-b) a registration whose caller-stated `mde_at_allocated_alpha` disagrees
   with the recomputed value beyond the pinned tolerance is REFUSED, naming both
   numbers — a caller-supplied MDE is never accepted on trust; (vi-c) a record
   carrying `mde_fee_theta = 0.06` (config.py:226's STALE default) is REFUSED
   naming `EVIDENCED_FEE_THETA = 0.0695` and the pin document; (vi-d) a record
   carrying `mde_variance_bound != 0.25` with no recorded outcome-free
   justification is REFUSED; (vi-e) the break-even helper reproduces
   `BE = a + theta * a * (1 - a) + slippage` on a worked example —
   `a = 0.30`, `theta = 0.0695`, slippage `0.01` gives
   `0.30 + 0.014595 + 0.01 = 0.324595`; **(vi-f)** a registration declaring
   `order_quantity = 2` is REFUSED naming `NON_UNIT_ORDER_QUANTITY` and
   `PINNED_ORDER_QUANTITY = 1`, while the otherwise-identical record at
   `order_quantity = 1` registers -- the constraint the `1/4` variance bound
   rests on (§6.1) is enforced, not assumed; **(vi-g)** a WORKED MIXED-SIDE
   FIXTURE -- one station-day carrying a YES leg and a NO leg on DIFFERENT
   rungs with `q = [0.5, 0.5]` at `qty = 1`, which the `Sum_i q_i > 1`
   admission gate ADMITS -- asserts BOTH directions: `combine_station_day`'s
   SUM variance is `1.0`, strictly GREATER than `VARIANCE_BOUND = 0.25`,
   while the pinned `MEAN_EXCESS_PER_TAKE` statistic over the same fixture
   has variance `<= 0.25`, and a registration declaring
   `station_day_statistic` as anything other than `"MEAN_EXCESS_PER_TAKE"` is
   REFUSED naming `NON_MEAN_STATION_DAY_STATISTIC`; **(vi-h)** a MANY-LEGS
   FIXTURE -- a station-day of `m_d >= 4` legs of mixed sides and distinct
   rungs -- asserts the MEAN statistic's value lies in an interval of width
   `1` and its variance stays `<= 0.25` as legs are added, while the SUM's
   does not, pinning that the bound is leg-count-free and dependence-free
   (§6.1's Popoviciu derivation); **(vi-i)** the ZERO-TAKE rule (§6.1): a
   `replay_results.jsonl` row with `outcome = "COMPLETED"` and `fills = 0` --
   legitimate under AUD-09 **§6b.3**'s own schema
   (`AUD-09-scheduled-per-station-replay.md:697-702`) -- is dropped at draw-set
   construction so it NEVER reaches `combine_station_day` and the run never
   raises that primitive's empty-day `ValueError`
   (`src/breezy/settlement/current_rung_hold_v2.py:318-319`), while the look row
   reports `n_station_days_observed` INCLUDING it, `n_station_days_with_takes`
   EXCLUDING it and their ratio as `take_rate`; on a fixture of 40 observed
   station-days of which 12 carry takes the look's `n_station_days` is **12,
   never 40**, and a `min_station_days = 20` hypothesis therefore does NOT look;
   **(vi-j)** the POOLED-P&L VETO (§6.1), pinned in BOTH directions on the
   round-7 counterexample -- a fixture of nine one-leg station-days winning at
   `entry_ask = 0.02` and one 100-leg station-day losing at `entry_ask = 0.98`
   yields a primary CI that EXCLUDES zero while
   `pooled_net_pnl_per_contract < 0`, and the recorded disposition is
   `PRIMARY_PASSED_PNL_VETO` with `veto_reason = "POOLED_PNL_NON_POSITIVE"`,
   **not** `CONFIRMED`, with the variant's alpha CONSUMED and no H5/H6 pack
   emitted; a FAILED primary whose pooled number is POSITIVE stays `REJECTED`
   (the gate only vetoes, never promotes); a registration whose
   `max_single_day_leg_share_cap != MAX_SINGLE_DAY_LEG_SHARE` is REFUSED naming
   `NON_PINNED_LEG_SHARE_CAP`; and a look whose realized
   `max_single_day_leg_share` exceeds that cap reaches the same terminal state
   with `veto_reason = "LEG_SHARE_ABOVE_CAP"`.
2. **GREEN** `src/breezy/analysis/hypothesis_ledger.py` — no new layer/import-
   linter contract; `lint-imports`/`mypy src/breezy` stay green at this step.
3. **RED** `tests/unit/test_hypothesis_triage.py`, subprocess-fake driven:
   a hypothesis under `min_station_days` stays `PARKED_INSUFFICIENT_DATA` and
   no draw is scored; one whose replay rows are all `MECHANISM_ONLY` is never
   evaluated even with sufficient n (the AUD-10 `C-VALIDITY` mirror); a
   hypothesis crossing its look boundary with `validity != MECHANISM_ONLY` and
   `params_match == true` produces exactly one `HypothesisLook` row with a
   CI computed via `combine_station_day`/`score_combined`, aggregated across
   legs as §6.1's `MEAN_EXCESS_PER_TAKE` (a mixed-side fixture asserts the
   look uses the MEAN, not the SUM), on a fixture matching a hand-computed
   value; a `K_variants`-exhausted hypothesis with no
   `CONFIRMED` variant transitions to `ABANDONED_CAP_EXHAUSTED` and emits
   exactly one alert to a recording fake sink; a PARKED hypothesis past its
   horizon emits exactly one advisory alert without changing status; a
   duplicate `(hypothesis_id, variant_id, looked_at)` append is a hard error.
   **No-re-look REDs (§6.4 step 3):** a `SINGLE_LOOK` variant that already
   carries a `HypothesisLook` row is NOT re-evaluated on a later run even
   though its `n_station_days` has grown — no second row is appended, no status
   changes, and the run records `skip_reason="ALREADY_LOOKED"` — and it REFUSES
   a second evaluation outright; a look attempted against a zero-look record
   (`REJECTED` disposition or `UNDERPOWERED_NOT_REGISTERED`) is a hard refusal
   that appends no row; and the triage loads NO boundary artefact on any path,
   since every admitted record is `SINGLE_LOOK` by §6.1's withdrawal.
   **Zero-take and veto REDs (§6.1):** a fixture mixing `fills = 0` `COMPLETED`
   rows with take-carrying days produces exactly ONE look whose `n_station_days`
   counts only the with-takes days, reports both counts and `take_rate`, and
   never raises `combine_station_day`'s empty-day `ValueError`; and the
   nine-cheap-winners/one-expensive-100-leg-loser counterexample fixture
   produces a `PRIMARY_PASSED_PNL_VETO` row -- no `CONFIRMED` status, no H5/H6
   evidence pack -- while the variant's alpha is recorded as spent.
4. **GREEN** `scripts/analysis/hypothesis_triage.py`.
5. **RED→GREEN** the scheduling surface of §6.4b, in the two existing test
   files rather than new ones:
   - `tests/unit/test_analysis_units_memory_capped.py` — the new
     `breezy-hypothesis-triage.service` declares `MemoryHigh`/`MemoryMax` and
     `Slice=breezy-studies.slice`, and declares
     `After=breezy-replay-daily.service`.
   - `tests/unit/test_analysis_units_serialized.py` — `hypothesis-triage-run.sh`
     takes the host-wide `breezy-studies.lock` with `flock -n` and
     skip-not-kill (`exit 0`), and contains exactly one `"$PY"` invocation,
     `scripts/analysis/hypothesis_triage.py`, with no JSONL parsing.
   - **The AUD-09 non-regression RED:** an assertion that the `"$PY"`
     invocation set of `deploy/systemd/replay-daily-run.sh` is **exactly** the
     three scripts AUD-09 **B18**/AUD-10 **C19** name
     (`replay_sufficiency_census.py`, `replay_daily_runner.py`,
     `promotion_proposal.py`) and does **not** contain
     `hypothesis_triage.py` — i.e. this item is proven not to have edited
     AUD-09's wrapper or invalidated B18/C19.
   - A triage failure (non-zero exit, missing/unreadable AUD-09 artefact,
     unknown schema version) emits exactly one `CRITICAL` alert to a recording
     fake sink and then exits non-zero.
6. **Gate:** `scripts/ci/run_tests_no_egress.sh`, `lint-imports`, `mypy
   src/breezy`.
7. **Register the CLOSED disposition for the forecast-taker class as data,
   not prose** — one `HypothesisRecord` with `status=REJECTED`,
   `k_variants=12` (matching `PREREG_WP7_MULTIPLICITY_RULE`), so a future
   registration attempt reusing that `hypothesis_id` prefix is refused by
   `register_hypothesis`'s duplicate check rather than relying on a human
   remembering the ruling.
8. **PEER-RULING STEP, then first real intake.** The operator has delegated
   strategy-lead rulings to engineering peers, so the first-intake horizon is
   decided HERE, by a named in-plan step, not deferred to an external actor:
   - **Dispatch two independent specialist peers per hypothesis** — an AUTHOR
     (trading-bot-architect) and an ADVERSARIAL REVIEWER
     (prediction-market-reviewer), briefed blind and separately, each
     reasoning from source and from the §6.3 evidence.
   - **Artefact:** `docs/evidence/RULING_<hypothesis_id>_horizon_<date>.md`,
     dated and signed by both peers, following this repo's existing `RULING_*`
     convention.
   - **The ruling MUST fix, in numbers:** (i) `min_station_days` per stratum
     (the pre-registered n at which the single look is taken — station-days
     WITH `>= 1` take, §6.1's zero-take rule; a take-rate too low to reach it
     inside the horizon is a KILL-clock matter, never a diluted n); (ii) the
     STOPPING RULE — `look_policy`, which is `SINGLE_LOOK` (the only admitted
     value, §6.1) and `k_variants <= MAX_VARIANTS_PER_HYPOTHESIS`, with the
     enumeration listed; (iii) the ALPHA SHARE — the variant's
     `per_variant_alpha` as ASSIGNED by §6.1's fixed Bonferroni split; the
     ruling CONFIRMS the allocation, it never hand-picks an alpha; (iv) the
     KILL CRITERION — the PARKED horizon in days past which §6.6's programme
     conclusion is read; **(v) the POWER CHECK (§6.1), computed and stated
     BEFORE any data is opened** — the minimum detectable effect from §6.1's
     PINNED formula
     `MDE = (z_(1-per_variant_alpha) + z_POWER) / (2 * sqrt(n))` at that
     `per_variant_alpha` and that `min_station_days` in station-day-clustered
     units, with the conservative Bernoulli variance bound `1/4` and one
     effective observation per station-day, **expressed as an edge per take net
     of costs** over `BE = a + theta * a * (1 - a) + slippage` at
     `theta = 0.0695` and AUD-12's slippage allowance, **and** the plausibility
     bound the ruling is willing to assert for a true effect on this venue. The
     ruling records EVERY input (`n`, `per_variant_alpha`, `POWER`, the variance
     bound, `theta`, slippage, reference ask, `order_quantity` -- which is 1,
     §6.1 -- and `station_day_statistic`, which is `MEAN_EXCESS_PER_TAKE`, the
     observation the `1/4` bound is derived for) so `register_hypothesis` can
     RECOMPUTE the number and refuse on mismatch; it is re-issued if AUD-12
     later publishes a measured slippage that changes `BE`. **The ruling MUST record
     `power_is_primary_only = true` and state IN TERMS that the stated MDE is
     PRIMARY-test power only, per §6.1 POWER-PRIMARY-ONLY** (which governs how
     the plausibility bound is read; the ruling asserts no number for the
     shortfall). If the MDE exceeds that bound the hypothesis is NOT registered:
     it is written `UNDERPOWERED_NOT_REGISTERED`, consuming no alpha and no
     slot, and the ruling says so in terms — an unpowered test is not evidence,
     and paying a quarter of the programme's budget for one is the failure mode
     `RULING_forecast_edge_programme_closes_2026-09-20.md` §7 already records;
     **(vi) the POOLED-P&L VETO and the CONCENTRATION CAP, PRE-REGISTERED as
     part of the design, not chosen at the look** — the ruling records that
     `CONFIRMED` additionally requires `pooled_net_pnl_per_contract > 0`
     strictly over the same confirmatory sample (net of `theta = 0.0695` and
     AUD-12's slippage through each leg's `BE_i`), that
     `max_single_day_leg_share_cap` is the pinned `0.20`, and that a veto
     yields the terminal `PRIMARY_PASSED_PNL_VETO` disposition which consumes
     the variant's alpha and is never handed on. The ruling states plainly that
     the veto spends NO alpha of its own because it can only shrink the
     rejection region.
   - **The ruling NEVER touches an operator cap.** It fixes statistical
     design only: it assigns no value to the max-daily-budget or
     max-per-position controls, and it arms nothing.
   - **Ordering is load-bearing:** the ruling lands **BEFORE** the
     `HypothesisRecord` is registered and **BEFORE any data for that
     hypothesis is opened** — a horizon chosen after looking at the sample is
     not a pre-registration, it is the exact failure mode `PREREG_WP7_MULTIPLICITY_RULE §1.v`'s
     freeze-date firewall exists to prevent.
   - Only then are the archive-table-recalibration class and the NO-side class
     registered as `PARKED_INSUFFICIENT_DATA` (one `HypothesisRecord` each),
     satisfying the binding constraint that PREREG semantics change only
     through a ruling artefact.
9. **First scheduled triage run**, observed by hand once: confirm both
   registered hypotheses report `PARKED_INSUFFICIENT_DATA` with a reason that
   matches §6.3's stated evidence, and that the run adds no new decisions,
   orders, or state to the live path.

## 8. Measurable acceptance criteria and required evidence

| # | Criterion | Evidence |
|---|---|---|
| D1 | `hypothesis_ledger.py` refuses malformed registration and an unknown schema version | step 1 RED→GREEN |
| D2 | Triage never evaluates a hypothesis under its declared `min_station_days`, and never scores a `MECHANISM_ONLY`/`params_match=false` row | step 3 RED→GREEN |
| D3 | A `K_variants`-exhausted, no-survivor hypothesis reaches `ABANDONED_CAP_EXHAUSTED` and emits exactly one alert via the shipped sink | step 3 RED→GREEN |
| D4 | The forecast-taker class is registered `REJECTED` with `k_variants=12`, and a duplicate registration attempt under the same id is refused | step 7 |
| D5 | AUD-09's wrapper is UNCHANGED by this item: the `"$PY"` invocation set of `deploy/systemd/replay-daily-run.sh` is exactly AUD-09 B18's/AUD-10 C19's three named scripts and does not contain `hypothesis_triage.py`; AUD-18's own unit declares `MemoryHigh`/`MemoryMax`, `Slice=breezy-studies.slice` and `After=breezy-replay-daily.service`, and its wrapper takes the host-wide `breezy-studies.lock` with `flock -n`, skip-not-kill, with exactly one `"$PY"` invocation | step 5 RED→GREEN |
| D6 | Zero orders, zero live-path state changes result from any triage run — proven by an AUTOMATED gate, not a hand check: (i) an `import-linter` `forbidden` contract in `pyproject.toml` forbidding `breezy.analysis.hypothesis_ledger` from importing anything under the live node's import graph (`breezy.runtime`, `breezy.execution`, `breezy.adapters`, `breezy.strategy`) and forbidding those packages from importing it — so the module is outside the live graph in BOTH directions; (ii) a test asserting `scripts/analysis/hypothesis_triage.py` writes only under `~/.local/share/breezy/derived/hypothesis/`; (iii) the whole suite re-run under `scripts/ci/run_tests_no_egress.sh`, so a triage run that tried to reach the venue would fail the sandbox rather than a reviewer's eye | step 5 + step 6 command output |
| D9 | The no-re-look invariant holds mechanically: a `SINGLE_LOOK` variant with an existing `HypothesisLook` row is never re-evaluated as n grows and refuses a second evaluation; a look against a zero-look record is a hard refusal; the triage loads no boundary artefact on any path | step 3 RED→GREEN |
| D12 | The programme alpha allocation is fixed a priori and bounded: assigned `allocated_alpha`/`per_variant_alpha` match §6.1's split exactly, the summed nominal alpha over all registered variants never exceeds `PROGRAMME_ALPHA`, an exhausted hypothesis budget refuses registration (no recycling of a REJECTED share), `k_variants > MAX_VARIANTS_PER_HYPOTHESIS` is refused, no admissible allocation falls below `MIN_PER_VARIANT_ALPHA`, and any `look_policy` other than `SINGLE_LOOK` is refused at registration | step 1 RED→GREEN |
| D13 | The POWER CHECK is mandatory, mechanical and cost-free to fail: (i) `recompute_mde` reproduces §6.1's pinned formula on both worked examples (`n=300 → 0.1032`, `n=600 → 0.0730` at `per_variant_alpha=0.003125`, `POWER=0.80`, variance bound `1/4`) — both PRIMARY-TEST-POWER-ONLY figures, so the record and the §7 step 8 ruling carry `power_is_primary_only = true` and a record asserting `False` is REFUSED, because §6.1's pooled-P&L veto makes the MDE an UPPER bound on `P(reach CONFIRMED)` by an amount this design does not bound analytically and asserts no number for — and the break-even helper on `a=0.30, theta=0.0695, slippage=0.01 → 0.324595`; (ii) a caller-supplied MDE is never trusted — a stated value disagreeing with the recomputed one is refused naming both numbers; (iii) an off-pin input is refused — `mde_fee_theta = 0.06` (the stale `config.py:226` default) and an unjustified `mde_variance_bound != 0.25` both refuse; (iv) a recomputed MDE above `mde_plausibility_bound` is refused as `UNDERPOWERED_NOT_REGISTERED`, carrying `allocated_alpha == 0.0`, leaving `programme_budget_remaining` unchanged and never carrying a `HypothesisLook` row; (v) the §7 step 8 ruling artefact states the MDE, the plausibility bound and EVERY input (`n`, `per_variant_alpha`, `POWER`, variance bound, `theta`, slippage allowance, reference ask), all dated before `registered_at`; (vi) the pinned unit quantity the `1/4` variance bound depends on is ENFORCED, not assumed -- `order_quantity != 1` is refused at registration naming `NON_UNIT_ORDER_QUANTITY`, and the §7 step 8 ruling records the design's `order_quantity` among the MDE inputs; (vii) the station-day OBSERVATION the `1/4` bound is derived for is ENFORCED, not assumed -- `station_day_statistic != "MEAN_EXCESS_PER_TAKE"` is refused at registration naming `NON_MEAN_STATION_DAY_STATISTIC`, a worked MIXED-SIDE fixture (YES + NO legs, `q = [0.5, 0.5]`, `qty = 1`, admitted by the `Sum_i q_i > 1` gate) asserts the station-day SUM's variance is `1.0 > 0.25` while the pinned MEAN's is `<= 0.25`, a MANY-LEGS fixture asserts the MEAN's bound holds as legs are added, and the §7 step 8 ruling records `station_day_statistic` among the MDE inputs; (viii) the ZERO-TAKE rule is ENFORCED and VISIBLE, not implicit -- a legitimately `COMPLETED` `replay_results.jsonl` row with `fills = 0` (AUD-09 §6b.3) is dropped at §6.4 step 4's named draw-set-construction filter, so it never reaches `combine_station_day` and never raises its empty-day `ValueError` (`current_rung_hold_v2.py:318-319`), every look row reports `n_station_days_observed`, `n_station_days_with_takes` and `take_rate`, and the confirmatory `n_station_days` equals the WITH-TAKES count only (a 40-observed/12-with-takes fixture looks at 12); (ix) the POOLED-P&L VETO is MANDATORY, alpha-free and VETO-ONLY -- `CONFIRMED` requires `pooled_net_pnl_per_contract > 0` strictly (computed from `combine_station_day`'s own `x`, `current_rung_hold_v2.py:337-340`, net of `theta = 0.0695` and AUD-12 slippage via each `BE_i`) AND `max_single_day_leg_share` within the pre-registered pinned cap `0.20`; the nine-1-leg-winners/one-100-leg-loser counterexample yields `PRIMARY_PASSED_PNL_VETO` with its `veto_reason`, alpha consumed and no H5/H6 hand-off, a FAILED primary with positive pooled P&L stays `REJECTED`, `max_single_day_leg_share_cap != MAX_SINGLE_DAY_LEG_SHARE` is refused as `NON_PINNED_LEG_SHARE_CAP`, and the §7 step 8 ruling pre-registers all of it | step 1 RED→GREEN + step 3 RED→GREEN + step 8 artefact |
| D10 | The pre-registration peer ruling exists as `docs/evidence/RULING_<hypothesis_id>_horizon_<date>.md`, is dated before the hypothesis's `registered_at` and before any data for it is opened, is signed by two independent peers, fixes n / stopping rule / alpha share / KILL criterion / MDE + plausibility bound + every MDE input (D13), and assigns no operator cap a value | step 8 artefact |
| D11 | A triage failure (non-zero exit, missing or unreadable AUD-09 artefact, unknown schema version) emits exactly one `CRITICAL` alert through the shipped `resolve_alert_sink`/`emit_alert` path and exits non-zero | step 5 RED→GREEN |
| D7 | H4/H5/H6 hand-off artefacts are read-only from AUD-18's side — no field is requested of AUD-09/AUD-10 that they do not already emit | inspection of §6.4/§6.5 against AUD-09 §6b.4, AUD-10 §6b.3 |
| D8 | `lint-imports` and `mypy src/breezy` stay green with the new module inside the existing `analysis` layer | command output |

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Failure case — every BLOCKED class stays blocked indefinitely.** Not a
  system failure: §6.6 names the honest terminal reading of that state
  ("nothing arms") and the advisory alert (§6.4 step 7) keeps it visible
  rather than silently aging out, closing the same "correct finding,
  undelivered" shape AUD-02 §6.4/§9 names for A1.
- **The expected outcome, stated honestly: a programme KILL is MORE LIKELY
  than a CONFIRMED hypothesis, and that is this item working.** PM.us offers 5
  cities × one daily HIGH settlement, so station-days accrue at ~5/day even
  when every class is unblocked; §6.1's multiplicity correction then costs
  another factor on top, leaving `per_variant_alpha` at `0.003125` one-sided at
  best. The repo's own history at the far looser `alpha = 0.05` — three
  retracted results and an underpowered negative
  (`RULING_forecast_edge_programme_closes_2026-09-20.md` §7) — is direct
  evidence that a real effect on this surface is already hard to resolve, and
  nothing here makes the sample larger. The plan therefore does not predict a
  CONFIRMED hypothesis and must not be read as promising one: its deliverable
  is a TRUSTWORTHY terminal state, and §6.1's power check exists precisely so
  the likely KILL arrives EARLY and cheaply (refused at registration, no alpha
  spent) rather than after a quarter of the budget has been burned on a test
  the sample could never have passed. Both branches satisfy the goal-state
  rule — measured positive-expectancy trading OR an evidenced KILL; only an
  indefinite "still looking" would not.
- **One honest worked illustration of what that power check will actually
  return.** Run §6.1's pinned formula at the floor allocation
  `per_variant_alpha = 0.003125` (`z = 2.7344`), `POWER = 0.80`
  (`z = 0.8416`), variance bound `1/4`, one effective observation per
  station-day, at two plausible PM.us horizons — 5 stations x 60 days
  (`n = 300`) and 5 stations x 120 days (`n = 600`):
  - `n = 300`: `(2.7344 + 0.8416) / (2 * sqrt(300)) = 3.5760 / 34.6410 =`
    **`0.1032`**.
  - `n = 600`: `3.5760 / (2 * 24.4949) = 3.5760 / 48.9898 =` **`0.0730`**.
  In market terms, at a reference ask `a = 0.30` the break-even is
  `BE = 0.30 + 0.0695 * 0.30 * 0.70 + 0.01 = 0.324595`, so the `n = 600` case
  demands a TRUE per-take hold probability of about `0.398` against a
  break-even of `0.325` — a **7.3-point** absolute edge net of fees and
  slippage, after FOUR MONTHS of every-station accrual, and **10.3 points**
  after two. **The honest implication: at any plausibility bound a peer ruling
  could defend on this venue — this repo's own measured edges are
  sub-percentage-point, not 7-to-10-point — the expected disposition of a
  first-intake hypothesis is `UNDERPOWERED_NOT_REGISTERED`, not `REGISTERED`.**
  That is the check working: it converts an un-runnable test into a dated,
  zero-cost refusal at intake instead of a quarter of the programme's alpha
  spent on a result that could never have reached significance. A hypothesis
  clears this bar only by raising `n` (more stations, or a longer
  pre-registered horizon), by narrowing `k_variants` to 1 (which roughly
  quadruples the allocation and cuts the MDE by about a factor of `1.2`), or
  by targeting a genuinely large effect — never by relaxing `POWER`, the
  variance bound, or `theta`, all of which are pinned against exactly that
  temptation.
- **The two MDEs above are PRIMARY-TEST power (see §6.1 POWER-PRIMARY-ONLY).**
  What that changes for THIS section's conclusion: the underpowered-at-intake
  expectation stated in the bullet above is if anything UNDERSTATED here, never
  overstated.
- **Failure case — a station-day produced no take at all.** The overwhelmingly
  common case on this venue, not an anomaly
  (`docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,11-16`: 0 of 40,796 decisions
  reached a price on 2026-09-20, 0 of 53,624 on 2026-09-16). §6.1's zero-take
  rule handles it as data, not as an error: the `fills = 0` `COMPLETED` row is
  dropped at §6.4 step 4's named filter, `combine_station_day`'s empty-day
  `ValueError` is never raised, both counts and the take rate land on the look
  row, and the hypothesis's `n` advances only on with-takes days — so an
  all-empty stretch parks the hypothesis and eventually trips §6.4 step 7's
  advisory alert instead of silently producing an under-powered look.
- **Failure case — the primary test passes on a sample that lost money.** §6.1's
  worked counterexample (nine one-leg winners at `ask ~ 0.02` against one
  hundred-leg loser at `ask ~ 0.98`: `Sum_d X_d ~ +7.5` while pooled dollars are
  `~ -89.5`) is reachable because the MEAN equal-weights days and P&L does not.
  The mandatory pooled-P&L veto converts that from a false CONFIRM into the
  terminal `PRIMARY_PASSED_PNL_VETO` disposition, with the variant's alpha
  consumed and nothing handed to H5/H6. It cannot mask the opposite error: a
  failed primary stays `REJECTED` however positive the pooled number is.
- **Failure case — a triage run crashes mid-write.** The ledger and
  evaluations files use the same atomic temp+`os.replace` discipline AUD-09's
  H0 writer uses; a crash leaves the prior file intact, and the next run
  re-reads from a known-good state — no partial-row corruption.
- **Integration:** this item touches no live trading code path; it reads two
  existing artefacts and writes two new ones under
  `~/.local/share/breezy/derived/hypothesis/`.
- **Failure case — the triage unit fails or never runs.** Covered by D11:
  the failure alerts once through the shipped sink and exits non-zero, so the
  unit's own `systemctl --user` failed state is corroborated by a delivered
  alert rather than discovered weeks later.
- **Autonomous operation:** the triage runs unattended from its own
  `Type=oneshot` unit (§6.4b), ordered `After=breezy-replay-daily.service`
  and serialised behind the SAME host-wide `breezy-studies.lock` every other
  nightly analysis unit takes (skip-not-kill), inside `breezy-studies.slice`
  with its own `MemoryHigh=1G`/`MemoryMax=2G` containment. It consumes
  AUD-09's artefacts read-only and never edits AUD-09's wrapper. Hypothesis
  **intake** (registering a new class) is deliberately NOT autonomous — it
  requires the §7 step 8 peer ruling the binding PREREG-semantics constraint
  mandates.

## 10. Deployment, observability, rollback

Deployment is: land the module + script + the three scheduling files of
§6.4b, `systemd-analyze --user verify` them (empty output = PASS, per
`deploy/systemd/README.md` §2), `systemctl --user enable --now
breezy-hypothesis-triage.timer`, run the gate (§7 step 6). **AUD-09's wrapper
is not touched**, so B18/C19 stay green (D5). Observability is the alert path
already shipped (WP-B0), the unit's journal under
`SyslogIdentifier=breezy-hypothesis-triage`, and the two JSONL artefacts, both
human-readable via `jq`. Rollback: `systemctl --user disable --now
breezy-hypothesis-triage.timer` — one command, no edit to any other item's
unit; the ledger and evaluations files are inert once nothing reads or writes
them, and no live trading behaviour depends on their existence.

## 11. Relationship to portfolio-level ROI and how it will be evaluated

This item does not move ROI by itself — like AUD-02, it is a governance layer
preventing §3's two evidenced failure modes at programme scale (a result
manufactured by uncorrected repeated looks; a hypothesis aging with no artefact
saying whether that is data or abandonment). **On the honest expectation:**
given PM.us's 5-city daily-HIGH sample and the cost of this correction (§9),
the more likely terminus of this programme is an evidenced KILL — PM.us
daily-high rungs close, and continued engineering investment is redirected —
not a CONFIRMED hypothesis. §9's worked power check makes that expectation
numerical rather than rhetorical: at the floor allocation the detectable edge
is `0.1032` at `n = 300` station-days and `0.0730` at `n = 600` — 7 to 10
points net of a `0.0695`-coefficient fee and AUD-12's slippage allowance —
against a venue where this repo has never evidenced an edge of that size.
**Those figures are PRIMARY-TEST power only (see §6.1 POWER-PRIMARY-ONLY),
which binds every downstream citation of them — a ruling author, AUD-02/A1 or
AUD-10b.** What that changes for THIS section's expectation: it makes the
evidenced-KILL terminus MORE likely than these numbers alone imply, never less.
So the most probable ROI contribution of this item is **capital and engineering
time NOT spent**: a dated, defensible stop beats an open-ended spend, and the
alternative is the status quo of uncorrected ad hoc studies §3 shows already
produced three retractions.
**On what a `CONFIRMED` pack now guarantees:** §6.1's mandatory pooled-P&L veto
means a `CONFIRMED` disposition additionally carries positive pooled net P&L per
contract over its OWN confirmatory sample, net of the `0.0695` fee coefficient
and AUD-12's slippage — so what AUD-02/A1 (H5) and AUD-10b (H6) receive is an
edge that also made money on the days it was measured on, not merely a positive
average per take on equal-weighted days. That strictly raises the bar and
therefore makes the evidenced-KILL terminus more likely still, which is the same
direction §9 already states.
**Evaluated by:** whether
the ledger's disposition table (§6.3, kept current by §6.4) ever differs from
what a hand audit of the underlying evidence would find — the test of whether
the programme is honest, independent of whether any hypothesis clears its bar.

## 12. Assumptions, unresolved questions, blockers

- **Assumption:** AUD-09a/b, AUD-11 and AUD-12 land substantially as specified;
  this item's `C-VALIDITY`-mirroring gate (§6.4 step 4) depends on
  `REPLAY_VALIDITY`/`params_match` existing as named there.
- **NOT a blocker any more — converted to an in-plan step.** The first-intake
  horizon for the archive-table-recalibration and NO-side classes was framed
  in round 1 as an external strategy-lead blocker. The operator has delegated
  strategy-lead rulings to engineering peers, so it is now **§7 step 8**: a
  named, dispatched two-peer PEER RULING producing
  `docs/evidence/RULING_<hypothesis_id>_horizon_<date>.md` before registration
  and before any data for that hypothesis is opened. Nothing external is
  waited on.
- **Operator-only residue, stated exactly and with no value:** the ONLY
  operator-reserved gate left on this path is **live-trading enablement of a
  NEW family** — plus the two operator-reserved cap VALUES (max daily budget,
  max per position), which are **already established and are never named,
  proposed or changed by this plan or by any artefact it produces**. The
  budget ceiling is therefore **NOT a blocker on AUD-18** and is not listed as
  one: AUD-18 arms nothing, and a `CONFIRMED` hypothesis is evidence handed to
  a ruling, never an enablement.
- **AUD-18's output is an INPUT to a future A1-class ruling, never a
  self-executing re-arm.** `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
  (Revision 3, ENDORSED by independent peer review with no required change —
  trail `docs/evidence/reviews/RULING_A1_review_2026-09-21.md`; cited by path
  only) names AUD-18 as owner of A1's "genuinely independent edge estimate".
  AUD-18 honours that scope: `CONFIRMED` produces an evidence pack (H5) for a
  future A1-class ruling to weigh — no arming, no enablement, no PREREG change.
- **Out of scope, stated so it is not read as an omission:** position sizing
  above unit quantity. §6.1 pins `order_quantity = 1` as a REGISTRATION
  constraint of this programme because the `1/4` variance bound is conservative
  only there; sizing belongs to **AUD-06a** (boundary revalidation) and
  **AUD-06b** (bounded allocation), cited by id only. A `CONFIRMED`
  unit-quantity edge is the evidence those items need as an INPUT -- it is not
  a licence to size, and AUD-18 neither proposes nor enables one.
- **Accepted limitation, stated so it is not read as an oversight:** §6.1's
  pinned `MEAN_EXCESS_PER_TAKE` station-day observation measures AVERAGE EDGE
  PER TAKE, equal-weighted within the station-day — it is **not** the day's
  P&L, and a day with many legs counts exactly once. That is the price of a
  variance bound that holds for ANY side mix, leg count and dependence
  (Popoviciu), and it is accepted deliberately — but **what the mean is
  conservative ABOUT is now stated precisely, because the earlier unqualified
  "conservative for this purpose" claim was not supportable in the direction
  that matters.** The mean is conservative about **VARIANCE**: `1/4` is a true
  upper bound on `Var(X_d)` for any side mix, leg count and dependence, so the
  MDE and the Type-I control on the per-take estimand are not optimistic, and
  it keeps the clustered station-day as the unit of analysis. It is **NOT
  conservative about ECONOMIC WEIGHTING**: it equal-weights station-days while
  real P&L is leg-weighted, so nine one-leg winners can outvote one
  hundred-leg loser and a primary CONFIRM can coexist with decisively negative
  pooled dollars (§6.1's worked counterexample). That direction is NOT accepted
  as a limitation — it is CLOSED by §6.1's mandatory, alpha-free, veto-only
  pooled-P&L gate, which no `CONFIRMED` disposition may bypass. ROI accounting
  — where the additive station-day SUM is correct — stays exactly where it
  already lives (`realized_draws.py`, `family_tally_v2.py`, settlement),
  untouched by this item, and the veto REUSES that same SUM
  (`combine_station_day`'s own `x`) rather than adding an estimator.
- **Accepted limitation: the programme's stated power is PRIMARY-ONLY, so it
  is never a confirmation-rate claim — see §6.1 POWER-PRIMARY-ONLY.** It is
  ACCEPTED rather than closed because the shortfall is not bounded analytically
  and errs in the SAFE direction; narrowing it would need a simulation-based
  composite-power estimate, which is a FUTURE amendment with its own ruling and
  is OUT OF SCOPE here.
- **Accepted limitation, stated honestly — the estimand is CONDITIONAL on the
  strategy's own trigger.** §6.1 excludes zero-take station-days, so
  `MEAN_EXCESS_PER_TAKE` estimates edge per take GIVEN a take occurred. That is
  what "edge per take" means and it is the right input for AUD-06a/AUD-06b, but
  it is silent on HOW OFTEN the strategy trades — and on this venue that is not
  a small silence: `docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,11-16`
  measures zero takes across 40,796 and 53,624 decisions on two recent days. The
  look row therefore carries `take_rate` beside the estimate (§6.2), and a
  CONFIRMED edge is handed to H5/H6 with that rate attached; a large per-take
  edge at a near-zero take rate is not a tradeable programme result and must not
  be read as one.
- **Open:** whether the archive-table class can EVER clear `min_station_days`
  per stratum on this venue's real tape growth rate — genuinely unknown, and
  §6.6's horizon exists precisely so that unknown does not stay open forever.
- **Closed by §6.1's mechanism, stated so it is not re-opened by accident:** a
  variant withdrawn mid-programme (e.g. its strategy code is found defective)
  forfeits its pre-allocated share — allocation is never recycled, so the union
  bound still holds and no adjustment formula is needed. The cost is power, not
  validity, and it is accepted deliberately.
- **Withdrawn here, recorded as a FUTURE amendment:** group-sequential
  (`LD_OBF`) monitoring. It is not merely unused — it is arithmetically
  unreachable at ANY allocation under a multi-hypothesis budget (§6.1), since
  `per_variant_alpha <= 0.0125 < 0.025`, the shipped artefact's only pin
  (`gs_boundary_artefact.py:78,82,269-272`). Reinstating it requires BOTH its
  own ruling AND a newly generated pinned boundary artefact at a reachable
  alpha, each registered as separate work (§5); until then `SINGLE_LOOK` is the
  only admitted policy and anything else is refused at registration.

## 13. Review history

**Baseline self-score (round 1, as authored — not re-scored here): 83/100**,
with named weaknesses at baseline: mid-programme variant-withdrawal treatment
left open (now closed, §12); the fourth-wrapper-invocation claim unverified
(now withdrawn, §6.4b); bootstrap CI cited by reused primitive; no criterion
proves the programme yields a CONFIRMED result (inherent — KILL is a valid
terminal state); crash-mid-look recovery asserted from the atomic-write
pattern.

**Round-1 peer review (independent, blind):** prediction-market-reviewer
72/100, mle-reviewer 75/100 (records under `reviews/`).

**Revision log**

| Round | Edits made | Status |
|---|---|---|
| 1 | Baseline authored. | NOT READY — peer review pending |
| 2 | Seven reviewer-named defects addressed in place, no scope removed. (1) The fourth-`"$PY"`-invocation into AUD-09a's wrapper is withdrawn: AUD-09 **B18** and AUD-10 **C19** name exactly three scripts and fail an unnamed fourth, and both items are closed — AUD-18 now ships its own `breezy-hypothesis-triage` unit/timer/wrapper (§6.4b) ordered `After=breezy-replay-daily.service`, serialised on the same host-wide `breezy-studies.lock` with `flock -n` skip-not-kill, capped `MemoryHigh=1G`/`MemoryMax=2G` in `breezy-studies.slice`, alerting failures through the shipped `resolve_alert_sink`/`emit_alert` path; §5 excludes editing AUD-09/AUD-10, §7 step 5 adds a RED asserting AUD-09's wrapper script set is unchanged, D5 restated, D11 added. (2) Nightly re-evaluation under Holm–Bonferroni removed as uncorrected repeated significance testing: §6.4 step 3 now fixes a `look_policy` at registration — `SINGLE_LOOK` (one look ever, enforced by an "already-looked" `HypothesisLook` row) or `LD_OBF` reusing the shipped, pin-verified `BoundaryArtefact.boundary_for`/`alpha_spent`/`remaining_alpha` over `information_fraction` on a pre-registered `n_k` grid — with the composition rule against the programme Holm ladder stated; §6.2 adds `look_policy`/`look_schedule_n`/`is_terminal_look`/`is_variant_eligible`, §7 step 3 adds the REDs, D9 added. (3) `load_realized_draws` re-cited to `src/breezy/persistence/realized_draws.py:249`; neighbouring citations re-verified against source (`combine_station_day` 298, `score_combined` 348, `resolve_alert_sink` 579, `emit_alert` 668, `information_fraction` 367). (4) The first-intake horizon becomes an in-plan two-peer PEER-RULING step (§7 step 8, §6.6) producing `docs/evidence/RULING_<hypothesis_id>_horizon_<date>.md` before registration and before any data is opened, fixing n, stopping rule, alpha share and KILL criterion and touching no operator cap; D10 added. (5) §12's "operator budget ceiling" blocker removed — the ceiling is already established; the only operator-only residue is live-trading enablement of a NEW family plus the two already-set cap values, named without values. (6) D6 converted from a one-time hand check to an automated gate: an `import-linter` forbidden contract in both directions against the live node's import graph, a write-path assertion, and re-run under `scripts/ci/run_tests_no_egress.sh`. (7) §13's embedded pre-scored self-review prose replaced by a baseline summary and §11 de-duplicated against §3 — no requirement, test or acceptance criterion cut; **the file nevertheless GREW 473 -> 638 lines this round** (the §6.4b scheduling surface, the sequential-design spec and the peer-ruling step are net additions), so the round-2 claim of a length reduction was true only of §13's own prose, not of the file. Added to §12: the peer-ENDORSED (Revision 3, no required change) `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` names AUD-18 as owner of A1's independent edge estimate, and AUD-18's output is an INPUT to a future A1-class ruling, never a self-executing re-arm. | NOT READY — round-2 peer review pending |
| 3 | Round-2 peer defects addressed in place; no scope, test or acceptance criterion removed. **(1) MATERIAL (mle-reviewer): the LD_OBF/Holm composition did not control FWER.** Both halves verified against source first — `load_boundary_artefact` does hard-refuse `i_max != 40` / `alpha != 0.025` (`src/breezy/persistence/gs_boundary_artefact.py:78,82,269-272`), and `PREREG_WP7_MULTIPLICITY_RULE §1.ii` does apply Holm at ONE fixed-sample selection decision over `K_variants = 12`, not across a programme. Holm is therefore **dropped at programme level** and replaced by ONE coherent, implementable mechanism (§6.1): a FIXED a-priori Bonferroni allocation — `PROGRAMME_ALPHA`/`MAX_HYPOTHESES` declared before intake, `allocated_alpha = PROGRAMME_ALPHA / MAX_HYPOTHESES` and `per_variant_alpha = allocated_alpha / k_variants` ASSIGNED at registration, never recycled, an exhausted budget REFUSING further intake, `SINGLE_LOOK` at the allocated alpha, and `LD_OBF` available ONLY when `per_variant_alpha == 0.025` (generating a new pinned artefact is newly EXCLUDED in §5). §6.1 now states what IS controlled (FWER over the pre-declared hypothesis budget, by union bound) and what is NOT (anything beyond the cap; post-hoc hypotheses, which are refused). §6.2's schema replaces `family_wise_alpha` with `allocated_alpha`/`per_variant_alpha`, adds the three programme constants and `programme_budget_remaining`; §6.4 step 3's composition rule, §7 steps 1/3/8 REDs and D9 are restated to match, and **D12** is added (allocation matches the split, summed alpha never exceeds `PROGRAMME_ALPHA`, exhausted budget refuses, off-pin `LD_OBF` refused). §12's Holm-withdrawal open item is closed by the same mechanism (a withdrawn variant forfeits its share). **(2) MINOR (prediction-market-reviewer): §13's round-2 row called the A1 ruling "PROPOSED" while §12 said ENDORSED, and claimed "length reduced" though the file grew** — both corrected factually in that row. **(3) MINOR: §6.4b's `OnCalendar` was constraint-only** — now the concrete `*-*-* 01:20:00 UTC`, justified against the enumerated `deploy/systemd/*.timer` tick list (no `HH:MM` collision; first free minute after the protected `[16:35Z, 01:15Z)` no-start window; 15 min clear of 01:35) and against the shared `breezy-studies.lock`, which it maximises headroom on. **(4) Length: genuine duplication only** was cut — §5's restatement of AUD-09 B18/AUD-10 C19 (now cited by id), §11's restatement of §3, §12's RULING_A1 prose, and §13's baseline self-score table (now a summary line). **The 120-250 target is NOT reachable without losing substance:** the file was 731 lines at that round's end (was 638; the row's own "730" was off by one and is corrected here); the added statistical mechanism, its four REDs and D12 are requirements, and every remaining section is a requirement, test, acceptance criterion, failure case or citation this brief forbids removing. | NOT READY — round-3 peer review pending |
| 4 | Round-3 peer defects addressed in place; nothing removed but one withdrawn option and the text that offered it. **(1) MATERIAL (mle-reviewer): `LD_OBF` was arithmetically unreachable yet presented as selectable.** Verified from source first: `I_MAX = 40.0` / `ALPHA_ONE_SIDED = 0.025` and their hard refusals (`src/breezy/persistence/gs_boundary_artefact.py:78,82,269-272`), against which `per_variant_alpha = PROGRAMME_ALPHA / MAX_HYPOTHESES / k_variants` can never reach `0.025` under any multi-hypothesis budget. **`LD_OBF` is WITHDRAWN as a selectable look policy** (KISS): `SINGLE_LOOK` is the only admitted policy, the reason is stated plainly in §6.1/§6.4 step 3/§12, and group-sequential looks are recorded as a FUTURE amendment needing their own ruling AND a newly generated pinned artefact (§5, which now excludes the whole design, not just the artefact). Every passage offering it is removed or reworded (§5, §6.1, §6.2's `look_policy`/`look_schedule_n`/`PINNED_LD_OBF_ALPHA`, §6.4 step 3, §7 steps 1/3/8, D9, D12); **one RED is kept — any `look_policy` other than `SINGLE_LOOK` is refused at registration.** **(2) MATERIAL (prediction-market-reviewer): power was unexamined.** (a) The constants are now DERIVED: `MAX_HYPOTHESES = 4` is §6.3's own count of look-taking classes (archive-table recalibration, NO-side, hours 10-11) plus one reserve for the maker/resting redesign §6.3 names — nothing else in §6.3 is registerable; `MAX_VARIANTS_PER_HYPOTHESIS = 4` is new, encoding fewer-and-sharper over broad sweeps; together they floor `per_variant_alpha` at `MIN_PER_VARIANT_ALPHA = 0.003125` one-sided, ~6x the ≈0.0005 the old 8x12 split left. Zero-look records (the §7 step 7 `REJECTED` disposition row at `k_variants=12`, and the new `UNDERPOWERED_NOT_REGISTERED`) carry `allocated_alpha = 0.0`, consume no slot and are exempt from the variant ceiling. (b) A **POWER CHECK is now mandatory** at the §7 step 8 ruling and at registration: before any data is opened the ruling states the MDE at the assigned alpha for the pre-registered n over station-day-clustered draws under the repo's own estimators (`combine_station_day`/`score_combined`, `src/breezy/settlement/current_rung_hold_v2.py:298,348`; the `ROIBoundUnderpowered` refusal precedent, `src/breezy/settlement/roi_bound.py:100,130,173`) plus a plausibility bound, and `register_hypothesis` REFUSES an MDE above that bound as `UNDERPOWERED_NOT_REGISTERED`, consuming NO alpha — §6.2 adds `mde_at_allocated_alpha`/`mde_plausibility_bound` and the status, §7 steps 1(vi)/8(v) add the REDs and the ruling clause, **D13** is added and D10 restated. (c) §9 and §11 now state honestly that at PM.us's 5-city daily-HIGH accrual an evidenced programme KILL is MORE LIKELY than a CONFIRMED hypothesis, that this is the programme working rather than failing, and that the power check exists so that KILL arrives early and cheaply — both branches satisfying the goal-state rule. **(3) MINOR: the round-3 length claim (730) was off by one** — corrected in that row; **this file is now 832 lines (was 731), and it GREW again, said plainly.** Withdrawing `LD_OBF` did cut text (§6.1's pin paragraph, §6.4 step 3's LD-OBF block, the `look_schedule_n`/`PINNED_LD_OBF_ALPHA` schema and their off-grid/off-pin REDs), but the mandatory power check that replaced the unexamined-power defect — derived constants, the zero-look-record rule, the §7 step 8 ruling clause, D13 and its RED — is a larger net addition. No requirement, test or acceptance criterion was cut to make room; the 120-250 target remains unreachable for the reason round 3 gave. | NOT READY — round-4 peer review received (mle-reviewer 83/100, prediction-market-reviewer 86/100) |
| 5 | **Round-4's single MATERIAL defect, found independently from two sides — the mandatory pre-data POWER CHECK was mis-cited and under-specified — fixed ONCE, coherently.** Verified in source before editing. **(a) The two mis-citations are withdrawn for this purpose and the text says why:** `ROIBoundUnderpowered`/`compute_roi_bound` (`src/breezy/settlement/roi_bound.py:100,130,173`) is a POST-HOC `n >= MIN_NON_EXCLUDED_N` floor on already-collected rows that computes NO effect size, and `combine_station_day`/`score_combined` (`src/breezy/settlement/current_rung_hold_v2.py:298,348`) are estimators over REALIZED `StratumRow` data — an estimator cannot be run "over draws" that do not exist yet. Neither is precedent for a PROSPECTIVE MDE; both keep their existing correct roles (§6.4 step 4, settlement) and neither is cited for power any more. **(b) §6.1 now pins a mechanical, outcome-free MDE convention:** unit of analysis = the station-day (clustered), `n` = the pre-registered station-day count; variance input = this repo's OWN conservative Bernoulli bound `q(1-q) <= 1/4` — the derivation behind the shipped `I_MAX = 40.0` pin (`src/breezy/persistence/gs_boundary_artefact.py:75-78`) as specified in `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md:55-60` (`I_max = n_max x 1/4 = 40`, "the theoretical bound, fixed once, ex ante", explicitly forbidding a live or look-1 estimate); design effect handled conservatively at ONE effective observation per station-day unless pre-registered otherwise; `POWER = 0.80` declared as a PINNED design constant, never a per-hypothesis dial; and the one-sided formula stated outright — `MDE = (z_(1-per_variant_alpha) + z_POWER) * sqrt(1/4) / sqrt(n)`. **(c) The MDE is expressed in MARKET terms, an edge per take NET of costs:** the excess of the true hold probability over `BE = a + theta * a * (1 - a) + slippage` at a pre-registered reference ask, with the shipped fee arithmetic (`polymarket_us_fee`, `src/breezy/adapters/polymarket_us/fees.py:277`) at the CURRENT evidenced `theta = 0.0695` (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:7,47`); the config default `required_fee_coefficient = Decimal("0.06")` (`src/breezy/strategy/current_rung_hold/config.py:226`) is named STALE for this purpose and forbidden, and the slippage allowance is AUD-12's (its UNMEASURED one-tick placeholder until AUD-12 lands, with a stated obligation to re-run this check and re-issue the ruling when it does). **(d) ENFORCEMENT moved from discretion into code:** `register_hypothesis` no longer accepts a caller-supplied MDE — §6.2 adds `recompute_mde` plus `POWER`/`VARIANCE_BOUND`/`EVIDENCED_FEE_THETA` and the `mde_reference_ask`/`mde_fee_theta`/`mde_slippage_allowance`/`mde_variance_bound` input fields, and registration RECOMPUTES the MDE and refuses on mismatch, on any off-pin input (stale `theta`, unjustified variance bound), and on `MDE > mde_plausibility_bound` (`UNDERPOWERED_NOT_REGISTERED`, alpha `0.0`, no slot). §7 step 1 gains REDs (vi-a..vi-e) pinning the COMPUTATION on two worked examples, the mismatch refusal, the stale-theta refusal and the variance-bound refusal; §7 step 8(v) restates the ruling clause with the formula and the full input list; **D13** is rewritten to five clauses and D10 updated. **(e) §9 and §11 carry one honest worked illustration:** at `per_variant_alpha = 0.003125` (`z = 2.7344`), `POWER = 0.80` (`z = 0.8416`) and variance bound `1/4`, `n = 300` gives `3.5760 / 34.6410 = 0.1032` and `n = 600` gives `3.5760 / 48.9898 = 0.0730` — 7 to 10 points of net edge over a `BE` of `0.324595` at `a = 0.30`, far above anything this repo has evidenced, so the expected first-intake disposition is stated plainly as `UNDERPOWERED_NOT_REGISTERED` rather than `REGISTERED`, and the only admitted ways to clear the bar (raise `n`, narrow `k_variants`, target a larger effect) exclude relaxing any pinned constant. **(f) Length: this file is now 961 lines (was 832) and it GREW again, said plainly** — the pinned convention, the recomputation surface, five REDs and the worked illustration are all net additions; nothing was cut to make room, and the 120-250 target remains unreachable for the reason round 3 gave. | NOT READY — round-5 peer review pending |
| 6 | **Round-5's single MATERIAL defect -- the pinned `VARIANCE_BOUND = 0.25` is a true conservative bound only at unit quantity, and nothing in the plan stated or enforced that -- fixed with the minimum correct edit.** Verified in source first: `combine_station_day` computes `variance = sum(qty * qty * q * (1.0 - q) ...)` minus the mutual-exclusivity covariance (`src/breezy/settlement/current_rung_hold_v2.py:341-344`) and its admission gate refuses only `sum_i q_i > 1` -- it bounds no `qty`, so at `qty_i = 2` one leg alone reaches `4 * q(1 - q) <= 1.0`, four times the assumed ceiling, and the recomputed MDE would UNDER-state the true MDE (the unsafe direction). The fix is the convention this repo already lives by, made a REGISTRATION CONSTRAINT of this programme rather than an inherited assumption: **every hypothesis AUD-18 registers is evaluated at `order_quantity = 1`**, citing `docs/specs/PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md:110-113` (§2.2 "Fixed across every variant (not searched) ... Quantity 1") and `CurrentRungHoldConfig.__post_init__`'s shipped `InvalidOrderQuantityError` ("order_quantity must be exactly 1", `src/breezy/strategy/current_rung_hold/config.py:253-255`). Round 5's reviewer cited this as "PREREG_v2 §2.2"; PREREG v2 has no §2.2 -- the text is PREREG_WP7's, and the plan cites the verified location. §6.1 adds the pinned-quantity bullet and states plainly that the `1/4` bound's conservatism RESTS on it; §6.2 adds `PINNED_ORDER_QUANTITY: Final[int] = 1` and the `order_quantity` record field, and `register_hypothesis` REFUSES a non-unit design naming `NON_UNIT_ORDER_QUANTITY`; §7 step 1 adds RED **(vi-f)** (a `order_quantity = 2` registration refused, the otherwise-identical unit-quantity record registering) and step 8(v) adds `order_quantity` to the ruling's recorded MDE inputs; **D13 gains clause (vi)** (no criterion renumbered); §12 adds an explicit out-of-scope bullet. **Sizing above 1 is NOT this item's subject** -- it belongs to **AUD-06a** (boundary revalidation) and **AUD-06b** (bounded allocation), cited by id only, and a CONFIRMED unit-quantity edge is the INPUT those items need, never a licence to size. No scope, test, acceptance criterion or citation was removed, and no operator-reserved value is named. **Length: 1004 lines (was 961) -- it GREW again, said plainly**; the additions are one constraint, one constant, one field, one refusal, one RED and one acceptance clause. | NOT READY -- round-6 peer review pending |
| 7 | **Round-6's single MATERIAL defect -- the pinned `VARIANCE_BOUND = 0.25` is not conservative for a MIXED-SIDE (YES + NO) station-day even at `qty = 1` -- fixed at the ROOT, by pinning the OBSERVATION rather than patching the bound.** Verified in source first: `combine_station_day`'s covariance term (`src/breezy/settlement/current_rung_hold_v2.py:342-344`) SUBTRACTS only when two legs share a side; for an opposite-side pair `s_i * s_j = -1` and it ADDS, so at `q = [0.5, 0.5]`, `qty = 1`, one YES leg and one NO leg the station-day SUM's variance is `0.25 + 0.25 + 0.5 = 1.0` -- four times the bound -- and the admission gate does NOT refuse it, because it fires only on `Sum_i q_i > 1` (`:331`) while this day sums to exactly `1.0`. That hits NO-side hunting, one of §6.3's three open registerable classes. **The fix:** §6.1 now PINS the station-day observation, for the power check AND the confirmatory test, as the station-day MEAN of per-take excess outcomes, `X_d = (1 / m_d) * Sum_i (W_i - BE_i)`, and states the derivation explicitly -- each `W_i - BE_i` spans an interval of width `1`, so their mean does too, so by **Popoviciu's inequality** `Var(X_d) <= 1/4` for ANY side mix, ANY leg count and ANY dependence between legs. Reliance on the SUM for this purpose is withdrawn and the reason is stated; `combine_station_day` KEEPS its per-leg terms and its admission/fold/opposite-side refusals as the reused primitive, and KEEPS the SUM wherever the repo does ROI accounting (`persistence/realized_draws.py`, `scripts/analysis/family_tally_v2.py`, settlement) -- each use is checked and labelled in §6.1 with the statistic it needs. **Stated honestly:** the mean estimates AVERAGE EDGE PER TAKE, equal-weighted within the station-day; it is NOT the day's P&L and a many-leg day counts once -- conservative for this purpose, and recorded as an accepted limitation in §12. **Propagated for consistency:** §3(d); §6.2 gains `STATION_DAY_STATISTIC = "MEAN_EXCESS_PER_TAKE"`, the `station_day_statistic` record field and a `NON_MEAN_STATION_DAY_STATISTIC` registration refusal, with `VARIANCE_BOUND`'s and `recompute_mde`'s comments re-derived off the mean; §6.4 step 4 and §7 step 3 aggregate across legs as the MEAN, never the SUM; §7 step 1 adds REDs **(vi-g)** (the worked mixed-side `q = [0.5, 0.5]` fixture asserting the SUM's variance `1.0 > 0.25` while the pinned MEAN's is `<= 0.25`, plus the statistic refusal) and **(vi-h)** (a many-legs mixed-side fixture, bound holds as legs are added); §7 step 8(v) records `station_day_statistic` among the MDE inputs; **D13 gains clause (vii)** (no criterion renumbered). The round-6 `order_quantity = 1` pin is KEPT but correctly demoted: under the mean statistic the `1/4` bound no longer depends on it, so it is belt-and-braces (and still removes the `qty^2` term from the SUM used for ROI accounting), and §6.1 says so. **The worked MDE numbers in §9/§11 are UNCHANGED and were re-checked: `0.1032` at `n = 300` and `0.0730` at `n = 600`** -- the bound the formula consumes is still exactly `1/4`, only its justification changed from an unstated single-side/unit-quantity assumption to a side-mix-free, leg-count-free, dependence-free derivation, so `recompute_mde` and both worked examples need no edit. No scope, test, acceptance criterion or citation was removed, and no operator-reserved value is named. **Length: 1112 lines (was 1004) -- it GREW again, said plainly**; the additions are one derivation, one constant, one field, one refusal, two REDs, one acceptance clause and one limitation bullet. | NOT READY -- round-7 peer review pending |
| 8 | **Round-7's two MATERIAL defects, one per reviewer, fixed in place; nothing removed, nothing renumbered.** Both verified in source before editing. **(1) MATERIAL (mle-reviewer): zero-take station-days (`m_d = 0`) were unaddressed while being a legitimate and DOMINANT case.** AUD-09 **§6b.3**'s `replay_results.jsonl` schema records `trials, fills` and admits `outcome = COMPLETED` independently of `fills` (`AUD-09-scheduled-per-station-replay.md:697-702`), and `docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,11-16` MEASURES 0 of 40,796 decisions reaching a price on 2026-09-20 and 0 of 53,624 on 2026-09-16 -- while `combine_station_day` raises `ValueError` on an empty day (`src/breezy/settlement/current_rung_hold_v2.py:318-319`). §6.1 now states the rule explicitly: a `fills = 0` day is EXCLUDED at a NAMED filter stage -- §6.4 step 4's draw-set construction, between the `C-VALIDITY` gate and the first `combine_station_day` call -- BEFORE any statistic, so the empty-day `ValueError` is unreachable by construction; both counts are REPORTED (`n_station_days_observed`, `n_station_days_with_takes`, plus `take_rate`); and every `n`/`min_station_days`/`n_station_days` in this item means station-days WITH `>= 1` take, so the power check's n is the with-takes count and a take-rate too low to reach it in the horizon is caught by the horizon/KILL rule (§6.4 step 7, §6.6), never silently diluted. The SELECTION CAVEAT is stated honestly in §6.1 and §12: conditioning on a take is conditioning on the strategy's own trigger -- that IS "edge per take", it says nothing about how often the strategy trades, and `take_rate` is reported alongside. **(2) MATERIAL (prediction-market-reviewer): the MEAN equal-weights station-days while real P&L is leg-weighted, so the primary test can CONFIRM on decisively negative pooled dollars** (the reviewer's counterexample: nine 1-leg winners at `ask ~ 0.02` give `Sum_d X_d ~ +7.5` against one 100-leg loser at `ask ~ 0.98` whose pooled P&L is `~ -89.5`). §6.1 adds a MANDATORY, ALPHA-FREE, VETO-ONLY secondary gate before any `CONFIRMED` disposition: `pooled_net_pnl_per_contract = Sum_d CombinedDraw.x` over the SAME confirmatory sample, from the EXISTING SUM machinery (`combine_station_day`, `current_rung_hold_v2.py:298,337-340`), net of cost through each leg's `BE_i = break_even_row(entry_ask_i, fee_i)` (`:76-84`) at `theta = 0.0695` and AUD-12's slippage, must be `> 0` STRICTLY; otherwise the disposition is the named terminal state `PRIMARY_PASSED_PNL_VETO`, which CONSUMES the variant's alpha (the look was taken) and is never handed to H5/H6 -- and it can NEVER rescue a failed primary. It needs no alpha allocation because a veto-only gate can only SHRINK the rejection region, so Type-I error stays bounded by `per_variant_alpha`; the cost is power, taken deliberately. Leg-count concentration is bounded cheaply too: `max_single_day_leg_share` is recorded and a PINNED cap `MAX_SINGLE_DAY_LEG_SHARE = 0.20` is pre-registered on the record, with `NON_PINNED_LEG_SHARE_CAP` refused at registration and an over-cap look taking the same terminal state. **§12's conservatism claim is CORRECTED** to say precisely what the mean is conservative about (VARIANCE -- `1/4` bounds `Var(X_d)` for any side mix, leg count and dependence) and what it is NOT (ECONOMIC WEIGHTING), with the latter closed by the veto rather than accepted. **Propagated for consistency, by clause, with no renumbering:** §6.1 (two new bullets); §6.2 (`ZERO_TAKE_STATION_DAYS_EXCLUDED`, `POOLED_PNL_VETO_REQUIRED`, `MAX_SINGLE_DAY_LEG_SHARE`; `min_station_days` re-commented as with-takes; `max_single_day_leg_share_cap` on the record; the `PRIMARY_PASSED_PNL_VETO` status; `n_station_days_observed`/`n_station_days_with_takes`/`take_rate`/`pooled_net_pnl_per_contract`/`max_single_day_leg_share`/`veto_reason` on the look row; `pooled_net_pnl_per_contract()`); §6.4 steps 3, 4 and 6; §7 step 1 REDs **(vi-i)** and **(vi-j)**, step 3's zero-take and veto REDs, step 8 clause (i) restated and new clause (vi); **D13 gains clauses (viii) and (ix)**; §9 gains two failure cases; §11 states what a `CONFIRMED` pack now guarantees. **The worked MDE numbers are UNCHANGED and were re-checked: `0.1032` at `n = 300` and `0.0730` at `n = 600`, at `per_variant_alpha = 0.003125`, `POWER = 0.80`, variance bound `1/4`** -- neither fix touches the formula or the bound it consumes; the zero-take rule only names WHICH station-days count toward `n`, and the veto is applied after the primary test at no alpha cost. No scope, test, acceptance criterion or citation was removed, and no operator-reserved value is named. **Length: 1372 lines (was 1112) -- it GREW again, said plainly**; the additions are two §6.1 bullets, three constants, one record field, one status, six look-row fields, one pure function, four REDs, two acceptance clauses, two failure cases and one corrected limitation. | NOT READY -- round-8 peer review pending |
| 9 | **Round-8's two defects fixed in place; nothing renumbered, no constant changed.** **(1) MATERIAL (mle-reviewer): power statements were not honestly qualified now that the pooled-P&L veto exists.** `POWER = 0.80` and the worked MDEs are `P(primary CI excludes zero | true effect = MDE)` -- the PRIMARY test only -- while `CONFIRMED` additionally requires the mandatory veto, and since the `CONFIRMED` set is a strict SUBSET of the primary rejection region (the same containment that makes the veto alpha-free), `P(CONFIRMED | true effect = MDE) <= 0.80`, strictly lower whenever a true-positive draw can fail the veto. Every place the figures are presented now says so: **SS6.1** gains a dedicated bullet (upper-bound statement + four mechanical sub-clauses), **SS6.2** re-comments `POWER` and adds the `power_is_primary_only: bool` record field, **SS7 step 1 (vi-a)** asserts `power_is_primary_only == True` and REFUSES a `False` record, **SS7 step 8 clause (v)** makes the ruling state it in terms, **D13 clause (i)** carries it (clause text extended, no new clause, nothing renumbered), and **SS9**, **SS11** and **SS12** each state it where the numbers appear. **The gap is NOT bounded analytically and NO number is invented for it** -- it depends on the realized leg-count and entry-price heterogeneity ACROSS station-days, unknown before the data is opened -- so it is handled MECHANICALLY and CONSERVATIVELY: the refusal direction is safe a fortiori (composite power can never EXCEED primary power, so an `UNDERPOWERED_NOT_REGISTERED` verdict is never wrong in the permissive direction), and the admitting direction is LABELLED primary-only wherever cited, never upgraded to "an 80% chance a real edge is confirmed". A simulation-based composite-power estimate is recorded as a FUTURE amendment needing its own ruling (SS12), not assumed here. **(2) MINOR (mle-reviewer): `MAX_SINGLE_DAY_LEG_SHARE = 0.20` was asserted as "the coarsest bound under which no single day can carry a pooled result" -- a property leg-COUNT share does not have.** The claim is WITHDRAWN and reframed in SS6.1 and SS6.2's comment: `0.20` is a PRAGMATIC, PRE-REGISTERED CONCENTRATION GUARDRAIL (pinned in the same spirit as the conventional `POWER = 0.80`), and the plan now says plainly that a leg-COUNT share does not bound a P&L-DOLLAR share, since each leg contributes `W_i - BE_i` at its OWN entry ask. **What closes the money-losing-CONFIRM gap is the STRICT `pooled_net_pnl_per_contract > 0` condition** -- at the pinned `qty = 1` that pooled sum IS the sample's exact realised net P&L per contract -- with the share cap kept as an ADDITIONAL ROBUSTNESS SCREEN against an estimate resting on one station-day. **The value stays PINNED at `0.20`** (it is pre-registered; changing it is out of scope), and `NON_PINNED_LEG_SHARE_CAP` is unchanged. **The worked MDE numbers, the MDE formula and every pinned constant are UNCHANGED and were re-checked: `0.1032` at `n = 300` and `0.0730` at `n = 600`, at `per_variant_alpha = 0.003125`, `POWER = 0.80`, variance bound `1/4`, `MAX_SINGLE_DAY_LEG_SHARE = 0.20`, `theta = 0.0695`, `PINNED_ORDER_QUANTITY = 1`** -- this round changes only what those numbers are SAID to mean and one record field that carries the qualification. No scope, test, acceptance criterion or citation was removed, no criterion renumbered, and no operator-reserved value is named. **Length: 1487 lines (was 1372) -- it GREW again, said plainly**; the additions are one SS6.1 bullet, one reframed cap paragraph, one record field, two constant comments and six qualifying statements. | NOT READY -- round-9 peer review pending |
| 10 | **Round-9's single named defect -- the §6.1 POWER-PRIMARY-ONLY argument (`POWER = 0.80` is primary-test power only; every MDE from it is an UPPER bound on `P(reach CONFIRMED)`) was restated as a full normative paragraph in FOUR independently-editable places, a drift risk -- fixed by CONSOLIDATION, not by scope reduction.** The full derivation stays exactly where it was, in **§6.1**, now carrying the stable anchor label **§6.1 POWER-PRIMARY-ONLY** and naming which sections cite it versus which enforce it. The three duplicate paragraphs are reduced to ONE sentence each stating only what that section uniquely owns, plus the anchor reference: **§9** keeps its section-specific consequence (the underpowered-at-intake expectation is UNDERSTATED, never overstated); **§11** keeps its section-specific consequence (the evidenced-KILL terminus is MORE likely than the numbers alone imply, never less) and the downstream-citation binding on AUD-02/A1 and AUD-10b; **§12** keeps the limitation's ACCEPTED status and its FUTURE-amendment route (a simulation-based composite-power estimate, out of scope here). **§7 step 8 clause (v)** re-argued the point at paragraph length and is trimmed to its binding requirement -- the ruling MUST record `power_is_primary_only = true` and state it in terms, per the anchor. **Nothing else changed, and nothing binding was removed:** §7 step 1's RED (`power_is_primary_only == True` asserted, `False` REFUSED), §6.2's record field and constant comments, and D13 clause (i) are untouched enforcement artefacts, not restatements. **Every pinned constant and both worked MDEs are UNCHANGED and were re-checked: `0.1032` at `n = 300`, `0.0730` at `n = 600`, `per_variant_alpha = 0.003125`, `POWER = 0.80`, variance bound `1/4`, `MAX_SINGLE_DAY_LEG_SHARE = 0.20`, `theta = 0.0695`, `PINNED_ORDER_QUANTITY = 1`**; the pooled-P&L veto definition is unchanged; no criterion renumbered; no operator-reserved value named. **Length: 1460 lines (was 1487) -- it SHRANK this round**, the first round it has, entirely by removing duplicated normative prose. | NOT READY -- round-10 peer review pending |

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `eac43837f2e9f6bec8cd2771f92b583467df58d2d9e3b2339b57f3bce12a67d1`
- **Baseline self-score:** 83/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 10: 100/100 — `reviews/AUD-18-r10-mle-reviewer.md`
  - `prediction-market-reviewer` round 10: 100/100 — `reviews/AUD-18-r10-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None blocking the build of the programme. Expected first outcome, stated honestly: at PM.us sample sizes the pinned power check gives a minimum detectable edge of roughly 7–10 probability points (`0.1032` at `n=300`, `0.0730` at `n=600`, primary-test power only — see §6.1 POWER-PRIMARY-ONLY), so the likely first disposition is `UNDERPOWERED_NOT_REGISTERED` or an evidenced programme KILL, not a confirmed edge.
  - Live enablement of any family this programme confirms is operator-only and is not part of this plan. Operator caps are established and never stated here.
- **Full review history:** 20 records, `reviews/AUD-18-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
