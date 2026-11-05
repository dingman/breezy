# GAP-3 CONFIDENCE-BINNED-BACKTEST — plan r1

Status: r1 — for re-review by **architect** and **python-reviewer**.

## 0 Finding → resolution (A = architect, P = python-reviewer)
| # | Sev | Resolution |
|---|---|---|
| A-1 | HIGH | Accepted. The live-root guard stays as it is, with no carve-out (L-12). Run dir is `docs/evidence/strategy_iteration/runs/<run_id>/`. (a) With the flag, the scan refuses (exit 4) when the script differs from HEAD, and records `script_git_sha`. (b) `main` refuses an existing `--out` up front, next to `_refuse_live_root` (`:868`). `write_outputs` creates the dir with `exist_ok=False` and opens files with mode `"x"` (§4.3). (c) The coordinator checks the sha256 against the writer's output and commits byte-for-byte; notes go in a sidecar (L-75). The STRATEGY_ITERATION `plan_r1_delta.md` D4 path text is amended in the same commit (§3). |
| A-2 / P-2 | HIGH | Accepted (both reviewers agree). `Cell` and `ZeroVarianceCell` get a trailing `edge_bin: str \| None = None`. `_cells` (`:615-644`) builds both by keyword. `to_dict`, `best_cell_by_t` (`:673`), the markdown table and the zero-variance line include `edge_bin` only when it is not None. `ForecastCellKey` is a separate 4-tuple alias, and `CellKey` (`:540`) is unchanged. |
| A-3 | HIGH | Accepted. With the flag, the markdown table gains an `edge` column after `ask bin`, and the zero-variance line gains the edge label. Without the flag the rendering is byte-identical (pinned). |
| P-1 | HIGH | Resolved without amending the guard. `test_scan_reads_no_model_output` (`tests/unit/test_market_calibration_scan.py:259`) checks import names only. The flag reads the CSV with stdlib `csv`, which is already imported (`:45`), and adds no import, so the test stays **unmodified and green**. The model-free claim in the docstring (`:4`) is scoped to "the default run". A new test pins that the default run opens no p file. Not escalated to the operator: the guard is unchanged and the decision sits with the coordinator under Pre-Auth (A-6). |
| P-3 | HIGH | Accepted. New helpers: `_load_forecast_p`, `_join_forecast`, `_forecast_block` and `_run_forecast_p`. `collect`, `build_scan` and `build_report` stay under 50 lines. `test_orchestrators_are_short_and_flat` (`:632`) stays unmodified and is a named gate. |
| A-4 | MED | Accepted. The pin covers the fixture sha, the default JSON key set and `kind`, and is committed alone before any implementation. |
| A-5 | MED | Accepted. Refused when `ref_ts_ns <= available_at_ns`, i.e. the ask time must be **strictly after** availability. This matches the GAP-2 contract and the `:270` convention. It raises `ForecastInputError("forecast_p_lookahead")` with exit 3, never `tally.failures` or INVALID. |
| A-6 | MED | Accepted. The flag sits inside the 10-21 existing-harness ruling (a join, a bin and provenance; `excess`, the bootstrap and SPA are untouched; precedent `wp7b --since`). The GAP-2 exception fallback is removed from §2 and §8. |
| A-7 / P-8 | LOW | Accepted. The PREREG discloses the number of forward day-blocks and that percentile coverage falls below nominal. The word "conservative" is dropped. |
| A-8 | LOW | Accepted. Unmatched observations are reported split into `forward` (≥ 10-02) and `pre_forward`. |
| P-4 | MED | Accepted. Any existing `--out` is refused (exit 4), even an empty one. JSON (which carries `tested_cells`) is written before MD. If the writer crashes between the two writes, that run_id is burned and its JSON debit still counts. |
| P-5 | MED | Accepted. The refusal order is fixed in §4.3. Exit 3 is separate from INVALID exit 2 (`:882`). |
| P-6 | MED | Accepted, with one change. The join format is pinned (§3). An unknown `window` or an unparseable `instrument_id` refuses the file. Instead of a fixed allow-list, the file must hold exactly one distinct `source_id` (otherwise refused), and that id is recorded. The reason: the GAP-1/GAP-2 source set is not frozen, so an allow-list would hard-code a guess. |
| P-7 | MED | Accepted. Dependents: `maker_design_score.py:32` imports `_bootstrap_stats` and `venue_fee` (both untouched), `no_longshot_pooled_test.py:62` and `p2_nbp_ask_murphy.py:663`. Their tests are named gates (§6). The sha pin does not cover them. |
| P-9 | LOW | Accepted. The pin fixture is built with `_depth` (`:60`), `_write` (`:82`) and `_truth_file` (`:91`), then runs `scan.main([...])`. |

## 1 Objective
Today the scan bins only by ask band × window, so it can say which bands are mispriced but not whether a forecast can pick out the mispriced rungs. `--forecast-p PATH` adds a forecast-edge axis so the scan can answer one question: do rungs where the forecast is more confident than the ask beat ask + fee? That is the band GAP-4 must register in order to execute winning trades. The output stays a screen (FQ-R14 `SCREENING_NOTICE`); a positive cell is never nomination evidence.

## 2 Preconditions and dependencies
- **GAP-2 is a hard dependency.** Its forward per-rung p file is the only input to the flag. §3 states what GAP-3 requires of it.
- The flag falls under the existing-harness ruling (A-6). It is no part of the GAP-2 exception.
- Holdout ruling cl.1–cl.4: only rows with climate_day ≥ 2026-10-02 are admissible.

## 3 Scope
- **In scope.** All changes are in `scripts/analysis/market_calibration_scan.py`:
  - `main` (`:860-882`)
  - `_day_matrices` (`:543-565`), which gains `key_fn`; the default is the existing 3-tuple
  - `build_scan` (`:683-699`), which passes `key_fn` through
  - `Cell` and `ZeroVarianceCell` (`:477-528`) and `_cells` (`:615-644`)
  - `_multiplicity.best_cell_by_t` (`:673`)
  - `build_report` (`:758-795`), which gets `kind` from a parameter and is otherwise unchanged
  - `_markdown` (`:820-835`) and `write_outputs` (`:847-857`)
  - the module docstring (`:3-5`)
  - the new helpers from P-3
- **Tests in scope.** A new `tests/unit/test_market_calibration_scan_forecast_p.py`, and a pin added to `tests/unit/test_market_calibration_scan.py`.
- **Doc in scope.** `docs/plans/backlog/STRATEGY_ITERATION_2026-11-01/plan_r1_delta.md` D4 (`:19`): the run-file path becomes `docs/evidence/strategy_iteration/runs/<run_id>/market_calibration_scan.json`, and the precedent cite and the path `prereg_precommit_check` sums are replaced with it. The guard code change itself remains STRATEGY_ITERATION's step.
- **Not in scope:** windows, ask deciles, `excess` (`:472`), the bootstrap, SPA, `validity_reasons`, `_refuse_live_root`, any strategy or exec code, and the explore-gate arithmetic. No new statistic and no verdict.
- **p-file contract (GAP-2 must match).** The file is CSV, read with stdlib `csv`.
  - Required columns: `instrument_id,window,p_yes,available_at_ns,source_id`. Extra columns are ignored and listed in `forecast_p.extra_columns`.
  - `instrument_id` is the full depth-directory name (`<slug>.POLYMARKET_US`). It is parsed with `classify_directory` (`:191`). It joins when `instrument_id.removesuffix(".POLYMARKET_US") == Observation.rung` (`:399`) AND `window == Observation.window`, where `window` ∈ {`D-1_18Z`,`D_12Z`,`D_17Z`} (`WINDOWS :152-156`).
  - A row whose `instrument_id` classifies as non-HIGH is counted (`non_high_rows`) and ignored.
- **The whole file is refused** (exit 3, `ForecastInputError(reason)`, nothing written) on any of:
  - a missing column, or a duplicate (instrument_id, window)
  - `p_yes` that is not a finite number in [0,1]
  - `available_at_ns` that is not a non-negative int
  - an unparseable instrument
  - an unknown window
  - a rung climate_day < `FORWARD_START = dt.date(2026,10,2)`
  - more than one distinct `source_id`
  - after the join: any matched observation with `ref_ts_ns <= available_at_ns`

## 4 Steps (route: grok, then Codex, then Claude tdd-guide; the coordinator verifies every artefact)
1. **Pin commit, alone (0.5 h).** Build the fixture as in P-9 and run `main --resamples 200 --seed <fixed>`. Pin the sha256 of the JSON and MD, the sorted top-level key set, and `kind == "market_calibration_scan/v2"`. The pin is green at HEAD.
2. **RED tests (§6), 1 h.** Every new test fails at HEAD. The guards listed in §6 are untouched.
3. **Implement (2–3 h).**
   - `edge_bin(p_side, ask)`. Edge = p_side − float(ask), where p_side = p_yes for YES and 1 − p_yes for NO. Bins: `<0`, `0-5` [0,.05), `5-10` [.05,.10), `10-20` [.10,.20), `>20` (≥ .20). The edge is gross of fee; `excess` already charges the fee.
   - **Order in `main` with the flag** (`_run_forecast_p`):
     - (i) `_refuse_live_root`; `--out` must not exist; the script must equal HEAD. Any failure → exit 4.
     - (ii) `_load_forecast_p` validates the whole file. Any failure → exit 3, before truth is loaded or `collect` runs.
     - (iii) Load truth, `collect`, `validity_reasons`. These are unchanged.
     - (iv) `_join_forecast`. Unmatched observations are dropped before `_day_matrices`, which takes them out of both s_mat and n_mat. Any look-ahead row → exit 3, nothing written.
     - (v) `build_scan(..., key_fn=edge key)`.
     - (vi) `build_report(kind="market_calibration_scan/v2+forecast_p")` plus `_forecast_block`.
     - (vii) `write_outputs(exclusive=True)`.
   - **Without the flag** the path, `kind`, keys and bytes are unchanged.
   - **`forecast_p` block:**
     - `source_id`
     - `matched_observations`
     - `unmatched_observations` as {`forward`, `pre_forward`}
     - `unmatched_station_days_forward`
     - `non_high_rows`, `extra_columns`
     - `input_sha256` for the p file and the truth file
     - `catalog_listing_sha256`: sha of the sorted depth-directory names plus their summed file bytes
     - `script_git_sha`, `run_id` (the `--out` basename), `seed`, `resamples`
     - `tested_cells` and `spa_p` are not copied; they already live in `multiplicity`.
4. **Gate (≈ 25 min).** One delegation runs `scripts/ci/run_tests_no_egress.sh` on the primary tree, with basetemp at `<wt>/.pytest-tmp/`, and returns ≤ 15 lines. Then `lint-imports` from the tree root. Read EXIT before any push.
5. **First real run (coordinator).** Only after GAP-2's file exists and the GAP-4/STRATEGY-ITERATION PREREG is frozen. One look. The output is committed per A-1(c).

## 5 Acceptance (frozen) and explore gate
- **Acceptance:**
  - the pin (sha, key set, `kind`) is unchanged
  - every §6 test is green
  - the named guards are unmodified and green
  - full gate EXIT=0
  - no `forecast_p` key and no `edge_bin` in the default JSON
- **The explore gate is coordinator arithmetic on the run file, not code.** A cell passes when `p_one_sided × K_cum ≤ 0.05` AND `ci95_lo > m`, with m ∈ {0.02, 0.03, 0.05}. `ci95_lo` is the 2.5-percentile bootstrap bound, i.e. the one-sided 97.5% lower bound. The scan emits no verdict.
- **Budget.** N = 240 cell-units and D = 28 days, never restarted; R ≤ 3. Each run debits `multiplicity.tested_cells`. Maximum keys per flagged run: 3 windows × 2 sides × 10 ask bins × 5 edge bins = 300. That is more than N, so the PREREG must state how a run whose `tested_cells` exceeds the remaining N is treated before it runs (STRATEGY_ITERATION D5's call, not GAP-3's).
- **K_cum seeding:** M1 (35 cells), P2, Card A legs 1–2, Card E, WP-7b, AUD-02, plus each GAP-3 run's `tested_cells`.
- **Bootstrap.** `_bootstrap_stats` (`:578-600`) resamples whole calendar days with every station summed into the row (`:550`). It is kept unchanged for byte identity. With about 30 forward day-blocks, percentile-bootstrap coverage falls below nominal. The PREREG must disclose the day-block n and this shortfall (A-7/P-8).

## 6 Tests (RED first) and gate
- **In `test_market_calibration_scan.py`:** `test_default_run_fixture_sha256_key_set_and_kind_pinned`. This is a characterisation pin, committed alone.
- **In `test_market_calibration_scan_forecast_p.py`** (all RED at HEAD):
  - `test_edge_bin_boundaries`, at −0.0001, 0, 0.0499, 0.05, 0.10 and 0.20
  - `test_instrument_id_join_matches_observation_rung_and_window`
  - `test_forecast_cell_built_by_keyword_edge_bin_not_shifted_into_n`
  - `test_default_cells_and_best_cell_omit_edge_bin`
  - `test_unmatched_observation_leaves_numerator_and_denominator`
  - `test_unmatched_counts_split_forward_and_pre_forward`
  - `test_forecast_p_refuses_any_row_before_2026_10_02`
  - `test_forecast_p_bad_rows_refused`, covering duplicate, out-of-range or NaN p, bad ns, unknown window and unparseable instrument
  - `test_forecast_p_multiple_source_ids_refused`
  - `test_forecast_p_non_high_rows_counted_and_ignored`
  - `test_forecast_p_lookahead_equal_or_later_available_at_refused`
  - `test_refusal_order_exit3_before_collect_and_writes_nothing`
  - `test_existing_out_dir_refused_exit4_even_when_empty`
  - `test_script_differs_from_head_refused_exit4`, which monkeypatches the git helper
  - `test_run_file_carries_tested_cells_spa_p_and_input_shas`
  - `test_forecast_p_markdown_has_edge_column`
  - `test_default_run_reads_no_p_file_and_emits_no_forecast_p_block`
- **Named whole-tree guards (unmodified):**
  - `test_scan_reads_no_model_output` (`:259`)
  - `test_orchestrators_are_short_and_flat` (`:632`)
  - `test_out_dir_refuses_live_data_root` (`:327`)
  - `tests/unit/test_maker_design_score.py`, `tests/unit/test_no_longshot_pooled_test.py` and `tests/unit/test_p2_nbp_ask_murphy.py`
  - `lint-imports`
- **Gate:** `scripts/ci/run_tests_no_egress.sh` on the primary tree; read EXIT before push.

## 7 Pins, isolation, risks
- **Live-root path conflict:** resolved per A-1. The guard is not relaxed.
- **`--out` is a directory.** The run file is `<run_id>/market_calibration_scan.json` plus `.md`.
- **Most 4-key cells will be untested.** With about 30 forward days × 5 stations, most fall below `MIN_CELL_N`=30 / `MIN_CELL_DAYS`=5 (`:104-105`). This is expected and reported as `untested_cells`.
- **The sha pin is sensitive to numpy and format changes** and fails loudly. A re-pin is only allowed with a coordinator sidecar note.
- **The p-file contract is shared with GAP-2.** Any drift in the GAP-2 schema refuses the file (exit 3); it never degrades silently.
- **Invariants:**
  - Nautilus is immutable; `allow_short` stays False.
  - No safety, settlement, contract, pin or NO-SEND test is weakened.
  - No operator caps are assigned; enablement and the egress firewall are untouched.
  - `iem_cli_fetch.fetch` is never called.
  - No credentials and no order ids.

## 8 Operator decisions
- None. The harness-ruling placement was decided by the coordinator under A-6, and the guard is unchanged (P-1). Sizing and caps are not involved.

## 9 Citations
- **Verified in r1:**
  - code: `:4`, `:45`, `:104-105`, `:138`, `:152-156` (WINDOWS = 3), `:176-185` (no `instrument_id` on `Observation`), `:270`, `:399`, `:472`, `:477-540`, `:543-565`, `:615-699`, `:758-795`, `:798-882`; `best_cell_by_t` is at `:673`
  - tests: test lines `:60`, `:82`, `:91`, `:259`, `:327`, `:632`
  - dependents' imports, and that their tests exist
  - `plan_r1_delta.md:19` D4 text; `scripts/analysis/prereg_precommit_check.py` exists
- **Not verified:** see below.

Still-unverified citations:
- K_cum seed counts for P2, Card A, Card E, WP-7b and AUD-02, and the on-disk location of the ledger.
- The `maker_stage0_replay.py:45` precedent, and which path `prereg_precommit_check.py` sums today.
- That GAP-2's `instrument_id` equals the depth-directory name including `.POLYMARKET_US` (assumed here; GAP-2 r1 must state it).
- That nothing under `docs/evidence/strategy_iteration/runs/` is gitignored.
