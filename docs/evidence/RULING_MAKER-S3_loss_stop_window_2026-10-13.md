# RULING_MAKER-S3_loss_stop_window_2026-10-13

Status: FINAL (two review rounds incorporated). Immutable once committed; any change is a new dated ruling.
Date: 2026-10-13
Type: coordinator ruling (no operator budget cap involved; decision owner per Pre-Auth)
Precondition for: `docs/plans/backlog/MAKER_2026-10-12/S3_loss_floor_reachability_plan_r3.md` §2 item 3 ("Window ruling") and the S5 PREREG `a1_stop` row (`docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r3.md` :218, :221, :228)
Reviews incorporated: round 1 `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r3-pmr-verification.md` (SOUND-WITH-CAVEATS; C1 unit error) + architect round 1 (REQUEST_CHANGES items 1/2/4); round 2 `reviews/S3-r4-pmr-final.md` (SOUND-WITH-CAVEATS; N-3 wording) + architect round 2 (edit-level: `frozen_c_deff` key, provenance paths, `tick_share`)

## 1. Question

The S3 Monte-Carlo certifies an A1 loss stop for the `no_ladder_maker` family.
The FQ engine calibrates that stop over the FQ v2 window
2026-10-08..2027-01-25: `n_cal = inclusive_days(freeze, horizon)` = 110
**climate dates** (`scripts/analysis/fq_loss_floor_mc_engine.py:231`), with
ticks per cell `T_low = ⌊n_days·λ_sd·p_keep·tick_share⌋` (`fq_loss_floor_mc_gate.py:136-142`),
epoch grid {freeze, 11-01, 11-15, 12-01}. Spec v0.3 §9.15 says every maker path
passes the 2027-01-25 RA-13 review date and that "a relative window is a label,
not a licence". The S3 plan asks whether the maker loss-stop window is RELATIVE
(110 climate dates from the family's start) or ABSOLUTE (ending 2027-01-25).

## 2. Ruling

**Option A — relative.** The maker loss-stop window is **110 climate dates,
counted from the S5 PREREG `holdout_start_date`**. The S3 binding run uses the
FQ v2 grid 2026-10-08..2027-01-25 purely as the 110-date label. Units: the
certified quantity is climate dates, never ticks; the certified tick count is a
per-cell OUTPUT of the artifact (`certified_ticks = T_low` for that cell), not a
field anyone chooses.

Option B (absolute, ending 2027-01-25) is rejected because under the S5 assumed
start (2026-11-23) the window is ~64 climate dates and under a post-PASS live
start it is ~0: either way the stop would EXPIRE on 2027-01-25 and the family
would run with no loss stop afterwards. A stop that disarms is worse than a stop
with an uncertified tail. (Engine convenience is NOT a ground: only a changed
*freeze* breaks `epoch_grid`/`complete_veto`; a longer *horizon* at freeze
2026-10-08 runs today, which O-2 uses.)

## 3. Obligations (binding on S3 WP3/WP4 and the S5 PREREG)

**O-1 Certified horizon and the armed tail.** `c` is certified over
`n_cal = 110` climate dates. The S5 PREREG `a1_stop` row carries
`certified_horizon_climate_days: 110` and `certified_ticks: <artifact value for
the frozen cell>` (both inside `a1_stop`, never as a separate stop key — the
S5 PREREG checker R-13 must accept them there). The stop STAYS ARMED for the
whole shadow run. Beyond date 110 the √t boundary's H0 false-stop rate is
uncertified and rises with t (PMR iid check: α 0.10 → ≈0.15 at 284 ticks when
solved at 76). This is capital-conservative and costs POWER, not safety: an A1
STOP is terminal under S5 (`S5_A1_STOP`, family halt row, no restart, resting
orders cancelled) and is neither a FAIL nor a refutation of the hypothesis. The
PREREG discloses the H0 false-stop rate at the S5 `calendar_cap_date` horizon,
read from the O-2 cell, and S5's power projection discounts for it.

**O-2 Mandatory horizon-sensitivity cell, pinned before the binding run.**
WP3 pins exactly one additional horizon: freeze 2026-10-08 (the builder refuses
any other freeze) with horizon length = inclusive days from `holdout_start_date`
to the S5 `calendar_cap_date`, reported as `horizon_sensitivity` (report-only,
never the binding cell), same seeds. The S5 `calendar_cap_date` is therefore an
INPUT to S3 WP4 step 3 and must be fixed (S2 landed) before the binding run.
No cell is added or chosen after results; after the PREREG freeze no re-solve is
permitted (spec v0.3: zero planned revisions; a changed stop is a new PREREG).

**O-3 The frozen pair is (σ·√1.5, c_deff) with c_deff = c/√1.5 at full float
precision.** S3 §4.4 certifies (σ, c) ≡ (σ·√1.5, c/√1.5) (same crossing paths;
G1/G3 ratio-invariant). The S5 PREREG freezes `c_deff` with the inflated σ,
never the unit-variance `c` with the inflated σ. This AMENDS S5 plan r3 :221
("freeze (c, t_min, α_floor) … σ inflated by √1.5" → `c_deff`) and S3 plan r3
§4.4 ("may freeze either form" → this single form). S5's test
`test_a1_stop_uses_s3_parameters_and_deff_inflated_sigma` pins `c_deff` from
the artifact key `frozen_c_deff` (a single frozen scalar; per-cell values live under `cells[*].c_deff` and are never read by S5).

**O-4 Which cell's c is frozen.** Each binding cell (k × b × f) solves its own
c. The frozen `c` is taken from the binding cell at `f_kill` nearest S2's
realised (k, b) point; if S2's realised point falls between grid cells, the
larger c of the bracketing cells is frozen. A larger c is the LESS protective
choice (it fires later); it is chosen so that the frozen stop never fires
faster than any bracketing cell certified, and protection is then guarded by
the re-check: WP4 re-evaluates G1, G3 AND the H0 crossing rate on EVERY binding
cell at that frozen c, and the artifact records the per-cell result (tests
required: plan r4 delta). The frozen c is solved at the `f_kill` tick count;
the artifact says so. If S2's realised b lies outside [0.70, 0.80] the binding
run is refused (spec B_FLOOR/B_CAP), not extrapolated.

**O-5 2027-01-25 is addressed, not pre-empted.** This ruling is NOT the RA-13
R4 ruling (PMR r1 #9). The S5 PREREG states the RA-13 review date 2027-01-25
explicitly and the fail-closed consequence: unless a separate dated R4 ruling
is issued before 2027-01-25, the programme KILL backstop stands; and because
the ≥300-position read lands after 2027-01-25 under every S5 start assumption,
the S5 report is ADVISORY-ONLY absent that R4 ruling. S2 and S3 artifacts are
inputs to the R4 ruling, never a substitute for it.

**O-6 Artifact wording.** The S3 binding artifact says, verbatim:
"window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-climate-date label;
certified_horizon_climate_days = 110; certified_ticks = <T_low of the frozen
cell>; frozen cell = <k, b, f_kill>; frozen_c_deff = <value>; see
RULING_MAKER-S3_loss_stop_window_2026-10-13".

## 4. What this ruling does not decide

- The S5 `holdout_start_date`, `calendar_cap_date`, or read target (S5 PREREG).
- Whether the maker family is registrable (S3 WP4 verdict).
- Anything about live enablement (operator-only).

## 5. Provenance

Inputs: S3 plan r3 §2/§4.3/§4.4/§7; spec v0.3 §4, §9.15;
`docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md` §3 (KILL horizon 2027-01-25, B-5);
`docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` :54;
`scripts/analysis/fq_loss_floor_mc_gate.py` (`DEFAULT_FREEZE`, `HORIZON`,
`_EPOCH_FIXED`, `t_low_count`); `scripts/analysis/fq_loss_floor_mc_engine.py:231-235`;
S5 plan r3 :202, :218, :221, :228, :285.
