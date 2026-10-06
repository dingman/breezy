"""The owner-placeholder ledger (ARCH-0 seam A AC 27; AUT-5 r7 owner-RED ledger).

One row per carried stub: ``(node_id, owner, owner_symbol, blocks_kinds)``.

* ``node_id``: the stub's full pytest node id, literal params included.
* ``owner``: a plan id (``AUT-5``) or ``<plan id>:<token>`` where the token (``WP1``) appears in
  that plan's newest revision. ``test_owner_ids_exist_in_plan_docs`` checks it.
* ``owner_symbol``: ``module`` or ``module:dotted.attribute`` the owner will deliver. A row whose
  symbol now resolves is stale and fails ``test_owner_placeholder_symbol_absent``.
* ``blocks_kinds``: the widening kinds that must stay disabled while the row stands. A row may not
  block fewer kinds than ``autonomy_blocks_kinds_floor.BLOCKS_KINDS_FLOOR`` demands.

Seam 4a shipped the mechanism with an empty ledger; seam 4b carries the stubs and their rows.
An owner deletes a row, the marker and the stub in one commit. ``blocks_kinds`` is empty for a
stub that blocks no widening kind (the plan annotates only the kinds it blocks).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, NamedTuple

__all__ = ["CROSS_AREA_FILE", "OWNER_PLACEHOLDERS", "OwnerRow"]


class OwnerRow(NamedTuple):
    node_id: str
    owner: str
    owner_symbol: str
    blocks_kinds: frozenset[str]


CROSS_AREA_FILE: Final = "tests/unit/test_autonomy_cross_area.py"


def _group(
    owner: str, owner_symbol: str, blocks_kinds: Iterable[str], *names: str
) -> tuple[OwnerRow, ...]:
    """Rows for ``names``: bare names are in the cross-area file, ``tests/...`` ids are literal."""
    kinds = frozenset(blocks_kinds)
    return tuple(
        OwnerRow(
            n if n.startswith("tests/") else f"{CROSS_AREA_FILE}::{n}", owner, owner_symbol, kinds
        )
        for n in names
    )


OWNER_PLACEHOLDERS: Final[tuple[OwnerRow, ...]] = (
    *_group(
        "AUT-5:WP1",
        "breezy.persistence.autonomy.nomination:check_k_nomination",
        ["PROMOTE"],
        "test_nomination_refused_past_k_max_lifetime",
        "test_nomination_refused_second_in_window",
        "test_alpha_index_never_resets",
        "test_two_pending_nominees_get_distinct_k",
        "test_infeasible_nomination_charges_no_alpha[store]",
        "test_nomination_columns_required_and_read_by_k_check[k_check]",
    ),
    *_group(
        "AUT-5:WP1",
        "breezy.persistence.autonomy.registry_store:admit_same_family_supersede",
        ["PROMOTE", "SUPERSEDE"],
        "test_repeat_supersede_same_family_is_not_replay[store]",
    ),
    *_group(
        "AUT-5:WP1",
        "breezy.persistence.autonomy.registry_store:append_prelaunch_pair",
        ["ACTIVATE", "ROLLBACK"],
        "test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]",
    ),
    *_group(
        "AUT-5:WP1",
        "breezy.persistence.autonomy.transitions:resume_policy_bounds",
        ["RESUME"],
        "test_resume_admission_reads_policy_block_bounds",
    ),
    *_group(
        "AUT-5:WP1",
        "breezy.runtime.submit_intent_record:classify_current_intent",
        [],
        "test_submit_intent_record_extraction_is_move_only",
        "test_classify_current_intent_states",
        "test_submit_intent_record_module_has_no_file_io",
    ),
    *_group(
        "AUT-5:WP3",
        "breezy.persistence.autonomy.policy:load_policy_block",
        ["PROMOTE"],
        "test_policy_block_not_looser_than_code_ceilings",
        "test_promote_disabled_when_eta_after_kill",
        "test_policy_map_not_looser_than_fallback_map",
        "test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[policy]",
    ),
    *_group(
        "AUT-5:WP4",
        "breezy.analysis.autonomy_engine:run_engine_pass",
        ["ROOT_ADMIT"],
        "test_verdict_acceptance_rules",
        "test_verdict_accepted_after_attest",
        "test_verdict_subject_sha_must_match_row",
        "test_verdict_validity_ceiling[engine]",
        "test_no_policy_fail_demotes_never_widens",
        "test_demotion_never_requires_policy_and_is_immediate[engine]",
        "test_intraday_engine_is_restrictive_only[engine]",
        "test_resume_written_only_at_prelaunch[engine]",
        "test_pending_write_uses_intraday_reconciliation[engine]",
        "test_promotion_requires_reconciled_state",
        "test_ambiguous_intent_cancels_swap_not_incumbent_launch",
        "test_prelaunch_requires_post_stop_reconciliation",
        "test_two_intraday_passes_inside_launch_window",
        "test_intraday_pass_yields_to_prelaunch_lock",
        "test_mirror_read_failure_is_integrity",
        "test_root_admit_only_when_venue_has_no_sender[engine]",
        "test_root_admit_requires_own_allowlist_triple[engine]",
        "test_root_admit_refused_after_operator_halt_within_cooldown",
        "test_root_admit_refused_on_stale_halt_mirror",
    ),
    *_group(
        "AUT-5:WP4",
        "breezy.analysis.autonomy_engine:run_engine_pass",
        ["ACTIVATE"],
        "test_attest_requires_every_listed_detector",
        "test_attest_cadence_has_no_expiry_gap[schedule]",
        "test_every_live_verdict_journaled_once_per_daily_pass",
        "test_cause_verdict_ids_subset_of_acted_rows",
        "test_retired_demand_file_archived",
        "test_demand_archive_crash_between_copy_and_unlink_is_idempotent",
        "test_demand_archive_differing_bytes_is_integrity",
        "test_demand_archive_tmpfile_fallback_sweeps_named_temp",
        "test_registry_champion_requires_live_orders_gate_for_every_kind[engine]",
        "test_prelaunch_writes_rollback_and_activate_atomically[prelaunch]",
        "test_holdout_opens_cache_has_named_writer",
    ),
    *_group(
        "AUT-5:WP2",
        "breezy.adapters.polymarket_us.exec.fill_reader:PolymarketUsFillReader",
        [],
        "test_containment_checks_read_directory_not_phantom_base",
        "test_entry_guard_exact_key_reads_only",
        "test_fill_reader_production_default_runs_once",
        "test_rung_net_position_veto_crosses_legs_and_families[adapter_reader]",
        "test_adapter_reader_fixtures_written_through_record_fill",
        "test_reconciliation_and_entry_guard_never_read_canary_store[adapter_reader]",
    ),
    *_group(
        "AUT-5:WP5",
        "breezy.strategy.autonomy.registry_watch_actor:RegistryWatchActor",
        [],
        "test_watch_actor_never_reads_projection",
        "test_registry_unreadable_veto_clears_only_after_verified_read",
        "test_attest_expiry_and_chain_staleness_veto_entries",
        "test_demotion_latency_slo",
        "test_transient_veto_writes_no_transition",
        "test_restrictive_commit_failure_sets_node_veto",
        "test_attest_veto_armed_after_first_attest",
        "test_attest_veto_rearmed_only_after_post_swap_attest",
        "test_engine_heartbeat_stale_vetoes",
        "test_entry_veto_closed_before_first_tick_and_on_stale_tick",
        "test_watch_actor_store_touches_stay_on_loop_thread",
        "test_node_relaunch_rule_family_id_and_seq_prefix[node]",
        "test_halted_family_boots_entries_vetoed_exits_live",
        "test_resume_clears_registry_halted_without_relaunch",
        "test_compose_refuses_without_entry_veto_slot",
        "test_registry_veto_leaves_exit_seam_open",
        "test_registry_unavailable_mints_no_permit",
        "test_verify_and_load_share_bytes[loader]",
        "test_node_loads_artefact_from_store_by_row_sha",
        "test_champion_own_artefact_mismatch_at_load_is_integrity",
        "test_swap_cannot_exceed_daily_budget_across_namespaces",
        "test_drill_fills_spend_venue_budget",
        "test_incumbent_boot_survives_child_ambiguous_intent",
        "test_entry_guard_cache_invalidated_on_fill",
        "test_bad_demand_file_vetoes_venue[actor]",
        "test_admissibility_predicate_shared[watch_actor]",
        "test_node_writes_hwm_at_boot_before_first_entry",
        "test_watch_actor_busy_tick_is_unverified_not_veto",
        "test_watch_actor_applies_admitted_prefix_then_vetoes",
        "test_watch_actor_export_seq_never_lowered",
        "test_write_monotone_skips_stale_boot_write_after_tick",
        "test_watch_actor_refused_ticks_idempotent",
    ),
    *_group(
        "AUT-5:WP6",
        "breezy.runtime.trade_supervisor_core:resolve_registry_family_at_launch",
        [],
        "test_hand_relaunch_without_registry_source_refused",
        "test_family_source_fixed_in_unit",
        "test_post_launch_swap_cancel_restores_incumbent[supervisor]",
        "test_child_env_touches_only_registry_keys",
        "test_child_env_drops_inbound_registry_keys",
        "test_registry_shadow_logs_agreement_and_spawns_env_family",
        "test_shadow_never_vetoes_or_arms_hand_relaunch_rule",
        "test_relaunch_request_schema_exact_set",
        "test_shadow_resolution_cannot_reach_build_child_env",
        "test_supervisor_busy_retry_only_at_launch",
    ),
    *_group(
        "AUT-5:WP10",
        "breezy.runtime.autonomy_l1_cutover:cutover_steps",
        [],
        "test_l1_cutover_writes_initial_hwm_under_exec_flock",
        "test_l1_cutover_hwm_write_slot_ends_by_164455",
        "test_l1_cutover_lock_acquired_at_164454_aborts",
        "test_l1_cutover_late_write_completion_aborts",
        "test_l1_cutover_abort_leaves_no_key_and_no_registry",
        "test_shadow_bootstrap_creates_export_dir",
    ),
    *_group(
        "AUT-5:WP8",
        "breezy.runtime.registry_hwm_reset_cli:main",
        ["HWM_RESET"],
        "test_hwm_reset_cli_journals_alerts_and_chains",
        "test_hwm_reset_cannot_unhalt",
        "test_hwm_reset_never_refunds_counters",
        "test_resolver_resolves_after_hwm_reset",
        "test_hwm_reset_store_refuses_carried_counters_below_export[store]",
        "test_hwm_absent_after_attest_clears_via_reset_cli",
        "test_hwm_reset_requires_expected_head",
    ),
    *_group(
        "AUT-5:WP11",
        "breezy.analysis.autonomy_producers.drawdown:build_drawdown_producer",
        [],
        "test_drawdown_producer_handshake_with_labels",
        "test_detectors_and_drawdown_include_drill_fills[drawdown]",
    ),
    *_group(
        "AUT-6",
        "breezy.runtime.alert_delivery:deliver_with_proof",
        [],
        "test_deliver_with_proof_reports_non_2xx_through_tee",
        "test_critical_alerts_use_delivery_proof",
        "test_detector_and_failure_mode_alerts_use_delivery_proof",
        "test_critical_survives_sigkill",
        "test_concurrent_drainers_send_at_most_once_per_claim_window",
        "test_try_submit_latency_independent_of_webhook_latency",
        "test_alerts_undeliverable_veto",
        "test_alerts_undeliverable_reads_two_days",
        "test_fee_schedule_verdict_feeds_fee_verified_checks",
    ),
    *_group(
        "AUT-6",
        "breezy.persistence.autonomy.drill_inject:drill_inject_clause",
        [],
        "test_drill_inject_passes_when_marker_absent",
        "test_drill_marker_read_error_never_resumes",
        "test_drill_inject_mapped_only_in_clause",
        "test_shadow_detector_ignores_production_marker",
        "test_production_detector_ignores_shadow_marker",
        "test_shadow_probe_marker_accepted_only_under_shadow_root",
    ),
    *_group(
        "AUT-6",
        "breezy.runtime.autonomy_health_cli:main",
        [],
        "test_health_memory_sum_within_memavailable",
        "test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec",
        "test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine",
        "test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all",
        "test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical",
    ),
    *_group(
        "AUT-6",
        "breezy.persistence.autonomy.detector_catalog:DETECTOR_CATALOG",
        [],
        "test_producer_demand_write_is_restrictive_only[aut6_producer_ast]",
        "test_detectors_and_drawdown_include_drill_fills[detectors]",
    ),
    # AUT-2: the cross-area tests whose GREEN is delivered (WP0-WP3) are real tests now and carry no
    # row. The rest wait on the symbol that lands them: the canary store (WP8), the post-STOP
    # producer (WP6) and the label run (WP6).
    *_group(
        "AUT-2",
        "breezy.persistence.autonomy.canary_store:append_canary_fill",
        [],
        "test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]",
        "test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]",
    ),
    *_group(
        "AUT-2",
        "breezy.analysis.labeling.recon_run:main",
        [],
        "test_post_stop_producer_inconclusive_without_stop_signal",
    ),
    *_group(
        "AUT-2",
        "breezy.analysis.labeling.label_run:main",
        [],
        "test_drill_fills_excluded_from_n_and_kill_clock",
    ),
    *_group(
        "AUT-4",
        "breezy.persistence.autonomy.sample_size:window_cap_verdict",
        [],
        "test_window_cap_below_n_min_is_inconclusive",
        "test_infeasible_nomination_charges_no_alpha[verdict]",
        "test_calibration_leg_relative_inconclusive_below_min_buckets",
    ),
    *_group(
        "AUT-3",
        "breezy.analysis.autonomy.refit:refit_artefact",
        [],
        "test_own_outcome_effect_not_vacuous",
        "test_own_outcome_refused_below_min_gate_decisions",
        "test_refit_writes_only_fresh_sha_dir",
    ),
    *_group(
        "AUT-1",
        "breezy.persistence.exit_tags:join_exit_fill",
        [],
        "test_every_exit_fill_joins",
        "test_decision_id_unique_per_take",
    ),
    *_group(
        "AUT-7",
        "breezy.persistence.autonomy.rollback:rollback_to_target",
        ["ROLLBACK"],
        "test_rollback_restores_byte_identical_artefact",
        "test_failed_rollback_halts_champion",
        "test_drill_rollback_to_superseded_incumbent_admitted",
        "test_rollback_fee_check_uses_verdict_not_node_memory",
        "test_target_manifest_mismatch_marks_ineligible",
        "test_target_byte_mismatch_ineligible_without_freeze[selection]",
        "test_drill_halt_never_freezes_or_writes_exec_store[exec_store]",
        "test_drill_timeline_matches_aut7_sequence",
    ),
    *_group(
        "AUT-7",
        "breezy.persistence.autonomy.rollback:rollback_to_target",
        ["RESUME", "ROLLBACK"],
        "test_failed_drill_close_restored_at_next_prelaunch",
    ),
    *_group(
        "AUT-1",
        "breezy.strategy.autonomy.node_plugins:CAPTURE_PLUGIN",
        [],
        "tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins[capture]",
    ),
    *_group(
        "AUT-2",
        "breezy.analysis.autonomy.offline_plugins:SCORER_PLUGIN",
        [],
        "tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins[scorer]",
    ),
    *_group(
        "AUT-4",
        "breezy.analysis.autonomy.offline_plugins:EVALUATOR_PLUGIN",
        [],
        "tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins[evaluator]",
    ),
    *_group(
        "AUT-6",
        "breezy.strategy.autonomy.node_plugins:DETECTORS_PLUGIN",
        [],
        "tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins[detectors]",
    ),
    *_group(
        "AUT-3",
        "breezy.analysis.autonomy.offline_plugins:REFITTER_PLUGIN",
        [],
        "tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins[refitter]",
    ),
    *_group(
        "AUT-5:WP11",
        "breezy.analysis.autonomy_producers.drawdown:drawdown_gate_on_labels",
        [],
        "tests/unit/test_drawdown_producer.py::test_drawdown_gates_on_labels_consumable",
    ),
    # Carried deploy finding (ruling A4-R5). The "symbol" is the cleared deploy unit; it never
    # resolves as a Python module, so the staleness test cannot fire, and the real staleness signal
    # is the strict XPASS of the parameter itself once the timer stops overlapping.
    OwnerRow(
        "tests/unit/test_launch_window_table.py::"
        "test_no_unit_overlaps_launch_window[known_overlap_breezy-discovery-pull]",
        "AUT-6:O-1",
        "deploy.systemd:breezy-discovery-pull.timer_clear_of_launch_window",
        frozenset(),
    ),
    OwnerRow(
        "tests/unit/test_autonomy_owner_placeholders.py::test_envelope_pending_names_empty",
        "ARCH-0-seamA:8d",
        "tests.unit.autonomy_envelope_manifest:ENVELOPE_PENDING_NAMES_CLEARED",
        frozenset(),
    ),
)
