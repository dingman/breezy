"""Code-reviewed autonomy pins (ARCH-0 AC 25). Literals only; imports nothing but typing and
``types.MappingProxyType``. Every value is changed only by a reviewed commit.

Ceilings are ARCH 4.5 (AUTONOMY_ARCHITECTURE.md:903-940) as amended by E-11
(reviews/ARCH-ERRATA-rev9_2.md:226; no ``SELF_HEAL_*``) and E-14 (:416). Where ARCH states a
bound (``<= x`` or ``>= x``) the pin is that bound; the policy block may only be stricter.
Fractions are decimal strings (the wire format has no floats). Kind sets are validated against
``schemas.Kind`` in seam 6b, not here.
"""

from types import MappingProxyType
from typing import Final

# --- Code identity (empty at ARCH-0: every production resolution refuses engine_code_unpinned).
ENGINE_SOURCE_SHA256: Final[frozenset[str]] = frozenset()
# aut6.health (P6-13, plan r15 section 3.4.1): sha256 of the import closure of
# ``breezy.runtime.autonomy_health_cli`` (``closure_manifest``). Any change to a closure module
# makes ``test_code_identity_pins_cover_import_closure`` fail until a reviewed commit re-pins it.
PRODUCER_SOURCE_SHA256: Final[MappingProxyType[str, str]] = MappingProxyType(
    {"aut6.health": "3cc7672cee0b33e95ac99c0c1c3a0848517ce27c1984039d80ce0a5612779aa8"}
)
REVOKED_SOURCE_SHA256: Final[frozenset[str]] = frozenset()

# --- Widening and policy gates (AC 25).
ENABLED_WIDENING_KINDS: Final[frozenset[str]] = frozenset()
POLICY_RULING_PIN: Final[tuple[str, ...]] = ()
ROOT_ADMIT_ENABLED_CEILING: Final = False  # ARCH:930 literal bool, committed false
LIVE_GATE_ROUTED_KINDS: Final = frozenset({"forecast_quantile_ladder"})  # ARCH:601

# --- Damping (ARCH 4.5 :908-927).
RESUME_COOLDOWN_H: Final = 24  # :909 >= 24
MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D: Final = 2  # :910 <= 2
MAX_INFRA_RESUMES_PER_VENUE_7D: Final = 3  # :911 <= 3
MAX_ROLLBACKS_PER_VENUE_30D: Final = 2  # :912 <= 2
ROLLBACK_MIN_DWELL_H: Final = 24  # :913 >= 24
ROLLBACK_TARGET_MAX_AGE_D: Final = 30  # :914 <= 30
DRILL_MIN_DRAWDOWN_HEADROOM_FRAC: Final = "0.5"  # :915 >= 0.5 (a floor)
RELAUNCH_REQUEST_TTL_S: Final = 120  # :916 = 120 (>= 2 x the 60 s schedule poll)
MAX_SENDER_CHANGES_PER_VENUE_PER_DAY: Final = 2  # :917 <= 2
MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE: Final = 14  # :918 >= 14
MIN_GATE_DECISIONS_CHANGED: Final = 1  # :919 >= 1
MIN_CALIBRATION_BUCKETS: Final = 1  # :919 >= 1 (floor; policy proposes 3)
MAX_NOMINATIONS_PER_LINEAGE_LIFETIME: Final = 4  # :920 <= 4
MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME: Final = 4  # E-25 rule 6 <= 4
MAX_NOMINATIONS_PER_FORWARD_WINDOW: Final = 1  # :920 <= 1
BOOTSTRAP_B_MAX: Final = 524288  # :921 literal draw cap; 2**19 per AUT-4 r11 R4-8 (:1784)
MAX_MINTS_PER_LINEAGE_PER_DAY: Final = 1  # :923 <= 1
DRILL_BUDGET_PER_VENUE_30D: Final = 1  # :924 <= 1
DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY: Final = 1  # E-5; AUT-5 r7 :112
DEADMAN_HORIZON_H: Final = 30  # :925 <= 30
MAX_VERDICT_VALIDITY_H: Final = 26  # :926 <= 26

# --- ATTEST cadence (:927). Invariant: PERIOD + L_max + MARGIN <= VALIDITY, where
# L_max = INTRADAY_ATTEST_VERDICT_PERIOD_MIN (<= 60) + the 150 s engine offset.
ATTEST_PERIOD_H: Final = 6  # <= 6
ATTEST_VERDICT_VALIDITY_H: Final = 8  # <= 8
ATTEST_MARGIN_H: Final = "0.5"  # >= 0.5
INTRADAY_ATTEST_VERDICT_PERIOD_MIN: Final = 60  # <= 60
INTRADAY_ENGINE_OFFSET_S: Final = 150  # :927 "the 150 s engine offset"

# --- Windows and reconciliation (:928-929).
FORWARD_WINDOW_DAYS_MIN: Final = 28  # :928 28 <= value
FORWARD_WINDOW_DAYS_MAX: Final = 120  # :928 value <= 120
POST_STOP_RECONCILE_RUNTIME_S: Final = 120  # :929 <= 120
POSTSTOP_POSITIONS_MAX_PAGES: Final = 20  # :929 <= 20
ROOT_ADMIT_COOLDOWN_H: Final = 24  # :930 >= 24

# --- Alerts (:931). ALERT_CLAIM_STALE_S >= 3 x ALERT_DELIVERY_TIMEOUT_S.
ALERT_DELIVERY_TIMEOUT_S: Final = 10  # <= 10
ALERT_OUTBOX_MAX: Final = 256  # <= 256 files
ALERT_OUTBOX_STALE_S: Final = 300  # <= 300
ALERT_CLAIM_STALE_S: Final = 30  # >= 3 x 10
HALT_MIRROR_MAX_AGE_S: Final = 180  # :932 <= 180
CANARY_RETRY_PERIOD_MIN: Final = 60  # :933 <= 60
# Pre-registered suppression-drill dates (UTC ISO dates, plan r15 section 3.7.1). EMPTY on purpose:
# ruling r3 item 4 (AUT-6-WP2-pathB-ruling_2026-10-08.md) withdrew the sender-armed dead-man after
# the live ntfy.sh check failed, so the drill has no receiver-side absence rule to prove and no
# date is registered until the off-host endpoint exists. The drill code is built and inert while
# this set is empty. Adding a date is a reviewed pins change made before that date, never on it.
CANARY_SUPPRESSION_DRILL_DATES: Final[frozenset[str]] = frozenset()
ENGINE_HEARTBEAT_STALE_S: Final = 3600  # :934 <= 3600
WATCH_TICK_STALE_S: Final = 180  # :935 <= 180 (3 x the 60 s tick)
ALERT_CANARY_MAX_AGE_H: Final = 26  # :936 <= 26

# --- Demand files (:937).
DEMAND_FILE_MAX_BYTES: Final = 4096  # <= 4096
DEMAND_FILES_MAX: Final = 64  # <= 64 per venue
DEMAND_INTEGRITY_RESERVED: Final = 8  # >= 8 of those
DEMAND_WRITER_PRODUCER_IDS: Final = ("aut6.intraday",)  # AC 25; ARCH:922
# Closed choice (plan r5 Unknown 4): AUT-6 supplies `integrity_floor` (r15:1477); widened only by
# a reviewed change.
DEMAND_REASONS: Final = frozenset({"integrity_floor"})

# --- Engine and watch timings (AC 25; AUT-5 r7 :112).
ENGINE_LOCK_MAX_HOLD_S: Final = 15
WATCH_BUSY_TIMEOUT_MS: Final = 250
ROW_TS_MAX_SKEW_S: Final = 300
EXPORT_FIRST_DUE_H: Final = 26
DRAWDOWN_INERT_ALERT_CEILING: Final = "0.5"  # AC 25; signal only, never a policy key
DRAWDOWN_INERT_ALERT_MIN_FILLS: Final = 10  # AC 25

# --- Roots (E-14 rules 2 and 7).
ROOT_ARTEFACT_COMPONENT: Final = "density_table"
# The closed set of model-class components an artefact may live under (A8b-R2; E-22 d). A model
# class is "<composition_kind>:<component>". The two components are AUT-3 r6 section 3.1's table
# (`forecast_quantile_ladder:density_table` and `:rung_recalibration`); the root component is the
# first. Replay probes exactly these and requires one match.
MODEL_CLASS_COMPONENTS: Final = ("density_table", "rung_recalibration")
# Cap on one artefact.json read by the replay (A8b-R5 L3).
ARTEFACT_MAX_BYTES: Final = 67_108_864  # 64 MiB
# Empty until the reviewed pins commit that precedes the first bootstrap (rows are append-only).
BOOTSTRAPPED_ROOT_MANIFEST_SHA256: Final[MappingProxyType[str, str]] = MappingProxyType({})

# --- Bootstrap seed (ARCH:472, :737): CHAMPION fq_v1; RETIRED v4, cont, v2 (never HALTED).
BOOTSTRAP_SEED: Final = (
    ("pm_us_crh_fq_v1", "CHAMPION"),
    ("pm_us_crh_v4", "RETIRED"),
    ("pm_us_crh_cont", "RETIRED"),
    ("pm_us_crh_v2", "RETIRED"),
)

# --- Schedule, UTC "HH:MM"; test-equal to runtime/trade_supervisor_core.py:37-44 (V6).
SCHEDULE_STOP_UTC: Final = "16:40"  # STOP_PRIOR_UTC
SCHEDULE_LAUNCH_UTC: Final = "16:50"  # LAUNCH_UTC
SCHEDULE_LAUNCH_WINDOW_END_UTC: Final = "17:00"  # LAUNCH_WINDOW_END_UTC

# --- Cause codes: closed choice (plan r5 Unknown 4; initial set from plan r1:320, ARCH names
# rollback_failed and target_integrity at :486, :505); widened only by a reviewed change.
CAUSE_CODES: Final = frozenset(
    {
        "verdict_fail",
        "exec_store_halt_mirror",
        "pair_cause_incoming",
        "pair_cause_outgoing",
        "prelaunch_precheck_failed",
        "engine_inconsistency",
        "infra_budget_exhausted",
        "model_budget_exhausted",
        "rollback_failed",
        "target_integrity",
        "drill_close_restore",
    }
)

# --- Exec-store halt mirror (ARCH C5 table :699-706): reason -> cause class (None: no effect).
HALT_REASON_CLASS_MAP: Final = MappingProxyType(
    {
        "duplicate_fill": "INTEGRITY",
        "ambiguous_exit": "INTEGRITY",
        "halts_all": "INTEGRITY",
        "attributable_to_v4": None,
        "policy_halt:fee_schedule_drift": "TERMINAL",
        "policy_halt:*": "TERMINAL",
        "unreadable_or_unknown": "INTEGRITY",
    }
)

# --- No-policy restrictive fallback (ARCH:372; AUT-5 r7 :224): detector -> (action, cause class).
# DRILL_INJECT and DRILL_INJECT_HALT are deliberately absent.
DEFAULT_RESTRICTIVE_CLASS: Final = MappingProxyType(
    {
        "freshness.persist": ("DEMOTE", "RECOVERABLE_INFRA"),
        "liveness.permit_process": ("DEMOTE", "RECOVERABLE_INFRA"),
        "health.capture_join": ("DEMOTE", "RECOVERABLE_INFRA"),
        "health.alert_canary": ("DEMOTE", "RECOVERABLE_INFRA"),
        "reconciliation.net_position": ("DEMOTE", "RECOVERABLE_INFRA"),
        "reconciliation.post_stop": ("DEMOTE", "RECOVERABLE_INFRA"),
        "drift.forecast_input": ("DEMOTE", "RECOVERABLE_MODEL"),
        "drift.calibration_live": ("DEMOTE", "RECOVERABLE_MODEL"),
        "drift.fill_rate_slippage": ("DEMOTE", "RECOVERABLE_MODEL"),
        "parity.train_serve": ("DEMOTE", "RECOVERABLE_MODEL"),
        "live.sequential": ("HALT", "RECOVERABLE_MODEL"),
        "live.kill_clock": ("HALT", "TERMINAL"),
        "live.drawdown": ("HALT", "TERMINAL"),
    }
)
