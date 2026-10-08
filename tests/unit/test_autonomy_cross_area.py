"""ARCH-0 seam 4b: the carried owner-pending stubs (seam A AC 27).

Each stub is a test whose GREEN belongs to another plan. It sits under
``xfail(strict=True, raises=OwnerPending)``, has a row in
``autonomy_owner_placeholders.OWNER_PLACEHOLDERS`` and calls ``await_owner`` on the symbol that row
declares. Today every declared symbol is absent, so each stub fails with ``OwnerPending`` (an
expected failure). When the owner delivers the symbol the stub stops raising ``OwnerPending``, and
the strict marker plus ``test_owner_placeholder_symbol_absent`` make that owner delete the row, the
marker and the stub in one commit and write the real test.

A parametrised stub names its half with ``pytest.param(..., id=<literal>, marks=...)`` because the
4a marker scan reads literal ids. Stubs for the plugin and drawdown-producer files the plan names
live in those files.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.support.autonomy_owner import OwnerPending
from tests.support.autonomy_owner_stub import await_owner
from tests.unit.autonomy_blocks_kinds_floor import BLOCKS_KINDS_FLOOR
from tests.unit.autonomy_owner_placeholders import CROSS_AREA_FILE, OWNER_PLACEHOLDERS, OwnerRow

#: Stubs the plan carries in this file, and the six AUT-5a stubs r5 added. 157 at seam 4b; five
#: AUT-2 stubs became real tests as their symbols landed (WP0, WP2, WP3 x2 and WP5: the
#: ``test_poststop_venue_read_is_get_only``, ``test_scorer_never_attributes_by_trial_id_prefix``,
#: ``test_p_at_decision_is_bought_leg_probability``,
#: ``test_retired_kind_keeps_scorer_until_last_fill_labelled`` and
#: ``test_voided_pair_fills_excluded_from_all_n`` stubs), so the carried count is 157 - 5.
#: WP8 delivered three more (the canary-store reconciliation and entry_guard halves and the drill
#: test), so 152 - 3.
#: AUT-6 WP1 delivered five (the deliver_with_proof, critical-alert, detector, SIGKILL and
#: concurrent-drainer tests, now in ``test_alert_delivery.py`` and
#: ``test_alert_outbox_concurrency.py``), so 149 - 5.
#: AUT-6 WP2 delivered two (``test_alerts_undeliverable_veto`` and
#: ``test_alerts_undeliverable_reads_two_days``, now in ``test_autonomy_node_detectors.py``), so
#: 144 - 2.
EXPECTED_CROSS_AREA_STUBS: Final = 142
R5_AUT_5A_STUBS: Final = (
    "test_l1_cutover_lock_acquired_at_164454_aborts",
    "test_l1_cutover_late_write_completion_aborts",
    "test_l1_cutover_abort_leaves_no_key_and_no_registry",
    "test_write_monotone_skips_stale_boot_write_after_tick",
    "test_watch_actor_refused_ticks_idempotent",
    "test_shadow_bootstrap_creates_export_dir",
)


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE")
def test_nomination_refused_past_k_max_lifetime() -> None:
    await_owner("test_nomination_refused_past_k_max_lifetime")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE")
def test_nomination_refused_second_in_window() -> None:
    await_owner("test_nomination_refused_second_in_window")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE")
def test_alpha_index_never_resets() -> None:
    await_owner("test_alpha_index_never_resets")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE")
def test_two_pending_nominees_get_distinct_k() -> None:
    await_owner("test_two_pending_nominees_get_distinct_k")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "store",
            id="store",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE"
            ),
        ),
        pytest.param(
            "verdict",
            id="verdict",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-4; blocks none"),
        ),
    ],
)
def test_infeasible_nomination_charges_no_alpha(case: str) -> None:
    await_owner(f"test_infeasible_nomination_charges_no_alpha[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "k_check",
            id="k_check",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE"
            ),
        ),
    ],
)
def test_nomination_columns_required_and_read_by_k_check(case: str) -> None:
    await_owner(f"test_nomination_columns_required_and_read_by_k_check[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "store",
            id="store",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks PROMOTE,SUPERSEDE"
            ),
        ),
    ],
)
def test_repeat_supersede_same_family_is_not_replay(case: str) -> None:
    await_owner(f"test_repeat_supersede_same_family_is_not_replay[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "store_atomic",
            id="store_atomic",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks ACTIVATE,ROLLBACK"
            ),
        ),
        pytest.param(
            "prelaunch",
            id="prelaunch",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE"
            ),
        ),
    ],
)
def test_prelaunch_writes_rollback_and_activate_atomically(case: str) -> None:
    await_owner(f"test_prelaunch_writes_rollback_and_activate_atomically[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks RESUME")
def test_resume_admission_reads_policy_block_bounds() -> None:
    await_owner("test_resume_admission_reads_policy_block_bounds")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks none")
def test_submit_intent_record_extraction_is_move_only() -> None:
    await_owner("test_submit_intent_record_extraction_is_move_only")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks none")
def test_classify_current_intent_states() -> None:
    await_owner("test_classify_current_intent_states")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP1; blocks none")
def test_submit_intent_record_module_has_no_file_io() -> None:
    await_owner("test_submit_intent_record_module_has_no_file_io")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP3; blocks PROMOTE")
def test_policy_block_not_looser_than_code_ceilings() -> None:
    await_owner("test_policy_block_not_looser_than_code_ceilings")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP3; blocks PROMOTE")
def test_promote_disabled_when_eta_after_kill() -> None:
    await_owner("test_promote_disabled_when_eta_after_kill")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP3; blocks PROMOTE")
def test_policy_map_not_looser_than_fallback_map() -> None:
    await_owner("test_policy_map_not_looser_than_fallback_map")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "policy",
            id="policy",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP3; blocks PROMOTE"
            ),
        ),
    ],
)
def test_drawdown_inert_ceiling_is_pins_literal_not_policy_key(case: str) -> None:
    await_owner(f"test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_verdict_acceptance_rules() -> None:
    await_owner("test_verdict_acceptance_rules")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_verdict_accepted_after_attest() -> None:
    await_owner("test_verdict_accepted_after_attest")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_verdict_subject_sha_must_match_row() -> None:
    await_owner("test_verdict_subject_sha_must_match_row")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_verdict_validity_ceiling(case: str) -> None:
    await_owner(f"test_verdict_validity_ceiling[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_no_policy_fail_demotes_never_widens() -> None:
    await_owner("test_no_policy_fail_demotes_never_widens")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_demotion_never_requires_policy_and_is_immediate(case: str) -> None:
    await_owner(f"test_demotion_never_requires_policy_and_is_immediate[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_intraday_engine_is_restrictive_only(case: str) -> None:
    await_owner(f"test_intraday_engine_is_restrictive_only[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_resume_written_only_at_prelaunch(case: str) -> None:
    await_owner(f"test_resume_written_only_at_prelaunch[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_pending_write_uses_intraday_reconciliation(case: str) -> None:
    await_owner(f"test_pending_write_uses_intraday_reconciliation[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_promotion_requires_reconciled_state() -> None:
    await_owner("test_promotion_requires_reconciled_state")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_ambiguous_intent_cancels_swap_not_incumbent_launch() -> None:
    await_owner("test_ambiguous_intent_cancels_swap_not_incumbent_launch")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_prelaunch_requires_post_stop_reconciliation() -> None:
    await_owner("test_prelaunch_requires_post_stop_reconciliation")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_two_intraday_passes_inside_launch_window() -> None:
    await_owner("test_two_intraday_passes_inside_launch_window")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_intraday_pass_yields_to_prelaunch_lock() -> None:
    await_owner("test_intraday_pass_yields_to_prelaunch_lock")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_mirror_read_failure_is_integrity() -> None:
    await_owner("test_mirror_read_failure_is_integrity")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_root_admit_only_when_venue_has_no_sender(case: str) -> None:
    await_owner(f"test_root_admit_only_when_venue_has_no_sender[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT"
            ),
        ),
    ],
)
def test_root_admit_requires_own_allowlist_triple(case: str) -> None:
    await_owner(f"test_root_admit_requires_own_allowlist_triple[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_root_admit_refused_after_operator_halt_within_cooldown() -> None:
    await_owner("test_root_admit_refused_after_operator_halt_within_cooldown")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ROOT_ADMIT")
def test_root_admit_refused_on_stale_halt_mirror() -> None:
    await_owner("test_root_admit_refused_on_stale_halt_mirror")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_attest_requires_every_listed_detector() -> None:
    await_owner("test_attest_requires_every_listed_detector")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "schedule",
            id="schedule",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE"
            ),
        ),
    ],
)
def test_attest_cadence_has_no_expiry_gap(case: str) -> None:
    await_owner(f"test_attest_cadence_has_no_expiry_gap[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_every_live_verdict_journaled_once_per_daily_pass() -> None:
    await_owner("test_every_live_verdict_journaled_once_per_daily_pass")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_cause_verdict_ids_subset_of_acted_rows() -> None:
    await_owner("test_cause_verdict_ids_subset_of_acted_rows")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_retired_demand_file_archived() -> None:
    await_owner("test_retired_demand_file_archived")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_demand_archive_crash_between_copy_and_unlink_is_idempotent() -> None:
    await_owner("test_demand_archive_crash_between_copy_and_unlink_is_idempotent")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_demand_archive_differing_bytes_is_integrity() -> None:
    await_owner("test_demand_archive_differing_bytes_is_integrity")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_demand_archive_tmpfile_fallback_sweeps_named_temp() -> None:
    await_owner("test_demand_archive_tmpfile_fallback_sweeps_named_temp")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "engine",
            id="engine",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE"
            ),
        ),
    ],
)
def test_registry_champion_requires_live_orders_gate_for_every_kind(case: str) -> None:
    await_owner(f"test_registry_champion_requires_live_orders_gate_for_every_kind[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP4; blocks ACTIVATE")
def test_holdout_opens_cache_has_named_writer() -> None:
    await_owner("test_holdout_opens_cache_has_named_writer")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none")
def test_containment_checks_read_directory_not_phantom_base() -> None:
    await_owner("test_containment_checks_read_directory_not_phantom_base")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none")
def test_entry_guard_exact_key_reads_only() -> None:
    await_owner("test_entry_guard_exact_key_reads_only")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none")
def test_fill_reader_production_default_runs_once() -> None:
    await_owner("test_fill_reader_production_default_runs_once")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "adapter_reader",
            id="adapter_reader",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none"
            ),
        ),
    ],
)
def test_rung_net_position_veto_crosses_legs_and_families(case: str) -> None:
    await_owner(f"test_rung_net_position_veto_crosses_legs_and_families[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none")
def test_adapter_reader_fixtures_written_through_record_fill() -> None:
    await_owner("test_adapter_reader_fixtures_written_through_record_fill")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "adapter_reader",
            id="adapter_reader",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP2; blocks none"
            ),
        ),
        pytest.param("reconciliation", id="reconciliation"),
        pytest.param("entry_guard", id="entry_guard"),
    ],
)
def test_reconciliation_and_entry_guard_never_read_canary_store(case: str, tmp_path: Path) -> None:
    """The two AUT-2 halves are delivered by WP8 (the isolation test scans both modules); the
    adapter-reader half waits on AUT-5:WP2."""
    if case == "adapter_reader":
        await_owner(f"test_reconciliation_and_entry_guard_never_read_canary_store[{case}]")
        return
    from tests.unit.test_aut2_canary_isolation import (
        test_reconciliation_and_entry_guard_never_read_canary_store as delivered,
    )

    delivered(tmp_path)


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_never_reads_projection() -> None:
    await_owner("test_watch_actor_never_reads_projection")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_registry_unreadable_veto_clears_only_after_verified_read() -> None:
    await_owner("test_registry_unreadable_veto_clears_only_after_verified_read")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_attest_expiry_and_chain_staleness_veto_entries() -> None:
    await_owner("test_attest_expiry_and_chain_staleness_veto_entries")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_demotion_latency_slo() -> None:
    await_owner("test_demotion_latency_slo")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_transient_veto_writes_no_transition() -> None:
    await_owner("test_transient_veto_writes_no_transition")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_restrictive_commit_failure_sets_node_veto() -> None:
    await_owner("test_restrictive_commit_failure_sets_node_veto")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_attest_veto_armed_after_first_attest() -> None:
    await_owner("test_attest_veto_armed_after_first_attest")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_attest_veto_rearmed_only_after_post_swap_attest() -> None:
    await_owner("test_attest_veto_rearmed_only_after_post_swap_attest")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_engine_heartbeat_stale_vetoes() -> None:
    await_owner("test_engine_heartbeat_stale_vetoes")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_entry_veto_closed_before_first_tick_and_on_stale_tick() -> None:
    await_owner("test_entry_veto_closed_before_first_tick_and_on_stale_tick")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_store_touches_stay_on_loop_thread() -> None:
    await_owner("test_watch_actor_store_touches_stay_on_loop_thread")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "node",
            id="node",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none"
            ),
        ),
    ],
)
def test_node_relaunch_rule_family_id_and_seq_prefix(case: str) -> None:
    await_owner(f"test_node_relaunch_rule_family_id_and_seq_prefix[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_halted_family_boots_entries_vetoed_exits_live() -> None:
    await_owner("test_halted_family_boots_entries_vetoed_exits_live")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_resume_clears_registry_halted_without_relaunch() -> None:
    await_owner("test_resume_clears_registry_halted_without_relaunch")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_compose_refuses_without_entry_veto_slot() -> None:
    await_owner("test_compose_refuses_without_entry_veto_slot")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_registry_veto_leaves_exit_seam_open() -> None:
    await_owner("test_registry_veto_leaves_exit_seam_open")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_registry_unavailable_mints_no_permit() -> None:
    await_owner("test_registry_unavailable_mints_no_permit")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "loader",
            id="loader",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none"
            ),
        ),
    ],
)
def test_verify_and_load_share_bytes(case: str) -> None:
    await_owner(f"test_verify_and_load_share_bytes[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_node_loads_artefact_from_store_by_row_sha() -> None:
    await_owner("test_node_loads_artefact_from_store_by_row_sha")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_champion_own_artefact_mismatch_at_load_is_integrity() -> None:
    await_owner("test_champion_own_artefact_mismatch_at_load_is_integrity")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_swap_cannot_exceed_daily_budget_across_namespaces() -> None:
    await_owner("test_swap_cannot_exceed_daily_budget_across_namespaces")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_drill_fills_spend_venue_budget() -> None:
    await_owner("test_drill_fills_spend_venue_budget")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_incumbent_boot_survives_child_ambiguous_intent() -> None:
    await_owner("test_incumbent_boot_survives_child_ambiguous_intent")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_entry_guard_cache_invalidated_on_fill() -> None:
    await_owner("test_entry_guard_cache_invalidated_on_fill")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "actor",
            id="actor",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none"
            ),
        ),
    ],
)
def test_bad_demand_file_vetoes_venue(case: str) -> None:
    await_owner(f"test_bad_demand_file_vetoes_venue[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "watch_actor",
            id="watch_actor",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none"
            ),
        ),
    ],
)
def test_admissibility_predicate_shared(case: str) -> None:
    await_owner(f"test_admissibility_predicate_shared[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_node_writes_hwm_at_boot_before_first_entry() -> None:
    await_owner("test_node_writes_hwm_at_boot_before_first_entry")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_busy_tick_is_unverified_not_veto() -> None:
    await_owner("test_watch_actor_busy_tick_is_unverified_not_veto")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_applies_admitted_prefix_then_vetoes() -> None:
    await_owner("test_watch_actor_applies_admitted_prefix_then_vetoes")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_export_seq_never_lowered() -> None:
    await_owner("test_watch_actor_export_seq_never_lowered")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_write_monotone_skips_stale_boot_write_after_tick() -> None:
    await_owner("test_write_monotone_skips_stale_boot_write_after_tick")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP5; blocks none")
def test_watch_actor_refused_ticks_idempotent() -> None:
    await_owner("test_watch_actor_refused_ticks_idempotent")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_hand_relaunch_without_registry_source_refused() -> None:
    await_owner("test_hand_relaunch_without_registry_source_refused")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_family_source_fixed_in_unit() -> None:
    await_owner("test_family_source_fixed_in_unit")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "supervisor",
            id="supervisor",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none"
            ),
        ),
    ],
)
def test_post_launch_swap_cancel_restores_incumbent(case: str) -> None:
    await_owner(f"test_post_launch_swap_cancel_restores_incumbent[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_child_env_touches_only_registry_keys() -> None:
    await_owner("test_child_env_touches_only_registry_keys")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_child_env_drops_inbound_registry_keys() -> None:
    await_owner("test_child_env_drops_inbound_registry_keys")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_registry_shadow_logs_agreement_and_spawns_env_family() -> None:
    await_owner("test_registry_shadow_logs_agreement_and_spawns_env_family")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_shadow_never_vetoes_or_arms_hand_relaunch_rule() -> None:
    await_owner("test_shadow_never_vetoes_or_arms_hand_relaunch_rule")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_relaunch_request_schema_exact_set() -> None:
    await_owner("test_relaunch_request_schema_exact_set")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_shadow_resolution_cannot_reach_build_child_env() -> None:
    await_owner("test_shadow_resolution_cannot_reach_build_child_env")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP6; blocks none")
def test_supervisor_busy_retry_only_at_launch() -> None:
    await_owner("test_supervisor_busy_retry_only_at_launch")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_l1_cutover_writes_initial_hwm_under_exec_flock() -> None:
    await_owner("test_l1_cutover_writes_initial_hwm_under_exec_flock")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_l1_cutover_hwm_write_slot_ends_by_164455() -> None:
    await_owner("test_l1_cutover_hwm_write_slot_ends_by_164455")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_l1_cutover_lock_acquired_at_164454_aborts() -> None:
    await_owner("test_l1_cutover_lock_acquired_at_164454_aborts")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_l1_cutover_late_write_completion_aborts() -> None:
    await_owner("test_l1_cutover_late_write_completion_aborts")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_l1_cutover_abort_leaves_no_key_and_no_registry() -> None:
    await_owner("test_l1_cutover_abort_leaves_no_key_and_no_registry")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP10; blocks none")
def test_shadow_bootstrap_creates_export_dir() -> None:
    await_owner("test_shadow_bootstrap_creates_export_dir")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_hwm_reset_cli_journals_alerts_and_chains() -> None:
    await_owner("test_hwm_reset_cli_journals_alerts_and_chains")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_hwm_reset_cannot_unhalt() -> None:
    await_owner("test_hwm_reset_cannot_unhalt")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_hwm_reset_never_refunds_counters() -> None:
    await_owner("test_hwm_reset_never_refunds_counters")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_resolver_resolves_after_hwm_reset() -> None:
    await_owner("test_resolver_resolves_after_hwm_reset")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "store",
            id="store",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET"
            ),
        ),
    ],
)
def test_hwm_reset_store_refuses_carried_counters_below_export(case: str) -> None:
    await_owner(f"test_hwm_reset_store_refuses_carried_counters_below_export[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_hwm_absent_after_attest_clears_via_reset_cli() -> None:
    await_owner("test_hwm_absent_after_attest_clears_via_reset_cli")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP8; blocks HWM_RESET")
def test_hwm_reset_requires_expected_head() -> None:
    await_owner("test_hwm_reset_requires_expected_head")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP11; blocks none")
def test_drawdown_producer_handshake_with_labels() -> None:
    await_owner("test_drawdown_producer_handshake_with_labels")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "drawdown",
            id="drawdown",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-5:WP11; blocks none"
            ),
        ),
        pytest.param(
            "detectors",
            id="detectors",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none"),
        ),
    ],
)
def test_detectors_and_drawdown_include_drill_fills(case: str) -> None:
    await_owner(f"test_detectors_and_drawdown_include_drill_fills[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_try_submit_latency_independent_of_webhook_latency() -> None:
    await_owner("test_try_submit_latency_independent_of_webhook_latency")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_fee_schedule_verdict_feeds_fee_verified_checks() -> None:
    await_owner("test_fee_schedule_verdict_feeds_fee_verified_checks")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_drill_inject_passes_when_marker_absent() -> None:
    await_owner("test_drill_inject_passes_when_marker_absent")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_drill_marker_read_error_never_resumes() -> None:
    await_owner("test_drill_marker_read_error_never_resumes")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_drill_inject_mapped_only_in_clause() -> None:
    await_owner("test_drill_inject_mapped_only_in_clause")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_shadow_detector_ignores_production_marker() -> None:
    await_owner("test_shadow_detector_ignores_production_marker")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_production_detector_ignores_shadow_marker() -> None:
    await_owner("test_production_detector_ignores_shadow_marker")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_shadow_probe_marker_accepted_only_under_shadow_root() -> None:
    await_owner("test_shadow_probe_marker_accepted_only_under_shadow_root")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_health_memory_sum_within_memavailable() -> None:
    await_owner("test_health_memory_sum_within_memavailable")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec() -> None:
    await_owner("test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine() -> None:
    await_owner("test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all() -> None:  # fmt: skip  # noqa: E501
    await_owner(
        "test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all"
    )


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none")
def test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical() -> None:
    await_owner("test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "aut6_producer_ast",
            id="aut6_producer_ast",
            marks=pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-6; blocks none"),
        ),
    ],
)
def test_producer_demand_write_is_restrictive_only(case: str) -> None:
    await_owner(f"test_producer_demand_write_is_restrictive_only[{case}]")


def test_p_at_decision_is_bought_leg_probability() -> None:
    """Delivered by AUT-2 WP3: the owner's own test, run under the ARCH 4.7 node id."""
    from tests.unit.test_aut2_probability import test_p_at_decision_is_bought_leg_probability as t

    t()


def test_scorer_never_attributes_by_trial_id_prefix() -> None:
    """Delivered by AUT-2 WP2: the owner's own test (AST scan plus a behaviour fixture)."""
    from tests.unit.test_aut2_attribution import (
        test_scorer_never_attributes_by_trial_id_prefix as t,
    )

    t()


def test_voided_pair_fills_excluded_from_all_n() -> None:
    """Delivered by AUT-2 WP3: the FQ scorer's own test, run on a voided-pair attribution."""
    from tests.unit.test_aut2_fq_scorer import test_voided_pair_fills_excluded_from_all_n as t

    t()


def test_poststop_venue_read_is_get_only() -> None:
    """Delivered by AUT-2 WP0: the owner's test of the one GET call, the literal and the cap."""
    from tests.unit.test_venue_positions_read import test_poststop_venue_read_is_get_only as t

    t()


def test_retired_kind_keeps_scorer_until_last_fill_labelled() -> None:
    """Delivered by AUT-2 WP3: a retired CRH kind keeps its scorer until its last fill."""
    from tests.unit.test_aut2_legacy_crh_scorer import (
        test_retired_kind_keeps_scorer_until_last_fill_labelled as t,
    )

    t()


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-2; blocks none")
def test_post_stop_producer_inconclusive_without_stop_signal() -> None:
    await_owner("test_post_stop_producer_inconclusive_without_stop_signal")


def test_drill_fills_excluded_from_n_and_kill_clock() -> None:
    """Delivered by AUT-2 WP8: the FQ scorer's own test (a drill row is inadmissible, so no n)."""
    from tests.unit.test_aut2_fq_scorer import test_drill_fills_excluded_from_n_and_kill_clock as t

    t()


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-4; blocks none")
def test_window_cap_below_n_min_is_inconclusive() -> None:
    await_owner("test_window_cap_below_n_min_is_inconclusive")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-4; blocks none")
def test_calibration_leg_relative_inconclusive_below_min_buckets() -> None:
    await_owner("test_calibration_leg_relative_inconclusive_below_min_buckets")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-3; blocks none")
def test_own_outcome_effect_not_vacuous() -> None:
    await_owner("test_own_outcome_effect_not_vacuous")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-3; blocks none")
def test_own_outcome_refused_below_min_gate_decisions() -> None:
    await_owner("test_own_outcome_refused_below_min_gate_decisions")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-3; blocks none")
def test_refit_writes_only_fresh_sha_dir() -> None:
    await_owner("test_refit_writes_only_fresh_sha_dir")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-1; blocks none")
def test_every_exit_fill_joins() -> None:
    await_owner("test_every_exit_fill_joins")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-1; blocks none")
def test_decision_id_unique_per_take() -> None:
    await_owner("test_decision_id_unique_per_take")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_rollback_restores_byte_identical_artefact() -> None:
    await_owner("test_rollback_restores_byte_identical_artefact")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_failed_rollback_halts_champion() -> None:
    await_owner("test_failed_rollback_halts_champion")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_drill_rollback_to_superseded_incumbent_admitted() -> None:
    await_owner("test_drill_rollback_to_superseded_incumbent_admitted")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_rollback_fee_check_uses_verdict_not_node_memory() -> None:
    await_owner("test_rollback_fee_check_uses_verdict_not_node_memory")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_target_manifest_mismatch_marks_ineligible() -> None:
    await_owner("test_target_manifest_mismatch_marks_ineligible")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "selection",
            id="selection",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK"
            ),
        ),
    ],
)
def test_target_byte_mismatch_ineligible_without_freeze(case: str) -> None:
    await_owner(f"test_target_byte_mismatch_ineligible_without_freeze[{case}]")


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "exec_store",
            id="exec_store",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK"
            ),
        ),
    ],
)
def test_drill_halt_never_freezes_or_writes_exec_store(case: str) -> None:
    await_owner(f"test_drill_halt_never_freezes_or_writes_exec_store[{case}]")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks ROLLBACK")
def test_drill_timeline_matches_aut7_sequence() -> None:
    await_owner("test_drill_timeline_matches_aut7_sequence")


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-7; blocks RESUME,ROLLBACK")
def test_failed_drill_close_restored_at_next_prelaunch() -> None:
    await_owner("test_failed_drill_close_restored_at_next_prelaunch")


# ---------------------------------------------------------------------------
# The carrying mechanism itself
# ---------------------------------------------------------------------------

_THIS_FILE: Final = Path(__file__)


def _own_rows() -> list[tuple[str, str]]:
    prefix = f"{CROSS_AREA_FILE}::"
    return [
        (r.node_id.removeprefix(prefix), r.owner)
        for r in OWNER_PLACEHOLDERS
        if r.node_id.startswith(prefix)
    ]


def test_every_floor_protected_test_is_carried() -> None:
    carried = {r.node_id.split("::", 1)[1] for r in OWNER_PLACEHOLDERS}
    assert sorted(set(BLOCKS_KINDS_FLOOR) - carried) == []


def test_the_plan_stub_count_and_the_six_new_aut_5a_stubs_are_carried() -> None:
    rows = dict(_own_rows())
    assert len(rows) == EXPECTED_CROSS_AREA_STUBS
    assert {rows[name] for name in R5_AUT_5A_STUBS} <= {"AUT-5:WP5", "AUT-5:WP10"}
    assert set(R5_AUT_5A_STUBS) <= set(rows)


def test_the_canary_store_param_split_follows_ruling_b6_a1() -> None:
    owners = dict(_own_rows())
    base = "test_reconciliation_and_entry_guard_never_read_canary_store"
    # WP8 delivered the two AUT-2 halves: they are real tests and carry no row
    assert f"{base}[entry_guard]" not in owners and f"{base}[reconciliation]" not in owners
    assert owners[f"{base}[adapter_reader]"] == "AUT-5:WP2"


def _owner_xfail_reasons(decorator: ast.expr) -> list[tuple[str | None, str]]:
    """``(param id or None, reason)`` for each strict owner xfail in one decorator."""
    xfails = [
        c
        for c in ast.walk(decorator)
        if isinstance(c, ast.Call) and ast.unparse(c.func).endswith("xfail")
    ]
    found: list[tuple[str | None, str]] = []
    for call in xfails:
        reason = next(k.value for k in call.keywords if k.arg == "reason")
        assert isinstance(reason, ast.Constant) and isinstance(reason.value, str)
        owner_param = [
            p
            for p in ast.walk(decorator)
            if isinstance(p, ast.Call)
            and ast.unparse(p.func).endswith("param")
            and call in list(ast.walk(p))
        ]
        param_id = None
        if owner_param:
            id_kw = next(k.value for k in owner_param[0].keywords if k.arg == "id")
            assert isinstance(id_kw, ast.Constant)
            param_id = str(id_kw.value)
        found.append((param_id, reason.value))
    return found


def _marker_reasons(path: Path) -> dict[str, str]:
    """Stub name (plus ``[id]``) -> literal xfail reason, for decorator and param forms."""
    reasons: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                for param_id, reason in _owner_xfail_reasons(decorator):
                    reasons[node.name + (f"[{param_id}]" if param_id else "")] = reason
    return reasons


def test_each_stub_reason_names_its_ledger_owner_and_blocked_kinds() -> None:
    reasons = _marker_reasons(_THIS_FILE)
    rows = {
        r.node_id.removeprefix(f"{CROSS_AREA_FILE}::"): r
        for r in OWNER_PLACEHOLDERS
        if r.node_id.startswith(f"{CROSS_AREA_FILE}::")
    }
    assert set(reasons) == set(rows)
    for name, row in rows.items():
        kinds = ",".join(sorted(row.blocks_kinds)) or "none"
        assert reasons[name] == f"{row.owner}; blocks {kinds}", name


def test_await_owner_is_pending_while_the_declared_symbol_is_absent() -> None:
    with pytest.raises(OwnerPending):
        await_owner("test_alpha_index_never_resets")


def test_await_owner_fails_loudly_for_a_stub_with_no_ledger_row() -> None:
    with pytest.raises(KeyError):
        await_owner("test_not_in_the_ledger")


def test_await_owner_fails_loudly_once_the_owner_symbol_resolves() -> None:
    delivered = OwnerRow(
        f"{CROSS_AREA_FILE}::test_delivered",
        "AUT-5:WP1",
        "breezy.persistence.autonomy.canonical:canonical_json",
        frozenset(),
    )
    with pytest.raises(NotImplementedError):
        await_owner("test_delivered", [delivered])
