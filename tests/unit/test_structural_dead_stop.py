"""RED-first tests for the v1 structural-dead stop (v1 PREREG section 5:105-106).

Ruling: `docs/evidence/grok_prereg_v2_ratification_2026-09-04.md`, Final
ruling (1)(f) and (3) "Allowed on v1" -- this stop is additive to the tally,
never a change to a registered threshold, BE computation,
`build_realized_stratum`, `break_even`, `FEE_THETA`, the Wilson z, the
60/150 floors, or `cell_dead`/`pooled_survive`.

Window [12:00, 17:00) LST, afternoon-covered >= 30 min of distinct captured
Depth10/quote instants (`ma_prelock_winner_ask_study.collect_window_instants`
/ `afternoon_coverage_minutes`, `MIN_AFTERNOON_STATION_DAYS`). "Listed" =
present in the discovered station-day set (a venue-skipped day never
appears there at all -- it is never captured, never discovered, and so
never enters the covered-listed count).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sds_mod() -> ModuleType:
    return _load_module("structural_dead_stop")


@pytest.fixture(scope="module")
def ma_mod() -> ModuleType:
    return _load_module("ma_prelock_winner_ask_study")


# ---------------------------------------------------------------------------
# The pure verdict function
# ---------------------------------------------------------------------------


def test_14_covered_days_0_fills_is_not_dead(sds_mod: ModuleType) -> None:
    verdict = sds_mod.structural_dead(covered_listed_station_days=14, filled_takes=0)
    assert verdict.structural_dead is False
    assert verdict.covered_listed_station_days == 14
    assert verdict.filled_takes == 0


def test_15_covered_days_0_fills_is_dead(sds_mod: ModuleType) -> None:
    verdict = sds_mod.structural_dead(covered_listed_station_days=15, filled_takes=0)
    assert verdict.structural_dead is True


def test_15_covered_days_1_fill_is_not_dead(sds_mod: ModuleType) -> None:
    """One fill defeats it -- not a Wilson take-rate test, no epsilon."""
    verdict = sds_mod.structural_dead(covered_listed_station_days=15, filled_takes=1)
    assert verdict.structural_dead is False


def test_unavailable_fill_time_count_is_never_evaluated_never_fires(
    sds_mod: ModuleType,
) -> None:
    """FAIL CLOSED: `filled_takes=None` means the fill-time source could not
    be counted (e.g. only settled/scored fills were reachable, which
    undercounts an unsettled Take) -- the stop must never fire on a count it
    cannot trust, no matter how large `covered_listed_station_days` is."""
    verdict = sds_mod.structural_dead(covered_listed_station_days=15, filled_takes=None)
    assert verdict.structural_dead is False
    assert verdict.evaluable is False


def test_a_zero_count_that_IS_available_is_still_evaluable(sds_mod: ModuleType) -> None:
    verdict = sds_mod.structural_dead(covered_listed_station_days=15, filled_takes=0)
    assert verdict.evaluable is True
    assert verdict.structural_dead is True


def test_the_floor_reuses_ma_prelock_min_afternoon_station_days(
    sds_mod: ModuleType, ma_mod: ModuleType
) -> None:
    """MIN_AFTERNOON_STATION_DAYS is imported, never re-declared as a literal."""
    assert sds_mod.MIN_STRUCTURAL_DEAD_STATION_DAYS == ma_mod.MIN_AFTERNOON_STATION_DAYS == 15
    source = (_SCRIPTS_ANALYSIS_DIR / "structural_dead_stop.py").read_text()
    assert "= 15" not in source.replace("MIN_STRUCTURAL_DEAD_STATION_DAYS", "")


# ---------------------------------------------------------------------------
# The covered-listed counting reader (pure core, injectable depth loader)
# ---------------------------------------------------------------------------


def _dep(ts_event: dt.datetime) -> object:
    return type(
        "Row",
        (),
        {"ts_event": ts_event, "best_ask": 0.5, "ask_ladder": None, "best_bid": 0.4},
    )()


def _depth_spanning_minutes(day: dt.date, minutes: float) -> dict[str, tuple[object, ...]]:
    start = dt.datetime.combine(day, dt.time(12, 5), tzinfo=dt.UTC)
    end = start + dt.timedelta(minutes=minutes)
    return {"INSTR": (_dep(start), _dep(end))}


def test_a_20_minute_span_is_not_covered(sds_mod: ModuleType) -> None:
    day = dt.date(2026, 8, 20)
    station_days = (("LAX", day),)

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 20.0)

    count = sds_mod.covered_listed_station_days(
        station_days=station_days,
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
    )
    assert count == 0


def test_a_30_minute_span_is_covered(sds_mod: ModuleType) -> None:
    day = dt.date(2026, 8, 20)
    station_days = (("LAX", day),)

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 30.0)

    count = sds_mod.covered_listed_station_days(
        station_days=station_days,
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
    )
    assert count == 1


def test_a_venue_skipped_day_is_excluded_because_it_is_never_in_the_discovered_set(
    sds_mod: ModuleType,
) -> None:
    """"Listed" = present in the discovered station-day set. A skip-day never
    appears there (never captured, never discovered), so it can never be
    passed into `station_days` in the first place -- this test asserts the
    counter only ever sees the days it is given, i.e. it performs no
    independent re-derivation of "listed" that could disagree with the
    discovery step."""
    covered_day = dt.date(2026, 8, 20)
    # The skipped day (2026-08-21) is simply absent from station_days --
    # exactly what `discover_station_days` would produce for a day the
    # venue never listed.
    station_days = (("LAX", covered_day),)

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 45.0)

    count = sds_mod.covered_listed_station_days(
        station_days=station_days,
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
    )
    assert count == 1


def _quote_tape_gap(
    city: str,
    day: dt.date,
    *,
    start_time: dt.time,
    end_time: dt.time,
) -> object:
    """A resolved QuoteTapeGap for one station-day."""
    start = dt.datetime.combine(day, start_time, tzinfo=dt.UTC)
    end = dt.datetime.combine(day, end_time, tzinfo=dt.UTC)
    return _quote_tape_gap_ns(
        city,
        day,
        started_ns=int(start.timestamp() * 1_000_000_000),
        ended_ns=int(end.timestamp() * 1_000_000_000),
    )


def _quote_tape_gap_ns(city: str, day: dt.date, *, started_ns: int, ended_ns: int) -> object:
    from nautilus_trader.model.identifiers import InstrumentId

    from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap

    token = f"tc-temp-{city.lower()}high-{day.isoformat()}-gte78lt80f"
    return QuoteTapeGap(
        instrument_id=InstrumentId.from_str(f"{token}.POLYMARKET_US"),
        gap_seq=1,
        started_ns=started_ns,
        ended_ns=ended_ns,
        resolved=True,
        recorder_instance_id="11111111-1111-1111-1111-111111111111",
        ts_event=started_ns,
        ts_init=ended_ns,
    )


def test_listed_day_with_afternoon_gap_is_not_covered(sds_mod: ModuleType) -> None:
    """Fixture (c): 15 listed tuples, 14 with a 30-min span, 1 overlapping a
    resolved QuoteTapeGap -- the outage day is listed but not covered."""
    days = tuple(dt.date(2026, 8, 20) + dt.timedelta(days=i) for i in range(15))
    station_days = tuple(("LAX", day) for day in days)
    outage_day = days[-1]

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 30.0)

    count = sds_mod.covered_listed_station_days(
        station_days=station_days,
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
        resolved_gaps=(_afternoon_gap("LAX", outage_day),),
    )
    assert count == 14


def _afternoon_gap(city: str, day: dt.date) -> object:
    """A resolved QuoteTapeGap whose interval sits inside [12:00, 17:00) LST."""
    return _quote_tape_gap(
        city,
        day,
        start_time=dt.time(13, 0),
        end_time=dt.time(14, 0),
    )


def test_gap_ending_exactly_at_afternoon_start_is_covered(sds_mod: ModuleType) -> None:
    day = dt.date(2026, 8, 20)

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 30.0)

    count = sds_mod.covered_listed_station_days(
        station_days=(("LAX", day),),
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
        resolved_gaps=(
            _quote_tape_gap(
                "LAX",
                day,
                start_time=dt.time(11, 0),
                end_time=dt.time(12, 0),
            ),
        ),
    )
    assert count == 1


def test_gap_starting_exactly_at_afternoon_end_is_covered(sds_mod: ModuleType) -> None:
    day = dt.date(2026, 8, 20)

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 30.0)

    count = sds_mod.covered_listed_station_days(
        station_days=(("LAX", day),),
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
        resolved_gaps=(
            _quote_tape_gap(
                "LAX",
                day,
                start_time=dt.time(17, 0),
                end_time=dt.time(18, 0),
            ),
        ),
    )
    assert count == 1


def test_gap_overlapping_afternoon_by_one_ns_is_not_covered(sds_mod: ModuleType) -> None:
    day = dt.date(2026, 8, 20)
    noon_ns = int(
        dt.datetime.combine(day, dt.time(12, 0), tzinfo=dt.UTC).timestamp()
        * 1_000_000_000
    )

    def loader(city: str, climate_day: dt.date) -> dict[str, tuple[object, ...]]:
        return _depth_spanning_minutes(climate_day, 30.0)

    count = sds_mod.covered_listed_station_days(
        station_days=(("LAX", day),),
        load_depth_for_day=loader,
        std_utc_offset_by_city={"LAX": 0.0},
        resolved_gaps=(
            _quote_tape_gap_ns(
                "LAX",
                day,
                started_ns=noon_ns - 1,
                ended_ns=noon_ns + 1,
            ),
        ),
    )
    assert count == 0


def test_unreadable_gap_partition_refuses_and_writes_no_output(
    sds_mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_root = tmp_path / "catalog"
    (catalog_root / "data" / "order_book_depths" / "tc-temp-laxhigh-2026-09-05-0").mkdir(
        parents=True
    )
    output_path = tmp_path / "covered.json"

    def _unreadable(_catalog: object) -> object:
        raise OSError("gap partition unreadable")

    monkeypatch.setattr(sds_mod, "load_partitioned_quote_tape_gaps", _unreadable)
    exit_code = sds_mod.main(
        ["--catalog-root", str(catalog_root), "--output", str(output_path)]
    )

    assert exit_code != 0
    assert not output_path.exists()


def test_absent_gap_partition_with_no_gap_rows_is_honestly_empty(
    sds_mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_root = tmp_path / "catalog"
    (catalog_root / "data" / "order_book_depths").mkdir(parents=True)
    output_path = tmp_path / "covered.json"

    class _EmptyPartitionedGaps:
        def values(self) -> tuple[object, ...]:
            return ()

    monkeypatch.setattr(
        sds_mod,
        "load_partitioned_quote_tape_gaps",
        lambda _catalog: _EmptyPartitionedGaps(),
    )
    exit_code = sds_mod.main(
        ["--catalog-root", str(catalog_root), "--output", str(output_path)]
    )

    assert exit_code == 0
    assert output_path.exists()
