"""AUT-2 r7 WP2: the C2 label store (``persistence/autonomy/label_store.py``).

Every store-reading test writes its fixtures through the real writer (L-42): rows go in through
``write_labels`` and come back through ``read_labels``; the raw parquet is read only to assert the
on-disk shape.
"""

from __future__ import annotations

import ast
import dataclasses
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from breezy.persistence.autonomy import label_store
from breezy.persistence.autonomy.label_schema import (
    LABEL_V1_ARROW_SCHEMA,
    ExcludedReason,
    LabelRole,
    PSource,
)
from breezy.persistence.autonomy.label_store import (
    InvalidLabelRow,
    LabelMarker,
    LabelRow,
    RunOutcome,
    UnknownLabelSchema,
    UnmappedScorerReason,
    labels_consumable,
    read_labels,
    write_labels,
)
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused

_REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILY = "pm_us_crh_fq_v1"
NOW_NS = 1_790_000_000_000_000_000
_H = 3_600_000_000_000


def _row(**overrides: Any) -> LabelRow:
    base: dict[str, Any] = {
        "label_id": "a" * 32,
        "decision_id": "d" * 64,
        "family_id": FAMILY,
        "trial_id": "forecast_quantile_ladder/trial/LAX/2026-10-02/89_90:yes.POLYMARKET_US",
        "client_order_id": "O-20261002-1",
        "trade_id": "T-1",
        "station": "LAX",
        "climate_day": "2026-10-02",
        "instrument_id": "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US",
        "rung_id": "89_90",
        "leg": "yes",
        "role": LabelRole.ENTRY,
        "qty": Decimal(1),
        "fill_px": Decimal("0.40"),
        "entry_ask": Decimal("0.40"),
        "fee_reconciled": Decimal("0.03"),
        "slippage": Decimal(0),
        "p_at_decision": 0.62,
        "p_raw_at_decision": 0.62,
        "p_source": PSource.C1_DECISION,
        "settled_outcome": True,
        "settlement_tmax_f": Decimal(89),
        "settlement_basis": "nws_final",
        "realized_pnl": Decimal("0.57"),
        "counterfactual_hold_pnl": None,
        "reconciled": True,
        "reconciliation_delta": Decimal(0),
        "reconciliation_source": "venue_get",
        "net_position_key": "tc-temp-laxhigh-2026-10-02-gte89lt90f",
        "admissible": True,
        "excluded_reason": None,
        "labelled_at_ns": NOW_NS,
        "label_seq": 0,
        "scorer_id": "forecast_quantile_ladder/v1",
    }
    base.update(overrides)
    return LabelRow(**base)


def _marker(**overrides: Any) -> LabelMarker:
    base: dict[str, Any] = {
        "run_outcome": RunOutcome.LABELLED,
        "pending": 0,
        "unresolved": 0,
        "missing_label": 0,
        "written_at_ns": NOW_NS,
    }
    base.update(overrides)
    return LabelMarker(**base)


def test_schema_is_exact_arch_label_v1(tmp_path: Path) -> None:
    path = write_labels(tmp_path, FAMILY, [_row()], now_ns=NOW_NS)

    table = pq.read_table(path)
    assert table.schema.remove_metadata().equals(LABEL_V1_ARROW_SCHEMA)
    assert [f.name for f in dataclasses.fields(LabelRow)] == LABEL_V1_ARROW_SCHEMA.names
    for column in (
        "p_raw_at_decision",
        "p_source",
        "reconciliation_source",
        "reconciliation_delta",
        "net_position_key",
    ):
        assert column in table.column_names
    assert path == tmp_path / "derived" / "labels" / FAMILY / f"labels_{NOW_NS}.parquet"
    assert read_labels(tmp_path, FAMILY) == (_row(),)


def test_p_source_enum_is_exact(tmp_path: Path) -> None:
    assert {m.value for m in PSource} == {"c1_decision", "artefact_recompute", "none"}
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(p_source="fresh_offline_fit")], now_ns=NOW_NS)
    assert not (tmp_path / "derived").exists()


def test_dedupe_keeps_max_label_seq(tmp_path: Path) -> None:
    first = _row(label_id="1" * 32, realized_pnl=Decimal("0.10"))
    other = _row(label_id="2" * 32, client_order_id="O-2")
    corrected = _row(label_id="1" * 32, realized_pnl=Decimal("-0.40"), label_seq=1)
    write_labels(tmp_path, FAMILY, [first, other], now_ns=NOW_NS)
    write_labels(tmp_path, FAMILY, [corrected], now_ns=NOW_NS + 1)

    rows = {r.label_id: r for r in read_labels(tmp_path, FAMILY)}

    assert set(rows) == {"1" * 32, "2" * 32}
    assert rows["1" * 32].label_seq == 1
    assert rows["1" * 32].realized_pnl == Decimal("-0.40")
    assert rows["2" * 32].label_seq == 0


@pytest.mark.parametrize("stamp", [b"label/v2", None])
def test_unknown_schema_version_refused(tmp_path: Path, stamp: bytes | None) -> None:
    directory = tmp_path / "derived" / "labels" / FAMILY
    directory.mkdir(parents=True, mode=0o700)
    table = pa.Table.from_pylist([], schema=LABEL_V1_ARROW_SCHEMA)
    if stamp is not None:
        table = table.replace_schema_metadata({b"breezy_label_schema": stamp})
    pq.write_table(table, directory / f"labels_{NOW_NS}.parquet")
    (directory / f"labels_{NOW_NS}.parquet").chmod(0o600)

    with pytest.raises(UnknownLabelSchema):
        read_labels(tmp_path, FAMILY)


def test_atomic_write_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from breezy.persistence.autonomy import single_read

    def _fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("link failed after the temp file was written")

    monkeypatch.setattr(single_read, "_link_temp", _fail)

    with pytest.raises(RuntimeError):
        write_labels(tmp_path, FAMILY, [_row()], now_ns=NOW_NS)

    directory = tmp_path / "derived" / "labels" / FAMILY
    assert list(directory.iterdir()) == []  # no partial file, no leftover temp
    monkeypatch.undo()
    assert read_labels(tmp_path, FAMILY) == ()


def test_money_columns_are_string_decimal(tmp_path: Path) -> None:
    path = write_labels(
        tmp_path,
        FAMILY,
        [_row(fill_px=Decimal("0.40"), realized_pnl=Decimal("-0.370"))],
        now_ns=NOW_NS,
    )

    table = pq.read_table(path)
    for column in ("qty", "fill_px", "entry_ask", "fee_reconciled", "realized_pnl", "slippage"):
        assert pa.types.is_string(table.schema.field(column).type), column
    assert table.column("fill_px").to_pylist() == ["0.4"]  # canonical decimal string
    assert table.column("realized_pnl").to_pylist() == ["-0.37"]
    assert table.column("slippage").to_pylist() == ["0"]
    assert read_labels(tmp_path, FAMILY)[0].realized_pnl == Decimal("-0.37")
    for column in ("p_at_decision", "p_raw_at_decision"):
        assert pa.types.is_float64(table.schema.field(column).type)
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(realized_pnl=0.57)], now_ns=NOW_NS + 1)


def test_unmapped_scorer_reason_refused(tmp_path: Path) -> None:
    with pytest.raises(UnmappedScorerReason):
        write_labels(
            tmp_path,
            FAMILY,
            [_row(excluded_reason="venue_settled_without_nws", admissible=False)],
            now_ns=NOW_NS,
        )
    assert not (tmp_path / "derived").exists()
    # every closed C2 reason is accepted, including ARCH's literal ``q≠1``
    for index, reason in enumerate(ExcludedReason):
        write_labels(
            tmp_path,
            FAMILY,
            [_row(excluded_reason=reason, admissible=False)],
            now_ns=NOW_NS + 1 + index,
        )
    assert ExcludedReason.QTY_NOT_ONE.value == "q≠1"


def test_c1_source_with_null_p_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(p_at_decision=None)], now_ns=NOW_NS)
    # a non-c1 source may carry a null p, with its reason stated by the source itself
    write_labels(
        tmp_path,
        FAMILY,
        [_row(p_at_decision=None, p_raw_at_decision=None, p_source=PSource.NONE, admissible=False)],
        now_ns=NOW_NS,
    )
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(p_at_decision=1.5)], now_ns=NOW_NS + 1)
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(family_id="other_family")], now_ns=NOW_NS + 2)


def test_consumer_gate_rule_is_shared() -> None:
    definitions = [
        path.relative_to(_REPO_ROOT).as_posix()
        for root in (_REPO_ROOT / "src", _REPO_ROOT / "scripts")
        for path in root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name == "labels_consumable"
    ]
    assert definitions == ["src/breezy/persistence/autonomy/label_store.py"]
    assert label_store.MARKER_STALE_H == 26
    assert labels_consumable(_marker(), now_ns=NOW_NS) is True
    assert labels_consumable(None, now_ns=NOW_NS) is False
    assert labels_consumable(_marker(), now_ns=NOW_NS + 26 * _H) is True
    assert labels_consumable(_marker(), now_ns=NOW_NS + 26 * _H + 1) is False


@pytest.mark.parametrize(
    "marker",
    [
        _marker(run_outcome=RunOutcome.FAILED_IDENTITY),
        _marker(unresolved=1),
        _marker(missing_label=1),
        _marker(pending=2),
    ],
    ids=["failed_identity", "unresolved", "missing_label", "pending"],
)
def test_labels_consumable_false_on_failed_identity_unresolved_or_missing_label(
    marker: LabelMarker,
) -> None:
    assert labels_consumable(marker, now_ns=NOW_NS) is False
    for outcome in (RunOutcome.LABELLED, RunOutcome.NO_INPUT, RunOutcome.PENDING):
        assert labels_consumable(_marker(run_outcome=outcome), now_ns=NOW_NS) is (
            outcome is not RunOutcome.FAILED_IDENTITY
        )


def test_label_files_are_write_once(tmp_path: Path) -> None:
    path = write_labels(tmp_path, FAMILY, [_row()], now_ns=NOW_NS)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # identical bytes are an idempotent no-op; different rows never replace the file
    assert write_labels(tmp_path, FAMILY, [_row()], now_ns=NOW_NS) == path
    before = path.read_bytes()
    with pytest.raises(SingleReadRefused) as refused:
        write_labels(tmp_path, FAMILY, [_row(realized_pnl=Decimal(9))], now_ns=NOW_NS)
    assert refused.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert path.read_bytes() == before


# -- hardened read and write validation (F4 review batch: P1, P2, P3, D3) ------------------


def _plant(
    root: Path, family: str, now_ns: int, wires: list[dict[str, Any]], *, as_dir: str = ""
) -> Path:
    """Place a raw label file the real writer would refuse (corruption fixtures only)."""
    parts = label_store.label_relative_path(family, now_ns)
    if as_dir:
        parts = (*parts[:-2], as_dir, parts[-1])
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(label_store._serialise(wires))  # the one serialiser, bypassing validation
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    ("column", "value", "error"),
    [
        ("qty", "not-a-decimal", InvalidLabelRow),
        ("p_source", "made_up", InvalidLabelRow),
        ("role", "sideways", InvalidLabelRow),
        ("excluded_reason", "made_up", InvalidLabelRow),
    ],
)
def test_a_corrupt_stored_row_raises_a_label_store_error_chained_from_the_cause(
    tmp_path: Path, column: str, value: str, error: type[Exception]
) -> None:
    wire = label_store._wire(_row())
    wire[column] = value
    _plant(tmp_path, FAMILY, NOW_NS, [wire])

    with pytest.raises(error) as caught:
        read_labels(tmp_path, FAMILY)

    assert isinstance(caught.value, label_store.LabelStoreError)
    assert caught.value.__cause__ is not None


def test_a_label_file_with_a_missing_or_extra_column_is_unknown_schema(tmp_path: Path) -> None:
    wire = label_store._wire(_row())
    wire_extra = {**wire, "surprise": "x"}
    short = {k: v for k, v in wire.items() if k != "scorer_id"}
    for wires, now in (([wire_extra], NOW_NS), ([short], NOW_NS + 1)):
        path = label_store.label_relative_path(FAMILY, now)
        target = tmp_path.joinpath(*path)
        target.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(wires, schema=None).replace_schema_metadata(
            {label_store._SCHEMA_META_KEY: b"label/v1"}
        )
        pq.write_table(table, target)
        target.chmod(0o600)

    with pytest.raises(UnknownLabelSchema):
        read_labels(tmp_path, FAMILY)


def test_a_row_stored_under_another_familys_directory_raises(tmp_path: Path) -> None:
    other = label_store._wire(_row(family_id="some_other_family"))
    _plant(tmp_path, FAMILY, NOW_NS, [other])

    with pytest.raises(InvalidLabelRow, match="family"):
        read_labels(tmp_path, FAMILY)
    with pytest.raises(InvalidLabelRow, match="family"):
        read_labels(tmp_path)


def test_a_duplicate_label_id_and_seq_with_different_content_raises(tmp_path: Path) -> None:
    first = label_store._wire(_row(realized_pnl=Decimal("0.57")))
    second = label_store._wire(_row(realized_pnl=Decimal("-0.43")))
    _plant(tmp_path, FAMILY, NOW_NS, [first])
    _plant(tmp_path, FAMILY, NOW_NS + 1, [second])

    with pytest.raises(label_store.ConflictingLabelRows):
        read_labels(tmp_path, FAMILY)


def test_a_duplicate_label_id_and_seq_with_identical_content_is_one_row(tmp_path: Path) -> None:
    wire = label_store._wire(_row())
    _plant(tmp_path, FAMILY, NOW_NS, [wire])
    _plant(tmp_path, FAMILY, NOW_NS + 1, [wire])

    assert len(read_labels(tmp_path, FAMILY)) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"admissible": "yes"},
        {"admissible": 1},
        {"reconciled": None},
        {"reconciled": 0},
        {"labelled_at_ns": 1.5},
        {"labelled_at_ns": True},
        {"labelled_at_ns": "1790000000000000000"},
        {"labelled_at_ns": -1},
    ],
)
def test_validated_type_checks_admissible_reconciled_and_labelled_at(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    with pytest.raises(InvalidLabelRow):
        write_labels(tmp_path, FAMILY, [_row(**overrides)], now_ns=NOW_NS)

    assert not (tmp_path / "derived").exists()


def test_only_admissible_rows_select_for_any_pnl_or_roi_aggregate() -> None:
    """D3: ``admissible_rows`` is the one selection rule. Exit rows and venue-fallback rows, whose
    ``excluded_reason`` is null, are still not admissible and never pass it."""
    entry = _row(label_id="1" * 32)
    exit_row = _row(label_id="2" * 32, role=LabelRole.EXIT, admissible=False, p_source=PSource.NONE)
    fallback = _row(
        label_id="3" * 32,
        settlement_basis="venue_last_fair_price_fallback",
        admissible=False,
        excluded_reason=None,
    )
    excluded = _row(label_id="4" * 32, admissible=False, excluded_reason=ExcludedReason.CANARY)

    chosen = label_store.admissible_rows([entry, exit_row, fallback, excluded])

    assert chosen == (entry,)
    assert fallback.excluded_reason is None and exit_row.excluded_reason is None


def test_the_unresolved_journal_has_a_one_writer_row() -> None:
    """P4: the journal path is a registered writer (widening 19 -> 20 in the writer table)."""
    from tests.unit.autonomy_writer_table import AUTONOMY_FILE_WRITERS

    assert "evidence/aut2/unresolved/<day>/<now_ns>_label_run.json" in {
        w.path for w in AUTONOMY_FILE_WRITERS
    }
