"""RED-first tests for the 6c append-only scored-trial parquet store."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from breezy.persistence.scored_trial_store import (
    SCORED_TRIAL_SCHEMA,
    read_scored_trials,
    write_scored_trials,
)
from breezy.settlement.trial_scorer import ScoredTrial

_BASE_NS = int(dt.datetime(2026, 9, 1, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _scored(**overrides: object) -> ScoredTrial:
    kwargs: dict[str, object] = {
        "trial_id": "current_rung_hold/trial/LAX/2026-08-31",
        "station": "LAX",
        "climate_day": "2026-08-31",
        "instrument_id": "LAX-2026-08-31-gte78lt80f",
        "settlement_tmax_f": 79,
        "held": True,
        "pnl": Decimal("0.570000000000000000001"),
        "revision_seq": 1,
        "raw_sha256": "a" * 64,
        "scored_at_ns": _BASE_NS,
        "score_seq": 0,
        "settlement_basis": "nws_final",
        "excluded_reason": None,
        "slippage": Decimal("0.02"),
        "entry_ask": Decimal("0.40"),
        "fill_px": Decimal("0.42"),
        "fee": Decimal("0.01"),
    }
    kwargs.update(overrides)
    return ScoredTrial(**kwargs)  # type: ignore[arg-type]


def test_a_written_run_round_trips_every_decimal_exactly(tmp_path: Path) -> None:
    trial = _scored()
    write_scored_trials(tmp_path, [trial], now_ns=_BASE_NS)
    rows = read_scored_trials(tmp_path)
    assert len(rows) == 1
    assert rows[0].pnl == trial.pnl
    assert rows[0].slippage == trial.slippage
    assert rows[0].entry_ask == trial.entry_ask
    assert rows[0].fill_px == trial.fill_px
    assert rows[0].fee == trial.fee
    assert isinstance(rows[0].pnl, Decimal)


def test_a_second_run_appends_a_file_and_never_rewrites_the_first(tmp_path: Path) -> None:
    first = write_scored_trials(tmp_path, [_scored()], now_ns=_BASE_NS)
    second = write_scored_trials(
        tmp_path, [_scored(trial_id="other", score_seq=0)], now_ns=_BASE_NS + 1
    )
    assert first != second
    assert first.exists()
    assert second.exists()
    files = sorted(tmp_path.glob("scored_trials_*.parquet"))
    assert len(files) == 2


def test_reading_an_empty_directory_returns_no_rows_not_an_error(tmp_path: Path) -> None:
    assert read_scored_trials(tmp_path) == ()
    missing = tmp_path / "does-not-exist"
    assert read_scored_trials(missing) == ()


def test_the_schema_is_pinned_column_for_column() -> None:
    names = SCORED_TRIAL_SCHEMA.names
    assert names == [
        "trial_id",
        "station",
        "climate_day",
        "instrument_id",
        "settlement_tmax_f",
        "held",
        "pnl",
        "revision_seq",
        "raw_sha256",
        "scored_at_ns",
        "score_seq",
        "settlement_basis",
        "excluded_reason",
        "slippage",
        "entry_ask",
        "fill_px",
        "fee",
    ]


def test_a_re_scored_trial_dedupes_to_the_highest_score_seq(tmp_path: Path) -> None:
    write_scored_trials(tmp_path, [_scored(score_seq=0, held=True)], now_ns=_BASE_NS)
    write_scored_trials(
        tmp_path, [_scored(score_seq=1, held=False, raw_sha256="b" * 64)], now_ns=_BASE_NS + 1
    )
    rows = read_scored_trials(tmp_path)
    assert len(rows) == 1
    assert rows[0].score_seq == 1
    assert rows[0].held is False
