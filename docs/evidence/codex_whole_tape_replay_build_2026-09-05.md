# Whole-Tape Paper Replay Build - 2026-09-05

Outcome: implementation is in the working tree, but the TDD pytest gate could
not execute in this sandbox. I did not fake the OS egress attestation.

Files changed / line counts:
- `scripts/analysis/current_rung_hold_paper_replay.py` - 742 lines; widened the live scored-trials path guard.
- `scripts/analysis/whole_tape_paper_replay.py` - 619 lines; new whole-tape paper replay wrapper.
- `tests/unit/test_whole_tape_paper_replay.py` - 311 lines; new RED tests for the amended findings.
- `derived/paper_replay/WHOLE_TAPE_PAPER_REPLAY_REPORT.md` - 18 lines.
- `derived/paper_replay/station_day_counts.csv` - 4 lines.
- `derived/paper_replay/LOOKAHEAD_CAVEAT.txt` - 1 line.

RED/GREEN evidence by build step:
1. RED `test_paper_replay_refuses_both_live_scored_trials_roots`: no target failure line available. Command
   `scripts/ci/run_tests_no_egress.sh -q -p no:cacheprovider tests/unit/test_whole_tape_paper_replay.py::test_paper_replay_refuses_both_live_scored_trials_roots`
   exited 3: `error: no usable unprivileged network-namespace mechanism on this host.`
   Fallback `.venv/bin/python -m pytest -q -p no:cacheprovider ...` exited 2 at N2:
   `execution-egress module(s) exist but the OS egress firewall is not attested`.
   Direct GREEN check: `derived/scored_trials RAISED`; `derived/live/scored_trials RAISED`; `derived/paper_replay/scored_trials OK`.
2. RED `test_classification_lists_corrupt_empty_live_and_preflight_errors` and `test_corrupt_only_station_days_are_blocked_not_denominator`: pytest blocked as above. Direct checks were not separately executable through pytest.
3. RED `test_station_coverage_filters_quote_ticks_to_that_station`, `test_unique_winner_uses_first_in_window_quote_not_longest_span`, `test_dual_cover_of_the_first_instant_is_blocked`: pytest blocked as above. Direct GREEN check: `station_coverage True`; `winner 20-minute {}`; `dual_cover True DUAL_COVER_FIRST_INSTANT`.
4. RED `test_replay_calls_nws_integer_precision_arm_only_with_unique_work_catalogs`, `test_existing_scored_trials_parquet_skips_that_lag_only`: pytest blocked as above. Direct GREEN check: `calls [(30, 'nws_integer_c'), (45, 'nws_integer_c')]`; `unique_work True`; `argv_precision False`.
5. RED `test_report_header_caveat_and_no_wilson_or_roi`: pytest blocked as above. Direct GREEN check: header `MECHANISM TEST -- NO VERDICT`; `no_wilson True`; `no_roi True`.
6. Full unit gate command:
   `scripts/ci/run_tests_no_egress.sh -q -p no:cacheprovider tests/unit`
   Exit code 3. Progress line: none; pytest never started. F/E markers: none from pytest. Fallback full command exited 2 at N2 before collection.

Other checks:
- `.venv/bin/python -m py_compile scripts/analysis/whole_tape_paper_replay.py tests/unit/test_whole_tape_paper_replay.py scripts/analysis/current_rung_hold_paper_replay.py` exited 0.
- `.venv/bin/python -m ruff check scripts/analysis/whole_tape_paper_replay.py tests/unit/test_whole_tape_paper_replay.py scripts/analysis/current_rung_hold_paper_replay.py` printed `All checks passed!`.

Dry run:
Command:
`.venv/bin/python scripts/analysis/whole_tape_paper_replay.py --quote-catalog /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us --output-root derived/paper_replay --work-root derived/paper_replay/work --dry-run --max-clean-instances 1`

Header:
`MECHANISM TEST -- NO VERDICT`

Look-ahead caveat:
`Settlement joins the highest-\`revision_seq\` FINAL NWS CLI record (\`climate_day_records_to_settlement:582\`). Those corrections are unpublished at decision time. This run is a plumbing / take-rate / L2 fill-realism mechanism test -- not a backtest of edge. MECHANISM TEST -- NO VERDICT.`

Counts:
- station-days replayed: 0
- BLOCKED:EMPTY_WINDOW: 10
- eligible_clean_unique_winner: 0
- classifications: CLEAN 12, CORRUPT 2, EMPTY 1, LIVE 1

Invariants not honored:
- Sequential Thinking MCP was required by the supplied guide but is not exposed in this session.
- RED/GREEN pytest evidence and the full unit gate could not run because the required no-egress namespace cannot start and the fallback is stopped by N2.

Left undone:
- Real pytest RED/GREEN and full unit progress-bar evidence.
- Non-dry replay of a replayable station-day; the one CLEAN-instance dry run found only empty-window blocked station-days.

Git status --porcelain:
```text
 M deploy/systemd/family-tally-v2-run.sh
 M scripts/analysis/current_rung_hold_paper_replay.py
 M scripts/analysis/family_tally_v2.py
 M scripts/analysis/structural_dead_stop.py
 M src/breezy/settlement/current_rung_hold_v2.py
 M tests/unit/test_family_tally_v2.py
 M tests/unit/test_family_tally_v2_deploy.py
 M tests/unit/test_structural_dead_stop.py
?? derived/
?? docs/evidence/codex_structural_dead_diff_review_2026-09-05.md
?? docs/evidence/codex_whole_tape_replay_build_2026-09-05.md
?? docs/evidence/grok_structural_dead_plan_review_2026-09-05.md
?? docs/evidence/grok_whole_tape_replay_plan_review_2026-09-05.md
?? docs/plans/STRUCTURAL_DEAD_RULE_2026-09-05.md
?? docs/plans/WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md
?? scripts/analysis/whole_tape_paper_replay.py
?? tests/unit/test_whole_tape_paper_replay.py
```

## Fix pass (Claude)

Sandbox no-egress DOES work on this host (`scripts/ci/run_tests_no_egress.sh` ran cleanly
throughout this pass) -- the prior "no usable unprivileged network-namespace" failure was
environmental to that earlier session, not a standing blocker. All RED/GREEN evidence below
is real pytest output, not a "direct check" substitute.

Addressed `docs/evidence/codex_whole_tape_replay_diff_review_2026-09-05.md` findings 1-5
(verdict REJECT), touching only `scripts/analysis/whole_tape_paper_replay.py` and
`tests/unit/test_whole_tape_paper_replay.py` (`current_rung_hold_paper_replay.py` was not
touched -- no containment-guard change was needed there). Root cause of the originally
reported "zero replayable station-days" was confirmed as NOT a coverage bug: the prior dry
run used `--max-clean-instances 1`, slicing to instance `16109d4d` (overnight-only
station-days). The real tape has 22 eligible CLEAN unique-winner station-days before
per-station filtering.

### Findings 1-6 -- RED then GREEN (real pytest, no direct-check substitutes)

1. **Containment.** RED `test_output_root_containment_refuses_paths_outside_derived_root`:
   `AttributeError: module 'whole_tape_paper_replay' has no attribute
   'PaperReplayOutputNotContainedError'`. GREEN: added `assert_output_root_is_contained`,
   `default_derived_root` (`BREEZY_DERIVED_ROOT` env override, default
   `~/.local/share/breezy/derived`), called at the top of `run()` before any write.
2. **Idempotence.** RED `test_a_genuinely_completed_replay_skips_the_same_lag_on_rerun`:
   `assert 'RAN' == 'SKIPPED_EXISTING'` (the old sentinel globbed `scored_trials_*.parquet`,
   a file this wrapper never writes). GREEN: added an atomic `REPLAY_COMPLETE` marker
   (write-to-temp + `Path.replace`) written LAST, after `mechanism_trials.csv/parquet`;
   `test_crash_before_the_completion_marker_reruns_rather_than_skipping` covers the
   crash-before-marker case.
3. **CORRUPT-only station-days.** RED `test_run_populates_corrupt_only_station_days_via_identity_only_read`:
   `AttributeError: ... has no attribute '_load_stream'`. GREEN: `_corrupt_instance_station_days`
   does an identity-only read of CORRUPT instances' `binary_option` registrations
   (`cli_basis_offer_gate_scan._load_stream`, mirroring `build_scan`'s own derivation),
   parsed via `read_weather_bucket_facts`; wired into `run()`.
4. **Malformed instrument facts.** RED `test_load_clean_instance_lists_malformed_instruments_instead_of_dropping_them`:
   `AttributeError: 'CleanInstance' object has no attribute 'malformed_instrument_ids'`.
   GREEN: `_load_clean_instance` parses via `read_weather_bucket_facts`, catching
   `WeatherFactsUnavailableError` and listing the instrument id under a new
   `malformed_instrument_ids` field; `run()` surfaces the count as
   `BLOCKED:MALFORMED_INSTRUMENT`.
5. **Look-ahead caveat on `station_day_counts.csv`.** RED
   `test_station_day_counts_csv_carries_the_lookahead_caveat`: `KeyError: 'lookahead_caveat'`.
   GREEN: added a `lookahead_caveat` column, one caveat value per row.
6. **Cap labelling.** RED `test_cap_label_partial_run_lists_the_selected_clean_instance_ids` /
   `test_cap_label_whole_tape_when_uncapped`: `TypeError: render_report() got an unexpected
   keyword argument 'clean_instance_ids_loaded'`. GREEN: `render_report` now prints
   `PARTIAL RUN -- N of M CLEAN instances` (+ selected ids) or `WHOLE TAPE -- M of M CLEAN
   instances`; `run()` records `clean_instances_loaded`/`clean_instances_total` in
   `station_day_counts.csv`.

Targeted command:
`scripts/ci/run_tests_no_egress.sh -q -p no:cacheprovider tests/unit/test_whole_tape_paper_replay.py tests/unit/test_current_rung_hold_paper_replay.py`
-- progress line `..........................................................  [100%]`, exit 0
(58 tests). `ruff check` on the three touched files: `All checks passed!`. `mypy` surfaces 17
pre-existing errors unrelated to this pass (module-export `attr-defined` on the
`current_rung_hold_paper_replay` re-import, a pre-existing `classifier` default-type mismatch,
and `current_rung_hold_paper_replay.py:365-378` `union-attr` findings) -- all present, byte-for-byte,
in the code as this pass found it; zero new mypy errors introduced.

### Additional findings, discovered only by actually running the real tape (not in the original 1-6 list)

Running the real (non-dry) whole-tape replay surfaced three further defects, all inside
`whole_tape_paper_replay.py`'s own wrapper logic (not the harness), each fixed RED-first in
the same pass because they made the requested real run impossible without them:

7. **Cross-station/day contamination.** `select_unique_clean_winners` handed a `Winner`
   the CLEAN instance's ENTIRE merged `tape_instruments` (every station, every day it
   captured), not just that `(station, climate_day)`'s own instruments. On the real catalog
   this let a fill on a `...-2026-09-01-...` instrument crash the `SFO/2026-08-31` replay
   with `EntryAskFromLatchMissingError` (`current_rung_hold_paper_replay.py:368`). RED
   `test_winner_tape_instruments_exclude_other_stations_and_days_on_the_same_clean_instance`:
   `AssertionError: assert {'inst', 'sfo-day1', 'sfo-day2'} == {'sfo-day1'}`. GREEN: added
   `_own_tape_instruments`, filtering to the winner's own `(station, climate_day)` before
   constructing `Winner`.
8. **Unsupported station (NYC).** `CurrentRungHoldConfig` refuses NYC at construction
   (hourly-only ASOS feed, A14) -- `whole_tape_paper_replay.py` never filtered it out first,
   so a real NYC winner crashed the whole run with `UnsupportedStationError`. RED
   `test_run_blocks_unsupported_stations_instead_of_crashing`: NYC's mocked
   `run_one_precision_arm` call was reached (`calls == ['LAX','LAX','NYC','NYC']`). GREEN:
   `run()` now filters `winners` against the native `SUPPORTED_STATIONS` constant
   (`breezy.strategy.current_rung_hold.config`), recording `BLOCKED:UNSUPPORTED_STATION`.
9. **No FINAL settlement yet.** A station-day whose climate day has not closed (today,
   2026-09-05) has no FINAL NWS CLI record, so `_synthesize_close` cannot build a
   `CONTRACT_EXPIRED` close and the native `assert_settlement_invariants` correctly refuses
   the whole backtest (`SettlementInvariantError`). RED
   `test_run_blocks_a_winner_with_no_final_settlement_record`: mocked `run_one_precision_arm`
   was still called for the unsettled winner. GREEN: `run()` checks `settlement_by_key`
   membership per winner before calling `replay_candidate_lags`, recording
   `BLOCKED:NO_FINAL_SETTLEMENT` instead of attempting (and crashing on) the replay.

Also discovered (not a code defect, an invocation default): the CLI's
`--weather-catalog-root` default (`~/.local/share/breezy/catalog/polymarket_us`) double-nests
`station_catalog_path`'s own `base/venue/city` join (venue = `"polymarket_us"`), resolving to
a directory that holds zero `NwsClimateDay` records. The real run below passes the correct
base (`~/.local/share/breezy/catalog`) explicitly; the CLI default itself was left unchanged
(out of this pass's touch-list, and not one of findings 1-6).

An ASOS observation cache (`--asos-cache-csv`) is a hard input to `run_one_precision_arm`
(used for every precision arm, not just `archive_metar`) and none existed on disk. Assembled
one, zero network, entirely from the local `~/.local/share/breezy/archive/settlement-alignment-cache/`
`.txt` cache (2,338,957 deduplicated rows across LAX/MDW/MIA/NYC/SFO) via the codebase's own
`cli_basis_offer_gate_scan.load_recent_asos_rows`, written to a scratch path outside the repo
and outside the containment root (it is an input, not a paper-replay output).

### Real whole-tape run (no cap, both lag arms)

Command:
```
.venv/bin/python scripts/analysis/whole_tape_paper_replay.py \
  --quote-catalog /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us \
  --derived-root /home/jon/.local/share/breezy/derived \
  --asos-cache-csv <local, zero-network ASOS cache> \
  --weather-catalog-root /home/jon/.local/share/breezy/catalog
```
Exit 0. Header: `MECHANISM TEST -- NO VERDICT` / `WHOLE TAPE -- 12 of 12 CLEAN instances`.
`take-rate: 12/14`. `station_day_counts.csv`: `BLOCKED:EMPTY_WINDOW,5`;
`BLOCKED:NO_FINAL_SETTLEMENT,4`; `BLOCKED:UNSUPPORTED_STATION,4`; `eligible_clean_unique_winner,14`;
`replayed,14`. 28 `REPLAY_COMPLETE` markers (14 station-days x 2 lags), all under
`/home/jon/.local/share/breezy/derived/paper_replay/scored_trials/`; `derived/scored_trials`
(the live store) untouched. Per-arm take (lag=30 vs lag=45 identical per station-day, as
expected for this precision arm): SFO 2026-09-01 (1/1), LAX 2026-09-04 (1/1), SFO 2026-09-04
(1/1), LAX 2026-09-03 (1/1), MIA 2026-09-03 (1/1), SFO 2026-09-03 (1/1); the remaining 8
station-days took 0.
