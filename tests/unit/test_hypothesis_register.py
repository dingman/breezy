"""Unit tests for `scripts/analysis/hypothesis_register.py` (AUD-18 Slice A,
plan step 7).

Every test writes into `tmp_path` via an explicit `path=`/`--derived-root`
override -- NEVER against the real derived directory
(`~/.local/share/breezy/derived`). The command the coordinator would run for
real, once a peer-reviewed freeze commit and date are in hand, is:

    BREEZY_PYTHON=.venv/bin/python "$BREEZY_PYTHON" scripts/analysis/hypothesis_register.py \\
        --registered-at 2026-09-20 \\
        --freeze-commit <sha> \\
        --register-forecast-taker-closed

which this test module deliberately never invokes without `--derived-root`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from hypothesis_register import (
    FORECAST_TAKER_HYPOTHESIS_ID,
    FORECAST_TAKER_K_VARIANTS,
    default_derived_root,
    ledger_path,
    main,
    register_forecast_taker_closed_disposition,
)

from breezy.analysis.hypothesis_ledger import (
    DuplicateHypothesisIdError,
    read_hypothesis_ledger,
)


def test_default_derived_root_honours_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BREEZY_DERIVED_ROOT", str(tmp_path))
    assert default_derived_root() == tmp_path


def test_ledger_path_lives_under_hypothesis_subdirectory(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    assert path == tmp_path / "hypothesis" / "hypothesis_ledger.jsonl"


def test_register_forecast_taker_writes_only_under_the_given_path(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    record = register_forecast_taker_closed_disposition(
        path=path, registered_at="2026-09-20", freeze_commit="deadbee"
    )
    assert record.status == "REJECTED"
    assert record.hypothesis_id == FORECAST_TAKER_HYPOTHESIS_ID
    assert record.k_variants == FORECAST_TAKER_K_VARIANTS
    assert record.allocated_alpha == 0.0
    assert record.per_variant_alpha == 0.0
    assert record.is_zero_look is True

    written_files = list(tmp_path.rglob("*"))
    assert [f for f in written_files if f.is_file()] == [path]

    round_tripped = read_hypothesis_ledger(path)
    assert round_tripped == (record,)


def test_duplicate_forecast_taker_registration_is_refused(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    register_forecast_taker_closed_disposition(
        path=path, registered_at="2026-09-20", freeze_commit="deadbee"
    )
    with pytest.raises(DuplicateHypothesisIdError):
        register_forecast_taker_closed_disposition(
            path=path, registered_at="2026-09-21", freeze_commit="deadbee"
        )


def test_cli_main_registers_and_exits_zero(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--derived-root",
            str(tmp_path),
            "--registered-at",
            "2026-09-20",
            "--freeze-commit",
            "deadbee",
            "--register-forecast-taker-closed",
        ]
    )
    assert exit_code == 0
    path = ledger_path(tmp_path)
    records = read_hypothesis_ledger(path)
    assert len(records) == 1
    assert records[0].hypothesis_id == FORECAST_TAKER_HYPOTHESIS_ID


def test_cli_main_refuses_duplicate_with_nonzero_exit(tmp_path: Path) -> None:
    argv = [
        "--derived-root",
        str(tmp_path),
        "--registered-at",
        "2026-09-20",
        "--freeze-commit",
        "deadbee",
        "--register-forecast-taker-closed",
    ]
    assert main(argv) == 0
    assert main(argv) == 1


def test_cli_main_requires_an_action(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--derived-root",
            str(tmp_path),
            "--registered-at",
            "2026-09-20",
            "--freeze-commit",
            "deadbee",
        ]
    )
    assert exit_code == 2
