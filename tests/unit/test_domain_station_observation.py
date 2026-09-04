"""Unit tests for `StationObservation` -- BL-24 Seam A.

Mirrors the shape of `tests/unit/test_domain_archived_records.py` and
`tests/unit/test_domain_nws_climate_day.py`: the hand-written `Data`
subclass pattern, its timestamp semantics, and the strict `from_dict`
decode path.
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from breezy.domain.station_observation import StationObservation

_ROOT = Path(__file__).resolve().parents[2]

#: An arbitrary but fixed measurement instant, chosen in July so the fixed
#: standard-offset behaviour is distinguishable from a DST-following one.
_JULY_OBSERVED_AT_NS = int(
    dt.datetime(2026, 7, 15, 4, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)
_JULY_RECEIVED_AT_NS = _JULY_OBSERVED_AT_NS + 60_000_000_000  # +60s


def make_observation(**overrides: Any) -> StationObservation:
    kwargs: dict[str, Any] = {
        "station": "KNYC",
        "observed_at_ns": _JULY_OBSERVED_AT_NS,
        "received_at_ns": _JULY_RECEIVED_AT_NS,
        "temp_c_tenths": 250,
        "precision_c_tenths": 5,
        "is_metar": True,
        "source_channel": "iem_asos_metar",
        "assumed_publication_lag_ns": 30_000_000_000,
    }
    kwargs.update(overrides)
    return StationObservation(**kwargs)


def test_ts_init_is_the_received_instant_and_not_a_ctor_param() -> None:
    """`ts_init` derives from `received_at_ns`; there is no `ts_init` kwarg."""
    record = make_observation()
    assert record.ts_init == record.received_at_ns == _JULY_RECEIVED_AT_NS
    assert record.ts_event == record.observed_at_ns == _JULY_OBSERVED_AT_NS

    with pytest.raises(TypeError):
        make_observation(ts_init=1)
    with pytest.raises(TypeError):
        make_observation(ts_event=1)


@pytest.mark.parametrize("delta_ns", [0, -1])
def test_arrival_at_or_before_measurement_is_refused(delta_ns: int) -> None:
    """`received_at_ns <= observed_at_ns` is physically impossible and refused."""
    with pytest.raises(ValueError, match="received_at_ns"):
        make_observation(
            observed_at_ns=_JULY_OBSERVED_AT_NS,
            received_at_ns=_JULY_OBSERVED_AT_NS + delta_ns,
        )


def test_arrival_strictly_after_measurement_is_accepted() -> None:
    record = make_observation(
        observed_at_ns=_JULY_OBSERVED_AT_NS,
        received_at_ns=_JULY_OBSERVED_AT_NS + 1,
    )
    assert record.ts_init == _JULY_OBSERVED_AT_NS + 1


def test_iem_asos_metar_requires_a_positive_publication_lag() -> None:
    with pytest.raises(ValueError, match="assumed_publication_lag_ns"):
        make_observation(source_channel="iem_asos_metar", assumed_publication_lag_ns=0)
    with pytest.raises(ValueError, match="assumed_publication_lag_ns"):
        make_observation(source_channel="iem_asos_metar", assumed_publication_lag_ns=-1)


def test_nws_api_observations_requires_a_positive_publication_lag() -> None:
    """BL-24 Seam B section 1: the guard is WIDENED to the NWS channel, never relaxed."""
    with pytest.raises(ValueError, match="assumed_publication_lag_ns"):
        make_observation(source_channel="nws_api_observations", assumed_publication_lag_ns=0)
    with pytest.raises(ValueError, match="assumed_publication_lag_ns"):
        make_observation(source_channel="iem_asos_metar", assumed_publication_lag_ns=0)
    record = make_observation(
        source_channel="nws_api_observations",
        is_metar=False,
        precision_c_tenths=10,
        assumed_publication_lag_ns=1,
    )
    assert record.source_channel == "nws_api_observations"


def test_assumed_publication_lag_is_never_subtracted_from_observed_at() -> None:
    """Amendment A6: declared provenance only -- never folded into the instant."""
    record = make_observation(assumed_publication_lag_ns=999_000_000_000)
    assert record.observed_at_ns == _JULY_OBSERVED_AT_NS
    assert record.ts_event == _JULY_OBSERVED_AT_NS


def test_climate_day_uses_local_standard_time_not_utc() -> None:
    """NYC is UTC-5 standard; 04:00 UTC on 2026-07-15 is 2026-07-14 local."""
    record = make_observation(observed_at_ns=_JULY_OBSERVED_AT_NS)
    assert record.climate_day(std_utc_offset_hours=-5.0) == dt.date(2026, 7, 14)


def test_july_climate_day_uses_the_standard_offset_not_dst() -> None:
    """NYC observes EDT (UTC-4) in July; the climate day must still use -5.0.

    A 23:30 UTC instant is 19:30 EDT (still 2026-07-14) but 18:30 standard
    time (also still 2026-07-14) -- pick an instant where DST vs standard
    disagrees on the DATE to make the distinction load-bearing.
    """
    # 03:30 UTC on 2026-07-15 -> EDT (UTC-4) says 23:30 on 2026-07-14 (same
    # day either way); use 04:30 UTC instead: EDT -> 00:30 2026-07-15,
    # standard (-5) -> 23:30 2026-07-14. The two disagree on the date.
    observed_at_ns = int(
        dt.datetime(2026, 7, 15, 4, 30, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
    )
    record = make_observation(
        observed_at_ns=observed_at_ns,
        received_at_ns=observed_at_ns + 1,
    )
    assert record.climate_day(std_utc_offset_hours=-5.0) == dt.date(2026, 7, 14)


@pytest.mark.parametrize(
    "missing_column",
    [
        "station",
        "temp_c_tenths",
        "precision_c_tenths",
        "is_metar",
        "source_channel",
        "assumed_publication_lag_ns",
        "schema_version",
        "ts_event",
        "ts_init",
    ],
)
def test_from_dict_raises_on_a_missing_column(missing_column: str) -> None:
    values = make_observation().to_dict()
    del values[missing_column]

    with pytest.raises(KeyError):
        StationObservation.from_dict(values)


def test_from_dict_round_trips_to_dict() -> None:
    original = make_observation()
    restored = StationObservation.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_schema_carries_no_settlement_like_column() -> None:
    """No `tmax_f`/`tmin_f`/`tavg_f`/`is_final`-shaped column, and no derived

    Fahrenheit column at all -- see the module docstring's "No
    settlement-shaped column" section. This is a raw reading, not a
    settlement datum.
    """
    names = set(StationObservation.schema().names)
    forbidden = {"tmax_f", "tmin_f", "tavg_f", "is_final", "temp_f", "rounded_f"}
    assert names.isdisjoint(forbidden)


@pytest.mark.parametrize("precision_c_tenths", [0, -1, -5])
def test_precision_c_tenths_must_be_positive(precision_c_tenths: int) -> None:
    with pytest.raises(ValueError, match="precision_c_tenths"):
        make_observation(precision_c_tenths=precision_c_tenths)


def test_precision_c_tenths_and_is_metar_round_trip_through_to_dict() -> None:
    metar_record = make_observation(precision_c_tenths=5, is_metar=True)
    assert metar_record.precision_c_tenths == 5
    assert metar_record.is_metar is True
    restored = StationObservation.from_dict(metar_record.to_dict())
    assert restored.precision_c_tenths == 5
    assert restored.is_metar is True

    integer_row = make_observation(
        precision_c_tenths=10,
        is_metar=False,
        source_channel="nws_api_5min",
        assumed_publication_lag_ns=1,
    )
    assert integer_row.precision_c_tenths == 10
    assert integer_row.is_metar is False
    restored_integer = StationObservation.from_dict(integer_row.to_dict())
    assert restored_integer.precision_c_tenths == 10
    assert restored_integer.is_metar is False


def test_is_metar_rejects_a_non_bool() -> None:
    with pytest.raises(TypeError):
        make_observation(is_metar=1)


def test_module_registers_arrow_exactly_once() -> None:
    """Record mutant: adding a second module-scope `register_arrow` call."""
    tree = ast.parse((_ROOT / "src/breezy/domain/station_observation.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "register_arrow"
    ]
    assert len(calls) == 1
