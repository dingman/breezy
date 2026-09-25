"""Unit tests for `src/breezy/analysis/replay_sufficiency.py` (RED first, AUD-09a;
AUD-09b amendment Rev 2.1 Stage A tests A1-A5, A8, A9).

Pure core: every test builds synthetic `InstanceSpan` values directly, never
touching a real feather tape or catalog -- that I/O belongs to
`scripts/analysis/replay_sufficiency_census.py` and is exercised by
`test_replay_sufficiency_census.py` instead.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path
from typing import get_args

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from cli_basis_offer_gate_scan import InstanceVerdict as ScriptInstanceVerdict
from ma_prelock_winner_ask_study import in_afternoon_window

from breezy.analysis.replay_sufficiency import (
    AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN,
    CORRUPT_ONLY,
    DEPTH_WINDOW_UNDER_30MIN,
    NO_CLEAN_INSTANCE,
    NO_IN_WINDOW_DEPTH,
    REPLAY_SUFFICIENCY_REASONS,
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    VENUE_NEVER_LISTED_UNCONFIRMED,
    WINDOW_EDGE_TOLERANCE_NS,
    DuplicateReplaySufficiencyRecordError,
    InstanceSpan,
    InstanceVerdict,
    ReplaySufficiency,
    ReplaySufficiencyRecordError,
    UnknownReplaySufficiencySchemaError,
    classify_station_day,
    count_live_instances_in_window,
    decision_window_ns,
    read_replay_sufficiency,
    window_extent,
    write_replay_sufficiency,
)
from breezy.domain.climate_day import standard_time_zone
from breezy.registry import default_registry

STATION = "SFO"
CLIMATE_DAY = "2026-09-01"
COMPUTED_DAY = "2026-09-24"

_NS_PER_MIN = 60_000_000_000


def _span(
    *,
    instance_id: str = "instance-1",
    verdict: str = "CLEAN",
    depth_window_minutes: float = 0.0,
    quote_window_minutes: float = 0.0,
    distinct_instruments: int = 1,
    first_in_window_ns: int | None = None,
    last_in_window_ns: int | None = None,
) -> InstanceSpan:
    return InstanceSpan(
        instance_id=instance_id,
        verdict=verdict,  # type: ignore[arg-type]
        depth_window_minutes=depth_window_minutes,
        quote_window_minutes=quote_window_minutes,
        distinct_instruments=distinct_instruments,
        first_in_window_ns=first_in_window_ns,
        last_in_window_ns=last_in_window_ns,
    )


def _full_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        "station": STATION,
        "climate_day": CLIMATE_DAY,
        "verdict": "SUFFICIENT",
        "reason": "",
        "winner_instance_id": "instance-1",
        "depth_window_minutes": 45.0,
        "quote_window_minutes": 10.0,
        "distinct_instruments": 2,
        "computed_day": COMPUTED_DAY,
        "window_start_ns": 1_000,
        "window_end_ns": 2_000,
        "winner_first_in_window_ns": 1_100,
        "winner_last_in_window_ns": 1_900,
        "window_complete": True,
        "live_instance_count": 0,
    }
    payload.update(overrides)
    return payload


def _to_lst_datetime(ts_ns: int, std_utc_offset_hours: float) -> dt.datetime:
    """Mirrors `current_rung_hold.strategy._local_hour`'s own precise
    ns -> tz-aware-datetime construction (never `timestamp()`-based)."""
    seconds, nanos = divmod(ts_ns, 1_000_000_000)
    instant = dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
        microseconds=nanos // 1_000,
    )
    return instant.astimezone(standard_time_zone(std_utc_offset_hours))


# ---------------------------------------------------------------------------
# A1: window_extent excludes D-1, includes D, None with no events.
# ---------------------------------------------------------------------------


def test_a1_window_extent_excludes_d_minus_1_includes_d_and_handles_empty() -> None:
    d = dt.date(2026, 9, 5)
    d_minus_1 = d - dt.timedelta(days=1)
    offset = -8.0
    start_ns, end_ns = decision_window_ns(climate_day=d, std_utc_offset_hours=offset)
    start_ns_d1, _ = decision_window_ns(climate_day=d_minus_1, std_utc_offset_hours=offset)

    fourteen_lst_d1 = start_ns_d1 + 2 * 60 * _NS_PER_MIN  # 14:00 LST on D-1
    fourteen_lst_d = start_ns + 2 * 60 * _NS_PER_MIN  # 14:00 LST on D

    result = window_extent([fourteen_lst_d1, fourteen_lst_d], start_ns=start_ns, end_ns=end_ns)

    assert result.first_ns == fourteen_lst_d
    assert result.last_ns == fourteen_lst_d
    assert result.span_ns == 0  # a single in-window instant has no span

    empty = window_extent([], start_ns=start_ns, end_ns=end_ns)
    assert empty.first_ns is None
    assert empty.last_ns is None
    assert empty.span_ns == 0


# ---------------------------------------------------------------------------
# A2 (Rev 2.1 #3): decision_window_ns bounds agree with the in_afternoon_window
# oracle, at +-1 microsecond around both bounds, for all 5 stations.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("city", ["NYC", "SFO", "MIA", "MDW", "LAX"])
def test_a2_decision_window_ns_bounds_agree_with_the_oracle(city: str) -> None:
    registry = default_registry()
    offset = registry.climate_day_window("polymarket_us", city).std_utc_offset_hours
    d = dt.date(2026, 9, 5)
    start_ns, end_ns = decision_window_ns(climate_day=d, std_utc_offset_hours=offset)

    for ts_ns, expected_in_window in (
        (start_ns - 1_000, False),
        (start_ns, True),
        (end_ns - 1_000, True),
        (end_ns, False),
    ):
        ts_lst = _to_lst_datetime(ts_ns, offset)
        oracle_result = in_afternoon_window(ts_lst, climate_day=d)
        assert oracle_result is expected_in_window, (city, ts_ns, ts_lst)


# ---------------------------------------------------------------------------
# A3 (ARCH B2): a D-1 event contributes nothing; the D instance wins under
# the EXISTING classify_station_day rule.
# ---------------------------------------------------------------------------


def test_a3_d_minus_1_instance_contributes_no_in_window_events_d_instance_wins() -> None:
    d = dt.date(2026, 9, 5)
    d_minus_1 = d - dt.timedelta(days=1)
    offset = -8.0
    start_ns, end_ns = decision_window_ns(climate_day=d, std_utc_offset_hours=offset)
    start_ns_d1, _ = decision_window_ns(climate_day=d_minus_1, std_utc_offset_hours=offset)

    # D-1 instance: real events, but all inside D-1's OWN window -- none of
    # them fall inside D's [start_ns, end_ns).
    d1_events = [start_ns_d1 + 10 * _NS_PER_MIN, start_ns_d1 + 50 * _NS_PER_MIN]
    d1_extent = window_extent(d1_events, start_ns=start_ns, end_ns=end_ns)
    assert d1_extent.first_ns is None  # contributes no in-window events

    # D instance: 60 minutes inside D's own window.
    d_events = [start_ns + 2 * _NS_PER_MIN, start_ns + 62 * _NS_PER_MIN]
    d_extent = window_extent(d_events, start_ns=start_ns, end_ns=end_ns)
    assert d_extent.span_ns == 60 * _NS_PER_MIN

    d1_span = _span(
        instance_id="instance-d-minus-1",
        depth_window_minutes=d1_extent.span_ns / 1_000_000_000 / 60,
        first_in_window_ns=d1_extent.first_ns,
        last_in_window_ns=d1_extent.last_ns,
    )
    d_span = _span(
        instance_id="instance-d",
        depth_window_minutes=d_extent.span_ns / 1_000_000_000 / 60,
        first_in_window_ns=d_extent.first_ns,
        last_in_window_ns=d_extent.last_ns,
    )

    result = classify_station_day(
        station=STATION,
        climate_day=d.isoformat(),
        instances=[d1_span, d_span],
        computed_day=COMPUTED_DAY,
        window_start_ns=start_ns,
        window_end_ns=end_ns,
    )

    assert result.verdict == "SUFFICIENT"
    assert result.reason == ""
    assert result.winner_instance_id == "instance-d"


# ---------------------------------------------------------------------------
# A4: window_complete at the exact 5-minute tolerance boundary.
# ---------------------------------------------------------------------------


def test_a4_window_complete_boundary() -> None:
    d = dt.date(2026, 9, 5)
    offset = -8.0
    start_ns, end_ns = decision_window_ns(climate_day=d, std_utc_offset_hours=offset)

    def _classify(*, first_in_window_ns: int, last_in_window_ns: int) -> ReplaySufficiency:
        span_minutes = (last_in_window_ns - first_in_window_ns) / 1_000_000_000 / 60
        winner = _span(
            instance_id="winner",
            depth_window_minutes=span_minutes,
            first_in_window_ns=first_in_window_ns,
            last_in_window_ns=last_in_window_ns,
        )
        return classify_station_day(
            station=STATION,
            climate_day=d.isoformat(),
            instances=[winner],
            computed_day=COMPUTED_DAY,
            window_start_ns=start_ns,
            window_end_ns=end_ns,
        )

    # A lone 13:00-13:40 winner: 60 min after start, well outside tolerance.
    lone = _classify(
        first_in_window_ns=start_ns + 60 * _NS_PER_MIN,
        last_in_window_ns=start_ns + 100 * _NS_PER_MIN,
    )
    assert lone.verdict == "SUFFICIENT"
    assert lone.window_complete is False

    # A 12:02-16:58 winner: 2 minutes off each edge, well within tolerance.
    full = _classify(
        first_in_window_ns=start_ns + 2 * _NS_PER_MIN, last_in_window_ns=end_ns - 2 * _NS_PER_MIN,
    )
    assert full.window_complete is True

    # Exactly AT the 5-minute tolerance on both edges: still complete (<=).
    at_edge = _classify(
        first_in_window_ns=start_ns + WINDOW_EDGE_TOLERANCE_NS,
        last_in_window_ns=end_ns - WINDOW_EDGE_TOLERANCE_NS,
    )
    assert at_edge.window_complete is True

    # One nanosecond past the tolerance: no longer complete.
    past_edge = _classify(
        first_in_window_ns=start_ns + WINDOW_EDGE_TOLERANCE_NS + 1,
        last_in_window_ns=end_ns - WINDOW_EDGE_TOLERANCE_NS - 1,
    )
    assert past_edge.window_complete is False


# ---------------------------------------------------------------------------
# A5: C4 round-trip is lossless; from_dict raises on missing/extra/wrong-type
# keys; the reader refuses v1.
# ---------------------------------------------------------------------------


def test_a5_to_dict_from_dict_round_trip_is_lossless() -> None:
    row = ReplaySufficiency.from_dict(_full_payload())

    restored = ReplaySufficiency.from_dict(row.to_dict())

    assert restored == row


def test_a5_from_dict_raises_on_a_missing_key() -> None:
    payload = _full_payload()
    del payload["window_complete"]

    with pytest.raises(ReplaySufficiencyRecordError, match="window_complete"):
        ReplaySufficiency.from_dict(payload)


def test_a5_from_dict_raises_on_an_extra_key() -> None:
    payload = _full_payload(bogus_extra_field=1)

    with pytest.raises(ReplaySufficiencyRecordError, match="bogus_extra_field"):
        ReplaySufficiency.from_dict(payload)


def test_a5_from_dict_raises_on_a_wrong_type() -> None:
    payload = _full_payload(window_complete="true")

    with pytest.raises(ReplaySufficiencyRecordError, match="window_complete"):
        ReplaySufficiency.from_dict(payload)


def test_a5_reader_refuses_a_v1_schema_line(tmp_path: Path) -> None:
    path = tmp_path / "replay_sufficiency.jsonl"
    payload = _full_payload(schema_version=1)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(UnknownReplaySufficiencySchemaError):
        read_replay_sufficiency(path)


# ---------------------------------------------------------------------------
# A8: LIVE instances count only when capture start precedes window_end_ns.
# ---------------------------------------------------------------------------


def test_a8_live_instances_count_only_when_capture_start_precedes_window_end() -> None:
    window_end_ns = 1_000_000_000_000

    assert count_live_instances_in_window([window_end_ns - 1], window_end_ns=window_end_ns) == 1
    # Started exactly at (or after) the window's end: registration may cover
    # D+1, but a capture that started after W never captured anything of it.
    assert count_live_instances_in_window([window_end_ns], window_end_ns=window_end_ns) == 0
    assert count_live_instances_in_window([window_end_ns + 1], window_end_ns=window_end_ns) == 0
    assert (
        count_live_instances_in_window(
            [window_end_ns - 5, window_end_ns + 5, window_end_ns - 1000],
            window_end_ns=window_end_ns,
        )
        == 2
    )


# ---------------------------------------------------------------------------
# A9: per-module pin -- replay_sufficiency.py never uses dataclasses.asdict.
# ---------------------------------------------------------------------------


def test_a9_replay_sufficiency_module_never_calls_asdict() -> None:
    source_path = REPO_ROOT / "src/breezy/analysis/replay_sufficiency.py"
    source = source_path.read_text(encoding="utf-8")

    tree = ast.parse(source, filename=str(source_path))

    # No `from dataclasses import asdict` (or `dataclasses.asdict`) binding at
    # all -- docstrings are free to explain why the module refuses it.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            assert all(alias.name != "asdict" for alias in node.names)

    # And no call site anywhere in the module actually invokes it.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert name != "asdict"


# ---------------------------------------------------------------------------
# Pre-existing AUD-09a tests (unchanged behaviour; classify_station_day's
# rule itself is untouched by the AUD-09b amendment -- A3 above).
# ---------------------------------------------------------------------------


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
    payload = _full_payload(schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION + 1)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(UnknownReplaySufficiencySchemaError) as excinfo:
        read_replay_sufficiency(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "1" in message  # line number
    assert str(REPLAY_SUFFICIENCY_SCHEMA_VERSION + 1) in message  # the unknown version seen


def test_read_replay_sufficiency_refuses_a_duplicate_station_climate_day(tmp_path: Path) -> None:
    path = tmp_path / "replay_sufficiency.jsonl"
    row = ReplaySufficiency.from_dict(_full_payload())
    # Two independently-written lines sharing one (station, climate_day) key --
    # never written via `write_replay_sufficiency`, which itself de-dupes by
    # construction; this simulates two racing writers.
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(2):
            handle.write(json.dumps(row.to_dict()) + "\n")

    with pytest.raises(DuplicateReplaySufficiencyRecordError) as excinfo:
        read_replay_sufficiency(path)

    assert STATION in str(excinfo.value)


def test_write_replay_sufficiency_is_byte_idempotent_regardless_of_input_order(
    tmp_path: Path,
) -> None:
    row_a = ReplaySufficiency.from_dict(
        _full_payload(
            station="LAX",
            verdict="INSUFFICIENT",
            reason=NO_CLEAN_INSTANCE,
            winner_instance_id=None,
            depth_window_minutes=0.0,
            quote_window_minutes=0.0,
            distinct_instruments=0,
            winner_first_in_window_ns=None,
            winner_last_in_window_ns=None,
            window_complete=False,
        )
    )
    row_b = ReplaySufficiency.from_dict(_full_payload())
    path_forward = tmp_path / "forward.jsonl"
    path_reverse = tmp_path / "reverse.jsonl"

    write_replay_sufficiency(path_forward, [row_a, row_b])
    write_replay_sufficiency(path_reverse, [row_b, row_a])

    assert path_forward.read_bytes() == path_reverse.read_bytes()
