"""RED-first coverage for the shadow resting-bid summary store
(``shadow_rest_store.py``, plan §5/§6 shadow stage) -- mirrors
``test_current_rung_hold_monitor_store.py``'s own write/read-back shape.
"""

from __future__ import annotations

from pathlib import Path

from breezy.strategy.current_rung_hold.resting_decider import REASON_CODES
from breezy.strategy.current_rung_hold.shadow_rest_store import (
    ShadowRestSummary,
    read_shadow_rest_summaries,
    write_shadow_rest_summaries,
)

_NOW_NS = 1_800_000_000_000_000_000


def test_record_reason_tallies_rest_and_reprice_and_cancel_reasons() -> None:
    summary = ShadowRestSummary(station="SFO", climate_day="2026-09-16", leg="YES")
    summary.record_reason("rest")
    summary.record_reason(None)
    summary.record_reason("reprice")
    summary.record_reason("staleness")
    summary.record_reason("staleness")

    assert summary.rests == 1
    assert summary.reprices == 1
    assert summary.cancels["staleness"] == 2
    assert summary.key == "SFO|2026-09-16|YES"


def test_record_reason_ignores_unknown_values() -> None:
    summary = ShadowRestSummary(station="SFO", climate_day="2026-09-16", leg="YES")
    summary.record_reason("not_a_real_reason")
    assert summary.rests == 0
    assert summary.reprices == 0
    assert summary.cancels == {}


def test_to_dict_carries_one_column_per_registered_reason_code() -> None:
    summary = ShadowRestSummary(station="SFO", climate_day="2026-09-16", leg="YES")
    summary.record_reason("halt")
    row = summary.to_dict()
    for reason in REASON_CODES:
        assert f"cancel_{reason}" in row
    assert row["cancel_halt"] == 1
    assert row["cancel_would_cross"] == 0


def test_write_with_no_summaries_writes_nothing(tmp_path: Path) -> None:
    result = write_shadow_rest_summaries(tmp_path / "shadow_rest", [], now_ns=_NOW_NS)
    assert result is None
    assert read_shadow_rest_summaries(tmp_path / "shadow_rest") == ()


def test_write_then_read_back_round_trips_every_field(tmp_path: Path) -> None:
    directory = tmp_path / "shadow_rest"
    summary = ShadowRestSummary(
        station="SFO",
        climate_day="2026-09-16",
        leg="YES",
        ticks_evaluated=42,
        still_resting_at_stop=True,
    )
    summary.record_reason("rest")
    summary.record_reason("reprice")
    summary.record_reason("reprice")
    summary.record_reason("window_close")

    path = write_shadow_rest_summaries(directory, [summary], now_ns=_NOW_NS)
    assert path is not None
    assert path.exists()

    read_back = read_shadow_rest_summaries(directory)
    assert len(read_back) == 1
    restored = read_back[0]
    assert restored.station == "SFO"
    assert restored.climate_day == "2026-09-16"
    assert restored.leg == "YES"
    assert restored.ticks_evaluated == 42
    assert restored.rests == 1
    assert restored.reprices == 2
    assert restored.cancels["window_close"] == 1
    assert restored.still_resting_at_stop is True


def test_a_second_write_never_overwrites_the_first(tmp_path: Path) -> None:
    directory = tmp_path / "shadow_rest"
    first = ShadowRestSummary(station="SFO", climate_day="2026-09-16", leg="YES")
    second = ShadowRestSummary(station="MIA", climate_day="2026-09-16", leg="NO")

    path_one = write_shadow_rest_summaries(directory, [first], now_ns=_NOW_NS)
    path_two = write_shadow_rest_summaries(directory, [second], now_ns=_NOW_NS + 1)

    assert path_one != path_two
    assert path_one is not None and path_one.exists()
    assert path_two is not None and path_two.exists()
    read_back = read_shadow_rest_summaries(directory)
    assert {row.station for row in read_back} == {"SFO", "MIA"}


def test_read_on_a_missing_directory_returns_empty() -> None:
    assert read_shadow_rest_summaries(Path("/nonexistent/shadow_rest_dir_xyz")) == ()
