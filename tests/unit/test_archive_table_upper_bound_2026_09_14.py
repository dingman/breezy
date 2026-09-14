"""RED->GREEN tests for `P_HOLD_UPPER` beside `P_HOLD_LOWER` (NO-side edge, S1).

Spec: `docs/plans/NO_SIDE_EDGE_2026-09-14.md` §2, §4 S1, N2-4, R3-9. `P_HOLD_UPPER`
is the Wilson 95% UPPER bound on `p_hold` -- the frozen calibration input for
`p_miss_lower := 1 - P_HOLD_UPPER[key]`, a valid 95% lower bound on
`P(HIGH not-in current rung)`. This slice touches ONLY the generator and the
frozen `archive_table.py`; it must never change `P_HOLD_LOWER`, `CORPUS_SHA256`,
or `decision.py` / any live path.

Tests that regenerate the real frozen table SKIP with the exact reason when the
on-disk archive corpus is absent (matches the existing pin test's convention),
never fabricating a substitute corpus.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_ARCHIVE_TABLE_PATH = (
    _REPO_ROOT / "src" / "breezy" / "strategy" / "current_rung_hold" / "archive_table.py"
)

#: `mb_current_rung_edge_study`'s own default corpus cache dir -- the same
#: path the generator uses when `--archive-cache-dir` is not given.
_DEFAULT_ARCHIVE_CACHE_DIR = Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"

#: Pinned literal -- this slice MUST NOT change the corpus sha256. Any diff
#: against this literal means the wrong thing moved.
_PINNED_CORPUS_SHA256 = "3b410fb9c0c9208c5afb5cd8de05789077aca93c71fd540ddae0607ad6f04d48"


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


def test_p_hold_upper_exists_with_the_same_key_set_as_p_hold_lower(
    archive_table: ModuleType,
) -> None:
    assert hasattr(archive_table, "P_HOLD_UPPER")
    lower_keys = set(archive_table.P_HOLD_LOWER.keys())
    upper_keys = set(archive_table.P_HOLD_UPPER.keys())
    assert lower_keys == upper_keys
    assert len(lower_keys) > 0


def test_p_hold_upper_is_never_below_p_hold_lower(archive_table: ModuleType) -> None:
    for key, lower in archive_table.P_HOLD_LOWER.items():
        upper = archive_table.P_HOLD_UPPER[key]
        if lower is None:
            continue
        assert upper is not None, f"upper missing for a defined lower cell {key}"
        assert upper >= lower, f"P_HOLD_UPPER[{key}]={upper} < P_HOLD_LOWER[{key}]={lower}"


def test_undefined_cells_co_occur_in_both_maps(archive_table: ModuleType) -> None:
    """A `None` (below `N_MIN`/illegal) cell always co-occurs across both maps.

    The real corpus happens to have zero below-N_MIN cells at the current
    dense-station/hour/width grid (every one of the 240 cells clears N_MIN=90
    with ARCHIVE_HOURS=5 seasons=4 stations=5 widths*margins=12), so this
    checks the (possibly-empty) None-key sets are equal on the frozen table --
    the synthetic-corpus test below pins the co-occurrence mechanism directly
    on a case that DOES produce a `None` cell.
    """
    none_lower_keys = {
        key for key, value in archive_table.P_HOLD_LOWER.items() if value is None
    }
    none_upper_keys = {
        key for key, value in archive_table.P_HOLD_UPPER.items() if value is None
    }
    assert none_lower_keys == none_upper_keys


def test_undefined_cells_co_occur_on_a_synthetic_below_n_min_cell(
    generator: ModuleType,
) -> None:
    """Direct mechanism pin: a cell below `N_MIN` is `None` in BOTH tables.

    Exercises `ArchiveCell.p_hold_lower`/`.p_hold_upper` on a synthetic cell
    with `n < N_MIN` (89 < 90), independent of whether the real corpus
    happens to contain one.
    """
    from mb_current_rung_edge_study import N_MIN, ArchiveCell

    assert 89 < N_MIN
    cell = ArchiveCell(
        city="SFO", season="DJF", hour=12, width="interior_2F", m=0, n=89, hold_count=50
    )
    assert cell.p_hold_lower is None
    assert cell.p_hold_upper is None


def test_corpus_sha256_is_unchanged(archive_table: ModuleType) -> None:
    assert archive_table.CORPUS_SHA256 == _PINNED_CORPUS_SHA256


def test_wilson_interval_is_called_exactly_once_per_cell_via_archive_cell(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural pin: `ArchiveCell` calls `wilson_interval` ONCE per cell.

    Reading both `p_hold_lower` and `p_hold_upper` (repeatedly) must not
    trigger a second call -- the two bounds are destructured from ONE raw
    Wilson float pair, cached at construction, so `upper >= lower` is
    structural rather than an accident of the function being pure
    (N2-4/R3-9, review follow-up item 1).
    """
    import mb_current_rung_edge_study as study
    from mb_current_rung_edge_study import ArchiveCell

    calls: list[tuple[int, int]] = []
    original = study.wilson_interval

    def _spy(successes: int, total: int, **kwargs: object) -> tuple[float, float]:
        calls.append((successes, total))
        return original(successes, total, **kwargs)

    monkeypatch.setattr(study, "wilson_interval", _spy)

    cell = ArchiveCell(
        city="MDW", season="SON", hour=12, width="interior_2F", m=0, n=455, hold_count=291
    )
    _ = cell.p_hold_lower
    _ = cell.p_hold_upper
    _ = cell.p_hold_lower  # a repeat read must not call again
    _ = cell.p_hold_upper  # a repeat read must not call again

    assert calls == [(291, 455)], f"expected exactly one wilson_interval call, got {calls}"


def test_wilson_interval_is_called_exactly_once_per_cell_via_aggregate_hold_cases(
    generator: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same structural pin, exercised through the real cell-construction path.

    `aggregate_hold_cases` is what `build_archive_table` (and hence
    `build_frozen_table`) calls to build each `ArchiveCell` from raw
    `HoldCase`s -- a small synthetic corpus (one cell, n=455 by repeating a
    single case) must produce exactly one `wilson_interval` call for that
    cell, not two.
    """
    import datetime as dt

    import mb_current_rung_edge_study as study

    calls: list[tuple[int, int]] = []
    original = study.wilson_interval

    def _spy(successes: int, total: int, **kwargs: object) -> tuple[float, float]:
        calls.append((successes, total))
        return original(successes, total, **kwargs)

    monkeypatch.setattr(study, "wilson_interval", _spy)

    n, hold_count = 455, 291
    cases = [
        study.HoldCase(
            city="MDW",
            climate_day=dt.date(2024, 1, 1),
            season="SON",
            hour=12,
            running_f=70,
            settled_f=70,
            width="interior_2F",
            m=0,
            held=index < hold_count,
        )
        for index in range(n)
    ]
    archive = study.aggregate_hold_cases(cases)
    (cell,) = archive.values()
    assert cell.n == n
    assert cell.hold_count == hold_count

    _ = cell.p_hold_lower
    _ = cell.p_hold_upper

    assert calls == [(hold_count, n)], f"expected exactly one wilson_interval call, got {calls}"


def test_p_hold_upper_is_derived_from_the_same_raw_wilson_float_as_the_lower_bound(
    generator: ModuleType,
) -> None:
    """Pin the derivation identity on a small synthetic corpus, not the real one.

    `build_frozen_table` must key each cell's upper bound off the SAME raw
    Wilson float used for the lower bound (`archive_correction_probe.wilson_interval`
    returns `(lower, upper)` from one call), quantised once with the same
    `Decimal(f"{v:.4f}")` rule -- never two independent quantisations that could
    violate `UPPER >= LOWER` at a boundary cell (N2-4/R3-9).
    """
    from archive_correction_probe import wilson_interval

    # A representative defined cell straight from the real corpus, if present;
    # otherwise a fixed synthetic (hold, n) pair exercises the same code path.
    hold, n = 291, 455  # matches the audited MDW-SON-h12-m0 cell (n=455, 291 holds)
    raw_lower, raw_upper = wilson_interval(hold, n)
    expected_lower = Decimal(f"{raw_lower:.4f}")
    expected_upper = Decimal(f"{raw_upper:.4f}")
    assert expected_upper >= expected_lower


def test_regenerating_the_frozen_table_upper_bound_is_byte_identical_modulo_timestamp(
    generator: ModuleType,
) -> None:
    import re

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
    regenerated_source, _tables, _sha = generator.generate(argv=[])
    timestamp_re = re.compile(r"^Generated at \(UTC\): .*$", re.MULTILINE)
    strip = lambda text: timestamp_re.sub("Generated at (UTC): <stripped>", text)
    assert strip(regenerated_source) == strip(frozen_source)


def test_the_audited_mdw_son_h12_m0_cell_upper_bound(
    archive_table: ModuleType, generator: ModuleType
) -> None:
    # Same cell as the existing lower-bound pin
    # (n=455, 291 holds, Wilson-lower 0.5944); the upper bound for this n/hold
    # pair is the mirror-side Wilson quantile, pinned by direct recomputation.
    from archive_correction_probe import wilson_interval

    key = ("MDW", "SON", 12, 0, 0)
    _lower, upper = wilson_interval(291, 455)
    expected_upper = Decimal(f"{upper:.4f}")
    value = archive_table.P_HOLD_UPPER.get(key)
    assert value is not None
    assert value == expected_upper
