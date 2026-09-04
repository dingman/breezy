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
    return type("Row", (), {"ts_event": ts_event, "best_ask": 0.5, "ask_ladder": None, "best_bid": 0.4})()


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
