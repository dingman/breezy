# RULING — S0: `pm_us_crh` probabilistic NBM-NBP forecast family — reopening, distinctness, and pre-registration pins

**Slug:** `forecast_nbp_reopen` · **Date:** 2026-09-29 · **Author:** trading-bot-architect
(BLIND run; no other agent's output visible). **Status:** SIGNED 2026-09-29. Peer round 1: prediction-market-reviewer
78 REVISE ("ship after fix") and mle-reviewer 78 REVISE. Confirmation:
mle-reviewer 87 APPROVE on the §12 amendments, which are binding and supersede
earlier text. S1 is authorized. **Arms nothing. Sets no operator control. Registers no ledger row.**

**Source:** `docs/plans/FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
(CONVERGED Rev 3, four-reviewer round-3 APPROVE, no open CRITICAL/HIGH), §1.1
obligations 1–6, §2.2, §2.5, §3.3, §4.1, §4.2, §4.4, §9 Q5/Q9/Q15/Q17.
Binding, not re-litigated: forecast-edge-closed-pmus-rungs (TERMINAL, WP7
class, 09-20); RA-13 KILL backstop 2027-01-25, firm, not extended by capture
holes (L-38); RA-13 B-3 — the firewall binds the **corpus**, not the
statistic; bot NOT ARMED, A1 halt operator-only and SET.

---

## 1. Distinctness — argued row by row against the closed WP7 class (obligation 1)

Closed class = WP7's 12-variant TXN-point + frozen-sigma family, REJECTED
`k=12` [VER `PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md:69-73,135-143`;
`hypothesis_ledger.jsonl:2`]. Comparison per plan §1.1 table:

| Dimension | Closed (WP7) | This family | Distinct? |
|---|---|---|---|
| Information set | TXN point + fitted, frozen sigma | NBP ensemble: day-varying spread (TXNSD) + 5 percentiles (shape/skew) | YES — a structurally different predictor, not a re-fit of the same one |
| Uncertainty | Climatological, same every day | Flow-dependent, varies by day — a candidate new source of *resolution* | YES, but not asserted for free: gated empirically by G2.3 (obligation 2, below) |
| Lead/cycle | D0 only, no partition | D+1 only, inside a live permit window | YES — disjoint lead structure; D0 variants were dropped for cause (§2.3: METAR truncation, repricing timing, permit does not cover the 07Z cycle) |
| Hours | Fixed LST windows (09–12, 12–17, 10–11) | Permit-covered hours, decisive; all-hours descriptive only | YES — a different, code-derived window, never a hand-picked LST band |
| Execution | Taker at ask only | Taker (V1) and maker/resting-bid (V2) | YES — a new execution mode with its own fee/haircut treatment |
| Cluster | Date primary | Station-day primary (date reported as sensitivity) | YES |
| Estimand | Per-cell median screen (WP7) → confirmatory Brier/D_res | `MEAN_EXCESS_PER_TAKE`, CLOSED, unchanged from the programme's own pinned estimand [VER `hypothesis_ledger.py:195-197`] | N/A — the estimand is shared BY DESIGN across the whole programme; sharing it is not evidence of non-distinctness, since WP7's own registration was scored on a different family of decision rules entirely |

**Ruling: DISTINCT.** Six of six comparison dimensions differ in kind, not
degree, and the one shared element (the confirmatory statistic) is a
programme-wide constant every hypothesis in the ledger uses, not a WP7-owned
artifact. This is not merely a sigma re-fit of the closed model — WP7's own
text anticipated that a sigma re-fit "is a new registration, not a knob" [VER
`PREREG_WP7:142`]; this family goes further, replacing the frozen-sigma
climatological model with a day-varying ensemble.

## 2. Obligation 2 — resolution-improvement pre-declaration (G2.3)

Ratified as written: "a model which does not improve *resolution* over the
closed model on matched events is not a distinct hypothesis" is G2.3 (plan
§4.1): require `D_res(model − M0)` station-day-clustered CI lower > 0 AND
point ≥ 0.0152 on the same D+1 matched events. **This is the operative
empirical test of distinctness for whichever model reaches S3**, and S0
closes one gap the plan left open (see §4 M1 fallback, below): G2.3 is a
general principle (obligation 2), not literally scoped to M2 only.

## 3. Hypothesis id and horizon (obligation 2 continued)

- **`hypothesis_id = H-FC-NBP-EV-2026-09`** — the confirmatory (S3b,
  programme-ledger, α-spending) leg named `H-FC-NBP-EV` in plan §2.1, dated
  per the ledger's own naming convention (`H-ARCHIVE-RECAL-2026-09`,
  `H-NO-SIDE-2026-09` [VER `hypothesis_ledger.py:146-150`]). **Never**
  `H-FORECAST-TAKER-*`. The S2 (`H-FC-NBP-SKILL`) and S3a
  (`H-FC-NBP-MKT-SEARCH`) legs spend no α and never touch the ledger, so they
  keep their plan-given working names unchanged.
- **`horizon_days = 180`** (of `RULED_HORIZON_DAYS ∈ {120, 180}` [VER
  `hypothesis_ledger.py:146-151`]). Rationale, outcome-free: this
  hypothesis's own S3b power arithmetic (plan §5) needs the **largest**
  pooled n in the programme (n≈1200–1743 at k=2, vs H-ARCHIVE-RECAL's n=600),
  and its trials are additionally thinned by the permit window (§3.3) — its
  realistic per-day accrual toward sufficiency is slower than
  H-ARCHIVE-RECAL's own 180-day design allowed for. 120 days mirrors
  H-NO-SIDE's narrower, faster-resolving question and is not a good
  structural match. **Note for the record:** RA-13's programme KILL backstop
  (2027-01-25, firm, ~118 days from today) binds independently of this
  choice and in practice will govern first if S3b registration lands near
  its own projected ≈2026-10-24..10-31 window — this pin only fixes the
  ledger-schema `horizon_days` field, it does not extend or supersede RA-13.
- **Programme slot:** `MAX_HYPOTHESES = 4` [VER
  `hypothesis_ledger.py:176-179`; that comment is design rationale, not
  occupancy]. **All 4 slots are free today:** all four existing ledger rows
  (H-ARCHIVE-RECAL, H-FORECAST-TAKER-RUNG-SCREEN, H-NO-SIDE, H-OFFWINDOW-T4)
  are `is_zero_look` (verified by peer against `hypothesis_ledger.jsonl`
  2026-09-29). This hypothesis occupies one slot only if REGISTERED at S3b. `programme_budget_remaining` [VER :813-822]
  must be checked live at that time; an `UNDERPOWERED_NOT_REGISTERED` or
  `REJECTED-at-S0` outcome is `is_zero_look` and never occupies or recycles a
  slot [VER :816-822].

## 4. Variant plausibility bounds (obligation 3), fixed before any tape is scored

- **V1 (taker): `mde_plausibility_bound = 0.03`.** By direct analogy to
  `RULING_H-ARCHIVE-RECAL-2026-09:85-95` — the same venue, the same 29%
  overround structure, and every measured comparator on this exact surface
  (WP7b ask CI half-width ≈0.013–0.020; the closed forecast-taker's own
  confirmed CI, under 3.3 points at its widest [VER
  `RULING_forecast_edge_programme_closes_2026-09-20.md:45`]) is sub-3.5-point.
  Nothing in the repo supports a larger plausible edge on PM.us daily-high
  rungs, regardless of which forecast model generates it.
- **V2 (maker): `mde_plausibility_bound = 0.03`**, same nominal value — there
  is no repo basis for a different *gross* informational-edge ceiling by
  execution mode. But V2's realized bar is strictly harder in practice: EV is
  computed **net of** the pessimistic quadratic fee ceiling (θ=0.0695, §6
  below) **and** the adverse-selection haircut (W=5 min, below), both of
  which only subtract from gross edge. Per plan §4.2, if A0 has not landed a
  wire-observed maker fee by S3b, V2 is reported
  `UNDERPOWERED-by-construction`, independent of this bound.
- **Honest read (already in the plan, ratified here):** at realistic
  post-freeze accrual (≈320–350 station-days by the RA-13 backstop, k=2),
  the recomputed MDE (≈0.096–0.10 unpooled, ≈0.089–0.093 pooled) exceeds
  0.03 by a wide margin. `UNDERPOWERED_NOT_REGISTERED` is the expected S3b
  outcome for V1 absent a materially longer horizon; V2 is stricter still.
  S0 does not pre-decide this — the actual power check runs at S3b against
  the real recomputed MDE, not this bound alone.

## 5. Pinned values (obligation 4)

- **M1 fallback validity.** Ruled **DISTINCT, conditionally.** M1
  (NBS-TXN-mean + XND-sd normal) differs from M0 on exactly one axis
  (day-varying vs frozen spread — §1's "Uncertainty" row). That single-axis
  change is thinner than M2's, so S0 closes the gap plan §2.2 left open:
  **if M1 becomes the surviving family model** (M2 fails G2.2 but M1 clears
  G2.0–G2.3), **G2.3 must be independently re-run as `D_res(M1 − M0)`** on
  the same matched D+1 events, before M1 is treated as a validated distinct
  fallback. G2.3 as literally worded in §4.1 names M2; this pin extends its
  general principle (obligation 2) to whichever model actually reaches S3.
  If M1 fails that check, the fallback is **void** and the family is not
  distinct at the model level — routes to §6 node 2 of the plan.
- **C-1 terms.** Ratified as fully specified in plan §4.1, unchanged: fires
  iff G2.1 fails on the v5.0 holdout while passing on validation; the only
  permitted re-fit (v5.0-only rolling refit); consumes the holdout look; a
  fresh holdout opens forward with the **same** n_min (≈412); **all four**
  S2 gates re-evaluate as a set on the fresh holdout; requires a documented
  protocol deviation co-signed by mle-reviewer; never silent, never taken
  twice. Consequence restated: taking C-1 almost surely moves S3b past the
  2027-01-25 KILL, routing to §6 node 4 (K-2 hand-off).
- **Haircut window `W = 5 minutes`.** Adopts the plan's own proposal (§4.2)
  as the S0 pin. Outcome-free: chosen without reading any tape, short enough
  to bound measurement noise in the adverse-selection statistic, long enough
  to capture a realistic repricing horizon on this venue's cadence.
- **Pooling: default NOT pooled** (plan §2.5). Ratified. S0 may elect
  pooling only if A0 lands the maker fee before S3b — that election, if the
  trigger fires, is made by the coordinator/peer loop at that later point
  against the actual A0 evidence, not asserted here in advance.
- **Permit-covered-hours definition.** The nominal schedule window
  `[LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS)`, read from code at run time
  (never hard-coded), per plan §3.3/R3-01. **Values recorded today, verified
  directly this session:** `LAUNCH_UTC = dt.time(16, 50)` UTC [VER
  `src/breezy/runtime/trade_supervisor_core.py:35`]; `PERMIT_TTL_NS =
  10*60*60*1_000_000_000` ns = 10 hours [VER
  `src/breezy/adapters/polymarket_us/safety.py:172`]. Today's nominal window
  is therefore **16:50Z–02:50Z**. Per the plan's own risk note (§9), SL-9
  must refuse at run time if either constant differs from this recorded pair
  without a fresh ruling.
- **G2.2 power target, σ_d, n_min.** `X = 0.0152` (the 09-20
  market-minus-forecast resolution gap [VER
  `RULING_forecast_edge_programme_closes_2026-09-20.md:45`]); planning
  `σ_d ≈ 0.11` (Rev 2's ±0.009 bound at 590 station-days); **`n_min ≈ 412`**
  final station-days (≈103 days × 4 stations), per the formula in plan
  §4.1. S0 replaces σ_d with its validation-split estimate once measured —
  outcome-free, since validation precedes any holdout peek.
- **G2.0 N and closed correction set.** `N = 60` final station-days
  spanning ≥15 distinct dates (months below N are `UNTESTED`, monitored by
  L, never tested). Correction set, closed: `{none, one offset per calendar
  month, linear in LST day-length}` — chosen on the validation split only;
  no other form may be introduced after S0.
- **τ grid for the LOVO shrinkage (S0 pin, not fully specified in the
  plan).** Parametrize τ as the partial-pooling shrinkage fraction on
  `[0, 1]`, where τ=0 is the unshrunk per-version fit (coincides with the
  §2.2 "v5.0-anchored" sensitivity) and τ=1 is full pooling to the grand
  mean across versions. **Pin the grid `τ ∈ {0.0, 0.1, 0.2, …, 1.0}`** (11
  points, uniform step 0.1) — fine enough for a meaningful LOVO-CRPS
  minimum, coarse enough to foreclose an unenumerated continuous search
  over an outcome-adjacent hyperparameter.

## 6. Firewall — Q5 (obligation 5)

- **(a) Does a registered SINGLE_LOOK of this hypothesis forfeit
  H-ARCHIVE-RECAL CONFIRM days? YES**, mechanically, under the already-binding
  rule that "the firewall binds the corpus, not the statistic" [VER
  `RULING_RA-13_programme_kill_2026-09-27.md` B-3, :90-92; restated at
  `RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md:19-33`]. S3b's
  confirmatory look reads the SAME going-forward PM.us tape corpus
  H-ARCHIVE-RECAL's own (currently unopened) confirmatory clock would draw
  from. **Today this costs nothing** — H-ARCHIVE-RECAL is
  `UNDERPOWERED_NOT_REGISTERED` and has never opened a confirmatory look
  [VER `RULING_RA-13:14`]. But it is a live scheduling dependency: any future
  H-ARCHIVE-RECAL registration (e.g. via the EDGE-4 revival trigger) that
  wants CONFIRM days over dates NBP's S3b look has already read will find
  those station-days already spent. **The coordinator must record this
  dependency explicitly at S3b registration time**, not discover it later.
- **(b) Does the §4.4 no-scoring rule suffice for S4-infra post-freeze
  shadow logs? NO.** §4.4's parity tool "emits mismatch counts only" on
  post-freeze tape. A mismatch count is structurally the same kind of
  object RA-13 B-3 already ruled DOES spend firewall days — that ruling's
  own precedent (an *outcome-blind* cluster count) was rejected as
  non-scoring precisely because the firewall binds the corpus, not whether
  the count carries outcome information. **S0 cannot certify §4.4 alone as
  sufficient.** Per §4.4's own named fallback: **S4-infra parity is
  RESTRICTED to replay on pre-freeze tape (≤2026-09-25) plus live liveness
  only** (actor publishes, strategy subscribes, decisions not persisted).
  S4-gate carries the first post-freeze parity check, which occurs only
  after S3b registration has already accepted the corpus cost named in (a).

## 7. Fee reconciliation (obligation 6)

The maker plausibility bound and every V2 EV computation use the **taker**
ceiling `θ = 0.0695` [VER `EVIDENCED_FEE_THETA`,
`hypothesis_ledger.py:202`; `fees.py:560-594` `taker_fee_at_fill`; pin file
`FEE_SCHEDULE_PIN_2026-09-18.md`], **never** the venue's documented maker
coefficient `MAKER_FEE_COEFFICIENT = Decimal("-0.0125")` [VER `fees.py:82`],
which is flagged DOCUMENTED-NOT-WIRE-OBSERVED — no captured payload or fill
confirms it, and a post-only order reaching the fee model today is refused
outright by `MakerRebateUnmodelledError` [VER `errors.py:305-322`] precisely
because charging the rebate would be wrong in sign. **This ceiling is
deliberately conservative and stays binding — for S3a's maker plausibility
bound and for any pooled-P&L veto involving V2 — until A0 produces a
wire-observed maker fee.** Relaxing it toward the documented rebate requires
a new S0-class amendment citing that A0 evidence; it is never a config edit
(mirrors the 09-17 θ drift precedent, where a first attempt to pin θ via
env-var was rejected by security review as a laundered pin edit [VER
`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:178-182`]).

## 8. Q9 — look policy (obligation 5)

**RESOLVED.** The confirmatory look is `SINGLE_LOOK`. `LD_OBF` is WITHDRAWN
programme-wide [VER `InvalidLookPolicyError`, `hypothesis_ledger.py:269-271`],
so A1 §7 item 4's "fresh LD-OBF α" language does not apply literally. The
post-enablement live tally, if this family ever reaches S5 and arms, is
governed by the family's **own** PREREG — a distinct control from the
programme's registration-time α, exactly as `pm_us_crh_v4`'s own tally is
governed separately from A1's registration α [VER
`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` throughout]. This closes
Q9 as a ruling, per the plan's own request.

## 9. Q15 — HUNT-1 vs the permit window

**Not fully resolvable at S0; the evidentiary requirement for S5 is pinned
now.** A1 §7 item 5 requires "all hours" [VER
`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:423-437`], and the
operator's own words are unambiguous: "never inside just a specific window."
The permit window (16:50Z–02:50Z, §5 above) is not all hours. **A
permit-bounded hour-coverage table alone does NOT satisfy A1 §7 item 5.**
However, this hypothesis's own trial trigger (§3.3: "evaluation runs on
every quote or depth update in **all venue hours**") already hunts
continuously — the permit only gates *executability* (whether an order can
be sent), a node-level safety control shared by every family, not a
decision-logic restriction this hypothesis chose. S0 pins that the S5
evidence pack must carry **both**, kept as distinct evidence, never
blended: (i) the all-hours decision/coverage table already produced
descriptively under R3-01, and (ii) an explicit accounting showing
NOT_EXECUTABLE decisions outside the permit are uniform across every family
on the node, not specific to this one. **Whether that combination satisfies
A1 §7 item 5 is reserved to the S5 ruling** — S0 does not decide it, per
Q15's own framing ("still open for the S0 and S5 rulings"), and this plan
does not propose changing `LAUNCH_UTC`/`PERMIT_TTL_NS` (Q16, out of scope).

## 10. Q17 — restated as binding

**RESOLVED (round 3, architect): option (b).** One node arms exactly ONE
sending family — `SENDING_FAMILY_ID_VAR` refuses more than one id
[VER `settings.py:356`]; `sending_family_id` is a single slot [VER
`settings.py:816-820`]; `trade.py:429-435` resolves the one sending family;
a single submit-intent flock [VER `submit_intent.py:556`]. The registered
look covers **both** V1 and V2 via offline replay, which never reads
`sending_family_id`. The S5 ruling arms **one** manifest at a time; swapping
which manifest is live is a manifest + env act, not a re-registration.
Options (a) (registry widening) and (c) (pooling via SL-10) are **rejected**.
V2 is not deferred — only its **live arming** is sequenced behind V1's.

## 12. Peer-review amendments (coordinator, 2026-09-29) — BINDING

Each amendment below supersedes any conflicting text above.

- **A-1 (PM HIGH) slot accounting:** corrected in §3. Programme budget today = 4
  of 4 free.
- **A-2 (PM MEDIUM) V2 bound = open assumption.** The 0.03 bound is carried
  over from net-of-taker-fee comparators, and nothing independently evidences
  a *gross* maker ceiling. Before V2 may enter any S3b intake, its bound is
  re-derived **net** of the A0 wire-observed maker fee and the W = 5 min
  haircut. Until A0 lands, V2 stays UNDERPOWERED-by-construction (§4).
- **A-3 (MLE HIGH + LOW) n_min is a formula, not a number.**
  - Fixed at S0: X = 0.0152, 80% power, two-sided α = 0.05, the formula
    n_min = ⌈((z₀.₉₇₅ + z₀.₈)·σ_d / X)²⌉, and the rule that σ_d is the
    **validation-split** estimate (station-day clustered). 412 is illustrative
    only.
  - S2's evidence note must record the measured σ_d and the applied n_min.
  - **Ceiling: n_min ≤ 520 final station-days.** 520 is the final v5.0-holdout
    count reachable by ≈2026-11-15, the latest S2 opening date that still
    leaves S3a+S3b able to register ≥ ~60 days before the 2027-01-25 KILL.
    Arithmetic: 07-01..11-15 ≈ 138 d × 4 stations × ≈0.95 final coverage.
  - If the recomputed n_min exceeds 520, S2 still runs when n_min is reached,
    as weather-only skill evidence and a K-2 asset. The PM.us confirmatory leg
    is then declared infeasible before the KILL and routes to plan §6 node 4
    **immediately**, with no waiting for accrual.
- **A-4 (MLE MEDIUM) shrinkage is precision-weighted.** This replaces the τ
  fraction.
  - Estimator: (a_v, γ_v)_shrunk = w_v·θ̂_v + (1 − w_v)·θ̄₋ᵥ, with
    w_v = n_v/(n_v + κ). Here n_v is the version's station-day count in its
    fit rows, and θ̄₋ᵥ is the leave-one-version-out pooled mean.
  - **κ grid pinned:** {0, 30, 60, 120, 240, 480, 960, ∞} station-days. κ = 0
    is unshrunk (the "v5.0-anchored" sensitivity); κ = ∞ is full pooling.
  - κ is chosen by the LOVO first-half-fit / second-half-score CRPS rule
    (plan §2.2), on validation plus the v5.0 fit slice only.
  - The S2 note reports the chosen κ, each version's n_v and w_v, and, as
    sensitivity, the unweighted τ-fraction result on the old
    {0.0 … 1.0, step 0.1} grid.
- **A-5 (MLE MEDIUM) S4-infra parity must compare two independent code paths.**
  On pre-freeze tape (2026-08-30..09-25; ≥ 14 days are required, and about 27
  are available), parity compares:
  - (i) the **live code path**: the NBP actor and strategy composed in a native
    Nautilus BacktestEngine replay of the captured tape;
  - (ii) the **batch path**: an offline script that recomputes decisions from
    the same NBP rows and tape, using only the pure modules (quantile_density,
    ladder_ev scoring, and the latch/permit rule), with **no** import of the
    strategy/actor classes.

  Parity = decision-key set equality, with mismatches = 0. A contract test pins
  that (ii) imports none of (i)'s classes, which rules out a vacuous
  self-comparison. Post-freeze live logs are liveness-only (§6(b)) until
  S4-gate.

- **Recorded residuals (LOW, not blocking):**
  - (i) A-5 parity shares the pure math modules between both paths, so a bug
    inside that shared math is invisible to parity. SL-6/SL-7 unit tests
    against hand-computed values are the control.
  - (ii) With only 5 versions, LOVO κ selection may be high-variance. The S2
    note reports the full CRPS-vs-κ curve, not just the argmin.

## 11. What this ruling does NOT authorize

No ledger registration, no `register_hypothesis` call, no S3b intake, no
change to the A1 halt, no assignment or naming beyond citation of any
operator-reserved control (max daily budget, max per position, live-trading
enablement) — none of the two operator-reserved caps or the enablement flag
are touched here. Nautilus Trader remains immutable and untouched.
`allow_short` stays `False`. No safety, settlement, or contract test is
weakened. This ruling does not itself start S1 — **S1 begins only after two
blind peer APPROVEs on this document** (plan §4, S0 exit criterion), and
even then S1's own build slices (§7 of the plan) carry the §8 invariants
verbatim in every brief.

---

## Unverifiable / not independently confirmed by me

- `RULING_HUNT-1` line-level citations (`:19,30,35,36,38,43`) are taken from
  the plan's and RA-13's own citations, not independently re-read this
  session.
- The precise rationale text behind `RULING_H-NO-SIDE-2026-09`'s own 120-day
  horizon choice was not independently read; my §3 horizon comparison relies
  on the ledger module's dated cross-reference comment only.
- `programme_budget_remaining`'s current live count (how many of the 4
  slots are actually free today) was not re-run against the current
  `hypothesis_ledger.jsonl` this session — the plan's own §2.4 states all
  four slots are free as of its writing; this should be re-verified at S3b
  intake time, not assumed carried forward unchanged.
