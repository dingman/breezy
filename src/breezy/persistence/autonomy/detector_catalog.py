"""AUT-6 catalogue literals for the read-only closure lint and the bwrap self-probe.

Plan r15 section 3.1 (E-7 rules 3 and 4, E-7a rule 4), section 3.1.1 and the r10/r11 allowlist
rules: a literal ``AUT6_WRITE_AUTHORITY`` (one row per AUT-6 entry point: the only places it may
write, as paths under ``~/.local/share/breezy/``, and the process calls it may make), the lint's
per-entry-point floor, the self-probe paths, the rollback-journal stores and the read allowlist.
``tests/unit/test_autonomy_readonly_closure.py`` judges each entry point's import closure against
them. A bwrap row (``AUTONOMY_BWRAP_TABLE``) enforces the write scope at the OS level; these
literals are the defence-in-depth lint's input and are never described as enforced for the
unwrapped lines (E-7a rule 5).

Data only, plus ``declare_with_ruling`` and ``declare_without_ruling`` (WP5), which are pure
functions over the literal catalogue and do no I/O. Process calls name no in-sandbox ``systemctl``
read: those arrive through the bus snapshot pre-line (E-7e(h)). Later work packages add their own
rows beside these.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NamedTuple


class AuthorityRow(NamedTuple):
    """What one entry point may write and which process calls it may make."""

    writes: tuple[str, ...]
    process_calls: tuple[str, ...] = ()


class SelfProbe(NamedTuple):
    """One row's self-probe paths, relative to the data root (section 3.1.1, AE3).

    ``negative`` directories must refuse a create with exactly ``EROFS``; ``positive`` directories
    must accept a create and an unlink. The probe file is ``.aut6_bwrap_probe_<invocation_id>``.
    """

    negative: tuple[str, ...]
    positive: tuple[str, ...]


_ALERTS: Final = "evidence/alerts/**"
_PROBE_FILE: Final = ".aut6_bwrap_probe_*"

AUT6_SELF_PROBE_PATHS: Final[MappingProxyType[str, SelfProbe]] = MappingProxyType(
    {
        # derived from AUTONOMY_BWRAP_TABLE["breezy-autonomy-alert-redeliver"]: the bind is
        # evidence/alerts, so state/, registry/ and its unbound parent evidence/ must refuse.
        "breezy-autonomy-alert-redeliver": SelfProbe(
            negative=("state", "registry", "evidence"),
            positive=("evidence/alerts/.bwrap_probe",),
        ),
        # AUT-6 WP2: the canary row binds the same single directory as the redeliver row.
        "breezy-autonomy-canary": SelfProbe(
            negative=("state", "registry", "evidence"),
            positive=("evidence/alerts/.bwrap_probe",),
        ),
    }
)

AUT6_WRITE_AUTHORITY: Final[MappingProxyType[str, AuthorityRow]] = MappingProxyType(
    {
        "breezy-autonomy-producer-intraday#evaluate": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_intraday_exec_snapshot/")
        ),
        "breezy-autonomy-producer-intraday#demand": AuthorityRow(
            ("registry/demand/<venue>/", _ALERTS)
        ),
        "breezy-autonomy-producer-daily": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_daily_exec_snapshot/")
        ),
        "breezy-autonomy-health": AuthorityRow(
            ("evidence/unit_health/**", "derived/verdicts/**", _ALERTS)
        ),
        "breezy-autonomy-alert-redeliver": AuthorityRow((_ALERTS,)),
        "breezy-autonomy-canary": AuthorityRow((_ALERTS,)),
        "breezy-check-alerts": AuthorityRow((_ALERTS,)),
        "node-sinks": AuthorityRow((_ALERTS,)),
        # the shared self-probe code: only the probe files named in AUT6_SELF_PROBE_PATHS
        "bwrap-self-probe": AuthorityRow(
            tuple(
                dict.fromkeys(  # rows share their negatives: one authority entry per path
                    rel + "/" + _PROBE_FILE
                    for probe in AUT6_SELF_PROBE_PATHS.values()
                    for rel in (*probe.negative, *probe.positive)
                )
            )
        ),
        "breezy-autonomy-failed@": AuthorityRow((_ALERTS,)),
    }
)

#: Minimum call sites each entry point's closure must hold, so a lint that judges nothing cannot
#: pass (the M2 floor). The test sums the real call counts of the entry point's modules.
AUT6_LINT_MIN_JUDGED_SITES: Final[MappingProxyType[str, int]] = MappingProxyType(
    {
        "breezy-autonomy-alert-redeliver": 170,
        "breezy-autonomy-canary": 180,
        "breezy-check-alerts": 140,
        "node-sinks": 110,
    }
)

#: Stores whose connections are rollback-journal (not WAL), so AUT-6 may open them in place.
#: None at WP1: AUT-6 opens no SQLite store here.
AUT6_ROLLBACK_JOURNAL_STORES: Final[frozenset[str]] = frozenset()

#: The dotted calls a NON-writer closure may make from the I/O modules (r10, AC6). Any other call
#: rooted in ``os``, ``shutil``, ``tempfile``, ``subprocess``, ``sqlite3``, ``fcntl``, ``socket``,
#: ``ctypes`` or ``importlib`` fails. ``open`` and ``os.open`` are further limited to read forms.
AUT6_READ_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "open",
        "os.open",
        "os.read",
        "os.close",
        "os.fsync",
        "os.stat",
        "os.lstat",
        "os.fstat",
        "os.path.lexists",
        "os.path.exists",
        "os.path.join",
        "fcntl.flock",
    }
)

#: Builtins a closure may call without an allowlist entry; ``print`` is stdout only.
AUT6_PURE_BUILTINS: Final[frozenset[str]] = frozenset(
    {
        "abs", "all", "any", "bool", "bytes", "callable", "dict", "enumerate", "float",
        "frozenset", "getattr", "hasattr", "id", "int", "isinstance", "iter", "len", "list", "max",
        "memoryview", "min", "next", "object", "print", "range", "repr", "reversed", "set",
        "sorted", "str", "sum", "super", "tuple", "type", "zip",
    }
)  # fmt: skip


# --- WP5: the detector catalogue (plan r15 section 3.2; ARCH C6). Literal-only.


class DetectorRow(NamedTuple):
    """One catalogue row: the plan's section 3.2 table, one cell per field.

    ``kind`` is ``NODE_LOCAL`` (code-fixed ENTRY_VETO), ``VERDICT`` (a C4 verdict whose action
    class comes from the policy map) or ``IN_NODE_EXEC_HALT`` (#17, mirrored by the engine's fixed
    table). ``c4_kind`` is the C4 verdict kind of a VERDICT row, else ``""``. ``action`` is the
    proposed action. ``floor`` is the INTEGRITY floor, ``HALT`` or ``""``. ``hx`` is the
    halted-by-design exemption. ``live_proof`` is ``N`` natural, ``D`` drill or ``G`` gate-proven.
    ``unknown_streak_max`` is the consecutive-UNKNOWN passes before #25 fires (0: not a VERDICT).
    """

    num: str
    id: str
    required_class: str
    kind: str
    c4_kind: str
    cadence: str
    action: str
    floor: str
    severity: str
    hx: str
    cause: str
    escalates_to: tuple[str, ...]
    live_proof: str
    unknown_streak_max: int
    critical_from: str = ""


#: The seven required detector classes (ARCH C6): removing the last row of one fails the gate.
REQUIRED_DETECTOR_CLASSES: Final = frozenset(
    {
        "freshness",
        "forecast_drift",
        "calibration_drift",
        "fill_slippage",
        "fee_shape",
        "liveness",
        "unit_health",
    }
)

#: Every action class a row may propose.
ACTION_CLASSES: Final = frozenset({"ENTRY_VETO", "ALERT", "SELF_HEAL", "DEMOTE", "HALT"})

#: Consecutive intraday passes with an unsettled exec-store snapshot before #25 fires (r12, AF3),
#: in place of the detector's catalogue value of 2.
EXEC_SNAPSHOT_UNKNOWN_STREAK_MAX: Final = 3

#: The one expected skip (H16): ``test_policy_detector_map_covers_catalog_exactly`` may skip only
#: with ``AUT6_EXPECTED_SKIP:<this>`` while no ``autonomy-policy/v1`` block is pinned.
AUT6_EXPECTED_SKIPS: Final = ("policy_map_pending_AUT-5b",)

#: AUT-6's proposal for the no-policy restrictive fallback (plan 3.3.1): detector id ->
#: (action, cause class). AUT-5 owns ``pins.DEFAULT_RESTRICTIVE_CLASS``; the two are reconciled
#: there (its keys are still the r7 class names). The drill ids never appear: they act only under
#: the drill clause.
AUT6_DEFAULT_RESTRICTIVE_CLASS_PROPOSAL: Final[MappingProxyType[str, tuple[str, str]]] = (
    MappingProxyType(
        {
            "aut6.fill_better_than_ask": ("HALT", "INTEGRITY"),
            "aut6.forecast_drift_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
            "aut6.feature_drift_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
            "aut6.calibration_drift_offline_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
            "aut6.calibration_drift_live": ("DEMOTE", "RECOVERABLE_MODEL"),
        }
    )
)

# Field order: num, id, required_class, kind, c4_kind, cadence, action, floor, severity, hx, cause,
# escalates_to, live_proof, unknown_streak_max[, critical_from].
# fmt: off
CATALOG: Final[tuple[DetectorRow, ...]] = (
    DetectorRow("1", "feed_stale", "freshness", "NODE_LOCAL", "", "node", "ENTRY_VETO", "",
                "WARN", "n/a", "INFRA", ("aut6.transient_veto_persistent",), "N", 0),
    DetectorRow("2", "recorder_stale", "freshness", "NODE_LOCAL", "", "node", "ENTRY_VETO", "",
                "WARN", "n/a", "INFRA", ("aut6.transient_veto_persistent", "aut6.unit_health"),
                "N", 0),
    DetectorRow("3", "capture_gap", "freshness", "NODE_LOCAL", "", "node", "ENTRY_VETO", "",
                "WARN", "n/a", "INFRA", ("aut6.transient_veto_persistent",), "N", 0),
    # severity CRITICAL is window-gated: PermitLapsedDetector pages only inside [17:10Z, 01:00Z).
    DetectorRow("4", "permit_lapsed", "liveness", "NODE_LOCAL", "", "node", "ENTRY_VETO", "",
                "CRITICAL", "n/a", "INFRA", ("aut6.node_liveness",), "N", 0),
    DetectorRow("5", "alerts_undeliverable", "unit_health", "NODE_LOCAL", "", "node",
                "ENTRY_VETO", "", "CRITICAL", "n/a", "INFRA", ("aut6.alert_delivery",), "N", 0),
    DetectorRow("6", "aut6.node_liveness", "liveness", "VERDICT", "HEALTH", "intraday", "ALERT",
                "", "CRITICAL", "Y", "INFRA", (), "N", 2),
    DetectorRow("7", "aut6.transient_veto_persistent", "freshness", "VERDICT", "HEALTH",
                "intraday", "ALERT", "", "CRITICAL", "Y", "INFRA", (), "N", 2),
    DetectorRow("8", "DRILL_INJECT", "drill", "VERDICT", "DRIFT", "intraday", "DEMOTE", "",
                "WARN", "N", "DRILL", (), "D", 2),
    DetectorRow("8h", "DRILL_INJECT_HALT", "drill", "VERDICT", "DRIFT", "intraday", "HALT", "",
                "WARN", "N", "DRILL", (), "D", 2),
    DetectorRow("9", "aut6.forecast_drift", "forecast_drift", "VERDICT", "DRIFT", "daily",
                "ALERT", "", "WARN", "N", "MODEL", ("aut6.forecast_drift_persistent",), "N", 1),
    DetectorRow("10", "aut6.forecast_drift_persistent", "forecast_drift", "VERDICT", "DRIFT",
                "daily", "DEMOTE", "", "CRITICAL", "N", "MODEL", (), "N", 1),
    DetectorRow("11", "aut6.feature_drift", "forecast_drift", "VERDICT", "DRIFT", "daily",
                "ALERT", "", "WARN", "N", "MODEL", ("aut6.feature_drift_persistent",), "N", 1),
    DetectorRow("11p", "aut6.feature_drift_persistent", "forecast_drift", "VERDICT", "DRIFT",
                "daily", "DEMOTE", "", "CRITICAL", "N", "MODEL", (), "N", 1),
    DetectorRow("12", "aut6.calibration_drift_offline", "calibration_drift", "VERDICT", "DRIFT",
                "daily", "ALERT", "", "WARN", "N", "MODEL",
                ("aut6.calibration_drift_offline_persistent",), "N", 1),
    DetectorRow("12p", "aut6.calibration_drift_offline_persistent", "calibration_drift",
                "VERDICT", "DRIFT", "daily", "DEMOTE", "", "CRITICAL", "N", "MODEL", (), "N", 1),
    DetectorRow("13", "aut6.calibration_drift_live", "calibration_drift", "VERDICT", "DRIFT",
                "daily", "DEMOTE", "", "CRITICAL", "N", "MODEL", (), "N", 1),
    DetectorRow("14", "aut6.fill_slippage_drift", "fill_slippage", "VERDICT", "DRIFT", "daily",
                "ALERT", "", "WARN", "Y", "MARKET", (), "N", 1),
    DetectorRow("15", "aut6.fill_better_than_ask", "fill_slippage", "VERDICT", "HEALTH",
                "intraday", "HALT", "HALT", "CRITICAL", "N", "INTEGRITY", (), "G", 72),
    DetectorRow("16", "aut6.shadow_parity", "forecast_drift", "VERDICT", "HEALTH", "daily",
                "ALERT", "", "CRITICAL", "N", "MODEL", (), "N", 1),
    DetectorRow("17", "fee_drift_probe", "fee_shape", "IN_NODE_EXEC_HALT", "", "node", "HALT", "",
                "CRITICAL", "n/a", "TERMINAL", (), "G", 0),
    DetectorRow("18", "aut6.fee_probe_health", "fee_shape", "VERDICT", "HEALTH", "intraday",
                "ALERT", "", "CRITICAL", "Y", "INFRA", (), "N", 2),
    DetectorRow("19", "aut6.shape_drift", "fee_shape", "VERDICT", "HEALTH", "intraday", "ALERT",
                "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("20", "aut6.decision_starvation", "decision_starvation", "VERDICT", "HEALTH",
                "daily", "ALERT", "", "CRITICAL", "Y", "MARKET", (), "N", 1),
    DetectorRow("21", "aut6.unit_health", "unit_health", "VERDICT", "HEALTH", "health",
                "SELF_HEAL", "", "CRITICAL", "N", "INFRA", ("aut6.unit_health_unhealable",),
                "N", 2),
    DetectorRow("22", "aut6.unit_health_unhealable", "unit_health", "VERDICT", "HEALTH", "health",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("23", "aut6.alert_delivery", "unit_health", "VERDICT", "HEALTH", "health",
                "ALERT", "", "CRITICAL", "N", "INFRA", ("alerts_undeliverable",), "N", 2),
    DetectorRow("24", "aut6.unit_config_drift", "unit_health", "VERDICT", "HEALTH", "daily",
                "ALERT", "", "WARN", "N", "INFRA", (), "N", 1, "2026-10-16"),
    DetectorRow("25", "aut6.detector_blind", "unit_health", "VERDICT", "HEALTH", "every_pass",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("26", "aut6.producer_stale", "liveness", "VERDICT", "HEALTH", "health", "ALERT",
                "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("27", "aut6.daily_verdict_absent", "unit_health", "VERDICT", "HEALTH", "health",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("28", "aut6.timer_liveness", "unit_health", "VERDICT", "HEALTH", "health",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("29", "aut6.health_monitor_stale", "liveness", "VERDICT", "HEALTH", "intraday",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("30", "aut6.halted_too_long", "liveness", "VERDICT", "HEALTH", "intraday",
                "ALERT", "", "CRITICAL", "N", "INFRA", (), "N", 2),
    DetectorRow("31", "aut6.memory_budget", "unit_health", "VERDICT", "HEALTH", "daily", "ALERT",
                "", "WARN", "N", "INFRA", (), "N", 1, "2026-10-16"),
    DetectorRow("32", "fee_schedule", "fee_shape", "VERDICT", "DRIFT", "intraday", "ALERT", "",
                "CRITICAL", "N", "TERMINAL", (), "N", 2),
)
# fmt: on


# --- WP5: what a VERDICT declares as its action class (plan r15 sections 3.3.1 and 3.3.3).
# With a verified ruling the class comes from the ruling's ``detector_action_map``. Without one the
# verdict carries ``policy_ruling_sha256=None``, the closed-enum assumption ``no_policy_ruling`` and
# a restrictive fallback: the default-row proposal above if the detector has one, else ``ALERT``. An
# INTEGRITY row's ``HALT`` floor is a code literal and holds whether or not any policy is readable.

#: Least to most restrictive. A floor or a default row can only raise the declared class.
_RESTRICTIVENESS: Final = {"ALERT": 0, "SELF_HEAL": 0, "DEMOTE": 1, "HALT": 2}


class DeclaredClass(NamedTuple):
    """The verdict columns a detector's class decides, plus the INTEGRITY floor."""

    declared_action_class: str
    policy_ruling_sha256: str | None
    assumptions: tuple[str, ...]
    floor_action_class: str


def verdict_row(detector_id: str) -> DetectorRow:
    """The catalogue row of a VERDICT detector; anything else is a caller error."""
    for row in CATALOG:
        if row.id == detector_id:
            if row.kind != "VERDICT":
                raise ValueError(f"{detector_id}: a {row.kind} detector declares no action class")
            return row
    raise ValueError(f"{detector_id}: not in the AUT-6 catalogue")


def _assumptions(row: DetectorRow, *, ruling: bool) -> tuple[str, ...]:
    tags = () if ruling else ("no_policy_ruling",)
    return (*tags, "drill") if row.cause == "DRILL" else tags


def _at_least(action: str, floor: str) -> str:
    if floor and _RESTRICTIVENESS[floor] > _RESTRICTIVENESS[action]:
        return floor
    return action


def declare_with_ruling(detector_id: str, ruled_class: str, ruling_sha256: str) -> DeclaredClass:
    """The class the verified ruling maps the detector to, raised to the floor."""
    row = verdict_row(detector_id)
    declared = _at_least(ruled_class, row.floor)
    return DeclaredClass(declared, ruling_sha256, _assumptions(row, ruling=True), row.floor)


def declare_without_ruling(
    detector_id: str,
    *,
    default_rows: Mapping[str, tuple[str, str]] = AUT6_DEFAULT_RESTRICTIVE_CLASS_PROPOSAL,
) -> DeclaredClass:
    """The no-policy fallback: ``no_policy_ruling``, the default row's class or ``ALERT``."""
    row = verdict_row(detector_id)
    proposed = default_rows.get(detector_id, ("ALERT", ""))[0]
    return DeclaredClass(
        _at_least(proposed, row.floor), None, _assumptions(row, ruling=False), row.floor
    )
