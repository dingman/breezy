"""ARCH-0 seam 5a: C3 ``lineage/v1``, ``root/v1``, ``refit_run/v1`` and the C2 arrow schema."""

from __future__ import annotations

import hashlib
import io
import json
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.label_schema import (
    LABEL_SCHEMA_ID,
    LABEL_V1_ARROW_SCHEMA,
    ExcludedReason,
    LabelRole,
    PSource,
)
from breezy.persistence.autonomy.lineage import (
    DataWindow,
    LeakageAssertion,
    Lineage,
    RefitOutcome,
    RefitRun,
    RootRecord,
    model_class_of,
    root_model_class,
)
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    parse_json_exact,
)

SHA_A, SHA_B, SHA_C, SHA_D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
GIT = "0123456789abcdef0123456789abcdef01234567"
CREATED_NS = 1_791_100_800 * 10**9  # 2026-10-04T08:00:00Z
FAMILY = "pm_us_crh_fq_v1"

LINEAGE_KEYS = frozenset(
    {
        "schema", "artefact_sha256", "model_class", "lineage_root_family_id",
        "parent_artefact_sha256", "code_git_sha", "build_sha", "producer_code_sha", "params",
        "seed", "fit_status", "data_windows", "own_outcome_label_set_sha256",
        "ablation_artefact_sha256", "own_outcome_max_abs_delta_p",
        "own_outcome_gate_decisions_changed", "train_end_exclusive_utc",
        "forward_eval_start_utc", "leakage_assertions", "recalibration", "correction_form",
        "created_at_ns", "runtime_s", "peak_rss_bytes",
    }
)  # fmt: skip
REFIT_KEYS = frozenset(
    {
        "schema", "run_id", "lineage_root_family_id", "model_class", "outcome", "reason",
        "artefact_sha256", "own_outcome_gate_decisions_changed", "data_windows",
        "own_outcome_label_set_sha256", "runtime_s", "peak_rss_bytes", "producer_code_sha",
    }
)  # fmt: skip
ROOT_KEYS = frozenset(
    {"schema", "family_id", "manifest_sha256", "artefact_sha256", "committed_path"}
)

REQUIRED_ASSERTIONS = (
    "no_sealed_holdout_rows_in_train",
    "ref_ts_lt_take_ts",
    "train_end_lt_forward_eval_start",
)


def window() -> DataWindow:
    return DataWindow(
        source="nbp_archive",
        start_utc="2026-09-01T00:00:00Z",
        end_exclusive_utc="2026-10-02T00:00:00Z",
        rows=4096,
        content_sha256=SHA_C,
    )


def lineage(**overrides: Any) -> Lineage:
    fields: dict[str, Any] = {
        "artefact_sha256": SHA_A,
        "model_class": "forecast_quantile_ladder:density_table",
        "lineage_root_family_id": FAMILY,
        "parent_artefact_sha256": SHA_B,
        "code_git_sha": GIT,
        "build_sha": GIT,
        "producer_code_sha": SHA_D,
        "params": {"alpha": "0.5", "folds": 5, "nested": {"k": [1, 2]}},
        "seed": 7,
        "data_windows": (window(),),
        "train_end_exclusive_utc": "2026-10-02T00:00:00Z",
        "forward_eval_start_utc": "2026-10-04T08:00:00Z",
        "leakage_assertions": tuple(LeakageAssertion(n, True) for n in REQUIRED_ASSERTIONS),
        "created_at_ns": CREATED_NS,
        "runtime_s": Decimal("12.5"),
        "peak_rss_bytes": 123456789,
    }
    fields.update(overrides)
    return Lineage(**fields)


def refit_run(**overrides: Any) -> RefitRun:
    fields: dict[str, Any] = {
        "run_id": "refit_2026_10_04_a",
        "lineage_root_family_id": FAMILY,
        "model_class": "forecast_quantile_ladder:density_table",
        "outcome": RefitOutcome.MINTED,
        "artefact_sha256": SHA_A,
        "data_windows": (window(),),
        "runtime_s": Decimal(3),
        "peak_rss_bytes": 1024,
        "producer_code_sha": SHA_D,
    }
    fields.update(overrides)
    return RefitRun(**fields)


# --- lineage/v1 -----------------------------------------------------------------------------


def test_lineage_exact_set_and_roundtrip() -> None:
    value = lineage(
        own_outcome_label_set_sha256=SHA_C,
        ablation_artefact_sha256=SHA_D,
        own_outcome_max_abs_delta_p=Decimal("0.0031"),
        own_outcome_gate_decisions_changed=2,
    )
    wire = value.to_wire()
    assert set(wire) == LINEAGE_KEYS
    assert wire["schema"] == "lineage/v1"
    assert wire["fit_status"] == "OK"
    assert wire["runtime_s"] == "12.5"
    assert wire["own_outcome_max_abs_delta_p"] == "0.0031"
    assert Lineage.from_wire(parse_json_exact(canonical_json(wire))) == value


def test_lineage_golden_bytes_hash() -> None:
    value = lineage()
    raw = canonical_json(value.to_wire())
    assert (
        raw
        == json.dumps(
            value.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "3b6c6435c34f0d508a5bc37345f657530666a22c7b07fdead402e9bdce971928"
    )


@pytest.mark.parametrize("key", sorted(LINEAGE_KEYS - {"schema"}))
def test_lineage_refuses_a_missing_key(key: str) -> None:
    wire = lineage().to_wire()
    del wire[key]
    with pytest.raises(WireRefused) as info:
        Lineage.from_wire(wire)
    assert info.value.reason is WireRefusalReason.MISSING_KEY


def test_lineage_refuses_unknown_key_float_and_bad_fit_status() -> None:
    wire = lineage().to_wire()
    with pytest.raises(WireRefused) as info:
        Lineage.from_wire({**wire, "extra": 1})
    assert info.value.reason is WireRefusalReason.UNKNOWN_KEY
    with pytest.raises(WireRefused):
        Lineage.from_wire({**wire, "fit_status": "PARTIAL"})
    with pytest.raises(WireRefused):
        Lineage.from_wire({**wire, "runtime_s": 12.5})
    with pytest.raises(WireRefused):
        Lineage.from_wire({**wire, "runtime_s": "12.50"})
    with pytest.raises(WireRefused):
        parse_json_exact('{"schema":"lineage/v1","params":{"x":0.5}}')


def test_lineage_ablation_equal_to_artefact_is_refused() -> None:
    with pytest.raises(WireRefused):
        lineage(
            own_outcome_label_set_sha256=SHA_C,
            ablation_artefact_sha256=SHA_A,  # equals artefact_sha256
            own_outcome_max_abs_delta_p=Decimal("0.1"),
            own_outcome_gate_decisions_changed=1,
        )


def test_lineage_with_a_failed_or_missing_leakage_assertion_is_never_built() -> None:
    failed = (
        LeakageAssertion("no_sealed_holdout_rows_in_train", True),
        LeakageAssertion("ref_ts_lt_take_ts", False),
        LeakageAssertion("train_end_lt_forward_eval_start", True),
    )
    with pytest.raises(WireRefused):
        lineage(leakage_assertions=failed)
    with pytest.raises(WireRefused):
        lineage(leakage_assertions=failed[:1])
    with pytest.raises(WireRefused):
        lineage(leakage_assertions=())


def test_lineage_forward_eval_must_not_precede_creation() -> None:
    with pytest.raises(WireRefused):
        lineage(forward_eval_start_utc="2026-10-04T07:59:59Z")
    assert lineage(forward_eval_start_utc="2026-10-04T08:00:00Z")


def test_lineage_model_class_and_root_family_are_path_safe() -> None:
    for bad in ("forecast_quantile_ladder:../x", "other:density_table", "x"):
        with pytest.raises(WireRefused):
            lineage(model_class=bad)
    with pytest.raises(WireRefused):
        lineage(lineage_root_family_id="../x")


def test_lineage_params_refuse_floats_and_non_json() -> None:
    with pytest.raises(WireRefused):
        lineage(params={"x": 0.5})
    with pytest.raises(WireRefused):
        lineage(params={"x": object()})


def test_data_window_validates_shape() -> None:
    with pytest.raises(WireRefused):
        DataWindow("s", "2026-10-02T00:00:00Z", "2026-09-01T00:00:00Z", 1, SHA_A)  # reversed
    with pytest.raises(WireRefused):
        DataWindow("s", "2026-09-01", "2026-10-01T00:00:00Z", 1, SHA_A)  # not a UTC instant
    with pytest.raises(WireRefused):
        DataWindow("s", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", -1, SHA_A)
    with pytest.raises(WireRefused):
        DataWindow("s", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", True, SHA_A)


def test_model_class_helpers() -> None:
    assert model_class_of("forecast_quantile_ladder", "rung_recalibration") == (
        "forecast_quantile_ladder:rung_recalibration"
    )
    assert root_model_class("continuous_rung_hold") == "continuous_rung_hold:density_table"
    with pytest.raises(WireRefused):
        model_class_of("unknown_kind", "density_table")
    with pytest.raises(WireRefused):
        model_class_of("forecast_quantile_ladder", "../x")
    with pytest.raises(WireRefused):
        root_model_class("unknown_kind")


# --- root/v1 --------------------------------------------------------------------------------


def test_root_record_exact_set_and_golden_bytes() -> None:
    record = RootRecord(
        family_id=FAMILY,
        manifest_sha256=SHA_A,
        artefact_sha256=SHA_B,
        committed_path=f"deploy/families/{FAMILY}.json",
    )
    assert set(record.to_wire()) == ROOT_KEYS
    assert canonical_json(record.to_wire()) == (
        b'{"artefact_sha256":"' + SHA_B.encode() + b'","committed_path":'
        b'"deploy/families/pm_us_crh_fq_v1.json","family_id":"pm_us_crh_fq_v1",'
        b'"manifest_sha256":"' + SHA_A.encode() + b'","schema":"root/v1"}'
    )
    assert RootRecord.from_wire(parse_json_exact(canonical_json(record.to_wire()))) == record


@pytest.mark.parametrize(
    "path",
    [
        "deploy/families/other.json",
        "/deploy/families/pm_us_crh_fq_v1.json",
        "deploy/families/pm_us_crh_fq_v1.json ",
        "../deploy/families/pm_us_crh_fq_v1.json",
        "",
    ],
)
def test_root_record_committed_path_must_equal_the_family_path_exactly(path: str) -> None:
    with pytest.raises(WireRefused):
        RootRecord(FAMILY, SHA_A, SHA_B, path)


def test_root_record_refuses_missing_and_unknown_keys() -> None:
    wire = RootRecord(FAMILY, SHA_A, SHA_B, f"deploy/families/{FAMILY}.json").to_wire()
    for key in ROOT_KEYS - {"schema"}:
        broken = {k: v for k, v in wire.items() if k != key}
        with pytest.raises(WireRefused):
            RootRecord.from_wire(broken)
    with pytest.raises(WireRefused):
        RootRecord.from_wire({**wire, "extra": "x"})


# --- refit_run/v1 ---------------------------------------------------------------------------


def test_refit_run_exact_set_and_outcome_vocabulary() -> None:
    wire = refit_run().to_wire()
    assert set(wire) == REFIT_KEYS
    assert wire["schema"] == "refit_run/v1"
    assert {o.value for o in RefitOutcome} == {
        "MINTED", "NO_CHANGE", "NOT_FITTABLE", "REFUSED", "MINT_REFUSED_CEILING", "ERROR",
    }  # fmt: skip
    assert RefitRun.from_wire(parse_json_exact(canonical_json(wire))) == refit_run()


def test_refit_run_artefact_is_non_null_exactly_when_minted() -> None:
    with pytest.raises(WireRefused):
        refit_run(artefact_sha256=None)
    for outcome in (RefitOutcome.ERROR, RefitOutcome.REFUSED, RefitOutcome.MINT_REFUSED_CEILING):
        with pytest.raises(WireRefused):
            refit_run(outcome=outcome, artefact_sha256=SHA_A)
        assert refit_run(outcome=outcome, artefact_sha256=None, reason="x")


def test_refit_run_reasons() -> None:
    assert refit_run(outcome=RefitOutcome.NO_CHANGE, artefact_sha256=None, reason="below_delta")
    with pytest.raises(WireRefused):
        refit_run(outcome=RefitOutcome.NO_CHANGE, artefact_sha256=None, reason="k_max_reached")
    with pytest.raises(WireRefused):
        refit_run(outcome=RefitOutcome.NO_CHANGE, artefact_sha256=None)
    with pytest.raises(WireRefused):
        refit_run(outcome=RefitOutcome.NOT_FITTABLE, artefact_sha256=None)
    assert refit_run(outcome=RefitOutcome.NOT_FITTABLE, artefact_sha256=None, reason="too_few_rows")
    with pytest.raises(WireRefused):
        refit_run(reason="has space")


def test_refit_run_refuses_missing_unknown_and_float() -> None:
    wire = refit_run().to_wire()
    for key in REFIT_KEYS - {"schema"}:
        with pytest.raises(WireRefused):
            RefitRun.from_wire({k: v for k, v in wire.items() if k != key})
    with pytest.raises(WireRefused):
        RefitRun.from_wire({**wire, "extra": 1})
    with pytest.raises(WireRefused):
        RefitRun.from_wire({**wire, "runtime_s": 3.0})
    with pytest.raises(WireRefused):
        RefitRun.from_wire({**wire, "outcome": "NO_CHANGE(below_delta)"})


# --- C2 label arrow schema ------------------------------------------------------------------

#: (name, arrow type, nullable), in ARCH C2 order. Decimals are strings; the two probabilities
#: are the only float64 columns.
EXPECTED_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("label_id", "string", False),
    ("decision_id", "string", True),
    ("family_id", "string", False),
    ("trial_id", "string", False),
    ("client_order_id", "string", False),
    ("trade_id", "string", True),
    ("station", "string", False),
    ("climate_day", "string", False),
    ("instrument_id", "string", False),
    ("rung_id", "string", False),
    ("leg", "string", False),
    ("role", "string", False),
    ("qty", "string", False),
    ("fill_px", "string", False),
    ("entry_ask", "string", True),
    ("fee_reconciled", "string", True),
    ("slippage", "string", True),
    ("p_at_decision", "double", True),
    ("p_raw_at_decision", "double", True),
    ("p_source", "string", False),
    ("settled_outcome", "bool", True),
    ("settlement_tmax_f", "string", True),
    ("settlement_basis", "string", True),
    ("realized_pnl", "string", True),
    ("counterfactual_hold_pnl", "string", True),
    ("reconciled", "bool", False),
    ("reconciliation_delta", "string", True),
    ("reconciliation_source", "string", False),
    ("net_position_key", "string", False),
    ("admissible", "bool", False),
    ("excluded_reason", "string", True),
    ("labelled_at_ns", "int64", False),
    ("label_seq", "int64", False),
    ("scorer_id", "string", False),
)


def test_label_arrow_schema_pinned_column_for_column() -> None:
    actual = tuple((f.name, str(f.type), f.nullable) for f in LABEL_V1_ARROW_SCHEMA)
    assert actual == EXPECTED_COLUMNS
    assert LABEL_V1_ARROW_SCHEMA.metadata is None
    assert LABEL_SCHEMA_ID == "label/v1"


def test_label_enums_are_the_arch_vocabulary() -> None:
    assert {r.value for r in ExcludedReason} == {
        "duplicate_fill", "q≠1", "fee_unreconciled", "window_incomplete", "canary", "drill",
        "voided_pair", "slippage_defect", "unattributed",
    }  # fmt: skip
    assert {s.value for s in PSource} == {"c1_decision", "artefact_recompute", "none"}
    assert {r.value for r in LabelRole} == {"entry", "exit"}


def test_label_schema_survives_a_parquet_roundtrip() -> None:
    row: dict[str, Any] = {name: None for name, _, _ in EXPECTED_COLUMNS}
    for name, kind, nullable in EXPECTED_COLUMNS:
        if not nullable:
            row[name] = {"string": "x", "bool": False, "int64": 1}[kind]
    table = pa.Table.from_pylist([row], schema=LABEL_V1_ARROW_SCHEMA)
    sink = io.BytesIO()
    pq.write_table(table, sink)
    sink.seek(0)
    assert pq.read_table(sink).schema.equals(LABEL_V1_ARROW_SCHEMA)
