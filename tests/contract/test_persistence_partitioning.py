"""Contract tests pinning WHY per-station separation must be a catalog root.

Each assertion below was observed by execution against nautilus-trader 1.231.0.
Together they close every alternative to one-root-per-station, so a future reader
cannot "simplify" `breezy.persistence.catalog` into a single shared catalog with a
filter. A failure here means the platform moved -- re-verify before changing
Breezy.

Scope note: `tests/contract/test_catalog_nws_records.py` pins the record types'
round-trip and the silent write-skip. This module pins the *partitioning* facts.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import CustomData

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, read_climate_days, write_records

pytestmark = pytest.mark.contract

_DAY = dt.date(2026, 8, 22)
_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"CDUS41 KOKX 230627").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_write_identifier_is_ignored_for_a_type_without_instrument_id(tmp_path: Path) -> None:
    """`write_data(identifier=...)` cannot separate stations.

    `identifier` is only consulted on the empty-data file-name-extension branch;
    for real records the identifier is derived from the objects, and a custom type
    with no `instrument_id` yields `None`. The rows land flat regardless.
    """
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    catalog.write_data([make_climate_day()], identifier="NYC")

    written = list(Path(catalog.path).rglob("*.parquet"))
    assert len(written) == 1
    assert written[0].parent.name == "custom_nws_climate_day"
    assert "NYC" not in str(written[0].relative_to(catalog.path))


def test_identifiers_filter_returns_nothing_for_our_types(tmp_path: Path) -> None:
    """`query(identifiers=[...])` matches on the identifier directory, which is absent."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day()])

    assert len(catalog.query(data_cls=NwsClimateDay)) == 1
    assert catalog.query(data_cls=NwsClimateDay, identifiers=["NYC"]) == []


def test_metadata_tags_the_wrapper_but_does_not_filter(tmp_path: Path) -> None:
    """Metadata is a routing tag, not a predicate.

    Two `BacktestDataConfig`s differing only by metadata therefore replay EVERY
    row twice -- the reason station separation cannot be expressed as metadata.
    """
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day(station="NYC")])

    as_nyc = catalog.query(data_cls=NwsClimateDay, metadata={"station": "NYC"})
    as_mdw = catalog.query(data_cls=NwsClimateDay, metadata={"station": "MDW"})

    assert len(as_nyc) == len(as_mdw) == 1
    assert isinstance(as_mdw[0], CustomData)
    assert as_mdw[0].data_type.metadata == {"station": "MDW"}
    assert as_mdw[0].data.station == "NYC", "metadata tagged the wrapper, not the row"


def test_custom_data_silently_drops_its_metadata_argument(tmp_path: Path) -> None:
    """`custom_data(metadata=...)` is consumed by the wrapper, not forwarded.

    `catalog/base.py:202-218`: `metadata` is a named parameter used ONLY on the
    `as_nautilus=True` branch, and `query` is called without it. So the default
    path returns wrappers tagged with `{}` while the caller believes it asked for
    something. `as_nautilus=True` is not the fix -- `query` already wraps custom
    classes, so it double-wraps. Read through `breezy.persistence.catalog`, which
    unwraps and never relies on either.
    """
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day(station="NYC")])

    results = catalog.custom_data(cls=NwsClimateDay, metadata={"station": "MDW"})

    assert results[0].data_type.metadata == {}, "the metadata argument was dropped"

    double_wrapped = catalog.custom_data(
        cls=NwsClimateDay,
        metadata={"station": "MDW"},
        as_nautilus=True,
    )
    assert isinstance(double_wrapped[0].data, CustomData), "as_nautilus double-wraps"


def test_separate_roots_are_the_only_working_separation(tmp_path: Path) -> None:
    """One shared root merges stations; one root per station does not."""
    base = tmp_path / "nws"
    nyc = make_climate_day(station="NYC", tmax_f=84)
    # A distinct `ts_init`, or the shared-root write would hit the silent
    # same-range skip instead of demonstrating the merge.
    mdw = make_climate_day(
        station="MDW",
        issuing_office="KLOT",
        tmax_f=91,
        retrieved_at_ns=_RETRIEVED_NS + 60_000_000_000,
    )

    shared = open_station_catalog(base, "polymarket_us", "SHARED")
    assert write_records(shared, [nyc]).is_complete
    assert write_records(shared, [mdw]).is_complete
    assert {r.station for r in read_climate_days(shared)} == {"NYC", "MDW"}

    nyc_catalog = open_station_catalog(base, "polymarket_us", "NYC")
    mdw_catalog = open_station_catalog(base, "polymarket_us", "MDW")
    write_records(nyc_catalog, [nyc])
    write_records(mdw_catalog, [mdw])

    assert {r.station for r in read_climate_days(nyc_catalog)} == {"NYC"}
    assert {r.station for r in read_climate_days(mdw_catalog)} == {"MDW"}


def test_station_roots_are_disjoint_directory_trees(tmp_path: Path) -> None:
    """No station's catalog may contain another's, or a parquet glob would merge them."""
    base = tmp_path / "nws"
    roots = [
        Path(open_station_catalog(base, "polymarket_us", city).path).resolve()
        for city in ("NYC", "MDW", "LAX", "MIA", "SFO")
    ]

    for outer in roots:
        for inner in roots:
            if outer is not inner:
                assert not inner.is_relative_to(outer)
