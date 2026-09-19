"""Unit tests for `breezy.strategy.ladder_ev.forecast_catalog` -- WP-12 Seam C.

Scope: the durable forecast archive (backtest source) over per-station
`ParquetDataCatalog` roots. Round-trip fidelity, root isolation, the two
Nautilus traps this seam is built around (a silently skipped same-range
rewrite, and a `delete_data_range` that no-ops for identifier-less custom
types), point-in-time reads, and path safety.

Every catalog lives under `tmp_path`; nothing here touches the network, no
process or unit is started, and no Nautilus source is modified.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.forecast_point import (
    FORECAST_POINT_SCHEMA_VERSION,
    ForecastPoint,
)
from breezy.strategy.ladder_ev import forecast_catalog as forecast_catalog_module
from breezy.strategy.ladder_ev.forecast_catalog import (
    FORECAST_CATALOG_NAMESPACE,
    ForecastCatalogRootError,
    ForeignStationRowError,
    SilentRewriteRefusedError,
    forecast_catalog_root,
    forecast_point_identity,
    open_forecast_catalog,
    read_forecast_points,
    read_forecast_points_as_of,
    require_disjoint_catalog_roots,
    write_forecast_points,
)

_MINUTE_NS = 60_000_000_000
_HOUR_NS = 60 * _MINUTE_NS
#: 2026-09-18T12:00:00Z as UNIX nanoseconds.
_CYCLE_NS = 1_789_473_600_000_000_000
_LAG_NS = 25 * _MINUTE_NS


def make_point(**overrides: Any) -> ForecastPoint:
    kwargs: dict[str, Any] = {
        "station": "KMIA",
        "model": "NBM_NBS",
        "model_version": "4.2",
        "variable": "TXN",
        "cycle_runtime_ns": _CYCLE_NS,
        "valid_start_ns": _CYCLE_NS + 12 * _HOUR_NS,
        "valid_end_ns": _CYCLE_NS + 24 * _HOUR_NS,
        "value_f": 88.0,
        "issuance_seq": 0,
        "measured_publication_lag_ns": _LAG_NS,
        "available_at_ns": _CYCLE_NS + _LAG_NS,
        "ingested_at_ns": _CYCLE_NS + _LAG_NS + _MINUTE_NS,
    }
    kwargs.update(overrides)
    lag = kwargs["measured_publication_lag_ns"]
    if "available_at_ns" not in overrides:
        kwargs["available_at_ns"] = kwargs["cycle_runtime_ns"] + lag
    return ForecastPoint(**kwargs)


# --------------------------------------------------------------------------
# 1. Round-trip and per-station root isolation
# --------------------------------------------------------------------------


def test_round_trip_preserves_every_field_including_a_declared_absence(
    tmp_path: Path,
) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    present = make_point()
    absent = make_point(
        value_f=None,
        absence_reason="not_published",
        issuance_seq=1,
        measured_publication_lag_ns=_LAG_NS + _MINUTE_NS,
    )

    outcome = write_forecast_points(catalog, [present, absent])
    assert outcome.is_complete

    read_back = read_forecast_points(catalog)
    assert [point.to_dict() for point in read_back] == [
        present.to_dict(),
        absent.to_dict(),
    ]
    restored_absence = read_back[1]
    assert restored_absence.value_f is None
    assert restored_absence.absence_reason == "not_published"
    assert restored_absence.schema_version == FORECAST_POINT_SCHEMA_VERSION


def test_two_stations_land_in_separate_roots_and_a_read_never_crosses_them(
    tmp_path: Path,
) -> None:
    miami = open_forecast_catalog(tmp_path, "KMIA")
    denver = open_forecast_catalog(tmp_path, "KDEN")

    assert Path(miami.path) != Path(denver.path)
    assert Path(miami.path) == forecast_catalog_root(tmp_path, "KMIA")
    assert not Path(miami.path).is_relative_to(Path(denver.path))
    assert not Path(denver.path).is_relative_to(Path(miami.path))

    write_forecast_points(miami, [make_point(station="KMIA", value_f=88.0)])
    write_forecast_points(denver, [make_point(station="KDEN", value_f=41.0)])

    assert [point.station for point in read_forecast_points(miami)] == ["KMIA"]
    assert [point.station for point in read_forecast_points(denver)] == ["KDEN"]
    assert [point.value_f for point in read_forecast_points(miami)] == [88.0]


def test_a_station_is_normalised_to_one_root(tmp_path: Path) -> None:
    assert forecast_catalog_root(tmp_path, " kmia ") == forecast_catalog_root(
        tmp_path, "KMIA"
    )


def test_reader_refuses_a_row_whose_station_contradicts_its_root(
    tmp_path: Path,
) -> None:
    miami = open_forecast_catalog(tmp_path, "KMIA")
    # Written through the RAW catalog, bypassing the writer's own guard: this
    # is the "a foreign fragment appeared in the root" case, not a caller
    # mistake, and the READ side must still refuse it.
    miami.write_data([make_point(station="KDEN")])

    with pytest.raises(ForeignStationRowError):
        read_forecast_points(miami)


def test_writer_refuses_a_point_whose_station_contradicts_its_root(
    tmp_path: Path,
) -> None:
    miami = open_forecast_catalog(tmp_path, "KMIA")

    with pytest.raises(ForeignStationRowError):
        write_forecast_points(miami, [make_point(station="KDEN")])


# --------------------------------------------------------------------------
# 2. Trap 1 -- a correction is never a rewrite
# --------------------------------------------------------------------------


def test_nautilus_silently_skips_a_same_ts_init_range_rewrite(tmp_path: Path) -> None:
    """Pin the platform behaviour this seam is defended against.

    `ParquetDataCatalog._write_chunk` (``persistence/catalog/parquet.py:378-380``)
    returns normally -- ``print`` and no exception -- when the computed filename
    already exists. WIDEN this test if the platform changes; never delete it.
    """
    raw = ParquetDataCatalog(path=tmp_path / "raw")
    original = make_point(value_f=88.0)
    rewrite = make_point(value_f=71.0)  # same ts_init range, different content
    assert original.ts_init == rewrite.ts_init

    raw.write_data([original])
    raw.write_data([rewrite])  # no exception raised by the platform

    rows = [
        row.data if hasattr(row, "data") else row
        for row in raw.query(data_cls=ForecastPoint)
    ]
    assert [row.value_f for row in rows] == [88.0]


def test_same_ts_init_range_rewrite_is_refused_or_skipped_loudly(
    tmp_path: Path,
) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    original = make_point(value_f=88.0)
    rewrite = make_point(value_f=71.0)

    assert write_forecast_points(catalog, [original]).is_complete

    with pytest.raises(SilentRewriteRefusedError) as excinfo:
        write_forecast_points(catalog, [rewrite])

    message = str(excinfo.value)
    assert forecast_point_identity(rewrite) in message
    assert "issuance_seq" in message

    # The archive is unchanged: the rewrite never displaced the original.
    assert [point.value_f for point in read_forecast_points(catalog)] == [88.0]


def test_a_correction_with_a_later_vintage_is_written_alongside_the_original(
    tmp_path: Path,
) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    original = make_point(value_f=88.0)
    correction = make_point(
        value_f=71.0,
        issuance_seq=1,
        measured_publication_lag_ns=_LAG_NS + 30 * _MINUTE_NS,
    )

    write_forecast_points(catalog, [original])
    assert write_forecast_points(catalog, [correction]).is_complete

    stored = read_forecast_points(catalog)
    assert [point.issuance_seq for point in stored] == [0, 1]
    assert [point.value_f for point in stored] == [88.0, 71.0]


# --------------------------------------------------------------------------
# 3. Trap 2 -- `delete_data_range` is a no-op here
# --------------------------------------------------------------------------


def test_delete_data_range_is_a_documented_noop_for_identifierless_forecast_point(
    tmp_path: Path,
) -> None:
    """`parquet.py:1386-1406` substring-matches ``"/data/<name>/"``.

    An identifier-less custom type writes flat to ``<root>/data/<name>``, whose
    path contains no separator after the type name, so the loop matches nothing
    and the call returns having deleted nothing. That no-op is what makes this
    archive append-only by construction -- assert it, and never build a
    delete-then-rewrite repair path on top of it.
    """
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    point = make_point()
    write_forecast_points(catalog, [point])

    catalog.delete_data_range(
        data_cls=ForecastPoint,
        start=point.ts_init - _HOUR_NS,
        end=point.ts_init + _HOUR_NS,
    )

    assert [row.to_dict() for row in read_forecast_points(catalog)] == [point.to_dict()]


def test_the_module_never_calls_delete_data_range(tmp_path: Path) -> None:
    tree = ast.parse(inspect.getsource(forecast_catalog_module))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "delete_data_range" not in called
    assert not hasattr(forecast_catalog_module, "delete_forecast_points")


# --------------------------------------------------------------------------
# 4. Point-in-time read -- the storage-layer leakage guard
# --------------------------------------------------------------------------


def test_an_as_of_read_cannot_see_a_correction_written_later(tmp_path: Path) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    original = make_point(value_f=88.0)
    correction = make_point(
        value_f=71.0,
        issuance_seq=1,
        measured_publication_lag_ns=_LAG_NS + 30 * _MINUTE_NS,
    )
    write_forecast_points(catalog, [original])
    write_forecast_points(catalog, [correction])

    before = read_forecast_points_as_of(
        catalog, as_of_ns=correction.available_at_ns - 1
    )
    assert [point.value_f for point in before.values()] == [88.0]
    assert [point.issuance_seq for point in before.values()] == [0]

    at_vintage = read_forecast_points_as_of(catalog, as_of_ns=correction.available_at_ns)
    assert [point.value_f for point in at_vintage.values()] == [71.0]


def test_an_as_of_read_before_the_first_vintage_omits_the_key(tmp_path: Path) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    original = make_point()
    write_forecast_points(catalog, [original])

    assert read_forecast_points_as_of(catalog, as_of_ns=original.cycle_runtime_ns) == {}
    assert (
        read_forecast_points_as_of(catalog, as_of_ns=original.available_at_ns)[
            original.join_key
        ].value_f
        == original.value_f
    )


def test_an_as_of_read_keeps_two_forecasts_of_one_station_apart(
    tmp_path: Path,
) -> None:
    catalog = open_forecast_catalog(tmp_path, "KMIA")
    txn = make_point(variable="TXN", value_f=88.0)
    tmp = make_point(
        variable="TMP",
        value_f=70.0,
        measured_publication_lag_ns=_LAG_NS + _MINUTE_NS,
    )
    write_forecast_points(catalog, [txn])
    write_forecast_points(catalog, [tmp])

    selected = read_forecast_points_as_of(catalog, as_of_ns=tmp.available_at_ns)
    assert selected[txn.join_key].value_f == 88.0
    assert selected[tmp.join_key].value_f == 70.0


# --------------------------------------------------------------------------
# 5. Path safety
# --------------------------------------------------------------------------


def test_the_forecast_root_carries_its_own_namespace_segment(tmp_path: Path) -> None:
    root = forecast_catalog_root(tmp_path, "KMIA")
    assert root == tmp_path / FORECAST_CATALOG_NAMESPACE / "KMIA"


def test_the_forecast_root_is_disjoint_from_the_tape_and_settlement_roots(
    tmp_path: Path,
) -> None:
    forecast_root = forecast_catalog_root(tmp_path, "KMIA")
    quote_tape_root = tmp_path / "live"
    settlement_backup_root = tmp_path / "polymarket_us" / "NYC"

    require_disjoint_catalog_roots(
        forecast_root, quote_tape_root, settlement_backup_root
    )

    with pytest.raises(ForecastCatalogRootError):
        require_disjoint_catalog_roots(forecast_root, forecast_root.parent)
    with pytest.raises(ForecastCatalogRootError):
        require_disjoint_catalog_roots(forecast_root, forecast_root / "data")


def test_a_traversing_or_unsafe_station_is_refused(tmp_path: Path) -> None:
    for unsafe in ("../escape", "K/MIA", "K~MIA", ""):
        with pytest.raises(ValueError):
            forecast_catalog_root(tmp_path, unsafe)


def test_the_identity_string_uses_caret_and_colon_and_never_a_tilde() -> None:
    identity = forecast_point_identity(make_point(issuance_seq=2))
    assert "~" not in identity
    assert identity.count("^") >= 4
    assert identity.endswith(":2")
    assert identity.startswith("KMIA^NBM_NBS^4.2^TXN^")
    assert forecast_point_identity(make_point()) != identity


def test_no_tilde_literal_appears_in_any_identifier_or_path_the_module_builds() -> None:
    """No tilde in any executable string -- separators, paths, messages.

    Docstrings are exempt and only docstrings: Sphinx cross-reference roles
    (``:class:`~pkg.Name```) legitimately carry one, and banning them would
    push the module toward less precise documentation for no safety gain. Every
    OTHER string literal is a value the module can put into an identifier or a
    path, and there the tilde is banned repo-wide.
    """
    tree = ast.parse(inspect.getsource(forecast_catalog_module))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    assert literals  # the scan must actually have something to scan
    assert not [text for text in literals if "~" in text]


def test_the_module_imports_neither_runtime_nor_adapters() -> None:
    tree = ast.parse(inspect.getsource(forecast_catalog_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    assert not any(
        name.startswith(("breezy.runtime", "breezy.adapters")) for name in imported
    )
