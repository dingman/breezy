# AUD-08b evidence: sighting sidecar, station-candidate register, alerts (2026-09-24)

Plan: `docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md` (§6b, §7, §8).
Branch `backlog/aud-08b-station-candidate-register-2026-09-24`, base `c527439`; commits `560d716`
(implementation) and `ece1b58` (review follow-ups).

**ADVISORY ONLY.** No path in this item makes a city tradeable. `src/breezy/registry/sites.toml`
and `SUPPORTED_STATIONS` are untouched; the register is read by the AUD-09a census and by humans.
On today's Polymarket.us surface we expect exactly one row, the NYC `REGISTRY_SEED`, and zero
sightings: the venue has never listed a sixth city.

## Acceptance criteria

| # | Status | Evidence |
|---|---|---|
| A1–A5, A13 | 08a (merged `aa737f1`) | unchanged; 08a tests still pass in the gate run below |
| A6 | PASS | `test_a_seed_and_a_later_sighting_of_the_same_token_collapse_into_one_seed_record`: one row, `origin="REGISTRY_SEED"`, `distinct_*` stay 0, seed sufficiency kept; `test_origin_never_changes_once_set`, `test_first_seen_day_never_moves_and_last_seen_day_is_monotone`, `test_records_are_ordered_deterministically_by_key` |
| A7 | PASS | `test_a_rerun_on_the_same_day_is_byte_identical`; dry run below: two same-day runs produce an identical register sha256 |
| A8 | PASS | `test_an_unknown_register_schema_version_raises_with_path_line_and_version` |
| A9 | PASS | `test_the_nyc_seed_sufficiency_equals_the_mapping_of_the_counter` (0 / floor−1 / floor; the floor is imported, never the literal 15); fourth arm `test_an_unreadable_catalog_refuses_and_never_reads_as_zero[root_absent\|depth_absent\|gap_refusal]` plus `test_the_first_fold_refuses_on_an_absent_catalog_and_writes_nothing` |
| A10 | PASS | `test_an_attached_sink_receives_every_stamped_sighting_once_per_cycle_after_the_warn` asserts a single venue request per cycle |
| A11 | PASS | `lint-imports`: `Contracts: 5 kept, 0 broken.` |
| A12 | PASS | `tests/unit/test_station_candidate_sightings.py`, including the UTC-midnight rotation arm; read-side dedupe covered by `test_repeated_identical_sightings_are_deduplicated_on_read` |
| A13 | PASS (changed files) | `mypy` on every changed src/script/test file is clean. `mypy src/breezy` reports 6 errors, all in `src/breezy/app/trade.py`, which this item does not touch and which is outside `[tool.mypy] files` |
| A14 | PASS | `test_the_trade_node_composition_attaches_no_sighting_sink`, `test_the_recorder_composition_attaches_one_file_backed_sink`, `test_both_factories_construct_exactly_one_instrument_provider` (identity, `misses == 1`), `test_the_shared_provider_getter_signature_is_unchanged` |
| A15 | PASS | `test_a_record_older_than_180_days_compacts_idempotently_and_is_never_deleted` |
| A16 | PASS | `test_a_new_sighting_candidate_alerts_exactly_once_across_two_folds`, `test_a_registry_seed_never_alerts`. Residual (per plan's design): a second run on the *same* UTC day alerts again, because the dedupe key is `first_seen_day == today` |
| A17 | PASS | `test_a_recovered_emitter_folds_every_missed_day_and_advances_the_watermark` (after three missed nights it also raises exactly one STALE alert); `test_an_absent_watermark_folds_every_unpruned_file_and_old_files_are_pruned_and_counted` |

Review follow-ups, each tested:

- **Decoupling.** The rotate unit is byte-identical to its pre-08b content apart from one added
  `OnSuccess=breezy-station-candidate-register.service` line. The register runs as its own oneshot
  unit in `breezy-studies.slice`, with its own memory caps, `alerts.env` and `OnFailure=`.
  Tests: `tests/unit/test_station_candidate_register_unit.py`.
- **Broken-sidecar alert.** The alert fires once after 3 consecutive failed cycles and re-arms
  after a success. A failing alert callable never aborts discovery. The callable is referenced by
  path and resolved with Nautilus `resolve_path`. Tests:
  - `test_a_persistently_failing_sink_alerts_once_after_n_consecutive_cycles`
  - `test_a_successful_append_resets_the_failure_streak_and_rearms_the_alert`
  - `test_a_raising_failure_alert_never_aborts_discovery`
  - `test_the_recorder_role_injects_the_sidecar_failure_alert`
  - `test_the_recorder_composition_wires_the_config_supplied_failure_alert`
  - `test_an_unresolvable_or_non_callable_failure_alert_path_refuses_at_build`
- **Stale-fold alert.** Tests:
  - `test_a_run_alerts_once_when_the_watermark_is_more_than_two_days_old`
  - `test_the_lock_skip_path_checks_staleness_without_touching_the_catalog`
  - `test_the_check_staleness_flag_skips_the_fold`
  - `test_a_quiet_venue_still_advances_the_watermark_to_yesterday`
  - `test_an_absent_watermark_is_not_reported_stale`
  - `test_the_wrapper_checks_staleness_when_it_skips_on_the_lock`

## Memory sizing measurements (L-49), 2026-09-24

The measurements ran read-only against `~/.local/share/breezy/catalog/quote_tape/polymarket_us`,
each under `systemd-run --user --scope -p MemoryMax=6G`, calling
`count_covered_listed_station_days_from_catalog`:

| cities | window | loaded days | count | secs | peak RSS |
|---|---|---|---|---|---|
| NYC | 2026-08-30..09-05 (7 d) | 0 | 0 | 2.0 | 757 MB |
| NYC | 2026-08-30..09-11 (13 d) | 0 | 0 | 2.7 | 842 MB |
| NYC | 2026-08-30..09-24 (26 d) | 7 | 3 | 11.5–14.2 | 1.85–1.95 GB |
| 5 cities | 2026-08-30..09-24 (26 d) | 31 | 16 | 72–81 | 3.16–3.45 GB |

Current RSS was sampled after each day's load in the 5-city run (MB):
673, 674, 687, 693, 703, 836, 966, 954, 961, 1004, 1467, 1682, 1892, 1902, 2318, 2589, 2405,
2691, 2719, 2415, 2422, 2386, 2400, 2731, 2842, 3450, 3377, 2858, 2676, 2661, 2597.

- The loader streams one day at a time: RSS rises with the heavier recent days, then levels off
  and falls back.
- The peak therefore follows the largest single day plus allocator retention, not the window
  length.
- The chosen caps are `MemoryHigh=4G` / `MemoryMax=6G`. That is at least 3× the measured
  single-city peak, and above the measured 31-loaded-day peak (about 4× NYC's current 7).
- NYC count today is 3, so the seed reads `CAPTURED_INSUFFICIENT`.

## Dry run (§7 step 16): recorded payload fixture, no live call

- **Input.** The recorded fixture `docs/evidence/venue/polymarket_us/raw/market_open_510636_by_slug.json`,
  re-keyed onto `nyc` (registered) and `bos` (unregistered), was parsed with
  `_weather_market_payloads(..., collect_unregistered=True)`. Accepted markets:
  `['tc-temp-nychigh-2026-09-24-lt79f']`. The one sighting was appended through `FileSightingSink`
  into a scratch state dir.
- **Emitter run.** `scripts/analysis/station_candidate_register.py --state-dir <scratch> --today 2026-09-25`,
  against the real catalog, with the webhook unset (so the alert went to the log only).

Sidecar `sightings-2026-09-24.jsonl` (sha256 `2d4a7640d20b32d002043f46680cbdc26d3628d9fadd4b4cbc176c81c23d0669`):

```
{"city_token": "bos", "climate_date": "2026-09-24", "observed_ts_ns": 1790208000000000000, "schema_version": 1, "slug": "tc-temp-boshigh-2026-09-24-lt79f", "venue": "polymarket_us"}
```

Emitter output:

```
breezy alert event=BREEZY_STATION_CANDIDATE_NEW site=polymarket_us/bos severity=WARN detail=new venue city bos recorded; to make it eligible a strategy-lead ruling under docs/evidence/ plus the sites.toml re-verification gate must be opened - see AUD-08 §6c
station-candidate-register: sightings_read=1 partial_lines_skipped=0 days_folded=1 sidecar_days_lost=0 records_written=2 records_compacted=0 sidecars_pruned=0 alerts=1
```

Register `station_candidates.jsonl` (sha256 `65d08ac635da99c7a952ed60f287be16e3627ed3502505365d454686fb34763b`,
identical after a second same-day run):

```
{"city_token": "bos", "distinct_climate_days": 1, "distinct_slugs": 1, "first_seen_day": "2026-09-25", "last_seen_day": "2026-09-24", "origin": "SIGHTING", "schema_version": 1, "sufficiency": "NO_SETTLEMENT_TRUTH", "venue": "polymarket_us"}
{"city_token": "nyc", "distinct_climate_days": 0, "distinct_slugs": 0, "first_seen_day": "2026-09-25", "last_seen_day": "2026-09-25", "origin": "REGISTRY_SEED", "schema_version": 1, "sufficiency": "CAPTURED_INSUFFICIENT", "venue": "polymarket_us"}
```

Watermark: `{"last_folded_day": "2026-09-24", "schema_version": 1}`.

## RED → GREEN summary

- **Round 1** (`560d716`).
  - RED:
    - New modules failed at collection (`ModuleNotFoundError breezy.persistence.station_candidates`,
      `ImportError SightingSinkAlreadyAttachedError`).
    - 3 provider-sink tests failed with `AttributeError`.
    - 10 unit/pin tests failed.
  - GREEN: `1001 passed, 1 skipped`.
- **Round 2** (`ece1b58`).
  - RED: `15 failed, 158 passed`, plus the discovery module failing at collection on
    `SIGHTING_SINK_FAILURE_ALERT_CYCLES`.
  - GREEN: `1799 passed, 1 skipped` across 62 importing modules and all gate files.
- **Mutation checks.**
  - Disabling the `subscribe_trades` attach fails 2 A14 tests.
  - Removing the provider's `_append_sightings()` call fails 2 sink tests.

## Known deviations from the plan text (reviewed)

- **Fold input.** Each run reads every retained sidecar day, not only the days after the watermark,
  and merges counts with `max`. This makes `distinct_*` exact over the 35-day window and a lower
  bound beyond it, so a listing seen on several days is never double-counted.
- **Today's file is never folded.** The recorder is still appending to it.
- **Watermark.** It is set to yesterday after every successful run.
- **Two day domains.** `first_seen_day` is the fold day, while `last_seen_day` is the observation
  day. A new record therefore normally has `first_seen_day` one day after `last_seen_day`.
  AUD-09a readers must not compare the two.
- **Alert severity** is `"WARN"`, the repo's convention.
