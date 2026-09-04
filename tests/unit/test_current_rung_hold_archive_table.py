"""RED->GREEN tests for the frozen `current_rung_hold` archive p_hold table.

Spec: `docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md` §2
(`archive_table.py`) and the CONVERGED amendment 5 (generator +
`test_regenerating_the_frozen_table_is_byte_identical`). Cross-checked
against `docs/evidence/mb_current_rung_edge_2026-09-02.md` Part A -- the
published memo rows and the independent-audit MDW/SON/h12/m=0 recomputation
quoted at the top of that memo.

The regeneration test reads the REAL on-disk archive corpus
(`~/.local/share/breezy/archive/settlement-alignment-cache`). If that corpus
is absent in the test environment the test SKIPS with the exact reason --
never fabricates a substitute corpus or a substitute result.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_ARCHIVE_TABLE_PATH = (
    _REPO_ROOT / "src" / "breezy" / "strategy" / "current_rung_hold" / "archive_table.py"
)
_MEMO_PATH = _REPO_ROOT / "docs" / "evidence" / "mb_current_rung_edge_2026-09-02.md"

#: `mb_current_rung_edge_study`'s own default corpus cache dir -- the same
#: path the generator uses when `--archive-cache-dir` is not given.
_DEFAULT_ARCHIVE_CACHE_DIR = Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"

_TIMESTAMP_LINE_RE = re.compile(r"^Generated at \(UTC\): .*$", re.MULTILINE)

_STATIONS = frozenset({"SFO", "MIA", "MDW", "LAX", "KNYC", "NYC"})
_SEASONS = frozenset({"DJF", "MAM", "JJA", "SON"})
_WIDTH_CODES = frozenset({0, 1, 2})


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    return _load_module(
        _SCRIPTS_ANALYSIS_DIR / "generate_current_rung_hold_archive_table.py",
        "generate_current_rung_hold_archive_table",
    )


@pytest.fixture(scope="module")
def archive_table() -> ModuleType:
    if not _ARCHIVE_TABLE_PATH.exists():
        pytest.fail(
            f"the frozen table does not exist yet at {_ARCHIVE_TABLE_PATH}; "
            "run the generator before these tests can pass"
        )
    return _load_module(_ARCHIVE_TABLE_PATH, "breezy.strategy.current_rung_hold.archive_table")


def _strip_timestamp(source: str) -> str:
    return _TIMESTAMP_LINE_RE.sub("Generated at (UTC): <stripped>", source)


def test_regenerating_the_frozen_table_is_byte_identical_modulo_timestamp(
    generator: ModuleType,
) -> None:
    if not _DEFAULT_ARCHIVE_CACHE_DIR.is_dir():
        pytest.skip(
            "archive corpus absent in this environment: "
            f"{_DEFAULT_ARCHIVE_CACHE_DIR} does not exist"
        )
    if not _ARCHIVE_TABLE_PATH.exists():
        pytest.fail(
            f"the frozen table does not exist yet at {_ARCHIVE_TABLE_PATH}; "
            "run the generator once to produce it before this test can compare"
        )
    frozen_source = _ARCHIVE_TABLE_PATH.read_text(encoding="utf-8")
    regenerated_source, _table, _sha = generator.generate(argv=[])
    assert _strip_timestamp(regenerated_source) == _strip_timestamp(frozen_source)


@dataclass(frozen=True, slots=True)
class _MemoRow:
    station: str
    season: str
    hour: int
    width: str
    m: int | None
    n: int
    holds: int
    wilson_lower: Decimal


def _parse_memo_part_a_rows() -> list[_MemoRow]:
    text = _MEMO_PATH.read_text(encoding="utf-8")
    rows: list[_MemoRow] = []
    row_re = re.compile(
        r"^\|\s*([A-Z]+)\s*\|\s*(DJF|MAM|JJA|SON)\s*\|\s*(\d+)\s*\|\s*"
        r"(interior_2F|open_upper|open_lower)\s*\|\s*([01-]|-)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|"
        r"\s*[\d.]+\s*\|\s*([\d.]+)\s*\|\s*$",
        re.MULTILINE,
    )
    for match in row_re.finditer(text):
        station, season, hour, width, m_raw, n, holds, wilson_lower = match.groups()
        rows.append(
            _MemoRow(
                station=station,
                season=season,
                hour=int(hour),
                width=width,
                m=None if m_raw == "-" else int(m_raw),
                n=int(n),
                holds=int(holds),
                wilson_lower=Decimal(wilson_lower),
            )
        )
    assert rows, f"no Part A rows parsed from {_MEMO_PATH}"
    return rows


def test_the_frozen_table_reproduces_every_published_memo_row(
    archive_table: ModuleType,
) -> None:
    width_codes = {"interior_2F": 0, "open_upper": 1, "open_lower": 2}
    for row in _parse_memo_part_a_rows():
        width_code = width_codes[row.width]
        m_code = 0 if row.m is None else row.m
        key = (row.station, row.season, row.hour, width_code, m_code)
        value = archive_table.P_HOLD_LOWER.get(key)
        assert value is not None, f"missing/underpowered cell for memo row {row}"
        assert value == row.wilson_lower, f"mismatch for memo row {row}: got {value}"


def test_the_frozen_table_reproduces_the_audited_mdw_son_h12_m0_cell(
    archive_table: ModuleType,
) -> None:
    # Independent-audit recomputation quoted verbatim at the top of the memo:
    # "MDW-SON-h12 m=0 reproduced exactly (n=455, 291 holds, Wilson-lower 0.5944)".
    key = ("MDW", "SON", 12, 0, 0)
    value = archive_table.P_HOLD_LOWER.get(key)
    assert value is not None
    assert value == Decimal("0.5944")


def test_every_value_is_decimal_or_none_and_keys_are_well_formed(
    archive_table: ModuleType,
) -> None:
    table = archive_table.P_HOLD_LOWER
    assert len(table) > 0
    for key, value in table.items():
        station, season, hour, width_code, m_code = key
        assert isinstance(station, str) and station in _STATIONS
        assert isinstance(season, str) and season in _SEASONS
        assert isinstance(hour, int) and 0 <= hour <= 23
        assert isinstance(width_code, int) and width_code in _WIDTH_CODES
        assert isinstance(m_code, int) and m_code in {0, 1}
        assert value is None or isinstance(value, Decimal)
        if isinstance(value, Decimal):
            assert Decimal(0) <= value <= Decimal(1)


def test_the_module_is_immutable(archive_table: ModuleType) -> None:
    with pytest.raises(TypeError):
        archive_table.P_HOLD_LOWER[("MDW", "SON", 12, 0, 0)] = Decimal("0.1")

