"""Frozen minimum ``blocks_kinds`` per carried test (ARCH-0 seam A AC 27; security r1 Q5).

Why a separate file: ``pins.ENABLED_WIDENING_KINDS`` and the ledger are edited together when a
kind is enabled, so a gate that only compares the two proves internal consistency. This map is the
independent floor. A ledger row for one of these tests may block more kinds, never fewer, and
changing this file needs a reviewer to see it.

The rows are the ``[blocks]`` annotations of ARCH-0 seam A plan r5 (carried-stub table; the AUT-5
WP4 and AUT-7 rows are the r4 annotations that r5 keeps "unchanged"). Keys are the stub's name
plus its literal params, without the file part. A test with no key here is not floor-protected.

Reading notes (ruling A4-R7):

* Plan r5 l.780 annotates the AUT-5 WP4 row "[ROOT_ADMIT; ACTIVATE]". It is read as two groups
  split at the semicolon: the verdict, intraday and root-admit tests before it block ROOT_ADMIT,
  and the attest, journaling, archive and holdout tests after it block ACTIVATE.
* The three ``test_demand_archive_*`` tests of that row are unnamed in the plan, so they have no key
  here and are not floor-protected until the plan names them.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__ = ["BLOCKS_KINDS_FLOOR", "FLOOR_KIND_VOCABULARY"]

#: ``transitions.WIDENING_KINDS`` (AUT-5 r7 §3.2) plus ``HWM_RESET``, which the plan blocks the
#: same way (``RuleSetPending``). Literal on purpose: ``transitions`` lands in seam 6b.
FLOOR_KIND_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        "PROMOTE",
        "DRILL_PROMOTE",
        "ROLLBACK",
        "RESUME",
        "ROOT_ADMIT",
        "ACTIVATE",
        "SUPERSEDE",
        "DISPLACED",
        "DRILL_ADMIT",
        "HWM_RESET",
    }
)

BLOCKS_KINDS_FLOOR: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "test_nomination_refused_past_k_max_lifetime": frozenset({"PROMOTE"}),
        "test_nomination_refused_second_in_window": frozenset({"PROMOTE"}),
        "test_alpha_index_never_resets": frozenset({"PROMOTE"}),
        "test_two_pending_nominees_get_distinct_k": frozenset({"PROMOTE"}),
        "test_infeasible_nomination_charges_no_alpha[store]": frozenset({"PROMOTE"}),
        "test_nomination_columns_required_and_read_by_k_check[k_check]": frozenset({"PROMOTE"}),
        "test_policy_block_not_looser_than_code_ceilings": frozenset({"PROMOTE"}),
        "test_promote_disabled_when_eta_after_kill": frozenset({"PROMOTE"}),
        "test_policy_map_not_looser_than_fallback_map": frozenset({"PROMOTE"}),
        "test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[policy]": frozenset(
            {"PROMOTE"}
        ),
        "test_repeat_supersede_same_family_is_not_replay[store]": frozenset(
            {"SUPERSEDE", "PROMOTE"}
        ),
        "test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]": frozenset(
            {"ROLLBACK", "ACTIVATE"}
        ),
        "test_resume_admission_reads_policy_block_bounds": frozenset({"RESUME"}),
        "test_verdict_acceptance_rules": frozenset({"ROOT_ADMIT"}),
        "test_verdict_accepted_after_attest": frozenset({"ROOT_ADMIT"}),
        "test_verdict_subject_sha_must_match_row": frozenset({"ROOT_ADMIT"}),
        "test_verdict_validity_ceiling[engine]": frozenset({"ROOT_ADMIT"}),
        "test_no_policy_fail_demotes_never_widens": frozenset({"ROOT_ADMIT"}),
        "test_demotion_never_requires_policy_and_is_immediate[engine]": frozenset({"ROOT_ADMIT"}),
        "test_intraday_engine_is_restrictive_only[engine]": frozenset({"ROOT_ADMIT"}),
        "test_resume_written_only_at_prelaunch[engine]": frozenset({"ROOT_ADMIT"}),
        "test_pending_write_uses_intraday_reconciliation[engine]": frozenset({"ROOT_ADMIT"}),
        "test_promotion_requires_reconciled_state": frozenset({"ROOT_ADMIT"}),
        "test_ambiguous_intent_cancels_swap_not_incumbent_launch": frozenset({"ROOT_ADMIT"}),
        "test_prelaunch_requires_post_stop_reconciliation": frozenset({"ROOT_ADMIT"}),
        "test_two_intraday_passes_inside_launch_window": frozenset({"ROOT_ADMIT"}),
        "test_intraday_pass_yields_to_prelaunch_lock": frozenset({"ROOT_ADMIT"}),
        "test_mirror_read_failure_is_integrity": frozenset({"ROOT_ADMIT"}),
        "test_root_admit_only_when_venue_has_no_sender[engine]": frozenset({"ROOT_ADMIT"}),
        "test_root_admit_requires_own_allowlist_triple[engine]": frozenset({"ROOT_ADMIT"}),
        "test_root_admit_refused_after_operator_halt_within_cooldown": frozenset({"ROOT_ADMIT"}),
        "test_root_admit_refused_on_stale_halt_mirror": frozenset({"ROOT_ADMIT"}),
        "test_attest_requires_every_listed_detector": frozenset({"ACTIVATE"}),
        "test_attest_cadence_has_no_expiry_gap[schedule]": frozenset({"ACTIVATE"}),
        "test_every_live_verdict_journaled_once_per_daily_pass": frozenset({"ACTIVATE"}),
        "test_cause_verdict_ids_subset_of_acted_rows": frozenset({"ACTIVATE"}),
        "test_retired_demand_file_archived": frozenset({"ACTIVATE"}),
        "test_registry_champion_requires_live_orders_gate_for_every_kind[engine]": frozenset(
            {"ACTIVATE"}
        ),
        "test_prelaunch_writes_rollback_and_activate_atomically[prelaunch]": frozenset(
            {"ACTIVATE"}
        ),
        "test_holdout_opens_cache_has_named_writer": frozenset({"ACTIVATE"}),
        "test_hwm_reset_cli_journals_alerts_and_chains": frozenset({"HWM_RESET"}),
        "test_hwm_reset_cannot_unhalt": frozenset({"HWM_RESET"}),
        "test_hwm_reset_never_refunds_counters": frozenset({"HWM_RESET"}),
        "test_resolver_resolves_after_hwm_reset": frozenset({"HWM_RESET"}),
        "test_hwm_reset_store_refuses_carried_counters_below_export[store]": frozenset(
            {"HWM_RESET"}
        ),
        "test_hwm_absent_after_attest_clears_via_reset_cli": frozenset({"HWM_RESET"}),
        "test_hwm_reset_requires_expected_head": frozenset({"HWM_RESET"}),
        "test_rollback_restores_byte_identical_artefact": frozenset({"ROLLBACK"}),
        "test_failed_rollback_halts_champion": frozenset({"ROLLBACK"}),
        "test_drill_rollback_to_superseded_incumbent_admitted": frozenset({"ROLLBACK"}),
        "test_rollback_fee_check_uses_verdict_not_node_memory": frozenset({"ROLLBACK"}),
        "test_target_manifest_mismatch_marks_ineligible": frozenset({"ROLLBACK"}),
        "test_target_byte_mismatch_ineligible_without_freeze[selection]": frozenset({"ROLLBACK"}),
        "test_drill_halt_never_freezes_or_writes_exec_store[exec_store]": frozenset({"ROLLBACK"}),
        "test_drill_timeline_matches_aut7_sequence": frozenset({"ROLLBACK"}),
        "test_failed_drill_close_restored_at_next_prelaunch": frozenset({"ROLLBACK", "RESUME"}),
    }
)
