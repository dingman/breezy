# Point-in-time classification — 2026-09-21 (AUD-11)

Survey of every file under `scripts/analysis/` and every backtest/replay
entrypoint under `src/breezy/runtime/`. Gap G-08 plus G-15(e) (look-ahead
status of the remaining study paths).

Classes:

- **(a) decision-time-only.** A record that can influence a decision is
  available strictly before that decision, or the feed is real `ts_init` and
  a guard refuses anything later. Settlement *labels* that are the outcome of
  an already-taken decision are not look-ahead.
- **(b) evidence diagnostic.** Point-in-time is intentionally relaxed for a
  named narrower purpose. Output is ineligible for PREREG or promotion.
- **(c) not applicable.** Does not feed a decision engine and does not score
  a trading decision against an outcome.

Shared guard: `breezy.runtime.point_in_time_guard.assert_available_before_decision`.
`ts_init > decision_ts_init_ns` is look-ahead. Equal `ts_init` is available.
One exception carries every offender, in input order. A missing integer
`ts_init` fails closed.

`ts_init` provenance is one of: **real** (capture or retrieval timestamp),
**harness** (assigned by the harness, no real-world referent), **mixed**,
or **n/a**.

No file under `scripts/analysis/` other than
`run_weather_strategy_backtests.py` restamps a weather or forecast timestamp
earlier than its real retrieval. `quote_tape_ingest_cli.py:618` states that
ingest does not restamp. Step 7 of the plan therefore adds no further call
sites: the other (a) rows already refuse look-ahead in their own guards
(cited below) and do not manufacture an earlier `ts_init`.

## Default-branch documenting assertion

Filled in after the captured-tape run. See the "Tape evidence" section at
the bottom. The code path is
`scripts/analysis/run_weather_strategy_backtests.py` (`main`, default
branch): boundary is `max(last_market_data_ts_init) + 1s`, which is the
same instant `_synthesize_close` uses. `N = len(exc.offending_records)`.
Climate-day records are not passed as `weather_data` either way.

## `scripts/analysis/`

| Entrypoint | Decision engine | Class | Evidence | Guard | `ts_init` provenance |
|---|---|---|---|---|---|
| `archive_correction_probe.py` | none | (c) | module purpose, line 1: archive correction probe, not a decision feed | n/a | n/a |
| `asos_cache_freshness_check.py` | none | (c) | line 1: cache freshness | n/a | n/a |
| `asos_recent_refresh.py` | none | (c) | line 1: ASOS refresh ahead of a scan | n/a | n/a |
| `band_decider_stage0b_screen.py` | none | (c) | line 1: read-only stage-0b screen | n/a | n/a |
| `capture_no_side_preview.py` | none | (c) | line 1: evidence capture of a preview, no engine | n/a | n/a |
| `cli_basis_adverse_selection_probe.py` | none (archive rates) | (c) | line 1: archive-side proxy, not an engine feed | n/a | n/a |
| `cli_basis_boundary_study.py` | none | (c) | line 1: climatology of the basis boundary | n/a | n/a |
| `cli_basis_hourly_profile_study.py` | none | (a) | `is_admissible_hour` line 159: hour alone, no realized peak can reach it | signature admits only `hour` | n/a (clock hour, not a record `ts_init`) |
| `cli_basis_offer_gate_scan.py` | none | (c) | line 1: does the venue offer the tail; tape read, no engine | n/a | real (quote tape) |
| `cli_basis_offer_gate_settlement.py` | none | (c) | line 1: did the offered rung win; settlement is the label | n/a | real |
| `cli_basis_setup_win_rate_study.py` | none | (c) | line 1: archive `P(win\|setup)` | n/a | n/a |
| `crh_group_sequential_boundaries.py` | none | (c) | line 1: boundary table for PREREG v2, no tape | n/a | n/a |
| `current_rung_hold_exit_window_study.py` | none (post-fill study) | (a) | calls `exit_window_core.build_exit_timeline`, which keeps `ts_init > filled_at_ns` | filter in `exit_window_core.py:198` | real (depth `ts_init`) |
| `current_rung_hold_monitor_hypothetical_hold.py` | none | (a) | delegates to `monitor_hypothetical_core.replay_monitor` | `LookAheadError` if `ts <= take.ts_ns` (`monitor_hypothetical_core.py:302`) | real |
| `current_rung_hold_paper_replay.py` | `run_backtest` via `paper_replay` | (b) | line 1 and line 8: `MECHANISM TEST -- NO VERDICT`; settlement from the FINAL climate day | textual marker; market-data window guard is `paper_replay._assert_no_foreign_market_data`. Machine `mechanism_test_only` is on the whole-tape bundle, not this driver's own scored-trial store | mixed: real tape; observation receipt = observed + declared lag |
| `current_rung_hold_resting_bid_study.py` | none | (c) | line 1: offline counterfactual driver | core guard in `resting_bid_core.py` | real |
| `exit_window_core.py` | none | (a) | `build_exit_timeline` line 172: post-fill frames only | filter `ts_init > filled_at_ns` (line 198), not a raise | real |
| `exit_window_report.py` | none | (c) | line 1: renders the exit-window study | n/a | n/a |
| `family_tally_v2.py` | none (PREREG consumer) | (c) | `read_scored_trials` / `load_family_manifest` | `assert_prereg_directory_eligible` refuses `mechanism_test_only` | n/a |
| `fill_time_count.py` | none | (c) | line 1: fill-time count for the structural-dead stop | n/a | n/a |
| `forecast_cheap_screen_wp7.py` | none | (a) | `_assert_reference_precedes` line 556; window is `local_date == climate_day` and `hour_lst < window` (line 545) | `PreWindowLookAheadError` when `reference.ts_ns >= take` | real |
| `forecast_climate_day_map.py` | none | (c) | line 1: pure TXN-to-climate-day map | n/a | n/a |
| `forecast_conditional_corpus.py` | none | (c) | line 1: joined corpus and leak guards for WP-6 | corpus leak guards | real |
| `forecast_conditional_model_study.py` | none | (c) | line 1: offline MOS-vs-climatology study | n/a | real |
| `forecast_conditional_report.py` | none | (c) | line 1: report renderer | n/a | n/a |
| `forecast_conditional_scoring.py` | none | (c) | line 1: scoring metrics for the offline study | n/a | n/a |
| `forecast_tape_screen.py` | none | (c) | line 1: fee arithmetic, no engine | n/a | n/a |
| `forecast_txn_climate_day_cli_alignment.py` | none | (c) | line 1: CLI-truth alignment of a frozen map | n/a | real |
| `generate_current_rung_hold_archive_table.py` | none | (c) | line 1: frozen archive table generator | n/a | n/a |
| `h4_preliminary_economic_read.py` | none | (c) | line 1: descriptive ask read, not an engine | n/a | real |
| `hourly_ask_relative_edge.py` | none | (a) | `assert_as_of` line 246; `hour_window_bounds` line 304 requires date and hour | `AsOfViolation` when `reference_ts_ns > decision_ts_ns` (equal is allowed) | real |
| `k1_cheap_open_settlement.py` | none | (c) | line 1: cheap-rung settlement rate; settlement is the label | n/a | real |
| `k1_kalshi_prior.py` | none | (c) | line 1: Kalshi prior for the same question | n/a | real |
| `ladder_ev_afternoon_coverage_census.py` | none | (c) | line 1: coverage census, no decision feed | n/a | real |
| `live_family_tally.py` | none (tally consumer) | (c) | `read_scored_trials(store_dir)` in `main` | `assert_prereg_directory_eligible` | n/a |
| `ma_prelock_winner_ask_study.py` | none | (c) | line 1: read-only pre-lock measurement | n/a | real |
| `mb_current_rung_edge_study.py` | none | (c) | line 1: p_hold x ask measurement | n/a | real |
| `monitor_hypothetical_core.py` | none | (a) | `replay_monitor` line 283 | `LookAheadError` if depth or observation `ts <= take.ts_ns` (line 302) | real |
| `monitor_hypothetical_report.py` | none | (c) | line 1: report aggregation | n/a | n/a |
| `mos_txn_occupancy.py` | none | (c) | line 1: pure CSV occupancy stats | n/a | n/a |
| `pmr_climatology_study.py` | none | (c) | line 1: climatology of the late-rise hazard | n/a | n/a |
| `portfolio_roi_report.py` | none | (c) | loads family manifests | `load_family_manifest` calls `assert_prereg_directory_eligible` on the manifest directory | n/a |
| `position_monitor_nightly_report.py` | none | (c) | nightly shadow report; loads a family manifest | same manifest guard | n/a |
| `preliminary_final_revision_rate_study.py` | none | (c) | line 1: revision-rate measurement, not a decision feed | n/a | real (`retrieved_at_ns`) |
| `price_conditional_settlement_analysis.py` | none | (a) | line 386 area: `anti_lookahead: leave_one_year_out` | leave-one-year-out; not the shared `ts_init` guard | real |
| `receipt_lag_probe.py` | none | (c) | line 1: measures receipt lag; does not feed an engine | n/a | real |
| `resting_bid_core.py` | none | (c) | pure counterfactual core | n/a | real |
| `resting_bid_report.py` | none | (c) | line 1: renderer | n/a | n/a |
| `run_weather_strategy_backtests.py` default `main` | `run_backtest` | (a) | restamp removed; `weather_data` is `[]`; guard call in `main` | `assert_available_before_decision` on real climate-day `ts_init`, boundary = last market-data `ts_init` + 1s | real for climate days; harness for synthesized `InstrumentClose` |
| `run_weather_strategy_backtests.py` `_run_live_capture` | `run_backtest` | (a) | `_load_climate_day_records` feeds real `ts_init` (not restamped), line ~1559 | harness settlement ordering; no restamp. Shared guard is not applied here because in-window finals are supposed to be visible | real |
| `score_live_trials.py` | none | (a) | scores filled live trials against settlement truth | settlement chain; `read_scored_trials` refuses a mechanism-test directory | real (live fills, NWS retrieval) |
| `settlement_alignment_cache.py` | none | (c) | path constants | n/a | n/a |
| `settlement_alignment_diagnosis.py` | none | (c) | cache-only diagnosis | n/a | n/a |
| `settlement_alignment_study.py` | none | (c) | offline alignment study, outside the engine | n/a | real |
| `settlement_bucket_gate.py` | none | (c) | cache-only bucket gate | n/a | n/a |
| `settlement_bucket_guard_band.py` | none | (c) | post-hoc exploratory sweep | n/a | n/a |
| `settlement_programme_report.py` | none | (c) | renders JSON | n/a | n/a |
| `settlement_truth_dataset.py` | none | (c) | historical settlement-truth dataset | n/a | real |
| `structural_dead_stop.py` | none | (c) | PREREG stop; loads a family manifest | manifest directory guard | n/a |
| `tape_arrow_columns.py` | none | (c) | shared Arrow mechanics | n/a | n/a |
| `weather_strategy_backtest_lib.py` | none | (c) | pure helpers; no engine, no timestamps | n/a | n/a |
| `whole_tape_paper_replay.py` | via paper replay | (b) | `LOOK_AHEAD_CAVEAT` line 59; highest-revision FINAL used as the score | `mechanism_test_only: true` on trial rows and parquet schema metadata (`_write_mechanism_trials`) | mixed: real tape; settlement may post after the decision |
| `wp7_realised_pnl_falsification.py` | none | (c) | line 1: falsification of an already-screened take list | screen's own as-of guard | real |
| `wp7b_market_as_forecaster.py` | none | (a) | `build_rung_probabilities` line 280 | `LookAheadError` when `cycle_runtime_ns > decision_ns` | real |
| `pre_registration_2026-08-24T192458Z.md` | none | (c) | pre-registration document, not code | n/a | n/a |
| `pre_registration_2026-08-24T192643Z.md` | none | (c) | pre-registration document | n/a | n/a |
| `pre_registration_2026-09-02T044737Z.md` | none | (c) | pre-registration document | n/a | n/a |
| `pre_registration_2026-09-02T055741Z.md` | none | (c) | pre-registration document | n/a | n/a |
| `pre_registration_2026-09-02T061500Z.md` | none | (c) | pre-registration document | n/a | n/a |
| `pre_registration_2026-09-02T062000Z.md` | none | (c) | pre-registration document | n/a | n/a |

## `src/breezy/runtime/` backtest and replay entrypoints

Other modules under `src/breezy/runtime/` are live-node wiring (settings,
health, quote-tape recorder, supervisor, order enablement). They do not
construct a `BacktestEngine` or score a replay. Class **(c)**. Provenance
**n/a**. They are not listed row-by-row.

| Entrypoint | Decision engine | Class | Evidence | Guard | `ts_init` provenance |
|---|---|---|---|---|---|
| `backtest_harness.run_backtest` / `build_backtest_engine` | `BacktestEngine` | (a) | `add_data` around line 786; settlement ordering refuses an `InstrumentClose` whose `ts_init` does not strictly follow that instrument's last market-data `ts_init` | `assert_settlement_invariants` (unchanged). Callers that inject weather call the shared guard themselves | mixed: caller-supplied market data (real when it is the tape); synthesized closes are harness-assigned |
| `backtest_feed.as_backtest_data` | none (wraps records) | (c) | passes `ts_init` through; no clock | n/a | unchanged from the record |
| `backtest_order_guard` | none | (c) | refuses order shapes the venue cannot model, not timestamps | n/a | n/a |
| `paper_replay` | `run_backtest` | (a) | `_assert_no_foreign_market_data`; `ImpossibleFillPriceError` | both unchanged. A non-close record outside the capture window is refused. A fill better than the decision-instant ask is refused | real capture for book and quotes; observation receipt is observed-at plus the declared lag |

## Tape evidence

**BLOCKED, 2026-09-24 -- memory envelope, not missing data.** The script's
default branch (`uv run python scripts/analysis/run_weather_strategy_backtests.py`,
i.e. `run_weather_strategy_backtests.main()` with no CLI arguments beyond
`--output-dir`, reading the default `DEFAULT_QUOTE_CATALOG_PATH`
(`/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`) and
`DEFAULT_WEATHER_CATALOG_ROOT` against the captured 2026-08-30 NYC/MIA tape,
per plan §7 step 5) was run twice under the mandated memory cap
(`systemd-run --user --scope -p MemoryMax=6G --`), once against a
`git archive 1780ccb` (pre-refactor) export and once against this worktree
(post-refactor, commit `5e10107`). **Both runs were killed by the kernel OOM
killer inside the cgroup before producing any stdout** -- neither reached the
`_select_tape_instruments` print lines, let alone `main`'s documenting
`assert_available_before_decision` call. Data is present and was not the
blocker: the quote-tape catalog carries 2026-08-30 `binary_option`,
`order_book_depths`, `custom_venue_settlement_snapshot` etc. partitions, and
the weather catalog carries the NYC/MIA `NwsClimateDay` records for that day.

Pre-refactor run (`1780ccb` export), `journalctl --user` for
`run-p668812-i42569400.scope`:
```
Sep 24 19:56:37 ... Started run-p668812-i42569400.scope - [systemd-run] ... run_weather_strategy_backtests.py --output-dir <scratch>/pre_output.
Sep 24 20:03:00 ... run-p668812-i42569400.scope: The kernel OOM killer killed some processes in this unit.
Sep 24 20:03:00 ... run-p668812-i42569400.scope: Failed with result 'oom-kill'.
Sep 24 20:03:00 ... run-p668812-i42569400.scope: Consumed 6min 1.993s CPU time over 6min 23.684s wall clock time, 6G memory peak, 1.5G memory swap peak.
```
stdout: empty. stderr: only the `systemd-run` "Running as unit" banner line.

Post-refactor run (this worktree, commit `5e10107`), `journalctl --user` for
`run-p690465-i42609296.scope`:
```
Sep 24 20:03:37 ... Started run-p690465-i42609296.scope - [systemd-run] ... run_weather_strategy_backtests.py --output-dir <scratch>/post_output.
Sep 24 20:09:43 ... run-p690465-i42609296.scope: The kernel OOM killer killed some processes in this unit.
Sep 24 20:09:43 ... run-p690465-i42609296.scope: Failed with result 'oom-kill'.
Sep 24 20:09:43 ... run-p690465-i42609296.scope: Consumed 5min 47.131s CPU time over 6min 6.482s wall clock time, 6G memory peak, 1.6G memory swap peak.
```
stdout: empty. stderr: only the `systemd-run` "Running as unit" banner line.

Both runs behave identically under the cap (~6 minutes wall clock, ~6G RSS
peak, ~1.5-1.6G swap peak, killed at the same point in the same phase --
the quote-tape catalog read/`_select_tape_instruments` step, before any of
the script's own `print` statements fire), so this is the script's
structural memory footprint against the full 2026-08-30 tape (consistent
with the MEMORY.md lesson that nightly studies of this shape run
10-24GB), not a regression introduced by this item's refactor. The host
had only ~1.6GB of free swap and ~8.3GB free RAM at the time (other
processes, including the live node, were resident), which likely tightened
the effective ceiling below a clean 6G.

**Consequence for this item's acceptance criteria (plan §8):** the
`real_observed`/scenario byte-identical-output comparison, the
`naive`/`realistic` per-strategy trading-result comparison, and the
documenting `assert_available_before_decision` raise/no-raise outcome for
this tape are **not captured** -- the run never reaches that code. This is
reported as a blocker, not fabricated. The refactor's correctness for the
selection-helper and the guard is instead evidenced by: (1) the RED->GREEN
unit tests in `tests/unit/test_run_weather_strategy_backtests_selection.py`
and `tests/unit/test_point_in_time_guard.py`, which exercise the same code
paths against small synthetic fixtures without loading the full tape, and
(2) the AUD-11 finding-1 fix (`5e10107`), which is verified the same way
(RED against `HEAD`, GREEN in this worktree; see that commit message). A
follow-up either needs a higher memory allowance explicitly authorized
above this task's 6G cap, or a quiet window with more free system memory
(this task's brief does not authorize either change; both are coordinator
decisions).

## 2026-09-26 rerun at 12G -- still OOM; root cause identified (not fixed)

Coordinator-authorized rerun at a higher cap, in the 22:58-01:50Z quiet
window (host: ~30G RAM, ~19G available, live node and quote-tape recorder
left running throughout, untouched). Command (unchanged, primary tree,
commit `41802df`, branch `feat/data-capture-and-risk`):

```
systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=2G -- \
  uv run python scripts/analysis/run_weather_strategy_backtests.py \
  --output-dir <scratch>/aud11_output
```

`journalctl --user` for `run-p1926925-i56437347.scope`:

```
Sep 26 22:58:04 ... Started run-p1926925-i56437347.scope ...
Sep 26 23:07:30 ... The kernel OOM killer killed some processes in this unit.
Sep 26 23:07:31 ... Failed with result 'oom-kill'.
Sep 26 23:07:31 ... Consumed 10min 32.530s CPU time over 9min 26.906s wall
clock time, 12G memory peak, 379.4M memory swap peak.
```

stdout/stderr (`/home/jon/.cache/aud11/run1.log`): only the `systemd-run`
banner plus `uv`'s own build/install lines (`Building breezy`, `Installed 1
package`); `EXIT_CODE=137`. As with both 2026-09-24 runs, the process never
reached any of the script's own `print` statements, so the documenting
`assert_available_before_decision` call is again **not captured** at 12G
either -- doubling the cap did not change where the process dies, only
delayed it (6min23s wall / 6G peak on 09-24 vs 9min27s wall / 12G peak
tonight), which is itself evidence the footprint scales with the cap rather
than converging.

**Root cause, located by inspection (no source edited per this task's
constraint):** `_select_tape_instruments`
(`scripts/analysis/run_weather_strategy_backtests.py:679-721`) is called
from `main` (line 1802) with no station/date filter of any kind. It calls
`catalog.instruments()` once, then for **every** instrument returned --
not just the 2026-08-30 NYC/MIA tape's instruments -- calls
`catalog.order_book_depth10(instrument_ids=[instrument.id.value])` and
`catalog.quote_ticks(instrument_ids=[instrument.id.value])` and retains
every returned Nautilus object in `depths_by_id`/`quotes_by_id` (lines
690-698), before `select_tradable_instrument_ids` ever runs to pick the
handful that are actually tradable (line 700). `DEFAULT_QUOTE_CATALOG_PATH`
(line 346-348) points at the live, shared, ever-growing capture catalog
(`/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us`), not a
2026-08-30-scoped export: it is 107G on disk today, with 765
`quote_tick/<instrument>` partitions and 815 `order_book_depths/<instrument>`
partitions covering 2026-09-01 through 2026-09-27 across 5 cities -- only 5
of those partitions belong to 2026-08-30. The function therefore
materialises the full multi-week tape's depth10 and quote history into
Python objects in memory before discarding all but 5 instruments' worth,
which is why memory scales with calendar days captured (growing daily as
the recorder keeps running) rather than with the fixed 2026-08-30 tape the
script is meant to prove against, and why raising the cgroup cap alone
cannot converge -- the catalog will keep growing past any fixed cap.

**Bounded-read fix needed (not applied -- source is read-only for this
task):** `_select_tape_instruments` needs to narrow to the target
instruments *before* calling `order_book_depth10`/`quote_ticks`, e.g. by
filtering `catalog.instruments()` to the known `("NYC","MIA")` /
`CLIMATE_DAY` (2026-08-30) bucket-id pattern already used elsewhere in this
file (`read_weather_bucket_facts`), or by passing a `start`/`end` window to
the catalog query methods if the installed `ParquetDataCatalog` version
supports it, so only the ~5 in-scope instrument partitions are ever
materialised. Note for whoever picks this up: S3a's coalesced-read change
(merged since 2026-09-24) may already reduce per-partition overhead, but it
does not change the fact that all 765+/815+ instrument partitions are read
before filtering -- the fix is a filter-before-read reordering, not a
read-path efficiency tweak.

**Acceptance criteria (plan §8) status, this run:**

- Documenting `assert_available_before_decision` raise/no-raise for the
  known tape, captured verbatim -- **FAIL**, not reached (OOM before any
  script `print`).
- `N == len(exc.offending_records) == len(records)` for this tape -- **FAIL**,
  not reached.
- `real_observed`/scenario byte-identical output pre/post-refactor -- **FAIL**,
  not reached.
- `naive`/`realistic` per-strategy trading-result identity after
  `weather_data` removal -- **FAIL**, not reached.
- Survey deliverable table (this document, all rows classified with
  `ts_init` provenance) -- **PASS** (already complete, independent of this
  run).
- RED->GREEN unit tests (`test_point_in_time_guard.py`,
  `test_run_weather_strategy_backtests_selection.py`, round-4
  missing-station fixtures) -- **PASS** (already captured in prior work,
  independent of this run; not re-executed tonight).

**AUD-11 cannot close.** The four tape-proof criteria remain unmet after
two cap levels (6G, 12G); this is not a quiet-window or cap-size problem,
it is `_select_tape_instruments` reading the whole shared, growing capture
catalog instead of the ~5 instruments the 2026-08-30 NYC/MIA proof needs.
Closing requires the filter-before-read fix above (a source change, out of
this task's scope) followed by one more capped run, which should then need
well under 6G.
