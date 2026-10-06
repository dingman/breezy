# F13 FQ-SRC-INGEST, plan r3

[DESIGN] US source ingest: C1 collector, timing study, offline blend skill, C2/D gate statement

Status: PLAN r3. Nothing is built. It is r2 with F13-R10..R21 applied exactly, for convergence round 3 (same three reviewers: `security-reviewer`, `prediction-market-reviewer`, architecture). All content is build-time design. Items marked **(r3)** are new or changed. Items marked **Correction** were re-verified with codegraph this round.

## Brief constraints (every implementer and reviewer brief restates these)

- Nautilus Trader is immutable. `allow_short` stays `False`.
- Never weaken or delete a safety, settlement, contract or firewall test. The only firewall-file touch is the WIDENED row in R10.
- No operator-reserved control is named or assigned.
- Never touch live enablement, the permit or the NO-SEND firewall.
- Holdout days ≥ 2026-07-01 are sealed, except the post-freeze forward ledger (R12).
- Venue prices are execution cost only. They are never a signal.
- Exact interpreter path. `PYTHONPATH` set in worktrees. `lint-imports` run from the tree, with the "N kept, 0 broken" line.
- Read the gate EXIT code before any push. No `uv sync`. Format only your own files.
- Read-only agents run read-only. Never `git stash` in a shared tree.
- **Why C1 lives off the node (r3, R20):** C1 is an offline data collector. It is not a Nautilus component and is not in the node process. It extends nothing in Nautilus, so the immutability and null-hypothesis rules hold. C2 (a node-resident `DataActor`) is the only Nautilus-native part, and it is gated below.

## 0. Verdict

- **Expected edge from a static public-US blend: about zero against the market, and likely below it once ECMWF is gone.**
  - The survey's roughly 2.25 against 2.44 RMSE is unverified and used ECMWF.
  - The ask-side hurdle is θ·p(1−p) at the fill, the 0.01 slippage floor and `margin(h)` ≥ 0.02.
  - Phase A's value is "does the blend beat NBP on CLI" and the veto descriptives. It is a loss-reduction tool, not an edge.
- **The timing hypothesis is the only path with a plausible positive edge, and it is cheap to falsify.**
  - B1 is offline and CLI-free, and runs on existing tape. It reads source forecast values but no champion output and no outcome (r3, R12).
  - B2 is only a futility screen. About 1,500 trades would be needed to confirm a 3¢ edge.
- **F13-C1 is the one time-critical item.** Forward availability times and the hourly LAMP archive cannot be backfilled. C1 has its own queue row and does not wait for Phase A or row 7.
- **KILL is 2027-01-25, 111 days from 2026-10-06.**
  - Settleable by KILL: the Phase A ACCEPT or STOP, B1 GO / NO-GO / UNDERPOWERED, the veto descriptives, the B2 FUTILE / INCONCLUSIVE / NOT-FUTILE result, and 3+ months of C1 data.
  - Not settleable by KILL: confirming a 3–8¢ edge, and any CHAMPION `density_table_multisource`.

## 1. Facts (verified with codegraph; corrections marked)

| Item | Where (verified) | Use |
|---|---|---|
| IEM host policy | `scripts/venue/iem_mos_probe_transport.py`. **Correction (r3, R20):** station tuple and set at `:58-59` (`IEM_MOS_STATION_ORDER`, `IEM_MOS_STATIONS`), model order at `:60-61`, `IEM_MOS_PATH` at `:62`. `IEM_ALLOWED_HOSTS` is `{mesonet.agron.iastate.edu}` (`:53`). `IEM_MIN_INTERVAL_NS` = 1 s (`:54`). Body cap 32 MiB (`:56`). Stations KLAX/KMDW/KMIA/KSFO. Models NBS/GFS. | **KNYC widening (r3):** KNYC is added to the station closed set, widening only, never relaxing a refusal. The LAV and AFOS paths are new closed-set constants beside `:62`. LAV never goes through `iem_mos_request`. |
| **`PacedIemTransport`** | `scripts/venue/iem_mos_probe_transport.py:171-261`, extends `HttpTransport`. The constructor refuses any host set other than `IEM_ALLOWED_HOSTS` and any other base URL (`:198-203`). It refuses settlement hosts (`:189-197`). The NWS methods raise `NotImplementedError` (`:222-244`). `_fetch` consumes the budget and awaits the pacer (`:246-261`). `IemMosProbeTransport` subclasses it at `:264`. | AFOS and LAV are new subclass methods on this class (F13-R6). A second IEM transport would bypass the pacer and budget. |
| Hardened S3/NOMADS client | `src/breezy/ingest/nbm_quantile_transport.py`; the single-pass sha256 digest is at `:449`. | **(r3, R19)** Reuse `NbmQuantileTransport` (GET) for any NBP poll. No new S3 client. Mirror its shape only for the MDL transport. |
| Archive cache | `src/breezy/persistence/archive_cache.py`. `ArchiveRequest` (`:96`) has exactly `source, station, product, window_start, window_end, model`. `source` matches `[a-z0-9-]` (`:62`, checked at `:107`). Payload path `<root>/<source>/<cache_key>.csv` (`:393`). `IEM_MOS_MODEL_PRODUCTS` is MOS-only at `:59`. `iem_mos_request` is at `:211`. Factories are re-exported via `src/breezy/persistence/archive_request.py`. | **`ArchiveCache` is unmodified (r3, R17).** `IEM_MOS_MODEL_PRODUCTS` is unedited. A separate `US_SOURCE_PRODUCTS` table is added. New request factories are re-exported via `archive_request.py` (r3, R20). Key freeze is OPEN-2. |
| **`available_at` floor rule** | `src/breezy/persistence/nbp_derived_store.py:142-153` (**Correction:** not under `ingest/`). The floor is `PUBLICATION_LAG_FLOOR_NS` (`:81`), which equals `MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]` (`src/breezy/domain/forecast_point.py:165`). | **(r3, R20)** The new pure function takes its per-source floor from `MINIMUM_PUBLICATION_LAG_NS`, not from a literal in the new module. Sources absent from that table (LAMP, GFS MOS, PFM) get a floor from the prereg A0 table. The implementer verifies which keys exist. |
| **`crps_numerical`** | `src/breezy/analysis/nbp_calibration.py:529`. Takes `(cdf callable, observed, *, center=...)`. Fixed 0.1 °F grid, ±40 °F (`:523-524`). | The blend scorer. Pass the blend μ as `center`. |
| `crps_normal` | `nbp_calibration.py:510`. It is a test oracle for the fit path. It is also used in the separate correction scorer at `:1451`, which this plan does not touch. | Test oracle for the Student-t and normal limits. Not in the fit path. |
| Champion fit entry points | `fit_hierarchical_emos` `:1166`, `fit_calibration` `:1280`, `open_holdout` `:353`. | Untouched (F13-R4). M0 = `fit_calibration`. `open_holdout` is never called. |
| Transport error routing contract | `tests/contract/test_transport_error_routing_contract.py`. A new `TransportError` subclass needs a route in `breezy.ingest.routing.TRANSPORT_ERROR_ROUTES`, a recipe in `TRANSPORT_ERROR_CONSTRUCTORS` (`:65`), and an explicit import in the contract test. | See R18 below. |
| Firewall guard helpers | `find_write_transport_importers` at `tests/unit/test_polymarket_us_write_transport.py:92`. `BANNED_EXEC_TRANSPORT_MODULES` at `tests/unit/test_execution_egress_firewall_guard.py:1862`, used at `:2310` by `find_exec_transport_violations` (`:2298`). `find_order_sender_reference_violations` at `:4242` only scans `self._order_sender` references and is not an import scan. | **(r3, R10)** M6(a) does not reuse `BANNED_EXEC_TRANSPORT_MODULES` as its banned set. It defines its own set. The only firewall-file edit is one WIDENED row (see M6). |
| **`lint-imports` scope** | `pyproject.toml:71`: `root_packages = ["breezy", "nautilus_trader"]`. | **(r3, R10)** `lint-imports` covers `src/` only. M6 is the only import check over `scripts/`. |
| Launch window | `src/breezy/persistence/autonomy/capture_schedule.py:3`, [16:30Z, 17:10Z). `launch_window_guard(now_ns, flock_wait_s, timeout_start_s)` at `:36`. `seconds_outside_launch_window(start_ns, end_ns)` at `:54`. | **(r3, R11)** The collector calls these in-process. See H5. |
| C3 invariants | `src/breezy/persistence/autonomy/lineage.py:73-74`. | Phase D only (gate statement). |

Recorded constraints:
- E-26 rules 2 and 4 stand.
- AUT-S Phase 0: G2 is empty.
- M1: MDE is far above a realistic edge.
- NBM spread was too narrow (about 2 °F, against 3–8 °F misses).

Not verified, and so an A0 probe item: the survey's arXiv figures, the LAMP/AFOS/MDL URLs and timings, and the PFM point-to-station mapping. The `ForecastPoint` field and `MINIMUM_PUBLICATION_LAG_NS` keys for LAMP, GFS MOS and PFM were also not checked.

## 2. Data contract (F13-R5, R20, R21)

Normalised CSV row: `source, source_version, station_icao, run_ts_utc, valid_ts_utc, variable, value, unit, available_at_utc, available_miss_utc, available_at_basis, host_tag, revision, raw_sha256, fetched_at_utc, late`.

- **`source` has one value per writer (r3, R20):** `us-lamp-live` (C1 LAMP), `us-lav-iem` (IEM LAV), `us-pfm-afos` (IEM AFOS PFM), `us-lamp-mdl` (MDL tars). Each is a separate `ArchiveCache` source directory and manifest, and there is no shared writer.
- **`available_at_basis` ∈ {`measured_header`, `wmo_header`, `first_seen`, `nominal_plus_conservative_lag`}.**
  - Mirror hosts are tagged in `host_tag` and in the basis suffix, for example `measured_header@iem`.
  - IEM/MDL `Last-Modified` is the **mirror ingest time**, never labelled `wmo_header`.
- **Interval, not a point.** Availability is recorded as `(available_miss_utc, available_at_utc]`. Backtest anchors use the upper bound.
- **Floor rule.** `us_source_availability.available_at(source, version, run_ts, observed) -> (ts, basis, miss_ts)` is pure and uses the `max(observed, run + floor)` pattern. It does not import from the NBP store. The floor comes from `MINIMUM_PUBLICATION_LAG_NS` (r3, R20; see §1). `test_floor_rule_matches_nbp_available_at_ns_on_shared_fixtures` pins the parity.
  - PFM: the WMO header time is exact.
  - LAMP: run + 60 min until measured.
  - GFS MOS: run + at least 5 h until measured.
- **Frozen backtest lags ≥ the maximum observed by C1 over ≥ 14 days (F13-R5).** **(r3, R21)** Rows flagged `late` are right-censored and excluded from the lag-freeze maximum. Until C1 has 14 days, Phase A scoring does not run.
- Clock: NTP offset is recorded with `fetched_at` on every cycle. An offset above the pre-registered bound refuses and alerts (LOW).

## 3. Holdout (r3, R12)

1. **Phase A scores only days < 2026-07-01 against CLI.** It never uses a market input and never calls `open_holdout`.
2. **Any blend-versus-market comparison is forward-only shadow,** on days strictly after a committed freeze (sha-pinned prereg plus fitted weights).
3. **B1** reads source forecast values (not champion output) and no outcome. Its days are scan days that never count as evidence. Its single read is pre-registered.
4. **Post-freeze forward-ledger carve-out.** B2 and the veto forward shadow read only days strictly after the freeze, and only through the live forward ledger written after the freeze. They never read a sealed day (≥ 2026-07-01) from any other path. Test: `test_b2_and_veto_read_only_post_freeze_days_via_live_ledger`.
5. **No tape exists for 07-01 to 08-29,** so no Phase A fold overlaps the market.
6. **Veto analysis tension.** Real FQ takes exist only from 2026-08-30. The blend applied to those days is a forward descriptive shadow on scan days, never evidence. The pre-07-01 version uses an out-of-fold model-side proxy (see Phase A).

## F13-C1: live collector (own queue row)

**Scope.**
- (a) The hourly LAMP live archive.
- (b) Measured availability times for NBP, PFM and LAMP.

GFS MOS and PFM *history* are backfilled from IEM, not collected. HRRR, MEX, the NAM ablation and GFS MOS in C1 are cut.

**NBP observation (r3, R19).** NBP availability is a header-only GET through the existing `NbmQuantileTransport`. B0 first checks whether the node's `ForecastPoint` NBM_NBP vintages exist. If they do, C1's NBP poll is a cross-check only. C1 never writes NBP rows into the NBP store.

**Form.** A systemd user timer fires a oneshot unit per source and cycle. It runs to completion and is idempotent. C1 is a separate domain, and the node never reads it.

**Revisions (r3, R17).** `ArchiveCache` is unmodified.
- `us_source_revision_store` owns revisions. It fetches directly and compares the sha256 against the stored first-seen revision.
- A changed payload is written as a new entry with `product=<…>-r<N>` and `window_start=run_ts`, through `ArchiveCache`'s flock single writer.
- `ArchiveCache.get_or_fetch` is never the change detector.
- Key: `(source, run_ts, revision)`.

**Cadence.**
- LAMP: hourly, a poll burst around HH:30–HH:50. The first poll that sees the product sets `available_at`, and the last poll without it sets `available_miss`.
- PFM: polls around the two issue windows.
- NBP: the cycle times.

**Firing rules (r3, R11).**
- The collector enforces the 16:30Z deadline **in-process**. It calls `launch_window_guard` (`capture_schedule.py:36`) before each firing and `seconds_outside_launch_window` (`:54`) to bound its work. `RuntimeMaxSec` is a backstop only.
- A firing that would overlap [16:30Z, 17:10Z) is skipped and rerun at 17:10Z with `late=true`.

**Files.**

| Status | File |
|---|---|
| NEW | `src/breezy/ingest/mdl_lamp_transport.py` (MDL only: exact host frozenset, M8 binding; the only place a new `TransportError` subclass may live, R18) |
| NEW | `scripts/venue/iem_afos_lav.py` or `PacedIemTransport` subclass methods `fetch_afos_pfm`, `fetch_lav` (F13-R6). Per-method byte caps and closed station and path sets (R21). |
| NEW | `src/breezy/ingest/us_source_availability.py`, `lamp_parse.py`, `pfm_parse.py` |
| NEW | `src/breezy/persistence/us_source_revision_store.py` (append-only revisions, H4, R17) |
| NEW | `scripts/collect/us_source_collector.py` (cycle driver, in-process deadline) |
| NEW | `ops/systemd/us-source-collector@.service` and `.timer`, plus the bwrap profile |
| NEW | `tests/contract/test_us_source_ingest_egress_guard.py` (M6) |
| EDIT (closed sets, widening only) | `scripts/venue/iem_mos_probe_transport.py` `:58-59` (KNYC), and new AFOS and LAV path constants beside `:62`. |
| EDIT (additive) | `src/breezy/persistence/archive_cache.py`: a **new** `US_SOURCE_PRODUCTS` table. `src/breezy/persistence/archive_request.py`: re-export of the new factories (R20). |
| EDIT (one WIDENED row) | `tests/unit/test_execution_egress_firewall_guard.py`: add `breezy.ingest.mdl_lamp_transport` to `BANNED_EXEC_TRANSPORT_MODULES` (`:1862`). This is the only firewall-file touch (R10). |
| EDIT (registration, only if MDL defines a new error class) | `breezy.ingest.routing.TRANSPORT_ERROR_ROUTES`, `TRANSPORT_ERROR_CONSTRUCTORS`, and an explicit import in `tests/contract/test_transport_error_routing_contract.py` (R18). |

**Error routing (r3, R18).**
- AFOS and LAV raise only existing `breezy.ingest.http` errors. They define no new `TransportError` subclass.
- A new `TransportError` subclass may exist only in `mdl_lamp_transport.py`. It needs a route, a constructor and an explicit import in the contract test, all in the same change.
- Parser and revision-store refusals are local non-transport exception classes on a refuse-and-alert path. They are not `TransportError`.

**Security requirements (F13-R7, R11, R21), each with a test.**

*H1, every new transport.*
- Exact-match host frozenset, https and port 443.
- `follow_redirects=False`: any 3xx is an error.
- `trust_env=False` plus the proxy-env check.
- GET only, explicit connect and read timeouts, and a per-source and **per-method (r3, R21)** byte cap.
- 429 honours `Retry-After`. The IEM 1 s interval is kept by reusing the pacer.
- AFOS and LAV use closed station and path sets.

Tests:
- `test_transport_refuses_3xx_to_allowed_host`
- `test_transport_refuses_3xx_to_disallowed_host`
- `test_transport_refuses_non_exact_host_suffix_and_subdomain`
- `test_transport_refuses_non_https_and_non_443`
- `test_transport_refuses_proxy_env`
- `test_transport_is_get_only`
- `test_oversize_body_refused_by_cap`
- `test_afos_and_lav_have_per_method_byte_caps`
- `test_afos_and_lav_refuse_station_or_path_outside_closed_set`
- `test_rate_limit_429_backoff_respects_retry_after`
- `test_afos_and_lav_use_paced_iem_transport_not_a_second_transport`
- `test_afos_and_lav_raise_only_existing_http_errors`

*H2, tar handling.*
- Stream mode `r|gz` (r3, R21). Never `extract` or `extractall`.
- `isreg()` members only.
- Output path derived from `(source, run_ts)` only, never from a member name.
- Caps on member count, per-member size and total decompressed bytes.
- **(r3, R21)** A cap on the compressed download. Decompressed bytes are counted as they stream, so a gzip bomb trips the cap before it is written.

Tests:
- `test_tar_rejects_dotdot_member`
- `test_tar_rejects_absolute_member`
- `test_tar_rejects_symlink_and_hardlink_members`
- `test_tar_rejects_oversize_member_and_total_and_member_count`
- `test_tar_refuses_oversize_compressed_download`
- `test_tar_counts_decompressed_bytes_while_streaming_and_refuses_bomb`
- `test_tar_stream_filters_stations_without_buffering_whole_tar`
- `test_output_path_never_derived_from_member_name`

*H3, parsers.*
- Bounded line and field counts, strict UTF-8 decode, and physical range and unit checks.
- A bad row **refuses the run and alerts**. It is never skipped.
- Closed station and point maps. An unmapped point is refused.

Tests:
- `test_parser_refuses_row_out_of_physical_range`
- `test_parser_refuses_non_utf8`
- `test_parser_refuses_line_and_field_count_over_bound`
- `test_pfm_unmapped_point_refused`
- `test_pfm_parse_selects_station_point_and_max_row`
- `test_lamp_daily_max_uses_climate_day_lst_window`
- `test_bad_row_refuses_run_and_emits_alert`
- `test_parser_and_revision_refusals_are_not_transport_error_subclasses`

*H4, integrity.*
- A changed payload for the same key appends a **new revision** (R17 mechanism). Overwrite is impossible.
- The first-seen revision anchors timing. An unconfirmed change is never promoted.
- An outlier more than N °F from every other source is quarantined. N is pre-registered.

Tests:
- `test_changed_payload_for_same_key_appends_revision_not_overwrite`
- `test_revision_written_as_product_suffix_r_n_with_window_start_run_ts`
- `test_get_or_fetch_is_never_used_as_change_detector`
- `test_archive_cache_module_is_byte_unchanged`
- `test_unconfirmed_outlier_not_promoted`
- `test_first_seen_revision_is_the_anchor_revision`
- `test_quarantined_outlier_excluded_from_features_and_counted`

*H5, the C1 unit (r3, R11).*
- **ExecStart is the bwrap profile** with: `--clearenv --unshare-all --share-net --die-with-parent`, a read-only minimal root, `--tmpfs $HOME`, the archive directory as the sole read-write bind, and `alerts.env` read-only. The implementer takes the exact argument list from the security review.
- No credentials. `~/.config/breezy` is not mounted.
- `alerts.env` must hold only the alert sink. The implementer verifies this and never prints values.
- `MemoryMax`, `LimitNOFILE` (set in the unit; the `systemd-run` soft limit is 1024), `TasksMax`, and `RuntimeMaxSec` as a **backstop** (never past 16:30Z). The in-process deadline is primary.
- A unit-level `flock`, so an overlapping run is skipped.
- Boundary clock tests at 16:29:59, 16:30:00, 17:09:59 and 17:10:00.
- **Behavioural probe** under the exact bwrap profile. It asserts that credentials and the config dir are absent, that writes outside the archive dir fail, and that the alert sink is reachable. It skips only when `bwrap_ok` fails (`scripts/ci/run_tests_no_egress.sh:60`), with the reason recorded.

Tests:
- `test_unit_execstart_is_the_bwrap_profile_with_clearenv_unshare_all_share_net_die_with_parent`
- `test_unit_has_no_credential_env_or_config_mount`
- `test_bwrap_probe_blocks_credentials_and_writes_outside_archive_dir` (skip reason only if `bwrap_ok` fails)
- `test_alerts_env_holds_only_alert_sink_keys_values_never_printed`
- `test_unit_sets_memory_nofile_tasks_caps`
- `test_runtime_max_is_backstop_and_never_extends_past_16_30z`
- `test_collector_enforces_deadline_in_process_via_launch_window_guard`
- `test_overlapping_run_skipped_by_flock`
- `test_clock_boundary_16_29_59_runs`
- `test_clock_boundary_16_30_00_skips`
- `test_clock_boundary_17_09_59_skips`
- `test_clock_boundary_17_10_00_runs_late_flagged`
- `test_late_rows_excluded_from_lag_freeze_maximum`

*M6, NO-SEND ruling (r3, R10). The firewall is not touched beyond the single WIDENED row.*
- **M6(a) has its own banned set.** It lists the write transport, the order sender, the permit, `breezy.runtime`, the exec client and `breezy.exec`. The implementer cites the file and line of each module.
- **It is a transitive import-closure check** over `breezy.*` and `scripts.*` imports. It is **scanned by directory** over `src/breezy/ingest/`, `scripts/venue/` (including `iem_mos_probe_transport.py`) and `scripts/collect/`. A new file in those directories is covered with no registration step.
- `BANNED_EXEC_TRANSPORT_MODULES` is not reused as M6's banned set. The one WIDENED row adds `breezy.ingest.mdl_lamp_transport` to it, and the x1 pin test asserts a superset against a recorded baseline.
- **Reverse test:** no `breezy.exec` or runtime module imports any C1 module.
- **State plainly:** `lint-imports` covers `src/` only (`root_packages`, `pyproject.toml:71`), so M6 is the only import check over `scripts/`.
- The guard runs under the no-egress gate with `MockTransport` and no live fetch in CI. Live fetches run only from offline tools or the C1 units, never from the node or from pytest.

Tests:
- `test_data_transports_have_no_transitive_import_of_write_transport_order_sender_permit_runtime_exec_client_or_exec`
- `test_m6_scans_by_directory_including_iem_mos_probe_transport`
- `test_no_exec_or_runtime_module_imports_any_c1_module`
- `test_data_transports_use_only_http_get` (AST)
- `test_no_polymarket_kalshi_or_exec_host_in_any_allowlist`
- `test_guard_runs_with_mock_transport_and_no_live_fetch`
- `test_exec_import_pin_x1_is_superset_of_recorded_baseline`
- `test_mdl_lamp_transport_in_banned_exec_transport_modules`

*M8.*
- Exact S3 bucket FQDNs are pinned, with a host-to-path-prefix binding. `*.amazonaws.com` is never used.
- `test_s3_host_bound_to_its_path_prefix`
- `test_wildcard_amazonaws_host_refused`

*LOW.*
- `redact_url` on every logged URL.
- A project-alias User-Agent contact, not the operator's email.
- NTP offset recorded with `fetched_at`.
- The disk guard is a hard refusal.

Tests:
- `test_user_agent_contains_project_alias_not_operator_email`
- `test_logged_urls_are_redacted`
- `test_disk_guard_refuses_below_threshold`
- `test_ntp_offset_recorded_and_excess_refuses`

*Reuse and registration (F13-R6, R18, R20).*
- `test_mdl_transport_error_has_route_constructor_and_contract_test_import` (only if MDL defines a new class)
- `test_us_source_products_table_does_not_modify_iem_mos_model_products`
- `test_each_writer_has_exactly_one_source_value`
- `test_new_factories_reexported_via_archive_request`
- `test_normalised_csv_roundtrips_through_archive_cache_with_digest`

*Idempotency and observability.*
- `test_cycle_is_idempotent_after_midwrite_kill`
- `test_rerun_never_duplicates_payload_or_manifest_entry`
- `test_available_at_is_observed_header_never_assumed`
- `test_first_seen_basis_and_miss_interval_recorded`
- `test_mirror_host_tagged_in_basis`
- `test_stale_source_alerts_after_deadline`

**Acceptance (C1).**
- 14 consecutive days with ≥ 95 % of expected cycles captured.
- Zero duplicate payloads.
- Every row has an observed `available_at` with a basis and an interval.
- The measured maximum lag per source (`late` rows excluded) is published as an A0 table. It freezes the Phase A backtest lags.

**Dependencies:** none. C1 needs no node respawn and no row 7. It needs the security review of the new egress hosts and the unit before the first live firing.

## Phase A0 / B0 (week 1)

**A0 (read-only probe, one day per source, writes a feasibility record).**
- Confirm every URL and the tar layout.
- Confirm PFM point names, with a closed station map for KNYC `NYZ072` and the other four.
- Confirm LAMP timing, the rate limit, and the member mtimes.
- Confirm that the MDL tars end in 2025.

**B0 (offline, days).**
- **B1 power pre-registration (r3, R14).** The preregistration fixes:
  - the plausible slope;
  - α = 0.025, Holm over 2;
  - power 0.8;
  - the analysis unit, which is the event-day, clustered by climate day.

  The SD comes from the placebo and pre-window arms. The B1 slope CI is a day-block bootstrap. The MDE comes from this empirical SD and is not scaled from M1. If the MDE exceeds the plausible slope, B1 records UNDERPOWERED.
- **Placebo feasibility.** Count the no-update days at the same clock time, and the days with METAR-offset matches. **Expect the PFM no-update placebo pool to be empty (r3, R14),** because PFM updates on a fixed schedule. In that case PFM runs descriptive only and relies on the pre-window and METAR-offset controls.
- **60 s resolution check (r3, R13).** Show that the Depth10 cadence per station-window resolves 60 s. If it does not, the B2 "adjusts under 60 s" STOP is recorded as untestable.
- **Tape inventory.** Depth10 cadence and coverage per station-window since 08-30. QuoteTicks cannot show an empty bid.
- **NBP vintage check (r3, R19).** Do the node's `ForecastPoint` NBM_NBP vintages exist? If so, the C1 NBP poll is a cross-check only.
- **Release census.** PFM WMO times from IEM AFOS, NBP measured vintages from the catalog if present, LAMP nominal until C1 has data.
- **Backfills.** PFM history (2021 onward) and GFS MOS (including KNYC) come from IEM through `PacedIemTransport`.

Tests:
- `test_mde_reported_before_any_effect_estimate`
- `test_b0_power_prereg_fixes_alpha_0_025_holm2_power_0_8_event_day_cluster`
- `test_b0_sd_taken_from_placebo_and_pre_window_arms`
- `test_b0_stops_underpowered_when_mde_exceeds_plausible_slope`
- `test_placebo_pool_feasibility_counted_per_stratum_and_empty_pfm_pool_goes_descriptive`
- `test_b0_reports_whether_depth10_cadence_resolves_60s`
- `test_b0_checks_node_nbp_vintages_exist_before_c1_nbp_poll_role`
- `test_pfm_wmo_header_time_is_available_at`
- `test_available_at_never_precedes_run_ts_for_any_source`
- `test_conservative_lag_not_earlier_than_measured_live_lag`
- `test_gfs_mos_closed_day_guard_does_not_apply_to_lav_or_pfm`

## Phase B1: timing event study

**Fixed rules.** CLI-free and champion-free. It reads source forecast values and no outcome (R12). Its days are scan days that never count as evidence. The single read is pre-registered.

- **Release time = measured first public availability** from C1 or the PFM WMO header. It is never the nominal run time. Before C1, only PFM has an exact time. NBP uses measured vintages if the catalog has them, otherwise it is omitted.
- **Primary family (Holm over 2, α = 0.025):** {PFM at the WMO time, the NBP cycle at its measured vintage} × the 60-min window.
- **Descriptive only:** the 15-min window (nested), and LAMP (hourly).
- **Outcome (r3, R16).**
  - The **signed** change in the ladder-implied expected daily max.
  - The **matched-rung panel is defined at t only.** A rung is in the panel if both sides are quoted at t. A rung missing at t+Δ is **dropout**, reported per arm, and is not removed from the panel.
  - **Regressor = source value minus the pre-release ladder-implied mean.** The slope is the primary statistic, with a day-block bootstrap CI (R14).
  - Differential missingness is itself an outcome.
- **Placebos and controls.**
  - The same clock time on days the source did not update.
  - Matching on minute offset from the METAR release (:51–:56).
  - A within-day pre-window, [t−60, t] versus [t, t+60].
- **Interpretation limit.** A significant slope says the market reacts around releases. It does not establish a tradable lag.

Files: NEW `src/breezy/analysis/release_timing.py` (pure), NEW `scripts/analysis/release_timing_event_study.py` (read-only, memory-capped), NEW `scripts/analysis/release_census.py`.

Tests:
- `test_event_study_uses_no_champion_output_cli_or_outcome_values`
- `test_release_time_is_measured_first_availability_never_nominal`
- `test_matched_rung_panel_defined_at_t_only_missing_t_plus_delta_is_dropout`
- `test_regressor_is_source_value_minus_pre_release_ladder_implied_mean`
- `test_dropout_and_differential_missingness_reported_per_arm`
- `test_signed_change_regressed_on_forecast_delta`
- `test_placebo_same_clock_time_on_no_update_days`
- `test_placebo_matched_on_metar_minute_offset`
- `test_pre_window_control_runs_for_every_event`
- `test_holm_over_exactly_two_primary_tests_at_alpha_0_025`
- `test_b1_slope_ci_is_day_block_bootstrap`
- `test_fifteen_minute_and_lamp_results_labelled_descriptive`
- `test_empty_bid_rungs_excluded_and_counted`
- `test_event_windows_never_cross_16_30_17_10z_without_flag`
- `test_release_timestamp_provenance_recorded_per_event`
- `test_b1_stops_when_b0_mde_exceeds_plausible_effect`
- `test_b1_prereg_sha_recorded_and_single_read_enforced`

## Phase B2: realised-EV futility screen (r3, R12, R13)

**Signal, entry and freeze.**
- **Signal:** a measured release from C1 or the PFM WMO header, with the source value moving the implied daily max in a pre-registered direction.
- **Entry:** a simulated take at the actual ask available at the lag, sized by depth at the ask.
- **Freeze = the B1/B2 prereg commit sha.** It is independent of Phase A, so B2 does not wait for the Phase A freeze.
- **Data:** forward C1 data and the live ledger after the freeze (R12). No scan day and no sealed day counts.

**Outcome.** Realised EV per take at settlement, **net of** the fee θ·p(1−p) evaluated at the fill price, the 0.01 slippage floor and `margin(h)`, at the actual fill price. Drift is a diagnostic only.

**Lags.**
- **The primary lag is the pre-registered median fetch-to-decision latency.** It is measured, not the single 44 s LAX case, and it is reported as a distribution.
- The lag curve at 0, 30, 60, 120 and 300 s is descriptive only.

**Stop rules and verdict.**
- "Market adjusts under 60 s" means the time to reach 50 % of the move, measured on Depth10. If B0 shows the cadence cannot resolve 60 s, the STOP is recorded as untestable.
- Outcomes are **FUTILE / INCONCLUSIVE / NOT-FUTILE.** It is a futility screen, not a confirmation (about 1,500 trades would be needed for 3¢).
- If F7b is not merged, B2 reports a descriptive fixed-n result with no verdict.
- **The R9 gate requires NOT-FUTILE.** INCONCLUSIVE does not open C2/D. This amends the earlier "not futile" wording.

Tests:
- `test_b2_outcome_is_realised_ev_net_of_theta_p_1_minus_p_slippage_and_margin`
- `test_b2_signal_entry_and_freeze_are_prereg_defined`
- `test_b2_freeze_is_b1_b2_prereg_sha_independent_of_phase_a`
- `test_b2_primary_lag_is_preregistered_median_latency_others_descriptive`
- `test_b2_lag_curve_points_exactly_0_30_60_120_300`
- `test_b2_latency_is_a_distribution_not_a_constant`
- `test_b2_depth_at_ask_limits_simulated_size`
- `test_b2_adjustment_time_is_time_to_50pct_of_move_on_depth10`
- `test_b2_untestable_stop_recorded_when_cadence_cannot_resolve_60s`
- `test_b2_verdict_is_futile_inconclusive_or_not_futile`
- `test_b2_labelled_futility_screen_never_confirmation`
- `test_b2_refuses_days_before_freeze`
- `test_b2_and_veto_read_only_post_freeze_days_via_live_ledger`
- `test_ref_ts_lt_decision_ts_for_every_b2_row`

## Phase A1 / A: archives, the blend and the veto analysis

**Archives (A1; HRRR, MEX and NAM are cut).**
- PFM: IEM AFOS for the five offices, 2021 onward (`us-pfm-afos`).
- GFS MOS: the existing backfill plus KNYC.
- LAMP: MDL tars to 2025 (`us-lamp-mdl`), streamed through the H2 handler. IEM LAV (`us-lav-iem`) fills the 2026 gap, with the basis flagged. C1 (`us-lamp-live`) supplies it going forward.
- Only days < 2026-07-01 reach the fit or the score. Later archives are kept for the forward feed.

**Procedure (F13-R4, R15).**
- **The champion is untouched.** M0 = `fit_calibration`. `test_nbp_calibration_module_is_byte_unchanged` is pinned to a recorded sha.
- M1–M3 are fit in a new `src/breezy/analysis/multisource_blend.py`, scored with `crps_numerical` (`:529`) and `center` = the blend μ.
- **M0′** is the new procedure with k = 0. It must match M0's CRPS within a pre-registered tolerance.
- **Test statistic: Δ = CRPS(M0′) − CRPS(M3).**
- **Distribution.** Student-t, with `log σ = c + d·log(NBP spread) + e·log(sd of the sources' μ)`, floored. The primary comparison uses an identical σ treatment on both arms. The disagreement-σ term is a separate, later ladder step.
- **Weights.** Shrinkage toward a sum of 1, not a hard box.
- **Ladder.** M0′, then M1 (+LAMP), M2 (+PFM) and M3 (+GFS MOS). K = 1. The primary hypothesis is M3 versus M0′. RMSE is descriptive only.
- **v5 never mints (AS-R14).**

**Acceptance (r3, R15).**
1. Paired ΔCRPS with a day-block bootstrap CI (stationary, mean block 7 days, by climate day across stations). **The LB is one-sided 97.5 % and must be > 0.**
2. **Minimum-effect floor = a pre-registered multiple of the M0 fold-to-fold CRPS SD.** It is committed to the prereg **before M1–M3 are scored.** The r1 "3 %" figure is withdrawn.
3. **Also require CRPS(M0) − CRPS(M3) LB > 0 and ≥ the floor,** so the gain is measured against the actual champion as well as M0′.
4. **ACCEPT is refused if M0′ is worse than M0 beyond the tolerance.**
5. The same sign in ≥ ⌈0.75·n_folds⌉ folds.
6. A Δ above the fold spread becomes `HELD_LEAK_AUDIT`.
7. No station degraded beyond a pre-registered tolerance.
8. **Lag-sensitivity rerun:** the scoring is repeated with every source lag +60 min. ACCEPT requires the sign to hold.
9. **Co-reported diagnostics:** CRPS by horizon, PIT, 80 % and 95 % coverage, the log score on the rung ladder, and RMSE (descriptive).

Otherwise **STOP:** record NO_SKILL, stop Phase D, and keep B1 and C1 running.

**Folds.** Blocked within each NBM version. A version enters only with ≥ 2 blocks of ≥ 28 held and ≥ 28 train days. No fold straddles a source break (the pre-registered list from A0). The positive control is that M0 reproduces the committed champion. The negative control is a shuffled-label Δ ≈ 0.

**Veto analysis (F13-R8, R15).**
- *Question:* how many FQ-style takes would the blend have refused, and what were their CLI outcomes.
- *Pre-07-01 descriptive proxy.*
  - No tape exists before 08-30, so no historical FQ take has a price before 07-01.
  - The take set is a **model-side proxy of the FQ rule that uses out-of-fold champion output (r3, R15)** and a pre-registered reference. Fitted-in-sample champion output is never used.
  - It reports refusal rate, and CLI outcomes of refused versus kept takes, by station. It is descriptive and carries no verdict.
- *Real FQ takes (≥ 08-30)* get a forward shadow veto count only, read through the live ledger (R12). They are scan days and never evidence.
- *Forward use is shadow only.*
- **OPEN-3:** the exact FQ take rule that the proxy mirrors must be copied from the FQ-LOSS-RESPONSE plan r3 and frozen in the prereg. It was not re-verified, so the proxy definition stays open until the implementer cites the rule's file and line.
- **Out of F13 scope.** The pooled NO-side favourite-longshot test goes to a separate M1-v3 item. Maker and resting orders go to the existing resting-bid line. A Kalshi lead-lag signal is **rejected** (venue prices are execution cost only).

Files:

| Status | File |
|---|---|
| NEW | `src/breezy/analysis/multisource_blend.py` (pure) |
| NEW | `scripts/analysis/multisource_blend_skill.py` (runner, memory-capped) |
| NEW | `scripts/analysis/blend_veto_descriptive.py` |
| NEW | `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json` (Phase A) and a separate B1/B2 prereg whose commit sha is the B2 freeze (R13) |

Tests:
- `test_nbp_calibration_module_is_byte_unchanged`
- `test_blend_m0_prime_matches_champion_crps_within_tolerance`
- `test_accept_refused_when_m0_prime_worse_than_m0_beyond_tolerance`
- `test_blend_uses_crps_numerical_with_blend_mu_as_center`
- `test_blend_identical_sigma_treatment_across_primary_arms`
- `test_blend_student_t_log_sigma_includes_source_disagreement_only_in_separate_step`
- `test_blend_sigma_floor_prevents_overconfidence`
- `test_blend_weight_sum_shrinks_toward_one_not_hard_box`
- `test_blend_nonfinite_input_refused_not_imputed`
- `test_lamp_peak_window_not_covered_is_missing_not_imputed`
- `test_feature_rows_all_available_before_anchor`
- `test_folds_blocked_within_version_and_never_straddle_source_break`
- `test_negative_control_shuffled_labels_gives_zero_delta`
- `test_no_row_on_or_after_2026_07_01_reaches_the_fit_or_score`
- `test_open_holdout_is_never_called`
- `test_prereg_sha_is_recorded_before_scoring_and_run_refuses_if_changed`
- `test_floor_is_prereg_multiple_of_m0_fold_sd_committed_before_m1_m3_scored`
- `test_acceptance_requires_floor_and_one_sided_975_lb_gt_zero`
- `test_acceptance_also_requires_m0_minus_m3_lb_gt_zero_and_ge_floor`
- `test_acceptance_stops_when_ci_lower_bound_not_positive`
- `test_fold_sign_rule_is_ceil_075_n_folds`
- `test_lag_sensitivity_rerun_plus_60_min_reported_and_sign_must_hold`
- `test_crps_by_horizon_pit_coverage_and_log_score_are_reported`
- `test_phase_a_refuses_to_score_until_c1_has_14_days_of_measured_lags`
- `test_veto_proxy_uses_out_of_fold_champion_output`
- `test_veto_report_uses_no_market_price_before_2026_08_30`
- `test_veto_forward_shadow_never_feeds_a_verdict`

**Gates:** `scripts/ci/run_tests_no_egress.sh` after every merge. `lint-imports` from the tree with the "N kept, 0 broken" line. Firewall guards in every focused gate. Adapters never import `breezy.runtime`.

## C2 / D: gate statement only (F13-R9, R13)

C2 (a node-resident `DataActor`) and D (`density_table_multisource`) are **not planned here**. They need all of the following:

- Phase A ACCEPT.
- **The forward B2 result NOT-FUTILE** (r3, R13). INCONCLUSIVE and FUTILE do not open the gate.
- F1 (E-26 filed), F4 and F7b (evaluator and e-process), F5 (PREREG amendment).
- AUT-3 (`c3_writer`).
- Row 7 (node wiring).
- **F6** (C2 composes inside `_compose_forecast_quantile_ladder`, E-28).
- The **ARCH-0 owner** for `pins.py:96`.
- The **AUT-4 OFFLINE_CHALLENGER screen**.
- The F12 PROMOTE enable for the CHAMPION step.

When the gate opens, M7 applies: an AST transitive import-closure check, a bridge with a hard timeout, activation only at the 16:50Z LAUNCH, and the activation commit parked on a branch until the gates pass. Not reachable before KILL.

## Risk register

| Risk | Containment |
|---|---|
| Leakage (`available_at` ≥ anchor) | The interval basis. Upper-bound anchors. Frozen lags ≥ the C1 maximum over ≥ 14 days, `late` rows excluded. A scored-row assertion `max(available_at) < anchor`. Date AND hour scoping. The +60-min lag rerun. A Δ above the fold spread becomes `HELD_LEAK_AUDIT`. |
| Sealed days read by B2 or the veto | The R12 post-freeze live-ledger-only carve-out and its test. |
| Mirror time mistaken for issuance | `host_tag` and a basis suffix. The WMO header is the only exact PFM time. |
| Tar-borne path, size or gzip-bomb attacks | The H2 stream handler, the compressed cap and decompressed counting. |
| Poisoned or garbled payloads | H3 refusal. H4 append-only revisions via the revision store and outlier quarantine. |
| C1 compromise or credential reach | The bwrap profile as ExecStart, a behavioural probe, only `alerts.env`, no `~/.config/breezy`. |
| C1 overrunning the launch window | The in-process `launch_window_guard` deadline, `RuntimeMaxSec` as a backstop, a skip-and-late rule, boundary tests. |
| C1 import reaches the order path | M6 transitive directory scan, the reverse test, the WIDENED row. `lint-imports` does not cover `scripts/`, so M6 is the only guard there. |
| Second IEM client breaking pacing | AFOS and LAV are `PacedIemTransport` methods. A test asserts no second transport. |
| Routing contract breaks | AFOS and LAV add no error classes. A new `TransportError` subclass lives only in the MDL module and is registered in the same change. |
| `ArchiveCache` used as change detector | `ArchiveCache` unmodified. The revision store compares sha256 itself. |
| Underpowered B1 or B2 | The B0 power prereg and the STOP rule. The PFM placebo pool is expected to be empty, so PFM is descriptive. B2 is labelled futility only. |
| B2 adjustment time untestable | B0 checks cadence resolution. An untestable STOP is recorded. |
| B1 timing is a mirror artefact | Release time = measured first availability from C1 or the WMO header. |
| LAMP horizon too short for D-1 | A missing-indicator, never imputed. |
| LAMP 2026 gap | IEM LAV with the basis flagged, then C1. |
| Version breaks | A pre-registered break list. v5 never mints. |
| Veto proxy not equal to the real FQ rule | OPEN-3. The proxy is descriptive only and out-of-fold. |
| Memory pressure | Streaming parsers, unit caps, one heavy job at a time, a stall watch. Never SIGKILL the node. |
| Disk | A hard-refusal disk guard. Raw tars not retained. |
| Operator-reserved controls, live enablement, permit, firewall, Nautilus | Named or assigned nowhere. None touched. M6 is a guard test, and the single WIDENED row is the only firewall-file edit. |

## Feasibility

- **Doable in week 1:** A0, B0 (power prereg, placebo and 60 s feasibility), and the C1 unit with LAMP archive and availability timing. The C1 first firing needs the security review done.
- **Doable by KILL:** Phase A verdict (it can start only after 14 days of C1 measured lags), B1, the veto descriptives, B2 futility, and 3+ months of C1.
- **Not feasible by KILL:** confirming a 3–8¢ edge or fielding a CHAMPION blend.
- **Edge expectation:** the blend is near zero against the market. A positive result is more likely from B1 and B2, but each has large risks. Those are thin books, an empty bid side, our latency of tens of seconds, and a market that may already be faster than us.
- **Terminal outcome if A is STOP and B1 is NO-GO:** F13's candidate space is exhausted for US public sources. That is recorded as the result.

## Build order

1. **F13-C1 row opens (parallel start).**
   - The prereg JSON skeletons and the A0 probe records (read-only).
   - `us_source_availability.py` with its tests, RED first.
   - Parsers (H3), the revision store (H4, R17), and the MDL transport (H1, H2, M8) with its routing registrations only if it defines a new error class (R18).
   - AFOS and LAV as `PacedIemTransport` methods, with per-method caps.
   - The M6 guard test and the one WIDENED row (R10).
   - The unit file, the bwrap ExecStart, the in-process deadline, the behavioural probe and the clock-boundary tests (H5, R11).
   - Security review. Then start the live timers (LAMP, availability observation) outside the launch window.
2. **B0** (power prereg, placebo and 60 s feasibility, NBP vintage check, tape inventory, release census), in parallel with step 1. PFM and GFS MOS history backfill through `PacedIemTransport`, one heavy job at a time.
3. **B1** after B0 passes its STOP rule. One pre-registered read.
4. **A1 and A.** LAMP archive backfill. The floor is committed before M1–M3 are scored. The blend runs only after C1 has 14 days of measured lags. The freeze commit comes before any forward comparison. The veto descriptives follow OPEN-3.
5. **B2** on C1 data and the live ledger after the B1/B2 prereg freeze.
6. **C2 / D:** only per the gate statement.

Reviewers: `python-reviewer` for code, `prediction-market-reviewer` for the statistics and the market comparison, and `security-reviewer` for the new egress, the M6 guard and the unit.

## OPEN items (with reasons)

- **OPEN-1 (import direction): CLOSED (r3, R20, per the architecture review).** `src/breezy/` cannot import `scripts/`, so the IEM-facing code and the collector driver live under `scripts/`. The MDL transport under `src/breezy/ingest/` is separate. File locations are fixed as in the table above.
- **OPEN-2 (`ArchiveRequest` keys).** The dataclass has no office or point field. A PFM key such as `source="us-pfm-afos"`, `station=<ICAO>`, `product="pfm"`, `model=<WFO>`, and a LAMP per-run tar key with a fixed `station` token, must be frozen in the prereg before any cache is built. Each key uses its writer's `source` value (R20). This needs the A0 probe's layout.
- **OPEN-3 (FQ rule).** The exact take rule the veto proxy mirrors was not re-read. The implementer cites its file and line first.
- **OPEN-4 (A0 facts).** The survey figures, URLs, timings, the 60-min LAMP and 5 h GFS lags, the `MINIMUM_PUBLICATION_LAG_NS` keys for LAMP, GFS MOS and PFM, and the NBP measured-vintage rows are unverified until A0 and C1 produce them.
- **OPEN-5 (numerics).** The minimum-effect multiple, the outlier threshold N, the NTP bound, the M0′ tolerance, the B1 plausible slope and the B2 primary-lag median are frozen in the prereg after B0 and A0, not guessed here.
- **OPEN-6 (r3).** The exact bwrap argument list and the exact banned-module file:line citations are taken by the implementer from the security review and the code at build time. The plan states only the contract.

## Changes from r2

| # | r2 | r3 | Ruling |
|---|---|---|---|
| 1 | M6(a) reused the `find_write_transport_importers` pattern and `BANNED_EXEC_TRANSPORT_MODULES`. | M6(a) has its own banned set. It is a transitive `breezy.*`/`scripts.*` closure check, scanned by directory over `src/breezy/ingest/`, `scripts/venue/` (including `iem_mos_probe_transport.py`) and `scripts/collect/`. | R10 |
| 2 | The firewall was not touched. | One WIDENED row adds `breezy.ingest.mdl_lamp_transport` to `BANNED_EXEC_TRANSPORT_MODULES`. It is the only firewall-file touch. The x1 pin test asserts a superset of a recorded baseline. | R10 |
| 3 | No reverse test. No note on `lint-imports` scope. | A reverse test asserts no `breezy.exec` or runtime module imports any C1 module. States that `lint-imports` covers `src/` only (`pyproject.toml:71`), so M6 is the only check over `scripts/`. | R10 |
| 4 | H5 had `RuntimeMaxSec` as the deadline and a generic bwrap description. | ExecStart is the bwrap profile (`--clearenv --unshare-all --share-net --die-with-parent`, ro minimal root, `--tmpfs $HOME`, the archive dir as the sole rw bind, `alerts.env` ro). A behavioural probe runs under it (skipped only if `bwrap_ok` fails, with the reason). | R11 |
| 5 | Deadline by `RuntimeMaxSec`. | The collector enforces 16:30Z in-process via `launch_window_guard` (`capture_schedule.py:36`) and `seconds_outside_launch_window` (`:54`). `RuntimeMaxSec` is a backstop. | R11 |
| 6 | `alerts.env` was assumed to hold only the alert sink. | The implementer verifies this and never prints values. A test is added. | R11 |
| 7 | B1 was "model-free and CLI-free". | B1 reads source forecast values (not champion output) and no outcome. | R12 |
| 8 | Holdout §3 had no carve-out for the post-freeze ledger. | The carve-out is adopted. B2 and the veto forward shadow read only post-freeze days via the live ledger. New test `test_b2_and_veto_read_only_post_freeze_days_via_live_ledger`. | R12 |
| 9 | B2 signal, entry and freeze were implicit. The "adjusts under 60 s" STOP was undefined. | B2 signal, entry and freeze are defined. The freeze is the B1/B2 prereg sha, independent of Phase A. | R13 |
| 10 | The lag curve at 0/30/60/120/300 s was the main execution detail. | The primary lag is the pre-registered median fetch-to-decision latency. The other lags are descriptive. | R13 |
| 11 | "Adjusts under 60 s" was a STOP condition only. | It means time to 50 % of the move on Depth10. B0 must show the cadence resolves 60 s, otherwise the STOP is recorded untestable. | R13 |
| 12 | Futility screen with a "not futile" gate. | The outcomes are FUTILE / INCONCLUSIVE / NOT-FUTILE. **The R9 gate requires NOT-FUTILE,** so INCONCLUSIVE does not open C2/D. The fee is θ·p(1−p) at the fill, plus 0.01, plus `margin(h)`. | R13 (amends R9) |
| 13 | B0 computed an MDE from the tape SD and counted placebo days. | B0 pre-registers the plausible slope, α = 0.025 Holm over 2, power 0.8, and the event-day unit clustered by climate day. The SD comes from the placebo and pre-window arms. The B1 slope CI is a day-block bootstrap. An empty PFM no-update placebo pool is expected, so PFM is descriptive. | R14 |
| 14 | The minimum-effect floor was "derived from the fold SE". | The floor is a pre-registered multiple of the M0 fold-to-fold CRPS SD, committed before M1–M3 are scored. | R15 |
| 15 | Acceptance compared M3 with M0′ only. | It also requires CRPS(M0) − CRPS(M3) LB > 0 and ≥ the floor. ACCEPT is refused if M0′ is worse than M0 beyond the tolerance. The LB is one-sided 97.5 %. | R15 |
| 16 | No lag-sensitivity check. CRPS was not broken out. | A +60-min lag-sensitivity rerun and CRPS by horizon are added. The veto proxy uses out-of-fold champion output. | R15 |
| 17 | The matched-rung panel required both sides quoted at t and t+Δ. | The panel is defined at t only. A missing t+Δ is dropout. | R16 |
| 18 | The regressor was "the forecast delta". | The regressor is the source value minus the pre-release ladder-implied mean. | R16 |
| 19 | The revision store used `ArchiveCache`'s write path with an ambiguous detection mechanism. | `ArchiveCache` is unmodified. `us_source_revision_store` fetches directly and compares sha256. It writes `product=<…>-r<N>` with `window_start=run_ts`. `get_or_fetch` is never the change detector. Two new tests. | R17 |
| 20 | All new error classes registered in the routing contract. | AFOS and LAV raise only existing `breezy.ingest.http` errors. A new `TransportError` subclass may live only in `mdl_lamp_transport.py`, with route, constructor and an explicit contract-test import. Parser and revision refusals are local non-transport classes on refuse-and-alert. | R18 |
| 21 | C1 polled NBP without a defined mechanism. | NBP observation reuses `NbmQuantileTransport` (GET), with no new S3 client. B0 checks whether the node's NBM_NBP `ForecastPoint` vintages exist. If so, C1's NBP poll is a cross-check only. | R19 |
| 22 | Floor from the NBP store pattern. IEM cites were `:58` and `:60`. `source` naming was unspecified. | The floor comes from `MINIMUM_PUBLICATION_LAG_NS` (`forecast_point.py:165`). **Correction:** the station set is at `:58-59` and `IEM_MOS_PATH` at `:62`. LAV never goes through `iem_mos_request`. The KNYC edit is widening only, never relaxing. | R20 |
| 23 | No per-writer source or factory re-export. OPEN-1 was open. No Nautilus justification for C1. | One `source` per writer (`us-lamp-live`, `us-lav-iem`, `us-pfm-afos`, `us-lamp-mdl`). Factories are re-exported via `archive_request.py`. The C1-off-node Nautilus justification line is added. **OPEN-1 is CLOSED.** | R20 |
| 24 | `late` rows were flagged but counted in the lag max. | `late` rows are right-censored and excluded from the lag-freeze maximum. | R21 |
| 25 | AFOS and LAV had a per-source byte cap. | They have per-method byte caps and closed station and path sets. | R21 |
| 26 | Stream mode `r|`. | Stream mode `r|gz`, a compressed-download cap, and decompressed-byte counting during the stream. | R21 |

Relevant paths (all under `/home/jon/breezy`):
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r1.md`
- `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13-us-source-ingest_plan_r2.md` (the file to supersede with r3; rulings appended there)
- `scripts/venue/iem_mos_probe_transport.py` (`:53-62`, `PacedIemTransport` `:171-261`)
- `src/breezy/ingest/nbm_quantile_transport.py` (digest `:449`)
- `src/breezy/persistence/nbp_derived_store.py` (`:81`, `:142-153`)
- `src/breezy/domain/forecast_point.py` (`MINIMUM_PUBLICATION_LAG_NS` `:165`)
- `src/breezy/persistence/archive_cache.py` (`:59`, `:62`, `:96`, `:211`, `:393`)
- `src/breezy/persistence/archive_request.py`
- `src/breezy/persistence/autonomy/capture_schedule.py` (`:36`, `:54`)
- `src/breezy/analysis/nbp_calibration.py` (`crps_numerical` `:529`)
- `tests/contract/test_transport_error_routing_contract.py`
- `tests/unit/test_polymarket_us_write_transport.py` (`:92`)
- `tests/unit/test_execution_egress_firewall_guard.py` (`:1862`, `:2298`, `:2310`, `:4242`)
- `scripts/ci/run_tests_no_egress.sh` (`bwrap_ok` `:60`)
- `pyproject.toml` (`root_packages` `:71`)

I wrote no files. This is a read-only design for the implementer briefs.

Verified this round with codegraph and grep: `MINIMUM_PUBLICATION_LAG_NS` at `forecast_point.py:165`; `PUBLICATION_LAG_FLOOR_NS` at `nbp_derived_store.py:81`; `launch_window_guard` at `capture_schedule.py:36`; `seconds_outside_launch_window` at `:54`; `iem_mos_request` at `archive_cache.py:211`; the `archive_request.py` re-export module; `_SOURCE_PATTERN` at `archive_cache.py:62`; `BANNED_EXEC_TRANSPORT_MODULES` at `:1862` used at `:2310`; `bwrap_ok` at `run_tests_no_egress.sh:60`; `root_packages` at `pyproject.toml:71`. The IEM station and path line numbers are corrected from r2 (`:58-59` and `:62`).

Not re-verified: the `pins.py:96` ARCH-0 citation, the `MINIMUM_PUBLICATION_LAG_NS` keys for LAMP, GFS MOS and PFM, and `ArchiveCache`'s existing write API for the `-r<N>` product suffix. The last should be checked against `_PRODUCT` validation before the revision store is built.

---

## r3.1 amendments: round-3 rulings F13-R22..R29 (coordinator, 2026-10-06). BINDING over any conflicting r3 text above.

Round 3: security NOT-READY (2 blockers), stats NOT-READY (2), architecture NOT-READY (4). Every blocker had one-paragraph fix text; it is adopted verbatim below. The plan is r3 + these amendments ("r3.1"). Implementer briefs cite both.

- **F13-R22 (M6 scope; security BLOCK-1).** M6(a) scans every `.py` under `scripts/collect/` and `src/breezy/ingest/mdl_lamp_transport.py`. It also scans every `.py` under `scripts/venue/` and `src/breezy/ingest/` that is not in `M6_PREEXISTING_BASELINE`: a recorded, additive-never-shrinking list of file paths with sha256, committed in the test and frozen at this change. Any file absent from the baseline is scanned automatically, with no registration step. The transitive closure from `us_source_collector.py`, `iem_mos_probe_transport.py`, `us_source_availability.py` and the parser modules must be clean. Tests: `test_m6_baseline_excludes_c1_closure`; `test_scripts_collect_exists_and_is_non_empty`. The reverse test scans `src/breezy/exec`, `src/breezy/runtime` and `src/breezy/adapters` by directory. The x1-pin test names the exact pin and baseline location (`test_execution_egress_firewall_guard.py`, implementer cites line).
- **F13-R23 (H5 probe; security BLOCK-2).** The probe skips only when a dedicated `bwrap_profile_ok` fails. That helper runs the exact C1 argument list with `true` as the command and skips with the recorded stderr as the reason. The probe asserts only: (a) `~/.config/breezy` and the credential env names are absent; (b) a write outside the archive dir fails; (c) `alerts.env` is present and read-only-mounted; (d) the alert sink is a path or config key, with no network call; (e) the real collector `--help` entry executes under the profile. Sink reachability is a separate timer-time check, never run in pytest. Per-method byte caps and the `RuntimeMaxSec` margin are frozen under OPEN-5.
- **F13-R24 (B2 verdict rule; stats BLOCK-1).** The verdict is computed on mean realised net EV per take, clustered by climate day.
  - FUTILE: the one-sided 97.5 % upper bound is below the pre-registered minimum useful edge, or the 60 s STOP fires.
  - NOT-FUTILE: the one-sided 97.5 % lower bound is above 0 AND the point estimate is at least the minimum useful edge.
  - Otherwise INCONCLUSIVE.
  - The minimum useful edge, minimum n and take count are frozen in the B1/B2 prereg.
  - Test: `test_b2_verdict_rule_boundaries`.
  - The B2 signal direction is sign(source value − the same source's previous vintage). Price enters only at fill and cost.
  - "The move" is the t+60-min level versus the pre-release level, with a pre-registered minimum move size. It is aggregated by the median across events per source.
  - θ is read from the live pinned value, never hard-coded.
- **F13-R25 (Phase A floor; stats BLOCK-2).** ACCEPT requires the one-sided 97.5 % LB of CRPS(M0′) − CRPS(M3) ≥ floor AND the LB of CRPS(M0) − CRPS(M3) ≥ floor. The +60-min lag rerun requires LB ≥ 0 (not just the sign) and reports the rows lost. Rename the acceptance test to assert LB ≥ floor for both comparisons.
- **F13-R26 (stats nits).**
  - B0 fixes the B1 family size before the read. If NBP vintages are absent, the family is PFM alone at α = 0.025.
  - A rung missing at t+Δ is carried forward at its last quote, with the dropout count reported per arm. The ladder is never renormalised.
  - `late` rows are counted per source beside the frozen lag, and each source needs a minimum number of uncensored samples (OPEN-5) before its 14-day freeze counts.
- **F13-R27 (archive module; arch BLOCK-1).** `US_SOURCE_PRODUCTS` and the four new request factories live in a NEW module, `src/breezy/persistence/us_source_request.py`, which constructs `ArchiveRequest`. They are re-exported via `archive_request.py`. `archive_cache.py` is byte-unchanged, and its EDIT row is deleted.
- **F13-R28 (revision compare; arch BLOCK-2).**
  - Compare the fetched sha256 against the set of digests of ALL stored revisions for `(source, run_ts)`. Append only if the digest is absent from that set.
  - N = 1 + the highest existing revision, computed under the source's unit-level flock.
  - The write goes through `ArchiveCache(fetch=<closure returning the already-fetched bytes>).get_or_fetch` on a key verified `missing()` (the only write API). `get_or_fetch` is the write path, never the comparison; rename the test accordingly.
  - `window_end = run_ts + 1 ns`. The first-seen revision is `-r0` (the `-r<N>` suffix is accepted by `ArchiveRequest`, verified).
  - Test: `test_identical_repoll_after_revision_appends_nothing`.
- **F13-R29 (floor vs lag, NBP poll; arch BLOCK-3/4, nits).**
  - `MINIMUM_PUBLICATION_LAG_NS` is a sanity floor only, never the backtest lag. Rows with no observed time take basis `nominal_plus_conservative_lag`, with the prereg conservative lag (GFS MOS ≥ 5 h, LAMP ≥ 60 min). That lag must be ≥ the floor and ≥ the C1-measured maximum where one exists.
  - LAMP and PFM get no key in `MINIMUM_PUBLICATION_LAG_NS`; their floor lives in the prereg A0 table. Test: `test_unmeasured_row_uses_conservative_lag_not_minimum_floor`.
  - The NBP observation calls the unmodified `fetch_nbp_bulletin`. Polling stops for a cycle after its first success. `host_tag` = `result.source_host`, and the basis is `measured_header@s3|nomads` from `last_modified`. The `stations` constructor argument includes KNYC, and the module default is not edited.
  - B0's vintage check reads the node catalog's `ForecastPoint` rows for `NBM_NBP`.
  - `TRANSPORT_ERROR_CONSTRUCTORS` lives in the contract test (`:65`). Parser refusal classes never subclass `CliParseError` or `CliSanityError`.
  - The KNYC widening updates any pinned 4-tuple test as a WIDENED row, never relaxing it.

Next: a confirmation-only round 4 on r3 + r3.1 (the same three reviewers, checking only R22..R29 and regressions). READY on all three marks F13 READY and opens the F13-C1 queue row.

## r3.2 amendments: round-4 rulings F13-R30..R33 (coordinator, 2026-10-06). BINDING over r3 and r3.1.

Round 4 results: stats READY (with nits), security NOT-READY (2), architecture NOT-READY (2). Each fix text below is adopted verbatim.

- **F13-R30 (M6 baseline digest; security).** A baseline entry exempts a file only while its current sha256 equals the recorded digest. A path-listed file with a differing digest is scanned like a new file.
  - Files in the C1 transitive closure, including `http.py`, `probe_transport.py` and `iem_mos_probe_transport.py`, are scanned regardless of baseline membership.
  - `test_m6_baseline_excludes_c1_closure` asserts that no closure file is exempted. `test_m6_modified_baseline_file_is_rescanned` asserts the digest rule.
- **F13-R31 (H5 probe credentials; security). Replaces R23(a).** (a) Credential files and credential env names are absent: `~/.config/breezy` contains no entry other than the read-only `alerts.env`, and `ls` of it shows exactly that one file.
  - The collector reads `alerts.env` as a file, because `--clearenv` strips `EnvironmentFile`.
  - `user_agent=` is passed explicitly for the same reason.
- **F13-R32 (revision scope; architecture).** The digest set is `{e.sha256}` over `entries(source)`, filtered to `station == S`, `window_start == run_ts`, and base product P with an `-r\d+` suffix. Only raw-payload entries count.
  - Normalised CSVs are stored under a distinct product and are excluded.
  - N is computed over the same filter.
  - The unit flock is never `<source>/coverage.json.lock`, which `_commit_miss` takes with `LOCK_NB`.
  - Parse and UTF-8 checks run before the `get_or_fetch` write, so a refused payload never leaves an orphan.
  - When `last_modified` is None, the basis falls back to `first_seen`.
- **F13-R33 (KNYC; architecture). Supersedes the R29 KNYC clause.** Leave `IEM_MOS_STATION_ORDER` unchanged. Widen only `IEM_MOS_STATIONS`, and have backfill and AFOS/LAV validate against the set.
  - KNYC runs only when named in an explicit `--stations`, so the nightly `asos-refresh-run.sh` default stays four stations.
  - Test: `test_knyc_widening_leaves_default_station_order_unchanged`.
- **Stats round-4 nits (adopted).**
  - θ = the pinned `EVIDENCED_FEE_THETA` (`hypothesis_ledger.py:202`), read and never copied. The test asserts equality with that symbol. Any per-instrument θ comes from the `costs.py:133` resolver.
  - The 60 s STOP is evaluated on the primary-lag source's median time-to-50%-of-move. An untestable STOP is not FUTILE and falls through to the interval rule.
  - Holm test renamed to `test_holm_family_size_equals_b0_fixed_size_1_or_2_at_alpha_0_025`.
  - OPEN-5 adds the per-source minimum uncensored lag samples, the per-method byte caps and the `RuntimeMaxSec` margin.
- **F13-R34 (R33 addendum + R32 nits; architecture round 5).**
  - Retarget `test_mos_url_rejects_knyc` to an unlisted station: rename it `test_mos_url_rejects_unlisted_station`, use station `KJFK`, and keep the `ValueError` refusal. Add `test_mos_url_accepts_knyc`. This keeps the closed-set refusal; it is a widening, not a weakening.
  - Add an EDIT row for `scripts/archive/iem_mos_backfill.py` `:469/:498/:526` (tuple → `IEM_MOS_STATIONS`). `STATIONS` and the `--stations` default stay `IEM_MOS_STATION_ORDER`, asserted by `test_knyc_widening_leaves_default_station_order_unchanged`.
  - The unit lock is `<archive_root>/<source>/collector.lock`.
  - The product match is `fullmatch(rf"{re.escape(P)}-r\d+")`.
  - The `first_seen` fallback also applies to an unparsable `last_modified`.
  - The collector parses `alerts.env` with a small local reader and imports nothing from `breezy.runtime`; M6 enforces this.
  - The probe asserts the one-entry rule by listing `~/.config/breezy` under the profile.

**STATUS: READY (2026-10-06).** Round 5: security READY, architecture READY once the R34 addendum is applied, statistics READY in round 4. The binding plan is r3 + r3.1 + r3.2. The F13-C1 queue row is open.

## Post-READY build finding (coordinator, 2026-10-06)

- **F13-OPEN-7 (LAMP daily-max window).** Real HH30 `lavtxt` bulletins carry 25 hourly columns, and `lavtxt_ext` carries hours 26–38. So no single run covers a full 24-hour LST climate day, and the strict "all 24 hours" daily max (S3 `lamp_parse`) is MISSING for real runs. This affects the Phase A and B feature definition only; C1 still archives the raw bulletins, unchanged. Before Phase A1 is scored, the prereg must freeze the LAMP feature. The proposal is the max over the forecast hours remaining in the climate day after the anchor, using `lavtxt` + `lavtxt_ext`, plus an explicit hours-covered field. The observed max-so-far comes from the existing obs path, never from LAMP. The strict 24-hour max stays as is and is labelled diagnostic. This needs a review before Phase A; it does not block C1.

### F13-OPEN-7 ruling: F13-R35 (coordinator, 2026-10-06, after trading-bot-architect review). BINDING over the S3 strict-24 h definition for Phase A/B features.

- **F13-R35. LAMP feature definition.**
  - **Feature.** Phase A/B use `lamp_rem_max_f`. It is the max over `lavtxt` and `lavtxt_ext` forecast hours where `valid_ts` is after the anchor and the hour falls inside the LST climate day (`climate_day_for_txn`).
  - **Run selection.** Use the latest run whose `available_at` (frozen upper-bound lag) is before the anchor.
  - **Leakage.** Assert the run side (r3.1, `max(available_at) < anchor`) and the hour side (`min(valid_ts) > anchor`).
  - **Persisted fields.**
    - `hours_covered`.
    - `lamp_peak_covered`, true only when every hour from 12 to 18 LST that is after the anchor is present.
    - If `lamp_peak_covered` is false, the feature is MISSING: `m_lamp=1`, the LAMP term drops, and the row scores as M0′. Nothing is imputed.
  - **Blend input.** The blend uses `L = max(obs_so_far, lamp_rem_max_f)`.
    - `obs_so_far` comes only from the obs path, with obs `available_at` before the anchor. It never comes from LAMP.
    - At a D-1 anchor, `L = lamp_rem_max_f`.
    - Both raw parts are persisted. Obs-only and LAMP-only are descriptive arms.
  - **M0′ baseline.** M0′ also receives `obs_so_far`, so LAMP credit is not confused with observation credit. The ladder stays K=1.
  - **Diagnostics and reporting.** The strict 24 h max is diagnostic only. Missingness is reported per horizon (D0, D-1); differential missingness is an outcome.
  - **A0 probe item before the Phase A freeze.** Confirm which HH30 cycles publish `lavtxt_ext`. D-1 18Z peak coverage depends on it (EST day end is +35 h, PST +38 h, and ext reaches 38 h).
  - **Tests (Phase A builder, RED first).**
    - `test_lamp_rem_max_excludes_hours_at_or_before_anchor`
    - `test_lamp_rem_run_available_at_before_anchor_asserted`
    - `test_lamp_peak_coverage_d0_complete_dm1_requires_ext`
    - `test_lamp_peak_uncovered_sets_missing_indicator_no_imputation`
    - `test_combined_feature_is_max_obs_so_far_and_lamp_rem`
    - `test_dm1_anchor_obs_so_far_undefined_uses_lamp_only`
    - `test_obs_so_far_never_sourced_from_lamp`
    - `test_missing_lamp_row_scores_as_m0prime`
    - `test_lamp_missingness_reported_per_horizon`
    - `test_strict_24h_max_labelled_diagnostic`
  - **Review.** The Phase A prereg freeze review re-checks R35.

### B0 verdict: F13-R36 (coordinator, 2026-10-06, after prediction-market-reviewer decision support)

- **Evidence.** `docs/evidence/f13/b0_report_2026-10-06.json`; census and backfill reports are in the same directory.
  - PFM family only (size 1; NBP vintages absent, R26).
  - SD (hour-matched, placebo and pre-window arms): 6.86 °F per 60-min window. n_eff is 35 climate days.
  - MDE is **3.25 °F**, one-sided at α=0.025 with power 0.8. The excluding-dropout sensitivity gives 2.66 °F.
  - The 60 s cadence check RESOLVES (182/182 windows).
- **Pinned plausible effect: 0.5 °F**, an optimistic bound. A typical PFM revision to the day's max is about 1 °F RMS. Assuming 30–50% of it is news not already priced from NBM, LAMP or obs, the 60-min ladder move is about 0.3–0.5 °F.
- **Verdict: B1 = UNDERPOWERED** under the B0 rule (MDE > plausible slope, 6.5×). B1 and B2 are not run.
- **No outcome amendment.** These options were considered and rejected:
  - A mass-normalised mean contradicts R26 and leaves the SD at about 5–6 °F.
  - Ladder quantiles are quantised by the rung spacing.
- **Recorded, not scheduled: B0′.** The change in the mid of the rung containing the prior PFM max is a new estimand. It is legitimate only as a separately hash-frozen exploratory prereg with an n_eff target stated up front, and it never rewrites this verdict.
- **Consequence.** F13 value now rests on Phase A, the US-source blend vs CLI, offline. Phase A still needs ≥14 days of C1 measured lags (≈10-20) and the R35 LAMP feature.
