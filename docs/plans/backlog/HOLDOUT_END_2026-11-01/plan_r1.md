# HOLDOUT-END — give `DEFAULT_SPLITS` the ruling's exclusive end date (plan r1, 2026-11-01)

Status: r1 for blind re-review (python-reviewer + prediction-market-reviewer); supersedes r0 (cbadf1c1) after two REVISE verdicts. Owed by `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` cl.1/cl.4; cl.1 requires "a reviewed L-12 widening" (widen, never relax). Class: **administrative correction** — the single confirmatory look has NOT been spent (no `open_holdout` caller is wired; the 09-30 validate reports `holdout_*_filtered: 0`), so re-partitioning changes no recorded result and is not an L-34 second look. Cl.3 note: 07-01..10-01 tape studies are contaminated; any later look on that window is descriptive only.

## 1. Defect (corrected)
`src/breezy/analysis/nbp_calibration.py:273-278` `DEFAULT_SPLITS` has `holdout_start=2026-07-01` and no end; `Splits` docstring (:238-240) calls it "open-ended"; `split_for_date` (:268) returns `"holdout"` for every day ≥ 07-01.
- No live leak INTO a fit: every fitter/screener refuses or splits at `>= holdout_start` (`nbp_calibration.py:1402/1606/1611`, `_assert_no_holdout_rows` :941-949, `multisource_blend_features.py:21/382`, `multisource_blend_folds.py:85/192/260`, `nbp_drift.py:46/107`, `nbp_learning_nightly.py:391/466`, `nbp_skill_study.py:759/769/1197/1207/1296/1906-1909`, `fq_mc_livedata.py:56/95/176/208`, `revision_latency.py:177`). Forward days (≥ 10-02) are wrongly SEALED, never wrongly fitted.
- `nbp_skill_study.py:1906-1909` is the fit-exclusion filter (drops ≥ 07-01 rows and counts them into `holdout_*_filtered` at :1961-1962) — NOT the look. It stays as the interim barrier.
- Real exposure: the one-look input `open_holdout` (`nbp_calibration.py:~353`, unwired; only `tests/unit/test_nbp_calibration.py:143` references it) takes `final_station_day_count` against `n_min` with no upper date bound, so forward days would inflate n and be pooled into the look when it is wired. Same for `nbp_learning_nightly.final_rows_for_report` (`include_holdout=True`, ~:207-219).
- `src/breezy/analysis/autonomy/leakage.py:14` hardcodes `FIRST_FORWARD_DAY = 2026-10-02` despite its docstring (:3).
- `_assert_no_holdout_rows` checks the split LABEL; a new `"forward"` label is not "holdout" and must NOT be refused there (cl.2, see §2.5).
- Hard-coded 07-01 copies needing no end: `scripts/archive/lamp_archive_runs.py:60`, `metar_routine_minute_probe.py:122`.

## 2. Change (minimal; widen, never relax)
1. `Splits` gains required `holdout_end_exclusive: dt.date`; `DEFAULT_SPLITS` sets `dt.date(2026, 10, 2)`; `__post_init__` rejects `end <= holdout_start` (existing `v5_fit_slice.end < start` check kept). Constructors to update: `nbp_calibration.py:273`, `tests/unit/test_nbp_calibration.py:49/60`, `tests/unit/test_revision_latency.py:376` (no others in src/scripts/tests).
2. `split_for_date` → `"holdout"` for [07-01, 10-02), `"forward"` for ≥ 10-02 (date inputs only; a `datetime` argument raises `TypeError` by contract — test it). Helpers `in_holdout(day)`, `is_forward(day)`. Docstrings at :22, :238-240, :476, :1182 corrected.
3. `leakage.FIRST_FORWARD_DAY = DEFAULT_SPLITS.holdout_end_exclusive` (`analysis.autonomy` → `analysis.nbp_calibration` is intra-layer; the F7b contract `pyproject.toml:230-237` covers only `eprocess`/`confidence_sequence`); rewrite `leakage.py:3` docstring to say the date is consumed by name. No equality test (would be tautological).
4. Bound the ONE-LOOK inputs at `< holdout_end_exclusive`: `open_holdout`'s `final_station_day_count` partition, and `final_rows_for_report(include_holdout=True)`. In `nbp_skill_study` keep the `>= holdout_start` fit-exclusion (:1906-1909) unchanged; split its reported count into `holdout_*_filtered` (< end) and a new `forward_rows_filtered` (≥ end).
5. Label guards: `_assert_no_holdout_rows` refuses `"holdout"` ONLY (cl.1: "no fitter or screener reads a row inside [07-01, 10-02)"; cl.2: AUT-3 trains on forward days before `forward_eval_start_utc`). A forward-labelled row passes this guard; the interim `>= holdout_start` barriers (§1) still stop it today and are lifted later only by AUT-3's `train_end_lt_forward_eval_start`, never by relaxing this guard. `fq_mc_livedata.py:95` (frozen FQ pipeline, bare `assert`) is NOT touched. Dead defence-in-depth `== "holdout"` tests at `nbp_skill_study.py:769/1207` are left as they are (unreachable behind the date barrier) — note in the diff, do not widen.
6. `multisource_blend_folds.py:192` will now label forward rows `"forward"`; :260 and `nbp_calibration.py:1198/1306` are allow-lists (safe; verify by test, not by reading).
7. **Pin:** `tests/unit/test_multisource_blend.py:35` `_NBP_MODULE_SHA256` byte-pins `nbp_calibration.py` (checked at :223-229) → re-pin ONCE after the final diff as a reviewed row in the existing AUT-6 WP5 comment style. Also check `tests/unit/test_gate_shards.py:670` and `tests/unit/test_mypy_ratchet.py:376` (both name the module) and run the x1/c10 sets.
8. `repr(DEFAULT_SPLITS)` provenance at `nbp_skill_study.py:2342/2376` changes text; no `docs/evidence` file embeds `holdout_start=` (verified by two reviewers); `PROVENANCE_MARKERS` / PREREG text tests match plain `"DEFAULT_SPLITS"` / `"holdout_start"` only. Builder re-greps before building; a hit = STOP.

## 3. Tests (RED first; none removed or weakened)
- `test_default_splits_pin_the_ruling_window` — `(holdout_start, holdout_end_exclusive) == (2026-07-01, 2026-10-02)`.
- `test_split_for_date_tags_forward_after_the_freeze` — 06-30 → pre-existing label, 07-01 and 10-01 → `"holdout"`, 10-02 → `"forward"`.
- `test_split_for_date_rejects_datetime` — `TypeError`.
- `test_splits_reject_end_not_after_start`.
- `test_open_holdout_station_day_count_excludes_forward_days` — rows on 07-01, 10-01 counted; 10-02 not.
- `test_final_rows_for_report_bounds_the_holdout_at_the_end_date` — 10-02 row excluded under `include_holdout=True`.
- `test_skill_study_counts_forward_rows_separately` — `holdout_*_filtered` unchanged for a ≤ 10-01 fixture; a 10-02 row lands in `forward_rows_filtered`.
- `test_no_fitter_reads_a_frozen_row` — `_assert_no_holdout_rows` raises for `"holdout"`; `test_forward_label_passes_the_frozen_row_guard` — does not raise for `"forward"` (cl.2), while `test_interim_date_barrier_still_stops_forward_rows` shows a `>= holdout_start` barrier still refuses a 10-02 row today.
- `test_first_forward_day_is_derived_from_default_splits` — only if the constant stays hard-coded (else drop).
- Existing: `test_nbp_calibration.py:73` (09-29 → holdout) stays + forward sibling; `test_nbp_skill_study.py:1060/1096`, `test_multisource_blend.py:278`, `test_lamp_archive_backfill.py:560`, `test_multisource_blend_inputs_lamp.py:45` stay green; `test_multisource_blend.py:223-229` green after the one re-pin.

## 4. Isolation / risk
`nbp_calibration` is imported only by analysis modules (trade node does not load it); `lint-imports` after the slice. Frozen artefacts / sealed FQ v1 use rows < 07-01; m1v3 `PREREG.json:29` and the TE2 predeclaration cite only the 07-01 seal. No PREREG reads the end date.

## 5. Acceptance (observable without a look)
Full gate green; new tests green; `lint-imports` clean; exactly one pin row changed; a read-only `nbp_skill_study` validate dry-run shows `holdout_*_filtered` unchanged, a `forward_rows_filtered` count present, and NO `open_holdout` marker created.

## 6. Invariants
Nautilus immutable; nothing in [07-01, 10-02) is fitted/folded/scored; no PREREG or frozen artefact edited; no new harness; no operator controls; no live-trading surface; L-12: widen, never relax.
