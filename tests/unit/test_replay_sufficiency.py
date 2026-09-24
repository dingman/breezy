"""Unit tests for `src/breezy/analysis/replay_sufficiency.py` (RED first, AUD-09a).

Pure core: every test builds synthetic `InstanceSpan` values directly, never
touching a real feather tape or catalog -- that I/O belongs to
`scripts/analysis/replay_sufficiency_census.py` and is exercised by
`test_replay_sufficiency_census.py` instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import get_args

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from cli_basis_offer_gate_scan import InstanceVerdict as ScriptInstanceVerdict

from breezy.analysis.replay_sufficiency import (
    AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN,
    CORRUPT_ONLY,
    DEPTH_WINDOW_UNDER_30MIN,
    NO_CLEAN_INSTANCE,
    NO_IN_WINDOW_DEPTH,
    REPLAY_SUFFICIENCY_REASONS,
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    VENUE_NEVER_LISTED_UNCONFIRMED,
    DuplicateReplaySufficiencyRecordError,
    InstanceSpan,
    InstanceVerdict,
    ReplaySufficiency,
    UnknownReplaySufficiencySchemaError,
    classify_station_day,
    read_replay_sufficiency,
    write_replay_sufficiency,
)

STATION = "SFO"
CLIMATE_DAY = "2026-09-01"
COMPUTED_DAY = "2026-09-24"


def _span(
    *,
    instance_id: str = "instance-1",
    verdict: str = "CLEAN",
    depth_window_minutes: float = 0.0,
    quote_window_minutes: float = 0.0,
    distinct_instruments: int = 1,
) -> InstanceSpan:
    return InstanceSpan(
        instance_id=instance_id,
        verdict=verdict,  # type: ignore[arg-type]
        depth_window_minutes=depth_window_minutes,
        quote_window_minutes=quote_window_minutes,
        distinct_instruments=distinct_instruments,
    )


def test_two_clean_instances_each_ge_30min_are_ambiguous_not_first_listed() -> None:
    first = _span(instance_id="zzz-listed-first", depth_window_minutes=45.0)
    second = _span(instance_id="aaa-listed-second", depth_window_minutes=60.0)

    result = classify_station_day(
        station=STATION,
        climate_day=CLIMATE_DAY,
        instances=[first, second],
        computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "INSUFFICIENT"
    assert result.reason == AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN
    assert result.winner_instance_id is None


def test_a_depth_only_day_is_sufficient() -> None:
    span = _span(depth_window_minutes=45.0, quote_window_minutes=0.0)

    result = classify_station_day(
        station=STATION, climate_day=CLIMATE_DAY, instances=[span], computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "SUFFICIENT"
    assert result.reason == ""
    assert result.winner_instance_id == span.instance_id
    assert result.depth_window_minutes == 45.0


def test_a_quote_only_day_has_no_in_window_depth() -> None:
    span = _span(depth_window_minutes=0.0, quote_window_minutes=90.0)

    result = classify_station_day(
        station=STATION, climate_day=CLIMATE_DAY, instances=[span], computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "INSUFFICIENT"
    assert result.reason == NO_IN_WINDOW_DEPTH
    assert result.winner_instance_id is None


def test_a_29_minute_depth_span_is_under_the_30_minute_floor() -> None:
    span = _span(depth_window_minutes=29.0)

    result = classify_station_day(
        station=STATION, climate_day=CLIMATE_DAY, instances=[span], computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "INSUFFICIENT"
    assert result.reason == DEPTH_WINDOW_UNDER_30MIN


def test_no_clean_instance_when_only_live_or_empty_instances_exist() -> None:
    span = _span(verdict="LIVE", depth_window_minutes=999.0)

    result = classify_station_day(
        station=STATION, climate_day=CLIMATE_DAY, instances=[span], computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "INSUFFICIENT"
    assert result.reason == NO_CLEAN_INSTANCE


def test_all_corrupt_instances_yield_corrupt_only_never_selected() -> None:
    span = _span(verdict="CORRUPT")

    result = classify_station_day(
        station=STATION, climate_day=CLIMATE_DAY, instances=[span], computed_day=COMPUTED_DAY,
    )

    assert result.verdict == "INSUFFICIENT"
    assert result.reason == CORRUPT_ONLY
    assert result.winner_instance_id is None


def test_the_reason_alphabet_contains_no_bare_venue_never_listed() -> None:
    assert "VENUE_NEVER_LISTED" not in REPLAY_SUFFICIENCY_REASONS
    assert VENUE_NEVER_LISTED_UNCONFIRMED in REPLAY_SUFFICIENCY_REASONS


def test_instance_span_verdict_alphabet_equals_the_scripts_instance_verdict() -> None:
    """B15: pinned equal so the two literal alphabets cannot silently drift."""
    assert set(get_args(InstanceVerdict)) == set(get_args(ScriptInstanceVerdict))


def test_read_replay_sufficiency_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "replay_sufficiency.jsonl"
    path.write_text(
        json.dumps({"schema_version": 2, "station": STATION, "climate_day": CLIMATE_DAY}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(UnknownReplaySufficiencySchemaError) as excinfo:
        read_replay_sufficiency(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "1" in message  # line number
    assert "2" in message  # the unknown version seen


def test_read_replay_sufficiency_refuses_a_duplicate_station_climate_day(tmp_path: Path) -> None:
    import dataclasses

    path = tmp_path / "replay_sufficiency.jsonl"
    row = ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=STATION,
        climate_day=CLIMATE_DAY,
        verdict="SUFFICIENT",
        reason="",
        winner_instance_id="instance-1",
        depth_window_minutes=45.0,
        quote_window_minutes=0.0,
        distinct_instruments=1,
        computed_day=COMPUTED_DAY,
    )
    # Two independently-written lines sharing one (station, climate_day) key --
    # never written via `write_replay_sufficiency`, which itself de-dupes by
    # construction; this simulates two racing writers.
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(2):
            handle.write(json.dumps(dataclasses.asdict(row)) + "\n")

    with pytest.raises(DuplicateReplaySufficiencyRecordError) as excinfo:
        read_replay_sufficiency(path)

    assert STATION in str(excinfo.value)


def test_write_replay_sufficiency_is_byte_idempotent_regardless_of_input_order(
    tmp_path: Path,
) -> None:
    row_a = ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station="LAX",
        climate_day=CLIMATE_DAY,
        verdict="INSUFFICIENT",
        reason=NO_CLEAN_INSTANCE,
        winner_instance_id=None,
        depth_window_minutes=0.0,
        quote_window_minutes=0.0,
        distinct_instruments=0,
        computed_day=COMPUTED_DAY,
    )
    row_b = ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=STATION,
        climate_day=CLIMATE_DAY,
        verdict="SUFFICIENT",
        reason="",
        winner_instance_id="instance-1",
        depth_window_minutes=45.0,
        quote_window_minutes=0.0,
        distinct_instruments=1,
        computed_day=COMPUTED_DAY,
    )
    path_forward = tmp_path / "forward.jsonl"
    path_reverse = tmp_path / "reverse.jsonl"

    write_replay_sufficiency(path_forward, [row_a, row_b])
    write_replay_sufficiency(path_reverse, [row_b, row_a])

    assert path_forward.read_bytes() == path_reverse.read_bytes()
