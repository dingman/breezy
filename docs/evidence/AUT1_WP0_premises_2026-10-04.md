# AUT-1 WP0 premises and measurements (2026-10-04)

Plan: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md` section 4 "AUT-1.WP0".
Rulings: `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-1-build-rulings.md` (WP0-R1 to WP0-R10).
Nautilus Trader 1.231.0, shared venv `/home/jon/breezy/.venv`. Tests: branch `backlog/aut1a-2026-10-04`.

Every number below is quoted from a measurement output, a test file or the rulings file. A number that no source records is written "not recorded". Raw measurement outputs live in the session scratchpad (`aut1wp0a/`, `aut1wp0b/`, `aut1wp0c/`), which is not committed; the 14-day journal extract (93 MB) is deliberately not copied here.

## Method deviation (part c, systemd experiments)

The plan asked for scratch unit files under `~/.config/systemd/user/` removed and `daemon-reload`ed afterwards. That was not done. Reason: the repo's `breezy-*` unit files are symlinked into systemd, so a `daemon-reload` could activate unmerged unit edits. Instead every experiment ran as a transient `systemd-run --user --unit=claude-aut1wp0-*` unit with every property set by `-p`. No unit file was written and no `daemon-reload` was issued. All units were cleaned up. No `breezy-*` unit was touched. The experiments ran 2026-10-04 07:48-07:51Z (ruling WP0 part (c)).

## Premise results

| # | Test or measurement | Result | Ruling |
|---|---|---|---|
| V-1 | `test_capture_types_registered_before_kernel_writer_exists` | PASS, red under mutation | WP0-R3: a late-defined `@customdataclass` is still found, because the writer holds the live schema dict. The real failure is a never-registered class: `KeyError` at `writer.py:460` (`_create_writer`), raised before the writer's own try. Premise holds; plan text corrected. |
| V-1b | `test_customdataclass_rejects_optional_and_decimal_fields` | PASS, red | None. Also pins that stringified annotations (`from __future__ import annotations`) are rejected. |
| V-3 | `test_streamed_native_event_serialisation_never_raises`; `test_msgbus_handler_exception_unwinds_into_publisher` | PASS, red | None. |
| V-5 | `test_custom_type_without_instrument_id_writes_regular_file` | PASS, red | None. |
| V-6 | `test_order_initialized_stream_fields_recompute_intent_fingerprint` | PASS (plan "if it fails" branch applies) | WP0-R4: see the enum map below. |
| V-7 | `test_quote_tick_cached_before_on_quote_tick`; `test_depth_frame_is_not_cached_before_on_order_book_depth`; measurement (below) | PASS, red; measured over 3 FQ days, not 14 | WP0-R9: satisfied by the ordering test, no re-measure. |
| V-8 (a)-(f) | Transient unit, logs `aut1wp0c/hook-v8*.log` | PASS | Observations carried to WP3 and AUT-6 (below). |
| V-9 (a) | Transient unit under bwrap, `hook-v9a-all.log` and `hook-v9a-main.log` | PASS: the `NotifyAccess=all` datagram is accepted across bwrap; the `=main` negative control times out | None. |
| V-9 (b) | `aut1wp0c/v9b.sh` | FAIL, superseded | WP0-R1: `systemctl --user show` inside `--unshare-pid` bwrap fails with ENODATA; `journalctl --user` works. The ARCH-0 seam B handoff replaces this case (seam B plan r5:426, errata E-7e). The handoff was proven on the real host (seam B V17 and V21 PASS). The audit reads the bus snapshot; the drill and guard are unwrapped residuals (seam B r5:425). Not adopted: dropping `--unshare-pid`, or `gdbus`/`busctl` in-row. |
| V-10 | Transient unit, `hook-v10.log` | PASS | None. |
| V-11 | Catalog corroboration measurement (below) | PROVISIONAL, over 3 FQ days, not 14 | WP0-R9: R6 baseline is 93.3% - 1 pp. Leg B splits into `tape_frame_absent` (INFO) and frame-present-but-unequal (FAIL). Re-measure over 14 FQ days on or after 2026-10-15; owner WP5; blocks WP5 activation only. |
| V-12 | `test_forecast_point_topic_pinned_by_publish_probe`; `test_capture_actor_subscribed_before_first_forecast_publish`; `test_forecast_point_streams_to_regular_custom_file` | Unit legs PASS, red. Replay leg CANNOT-MEASURE: there is no persisted held vector, and FQ has been live only since 10-01 | WP0-R8: deferred to WP8 acceptance (first full capture day). WP1 keeps `test_forecast_ref_resolves_to_vector_equal_to_strategy_state` and `test_reissue_replays_as_fq_pushed_it`. A mismatch marks the day `forecast_ref_unverified`. |
| V-13 | `test_sample_feed_health_runs_on_loop_thread` | PASS, red; cadence 5.0 s | None. |
| V-14 | `test_client_order_id_embeds_utc_date`; `test_supervisor_spawn_sites_and_their_log_lines`; `test_every_evaluation_emits_one_shadow_decision_line`; `test_nautilus_disposal_line_text_is_component_colon_disposed` | PASS, red. Plan text wrong on two points | WP0-R7, owner WP5, no `trade_supervisor.py` edit: four spawn sites, not three; a Take emits two decision-class lines. Details below. |
| V-15 | closure tests (map below) | Entry points PASS. `forecast_state` closure FAILED at first (33 adapter modules), fixed by WP0-R6 | WP0-R6: strip the `ladder_ev` package facade. WP1's first commit (`refactor(strategy): ladder_ev package facade imports nothing ...`) does it and removes the xfail. `submit_chain.py` is not byte-pinned (positive control finds the exec client's pin). The AST walk remains the lint, because grimp has no edge for a package's implicit `__init__`. |
| V-16 | `test_native_event_counted_once_per_event_id` | PASS, red | None. |
| V-17 | `test_each_silent_writer_drop_is_seen_by_the_per_type_check` | PASS, red | None. |
| V-18 | Transient unit, `hook-v18.log` | PASS | None. |
| V-19 | `test_per_write_delta_flags_each_silent_drop`; `test_first_write_to_lazily_created_table_with_zero_size_is_a_drop`; `test_per_write_delta_has_no_false_positive`; `test_capture_include_types_use_plain_str_size_keys` | PASS, red | None. |
| V-20 | 14-day journal measurement (below) | PASS | `DISCOVERY_ATTEMPT_BUDGET_S` = 180 holds. |
| V-21 | 14-day journal against `config.json` (below) | PASS with WP0-R5 caveat. Scratch half STOPPED (WP0-R2) | WP0-R2, WP0-R5, WP0-R9. |
| V-22 | Unit and rotate-window reading, `deployed_units.txt`, `repo_units.txt` | PASS | None. |
| V-23 | Unit and script reading since `f45f5a65` | PASS: no mover. Only the ingest timer changed (O-1) | None. |

Test summary at the WP0 test commit: 31 tests, 30 pass plus 1 strict xfail (V-15 `forecast_state`, flipped to a plain pass by WP1's first commit). Every test goes red against its recorded mutation (`aut1wp0a/mut_all.txt`, `mut_ids.txt`, `mut_pin.txt`, `mut_src.txt`). lint-imports 11 kept, 0 broken.

## Constants

| Constant | Value | Basis |
|---|---|---|
| `STREAM_SILENCE_S` | 900 | Venue-wide silence maximum over 14 days is 461 s, with 0 runs at or above 900 s (`S5.json`). |
| `QUIET_HOURS_MULTIPLIER` | 1 | Ruling constants block. |
| `WRITER_STALL_S` | 120 | Floor binds: `max(120, 6*p99.9)` = 120.0 (`growth_result.json`). |
| `FLUSH_MARGIN_S` | 30 | 3 x 10 s flush (`growth_result.json`). |
| `DISCOVERY_ATTEMPT_BUDGET_S` | 180 | V-20, below. |

## Measurements

All from one studies-flock job (07:57-08:01Z, `MemoryMax=4G`, peak 2.8G, `aut1wp0b/full.out`), plus a separate 40-minute growth sample.

**V-20 (journal window from 2026-09-20T09:00:38Z, `v20_v21.out`).**
- Connect-time attempts: n=17, p50 0.205 s, p90 0.295 s, p99 10.002 s, max 10.002 s; pages 0-1. The review trigger is 90 s.
- All attempts: n=712, p99 0.785 s, p99.9 5.275 s, max 10.002 s.
- Outcomes: 706 loaded, 1 client connect error, 5 discovery-returned-zero. Empty-discovery retry lines: 0.
- No transport retry is visible: the `HttpClient` stub exposes no retry knob, and the Rust internals are unreadable.

**V-21 (`v20_v21.out`, `v21b.out`).**
- 16 journal `Started` entries; 72 live dirs, each with a `config.json`. Each start has a `config.json` at 0.7-2.4 s after start (the 09-29 pair shows a second dir at 41.9 s).
- 14 of 16 starts have exactly one `config.json` within 60 s; the other two are the 09-29 pair 41.2 s apart (WP0-R5: match by `instance_id`, never by a 60 s window).
- 16 `config.json` mtimes in the window, none unmatched.
- Directory-mtime overcount confirmed: 14 of 16 dirs have a dir mtime in a later trading day than the `config.json`. Day 09-26 counts 1 boot by `config.json` and 7 by dir mtime.
- Instance age at 12:30Z: minimum 3.48 h, all above 1 h. The drill window [12:30Z, 12:30Z+900 s] ends 12:45Z, 225.0 min before the 16:30Z launch window.
- Scratch half: `quote_tape_cli.py` requires `POLYMARKET_US_*` venue env and would open a venue connection, so it was never run in a scratch unit (WP0-R2). A restart writing a new `config.json` is decided from the journal match.

**V-7 (`summarize.out`; FQ depth-triggered evaluations, node logs against the catalog, 3 FQ days).**
- No same-frame quote: 26616 / 2525375 = 1.0539% (Wilson 95% [1.0414%, 1.0666%]).
- No cached quote since node boot: 10 / 2525375 = 0.0004%.
- No quote ever in the catalog: 0 / 2525375.
- Tape proxy (depth frames of the 4 FQ stations' D+1 rungs, 09-21 to 10-04): no same-ts quote 162709 / 11502391 = 1.4146%; no quote since window start 3781 / 11502391 = 0.0329%; 336 instrument-days with zero quotes in the window.
- The ruling records "a true missing quote is about 4e-6"; that figure is not in `summarize.out` and is quoted from the rulings only.

**V-11 (`summarize.out`).**
- All eval frames in ingested ranges present as depth or quote: 2514033 / 2694515 = 93.3019% (Wilson 95% [93.2720%, 93.3317%]).
- Takes inside both ingested ranges: 13 / 14 = 92.8571% (Wilson 95% [68.5307%, 98.7278%]).
- Refuse: 173 / 174 = 99.4253%. NotExecutable or NotDPlus1: 91 / 95 = 95.7895%.
- Unrestricted by range: Take 14 / 21, Refuse 183 / 207, NotExecutable or NotDPlus1 93 / 144.
- Groups total 4481881; in both ranges 2694515; out of ingested range (catalog lag) 1787366.
- Missing-group nearest depth distance (ns) [min, p10, p50, p90, max]: [23620, 4755877, 43767263, 73512192, 39259708912].
- Leg B is INFO at this level (ruling); the 14-day re-measure is WP0-R9.

**Stream volume per UTC day (`summarize.out`; threshold 20,000).** Projected rows per full UTC day: 1665 (10-01), 1769 (10-02), 1694 (10-03). Each includes a heartbeat design constant of 1441 (1,440 + 1).

| Day | decision records (on-change incl. Take/TrySubmit) | frame copy (Take path) | native order/position events | `ForecastPoint` | Total |
|---|---|---|---|---|---|
| 2026-10-01 | 83 | 6 | 23 | 112 | 1665 |
| 2026-10-02 | 161 | 6 | 21 | 140 | 1769 |
| 2026-10-03 | 101 | 9 | 31 | 112 | 1694 |

`ForecastPoint` rows per day: 112-140. In-boot reissues: 0. Cycles re-published across boots: 4. `FQ_VECTOR_COMPLETE` lines: 56.

**D8 silence (`S5.json`, window 2026-09-20 to 2026-10-04, 14 full UTC days, 39870556 frames, 1025 instruments).**
- Venue-wide runs: n=40899, p99 15.0 s, p99.9 133.1 s, max 461 s, 0 runs at or above 900 s, 1800 s or 3600 s.
- Active hours: max 447 s. Quiet hours (UTC 11, 22, 23): max 461 s.
- Per-instrument gaps of 900 s or more occur 2,051 times (ruling and `S5.json`), so the gate stays venue-wide.

**Writer-stall growth (`growth_result.json`, 07:53:33-08:33:32Z, 40 minutes, weak tail).**
- 2272 growth events; growth interval p50 1.000000 s, p99 3.0 s, p99.9 5.0 s, max 7.0 s.
- 0 intervals over 30 s with events; 0 intervals over 60 s.
- Frame to next visible growth: n=246111, p50 0.5035 s, p99 0.9914 s, p99.9 0.9996 s, max 3.548 s.
- Mean 105.35 frames/s.

**Drill slot 12:00-13:30Z (`S6.json`).** Orders submitted by UTC hour across all retained logs appear only in hours 1, 2, 16, 17, 18, 19, 20, 21; hours 12 and 13 have none. 0 Takes and 0 orders in the slot.

## V-6 enum map (WP0-R4)

The streamed `OrderInitialized` row carries enum NAMES (`BUY`, `IOC`). `intent_fingerprint` hashes `str(enum)`, which on 1.231.0 is `'1'` for BUY and `'2'` for IOC. The price is only in the `options` JSON and the `price` column is null. The WP1 reader maps `order_side` through `nautilus_trader.model.enums.order_side_from_str` and `time_in_force` through `time_in_force_from_str`, then applies `str()`, and reads the price from `json.loads(row["options"])["price"]`. Proven on the YES and NO legs.

## V-14 details (WP0-R7, owner WP5)

- Spawn events, exactly four: `launched pid=` at `trade_supervisor.py:1300`; `boot_retry_launched pid=` at `:1633`; `relaunching attempt=` at `:1377`, logged before the spawn; `midday_relaunching phase=midday_watch attempt=` at `:1972`, logged before the spawn. `launch_spawn_failed` at `:1296` is a no-spawn event. The `ports.spawn(` calls sit at `:1289`, `:1379`, `:1631`, `:1982` in the tree at the WP0 commit.
- The two non-pid events log no pid. Matching is 1:1 in time order to the next unmatched `breezy-trade-<stamp>.log`; the pid is never the join key; an event with no log is `ERROR node_log_missing`.
- Decision lines: each evaluation emits exactly one decision-class line. A Take adds one `kind="TrySubmit"` line, only when `shadow_only=False`. R1 pairs each TrySubmit with the preceding Take on `(instrument_id, rung_id, side)`; R2 drops TrySubmit before the OnChange/EvalSeq replay; R3 computes evaluations as total minus TrySubmit; the WP5 parser classifies by `kind`.

## Observations carried forward

- WP3/AUT-6: the default `WatchdogSignal` is SIGABRT and dumps core, so WP3 sets `WatchdogSignal=` explicitly (plan section 3.10.2).
- WP3: a unit that keeps sending `EXTEND_TIMEOUT_USEC` while ignoring SIGTERM sat in `stop-sigterm` for more than 3 minutes; the pinger must stop extending once stop begins, and this needs a test.
- AUT-6: `OnFailure=` fired on every failure, but a real notifier target was not exercised (`breezy-autonomy-failed@`, X-4).
- V-8 hook outputs (`SERVICE_RESULT=` lines, all with a non-empty `INVOCATION_ID`): watchdog, success, timeout, watchdog, watchdog, watchdog, success, watchdog, watchdog, success, timeout across the hook logs.

## Nautilus 1.231.0 line pins

Read directly from `/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader` on 2026-10-04. The citations in this table were read at these lines on that date.

| Pin | Content at that line |
|---|---|
| `persistence/writer.py:129` | `self._schemas = list_schemas()` |
| `persistence/writer.py:136-146` | `_instrument_writers` keyed by `(table, instrument)`; `_per_instrument_writers` set (`bar`, `order_book_deltas`, ...) |
| `persistence/writer.py:230-245` | per-instrument keying; instrument absent from cache returns silently; `custom_` tables get a regular writer |
| `persistence/writer.py:250-255` | unregistered class: warning plus `missing_writers`, return |
| `persistence/writer.py:261` | `if not serialized:` (empty serialisation drop) |
| `persistence/writer.py:285-288` | `except Exception` logs `Failed to serialize` (raising `write_table` is swallowed) |
| `persistence/writer.py:460` | `schema = self._schemas[cls]` |
| `persistence/writer.py:463-473` | stream and file created before serialisation; `_file_sizes[table] = 0` |
| `serialization/arrow/serializer.py:85-86` | `list_schemas()` returns the live `_SCHEMAS` |
| `model/custom.py:259-265` | `Unsupported custom data field type` `TypeError` |
| `common/component.pyx:2202` | `self._log.info(f"{self._fsm.state_string_c()}")` |
| `common/component.pyx:2832-2834` | handler loop `sub.handler(msg)`, no try (handler exceptions unwind) |
| `data/engine.pyx:2691-2696` | `_handle_order_book_depth` publishes with no quote cache |
| `data/engine.pyx:2716` | `self._cache.add_quote_tick(tick)` |
| `data/engine.pyx:2728` | `self._msgbus.publish_c(` (after the cache add at `:2716`) |
| `trading/trader.py:251-271` | `_start` begins at `:251`; `exec_algorithm.start()` at `:271` (the test asserts actors start before strategies) |

## Test-name to file map (after the WP0-R10 split)

Helpers and the closure walk: `tests/unit/aut1_premises_support.py` (non-test, importable).

| File | Tests |
|---|---|
| `tests/unit/test_aut1_wp0_writer_premises.py` | `test_capture_types_registered_before_kernel_writer_exists`; `test_customdataclass_rejects_optional_and_decimal_fields`; `test_streamed_native_event_serialisation_never_raises`; `test_msgbus_handler_exception_unwinds_into_publisher`; `test_custom_type_without_instrument_id_writes_regular_file`; `test_native_event_counted_once_per_event_id`; `test_each_silent_writer_drop_is_seen_by_the_per_type_check`; `test_per_write_delta_flags_each_silent_drop`; `test_first_write_to_lazily_created_table_with_zero_size_is_a_drop`; `test_per_write_delta_has_no_false_positive`; `test_capture_include_types_use_plain_str_size_keys` |
| `tests/unit/test_aut1_wp0_order_cache_premises.py` | `test_order_initialized_stream_fields_recompute_intent_fingerprint`; `test_quote_tick_cached_before_on_quote_tick`; `test_depth_frame_is_not_cached_before_on_order_book_depth`; `test_client_order_id_embeds_utc_date` |
| `tests/unit/test_aut1_wp0_forecast_feed_premises.py` | `test_forecast_point_topic_pinned_by_publish_probe`; `test_capture_actor_subscribed_before_first_forecast_publish`; `test_forecast_point_streams_to_regular_custom_file`; `test_sample_feed_health_runs_on_loop_thread` |
| `tests/unit/test_aut1_wp0_log_line_premises.py` | `test_supervisor_spawn_sites_and_their_log_lines`; `test_every_evaluation_emits_one_shadow_decision_line`; `test_nautilus_disposal_line_text_is_component_colon_disposed` |
| `tests/unit/test_aut1_wp0_closure_premises.py` | `test_static_walk_positive_and_negative_controls`; `test_aut1_entry_point_closures_are_free_of_venue_adapter_modules` (5 parametrised entries); `test_forecast_state_closure_is_adapter_free`; `test_forecast_state_closure_reaches_adapters_through_ladder_ev_init`; `test_submit_chain_is_not_byte_pinned_in_tests` |

The split collects the same 31 ids as the original `test_aut1_l1_nautilus_premises.py` (modulo module path), and the result is unchanged.

Tests the rulings assign to later WPs, not yet written: `test_boot_count_matches_by_instance_id_not_time_window` (WP5, WP0-R9); the four-site extension of the spawn-line test plus an AST pin of exactly four `ports.spawn(` calls (WP5, WP0-R7). The plan's WP0 file name `test_aut1_l1_nautilus_premises.py` is superseded by the five files above.
