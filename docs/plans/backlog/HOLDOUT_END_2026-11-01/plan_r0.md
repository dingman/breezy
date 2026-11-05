# HOLDOUT-END — give `DEFAULT_SPLITS` the ruling's exclusive end date (plan r0, 2026-11-01)

Status: PROPOSAL r0 for blind peer review (python-reviewer + prediction-market-reviewer). Source: architect spec 11-01 (read-only codegraph survey), landed by the coordinator. Owed by `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` cl.1/cl.4; cl.1 requires "a reviewed L-12 widening", hence this plan.

## 1. Defect
`src/breezy/analysis/nbp_calibration.py:273-278` `DEFAULT_SPLITS` has `holdout_start=2026-07-01` and NO end; the `Splits` docstring (:238-240) calls the holdout "open-ended" and `split_for_date` (:268) returns `"holdout"` for every day ≥ 07-01. Consequences today:
- No live leak INTO a fit: every consumer refuses or splits at `>= holdout_start` (`nbp_calibration.py:1402/1606/1611`, `_assert_no_holdout_rows` :941-949, `multisource_blend_features.py:21/382`, `multisource_blend_folds.py:85/192/260`, `nbp_drift.py:46/107`, `nbp_learning_nightly.py:391/466`, `nbp_skill_study.py:759/1197/1296/1906-1909`, `fq_mc_livedata.py:56/95/176/208`, `revision_latency.py:177`). Forward days (≥ 10-02) are therefore wrongly kept SEALED, not wrongly fitted.
- Real defect: `nbp_skill_study.py:1907/1909` puts every day ≥ 07-01 into the single confirmatory holdout look, so forward days are pooled into the one sealed read (violates cl.1/cl.2).
- `autonomy/leakage.py:14` hardcodes `FIRST_FORWARD_DAY = 2026-10-02`, restating the ruling's date despite its docstring promising it never would.
- Trap: `_assert_no_holdout_rows` checks the split LABEL, not the date; a new `"forward"` label would slip past it unless widened.
- Hard-coded 07-01 copies that need no end: `scripts/archive/lamp_archive_runs.py:60`, `metar_routine_minute_probe.py:122` (archive-fetch caps at the START; `metar_routine_store.py:10` cites 07-01 in a docstring only).

## 2. Change (minimal)
1. `Splits` gains `holdout_end_exclusive: dt.date`; `DEFAULT_SPLITS` sets `dt.date(2026, 10, 2)`; `__post_init__` rejects an end ≤ start.
2. `split_for_date` returns `"holdout"` only for [07-01, 10-02) and `"forward"` for ≥ 10-02; helpers `in_holdout(day)` / `is_forward(day)`; docstring fixed.
3. `leakage.FIRST_FORWARD_DAY` = `DEFAULT_SPLITS.holdout_end_exclusive` (import direction to be confirmed by `lint-imports`; if `autonomy` may not import `analysis`, keep the constant and add an equality TEST instead).
4. Partitions bounded `< holdout_end_exclusive`: `nbp_skill_study.py:1907/1909` (confirmatory holdout look) and `nbp_learning_nightly.final_rows_for_report` (`include_holdout=True` path).
5. Label-based guards widened to refuse BOTH labels: `_assert_no_holdout_rows` and `fq_mc_livedata.py:95` → `split in {"holdout", "forward"}` (fitters must not see forward days either; conservative).
6. The `>= holdout_start` refusals in the frozen FQ/NBP/blend pipelines stay as they are.
7. `repr(DEFAULT_SPLITS)` is printed as provenance at `nbp_skill_study.py:2342/2376` — text changes; confirm no sha-pinned artefact embeds it (builder must grep `docs/evidence` for `holdout_start=` before building; if one does, STOP and report).

## 3. Tests (RED first)
- `test_default_splits_pin_the_ruling_window`: `(holdout_start, holdout_end_exclusive) == (2026-07-01, 2026-10-02)`.
- `test_split_for_date_tags_forward_after_the_freeze`: 10-01 → `"holdout"`, 10-02 → `"forward"`, 06-30 → the pre-existing label.
- `test_splits_reject_end_not_after_start`.
- `test_confirmatory_holdout_partition_excludes_forward_days` (`nbp_skill_study`): events on 07-01 and 10-01 are in the holdout partition, 10-02 is not.
- `test_no_fitter_reads_a_frozen_or_forward_row`: `_assert_no_holdout_rows` raises for both labels (cl.1 RED test).
- `test_first_forward_day_is_the_holdout_end`.
- `test_final_rows_for_report_bounds_the_holdout_at_the_end_date`.
- Existing tests that move (field added, assertions unchanged): hand-built `Splits(...)` in `tests/unit/test_nbp_calibration.py:49/60`, `tests/unit/test_revision_latency.py:376`; `test_nbp_calibration.py:73` (09-29 → holdout) stays and gains a forward sibling; `test_nbp_skill_study.py:1060/1096` must stay green.

## 4. Pins / isolation / risk
- Only `tests/unit/test_maker_stage0_pins.py:161` imports `DEFAULT_SPLITS` (pins `v5_fit_slice.end`, unchanged). No `nbp_calibration` entry found in `pins.py` or the pin/x1/closure test files (builder re-checks the x1/c10 sets by running them).
- Import isolation: `nbp_calibration` is imported only by analysis modules; the trade node does not load it. `lint-imports` after the slice.
- Frozen artefacts / sealed FQ v1 use rows < 07-01 (unchanged); no PREREG reads the end date; `revision_latency` string-matches markers only.
- Gate class: new label + edited partitions = new behaviour under cl.1 → this plan + peer review → tdd-guide build → python review → full gate.

## 5. Acceptance
Full gate green; the 5 new tests green; `lint-imports` 13 kept / 0 broken; no artefact sha changes; the next nightly skill-study run's confirmatory partition reports its holdout end as 10-02 (read-only check at the following wake).

## 6. Invariants
Nautilus immutable; nothing in the holdout is fitted/folded/scored; no PREREG or frozen artefact edited; no new harness; no operator controls; no live-trading surface.
