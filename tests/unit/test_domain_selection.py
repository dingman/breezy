"""Unit tests for the max-`ts_init` supersession selector.

§4.3: corrections are new records with a strictly later `ts_init`, never a rewrite.
The reader therefore selects max-`ts_init` per `(station, climate_day)`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.selection import climate_day_key, latest_by_climate_day, select_climate_day

_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_BASE_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"seed").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2026, 8, 22),
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _BASE_NS - 240_000_000_000,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "sites.toml@1",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_key_is_station_and_climate_day() -> None:
    assert climate_day_key(make_climate_day()) == ("NYC", dt.date(2026, 8, 22))


def test_latest_wins_regardless_of_input_order() -> None:
    first = make_climate_day(tmax_f=84)
    correction = make_climate_day(
        tmax_f=85,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )

    for records in ([first, correction], [correction, first]):
        selected = latest_by_climate_day(records)
        assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 85


def test_stations_are_selected_independently() -> None:
    nyc = make_climate_day(station="NYC", tmax_f=84)
    mdw = make_climate_day(station="MDW", issuing_office="KLOT", tmax_f=91)

    selected = latest_by_climate_day([nyc, mdw])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 84
    assert selected[("MDW", dt.date(2026, 8, 22))].tmax_f == 91


def test_days_are_selected_independently() -> None:
    day22 = make_climate_day(climate_day=dt.date(2026, 8, 22), tmax_f=84)
    day23 = make_climate_day(
        climate_day=dt.date(2026, 8, 23),
        tmax_f=88,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )

    selected = latest_by_climate_day([day22, day23])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 84
    assert selected[("NYC", dt.date(2026, 8, 23))].tmax_f == 88


def test_equal_ts_init_breaks_the_tie_on_revision_seq() -> None:
    original = make_climate_day(tmax_f=84, revision_seq=1)
    same_instant = make_climate_day(tmax_f=85, revision_seq=2)

    selected = latest_by_climate_day([same_instant, original])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 85


def test_as_of_bound_reproduces_the_pre_correction_answer() -> None:
    """§4.4: post-hoc audit needs 'what would the resolver have said at time T'."""
    first = make_climate_day(tmax_f=84)
    correction = make_climate_day(
        tmax_f=85,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )
    records = [first, correction]

    assert select_climate_day(records, "NYC", dt.date(2026, 8, 22)).tmax_f == 85
    as_of = select_climate_day(
        records,
        "NYC",
        dt.date(2026, 8, 22),
        as_of_ts_init=_BASE_NS + 3_600_000_000_000,
    )
    assert as_of is not None
    assert as_of.tmax_f == 84


def test_as_of_bound_is_inclusive() -> None:
    record = make_climate_day()
    assert (
        select_climate_day(
            [record],
            "NYC",
            dt.date(2026, 8, 22),
            as_of_ts_init=_BASE_NS,
        )
        is record
    )


def test_as_of_before_any_arrival_selects_nothing() -> None:
    record = make_climate_day()
    assert (
        select_climate_day([record], "NYC", dt.date(2026, 8, 22), as_of_ts_init=_BASE_NS - 1)
        is None
    )


def test_unknown_key_selects_nothing() -> None:
    assert select_climate_day([make_climate_day()], "LAX", dt.date(2026, 8, 22)) is None


def test_empty_input_selects_nothing() -> None:
    assert latest_by_climate_day([]) == {}


def test_custom_data_wrappers_are_rejected_with_a_pointed_message() -> None:
    """`catalog.query`/`custom_data` return `CustomData`; callers must unwrap `.data`."""
    from nautilus_trader.model.data import CustomData, DataType

    wrapped = CustomData(DataType(NwsClimateDay), make_climate_day())
    with pytest.raises(TypeError, match="CustomData"):
        latest_by_climate_day([wrapped])  # type: ignore[list-item]
