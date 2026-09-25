# RULING — R-11 LD-OBF boundary qty-envelope re-validation (AUD-06a)

Status: **VERIFICATION ONLY** — no sizing code, no order, no live data on the decision path.
Clears R-11 (`PROGRESS.md:76`) per `docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md`
(READY, 100/100). Amendment C to `docs/plans/MULTI_POSITION_PER_STATION_2026-09-14.md` (replacing
validation-slice item (ii)).

Code sha (this worktree, `backlog/aud-06a-r11-revalidation-2026-09-24`): see `COMMIT_SHA` in the
implementer return. Registered inputs unchanged: `alpha=0.025`, `n_max=160`, `i_max=40`,
`look_step=10`, `boundary_inputs_sha256=471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c`
(re-asserted by `test_the_boundary_inputs_sha256_is_unchanged`, unchanged in this change).

**Threshold provenance (AC #10), stated explicitly:** `ρ ≥ 0.70` and permutation `p < 0.01` are
REASONED BUILD-SIDE DEFAULTS, fixed before the sweep ran, and are **NOT inherited from any registered
study**. By contrast, **20000 replications/cell**, the **Clopper-Pearson exact one-sided 95%** upper
bound, and the **`Var(S) ∈ [0.95,1.05]`** per-look tolerance **ARE** anchored to
`docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6's registered qty≡1 mixed-side study
(20000 reps, Monte-Carlo SE 0.001104).

## 0. FULL-GRID ADDENDUM (2026-09-25, continuation) — supersedes §3-§6 below where they conflict

**All 320 cells now run and merged** (`docs/evidence/aud06a_sweep_cells.jsonl`, sorted by cell index,
verified index/seed/label against the canonical ordering, zero conflicts, zero gaps): the 33 cells
committed earlier in this item, 287 cells run by the coordinator (cells 33-319, `docs/evidence/
aud06a_sweep_cells.jsonl` sha unchanged in substance for the 25 overlapping indices — byte-verified
identical), and 25 cells (indices 8-32, the missing `two_point`/`cap_shaped R∈{2,3}` q_max=1 baselines)
run by this implementer to close a genuine gap left by the numeric-range assumption in the hand-off
(the committed 33 were a scattered strategic subset — indices 0-7, 64-87, 140 — not the contiguous
range 0-32 the hand-off assumed). 40/320 cells are `skipped` (all `all_no,k=3`, structurally
near-infeasible under the observed ask sample — §4). **280 contributing cells.**

**Amendment C2 (baseline-relative anchor, POST-HOC — see the plan doc's Amendment C2 for the full
justification):** the domain review correctly found the ORIGINAL absolute control anchor
(`max_k|Δt_k|≤0.01`) unsatisfiable because it assumes `BE≈0.5`. C2 pairs each cell against its own
`q_max=1` baseline in the same `(k, side_mix, dispersion, R)` stratum, differencing out that structural
component.

### Verdict under BOTH anchors (never only the favourable one)

| Anchor | ρ | p | n_cells | control_ok | Verdict |
|---|---|---|---|---|---|
| **Original (absolute)** | 0.8704 | 0.0001 | 280 | **False** | **INDETERMINATE** |
| **Amendment C2 (baseline-relative)** | 0.7006 | 0.0001 | 280 | **False** | **INDETERMINATE** |

Monotonicity is strongly satisfied under BOTH anchors (`ρ ≥ 0.70`, `p < 0.01`). Both verdicts are
INDETERMINATE anyway, because **`control_ok` fails under C2 too — for a NEW, distinct, and more
important reason than the one C2 was written to fix.**

### A more important finding than the one this item set out to test

**16 of the 56 `q_max=1` cells already have Clopper-Pearson upper bound > α=0.025 — and EVERY ONE of
those 16 is a `mixed` (YES+NO) side_mix cell** (every `dispersion×k∈{2,3}` combination; e.g.
`q_max=1,all_equal,k=2,mixed`: rate 0.0534, CP-upper 0.0561 — more than double `α`). **Every
non-`mixed` `q_max=1` cell (40/56) passes comfortably** (CP-upper ≤ 0.025, most ≤ 0.02).

**This means the boundary over-crossing is not purely a qty effect. Mixing YES and NO legs on the same
station-day inflates the crossing rate above α even at `qty≡1`** — the crossing-term sign argument
already in Amendment C (`combine_station_day:344`, a YES/NO pair's cross term is positive, raising
variance) is now demonstrated to be severe enough, on its own, to break the boundary's nominal type-I
rate with NO qty involvement at all. Because `control_ok` requires ALL `q_max=1` cells (baselines) to
individually pass, and the `mixed` ones do not, `control_ok=False` under BOTH anchors — the C2 fix
correctly repaired the qty-1-vs-BE-prior confound it was written for, but exposed this qty-independent
one underneath it. **This is reported honestly as INDETERMINATE, not forced to CONFIRMED.**

### Stratum-controlled paired trend (56 strata, full grid) — confirms the reviewer's 33-cell observation

**Every one of the 56 strata shows `q_max=2` crossing well above `α`: 56/56 (100%).** Fold increase
from `q_max=1` to `q_max=2`: min 1.27×, median 4.38×, max 17.95× (largest fold increases are in
`all_no` strata, where the `q_max=1` baseline itself is very low, ~0.003-0.004). At `q_max=3/4/5` the
picture is unanimous too: **56/56 strata over `α` at every `q_max∈{2,3,4,5}` sampled**, CP-upper ranges
`[0.048,0.087]` (q=2), `[0.062,0.099]` (q=3), `[0.070,0.101]` (q=4), `[0.072,0.101]` (q=5). **The
reviewer's 33-cell observation ("q_max 1→2 raised crossing 4-6× to well above α in every sampled
stratum") is CONFIRMED on the full grid**, with a wider fold-increase range than the 33-cell sample
suggested (1.27×-17.95×, not just 4-6×) — `all_no` strata inflate far more sharply than `all_yes` or
`mixed` strata.

### Envelope — raw empirical result, reported plainly, still NOT formally "published"

Per Amendment C, an envelope may not be formally PUBLISHED on an unestablished (non-CONFIRMED)
mechanism premise, and neither anchor reaches CONFIRMED here. **No envelope is formally published.**

**The raw data is nonetheless unambiguous and is reported as an operational finding, not a ruling:**
`q_max_validated` computed directly from the full grid returns `{all_yes: 1, all_no: 1, mixed: 1}` —
**every side_mix caps at `q_max=1`**, with zero exceptions across all 224 cells run at `q_max≥2`. This
is not a borderline result requiring a formal envelope-publication gate to trust operationally: **no
plausible reading of this data supports qty>1 today**, mechanism-verdict formality notwithstanding.

### Operational consequence for AUD-06b / AUD-07 (finding only — no live code, no operator value touched)

1. **AUD-06b (qty>1 sizing): do not proceed.** The full grid shows 100% of sampled `q_max≥2` cells
   over-crossing `α`, in every stratum, with no dispersion class or `k` value found to be an exception.
   Remedy (A) (an envelope) is empty in substance; remedy (B) (re-solve the boundary) would need to
   account for BOTH the qty effect AND the independent mixed-side effect below.
2. **AUD-07 (boundary package) — NEW finding, higher priority than qty:** mixed-side (YES+NO)
   station-days over-cross `α` at `qty≡1` — i.e. **this affects Increment A's already-shipped
   qty≡1 configuration**, not just the qty>1 capability AUD-06b would add. Since AUD-05 (merged,
   `013d654`) made the live tally side-aware, mixed-side station-days can occur in the live system
   TODAY. Whether the live LD-OBF boundary needs recalibration for mixed-side days (independent of
   qty) is a question this item surfaces but does not resolve — it is exactly the "boundary validity
   beyond qty" case Amendment C's §4 dependency line anticipated ("inherited by AUD-07's boundary
   package ... if this item concludes anything about boundary validity beyond qty"). **Recommendation,
   stated as a finding: AUD-07 should treat mixed-side LD-OBF validity as a standalone, qty-independent
   question**, not a sub-case of AUD-06b's qty envelope.
3. **The strict `xfail` stays exactly as it is** (§9) — no envelope was published, so the plan's own
   flip condition never fires.

## 1. Step 1 — reproduction (§7 step 1)

The xfail reason's two figures (`tests/unit/test_multi_position_validation_2026_09_14.py:161-199`)
were re-derived (not byte-identical re-run — a different, amendment-compliant sampler; analytically
the same registered H0):

- **qty≡1 control** (`q_max=1`, `k=1`, `all_yes`, this module's sampler): crossing rate **0.0100** at
  2000 reps (CP-upper 0.0145), **0.0112** at 5000 reps (CP-upper 0.0140) — reproduces the xfail
  reason's recorded "~0.011–0.013" qty≡1 control figure.
- **Mixed qty, k∈{1,2,3}** (existing, UNCHANGED test `test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha`,
  seed 20260914, 2000 reps): still `xfail`s at ~0.058, matching the recorded figure exactly (the test
  and its sampler are byte-unchanged by this item).

**Verdict: REPRODUCES.** R-11's blocker is real, not a harness artefact.

## 2. A material sampler defect found and fixed during this item

While building the sweep's mixed-side sampler, `held` was initially assigned `(i == holder)`
identically for YES and NO legs. This is a genuine H0-drift bug of exactly the class L-41 warns about:
`StratumRow`'s own docstring and `build_stratum_v2`'s "under H0 `E[held_i] = BE_i` on both YES and NO"
require a NO leg's `held` to be `holder != i` (`1{HIGH NOT in r_i}`), not `holder == i`. The unfixed
sampler gave `E[held_i] = q_i = 1-BE_i` for NO legs instead of `BE_i`, which for typically-cheap
observed asks (`BE_i` well below 0.5) biased `X_sd` strongly positive and drove `all_no` cells to a
measured crossing rate of **1.0** — a simulation artefact, not a finding about the registered
statistic. Fixed (`sample_station_day`, `scripts/analysis/aud06a_qty_envelope_sweep.py`) and pinned by
a new regression test, `test_the_no_side_sampler_produces_unbiased_held_under_h0` (single fixed ask,
20000 draws, empirical held-rate within 0.02 of `BE_i`). All sweep cells below were run AFTER this fix.

## 3. Compute budget (§7 step 4a, AC #9)

**Calibration cell** (`q_max=3`, `two_point`, `k=2`, `mixed` — the plan's own reference cell), 20000
reps, `systemd-run --user --scope -p MemoryMax=6G -p CPUQuota=400%`:

- **τ_cell = 59.50 s**
- **peak RSS = 97.8 MB**
- **Projected total for the full 320-cell grid: 320 × 59.50 s ≈ 19,039 s ≈ 5.29 wall-hours** — under
  the plan's 6-hour chunking gate, but far beyond this implementation session's own compute allowance
  (a shared host running a live trading node; this session was capped at 2 wall-hours for the
  simulation by its own operating brief).

**Disposition (stated per the brief's explicit compute-governance clause, not a plan deviation): the
full 320-cell grid was NOT completed in this change.** A bounded, representative subset was run
instead — **33 cells** at the full registered 20000 reps each, chunked and JSONL-appended exactly per
Amendment C's `--cells FROM:TO` protocol (`docs/evidence/aud06a_sweep_cells.jsonl`), so the grid can be
resumed and completed in a later, longer compute window without re-deriving anything already computed
here. This is an **honest partial delivery**, not a claim that AC #9's 320-row requirement is met.

## 4. Cells run (subset — 33 of 320, seeds `20260921_000 + cell_index`, canonical ordering)

| idx | q_max | dispersion | k | side_mix | reps | crossing_rate | CP_upper | CP_lower | max\|Δt_k\| | skipped |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1 | all_equal | 1 | all_yes | 20000 | 0.0089 | 0.0100 | 0.0078 | 0.3650 | no |
| 1 | 1 | all_equal | 1 | all_no | 20000 | 0.0106 | 0.0119 | 0.0095 | 0.3648 | no |
| 2 | 1 | all_equal | 2 | all_yes | 20000 | 0.0146 | 0.0160 | 0.0132 | 0.1959 | no |
| 3 | 1 | all_equal | 2 | all_no | 20000 | 0.0032 | 0.0039 | 0.0026 | 0.5394 | no |
| 4 | 1 | all_equal | 2 | mixed | 20000 | 0.0534 | 0.0561 | 0.0509 | 0.5000 | no |
| 5 | 1 | all_equal | 3 | all_yes | 20000 | 0.0130 | 0.0144 | 0.0117 | 0.2266 | no |
| 6 | 1 | all_equal | 3 | all_no | 0 | n/a | n/a | n/a | n/a | **YES** — structurally near-infeasible: `Σ(1-ask_i)>1` for 3 legs at these observed asks |
| 7 | 1 | all_equal | 3 | mixed | 20000 | 0.0583 | 0.0611 | 0.0556 | 0.6250 | no |
| 64 | 2 | all_equal | 1 | all_yes | 20000 | 0.0583 | 0.0610 | 0.0555 | 0.5775 | no |
| 65 | 2 | all_equal | 1 | all_no | 20000 | 0.0579 | 0.0607 | 0.0552 | 0.5779 | no |
| 66 | 2 | all_equal | 2 | all_yes | 20000 | 0.0565 | 0.0592 | 0.0538 | 0.6875 | no |
| 67 | 2 | all_equal | 2 | all_no | 20000 | 0.0524 | 0.0551 | 0.0498 | 0.4375 | no |
| 68 | 2 | all_equal | 2 | mixed | 20000 | 0.0793 | 0.0825 | 0.0762 | 0.8750 | no |
| 69 | 2 | all_equal | 3 | all_yes | 20000 | 0.0500 | 0.0526 | 0.0475 | 0.6531 | no |
| 70 | 2 | all_equal | 3 | all_no | 0 | n/a | n/a | n/a | n/a | **YES** — same structural cause as idx 6 |
| 71 | 2 | all_equal | 3 | mixed | 20000 | 0.0742 | 0.0773 | 0.0712 | 0.8750 | no |
| 72 | 2 | two_point | 1 | all_yes | 20000 | 0.0591 | 0.0619 | 0.0564 | 0.5774 | no |
| 73 | 2 | two_point | 1 | all_no | 20000 | 0.0553 | 0.0580 | 0.0526 | 0.5777 | no |
| 74 | 2 | two_point | 2 | all_yes | 20000 | 0.0504 | 0.0530 | 0.0479 | 0.5370 | no |
| 75 | 2 | two_point | 2 | all_no | 20000 | 0.0452 | 0.0477 | 0.0429 | 0.4375 | no |
| 76 | 2 | two_point | 2 | mixed | 20000 | 0.0722 | 0.0753 | 0.0693 | 0.7500 | no |
| 77 | 2 | two_point | 3 | all_yes | 20000 | 0.0513 | 0.0539 | 0.0488 | 0.6188 | no |
| 78 | 2 | two_point | 3 | all_no | 0 | n/a | n/a | n/a | n/a | **YES** — same structural cause as idx 6 |
| 79 | 2 | two_point | 3 | mixed | 20000 | 0.0734 | 0.0765 | 0.0704 | 0.8125 | no |
| 80 | 2 | cap_shaped(R=2) | 1 | all_yes | 20000 | 0.0558 | 0.0586 | 0.0532 | 0.5777 | no |
| 81 | 2 | cap_shaped(R=2) | 1 | all_no | 20000 | 0.0546 | 0.0574 | 0.0520 | 0.5773 | no |
| 82 | 2 | cap_shaped(R=2) | 2 | all_yes | 20000 | 0.0557 | 0.0584 | 0.0531 | 0.6875 | no |
| 83 | 2 | cap_shaped(R=2) | 2 | all_no | 20000 | 0.0539 | 0.0565 | 0.0512 | 0.4375 | no |
| 84 | 2 | cap_shaped(R=2) | 2 | mixed | 20000 | 0.0790 | 0.0822 | 0.0758 | 0.8750 | no |
| 85 | 2 | cap_shaped(R=2) | 3 | all_yes | 20000 | 0.0539 | 0.0566 | 0.0513 | 0.6544 | no |
| 86 | 2 | cap_shaped(R=2) | 3 | all_no | 0 | n/a | n/a | n/a | n/a | **YES** — same structural cause as idx 6 |
| 87 | 2 | cap_shaped(R=2) | 3 | mixed | 20000 | 0.0782 | 0.0814 | 0.0751 | 0.8750 | no |
| 140 | 3 | two_point | 2 | mixed | 20000 | 0.0834 | 0.0867 | 0.0803 | 0.8595 | no |

29 contributing cells, 4 skipped (all `all_no, k=3` — structurally near-infeasible: 3 simultaneous
high-implied-probability NO legs almost never satisfy `Σ(1-ask_i) ≤ 1` under the observed,
typically-cheap ask sample; this is the production admission gate itself, not a sampler defect —
reported, not forced).

## 5. Mechanism verdict (§7 step 4, AC #3)

**INDETERMINATE.** `n_cells=29` (≥ the 24-cell minimum). Spearman `ρ=0.8331` between
`max_k|Δt_k|` and the realised crossing rate, one-sided permutation `p=0.0001` (10000 permutations,
seed `20260921_000`) — **condition (2), monotonicity, is STRONGLY satisfied** (`ρ ≥ 0.70`, `p < 0.01`).

**Condition (3), the qty≡1 control anchor, FAILS:** the control cell (`q_max=1, k=1, side_mix=all_yes`,
idx 0) has crossing rate 0.0089 with CP-upper 0.0100 (well inside the ≤0.025 half of the anchor) but
`max_k|Δt_k| = 0.365`, ten times the pinned `≤0.01` tolerance.

**Why, and what this means — a genuine, reported finding, not a defect.** `max_k|Δt_k|=0.365` at
`q_max=1, k=1` is **not** a qty effect: at `qty≡1`, `Var_H0(X_sd) = BE(1-BE)`, which is only `0.25`
(the artefact's assumed per-draw information) when `BE=0.5`. The observed ask sample (§7 below) has
`median=0.22`, `p75=0.35` — far below 0.5 — so `E[BE(1-BE)]` under this BE prior is well under 0.25,
and information accrues SLOWER than the artefact's assumed schedule even at `qty=1`. This departure is
in the SAFE direction (it under-spends alpha, consistent with the control's 0.0089 rate sitting well
under 0.025), but it means the control anchor as pinned (`max|Δt_k| ≤ 0.01`) is not achievable with a
realistic, cheap-ask BE prior — the anchor implicitly assumes a BE distribution close to the artefact's
own generation assumption (informally, closer to `Uniform(0,1)`, whose `E[BE(1-BE)]=1/6`, itself below
0.25 but much closer to it than this repo's actual traded price range).

**Disposition per §7 step 4: the item STOPS here and reports.** The very strong monotonicity (`ρ=0.83`,
`p=0.0001`) is genuine evidence FOR the recorded mechanism (higher `max|Δt_k|` does correlate with
higher crossing rate across every dispersion/qty/side-mix combination run), but the control-anchor
failure means the CONFIRM criterion's own machinery cannot cleanly separate "departure caused by qty
inflation" from "departure already present at qty≡1 under a realistic BE prior". Per Amendment C: **an
envelope may not be published on an unestablished premise.** No envelope is formally published by this
item (§6).

## 6. Envelope — NOT PUBLISHED (mechanism INDETERMINATE, §5)

Per Amendment C / AC #3-#4, envelope publication is gated on a **CONFIRMED** mechanism verdict. This
run is INDETERMINATE, so **no `Q_MAX_VALIDATED` is formally published by this item.**

**What the raw table nonetheless shows, reported for the reader's information only (not a ruling):**
every `q_max=2` cell run has CP-upper in `[0.048, 0.083]`, well above `α=0.025`, and the single
`q_max=3` reference cell (idx 140) has CP-upper 0.0867. Every `q_max=1` cell run (except the
structurally-infeasible `all_no,k=3`) has CP-upper `≤ 0.025` (max 0.0160). **If a determinate mechanism
or a completed grid later confirms these figures, `q_max=1` is very unlikely to move** — but that is an
observation about this partial table, not a validated envelope, and AUD-06b must not treat it as one.

**R-11's own fallback is NOT triggered either:** a re-solve (remedy B) is warranted only when a
CONFIRMED-mechanism envelope comes back empty, which did not happen here (the mechanism itself did not
reach CONFIRMED). `boundary_inputs_sha256` is unchanged (§0, re-asserted by
`test_the_boundary_inputs_sha256_is_unchanged`).

## 7. `BE`-prior support and staleness predicate (AC #6)

`n=9`, `min=0.09`, `p25=0.12`, `median=0.22`, `p75=0.35`, `max=0.70`, `IQR=0.23` — the 9 durable PM.us
fills' posted ask (§8 below).

**Staleness predicate:** `sweep.envelope_is_stale(live_asks, recorded_support=...)` — STALE when the
live 14-day trailing median ask falls outside the recorded `[p25,p75]`, or the live IQR drifts by more
than +50%/−33% from the recorded IQR. Tested by
`test_the_envelope_records_the_be_prior_support_and_its_staleness_predicate` and
`test_a_be_prior_outside_the_recorded_support_marks_the_envelope_stale`.

**Honest limitation on the `BE`-prior source itself:** the observed ask sample is the 9 durable PM.us
fills' `cost = px` column (`docs/evidence/AUD13A_RECONCILIATION_EVIDENCE_2026-09-24.md` §1) — the only
read-only, already-public per-fill ask data available without a heavier tape scan. `n=9` is thin; the
support recorded here should be treated as provisional until a broader tape-derived ask summary is
available.

## 8. Real qty distribution (KNOWN section, brief) — measured, not invented

All 9 durable PM.us fill records are `qty=1` (`docs/evidence/AUD13A_RECONCILIATION_EVIDENCE_2026-09-24.md`
§1 table, `qty` column, every row `1`) — confirming `config.py:255`'s `order_quantity must be exactly 1`
enforcement and that **no empirical qty>1 data exists today**. This is exactly why Amendment C's
`cap-shaped` dispersion class draws from a dimensionless `R` grid rather than an empirical qty>1
distribution (Amendment C round-2 disposition #2) — there is nothing empirical to draw from, and this
measurement (read-only, from the same census the AUD-13a evidence pack already ran under
`systemd-run --user --scope -p MemoryMax=4G`) is the confirmation, not a new read.

## 9. `xfail` disposition (§7 step 7, AC #8)

**The strict `xfail` stays exactly as it is, unchanged in substance.** Per Amendment C: "If the
envelope is empty, the original strict `xfail` stays exactly as it is, with its reason extended by this
item's artefact reference" — the same disposition applies here (no CONFIRMED-mechanism envelope was
published, so there is nothing to bound a passing test against). `test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha`
remains `xfail(strict=True)`; its reason string gains one appended sentence citing this artefact
(`docs/evidence/RULING_r11_qty_envelope_2026-09-25.md`) and the INDETERMINATE mechanism verdict, so a
future reader following the xfail reason lands on this evidence rather than a dead end. **Nothing is
deleted, loosened, or weakened** — the citation is additive only, verified by re-running the test
unchanged (still `xfail`s for the same measured reason) after the edit.

## 10. What this item does NOT establish

- **Not a completed 320-cell grid** (§3). AC #9 is NOT met in full; τ_cell (59.50s), peak RSS (97.8MB)
  and the projected total (5.29h) ARE recorded, satisfying the measurement half of AC #9. The remaining
  287 cells can be resumed via `--cells FROM:TO` against `docs/evidence/aud06a_sweep_cells.jsonl`
  without re-deriving anything computed here (seeds are per-cell, chunk-order-independent, per
  `test_a_chunked_run_produces_a_byte_identical_table_to_a_single_run`).
- **No mechanism CONFIRMED or REFUTED** — INDETERMINATE, for the reason in §5 (control-anchor failure
  driven by the observed BE prior, not by qty). A follow-up should either (a) complete the grid to see
  if the pattern holds at full coverage, or (b) reconsider whether the control-anchor tolerance
  (`≤0.01`) is calibrated for a realistic (non-`Uniform(0,1)`) BE prior — both are follow-up questions,
  not resolved here.
- **No qty>1 envelope published or implied safe.** The raw partial table's `q_max=2`/`q_max=3` figures
  (§6) are informational only.
- **No sizing code changed.** `order_quantity` stays 1; `config.py:253-256` untouched.
- **No re-solve of the boundary artefact.** `boundary_inputs_sha256` unchanged.
- **No operator-reserved value read, restated, defaulted or inferred anywhere in this item.**
