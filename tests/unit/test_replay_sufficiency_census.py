"""Unit tests for `scripts/analysis/replay_sufficiency_census.py` (RED first, AUD-09a).

The script's own I/O wiring against a real feather/catalog capture is
exercised by the plan's "one real run" (AUD-09 §7 step 3-equivalent for the
census), not by these tests: replicating a real Nautilus `BinaryOption` +
`OrderBookDepth10`/`QuoteTick` capture here would duplicate the fixtures
`test_cli_basis_offer_gate_scan.py` already owns for that purpose without
adding coverage `classify_station_day`'s own pure tests (`test_replay_sufficiency.py`)
do not already provide. What IS unit-tested here is everything this script
owns beyond that classification: the aggregation into one row per
`(station, climate_day)`, the H1 candidate-register contract (missing file,
schema mismatch, one row per candidate, never queued), and that the write
path stays byte-idempotent -- all pure or local-file I/O, all network-free by
the repo-wide socket block (`tests/conftest.py`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from replay_sufficiency_census import (
    STATION_CANDIDATES_SCHEMA_VERSION,
    UnknownStationCandidateSchemaError,
    _candidate_rows_to_replay_sufficiency,
    _read_station_candidates,
    _StationCandidateRow,
    build_census,
)

from breezy.analysis.replay_sufficiency import (
    CANDIDATE_UNSUPPORTED_STATION,
    CORRUPT_ONLY,
    InstanceSpan,
)

COMPUTED_DAY = "2026-09-24"


def _span(verdict: str, depth: float = 0.0, instance_id: str = "instance-1") -> InstanceSpan:
    return InstanceSpan(
        instance_id=instance_id,
        verdict=verdict,  # type: ignore[arg-type]
        depth_window_minutes=depth,
        quote_window_minutes=0.0,
        distinct_instruments=1,
    )


def test_build_census_emits_one_row_per_station_climate_day() -> None:
    spans = {
        ("SFO", "2026-09-01"): [_span("CLEAN", depth=45.0)],
        ("LAX", "2026-09-01"): [_span("CLEAN", depth=10.0)],
    }

    rows = build_census(station_day_spans=spans, computed_day=COMPUTED_DAY)

    keys = {(row.station, row.climate_day) for row in rows}
    assert keys == {("SFO", "2026-09-01"), ("LAX", "2026-09-01")}


def test_build_census_marks_a_corrupt_only_day_corrupt_only_and_never_selected() -> None:
    spans = {("MIA", "2026-08-20"): [_span("CORRUPT")]}

    rows = build_census(station_day_spans=spans, computed_day=COMPUTED_DAY)

    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "INSUFFICIENT"
    assert row.reason == CORRUPT_ONLY
    assert row.winner_instance_id is None


def test_build_census_includes_candidate_rows_alongside_tape_rows() -> None:
    spans = {("SFO", "2026-09-01"): [_span("CLEAN", depth=45.0)]}
    candidate_rows = _candidate_rows_to_replay_sufficiency(
        [
            _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20"),
        ],
        computed_day=COMPUTED_DAY,
    )

    rows = build_census(
        station_day_spans=spans, candidate_rows=candidate_rows, computed_day=COMPUTED_DAY
    )

    assert len(rows) == 2
    candidate_row = next(row for row in rows if row.reason == CANDIDATE_UNSUPPORTED_STATION)
    assert candidate_row.verdict == "INSUFFICIENT"
    assert candidate_row.winner_instance_id is None
    assert candidate_row.climate_day == "2026-09-20"


def _fake_candidate(*, venue: str, city_token: str, last_seen_day: str) -> _StationCandidateRow:
    return _StationCandidateRow(
        schema_version=STATION_CANDIDATES_SCHEMA_VERSION,
        venue=venue,
        city_token=city_token,
        last_seen_day=last_seen_day,
    )


def test_read_station_candidates_missing_file_warns_and_yields_empty_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "station_candidates.jsonl"

    result = _read_station_candidates(missing)

    assert result == ()
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert str(missing) in captured.err


def test_read_station_candidates_parses_one_line_per_candidate(tmp_path: Path) -> None:
    path = tmp_path / "station_candidates.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": STATION_CANDIDATES_SCHEMA_VERSION,
                "venue": "polymarket_us",
                "city_token": "nyc",
                "last_seen_day": "2026-09-20",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _read_station_candidates(path)

    assert len(result) == 1
    assert result[0].venue == "polymarket_us"
    assert result[0].city_token == "nyc"


def test_read_station_candidates_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "station_candidates.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "venue": "polymarket_us",
                "city_token": "nyc",
                "last_seen_day": "2026-09-20",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(UnknownStationCandidateSchemaError) as excinfo:
        _read_station_candidates(path)

    assert str(path) in str(excinfo.value)


def test_candidate_rows_never_enter_the_replay_queue() -> None:
    """H1: a candidate is recorded, never queued -- it always carries the
    closed CANDIDATE_UNSUPPORTED_STATION reason and no winner instance."""
    candidate = _fake_candidate(venue="polymarket_us", city_token="nyc", last_seen_day="2026-09-20")

    rows = _candidate_rows_to_replay_sufficiency([candidate], computed_day=COMPUTED_DAY)

    assert len(rows) == 1
    assert rows[0].reason == CANDIDATE_UNSUPPORTED_STATION
    assert rows[0].verdict == "INSUFFICIENT"
    assert rows[0].winner_instance_id is None
