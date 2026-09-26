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

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import hypothesis_register
from hypothesis_register import (
    ARCHIVE_RECAL_FREEZE_COMMIT,
    ARCHIVE_RECAL_HYPOTHESIS_CLASS,
    ARCHIVE_RECAL_HYPOTHESIS_ID,
    ARCHIVE_RECAL_MDE,
    ARCHIVE_RECAL_PLAUSIBILITY_BOUND,
    ARCHIVE_RECAL_REFERENCE_ASK,
    FORECAST_TAKER_HYPOTHESIS_ID,
    FORECAST_TAKER_K_VARIANTS,
    NO_SIDE_FREEZE_COMMIT,
    NO_SIDE_HYPOTHESIS_CLASS,
    NO_SIDE_HYPOTHESIS_ID,
    NO_SIDE_MDE,
    NO_SIDE_PLAUSIBILITY_BOUND,
    NO_SIDE_REFERENCE_ASK,
    UnexpectedRegistrationStatusError,
    default_derived_root,
    ledger_path,
    main,
    register_archive_recal_underpowered,
    register_forecast_taker_closed_disposition,
    register_no_side_underpowered,
)

from breezy.analysis.hypothesis_ledger import (
    MDE_MISMATCH_TOLERANCE,
    DuplicateHypothesisIdError,
    programme_budget_remaining,
    read_hypothesis_ledger,
    recompute_mde,
    write_hypothesis_ledger,
)

#: A syntactically-valid 40-hex placeholder for CLI-path tests, which (per
#: the added `--freeze-commit` format check) can no longer use the
#: pre-existing direct-call placeholder `"deadbee"`. Direct-call tests below
#: keep using `"deadbee"` unchanged -- the functions never validate format,
#: only `main()` does.
_VALID_FREEZE_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

RULING_PATH = (
    REPO_ROOT / "docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md"
)

ARCHIVE_RECAL_RULING_PATH = (
    REPO_ROOT / "docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md"
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
            _VALID_FREEZE_SHA,
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
        _VALID_FREEZE_SHA,
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


# --- AUD-18 remainder (2026-09-25): check-before-write registrar + NO-SIDE ---


def test_no_side_constants_match_ruling_lines() -> None:
    """T1: assert against prose/code-span numbers in the ruling text, never
    against a bold markdown table cell (e.g. `**1**`, `**300**`) -- those are
    easy to satisfy by coincidence."""
    text = RULING_PATH.read_text(encoding="utf-8")
    assert "`hypothesis_id` | `H-NO-SIDE-2026-09`" in text
    assert "`hypothesis_class` | `no_side_hunting`" in text
    assert "`freeze_commit` | `49261a5c2119fc621863ad7df05af1e2a96c6b55`" in text
    assert "per_variant_alpha=0.0125" in text
    assert "3.08302/34.6410 = 0.0890" in text
    assert "Reference ask `a=0.30`" in text
    assert "0.0695" in text
    assert "mde_plausibility_bound = 0.04" in text
    assert "MDE (0.0890) > mde_plausibility_bound (0.04)" in text
    assert "ENDORSED as-is" in text

    assert NO_SIDE_HYPOTHESIS_ID == "H-NO-SIDE-2026-09"
    assert NO_SIDE_HYPOTHESIS_CLASS == "no_side_hunting"
    assert NO_SIDE_FREEZE_COMMIT == "49261a5c2119fc621863ad7df05af1e2a96c6b55"
    assert NO_SIDE_PLAUSIBILITY_BOUND == 0.04
    assert NO_SIDE_REFERENCE_ASK == 0.30

    recomputed = recompute_mde(per_variant_alpha=0.0125, n_station_days=300)
    assert abs(recomputed - NO_SIDE_MDE) <= MDE_MISMATCH_TOLERANCE


def test_register_underpowered_no_side_writes_zero_look_record(tmp_path: Path) -> None:
    """T2."""
    path = ledger_path(tmp_path)
    record = register_no_side_underpowered(path=path, registered_at="2026-09-25")

    assert record.hypothesis_id == NO_SIDE_HYPOTHESIS_ID
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert record.allocated_alpha == 0.0
    assert record.per_variant_alpha == 0.0
    assert record.is_zero_look is True
    assert record.look_policy == "SINGLE_LOOK"
    assert record.mde_fee_theta == pytest.approx(0.0695)
    assert record.order_quantity == 1
    assert record.station_day_statistic == "MEAN_EXCESS_PER_TAKE"
    assert record.freeze_commit == NO_SIDE_FREEZE_COMMIT

    round_tripped = read_hypothesis_ledger(path)
    assert round_tripped == (record,)
    assert programme_budget_remaining(round_tripped) == 4


def test_registered_outcome_leaves_ledger_bytes_and_mtime_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3: under the OLD write order (compute, then write unconditionally)
    this monkeypatched design would have been silently persisted as
    `REGISTERED`. The check-before-write path refuses it before any bytes
    reach the file."""
    path = ledger_path(tmp_path)
    write_hypothesis_ledger(path, ())
    before_bytes = path.read_bytes()
    before_mtime_ns = path.stat().st_mtime_ns

    monkeypatch.setattr(hypothesis_register, "NO_SIDE_PLAUSIBILITY_BOUND", 0.20)
    with pytest.raises(UnexpectedRegistrationStatusError):
        register_no_side_underpowered(path=path, registered_at="2026-09-25")

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime_ns


def test_second_underpowered_registration_exits_one_file_unchanged(tmp_path: Path) -> None:
    """T4."""
    argv = [
        "--derived-root",
        str(tmp_path),
        "--registered-at",
        "2026-09-25",
        "--register-underpowered",
        NO_SIDE_HYPOTHESIS_ID,
    ]
    assert main(argv) == 0
    path = ledger_path(tmp_path)
    after_first = path.read_bytes()

    assert main(argv) == 1
    assert path.read_bytes() == after_first


def test_append_keeps_closed_line_byte_identical(tmp_path: Path) -> None:
    """T5."""
    path = ledger_path(tmp_path)
    closed = register_forecast_taker_closed_disposition(
        path=path, registered_at="2026-09-20", freeze_commit="deadbee"
    )
    closed_line_before = json.dumps(closed.to_dict(), sort_keys=True)

    register_no_side_underpowered(path=path, registered_at="2026-09-25")

    records = {record.hypothesis_id: record for record in read_hypothesis_ledger(path)}
    closed_line_after = json.dumps(records[FORECAST_TAKER_HYPOTHESIS_ID].to_dict(), sort_keys=True)
    assert closed_line_after == closed_line_before


def test_unknown_hypothesis_is_not_a_registrable_choice(tmp_path: Path) -> None:
    """Supersedes T6 (AUD-18a plan): the refusal property is a preservation
    guard, kept and retargeted from `H-ARCHIVE-RECAL-2026-09` (now
    registrable per its ruling's `The :137 condition is closed.`) to a
    genuinely unknown id. Green immediately -- argparse's `choices` refuses
    it before any ledger file is touched, before this slice's own
    implementation lands."""
    path = ledger_path(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--derived-root",
                str(tmp_path),
                "--registered-at",
                "2026-09-25",
                "--register-underpowered",
                "H-SOME-UNKNOWN-HYPOTHESIS",
            ]
        )
    assert exc_info.value.code == 2
    assert not path.exists()


def test_archive_recal_constants_match_ruling_lines() -> None:
    """T1: pins exact ruling STRINGS, never line numbers (AUD-18a plan r1.1:
    the ruling's line numbers moved +2 when a STATUS line was added on
    09-26). `k_variants` and `min_station_days` are pinned against their
    canonical bold table-cell rows per r1.1's citation correction; every
    other value is pinned against non-bold prose."""
    text = ARCHIVE_RECAL_RULING_PATH.read_text(encoding="utf-8")
    assert "`hypothesis_id` | `H-ARCHIVE-RECAL-2026-09`" in text
    assert "`hypothesis_class` | `pm_us_crh_v4_archive_recalibration`" in text
    assert "| `k_variants` | **1** |" in text
    assert "`min_station_days` (with-takes, §6.1 zero-take rule) | **600** |" in text
    assert "`freeze_commit` | `49261a5c2119fc621863ad7df05af1e2a96c6b55`" in text
    assert "per_variant_alpha=0.0125" in text
    assert "3.08302/48.9898 = 0.0629" in text
    assert "reference ask `a = 0.30`" in text
    assert "theta = 0.0695" in text
    assert "mde_plausibility_bound = 0.03" in text
    assert "MDE (0.0629) > mde_plausibility_bound (0.03)" in text
    assert "CONFIRMED-WITH-NOTES" in text
    assert "The :137 condition is closed." in text

    assert ARCHIVE_RECAL_HYPOTHESIS_ID == "H-ARCHIVE-RECAL-2026-09"
    assert ARCHIVE_RECAL_HYPOTHESIS_CLASS == "pm_us_crh_v4_archive_recalibration"
    assert ARCHIVE_RECAL_FREEZE_COMMIT == "49261a5c2119fc621863ad7df05af1e2a96c6b55"
    assert ARCHIVE_RECAL_PLAUSIBILITY_BOUND == 0.03
    assert ARCHIVE_RECAL_REFERENCE_ASK == 0.30

    recomputed = recompute_mde(per_variant_alpha=0.0125, n_station_days=600)
    assert abs(recomputed - ARCHIVE_RECAL_MDE) <= MDE_MISMATCH_TOLERANCE


def test_register_underpowered_archive_recal_writes_zero_look_record(tmp_path: Path) -> None:
    """T2."""
    path = ledger_path(tmp_path)
    record = register_archive_recal_underpowered(path=path, registered_at="2026-09-25")

    assert record.hypothesis_id == ARCHIVE_RECAL_HYPOTHESIS_ID
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert record.allocated_alpha == 0.0
    assert record.per_variant_alpha == 0.0
    assert record.is_zero_look is True
    assert record.look_policy == "SINGLE_LOOK"
    assert record.mde_fee_theta == pytest.approx(0.0695)
    assert record.order_quantity == 1
    assert record.station_day_statistic == "MEAN_EXCESS_PER_TAKE"
    assert record.freeze_commit == ARCHIVE_RECAL_FREEZE_COMMIT

    round_tripped = read_hypothesis_ledger(path)
    assert round_tripped == (record,)
    assert programme_budget_remaining(round_tripped) == 4


def test_archive_recal_powered_up_design_leaves_ledger_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3: mirrors the NO-SIDE T3 -- monkeypatching the plausibility bound to
    0.20 would power this design up to `REGISTERED` under the OLD write
    order (compute, then write unconditionally). The check-before-write path
    refuses it before any bytes reach the file."""
    path = ledger_path(tmp_path)
    write_hypothesis_ledger(path, ())
    before_bytes = path.read_bytes()
    before_mtime_ns = path.stat().st_mtime_ns

    monkeypatch.setattr(hypothesis_register, "ARCHIVE_RECAL_PLAUSIBILITY_BOUND", 0.20)
    with pytest.raises(UnexpectedRegistrationStatusError):
        register_archive_recal_underpowered(path=path, registered_at="2026-09-25")

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime_ns


def test_archive_recal_cli_second_run_exits_one_file_unchanged(tmp_path: Path) -> None:
    """T4."""
    argv = [
        "--derived-root",
        str(tmp_path),
        "--registered-at",
        "2026-09-26",
        "--register-underpowered",
        ARCHIVE_RECAL_HYPOTHESIS_ID,
    ]
    assert main(argv) == 0
    path = ledger_path(tmp_path)
    after_first = path.read_bytes()

    assert main(argv) == 1
    assert path.read_bytes() == after_first


def test_archive_recal_append_keeps_existing_lines_byte_identical(tmp_path: Path) -> None:
    """T5. AC4: the forecast-taker and NO-side lines stay byte-identical
    after `H-ARCHIVE-RECAL-2026-09` is appended."""
    path = ledger_path(tmp_path)
    closed = register_forecast_taker_closed_disposition(
        path=path, registered_at="2026-09-20", freeze_commit="deadbee"
    )
    closed_line_before = json.dumps(closed.to_dict(), sort_keys=True)

    no_side = register_no_side_underpowered(path=path, registered_at="2026-09-25")
    no_side_line_before = json.dumps(no_side.to_dict(), sort_keys=True)

    register_archive_recal_underpowered(path=path, registered_at="2026-09-26")

    records = {record.hypothesis_id: record for record in read_hypothesis_ledger(path)}
    closed_line_after = json.dumps(records[FORECAST_TAKER_HYPOTHESIS_ID].to_dict(), sort_keys=True)
    no_side_line_after = json.dumps(records[NO_SIDE_HYPOTHESIS_ID].to_dict(), sort_keys=True)
    assert closed_line_after == closed_line_before
    assert no_side_line_after == no_side_line_before


def test_archive_recal_registered_at_before_ruling_date_refused(tmp_path: Path) -> None:
    """Per-hypothesis date gate: `H-ARCHIVE-RECAL-2026-09`'s own ruling date
    (2026-09-25) gates it independently of `NO_SIDE_RULING_DATE`."""
    path = ledger_path(tmp_path)
    exit_code = main(
        [
            "--derived-root",
            str(tmp_path),
            "--registered-at",
            "2026-09-24",
            "--register-underpowered",
            ARCHIVE_RECAL_HYPOTHESIS_ID,
        ]
    )
    assert exit_code == 2
    assert not path.exists()


def test_non_hex_freeze_commit_refused(tmp_path: Path) -> None:
    """T7."""
    path = ledger_path(tmp_path)
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
    assert exit_code == 2
    assert not path.exists()


def test_registered_at_before_ruling_date_refused(tmp_path: Path) -> None:
    """T8."""
    path = ledger_path(tmp_path)
    exit_code = main(
        [
            "--derived-root",
            str(tmp_path),
            "--registered-at",
            "2026-09-24",
            "--register-underpowered",
            NO_SIDE_HYPOTHESIS_ID,
        ]
    )
    assert exit_code == 2
    assert not path.exists()


def test_freeze_commit_with_underpowered_refused(tmp_path: Path) -> None:
    """T9."""
    path = ledger_path(tmp_path)
    exit_code = main(
        [
            "--derived-root",
            str(tmp_path),
            "--registered-at",
            "2026-09-25",
            "--freeze-commit",
            NO_SIDE_FREEZE_COMMIT,
            "--register-underpowered",
            NO_SIDE_HYPOTHESIS_ID,
        ]
    )
    assert exit_code == 2
    assert not path.exists()
