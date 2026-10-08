"""AUT-6 WP5: the detector catalogue (plan r15 sections 3.2 and 3.3; ARCH C6, C4).

``CATALOG`` is the code proposal for the ruling's ``detector_action_map``. The plan's section 3.2
table is transcribed here as an independent literal (row number -> expected facts), so a wrong
cell in the catalogue fails against this copy and not against itself.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from breezy.analysis.autonomy.metric_registry import ASSUMPTION_TAGS
from breezy.persistence.autonomy import detector_catalog as dc
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.veto import VetoReason

_CATALOG_PATH: Final = Path(dc.__file__)

#: Plan 3.2 "Action-class coverage", transcribed (11p and 12p are the DEMOTE persistence rows).
_ACTION_COVERAGE: Final[dict[str, frozenset[str]]] = {
    "ENTRY_VETO": frozenset({"1", "2", "3", "4", "5"}),
    "ALERT": frozenset(
        {"6", "7", "9", "11", "12", "14", "16", "18", "19", "20"} | {str(n) for n in range(22, 33)}
    ),
    "SELF_HEAL": frozenset({"21"}),
    "DEMOTE": frozenset({"8", "10", "11p", "12p", "13"}),
    "HALT": frozenset({"8h", "15", "17"}),
}

#: Plan 3.2 "Required-class coverage (C6)", transcribed.
_CLASS_COVERAGE: Final[dict[str, frozenset[str]]] = {
    "freshness": frozenset({"1", "2", "3", "7"}),
    "forecast_drift": frozenset({"9", "10", "11", "16"}),
    "calibration_drift": frozenset({"12", "13"}),
    "fill_slippage": frozenset({"14", "15"}),
    "fee_shape": frozenset({"17", "18", "19", "32"}),
    "liveness": frozenset({"4", "6", "26", "29", "30"}),
    "unit_health": frozenset({"5", "21", "22", "23", "24", "25", "27", "28", "31"}),
}

_ALL_NUMS: Final = frozenset({str(n) for n in range(1, 33)} | {"8h", "11p", "12p"})


def _by_num() -> dict[str, dc.DetectorRow]:
    return {row.num: row for row in dc.CATALOG}


def _verdict_rows() -> tuple[dc.DetectorRow, ...]:
    return tuple(row for row in dc.CATALOG if row.kind == "VERDICT")


# --------------------------------------------------------------------------- shape


def test_catalog_is_literal_only() -> None:
    tree = ast.parse(_CATALOG_PATH.read_text(encoding="utf-8"))
    value = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "CATALOG"
    )
    assert isinstance(value, ast.Tuple)
    for node in ast.walk(value):
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name) and node.func.id == "DetectorRow", ast.dump(node)
            assert all(isinstance(a, ast.Constant | ast.Tuple) for a in node.args)
            assert all(isinstance(k.value, ast.Constant | ast.Tuple) for k in node.keywords)
        else:
            assert isinstance(node, ast.Tuple | ast.Constant | ast.Load | ast.keyword | ast.Name), (
                ast.dump(node)
            )
    assert len(dc.CATALOG) == 35
    assert frozenset(row.num for row in dc.CATALOG) == _ALL_NUMS
    ids = [row.id for row in dc.CATALOG]
    assert len(set(ids)) == len(ids)


def test_every_live_kind_covers_required_detector_classes() -> None:
    assert pins.LIVE_GATE_ROUTED_KINDS == frozenset({"forecast_quantile_ladder"})
    assert frozenset(_CLASS_COVERAGE) == dc.REQUIRED_DETECTOR_CLASSES
    by_num = _by_num()
    for cls, nums in _CLASS_COVERAGE.items():
        assert {n for n in nums if by_num[n].required_class != cls} == set(), cls
    # removing the last detector of a class must fail: every class has at least one row
    for cls in dc.REQUIRED_DETECTOR_CLASSES:
        assert any(row.required_class == cls for row in dc.CATALOG), cls


def test_node_local_ids_are_entry_veto_only() -> None:
    node_local = [row for row in dc.CATALOG if row.kind == "NODE_LOCAL"]
    assert {row.num for row in node_local} == {"1", "2", "3", "4", "5"}
    veto_values = {reason.value for reason in VetoReason}
    for row in node_local:
        assert row.action == "ENTRY_VETO", row.id
        assert row.id in veto_values, row.id
        assert row.c4_kind == ""
    # and no other row may use ENTRY_VETO or a veto id
    assert {row.num for row in dc.CATALOG if row.action == "ENTRY_VETO"} == {
        row.num for row in node_local
    }
    assert {row.id for row in dc.CATALOG if row.id in veto_values} == {row.id for row in node_local}


def test_policy_detector_map_covers_catalog_exactly() -> None:
    if pins.POLICY_RULING_PIN == ():
        pytest.skip(f"AUT6_EXPECTED_SKIP:{dc.AUT6_EXPECTED_SKIPS[0]}")
    pytest.fail(  # pragma: no cover - fires when the ruling lands
        "an autonomy-policy/v1 block is pinned: compare its detector_action_map with "
        "CATALOG's VERDICT ids and classes through AUT-5's loader, then drop the expected skip"
    )


def test_aut6_expected_skips_are_exact_and_bounded() -> None:
    assert dc.AUT6_EXPECTED_SKIPS == ("policy_map_pending_AUT-5b",)
    # the skip self-expires: once a policy ruling is pinned the allowance must be empty
    assert pins.POLICY_RULING_PIN == (), "ruling landed: AUT6_EXPECTED_SKIPS must be ()"


def test_every_action_class_has_at_least_one_detector() -> None:
    by_action: dict[str, set[str]] = {}
    for row in dc.CATALOG:
        by_action.setdefault(row.action, set()).add(row.num)
    assert {k: frozenset(v) for k, v in by_action.items()} == _ACTION_COVERAGE
    assert frozenset(by_action) == dc.ACTION_CLASSES


def test_every_detector_has_a_severity() -> None:
    for row in dc.CATALOG:
        assert row.severity in {"WARN", "CRITICAL"}, row.id
        assert row.hx in {"Y", "N", "n/a"}, row.id
    by_num = _by_num()
    assert by_num["24"].critical_from == by_num["31"].critical_from == "2026-10-16"
    assert [row.num for row in dc.CATALOG if row.critical_from] == ["24", "31"]


def test_integrity_rows_have_halt_floor() -> None:
    integrity = [row for row in dc.CATALOG if row.cause == "INTEGRITY"]
    assert [row.num for row in integrity] == ["15"]
    assert all(row.floor == "HALT" and row.action == "HALT" for row in integrity)
    # a floor is only ever declared on an INTEGRITY row
    assert [row.num for row in dc.CATALOG if row.floor] == ["15"]


def test_catalog_contains_drill_ids_and_fee_schedule() -> None:
    ids = {row.id for row in dc.CATALOG}
    assert {"DRILL_INJECT", "DRILL_INJECT_HALT", "fee_schedule"} <= ids
    by_num = _by_num()
    assert by_num["8"].action == "DEMOTE" and by_num["8h"].action == "HALT"
    assert by_num["8"].cause == by_num["8h"].cause == "DRILL"
    assert by_num["32"].id == "fee_schedule" and by_num["32"].c4_kind == "DRIFT"
    # the 3 added ids and the VERDICT set the ruling must list
    assert {"11p", "12p", "8h"} <= set(by_num)
    assert len(_verdict_rows()) == 29


def test_halt_live_proof_class_is_drill_only() -> None:
    halts = {row.num: row for row in dc.CATALOG if row.action == "HALT"}
    assert set(halts) == {"8h", "15", "17"}
    assert halts["8h"].live_proof == "D"
    assert halts["15"].live_proof == halts["17"].live_proof == "G"
    # no natural-proof HALT, and no other row is drill-proven
    assert all(row.live_proof != "N" for row in halts.values())
    assert {row.num for row in dc.CATALOG if row.live_proof == "D"} == {"8", "8h"}
    assert {row.num for row in dc.CATALOG if row.live_proof == "G"} == {"15", "17"}


# --------------------------------------------------------------------------- no-policy fallback


def test_default_restrictive_class_proposal_rows_exact() -> None:
    assert dict(dc.AUT6_DEFAULT_RESTRICTIVE_CLASS_PROPOSAL) == {
        "aut6.fill_better_than_ask": ("HALT", "INTEGRITY"),
        "aut6.forecast_drift_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
        "aut6.feature_drift_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
        "aut6.calibration_drift_offline_persistent": ("DEMOTE", "RECOVERABLE_MODEL"),
        "aut6.calibration_drift_live": ("DEMOTE", "RECOVERABLE_MODEL"),
    }
    by_id = {row.id: row for row in dc.CATALOG}
    for detector, (action, _cause) in dc.AUT6_DEFAULT_RESTRICTIVE_CLASS_PROPOSAL.items():
        assert by_id[detector].action == action, detector
    # drill ids act only under the drill clause: never a default row
    assert not {"DRILL_INJECT", "DRILL_INJECT_HALT"} & set(
        dc.AUT6_DEFAULT_RESTRICTIVE_CLASS_PROPOSAL
    )


def test_no_policy_verdict_stamps_no_policy_ruling_and_default_restrictive_class() -> None:
    demote = dc.declare_without_ruling("aut6.calibration_drift_live")
    assert demote.policy_ruling_sha256 is None
    assert demote.assumptions == ("no_policy_ruling",)
    assert demote.declared_action_class == "DEMOTE"
    # a detector with no default row declares ALERT
    alert = dc.declare_without_ruling("aut6.unit_health_unhealable")
    assert (alert.declared_action_class, alert.assumptions) == ("ALERT", ("no_policy_ruling",))
    # a drill verdict carries the drill assumption and never a restrictive class
    drill = dc.declare_without_ruling("DRILL_INJECT_HALT")
    assert drill.declared_action_class == "ALERT"
    assert drill.assumptions == ("no_policy_ruling", "drill")
    # node-local ids are code-fixed ENTRY_VETO and never get a declared class
    with pytest.raises(ValueError, match="feed_stale"):
        dc.declare_without_ruling("feed_stale")
    with pytest.raises(ValueError, match="not_a_detector"):
        dc.declare_without_ruling("not_a_detector")


def test_no_policy_integrity_verdict_declares_halt() -> None:
    declared = dc.declare_without_ruling("aut6.fill_better_than_ask")
    assert declared.declared_action_class == "HALT"
    assert declared.floor_action_class == "HALT"
    assert declared.policy_ruling_sha256 is None
    # the floor is a code literal: it holds even if the default-row proposal were empty
    assert (
        dc.declare_without_ruling(
            "aut6.fill_better_than_ask", default_rows={}
        ).declared_action_class
        == "HALT"
    )


def test_aut6_assumptions_use_closed_c4_enum_only() -> None:
    seen: set[str] = set()
    for row in _verdict_rows():
        declared = dc.declare_without_ruling(row.id)
        seen.update(declared.assumptions)
        with_ruling = dc.declare_with_ruling(row.id, "ALERT", "a" * 64)
        seen.update(with_ruling.assumptions)
        assert with_ruling.policy_ruling_sha256 == "a" * 64
        assert ("drill" in with_ruling.assumptions) == (row.cause == "DRILL")
    assert seen <= ASSUMPTION_TAGS
    assert not seen & {"policy_unavailable", "input_unreadable"}
    assert seen == {"no_policy_ruling", "drill"}


def test_exec_snapshot_streak_is_three_and_unknown_streaks_are_declared() -> None:
    assert dc.EXEC_SNAPSHOT_UNKNOWN_STREAK_MAX == 3
    by_num = _by_num()
    assert by_num["15"].unknown_streak_max == 72
    assert all(row.unknown_streak_max == 0 for row in dc.CATALOG if row.kind != "VERDICT")
    assert all(row.unknown_streak_max >= 1 for row in _verdict_rows())
    daily = {row.unknown_streak_max for row in dc.CATALOG if row.cadence == "daily"}
    assert daily == {1}
