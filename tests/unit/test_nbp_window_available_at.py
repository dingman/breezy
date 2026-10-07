"""FB-R5: ``NbpPercentileWindow.available_at_ns`` is the max over the window's derived rows.

The field is added inside ``complete_percentile_windows`` (no separate side index). Other
constructors of the window (the existing tests build it by hand) must stay valid, and
``build_version_rows`` must be unaffected by the new field.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from scripts.analysis import nbp_skill_study
from tests.unit.test_nbp_skill_study import (
    _complete_window_rows,
    _cycle_runtime_ns,
    _d1_valid_ns_for_13z_or_19z,
)

_HOUR_NS = 3_600 * 10**9


def _window_rows(*, late_by_ns: int) -> list[object]:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    rows = _complete_window_rows(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_ns=_d1_valid_ns_for_13z_or_19z(day),
        q50=90.0,
    )
    # One variable arrives late (a later LastModified): the window is available only when ALL are.
    rows[3] = dataclasses.replace(rows[3], available_at_ns=cycle + late_by_ns)
    return list(rows)


def test_window_available_at_is_the_max_over_its_derived_rows() -> None:
    rows = _window_rows(late_by_ns=5 * _HOUR_NS)

    windows = nbp_skill_study.complete_percentile_windows(rows)  # type: ignore[arg-type]

    assert len(windows) == 1
    cycle = _cycle_runtime_ns(dt.date(2025, 6, 1), 13)
    assert windows[0].available_at_ns == cycle + 5 * _HOUR_NS


def test_window_available_at_defaults_to_none_for_hand_built_windows() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    rows = _complete_window_rows(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_ns=_d1_valid_ns_for_13z_or_19z(day),
        q50=90.0,
    )
    built = nbp_skill_study.complete_percentile_windows(rows)[0]

    by_hand = nbp_skill_study.NbpPercentileWindow(
        station=built.station,
        cycle_runtime_ns=built.cycle_runtime_ns,
        valid_start_ns=built.valid_start_ns,
        nbm_version_era=built.nbm_version_era,
        percentiles=built.percentiles,
    )

    assert by_hand.available_at_ns is None
    assert built.available_at_ns == cycle  # _derived_row stamps available_at_ns = cycle


def test_the_new_field_does_not_change_which_window_build_version_rows_selects() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    rows = _complete_window_rows(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_ns=_d1_valid_ns_for_13z_or_19z(day),
        q50=90.0,
    )
    windows = nbp_skill_study.complete_percentile_windows(rows)
    stripped = [dataclasses.replace(w, available_at_ns=None) for w in windows]
    registry = nbp_skill_study.station_registry(stations=("KMIA",))
    truth: dict[
        tuple[str, dt.date], object
    ] = {}  # no settlement rows: both paths must count the same single gap

    with_field = nbp_skill_study.build_version_rows(windows, truth, registry=registry)
    without = nbp_skill_study.build_version_rows(stripped, truth, registry=registry)

    assert with_field == without
