"""Parity goldens for the shared location-correction math (FQ go-live S1).

The floats in ``location_correction_parity_goldens.f64`` were captured from
the pre-move functions, before ``daylight_hours`` /
``correction_prediction_f`` / ``CorrectionForm`` /
``emos_params_from_draw_entry`` lived in
``breezy.strategy.ladder_ev.location_correction``:

* ``scripts/analysis/nbp_skill_study._daylight_hours``
* ``breezy.analysis.nbp_calibration.apply_correction_form`` with
  ``CorrectionForm.LINEAR_DAYLENGTH``
* ``breezy.analysis.nbp_calibration._correction_prediction``

Stations are KLAX, KSFO, KMDW, KMIA. Days are every climate day of 2025 and
2026 (neither is a leap year: 730 days). Per station-day the record is
``(daylight_hours, applied_residual, prediction)`` as little-endian
float64. The linear coefficients are the SL-8f selection printed in
``docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md``. ``residual_f`` is
the fixed input 1.25. Equality is exact, not approximate.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import struct
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from breezy.analysis import nbp_calibration as calib
from breezy.analysis.nbp_calibration import (
    CorrectionFitRow,
    CorrectionSelection,
    _correction_prediction,
    apply_correction_form,
)
from breezy.strategy.ladder_ev.location_correction import (
    CorrectionForm,
    correction_prediction_f,
    daylight_hours,
    emos_params_from_draw_entry,
)
from breezy.strategy.ladder_ev.quantile_density import EmosParams

_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KSFO", "KMDW", "KMIA")
_LINEAR_COEFFICIENTS: Final[tuple[float, float]] = (-0.3983509175275623, 4.281481160946798)
_RESIDUAL_F: Final[float] = 1.25
_N_DAYS: Final[int] = 730
_SERIES: Final[int] = 3  # daylight, applied residual, prediction
_GOLDEN_PATH: Final[Path] = Path(__file__).with_name("location_correction_parity_goldens.f64")

_MODULE_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_skill_study.py"
)
_spec = importlib.util.spec_from_file_location(
    "nbp_skill_study_location_correction_parity",
    _MODULE_PATH,
)
assert _spec is not None and _spec.loader is not None
nbp_skill_study: Any = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nbp_skill_study
_spec.loader.exec_module(nbp_skill_study)


def _climate_days() -> tuple[dt.date, ...]:
    days: list[dt.date] = []
    day = dt.date(2025, 1, 1)
    last = dt.date(2026, 12, 31)
    while day <= last:
        days.append(day)
        day += dt.timedelta(days=1)
    return tuple(days)


def _goldens() -> tuple[float, ...]:
    raw = _GOLDEN_PATH.read_bytes()
    count = len(_STATIONS) * _N_DAYS * _SERIES
    if len(raw) != count * 8:
        raise AssertionError(f"golden file is {len(raw)} bytes, expected {count * 8}")
    unpacked = struct.unpack(f"<{count}d", raw)
    return cast(tuple[float, ...], unpacked)


def _latitude(station: str) -> float:
    latitudes = cast(Mapping[str, float], nbp_skill_study._station_latitudes())
    return latitudes[station]


def _study_daylight(station: str, day: dt.date) -> float:
    value: object = nbp_skill_study._daylight_hours(station, day)
    if not isinstance(value, float):
        raise TypeError(f"_daylight_hours({station!r}, {day}) returned {value!r}")
    return value


def test_daylight_and_linear_correction_match_the_pre_move_goldens() -> None:
    days = _climate_days()
    assert len(days) == _N_DAYS
    expected = _goldens()
    selection = CorrectionSelection(
        form=CorrectionForm.LINEAR_DAYLENGTH,
        linear_coefficients=_LINEAR_COEFFICIENTS,
    )
    index = 0
    for station in _STATIONS:
        latitude = _latitude(station)
        for day in days:
            daylight_golden = expected[index]
            applied_golden = expected[index + 1]
            prediction_golden = expected[index + 2]
            index += _SERIES
            daylight = _study_daylight(station, day)
            where = (station, day.isoformat())
            assert daylight == daylight_golden, where
            assert daylight_hours(latitude, day) == daylight_golden, where
            applied = apply_correction_form(
                CorrectionForm.LINEAR_DAYLENGTH,
                residual_f=_RESIDUAL_F,
                month=day.month,
                day_length_hours=daylight,
                linear_coefficients=_LINEAR_COEFFICIENTS,
            )
            assert applied == applied_golden, where
            prediction = _correction_prediction(
                selection,
                CorrectionFitRow(
                    split="validate",
                    climate_day=day,
                    residual_f=_RESIDUAL_F,
                    day_length_hours=daylight,
                    scale_f=1.0,
                ),
            )
            assert prediction == prediction_golden, where
            assert (
                correction_prediction_f(
                    CorrectionForm.LINEAR_DAYLENGTH,
                    month=day.month,
                    day_length_hours=daylight,
                    linear_coefficients=_LINEAR_COEFFICIENTS,
                )
                == prediction_golden
            ), where
            assert applied == _RESIDUAL_F - prediction, where
    assert index == len(expected)


def test_correction_form_is_the_shared_enum() -> None:
    assert calib.CorrectionForm is CorrectionForm


def test_two_and_three_element_draw_entries_parse_identically() -> None:
    """A 2-element ``[a, gamma]`` entry with ``fallback_delta`` parses as the
    same ``EmosParams`` as a 3-element ``[a, gamma, delta]`` entry, and the
    analysis wrapper agrees with the shared parser on both shapes. A
    3-element entry keeps its own delta when it differs from the fallback.
    """
    two_analysis = calib.emos_params_from_draw_entry((0.3, 0.1), fallback_delta=1.4)
    three_analysis = calib.emos_params_from_draw_entry((0.3, 0.1, 1.4), fallback_delta=9.0)
    two_shared = emos_params_from_draw_entry((0.3, 0.1), fallback_delta=1.4)
    three_shared = emos_params_from_draw_entry((0.3, 0.1, 1.4), fallback_delta=9.0)
    expected = EmosParams(a=0.3, gamma=0.1, delta=1.4)
    assert two_analysis == expected
    assert three_analysis == expected
    assert two_shared == expected
    assert three_shared == expected
    own_delta = EmosParams(a=0.3, gamma=0.1, delta=0.5)
    assert emos_params_from_draw_entry((0.3, 0.1, 0.5), fallback_delta=1.4) == own_delta
    assert calib.emos_params_from_draw_entry((0.3, 0.1, 0.5), fallback_delta=1.4) == own_delta
