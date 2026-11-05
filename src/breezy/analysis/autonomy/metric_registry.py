"""Closed metric names, reason literals and the per-kind column rules of AUT-4 verdicts.

AUT-4 r11 §3.1a and §3.11a. The ARCH-0 ``verdict/v1`` writer owns the wire schema; this registry
is the AUT-4-side closed vocabulary that the producers draw from, so a typo can never mint a new
metric name or reason. ``tests/unit/autonomy/test_verdict_schema.py`` pins the column rules
against the ARCH-0 ``Verdict`` so the two cannot drift.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

KIND_OFFLINE_CHALLENGER: Final[str] = "OFFLINE_CHALLENGER"
KIND_FORWARD_SHADOW: Final[str] = "FORWARD_SHADOW"
KIND_LIVE_SEQUENTIAL: Final[str] = "LIVE_SEQUENTIAL"
KIND_HEALTH: Final[str] = "HEALTH"
AUT4_KINDS: Final[tuple[str, ...]] = (
    KIND_OFFLINE_CHALLENGER,
    KIND_FORWARD_SHADOW,
    KIND_LIVE_SEQUENTIAL,
    KIND_HEALTH,
)

#: The closed five-tag ``assumptions`` enum (ARCH C4, P4-12). Nothing else may be added.
ASSUMPTION_TAGS: Final[frozenset[str]] = frozenset(
    {
        "slippage_champion_proxy",
        "slippage_floor_aud12a",
        "fill_survivorship_unmodelled",
        "no_policy_ruling",
        "drill",
    }
)

#: The two ruling-sha columns every kind carries (ARCH C4, P4-10).
POLICY_RULING_COLUMN: Final[str] = "policy_ruling_sha256"
FAMILY_PREREG_COLUMN: Final[str] = "family_prereg_sha256"
RULING_SHA_COLUMNS: Final[tuple[str, str]] = (POLICY_RULING_COLUMN, FAMILY_PREREG_COLUMN)

FORWARD_SHADOW_ONLY_COLUMNS: Final[tuple[str, ...]] = ("k_life", "alpha_k", "n_min_eff", "n_cap")
#: E-25 (F7B-R2): non-null only on a FORWARD_SHADOW ``e_process`` verdict (null elsewhere).
FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS: Final[tuple[str, ...]] = ("eta_ns", "window_end")
#: E-25 rule 1: ``test_kind`` is null on every kind but FORWARD_SHADOW and LIVE_SEQUENTIAL.
TEST_KIND_COLUMN: Final[str] = "test_kind"
_NO_TEST_KIND_NULL: Final[frozenset[str]] = frozenset(
    {TEST_KIND_COLUMN, *FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS}
)
_HEALTH_NULL: Final[frozenset[str]] = frozenset(
    {
        "n",
        "n_min",
        "power",
        "mde",
        "comparator_family_id",
        "alpha_spent",
        "eta_to_verdict_days",
        FAMILY_PREREG_COLUMN,
        *FORWARD_SHADOW_ONLY_COLUMNS,
        *_NO_TEST_KIND_NULL,
    }
)

#: Columns that MUST be null for each kind (§3.1a). Every other column is populated, or null
#: with a literal ``metrics.outcome_reason``.
NULL_COLUMNS_BY_KIND: Final = MappingProxyType(
    {
        KIND_OFFLINE_CHALLENGER: frozenset(
            {"power", FAMILY_PREREG_COLUMN, *FORWARD_SHADOW_ONLY_COLUMNS, *_NO_TEST_KIND_NULL}
        ),
        KIND_FORWARD_SHADOW: frozenset({FAMILY_PREREG_COLUMN}),
        KIND_LIVE_SEQUENTIAL: frozenset(
            {*FORWARD_SHADOW_ONLY_COLUMNS, *FORWARD_SHADOW_E_PROCESS_ONLY_COLUMNS}
        ),
        KIND_HEALTH: _HEALTH_NULL,
    }
)

#: Closed reason literals carried in ``INCONCLUSIVE(...)``/``UNDERPOWERED(...)`` outcomes.
OUTCOME_REASONS: Final[frozenset[str]] = frozenset(
    {
        "screen_min_days",
        "NOT_DISTINCT",
        "min_clusters",
        "cluster_sensitivity",
        "calibration_buckets_below_min",
        "window_cap_below_n_min",
        "window_end_underpowered",
        "fill_rate_underpowered",
        "PROXY_UNDERPOWERED",
        "fill_selection_sensitive",
        "mixed_closure",
        "no_registered_boundary",
        "SEALED_WINDOW",
    }
)
DAY_STATUS_NO_INPUT: Final[str] = "NO_INPUT"

#: §3.11a: the closed ``eval_replay_path`` metric names (AUT-6 pins the same set).
EVAL_REPLAY_PATH_METRICS: Final[frozenset[str]] = frozenset(
    {
        "tape_day",
        "closure_sha256",
        "subject_role",
        "admitted_station_days",
        "excluded_by_reason",
        "parity",
        "day_status",
    }
)
#: The keys of ``metrics.parity``: ``ParityReport.to_counts_dict()`` plus three Take counts.
PARITY_SCALAR_COUNT_KEYS: Final[tuple[str, ...]] = (
    "n_live",
    "n_batch",
    "n_matched",
    "n_live_only",
    "n_batch_only",
    "n_numeric_mismatches",
    "n_mismatches",
)
PARITY_SIDE_KIND_COUNT_KEYS: Final[tuple[str, ...]] = tuple(
    f"n_{route}_{side}_{kind}"
    for route in ("live", "batch")
    for side in ("yes", "no")
    for kind in ("NotDPlus1", "NotExecutable", "Refuse", "Take")
)
PARITY_TAKE_COUNT_KEYS: Final[tuple[str, ...]] = (
    "n_take_live_only",
    "n_take_batch_only",
    "n_take_numeric_mismatches",
)
PARITY_KEYS: Final[frozenset[str]] = frozenset(
    (*PARITY_SCALAR_COUNT_KEYS, *PARITY_SIDE_KIND_COUNT_KEYS, *PARITY_TAKE_COUNT_KEYS)
)

#: Every other AUT-4 metric name the plan registers.
VERDICT_METRICS: Final[frozenset[str]] = frozenset(
    {
        "brier_rung_diff_vs_champion",
        "crps_tmax_diff_vs_champion",
        "brier_rung_diff_vs_market",
        "underconfidence_mean_signed_dev",
        "calibration_leg_rung",
        "msd_diff",
        "nomination_transition_id",
        "fixture_candidate",
        "fill_selection_sensitive",
        "ev_eff_worst_case",
        "sigma_source_contaminated",
        "p_method",
        "alpha_scope",
        "n_max",
        "stop_reason",
        "outcome_reason",
        "day_status",
    }
)
METRIC_NAMES: Final[frozenset[str]] = VERDICT_METRICS | EVAL_REPLAY_PATH_METRICS


def is_registered_metric(name: str) -> bool:
    return name in METRIC_NAMES


def is_registered_reason(reason: str) -> bool:
    return reason in OUTCOME_REASONS
