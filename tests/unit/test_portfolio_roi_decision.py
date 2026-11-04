"""AUD-04 ROI decision accessor. Every report is the production writer's bytes."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.accounting import Disclosures
from breezy.persistence.autonomy.label_store import MARKER_STALE_H
from tests.support.portfolio_roi_loader import load_portfolio_roi_report

_prr = load_portfolio_roi_report()

_NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
_NOW_NS = int(_NOW.timestamp()) * 1_000_000_000
_V6_KEYS = (
    "generated_at",
    "days_since_newest_input",
    "input_freshness_status",
    "n_open_anchors_without_fill",
    "label_gate_status",
    "family_decision_stats",
)
_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "breezy"
    / "persistence"
    / "portfolio_roi_decision.py"
)


def _decision() -> Any:
    import breezy.persistence.portfolio_roi_decision as decision

    return decision


def _clean_row(**over: Any) -> Any:
    decision = _decision()
    base: dict[str, Any] = {
        "family_id": "fam_b",
        "n_admissible": 1,
        "net_pnl": Decimal("1.25"),
        "n_incomplete": 0,
        "n_fee_unverified": 0,
        "n_settlement_disagree": 0,
        "n_residual": 0,
        "n_residual_pending": 0,
        "residual_pnl": Decimal("0.50"),
        "n_residual_fee_unverified": 0,
        "n_residual_settlement_disagree": 0,
        "n_fills_attributed": 1,
        "n_other_excluded": 0,
    }
    base.update(over)
    return decision.FamilyDecisionStats(**base)


def _write(
    tmp_path: Path,
    *,
    rows: tuple[Any, ...] = (),
    days: int | None = 1,
    anchors: int | None = 0,
    label_gate_status: str | None = None,
    roi_status: str | None = None,
    settled_through: str = "2026-10-27",
    disclosures: Disclosures | None = None,
    generated_at_ns: int = _NOW_NS,
) -> Path:
    cumulative = _prr.cumulative_reconciliation(daily_rows=(), settled_through=settled_through)
    baselines = _prr.roi_against_baselines(
        total_realised_pnl=Decimal(0), total_capital_deployed=Decimal(0), fills=[]
    )
    data = _prr.build_portfolio_roi_report_data(
        period_start="2026-10-01",
        period_end="2026-11-04",
        fill_buckets={},
        total_realised_pnl=Decimal(0),
        total_capital_deployed=Decimal(0),
        baselines=baselines,
        cumulative=cumulative,
        settled_through_statistic="max",
        lag_sample_n=0,
        permanently_unsettled=(),
        disclosures=Disclosures() if disclosures is None else disclosures,
        generated_at_ns=generated_at_ns,
        label_gate_status=label_gate_status,
        days_since_newest_input=days,
        n_open_anchors_without_fill=anchors,
        family_decision_stats=rows,
        roi_status_override=roi_status,
    )
    path = tmp_path / "PRIVATE_portfolio_roi.json"
    _prr.write_portfolio_roi_json(path, data)
    return path


def _mutate(path: Path, edit: Any) -> None:
    raw = json.loads(path.read_text())
    edit(raw)
    path.write_text(json.dumps(raw))


def _read(path: Path, now: datetime = _NOW) -> Any:
    return _decision().read_roi_for_decision(path, now)


def _reason(result: Any) -> Any:
    return result.reason


class TestRoiDecisionAccessor:
    def test_a_fresh_ungated_v6_report_yields_a_decision_view(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),))

        view = _read(path)

        assert isinstance(view, decision.RoiDecisionView)
        assert view.schema_version == 6
        assert view.generated_at == _NOW
        assert view.settled_through == "2026-10-27"
        assert view.roi_status == _prr.ROI_STATUS_OK
        assert view.label_gate_status is None
        assert view.days_since_newest_input == 1
        assert view.input_freshness_status == decision.INPUT_FRESHNESS_OK
        assert view.n_open_anchors_without_fill == 0
        assert [row.family_id for row in view.family_stats] == ["fam_b"]
        assert view.family_refusals == ()
        assert view.for_family("fam_b").net_pnl == Decimal("1.25")

    def test_rewritten_v5_report_is_refused_with_schema_version(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),))

        def edit(raw: dict[str, Any]) -> None:
            raw["schema_version"] = 5
            for key in _V6_KEYS:
                raw.pop(key, None)

        _mutate(path, edit)
        result = _read(path)

        assert isinstance(result, decision.RoiDecisionRefusal)
        assert _reason(result) is decision.RoiDecisionRefusalReason.SCHEMA_VERSION

    @pytest.mark.parametrize("schema", [7, 999, "missing", True])
    def test_unknown_or_non_int_schema_version_is_refused(
        self, tmp_path: Path, schema: object
    ) -> None:
        decision = _decision()
        path = _write(tmp_path)

        def edit(raw: dict[str, Any]) -> None:
            if schema == "missing":
                raw.pop("schema_version")
            else:
                raw["schema_version"] = schema

        _mutate(path, edit)

        assert _reason(_read(path)) is decision.RoiDecisionRefusalReason.SCHEMA_VERSION

    @pytest.mark.parametrize("stamp", ["missing", "yesterday", "2026-11-04T12:00:00"])
    def test_missing_unparseable_or_naive_generated_at_is_refused(
        self, tmp_path: Path, stamp: str
    ) -> None:
        decision = _decision()
        path = _write(tmp_path)

        def edit(raw: dict[str, Any]) -> None:
            if stamp == "missing":
                raw.pop("generated_at")
            else:
                raw["generated_at"] = stamp

        _mutate(path, edit)

        assert _reason(_read(path)) is decision.RoiDecisionRefusalReason.GENERATED_AT_INVALID

    def test_age_boundary_accepts_26h_and_refuses_one_second_more(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),))
        generated = _NOW

        assert isinstance(_read(path, generated), decision.RoiDecisionView)
        assert isinstance(_read(path, generated + timedelta(hours=26)), decision.RoiDecisionView)
        stale = _read(path, generated + timedelta(hours=26, seconds=1))
        assert _reason(stale) is decision.RoiDecisionRefusalReason.REPORT_STALE

    def test_report_from_the_future_is_refused(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path)

        result = _read(path, _NOW - timedelta(seconds=1))

        assert _reason(result) is decision.RoiDecisionRefusalReason.REPORT_FROM_FUTURE

    def test_naive_now_raises_value_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path)

        with pytest.raises(ValueError):
            _read(path, datetime(2026, 11, 4, 12, 0))  # noqa: DTZ001 - intentional invalid caller

    @pytest.mark.parametrize(
        ("status", "labels", "expect"),
        [
            (None, 0, "serve"),
            ("GATED_UNSETTLED_CAPITAL", 0, "serve"),
            ("GATED_IDENTITY", 0, "refuse"),
            ("GATED_UNLABELLED_FQ", 0, "refuse"),
            (None, 2, "refuse"),
            ("GATED_OTHER", 0, "malformed"),
            ("missing", 0, "malformed"),
            (1, 0, "malformed"),
        ],
    )
    def test_label_gate_status_exact_set(
        self, tmp_path: Path, status: object, labels: int, expect: str
    ) -> None:
        decision = _decision()
        written = None if status == "missing" else status
        path = _write(
            tmp_path,
            rows=(_clean_row(),),
            label_gate_status=None if not isinstance(written, str) else written,
            disclosures=Disclosures(n_labels_gated=labels),
        )
        if status == "missing":
            _mutate(path, lambda raw: raw.pop("label_gate_status"))
        elif not isinstance(status, str) and status is not None:
            _mutate(path, lambda raw: raw.__setitem__("label_gate_status", status))

        result = _read(path)

        if expect == "serve":
            assert isinstance(result, decision.RoiDecisionView)
            assert result.label_gate_status == status
        elif expect == "refuse":
            assert _reason(result) is decision.RoiDecisionRefusalReason.LABELS_GATED
        else:
            assert _reason(result) is decision.RoiDecisionRefusalReason.MALFORMED

    @pytest.mark.parametrize(
        ("roi_status", "days", "anchors", "fee", "disagree"),
        [
            ("GATED_IDENTITY", 1, 0, 0, 0),
            ("GATED_ACCOUNTING_ONLY", 1, 0, 0, 0),
            ("GATED_UNSETTLED_CAPITAL", 1, 0, 0, 0),
            (None, 4, 0, 0, 0),
            (None, 4, 3, 0, 0),
            (None, 4, None, 0, 0),
            (None, None, None, 0, 0),
            (None, 1, 0, 4, 2),
        ],
    )
    def test_disclosure_only_inputs_still_serve(
        self,
        tmp_path: Path,
        roi_status: str | None,
        days: int | None,
        anchors: int | None,
        fee: int,
        disagree: int,
    ) -> None:
        decision = _decision()
        path = _write(
            tmp_path,
            rows=(_clean_row(),),
            days=days,
            anchors=anchors,
            roi_status=roi_status,
            label_gate_status="GATED_UNSETTLED_CAPITAL"
            if roi_status == "GATED_UNSETTLED_CAPITAL"
            else None,
            disclosures=Disclosures(n_fee_unverified=fee, n_settlement_disagree=disagree),
        )

        view = _read(path)

        assert isinstance(view, decision.RoiDecisionView)
        if roi_status is not None:
            assert view.roi_status == roi_status
        assert view.n_open_anchors_without_fill == anchors

    @pytest.mark.parametrize(
        ("field", "value", "reason_name"),
        [
            ("n_fee_unverified", 1, "FAMILY_FEE_UNVERIFIED"),
            ("n_settlement_disagree", 1, "FAMILY_SETTLEMENT_DISAGREE"),
            ("n_incomplete", 1, "FAMILY_INCOMPLETE"),
            ("n_other_excluded", -1, "FAMILY_PARTITION"),
        ],
    )
    def test_a_family_refusal_isolates_the_other_family(
        self, tmp_path: Path, field: str, value: int, reason_name: str
    ) -> None:
        decision = _decision()
        refused = _clean_row(family_id="fam_a", n_fills_attributed=2, **{field: value})
        served = _clean_row(family_id="fam_b")
        path = _write(tmp_path, rows=(refused, served))

        view = _read(path)

        assert isinstance(view, decision.RoiDecisionView)
        assert isinstance(view.for_family("fam_b"), decision.FamilyDecisionStats)
        refusal = view.for_family("fam_a")
        assert refusal.reason is decision.FamilyRefusalReason[reason_name]
        assert refusal.restrictive is not None
        assert refusal.restrictive.net_pnl == refused.net_pnl
        assert refusal.restrictive.n_residual == refused.n_residual
        assert refusal.restrictive.n_residual_pending == refused.n_residual_pending
        assert refusal.restrictive.residual_pnl == refused.residual_pnl
        assert refusal.restrictive.n_residual_fee_unverified == refused.n_residual_fee_unverified
        assert refusal.restrictive.n_residual_settlement_disagree == (
            refused.n_residual_settlement_disagree
        )

    def test_unknown_family_is_refused_and_the_others_are_served(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(
            tmp_path,
            rows=(_clean_row(family_id="UNKNOWN", n_admissible=1), _clean_row(family_id="fam_b")),
        )

        view = _read(path)

        unknown = view.for_family("UNKNOWN")
        assert unknown.reason is decision.FamilyRefusalReason.FAMILY_UNKNOWN
        assert unknown.restrictive is None
        assert isinstance(view.for_family("fam_b"), decision.FamilyDecisionStats)

    @pytest.mark.parametrize(
        "edit",
        [
            lambda row: row.__setitem__("n_admissible", -1),
            lambda row: row.__setitem__("n_admissible", True),
            lambda row: row.__setitem__("net_pnl", "NaN"),
            lambda row: row.__setitem__("net_pnl", "Infinity"),
            lambda row: row.__setitem__("net_pnl", "-Infinity"),
            lambda row: row.__setitem__("net_pnl", "sNaN"),
            lambda row: row.__setitem__("residual_pnl", "-0"),
            "duplicate",
            lambda raw: raw.__setitem__("n_open_anchors_without_fill", "1"),
            lambda raw: raw.__setitem__("n_open_anchors_without_fill", True),
            lambda raw: raw.__setitem__("n_open_anchors_without_fill", -1),
            lambda raw: raw.pop("n_open_anchors_without_fill"),
        ],
    )
    def test_malformed_rows_are_refused(self, tmp_path: Path, edit: Any) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),))

        def apply(raw: dict[str, Any]) -> None:
            if edit == "duplicate":
                raw["family_decision_stats"].append(dict(raw["family_decision_stats"][0]))
            elif edit.__code__.co_varnames[0] == "raw":
                edit(raw)
            else:
                edit(raw["family_decision_stats"][0])

        _mutate(path, apply)

        assert _reason(_read(path)) is decision.RoiDecisionRefusalReason.MALFORMED

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("disclosures", None),
            ("disclosures", "missing"),
            ("roi_status", None),
            ("roi_status", "missing"),
            ("input_freshness_status", None),
            ("input_freshness_status", "missing"),
        ],
    )
    def test_null_or_missing_header_fields_are_malformed(
        self, tmp_path: Path, key: str, value: object
    ) -> None:
        decision = _decision()
        path = _write(tmp_path)

        def edit(raw: dict[str, Any]) -> None:
            if value == "missing":
                raw.pop(key)
            else:
                raw[key] = value

        _mutate(path, edit)

        assert _reason(_read(path)) is decision.RoiDecisionRefusalReason.MALFORMED

    @pytest.mark.parametrize("body", ["missing", "{", "[]"])
    def test_missing_file_non_json_or_non_object_is_unreadable(
        self, tmp_path: Path, body: str
    ) -> None:
        decision = _decision()
        path = tmp_path / "absent.json"
        if body != "missing":
            path.write_text(body)

        assert _reason(_read(path)) is decision.RoiDecisionRefusalReason.UNREADABLE

    def test_absent_family_is_not_in_report(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),))

        missing = _read(path).for_family("no_such_family")

        assert missing.reason is decision.FamilyRefusalReason.NOT_IN_REPORT
        assert missing.restrictive is None

    def test_view_fields_are_exactly_the_specified_set(self, tmp_path: Path) -> None:
        decision = _decision()
        view = _read(_write(tmp_path, rows=(_clean_row(),)))
        names = {
            decision.FamilyDecisionStats: {
                "family_id",
                "n_admissible",
                "net_pnl",
                "n_incomplete",
                "n_fee_unverified",
                "n_settlement_disagree",
                "n_residual",
                "n_residual_pending",
                "residual_pnl",
                "n_residual_fee_unverified",
                "n_residual_settlement_disagree",
                "n_fills_attributed",
                "n_other_excluded",
            },
            decision.FamilyRestrictiveBlock: {
                "net_pnl",
                "n_residual",
                "n_residual_pending",
                "residual_pnl",
                "n_residual_fee_unverified",
                "n_residual_settlement_disagree",
            },
            decision.FamilyDecisionRefusal: {"family_id", "reason", "restrictive"},
            decision.RoiDecisionView: {
                "schema_version",
                "generated_at",
                "settled_through",
                "roi_status",
                "label_gate_status",
                "days_since_newest_input",
                "input_freshness_status",
                "n_open_anchors_without_fill",
                "family_stats",
                "family_refusals",
            },
            decision.RoiDecisionRefusal: {"reason"},
        }
        for cls, expected in names.items():
            assert {field.name for field in dataclasses.fields(cls)} == expected
            assert cls.__dataclass_params__.frozen is True
            assert set(cls.__slots__) == expected
            assert all(field.kw_only for field in dataclasses.fields(cls))
        with pytest.raises(dataclasses.FrozenInstanceError):
            view.schema_version = 1

    def test_module_has_no_asdict(self) -> None:
        def hits(source: str) -> set[str]:
            found: set[str] = set()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Name) and node.id in {"asdict", "astuple"}:
                    found.add(node.id)
                if isinstance(node, ast.Attribute) and node.attr in {"asdict", "astuple"}:
                    found.add(node.attr)
                if isinstance(node, ast.Call) and _getattr_pieces(node) in {"asdict", "astuple"}:
                    found.add(_getattr_pieces(node) or "")
            return found

        planted = (
            "import dataclasses\n"
            "def bad(row):\n"
            "    dataclasses.asdict(row)\n"
            "    dataclasses.astuple(row)\n"
            "    getattr(row, 'as' + 'dict')\n"
        )
        assert hits(planted) == {"asdict", "astuple"}
        assert hits(_MODULE_PATH.read_text()) == set()

    def test_copied_literals_equal_the_source_constants(self) -> None:
        decision = _decision()

        assert decision.INPUT_FRESHNESS_OK == _prr.ROI_STATUS_OK == "OK"
        assert decision.INPUT_FRESHNESS_STALE == "STALE"
        assert decision._UNKNOWN_FAMILY == _prr.UNKNOWN_TRIAL_FAMILY_LABEL == "UNKNOWN"
        assert decision.LABEL_GATE_SERVES == frozenset(
            {None, _prr.ROI_STATUS_GATED_UNSETTLED_CAPITAL}
        )
        assert decision.LABEL_GATE_REFUSES == frozenset(
            {_prr.ROI_STATUS_GATED_IDENTITY, _prr.ROI_STATUS_GATED_UNLABELLED_FQ}
        )
        assert decision.MAX_DECISION_REPORT_AGE == timedelta(hours=MARKER_STALE_H)
        assert decision.DECISION_SCHEMA_VERSIONS == frozenset({6})

        def produced_literal(node: ast.expr | None) -> str | None:
            if isinstance(node, ast.Constant) and node.value is None:
                return None
            assert isinstance(node, ast.Name)
            value: str = getattr(_prr, node.id)
            return value

        gate_tree = ast.parse(inspect.getsource(_prr._gate_status_of))
        produced = {
            produced_literal(node.value)
            for node in ast.walk(gate_tree)
            if isinstance(node, ast.Return)
        }
        for node in ast.walk(ast.parse(inspect.getsource(_prr._run))):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id == "label_status" for target in targets
            ):
                continue
            if isinstance(node.value, ast.Attribute) and node.value.attr == "gate_status":
                continue  # the exact return set was collected from _gate_status_of above
            produced.add(produced_literal(node.value))
        assert decision.LABEL_GATE_SERVES | decision.LABEL_GATE_REFUSES == frozenset(produced)

    def test_old_settled_through_with_fresh_generated_at_is_served(self, tmp_path: Path) -> None:
        decision = _decision()
        path = _write(tmp_path, rows=(_clean_row(),), settled_through="2020-01-01")

        view = _read(path)

        assert isinstance(view, decision.RoiDecisionView)
        assert view.settled_through == "2020-01-01"
        assert view.generated_at == _NOW

    def test_residual_flags_still_serve_and_round_trip(self, tmp_path: Path) -> None:
        decision = _decision()
        row = _clean_row(
            n_residual=2,
            n_residual_pending=1,
            residual_pnl=Decimal("-1.5"),
            n_residual_fee_unverified=2,
            n_residual_settlement_disagree=1,
        )
        path = _write(tmp_path, rows=(row,))

        view = _read(path)
        served = view.for_family("fam_b")

        assert isinstance(served, decision.FamilyDecisionStats)
        assert served.n_residual_fee_unverified == 2
        assert served.n_residual_settlement_disagree == 1
        assert served.residual_pnl == Decimal("-1.5")
        again = decision.FamilyDecisionStats.from_json(served.to_json())
        assert again == served


def _const_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _const_text(node.left), _const_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _getattr_pieces(node: ast.Call) -> str | None:
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "getattr" or len(node.args) < 2:
        return None
    return _const_text(node.args[1])
