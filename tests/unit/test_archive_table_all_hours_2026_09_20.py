"""RED->GREEN: the archive `p_hold` table must be computable at EVERY LST hour.

Motivation: `docs/evidence/CONTINUOUS_HUNTING_GAP_2026-09-20.md`. The live
strategy's `[12:00, 17:00)` LST entry window is not a policy -- it is exactly
the coverage of the frozen archive table, whose only `hour_lst` keys are
`{12..16}`. Hunting outside that window is impossible because
`archive_table.P_HOLD_LOWER` has no cell there, so the take rule
`p_bound > price + fee` has no `p_bound` to compare.

The measurement half of the fix: the study and its generator must be able to
build cells at every hour the venue quotes (measured: all 24 LST hours carry
depth instants with a live ask -- see the WP report). This file pins the
widening WITHOUT touching the shipped artefact, the live window constants, or
`N_MIN`:

* a hour-selection option exists and DEFAULTS to the shipped five hours, so
  regenerating `src/.../archive_table.py` stays byte-identical;
* an under-powered cell at a newly-covered hour stays `None`, never `0.0`
  and never borrowed from a neighbouring hour;
* both Wilson bounds keep coming from the SAME interval call.
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


def _load(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mb() -> ModuleType:
    return _load("mb_current_rung_edge_study")


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return _load("generate_current_rung_hold_archive_table")


def _complete_day(mb: ModuleType, *, city: str, day: dt.date, running_f: int) -> object:
    """A complete 24h `RunningMaxDay` -- flat running max, so every hour is scorable."""
    return mb.RunningMaxDay(
        city=city,
        climate_day=day,
        running_max_f=tuple(running_f for _hour in range(24)),
        observed_max_f=running_f,
        observed_max_unrounded_f=float(running_f),
        hour_of_max=13,
        instant_of_max=dt.datetime.combine(day, dt.time(13, 0), tzinfo=dt.UTC),
        hour_of_rounded_max=13,
        observation_count=24,
        covered_hours=24,
    )


def test_all_quoted_hours_is_every_hour_of_the_local_standard_day(mb: ModuleType) -> None:
    """The venue quotes around the clock (measured), so the study's widened
    hour set is the whole LST day -- NOT a hand-picked sub-window."""
    assert mb.ALL_QUOTED_HOURS == tuple(range(24))
    assert "ALL_QUOTED_HOURS" in mb.__all__
    # The shipped five-hour set is untouched by the widening.
    assert mb.ARCHIVE_HOURS == (12, 13, 14, 15, 16)


def test_build_hold_cases_covers_every_quoted_hour_when_asked(mb: ModuleType) -> None:
    day = _complete_day(mb, city="MDW", day=dt.date(2021, 6, 15), running_f=50)
    cases = mb.build_hold_cases(day=day, settled_f=51, hours=mb.ALL_QUOTED_HOURS)

    assert {case.hour for case in cases} == set(range(24))
    assert len(cases) == 24 * 3


def test_an_under_powered_newly_covered_hour_stays_none_never_zero(mb: ModuleType) -> None:
    """Below `N_MIN` the bound is UNDEFINED -- the whole point of widening
    honestly. Ten days is far below 90, so every 03 LST cell must be `None`."""
    days = tuple(
        _complete_day(mb, city="MDW", day=dt.date(2021, 6, 1) + dt.timedelta(days=i), running_f=50)
        for i in range(10)
    )
    finals = {day.climate_day: 51 for day in days}
    table = mb.build_archive_table(
        {"MDW": days}, {"MDW": finals}, hours=mb.ALL_QUOTED_HOURS
    )

    assert {key[2] for key in table} == set(range(24))
    for key, cell in table.items():
        assert cell.n == 10
        assert cell.p_hold_lower is None, f"{key} fabricated a lower bound below N_MIN"
        assert cell.p_hold_upper is None, f"{key} fabricated an upper bound below N_MIN"
    assert mb.N_MIN == 90


def test_a_powered_newly_covered_hour_keeps_both_bounds_from_one_interval(
    mb: ModuleType,
) -> None:
    days = tuple(
        _complete_day(mb, city="MDW", day=dt.date(2021, 6, 1) + dt.timedelta(days=i), running_f=50)
        for i in range(100)
    )
    finals = {day.climate_day: 51 for day in days}
    table = mb.build_archive_table(
        {"MDW": days}, {"MDW": finals}, hours=mb.ALL_QUOTED_HOURS
    )
    cell = table[("MDW", "JJA", 3, mb.WIDTH_INTERIOR, 0)]

    # 100 days from 2021-06-01 straddle the JJA/SON boundary; JJA keeps 92.
    assert cell.n == 92 >= mb.N_MIN
    assert cell.p_hold_lower is not None and cell.p_hold_upper is not None
    assert cell.p_hold_lower <= cell.p_hold_upper
    assert (cell.p_hold_lower, cell.p_hold_upper) == mb.wilson_interval(
        cell.hold_count, cell.n
    )


def test_the_generator_hours_option_defaults_to_the_shipped_window(
    generator: ModuleType, mb: ModuleType
) -> None:
    """Default MUST stay the shipped five hours: the byte-identical
    regeneration test for `src/.../archive_table.py` depends on it."""
    assert generator.parse_hours(None) == mb.ARCHIVE_HOURS
    assert generator._parse_args([]).hours is None


def test_the_generator_hours_option_parses_sorts_and_dedupes(generator: ModuleType) -> None:
    assert generator.parse_hours("3,1,1,23") == (1, 3, 23)
    assert generator.parse_hours("0-23") == tuple(range(24))
    assert generator._parse_args(["--hours", "0-23"]).hours == "0-23"


@pytest.mark.parametrize("bad", ["", "24", "-1", "12,24", "noon", "5-4"])
def test_the_generator_rejects_an_hour_outside_the_local_standard_day(
    generator: ModuleType, bad: str
) -> None:
    with pytest.raises(SystemExit):
        generator.parse_hours(bad)


def test_a_widened_run_refuses_to_overwrite_the_shipped_artefact(
    generator: ModuleType,
) -> None:
    """Publishing a widened table changes a registered selector's estimand
    (L-34, class C). The generator must not let a `--hours` run quietly
    replace `src/.../archive_table.py` under the live strategy's feet."""
    with pytest.raises(SystemExit) as excinfo:
        generator.main(["--hours", "0-23"])

    assert "refusing to overwrite the SHIPPED artefact" in str(excinfo.value)
    assert generator.DEFAULT_OUTPUT.name == "archive_table.py"
