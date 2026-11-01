# GAP-3 CONFIDENCE-BINNED-BACKTEST — plan r0

Status: r0. Peer review pending: **architect** and **python-reviewer**.

## 1 Objective
`scripts/analysis/market_calibration_scan.py` can only show which ask band is mispriced. It cannot show whether a mispriced band is one a forecast can pick out. The flag `--forecast-p PATH` adds a forecast-edge axis so the scan can answer one question: do rungs where the forecast is more confident than the ask beat price plus fee? That is the band GAP-4 has to register for winning trades. The scan stays a screen (FQ-R14 `SCREENING_NOTICE`), so a positive cell is never nomination evidence.

## 2 Preconditions and dependencies
- **GAP-2 is a hard dependency.** Its forward per-rung p file is the only input to `--forecast-p`. The schema below is what GAP-3 requires of GAP-2.
- Harness route: this is the "one-flag harness route" from STRATEGY_ITERATION r0/r1, which extends the existing scan rather than adding a new evaluator. If the operator rules it is new evaluator logic, it falls under the same exception as GAP-2. That exception covers one flag on this one script and nothing else.
- The holdout ruling cl.1–cl.4 applies. Only rows from the forward window (≥ 2026-10-02) are admissible.

## 3 Scope
- **In scope:** `scripts/analysis/market_calibration_scan.py`, meaning `main` (`:860-882`), `_day_matrices` (`:543-565`), `CellKey` (`:540`), `Cell`/`ZeroVarianceCell.to_dict` (`:493-528`), `_multiplicity` (`:647-680`) and `write_outputs` (`:847-857`). Tests go in `tests/unit/test_market_calibration_scan_forecast_p.py` (new) plus a pin added to `tests/unit/test_market_calibration_scan.py`.
- **Not in scope:** windows, ask deciles, `excess()` (`:472`, which is hit − (ask + fee)), the bootstrap, SPA, the markdown table, the live-root guard, any strategy or exec code, and the explore-gate arithmetic.
- **Required p-file schema (CSV).** Header exactly `station,climate_day,window,rung,p_yes,issued_ts_ns,source_id`. `rung` and `window` use the same labels as `Observation.rung` and `.window`. The scan refuses the whole file (exit 3, nothing written) on any of:
  - a duplicate key
  - `p_yes` outside [0,1]
  - a row with `climate_day < 2026-10-02` (string-parsed `dt.date`, constant `FORWARD_START = dt.date(2026,10,2)`)
  - `issued_ts_ns > ref_ts_ns` for a matched observation (raises the existing `LookAheadError` class)

## 4 Steps (route: grok, then Codex, then Claude tdd-guide; the coordinator verifies)
1. **Pin first (0.5 h).** Run the default scan at HEAD 9e46cd1c on a small fixture (the existing test fixture builder; `--resamples 200 --seed` fixed). Record the sha256 of `market_calibration_scan.json` and `.md` as constants in the test.
   - Byte identity with `docs/evidence/m1/market_calibration_scan_v2.json` itself cannot be re-run, because the live catalog has grown since. Identity is therefore guaranteed through the code path: the fixture sha pin, plus the rule that no new key is emitted without the flag.
2. **RED tests (§6), 1 h.** Every new test fails at HEAD.
3. **Implement (2–3 h).**
   - `edge_bin(p_side, ask)`: edge = p_side − ask, where p_side = `p_yes` for YES and 1 − `p_yes` for NO. Bins are `<0` (edge < 0), `0-5` [0, 0.05), `5-10` [0.05, 0.10), `10-20` [0.10, 0.20) and `>20` (≥ 0.20). The edge is gross of fee by design; `excess` already charges the fee.
   - With the flag, the key becomes (window, side, ask_bin, edge_bin). Without it, the key stays the 3-tuple, so the sorting, JSON and markdown are unchanged.
   - Join on (station, climate_day, window, rung). An observation with no p row is dropped before `_day_matrices`, which takes it out of both s_mat (numerator) and n_mat (denominator). Drops are counted in `forecast_p.unmatched_observations`, and `forecast_p.unmatched_station_days` is also reported.
   - With the flag, the report gains a `forecast_p` block holding:
     - `tested_cells`, which is `len(keys)` after `MIN_CELL_N`=30 / `MIN_CELL_DAYS`=5
     - `spa_p` and `reality_check_p` from `_max_tests`
     - `input_sha256` for the p file and the truth file, plus `catalog_listing_sha256` (sha of the sorted depth-directory names and sizes)
     - `script_git_sha`, `run_id`, `seed`, `resamples`
   - Immutable run file: with the flag, `write_outputs` opens with mode `"x"` and refuses an existing run dir or file (exit 4). Without the flag, the existing overwrite behaviour is kept.
4. **Gate (≈ 25 min).** One delegation runs `scripts/ci/run_tests_no_egress.sh` on the primary tree and returns at most 15 lines. Read EXIT before any push. Also run `lint-imports` from the tree root.
5. **First real run (coordinator).** Done only after GAP-2's file exists and the GAP-4/STRATEGY-ITERATION PREREG is frozen. One look.

## 5 Acceptance (frozen) and explore gate
- **Acceptance:**
  - the default fixture sha is unchanged
  - every §6 test is green
  - the full gate EXIT=0
  - no new key appears in the default JSON
- **The explore gate is computed by the COORDINATOR from the run file, not by new code.** A cell passes when `p_one_sided × K_cum ≤ 0.05` AND `ci95_lo > m`, with m taken from the grid {0.02, 0.03, 0.05}. `ci95_lo` is the scan's 2.5-percentile bootstrap bound, which is the one-sided 97.5% lower bound. The scan emits no verdict.
- **Budget:** N = 240 cell-units and D = 28 days, never restarted. Each run debits its `tested_cells` (with the flag, up to 5× the old count per run). R ≤ 3.
- **K_cum seeding list (comparison ledger):**
  - M1 (35 cells)
  - P2 NBP-ask Murphy
  - Card A leg 1 and leg 2
  - Card E
  - WP-7b
  - AUD-02
  - then plus each GAP-3 run's `tested_cells`
- **Bootstrap block, verified.** `_bootstrap_stats` (`:578-600`) is a **calendar-day block across all stations**, not a station-day block. s_mat rows are `climate_day` values, with every station summed into the row (`_day_matrices :550`), and the resample is multinomial over days. This is **conservative** compared with station-day blocking: it keeps same-day cross-station correlation from shared synoptic regimes and gives fewer, larger blocks, so the CIs are wider. It is kept, both on those grounds and because switching to station-day would break byte identity. The caveat is that about 30 forward day-blocks means percentile-bootstrap coverage is slightly below nominal. The reviewers should rule on whether that needs disclosure in the PREREG.

## 6 Tests (RED first) and gate
- In `tests/unit/test_market_calibration_scan.py`: `test_default_run_fixture_sha256_pinned_json_and_md`. This is a characterisation pin that is green at HEAD and must stay green after the change.
- In `tests/unit/test_market_calibration_scan_forecast_p.py`:
  - `test_forecast_p_refuses_any_row_before_2026_10_02` (RED; asserts nothing is written)
  - `test_edge_bin_boundaries` (−0.0001, 0, 0.0499, 0.05, 0.10, 0.20)
  - `test_forecast_p_cell_key_has_edge_bin`
  - `test_station_day_absent_from_p_file_leaves_numerator_and_denominator`
  - `test_forecast_p_lookahead_issued_after_ref_refused`
  - `test_forecast_p_duplicate_and_out_of_range_rows_refused`
  - `test_run_file_exclusive_create_refuses_existing`
  - `test_run_file_carries_tested_cells_spa_p_and_input_shas`
  - `test_default_run_emits_no_forecast_p_block`
- The existing live-root-guard test must stay unmodified and green.
- Gate: `scripts/ci/run_tests_no_egress.sh`, with basetemp inside the worktree (`<wt>/.pytest-tmp/`).

## 7 Pins, isolation, risks
- **[HIGH] Path conflict.** `_refuse_live_root` (`:840-844`) refuses every path under `~/.local/share/breezy`. The STRATEGY_ITERATION run path `~/.local/share/breezy/derived/strategy_iteration/runs/<run_id>.json` is therefore refused today. The guard must not be relaxed (no carve-out; L-12). The default proposed here is to write run files to `docs/evidence/strategy_iteration/runs/<run_id>/market_calibration_scan.json` (git-tracked, immutable, L-75) and amend the r1 path to match. Reviewers to confirm.
- `--out` is a **directory** in the current CLI, so the run file is `<out>/market_calibration_scan.json` rather than `<run_id>.json`. Keeping it that way preserves default behaviour.
- With about 30 forward days × 5 stations, most 4-key cells fall below `MIN_CELL_N` and are untested. That is expected; `untested_cells` is reported.
- The fixture sha pin is sensitive to numpy or format changes, so it fails loudly. Never re-pin without a coordinator sidecar note.
- Invariants restated: Nautilus immutable; `allow_short` False; no safety, settlement, contract, pin or NO-SEND test weakened; no operator caps assigned; enablement and egress firewall untouched; `iem_cli_fetch.fetch` never called; no credentials and no order ids.

## 8 Operator decisions
- Whether the one-flag route sits inside the existing-harness ruling or under the GAP-2 exception (§2). Nothing else; sizing and caps are not involved.

## 9 Citations not verified
- K_cum seed counts for P2, Card A/E, WP-7b and AUD-02, and the ledger's on-disk location (I did not read STRATEGY_ITERATION r0/r1).
- The r1 run-file path is taken from the shared context and not checked against plan_r1_delta.md.
- The `WINDOWS` count, and therefore the maximum cells per run, was not read.
- I have not confirmed that a fixture builder exists in `tests/unit/test_market_calibration_scan.py`.
