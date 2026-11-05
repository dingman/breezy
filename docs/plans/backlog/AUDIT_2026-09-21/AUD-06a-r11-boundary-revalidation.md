# AUD-06a — Clear R-11: re-validate the LD-OBF boundary against the RECORDED variance-inflation mechanism, publish the validated qty envelope and its staleness trigger

## 1. ID and actionable title

**AUD-06a** — Land **Amendment C** to `docs/plans/MULTI_POSITION_PER_STATION_2026-09-14.md`
replacing its validation slice item (ii), and run it: a seeded Monte-Carlo under the registered H0
that (a) **confirms or refutes the mechanism already recorded in the strict-xfail reason** —
variance inflation making information accrue faster than the artefact's solved schedule assumes, so
the boundary interpolation undershoots — and (b) reports the realised one-sided crossing rate as a
**function of the qty distribution**, publishing the largest qty envelope for which the boundary
still holds at α=0.025, **with an explicit staleness trigger**. Offline only; no sizing code, no
order.

## 2. Source finding and class

- **Gap:** G-11 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:82-84`). Verdict **FALSE
  (alignment)**: `order_quantity=1`; **MP-B blocked on R-11** (`PROGRESS.md:53`) (V);
  `weather_common/equity.py`'s `max_equity_fraction` is unused by the live family (A).
- **The blocker itself:** R-11 (`PROGRESS.md:76`) — "LD-OBF boundary validity at qty>1: H0 crossing
  0.059 at mixed qty vs α 0.025 (qty≡1: 0.012). Re-validate at the real Increment-B qty
  distribution, re-solve the artefact only if it still fails." Strict `xfail` at
  `tests/unit/test_multi_position_validation_2026_09_14.py:161-199`.
- **The recorded diagnosis this plan is built on (NOT a fresh hypothesis).** The xfail reason
  (`:163-179`) already states the measured mechanism verbatim:
  > "higher qty pushes a station-day's variance up to 9x a single Bernoulli term, so I saturates far
  > faster than the artefact's n_k/n_max=0.25-per-draw schedule assumes, and the realised-t boundary
  > interpolation undershoots at that faster accrual"

  and records the measurements the re-run must reproduce: 0.0592 at seed 20260914 / 5000 reps,
  0.058 at seed 20260914 / 2000 reps, against a qty≡1 control of ~0.011–0.013.
- **Registered context, verified:** `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6 reports a
  REGISTERED mixed-side Monte-Carlo **at qty ≡ 1** — 20000 reps per configuration, terminal crossing
  rates 0.0020–0.0199 across k ∈ {1,2,3,4}, per-look `Var(S) ∈ [0.98, 1.02]`, gate α + 3·SE =
  0.02831, verdict NULL_CORRECT. **This item is the qty>1 counterpart of that study and inherits its
  methodology deliberately** (see §6 "Methodology, pinned").
- **Existing item updated, not duplicated:** MP-B (`PROGRESS.md:53`). This file is the backlog entry
  for the **validation half**; the build half is AUD-06b.
- **Class:** **verification gap.** Nothing is broken in production; a statistical precondition for a
  capability is unmet and the capability is correctly withheld.

## 3. Current behaviour, required behaviour, concrete gap

**Current.** `order_quantity` is pinned to 1 and `InvalidOrderQuantityError` refuses anything else
(`current_rung_hold/config.py:253-256`). The registered statistic was generalised to qty weighting
in Increment A (S4a, merged `b5a7c04`) and is **correct by construction at qty≡1** — the byte-identity
test is its merge gate. What is NOT established is that the pre-solved LD-OBF boundary retains its
nominal one-sided type-I rate once draws carry unequal weights: the measured crossing rate at mixed
qty is ~0.059 against α=0.025, a ~2.4× over-spend of alpha. R-11 therefore correctly blocks MP-B.

**Required.** A reproducible, seeded artefact that (i) reproduces R-11's two figures, (ii)
**tests the recorded mechanism directly** by reporting the realised information-accrual trajectory
against the artefact's solved schedule, (iii) states the realised crossing rate as a function of the
qty distribution with a pinned CI construction, and (iv) publishes a **validated sizing envelope**
plus the conditions under which that envelope expires — expressible in code without ever reading an
operator-reserved value.

**Concrete gap, and the reason this is not simply "re-run it".** R-11 as written asks for
re-validation "at the real Increment-B qty distribution". That distribution is
`qty = floor(cap / ask / lot) * lot` (MP plan S2), i.e. it is a function of the **operator-reserved
per-position cap** — a value this repo may never read, restate or assign
(`PROGRESS.md:17-24`, L-39). Validating at one unnamed value would also be a single point on a
curve: if the cap changes, the validation silently expires. **The re-validation must therefore be
parameterised over the qty distribution, not conditioned on the cap**, and must output an envelope
the sizing code can enforce structurally, plus a trigger that invalidates it when its inputs drift.

## 4. Priority, rationale, dependencies, execution order

**Priority: P2.** It is the only work that can clear R-11, and it is fully actionable today: pure
offline computation over synthetic draws under a registered null, no fills required, no live data
(other than a read-only ask-distribution summary), no exposure. It is not P0/P1 because the
capability it unblocks (AUD-06b) is itself correctly gated behind a demonstrated edge that does not
exist.

**Dependency ordering (STAGE 2 — a precondition, never a deliverable):**
- **Depends on:** nothing. Explicitly **not** dependent on AUD-02 (edge) — validating a statistic's
  type-I behaviour is independent of whether the statistic will ever detect anything.
- **Blocks:** AUD-06b (BLOCKER-A there). Its output is consumed by exactly one consumer, as a
  sha-pinned constant plus a staleness predicate.
- **Is inherited by:** AUD-07's `pm_us_crh_exit_v4` boundary package (AUD-07 BLOCKER-3) if this item
  concludes anything about boundary validity beyond qty.

**Execution order:** amendment → reproduce-first → mechanism check → sweep → envelope + staleness
trigger → artefact → xfail disposition.

## 5. Scope and explicit exclusions

**In scope:** Amendment C to the MP plan; the simulation harness extension at
`tests/unit/test_multi_position_validation_2026_09_14.py` and its supporting analysis script; a
read-only summary of the live/tape ask distribution used as the `BE` prior; one dated evidence
artefact; the disposition of the strict `xfail`.

**Explicitly excluded:**
- **No sizing code.** `order_quantity` stays 1; `config.py:253-256` is untouched. That is AUD-06b.
- **No `max_equity_fraction` (R4 pm defect 1 — the specific G-11 element §2 imports into this plan's
  own source finding).** `max_equity_fraction` (declared at `src/breezy/strategy/weather_common/risk.py:186`,
  applied as the equity-notional clip at `:698-699` under a `signed_qty_delta > 0` guard — read from
  source; §2 attributes it to `weather_common/equity.py` following G-11's own wording, but the field
  and its clip live in `risk.py`) is **explicitly out of this item's scope and is not merely covered
  by the generic sizing exclusion above**: its disposition belongs to AUD-06b §12, which records it
  as a **DECISION** — "`max_equity_fraction` … is **NOT adopted as a fourth clamp in this
  increment**", because "its denominator is the UNVERIFIED `currentBalance` semantics (T-4 §4), so
  adding an equity-denominated clamp in the same change that introduces sizing would introduce a new
  failure mode on an unestablished quantity" — with the named re-evaluation trigger that the decision
  re-opens, and a follow-up item is filed, **when AUD-04 publishes its balance-semantics finding**,
  after which "not re-opening it is itself a defect". This item neither adopts, re-litigates nor
  re-decides that disposition; it is recorded here only so a reader checking G-11 element by element
  reads the mapping instead of inferring it.
- **No re-solve of the boundary artefact unless the envelope is empty.** R-11's own instruction:
  re-solve *only if it still fails*. A re-solve changes `boundary_inputs_sha256` and is a
  registration event (L-34) — it is a fallback, not the plan.
- **No change to α, `n_max=160`, `i_max=40`, `look_step=10`, or the H0 variance formula**
  (`MULTI_POSITION_PER_STATION_2026-09-14.md:130-132`; the mixed-side generalisation is
  `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §3). The Monte-Carlo must reproduce the
  registered H0 *exactly* — L-41 names quote-noise-plus-selection as the way this goes wrong, and
  the amendment's own §6 "History note" records that this repo has already published one misspecified
  null and had to supersede it.
- **No deletion or weakening of the strict `xfail`.** It stays STRICT and stays failing until the
  evidence clears it; its disposition (§7 step 7) replaces it with *more* evidence, never less.
- **No reading, restating, defaulting or inferring of either operator cap.** The simulation is
  parameterised on dimensionless qty shape, never on dollars.
- No live data on the decision path, no venue call, no order, no node change.

## 6. Proposed changes grounded in inspected code

**Null hypothesis (L-1).** Nautilus supplies no group-sequential machinery: the LD-OBF boundary,
`score_combined`, `information_fraction`, `look_verdict`/`terminal_look` and the artefact loader are
all Breezy's (`scripts/analysis/family_tally_v2.py:699-807`,
`scripts/analysis/crh_group_sequential_boundaries.py`,
`src/breezy/settlement/current_rung_hold_v2.py`, `src/breezy/persistence/gs_boundary_artefact.py`).
Nothing native is displaced; nothing new is built either — the existing simulation is
re-parameterised.

### Amendment C to `MULTI_POSITION_PER_STATION_2026-09-14.md`

Replaces validation-slice item (ii) (`:133`). New text: item (ii) sweeps the qty distribution,
reports crossing rate as a function of it **and reports the realised information-accrual trajectory
against the artefact's assumed schedule**; Increment B's merge gate becomes "the sizing formula
provably cannot emit a qty outside the validated envelope, and the envelope is not stale", not "the
boundary was re-validated once". Amendment C carries the pinned methodology below in its own text,
so the implementer receives it as a specification rather than a choice.

### Simulation, reusing the registered formulas verbatim

(`MULTI_POSITION_PER_STATION_2026-09-14.md:130-132`, generalised by the NO-side amendment §3):
`X_sd = Σ_i qty_i·(held_i − BE_i)`;
`Var_H0(X_sd) = Σ_i qty_i²·q_i(1−q_i) − 2·Σ_{i<j} qty_i·qty_j·s_i·s_j·q_i·q_j`;
`I = Σ_sd Var_H0(X_sd)`; `S = Σ_sd X_sd / √I`.
The station-day admission gate `Σ_i q_i ≤ 1` is enforced at draw construction, never post-hoc
(`:132`, amendment §4) — a simulation that admits inadmissible station-days measures a different
null. The production `score_combined` / `information_fraction` / artefact loader are IMPORTED, never
reimplemented.

### The mechanism test (R1 MATERIAL fix — this replaces the plan's previous independent hypothesis)

The previous revision proposed "unequal weights lower the effective number of independent draws so
the asymptotic normal approximation degrades at the early looks", and offered "raise the first
look's `n`" as a cheaper remedy. **Both are withdrawn.** The codebase already carries a more
specific, already-measured mechanism (§2), and the proposed remedy does not follow from it: raising
the first look's `n` changes *where the looks land*, not the *rate* at which information accrues per
draw. If variance inflation is what makes realised `t` depart from the solved schedule, an earlier
or later first look still interpolates the boundary at a `t` the solve's grid never covered — it
relocates the undershoot rather than removing it. Carrying that remedy forward would have risked
publishing a treatment the documented cause contradicts.

**Adopted leading hypothesis (the recorded one):** higher qty inflates a station-day's variance (up
to ~9× a single Bernoulli term at qty≤3), so `I` saturates faster than the artefact's
`n_k/n_max = 0.25`-per-draw assumption, and the `reference_table` interpolation at the realised
information fraction undershoots.

**How it is tested, not assumed.** Every swept cell additionally reports:
1. the realised information-fraction trajectory `t_k = I(n_k)/I_max` at each look `n_k ∈ {10,…,160}`;
2. the artefact's **assumed** trajectory at the same looks;
3. the per-look departure `Δt_k = t_k^realised − t_k^assumed`, and the boundary value actually used
   at each look;
4. the per-cell correlation between `max_k |Δt_k|` and the realised crossing rate.

**Confirmation criterion — MACHINE-CHECKABLE (R2 fix; round 2 correctly found the round-1 wording
left the verdict to a reader's judgement on a plot).** The verdict is computed, printed and asserted
by the sweep driver itself, from three conditions that must **all** hold:

1. **Minimum cell count:** at least **24** swept cells contribute to the verdict (the product of the
   axes in "Sweep axes" below comfortably exceeds this; a run producing fewer is `INDETERMINATE`,
   never CONFIRMED). Cells are the unit, not replications.
2. **Monotonicity statistic:** **Spearman rank correlation `ρ ≥ 0.70`** between each cell's
   `max_k |Δt_k|` and its realised crossing rate, with a one-sided permutation p-value `< 0.01`
   (10000 label permutations on the recorded sweep seed sequence). `ρ` and its p-value are both
   printed in Amendment C's table. Rank correlation is used rather than "monotone increasing" so
   near-ties cannot flip the verdict, and so a single noisy cell cannot veto an otherwise clean
   relationship.
3. **Control anchor, with a tolerance rather than "≈ 0":** the qty≡1 control cell has
   `max_k |Δt_k| ≤ 0.01` **and** its crossing-rate Clopper-Pearson upper bound ≤ 0.025 (i.e. the
   control both shows no departure and does not over-cross).

**Refutation — also machine-checkable:** the mechanism is REFUTED if **any** cell with
`max_k |Δt_k| ≤ 0.01` has a crossing-rate Clopper-Pearson **lower** bound above the qty≡1 control's
CP **upper** bound — i.e. a demonstrably over-crossing cell with no measurable departure, separated
by non-overlapping intervals rather than by point estimates. If REFUTED, the recorded mechanism is
wrong, the envelope may be treating a symptom, and **the item stops and reports** rather than
publishing an envelope on a refuted premise. Any outcome that is neither CONFIRMED nor REFUTED is
printed as `INDETERMINATE` — which also stops the item, since an envelope may not be published on an
unestablished premise. All three thresholds (`24`, `ρ ≥ 0.70`, `p < 0.01`, `0.01`) are stated in
Amendment C's own text so two implementers reading the same sweep table reach the same verdict.
Only two remedies are consistent with the confirmed mechanism, and both are reported:
- **(A) the qty envelope** — bound qty so variance inflation keeps realised accrual inside the
  solved schedule's support. Enforceable in sizing code with a local constant. **Preferred.**
- **(B) re-solve the boundary on the realised accrual grid** — changes `boundary_inputs_sha256` and
  is a registration event (L-34). This is R-11's own explicit fallback ("re-solve the artefact only
  if it still fails"), taken only when the envelope is empty.

### Methodology, pinned (R1 fix — no longer left to the implementer)

Stated in Amendment C's own text, not only here:

- **Replications: 20000 per cell.** This is not a new number: it is the replication count of the
  REGISTERED qty≡1 mixed-side study (`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6, Monte-Carlo
  SE 0.001104), so the qty>1 sweep is directly comparable to the study it extends.
- **CI: Clopper-Pearson exact one-sided 95% upper bound** on the crossing rate. Chosen over
  normal-approximation/Wilson because the quantity is a small-count rate evaluated against a safety
  boundary, where the normal approximation's coverage is worst exactly where the decision is made.
  **Stated consequence, so no one is surprised at the table:** at 20000 reps, a cell's CP upper bound
  is ≤ 0.025 only if its observed rate is roughly ≤ 0.0232. A cell whose point estimate is 0.0249
  does NOT enter the envelope. This is intentional — the envelope is a safety boundary, not a
  best-estimate.
- **Seeds:** the R-11 seed family `20260914` for the reproduction cells (so step 1 compares
  like-for-like), and a disjoint, recorded seed sequence `20260921_000 + cell_index` for the sweep,
  so the envelope is not selected on the same noise the blocker was measured on.
- **`Var(S)` tolerance: [0.95, 1.05] per look at 20000 reps.** Grounded: the registered study
  observed [0.98, 1.02] at the same replication count; [0.95,1.05] is a deliberately looser envelope
  than observed and materially tighter than the existing 2000-rep test's [0.85, 1.15]
  (`test_multi_position_validation_2026_09_14.py:156`).

### Sweep axes (dimensionless, seeded)

`q_max ∈ {1,2,3,4,5}`; qty dispersion (three classes, defined below); rungs per
station-day `k ∈ {1,2,3}`; **leg side composition (R2 addition, see below)**; and the `BE`
distribution drawn from the **observed live/tape ask distribution** rather than uniform, because `BE`
enters the variance quadratically and a mis-shaped `BE` prior is exactly the artefact L-41 warns
about.

**Qty dispersion classes, DEFINED (R2 fix — round 2 correctly found "empirical-shaped" named but not
defined, and correctly noted no real qty>1 data exists today since `config.py:255` enforces
`order_quantity must be exactly 1`):**

- **all-equal:** every leg on the station-day carries the same `qty ∈ {1,…,q_max}`.
- **two-point:** half the legs at `qty = 1`, half at `qty = q_max` (the maximum-dispersion case at a
  given `q_max`).
- **cap-shaped (renamed from "empirical-shaped", which promised data that does not exist).** Drawn
  from the *shape* AUD-06b's sizing formula would produce, **without reading either operator-reserved
  cap**, by parameterising over a **dimensionless budget-to-ask ratio** `R`:
  `qty_i = clip(floor(R / ask_i), 1, q_max)`, with `ask_i` drawn from the **same observed live/tape
  ask distribution** the `BE` prior already uses (one source, not two), and `R` swept over
  `{2, 3, 5, 8, 13, 21}` — a stated, recorded, dimensionless grid, **never** a cap value, a cap
  quotient, or anything from which a cap could be reconstructed. This is what makes the axis
  reproducible today; it also gives AUD-06b's pre-merge sweep the cap-free parameterisation it needs
  (AUD-06b §7 step 7a consumes this same `R` grid by reference).

**Leg side composition — a SWEPT AXIS, not a scoped-out assumption (R2 fix).** Round 2 observed that
`_sample_station_day` (`tests/unit/test_multi_position_validation_2026_09_14.py:69-99`) never sets
`side`, so every sampled row defaults to `"yes"` (`current_rung_hold_v2.py:129`) and the envelope
would be validated only on YES-only station-days. The plan takes the reviewer's option **(b), add the
axis**, rather than option (a), scope the envelope to YES-only — because **a YES-only envelope is
anti-conservative for mixed-side days, not conservative**, which the amendment's own closed form shows
directly. In `combine_station_day` (`current_rung_hold_v2.py:344`) the pair term is
`variance -= 2·qty_i·qty_j·s_i·s_j·q_i·q_j` with `signs` built at `:329`: for a YES/YES or NO/NO pair
`s_i s_j = +1` and the term **reduces** variance; for a YES/NO pair `s_i s_j = −1` and it **raises**
it. Since R-11's recorded mechanism is that higher station-day variance makes `I` saturate faster than
the artefact's schedule assumes, a mixed-side day is **strictly more adverse** than an all-YES day at
the same `q` and `qty` — so an envelope validated only on YES-only days could be published as safe and
then applied to the shape that breaks it. The axis is therefore
`side_mix ∈ {all-YES, all-NO, mixed}`, with `mixed` respecting the two live admission gates so no
inadmissible day enters the sweep: the same-rung YES/NO hedge refusal (`_SameRungOppositeSidesRefusal`,
`:237-241`, raised at `:269-273`) and the `Σ q_i > 1` gate (`:331-336`). `Q_MAX_VALIDATED` is published
**per `side_mix`** if the cells differ, and as a single envelope only if the `all-YES` cell is not the
binding one; §8 AC #4 carries this.

### Output: the validated envelope AND its expiry condition

The largest `q_max` (and dispersion class) whose realised one-sided crossing rate at `n_max=160` has
a Clopper-Pearson upper bound ≤ α=0.025. Published as a named constant plus its artefact sha, so
AUD-06b's sizing can clamp to it **without any reference to the operator cap**:
`qty = min(cap-derived qty, Q_MAX_VALIDATED)`.

**Staleness trigger (R1 MATERIAL fix).** The artefact additionally records the `BE` prior's sampled
support: `min`, `p25`, `median`, `p75`, `max` and the IQR of the ask distribution the sweep drew
from, plus the sampling window's dates. The envelope is declared **STALE — and `Q_MAX_VALIDATED`
must not be relied on — when either of two dimensionless conditions holds** over the live ask
distribution of the trailing 14 days:
1. the live median ask falls outside the recorded `[p25, p75]`; or
2. the live IQR exceeds the recorded IQR by more than 50% (or falls below it by more than 33%).

These thresholds are build-side constants, stated in Amendment C, carrying no dollar value and no
operator-reserved quantity. The check is **not a timer** (§9 keeps this item timer-free): it is a
predicate AUD-06b evaluates (a) in its §7 step-0 gate, and (b) before each sized cohort, and it is
**fail-closed** — a stale envelope makes sizing refuse, not warn. The staleness predicate ships as
part of this item's output (a function plus the recorded support), so AUD-06b consumes a checkable
artefact rather than a bare number.

### Compute budget, chunking and resumability (R3 fix — the four-axis grid against a one-heavy-job host)

Round 3 correctly found that adding the `side_mix` axis multiplies the grid without the plan
re-estimating the cost, on a host with a documented history of memory pressure from nightly studies.
Budgeted here rather than discovered at run time.

**Cell count, enumerated (not estimated):** `q_max ∈ {1,2,3,4,5}` = 5; dispersion = **8** sub-cells
(`all-equal` 1 + `two-point` 1 + `cap-shaped` at `R ∈ {2,3,5,8,13,21}` = 6); and `(k, side_mix)` = **8**
ADMISSIBLE pairs, not 9 — `mixed` is undefined at `k = 1` (a one-rung station-day has one side), so the
pairs are `all-YES × {1,2,3}`, `all-NO × {1,2,3}`, `mixed × {2,3}`. **Total = 5 × 8 × 8 = 320 cells**,
at the registered 20000 reps = **6.4 M simulated trial trajectories**. A `mixed × k=1` cell must be
SKIPPED and recorded as `n/a` in the table, never silently sampled as all-YES.

**Wall time is MEASURED, then projected — no invented number.** Step 4a (new, below) runs ONE
reference cell (`q_max=3`, `two-point`, `k=2`, `side_mix=mixed` — mid-grid on every axis and the most
expensive dispersion/side combination per trajectory) at the full 20000 reps, timed, and records
`τ_cell` (wall seconds) and peak RSS. The projected total is `320 × τ_cell` plus the reproduction
cells, published in the artefact beside the measurement. **Budget gate:** if the projection exceeds
**6 wall-hours**, the run is chunked across nights (below) — the replication count is **never**
reduced, because 20000 is the registered study's own count and reducing it would break comparability
with the figure R-11 is measured against.

**Memory is bounded by construction, and asserted.** Each trajectory retains only the current
`ScoreState`, the per-look `t` history (length `n_max / look_step`) and the cell's scalar accumulators
(crossing count, `Δt_k` sums, per-look `Var(S)` sums); **no trajectory, draw list or per-rep record is
retained after the rep closes**, so resident memory is O(1) in reps and O(cells completed) in the
results table. RED test: `test_the_sweep_retains_no_per_replication_state` (assert the driver holds no
growing container across reps — the failure mode `replay_driver_memory_grows_unbounded` already cost
this repo a run). The job runs under `breezy-studies.slice` with its existing memory ceiling; **a cell
that trips the ceiling is a defect in the driver, never a reason to raise the cap.**

**Chunked and resumable, so it never occupies the host in one block.** The driver takes
`--cells FROM:TO` over the canonical cell ordering (lexicographic on
`(q_max, dispersion, R_or_none, k, side_mix)`, fixed and recorded, so the index of a cell never moves)
and appends **one JSONL row per completed cell** to `<artefact_dir>/sweep_cells.jsonl` via a single
`open(..., "a")` write per row. A resume reads the completed `cell_index` values and skips them.
**Chunk boundaries cannot change the result:** the seed is already per-cell
(`20260921_000 + cell_index`), so every cell's stream is independent of what ran before it. RED test:
`test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run` — run cells `0:40` then `40:320`,
and assert the assembled table is byte-identical to a single `0:320` run. The final table is assembled
from the JSONL, so a killed run loses at most one cell.

**One heavy job at a time, stated operationally:** the run is launched only in a window where no
nightly study is active, chunked so each chunk fits that window, and it is **not** added to any timer
(§9). Wall time, peak RSS, chunk boundaries, the seed sequence and the code sha are all recorded in the
artefact.

**Threshold provenance, stated explicitly (R3 fix).** The mechanism verdict's `ρ ≥ 0.70` and
permutation `p < 0.01` are **reasoned build-side defaults chosen before the sweep runs, NOT inherited
from any registered study** — unlike the 20000 reps, the Clopper-Pearson construction and the
`[0.95,1.05]` `Var(S)` tolerance, which are all anchored to
`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6's own figures. The artefact header must say so in those
words, so no later reader treats them as registered.

## 7. Ordered verification steps (RED first)

1. **Characterisation, not RED (L-33).** Reproduce the two figures the xfail reason records —
   ~0.012 at qty≡1 and 0.0592/0.058 at mixed qty — at the recorded seed (`20260914`) and recorded
   replication counts (5000 and 2000). **If they do not reproduce, stop and report**: R-11 rests on
   them, and an unreproducible input invalidates the blocker rather than the plan.
2. **RED:**
   - `test_the_crossing_rate_is_reported_per_qty_envelope` (the sweep function does not exist);
   - `test_the_simulated_null_reproduces_the_registered_h0_variance_exactly` — closed-form check of
     `Var_H0(X_sd)` against the §6 formula at k=1 qty=1 and k=2 mixed qty, including a YES/NO pair
     whose cross term is POSITIVE per the amendment §3 sign breakdown. **This is the L-41 guard.**
   - `test_an_inadmissible_station_day_is_refused_at_draw_construction`;
   - `test_the_realised_information_trajectory_is_reported_per_look` (the mechanism instrument);
   - `test_the_envelope_records_the_be_prior_support_and_its_staleness_predicate`;
   - `test_a_be_prior_outside_the_recorded_support_marks_the_envelope_stale` (both conditions);
   - **NEW (R2)** `test_the_sampler_sets_side_and_the_mixed_cell_contains_both_legs` — the sampler
     today never sets `side` (`test_multi_position_validation_2026_09_14.py:69-99`, defaulting to
     `"yes"` per `current_rung_hold_v2.py:129`), so this test is the RED that forces the axis to exist;
   - **NEW (R2)** `test_a_mixed_side_pair_raises_station_day_variance_relative_to_an_all_yes_pair` —
     pins the sign consequence the axis exists for, at equal `q` and `qty`, against
     `combine_station_day:344`;
   - **NEW (R2)** `test_the_mixed_cell_never_samples_an_inadmissible_station_day` — no same-rung
     YES/NO pair (`:237-241`, raised `:269-273`) and no `Σ q_i > 1` day (`:331-336`) enters the sweep;
   - **NEW (R2)** `test_the_cap_shaped_dispersion_reads_no_operator_reserved_value` — the `R` grid is
     a literal dimensionless sequence in Amendment C; assert the sweep code and artefact contain no
     cap read, no currency figure and no cap-derived quotient;
   - **NEW (R3)** `test_the_sweep_retains_no_per_replication_state` — the O(1)-memory guard;
   - **NEW (R3)** `test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run` — cells `0:40`
     then `40:320` versus a single `0:320` run;
   - **NEW (R3)** `test_a_mixed_side_cell_at_k_equals_one_is_skipped_not_sampled_as_all_yes` — the
     inadmissible `(k=1, mixed)` pair is recorded `n/a`, never silently degraded;
   - **NEW (R2)** `test_the_mechanism_verdict_is_computed_not_eyeballed` — the driver emits
     `CONFIRMED`/`REFUTED`/`INDETERMINATE` with `ρ`, its permutation p-value and the cell count, and
     the same table always yields the same verdict.
3. **GREEN:** implement the sweep in the existing validation module; reuse `score_combined` /
   `information_fraction` / the artefact loader — never a second implementation of the statistic.
4. **Mechanism check FIRST, envelope second.** Run the `Δt_k` instrumentation across the sweep grid
   and evaluate the machine-checkable confirmation/refutation criterion in §6 — the driver computes
   and prints the verdict, the Spearman `ρ`, its permutation p-value and the contributing cell count;
   no reader judges a plot. **If the mechanism is REFUTED *or* `INDETERMINATE`, stop and report**; do
   not publish an envelope derived on an unestablished premise.
4a. **(R3) CALIBRATION BEFORE THE FULL RUN.** Run the single reference cell (`q_max=3`, `two-point`,
   `k=2`, `side_mix=mixed`) at 20000 reps, timed, recording `τ_cell` and peak RSS; publish
   `320 × τ_cell` as the projected total. **If the projection exceeds 6 wall-hours, chunk** per §6's
   compute-budget subsection — never reduce the replication count. If peak RSS approaches the
   `breezy-studies.slice` ceiling, fix the driver's retention before running the grid.
5. **Run** the full sweep under `breezy-studies.slice` discipline in a quiet window (one heavy job at
   a time; the host has been memory-pressured by nightly studies before), **chunked via `--cells
   FROM:TO` with per-cell JSONL append so a killed run loses at most one cell and a resume skips
   completed cells**. Record wall time per chunk, peak RSS, chunk boundaries, seeds and the code sha.
6. **Publish** `docs/evidence/RULING_r11_qty_envelope_2026-09-__.md`: the sweep table (per cell:
   replications, observed rate, Clopper-Pearson upper bound, `max_k |Δt_k|`, per-look `Var(S)`), the
   mechanism verdict, the envelope, the recorded `BE`-prior support and staleness thresholds, the
   remedy (A) vs (B) disposition, and an explicit statement that α, `n_max`, `i_max`, `look_step` and
   `boundary_inputs_sha256` are UNCHANGED.
7. **Dispose of the strict `xfail`** in `test_multi_position_validation_2026_09_14.py`. It stays
   STRICT throughout and is replaced only by evidence: it becomes (i) a passing test **bounded by the
   envelope** (mixed qty *within* the envelope does not over-cross) plus (ii) a second **strict**
   `xfail` pinning that mixed qty *outside* the envelope still does. If the envelope is empty, the
   original strict `xfail` stays exactly as it is, with its reason extended by this item's artefact
   reference. **Deleting the xfail without replacing its evidence is prohibited.**
8. `scripts/ci/run_tests_no_egress.sh` + `lint-imports`.

## 8. Measurable acceptance criteria and required evidence

1. R-11's figures reproduce at the recorded seed and replication counts, or the failure to reproduce
   is the reported result.
2. A sweep table exists with, per `(q_max, dispersion, k, side_mix)` cell (**R2: `side_mix` added**):
   replications (20000), realised one-sided crossing rate at `n_max=160`, its **Clopper-Pearson
   one-sided 95% upper bound**, `max_k |Δt_k|`, and per-look `Var(S)`. The `cap-shaped` dispersion
   rows additionally record their dimensionless `R` value.
3. **The mechanism verdict is COMPUTED and stated** (`CONFIRMED` / `REFUTED` / `INDETERMINATE`)
   against §6's machine-checkable criterion, printed with the Spearman `ρ`, its permutation p-value
   and the contributing cell count, so the verdict is reproducible from the table alone rather than
   read off a plot. A `REFUTED` **or** `INDETERMINATE` verdict stops the item at step 4 and is a
   complete, legitimate outcome.
4. **An envelope is published — whatever it is.** No threshold is asserted in advance: the previous
   revision's `q_max ≥ 2` requirement is removed as unjustified. `q_max = 1` (i.e. no qty above 1
   validates) is a legitimate published result, in which case R-11 resolves to "sizing above qty 1
   requires a re-solve (remedy B)" and AUD-06b is **re-scoped, not quietly proceeded with**.
   **(R2) The envelope states the `side_mix` it is validated for.** If the `mixed` cell binds tighter
   than `all-YES`, `Q_MAX_VALIDATED` is published **per `side_mix`** and the consumer (AUD-06b) must
   apply the value matching the station-day it is sizing; a single scalar envelope may be published
   only when `all-YES` is not the binding cell. Publishing a YES-only-validated scalar and applying it
   to mixed-side days is explicitly prohibited — by the §6 sign argument that is anti-conservative,
   not conservative.
5. `Var(S)` within [0.95, 1.05] at every look in every swept cell, or the departing cells are named
   and excluded from the envelope.
6. The artefact records the `BE`-prior support, the two staleness conditions, and ships the
   staleness predicate AUD-06b consumes; a test proves a drifted prior marks the envelope stale.
7. α, `n_max`, `i_max`, `look_step`, `boundary_inputs_sha256` provably unchanged — asserted by a
   test, not by inspection (`test_the_boundary_inputs_sha256_is_unchanged` already exists at
   `:202`).
8. RED→GREEN output plus the xfail disposition diff, showing the xfail remained STRICT throughout.

9. **(R3) The compute budget is measured, published and respected.** The artefact records `τ_cell`
   from the step-4a calibration, the projected `320 × τ_cell` total, the actual wall time per chunk,
   peak RSS, the chunk boundaries and the per-cell seed sequence. The replication count is **20000 in
   every cell** — a reduced count anywhere fails this criterion regardless of the time saved.
   `test_the_sweep_retains_no_per_replication_state` and
   `test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run` are green, and the table
   contains exactly 320 rows of which the `(k=1, mixed)` combinations are absent by construction
   (proven by `test_a_mixed_side_cell_at_k_equals_one_is_skipped_not_sampled_as_all_yes`).
10. **(R3) Threshold provenance is stated, not implied.** The artefact header says in those words that
   `ρ ≥ 0.70` and permutation `p < 0.01` are reasoned build-side defaults fixed before the sweep ran
   and are NOT inherited from a registered study, while 20000 reps, the Clopper-Pearson construction
   and the `[0.95,1.05]` `Var(S)` tolerance ARE anchored to the amendment's §6 figures.

## 9. Validation: failure cases, integration, autonomous operation

- **The simulation drifts from the registered H0** — the single most dangerous failure, and exactly
  L-41. This repo has already published one misspecified null and superseded it (amendment §6
  "History note"). Guarded by the step-2 closed-form variance test (including the mixed-side positive
  cross term) and by importing the production `score_combined` rather than reimplementing it.
- **The recorded mechanism is wrong.** Detected, not assumed, by step 4's refutation criterion; the
  item stops rather than publishing a treatment for a symptom.
- **Envelope empty.** Reported honestly; `q_max = 1` remains and AUD-06b degenerates to "no sizing
  change" or to remedy (B)'s re-solve, which is a legitimate outcome, not a failure of this item.
- **Envelope derived on the wrong `BE` prior.** Mitigated at publication by drawing `BE` from the
  observed ask distribution and reporting sensitivity to that choice, and mitigated *over time* by
  the staleness trigger, which is fail-closed at the consumer: a stale envelope makes AUD-06b's
  sizing refuse, not warn. An envelope that flips under a plausible alternative prior is reported as
  fragile and is **not** published as validated.
- **Integration:** the envelope constant and its staleness predicate are consumed only by AUD-06b,
  which re-checks both at its own gate. If AUD-06b never ships, this artefact still retires R-11 as a
  question.
- **Autonomous operation:** none required — this is a one-shot offline study, not a running
  capability. **It must not be added to any timer.** Its artefact carries the seeds, the replication
  count and the code sha so it is reproducible rather than re-runnable-on-schedule. The staleness
  trigger deliberately lives at the consumer's gate rather than on a timer, so no unattended surface
  is created here.

## 10. Deployment, observability, rollback

- **Deploy:** nothing is deployed. The change is a plan amendment, test-suite changes and a
  committed evidence artefact. No unit, no node, no behaviour change.
- **Observability:** the artefact is the observable.
- **Rollback:** revert the commit. Because no production constant changes, rollback has no runtime
  consequence whatsoever.

## 11. Relationship to portfolio-level ROI and how it is evaluated

**Channel: enabling and protective. This item contributes ZERO ROI by itself and must never be
presented as contributing any.**

**The path, stated concretely.** Fixed `qty = 1` caps every possible ROI at one contract per
opportunity. This item is the statistical precondition for lifting that cap. The ROI it enables is
realised (if at all) by AUD-06b and measured exclusively through AUD-04's
`realised_pnl_after_fees_total` / `capital_deployed_total` over matched periods against AUD-04's B0
and B1 baselines. **No number produced by this item appears in any ROI statement.**

**Plausible vs demonstrated, separated explicitly:**

| Claim | Status |
|---|---|
| "A validated envelope permits qty > 1, which multiplies whatever edge exists" | **PLAUSIBLE.** Conditional on an edge existing, which today it does not (AUD-02; forecast programme TERMINAL). |
| "This item clears R-11 with a reproducible artefact" | **DEMONSTRATED on delivery**, and it is the only thing this item claims. |
| "Lifting qty improves ROI" | **NOT CLAIMED. Not evaluated here.** If the edge is negative, a larger qty makes ROI worse, which is precisely why AUD-06b carries BLOCKER-B. |

**Baseline.** The explicit baseline is the recorded blocker state: crossing rate ~0.059 at mixed qty
vs α=0.025, `q_max` validated = 1, R-11 open. The post-change comparison is against exactly those
figures.

**How it is evaluated.** Binary and epistemic: does R-11 leave the rulings queue with a reproducible
artefact behind it, and is the envelope accompanied by a staleness predicate a consumer can check?
A published envelope of `q_max = 1` scores as full success.

**Falsifier.** If an envelope is published while the mechanism is refuted, or without its
`BE`-prior support and staleness predicate, the item has failed even though a number exists —
because AUD-06b would then be clamping to a constant nobody can tell is still valid.

**Dependency ordering.** Stage 2. Depends on nothing; blocks AUD-06b (BLOCKER-A there); inherited by
AUD-07's boundary package (AUD-07 BLOCKER-3).

## 12. Assumptions, unresolved questions, blockers

- **Assumption (load-bearing):** the existing validation harness can be re-parameterised rather than
  rewritten. If it cannot, sizing grows materially — re-estimate at step 3 and report.
- **Assumption:** the ~0.059 figure is a type-I over-spend and not a harness defect. Step 1 tests it
  against the seeds and replication counts the xfail reason itself records.
- **Withdrawn (round 1):** the "raise the first look's `n`" remedy and the small-sample
  normal-approximation hypothesis behind it. Both are inconsistent with the recorded mechanism (§6)
  and are no longer carried. Only remedies (A) envelope and (B) re-solve are evaluated.
- **Build-side decision, recorded:** remedy (A) is preferred over (B) because it is enforceable in
  sizing code with a local constant, whereas (B) touches the registered spending schedule and is a
  re-registration event (L-34). (B) is taken only when (A)'s envelope is empty, exactly as R-11
  instructs.
- **Build-side constants, stated not escalated:** 20000 replications, Clopper-Pearson one-sided 95%,
  `Var(S) ∈ [0.95,1.05]`, and the two staleness thresholds (median outside `[p25,p75]`; IQR ±50%/
  −33%). Each is dimensionless, none is an operator-reserved value, and each is grounded in §6.
- **Blockers: none.** No operator input is required and none may be sought: the item is
  deliberately constructed so that no operator-reserved value enters the analysis. R-11 is a
  strategy-lead question this artefact is designed to *answer*, not to escalate.
- **Named risk:** an implementer reading "re-validate at the real qty distribution" literally and
  reaching for the operator cap. §5's exclusion and §3's argument exist to foreclose that.

## 13. Review history

**Baseline self-score (2026-09-21, author), 76/100** — carried-forward weaknesses folded into the
Revision 2 table below.

### Round 1 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 70/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 75/100 |

**Dispositions:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | mle | MATERIAL — the plan's diagnosis hypothesis does not engage with the mechanistic diagnosis the codebase already carries | **ACCEPTED IN FULL; this was the plan's worst defect.** Verified against `tests/unit/test_multi_position_validation_2026_09_14.py:163-179`: the xfail reason does record a specific, measured mechanism (variance inflation → `I` saturates faster than the artefact's `n_k/n_max=0.25`-per-draw schedule → realised-`t` boundary interpolation undershoots), and the plan's independent "early-look normal approximation" hypothesis neither cited nor reconciled with it. §2 now quotes the recorded mechanism verbatim as the source finding; §6 adopts it as the leading hypothesis; the reviewer's option (b) is taken — **"raise the first look's `n`" is WITHDRAWN**, with the reason stated: it relocates where looks land, not the per-draw accrual rate, so it relocates the undershoot rather than removing it. §6 adds a direct mechanism instrument (`Δt_k` per look, its correlation with the crossing rate) with explicit CONFIRM/REFUTE criteria, and §7 step 4 **stops the item** if the mechanism is refuted rather than publishing an envelope on a refuted premise. Only the two mechanism-consistent remedies (envelope; re-solve) survive. |
| 2 | mle (MATERIAL) + pm (MINOR) | No re-validation trigger for the published envelope once it can go stale | **ACCEPTED.** §6 "Staleness trigger" records the `BE` prior's sampled support (min/p25/median/p75/max/IQR + window) in the artefact and defines two dimensionless expiry conditions (live median outside `[p25,p75]`; live IQR +50%/−33%). Critically it is **fail-closed at the consumer**: a stale envelope makes AUD-06b's sizing REFUSE, not warn — stronger than the "WARN" both reviewers suggested. It is a predicate evaluated at AUD-06b's gate and before each cohort, not a timer, preserving §9's no-autonomy stance. Shipped as a function plus recorded support so the consumer checks an artefact, not a bare number. Two tests in §7 step 2; AC #6. |
| 3 | pm (MINOR) + mle | CI method and replication count unspecified | **ACCEPTED, and grounded rather than invented.** §6 "Methodology, pinned": **20000 reps** — not a new number, it is the replication count of the REGISTERED qty≡1 mixed-side study (`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6, MC SE 0.001104), making this sweep directly comparable to the study it extends. **Clopper-Pearson exact one-sided 95% upper**, as the pm reviewer recommended, with the consequence stated explicitly (a cell needs an observed rate ≈ ≤0.0232 at 20000 reps to enter the envelope). Seeds split: R-11's `20260914` for reproduction, a disjoint `20260921_*` sequence for the sweep so the envelope is not selected on the blocker's own noise. All three live in Amendment C's text, not just this plan. |
| 4 | both | `Var(S) ≈ 1` tolerance unpinned | **ACCEPTED.** [0.95, 1.05] per look at 20000 reps, grounded in the registered study's observed [0.98, 1.02] at the same replication count and tighter than the existing 2000-rep test's [0.85, 1.15] (`:156`). AC #5. |
| 5 | both | AC #3's `q_max ≥ 2` threshold asserted without justification | **ACCEPTED by REMOVAL, not by justification.** No threshold can be justified before the sweep runs; asserting one invites selecting the methodology to clear it. AC #4 now requires only that an envelope be published, with `q_max = 1` an explicitly legitimate result that re-scopes AUD-06b to remedy (B). |
| 6 | (brief) | The strict xfail must stay strict until evidence clears it | **ACCEPTED and hardened.** §5 adds an explicit exclusion; §7 step 7 keeps it STRICT throughout, replaces it only with *more* evidence (a bounded passing test plus a second strict xfail outside the envelope), and leaves it untouched if the envelope is empty. AC #8 requires the diff to show it remained strict. |
| 7 | both | "Portfolio objective alignment" 5/10 — "downstream of an edge that does not exist" | **ACCEPTED in cause, REJECTED as a reason to overstate value.** The cause was that §11 asserted "enabling, not contributing" without an evaluation path. §11 now gives the concrete path (enables AUD-06b, measured only through AUD-04's named fields against B0/B1), a three-row plausible-vs-demonstrated table that explicitly declines the ROI claim, a numeric baseline (0.059 vs α=0.025, `q_max`=1, R-11 open), an evaluation rule (binary/epistemic), a falsifier and the dependency stage. The item's genuine zero-ROI contribution is **restated, not softened**. |

**Rejections:** one substantive — the previously proposed "raise the first look's `n`" remedy and its underlying hypothesis are rejected (withdrawn from the plan) as inconsistent with the mechanism recorded in the xfail reason. `q_max ≥ 2` is rejected as an acceptance threshold for the same class of reason: it presupposes the answer.

**Revision 2 self-score (2026-09-21, author), 87/100:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Squarely addresses G-11's blocker, updates the MP plan rather than duplicating it, and now tests the recorded mechanism rather than an invented one. Still loses points because G-11 also names `max_equity_fraction` being unused by the live family, which this item does not touch (deferred to AUD-06b). |
| Technical correctness and evidence grounding | 20 | 18 | The diagnosis is now the codebase's own recorded, measured mechanism, quoted verbatim, with an instrument that can REFUTE it; the registered H0 formulas are quoted from both the MP plan and the NO-side amendment; methodology is inherited from a REGISTERED study rather than invented. Loses points because the mechanism remains a hypothesis until step 4 runs — correctly, but it means the item's central analytical claim is still open at plan time. |
| Implementation specificity and feasibility | 15 | 14 | Replications, CI construction, seeds, `Var(S)` tolerance, sweep axes, the `Δt_k` instrument and the staleness thresholds are all pinned in Amendment C's own text. Loses a point because the "empirical-shaped" qty dispersion class is described rather than defined, so the implementer still chooses its exact shape. |
| Acceptance criteria and validation quality | 20 | 18 | Reproduce-first gate, a stop-and-report refutation branch, an honest empty-envelope branch, and no pre-asserted threshold. Loses points because AC #1's reproduction depends on harness behaviour unchanged since 09-14; if the harness drifted, step 1 consumes the item's budget before any sweep runs. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Correctly forbids a timer, and the staleness gap is closed with a fail-closed consumer-side predicate rather than a warning. Loses points because the staleness check depends on AUD-06b actually evaluating it — this item ships the predicate but cannot enforce its use, which is why AUD-06b carries a matching gate test. |
| Portfolio objective alignment, scope, dependencies | 10 | 7 | §11 now separates plausible from demonstrated in a table that explicitly declines the ROI claim, names the evaluation channel (AUD-04 fields), the baseline, a falsifier and the dependency stage. Still mid-range because the work is genuinely downstream of an edge that does not exist, and this revision does not pretend otherwise. |

### Round 2 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 92/100 |
| mle-reviewer (statistical validation / measurement engineering) | 87/100 |

**Round-2 readiness is the LOWER of the two: 87/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MINOR | The step-2 closed-form guard asserts a YES/NO mixed-side property the sweep itself never exercises; `_sample_station_day` never sets `side`, so the envelope would be validated only on YES-only station-days while AUD-05/AUD-07's family can now produce mixed-side ones. Reviewer offered (a) scope to YES-only, or (b) add a `side` axis | **ACCEPTED, taking option (b) — and the choice is forced by evidence, not preference.** Re-verified: `_sample_station_day` (`tests/unit/test_multi_position_validation_2026_09_14.py:69-99`) sets no `side`, and `StratumRow.side` defaults to `"yes"` (`current_rung_hold_v2.py:129`), so the reviewer's premise is exactly right. Option (a) is **rejected with a source argument**: a YES-only envelope is *anti*-conservative for mixed-side days, not conservative. In `combine_station_day` the pair term is `variance -= 2·qty_i·qty_j·s_i·s_j·q_i·q_j` (`:344`, `signs` at `:329`): a YES/YES or NO/NO pair has `s_i s_j = +1` and **reduces** variance, a YES/NO pair has `s_i s_j = −1` and **raises** it. Since R-11's recorded mechanism is that higher station-day variance saturates `I` faster than the artefact's schedule assumes, a mixed-side day is strictly more adverse at the same `q` and `qty` — an envelope validated only on YES-only days could be published as safe and then applied to the shape that breaks it. §6 therefore adds `side_mix ∈ {all-YES, all-NO, mixed}` as a fourth swept axis, with the `mixed` cell respecting the two live admission gates (`_SameRungOppositeSidesRefusal` `:237-241`/`:269-273`; `Σ q_i > 1` `:331-336`) so no inadmissible day enters the sweep. AC #2 adds `side_mix` to the table key; AC #4 requires the envelope to state the `side_mix` it is validated for and, if `mixed` binds tighter, to publish **per `side_mix`** — publishing a YES-only scalar and applying it to mixed days is prohibited. Four new tests in §7 step 2. |
| 2 | pm + mle | MINOR (both) | The "empirical-shaped" qty dispersion class is named but not defined, and no empirical qty>1 data exists today (`config.py:255` enforces `order_quantity must be exactly 1`) | **ACCEPTED.** The class is **renamed `cap-shaped`** — "empirical-shaped" promised data that does not exist — and defined exactly: `qty_i = clip(floor(R / ask_i), 1, q_max)` with `ask_i` drawn from the **same observed live/tape ask distribution the `BE` prior already uses** (one source, not two), and `R` a **dimensionless budget-to-ask ratio** swept over the literal grid `{2, 3, 5, 8, 13, 21}`. This is the pm reviewer's own suggested construction, adopted verbatim in substance: it reproduces the shape AUD-06b's sizing formula would produce **without reading either operator-reserved cap**, and records no cap value, cap quotient, or anything a cap could be reconstructed from. A new test (`test_the_cap_shaped_dispersion_reads_no_operator_reserved_value`) asserts that property. The same `R` grid is exported by reference to resolve AUD-06b's pre-merge sweep parameterisation. The other two classes (`all-equal`, `two-point`) are also stated explicitly rather than left to their names. |
| 3 | pm | MINOR | The mechanism CONFIRM/REFUTE criterion is "monotone increasing across cells" with no minimum cell count, no near-tie tolerance and no statistic, so two implementers could reach opposite verdicts on the same table — while AC #3 makes that verdict gate whether an envelope is published at all | **ACCEPTED.** §6's criterion is replaced by a machine-checkable one, stated in Amendment C's own text: **(1)** ≥ **24** contributing cells or the verdict is `INDETERMINATE`; **(2)** **Spearman `ρ ≥ 0.70`** between `max_k |Δt_k|` and the realised crossing rate with a one-sided permutation p-value `< 0.01` over 10000 label permutations on the recorded seed sequence — rank correlation specifically so near-ties cannot flip the verdict and one noisy cell cannot veto a clean relationship; **(3)** the qty≡1 control anchored with a tolerance (`max_k |Δt_k| ≤ 0.01` **and** CP upper ≤ 0.025) rather than "≈ 0". **Refutation is equally mechanical:** any cell with `max_k |Δt_k| ≤ 0.01` whose crossing-rate CP **lower** bound exceeds the control's CP **upper** bound — non-overlapping intervals, not point estimates. A third outcome, `INDETERMINATE`, is introduced and **also stops the item**, closing the gap where neither condition held. §7 step 4 and AC #3 restated; `test_the_mechanism_verdict_is_computed_not_eyeballed` added. |
| 4 | mle | scoring note | Portfolio alignment 7/10 attributed to "the structural ceiling this criterion imposes on enabling-only work", with **no named defect** ("I find no remaining defect to name here") | **RECORDED, no change made — round 3 must justify or award.** The prediction-market reviewer scored the same §11, unchanged, at **10/10**, stating full marks apply because no operator ruling is needed and the table explicitly declines the ROI claim. A deduction with no named defect and no requested change is not actionable. If round 3 deducts here it must name a concrete gap; otherwise the points should be awarded. |

**Rejections:** one sub-option, with evidence — the mle reviewer's option (a) ("scope the envelope to YES-only and defer mixed-side to a follow-up") is rejected because the amendment's own closed form makes a YES-only envelope anti-conservative for the population it would be applied to; the underlying defect is accepted in full and remedied by adding the axis instead. No scope was removed and no acceptance criterion softened — AC #2, #3 and #4 were each tightened. No operator-reserved value is read, restated, defaulted or assigned anywhere in this revision, and the new `cap-shaped` axis is specifically constructed to keep that true.

**Revision 3 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-2 total:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | R-11/G-11's blocker squarely addressed against the codebase's own recorded mechanism, now over the station-day shapes the envelope will actually be applied to. Unchanged shortfall: G-11 also names `max_equity_fraction` being unused, correctly deferred to AUD-06b but genuinely outside this item's coverage. |
| Technical correctness and evidence grounding | 20 | 18 | The xfail mechanism quote, the registered rep count/SE, the CP arithmetic and the `Var(S)` bounds all survived two independent re-verifications; the R2 side-axis argument is grounded in the sign of `combine_station_day:344`/`:329` rather than asserted. Does not claim more: the mechanism itself remains a hypothesis until step 4 runs, and the `cap-shaped` `R` grid is a chosen span, not an observed one. |
| Implementation specificity and feasibility | 15 | 13 | Reps, CI, seeds, tolerance, staleness thresholds, all three dispersion classes, the `side_mix` axis and the verdict statistic are now pinned in Amendment C's own text. Loses points because adding `side_mix` multiplies the sweep grid threefold and the plan does not re-estimate the wall-time budget for a host that has been memory-pressured by nightly studies before. |
| Acceptance criteria and validation quality | 20 | 18 | Reproduce-first gate, a computed verdict with a third `INDETERMINATE` outcome that also stops the item, an honest empty-envelope branch, no pre-asserted threshold, and a per-`side_mix` publication rule. Loses points because the `ρ ≥ 0.70` and `p < 0.01` thresholds are reasoned defaults, not values inherited from a registered study. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Correctly forbids a timer; the staleness predicate is fail-closed at the one real consumer. Unchanged weakness: this item ships the predicate but cannot itself enforce that AUD-06b evaluates it — an interface risk named in §12. |
| Portfolio objective alignment, scope, dependencies | 10 | 7 | §11 gives the enabling chain, a numeric baseline, a falsifier and an explicit decline of the ROI claim. Held at the lower reviewer's mark pending round 3 naming a defect or awarding the points (disposition #4). |

### Round 3 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 94/100 |
| mle-reviewer (statistical validation / measurement engineering) | 90/100 |

**Round-3 readiness is the LOWER of the two: 90/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm (required change 1), echoed by mle as a self-conceded weakness | MINOR | The fourth axis multiplies the grid and the plan does not re-estimate wall time or memory for a host with documented memory pressure from nightly studies | **ACCEPTED in full.** §6 gains a **compute budget** subsection that (a) **enumerates** the grid rather than estimating it — `5 q_max × 8 dispersion sub-cells × 8 ADMISSIBLE (k, side_mix) pairs = 320 cells`, correcting 9 to 8 because `mixed` is undefined at `k = 1` and must be skipped, not silently sampled as all-YES; (b) refuses to invent a wall-time number and instead adds **step 4a**, a timed single-cell calibration at the reference cell (`q_max=3`, `two-point`, `k=2`, `mixed`) that publishes `τ_cell`, peak RSS and the projected `320 × τ_cell`, with a **6-wall-hour gate** that triggers chunking and **never** a reduced replication count (20000 is the registered study's own figure); (c) bounds memory **by construction** — only scalar accumulators and the `t` history survive a rep — with `test_the_sweep_retains_no_per_replication_state` as the guard and an explicit rule that a cell tripping the `breezy-studies.slice` ceiling is a driver defect, never a reason to raise the cap; (d) makes the run **chunked and resumable** via `--cells FROM:TO` over a fixed canonical cell ordering with one JSONL row appended per completed cell, so a killed run loses at most one cell — and because the seed is already per-cell (`20260921_000 + cell_index`), chunk boundaries cannot change the result, asserted by `test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run`. New AC #9 requires the measured budget and the full 320-row table as evidence. |
| 2 | pm (required change 2), echoed by mle | MINOR | State the `ρ ≥ 0.70` / permutation-`p` thresholds' provenance explicitly as "reasoned, not inherited" | **ACCEPTED.** §6's compute-budget subsection states it in those words and contrasts it with the three quantities that ARE anchored to `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6 (20000 reps, Clopper-Pearson, the `[0.95,1.05]` `Var(S)` tolerance). New AC #10 requires the artefact header to carry the statement. |
| 3 | mle | none found | "I looked specifically for a fresh defect this round ... I did not find one"; the `side_mix` axis, the `cap-shaped` definition and the machine-checkable monotonicity criterion are all confirmed correctly implemented, and the xfail reason matches every cited figure word for word | **NOTED, no change.** |
| 4 | pm | observation, explicitly not scored | AUD-06a's artefact must be re-read fresh by AUD-06b on every sizing decision rather than cached at boot — arguably AUD-06b's responsibility, and AUD-06b's G1 does specify a fail-closed `envelope_is_stale` check | **NOTED, no change here.** The reviewer scores it as not a deduction against this item; AUD-06b already owns and specifies the fail-closed staleness read, and duplicating the requirement in this plan would create a second specification of the kind round 3 penalised elsewhere in this batch. |
| 5 | both | scoring note | §11 awarded 10/10 by both reviewers with no named defect, resolving round-2 disposition #4 | **RESOLVED and awarded** — the revision-4 self-score holds this criterion at 10/10. |

**Rejections:** none. **No scope was removed and no criterion softened** — the budget gate explicitly forbids buying wall time by cutting replications, and the `(k=1, mixed)` correction removes cells that were never admissible rather than trimming the grid for cost. No operator-reserved value enters the analysis anywhere in this revision.

**Points withheld in round 3 without a named defect or requested change — round 4 must justify or award:**

- **mle, "Fidelity" 18/20, "Technical correctness" 18/20, "Acceptance criteria" 18/20, "Autonomous operation" 13/15.** All four recorded as "matches round 2/3 self-score" alongside an explicit "no new defect found" and "Required changes to reach 100: None found this round". The two weaknesses the record does name (wall-time re-budgeting; threshold provenance) are both closed by this revision, so the deductions have no surviving basis.
- **pm, "Technical correctness" 19/20.** The −1 is attributed to the mechanism remaining a hypothesis until step 4 runs — which is a property of an unexecuted study, correctly deferred, with no requested change.
- **pm, "Autonomous operation" 14/15.** The −1 is for this item being unable to enforce that AUD-06b evaluates its staleness predicate, which the same record calls "the right disposition" and declines to ask to be changed.

**Revision 4 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-3 total (90):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 18 | R-11 is addressed against the codebase's own recorded mechanism, over the station-day shapes the envelope will actually be applied to, and the grid is now enumerated rather than estimated. Loses points because `max_equity_fraction`, also named in G-11, is deferred to AUD-06b. |
| Technical correctness and evidence grounding | 20 | 18 | Every formula, line number and sign argument holds on re-verification; the `(k=1, mixed)` inadmissibility is a correctness fix, not a cost trim; the reps/CI/tolerance remain anchored to the amendment's own figures while the two reasoned thresholds are now labelled as such. Loses points because the mechanism itself is a hypothesis until step 4 runs, and `τ_cell` is a measurement this plan schedules rather than reports. |
| Implementation specificity and feasibility | 15 | 14 | Reps, CI, seeds, tolerance, all three dispersion classes, the `side_mix` axis, the verdict statistic, and now the cell ordering, chunk interface, JSONL resume protocol and memory contract are all pinned. Loses a point because the wall-time projection cannot exist until step 4a runs, so the chunk plan is conditional by construction. |
| Acceptance criteria and validation quality | 20 | 18 | Reproduce-first gate, a computed three-outcome verdict that also stops the item, an honest empty-envelope branch, a `side_mix`-aware publication rule, and now a measured-budget criterion and a threshold-provenance criterion. Loses points because AC #9's budget figures are produced by the run itself rather than checkable beforehand. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Correctly forbids a timer; the staleness predicate is fail-closed at its one real consumer; the run is now resumable so a host kill costs one cell rather than the sweep. Loses a point because this item still cannot enforce that AUD-06b evaluates the predicate every cycle. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11's enabling chain, numeric baseline, explicit ROI-claim decline and falsifier were awarded 10/10 by both round-3 reviewers with no named defect; no operator-reserved value is read anywhere. |

**Latest score:** 92/100 (Revision 4 self-score); round-3 peer readiness 90/100.
**Readiness: NOT READY — round 4 peer review pending. No blocker requires an operator or strategy-lead ruling: this item is constructed so no operator-reserved value enters the analysis.**

### Round 4 (reconciled) (2026-09-21) — independent blind peer review, with scoring reconciliation

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 99/100 |
| mle-reviewer (statistical validation / measurement engineering) | 100/100 |

**Round-4 readiness is the LOWER of the two: 99/100.** Both records ran a reconciliation pass in
which a deduction stands only if tied to a named defect AND a text-level required change; shortfalls
fixable only by execution, or owned by another item, were awarded back as notes.

**Dispositions (every defect and every note, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm | MINOR (−1 Fidelity) | §5 excludes "sizing code" generically but never names `max_equity_fraction` specifically, nor cites AUD-06b's actual disposition of it — so a reader checking G-11 element by element has to infer the mapping, even though this plan's own §2 imports that element into its source finding | **ACCEPTED in full; the only change of this revision.** §5 gains an explicit exclusion bullet naming `max_equity_fraction` and quoting AUD-06b §12's disposition verbatim: it is a **DECISION** — "**NOT adopted as a fourth clamp in this increment**" because "its denominator is the UNVERIFIED `currentBalance` semantics (T-4 §4)" — with the named re-evaluation trigger that it re-opens, and a follow-up item is filed, **when AUD-04 publishes its balance-semantics finding**, after which "not re-opening it is itself a defect". Source read before writing the claim: the field is declared at `src/breezy/strategy/weather_common/risk.py:186` and applied as the equity-notional clip at `:698-699` under a `signed_qty_delta > 0` guard. The bullet records that §2's `weather_common/equity.py` attribution follows G-11's own wording while the field and its clip actually live in `risk.py`, so the cross-reference is accurate rather than propagating a location this revision could not verify. This item does not adopt, re-litigate or re-decide the disposition — it maps it. **Nothing excluded here is newly removed from scope:** `max_equity_fraction` was already outside this item in every prior revision; only the mapping was implicit. |
| 2 | pm + mle (independently, same conclusion) | reconciled, awarded | "The `Var(S)` mechanism remains a hypothesis until step 4 runs"; "the wall-time projection is conditional on step 4a running"; "AC #9's budget figures are produced by the run itself rather than checkable beforehand" | **NOTED, no change.** All three are properties of an unexecuted calibration study specified before it runs. §6/§7 already name the exact settling test (Spearman `ρ`, permutation `p`, a machine-checkable three-outcome verdict including `INDETERMINATE`) and §7 step 4 treats a refuted mechanism as a **stop condition** rather than papering over it; inventing a wall-time number here would be the defect, not omitting one. Both reviewers awarded these in full. |
| 3 | pm + mle (independently, same conclusion) | reconciled, awarded | "This item cannot enforce that AUD-06b evaluates the staleness predicate every cycle" | **NOTED, no change.** This item ships a fail-closed `envelope_is_stale(...)` predicate; whether the CONSUMER calls it is AUD-06b's scope and is verified there by `test_sizing_refuses_when_the_envelope_is_stale` (independently checked by both reviewers while reviewing that plan). Duplicating the enforcement here would create a second specification of one rule — the single-owner failure this backlog penalises elsewhere (the shared alert ladder). |
| 4 | pm | verification, no defect | The 320-cell grid (`5 q_max × 8 dispersion × 8 admissible (k, side_mix)`, with `(k=1, mixed)` excluded as undefined rather than silently sampled as all-YES), the step-4a `τ_cell` calibration with its 6-wall-hour chunking gate that never reduces the registered 20000 reps, and the explicit "reasoned build-side defaults … NOT inherited" labelling of `ρ ≥ 0.70` / `p < 0.01` were each confirmed present **in the plan body**, not only in §13 | **NOTED, no change.** Both of round 3's required changes are confirmed genuinely implemented. The O(1)-memory guard, the `--cells FROM:TO` byte-identical resume and the per-cell seeding (`20260921_000 + cell_index`) were likewise re-verified by the mle record. |

**Rejections:** none. The mle record additionally re-read the plan hunting for a fresh defect — specifically the monotonicity criterion's power at the minimum 24-cell threshold, the `cap-shaped` dispersion's coverage of the live ask distribution, and the revision-3 compute-budget subsection — and found none beyond what is already disclosed.

**Revision 5 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-4 total (99):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 19 | R-11/G-11's `Var(S)` blocker is addressed against the codebase's own recorded mechanism over the station-day shapes the envelope will actually be applied to, with the grid enumerated rather than estimated, and G-11's `max_equity_fraction` element now explicitly mapped to AUD-06b §12's DECISION rather than left to inference. Holds a point back because that element is still *dispositioned elsewhere* rather than delivered by any item yet — the mapping closes the reader's gap, not the capability gap. |
| Technical correctness and evidence grounding | 20 | 19 | Every formula, line reference and sign argument re-verified across four rounds; the `(k=1, mixed)` exclusion is an admissibility fix, not a cost trim; reps/CI/tolerance stay anchored to the amendment's own registered figures, and the `risk.py:186`/`:698-699` location added this revision was read from source before being written. Holds a point back because the `Var(S)` mechanism is still an unexecuted hypothesis at plan time — honestly disclosed in §6/§9, with a stop condition, but unmeasured. |
| Implementation specificity and feasibility | 15 | 14 | Reps, CI, seeds, tolerance, all three dispersion classes, the `side_mix` axis, the verdict statistic, cell ordering, the chunk interface, the JSONL resume protocol and the memory contract are all pinned, and the wall-time budget is scheduled by a calibration step rather than guessed. Holds a point back because the chunk plan is conditional on `τ_cell` by construction and cannot be checked before step 4a runs. |
| Acceptance criteria and validation quality | 20 | 19 | Reproduce-first gate, a computed three-outcome verdict that also stops the item, an honest empty-envelope branch, a `side_mix`-aware publication rule, a measured-budget criterion (AC #9) and a threshold-provenance criterion (AC #10). Holds a point back because AC #9's figures are produced by the run itself rather than checkable beforehand. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Correctly forbids a standing timer; the staleness predicate is fail-closed and ships tested at its one real consumer; the run is resumable so a host kill costs at most one cell. Holds a point back because this item still cannot compel its consumer to call the predicate — correctly AUD-06b's scope, but a real seam between two items. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11's enabling chain, numeric baseline, explicit decline of any ROI claim and falsifier are concrete; no operator-reserved value enters the analysis anywhere, and the one scope boundary a reviewer found under-mapped is now explicit. |

**Latest score:** 95/100 (Revision 5 self-score); round-4 peer readiness 99/100.
**Readiness: NOT READY — round 5 delta review pending. No blocker requires an operator or strategy-lead ruling for this item's own scope: it is constructed so no operator-reserved value enters the analysis, and R-11 is a strategy-lead question this artefact answers rather than escalates.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `1c55d80b276cdf7f6b16899b9edde4025ac3e436fcc10de66340b302533d9be3`
- **Baseline self-score:** 76/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 5: 100/100 — `reviews/AUD-06a-r5-mle-reviewer.md`
  - `prediction-market-reviewer` round 5: 100/100 — `reviews/AUD-06a-r5-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None.
- **Full review history:** 10 records, `reviews/AUD-06a-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
