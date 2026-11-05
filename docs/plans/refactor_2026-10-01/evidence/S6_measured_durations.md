# MEASURED timed gate run 2026-10-01 (worktree HEAD 60290e9d, scripts/ci/run_tests_no_egress.sh --durations=80 --durations-min=0.5)
wall 25m03s, CPU 21m52s, peak 2.4 GB, GATE_EXIT=0 (systemd unit breezy-gate-refactor-dur)
top-80 durations sum = 1,062 s of ~1,503 s wall (~71%)

## per-file sum of top-80 entries (seconds)
   322.9 tests/unit/test_aud07_m1c_census.py
   260.0 tests/unit/test_current_rung_hold_exit_window_study.py
    82.1 tests/unit/test_aud07_live_rule_crossing_sim.py
    40.5 tests/unit/test_nbp_calibration.py
    28.0 tests/unit/test_quote_tape_ingest_bounded_rss.py
    24.1 tests/unit/test_archive_table_upper_bound_2026_09_14.py
    23.5 tests/unit/test_current_rung_hold_archive_table.py
    22.4 tests/unit/test_polymarket_us_readonly_guard.py
    22.2 tests/unit/test_execution_egress_firewall_guard.py
    21.1 tests/unit/test_mypy_ratchet.py
    19.7 tests/unit/test_forecast_conditional_model_study.py
    18.5 tests/unit/test_no_side_ldobf_validation_2026_09_14.py
    15.9 tests/unit/test_nbp_skill_study.py
    13.1 tests/unit/test_polymarket_us_credential_gate.py
    12.2 tests/unit/test_multi_position_validation_2026_09_14.py
    10.1 tests/unit/test_replay_daily_wrapper.py
    10.0 tests/unit/test_polymarket_us_instrument_cache_alert.py
    10.0 tests/unit/test_operator_control_assignment_scan.py
    10.0 tests/contract/test_trade_node_lifecycle_contract.py
    10.0 tests/contract/test_boot_halt_alert_contract.py
     9.5 tests/unit/test_gs_boundary_artefact.py
     9.3 tests/unit/test_crh_group_sequential_boundaries.py
     8.0 tests/unit/test_polymarket_us_permit_issuance.py
     6.7 tests/unit/test_census_column_scan_memory.py
     6.1 tests/unit/test_family_tally_v2.py
     3.9 tests/unit/test_fd_hygiene_guard.py
     3.9 tests/unit/test_cage_rule_constants_are_pinned.py
     3.5 tests/unit/test_extend_dedupe_filtered.py
     3.2 tests/unit/test_probe_containment.py
     3.1 tests/unit/test_no_native_read_spies.py
     2.9 tests/unit/test_strategy_module_gate.py
     2.8 tests/unit/test_polymarket_us_write_transport.py
     2.8 tests/unit/test_nbm_quantile_actor.py
     2.8 tests/unit/test_aud07_m1c_orchestration.py
     2.6 tests/unit/test_archive_cache.py
     2.5 tests/unit/test_replay_census_memory_bound.py
     2.5 tests/unit/test_polymarket_us_capital_flow_pull.py
     2.5 tests/unit/test_nbm_forecast_actor.py
     2.3 tests/unit/test_decision_funnel_daily_digest.py
     2.1 tests/unit/test_polymarket_us_fee_guard.py
     2.1 tests/unit/test_iem_asos1min_backfill.py

## raw top 80
============================= slowest 80 durations =============================
120.03s call     tests/unit/test_aud07_m1c_census.py::test_chunked_census_plus_derive_pin_equals_the_all_in_one_result
65.01s call     tests/unit/test_current_rung_hold_exit_window_study.py::TestAud04V1FallsBackToTotalLevel::test_main_dispatches_to_the_total_level_path_when_trial_rows_is_none
65.01s call     tests/unit/test_current_rung_hold_exit_window_study.py::TestAud04V1FallsBackToTotalLevel::test_main_dispatches_to_the_per_trial_path_when_trial_rows_is_present
65.01s call     tests/unit/test_current_rung_hold_exit_window_study.py::test_main_degrades_to_skipped_on_a_corrupt_aud04_artefact_and_still_writes_output
65.01s call     tests/unit/test_current_rung_hold_exit_window_study.py::test_main_degrades_to_skipped_on_a_malformed_aud04_artefact_and_still_writes_output
64.10s call     tests/unit/test_aud07_m1c_census.py::test_derive_pin_refuses_missing_cells
62.54s call     tests/unit/test_aud07_m1c_census.py::test_derive_pin_refuses_missing_stress_row
59.29s call     tests/unit/test_aud07_m1c_census.py::test_derive_pin_refuses_mixed_code_shas
40.52s call     tests/unit/test_nbp_calibration.py::test_skew_normal_cdf_gives_a_different_kappa_curve_than_normal
28.22s call     tests/unit/test_aud07_live_rule_crossing_sim.py::test_refined_run_equals_the_fine_grid_run_field_for_field_and_exercises_both_paths
27.60s call     tests/unit/test_aud07_live_rule_crossing_sim.py::test_the_all_yes_qty1_control_passes_the_m2_gate_under_the_live_rule
26.29s call     tests/unit/test_aud07_live_rule_crossing_sim.py::test_the_sim_null_has_mean_s_near_zero_and_unit_var_s_on_mixed_days
24.08s call     tests/unit/test_archive_table_upper_bound_2026_09_14.py::test_regenerating_the_frozen_table_upper_bound_is_byte_identical_modulo_timestamp
23.53s call     tests/unit/test_current_rung_hold_archive_table.py::test_regenerating_the_frozen_table_is_byte_identical_modulo_timestamp
21.12s setup    tests/unit/test_mypy_ratchet.py::test_mypy_stays_within_the_cf12_clean_set_and_ceilings
15.94s call     tests/unit/test_nbp_skill_study.py::test_default_stage_is_validate_and_never_needs_authorization
15.89s setup    tests/unit/test_quote_tape_ingest_bounded_rss.py::test_control_scales_far_faster_than_the_coalesced_treatment
12.14s call     tests/unit/test_quote_tape_ingest_bounded_rss.py::test_control_scales_far_faster_than_the_coalesced_treatment
10.02s call     tests/contract/test_trade_node_lifecycle_contract.py::test_the_trade_node_reaches_running_and_stops_cleanly
10.02s call     tests/contract/test_boot_halt_alert_contract.py::test_a_real_node_that_reaches_running_then_sigterm_emits_no_boot_halt_alert
9.52s call     tests/unit/test_gs_boundary_artefact.py::test_solver_reproduces_the_16_row_reference_fixture_to_1e_9
9.28s call     tests/unit/test_crh_group_sequential_boundaries.py::test_boundary_for_on_equal_t_grid_reproduces_reference_table_to_1e_minus_6
8.55s call     tests/unit/test_polymarket_us_readonly_guard.py::test_b9_post_order_and_clear_submit_intent_have_exactly_one_caller_each
6.73s call     tests/unit/test_census_column_scan_memory.py::TestNewPathDeltaRssDoesNotScaleWithFileCount::test_d1_vs_d4_at_20k_rows_per_day
6.69s call     tests/unit/test_execution_egress_firewall_guard.py::test_n2_an_attested_session_lives_or_dies_by_the_real_canary
6.69s call     tests/unit/test_aud07_m1c_census.py::test_stress_set_covers_t1_in_half_min_observed_to_0_15_and_dt_down_to_1e_4
6.46s call     tests/unit/test_no_side_ldobf_validation_2026_09_14.py::test_var_s_per_look_is_approximately_one[4]
6.13s call     tests/unit/test_family_tally_v2.py::test_the_multi_station_tally_matches_the_uncombined_score_reference
6.09s call     tests/unit/test_execution_egress_firewall_guard.py::test_n2_an_unattested_session_aborts_before_collection
5.55s call     tests/unit/test_aud07_m1c_census.py::test_stress_chunk_resume_skips_when_already_done
5.40s call     tests/unit/test_forecast_conditional_model_study.py::test_the_same_corpus_renders_a_byte_identical_artefact
5.39s call     tests/unit/test_polymarket_us_readonly_guard.py::test_b11_issue_has_exactly_one_production_caller_plus_alias_resolved_test_sites
5.35s call     tests/unit/test_no_side_ldobf_validation_2026_09_14.py::test_var_s_per_look_is_approximately_one[3]
5.04s call     tests/unit/test_replay_daily_wrapper.py::test_lock_contention_exits_zero_and_records_a_skip
5.04s call     tests/unit/test_replay_daily_wrapper.py::test_a_crashing_skip_recorder_exits_nonzero_on_lock_contention
5.03s call     tests/unit/test_operator_control_assignment_scan.py::test_the_scan_still_fires_on_the_shipped_tree_if_the_exemption_is_removed
5.02s call     tests/unit/test_polymarket_us_instrument_cache_alert.py::test_an_instrument_that_never_reaches_the_cache_still_alerts
5.00s call     tests/unit/test_polymarket_us_instrument_cache_alert.py::test_waiting_for_the_engine_is_bounded_and_does_not_hang
4.99s call     tests/unit/test_operator_control_assignment_scan.py::test_no_repo_file_assigns_an_operator_reserved_control
4.72s call     tests/unit/test_aud07_m1c_census.py::test_run_census_cell_buckets_deltas_by_depth_and_a_terminal_bucket
4.47s call     tests/unit/test_polymarket_us_credential_gate.py::test_credentials_are_scrubbed_from_an_ordinary_test_inside_an_exempt_session
4.36s call     tests/unit/test_polymarket_us_credential_gate.py::test_the_exemption_notice_names_variables_but_never_values
4.25s call     tests/unit/test_polymarket_us_credential_gate.py::test_all_three_unlocks_allow_the_session_to_start
3.94s call     tests/unit/test_multi_position_validation_2026_09_14.py::test_the_mechanism_verdict_is_computed_not_eyeballed
3.91s call     tests/unit/test_cage_rule_constants_are_pinned.py::test_p1_no_module_rebinds_a_pinned_constant_anywhere_in_the_repo
3.85s call     tests/unit/test_fd_hygiene_guard.py::test_stop_if_still_open_bounds_fd_growth_across_start_without_stop_cycles
3.57s call     tests/unit/test_forecast_conditional_model_study.py::test_the_ladder_reports_every_model_and_a_skill_score
3.48s call     tests/unit/test_extend_dedupe_filtered.py::test_filtered_extend_dedupe_rss_does_not_scale_with_other_instruments
3.38s call     tests/unit/test_no_side_ldobf_validation_2026_09_14.py::test_var_s_per_look_is_approximately_one[2]
3.28s call     tests/unit/test_no_side_ldobf_validation_2026_09_14.py::test_under_the_real_selection_rule_var_s_is_approximately_one
3.25s call     tests/unit/test_probe_containment.py::test_the_probe_live_modules_collect_to_zero_under_default_addopts
3.18s call     tests/unit/test_multi_position_validation_2026_09_14.py::test_under_h0_the_combined_statistic_has_unit_variance
3.13s call     tests/unit/test_no_native_read_spies.py::test_no_unallowlisted_native_read_spy_exists_in_the_suite
2.99s call     tests/unit/test_multi_position_validation_2026_09_14.py::test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha
2.96s call     tests/unit/test_polymarket_us_readonly_guard.py::test_sdk_signing_module_is_imported_only_by_the_named_oracle_test
2.92s call     tests/unit/test_strategy_module_gate.py::test_a_brand_new_strategy_module_typechecks_with_no_pyproject_edit
2.85s call     tests/unit/test_polymarket_us_permit_issuance.py::test_the_permit_is_constructed_only_by_its_issuer_and_this_suite
2.84s call     tests/unit/test_polymarket_us_readonly_guard.py::test_get_value_never_appears_inside_an_assert_statement
2.83s call     tests/unit/test_aud07_m1c_orchestration.py::test_cell_sh_cal_b_dispatches_to_the_census_per_cell_cli_and_validates_its_args
2.81s call     tests/unit/test_nbm_quantile_actor.py::test_no_sl11_module_is_an_execution_egress_surface
2.76s call     tests/unit/test_polymarket_us_write_transport.py::test_build_post_only_callable_has_exactly_one_caller
2.74s call     tests/unit/test_forecast_conditional_model_study.py::test_the_rung_family_does_not_report_a_climatology_comparison
2.74s call     tests/unit/test_forecast_conditional_model_study.py::test_the_calibration_leg_is_evaluated_not_merely_computed
2.70s call     tests/unit/test_polymarket_us_readonly_guard.py::test_d3_the_post_only_callable_has_exactly_one_caller
2.67s call     tests/unit/test_polymarket_us_permit_issuance.py::test_the_capability_is_constructed_only_by_the_chokepoint_and_this_suite
2.66s call     tests/unit/test_forecast_conditional_model_study.py::test_the_artefact_carries_source_archive_digests_and_code_provenance
2.62s call     tests/unit/test_forecast_conditional_model_study.py::test_the_artefact_records_the_declared_feature_set_and_the_cadence
2.59s call     tests/unit/test_archive_cache.py::test_find_execution_egress_modules_is_unchanged_by_this_item
2.54s call     tests/unit/test_replay_census_memory_bound.py::test_warm_cache_work_is_independent_of_instance_count
2.52s call     tests/unit/test_polymarket_us_permit_issuance.py::test_the_constructor_scan_is_not_vacuous
2.51s call     tests/unit/test_polymarket_us_capital_flow_pull.py::test_not_an_execution_egress_module
2.47s call     tests/unit/test_execution_egress_firewall_guard.py::test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules
2.46s call     tests/unit/test_nbm_forecast_actor.py::test_no_wp12_module_is_an_execution_egress_surface
2.44s call     tests/unit/test_execution_egress_firewall_guard.py::test_n2_no_execution_egress_module_may_exist_without_a_proven_firewall
2.38s call     tests/unit/test_execution_egress_firewall_guard.py::test_iem_mos_probe_transport_is_not_an_execution_egress_module
2.33s call     tests/unit/test_decision_funnel_daily_digest.py::test_digest_streams_bounded_memory
2.15s call     tests/unit/test_execution_egress_firewall_guard.py::test_x1_no_shipped_test_imports_the_exec_package_under_a_socket_marker
2.11s call     tests/unit/test_multi_position_validation_2026_09_14.py::test_the_crossing_rate_is_reported_per_qty_envelope
2.11s call     tests/unit/test_iem_asos1min_backfill.py::test_no_more_than_one_station_year_payload_is_held_at_a_time
2.10s call     tests/unit/test_polymarket_us_fee_guard.py::test_the_repository_still_has_no_unguarded_fee_reads
GATE_EXIT=0
