"""Unit tests for `scripts/analysis/mos_txn_occupancy.py` (FC-0a TXN occupancy measurement).

Pure parsing/aggregation tests only -- no network, no real MOS fetch. Every
fixture is a small synthetic CSV body, matching
`test_forecast_txn_climate_day_cli_alignment.py`'s module-loading convention.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_HEADER = "runtime,ftime,model,station,txn,xnd"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def occ() -> ModuleType:
    return _load_module("mos_txn_occupancy")


def _csv(*data_lines: str) -> str:
    return "\n".join((_HEADER, *data_lines)) + "\n"


class TestParseMosTxnRows:
    def test_empty_body_returns_no_rows(self, occ: ModuleType) -> None:
        assert occ.parse_mos_txn_rows("") == ()

    def test_html_error_body_returns_no_rows(self, occ: ModuleType) -> None:
        assert occ.parse_mos_txn_rows("<html>error</html>") == ()

    def test_header_only_returns_no_rows(self, occ: ModuleType) -> None:
        assert occ.parse_mos_txn_rows(_HEADER + "\n") == ()

    def test_missing_required_column_returns_no_rows(self, occ: ModuleType) -> None:
        text = "runtime,ftime,model,station,tmp\n2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,55\n"
        assert occ.parse_mos_txn_rows(text) == ()

    def test_row_with_empty_txn_is_parsed_with_empty_string(self, occ: ModuleType) -> None:
        text = _csv("2026-09-01 00:00:00,2026-09-01 03:00:00,NBS,KLAX,,")
        rows = occ.parse_mos_txn_rows(text)
        assert len(rows) == 1
        assert rows[0].txn == ""
        assert rows[0].txn_present is False

    def test_row_with_populated_txn_is_parsed(self, occ: ModuleType) -> None:
        text = _csv("2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,72,X")
        rows = occ.parse_mos_txn_rows(text)
        assert len(rows) == 1
        row = rows[0]
        assert row.station == "KLAX"
        assert row.runtime == "2026-09-01 00:00:00"
        assert row.ftime == "2026-09-01 06:00:00"
        assert row.txn == "72"
        assert row.xnd == "X"
        assert row.txn_present is True

    def test_two_rows_one_empty_one_populated(self, occ: ModuleType) -> None:
        text = _csv(
            "2026-09-01 00:00:00,2026-09-01 03:00:00,NBS,KLAX,,",
            "2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,72,X",
        )
        rows = occ.parse_mos_txn_rows(text)
        assert len(rows) == 2
        assert [row.txn_present for row in rows] == [False, True]


class TestHourExtraction:
    def test_ftime_hour_parses_space_separated_datetime(self, occ: ModuleType) -> None:
        row = occ.MosTxnRow(
            station="KLAX", runtime="2026-09-01 00:00:00", ftime="2026-09-01 06:00:00", txn="", xnd=""
        )
        assert occ.ftime_hour(row) == 6
        assert occ.runtime_hour(row) == 0

    def test_unparseable_ftime_returns_none(self, occ: ModuleType) -> None:
        row = occ.MosTxnRow(station="KLAX", runtime="", ftime="not-a-date", txn="", xnd="")
        assert occ.ftime_hour(row) is None
        assert occ.runtime_hour(row) is None


class TestOccupancyByHour:
    def test_counts_total_and_nonempty_per_ftime_hour(self, occ: ModuleType) -> None:
        text = _csv(
            "2026-09-01 00:00:00,2026-09-01 03:00:00,NBS,KLAX,,",
            "2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,72,X",
            "2026-09-01 06:00:00,2026-09-01 09:00:00,NBS,KLAX,,",
            "2026-09-01 06:00:00,2026-09-02 06:00:00,NBS,KLAX,55,N",
        )
        rows = occ.parse_mos_txn_rows(text)
        by_ftime = occ.occupancy_by_ftime_hour(rows)
        assert by_ftime[3].total == 1
        assert by_ftime[3].non_empty == 0
        assert by_ftime[3].occupancy_rate == 0.0
        assert by_ftime[6].total == 2
        assert by_ftime[6].non_empty == 2
        assert by_ftime[6].occupancy_rate == 1.0
        assert by_ftime[9].total == 1
        assert by_ftime[9].non_empty == 0

    def test_occupancy_by_runtime_hour(self, occ: ModuleType) -> None:
        text = _csv(
            "2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,72,X",
            "2026-09-01 12:00:00,2026-09-01 18:00:00,NBS,KLAX,,",
        )
        rows = occ.parse_mos_txn_rows(text)
        by_runtime = occ.occupancy_by_runtime_hour(rows)
        assert by_runtime[0] == occ.OccupancyBucket(total=1, non_empty=1)
        assert by_runtime[12] == occ.OccupancyBucket(total=1, non_empty=0)

    def test_empty_rows_yields_empty_mapping(self, occ: ModuleType) -> None:
        assert occ.occupancy_by_ftime_hour(()) == {}


class TestXndValueCounts:
    def test_counts_only_nonempty_txn_rows(self, occ: ModuleType) -> None:
        text = _csv(
            "2026-09-01 00:00:00,2026-09-01 03:00:00,NBS,KLAX,,Z",
            "2026-09-01 00:00:00,2026-09-01 06:00:00,NBS,KLAX,72,X",
            "2026-09-01 06:00:00,2026-09-02 06:00:00,NBS,KLAX,55,N",
            "2026-09-01 06:00:00,2026-09-02 06:00:00,NBS,KLAX,58,X",
        )
        rows = occ.parse_mos_txn_rows(text)
        counts = occ.xnd_value_counts_for_nonempty_txn(rows)
        assert counts == {"X": 2, "N": 1}
        assert "Z" not in counts
