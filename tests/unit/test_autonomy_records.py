"""ARCH-0 seam 5a: C3 ``lineage/v1``, ``root/v1``, ``refit_run/v1`` and the C2 arrow schema."""

from __future__ import annotations

import hashlib
import io
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.drill_marker import (
    MAX_MARKER_BYTES,
    DrillDetector,
    DrillMarker,
    DrillStep,
    MarkerAbsent,
    MarkerError,
    MarkerErrorReason,
    read_marker,
    read_marker_at,
)
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
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.single_read import open_root
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


# --- drill_marker/v1 (5b) --------------------------------------------------------------------

MARKER_KEYS = frozenset(
    {
        "schema", "registry_root", "venue", "episode_id", "child_id", "detector", "step",
        "window_start_ns", "window_end_ns", "abort_record_sha256", "drill_clause_sha256", "ts_ns",
    }
)  # fmt: skip
WINDOW_START_NS = CREATED_NS
WINDOW_END_NS = CREATED_NS + 30 * 60 * 10**9


def marker_wire(**overrides: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "schema": "drill_marker/v1",
        "registry_root": "/home/jon/.local/share/breezy",
        "venue": "polymarket_us",
        "episode_id": "ep_2026_10_05",
        "child_id": "pm_us_crh_fq_v1_d0001",
        "detector": "DRILL_INJECT",
        "step": "demote",
        "window_start_ns": WINDOW_START_NS,
        "window_end_ns": WINDOW_END_NS,
        "abort_record_sha256": None,
        "drill_clause_sha256": SHA_D,
        "ts_ns": WINDOW_START_NS,
    }
    wire.update(overrides)
    return wire


def place_marker(root: Path, data: bytes, *, dir_mode: int = 0o700, file_mode: int = 0o600) -> Path:
    folder = root / "registry" / "drill"
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(dir_mode)
    path = folder / "marker.json"
    path.write_bytes(data)
    path.chmod(file_mode)
    return path


def read_at(root: Path) -> DrillMarker | MarkerAbsent | MarkerError:
    rootfd = open_root(root)
    try:
        return read_marker_at(rootfd)
    finally:
        os.close(rootfd)


def test_drill_marker_exact_set_and_absent_vs_dir_missing(tmp_path: Path) -> None:
    # exact set: the 12 keys of AUT-7 r5, and nothing else
    marker = DrillMarker.from_wire(marker_wire())
    assert set(marker.to_wire()) == MARKER_KEYS
    assert marker.to_wire() == marker_wire()
    assert marker.detector is DrillDetector.DRILL_INJECT and marker.step is DrillStep.DEMOTE

    # ENOENT on the directory is an error; ENOENT on the marker is the clean "absent"
    assert read_at(tmp_path) == MarkerError(MarkerErrorReason.DIR_MISSING, "not_found")
    assert read_marker(AutonomyPaths(tmp_path)) == MarkerError(
        MarkerErrorReason.DIR_MISSING, "not_found"
    )
    (tmp_path / "registry" / "drill").mkdir(parents=True, mode=0o700)
    (tmp_path / "registry" / "drill").chmod(0o700)
    assert read_at(tmp_path) == MarkerAbsent()
    assert read_marker(AutonomyPaths(tmp_path)) == MarkerAbsent()

    # a present marker reads back as the record
    place_marker(tmp_path, canonical_json(marker_wire()))
    assert read_at(tmp_path) == marker
    assert read_marker(AutonomyPaths(tmp_path)) == marker


def test_drill_marker_golden_bytes() -> None:
    raw = canonical_json(DrillMarker.from_wire(marker_wire()).to_wire())
    assert raw == (
        b'{"abort_record_sha256":null,"child_id":"pm_us_crh_fq_v1_d0001",'
        b'"detector":"DRILL_INJECT","drill_clause_sha256":"' + SHA_D.encode() + b'",'
        b'"episode_id":"ep_2026_10_05","registry_root":"/home/jon/.local/share/breezy",'
        b'"schema":"drill_marker/v1","step":"demote","ts_ns":1791100800000000000,'
        b'"venue":"polymarket_us","window_end_ns":1791102600000000000,'
        b'"window_start_ns":1791100800000000000}'
    )


@pytest.mark.parametrize(
    ("overrides", "valid"),
    [
        ({}, True),  # demote pairs with DRILL_INJECT
        ({"detector": "DRILL_INJECT_HALT", "step": "halt"}, True),
        (
            {"detector": "DRILL_INJECT_HALT", "step": "abort_halt", "abort_record_sha256": SHA_A},
            True,
        ),
        ({"detector": "DRILL_INJECT", "step": "halt"}, False),
        ({"detector": "DRILL_INJECT_HALT", "step": "demote"}, False),
        ({"detector": "DRILL_INJECT", "step": "abort_halt", "abort_record_sha256": SHA_A}, False),
        ({"detector": "DRILL_INJECT_HALT", "step": "abort_halt"}, False),  # abort needs its record
        ({"abort_record_sha256": SHA_A}, False),  # a non-abort step has none
        ({"detector": "DRILL_OTHER"}, False),
        ({"step": "rollback"}, False),
    ],
)
def test_drill_marker_detector_step_and_abort_record_pairing(
    overrides: dict[str, Any], valid: bool
) -> None:
    if valid:
        assert DrillMarker.from_wire(marker_wire(**overrides)).to_wire() == marker_wire(**overrides)
    else:
        with pytest.raises(WireRefused) as caught:
            DrillMarker.from_wire(marker_wire(**overrides))
        assert caught.value.reason is WireRefusalReason.BAD_VALUE


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"schema": "drill_marker/v2"}, WireRefusalReason.BAD_VALUE),
        ({"venue": "Poly US"}, WireRefusalReason.BAD_VALUE),
        ({"child_id": "../x"}, WireRefusalReason.BAD_VALUE),
        ({"episode_id": ""}, WireRefusalReason.BAD_VALUE),
        ({"registry_root": "relative/path"}, WireRefusalReason.BAD_VALUE),
        ({"registry_root": "/a\x00b"}, WireRefusalReason.BAD_VALUE),
        ({"registry_root": 7}, WireRefusalReason.WRONG_TYPE),
        ({"drill_clause_sha256": "zz"}, WireRefusalReason.BAD_VALUE),
        ({"drill_clause_sha256": None}, WireRefusalReason.WRONG_TYPE),
        ({"ts_ns": True}, WireRefusalReason.BOOL_AS_INT),
        ({"ts_ns": -1}, WireRefusalReason.BAD_VALUE),
        ({"window_start_ns": "1"}, WireRefusalReason.WRONG_TYPE),
        ({"window_end_ns": WINDOW_START_NS}, WireRefusalReason.BAD_VALUE),  # empty window
        ({"window_end_ns": WINDOW_START_NS - 1}, WireRefusalReason.BAD_VALUE),
    ],
)
def test_drill_marker_refuses_inexact_values(
    overrides: dict[str, Any], reason: WireRefusalReason
) -> None:
    with pytest.raises(WireRefused) as caught:
        DrillMarker.from_wire(marker_wire(**overrides))
    assert caught.value.reason is reason


def test_drill_marker_refuses_missing_unknown_and_float_keys() -> None:
    wire = marker_wire()
    del wire["ts_ns"]
    with pytest.raises(WireRefused) as missing:
        DrillMarker.from_wire(wire)
    assert missing.value.reason is WireRefusalReason.MISSING_KEY
    with pytest.raises(WireRefused) as unknown:
        DrillMarker.from_wire(marker_wire(extra=1))
    assert unknown.value.reason is WireRefusalReason.UNKNOWN_KEY
    with pytest.raises(WireRefused) as float_token:
        parse_json_exact(canonical_json(marker_wire()).replace(b'"ts_ns":1', b'"ts_ns":1.0e0', 1))
    assert float_token.value.reason is WireRefusalReason.FLOAT_TOKEN


def test_drill_marker_other_detectors_marker_parses_and_is_left_to_the_detector(
    tmp_path: Path,
) -> None:
    other = marker_wire(detector="DRILL_INJECT_HALT", step="halt")
    place_marker(tmp_path, canonical_json(other))
    result = read_at(tmp_path)
    assert isinstance(result, DrillMarker) and result.detector is DrillDetector.DRILL_INJECT_HALT


def test_drill_marker_registry_root_keys_the_marker_to_its_root(tmp_path: Path) -> None:
    place_marker(tmp_path, canonical_json(marker_wire(registry_root=str(tmp_path))))
    prod = read_marker(AutonomyPaths(tmp_path))
    shadow = read_marker(ShadowPaths(tmp_path))
    assert isinstance(prod, DrillMarker) and prod.registry_root == str(tmp_path)
    assert shadow == prod  # the reader reports the bytes; the detector compares the root


def _marker_is_a_symlink(root: Path) -> None:
    target = root / "elsewhere.json"
    target.write_bytes(canonical_json(marker_wire()))
    folder = root / "registry" / "drill"
    folder.mkdir(parents=True)
    folder.chmod(0o700)
    os.symlink(target, folder / "marker.json")


def _marker_oversize(root: Path) -> None:
    place_marker(root, b" " * (MAX_MARKER_BYTES + 1))


def _marker_unparseable(root: Path) -> None:
    place_marker(root, b"{nope")


def _marker_group_writable(root: Path) -> None:
    place_marker(root, canonical_json(marker_wire()), file_mode=0o660)


def _marker_is_a_directory(root: Path) -> None:
    (root / "registry" / "drill" / "marker.json").mkdir(parents=True)
    (root / "registry" / "drill").chmod(0o700)


def _marker_unknown_key(root: Path) -> None:
    place_marker(root, canonical_json(marker_wire(extra=1)))


def _dir_too_open(root: Path) -> None:
    place_marker(root, canonical_json(marker_wire()), dir_mode=0o755)


def _dir_group_writable(root: Path) -> None:
    place_marker(root, canonical_json(marker_wire()), dir_mode=0o770)


def _dir_is_a_symlink(root: Path) -> None:
    real = root / "real_drill"
    real.mkdir(mode=0o700)
    (root / "registry").mkdir()
    os.symlink(real, root / "registry" / "drill")


def _dir_is_a_file(root: Path) -> None:
    (root / "registry").mkdir()
    (root / "registry" / "drill").write_bytes(b"x")


MARKER_ERRORS = {
    "marker_symlink": (_marker_is_a_symlink, MarkerErrorReason.FILE_UNSAFE, "symlink"),
    "marker_oversize": (_marker_oversize, MarkerErrorReason.FILE_UNSAFE, "oversize"),
    "marker_group_writable": (
        _marker_group_writable,
        MarkerErrorReason.FILE_UNSAFE,
        "mode_too_open",
    ),
    "marker_is_a_directory": (_marker_is_a_directory, MarkerErrorReason.FILE_UNSAFE, "not_regular"),
    "marker_unparseable": (_marker_unparseable, MarkerErrorReason.INVALID, "malformed_json"),
    "marker_unknown_key": (_marker_unknown_key, MarkerErrorReason.INVALID, "unknown_key"),
    "dir_mode_0755": (_dir_too_open, MarkerErrorReason.DIR_UNSAFE, "dir_mode"),
    "dir_mode_0770": (_dir_group_writable, MarkerErrorReason.DIR_UNSAFE, "dir_mode"),
    "dir_symlink": (_dir_is_a_symlink, MarkerErrorReason.DIR_UNSAFE, "symlink"),
    "dir_is_a_file": (_dir_is_a_file, MarkerErrorReason.DIR_UNSAFE, "not_directory"),
}


@pytest.mark.parametrize("fault", sorted(MARKER_ERRORS))
def test_drill_marker_every_unsafe_or_unreadable_state_is_an_error_never_absent(
    tmp_path: Path, fault: str
) -> None:
    build, reason, detail = MARKER_ERRORS[fault]
    build(tmp_path)
    assert read_at(tmp_path) == MarkerError(reason, detail), fault


def test_drill_marker_missing_root_is_an_error_not_absent(tmp_path: Path) -> None:
    result = read_marker(AutonomyPaths(tmp_path / "no_such_root"))
    assert result == MarkerError(MarkerErrorReason.DIR_MISSING, "not_found")


def test_drill_marker_layout_matches_the_paths_builder(tmp_path: Path) -> None:
    from breezy.persistence.autonomy import drill_marker

    expected = AutonomyPaths(tmp_path).drill_marker()
    built = tmp_path.joinpath(*drill_marker.MARKER_DIR_PARTS, drill_marker.MARKER_NAME)
    assert built == expected


def test_drill_marker_error_text_never_carries_a_path(tmp_path: Path) -> None:
    _marker_is_a_symlink(tmp_path)
    assert str(tmp_path) not in repr(read_at(tmp_path))


# --- A5-R4 / A5-R5 lineage and refit_run items --------------------------------------------------


@pytest.mark.parametrize("reason", ["below_delta", "existing_sha"])
def test_refit_run_no_change_takes_below_delta_or_existing_sha(reason: str) -> None:
    run = refit_run(outcome=RefitOutcome.NO_CHANGE, artefact_sha256=None, reason=reason)
    assert RefitRun.from_wire(parse_json_exact(canonical_json(run.to_wire()))) == run


def test_refit_run_reason_regex_admits_a_sha_suffix_and_refuses_others() -> None:
    sha_reason = f"engine_refused:{SHA_A}"
    assert refit_run(outcome=RefitOutcome.REFUSED, artefact_sha256=None, reason=sha_reason)
    for bad in (f"engine_refused:{SHA_A[:-1]}", f"engine_refused:{'A' * 64}", "a:b", ":" + SHA_A):
        with pytest.raises(WireRefused):
            refit_run(outcome=RefitOutcome.REFUSED, artefact_sha256=None, reason=bad)
    with pytest.raises(WireRefused):  # NO_CHANGE stays a closed set
        refit_run(outcome=RefitOutcome.NO_CHANGE, artefact_sha256=None, reason=sha_reason)


@pytest.mark.parametrize("field", ["build_sha", "code_git_sha"])
@pytest.mark.parametrize("bad", ["abc1234", "0" * 39, "0" * 41, "0" * 63, "G" * 40])
def test_lineage_git_shas_must_be_full_length(field: str, bad: str) -> None:
    with pytest.raises(WireRefused):
        lineage(**{field: bad})
    assert lineage(**{field: "0" * 40})
    assert lineage(**{field: "0" * 64})


def test_lineage_train_end_must_not_follow_forward_eval_start() -> None:
    with pytest.raises(WireRefused):
        lineage(train_end_exclusive_utc="2026-10-04T08:00:01Z")
    assert lineage(train_end_exclusive_utc="2026-10-04T08:00:00Z")


def test_lineage_own_outcome_gate_count_and_label_set_are_null_together() -> None:
    both = {
        "own_outcome_label_set_sha256": SHA_C,
        "ablation_artefact_sha256": SHA_D,
        "own_outcome_max_abs_delta_p": Decimal("0.1"),
        "own_outcome_gate_decisions_changed": 1,
    }
    assert lineage(**both)
    with pytest.raises(WireRefused):
        lineage(**{**both, "own_outcome_gate_decisions_changed": None})
    with pytest.raises(WireRefused):
        lineage(own_outcome_gate_decisions_changed=1)


def test_lineage_params_are_frozen_and_detached_from_the_callers_dict() -> None:
    source: dict[str, Any] = {"alpha": "0.5", "nested": {"k": [1, 2]}}
    value = lineage(params=source)
    source["alpha"] = "9"
    source["nested"]["k"].append(3)
    assert value.to_wire()["params"] == {"alpha": "0.5", "nested": {"k": [1, 2]}}
    with pytest.raises(TypeError):
        value.params["alpha"] = "9"  # type: ignore[index]
    with pytest.raises(TypeError):
        value.params["nested"]["k"] = ()
    again = Lineage.from_wire(parse_json_exact(canonical_json(value.to_wire())))
    assert again == value


# --- 6d: E-14 root copies ---------------------------------------------------------------------

DENSITY_RAW = b'{"placeholder":"not_applicable_density"}\n'
DENSITY_SHA = hashlib.sha256(DENSITY_RAW).hexdigest()
CONT_KIND = "continuous_rung_hold"
ROOT_FAMILIES = ("pm_us_crh_v4", "pm_us_crh_cont")


def _root_record(family_id: str, manifest_sha: str = SHA_A) -> RootRecord:
    return RootRecord(
        family_id=family_id,
        manifest_sha256=manifest_sha,
        artefact_sha256=DENSITY_SHA,
        committed_path=f"deploy/families/{family_id}.json",
    )


@pytest.fixture
def registry_root(tmp_path: Path) -> Any:
    data_root = tmp_path / "registry"
    data_root.mkdir(mode=0o700)
    yield data_root
    for directory in [data_root, *data_root.rglob("*")]:
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)


def _sha_dir(paths: AutonomyPaths) -> Path:
    return paths.artefact_dir(root_model_class(CONT_KIND), DENSITY_SHA)


def test_two_roots_sharing_sha_write_identical_artefact_json(registry_root: Path) -> None:
    from breezy.persistence.autonomy.family_bytes import RootCopyResult, write_root_copy

    paths = AutonomyPaths(registry_root)
    first = write_root_copy(
        paths,
        record=_root_record("pm_us_crh_v4", SHA_A),
        artefact_raw=DENSITY_RAW,
        composition_kind=CONT_KIND,
    )
    artefact = _sha_dir(paths) / "artefact.json"
    first_bytes = artefact.read_bytes()
    second = write_root_copy(
        paths,
        record=_root_record("pm_us_crh_cont", SHA_B),
        artefact_raw=DENSITY_RAW,
        composition_kind=CONT_KIND,
    )
    assert first is RootCopyResult.WRITTEN
    assert second is RootCopyResult.WRITTEN  # its own roots/<family>.json is new
    assert artefact.read_bytes() == first_bytes == DENSITY_RAW
    roots = {p.name: p.read_bytes() for p in (_sha_dir(paths) / "roots").iterdir()}
    assert set(roots) == {f"{family}.json" for family in ROOT_FAMILIES}
    assert roots["pm_us_crh_v4.json"] == canonical_json(_root_record("pm_us_crh_v4").to_wire())
    assert roots["pm_us_crh_cont.json"] == canonical_json(
        _root_record("pm_us_crh_cont", SHA_B).to_wire()
    )
    assert os.stat(artefact).st_mode & 0o777 == 0o444


def test_root_copy_exists_different_is_integrity(registry_root: Path) -> None:
    from breezy.persistence.autonomy.family_bytes import RootCopyIntegrity, write_root_copy

    paths = AutonomyPaths(registry_root)
    write_root_copy(
        paths,
        record=_root_record("pm_us_crh_v4", SHA_A),
        artefact_raw=DENSITY_RAW,
        composition_kind=CONT_KIND,
    )
    before = {p: p.read_bytes() for p in _sha_dir(paths).rglob("*") if p.is_file()}
    # Same family, different manifest sha: roots/<family>.json differs.
    with pytest.raises(RootCopyIntegrity):
        write_root_copy(
            paths,
            record=_root_record("pm_us_crh_v4", SHA_B),
            artefact_raw=DENSITY_RAW,
            composition_kind=CONT_KIND,
        )
    # artefact.json differs from the content-addressed bytes already in the directory.
    (_sha_dir(paths) / "artefact.json").chmod(0o644)
    (_sha_dir(paths) / "artefact.json").write_bytes(b"tampered")
    with pytest.raises(RootCopyIntegrity):
        write_root_copy(
            paths,
            record=_root_record("pm_us_crh_cont", SHA_B),
            artefact_raw=DENSITY_RAW,
            composition_kind=CONT_KIND,
        )
    after = {p: p.read_bytes() for p in _sha_dir(paths).rglob("*") if p.is_file()}
    assert after[_sha_dir(paths) / "artefact.json"] == b"tampered"
    assert after.keys() == before.keys()  # the refused second root left no new file


def test_root_copy_rerun_after_chmod_0500_is_exists_equal(registry_root: Path) -> None:
    from breezy.persistence.autonomy.family_bytes import RootCopyResult, write_root_copy

    paths = AutonomyPaths(registry_root)
    kwargs: dict[str, Any] = {
        "record": _root_record("pm_us_crh_v4"),
        "artefact_raw": DENSITY_RAW,
        "composition_kind": CONT_KIND,
    }
    assert write_root_copy(paths, **kwargs) is RootCopyResult.WRITTEN
    _sha_dir(paths).joinpath("roots").chmod(0o500)
    _sha_dir(paths).chmod(0o500)
    leftovers = sorted(p.name for p in _sha_dir(paths).rglob("*"))
    assert write_root_copy(paths, **kwargs) is RootCopyResult.EXISTS_EQUAL
    assert sorted(p.name for p in _sha_dir(paths).rglob("*")) == leftovers


def test_refit_into_root_sha_dir_fails_closed(registry_root: Path) -> None:
    from breezy.persistence.autonomy.family_bytes import write_root_copy
    from breezy.persistence.autonomy.single_read import (
        SingleReadReason,
        SingleReadRefused,
        write_once,
    )

    paths = AutonomyPaths(registry_root)
    write_root_copy(
        paths,
        record=_root_record("pm_us_crh_v4"),
        artefact_raw=DENSITY_RAW,
        composition_kind=CONT_KIND,
    )
    sha_dir = _sha_dir(paths)
    (sha_dir / "roots").chmod(0o500)
    sha_dir.chmod(0o500)
    for name in ("lineage.json", "refit_run.json"):  # what an AUT-3 refit would add
        with pytest.raises(SingleReadRefused) as caught:
            write_once(sha_dir / name, b"{}", root=registry_root, mode=0o444)
        assert caught.value.reason is SingleReadReason.DIR_NOT_WRITABLE
    with pytest.raises(SingleReadRefused) as caught:  # a new root record in the sealed roots/
        write_once(sha_dir / "roots" / "other.json", b"{}", root=registry_root, mode=0o444)
    assert caught.value.reason is SingleReadReason.DIR_NOT_WRITABLE
    assert sorted(p.name for p in sha_dir.iterdir()) == ["artefact.json", "roots"]
