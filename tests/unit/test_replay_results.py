"""RED-first tests for `breezy.analysis.replay_results` (AUD-09b amendment
§10 item 4: H3 plus the R2 fields; `REPLAY_VALIDITY` unchanged).

Mirrors `tests/unit/test_replay_sufficiency.py`'s own house style: explicit
`to_dict`/`from_dict` round trip (never `dataclasses.asdict`), a refused
unknown `schema_version`, and a refused duplicate key -- but the duplicate
check applies only to TERMINAL outcomes (`COMPLETED`/`RECOVERED`/`FAILED`):
`BLOCKED` rows are expected to repeat under the identical key while a day
stays queued (base plan §6b.3; the runner's stall-escalation counts a RUN
of consecutive `BLOCKED` rows, which requires more than one to ever be
written).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    DuplicateReplayResultError,
    ReplayResult,
    ReplayResultRecordError,
    UnknownReplayResultSchemaError,
    append_replay_result,
    read_replay_results,
    result_key,
)


def _row(**overrides: object) -> ReplayResult:
    base: dict[str, object] = {
        "schema_version": REPLAY_RESULTS_SCHEMA_VERSION,
        "run_ts": "2026-09-25T15:50:00+00:00",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "strategy": "continuous_rung_hold",
        "lag_minutes": 30,
        "outcome": "COMPLETED",
        "validity": REPLAY_VALIDITY,
        "blocked_reason": None,
        "exception_type": None,
        "family_id": "pm_us_crh_v4",
        "manifest_sha256": "a" * 64,
        "manifest_taker_fee_coefficient": "0.0695",
        "engine_required_fee_coefficient": "0.0695",
        "engine_params_source": "FAMILY_MANIFEST",
        "params_match": True,
        "composition_kind": "continuous_rung_hold",
        "tape_instance_id": "5a111bca-0000-0000-0000-000000000000",
        "sufficiency_reason": "",
        "trials": 3,
        "fills": 3,
        "fill_price_vs_decision_ask": ("0.01", "-0.02", "0.00"),
        "refusal_counts": {"no_decision_window_coverage": 0},
        "wall_s": 82.5,
        "peak_rss_bytes": 674_000_000,
        "parquet_sha256": None,
        "window_complete": True,
        "replayed_first_ns": 1_000,
        "replayed_last_ns": 2_000,
        "census_schema_version": 3,
    }
    base.update(overrides)
    return ReplayResult(**base)  # type: ignore[arg-type]


def test_result_key_is_station_climate_day_strategy_lag() -> None:
    row = _row()
    assert result_key(row) == ("SFO", "2026-09-01", "continuous_rung_hold", 30)


def test_to_dict_from_dict_round_trip_is_lossless() -> None:
    row = _row()
    assert ReplayResult.from_dict(row.to_dict()) == row


def test_from_dict_raises_on_a_missing_key() -> None:
    payload = _row().to_dict()
    del payload["station"]
    with pytest.raises(ReplayResultRecordError):
        ReplayResult.from_dict(payload)


def test_from_dict_raises_on_an_extra_key() -> None:
    payload = _row().to_dict()
    payload["unexpected"] = "surprise"
    with pytest.raises(ReplayResultRecordError):
        ReplayResult.from_dict(payload)


def test_from_dict_raises_on_a_wrong_type() -> None:
    payload = _row().to_dict()
    payload["trials"] = "3"
    with pytest.raises(ReplayResultRecordError):
        ReplayResult.from_dict(payload)


def test_a_write_failure_surfaces_its_own_exception_not_a_double_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review fix 8 (MEDIUM): `os.fdopen(fd, ...)` takes ownership of `fd`.
    If a failure happens INSIDE the `with` block (after `fdopen` already
    succeeded), the `with` statement's own `__exit__` already closes `fd`
    while unwinding -- a second `os.close(fd)` in the `except` handler then
    raises its OWN `OSError: Bad file descriptor`, masking the real error.
    Injecting the failure at `os.fsync` (after `fdopen` succeeded) proves
    the ORIGINAL exception surfaces, not the masking one."""
    path = tmp_path / "replay_results.jsonl"

    def _raise_fsync(_fd: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", _raise_fsync)
    with pytest.raises(OSError, match="injected fsync failure"):
        append_replay_result(path, _row())


def test_append_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    row = _row()
    append_replay_result(path, row)
    assert read_replay_results(path) == (row,)


def test_read_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    row = _row(schema_version=REPLAY_RESULTS_SCHEMA_VERSION + 1)
    # Bypass the dataclass's own version-agnostic constructor by writing the
    # line directly -- `append_replay_result` never rejects a caller-chosen
    # schema_version, only `read_replay_results` refuses it (H3, mirrors H0).
    append_replay_result(path, row)
    with pytest.raises(UnknownReplayResultSchemaError):
        read_replay_results(path)


def test_read_refuses_a_duplicate_terminal_key(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    append_replay_result(path, _row(outcome="COMPLETED"))
    append_replay_result(path, _row(outcome="RECOVERED"))
    with pytest.raises(DuplicateReplayResultError):
        read_replay_results(path)


def test_repeated_blocked_rows_under_the_identical_key_are_not_a_duplicate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replay_results.jsonl"
    for _ in range(3):
        append_replay_result(
            path,
            _row(
                outcome="BLOCKED",
                blocked_reason="ASOS_CACHE_EMPTY",
                family_id=None,
                manifest_sha256=None,
                manifest_taker_fee_coefficient=None,
                engine_required_fee_coefficient=None,
                engine_params_source=None,
                params_match=None,
                composition_kind=None,
                tape_instance_id="5a111bca-0000-0000-0000-000000000000",
                trials=0,
                fills=0,
                fill_price_vs_decision_ask=(),
                refusal_counts={},
                wall_s=None,
                peak_rss_bytes=None,
                window_complete=None,
                replayed_first_ns=None,
                replayed_last_ns=None,
            ),
        )
    rows = read_replay_results(path)
    assert len(rows) == 3
    assert all(row.outcome == "BLOCKED" for row in rows)


def test_a_failed_row_after_a_blocked_row_is_not_a_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    append_replay_result(path, _row(outcome="BLOCKED", blocked_reason="ASOS_CACHE_EMPTY"))
    append_replay_result(path, _row(outcome="FAILED", exception_type="ImpossibleFillPriceError"))
    rows = read_replay_results(path)
    assert [row.outcome for row in rows] == ["BLOCKED", "FAILED"]


def test_validity_constant_is_mechanism_only() -> None:
    assert REPLAY_VALIDITY == "MECHANISM_ONLY"


def test_module_does_not_use_dataclasses_asdict() -> None:
    source = Path(
        __file__,
    ).resolve().parents[2] / "src" / "breezy" / "analysis" / "replay_results.py"
    assert "asdict(" not in source.read_text()
