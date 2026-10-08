"""The ARCH Rev 9.2 section 4.7 envelope-test manifest (ARCH-0 seam A AC 27).

``ARCH_FREEZE_SHA256`` pins the frozen ``AUTONOMY_ARCHITECTURE.md``.
``test_envelope_manifest_equals_frozen_arch`` extracts every backticked ``test_*`` name from the
"New test" column of section 4.7, applies ``E11_RENAMES``, and requires the result to equal the
names in ``ENVELOPE_NODE_IDS`` plus ``ENVELOPE_PENDING_NAMES``, with no name in both.

* ``ENVELOPE_NODE_IDS``: the full node ids (literal params included) of the envelope tests that
  exist today. ``test_every_envelope_node_id_collected_and_unskipped`` requires each one to be
  collected by pytest and to carry no skip marker or skip call. An owner-carried stub
  (``xfail(strict=True, raises=OwnerPending)``) counts as unskipped.
* ``ENVELOPE_PENDING_NAMES``: names whose test has not landed. The same test requires that no test
  under ``tests/`` defines one of them, so a landing test cannot stay in this set. A seam that
  lands (or carries) an envelope test moves its name from here to ``ENVELOPE_NODE_IDS`` in the
  same commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = ["ARCH_FREEZE_SHA256", "E11_RENAMES", "ENVELOPE_NODE_IDS", "ENVELOPE_PENDING_NAMES"]

ARCH_FREEZE_SHA256: Final = "1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42"

#: Frozen ARCH name -> adopted name (errata E-11, SELF_HEAL realised natively by systemd).
E11_RENAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "test_self_heal_unit_allowlist_is_literal_and_excludes_trade": (
            "test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine"
        ),
        "test_self_heal_cap_survives_process_restart": (
            "test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all"
        ),
        "test_restart_window_resets_before_launch": (
            "test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical"
        ),
    }
)

ENVELOPE_NODE_IDS: Final[frozenset[str]] = frozenset(
    {
        "tests/unit/test_autonomy_node_detectors.py::test_alerts_undeliverable_reads_two_days",
        "tests/unit/test_autonomy_node_detectors.py::test_alerts_undeliverable_veto",
        "tests/unit/test_autonomy_cross_area.py::test_alpha_index_never_resets",
        "tests/unit/test_autonomy_cross_area.py::test_ambiguous_intent_cancels_swap_not_incumbent_launch",
        "tests/unit/test_autonomy_cross_area.py::test_attest_expiry_and_chain_staleness_veto_entries",
        "tests/unit/test_autonomy_cross_area.py::test_attest_requires_every_listed_detector",
        "tests/unit/test_autonomy_cross_area.py::test_attest_veto_armed_after_first_attest",
        "tests/unit/test_autonomy_cross_area.py::test_attest_veto_rearmed_only_after_post_swap_attest",
        "tests/unit/test_autonomy_cross_area.py::test_bad_demand_file_vetoes_venue[actor]",
        "tests/unit/test_autonomy_cross_area.py::test_calibration_leg_relative_inconclusive_below_min_buckets",
        "tests/unit/test_autonomy_cross_area.py::test_cause_verdict_ids_subset_of_acted_rows",
        "tests/unit/test_autonomy_cross_area.py::test_champion_own_artefact_mismatch_at_load_is_integrity",
        "tests/unit/test_autonomy_cross_area.py::test_child_env_drops_inbound_registry_keys",
        "tests/unit/test_autonomy_cross_area.py::test_child_env_touches_only_registry_keys",
        "tests/unit/test_autonomy_cross_area.py::test_compose_refuses_without_entry_veto_slot",
        "tests/unit/test_alert_outbox_concurrency.py::test_concurrent_drainers_send_at_most_once_per_claim_window",
        "tests/unit/test_alert_delivery.py::test_critical_alerts_use_delivery_proof",
        "tests/unit/test_alert_delivery.py::test_critical_survives_sigkill",
        "tests/unit/test_autonomy_cross_area.py::test_decision_id_unique_per_take",
        "tests/unit/test_alert_delivery.py::test_deliver_with_proof_reports_non_2xx_through_tee",
        "tests/unit/test_autonomy_cross_area.py::test_demotion_latency_slo",
        "tests/unit/test_autonomy_cross_area.py::test_demotion_never_requires_policy_and_is_immediate[engine]",
        "tests/unit/test_alert_delivery.py::test_detector_and_failure_mode_alerts_use_delivery_proof",
        "tests/unit/test_autonomy_cross_area.py::test_detectors_and_drawdown_include_drill_fills[detectors]",
        "tests/unit/test_autonomy_cross_area.py::test_detectors_and_drawdown_include_drill_fills[drawdown]",
        "tests/unit/test_autonomy_cross_area.py::test_drawdown_producer_handshake_with_labels",
        "tests/unit/test_autonomy_cross_area.py::test_drill_fills_excluded_from_n_and_kill_clock",
        "tests/unit/test_autonomy_cross_area.py::test_drill_fills_spend_venue_budget",
        "tests/unit/test_autonomy_cross_area.py::test_drill_halt_never_freezes_or_writes_exec_store[exec_store]",
        "tests/unit/test_autonomy_cross_area.py::test_drill_inject_mapped_only_in_clause",
        "tests/unit/test_autonomy_cross_area.py::test_drill_inject_passes_when_marker_absent",
        "tests/unit/test_autonomy_cross_area.py::test_drill_marker_read_error_never_resumes",
        "tests/unit/test_autonomy_cross_area.py::test_drill_rollback_to_superseded_incumbent_admitted",
        "tests/unit/test_autonomy_cross_area.py::test_drill_timeline_matches_aut7_sequence",
        "tests/unit/test_autonomy_cross_area.py::test_engine_heartbeat_stale_vetoes",
        "tests/unit/test_autonomy_cross_area.py::test_entry_guard_cache_invalidated_on_fill",
        "tests/unit/test_autonomy_cross_area.py::test_entry_guard_exact_key_reads_only",
        "tests/unit/test_autonomy_cross_area.py::test_entry_veto_closed_before_first_tick_and_on_stale_tick",
        "tests/unit/test_autonomy_cross_area.py::test_every_exit_fill_joins",
        "tests/unit/test_autonomy_cross_area.py::test_every_live_verdict_journaled_once_per_daily_pass",
        "tests/unit/test_autonomy_cross_area.py::test_failed_rollback_halts_champion",
        "tests/unit/test_autonomy_cross_area.py::test_family_source_fixed_in_unit",
        "tests/unit/test_autonomy_cross_area.py::test_halted_family_boots_entries_vetoed_exits_live",
        "tests/unit/test_autonomy_cross_area.py::test_hand_relaunch_without_registry_source_refused",
        "tests/unit/test_autonomy_cross_area.py::test_health_memory_sum_within_memavailable",
        "tests/unit/test_autonomy_cross_area.py::test_hwm_reset_cannot_unhalt",
        "tests/unit/test_autonomy_cross_area.py::test_hwm_reset_cli_journals_alerts_and_chains",
        "tests/unit/test_autonomy_cross_area.py::test_hwm_reset_never_refunds_counters",
        "tests/unit/test_autonomy_cross_area.py::test_incumbent_boot_survives_child_ambiguous_intent",
        "tests/unit/test_autonomy_cross_area.py::test_infeasible_nomination_charges_no_alpha[store]",
        "tests/unit/test_autonomy_cross_area.py::test_infeasible_nomination_charges_no_alpha[verdict]",
        "tests/unit/test_autonomy_cross_area.py::test_intraday_engine_is_restrictive_only[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_intraday_pass_yields_to_prelaunch_lock",
        "tests/unit/test_autonomy_cross_area.py::test_mirror_read_failure_is_integrity",
        "tests/unit/test_autonomy_cross_area.py::test_no_policy_fail_demotes_never_widens",
        "tests/unit/test_autonomy_cross_area.py::test_node_loads_artefact_from_store_by_row_sha",
        "tests/unit/test_autonomy_cross_area.py::test_node_relaunch_rule_family_id_and_seq_prefix[node]",
        "tests/unit/test_autonomy_cross_area.py::test_nomination_columns_required_and_read_by_k_check[k_check]",
        "tests/unit/test_autonomy_cross_area.py::test_nomination_refused_past_k_max_lifetime",
        "tests/unit/test_autonomy_cross_area.py::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec",
        "tests/unit/test_autonomy_cross_area.py::test_own_outcome_effect_not_vacuous",
        "tests/unit/test_autonomy_cross_area.py::test_own_outcome_refused_below_min_gate_decisions",
        "tests/unit/test_autonomy_cross_area.py::test_p_at_decision_is_bought_leg_probability",
        "tests/unit/test_autonomy_cross_area.py::test_pending_write_uses_intraday_reconciliation[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_policy_block_not_looser_than_code_ceilings",
        "tests/unit/test_autonomy_cross_area.py::test_post_launch_swap_cancel_restores_incumbent[supervisor]",
        "tests/unit/test_autonomy_cross_area.py::test_poststop_venue_read_is_get_only",
        "tests/unit/test_autonomy_cross_area.py::test_prelaunch_requires_post_stop_reconciliation",
        "tests/unit/test_autonomy_cross_area.py::test_prelaunch_writes_rollback_and_activate_atomically[prelaunch]",
        "tests/unit/test_autonomy_cross_area.py::test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]",
        "tests/unit/test_autonomy_cross_area.py::test_producer_demand_write_is_restrictive_only[aut6_producer_ast]",
        "tests/unit/test_autonomy_cross_area.py::test_promote_disabled_when_eta_after_kill",
        "tests/unit/test_autonomy_cross_area.py::test_promotion_requires_reconciled_state",
        "tests/unit/test_autonomy_cross_area.py::test_reconciliation_and_entry_guard_never_read_canary_store[adapter_reader]",
        "tests/unit/test_autonomy_cross_area.py::test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]",
        "tests/unit/test_autonomy_cross_area.py::test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]",
        "tests/unit/test_autonomy_cross_area.py::test_registry_shadow_logs_agreement_and_spawns_env_family",
        "tests/unit/test_autonomy_cross_area.py::test_registry_unavailable_mints_no_permit",
        "tests/unit/test_autonomy_cross_area.py::test_registry_unreadable_veto_clears_only_after_verified_read",
        "tests/unit/test_autonomy_cross_area.py::test_registry_veto_leaves_exit_seam_open",
        "tests/unit/test_autonomy_cross_area.py::test_relaunch_request_schema_exact_set",
        "tests/unit/test_autonomy_cross_area.py::test_repeat_supersede_same_family_is_not_replay[store]",
        "tests/unit/test_autonomy_cross_area.py::test_resolver_resolves_after_hwm_reset",
        "tests/unit/test_autonomy_cross_area.py::test_restrictive_commit_failure_sets_node_veto",
        "tests/unit/test_autonomy_cross_area.py::test_resume_clears_registry_halted_without_relaunch",
        "tests/unit/test_autonomy_cross_area.py::test_resume_written_only_at_prelaunch[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_retired_demand_file_archived",
        "tests/unit/test_autonomy_cross_area.py::test_retired_kind_keeps_scorer_until_last_fill_labelled",
        "tests/unit/test_autonomy_cross_area.py::test_rollback_fee_check_uses_verdict_not_node_memory",
        "tests/unit/test_autonomy_cross_area.py::test_rollback_restores_byte_identical_artefact",
        "tests/unit/test_autonomy_cross_area.py::test_root_admit_only_when_venue_has_no_sender[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_root_admit_refused_after_operator_halt_within_cooldown",
        "tests/unit/test_autonomy_cross_area.py::test_root_admit_refused_on_stale_halt_mirror",
        "tests/unit/test_autonomy_cross_area.py::test_root_admit_requires_own_allowlist_triple[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_scorer_never_attributes_by_trial_id_prefix",
        "tests/unit/test_autonomy_cross_area.py::test_shadow_never_vetoes_or_arms_hand_relaunch_rule",
        "tests/unit/test_autonomy_cross_area.py::test_swap_cannot_exceed_daily_budget_across_namespaces",
        "tests/unit/test_autonomy_cross_area.py::test_target_byte_mismatch_ineligible_without_freeze[selection]",
        "tests/unit/test_autonomy_cross_area.py::test_target_manifest_mismatch_marks_ineligible",
        "tests/unit/test_autonomy_cross_area.py::test_transient_veto_writes_no_transition",
        "tests/unit/test_autonomy_cross_area.py::test_try_submit_latency_independent_of_webhook_latency",
        "tests/unit/test_autonomy_cross_area.py::test_two_intraday_passes_inside_launch_window",
        "tests/unit/test_autonomy_cross_area.py::test_two_pending_nominees_get_distinct_k",
        "tests/unit/test_autonomy_cross_area.py::test_verdict_acceptance_rules",
        "tests/unit/test_autonomy_cross_area.py::test_verdict_accepted_after_attest",
        "tests/unit/test_autonomy_cross_area.py::test_verdict_subject_sha_must_match_row",
        "tests/unit/test_autonomy_cross_area.py::test_verdict_validity_ceiling[engine]",
        "tests/unit/test_autonomy_cross_area.py::test_verify_and_load_share_bytes[loader]",
        "tests/unit/test_autonomy_cross_area.py::test_voided_pair_fills_excluded_from_all_n",
        "tests/unit/test_autonomy_cross_area.py::test_watch_actor_never_reads_projection",
        "tests/unit/test_autonomy_cross_area.py::test_watch_actor_store_touches_stay_on_loop_thread",
        "tests/unit/test_autonomy_cross_area.py::test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical",
        "tests/unit/test_autonomy_cross_area.py::test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all",
        "tests/unit/test_autonomy_cross_area.py::test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine",
        "tests/unit/test_autonomy_cross_area.py::test_window_cap_below_n_min_is_inconclusive",
        "tests/unit/test_autonomy_demand.py::test_bad_demand_file_vetoes_venue[reader]",
        "tests/unit/test_autonomy_demand.py::test_producer_demand_flood_cannot_exhaust_integrity_slot",
        "tests/unit/test_autonomy_demand.py::test_producer_demand_write_is_restrictive_only[writer_api]",
        "tests/unit/test_autonomy_envelope.py::test_autonomy_alert_egress_not_widened",
        "tests/unit/test_autonomy_envelope.py::test_autonomy_never_imports_order_path",
        "tests/unit/test_autonomy_envelope.py::test_autonomy_never_reads_or_writes_operator_controls",
        "tests/unit/test_autonomy_envelope.py::test_autonomy_never_touches_enablement_permit_or_firewall",
        "tests/unit/test_autonomy_envelope.py::test_autonomy_payload_hygiene_scan",
        "tests/unit/test_autonomy_files_one_writer.py::test_autonomy_files_have_one_writer",
        "tests/unit/test_autonomy_pins.py::test_attest_cadence_has_no_expiry_gap[pins_invariant]",
        "tests/unit/test_autonomy_pins.py::test_code_identity_pins_cover_import_closure",
        "tests/unit/test_autonomy_pins.py::test_damping_ceilings[ceilings]",
        "tests/unit/test_autonomy_pins.py::test_engine_pin_history_retained",
        "tests/unit/test_autonomy_pins.py::test_halt_reason_class_map_is_exact",
        "tests/unit/test_autonomy_pins.py::test_request_ttl_covers_two_schedule_polls",
        "tests/unit/test_autonomy_pins.py::test_rollback_dwell_age_and_drill_headroom_ceilings",
        "tests/unit/test_autonomy_plugins.py::test_capture_untagged_is_a_veto_reason",
        "tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set",
        "tests/unit/test_autonomy_verdict.py::test_differing_body_same_id_refused",
        "tests/unit/test_entry_guard.py::test_entry_guard_unreadable_index_vetoes",
        "tests/unit/test_entry_guard.py::test_rung_net_position_veto_crosses_legs_and_families[double]",
        "tests/unit/test_lineage_policy_allowlist.py::test_lineage_policy_allowlist_is_literal_only",
        "tests/unit/test_registry_fold_effects.py::test_demote_during_pending_swap_incoming",
        "tests/unit/test_registry_fold_effects.py::test_demote_during_pending_swap_outgoing",
        "tests/unit/test_registry_fold_effects.py::test_drill_flag_spans_promote_to_rollback",
        "tests/unit/test_registry_fold_effects.py::test_infra_cause_never_retires",
        "tests/unit/test_registry_fold_effects.py::test_post_launch_swap_cancel_restores_incumbent[fold]",
        "tests/unit/test_registry_fold_effects.py::test_rollback_failed_never_freezes_venue",
        "tests/unit/test_registry_fold_effects.py::test_terminal_halt_freezes_lineage",
        "tests/unit/test_registry_fold_effects.py::test_unactivated_pair_lapses_at_launch",
        "tests/unit/test_registry_fold_tallies.py::test_drill_admit_charges_only_drill_budget",
        "tests/unit/test_registry_fold_validate.py::test_drill_budget_separate",
        "tests/unit/test_registry_fold_validate_rulings.py::test_family_artefact_binding_immutable",
        "tests/unit/test_registry_fold_validate.py::test_drill_demote_and_halt_counters_capped[drill_admits]",
        "tests/unit/test_registry_fold_validate.py::test_drill_demote_and_halt_counters_capped[drill_demotes]",
        "tests/unit/test_registry_fold_validate.py::test_drill_demote_and_halt_counters_capped[drill_halts]",
        "tests/unit/test_registry_fold_validate.py::test_drill_demote_and_halt_counters_capped[drill_promotes]",
        "tests/unit/test_registry_fold_validate.py::test_drill_promote_refuses_non_champion_sha[admit]",
        "tests/unit/test_registry_fold_validate.py::test_drill_promote_refuses_non_champion_sha[promote]",
        "tests/unit/test_registry_fold_validate.py::test_drill_refused_over_halted_incumbent[admit]",
        "tests/unit/test_registry_fold_validate.py::test_drill_refused_over_halted_incumbent[promote]",
        "tests/unit/test_registry_fold_validate_resume.py::test_drill_resume_never_charges_model_budget",
        "tests/unit/test_registry_fold_validate_resume.py::test_resume_refused_while_swap_pending",
        "tests/unit/test_registry_fold_validate_resume.py::test_resume_requires_every_cause_cleared",
        "tests/unit/test_registry_export.py::test_registry_readonly_open_engine_stopped",
        "tests/unit/test_registry_hwm.py::test_autonomy_exec_keys_disjoint_from_halt_prefixes",
        "tests/unit/test_registry_hwm.py::test_registry_hwm_refuses_regression",
        "tests/unit/test_registry_store.py::test_registry_cas_and_idempotent_replay",
        "tests/unit/test_registry_store.py::test_registry_hash_chain_and_triggers",
        "tests/unit/test_registry_store.py::test_registry_transition_table_is_exact",
        "tests/unit/test_registry_store_wiring.py::test_bootstrap_seed_genesis_only",
        "tests/unit/test_registry_resolver.py::test_family_source_registry_requires_bootstrap",
        "tests/unit/test_registry_resolver.py::test_node_relaunch_rule_family_id_and_seq_prefix[resolver]",
        "tests/unit/test_registry_resolver_child.py::test_child_d0_and_trial_prefix_pinned[resolver]",
        "tests/unit/test_registry_resolver_child.py::test_child_manifest_equals_committed_root_except_allowlist",
        "tests/unit/test_registry_resolver_guards.py::test_exit_gate_stays_code_only",
        "tests/unit/test_registry_resolver_bytes.py::test_registry_paths_refuse_symlinks",
        "tests/unit/test_registry_resolver_bytes.py::test_resolver_binds_bytes_to_row",
        "tests/unit/test_registry_resolver_child.py::test_resume_not_subject_to_d0_rule",
        "tests/unit/test_registry_resolver_child.py::test_rollback_to_earlier_child_passes_d0_rule",
        "tests/unit/test_registry_resolver_bytes.py::test_rollback_to_root_reads_content_addressed_copy",
        "tests/unit/test_registry_resolver_bytes.py::test_root_admit_requires_own_allowlist_triple[resolver]",
        "tests/unit/test_registry_resolver_bytes.py::test_root_resolves_under_live_orders_allowlist",
        "tests/unit/test_registry_resolver_bytes.py::test_verify_and_load_share_bytes[resolver]",
        "tests/unit/test_registry_validate_ii.py::test_damping_ceilings[counting_rule]",
        "tests/unit/test_registry_validate_ii.py::test_mint_unlimited_by_k_max_but_one_per_day",
        "tests/unit/test_registry_validate_ii.py::test_root_admit_only_when_venue_has_no_sender[validate]",
        "tests/unit/test_registry_validate_store.py::test_child_d0_and_trial_prefix_pinned[store]",
        "tests/unit/test_launch_window_table.py::test_launch_path_units_end_before_next_fixed_point[existing_units]",
        "tests/unit/test_launch_window_table.py::test_no_unit_overlaps_launch_window[existing_units]",
    }
)

ENVELOPE_PENDING_NAMES: Final[frozenset[str]] = frozenset(
    {
        "test_candidate_cap_and_mint_rate",
    }
)
